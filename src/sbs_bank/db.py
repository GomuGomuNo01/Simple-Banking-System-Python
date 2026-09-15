"""MySQL access helpers.

- PyMySQL for the application and loading (fine-grained transaction control)
- SQLAlchemy engine for pandas in the analysis notebook
"""

from __future__ import annotations

import re
from pathlib import Path

import pymysql
from pymysql.constants import CLIENT
from sqlalchemy import URL, Engine, create_engine

from .config import DbConfig, get_db_config

_QUERY_NAME = re.compile(r"^--\s*name:\s*(\w+)\s*$", re.MULTILINE)


def connect(
    config: DbConfig | None = None,
    use_database: bool = True,
    multi_statements: bool = False,
) -> pymysql.connections.Connection:
    cfg = config or get_db_config()
    return pymysql.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
        database=cfg.database if use_database else None,
        charset="utf8mb4",
        autocommit=False,
        client_flag=CLIENT.MULTI_STATEMENTS if multi_statements else 0,
    )


def get_engine(config: DbConfig | None = None) -> Engine:
    cfg = config or get_db_config()
    url = URL.create(
        "mysql+pymysql",
        username=cfg.user,
        password=cfg.password or None,
        host=cfg.host,
        port=cfg.port,
        database=cfg.database,
        query={"charset": "utf8mb4"},
    )
    return create_engine(url)


def run_sql_script(conn: pymysql.connections.Connection, path: Path) -> None:
    """Execute a multi-statement SQL file (connection opened with multi_statements=True)."""
    sql = Path(path).read_text(encoding="utf-8")
    with conn.cursor() as cursor:
        cursor.execute(sql)
        while cursor.nextset():
            pass
    conn.commit()


def load_named_queries(path: Path) -> dict[str, str]:
    """Parse a SQL file where each query is preceded by a `-- name: <query_name>` line.

    SQL files stay the single source of truth: the notebook runs the same
    queries a reviewer can execute directly in the IDE.
    """
    text = Path(path).read_text(encoding="utf-8")
    parts = _QUERY_NAME.split(text)
    return {name: body.strip().rstrip(";").strip() for name, body in zip(parts[1::2], parts[2::2])}
