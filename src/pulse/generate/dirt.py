"""Post-process synthetic source files and write a weekly defect manifest."""

from __future__ import annotations

import csv
import hashlib
import itertools
import math
import random
import re
import sqlite3
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import ValidationError

from pulse.contracts.defects import Defect, DefectKind, DefectManifest
from pulse.contracts.enums import AssignmentReason, DqAction
from pulse.contracts.patterns import POSTAL_CODE
from pulse.contracts.sources import SnowflakeActivity
from pulse.generate.advisors import AdvisorRoster
from pulse.generate.clients import ClientBatch, delta_rows

DEFAULT_RATES: Mapping[DefectKind, float] = {
    DefectKind.EXACT_DUPLICATE: 0.015,
    DefectKind.RESENT_UPDATE: 0.03,
    DefectKind.NULL_ACTIVITY_ID: 0.002,
    DefectKind.INVALID_ENUM: 0.001,
    DefectKind.DURATION_OUT_OF_RANGE: 0.001,
    DefectKind.ACTIVITY_TS_OUT_OF_RANGE: 0.0,
    DefectKind.UNPARSEABLE_VALUE: 0.0,
    DefectKind.UNKNOWN_ADVISOR: 0.003,
    DefectKind.DIRTY_POSTAL_CODE: 0.08,
    DefectKind.LATE_ARRIVING: 0.04,
    DefectKind.ADVISOR_TRANSFER: 1.0,
    DefectKind.ADVISOR_PROMOTION: 1.0,
    DefectKind.ADVISOR_TERM: 1.0,
    DefectKind.CLIENT_REASSIGNMENT: 1.0,
}

POSTAL_VARIANTS = (
    ("lowercase, no space", lambda p: p.lower().replace(" ", "")),
    ("missing space", lambda p: p.replace(" ", "")),
    ("hyphen", lambda p: p.replace(" ", "-")),
    ("trailing space", lambda p: p + " "),
    ("US ZIP", lambda _p: "90210"),
    ("null", lambda _p: None),
)


def _count(size: int, rate: float, rng: random.Random) -> int:
    expected = size * rate
    return min(size, int(expected) + (rng.random() < expected % 1)) if rate else 0


def _select(indices: list[int], rate: float, rng: random.Random) -> list[int]:
    chosen = rng.sample(indices, _count(len(indices), rate, rng))
    for index in chosen:
        indices.remove(index)
    return chosen


def _note(
    kind: DefectKind,
    week: str,
    source: str,
    table: str,
    file: str,
    *,
    row: int | None,
    natural_key: str | None,
    column: str | None = None,
    raw: Any = None,
    expected: str | None = None,
    rule: str | None = None,
    action: DqAction | None = None,
    detail: str,
) -> Defect:
    return Defect(
        kind=kind,
        iso_week_id=week,
        source=source,
        table_name=table,
        file=file,
        row=row,
        natural_key=natural_key,
        column=column,
        raw_value=None if raw is None else str(raw),
        expected_value=expected,
        rule_id=rule,
        action=action,
        detail=detail,
    )


