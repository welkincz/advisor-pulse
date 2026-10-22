"""Weekly generation: one week at a time equals a backfill, and old files stay as written."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner

import pulse.generate.cli as gen
from pulse.cli import app
from pulse.contracts.defects import DefectKind, DefectManifest
from pulse.generate.cli import (
    Sizes,
    build_world,
    generate_weeks,
    horizon_weeks,
    roster_as_of,
    week_range,
)

SEED = 7
SIZES = Sizes(advisors=120, clients=4000)
# 2026-W08..W15 crosses a horizon step (78 → 91 weeks from 2024-W41).
WEEKS = week_range("2026-W08", "2026-W15")


def quiet(_: str) -> None:
    pass


def hashes(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def backfill(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("backfill")
    assert generate_weeks(root, WEEKS, seed=SEED, sizes=SIZES, echo=quiet) == len(WEEKS)
    return root


def test_weeks_one_at_a_time_are_byte_identical_to_a_backfill(
    backfill: Path, tmp_path: Path
) -> None:
    assert horizon_weeks(WEEKS[0]) != horizon_weeks(WEEKS[-1])
    for week in WEEKS:
        generate_weeks(tmp_path, [week], seed=SEED, sizes=SIZES, echo=quiet)
    one, bulk = hashes(tmp_path), hashes(backfill)
    assert one == bulk
    assert sum(name.startswith("sources/snowflake/activity/") for name in one) >= len(WEEKS)


def test_a_new_week_adds_files_and_rewrites_none(tmp_path: Path) -> None:
    generate_weeks(tmp_path, WEEKS[:3], seed=SEED, sizes=SIZES, echo=quiet)
    before = hashes(tmp_path)
    generate_weeks(tmp_path, [WEEKS[3]], seed=SEED, sizes=SIZES, echo=quiet)
    after = hashes(tmp_path)

    # The EDW database and the merged manifest are state, not extracts.
    state = {"sources/teradata/edw.sqlite", "defects.json"}
    assert {k: v for k, v in after.items() if k in before and k not in state} == {
        k: v for k, v in before.items() if k not in state
    }
    sunday = date.fromisocalendar(2026, 11, 7)
    days = {f"{sunday - timedelta(days=i):%Y%m%d}" for i in range(7)}
    for name in set(after) - set(before):
        assert (
            name.startswith(f"sources/snowflake/activity/extract_date={sunday}/")
            or name == f"defects/{WEEKS[3]}.json"
            or (name.startswith("sources/teradata/client_") and name[-12:-4] in days)
        ), name

    assert generate_weeks(tmp_path, [WEEKS[3]], seed=SEED, sizes=SIZES, echo=quiet) == 0
    assert hashes(tmp_path) == after


def test_late_arrivals_are_three_to_five_percent_of_rows(backfill: Path) -> None:
    rows = sum(
        pq.read_metadata(p).num_rows
        for p in (backfill / "sources/snowflake/activity").rglob("*.parquet")
    )
    manifest = DefectManifest.model_validate_json((backfill / "defects.json").read_text())
    late = sum(d.kind is DefectKind.LATE_ARRIVING for d in manifest.defects)
    assert manifest.iso_weeks == WEEKS
    assert 0.03 <= late / rows <= 0.05


def test_the_client_snapshot_comes_from_the_first_week_only(backfill: Path) -> None:
    first_monday = date.fromisocalendar(2026, 8, 1)
    with sqlite3.connect(backfill / "sources/teradata/edw.sqlite") as con:
        newest = con.execute('SELECT max("LAST_UPD_TS") FROM "CLNT"').fetchone()[0]
        assignments = con.execute('SELECT max("EFF_DT") FROM "ADVSR_ASGN"').fetchone()[0]
        portfolios = con.execute('SELECT count(*) FROM "PRTF"').fetchone()[0]
        portfolio_events = con.execute('SELECT count(*) FROM "PRTF_ASGN"').fetchone()[0]
        assert con.execute('SELECT count(*) FROM "CLNT" WHERE PRTF_ID IS NULL').fetchone() == (0,)
    assert newest < first_monday.isoformat()
    assert assignments <= date.fromisocalendar(2026, 15, 7).isoformat()
    assert portfolios > 0 and portfolio_events >= portfolios
    deltas = sorted((backfill / "sources/teradata").glob("client_*.csv"))
    assert deltas and all(p.name[7:15] >= f"{first_monday:%Y%m%d}" for p in deltas)


def test_a_longer_horizon_keeps_every_earlier_day_unchanged() -> None:
    short = build_world(SEED, SIZES, "2026-W08")
    long = build_world(SEED, SIZES, "2026-W30")
    end = date.fromisocalendar(2026, 8, 7)
    assert short.clients.snapshot == long.clients.snapshot
    assert [c for c in short.clients.changes if c.day <= end] == [
        c for c in long.clients.changes if c.day <= end
    ]
    assert roster_as_of(short.roster, end) == roster_as_of(long.roster, end)


def test_roster_as_of_hides_later_hr_events() -> None:
    roster = build_world(SEED, SIZES, "2026-W40").roster
    assert roster_as_of(roster, date(2099, 1, 1)) == roster
    as_of = date(2025, 6, 30)
    early = roster_as_of(roster, as_of)
    assert all(a.effective_date <= as_of for a in early.assignments)
    assert all(a.term_date is None or a.term_date <= as_of for a in early.advisors)
    assert all(a.last_updated_ts.date() <= as_of for a in early.advisors)
    assert len(early.advisors) < len(roster.advisors)


@pytest.mark.parametrize(
    "args",
    [
        ["generate", "--backfill", "--from", "2026-W10"],
        ["generate", "--from", "2026-W10", "--to", "2026-W11"],
        ["generate", "--backfill", "--from", "2026-W11", "--to", "2026-W10"],
        ["generate", "--week", "2024-W30"],
        ["generate", "--week", "2026-40"],
    ],
)
def test_cli_rejects_bad_ranges(
    args: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(app, args)
    assert result.exit_code != 0
    assert not any(tmp_path.iterdir())


def test_cli_backfill_writes_each_week(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PULSE_SEED", str(SEED))
    small: Callable[[], Sizes] = lambda: SIZES  # noqa: E731
    monkeypatch.setattr(gen, "Sizes", small)
    args = ["generate", "--backfill", "--from", "2026-W08", "--to", "2026-W09"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "2026-W08: generated" in result.output
    assert json.loads((tmp_path / "defects.json").read_text())["iso_weeks"] == WEEKS[:2]
    again = CliRunner().invoke(app, args)
    assert "2026-W09: already generated" in again.output


def test_the_first_weeks_have_no_activity_before_the_history_start(tmp_path: Path) -> None:
    from zoneinfo import ZoneInfo

    from pulse.generate.advisors import DEFAULT_START

    first = DEFAULT_START.isocalendar()
    weeks = week_range(f"{first.year}-W{first.week:02d}", f"{first.year}-W{first.week + 1:02d}")
    generate_weeks(tmp_path, weeks, seed=SEED, sizes=SIZES, echo=quiet)
    toronto = ZoneInfo("America/Toronto")
    earliest = min(
        ts.astimezone(toronto).date()
        for p in (tmp_path / "sources/snowflake/activity").rglob("*.parquet")
        for ts in pq.read_table(p, columns=["ACTIVITY_TS"]).column("ACTIVITY_TS").to_pylist()
        if ts is not None
    )
    assert earliest >= DEFAULT_START
