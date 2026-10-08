from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.models.agent_react import AgentReActDecision
from backend.models.agent_runtime import AgentPlanContext, AgentPlanStep, AgentRouteDecision
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.chat_session_service import ChatSessionService
from backend.services.filesystem_workspace_service import FilesystemWorkspaceService
from backend.services.product_agent_service import ProductAgentService
from backend.services.task_completion_verifier import apply_task_completion
from backend.services.tool_capability_router import requested_capabilities
from backend.services.workspace_file_service import WorkspaceFileError, WorkspaceFileService


@pytest.fixture
def files(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    workspaces = FilesystemWorkspaceService(tmp_path / "state" / "workspaces.sqlite3")
    workspace = workspaces.create(str(root))
    service = WorkspaceFileService(workspaces, tmp_path / "state" / "changes.sqlite3")
    registry = AgentToolRegistry(filesystem_workspace_service=workspaces, workspace_file_service=service)
    return root, workspace.workspace_id, service, registry


def invoke(registry, workspace_id, tool_name, **arguments):
    return registry.execute(tool_name, filesystem_workspace_id=workspace_id, filesystem_access="read_write", session_id="files", **arguments)


def request(workspace_id, tool_name, arguments, message="创建文件 a.md，内容为 abcd", **options):
    return dict(session_id="files", source_text="", user_message=message, filesystem_workspace_id=workspace_id,
                filesystem_access="read_write", execution_mode="react", _resolved_route=AgentRouteDecision(
                    kind="tool", source="planner", tool_name=tool_name, arguments=arguments), **options)


@pytest.mark.parametrize("body", ["abcd", "  abcd\r\n\r\n", "", "中文\t "])
def test_exact_creation_and_typed_readback(files, body):
    root, wid, service, registry = files
    arguments = registry.validate_planner_arguments("create_workspace_file", {"relative_path": "a.md", "content": body})
    assert arguments["content"] == body
    result = invoke(registry, wid, "create_workspace_file", **arguments)
    assert (root / "a.md").read_bytes() == body.encode()
    assert result.data["size_bytes"] == len(body.encode())
    verified = registry.verify_result("create_workspace_file", {"filesystem_workspace_id": wid, **arguments}, result)
    assert verified.verification["status"] == "passed"
    read = invoke(registry, wid, "read_workspace_text", relative_path="a.md")
    assert read.data["text"] == body
    assert service.changes(wid, "files")[0]["change_id"] == result.data["change_id"]


def test_existing_path_is_not_overwritten(files):
    root, wid, service, _ = files
    (root / "a.md").write_bytes(b"original")
    with pytest.raises(WorkspaceFileError, match="已存在"):
        service.apply(wid, "create", {"relative_path": "a.md", "content": "abcd"})
    assert (root / "a.md").read_bytes() == b"original"


@pytest.mark.parametrize("path", ["../a.md", "C:/a.md", "/a.md", "a.md:stream", "CON.md", "aux", "folder/../a.md", "a.md.", "a.md ", ".env", ".git/config", "a\x00.md", "folder//a.md"])
def test_paths_cannot_escape_or_alias(files, path):
    _, wid, service, _ = files
    with pytest.raises(WorkspaceFileError):
        service.apply(wid, "create", {"relative_path": path, "content": "abcd"})


def test_external_modification_blocks_edit_and_undo(files):
    root, wid, service, _ = files
    created = service.apply(wid, "create", {"relative_path": "a.md", "content": "abcd"})
    version = service.read(wid, "a.md")["sha256"]
    (root / "a.md").write_bytes(b"manual")
    with pytest.raises(WorkspaceFileError, match="变化"):
        service.apply(wid, "edit", {"relative_path": "a.md", "expected_sha256": version, "old_text": "abcd", "new_text": "xyz"})
    with pytest.raises(WorkspaceFileError, match="变化"):
        service.apply(wid, "undo", {"change_id": created["change_id"]})
    assert (root / "a.md").read_bytes() == b"manual"


def test_unique_edit_preserves_bom_newlines_and_can_undo_after_restart(files):
    root, wid, service, _ = files
    original = b"\xef\xbb\xbfline\r\n  abcd \r\n"
    (root / "a.md").write_bytes(original)
    arguments = {"relative_path": "a.md", "expected_sha256": service.read(wid, "a.md")["sha256"], "old_text": "  abcd ", "new_text": "  xyz "}
    preview = service.preview(wid, "edit", arguments)
    assert "abcd" in preview["diff"] and "xyz" in preview["diff"]
    edited = service.apply(wid, "edit", arguments, session_id="files")
    assert (root / "a.md").read_bytes() == original.replace(b"abcd", b"xyz")
    restored = WorkspaceFileService(service.workspaces, service.database_path)
    approval = restored.undo_preview(wid, "files", edited["change_id"])
    restored.undo_confirmed(wid, "files", approval["approval_token"])
    assert (root / "a.md").read_bytes() == original
    with pytest.raises(WorkspaceFileError):
        restored.undo_confirmed(wid, "files", approval["approval_token"])


def test_ambiguous_edit_aborts(files):
    root, wid, service, _ = files
    (root / "a.md").write_bytes(b"abcd abcd")
    with pytest.raises(WorkspaceFileError, match="不唯一"):
        service.apply(wid, "edit", {"relative_path": "a.md", "expected_sha256": service.read(wid, "a.md")["sha256"], "old_text": "abcd", "new_text": "xyz"})
    assert (root / "a.md").read_bytes() == b"abcd abcd"


def test_directory_creation_listing_and_nonempty_undo(files):
    root, wid, service, _ = files
    directory = service.apply(wid, "mkdir", {"relative_path": "reports"})
    service.apply(wid, "create", {"relative_path": "reports/a.md", "content": "abcd"})
    assert service.list(wid)["entries"][0]["kind"] == "directory"
    assert service.list(wid, "reports", "*.md")["entries"][0]["relative_path"] == "reports/a.md"
    assert service.search(wid, "abcd")["matches"][0]["line"] == 1
    with pytest.raises(WorkspaceFileError, match="非空"):
        service.apply(wid, "undo", {"change_id": directory["change_id"]})


def test_pending_write_is_never_replayed(files, monkeypatch):
    root, wid, service, _ = files
    arguments = {"relative_path": "a.md", "content": "abcd"}
    verify = service.verify
    monkeypatch.setattr(service, "verify", lambda *_: (_ for _ in ()).throw(OSError("readback unavailable")))
    with pytest.raises(OSError):
        service.apply(wid, "create", arguments, operation_key="call")
    assert (root / "a.md").read_bytes() == b"abcd"
    monkeypatch.setattr(service, "verify", verify)
    with pytest.raises(WorkspaceFileError, match="重放"):
        service.apply(wid, "create", arguments, operation_key="call")


def test_cross_instance_replay_returns_same_receipt(files):
    root, wid, service, _ = files
    arguments = {"relative_path": "a.md", "content": "abcd"}
    second = WorkspaceFileService(service.workspaces, service.database_path)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(item.apply, wid, "create", arguments, operation_key="same-call", session_id="files") for item in (service, second)]
        receipts = [future.result() for future in futures]
    assert receipts[0] == receipts[1]
    assert (root / "a.md").read_bytes() == b"abcd"
    assert len(service.changes(wid, "files")) == 1


