"""The runner DAG as ``pipeline_graph`` nodes and edges.

Stage nodes only. Issue #41 merges these with the dbt manifest's layers and the source and
output nodes, and owns the final layout.
"""

from __future__ import annotations

from collections.abc import Sequence

from pulse.contracts.enums import PipelineNodeKind
from pulse.contracts.exports import PipelineEdge, PipelineGraph, PipelineNode, Position
from pulse.runner.dag import execution_order
from pulse.runner.stage import Stage

COLUMN_WIDTH = 240.0
ROW_HEIGHT = 120.0


def stage_graph(stages: Sequence[Stage]) -> PipelineGraph:
    """Lay stages out by depth (longest path from a root); siblings stack downwards."""
    ordered = execution_order(stages)
    depth: dict[str, int] = {}
    for stage in ordered:
        depth[stage.name] = 1 + max((depth[d] for d in stage.depends_on), default=-1)
    rows: dict[int, int] = {}
    nodes = []
    for stage in ordered:
        col = depth[stage.name]
        row = rows.get(col, 0)
        rows[col] = row + 1
        nodes.append(
            PipelineNode(
                id=stage.name,
                label=stage.label,
                kind=PipelineNodeKind.STAGE,
                stage=stage.name,
                position=Position(x=col * COLUMN_WIDTH, y=row * ROW_HEIGHT),
            )
        )
    edges = [
        PipelineEdge(id=f"{dep}->{stage.name}", source=dep, target=stage.name)
        for stage in ordered
        for dep in stage.depends_on
    ]
    return PipelineGraph(nodes=nodes, edges=edges)
