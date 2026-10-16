"""Ingest guarantees from PLAN.md §9, end to end on the committed fixtures.

Double runs are no-ops, a crash between loaders recovers to the clean-run state, late files
load and are late by the staging rule, and a changed file loads as a new batch.
"""

from __future__ import annotations

import hashlib
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pulse.contracts.defects import DefectManifest
from pulse.contracts.enums import LoadStatus, RunType, StageStatus
from pulse.ingest import meta
from pulse.ingest.stage import ingest
from pulse.runner import WEEKLY_STAGES, Runner, StageContext, StageResult, WarehouseSink
from pulse.warehouse import TABLES, WAREHOUSE_FILE, connect

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
RAW_TABLES = [spec.name for spec in TABLES if spec.name.startswith("raw.")]
# Differ between runs by design: the batch id carries the run id, and the load time.
RUN_SPECIFIC = ("_batch_id", "_loaded_at")


class FixedClock:
    def __init__(self, now: datetime = datetime(2026, 10, 5, 4, tzinfo=UTC)) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def sleep(self, seconds: float) -> None:
        pass


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURES / "sources", tmp_path / "sources")
    return tmp_path


def _ingest(data_dir: Path, run_id: str) -> StageResult:
    ctx = StageContext(run_id, RunType.MANUAL, "2026-W40", data_dir, FixedClock())
    return ingest(ctx)


def _state(data_dir: Path, *, exact: bool = False) -> dict[str, object]:
    """Raw content hashes, manifest counts, watermarks and quarantine keys.

    ``exact`` keeps the run-specific columns, so two states match only if nothing was written.
    """
    con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
    try:
        state: dict[str, object] = {}
        for table in RAW_TABLES:
            exclude = "" if exact else f" EXCLUDE ({', '.join(RUN_SPECIFIC)})"
            rows = con.execute(f"SELECT *{exclude} FROM {table} ORDER BY ALL").fetchall()
            state[table] = (len(rows), hashlib.sha256(repr(rows).encode()).hexdigest())
        manifest = meta.get_manifest(con)
        state["manifest"] = sorted(
            (m.file_path, m.file_sha256, m.status.value, m.rows_loaded, m.rows_quarantined)
            for m in manifest
        )
        state["watermarks"] = sorted(
            con.execute("SELECT source, table_name, watermark_value FROM meta.watermark").fetchall()
        )
        state["rejected"] = sorted(
            (r.source_file, r.source_row, r.rule_id) for r in meta.get_rejected_rows(con)
        )
        return state
    finally:
        con.close()


def test_second_run_is_a_no_op(data_dir: Path) -> None:
    first = _ingest(data_dir, "run-1")
    assert first.status is StageStatus.SUCCESS
    assert first.rows_out and first.rows_quarantined == 10
    before = _state(data_dir, exact=True)

    second = _ingest(data_dir, "run-2")

    assert second.status is StageStatus.SKIPPED
    assert (second.rows_in, second.rows_out, second.rows_quarantined) == (0, 0, 0)
    assert _state(data_dir, exact=True) == before


