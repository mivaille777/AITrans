from __future__ import annotations

from dataclasses import dataclass

from backend.models.agent_tasks import TaskRole


DOCUMENT_TOOLS = frozenset(
    {
        "inspect_reading_context",
        "explain_selection",
        "summarize_selection",
        "analyze_section_role",
        "define_terms",
        "analyze_equation",
        "summarize_current_section",
        "search_knowledge_base",
    }
)

RESEARCH_TOOLS = frozenset(
    {
        "search_knowledge_base",
        "list_research_notes",
        "search_research_notes",
        "get_research_note",
        "analyze_cross_document_research",
    }
)

WRITER_TOOLS = frozenset(
    {
        "inspect_reading_context",
        "search_knowledge_base",
        "get_research_note",
        "translate_selection",
        "polish_selection",
    }
)

CURATOR_TOOLS = frozenset(
    {
        "search_knowledge_base",
        "list_research_notes",
        "search_research_notes",
        "get_research_note",
    }
)


@dataclass(frozen=True, slots=True)
class RoleSpec:
    role: TaskRole
    allowed_tools: frozenset[str]
    description: str


@dataclass(frozen=True, slots=True)
class LegacyRoleResolution:
    legacy_name: str
    role: TaskRole
    capability_only: bool = False


class RoleRegistry:
    def __init__(self, roles: tuple[RoleSpec, ...] | None = None) -> None:
        defaults = roles or (
            RoleSpec(TaskRole.DOCUMENT, DOCUMENT_TOOLS, "Document understanding and bounded analysis."),
            RoleSpec(TaskRole.RESEARCH, RESEARCH_TOOLS, "Cross-source synthesis and reviewed research."),
            RoleSpec(TaskRole.WRITER, WRITER_TOOLS, "Evidence-backed academic writing and revision."),
            RoleSpec(TaskRole.CURATOR, CURATOR_TOOLS, "Knowledge-note and graph proposal preparation."),
        )
        self._roles = {item.role: item for item in defaults}
        self._legacy = {
            "reading": LegacyRoleResolution("reading", TaskRole.DOCUMENT),
            "research": LegacyRoleResolution("research", TaskRole.RESEARCH),
            "translation": LegacyRoleResolution(
                "translation",
                TaskRole.WRITER,
                capability_only=True,
            ),
        }

    def get(self, role: TaskRole | str) -> RoleSpec:
        resolved = role if isinstance(role, TaskRole) else TaskRole(str(role))
        try:
            return self._roles[resolved]
        except KeyError as exc:
            raise KeyError(f"Unknown multi-agent role: {resolved.value}") from exc

    def is_tool_allowed(self, role: TaskRole | str, tool_name: str) -> bool:
        return str(tool_name or "").strip() in self.get(role).allowed_tools

    def require_tools(self, role: TaskRole | str, tool_names: list[str]) -> None:
        spec = self.get(role)
        unknown = sorted(
            {
                str(name or "").strip()
                for name in tool_names
                if str(name or "").strip() not in spec.allowed_tools
            }
        )
        if unknown:
            raise ValueError(
                f"Role {spec.role.value} is not allowed to use tools: {unknown}"
            )

    def adapt_legacy(self, legacy_name: str) -> LegacyRoleResolution:
        key = str(legacy_name or "").strip().lower()
        try:
            return self._legacy[key]
        except KeyError as exc:
            raise KeyError(f"Unknown legacy Agent role: {legacy_name}") from exc

    def roles(self) -> tuple[RoleSpec, ...]:
        return tuple(self._roles[key] for key in sorted(self._roles, key=lambda item: item.value))


__all__ = [
    "CURATOR_TOOLS",
    "DOCUMENT_TOOLS",
    "LegacyRoleResolution",
    "RESEARCH_TOOLS",
    "RoleRegistry",
    "RoleSpec",
    "WRITER_TOOLS",
]
