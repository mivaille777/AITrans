"""One persistent capability policy shared by registry and native knowledge calls."""

from functools import lru_cache

from backend.services.tool_management_repository import ToolManagementRepository
from backend.services.tool_management_service import ToolManagementError


class ToolPolicyService:
    def __init__(self, repository=None):
        self.repository = repository or ToolManagementRepository()

    def is_enabled(self, name: str) -> bool:
        tool_id = name if ":" in name else "builtin:" + name
        return bool(self.repository.settings(tool_id)["enabled"])

    def assert_enabled(self, name: str):
        if not self.is_enabled(name):
            raise PermissionError(f"Tool {name} is disabled in Tools management.")

    def update(self, tool_id: str, revision: int, enabled: bool):
        if not isinstance(enabled, bool):
            raise ToolManagementError("invalid_enabled", "enabled must be boolean.")
        self.repository.update(tool_id, revision, enabled=enabled)


@lru_cache(maxsize=1)
def get_tool_policy_service():
    return ToolPolicyService()
