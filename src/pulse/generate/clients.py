"""Deterministic clean client source rows: a CLNT snapshot plus daily Teradata-style deltas.

Follows PLAN.md §6.2: CLNT is the state the day before ``start_date`` and is never rewritten.
Every later change is a row in ``client_YYYYMMDD.csv`` whose LAST_UPD_TS is strictly after
every snapshot timestamp, so an incremental load on LAST_UPD_TS sees each delta exactly once.
"""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal

from pulse.contracts import column_names
from pulse.contracts.enums import ClientStatus, Role, Segment
from pulse.contracts.sources import TeradataClient
from pulse.generate.advisors import DEFAULT_START
from pulse.generate.portfolios import PortfolioBatch, generate_portfolios, holder_as_of
from pulse.generate.teradata import replace_table, sql_value, write_transaction
from pulse.reference import OrgReference, fsa_province

QUARTER_DAYS = 91
REASSIGN_RATE = 0.02
NEW_DAILY_RATE = 0.00002
CLOSE_DAILY_RATE = 0.00001
POSTAL_LETTERS = "ABCEGHJKLMNPRSTVWXYZ"

# (advisor_id, branch_id, role, valid_from, valid_to exclusive), as from
# pulse.generate.advisors.assignment_ranges.
AdvisorAssignment = tuple[str, str, Role, date, date | None]
# REASSIGNED is the ~2%/quarter business churn. Holder changes retain the portfolio ID.
# REBALANCED fills a portfolio opened mid-history (a hire or a transfer) from its branch.
ChangeKind = Literal[
    "NEW", "CLOSED", "REASSIGNED", "ADVISOR_LEFT", "PORTFOLIO_TRANSFER", "REBALANCED"
]


@dataclass(frozen=True)
class ClientChange:
    day: date
    kind: ChangeKind
    before: TeradataClient | None
    after: TeradataClient


@dataclass(frozen=True)
class ClientBatch:
    snapshot: tuple[TeradataClient, ...]
    changes: tuple[ClientChange, ...]
    # The portfolios the clients name: a client's book owner is its portfolio's holder.
    portfolios: PortfolioBatch

    def owner(self, client: TeradataClient, day: date) -> str | None:
        """The client's book owner on ``day``: the holder of its portfolio."""
        return holder_as_of(self.portfolios, client.portfolio_id, day)

    def final(self) -> tuple[TeradataClient, ...]:
        """Snapshot with every change applied, in CLNT_ID order."""
        state = {c.client_id: c for c in self.snapshot}
        for change in self.changes:
            state[change.after.client_id] = change.after
        return tuple(state[k] for k in sorted(state))


def _ts(day: date) -> datetime:
    return datetime.combine(day, time(12), tzinfo=UTC)


def _count_at_rate(population: int, rate: float, rng: random.Random) -> int:
    expected = population * rate
    whole = int(expected)
    return whole + (rng.random() < expected - whole)


def _book_owners(roster: Sequence[AdvisorAssignment], day: date) -> list[AdvisorAssignment]:
    """Advisors who can own a book on ``day``. Branch managers do not."""
    return [
        a
        for a in roster
        if a[2] != Role.BRANCH_MANAGER and a[3] <= day and (a[4] is None or day < a[4])
    ]


