from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pytest

from pulse.contracts import ALL_CONTRACTS, REGISTRY, arrow_schema, duckdb_columns
from pulse.contracts.base import Contract, columns
from pulse.contracts.codegen import DEFAULT_OUT, main, render, stale_files, write
from pulse.contracts.exports import EXPORT_TABLE_CONTRACTS, Manifest
from pulse.contracts.raw import RAW_CONTRACTS
from pulse.contracts.sources import SOURCE_CONTRACTS, SnowflakeActivity

TABLES = [m for m in ALL_CONTRACTS if m.contract_kind == "table"]


def test_registry_covers_every_planned_contract() -> None:
    expected = {
        "snowflake__activity",
        "teradata__clnt",
        "teradata__advsr",
        "teradata__advsr_asgn",
        "teradata__brnch",
        "raw_metadata",
        "raw.snowflake__activity",
        "raw.teradata__clnt",
        "raw.teradata__advsr",
        "raw.teradata__advsr_asgn",
        "raw.teradata__brnch",
        "meta.watermark",
        "meta.load_manifest",
        "meta.run_log",
        "meta.check_result",
        "quarantine.rejected_rows",
        "org_weekly",
        "advisor_weekly",
        "weekly_report",
        "geo_weekly",
        "dq_weekly",
        "manifest",
        "run_log",
        "pipeline_graph",
        "narrative",
        "defect_manifest",
    }
    assert set(REGISTRY) == expected


@pytest.mark.parametrize("model", TABLES, ids=lambda m: m.contract_name)
def test_arrow_schema_matches_columns(model: type[Contract]) -> None:
    schema = arrow_schema(model)
    cols = columns(model)
    assert schema.names == [c.name for c in cols]
    assert [f.nullable for f in schema] == [c.nullable for c in cols]
    assert schema.metadata[b"contract"] == model.contract_name.encode()


def test_arrow_types() -> None:
    schema = arrow_schema(SnowflakeActivity)
    assert schema.field("ACTIVITY_TYPE").type == pa.string()
    assert schema.field("DURATION_MIN").type == pa.int64()
    assert schema.field("ACTIVITY_TS").type == pa.timestamp("us", tz="UTC")
    assert schema.field("CLIENT_ID").nullable
    assert not schema.field("ACTIVITY_ID").nullable


def test_arrow_round_trip_of_a_valid_row() -> None:
    row = SnowflakeActivity.model_validate(
        {
            "ACTIVITY_ID": "ACT-0a1b2c3d4e5f",
            "ADVISOR_ID": "ADV-00123",
            "BRANCH_ID": "BR-0412",
            "ACTIVITY_TYPE": "CALL_OUT",
            "CHANNEL": "PHONE",
            "STATUS": "COMPLETED",
            "ACTIVITY_TS": datetime(2026, 10, 6, 14, tzinfo=UTC),
            "CREATED_TS": datetime(2026, 10, 6, 14, tzinfo=UTC),
            "UPDATED_TS": datetime(2026, 10, 6, 14, tzinfo=UTC),
            "_EXTRACTED_AT": datetime(2026, 10, 12, 6, tzinfo=UTC),
        }
    )
    table = pa.Table.from_pylist(
        [row.model_dump(by_alias=True, mode="python")], schema=arrow_schema(SnowflakeActivity)
    )
    back = SnowflakeActivity.model_validate(table.to_pylist()[0])
    assert back == row


def test_duckdb_types() -> None:
    cols = {name: (t, n) for name, t, n in duckdb_columns(SnowflakeActivity)}
    assert cols["ACTIVITY_ID"] == ("VARCHAR", False)
    assert cols["DURATION_MIN"] == ("BIGINT", True)
    assert cols["ACTIVITY_TS"] == ("TIMESTAMP WITH TIME ZONE", False)


def test_documents_are_not_tables() -> None:
    with pytest.raises(TypeError):
        columns(Manifest)


def test_contract_groups_are_consistent() -> None:
    assert len(RAW_CONTRACTS) == len(SOURCE_CONTRACTS)
    assert all(m.contract_kind == "table" for m in EXPORT_TABLE_CONTRACTS)


# ── codegen ────────────────────────────────────────────────────────────────


def test_render_is_deterministic() -> None:
    assert render() == render()


def test_schema_files_carry_version_and_aliases() -> None:
    import json

    activity = json.loads(render()["snowflake__activity.schema.json"])
    assert activity["x-schema-version"] == "1.0.0"
    assert "_EXTRACTED_AT" in activity["properties"]
    assert "ACTIVITY_ID" in activity["required"]


def test_check_detects_stale_and_extra_files(tmp_path: Path) -> None:
    assert stale_files(tmp_path)  # empty dir: everything missing
    write(tmp_path)
    assert stale_files(tmp_path) == []
    (tmp_path / "manifest.schema.json").write_text("{}\n")
    (tmp_path / "gone.schema.json").write_text("{}\n")
    assert stale_files(tmp_path) == ["gone.schema.json", "manifest.schema.json"]
    assert main(["--check", "--out", str(tmp_path)]) == 1
    write(tmp_path)
    assert not (tmp_path / "gone.schema.json").exists()
    assert main(["--check", "--out", str(tmp_path)]) == 0


def test_committed_schemas_are_fresh() -> None:
    assert stale_files(DEFAULT_OUT) == []
