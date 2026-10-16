"""Active synthetic client books reconstructed from a CLNT snapshot and deltas."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from pulse.contracts.enums import ClientStatus
from pulse.generate.clients import ClientBatch

ClientPools = tuple[dict[str, tuple[str, ...]], tuple[str, ...]]


def client_pools_by_day(batch: ClientBatch, days: Sequence[date]) -> dict[date, ClientPools]:
    """Return advisor books and all active IDs for one weekly run (at most seven days)."""
    requested = sorted(set(days))
    if len(requested) > 7:
        raise ValueError("client pools are limited to seven days per call")
    state = {client.client_id: client for client in batch.snapshot}
    changes = sorted(batch.changes, key=lambda change: change.day)
    cursor = 0
    pools: dict[date, ClientPools] = {}
    for day in requested:
        while cursor < len(changes) and changes[cursor].day <= day:
            client = changes[cursor].after
            state[client.client_id] = client
            cursor += 1
        books: dict[str, list[str]] = defaultdict(list)
        for client in state.values():
            if client.status_code is ClientStatus.ACTIVE and client.client_since_date <= day:
                books[client.primary_advisor_id].append(client.client_id)
        frozen_books = {owner: tuple(sorted(ids)) for owner, ids in books.items()}
        active = tuple(sorted(client_id for ids in frozen_books.values() for client_id in ids))
        if not active:
            raise ValueError(f"client_batch has no active clients on {day}")
        pools[day] = frozen_books, active
    return pools
