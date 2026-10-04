"""Exercise the shipped PDF import API/runtime with real local models and stores.

Source-page gold is frozen before retrieval. This small engineering proxy does
not establish production quality, answer support, or representative OCR quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.infrastructure.settings import SettingsManager
from backend.api import knowledge, knowledge_dependencies, knowledge_preview
from backend.rag.benchmarks.common import atomic_write_json, atomic_write_jsonl
from backend.rag.config import RagConfig
from backend.rag.evaluation import percentile, recall_at_k, reciprocal_rank
from backend.rag.models import NormalizedDocument
from backend.rag.parsers.pdf import PdfDocumentParser
from backend.rag.source_span import SourceSpan, resolve_source_span
from backend.rag.stores.base import VectorSearchFilter

PROFILES = {
    "dense": {"sparse_enabled": False, "structural_enabled": False, "reranker_enabled": False},
    "sparse": {"dense_enabled": False, "structural_enabled": False, "reranker_enabled": False},
    "current": {},
}


def canonical(text: str) -> tuple[str, list[int]]:
    letters, positions = [], []
    for index, char in enumerate(text):
        for value in unicodedata.normalize("NFKC", char).casefold():
            left = text[:index].rstrip() if value == "." else ""
            right = text[index + 1:].lstrip() if value in {".", "+", "-", "−"} else ""
            numeric_punctuation = (
                value == "%"
                or (value == "." and left and right and left[-1].isdigit() and right[0].isdigit())
                or (value in {"+", "-", "−"} and right and right[0].isdigit())
            )
            if value.isalnum() or numeric_punctuation:
                value = "-" if value == "−" else value
                letters.append(value)
                positions.append(index)
    return "".join(letters), positions


def locate_gold(document: NormalizedDocument, case: dict) -> SourceSpan | None:
    page = next((p for p in document.pages if p.page_number == case["page"]), None)
    if page is None:
        return None
    text, positions = canonical(page.text)
    anchors = [canonical(anchor)[0] for anchor in case["anchors"]]
    if any(not anchor for anchor in anchors):
        raise ValueError("empty gold anchor")
    matches = []
    start = text.find(anchors[0])
    while start >= 0:
        end = start + len(anchors[0])
        for anchor in anchors[1:]:
            position = text.find(anchor, end)
            if position < 0:
                end = -1
                break
            end = position + len(anchor)
        if end > start and end - start <= 300:
            matches.append((start, end))
        start = text.find(anchors[0], start + 1)
    if len(matches) != 1:
        return None
    start, end = matches[0]
    return SourceSpan.from_text(document.text,
        start_char=page.start_char + positions[start], end_char=page.start_char + positions[end - 1] + 1,
        document_hash=document.document.content_hash, source_uri=document.document.source_uri,
        page_start=case["page"], page_end=case["page"])


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parser", choices=("current", "pypdf"), default="current")
    parser.add_argument("--gold", type=Path, default=REPO_ROOT / "tests/rag/fixtures/pdf_import_queries.json")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("output must be new; preserve earlier runs")
    specification = json.loads(args.gold.read_text(encoding="utf-8"))
    settings = SettingsManager().data
    production_config = RagConfig.model_validate(settings.get("rag", {}))
    if (production_config.graph.enabled or production_config.visual_understanding.enabled
            or production_config.visual_retrieval.enabled):
        raise ValueError("this local PDF proxy requires optional Graph/visual API paths disabled")
    original_allowed_roots = [str(root) for root in knowledge_dependencies._allowed_roots()]
    # Verify frozen source gold before constructing any index or retrieval output.
    sources = {}
    for key, item in specification["documents"].items():
        source = REPO_ROOT / item["path"]
        if digest(source) != item["sha256"]:
            raise ValueError(f"source hash differs: {source}")
        document = PdfDocumentParser().parse(source)
        for case in specification["cases"]:
            if case["document"] == key and locate_gold(document, case) is None:
                raise ValueError(f"source gold missing/ambiguous before retrieval: {case['id']}")
        sources[key] = source
    args.output.mkdir(parents=True)
    corpus = args.output.resolve() / "corpus"
    corpus.mkdir()
    copied = {}
    for key, item in specification["documents"].items():
        copied[key] = corpus / item["filename"]
        shutil.copy2(sources[key], copied[key])
    config = production_config.model_copy(deep=True)
    if args.parser == "pypdf":
        config.advanced_parsing.enabled = False
    config.vector_store.storage_path = str(args.output.resolve() / "runtime" / "qdrant")
    config.vector_store.collection_name = "pdf_import_proxy"
    config.embedding.local_files_only = True
    config.reranker.local_files_only = True
    manifest = {"status": "running", "started_at": datetime.now(UTC).isoformat(),
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip(),
        "parser_profile": args.parser, "production_config": production_config.model_dump(mode="json"),
        "original_allowed_roots": original_allowed_roots, "benchmark_allowed_roots": [str(corpus)],
        "gold_sha256": digest(args.gold), "source_hashes": {key: digest(path) for key, path in copied.items()},
        "scope": "Both original PDFs; no gold-document filter. Isolated API/router and real production factory, models and stores.",
        "limitations": "Two papers, correlated source facts; no Electron interaction, answer generation, independent citation semantics, full process restart or production capacity acceptance.",
        "code_hashes": {name: digest(REPO_ROOT / name) for name in (
            "scripts/run_pdf_rag_benchmark.py", "backend/api/knowledge_dependencies.py",
            "backend/rag/index_service.py", "backend/rag/parsers/pdf.py", "backend/rag/parsers/docling.py",
            "backend/rag/semantic_chunking.py", "backend/rag/retrieval_service.py")}}
    atomic_write_json(args.output / "manifest.json", manifest)
    runtime = None
    smoke, documents, indexed, aligned, catalogue = [], {}, {}, [], []
    with patch.object(knowledge_dependencies, "SettingsManager", return_value=SimpleNamespace(data={"rag": config.model_dump(mode="json")})), patch.dict(
        "os.environ", {"AITRANS_KNOWLEDGE_ALLOWED_ROOTS": str(corpus),
                       "AITRANS_RAG_ASSET_DIR": str(args.output.resolve() / "assets")}):
        try:
            runtime = knowledge_dependencies._build_runtime()
            original_parser = runtime.index_service._parser

            def observed_parser(path):
                parsed = original_parser(path)
                documents[str(Path(path).resolve())] = parsed
                atomic_write_json(args.output / (Path(path).stem + "-parsed.json"), parsed.model_dump(mode="json"))
                return parsed

            runtime.index_service._parser = observed_parser
            app = FastAPI()
            app.include_router(knowledge.router)
            app.include_router(knowledge_preview.router)
            app.dependency_overrides[knowledge_dependencies.get_knowledge_library_service] = lambda: runtime.library_service
            with TestClient(app) as client:
                def request(method, endpoint, expected, **kwargs):
                    response = client.request(method, "/api/knowledge" + endpoint, **kwargs)
                    smoke.append({"method": method, "endpoint": endpoint, "status": response.status_code,
                                  "expected": expected, "body": response.json()})
                    atomic_write_json(args.output / "smoke.json", smoke)
                    if response.status_code != expected:
                        raise ValueError(f"{method} {endpoint}: {response.status_code}, {response.text}")
                    return response.json()

                for key, path in copied.items():
                    imported = request("POST", "/documents", 201, json={"path": str(path)})
                    record = runtime.manifest.get(imported["document"]["document_id"])
                    if record.status.value != "ready":
                        raise ValueError("import did not publish READY")
                    normalized = documents[str(path)]
                    chunks = runtime.vector_store.list_chunks(generation_id=record.generation_id)
                    sparse = runtime.sparse_retriever.list_chunks(generation_id=record.generation_id)
                    catalogue.extend(c.model_dump(mode="json") for c in chunks)
                    if set(record.chunk_ids) != {c.chunk_id for c in chunks} or set(record.chunk_ids) != {c.chunk_id for c in sparse}:
                        raise ValueError("manifest/vector/BM25 identities differ")
                    for chunk in chunks:
                        if chunk.source_span is not None:
                            if resolve_source_span(chunk.source_span, normalized.text,
                                expected_document_hash=digest(path)) != chunk.text:
                                raise ValueError("chunk source span does not resolve exactly")
                        else:
                            element = next((e for e in normalized.elements
                                if e.element_id == chunk.metadata.get("element_id")), None)
                            if element is None or chunk.metadata.get("retrieval_text_source") != "surrogate_text":
                                raise ValueError("text chunk is missing its source span")
                            asset = runtime.library_service._path_from_file_uri(element.asset_uri)
                            if (not asset.is_file() or not asset.is_relative_to(args.output.resolve() / "assets")
                                    or chunk.page_number != element.page_number
                                    or chunk.document_hash != digest(path)):
                                raise ValueError("visual surrogate has no valid isolated source asset")
                    reused = request("POST", "/documents", 201, json={"path": str(path)})
                    if not reused["reused_existing"] or runtime.manifest.get(record.document_id).generation_id != record.generation_id:
                        raise ValueError("duplicate import did not reuse the generation")
                    request("GET", f"/documents/{record.document_id}/status", 200)
                    preview = client.get(f"/api/knowledge/documents/{record.document_id}/preview")
                    smoke.append({"method": "GET", "endpoint": f"/documents/{record.document_id}/preview",
                                  "status": preview.status_code, "expected": 200,
                                  "source_sha256": hashlib.sha256(preview.content).hexdigest()})
                    if preview.status_code != 200 or hashlib.sha256(preview.content).hexdigest() != digest(path):
                        raise ValueError("PDF preview differs from the original source bytes")
                    indexed[key] = {"document_id": record.document_id, "generation": record.generation_id,
                        "pages": len(normalized.pages), "chunks": len(chunks), "parser": record.parser_version,
                        "text_chunks": sum(c.source_span is not None for c in chunks),
                        "visual_chunks": sum(c.source_span is None for c in chunks),
                        "import_ms": imported["elapsed_ms"], "parse_metadata": normalized.metadata}
                    for case in specification["cases"]:
                        if case["document"] != key:
                            continue
                        span = locate_gold(normalized, case)
                        gold = [c.chunk_id for c in chunks if span is not None and c.source_span is not None
                            and c.source_span.start_char <= span.start_char and c.source_span.end_char >= span.end_char]
                        aligned.append({**case, "document_id": record.document_id,
                            "gold_span": span.model_dump(mode="json") if span else None, "gold_chunk_ids": gold})
                    print(f"imported {key}: {indexed[key]['parser']}, {len(chunks)} chunks", flush=True)
                atomic_write_json(args.output / "indexed.json", indexed)
                atomic_write_jsonl(args.output / "catalogue.jsonl", catalogue)
                atomic_write_jsonl(args.output / "aligned-gold.jsonl", aligned)
                summary = {}
                for name, options in PROFILES.items():
                    runtime.retrieval_service.retrieve(specification["cases"][0]["query"], **options)
                    outputs = []
                    for case in sorted(aligned, key=lambda item: item["id"]):
                        result = runtime.retrieval_service.retrieve(case["query"], **options)
                        ranked = [c.chunk.chunk_id for c in result.candidates]
                        errors = {k: result.metadata[k] for k in ("dense_error", "sparse_error", "fallback_reason", "reranker_fallback_reason") if result.metadata.get(k)}
                        gold = set(case["gold_chunk_ids"])
                        outputs.append({"id": case["id"], "language": case["language"],
                            "ranked_ids": ranked, "gold_ids": sorted(gold), "gold_mapped": bool(gold),
                            "Recall@5": recall_at_k(ranked, gold, 5) if gold else 0.0,
                            "MRR@8": reciprocal_rank(ranked, gold) if gold else 0.0,
                            "evidence_hit@5": bool(set(ranked[:5]) & gold), "elapsed_ms": result.elapsed_ms,
                            "errors": errors, "trace": result.metadata})
                    atomic_write_jsonl(args.output / f"{name}-predictions.jsonl", outputs)
                    summary[name] = {"N": len(outputs), "mapped_N": sum(r["gold_mapped"] for r in outputs),
                        **{k: mean(r[k] for r in outputs) for k in ("Recall@5", "MRR@8", "evidence_hit@5")},
                        "warm_retrieval_p95_ms": percentile([r["elapsed_ms"] for r in outputs], 95),
                        "degraded_queries": sum(bool(r["errors"]) for r in outputs), "options": options}
                    atomic_write_json(args.output / "metrics.json", summary)
                    print(json.dumps({name: summary[name]}), flush=True)
                # Reopen real persisted stores/manifest; reuse real model instances only.
                embedding = runtime.embedding_provider
                reranker = runtime.retrieval_service._reranker
                runtime.vector_store.close()
                with patch.object(knowledge_dependencies, "create_embedding_provider", return_value=embedding), patch.object(
                    knowledge_dependencies, "Qwen3RerankerProvider", return_value=reranker):
                    runtime = knowledge_dependencies._build_runtime()
                for key, item in indexed.items():
                    restored = request("POST", "/documents", 201, json={"path": str(copied[key])})
                    if not restored["reused_existing"]:
                        raise ValueError("persisted generation was not reused after reopen")
                    outline = request("GET", f"/documents/{item['document_id']}/outline", 200)
                    if outline["page_count"] != item["pages"]:
                        raise ValueError("outline page count differs from indexed PDF")
                first = next(iter(indexed.values()))
                rebuilt = request("POST", f"/documents/{first['document_id']}/reindex", 200, json={})
                generation = runtime.manifest.get(first["document_id"]).generation_id
                if rebuilt["reused_existing"] or generation == first["generation"]:
                    raise ValueError("reindex did not switch generation")
                scoped = runtime.retrieval_service.retrieve(specification["cases"][0]["query"],
                    filters=VectorSearchFilter(document_ids=[first["document_id"]]), reranker_enabled=False)
                if not scoped.candidates or scoped.metadata["active_generations"][first["document_id"]] != generation:
                    raise ValueError("reindexed generation is not retrievable")
                blank = corpus / "empty.pdf"
                writer = PdfWriter(); writer.add_blank_page(width=300, height=300); writer.write(blank)
                corrupt = corpus / "corrupt.pdf"; corrupt.write_bytes(b"not a PDF")
                for bad in (blank, corrupt):
                    request("POST", "/documents", 503, json={"path": str(bad)})
                request("POST", "/documents", 404, json={"path": str(corpus / "missing.pdf")})
                request("POST", "/documents", 422, json={"path": "relative.pdf"})
                outside = args.output.resolve() / "outside.pdf"; shutil.copy2(next(iter(copied.values())), outside)
                request("POST", "/documents", 403, json={"path": str(outside)})
                for key, item in indexed.items():
                    request("DELETE", f"/documents/{item['document_id']}", 200)
                    if not copied[key].exists() or runtime.manifest.get(item["document_id"]) is not None:
                        raise ValueError("delete removed source or retained active manifest")
                after = runtime.retrieval_service.retrieve("BERT Transformer", reranker_enabled=False)
                if after.candidates or runtime.vector_store.count_chunks() or runtime.sparse_retriever.list_chunks():
                    raise ValueError("deleted PDF remains retrievable/indexed")
            manifest.update(status="complete", functional_status="PASS", completed_at=datetime.now(UTC).isoformat(),
                effective_config=runtime.config.model_dump(mode="json"), embedding=embedding.fingerprint.as_dict(),
                indexed=indexed, profile_metrics=summary, smoke_requests=len(smoke),
                quality_status="evaluated proxy only; semantic citations and representative corpus acceptance absent")
            atomic_write_json(args.output / "manifest.json", manifest)
        except Exception as exc:
            manifest.update(status="failed", functional_status="FAIL", error=f"{type(exc).__name__}: {exc}")
            atomic_write_json(args.output / "manifest.json", manifest)
            raise
        finally:
            if runtime is not None:
                runtime.vector_store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
