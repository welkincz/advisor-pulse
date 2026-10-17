"""Shared test setup."""

from __future__ import annotations

from pathlib import Path

import pytest

from pulse.generate import stage as generate_stage
from pulse.generate.cli import Sizes

R2_VARS = ("R2_BUCKET", "R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A developer's real R2 or Anthropic credentials never reach a test (the live narrative
    test reads its key at import), the export stage never publishes into the repo, and a
    real DAG on an empty data dir generates a small world instead of the default one."""
    for name in (*R2_VARS, "ANTHROPIC_API_KEY", "PULSE_NARRATIVE_BACKEND"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PULSE_EXPORT_DIR", str(tmp_path / "web-data"))
    monkeypatch.setattr(generate_stage, "SIZES", Sizes(advisors=120, clients=3000))
