from __future__ import annotations

import hashlib
from typing import Any

from backend.agent_tools.base import (
    AgentToolExecutionResult,
    AgentToolInvocationContext,
    AgentToolSpec,
    TypedAgentToolDefinition,
)
from backend.agent_tools.cross_document_research import (
    CrossDocumentResearchAgentTool,
    build_cross_document_research_tool_definition,
)
from backend.agent_tools.evidence_ledger import (
    EvidenceLedgerAgentTools,
    build_evidence_ledger_tool_definitions,
)
from backend.agent_tools.knowledge import (
    KnowledgeAgentTools,
    KnowledgeChunkStore,
    build_knowledge_tool_definitions,
)
from backend.agent_tools.reading import (
    ReadingAgentTools,
    build_reading_tool_definitions,
)
from backend.agent_tools.research import (
    ResearchAgentTools,
    build_research_tool_definitions,
)
from backend.agent_tools.research_memory import (
    ResearchMemoryAgentTool,
    build_research_memory_tool_definition,
)
from backend.agent_tools.sandbox import build_python_sandbox_tool_definition
from backend.agent_tools.translation import (
    TranslationAgentTool,
    build_translation_tool_definition,
)
from backend.agent_tools.writing import (
    WritingAgentTool,
    build_writing_tool_definition,
)
from backend.knowledge.service import KnowledgeWorkspaceService
from backend.services.quick_action_service import QuickActionService
from backend.services.research_note_service import ResearchNoteService
from backend.services.translation_fallback_service import TranslationFallbackService
from backend.services.translation_service import TranslationService

_CONTEXT_FIELDS = (
    "source_text",
    "translated_text",
    "source_language",
    "target_language",
    "resource_url",
    "resource_title",
    "section_heading",
    "context_before",
    "context_after",
    "source_kind",
    "style",
    "ai_action",
    "workspace_id",
    "knowledge_document_ids",
    "knowledge_scope_allow_global",
    "request_id",
    "run_id",
    "trace_id",
    "ai_content",
    "knowledge_item_id",
    "knowledge_writeback_type",
    "knowledge_writeback_operation",
    "knowledge_relation_type",
    "memory_preferences",
)


