"""Shared test setup."""

from __future__ import annotations

from pathlib import Path

import pytest

R2_VARS = ("R2_BUCKET", "R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")


@pytest.fixture(autouse=True)
def _no_r2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Real R2 credentials in a developer's shell must never reach a test, and the export
    stage must never publish into the repo's web/public/data."""
    for name in R2_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PULSE_EXPORT_DIR", str(tmp_path / "web-data"))
