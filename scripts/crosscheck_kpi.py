"""Cross-check the lead KPI, PRTF_CONTACT_12M, against the marts (#303).

A second implementation that shares no code with `dbt/` or `src/pulse/ingest/`. It reads the
raw source extracts under `<data dir>/sources` plus `reference/`, applies the business rules
below, and compares the result for every week and node with `mart_portfolio_weekly`,
`mart_advisor_weekly` and `mart_org_weekly` (all four levels). Counts must match exactly;
rates must match to 1e-9 once rounded to 4 places the way the marts round them.

The only project import is `pulse.contracts.enums`, the allowed values of each enum column
(the contract, no logic). Everything else is the standard library, pyarrow (Parquet), PyYAML
(org.yaml) and DuckDB, which is used only to read the marts.

The rules, as written in PLAN.md §6–§8 and ADR 0005:

R1  Activity quarantine (DQ001–DQ005, DQ006). A row is dropped when ACTIVITY_ID is null;
    a required column is null; an enum is outside the contract; DURATION_MIN is outside
    0–480; or ACTIVITY_TS is before 2015-01-01 UTC or more than 1 day after _EXTRACTED_AT.
    A file missing a required column, or with a column of another type, is dropped whole.
R2  Activity dedupe (DQ010). One row per ACTIVITY_ID: the latest UPDATED_TS, then the latest
    _EXTRACTED_AT, then the later file and row.
R3  Business dates are America/Toronto; weeks are ISO weeks (Monday to Sunday).
R4  A contact is a deduped activity with STATUS = COMPLETED, a CLIENT_ID, and a type whose
    `counts_as_contact` is true in reference/activity_types.csv, by any advisor (known or not).
R5  The window is (week end − 12 months, week end], on the contact's Toronto date. Twelve
    months back from 29 February is 28 February.
R6  Client quarantine (DQ002, DQ005). A CLNT row is dropped when a required column is null,
    CLNT_SINCE_DT, BRTH_YR or LAST_UPD_TS does not parse, or SEG_CD, PROV_CD or STAT_CD is
    outside the contract. CSV rows with the wrong number of fields are dropped too.
R7  Client version at week end. Each CLNT row (snapshot, then daily deltas in file order) is
    a version in force from its LAST_UPD_TS (naive UTC) until the client's next one; the week
    uses the version in force at Sunday 23:59 Toronto. A second row with the same
    LAST_UPD_TS replaces the first. The client must exist by then (CLNT_SINCE_DT ≤ week end).
R8  Active portfolio client: that version has STAT_CD = A and a PRTF_ID found in PRTF.
R9  Portfolio holder at week end: the latest PRTF_ASGN event with EFF_DT ≤ week end (two
    events on one day: the larger PASGN_ID). A portfolio before its first event has no
    holder, and its clients are out of the KPI. The transit is PRTF.BRNCH_ID.
R10 Roll-up. Portfolio → holder (advisor) and portfolio → transit branch → district →
    region → national, from reference/org.yaml, by summing clients and contacted clients.
    The rate is contacted ÷ clients at each level, never an average of rates.
R11 Window completeness: a week has a rate only when week end − 12 months is on or after the
    first completed activity's date (any type). Before that, counts only.
R12 Reported weeks: from the first week with a complete window that is not after the last
    completed-activity week (or, failing that, the first completed-activity week), through
    the last week with any activity. Warm-up weeks before that feed the window only.
R13 Advisor rows exist for advisors on the roster at week start: their latest ADVSR_ASGN
    event on or before Monday (two on one day: the larger ASGN_ID) is not TERM, and the role
    is not BR_MGR. Holders off the roster still count at their portfolios' branch.

Usage: python scripts/crosscheck_kpi.py --data-dir data   (exit 1 on any mismatch, 2 when
the warehouse is missing). CI's dbt job runs it on the fixture warehouse with
--sources fixtures/sources --warehouse data/ci/warehouse.duckdb.
"""

from __future__ import annotations

