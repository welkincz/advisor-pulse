"""The lead KPI's non-null ratio path (#322), on a backdated copy of the fixture warehouse.

The fixtures hold four weeks of activity, so no week has a full 12-month window and
`portfolio_contacted_rate_12m` is null everywhere. Here a scratch copy of the fixture
warehouse gets 60 extra completed calls spread back to January 2025 (the approach of
`tests/integration/test_stale_book.py` in #302): every week from 2026-W01 then has a full
window. The main project's dbt rebuilds `mart_org_weekly` in the copy, and the lab's
MetricFlow values must equal the mart, now with non-null lead-KPI rates.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

LAB_DIR = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("parity", LAB_DIR / "parity.py")
assert _spec and _spec.loader
parity = importlib.util.module_from_spec(_spec)
sys.modules["parity"] = parity
_spec.loader.exec_module(parity)

REPO_ROOT = parity.REPO_ROOT
WAREHOUSE = parity.DEFAULT_WAREHOUSE
UV = shutil.which("uv")
pytestmark = [
    pytest.mark.skipif(
        not WAREHOUSE.exists(), reason="run `make dbt-build-ci` to build the fixture warehouse"
    ),
    pytest.mark.skipif(UV is None, reason="needs `uv` to run the main project's dbt"),
]

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


def _main_dbt(data_dir: Path, *args: str) -> None:
    assert UV is not None
    command = [
        UV, "run", "--project", str(REPO_ROOT), "dbt", "--no-use-colors", *args,
        "--project-dir", "dbt", "--profiles-dir", "dbt", "--target", "dev",
        "--target-path", str(data_dir / "target"),
    ]  # fmt: skip
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["PULSE_DATA_DIR"] = str(data_dir)
    proc = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]


def test_lead_kpi_rate_matches_the_mart_with_full_windows(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    warehouse = data_dir / "warehouse.duckdb"
    shutil.copy2(WAREHOUSE, warehouse)
    with duckdb.connect(str(warehouse)) as con:
        con.execute(_BACKDATE)
    _main_dbt(data_dir, "seed")
    _main_dbt(data_dir, "run", "--select", "+mart_org_weekly")

    with duckdb.connect(str(warehouse), read_only=True) as con:
        [(rows, rates)] = con.sql(
            "select count(*), count(portfolio_contacted_rate_12m) from marts.mart_org_weekly"
        ).fetchall()
    assert rates > 100, "too few non-null lead-KPI rates to compare"

    lab = tmp_path / "lab"
    lab.mkdir()
    report = parity.compare(parity.copy_project(lab), warehouse)

    assert report.ok, report.mismatches[:10]
    assert sum(report.rows.values()) == rows
    assert report.cells == rows * len(parity.METRICS)
