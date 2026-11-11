"""Parity harness tests: unit cases on hand-made rows, then the legacy job on the fixture
warehouse (skipped when `make dbt-build-ci` has not built it)."""

from __future__ import annotations

from pathlib import Path

import pytest
import run
from parity import ColumnRule, SourceMapping, Spec, reconcile

SPEC = Spec(keys=("wk", "br"), columns={"n": ColumnRule(), "avg": ColumnRule(tolerance=0.05)})
TARGET = [
    {"wk": "W1", "br": "A", "n": 3, "avg": 10.25},
    {"wk": "W1", "br": "B", "n": 4, "avg": None},
]


def test_identical_rows_pass() -> None:
    report = reconcile(TARGET, TARGET, SPEC)
    assert report.ok and report.compared_cells == 4


def test_injected_mismatch_names_the_exact_key_and_column() -> None:
    source = [dict(TARGET[0], n=4), TARGET[1]]
    report = reconcile(source, TARGET, SPEC)
    assert not report.ok
    [m] = report.mismatches
    assert (m.key, m.column, m.source, m.target, m.diff) == (("W1", "A"), "n", 4, 3, 1.0)
    assert "mismatch (wk=W1, br=A) n: source=4 target=3  diff=+1" in report.render()


def test_missing_extra_and_duplicate_keys_are_reported() -> None:
    source = [TARGET[0], TARGET[0], {"wk": "W1", "br": "C", "n": 1, "avg": None}]
    report = reconcile(source, TARGET, SPEC)
    assert report.missing_in_source == [("W1", "B")]
    assert report.extra_in_source == [("W1", "C")]
    assert report.duplicate_source_keys == [("W1", "A")]
    assert not report.ok


def test_tolerance_is_inclusive_and_null_only_equals_null() -> None:
    edge = [dict(TARGET[0], avg=10.3), TARGET[1]]
    assert reconcile(edge, TARGET, SPEC).ok
    over = [dict(TARGET[0], avg=10.31), dict(TARGET[1], avg=0)]
    columns = [m.column for m in reconcile(over, TARGET, SPEC).mismatches]
    assert columns == ["avg", "avg"]


def test_sentinel_reads_a_source_zero_as_null() -> None:
    spec = Spec(SPEC.keys, {"avg": ColumnRule(source_null_sentinel=0)})
    assert reconcile([TARGET[1] | {"avg": 0}], [TARGET[1]], spec).ok


WAREHOUSE = Path(__file__).resolve().parents[3] / "data/ci/warehouse.duckdb"
needs_warehouse = pytest.mark.skipif(not WAREHOUSE.exists(), reason="run `make dbt-build-ci`")


@needs_warehouse
def test_legacy_report_matches_the_mart_after_mapping_decisions() -> None:
    report, _ = run.parity(WAREHOUSE)
    assert report.ok, report.render()
    assert report.source_rows == report.target_rows == 24


@needs_warehouse
def test_strict_compare_detects_the_documented_legacy_quirks() -> None:
    report, _ = run.parity(WAREHOUSE, strict=True)
    assert {m.column for m in report.mismatches} == {"avg_meeting_duration_min"}
    nulls = [m for m in report.mismatches if m.target is None]
    assert [(m.key, m.source) for m in nulls] == [(("2026-W40", "BR-0202"), 0)]
    rounded = [m for m in report.mismatches if m.target is not None]
    assert rounded and all(abs(m.diff or 0) <= 0.05 + 1e-9 for m in rounded)


@needs_warehouse
def test_injected_mismatch_on_the_warehouse_is_reported_exactly() -> None:
    report, _ = run.parity(WAREHOUSE, inject_mismatch=True)
    assert [(m.key, m.column) for m in report.mismatches] == [
        (("2026-W39", "BR-0201"), "activities_completed")
    ]


@needs_warehouse
def test_without_the_key_decision_every_key_fails_to_join() -> None:
    con = run.connect(WAREHOUSE)
    mapping = SourceMapping.load(run.MAPPING)
    raw_keys = SourceMapping(
        keys={"iso_week_id": "{RPT_WK_ID}", "branch_id": "{BRNCH_CD}"},
        rename=mapping.rename,
        rules=mapping.rules,
    )
    report = reconcile(raw_keys.apply(run.run_legacy(con)), run.read_target(con), raw_keys.spec())
    assert len(report.missing_in_source) == len(report.extra_in_source) == 24
    assert report.compared_cells == 0
