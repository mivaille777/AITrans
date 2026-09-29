from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "rag" / "fixtures" / "production_eval"
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


class BaselineError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run_import_smoke_case(
    source_path: str | Path,
    query: str,
    *,
    library_service: Any,
    retrieval_service: Any,
    required_term: str | None = None,
) -> dict[str, Any]:
    """Exercise import, scoped retrieval, evidence mapping, and citations."""
    source = Path(source_path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise BaselineError("import smoke source must be a file")
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise BaselineError("import smoke query must not be empty")

    started = datetime.now(UTC)
    indexed = library_service.import_document(source)
    if getattr(indexed.status, "value", indexed.status) != "ready":
        raise BaselineError(
            f"document import did not reach READY: {getattr(indexed, 'error', '')}"
        )
    record = library_service.get_document(indexed.document_id)
    if record is None or getattr(record.status, "value", record.status) != "ready":
        raise BaselineError("imported document is missing a READY manifest record")

    from backend.rag.citation_service import build_evidence_citations
    from backend.rag.evidence_builder import build_agent_evidence
    from backend.rag.stores.base import VectorSearchFilter

    retrieval = retrieval_service.retrieve(
        normalized_query,
        filters=VectorSearchFilter(document_ids=[indexed.document_id]),
    )
    candidates = list(retrieval.candidates)
    if not candidates:
        raise BaselineError("imported TXT fixture returned no retrieval candidates")
    scope_violations = [
        candidate.chunk.document_id
        for candidate in candidates
        if candidate.chunk.document_id != indexed.document_id
    ]
    if scope_violations:
        raise BaselineError(
            f"retrieval escaped its document scope: {scope_violations[0]}"
        )
    matched_term_chunk_ids = [
        candidate.chunk.chunk_id
        for candidate in candidates
        if required_term
        and required_term.casefold() in candidate.chunk.text.casefold()
    ]
    if required_term and not matched_term_chunk_ids:
        raise BaselineError(
            "retrieved candidates do not contain the fixture's expected evidence term"
        )

    evidence = build_agent_evidence(retrieval)
    citations = build_evidence_citations(evidence)
    evidence_ids = {item.evidence_id for item in evidence}
    invalid_citations = [
        citation.citation_id
        for citation in citations
        if not citation.evidence_ids
        or not set(citation.evidence_ids).issubset(evidence_ids)
    ]
    if invalid_citations:
        raise BaselineError(
            f"citation references unavailable evidence: {invalid_citations[0]}"
        )

    return {
        "case_id": "real-txt-import-smoke",
        "status": "complete",
        "source_name": source.name,
        "source_sha256": _sha256(source),
        "query_sha256": hashlib.sha256(normalized_query.encode("utf-8")).hexdigest(),
        "document_id": indexed.document_id,
        "manifest_status": record.status.value,
        "chunk_count": indexed.chunk_count,
        "retrieved_chunk_ids": [candidate.chunk.chunk_id for candidate in candidates],
        "retrieved_document_ids": sorted(
            {candidate.chunk.document_id for candidate in candidates}
        ),
        "expected_term_match_count": len(matched_term_chunk_ids),
        "expected_term_match_chunk_ids": matched_term_chunk_ids,
        "scope_violation_count": len(scope_violations),
        "evidence_count": len(evidence),
        "citations": [citation.model_dump(mode="json") for citation in citations],
        "elapsed_ms": round((datetime.now(UTC) - started).total_seconds() * 1000, 3),
        "isolated_index": True,
    }


def _import_worker() -> int:
    try:
        request = json.loads(sys.stdin.read())
        source = Path(request["source_path"]).expanduser().resolve(strict=True)
        query = str(request["query"])
        from backend.api.knowledge_dependencies import (
            close_rag_runtime,
            get_rag_runtime,
        )

        runtime = get_rag_runtime()
        try:
            result = run_import_smoke_case(
                source,
                query,
                library_service=runtime.library_service,
                retrieval_service=runtime.retrieval_service,
                required_term=request.get("required_term"),
            )
        finally:
            close_rag_runtime()
        print(json.dumps({"status": "complete", "case": result}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary emits machine-readable failure
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(exc) or exc.__class__.__name__,
                },
                ensure_ascii=False,
            )
        )
        return 2


