from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.skills import get_skill_service, router
from backend.services.skill_service import (
    MAX_FILE_BYTES,
    SkillError,
    SkillService,
    parse_manifest,
)


@pytest.fixture
def service(tmp_path):
    return SkillService(tmp_path / "library")


@pytest.fixture
def client(service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_skill_service] = lambda: service
    return TestClient(app)


def test_api_lifecycle_preserves_files_and_state(client, service):
    result = client.post(
        "/api/skills",
        json={"name": "paper-review", "description": "审阅学术论文，提取论点和证据。"},
    )
    assert result.status_code == 201
    skill = result.json()
    assert skill["valid"] and not skill["enabled"]
    assert skill["files"] == [{"path": "SKILL.md", "size": skill["files"][0]["size"]}]
    manifest = client.get(
        "/api/skills/paper-review/file", params={"path": "SKILL.md"}
    ).json()
    assert manifest["language"] == "markdown"
    assert "审阅学术论文" in manifest["content"]
    update = client.put(
        "/api/skills/paper-review/file",
        json={
            "path": "references/guide.md",
            "content": "# 参考\n\n证据",
            "revision": None,
        },
    )
    assert update.status_code == 200
    assert client.patch("/api/skills/paper-review", json={"enabled": True}).json()[
        "enabled"
    ]
    assert SkillService(service.root).detail("paper-review").enabled
    listing = client.get("/api/skills").json()
    assert listing["skills"][0]["file_count"] == 2
    assert "files" not in listing["skills"][0]
    removed = client.delete("/api/skills/paper-review").json()
    assert removed["removed"]
    assert (Path(removed["archived_path"]) / "references" / "guide.md").read_text(
        encoding="utf-8"
    ) == "# 参考\n\n证据"
    assert client.get("/api/skills").json()["skills"] == []
    assert client.get("/api/skills/paper-review").status_code == 404
    assert not client.post(
        "/api/skills", json={"name": "paper-review", "description": "新版本"}
    ).json()["enabled"]


def test_invalid_draft_deactivates_until_explicit_enable(client):
    client.post("/api/skills", json={"name": "sample", "description": "test"})
    client.patch("/api/skills/sample", json={"enabled": True})
    file = client.get("/api/skills/sample/file", params={"path": "SKILL.md"}).json()
    draft = client.put(
        "/api/skills/sample/file",
        json={
            "path": "SKILL.md",
            "content": "# unfinished",
            "revision": file["revision"],
        },
    )
    assert draft.status_code == 200
    record = client.get("/api/skills/sample").json()
    assert not record["valid"] and not record["enabled"] and record["diagnostics"]
    assert client.patch("/api/skills/sample", json={"enabled": True}).status_code == 409
    repaired = client.put(
        "/api/skills/sample/file",
        json={
            "path": "SKILL.md",
            "content": file["content"],
            "revision": draft.json()["revision"],
        },
    )
    assert repaired.status_code == 200
    record = client.get("/api/skills/sample").json()
    assert record["valid"] and not record["enabled"]


def test_stale_write_and_delete_do_not_overwrite_external_changes(service):
    service.create("sample", "test")
    original = service.write_file("sample", "references/a.md", "original", None)
    (service.root / "sample" / "references" / "a.md").write_text(
        "external", encoding="utf-8"
    )
    with pytest.raises(SkillError) as error:
        service.write_file("sample", "references/a.md", "edited", original.revision)
    assert error.value.status == 409
    with pytest.raises(SkillError):
        service.delete_file("sample", "references/a.md", original.revision)
    assert service.read_file("sample", "references/a.md").content == "external"
    current = service.read_file("sample", "references/a.md")
    service.delete_file("sample", "references/a.md", current.revision)
    with pytest.raises(SkillError) as error:
        service.write_file("sample", "references/a.md", "edited", current.revision)
    assert error.value.status == 409


def test_create_only_and_protected_entrypoint(client):
    client.post("/api/skills", json={"name": "sample", "description": "test"})
    current = client.get("/api/skills/sample/file", params={"path": "SKILL.md"}).json()
    assert (
        client.put(
            "/api/skills/sample/file", json={"path": "SKILL.md", "content": "overwrite"}
        ).status_code
        == 409
    )
    assert (
        client.delete(
            "/api/skills/sample/file",
            params={"path": "SKILL.md", "revision": current["revision"]},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/skills", json={"name": "sample", "description": "test"}
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "path",
    [
        "../outside.md",
        "refs/../../escape.md",
        "C:/secret",
        "/etc/passwd",
        "file.md:secret",
        "refs\\..\\escape",
        "NUL.md",
        "refs/CON",
        "trailing.",
        "refs//a.md",
        ".state.json",
    ],
)
def test_paths_cannot_escape_or_access_reserved_files(client, path):
    client.post("/api/skills", json={"name": "sample", "description": "test"})
    assert (
        client.get("/api/skills/sample/file", params={"path": path}).status_code == 400
    )
    assert (
        client.put(
            "/api/skills/sample/file", json={"path": path, "content": "bad"}
        ).status_code
        == 400
    )


@pytest.mark.parametrize(
    "name", ["UPPER", "-sample", "sample--a", "../sample", "con", "a" * 65]
)
def test_invalid_names_rejected(client, name):
    assert client.post(
        "/api/skills", json={"name": name, "description": "test"}
    ).status_code in {400, 422}


def test_folder_import_copies_resources_and_leaves_original_untouched(
    service, tmp_path
):
    source = tmp_path / "source" / "paper-review"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: paper-review\ndescription: |\n  中文多行描述\n  第二行\nmetadata:\n  version: '1.0'\n---\n# Instructions\n",
        encoding="utf-8",
    )
    (source / "assets").mkdir()
    (source / "assets" / "binary.png").write_bytes(b"\x89PNG\x00\xff")
    (source / "scripts").mkdir()
    (source / "scripts" / "run.py").write_text("print('test')", encoding="utf-8")
    detail = service.import_skill(path=str(source))
    assert detail.valid and detail.file_count == 3 and not detail.enabled
    assert "第二行" in detail.description
    binary = service.read_file(detail.id, "assets/binary.png")
    assert binary.content is None and not binary.previewable
    service.write_file(
        detail.id,
        "scripts/run.py",
        "# edited",
        service.read_file(detail.id, "scripts/run.py").revision,
    )
    assert (source / "scripts" / "run.py").read_text(
        encoding="utf-8"
    ) == "print('test')"


