from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from pulse.contracts import column_names
from pulse.contracts.base import Contract
from pulse.contracts.exports import (
    AdvisorWeekly,
    DqWeekly,
    GeoWeekly,
    Manifest,
    NarrativeFile,
    OrgWeekly,
    PipelineGraph,
    RunLogExport,
    WeeklyReport,
)

MEASURES = (
    "activities_completed calls_out calls_in appointments_booked appointments_held no_shows "
    "conversions unique_clients_contacted avg_meeting_duration_min"
)
PORTFOLIO = "portfolio_clients portfolio_contacted_12m portfolio_contacted_rate_12m"


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (
            AdvisorWeekly,
            f"iso_week_id advisor_id branch_id district_code region_code {MEASURES} {PORTFOLIO}",
        ),
        (
            OrgWeekly,
            f"iso_week_id level node_id node_name parent_id active_advisors {MEASURES} "
            f"activities_per_advisor show_rate conversion_rate call_to_appt_rate {PORTFOLIO}",
        ),
        (
            WeeklyReport,
            "iso_week_id level node_id node_name parent_id kpi_code value prior_week_value "
            "wow_delta wow_pct trailing_13w_avg rank_in_parent peer_count flag",
        ),
        (
            GeoWeekly,
            f"iso_week_id fsa_code district_code active_clients activities_completed {PORTFOLIO}",
        ),
        (
            DqWeekly,
            "iso_week_id rule_id rule_name action rows_affected rows_in_batch rate",
        ),
    ],
)
def test_export_table_columns_match_dictionary(model: type[Contract], expected: str) -> None:
    assert column_names(model) == expected.split()


def _org(**changes: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "iso_week_id": "2026-W41",
        "level": "DISTRICT",
        "node_id": "GTA",
        "node_name": "GTA",
        "parent_id": "ON",
        "active_advisors": 120,
        "show_rate": 0.82,
    }
    for col in MEASURES.split():
        row.setdefault(col, 10)
    row.update(portfolio_clients=10, portfolio_contacted_12m=8)
    return {**row, **changes}


def test_rates_are_fractions() -> None:
    OrgWeekly.model_validate(_org())
    OrgWeekly.model_validate(_org(show_rate=None))
    for bad in [{"show_rate": 1.2}, {"portfolio_contacted_rate_12m": -0.1}, {"calls_out": -1}]:
        with pytest.raises(ValidationError):
            OrgWeekly.model_validate(_org(**bad))


def test_report_enums() -> None:
    row = {
        "iso_week_id": "2026-W41",
        "level": "REGION",
        "node_id": "ON",
        "node_name": "Ontario",
        "kpi_code": "SHOW_RATE",
        "flag": "UP",
    }
    WeeklyReport.model_validate(row)
    with pytest.raises(ValidationError):
        WeeklyReport.model_validate({**row, "kpi_code": "REVENUE"})
    with pytest.raises(ValidationError):
        WeeklyReport.model_validate({**row, "rank_in_parent": 0})


def test_geo_allows_unknown_fsa() -> None:
    row = {
        "iso_week_id": "2026-W41",
        "fsa_code": "UNK",
        "district_code": "GTA",
        "active_clients": 3,
        "activities_completed": 2,
        "portfolio_clients": 3,
        "portfolio_contacted_12m": 2,
    }
    GeoWeekly.model_validate(row)
    with pytest.raises(ValidationError):
        GeoWeekly.model_validate({**row, "fsa_code": "XYZ"})


def _manifest(**changes: Any) -> dict[str, Any]:
    doc = {
        "run_id": "r",
        "generated_at": "2026-10-12T12:00:00Z",
        "latest_week": "2026-W41",
        "weeks_available": ["2026-W40", "2026-W41"],
        "files": [{"name": "org_weekly.parquet", "sha256": "a" * 64, "rows": 10, "bytes": 2048}],
        "summary": [{"kpi_code": "ACT_PER_ADV", "value": 31.5, "flag": "UP"}],
    }
    return {**doc, **changes}


def test_manifest() -> None:
    m = Manifest.model_validate(_manifest())
    assert m.schema_version == "1.0.0"
    assert m.has_fsa_boundaries is False
    with pytest.raises(ValidationError):
        Manifest.model_validate(_manifest(weeks_available=[]))


def _stage(status: str = "SUCCESS", attempt: int = 1) -> dict[str, Any]:
    return {
        "stage": "ingest",
        "attempt": attempt,
        "status": status,
        "started_at": "2026-10-12T11:00:00Z",
    }


def test_run_log_keeps_at_most_12_runs() -> None:
    run = {
        "run_id": "r",
        "run_type": "WEEKLY",
        "iso_week_id": "2026-W41",
        "status": "WARN",
        "started_at": "2026-10-12T11:00:00Z",
        "stages": [_stage("FAILED"), _stage("SUCCESS", 2)],
        "checks": [{"check_id": "DQ031", "severity": "WARN", "status": "WARN"}],
    }
    doc = {"generated_at": "2026-10-12T12:00:00Z", "runs": [run] * 12}
    RunLogExport.model_validate(doc)
    with pytest.raises(ValidationError):
        RunLogExport.model_validate({**doc, "runs": [run] * 13})


def test_pipeline_graph() -> None:
    doc = {
        "nodes": [
            {
                "id": "src.snowflake",
                "label": "Snowflake",
                "kind": "SOURCE",
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "dbt.staging",
                "label": "staging",
                "kind": "DBT_LAYER",
                "models": ["stg_activity"],
                "position": {"x": 200, "y": 0},
            },
        ],
        "edges": [{"id": "e1", "source": "src.snowflake", "target": "dbt.staging"}],
    }
    PipelineGraph.model_validate(doc)
    with pytest.raises(ValidationError):
        PipelineGraph.model_validate({**doc, "nodes": []})


def _narrative(**bullet: Any) -> dict[str, Any]:
    return {
        "iso_week_id": "2026-W41",
        "generated_at": "2026-10-12T12:00:00Z",
        "narratives": [
            {
                "node_id": "GTA",
                "level": "DISTRICT",
                "headline": "Activity per advisor rose 4.2% week over week.",
                "bullets": [
                    {"text": "Activity per advisor rose to 31.5.", "fact_ids": ["F1"], **bullet}
                ],
                "facts_used": [
                    {
                        "fact_id": "F1",
                        "node_id": "GTA",
                        "kpi_code": "ACT_PER_ADV",
                        "iso_week_id": "2026-W41",
                        "value": 31.5,
                        "wow_pct": 0.042,
                    }
                ],
                "model": "claude-opus-5-5",
                "prompt_version": "v1",
                "validated": True,
                "fallback": False,
            }
        ],
    }


def test_narrative_bullets_must_cite_facts() -> None:
    NarrativeFile.model_validate(_narrative())
    with pytest.raises(ValidationError):
        NarrativeFile.model_validate(_narrative(fact_ids=[]))
    with pytest.raises(ValidationError):
        NarrativeFile.model_validate(_narrative(fact_ids=["fact-1"]))