def test_crash_between_loaders_recovers_to_clean_state(
    data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean_dir = tmp_path_factory.mktemp("clean")
    shutil.copytree(FIXTURES / "sources", clean_dir / "sources")
    _ingest(clean_dir, "clean")
    clean = _state(clean_dir)

    def crash(*args: object, **kwargs: object) -> StageResult:
        raise RuntimeError("simulated crash after the activity load")

    monkeypatch.setattr("pulse.ingest.stage.load_teradata_client", crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        _ingest(data_dir, "run-1")
    partial = _state(data_dir)
    assert partial["raw.snowflake__activity"] == clean["raw.snowflake__activity"]
    assert partial["raw.teradata__clnt"][0] == 0  # type: ignore[index]

    monkeypatch.undo()
    recovered = _ingest(data_dir, "run-2")

    assert recovered.status is StageStatus.SUCCESS
    assert "activity: SKIPPED_DUPLICATE" in (recovered.message or "")
    assert _state(data_dir) == clean


def test_late_arriving_rows_load_and_are_late_by_the_staging_rule(data_dir: Path) -> None:
    """stg_activity: is_late_arriving = Toronto activity week < Toronto extract week."""
    defects = DefectManifest.model_validate_json((FIXTURES / "defects.json").read_text())
    late = {d.natural_key: d.expected_value for d in defects.defects if d.kind == "LATE_ARRIVING"}
    assert late
    _ingest(data_dir, "run-1")

    # A later extract re-delivers an old activity under a new id.
    source = data_dir / "sources/snowflake/activity/extract_date=2026-09-13/part-000.parquet"
    table = pq.read_table(source)
    row = table.slice(0, 1).to_pylist()[0]
    row["ACTIVITY_ID"] = "ACT-1a7e0000beef"
    row["_EXTRACTED_AT"] = datetime(2026, 10, 12, 3, tzinfo=UTC)
    new_part = source.parents[1] / "extract_date=2026-10-11/part-000.parquet"
    new_part.parent.mkdir()
    pq.write_table(pa.Table.from_pylist([row], schema=table.schema), new_part)
    late[row["ACTIVITY_ID"]] = None

    result = _ingest(data_dir, "run-2")

    assert (result.rows_in, result.rows_out) == (1, 1)
    con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
    try:
        rows = con.execute(
            "SELECT ACTIVITY_ID, "
            "strftime(timezone('America/Toronto', ACTIVITY_TS), '%G-W%V') AS activity_week, "
            "strftime(timezone('America/Toronto', _EXTRACTED_AT), '%G-W%V') AS extract_week "
            "FROM raw.snowflake__activity WHERE ACTIVITY_ID IN (SELECT unnest(?))",
            [list(late)],
        ).fetchall()
    finally:
        con.close()
    assert {activity_id for activity_id, _, _ in rows} == set(late)
    for activity_id, activity_week, extract_week in rows:
        assert activity_week < extract_week
        if late[activity_id] is not None:
            assert activity_week == late[activity_id]


def test_changed_file_loads_as_a_new_batch(data_dir: Path) -> None:
    _ingest(data_dir, "run-1")
    path = data_dir / "sources/snowflake/activity/extract_date=2026-09-20/part-000.parquet"
    table = pq.read_table(path)
    durations = table.column("DURATION_MIN").to_pylist()
    durations[0] = (durations[0] or 0) + 1
    index = table.schema.get_field_index("DURATION_MIN")
    pq.write_table(table.set_column(index, table.field(index), pa.array(durations)), path)

    result = _ingest(data_dir, "run-2")

    assert result.status is StageStatus.SUCCESS
    assert result.rows_out == table.num_rows - _rejected_in(data_dir, path)
    con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
    try:
        versions = meta.get_manifest(con, path.relative_to(data_dir / "sources").as_posix())
    finally:
        con.close()
    assert len({v.file_sha256 for v in versions}) == 2
    assert {v.status for v in versions} == {LoadStatus.LOADED}


def _rejected_in(data_dir: Path, path: Path) -> int:
    name = path.relative_to(data_dir / "sources").as_posix()
    con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
    try:
        return len({r.source_row for r in meta.get_rejected_rows(con) if r.source_file == name})
    finally:
        con.close()


def test_ingest_is_a_registered_runner_stage_with_run_log_rows(data_dir: Path) -> None:
    warehouse = data_dir / WAREHOUSE_FILE
    report = Runner(
        WEEKLY_STAGES, data_dir=data_dir, sinks=[WarehouseSink(warehouse)], clock=FixedClock()
    ).run("2026-W40", RunType.WEEKLY, "weekly-2026-W40-1")

    con = connect(warehouse, read_only=True)
    try:
        logged = [r for r in meta.get_run_log(con) if r.run_id == "weekly-2026-W40-1"]
    finally:
        con.close()
    finals = {r.stage: r for r in logged if r.status is not StageStatus.RUNNING}
    assert finals["ingest"].status is StageStatus.SUCCESS
    assert finals["ingest"].rows_quarantined == 10
    assert finals["ingest"].rows_out == report.rows[2].rows_out
    # The RUNNING row is upserted by the final row of the same attempt.
    assert Counter(r.stage for r in logged)["ingest"] == 1
    assert finals["ingest"].attempt == 1 and finals["ingest"].ended_at is not None
