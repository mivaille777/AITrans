"""Real localhost API smoke against an explicitly isolated AITrans data directory.

Run tools_management_acceptance_server.py with disposable data first.
This imports authored fixtures and invokes real tools. The isolated server must
disable optional LLM rewriting and use already-cached offline models.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8772")
    parser.add_argument(
        "--acknowledge-isolated-data", action="store_true", required=True
    )
    parser.add_argument(
        "--report", type=Path, default=Path("test-results/tools-management-live.json")
    )
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.scheme != "http"
    ):
        parser.error("Only a localhost HTTP backend is supported.")
    root = Path(__file__).resolve().parent.parent
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "source": "real localhost API; authored Markdown; configured local embedding runtime",
        "checks": [],
        "runs": [],
    }
    originals = {}

    def call(method, path, body=None, *, expected=200, timeout=120):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(
            args.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                status, payload = response.status, json.load(response)
        except HTTPError as exc:
            status, payload = exc.code, json.load(exc)
        if status != expected:
            raise RuntimeError(
                f"{method} {path}: expected {expected}, received {status}: {payload}"
            )
        return payload

    def check(label):
        report["checks"].append(label)
        print("PASS:", label, flush=True)

    def tool_path(id):
        return "/api/tools/" + quote(id, safe="")

    def enabled(id, value):
        detail = call("GET", tool_path(id))
        return call(
            "PATCH", tool_path(id), {"revision": detail["revision"], "enabled": value}
        )

    def body(arguments=None, documents=None, reading=None):
        return {
            "client_request_id": "acceptance_" + uuid4().hex,
            "arguments": arguments or {},
            "context_selection": {
                "knowledge_document_ids": documents or [],
                "reading_context": reading or {},
            },
            "timeout_seconds": 30,
            "stream_output": False,
        }

    def wait(id, run):
        until = monotonic() + 45
        while monotonic() < until:
            current = call(
                "GET", tool_path(id) + "/test-runs/" + run["test_run_id"], timeout=10
            )
            if current["finished_at"]:
                if current["status"] != "succeeded":
                    raise RuntimeError(
                        f"Test failed: {current['status']}: {current['error']}"
                    )
                report["runs"].append(
                    {
                        key: current[key]
                        for key in (
                            "test_run_id",
                            "tool_id",
                            "trace_id",
                            "tool_call_id",
                            "status",
                            "execution_state",
                            "elapsed_ms",
                        )
                    }
                )
                return current
            sleep(0.2)
        raise TimeoutError("Test did not finish in the bounded acceptance window.")

    def run(id, request):
        created = call("POST", tool_path(id) + "/test-runs", request, expected=202)
        return wait(id, created)

    try:
        for id in ("builtin:inspect_reading_context", "builtin:search_knowledge_base"):
            originals[id] = call("GET", tool_path(id))["enabled"]
            enabled(id, True)
        documents = []
        for name in ("tools-acceptance-agent.md", "tools-acceptance-control.md"):
            imported = call(
                "POST",
                "/api/knowledge/documents",
                {"path": str(root / "docs/development/fixtures" / name)},
                expected=201,
            )
            document = imported["document"]
            assert document["status"] == "ready" and document["chunk_count"] > 0
            documents.append(document["document_id"])
            report.setdefault("documents", []).append(
                {
                    key: document[key]
                    for key in (
                        "document_id",
                        "chunk_count",
                        "embedding_model",
                        "embedding_dimension",
                    )
                }
            )
        check(
            "Two authored Markdown documents indexed by the configured embedding runtime"
        )
        id = "builtin:search_knowledge_base"
        scoped = body(
            {"query": "How does approval protect an AI agent write?", "top_k": 3},
            [documents[0]],
        )
        search = run(id, scoped)
        results = search["result"]["data"]["results"]
        assert results and {x["document_id"] for x in results} == {documents[0]}
        report["retrieval_strategy"] = search["result"]["data"]["retrieval_strategy"]
        report["dense_candidates"] = sum(
            x.get("dense_score") is not None for x in results
        )
        report["sparse_candidates"] = sum(
            x.get("sparse_score") is not None for x in results
        )
        check("Actual scoped search returned indexed chunks; control document excluded")
        duplicate = call("POST", tool_path(id) + "/test-runs", scoped, expected=202)
        assert duplicate["test_run_id"] == search["test_run_id"]
        call(
            "POST",
            tool_path(id) + "/test-runs",
            {**scoped, "timeout_seconds": 20},
            expected=409,
        )
        call(
            "POST",
            tool_path(id) + "/validate",
            body({"query": "agent", "document_ids": [documents[1]]}, [documents[0]]),
            expected=403,
        )
        call(
            "POST",
            tool_path(id) + "/validate",
            body({"query": "agent", "run_id": "fake"}, [documents[0]]),
            expected=422,
        )
        check(
            "Duplicate reuse, conflicting reuse and scope/identifier injection rejected"
        )
        read = run(
            "builtin:read_knowledge_chunk",
            body({"chunk_id": results[0]["chunk_id"]}, [documents[0]]),
        )
        assert read["result"]["data"]["chunks"][0]["text"]
        check("Real source chunk read through the governed execution endpoint")
        source = {
            "source_text": "Tools acceptance reading selection.",
            "resource_title": "Tools acceptance fixture",
        }
        context = run("builtin:inspect_reading_context", body(reading=source))
        assert context["result"]["data"]["source_text"] == source["source_text"]
        enabled("builtin:inspect_reading_context", False)
        call(
            "POST",
            tool_path("builtin:inspect_reading_context") + "/test-runs",
            body(reading=source),
            expected=403,
        )
        call(
            "POST",
            "/api/agent/tools/inspect_reading_context/execute",
            source,
            expected=403,
        )
        enabled("builtin:inspect_reading_context", True)
        check(
            "Management policy blocks actual test and legacy execution, then restores"
        )
        note_id = "builtin:save_research_note"
        request = body(
            {"user_note": "Tools acceptance: approved once."}, reading=source
        )
        pending = call("POST", tool_path(note_id) + "/test-runs", request, expected=202)
        assert pending["status"] == "awaiting_approval"
        call(
            "POST",
            tool_path(note_id) + "/test-runs/" + pending["test_run_id"] + "/approve",
            {"approval_id": "wrong"},
            expected=409,
        )
        approved = call(
            "POST",
            tool_path(note_id) + "/test-runs/" + pending["test_run_id"] + "/approve",
            {"approval_id": pending["approval_id"]},
        )
        saved = wait(note_id, approved)
        report["research_note_id"] = saved["result"]["data"]["note_id"]
        call(
            "POST",
            tool_path(note_id) + "/test-runs/" + pending["test_run_id"] + "/approve",
            {"approval_id": pending["approval_id"]},
            expected=409,
        )
        rejected = call(
            "POST",
            tool_path(note_id) + "/test-runs",
            body({"user_note": "must not be saved"}, reading=source),
            expected=202,
        )
        rejection = call(
            "POST",
            tool_path(note_id) + "/test-runs/" + rejected["test_run_id"] + "/cancel",
            {},
        )
        assert (
            rejection["status"] == "cancelled"
            and rejection["execution_state"] == "stopped"
        )
        check(
            "A real research note requires bound approval; grant replay and rejected writes cannot execute"
        )
        suffix = uuid4().hex[:8]
        preset = {
            "name": "custom_acceptance_search_" + suffix,
            "title": "Acceptance scoped search",
            "template_id": id,
            "fixed_arguments": {"top_k": 2},
            "exposed_fields": ["query", "document_ids", "document_scope"],
            "defaults": {},
            "examples": [],
            "timeout_seconds": 20,
        }
        custom = call("POST", "/api/tools/custom", preset, expected=201)
        assert not custom["enabled"]
        custom = enabled(custom["tool_id"], True)
        custom_result = run(
            custom["tool_id"], body({"query": "agent approval"}, [documents[0]])
        )
        assert len(custom_result["result"]["data"]["results"]) <= 2
        enabled(id, False)
        call(
            "POST",
            tool_path(custom["tool_id"]) + "/test-runs",
            body({"query": "agent"}, [documents[0]]),
            expected=403,
        )
        enabled(id, True)
        check(
            "A persisted custom preset runs real retrieval and obeys primitive disabled policy"
        )
        import_preset = {**preset, "name": "custom_import_search_" + suffix}
        document = {"schema_version": 1, "tools": [import_preset]}
        preview = call("POST", "/api/tools/imports/preview", document)
        imported = call(
            "POST",
            "/api/tools/imports",
            {"document": document, "preview_token": preview["preview_token"]},
        )["items"][0]
        assert not imported["enabled"]
        call(
            "POST",
            "/api/tools/imports",
            {"document": document, "preview_token": preview["preview_token"]},
            expected=409,
        )
        for tool in (custom, imported):
            latest = call("GET", tool_path(tool["tool_id"]))
            archived = call(
                "POST",
                tool_path(tool["tool_id"]) + "/archive",
                {"revision": latest["revision"]},
            )
            assert archived["archived"] and not archived["enabled"]
        history = call("GET", tool_path(custom["tool_id"]) + "/test-runs")
        assert any(
            item["test_run_id"] == custom_result["test_run_id"]
            for item in history["items"]
        )
        check("Preview/apply/stale-token import and archive preserve test history")
        events = call(
            "GET", tool_path(id) + "/test-runs/" + search["test_run_id"] + "/event-log"
        )["items"]
        assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
        assert events[-1]["status"] == "succeeded"
        check("Ordered persisted lifecycle includes final success without source text")
        report["status"] = "passed"
    except Exception as exc:  # record an honest failure before restoring test policy
        report["status"] = "failed"
        report["error"] = str(exc)
        raise
    finally:
        for id, value in originals.items():
            enabled(id, value)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("Report:", args.report, flush=True)


if __name__ == "__main__":
    main()