def test_read_only_blocks_registry_and_import(files, tmp_path):
    root, wid, service, registry = files
    with pytest.raises(PermissionError):
        registry.execute("create_workspace_file", filesystem_workspace_id=wid, relative_path="a.md", content="abcd")
    assert registry.availability("create_workspace_file", payload={"filesystem_workspace_id": wid})[0] is False
    sessions = ChatSessionService(service.workspaces, tmp_path / "state" / "chat.sqlite3")
    sessions.update("files", filesystem_workspace_id=wid, filesystem_access="read_only")
    source = tmp_path / "in.md"
    source.write_text("text")
    with pytest.raises(ValueError, match="只读"):
        sessions.import_file("files", str(source))
    assert not (root / "a.md").exists()


@pytest.mark.parametrize("message", ["如何新建 a.md？", "你能创建文件吗？", "不要新建 a.md", "解释‘创建 a.md’", "查看文件，内容为 创建 a.md"])
def test_non_commands_do_not_authorize_writes(message):
    from backend.services.workspace_file_intent import explicit_new_file_request
    assert explicit_new_file_request(message, "a.md") is False


def test_local_save_and_download_are_distinct():
    from backend.services.markdown_export_service import wants_markdown_export
    assert "filesystem" in requested_capabilities("在这个文件夹保存为 a.md")
    assert not wants_markdown_export("在这个文件夹保存为 a.md")
    assert wants_markdown_export("导出 Markdown 给我下载")