def _activity(
    root: Path, week: str, rates: Mapping[DefectKind, float], rng: random.Random
) -> list[Defect]:
    year, number = map(int, week.split("-W"))
    sunday = date.fromisocalendar(year, number, 7)
    base = root / "snowflake/activity"
    directory = base / f"extract_date={sunday + timedelta(days=1)}"
    if not directory.exists():
        directory = base / f"extract_date={sunday}"
    defects: list[Defect] = []
    for path in sorted(directory.glob("part-*.parquet")):
        table = pq.read_table(path)
        rows = table.to_pylist()
        file = path.relative_to(root).as_posix()
        keys = Counter(row["ACTIVITY_ID"] for row in rows)
        available = []
        for i, row in enumerate(rows):
            if not row["ACTIVITY_ID"] or keys[row["ACTIVITY_ID"]] != 1:
                continue
            try:
                SnowflakeActivity.model_validate(row)
            except ValidationError:
                continue
            available.append(i)
        changed = False
        for kind in (
            DefectKind.NULL_ACTIVITY_ID,
            DefectKind.INVALID_ENUM,
            DefectKind.DURATION_OUT_OF_RANGE,
            DefectKind.ACTIVITY_TS_OUT_OF_RANGE,
            DefectKind.UNKNOWN_ADVISOR,
            DefectKind.LATE_ARRIVING,
            DefectKind.RESENT_UPDATE,
            DefectKind.EXACT_DUPLICATE,
        ):
            for index in _select(available, rates[kind], rng):
                original = rows[index]
                key = original["ACTIVITY_ID"]
                column: str | None
                rule: str | None
                expected: str | None
                if kind is DefectKind.EXACT_DUPLICATE:
                    rows.append(dict(original))
                    position, column, raw, expected = len(rows) - 1, None, None, None
                    rule, action = "DQ010", DqAction.DEDUPE
                elif kind is DefectKind.RESENT_UPDATE:
                    copy = dict(original)
                    previous = str(copy["STATUS"])
                    copy["STATUS"] = "CANCELLED" if previous != "CANCELLED" else "COMPLETED"
                    copy["UPDATED_TS"] += timedelta(minutes=1)
                    rows.append(copy)
                    position, column, raw, expected = (
                        len(rows) - 1,
                        "STATUS",
                        previous,
                        copy["STATUS"],
                    )
                    rule, action = "DQ010", DqAction.DEDUPE
                else:
                    position = index
                    column, rule, action, expected = {
                        DefectKind.NULL_ACTIVITY_ID: (
                            "ACTIVITY_ID",
                            "DQ001",
                            DqAction.QUARANTINE,
                            None,
                        ),
                        DefectKind.INVALID_ENUM: (
                            "ACTIVITY_TYPE",
                            "DQ002",
                            DqAction.QUARANTINE,
                            None,
                        ),
                        DefectKind.DURATION_OUT_OF_RANGE: (
                            "DURATION_MIN",
                            "DQ003",
                            DqAction.QUARANTINE,
                            None,
                        ),
                        DefectKind.ACTIVITY_TS_OUT_OF_RANGE: (
                            "ACTIVITY_TS",
                            "DQ004",
                            DqAction.QUARANTINE,
                            None,
                        ),
                        DefectKind.UNKNOWN_ADVISOR: (
                            "ADVISOR_ID",
                            "DQ012",
                            DqAction.MAP_UNKNOWN,
                            "UNKNOWN",
                        ),
                        DefectKind.LATE_ARRIVING: (
                            "ACTIVITY_TS",
                            None,
                            DqAction.KEEP_FLAGGED,
                            None,
                        ),
                    }[kind]
                    raw = {
                        DefectKind.NULL_ACTIVITY_ID: None,
                        DefectKind.INVALID_ENUM: "EMAIL",
                        DefectKind.DURATION_OUT_OF_RANGE: -15,
                        DefectKind.ACTIVITY_TS_OUT_OF_RANGE: datetime(2014, 6, 2, tzinfo=UTC),
                        DefectKind.UNKNOWN_ADVISOR: "ADV-00000",
                        DefectKind.LATE_ARRIVING: original["ACTIVITY_TS"]
                        - timedelta(weeks=rng.randint(1, 3)),
                    }[kind]
                    rows[index][column] = raw
                    if kind is DefectKind.LATE_ARRIVING:
                        prior = raw.date().isocalendar()
                        expected = f"{prior.year}-W{prior.week:02d}"
                defects.append(
                    _note(
                        kind,
                        week,
                        "snowflake",
                        "activity",
                        file,
                        row=position,
                        natural_key=key,
                        column=column,
                        raw=raw,
                        expected=expected,
                        rule=rule,
                        action=action,
                        detail=f"{kind.value} in weekly activity extract.",
                    )
                )
                changed = True
        if changed:
            schema = pa.schema(
                [field.with_nullable(True) for field in table.schema],
                metadata=cast(dict[bytes | str, bytes | str] | None, table.schema.metadata),
            )
            pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")
    return defects


