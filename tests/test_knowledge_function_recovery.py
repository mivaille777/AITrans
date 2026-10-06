"""Fault-injection coverage for model arguments, full reading and persistent outcomes."""
from __future__ import annotations
import copy
import json
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app.ai.errors import AIAuthenticationError, AIResponseError
from app.ai.tool_calling import ToolCompletion
from backend.agent_core.exceptions import AgentCancelledError
from backend.api.dependencies import get_companion_chat_service, get_conversation_store_service
from backend.main import create_app
from backend.rag.models import DocumentChunk
from backend.services.conversation_grounding_service import load_message_grounding
from backend.services.conversation_store_service import ConversationStoreService
from backend.services.knowledge_function_recovery import parse_arguments
from test_knowledge_function_calling import resources, NativeClient, call, answer, search, service, send

FACT = "The controller uses a proportional gain of 2.5 to regulate water level [1]."


@pytest.fixture(autouse=True)
def isolate_unrelated_model_warmup(monkeypatch):
    # These transport tests inject the full retrieval boundary. Startup GPU/model
    # warmup would exercise the user's real library rather than this fixture.
    monkeypatch.setattr("backend.main.warm_existing_knowledge_runtime", lambda: None)


def batch(*calls):
    return ToolCompletion({"role": "assistant", "content": None, "tool_calls": [c.tool_calls[0] for c in calls]})


def trace_send(resources, responses, **kwargs):
    native = NativeClient(responses)
    prepared = []
    result = send(service(native, resources), prepared_callback=prepared.append, **kwargs)
    return result, native, prepared[-1].grounding.debug_metadata


def test_safe_json_fence_and_inherited_scope_defaults(resources):
    fenced = "\x60\x60\x60json\n" + json.dumps({"query": "water"}) + "\n\x60\x60\x60"
    result, native, meta = trace_send(resources, [
        call("search_knowledge_base", fenced), call("read_knowledge_chunk", {"chunk_id": "chunk-A"}, "read"), answer(FACT),
    ], knowledge_document_ids=("doc-A",))
    assert result.evidence and meta["function_calls"][0]["status"] == "success"
    assert resources[0].calls[0][1].document_ids == ["doc-A"]
    args, _ = parse_arguments("search_knowledge_base", fenced)
    assert args.top_k == 5 and args.document_ids == []


@pytest.mark.parametrize("args,path,actual", [
    ({"query": "private-query", "top_k": True}, "top_k", "bool"),
    ({"query": "private-query", "top_k": 99}, "top_k", "int"),
    ({"query": "private-query", "unknown": "private-value"}, "unknown", "str"),
    ({"document_ids": []}, "query", "missing"),
    ({"query": "x", "document_ids": "doc-A"}, "document_ids", "str"),
])
def test_field_feedback_is_strict_and_has_no_argument_values(args, path, actual):
    model, error = parse_arguments("search_knowledge_base", json.dumps(args))
    assert model is None
    assert any(f["path"] == path and f["actual_type"] == actual for f in error["fields"])
    assert "private-query" not in json.dumps(error) and "private-value" not in json.dumps(error)


def test_entire_invalid_batch_has_responses_and_costs_one_repair_round(resources):
    result, native, meta = trace_send(resources, [
        batch(call("search_knowledge_base", "{", "bad-json"), call("search_knowledge_base", {"query": "q", "top_k": True}, "bad-bool")),
        search("good-search"), call("read_knowledge_chunk", {"chunk_id": "chunk-A"}, "read"), answer(FACT),
    ], knowledge_document_ids=("doc-A",))
    errors = [m for m in native.calls[1]["messages"] if m["role"] == "tool"]
    assert {m["tool_call_id"] for m in errors} == {"bad-json", "bad-bool"}
    assert all(json.loads(m["content"])["error"]["remaining"]["tool_calls"] == 7 for m in errors)
    assert result.knowledge_recovery["repair_rounds"] == 1
    assert meta["function_calls"][-1]["budgets"]["executed"] == 2


def test_two_distinct_repair_rounds_then_success(resources):
    result, _, meta = trace_send(resources, [
        call("search_knowledge_base", "{", "bad-json"),
        call("search_knowledge_base", {"query": "x", "top_k": True}, "bad-type"),
        search("ok"), call("read_knowledge_chunk", {"chunk_id": "chunk-A"}, "read"), answer(FACT),
    ], knowledge_document_ids=("doc-A",))
    assert result.knowledge_recovery["repair_rounds"] == 2
    assert result.knowledge_recovery["outcome"] == "repaired"
    assert len(resources[0].calls) == 1


