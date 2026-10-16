"""Behavior tests for the synthetic advisor and assignment source."""

from __future__ import annotations

import importlib
import itertools
import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from pulse.contracts import column_names
from pulse.contracts.enums import AssignmentReason
from pulse.contracts.sources import TeradataAdvisor, TeradataAssignment, TeradataBranch
from pulse.reference import org

START = date(2024, 10, 7)


def _advisors_module() -> Any:
    return importlib.import_module("pulse.generate.advisors")


@pytest.fixture(scope="module")
def roster() -> Any:
    return _advisors_module().generate_advisors(
        org(), seed=17, advisor_count=900, start_date=START, weeks=104
    )


@pytest.mark.unit
def test_same_seed_and_inputs_give_identical_rows() -> None:
    generate = _advisors_module().generate_advisors
    first = generate(org(), seed=17, advisor_count=80, start_date=START, weeks=16)
    again = generate(org(), seed=17, advisor_count=80, start_date=START, weeks=16)
    different = generate(org(), seed=18, advisor_count=80, start_date=START, weeks=16)

    assert first == again
    assert first != different


@pytest.mark.unit
def test_invalid_scale_is_rejected() -> None:
    with pytest.raises(ValueError, match="advisor_count"):
        _advisors_module().generate_advisors(org(), seed=1, advisor_count=0)


@pytest.mark.unit
def test_default_scale_has_one_hire_and_ordered_nonoverlapping_events(roster: Any) -> None:
    by_advisor: dict[str, list[TeradataAssignment]] = defaultdict(list)
    for event in roster.assignments:
        by_advisor[event.advisor_id].append(event)

    assert len(_advisors_module().assignments_as_of(roster, START)) == 900
    assert len(roster.advisors) > 900  # Terminations are replaced with new hires.
    assert {a.advisor_id for a in roster.advisors} == set(by_advisor)
    for advisor in roster.advisors:
        events = by_advisor[advisor.advisor_id]
        assert [event.effective_date for event in events] == sorted(
            {event.effective_date for event in events}
        )
        assert sum(e.reason_code == AssignmentReason.HIRE for e in events) == 1
        assert events[0].reason_code == AssignmentReason.HIRE
        assert events[0].effective_date == advisor.hire_date
        if advisor.term_date is not None:
            assert events[-1].reason_code == AssignmentReason.TERM
            assert events[-1].effective_date == advisor.term_date


@pytest.mark.unit
def test_transfer_rate_and_geography_over_104_weeks(roster: Any) -> None:
    placements = {p.branch.branch_id: p for p in org().placements()}
    by_advisor: dict[str, list[TeradataAssignment]] = defaultdict(list)
    for event in roster.assignments:
        by_advisor[event.advisor_id].append(event)

    transfers = 0
    within_district = 0
    cross_region = 0
    for events in by_advisor.values():
        for previous, current in itertools.pairwise(events):
            if current.reason_code != AssignmentReason.TRANSFER:
                continue
            transfers += 1
            assert previous.branch_id != current.branch_id
            old = placements[previous.branch_id]
            new = placements[current.branch_id]
            within_district += old.district.district_code == new.district.district_code
            cross_region += old.region.region_code != new.region.region_code

    assert 0.012 <= transfers / (900 * 24) <= 0.018
    assert within_district > transfers / 2
    assert cross_region > 0
    assert any(e.reason_code == AssignmentReason.PROMOTION for e in roster.assignments)
    assert any(e.reason_code == AssignmentReason.TERM for e in roster.assignments)


@pytest.mark.unit
def test_as_of_assignment_uses_exclusive_end_at_transfer_and_term(roster: Any) -> None:
    module = _advisors_module()
    transfer = next(e for e in roster.assignments if e.reason_code == AssignmentReason.TRANSFER)
    before = {
        row[0]: row
        for row in module.assignments_as_of(roster, transfer.effective_date - timedelta(days=1))
    }
    after = {row[0]: row for row in module.assignments_as_of(roster, transfer.effective_date)}
    assert before[transfer.advisor_id][1] != after[transfer.advisor_id][1]
    assert before[transfer.advisor_id][4] == transfer.effective_date
    assert after[transfer.advisor_id][3] == transfer.effective_date

    term = next(e for e in roster.assignments if e.reason_code == AssignmentReason.TERM)
    before_term = {
        row[0] for row in module.assignments_as_of(roster, term.effective_date - timedelta(days=1))
    }
    after_term = {row[0] for row in module.assignments_as_of(roster, term.effective_date)}
    assert term.advisor_id in before_term
    assert term.advisor_id not in after_term
    assert len(after_term) == 900


