"""The ``narrate`` stage: one narrative per region and district into
``$PULSE_DATA_DIR/narratives/YYYY-Www.json``, which the export stage publishes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import duckdb

from pulse.contracts import column_names
from pulse.contracts.enums import StageStatus
from pulse.contracts.exports import NarrativeFile, WeeklyReport
from pulse.export.web import NARRATIVE_WINDOW_WEEKS
from pulse.narrative.client import NarrativeClient, client_from_env
from pulse.narrative.facts import HISTORY_WEEKS, build_facts, narrated_nodes, weeks_back
from pulse.narrative.generate import Outcome, ResponseCache, narrate_node
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


def load_report(
    con: duckdb.DuckDBPyConnection, week: str, history: int = HISTORY_WEEKS
) -> list[WeeklyReport]:
    """This week and its requested history window (13 weeks by default)."""
    first = weeks_back(week, history - 1)[0]
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
    *,
    templates_only: bool = False,
) -> StageResult:
    nodes = narrated_nodes(report, week)
    if not nodes:
        return StageResult(StageStatus.SKIPPED, message=f"No region or district rows for {week}.")
    path = out_dir / f"{week}.json"
    old = NarrativeFile.model_validate_json(path.read_text()) if path.exists() else None
    existing = {n.node_id: n for n in old.narratives} if old else {}
    retained = {key: n for key, n in existing.items() if n.model is not None}
    # Index once: each node needs its own history and only its current children.
    own: dict[str, list[WeeklyReport]] = defaultdict(list)
    children: dict[str | None, list[WeeklyReport]] = defaultdict(list)
    for row in report:
        own[row.node_id].append(row)
        if row.iso_week_id == week:
            children[row.parent_id].append(row)
    cache = ResponseCache(out_dir / CACHE_DIR)
    outcomes = [
        Outcome(retained[node_id], cached=True)
        if node_id in retained
        else narrate_node(
            build_facts(own[node_id] + children[node_id], node_id, week),
            None if templates_only or node_id in existing else client,
            cache,
        )
        for node_id, _ in nodes
    ]
    narratives = [o.narrative for o in outcomes]
    narratives.extend(
        n for key, n in retained.items() if key not in {x.node_id for x in narratives}
    )
    doc = NarrativeFile(
        iso_week_id=week,
        generated_at=old.generated_at if old and retained else ctx.clock.now(),
        narratives=narratives,
    )
    if doc != old:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        partial.write_text(doc.model_dump_json(indent=2) + "\n", encoding="utf-8")
        partial.replace(path)
    if templates_only:
        total = len(narratives) - len(retained)
        return StageResult(
            rows_out=total,
            message=f"Rebuilt {total} templates; kept {len(retained)} model narratives.",
        )

    total = len(outcomes)
    fell_back = [
        o for o in outcomes if o.narrative.fallback and o.narrative.node_id not in existing
    ]
    hits = sum(o.cached for o in outcomes)
    if client is None and retained:
        return StageResult(
            rows_out=total,
            message=(
                f"Rebuilt {total - len(retained)} templates; kept {len(retained)} model narratives."
            ),
        )
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
        last = con.execute("select max(iso_week_id) from marts.mart_weekly_report").fetchone()
        latest = last[0] if last else None
        if latest is None:
            return StageResult(StageStatus.SKIPPED, message="No reporting weeks yet.")
        report = load_report(con, latest, HISTORY_WEEKS + NARRATIVE_WINDOW_WEEKS - 1)
        first = weeks_back(latest, NARRATIVE_WINDOW_WEEKS - 1)[0]
        weeks = sorted({r.iso_week_id for r in report if first <= r.iso_week_id <= latest})
        requested = report if ctx.iso_week_id >= first else load_report(con, ctx.iso_week_id)
    finally:
        con.close()
    out = ctx.data_dir / NARRATIVES_DIR
    for week in weeks:
        # A missing latest file still needs its first model opportunity at that week's run.
        if week != ctx.iso_week_id and (week < latest or (out / f"{week}.json").exists()):
            write_narratives(report, week, out, None, ctx, templates_only=True)
    historical = ctx.iso_week_id < latest
    return write_narratives(
        requested,
        ctx.iso_week_id,
        out,
        None if historical else client_factory(),
        ctx,
        templates_only=historical,
    )