def _clients(
    root: Path,
    week: str,
    rates: Mapping[DefectKind, float],
    rng: random.Random,
    include_snapshot: bool,
) -> list[Defect]:
    defects: list[Defect] = []
    rate = rates[DefectKind.DIRTY_POSTAL_CODE]
    if not rate and not rates[DefectKind.UNPARSEABLE_VALUE]:
        return defects
    db = root / "teradata/edw.sqlite"
    if include_snapshot and db.exists() and rate:
        with sqlite3.connect(db) as conn:
            candidates = conn.execute(
                "SELECT CLNT_ID, PSTL_CD FROM CLNT WHERE PSTL_CD IS NOT NULL ORDER BY CLNT_ID"
            ).fetchall()
            candidates = [
                (key, value) for key, value in candidates if re.fullmatch(POSTAL_CODE, value)
            ]
            chosen = sorted(rng.sample(candidates, _count(len(candidates), rate, rng)))
            for ordinal, (key, original) in enumerate(chosen):
                label, transform = POSTAL_VARIANTS[ordinal % len(POSTAL_VARIANTS)]
                value = transform(original)
                conn.execute("UPDATE CLNT SET PSTL_CD = ? WHERE CLNT_ID = ?", (value, key))
                defects.append(
                    _note(
                        DefectKind.DIRTY_POSTAL_CODE,
                        week,
                        "teradata",
                        "CLNT",
                        "teradata/edw.sqlite",
                        row=None,
                        natural_key=key,
                        column="PSTL_CD",
                        raw=value,
                        expected=original if value not in ("90210", None) else "UNK",
                        rule="DQ011",
                        action=DqAction.NORMALIZE,
                        detail=f"Postal code variant: {label}.",
                    )
                )
    year, number = map(int, week.split("-W"))
    monday = date.fromisocalendar(year, number, 1)
    for day in (monday + timedelta(days=i) for i in range(7)):
        path = root / "teradata" / f"client_{day:%Y%m%d}.csv"
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames
            rows = list(reader)
        if fields is None:
            continue
        available = [
            i
            for i, row in enumerate(rows)
            if row["PSTL_CD"] and re.fullmatch(POSTAL_CODE, row["PSTL_CD"])
        ]
        changed = False
        for ordinal, index in enumerate(_select(available, rate, rng)):
            row = rows[index]
            original = row["PSTL_CD"]
            label, transform = POSTAL_VARIANTS[ordinal % len(POSTAL_VARIANTS)]
            value = transform(original)
            row["PSTL_CD"] = value or ""
            defects.append(
                _note(
                    DefectKind.DIRTY_POSTAL_CODE,
                    week,
                    "teradata",
                    "CLNT",
                    path.relative_to(root).as_posix(),
                    row=index,
                    natural_key=row["CLNT_ID"],
                    column="PSTL_CD",
                    raw=value,
                    expected=original if value not in ("90210", None) else "UNK",
                    rule="DQ011",
                    action=DqAction.NORMALIZE,
                    detail=f"Postal code variant: {label}.",
                )
            )
            changed = True
        for index in _select(available, rates[DefectKind.UNPARSEABLE_VALUE], rng):
            row = rows[index]
            row["BRTH_YR"] = "19S2"
            defects.append(
                _note(
                    DefectKind.UNPARSEABLE_VALUE,
                    week,
                    "teradata",
                    "CLNT",
                    path.relative_to(root).as_posix(),
                    row=index,
                    natural_key=row["CLNT_ID"],
                    column="BRTH_YR",
                    raw="19S2",
                    rule="DQ005",
                    action=DqAction.QUARANTINE,
                    detail="BRTH_YR does not parse.",
                )
            )
            changed = True
        if changed:
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
    return defects


