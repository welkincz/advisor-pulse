"""Deterministic fictional advisor roster and Teradata-style assignment events."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from faker import Faker

from pulse.contracts.enums import AssignmentReason, Role
from pulse.contracts.sources import TeradataAdvisor, TeradataAssignment, TeradataBranch
from pulse.generate.teradata import replace_table, write_transaction
from pulse.reference import BranchPlacement, OrgReference

DEFAULT_START = date(2024, 10, 7)
TRANSFER_RATE = 0.015
PROMOTION_RATE = 0.002
TERM_RATE = 0.002

AssignmentRow = tuple[str, str, Role, date, date | None]
_Event = tuple[date, str, str, Role, AssignmentReason]


@dataclass(frozen=True)
class AdvisorRoster:
    advisors: tuple[TeradataAdvisor, ...]
    assignments: tuple[TeradataAssignment, ...]
    branches: tuple[TeradataBranch, ...]


def _updated_on(day: date) -> datetime:
    return datetime.combine(day, time(12), tzinfo=UTC)


def _count_at_rate(population: int, rate: float, rng: random.Random) -> int:
    expected = population * rate
    whole = int(expected)
    return whole + (rng.random() < expected - whole)


def _month_starts(start: date, end: date) -> Sequence[date]:
    year, month = start.year, start.month
    dates: list[date] = []
    while True:
        month += 1
        if month == 13:
            year, month = year + 1, 1
        day = date(year, month, 1)
        if day >= end:
            return dates
        dates.append(day)


def _transfer_target(
    current: str,
    placements: Sequence[BranchPlacement],
    by_id: dict[str, BranchPlacement],
    rng: random.Random,
) -> str:
    source = by_id[current]
    chance = rng.random()
    if chance < 0.8:
        choices = [
            p.branch.branch_id
            for p in placements
            if p.district.district_code == source.district.district_code
            and p.branch.branch_id != current
        ]
    elif chance < 0.9:
        choices = [
            p.branch.branch_id
            for p in placements
            if p.region.region_code == source.region.region_code
            and p.district.district_code != source.district.district_code
        ]
    else:
        choices = [
            p.branch.branch_id
            for p in placements
            if p.region.region_code != source.region.region_code
        ]
    if not choices:
        choices = [p.branch.branch_id for p in placements if p.branch.branch_id != current]
    return rng.choice(choices)


def generate_advisors(
    org: OrgReference,
    *,
    seed: int,
    advisor_count: int = 900,
    start_date: date = DEFAULT_START,
    weeks: int = 104,
) -> AdvisorRoster:
    """Return source rows; never write files or use the wall clock."""
    if advisor_count < 1 or advisor_count > 99_999:
        raise ValueError("advisor_count must be between 1 and 99999")
    if weeks < 1:
        raise ValueError("weeks must be positive")
    placements = org.placements()
    if len(placements) < 2:
        raise ValueError("at least two branches are needed for transfers")

    rng = random.Random(seed)
    fake = Faker("en_CA")
    fake.seed_instance(seed)
    branch_order = list(placements)
    rng.shuffle(branch_order)
    by_id = {p.branch.branch_id: p for p in placements}
    branches = tuple(
        TeradataBranch(
            BRNCH_ID=p.branch.branch_id,
            BRNCH_NM=p.branch.branch_name,
            DIST_CD=p.district.district_code,
            FSA_CD=p.branch.fsa_code,
            OPEN_DT=p.branch.open_date,
            LAST_UPD_TS=_updated_on(start_date),
        )
        for p in placements
    )

    advisors: dict[str, TeradataAdvisor] = {}
    active: dict[str, tuple[str, Role]] = {}
    events: list[_Event] = []
    next_advisor = 1
    manager_count = min(len(placements), advisor_count // 5)
    for index in range(advisor_count):
        placement = branch_order[index % len(branch_order)]
        role = (
            Role.BRANCH_MANAGER
            if index < manager_count
            else rng.choices(
                [Role.ASSOCIATE, Role.ADVISOR, Role.SENIOR_ADVISOR],
                weights=[25, 60, 15],
            )[0]
        )
        earliest = max(start_date - timedelta(days=3652), placement.branch.open_date)
        hired = earliest + timedelta(days=rng.randrange((start_date - earliest).days + 1))
        advisor_id = f"ADV-{next_advisor:05d}"
        next_advisor += 1
        advisors[advisor_id] = TeradataAdvisor(
            ADVSR_ID=advisor_id,
            ADVSR_NM=fake.name(),
            ROLE_CD=role,
            HIRE_DT=hired,
            LAST_UPD_TS=_updated_on(hired),
        )
        active[advisor_id] = (placement.branch.branch_id, role)
        events.append((hired, advisor_id, placement.branch.branch_id, role, AssignmentReason.HIRE))

    for day in _month_starts(start_date, start_date + timedelta(weeks=weeks)):
        transferable = sorted(
            advisor_id for advisor_id, (_, role) in active.items() if role != Role.BRANCH_MANAGER
        )
        rng.shuffle(transferable)
        changed: set[str] = set()
        for advisor_id in transferable[: _count_at_rate(len(active), TRANSFER_RATE, rng)]:
            branch_id, role = active[advisor_id]
            target = _transfer_target(branch_id, placements, by_id, rng)
            active[advisor_id] = (target, role)
            events.append((day, advisor_id, target, role, AssignmentReason.TRANSFER))
            advisors[advisor_id] = advisors[advisor_id].model_copy(
                update={"last_updated_ts": _updated_on(day)}
            )
            changed.add(advisor_id)

        promotable = sorted(
            advisor_id
            for advisor_id, (_, role) in active.items()
            if advisor_id not in changed and role in (Role.ASSOCIATE, Role.ADVISOR)
        )
        rng.shuffle(promotable)
        for advisor_id in promotable[: _count_at_rate(len(active), PROMOTION_RATE, rng)]:
            branch_id, role = active[advisor_id]
            promoted = Role.ADVISOR if role == Role.ASSOCIATE else Role.SENIOR_ADVISOR
            active[advisor_id] = (branch_id, promoted)
            events.append((day, advisor_id, branch_id, promoted, AssignmentReason.PROMOTION))
            advisors[advisor_id] = advisors[advisor_id].model_copy(
                update={"role_code": promoted, "last_updated_ts": _updated_on(day)}
            )
            changed.add(advisor_id)

        leavers = sorted(advisor_id for advisor_id in active if advisor_id not in changed)
        rng.shuffle(leavers)
        for advisor_id in leavers[: _count_at_rate(len(active), TERM_RATE, rng)]:
            branch_id, role = active.pop(advisor_id)
            events.append((day, advisor_id, branch_id, role, AssignmentReason.TERM))
            advisors[advisor_id] = advisors[advisor_id].model_copy(
                update={"term_date": day, "last_updated_ts": _updated_on(day)}
            )
            replacement_id = f"ADV-{next_advisor:05d}"
            next_advisor += 1
            advisors[replacement_id] = TeradataAdvisor(
                ADVSR_ID=replacement_id,
                ADVSR_NM=fake.name(),
                ROLE_CD=role,
                HIRE_DT=day,
                LAST_UPD_TS=_updated_on(day),
            )
            active[replacement_id] = (branch_id, role)
            events.append((day, replacement_id, branch_id, role, AssignmentReason.HIRE))

    assignments = tuple(
        TeradataAssignment(
            ASGN_ID=f"ASG-{number:08d}",
            ADVSR_ID=advisor_id,
            BRNCH_ID=branch_id,
            ROLE_CD=role,
            EFF_DT=day,
            RSN_CD=reason,
            LAST_UPD_TS=_updated_on(day),
        )
        for number, (day, advisor_id, branch_id, role, reason) in enumerate(sorted(events), start=1)
    )
    return AdvisorRoster(
        advisors=tuple(advisors.values()), assignments=assignments, branches=branches
    )


def assignment_ranges(roster: AdvisorRoster) -> tuple[AssignmentRow, ...]:
    """Every (advisor, branch, role, valid_from, valid_to) range; ``valid_to`` is exclusive.

    A TERM event closes the previous range and opens none, so a leaver's last range ends on
    their TERM date. The current range of an active advisor has ``valid_to`` None.
    """
    by_advisor: dict[str, list[TeradataAssignment]] = defaultdict(list)
    for event in roster.assignments:
        by_advisor[event.advisor_id].append(event)
    rows: list[AssignmentRow] = []
    for advisor_id, events in sorted(by_advisor.items()):
        events.sort(key=lambda e: (e.effective_date, e.assignment_id))
        for index, event in enumerate(events):
            if event.reason_code == AssignmentReason.TERM:
                continue
            valid_to = events[index + 1].effective_date if index + 1 < len(events) else None
            rows.append(
                (advisor_id, event.branch_id, event.role_code, event.effective_date, valid_to)
            )
    return tuple(rows)


def assignments_as_of(roster: AdvisorRoster, as_of: date) -> tuple[AssignmentRow, ...]:
    """The ranges in effect on ``as_of``: one per active advisor."""
    return tuple(
        r for r in assignment_ranges(roster) if r[3] <= as_of and (r[4] is None or as_of < r[4])
    )


def write_advisors(roster: AdvisorRoster, db_path: Path) -> None:
    """Replace only ADVSR, ADVSR_ASGN and BRNCH; preserve CLNT in the same file."""
    with write_transaction(db_path) as conn:
        replace_table(conn, "ADVSR", TeradataAdvisor, roster.advisors, "ADVSR_ID")
        replace_table(conn, "ADVSR_ASGN", TeradataAssignment, roster.assignments, "ASGN_ID")
        replace_table(conn, "BRNCH", TeradataBranch, roster.branches, "BRNCH_ID")
