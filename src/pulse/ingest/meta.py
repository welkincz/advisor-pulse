"""Repository API over the ``meta`` and ``quarantine`` schemas.

Each function is a single statement, so it is atomic on its own and joins the caller's
transaction when called inside ``pulse.warehouse.transaction``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any

import duckdb

from pulse.contracts import Contract, column_names
from pulse.contracts.enums import LoadStatus
from pulse.contracts.meta import CheckResult, LoadManifest, RejectedRow, RunLogRow, Watermark
from pulse.warehouse import TABLES_BY_NAME, qualified


class WatermarkRegressionError(ValueError):
    """Raised when a watermark would move backwards."""


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _values(row: Contract) -> list[Any]:
    data = row.model_dump(by_alias=True, mode="python")
    return [v.value if isinstance(v, StrEnum) else v for v in data.values()]


def _upsert_sql(table: str) -> str:
    spec = TABLES_BY_NAME[table]
    cols = column_names(spec.model)
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(_quote(c) for c in cols)
    sql = f"INSERT INTO {qualified(table)} ({col_list}) VALUES ({placeholders})"
    if spec.primary_key:
        updates = [c for c in cols if c not in spec.primary_key]
        sql += (
            f" ON CONFLICT ({', '.join(_quote(c) for c in spec.primary_key)}) DO UPDATE SET "
            + ", ".join(f"{_quote(c)} = excluded.{_quote(c)}" for c in updates)
        )
    return sql


def _write(con: duckdb.DuckDBPyConnection, table: str, rows: Sequence[Contract]) -> None:
    if rows:
        con.executemany(_upsert_sql(table), [_values(r) for r in rows])


def _read[M: Contract](
    con: duckdb.DuckDBPyConnection,
    table: str,
    model: type[M],
    where: str = "",
    params: Sequence[Any] = (),
    order_by: str = "",
) -> list[M]:
    cols = column_names(model)
    sql = f"SELECT {', '.join(_quote(c) for c in cols)} FROM {qualified(table)}"
    if where:
        sql += f" WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    return [
        model.model_validate(dict(zip(cols, r, strict=True)))
        for r in con.execute(sql, params).fetchall()
    ]


# ── Watermarks ───────────────────────────────────────────────────────────────


def get_watermark(con: duckdb.DuckDBPyConnection, source: str, table_name: str) -> Watermark | None:
    rows = _read(
        con, "meta.watermark", Watermark, "source = ? AND table_name = ?", [source, table_name]
    )
    return rows[0] if rows else None


def get_watermark_value(
    con: duckdb.DuckDBPyConnection, source: str, table_name: str
) -> datetime | None:
    wm = get_watermark(con, source, table_name)
    return wm.watermark_value if wm else None


def set_watermark(
    con: duckdb.DuckDBPyConnection, watermark: Watermark, *, allow_regression: bool = False
) -> None:
    """Upsert a watermark.

    Refuses to move it backwards unless ``allow_regression`` (used by backfill rebuilds).
    """
    current = get_watermark(con, watermark.source, watermark.table_name)
    if current and watermark.watermark_value < current.watermark_value and not allow_regression:
        raise WatermarkRegressionError(
            f"{watermark.source}.{watermark.table_name}: {watermark.watermark_value.isoformat()} "
            f"is before current {current.watermark_value.isoformat()}"
        )
    _write(con, "meta.watermark", [watermark])


# ── Load manifest ────────────────────────────────────────────────────────────


def record_manifest(con: duckdb.DuckDBPyConnection, entry: LoadManifest) -> None:
    """Upsert by (file_path, file_sha256), so a FAILED file that later loads becomes LOADED."""
    _write(con, "meta.load_manifest", [entry])


def is_file_loaded(con: duckdb.DuckDBPyConnection, file_path: str, file_sha256: str) -> bool:
    """True only for this exact content: the same path with a new hash is a new file."""
    row = con.execute(
        f"SELECT 1 FROM {qualified('meta.load_manifest')} "
        "WHERE file_path = ? AND file_sha256 = ? AND status = ?",
        [file_path, file_sha256, LoadStatus.LOADED.value],
    ).fetchone()
    return row is not None


def get_manifest(
    con: duckdb.DuckDBPyConnection, file_path: str | None = None
) -> list[LoadManifest]:
    if file_path is None:
        return _read(con, "meta.load_manifest", LoadManifest, order_by="loaded_at, file_path")
    return _read(
        con, "meta.load_manifest", LoadManifest, "file_path = ?", [file_path], order_by="loaded_at"
    )


# ── Run log and checks ───────────────────────────────────────────────────────


def write_run_log(con: duckdb.DuckDBPyConnection, row: RunLogRow) -> None:
    """Upsert one stage attempt; a RUNNING row is later replaced by its final status."""
    _write(con, "meta.run_log", [row])


def get_run_log(con: duckdb.DuckDBPyConnection, run_id: str | None = None) -> list[RunLogRow]:
    if run_id is None:
        return _read(con, "meta.run_log", RunLogRow, order_by="started_at, stage, attempt")
    return _read(
        con,
        "meta.run_log",
        RunLogRow,
        "run_id = ?",
        [run_id],
        order_by="started_at, stage, attempt",
    )


def write_check_result(con: duckdb.DuckDBPyConnection, row: CheckResult) -> None:
    _write(con, "meta.check_result", [row])


def get_check_results(con: duckdb.DuckDBPyConnection, run_id: str) -> list[CheckResult]:
    return _read(con, "meta.check_result", CheckResult, "run_id = ?", [run_id], order_by="check_id")


# ── Quarantine ───────────────────────────────────────────────────────────────


def write_rejected_rows(con: duckdb.DuckDBPyConnection, rows: Sequence[RejectedRow]) -> None:
    """Upsert by rejected_id, so re-running a batch does not duplicate rejects."""
    _write(con, "quarantine.rejected_rows", rows)


def get_rejected_rows(
    con: duckdb.DuckDBPyConnection, batch_id: str | None = None
) -> list[RejectedRow]:
    if batch_id is None:
        return _read(
            con,
            "quarantine.rejected_rows",
            RejectedRow,
            order_by="source_file, source_row, rule_id",
        )
    return _read(
        con,
        "quarantine.rejected_rows",
        RejectedRow,
        "batch_id = ?",
        [batch_id],
        order_by="source_file, source_row, rule_id",
    )
