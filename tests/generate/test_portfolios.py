"""Portfolio ownership is a source history, independent of client reassignment."""

from datetime import date, timedelta

import pytest

from pulse.contracts.enums import PortfolioAssignmentReason, Role
from pulse.generate.clients import generate_clients
from pulse.generate.portfolios import generate_portfolios, holder_as_of
from pulse.reference import org

START = date(2024, 10, 7)
BRANCH = org().branches[0].branch_id
OTHER = org().branches[1].branch_id


def roster():
    term = START + timedelta(days=14)
    transfer = START + timedelta(days=21)
    return (
        ("ADV-00001", BRANCH, Role.ADVISOR, START - timedelta(days=30), term),
        ("ADV-00002", BRANCH, Role.ADVISOR, START - timedelta(days=30), None),
        ("ADV-00003", BRANCH, Role.ADVISOR, START - timedelta(days=30), transfer),
        ("ADV-00003", OTHER, Role.ADVISOR, transfer, None),
        ("ADV-00004", BRANCH, Role.BRANCH_MANAGER, START - timedelta(days=30), None),
    )


def test_portfolio_history_hands_over_whole_book_and_retains_transit() -> None:
    portfolios = generate_portfolios(roster(), seed=19, start_date=START)
    initial = [p for p in portfolios.master if p.open_date < START]
    assert len(initial) == 3
    assert all(p.branch_id == BRANCH for p in initial)
    assert all(p.portfolio_id.startswith("PRT-") for p in portfolios.master)
    by_owner = {holder_as_of(portfolios, p.portfolio_id, START): p for p in initial}
    assert set(by_owner) == {"ADV-00001", "ADV-00002", "ADV-00003"}
    old = by_owner["ADV-00001"]
    events = [a for a in portfolios.assignments if a.portfolio_id == old.portfolio_id]
    assert [a.reason_code for a in events[:2]] == [
        PortfolioAssignmentReason.OPEN,
        PortfolioAssignmentReason.HANDOVER,
    ]
    assert events[1].effective_date == START + timedelta(days=15)
    assert holder_as_of(portfolios, old.portfolio_id, events[1].effective_date) in {
        "ADV-00002",
        "ADV-00003",
    }
    moved = by_owner["ADV-00003"]
    assert holder_as_of(portfolios, moved.portfolio_id, START + timedelta(days=21)) == "ADV-00002"
    assert [a.reason_code for a in portfolios.assignments if a.portfolio_id == moved.portfolio_id][
        -1
    ] == PortfolioAssignmentReason.TRANSFER


def test_clients_retain_portfolio_on_handover_and_change_it_on_reassignment() -> None:
    portfolios = generate_portfolios(roster(), seed=19, start_date=START)
    batch = generate_clients(
        org(),
        roster(),
        seed=19,
        client_count=500,
        start_date=START,
        weeks=8,
        portfolio_batch=portfolios,
    )
    assert all(client.portfolio_id for client in batch.snapshot)
    for change in batch.changes:
        assert change.after.primary_advisor_id == holder_as_of(
            portfolios, change.after.portfolio_id, change.day
        )
    handed = [c for c in batch.changes if c.kind == "ADVISOR_LEFT"]
    assert handed
    assert all(c.before and c.before.portfolio_id == c.after.portfolio_id for c in handed)
    moved = [c for c in batch.changes if c.kind == "REASSIGNED"]
    assert moved
    assert all(c.before and c.before.portfolio_id != c.after.portfolio_id for c in moved)
    assert all(c.after.portfolio_id for c in batch.changes)


def test_last_advisor_departure_has_no_invented_handover_holder() -> None:
    only = (("ADV-00001", BRANCH, Role.ADVISOR, START, START + timedelta(days=7)),)
    with pytest.raises(ValueError, match="no portfolio handover advisor"):
        generate_portfolios(only, seed=19, start_date=START)


def test_a_transfer_opens_a_portfolio_at_the_destination() -> None:
    portfolios = generate_portfolios(roster(), seed=19, start_date=START)
    opened = [p for p in portfolios.master if p.open_date >= START]
    assert [(p.portfolio_id, p.branch_id, p.open_date) for p in opened] == [
        ("PRT-900001", OTHER, START + timedelta(days=21))
    ]
    assert holder_as_of(portfolios, "PRT-900001", START + timedelta(days=21)) == "ADV-00003"
    assert holder_as_of(portfolios, "PRT-900001", START + timedelta(days=20)) is None
