"""Weekly activity generation follows assignment history and the source contract."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from statistics import median

import pyarrow.parquet as pq
import pytest

from pulse.contracts import arrow_schema
from pulse.contracts.enums import ActivityStatus, ActivityType, Role
from pulse.contracts.sources import SnowflakeActivity
from pulse.generate.activity import generate_activity, write_activity
from pulse.generate.advisors import assignment_ranges, generate_advisors
from pulse.generate.books import client_pools_by_day
from pulse.generate.clients import ClientBatch, generate_clients
from pulse.reference import org


def _roster(count: int = 80):
    return generate_advisors(org(), seed=29, advisor_count=count, weeks=104)


@lru_cache
def _clients(count: int) -> ClientBatch:
    return generate_clients(
        org(),
        assignment_ranges(_roster(count)),
        seed=29,
        client_count=10_000 if count == 900 else 5_000,
        weeks=104,
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
    assert owned / len(linked) >= 0.9


@pytest.mark.slow
def test_default_scale_thirteen_week_book_coverage() -> None:
    ranges = assignment_ranges(_roster(900))
    batch = generate_clients(org(), ranges, seed=29, client_count=150_000, weeks=13)
    contacted: dict[str, set[str]] = defaultdict(set)
    linked = owned = 0
    for offset in range(13):
        monday = date(2024, 10, 7) + timedelta(weeks=offset)
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
    end_books, _ = client_pools_by_day(batch, [date(2025, 1, 5)])[date(2025, 1, 5)]
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
        assert 12_000 <= len(week_rows(week)) <= 18_000
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
