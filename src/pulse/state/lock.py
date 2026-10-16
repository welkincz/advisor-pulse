"""Run lock: one JSON object in R2, written with conditional puts so only one run holds it.

``If-None-Match: *`` creates the lock only when none exists. An expired lock is taken over
with ``If-Match: <etag>``, so two runs racing for the same stale lock cannot both win.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from pulse.state.store import ObjectStore, PreconditionFailed

LOCK_KEY = "lock.json"
LOCK_TTL = timedelta(hours=2)


@dataclass(frozen=True)
class LockInfo:
    run_id: str
    token: str
    acquired_at: datetime
    expires_at: datetime

    def to_json(self) -> bytes:
        return json.dumps(
            {
                "run_id": self.run_id,
                "token": self.token,
                "acquired_at": self.acquired_at.isoformat(),
                "expires_at": self.expires_at.isoformat(),
            }
        ).encode()

    @classmethod
    def from_json(cls, body: bytes) -> LockInfo:
        doc = json.loads(body)
        return cls(
            run_id=doc["run_id"],
            token=doc["token"],
            acquired_at=datetime.fromisoformat(doc["acquired_at"]),
            expires_at=datetime.fromisoformat(doc["expires_at"]),
        )


@dataclass(frozen=True)
class Acquired:
    lock: LockInfo
    took_over: LockInfo | None = None  # the expired lock this run replaced, if any


@dataclass(frozen=True)
class Held:
    holder: LockInfo


def acquire(
    store: ObjectStore, run_id: str, token: str, now: datetime, ttl: timedelta = LOCK_TTL
) -> Acquired | Held:
    """Take the lock, or report who holds it. Re-acquiring with the same token is a no-op,
    so a retried restore does not lock itself out."""
    mine = LockInfo(run_id, token, now, now + ttl)
    for _ in range(3):
        try:
            store.put(LOCK_KEY, mine.to_json(), if_none_match=True)
            return Acquired(mine)
        except PreconditionFailed:
            pass
        current = store.get(LOCK_KEY)
        if current is None:  # released between our put and get; try again
            continue
        body, etag = current
        holder = LockInfo.from_json(body)
        if holder.token == token:
            return Acquired(holder)
        if now < holder.expires_at:
            return Held(holder)
        try:
            store.put(LOCK_KEY, mine.to_json(), if_match=etag)
            return Acquired(mine, took_over=holder)
        except PreconditionFailed:
            continue  # another run took it over first; re-read
    current = store.get(LOCK_KEY)
    if current is None:
        raise RuntimeError("Run lock kept changing; giving up.")
    return Held(LockInfo.from_json(current[0]))


def holder(store: ObjectStore) -> LockInfo | None:
    current = store.get(LOCK_KEY)
    return LockInfo.from_json(current[0]) if current else None


def release(store: ObjectStore, token: str) -> bool:
    """Delete the lock if this token still holds it. False when another run holds it now."""
    current = holder(store)
    if current is None or current.token != token:
        return False
    store.delete(LOCK_KEY)
    return True
