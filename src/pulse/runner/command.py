"""``pulse run``: wire the weekly stages to the warehouse run log and ``run_log.json``."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

from pulse.contracts.enums import RunType, StageStatus
from pulse.contracts.exports import RunLogExport
from pulse.contracts.meta import RunLogRow
from pulse.ingest import meta
from pulse.runner import run_log
from pulse.runner.dag import WEEKLY_STAGES
from pulse.runner.run import Runner, WarehouseSink, new_run_id, plan, resolve_week
from pulse.runner.stage import Clock, Stage, SystemClock
from pulse.warehouse import WAREHOUSE_FILE, connect, init_warehouse

RUN_LOG_JSON = Path("exports") / "run_log.json"
EXPORT_STAGE = "export"


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
        doc = run_log.export_from_warehouse(
            con, generated_at=clock.now(), current_run_id=report.run_id
        )
    finally:
        con.close()
    run_log.write_json(doc, data_dir / RUN_LOG_JSON)
    refreshed = _refresh_exported_run_log(report.rows, doc, echo)

    for row in report.rows:
        echo(f"  {row.stage:<15} attempt {row.attempt}  {row.status.value:<8} {row.message or ''}")
    echo(f"{report.run_id}: {report.status.value}")
    return 1 if report.failed or not refreshed else 0


def _refresh_exported_run_log(
    rows: Sequence[RunLogRow], doc: RunLogExport, echo: Callable[[str], None]
) -> bool:
    """Republish the site's ``run_log.json`` now that every stage has finished.

    The export stage writes it while export itself is RUNNING and the stages after it have
    not started (#281). When export ran, or failed, this copy replaces that snapshot so the
    site shows each stage's final status; a failed export keeps the previous data. A
    SKIPPED export (no marts yet, or a halted run) published nothing and stays untouched.
    Returns False, after saying why, when the refresh itself fails.
    """
    from pulse.export.web import publish_run_log
    from pulse.runner.stages import export_dir

    finals = [r for r in rows if r.stage == EXPORT_STAGE]
    if not finals or finals[-1].status is StageStatus.SKIPPED:
        return True
    try:
        publish_run_log(export_dir(), doc)
    except Exception as exc:
        echo(
            "Could not republish run_log.json with final stage statuses: "
            f"{type(exc).__name__}: {exc}"
        )
        return False
    return True
