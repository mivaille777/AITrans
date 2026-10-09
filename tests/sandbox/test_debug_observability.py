from __future__ import annotations

import hashlib
import json
import time
from types import SimpleNamespace
from threading import Event, Thread

import pytest

from backend.sandbox.capacity import bounded_execution
from backend.sandbox.errors import SandboxExecutionError
from backend.sandbox.models import SandboxExecutionResult
from backend.sandbox.monitoring import directory_usage, docker_resource_sample
from backend.sandbox.policy import DEFAULT_SANDBOX_POLICY
from backend.sandbox.recovery import mark_directory, recover_resources
from backend.services.sandbox_debug_artifacts import read_artifact, export_report
from backend.services.sandbox_debug_service import (
    SandboxDebugService,
    SandboxDebugError,
)
from backend.services.sandbox_history_store import SandboxHistoryStore
from backend.models.sandbox_debug import SandboxDebugFile


MANAGER = SimpleNamespace(image="sandbox:v1", policy=DEFAULT_SANDBOX_POLICY)


def begin(service):
    return service.begin_agent_run(
        run_id="run-test", tool_call_id="call-test", manager=MANAGER
    )[0]


def finish(service, sid, stdout="done"):
    return service.finish_agent_run(
        sid,
        SandboxExecutionResult(
            sandbox_id=sid,
            status="succeeded",
            stdout=stdout,
            exit_code=0,
            duration_ms=20,
        ),
    )


def test_live_output_is_scrubbed_across_secret_boundaries():
    service = SandboxDebugService(secret_values_provider=lambda: ("abcSECRET123",))
    try:
        sid = begin(service)
        service.record_observation(
            sid, {"type": "output", "stdout": "hello abcSE", "stderr": ""}
        )
        assert service.get_run(sid).stdout == "hello "
        service.record_observation(
            sid,
            {
                "type": "output",
                "stdout": "hello abcSECRET123 world",
                "stderr": "password=hunter2",
            },
        )
        trace = service.get_run(sid)
        assert trace.run.status == "running"
        assert "abcSECRET123" not in trace.stdout
        assert "hunter2" not in trace.stderr
        assert "world" in trace.stdout
        events, complete = service.wait_events(sid, 0, timeout=0)
        assert not complete and events[-1]["type"] == "output"
    finally:
        service.close()


def test_observed_policy_and_resources_replace_defaults_and_ignore_late_samples():
    service = SandboxDebugService()
    try:
        sid = begin(service)
        service.record_observation(
            sid,
            {
                "type": "policy",
                "network": "restricted",
                "network_hosts": ["example.org"],
                "observed": True,
                "runtime_info": {"image_id": "sha256:123"},
            },
        )
        service.record_observation(
            sid, {"type": "disk", "workspace_bytes": 55, "output_bytes": 22}
        )
        for index in range(250):
            service.record_observation(
                sid,
                {
                    "type": "resource",
                    "sample": {
                        "timestamp_ms": index,
                        "memory_bytes": 1024,
                        "cpu_percent": None,
                    },
                },
            )
        trace = finish(service, sid)
        assert trace.policy.network == "restricted" and trace.policy.observed
        assert trace.policy.network_hosts == ["example.org"]
        assert trace.runtime_info["image_id"] == "sha256:123"
        assert len(trace.resources) == 240
        assert trace.resources[-1].cpu_percent is None
        assert trace.resources[-1].workspace_bytes == 55
        sequence = trace.sequence
        service.record_observation(sid, {"type": "output", "stdout": "stale"})
        service._set_run_status(sid, "running")
        assert service.get_run(sid).sequence == sequence
        assert service.get_run(sid).stdout == "done"
    finally:
        service.close()


def test_event_buffer_resynchronizes_with_latest_snapshot():
    service = SandboxDebugService()
    try:
        sid = begin(service)
        for index in range(2100):
            service.record_observation(
                sid, {"type": "output", "stdout": str(index), "stderr": ""}
            )
        events, complete = service.wait_events(sid, 1, timeout=0)
        assert not complete and len(events) == 1 and events[0]["type"] == "trace"
        assert events[0]["trace"]["stdout"] == "2099"
        assert len(service._get_entry(sid).events) <= 2048
    finally:
        service.close()


@pytest.mark.parametrize("retained", [False, True])
def test_history_content_is_opt_in_and_scrubbed(tmp_path, retained):
    path = tmp_path / "history.sqlite3"
    service = SandboxDebugService(
        history_path=path, secret_values_provider=lambda: ("secret-123",)
    )
    sid = begin(service)
    entry = service._get_entry(sid)
    entry.trace = entry.trace.model_copy(
        update={"logs_retained": retained, "code": "print('[REDACTED]')"}
    )
    finish(service, sid, "hello secret-123")
    service.close()
    restarted = SandboxDebugService(history_path=path)
    try:
        trace = restarted.get_run(sid)
        assert trace.run.status == "succeeded"
        assert "secret-123" not in trace.model_dump_json()
        assert bool(trace.stdout) == retained
        assert bool(trace.code) == retained
    finally:
        restarted.close()


def test_abandoned_history_becomes_interrupted(tmp_path):
    service = SandboxDebugService()
    sid = begin(service)
    trace = service.get_run(sid)
    store = SandboxHistoryStore(tmp_path / "history.sqlite3", 2)
    store.save(trace, {"pid": 2147483647, "started": 0}, terminal=False)
    service.close()
    restarted = SandboxDebugService(history_path=store.path)
    try:
        assert restarted.get_run(sid).run.status == "interrupted"
        assert (
            next(s for s in restarted.get_run(sid).stages if s.key == "cleanup").status
            == "pending"
        )
        restarted.recover(
            SimpleNamespace(
                recover=lambda: {"removed": [], "failed": [], "skipped": []}
            )
        )
        assert (
            next(s for s in restarted.get_run(sid).stages if s.key == "cleanup").status
            == "complete"
        )
    finally:
        restarted.close()


