"""Read-only projection of the actual typed registry, with stable catalog paging."""

from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter
from typing import Any

from backend.models.tool_management import ToolCatalog, ToolDetail, ToolSummary


class ToolManagementError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 422, fields=None):
        super().__init__(message)
        self.code, self.status, self.fields = code, status, fields or []

    def detail(self):
        return {"code": self.code, "message": str(self), "field_errors": self.fields}


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


class ToolManagementService:
    def __init__(self, registry, policy=None):
        self.registry = registry
        self.policy = policy or getattr(registry, "tool_policy", None)

    def detail(self, tool_id: str) -> ToolDetail:
        name = tool_id.removeprefix("builtin:")
        if not tool_id.startswith("builtin:"):
            raise ToolManagementError("tool_not_found", "Tool was not found.", 404)
        definition = self.registry.get_definition(name)
        if definition is None:
            raise ToolManagementError("tool_not_found", "Tool was not found.", 404)
        spec = definition.spec
        requirements = []
        if spec.requires_reading_context:
            requirements.append("reading_context")
        if spec.category == "knowledge":
            requirements.append("knowledge_scope")
        if name in {"python_execute", "command_execute"}:
            requirements.extend(["filesystem_workspace", "sandbox"])
        owner = getattr(definition.executor, "__self__", None)
        reason = ""
        if (
            name == "search_knowledge_base"
            and owner is not None
            and getattr(owner, "_retrieval_service", None) is None
        ):
            reason = "Knowledge retrieval is unavailable."
        if (
            name in {"read_knowledge_chunk", "read_knowledge_section"}
            and owner is not None
            and getattr(owner, "_chunk_store", None) is None
        ):
            reason = "Knowledge chunk storage is unavailable."
        profiles = {}
        # Same invocation name can have a stricter native Chat parameter model.
        if spec.category == "knowledge":
            from backend.services.knowledge_function_calling import _MODELS

            if name in _MODELS:
                profiles["native_chat"] = _MODELS[name].model_json_schema()
        schema = definition.args_model.model_json_schema()
        output = definition.result_model.model_json_schema()
        examples = self._examples(name, schema, definition.args_model)
        revision = fingerprint([spec.tool_version, schema, output, spec.description])
        settings = (
            self.policy.repository.settings(tool_id)
            if self.policy
            else {"enabled": True, "revision": 0, "updated_at": None}
        )
        enabled = bool(settings["enabled"])
        return ToolDetail(
            tool_id=tool_id,
            name=name,
            title=spec.title,
            description=spec.description,
            category=spec.category,
            effect=spec.effect,
            available=not reason,
            enabled=enabled,
            effective_enabled=enabled and not reason,
            unavailable_reason=reason,
            risk_level="confirmation_required"
            if spec.requires_confirmation
            else "unknown",
            tool_version=spec.tool_version,
            revision=revision + "." + str(settings["revision"]),
            input_schema=schema,
            output_schema=output,
            input_profiles=profiles,
            context_requirements=requirements,
            permissions={
                "requires_confirmation": spec.requires_confirmation,
                "effect": spec.effect,
                "source": "typed executor definition",
                "knowledge_access": "explicit document scope"
                if "knowledge_scope" in requirements
                else "not declared",
                "filesystem_access": "sandbox workspace policy"
                if "filesystem_workspace" in requirements
                else "not declared",
                "network_access": "sandbox network policy"
                if name == "command_execute"
                else "not declared",
            },
            limits={
                "timeout_seconds": spec.timeout_seconds,
                "parallel_safe": spec.parallel_safe,
                "idempotent": spec.idempotent,
                "retry_policy": definition.retry_policy,
            },
            examples=examples,
            execution_capabilities={
                "supports_output_stream": False,
                "supports_cancel": True,
                "cancel_stops_executor": False,
                "supports_test": True,
            },
            editable_fields=["enabled"],
            updated_at=settings["updated_at"],
        )

    def update(self, tool_id, payload):
        current = self.detail(tool_id)
        if payload.revision != current.revision:
            raise ToolManagementError(
                "revision_conflict",
                "Tool configuration changed. Reload and retry.",
                409,
            )
        if self.policy is None:
            raise ToolManagementError(
                "policy_unavailable", "Tool policy is unavailable.", 503
            )
        self.policy.update(
            tool_id, int(current.revision.rsplit(".", 1)[1]), payload.enabled
        )
        return self.detail(tool_id)

    @staticmethod
    def _examples(name, schema, model):
        candidates = [{}]
        if name == "search_knowledge_base" or name == "search_research_notes":
            candidates = [{"query": "AI agent framework", "top_k": 5}]
        elif "query" in schema.get("required", []):
            candidates = [{"query": "AI agent framework"}]
        examples = []
        for candidate in candidates:
            try:
                model.model_validate(candidate, strict=True)
            except ValueError:
                continue
            examples.append(
                {
                    "id": "basic",
                    "title": "Basic example",
                    "arguments": candidate,
                    "description": "Supply the required context before running.",
                }
            )
        return examples

    def list(
        self, q="", category="", status="all", limit=100, cursor=None
    ) -> ToolCatalog:
        if status not in {"all", "enabled", "disabled"} or not 1 <= limit <= 200:
            raise ToolManagementError("invalid_filter", "Invalid catalog filter.")
        details = [
            self.detail("builtin:" + spec.name)
            for spec in (
                self.registry.list_all_tools()
                if hasattr(self.registry, "list_all_tools")
                else self.registry.list_tools()
            )
        ]
        details.sort(key=lambda item: (item.category, item.name))
        revision = fingerprint([item.model_dump() for item in details])
        query = q.strip().casefold()
        matched = [
            item
            for item in details
            if (
                not query
                or query in f"{item.name} {item.title} {item.description}".casefold()
            )
            and (not category or item.category == category)
            and (status == "all" or item.enabled == (status == "enabled"))
        ]
        binding = fingerprint([revision, query, category, status])
        offset = 0
        if cursor:
            try:
                value = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                offset = value["offset"]
                if value["binding"] != binding:
                    raise ToolManagementError(
                        "stale_cursor", "Catalog changed; restart paging.", 409
                    )
                if not isinstance(offset, int) or offset < 0:
                    raise ValueError()
            except (ValueError, KeyError, TypeError) as exc:
                raise ToolManagementError(
                    "invalid_cursor", "Invalid catalog cursor."
                ) from exc
        end = offset + limit
        next_cursor = (
            base64.urlsafe_b64encode(
                json.dumps({"offset": end, "binding": binding}).encode()
            ).decode()
            if end < len(matched)
            else None
        )
        items = [
            ToolSummary.model_validate(
                item.model_dump(include=set(ToolSummary.model_fields))
            )
            for item in matched[offset:end]
        ]
        enabled = sum(item.enabled for item in details)
        return ToolCatalog(
            items=items,
            categories=dict(Counter(item.category for item in matched)),
            total=len(details),
            enabled=enabled,
            disabled=len(details) - enabled,
            matched_total=len(matched),
            next_cursor=next_cursor,
            catalog_revision=revision,
        )
