"""Runtime regressions: lazy disclosure, scope, budgets and native tool integration."""

import copy
import json
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.tool_calling import ToolCompletion
from backend.api.skills import get_skill_service, router
from backend.services.agent_react_decision_service import AgentReActDecisionService
from backend.services.companion_chat_service import CompanionChatService
from backend.services.skill_runtime import INSTRUCTION_CHARS, MAX_CALLS, SkillRuntime
from backend.services.skill_service import SkillService


@pytest.fixture
def service(tmp_path):
    return SkillService(tmp_path / "skills")


def install(
    service, name="paper-review", body="Check methods before conclusions.", **metadata
):
    content = (
        "---\n"
        + yaml.safe_dump(
            {"name": name, "description": "审阅论文和研究方法", "metadata": metadata},
            allow_unicode=True,
        )
        + "---\n"
        + body
    )
    service.import_skill(content=content)
    service.write_file(name, "references/guide.md", "Reference text " * 500, None)
    service.set_enabled(name, True)
    return name


def invoke(session, name, **args):
    return session.invoke(name, json.dumps(args))


def test_discovery_reads_only_header_and_caches_it(service, monkeypatch):
    install(service, body="SECRET_BODY" * 10000)
    monkeypatch.setattr(
        service, "read_file", lambda *args: pytest.fail("Discovery read a body")
    )
    monkeypatch.setattr(
        service, "_inventory", lambda *args: pytest.fail("Discovery walked resources")
    )
    descriptors = service.descriptors()
    assert descriptors[0].id == "paper-review"
    assert "SECRET_BODY" not in descriptors[0].model_dump_json()
    assert service._headers
    # The second pass validates file stats, but does not reparse unchanged YAML.
    import backend.services.skill_service as module

    monkeypatch.setattr(
        module, "parse_manifest", lambda *args: pytest.fail("Cache missed")
    )
    assert service.descriptors() == descriptors


def test_three_disclosure_levels_and_paged_resource_dedup(service):
    install(service, body="INSTRUCTION_SENTINEL")
    runtime = SkillRuntime(service)
    session = runtime.start("审阅论文")
    assert "INSTRUCTION_SENTINEL" not in session.context()
    assert "Reference text" not in session.context()
    assert "read_skill_resource" not in session.function_names
    assert invoke(session, "activate_skill", skill_id="paper-review")["ok"]
    assert "INSTRUCTION_SENTINEL" in session.context()
    assert "Reference text" not in session.context()
    result = invoke(
        session,
        "read_skill_resource",
        skill_id="paper-review",
        path="references/guide.md",
        offset=0,
        limit=100,
    )
    assert result["data"]["next_offset"] == 100
    assert "Reference text" in session.context()
    cost = session.resource_chars
    assert invoke(
        session,
        "read_skill_resource",
        skill_id="paper-review",
        path="references/guide.md",
        offset=0,
        limit=100,
    )["data"]["already_loaded"]
    assert session.resource_chars == cost
    assert "INSTRUCTION_SENTINEL" not in json.dumps(session.snapshot())


def test_manual_and_mode_scope_fail_closed(service):
    install(
        service, **{"aitrans-invocation": "manual", "aitrans-context-modes": "reading"}
    )
    runtime = SkillRuntime(service)
    assert not runtime.start("审阅论文", "reading").candidates
    assert not runtime.start("$paper-review", "general").active
    explicit = runtime.start("/paper-review 帮我审稿", "reading")
    assert "paper-review" in explicit.active
    # A model cannot use a forged explicit mention in discovery to expose a manual Skill.
    automatic = runtime.start("审阅论文", "reading")
    discovered = invoke(
        automatic, "discover_skills", category="research", query="$paper-review"
    )
    assert discovered["ok"] and discovered["data"]["candidates"] == []
    service.set_enabled("paper-review", False)
    assert not explicit.active or "INSTRUCTION_SENTINEL" not in explicit.context()
    assert explicit.snapshot()["active"] == []


def test_metadata_update_invalidates_cached_candidates_and_active_body(service):
    install(service, body="OLD_INSTRUCTIONS")
    runtime = SkillRuntime(service)
    session = runtime.start("$paper-review")
    before = runtime.catalog().revision
    file = service.read_file("paper-review", "SKILL.md")
    service.write_file(
        "paper-review",
        "SKILL.md",
        file.content.replace("OLD_INSTRUCTIONS", "NEW_INSTRUCTIONS"),
        file.revision,
    )
    assert runtime.catalog().revision != before
    assert "OLD_INSTRUCTIONS" not in session.context()
    assert not invoke(session, "activate_skill", skill_id="paper-review")["ok"]
    assert "NEW_INSTRUCTIONS" in runtime.start("$paper-review").context()


