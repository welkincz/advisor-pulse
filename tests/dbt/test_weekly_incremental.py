"""Weekly incremental models equal a full refresh (#304).

Every model built with the ``replace_from`` strategy (dbt/macros/weekly_incremental.sql) is
found in dbt's manifest, so a new one is covered without editing this file. On the fixtures:
load through W39 and build, then load the W40 extract (rows one to three weeks late) and
build incrementally. Each model must match a ``--full-refresh`` exactly, a second run of the
same week must change nothing, and the run must really be incremental: its delete starts at
a week, not at the beginning. A lookback too short for the late rows must break the match,
so the comparison can fail.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pulse.contracts.enums import RunType, StageStatus
from pulse.ingest.stage import SOURCES_DIR, ingest
from pulse.runner.stage import StageContext
from pulse.warehouse import WAREHOUSE_FILE, connect

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "fixtures" / "sources"
DBT_DIR = ROOT / "dbt"
STRATEGY = "replace_from"
pytestmark = pytest.mark.integration

Hashes = dict[str, tuple[int, int]]


class _Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at

    def sleep(self, seconds: float) -> None:
        pass


def _link_sources(sources: Path, through: str) -> None:
    """Fixture sources with Snowflake extracts up to and including `through`."""
    activity = sources / "snowflake" / "activity"
    activity.mkdir(parents=True, exist_ok=True)
    for partition in sorted((FIXTURES / "snowflake" / "activity").iterdir()):
        target = activity / partition.name
        if partition.name <= f"extract_date={through}" and not target.exists():
            shutil.copytree(partition, target)  # the loader's rglob does not follow symlinks
    if not (sources / "teradata").exists():
        (sources / "teradata").symlink_to(FIXTURES / "teradata", target_is_directory=True)


def _ingest(data_dir: Path, week: str, at: datetime) -> None:
    result = ingest(StageContext(f"test-{week}", RunType.MANUAL, week, data_dir, _Clock(at)))
    assert result.status is not StageStatus.FAILED, result.message


def _dbt(data_dir: Path, *args: str) -> None:
    command = [
        sys.executable,
        "-m",
        "dbt.cli.main",
        "--no-use-colors",
        "build",
        "--project-dir",
        str(DBT_DIR),
        "--profiles-dir",
        str(DBT_DIR),
        "--target",
        "dev",
        "--target-path",
        str(data_dir / "target"),
        "--resource-type",
        "seed",
        "--resource-type",
        "model",
        *args,
    ]
    env = {**os.environ, "PULSE_DATA_DIR": str(data_dir)}
    proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout[-3000:]


def _incremental_models(data_dir: Path) -> dict[str, str]:
    """Model name -> schema, for every model built with the replace_from strategy."""
    manifest = json.loads((data_dir / "target" / "manifest.json").read_text())
    models = {
        node["name"]: node["schema"]
        for node in manifest["nodes"].values()
        if node["resource_type"] == "model"
        and node["config"].get("incremental_strategy") == STRATEGY
    }
    assert len(models) >= 9, models
    return models


def _hashes(data_dir: Path, models: dict[str, str]) -> Hashes:
    con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
    try:
        return {
            name: con.execute(
                f"select count(*), coalesce(sum(hash(t)::hugeint), 0) from {schema}.{name} as t"
            ).fetchone()  # type: ignore[misc]
            for name, schema in models.items()
        }
    finally:
        con.close()


def _delete_floors(data_dir: Path, models: dict[str, str]) -> dict[str, str]:
    """The key each model's last incremental run deleted from, read from dbt's run SQL."""
    floors = {}
    for name in models:
        (path,) = (data_dir / "target" / "run").rglob(f"{name}.sql")
        match = re.search(r"where \w+ >= '([^']*)';", path.read_text())
        assert match, f"{name} did not run incrementally"
        floors[name] = match.group(1)
    return floors


@pytest.fixture(scope="module")
def built_through_w39(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A warehouse built through W39, before the W40 extract arrives."""
    data_dir = tmp_path_factory.mktemp("w39")
    _link_sources(data_dir / SOURCES_DIR, through="2026-09-27")
    _ingest(data_dir, "2026-W39", datetime(2026, 9, 28, 3, 30, tzinfo=UTC))
    _dbt(data_dir)
    return data_dir


def _next_week(built: Path, tmp_path: Path) -> Path:
    """A copy of the W39 warehouse with the W40 extract loaded."""
    data_dir = tmp_path / "data"
    shutil.copytree(built, data_dir, symlinks=True)
    shutil.rmtree(data_dir / "target")
    _link_sources(data_dir / SOURCES_DIR, through="2026-10-04")
    _ingest(data_dir, "2026-W40", datetime(2026, 10, 5, 3, 30, tzinfo=UTC))
    return data_dir


def test_incremental_run_equals_full_refresh_and_a_rerun_changes_nothing(
    built_through_w39: Path, tmp_path: Path
) -> None:
    data_dir = _next_week(built_through_w39, tmp_path)
    _dbt(data_dir)
    models = _incremental_models(data_dir)
    floors = _delete_floors(data_dir, models)
    incremental = _hashes(data_dir, models)

    _dbt(data_dir)  # the same week again
    again = _hashes(data_dir, models)

    _dbt(data_dir, "--full-refresh")
    full = _hashes(data_dir, models)

    assert incremental == full
    assert again == incremental
    # Rebuilt from four weeks before W39 (the quarterly mart from that week's quarter), not
    # from the beginning: the book's weeks from W01 to W34 were kept, not recomputed.
    assert floors == {
        name: "FY26-Q4" if name == "mart_org_quarterly" else "2026-W35" for name in models
    }


def test_a_lookback_shorter_than_the_late_rows_breaks_the_match(
    built_through_w39: Path, tmp_path: Path
) -> None:
    """The W40 extract carries rows one to three weeks late. With no lookback the run
    rebuilds from W39 only, so the earlier weeks stay stale: the comparison can fail."""
    data_dir = _next_week(built_through_w39, tmp_path)
    _dbt(data_dir, "--vars", "{weekly_lookback_weeks: 0}")
    models = _incremental_models(data_dir)
    assert set(_delete_floors(data_dir, models).values()) <= {"2026-W39", "FY26-Q4"}
    short = _hashes(data_dir, models)

    _dbt(data_dir, "--full-refresh")
    full = _hashes(data_dir, models)

    assert short["mart_org_weekly"] != full["mart_org_weekly"]
    assert short["int_kpi_events"] != full["int_kpi_events"]
