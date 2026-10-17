"""Weekly and backfill generation: one ISO week of source extracts at a time.

Each week is a pure function of (seed, week, sizes) plus the first week generated into
this data directory, so generating W01..W08 one at a time writes the same bytes as a
backfill of W01..W08. A week writes only files that belong to it:

- ``snowflake/activity/extract_date=<Sunday>/part-NNN.parquet``, then defects (#15),
  which include the late arrivals (1–3 weeks back) and re-sent updates;
- ``teradata/client_YYYYMMDD.csv`` for each of its days with a client change;
- ``defects/YYYY-Www.json``.

``teradata/edw.sqlite`` is a database, not an extract: its HR tables hold their state as
of the week's Sunday (PLAN.md §6.2), and its CLNT snapshot is written once, by the first
week, as of the day before it. ``defects.json`` merges every week's manifest for the
runner's checks.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from pulse.contracts.defects import DefectManifest
from pulse.contracts.enums import AssignmentReason
from pulse.contracts.patterns import ISO_WEEK_ID
from pulse.contracts.sources import (
    TeradataAdvisor,
    TeradataAssignment,
    TeradataBranch,
    TeradataClient,
)
from pulse.generate.activity import generate_activity, write_activity
from pulse.generate.advisors import (
    DEFAULT_START,
    AdvisorRoster,
    assignment_ranges,
    generate_advisors,
)
from pulse.generate.clients import (
    QUARTER_DAYS,
    ClientBatch,
    delta_rows,
    generate_clients,
    write_delta,
)
from pulse.generate.dirt import inject_dirt
from pulse.generate.teradata import replace_table, write_transaction
from pulse.reference import org

SOURCES_DIR = "sources"
DEFECTS_DIR = "defects"
DEFECTS_FILE = "defects.json"
EDW = Path("teradata/edw.sqlite")
ACTIVITY = Path("snowflake/activity")
SEED_ENV = "PULSE_SEED"
DEFAULT_SEED = 20261013
DEFAULT_ADVISORS = 900
DEFAULT_CLIENTS = 150_000
# The roster and book generators are stable on a prefix only when their horizon ends on a
# client reassignment quarter, so the horizon grows in whole quarters.
HORIZON_STEP_WEEKS = QUARTER_DAYS // 7


@dataclass(frozen=True)
class World:
    """The seeded advisor roster and client book through the end of a horizon."""

    roster: AdvisorRoster
    clients: ClientBatch


@dataclass(frozen=True)
class Sizes:
    advisors: int = DEFAULT_ADVISORS
    clients: int = DEFAULT_CLIENTS


def default_seed() -> int:
    return int(os.environ.get(SEED_ENV) or DEFAULT_SEED)


def week_start(iso_week_id: str) -> date:
    if not re.fullmatch(ISO_WEEK_ID, iso_week_id):
        raise ValueError(f"Not an ISO week id: {iso_week_id!r} (expected e.g. 2026-W40)")
    year, week = iso_week_id.split("-W")
    monday = date.fromisocalendar(int(year), int(week), 1)
    if monday < DEFAULT_START:
        raise ValueError(f"{iso_week_id} is before the generator's first week, 2024-W41")
    return monday


def iso_week(day: date) -> str:
    calendar = day.isocalendar()
    return f"{calendar.year}-W{calendar.week:02d}"


def week_range(first: str, last: str) -> list[str]:
    start, end = week_start(first), week_start(last)
    if end < start:
        raise ValueError(f"--to {last} is before --from {first}")
    return [iso_week(start + timedelta(weeks=i)) for i in range((end - start).days // 7 + 1)]


def horizon_weeks(iso_week_id: str) -> int:
    """Weeks from DEFAULT_START through ``iso_week_id``, rounded up to whole quarters."""
    needed = (week_start(iso_week_id) - DEFAULT_START).days // 7 + 1
    return math.ceil(needed / HORIZON_STEP_WEEKS) * HORIZON_STEP_WEEKS


def build_world(seed: int, sizes: Sizes, through: str) -> World:
    weeks = horizon_weeks(through)
    roster = generate_advisors(org(), seed=seed, advisor_count=sizes.advisors, weeks=weeks)
    clients = generate_clients(
        org(), assignment_ranges(roster), seed=seed, client_count=sizes.clients, weeks=weeks
    )
    return World(roster, clients)


def roster_as_of(roster: AdvisorRoster, as_of: date) -> AdvisorRoster:
    """The HR tables as the EDW held them at the end of ``as_of``: assignment events up to
    that day, and each advisor hired by then with the role, TERM_DT and LAST_UPD_TS of
    their latest event. Branches do not change."""
    events = tuple(a for a in roster.assignments if a.effective_date <= as_of)
    latest: dict[str, TeradataAssignment] = {}
    for event in sorted(events, key=lambda e: (e.effective_date, e.assignment_id)):
        latest[event.advisor_id] = event
    advisors = tuple(
        advisor.model_copy(
            update={
                "role_code": latest[advisor.advisor_id].role_code,
                "term_date": latest[advisor.advisor_id].effective_date
                if latest[advisor.advisor_id].reason_code is AssignmentReason.TERM
                else None,
                "last_updated_ts": latest[advisor.advisor_id].last_updated_ts,
            }
        )
        for advisor in roster.advisors
        if advisor.advisor_id in latest
    )
    return AdvisorRoster(advisors=advisors, assignments=events, branches=roster.branches)


def clients_as_of(batch: ClientBatch, as_of: date) -> tuple[TeradataClient, ...]:
    """The CLNT table at the end of ``as_of``, in CLNT_ID order."""
    state = {client.client_id: client for client in batch.snapshot}
    for change in batch.changes:
        if change.day <= as_of:
            state[change.after.client_id] = change.after
    return tuple(state[key] for key in sorted(state))


def activity_dir(sources: Path, iso_week_id: str) -> Path:
    return sources / ACTIVITY / f"extract_date={week_start(iso_week_id) + timedelta(days=6)}"


def generate_week(
    data_dir: Path, iso_week_id: str, *, seed: int, world: World
) -> DefectManifest | None:
    """Write one week's extracts and defect manifest. Returns None if the week exists."""
    sources = data_dir / SOURCES_DIR
    monday = week_start(iso_week_id)
    sunday = monday + timedelta(days=6)
    partition = activity_dir(sources, iso_week_id)
    if partition.exists():
        return None
    edw = sources / EDW
    first_week = not edw.exists()
    hr = roster_as_of(world.roster, sunday)
    with write_transaction(edw) as con:
        replace_table(con, "ADVSR", TeradataAdvisor, hr.advisors, "ADVSR_ID")
        replace_table(con, "ADVSR_ASGN", TeradataAssignment, hr.assignments, "ASGN_ID")
        replace_table(con, "BRNCH", TeradataBranch, hr.branches, "BRNCH_ID")
        if first_week:
            snapshot = clients_as_of(world.clients, monday - timedelta(days=1))
            replace_table(con, "CLNT", TeradataClient, snapshot, "CLNT_ID")

    deltas = delta_rows(world.clients)
    for day in (monday + timedelta(days=i) for i in range(7)):
        if day in deltas:
            write_delta(edw.parent, day, deltas[day])
    rows = generate_activity(
        org(),
        assignment_ranges(world.roster),
        iso_week_id=iso_week_id,
        seed=seed,
        client_batch=world.clients,
    )
    write_activity(rows, sources, extract_date=sunday)
    manifest = inject_dirt(
        sources,
        data_dir / DEFECTS_DIR,
        iso_week_id=iso_week_id,
        seed=seed,
        include_client_snapshot=first_week,
        client_batch=world.clients,
        advisor_roster=world.roster,
    )
    merge_defects(data_dir)
    return manifest