import argparse
import csv
import math
import sqlite3
import sys
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from pulse.contracts.enums import (
    ActivityStatus,
    ActivityType,
    Channel,
    ClientStatus,
    Outcome,
    ProductLine,
    Province,
    Segment,
)

ROOT = Path(__file__).resolve().parents[1]
TORONTO = ZoneInfo("America/Toronto")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
US_PER_HOUR = 3_600_000_000

# The rules as data, so a test can break one and watch the comparison fail.
CONTACT_STATUSES = frozenset({"COMPLETED"})  # R4
WINDOW_MONTHS = 12  # R5
ACTIVE_STATUS = "A"  # R8
RATE_TOLERANCE = 1e-9

# R1: the activity contract's required columns and types, and its enum columns.
_TS = pa.timestamp("us", tz="UTC")
ACTIVITY_COLUMNS: dict[str, tuple[pa.DataType, bool]] = {
    "ACTIVITY_ID": (pa.string(), True),  # null is DQ001, not a file failure
    "ADVISOR_ID": (pa.string(), False),
    "CLIENT_ID": (pa.string(), True),
    "BRANCH_ID": (pa.string(), False),
    "ACTIVITY_TYPE": (pa.string(), False),
    "CHANNEL": (pa.string(), False),
    "STATUS": (pa.string(), False),
    "OUTCOME": (pa.string(), True),
    "PRODUCT_LINE": (pa.string(), True),
    "SCHEDULED_TS": (_TS, True),
    "ACTIVITY_TS": (_TS, False),
    "DURATION_MIN": (pa.int64(), True),
    "BOOKED_FROM_ACTIVITY_ID": (pa.string(), True),
    "CREATED_TS": (_TS, False),
    "UPDATED_TS": (_TS, False),
    "_EXTRACTED_AT": (_TS, False),
}
ACTIVITY_ENUMS: dict[str, frozenset[str]] = {
    "ACTIVITY_TYPE": frozenset(ActivityType),
    "CHANNEL": frozenset(Channel),
    "STATUS": frozenset(ActivityStatus),
    "OUTCOME": frozenset(Outcome),
    "PRODUCT_LINE": frozenset(ProductLine),
}
EARLIEST_ACTIVITY_US = int((datetime(2015, 1, 1, tzinfo=UTC) - EPOCH).total_seconds()) * 10**6
FUTURE_SKEW_US = 24 * US_PER_HOUR
MAX_DURATION = 480

# R6: the client contract.
CLIENT_REQUIRED = (
    "CLNT_ID",
    "CLNT_SINCE_DT",
    "BRTH_YR",
    "SEG_CD",
    "PROV_CD",
    "PRIM_BRNCH_ID",
    "STAT_CD",
    "LAST_UPD_TS",
    "PRTF_ID",
)
CLIENT_ENUMS: dict[str, frozenset[str]] = {
    "SEG_CD": frozenset(Segment),
    "PROV_CD": frozenset(Province),
    "STAT_CD": frozenset(ClientStatus),
}

LEVELS = ("NATIONAL", "REGION", "DISTRICT", "BRANCH")


# ── Calendar ────────────────────────────────────────────────────────────────


def iso_week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def week_bounds(week_id: str) -> tuple[date, date]:
    year, week = week_id.split("-W")
    monday = date.fromisocalendar(int(year), int(week), 1)
    return monday, monday + timedelta(days=6)


def months_back(day: date, months: int) -> date:
    """Calendar months back, clamped to the month's last day (31 March → 28/29 February)."""
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(day.day, last))


class TorontoDates:
    """UTC microseconds → Toronto date. Toronto's offsets are whole hours, so the date only
    depends on the UTC hour, and a cache per hour makes this cheap for millions of rows."""

    def __init__(self) -> None:
        self._cache: dict[int, date] = {}

    def __call__(self, micros: int) -> date:
        hour = micros // US_PER_HOUR
        found = self._cache.get(hour)
        if found is None:
            found = datetime.fromtimestamp(hour * 3600, tz=UTC).astimezone(TORONTO).date()
            self._cache[hour] = found
        return found


