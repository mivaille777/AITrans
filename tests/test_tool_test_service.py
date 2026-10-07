from dataclasses import replace
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from backend.models.tool_test import ToolTestRequest
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.tool_management_repository import ToolManagementRepository
from backend.services.tool_management_service import (
    ToolManagementError,
    ToolManagementService,
)
from backend.services.tool_policy_service import ToolPolicyService
from backend.services.tool_test_service import ToolTestService


def setup(tmp_path):
    from backend.services.tool_test_store import ToolTestStore

    policy = ToolPolicyService(ToolManagementRepository(tmp_path / "settings.sqlite3"))
    registry = AgentToolRegistry(tool_policy=policy, retrieval_service=object())
    service = ToolTestService(
        ToolManagementService(registry, policy),
        library=SimpleNamespace(
            get_document=lambda id: object() if id == "doc" else None
        ),
        store=ToolTestStore(tmp_path / "agent_runtime.sqlite3"),
    )
    return service, registry, policy


def request(**values):
    return ToolTestRequest(
        **{
            "client_request_id": "request-1",
            "context_selection": {"reading_context": {"source_text": "text"}},
            **values,
        }
    )


def wait(service, id, status):
    until = monotonic() + 4
    while monotonic() < until:
        run = service.get("builtin:inspect_reading_context", id)
        if run.status == status:
            return run
        sleep(0.01)
    assert run.status == status, run


def test_strict_validation_idempotency_and_server_owned_identifiers(tmp_path):
    service, _, _ = setup(tmp_path)
    id = "builtin:inspect_reading_context"
    with pytest.raises(ToolManagementError, match="reserved"):
        service.create(id, request(arguments={"run_id": "fake"}))
    run = service.create(id, request())
    finished = wait(service, run.test_run_id, "succeeded")
    assert finished.result["tool_name"] == "inspect_reading_context"
    assert finished.tool_call_id.startswith("call_")
    assert service.create(id, request()).test_run_id == run.test_run_id
    with pytest.raises(ToolManagementError, match="different input"):
        service.create(id, request(timeout_seconds=20))
    with pytest.raises(ToolManagementError, match="not found"):
        service.get("builtin:other", run.test_run_id)


def test_scoped_inputs_never_widen_or_enable_global_search(tmp_path):
    service, _, _ = setup(tmp_path)
    body = ToolTestRequest(
        client_request_id="scope",
        arguments={"query": "test"},
        context_selection={"knowledge_document_ids": ["missing"]},
    )
    with pytest.raises(ToolManagementError, match="not found"):
        service.validate("builtin:search_knowledge_base", body)
    with pytest.raises(ToolManagementError, match="global"):
        service.validate(
            "builtin:search_knowledge_base",
            ToolTestRequest(client_request_id="scope", arguments={"query": "test"}),
        )
    with pytest.raises(ToolManagementError, match="expand"):
        service.validate(
            "builtin:search_knowledge_base",
            ToolTestRequest(
                client_request_id="scope",
                arguments={"query": "test", "document_ids": ["other"]},
                context_selection={"knowledge_document_ids": ["doc"]},
            ),
        )
    with pytest.raises(ToolManagementError, match="server-owned"):
        service.validate(
            "builtin:inspect_reading_context",
            ToolTestRequest(
                client_request_id="scope",
                context_selection={
                    "reading_context": {"knowledge_scope_allow_global": True}
                },
            ),
        )


