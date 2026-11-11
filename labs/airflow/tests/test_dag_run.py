"""Run the DAG for one week with ``dag.test()``, force a failure and watch retries, then
re-run the failed week cleanly in the same data dir."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pendulum
import pytest
from pulse_weekly import dag

# Fires Monday 2026-11-09 06:00 UTC: data interval 2026-11-02 → 2026-11-09, ISO week 2026-W45.
RUN_AFTER = pendulum.datetime(2026, 11, 9, 6, tz="UTC")
WEEK = "2026-W45"


def run_week(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, dict, float]:
    monkeypatch.setenv("PULSE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PULSE_EXPORT_DIR", str(data_dir / "web-export"))
    started = time.perf_counter()
    dag_run = dag.test(run_after=RUN_AFTER, logical_date=RUN_AFTER)
    seconds = time.perf_counter() - started
    tis = {ti.task_id: ti for ti in dag_run.get_task_instances()}
    print(f"\n{dag_run.run_id}: {dag_run.state} in {seconds:.1f} s")
    for name, ti in tis.items():
        print(f"  {name:<10} {ti.state!s:<16} try {ti.try_number}")
    return dag_run, tis, seconds


def runs(data_dir: Path) -> list[dict]:
    """``run_log.json`` runs, newest first."""
    doc = json.loads((data_dir / "web-export" / "run_log.json").read_text())
    return [run for run in doc["runs"] if "-airflow-" in run["run_id"]]


def run_log(data_dir: Path) -> list[dict]:
    return [s for run in runs(data_dir) for s in run["stages"]]


def test_one_week_end_to_end(
    airflow_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dag_run, tis, _ = run_week(tmp_path, monkeypatch)
    assert dag_run.state == "success"
    states = {t: str(ti.state) for t, ti in tis.items()}
    assert states == {**dict.fromkeys(tis, "success"), "run_status": "skipped"}
    assert all(ti.try_number <= 1 for ti in tis.values())
    weekly = tmp_path / "web-export"
    assert (weekly / "manifest.json").exists()
    assert json.loads((weekly / "manifest.json").read_text())["latest_week"] == WEEK
    assert (tmp_path / "narratives" / f"{WEEK}.json").exists()


def test_failed_stage_retries_then_blocks_downstream(
    airflow_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The runner's own failure hook: checks returns FAILED on every attempt.
    monkeypatch.setenv("PULSE_FORCE_FAIL", "checks")
    dag_run, tis, _ = run_week(tmp_path, monkeypatch)

    assert dag_run.state == "failed"
    assert str(tis["checks"].state) == "failed"
    assert tis["checks"].try_number == 3  # 1 try + 2 retries
    assert str(tis["narrate"].state) == "upstream_failed"  # never ran
    # export is the runner's `always` stage: it still runs and publishes run_log.json only.
    assert str(tis["export"].state) == "success"
    assert str(tis["run_status"].state) == "failed"  # turns the Airflow run red
    assert not (tmp_path / "narratives").exists()
    assert not (tmp_path / "web-export" / "manifest.json").exists()

    attempts = [(s["stage"], s["attempt"], s["status"]) for s in run_log(tmp_path)]
    assert [a for a in attempts if a[0] == "checks"] == [("checks", n, "FAILED") for n in (1, 2, 3)]
    assert not any(a[0] == "narrate" for a in attempts)


def test_rerun_after_a_failed_week_succeeds_and_exports(
    airflow_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PULSE_FORCE_FAIL", "checks")
    failed, _, _ = run_week(tmp_path, monkeypatch)
    assert failed.state == "failed"
    assert not (tmp_path / "web-export" / "manifest.json").exists()

    # The fix is in; the same week runs again as a new DagRun on the same data dir.
    monkeypatch.delenv("PULSE_FORCE_FAIL")
    rerun, tis, _ = run_week(tmp_path, monkeypatch)
    assert rerun.state == "success"
    assert all(ti.try_number <= 1 for ti in tis.values())

    # Two pulse runs: the re-run leads and is not FAILED (WARN, like the clean one-week run,
    # from the fixture world's DQ warnings), and the failed run keeps its own record.
    summary = [(r["run_id"], r["status"]) for r in runs(tmp_path)]
    assert summary == [
        (f"manual-{WEEK}-airflow-2", "WARN"),
        (f"manual-{WEEK}-airflow-1", "FAILED"),
    ]
    manifest = tmp_path / "web-export" / "manifest.json"
    assert manifest.exists()
    assert json.loads(manifest.read_text())["latest_week"] == WEEK
    assert (tmp_path / "narratives" / f"{WEEK}.json").exists()
