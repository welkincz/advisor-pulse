from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from pulse.contracts import Contract, arrow_schema, column_names
from pulse.contracts.defects import DefectKind, DefectManifest
from pulse.contracts.enums import OrgLevel, StageStatus
from pulse.contracts.exports import (
    AdvisorWeekly,
    DqWeekly,
    GeoWeekly,
    Manifest,
    NarrativeFile,
    OrgWeekly,
    PipelineGraph,
    RunLogExport,
    WeeklyReport,
)
from pulse.contracts.sources import (
    SnowflakeActivity,
    TeradataAdvisor,
    TeradataAssignment,
    TeradataBranch,
    TeradataClient,
)
from pulse.fixtures import (
    FIXTURES_DIR,
    RUNNER_STAGES,
    WEEKS,
    build,
    iso_week,
    local_date,
    normalize_postal,
)

COMMITTED = FIXTURES_DIR
SOURCES = COMMITTED / "sources"
EXPORTS = COMMITTED / "exports"
QUARANTINE_RULES = {"DQ001", "DQ002", "DQ003", "DQ004", "DQ005"}
EXPORT_TABLES: dict[str, type[Contract]] = {
    "org_weekly.parquet": OrgWeekly,
    "advisor_weekly.parquet": AdvisorWeekly,
    "weekly_report.parquet": WeeklyReport,
    "geo_weekly.parquet": GeoWeekly,
    "dq_weekly.parquet": DqWeekly,
}
SQLITE_TABLES: dict[str, type[Contract]] = {
    "CLNT": TeradataClient,
    "ADVSR": TeradataAdvisor,
    "ADVSR_ASGN": TeradataAssignment,
    "BRNCH": TeradataBranch,
}


def _files(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name not in {"README.md", ".gitattributes"}
    }


def _sqlite_dump(data: bytes, tmp: Path) -> list[str]:
    path = tmp / "dump.sqlite"
    path.write_bytes(data)
    con = sqlite3.connect(path)
    try:
        return list(con.iterdump())
    finally:
        con.close()


@pytest.fixture(scope="module")
def defects() -> DefectManifest:
    return DefectManifest.model_validate_json((COMMITTED / "defects.json").read_text())


def _activity_files() -> list[Path]:
    return sorted((SOURCES / "snowflake/activity").rglob("*.parquet"))


def _csv_rows(path: Path) -> list[dict[str, str]]:
    text = path.read_bytes().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


# ── Determinism and freshness ────────────────────────────────────────────────


def test_rebuild_is_byte_identical(tmp_path: Path) -> None:
    build(tmp_path / "a")
    build(tmp_path / "b")
    assert _files(tmp_path / "a") == _files(tmp_path / "b")


def test_committed_fixtures_are_current(tmp_path: Path) -> None:
    """``make fixtures`` was run after the last change to src/pulse/fixtures.py.

    SQLite files are compared by content: their header records the library version.
    """
    build(tmp_path / "fresh")
    fresh, committed = _files(tmp_path / "fresh"), _files(COMMITTED)
    assert sorted(fresh) == sorted(committed)
    for name, data in fresh.items():
        if name.endswith(".sqlite"):
            assert _sqlite_dump(data, tmp_path) == _sqlite_dump(committed[name], tmp_path)
        else:
            assert data == committed[name], f"{name} is stale: run `make fixtures`"


def test_size_budget() -> None:
    assert sum(len(b) for b in _files(COMMITTED).values()) < 2 * 1024 * 1024


# ── Sources validate against their contracts ─────────────────────────────────


def test_activity_parquet_matches_contract_schema() -> None:
    expected = arrow_schema(SnowflakeActivity)
    for path in _activity_files():
        schema = pq.read_schema(path)
        assert schema.names == expected.names, path
        assert [f.type for f in schema] == [f.type for f in expected], path


def test_only_the_quarantine_defects_fail_validation(defects: DefectManifest) -> None:
    expected = {
        (d.file, d.row, d.rule_id) for d in defects.defects if d.rule_id in QUARANTINE_RULES
    }
    failed = set()
    for path in _activity_files():
        rel = path.relative_to(SOURCES).as_posix()
        for i, row in enumerate(pq.read_table(path).to_pylist()):
            try:
                SnowflakeActivity.model_validate(row)
            except ValidationError:
                rule = next(d.rule_id for d in defects.defects if (d.file, d.row) == (rel, i))
                failed.add((rel, i, rule))
    for path in sorted((SOURCES / "teradata").glob("client_*.csv")):
        rel = path.relative_to(SOURCES).as_posix()
        for i, csv_row in enumerate(_csv_rows(path)):
            try:
                TeradataClient.model_validate({k: v or None for k, v in csv_row.items()})
            except ValidationError:
                failed.add((rel, i, "DQ005"))
    assert failed == expected
    assert {rule for *_, rule in expected} == QUARANTINE_RULES


