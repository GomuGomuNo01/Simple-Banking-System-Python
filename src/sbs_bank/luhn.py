"""Luhn algorithm: card number generation and validation.

The last digit of a card number is a checksum. It lets the application reject
most typing errors (any single wrong digit, most swapped neighbours) before
querying the database.
"""

from __future__ import annotations

import random

BANK_BIN = "400000"  # Bank Identification Number: first 6 digits of every SBS card
CARD_LENGTH = 16


def check_digit(partial_number: str) -> int:
    """Return the digit that makes `partial_number + digit` pass the Luhn test."""
    total = 0
    # Walking from the right, the digit next to the future check digit is doubled.
    for position, char in enumerate(reversed(partial_number)):
        digit = int(char)
        if position % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return (10 - total % 10) % 10


def is_valid(number: str) -> bool:
    """True if `number` only contains ASCII digits and has a correct checksum."""
    if len(number) < 2 or not (number.isascii() and number.isdigit()):
        return False
    return check_digit(number[:-1]) == int(number[-1])


def generate_card_number(rng: random.Random | None = None) -> str:
    """Generate a Luhn-valid 16-digit card number starting with the bank BIN."""
    rng = rng or random.SystemRandom()
    body_length = CARD_LENGTH - len(BANK_BIN) - 1
    body = BANK_BIN + "".join(str(rng.randrange(10)) for _ in range(body_length))
    return body + str(check_digit(body))
