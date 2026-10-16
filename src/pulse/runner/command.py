"""``pulse run``: wire the weekly stages to the warehouse run log and ``run_log.json``."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

from pulse.contracts.enums import RunType
from pulse.ingest import meta
from pulse.runner import run_log
from pulse.runner.dag import WEEKLY_STAGES
from pulse.runner.run import Runner, WarehouseSink, new_run_id, plan, resolve_week
from pulse.runner.stage import Clock, Stage, SystemClock
from pulse.warehouse import WAREHOUSE_FILE, connect, init_warehouse

RUN_LOG_JSON = Path("exports") / "run_log.json"


def run_week(
    week: str | None,
    *,
    data_dir: Path,
    run_type: RunType = RunType.MANUAL,
    dry_run: bool = False,
    stages: Sequence[Stage] = WEEKLY_STAGES,
    clock: Clock | None = None,
    echo: Callable[[str], None] = print,
) -> int:
    """Run (or with ``dry_run``, plan) one week. Returns the process exit code."""
    clock = clock or SystemClock()
    iso_week = resolve_week(week, clock.now().date())

    if dry_run:
        echo(f"Plan for {iso_week} ({run_type.value}), nothing will run:")
        for line in plan(stages):
            echo(f"  {line}")
        return 0

    warehouse = data_dir / WAREHOUSE_FILE
    con = connect(warehouse)
    try:
        init_warehouse(con)
        existing = {r.run_id for r in meta.get_run_log(con)}
    finally:
        con.close()
    # Imported on call: pulse.state imports the runner. On a fresh CI runner the local
    # warehouse is empty, so the ids persisted to R2 keep run_ids unique across runners.
    from pulse.state import STATE

    run_id = new_run_id(run_type, iso_week, existing | STATE.known_run_ids())

    runner = Runner(
        stages,
        data_dir=data_dir,
        sinks=[WarehouseSink(warehouse)],
        clock=clock,
        git_sha=os.environ.get("GITHUB_SHA"),
    )
    report = runner.run(iso_week, run_type, run_id)

    con = connect(warehouse, read_only=True)
    try:
        doc = run_log.export_from_warehouse(con, generated_at=clock.now())
    finally:
        con.close()
    run_log.write_json(doc, data_dir / RUN_LOG_JSON)

    for row in report.rows:
        echo(f"  {row.stage:<15} attempt {row.attempt}  {row.status.value:<8} {row.message or ''}")
    echo(f"{report.run_id}: {report.status.value}")
    return 1 if report.failed else 0