def week_end_cutoff(week_end: date) -> int:
    """Sunday 23:59 Toronto as UTC epoch seconds (R7)."""
    local = datetime.combine(week_end, time(23, 59), tzinfo=TORONTO)
    return int(local.timestamp())


# ── Activity (R1–R4, R11, R12) ──────────────────────────────────────────────


@dataclass
class ActivityFacts:
    contacts: dict[str, list[date]]  # client → sorted distinct contact dates
    first_completed: date | None
    first_completed_week: str | None
    last_completed_week: str | None
    first_week: str | None
    last_week: str | None
    rows_read: int = 0
    rows_quarantined: int = 0
    rows_kept: int = 0
    files_failed: list[str] = field(default_factory=list)


def _file_schema_ok(table: pa.Table) -> bool:
    for name, (kind, nullable) in ACTIVITY_COLUMNS.items():
        if name not in table.column_names:
            if not nullable:
                return False
            continue
        actual = table.schema.field(name).type
        if actual != kind and not pa.types.is_null(actual):
            return False
    return True


def _column(table: pa.Table, name: str) -> list[object]:
    if name not in table.column_names:
        return [None] * table.num_rows
    column = table.column(name)
    if pa.types.is_timestamp(column.type):
        column = column.cast(pa.int64())
    return column.to_pylist()


def _micros(value: object) -> int:
    assert isinstance(value, int)
    return value


def _quarantined(row: dict[str, object]) -> bool:
    if row["ACTIVITY_ID"] is None:
        return True  # DQ001
    for name, (_, nullable) in ACTIVITY_COLUMNS.items():
        if not nullable and row[name] is None:
            return True  # DQ005
    for name, allowed in ACTIVITY_ENUMS.items():
        if row[name] is not None and row[name] not in allowed:
            return True  # DQ002
    duration = row["DURATION_MIN"]
    if isinstance(duration, int) and not 0 <= duration <= MAX_DURATION:
        return True  # DQ003
    ts, extracted = row["ACTIVITY_TS"], row["_EXTRACTED_AT"]
    assert isinstance(ts, int) and isinstance(extracted, int)
    return ts < EARLIEST_ACTIVITY_US or ts > extracted + FUTURE_SKEW_US  # DQ004


def load_activity(sources: Path, contact_types: frozenset[str]) -> ActivityFacts:
    paths = sorted((sources / "snowflake" / "activity").rglob("*.parquet"))
    latest: dict[str, tuple[tuple[int, int, int, int], str, str | None, str, int]] = {}
    facts = ActivityFacts({}, None, None, None, None, None)
    names = list(ACTIVITY_COLUMNS)
    for file_index, path in enumerate(paths):
        table = pq.read_table(path)
        facts.rows_read += table.num_rows
        if not _file_schema_ok(table):
            facts.files_failed.append(path.relative_to(sources).as_posix())  # DQ006
            continue
        columns = [_column(table, name) for name in names]
        for row_number, values in enumerate(zip(*columns, strict=True)):
            row = dict(zip(names, values, strict=True))
            if _quarantined(row):
                facts.rows_quarantined += 1
                continue
            activity_id = str(row["ACTIVITY_ID"])
            rank = (
                _micros(row["UPDATED_TS"]),
                _micros(row["_EXTRACTED_AT"]),
                file_index,
                row_number,
            )
            held = latest.get(activity_id)
            if held is None or rank > held[0]:
                client = row["CLIENT_ID"]
                latest[activity_id] = (
                    rank,
                    str(row["STATUS"]),
                    None if client is None else str(client),
                    str(row["ACTIVITY_TYPE"]),
                    _micros(row["ACTIVITY_TS"]),
                )

    to_date = TorontoDates()
    contacts: dict[str, set[date]] = defaultdict(set)
    completed: list[date] = []
    every: list[date] = []
    for _, status, client, activity_type, ts in latest.values():
        day = to_date(ts)
        every.append(day)
        if status == "COMPLETED":
            completed.append(day)
        if status in CONTACT_STATUSES and client is not None and activity_type in contact_types:
            contacts[client].add(day)
    facts.rows_kept = len(latest)
    facts.contacts = {client: sorted(days) for client, days in contacts.items()}
    if completed:
        facts.first_completed = min(completed)
        facts.first_completed_week = iso_week(min(completed))
        facts.last_completed_week = iso_week(max(completed))
    if every:
        facts.first_week, facts.last_week = iso_week(min(every)), iso_week(max(every))
    return facts


