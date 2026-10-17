"""pipeline_graph.json from the runner DAG and a dbt manifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pulse.contracts.enums import PipelineNodeKind
from pulse.contracts.exports import PipelineGraph
from pulse.export.pipeline_graph import build_pipeline_graph, read_manifest
from pulse.runner.dag import WEEKLY_STAGES

FIXTURE_EXPORTS = Path(__file__).resolve().parents[2] / "fixtures/exports"


def _model(layer: str, name: str, *upstream: str) -> tuple[str, dict[str, Any]]:
    return f"model.advisor_pulse.{name}", {
        "resource_type": "model",
        "package_name": "advisor_pulse",
        "name": name,
        "fqn": ["advisor_pulse", layer, name],
        "depends_on": {"nodes": [f"model.advisor_pulse.{u}" for u in upstream]},
    }


def _source(source_name: str, name: str) -> tuple[str, dict[str, Any]]:
    return f"source.advisor_pulse.{source_name}.{name}", {"source_name": source_name, "name": name}


def manifest() -> dict[str, Any]:
    nodes = dict(
        [
            _model("staging", "stg_activity"),
            _model("staging", "stg_client"),
            _model("intermediate", "int_book", "stg_client", "dim_date"),
            _model("marts", "dim_date"),
            # Reads staging directly as well as through intermediate.
            _model("marts", "mart_org", "int_book", "stg_activity"),
            ("seed.advisor_pulse.org_branch", {"resource_type": "seed", "name": "org_branch"}),
            ("test.advisor_pulse.t", {"resource_type": "test", "name": "t"}),
        ]
    )
    sources = dict(
        [
            _source("raw", "teradata__clnt"),
            _source("raw", "snowflake__activity"),
            _source("raw", "teradata__advsr"),
            _source("meta", "run_log"),
        ]
    )
    return {"nodes": nodes, "sources": sources}


def _edges(graph: PipelineGraph) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in graph.edges}


def test_graph_validates_against_the_contract() -> None:
    graph = build_pipeline_graph(WEEKLY_STAGES, manifest())
    again = PipelineGraph.model_validate_json(graph.model_dump_json())
    assert again == graph
    ids = [n.id for n in graph.nodes]
    assert len(ids) == len(set(ids))
    assert all(e.source in ids and e.target in ids for e in graph.edges)
    assert len({(n.position.x, n.position.y) for n in graph.nodes}) == len(ids)


def test_node_ids_are_stable_across_runs_and_manifest_order() -> None:
    first = build_pipeline_graph(WEEKLY_STAGES, manifest())
    shuffled = manifest()
    shuffled["nodes"] = dict(reversed(shuffled["nodes"].items()))
    shuffled["sources"] = dict(reversed(shuffled["sources"].items()))
    assert build_pipeline_graph(WEEKLY_STAGES, shuffled).model_dump_json() == (
        first.model_dump_json()
    )
    assert build_pipeline_graph(WEEKLY_STAGES, manifest()) == first


def test_dbt_models_are_grouped_by_layer_with_counts() -> None:
    graph = build_pipeline_graph(WEEKLY_STAGES, manifest())
    layers = {n.id: n for n in graph.nodes if n.kind is PipelineNodeKind.DBT_LAYER}
    assert {i: n.models for i, n in layers.items()} == {
        "dbt_staging": ["stg_activity", "stg_client"],
        "dbt_intermediate": ["int_book"],
        "dbt_marts": ["dim_date", "mart_org"],
    }
    assert layers["dbt_staging"].label == "Staging (2 models)"
    assert {n.stage for n in layers.values()} == {"dbt_build"}
    # One chain: intermediate reading dim_date and marts reading staging add no edges.
    assert _edges(graph) & {(s, t) for s in layers for t in layers} == {
        ("dbt_staging", "dbt_intermediate"),
        ("dbt_intermediate", "dbt_marts"),
    }
    xs = [layers[i].position.x for i in ("dbt_staging", "dbt_intermediate", "dbt_marts")]
    assert xs == sorted(xs) and len(set(xs)) == 3


def test_edges_match_the_fixture_graph() -> None:
    graph = build_pipeline_graph(WEEKLY_STAGES, manifest())
    fixture = PipelineGraph.model_validate_json(
        (FIXTURE_EXPORTS / "pipeline_graph.json").read_text()
    )
    assert {n.id: n.kind for n in graph.nodes} == {n.id: n.kind for n in fixture.nodes}
    assert _edges(graph) == _edges(fixture)


def test_sources_sit_before_their_first_consumer() -> None:
    graph = build_pipeline_graph(WEEKLY_STAGES, manifest())
    x = {n.id: n.position.x for n in graph.nodes}
    assert x["generate"] < x["src_snowflake"] == x["src_teradata"] < x["ingest"]
    assert x["src_reference"] < x["dbt_build"]
    assert x["export"] < x["out_web"]


def test_without_a_manifest_the_graph_has_stages_and_outputs(tmp_path: Path) -> None:
    assert read_manifest(tmp_path / "manifest.json") is None
    graph = build_pipeline_graph(WEEKLY_STAGES, None)
    kinds = {n.kind for n in graph.nodes}
    assert kinds == {PipelineNodeKind.STAGE, PipelineNodeKind.OUTPUT}
    assert {("ingest", "dbt_build"), ("dbt_build", "checks")} <= _edges(graph)
    by_id = {n.id: n.position for n in graph.nodes}
    assert by_id["publish_sheets"].x == by_id["persist_state"].x
    assert by_id["publish_sheets"].y != by_id["persist_state"].y


def test_read_manifest_reads_dbt_json(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest()), encoding="utf-8")
    assert read_manifest(path) == manifest()