@pytest.mark.parametrize("query", ["请先完整阅读这篇文档", "请读取完整内容后回答", "Read the entire paper before answering"])
def test_explicit_full_read_intent_variants(query):
    from backend.services.knowledge_function_recovery import wants_full_read
    assert wants_full_read(query)


def test_unusable_general_model_response_does_not_load_library(resources):
    native = NativeClient([])
    def malformed(**kwargs):
        raise AIResponseError("Unusable general response")
    native.complete_tools = malformed
    chat = service(native, resources)
    chat._knowledge_tools_factory = lambda: pytest.fail("General response failure must not load RAG")
    result = chat.send(session_id="ordinary-failure", user_message="你好", context_mode="general")
    assert result.output_text and not result.evidence and not result.knowledge_retrieved



def test_third_distinct_bad_round_falls_back_with_original_query(resources):
    result, native, meta = trace_send(resources, [
        call("search_knowledge_base", "{", "bad-json"),
        call("search_knowledge_base", {"query": "different", "top_k": True}, "bad-type"),
        call("unknown_tool", {}, "bad-name"), answer(FACT),
    ], knowledge_document_ids=("doc-A",))
    assert result.knowledge_recovery["repair_rounds"] == 2
    assert result.knowledge_recovery["outcome"] == "fallback"
    assert resources[0].calls[0][0] == "What does the paper say?"
    assert all(e.source_id == "doc-A" for e in result.evidence)
    assert native.calls[-1]["tools"] == [] and native.calls[-1]["tool_choice"] == "none"


def test_runtime_value_error_is_service_failure_without_repair(resources):
    resources[0].error = ValueError("server invariant, not model arguments")
    result, native, meta = trace_send(resources, [search(), answer("Cannot verify")])
    assert meta["function_calls"][0]["status"] == "tool_unavailable"
    assert result.knowledge_recovery["repair_rounds"] == 0
    assert "无法" in result.output_text
    error = next(m for m in native.calls[-1]["messages"] if m["role"] == "tool")
    assert json.loads(error["content"])["error"]["code"] == "tool_unavailable"


def test_successful_repeat_is_cached_not_executed_again(resources):
    result, native, meta = trace_send(resources, [
        search(), call("read_knowledge_chunk", {"chunk_id": "chunk-A"}, "read-1"),
        call("read_knowledge_chunk", {"chunk_id": "chunk-A"}, "read-2"), answer(FACT),
    ])
    assert [c["status"] for c in meta["function_calls"]] == ["success", "success", "repeated_call"]
    assert meta["function_calls"][-1]["budgets"]["reads"] == 1
    assert result.knowledge_recovery["repair_rounds"] == 0


def test_batch_execution_budget_is_checked_between_calls(resources):
    resources[0].chunks.clear()
    result, native, meta = trace_send(resources, [
        batch(search("s1", query="one"), search("s2", query="two"), search("s3", query="three")),
    ])
    assert len(resources[0].calls) == 2
    assert [c["status"] for c in meta["function_calls"]] == ["success", "success", "budget_exhausted"]
    assert result.output_text and not result.evidence


def test_provider_failure_after_read_reuses_source_owned_evidence(resources):
    native = NativeClient([search(), call("read_knowledge_chunk", {"chunk_id": "chunk-A"}, "read")])
    original = native.complete_tools
    def provider(**kwargs):
        if not native.responses:
            raise AIResponseError("Bad provider response")
        return original(**kwargs)
    native.complete_tools = provider
    result = send(service(native, resources), knowledge_document_ids=("doc-A",))
    assert result.output_text and "[1]" in result.output_text
    assert len(resources[0].calls) == 1 and result.evidence


