"""Rebuild the branch × week 12-month portfolio-contacted KPI in PySpark and check it against dbt.

The dbt chain is int_portfolio_history + int_client_book_weekly -> int_client_contact_12m
-> int_kpi_events -> mart_org_weekly (BRANCH rows). This job starts from the same inputs
dbt reads on fixtures (raw client extract, staged activity and portfolio tables, the
calendar and activity-type dimensions), recomputes every step with the DataFrame API, and
compares the result with the dbt tables in the CI warehouse built by `make dbt-build-ci`.

Local mode on one machine, synthetic data. See README.md for the limits.

    uv run --project labs/pyspark-parity python labs/pyspark-parity/parity.py
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

LAB_DIR = Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
WAREHOUSE = REPO_ROOT / "data" / "ci" / "warehouse.duckdb"
WORK_DIR = LAB_DIR / ".work" / "inputs"

# The tables dbt reads for this KPI, by the name the Spark job uses.
INPUTS = {
    "raw_client": "raw.teradata__clnt",
    "stg_activity": "staging.stg_activity",
    "stg_portfolio": "staging.stg_portfolio",
    "stg_portfolio_assignment": "staging.stg_portfolio_assignment",
    "dim_activity_type": "marts.dim_activity_type",
    "dim_date": "marts.dim_date",
}

# Fixtures are a few thousand rows, so a handful of shuffle partitions is plenty. Stated
# explicitly rather than left at Spark's default of 200.
SHUFFLE_PARTITIONS = 4
RATE_TOLERANCE = 1e-9
FAR_FUTURE_DATE = "9999-12-31"


def spark_session(cores: int = 4) -> SparkSession:
    return (
        SparkSession.builder.master(f"local[{cores}]")
        .appName("pulse-pyspark-parity")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", str(SHUFFLE_PARTITIONS))
        .config("spark.sql.adaptive.enabled", "false")
        .config("spark.ui.enabled", "false")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )


def export_inputs(warehouse: Path = WAREHOUSE, out_dir: Path = WORK_DIR) -> dict[str, int]:
    """Copy the dbt inputs out of DuckDB as Parquet, the hand-off format Spark reads."""
    if not warehouse.exists():
        raise SystemExit(
            f"{warehouse} not found. Run `make dbt-build-ci` from the repo root first."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with duckdb.connect(str(warehouse), read_only=True) as con:
        for name, table in INPUTS.items():
            path = out_dir / f"{name}.parquet"
            con.execute(f"copy (select * from {table}) to '{path}' (format parquet)")
            counts[name] = con.execute(f"select count(*) from {table}").fetchone()[0]  # type: ignore[index]
    return counts


def read_inputs(spark: SparkSession, in_dir: Path = WORK_DIR) -> dict[str, DataFrame]:
    return {name: spark.read.parquet(str(in_dir / f"{name}.parquet")) for name in INPUTS}


# ── The computation ──────────────────────────────────────────────────────────


def portfolio_history(assignment: DataFrame, portfolio: DataFrame) -> DataFrame:
    """int_portfolio_history: SCD2 holder ranges; the later id wins on a same-day tie."""
    same_day = Window.partitionBy("portfolio_id", "effective_date").orderBy(
        F.col("portfolio_assignment_id").desc()
    )
    by_portfolio = Window.partitionBy("portfolio_id").orderBy("effective_date")
    return (
        assignment.where(F.col("effective_date").isNotNull())
        .withColumn("rn", F.row_number().over(same_day))
        .where("rn = 1")
        .withColumn(
            "valid_to",
            F.coalesce(
                F.lead("effective_date").over(by_portfolio), F.lit(FAR_FUTURE_DATE).cast("date")
            ),
        )
        .join(
            portfolio.select("portfolio_id", F.col("branch_id").alias("transit_branch_id")),
            "portfolio_id",
        )
        .select(
            "portfolio_id",
            "transit_branch_id",
            "advisor_id",
            F.col("effective_date").alias("valid_from"),
            "valid_to",
        )
    )


def client_versions(raw_client: DataFrame) -> DataFrame:
    """Every loaded CLNT row as a validity range (int_client_book_weekly's `ranged`)."""
    latest_load = Window.partitionBy("client_id", "valid_from").orderBy(
        F.col("_loaded_at").desc(), F.col("_source_file").desc(), F.col("_source_row").desc()
    )
    next_update = Window.partitionBy("client_id").orderBy("valid_from")
    return (
        raw_client.select(
            F.col("CLNT_ID").alias("client_id"),
            F.col("CLNT_SINCE_DT").cast("date").alias("client_since_date"),
            F.expr("nullif(trim(PRTF_ID), '')").alias("portfolio_id"),
            F.expr("nullif(upper(trim(STAT_CD)), '')").alias("status_code"),
            F.col("LAST_UPD_TS").alias("valid_from"),
            "_loaded_at",
            "_source_file",
            "_source_row",
        )
        .where(F.col("client_id").isNotNull() & F.col("valid_from").isNotNull())
        .withColumn("rn", F.row_number().over(latest_load))
        .where("rn = 1")
        .withColumn(
            "valid_to",
            F.coalesce(
                F.lead("valid_from").over(next_update),
                F.lit(FAR_FUTURE_DATE).cast("timestamp"),
            ),
        )
        .drop("rn", "_loaded_at", "_source_file", "_source_row")
    )


def calendar_weeks(dim_date: DataFrame) -> DataFrame:
    """One row per ISO week with its Sunday and the 23:59 America/Toronto cut-off as UTC."""
    return (
        dim_date.groupBy("iso_week_id")
        .agg(F.max("week_end").alias("week_end"))
        .withColumn(
            "as_of_ts",
            F.to_utc_timestamp(
                F.to_timestamp(F.concat(F.col("week_end").cast("string"), F.lit(" 23:59:00"))),
                "America/Toronto",
            ),
        )
    )


def contact_window(activity: DataFrame, weeks: DataFrame) -> DataFrame:
    """int_contact_window: is the 12-month window complete, and is the week reported."""
    first = activity.where("status = 'COMPLETED'").agg(
        F.min("activity_date").alias("first_date"),
        F.min("iso_week_id").alias("first_week"),
        F.max("iso_week_id").alias("last_week"),
    )
    windows = weeks.crossJoin(F.broadcast(first)).withColumn(
        "is_window_complete", F.add_months("week_end", -12) >= F.col("first_date")
    )
    first_complete = F.min(
        F.when(
            F.col("is_window_complete") & (F.col("iso_week_id") <= F.col("last_week")),
            F.col("iso_week_id"),
        )
    ).over(Window.partitionBy())  # one global window: 260-odd calendar weeks, fine on one partition
    return windows.select(
        "iso_week_id",
        "is_window_complete",
        (F.col("iso_week_id") >= F.coalesce(first_complete, F.col("first_week"))).alias(
            "is_reported"
        ),
    )


def client_contact_12m(inputs: dict[str, DataFrame]) -> DataFrame:
    """int_client_contact_12m: active clients in a known portfolio, contacted in 12 months."""
    activity, weeks = inputs["stg_activity"], calendar_weeks(inputs["dim_date"])
    last_week = activity.agg(F.max("iso_week_id").alias("last_week"))
    holders = portfolio_history(inputs["stg_portfolio_assignment"], inputs["stg_portfolio"])

    observed_weeks = weeks.crossJoin(F.broadcast(last_week)).where("iso_week_id <= last_week")
    book = (
        # Range join on the week's cut-off; the week side is small, so broadcast it.
        client_versions(inputs["raw_client"])
        .join(
            F.broadcast(observed_weeks),
            (F.col("as_of_ts") >= F.col("valid_from"))
            & (F.col("as_of_ts") < F.col("valid_to"))
            & (F.col("client_since_date") <= F.col("week_end")),
        )
        .select("client_id", "iso_week_id", "week_end", "portfolio_id", "status_code")
        .alias("b")
        .join(
            F.broadcast(holders).alias("h"),
            (F.col("h.portfolio_id") == F.col("b.portfolio_id"))
            & (F.col("b.week_end") >= F.col("h.valid_from"))
            & (F.col("b.week_end") < F.col("h.valid_to")),
            "left",
        )
        .where((F.col("b.status_code") == "A") & F.col("h.transit_branch_id").isNotNull())
        .select(
            "b.client_id",
            "b.iso_week_id",
            "b.week_end",
            F.col("h.portfolio_id").alias("portfolio_id"),
            F.col("h.advisor_id").alias("advisor_id"),
            F.col("h.transit_branch_id").alias("transit_branch_id"),
        )
    )

    contact_types = inputs["dim_activity_type"].where("counts_as_contact").select("activity_type")
    contacts = (
        activity.where("status = 'COMPLETED' and client_id is not null")
        .join(F.broadcast(contact_types), "activity_type")
        .select("client_id", F.col("activity_date").alias("event_date"))
        .distinct()
    )

    # As-of join without a range join: stack contacts and book rows per client, order them
    # by date (a contact on the week-end day sorts first, so it counts), and carry the last
    # contact date forward. One shuffle on client_id instead of a client × contact product.
    stacked = (
        book.withColumn("event_date", F.col("week_end"))
        .withColumn("is_book", F.lit(1))
        .unionByName(contacts.withColumn("is_book", F.lit(0)), allowMissingColumns=True)
    )
    carry = (
        Window.partitionBy("client_id")
        .orderBy("event_date", "is_book")
        .rowsBetween(Window.unboundedPreceding, Window.currentRow)
    )
    return (
        stacked.repartition(SHUFFLE_PARTITIONS, "client_id")
        .withColumn(
            "last_contact_date",
            F.last(F.when(F.col("is_book") == 0, F.col("event_date")), ignorenulls=True).over(
                carry
            ),
        )
        .where("is_book = 1")
        .select(
            "client_id",
            "iso_week_id",
            "week_end",
            "portfolio_id",
            "advisor_id",
            "transit_branch_id",
            "last_contact_date",
            F.coalesce(
                F.col("last_contact_date") > F.add_months("week_end", -12), F.lit(False)
            ).alias("contacted_12m"),
        )
    )


def branch_weekly(inputs: dict[str, DataFrame], contact_12m: DataFrame) -> DataFrame:
    """The portfolio columns of mart_org_weekly's BRANCH rows, for the weeks it reports."""
    activity = inputs["stg_activity"]
    window = contact_window(activity, calendar_weeks(inputs["dim_date"]))
    span = activity.agg(F.min("iso_week_id").alias("lo"), F.max("iso_week_id").alias("hi"))
    reported = (
        window.crossJoin(F.broadcast(span))
        .where("is_reported and iso_week_id between lo and hi")
        .select("iso_week_id", "is_window_complete")
    )
    rate = F.col("portfolio_contacted_12m") / F.col("portfolio_clients")
    return (
        contact_12m.join(F.broadcast(reported), "iso_week_id")
        .groupBy("iso_week_id", F.col("transit_branch_id").alias("branch_id"), "is_window_complete")
        .agg(
            F.count("*").alias("portfolio_clients"),
            F.sum(F.col("contacted_12m").cast("int")).alias("portfolio_contacted_12m"),
        )
        .withColumn("rate_unrounded", rate)
        .withColumn(
            "portfolio_contacted_rate_12m", F.when(F.col("is_window_complete"), F.round(rate, 4))
        )
        .drop("is_window_complete")
    )


# ── Parity ───────────────────────────────────────────────────────────────────


@dataclass
class Parity:
    client_weeks: int = 0
    branch_weeks: int = 0
    mismatches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches


def _same_rate(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=0.0, abs_tol=RATE_TOLERANCE)


def compare(contact_12m: DataFrame, branch: DataFrame, warehouse: Path = WAREHOUSE) -> Parity:
    with duckdb.connect(str(warehouse), read_only=True) as con:
        dbt_clients = con.execute(
            "select client_id, iso_week_id, week_end, portfolio_id, advisor_id, transit_branch_id,"
            " last_contact_date, contacted_12m from intermediate.int_client_contact_12m"
        ).fetchall()
        dbt_branch = con.execute(
            "select iso_week_id, node_id, portfolio_clients, portfolio_contacted_12m,"
            " portfolio_contacted_12m / nullif(portfolio_clients, 0), portfolio_contacted_rate_12m"
            " from marts.mart_org_weekly where level = 'BRANCH'"
        ).fetchall()

    result = Parity()
    spark_clients = {(r[0], r[1]): tuple(r) for r in contact_12m.collect()}
    dbt_client_map = {(r[0], r[1]): tuple(r) for r in dbt_clients}
    result.client_weeks = len(dbt_client_map)
    for key in sorted(spark_clients.keys() | dbt_client_map.keys()):
        if spark_clients.get(key) != dbt_client_map.get(key):
            result.mismatches.append(
                f"client-week {key}: spark={spark_clients.get(key)} dbt={dbt_client_map.get(key)}"
            )

    spark_branch: dict[tuple[str, str], Any] = {
        (r.iso_week_id, r.branch_id): r for r in branch.collect()
    }
    result.branch_weeks = len(dbt_branch)
    for week, node, clients, contacted, rate, published in dbt_branch:
        row = spark_branch.pop((week, node), None)
        got = (
            (0, 0, None, None)
            if row is None
            else (
                row.portfolio_clients,
                row.portfolio_contacted_12m,
                row.rate_unrounded,
                row.portfolio_contacted_rate_12m,
            )
        )
        if (got[0], got[1]) != (clients, contacted) or not (
            _same_rate(got[2], rate) and _same_rate(got[3], published)
        ):
            want = (clients, contacted, rate, published)
            result.mismatches.append(f"branch-week ({week}, {node}): spark={got} dbt={want}")
    for key in sorted(spark_branch):
        result.mismatches.append(f"branch-week {key}: only in spark")
    return result


def run(inputs: dict[str, DataFrame]) -> tuple[DataFrame, DataFrame]:
    contact_12m = client_contact_12m(inputs).cache()
    return contact_12m, branch_weekly(inputs, contact_12m)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--warehouse", type=Path, default=WAREHOUSE)
    args = parser.parse_args()

    started = time.perf_counter()
    counts = export_inputs(args.warehouse)
    exported = time.perf_counter()
    spark = spark_session()
    spark.sparkContext.setLogLevel("ERROR")
    session = time.perf_counter()
    contact_12m, branch = run(read_inputs(spark))
    branch_rows = branch.count()
    computed = time.perf_counter()
    parity = compare(contact_12m, branch, args.warehouse)
    finished = time.perf_counter()

    print("inputs:", ", ".join(f"{name}={n}" for name, n in counts.items()))
    print(f"spark {spark.version}, local[4], shuffle partitions {SHUFFLE_PARTITIONS}")
    print(f"client-weeks: spark={contact_12m.count()} dbt={parity.client_weeks}")
    print(f"branch-weeks: spark={branch_rows} dbt={parity.branch_weeks}")
    print(
        f"wall time: export {exported - started:.2f}s, spark start {session - exported:.2f}s, "
        f"compute {computed - session:.2f}s, compare {finished - computed:.2f}s, "
        f"total {finished - started:.2f}s"
    )
    for line in parity.mismatches[:20]:
        print("MISMATCH", line)
    print("PARITY OK" if parity.ok else f"PARITY FAILED: {len(parity.mismatches)} mismatches")
    spark.stop()
    return 0 if parity.ok else 1


if __name__ == "__main__":
    sys.exit(main())
