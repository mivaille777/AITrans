from __future__ import annotations

import copy
import json
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from app.ai.client import DeepSeekClient
from app.ai.errors import AIResponseError, AITimeoutError
from app.ai.openai_compatible import OpenAICompatibleClient
from app.ai.tool_calling import ToolCompletion
from backend.agent_core.exceptions import AgentCancelledError, AgentToolTimeoutError
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.state import AgentState
from backend.agent_tools.knowledge import KnowledgeAgentTools
from backend.api.dependencies import (
    get_companion_chat_service,
    get_conversation_store_service,
)
from backend.main import create_app
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.services.agent_react_decision_service import AgentReActDecisionService
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.companion_chat_service import CompanionChatService
from backend.services.conversation_grounding_service import load_message_grounding
from backend.services.conversation_store_service import ConversationStoreService
from backend.services.product_agent_service import ProductAgentService


def call(name, args, identifier="call-1", content=None):
    return ToolCompletion(
        {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": identifier,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": args
                        if isinstance(args, str)
                        else json.dumps(args),
                    },
                }
            ],
        }
    )


def answer(text="Hello."):
    return ToolCompletion({"role": "assistant", "content": text})


class NativeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, **kwargs):
        raise AssertionError("Native decisions must not use the legacy JSON protocol")

    def complete_tools(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return self.responses.pop(0)

    def stream_tools(self, **kwargs):
        response = self.complete_tools(**kwargs)
        if response.content:
            yield response.content[:10]
            yield response.content[10:]
        yield response


class Retrieval:
    def __init__(self, chunks, *, error=None):
        self.chunks = {item.chunk_id: item for item in chunks}
        self.calls = []
        self.error = error

    def retrieve(self, query, *, filters=None, **kwargs):
        self.calls.append((query, filters, kwargs))
        if self.error:
            raise self.error
        return RetrievalResult(
            query=query,
            retrieval_strategy="hybrid",
            candidates=[
                RetrievalCandidate(chunk=item, rank=index + 1)
                for index, item in enumerate(self.chunks.values())
                if filters is None
                or not filters.document_ids
                or item.document_id in filters.document_ids
            ],
        )

    def get_chunk(self, chunk_id):
        return self.chunks.get(chunk_id)

    def section_neighbors(self, anchor, radius):
        return [anchor]


@pytest.fixture
def resources():
    text = "The controller uses a proportional gain of 2.5 to regulate water level."
    chunks = [
        DocumentChunk(
            chunk_id=f"chunk-{doc}",
            document_id=f"doc-{doc}",
            text=text,
            title=f"Paper {doc}",
            section_heading="Method",
            section_path=["Method"],
            chunk_index=0,
            start_char=0,
            end_char=len(text),
            source_uri=f"https://example.org/{doc}",
        )
        for doc in ("A", "B")
    ]
    retrieval = Retrieval(chunks)
    records = [
        SimpleNamespace(
            document_id=item.document_id,
            title=item.title,
            source_uri=item.source_uri,
            status="ready",
            chunk_ids=[item.chunk_id],
        )
        for item in chunks
    ]
    library = SimpleNamespace(list_documents=lambda: records)
    tools = KnowledgeAgentTools(
        retrieval_service=retrieval,
        chunk_store=retrieval,
        jit_search_read_enabled=True,
        library_service=library,
    )
    return retrieval, library, tools


def service(client, resources):
    _, library, tools = resources
    text = SimpleNamespace(
        provider=SimpleNamespace(client=client),
        provider_name="fake",
        model="fake-model",
    )
    return CompanionChatService(
        text_service=text,
        function_calling_enabled=True,
        knowledge_library_service=library,
        knowledge_tools_factory=lambda: tools,
    )


def send(chat, **kwargs):
    return chat.send(
        session_id="test",
        user_message="What does the paper say?",
        context_mode="general",
        **kwargs,
    )


def search(identifier="search-1", ids=None, **kwargs):
    return call(
        "search_knowledge_base",
        {
            "query": "water controller gain",
            "document_ids": ids or [],
            "top_k": 5,
            **kwargs,
        },
        identifier,
    )


@pytest.mark.parametrize(
    "question", ["你好", "什么是比例控制", "翻译这段话", "继续解释上一条"]
)
def test_auto_llm_can_answer_without_loading_knowledge(resources, question):
    native = NativeClient([answer()])
    chat = service(native, resources)
    chat._knowledge_tools_factory = lambda: pytest.fail(
        "Ordinary answers must not initialize RAG"
    )
    result = chat.send(session_id="test", user_message=question, context_mode="general")
    assert result.output_text == "Hello."
    assert not result.knowledge_retrieved
    assert native.calls[0]["tool_choice"] == "auto"
    names = {item["function"]["name"] for item in native.calls[0]["tools"]}
    assert names == {
        "search_knowledge_base",
        "list_knowledge_documents",
        "read_knowledge_chunk",
        "read_knowledge_section",
    }


def test_catalog_uses_manifest_and_native_tool_result(resources):
    native = NativeClient(
        [call("list_knowledge_documents", {}, "catalog"), answer("Paper A、Paper B。")]
    )
    result = send(service(native, resources))
    assert "Paper A" in result.output_text
    assert not resources[0].calls
    assert not result.knowledge_retrieved
    assert result.knowledge_document_count == 2
    messages = native.calls[1]["messages"]
    assert messages[-2]["tool_calls"][0]["id"] == "catalog"
    assert messages[-1]["role"] == "tool" and messages[-1]["tool_call_id"] == "catalog"
    assert json.loads(messages[-1]["content"])["data"]["total"] == 2


def test_search_read_preserves_scope_citations_and_replay(resources):
    native = NativeClient(
        [
            search(),
            call("read_knowledge_chunk", {"chunk_id": "chunk-A"}, "read"),
            answer(
                "The controller uses a proportional gain of 2.5 to regulate water level [1]."
            ),
        ]
    )
    result = send(service(native, resources), knowledge_document_ids=("doc-A",))
    assert result.knowledge_retrieved and result.knowledge_chunk_count == 1
    assert result.evidence[0].source_id == "doc-A"
    assert result.citations[0].evidence_ids == ["evidence:chunk-A"]
    assert resources[0].calls[0][1].document_ids == ["doc-A"]
    search_data = json.loads(native.calls[1]["messages"][-1]["content"])["data"]
    assert search_data["evidence"] == [] and "snippet" in search_data["results"][0]
    read_data = json.loads(native.calls[2]["messages"][-1]["content"])["data"]
    assert "[1]" in read_data["available_evidence"]
    assert native.calls[1]["tool_choice"] == "required"
    assert {item["function"]["name"] for item in native.calls[1]["tools"]} == {
        "read_knowledge_chunk", "read_knowledge_section"
    }


def test_found_search_candidates_cannot_be_released_without_read(resources):
    native = NativeClient([search(), answer("The gain is 2.5 [1].")])
    with pytest.raises(AIResponseError, match="evidence Read"):
        send(service(native, resources))


def test_multiple_reads_use_stable_distinct_citation_labels(resources):
    native = NativeClient(
        [
            search(),
            ToolCompletion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        call(
                            "read_knowledge_chunk", {"chunk_id": "chunk-A"}, "a"
                        ).tool_calls[0],
                        call(
                            "read_knowledge_chunk", {"chunk_id": "chunk-B"}, "b"
                        ).tool_calls[0],
                    ],
                }
            ),
            answer(
                "The controller uses a proportional gain of 2.5 to regulate water level [1][2]."
            ),
        ]
    )
    result = send(service(native, resources))
    assert [item.label for item in result.citations] == ["[1]", "[2]"]
    assert (
        "[2]"
        in json.loads(native.calls[-1]["messages"][-1]["content"])["data"][
            "available_evidence"
        ]
    )


