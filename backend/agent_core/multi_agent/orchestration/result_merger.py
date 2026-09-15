from typing import Any, Dict, List


class AgentResultMerger:
    """Merge outputs from multiple agents into a unified response."""

    def merge(self, results: List[Any]) -> Dict[str, Any]:
        merged = {
            "agents": [],
            "results": [],
        }

        for result in results:
            name = getattr(result, "agent_name", None)
            if name:
                merged["agents"].append(name)
            merged["results"].append(result)

        return merged
