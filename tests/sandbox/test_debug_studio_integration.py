from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import sandbox_debug as api
from backend.api.dependencies import (
    get_sandbox_debug_service,
    get_filesystem_workspace_service,
)
from backend.sandbox.docker_runtime import DockerSandboxRuntime, SANDBOX_LABEL
from backend.sandbox.manager import SandboxManager
from backend.sandbox.policy import DEFAULT_SANDBOX_POLICY
from backend.sandbox.workspace import SandboxWorkspaceManager
from backend.sandbox.network_policy import NetworkPolicy
from backend.services.sandbox_debug_service import SandboxDebugService

pytestmark = pytest.mark.docker_integration


@pytest.fixture
def studio(tmp_path, monkeypatch):
    runtime = DockerSandboxRuntime()
    health = runtime.health()
    if not health.available:
        pytest.skip(f"Docker sandbox unavailable: {health.error_code}")
    baseline = {
        c.id
        for c in runtime._get_client().containers.list(
            all=True, filters={"label": f"{SANDBOX_LABEL}=true"}
        )
    }
    # An ASCII staging directory also works with Docker Desktop bind mounts.
    root = Path(".cache/sandbox-studio-live") / uuid4().hex
    manager = SandboxManager(
        runtime,
        SandboxWorkspaceManager(
            sandbox_root=root / "sandboxes", artifact_root=root / "artifacts"
        ),
    )
    service = SandboxDebugService(history_path=tmp_path / "history.sqlite3")
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_sandbox_debug_service] = lambda: service
    app.dependency_overrides[get_filesystem_workspace_service] = lambda: None
    monkeypatch.setattr(api, "get_sandbox_debug_service", lambda: service)
    monkeypatch.setattr(api, "_require_manager", lambda: manager)
    with TestClient(app) as client:
        yield client, service, manager, runtime
    service.close()
    remaining = {
        c.id
        for c in runtime._get_client().containers.list(
            all=True, filters={"label": f"{SANDBOX_LABEL}=true"}
        )
    }
    assert remaining == baseline
    manager.close()


def wait_terminal(client, sid):
    for _ in range(400):
        trace = client.get(f"/api/sandbox/debug/runs/{sid}").json()
        if trace["run"]["status"] not in {
            "pending",
            "queued",
            "preparing",
            "running",
            "cancelling",
        }:
            return trace
        time.sleep(0.05)
    raise AssertionError("Run did not finish")


def test_real_stream_reconnect_resources_reports_and_artifact(studio):
    client, service, manager, runtime = studio
    response = client.post(
        "/api/sandbox/debug/runs",
        json={
            "code": "import time\nprint('Hello from AITran Sandbox', flush=True)\ntime.sleep(4)\nopen('/output/report.md','w').write('# sandbox report')\nprint('finished')",
            "retain_content": True,
        },
    )
    assert response.status_code == 202
    sid = response.json()["sandbox_id"]
    with client.websocket_connect(f"/api/sandbox/debug/runs/{sid}/stream") as stream:
        first = stream.receive_json()
        assert first["trace"]["run"]["sandbox_id"] == sid
        for _ in range(100):
            event = stream.receive_json()
            if (
                event["type"] == "output"
                and "Hello from AITran Sandbox" in event["stdout"]
            ):
                assert service.get_run(sid).run.status == "running"
                break
        else:
            raise AssertionError("No live stdout before completion")
    with client.websocket_connect(f"/api/sandbox/debug/runs/{sid}/stream") as stream:
        snapshot = stream.receive_json()
        assert snapshot["trace"]["run"]["sandbox_id"] == sid
        assert "Hello from AITran Sandbox" in snapshot["trace"]["stdout"]
        while stream.receive_json()["type"] != "terminal":
            pass
    trace = wait_terminal(client, sid)
    assert trace["run"]["status"] == "succeeded"
    assert len(client.get("/api/sandbox/debug/runs").json()) == 1
    assert "finished" in trace["stdout"]
    assert trace["policy"]["observed"] and trace["policy"]["network"] == "none"
    assert trace["runtime_info"]["image_id"].startswith("sha256:")
    assert trace["runtime_info"]["docker_network_mode"] == "none"
    assert any(
        sample["memory_bytes"] and sample["pids"] for sample in trace["resources"]
    )
    assert any(sample["cpu_percent"] is not None for sample in trace["resources"])
    file_id = trace["output_files"][0]["file_id"]
    path = f"/api/sandbox/debug/runs/{sid}/files/{file_id}"
    assert client.get(path + "?preview=true").json()["text"] == "# sandbox report"
    downloaded = client.get(path)
    assert downloaded.content == b"# sandbox report"
    assert "attachment" in downloaded.headers["content-disposition"]
    assert client.get(f"/api/sandbox/debug/runs/{sid}/files/unknown").status_code == 404
    for format in ("markdown", "json"):
        report = client.get(
            f"/api/sandbox/debug/runs/{sid}/report?format={format}"
        ).json()
        assert sid in report["content"]
    diagnostics = client.post("/api/sandbox/debug/runtime/diagnostics").json()
    assert diagnostics["environment"]["python"].startswith("3.")
    assert "pytest" in diagnostics["environment"]["dependencies"]


