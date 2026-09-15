import pandas as pd

from sbs_bank.analysis import SEGMENT_ORDER, segment_rfm
from sbs_bank.powerbi import build_calendar


def make_rfm(rows):
    return pd.DataFrame(rows, columns=["account_id", "recency_days", "frequency_180d", "card_spend_180d", "balance_at_period_end"])


def test_segment_rules():
    rfm = make_rfm([
        (1, 0, 200, 5000, 500),     # very active, high spend
        (2, 2, 190, 4800, 400),
        (3, 1, 180, 4600, 300),
        (4, 3, 170, 4400, 200),
        (5, 45, 5, 50, 20000),      # low activity, top balance
        (6, 200, 1, 10, 100),       # no activity for 200 days
        (7, 70, 60, 900, 150),      # no activity for 70 days
        (8, 5, 80, 300, 120),       # recent and fairly frequent
        (9, 4, 2, 20, 50),          # recent but infrequent
        (10, 6, 90, 700, 90),
    ])
    segments = segment_rfm(rfm).set_index("account_id")["segment"]
    assert segments[1] == "Champions"
    assert segments[5] == "Épargnants peu actifs"
    assert segments[6] == "Endormis"
    assert segments[7] == "À risque"
    assert segments[9] == "Occasionnels"
    assert set(segments) <= set(SEGMENT_ORDER)


def test_calendar_covers_every_month_with_french_labels():
    calendar = build_calendar(pd.to_datetime(pd.Series(["2025-01-01", "2026-06-01"])))
    assert len(calendar) == 18
    assert calendar["Libellé mois"].iloc[0] == "janv. 2025"
    assert calendar["Libellé mois"].iloc[-1] == "juin 2026"
    assert calendar["Ordre mois"].is_monotonic_increasing
