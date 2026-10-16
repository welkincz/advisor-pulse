"""Build the dbt `ci` warehouse by ingesting the committed fixtures (used by `make dbt-build-ci`).

Runs the runner's ingest stage, so quarantine and dedupe behave as in a weekly run. The load
time and run id are fixed, so the warehouse content is the same on every machine.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pulse.contracts.enums import RunType, StageStatus
from pulse.ingest.stage import SOURCES_DIR, ingest
from pulse.runner.stage import StageContext
from pulse.warehouse import WAREHOUSE_FILE

LOADED_AT = datetime(2026, 10, 5, 3, 30, tzinfo=UTC)
RUN_ID = "ci-fixtures"


class _FixedClock:
    def now(self) -> datetime:
        return LOADED_AT

    def sleep(self, seconds: float) -> None:
        pass


def build(sources: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as work:
        data_dir = Path(work)
        (data_dir / SOURCES_DIR).symlink_to(sources.resolve(), target_is_directory=True)
        ctx = StageContext(RUN_ID, RunType.MANUAL, "2026-W40", data_dir, _FixedClock())
        result = ingest(ctx)
        if result.status is StageStatus.FAILED:
            raise SystemExit(f"Fixture ingest failed: {result.message}")
        shutil.move(data_dir / WAREHOUSE_FILE, target)
    print(f"{target}: {result.rows_out} rows loaded, {result.rows_quarantined} quarantined")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=Path("fixtures/sources"))
    parser.add_argument("--target", type=Path, default=Path("data/ci/warehouse.duckdb"))
    args = parser.parse_args()
    build(args.sources, args.target)


if __name__ == "__main__":
    main()
