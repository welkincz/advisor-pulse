"""Seeded weekly activity facts for the fictional advisor network."""

from __future__ import annotations

import hashlib
import itertools
import math
import random
import re
import tempfile
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from pathlib import Path
from statistics import NormalDist

import pyarrow as pa
import pyarrow.parquet as pq

from pulse.business_calendar import WEEKDAY_WEIGHTS, holiday_factor, seasonal_factor
from pulse.contracts import arrow_schema
from pulse.contracts.enums import (
    ActivityStatus,
    ActivityType,
    Channel,
    Outcome,
    ProductLine,
    Role,
)
from pulse.contracts.patterns import ISO_WEEK_ID
from pulse.contracts.sources import SnowflakeActivity
from pulse.generate.advisors import DEFAULT_START, AssignmentRow
from pulse.generate.books import client_pools_by_day
from pulse.generate.clients import ClientBatch
from pulse.reference import OrgReference

STORY_START = date(2026, 8, 10)
# A few advisors' portfolios slip from here on, so the 12-month contacted rate has a story.
DRIFT_START = date(2025, 11, 1)
DRIFT_DAYS = 270
DRIFT_SHARE = 0.12
# A gradual bank-wide shift towards clients who hear from advisors less often. The rolling
# 12-month KPI keeps improving after this ramp ends as concentrated-contact weeks roll off.
OUTREACH_END = date.fromisocalendar(2026, 42, 1)
OUTREACH_INITIAL_BIAS = 0.28
OUTREACH_FINAL_BIAS = -0.19
_STANDARD_NORMAL = NormalDist()


def _week_start(iso_week_id: str) -> date:
    try:
        if not re.fullmatch(ISO_WEEK_ID, iso_week_id):
            raise ValueError("Noncanonical ISO week")
        year, week = iso_week_id.split("-W")
        return date.fromisocalendar(int(year), int(week), 1)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid ISO week: {iso_week_id}") from exc


def _id(seed: int, week: str, advisor: str, sequence: int) -> str:
    digest = hashlib.sha256(f"{seed}|{week}|{advisor}|{sequence}".encode()).hexdigest()[:12]
    return f"ACT-{digest}"


def _profile(advisor: str) -> float:
    value = int.from_bytes(hashlib.sha256(advisor.encode()).digest()[:2], "big") / 65535
    return 0.8 + 0.4 * value


def _unit(*parts: object) -> float:
    """A seeded number in [0, 1), stable across weeks and processes."""
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


@cache
def _propensity(seed: int, client: str) -> float:
    """How readily a client is contacted: lognormal, so some are called often, some rarely."""
    u = min(max(_unit(seed, "propensity", client), 1e-12), 1 - 1e-12)
    return math.exp(_STANDARD_NORMAL.inv_cdf(u))


def _concentration(seed: int, advisor: str, day: date) -> float:
    """How strongly an advisor favours the same clients: 0 spreads calls across the whole
    book, higher keeps returning to a few. A gradual bank-wide easing lifts the rolling
    12-month rate from about 83% in 2024 to about 87% by 2027; seeded drifters still slip."""
    alpha: float = 0.22 + 1.45 * _unit(seed, "reach", advisor) ** 1.2
    progress = min(1.0, max(0.0, (day - DEFAULT_START).days / (OUTREACH_END - DEFAULT_START).days))
    alpha += OUTREACH_INITIAL_BIAS + (OUTREACH_FINAL_BIAS - OUTREACH_INITIAL_BIAS) * progress
    if _unit(seed, "drift", advisor) < DRIFT_SHARE:
        alpha += 0.7 * min(1.0, max(0.0, (day - DRIFT_START).days / DRIFT_DAYS))
    return alpha


def _count(rng: random.Random, factor: float) -> int:
    base = rng.choices([1, 2, 3, 4, 5], weights=[5, 15, 30, 30, 20])[0] * factor
    whole = int(base)
    return whole + (rng.random() < base - whole)