@pytest.mark.parametrize(
    "bad",
    [
        call("unknown_tool", {}),
        call("search_knowledge_base", "{broken"),
        call("search_knowledge_base", {"query": "x", "document_ids": [], "top_k": 99}),
        call(
            "search_knowledge_base", {"query": "x", "document_ids": [], "top_k": True}
        ),
        call(
            "search_knowledge_base",
            {"query": "x", "document_ids": [], "top_k": 5, "trace_id": "spoof"},
        ),
    ],
)
def test_invalid_arguments_get_one_structured_repair_without_execution(resources, bad):
    native = NativeClient([bad, answer("Cannot perform that call.")])
    send(service(native, resources))
    assert not resources[0].calls
    assert (
        json.loads(native.calls[-1]["messages"][-1]["content"])["error"]["code"]
        == "invalid_arguments"
    )


def test_second_invalid_call_fails_explicitly(resources):
    native = NativeClient(
        [call("unknown_tool", {}, "one"), call("unknown_tool", {}, "two")]
    )
    with pytest.raises(AIResponseError, match="one repair"):
        send(service(native, resources))


def test_always_keeps_required_choice_during_argument_repair(resources):
    native = NativeClient(
        [
            call("unknown_tool", {}, "invalid"),
            call("list_knowledge_documents", {}, "catalog"),
            answer(),
        ]
    )
    send(service(native, resources), knowledge_access_policy="always")
    assert [request["tool_choice"] for request in native.calls] == [
        "required",
        "required",
        "auto",
    ]


