"""DQ030–DQ033 policy and stage behavior against synthetic fixture data."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest

from pulse.contracts.defects import DefectManifest
from pulse.contracts.enums import CheckStatus, RunType, StageStatus
from pulse.ingest import meta
from pulse.quality.checks import (
    CheckPolicy,
    defect_reconciliation,
    freshness,
    quarantine_rate,
    run_checks,
    volume,
)
from pulse.runner.run import Runner
from pulse.runner.stage import Stage, StageContext, StageResult
from pulse.warehouse import connect, init_warehouse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def test_freshness_pass_and_fail() -> None:
    policy = CheckPolicy()
    assert freshness("r", "2026-W40", date(2026, 10, 2), policy).status is CheckStatus.PASS
    assert freshness("r", "2026-W40", date(2026, 10, 1), policy).status is CheckStatus.FAIL


def test_volume_pass_warn_and_fail() -> None:
    policy = CheckPolicy()
    history = [100] * 8
    assert volume("r", 100, history, policy).status is CheckStatus.PASS
    assert volume("r", 130, history, policy).status is CheckStatus.WARN
    assert volume("r", 160, history, policy).status is CheckStatus.FAIL


def test_quarantine_rate_pass_and_fail() -> None:
    policy = CheckPolicy()
    assert quarantine_rate("r", 2, 100, policy).status is CheckStatus.PASS
    assert quarantine_rate("r", 3, 100, policy).status is CheckStatus.FAIL


def test_defect_reconciliation_pass_and_fail() -> None:
    manifest = DefectManifest.model_validate_json((FIXTURES / "defects.json").read_text())
    expected = {
        (d.file, d.row, d.rule_id)
        for d in manifest.defects
        if d.iso_week_id == "2026-W40" and d.rule_id in {f"DQ00{i}" for i in range(1, 6)}
    }
    assert expected
    assert defect_reconciliation("r", expected, expected, CheckPolicy()).status is CheckStatus.PASS
    assert defect_reconciliation("r", expected, set(), CheckPolicy()).status is CheckStatus.WARN
    assert (
        defect_reconciliation("r", expected, set(), CheckPolicy(), ci=True).status
        is CheckStatus.FAIL
    )


def test_policy_reads_thresholds_and_actions_from_toml(tmp_path: Path) -> None:
    path = tmp_path / "pulse.toml"
    path.write_text(
        "[quality]\nfreshness_lag_days = 3\nquarantine_max_rate = 0.05\n"
        'dq030_action = "WARN"\ndq032_action = "WARN"\n'
    )
    policy = CheckPolicy.from_toml(path)
    assert freshness("r", "2026-W40", date(2026, 10, 1), policy).status is CheckStatus.PASS
    assert freshness("r", "2026-W40", date(2026, 9, 30), policy).status is CheckStatus.WARN
    assert quarantine_rate("r", 3, 100, policy).status is CheckStatus.PASS
    assert quarantine_rate("r", 6, 100, policy).status is CheckStatus.WARN


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
