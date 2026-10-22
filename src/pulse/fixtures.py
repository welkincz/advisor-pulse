"""Tiny deterministic fixtures for every contract (issue #4).

Hand-designed, not produced by the generator: a 6-branch slice of the org (2 regions,
3 districts), 20 advisors, ~200 clients and 4 weeks of activity (2026-W37..W40), with
examples of every defect in PLAN.md §5. Ingestion, dbt, export and the web app build against
these files before the generator exists. ``make fixtures`` rebuilds them byte for byte.

Conventions the files follow (also in fixtures/README.md):

- Each weekly 'Snowflake' extract is taken Sunday 23:00 America/Toronto, so the extract's
  business week is the week it closes; a row is late when its activity week is earlier.
- A BOOKED appointment's ACTIVITY_TS is its booking time; when it resolves, the re-sent row
  carries the held (or due) time. SCHEDULED_TS never changes.
- edw.sqlite CLNT is the snapshot as of 2026-09-06 (end of W36); the CSV deltas carry every
  later client change. The HR tables (ADVSR, ADVSR_ASGN, BRNCH) hold their current state.
- Transfers, promotions and the termination take effect on Mondays, so an advisor has one
  branch per week. Activity by the unknown advisor is credited to the logged branch and kept
  out of advisor_weekly.

The export files are computed from the clean truth with straightforward Python versions of
the KPI rules in PLAN.md §7, so they are internally consistent (children sum to parents).
They are fixtures for consumers, not the reference implementation: dbt is.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import re
import shutil
import sqlite3
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from pulse.contracts import Contract, arrow_schema, columns, patterns
from pulse.contracts.defects import Defect, DefectKind, DefectManifest
from pulse.contracts.enums import (
    ActivityStatus,
    ActivityType,
    AssignmentReason,
    CheckSeverity,
    CheckStatus,
    DqAction,
    KpiCode,
    OrgLevel,
    Outcome,
    ProductLine,
    ReportFlag,
    Role,
    RunType,
    Segment,
    StageStatus,
)
from pulse.contracts.exports import (
    AdvisorWeekly,
    DqWeekly,
    ExportFile,
    GeoWeekly,
    Manifest,
    NarrativeBullet,
    NarrativeFact,
    NarrativeFile,
    NodeNarrative,
    OrgQuarterly,
    OrgWeekly,
    PipelineGraph,
    PortfolioWeekly,
    RunCheck,
    RunLogExport,
    RunSummary,
    StageAttempt,
    SummaryKpi,
    WatchItem,
    WeeklyReport,
)
from pulse.contracts.sources import (
    SnowflakeActivity,
    TeradataAdvisor,
    TeradataAssignment,
    TeradataBranch,
    TeradataClient,
    TeradataPortfolio,
    TeradataPortfolioAssignment,
)
from pulse.fiscal import quarter_bounds, week_fiscal_quarter_id, week_sunday, weeks_in_quarter
from pulse.reference import org

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
TORONTO = ZoneInfo("America/Toronto")
SEED = 4
WEEKS = ("2026-W37", "2026-W38", "2026-W39", "2026-W40")
BRANCH_IDS = ("BR-0101", "BR-0102", "BR-0201", "BR-0202", "BR-0501", "BR-0502")
SNAPSHOT_DATE = date(2026, 9, 6)
UNKNOWN_ADVISOR_ID = "ADV-09999"
NARRATIVE_MODEL = "claude-opus-5-5"
PROMPT_VERSION = "narrative-v1"
RUNNER_STAGES = (
    "restore_state",
    "generate",
    "ingest",
    "dbt_build",
    "checks",
    "narrate",
    "export",
    "publish_sheets",
    "persist_state",
    "release_lock",
)
APPOINTMENT_LIKE = {ActivityType.APPOINTMENT, ActivityType.REVIEW}
CONVERTING = {Outcome.PLAN_CREATED, Outcome.PRODUCT_OPENED}
LOWER_IS_BETTER = {KpiCode.NO_SHOW_RATE, KpiCode.LATE_RATE, KpiCode.QUAR_RATE}
LDU_LETTERS = "ABCEGHJKLMNPRSTVWXYZ"
ACTIVITY_DIR = "snowflake/activity"
TERADATA_DIR = "teradata"
SQLITE_NAME = "edw.sqlite"

# ── Time ─────────────────────────────────────────────────────────────────────


def week_start(week: str) -> date:
    year, number = week.split("-W")
    return date.fromisocalendar(int(year), int(number), 1)


def week_end(week: str) -> date:
    return week_start(week) + timedelta(days=6)


def iso_week(day: date) -> str:
    year, number, _ = day.isocalendar()
    return f"{year}-W{number:02d}"


def at(day: date, hour: int, minute: int = 0) -> datetime:
    """Toronto wall-clock time on ``day``, as UTC."""
    return datetime.combine(day, time(hour, minute), TORONTO).astimezone(UTC)


def local_date(ts: datetime) -> date:
    return ts.astimezone(TORONTO).date()


def extract_at(week: str) -> datetime:
    return at(week_end(week), 23)


WINDOW_START = week_start(WEEKS[0])
WINDOW_END = week_end(WEEKS[-1])


def _sql_ts(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


# ── Advisors and assignment events ───────────────────────────────────────────


@dataclass(frozen=True)
class Advisor:
    advisor_id: str
    name: str
    branch_id: str
    role: Role
    hire_date: date


@dataclass(frozen=True)
class Assignment:
    assignment_id: str
    advisor_id: str
    branch_id: str
    role: Role
    effective: date
    reason: AssignmentReason
    entered: datetime


_R = Role
ROSTER = (
    Advisor("ADV-10001", "Margaret Okafor", "BR-0101", _R.BRANCH_MANAGER, date(2011, 3, 14)),
    Advisor("ADV-10002", "Daniel Reyes", "BR-0101", _R.SENIOR_ADVISOR, date(2014, 6, 2)),
    Advisor("ADV-10003", "Priya Nair", "BR-0101", _R.ASSOCIATE, date(2019, 1, 21)),
    Advisor("ADV-10004", "Owen Fitzgerald", "BR-0101", _R.ADVISOR, date(2017, 9, 11)),
    Advisor("ADV-10005", "Helen Tran", "BR-0102", _R.BRANCH_MANAGER, date(2009, 5, 4)),
    Advisor("ADV-10006", "Marcus Bell", "BR-0102", _R.ADVISOR, date(2018, 2, 26)),
    Advisor("ADV-10007", "Sofia Marchetti", "BR-0102", _R.SENIOR_ADVISOR, date(2013, 10, 7)),
    Advisor("ADV-10008", "Liam O'Connor", "BR-0102", _R.ADVISOR, date(2020, 8, 17)),
    Advisor("ADV-10009", "Grace Whitfield", "BR-0201", _R.BRANCH_MANAGER, date(2010, 1, 11)),
    Advisor("ADV-10010", "Ethan Kowalski", "BR-0201", _R.ADVISOR, date(2016, 4, 18)),
    Advisor("ADV-10011", "Nadia Haddad", "BR-0202", _R.ADVISOR, date(2015, 7, 6)),
    Advisor("ADV-10012", "Robert Lam", "BR-0202", _R.BRANCH_MANAGER, date(2008, 11, 3)),
    Advisor("ADV-10013", "Chloe Bergeron", "BR-0202", _R.SENIOR_ADVISOR, date(2012, 3, 19)),
    Advisor("ADV-10014", "Samuel Ortiz", "BR-0202", _R.ADVISOR, date(2021, 5, 10)),
    Advisor("ADV-10015", "Isabelle Gagnon", "BR-0501", _R.BRANCH_MANAGER, date(2007, 9, 24)),
    Advisor("ADV-10016", "Mathieu Tremblay", "BR-0501", _R.SENIOR_ADVISOR, date(2011, 2, 7)),
    Advisor("ADV-10017", "Camille Roy", "BR-0501", _R.ASSOCIATE, date(2024, 1, 15)),
    Advisor("ADV-10018", "Julien Lefebvre", "BR-0502", _R.BRANCH_MANAGER, date(2006, 6, 12)),
    Advisor("ADV-10019", "Amélie Côté", "BR-0502", _R.ADVISOR, date(2016, 10, 3)),
    Advisor("ADV-10020", "Antoine Pelletier", "BR-0502", _R.ADVISOR, date(2019, 8, 26)),
)
ADVISORS = {a.advisor_id: a for a in ROSTER}


def portfolio_of(advisor_id: str) -> str:
    """Each book-owning advisor opens one portfolio: ADV-10014 holds PRT-010014."""
    return "PRT-0" + advisor_id[4:]


# Branch managers own no book. The leaver's portfolio is handed over on the TERM date, the
# same day its clients move in the 2026-09-28 delta; the two in-window transfers keep their
# portfolios at the old transit, which DQ025 reports.
PORTFOLIOS = {portfolio_of(a.advisor_id) for a in ROSTER if a.role is not _R.BRANCH_MANAGER}
HANDOVERS = (("ADV-10014", "ADV-10013", date(2026, 9, 28)),)

# (advisor, branch, role, effective, reason) after the HIRE events. The last four fall in the
# fixture window; the first two give SCD2 some older history.
_AR = AssignmentReason
LATER_EVENTS = (
    ("ADV-10003", "BR-0101", _R.ADVISOR, date(2022, 4, 4), _AR.PROMOTION),
    ("ADV-10011", "BR-0201", _R.ADVISOR, date(2023, 6, 5), _AR.TRANSFER),
    ("ADV-10008", "BR-0201", _R.ADVISOR, date(2026, 9, 14), _AR.TRANSFER),
    ("ADV-10004", "BR-0102", _R.ADVISOR, date(2026, 9, 21), _AR.TRANSFER),
    ("ADV-10017", "BR-0501", _R.ADVISOR, date(2026, 9, 28), _AR.PROMOTION),
    ("ADV-10014", "BR-0202", _R.ADVISOR, date(2026, 9, 28), _AR.TERM),
)
BLITZ_ADVISOR = ("ADV-10019", "2026-W40")  # an outbound-call push, so W40 has an ANOMALY


def _entered(effective: date) -> datetime:
    """In-window events are keyed in the Friday before; older ones on the day."""
    if effective >= WINDOW_START - timedelta(days=7):
        return at(effective - timedelta(days=3), 11)
    return at(effective, 9)


def build_assignments() -> list[Assignment]:
    raw = [(a.advisor_id, a.branch_id, a.role, a.hire_date, _AR.HIRE) for a in ROSTER]
    raw += list(LATER_EVENTS)
    raw.sort(key=lambda e: (e[3], e[0]))
    return [
        Assignment(f"ASG-{i:08d}", adv, branch, role, eff, reason, _entered(eff))
        for i, (adv, branch, role, eff, reason) in enumerate(raw, start=1)
    ]


# ── Clients ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Client:
    client_id: str
    since: date
    birth_year: int
    segment: Segment
    postal: str | None
    province: str
    advisor_id: str  # the book owner in the fixture world; the source row names only PRTF_ID
    branch_id: str
    status: str
    updated: datetime
    portfolio_id: str | None = None  # default: the advisor's own portfolio

    def source_row(self) -> dict[str, Any]:
        return {
            "CLNT_ID": self.client_id,
            "CLNT_SINCE_DT": self.since,
            "BRTH_YR": self.birth_year,
            "SEG_CD": self.segment.value,
            "PSTL_CD": self.postal,
            "PROV_CD": self.province,
            "PRIM_BRNCH_ID": self.branch_id,
            "STAT_CD": self.status,
            "LAST_UPD_TS": self.updated,
            "PRTF_ID": self.portfolio_id or portfolio_of(self.advisor_id),
        }


def normalize_postal(raw: str | None) -> str | None:
    """The staging rule (DQ011): strip, upper, drop space and hyphen, re-space, validate."""
    if raw is None:
        return None
    compact = raw.strip().upper().replace("-", "").replace(" ", "")
    candidate = f"{compact[:3]} {compact[3:]}"
    return candidate if re.fullmatch(patterns.POSTAL_CODE, candidate) else None


POSTAL_VARIANTS: tuple[tuple[str, Callable[[str], str | None]], ...] = (
    ("lowercase, no space", lambda p: p.lower().replace(" ", "")),
    ("hyphen", lambda p: p.replace(" ", "-")),
    ("trailing space", lambda p: p + " "),
    ("missing space", lambda p: p.replace(" ", "")),
    ("lowercase, leading space", lambda p: " " + p.lower()),
    ("US ZIP", lambda _p: "90210"),
    ("null", lambda _p: None),
    ("placeholder text", lambda _p: "N/A"),
)


@dataclass
class ClientDelta:
    """One client_YYYYMMDD.csv: rows as text, so malformed values survive."""

    file_date: date
    rows: list[dict[str, str]] = field(default_factory=list)
    notes: list[Defect | None] = field(default_factory=list)
    bom: bool = False
    quote_all: bool = False

    @property
    def name(self) -> str:
        return f"client_{self.file_date:%Y%m%d}.csv"

    def add(self, row: dict[str, str], note: Defect | None = None) -> None:
        self.rows.append(row)
        self.notes.append(note)


def _client_text(c: Client) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in c.source_row().items():
        if value is None:
            out[key] = ""
        elif isinstance(value, datetime):
            out[key] = _sql_ts(value)
        elif isinstance(value, date):
            out[key] = value.isoformat()
        else:
            out[key] = str(value)
    return out


# ── The world ────────────────────────────────────────────────────────────────


@dataclass
class SourceRow:
    values: dict[str, Any]
    defects: list[Defect] = field(default_factory=list)


@dataclass
class Activity:
    """The clean truth for one activity: its versions in time order (latest wins)."""

    versions: list[dict[str, Any]]
    unknown_advisor: bool = False

    @property
    def final(self) -> dict[str, Any]:
        return self.versions[-1]


@dataclass
class World:
    assignments: list[Assignment]
    snapshot: list[Client]
    deltas: list[ClientDelta]
    activities: list[Activity]
    extracts: dict[str, list[list[SourceRow]]]  # week → parts → rows
    defects: list[Defect]

    # ── as-of lookups ──

    def assignment_on(self, advisor_id: str, day: date) -> Assignment | None:
        """The advisor's assignment in force on ``day``; None before hire or after TERM."""
        current = None
        for a in self.assignments:
            if a.advisor_id == advisor_id and a.effective <= day:
                current = a
        return None if current is None or current.reason is _AR.TERM else current

    def branch_for_week(self, advisor_id: str, week: str) -> str | None:
        a = self.assignment_on(advisor_id, week_start(week))
        return a.branch_id if a else None

    def active_advisors(self, week: str) -> list[str]:
        """Active = employed at week start and not a branch manager (PLAN.md §7)."""
        out = []
        for advisor_id in ADVISORS:
            a = self.assignment_on(advisor_id, week_start(week))
            if a and a.role is not _R.BRANCH_MANAGER:
                out.append(advisor_id)
        return out

    def clients_as_of(self, ts: datetime) -> dict[str, Client]:
        state = {c.client_id: c for c in self.snapshot}
        for delta in self.deltas:
            for row, note in zip(delta.rows, delta.notes, strict=True):
                if note is not None and note.rule_id == "DQ005":
                    continue
                client = _parse_client(row, state.get(row["CLNT_ID"]))
                if client.updated <= ts:
                    state[client.client_id] = client
        return state


