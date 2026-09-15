"""Helpers for the analysis notebook: named SQL queries, chart style, figure export."""

from __future__ import annotations

from functools import cache

import matplotlib.pyplot as plt
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


@cache
def _engine():
    return db.get_engine()


@cache
def _queries() -> dict[str, str]:
    queries = {}
    for file_name in ("03_data_quality_checks.sql", "05_business_analysis.sql"):
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