def test_react_explicit_create_needs_no_second_confirmation(files):
    root, wid, _, registry = files
    product = ProductAgentService(registry=registry, chat_service=SimpleNamespace())
    result = product.run(**request(wid, "create_workspace_file", {"relative_path": "a.md", "content": "abcd"}))
    assert result.status == "completed"
    assert result.tool_result.verification["status"] == "passed"
    assert (root / "a.md").read_bytes() == b"abcd"


def test_overwrite_requires_confirmation(files):
    root, wid, service, registry = files
    (root / "a.md").write_bytes(b"abcd")
    arguments = {"relative_path": "a.md", "content": "xyz", "expected_sha256": service.read(wid, "a.md")["sha256"]}
    product = ProductAgentService(registry=registry, chat_service=SimpleNamespace())
    result = product.run(**request(wid, "write_workspace_file", arguments, message="把 a.md 改为 xyz"))
    assert result.status == "confirmation_required"
    assert (root / "a.md").read_bytes() == b"abcd"
    result = product.run(**request(wid, "write_workspace_file", arguments, message="把 a.md 改为 xyz", confirmed_write_tools=["write_workspace_file"]))
    assert result.tool_result.verification["status"] == "passed"
    assert (root / "a.md").read_bytes() == b"xyz"


def test_false_file_completion_claim_is_rejected():
    state = AgentState(session_id="files", user_input="创建 a.md 文件，内容为 abcd")
    state.apply_response({"status": "completed", "output_text": "已创建 a.md。"})
    assert apply_task_completion(state)["status"] != "completed"
    assert "已创建 a.md。" not in state.response["output_text"]


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_plan_waits_then_creates_or_cancels_exact_file(files, decision):
    root, wid, _, registry = files
    class Planner:
        def plan(self, **_):
            return AgentPlanContext(mode="multi_step", goal="新建 a.md", steps=[AgentPlanStep(step_id="step-1", tool_name="create_workspace_file", arguments={"relative_path": "a.md", "content": "abcd"})])
    product = ProductAgentService(registry=registry, chat_service=SimpleNamespace(), multi_step_planner=Planner())
    graph = ReadingAgentGraph(ProductAgentRuntimeAdapter(product), checkpointer=InMemorySaver())
    runtime = AgentRuntime(workflow_adapter=graph)
    state = AgentState(session_id="files", user_input="创建文件 a.md，内容为 abcd", browser_context={
        "execution_mode": "plan_execute", "context_mode": "general", "filesystem_workspace_id": wid, "filesystem_access": "read_write"})
    pending = runtime.execute(state)
    assert pending.response["status"] == "confirmation_required"
    assert not (root / "a.md").exists()
    assert pending.plan.steps[0].file_preview["size_after"] == 4
    checkpoint = runtime.restore_checkpoint(pending.run_id)
    checkpoint.browser_context["plan_confirmation_decision"] = {"decision": decision, "plan_hash": checkpoint.browser_context["pending_plan_confirmation"]["plan_hash"]}
    completed = runtime.execute(checkpoint, resume=True)
    assert completed.response["status"] == "completed"
    assert (root / "a.md").exists() == (decision == "approve")
    if decision == "approve":
        assert (root / "a.md").read_bytes() == b"abcd"
        assert completed.browser_context["task_completion"]["status"] == "completed"


