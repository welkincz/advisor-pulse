"""Dirt injection preserves source files at zero rate and records exact source rows."""

from __future__ import annotations

import csv
import hashlib
import re
import shutil
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pulse.contracts.defects import DefectKind, DefectManifest
from pulse.contracts.enums import AssignmentReason, DqAction, Role
from pulse.contracts.sources import TeradataAssignment
from pulse.generate.advisors import (
    AdvisorRoster,
    assignment_ranges,
    generate_advisors,
    write_advisors,
)
from pulse.generate.clients import generate_clients, write_clients
from pulse.generate.dirt import inject_dirt
from pulse.reference import org

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/sources"
WEEK = "2026-W37"


def _sources(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    shutil.copytree(FIXTURES, root)
    return root


def _files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _rates(**enabled: float) -> dict[DefectKind, float]:
    upstream = {
        DefectKind.ADVISOR_TRANSFER,
        DefectKind.ADVISOR_PROMOTION,
        DefectKind.ADVISOR_TERM,
        DefectKind.CLIENT_REASSIGNMENT,
    }
    return {kind: enabled.get(kind.value, 0.0) for kind in DefectKind if kind not in upstream}


def test_zero_rates_leave_fixture_files_identical_and_write_empty_manifest(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    before = _files(sources)
    manifest = inject_dirt(sources, tmp_path / "defects", iso_week_id=WEEK, seed=7, rates=_rates())

    assert _files(sources) == before
    assert manifest.defects == []
    assert (
        DefectManifest.model_validate_json((tmp_path / "defects/2026-W37.json").read_text())
        == manifest
    )


def test_activity_mutations_identify_written_rows_and_rule_ids(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    manifest = inject_dirt(
        sources,
        tmp_path / "defects",
        iso_week_id=WEEK,
        seed=7,
        rates=_rates(EXACT_DUPLICATE=0.1, NULL_ACTIVITY_ID=0.1, UNKNOWN_ADVISOR=0.1),
    )
    relevant = {DefectKind.EXACT_DUPLICATE, DefectKind.NULL_ACTIVITY_ID, DefectKind.UNKNOWN_ADVISOR}
    assert {d.kind for d in manifest.defects} == relevant
    rows_by_file = {
        str(path.relative_to(sources)): pq.read_table(path).to_pylist()
        for path in sources.glob("snowflake/activity/extract_date=2026-09-13/*.parquet")
    }
    for defect in manifest.defects:
        assert defect.rule_id in {"DQ001", "DQ010", "DQ012"}
        assert defect.row is not None
        row = rows_by_file[defect.file][defect.row]
        if defect.kind is DefectKind.NULL_ACTIVITY_ID:
            assert row["ACTIVITY_ID"] is None
        elif defect.kind is DefectKind.UNKNOWN_ADVISOR:
            assert row["ADVISOR_ID"] == defect.raw_value == "ADV-00000"
        else:
            assert sum(r == row for r in rows_by_file[defect.file]) == 2


def test_uses_activity_writer_next_monday_extract_date(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    sunday = sources / "snowflake/activity/extract_date=2026-09-13"
    monday = sources / "snowflake/activity/extract_date=2026-09-14"
    sunday.rename(monday)
    manifest = inject_dirt(
        sources,
        tmp_path / "defects",
        iso_week_id=WEEK,
        seed=3,
        rates=_rates(NULL_ACTIVITY_ID=0.2),
    )
    assert manifest.defects
    assert all("extract_date=2026-09-14" in d.file for d in manifest.defects)


def test_postal_variants_reconcile_to_written_snapshot_rows(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    with sqlite3.connect(sources / "teradata/edw.sqlite") as conn:
        conn.execute("UPDATE CLNT SET PSTL_CD = 'M5V 3L9'")
    manifest = inject_dirt(
        sources,
        tmp_path / "defects",
        iso_week_id=WEEK,
        seed=4,
        rates=_rates(DIRTY_POSTAL_CODE=1.0),
        include_client_snapshot=True,
    )
    postal = [
        d
        for d in manifest.defects
        if d.kind is DefectKind.DIRTY_POSTAL_CODE and d.file == "teradata/edw.sqlite"
    ]
    assert postal
    with sqlite3.connect(sources / "teradata/edw.sqlite") as conn:
        actual = dict(conn.execute("SELECT CLNT_ID, PSTL_CD FROM CLNT"))
    assert {"m5v3l9", "M5V3L9", "M5V-3L9", "M5V 3L9 ", "90210", None} <= {
        actual[d.natural_key] for d in postal
    }
    assert all(d.row is None and d.rule_id == "DQ011" for d in postal)
    assert all(actual[d.natural_key] == d.raw_value for d in postal)


def test_same_seed_and_week_reproduce_sources_and_manifest(tmp_path: Path) -> None:
    results = []
    for index in range(2):
        root = tmp_path / str(index)
        sources = _sources(root)
        manifest = inject_dirt(
            sources,
            root / "defects",
            iso_week_id=WEEK,
            seed=19,
            rates=_rates(EXACT_DUPLICATE=0.08, RESENT_UPDATE=0.08, DIRTY_POSTAL_CODE=0.08),
        )
        results.append((_files(sources), manifest, (root / "defects/2026-W37.json").read_bytes()))
    assert results[0] == results[1]


def test_completed_week_retry_does_not_inject_again(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    kwargs = dict(
        iso_week_id=WEEK,
        seed=19,
        rates=_rates(
            EXACT_DUPLICATE=0.1, RESENT_UPDATE=0.1, NULL_ACTIVITY_ID=0.1, DIRTY_POSTAL_CODE=0.1
        ),
    )
    first = inject_dirt(sources, tmp_path / "defects", **kwargs)
    before = _files(sources)
    manifest_bytes = (tmp_path / "defects/2026-W37.json").read_bytes()
    assert inject_dirt(sources, tmp_path / "defects", **kwargs) == first
    assert _files(sources) == before
    assert (tmp_path / "defects/2026-W37.json").read_bytes() == manifest_bytes


@pytest.mark.parametrize(
    ("kind", "column", "rule", "written"),
    [
        (DefectKind.INVALID_ENUM, "ACTIVITY_TYPE", "DQ002", "EMAIL"),
        (DefectKind.DURATION_OUT_OF_RANGE, "DURATION_MIN", "DQ003", -15),
        (DefectKind.ACTIVITY_TS_OUT_OF_RANGE, "ACTIVITY_TS", "DQ004", 2014),
        (DefectKind.LATE_ARRIVING, "ACTIVITY_TS", None, 2026),
        (DefectKind.RESENT_UPDATE, "STATUS", "DQ010", "BOOKED"),
    ],
)
def test_each_activity_defect_has_written_evidence(
    tmp_path: Path, kind: DefectKind, column: str, rule: str | None, written: str | int
) -> None:
    sources = _sources(tmp_path)
    manifest = inject_dirt(
        sources,
        tmp_path / "defects",
        iso_week_id=WEEK,
        seed=12,
        rates=_rates(**{kind.value: 0.2}),
    )
    assert manifest.defects and {d.kind for d in manifest.defects} == {kind}
    for defect in manifest.defects:
        row = pq.read_table(sources / defect.file).to_pylist()[defect.row]
        assert defect.column == column and defect.rule_id == rule
        if kind is DefectKind.RESENT_UPDATE:
            assert row["STATUS"] == defect.raw_value == "BOOKED"
            assert row["ACTIVITY_TYPE"] == "APPOINTMENT"
            assert row["OUTCOME"] is row["PRODUCT_LINE"] is row["DURATION_MIN"] is None
            final = next(
                r
                for r in pq.read_table(sources / defect.file).to_pylist()
                if r["ACTIVITY_ID"] == defect.natural_key and r["STATUS"] != "BOOKED"
            )
            assert final["STATUS"] == defect.expected_value
            assert final["UPDATED_TS"] > row["UPDATED_TS"]
            assert row["ACTIVITY_TS"] == row["CREATED_TS"]
        elif kind in (DefectKind.LATE_ARRIVING, DefectKind.ACTIVITY_TS_OUT_OF_RANGE):
            assert row[column].year == written
        else:
            assert row[column] == written


def test_late_rows_shift_whole_call_and_keep_toronto_week(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    before = {
        row["ACTIVITY_ID"]: row
        for path in sources.glob("snowflake/activity/extract_date=2026-09-13/*.parquet")
        for row in pq.read_table(path).to_pylist()
        if row["ACTIVITY_ID"]
    }
    booked = {
        row["BOOKED_FROM_ACTIVITY_ID"] for row in before.values() if row["BOOKED_FROM_ACTIVITY_ID"]
    }
    manifest = inject_dirt(
        sources,
        tmp_path / "defects",
        iso_week_id=WEEK,
        seed=8,
        rates=_rates(LATE_ARRIVING=1.0),
    )
    late = [d for d in manifest.defects if d.kind is DefectKind.LATE_ARRIVING]
    assert late
    toronto = ZoneInfo("America/Toronto")
    for defect in late:
        row = pq.read_table(sources / defect.file).to_pylist()[defect.row]
        old = before[defect.natural_key]
        assert row["ACTIVITY_TYPE"] == "CALL_IN"
        assert defect.natural_key not in booked
        offset = old["ACTIVITY_TS"] - row["ACTIVITY_TS"]
        assert timedelta(weeks=1) <= offset <= timedelta(weeks=3)
        assert all(
            old[column] - row[column] == offset
            for column in ("ACTIVITY_TS", "CREATED_TS", "UPDATED_TS")
        )
        if old["SCHEDULED_TS"] is not None:
            assert old["SCHEDULED_TS"] - row["SCHEDULED_TS"] == offset
        day = row["ACTIVITY_TS"].astimezone(toronto).date().isocalendar()
        assert defect.expected_value == f"{day.year}-W{day.week:02d}"


def test_late_row_requires_advisor_assignment_on_shifted_date(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    row = next(
        row
        for path in sources.glob("snowflake/activity/extract_date=2026-09-13/*.parquet")
        for row in pq.read_table(path).to_pylist()
        if row["ACTIVITY_TYPE"] == "CALL_IN"
    )

    def roster(start: date) -> AdvisorRoster:
        assignment = TeradataAssignment(
            ASGN_ID="ASG-00000001",
            ADVSR_ID=row["ADVISOR_ID"],
            BRNCH_ID=row["BRANCH_ID"],
            ROLE_CD=Role.ADVISOR,
            EFF_DT=start,
            RSN_CD=AssignmentReason.HIRE,
            LAST_UPD_TS=datetime(2026, 9, 7, tzinfo=UTC),
        )
        return AdvisorRoster(advisors=(), assignments=(assignment,), branches=())

    absent = inject_dirt(
        sources,
        tmp_path / "absent",
        iso_week_id=WEEK,
        seed=8,
        rates=_rates(LATE_ARRIVING=1.0),
        advisor_roster=roster(date(2026, 9, 7)),
    )
    assert absent.defects == []
    eligible = inject_dirt(
        sources,
        tmp_path / "eligible",
        iso_week_id=WEEK,
        seed=8,
        rates=_rates(LATE_ARRIVING=1.0),
        advisor_roster=roster(date(2026, 8, 1)),
    )
    assert eligible.defects
    assert {d.natural_key for d in eligible.defects} <= {
        r["ACTIVITY_ID"]
        for path in sources.glob("snowflake/activity/extract_date=2026-09-13/*.parquet")
        for r in pq.read_table(path).to_pylist()
        if r["ADVISOR_ID"] == row["ADVISOR_ID"]
    }


def test_late_expected_week_uses_toronto_sunday(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    path = next(sources.glob("snowflake/activity/extract_date=2026-09-13/*.parquet"))
    table = pq.read_table(path)
    rows = table.to_pylist()
    booked = {r["BOOKED_FROM_ACTIVITY_ID"] for r in rows if r["BOOKED_FROM_ACTIVITY_ID"]}
    target = next(
        r for r in rows if r["ACTIVITY_TYPE"] == "CALL_IN" and r["ACTIVITY_ID"] not in booked
    )
    target["ACTIVITY_TS"] = datetime(2026, 9, 14, 1, tzinfo=UTC)
    target["CREATED_TS"] = target["ACTIVITY_TS"]
    target["UPDATED_TS"] = target["ACTIVITY_TS"]
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path, compression="zstd")
    manifest = inject_dirt(
        sources,
        tmp_path / "defects",
        iso_week_id=WEEK,
        seed=8,
        rates=_rates(LATE_ARRIVING=1.0),
    )
    defect = next(d for d in manifest.defects if d.natural_key == target["ACTIVITY_ID"])
    utc_week = datetime.fromisoformat(defect.raw_value).date().isocalendar()
    assert defect.expected_value != f"{utc_week.year}-W{utc_week.week:02d}"
    assert defect.expected_value in {"2026-W36", "2026-W35", "2026-W34"}


def test_unparseable_client_delta_has_exact_csv_row(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    manifest = inject_dirt(
        sources,
        tmp_path / "defects",
        iso_week_id=WEEK,
        seed=9,
        rates=_rates(UNPARSEABLE_VALUE=1.0),
    )
    defects = manifest.defects
    assert defects and {d.kind for d in defects} == {DefectKind.UNPARSEABLE_VALUE}
    for defect in defects:
        with (sources / defect.file).open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[defect.row]["CLNT_ID"] == defect.natural_key
        assert rows[defect.row]["BRTH_YR"] == "19S2"
        assert defect.rule_id == "DQ005" and defect.action == "QUARANTINE"


def test_upstream_assignment_and_book_changes_are_recorded_at_source_keys(tmp_path: Path) -> None:
    roster = generate_advisors(org(), seed=29, advisor_count=80, weeks=104)
    batch = generate_clients(
        org(), assignment_ranges(roster), seed=29, client_count=5000, weeks=104
    )
    sources = tmp_path / "sources"
    db = sources / "teradata/edw.sqlite"
    write_advisors(roster, db)
    write_clients(batch, db)
    rates = _rates()

    def manifest_for(day):
        week = day.isocalendar()
        return inject_dirt(
            sources,
            tmp_path / "defects",
            iso_week_id=f"{week.year}-W{week.week:02d}",
            seed=29,
            rates=rates,
            advisor_roster=roster,
            client_batch=batch,
        )

    kinds = {
        AssignmentReason.TRANSFER: DefectKind.ADVISOR_TRANSFER,
        AssignmentReason.PROMOTION: DefectKind.ADVISOR_PROMOTION,
        AssignmentReason.TERM: DefectKind.ADVISOR_TERM,
    }
    for reason, kind in kinds.items():
        event = next(e for e in roster.assignments if e.reason_code == reason)
        defect = next(
            d
            for d in manifest_for(event.effective_date).defects
            if d.natural_key == event.assignment_id
        )
        assert defect.kind is kind
        assert defect.file == "teradata/edw.sqlite" and defect.row is None
        with sqlite3.connect(db) as conn:
            column = "ROLE_CD" if kind is DefectKind.ADVISOR_PROMOTION else "BRNCH_ID"
            written = conn.execute(
                f"SELECT {column} FROM ADVSR_ASGN WHERE ASGN_ID = ?", (event.assignment_id,)
            ).fetchone()[0]
        if kind is not DefectKind.ADVISOR_TERM:
            assert written == defect.expected_value
    change = next(c for c in batch.changes if c.kind == "REASSIGNED")
    reassigned = [
        d for d in manifest_for(change.day).defects if d.kind is DefectKind.CLIENT_REASSIGNMENT
    ]
    assert any(d.natural_key == change.after.client_id for d in reassigned)
    for defect in reassigned:
        with (sources / defect.file).open(newline="", encoding="utf-8") as handle:
            row = list(csv.DictReader(handle))[defect.row]
        assert row["CLNT_ID"] == defect.natural_key
        assert row["PRIM_ADVSR_ID"] == defect.expected_value


@pytest.mark.parametrize("rate", [-0.1, 1.1, float("nan")])
def test_reject_invalid_rate_without_modifying_sources(tmp_path: Path, rate: float) -> None:
    sources = _sources(tmp_path)
    before = _files(sources)
    with pytest.raises(ValueError, match="rate"):
        inject_dirt(
            sources,
            tmp_path / "defects",
            iso_week_id=WEEK,
            seed=7,
            rates=_rates(EXACT_DUPLICATE=rate),
        )
    assert _files(sources) == before


def test_upstream_event_rates_cannot_hide_existing_events(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    with pytest.raises(ValueError, match="only the defects injected"):
        inject_dirt(
            sources,
            tmp_path / "defects",
            iso_week_id=WEEK,
            seed=7,
            rates={**_rates(), DefectKind.ADVISOR_TRANSFER: 0.5},
        )


def test_late_rows_never_predate_the_history_start(tmp_path: Path) -> None:
    # #233: the first extracts' late rows used to land in the weeks before history began.
    monday = date.fromisocalendar(2026, 37, 1)
    clamped = inject_dirt(
        _sources(tmp_path / "a"),
        tmp_path / "clamped",
        iso_week_id=WEEK,
        seed=8,
        rates=_rates(LATE_ARRIVING=1.0),
        history_start=monday,
    )
    assert not [d for d in clamped.defects if d.kind is DefectKind.LATE_ARRIVING]
    open_start = inject_dirt(
        _sources(tmp_path / "b"),
        tmp_path / "open",
        iso_week_id=WEEK,
        seed=8,
        rates=_rates(LATE_ARRIVING=1.0),
        history_start=monday - timedelta(weeks=3),
    )
    assert [d for d in open_start.defects if d.kind is DefectKind.LATE_ARRIVING]


def test_unknown_portfolio_is_injected_and_recorded(tmp_path: Path) -> None:
    # DQ014: a CLNT delta row naming a portfolio the master lacks (#230).
    sources = _sources(tmp_path)
    path = sources / "teradata/client_20260913.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    assert fields is not None and rows
    for row in rows:
        row["PRTF_ID"] = "PRT-000001"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    manifest = inject_dirt(
        sources,
        tmp_path / "defects",
        iso_week_id=WEEK,
        seed=8,
        rates=_rates(UNKNOWN_PORTFOLIO=1.0),
    )
    found = [d for d in manifest.defects if d.kind is DefectKind.UNKNOWN_PORTFOLIO]
    assert len(found) == len(rows)
    assert {(d.rule_id, d.action, d.expected_value) for d in found} == {
        ("DQ014", DqAction.MAP_UNKNOWN, "PRT-000001")
    }
    with path.open(newline="", encoding="utf-8") as handle:
        written = [r["PRTF_ID"] for r in csv.DictReader(handle)]
    assert [d.raw_value for d in sorted(found, key=lambda d: d.row or 0)] == written
    assert all(re.fullmatch(r"PRT-8\d{5}", value) for value in written)