def test_resource_changes_do_not_mix_versions(service):
    install(service)
    session = SkillRuntime(service).start("$paper-review")
    assert invoke(
        session,
        "read_skill_resource",
        skill_id="paper-review",
        path="references/guide.md",
        limit=100,
    )["ok"]
    file = service.read_file("paper-review", "references/guide.md")
    service.write_file("paper-review", file.path, "new text", file.revision)
    assert not invoke(
        session,
        "read_skill_resource",
        skill_id="paper-review",
        path=file.path,
        offset=1,
        limit=2,
    )["ok"]
    assert "Reference text" not in session.context()


@pytest.mark.parametrize("path", ["../outside.txt", "SKILL.md", "missing.txt"])
def test_resource_paths_must_be_listed_and_active(service, path):
    install(service)
    session = SkillRuntime(service).start("$paper-review")
    assert not invoke(
        session, "read_skill_resource", skill_id="paper-review", path=path
    )["ok"]


def test_binary_resource_is_not_injected(service):
    install(service)
    (service.root / "paper-review" / "assets").mkdir()
    (service.root / "paper-review" / "assets" / "binary.bin").write_bytes(b"\x00\xff")
    session = SkillRuntime(service).start("$paper-review")
    assert not invoke(
        session,
        "read_skill_resource",
        skill_id="paper-review",
        path="assets/binary.bin",
    )["ok"]


def test_instruction_budget_never_silently_truncates_and_calls_are_bounded(service):
    install(service, body="X" * (INSTRUCTION_CHARS + 1))
    session = SkillRuntime(service).start("审阅论文")
    assert not invoke(session, "activate_skill", skill_id="paper-review")["ok"]
    assert not session.active
    for _ in range(MAX_CALLS + 3):
        invoke(session, "discover_skills", category="research", query="review")
    assert len(session.calls) == MAX_CALLS
    assert session.function_names == []


def test_sessions_are_isolated_and_catalog_does_not_enumerate_all_skills(service):
    install(service)
    runtime = SkillRuntime(service)
    assert "paper-review" not in runtime.catalog().model_dump_json()
    assert runtime.start("$paper-review").active
    assert not runtime.start("你好").active


def test_http_route_is_metadata_only_and_static_paths_precede_ids(service, monkeypatch):
    install(service, body="BODY_SENTINEL")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_skill_service] = lambda: service
    monkeypatch.setattr(
        service, "read_file", lambda *args: pytest.fail("Route preview loaded a body")
    )
    with TestClient(app) as client:
        catalog = client.get("/api/skills/catalog")
        assert catalog.status_code == 200 and catalog.json()["eligible_count"] == 1
        result = client.post(
            "/api/skills/route", json={"query": "审阅论文", "context_mode": "reading"}
        )
        assert result.status_code == 200
        assert result.json()["candidates"][0]["id"] == "paper-review"
        assert result.json()["body_loaded"] is False
        assert "BODY_SENTINEL" not in result.text
        assert (
            client.post(
                "/api/skills/route", json={"query": "x", "category": "unknown"}
            ).status_code
            == 400
        )


def tool(name, args, identifier):
    return ToolCompletion(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": identifier,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ],
        }
    )


