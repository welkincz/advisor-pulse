"""Keep seeded client history exact while bounding repeated hierarchy lookups (#349)."""

import hashlib
import json
from collections import Counter
from unittest.mock import Mock

import pytest

from pulse.generate.advisors import assignment_ranges, generate_advisors
from pulse.generate.cli import Sizes, build_world
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