def test_sqlite_tables_validate() -> None:
    con = sqlite3.connect(SOURCES / "teradata/edw.sqlite")
    con.row_factory = sqlite3.Row
    try:
        for table, model in SQLITE_TABLES.items():
            rows = [dict(r) for r in con.execute(f"SELECT * FROM {table}")]
            assert rows, table
            assert list(rows[0]) == column_names(model), table
            for row in rows:
                model.model_validate(row)
    finally:
        con.close()


def test_slice_shape() -> None:
    con = sqlite3.connect(SOURCES / "teradata/edw.sqlite")
    try:
        branches = con.execute("SELECT COUNT(*), COUNT(DISTINCT DIST_CD) FROM BRNCH").fetchone()
        advisors = con.execute("SELECT COUNT(*) FROM ADVSR").fetchone()
        clients = con.execute("SELECT COUNT(*) FROM CLNT").fetchone()
        transfers = con.execute(
            "SELECT COUNT(*) FROM ADVSR_ASGN WHERE RSN_CD = 'TRANSFER' AND EFF_DT >= '2026-09-07'"
        ).fetchone()
    finally:
        con.close()
    assert branches == (6, 3)
    assert advisors == (20,)
    assert clients == (200,)
    assert transfers == (2,)
    assert len(_activity_files()) >= len(WEEKS)


# ── Defect manifest ──────────────────────────────────────────────────────────


def test_every_defect_kind_is_present(defects: DefectManifest) -> None:
    assert {d.kind for d in defects.defects} == set(DefectKind)


def test_defects_point_at_real_rows(defects: DefectManifest) -> None:
    activity = {
        p.relative_to(SOURCES).as_posix(): pq.read_table(p).to_pylist() for p in _activity_files()
    }
    deltas = {
        p.relative_to(SOURCES).as_posix(): _csv_rows(p)
        for p in (SOURCES / "teradata").glob("client_*.csv")
    }
    for d in defects.defects:
        if d.file in activity:
            assert d.row is not None
            row = activity[d.file][d.row]
            assert row["ACTIVITY_ID"] == d.natural_key, d
            if d.column and d.raw_value is not None and d.kind is not DefectKind.RESENT_UPDATE:
                raw = row[d.column]
                assert (raw.isoformat() if hasattr(raw, "isoformat") else str(raw)) == d.raw_value
        elif d.file in deltas:
            assert d.row is not None
            assert deltas[d.file][d.row]["CLNT_ID"] == d.natural_key, d
        else:
            assert d.file == "teradata/edw.sqlite", d


def test_exact_duplicates_are_exact(defects: DefectManifest) -> None:
    for d in defects.defects:
        if d.kind is DefectKind.EXACT_DUPLICATE:
            assert d.row is not None
            rows = pq.read_table(SOURCES / d.file).to_pylist()
            assert rows.count(rows[d.row]) == 2


def test_late_rows_are_exactly_the_late_defects(defects: DefectManifest) -> None:
    late = set()
    for path in _activity_files():
        rel = path.relative_to(SOURCES).as_posix()
        for i, row in enumerate(pq.read_table(path).to_pylist()):
            if row["ACTIVITY_ID"] is None or row["ACTIVITY_TS"].year < 2015:
                continue
            if iso_week(local_date(row["ACTIVITY_TS"])) < iso_week(
                local_date(row["_EXTRACTED_AT"])
            ):
                late.add((rel, i))
    assert late == {(d.file, d.row) for d in defects.defects if d.kind is DefectKind.LATE_ARRIVING}


def test_postal_variants_normalize_as_declared(defects: DefectManifest) -> None:
    postal = [d for d in defects.defects if d.kind is DefectKind.DIRTY_POSTAL_CODE]
    assert len(postal) >= 16
    for d in postal:
        assert (normalize_postal(d.raw_value) or "UNK") == d.expected_value
    assert {d.raw_value for d in postal} >= {None, "90210", "N/A"}


def test_quarantine_rate_per_file_is_under_circuit_breaker(defects: DefectManifest) -> None:
    rejects = Counter(d.file for d in defects.defects if d.rule_id in QUARANTINE_RULES)
    for path in _activity_files():
        rel = path.relative_to(SOURCES).as_posix()
        assert rejects[rel] / pq.read_metadata(path).num_rows <= 0.02, rel


# ── Exports ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("name", "model"), list(EXPORT_TABLES.items()))
def test_export_tables_match_contract(name: str, model: type[Contract]) -> None:
    table = pq.read_table(EXPORTS / name)
    assert table.schema.equals(arrow_schema(model), check_metadata=True)
    rows = table.to_pylist()
    assert rows
    for row in rows:
        model.model_validate(row)


def _load(name: str, model: type[Contract]) -> Any:
    return model.model_validate_json((EXPORTS / name).read_text())


def test_documents_validate() -> None:
    _load("manifest.json", Manifest)
    _load("run_log.json", RunLogExport)
    _load("pipeline_graph.json", PipelineGraph)
    narratives = sorted((EXPORTS / "narratives").glob("*.json"))
    assert [p.name for p in narratives] == [f"{WEEKS[-1]}.json"]
    NarrativeFile.model_validate_json(narratives[0].read_text())