@pytest.mark.unit
def test_generated_rows_follow_source_contracts(roster: Any) -> None:
    assert len(roster.branches) == len(org().branches)
    for rows, contract in (
        (roster.advisors, TeradataAdvisor),
        (roster.assignments, TeradataAssignment),
        (roster.branches, TeradataBranch),
    ):
        assert rows
        for row in rows:
            assert contract.model_validate(row.model_dump(by_alias=True)) == row


@pytest.mark.unit
def test_writer_replaces_only_owned_tables_and_preserves_client_table(tmp_path: Path) -> None:
    module = _advisors_module()
    roster = module.generate_advisors(org(), seed=23, advisor_count=40, start_date=START, weeks=12)
    db_path = tmp_path / "teradata" / "edw.sqlite"
    db_path.parent.mkdir()
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE CLNT (CLNT_ID TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO CLNT VALUES ('CLI-00000001')")

    module.write_advisors(roster, db_path)
    module.write_advisors(roster, db_path)
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables == {"ADVSR", "ADVSR_ASGN", "BRNCH", "CLNT"}
        assert conn.execute("SELECT CLNT_ID FROM CLNT").fetchall() == [("CLI-00000001",)]
        assert conn.execute("SELECT COUNT(*) FROM ADVSR").fetchone()[0] == len(roster.advisors)
        assert conn.execute("SELECT COUNT(*) FROM ADVSR_ASGN").fetchone()[0] == len(
            roster.assignments
        )
        assert conn.execute("SELECT COUNT(*) FROM BRNCH").fetchone()[0] == len(roster.branches)
        for table, contract in (
            ("ADVSR", TeradataAdvisor),
            ("ADVSR_ASGN", TeradataAssignment),
            ("BRNCH", TeradataBranch),
        ):
            assert [column[1] for column in conn.execute(f'PRAGMA table_info("{table}")')] == (
                column_names(contract)
            )
        advisor_types = {
            column[1]: column[2] for column in conn.execute('PRAGMA table_info("ADVSR")')
        }
        assert advisor_types["HIRE_DT"] == "DATE"
        assert advisor_types["LAST_UPD_TS"] == "TIMESTAMP"

    with pytest.raises(sqlite3.IntegrityError):
        module.write_advisors(
            replace(roster, assignments=(roster.assignments[0], roster.assignments[0])), db_path
        )
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ADVSR_ASGN").fetchone()[0] == len(
            roster.assignments
        )
        assert conn.execute("SELECT CLNT_ID FROM CLNT").fetchall() == [("CLI-00000001",)]


@pytest.mark.unit
def test_writer_uses_teradata_text_conventions(tmp_path: Path) -> None:
    """PLAN.md §6.2: naive UTC 'YYYY-MM-DD HH:MM:SS' timestamps and ISO dates, as in fixtures."""
    module = _advisors_module()
    roster = module.generate_advisors(org(), seed=5, advisor_count=40, start_date=START, weeks=30)
    db_path = tmp_path / "edw.sqlite"
    module.write_advisors(roster, db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        ts, hired = conn.execute("SELECT LAST_UPD_TS, HIRE_DT FROM ADVSR LIMIT 1").fetchone()
        terms = [r[0] for r in conn.execute("SELECT TERM_DT FROM ADVSR WHERE TERM_DT IS NOT NULL")]
        reasons = {r[0] for r in conn.execute("SELECT RSN_CD FROM ADVSR_ASGN")}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", ts)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", hired)
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", t) for t in terms)
    assert reasons <= {r.value for r in AssignmentReason}


@pytest.mark.unit
def test_assignment_ranges_cover_full_history(roster: Any) -> None:
    module = _advisors_module()
    ranges = module.assignment_ranges(roster)
    events = [e for e in roster.assignments if e.reason_code != AssignmentReason.TERM]
    assert len(ranges) == len(events)

    by_advisor: dict[str, list[Any]] = defaultdict(list)
    for r in ranges:
        by_advisor[r[0]].append(r)
    termed = {
        e.advisor_id: e.effective_date
        for e in roster.assignments
        if e.reason_code == AssignmentReason.TERM
    }
    for advisor_id, rows in by_advisor.items():
        # Contiguous: each range ends where the next begins.
        for prev, nxt in itertools.pairwise(rows):
            assert prev[4] == nxt[3]
        assert rows[-1][4] == termed.get(advisor_id)

    # as_of is exactly the ranges that contain the day.
    day = START + timedelta(weeks=50)
    assert set(module.assignments_as_of(roster, day)) == {
        r for r in ranges if r[3] <= day and (r[4] is None or day < r[4])
    }
