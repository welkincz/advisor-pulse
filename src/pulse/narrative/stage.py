"""The ``narrate`` stage: one narrative per region and district into
``$PULSE_DATA_DIR/narratives/YYYY-Www.json``, which the export stage publishes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import duckdb

from pulse.contracts import column_names
from pulse.contracts.enums import StageStatus
from pulse.contracts.exports import NarrativeFile, WeeklyReport
from pulse.narrative.client import NarrativeClient, client_from_env
from pulse.narrative.facts import HISTORY_WEEKS, build_facts, narrated_nodes, weeks_back
from pulse.narrative.generate import ResponseCache, narrate_node
from pulse.runner.stage import StageContext, StageResult
from pulse.warehouse import WAREHOUSE_FILE, connect

NARRATIVES_DIR = "narratives"
CACHE_DIR = "cache"

ClientFactory = Callable[[], NarrativeClient | None]


def _has_report(con: duckdb.DuckDBPyConnection) -> bool:
    row = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'marts' AND table_name = 'mart_weekly_report'"
    ).fetchone()
    return bool(row and row[0])


def load_report(con: duckdb.DuckDBPyConnection, week: str) -> list[WeeklyReport]:
    """This week plus the 12 before it: enough for the 13-week history facts."""
    first = weeks_back(week, HISTORY_WEEKS - 1)[0]
    columns = column_names(WeeklyReport)
    projection = ", ".join(f'"{c}"' for c in columns)
    rows = con.execute(
        f"SELECT {projection} FROM marts.mart_weekly_report WHERE iso_week_id BETWEEN ? AND ? "
        "ORDER BY iso_week_id, level, node_id, kpi_code",
        [first, week],
    ).fetchall()
    return [WeeklyReport.model_validate(dict(zip(columns, r, strict=True))) for r in rows]


def write_narratives(
    report: list[WeeklyReport],
    week: str,
    out_dir: Path,
    client: NarrativeClient | None,
    ctx: StageContext,
) -> StageResult:
    nodes = narrated_nodes(report, week)
    if not nodes:
        return StageResult(StageStatus.SKIPPED, message=f"No region or district rows for {week}.")
    cache = ResponseCache(out_dir / CACHE_DIR)
    outcomes = [
        narrate_node(build_facts(report, node_id, week), client, cache) for node_id, _ in nodes
    ]
    doc = NarrativeFile(
        iso_week_id=week,
        generated_at=ctx.clock.now(),
        narratives=[o.narrative for o in outcomes],
    )
    path = out_dir / f"{week}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial")
    partial.write_text(doc.model_dump_json(indent=2) + "\n", encoding="utf-8")
    partial.replace(path)

    total = len(outcomes)
    fell_back = [o for o in outcomes if o.narrative.fallback]
    hits = sum(o.cached for o in outcomes)
    if client is None:
        return StageResult(
            StageStatus.WARN,
            rows_out=total,
            message=f"No model backend configured: wrote {total} template narratives.",
        )
    if fell_back:
        reasons = sorted({o.reason or "unknown" for o in fell_back})
        return StageResult(
            StageStatus.WARN,
            rows_out=total,
            message=f"{len(fell_back)} of {total} narratives fell back to the template "
            f"({'; '.join(reasons)}).",
        )
    return StageResult(rows_out=total, message=f"{total} narratives validated ({hits} from cache).")


def narrate(ctx: StageContext, client_factory: ClientFactory = client_from_env) -> StageResult:
    warehouse = ctx.data_dir / WAREHOUSE_FILE
    if not warehouse.exists():
        return StageResult(StageStatus.SKIPPED, message="No warehouse yet.")
    con = connect(warehouse, read_only=True)
    try:
        if not _has_report(con):
            return StageResult(
                StageStatus.SKIPPED, message="marts.mart_weekly_report not built yet (issue #28)."
            )
        report = load_report(con, ctx.iso_week_id)
    finally:
        con.close()
    return write_narratives(
        report, ctx.iso_week_id, ctx.data_dir / NARRATIVES_DIR, client_factory(), ctx
    )
