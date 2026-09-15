"""Data pipeline: generate -> load -> clean -> check -> analytics views.

Usage
    python -m sbs_bank.pipeline all        full rebuild (about 2 minutes)
    python -m sbs_bank.pipeline generate   CSV files only
    python -m sbs_bank.pipeline load       database rebuild from existing CSV files
    python -m sbs_bank.pipeline quality    data quality report only

Why Python for this step? Reading files, converting empty strings to NULL
and loading in batches is file handling and orchestration, which Python does
well. Transformations on data already in the database are left to SQL.
"""

from __future__ import annotations

import argparse
import csv
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from . import db, simulation
from .config import DATA_RAW_DIR, REPORTS_DIR, SQL_DIR, DbConfig, get_db_config

BATCH_SIZE = 5_000

OPERATIONAL_TABLES = [
    ("accounts.csv", "accounts"),
    ("operation_log.csv", "operation_log"),
    ("transactions.csv", "transactions"),
]


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def read_csv_batches(path: Path, delimiter: str, empty_as_null: bool) -> tuple[list[str], Iterator[list]]:
    handle = open(path, newline="", encoding="utf-8")
    reader = csv.reader(handle, delimiter=delimiter)
    header = next(reader)

    def batches():
        with handle:
            batch = []
            for row in reader:
                batch.append([None if (empty_as_null and value == "") else value for value in row])
                if len(batch) == BATCH_SIZE:
                    yield batch
                    batch = []
            if batch:
                yield batch

    return header, batches()


def load_csv(conn, path: Path, table: str, delimiter: str = ",", empty_as_null: bool = True) -> int:
    header, batches = read_csv_batches(path, delimiter, empty_as_null)
    columns = ", ".join(header)
    placeholders = ", ".join(["%s"] * len(header))
    sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
    total = 0
    with conn.cursor() as cursor:
        for batch in batches:
            cursor.executemany(sql, batch)
            total += len(batch)
    conn.commit()
    return total


def generate(n_customers: int, seed: int) -> None:
    log(f"Simulating activity for {n_customers} customers (seed={seed})")
    counts = simulation.generate(DATA_RAW_DIR, n_customers=n_customers, seed=seed)
    for name, count in counts.items():
        log(f"  {name}: {count:,} rows")


def create_database(config: DbConfig) -> None:
    log(f"Creating database `{config.database}`")
    conn = db.connect(config, use_database=False, multi_statements=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"DROP DATABASE IF EXISTS `{config.database}`;"
                f"CREATE DATABASE `{config.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
            )
            while cursor.nextset():
                pass
    finally:
        conn.close()
    conn = db.connect(config, multi_statements=True)
    try:
        db.run_sql_script(conn, SQL_DIR / "01_schema.sql")
    finally:
        conn.close()


def load(config: DbConfig) -> None:
    create_database(config)
    conn = db.connect(config, multi_statements=True)
    try:
        # Raw values are kept exactly as exported: empty strings stay empty strings
        count = load_csv(conn, DATA_RAW_DIR / "customers_crm_export.csv", "stg_customers_raw", ";", empty_as_null=False)
        log(f"  stg_customers_raw: {count:,} rows loaded")
        db.run_sql_script(conn, SQL_DIR / "02_clean_customers.sql")
        log("  customers: cleaned and deduplicated with 02_clean_customers.sql")
        for file_name, table in OPERATIONAL_TABLES:
            count = load_csv(conn, DATA_RAW_DIR / file_name, table)
            log(f"  {table}: {count:,} rows loaded")
        db.run_sql_script(conn, SQL_DIR / "04_analytics_views.sql")
        log("  analytics views created")
    finally:
        conn.close()


def quality_report(config: DbConfig) -> bool:
    queries = db.load_named_queries(SQL_DIR / "03_data_quality_checks.sql")
    conn = db.connect(config)
    try:
        with conn.cursor() as cursor:
            cursor.execute(queries["crm_profiling"])
            profiling = cursor.fetchall()
            cursor.execute(queries["integrity_checks"])
            checks = cursor.fetchall()
    finally:
        conn.close()

    all_passed = all(int(failing) == 0 for _, failing in checks)
    lines = [
        "# Rapport de qualité des données",
        "",
        "Généré automatiquement par `python -m sbs_bank.pipeline` à partir de `sql/03_data_quality_checks.sql`.",
        "",
        "## 1. Préparation de l'export CRM",
        "",
        "| Indicateur | Valeur |",
        "|---|---:|",
        *[f"| {indicator} | {int(value or 0):,} |".replace(",", " ") for indicator, value in profiling],
        "",
        "## 2. Contrôles d'intégrité des données opérationnelles",
        "",
        "| Contrôle | Lignes en erreur | Statut |",
        "|---|---:|:---:|",
        *[f"| {name} | {int(failing)} | {'OK' if int(failing) == 0 else 'ÉCHEC'} |" for name, failing in checks],
        "",
        f"**Résultat global : {'tous les contrôles sont validés' if all_passed else 'au moins un contrôle a échoué'}.**",
        "",
    ]
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "data_quality_report.md").write_text("\n".join(lines), encoding="utf-8")
    for name, failing in checks:
        log(f"  [{'OK' if int(failing) == 0 else 'FAILED'}] {name}: {int(failing)}")
    log("Data quality report written to reports/data_quality_report.md")
    return all_passed


def main() -> None:
    parser = argparse.ArgumentParser(description="SBS Bank data pipeline")
    parser.add_argument("step", choices=["all", "generate", "load", "quality"])
    parser.add_argument("--customers", type=int, default=1800)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    config = get_db_config()
    started = time.perf_counter()

    if args.step in ("all", "generate"):
        generate(args.customers, args.seed)
    if args.step in ("all", "load"):
        load(config)
    if args.step in ("all", "load", "quality"):
        if not quality_report(config):
            raise SystemExit("Data quality checks failed: analysis results would not be reliable.")
    log(f"Done in {time.perf_counter() - started:.0f} s")


if __name__ == "__main__":
    main()
