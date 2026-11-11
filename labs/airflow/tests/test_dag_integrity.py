"""The DAG imports cleanly, has no cycles, and matches the runner's stage DAG."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pendulum
import pulse_weekly
import pytest
from airflow.dag_processing.dagbag import DagBag
from pulse_weekly import ALLOCATE, STAGES, dag, iso_week_for, parse_summary

from conftest import LAB

REPO = LAB.parents[1]
STATE_STAGES = {"restore_state", "persist_state", "release_lock"}


def runner_stages() -> list[dict[str, object]]:
    """The runner's own DAG, read from the root project's environment."""
    code = (
        "import json; from pulse.runner.dag import WEEKLY_STAGES, execution_order; "
        "print(json.dumps([{'name': s.name, 'deps': list(s.depends_on), 'always': s.always} "
        "for s in execution_order(WEEKLY_STAGES)]))"
    )
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    out = subprocess.run(
        [shutil.which("uv") or "uv", "run", "--project", str(REPO), "--frozen", "--quiet",
         "python", "-c", code],
        cwd=REPO, env=env, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return [s for s in json.loads(out.stdout) if s["name"] not in STATE_STAGES]


def test_dag_folder_imports_without_errors() -> None:
    bag = DagBag(dag_folder=LAB / "dags")
    assert bag.import_errors == {}
    assert set(bag.dag_ids) == {"pulse_weekly"}


def test_no_cycles_and_runner_order() -> None:
    dag.check_cycle()  # raises on a cycle
    runner = runner_stages()
    order = [t.task_id for t in dag.topological_sort() if t.task_id not in {"run_status", ALLOCATE}]
    assert order == [s["name"] for s in runner]
    for stage in runner:
        deps = {d for d in stage["deps"] if d not in STATE_STAGES} | {ALLOCATE}  # type: ignore[union-attr]
        task = dag.get_task(str(stage["name"]))
        assert task.upstream_task_ids == deps
        assert (task.trigger_rule == "all_done") is stage["always"]


def test_cycle_is_caught() -> None:
    from airflow.providers.standard.operators.empty import EmptyOperator
    from airflow.sdk import DAG
    from airflow.sdk.exceptions import AirflowDagCycleException

    with DAG("cyclic", schedule=None) as bad:
        a, b = EmptyOperator(task_id="a"), EmptyOperator(task_id="b")
        a >> b >> a
    with pytest.raises(AirflowDagCycleException):
        bad.check_cycle()


def test_operational_settings() -> None:
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    assert dag.dagrun_timeout == timedelta(hours=2)
    for name, _ in STAGES:
        task = dag.get_task(name)
        assert task.retries == 2
        assert task.execution_timeout == timedelta(minutes=30)
    status = dag.get_task("run_status")
    assert status.trigger_rule == "one_failed"
    assert status.upstream_task_ids == {name for name, _ in STAGES} | {ALLOCATE}


def test_a_failed_week_blocks_the_next() -> None:
    # The first task waits for the previous week's whole run: itself, every stage and
    # run_status (its direct downstream tasks) must have succeeded or been skipped.
    first = dag.get_task(ALLOCATE)
    assert first.depends_on_past is True
    assert first.wait_for_downstream is True
    assert first.upstream_task_ids == set()
    assert first.downstream_task_ids == {name for name, _ in STAGES} | {"run_status"}


@pytest.mark.parametrize(
    ("run_after", "week"),
    [
        # A Monday run reports the week that ended the day before, like `pulse run --week last`.
        (pendulum.datetime(2026, 11, 9, 6, tz="UTC"), "2026-W45"),
        # ISO year boundary: 2026 has 53 ISO weeks.
        (pendulum.datetime(2027, 1, 4, 6, tz="UTC"), "2026-W53"),
        (pendulum.datetime(2027, 1, 11, 6, tz="UTC"), "2027-W01"),
        # A manual run mid-week still reports the last complete week.
        (pendulum.datetime(2026, 11, 12, 15, tz="UTC"), "2026-W45"),
    ],
)
def test_data_interval_maps_to_iso_week(run_after: pendulum.DateTime, week: str) -> None:
    interval = dag.timetable.infer_manual_data_interval(run_after=run_after)
    assert interval.end - interval.start == timedelta(days=7)
    assert iso_week_for(interval.start) == week


def test_backfill_creates_one_run_per_week() -> None:
    from airflow.timetables.base import TimeRestriction

    start = pendulum.datetime(2026, 10, 5, 6, tz="UTC")
    restriction = TimeRestriction(start, pendulum.datetime(2026, 11, 2, 6, tz="UTC"), True)
    weeks, last = [], None
    while (
        info := dag.timetable.next_dagrun_info(
            last_automated_data_interval=last, restriction=restriction
        )
    ) is not None:
        weeks.append(iso_week_for(info.data_interval.start))
        last = info.data_interval
    assert weeks == ["2026-W41", "2026-W42", "2026-W43", "2026-W44", "2026-W45"]


def test_parse_summary_takes_the_last_json_line() -> None:
    out = '{"status": "WARN"}\nnot json\n{"status": "SUCCESS"}\ntrailing noise\n'
    proc = subprocess.CompletedProcess([], 0, stdout=out, stderr="")
    assert parse_summary("checks", proc) == {"status": "SUCCESS"}


def test_parse_summary_surfaces_stderr_on_a_crash() -> None:
    stderr = "\n".join(f"line {n}" for n in range(30)) + "\nImportError: no module named x"
    proc = subprocess.CompletedProcess([], 1, stdout="starting\n", stderr=stderr)
    with pytest.raises(RuntimeError) as err:
        parse_summary("ingest", proc)
    message = str(err.value)
    assert "ingest crashed (exit 1)" in message
    assert "ImportError: no module named x" in message
    assert "line 5\n" not in message  # only the end of stderr


def test_allocate_prints_the_next_free_run_id(tmp_path: Path) -> None:
    def allocate() -> str:
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        env["PULSE_DATA_DIR"] = str(tmp_path)
        out = subprocess.run(
            [shutil.which("uv") or "uv", "run", "--project", str(REPO), "--frozen", "--quiet",
             "python", str(LAB / "pulse_stage.py"), "allocate", "--week", "2026-W45",
             "--run-type", "MANUAL"],
            cwd=REPO, env=env, capture_output=True, text=True, check=True,
        )  # fmt: skip
        return str(json.loads(out.stdout.splitlines()[-1])["run_id"])

    assert allocate() == "manual-2026-W45-airflow-1"
    assert allocate() == "manual-2026-W45-airflow-1"  # nothing recorded under it yet
    assert {"export"} == pulse_weekly.ALWAYS
