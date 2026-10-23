"""``pipeline_graph.json``: the runner's stage DAG merged with dbt's manifest.

dbt models collapse into one DBT_LAYER node per folder under ``models/`` (staging,
intermediate, marts), listing its models; the layers sit between ``dbt_build`` and the
stages after it. Raw sources become one SOURCE node per source system (the table prefix
before ``__``) between ``generate`` and ``ingest``; seeds become one reference node feeding
``dbt_build``. IDs come from names only, so they are stable across runs. Without a
manifest the graph has the stages and outputs only.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pulse.contracts.enums import PipelineNodeKind
from pulse.contracts.exports import PipelineEdge, PipelineGraph, PipelineNode, Position
from pulse.runner.dag import execution_order
from pulse.runner.stage import Stage

log = logging.getLogger(__name__)

COLUMN_WIDTH = 240.0
ROW_HEIGHT = 160.0
RAW_SOURCE = "raw"
GENERATE_STAGE = "generate"
INGEST_STAGE = "ingest"
DBT_STAGE = "dbt_build"
LAYER_ORDER = ("staging", "intermediate", "marts")
SOURCE_LABELS = {"snowflake": "'Snowflake' activity", "teradata": "'Teradata' EDW"}
REFERENCE_ID = "src_reference"
REFERENCE_LABEL = "Reference seeds"
# Where a stage's output lands outside the pipeline.
OUTPUTS: dict[str, tuple[tuple[str, str], ...]] = {
    "export": (("out_web", "pulse.charliebuild.com"),),
}

Manifest = Mapping[str, Any]


def read_manifest(path: Path) -> Manifest | None:
    """dbt's ``manifest.json``, or None (with a warning) if dbt has not written one."""
    if not path.exists():
        log.warning("No dbt manifest at %s: pipeline graph has stages only.", path)
        return None
    data: Manifest = json.loads(path.read_text(encoding="utf-8"))
    return data


def _layers(manifest: Manifest) -> dict[str, list[str]]:
    """Model names by layer folder, layers in pipeline order, models sorted."""
    layers: dict[str, list[str]] = {}
    for node in manifest.get("nodes", {}).values():
        if node["resource_type"] == "model":
            layer = node["fqn"][1] if len(node["fqn"]) > 2 else "models"
            layers.setdefault(layer, []).append(node["name"])
    known = [layer for layer in LAYER_ORDER if layer in layers]
    order = known + sorted(set(layers) - set(known))
    return {layer: sorted(layers[layer]) for layer in order}


def _layer_edges(manifest: Manifest, layers: Mapping[str, list[str]]) -> list[tuple[str, str]]:
    """Cross-layer model dependencies that point forward in layer order, minus any implied
    by a longer path. Backward ones (an intermediate model reading ``dim_date``) would make
    the layers a cycle."""
    layer_of = {
        f"model.{node['package_name']}.{node['name']}": node["fqn"][1]
        if len(node["fqn"]) > 2
        else "models"
        for node in manifest.get("nodes", {}).values()
        if node["resource_type"] == "model"
    }
    rank = {layer: i for i, layer in enumerate(layers)}
    direct: set[tuple[str, str]] = set()
    for node_id, layer in layer_of.items():
        for upstream in manifest["nodes"][node_id]["depends_on"]["nodes"]:
            if upstream in layer_of and rank[layer_of[upstream]] < rank[layer]:
                direct.add((layer_of[upstream], layer))

    def reachable(start: str, skip: tuple[str, str]) -> set[str]:
        seen: set[str] = set()
        frontier = {start}
        while frontier:
            nxt = {t for s, t in direct if s in frontier and (s, t) != skip} - seen
            seen |= nxt
            frontier = nxt
        return seen

    kept = [(s, t) for s, t in direct if t not in reachable(s, (s, t))]
    return sorted(kept, key=lambda e: (rank[e[0]], rank[e[1]]))


def _source_systems(manifest: Manifest) -> list[str]:
    systems = {
        source["name"].split("__", 1)[0]
        for source in manifest.get("sources", {}).values()
        if source["source_name"] == RAW_SOURCE
    }
    return sorted(systems)


def _has_seeds(manifest: Manifest) -> bool:
    return any(node["resource_type"] == "seed" for node in manifest.get("nodes", {}).values())