def test_bound_write_approval_rechecks_policy_and_cannot_replay(tmp_path):
    service, registry, policy = setup(tmp_path)
    definition = registry.get_definition("inspect_reading_context")
    calls = []

    def execute(context, args):
        calls.append(context.tool_call_id)
        return replace(definition.executor(context, args), effect="write")

    registry._definition_by_name["inspect_reading_context"] = replace(
        definition,
        spec=replace(
            definition.spec,
            effect="write",
            requires_confirmation=True,
            parallel_safe=False,
            idempotent=False,
        ),
        retry_policy="never",
        executor=execute,
    )
    run = service.create("builtin:inspect_reading_context", request())
    assert run.status == "awaiting_approval" and calls == []
    with pytest.raises(ToolManagementError, match="match"):
        service.approve(run.tool_id, run.test_run_id, "wrong")
    policy.update(run.tool_id, 0, False)
    with pytest.raises(ToolManagementError, match="disabled"):
        service.approve(run.tool_id, run.test_run_id, run.approval_id)
    assert calls == []
    policy.update(run.tool_id, 1, True)
    with pytest.raises(ToolManagementError, match="changed"):
        service.approve(run.tool_id, run.test_run_id, run.approval_id)
    fresh = service.create(run.tool_id, request(client_request_id="fresh"))
    service.approve(fresh.tool_id, fresh.test_run_id, fresh.approval_id)
    wait(service, fresh.test_run_id, "succeeded")
    assert calls == [fresh.tool_call_id]
    with pytest.raises(ToolManagementError):
        service.approve(fresh.tool_id, fresh.test_run_id, fresh.approval_id)


def test_cancel_does_not_claim_to_stop_physical_executor(tmp_path):
    service, registry, _ = setup(tmp_path)
    definition = registry.get_definition("inspect_reading_context")
    started, release = Event(), Event()

    def blocked(context, args):
        started.set()
        release.wait(3)
        return definition.executor(context, args)

    registry._definition_by_name[definition.spec.name] = replace(
        definition, executor=blocked
    )
    run = service.create("builtin:inspect_reading_context", request())
    assert started.wait(2)
    cancelled = service.cancel(run.tool_id, run.test_run_id)
    assert cancelled.status == "cancelled" and cancelled.execution_state == "running"
    release.set()
    until = monotonic() + 3
    while (
        service.get(run.tool_id, run.test_run_id).execution_state != "stopped"
        and monotonic() < until
    ):
        sleep(0.01)
    final = service.get(run.tool_id, run.test_run_id)
    assert (
        final.status == "cancelled"
        and final.result is None
        and final.execution_state == "stopped"
    )


def test_deadline_does_not_retry_or_hide_continuing_worker(tmp_path):
    service, registry, _ = setup(tmp_path)
    definition = registry.get_definition("inspect_reading_context")
    release = Event()
    calls = []

    def blocked(context, args):
        calls.append(context.tool_call_id)
        release.wait(3)
        return definition.executor(context, args)

    registry._definition_by_name[definition.spec.name] = replace(
        definition, executor=blocked
    )
    run = service.create("builtin:inspect_reading_context", request(timeout_seconds=1))
    timed_out = wait(service, run.test_run_id, "timed_out")
    assert timed_out.execution_state in {"running", "unknown"}
    assert calls == [run.tool_call_id]
    release.set()


def test_api_rejects_raw_confirmation_and_context_ids(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.tools import get_tool_test_service, router

    service, _, _ = setup(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tool_test_service] = lambda: service
    client = TestClient(app)
    url = "/api/tools/builtin:inspect_reading_context/test-runs"
    body = request().model_dump()
    assert client.post(url, json={**body, "confirmed": True}).status_code == 422
    assert (
        client.post(
            url, json={**body, "context_selection": {"run_id": "fake"}}
        ).status_code
        == 422
    )
    response = client.post(url, json=body)
    assert response.status_code == 202
    assert (
        client.post(url, json=body).json()["test_run_id"]
        == response.json()["test_run_id"]
    )
    finished = wait(service, response.json()["test_run_id"], "succeeded")
    events_url = url + "/" + finished.test_run_id + "/events"
    stream = client.get(events_url, headers={"Last-Event-ID": "1"})
    assert stream.status_code == 200
    assert "id: 1\n" not in stream.text and "event: closed" in stream.text
    assert client.get(url).json()["items"][0]["test_run_id"] == finished.test_run_id
    restarted = ToolTestService(service.management, store=service.store)
    assert (
        restarted.create(finished.tool_id, request()).test_run_id
        == finished.test_run_id
    )
