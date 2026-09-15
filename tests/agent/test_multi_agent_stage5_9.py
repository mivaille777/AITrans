from __future__ import annotations

from types import SimpleNamespace

from backend.agent_core.multi_agent.context import KnowledgeInjector
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.multi_agent_workspace_service import MultiAgentWorkspaceService


class _FakeKnowledgeRuntime:
    def build_context(self, query: str, top_k: int = 5):
        return {
            "query": query,
            "context": "[knowledge-1] Grounded PID evidence (paper)",
            "citations": [
                {
                    "id": "knowledge-1",
                    "title": "Grounded PID evidence",
                    "source_type": "paper",
                    "score": 0.9,
                }
            ],
        }


class _FakeResearchService:
    def __init__(self) -> None:
        self.calls = []

    def search(self, query, *, limit=5, source_ids=()):
        self.calls.append((query, limit, tuple(source_ids)))
        note = SimpleNamespace(
            note_id="note-1",
            display_title="PID paper note",
            resource_title="PID paper",
            section_heading="Experiments",
            source_text="Safety-constrained Bayesian optimization experiment evidence.",
            ai_content="",
            user_note="",
        )
        return (SimpleNamespace(note=note, source_id="source-1", score=8.5),)


class _FakeTranslationService:
    def __init__(self) -> None:
        self.calls = []

    def translate(self, text, *, source_language, target_language, request_id=0):
        self.calls.append((text, source_language, target_language, request_id))
        return SimpleNamespace(
            translated_text="实验章节翻译草稿",
            provider="fake-translation",
        )


def _service():
    research = _FakeResearchService()
    translation = _FakeTranslationService()
    service = MultiAgentWorkspaceService(
        knowledge_injector=KnowledgeInjector(_FakeKnowledgeRuntime()),
        research_service=research,
        translation_service=translation,
    )
    return service, research, translation


def test_stage5_9_specialists_use_real_service_contracts_and_shared_results():
    service, research, translation = _service()
    run = service.run(
        "阅读这篇论文并翻译实验章节",
        runtime_context={
            "source_text": "Experimental results show lower tracking error.",
            "source_language": "en",
            "target_language": "zh-CN",
            "resource_title": "Control paper",
            "section_heading": "Experiments",
            "research_source_ids": ["source-1"],
        },
    )

    results = {item.agent_name: item for item in run.results}
    assert set(results) == {"research", "reading", "translation"}

    assert research.calls
    assert research.calls[0][2] == ("source-1",)
    assert results["research"].output["matches"][0]["note_id"] == "note-1"

    assert results["reading"].output["resource_title"] == "Control paper"
    assert results["reading"].output["research_findings"][0]["note_id"] == "note-1"

    assert translation.calls
    assert translation.calls[0][1:3] == ("en", "zh-CN")
    assert results["translation"].output["translated_draft"] == "实验章节翻译草稿"
    assert results["translation"].metadata["provider"] == "fake-translation"


def test_stage5_9_bridge_includes_specialist_outputs_in_advisory_context():
    service, _, _ = _service()
    bridge = MultiAgentRuntimeBridge(service)
    payloads = []

    from backend.agent_core.state import AgentState

    state = AgentState(
        user_input="阅读这篇论文并翻译实验章节",
        selected_text="Experimental results show lower tracking error.",
        browser_context={
            "source_language": "en",
            "target_language": "zh-CN",
            "resource_title": "Control paper",
            "section_heading": "Experiments",
        },
    )
    result = bridge.run_with_events(state, lambda event_type, payload: payloads.append((event_type, payload)))

    collaboration = result.browser_context["multi_agent_context"]
    assert collaboration["specialist_result_count"] == 3
    assert {item["agent_name"] for item in collaboration["specialists"]} == {
        "research",
        "reading",
        "translation",
    }
    context_before = result.browser_context["context_before"]
    assert "research specialist output" in context_before
    assert "translation specialist output" in context_before
    assert "实验章节翻译草稿" in context_before
    assert payloads
