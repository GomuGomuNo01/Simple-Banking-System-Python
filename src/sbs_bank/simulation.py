"""Behaviour-driven simulation of 18 months of SBS Bank activity.

Why a simulation?
Real banking data is confidential. Instead of random rows, this module models
customer behaviours (salaried, occasional user, saver, churner, never
activated), then replays every intention in chronological order through the
business rules of `rules.py`. Balances, refusals and typing errors therefore
emerge from the rules instead of being written by hand, and the dataset stays
internally consistent (balances always equal the sum of transactions).

Outputs (data/raw/)
- customers_crm_export.csv   CRM export, deliberately messy (cleaned in SQL)
- accounts.csv, operation_log.csv, transactions.csv   operational extracts
"""

from __future__ import annotations

import csv
import random
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from faker import Faker

from . import luhn, security
from .rules import AccountSnapshot, FailureReason, check_debit, check_login, check_transfer

START = datetime(2025, 1, 1)
END = datetime(2026, 6, 30, 23, 59, 59)

# The application uses 600 000 PBKDF2 iterations. Hashing thousands of PINs with
# that work factor would take minutes, so simulated accounts use a lower one
# (the iteration count is stored in each hash, both coexist safely).
SIMULATION_PIN_ITERATIONS = 1_000

CITIES = {
    "Paris": 22, "Lyon": 9, "Marseille": 8, "Toulouse": 7, "Lille": 6, "Bordeaux": 6, "Nantes": 6,
    "Strasbourg": 5, "Montpellier": 5, "Rennes": 5, "Nice": 4, "Grenoble": 4, "Saint-Étienne": 3,
    "Dijon": 3, "Angers": 3, "Reims": 3,
}
EMAIL_DOMAINS = {"gmail.com": 45, "outlook.fr": 18, "yahoo.fr": 12, "orange.fr": 10, "free.fr": 8, "laposte.net": 7}

AGE_BANDS = [((18, 24), 0.18), ((25, 34), 0.34), ((35, 44), 0.22), ((45, 54), 0.13), ((55, 64), 0.08), ((65, 80), 0.05)]
CHANNEL_MIX_BY_AGE = {  # MOBILE, WEB, PARTNER
    "young": (0.74, 0.20, 0.06),
    "middle": (0.55, 0.33, 0.12),
    "senior": (0.33, 0.45, 0.22),
}
PERSONA_MIX_BY_CHANNEL = {  # salaried, occasional, saver, churner, inactive
    "MOBILE": (0.43, 0.23, 0.08, 0.16, 0.10),
    "WEB": (0.41, 0.23, 0.12, 0.12, 0.12),
    "PARTNER": (0.24, 0.22, 0.06, 0.18, 0.30),
}
PERSONAS = ("salaried", "occasional", "saver", "churner", "inactive")


@dataclass(frozen=True)
class Persona:
    payments: float          # card payments per month
    top_ups: float           # deposits made in the app per month
    top_up_median: float     # EUR
    transfers: float
    withdrawals: float
    balance_checks: float
    spend_factor: float      # multiplier on card payment amounts
    monthly_churn: float     # probability of becoming inactive each month
    close_probability: float # probability that an inactive customer closes the account


PERSONA_PARAMS = {
    "salaried": Persona(16, 0.3, 150, 1.8, 0.8, 3.0, 1.0, 0.008, 0.25),
    "occasional": Persona(5, 1.3, 180, 0.8, 0.3, 1.5, 0.9, 0.020, 0.25),
    "saver": Persona(2.5, 1.0, 1200, 0.3, 0.15, 2.0, 1.2, 0.006, 0.20),
    "churner": Persona(6, 1.1, 150, 0.7, 0.3, 1.5, 1.0, 0.0, 0.55),
}