def reported_weeks(facts: ActivityFacts) -> list[str]:
    """R12, over the weeks that hold activity."""
    if facts.first_week is None or facts.last_week is None:
        return []
    weeks: list[str] = []
    monday, _ = week_bounds(facts.first_week)
    while iso_week(monday) <= facts.last_week:
        weeks.append(iso_week(monday))
        monday += timedelta(days=7)
    complete = [
        week
        for week in weeks
        if window_complete(week, facts) and week <= (facts.last_completed_week or "")
    ]
    start = complete[0] if complete else facts.first_completed_week
    if start is None:
        return []
    # A first complete week before the first activity week can only be the first week itself.
    return [week for week in weeks if week >= start]


def window_complete(week: str, facts: ActivityFacts) -> bool:
    """R11."""
    if facts.first_completed is None:
        return False
    return months_back(week_bounds(week)[1], WINDOW_MONTHS) >= facts.first_completed


# ── Clients and portfolios (R6–R9, R13) ─────────────────────────────────────


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        return None


def _parse_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except ValueError:
        return None


def _parse_ts(text: str) -> int | None:
    """Naive 'Teradata' text is UTC (PLAN.md §6.2). Epoch seconds."""
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


@dataclass(frozen=True)
class ClientVersion:
    since: date
    status: str
    portfolio_id: str