def merge_defects(data_dir: Path) -> DefectManifest | None:
    """Write ``defects.json``: every weekly manifest in ``defects/``, weeks in order."""
    weekly = [
        DefectManifest.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted((data_dir / DEFECTS_DIR).glob("*.json"))
    ]
    if not weekly:
        return None
    merged = DefectManifest(
        generated_at=max(m.generated_at for m in weekly),
        seed=weekly[0].seed,
        iso_weeks=[week for m in weekly for week in m.iso_weeks],
        defects=[defect for m in weekly for defect in m.defects],
    )
    (data_dir / DEFECTS_FILE).write_text(merged.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return merged


def generate_weeks(
    data_dir: Path,
    weeks: list[str],
    *,
    seed: int,
    sizes: Sizes | None = None,
    echo: Callable[[str], None] = print,
) -> int:
    """Generate ``weeks`` in order; one world serves them all. Returns weeks written."""
    if not weeks:
        return 0
    world = build_world(seed, sizes or Sizes(), max(weeks))
    written = 0
    for week in weeks:
        manifest = generate_week(data_dir, week, seed=seed, world=world)
        if manifest is None:
            echo(f"{week}: already generated; left unchanged.")
            continue
        written += 1
        echo(f"{week}: generated with {len(manifest.defects)} recorded defects.")
    return written
