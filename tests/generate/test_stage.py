from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pulse.contracts.enums import RunType, StageStatus
from pulse.generate.cli import Sizes, activity_dir
from pulse.generate.stage import generate
from pulse.runner import Runner, StageContext
from pulse.runner.dag import WEEKLY_STAGES
from pulse.runner.stage import Stage

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
SMALL = Sizes(advisors=60, clients=1500)


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 5, 4, tzinfo=UTC)

    def sleep(self, seconds: float) -> None:
        pass


def ctx(data_dir: Path, week: str = "2026-W40") -> StageContext:
    return StageContext(f"manual-{week}-1", RunType.MANUAL, week, data_dir, Clock())


def test_generates_the_week_into_an_empty_data_dir(tmp_path: Path) -> None:
    result = generate(ctx(tmp_path), SMALL)
    assert result.status is StageStatus.SUCCESS
    assert "2026-W40: generated with" in (result.message or "")
    assert activity_dir(tmp_path / "sources", "2026-W40").is_dir()
    assert (tmp_path / "defects.json").exists()


def test_skips_when_the_week_is_already_present(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES / "sources", tmp_path / "sources")
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    result = generate(ctx(tmp_path), SMALL)
    assert result.status is StageStatus.SKIPPED
    assert "already present" in (result.message or "")
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before


def test_a_generator_error_fails_the_stage_with_its_message(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="before the generator's first week"):
        generate(ctx(tmp_path, "2024-W01"), SMALL)

    stages = [
        Stage("generate", "Generate week", lambda c: generate(c, SMALL)),
    ]
    report = Runner(stages, data_dir=tmp_path, sinks=[], clock=Clock()).run(
        "2024-W01", RunType.MANUAL, "manual-2024-W01-1"
    )
    assert report.status is StageStatus.FAILED
    final = report.rows[-1]
    assert final.status is StageStatus.FAILED
    assert "ValueError" in (final.message or "") and "2024-W41" in (final.message or "")


def test_weekly_dag_wires_the_generate_stage() -> None:
    by_name = {s.name: s for s in WEEKLY_STAGES}
    assert by_name["generate"].depends_on == ("restore_state",)
    assert by_name["generate"].fn.__name__ == "_generate"
