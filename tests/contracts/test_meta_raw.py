from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from pulse.contracts import column_names
from pulse.contracts.base import Contract
from pulse.contracts.meta import CheckResult, LoadManifest, RejectedRow, RunLogRow, Watermark
from pulse.contracts.raw import RAW_CONTRACTS, RawMetadata, RawSnowflakeActivity
from pulse.contracts.sources import SOURCE_CONTRACTS

META = ["_batch_id", "_source_file", "_source_row", "_row_hash", "_loaded_at"]


@pytest.mark.parametrize(("raw", "source"), list(zip(RAW_CONTRACTS, SOURCE_CONTRACTS, strict=True)))
def test_raw_is_source_columns_then_metadata(raw: type[Contract], source: type[Contract]) -> None:
    assert column_names(raw) == column_names(source) + META


def test_raw_row_validates(activity_row: dict[str, Any]) -> None:
    meta = {
        "_batch_id": "run-1:snowflake:ab12",
        "_source_file": "snowflake/activity/extract_date=2026-10-12/part-000.parquet",
        "_source_row": 0,
        "_row_hash": "9f86d081",
        "_loaded_at": "2026-10-12T07:00:00Z",
    }
    RawSnowflakeActivity.model_validate({**activity_row, **meta})
    with pytest.raises(ValidationError):
        RawSnowflakeActivity.model_validate(activity_row)
    assert column_names(RawMetadata) == META


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (Watermark, "source table_name watermark_column watermark_value updated_at run_id"),
        (
            LoadManifest,
            "file_path file_sha256 source table_name batch_id row_count rows_loaded "
            "rows_quarantined status loaded_at run_id",
        ),
        (
            RunLogRow,
            "run_id run_type iso_week_id stage attempt status started_at ended_at duration_ms "
            "rows_in rows_out rows_quarantined message git_sha",
        ),
        (CheckResult, "run_id check_id severity status observed expected message"),
        (
            RejectedRow,
            "rejected_id run_id batch_id source table_name source_file source_row rule_id "
            "reason payload detected_at",
        ),
    ],
)
def test_meta_columns_match_dictionary(model: type[Contract], expected: str) -> None:
    assert column_names(model) == expected.split()


def _run_log(**changes: Any) -> dict[str, Any]:
    row = {
        "run_id": "2026-W41-weekly-1",
        "run_type": "WEEKLY",
        "iso_week_id": "2026-W41",
        "stage": "ingest",
        "attempt": 1,
        "status": "SUCCESS",
        "started_at": "2026-10-12T11:00:00Z",
    }
    return {**row, **changes}


def test_run_log_rules() -> None:
    RunLogRow.model_validate(_run_log())
    for bad in [
        {"attempt": 0},
        {"status": "DONE"},
        {"iso_week_id": "2026-41"},
        {"iso_week_id": "2026-W54"},
        {"run_type": "HOURLY"},
        {"rows_in": -1},
    ]:
        with pytest.raises(ValidationError):
            RunLogRow.model_validate(_run_log(**bad))


def test_manifest_requires_sha256() -> None:
    row = {
        "file_path": "a.parquet",
        "file_sha256": "0" * 64,
        "source": "snowflake",
        "table_name": "activity",
        "batch_id": "b",
        "row_count": 10,
        "rows_loaded": 9,
        "rows_quarantined": 1,
        "status": "LOADED",
        "loaded_at": "2026-10-12T11:00:00Z",
        "run_id": "r",
    }
    LoadManifest.model_validate(row)
    with pytest.raises(ValidationError):
        LoadManifest.model_validate({**row, "file_sha256": "abc"})


def test_rule_ids() -> None:
    base = {"run_id": "r", "severity": "FAIL", "status": "PASS"}
    CheckResult.model_validate({**base, "check_id": "DQ030"})
    with pytest.raises(ValidationError):
        CheckResult.model_validate({**base, "check_id": "DQ30"})
