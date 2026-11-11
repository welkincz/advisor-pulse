"""Advisor Pulse weekly run as an Airflow DAG. Local lab, synthetic data, single machine.

Each task runs one stage of the project's own runner (``src/pulse/runner/dag.py``) through
``pulse_stage.py`` in the root project's environment. Airflow owns scheduling and retries
here; the stage code is unchanged.

Schedule: Mondays 06:00 UTC with a data interval of the previous Monday 06:00 to this Monday
06:00. The interval's start date is the Monday of the week being reported, so a run that
fires on Monday reports the week that just ended, which is what ``pulse run --week last``
does. Catchup is off; a backfill creates one run per interval, one ISO week each.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pendulum
from airflow.sdk import DAG, task
from airflow.sdk.exceptions import AirflowFailException
from airflow.timetables.interval import CronDataIntervalTimetable

LAB_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = LAB_DIR.parents[1]
STAGE_SCRIPT = LAB_DIR / "pulse_stage.py"

# Mirrors WEEKLY_STAGES in src/pulse/runner/dag.py without the R2 state stages.
# tests/test_dag_integrity.py fails if this drifts from the runner's order.
STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("generate", ()),
    ("ingest", ("generate",)),
    ("dbt_build", ("ingest",)),
    ("checks", ("dbt_build",)),
    ("narrate", ("checks",)),
    ("export", ("narrate",)),
)
# The runner's ``always`` stages: export still runs after a failure (publishes run_log only).
ALWAYS = frozenset({"export"})

RUN_TYPES = {"scheduled": "WEEKLY", "backfill": "BACKFILL"}


def iso_week_for(interval_start: datetime) -> str:
    """The ISO week a run reports: the week containing its data interval's start."""
    year, week, _ = interval_start.isocalendar()
    return f"{year}-W{week:02d}"


# The first task: allocates this DagRun's pulse run id, which every stage then uses.
ALLOCATE = "pulse_run_id"


def _retry_delay() -> timedelta:
    return timedelta(seconds=float(os.environ.get("PULSE_AIRFLOW_RETRY_DELAY_S", "300")))


def _stage_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    if "PULSE_DATA_DIR" not in env:
        raise RuntimeError("Set PULSE_DATA_DIR to a scratch directory before running the lab.")
    # Never let the lab write into the site's web/public/data.
    env.setdefault("PULSE_EXPORT_DIR", str(Path(env["PULSE_DATA_DIR"]) / "web-export"))
    return env


def parse_summary(stage: str, proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """The last stdout line that parses as a JSON object. A crash can print other lines after
    it, or none at all; then the error names the return code and the end of stderr."""
    for line in reversed(proc.stdout.strip().splitlines()):
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict):
            return doc
    tail = "\n".join(proc.stderr.strip().splitlines()[-20:])
    raise RuntimeError(f"{stage} crashed (exit {proc.returncode}) with no JSON summary:\n{tail}")


def _call(stage: str, week: str, run_type: str, *extra: str) -> dict[str, Any]:
    uv = shutil.which("uv") or "uv"
    cmd = [
        uv, "run", "--project", str(REPO_ROOT), "--frozen", "--quiet",
        "python", str(STAGE_SCRIPT), stage, "--week", week, "--run-type", run_type, *extra,
    ]  # fmt: skip
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, env=_stage_env(), capture_output=True, text=True, check=False
    )
    print(proc.stdout + proc.stderr)
    summary = parse_summary(stage, proc)
    if proc.returncode != 0:
        raise RuntimeError(f"{stage} {summary.get('status', 'crashed')}: {summary.get('message')}")
    return summary


def _week_and_type(context: dict[str, Any]) -> tuple[str, str]:
    airflow_type = str(getattr(context["dag_run"].run_type, "value", context["dag_run"].run_type))
    return iso_week_for(context["data_interval_start"]), RUN_TYPES.get(airflow_type, "MANUAL")


def allocate_run_id(**context: Any) -> str:
    """A new pulse run id for each DagRun (``manual-2026-W45-airflow-2``). Retries and cleared
    tasks inside one DagRun reuse it through XCom; a new DagRun for the same week gets the
    next number, so its stages are not outranked by an earlier failed run's attempts."""
    week, run_type = _week_and_type(context)
    return str(_call("allocate", week, run_type)["run_id"])


def run_stage(stage: str, run_id: str, **context: Any) -> dict[str, Any]:
    week, run_type = _week_and_type(context)
    try_number = str(context["ti"].try_number)
    return _call(stage, week, run_type, "--run-id", run_id, "--attempt", try_number)


def fail_run(**context: Any) -> None:
    """Runs only when a stage failed. Without it the run would end green: Airflow judges a
    run by its leaf tasks, and export (all_done) succeeds after a failure by design."""
    raise AirflowFailException("A weekly stage failed; see the failed task's log and run_log.")


with DAG(
    dag_id="pulse_weekly",
    description="Advisor Pulse weekly report (local Airflow lab, synthetic data).",
    schedule=CronDataIntervalTimetable("0 6 * * 1", timezone="UTC"),
    start_date=pendulum.datetime(2024, 10, 7, 6, tz="UTC"),  # first reported week, 2024-W41
    catchup=False,
    max_active_runs=1,  # weeks share one warehouse and SCD2 history: one at a time
    dagrun_timeout=timedelta(hours=2),
    default_args={
        "owner": "advisor-pulse",
        "retries": 2,
        "retry_delay": _retry_delay(),
        "retry_exponential_backoff": True,
        "execution_timeout": timedelta(minutes=30),
        "depends_on_past": False,
    },
    tags=["advisor-pulse", "lab"],
) as dag:
    # depends_on_past + wait_for_downstream on the first task: a week starts only after the
    # previous week's pulse_run_id task and all of its direct downstream tasks (every stage
    # and run_status) succeeded or were skipped. A failed week therefore blocks the next one
    # until it is re-run or marked done.
    run_id = task(task_id=ALLOCATE, depends_on_past=True, wait_for_downstream=True)(
        allocate_run_id
    )()
    tasks = {ALLOCATE: run_id}
    for name, _deps in STAGES:
        rule = "all_done" if name in ALWAYS else "all_success"
        tasks[name] = task(task_id=name, trigger_rule=rule)(run_stage)(stage=name, run_id=run_id)
    for name, deps in STAGES:
        for dep in deps:
            tasks[dep] >> tasks[name]
    # The runner's run status is the worst stage status; this makes the Airflow run agree.
    (
        list(tasks.values())
        >> task(task_id="run_status", trigger_rule="one_failed", retries=0)(fail_run)()
    )
