"""#291: the run log persisted with the warehouse ends with every stage's final status."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

import pulse.state
from pulse.contracts.enums import RunType, StageStatus
from pulse.contracts.exports import RunLogExport
from pulse.contracts.meta import RunLogRow
from pulse.runner import WEEKLY_STAGES, RetryableError, Stage, StageContext, StageResult, stages
from pulse.runner.backfill import backfill_range
from pulse.runner.command import RUN_LOG_JSON
from pulse.state import StateSync
from pulse.state.store import ObjectStore

BUCKET = "pulse-state"
WEEKS = ("2026-W40", "2026-W41")
RUNS = [f"backfill-{w}-1" for w in WEEKS]
STATE_STAGE_NAMES = {"restore_state", "persist_state", "release_lock"}


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)

    def now(self) -> datetime:
        self.t += timedelta(milliseconds=10)
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def store() -> Iterator[ObjectStore]:
    with mock_aws():
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y"
        )
        client.create_bucket(Bucket=BUCKET)
        yield ObjectStore(client, BUCKET)


_TOKENS = count(1)


def use_store(monkeypatch: pytest.MonkeyPatch, store: ObjectStore) -> StateSync:
    """A fresh process's StateSync over the test bucket (the runner reads pulse.state.STATE)."""
    sync = StateSync(
        lambda: store,
        new_token=lambda: f"token-{next(_TOKENS)}",
        rebuild=lambda ctx, weeks: StageResult(),
    )
    monkeypatch.setattr(pulse.state, "STATE", sync)
    return sync


def ok(ctx: StageContext) -> StageResult:
    return StageResult()


def stub_pipeline() -> tuple[Stage, ...]:
    """The weekly DAG with the real state stages and every other stage a no-op."""
    return tuple(s if s.name in STATE_STAGE_NAMES else replace(s, fn=ok) for s in WEEKLY_STAGES)


def exported(data_dir: Path) -> RunLogExport:
    return RunLogExport.model_validate_json((data_dir / RUN_LOG_JSON).read_text())


def assert_every_stage_final(doc: RunLogExport, run_ids: list[str]) -> None:
    runs = {r.run_id: r for r in doc.runs}
    assert set(run_ids) <= set(runs)
    for run_id in run_ids:
        run = runs[run_id]
        assert [a.stage for a in run.stages] == [s.name for s in WEEKLY_STAGES], run_id
        for attempt in run.stages:
            assert attempt.status is not StageStatus.RUNNING, (run_id, attempt.stage)
            assert attempt.ended_at is not None, (run_id, attempt.stage)
        assert run.ended_at is not None, run_id


def backfill(first: str, last: str, data_dir: Path, clock: Clock, out: list[str]) -> int:
    return backfill_range(
        first, last, data_dir=data_dir, stages=stub_pipeline(), clock=clock, echo=out.append
    )


def test_two_week_backfill_keeps_every_stage_final(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, store)
    assert backfill(WEEKS[0], WEEKS[-1], tmp_path, Clock(), []) == 0
    doc = exported(tmp_path)
    assert doc.runs[0].run_id == RUNS[-1]
    assert_every_stage_final(doc, RUNS)
    first = {a.stage: a for a in next(r for r in doc.runs if r.run_id == RUNS[0]).stages}
    assert first["persist_state"].status is StageStatus.SUCCESS
    assert first["release_lock"].status is StageStatus.SUCCESS