def test_storage_scan_counts_files_and_rejects_entry_or_byte_overflow(tmp_path):
    (tmp_path / "a").write_bytes(b"1234")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "c").write_bytes(b"56")
    assert directory_usage(tmp_path, byte_limit=10, entry_limit=3) == (6, 3, False)
    assert directory_usage(tmp_path, byte_limit=5, entry_limit=3)[2]
    assert directory_usage(tmp_path, byte_limit=10, entry_limit=2)[2]


def test_generated_output_cannot_replace_owner_marker(tmp_path):
    from backend.sandbox.workspace import SandboxWorkspaceManager
    from backend.sandbox.recovery import MARKER

    manager = SandboxWorkspaceManager(
        sandbox_root=tmp_path / "sandboxes", artifact_root=tmp_path / "artifacts"
    )
    workspace = manager.create("sb_" + "a" * 32)
    original = (workspace.root / MARKER).read_bytes()
    (workspace.output_dir / MARKER.upper()).write_text("forged")
    with pytest.raises(SandboxExecutionError, match="reserved"):
        manager.collect_outputs(workspace)
    assert (workspace.root / MARKER).read_bytes() == original
    manager.cleanup(workspace)


def test_cpu_sample_uses_deltas_and_missing_values_remain_unknown():
    previous = {
        "cpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000}
    }
    current = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 200},
            "system_cpu_usage": 2000,
            "online_cpus": 2,
        },
        "memory_stats": {"usage": 55},
        "pids_stats": {"current": 3},
    }
    sample = docker_resource_sample(current, previous)
    assert sample == {"cpu_percent": 20.0, "memory_bytes": 55, "pids": 3}
    assert docker_resource_sample({}, None) == {
        "cpu_percent": None,
        "memory_bytes": None,
        "pids": None,
    }


def test_artifact_download_is_manifest_bound_and_detects_tampering(tmp_path):
    service = SandboxDebugService()
    try:
        sid = begin(service)
        trace = finish(service, sid)
        path = tmp_path / sid / "result.md"
        path.parent.mkdir()
        path.write_bytes(b"# result")
        item = SandboxDebugFile(
            file_id="file-1",
            relative_path="result.md",
            size_bytes=8,
            sha256=hashlib.sha256(b"# result").hexdigest(),
            source="generated",
        )
        trace = trace.model_copy(update={"output_files": [item]})
        assert read_artifact(trace, "file-1", tmp_path) == ("result.md", b"# result")
        with pytest.raises(SandboxDebugError, match="not found"):
            read_artifact(trace, "../outside", tmp_path)
        path.write_bytes(b"# change")
        with pytest.raises(SandboxDebugError, match="verification"):
            read_artifact(trace, "file-1", tmp_path)
        bad = trace.model_copy(
            update={
                "output_files": [
                    item.model_copy(update={"relative_path": "../private.txt"})
                ]
            }
        )
        with pytest.raises(SandboxDebugError, match="Invalid artifact"):
            read_artifact(bad, "file-1", tmp_path)
        path.unlink()
        with pytest.raises(SandboxDebugError) as expired:
            read_artifact(trace, "file-1", tmp_path)
        assert expired.value.status_code == 410
    finally:
        service.close()


def test_markdown_report_fences_untrusted_content():
    service = SandboxDebugService()
    try:
        trace = finish(service, begin(service), "````\n<script>untrusted</script>")
        report = export_report(trace, "markdown")
        assert "`````json" in report["content"]
        assert (
            json.loads(export_report(trace, "json")["content"])["run"]["status"]
            == "succeeded"
        )
    finally:
        service.close()


def test_recovery_preserves_live_and_unverifiable_owners(tmp_path, monkeypatch):
    from backend.sandbox import recovery

    monkeypatch.setattr(
        recovery, "owner_alive", lambda owner: str(owner.get("pid")) == "123"
    )
    removed = []
    sid = "sb_" + "a" * 32

    def resource(pid=None):
        labels = {"com.aitrans.sandbox_id": sid}
        if pid:
            labels.update(
                {"com.aitrans.owner_pid": pid, "com.aitrans.owner_started": "1"}
            )
        return SimpleNamespace(
            name=str(pid),
            attrs={"Config": {"Labels": labels}},
            remove=lambda **kw: removed.append(pid),
        )

    client = SimpleNamespace(
        containers=SimpleNamespace(
            list=lambda **kw: [resource("2147483647"), resource("123"), resource(), resource("-1")]
        ),
        networks=SimpleNamespace(list=lambda **kw: []),
    )
    root = tmp_path / "sandboxes"
    owned = root / sid
    owned.mkdir(parents=True)
    mark_directory(
        owned, sid, {"pid": "2147483647", "started": 1, "created": time.time()}
    )
    unknown = root / ("sb_" + "b" * 32)
    unknown.mkdir()
    result = recover_resources(client, root, tmp_path / "artifacts")
    assert removed == ["2147483647"]
    assert not owned.exists() and unknown.exists()
    assert result["skipped"] == [sid, sid]


def test_process_wide_concurrency_budget_releases_slots():
    release = Event()
    entered = [Event() for _ in range(4)]

    @bounded_execution
    def execute(index):
        entered[index].set()
        release.wait(3)

    threads = [Thread(target=execute, args=(index,)) for index in range(4)]
    try:
        for thread in threads:
            thread.start()
        assert all(event.wait(2) for event in entered)
        with pytest.raises(SandboxExecutionError, match="budget"):
            execute(0)
    finally:
        release.set()
        for thread in threads:
            thread.join(3)
    execute(0)
