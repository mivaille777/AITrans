from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.services.knowledge_graph_service import suggest_relations
from backend.services.knowledge_graph_repository import KnowledgeGraphRepository

router = APIRouter(prefix="/knowledge/canvas", tags=["knowledge-canvas"])
repository = KnowledgeGraphRepository()


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


class CanvasAnalyzeRequest(BaseModel):
    nodes: list[CanvasNode] = Field(default_factory=list)


def default_graph() -> CanvasGraph:
    return CanvasGraph(
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
    data = repository.get_graph()
    if not data.get("nodes"):
        graph = default_graph()
        repository.save_graph(graph.model_dump())
        return graph
    return CanvasGraph(**data)


@router.post("")
def update_canvas(graph: CanvasGraph) -> CanvasGraph:
    repository.save_graph(graph.model_dump())
    return graph


@router.post("/relation")
def add_relation(edge: CanvasEdge):
    graph = get_canvas()
    graph.edges.append(edge)
    repository.save_graph(graph.model_dump())
    return edge


@router.post("/analyze")
def analyze_canvas(payload: CanvasAnalyzeRequest):
    return {"edges": suggest_relations([node.model_dump() for node in payload.nodes])}
