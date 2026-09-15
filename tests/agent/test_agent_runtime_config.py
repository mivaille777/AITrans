from __future__ import annotations

from fastapi.testclient import TestClient

from app.ai.gateway import LLMGateway
from backend.api.agent_runtime_config import get_agent_runtime_config
from backend.main import create_app


class DefaultSettings:
    user_data: dict[str, object] = {}

    def get(self, _section: str, _key: str, default=None):
        return default


def test_runtime_config_exposes_only_safe_routing_metadata() -> None:
    response = get_agent_runtime_config(LLMGateway(settings_factory=DefaultSettings))

    routes = {route.role: route for route in response.model_routes}
    assert routes["planner"].model == "deepseek-v4-flash"
    assert routes["agent_synthesis"].model == "deepseek-v4-pro"
    assert routes["reading"].provider == "deepseek"
    assert response.document_content_trust == "untrusted_data"
    assert response.planner_argument_policy == "tool_schema_allowlist"
    assert response.write_confirmation_required is True
    assert response.planner_context_max_chars > 0
    assert response.chat_context_max_chars > response.planner_context_max_chars

    prompt_ids = {prompt.prompt_id for prompt in response.prompts}
    assert "agent.planner@1.2.0" in prompt_ids
    assert "agent.multi_step_planner@1.1.0" in prompt_ids
    assert "rag.query_planner@1.3.0" in prompt_ids
    assert "chat.reading@1.3.0" in prompt_ids
    assert "text.translate@1.0.0" in prompt_ids
    assert all("prompt" not in prompt.model_dump() for prompt in response.prompts)


def test_runtime_config_http_endpoint_requires_no_provider_credentials() -> None:
    client = TestClient(create_app())

    response = client.get("/api/agent/runtime/config")

    assert response.status_code == 200
    body = response.json()
    assert body["document_content_trust"] == "untrusted_data"
    assert body["model_routes"]
    assert body["prompts"]
