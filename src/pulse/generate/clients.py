"""Deterministic clean client source rows and daily Teradata-style deltas."""

from __future__ import annotations

import csv
import random
import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal

from pulse.contracts import column_names, columns
from pulse.contracts.enums import ClientStatus, Role, Segment
from pulse.contracts.sources import TeradataClient
from pulse.reference import OrgReference, fsa_province

DEFAULT_START = date(2024, 10, 7)
QUARTER_DAYS = 91
REASSIGN_RATE = 0.02
NEW_DAILY_RATE = 0.00002
CLOSE_DAILY_RATE = 0.00001
POSTAL_LETTERS = "ABCEGHJKLMNPRSTVWXYZ"

AdvisorAssignment = tuple[str, str, Role, date, date | None]
ChangeKind = Literal["NEW", "CLOSED", "REASSIGNED"]


@dataclass(frozen=True)
class ClientChange:
    day: date
    kind: ChangeKind
    before: TeradataClient | None
    after: TeradataClient


@dataclass(frozen=True)
class ClientBatch:
    clients: tuple[TeradataClient, ...]
    changes: tuple[ClientChange, ...]


def _updated_on(day: date) -> datetime:
    return datetime.combine(day, time(12), tzinfo=UTC)


def _count_at_rate(population: int, rate: float, rng: random.Random) -> int:
    expected = population * rate
    whole = int(expected)
    return whole + (rng.random() < expected - whole)


def _active_advisors(roster: Sequence[AdvisorAssignment], day: date) -> list[AdvisorAssignment]:
    return [
        assignment
        for assignment in roster
        if assignment[3] <= day and (assignment[4] is None or day < assignment[4])
    ]


def generate_clients(
    org: OrgReference,
    advisors: Sequence[AdvisorAssignment],
    *,
    seed: int,
    client_count: int = 150_000,
    start_date: date = DEFAULT_START,
    weeks: int = 104,
) -> ClientBatch:
    """Return the final CLNT master and changed rows for each simulation day."""
    if not 1 <= client_count < 100_000_000:
        raise ValueError("client_count must be between 1 and 99999999")
    if weeks < 1:
        raise ValueError("weeks must be positive")
    if not _active_advisors(advisors, start_date):
        raise ValueError("at least one active advisor is required at start_date")

    rng = random.Random(seed)
    placements = {p.branch.branch_id: p for p in org.placements()}
    for advisor_id, branch_id, _, valid_from, valid_to in advisors:
        if branch_id not in placements or (valid_to is not None and valid_to <= valid_from):
            raise ValueError(f"invalid advisor assignment for {advisor_id}")
    pools = {
        p.branch.branch_id: tuple(b.fsa_code for b in p.district.branches)
        for p in placements.values()
    }

    def make_client(
        client_id: str, assignment: AdvisorAssignment, since: date, updated: date
    ) -> TeradataClient:
        branch_id = assignment[1]
        branch_fsa = placements[branch_id].branch.fsa_code
        fsa = branch_fsa if rng.random() < 0.8 else rng.choice(pools[branch_id])
        postal = f"{fsa} {rng.randrange(10)}{rng.choice(POSTAL_LETTERS)}{rng.randrange(10)}"
        return TeradataClient(
            CLNT_ID=client_id,
            CLNT_SINCE_DT=since,
            BRTH_YR=rng.randint(1940, 1995),
            SEG_CD=rng.choices(list(Segment), weights=[60, 25, 10, 5])[0],
            PSTL_CD=postal,
            PROV_CD=fsa_province(fsa),
            PRIM_ADVSR_ID=assignment[0],
            PRIM_BRNCH_ID=branch_id,
            STAT_CD=ClientStatus.ACTIVE,
            LAST_UPD_TS=_updated_on(updated),
        )

    initial_advisors = _active_advisors(advisors, start_date)
    current: dict[str, TeradataClient] = {}
    active_ids: list[str] = []
    active_position: dict[str, int] = {}
    for number in range(1, client_count + 1):
        client_id = f"CLI-{number:08d}"
        since = start_date - timedelta(days=rng.randrange(3653))
        current[client_id] = make_client(client_id, rng.choice(initial_advisors), since, start_date)
        active_position[client_id] = len(active_ids)
        active_ids.append(client_id)

    changes: list[ClientChange] = []
    scheduled: dict[date, list[str]] = defaultdict(list)
    protected: set[str] = set()
    next_number = client_count + 1
    total_days = weeks * 7
    for offset in range(total_days):
        day = start_date + timedelta(days=offset)
        eligible = _active_advisors(advisors, day)
        if not eligible:
            raise ValueError(f"no active advisor on {day.isoformat()}")
        if offset % QUARTER_DAYS == 0:
            reassignment_count = _count_at_rate(len(active_ids), REASSIGN_RATE, rng)
            chosen = rng.sample(active_ids, min(len(active_ids), reassignment_count))
            protected = set(chosen)
            days_left = min(QUARTER_DAYS, total_days - offset)
            for client_id in chosen:
                scheduled[day + timedelta(days=rng.randrange(days_left))].append(client_id)

        new_today: set[str] = set()
        for _ in range(_count_at_rate(len(active_ids), NEW_DAILY_RATE, rng)):
            if next_number >= 100_000_000:
                raise ValueError("client ID space exhausted")
            client_id = f"CLI-{next_number:08d}"
            next_number += 1
            after = make_client(client_id, rng.choice(eligible), day, day)
            current[client_id] = after
            active_position[client_id] = len(active_ids)
            active_ids.append(client_id)
            new_today.add(client_id)
            changes.append(ClientChange(day, "NEW", None, after))

        for client_id in scheduled.pop(day, []):
            before = current[client_id]
            district_code = placements[before.primary_branch_id].district.district_code
            alternatives = [
                assignment
                for assignment in eligible
                if assignment[0] != before.primary_advisor_id
                and placements[assignment[1]].district.district_code == district_code
            ]
            if not alternatives:
                continue
            assignment = rng.choice(alternatives)
            after = before.model_copy(
                update={
                    "primary_advisor_id": assignment[0],
                    "primary_branch_id": assignment[1],
                    "last_updated_ts": _updated_on(day),
                }
            )
            current[client_id] = after
            changes.append(ClientChange(day, "REASSIGNED", before, after))

        for _ in range(_count_at_rate(len(active_ids), CLOSE_DAILY_RATE, rng)):
            if len(protected | new_today) >= len(active_ids):
                break
            client_id = rng.choice(active_ids)
            while client_id in protected or client_id in new_today:
                client_id = rng.choice(active_ids)
            before = current[client_id]
            after = before.model_copy(
                update={"status_code": ClientStatus.CLOSED, "last_updated_ts": _updated_on(day)}
            )
            current[client_id] = after
            changes.append(ClientChange(day, "CLOSED", before, after))
            index = active_position.pop(client_id)
            last = active_ids.pop()
            if index < len(active_ids):
                active_ids[index] = last
                active_position[last] = index

    return ClientBatch(clients=tuple(current.values()), changes=tuple(changes))


