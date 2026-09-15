"""Banking service: every operation is validated, logged and executed atomically.

Design choices
- Each attempt, successful or not, is written to `operation_log`: the log is
  the raw material of the operational quality analysis.
- Money movements are written to `transactions` in the same database
  transaction as the balance update (all or nothing).
- Rows are locked with SELECT ... FOR UPDATE, always in account_id order,
  so two simultaneous transfers cannot corrupt balances or deadlock.
- Queries are parameterised (%s placeholders) to prevent SQL injection.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pymysql

from . import luhn, security
from .rules import (
    AccountSnapshot,
    FailureReason,
    check_debit,
    check_login,
    check_transfer,
    validate_amount,
)

MESSAGES = {
    FailureReason.WRONG_PIN: "Numéro de carte ou code PIN incorrect.",
    FailureReason.UNKNOWN_CARD: "Cette carte n'existe pas.",
    FailureReason.INVALID_CARD_NUMBER: "Numéro de carte invalide (erreur de saisie probable).",
    FailureReason.SAME_ACCOUNT: "Vous ne pouvez pas virer de l'argent vers le même compte.",
    FailureReason.ACCOUNT_CLOSED: "Ce compte est clôturé.",
    FailureReason.INVALID_AMOUNT: "Le montant doit être strictement positif.",
    FailureReason.INSUFFICIENT_FUNDS: "Solde insuffisant.",
}

_ACCOUNT_COLUMNS = "account_id, card_number, balance, status = 'ACTIVE' AS is_active"


class OperationError(Exception):
    def __init__(self, reason: FailureReason):
        super().__init__(MESSAGES[reason])
        self.reason = reason


@dataclass(frozen=True)
class Session:
    account_id: int
    card_number: str


class BankService:
    def __init__(self, conn: pymysql.connections.Connection, clock: Callable[[], datetime] = datetime.now):
        self.conn = conn
        self.clock = clock

    # ------------------------------------------------------------------ helpers
    def _now(self) -> datetime:
        return self.clock().replace(microsecond=0)

    @staticmethod
    def _snapshot(row) -> AccountSnapshot:
        return AccountSnapshot(row[0], row[1], row[2], bool(row[3]))

    def _find_by_card(self, cursor, card_number: str, lock: bool = False) -> AccountSnapshot | None:
        suffix = " FOR UPDATE" if lock else ""
        cursor.execute(f"SELECT {_ACCOUNT_COLUMNS} FROM accounts WHERE card_number = %s{suffix}", (card_number,))
        row = cursor.fetchone()
        return self._snapshot(row) if row else None

    def _log(self, cursor, account_id, event_type, reason=None, amount=None, channel="APP") -> int:
        cursor.execute(
            "INSERT INTO operation_log (account_id, event_type, status, failure_reason, channel,"
            " amount_requested, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (account_id, event_type, "FAILED" if reason else "SUCCESS", reason, channel, amount, self._now()),
        )
        return cursor.lastrowid

    def _record_transaction(self, cursor, operation_id, txn_type, from_id, to_id, amount) -> None:
        cursor.execute(
            "INSERT INTO transactions (operation_id, txn_type, from_account_id, to_account_id, amount, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (operation_id, txn_type, from_id, to_id, amount, self._now()),
        )

    def _fail(self, cursor, account_id, event_type, reason: FailureReason, amount=None):
        """Undo pending changes, keep a trace of the failed attempt, then raise."""
        self.conn.rollback()
        self._log(cursor, account_id, event_type, reason, amount)
        self.conn.commit()
        raise OperationError(reason)

    def _change_balance(self, cursor, account_id: int, delta: Decimal) -> None:
        cursor.execute("UPDATE accounts SET balance = balance + %s WHERE account_id = %s", (delta, account_id))

    # --------------------------------------------------------------- operations
    def create_account(self, first_name: str, last_name: str, email: str) -> tuple[str, str]:
        """Open an account for a new or existing customer. Returns (card number, PIN)."""
        now = self._now()
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT customer_id FROM customers WHERE email = %s", (email.strip().lower(),))
            row = cursor.fetchone()
            if row:
                customer_id = row[0]
            else:
                cursor.execute(
                    "INSERT INTO customers (first_name, last_name, email, signup_channel, crm_updated_at)"
                    " VALUES (%s, %s, %s, 'WEB', %s)",
                    (first_name.strip().title(), last_name.strip().title(), email.strip().lower(), now),
                )
                customer_id = cursor.lastrowid

            pin = security.generate_pin()
            pin_hash = security.hash_pin(pin)
            while True:
                card_number = luhn.generate_card_number()
                cursor.execute("SELECT 1 FROM accounts WHERE card_number = %s", (card_number,))
                if cursor.fetchone() is None:
                    break
            cursor.execute(
                "INSERT INTO accounts (customer_id, card_number, pin_hash, opened_at) VALUES (%s, %s, %s, %s)",
                (customer_id, card_number, pin_hash, now),
            )
            self._log(cursor, cursor.lastrowid, "CREATE_ACCOUNT")
        self.conn.commit()
        return card_number, pin

    def login(self, card_input: str, pin: str) -> Session:
        with self.conn.cursor() as cursor:
            cursor.execute(
                f"SELECT {_ACCOUNT_COLUMNS}, pin_hash FROM accounts WHERE card_number = %s", (card_input,)
            )
            row = cursor.fetchone()
            pin_hash = row[4] if row else ""
            reason, account = check_login(
                card_input,
                pin_matches=lambda _: security.verify_pin(pin, pin_hash),
                find_account=lambda _: self._snapshot(row) if row else None,
            )
            if reason:
                self._fail(cursor, account.account_id if account else None, "LOGIN", reason)
            self._log(cursor, account.account_id, "LOGIN")
        self.conn.commit()
        return Session(account.account_id, account.card_number)

    def get_balance(self, session: Session) -> Decimal:
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT balance FROM accounts WHERE account_id = %s", (session.account_id,))
            balance = cursor.fetchone()[0]
            self._log(cursor, session.account_id, "BALANCE_INQUIRY")
        self.conn.commit()
        return balance

    def deposit(self, session: Session, amount: Decimal) -> None:
        with self.conn.cursor() as cursor:
            if reason := validate_amount(amount):
                self._fail(cursor, session.account_id, "DEPOSIT", reason, amount)
            operation_id = self._log(cursor, session.account_id, "DEPOSIT", amount=amount)
            self._change_balance(cursor, session.account_id, amount)
            self._record_transaction(cursor, operation_id, "DEPOSIT", None, session.account_id, amount)
        self.conn.commit()

    def withdraw(self, session: Session, amount: Decimal) -> None:
        with self.conn.cursor() as cursor:
            account = self._find_by_card(cursor, session.card_number, lock=True)
            if reason := check_debit(account.balance, amount):
                self._fail(cursor, session.account_id, "WITHDRAWAL", reason, amount)
            operation_id = self._log(cursor, session.account_id, "WITHDRAWAL", amount=amount)
            self._change_balance(cursor, session.account_id, -amount)
            self._record_transaction(cursor, operation_id, "WITHDRAWAL", session.account_id, None, amount)
        self.conn.commit()

    def transfer(self, session: Session, target_card: str, amount: Decimal) -> None:
        with self.conn.cursor() as cursor:
            target = self._find_by_card(cursor, target_card) if luhn.is_valid(target_card) else None
            ids = sorted({session.account_id} | ({target.account_id} if target else set()))
            placeholders = ", ".join(["%s"] * len(ids))
            cursor.execute(
                f"SELECT {_ACCOUNT_COLUMNS} FROM accounts WHERE account_id IN ({placeholders})"
                " ORDER BY account_id FOR UPDATE",
                ids,
            )
            locked = {snap.card_number: snap for snap in map(self._snapshot, cursor.fetchall())}
            sender = locked[session.card_number]
            reason, resolved = check_transfer(sender, target_card, amount, locked.get)
            if reason:
                self._fail(cursor, sender.account_id, "TRANSFER", reason, amount)
            operation_id = self._log(cursor, sender.account_id, "TRANSFER", amount=amount)
            self._change_balance(cursor, sender.account_id, -amount)
            self._change_balance(cursor, resolved.account_id, amount)
            self._record_transaction(cursor, operation_id, "TRANSFER", sender.account_id, resolved.account_id, amount)
        self.conn.commit()

    def close_account(self, session: Session) -> Decimal:
        """Pay out the remaining balance, then close the account.

        The account is closed (status + date), not deleted: its history stays
        available for audit and analysis.
        """
        with self.conn.cursor() as cursor:
            balance = self._find_by_card(cursor, session.card_number).balance
        if balance > 0:
            self.withdraw(session, balance)
        with self.conn.cursor() as cursor:
            cursor.execute(
                "UPDATE accounts SET status = 'CLOSED', closed_at = %s WHERE account_id = %s",
                (self._now(), session.account_id),
            )
            self._log(cursor, session.account_id, "CLOSE_ACCOUNT")
        self.conn.commit()
        return balance
