"""TaskRole compatibility facade over the LG01 Agent Registry."""

from __future__ import annotations

from dataclasses import dataclass, replace

from backend.agent_core.orchestration.agent_registry import (
    CURATOR_TOOLS,
    DOCUMENT_TOOLS,
    RESEARCH_TOOLS,
    WRITER_TOOLS,
    AgentRegistry,
    build_default_agent_registry,
)
from backend.models.agent_tasks import TaskRole


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
    def __init__(
        self,
        roles: tuple[RoleSpec, ...] | None = None,
        *,
        agent_registry: AgentRegistry | None = None,
    ) -> None:
        if roles is not None and agent_registry is not None:
            raise ValueError("Provide roles or agent_registry, not both")
        if roles:
            defaults = build_default_agent_registry()
            self.agent_registry = AgentRegistry(
                tuple(
                    replace(
                        defaults.for_role(item.role),
                        allowed_tools=item.allowed_tools,
                        default_tools=tuple(
                            tool
                            for tool in defaults.for_role(item.role).default_tools
                            if tool in item.allowed_tools
                        ),
                        description=item.description,
                    )
                    for item in roles
                )
            )
        else:
            self.agent_registry = agent_registry or build_default_agent_registry()
        self._legacy = {
            "reading": LegacyRoleResolution("reading", TaskRole.DOCUMENT),
            "research": LegacyRoleResolution("research", TaskRole.RESEARCH),
            "translation": LegacyRoleResolution(
                "translation", TaskRole.WRITER, capability_only=True
            ),
        }

    def get(self, role: TaskRole | str) -> RoleSpec:
        resolved = role if isinstance(role, TaskRole) else TaskRole(str(role))
        try:
            spec = self.agent_registry.for_role(resolved)
        except KeyError as exc:
            raise KeyError(f"Unknown multi-agent role: {resolved.value}") from exc
        return RoleSpec(resolved, spec.allowed_tools, spec.description)

    def is_tool_allowed(self, role: TaskRole | str, tool_name: str) -> bool:
        return str(tool_name or "").strip() in self.get(role).allowed_tools

    def require_tools(self, role: TaskRole | str, tool_names: list[str]) -> None:
        agent_id = self.agent_registry.agent_id_for_role(role)
        self.agent_registry.require_tools(agent_id, tool_names)

    def adapt_legacy(self, legacy_name: str) -> LegacyRoleResolution:
        key = str(legacy_name or "").strip().lower()
        try:
            return self._legacy[key]
        except KeyError as exc:
            raise KeyError(f"Unknown legacy Agent role: {legacy_name}") from exc

    def roles(self) -> tuple[RoleSpec, ...]:
        known_roles = {role.value: role for role in TaskRole}
        return tuple(
            self.get(known_roles[spec.agent_id])
            for spec in self.agent_registry.list_agents()
            if spec.agent_id in known_roles
        )


__all__ = [
    "CURATOR_TOOLS",
    "DOCUMENT_TOOLS",
    "RESEARCH_TOOLS",
    "WRITER_TOOLS",
    "LegacyRoleResolution",
    "RoleRegistry",
    "RoleSpec",
]
