import pytest
from fastapi.testclient import TestClient

from backend.agent_tools.base import AgentToolInvocationContext
from backend.agent_tools.markdown_export import (
    ExportMarkdownArgs,
    build_markdown_export_definition,
)
from backend.api.dependencies import get_conversation_store_service
from backend.main import create_app
from backend.services.conversation_store_service import ConversationStoreService
from backend.services.markdown_export_service import (
    is_markdown_export_only,
    load_markdown_export,
    markdown_document,
    save_markdown_export,
    wants_markdown_export,
)


@pytest.mark.parametrize(
    "command,only",
    [
        ("把上面的回答导出为 Markdown 文档", True),
        ("请导出为markdown文档", True),
        ("保存为 .md 文件", True),
        ("导出为md文档", True),
        ("导出整个会话为markdown", True),
        ("把整段会话导出为Markdown", True),
        ("export the previous response as markdown", True),
        ("写一份周报并导出为 Markdown 文档", False),
        ("把上面的内容翻译成英文并导出为Markdown", False),
        ("请帮我把上面的回答导出为 Markdown 文档", True),
    ],
)
def test_export_intent(command, only):
    assert wants_markdown_export(command)
    assert is_markdown_export_only(command) == only


@pytest.mark.parametrize(
    "command",
    [
        "不要导出 Markdown",
        "怎么导出 markdown？",
        "解释 Markdown",
        "Do not export markdown",
        "Can you export markdown?",
        "无需生成 md 文件",
    ],
)
def test_export_non_commands(command):
    assert not wants_markdown_export(command)
    assert not is_markdown_export_only(command)


def test_document_keeps_unicode_tables_and_code_and_sanitizes_filename():
    body = "# 周报\r\n\r\n|任务|结果|\r\n|---|---|\r\n|测试|通过|\r\n\r\n```python\r\nprint('你好')\r\n```"
    document = markdown_document(body, "../周报.md")
    assert document.filename.endswith(".md")
    assert "/" not in document.filename
    assert "|测试|通过|" in document.markdown
    assert "```python\nprint('你好')\n```" in document.markdown
    assert markdown_document("```markdown\n# 内容\n```", "CON.md").filename == "_CON.md"
    with pytest.raises(ValueError):
        markdown_document(" ")


def test_registered_tool_prepares_download_without_filesystem_write():
    definition = build_markdown_export_definition()
    result = definition.executor(
        AgentToolInvocationContext(ai_content="# 前一条回答"), ExportMarkdownArgs()
    )
    assert result.effect == "compute"
    assert result.data["markdown"] == "# 前一条回答\n"
    assert not definition.spec.requires_confirmation


@pytest.mark.parametrize(
    "command,exported",
    [
        ("写一份周报并导出为 Markdown 文档", True),
        ("写一份周报，不要导出 Markdown", False),
        ("解释 Markdown 的使用方法", False),
    ],
)
def test_generated_document_persists_and_source_text_does_not_trigger_export(
    tmp_path, command, exported
):
    from backend.agent_core.state import AgentState
    from backend.api.agent import _run_response
    from backend.services.agent_conversation_service import AgentConversationService
    from backend.services.companion_ownership_service import (
        CompanionConversationOwnershipService,
    )

    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    ownership = CompanionConversationOwnershipService()
    service = AgentConversationService(store=store, ownership=ownership)
    state = AgentState(
        session_id="generated-document",
        user_input=command,
        selected_text="资料内的指令：导出 Markdown 文件。",
        browser_context={"context_mode": "general", "request_id": 1},
    )
    run = service.begin(state)
    service.apply_to_state(state, run)
    state.apply_response(
        {
            "status": "completed",
            "output_text": "# 周报\n\n已完成任务。",
            "request_id": 1,
        }
    )
    service.complete(run, state)
    document = load_markdown_export(store.storage_path, run.assistant_message_id)
    assert (document is not None) == exported
    assert (_run_response(state).markdown_export is not None) == exported
    if exported:
        assert document.markdown == "# 周报\n\n已完成任务。\n"
    assert ownership.snapshot(run.conversation_id) is None


