from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from tenacity import wait_exponential_jitter
from typer.testing import CliRunner

from pulse.cli import app
from pulse.contracts.enums import RunType, StageStatus
from pulse.contracts.exports import RunLogExport
from pulse.contracts.meta import CheckResult, RunLogRow
from pulse.ingest import meta
from pulse.runner import (
    WEEKLY_STAGES,
    DagError,
    MemorySink,
    RetryableError,
    Runner,
    Stage,
    StageContext,
    StageResult,
    WarehouseSink,
    execution_order,
    new_run_id,
    not_implemented,
    plan,
)
from pulse.runner.command import RUN_LOG_JSON, run_week
from pulse.runner.run import resolve_week, run_status
from pulse.runner.run_log import build_export
from pulse.warehouse import WAREHOUSE_FILE, connect

T0 = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)
WEEK = "2026-W40"
FIXTURE_EXPORTS = Path(__file__).parents[2] / "fixtures" / "exports"


class FakeClock:
    """Time moves only when a stage works or the runner sleeps."""

    def __init__(self, start: datetime = T0) -> None:
        self.t = start
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += timedelta(seconds=seconds)

    def work(self, ms: int) -> None:
        self.t += timedelta(milliseconds=ms)


def ok(clock: FakeClock, ms: int = 100, **kw: object) -> Callable[[StageContext], StageResult]:
    def fn(ctx: StageContext) -> StageResult:
        clock.work(ms)
        return StageResult(**kw)  # type: ignore[arg-type]

    return fn


def flaky(
    clock: FakeClock, failures: int, exc: type[Exception] = RetryableError
) -> Callable[[StageContext], StageResult]:
    calls = {"n": 0}

    def fn(ctx: StageContext) -> StageResult:
        calls["n"] += 1
        clock.work(50)
        if calls["n"] <= failures:
            raise exc(f"call {calls['n']} failed")
        return StageResult(rows_in=10, rows_out=9, rows_quarantined=1)

    return fn


# The weekly DAG with the stages that write sources, shell out to dbt or read marts swapped
# for placeholders, so runner tests stay fast. tests/runner/test_stages.py and
# tests/generate/test_stage.py cover those.
PLACEHOLDERS = [
    replace(s, fn=not_implemented(103))
    if s.name in {"generate", "dbt_build", "checks", "export"}
    else s
    for s in WEEKLY_STAGES
]


def weekly(clock: FakeClock, **overrides: Callable[[StageContext], StageResult]) -> list[Stage]:
    """The real weekly DAG with every stage succeeding unless overridden."""
    return [replace(s, fn=overrides.get(s.name, ok(clock))) for s in WEEKLY_STAGES]


def run(
    stages: list[Stage], clock: FakeClock, sink: MemorySink | None = None
) -> tuple[list[RunLogRow], StageStatus]:
    sink = sink or MemorySink()
    runner = Runner(
        stages,
        data_dir=Path("unused"),
        sinks=[sink],
        clock=clock,
        wait=wait_exponential_jitter(multiplier=2, max=30, jitter=1),
    )
    report = runner.run(WEEK, RunType.WEEKLY, f"weekly-{WEEK}-1")
    return report.rows, report.status


def final(rows: list[RunLogRow]) -> dict[str, StageStatus]:
    return {r.stage: r.status for r in rows}


# ── Acceptance: complete run_log with SUCCESS/SKIPPED ────────────────────────


def test_placeholder_stages_log_one_skipped_row_each() -> None:
    rows, status = run(PLACEHOLDERS, FakeClock())
    assert [r.stage for r in rows] == [s.name for s in WEEKLY_STAGES]
    assert {r.status for r in rows} == {StageStatus.SKIPPED}
    assert all(r.attempt == 1 and r.ended_at is not None for r in rows)
    assert "R2 credentials absent" in (rows[0].message or "")
    assert "issue #103" in (rows[1].message or "")
    assert status is StageStatus.SKIPPED


def test_mixed_success_and_placeholder_run_is_success() -> None:
    clock = FakeClock()
    stages = [
        replace(s, fn=ok(clock)) if s.name in {"restore_state", "generate"} else s
        for s in PLACEHOLDERS
    ]
    rows, status = run(stages, clock)
    assert final(rows)["restore_state"] is StageStatus.SUCCESS
    assert final(rows)["export"] is StageStatus.SKIPPED
    assert len(rows) == len(WEEKLY_STAGES)
    assert status is StageStatus.SUCCESS
    assert rows[0].duration_ms == 100


