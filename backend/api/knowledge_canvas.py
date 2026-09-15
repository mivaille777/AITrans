from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.services.agent_context_builder import AgentContextBuilder
from backend.services.agent_knowledge_retrieval import AgentKnowledgeRetriever
from backend.services.knowledge_graph_service import suggest_relations
from backend.services.knowledge_graph_repository import KnowledgeGraphRepository

router = APIRouter(prefix="/knowledge/canvas", tags=["knowledge-canvas"])
repository = KnowledgeGraphRepository()
retriever = AgentKnowledgeRetriever(repository)
context_builder = AgentContextBuilder()


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


class KnowledgeRetrievalRequest(BaseModel):
    query: str
    top_k: int = 5


class AgentContextRequest(BaseModel):
    query: str
    top_k: int = 5


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


@router.post("/retrieve")
def retrieve_knowledge(payload: KnowledgeRetrievalRequest):
    return {
        "query": payload.query,
        "results": retriever.retrieve(payload.query, payload.top_k),
    }


@router.post("/context")
def build_agent_context(payload: AgentContextRequest):
    evidence = retriever.retrieve(payload.query, payload.top_k)
    return context_builder.build(payload.query, evidence)
