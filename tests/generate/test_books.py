"""As-of client book pools use the synthetic CLNT snapshot and daily deltas."""

from datetime import date

from pulse.contracts.enums import ClientStatus, Role
from pulse.generate.books import client_pools_by_day
from pulse.generate.clients import generate_clients
from pulse.reference import org


def test_active_books_follow_new_reassigned_and_closed_clients() -> None:
    roster = [
        (f"ADV-{index:05d}", branch.branch_id, Role.ADVISOR, date(2024, 10, 6), None)
        for index, branch in enumerate(org().branches[:8], 1)
    ]
    batch = generate_clients(org(), roster, seed=19, client_count=5000, weeks=13)
    days = [date(2024, 10, 7), date(2024, 12, 30)]
    pools = client_pools_by_day(batch, days)
    assert {change.kind for change in batch.changes} >= {"NEW", "REASSIGNED", "CLOSED"}
    for day in days:
        state = {client.client_id: client for client in batch.snapshot}
        for change in batch.changes:
            if change.day <= day:
                state[change.after.client_id] = change.after
        expected = {
            client.client_id: client.primary_advisor_id
            for client in state.values()
            if client.status_code is ClientStatus.ACTIVE and client.client_since_date <= day
        }
        books, active = pools[day]
        assert set(active) == set(expected)
        assert {client_id: owner for owner, ids in books.items() for client_id in ids} == expected
