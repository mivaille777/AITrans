from __future__ import annotations

from collections.abc import Mapping

from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_tasks import TaskRole

_TRANSLATION_TERMS = ("翻译", "translate", "润色", "polish", "改写", "rewrite")
_COMPARE_TERMS = ("比较", "对比", "compare", "contrast", "综述", "review", "综合", "synthesis")
_WRITING_TERMS = ("撰写", "写作", "起草", "大纲", "章节", "draft", "outline", "write", "revise")
_CURATION_TERMS = ("笔记", "知识图谱", "知识卡", "整理", "note", "knowledge graph", "curate")
_DOCUMENT_TERMS = ("论文", "文档", "总结", "方法", "实验", "图表", "table", "figure", "paper", "summarize", "analyze")
_DIRECT_WRITE_TERMS = ("save", "保存", "存为", "添加到笔记", "add to notes")
_ACTION_ROLES = {
    "quick_read": TaskRole.DOCUMENT,
    "analyze_visuals": TaskRole.DOCUMENT,
    "compare_papers": TaskRole.RESEARCH,
    "curate_knowledge": TaskRole.CURATOR,
    "draft_section": TaskRole.WRITER,
}


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


class ResearchTaskRouter:
    """Deterministically choose direct, one-specialist, or task-DAG execution."""

    def route(
        self,
        user_input: str,
        runtime_context: Mapping[str, object] | None = None,
        *,
        mode: str = "auto",
    ) -> OrchestrationRoute:
        context = dict(runtime_context or {})
        text = " ".join(str(user_input or "").casefold().split())
        selected_text = str(context.get("source_text", "") or "").strip()
        document_ids = {
            str(item or "").strip()
            for item in context.get("knowledge_document_ids", ()) or ()
            if str(item or "").strip()
        }
        normalized_mode = str(mode or "auto").strip().lower()
        if normalized_mode == "off":
            return OrchestrationRoute(
                lane=OrchestrationLane.FAST,
                reason_code="multi_agent_disabled",
                user_visible_reason="Multi-agent execution is disabled for this request.",
            )

        workflow_action = str(context.get("workflow_action", "") or "").strip()
        explicit_role = _ACTION_ROLES.get(workflow_action)
        if explicit_role is not None:
            missing_information: list[str] = []
            if workflow_action in {"quick_read", "analyze_visuals"}:
                if not selected_text and not document_ids:
                    missing_information.append("source_required")
            elif workflow_action == "compare_papers" and len(document_ids) < 2:
                missing_information.append("at_least_two_documents")
            elif (
                workflow_action in {"curate_knowledge", "draft_section"}
                and not document_ids
                and not selected_text
            ):
                missing_information.append("source_required")
            lane = (
                OrchestrationLane.SINGLE
                if workflow_action in {"quick_read", "analyze_visuals"}
                else OrchestrationLane.WORKFLOW
            )
            return OrchestrationRoute(
                lane=lane,
                primary_role=explicit_role,
                reason_code=f"explicit_{workflow_action}",
                user_visible_reason=(
                    "The selected research action maps to a typed specialist deliverable."
                ),
                missing_information=missing_information,
            )

        if selected_text and _contains(text, _TRANSLATION_TERMS) and not (
            _contains(text, _COMPARE_TERMS)
            or _contains(text, _WRITING_TERMS)
            or _contains(text, _CURATION_TERMS)
        ):
            return OrchestrationRoute(
                lane=OrchestrationLane.FAST,
                reason_code="bounded_language_action",
                user_visible_reason="The selected text can use the existing direct language tool.",
            )

        if selected_text and _contains(text, _DIRECT_WRITE_TERMS):
            return OrchestrationRoute(
                lane=OrchestrationLane.FAST,
                reason_code="confirmed_product_write",
                user_visible_reason=(
                    "The existing product write tool owns confirmation and persistence."
                ),
            )

        role: TaskRole | None = None
        if _contains(text, _CURATION_TERMS):
            role = TaskRole.CURATOR
        elif _contains(text, _WRITING_TERMS):
            role = TaskRole.WRITER
        elif _contains(text, _COMPARE_TERMS):
            role = TaskRole.RESEARCH
        elif _contains(text, _DOCUMENT_TERMS) or document_ids or selected_text:
            role = TaskRole.DOCUMENT

        if role is None:
            return OrchestrationRoute(
                lane=OrchestrationLane.FAST,
                reason_code="canonical_agent_sufficient",
                user_visible_reason="The canonical Agent path is sufficient.",
            )

        missing_information: list[str] = []
        if (
            role is TaskRole.RESEARCH
            and _contains(text, _COMPARE_TERMS)
            and len(document_ids) < 2
            and not selected_text
        ):
            missing_information.append("at_least_two_documents")

        workflow = (
            len(document_ids) > 1
            or _contains(text, _COMPARE_TERMS)
            or (role in {TaskRole.WRITER, TaskRole.CURATOR} and bool(document_ids))
        )
        return OrchestrationRoute(
            lane=OrchestrationLane.WORKFLOW if workflow else OrchestrationLane.SINGLE,
            primary_role=role,
            reason_code="multi_source_workflow" if workflow else "single_specialist",
            user_visible_reason=(
                "The request needs an evidence-producing task graph."
                if workflow
                else f"The request maps to one {role.value} specialist."
            ),
            missing_information=missing_information,
        )


__all__ = ["ResearchTaskRouter"]
