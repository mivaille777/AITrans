from __future__ import annotations

from backend.rag.bad_cases.models import RagBadCase

SENSITIVE_FIELDS = frozenset({"query", "text", "excerpt", "answer", "quote", "context", "source_text",
                              "original_query", "rewritten_query", "rewrites", "subqueries", "retrieval_queries"})


def redact_snapshot(value):
    if isinstance(value, dict):
        return {key: ((["[redacted]"] if isinstance(item, list) else "[redacted]")
                      if key in SENSITIVE_FIELDS and not isinstance(item, dict)
                      else redact_snapshot(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_snapshot(item) for item in value]
    return value


class BadCaseStore:
    def __init__(self, debug_store):
        self.debug_store = debug_store

    def save(self, case: RagBadCase, *, retain_source: bool = False) -> str:
        identity = f"badcase:{case.case.case_id}:{case.trace_id}"
        payload = case.model_dump(mode="json")
        payload["source_redacted"] = not retain_source
        self.debug_store.save_snapshot(identity, "bad_case", payload if retain_source else redact_snapshot(payload))
        return identity

    def load(self, identity: str) -> dict | None:
        return self.debug_store.get_snapshot(identity)
