from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.state import AgentState
from backend.agent_graph.academic_writer_graph import AcademicWriterGraph
from backend.agent_tools.base import AgentToolInvocationContext
from backend.agent_tools.translation import TranslateSelectionArgs, TranslationAgentTool
from backend.memory.coordinator import MemoryCoordinator
from backend.memory.repository import SQLiteMemoryRepository
from backend.models.agent_artifacts import ArtifactKind
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_tasks import ScopeContext, TaskRole, TaskSpec
from backend.models.memory import MemoryKind
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge


class CaptureWriter:
    def __init__(self):
        self.payload = {}

    def generate(self, *, expected_kind, payload):
        self.payload = dict(payload)
        return {
            "section_id": "discussion",
            "title": "Discussion",
            "paragraphs": [],
            "missing_inputs": ["source_artifacts"],
        }


class CaptureLanguageCapability:
    def __init__(self):
        self.arguments = {}

    def translate(self, source_text, **kwargs):
        self.arguments = {"source_text": source_text, **kwargs}
        return type(
            "TranslationResult",
            (),
            {
                "translated_text": "图神经网络",
                "provider": "ai",
                "model": "test-model",
                "source_language": kwargs["source_language"],
                "target_language": kwargs["target_language"],
                "request_id": kwargs["request_id"],
                "fallback_level": 0,
                "notice": "",
                "attempts": (),
            },
        )()


class FastMemoryOrchestrator:
    def __init__(self, scope, snapshot):
        self.scope = scope
        self.snapshot = snapshot

    def route(self, *_args, **_kwargs):
        return OrchestrationRoute(
            lane=OrchestrationLane.FAST,
            reason_code="fast_language",
            user_visible_reason="Use the language capability directly.",
        )

    def resolve_memory(self, **_kwargs):
        return self.scope, self.snapshot


def test_new_session_resolves_explicit_project_reference_and_writer_preferences(
    tmp_path,
):
    path = tmp_path / "memory.sqlite3"
    coordinator = MemoryCoordinator(SQLiteMemoryRepository(path))
    coordinator.remember(
        operation_id="project-ref",
        profile_id="profile-a",
        workspace_id="workspace-a",
        kind=MemoryKind.PROJECT_REFERENCE,
        content="Continue writing project writing-123 at section discussion version 4.",
        source_ref="writing-project:writing-123:4",
        metadata={
            "project_id": "writing-123",
            "section_id": "discussion",
            "version": 4,
        },
    )
    coordinator.remember(
        operation_id="style",
        profile_id="profile-a",
        kind=MemoryKind.WRITING_STYLE,
        content="Use concise academic prose.",
        source_ref="user:style",
    )
    scope = ScopeContext.issue(
        profile_id="profile-a",
        workspace_id="workspace-a",
        scope_revision="continuity",
    )
    snapshot = MemoryCoordinator(SQLiteMemoryRepository(path)).load_snapshot(
        profile_id="profile-a", scope=scope, run_id="new-session"
    )
    provider = CaptureWriter()
    writer = AcademicWriterGraph(
        artifact_store=InMemoryArtifactStore(), provider=provider
    )
    task = TaskSpec(
        task_id="writer-1",
        role=TaskRole.WRITER,
        objective="Continue the specified discussion section",
        required=True,
        expected_output_kind=ArtifactKind.MANUSCRIPT_SECTION,
        scope_ref=scope.scope_ref,
    )

    writer.execute(
        task=task,
        scope=scope,
        dependency_results={},
        memory_snapshot=snapshot,
    )

    preferences = provider.payload["writing_preferences"]
    assert {item["kind"] for item in preferences} == {
        "project_reference",
        "writing_style",
    }
    reference = next(
        item for item in preferences if item["kind"] == "project_reference"
    )
    assert reference["metadata"] == {
        "project_id": "writing-123",
        "section_id": "discussion",
        "version": 4,
    }


def test_project_reference_never_leaks_to_another_workspace(tmp_path):
    coordinator = MemoryCoordinator(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    coordinator.remember(
        operation_id="project-a",
        profile_id="profile-a",
        workspace_id="workspace-a",
        kind=MemoryKind.PROJECT_REFERENCE,
        content="writing-SECRET-A",
        source_ref="writing-project:writing-SECRET-A:1",
    )
    other_scope = ScopeContext.issue(
        profile_id="profile-a",
        workspace_id="workspace-b",
        scope_revision="other",
    )
    packet = coordinator.load_snapshot(
        profile_id="profile-a", scope=other_scope, run_id="workspace-b-run"
    )
    assert "writing-SECRET-A" not in str(packet)


def test_language_and_writer_share_the_same_effective_terminology_version(tmp_path):
    coordinator = MemoryCoordinator(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    terminology = coordinator.remember(
        operation_id="terminology-1",
        profile_id="profile-a",
        kind=MemoryKind.TERMINOLOGY,
        content="graph neural network => 图神经网络",
        source_ref="user:terminology",
    )
    scope = ScopeContext.issue(
        profile_id="profile-a",
        workspace_id="workspace-a",
        scope_revision="terminology",
    )
    snapshot = coordinator.load_snapshot(
        profile_id="profile-a", scope=scope, run_id="shared-terminology-run"
    )

    writer_provider = CaptureWriter()
    AcademicWriterGraph(
        artifact_store=InMemoryArtifactStore(), provider=writer_provider
    ).execute(
        task=TaskSpec(
            task_id="writer-terminology",
            role=TaskRole.WRITER,
            objective="Draft with the preferred terminology",
            required=True,
            expected_output_kind=ArtifactKind.MANUSCRIPT_SECTION,
            scope_ref=scope.scope_ref,
        ),
        scope=scope,
        dependency_results={},
        memory_snapshot=snapshot,
    )

    language = CaptureLanguageCapability()
    bridge = MultiAgentRuntimeBridge(
        orchestrator=FastMemoryOrchestrator(scope, snapshot)
    )
    fast_state = AgentState(
        user_input="translate this",
        selected_text="graph neural network",
        browser_context={"source_language": "en", "target_language": "zh-CN"},
    )
    assert bridge.should_run(fast_state) is False
    bridge.prepare_state(fast_state)
    language_preferences = ProductAgentRuntimeAdapter.build_payload(fast_state)[
        "memory_language_preferences"
    ]
    result = TranslationAgentTool(
        translation_service=None,
        translation_fallback_service=language,
    ).execute(
        AgentToolInvocationContext(
            source_text="graph neural network",
            source_language="en",
            target_language="zh-CN",
            memory_preferences=language_preferences,
        ),
        TranslateSelectionArgs(target_language="zh-CN"),
    )

    writer_term = next(
        item
        for item in writer_provider.payload["writing_preferences"]
        if item["kind"] == "terminology"
    )
    assert (writer_term["item_id"], writer_term["version"]) == (
        terminology.item_id,
        terminology.version,
    )
    assert language.arguments["terminology"] == (terminology.content,)
    assert result.data["memory_preference_refs"] == [
        f"{terminology.item_id}:{terminology.version}"
    ]