# category: (weight, median amount EUR, lognormal sigma)
CATEGORIES = {
    "GROCERIES": (30, 38, 0.6), "RESTAURANTS": (17, 22, 0.5), "TRANSPORT": (14, 15, 0.7),
    "ONLINE_SHOPPING": (13, 45, 0.8), "UTILITIES": (6, 35, 0.4), "LEISURE": (9, 28, 0.7),
    "HEALTH": (5, 25, 0.6), "TRAVEL": (3, 180, 0.7), "OTHER": (3, 20, 0.8),
}
PAYMENT_SEASONALITY = {1: 0.92, 2: 0.90, 3: 1.0, 4: 1.0, 5: 1.02, 6: 1.05, 7: 1.10, 8: 1.05, 9: 1.0, 10: 1.0, 11: 1.08, 12: 1.30}
PAYMENT_HOURS = [0.2, 0.1, 0.05, 0.05, 0.05, 0.1, 0.3, 0.8, 1.5, 2, 2.3, 2.8, 4, 3.5, 2.5, 2.3, 2.5, 3.2, 4, 3.8, 3, 2, 1.2, 0.6]
APP_HOURS = [0.2, 0.1, 0.05, 0.05, 0.05, 0.1, 0.5, 1.5, 2, 2, 2, 2.2, 3, 2.5, 2, 2, 2.2, 2.6, 3, 3.3, 3.5, 3, 2, 1]

# Human error rates
P_LOGIN_CARD_TYPO = 0.02
P_WRONG_PIN = 0.035
P_TRANSFER_SAME_CARD = 0.004
P_TRANSFER_TYPO = 0.045
P_TRANSFER_WRONG_CARD = 0.004  # a valid-looking number that belongs to nobody (wrong copy-paste)
P_INVALID_AMOUNT = 0.003
P_TRANSFER_OVERSHOOT = 0.06    # customer asks more than the balance


@dataclass
class SimAccount:
    account_id: int
    customer_id: int
    card_number: str
    pin_hash: str
    persona: str
    channel: str
    opened_at: datetime
    balance: int = 0  # cents
    is_active: bool = True
    closed_at: datetime | None = None
    engaged_until: datetime | None = None  # end of the period during which the customer uses the account
    contacts: list[int] = field(default_factory=list)

    def snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(self.account_id, self.card_number, self.balance, self.is_active)


def cents_to_str(cents: int | None) -> str:
    return "" if cents is None else f"{cents // 100}.{cents % 100:02d}"


def month_starts(start: datetime, end: datetime):
    current = datetime(start.year, start.month, 1)
    while current <= end:
        yield current
        current = datetime(current.year + (current.month == 12), current.month % 12 + 1, 1)


