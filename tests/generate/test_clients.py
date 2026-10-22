"""Synthetic client master and changed-row delta behavior."""

from __future__ import annotations

import csv
import importlib
import re
import sqlite3
import time
from collections import Counter
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from pulse.contracts import column_names
from pulse.contracts.enums import ClientStatus, Role
from pulse.contracts.patterns import POSTAL_CODE
from pulse.contracts.sources import TeradataClient
from pulse.reference import fsa_province, org

START = date(2024, 10, 7)


def _clients_module() -> Any:
    return importlib.import_module("pulse.generate.clients")


@pytest.fixture(scope="module")
def roster() -> list[tuple[str, str, Role, date, date | None]]:
    branches = [branch for district in org().districts[:4] for branch in district.branches[:2]]
    return [
        (f"ADV-{index:05d}", branch.branch_id, Role.ADVISOR, START - timedelta(days=30), None)
        for index, branch in enumerate(branches[:8], start=1)
    ]


@pytest.fixture(scope="module")
def dataset(roster: list[tuple[str, str, Role, date, date | None]]) -> Any:
    return _clients_module().generate_clients(
        org(), roster, seed=19, client_count=5000, start_date=START, weeks=104
    )


@pytest.mark.unit
def test_seed_repeats_and_changes_output(
    roster: list[tuple[str, str, Role, date, date | None]],
) -> None:
    generate = _clients_module().generate_clients
    first = generate(org(), roster, seed=19, client_count=200, start_date=START, weeks=13)
    again = generate(org(), roster, seed=19, client_count=200, start_date=START, weeks=13)
    changed = generate(org(), roster, seed=20, client_count=200, start_date=START, weeks=13)
    assert first == again
    assert first != changed


@pytest.mark.unit
def test_postal_province_contract_and_district_pool(dataset: Any) -> None:
    placement = {p.branch.branch_id: p for p in org().placements()}
    for client in dataset.snapshot:
        assert TeradataClient.model_validate(client.model_dump(by_alias=True)) == client
        assert client.postal_code is not None
        assert re.fullmatch(POSTAL_CODE, client.postal_code)
        assert fsa_province(client.postal_code[:3]) == client.province_code
        district = placement[client.primary_branch_id].district
        assert client.postal_code[:3] in {b.fsa_code for b in district.branches}


@pytest.mark.unit
def test_quarterly_reassignments_and_changed_rows_only(dataset: Any) -> None:
    changes = dataset.changes
    reasons = Counter(change.kind for change in changes)
    quarters = 8
    assert 0.015 <= reasons["REASSIGNED"] / (5000 * quarters) <= 0.025
    assert reasons["NEW"] > 0
    assert reasons["CLOSED"] > 0
    assert all(change.after.last_updated_ts.date() == change.day for change in changes)
    assert all(change.before != change.after for change in changes)
    assert reasons["ADVISOR_LEFT"] == 0  # this roster has no leavers
    for change in changes:
        if change.kind == "NEW":
            assert change.before is None
        elif change.kind == "CLOSED":
            assert change.before is not None and change.before.status_code == "A"
            assert change.after.status_code == "C"
        else:
            assert change.before is not None
            assert change.before.primary_advisor_id != change.after.primary_advisor_id
    assert all(change.day >= START for change in changes)
    assert all(change.day < START + timedelta(weeks=104) for change in changes)


@pytest.mark.unit
def test_roster_date_ranges_control_new_assignment() -> None:
    branches = org().branches
    switch = START + timedelta(days=14)
    roster = [
        ("ADV-00001", branches[0].branch_id, Role.ADVISOR, START - timedelta(days=1), switch),
        ("ADV-00002", branches[1].branch_id, Role.ADVISOR, switch, None),
    ]
    dataset = _clients_module().generate_clients(
        org(), roster, seed=4, client_count=5000, start_date=START, weeks=8
    )
    left = [c for c in dataset.changes if c.kind == "ADVISOR_LEFT"]
    assert left and {c.day for c in left} == {switch}  # the leaver's range ends on switch
    for change in dataset.changes:
        if change.kind in {"NEW", "REASSIGNED"} and change.day >= switch:
            assert change.after.primary_advisor_id == "ADV-00002"
    active = [c for c in dataset.final() if c.status_code == ClientStatus.ACTIVE]
    assert {c.primary_advisor_id for c in active} == {"ADV-00002"}


