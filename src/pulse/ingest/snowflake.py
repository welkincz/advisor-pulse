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
from pulse.ingest.validate import SchemaDriftError, validate_rows
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


def _batch_id(run_id: str, source_file: str, file_sha: str) -> str:
    path_hash = hashlib.sha256(source_file.encode()).hexdigest()[:8]
    return f"{run_id}:snowflake:{file_sha[:12]}:{path_hash}"


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
    batch_id = _batch_id(run_id, source_file, file_sha)
    watermark = meta.get_watermark_value(warehouse, "snowflake", "activity")
    if watermark is not None:
        watermark = _utc(watermark)
    replay = bool(meta.get_manifest(warehouse, source_file))

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
        valid_indices = (index for index in range(len(table)) if index not in rejected)
        for row_number, data in zip(valid_indices, result.valid_rows.to_pylist(), strict=True):
            source = SnowflakeActivity.model_validate(data)
            extracted = _utc(source.extracted_at)
            if not replay and watermark is not None and extracted < watermark:
                continue
            business = source.model_dump(by_alias=True, mode="json")
            canonical = json.dumps(
                business, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            row_hash = xxhash.xxh64_hexdigest(canonical.encode("utf-8"))
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
        if maximum is not None and (watermark is None or maximum > watermark):
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
    drifted: list[str] = []
    for path in paths:
        source_file = path.relative_to(sources_root).as_posix()
        file_sha = _sha256(path)
        if meta.is_file_loaded(warehouse, source_file, file_sha):
            skipped += 1
            continue
        try:
            read, loaded, rejected = _load_file(
                warehouse, path, source_file, file_sha, run_id=run_id, loaded_at=loaded_at
            )
        except SchemaDriftError:
            drifted.append(source_file)
            rows_in += pq.read_metadata(path).num_rows
            with transaction(warehouse):
                meta.record_manifest(
                    warehouse,
                    LoadManifest(
                        file_path=source_file,
                        file_sha256=file_sha,
                        source="snowflake",
                        table_name="activity",
                        batch_id=_batch_id(run_id, source_file, file_sha),
                        row_count=pq.read_metadata(path).num_rows,
                        rows_loaded=0,
                        rows_quarantined=0,
                        status=LoadStatus.FAILED,
                        loaded_at=loaded_at,
                        run_id=run_id,
                    ),
                )
            continue
        rows_in += read
        rows_out += loaded
        quarantined += rejected
    if skipped == len(paths):
        return StageResult(StageStatus.SKIPPED, 0, 0, 0, f"SKIPPED_DUPLICATE: {skipped} files")
    if drifted:
        return StageResult(
            StageStatus.WARN,
            rows_in,
            rows_out,
            quarantined,
            f"DQ006 failed files: {', '.join(drifted)}",
        )
    return StageResult(
        StageStatus.SUCCESS,
        rows_in,
        rows_out,
        quarantined,
        f"Loaded {len(paths) - skipped} files; skipped {skipped} duplicates",
    )
