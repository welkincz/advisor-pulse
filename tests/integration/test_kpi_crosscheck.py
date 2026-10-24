"""The lead KPI agrees with an independent implementation on the fixtures (#303).

`scripts/crosscheck_kpi.py` recomputes PRTF_CONTACT_12M from the raw extracts without any
code from dbt/ or the ingest package. Here the fixtures go through the real ingest and dbt
into a scratch warehouse, and the two must agree on every portfolio, advisor and org node in
every week. A second test breaks one rule in the independent copy and expects the
comparison to fail and name the first differing node, so a pass means something.
"""

from __future__ import annotations

import importlib.util
import os
import random
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType

import duckdb
import pytest

from pulse.contracts.enums import RunType, StageStatus
from pulse.ingest.stage import SOURCES_DIR, ingest
from pulse.runner.stage import StageContext

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "fixtures" / "sources"
DBT_DIR = ROOT / "dbt"
MARTS = ("+mart_org_weekly", "+mart_advisor_weekly", "+mart_portfolio_weekly")
pytestmark = pytest.mark.integration


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "crosscheck_kpi", ROOT / "scripts" / "crosscheck_kpi.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


crosscheck = _load_script()


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 5, 3, 30, tzinfo=UTC)

    def sleep(self, seconds: float) -> None:
        pass


def _dbt(data_dir: Path, *args: str) -> None:
    command = [
        sys.executable,
        "-m",
        "dbt.cli.main",
        "--no-use-colors",
        *args,
        "--project-dir",
        str(DBT_DIR),
        "--profiles-dir",
        str(DBT_DIR),
        "--target",
        "dev",
        "--target-path",
        str(data_dir / "target"),
    ]
    env = {**os.environ, "PULSE_DATA_DIR": str(data_dir)}
    proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout[-3000:]


@pytest.fixture(scope="module")
def fixture_run(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Fixtures ingested and the three marts built, in a scratch data dir."""
    data_dir = tmp_path_factory.mktemp("crosscheck")
    (data_dir / SOURCES_DIR).symlink_to(FIXTURES, target_is_directory=True)
    result = ingest(StageContext("test-crosscheck", RunType.MANUAL, "2026-W40", data_dir, _Clock()))
    assert result.status is not StageStatus.FAILED, result.message
    _dbt(data_dir, "seed")
    _dbt(data_dir, "run", "--select", *MARTS)
    yield data_dir


def test_independent_kpi_matches_the_marts_on_every_node_and_week(fixture_run: Path) -> None:
    ok, lines = crosscheck.run(fixture_run)
    report = "\n".join(lines)
    assert ok, report
    assert "Reported weeks: 4 (2026-W37 to 2026-W40)" in report
    # Every DQ001–DQ004 activity defect and both DQ005 client rows in defects.json.
    assert "8 quarantined" in report
    assert "Clients: 2 CLNT rows quarantined" in report


def test_a_broken_rule_is_caught_and_the_first_difference_is_named(
    fixture_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Count no-shows as contacts: completed-only (R4) is broken.
    monkeypatch.setattr(crosscheck, "CONTACT_STATUSES", frozenset({"COMPLETED", "NO_SHOW"}))
    ok, lines = crosscheck.run(fixture_run)
    report = "\n".join(lines)
    assert not ok, report
    first = next(line for line in lines if line.startswith("MISMATCH mart_org_weekly"))
    assert "NATIONAL CA: independent" in first
    assert "contacted/clients" in first and ", mart " in first
    assert report.endswith("FAIL")


def test_rates_are_compared_after_the_marts_rounding() -> None:
    """The marts store round(contacted / clients, 4); the fixtures never have a complete
    window, so the rounding the comparison mimics is pinned against DuckDB here."""
    rng = random.Random(303)
    pairs = [(rng.randint(0, n), n) for n in (rng.randint(1, 400_000) for _ in range(2000))]
    pairs += [(1, 8), (5, 16), (12345, 20000), (24689, 200000), (0, 1), (7, 7)]
    con = duckdb.connect()
    rounded = con.execute(
        "select round(c / n, 4) from (select unnest(?::bigint[]) as c, unnest(?::bigint[]) as n)",
        [[c for c, _ in pairs], [n for _, n in pairs]],
    ).fetchall()
    for (contacted, clients), (want,) in zip(pairs, rounded, strict=True):
        assert crosscheck.mart_round(contacted / clients) == want, (contacted, clients)


def test_twelve_months_back_clamps_to_the_end_of_february() -> None:
    assert crosscheck.months_back(date(2028, 2, 29), 12) == date(2027, 2, 28)
    assert crosscheck.months_back(date(2026, 10, 4), 12) == date(2025, 10, 4)
    assert crosscheck.months_back(date(2025, 3, 31), 1) == date(2025, 2, 28)
