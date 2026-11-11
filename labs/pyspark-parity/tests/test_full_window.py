"""Parity on a year of history, where the published rate is not null.

The fixtures hold a few weeks of activity, so no week has a full 12-month window and the
published rate is null everywhere. Here a scratch copy of the CI warehouse gets 60 extra
completed calls spread back to February 2025 (the approach of the
stale-book test in PR #364), dbt rebuilds the KPI chain on the copy, and the
Spark job must match it, including the window-complete gate, the first reported week and
the 4-dp rounding of the published rate.

Needs the CI warehouse (`make dbt-build-ci`) and the root project's venv for dbt
(`make setup`).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from pyspark.sql import SparkSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import parity

ROOT = parity.REPO_ROOT
DBT_PYTHON = ROOT / ".venv" / "bin" / "python"

pytestmark = [
    pytest.mark.skipif(not parity.WAREHOUSE.exists(), reason="run `make dbt-build-ci` first"),
    pytest.mark.skipif(not DBT_PYTHON.exists(), reason="run `make setup` for the root dbt venv"),
]

# One completed outbound call per client, copied and moved back in time, 9 days apart from
# 2025-02-01: the window is first complete in 2026-W05, so the book weeks 2026-W01 to W04
# exist but are not reported.
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
    timestamptz '2025-02-01 15:00:00+00' + to_days(cast(9 * (n - 1) as integer)) as ACTIVITY_TS,
    timestamptz '2025-02-01 14:00:00+00' + to_days(cast(9 * (n - 1) as integer)) as CREATED_TS,
    timestamptz '2025-02-01 15:00:00+00' + to_days(cast(9 * (n - 1) as integer)) as UPDATED_TS,
    md5('backdated' || n) as _row_hash
)
from picked
where n <= 60
"""


@pytest.fixture(scope="module")
def year_of_history(tmp_path_factory: pytest.TempPathFactory) -> Path:
    data_dir = tmp_path_factory.mktemp("full-window")
    warehouse = data_dir / "warehouse.duckdb"
    shutil.copyfile(parity.WAREHOUSE, warehouse)
    with duckdb.connect(str(warehouse)) as con:
        con.execute(_BACKDATE)
    command = [
        str(DBT_PYTHON), "-m", "dbt.cli.main", "--no-use-colors", "run",
        "--select", "+mart_org_weekly",
        "--project-dir", "dbt", "--profiles-dir", "dbt", "--target", "dev",
        "--target-path", str(data_dir / "target"),
    ]  # fmt: skip
    env = {**os.environ, "PULSE_DATA_DIR": str(data_dir)}
    proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout[-3000:]
    return warehouse


@pytest.fixture(scope="module")
def spark() -> Iterator[SparkSession]:
    session = parity.spark_session(cores=2)
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


def test_parity_holds_with_published_rates(
    year_of_history: Path, spark: SparkSession, tmp_path: Path
) -> None:
    parity.export_inputs(year_of_history, tmp_path)
    result = parity.compare(*parity.run(parity.read_inputs(spark, tmp_path)), year_of_history)
    assert result.mismatches == []
    assert result.client_weeks and result.branch_weeks
    with duckdb.connect(str(year_of_history), read_only=True) as con:
        first_reported = con.execute(
            "select min(iso_week_id) from marts.mart_org_weekly where level = 'BRANCH'"
        ).fetchone()[0]  # type: ignore[index]
        published, unrounded = con.execute(
            "select count(portfolio_contacted_rate_12m),"
            " count(*) filter (where portfolio_contacted_rate_12m"
            "   <> portfolio_contacted_12m / portfolio_clients)"
            " from marts.mart_org_weekly where level = 'BRANCH'"
        ).fetchone()  # type: ignore[misc]
    # The gate opened for many branch-weeks, and rounding changed some of them.
    assert result.published_rates == published >= 50
    assert unrounded > 0
    # Book weeks before the first full window exist but are not reported.
    assert first_reported == "2026-W05"
