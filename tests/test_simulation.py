from collections import Counter

import pytest

from sbs_bank import luhn
from sbs_bank.simulation import Simulation


@pytest.fixture(scope="module")
def simulation():
    sim = Simulation(n_customers=80, seed=7)
    sim.run()
    return sim


def test_balances_match_transactions_and_are_never_negative(simulation):
    computed = Counter()
    for _txn_id, _op_id, _type, from_id, to_id, amount, _category, _moment in simulation.transactions:
        if to_id:
            computed[to_id] += amount
        if from_id:
            computed[from_id] -= amount
    for account in simulation.accounts:
        assert account.balance >= 0
        assert computed[account.account_id] == account.balance


def test_card_numbers_are_unique_and_luhn_valid(simulation):
    numbers = [account.card_number for account in simulation.accounts]
    assert len(numbers) == len(set(numbers))
    assert all(luhn.is_valid(number) for number in numbers)


def test_operation_log_is_chronological_and_consistent(simulation):
    moments = [operation[7] for operation in simulation.operations]
    assert moments == sorted(moments)
    for _op_id, _account, _event, status, reason, *_ in simulation.operations:
        assert (status == "FAILED") == (reason is not None)


def test_same_seed_gives_same_data():
    first, second = Simulation(n_customers=20, seed=3), Simulation(n_customers=20, seed=3)
    first.run()
    second.run()
    assert first.operations == second.operations
