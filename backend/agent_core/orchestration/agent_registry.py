"""Specialist catalog for the gradual LangGraph-native migration.

TaskRole remains the persisted task contract through LG01. The registry owns
specialist metadata and planning defaults; the existing tool registry still
owns typed tool execution.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from backend.models.agent_artifacts import ArtifactKind
from backend.models.agent_tasks import TaskRole

GraphFactory = Callable[[], object]
OutputSelector = Callable[[str], ArtifactKind]
ResourceClass = Literal["cpu", "gpu", "io"]


@dataclass(frozen=True, slots=True)
class AgentRetryPolicy:
    max_retries: int = 1

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be nonnegative")


@dataclass(frozen=True, slots=True)
class AgentTimeoutPolicy:
    seconds: float = 90.0

    def __post_init__(self) -> None:
        if self.seconds <= 0:
            raise ValueError("timeout seconds must be positive")

DOCUMENT_TOOLS = frozenset(
    {
        "inspect_reading_context", "explain_selection", "summarize_selection",
        "analyze_section_role", "define_terms", "analyze_equation",
        "summarize_current_section", "search_knowledge_base",
    }
)
RESEARCH_TOOLS = frozenset(
    {
        "search_knowledge_base", "list_research_notes", "search_research_notes",
        "get_research_note", "analyze_cross_document_research",
    }
)
WRITER_TOOLS = frozenset(
    {
        "inspect_reading_context", "search_knowledge_base", "get_research_note",
        "translate_selection", "polish_selection",
    }
)
CURATOR_TOOLS = frozenset(
    {
        "search_knowledge_base", "list_research_notes", "search_research_notes",
        "get_research_note",
    }
)


def _writer_output(objective: str) -> ArtifactKind:
    lowered = str(objective).casefold()
    if any(term in lowered for term in ("outline", "大纲")):
        return ArtifactKind.OUTLINE
    if any(term in lowered for term in ("revise", "revision", "修改", "修订", "只改")):
        return ArtifactKind.REVISION
    return ArtifactKind.MANUSCRIPT_SECTION


@dataclass(frozen=True, slots=True)
class AgentSpec:
    agent_id: str
    version: str
    display_name: str
    description: str
    capabilities: frozenset[str]
    accepted_input_kinds: frozenset[ArtifactKind]
    output_kinds: frozenset[ArtifactKind]
    allowed_tools: frozenset[str]
    default_tools: tuple[str, ...]
    default_output_kind: ArtifactKind
    graph_factory: GraphFactory | None = field(default=None, compare=False, repr=False)
    temporary_graph_factory: GraphFactory | None = field(
        default=None, compare=False, repr=False
    )
    resource_class: ResourceClass = "cpu"
    retry_policy: AgentRetryPolicy = field(default_factory=AgentRetryPolicy)
    timeout_policy: AgentTimeoutPolicy = field(default_factory=AgentTimeoutPolicy)
    output_selector: OutputSelector | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        for name in (
            "capabilities", "accepted_input_kinds", "output_kinds", "allowed_tools"
        ):
            object.__setattr__(self, name, frozenset(getattr(self, name)))
        object.__setattr__(self, "default_tools", tuple(self.default_tools))
        if not self.agent_id or not self.agent_id.strip() or self.agent_id != self.agent_id.strip():
            raise ValueError("agent_id must be a nonempty stable ID")
        if not self.version.strip() or not self.display_name.strip():
            raise ValueError("version and display_name are required")
        if self.default_output_kind not in self.output_kinds:
            raise ValueError("default_output_kind must belong to output_kinds")
        if len(self.default_tools) != len(set(self.default_tools)):
            raise ValueError("default_tools must be unique")
        if not set(self.default_tools) <= self.allowed_tools:
            raise ValueError("default_tools must be allowed_tools")
        if self.resource_class not in {"cpu", "gpu", "io"}:
            raise ValueError("resource_class must be cpu, gpu, or io")

    @property
    def max_retries(self) -> int:
        return self.retry_policy.max_retries

    @property
    def timeout_seconds(self) -> float:
        return self.timeout_policy.seconds

    def output_for(self, objective: str) -> ArtifactKind:
        selected = (
            self.output_selector(objective)
            if self.output_selector is not None
            else self.default_output_kind
        )
        if selected not in self.output_kinds:
            raise ValueError(f"Agent {self.agent_id} cannot produce {selected.value}")
        return selected


class AgentRegistry:
    """A deterministic, request-local directory; registration never runs an Agent."""

    def __init__(self, specs: tuple[AgentSpec, ...] = ()) -> None:
        self._specs: dict[str, AgentSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: AgentSpec) -> None:
        if spec.agent_id in self._specs:
            raise ValueError(f"Agent already registered: {spec.agent_id}")
        self._specs[spec.agent_id] = spec

    def get(self, agent_id: str) -> AgentSpec:
        try:
            return self._specs[str(agent_id)]
        except KeyError as exc:
            raise KeyError(f"Unknown Agent: {agent_id}") from exc

    def list_agents(self) -> tuple[AgentSpec, ...]:
        return tuple(self._specs[key] for key in sorted(self._specs))

    def agent_id_for_role(self, role: TaskRole | str) -> str:
        """Compatibility adapter while TaskSpec.role is still a TaskRole enum."""

        resolved = role if isinstance(role, TaskRole) else TaskRole(str(role))
        agent_id = resolved.value
        self.get(agent_id)
        return agent_id

    def for_role(self, role: TaskRole | str) -> AgentSpec:
        return self.get(self.agent_id_for_role(role))

    def require_tools(self, agent_id: str, tool_names: list[str]) -> None:
        spec = self.get(agent_id)
        unknown = sorted(
            {
                str(name or "").strip()
                for name in tool_names
                if str(name or "").strip() not in spec.allowed_tools
            }
        )
        if unknown:
            raise ValueError(f"Agent {agent_id} is not allowed to use tools: {unknown}")

    def authorize_tool(self, agent_id: str, tool_name: str) -> AgentSpec:
        """Return the server-owned Agent spec after one Tool allowlist check."""

        name = str(tool_name or "").strip()
        if not name:
            raise ValueError("tool_name is required")
        self.require_tools(agent_id, [name])
        return self.get(agent_id)


def build_default_agent_registry(
    *,
    graph_factories: Mapping[str, GraphFactory] | None = None,
    temporary_graph_factories: Mapping[str, GraphFactory] | None = None,
) -> AgentRegistry:
    factories = dict(graph_factories or {})
    temporary_factories = dict(temporary_graph_factories or {})
    return AgentRegistry(
        (
            AgentSpec(
                agent_id="document", version="1", display_name="Document Analyst",
                description="Document understanding and bounded analysis.",
                capabilities=frozenset({"document_analysis", "reading"}),
                accepted_input_kinds=frozenset(),
                output_kinds=frozenset({ArtifactKind.DOCUMENT_ANALYSIS}),
                allowed_tools=DOCUMENT_TOOLS,
                default_tools=("inspect_reading_context", "search_knowledge_base"),
                default_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
                graph_factory=factories.get("document"),
                temporary_graph_factory=temporary_factories.get("document"),
                resource_class="io",
            ),
            AgentSpec(
                agent_id="research", version="1", display_name="Research Synthesizer",
                description="Cross-source synthesis and reviewed research.",
                capabilities=frozenset({"comparison", "research_synthesis"}),
                accepted_input_kinds=frozenset({ArtifactKind.DOCUMENT_ANALYSIS}),
                output_kinds=frozenset({ArtifactKind.COMPARISON}),
                allowed_tools=RESEARCH_TOOLS,
                default_tools=("analyze_cross_document_research", "search_knowledge_base"),
                default_output_kind=ArtifactKind.COMPARISON,
                graph_factory=factories.get("research"),
                temporary_graph_factory=temporary_factories.get("research"),
                resource_class="io",
            ),
            AgentSpec(
                agent_id="writer", version="1", display_name="Academic Writer",
                description="Evidence-backed academic writing and revision.",
                capabilities=frozenset({"outline", "draft", "revision"}),
                accepted_input_kinds=frozenset({ArtifactKind.DOCUMENT_ANALYSIS, ArtifactKind.COMPARISON}),
                output_kinds=frozenset({ArtifactKind.OUTLINE, ArtifactKind.MANUSCRIPT_SECTION, ArtifactKind.REVISION}),
                allowed_tools=WRITER_TOOLS,
                default_tools=("get_research_note", "polish_selection"),
                default_output_kind=ArtifactKind.MANUSCRIPT_SECTION,
                graph_factory=factories.get("writer"),
                temporary_graph_factory=temporary_factories.get("writer"),
                resource_class="io",
                output_selector=_writer_output,
            ),
            AgentSpec(
                agent_id="curator", version="1", display_name="Knowledge Curator",
                description="Knowledge-note and graph proposal preparation.",
                capabilities=frozenset({"knowledge_draft", "curation"}),
                accepted_input_kinds=frozenset({ArtifactKind.DOCUMENT_ANALYSIS, ArtifactKind.COMPARISON}),
                output_kinds=frozenset({ArtifactKind.KNOWLEDGE_DRAFT}),
                allowed_tools=CURATOR_TOOLS,
                default_tools=("get_research_note", "search_knowledge_base"),
                default_output_kind=ArtifactKind.KNOWLEDGE_DRAFT,
                graph_factory=factories.get("curator"),
                temporary_graph_factory=temporary_factories.get("curator"),
                resource_class="io",
            ),
        )
    )


__all__ = [
    "CURATOR_TOOLS",
    "DOCUMENT_TOOLS",
    "RESEARCH_TOOLS",
    "WRITER_TOOLS",
    "AgentRegistry",
    "AgentRetryPolicy",
    "AgentSpec",
    "AgentTimeoutPolicy",
    "build_default_agent_registry",
]
