"""Fixture-backed DQ check persistence and runner gating."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from pulse.contracts.defects import DefectManifest
from pulse.contracts.enums import CheckStatus, LoadStatus, RunType, StageStatus
from pulse.contracts.meta import LoadManifest, RejectedRow
from pulse.ingest import meta
from pulse.ingest.snowflake import load_snowflake_activity
from pulse.ingest.teradata_client import load_teradata_client
from pulse.quality.checks import run_checks
from pulse.runner.run import Runner
from pulse.runner.stage import Stage, StageContext, StageResult
from pulse.warehouse import connect, init_warehouse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def warehouse() -> duckdb.DuckDBPyConnection:
    con = connect(":memory:")
    init_warehouse(con)
    con.execute("CREATE SCHEMA marts")
    con.execute(
        "CREATE TABLE marts.mart_org_weekly AS SELECT * FROM read_parquet(?)",
        [str(FIXTURES / "exports/org_weekly.parquet")],
    )
    yield con
    con.close()


def test_freshness_uses_toronto_business_date(warehouse: duckdb.DuckDBPyConnection) -> None:
    warehouse.execute("DROP TABLE raw.snowflake__activity")
    warehouse.execute(
        "CREATE VIEW raw.snowflake__activity AS "
        "SELECT TIMESTAMPTZ '2026-10-02 02:00:00+00' AS ACTIVITY_TS"
    )
    defects = DefectManifest.model_validate_json((FIXTURES / "defects.json").read_text())
    run_checks(warehouse, run_id="timezone", iso_week_id="2026-W40", defect_manifest=defects)
    assert meta.get_check_results(warehouse, "timezone")[0].status is CheckStatus.FAIL


def test_volume_requires_eight_calendar_weeks(warehouse: duckdb.DuckDBPyConnection) -> None:
    source = warehouse.execute(
        "SELECT * FROM marts.mart_org_weekly "
        "WHERE level = 'NATIONAL' AND node_id = 'CA' AND iso_week_id = '2026-W37'"
    ).fetchone()
    assert source is not None
    warehouse.execute("DELETE FROM marts.mart_org_weekly WHERE level = 'NATIONAL'")
    for week in [31, 32, 33, 34, 36, 37, 38, 39, 40]:
        row = (f"2026-W{week:02d}", *source[1:6], 5000 if week == 31 else 133, *source[7:])
        warehouse.execute(
            "INSERT INTO marts.mart_org_weekly VALUES (" + ", ".join("?" * len(row)) + ")", row
        )
    defects = DefectManifest.model_validate_json((FIXTURES / "defects.json").read_text())
    run_checks(warehouse, run_id="gap", iso_week_id="2026-W40", defect_manifest=defects)
    assert meta.get_check_results(warehouse, "gap")[1].status is CheckStatus.WARN
    row = ("2026-W35", *source[1:6], 133, *source[7:])
    warehouse.execute(
        "INSERT INTO marts.mart_org_weekly VALUES (" + ", ".join("?" * len(row)) + ")", row
    )
    run_checks(warehouse, run_id="complete", iso_week_id="2026-W40", defect_manifest=defects)
    assert meta.get_check_results(warehouse, "complete")[1].status is CheckStatus.PASS


def test_defect_reconciliation_uses_prior_loaded_batch_on_rerun(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    fixture = DefectManifest.model_validate_json((FIXTURES / "defects.json").read_text())
    defect = next(
        d for d in fixture.defects if d.iso_week_id == "2026-W40" and d.rule_id == "DQ002"
    )
    defects = fixture.model_copy(update={"defects": [defect]})
    when = datetime(2026, 10, 5, tzinfo=UTC)
    meta.record_manifest(
        warehouse,
        LoadManifest(
            file_path=defect.file,
            file_sha256="0" * 64,
            source="snowflake",
            table_name="activity",
            batch_id="old-batch",
            row_count=100,
            rows_loaded=99,
            rows_quarantined=1,
            status=LoadStatus.LOADED,
            loaded_at=when,
            run_id="first-run",
        ),
    )
    meta.write_rejected_rows(
        warehouse,
        [
            RejectedRow(
                rejected_id="fixture-defect",
                run_id="first-run",
                batch_id="old-batch",
                source="snowflake",
                table_name="activity",
                source_file=defect.file,
                source_row=defect.row or 0,
                rule_id=defect.rule_id,
                reason="fixture",
                payload="{}",
                detected_at=when,
            )
        ],
    )
    run_checks(warehouse, run_id="rerun", iso_week_id="2026-W40", defect_manifest=defects)
    assert meta.get_check_results(warehouse, "rerun")[3].status is CheckStatus.PASS


def test_defect_reconciliation_covers_all_files_loaded_in_run(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    run_id = "fixture-backfill"
    loaded_at = datetime(2026, 10, 5, tzinfo=UTC)
    sources = FIXTURES / "sources"
    assert (
        load_snowflake_activity(warehouse, sources, run_id=run_id, loaded_at=loaded_at).status
        is StageStatus.SUCCESS
    )
    assert (
        load_teradata_client(warehouse, sources, run_id=run_id, loaded_at=loaded_at).status
        is StageStatus.SUCCESS
    )
    defects = DefectManifest.model_validate_json((FIXTURES / "defects.json").read_text())
    assert len(meta.get_manifest(warehouse)) == 11

    run_checks(warehouse, run_id=run_id, iso_week_id="2026-W40", defect_manifest=defects, ci=True)

    reconciliation = meta.get_check_results(warehouse, run_id)[3]
    assert reconciliation.status is CheckStatus.PASS
    assert reconciliation.observed == 10


def test_failed_check_persists_results_and_blocks_export(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    defects = DefectManifest.model_validate_json((FIXTURES / "defects.json").read_text())

    class FixedClock:
        def now(self) -> datetime:
            return datetime(2026, 10, 5, tzinfo=UTC)

        def sleep(self, seconds: float) -> None:
            pass

    exported: list[bool] = []

    def export(_ctx: StageContext) -> StageResult:
        exported.append(True)
        return StageResult()

    stages = (
        Stage(
            "checks",
            "Run checks",
            lambda ctx: run_checks(
                warehouse,
                run_id=ctx.run_id,
                iso_week_id=ctx.iso_week_id,
                defect_manifest=defects,
            ),
        ),
        Stage(
            "export",
            "Export",
            export,
            ("checks",),
        ),
    )
    report = Runner(stages, data_dir=FIXTURES, clock=FixedClock()).run(
        "2026-W40", RunType.WEEKLY, "next-run"
    )
    assert report.failed
    assert report.rows[-1].stage == "export"
    assert report.rows[-1].status is StageStatus.SKIPPED
    assert not exported
    checks = meta.get_check_results(warehouse, "next-run")
    assert [check.check_id for check in checks] == ["DQ030", "DQ031", "DQ032", "DQ033"]
    assert checks[0].status is CheckStatus.FAIL