def test_read_and_search_pagination_are_bounded(files):
    root, wid, service, _ = files
    (root / "a.md").write_bytes(b"match\r\nmatch\r\nmatch")
    first = service.read(wid, "a.md", max_lines=1)
    assert first["text"] == "match\r\n" and first["has_more"]
    assert service.read(wid, "a.md", first["next_line"], 2)["text"] == "match\r\nmatch"
    assert service.search(wid, "match", limit=1)["has_more"]
    assert service.search(wid, "match", offset=2, limit=1)["matches"][0]["line"] == 3


def test_live_session_readonly_is_checked_after_checkpoint_resume(files, monkeypatch, tmp_path):
    from backend.api import chat_sessions
    root, wid, service, registry = files
    sessions = ChatSessionService(service.workspaces, tmp_path / "state" / "sessions.sqlite3")
    sessions.update("files", filesystem_workspace_id=wid, filesystem_access="read_only")
    monkeypatch.setattr(chat_sessions, "get_chat_session_service", lambda: sessions)
    product = ProductAgentService(registry=registry, chat_service=SimpleNamespace())
    with pytest.raises(Exception, match="只读"):
        product.run(**request(wid, "create_workspace_file", {"relative_path": "a.md", "content": "abcd"}, chat_configuration=True))
    assert not (root / "a.md").exists()


def test_plan_edit_binds_version_and_reuses_exact_approval(files):
    root, wid, service, registry = files
    (root / "a.md").write_bytes(b"abcd")
    class Planner:
        def plan(self, **_):
            return AgentPlanContext(mode="multi_step", goal="编辑 a.md", steps=[AgentPlanStep(step_id="step-1", tool_name="edit_workspace_file", arguments={"relative_path": "a.md", "old_text": "abcd", "new_text": "xyz"})])
    product = ProductAgentService(registry=registry, chat_service=SimpleNamespace(), multi_step_planner=Planner())
    graph = ReadingAgentGraph(ProductAgentRuntimeAdapter(product), checkpointer=InMemorySaver())
    runtime = AgentRuntime(workflow_adapter=graph)
    state = AgentState(session_id="files", user_input="把文件 a.md 中的 abcd 改成 xyz", browser_context={
        "execution_mode": "plan_execute", "context_mode": "general", "filesystem_workspace_id": wid, "filesystem_access": "read_write"})
    pending = runtime.execute(state)
    assert (root / "a.md").read_bytes() == b"abcd"
    assert pending.plan.steps[0].arguments["expected_sha256"] == service.read(wid, "a.md")["sha256"]
    assert "xyz" in pending.plan.steps[0].file_preview["diff"]
    restored = runtime.restore_checkpoint(pending.run_id)
    restored.browser_context["plan_confirmation_decision"] = {"decision": "approve", "plan_hash": restored.browser_context["pending_plan_confirmation"]["plan_hash"]}
    completed = runtime.execute(restored, resume=True)
    assert completed.response["status"] == "completed"
    assert (root / "a.md").read_bytes() == b"xyz"


def test_hardlink_is_not_read_or_modified(files, tmp_path):
    import os
    root, wid, service, _ = files
    external = tmp_path / "external.md"
    external.write_bytes(b"outside")
    os.link(external, root / "linked.md")
    with pytest.raises(WorkspaceFileError, match="链接"):
        service.read(wid, "linked.md")
    assert not service.list(wid)["entries"]


def test_junction_cannot_escape_workspace(files, tmp_path):
    import os
    import subprocess
    if os.name != "nt":
        pytest.skip("Windows junction regression")
    root, wid, service, _ = files
    external = tmp_path / "external"
    external.mkdir()
    (external / "a.md").write_bytes(b"outside")
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "link"), str(external)], capture_output=True)
    assert result.returncode == 0
    with pytest.raises(WorkspaceFileError, match="链接"):
        service.read(wid, "link/a.md")
    assert not service.list(wid)["entries"]


