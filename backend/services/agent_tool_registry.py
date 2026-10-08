from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from backend.agent_tools.base import (
    AgentToolExecutionResult,
    AgentToolInvocationContext,
    AgentToolSpec,
    TypedAgentToolDefinition,
)
from backend.agent_tools.command import build_command_execute_tool_definition
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
    "filesystem_workspace_id",
    "filesystem_access",
    "session_id",
    "tool_call_id",
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


def _validate_external_definition(definition: TypedAgentToolDefinition) -> None:
    if not isinstance(definition, TypedAgentToolDefinition):
        raise TypeError("external agent tools must be TypedAgentToolDefinition values")
    spec = definition.spec
    name = str(spec.name or "")
    if not name.strip() or name != name.strip():
        raise ValueError("external agent tool name must be nonempty and trimmed")
    if not callable(definition.executor):
        raise TypeError(f"external agent tool {name} requires an executor")
    if (
        not isinstance(definition.args_model, type)
        or not issubclass(definition.args_model, BaseModel)
        or not isinstance(definition.result_model, type)
        or not issubclass(definition.result_model, BaseModel)
    ):
        raise TypeError(f"external agent tool {name} requires typed input and result models")
    if not isinstance(spec.input_schema, dict):
        raise TypeError(f"external agent tool {name} has an invalid input schema")
    try:
        json.dumps(spec.input_schema, ensure_ascii=False, allow_nan=False)
        definition.args_model.model_json_schema()
        definition.result_model.model_json_schema()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"external agent tool {name} has an invalid schema") from exc
    for argument, schema in spec.input_schema.items():
        if (
            not isinstance(argument, str)
            or not argument.strip()
            or argument != argument.strip()
            or argument not in definition.args_model.model_fields
            or not isinstance(schema, dict)
        ):
            raise ValueError(f"external agent tool {name} has an invalid schema")
        value_type = schema.get("type")
        if value_type is not None and not (
            isinstance(value_type, str)
            and value_type
            in {"array", "boolean", "integer", "number", "object", "string"}
            or isinstance(value_type, list)
            and all(
                item
                in {"array", "boolean", "integer", "number", "object", "string"}
                for item in value_type
            )
        ):
            raise ValueError(f"external agent tool {name} has an invalid schema")
    if spec.effect == "write" and not spec.requires_confirmation:
        raise ValueError(f"external write tool {name} requires confirmation")


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
        knowledge_library_service: Any | None = None,
        knowledge_workspace_service: KnowledgeWorkspaceService | None = None,
        sandbox_manager: Any | None = None,
        filesystem_workspace_service: Any | None = None,
        workspace_file_service: Any | None = None,
        sandbox_debug_service: Any | None = None,
        sandbox_network_permission_service: Any | None = None,
        external_tool_definitions: Iterable[TypedAgentToolDefinition] = (),
        tool_policy: Any | None = None,
    ) -> None:
        self.tool_policy = tool_policy
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
        from backend.services.tool_result_validator import ToolResultValidator
        from backend.services.chat_session_service import ChatSessionService
        self.result_validator = ToolResultValidator(
            filesystem=(lambda: ChatSessionService(filesystem_workspace_service)) if filesystem_workspace_service else None,
            research=shared_research_note_service, library=knowledge_library_service,
            workspace=knowledge_workspace_service,
            chunks=chunk_store,
        )
        self.workspace_files = None
        if filesystem_workspace_service is not None:
            from backend.services.workspace_file_service import WorkspaceFileService
            self.workspace_files = workspace_file_service or WorkspaceFileService(filesystem_workspace_service)
            self.result_validator.workspace_files = self.workspace_files

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
            tool_policy=tool_policy,
            retrieval_service=retrieval_service,
            query_planner=query_planner,
            chunk_store=chunk_store,
            jit_search_read_enabled=self.jit_search_read_enabled,
            workspace_service=knowledge_workspace_service,
            library_service=knowledge_library_service,
        )
        knowledge_definitions = build_knowledge_tool_definitions(knowledge_tools)
        sandbox_definitions = (
            (
                build_python_sandbox_tool_definition(
                    sandbox_manager,
                    filesystem_workspace_service=filesystem_workspace_service,
                    sandbox_debug_service=sandbox_debug_service,
                ),
                build_command_execute_tool_definition(
                    sandbox_manager,
                    filesystem_workspace_service=filesystem_workspace_service,
                    network_permission_service=sandbox_network_permission_service,
                    sandbox_debug_service=sandbox_debug_service,
                ),
            )
            if sandbox_manager is not None
            else ()
        )

        built_in_definitions = (
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
        definitions = list(built_in_definitions)
        from backend.agent_tools.markdown_export import build_markdown_export_definition
        definitions.append(build_markdown_export_definition())
        if filesystem_workspace_service is not None:
            from backend.agent_tools.chat_files import build_read_workspace_file_definition
            from backend.services.chat_session_service import ChatSessionService
            definitions.append(build_read_workspace_file_definition(lambda: ChatSessionService(filesystem_workspace_service)))
            from backend.agent_tools.workspace_files import build_workspace_file_definitions
            definitions.extend(build_workspace_file_definitions(self.workspace_files))
        known_names = {item.spec.name for item in definitions}
        for definition in external_tool_definitions:
            _validate_external_definition(definition)
            name = definition.spec.name
            if name in known_names:
                raise ValueError(f"Duplicate agent tool definition: {name}")
            known_names.add(name)
            definitions.append(definition)
        self._definitions = tuple(definitions)
        self._definition_by_name = {
            definition.spec.name: definition for definition in self._definitions
        }

    def list_tools(self) -> tuple[AgentToolSpec, ...]:
        return tuple(spec for spec in self.list_all_tools() if self.tool_policy is None or self.tool_policy.is_enabled(spec.name))

    def list_all_tools(self) -> tuple[AgentToolSpec, ...]:
        names = [definition.spec.name for definition in self._definitions]
        if self.tool_policy is not None:
            names.extend(row["name"] for row in self.tool_policy.repository.custom_tools())
        return tuple(definition.spec for name in names if (definition := self.get_definition(name)) is not None)

    def get_tool(self, name: str) -> AgentToolSpec | None:
        definition = self.get_definition(name)
        return definition.spec if definition is not None else None

    def primitive_name(self, name: str) -> str:
        custom = self.tool_policy.repository.custom(name) if self.tool_policy else None
        return custom["preset"]["template_id"].removeprefix("builtin:") if custom else name

    def get_definition(self, name: str) -> TypedAgentToolDefinition | None:
        name = str(name or "").strip()
        definition = self._definition_by_name.get(name)
        if self.tool_policy is None:
            return definition
        if definition is not None:
            import json
            from backend.services.tool_configuration import metadata_definition
            config = json.loads(self.tool_policy.repository.settings("builtin:" + name)["config_json"])
            return metadata_definition(definition, config) if config else definition
        custom = self.tool_policy.repository.custom(name)
        if custom and not custom["archived"]:
            from backend.services.tool_configuration import preset_definition
            return preset_definition(self, custom["preset"])
        return None

    def validate_planner_arguments(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        spec = self.get_tool(name)
        if spec is None:
            raise KeyError(f"Unknown agent tool: {name}")
        return spec.validate_planner_arguments(arguments)

    def verify_result(self, name, payload, result):
        primitive = self.primitive_name(name)
        custom = self.tool_policy.repository.custom(name) if self.tool_policy else None
        arguments = {**(custom["preset"]["fixed_arguments"] if custom else {}), **payload}
        from backend.services.workspace_file_service import FILE_TOOLS
        if primitive in FILE_TOOLS:
            arguments.update(self.workspace_file_arguments(name, payload))
        return self.result_validator.verify(primitive, arguments, result)

    def workspace_file_arguments(self, name, payload):
        definition = self.get_definition(name)
        custom = self.tool_policy.repository.custom(name) if self.tool_policy else None
        fixed = custom["preset"]["fixed_arguments"] if custom else {}
        return {**fixed, **definition.parse_args(payload).model_dump(mode="json")}

    def availability(self, name, *, payload=None):
        definition = self.get_definition(name)
        if definition is None:
            return False, "工具不存在或已归档。"
        if self.tool_policy and not self.tool_policy.is_enabled(name):
            return False, "工具已禁用。"
        primitive = self.primitive_name(name)
        owner = getattr(definition.executor, "__self__", None)
        if primitive == "search_knowledge_base" and owner and getattr(owner, "_retrieval_service", None) is None:
            return False, "知识检索服务不可用。"
        if primitive in {"read_knowledge_chunk", "read_knowledge_section"} and owner and getattr(owner, "_chunk_store", None) is None:
            return False, "知识片段存储不可用。"
        if payload is not None:
            from backend.services.workspace_file_service import FILE_TOOLS, FILE_WRITE_TOOLS
            if definition.spec.requires_reading_context and not str(payload.get("source_text", "")).strip():
                return False, "缺少阅读内容。"
            if primitive in FILE_TOOLS | {"read_workspace_file"} and not payload.get("filesystem_workspace_id"):
                return False, "请先选择工作区。"
            if primitive in FILE_WRITE_TOOLS and payload.get("filesystem_access", "read_only") != "read_write":
                return False, "当前工作区为只读。"
            if primitive in {"list_knowledge_documents", "search_knowledge_base", "read_knowledge_chunk", "read_knowledge_section"} and str(payload.get("knowledge_access_policy", "auto")) == "never":
                return False, "当前会话已关闭知识检索。"
        return True, ""

    def trace_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Return trace-safe arguments without changing ordinary tool traces."""

        name = str(tool_name).strip()
        if name == "python_execute":
            code = str((arguments or {}).get("code", "") or "")
            return {
                "code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
                "code_chars": len(code),
            }
        if name == "command_execute":
            argv = (arguments or {}).get("argv", [])
            encoded = json.dumps(argv, ensure_ascii=False, separators=(",", ":"))
            return {
                "argv_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                "argv_count": len(argv) if isinstance(argv, list) else 0,
                "argv_chars": len(encoded),
            }
        return dict(arguments or {})

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
        if self.tool_policy is not None:
            self.tool_policy.assert_enabled(name)
            custom = self.tool_policy.repository.custom(name)
            if custom and set(payload) & set(custom["preset"]["fixed_arguments"]):
                raise ValueError("Fixed preset arguments cannot be supplied by callers.")
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
