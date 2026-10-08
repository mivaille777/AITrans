import pytest

from backend.services.chat_session_service import ChatSessionService
from backend.services.filesystem_workspace_service import FilesystemWorkspaceService


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    workspaces = FilesystemWorkspaceService(tmp_path / "workspaces.sqlite3")
    workspace = workspaces.create(str(root))
    service = ChatSessionService(workspaces, tmp_path / "chat.sqlite3")
    service.update("session-1", filesystem_workspace_id=workspace.workspace_id)
    return service, root, tmp_path


def test_import_is_local_to_session_and_persisted(setup):
    service, root, tmp_path = setup
    source = tmp_path / "paper.md"
    source.write_text("# Results\nAn imported local finding", encoding="utf-8")
    config = service.import_file("session-1", str(source))
    assert len(config.attachments) == 1
    imported = root / config.attachments[0].relative_path
    assert imported.read_bytes() == source.read_bytes()
    restored = ChatSessionService(service.workspaces, service.database_path)
    assert "An imported local finding" in restored.context("session-1")[1]
    assert restored.context("session-2")[1] == ""
    service.detach("session-1", config.attachments[0].attachment_id)
    assert service.context("session-1")[1] == ""
    assert imported.exists()


def test_plan_freezes_scope_and_switching_drops_old_file_references(setup):
    service, root, tmp_path = setup
    source = tmp_path / "file.txt"
    source.write_text("session evidence", encoding="utf-8")
    service.import_file("session-1", str(source))
    service.set_pending_run("session-1", "run-1")
    with pytest.raises(ValueError):
        service.update("session-1", filesystem_workspace_id="")
    with pytest.raises(ValueError):
        service.import_file("session-1", str(source))
    service.set_pending_run("session-1", "")
    service.update("session-1", filesystem_workspace_id="")
    assert service.get("session-1").attachments == []
    assert list((root / "AITrans Chat Imports").iterdir())


def test_import_requires_workspace_and_does_not_overwrite(setup):
    service, root, tmp_path = setup
    source = tmp_path / "file.txt"
    source.write_text("a", encoding="utf-8")
    with pytest.raises(ValueError):
        service.import_file("unscoped", str(source))
    service.import_file("session-1", str(source))
    service.import_file("session-1", str(source))
    assert len(list((root / "AITrans Chat Imports").iterdir())) == 2


def test_workspace_read_paginates_and_rejects_escape(setup):
    service, root, tmp_path = setup
    (root / "large.txt").write_text("abcdefghij", encoding="utf-8")
    workspace_id = service.get("session-1").filesystem_workspace_id
    result = service.read_file(workspace_id, "large.txt", 3, 4)
    assert result["text"] == "defg"
    assert result["next_offset"] == 7
    assert result["has_more"] is True
    assert service.read_file(workspace_id, "large.txt", 7, 4)["has_more"] is False
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    with pytest.raises(ValueError, match="工作区"):
        service.read_file(workspace_id, "../outside.txt", 0, 100)