def test_warn_stage_makes_the_run_warn() -> None:
    clock = FakeClock()
    rows, status = run(weekly(clock, narrate=ok(clock, status=StageStatus.WARN)), clock)
    assert status is StageStatus.WARN
    assert final(rows)["export"] is StageStatus.SUCCESS


# ── Acceptance: retries, with a fake clock ───────────────────────────────────


def test_retryable_error_twice_then_success_logs_attempts_1_to_3() -> None:
    clock = FakeClock()
    sink = MemorySink()
    rows, status = run(weekly(clock, ingest=flaky(clock, failures=2)), clock, sink)

    ingest = [r for r in rows if r.stage == "ingest"]
    assert [(r.attempt, r.status) for r in ingest] == [
        (1, StageStatus.FAILED),
        (2, StageStatus.FAILED),
        (3, StageStatus.SUCCESS),
    ]
    assert all("retrying" in (r.message or "") for r in ingest[:2])
    assert (ingest[2].rows_in, ingest[2].rows_out, ingest[2].rows_quarantined) == (10, 9, 1)
    assert status is StageStatus.SUCCESS

    # Two backoff sleeps, exponential with jitter, all on the fake clock.
    assert len(clock.sleeps) == 2
    assert 2 <= clock.sleeps[0] <= 3
    assert 4 <= clock.sleeps[1] <= 5
    assert ingest[1].started_at - ingest[0].ended_at == timedelta(seconds=clock.sleeps[0])

    # The sink saw each attempt start as RUNNING before its final row.
    seen = [(r.stage, r.attempt, r.status) for r in sink.rows if r.stage == "ingest"]
    assert seen[:2] == [("ingest", 1, StageStatus.RUNNING), ("ingest", 1, StageStatus.FAILED)]


def test_retries_exhausted_fails_and_skips_downstream() -> None:
    clock = FakeClock()
    rows, status = run(weekly(clock, dbt_build=flaky(clock, failures=5)), clock)

    dbt = [r for r in rows if r.stage == "dbt_build"]
    assert [r.attempt for r in dbt] == [1, 2, 3]
    assert dbt[-1].status is StageStatus.FAILED
    assert "retrying" not in (dbt[-1].message or "")
    statuses = final(rows)
    for name in ("checks", "narrate", "persist_state"):
        assert statuses[name] is StageStatus.SKIPPED
    assert "Upstream stage dbt_build failed." in {r.message for r in rows}
    # export and release_lock are ``always`` stages: they run even though upstream failed.
    assert statuses["export"] is StageStatus.SUCCESS
    assert statuses["release_lock"] is StageStatus.SUCCESS
    assert status is StageStatus.FAILED


def test_halt_skips_every_later_stage_and_the_run_is_skipped() -> None:
    clock = FakeClock()
    held = ok(
        clock, status=StageStatus.SKIPPED, message="Run lock held by weekly-2026-W40-1.", halt=True
    )
    rows, status = run(weekly(clock, restore_state=held), clock)
    assert {r.status for r in rows} == {StageStatus.SKIPPED}
    assert len(rows) == len(WEEKLY_STAGES)
    assert final(rows)["release_lock"] is StageStatus.SKIPPED
    assert rows[1].message == "Run stopped at restore_state: Run lock held by weekly-2026-W40-1."
    assert status is StageStatus.SKIPPED


def test_non_retryable_error_fails_on_first_attempt() -> None:
    clock = FakeClock()
    rows, status = run(weekly(clock, generate=flaky(clock, failures=1, exc=KeyError)), clock)
    generate = [r for r in rows if r.stage == "generate"]
    assert [(r.attempt, r.status) for r in generate] == [(1, StageStatus.FAILED)]
    assert (generate[0].message or "").startswith("KeyError")
    assert clock.sleeps == []
    assert status is StageStatus.FAILED


def test_returned_failed_status_is_not_retried() -> None:
    clock = FakeClock()
    rows, status = run(weekly(clock, checks=ok(clock, status=StageStatus.FAILED)), clock)
    assert [r.attempt for r in rows if r.stage == "checks"] == [1]
    assert final(rows)["narrate"] is StageStatus.SKIPPED
    assert status is StageStatus.FAILED


def test_failure_only_skips_its_own_descendants() -> None:
    clock = FakeClock()
    boom = ok(clock, status=StageStatus.FAILED, message="Narrative backend 503")
    rows, status = run(weekly(clock, narrate=boom), clock)
    statuses = final(rows)
    assert statuses["narrate"] is StageStatus.FAILED
    assert statuses["persist_state"] is StageStatus.SUCCESS
    assert statuses["release_lock"] is StageStatus.SUCCESS
    assert status is StageStatus.FAILED


