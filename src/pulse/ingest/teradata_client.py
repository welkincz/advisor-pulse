"""Load the synthetic Teradata client snapshot and daily CSV changes."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import xxhash

from pulse.contracts import column_names, columns
from pulse.contracts.enums import LoadStatus, StageStatus
from pulse.contracts.meta import LoadManifest, Watermark
from pulse.contracts.raw import RawTeradataClient
from pulse.contracts.sources import TeradataClient
from pulse.ingest import meta
from pulse.ingest.validate import SchemaDriftError, validate_rows
from pulse.runner.stage import StageResult
from pulse.warehouse import insert_contracts, transaction

_COLUMNS = column_names(TeradataClient)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _text_table(rows: Sequence[Mapping[str, object]], names: list[str]) -> pa.Table:
    return pa.table(
        {
            name: pa.array(
                [str(value) if (value := row.get(name)) is not None else None for row in rows],
                type=pa.string(),
            )
            for name in names
        }
    )


def _snapshot(path: Path) -> pa.Table:
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as source:
        source.row_factory = sqlite3.Row
        cursor = source.execute("SELECT * FROM CLNT ORDER BY CLNT_ID")
        names = [field[0] for field in cursor.description]
        declared = {
            name: kind.upper() for _, name, kind, *_ in source.execute('PRAGMA table_info("CLNT")')
        }
        for column in columns(TeradataClient):
            actual = declared.get(column.name)
            expected = (
                "INTEGER"
                if column.python_type is int
                else "DATE"
                if column.python_type is date
                else "TIMESTAMP"
                if column.python_type is datetime
                else "VARCHAR"
            )
            if actual is not None and (
                actual != expected
                if expected != "VARCHAR"
                else not actual.startswith(("VARCHAR", "CHAR", "TEXT"))
            ):
                raise SchemaDriftError(
                    f"DQ006 CLNT.{column.name}: expected {expected}, got {actual}"
                )
        rows = [dict(row) for row in cursor]
    return _text_table(rows, names)


def _parse_record(text: str) -> list[str] | None:
    try:
        return next(csv.reader([text], strict=True))
    except csv.Error:
        return None


def _csv_delta(path: Path) -> tuple[pa.Table, dict[int, str]]:
    rows: list[dict[str, str | None]] = []
    malformed: dict[int, str] = {}
    lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    header = _parse_record(lines[0]) if lines else None
    if not header:
        raise SchemaDriftError(f"DQ006 missing CSV header: {path}")
    if len(header) != len(set(header)):
        raise SchemaDriftError(f"DQ006 repeated CSV columns: {path}")
    index = 1
    while index < len(lines):
        raw = lines[index]
        index += 1
        values = _parse_record(raw)
        while values is None and index < len(lines):
            candidate = _parse_record(lines[index])
            if candidate and len(candidate) == len(header) and candidate[0].startswith("CLI-"):
                break
            raw += lines[index]
            index += 1
            values = _parse_record(raw)
        if values is None or len(values) != len(header):
            malformed[len(rows)] = raw
            rows.append(dict.fromkeys(header))
            continue
        rows.append({name: value or None for name, value in zip(header, values, strict=True)})
    return _text_table(rows, header), malformed


def _batch_id(run_id: str, source_file: str, file_sha: str) -> str:
    path_hash = hashlib.sha256(source_file.encode()).hexdigest()[:8]
    return f"{run_id}:teradata:clnt:{file_sha[:12]}:{path_hash}"


def _insert_rows(
    warehouse: duckdb.DuckDBPyConnection, rows: list[RawTeradataClient], batch_id: str
) -> None:
    warehouse.execute("DELETE FROM raw.teradata__clnt WHERE _batch_id = ?", [batch_id])
    if not rows:
        return
    insert_contracts(warehouse, "raw.teradata__clnt", RawTeradataClient, rows)


def _load_file(
    warehouse: duckdb.DuckDBPyConnection,
    path: Path,
    source_file: str,
    file_sha: str,
    *,
    snapshot: bool,
    run_id: str,
    loaded_at: datetime,
) -> tuple[int, int, int]:
    table, malformed = (_snapshot(path), {}) if snapshot else _csv_delta(path)
    if _sha256(path) != file_sha:
        raise ValueError(f"Source changed while reading: {path}")
    batch_id = _batch_id(run_id, source_file, file_sha)
    watermark = meta.get_watermark_value(warehouse, "teradata", "CLNT")
    if watermark is not None:
        watermark = _utc(watermark)
    latest_manifest = warehouse.execute(
        "SELECT status FROM meta.load_manifest WHERE file_path = ? "
        "ORDER BY loaded_at DESC, rowid DESC LIMIT 1",
        [source_file],
    ).fetchone()
    recovering = latest_manifest is not None and latest_manifest[0] == LoadStatus.FAILED.value

    with transaction(warehouse):
        validated = validate_rows(
            table,
            TeradataClient,
            source="teradata",
            table_name="CLNT",
            source_file=source_file.removesuffix("#clnt"),
            batch_id=batch_id,
            run_id=run_id,
            detected_at=loaded_at,
            warehouse=warehouse,
            allow_text_coercion=True,
        )
        if malformed:
            meta.write_rejected_rows(
                warehouse,
                [
                    row.model_copy(
                        update={"payload": json.dumps({"raw_text": malformed[row.source_row]})}
                    )
                    for row in validated.rejected_rows
                    if row.source_row in malformed
                ],
            )
        rejected = {row.source_row for row in validated.rejected_rows}
        selected: list[RawTeradataClient] = []
        maximum: datetime | None = None
        valid_indices = (index for index in range(len(table)) if index not in rejected)
        for row_number, data in zip(valid_indices, validated.valid_rows.to_pylist(), strict=True):
            client = TeradataClient.model_validate(data)
            updated = _utc(client.last_updated_ts)
            if not recovering and watermark is not None and updated <= watermark:
                continue
            business = client.model_dump(by_alias=True, mode="json")
            canonical = json.dumps(
                business, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            selected.append(
                RawTeradataClient.model_validate(
                    {
                        **client.model_dump(by_alias=True, mode="python"),
                        "_batch_id": batch_id,
                        "_source_file": source_file.removesuffix("#clnt"),
                        "_source_row": row_number,
                        "_row_hash": xxhash.xxh64_hexdigest(canonical.encode()),
                        "_loaded_at": loaded_at,
                    }
                )
            )
            maximum = updated if maximum is None else max(maximum, updated)
        _insert_rows(warehouse, selected, batch_id)
        if maximum is not None and (watermark is None or maximum > watermark):
            meta.set_watermark(
                warehouse,
                Watermark(
                    source="teradata",
                    table_name="CLNT",
                    watermark_column="LAST_UPD_TS",
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
                source="teradata",
                table_name="CLNT",
                batch_id=batch_id,
                row_count=len(table),
                rows_loaded=len(selected),
                rows_quarantined=len(validated.rejected_rows),
                status=LoadStatus.LOADED,
                loaded_at=loaded_at,
                run_id=run_id,
            ),
        )
    return len(table), len(selected), len(validated.rejected_rows)


def load_teradata_client(
    warehouse: duckdb.DuckDBPyConnection,
    sources_root: Path,
    *,
    run_id: str,
    loaded_at: datetime,
) -> StageResult:
    """Load the immutable CLNT snapshot, then CSV deltas in file-date order."""
    if loaded_at.tzinfo is None:
        raise ValueError("loaded_at must have a timezone")
    base = sources_root / "teradata"
    snapshot = base / "edw.sqlite"
    files = [(snapshot, "teradata/edw.sqlite#clnt", True)]
    files.extend(
        (path, path.relative_to(sources_root).as_posix(), False)
        for path in sorted(base.glob("client_*.csv"))
    )
    rows_in = rows_out = quarantined = skipped = watermark_skipped = 0
    failed: list[str] = []
    for path, source_file, is_snapshot in files:
        file_sha = _sha256(path)
        if meta.is_file_loaded(warehouse, source_file, file_sha):
            skipped += 1
            continue
        try:
            read, loaded, rejected = _load_file(
                warehouse,
                path,
                source_file,
                file_sha,
                snapshot=is_snapshot,
                run_id=run_id,
                loaded_at=loaded_at,
            )
        except SchemaDriftError as exc:
            failed.append(f"{source_file}: {exc}")
            with transaction(warehouse):
                meta.record_manifest(
                    warehouse,
                    LoadManifest(
                        file_path=source_file,
                        file_sha256=file_sha,
                        source="teradata",
                        table_name="CLNT",
                        batch_id=_batch_id(run_id, source_file, file_sha),
                        row_count=0,
                        rows_loaded=0,
                        rows_quarantined=0,
                        status=LoadStatus.FAILED,
                        loaded_at=loaded_at,
                        run_id=run_id,
                    ),
                )
            if is_snapshot and not any(
                entry.status is LoadStatus.LOADED
                for entry in meta.get_manifest(warehouse, source_file)
            ):
                return StageResult(StageStatus.FAILED, rows_in, rows_out, quarantined, exc.args[0])
            continue
        rows_in += read
        rows_out += loaded
        quarantined += rejected
        watermark_skipped += int(read > rejected and loaded == 0)
    if skipped == len(files):
        return StageResult(StageStatus.SKIPPED, 0, 0, 0, f"SKIPPED_DUPLICATE: {skipped} files")
    if failed:
        return StageResult(
            StageStatus.WARN, rows_in, rows_out, quarantined, f"DQ006 failed: {'; '.join(failed)}"
        )
    return StageResult(
        StageStatus.SUCCESS,
        rows_in,
        rows_out,
        quarantined,
        f"Processed {len(files) - skipped} files; skipped {skipped} duplicates; "
        f"{watermark_skipped} had no new rows after the watermark",
    )