def _source_events(
    root: Path,
    week: str,
    rates: Mapping[DefectKind, float],
    rng: random.Random,
    client_batch: ClientBatch | None,
    advisor_roster: AdvisorRoster | None,
) -> list[Defect]:
    """Record change events already produced by the upstream generators."""
    defects: list[Defect] = []
    year, number = map(int, week.split("-W"))
    if advisor_roster is not None:
        by_advisor: dict[str, list[Any]] = {}
        for event in advisor_roster.assignments:
            by_advisor.setdefault(event.advisor_id, []).append(event)
        kinds = {
            AssignmentReason.TRANSFER: DefectKind.ADVISOR_TRANSFER,
            AssignmentReason.PROMOTION: DefectKind.ADVISOR_PROMOTION,
            AssignmentReason.TERM: DefectKind.ADVISOR_TERM,
        }
        for events in by_advisor.values():
            events.sort(key=lambda event: (event.effective_date, event.assignment_id))
            for previous, event in itertools.pairwise(events):
                kind = kinds.get(event.reason_code)
                calendar = event.effective_date.isocalendar()
                if kind is None or (calendar.year, calendar.week) != (year, number):
                    continue
                if rng.random() >= rates[kind]:
                    continue
                column = "ROLE_CD" if kind is DefectKind.ADVISOR_PROMOTION else "BRNCH_ID"
                prior = previous.role_code if column == "ROLE_CD" else previous.branch_id
                current = event.role_code if column == "ROLE_CD" else event.branch_id
                defects.append(
                    _note(
                        kind,
                        week,
                        "teradata",
                        "ADVSR_ASGN",
                        "teradata/edw.sqlite",
                        row=None,
                        natural_key=event.assignment_id,
                        column=column,
                        raw=prior,
                        expected=str(current) if kind is not DefectKind.ADVISOR_TERM else None,
                        detail=(
                            f"{event.advisor_id} {event.reason_code.value} "
                            f"effective {event.effective_date}."
                        ),
                    )
                )
    if client_batch is not None:
        locations = {
            (day, row.client_id): (f"teradata/client_{day:%Y%m%d}.csv", index)
            for day, rows in delta_rows(client_batch).items()
            for index, row in enumerate(rows)
        }
        for change in client_batch.changes:
            if change.kind not in ("REASSIGNED", "ADVISOR_LEFT"):
                continue
            calendar = change.day.isocalendar()
            if (calendar.year, calendar.week) != (year, number):
                continue
            if rng.random() >= rates[DefectKind.CLIENT_REASSIGNMENT]:
                continue
            file, row = locations[(change.day, change.after.client_id)]
            if not (root / file).exists():
                continue
            defects.append(
                _note(
                    DefectKind.CLIENT_REASSIGNMENT,
                    week,
                    "teradata",
                    "CLNT",
                    file,
                    row=row,
                    natural_key=change.after.client_id,
                    column="PRIM_ADVSR_ID",
                    raw=change.before.primary_advisor_id if change.before else None,
                    expected=change.after.primary_advisor_id,
                    detail="Book history changes as of week end.",
                )
            )
    return defects


def inject_dirt(
    sources_root: Path,
    defects_root: Path,
    *,
    iso_week_id: str,
    seed: int,
    rates: Mapping[DefectKind, float] | None = None,
    include_client_snapshot: bool = False,
    client_batch: ClientBatch | None = None,
    advisor_roster: AdvisorRoster | None = None,
) -> DefectManifest:
    """Mutate clean extracts in place and write a contract-validated weekly manifest.

    The caller enables snapshot injection only for its initial week. Later weeks only
    touch their own client deltas. HR and book changes are generated upstream.
    """
    year, number = map(int, iso_week_id.split("-W"))
    monday = date.fromisocalendar(year, number, 1)
    configured = dict(DEFAULT_RATES if rates is None else rates)
    if set(configured) != set(DefectKind):
        raise ValueError("rates must configure every defect kind")
    if any(
        isinstance(rate, bool) or not math.isfinite(rate) or not 0 <= rate <= 1
        for rate in configured.values()
    ):
        raise ValueError("every defect rate must be finite and within [0, 1]")
    manifest_path = defects_root / f"{iso_week_id}.json"
    if manifest_path.exists():
        existing = DefectManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if existing.seed != seed or existing.iso_weeks != [iso_week_id]:
            raise ValueError("existing defect manifest belongs to another seed or week")
        return existing
    rng_seed = int.from_bytes(hashlib.sha256(f"{seed}|{iso_week_id}".encode()).digest()[:8], "big")
    rng = random.Random(rng_seed)
    defects = _activity(sources_root, iso_week_id, configured, rng)
    defects += _clients(sources_root, iso_week_id, configured, rng, include_client_snapshot)
    defects += _source_events(
        sources_root, iso_week_id, configured, rng, client_batch, advisor_roster
    )
    defects.sort(key=lambda d: (d.file, -1 if d.row is None else d.row, d.kind.value))
    manifest = DefectManifest(
        generated_at=datetime.combine(monday + timedelta(days=7), time(3), tzinfo=UTC),
        seed=seed,
        iso_weeks=[iso_week_id],
        defects=defects,
    )
    defects_root.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest
