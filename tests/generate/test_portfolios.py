"""Portfolio ownership is a source history, independent of client reassignment."""

from datetime import date, timedelta

import pytest

from pulse.contracts.enums import PortfolioAssignmentReason, Role
from pulse.contracts.sources import TeradataClient
from pulse.generate.clients import generate_clients
from pulse.generate.portfolios import generate_portfolios, holder_as_of, holders_on
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
    assert events[1].effective_date == START + timedelta(days=14)  # the TERM date
    assert holder_as_of(portfolios, old.portfolio_id, events[1].effective_date) in {
        "ADV-00002",
        "ADV-00003",
    }
    moved = by_owner["ADV-00003"]
    assert holder_as_of(portfolios, moved.portfolio_id, START + timedelta(days=21)) == "ADV-00002"
    assert [a.reason_code for a in portfolios.assignments if a.portfolio_id == moved.portfolio_id][
        -1
    ] == PortfolioAssignmentReason.TRANSFER


def test_a_leavers_book_goes_to_the_colleague_holding_the_fewest_portfolios() -> None:
    """Two leavers hand four portfolios to two colleagues (one a new hire with an empty
    portfolio): each ends with two for every seed, where a random pick could give one three."""
    first, second = START + timedelta(days=14), START + timedelta(days=28)
    advisors = (
        ("ADV-00001", BRANCH, Role.ADVISOR, START - timedelta(days=30), first),
        ("ADV-00002", BRANCH, Role.ADVISOR, START - timedelta(days=30), None),
        ("ADV-00005", BRANCH, Role.ADVISOR, START - timedelta(days=30), second),
        ("ADV-00006", BRANCH, Role.ADVISOR, START + timedelta(days=21), None),
    )
    for seed in range(8):
        portfolios = generate_portfolios(advisors, seed=seed, start_date=START)
        holders = holders_on(portfolios, second)
        assert sorted(holders.values()).count("ADV-00002") == 2, seed
        assert sorted(holders.values()).count("ADV-00006") == 2, seed


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
    assert batch.portfolios == portfolios
    for change in batch.changes:
        assert holder_as_of(portfolios, change.after.portfolio_id, change.day) is not None
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


def test_a_portfolio_opened_mid_history_is_filled_from_its_branch() -> None:
    hire = START + timedelta(days=7)
    people = (
        ("ADV-00001", BRANCH, Role.ADVISOR, START - timedelta(days=30), None),
        ("ADV-00002", BRANCH, Role.ADVISOR, START - timedelta(days=30), None),
        ("ADV-00003", BRANCH, Role.ADVISOR, hire, None),  # joins with an empty portfolio
        ("ADV-00005", OTHER, Role.ADVISOR, hire, None),  # alone at its branch: no donors
    )
    portfolios = generate_portfolios(people, seed=19, start_date=START)
    batch = generate_clients(
        org(),
        people,
        seed=19,
        client_count=600,
        start_date=START,
        weeks=4,
        portfolio_batch=portfolios,
    )
    before = {c.client_id: c for c in batch.snapshot}

    def owner(client: TeradataClient) -> str | None:
        return batch.owner(client, START - timedelta(days=1))

    donors = {
        a: sum(1 for c in batch.snapshot if owner(c) == a and c.status_code == "A")
        for a in ("ADV-00001", "ADV-00002")
    }
    moved = [c for c in batch.changes if c.kind == "REBALANCED"]
    assert moved and all(c.day == hire for c in moved)
    assert {batch.owner(c.after, hire) for c in moved} == {"ADV-00003"}
    for advisor, size in donors.items():
        given = sum(1 for c in moved if owner(before[c.after.client_id]) == advisor)
        # 1 / (n + 1) with two donors, less clients closed or protected before the hire
        assert abs(given - size // 3) <= max(3, size // 20)
    # Nobody at ADV-00005's branch to give: no moves, and no error.
    assert not [c for c in moved if batch.owner(c.after, hire) == "ADV-00005"]


def test_every_portfolio_has_an_employed_holder_on_every_day() -> None:
    # A leaver's range excludes the TERM date, so the handover must land on it; a holder
    # who has already left (even for one day) owns a book nobody can work.
    rows = roster()
    portfolios = generate_portfolios(rows, seed=19, start_date=START)
    for offset in range(-1, 60):
        day = START + timedelta(days=offset)
        for portfolio in portfolios.master:
            if portfolio.open_date > day:
                continue
            holder = holder_as_of(portfolios, portfolio.portfolio_id, day)
            assert any(
                advisor == holder and start <= day and (end is None or day < end)
                for advisor, _, _, start, end in rows
            ), (portfolio.portfolio_id, day, holder)


def test_holders_on_matches_holder_as_of_every_day() -> None:
    portfolios = generate_portfolios(roster(), seed=19, start_date=START)
    for offset in range(-1, 30):
        day = START + timedelta(days=offset)
        expected = {
            p.portfolio_id: holder
            for p in portfolios.master
            if (holder := holder_as_of(portfolios, p.portfolio_id, day)) is not None
        }
        assert holders_on(portfolios, day) == expected
