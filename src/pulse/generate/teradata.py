"""Write 'Teradata' tables to SQLite using the text conventions in PLAN.md §6.2.

Timestamps are naive UTC text ``YYYY-MM-DD HH:MM:SS``; dates are ``YYYY-MM-DD``. The column
types match ``fixtures/sources/teradata/edw.sqlite``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pulse.contracts import columns
from pulse.contracts.base import Contract

TS_FORMAT = "%Y-%m-%d %H:%M:%S"

_TYPES: dict[type, str] = {str: "VARCHAR", int: "INTEGER", date: "DATE", datetime: "TIMESTAMP"}
_OVERRIDES = {"PROV_CD": "CHAR(2)", "STAT_CD": "CHAR(1)"}


def sql_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime(TS_FORMAT)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


@contextmanager
def write_transaction(db_path: Path) -> Iterator[sqlite3.Connection]:
    """One explicit transaction, closed afterwards.

    sqlite3's default mode only opens a transaction before DML, so a DROP TABLE would commit
    on its own and a failed insert would leave the table empty.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path, isolation_level=None)) as con:
        con.execute("BEGIN")
        try:
            yield con
        except BaseException:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")


def replace_table(
    con: sqlite3.Connection,
    name: str,
    model: type[Contract],
    rows: Sequence[Contract],
    primary_key: str | None = None,
) -> None:
    """Drop and recreate ``name`` with ``rows``. Joins the caller's transaction."""
    cols = columns(model)
    ddl = ", ".join(
        f'"{c.name}" {_OVERRIDES.get(c.name, _TYPES.get(c.python_type, "VARCHAR"))}' for c in cols
    )
    if primary_key:
        ddl += f', PRIMARY KEY ("{primary_key}")'
    con.execute(f'DROP TABLE IF EXISTS "{name}"')
    con.execute(f'CREATE TABLE "{name}" ({ddl})')
    con.executemany(
        f'INSERT INTO "{name}" VALUES ({", ".join("?" for _ in cols)})',
        [
            [sql_value(v) for v in row.model_dump(by_alias=True, mode="python").values()]
            for row in rows
        ],
    )