def test_directory_only_does_not_complete_file_creation_request():
    state = AgentState(session_id="files", user_input="在这个文件夹新建 a.md 文件")
    state.record_tool_result({"tool_name": "create_workspace_directory", "effect": "write", "verification": {"status": "passed"}})
    state.apply_response({"status": "completed", "output_text": "已完成"})
    assert apply_task_completion(state)["status"] != "completed"


def test_directory_only_does_not_complete_directory_and_file_request():
    state = AgentState(session_id="files", user_input="创建目录 reports，然后新建 reports/a.md 文件")
    state.record_tool_result({"tool_name": "create_workspace_directory", "effect": "write", "verification": {"status": "passed"}})
    state.apply_response({"status": "completed", "output_text": "已完成"})
    assert apply_task_completion(state)["status"] != "completed"


def test_diff_of_text_without_final_newlines_is_readable(files):
    root, wid, service, _ = files
    (root / "a.md").write_bytes(b"abcd")
    preview = service.preview(wid, "edit", {"relative_path": "a.md", "expected_sha256": service.read(wid, "a.md")["sha256"],
                                          "old_text": "abcd", "new_text": "xyz"})
    assert "-abcd\n\\ No newline at end of file\n+xyz\n" in preview["diff"]
    assert (root / "a.md").read_bytes() == b"abcd"


@pytest.mark.parametrize("ranges, expected", [([(1, 2)], "partial"), ([(1, 2), (2, 4)], "completed"), ([(1, 2), (3, 4)], "partial")])
def test_full_raw_text_requires_contiguous_pages(ranges, expected):
    state = AgentState(session_id="files", user_input="读取工作区文件全文", browser_context={"filesystem_workspace_id": "workspace"})
    for start, next_line in ranges:
        state.record_tool_result({"tool_name": "read_workspace_text", "verification": {"status": "passed"},
                                 "data": {"relative_path": "a.md", "sha256": "version", "total_lines": 3, "start_line": start, "next_line": next_line}})
    state.apply_response({"status": "completed", "output_text": "全文已读取"})
    assert apply_task_completion(state)["status"] == expected


def test_text_whitespace_survives_configured_and_exposed_presets(files):
    from backend.services.tool_configuration import configured_model, metadata_definition
    _, _, _, registry = files
    definition = registry.get_definition("create_workspace_file")
    configured = metadata_definition(definition, {"defaults": {"content": "  abcd\r\n"}})
    assert configured.parse_args({"relative_path": "a.md"}).content == "  abcd\r\n"
    exposed = configured_model(definition, {}, ["relative_path", "content"])
    assert exposed.model_validate({"relative_path": "a.md", "content": "  abcd\r\n"}).content == "  abcd\r\n"


def test_plan_directory_and_file_share_one_confirmation(files):
    root, wid, _, registry = files
    class Planner:
        def plan(self, **_):
            return AgentPlanContext(mode="multi_step", goal="创建报告目录和文件", steps=[
                AgentPlanStep(step_id="step-1", tool_name="create_workspace_directory", arguments={"relative_path": "reports"}),
                AgentPlanStep(step_id="step-2", tool_name="create_workspace_file", arguments={"relative_path": "reports/a.md", "content": "abcd"}, depends_on=["step-1"]),
            ])
    product = ProductAgentService(registry=registry, chat_service=SimpleNamespace(), multi_step_planner=Planner())
    runtime = AgentRuntime(workflow_adapter=ReadingAgentGraph(ProductAgentRuntimeAdapter(product), checkpointer=InMemorySaver()))
    pending = runtime.execute(AgentState(session_id="files", user_input="创建目录 reports，然后新建 reports/a.md 文件，内容为 abcd", browser_context={
        "execution_mode": "plan_execute", "context_mode": "general", "filesystem_workspace_id": wid, "filesystem_access": "read_write"}))
    assert not (root / "reports").exists()
    restored = runtime.restore_checkpoint(pending.run_id)
    restored.browser_context["plan_confirmation_decision"] = {"decision": "approve", "plan_hash": restored.browser_context["pending_plan_confirmation"]["plan_hash"]}
    completed = runtime.execute(restored, resume=True)
    assert completed.response["status"] == "completed"
    assert (root / "reports/a.md").read_bytes() == b"abcd"