class AgentToolRegistry:
    """Typed registry over AITranslator Agent capabilities.

    The public ``AgentToolSpec`` and successful result surfaces stay stable for
    planner, trace, HTTP, and frontend consumers. Capability families own their
    executors while the registry only assembles definitions, validates context,
    and applies the shared typed result contract.
    """

    def __init__(
        self,
        *,
        translation_service: TranslationService | Any | None = None,
        translation_fallback_service: TranslationFallbackService | Any | None = None,
        quick_action_service: QuickActionService | Any | None = None,
        research_note_service: ResearchNoteService | Any | None = None,
        research_memory_service: Any | None = None,
        cross_document_research_service: Any | None = None,
        evidence_ledger_service: Any | None = None,
        retrieval_service: Any | None = None,
        query_planner: Any | None = None,
        chunk_store: KnowledgeChunkStore | None = None,
        jit_search_read_enabled: bool = False,
        knowledge_workspace_service: KnowledgeWorkspaceService | None = None,
        sandbox_manager: Any | None = None,
    ) -> None:
        self.jit_search_read_enabled = bool(jit_search_read_enabled)
        if translation_fallback_service is not None:
            fallback_service = translation_fallback_service
        elif translation_service is None or isinstance(
            translation_service, TranslationService
        ):
            fallback_service = TranslationFallbackService()
        else:
            fallback_service = None

        shared_quick_action_service = quick_action_service or QuickActionService()
        shared_research_note_service = research_note_service or ResearchNoteService()

        translation_tool = TranslationAgentTool(
            translation_service=translation_service,
            translation_fallback_service=fallback_service,
        )
        translation_definition = build_translation_tool_definition(translation_tool)

        reading_tools = ReadingAgentTools(
            quick_action_service=shared_quick_action_service,
        )
        reading_definitions = build_reading_tool_definitions(reading_tools)
        reading_by_name = {
            definition.spec.name: definition for definition in reading_definitions
        }

        writing_tool = WritingAgentTool(
            quick_action_service=shared_quick_action_service,
        )
        writing_definition = build_writing_tool_definition(writing_tool)

        research_tools = ResearchAgentTools(
            research_note_service=shared_research_note_service,
        )
        research_definitions = build_research_tool_definitions(research_tools)
        research_memory_definitions: tuple[TypedAgentToolDefinition, ...] = ()
        if research_memory_service is not None:
            research_memory_tool = ResearchMemoryAgentTool(
                research_memory_service=research_memory_service,
                research_note_service=shared_research_note_service,
            )
            research_memory_definitions = (
                build_research_memory_tool_definition(research_memory_tool),
            )

        cross_document_definitions: tuple[TypedAgentToolDefinition, ...] = ()
        if (
            research_memory_service is not None
            and cross_document_research_service is not None
        ):
            cross_document_tool = CrossDocumentResearchAgentTool(
                cross_document_service=cross_document_research_service,
                research_memory_service=research_memory_service,
                research_note_service=shared_research_note_service,
            )
            cross_document_definitions = (
                build_cross_document_research_tool_definition(cross_document_tool),
            )

        evidence_ledger_definitions: tuple[TypedAgentToolDefinition, ...] = ()
        if research_memory_service is not None and evidence_ledger_service is not None:
            evidence_ledger_tools = EvidenceLedgerAgentTools(
                evidence_ledger_service=evidence_ledger_service,
                research_memory_service=research_memory_service,
                research_note_service=shared_research_note_service,
            )
            evidence_ledger_definitions = build_evidence_ledger_tool_definitions(
                evidence_ledger_tools
            )

        knowledge_tools = KnowledgeAgentTools(
            retrieval_service=retrieval_service,
            query_planner=query_planner,
            chunk_store=chunk_store,
            jit_search_read_enabled=self.jit_search_read_enabled,
            workspace_service=knowledge_workspace_service,
        )
        knowledge_definitions = build_knowledge_tool_definitions(knowledge_tools)
        sandbox_definitions = (
            (build_python_sandbox_tool_definition(sandbox_manager),)
            if sandbox_manager is not None
            else ()
        )

        self._definitions = (
            reading_by_name["inspect_reading_context"],
            translation_definition,
            reading_by_name["explain_selection"],
            reading_by_name["summarize_selection"],
            reading_by_name["analyze_section_role"],
            writing_definition,
            *research_definitions,
            *research_memory_definitions,
            *cross_document_definitions,
            *evidence_ledger_definitions,
            reading_by_name["define_terms"],
            reading_by_name["analyze_equation"],
            reading_by_name["summarize_current_section"],
            *knowledge_definitions,
            *sandbox_definitions,
        )
        self._definition_by_name = {
            definition.spec.name: definition for definition in self._definitions
        }

    def list_tools(self) -> tuple[AgentToolSpec, ...]:
        return tuple(definition.spec for definition in self._definitions)

    def get_tool(self, name: str) -> AgentToolSpec | None:
        definition = self._definition_by_name.get(str(name or "").strip())
        return definition.spec if definition is not None else None

    def get_definition(self, name: str) -> TypedAgentToolDefinition | None:
        return self._definition_by_name.get(str(name or "").strip())

    def validate_planner_arguments(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, str]:
        spec = self.get_tool(name)
        if spec is None:
            raise KeyError(f"Unknown agent tool: {name}")
        return spec.validate_planner_arguments(arguments)

    def trace_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Return trace-safe arguments without changing ordinary tool traces."""

        if str(tool_name).strip() != "python_execute":
            return dict(arguments or {})
        code = str((arguments or {}).get("code", "") or "")
        return {
            "code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "code_chars": len(code),
        }

    def allows_safe_retry(self, name: str) -> bool:
        definition = self.get_definition(name)
        if definition is None:
            raise KeyError(f"Unknown agent tool: {name}")
        return definition.allows_safe_retry

    @staticmethod
    def _invocation_context(payload: dict[str, Any]) -> AgentToolInvocationContext:
        candidate = {key: payload[key] for key in _CONTEXT_FIELDS if key in payload}
        return AgentToolInvocationContext.model_validate(candidate)

    @staticmethod
    def _context_payload(payload: dict[str, Any]) -> dict[str, Any]:
        return AgentToolRegistry._invocation_context(payload).reading_payload()

    def execute(self, name: str, **payload: Any) -> AgentToolExecutionResult:
        definition = self.get_definition(name)
        if definition is None:
            raise KeyError(f"Unknown agent tool: {name}")

        spec = definition.spec
        args = definition.parse_args(dict(payload))
        context = self._invocation_context(payload)
        if spec.requires_reading_context and not context.source_text.strip():
            raise ValueError(f"Agent tool {spec.name} requires selected source text.")

        result = definition.executor(context, args)
        return definition.normalize_execution_result(result)


__all__ = [
    "AgentToolExecutionResult",
    "AgentToolRegistry",
    "AgentToolSpec",
]
