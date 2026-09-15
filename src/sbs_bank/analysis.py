"""Helpers for the analysis notebook: named SQL queries, chart style, figure export."""

from __future__ import annotations

from functools import cache

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sqlalchemy import text

from . import db
from .config import REPORTS_DIR, SQL_DIR

FIGURES_DIR = REPORTS_DIR / "figures"

# Validated categorical order (colour-blind safe for up to 3 series side by side)
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK_SECONDARY, INK_MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"
SEQUENTIAL_BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

CHANNEL_COLORS = {"MOBILE": BLUE, "WEB": ORANGE, "PARTNER": AQUA}
CHANNEL_LABELS = {"MOBILE": "Application mobile", "WEB": "Site web", "PARTNER": "Partenaires"}
STATUS_LABELS = {
    "ACTIVE": "Actif",
    "DORMANT": "Dormant (90 j sans activité)",
    "NEVER_FUNDED": "Jamais alimenté",
    "CLOSED": "Clôturé",
}


SEGMENT_ORDER = ["Champions", "Clients réguliers", "Épargnants peu actifs", "Occasionnels", "À risque", "Endormis"]


def segment_rfm(rfm: pd.DataFrame) -> pd.DataFrame:
    """Score recency, frequency and monetary value, then assign a business segment.

    Expects the columns of the `q12_rfm_base` query. Shared by the notebook and
    the Power BI export so both show exactly the same segments.
    """
    rfm = rfm.copy()
    # Recency uses business thresholds (7, 30, 60, 90 days); frequency and spend use quintiles
    rfm["R"] = pd.cut(rfm["recency_days"], bins=[-1, 7, 30, 60, 90, np.inf], labels=[5, 4, 3, 2, 1]).astype(int)
    rfm["F"] = pd.qcut(rfm["frequency_180d"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    rfm["M"] = pd.qcut(rfm["card_spend_180d"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    high_balance = rfm["balance_at_period_end"].quantile(0.75)

    def segment(row) -> str:
        # Rules are evaluated in order: the first matching rule gives the segment
        if row.R >= 4 and row.F >= 4 and row.M >= 4:
            return "Champions"             # active this month, frequent, high card spend
        if row.F <= 2 and row.balance_at_period_end >= high_balance:
            return "Épargnants peu actifs"  # low activity but top 25 % balance
        if row.R == 1:
            return "Endormis"              # no activity for more than 90 days
        if row.R <= 3:
            return "À risque"              # no activity for 31 to 90 days
        if row.F >= 3:
            return "Clients réguliers"
        return "Occasionnels"              # recent but infrequent activity

    rfm["segment"] = rfm.apply(segment, axis=1)
    return rfm


@cache
def _engine():
    return db.get_engine()


@cache
def _queries() -> dict[str, str]:
    queries = {}
    for file_name in ("03_data_quality_checks.sql", "05_business_analysis.sql", "06_powerbi_export.sql"):
        queries.update(db.load_named_queries(SQL_DIR / file_name))
    return queries


def run_query(name: str) -> pd.DataFrame:
    """Run a named query from the sql/ folder and return a DataFrame."""
    return pd.read_sql(text(_queries()[name]), _engine())


def apply_style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "figure.dpi": 110,
        "savefig.dpi": 150,
        "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"],
        "font.size": 10,
        "text.color": INK,
        "axes.labelcolor": INK_SECONDARY,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.titlecolor": INK,
        "axes.edgecolor": BASELINE,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
        "legend.frameon": False,
        "lines.linewidth": 2,
    })


def save_figure(fig, name: str) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES_DIR / f"{name}.png", bbox_inches="tight")


def euros(value: float, decimals: int = 0) -> str:
    formatted = f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")
    return f"{formatted} €"
