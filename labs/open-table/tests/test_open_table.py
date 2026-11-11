"""Idempotent weekly writes, rejected schema changes and time travel on a local Iceberg table."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pytest
from pyiceberg.exceptions import ValidationError
from pyiceberg.table import Table
from pyiceberg.types import StringType

_SPEC = importlib.util.spec_from_file_location(
    "open_table", Path(__file__).resolve().parents[1] / "open_table.py"
)
assert _SPEC and _SPEC.loader
ot = importlib.util.module_from_spec(_SPEC)
sys.modules["open_table"] = ot
_SPEC.loader.exec_module(ot)


@pytest.fixture
def source() -> pa.Table:
    return ot.read_fixture()


@pytest.fixture
def table(tmp_path: Path, source: pa.Table) -> Table:
    return ot.create_table(ot.open_catalog(tmp_path / "wh"), source.schema)


def week(source: pa.Table, iso_week_id: str) -> pa.Table:
    return source.filter(pc.equal(source["iso_week_id"], iso_week_id))


def test_same_week_twice_gives_the_same_rows_and_hash(table: Table, source: pa.Table) -> None:
    w40 = week(source, "2026-W40")
    ot.write_week(table, week(source, "2026-W39"))
    ot.write_week(table, w40)
    once = table.scan().to_arrow()
    ot.write_week(table, w40)
    twice = table.scan().to_arrow()
    assert once.num_rows == twice.num_rows == 14 + 13
    assert ot.content_hash(once) == ot.content_hash(twice)
    assert ot.content_hash(twice) == ot.content_hash(
        pa.concat_tables([week(source, "2026-W39"), w40])
    )


def test_a_rerun_with_fewer_rows_replaces_the_week_instead_of_merging(
    table: Table, source: pa.Table
) -> None:
    w40 = week(source, "2026-W40")
    ot.write_week(table, w40)
    ot.write_week(table, w40.slice(0, 5))
    assert table.scan().to_arrow().num_rows == 5


def test_a_multi_week_batch_is_rejected(table: Table, source: pa.Table) -> None:
    with pytest.raises(ValueError, match="exactly one ISO week"):
        ot.write_week(table, source)
    assert table.current_snapshot() is None


def test_an_incompatible_type_change_is_rejected_and_the_table_is_unchanged(
    table: Table, source: pa.Table
) -> None:
    ot.write_week(table, week(source, "2026-W40"))
    schema_before = table.schema()
    with pytest.raises(ValidationError), table.update_schema() as update:
        update.update_column("activities_completed", StringType())
    table.refresh()
    assert table.schema() == schema_before


def test_writing_a_frame_with_a_mistyped_column_is_rejected(table: Table, source: pa.Table) -> None:
    w40 = week(source, "2026-W40")
    snapshot = table.current_snapshot()
    i = w40.schema.get_field_index("activities_completed")
    bad = w40.set_column(
        i, "activities_completed", pc.cast(w40["activities_completed"], pa.string())
    )
    with pytest.raises(ValueError):
        ot.write_week(table, bad)
    assert table.current_snapshot() == snapshot


def test_time_travel_returns_the_snapshot_before_evolution(table: Table, source: pa.Table) -> None:
    w40 = week(source, "2026-W40")
    ot.write_week(table, w40)
    old = table.current_snapshot()
    with table.update_schema() as update:
        update.add_column("loaded_by_run", StringType())
    ot.write_week(
        table,
        w40.slice(0, 3).append_column("loaded_by_run", pa.array(["r2"] * 3)),
    )
    now = table.scan().to_arrow()
    assert now.num_rows == 3 and "loaded_by_run" in now.schema.names
    then = table.scan(snapshot_id=old.snapshot_id).to_arrow()
    assert then.num_rows == 13
    assert "loaded_by_run" not in then.schema.names
    assert ot.content_hash(then) == ot.content_hash(w40)


def test_the_demo_reads_back_through_duckdb(tmp_path: Path) -> None:
    result = ot.run(tmp_path / "wh")
    assert result["rows_after_appends"] == result["rows_after_rerun"] == 55
    assert result["hash_after_appends"] == result["hash_after_rerun"]
    assert result["time_travel_hash"] == result["hash_after_appends"]
    assert result["null_loaded_by_run"] == 55 - 13
    assert sum(n for _, n in result["duckdb_week_counts"]) == 55
