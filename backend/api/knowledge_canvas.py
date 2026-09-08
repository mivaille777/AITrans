from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/knowledge/canvas", tags=["knowledge-canvas"])


class CanvasNode(BaseModel):
    id: str
    title: str
    type: str
    summary: str = ""
    metadata: dict = Field(default_factory=dict)


class CanvasEdge(BaseModel):
    source: str
    target: str
    relation: str = "related"
    confidence: float = 0.0


class CanvasGraph(BaseModel):
    nodes: list[CanvasNode] = Field(default_factory=list)
    edges: list[CanvasEdge] = Field(default_factory=list)


_graph = CanvasGraph(
    nodes=[
        CanvasNode(id="paper-1", title="Agent Planning Research", type="paper"),
        CanvasNode(id="concept-1", title="Supervisor Routing", type="concept"),
        CanvasNode(id="note-1", title="Implementation Notes", type="note"),
    ],
    edges=[
        CanvasEdge(source="paper-1", target="concept-1", relation="supports", confidence=0.86),
        CanvasEdge(source="concept-1", target="note-1", relation="implements", confidence=0.78),
    ],
)


@router.get("")
def get_canvas() -> CanvasGraph:
    return _graph


@router.post("")
def update_canvas(graph: CanvasGraph) -> CanvasGraph:
    global _graph
    _graph = graph
    return _graph


@router.post("/relation")
def add_relation(edge: CanvasEdge):
    _graph.edges.append(edge)
    return edge
