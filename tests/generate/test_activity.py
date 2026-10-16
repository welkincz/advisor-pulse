"""Weekly activity generation follows assignment history and the source contract."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from pulse.contracts import arrow_schema
from pulse.contracts.enums import ActivityStatus, ActivityType, Role
from pulse.contracts.sources import SnowflakeActivity
from pulse.generate.activity import generate_activity, write_activity
from pulse.generate.advisors import assignment_ranges, generate_advisors
from pulse.reference import org

CLIENT_IDS = tuple(f"CLI-{number:08d}" for number in range(1, 201))


def _roster(count: int = 80):
    return generate_advisors(org(), seed=29, advisor_count=count, weeks=104)


def test_activity_uses_advisor_branch_as_of_each_date() -> None:
    ranges = assignment_ranges(_roster())
    week = "2026-W37"
    rows = generate_activity(org(), ranges, iso_week_id=week, seed=17, client_ids=CLIENT_IDS)
    assert rows
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


def test_appointments_follow_calls_and_have_valid_status_timing() -> None:
    rows = generate_activity(
        org(),
        assignment_ranges(_roster()),
        iso_week_id="2026-W37",
        seed=17,
        client_ids=CLIENT_IDS,
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
        assert appointment.booked_from_activity_id in by_id
        call = by_id[appointment.booked_from_activity_id]
        assert call.activity_type == ActivityType.CALL_OUT
        assert call.created_ts <= appointment.created_ts < appointment.scheduled_ts


def test_default_volume_and_district_stories() -> None:
    ranges = assignment_ranges(_roster(900))
    districts = {p.branch.branch_id: p.district.district_code for p in org().placements()}
    weeks = [date(2026, 8, 10) + timedelta(weeks=i) for i in range(8)]
    totals: list[Counter[str]] = []
    for monday in weeks:
        week = f"{monday.isocalendar().year}-W{monday.isocalendar().week:02d}"
        rows = generate_activity(
            org(),
            ranges,
            iso_week_id=week,
            seed=31,
            story_districts=("GTA", "MTL"),
            client_ids=CLIENT_IDS,
        )
        assert 12_000 <= len(rows) <= 18_000
        totals.append(Counter(districts[r.branch_id] for r in rows))
    assert totals[-1]["GTA"] < totals[0]["GTA"] * 0.85
    assert totals[-1]["MTL"] > totals[0]["MTL"] * 1.15
    late = generate_activity(
        org(),
        ranges,
        iso_week_id="2026-W40",
        seed=31,
        story_districts=("GTA", "MTL"),
        client_ids=CLIENT_IDS,
    )
    assert 12_000 <= len(late) <= 18_000


def test_holiday_dip_and_february_lift() -> None:
    ranges = assignment_ranges(_roster(900))
    for week in ("2024-W52", "2025-W52"):
        christmas = generate_activity(
            org(), ranges, iso_week_id=week, seed=31, client_ids=CLIENT_IDS
        )
        assert 12_000 <= len(christmas) <= 18_000
    holiday_week = generate_activity(
        org(), ranges, iso_week_id="2026-W27", seed=31, client_ids=CLIENT_IDS
    )
    by_day = Counter(row.activity_ts.date() for row in holiday_week)
    assert by_day[date(2026, 7, 1)] < by_day[date(2026, 7, 2)] * 0.7

    january = generate_activity(
        org(), ranges, iso_week_id="2026-W03", seed=31, client_ids=CLIENT_IDS
    )
    february = generate_activity(
        org(), ranges, iso_week_id="2026-W07", seed=31, client_ids=CLIENT_IDS
    )
    assert len(february) > len(january) * 1.04


def test_seed_week_determinism_and_parquet_schema(tmp_path: Path) -> None:
    ranges = assignment_ranges(_roster(50))
    first = generate_activity(org(), ranges, iso_week_id="2026-W37", seed=7, client_ids=CLIENT_IDS)
    second = generate_activity(org(), ranges, iso_week_id="2026-W37", seed=7, client_ids=CLIENT_IDS)
    other = generate_activity(org(), ranges, iso_week_id="2026-W38", seed=7, client_ids=CLIENT_IDS)
    with pytest.raises(ValueError, match="client_ids"):
        generate_activity(org(), ranges, iso_week_id="2026-W37", seed=7)
    assert first == second
    assert first != other
    path = write_activity(first, tmp_path, extract_date=date(2026, 9, 14))[0]
    bytes_once = path.read_bytes()
    assert (
        write_activity(first, tmp_path, extract_date=date(2026, 9, 14))[0].read_bytes()
        == bytes_once
    )
    table = pq.read_table(path)
    assert table.schema == arrow_schema(SnowflakeActivity)
    assert [SnowflakeActivity.model_validate(row) for row in table.to_pylist()] == list(first)


def test_rewrite_with_fewer_rows_removes_stale_parts(tmp_path: Path) -> None:
    rows = generate_activity(
        org(),
        assignment_ranges(_roster(50)),
        iso_week_id="2026-W37",
        seed=7,
        client_ids=CLIENT_IDS,
    )
    assert len(write_activity(rows[:2], tmp_path, extract_date=date(2026, 9, 14), part_size=1)) == 2
    latest = write_activity(rows[:1], tmp_path, extract_date=date(2026, 9, 14))
    assert len(latest) == 1
    assert sorted(latest[0].parent.glob("part-*.parquet")) == list(latest)
