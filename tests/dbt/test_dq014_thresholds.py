"""DQ014 warns above 0.5% of the active book and fails above 2% (PLAN.md §8).

The fixtures sit between the two, so the fail test passes there trivially. This runs both
tests' SQL against hand-built rates on each side of each threshold.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

TESTS = Path(__file__).parents[2] / "dbt" / "tests"


def _weeks_caught(test: str) -> set[str]:
    con = duckdb.connect()
    con.execute(
        "create table mart_dq_weekly (iso_week_id varchar, rule_id varchar,"
        " rows_affected bigint, rows_in_batch bigint, rate double)"
    )
    con.executemany(
        "insert into mart_dq_weekly values (?, ?, ?, ?, ?)",
        [
            ("2026-W01", "DQ014", 4, 1000, 0.004),  # under both
            ("2026-W02", "DQ014", 6, 1000, 0.006),  # warns only
            ("2026-W03", "DQ014", 25, 1000, 0.025),  # warns and fails
            ("2026-W04", "DQ011", 300, 1000, 0.3),  # another rule
        ],
    )
    sql = (TESTS / f"{test}.sql").read_text()
    sql = re.sub(r"\{\{\s*config\([^)]*\)\s*\}\}", "", sql)
    sql = re.sub(r"\{\{\s*ref\('(\w+)'\)\s*\}\}", r"\1", sql)
    return {week for week, *_ in con.execute(sql).fetchall()}


def test_dq014_warns_above_half_a_percent() -> None:
    assert _weeks_caught("dq014_unknown_portfolio_rate") == {"2026-W02", "2026-W03"}


def test_dq014_fails_above_two_percent() -> None:
    assert _weeks_caught("dq014_unknown_portfolio_rate_fail") == {"2026-W03"}
