"""Vectorized source validation and quarantine for ingest."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import duckdb
import pyarrow as pa

from pulse.contracts import Contract, arrow_schema, columns, duckdb_columns
from pulse.contracts.enums import CheckSeverity, CheckStatus
from pulse.contracts.meta import CheckResult, RejectedRow
from pulse.ingest import meta

logger = logging.getLogger(__name__)

_REASONS = {
    "DQ001": "ACTIVITY_ID is null",
    "DQ002": "Enum value is not in the contract",
    "DQ003": "DURATION_MIN is outside 0–480",
    "DQ004": "ACTIVITY_TS is outside the allowed range",
    "DQ005": "Required value is null or a date/number cannot be parsed",
}


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _schema_check(table: pa.Table, model: type[Contract], allow_text: bool) -> tuple[str, ...]:
    expected = arrow_schema(model)
    available = set(table.column_names)
    missing = [f.name for f in expected if not f.nullable and f.name not in available]
    if missing:
        raise ValueError(f"DQ006 missing required columns: {', '.join(missing)}")
    for field in expected:
        if field.name not in available:
            continue
        actual = table.schema.field(field.name).type
        text_input = allow_text and (pa.types.is_string(actual) or pa.types.is_null(actual))
        if actual != field.type and not text_input:
            raise ValueError(f"DQ006 {field.name}: expected {field.type}, got {actual}")
    return tuple(sorted(available - set(expected.names)))


def _rule_sql(model: type[Contract]) -> str:
    conditions: list[tuple[str, str]] = []
    fields = {column.name: column for column in columns(model)}
    if "ACTIVITY_ID" in fields:
        conditions.append(('"ACTIVITY_ID" IS NULL', "DQ001"))

    types = duckdb_columns(model)
    for name, sql_type, nullable in types:
        col = _quote(name)
        if not nullable and name != "ACTIVITY_ID":
            conditions.append((f"{col} IS NULL", "DQ005"))
        if sql_type in {"DATE", "TIMESTAMP WITH TIME ZONE", "BIGINT", "DOUBLE"}:
            conditions.append(
                (f"{col} IS NOT NULL AND TRY_CAST({col} AS {sql_type}) IS NULL", "DQ005")
            )

    for name, field in fields.items():
        if issubclass(field.python_type, StrEnum):
            enum_values = ", ".join(f"'{member.value}'" for member in field.python_type)
            col = _quote(name)
            conditions.append((f"{col} IS NOT NULL AND {col} NOT IN ({enum_values})", "DQ002"))

    if "DURATION_MIN" in fields:
        conditions.append(('TRY_CAST("DURATION_MIN" AS BIGINT) NOT BETWEEN 0 AND 480', "DQ003"))
    if "ACTIVITY_TS" in fields and "_EXTRACTED_AT" in fields:
        ts = 'TRY_CAST("ACTIVITY_TS" AS TIMESTAMP WITH TIME ZONE)'
        extracted = 'TRY_CAST("_EXTRACTED_AT" AS TIMESTAMP WITH TIME ZONE)'
        conditions.append(
            (
                f"{ts} < TIMESTAMPTZ '2015-01-01 00:00:00+00' "
                f"OR {ts} > {extracted} + INTERVAL 1 DAY",
                "DQ004",
            )
        )
    arms = " ".join(f"WHEN {condition} THEN '{rule}'" for condition, rule in conditions)
    return f"CASE {arms} ELSE NULL END"


@dataclass(frozen=True)
class ValidationResult:
    valid_rows: pa.Table
    rejected_rows: list[RejectedRow]
    warnings: tuple[str, ...]


def validate_rows(
    table: pa.Table,
    model: type[Contract],
    *,
    source: str,
    table_name: str,
    source_file: str,
    batch_id: str,
    run_id: str,
    detected_at: datetime,
    warehouse: duckdb.DuckDBPyConnection | None = None,
    allow_text_coercion: bool = False,
) -> ValidationResult:
    """Classify rows in DuckDB SQL, then materialize only rejected payloads in Python.

    Call inside the loader's transaction when ``warehouse`` is supplied, so rejected
    rows and DQ006 warnings commit atomically with the raw insert and watermark.
    """
    added = _schema_check(table, model, allow_text_coercion)
    warning_message = f"Extra columns ignored: {', '.join(added)}"
    warnings = (warning_message,) if added else ()
    if added:
        logger.warning("%s: %s", source_file, warning_message)

    expected = arrow_schema(model)
    for field in expected:
        if field.name not in table.column_names:
            table = table.append_column(field.name, pa.nulls(len(table), type=field.type))
    if "__source_row" in table.column_names:
        raise ValueError("Reserved source column: __source_row")
    indexed = table.append_column("__source_row", pa.array(range(len(table)), type=pa.int64()))
    con = duckdb.connect(":memory:")
    try:
        con.register("incoming", indexed)
        con.execute(
            f"CREATE TEMP TABLE verdict AS SELECT __source_row, {_rule_sql(model)} AS rule "
            "FROM incoming"
        )
        classified = con.execute(
            "SELECT __source_row, rule FROM verdict WHERE rule IS NOT NULL ORDER BY __source_row"
        ).fetchall()
        projection = ", ".join(
            f"TRY_CAST(i.{_quote(name)} AS {sql_type}) AS {_quote(name)}"
            for name, sql_type, _ in duckdb_columns(model)
        )
        valid = con.execute(
            f"SELECT {projection} FROM incoming i JOIN verdict v USING (__source_row) "
            "WHERE v.rule IS NULL ORDER BY __source_row"
        ).to_arrow_table()
    finally:
        con.close()

    rejected: list[RejectedRow] = []
    if classified:
        indices = pa.array([row_number for row_number, _ in classified], type=pa.int64())
        payloads = table.take(indices).to_pylist()
        for (row_number, rule), payload in zip(classified, payloads, strict=True):
            identity = f"{batch_id}|{source_file}|{row_number}|{rule}"
            rejected.append(
                RejectedRow(
                    rejected_id=hashlib.sha256(identity.encode()).hexdigest(),
                    run_id=run_id,
                    batch_id=batch_id,
                    source=source,
                    table_name=table_name,
                    source_file=source_file,
                    source_row=row_number,
                    rule_id=rule,
                    reason=_REASONS[rule],
                    payload=json.dumps(payload, default=str, sort_keys=True, ensure_ascii=False),
                    detected_at=detected_at,
                )
            )
    if warehouse is not None:
        meta.write_rejected_rows(warehouse, rejected)
        if warnings:
            meta.write_check_result(
                warehouse,
                CheckResult(
                    run_id=run_id,
                    check_id="DQ006",
                    severity=CheckSeverity.WARN,
                    status=CheckStatus.WARN,
                    observed=float(len(added)),
                    message=f"{source_file}: {warnings[0]}",
                ),
            )
    return ValidationResult(valid_rows=valid, rejected_rows=rejected, warnings=warnings)
