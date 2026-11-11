"""Write the advisor_weekly fixture into a local Apache Iceberg table, one ISO week at a time.

Local, synthetic, single machine: a SQLite-backed catalog and a filesystem warehouse.
Run: uv run --project labs/open-table python labs/open-table/open_table.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import warnings
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.table import Table
from pyiceberg.types import StringType

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/exports/advisor_weekly.parquet"
TABLE = "pulse.advisor_weekly"
KEY = ["iso_week_id", "advisor_id"]


def open_catalog(warehouse: Path) -> SqlCatalog:
    warehouse.mkdir(parents=True, exist_ok=True)
    return SqlCatalog(
        "local",
        uri=f"sqlite:///{warehouse / 'catalog.db'}",
        warehouse=warehouse.as_uri(),
    )


def read_fixture(path: Path = FIXTURE) -> pa.Table:
    # Drop the contract metadata so the Iceberg schema is the column list only.
    return pq.read_table(path).replace_schema_metadata(None)


def create_table(catalog: SqlCatalog, schema: pa.Schema) -> Table:
    catalog.create_namespace_if_not_exists("pulse")
    table = catalog.create_table(TABLE, schema=schema)
    with table.update_spec() as spec:
        spec.add_identity("iso_week_id")
    return table


def write_week(table: Table, rows: pa.Table) -> None:
    """Replace the partitions present in `rows`: append on first sight, overwrite on re-run."""
    weeks = pc.unique(rows["iso_week_id"]).to_pylist()
    if len(weeks) != 1:
        raise ValueError(f"write_week expects exactly one ISO week, got {weeks}")
    # The delete and the append commit in one transaction: one new metadata file per call.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", "Delete operation did not match any records")
        table.dynamic_partition_overwrite(rows)


def content_hash(rows: pa.Table) -> str:
    """Order-independent hash of the rows, so two reads of the same data compare equal."""
    ordered = rows.sort_by([(k, "ascending") for k in KEY])
    payload = json.dumps(ordered.to_pylist(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def duckdb_week_counts(table: Table) -> list[tuple[str, int]]:
    """Read the table back through DuckDB's iceberg extension from the current metadata file."""
    metadata = table.metadata_location.removeprefix("file://")
    con = duckdb.connect()
    con.sql("INSTALL iceberg; LOAD iceberg;")
    query = "SELECT iso_week_id, count(*) FROM iceberg_scan(?) GROUP BY 1 ORDER BY 1"
    return [(w, int(n)) for w, n in con.execute(query, [metadata]).fetchall()]


def run(warehouse: Path) -> dict[str, object]:
    if warehouse.exists():
        shutil.rmtree(warehouse)
    timings: dict[str, float] = {}
    start = time.perf_counter()
    source = read_fixture()
    weeks = sorted(pc.unique(source["iso_week_id"]).to_pylist())
    table = create_table(open_catalog(warehouse), source.schema)
    timings["setup_s"] = time.perf_counter() - start

    t = time.perf_counter()
    for week in weeks:
        write_week(table, source.filter(pc.equal(source["iso_week_id"], week)))
    timings["append_weeks_s"] = time.perf_counter() - t
    first = table.scan().to_arrow()
    before_rerun = table.current_snapshot()
    assert before_rerun is not None

    t = time.perf_counter()
    last = weeks[-1]
    write_week(table, source.filter(pc.equal(source["iso_week_id"], last)))
    timings["rerun_week_s"] = time.perf_counter() - t
    rerun = table.scan().to_arrow()

    t = time.perf_counter()
    with table.update_schema() as update:
        update.add_column("loaded_by_run", StringType(), doc="Run that wrote the row")
    evolved = source.filter(pc.equal(source["iso_week_id"], last))
    evolved = evolved.append_column(
        pa.field("loaded_by_run", pa.string()), pa.array(["lab-rerun"] * evolved.num_rows)
    )
    write_week(table, evolved)
    timings["evolve_and_write_s"] = time.perf_counter() - t
    current = table.scan().to_arrow()

    t = time.perf_counter()
    travelled = table.scan(snapshot_id=before_rerun.snapshot_id).to_arrow()
    timings["time_travel_s"] = time.perf_counter() - t

    t = time.perf_counter()
    duck = duckdb_week_counts(table)
    timings["duckdb_read_s"] = time.perf_counter() - t
    timings["total_s"] = time.perf_counter() - start

    return {
        "source_rows": source.num_rows,
        "weeks": weeks,
        "rows_after_appends": first.num_rows,
        "rows_after_rerun": rerun.num_rows,
        "hash_after_appends": content_hash(first),
        "hash_after_rerun": content_hash(rerun),
        "rows_after_evolution": current.num_rows,
        "columns_now": len(current.schema),
        "null_loaded_by_run": current["loaded_by_run"].null_count,
        "time_travel_rows": travelled.num_rows,
        "time_travel_columns": len(travelled.schema),
        "time_travel_hash": content_hash(travelled),
        "snapshots": [
            (s.snapshot_id, s.summary.operation.value if s.summary else None)
            for s in table.snapshots()
        ],
        "metadata_commits": len(table.metadata.metadata_log) + 1,
        "duckdb_week_counts": duck,
        "timings_s": {k: round(v, 3) for k, v in timings.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warehouse", type=Path, default=Path(__file__).parent / ".warehouse")
    result = run(parser.parse_args().warehouse)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
