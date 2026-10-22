"""Seeded portfolio master and holder events derived from advisor assignment ranges."""

from __future__ import annotations

import hashlib
import itertools
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from pulse.contracts.enums import PortfolioAssignmentReason, Role
from pulse.contracts.sources import TeradataPortfolio, TeradataPortfolioAssignment
from pulse.generate.advisors import AssignmentRow


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
    changes: list[tuple[date, str, PortfolioAssignmentReason]] = []
    for owner, ranges in by_advisor.items():
        for prior, later in itertools.pairwise(ranges):
            if later[1] != prior[1]:
                changes.append((later[3], owner, PortfolioAssignmentReason.TRANSFER))
        last = ranges[-1]
        if last[4] is not None:
            changes.append((last[4] + timedelta(days=1), owner, PortfolioAssignmentReason.HANDOVER))

    for day, outgoing, reason in sorted(changes):
        for portfolio_id, holder in sorted(current.items()):
            if holder != outgoing:
                continue
            transit = by_portfolio[portfolio_id].branch_id
            candidates = sorted(
                advisor
                for advisor, ranges in by_advisor.items()
                if advisor != outgoing
                and any(
                    branch == transit and start <= day and (end is None or day < end)
                    for _, branch, _, start, end in ranges
                )
            )
            if not candidates:
                candidates = sorted(
                    advisor
                    for advisor, ranges in by_advisor.items()
                    if advisor != outgoing
                    and any(
                        start <= day and (end is None or day < end)
                        for _, _, _, start, end in ranges
                    )
                )
            if not candidates:
                raise ValueError(f"no portfolio handover advisor at {transit} on {day}")
            digest = hashlib.sha256(f"{seed}|{portfolio_id}|{day}".encode()).digest()
            successor = candidates[int.from_bytes(digest[:8], "big") % len(candidates)]
            current[portfolio_id] = successor
            pending.append((day, portfolio_id, successor, reason))

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
