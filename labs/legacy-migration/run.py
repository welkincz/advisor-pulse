"""Run the legacy branch report and reconcile it with the dbt mart (#324 lab).

    uv run --project labs/legacy-migration python labs/legacy-migration/run.py \
        [--warehouse PATH] [--strict] [--inject-mismatch]

--strict           compare without the tolerance/sentinel decisions (shows quirks Q2, Q3)
--inject-mismatch  add 1 to one legacy count before comparing (the harness must catch it)
--warehouse defaults to <repo root>/data/ci/warehouse.duckdb, whatever the CWD.
Exit 0 on parity, 1 on any difference, 2 when the warehouse is missing.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import duckdb
from parity import Report, SourceMapping, reconcile

LAB = Path(__file__).resolve().parent
LEGACY_SQL = LAB / "legacy" / "branch_contact_report.sql"
MAPPING = LAB / "mapping.toml"
# Resolved against the repo root (labs/legacy-migration -> ../..), so the CLI works from any CWD.
DEFAULT_WAREHOUSE = LAB.parents[1] / "data" / "ci" / "warehouse.duckdb"
INJECT = {"RPT_WK_ID": "2026-W39", "BRNCH_CD": "0201", "column": "ACT_CNT"}

TARGET_SQL = """
select iso_week_id, node_id as branch_id, activities_completed, calls_out, calls_in,
       unique_clients_contacted, avg_meeting_duration_min
from wh.marts.mart_org_weekly
where level = 'BRANCH'
"""


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def connect(warehouse: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    path = str(warehouse).replace("'", "''")  # SQL string literal: double any single quote
    con.execute(f"attach '{path}' as wh (read_only)")
    con.execute("set TimeZone = 'UTC'")
    return con


def run_legacy(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    con.execute(LEGACY_SQL.read_text())
    return _rows(con, "select * from BRANCH_CONTACT_RPT")


def read_target(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return _rows(con, TARGET_SQL)


def inject(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        if row["RPT_WK_ID"] == INJECT["RPT_WK_ID"] and row["BRNCH_CD"] == INJECT["BRNCH_CD"]:
            row[INJECT["column"]] += 1
            return
    raise LookupError("injection row not found")


def parity(
    warehouse: Path, *, strict: bool = False, inject_mismatch: bool = False
) -> tuple[Report, dict[str, float]]:
    mapping = SourceMapping.load(MAPPING)
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    con = connect(warehouse)
    legacy = run_legacy(con)
    t1 = time.perf_counter()
    target = read_target(con)
    t2 = time.perf_counter()
    if inject_mismatch:
        inject(legacy)
    report = reconcile(mapping.apply(legacy), target, mapping.spec(strict=strict))
    t3 = time.perf_counter()
    timings.update(legacy_s=t1 - t0, target_s=t2 - t1, reconcile_s=t3 - t2, total_s=t3 - t0)
    return report, timings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--warehouse", type=Path, default=DEFAULT_WAREHOUSE)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--inject-mismatch", action="store_true")
    args = ap.parse_args(argv)
    if not args.warehouse.exists():
        print(f"warehouse not found: {args.warehouse} (run `make dbt-build-ci`)", file=sys.stderr)
        return 2
    report, timings = parity(
        args.warehouse, strict=args.strict, inject_mismatch=args.inject_mismatch
    )
    print(report.render())
    print("  timing      " + "  ".join(f"{k}={v:.3f}" for k, v in timings.items()))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