def test_loop_deadline_is_reported_as_a_stable_ai_timeout(resources, monkeypatch):
    from backend.agent_core.exceptions import AgentBudgetExceededError
    from backend.services import companion_chat_service

    def deadline(**kwargs):
        raise AgentBudgetExceededError("deadline exceeded")

    monkeypatch.setattr(companion_chat_service, "run_knowledge_functions", deadline)
    with pytest.raises(AITimeoutError, match="execution deadline"):
        send(service(NativeClient([]), resources))


@pytest.mark.parametrize(
    "bad",
    [search(ids=["doc-B"]), call("read_knowledge_chunk", {"chunk_id": "chunk-A"})],
)
def test_out_of_scope_or_unlocated_read_is_denied(resources, bad):
    native = NativeClient([bad, answer("Access denied.")])
    send(service(native, resources), knowledge_document_ids=("doc-A",))
    assert not resources[0].calls
    assert (
        json.loads(native.calls[-1]["messages"][-1]["content"])["error"]["code"]
        == "scope_denied"
    )


@pytest.mark.parametrize(
    "policy, choice, has_tools",
    [("never", "auto", False), ("always", "required", True)],
)
def test_user_policy_controls_tool_availability(resources, policy, choice, has_tools):
    native = NativeClient(
        [call("list_knowledge_documents", {}, "catalog"), answer()]
        if policy == "always"
        else [answer()]
    )
    send(service(native, resources), knowledge_access_policy=policy)
    assert native.calls[0]["tool_choice"] == choice
    assert bool(native.calls[0]["tools"]) is has_tools


def test_service_fault_is_not_reported_as_no_match(resources):
    resources[0].error = RuntimeError("backend unavailable")
    native = NativeClient([search(), answer("Knowledge service is unavailable.")])
    result = send(service(native, resources))
    assert result.knowledge_fallback_reason.startswith("tool_unavailable")
    assert (
        json.loads(native.calls[-1]["messages"][-1]["content"])["error"]["code"]
        == "tool_unavailable"
    )


def test_search_budget_filters_third_search(resources):
    resources[0].chunks.clear()
    native = NativeClient(
        [search(), search("search-2", query="different water gain"), answer()]
    )
    send(service(native, resources))
    assert len(resources[0].calls) == 2
    assert "search_knowledge_base" not in {
        item["function"]["name"] for item in native.calls[-1]["tools"]
    }


def test_timeout_is_explicit_and_does_not_dispatch_late_tools(resources, monkeypatch):
    from backend.services import knowledge_function_calling

    def timed_out(*args, **kwargs):
        raise AgentToolTimeoutError("tool exceeded deadline")

    monkeypatch.setattr(
        knowledge_function_calling, "run_safe_tool_with_timeout", timed_out
    )
    native = NativeClient([search(), answer("Local knowledge request timed out.")])
    result = send(service(native, resources))
    assert "访问超时" in result.output_text
    assert result.knowledge_fallback_reason.startswith("tool_timeout")
    assert (
        json.loads(native.calls[-1]["messages"][-1]["content"])["error"]["code"]
        == "tool_timeout"
    )


