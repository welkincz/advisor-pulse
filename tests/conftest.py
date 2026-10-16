"""Shared test setup."""

from __future__ import annotations

from pathlib import Path

import pytest

R2_VARS = ("R2_BUCKET", "R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A developer's real R2 or Anthropic credentials never reach a test (the live narrative
    test reads its key at import), and the export stage never publishes into the repo."""
    for name in (*R2_VARS, "ANTHROPIC_API_KEY", "PULSE_NARRATIVE_BACKEND"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PULSE_EXPORT_DIR", str(tmp_path / "web-data"))
