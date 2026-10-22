"""The booked-from orphan test warns only when the share is unusual and the sample is big.

The fixtures hold too few bookings to reach the 500-row floor, so the test passes there
trivially. This runs its SQL against hand-built bookings on each side of both limits.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

SQL = Path(__file__).parents[2] / "dbt" / "tests" / "assert_booked_from_orphan_rate.sql"


def _warns(bookings: int, missing: int) -> bool:
    con = duckdb.connect()
    con.execute("create table stg_activity (activity_id varchar, booked_from_activity_id varchar)")
    calls = [(f"CALL-{i}", None) for i in range(bookings - missing)]
    found = [(f"APPT-{i}", f"CALL-{i}") for i in range(bookings - missing)]
    orphans = [(f"APPT-X{i}", f"GONE-{i}") for i in range(missing)]
    con.executemany("insert into stg_activity values (?, ?)", calls + found + orphans)
    sql = re.sub(r"\{\{\s*config\([^)]*\)\s*\}\}", "", SQL.read_text())
    sql = re.sub(r"\{\{\s*ref\('(\w+)'\)\s*\}\}", r"\1", sql)
    return bool(con.execute(sql).fetchall())


def test_a_quarantine_sized_share_does_not_warn() -> None:
    assert not _warns(bookings=1000, missing=5)  # 0.5%, about the quarantine rate


def test_a_share_several_times_the_quarantine_rate_warns() -> None:
    assert _warns(bookings=1000, missing=30)  # 3%


def test_a_small_sample_never_warns() -> None:
    assert not _warns(bookings=100, missing=10)  # 10%, but too few bookings to judge
