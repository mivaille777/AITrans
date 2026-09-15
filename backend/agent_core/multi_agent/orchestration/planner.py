from typing import Any, Dict, List


class AgentPlanner:
    """Create executable task plans for the supervisor workflow."""

    _research_keywords = (
        "paper",
        "research",
        "literature",
        "论文",
        "研究",
        "文献",
    )
    _reading_keywords = (
        "read",
        "analyze",
        "analysis",
        "summary",
        "summarize",
        "阅读",
        "分析",
        "总结",
        "概括",
    )
    _translation_keywords = (
        "translate",
        "translation",
        "翻译",
        "译文",
    )

    def create_plan(self, task: str, context: Any = None) -> List[Dict[str, Any]]:
        del context
        plan = []
        lowered = task.lower()

        if any(keyword in lowered for keyword in self._research_keywords):
            plan.append({
                "agent": "research",
                "task": task,
            })

        if any(keyword in lowered for keyword in self._reading_keywords):
            plan.append({
                "agent": "reading",
                "task": task,
            })

        if any(keyword in lowered for keyword in self._translation_keywords):
            plan.append({
                "agent": "translation",
                "task": task,
            })

        if not plan:
            plan.append({
                "agent": "research",
                "task": task,
            })

        return plan