def test_no_match_is_distinct_from_service_failure(resources):
    resources[0].chunks.clear()
    native = NativeClient([search(), answer("No usable evidence.")])
    result = send(service(native, resources))
    data = json.loads(native.calls[-1]["messages"][-1]["content"])
    assert data["ok"] and data["data"]["results"] == []
    assert result.knowledge_fallback_reason.startswith("no_evidence")


def test_catalog_ids_allow_model_to_narrow_global_search(resources):
    native = NativeClient(
        [
            call("list_knowledge_documents", {}, "catalog"),
            search(ids=["doc-B"]),
            call(
                "read_knowledge_section",
                {"chunk_id": "chunk-B", "neighbor_radius": 0},
                "read",
            ),
            answer(
                "The controller uses a proportional gain of 2.5 to regulate water level [1]."
            ),
        ]
    )
    result = send(service(native, resources))
    assert resources[0].calls[0][1].document_ids == ["doc-B"]
    assert result.evidence[0].source_id == "doc-B"


def test_agent_native_replays_call_ids_and_located_candidates(resources):
    native = NativeClient(
        [search(), call("read_knowledge_chunk", {"chunk_id": "chunk-A"}, "read-1")]
    )
    text = SimpleNamespace(provider=SimpleNamespace(client=native))
    registry = AgentToolRegistry(
        retrieval_service=resources[0],
        chunk_store=resources[0],
        jit_search_read_enabled=True,
        knowledge_library_service=resources[1],
    )
    decisions = AgentReActDecisionService(text_service=text)
    first = decisions.decide(
        iteration=1,
        tools=registry.list_tools(),
        user_message="Local paper?",
        knowledge_document_ids=["doc-A"],
    )
    result = registry.execute(
        first.tool_name, **first.arguments, knowledge_document_ids=["doc-A"]
    )
    second = decisions.decide(
        iteration=2,
        tools=registry.list_tools(),
        user_message="Local paper?",
        knowledge_document_ids=["doc-A"],
        native_decisions=(first,),
        native_results=({"step_id": "react-1", "data": result.data},),
    )
    assert second.tool_name == "read_knowledge_chunk"
    assert native.calls[-1]["tool_choice"] == "required"
    assert {item["function"]["name"] for item in native.calls[-1]["tools"]} == {
        "read_knowledge_chunk", "read_knowledge_section"
    }
    messages = native.calls[-1]["messages"]
    assert (
        messages[-2]["tool_calls"][0]["id"]
        == messages[-1]["tool_call_id"]
        == "search-1"
    )


def test_native_agent_general_answer_runs_through_the_compiled_graph(resources):
    from backend.agent_core.runtime import AgentRuntime
    from backend.agent_graph.reading_agent_graph import ReadingAgentGraph

    native = NativeClient([answer("Hello from native Agent.")])
    text = SimpleNamespace(
        provider=SimpleNamespace(client=native), provider_name="fake", model="fake"
    )
    registry = AgentToolRegistry(
        retrieval_service=resources[0],
        chunk_store=resources[0],
        jit_search_read_enabled=True,
        knowledge_library_service=resources[1],
    )
    product = ProductAgentService(
        registry=registry,
        chat_service=service(native, resources),
        function_calling_enabled=True,
    )
    workflow = ReadingAgentGraph(
        adapter=ProductAgentRuntimeAdapter(product),
        react_decision_service=AgentReActDecisionService(text_service=text),
    )
    result = AgentRuntime(workflow_adapter=workflow).execute(
        AgentState(
            user_input="你好",
            browser_context={
                "user_message": "你好",
                "context_mode": "general",
                "knowledge_access_policy": "auto",
            },
        )
    )
    assert result.response_state.output_text == "Hello from native Agent."
    assert not result.tool_calls


def test_provider_complete_preserves_tool_only_assistant_response():
    response = ChatCompletion.model_validate(
        {
            "id": "response",
            "object": "chat.completion",
            "created": 0,
            "model": "fake",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": call("list_knowledge_documents", {}, "catalog").message,
                }
            ],
        }
    )
    sdk = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: response)
        )
    )
    result = DeepSeekClient(sdk_client=sdk).complete_tools(
        messages=[{"role": "user", "content": "test"}], tools=[]
    )
    assert result.content == "" and result.tool_calls[0]["id"] == "catalog"


