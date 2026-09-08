from typing import Dict, List

from .message import AgentMessage


class CollaborationProtocol:
    """Basic communication layer between specialized agents."""

    def __init__(self):
        self.messages: List[AgentMessage] = []

    def send(self, message: AgentMessage) -> Dict:
        self.messages.append(message)
        return message.to_dict()

    def history(self) -> List[Dict]:
        return [message.to_dict() for message in self.messages]
