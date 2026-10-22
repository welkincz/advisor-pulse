"""DQ024 fires on each kind of broken portfolio holder range (issue #223).

The fixtures are clean, so the singular test passes there trivially. This runs its SQL
against hand-built ranges, one portfolio per problem, and one clean portfolio that must
return nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

SQL = Path(__file__).parents[2] / "dbt" / "tests" / "assert_portfolio_history_dq024.sql"
OPEN = "9999-12-31"


def test_dq024_returns_one_row_per_problem() -> None:
    con = duckdb.connect()
    con.execute(
        "create table stg_portfolio (portfolio_id varchar, open_date date);"
        "create table int_portfolio_history"
        " (portfolio_id varchar, advisor_id varchar, valid_from date, valid_to date);"
        "create table int_advisor_history"
        " (advisor_id varchar, role_code varchar, valid_from date, valid_to date);"
    )
    con.executemany(
        "insert into stg_portfolio values (?, ?)",
        [
            ("PRT-CLEAN", "2025-01-01"),
            ("PRT-EARLY", "2025-02-01"),
            ("PRT-LATE", "2025-01-01"),
            ("PRT-GAP", "2025-01-01"),
            ("PRT-MGR", "2025-01-01"),
        ],
    )
    con.executemany(
        "insert into int_portfolio_history values (?, ?, ?, ?)",
        [
            ("PRT-CLEAN", "ADV-1", "2025-01-01", "2025-06-01"),
            ("PRT-CLEAN", "ADV-2", "2025-06-01", OPEN),
            ("PRT-EARLY", "ADV-1", "2025-01-15", OPEN),
            ("PRT-LATE", "ADV-1", "2025-01-10", OPEN),
            ("PRT-GAP", "ADV-1", "2025-01-01", "2025-03-01"),
            ("PRT-GAP", "ADV-2", "2025-03-05", OPEN),
            ("PRT-MGR", "ADV-9", "2025-01-01", OPEN),
        ],
    )
    con.executemany(
        "insert into int_advisor_history values (?, ?, ?, ?)",
        [
            ("ADV-1", "ADVSR", "2024-01-01", OPEN),
            ("ADV-2", "ADVSR", "2024-01-01", OPEN),
            ("ADV-9", "BR_MGR", "2024-01-01", OPEN),
        ],
    )

    sql = re.sub(r"\{\{\s*ref\('(\w+)'\)\s*\}\}", r"\1", SQL.read_text())
    found = {(p, problem) for p, _, problem in con.execute(sql).fetchall()}
    assert found == {
        ("PRT-EARLY", "starts before the portfolio opened"),
        ("PRT-LATE", "first holder starts after the portfolio opened"),
        ("PRT-GAP", "overlaps or leaves a gap after the prior range"),
        ("PRT-MGR", "holder not an employed book owner on that day"),
    }