def run_isolated_import_smoke(
    source_path: Path,
    query: str,
    *,
    required_term: str | None = None,
) -> dict[str, Any]:
    source = source_path.expanduser().resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="aitrans-rag-baseline-") as scratch:
        environment = os.environ.copy()
        environment["AITRANSLATOR_DATA_DIR"] = scratch
        environment["AITRANS_KNOWLEDGE_ALLOWED_ROOTS"] = str(source.parent)
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--_import-worker"],
            cwd=REPOSITORY_ROOT,
            input=json.dumps(
                {
                    "source_path": str(source),
                    "query": query,
                    "required_term": required_term,
                }
            ),
            capture_output=True,
            text=True,
            env=environment,
            check=False,
            timeout=1800,
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise BaselineError(
            f"isolated import worker emitted no result: {detail or completed.returncode}"
        ) from exc
    if completed.returncode or payload.get("status") != "complete":
        raise BaselineError(
            f"isolated import worker failed: {payload.get('error', completed.stderr.strip())}"
        )
    return payload["case"]


def _qasper_raw_path(value: Path | None) -> Path:
    path = value or (
        REPOSITORY_ROOT
        / "data"
        / "benchmarks"
        / "qasper"
        / "raw"
        / "qasper-dev-v0.3.json"
    )
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise BaselineError(
            f"QASPER raw JSON is unavailable at {resolved}; prepare it explicitly before running"
        )
    return resolved


