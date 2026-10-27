"""Seeded portfolio master and holder events derived from advisor assignment ranges."""

from __future__ import annotations

import hashlib
import itertools
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import cache

from pulse.contracts.enums import PortfolioAssignmentReason, Role
from pulse.contracts.sources import TeradataPortfolio, TeradataPortfolioAssignment
from pulse.generate.advisors import AssignmentRow

# Portfolios opened when an advisor transfers are numbered from here (PRT-900001 on).
TRANSFER_RANGE = 900_000


@dataclass(frozen=True)
class PortfolioBatch:
    master: tuple[TeradataPortfolio, ...]
    assignments: tuple[TeradataPortfolioAssignment, ...]


def _ts(day: date) -> datetime:
    return datetime.combine(day, time(12), tzinfo=UTC)


def holder_as_of(batch: PortfolioBatch, portfolio_id: str, day: date) -> str | None:
    events = (
        a for a in batch.assignments if a.portfolio_id == portfolio_id and a.effective_date <= day
    )
    latest = max(events, key=lambda a: (a.effective_date, a.portfolio_assignment_id), default=None)
    return latest.advisor_id if latest else None


def holders_on(batch: PortfolioBatch, day: date) -> dict[str, str]:
    """Every portfolio's holder on ``day`` (the book owner), in one pass over the events."""
    latest: dict[str, TeradataPortfolioAssignment] = {}
    for event in batch.assignments:
        if event.effective_date > day:
            continue
        seen = latest.get(event.portfolio_id)
        key = (event.effective_date, event.portfolio_assignment_id)
        if seen is None or key > (seen.effective_date, seen.portfolio_assignment_id):
            latest[event.portfolio_id] = event
    return {portfolio_id: event.advisor_id for portfolio_id, event in latest.items()}


def generate_portfolios(
    advisors: Sequence[AssignmentRow], *, seed: int, start_date: date
) -> PortfolioBatch:
    """One starting portfolio per book owner; preserve its transit through holder changes."""
    by_advisor: dict[str, list[AssignmentRow]] = defaultdict(list)
    for row in advisors:
        if row[2] is not Role.BRANCH_MANAGER:
            by_advisor[row[0]].append(row)
    for ranges in by_advisor.values():
        ranges.sort(key=lambda r: (r[3], r[1]))

    master: list[TeradataPortfolio] = []
    pending: list[tuple[date, str, str, PortfolioAssignmentReason]] = []
    for number, (owner, ranges) in enumerate(sorted(by_advisor.items()), start=1):
        first = ranges[0]
        portfolio_id = f"PRT-{number:06d}"
        opened = max(first[3], start_date - timedelta(days=1))
        master.append(
            TeradataPortfolio(
                PRTF_ID=portfolio_id,
                BRNCH_ID=first[1],
                OPEN_DT=opened,
                LAST_UPD_TS=_ts(opened),
            )
        )
        pending.append((opened, portfolio_id, owner, PortfolioAssignmentReason.OPEN))

    by_portfolio = {p.portfolio_id: p for p in master}
    current = {portfolio_id: owner for _, portfolio_id, owner, _ in pending}
    # (day, advisor, reason, destination branch for a transfer)
    changes: list[tuple[date, str, PortfolioAssignmentReason, str | None]] = []
    for owner, ranges in by_advisor.items():
        for prior, later in itertools.pairwise(ranges):
            if later[1] != prior[1]:
                changes.append((later[3], owner, PortfolioAssignmentReason.TRANSFER, later[1]))
        last = ranges[-1]
        if last[4] is not None:
            # A range ends on the TERM date and excludes it (advisors.assignment_ranges), so
            # the leaver no longer holds anything that day: the handover is dated the TERM
            # date itself. A day later left one day with a departed holder, which surfaced
            # whenever a TERM date fell on a week end.
            changes.append((last[4], owner, PortfolioAssignmentReason.HANDOVER, None))

    @cache
    def roster_on(day: date) -> tuple[dict[str, set[str]], set[str]]:
        # Several portfolios can change holders on one day. Index the same roster once,
        # then retain the original sorted candidate order for every successor decision.
        branches: dict[str, set[str]] = defaultdict(set)
        active: set[str] = set()
        for advisor, ranges in by_advisor.items():
            for _, branch, _, start, end in ranges:
                if start <= day and (end is None or day < end):
                    branches[branch].add(advisor)
                    active.add(advisor)
        return branches, active

    opened_on_transfer = 0
    for day, outgoing, reason, destination in sorted(changes, key=lambda c: c[:3]):
        for portfolio_id, holder in sorted(current.items()):
            if holder != outgoing:
                continue
            transit = by_portfolio[portfolio_id].branch_id
            branches, active = roster_on(day)
            candidates = sorted(branches.get(transit, set()) - {outgoing}) or sorted(
                active - {outgoing}
            )
            if not candidates:
                raise ValueError(f"no portfolio handover advisor at {transit} on {day}")
            # The book goes to the colleague holding the fewest portfolios, as a branch would
            # spread a leaver's clients; a random pick piled books onto a few advisors, and
            # their portfolios' contacted rate slid year after year.
            held = Counter(current.values())
            successor = min(
                candidates,
                key=lambda a: (
                    held[a],
                    hashlib.sha256(f"{seed}|{portfolio_id}|{day}|{a}".encode()).digest(),
                ),
            )
            current[portfolio_id] = successor
            pending.append((day, portfolio_id, successor, reason))
        if destination is not None:
            # The mover leaves their portfolio at its transit and opens one at the new branch;
            # client generation fills it from that branch's other portfolios. These IDs have
            # their own range, so a longer horizon (more hires) never renumbers them.
            opened_on_transfer += 1
            portfolio_id = f"PRT-{TRANSFER_RANGE + opened_on_transfer:06d}"
            portfolio = TeradataPortfolio(
                PRTF_ID=portfolio_id, BRNCH_ID=destination, OPEN_DT=day, LAST_UPD_TS=_ts(day)
            )
            master.append(portfolio)
            by_portfolio[portfolio_id] = portfolio
            current[portfolio_id] = outgoing
            pending.append((day, portfolio_id, outgoing, PortfolioAssignmentReason.OPEN))

    assignments = tuple(
        TeradataPortfolioAssignment(
            PASGN_ID=f"PAS-{number:08d}",
            PRTF_ID=portfolio_id,
            ADVSR_ID=owner,
            EFF_DT=day,
            RSN_CD=reason,
            LAST_UPD_TS=_ts(day),
        )
        for number, (day, portfolio_id, owner, reason) in enumerate(sorted(pending), start=1)
    )
    return PortfolioBatch(tuple(master), assignments)
