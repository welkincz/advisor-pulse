"""Run one weekly-runner stage for the Airflow lab, in the root project's environment.

Airflow (lab env) calls this through ``uv run --project <repo>``, so Airflow's pinned
dependencies never meet dbt's. The stage functions are the runner's own (``WEEKLY_STAGES``);
each attempt is recorded in ``meta.run_log`` with Airflow's try number as the attempt.
The last stdout line is a JSON summary that the Airflow task returns as its XCom.

Exit code: 0 for SUCCESS, WARN or SKIPPED; 1 for FAILED (Airflow then retries or fails).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pulse.contracts.enums import RunType, StageStatus
from pulse.contracts.meta import RunLogRow
from pulse.generate import stage as generate_stage
from pulse.generate.cli import Sizes
from pulse.narrative.stage import narrate
from pulse.runner.dag import WEEKLY_STAGES
from pulse.runner.run import WarehouseSink
from pulse.runner.stage import StageContext, StageFn, StageResult, SystemClock
from pulse.warehouse import WAREHOUSE_FILE

# The R2 state stages (restore/persist/release) are left out: the lab keeps local state.
LAB_STAGES = ("generate", "ingest", "dbt_build", "checks", "narrate", "export")


def stage_fn(name: str) -> StageFn:
    if name == "narrate":
        # Template narratives only: no model backend, no API key, deterministic text.
        return lambda ctx: narrate(ctx, client_factory=lambda: None)
    return next(s.fn for s in WEEKLY_STAGES if s.name == name)


def run(name: str, ctx: StageContext, attempt: int) -> StageResult:
    sink = WarehouseSink(ctx.data_dir / WAREHOUSE_FILE)
    started = ctx.clock.now()
    base = RunLogRow(
        run_id=ctx.run_id,
        run_type=ctx.run_type,
        iso_week_id=ctx.iso_week_id,
        stage=name,
        attempt=attempt,
        status=StageStatus.RUNNING,
        started_at=started,
    )
    sink.write(base)
    try:
        result = stage_fn(name)(ctx)
    except Exception as exc:
        result = StageResult(StageStatus.FAILED, message=f"{type(exc).__name__}: {exc}")
    ended = ctx.clock.now()
    sink.write(
        base.model_copy(
            update={
                "status": result.status,
                "ended_at": ended,
                "duration_ms": max(0, int((ended - started).total_seconds() * 1000)),
                "rows_in": result.rows_in,
                "rows_out": result.rows_out,
                "message": result.message,
            }
        )
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=LAB_STAGES)
    parser.add_argument("--week", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-type", default=RunType.WEEKLY.value)
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args(argv)

    data_dir = Path(os.environ["PULSE_DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    generate_stage.SIZES = Sizes(
        advisors=int(os.environ.get("PULSE_LAB_ADVISORS", "60")),
        clients=int(os.environ.get("PULSE_LAB_CLIENTS", "1500")),
    )
    ctx = StageContext(args.run_id, RunType(args.run_type), args.week, data_dir, SystemClock())
    result = run(args.stage, ctx, args.attempt)
    summary = {
        "stage": args.stage,
        "week": args.week,
        "attempt": args.attempt,
        "status": result.status.value,
        "rows_out": result.rows_out,
        "message": result.message,
    }
    print(json.dumps(summary))
    return 1 if result.status is StageStatus.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