def ascii_slug(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(ch for ch in normalized.lower() if ch.isalnum())


class Simulation:
    def __init__(self, n_customers: int = 1800, seed: int = 42, start: datetime = START, end: datetime = END):
        self.n_customers = n_customers
        self.start, self.end = start, end
        self.rng = np.random.default_rng(seed)
        self.py_rng = random.Random(seed)
        self.faker = Faker("fr_FR")
        self.faker.seed_instance(seed)

        self.customers: list[dict] = []
        self.accounts: list[SimAccount] = []
        self.accounts_by_card: dict[str, SimAccount] = {}
        self.opened_ids: list[int] = []
        self.intents: list[tuple] = []
        self.operations: list[tuple] = []
        self.transactions: list[tuple] = []

    # ================================================================ helpers
    def _choice(self, options, weights):
        weights = np.asarray(weights, dtype=float)
        return options[self.rng.choice(len(options), p=weights / weights.sum())]

    def _random_time(self, window_start: datetime, window_end: datetime, hours: list[float]) -> datetime | None:
        """Random moment in the window following an hourly activity profile."""
        days = (window_end.date() - window_start.date()).days
        day = window_start.date() + timedelta(days=int(self.rng.integers(0, days + 1)))
        hour = self._choice(list(range(24)), hours)
        moment = datetime(day.year, day.month, day.day, hour, int(self.rng.integers(60)), int(self.rng.integers(60)))
        return moment if window_start <= moment <= window_end else None

    def _push(self, moment: datetime | None, kind: str, account: SimAccount, payload=None) -> None:
        if moment is not None and moment <= self.end:
            moment = moment.replace(microsecond=0)
            self.intents.append((moment, len(self.intents), kind, account.account_id, payload))

    # ======================================================= customers & accounts
    def _name(self, generator) -> str:
        # Simple names only: compound names would need extra cleaning rules.
        while True:
            value = generator()
            if value.isalpha():
                return value

    def build_customers(self) -> None:
        months = list(month_starts(self.start, self.end))
        weights = []
        for index, month in enumerate(months):
            weight = 1 + 0.06 * index
            weight *= {(2025, 8): 0.75, (2025, 9): 1.9, (2025, 10): 1.3, (2025, 12): 0.85, (2026, 1): 1.25}.get(
                (month.year, month.month), 1
            )
            weights.append(weight)
        per_month = self.rng.multinomial(self.n_customers, np.asarray(weights) / sum(weights))

        used_emails: set[str] = set()
        customer_id = 10_001
        for month, count in zip(months, per_month):
            next_month = datetime(month.year + (month.month == 12), month.month % 12 + 1, 1)
            for _ in range(count):
                opened_at = month + (next_month - month) * float(self.rng.random())
                opened_at = min(opened_at.replace(microsecond=0), self.end - timedelta(days=1))
                (low, high) = AGE_BANDS[self.rng.choice(len(AGE_BANDS), p=[w for _, w in AGE_BANDS])][0]
                age = int(self.rng.integers(low, high + 1))
                birth_date = opened_at.date() - timedelta(days=int(age * 365.25 + self.rng.integers(0, 365)))
                age_group = "young" if age < 30 else "middle" if age < 50 else "senior"
                channel = self._choice(("MOBILE", "WEB", "PARTNER"), CHANNEL_MIX_BY_AGE[age_group])

                mix = list(PERSONA_MIX_BY_CHANNEL[channel])
                if age >= 45:  # older customers save more
                    mix[1] -= 0.06
                    mix[2] += 0.06
                elif age <= 24:  # students: fewer salaries
                    mix[0] -= 0.10
                    mix[1] += 0.10
                persona = self._choice(PERSONAS, mix)

                first_name = self._name(self.faker.first_name)
                last_name = self._name(self.faker.last_name)
                base = f"{ascii_slug(first_name)}.{ascii_slug(last_name)}"
                domain = self._choice(list(EMAIL_DOMAINS), list(EMAIL_DOMAINS.values()))
                email, suffix = f"{base}@{domain}", 1
                while email in used_emails:
                    suffix += 1
                    email = f"{base}{suffix}@{domain}"
                used_emails.add(email)

                customer = {
                    "customer_id": customer_id, "first_name": first_name, "last_name": last_name,
                    "email": email, "birth_date": birth_date, "city": self._choice(list(CITIES), list(CITIES.values())),
                    "channel": channel, "signup_at": opened_at,
                }
                self.customers.append(customer)
                self._open_account(customer, persona, opened_at)

                # 6% of engaged customers open a second, savings-like account later
                if persona != "inactive" and self.rng.random() < 0.06:
                    second_open = opened_at + timedelta(days=float(self.rng.uniform(30, 240)))
                    if second_open < self.end - timedelta(days=7):
                        self._open_account(customer, "saver", second_open.replace(microsecond=0))
                customer_id += 1

    def _open_account(self, customer: dict, persona: str, opened_at: datetime) -> None:
        while True:
            card_number = luhn.generate_card_number(self.py_rng)
            if card_number not in self.accounts_by_card:
                break
        pin = security.generate_pin(self.py_rng)
        account = SimAccount(
            account_id=len(self.accounts) + 1,
            customer_id=customer["customer_id"],
            card_number=card_number,
            pin_hash=security.hash_pin(pin, SIMULATION_PIN_ITERATIONS, salt=self.py_rng.randbytes(16)),
            persona=persona,
            channel=customer["channel"],
            opened_at=opened_at,
        )
        self.accounts.append(account)
        self.accounts_by_card[card_number] = account

    # ================================================================ intents
    def _generate_intents(self, account: SimAccount) -> None:
        rng = self.rng
        self._push(account.opened_at, "OPEN", account)
        if account.persona == "inactive":
            for _ in range(int(rng.integers(0, 3))):
                moment = account.opened_at + timedelta(days=float(rng.exponential(10)))
                self._push(moment, "SESSION", account, [("BALANCE",)])
            return

        params = PERSONA_PARAMS[account.persona]
        activation_delay = rng.exponential(10 if account.channel == "PARTNER" else 3)
        activation = account.opened_at + timedelta(days=float(activation_delay), minutes=5)
        if activation > self.end:
            return
        self._push(activation, "SESSION", account, [("DEPOSIT", self._top_up_amount(params))])

        if account.persona == "churner":
            lifetime_end = activation + timedelta(days=float(rng.uniform(30, 240)))
        else:
            lifetime_end = activation + timedelta(days=float(rng.exponential(30 / params.monthly_churn)))
        active_end = min(self.end, lifetime_end)
        account.engaged_until = lifetime_end
        salary =int(rng.lognormal(np.log(2100), 0.25) * 100) if account.persona == "salaried" else 0

        for month in month_starts(activation, active_end):
            next_month = datetime(month.year + (month.month == 12), month.month % 12 + 1, 1)
            window_start = max(month, activation + timedelta(hours=1))
            window_end = min(next_month - timedelta(seconds=1), active_end)
            if window_start >= window_end:
                continue
            share = (window_end - window_start) / (next_month - month)

            if salary:
                pay_day = month + timedelta(days=int(rng.integers(0, 4)), hours=int(rng.integers(6, 10)))
                if window_start <= pay_day <= window_end:
                    self._push(pay_day, "SALARY", account, int(salary * rng.uniform(0.97, 1.03)))
                    rent_day = pay_day + timedelta(days=int(rng.integers(2, 7)), hours=int(rng.integers(1, 10)))
                    if rent_day <= window_end:
                        self._push(rent_day, "SESSION", account, [("BALANCE",), ("WITHDRAW", rng.uniform(0.30, 0.45))])

            category_weights = {code: spec[0] for code, spec in CATEGORIES.items()}
            if month.month in (7, 8):
                category_weights["TRAVEL"] *= 3
            if month.month == 12:
                category_weights["ONLINE_SHOPPING"] *= 1.6
                category_weights["LEISURE"] *= 1.3
            for _ in range(rng.poisson(params.payments * PAYMENT_SEASONALITY[month.month] * share)):
                category = self._choice(list(category_weights), list(category_weights.values()))
                _, median, sigma = CATEGORIES[category]
                amount = max(100, int(rng.lognormal(np.log(median * params.spend_factor), sigma) * 100))
                self._push(self._random_time(window_start, window_end, PAYMENT_HOURS), "PAY", account, (category, amount))

            for _ in range(rng.poisson(params.top_ups * share)):
                self._push(self._random_time(window_start, window_end, APP_HOURS), "SESSION", account,
                           [("BALANCE",), ("DEPOSIT", self._top_up_amount(params))])
            for _ in range(rng.poisson(params.transfers * share)):
                ratio = rng.uniform(1.05, 2.0) if rng.random() < P_TRANSFER_OVERSHOOT else rng.uniform(0.05, 0.5)
                self._push(self._random_time(window_start, window_end, APP_HOURS), "SESSION", account, [("TRANSFER", ratio)])
            for _ in range(rng.poisson(params.withdrawals * share)):
                self._push(self._random_time(window_start, window_end, APP_HOURS), "SESSION", account,
                           [("WITHDRAW", rng.uniform(0.1, 0.4))])
            for _ in range(rng.poisson(params.balance_checks * share)):
                self._push(self._random_time(window_start, window_end, APP_HOURS), "SESSION", account, [("BALANCE",)])

        if lifetime_end < self.end and rng.random() < params.close_probability:
            closing = lifetime_end + timedelta(days=float(rng.uniform(20, 120)))
            self._push(closing.replace(microsecond=0), "SESSION", account, [("BALANCE",), ("CLOSE",)])

    def _top_up_amount(self, params: Persona) -> int:
        return max(1000, int(round(self.rng.lognormal(np.log(params.top_up_median), 0.8))) * 100)

    # ============================================================== execution
    def _log(self, account_id, event_type, reason, channel, amount, moment) -> int:
        operation_id = len(self.operations) + 1
        status = "FAILED" if reason else "SUCCESS"
        self.operations.append((operation_id, account_id, event_type, status, reason, channel, amount, moment))
        return operation_id

    def _transaction(self, operation_id, txn_type, from_id, to_id, amount, moment, category=None) -> None:
        self.transactions.append(
            (len(self.transactions) + 1, operation_id, txn_type, from_id, to_id, amount, category, moment)
        )

    def _find(self, card_number: str) -> AccountSnapshot | None:
        account = self.accounts_by_card.get(card_number)
        return account.snapshot() if account else None

    def _mistype(self, number: str) -> str:
        """Simulate a human typing error on a card number."""
        digits = list(number)
        roll = self.rng.random()
        if roll < 0.70:  # one wrong digit
            index = int(self.rng.integers(len(digits)))
            digits[index] = str((int(digits[index]) + int(self.rng.integers(1, 10))) % 10)
        elif roll < 0.90:  # two neighbouring digits swapped
            candidates = [i for i in range(len(digits) - 1) if digits[i] != digits[i + 1]]
            index = candidates[int(self.rng.integers(len(candidates)))]
            digits[index], digits[index + 1] = digits[index + 1], digits[index]
        elif roll < 0.95:  # missing digit
            del digits[int(self.rng.integers(len(digits)))]
        else:  # extra digit
            digits.insert(int(self.rng.integers(len(digits))), str(int(self.rng.integers(10))))
        return "".join(digits)

    def _login(self, account: SimAccount, moment: datetime) -> tuple[bool, datetime]:
        for _attempt in range(3):
            typed = self._mistype(account.card_number) if self.rng.random() < P_LOGIN_CARD_TYPO else account.card_number
            pin_ok = self.rng.random() > P_WRONG_PIN
            reason, found = check_login(typed, lambda snap: pin_ok and snap.account_id == account.account_id, self._find)
            self._log(found.account_id if found else None, "LOGIN", reason, "APP", None, moment)
            if reason is None:
                return True, moment
            moment += timedelta(seconds=int(self.rng.integers(10, 60)))
            if self.rng.random() > 0.9:  # gives up
                break
        return False, moment

    def _run_session(self, account: SimAccount, moment: datetime, actions: list[tuple]) -> None:
        if not account.is_active:
            return
        logged_in, moment = self._login(account, moment)
        if not logged_in:
            return
        for action in actions:
            moment += timedelta(seconds=int(self.rng.integers(8, 120)))
            kind = action[0]
            if kind == "BALANCE":
                self._log(account.account_id, "BALANCE_INQUIRY", None, "APP", None, moment)
            elif kind == "DEPOSIT":
                self._deposit(account, action[1], moment, "APP")
            elif kind == "WITHDRAW":
                amount = max(1000, int(account.balance * action[1]) // 100 * 100)
                if account.balance > 0 or self.rng.random() < 0.3:
                    self._debit(account, amount, moment, "WITHDRAWAL", "APP")
            elif kind == "TRANSFER":
                self._transfer(account, action[1], moment)
            elif kind == "CLOSE":
                if account.balance > 0:
                    self._debit(account, account.balance, moment, "WITHDRAWAL", "APP")
                    moment += timedelta(seconds=5)
                self._log(account.account_id, "CLOSE_ACCOUNT", None, "APP", None, moment)
                account.is_active, account.closed_at = False, moment

    def _deposit(self, account: SimAccount, amount: int, moment: datetime, channel: str) -> None:
        if channel == "APP" and self.rng.random() < P_INVALID_AMOUNT:
            self._log(account.account_id, "DEPOSIT", FailureReason.INVALID_AMOUNT, channel, 0, moment)
            moment += timedelta(seconds=20)
        operation_id = self._log(account.account_id, "DEPOSIT", None, channel, amount, moment)
        account.balance += amount
        self._transaction(operation_id, "DEPOSIT", None, account.account_id, amount, moment)

    def _debit(self, account: SimAccount, amount: int, moment: datetime, event_type: str, channel: str, category=None) -> bool:
        reason = check_debit(account.balance, amount)
        operation_id = self._log(account.account_id, event_type, reason, channel, amount, moment)
        if reason:
            return False
        account.balance -= amount
        self._transaction(operation_id, event_type, account.account_id, None, amount, moment, category)
        return True

    def _transfer(self, account: SimAccount, ratio: float, moment: datetime, retry: bool = False) -> None:
        # Customers send money to people who actually use the bank (never-activated
        # accounts are excluded) and gradually replace contacts who stopped using it.
        pool = self.opened_ids
        if len(pool) < 2:
            return

        def pick_contact() -> int:
            while (candidate := self.py_rng.choice(pool)) == account.account_id:
                pass
            return candidate

        if not account.contacts:
            account.contacts = [pick_contact() for _ in range(int(self.rng.integers(1, 6)))]
        contact_index = self.py_rng.randrange(len(account.contacts))
        target = self.accounts[account.contacts[contact_index] - 1]
        if target.engaged_until < moment and self.rng.random() < 0.7:
            account.contacts[contact_index] = pick_contact()
            target = self.accounts[account.contacts[contact_index] - 1]

        typed = target.card_number
        amount = max(1000, int(account.balance * ratio) // 100 * 100)
        if not retry:
            roll = self.rng.random()
            if roll < P_TRANSFER_SAME_CARD:
                typed = account.card_number
            elif roll < P_TRANSFER_SAME_CARD + P_TRANSFER_TYPO:
                typed = self._mistype(target.card_number)
            elif roll < P_TRANSFER_SAME_CARD + P_TRANSFER_TYPO + P_TRANSFER_WRONG_CARD:
                typed = luhn.generate_card_number(self.py_rng)
            if self.rng.random() < P_INVALID_AMOUNT:
                amount = 0
            if account.balance == 0 and self.rng.random() > 0.25:
                return  # most customers do not try to transfer from an empty account

        reason, resolved = check_transfer(account.snapshot(), typed, amount, self._find)
        operation_id = self._log(account.account_id, "TRANSFER", reason, "APP", amount, moment)
        if reason is None:
            receiver = self.accounts[resolved.account_id - 1]
            account.balance -= amount
            receiver.balance += amount
            self._transaction(operation_id, "TRANSFER", account.account_id, receiver.account_id, amount, moment)
            return

        if retry:
            return
        moment += timedelta(seconds=int(self.rng.integers(20, 90)))
        if reason == FailureReason.INSUFFICIENT_FUNDS:
            if account.balance >= 2000 and self.rng.random() < 0.5:
                self._transfer(account, self.rng.uniform(0.3, 0.9), moment, retry=True)
        elif reason != FailureReason.ACCOUNT_CLOSED and self.rng.random() < 0.8:
            self._transfer(account, min(ratio, 0.5), moment, retry=True)

    def run(self) -> None:
        self.build_customers()
        for account in self.accounts:
            self._generate_intents(account)
        self.intents.sort(key=lambda intent: (intent[0], intent[1]))

        for moment, _seq, kind, account_id, payload in self.intents:
            account = self.accounts[account_id - 1]
            if kind == "OPEN":
                self._log(account_id, "CREATE_ACCOUNT", None, "APP", None, moment)
                if account.engaged_until:  # only accounts that will really be used receive transfers
                    self.opened_ids.append(account_id)
            elif not account.is_active:
                continue
            elif kind == "SALARY":
                self._deposit(account, payload, moment, "SEPA")
            elif kind == "PAY":
                category, amount = payload
                self._debit(account, amount, moment, "CARD_PAYMENT", "CARD_NETWORK", category)
            elif kind == "SESSION":
                self._run_session(account, moment, payload)

        # Operations of a session may spill a few seconds after the next intent:
        # renumber everything chronologically, as an auto-increment log would.
        self._renumber_chronologically()

    def _renumber_chronologically(self) -> None:
        order = sorted(range(len(self.operations)), key=lambda i: (self.operations[i][7], i))
        new_ids = {self.operations[i][0]: rank + 1 for rank, i in enumerate(order)}
        self.operations = [(new_ids[op[0]], *op[1:]) for op in (self.operations[i] for i in order)]
        self.transactions.sort(key=lambda t: new_ids[t[1]])
        self.transactions = [(rank + 1, new_ids[t[1]], *t[2:]) for rank, t in enumerate(self.transactions)]

    # ================================================================ exports
    def _dirty_customer_rows(self) -> list[dict]:
        """CRM export with the defects commonly met in real extracts."""
        rng = self.rng
        channel_variants = {
            "MOBILE": ["mobile", "Mobile", "MOBILE", "app mobile", "mobile_app"],
            "WEB": ["web", "Web", "WEB", "site web"],
            "PARTNER": ["partner", "Partner", "PARTENAIRE", "partenaire"],
        }
        rows = []
        for customer in self.customers:
            updated_at = customer["signup_at"] + (self.end - customer["signup_at"]) * float(rng.random())
            first_name, last_name = customer["first_name"], customer["last_name"]
            if rng.random() < 0.10:
                last_name = last_name.upper()
            if rng.random() < 0.06:
                first_name = first_name.lower()
            if rng.random() < 0.05:
                first_name = f" {first_name}  "

            email = customer["email"]
            roll = rng.random()
            if roll < 0.06:
                email = email.upper()
            elif roll < 0.09:
                email = f" {email} "
            elif roll < 0.10:
                email = email.replace("@", " at ")

            birth = customer["birth_date"]
            roll = rng.random()
            if roll < 0.025:
                birth_value = ""
            elif roll < 0.032:
                birth_value = self._choice(["1900-01-01", "2031-05-14", "01/01/1901"], [1, 1, 1])
            elif roll < 0.28:
                birth_value = birth.strftime("%d/%m/%Y")
            else:
                birth_value = birth.isoformat()

            city = customer["city"]
            roll = rng.random()
            if roll < 0.08:
                city = city.upper()
            elif roll < 0.12:
                city = f"{city.lower()} "
            elif roll < 0.13:
                city = ""
            if customer["city"] == "Saint-Étienne" and rng.random() < 0.5:
                city = self._choice(["St-Etienne", "Saint Etienne", "saint-etienne"], [1, 1, 1])

            row = {
                "crm_customer_id": customer["customer_id"], "first_name": first_name, "last_name": last_name,
                "email": email, "birth_date": birth_value, "city": city,
                "signup_channel": self._choice(channel_variants[customer["channel"]], [1] * len(channel_variants[customer["channel"]])),
                "updated_at": updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            rows.append(row)

            if rng.random() < 0.04:  # older version of the same customer exported twice
                older = dict(row)
                older["updated_at"] = (customer["signup_at"] + (updated_at - customer["signup_at"]) * 0.5).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                older["city"] = self._choice(list(CITIES), list(CITIES.values()))
                older["email"] = customer["email"].replace("@", ".old@")
                rows.append(older)
            if rng.random() < 0.005:  # exact duplicate line
                rows.append(dict(row))

        self.py_rng.shuffle(rows)
        return rows

    def export(self, output_dir: Path) -> dict[str, int]:
        output_dir.mkdir(parents=True, exist_ok=True)
        counts = {}

        customer_rows = self._dirty_customer_rows()
        with open(output_dir / "customers_crm_export.csv", "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(customer_rows[0]), delimiter=";")
            writer.writeheader()
            writer.writerows(customer_rows)
        counts["customers_crm_export.csv"] = len(customer_rows)

        def write(name: str, header: list[str], rows) -> None:
            with open(output_dir / name, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(header)
                count = 0
                for row in rows:
                    writer.writerow(row)
                    count += 1
            counts[name] = count

        write(
            "accounts.csv",
            ["account_id", "customer_id", "card_number", "pin_hash", "balance", "status", "opened_at", "closed_at"],
            (
                (a.account_id, a.customer_id, a.card_number, a.pin_hash, cents_to_str(a.balance),
                 "ACTIVE" if a.is_active else "CLOSED", a.opened_at, a.closed_at or "")
                for a in self.accounts
            ),
        )
        write(
            "operation_log.csv",
            ["operation_id", "account_id", "event_type", "status", "failure_reason", "channel", "amount_requested", "created_at"],
            (
                (op_id, acc or "", event, status, reason or "", channel, cents_to_str(amount), moment)
                for op_id, acc, event, status, reason, channel, amount, moment in self.operations
            ),
        )
        write(
            "transactions.csv",
            ["transaction_id", "operation_id", "txn_type", "from_account_id", "to_account_id", "amount", "merchant_category", "created_at"],
            (
                (txn_id, op_id, txn_type, from_id or "", to_id or "", cents_to_str(amount), category or "", moment)
                for txn_id, op_id, txn_type, from_id, to_id, amount, category, moment in self.transactions
            ),
        )
        return counts


def generate(output_dir: Path, n_customers: int = 1800, seed: int = 42) -> dict[str, int]:
    simulation = Simulation(n_customers=n_customers, seed=seed)
    simulation.run()
    return simulation.export(output_dir)
