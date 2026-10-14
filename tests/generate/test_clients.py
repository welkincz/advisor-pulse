"""Synthetic client master and changed-row delta behavior."""

from __future__ import annotations

import csv
import importlib
import re
import sqlite3
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from pulse.contracts import column_names
from pulse.contracts.enums import Role
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
        (f"ADV-{index:05d}", branch.branch_id, Role.ADVISOR, START, None)
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
    for client in dataset.clients:
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
        ("ADV-00001", branches[0].branch_id, Role.ADVISOR, START, switch),
        ("ADV-00002", branches[1].branch_id, Role.ADVISOR, switch, None),
    ]
    dataset = _clients_module().generate_clients(
        org(), roster, seed=4, client_count=5000, start_date=START, weeks=8
    )
    assert any(change.day >= switch and change.kind == "REASSIGNED" for change in dataset.changes)
    for change in dataset.changes:
        if change.kind in {"NEW", "REASSIGNED"} and change.day >= switch:
            assert change.after.primary_advisor_id == "ADV-00002"


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
        assert conn.execute("SELECT COUNT(*) FROM CLNT").fetchone()[0] == len(dataset.clients)
        assert [row[1] for row in conn.execute('PRAGMA table_info("CLNT")')] == column_names(
            TeradataClient
        )

    files = sorted(db_path.parent.glob("client_*.csv"))
    assert files
    assert len(files) == len({change.day for change in dataset.changes})
    csv_rows = 0
    for path in files:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames == column_names(TeradataClient)
            rows = list(reader)
        day = date.fromisoformat(path.stem.removeprefix("client_"))
        assert all(row["LAST_UPD_TS"].startswith(day.isoformat()) for row in rows)
        csv_rows += len(rows)
    assert csv_rows == len(dataset.changes)

    with pytest.raises(sqlite3.IntegrityError):
        duplicate = (dataset.clients[0], dataset.clients[0])
        module.write_clients(replace(dataset, clients=duplicate), db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM CLNT").fetchone()[0] == len(dataset.clients)
        assert conn.execute("SELECT ADVSR_ID FROM ADVSR").fetchall() == [("ADV-00001",)]