def test_approval_does_not_authorize_changed_tool_defaults(files):
    from backend.services.tool_configuration import metadata_definition
    from backend.services.workspace_file_service import preview_fingerprint
    root, wid, service, registry = files
    original = registry.get_definition("create_workspace_file")
    registry._definition_by_name["create_workspace_file"] = metadata_definition(original, {"defaults": {"content": "old"}})
    old_preview = service.preview(wid, "create", {"relative_path": "a.md", "content": "old"})
    approved = [{"tool_name": "create_workspace_file", "arguments": {"relative_path": "a.md"}, "workspace_id": wid,
                 "file_preview_hash": preview_fingerprint(old_preview)}]
    registry._definition_by_name["create_workspace_file"] = metadata_definition(original, {"defaults": {"content": "new"}})
    product = ProductAgentService(registry=registry, chat_service=SimpleNamespace())
    payload = request(wid, "create_workspace_file", {"relative_path": "a.md"}, approved_file_steps=approved)
    payload["execution_mode"] = "plan_execute"
    result = product.run(**payload)
    assert result.status == "confirmation_required"
    assert not (root / "a.md").exists()


@pytest.mark.parametrize("defaults_changed", [False, True])
def test_native_edit_confirmation_binds_preview_even_with_legacy_tool_approval(files, defaults_changed):
    from backend.agent_graph.root_agent_graph import RootAgentGraph
    from backend.agent_core.state import CURRENT_AGENT_GRAPH_VERSION
    from backend.services.tool_configuration import metadata_definition
    root, wid, service, registry = files
    (root / "a.md").write_bytes(b"abcd")
    original = registry.get_definition("edit_workspace_file")
    registry._definition_by_name["edit_workspace_file"] = metadata_definition(original, {"defaults": {"new_text": "xyz"}})
    arguments = {"relative_path": "a.md", "old_text": "abcd", "expected_sha256": service.read(wid, "a.md")["sha256"]}
    chat = SimpleNamespace(send=lambda **_: SimpleNamespace(output_text="done", provider="test", model="test", request_id=0))
    product = ProductAgentService(registry=registry, chat_service=chat)
    product.resolve_route = lambda **_: (AgentRouteDecision(kind="tool", source="deterministic", tool_name="edit_workspace_file", arguments=arguments), {})
    class Decisions:
        def decide(self, iteration, **_):
            if iteration == 1:
                return AgentReActDecision(iteration=iteration, kind="tool", tool_name="edit_workspace_file", arguments=arguments)
            return AgentReActDecision(iteration=iteration, kind="final", final_answer="已完成")
    runtime = AgentRuntime(workflow_adapter=RootAgentGraph(ProductAgentRuntimeAdapter(product), checkpointer=InMemorySaver(),
                                                          react_decision_service=Decisions(), graph_version=CURRENT_AGENT_GRAPH_VERSION, engine="native"))
    pending = runtime.execute(AgentState(session_id="files", user_input="修改文件 a.md", browser_context={
        "execution_mode": "react", "filesystem_workspace_id": wid, "filesystem_access": "read_write"}))
    assert pending.response["status"] == "confirmation_required"
    assert (root / "a.md").read_bytes() == b"abcd"
    restored = runtime.restore_checkpoint(pending.run_id)
    restored.browser_context["write_confirmation_decision"] = {**pending.browser_context["pending_write_confirmation"], "approved": True}
    restored.browser_context["confirmed_write_tools"] = ["edit_workspace_file"]
    if defaults_changed:
        registry._definition_by_name["edit_workspace_file"] = metadata_definition(original, {"defaults": {"new_text": "different"}})
        with pytest.raises(Exception, match="authorization"):
            runtime.execute(restored, resume=True)
        assert (root / "a.md").read_bytes() == b"abcd"
    else:
        completed = runtime.execute(restored, resume=True)
        assert completed.response["status"] == "completed"
        assert (root / "a.md").read_bytes() == b"xyz"