def test_weekly_dag_has_no_sheets_stage() -> None:
    # #55 (Google Sheets push) is out of scope: no stage, and the lock waits on export.
    names = [s.name for s in WEEKLY_STAGES]
    assert "publish_sheets" not in names
    release = next(s for s in WEEKLY_STAGES if s.name == "release_lock")
    assert set(release.depends_on) == {"persist_state", "export"}


def test_export_failure_still_persists_checked_state() -> None:
    clock = FakeClock()
    boom = ok(clock, status=StageStatus.FAILED, message="run_log export broke")
    rows, status = run(weekly(clock, export=boom), clock)
    statuses = final(rows)
    assert statuses["export"] is StageStatus.FAILED
    assert statuses["persist_state"] is StageStatus.SUCCESS
    assert status is StageStatus.FAILED


def test_narrate_failure_still_persists_checked_state() -> None:
    clock = FakeClock()
    rows, _ = run(weekly(clock, narrate=ok(clock, status=StageStatus.FAILED)), clock)
    assert final(rows)["persist_state"] is StageStatus.SUCCESS


def test_warned_checks_still_persist_state() -> None:
    clock = FakeClock()
    checks = ok(clock, status=StageStatus.WARN)
    rows, _ = run(weekly(clock, checks=checks, export=ok(clock, status=StageStatus.FAILED)), clock)
    assert final(rows)["persist_state"] is StageStatus.SUCCESS


def test_failed_checks_do_not_persist_state() -> None:
    clock = FakeClock()
    rows, _ = run(weekly(clock, checks=ok(clock, status=StageStatus.FAILED)), clock)
    assert final(rows)["persist_state"] is StageStatus.SKIPPED
    assert final(rows)["release_lock"] is StageStatus.SUCCESS


def test_stage_returning_the_wrong_type_fails() -> None:
    clock = FakeClock()
    bad = weekly(clock, restore_state=lambda ctx: None)  # type: ignore[arg-type,return-value]
    rows, _ = run(bad, clock)
    assert rows[0].status is StageStatus.FAILED
    assert "TypeError" in (rows[0].message or "")


def test_stage_result_cannot_be_running() -> None:
    with pytest.raises(ValueError, match="RUNNING"):
        StageResult(StageStatus.RUNNING)


# ── Acceptance: exit code, dry run, run_log.json ─────────────────────────────


def test_failed_run_exits_non_zero_and_still_writes_run_log(tmp_path: Path) -> None:
    clock = FakeClock()
    out: list[str] = []
    code = run_week(
        WEEK,
        data_dir=tmp_path,
        stages=weekly(clock, export=flaky(clock, failures=1, exc=OSError)),
        clock=clock,
        echo=out.append,
    )
    assert code == 1
    assert out[-1] == f"manual-{WEEK}-1: FAILED"
    doc = RunLogExport.model_validate_json((tmp_path / RUN_LOG_JSON).read_text())
    assert doc.runs[0].status is StageStatus.FAILED


def test_successful_run_exits_zero(tmp_path: Path) -> None:
    clock = FakeClock()
    code = run_week(WEEK, data_dir=tmp_path, stages=weekly(clock), clock=clock, echo=lambda _: None)
    assert code == 0


def test_cli_exit_code_follows_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(app, ["run", "--week", WEEK, "--run-type", "weekly"])
    assert result.exit_code == 0, result.output
    # Real stages on an empty data dir: generate writes the week, the rest runs on it.
    assert f"weekly-{WEEK}-1:" in result.output
    assert (tmp_path / "web-data" / "weekly_report.parquet").exists()
    assert (tmp_path / RUN_LOG_JSON).exists()


def test_cli_rejects_a_bad_week(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(app, ["run", "--week", "2026-40"])
    assert result.exit_code != 0
    assert not (tmp_path / WAREHOUSE_FILE).exists()


def test_dry_run_prints_the_plan_and_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(app, ["run", "--week", WEEK, "--dry-run"])
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0] == f"Plan for {WEEK} (MANUAL), nothing will run:"
    assert lines[1].strip() == "1. restore_state (Restore state), up to 3 attempts"
    assert lines[-2].strip().startswith("8. persist_state (Persist state) after checks")
    last = "9. release_lock (Release lock) after persist_state, export"
    assert lines[-1].strip().startswith(last)
    assert list(tmp_path.iterdir()) == []


