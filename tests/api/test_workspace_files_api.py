import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import agent, chat_sessions
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.chat_session_service import ChatSessionService
from backend.services.filesystem_workspace_service import FilesystemWorkspaceService
from backend.services.workspace_file_service import WorkspaceFileService


@pytest.fixture
def api(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    workspaces = FilesystemWorkspaceService(tmp_path / "state" / "workspaces.sqlite3")
    wid = workspaces.create(str(root)).workspace_id
    sessions = ChatSessionService(workspaces, tmp_path / "state" / "sessions.sqlite3")
    sessions.update("session", filesystem_workspace_id=wid)
    files = WorkspaceFileService(workspaces, tmp_path / "state" / "changes.sqlite3")
    monkeypatch.setattr(chat_sessions, "get_workspace_file_service", lambda: files)
    monkeypatch.setattr(agent, "get_chat_session_service", lambda: sessions)
    app = FastAPI()
    app.include_router(chat_sessions.router)
    app.include_router(agent.router)
    app.dependency_overrides[chat_sessions.get_chat_session_service] = lambda: sessions
    app.dependency_overrides[agent.get_agent_tool_registry] = lambda: AgentToolRegistry(
        filesystem_workspace_service=workspaces, workspace_file_service=files)
    with TestClient(app) as client:
        yield client, root, files, wid, sessions


def test_browse_preview_location_and_undo_roundtrip(api):
    client, root, files, wid, _ = api
    change = files.apply(wid, "create", {"relative_path": "a.md", "content": "abcd"}, session_id="session")
    base = "/api/companion/sessions/session/workspace"
    assert client.get(base).json()["display_path"] == str(root)
    assert client.get(base).json()["entries"][0]["size_bytes"] == 4
    assert client.get(base + "/text", params={"relative_path": "a.md"}).json()["text"] == "abcd"
    assert client.get(base + "/location", params={"relative_path": "a.md"}).json()["resource_url"] == (root / "a.md").as_uri()
    assert client.get(base + "/changes").json()[0]["change_id"] == change["change_id"]
    preview = client.post(base + "/undo/preview", json={"change_id": change["change_id"]})
    assert preview.status_code == 200
    assert (root / "a.md").exists()
    token = preview.json()["approval_token"]
    assert client.post(base + "/undo/apply", json={"approval_token": token}).status_code == 200
    assert not (root / "a.md").exists()
    assert client.post(base + "/undo/apply", json={"approval_token": token}).status_code == 409


def test_read_only_and_pending_plan_block_mutations(api):
    client, root, files, wid, sessions = api
    change = files.apply(wid, "create", {"relative_path": "a.md", "content": "abcd"}, session_id="session")
    base = "/api/companion/sessions/session"
    assert client.patch(base, json={"filesystem_access": "read_only"}).status_code == 200
    assert client.get(base + "/workspace/text", params={"relative_path": "a.md"}).status_code == 200
    assert client.post(base + "/workspace/undo/preview", json={"change_id": change["change_id"]}).status_code == 409
    assert client.patch(base, json={"filesystem_access": "read_write"}).status_code == 200
    preview = client.post(base + "/workspace/undo/preview", json={"change_id": change["change_id"]}).json()
    sessions.set_pending_run("session", "pending-plan")
    assert client.patch(base, json={"filesystem_access": "read_only"}).status_code == 409
    assert client.post(base + "/workspace/undo/apply", json={"approval_token": preview["approval_token"]}).status_code == 409
    assert (root / "a.md").read_bytes() == b"abcd"


def test_tool_menu_uses_server_session_workspace_and_access(api):
    client, _, _, _, sessions = api
    params = {"session_id": "session", "has_reading_context": False,
              "filesystem_workspace_id": "untrusted-client-workspace"}
    def catalog():
        response = client.get("/api/agent/tools", params=params)
        assert response.status_code == 200
        return {item["name"]: item for item in response.json()["tools"]}
    assert catalog()["create_workspace_file"]["available"] is True
    sessions.update("session", filesystem_access="read_only")
    assert catalog()["create_workspace_file"]["available"] is False
    assert catalog()["read_workspace_text"]["available"] is True


def test_undo_token_is_bound_to_session_workspace_and_file_version(api, tmp_path):
    client, root, files, wid, sessions = api
    change = files.apply(wid, "create", {"relative_path": "a.md", "content": "abcd"}, session_id="session")
    base = "/api/companion/sessions/session/workspace"
    token = client.post(base + "/undo/preview", json={"change_id": change["change_id"]}).json()["approval_token"]
    sessions.update("other-session", filesystem_workspace_id=wid)
    assert client.post("/api/companion/sessions/other-session/workspace/undo/apply", json={"approval_token": token}).status_code == 409
    (root / "a.md").write_bytes(b"external edit")
    assert client.post(base + "/undo/apply", json={"approval_token": token}).status_code == 409
    assert (root / "a.md").read_bytes() == b"external edit"


@pytest.mark.parametrize("path", ["../outside.md", "C:/outside.md", ".env", "a.md:stream"])
def test_api_preview_and_location_enforce_workspace_scope(api, path):
    client, _, _, _, _ = api
    base = "/api/companion/sessions/session/workspace"
    assert client.get(base + "/text", params={"relative_path": path}).status_code == 409
    assert client.get(base + "/location", params={"relative_path": path}).status_code == 409