def generate_clients(
    org: OrgReference,
    advisors: Sequence[AdvisorAssignment],
    *,
    seed: int,
    client_count: int = 150_000,
    start_date: date = DEFAULT_START,
    weeks: int = 104,
    portfolio_batch: PortfolioBatch | None = None,
    retain_from: date | None = None,
    retain_through: date | None = None,
) -> ClientBatch:
    """Return the CLNT snapshot (as of the day before ``start_date``) and every daily change."""
    if not 1 <= client_count < 100_000_000:
        raise ValueError("client_count must be between 1 and 99999999")
    if weeks < 1:
        raise ValueError("weeks must be positive")
    # Earlier changes still consume the same RNG draws and update the same books, but
    # their versions need not survive when the caller only exports a later date range.
    if retain_from is not None and not start_date <= retain_from < start_date + timedelta(
        weeks=weeks
    ):
        raise ValueError("retain_from must be within the generated horizon")
    snapshot_day = start_date - timedelta(days=1)
    initial_owners = _book_owners(advisors, snapshot_day)
    if not initial_owners:
        raise ValueError("at least one active advisor (not a branch manager) is required")

    rng = random.Random(seed)
    portfolios = portfolio_batch or generate_portfolios(advisors, seed=seed, start_date=start_date)
    by_portfolio = {p.portfolio_id: p for p in portfolios.master}
    portfolio_holders = {
        p.portfolio_id: holder_as_of(portfolios, p.portfolio_id, snapshot_day)
        for p in portfolios.master
    }
    initial_portfolio = {
        holder: portfolio_id
        for portfolio_id, holder in portfolio_holders.items()
        if holder is not None
    }
    holder_events = defaultdict(list)
    for event in portfolios.assignments:
        if event.effective_date >= start_date:
            holder_events[event.effective_date].append(event)
    portfolios_by_branch: dict[str, list[str]] = defaultdict(list)
    for portfolio in portfolios.master:
        portfolios_by_branch[portfolio.branch_id].append(portfolio.portfolio_id)
    placements = {p.branch.branch_id: p for p in org.placements()}
    for advisor_id, branch_id, _, valid_from, valid_to in advisors:
        if branch_id not in placements or (valid_to is not None and valid_to <= valid_from):
            raise ValueError(f"invalid advisor assignment for {advisor_id}")
    pools = {
        p.branch.branch_id: tuple(b.fsa_code for b in p.district.branches)
        for p in placements.values()
    }

    district_by_branch = {branch: p.district.district_code for branch, p in placements.items()}
    district_by_portfolio = {
        p.portfolio_id: district_by_branch[p.branch_id] for p in portfolios.master
    }

    segments = list(Segment)
    segment_weights = [60, 85, 95, 100]  # Exact cumulative form of [60, 25, 10, 5].
    history_dates = [snapshot_day - timedelta(days=i) for i in range(3653)]
    timestamps: dict[date, datetime] = {}

    def timestamp(day: date) -> datetime:
        if day not in timestamps:
            timestamps[day] = _ts(day)
        return timestamps[day]

    def make_client(
        client_id: str,
        owner: AdvisorAssignment,
        portfolio_id: str,
        since: date,
        updated: date,
    ) -> TeradataClient:
        branch_id = owner[1]
        branch_fsa = placements[branch_id].branch.fsa_code
        fsa = branch_fsa if rng.random() < 0.8 else rng.choice(pools[branch_id])
        postal = f"{fsa} {rng.randrange(10)}{rng.choice(POSTAL_LETTERS)}{rng.randrange(10)}"
        return TeradataClient(
            CLNT_ID=client_id,
            CLNT_SINCE_DT=since,
            BRTH_YR=rng.randint(1940, 1995),
            SEG_CD=rng.choices(segments, cum_weights=segment_weights)[0],
            PSTL_CD=postal,
            PROV_CD=fsa_province(fsa),
            PRIM_BRNCH_ID=branch_id,
            STAT_CD=ClientStatus.ACTIVE,
            LAST_UPD_TS=timestamp(updated),
            PRTF_ID=portfolio_id,
        )

    current: dict[str, TeradataClient] = {}
    book: dict[str, set[str]] = defaultdict(set)  # portfolio_id -> active client ids
    active_ids: list[str] = []
    active_position: dict[str, int] = {}

    def activate(client: TeradataClient) -> None:
        current[client.client_id] = client
        book[client.portfolio_id].add(client.client_id)
        active_position[client.client_id] = len(active_ids)
        active_ids.append(client.client_id)

    for number in range(1, client_count + 1):
        age = rng.randrange(3653)
        since = history_dates[age]
        updated = history_dates[age - rng.randrange(age + 1)]
        owner = rng.choice(initial_owners)
        # The row names its owner as of LAST_UPD_TS, so that is no earlier than the
        # owner's current assignment.
        updated = max(updated, owner[3])
        activate(
            make_client(f"CLI-{number:08d}", owner, initial_portfolio[owner[0]], since, updated)
        )
    snapshot = tuple(current.values())

    changes: list[ClientChange] = []

    def move(client_id: str, portfolio_id: str, day: date, kind: ChangeKind) -> None:
        before = current[client_id]
        old_portfolio = before.portfolio_id
        if retain_from is not None and day < retain_from and old_portfolio == portfolio_id:
            # Holder changes retain the book, and align the branch to its transit.
            before.__dict__["primary_branch_id"] = by_portfolio[portfolio_id].branch_id
            before.__dict__["last_updated_ts"] = timestamp(day)
            return
        update = {
            "primary_branch_id": by_portfolio[portfolio_id].branch_id,
            "portfolio_id": portfolio_id,
            "last_updated_ts": timestamp(day),
        }
        if retain_from is not None and day < retain_from:
            # These rows are private working state until the boundary snapshot below.
            # Like model_copy(update=...), updates use already validated field values.
            before.__dict__.update(update)
            after = before
        else:
            after = before.model_copy(update=update)
        book[old_portfolio].discard(client_id)
        book[portfolio_id].add(client_id)
        current[client_id] = after
        if retain_from is None or day >= retain_from:
            changes.append(ClientChange(day, kind, before, after))

    def rebalance(portfolio_id: str, day: date, owners: dict[str, AdvisorAssignment]) -> None:
        """Give a newly opened portfolio an even share of its branch's clients.

        Every other portfolio at the same transit hands over 1 / (n + 1) of its active
        clients, chosen by the seeded generator, so the newcomer starts with a typical book.
        """
        transit = by_portfolio[portfolio_id].branch_id
        donors = sorted(
            (p, h)
            for p in portfolios_by_branch[transit]
            if p != portfolio_id and (h := portfolio_holders[p]) is not None and h in owners
        )
        for donor, _ in donors:
            clients = sorted(c for c in book[donor] if c not in protected)
            for client_id in rng.sample(clients, len(clients) // (len(donors) + 1)):
                move(client_id, portfolio_id, day, "REBALANCED")

    scheduled: dict[date, list[str]] = defaultdict(list)
    protected: set[str] = set()
    next_number = client_count + 1
    total_days = weeks * 7
    roster_days = {day for row in advisors for day in row[3:] if day is not None} | {start_date}
    owner_by_id: dict[str, AdvisorAssignment] = {}
    # Keep total_days for quarter scheduling: shortening the last quarter would change
    # its RNG draws. Only stop replay after the final day the caller will consume.
    replay_days = (
        total_days
        if retain_through is None
        else min(total_days, (retain_through - start_date).days + 1)
    )
    for offset in range(replay_days):
        day = start_date + timedelta(days=offset)
        if day == retain_from:
            snapshot = tuple(current.values())
        if day in roster_days:
            owner_by_id = {owner[0]: owner for owner in _book_owners(advisors, day)}
        if not owner_by_id:
            raise ValueError(f"no active advisor on {day.isoformat()}")
        for event in holder_events.get(day, []):
            if event.advisor_id not in owner_by_id:
                raise ValueError(f"{event.advisor_id} cannot hold a portfolio on {day}")
            previous = portfolio_holders[event.portfolio_id]
            portfolio_holders[event.portfolio_id] = event.advisor_id
            if previous is None:
                rebalance(event.portfolio_id, day, owner_by_id)
                continue
            # The clients stay in the portfolio; their rows are touched on the day so the
            # delta shows the handover, as the Teradata extract does.
            kind: ChangeKind = (
                "ADVISOR_LEFT" if event.reason_code == "HANDOVER" else "PORTFOLIO_TRANSFER"
            )
            for client_id in sorted(book[event.portfolio_id]):
                move(client_id, event.portfolio_id, day, kind)

        if day in roster_days or day in holder_events:
            active_portfolios = [
                (p.portfolio_id, owner_by_id[holder])
                for p in portfolios.master
                if (holder := portfolio_holders[p.portfolio_id]) in owner_by_id
            ]

            # Preserve master order within each district: rng.choice must see exactly the
            # same candidates in the same order as filtering the full list for every move.
            district_portfolios: dict[str, list[tuple[str, AdvisorAssignment]]] = defaultdict(list)
            for portfolio_id, owner in active_portfolios:
                district_portfolios[district_by_portfolio[portfolio_id]].append(
                    (portfolio_id, owner)
                )

        if offset % QUARTER_DAYS == 0:
            count = _count_at_rate(len(active_ids), REASSIGN_RATE, rng)
            chosen = rng.sample(active_ids, min(len(active_ids), count))
            protected = set(chosen)
            days_left = min(QUARTER_DAYS, total_days - offset)
            for client_id in chosen:
                scheduled[day + timedelta(days=rng.randrange(days_left))].append(client_id)

        new_today: set[str] = set()
        for _ in range(_count_at_rate(len(active_ids), NEW_DAILY_RATE, rng)):
            if next_number >= 100_000_000:
                raise ValueError("client ID space exhausted")
            portfolio_id, owner = rng.choice(active_portfolios)
            client = make_client(f"CLI-{next_number:08d}", owner, portfolio_id, day, day)
            next_number += 1
            activate(client)
            new_today.add(client.client_id)
            if retain_from is None or day >= retain_from:
                changes.append(ClientChange(day, "NEW", None, client))

        for client_id in scheduled.pop(day, []):
            before = current[client_id]
            alternatives = [
                (p, o)
                for p, o in district_portfolios[district_by_branch[before.primary_branch_id]]
                if p != before.portfolio_id
            ]
            if alternatives:
                portfolio_id, _ = rng.choice(alternatives)
                move(client_id, portfolio_id, day, "REASSIGNED")

        for _ in range(_count_at_rate(len(active_ids), CLOSE_DAILY_RATE, rng)):
            if len(protected | new_today) >= len(active_ids):
                break
            client_id = rng.choice(active_ids)
            while client_id in protected or client_id in new_today:
                client_id = rng.choice(active_ids)
            before = current[client_id]
            after = before.model_copy(
                update={"status_code": ClientStatus.CLOSED, "last_updated_ts": timestamp(day)}
            )
            current[client_id] = after
            book[before.portfolio_id].discard(client_id)
            if retain_from is None or day >= retain_from:
                changes.append(ClientChange(day, "CLOSED", before, after))
            index = active_position.pop(client_id)
            last = active_ids.pop()
            if index < len(active_ids):
                active_ids[index] = last
                active_position[last] = index

    return ClientBatch(snapshot=snapshot, changes=tuple(changes), portfolios=portfolios)


def delta_rows(batch: ClientBatch) -> dict[date, list[TeradataClient]]:
    """Rows per delta file: each changed client once per day, in its end-of-day state."""
    by_day: dict[date, dict[str, TeradataClient]] = defaultdict(dict)
    for change in batch.changes:
        by_day[change.day][change.after.client_id] = change.after
    return {day: list(rows.values()) for day, rows in sorted(by_day.items())}


def write_clients(batch: ClientBatch, db_path: Path) -> None:
    """Replace CLNT with the snapshot and rewrite the CSV deltas; other tables are kept."""
    with write_transaction(db_path) as conn:
        replace_table(conn, "CLNT", TeradataClient, batch.snapshot, "CLNT_ID")

    written: set[Path] = set()
    for day, rows in delta_rows(batch).items():
        written.add(write_delta(db_path.parent, day, rows))
    for stale in db_path.parent.glob("client_*.csv"):
        if stale not in written:
            stale.unlink()


def write_delta(directory: Path, day: date, rows: Sequence[TeradataClient]) -> Path:
    """Write one day's ``client_YYYYMMDD.csv`` in the PLAN.md §6.2 text conventions."""
    path = directory / f"client_{day:%Y%m%d}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(column_names(TeradataClient))
        for row in rows:
            values = row.model_dump(by_alias=True, mode="python").values()
            writer.writerow("" if v is None else sql_value(v) for v in values)
    return path
