"""Deterministic weekly run checks DQ030–DQ033 (PLAN.md §8)."""

from __future__ import annotations

import math
import statistics
import tomllib
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from pulse.contracts.enums import CheckSeverity, CheckStatus
from pulse.contracts.meta import CheckResult


@dataclass(frozen=True)
class CheckPolicy:
    freshness_lag_days: int = 2
    volume_sigma: float = 3.0
    volume_fail_fraction: float = 0.5
    quarantine_max_rate: float = 0.02
    dq030_action: CheckSeverity = CheckSeverity.FAIL
    dq031_warn_action: CheckSeverity = CheckSeverity.WARN
    dq031_fail_action: CheckSeverity = CheckSeverity.FAIL
    dq032_action: CheckSeverity = CheckSeverity.FAIL
    dq033_weekly_action: CheckSeverity = CheckSeverity.WARN
    dq033_ci_action: CheckSeverity = CheckSeverity.FAIL

    def __post_init__(self) -> None:
        thresholds = (self.volume_sigma, self.volume_fail_fraction, self.quarantine_max_rate)
        if not all(math.isfinite(value) for value in thresholds):
            raise ValueError("quality thresholds must be finite")
        if self.freshness_lag_days < 0 or self.volume_sigma <= 0:
            raise ValueError("freshness lag must be nonnegative and volume sigma positive")
        if not 0 < self.volume_fail_fraction <= 1 or not 0 < self.quarantine_max_rate <= 1:
            raise ValueError("quality fractions must be in (0, 1]")

    @classmethod
    def from_toml(cls, path: Path | None) -> CheckPolicy:
        """Read optional ``[quality]`` overrides, using PLAN.md defaults otherwise."""
        if path is None or not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8")).get("quality", {})
        if not isinstance(data, dict):
            raise ValueError("[quality] must be a table")
        allowed = set(cls.__dataclass_fields__)
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"Unknown quality settings: {', '.join(sorted(unknown))}")
        defaults = cls()
        lag = data.get("freshness_lag_days", defaults.freshness_lag_days)
        if type(lag) is not int:
            raise ValueError("freshness_lag_days must be an integer")

        def number(name: str, default: float) -> float:
            value = data.get(name, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            return float(value)

        def action(name: str) -> CheckSeverity:
            return CheckSeverity(data.get(name, getattr(defaults, name)))

        return cls(
            freshness_lag_days=lag,
            volume_sigma=number("volume_sigma", defaults.volume_sigma),
            volume_fail_fraction=number("volume_fail_fraction", defaults.volume_fail_fraction),
            quarantine_max_rate=number("quarantine_max_rate", defaults.quarantine_max_rate),
            dq030_action=action("dq030_action"),
            dq031_warn_action=action("dq031_warn_action"),
            dq031_fail_action=action("dq031_fail_action"),
            dq032_action=action("dq032_action"),
            dq033_weekly_action=action("dq033_weekly_action"),
            dq033_ci_action=action("dq033_ci_action"),
        )


def _result(
    run_id: str,
    check_id: str,
    action: CheckSeverity,
    failed: bool,
    observed: float | None,
    expected: str,
    message: str,
) -> CheckResult:
    return CheckResult(
        run_id=run_id,
        check_id=check_id,
        severity=action,
        status=CheckStatus(action.value) if failed else CheckStatus.PASS,
        observed=observed,
        expected=expected,
        message=message,
    )


def freshness(
    run_id: str, iso_week_id: str, latest: date | None, policy: CheckPolicy
) -> CheckResult:
    year, week = iso_week_id.split("-W")
    week_end = date.fromisocalendar(int(year), int(week), 7)
    deadline = week_end - timedelta(days=policy.freshness_lag_days)
    failed = latest is None or latest < deadline
    return _result(
        run_id,
        "DQ030",
        policy.dq030_action,
        failed,
        float((week_end - latest).days) if latest else None,
        f"activity_date >= {deadline.isoformat()} (lag <= {policy.freshness_lag_days}d)",
        f"Latest activity date: {latest.isoformat() if latest else 'missing'}",
    )


def volume(
    run_id: str, current: int | None, history: list[int], policy: CheckPolicy
) -> CheckResult:
    if current is None:
        return _result(
            run_id,
            "DQ031",
            policy.dq031_warn_action,
            True,
            None,
            "current national weekly volume present",
            "National weekly volume is missing",
        )
    if len(history) < 8:
        return _result(
            run_id,
            "DQ031",
            policy.dq031_warn_action,
            True,
            float(current),
            "8 prior weeks",
            f"Only {len(history)} prior weeks; baseline pending",
        )
    baseline = history[:8]
    mean = statistics.mean(baseline)
    sigma = statistics.pstdev(baseline)
    deviation = abs(current - mean)
    fraction = deviation / mean if mean else (0.0 if current == 0 else float("inf"))
    if fraction > policy.volume_fail_fraction:
        action, failed = policy.dq031_fail_action, True
    else:
        action = policy.dq031_warn_action
        failed = deviation > policy.volume_sigma * sigma
    return _result(
        run_id,
        "DQ031",
        action,
        failed,
        float(current),
        f"within {policy.volume_sigma:g}σ of {mean:g}; "
        f"fail beyond {policy.volume_fail_fraction:.0%}",
        f"Current {current}; trailing mean {mean:g}, σ {sigma:g}",
    )


def quarantine_rate(
    run_id: str, quarantined: int, rows_in: int, policy: CheckPolicy
) -> CheckResult:
    rate = quarantined / rows_in if rows_in else 0.0
    return _result(
        run_id,
        "DQ032",
        policy.dq032_action,
        rows_in > 0 and rate > policy.quarantine_max_rate,
        rate,
        f"<= {policy.quarantine_max_rate:.1%}",
        f"{quarantined} of {rows_in} batch rows quarantined",
    )


def defect_reconciliation(
    run_id: str,
    expected: set[tuple[str, int | None, str | None]],
    actual: set[tuple[str, int | None, str | None]],
    policy: CheckPolicy,
    *,
    ci: bool = False,
) -> CheckResult:
    action = policy.dq033_ci_action if ci else policy.dq033_weekly_action
    missing, extra = expected - actual, actual - expected
    return _result(
        run_id,
        "DQ033",
        action,
        bool(missing or extra),
        float(len(actual)),
        f"{len(expected)} exact injected quarantines",
        f"Missing {len(missing)}; unexpected {len(extra)}",
    )