def test_import_api_accepts_manifest_and_rejects_ambiguous_sources(client):
    content = "---\nname: single\ndescription: Sample\n---\n# hello\n"
    assert (
        client.post("/api/skills/import", json={"content": content}).status_code == 201
    )
    assert (
        client.post("/api/skills/import", json={"content": content}).status_code == 409
    )
    assert (
        client.post(
            "/api/skills/import", json={"path": "/tmp", "content": content}
        ).status_code
        == 422
    )
    assert client.post("/api/skills/import", json={}).status_code == 422
    assert (
        client.post(
            "/api/skills/import", json={"content": "# missing name"}
        ).status_code
        == 400
    )


def test_invalid_import_can_be_repaired_and_does_not_enable(service, tmp_path):
    source = tmp_path / "broken"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: wrong-name\ndescription: Sample\n---\n# hello", encoding="utf-8"
    )
    record = service.import_skill(path=str(source))
    assert not record.valid and not record.enabled
    assert "broken" in record.diagnostics[0]


def test_size_limits_reject_partial_imports_and_writes(service, tmp_path):
    source = tmp_path / "oversize"
    source.mkdir()
    (source / "SKILL.md").write_bytes(b"a" * (MAX_FILE_BYTES + 1))
    with pytest.raises(SkillError) as error:
        service.import_skill(path=str(source))
    assert error.value.status == 413
    assert not (service.root / "oversize").exists()
    service.create("sample", "test")
    with pytest.raises(SkillError):
        service.write_file("sample", "big.md", "中文" * (MAX_FILE_BYTES // 3 + 1), None)
    assert not (service.root / "sample" / "big.md").exists()


def test_symlink_import_and_access_are_rejected(service, tmp_path):
    source = tmp_path / "linked"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: linked\ndescription: Sample\n---\n", encoding="utf-8"
    )
    outside = tmp_path / "secret.md"
    outside.write_text("private", encoding="utf-8")
    try:
        (source / "secret.md").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    with pytest.raises(SkillError):
        service.import_skill(path=str(source))
    service.create("sample", "test")
    (service.root / "sample" / "secret.md").symlink_to(outside)
    with pytest.raises(SkillError):
        service.read_file("sample", "secret.md")
    assert not service.detail("sample").valid


def test_yaml_objects_are_not_executed_and_errors_are_inspectable(service, tmp_path):
    source = tmp_path / "unsafe"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: unsafe\ndescription: !!python/object/apply:os.system ['echo unsafe']\n---\n",
        encoding="utf-8",
    )
    record = service.import_skill(path=str(source))
    assert not record.valid and record.diagnostics
    assert service.read_file("unsafe", "SKILL.md").previewable


def test_external_invalid_edit_never_reports_enabled(service):
    service.create("sample", "test")
    service.set_enabled("sample", True)
    (service.root / "sample" / "SKILL.md").write_text("# invalid", encoding="utf-8")
    assert not service.detail("sample").enabled


def test_entrypoint_case_aliases_cannot_bypass_protection(service):
    service.create("sample", "test")
    revision = service.read_file("sample", "SKILL.md").revision
    with pytest.raises(SkillError):
        service.delete_file("sample", "skill.md", revision)
    with pytest.raises(SkillError):
        service.write_file("sample", "skill.md", "# invalid", revision)
    assert service.detail("sample").valid


def test_state_corruption_does_not_silently_reset_settings(service):
    service.create("sample", "test")
    (service.root / ".state.json").write_text("broken", encoding="utf-8")
    with pytest.raises(SkillError) as error:
        service.list()
    assert error.value.status == 409


@pytest.mark.parametrize(
    "extra",
    [
        "metadata:\n  1: string-value",
        "extra: .inf",
        "extra: &cycle [*cycle]",
        "extra: " + "x" * (64 * 1024),
        "a: &a [x,x,x,x,x,x,x,x,x,x]\nb: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a,*a]\nc: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b,*b]\nd: [*c,*c,*c,*c,*c,*c,*c,*c,*c,*c]",
    ],
    ids=[
        "nonstring-key",
        "nonfinite-number",
        "cyclic-alias",
        "large-metadata",
        "expanded-aliases",
    ],
)
def test_metadata_serialization_is_bounded_and_keeps_key_types(extra):
    metadata, diagnostics = parse_manifest(
        f"---\nname: sample\ndescription: test\n{extra}\n---\n", "sample"
    )
    assert metadata == {} and diagnostics