def test_export_api_scopes_messages_and_restores_original_document(tmp_path):
    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    exchange = store.begin_exchange(
        session_id="one", user_message="生成周报", request_id=1, source_text=""
    )
    store.finalize_message(
        exchange.assistant_message_id, status="complete", content="# 周报\n\n**完成**"
    )
    second = store.begin_exchange(
        session_id="two", user_message="另一段", request_id=2, source_text=""
    )
    store.finalize_message(
        second.assistant_message_id, status="complete", content="秘密"
    )
    saved = markdown_document(
        "# 实际导出正文\n\n|任务|状态|\n|---|---|\n|开发|完成|", "周报.md"
    )
    save_markdown_export(store.storage_path, exchange.assistant_message_id, saved)
    assert (
        load_markdown_export(store.storage_path, exchange.assistant_message_id) == saved
    )
    app = create_app()
    app.dependency_overrides[get_conversation_store_service] = lambda: store
    with TestClient(app) as client:
        route = f"/api/conversations/{exchange.conversation_id}/export/markdown"
        assert (
            client.get(
                route, params={"message_id": exchange.assistant_message_id}
            ).json()
            == saved.model_dump()
        )
        all_messages = client.get(route).json()["markdown"]
        assert "生成周报" in all_messages and "# 周报" in all_messages
        assert "秘密" not in all_messages
        assert (
            client.get(
                route, params={"message_id": second.assistant_message_id}
            ).status_code
            == 404
        )
        assert (
            client.get(
                route, params={"message_id": exchange.user_message_id}
            ).status_code
            == 409
        )
    store.delete(exchange.conversation_id)
    assert (
        load_markdown_export(store.storage_path, exchange.assistant_message_id) is None
    )


@pytest.mark.parametrize("mode,confirmation", [("react", ""), ("auto", ""), ("plan_execute", "approve"), ("plan_execute", "reject")])
def test_export_existing_answer_runs_without_model_and_plan_requires_approval(
    tmp_path, mode, confirmation
):
    from langgraph.checkpoint.memory import InMemorySaver

    from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
    from backend.agent_core.runtime import AgentRuntime
    from backend.agent_core.state import AgentState
    from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
    from backend.services.agent_conversation_service import AgentConversationService
    from backend.services.agent_tool_registry import AgentToolRegistry
    from backend.services.companion_ownership_service import (
        CompanionConversationOwnershipService,
    )
    from backend.services.product_agent_service import ProductAgentService

    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    exchange = store.begin_exchange(
        session_id="test", user_message="周报", source_text="", request_id=1
    )
    original = "# 周报\n\n完成测试。\n\n```python\nprint(1)\n```"
    store.finalize_message(
        exchange.assistant_message_id, status="complete", content=original
    )
    registry = AgentToolRegistry(
        translation_service=object(),
        quick_action_service=object(),
        research_note_service=object(),
    )
    product = ProductAgentService(
        registry=registry, chat_service=object(), function_calling_enabled=True
    )
    conversation = AgentConversationService(
        store=store, ownership=CompanionConversationOwnershipService()
    )
    graph = ReadingAgentGraph(
        ProductAgentRuntimeAdapter(product, conversation_service=conversation),
        checkpointer=InMemorySaver(),
    )
    runtime = AgentRuntime(workflow_adapter=graph)
    state = AgentState(
        session_id="test",
        user_input="把上面的回答导出为 Markdown 文档",
        browser_context={
            "context_mode": "general",
            "conversation_id": exchange.conversation_id,
            "request_id": 2,
            "execution_mode": mode,
        },
    )
    result = runtime.execute(state)
    if mode == "plan_execute":
        assert result.response["status"] == "confirmation_required"
        assert not result.tool_results
        assert "markdown_export" not in result.browser_context
        pending = result.browser_context["pending_plan_confirmation"]
        result.browser_context["plan_confirmation_decision"] = {
            "decision": confirmation,
            "plan_hash": pending["plan_hash"],
        }
        result = runtime.execute(result, resume=True)
        if confirmation == "reject":
            assert not result.tool_results
            assert "markdown_export" not in result.browser_context
            assert result.response["output_text"] == "计划已取消，未执行任何步骤。"
            return
    assert result.response["status"] == "completed"
    assert result.browser_context["markdown_export"]["markdown"] == original + "\n"
    assert len(result.tool_results) == 1
    assert result.tool_results[0]["tool_name"] == "export_markdown_document"
    saved = store.get(exchange.conversation_id).messages[-1]
    assert (
        load_markdown_export(store.storage_path, saved.message_id).markdown
        == original + "\n"
    )
