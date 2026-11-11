"""Semantic-layer lab tests (#322). Need the fixture warehouse from `make dbt-build-ci`."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import duckdb
import pytest

LAB_DIR = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("parity", LAB_DIR / "parity.py")
assert _spec and _spec.loader
parity = importlib.util.module_from_spec(_spec)
sys.modules["parity"] = parity
_spec.loader.exec_module(parity)

WAREHOUSE = parity.DEFAULT_WAREHOUSE
pytestmark = pytest.mark.skipif(
    not WAREHOUSE.exists(), reason="run `make dbt-build-ci` to build the fixture warehouse"
)

GUARD = "        filter: \"{{ Dimension('kpi_event__is_window_complete') }} = true\"\n"

# Deliberately wrong metric definitions: (file, find, replace, metric the check must flag).
MUTATIONS = {
    "distinct clients counted, not distinct": (
        "semantic_models.yml",
        "agg: count_distinct",
        "agg: count",
        "clients_contacted",
    ),
    "lead KPI without the 12-month window guard": (
        "metrics.yml",
        GUARD,
        "",
        "portfolio_contacted_rate_12m",
    ),
    "show rate denominator forgets no-shows": (
        "metrics.yml",
        "denominator: appointments_held_or_no_show",
        "denominator: appointments_held",
        "show_rate",
    ),
}


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, parity.Report]:
    project = parity.copy_project(tmp_path_factory.mktemp("lab"))
    return project, parity.compare(project, WAREHOUSE)


def test_metricflow_equals_mart_at_every_level(built: tuple[Path, parity.Report]) -> None:
    _, report = built
    assert report.ok, report.mismatches[:10]
    with duckdb.connect(str(WAREHOUSE), read_only=True) as con:
        expected = dict(
            con.sql("select level, count(*) from marts.mart_org_weekly group by 1").fetchall()
        )
    assert report.rows == expected
    assert report.cells == sum(expected.values()) * len(parity.METRICS)


@pytest.mark.parametrize("name", MUTATIONS)
def test_wrong_metric_definition_is_caught(name: str, tmp_path: Path) -> None:
    file, find, replace, metric = MUTATIONS[name]
    project = parity.copy_project(tmp_path)
    path = project / "models" / "semantic" / file
    text = path.read_text()
    assert find in text, f"mutation target not found in {file}"
    path.write_text(text.replace(find, replace))

    report = parity.compare(project, WAREHOUSE)

    assert not report.ok
    assert any(f" {metric}:" in line for line in report.mismatches)


def _scoped(project: Path, viewer: str | None, sql: str) -> list[tuple]:
    db = project / "target" / "semantic_lab.duckdb"
    with duckdb.connect(str(db), read_only=True) as con:
        if viewer is not None:
            con.execute("set variable pulse_viewer = ?", [viewer])
        return con.sql(sql).fetchall()


def test_row_level_scope_illustration(built: tuple[Path, parity.Report]) -> None:
    project, _ = built
    by_week = (
        "select iso_week_id, sum(calls_out), sum(portfolio_clients) "
        "from secure_kpi_events group by 1 order by 1"
    )
    with duckdb.connect(str(WAREHOUSE), read_only=True) as con:
        gta = con.sql(
            "select iso_week_id, calls_out, portfolio_clients from marts.mart_org_weekly "
            "where level = 'DISTRICT' and node_id = 'GTA' order by 1"
        ).fetchall()
    assert _scoped(project, "dm_gta", by_week) == gta

    regions = "select distinct region_code from secure_kpi_events join sem_org using (branch_id)"
    assert _scoped(project, "rm_quebec", regions) == [("QC",)]
    assert _scoped(project, "bm_byward", "select distinct branch_id from secure_kpi_events") == [
        ("BR-0201",)
    ]
    count = "select count(*) from secure_kpi_events"
    total = _scoped(project, None, "select count(*) from sem_kpi_events")[0][0]
    assert _scoped(project, "national_analyst", count) == [(total,)]
    # Fail closed: no viewer, or one with no scope row, sees nothing.
    assert _scoped(project, None, count) == [(0,)]
    assert _scoped(project, "someone_else", count) == [(0,)]
