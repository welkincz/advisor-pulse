"""A backfill loads weeks in order, then finalizes the complete batch."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pulse.generate.cli import activity_dir
from pulse.runner.backfill import backfill_range
from pulse.runner.stage import Stage, StageContext, StageResult


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 5, 4, tzinfo=UTC)

    def sleep(self, seconds: float) -> None:
        pass


def test_dbt_runs_once_after_every_week_is_ingested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pulse.runner.dag as dag

    seen: list[tuple[str, str]] = []

    def operation(name: str):
        def run(ctx: StageContext) -> StageResult:
            seen.append((ctx.iso_week_id, name))
            if name == "generate":
                activity_dir(ctx.data_dir / "sources", ctx.iso_week_id).mkdir(parents=True)
            return StageResult()

        return run

    names = (
        "restore_state",
        "generate",
        "ingest",
        "dbt_build",
        "checks",
        "export",
        "persist_state",
        "release_lock",
    )
    stages = tuple(
        Stage(name, name, operation(name), (names[index - 1],) if index else ())
        for index, name in enumerate(names)
    )
    monkeypatch.setattr(dag, "WEEKLY_STAGES", stages)
    assert backfill_range("2026-W37", "2026-W39", data_dir=tmp_path, clock=Clock()) == 0
    assert [week for week, name in seen if name == "ingest"] == ["2026-W37", "2026-W38", "2026-W39"]
    assert [week for week, name in seen if name == "dbt_build"] == ["2026-W39"]
    assert seen.index(("2026-W39", "ingest")) < seen.index(("2026-W39", "dbt_build"))
