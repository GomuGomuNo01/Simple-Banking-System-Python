"""Integration tests: the banking service against a real MySQL test database.

The database `sbs_bank_test` is rebuilt for each test module run.
Tests are skipped when MySQL is not reachable (start WampServer first).
"""

from decimal import Decimal

import pymysql
import pytest

from sbs_bank import db
from sbs_bank.bank import BankService, OperationError
from sbs_bank.config import SQL_DIR, get_db_config
from sbs_bank.rules import FailureReason

pytestmark = pytest.mark.integration
TEST_DB = "sbs_bank_test"


@pytest.fixture(scope="module")
def conn():
    config = get_db_config(TEST_DB)
    try:
        admin = db.connect(config, use_database=False, multi_statements=True)
    except pymysql.err.OperationalError:
        pytest.skip("MySQL server not reachable")
    with admin.cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS {TEST_DB}; CREATE DATABASE {TEST_DB};")
        while cursor.nextset():
            pass
    admin.close()

    connection = db.connect(config, multi_statements=True)
    db.run_sql_script(connection, SQL_DIR / "01_schema.sql")
    yield connection
    with connection.cursor() as cursor:
        cursor.execute(f"DROP DATABASE {TEST_DB}")
    connection.close()


@pytest.fixture(scope="module")
def bank(conn):
    return BankService(conn)


def last_log(conn):
    with conn.cursor() as cursor:
        cursor.execute("SELECT event_type, status, failure_reason FROM operation_log ORDER BY operation_id DESC LIMIT 1")
        return cursor.fetchone()


def test_full_customer_journey(conn, bank):
    alice_card, alice_pin = bank.create_account("alice", "martin", "Alice.Martin@example.com")
    bob_card, bob_pin = bank.create_account("bob", "durand", "bob.durand@example.com")

    with pytest.raises(OperationError) as error:
        bank.login(alice_card, "0000" if alice_pin != "0000" else "1111")
    assert error.value.reason == FailureReason.WRONG_PIN
    assert last_log(conn) == ("LOGIN", "FAILED", "WRONG_PIN")

    alice = bank.login(alice_card, alice_pin)
    bank.deposit(alice, Decimal("250.00"))
    bank.transfer(alice, bob_card, Decimal("100.00"))
    assert bank.get_balance(alice) == Decimal("150.00")

    with pytest.raises(OperationError) as error:
        bank.transfer(alice, bob_card, Decimal("500.00"))
    assert error.value.reason == FailureReason.INSUFFICIENT_FUNDS
    assert bank.get_balance(alice) == Decimal("150.00")  # failed transfer changed nothing

    bob = bank.login(bob_card, bob_pin)
    assert bank.get_balance(bob) == Decimal("100.00")
    assert bank.close_account(bob) == Decimal("100.00")

    with pytest.raises(OperationError) as error:
        bank.transfer(alice, bob_card, Decimal("10.00"))
    assert error.value.reason == FailureReason.ACCOUNT_CLOSED


def test_typing_error_is_rejected_before_lookup(bank):
    card, pin = bank.create_account("carla", "petit", "carla.petit@example.com")
    session = bank.login(card, pin)
    typo = card[:-1] + str((int(card[-1]) + 1) % 10)
    with pytest.raises(OperationError) as error:
        bank.transfer(session, typo, Decimal("1.00"))
    assert error.value.reason == FailureReason.INVALID_CARD_NUMBER


def test_database_integrity_after_operations(conn):
    queries = db.load_named_queries(SQL_DIR / "03_data_quality_checks.sql")
    with conn.cursor() as cursor:
        cursor.execute(queries["integrity_checks"])
        failures = {name: int(count) for name, count in cursor.fetchall() if int(count)}
    assert failures == {}