def holder_of(portfolio: str, day: date) -> str:
    """The portfolio's holder on ``day`` (int_portfolio_history): its opener, until a handover."""
    holder = "ADV-" + portfolio[5:]
    for old, new, handover in HANDOVERS:
        if portfolio == portfolio_of(old) and day >= handover:
            holder = new
    return holder


def _parse_client(row: dict[str, str], previous: Client | None) -> Client:
    """A client from its source row. The owner is the portfolio's holder on the update date;
    a portfolio the master lacks (DQ014) keeps the owner the world already had."""
    portfolio = row["PRTF_ID"]
    updated = datetime.strptime(row["LAST_UPD_TS"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    if portfolio in PORTFOLIOS:
        advisor_id = holder_of(portfolio, local_date(updated))
    elif previous is not None:
        advisor_id = previous.advisor_id
    else:
        raise ValueError(f"{row['CLNT_ID']} names unknown portfolio {portfolio} with no history")
    return Client(
        client_id=row["CLNT_ID"],
        since=date.fromisoformat(row["CLNT_SINCE_DT"]),
        birth_year=int(row["BRTH_YR"]),
        segment=Segment(row["SEG_CD"]),
        postal=row["PSTL_CD"] if row["PSTL_CD"] != "" else None,
        province=row["PROV_CD"],
        advisor_id=advisor_id,
        branch_id=row["PRIM_BRNCH_ID"],
        status=row["STAT_CD"],
        updated=updated,
        portfolio_id=portfolio,
    )


def _province(branch_id: str) -> str:
    return org().placement(branch_id).branch.province.value


def fsa_pool(branch_id: str) -> tuple[str, ...]:
    """Client FSAs for a branch: its own (twice as likely) or another branch's in the district.

    The same rule as the generator (#13), so every client FSA is a branch FSA with a boundary.
    """
    p = org().placement(branch_id)
    others = [b.fsa_code for b in p.district.branches if b.branch_id != branch_id][:2]
    return (p.branch.fsa_code, p.branch.fsa_code, *others)


def _postal(rng: random.Random, branch_id: str) -> str:
    fsa = rng.choice(fsa_pool(branch_id))
    return f"{fsa} {rng.randint(0, 9)}{rng.choice(LDU_LETTERS)}{rng.randint(0, 9)}"


def _defect(kind: DefectKind, week: str, source: str, table: str, file: str, **kw: Any) -> Defect:
    return Defect(kind=kind, iso_week_id=week, source=source, table_name=table, file=file, **kw)


class _Builder:
    def __init__(self) -> None:
        self.rng = random.Random(SEED)
        self.assignments = build_assignments()
        self.world = World(self.assignments, [], [], [], {}, [])
        self.next_activity = 0

    # ── clients ──

    def clients(self) -> None:
        rng = self.rng
        owners = [
            a
            for a in ADVISORS
            if (x := self.world.assignment_on(a, SNAPSHOT_DATE)) and x.role is not _R.BRANCH_MANAGER
        ]
        segments = [Segment.MASS] * 11 + [Segment.MASS_AFFLUENT] * 5
        segments += [Segment.AFFLUENT] * 3 + [Segment.SMALL_BUSINESS] * 1
        snapshot: list[Client] = []
        dirty = 0
        for n in range(1, 201):
            advisor_id = owners[(n * 5) % len(owners)]
            branch_id = self.world.branch_for_week(advisor_id, iso_week(SNAPSHOT_DATE)) or ""
            postal: str | None = _postal(rng, branch_id)
            client = Client(
                client_id=f"CLI-{n:08d}",
                since=date(rng.randint(2004, 2025), rng.randint(1, 12), rng.randint(1, 28)),
                birth_year=rng.randint(1942, 2003),
                segment=rng.choice(segments),
                postal=postal,
                province=_province(branch_id),
                advisor_id=advisor_id,
                branch_id=branch_id,
                status="C" if rng.random() < 0.04 else "A",
                updated=at(date(2026, rng.randint(1, 8), rng.randint(1, 28)), rng.randint(8, 17)),
            )
            if n % 12 == 5 and dirty < 16:  # 8% of the snapshot, two of each variant
                label, variant = POSTAL_VARIANTS[dirty % len(POSTAL_VARIANTS)]
                client = _replace(client, postal=variant(postal or ""))
                self._postal_defect(client, label, None)
                dirty += 1
            snapshot.append(client)
        self.world.snapshot = snapshot

    def _postal_defect(self, client: Client, label: str, delta: ClientDelta | None) -> None:
        """Snapshot rows (``delta`` None) load in the first week; SQLite rows have no number."""
        normalized = normalize_postal(client.postal)
        self.world.defects.append(
            _defect(
                DefectKind.DIRTY_POSTAL_CODE,
                WEEKS[0] if delta is None else iso_week(delta.file_date),
                "teradata",
                "CLNT",
                f"{TERADATA_DIR}/{SQLITE_NAME if delta is None else delta.name}",
                row=None if delta is None else len(delta.rows),
                natural_key=client.client_id,
                column="PSTL_CD",
                raw_value=client.postal,
                expected_value=normalized or "UNK",
                rule_id="DQ011",
                action=DqAction.NORMALIZE,
                detail=f"Postal code variant: {label}.",
            )
        )

    def deltas(self) -> None:
        w = self.world
        snap = {c.client_id: c for c in w.snapshot}
        d1 = ClientDelta(date(2026, 9, 9), bom=True, quote_all=True)
        d2 = ClientDelta(date(2026, 9, 13))
        d3 = ClientDelta(date(2026, 9, 20))  # header only: a day with no changes
        d4 = ClientDelta(date(2026, 9, 28))
        d5 = ClientDelta(date(2026, 10, 4))
        w.deltas = [d1, d2, d3, d4, d5]

        def stamp(delta: ClientDelta, minute: int) -> datetime:
            return at(delta.file_date, 9, minute)

        def new_client(n: int, advisor_id: str, delta: ClientDelta, postal: str) -> Client:
            branch = w.branch_for_week(advisor_id, iso_week(delta.file_date)) or ""
            return Client(
                f"CLI-{n:08d}",
                delta.file_date,
                1990 + n % 10,
                Segment.MASS,
                postal,
                _province(branch),
                advisor_id,
                branch,
                "A",
                stamp(delta, len(delta.rows)),
            )

        # d1: two new clients (one with a dirty postal code), a move, one malformed line.
        d1.add(_client_text(new_client(201, "ADV-10006", d1, "M6K 2B7")))
        dirty = new_client(202, "ADV-10019", d1, "h2x-1y4")
        self._postal_defect(dirty, "lowercase, hyphen", d1)
        d1.add(_client_text(dirty))
        mover = snap["CLI-00000010"]
        # DQ014: the mover's row names a portfolio the master lacks.
        moved = _replace(
            mover,
            postal=_postal(self.rng, mover.branch_id),
            updated=stamp(d1, 2),
            portfolio_id="PRT-899001",
        )
        moved_text = _client_text(moved)
        w.defects.append(
            _defect(
                DefectKind.UNKNOWN_PORTFOLIO,
                iso_week(d1.file_date),
                "teradata",
                "CLNT",
                f"{TERADATA_DIR}/{d1.name}",
                row=len(d1.rows),
                natural_key=moved.client_id,
                column="PRTF_ID",
                raw_value="PRT-899001",
                rule_id="DQ014",
                action=DqAction.MAP_UNKNOWN,
                detail="PRTF_ID is not in the portfolio master; mapped to Unknown.",
            )
        )
        d1.add(moved_text)
        bad = _client_text(_replace(snap["CLI-00000011"], updated=stamp(d1, 3)))
        bad["BRTH_YR"] = "19S2"
        d1.add(bad, self._dq005(d1, 3, "CLI-00000011", "BRTH_YR", "19S2"))

        # d2: one closure and one reassignment inside BR-0101.
        d2.add(_client_text(_replace(snap["CLI-00000020"], status="C", updated=stamp(d2, 0))))
        moved_client = next(
            c
            for c in w.snapshot
            if c.advisor_id == "ADV-10002" and c.status == "A" and c.client_id > "CLI-00000020"
        )
        self._reassign(d2, moved_client, "ADV-10003", "Book rebalanced inside BR-0101.")

        # d4: the terminated advisor's active book moves to a colleague on the TERM date.
        book = [c for c in w.snapshot if c.advisor_id == "ADV-10014" and c.status == "A"]
        for c in book:
            self._reassign(
                d4, c, "ADV-10013", "ADV-10014 terminated 2026-09-28.", portfolio_of("ADV-10014")
            )

        # d5: one new client, one reassignment, one malformed date.
        d5.add(_client_text(new_client(203, "ADV-10017", d5, "H3A 1B9")))
        other = next(c for c in w.snapshot if c.advisor_id == "ADV-10020" and c.status == "A")
        self._reassign(d5, other, "ADV-10019", "Client asked for a French-speaking advisor.")
        bad = _client_text(_replace(snap["CLI-00000030"], updated=stamp(d5, 9)))
        bad["CLNT_SINCE_DT"] = "2026-02-30"
        d5.add(bad, self._dq005(d5, len(d5.rows), "CLI-00000030", "CLNT_SINCE_DT", "2026-02-30"))

    def _dq005(self, delta: ClientDelta, row: int, key: str, column: str, raw: str) -> Defect:
        d = _defect(
            DefectKind.UNPARSEABLE_VALUE,
            iso_week(delta.file_date),
            "teradata",
            "CLNT",
            f"{TERADATA_DIR}/{delta.name}",
            row=row,
            natural_key=key,
            column=column,
            raw_value=raw,
            rule_id="DQ005",
            action=DqAction.QUARANTINE,
            detail=f"{column} does not parse.",
        )
        self.world.defects.append(d)
        return d

    def _reassign(
        self, delta: ClientDelta, client: Client, to: str, why: str, portfolio: str | None = None
    ) -> None:
        """Move a client to ``to``: into their portfolio, or with ``portfolio`` on a handover."""
        stamp = at(delta.file_date, 9, len(delta.rows))
        moved = _replace(client, advisor_id=to, updated=stamp, portfolio_id=portfolio)
        self.world.defects.append(
            _defect(
                DefectKind.CLIENT_REASSIGNMENT,
                iso_week(delta.file_date),
                "teradata",
                "CLNT",
                f"{TERADATA_DIR}/{delta.name}",
                row=len(delta.rows),
                natural_key=client.client_id,
                raw_value=client.advisor_id,
                expected_value=to,
                detail=f"{why} The book owner (the portfolio's holder) changes as of week end.",
            )
        )
        delta.add(_client_text(moved))

    # ── activities ──

    def _activity_id(self) -> str:
        self.next_activity += 1
        return (
            "ACT-"
            + hashlib.sha256(f"fixture-activity-{self.next_activity}".encode()).hexdigest()[:12]
        )

    def activities(self) -> None:
        w = self.world
        rng = self.rng
        for week in WEEKS:
            clients = w.clients_as_of(at(week_start(week), 0))
            for advisor_id in w.active_advisors(week):
                branch = w.branch_for_week(advisor_id, week) or ""
                book = sorted(
                    c.client_id
                    for c in clients.values()
                    if c.advisor_id == advisor_id and c.status == "A"
                )
                calls_out = rng.randint(5, 8)
                if (advisor_id, week) == BLITZ_ADVISOR:
                    calls_out = 16
                for _ in range(calls_out):
                    self._call(advisor_id, branch, week, ActivityType.CALL_OUT, book)
                for _ in range(rng.randint(1, 3)):
                    self._call(advisor_id, branch, week, ActivityType.CALL_IN, book)
                if book and rng.random() < 0.6:
                    self._review(advisor_id, branch, week, rng.choice(book))

    def _base(self, advisor_id: str, branch: str, kind: ActivityType) -> dict[str, Any]:
        return {
            "ACTIVITY_ID": self._activity_id(),
            "ADVISOR_ID": advisor_id,
            "CLIENT_ID": None,
            "BRANCH_ID": branch,
            "ACTIVITY_TYPE": kind.value,
            "CHANNEL": "PHONE",
            "STATUS": ActivityStatus.COMPLETED.value,
            "OUTCOME": None,
            "PRODUCT_LINE": None,
            "SCHEDULED_TS": None,
            "ACTIVITY_TS": None,
            "DURATION_MIN": None,
            "BOOKED_FROM_ACTIVITY_ID": None,
            "CREATED_TS": None,
            "UPDATED_TS": None,
        }

    def _call(
        self, advisor_id: str, branch: str, week: str, kind: ActivityType, book: list[str]
    ) -> None:
        rng = self.rng
        day = week_start(week) + timedelta(days=rng.randint(0, 4))
        ts = at(day, rng.randint(9, 16), rng.choice((0, 10, 20, 30, 40, 50)))
        row = self._base(advisor_id, branch, kind)
        prospecting = kind is ActivityType.CALL_OUT and rng.random() < 0.1
        client = None if prospecting or not book else rng.choice(book)
        duration = rng.randint(3, 25) if kind is ActivityType.CALL_OUT else rng.randint(4, 20)
        outcome = rng.choices(
            [Outcome.NONE, Outcome.FOLLOW_UP, Outcome.REFERRAL], weights=[6, 3, 1]
        )[0]
        row.update(
            CLIENT_ID=client,
            ACTIVITY_TS=ts,
            DURATION_MIN=duration,
            CREATED_TS=ts,
            UPDATED_TS=ts + timedelta(minutes=duration + 2),
            OUTCOME=outcome.value,
        )
        books = kind is ActivityType.CALL_OUT and client is not None and rng.random() < 0.25
        if books:
            row["OUTCOME"] = Outcome.FOLLOW_UP.value
        self.world.activities.append(Activity([row]))
        if books:
            self._appointment(row, rng.choice((1, 1, 2, 2, 3, 6)))

    def _appointment(self, call: dict[str, Any], days_ahead: int) -> None:
        rng = self.rng
        day = local_date(call["ACTIVITY_TS"]) + timedelta(days=days_ahead)
        if day.weekday() >= 5:
            day += timedelta(days=7 - day.weekday())
        term = next(
            (
                a.effective
                for a in self.assignments
                if a.advisor_id == call["ADVISOR_ID"] and a.reason is _AR.TERM
            ),
            None,
        )
        if term is not None and day >= term:
            return
        created = call["UPDATED_TS"]
        booked = self._base(call["ADVISOR_ID"], call["BRANCH_ID"], ActivityType.APPOINTMENT)
        booked.update(
            CLIENT_ID=call["CLIENT_ID"],
            CHANNEL=rng.choices(["IN_BRANCH", "VIDEO", "PHONE"], weights=[6, 3, 1])[0],
            STATUS=ActivityStatus.BOOKED.value,
            SCHEDULED_TS=at(day, rng.randint(9, 16)),
            ACTIVITY_TS=created,
            CREATED_TS=created,
            UPDATED_TS=created,
            BOOKED_FROM_ACTIVITY_ID=call["ACTIVITY_ID"],
        )
        self._resolve(booked, (72, 15, 13), (30, 25, 30, 15), 30, 75)

    def _review(self, advisor_id: str, branch: str, week: str, client: str) -> None:
        rng = self.rng
        day = week_start(week) + timedelta(days=rng.randint(0, 4))
        created = at(day - timedelta(days=rng.choice((3, 4, 9, 30))), 11, rng.choice((5, 25, 45)))
        booked = self._base(advisor_id, branch, ActivityType.REVIEW)
        booked.update(
            CLIENT_ID=client,
            CHANNEL=rng.choices(["IN_BRANCH", "VIDEO"], weights=[7, 3])[0],
            STATUS=ActivityStatus.BOOKED.value,
            SCHEDULED_TS=at(day, rng.randint(9, 16)),
            ACTIVITY_TS=created,
            CREATED_TS=created,
            UPDATED_TS=created,
        )
        self._resolve(booked, (85, 10, 5), (35, 20, 30, 15), 45, 90)

    def _resolve(
        self,
        booked: dict[str, Any],
        status_weights: tuple[int, int, int],
        outcome_weights: tuple[int, int, int, int],
        min_minutes: int,
        max_minutes: int,
    ) -> None:
        """Add the final version of a booked meeting, if it resolves inside the window."""
        rng = self.rng
        scheduled: datetime = booked["SCHEDULED_TS"]
        versions = [booked]
        if local_date(scheduled) <= WINDOW_END:
            status = rng.choices(
                [ActivityStatus.COMPLETED, ActivityStatus.NO_SHOW, ActivityStatus.CANCELLED],
                weights=status_weights,
            )[0]
            final = dict(booked, STATUS=status.value)
            if status is ActivityStatus.COMPLETED:
                minutes = rng.randint(min_minutes, max_minutes)
                outcome = rng.choices(
                    [Outcome.PLAN_CREATED, Outcome.PRODUCT_OPENED, Outcome.FOLLOW_UP, Outcome.NONE],
                    weights=outcome_weights,
                )[0]
                final.update(
                    ACTIVITY_TS=scheduled,
                    DURATION_MIN=minutes,
                    OUTCOME=outcome.value,
                    UPDATED_TS=scheduled + timedelta(minutes=minutes + 15),
                    PRODUCT_LINE=rng.choice(list(ProductLine)).value
                    if outcome in CONVERTING
                    else None,
                )
            elif status is ActivityStatus.NO_SHOW:
                final.update(ACTIVITY_TS=scheduled, UPDATED_TS=scheduled + timedelta(minutes=30))
            else:
                cancel = max(
                    booked["CREATED_TS"] + timedelta(hours=3), scheduled - timedelta(days=1)
                )
                final.update(ACTIVITY_TS=cancel, UPDATED_TS=cancel)
            versions.append(final)
        self.world.activities.append(Activity(versions))

    # ── extracts and their dirt ──

    def extracts(self) -> None:
        w = self.world
        rng = self.rng
        delivered: dict[str, str] = {}  # activity_id → late delivery week
        late_plan = (
            ("2026-W37", "2026-W38", 2),
            ("2026-W37", "2026-W40", 1),
            ("2026-W38", "2026-W40", 2),
            ("2026-W38", "2026-W39", 1),
            ("2026-W39", "2026-W40", 2),
        )
        for origin, target, count in late_plan:
            candidates = sorted(
                a.final["ACTIVITY_ID"]
                for a in w.activities
                if len(a.versions) == 1
                and a.final["ACTIVITY_TYPE"] == "CALL_IN"
                and iso_week(local_date(a.final["UPDATED_TS"])) == origin
                and a.final["ACTIVITY_ID"] not in delivered
            )
            for activity_id in rng.sample(candidates, count):
                delivered[activity_id] = target

        by_week: dict[str, list[SourceRow]] = {week: [] for week in WEEKS}
        for act in w.activities:
            sent: dict[str, Any] | None = None
            for week in WEEKS:
                in_week = [
                    v
                    for v in act.versions
                    if iso_week(local_date(v["UPDATED_TS"])) == week
                    and v["UPDATED_TS"] <= extract_at(week)
                ]
                if not in_week:
                    continue
                version = in_week[-1]
                target = delivered.get(version["ACTIVITY_ID"], week)
                row = SourceRow(dict(version, _EXTRACTED_AT=extract_at(target)))
                if target != week:
                    weeks_late = WEEKS.index(target) - WEEKS.index(week)
                    row.defects.append(
                        self._row_defect(
                            DefectKind.LATE_ARRIVING,
                            target,
                            version,
                            expected_value=week,
                            action=DqAction.KEEP_FLAGGED,
                            detail=f"Delivered {weeks_late} week(s) late; is_late_arriving = true.",
                        )
                    )
                if sent is not None:
                    row.defects.append(
                        self._row_defect(
                            DefectKind.RESENT_UPDATE,
                            target,
                            version,
                            column="STATUS",
                            raw_value=sent["STATUS"],
                            expected_value=version["STATUS"],
                            rule_id="DQ010",
                            action=DqAction.DEDUPE,
                            detail="Re-sent with a newer UPDATED_TS; the latest version wins.",
                        )
                    )
                by_week[target].append(row)
                sent = version

        for week in WEEKS:
            rows = sorted(
                by_week[week], key=lambda r: (r.values["UPDATED_TS"], r.values["ACTIVITY_ID"])
            )
            parts = (
                [rows] if week != WEEKS[-1] else [rows[: len(rows) // 2], rows[len(rows) // 2 :]]
            )
            w.extracts[week] = parts
        self._inject()

    def _row_defect(self, kind: DefectKind, week: str, values: dict[str, Any], **kw: Any) -> Defect:
        # file and row are filled in once the part files are laid out.
        return _defect(
            kind, week, "snowflake", "activity", "pending", natural_key=values["ACTIVITY_ID"], **kw
        )

    def _inject(self) -> None:
        """Exact duplicates, quarantine-worthy rows and one unknown advisor, per week."""
        rng = self.rng
        q = DqAction.QUARANTINE
        plan: dict[str, list[tuple[int, str, Any, DefectKind, str, str]]] = {
            # (part, column, value, kind, rule, detail)
            "2026-W37": [
                (
                    0,
                    "ACTIVITY_ID",
                    None,
                    DefectKind.NULL_ACTIVITY_ID,
                    "DQ001",
                    "ACTIVITY_ID is null.",
                ),
                (
                    0,
                    "ACTIVITY_TYPE",
                    "EMAIL",
                    DefectKind.INVALID_ENUM,
                    "DQ002",
                    "ACTIVITY_TYPE is not in the contract.",
                ),
            ],
            "2026-W38": [
                (
                    0,
                    "STATUS",
                    "PENDING",
                    DefectKind.INVALID_ENUM,
                    "DQ002",
                    "STATUS is not in the contract.",
                ),
                (
                    0,
                    "DURATION_MIN",
                    -15,
                    DefectKind.DURATION_OUT_OF_RANGE,
                    "DQ003",
                    "DURATION_MIN is negative.",
                ),
            ],
            "2026-W39": [
                (
                    0,
                    "OUTCOME",
                    "SOLD",
                    DefectKind.INVALID_ENUM,
                    "DQ002",
                    "OUTCOME is not in the contract.",
                ),
                (
                    0,
                    "ACTIVITY_TS",
                    datetime(2014, 6, 2, 14, 0, tzinfo=UTC),
                    DefectKind.ACTIVITY_TS_OUT_OF_RANGE,
                    "DQ004",
                    "ACTIVITY_TS is before 2015.",
                ),
            ],
            "2026-W40": [
                (
                    0,
                    "CHANNEL",
                    "CHAT",
                    DefectKind.INVALID_ENUM,
                    "DQ002",
                    "CHANNEL is not in the contract.",
                ),
                (
                    1,
                    "ACTIVITY_TS",
                    extract_at("2026-W40") + timedelta(days=3),
                    DefectKind.ACTIVITY_TS_OUT_OF_RANGE,
                    "DQ004",
                    "ACTIVITY_TS is more than a day after _EXTRACTED_AT.",
                ),
            ],
        }
        for week, parts in self.world.extracts.items():
            for part_no, column, value, kind, rule, detail in plan[week]:
                rows = parts[part_no]
                template = self._completed_call(rows)
                values = dict(template.values, ACTIVITY_ID=self._activity_id())
                values[column] = value
                raw = value.isoformat() if isinstance(value, datetime) else value
                note = self._row_defect(
                    kind,
                    week,
                    values,
                    column=column,
                    raw_value=None if raw is None else str(raw),
                    rule_id=rule,
                    action=q,
                    detail=detail,
                )
                rows.insert(rng.randint(0, len(rows)), SourceRow(values, [note]))
            if week != "2026-W38":  # exact duplicates in three of four weeks
                rows = parts[-1]
                original = self._completed_call(rows)
                copy = SourceRow(
                    dict(original.values),
                    [
                        self._row_defect(
                            DefectKind.EXACT_DUPLICATE,
                            week,
                            original.values,
                            rule_id="DQ010",
                            action=DqAction.DEDUPE,
                            detail="Exact copy of another row in the same file.",
                        )
                    ],
                )
                rows.insert(rng.randint(rows.index(original) + 1, len(rows)), copy)
        # One activity logged under an advisor ID that is not in the master.
        rows = self.world.extracts["2026-W39"][0]
        template = self._completed_call(rows, branch="BR-0501")
        values = dict(
            template.values, ACTIVITY_ID=self._activity_id(), ADVISOR_ID=UNKNOWN_ADVISOR_ID
        )
        note = self._row_defect(
            DefectKind.UNKNOWN_ADVISOR,
            "2026-W39",
            values,
            column="ADVISOR_ID",
            raw_value=UNKNOWN_ADVISOR_ID,
            expected_value="UNKNOWN",
            rule_id="DQ012",
            action=DqAction.MAP_UNKNOWN,
            detail="Kept; mapped to the Unknown advisor member and credited to BRANCH_ID.",
        )
        rows.insert(rows.index(template) + 1, SourceRow(values, [note]))
        self.world.activities.append(Activity([dict(values)], unknown_advisor=True))

    def _completed_call(self, rows: list[SourceRow], branch: str | None = None) -> SourceRow:
        candidates = [
            r
            for r in rows
            if not r.defects
            and r.values["ACTIVITY_TYPE"] == "CALL_OUT"
            and r.values["CLIENT_ID"] is not None
            and (branch is None or r.values["BRANCH_ID"] == branch)
        ]
        return self.rng.choice(candidates)

    def hr_defects(self) -> None:
        kinds = {
            _AR.TRANSFER: DefectKind.ADVISOR_TRANSFER,
            _AR.PROMOTION: DefectKind.ADVISOR_PROMOTION,
            _AR.TERM: DefectKind.ADVISOR_TERM,
        }
        for a in self.assignments:
            if a.effective < WINDOW_START or a.reason not in kinds:
                continue
            prior = self.world.assignment_on(a.advisor_id, a.effective - timedelta(days=1))
            assert prior is not None
            change = {
                _AR.TRANSFER: (prior.branch_id, a.branch_id),
                _AR.PROMOTION: (prior.role.value, a.role.value),
                _AR.TERM: (prior.branch_id, None),
            }[a.reason]
            self.world.defects.append(
                _defect(
                    kinds[a.reason],
                    iso_week(a.effective),
                    "teradata",
                    "ADVSR_ASGN",
                    f"{TERADATA_DIR}/{SQLITE_NAME}",
                    natural_key=a.assignment_id,
                    column="ROLE_CD" if a.reason is _AR.PROMOTION else "BRNCH_ID",
                    raw_value=change[0],
                    expected_value=change[1],
                    detail=f"{a.advisor_id} {a.reason.value} effective {a.effective}; "
                    "SCD2 closes the prior range, activity credits the as-of branch.",
                )
            )

    def build(self) -> World:
        self.clients()
        self.deltas()
        self.activities()
        self.extracts()
        self.hr_defects()
        return self.world


def _replace(c: Client, **changes: Any) -> Client:
    return Client(**{**c.__dict__, **changes})


def build_world() -> World:
    return _Builder().build()


def activity_part_path(week: str, part: int) -> str:
    return f"{ACTIVITY_DIR}/extract_date={week_end(week).isoformat()}/part-{part:03d}.parquet"


def finalize_defects(world: World) -> list[Defect]:
    """Every defect with its file and row, in a stable order."""
    out = [d for d in world.defects]
    for week, parts in world.extracts.items():
        for part_no, rows in enumerate(parts):
            path = activity_part_path(week, part_no)
            for i, r in enumerate(rows):
                out += [d.model_copy(update={"file": path, "row": i}) for d in r.defects]
    for delta in world.deltas:
        for i, note in enumerate(delta.notes):
            if note is not None:
                assert note.row == i, (delta.name, i)
    return sorted(
        out,
        key=lambda d: (
            d.iso_week_id,
            d.file,
            -1 if d.row is None else d.row,
            d.kind.value,
            d.natural_key or "",
        ),
    )


# ── Marts (clean truth → exports) ────────────────────────────────────────────


@dataclass
class Scope:
    """Activities, portfolio clients and advisors for one advisor or org node in one week."""

    week: str
    acts: list[dict[str, Any]]
    active_advisors: int
    portfolio: set[str] = field(default_factory=set)  # active clients in its portfolios
    contacted_12m: set[str] = field(default_factory=set)
    window_complete: bool = False


def _parts(s: Scope) -> dict[str, Any]:
    """The additive parts behind every KPI for one scope (week), plus the clients contacted."""

    def in_week(ts: datetime | None) -> bool:
        return ts is not None and iso_week(local_date(ts)) == s.week

    completed = [a for a in s.acts if a["STATUS"] == "COMPLETED" and in_week(a["ACTIVITY_TS"])]
    meetings = [a for a in s.acts if a["ACTIVITY_TYPE"] in APPOINTMENT_LIKE]
    scheduled = [a for a in meetings if in_week(a["SCHEDULED_TS"])]
    held = [a for a in scheduled if a["STATUS"] == "COMPLETED"]
    held_meetings = [a for a in completed if a["ACTIVITY_TYPE"] in APPOINTMENT_LIKE]
    booked = [a for a in meetings if in_week(a["CREATED_TS"])]
    minutes = [a["DURATION_MIN"] for a in held_meetings]
    return {
        "active_advisors": s.active_advisors,
        "activities_completed": len(completed),
        "calls_out": sum(a["ACTIVITY_TYPE"] == "CALL_OUT" for a in completed),
        "calls_in": sum(a["ACTIVITY_TYPE"] == "CALL_IN" for a in completed),
        "appointments_booked": len(booked),
        "booked_from_call": sum(a["BOOKED_FROM_ACTIVITY_ID"] is not None for a in booked),
        "appointments_held": len(held),
        "no_shows": sum(a["STATUS"] == "NO_SHOW" for a in scheduled),
        "conversions": sum(a["OUTCOME"] in CONVERTING for a in held),
        "clients": {a["CLIENT_ID"] for a in completed if a["CLIENT_ID"]},
        "portfolio_clients": len(s.portfolio),
        "portfolio_contacted_12m": len(s.portfolio & s.contacted_12m),
        "meeting_minutes": sum(minutes),
        "meetings_held": len(minutes),
    }


def _rates(p: dict[str, Any], advisors: int) -> dict[str, Any]:
    """Every ratio from its summed parts, as mart_org_weekly and mart_org_quarterly do."""
    return {
        "avg_meeting_duration_min": _ratio(p["meeting_minutes"], p["meetings_held"], 2),
        "activities_per_advisor": _ratio(p["activities_completed"], advisors, 2),
        "show_rate": _ratio(p["appointments_held"], p["appointments_held"] + p["no_shows"]),
        "conversion_rate": _ratio(p["conversions"], p["appointments_held"]),
        "call_to_appt_rate": _ratio(p["booked_from_call"], p["calls_out"]),
    }


_COUNTS = (
    "activities_completed", "calls_out", "calls_in", "appointments_booked", "appointments_held",
    "no_shows", "conversions",
)  # fmt: skip


def _measures(s: Scope) -> dict[str, Any]:
    p = _parts(s)
    return {
        "active_advisors": s.active_advisors,
        **{k: p[k] for k in _COUNTS},
        "unique_clients_contacted": len(p["clients"]),
        **_rates(p, s.active_advisors),
        "portfolio_clients": p["portfolio_clients"],
        "portfolio_contacted_12m": p["portfolio_contacted_12m"],
        "portfolio_contacted_rate_12m": _ratio(p["portfolio_contacted_12m"], p["portfolio_clients"])
        if s.window_complete
        else None,
    }


def _ratio(num: float, den: float, digits: int = 4) -> float | None:
    return round(num / den, digits) if den else None


@dataclass(frozen=True)
class Node:
    level: OrgLevel
    node_id: str
    name: str
    parent_id: str | None
    branches: frozenset[str]


def org_nodes() -> list[Node]:
    o = org()
    placements = [o.placement(b) for b in BRANCH_IDS]
    nodes = [
        Node(OrgLevel.NATIONAL, o.national.node_id, o.national.name, None, frozenset(BRANCH_IDS))
    ]
    for region in dict.fromkeys(p.region for p in placements):
        nodes.append(
            Node(
                OrgLevel.REGION,
                region.region_code.value,
                region.region_name,
                o.national.node_id,
                frozenset(p.branch.branch_id for p in placements if p.region == region),
            )
        )
    for district in dict.fromkeys(p.district for p in placements):
        nodes.append(
            Node(
                OrgLevel.DISTRICT,
                district.district_code,
                district.district_name,
                o.region_of(district.district_code).region_code.value,
                frozenset(p.branch.branch_id for p in placements if p.district == district),
            )
        )
    for p in placements:
        nodes.append(
            Node(
                OrgLevel.BRANCH,
                p.branch.branch_id,
                p.branch.branch_name,
                p.district.district_code,
                frozenset({p.branch.branch_id}),
            )
        )
    return nodes


class Marts:
    def __init__(self, world: World) -> None:
        self.world = world
        self.nodes = org_nodes()
        self.acts = [a.final for a in world.activities]
        self.unknown = {a.final["ACTIVITY_ID"] for a in world.activities if a.unknown_advisor}
        self.books = {w: world.clients_as_of(at(week_end(w), 23, 59)) for w in WEEKS}

    def credited_branch(self, act: dict[str, Any], week: str) -> str:
        if act["ACTIVITY_ID"] in self.unknown:
            return str(act["BRANCH_ID"])
        return self.world.branch_for_week(act["ADVISOR_ID"], week) or str(act["BRANCH_ID"])

    def holder(self, portfolio: str, week: str) -> str:
        """The portfolio's holder on the week-end date (int_portfolio_history)."""
        return holder_of(portfolio, week_end(week))

    def transit(self, portfolio: str) -> str:
        advisor = "ADV-" + portfolio[5:]
        return (self.world.assignment_on(advisor, SNAPSHOT_DATE) or ADVISORS[advisor]).branch_id

    def portfolio_book(self, week: str) -> dict[str, str]:
        """Active clients in a known portfolio at week end -> that portfolio (DQ014 excluded)."""
        return {
            c.client_id: portfolio
            for c in self.books[week].values()
            if c.status == "A" and (portfolio := c.source_row()["PRTF_ID"]) in PORTFOLIOS
        }

    def contacted_12m(self, week: str) -> set[str]:
        end = week_end(week)
        start = end.replace(year=end.year - 1)  # the window is (start, end]
        return {
            a["CLIENT_ID"]
            for a in self.acts
            if a["CLIENT_ID"]
            and a["STATUS"] == "COMPLETED"
            and start < local_date(a["ACTIVITY_TS"]) <= end
        }

    def window_complete(self, week: str) -> bool:
        first = min(local_date(a["ACTIVITY_TS"]) for a in self.acts if a["STATUS"] == "COMPLETED")
        end = week_end(week)
        return end.replace(year=end.year - 1) >= first

    def advisor_weekly(self) -> list[dict[str, Any]]:
        rows = []
        for week in WEEKS:
            portfolios = self.portfolio_book(week)
            reached, complete = self.contacted_12m(week), self.window_complete(week)
            for advisor_id in self.world.active_advisors(week):
                branch = self.world.branch_for_week(advisor_id, week) or ""
                place = org().placement(branch)
                m = _measures(
                    Scope(
                        week,
                        [
                            a
                            for a in self.acts
                            if a["ADVISOR_ID"] == advisor_id
                            and a["ACTIVITY_ID"] not in self.unknown
                        ],
                        1,
                        {c for c, p in portfolios.items() if self.holder(p, week) == advisor_id},
                        reached,
                        complete,
                    )
                )
                for k in (
                    "active_advisors",
                    "activities_per_advisor",
                    "show_rate",
                    "conversion_rate",
                    "call_to_appt_rate",
                ):
                    m.pop(k)
                rows.append(
                    {
                        "iso_week_id": week,
                        "advisor_id": advisor_id,
                        "branch_id": branch,
                        "district_code": place.district.district_code,
                        "region_code": place.region.region_code.value,
                        **m,
                    }
                )
        return rows

    def org_weekly(self) -> list[dict[str, Any]]:
        rows = []
        for week in WEEKS:
            active = self.world.active_advisors(week)
            portfolios = self.portfolio_book(week)
            reached, complete = self.contacted_12m(week), self.window_complete(week)
            for node in self.nodes:
                advisors = [
                    a for a in active if self.world.branch_for_week(a, week) in node.branches
                ]
                acts = [a for a in self.acts if self.credited_branch(a, week) in node.branches]
                in_node = {c for c, p in portfolios.items() if self.transit(p) in node.branches}
                m = _measures(
                    Scope(
                        week,
                        acts,
                        len(advisors),
                        in_node,
                        reached,
                        complete,
                    )
                )
                rows.append(
                    {
                        "iso_week_id": week,
                        "level": node.level.value,
                        "node_id": node.node_id,
                        "node_name": node.name,
                        "parent_id": node.parent_id,
                        **m,
                    }
                )
        return rows

    def org_quarterly(self) -> list[dict[str, Any]]:
        """The fiscal-quarter mart: flows summed, clients distinct over the quarter, stocks at
        the last reported week, ratios rebuilt from parts (mart_org_quarterly)."""
        rows = []
        by_quarter: dict[str, list[str]] = {}
        for week in WEEKS:
            by_quarter.setdefault(week_fiscal_quarter_id(week), []).append(week)
        for quarter, weeks in by_quarter.items():
            start, end = quarter_bounds(week_sunday(weeks[0]))
            for node in self.nodes:
                parts = []
                for week in weeks:
                    active = self.world.active_advisors(week)
                    advisors = [
                        a for a in active if self.world.branch_for_week(a, week) in node.branches
                    ]
                    acts = [a for a in self.acts if self.credited_branch(a, week) in node.branches]
                    in_node = {
                        c
                        for c, p in self.portfolio_book(week).items()
                        if self.transit(p) in node.branches
                    }
                    parts.append(
                        _parts(
                            Scope(
                                week,
                                acts,
                                len(advisors),
                                in_node,
                                self.contacted_12m(week),
                            )
                        )
                    )
                total = {
                    k: sum(p[k] for p in parts)
                    for k in (*_COUNTS, "booked_from_call", "meeting_minutes", "meetings_held")
                }
                advisor_weeks = sum(p["active_advisors"] for p in parts)
                last = parts[-1]
                rows.append(
                    {
                        "fiscal_quarter_id": quarter,
                        "fiscal_year": 2000 + int(quarter[2:4]),
                        "fiscal_quarter": int(quarter[-1]),
                        "quarter_start": start,
                        "quarter_end": end,
                        "first_week": weeks[0],
                        "last_week": weeks[-1],
                        "weeks_reported": len(weeks),
                        "weeks_in_quarter": weeks_in_quarter(quarter),
                        "is_complete": len(weeks) == weeks_in_quarter(quarter),
                        "level": node.level.value,
                        "node_id": node.node_id,
                        "node_name": node.name,
                        "parent_id": node.parent_id,
                        "advisor_weeks": advisor_weeks,
                        **{k: total[k] for k in _COUNTS},
                        "booked_from_call": total["booked_from_call"],
                        "unique_clients_contacted": len(
                            set().union(*(p["clients"] for p in parts))
                        ),
                        **_rates(total, advisor_weeks),
                        "portfolio_clients": last["portfolio_clients"],
                        "portfolio_contacted_12m": last["portfolio_contacted_12m"],
                        "portfolio_contacted_rate_12m": _ratio(
                            last["portfolio_contacted_12m"], last["portfolio_clients"]
                        )
                        if self.window_complete(weeks[-1])
                        else None,
                    }
                )
        return rows

    def batch_stats(self) -> dict[str, dict[str, int]]:
        """Per weekly ingest: activity rows read, quarantined, late; client rows read."""
        stats: dict[str, dict[str, int]] = {}
        for week, parts in self.world.extracts.items():
            rows = [r for p in parts for r in p]
            kinds = Counter(d.rule_id for r in rows for d in r.defects)
            late = sum(any(d.kind is DefectKind.LATE_ARRIVING for d in r.defects) for r in rows)
            quarantined = sum(kinds[f"DQ00{n}"] for n in range(1, 5))
            stats[week] = {
                "activity_rows": len(rows),
                "quarantined": quarantined,
                "late": late,
                "dedupe": kinds["DQ010"],
                "unknown_advisor": kinds["DQ012"],
                "client_rows": 0,
                "client_quarantined": 0,
            }
        stats[WEEKS[0]]["client_rows"] += len(self.world.snapshot)
        for delta in self.world.deltas:
            s = stats[iso_week(delta.file_date)]
            s["client_rows"] += len(delta.rows)
            s["client_quarantined"] += sum(
                n is not None and n.rule_id == "DQ005" for n in delta.notes
            )
        stats[WEEKS[0]]["hr_rows"] = len(ROSTER) + len(self.world.assignments) + len(BRANCH_IDS)
        return stats

    def weekly_report(self, org_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        value_of: dict[KpiCode, Callable[[dict[str, Any]], float | None]] = {
            KpiCode.PRTF_CONTACT_12M: lambda r: r["portfolio_contacted_rate_12m"],
            KpiCode.ACT_PER_ADV: lambda r: r["activities_per_advisor"],
            KpiCode.CALLS_OUT: lambda r: r["calls_out"],
            KpiCode.APPT_BOOKED: lambda r: r["appointments_booked"],
            KpiCode.CALL_TO_APPT: lambda r: r["call_to_appt_rate"],
            KpiCode.SHOW_RATE: lambda r: r["show_rate"],
            KpiCode.APPT_CONV: lambda r: r["conversion_rate"],
            KpiCode.CLIENTS_CONTACTED: lambda r: r["unique_clients_contacted"],
            KpiCode.AVG_MEET_MIN: lambda r: r["avg_meeting_duration_min"],
            KpiCode.NO_SHOW_RATE: lambda r: (
                None if r["show_rate"] is None else round(1 - r["show_rate"], 4)
            ),
        }
        stats = self.batch_stats()
        values: dict[tuple[str, str, KpiCode], float | None] = {}
        for r in org_rows:
            for kpi, fn in value_of.items():
                v = fn(r)
                values[(r["iso_week_id"], r["node_id"], kpi)] = None if v is None else float(v)
            if r["level"] == OrgLevel.NATIONAL.value:
                s = stats[r["iso_week_id"]]
                loaded = s["activity_rows"] - s["quarantined"]
                read = s["activity_rows"] + s["client_rows"]
                quarantined = s["quarantined"] + s["client_quarantined"]
                values[(r["iso_week_id"], r["node_id"], KpiCode.LATE_RATE)] = _ratio(
                    s["late"], loaded
                )
                values[(r["iso_week_id"], r["node_id"], KpiCode.QUAR_RATE)] = _ratio(
                    quarantined, read
                )

        out = []
        for r in org_rows:
            week, node_id = r["iso_week_id"], r["node_id"]
            siblings = [
                n.node_id
                for n in self.nodes
                if n.parent_id == r["parent_id"] and n.level.value == r["level"]
            ]
            for kpi in KpiCode:
                if (week, node_id, kpi) not in values:
                    continue
                value = values[(week, node_id, kpi)]
                i = WEEKS.index(week)
                prior = values.get((WEEKS[i - 1], node_id, kpi)) if i else None
                history = [values[(w, node_id, kpi)] for w in WEEKS[max(0, i - 12) : i + 1]]
                trailing = [h for h in history if h is not None]
                delta = None if value is None or prior is None else round(value - prior, 4)
                pct = None if delta is None or not prior else round(delta / prior, 4)
                rank = peers = None
                if r["parent_id"] is not None and value is not None:
                    peer_values = [values.get((week, s, kpi)) for s in siblings]
                    present = sorted(
                        {v for v in peer_values if v is not None},
                        reverse=kpi not in LOWER_IS_BETTER,
                    )
                    rank, peers = present.index(value) + 1, len(siblings)
                out.append(
                    {
                        "iso_week_id": week,
                        "level": r["level"],
                        "node_id": node_id,
                        "node_name": r["node_name"],
                        "parent_id": r["parent_id"],
                        "kpi_code": kpi.value,
                        "value": value,
                        "prior_week_value": prior,
                        "wow_delta": delta,
                        "wow_pct": pct,
                        "trailing_13w_avg": round(statistics.fmean(trailing), 4)
                        if trailing
                        else None,
                        "rank_in_parent": rank,
                        "peer_count": peers,
                        "flag": _flag(value, [h for h in history[:-1] if h is not None], pct).value,
                    }
                )
        return out

    def geo_weekly(self) -> list[dict[str, Any]]:
        rows = []
        for week in WEEKS:
            portfolios, reached = self.portfolio_book(week), self.contacted_12m(week)
            complete = self.window_complete(week)
            groups: dict[tuple[str, str], set[str]] = defaultdict(set)
            for c in self.books[week].values():
                if c.status != "A":
                    continue
                postal = normalize_postal(c.postal)
                fsa = postal[:3] if postal else "UNK"
                groups[(fsa, org().placement(c.branch_id).district.district_code)].add(c.client_id)
            completed = Counter(
                a["CLIENT_ID"]
                for a in self.acts
                if a["CLIENT_ID"]
                and a["STATUS"] == "COMPLETED"
                and iso_week(local_date(a["ACTIVITY_TS"])) == week
            )
            for (fsa, district), clients in sorted(groups.items()):
                rows.append(
                    {
                        "iso_week_id": week,
                        "fsa_code": fsa,
                        "district_code": district,
                        "active_clients": len(clients),
                        "activities_completed": sum(completed[c] for c in clients),
                        "portfolio_clients": len(owned := clients & portfolios.keys()),
                        "portfolio_contacted_12m": len(owned & reached),
                        "portfolio_contacted_rate_12m": _ratio(len(owned & reached), len(owned))
                        if complete
                        else None,
                    }
                )
        return rows

    def portfolio_weekly(self) -> list[dict[str, Any]]:
        """Portfolio x week, as mart_portfolio_weekly: holder at week end, transit, the KPI."""
        rows = []
        for week in WEEKS:
            reached, complete = self.contacted_12m(week), self.window_complete(week)
            members: dict[str, set[str]] = defaultdict(set)
            for client, portfolio in self.portfolio_book(week).items():
                members[portfolio].add(client)
            for portfolio, clients in sorted(members.items()):
                holder, transit = self.holder(portfolio, week), self.transit(portfolio)
                place = org().placement(transit)
                hit = len(clients & reached)
                rows.append(
                    {
                        "iso_week_id": week,
                        "portfolio_id": portfolio,
                        "advisor_id": holder,
                        "branch_id": transit,
                        "district_code": place.district.district_code,
                        "region_code": place.region.region_code.value,
                        "holder_branch_id": (
                            a.branch_id
                            if (a := self.world.assignment_on(holder, week_end(week)))
                            else None
                        ),
                        "clients": len(clients),
                        "contacted_12m": hit,
                        "contacted_rate_12m": _ratio(hit, len(clients)) if complete else None,
                    }
                )
        return rows

    def dq_weekly(self) -> list[dict[str, Any]]:
        stats = self.batch_stats()
        rules = (
            ("DQ001", "Null ACTIVITY_ID", DqAction.QUARANTINE),
            ("DQ002", "Enum not in contract", DqAction.QUARANTINE),
            ("DQ003", "DURATION_MIN out of range", DqAction.QUARANTINE),
            ("DQ004", "ACTIVITY_TS out of range", DqAction.QUARANTINE),
            ("DQ005", "Unparseable value", DqAction.QUARANTINE),
            ("DQ010", "Duplicate or re-sent row", DqAction.DEDUPE),
            ("DQ011", "Invalid postal code", DqAction.NORMALIZE),
            ("DQ012", "Unknown advisor_id", DqAction.MAP_UNKNOWN),
            ("DQ014", "Unknown portfolio", DqAction.MAP_UNKNOWN),
        )
        rows = []
        for week in WEEKS:
            s = stats[week]
            counts = Counter(
                d.rule_id for p in self.world.extracts[week] for r in p for d in r.defects
            )
            active = [c for c in self.books[week].values() if c.status == "A"]
            for rule_id, name, action in rules:
                if rule_id == "DQ005":
                    affected, total = s["client_quarantined"], s["client_rows"]
                elif rule_id == "DQ011":
                    affected = sum(normalize_postal(c.postal) is None for c in active)
                    total = len(active)
                elif rule_id == "DQ014":
                    affected = sum(c.source_row()["PRTF_ID"] not in PORTFOLIOS for c in active)
                    total = len(active)
                else:
                    affected, total = counts[rule_id], s["activity_rows"]
                rows.append(
                    {
                        "iso_week_id": week,
                        "rule_id": rule_id,
                        "rule_name": name,
                        "action": action.value,
                        "rows_affected": affected,
                        "rows_in_batch": total,
                        "rate": _ratio(affected, total),
                    }
                )
        return rows


def _flag(value: float | None, prior_values: list[float], pct: float | None) -> ReportFlag:
    """ANOMALY when |z| > 3 against prior weeks and WoW moved 25%+; else WoW direction.

    Stricter than the mart rule (|z| > 2 over 13 weeks) because the fixtures have 3 prior weeks.
    """
    if value is not None and len(prior_values) >= 3 and pct is not None and abs(pct) >= 0.25:
        sd = statistics.stdev(prior_values)
        if sd > 0 and abs(value - statistics.fmean(prior_values)) / sd > 3:
            return ReportFlag.ANOMALY
    if pct is None or abs(pct) < 0.01:
        return ReportFlag.FLAT
    return ReportFlag.UP if pct > 0 else ReportFlag.DOWN


# ── Documents: run log, pipeline graph, narrative ────────────────────────────


def _run_id(week: str) -> str:
    return f"weekly-{week}-1"


class _Timeline:
    """Stage attempts laid end to end, 150 ms apart."""

    def __init__(self, start: datetime) -> None:
        self.clock = start
        self.attempts: list[StageAttempt] = []

    def stage(
        self,
        name: str,
        ms: int,
        status: StageStatus = StageStatus.SUCCESS,
        attempt: int = 1,
        **kw: Any,
    ) -> None:
        end = self.clock + timedelta(milliseconds=ms)
        self.attempts.append(
            StageAttempt(
                stage=name,
                attempt=attempt,
                status=status,
                started_at=self.clock,
                ended_at=end,
                duration_ms=ms,
                **kw,
            )
        )
        self.clock = end + timedelta(milliseconds=150)


def run_log(
    stats: dict[str, dict[str, int]], completed: dict[str, int], freshness_gap: dict[str, int]
) -> RunLogExport:
    """Four weekly runs: W39 retries ingest once; W39 and W40 end WARN."""
    runs = []
    for week in WEEKS:
        s = stats[week]
        started = at(week_end(week) + timedelta(days=1), 6)
        timeline = _Timeline(started)
        stage = timeline.stage
        attempts = timeline.attempts

        read = s["activity_rows"] + s["client_rows"] + s.get("hr_rows", 0)
        quarantined = s["quarantined"] + s["client_quarantined"]
        cold = week == WEEKS[0]
        stage(
            "restore_state",
            4200,
            message="Cold start: no state in R2."
            if cold
            else "Restored warehouse.duckdb and sources from R2.",
        )
        stage(
            "generate",
            9100,
            rows_out=s["activity_rows"],
            message=f"Generated {week} plus late arrivals.",
        )
        if week == "2026-W39":
            stage(
                "ingest",
                2300,
                StageStatus.FAILED,
                message="R2 read timed out (TransientError); retrying in 4 s.",
                rows_in=0,
            )
            stage(
                "ingest",
                6100,
                attempt=2,
                rows_in=read,
                rows_out=read - quarantined,
                rows_quarantined=quarantined,
            )
        else:
            stage(
                "ingest",
                5800,
                rows_in=read,
                rows_out=read - quarantined,
                rows_quarantined=quarantined,
            )
        unknown = s["unknown_advisor"]
        if unknown:
            share = unknown / (s["activity_rows"] - s["quarantined"])
            stage(
                "dbt_build",
                31400,
                StageStatus.WARN,
                message=f"DQ012 warn: {share:.2%} of activity rows map to the Unknown "
                "advisor (warn above 0.5%).",
            )
        else:
            stage("dbt_build", 30200, message="All models and tests passed.")
        stage("checks", 1800, message="4 checks run.")
        if week == WEEKS[-1]:
            stage(
                "narrate",
                24800,
                StageStatus.WARN,
                message="1 of 5 narratives fell back to the template.",
            )
        else:
            stage("narrate", 22100, message="5 narratives validated.")
        stage("export", 2600, message="Exported 5 tables and 4 documents.")
        stage("publish_sheets", 0, StageStatus.SKIPPED, message="GSHEET_ID is not set.")
        stage(
            "persist_state",
            3900,
            message=(
                "Persisted warehouse.duckdb and 3 new or changed source files, "
                "plus 2 narrative files."
            ),
        )
        stage("release_lock", 300, message="Released run lock.")

        finals: dict[str, StageStatus] = {a.stage: a.status for a in attempts}
        order = [StageStatus.FAILED, StageStatus.WARN, StageStatus.SUCCESS]
        status = next(x for x in order if x in finals.values())
        prior = [completed[w] for w in WEEKS[max(0, WEEKS.index(week) - 8) : WEEKS.index(week)]]
        z = None
        if len(prior) >= 3 and statistics.stdev(prior) > 0:
            z = round((completed[week] - statistics.fmean(prior)) / statistics.stdev(prior), 2)
        checks = [
            RunCheck(
                check_id="DQ030",
                severity=CheckSeverity.FAIL,
                status=CheckStatus.PASS,
                observed=freshness_gap[week],
                expected="<= 2 days before week end",
                message="Latest activity date is within 2 days of week end.",
            ),
            RunCheck(
                check_id="DQ031",
                severity=CheckSeverity.WARN,
                status=CheckStatus.PASS if z is None or abs(z) <= 3 else CheckStatus.WARN,
                observed=z,
                expected="|z| <= 3 vs trailing 8 weeks",
                message="Needs 3 prior weeks of history."
                if z is None
                else f"{completed[week]} completed activities, z = {z}.",
            ),
            RunCheck(
                check_id="DQ032",
                severity=CheckSeverity.FAIL,
                status=CheckStatus.PASS,
                observed=round(quarantined / read, 4),
                expected="<= 0.02",
                message="Quarantine rate below the circuit breaker.",
            ),
            RunCheck(
                check_id="DQ033",
                severity=CheckSeverity.WARN,
                status=CheckStatus.PASS,
                observed=quarantined,
                expected=f"== {quarantined} injected",
                message="Quarantined rows match the defect manifest.",
            ),
        ]
        ended = attempts[-1].ended_at
        assert ended is not None
        runs.append(
            RunSummary(
                run_id=_run_id(week),
                run_type=RunType.WEEKLY,
                iso_week_id=week,
                status=status,
                started_at=started,
                ended_at=ended,
                duration_ms=int((ended - started).total_seconds() * 1000),
                git_sha=hashlib.sha1(week.encode()).hexdigest(),
                stages=attempts,
                checks=checks,
            )
        )
    runs.reverse()
    newest = runs[0].ended_at
    assert newest is not None
    return RunLogExport(generated_at=newest, runs=runs)


DBT_MODELS = {
    "staging": [
        "stg_activity",
        "stg_client",
        "stg_advisor",
        "stg_advisor_assignment",
        "stg_branch",
    ],
    "intermediate": ["int_advisor_history", "int_client_book_weekly", "int_activity_enriched"],
    "marts": [
        "dim_date",
        "dim_org",
        "dim_geography",
        "dim_advisor",
        "dim_client",
        "dim_activity_type",
        "fct_activity",
        "mart_advisor_weekly",
        "mart_org_weekly",
        "mart_weekly_report",
        "mart_geo_weekly",
        "mart_dq_weekly",
    ],
}


def pipeline_graph() -> PipelineGraph:
    """The graph export builds from the weekly stages and a dbt manifest: here a small
    manifest holding the fixture models, each layer reading the one before."""
    from pulse.export.pipeline_graph import build_pipeline_graph
    from pulse.runner.dag import WEEKLY_STAGES

    nodes: dict[str, Any] = {}
    previous: list[str] = []
    for layer, models in DBT_MODELS.items():
        for name in models:
            nodes[f"model.advisor_pulse.{name}"] = {
                "resource_type": "model",
                "package_name": "advisor_pulse",
                "name": name,
                "fqn": ["advisor_pulse", layer, name],
                "depends_on": {"nodes": [f"model.advisor_pulse.{p}" for p in previous[:1]]},
            }
        previous = models
    nodes["seed.advisor_pulse.org_branch"] = {"resource_type": "seed", "name": "org_branch"}
    sources = {
        f"source.advisor_pulse.raw.{name}": {"source_name": "raw", "name": name}
        for name in ("snowflake__activity", "teradata__clnt", "teradata__advsr")
    }
    return build_pipeline_graph(WEEKLY_STAGES, {"nodes": nodes, "sources": sources})


def _fmt(kpi: KpiCode, value: float) -> str:
    if kpi in {
        KpiCode.SHOW_RATE,
        KpiCode.APPT_CONV,
        KpiCode.CALL_TO_APPT,
        KpiCode.NO_SHOW_RATE,
    }:
        return f"{value:.1%}"
    return f"{value:g}" if value == int(value) else f"{value:.1f}"


class _FactBook:
    """Numbered facts (F1, F2, ...) for one node's narrative, from weekly_report rows."""

    def __init__(self, rows: dict[tuple[str, str], dict[str, Any]], week: str) -> None:
        self.rows = rows
        self.week = week
        self.facts: list[NarrativeFact] = []

    def add(self, node_id: str, kpi: KpiCode) -> NarrativeFact:
        r = self.rows[(node_id, kpi.value)]
        f = NarrativeFact(
            fact_id=f"F{len(self.facts) + 1}",
            node_id=node_id,
            kpi_code=kpi,
            iso_week_id=self.week,
            value=r["value"],
            prior_week_value=r["prior_week_value"],
            wow_pct=r["wow_pct"],
            trailing_13w_avg=r["trailing_13w_avg"],
            rank_in_parent=r["rank_in_parent"],
            peer_count=r["peer_count"],
        )
        self.facts.append(f)
        return f


def narratives(report: list[dict[str, Any]], generated_at: datetime) -> NarrativeFile:
    week = WEEKS[-1]
    rows = {(r["node_id"], r["kpi_code"]): r for r in report if r["iso_week_id"] == week}
    labels = {
        KpiCode.ACT_PER_ADV: "Activities per advisor",
        KpiCode.SHOW_RATE: "Show rate",
        KpiCode.APPT_CONV: "Appointment conversion",
        KpiCode.CALLS_OUT: "Outbound calls",
    }
    out = []
    for node in org_nodes():
        if node.level not in (OrgLevel.REGION, OrgLevel.DISTRICT):
            continue
        children = [n for n in org_nodes() if n.parent_id == node.node_id]
        book = _FactBook(rows, week)
        fact, facts = book.add, book.facts
        headline_fact = fact(node.node_id, KpiCode.ACT_PER_ADV)
        bullets = []
        for kpi in (KpiCode.CALLS_OUT, KpiCode.SHOW_RATE, KpiCode.APPT_CONV):
            f = fact(node.node_id, kpi)
            if f.value is None:
                continue
            text = f"{labels[kpi]} {_fmt(kpi, f.value)}"
            if f.prior_week_value is not None:
                text += f", from {_fmt(kpi, f.prior_week_value)} the week before."
            else:
                text += "."
            bullets.append(NarrativeBullet(text=text, fact_ids=[f.fact_id]))
        watch: list[WatchItem] = []
        if len(children) >= 2:  # a lone child has no peers to trail
            child_facts = [fact(c.node_id, KpiCode.ACT_PER_ADV) for c in children]
            lowest = min(
                (f for f in child_facts if f.value is not None), key=lambda f: f.value or 0.0
            )
            name = next(c.name for c in children if c.node_id == lowest.node_id)
            pace = _fmt(KpiCode.ACT_PER_ADV, lowest.value or 0.0)
            watch.append(
                WatchItem(
                    node_id=lowest.node_id,
                    reason=f"Fewest activities per advisor under {node.name} ({pace}).",
                    fact_ids=[lowest.fact_id],
                )
            )
        v, pct = headline_fact.value or 0.0, headline_fact.wow_pct
        fallback = node.node_id == "MTL"
        if pct is None or abs(pct) < 0.01:
            move = f"held at {_fmt(KpiCode.ACT_PER_ADV, v)}"
        else:
            move = (
                f"{'rose' if pct > 0 else 'fell'} {abs(pct):.1%} week over week to "
                f"{_fmt(KpiCode.ACT_PER_ADV, v)}"
            )
        headline = (
            f"Activities per advisor {move}."
            if fallback
            else f"{node.name}: activities per advisor {move}."
        )
        if watch and not fallback:
            bullets.append(
                NarrativeBullet(
                    text=f"{name} trails its peers on activities per advisor at {pace}.",
                    fact_ids=watch[0].fact_ids,
                )
            )
        out.append(
            NodeNarrative(
                node_id=node.node_id,
                level=node.level,
                headline=headline,
                bullets=bullets or [NarrativeBullet(text=headline, fact_ids=["F1"])],
                watchlist=watch,
                facts_used=facts,
                model=None if fallback else NARRATIVE_MODEL,
                prompt_version=PROMPT_VERSION,
                validated=True,
                fallback=fallback,
            )
        )
    return NarrativeFile(iso_week_id=week, generated_at=generated_at, narratives=out)


# ── Writers ──────────────────────────────────────────────────────────────────


def _plain(value: Any) -> Any:
    return value.value if isinstance(value, StrEnum) else value


def write_parquet(
    path: Path, model: type[Contract], rows: Sequence[dict[str, Any]], *, strict: bool = True
) -> None:
    """Write rows under the contract's Arrow schema; ``strict=False`` lets dirt through."""
    schema = arrow_schema(model)
    if strict:
        rows = [
            {k: _plain(v) for k, v in model.model_validate(r).model_dump(by_alias=True).items()}
            for r in rows
        ]
    else:
        schema = pa.schema(
            [f.with_nullable(True) for f in schema],
            metadata=dict(schema.metadata or {}),  # type: ignore[arg-type]  # stub too narrow
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(list(rows), schema=schema), path, compression="zstd")


_SQLITE_TYPES = {str: "VARCHAR", int: "INTEGER", date: "DATE", datetime: "TIMESTAMP"}
_SQLITE_OVERRIDES = {"PROV_CD": "CHAR(2)", "STAT_CD": "CHAR(1)"}


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _sql_ts(value)
    if isinstance(value, date):
        return value.isoformat()
    return _plain(value)


def write_sqlite(
    path: Path, tables: dict[str, tuple[type[Contract], list[dict[str, Any]]]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode = DELETE")
        for name, (model, rows) in tables.items():
            cols = columns(model)
            ddl = ", ".join(
                f'"{c.name}" '
                + _SQLITE_OVERRIDES.get(c.name, _SQLITE_TYPES.get(c.python_type, "VARCHAR"))
                for c in cols
            )
            con.execute(f"CREATE TABLE {name} ({ddl})")
            con.executemany(
                f"INSERT INTO {name} VALUES ({', '.join('?' for _ in cols)})",
                [[_sqlite_value(r[c.name]) for c in cols] for r in rows],
            )
        con.commit()
    finally:
        con.close()


def write_csv(path: Path, model: type[Contract], delta: ClientDelta) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[c.name for c in columns(model)],
        lineterminator="\n",
        quoting=csv.QUOTE_ALL if delta.quote_all else csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    writer.writerows(delta.rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("﻿" if delta.bom else "").encode() + buf.getvalue().encode())


def write_json(path: Path, doc: Contract) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc.model_dump_json(indent=2, by_alias=True) + "\n", encoding="utf-8")


# ── Build ────────────────────────────────────────────────────────────────────


def write_sources(world: World, root: Path) -> None:
    for week, parts in world.extracts.items():
        for part_no, rows in enumerate(parts):
            write_parquet(
                root / activity_part_path(week, part_no),
                SnowflakeActivity,
                [r.values for r in rows],
                strict=False,
            )
    o = org()
    advisors = []
    for a in ROSTER:
        events = [e for e in world.assignments if e.advisor_id == a.advisor_id]
        latest = events[-1]
        term = latest.effective if latest.reason is _AR.TERM else None
        role = (world.assignment_on(a.advisor_id, WINDOW_END) or latest).role
        advisors.append(
            {
                "ADVSR_ID": a.advisor_id,
                "ADVSR_NM": a.name,
                "ROLE_CD": role,
                "HIRE_DT": a.hire_date,
                "TERM_DT": term,
                "LAST_UPD_TS": max(e.entered for e in events),
            }
        )
    tables: dict[str, tuple[type[Contract], list[dict[str, Any]]]] = {
        "CLNT": (TeradataClient, [c.source_row() for c in world.snapshot]),
        "ADVSR": (TeradataAdvisor, advisors),
        "ADVSR_ASGN": (
            TeradataAssignment,
            [
                {
                    "ASGN_ID": e.assignment_id,
                    "ADVSR_ID": e.advisor_id,
                    "BRNCH_ID": e.branch_id,
                    "ROLE_CD": e.role,
                    "EFF_DT": e.effective,
                    "RSN_CD": e.reason,
                    "LAST_UPD_TS": e.entered,
                }
                for e in world.assignments
            ],
        ),
        "PRTF": (
            TeradataPortfolio,
            [
                {
                    "PRTF_ID": portfolio_of(a.advisor_id),
                    "BRNCH_ID": (world.assignment_on(a.advisor_id, SNAPSHOT_DATE) or a).branch_id,
                    "OPEN_DT": a.hire_date,
                    "CLOSE_DT": None,
                    "LAST_UPD_TS": at(date(2026, 1, 5), 9),
                }
                for a in ROSTER
                if portfolio_of(a.advisor_id) in PORTFOLIOS
            ],
        ),
        "PRTF_ASGN": (
            TeradataPortfolioAssignment,
            [
                {
                    "PASGN_ID": f"PAS-{i:08d}",
                    "PRTF_ID": portfolio,
                    "ADVSR_ID": advisor,
                    "EFF_DT": day,
                    "RSN_CD": reason,
                    "LAST_UPD_TS": _entered(day),
                }
                for i, (day, portfolio, advisor, reason) in enumerate(
                    sorted(
                        [
                            (a.hire_date, portfolio_of(a.advisor_id), a.advisor_id, "OPEN")
                            for a in ROSTER
                            if portfolio_of(a.advisor_id) in PORTFOLIOS
                        ]
                        + [(day, portfolio_of(old), new, "HANDOVER") for old, new, day in HANDOVERS]
                    ),
                    start=1,
                )
            ],
        ),
        "BRNCH": (
            TeradataBranch,
            [
                {
                    "BRNCH_ID": b,
                    "BRNCH_NM": (p := o.placement(b)).branch.branch_name,
                    "DIST_CD": p.district.district_code,
                    "FSA_CD": p.branch.fsa_code,
                    "OPEN_DT": p.branch.open_date,
                    "CLOSE_DT": None,
                    "LAST_UPD_TS": at(date(2026, 1, 5), 9),
                }
                for b in BRANCH_IDS
            ],
        ),
    }
    write_sqlite(root / TERADATA_DIR / SQLITE_NAME, tables)
    for delta in world.deltas:
        write_csv(root / TERADATA_DIR / delta.name, TeradataClient, delta)


def write_exports(world: World, root: Path) -> None:
    marts = Marts(world)
    org_rows = marts.org_weekly()
    report = marts.weekly_report(org_rows)
    tables: list[tuple[str, type[Contract], list[dict[str, Any]]]] = [
        ("org_weekly.parquet", OrgWeekly, org_rows),
        ("org_quarterly.parquet", OrgQuarterly, marts.org_quarterly()),
        ("advisor_weekly.parquet", AdvisorWeekly, marts.advisor_weekly()),
        ("weekly_report.parquet", WeeklyReport, report),
        ("geo_weekly.parquet", GeoWeekly, marts.geo_weekly()),
        ("dq_weekly.parquet", DqWeekly, marts.dq_weekly()),
        ("portfolio_weekly.parquet", PortfolioWeekly, marts.portfolio_weekly()),
    ]
    files: list[ExportFile] = []
    for name, model, rows in tables:
        write_parquet(root / name, model, rows)
        files.append(_export_file(root, name, len(rows)))

    national = {r["iso_week_id"]: r for r in org_rows if r["level"] == OrgLevel.NATIONAL.value}
    gap = {
        w: (
            week_end(w)
            - max(
                local_date(a["ACTIVITY_TS"])
                for a in marts.acts
                if iso_week(local_date(a["ACTIVITY_TS"])) == w
            )
        ).days
        for w in WEEKS
    }
    log = run_log(
        marts.batch_stats(), {w: r["activities_completed"] for w, r in national.items()}, gap
    )
    latest = log.runs[0]
    export_end = next(a.ended_at for a in latest.stages if a.stage == "export")
    assert export_end is not None
    narrate_end = next(a.ended_at for a in latest.stages if a.stage == "narrate")
    assert narrate_end is not None
    docs: list[tuple[str, Contract]] = [
        ("run_log.json", log),
        ("pipeline_graph.json", pipeline_graph()),
        (f"narratives/{WEEKS[-1]}.json", narratives(report, narrate_end)),
    ]
    for name, doc in docs:
        write_json(root / name, doc)
        if name != "run_log.json":  # run_log.json changes after every run, success or not
            files.append(_export_file(root, name, None))

    summary = [
        r for r in report if r["iso_week_id"] == WEEKS[-1] and r["level"] == OrgLevel.NATIONAL.value
    ]
    write_json(
        root / "manifest.json",
        Manifest(
            run_id=latest.run_id,
            generated_at=export_end,
            latest_week=WEEKS[-1],
            weeks_available=list(WEEKS),
            files=files,
            summary=[
                SummaryKpi(
                    kpi_code=r["kpi_code"],
                    value=r["value"],
                    prior_week_value=r["prior_week_value"],
                    wow_pct=r["wow_pct"],
                    flag=r["flag"],
                )
                for r in summary
            ],
            has_fsa_boundaries=False,
        ),
    )


def _export_file(root: Path, name: str, rows: int | None) -> ExportFile:
    data = (root / name).read_bytes()
    return ExportFile(
        name=name, sha256=hashlib.sha256(data).hexdigest(), rows=rows, bytes=len(data)
    )


def build(out_dir: Path = FIXTURES_DIR) -> World:
    """Rebuild sources/, exports/ and defects.json under ``out_dir``. Other files are kept."""
    world = build_world()
    for sub in ("sources", "exports"):
        shutil.rmtree(out_dir / sub, ignore_errors=True)
    write_sources(world, out_dir / "sources")
    write_exports(world, out_dir / "exports")
    write_json(
        out_dir / "defects.json",
        DefectManifest(
            generated_at=extract_at(WEEKS[-1]),
            seed=SEED,
            iso_weeks=list(WEEKS),
            defects=finalize_defects(world),
        ),
    )
    return world


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the deterministic fixtures.")
    parser.add_argument("--out", type=Path, default=FIXTURES_DIR)
    args = parser.parse_args(argv)
    world = build(args.out)
    files = [p for p in args.out.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    print(f"Wrote fixtures to {args.out}: {len(files)} files, {size / 1024:.0f} KiB")
    print(json.dumps(Counter(d.kind.value for d in finalize_defects(world)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