def generate_activity(
    org: OrgReference,
    assignments: Sequence[AssignmentRow],
    *,
    iso_week_id: str,
    seed: int,
    client_batch: ClientBatch,
    story_districts: tuple[str, str] | None = None,
) -> tuple[SnowflakeActivity, ...]:
    """Generate one week from as-of assignments; no wall clock or mutable state."""
    monday = _week_start(iso_week_id)
    pools = client_pools_by_day(client_batch, [monday + timedelta(days=i) for i in range(5)])
    story_step = min(7, max(0, (monday - STORY_START).days // 7))
    districts = {p.branch.branch_id: p.district.district_code for p in org.placements()}
    if story_districts is None:
        codes = sorted(set(districts.values()))
        story_districts = (codes[0], codes[1])
    if len(set(story_districts)) != 2 or any(d not in districts.values() for d in story_districts):
        raise ValueError("story_districts must name two distinct known districts")
    rng_seed = int.from_bytes(hashlib.sha256(f"{seed}|{iso_week_id}".encode()).digest()[:8], "big")
    rng = random.Random(rng_seed)
    extracted = datetime.combine(monday + timedelta(days=7), time(3), tzinfo=UTC)
    rows: list[SnowflakeActivity] = []
    sequence = 0
    for offset in range(5):
        day = monday + timedelta(days=offset)
        books, active_clients = pools[day]
        weights: dict[str, list[float]] = {}
        weekday = WEEKDAY_WEIGHTS[offset]
        seasonal = seasonal_factor(day)
        holiday = holiday_factor(day)
        active = sorted(
            (advisor, branch)
            for advisor, branch, role, start, end in assignments
            if role != Role.BRANCH_MANAGER and start <= day and (end is None or day < end)
        )
        for advisor, branch in active:
            district = districts[branch]
            story = (
                1 - 0.05 * story_step
                if district == story_districts[0]
                else 1 + 0.05 * story_step
                if district == story_districts[1]
                else 1.0
            )
            for _ in range(_count(rng, _profile(advisor) * weekday * seasonal * holiday * story)):
                kind = rng.choices(
                    [ActivityType.CALL_OUT, ActivityType.CALL_IN, ActivityType.REVIEW],
                    weights=[60, 30, 10],
                )[0]
                at = datetime.combine(
                    day, time(14 + rng.randrange(6), rng.randrange(60)), tzinfo=UTC
                )
                client = None
                if kind != ActivityType.CALL_OUT or rng.random() >= 0.1:
                    own_book = books.get(advisor, ())
                    if own_book and rng.random() < 0.95:
                        if advisor not in weights:
                            alpha = _concentration(seed, advisor, day)
                            weights[advisor] = list(
                                itertools.accumulate(
                                    _propensity(seed, c) ** alpha for c in own_book
                                )
                            )
                        client = rng.choices(own_book, cum_weights=weights[advisor])[0]
                    else:
                        client = rng.choice(active_clients)
                sequence += 1
                activity_id = _id(seed, iso_week_id, advisor, sequence)
                duration = rng.randrange(5, 46)
                scheduled = at if kind == ActivityType.REVIEW else None
                outcome = rng.choices(
                    [Outcome.NONE, Outcome.FOLLOW_UP, Outcome.PLAN_CREATED, Outcome.PRODUCT_OPENED],
                    weights=[35, 40, 15, 10],
                )[0]
                rows.append(
                    SnowflakeActivity(
                        ACTIVITY_ID=activity_id,
                        ADVISOR_ID=advisor,
                        CLIENT_ID=client,
                        BRANCH_ID=branch,
                        ACTIVITY_TYPE=kind,
                        CHANNEL=Channel.PHONE if kind != ActivityType.REVIEW else Channel.VIDEO,
                        STATUS=ActivityStatus.COMPLETED,
                        OUTCOME=outcome,
                        PRODUCT_LINE=rng.choice(list(ProductLine))
                        if outcome != Outcome.NONE
                        else None,
                        SCHEDULED_TS=scheduled,
                        ACTIVITY_TS=at + timedelta(minutes=duration) if scheduled else at,
                        DURATION_MIN=duration,
                        CREATED_TS=at - timedelta(days=1) if scheduled else at,
                        UPDATED_TS=at + timedelta(minutes=duration),
                        _EXTRACTED_AT=extracted,
                    )
                )
                if kind != ActivityType.CALL_OUT or client is None or rng.random() >= 0.09:
                    continue
                appointment_time = at + timedelta(hours=2)
                status = rng.choices(
                    [ActivityStatus.COMPLETED, ActivityStatus.NO_SHOW, ActivityStatus.CANCELLED],
                    weights=[80, 12, 8],
                )[0]
                appointment_duration = (
                    rng.randrange(25, 91) if status == ActivityStatus.COMPLETED else None
                )
                sequence += 1
                rows.append(
                    SnowflakeActivity(
                        ACTIVITY_ID=_id(seed, iso_week_id, advisor, sequence),
                        ADVISOR_ID=advisor,
                        CLIENT_ID=client,
                        BRANCH_ID=branch,
                        ACTIVITY_TYPE=ActivityType.APPOINTMENT,
                        CHANNEL=Channel.IN_BRANCH,
                        STATUS=status,
                        OUTCOME=outcome if status == ActivityStatus.COMPLETED else None,
                        PRODUCT_LINE=rng.choice(list(ProductLine))
                        if status == ActivityStatus.COMPLETED
                        else None,
                        SCHEDULED_TS=appointment_time,
                        ACTIVITY_TS=appointment_time + timedelta(minutes=appointment_duration or 0),
                        DURATION_MIN=appointment_duration,
                        BOOKED_FROM_ACTIVITY_ID=activity_id,
                        CREATED_TS=at,
                        UPDATED_TS=appointment_time + timedelta(minutes=appointment_duration or 0),
                        _EXTRACTED_AT=extracted,
                    )
                )
    return tuple(rows)


def write_activity(
    rows: Sequence[SnowflakeActivity],
    sources_root: Path,
    *,
    extract_date: date,
    part_size: int = 25_000,
) -> tuple[Path, ...]:
    """Write deterministic Parquet parts with the contract's exact Arrow schema."""
    if part_size < 1:
        raise ValueError("part_size must be positive")
    directory = sources_root / "snowflake/activity" / f"extract_date={extract_date.isoformat()}"
    directory.parent.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    with tempfile.TemporaryDirectory(dir=directory.parent) as temporary:
        staging = Path(temporary) / directory.name
        staging.mkdir()
        for index, start in enumerate(range(0, len(rows), part_size)):
            name = f"part-{index:03d}.parquet"
            table = pa.Table.from_pylist(
                [
                    row.model_dump(by_alias=True, mode="python")
                    for row in rows[start : start + part_size]
                ],
                schema=arrow_schema(SnowflakeActivity),
            )
            pq.write_table(table, staging / name, compression="zstd")
            names.append(name)
        if directory.exists():
            directory.rename(Path(temporary) / "old")
        try:
            staging.rename(directory)
        except BaseException:
            if (Path(temporary) / "old").exists():
                (Path(temporary) / "old").rename(directory)
            raise
    return tuple(directory / name for name in names)