def build_pipeline_graph(stages: Sequence[Stage], manifest: Manifest | None) -> PipelineGraph:
    """Nodes and edges for the pipeline view, laid out left to right by depth."""
    ordered = execution_order(stages)
    names = {stage.name for stage in ordered}
    nodes: dict[str, PipelineNode] = {}
    edges: list[tuple[str, str]] = []

    def add(node_id: str, label: str, kind: PipelineNodeKind, **fields: Any) -> None:
        nodes[node_id] = PipelineNode(
            id=node_id, label=label, kind=kind, position=Position(x=0, y=0), **fields
        )

    layers = _layers(manifest) if manifest else {}
    layer_edges = _layer_edges(manifest, layers) if manifest else []
    first_layers = [x for x in layers if all(t != x for _, t in layer_edges)]
    last_layers = [x for x in layers if all(s != x for s, _ in layer_edges)]
    systems = _source_systems(manifest) if manifest else []

    for stage in ordered:
        add(stage.name, stage.label, PipelineNodeKind.STAGE, stage=stage.name)
        if stage.name == DBT_STAGE:
            for layer, models in layers.items():
                add(
                    f"dbt_{layer}",
                    f"{layer.capitalize()} ({len(models)} models)",
                    PipelineNodeKind.DBT_LAYER,
                    stage=DBT_STAGE,
                    models=models,
                )
    for system in systems:
        add(f"src_{system}", SOURCE_LABELS.get(system, system), PipelineNodeKind.SOURCE)
    if manifest and _has_seeds(manifest) and DBT_STAGE in names:
        add(REFERENCE_ID, REFERENCE_LABEL, PipelineNodeKind.SOURCE)
        edges.append((REFERENCE_ID, DBT_STAGE))

    for stage in ordered:
        for dep in stage.depends_on:
            if dep == DBT_STAGE and layers:
                edges.extend((f"dbt_{x}", stage.name) for x in last_layers)
            elif dep == GENERATE_STAGE and stage.name == INGEST_STAGE and systems:
                for system in systems:
                    edges.extend([(dep, f"src_{system}"), (f"src_{system}", stage.name)])
            else:
                edges.append((dep, stage.name))
        if stage.name == DBT_STAGE:
            edges.extend((DBT_STAGE, f"dbt_{x}") for x in first_layers)
            edges.extend((f"dbt_{s}", f"dbt_{t}") for s, t in layer_edges)
        for out_id, label in OUTPUTS.get(stage.name, ()):
            add(out_id, label, PipelineNodeKind.OUTPUT)
            edges.append((stage.name, out_id))

    return PipelineGraph(
        nodes=_laid_out(nodes, edges),
        edges=[PipelineEdge(id=f"{s}->{t}", source=s, target=t) for s, t in edges],
    )


def _laid_out(
    nodes: Mapping[str, PipelineNode], edges: Sequence[tuple[str, str]]
) -> list[PipelineNode]:
    """Column = longest path from a root; a root SOURCE sits just left of its first consumer.
    Each column stacks outputs first, then the rest in insertion order, centred on y = 0.
    Outputs on top keep ``release_lock`` in the bottom lane, so the line from
    ``persist_state`` runs below ``export`` instead of through it."""
    parents: dict[str, list[str]] = {n: [] for n in nodes}
    for s, t in edges:
        parents[t].append(s)
    col: dict[str, int] = {}

    def depth(node_id: str) -> int:
        if node_id not in col:
            col[node_id] = 1 + max((depth(p) for p in parents[node_id]), default=-1)
        return col[node_id]

    for node_id in nodes:
        depth(node_id)
    for node_id, node in nodes.items():
        children = [col[t] for s, t in edges if s == node_id]
        if node.kind is PipelineNodeKind.SOURCE and not parents[node_id] and children:
            col[node_id] = min(children) - 1

    columns: dict[int, list[str]] = {}
    for node_id in nodes:
        columns.setdefault(col[node_id], []).append(node_id)
    placed = []
    for c, members in sorted(columns.items()):
        members.sort(key=lambda n: nodes[n].kind is not PipelineNodeKind.OUTPUT)
        for row, node_id in enumerate(members):
            y = (row - (len(members) - 1) / 2) * ROW_HEIGHT
            position = Position(x=c * COLUMN_WIDTH, y=y)
            placed.append(nodes[node_id].model_copy(update={"position": position}))
    return placed
