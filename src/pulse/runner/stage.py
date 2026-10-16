"""Stage definitions: what a stage is given, what it returns, and which errors are retried."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pulse.contracts.enums import RunType, StageStatus


class RetryableError(Exception):
    """A transient failure (network, R2, API). The runner retries the stage on it."""


class Clock(Protocol):
    def now(self) -> datetime: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class StageContext:
    run_id: str
    run_type: RunType
    iso_week_id: str
    data_dir: Path
    clock: Clock


@dataclass(frozen=True)
class StageResult:
    status: StageStatus = StageStatus.SUCCESS
    rows_in: int | None = None
    rows_out: int | None = None
    rows_quarantined: int | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.status is StageStatus.RUNNING:
            raise ValueError("A stage cannot finish with status RUNNING.")


StageFn = Callable[[StageContext], StageResult]


@dataclass(frozen=True)
class Stage:
    """One node of the runner DAG.

    ``retry_on`` lists the exception types worth another attempt; anything else fails the
    stage on its first attempt.
    """

    name: str
    label: str
    fn: StageFn
    depends_on: tuple[str, ...] = ()
    retry_on: tuple[type[BaseException], ...] = (RetryableError,)
    max_attempts: int = 3


def not_implemented(issue: int) -> StageFn:
    """A placeholder stage that reports SKIPPED until its issue lands."""

    def fn(ctx: StageContext) -> StageResult:
        return StageResult(StageStatus.SKIPPED, message=f"Not implemented yet (issue #{issue}).")

    return fn
