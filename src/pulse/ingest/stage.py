"""The runner's ``ingest`` stage: every loader, in one order, against one warehouse.

Each loader commits its own files atomically (raw rows, watermark, manifest and quarantine
together), so a crash between loaders leaves the earlier sources fully loaded and the later
ones untouched. A re-run skips what is already in the manifest and loads the rest, which
gives the same final state as an uninterrupted run (tests/integration/test_idempotency.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pulse.contracts.enums import StageStatus
from pulse.ingest.snowflake import load_snowflake_activity
from pulse.ingest.teradata_client import load_teradata_client
from pulse.ingest.teradata_hr import load_teradata_hr
from pulse.runner.stage import StageContext, StageResult
from pulse.warehouse import WAREHOUSE_FILE, connect, init_warehouse

SOURCES_DIR = "sources"
_EDW = Path("teradata/edw.sqlite")
_ACTIVITY = Path("snowflake/activity")


@dataclass(frozen=True)
class _Part:
    name: str
    result: StageResult


def _combine(parts: list[_Part]) -> StageResult:
    statuses = {p.result.status for p in parts}
    if StageStatus.FAILED in statuses:
        status = StageStatus.FAILED
    elif StageStatus.WARN in statuses:
        status = StageStatus.WARN
    elif statuses == {StageStatus.SKIPPED}:
        status = StageStatus.SKIPPED
    else:
        status = StageStatus.SUCCESS

    def total(field: str) -> int:
        return sum(getattr(p.result, field) or 0 for p in parts)

    message = "; ".join(f"{p.name}: {p.result.message or p.result.status.value}" for p in parts)
    return StageResult(
        status,
        rows_in=total("rows_in"),
        rows_out=total("rows_out"),
        rows_quarantined=total("rows_quarantined"),
        message=message,
    )


def ingest(ctx: StageContext) -> StageResult:
    """Load ``$data_dir/sources`` into ``$data_dir/warehouse.duckdb``."""
    sources = ctx.data_dir / SOURCES_DIR
    has_edw = (sources / _EDW).is_file()
    has_activity = (sources / _ACTIVITY).is_dir()
    if not has_edw and not has_activity:
        return StageResult(StageStatus.SKIPPED, 0, 0, 0, f"No source files under {sources}")

    loaded_at = ctx.clock.now()
    con = connect(ctx.data_dir / WAREHOUSE_FILE)
    try:
        init_warehouse(con)
        parts: list[_Part] = []
        if has_activity:
            parts.append(
                _Part(
                    "activity",
                    load_snowflake_activity(con, sources, run_id=ctx.run_id, loaded_at=loaded_at),
                )
            )
        if has_edw:
            parts.append(
                _Part(
                    "clients",
                    load_teradata_client(con, sources, run_id=ctx.run_id, loaded_at=loaded_at),
                )
            )
            hr = load_teradata_hr(con, sources / _EDW, run_id=ctx.run_id, loaded_at=loaded_at)
            parts.append(
                _Part(
                    "hr",
                    StageResult(
                        StageStatus.SKIPPED if hr.skipped else StageStatus.SUCCESS,
                        rows_in=hr.rows_read,
                        rows_out=hr.rows_loaded,
                        rows_quarantined=0,
                        message="SKIPPED_DUPLICATE" if hr.skipped else None,
                    ),
                )
            )
    finally:
        con.close()
    return _combine(parts)
