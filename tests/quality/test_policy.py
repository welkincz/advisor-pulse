"""DQ030–DQ033 policy and stage behavior against synthetic fixture data."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pulse.contracts.defects import DefectManifest
from pulse.contracts.enums import CheckStatus
from pulse.quality.policy import (
    CheckPolicy,
    defect_reconciliation,
    freshness,
    quarantine_rate,
    volume,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def test_freshness_pass_and_fail() -> None:
    policy = CheckPolicy()
    assert freshness("r", "2026-W40", date(2026, 10, 2), policy).status is CheckStatus.PASS
    assert freshness("r", "2026-W40", date(2026, 10, 1), policy).status is CheckStatus.FAIL


def test_volume_pass_warn_and_fail() -> None:
    policy = CheckPolicy()
    history = [100] * 8
    assert volume("r", 100, history, policy).status is CheckStatus.PASS
    assert volume("r", 130, history, policy).status is CheckStatus.WARN
    assert volume("r", 160, history, policy).status is CheckStatus.FAIL
    assert volume("r", 100, history[:7], policy).status is CheckStatus.WARN


def test_quarantine_rate_pass_and_fail() -> None:
    policy = CheckPolicy()
    assert quarantine_rate("r", 2, 100, policy).status is CheckStatus.PASS
    assert quarantine_rate("r", 3, 100, policy).status is CheckStatus.FAIL


def test_defect_reconciliation_pass_and_fail() -> None:
    manifest = DefectManifest.model_validate_json((FIXTURES / "defects.json").read_text())
    expected = {
        (d.file, d.row, d.rule_id)
        for d in manifest.defects
        if d.iso_week_id == "2026-W40" and d.rule_id in {f"DQ00{i}" for i in range(1, 6)}
    }
    assert expected
    assert defect_reconciliation("r", expected, expected, CheckPolicy()).status is CheckStatus.PASS
    assert defect_reconciliation("r", expected, set(), CheckPolicy()).status is CheckStatus.WARN
    assert (
        defect_reconciliation("r", expected, set(), CheckPolicy(), ci=True).status
        is CheckStatus.FAIL
    )


def test_policy_reads_thresholds_and_actions_from_toml(tmp_path: Path) -> None:
    path = tmp_path / "pulse.toml"
    path.write_text(
        "[quality]\nfreshness_lag_days = 3\nquarantine_max_rate = 0.05\n"
        'dq030_action = "WARN"\ndq032_action = "WARN"\n'
    )
    policy = CheckPolicy.from_toml(path)
    assert freshness("r", "2026-W40", date(2026, 10, 1), policy).status is CheckStatus.PASS
    assert freshness("r", "2026-W40", date(2026, 9, 30), policy).status is CheckStatus.WARN
    assert quarantine_rate("r", 3, 100, policy).status is CheckStatus.PASS
    assert quarantine_rate("r", 6, 100, policy).status is CheckStatus.WARN


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_policy_rejects_nonfinite_thresholds(tmp_path: Path, value: str) -> None:
    path = tmp_path / "pulse.toml"
    path.write_text(f"[quality]\nvolume_sigma = {value}\n")
    with pytest.raises(ValueError):
        CheckPolicy.from_toml(path)
