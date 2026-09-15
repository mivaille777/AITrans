from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class AgentMessage:
    """Message exchanged between agents."""

    sender: str
    receiver: str
    message_type: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sender": self.sender,
            "receiver": self.receiver,
            "message_type": self.message_type,
            "payload": self.payload,
        }