@pytest.mark.unit
def test_rejects_empty_active_roster() -> None:
    with pytest.raises(ValueError, match="active advisor"):
        _clients_module().generate_clients(org(), [], seed=1, client_count=100, start_date=START)


@pytest.mark.unit
def test_writer_preserves_other_tables_and_outputs_only_changed_csv_rows(
    tmp_path: Path, roster: list[tuple[str, str, Role, date, date | None]]
) -> None:
    module = _clients_module()
    dataset = module.generate_clients(
        org(), roster, seed=3, client_count=2000, start_date=START, weeks=13
    )
    db_path = tmp_path / "teradata" / "edw.sqlite"
    db_path.parent.mkdir()
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE ADVSR (ADVSR_ID TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO ADVSR VALUES ('ADV-00001')")

    module.write_clients(dataset, db_path)
    module.write_clients(dataset, db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT ADVSR_ID FROM ADVSR").fetchall() == [("ADV-00001",)]
        assert conn.execute("SELECT COUNT(*) FROM CLNT").fetchone()[0] == len(dataset.snapshot)
        assert [row[1] for row in conn.execute('PRAGMA table_info("CLNT")')] == column_names(
            TeradataClient
        )

    files = sorted(db_path.parent.glob("client_*.csv"))
    assert files
    deltas = module.delta_rows(dataset)
    assert len(files) == len(deltas)
    csv_rows = 0
    for path in files:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames == column_names(TeradataClient)
            rows = list(reader)
        day = date.fromisoformat(path.stem.removeprefix("client_"))
        assert all(row["LAST_UPD_TS"].startswith(day.isoformat()) for row in rows)
        csv_rows += len(rows)
    assert csv_rows == sum(len(rows) for rows in deltas.values())

    with pytest.raises(sqlite3.IntegrityError):
        duplicate = (dataset.snapshot[0], dataset.snapshot[0])
        module.write_clients(replace(dataset, snapshot=duplicate), db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM CLNT").fetchone()[0] == len(dataset.snapshot)
        assert conn.execute("SELECT ADVSR_ID FROM ADVSR").fetchall() == [("ADV-00001",)]


def _parse_ts(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


@pytest.mark.unit
def test_snapshot_is_the_day_before_start_and_deltas_are_strictly_later(dataset: Any) -> None:
    newest = max(c.last_updated_ts for c in dataset.snapshot)
    assert newest.date() < START
    assert all(c.client_since_date < START for c in dataset.snapshot)
    assert all(change.after.last_updated_ts > newest for change in dataset.changes)
    # The snapshot is the starting state, not the final one.
    assert dataset.final() != tuple(sorted(dataset.snapshot, key=lambda c: c.client_id))


@pytest.mark.unit
def test_incremental_load_on_last_upd_ts_rebuilds_the_final_state(
    tmp_path: Path, roster: list[tuple[str, str, Role, date, date | None]]
) -> None:
    """What #18 will do: load CLNT, then each CSV whose rows are past the watermark."""
    module = _clients_module()
    dataset = module.generate_clients(
        org(), roster, seed=8, client_count=3000, start_date=START, weeks=26
    )
    db_path = tmp_path / "edw.sqlite"
    module.write_clients(dataset, db_path)

    with closing(sqlite3.connect(db_path)) as conn:
        cols = [r[1] for r in conn.execute('PRAGMA table_info("CLNT")')]
        state = {
            row[0]: dict(zip(cols, row, strict=True))
            for row in conn.execute('SELECT * FROM "CLNT"')
        }
    watermark = max(_parse_ts(r["LAST_UPD_TS"]) for r in state.values())
    for path in sorted(tmp_path.glob("client_*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            rows = [r for r in csv.DictReader(handle) if _parse_ts(r["LAST_UPD_TS"]) > watermark]
        assert rows, f"{path.name} would be skipped by the watermark"
        for r in rows:
            state[r["CLNT_ID"]] = r
        watermark = max(_parse_ts(r["LAST_UPD_TS"]) for r in rows)

    expected = {c.client_id: (c.primary_advisor_id, c.status_code.value) for c in dataset.final()}
    assert {k: (v["PRIM_ADVSR_ID"], v["STAT_CD"]) for k, v in state.items()} == expected


@pytest.mark.unit
def test_writer_uses_teradata_text_conventions(
    tmp_path: Path, roster: list[tuple[str, str, Role, date, date | None]]
) -> None:
    module = _clients_module()
    dataset = module.generate_clients(
        org(), roster, seed=2, client_count=500, start_date=START, weeks=13
    )
    db_path = tmp_path / "edw.sqlite"
    module.write_clients(dataset, db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        ts, since = conn.execute('SELECT LAST_UPD_TS, CLNT_SINCE_DT FROM "CLNT" LIMIT 1').fetchone()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", ts)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", since)
    first = sorted(tmp_path.glob("client_*.csv"))[0]
    row = next(csv.DictReader(first.open(newline="", encoding="utf-8")))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} 12:00:00", row["LAST_UPD_TS"])


@pytest.fixture(scope="module")
def generated() -> Any:
    """Clients on top of the real advisor generator (#12)."""
    from pulse.generate.advisors import assignment_ranges, generate_advisors

    roster = generate_advisors(org(), seed=11, advisor_count=300, start_date=START, weeks=52)
    ranges = assignment_ranges(roster)
    batch = _clients_module().generate_clients(
        org(), ranges, seed=11, client_count=20_000, start_date=START, weeks=52
    )
    return ranges, batch


@pytest.mark.unit
def test_branch_managers_own_no_clients(generated: Any) -> None:
    ranges, batch = generated
    managers = {r[0] for r in ranges if r[2] == Role.BRANCH_MANAGER}
    assert managers
    owners = {c.primary_advisor_id for c in batch.snapshot}
    owners |= {ch.after.primary_advisor_id for ch in batch.changes}
    assert not owners & managers


@pytest.mark.unit
def test_leavers_books_change_holder_on_the_term_date(generated: Any) -> None:
    ranges, batch = generated
    starts = {(r[0], r[3]) for r in ranges}
    terms = {(r[0], r[4]) for r in ranges if r[4] is not None and (r[0], r[4]) not in starts}
    assert terms
    left = [c for c in batch.changes if c.kind == "ADVISOR_LEFT"]
    assert left
    for change in left:
        assert change.before is not None
        assert (change.before.primary_advisor_id, change.day) in terms
        assert change.before.portfolio_id == change.after.portfolio_id
    # A leaver's range excludes TERM_DT (advisors.assignment_ranges), so from that day on
    # no client may still name them.
    term_day = dict(terms)
    for change in batch.changes:
        owner = change.after.primary_advisor_id
        assert owner not in term_day or change.day < term_day[owner]
    active = [c for c in batch.final() if c.status_code == ClientStatus.ACTIVE]
    assert not {c.primary_advisor_id for c in active} & set(term_day)


@pytest.mark.slow
def test_default_scale_runs_in_under_30_seconds() -> None:
    from pulse.generate.advisors import assignment_ranges, generate_advisors

    t0 = time.perf_counter()
    ranges = assignment_ranges(generate_advisors(org(), seed=1))
    batch = _clients_module().generate_clients(org(), ranges, seed=1)
    assert time.perf_counter() - t0 < 30
    assert len(batch.snapshot) == 150_000
