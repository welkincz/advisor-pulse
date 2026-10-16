"""Incremental ingestion of synthetic Snowflake activity Parquet partitions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import xxhash

from pulse.contracts import column_names
from pulse.contracts.enums import LoadStatus, StageStatus
from pulse.contracts.meta import LoadManifest, Watermark
from pulse.contracts.raw import RawSnowflakeActivity
from pulse.contracts.sources import SnowflakeActivity
from pulse.ingest import meta
from pulse.ingest.validate import validate_rows
from pulse.runner.stage import StageResult
from pulse.warehouse import transaction


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _insert_rows(
    warehouse: duckdb.DuckDBPyConnection, rows: list[RawSnowflakeActivity], batch_id: str
) -> None:
    warehouse.execute("DELETE FROM raw.snowflake__activity WHERE _batch_id = ?", [batch_id])
    if not rows:
        return
    columns = column_names(RawSnowflakeActivity)
    quoted = ", ".join(f'"{name}"' for name in columns)
    markers = ", ".join("?" for _ in columns)
    sql = f"INSERT INTO raw.snowflake__activity ({quoted}) VALUES ({markers})"
    values = [list(row.model_dump(by_alias=True, mode="python").values()) for row in rows]
    warehouse.executemany(sql, values)


def _boundary_rows(
    warehouse: duckdb.DuckDBPyConnection, watermark: datetime | None
) -> set[tuple[str, str]]:
    if watermark is None:
        return set()
    return set(
        warehouse.execute(
            "SELECT ACTIVITY_ID, _row_hash FROM raw.snowflake__activity WHERE _EXTRACTED_AT = ?",
            [watermark],
        ).fetchall()
    )


def _load_file(
    warehouse: duckdb.DuckDBPyConnection,
    path: Path,
    source_file: str,
    file_sha: str,
    *,
    run_id: str,
    loaded_at: datetime,
) -> tuple[int, int, int]:
    table = pq.read_table(path)
    if _sha256(path) != file_sha:
        raise ValueError(f"Source changed while reading: {path}")
    path_hash = hashlib.sha256(source_file.encode()).hexdigest()[:8]
    batch_id = f"{run_id}:snowflake:{file_sha[:12]}:{path_hash}"
    watermark = meta.get_watermark_value(warehouse, "snowflake", "activity")
    if watermark is not None:
        watermark = _utc(watermark)
    boundary = _boundary_rows(warehouse, watermark)

    with transaction(warehouse):
        result = validate_rows(
            table,
            SnowflakeActivity,
            source="snowflake",
            table_name="activity",
            source_file=source_file,
            batch_id=batch_id,
            run_id=run_id,
            detected_at=loaded_at,
            warehouse=warehouse,
        )
        rejected = {row.source_row for row in result.rejected_rows}
        loaded: list[RawSnowflakeActivity] = []
        maximum: datetime | None = None
        for row_number, data in enumerate(table.to_pylist()):
            if row_number in rejected:
                continue
            source = SnowflakeActivity.model_validate(data)
            extracted = _utc(source.extracted_at)
            if watermark is not None and extracted < watermark:
                continue
            business = source.model_dump(by_alias=True, mode="json")
            canonical = json.dumps(
                business, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            row_hash = xxhash.xxh64_hexdigest(canonical.encode("utf-8"))
            if (
                watermark is not None
                and extracted == watermark
                and (source.activity_id, row_hash) in boundary
            ):
                continue
            loaded.append(
                RawSnowflakeActivity.model_validate(
                    {
                        **source.model_dump(by_alias=True, mode="python"),
                        "_batch_id": batch_id,
                        "_source_file": source_file,
                        "_source_row": row_number,
                        "_row_hash": row_hash,
                        "_loaded_at": loaded_at,
                    }
                )
            )
            maximum = extracted if maximum is None else max(maximum, extracted)
        _insert_rows(warehouse, loaded, batch_id)
        if maximum is not None:
            meta.set_watermark(
                warehouse,
                Watermark(
                    source="snowflake",
                    table_name="activity",
                    watermark_column="_EXTRACTED_AT",
                    watermark_value=maximum,
                    updated_at=loaded_at,
                    run_id=run_id,
                ),
            )
        meta.record_manifest(
            warehouse,
            LoadManifest(
                file_path=source_file,
                file_sha256=file_sha,
                source="snowflake",
                table_name="activity",
                batch_id=batch_id,
                row_count=len(table),
                rows_loaded=len(loaded),
                rows_quarantined=len(result.rejected_rows),
                status=LoadStatus.LOADED,
                loaded_at=loaded_at,
                run_id=run_id,
            ),
        )
    return len(table), len(loaded), len(result.rejected_rows)


def load_snowflake_activity(
    warehouse: duckdb.DuckDBPyConnection,
    sources_root: Path,
    *,
    run_id: str,
    loaded_at: datetime,
) -> StageResult:
    """Load new activity partitions, preserving per-file atomicity and source row numbers."""
    if loaded_at.tzinfo is None:
        raise ValueError("loaded_at must have a timezone")
    paths = sorted((sources_root / "snowflake/activity").rglob("*.parquet"))
    if not paths:
        return StageResult(StageStatus.SKIPPED, 0, 0, 0, "No activity partitions found")

    rows_in = rows_out = quarantined = skipped = 0
    for path in paths:
        source_file = path.relative_to(sources_root).as_posix()
        file_sha = _sha256(path)
        if meta.is_file_loaded(warehouse, source_file, file_sha):
            skipped += 1
            continue
        read, loaded, rejected = _load_file(
            warehouse, path, source_file, file_sha, run_id=run_id, loaded_at=loaded_at
        )
        rows_in += read
        rows_out += loaded
        quarantined += rejected
    if skipped == len(paths):
        return StageResult(StageStatus.SKIPPED, 0, 0, 0, f"SKIPPED_DUPLICATE: {skipped} files")
    return StageResult(
        StageStatus.SUCCESS,
        rows_in,
        rows_out,
        quarantined,
        f"Loaded {len(paths) - skipped} files; skipped {skipped} duplicates",
    )