def test_real_cancel_waits_for_container_cleanup(studio):
    client, service, manager, runtime = studio
    sid = client.post(
        "/api/sandbox/debug/runs",
        json={"code": "import time\nprint('ready')\ntime.sleep(20)"},
    ).json()["sandbox_id"]
    for _ in range(100):
        if service.get_run(sid).stdout:
            break
        time.sleep(0.05)
    response = client.post(f"/api/sandbox/debug/runs/{sid}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] in {"cancelling", "cancelled"}
    trace = wait_terminal(client, sid)
    assert trace["run"]["status"] == "cancelled"
    assert (
        next(stage for stage in trace["stages"] if stage["key"] == "cleanup")["status"]
        == "complete"
    )


def test_real_storage_budget_stops_execution(studio):
    client, service, manager, runtime = studio
    runtime.policy = replace(DEFAULT_SANDBOX_POLICY, workspace_disk_limit_bytes=1024)
    sid = client.post(
        "/api/sandbox/debug/runs",
        json={
            "code": "import time\nopen('/workspace/large.txt','w').write('x'*2048)\ntime.sleep(15)"
        },
    ).json()["sandbox_id"]
    trace = wait_terminal(client, sid)
    assert trace["run"]["status"] == "storage_limit_exceeded"
    assert trace["run"]["duration_ms"] < 10000
    assert trace["output_files"] == []


def test_real_command_debug_rejects_shell_and_path_escape(studio):
    client, service, manager, runtime = studio
    invalid = client.post(
        "/api/sandbox/debug/runs",
        json={
            "code": "command",
            "execution_kind": "command",
            "argv": ["python", "--version"],
            "cwd": "../private",
        },
    )
    assert invalid.status_code == 422
    for argv, expected in (
        (["python", "--version"], "succeeded"),
        (["sh", "-c", "echo unsafe"], "failed"),
    ):
        response = client.post(
            "/api/sandbox/debug/runs",
            json={"code": "command", "execution_kind": "command", "argv": argv},
        )
        assert response.status_code == 202
        trace = wait_terminal(client, response.json()["sandbox_id"])
        assert trace["run"]["status"] == expected
        if expected == "succeeded":
            assert "Python 3." in trace["stdout"]
        else:
            assert "denied" in trace["error"].lower()


def test_real_restricted_policy_and_dead_owner_recovery(studio):
    client, service, manager, runtime = studio
    sid, stage = service.begin_agent_run(
        run_id="approved-network", tool_call_id="call-network", manager=manager
    )
    result = manager.execute_python(
        "print('restricted')",
        sandbox_id=sid,
        network_policy=NetworkPolicy(mode="restricted", allowed_hosts=("example.com",)),
        on_stage=stage,
        on_observation=service.observation_callback(sid),
    )
    trace = service.finish_agent_run(sid, result)
    assert trace.run.status == "succeeded"
    assert trace.policy.network == "restricted"
    assert trace.policy.network_hosts == ["example.com"]
    abandoned_id = "sb_" + uuid4().hex
    labels = {
        "com.aitrans.sandbox": "true",
        "com.aitrans.sandbox_id": abandoned_id,
        "com.aitrans.owner_pid": "2147483647",
        "com.aitrans.owner_started": "1",
    }
    orphan = runtime._get_client().containers.create(
        runtime.image,
        command=["python", "-c", "print('orphan')"],
        labels=labels,
        network_mode="none",
    )
    try:
        recovered = client.post("/api/sandbox/debug/runtime/recover").json()
        assert abandoned_id in recovered["removed"]
    finally:
        from docker.errors import NotFound

        try:
            orphan.remove(force=True)
        except NotFound:
            pass
