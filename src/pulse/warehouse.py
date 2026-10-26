"""The DuckDB warehouse: one connection helper, schemas, and DDL derived from contracts.

Every table under ``raw``, ``meta`` and ``quarantine`` is created from its pydantic contract, so
a contract change shows up as a DDL change and is caught by the DESCRIBE test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pyarrow as pa

from pulse.contracts import Contract, arrow_schema, column_names, duckdb_columns
from pulse.contracts.meta import CheckResult, LoadManifest, RejectedRow, RunLogRow, Watermark
from pulse.contracts.raw import (
    RawSnowflakeActivity,
    RawTeradataAdvisor,
    RawTeradataAssignment,
    RawTeradataBranch,
    RawTeradataClient,
    RawTeradataPortfolio,
    RawTeradataPortfolioAssignment,
)

SCHEMAS = ("raw", "meta", "quarantine")
WAREHOUSE_FILE = "warehouse.duckdb"


@dataclass(frozen=True)
class TableSpec:
    name: str
    model: type[Contract]
    primary_key: tuple[str, ...] = ()


TABLES: tuple[TableSpec, ...] = (
    TableSpec("meta.watermark", Watermark, ("source", "table_name")),
    TableSpec("meta.load_manifest", LoadManifest, ("file_path", "file_sha256")),
    TableSpec("meta.run_log", RunLogRow, ("run_id", "stage", "attempt")),
    TableSpec("meta.check_result", CheckResult, ("run_id", "check_id")),
    TableSpec("quarantine.rejected_rows", RejectedRow, ("rejected_id",)),
    # Raw tables keep duplicates and re-sent rows by design: no primary key.
    TableSpec("raw.snowflake__activity", RawSnowflakeActivity),
    TableSpec("raw.teradata__clnt", RawTeradataClient),
    TableSpec("raw.teradata__advsr", RawTeradataAdvisor),
    TableSpec("raw.teradata__advsr_asgn", RawTeradataAssignment),
    TableSpec("raw.teradata__brnch", RawTeradataBranch),
    TableSpec("raw.teradata__prtf", RawTeradataPortfolio),
    TableSpec("raw.teradata__prtf_asgn", RawTeradataPortfolioAssignment),
)

TABLES_BY_NAME: dict[str, TableSpec] = {t.name: t for t in TABLES}


def data_dir() -> Path:
    return Path(os.environ.get("PULSE_DATA_DIR", "data"))


def warehouse_path() -> Path:
    return data_dir() / WAREHOUSE_FILE


def connect(
    path: Path | str | None = None, *, read_only: bool = False
) -> duckdb.DuckDBPyConnection:
    """Open the warehouse (default ``$PULSE_DATA_DIR/warehouse.duckdb``); ``":memory:"`` for tests.

    The session time zone is UTC so TIMESTAMPTZ values round-trip unchanged.
    """
    target = str(path) if path is not None else str(warehouse_path())
    if target != ":memory:" and not read_only:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(target, read_only=read_only)
    con.execute("SET TimeZone = 'UTC'")
    return con


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def qualified(name: str) -> str:
    schema, table = name.split(".", 1)
    return f"{_quote(schema)}.{_quote(table)}"


def create_table_sql(spec: TableSpec) -> str:
    cols = [
        f"{_quote(name)} {sql_type}{'' if nullable else ' NOT NULL'}"
        for name, sql_type, nullable in duckdb_columns(spec.model)
    ]
    if spec.primary_key:
        cols.append(f"PRIMARY KEY ({', '.join(_quote(c) for c in spec.primary_key)})")
    body = ",\n  ".join(cols)
    return f"CREATE TABLE IF NOT EXISTS {qualified(spec.name)} (\n  {body}\n)"


def init_warehouse(con: duckdb.DuckDBPyConnection) -> None:
    """Create schemas and every contract table. Safe to call repeatedly."""
    with transaction(con):
        for schema in SCHEMAS:
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote(schema)}")
        for spec in TABLES:
            con.execute(create_table_sql(spec))
            for sql in add_column_sql(con, spec):
                con.execute(sql)


def add_column_sql(con: duckdb.DuckDBPyConnection, spec: TableSpec) -> list[str]:
    """ALTERs for nullable contract columns an existing table lacks (additive evolution).

    A warehouse restored from an earlier run keeps working when a contract gains an optional
    column. Anything else (a new required column, a type change) needs a rebuild and fails at
    insert time, loudly.
    """
    schema, table = spec.name.split(".", 1)
    have = {
        row[0]
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ?",
            [schema, table],
        ).fetchall()
    }
    return [
        f"ALTER TABLE {qualified(spec.name)} ADD COLUMN {_quote(name)} {sql_type}"
        for name, sql_type, nullable in duckdb_columns(spec.model)
        if nullable and name not in have
    ]


@contextmanager
def transaction(con: duckdb.DuckDBPyConnection) -> Iterator[duckdb.DuckDBPyConnection]:
    """Run a block atomically: commit on success, roll back on any exception.

    Repository functions issue single statements and never open their own transaction, so
    calling them inside this block makes them part of it (e.g. raw insert + manifest +
    watermark in one unit).
    """
    con.execute("BEGIN TRANSACTION")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def insert_contracts(
    con: duckdb.DuckDBPyConnection, table: str, model: type[Contract], rows: Sequence[Contract]
) -> None:
    """Append contract rows to ``table`` as one Arrow batch.

    ``executemany`` converts row by row, and for every row DuckDB's Python binding probes for
    pandas; with pandas absent each probe is a failed, uncached import, about 1 ms a row (#347).
    """
    if not rows:
        return
    batch = pa.Table.from_pylist(
        [row.model_dump(by_alias=True, mode="python") for row in rows],
        schema=arrow_schema(model),
    )
    names = ", ".join(_quote(name) for name in column_names(model))
    con.register("_insert_batch", batch)
    try:
        con.execute(f"INSERT INTO {table} ({names}) SELECT {names} FROM _insert_batch")
    finally:
        con.unregister("_insert_batch")
