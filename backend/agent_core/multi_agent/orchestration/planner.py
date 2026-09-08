from typing import Any, Dict, List


class AgentPlanner:
    """Create executable task plans for the supervisor workflow."""

    def create_plan(self, task: str, context: Any = None) -> List[Dict[str, Any]]:
        plan = []

        lowered = task.lower()

        if any(k in lowered for k in ["paper", "research", "literature"]):
            plan.append({
                "agent": "research",
                "task": task,
            })

        if any(k in lowered for k in ["read", "analyze", "summary", "summarize"]):
            plan.append({
                "agent": "reading",
                "task": task,
            })

        if any(k in lowered for k in ["translate", "translation", "翻译"]):
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