def write_clients(batch: ClientBatch, db_path: Path) -> None:
    """Replace CLNT and its daily CSV deltas without touching other SQLite tables."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fields = columns(TeradataClient)
    definitions = []
    for field in fields:
        python_type = field.python_type
        if issubclass(python_type, datetime):
            sql_type = "TIMESTAMP"
        elif issubclass(python_type, date):
            sql_type = "DATE"
        else:
            sql_type = "INTEGER" if issubclass(python_type, int) else "TEXT"
        definitions.append(f'"{field.name}" {sql_type}' + ("" if field.nullable else " NOT NULL"))
    definitions.append('PRIMARY KEY ("CLNT_ID")')
    names = column_names(TeradataClient)
    quoted = ", ".join(f'"{name}"' for name in names)
    placeholders = ", ".join("?" for _ in names)
    with sqlite3.connect(db_path) as conn:
        conn.execute("BEGIN")
        conn.execute('DROP TABLE IF EXISTS "CLNT"')
        conn.execute(f'CREATE TABLE "CLNT" ({", ".join(definitions)})')
        conn.executemany(
            f'INSERT INTO "CLNT" ({quoted}) VALUES ({placeholders})',
            (
                tuple(client.model_dump(by_alias=True, mode="json")[name] for name in names)
                for client in batch.clients
            ),
        )

    by_day: dict[date, list[TeradataClient]] = defaultdict(list)
    for change in batch.changes:
        by_day[change.day].append(change.after)
    written: set[Path] = set()
    for day, rows in sorted(by_day.items()):
        path = db_path.parent / f"client_{day:%Y%m%d}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=names, lineterminator="\n")
            writer.writeheader()
            writer.writerows(row.model_dump(by_alias=True, mode="json") for row in rows)
        written.add(path)
    for stale in db_path.parent.glob("client_*.csv"):
        if stale not in written:
            stale.unlink()
