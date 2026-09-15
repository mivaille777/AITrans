from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class AgentTask:
    """Task assigned to an agent by supervisor."""

    task_id: str
    agent_name: str
    description: str
    metadata: Dict[str, Any] = field(default_factory=dict)
