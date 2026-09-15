from sbs_bank import security
from sbs_bank.rules import AccountSnapshot, FailureReason, check_debit, check_login, check_transfer

SENDER = AccountSnapshot(1, "4000003972196501", 100, True)
RECEIVER = AccountSnapshot(2, "4000004938320896", 0, True)
CLOSED = AccountSnapshot(3, "4000007916053702", 0, False)
ACCOUNTS = {a.card_number: a for a in (SENDER, RECEIVER, CLOSED)}


def test_transfer_success():
    assert check_transfer(SENDER, RECEIVER.card_number, 50, ACCOUNTS.get) == (None, RECEIVER)


def test_transfer_failure_reasons_in_business_order():
    assert check_transfer(SENDER, "4000004938320895", 50, ACCOUNTS.get)[0] == FailureReason.INVALID_CARD_NUMBER
    assert check_transfer(SENDER, "400000493832089", 50, ACCOUNTS.get)[0] == FailureReason.INVALID_CARD_NUMBER
    assert check_transfer(SENDER, SENDER.card_number, 50, ACCOUNTS.get)[0] == FailureReason.SAME_ACCOUNT
    assert check_transfer(SENDER, "4000000000000002", 50, ACCOUNTS.get)[0] == FailureReason.UNKNOWN_CARD
    assert check_transfer(SENDER, CLOSED.card_number, 50, ACCOUNTS.get)[0] == FailureReason.ACCOUNT_CLOSED
    assert check_transfer(SENDER, RECEIVER.card_number, 0, ACCOUNTS.get)[0] == FailureReason.INVALID_AMOUNT
    assert check_transfer(SENDER, RECEIVER.card_number, 101, ACCOUNTS.get)[0] == FailureReason.INSUFFICIENT_FUNDS


def test_debit_rules():
    assert check_debit(100, 100) is None
    assert check_debit(100, 100.01) == FailureReason.INSUFFICIENT_FUNDS
    assert check_debit(100, -5) == FailureReason.INVALID_AMOUNT


def test_login_rules():
    assert check_login(SENDER.card_number, lambda _: True, ACCOUNTS.get) == (None, SENDER)
    assert check_login(SENDER.card_number, lambda _: False, ACCOUNTS.get)[0] == FailureReason.WRONG_PIN
    assert check_login(CLOSED.card_number, lambda _: True, ACCOUNTS.get)[0] == FailureReason.ACCOUNT_CLOSED
    assert check_login("1234", lambda _: True, ACCOUNTS.get)[0] == FailureReason.INVALID_CARD_NUMBER


def test_pin_hash_roundtrip_and_salting():
    first = security.hash_pin("1234", iterations=1_000)
    second = security.hash_pin("1234", iterations=1_000)
    assert first != second  # random salt: same PIN, different hashes
    assert "1234" not in first
    assert security.verify_pin("1234", first)
    assert not security.verify_pin("4321", first)
    assert not security.verify_pin("1234", "corrupted value")
