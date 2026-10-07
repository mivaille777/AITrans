"""Atomic custom configuration creation/import/archive, without executable imports."""

import json
from datetime import UTC, datetime

from backend.services.tool_configuration import preset_definition
from backend.services.tool_management_service import ToolManagementError, fingerprint


class ToolCustomService:
    def __init__(self, management):
        self.management = management
        if management.policy is None:
            raise ToolManagementError(
                "policy_unavailable", "Tool policy is unavailable.", 503
            )
        self.repository = management.policy.repository

    def create(self, preset):
        raw = preset.model_dump()
        preset_definition(self.management.registry, raw)
        with self.repository.transaction() as db:
            if db.execute(
                "SELECT 1 FROM custom_tools WHERE name=?", (preset.name,)
            ).fetchone() or self.management.registry._definition_by_name.get(
                preset.name
            ):
                raise ToolManagementError(
                    "name_conflict", "This call name already exists.", 409
                )
            tool_id = self.repository.insert_custom(db, raw)
        return self.management.detail(tool_id)

    def _validate_import(self, document):
        if document.schema_version != 1:
            raise ToolManagementError(
                "import_version", "Only schema_version 1 is supported."
            )
        names = [item.name for item in document.tools]
        if len(set(names)) != len(names):
            raise ToolManagementError(
                "import_duplicate", "Duplicate call names in import."
            )
        for item in document.tools:
            preset_definition(self.management.registry, item.model_dump())

    def preview(self, document):
        self._validate_import(document)
        with self.repository.transaction() as db:
            token = fingerprint([document.model_dump(), self.repository.state(db)])
            existing = {
                row[0]: row[1]
                for row in db.execute("SELECT name,archived FROM custom_tools")
            }
        conflicts = [
            {"name": item.name, "archived": bool(existing[item.name])}
            for item in document.tools
            if item.name in existing
        ]
        return {
            "preview_token": token,
            "items": [
                {
                    "name": x.name,
                    "template_id": x.template_id,
                    "effect": "read",
                    "enabled": False,
                }
                for x in document.tools
            ],
            "conflicts": conflicts,
            "message": "All imported tools are disabled. Existing names require explicit replace; archived names cannot be reused.",
        }

    def apply(self, request):
        self._validate_import(request.document)
        ids = []
        with self.repository.transaction() as db:
            if request.preview_token != fingerprint(
                [request.document.model_dump(), self.repository.state(db)]
            ):
                raise ToolManagementError(
                    "preview_stale",
                    "Configuration changed since preview. Preview again.",
                    409,
                )
            for item in request.document.tools:
                existing = db.execute(
                    "SELECT tool_id,archived FROM custom_tools WHERE name=?",
                    (item.name,),
                ).fetchone()
                raw = item.model_dump()
                if existing:
                    if existing[1] or request.conflict_mode != "replace":
                        raise ToolManagementError(
                            "import_conflict",
                            "Resolve conflicting or archived names before import.",
                            409,
                        )
                    tool_id = existing[0]
                    db.execute(
                        "UPDATE custom_tools SET preset_json=? WHERE tool_id=?",
                        (json.dumps(raw), tool_id),
                    )
                    db.execute(
                        "UPDATE tool_settings SET enabled=0,revision=revision+1,updated_at=? WHERE tool_id=?",
                        (datetime.now(UTC).isoformat(), tool_id),
                    )
                else:
                    tool_id = self.repository.insert_custom(db, raw)
                ids.append(tool_id)
        return {"items": [self.management.detail(id).model_dump() for id in ids]}

    def archive(self, tool_id, revision):
        tool = self.management.detail(tool_id)
        if tool.origin != "custom":
            raise ToolManagementError(
                "builtin_archive", "Built-in tools cannot be archived."
            )
        if tool.revision != revision or tool.archived:
            raise ToolManagementError(
                "revision_conflict", "Tool changed or is already archived.", 409
            )
        with self.repository.transaction() as db:
            row = db.execute(
                "SELECT revision FROM tool_settings WHERE tool_id=?", (tool_id,)
            ).fetchone()
            if row[0] != int(revision.rsplit(".", 1)[1]):
                raise ToolManagementError("revision_conflict", "Tool changed.", 409)
            db.execute("UPDATE custom_tools SET archived=1 WHERE tool_id=?", (tool_id,))
            db.execute(
                "UPDATE tool_settings SET enabled=0,revision=revision+1,updated_at=? WHERE tool_id=?",
                (datetime.now(UTC).isoformat(), tool_id),
            )
        return self.management.detail(tool_id)
