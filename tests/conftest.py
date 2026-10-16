"""Shared test setup."""

from __future__ import annotations

import pytest

R2_VARS = ("R2_BUCKET", "R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")


@pytest.fixture(autouse=True)
def _no_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real R2 credentials in a developer's shell must never reach a test."""
    for name in R2_VARS:
        monkeypatch.delenv(name, raising=False)
