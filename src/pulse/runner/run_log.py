"""Fold ``meta.run_log`` and ``meta.check_result`` rows into the ``run_log.json`` document."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import duckdb

from pulse.contracts.exports import RunCheck, RunLogExport, RunSummary, StageAttempt
from pulse.contracts.meta import CheckResult, RunLogRow
from pulse.ingest import meta
from pulse.runner.run import run_status

MAX_RUNS = 12


def summarize(rows: Sequence[RunLogRow], checks: Sequence[CheckResult] = ()) -> list[RunSummary]:
    """One summary per run, newest first. Status uses each stage's last attempt only, so a
    stage that failed once and then succeeded does not fail the run."""
    by_run: dict[str, list[RunLogRow]] = defaultdict(list)
    for row in rows:
        by_run[row.run_id].append(row)
    checks_by_run: dict[str, list[CheckResult]] = defaultdict(list)
    for check in checks:
        checks_by_run[check.run_id].append(check)

    summaries = []
    for run_id, run_rows in by_run.items():
        run_rows.sort(key=lambda r: (r.started_at, r.attempt))
        last: dict[str, RunLogRow] = {}
        for r in run_rows:
            if r.stage not in last or r.attempt > last[r.stage].attempt:
                last[r.stage] = r
        started = run_rows[0].started_at
        ends = [r.ended_at for r in run_rows]
        ended = None if any(e is None for e in ends) else max(e for e in ends if e is not None)
        first = run_rows[0]
        summaries.append(
            RunSummary(
                run_id=run_id,
                run_type=first.run_type,
                iso_week_id=first.iso_week_id,
                status=run_status(r.status for r in last.values()),
                started_at=started,
                ended_at=ended,
                duration_ms=None
                if ended is None
                else int((ended - started).total_seconds() * 1000),
                git_sha=next((r.git_sha for r in run_rows if r.git_sha), None),
                stages=[
                    StageAttempt.model_validate(
                        r.model_dump(include=set(StageAttempt.model_fields))
                    )
                    for r in run_rows
                ],
                checks=[
                    RunCheck.model_validate(c.model_dump(include=set(RunCheck.model_fields)))
                    for c in sorted(checks_by_run[run_id], key=lambda c: c.check_id)
                ],
            )
        )
    summaries.sort(key=lambda s: s.started_at, reverse=True)
    return summaries


def build_export(
    rows: Sequence[RunLogRow], checks: Sequence[CheckResult], generated_at: datetime
) -> RunLogExport:
    return RunLogExport(generated_at=generated_at, runs=summarize(rows, checks)[:MAX_RUNS])


def export_from_warehouse(con: duckdb.DuckDBPyConnection, generated_at: datetime) -> RunLogExport:
    rows = meta.get_run_log(con)
    checks = [c for run_id in {r.run_id for r in rows} for c in meta.get_check_results(con, run_id)]
    return build_export(rows, checks, generated_at)


def write_json(doc: RunLogExport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc.model_dump_json(indent=2, by_alias=True) + "\n", encoding="utf-8")
