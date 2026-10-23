"""Publish contract-checked marts and documents for the static weekly report."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from pulse.contracts import Contract, arrow_schema, column_names
from pulse.contracts.enums import KpiCode, OrgLevel, StageStatus
from pulse.contracts.exports import (
    EXPORT_TABLE_CONTRACTS,
    ExportFile,
    Manifest,
    NarrativeFile,
    OrgWeekly,
    PipelineGraph,
    RunLogExport,
    SummaryKpi,
    WeeklyReport,
)
from pulse.export.publish import (
    DEFAULT_FILE_BYTES,
    DEFAULT_TOTAL_BYTES,
    publish_directory,
)

ROW_GROUP_SIZE = 8_192
NARRATIVE_WINDOW_WEEKS = 26

_ORDER = {
    "org_weekly": "iso_week_id, level, node_id",
    "org_quarterly": "fiscal_quarter_id, level, node_id",
    "advisor_weekly": "iso_week_id, advisor_id",
    "weekly_report": "iso_week_id, level, node_id, kpi_code",
    "geo_weekly": "iso_week_id, fsa_code, district_code",
    "dq_weekly": "iso_week_id, rule_id",
    "portfolio_weekly": "iso_week_id, portfolio_id",
}


def _plain(value: object) -> object:
    return value.value if isinstance(value, StrEnum) else value


def _mart_rows(
    warehouse: duckdb.DuckDBPyConnection,
    model: type[Contract],
    *,
    first_week: str | None = None,
    latest_week: str | None = None,
) -> list[Contract]:
    name = model.contract_name
    columns = column_names(model)
    projection = ", ".join(f'"{column}"' for column in columns)
    where = " WHERE iso_week_id BETWEEN ? AND ?" if first_week and latest_week else ""
    params = [first_week, latest_week] if where else []
    cursor = warehouse.execute(
        f"SELECT {projection} FROM marts.mart_{name}{where} ORDER BY {_ORDER[name]}", params
    )
    return [model.model_validate(dict(zip(columns, row, strict=True))) for row in cursor.fetchall()]


def _write_json(path: Path, document: Contract, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = document.model_dump_json(indent=None if compact else 2)
    path.write_text(contents + "\n", encoding="utf-8")


def _entry(root: Path, name: str, rows: int | None) -> ExportFile:
    data = (root / name).read_bytes()
    return ExportFile(
        name=name, sha256=hashlib.sha256(data).hexdigest(), rows=rows, bytes=len(data)
    )


def _write_parquet(path: Path, model: type[Contract], rows: list[Contract]) -> None:
    records = [
        {name: _plain(value) for name, value in row.model_dump(by_alias=True).items()}
        for row in rows
    ]
    table = pa.Table.from_pylist(records, schema=arrow_schema(model))
    pq.write_table(table, path, compression="zstd", row_group_size=ROW_GROUP_SIZE)


def publish_run_log(
    output_dir: Path,
    run_log: RunLogExport,
    *,
    max_total_bytes: int = DEFAULT_TOTAL_BYTES,
    max_file_bytes: int = DEFAULT_FILE_BYTES,
) -> None:
    """Republish ``output_dir`` with only ``run_log.json`` replaced; every other file stays.

    ``run_log.json`` is not listed in the manifest, so the manifest's hashes still hold.
    """
    if not run_log.runs:
        raise ValueError("run_log must contain the current run")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_dir.parent) as directory:
        temporary = Path(directory)
        staging = temporary / "data"
        if output_dir.exists():
            shutil.copytree(output_dir, staging)
        else:
            staging.mkdir()
        _write_json(staging / "run_log.json", run_log)
        publish_directory(
            staging,
            output_dir,
            temporary,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
        )


def export_web(
    warehouse: duckdb.DuckDBPyConnection,
    output_dir: Path,
    *,
    run_log: RunLogExport,
    pipeline_graph: PipelineGraph,
    narratives: Mapping[str, NarrativeFile],
    run_id: str,
    generated_at: datetime,
    max_total_bytes: int = DEFAULT_TOTAL_BYTES,
    max_file_bytes: int = DEFAULT_FILE_BYTES,
    has_fsa_boundaries: bool = False,
) -> Manifest | None:
    """Stage and validate all files; publish only after the complete export fits budget.

    A failed run writes just ``run_log.json`` into the existing directory. All other
    outputs remain the last successful weekly report.
    """
    if not run_log.runs:
        raise ValueError("run_log must contain the current run")
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must have a timezone")
    if max_total_bytes < 1 or max_file_bytes < 1:
        raise ValueError("export byte budgets must be positive")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if run_log.runs[0].status is StageStatus.FAILED:
        publish_run_log(
            output_dir, run_log, max_file_bytes=max_file_bytes, max_total_bytes=max_total_bytes
        )
        return None

    with tempfile.TemporaryDirectory(dir=output_dir.parent) as directory:
        temporary = Path(directory)
        staging = temporary / "data"
        staging.mkdir()
        files: list[ExportFile] = []
        org_rows = _mart_rows(warehouse, OrgWeekly)
        weeks = sorted({row.iso_week_id for row in org_rows if isinstance(row, OrgWeekly)})
        if not weeks:
            raise ValueError("mart_org_weekly contains no reporting weeks")
        latest = weeks[-1]
        latest_monday = date.fromisocalendar(int(latest[:4]), int(latest[6:]), 1)
        narrative_monday = latest_monday - timedelta(weeks=NARRATIVE_WINDOW_WEEKS - 1)
        narrative_first = (
            f"{narrative_monday.isocalendar().year}-W{narrative_monday.isocalendar().week:02d}"
        )
        tables = {"org_weekly": org_rows}
        for model in EXPORT_TABLE_CONTRACTS:
            if model is OrgWeekly:
                continue
            window = {"advisor_weekly": 26, "geo_weekly": 13, "portfolio_weekly": 26}.get(
                model.contract_name
            )
            first = latest_monday - timedelta(weeks=window - 1) if window else None
            first_week = (
                f"{first.isocalendar().year}-W{first.isocalendar().week:02d}" if first else None
            )
            tables[model.contract_name] = _mart_rows(
                warehouse, model, first_week=first_week, latest_week=latest if first else None
            )
        for model in EXPORT_TABLE_CONTRACTS:
            name = f"{model.contract_name}.parquet"
            rows = tables[model.contract_name]
            _write_parquet(staging / name, model, rows)
            files.append(_entry(staging, name, len(rows)))

        report = tables["weekly_report"]
        summary = [
            SummaryKpi(
                kpi_code=row.kpi_code,
                value=row.value,
                prior_week_value=row.prior_week_value,
                wow_pct=row.wow_pct,
                flag=row.flag,
            )
            for row in report
            if isinstance(row, WeeklyReport)
            and row.iso_week_id == latest
            and row.level is OrgLevel.NATIONAL
        ]
        if not summary:
            raise ValueError(f"No national weekly report summary for {latest}")
        # The lead KPI first, so a reader of the manifest sees it before the rest.
        summary.sort(key=lambda kpi: kpi.kpi_code is not KpiCode.PRTF_CONTACT_12M)

        _write_json(staging / "run_log.json", run_log)
        _write_json(staging / "pipeline_graph.json", pipeline_graph)
        files.append(_entry(staging, "pipeline_graph.json", None))
        for week, narrative in sorted(narratives.items()):
            if week != narrative.iso_week_id or "/" in week or ".." in week:
                raise ValueError(f"Narrative week does not match key: {week}")
            if not narrative_first <= week <= latest:
                continue
            name = f"narratives/{week}.json"
            _write_json(staging / name, narrative, compact=True)
            files.append(_entry(staging, name, None))

        manifest = Manifest(
            run_id=run_id,
            generated_at=generated_at,
            latest_week=latest,
            weeks_available=weeks,
            files=files,
            summary=summary,
            has_fsa_boundaries=has_fsa_boundaries,
        )
        _write_json(staging / "manifest.json", manifest)
        publish_directory(
            staging,
            output_dir,
            temporary,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
        )
    return manifest