@pytest.mark.parametrize("typed_orchestration", [False, True])
@pytest.mark.parametrize("engine", ["compat", "native"])
def test_native_agent_search_read_and_verified_synthesis_through_compiled_graph(
    resources, typed_orchestration, engine,
):
    from backend.agent_core.runtime import AgentRuntime
    from backend.agent_graph.reading_agent_graph import ReadingAgentGraph

    body = "The controller uses a proportional gain of 2.5 to regulate water level [1]."
    native = NativeClient(
        [
            search(),
            call("read_knowledge_chunk", {"chunk_id": "chunk-A"}, "read"),
            answer(body),
        ]
    )
    text = SimpleNamespace(
        provider=SimpleNamespace(client=native), provider_name="fake", model="fake"
    )

    class SynthesisChat:
        prompt_id = "synthesis-test"

        def execute(self, request):
            assert "[1]" in request.tool_context
            return SimpleNamespace(
                session_id=request.session_id,
                user_message=request.user_message,
                output_text=body,
                provider="fake",
                model="fake",
                request_id=request.request_id,
            )

    synthesis = CompanionChatService(chat_service=SynthesisChat())
    registry = AgentToolRegistry(
        retrieval_service=resources[0],
        chunk_store=resources[0],
        jit_search_read_enabled=True,
        knowledge_library_service=resources[1],
    )
    product = ProductAgentService(
        registry=registry, chat_service=synthesis, function_calling_enabled=True
    )
    workflow = ReadingAgentGraph(
        adapter=ProductAgentRuntimeAdapter(product),
        react_decision_service=AgentReActDecisionService(text_service=text),
        engine=engine,
    )
    if typed_orchestration:
        from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge

        def legacy_route(*_args, **_kwargs):
            raise AssertionError("Default native question must reach function calling")
        workflow._orchestration_service = SimpleNamespace(route=legacy_route)
        workflow._collaboration_adapter = MultiAgentRuntimeBridge(
            orchestrator=workflow._orchestration_service
        )
    runtime = AgentRuntime(workflow_adapter=workflow)
    result = runtime.execute(
        AgentState(
            user_input="What is the gain in the local paper?",
            browser_context={
                "user_message": "What is the gain in the local paper?",
                "context_mode": "general",
                "knowledge_document_ids": ["doc-A"],
                "knowledge_access_policy": "auto",
            },
        )
    )
    assert result.response_state.output_text == body
    assert [item["name"] for item in result.tool_calls] == [
        "search_knowledge_base",
        "read_knowledge_chunk",
    ]
    assert result.evidence[0].source_id == "doc-A"
    assert result.knowledge_decision.should_retrieve
    assert resources[0].calls[0][1].document_ids == ["doc-A"]
    events = [
        event.payload
        for event in runtime.events
        if event.event_type.value == "grounding_verification_evaluated"
    ]
    assert events and events[-1]["passed"]


def test_native_agent_failed_search_cannot_release_fabricated_citations(resources):
    from backend.agent_core.runtime import AgentRuntime
    from backend.agent_graph.reading_agent_graph import ReadingAgentGraph

    resources[0].error = RuntimeError("retrieval service is unavailable")
    fabricated = (
        "The undocumented gain is 999 and the experiment achieved perfect control [1]."
    )
    native = NativeClient([search(), answer(fabricated)])
    text = SimpleNamespace(
        provider=SimpleNamespace(client=native), provider_name="fake", model="fake"
    )
    registry = AgentToolRegistry(
        retrieval_service=resources[0],
        chunk_store=resources[0],
        jit_search_read_enabled=True,
        knowledge_library_service=resources[1],
    )
    product = ProductAgentService(
        registry=registry,
        chat_service=service(native, resources),
        function_calling_enabled=True,
    )
    workflow = ReadingAgentGraph(
        adapter=ProductAgentRuntimeAdapter(product),
        react_decision_service=AgentReActDecisionService(text_service=text),
    )
    result = AgentRuntime(workflow_adapter=workflow).execute(
        AgentState(
            user_input="What is the gain in the local paper?",
            browser_context={
                "context_mode": "general",
                "knowledge_document_ids": ["doc-A"],
                "knowledge_access_policy": "auto",
            },
        )
    )
    assert result.response_state.output_text != fabricated
    assert "无法可靠回答" in result.response_state.output_text
    assert not result.evidence and not result.citations