def _client_rows(sources: Path) -> Iterator[dict[str, str | None] | None]:
    """Every CLNT row in load order, as text; None for a CSV row that does not parse."""
    edw = sources / "teradata" / "edw.sqlite"
    with closing(sqlite3.connect(edw.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        cursor = con.execute("SELECT * FROM CLNT ORDER BY CLNT_ID")
        names = [column[0] for column in cursor.description]
        for record in cursor:
            yield {
                name: None if value is None else str(value)
                for name, value in zip(names, record, strict=True)
            }
    for path in sorted((sources / "teradata").glob("client_*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if not header:
                continue
            for values in reader:
                if len(values) != len(header):
                    yield None
                    continue
                yield {
                    name: (value if value != "" else None)
                    for name, value in zip(header, values, strict=True)
                }


def load_clients(sources: Path) -> tuple[dict[str, tuple[list[int], list[ClientVersion]]], int]:
    """R6, R7: per client, version start times (epoch seconds, sorted) and versions."""
    versions: dict[str, dict[int, ClientVersion]] = defaultdict(dict)
    rejected = 0
    for row in _client_rows(sources):
        if row is None or any(row.get(name) is None for name in CLIENT_REQUIRED):
            rejected += 1
            continue
        since = _parse_date(str(row["CLNT_SINCE_DT"]))
        birth = _parse_int(str(row["BRTH_YR"]))
        updated = _parse_ts(str(row["LAST_UPD_TS"]))
        enums_ok = all(row.get(name) in allowed for name, allowed in CLIENT_ENUMS.items())
        if since is None or birth is None or updated is None or not enums_ok:
            rejected += 1
            continue
        versions[str(row["CLNT_ID"])][updated] = ClientVersion(
            since, str(row["STAT_CD"]), str(row["PRTF_ID"]).strip()
        )
    out = {}
    for client, by_time in versions.items():
        starts = sorted(by_time)
        out[client] = (starts, [by_time[start] for start in starts])
    return out, rejected


def _edw_rows(sources: Path, sql: str) -> list[tuple[object, ...]]:
    edw = sources / "teradata" / "edw.sqlite"
    with closing(sqlite3.connect(edw.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        return list(con.execute(sql))


def load_transits(sources: Path) -> dict[str, str]:
    """Portfolio → transit branch, from the latest PRTF row."""
    rows = _edw_rows(sources, "SELECT PRTF_ID, BRNCH_ID, LAST_UPD_TS FROM PRTF")
    latest: dict[str, tuple[str, str]] = {}
    for portfolio, branch, updated in rows:
        key, stamp = str(portfolio), str(updated)
        if key not in latest or stamp >= latest[key][0]:
            latest[key] = (stamp, str(branch).strip())
    return {portfolio: branch for portfolio, (_, branch) in latest.items()}


def _events(
    rows: Iterable[tuple[object, ...]],
) -> dict[str, tuple[list[date], list[tuple[str, ...]]]]:
    """(entity, event id, effective date, *payload) → per entity, sorted dates and payloads,
    one event per day (the larger event id)."""
    by_day: dict[str, dict[date, tuple[str, tuple[str, ...]]]] = defaultdict(dict)
    for entity, event_id, effective, *payload in rows:
        if entity is None or effective is None:
            continue
        day = date.fromisoformat(str(effective))
        held = by_day[str(entity)].get(day)
        if held is None or str(event_id) > held[0]:
            by_day[str(entity)][day] = (str(event_id), tuple(str(value) for value in payload))
    out = {}
    for entity, days in by_day.items():
        ordered = sorted(days)
        out[entity] = (ordered, [days[day][1] for day in ordered])
    return out


def load_holders(sources: Path) -> dict[str, tuple[list[date], list[tuple[str, ...]]]]:
    """R9: portfolio → (event dates, (advisor,))."""
    return _events(_edw_rows(sources, "SELECT PRTF_ID, PASGN_ID, EFF_DT, ADVSR_ID FROM PRTF_ASGN"))


def load_roster(sources: Path) -> dict[str, tuple[list[date], list[tuple[str, ...]]]]:
    """R13: advisor → (event dates, (role, reason))."""
    sql = "SELECT ADVSR_ID, ASGN_ID, EFF_DT, ROLE_CD, RSN_CD FROM ADVSR_ASGN"
    return _events(_edw_rows(sources, sql))


def as_of[T](timeline: tuple[list[date], list[T]] | None, day: date) -> T | None:
    if timeline is None:
        return None
    dates, payloads = timeline
    index = bisect_right(dates, day)
    return payloads[index - 1] if index else None


def load_org(reference: Path) -> dict[str, tuple[str, str]]:
    """Branch → (district, region), from reference/org.yaml."""
    org = yaml.safe_load((reference / "org.yaml").read_text())
    return {
        str(branch["branch_id"]): (str(district["district_code"]), str(region["region_code"]))
        for region in org["regions"]
        for district in region["districts"]
        for branch in district["branches"]
    }


def load_contact_types(reference: Path) -> frozenset[str]:
    with (reference / "activity_types.csv").open(newline="") as handle:
        return frozenset(
            row["activity_type"]
            for row in csv.DictReader(handle)
            if row["counts_as_contact"].strip().lower() == "true"
        )


# ── The KPI ─────────────────────────────────────────────────────────────────

Parts = list[int]  # [clients, contacted]


@dataclass
class Expected:
    weeks: list[str]
    complete: dict[str, bool]
    portfolio: dict[tuple[str, str], tuple[str, str, Parts]]  # → (advisor, transit, parts)
    advisor: dict[tuple[str, str], Parts]
    org: dict[tuple[str, str, str], Parts]  # (week, level, node)
    off_roster: dict[tuple[str, str], Parts]  # holders without an advisor row (R13)
    facts: ActivityFacts
    clients_rejected: int


def compute(sources: Path, reference: Path = ROOT / "reference") -> Expected:
    facts = load_activity(sources, load_contact_types(reference))
    clients, rejected = load_clients(sources)
    transits = load_transits(sources)
    holders = load_holders(sources)
    roster = load_roster(sources)
    org = load_org(reference)
    weeks = reported_weeks(facts)

    portfolio: dict[tuple[str, str], tuple[str, str, Parts]] = {}
    for week in weeks:
        monday, sunday = week_bounds(week)
        cutoff_ts = week_end_cutoff(sunday)
        window_start = months_back(sunday, WINDOW_MONTHS)
        for client, (starts, versions) in clients.items():
            index = bisect_right(starts, cutoff_ts)
            if not index:
                continue
            version = versions[index - 1]
            if version.since > sunday or version.status != ACTIVE_STATUS:
                continue
            transit = transits.get(version.portfolio_id)
            holder = as_of(holders.get(version.portfolio_id), sunday)
            if transit is None or holder is None:
                continue
            days = facts.contacts.get(client, [])
            last = bisect_right(days, sunday)
            contacted = bool(last) and days[last - 1] > window_start
            key = (week, version.portfolio_id)
            entry = portfolio.setdefault(key, (holder[0], transit, [0, 0]))
            entry[2][0] += 1
            entry[2][1] += int(contacted)

    advisor: dict[tuple[str, str], Parts] = defaultdict(lambda: [0, 0])
    off_roster: dict[tuple[str, str], Parts] = defaultdict(lambda: [0, 0])
    nodes: dict[tuple[str, str, str], Parts] = defaultdict(lambda: [0, 0])
    for (week, _), (holder_id, transit, parts) in portfolio.items():
        monday, _ = week_bounds(week)
        event = as_of(roster.get(holder_id), monday)
        on_roster = event is not None and event[1] != "TERM" and event[0] != "BR_MGR"
        target = advisor if on_roster else off_roster
        _add(target[(week, holder_id)], parts)
        if transit not in org:
            continue
        district, region = org[transit]
        for level, node in zip(LEVELS, ("CA", region, district, transit), strict=True):
            _add(nodes[(week, level, node)], parts)
    # Portfolios at a transit outside org.yaml have no place in the org or portfolio marts.
    portfolio = {key: value for key, value in portfolio.items() if value[1] in org}
    return Expected(
        weeks=weeks,
        complete={week: window_complete(week, facts) for week in weeks},
        portfolio=portfolio,
        advisor=dict(advisor),
        org=dict(nodes),
        off_roster=dict(off_roster),
        facts=facts,
        clients_rejected=rejected,
    )


def _add(total: Parts, parts: Parts) -> None:
    total[0] += parts[0]
    total[1] += parts[1]


def mart_round(value: float) -> float:
    """DuckDB's round(x, 4) on a double: round half away from zero on x × 10⁴."""
    scaled = value * 10_000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    return whole / 10_000


def expected_rate(parts: Parts, complete: bool) -> float | None:
    clients, contacted = parts
    if not complete or clients == 0:
        return None
    return mart_round(contacted / clients)


# ── The marts ───────────────────────────────────────────────────────────────


@dataclass
class Marts:
    weeks: set[str]
    portfolio: dict[tuple[str, str], tuple[str, str, Parts, float | None]]
    advisor: dict[tuple[str, str], tuple[Parts, float | None]]
    org: dict[tuple[str, str, str], tuple[Parts, float | None]]


def read_marts(warehouse: Path) -> Marts:
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        org_rows = con.execute(
            "select iso_week_id, level, node_id, portfolio_clients, portfolio_contacted_12m,"
            " portfolio_contacted_rate_12m from marts.mart_org_weekly"
        ).fetchall()
        advisor_rows = con.execute(
            "select iso_week_id, advisor_id, portfolio_clients, portfolio_contacted_12m,"
            " portfolio_contacted_rate_12m from marts.mart_advisor_weekly"
        ).fetchall()
        portfolio_rows = con.execute(
            "select iso_week_id, portfolio_id, advisor_id, branch_id, clients, contacted_12m,"
            " contacted_rate_12m from marts.mart_portfolio_weekly"
        ).fetchall()
    finally:
        con.close()
    return Marts(
        weeks={row[0] for row in org_rows},
        portfolio={(w, p): (a, b, [n or 0, c or 0], r) for w, p, a, b, n, c, r in portfolio_rows},
        advisor={(w, a): ([n or 0, c or 0], r) for w, a, n, c, r in advisor_rows},
        org={(w, lvl, node): ([n or 0, c or 0], r) for w, lvl, node, n, c, r in org_rows},
    )


# ── Comparison ──────────────────────────────────────────────────────────────


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    mismatches: dict[str, int] = field(default_factory=dict)
    first: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(self.mismatches.values())

    def miss(self, table: str, message: str) -> None:
        self.mismatches[table] = self.mismatches.get(table, 0) + 1
        self.first.setdefault(table, message)


def _rate_text(rate: float | None) -> str:
    return "null" if rate is None else f"{rate:.4f}"


def _check(
    report: Report,
    table: str,
    label: str,
    mine: Parts,
    mart: Parts | None,
    mart_rate: float | None,
    complete: bool,
) -> None:
    want_rate = expected_rate(mine, complete)
    if mart is None:
        report.miss(
            table,
            f"{label}: independent {mine[1]}/{mine[0]} contacted/clients,"
            " row missing from the mart",
        )
        return
    rate_ok = (want_rate is None and mart_rate is None) or (
        want_rate is not None
        and mart_rate is not None
        and abs(want_rate - mart_rate) <= RATE_TOLERANCE
    )
    if mine != mart or not rate_ok:
        report.miss(
            table,
            f"{label}: independent {mine[1]}/{mine[0]} contacted/clients"
            f" (rate {_rate_text(want_rate)}), mart {mart[1]}/{mart[0]}"
            f" (rate {_rate_text(mart_rate)})",
        )


def _level_order(key: tuple[str, str, str]) -> tuple[str, int, str]:
    return (key[0], LEVELS.index(key[1]) if key[1] in LEVELS else 9, key[2])


def compare(expected: Expected, marts: Marts) -> Report:
    report = Report()
    for table in ("weeks", "mart_org_weekly", "mart_advisor_weekly", "mart_portfolio_weekly"):
        report.mismatches[table] = 0
    mine_weeks = set(expected.weeks)
    for week in sorted(mine_weeks ^ marts.weeks):
        side = "independent only" if week in mine_weeks else "mart only"
        report.miss("weeks", f"{week}: reported week on one side ({side})")

    zero: Parts = [0, 0]
    for key in sorted(set(expected.org) | set(marts.org), key=_level_order):
        week, level, node = key
        mine = expected.org.get(key, zero)
        found = marts.org.get(key)
        if found is None and mine == zero:
            continue
        _check(
            report,
            "mart_org_weekly",
            f"{week} {level} {node}",
            mine,
            None if found is None else found[0],
            None if found is None else found[1],
            expected.complete.get(week, False),
        )

    for advisor_key in sorted(set(expected.advisor) | set(marts.advisor)):
        week, advisor_id = advisor_key
        mine = expected.advisor.get(advisor_key, zero)
        found_advisor = marts.advisor.get(advisor_key)
        found = found_advisor
        if found is None and mine == zero:
            continue
        if found is None and week not in marts.weeks:
            continue  # reported as a week mismatch already
        _check(
            report,
            "mart_advisor_weekly",
            f"{week} advisor {advisor_id}",
            mine,
            None if found is None else found[0],
            None if found is None else found[1],
            expected.complete.get(week, False),
        )

    for portfolio_key in sorted(set(expected.portfolio) | set(marts.portfolio)):
        week, portfolio_id = portfolio_key
        label = f"{week} portfolio {portfolio_id}"
        mine_entry = expected.portfolio.get(portfolio_key)
        mart_entry = marts.portfolio.get(portfolio_key)
        if mine_entry is None:
            assert mart_entry is not None
            report.miss(
                "mart_portfolio_weekly",
                f"{label}: mart {mart_entry[2][1]}/{mart_entry[2][0]} contacted/clients,"
                " no active clients in the independent result",
            )
            continue
        if mart_entry is None and week not in marts.weeks:
            continue
        holder, transit, parts = mine_entry
        if mart_entry is not None and (mart_entry[0], mart_entry[1]) != (holder, transit):
            report.miss(
                "mart_portfolio_weekly",
                f"{label}: independent holder {holder} at {transit},"
                f" mart holder {mart_entry[0]} at {mart_entry[1]}",
            )
            continue
        _check(
            report,
            "mart_portfolio_weekly",
            label,
            parts,
            None if mart_entry is None else mart_entry[2],
            None if mart_entry is None else mart_entry[3],
            expected.complete.get(week, False),
        )
    return report


def summarize(expected: Expected, marts: Marts, report: Report) -> list[str]:
    facts = expected.facts
    complete = [week for week in expected.weeks if expected.complete[week]]
    lines = [
        f"Activity: {facts.rows_read} rows read, {facts.rows_quarantined} quarantined,"
        f" {facts.rows_kept} after dedupe; {len(facts.files_failed)} files failed (DQ006)."
        f" First completed activity {facts.first_completed}.",
        f"Clients: {expected.clients_rejected} CLNT rows quarantined.",
        f"Reported weeks: {len(expected.weeks)}"
        + (f" ({expected.weeks[0]} to {expected.weeks[-1]})" if expected.weeks else "")
        + f", {len(complete)} with a complete 12-month window.",
        f"Compared: {len(marts.org)} org rows, {len(marts.advisor)} advisor rows,"
        f" {len(marts.portfolio)} portfolio rows.",
    ]
    if expected.off_roster:
        clients = sum(parts[0] for parts in expected.off_roster.values())
        lines.append(
            f"Note: {len(expected.off_roster)} holder-weeks ({clients} client-weeks) belong to"
            " advisors off the roster (branch manager or not employed at week start); they"
            " have no advisor row and count at their portfolios' branch only (R13)."
        )
    for week in (expected.weeks[:1] + expected.weeks[-1:]) if expected.weeks else []:
        parts = expected.org.get((week, "NATIONAL", "CA"), [0, 0])
        rate = expected_rate(parts, expected.complete[week])
        lines.append(
            f"National {week}: {parts[1]}/{parts[0]} contacted/clients, rate {_rate_text(rate)}"
        )
    for table, count in report.mismatches.items():
        if count:
            lines.append(f"MISMATCH {table}: {count} rows differ. First: {report.first[table]}")
        else:
            lines.append(f"OK {table}")
    lines.append("PASS" if report.ok else "FAIL")
    return lines


def run(
    data_dir: Path,
    reference: Path = ROOT / "reference",
    *,
    sources: Path | None = None,
    warehouse: Path | None = None,
) -> tuple[bool, list[str]]:
    expected = compute(sources or data_dir / "sources", reference)
    marts = read_marts(warehouse or data_dir / "warehouse.duckdb")
    report = compare(expected, marts)
    return report.ok, summarize(expected, marts, report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cross-check PRTF_CONTACT_12M against the marts.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Holds sources/ and warehouse.duckdb (PULSE_DATA_DIR).",
    )
    parser.add_argument("--sources", type=Path, help="Override <data-dir>/sources.")
    parser.add_argument("--warehouse", type=Path, help="Override <data-dir>/warehouse.duckdb.")
    parser.add_argument("--reference", type=Path, default=ROOT / "reference")
    args = parser.parse_args(argv)
    sources = args.sources or args.data_dir / "sources"
    warehouse = args.warehouse or args.data_dir / "warehouse.duckdb"
    needed = (sources / "teradata" / "edw.sqlite", warehouse)
    missing = [str(path) for path in needed if not path.is_file()]
    if missing:
        print(
            f"Missing {', '.join(missing)}. Build the warehouse first"
            " (make run / make backfill, or make dbt-build-ci for the fixtures).",
            file=sys.stderr,
        )
        return 2
    ok, lines = run(args.data_dir, args.reference, sources=sources, warehouse=warehouse)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
