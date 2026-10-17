"""The runner's ``generate`` stage: this week's source extracts, before ingest reads them.

The week is generated only if its activity partition is missing, so a data dir that
already holds the week (copied fixture sources, a re-run) is left untouched. A generator
error propagates, and the runner logs it as the stage's FAILED message.
"""

from __future__ import annotations

from pulse.contracts.enums import StageStatus
from pulse.generate.cli import SOURCES_DIR, Sizes, activity_dir, default_seed, generate_weeks
from pulse.runner.stage import StageContext, StageResult

# Module-level so tests can generate a smaller world.
SIZES = Sizes()


def generate(ctx: StageContext, sizes: Sizes | None = None) -> StageResult:
    partition = activity_dir(ctx.data_dir / SOURCES_DIR, ctx.iso_week_id)
    if partition.exists():
        return StageResult(
            StageStatus.SKIPPED,
            message=f"Sources for {ctx.iso_week_id} already present; not regenerated.",
        )
    lines: list[str] = []
    generate_weeks(
        ctx.data_dir,
        [ctx.iso_week_id],
        seed=default_seed(),
        sizes=sizes or SIZES,
        echo=lines.append,
    )
    return StageResult(StageStatus.SUCCESS, message=" ".join(lines))
