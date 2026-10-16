"""Stage DAG: validation, execution order, and the weekly pipeline's default stages."""

from __future__ import annotations

from collections.abc import Sequence

from pulse.runner.stage import Stage, not_implemented


class DagError(ValueError):
    """Raised for duplicate stage names, unknown dependencies, or cycles."""


def execution_order(stages: Sequence[Stage]) -> list[Stage]:
    """Topological order. Ties keep registration order, so the plan is stable."""
    by_name: dict[str, Stage] = {}
    for stage in stages:
        if stage.name in by_name:
            raise DagError(f"Duplicate stage name: {stage.name}")
        by_name[stage.name] = stage
    for stage in stages:
        for dep in stage.depends_on:
            if dep not in by_name:
                raise DagError(f"{stage.name} depends on unknown stage {dep}")

    done: set[str] = set()
    ordered: list[Stage] = []
    while len(ordered) < len(stages):
        ready = [s for s in stages if s.name not in done and set(s.depends_on) <= done]
        if not ready:
            stuck = sorted(s.name for s in stages if s.name not in done)
            raise DagError(f"Cycle among stages: {', '.join(stuck)}")
        ordered.append(ready[0])
        done.add(ready[0].name)
    return ordered


def downstream(stages: Sequence[Stage], name: str) -> set[str]:
    """Every stage that depends on ``name``, directly or transitively."""
    found: set[str] = set()
    frontier = {name}
    while frontier:
        nxt = {s.name for s in stages if set(s.depends_on) & frontier} - found
        found |= nxt
        frontier = nxt
    return found


# Stages land one issue at a time; until then each is a SKIPPED placeholder naming its issue.
WEEKLY_STAGES: tuple[Stage, ...] = (
    Stage("restore_state", "Restore state", not_implemented(45)),
    Stage("generate", "Generate week", not_implemented(16), ("restore_state",)),
    Stage("ingest", "Ingest + validate", not_implemented(52), ("generate",)),
    Stage("dbt_build", "dbt build", not_implemented(52), ("ingest",)),
    Stage("checks", "Run checks", not_implemented(44), ("dbt_build",)),
    Stage("narrate", "AI narrative", not_implemented(47), ("checks",)),
    Stage("export", "Export", not_implemented(46), ("narrate",)),
    Stage("publish_sheets", "Google Sheets", not_implemented(55), ("export",)),
    Stage("persist_state", "Persist state", not_implemented(45), ("export",)),
)