def test_cancellation_prevents_model_or_tool_dispatch(resources):
    event = Event()
    event.set()
    native = NativeClient([search()])
    with pytest.raises(AgentCancelledError):
        list(
            service(native, resources).run_functions(
                session_id="test",
                user_message="x",
                context_mode="general",
                cancel_event=event,
            )
        )
    assert not native.calls and not resources[0].calls


def test_cancelled_tool_status_reaches_prepared_callback(resources, monkeypatch):
    from backend.services import knowledge_function_calling

    def cancelled(*_args, **_kwargs):
        raise AgentCancelledError("Cancelled while searching")

    monkeypatch.setattr(
        knowledge_function_calling, "run_safe_tool_with_timeout", cancelled
    )
    prepared = []
    with pytest.raises(AgentCancelledError):
        send(
            service(NativeClient([search()]), resources),
            prepared_callback=prepared.append,
        )
    calls = prepared[-1].grounding.debug_metadata["function_calls"]
    assert calls[-1]["tool_call_id"] == "search-1"
    assert calls[-1]["status"] == "cancelled"


@pytest.mark.parametrize("transport", ["http", "websocket"])
def test_tool_trace_survives_later_model_failure(
    resources, tmp_path, monkeypatch, transport
):
    from backend.api import companion, companion_stream

    recorded = []

    def record_route(**kwargs):
        recorded.append(copy.deepcopy(kwargs))
        return "trace-native-failure"

    debug = SimpleNamespace(
        record_companion_route=record_route,
        record_companion_event=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(companion, "get_rag_debug_service", lambda: debug)
    monkeypatch.setattr(companion_stream, "get_rag_debug_service", lambda: debug)
    native = NativeClient([search()])
    original = native.complete_tools

    def failed_after_search(**kwargs):
        if not native.responses:
            raise AIResponseError("Model unavailable after search")
        return original(**kwargs)

    native.complete_tools = failed_after_search
    chat = service(native, resources)
    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    app = create_app()
    app.dependency_overrides[get_companion_chat_service] = lambda: chat
    app.dependency_overrides[get_conversation_store_service] = lambda: store
    payload = {
        "session_id": "test",
        "user_message": "Find the water controller gain",
        "context_mode": "general",
        "knowledge_document_ids": ["doc-A"],
        "request_id": 104,
    }
    with TestClient(app) as client:
        if transport == "http":
            assert client.post("/api/companion/chat", json=payload).status_code == 502
        else:
            with client.websocket_connect("/ws/companion/chat") as ws:
                ws.send_json({"type": "start", "request": payload})
                event = {}
                while event.get("type") not in {"done", "error"}:
                    event = ws.receive_json()
            assert event["type"] == "error"
    calls = recorded[-1]["retrieval"]["function_calls"]
    assert calls[-1]["tool_name"] == "search_knowledge_base"
    assert calls[-1]["status"] == "success"


def test_native_http_and_websocket_share_verified_evidence(
    resources, tmp_path, monkeypatch
):
    from backend.api import companion, companion_stream

    monkeypatch.setattr(companion, "get_rag_debug_service", lambda: None)
    monkeypatch.setattr(companion_stream, "get_rag_debug_service", lambda: None)
    response_text = (
        "The controller uses a proportional gain of 2.5 to regulate water level [1]."
    )
    native = NativeClient(
        [
            search(),
            call("read_knowledge_chunk", {"chunk_id": "chunk-A"}, "read"),
            answer(response_text),
        ]
        * 2
    )
    chat = service(native, resources)
    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    app = create_app()
    app.dependency_overrides[get_companion_chat_service] = lambda: chat
    app.dependency_overrides[get_conversation_store_service] = lambda: store
    payload = {
        "session_id": "test",
        "user_message": "What is the controller gain?",
        "context_mode": "general",
        "knowledge_document_ids": ["doc-A"],
        "request_id": 101,
    }
    with TestClient(app) as client:
        http = client.post("/api/companion/chat", json=payload)
        assert http.status_code == 200, http.text
        assert http.json()["output_text"] == response_text
        payload["request_id"] = 102
        with client.websocket_connect("/ws/companion/chat") as ws:
            ws.send_json({"type": "start", "request": payload})
            events = []
            while not events or events[-1]["type"] not in {"done", "error"}:
                events.append(ws.receive_json())
        done = events[-1]
        assert done["type"] == "done", done
        assert done["output_text"] == response_text
        assert done["grounding_verification"]["passed"]
        assert done["citations"] == http.json()["citations"]
        assert load_message_grounding(store.storage_path, done["message_id"]).citations


def test_agent_native_decision_and_adapter_do_not_rule_veto_auto(resources):
    native = NativeClient([search()])
    text = SimpleNamespace(
        provider=SimpleNamespace(client=native), provider_name="fake", model="fake"
    )
    registry = AgentToolRegistry(
        retrieval_service=resources[0],
        chunk_store=resources[0],
        jit_search_read_enabled=True,
        knowledge_library_service=resources[1],
    )
    product = ProductAgentService(
        registry=registry,
        chat_service=service(native, resources),
        function_calling_enabled=True,
    )
    state = AgentState(
        browser_context={
            "user_message": "这个方案有哪些实验结果？",
            "context_mode": "general",
            "explicit_knowledge_document_ids": ["doc-A"],
            "knowledge_access_policy": "auto",
        }
    )
    adapter = ProductAgentRuntimeAdapter(product)
    route, _ = adapter.resolve_route(state)
    assert route.kind == "complex" and route.intent == "native_function_calling"
    tools = adapter.registered_tools(state)
    assert "search_knowledge_base" in {tool.name for tool in tools}
    decision = AgentReActDecisionService(text_service=text).decide(
        iteration=1,
        tools=tools,
        user_message="这个方案有哪些实验结果？",
        knowledge_document_ids=["doc-A"],
        source_text="",
    )
    assert decision.native_tool_call_id == "search-1"
    assert decision.arguments["top_k"] == 5


def completion_event(delta, finish=None):
    return ChatCompletionChunk.model_validate(
        {
            "id": "response",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "fake",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
    )


@pytest.mark.parametrize("client_type", [DeepSeekClient, OpenAICompatibleClient])
def test_provider_assembles_stream_arguments_before_returning_tool_call(client_type):
    events = [
        completion_event(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "search_knowledge_base",
                            "arguments": '{"query":',
                        },
                    }
                ],
            }
        ),
        completion_event(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "function": {
                            "arguments": '"water","document_ids":[],"top_k":5}'
                        },
                    }
                ]
            }
        ),
        completion_event({}, "tool_calls"),
    ]
    closed = []

    class Stream:
        def __iter__(self):
            return iter(events)

        def close(self):
            closed.append(True)

    sdk = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: Stream())
        )
    )
    wrapper = (
        client_type(sdk_client=sdk)
        if client_type is DeepSeekClient
        else client_type(
            model="fake", base_url="https://example.org/v1", sdk_client=sdk
        )
    )
    parts = list(
        wrapper.stream_tools(messages=[{"role": "user", "content": "test"}], tools=[])
    )
    assert len(parts) == 1 and isinstance(parts[0], ToolCompletion)
    assert json.loads(parts[0].tool_calls[0]["function"]["arguments"])["top_k"] == 5
    assert closed == [True]


def test_incomplete_stream_never_yields_an_executable_tool_call():
    sdk = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: iter(
                    [
                        completion_event(
                            {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "c1",
                                        "type": "function",
                                        "function": {
                                            "name": "search_knowledge_base",
                                            "arguments": "{",
                                        },
                                    }
                                ]
                            }
                        )
                    ]
                )
            )
        )
    )
    with pytest.raises(AIResponseError, match="did not finish"):
        list(
            DeepSeekClient(sdk_client=sdk).stream_tools(
                messages=[{"role": "user", "content": "test"}], tools=[]
            )
        )
