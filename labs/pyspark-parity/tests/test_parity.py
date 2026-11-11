"""Parity holds on fixtures and breaks when one input row changes.

Needs the CI warehouse: run `make dbt-build-ci` from the repo root first.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import parity

pytestmark = pytest.mark.skipif(
    not parity.WAREHOUSE.exists(), reason="run `make dbt-build-ci` first"
)


@pytest.fixture(scope="module")
def spark() -> Iterator[SparkSession]:
    session = parity.spark_session(cores=2)
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


@pytest.fixture(scope="module")
def inputs(spark: SparkSession) -> dict[str, DataFrame]:
    parity.export_inputs()
    return parity.read_inputs(spark)


def _one_row_changed(before: DataFrame, after: DataFrame) -> None:
    assert before.count() == after.count()
    assert after.exceptAll(before).count() == 1


def test_parity_holds_on_fixtures(inputs: dict[str, DataFrame]) -> None:
    result = parity.compare(*parity.run(inputs))
    assert result.mismatches == []
    assert result.client_weeks == 4549
    assert result.branch_weeks == 24


def test_parity_fails_when_one_client_row_goes_inactive(inputs: dict[str, DataFrame]) -> None:
    raw = inputs["raw_client"]
    # A client with a single CLNT row who is in a branch's book in 2026-W40.
    single = raw.groupBy("CLNT_ID").count().where("count = 1").select("CLNT_ID")
    contact_12m, _ = parity.run(inputs)
    in_book = contact_12m.where("iso_week_id = '2026-W40'").select(
        F.col("client_id").alias("CLNT_ID")
    )
    client_id = single.join(in_book, "CLNT_ID").orderBy("CLNT_ID").first()["CLNT_ID"]  # type: ignore[index]

    altered = raw.withColumn(
        "STAT_CD", F.when(F.col("CLNT_ID") == client_id, F.lit("C")).otherwise(F.col("STAT_CD"))
    )
    _one_row_changed(raw, altered)

    result = parity.compare(*parity.run({**inputs, "raw_client": altered}))
    assert not result.ok
    assert any(m.startswith("branch-week (2026-W40") for m in result.mismatches)


def test_parity_fails_when_one_contact_is_cancelled(inputs: dict[str, DataFrame]) -> None:
    activity = inputs["stg_activity"]
    contact_types = inputs["dim_activity_type"].where("counts_as_contact").select("activity_type")
    contact_12m, _ = parity.run(inputs)
    # A client's latest contact as of 2026-W40, on a date no other contact of theirs shares.
    counted = contact_12m.where("iso_week_id = '2026-W40' and contacted_12m").select(
        "client_id", F.col("last_contact_date").alias("activity_date")
    )
    target = (
        activity.where("status = 'COMPLETED'")
        .join(contact_types, "activity_type")
        .join(counted, ["client_id", "activity_date"])
        .groupBy("client_id", "activity_date")
        .agg(F.count("*").alias("n"), F.min("activity_id").alias("activity_id"))
        .where("n = 1")
        .orderBy("activity_id")
        .first()
    )
    assert target is not None

    altered = activity.withColumn(
        "status",
        F.when(F.col("activity_id") == target["activity_id"], F.lit("CANCELLED")).otherwise(
            F.col("status")
        ),
    )
    _one_row_changed(activity, altered)

    result = parity.compare(*parity.run({**inputs, "stg_activity": altered}))
    assert not result.ok
    assert any(target["client_id"] in m for m in result.mismatches)


def test_rate_tolerance_is_tight() -> None:
    assert parity._same_rate(0.5, 0.5 + 1e-10)
    assert not parity._same_rate(0.5, 0.5 + 1e-8)
    assert parity._same_rate(None, None)
    assert not parity._same_rate(None, 0.0)
