from __future__ import annotations

from typing import Any

from backend.agent_core.multi_agent.base_agent import BaseAgent, AgentResult


class TranslationAgent(BaseAgent):
    """Produce a bounded translation draft through the existing translation core."""

    name = "translation"

    def __init__(self, translation_service: Any | None = None, *, max_chars: int = 2200) -> None:
        self.translation_service = translation_service
        self.max_chars = max(200, min(6000, int(max_chars)))

    @staticmethod
    def _runtime(context: Any) -> dict[str, Any]:
        value = getattr(context, "runtime", {}) if context is not None else {}
        return value if isinstance(value, dict) else {}

    def execute(self, task: str, context=None) -> AgentResult:
        runtime = self._runtime(context)
        source_text = str(runtime.get("source_text", "") or "").strip()
        source_language = str(runtime.get("source_language", "auto") or "auto")
        target_language = str(runtime.get("target_language", "zh-CN") or "zh-CN")
        draft_source = source_text[: self.max_chars]

        translated_text = ""
        provider = ""
        degraded = self.translation_service is None or not draft_source
        if self.translation_service is not None and draft_source:
            try:
                result = self.translation_service.translate(
                    draft_source,
                    source_language=source_language,
                    target_language=target_language,
                    request_id=0,
                )
                translated_text = str(getattr(result, "translated_text", "") or "")
                provider = str(getattr(result, "provider", "") or "")
                degraded = not bool(translated_text)
            except Exception:
                degraded = True

        return AgentResult(
            agent_name=self.name,
            output={
                "task": str(task or "").strip(),
                "source_excerpt": draft_source,
                "translated_draft": translated_text[:4000],
                "source_language": source_language,
                "target_language": target_language,
            },
            metadata={
                "role": "translation",
                "provider": provider,
                "source_chars": len(draft_source),
                "translated_chars": len(translated_text),
                "degraded": degraded,
            },
        )


__all__ = ["TranslationAgent"]
