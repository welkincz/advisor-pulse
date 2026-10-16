"""Incremental ingest for the three Teradata-style HR tables."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import duckdb
import xxhash

from pulse.contracts import Contract, column_names
from pulse.contracts.enums import LoadStatus
from pulse.contracts.meta import LoadManifest, Watermark
from pulse.contracts.raw import RawTeradataAdvisor, RawTeradataAssignment, RawTeradataBranch
from pulse.contracts.sources import TeradataAdvisor, TeradataAssignment, TeradataBranch
from pulse.ingest import meta
from pulse.warehouse import transaction


@dataclass(frozen=True)
class HRLoadResult:
    rows_read: int
    rows_loaded: int
    skipped: bool


@dataclass(frozen=True)
class _Table:
    name: str
    key: str
    source_model: type[Contract]
    raw_model: type[Contract]

    @property
    def raw_name(self) -> str:
        return f"raw.teradata__{self.name.lower()}"


_TABLES = (
    _Table("ADVSR", "ADVSR_ID", TeradataAdvisor, RawTeradataAdvisor),
    _Table("ADVSR_ASGN", "ASGN_ID", TeradataAssignment, RawTeradataAssignment),
    _Table("BRNCH", "BRNCH_ID", TeradataBranch, RawTeradataBranch),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _raw_row(
    source: Contract,
    table: _Table,
    *,
    batch_id: str,
    source_file: str,
    source_row: int,
    loaded_at: datetime,
) -> Contract:
    business = source.model_dump(by_alias=True, mode="json")
    canonical = json.dumps(business, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return table.raw_model.model_validate(
        {
            **source.model_dump(by_alias=True, mode="python"),
            "_batch_id": batch_id,
            "_source_file": source_file,
            "_source_row": source_row,
            "_row_hash": xxhash.xxh64_hexdigest(canonical.encode("utf-8")),
            "_loaded_at": loaded_at,
        }
    )


def _insert_rows(
    con: duckdb.DuckDBPyConnection, table: _Table, rows: list[Contract], batch_id: str
) -> None:
    con.execute(f"DELETE FROM {table.raw_name} WHERE _batch_id = ?", [batch_id])
    if not rows:
        return
    columns = column_names(table.raw_model)
    quoted = ", ".join(f'"{name}"' for name in columns)
    marks = ", ".join("?" for _ in columns)
    sql = f"INSERT INTO {table.raw_name} ({quoted}) VALUES ({marks})"
    values = [list(row.model_dump(by_alias=True, mode="python").values()) for row in rows]
    con.executemany(sql, values)


def load_teradata_hr(
    warehouse: duckdb.DuckDBPyConnection,
    sqlite_path: Path,
    *,
    run_id: str,
    loaded_at: datetime,
) -> HRLoadResult:
    """Load valid rows newer than each table's high-water mark as one atomic batch.

    The physical SQLite snapshot contains CLNT too. Its manifest key has an ``#hr``
    suffix so a separate client loader can consume the same file independently.
    """
    if loaded_at.tzinfo is None:
        raise ValueError("loaded_at must have a timezone")
    file_sha = _sha256(sqlite_path)
    source_file = f"teradata/{sqlite_path.name}"
    manifest_path = f"{source_file}#hr"
    if meta.is_file_loaded(warehouse, manifest_path, file_sha):
        return HRLoadResult(rows_read=0, rows_loaded=0, skipped=True)

    batch_id = f"{run_id}:teradata:{file_sha[:12]}:hr"
    batches: list[tuple[_Table, list[Contract], datetime | None]] = []
    rows_read = 0
    uri = sqlite_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as source:
        source.row_factory = sqlite3.Row
        for table in _TABLES:
            watermark = meta.get_watermark_value(warehouse, "teradata", table.name)
            selected: list[Contract] = []
            maximum: datetime | None = None
            for row_number, row in enumerate(
                source.execute(f"SELECT * FROM {table.name} ORDER BY {table.key}")
            ):
                rows_read += 1
                try:
                    validated = table.source_model.model_validate(dict(row))
                except ValueError as exc:
                    raise ValueError(f"{table.name} row {row_number}: {exc}") from exc
                updated = _utc(cast("datetime", validated.model_dump()["last_updated_ts"]))
                if watermark is not None and updated <= _utc(watermark):
                    continue
                selected.append(
                    _raw_row(
                        validated,
                        table,
                        batch_id=batch_id,
                        source_file=source_file,
                        source_row=row_number,
                        loaded_at=loaded_at,
                    )
                )
                maximum = updated if maximum is None else max(maximum, updated)
            batches.append((table, selected, maximum))

    # A concurrently replaced snapshot must not be committed under the previous hash.
    if _sha256(sqlite_path) != file_sha:
        raise ValueError(f"Source changed while reading: {sqlite_path}")

    rows_loaded = sum(len(rows) for _, rows, _ in batches)
    with transaction(warehouse):
        for table, rows, maximum in batches:
            _insert_rows(warehouse, table, rows, batch_id)
            if maximum is not None:
                meta.set_watermark(
                    warehouse,
                    Watermark(
                        source="teradata",
                        table_name=table.name,
                        watermark_column="LAST_UPD_TS",
                        watermark_value=maximum,
                        updated_at=loaded_at,
                        run_id=run_id,
                    ),
                )
        meta.record_manifest(
            warehouse,
            LoadManifest(
                file_path=manifest_path,
                file_sha256=file_sha,
                source="teradata",
                table_name="ADVSR+ADVSR_ASGN+BRNCH",
                batch_id=batch_id,
                row_count=rows_read,
                rows_loaded=rows_loaded,
                rows_quarantined=0,
                status=LoadStatus.LOADED,
                loaded_at=loaded_at,
                run_id=run_id,
            ),
        )
    return HRLoadResult(rows_read=rows_read, rows_loaded=rows_loaded, skipped=False)