class Client:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def complete(self, **kwargs):
        pytest.fail("Expected native functions")

    def complete_tools(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return self.responses.pop(0)


def workflow():
    return [
        tool("discover_skills", {"category": "research", "query": "审阅论文"}, "s1"),
        tool("activate_skill", {"skill_id": "paper-review"}, "s2"),
        tool(
            "read_skill_resource",
            {"skill_id": "paper-review", "path": "references/guide.md", "limit": 100},
            "s3",
        ),
        ToolCompletion({"role": "assistant", "content": "完成评审。"}),
    ]


def test_companion_native_discover_activate_read_with_knowledge_never(service):
    install(service, body="INSTRUCTION_SENTINEL")
    client = Client(workflow())
    chat = CompanionChatService(
        text_service=SimpleNamespace(
            provider=SimpleNamespace(client=client), provider_name="fake", model="fake"
        ),
        function_calling_enabled=True,
        skill_runtime_factory=lambda: SkillRuntime(service),
        knowledge_tools_factory=lambda: pytest.fail(
            "Knowledge NEVER must not load tools"
        ),
    )
    prepared = []
    result = chat.send(
        session_id="s",
        user_message="审阅论文",
        context_mode="general",
        knowledge_access_policy="never",
        prepared_callback=prepared.append,
    )
    assert result.output_text == "完成评审。"
    assert "INSTRUCTION_SENTINEL" not in json.dumps(client.requests[0]["messages"])
    assert "INSTRUCTION_SENTINEL" in json.dumps(client.requests[2]["messages"])
    assert "Reference text" in json.dumps(client.requests[3]["messages"])
    assert not prepared[-1].grounding.debug_metadata["function_calls"]
    assert len(prepared[-1].grounding.debug_metadata["skills"]["active"]) == 1
    assert not result.evidence


def test_react_consumes_skills_before_returning_decision_and_reuses_session(service):
    install(service, body="INSTRUCTION_SENTINEL")
    client = Client(
        workflow() + [ToolCompletion({"role": "assistant", "content": "继续。"})]
    )
    decision_service = AgentReActDecisionService(
        text_service=SimpleNamespace(provider=SimpleNamespace(client=client))
    )
    session = SkillRuntime(service).start("审阅论文")
    decision = decision_service.decide(
        iteration=1,
        tools=(),
        user_message="审阅论文",
        knowledge_access_policy="never",
        skill_session=session,
    )
    assert decision.kind == "final" and decision.final_answer == "完成评审。"
    assert len(session.active) == 1
    decision_service.decide(
        iteration=2,
        tools=(),
        user_message="审阅论文",
        knowledge_access_policy="never",
        skill_session=session,
    )
    assert (
        json.dumps(client.requests[-1]["messages"]).count("INSTRUCTION_SENTINEL") == 1
    )


def test_knowledge_always_offers_knowledge_before_skill_selection(service):
    install(service)
    from backend.services.skill_function_bridge import SkillCallingClient

    client = Client([ToolCompletion({"role": "assistant", "content": "invalid"})])
    bridge = SkillCallingClient(client, SkillRuntime(service).start("审阅论文"))
    bridge.complete_tools(
        messages=[{"role": "user", "content": "question"}],
        tools=[{"type": "function", "function": {"name": "search_knowledge_base"}}],
        tool_choice="required",
    )
    offered = {item["function"]["name"] for item in client.requests[0]["tools"]}
    assert "search_knowledge_base" in offered and "activate_skill" not in offered


def test_native_stream_only_releases_final_text_after_skill_calls(service):
    install(service)
    from backend.services.skill_function_bridge import SkillCallingClient

    client = Client(workflow())

    def stream_tools(**kwargs):
        response = client.complete_tools(**kwargs)
        yield response.content or "tentative text must be discarded"
        yield response

    client.stream_tools = stream_tools
    bridge = SkillCallingClient(client, SkillRuntime(service).start("审阅论文"))
    result = list(
        bridge.stream_tools(
            messages=[{"role": "user", "content": "审阅论文"}],
            tools=[],
            tool_choice="auto",
        )
    )
    assert result[0] == "完成评审。" and result[1].content == "完成评审。"
    assert len(result) == 2


def test_resource_budget_and_active_limit(service):
    for name in ("paper-review", "paper-writing", "paper-reading", "paper-extra"):
        install(service, name=name)
    session = SkillRuntime(service).start("paper")
    for name in ("paper-review", "paper-writing", "paper-reading"):
        assert invoke(session, "activate_skill", skill_id=name)["ok"]
    assert not invoke(session, "activate_skill", skill_id="paper-extra")["ok"]
    assert invoke(
        session,
        "read_skill_resource",
        skill_id="paper-review",
        path="references/guide.md",
        limit=4000,
    )["ok"]
    assert not invoke(
        session,
        "read_skill_resource",
        skill_id="paper-writing",
        path="references/guide.md",
        limit=4000,
    )["ok"]
    assert len(session.active) == 3 and session.resource_chars <= 8000


def test_legacy_chat_loads_explicit_skill_and_initializes_empty_debug_metadata(service):
    install(service, body="INSTRUCTION_SENTINEL")
    requests, prepared = [], []

    def execute(request):
        requests.append(request)
        return SimpleNamespace(
            session_id=request.session_id,
            user_message=request.user_message,
            output_text="完成。",
            provider="fake",
            model="fake",
            request_id=request.request_id,
        )

    chat = CompanionChatService(
        chat_service=SimpleNamespace(execute=execute),
        skill_runtime_factory=lambda: SkillRuntime(service),
    )
    result = chat.send(
        session_id="s",
        user_message="$paper-review 审阅论文",
        context_mode="general",
        knowledge_access_policy="never",
        prepared_callback=prepared.append,
    )
    assert result.output_text == "完成。"
    assert "INSTRUCTION_SENTINEL" in requests[0].skill_context
    assert (
        prepared[-1].grounding.debug_metadata["skills"]["active"][0]["id"]
        == "paper-review"
    )