def test_a_fresh_runner_restores_the_previous_runs_final_rows(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The weekly cron: every week starts on an empty runner and restores from R2."""
    clock = Clock()
    for week, data_dir in zip(WEEKS, (tmp_path / "runner1", tmp_path / "runner2"), strict=True):
        use_store(monkeypatch, store)
        assert backfill(week, week, data_dir, clock, []) == 0
    assert_every_stage_final(exported(tmp_path / "runner2"), RUNS)


def test_a_failed_persist_is_recorded_and_nothing_claims_it_succeeded(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    use_store(monkeypatch, store)
    assert backfill(WEEKS[0], WEEKS[0], tmp_path, clock, []) == 0

    def upload_fails(path: Path, key: str) -> None:
        raise OSError(f"cannot upload {key}")

    monkeypatch.setattr(store, "upload", upload_fails)
    out: list[str] = []
    assert backfill(WEEKS[1], WEEKS[1], tmp_path, clock, out) == 1
    doc = exported(tmp_path)
    assert doc.runs[0].run_id == RUNS[1]
    assert_every_stage_final(doc, RUNS)
    failed = {a.stage: a for a in doc.runs[0].stages}
    assert failed["persist_state"].status is StageStatus.FAILED
    assert failed["persist_state"].message == "OSError: cannot upload warehouse.duckdb"
    assert failed["release_lock"].status is StageStatus.SUCCESS
    assert doc.runs[0].status is StageStatus.FAILED
    assert f"{RUNS[1]}: FAILED" in out

    # R2 still holds the first week's state, whose run log knows nothing of the failed run.
    monkeypatch.undo()
    use_store(monkeypatch, store)
    later = tmp_path / "runner2"
    assert backfill("2026-W42", "2026-W42", later, clock, []) == 0
    doc = exported(later)
    assert RUNS[1] not in {r.run_id for r in doc.runs}
    assert_every_stage_final(doc, [RUNS[0], "backfill-2026-W42-1"])


def test_applied_tails_are_removed_and_a_reused_run_id_is_not_finished(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    use_store(monkeypatch, store)
    assert backfill(WEEKS[0], WEEKS[0], tmp_path, clock, []) == 0
    assert sorted(store.etags("run_logs/")) == [f"run_logs/{RUNS[0]}.json"]
    assert backfill(WEEKS[1], WEEKS[1], tmp_path, clock, []) == 0
    # The second persist uploaded the first run's final rows and dropped its tail.
    assert sorted(store.etags("run_logs/")) == [f"run_logs/{RUNS[1]}.json"]

    # A tail whose run id the warehouse reuses for a different run (after a rebuild).
    stale = json.loads(store.get(f"run_logs/{RUNS[1]}.json")[0])  # type: ignore[index]
    for row in stale:
        row["started_at"] = "2020-01-06T00:00:00Z"
        row["status"] = "FAILED"
    store.put(f"run_logs/{RUNS[1]}.json", json.dumps(stale).encode())
    use_store(monkeypatch, store)
    assert backfill("2026-W42", "2026-W42", tmp_path / "runner2", clock, []) == 0
    second = next(r for r in exported(tmp_path / "runner2").runs if r.run_id == RUNS[1])
    assert second.ended_at is None  # the stale FAILED rows were not applied
    assert {a.stage: a.status for a in second.stages}["persist_state"] is StageStatus.RUNNING


def test_a_failed_tail_write_fails_the_command_and_says_why(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sync = use_store(monkeypatch, store)

    def r2_down(rows: object) -> bool:
        raise RetryableError("R2 put_object failed")

    monkeypatch.setattr(sync, "record_run_log", r2_down)
    out: list[str] = []
    assert backfill(WEEKS[0], WEEKS[0], tmp_path, Clock(), out) == 1
    assert (
        "Could not keep the final run log with the state: RetryableError: R2 put_object failed"
        in out
    )
    assert f"{RUNS[0]}: SUCCESS" in out


def test_without_credentials_no_tail_is_kept(tmp_path: Path) -> None:
    sync = StateSync(lambda: None)
    rows = [
        RunLogRow(
            run_id=RUNS[0],
            run_type=RunType.BACKFILL,
            iso_week_id=WEEKS[0],
            stage="persist_state",
            attempt=1,
            status=StageStatus.SKIPPED,
            started_at=datetime(2026, 10, 19, tzinfo=UTC),
        )
    ]
    assert sync.record_run_log(rows) is False
    assert sync.record_run_log([]) is False


def test_an_unreadable_tail_is_skipped_and_removed(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    use_store(monkeypatch, store)
    assert backfill(WEEKS[0], WEEKS[0], tmp_path, clock, []) == 0
    store.put(f"run_logs/{RUNS[0]}.json", b'[{"run_id": "half a ro')
    out: list[str] = []
    assert backfill(WEEKS[1], WEEKS[1], tmp_path, clock, out) == 0, out
    assert sorted(store.etags("run_logs/")) == [f"run_logs/{RUNS[1]}.json"]


@pytest.mark.integration
@pytest.mark.slow
def test_real_two_week_backfill_on_fixtures_exports_every_stage_final(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real DAG, as ``make backfill``, with state on a local (moto) bucket."""
    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sync = StateSync(lambda: store, new_token=lambda: f"token-{next(_TOKENS)}", start_week=WEEKS[0])
    monkeypatch.setattr(pulse.state, "STATE", sync)
    out: list[str] = []
    assert backfill_range(WEEKS[0], WEEKS[-1], data_dir=tmp_path, echo=out.append) == 0, out
    for doc in (
        exported(tmp_path),
        RunLogExport.model_validate_json((stages.export_dir() / "run_log.json").read_text()),
    ):
        assert_every_stage_final(doc, RUNS)
        first = {a.stage: a for a in next(r for r in doc.runs if r.run_id == RUNS[0]).stages}
        assert first["persist_state"].status is StageStatus.SUCCESS
        assert first["release_lock"].status is StageStatus.SUCCESS
