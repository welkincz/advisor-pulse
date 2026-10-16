"""Build the dbt `ci` warehouse by ingesting the committed fixtures (used by `make dbt-build-ci`).

Runs the real loaders, so quarantine and dedupe behave as in a weekly run. The load time and
run id are fixed, so the warehouse content is the same on every machine. Replaced by the
runner's ingest stage once #21 lands.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from pulse.ingest.snowflake import load_snowflake_activity
from pulse.ingest.teradata_client import load_teradata_client
from pulse.ingest.teradata_hr import load_teradata_hr
from pulse.warehouse import connect, init_warehouse

LOADED_AT = datetime(2026, 10, 5, 3, 30, tzinfo=UTC)
RUN_ID = "ci-fixtures"


def build(sources: Path, target: Path) -> None:
    for stale in (target, target.with_name(target.name + ".wal")):
        stale.unlink(missing_ok=True)
    con = connect(target)
    try:
        init_warehouse(con)
        load_teradata_hr(con, sources / "teradata/edw.sqlite", run_id=RUN_ID, loaded_at=LOADED_AT)
        load_teradata_client(con, sources, run_id=RUN_ID, loaded_at=LOADED_AT)
        load_snowflake_activity(con, sources, run_id=RUN_ID, loaded_at=LOADED_AT)
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=Path("fixtures/sources"))
    parser.add_argument("--target", type=Path, default=Path("data/ci/warehouse.duckdb"))
    args = parser.parse_args()
    build(args.sources, args.target)


if __name__ == "__main__":
    main()