def full_resources(resources, *, count=3, length=100):
    retrieval, _, tools = resources
    chunks = []
    for index in range(count):
        text = f"FULL-TEXT-{index} " + "The controller uses a proportional gain of 2.5 to regulate water level. " * max(1, length // 70)
        chunks.append(DocumentChunk(
            chunk_id=f"full-{index}", document_id="doc-A", text=text, title="Paper A",
            chunk_index=index, start_char=index * len(text), end_char=(index + 1) * len(text),
            source_uri="https://example.org/A", page_number=index + 1,
        ))
    retrieval.chunks.update({c.chunk_id: c for c in chunks})
    snapshots = []
    def snapshot(document_id, *, generation_id=None):
        assert document_id == "doc-A"
        assert generation_id in {None, "generation-1"}
        snapshots.append(generation_id)
        return "generation-1", copy.deepcopy(chunks)
    retrieval.snapshot_document_chunks = snapshot
    return chunks, snapshots


def full_send(resources, responses, **kwargs):
    native = NativeClient(responses)
    result = service(native, resources).send(
        session_id="full", user_message="请读取全文之后回答：控制器的增益是多少？",
        context_mode="general", knowledge_document_ids=("doc-A",), **kwargs,
    )
    return result, native


def test_full_document_sends_every_chunk_in_order_before_synthesis(resources):
    chunks, snapshots = full_resources(resources, count=4, length=6000)
    result, native = full_send(resources, [answer(FACT)] * 5)
    full = result.knowledge_recovery["full_read"]
    assert full["complete"] and full["processed_chunks"] == 4
    batch_prompts = [c["messages"][-1]["content"] for c in native.calls[:-1]]
    assert all(chunk.text in "\n".join(batch_prompts) for chunk in chunks)
    assert [p.index("FULL-TEXT-") for p in batch_prompts]
    assert snapshots == [None, "generation-1", "generation-1"]
    assert "全部可用正文" in result.output_text
    assert all(c["tools"] == [] and c["tool_choice"] == "none" for c in native.calls)


def test_full_read_budget_reports_partial_without_false_completion(resources, monkeypatch):
    from backend.services import knowledge_function_recovery as recovery
    monkeypatch.setattr(recovery, "MAX_FULL_BATCHES", 1)
    chunks, _ = full_resources(resources, count=3, length=6500)
    result, native = full_send(resources, [answer(FACT), answer(FACT)])
    assert not result.knowledge_recovery["full_read"]["complete"]
    assert result.knowledge_recovery["outcome"] == "partial"
    assert result.knowledge_recovery["full_read"]["processed_chunks"] == 1
    assert "尚未完成" in result.output_text


def test_full_read_version_change_drops_stale_citations(resources):
    chunks, _ = full_resources(resources, count=1)
    def changed(document_id, *, generation_id=None):
        if generation_id is not None:
            raise LookupError("publication changed")
        return "generation-1", chunks
    resources[0].snapshot_document_chunks = changed
    result, _ = full_send(resources, [answer(FACT)])
    assert not result.evidence and not result.citations
    assert not result.knowledge_recovery["full_read"]["complete"]
    assert "尚未完成" in result.output_text


def test_full_read_change_during_final_synthesis_drops_stale_citations(resources):
    chunks, _ = full_resources(resources, count=1)
    calls = []
    def changed(document_id, *, generation_id=None):
        calls.append(generation_id)
        if len(calls) == 3:
            raise LookupError("changed during final synthesis")
        return "generation-1", chunks
    resources[0].snapshot_document_chunks = changed
    result, _ = full_send(resources, [answer(FACT), answer(FACT)])
    assert not result.evidence and not result.citations
    assert not result.knowledge_recovery["full_read"]["complete"]


def test_full_read_never_policy_does_not_load_tools(resources):
    native = NativeClient([])
    chat = service(native, resources)
    chat._knowledge_tools_factory = lambda: pytest.fail("NEVER must not initialize knowledge")
    result = chat.send(session_id="never", user_message="请读取全文", knowledge_access_policy="never")
    assert not native.calls and not result.evidence
    assert result.knowledge_recovery["reason"] == "policy_never"


def test_ambiguous_full_document_request_asks_for_selection(resources):
    native = NativeClient([])
    result = service(native, resources).send(session_id="ambiguous", user_message="阅读全文后回答", context_mode="general")
    assert "选择" in result.output_text and not native.calls
    assert result.knowledge_recovery["reason"] == "document_selection_required"
    assert not resources[0].calls


def test_cancel_after_full_batch_prevents_next_batch_and_release(resources):
    full_resources(resources, count=3, length=6500)
    event = Event()
    native = NativeClient([answer(FACT)])
    original = native.complete_tools
    def cancel(**kwargs):
        result = original(**kwargs)
        event.set()
        return result
    native.complete_tools = cancel
    with pytest.raises(AgentCancelledError):
        list(service(native, resources).run_functions(
            session_id="cancel", user_message="读取全文", context_mode="general",
            knowledge_document_ids=("doc-A",), cancel_event=event, stream=False,
        ))
    assert len(native.calls) == 1


def test_stream_failure_persists_nonempty_error_and_replays(resources, tmp_path, monkeypatch):
    from backend.api import companion_stream
    monkeypatch.setattr(companion_stream, "get_rag_debug_service", lambda: None)
    native = NativeClient([])
    def fail(**kwargs):
        raise AIAuthenticationError("secret-provider-detail")
    native.complete_tools = fail
    chat = service(native, resources)
    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    app = create_app()
    app.dependency_overrides[get_companion_chat_service] = lambda: chat
    app.dependency_overrides[get_conversation_store_service] = lambda: store
    with TestClient(app) as client:
        with client.websocket_connect("/ws/companion/chat") as ws:
            ws.send_json({"type": "start", "request": {"session_id": "error", "user_message": "你好", "request_id": 77, "context_mode": "general"}})
            events = []
            while not events or events[-1]["type"] not in {"error", "done", "cancelled"}:
                events.append(ws.receive_json())
        final = events[-1]
        assert final["type"] == "error" and final["code"] == "authentication"
        assert final["output_text"] and "secret" not in final["output_text"]
        assert sum(e["type"] in {"error", "done", "cancelled"} for e in events) == 1
        detail = client.get("/api/conversations/" + final["conversation_id"]).json()
        assert detail["messages"][-1]["content"] == final["output_text"]


def test_stream_recovery_outcome_and_evidence_survive_replay(resources, tmp_path, monkeypatch):
    from backend.api import companion_stream
    monkeypatch.setattr(companion_stream, "get_rag_debug_service", lambda: None)
    native = NativeClient([call("unknown_tool", {}, "one"), call("unknown_tool", {}, "two"), answer(FACT)])
    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    app = create_app()
    app.dependency_overrides[get_companion_chat_service] = lambda: service(native, resources)
    app.dependency_overrides[get_conversation_store_service] = lambda: store
    with TestClient(app) as client:
        with client.websocket_connect("/ws/companion/chat") as ws:
            ws.send_json({"type": "start", "request": {"session_id": "recover", "user_message": "What does the paper say?", "request_id": 78, "knowledge_document_ids": ["doc-A"], "context_mode": "general"}})
            events = []
            while not events or events[-1]["type"] not in {"error", "done", "cancelled"}:
                events.append(ws.receive_json())
        final = events[-1]
        assert final["type"] == "done", final
        assert any(e.get("phase") == "recovering" for e in events)
        assert final["knowledge_recovery"]["outcome"] == "fallback"
        saved = load_message_grounding(store.storage_path, final["message_id"])
        assert saved.knowledge_recovery == final["knowledge_recovery"] and saved.citations
        detail = client.get("/api/conversations/" + final["conversation_id"]).json()
        assert detail["messages"][-1]["knowledge_recovery"] == final["knowledge_recovery"]


def test_full_snapshot_uses_published_ids_and_rejects_missing_stale_or_forged_text(tmp_path):
    from types import SimpleNamespace
    from backend.rag.index_manifest import IndexManifest, IndexManifestRecord
    from backend.rag.retrieval_service import RetrievalService
    from backend.rag.exceptions import RagRetrievalError
    manifest = IndexManifest(tmp_path / "manifest.json")
    chunk = DocumentChunk(chunk_id="active", document_id="doc-A", text="source-owned",
                          chunk_index=0, source_uri="local://doc-A", document_hash="hash-A",
                          metadata={"index_generation": "generation-1"})
    record = IndexManifestRecord(document_id="doc-A", chunk_ids=["active"], content_hash="hash-A")
    manifest.begin_generation("doc-A", "generation-1", ["active"])
    manifest.validate_generation("doc-A", "generation-1", ["active"])
    manifest.publish_generation("doc-A", "generation-1", manifest_record=record)
    items = {"active": chunk, "retired": chunk.model_copy(update={"chunk_id": "retired", "metadata": {"index_generation": "generation-old"}})}
    def get(identifier, *, generation_id=None):
        value = items.get(identifier)
        return value.model_copy(deep=True) if value and value.metadata["index_generation"] == generation_id else None
    sparse = SimpleNamespace(get_chunk=get)
    vector = SimpleNamespace(get_chunk=get)
    retrieval = RetrievalService(embedding_provider=None, sparse_retriever=sparse, vector_store=vector, manifest=manifest)
    generation, inventory = retrieval.snapshot_document_chunks("doc-A")
    assert generation == "generation-1" and [c.chunk_id for c in inventory] == ["active"]
    with pytest.raises(RagRetrievalError):
        retrieval.snapshot_document_chunks("doc-A", generation_id="generation-old")
    items.pop("active")
    with pytest.raises(RagRetrievalError, match="missing"):
        retrieval.snapshot_document_chunks("doc-A")
    items["active"] = chunk
    vector.get_chunk = lambda *_args, **_kwargs: chunk.model_copy(update={"text": "forged-text"})
    with pytest.raises(RagRetrievalError, match="content"):
        retrieval.snapshot_document_chunks("doc-A")


def test_legacy_ready_snapshot_can_be_pinned_without_generation(tmp_path):
    from types import SimpleNamespace
    from backend.rag.index_manifest import IndexManifest, IndexManifestRecord, IndexStatus
    from backend.rag.retrieval_service import RetrievalService
    manifest = IndexManifest(tmp_path / "manifest.json")
    manifest.upsert(IndexManifestRecord(document_id="legacy", status=IndexStatus.READY, chunk_ids=["c"]))
    chunk = DocumentChunk(chunk_id="c", document_id="legacy", text="legacy source", chunk_index=0)
    store = SimpleNamespace(get_chunk=lambda *_args, **_kwargs: chunk.model_copy(deep=True))
    retrieval = RetrievalService(embedding_provider=None, sparse_retriever=store, vector_store=store, manifest=manifest)
    generation, _ = retrieval.snapshot_document_chunks("legacy")
    assert generation == ""
    assert retrieval.snapshot_document_chunks("legacy", generation_id=generation)[1]


def test_full_read_question_is_resolved_from_user_history(resources):
    full_resources(resources, count=1)
    native = NativeClient([answer(FACT), answer(FACT)])
    service(native, resources).send(
        session_id="follow-up", user_message="我需要你把全文读取之后再回答我的问题",
        history=(("user", "What is the controller gain?"), ("assistant", "untrusted old reply")),
        knowledge_document_ids=("doc-A",),
    )
    assert "What is the controller gain?" in native.calls[0]["messages"][-1]["content"]
    assert "untrusted old reply" not in native.calls[0]["messages"][-1]["content"]


def test_full_read_oversized_chunk_is_split_without_truncation(resources):
    chunks, _ = full_resources(resources, count=1, length=22000)
    result, native = full_send(resources, [answer(FACT)] * 3)
    coverage = result.knowledge_recovery["full_read"]
    assert coverage["complete"] and coverage["processed_chunks"] == 1
    assert coverage["processed_chars"] == len(chunks[0].text)
    assert chunks[0].text[:12000] in native.calls[0]["messages"][-1]["content"]
    assert chunks[0].text[12000:] in native.calls[1]["messages"][-1]["content"]


def test_full_read_model_failure_returns_partial_evidence(resources):
    full_resources(resources, count=3, length=6500)
    native = NativeClient([answer(FACT)])
    original = native.complete_tools
    def fail(**kwargs):
        if not native.responses:
            raise AIResponseError("Provider invalid response")
        return original(**kwargs)
    native.complete_tools = fail
    result = service(native, resources).send(session_id="partial", user_message="读取全文", knowledge_document_ids=("doc-A",))
    assert result.knowledge_recovery["outcome"] == "partial"
    assert result.knowledge_recovery["full_read"]["processed_chunks"] == 1
    assert result.evidence and result.citations and "尚未完成" in result.output_text


def test_fallback_deadline_releases_only_existing_evidence(resources, monkeypatch):
    from backend.services import knowledge_function_recovery as recovery
    from backend.agent_core.exceptions import AgentBudgetExceededError
    original = recovery.run_node_operation_with_timeout
    def bounded(operation, **kwargs):
        if kwargs["stage"] == "knowledge_fallback_synthesis":
            raise AgentBudgetExceededError("No remaining time")
        return original(operation, **kwargs)
    monkeypatch.setattr(recovery, "run_node_operation_with_timeout", bounded)
    result, _, _ = trace_send(resources, [
        search(), call("unknown_tool", {}, "one"), call("unknown_tool", {}, "two"),
    ], knowledge_document_ids=("doc-A",))
    assert result.evidence and result.output_text
    assert len(resources[0].calls) == 1
