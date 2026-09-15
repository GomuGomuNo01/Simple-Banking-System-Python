import random

from sbs_bank import luhn


def test_known_valid_and_invalid_numbers():
    assert luhn.is_valid("4000003972196501")
    assert luhn.is_valid("79927398713")
    assert not luhn.is_valid("4000003972196502")
    assert not luhn.is_valid("40000039721965O1")  # letter O instead of zero
    assert not luhn.is_valid("")


def test_generated_numbers_are_valid_and_use_bank_bin():
    rng = random.Random(0)
    for _ in range(500):
        number = luhn.generate_card_number(rng)
        assert len(number) == 16
        assert number.startswith(luhn.BANK_BIN)
        assert luhn.is_valid(number)


def test_every_single_digit_error_is_detected():
    number = luhn.generate_card_number(random.Random(1))
    for position in range(len(number)):
        for digit in "0123456789":
            if digit != number[position]:
                typo = number[:position] + digit + number[position + 1:]
                assert not luhn.is_valid(typo)


def test_adjacent_swaps_are_detected_except_09_and_90():
    for first in range(10):
        for second in range(10):
            if first == second:
                continue
            base = luhn.BANK_BIN + "12345" + f"{first}{second}" + "12"
            number = base + str(luhn.check_digit(base))
            swapped = number[:11] + number[12] + number[11] + number[13:]
            expected_detected = {first, second} != {0, 9}
            assert (not luhn.is_valid(swapped)) == expected_detected