def test_manifest_lists_files_with_hashes() -> None:
    manifest: Manifest = _load("manifest.json", Manifest)
    assert manifest.latest_week == WEEKS[-1]
    assert manifest.weeks_available == list(WEEKS)
    for f in manifest.files:
        data = (EXPORTS / f.name).read_bytes()
        assert f.sha256 == hashlib.sha256(data).hexdigest()
        assert f.bytes == len(data)
        if f.name.endswith(".parquet"):
            assert f.rows == pq.read_metadata(EXPORTS / f.name).num_rows
    assert {f.name for f in manifest.files} >= set(EXPORT_TABLES)
    assert len(manifest.summary) == len({s.kpi_code for s in manifest.summary}) >= 10


def test_run_log_covers_success_warn_and_a_retry() -> None:
    log: RunLogExport = _load("run_log.json", RunLogExport)
    assert [r.iso_week_id for r in log.runs] == list(reversed(WEEKS))
    statuses = {r.status for r in log.runs}
    assert {StageStatus.SUCCESS, StageStatus.WARN} <= statuses
    retried = [
        (r.run_id, s.stage)
        for r in log.runs
        for s in r.stages
        if s.status is StageStatus.FAILED
        and any(
            t.stage == s.stage and t.attempt == s.attempt + 1 and t.status is StageStatus.SUCCESS
            for t in r.stages
        )
    ]
    assert len(retried) == 1
    assert all(StageStatus.FAILED is not r.status for r in log.runs)


def test_pipeline_graph_has_every_stage() -> None:
    graph: PipelineGraph = _load("pipeline_graph.json", PipelineGraph)
    ids = {n.id for n in graph.nodes}
    assert {n.stage for n in graph.nodes if n.kind == "STAGE"} == set(RUNNER_STAGES)
    assert all(e.source in ids and e.target in ids for e in graph.edges)
    assert len(ids) == len(graph.nodes)


def test_narrative_bullets_cite_known_facts() -> None:
    doc: NarrativeFile = _load(f"narratives/{WEEKS[-1]}.json", NarrativeFile)
    assert {n.fallback for n in doc.narratives} == {True, False}
    for n in doc.narratives:
        facts = {f.fact_id for f in n.facts_used}
        cited = {i for b in n.bullets for i in b.fact_ids} | {
            i for w in n.watchlist for i in w.fact_ids
        }
        assert cited <= facts, n.node_id


ADDITIVE = [
    "active_advisors",
    "activities_completed",
    "calls_out",
    "calls_in",
    "appointments_booked",
    "appointments_held",
    "no_shows",
    "conversions",
    "portfolio_clients",
    "portfolio_contacted_12m",
]


def test_org_children_sum_to_parent() -> None:
    rows = pq.read_table(EXPORTS / "org_weekly.parquet").to_pylist()
    by_key = {(r["iso_week_id"], r["node_id"]): r for r in rows}
    for parent in rows:
        if parent["level"] == OrgLevel.BRANCH:
            continue
        children = [
            r
            for r in rows
            if r["iso_week_id"] == parent["iso_week_id"] and r["parent_id"] == parent["node_id"]
        ]
        assert children, parent["node_id"]
        for m in ADDITIVE:
            assert sum(c[m] for c in children) == parent[m], (parent["node_id"], m)
    assert len(by_key) == len(rows)


def test_advisor_rows_sum_to_branch_except_unknown_advisor() -> None:
    advisors = pq.read_table(EXPORTS / "advisor_weekly.parquet").to_pylist()
    branches = [
        r
        for r in pq.read_table(EXPORTS / "org_weekly.parquet").to_pylist()
        if r["level"] == OrgLevel.BRANCH
    ]
    gaps = Counter()
    for b in branches:
        mine = [
            a
            for a in advisors
            if a["iso_week_id"] == b["iso_week_id"] and a["branch_id"] == b["node_id"]
        ]
        assert len(mine) == b["active_advisors"]
        gaps[(b["iso_week_id"], b["node_id"])] = b["activities_completed"] - sum(
            a["activities_completed"] for a in mine
        )
    assert {k: v for k, v in gaps.items() if v} == {("2026-W39", "BR-0501"): 1}
    # Portfolio clients sit under the holder here and under the transit branch in org_weekly,
    # which differ for a mover (DQ025), so they reconcile nationally rather than per branch.
    national = {b["iso_week_id"]: 0 for b in branches}
    for b in branches:
        national[b["iso_week_id"]] += b["portfolio_clients"]
    for week, total in national.items():
        assert sum(a["portfolio_clients"] for a in advisors if a["iso_week_id"] == week) == total


def test_weekly_report_first_week_has_no_prior() -> None:
    rows = pq.read_table(EXPORTS / "weekly_report.parquet").to_pylist()
    first = [r for r in rows if r["iso_week_id"] == WEEKS[0]]
    assert all(r["prior_week_value"] is None and r["wow_pct"] is None for r in first)
    assert {r["flag"] for r in rows} == {"UP", "DOWN", "FLAT", "ANOMALY"}
    json.dumps(rows, default=str)  # serializable for the narrative input
