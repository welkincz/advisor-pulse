"""The stale-book indicator in mart_org_weekly matches the analysis that chose it (#302).

The fixtures hold four weeks of activity, so no week has a 12-month window and the measure
is null throughout. Here a scratch copy of the fixture warehouse gets 60 extra completed calls
spread back to January 2025: every week from 2026-W01 then has a full window, and the books
have a mix of recent and stale contacts. dbt rebuilds the mart, and every branch-week the
analysis script scores must carry the same share and 13-week rise.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import duckdb
import pytest

from pulse.contracts.enums import RunType, StageStatus
from pulse.ingest.stage import SOURCES_DIR, ingest
from pulse.runner.stage import StageContext
from pulse.warehouse import WAREHOUSE_FILE

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "fixtures" / "sources"
DBT_DIR = ROOT / "dbt"
pytestmark = pytest.mark.integration

# One completed outbound call per client, copied from the fixtures and moved back in time,
# 9 days apart from 2025-01-01: the first one completes the 12-month window for 2026-W01.
_BACKDATE = """
insert into raw.snowflake__activity
with calls as (
    select *
    from raw.snowflake__activity
    where STATUS = 'COMPLETED' and ACTIVITY_TYPE = 'CALL_OUT' and CLIENT_ID is not null
    qualify row_number() over (partition by CLIENT_ID order by ACTIVITY_ID) = 1
),
picked as (
    select *, row_number() over (order by CLIENT_ID) as n from calls
)
select * exclude (n) replace (
    'ACT-' || lpad(printf('%x', 4096 + n), 12, '0') as ACTIVITY_ID,
    timestamptz '2025-01-01 15:00:00+00' + to_days(cast(9 * (n - 1) as integer)) as ACTIVITY_TS,
    timestamptz '2025-01-01 14:00:00+00' + to_days(cast(9 * (n - 1) as integer)) as CREATED_TS,
    timestamptz '2025-01-01 15:00:00+00' + to_days(cast(9 * (n - 1) as integer)) as UPDATED_TS,
    md5('backdated' || n) as _row_hash
)
from picked
where n <= 60
"""


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "leading_indicator_mart", ROOT / "scripts" / "leading_indicator.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


li = _load_script()


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 5, 3, 30, tzinfo=UTC)

    def sleep(self, seconds: float) -> None:
        pass


def _dbt(data_dir: Path, *args: str) -> None:
    command = [
        sys.executable, "-m", "dbt.cli.main", "--no-use-colors", *args,
        "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR), "--target", "dev",
        "--target-path", str(data_dir / "target"),
    ]  # fmt: skip
    env = {**os.environ, "PULSE_DATA_DIR": str(data_dir)}
    proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout[-3000:]


@pytest.fixture(scope="module")
def year_of_history(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    data_dir = tmp_path_factory.mktemp("stale-book")
    (data_dir / SOURCES_DIR).symlink_to(FIXTURES, target_is_directory=True)
    result = ingest(StageContext("test-stale-book", RunType.MANUAL, "2026-W40", data_dir, _Clock()))
    assert result.status is not StageStatus.FAILED, result.message
    with duckdb.connect(str(data_dir / WAREHOUSE_FILE)) as con:
        con.execute(_BACKDATE)
    _dbt(data_dir, "seed")
    _dbt(data_dir, "run", "--select", "+mart_org_weekly")
    yield data_dir


def test_mart_matches_the_analysis_on_every_scored_branch_week(year_of_history: Path) -> None:
    with duckdb.connect(str(year_of_history / WAREHOUSE_FILE), read_only=True) as con:
        cursor = con.execute(li._PANEL)
        names = [d[0] for d in cursor.description]
        panel = [dict(zip(names, raw, strict=True)) for raw in cursor.fetchall()]
        mart = {
            (branch, week): (share, rise)
            for branch, week, share, rise in con.execute(
                "select node_id, iso_week_id, stale_9m_share, stale_9m_rise_13w"
                " from marts.mart_org_weekly where level = 'BRANCH'"
            ).fetchall()
        }
    assert len(panel) >= 50, "too few scored branch-weeks to compare"
    shares = {round(r["stale_9m"], 4) for r in panel}
    rises = [r["stale_9m_rise_13w"] for r in panel]
    assert len(shares) > 10 and any(rises) and min(rises) < max(rises), "no variation to test"
    for r in panel:
        share, rise = mart[(r["branch_id"], r["iso_week_id"])]
        key = (r["branch_id"], r["iso_week_id"])
        assert share == pytest.approx(r["stale_9m"], abs=5e-5 + 1e-9), key
        assert rise == pytest.approx(r["stale_9m_rise_13w"], abs=5e-5 + 1e-9), key


def test_the_measure_is_branch_only_and_needs_an_earlier_week(year_of_history: Path) -> None:
    with duckdb.connect(str(year_of_history / WAREHOUSE_FILE), read_only=True) as con:
        rows = con.execute(
            "select level, iso_week_id, stale_9m_share, stale_9m_rise_13w,"
            " portfolio_contacted_rate_12m from marts.mart_org_weekly"
        ).fetchall()
    branch = [r for r in rows if r[0] == "BRANCH"]
    assert all(r[2] is None and r[3] is None for r in rows if r[0] != "BRANCH")
    assert all((r[2] is None) == (r[4] is None) for r in branch)
    first = min(r[1] for r in branch if r[2] is not None)
    assert first == "2026-W01"
    # The rise needs the week 13 reported weeks earlier: none before 2026-W14.
    assert all(r[3] is None for r in branch if r[1] < "2026-W14")
    assert any(r[3] is not None for r in branch if r[1] == "2026-W14")
