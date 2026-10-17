"""fct_activity built incrementally week by week equals a full refresh (issue #26).

Loads the fixture extracts through W39, builds the fact, then loads the W40 extract (which
carries rows one to three weeks late) and runs the fact incrementally. The table must match a
full refresh exactly, and the late rows must sit in their original weeks.
"""

from __future__ import annotations

import os
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
LATE_IN_W40 = {
    "ACT-ec6171ef0cc0": "2026-W37",
    "ACT-f0fd2f1ddb01": "2026-W38",
    "ACT-605d22cf2d69": "2026-W38",
    "ACT-0bdaf000d60d": "2026-W39",
    "ACT-14ad2f7878c5": "2026-W39",
}
pytestmark = pytest.mark.integration


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
        "run",
        "--project-dir",
        str(DBT_DIR),
        "--profiles-dir",
        str(DBT_DIR),
        "--target",
        "dev",
        "--target-path",
        str(data_dir / "target"),
        *args,
    ]
    env = {**os.environ, "PULSE_DATA_DIR": str(data_dir)}
    proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout[-3000:]


def _fact(data_dir: Path) -> tuple[int, str, dict[str, str]]:
    con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
    try:
        count, digest = con.execute(
            "select count(*), md5(string_agg(f::varchar, '|' order by activity_id))"
            " from marts.fct_activity as f"
        ).fetchone()  # type: ignore[misc]
        weeks = dict(
            con.execute(
                "select activity_id, iso_week_id from marts.fct_activity"
                " where activity_id = any(?)",
                [list(LATE_IN_W40)],
            ).fetchall()
        )
    finally:
        con.close()
    return count, digest, weeks


def test_incremental_build_equals_full_refresh_and_keeps_late_rows_in_their_week(
    tmp_path: Path,
) -> None:
    sources = tmp_path / SOURCES_DIR
    _link_sources(sources, through="2026-09-27")
    _ingest(tmp_path, "2026-W39", datetime(2026, 9, 28, 3, 30, tzinfo=UTC))
    _dbt(tmp_path, "--select", "+fct_activity")
    before, _, weeks = _fact(tmp_path)
    assert weeks == {}  # the W40 extract is not loaded yet

    _link_sources(sources, through="2026-10-04")
    _ingest(tmp_path, "2026-W40", datetime(2026, 10, 5, 3, 30, tzinfo=UTC))
    _dbt(tmp_path, "--select", "+fct_activity")  # fct_activity runs incrementally
    incremental = _fact(tmp_path)

    _dbt(tmp_path, "--select", "fct_activity", "--full-refresh")
    full = _fact(tmp_path)

    assert incremental[0] > before
    assert incremental == full
    assert incremental[2] == LATE_IN_W40
