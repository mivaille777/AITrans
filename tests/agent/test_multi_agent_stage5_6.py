from backend.agent_core.multi_agent.agent_registry import AgentRegistry
from backend.agent_core.multi_agent.base_agent import AgentResult, BaseAgent
from backend.agent_core.multi_agent.context import (
    AgentMemoryAdapter,
    KnowledgeInjector,
    SharedContextManager,
)
from backend.agent_core.multi_agent.orchestration.executor import AgentExecutor
from backend.services.agent_knowledge_runtime import AgentKnowledgeContext


class _KnowledgeRuntime:
    def build_context(self, query: str, top_k: int = 5) -> AgentKnowledgeContext:
        assert top_k == 3
        return AgentKnowledgeContext(
            query=query,
            context="grounded context",
            citations=[
                {
                    "id": "node-1",
                    "title": "Grounded Node",
                    "source_type": "concept",
                    "score": 0.9,
                }
            ],
        )


class _ProbeAgent(BaseAgent):
    name = "probe"

    def execute(self, task: str, context=None) -> AgentResult:
        assert context is not None
        assert context.knowledge_context == "grounded context"
        assert context.citations[0]["id"] == "node-1"
        return AgentResult(
            agent_name=self.name,
            output=f"done:{task}",
            metadata={"knowledge_seen": True},
        )


def test_knowledge_injector_accepts_runtime_dataclass() -> None:
    context = SharedContextManager().create("agent knowledge")
    injector = KnowledgeInjector(_KnowledgeRuntime(), top_k=3)

    result = injector.inject(context.query, context)

    assert result is context
    assert context.knowledge_context == "grounded context"
    assert context.citations == [
        {
            "id": "node-1",
            "title": "Grounded Node",
            "source_type": "concept",
            "score": 0.9,
        }
    ]
    assert context.memory["knowledge_query"] == "agent knowledge"
    assert context.memory["knowledge_citation_count"] == 1


def test_default_memory_adapter_round_trips_agent_results() -> None:
    memory = AgentMemoryAdapter()
    payload = {"agent": "research", "finding": "graph-aware RAG"}

    memory.save(payload, "user-1")
    loaded = memory.load("user-1")

    assert loaded["last_agent_result"] == payload
    assert loaded["agent_results"] == [payload]
    assert memory.load("another-user") == {}


def test_executor_injects_knowledge_updates_context_and_saves_memory() -> None:
    registry = AgentRegistry()
    registry.register(_ProbeAgent())
    context_manager = SharedContextManager()
    context = context_manager.create("explain the paper")
    memory = AgentMemoryAdapter()
    executor = AgentExecutor(
        registry=registry,
        context_manager=context_manager,
        knowledge_injector=KnowledgeInjector(_KnowledgeRuntime(), top_k=3),
        memory_adapter=memory,
    )

    results = executor.execute(
        [{"agent": "probe", "task": "inspect"}],
        context=context,
        user_id="user-1",
    )

    assert len(results) == 1
    assert results[0].output == "done:inspect"
    assert context.intermediate_results["probe"] == results[0]
    saved = memory.load("user-1")
    assert saved["last_agent_result"] == results[0]