def test_run_log_json_validates_and_accumulates_runs(tmp_path: Path) -> None:
    clock = FakeClock()
    for _ in range(2):
        run_week(
            WEEK,
            data_dir=tmp_path,
            run_type=RunType.WEEKLY,
            stages=PLACEHOLDERS,
            clock=clock,
            echo=lambda _: None,
        )
        clock.work(60_000)
    raw = json.loads((tmp_path / RUN_LOG_JSON).read_text())
    doc = RunLogExport.model_validate(raw)
    assert [r.run_id for r in doc.runs] == [f"weekly-{WEEK}-2", f"weekly-{WEEK}-1"]
    assert all(len(r.stages) == len(WEEKLY_STAGES) for r in doc.runs)


def test_run_log_json_matches_the_fixture_when_rebuilt_from_rows() -> None:
    """Flatten the fixture's run_log.json to meta rows; folding them back gives it unchanged."""
    fixture = RunLogExport.model_validate_json((FIXTURE_EXPORTS / "run_log.json").read_text())
    rows, checks = [], []
    for summary in fixture.runs:
        for a in summary.stages:
            rows.append(
                RunLogRow(
                    run_id=summary.run_id,
                    run_type=summary.run_type,
                    iso_week_id=summary.iso_week_id,
                    git_sha=summary.git_sha,
                    **a.model_dump(),
                )
            )
        checks += [CheckResult(run_id=summary.run_id, **c.model_dump()) for c in summary.checks]
    assert build_export(rows, checks, fixture.generated_at) == fixture


# ── Warehouse sink ───────────────────────────────────────────────────────────


def test_warehouse_sink_rewrites_rows_lost_when_the_file_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / WAREHOUSE_FILE
    sink = WarehouseSink(path)
    clock = FakeClock()
    rows, _ = run(weekly(clock), clock)
    sink.write(rows[0])
    path.unlink()  # restore_state swaps in the warehouse from R2
    for row in rows[1:]:
        sink.write(row)
    con = connect(path, read_only=True)
    try:
        stored = meta.get_run_log(con)
    finally:
        con.close()
    assert [r.stage for r in stored] == [r.stage for r in rows]
    assert {r.status for r in stored} == {StageStatus.SUCCESS}


# ── DAG, plan, graph, ids ────────────────────────────────────────────────────


def _noop(ctx: StageContext) -> StageResult:
    return StageResult()


def test_dag_rejects_cycles_unknown_deps_and_duplicates() -> None:
    a = Stage("a", "A", _noop, ("b",))
    b = Stage("b", "B", _noop, ("a",))
    with pytest.raises(DagError, match="Cycle"):
        execution_order([a, b])
    with pytest.raises(DagError, match="unknown"):
        execution_order([Stage("a", "A", _noop, ("zzz",))])
    with pytest.raises(DagError, match="Duplicate"):
        execution_order([Stage("a", "A", _noop), Stage("a", "A2", _noop)])


def test_execution_order_respects_dependencies_not_registration() -> None:
    stages = [
        Stage("c", "C", _noop, ("b",)),
        Stage("b", "B", _noop, ("a",)),
        Stage("a", "A", _noop),
    ]
    assert [s.name for s in execution_order(stages)] == ["a", "b", "c"]
    assert len(plan(stages)) == 3


def test_new_run_id_counts_earlier_runs_of_the_same_type_and_week() -> None:
    existing = {"weekly-2026-W40-1", "weekly-2026-W40-2", "manual-2026-W40-1", "weekly-2026-W39-7"}
    assert new_run_id(RunType.WEEKLY, WEEK, existing) == "weekly-2026-W40-3"
    assert new_run_id(RunType.BACKFILL, WEEK, existing) == "backfill-2026-W40-1"


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 5), "2026-W40"),  # Monday after W40
        (date(2026, 10, 11), "2026-W40"),  # Sunday of W41: W41 is not complete
        (date(2027, 1, 4), "2026-W53"),
    ],
)
def test_resolve_last_week(today: date, expected: str) -> None:
    assert resolve_week("last", today) == expected
    assert resolve_week(None, today) == expected


def test_run_status_is_the_worst_stage() -> None:
    S = StageStatus
    assert run_status([S.SUCCESS, S.SKIPPED]) is S.SUCCESS
    assert run_status([S.SUCCESS, S.WARN, S.SKIPPED]) is S.WARN
    assert run_status([S.WARN, S.FAILED]) is S.FAILED
    assert run_status([]) is S.SKIPPED