def run_qasper_smoke(
    *,
    root: Path,
    raw_json: Path,
    run_id: str,
    seed: int,
    limit: int,
    timeout_seconds: int,
    artifact_dir: Path,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(REPOSITORY_ROOT / "scripts" / "run_qasper_benchmark.py"),
        "--root",
        str(root.resolve()),
        "--split",
        "validation",
        "--raw-json",
        str(raw_json),
        "--mode",
        "smoke",
        "--limit",
        str(limit),
        "--seed",
        str(seed),
        "--run-id",
        f"rag-prod-{run_id}",
        "--retrieval-only",
    ]
    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise BaselineError(
            f"QASPER runner emitted no result: {detail or completed.returncode}"
        ) from exc
    if completed.returncode or payload.get("status") != "complete":
        raise BaselineError(
            f"QASPER smoke failed: {payload.get('status')}; "
            f"errors={payload.get('error_count', 'unknown')}; "
            f"{completed.stderr.strip()}"
        )

    copied: dict[str, dict[str, str]] = {}
    metrics_payload: dict[str, Any] = {}
    case_counts: dict[str, int] = {}
    for key in ("predictions", "retrieval_trace", "metrics", "qrels", "errors"):
        raw = payload.get(key)
        if not raw:
            raise BaselineError(f"QASPER output omitted required artifact: {key}")
        source = Path(raw).expanduser().resolve()
        if not source.is_file():
            raise BaselineError(f"QASPER artifact is missing: {source}")
        destination = artifact_dir / f"qasper-{source.name}"
        shutil.copyfile(source, destination)
        if key in {"predictions", "retrieval_trace"}:
            rows = [
                json.loads(line)
                for line in destination.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            case_counts[key] = len(rows)
            expected_field = "question_id"
            ids = [str(row.get(expected_field, "")) for row in rows]
            if not all(ids) or len(ids) != len(set(ids)):
                raise BaselineError(
                    f"QASPER {key} must contain unique question_id records"
                )
        if key == "metrics":
            metrics_payload = json.loads(destination.read_text(encoding="utf-8"))
        copied[key] = {
            "path": str(destination.resolve()),
            "sha256": _sha256(destination),
        }
    if (
        case_counts.get("predictions") != payload["question_count"]
        or case_counts.get("retrieval_trace") != payload["question_count"]
    ):
        raise BaselineError(
            "QASPER per-question outputs do not match the completed question count"
        )
    return {
        "status": payload["status"],
        "question_count": payload["question_count"],
        "error_count": payload["error_count"],
        "run_directory": payload["run_directory"],
        "answer_generation": "disabled",
        "official_evidence_f1": payload.get("official_evidence_f1"),
        "retrieval_metrics": metrics_payload.get("ai_trans_retrieval", {}),
        "paragraph_evidence_metrics": metrics_payload.get(
            "paragraph_evidence", {}
        ),
        "performance_ms": metrics_payload.get("performance_ms", {}),
        "per_question_records": case_counts,
        "artifacts": copied,
    }


def _read_import_fixture() -> tuple[Path, str, str]:
    fixture = json.loads(
        (FIXTURE_ROOT / "import-smoke.json").read_text(encoding="utf-8")
    )
    return (
        FIXTURE_ROOT / "import-smoke.txt",
        str(fixture["query"]),
        str(fixture["expected_term"]),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the existing QASPER retrieval benchmark and an isolated real-file "
            "import/retrieval/citation smoke test."
        )
    )
    parser.add_argument("--mode", choices=("all", "qasper", "import"), default="all")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "benchmarks" / "rag-production-baseline",
    )
    parser.add_argument(
        "--qasper-root",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "benchmarks" / "qasper",
    )
    parser.add_argument("--qasper-raw-json", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--document", type=Path)
    parser.add_argument("--query")
    parser.add_argument("--_import-worker", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args._import_worker:
        return _import_worker()
    if args.limit < 1 or args.timeout_seconds < 1:
        print("limit and timeout must be positive", file=sys.stderr)
        return 2
    run_id = args.run_id or (
        datetime.now(UTC).strftime("baseline-%Y%m%dT%H%M%SZ-")
        + uuid4().hex[:8]
    )
    if not RUN_ID_PATTERN.fullmatch(run_id):
        print("run-id must contain only letters, digits, dot, underscore, or hyphen", file=sys.stderr)
        return 2
    if args.document is not None and not args.query and args.mode in {"all", "import"}:
        print("--query is required when --document is supplied", file=sys.stderr)
        return 2

    output_root = args.output_dir.expanduser().resolve()
    artifact_dir = output_root / run_id
    try:
        artifact_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(f"output directory already exists: {artifact_dir}", file=sys.stderr)
        return 2

    requested = ("qasper", "import") if args.mode == "all" else (args.mode,)
    summary: dict[str, Any] = {
        "baseline_version": 1,
        "run_id": run_id,
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "repository_root": str(REPOSITORY_ROOT),
        "git_head": _git_head(),
        "requested": list(requested),
        "results": {},
        "errors": [],
    }

    if "qasper" in requested:
        try:
            raw_json = _qasper_raw_path(args.qasper_raw_json)
            summary["results"]["qasper"] = run_qasper_smoke(
                root=args.qasper_root.expanduser().resolve(),
                raw_json=raw_json,
                run_id=run_id,
                seed=args.seed,
                limit=args.limit,
                timeout_seconds=args.timeout_seconds,
                artifact_dir=artifact_dir,
            )
            summary["qasper_input"] = {
                "split": "validation",
                "mode": "smoke",
                "seed": args.seed,
                "limit": args.limit,
                "raw_json_sha256": _sha256(raw_json),
            }
        except Exception as exc:  # noqa: BLE001 - persist each sub-run independently
            summary["results"]["qasper"] = {"status": "failed"}
            summary["errors"].append(
                {"stage": "qasper", "error": str(exc) or exc.__class__.__name__}
            )

    if "import" in requested:
        try:
            if args.document is not None:
                source_path = args.document.expanduser().resolve(strict=True)
                query = str(args.query)
                required_term = None
            else:
                source_path, fixture_query, required_term = _read_import_fixture()
                query = str(args.query or fixture_query)
            summary["results"]["import"] = run_isolated_import_smoke(
                source_path,
                query,
                required_term=required_term,
            )
            summary["import_fixture_sha256"] = _sha256(source_path)
        except Exception as exc:  # noqa: BLE001 - persist each sub-run independently
            summary["results"]["import"] = {"status": "failed"}
            summary["errors"].append(
                {"stage": "import", "error": str(exc) or exc.__class__.__name__}
            )

    summary["status"] = "complete" if not summary["errors"] else "failed"
    summary["completed_at"] = datetime.now(UTC).isoformat()
    summary_path = artifact_dir / "summary.json"
    _write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"artifact: {summary_path}")
    return 0 if summary["status"] == "complete" else 2


def _git_head() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return completed.stdout.strip() if completed.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
