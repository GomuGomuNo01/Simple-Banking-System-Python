"""Business rules shared by the banking application and the activity simulation.

Keeping the rules in one place guarantees that simulated data follows exactly
the same logic as the real application (same checks, same order, same
failure reasons written to the operation log).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from . import luhn


class FailureReason(StrEnum):
    WRONG_PIN = "WRONG_PIN"
    UNKNOWN_CARD = "UNKNOWN_CARD"
    INVALID_CARD_NUMBER = "INVALID_CARD_NUMBER"
    SAME_ACCOUNT = "SAME_ACCOUNT"
    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: int
    card_number: str
    balance: object  # Decimal in the application, integer cents in the simulation
    is_active: bool


AccountLookup = Callable[[str], AccountSnapshot | None]


def validate_card_input(card_input: str) -> FailureReason | None:
    """Format and Luhn check, done before any database lookup."""
    if len(card_input) != luhn.CARD_LENGTH or not luhn.is_valid(card_input):
        return FailureReason.INVALID_CARD_NUMBER
    return None


def validate_amount(amount) -> FailureReason | None:
    return FailureReason.INVALID_AMOUNT if amount <= 0 else None


def check_login(
    card_input: str,
    pin_matches: Callable[[AccountSnapshot], bool],
    find_account: AccountLookup,
) -> tuple[FailureReason | None, AccountSnapshot | None]:
    if reason := validate_card_input(card_input):
        return reason, None
    account = find_account(card_input)
    if account is None:
        return FailureReason.UNKNOWN_CARD, None
    if not account.is_active:
        return FailureReason.ACCOUNT_CLOSED, account
    if not pin_matches(account):
        return FailureReason.WRONG_PIN, account
    return None, account


def check_debit(balance, amount) -> FailureReason | None:
    """Rule for withdrawals and card payments."""
    if reason := validate_amount(amount):
        return reason
    return FailureReason.INSUFFICIENT_FUNDS if amount > balance else None


def check_transfer(
    sender: AccountSnapshot,
    target_input: str,
    amount,
    find_account: AccountLookup,
) -> tuple[FailureReason | None, AccountSnapshot | None]:
    """Return (failure reason or None, resolved target account)."""
    if reason := validate_card_input(target_input):
        return reason, None
    if target_input == sender.card_number:
        return FailureReason.SAME_ACCOUNT, None
    target = find_account(target_input)
    if target is None:
        return FailureReason.UNKNOWN_CARD, None
    if not target.is_active:
        return FailureReason.ACCOUNT_CLOSED, target
    return check_debit(sender.balance, amount), target
