"""Pipeline metadata and quarantine contracts (PLAN.md §6.5)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from pulse.contracts import patterns
from pulse.contracts.base import Contract
from pulse.contracts.enums import CheckSeverity, CheckStatus, LoadStatus, RunType, StageStatus


class Watermark(Contract):
    contract_name = "meta.watermark"
    contract_description = "High-water mark per (source, table_name). Primary key: both columns."

    source: str = Field(min_length=1)
    table_name: str = Field(min_length=1)
    watermark_column: str = Field(min_length=1)
    watermark_value: datetime
    updated_at: datetime
    run_id: str = Field(min_length=1)


class LoadManifest(Contract):
    contract_name = "meta.load_manifest"
    contract_description = (
        "One row per file seen. Primary key: (file_path, file_sha256); a changed file is a new row."
    )

    file_path: str = Field(min_length=1)
    file_sha256: str = Field(pattern=patterns.SHA256)
    source: str = Field(min_length=1)
    table_name: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    row_count: int = Field(ge=0)
    rows_loaded: int = Field(ge=0)
    rows_quarantined: int = Field(ge=0)
    status: LoadStatus
    loaded_at: datetime
    run_id: str = Field(min_length=1)


class RunLogRow(Contract):
    contract_name = "meta.run_log"
    contract_description = "One row per stage attempt."

    run_id: str = Field(min_length=1)
    run_type: RunType
    iso_week_id: str = Field(pattern=patterns.ISO_WEEK_ID)
    stage: str = Field(min_length=1)
    attempt: int = Field(ge=1)
    status: StageStatus
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    rows_in: int | None = Field(default=None, ge=0)
    rows_out: int | None = Field(default=None, ge=0)
    rows_quarantined: int | None = Field(default=None, ge=0)
    message: str | None = None
    git_sha: str | None = None


class CheckResult(Contract):
    contract_name = "meta.check_result"
    contract_description = "One row per run check (DQ030–DQ033)."

    run_id: str = Field(min_length=1)
    check_id: str = Field(pattern=patterns.RULE_ID)
    severity: CheckSeverity
    status: CheckStatus
    observed: float | None = None
    expected: str | None = Field(default=None, description="Threshold or range, as text.")
    message: str | None = None


class RejectedRow(Contract):
    contract_name = "quarantine.rejected_rows"
    contract_description = "Rows rejected at ingest, with the rule that rejected them."

    rejected_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    table_name: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    source_row: int = Field(ge=0)
    rule_id: str = Field(pattern=patterns.RULE_ID)
    reason: str = Field(min_length=1)
    payload: str = Field(description="The rejected row as a JSON object string.")
    detected_at: datetime


META_CONTRACTS: tuple[type[Contract], ...] = (
    Watermark,
    LoadManifest,
    RunLogRow,
    CheckResult,
    RejectedRow,
)
