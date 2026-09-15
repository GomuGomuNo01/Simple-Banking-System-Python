"""Project paths and database settings read from environment variables (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
REPORTS_DIR = PROJECT_ROOT / "reports"

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


def get_db_config(database: str | None = None) -> DbConfig:
    """Build the connection settings. Defaults match a local WampServer MySQL."""
    return DbConfig(
        host=os.getenv("SBS_DB_HOST", "localhost"),
        port=int(os.getenv("SBS_DB_PORT", "3306")),
        user=os.getenv("SBS_DB_USER", "root"),
        password=os.getenv("SBS_DB_PASSWORD", ""),
        database=database or os.getenv("SBS_DB_NAME", "sbs_bank"),
    )
