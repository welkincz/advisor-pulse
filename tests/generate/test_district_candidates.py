"""Keep seeded client history exact while bounding repeated hierarchy lookups (#349)."""

import hashlib
import json
from collections import Counter
from datetime import date, timedelta
from unittest.mock import Mock

import pytest

from pulse.generate.advisors import assignment_ranges, generate_advisors
from pulse.generate.cli import Sizes, build_world, clients_as_of
from pulse.generate.clients import generate_clients
from pulse.reference import BranchPlacement, OrgReference, org


@pytest.mark.parametrize(
    "seed,digest",
    [
        (7, "4c6baaeadc3483b7ad9b9a040370d422af7109f061ec28a3089847a890fbd10d"),
        (20261013, "a48779625fd04718a17a96855a14ef0dca49944dbd93cfc9f259558e754c39c1"),
    ],
)
def test_ordered_history_matches_pre_optimization_reference(seed: int, digest: str) -> None:
    """Digests captured from main e71a946; include every snapshot and change field."""
    world = build_world(seed, Sizes(advisors=120, clients=4000), "2026-W42")
    data = {
        "snapshot": [c.model_dump(mode="json") for c in world.clients.snapshot],
        "changes": [
            (
                c.day.isoformat(),
                c.kind,
                c.before.model_dump(mode="json") if c.before else None,
                c.after.model_dump(mode="json"),
            )
            for c in world.clients.changes
        ],
    }
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == digest


def test_district_lookup_work_depends_on_branches_not_reassignments() -> None:
    """A fixed hierarchy need not be traversed for every candidate of every move."""
    reference = org()
    reads: Counter[str] = Counter()

    class PlacementProbe:
        def __init__(self, placement: BranchPlacement):
            self.branch = placement.branch
            self._district = placement.district

        @property
        def district(self):
            reads[self.branch.branch_id] += 1
            return self._district

    placements = reference.placements()
    probe = Mock(spec=OrgReference, wraps=reference)
    probe.placements.return_value = tuple(PlacementProbe(p) for p in placements)
    roster = generate_advisors(reference, seed=19, advisor_count=120, weeks=26)
    batch = generate_clients(probe, assignment_ranges(roster), seed=19, client_count=4000, weeks=26)
    assert any(c.kind == "REASSIGNED" for c in batch.changes)
    assert sum(reads.values()) <= 4 * len(placements)


@pytest.mark.parametrize("seed", [7, 20261013])
@pytest.mark.parametrize("boundary", [date(2023, 10, 9), date(2026, 10, 12)])
def test_compact_history_preserves_boundary_and_every_retained_version(
    seed: int, boundary: date
) -> None:
    sizes = Sizes(advisors=120, clients=4000)
    full = build_world(seed, sizes, "2026-W42")
    compact = build_world(seed, sizes, "2026-W42", retain_from=boundary)
    state = {c.client_id: c for c in full.clients.snapshot}
    for change in full.clients.changes:
        if change.day < boundary:
            state[change.after.client_id] = change.after
    assert compact.clients.snapshot == tuple(state.values())
    end = date(2026, 10, 18)
    assert compact.clients.changes == tuple(
        c for c in full.clients.changes if boundary <= c.day <= end
    )
    assert compact.clients.final() == clients_as_of(full.clients, end)
    from pulse.generate.books import client_pools_by_day

    days = [boundary + timedelta(days=i) for i in range(5)]
    assert client_pools_by_day(compact.clients, days) == client_pools_by_day(full.clients, days)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_generation_restores_callers_gc_state(monkeypatch, tmp_path, enabled, fails) -> None:
    import gc

    from pulse.generate import cli

    original = gc.isenabled()
    (gc.enable if enabled else gc.disable)()

    def world(*args, **kwargs):
        assert not gc.isenabled()
        if fails:
            raise ValueError("synthetic failure")
        return object()

    monkeypatch.setattr(cli, "build_world", world)
    monkeypatch.setattr(cli, "generate_week", lambda *a, **k: None)
    try:
        if fails:
            with pytest.raises(ValueError, match="synthetic failure"):
                cli.generate_weeks(tmp_path, ["2026-W42"], seed=7)
        else:
            assert cli.generate_weeks(tmp_path, ["2026-W42"], seed=7, echo=lambda _: None) == 0
        assert gc.isenabled() == enabled
    finally:
        (gc.enable if original else gc.disable)()


def test_unchanged_days_reuse_the_same_active_roster(monkeypatch) -> None:
    from pulse.generate import clients

    roster = generate_advisors(org(), seed=19, advisor_count=120, weeks=26)
    ranges = assignment_ranges(roster)
    probe = Mock(wraps=clients._book_owners)
    monkeypatch.setattr(clients, "_book_owners", probe)
    clients.generate_clients(org(), ranges, seed=19, client_count=4000, weeks=26)
    transitions = {day for row in ranges for day in row[3:] if day is not None}
    assert probe.call_count <= len(transitions) + 2
