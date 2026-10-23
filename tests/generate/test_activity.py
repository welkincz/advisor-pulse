"""Weekly activity generation follows assignment history and the source contract."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from statistics import median

import pyarrow.parquet as pq
import pytest

from pulse.contracts import arrow_schema
from pulse.contracts.enums import ActivityStatus, ActivityType, ClientStatus, Role
from pulse.contracts.sources import SnowflakeActivity
from pulse.generate.activity import generate_activity, write_activity
from pulse.generate.advisors import (
    DEFAULT_START,
    REPORT_START,
    assignment_ranges,
    generate_advisors,
)
from pulse.generate.books import client_pools_by_day
from pulse.generate.cli import DEFAULT_SEED, Sizes, build_world
from pulse.generate.clients import ClientBatch, generate_clients
from pulse.reference import org


def _roster(count: int = 80):
    # The world starts in the warm-up year (DEFAULT_START), so 160 weeks reach 2026-W43.
    return generate_advisors(org(), seed=29, advisor_count=count, weeks=160)


@lru_cache
def _clients(count: int) -> ClientBatch:
    return generate_clients(
        org(),
        assignment_ranges(_roster(count)),
        seed=29,
        client_count=10_000 if count == 900 else 5_000,
        weeks=160,
    )


def test_activity_uses_advisor_branch_as_of_each_date() -> None:
    ranges = assignment_ranges(_roster())
    rows = generate_activity(
        org(), ranges, iso_week_id="2026-W37", seed=17, client_batch=_clients(80)
    )
    for row in rows:
        day = row.activity_ts.date()
        assert any(
            advisor == row.advisor_id
            and branch == row.branch_id
            and role != Role.BRANCH_MANAGER
            and start <= day
            and (end is None or day < end)
            for advisor, branch, role, start, end in ranges
        )
    batch = _clients(80)
    linked = [row for row in rows if row.client_id is not None]
    pools = client_pools_by_day(batch, [row.activity_ts.date() for row in linked])
    owned = 0
    for row in linked:
        books, active = pools[row.activity_ts.date()]
        assert row.client_id in active
        owned += row.client_id in books.get(row.advisor_id, ())
    # A transfer or a hire opens a portfolio that its branch fills: nobody is left bookless.
    assert owned / len(linked) >= 0.9


@pytest.mark.slow
def test_default_scale_thirteen_week_book_coverage() -> None:
    ranges = assignment_ranges(_roster(900))
    batch = generate_clients(org(), ranges, seed=29, client_count=150_000, weeks=13)
    contacted: dict[str, set[str]] = defaultdict(set)
    linked = owned = 0
    for offset in range(13):
        monday = DEFAULT_START + timedelta(weeks=offset)
        week = f"{monday.isocalendar().year}-W{monday.isocalendar().week:02d}"
        rows = generate_activity(org(), ranges, iso_week_id=week, seed=31, client_batch=batch)
        pools = client_pools_by_day(batch, [row.activity_ts.date() for row in rows])
        for row in rows:
            if row.client_id is None:
                continue
            linked += 1
            books, _ = pools[row.activity_ts.date()]
            if row.client_id in books.get(row.advisor_id, ()):
                owned += 1
                contacted[row.advisor_id].add(row.client_id)
    assert owned / linked >= 0.9
    end = DEFAULT_START + timedelta(weeks=13, days=-1)
    end_books, _ = client_pools_by_day(batch, [end])[end]
    coverage = [
        len(contacted[owner].intersection(ids)) / len(ids) for owner, ids in end_books.items()
    ]
    assert 0.30 <= median(coverage) <= 0.80


def test_appointments_follow_calls_and_have_valid_status_timing() -> None:
    rows = generate_activity(
        org(),
        assignment_ranges(_roster()),
        iso_week_id="2026-W37",
        seed=17,
        client_batch=_clients(80),
    )
    by_id = {row.activity_id: row for row in rows}
    appointments = [r for r in rows if r.activity_type == ActivityType.APPOINTMENT]
    assert appointments
    for row in rows:
        if row.activity_type in {ActivityType.REVIEW, ActivityType.APPOINTMENT}:
            assert row.client_id is not None
        if row.status == ActivityStatus.NO_SHOW:
            assert row.activity_type == ActivityType.APPOINTMENT
        if row.status == ActivityStatus.COMPLETED and row.scheduled_ts is not None:
            assert row.activity_ts >= row.scheduled_ts
    for appointment in appointments:
        call = by_id[appointment.booked_from_activity_id]
        assert call.activity_type == ActivityType.CALL_OUT
        assert call.created_ts <= appointment.created_ts < appointment.scheduled_ts


@pytest.mark.slow
def test_default_volume_and_district_stories() -> None:
    ranges = assignment_ranges(_roster(900))
    districts = {p.branch.branch_id: p.district.district_code for p in org().placements()}
    totals: list[Counter[str]] = []
    for monday in (date(2026, 8, 10) + timedelta(weeks=i) for i in range(8)):
        week = f"{monday.isocalendar().year}-W{monday.isocalendar().week:02d}"
        rows = generate_activity(
            org(),
            ranges,
            iso_week_id=week,
            seed=31,
            story_districts=("GTA", "MTL"),
            client_batch=_clients(900),
        )
        assert 12_000 <= len(rows) <= 18_000
        totals.append(Counter(districts[r.branch_id] for r in rows))
    assert totals[-1]["GTA"] < totals[0]["GTA"] * 0.85
    assert totals[-1]["MTL"] > totals[0]["MTL"] * 1.15


@pytest.mark.slow
def test_holiday_dip_and_february_lift() -> None:
    ranges = assignment_ranges(_roster(900))

    def week_rows(week: str):
        return generate_activity(
            org(), ranges, iso_week_id=week, seed=31, client_batch=_clients(900)
        )

    for week in ("2024-W52", "2025-W52"):
        # Christmas weeks run lighter than a normal ~15k; 2024-W52 lands near 12k.
        assert 11_500 <= len(week_rows(week)) <= 18_000
    holiday_week = week_rows("2026-W27")
    by_day = Counter(row.activity_ts.date() for row in holiday_week)
    assert by_day[date(2026, 7, 1)] < by_day[date(2026, 7, 2)] * 0.75

    assert len(week_rows("2026-W07")) > len(week_rows("2026-W03")) * 1.04


def test_seed_week_determinism_and_parquet_schema(tmp_path: Path) -> None:
    ranges = assignment_ranges(_roster(50))

    def generated(week: str):
        return generate_activity(org(), ranges, iso_week_id=week, seed=7, client_batch=_clients(50))

    for invalid in ("2026-W1", "2026-W001"):
        with pytest.raises(ValueError, match="Invalid ISO week"):
            generated(invalid)

    first = generated("2026-W37")
    assert first == generated("2026-W37")
    assert first != generated("2026-W38")
    path = write_activity(first, tmp_path, extract_date=date(2026, 9, 14))[0]
    bytes_once = path.read_bytes()
    assert (
        write_activity(first, tmp_path, extract_date=date(2026, 9, 14))[0].read_bytes()
        == bytes_once
    )
    table = pq.read_table(path)
    assert table.schema == arrow_schema(SnowflakeActivity)
    assert [SnowflakeActivity.model_validate(row) for row in table.to_pylist()] == list(first)
    assert (
        len(write_activity(first[:2], tmp_path, extract_date=date(2026, 9, 14), part_size=1)) == 2
    )
    latest = write_activity(first[:1], tmp_path, extract_date=date(2026, 9, 14))
    assert len(latest) == 1
    assert sorted(latest[0].parent.glob("part-*.parquet")) == list(latest)


@pytest.mark.slow
def test_default_scale_twelve_month_portfolio_contacted_spreads() -> None:
    # #230, #288: shortly after the first reported week, the national rate starts
    # near 83% and still spreads widely across advisor books.
    weeks = 57
    roster = generate_advisors(org(), seed=7, advisor_count=900, weeks=weeks)
    ranges = assignment_ranges(roster)
    batch = generate_clients(org(), ranges, seed=7, client_count=150_000, weeks=weeks)
    last: dict[str, date] = {}
    start = DEFAULT_START
    for offset in range(weeks):
        monday = start + timedelta(weeks=offset)
        week = f"{monday.isocalendar().year}-W{monday.isocalendar().week:02d}"
        for row in generate_activity(org(), ranges, iso_week_id=week, seed=7, client_batch=batch):
            if row.client_id and row.status is ActivityStatus.COMPLETED:
                day = row.activity_ts.date()
                last[row.client_id] = max(day, last.get(row.client_id, day))
    sunday = start + timedelta(weeks=weeks - 1, days=6)
    books, _ = client_pools_by_day(batch, [sunday])[sunday]
    cutoff = sunday.replace(year=sunday.year - 1)
    hit = {a: sum(last.get(c, cutoff) > cutoff for c in ids) for a, ids in books.items()}
    national = sum(hit.values()) / sum(len(ids) for ids in books.values())
    rates = sorted(hit[a] / len(ids) for a, ids in books.items() if len(ids) >= 20)
    assert 0.81 <= national <= 0.84
    assert rates[len(rates) // 20] < 0.75  # the bottom 5% is clearly behind
    assert rates[-len(rates) // 20] > 0.95  # and the top 5% reaches almost everyone


@pytest.mark.slow
def test_default_seed_contacted_rate_rises_smoothly_with_local_slips() -> None:
    """Model the mart's any-advisor, completed-contact, rolling-year definition."""
    end = date.fromisocalendar(2027, 52, 1)
    weeks = (end - DEFAULT_START).days // 7 + 1
    reference = org()
    world = build_world(DEFAULT_SEED, Sizes(), "2027-W52")
    ranges = assignment_ranges(world.roster)
    state = {client.client_id: client for client in world.clients.snapshot}
    changes = sorted(world.clients.changes, key=lambda change: change.day)
    cursor = 0
    last_contact: dict[str, date] = {}
    rates: dict[str, float] = {}
    details: dict[str, tuple[dict[str, float], dict[str, float]]] = {}
    placements = {p.branch.branch_id: p.region.region_code for p in reference.placements()}
    endpoints = {"2024-W41", "2027-W52"}

    for offset in range(weeks):
        monday = DEFAULT_START + timedelta(weeks=offset)
        sunday = monday + timedelta(days=6)
        week = f"{monday.isocalendar().year}-W{monday.isocalendar().week:02d}"
        for row in generate_activity(
            reference, ranges, iso_week_id=week, seed=DEFAULT_SEED, client_batch=world.clients
        ):
            if row.client_id and row.status is ActivityStatus.COMPLETED:
                day = row.activity_ts.date()
                last_contact[row.client_id] = max(day, last_contact.get(row.client_id, day))
        while cursor < len(changes) and changes[cursor].day <= sunday:
            client = changes[cursor].after
            state[client.client_id] = client
            cursor += 1
        if monday < REPORT_START:
            continue
        cutoff = sunday.replace(year=sunday.year - 1)
        active = [
            client
            for client in state.values()
            if client.status_code is ClientStatus.ACTIVE and client.client_since_date <= sunday
        ]
        contacted = {
            c.client_id for c in active if last_contact.get(c.client_id, date.min) > cutoff
        }
        rates[week] = len(contacted) / len(active)
        if week in endpoints:
            by_region: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            by_branch: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            transit = {p.portfolio_id: p.branch_id for p in world.portfolios.master}
            for client in active:
                branch = transit[client.portfolio_id]
                hit = int(client.client_id in contacted)
                by_branch[branch][0] += hit
                by_branch[branch][1] += 1
                region = placements[branch]
                by_region[region][0] += hit
                by_region[region][1] += 1
            details[week] = (
                {code: hit / total for code, (hit, total) in by_region.items()},
                {code: hit / total for code, (hit, total) in by_branch.items()},
            )

    values = list(rates.values())
    assert 0.81 <= rates["2024-W41"] <= 0.84
    assert 0.855 <= rates["2026-W42"] <= 0.875
    assert all(0.80 <= value <= 0.90 for value in values)
    assert max(abs(right - left) for left, right in pairwise(values)) <= 0.0015
    assert rates["2027-W52"] <= 0.88
    early_gain = (rates["2026-W42"] - rates["2024-W41"]) / 105
    late_gain = (rates["2027-W52"] - rates["2026-W42"]) / 63
    assert 0 <= late_gain < early_gain
    first_regions, first_branches = details["2024-W41"]
    last_regions, last_branches = details["2027-W52"]
    assert any(last_regions[key] < value for key, value in first_regions.items())
    assert (
        sum(last_regions[key] > value for key, value in first_regions.items())
        > len(first_regions) // 2
    )
    assert max(last_regions.values()) - min(last_regions.values()) >= 0.03
    assert sum(last_branches[key] < value for key, value in first_branches.items()) >= 3
    branch_rates = sorted(last_branches.values())
    assert 0.72 <= branch_rates[len(branch_rates) // 20] <= 0.80
    assert 0.90 <= branch_rates[-len(branch_rates) // 20] <= 0.96
