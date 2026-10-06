"""Read-only, source-pinned completeness evaluation of the user's local library.

Gold cases and reports contain private excerpts and belong in test-results/.
No remote LLM, indexing, configuration write, or production-store mutation occurs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.infrastructure.settings import SettingsManager
from backend.rag.citation_service import build_evidence_citations
from backend.rag.config import RagConfig
from backend.rag.context_builder import GroundedContextBuilder
from backend.rag.embeddings import create_embedding_provider
from backend.rag.evidence_builder import build_agent_evidence
from backend.rag.index_manifest import IndexManifest
from backend.rag.model_manager import ModelManager
from backend.rag.rerankers import Qwen3RerankerProvider
from backend.rag.retrieval_service import RetrievalService
from backend.rag.sparse import BM25SparseRetriever
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.stores.faiss import FaissVectorStore
from backend.rag.stores.local_repository import LocalVectorRepository
from backend.rag.structure_retrieval import detect_structural_intent
from backend.services.companion_chat_service import CompanionChatService


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def normalized(text):
    return re.sub(r"[^\w]", "", text.casefold()).replace("_", "")


def source_path(uri):
    return Path(unquote(urlparse(uri).path).lstrip("/"))


def build_dataset(manifest, sparse, store, output):
    records = [r for r in manifest.list_records() if str(r.status.value) == "ready"]
    active = manifest.list_active_generations()
    chunks = [
        c
        for c in sparse.list_chunks()
        if c.metadata.get("index_generation") == active.get(c.document_id)
    ]
    dense = store.list_chunks()
    audit = []
    sources = {}
    for record in records:
        path = source_path(record.source_uri)
        raw = path.read_bytes()
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            pages = [p.extract_text() or "" for p in PdfReader(path).pages]
        else:
            from backend.rag.parsers.text import TextDocumentParser

            pages = [TextDocumentParser._decode(raw, path)[0]]
        sources[record.document_id] = normalized("\n".join(pages))
        doc_chunks = [c for c in chunks if c.document_id == record.document_id]
        dense_ids = {
            c.chunk_id
            for c in dense
            if c.document_id == record.document_id
            and c.metadata.get("index_generation") == record.generation_id
        }
        sparse_ids = {c.chunk_id for c in doc_chunks}
        if dense_ids != set(record.chunk_ids) or sparse_ids != set(record.chunk_ids):
            raise RuntimeError(f"active index catalogue mismatch: {record.document_id}")
        if sha256(raw).hexdigest() != record.content_hash:
            raise RuntimeError(f"source changed: {path}")
        audit.append(
            {
                "document_id": record.document_id,
                "source_uri": record.source_uri,
                "source_hash": record.content_hash,
                "generation_id": record.generation_id,
                "active_chunks": len(doc_chunks),
                "pages": len(pages),
                "pages_with_extractable_text": [
                    i for i, p in enumerate(pages, 1) if p.strip()
                ],
                "indexed_pages": sorted(
                    {c.page_number for c in doc_chunks if c.page_number}
                ),
                "catalogues_equal": True,
                "sections": dict(Counter(c.section_heading for c in doc_chunks)),
            }
        )
    save(output / "source-audit.json", audit)
    wen = next(r.document_id for r in records if "Wen" in unquote(r.source_uri))
    meas = next(r.document_id for r in records if "MEAS" in r.source_uri)
    md = next(r.document_id for r in records if r.source_uri.endswith(".md"))

    def section(document, heading, *, all_chunks=False, contains=""):
        found = [
            c
            for c in chunks
            if c.document_id == document
            and c.section_heading == heading
            and c.chunk_type in {"paragraph_group", "reference_group", "table"}
            and (not contains or normalized(contains) in normalized(c.text))
        ]
        if not found:
            raise RuntimeError(f"missing gold section {heading}: {contains}")
        groups = [[c] for c in found] if all_chunks else [found]
        requirements = []
        for group in groups:
            quotes = []
            for c in group:
                text = normalized(c.text)
                # Verify a substantive 60-character anchor independently against the original.
                anchor = next(
                    (
                        text[i : i + 60]
                        for i in range(0, max(1, len(text) - 59), 30)
                        if len(text[i : i + 60]) == 60
                        and text[i : i + 60] in sources[document]
                    ),
                    "",
                )
                quotes.append(
                    {
                        "chunk_id": c.chunk_id,
                        "page": c.page_number,
                        "quote": c.text,
                        "quote_hash": sha256(c.text.encode()).hexdigest(),
                        "source_anchor": anchor,
                    }
                )
            requirements.append(
                {
                    "label": heading + (":" + group[0].chunk_id if all_chunks else ""),
                    "acceptable_chunk_ids": [c.chunk_id for c in group],
                    "quotes": quotes,
                }
            )
        return requirements

    cases = []

    def add(identifier, query, doc, requirements, category="factual"):
        cases.append(
            {
                "case_id": identifier,
                "query": query,
                "document_ids": [doc],
                "category": category,
                "requirements": requirements,
            }
        )

    for lang, query in [
        ("zh", "请完整列出这篇研究的所有局限性。"),
        ("en", "List every limitation of this study."),
    ]:
        add(
            "meas-all-limitations-" + lang,
            query,
            meas,
            section(meas, "5.6. Limitations and Generalizability", all_chunks=True),
            "section_complete",
        )
    for doc, prefix, heading in [
        (wen, "wen", "4. Conclusions and perspectives"),
        (meas, "meas", "6. Conclusions and Future Work"),
    ]:
        add(
            prefix + "-all-conclusions",
            "请完整总结本文结论与未来工作，不遗漏任何一项。",
            doc,
            section(doc, heading, all_chunks=True),
            "section_complete",
        )
        add(
            prefix + "-all-references",
            "请列出本文的全部参考文献。",
            doc,
            section(doc, "References", all_chunks=True),
            "section_complete",
        )
    add(
        "wen-communication",
        "MATLAB、Python 和 Ollama 如何进行双向数据交换？",
        wen,
        section(
            wen,
            "2.2. Step 2: Set up a data transmission and communication mechanism",
            contains="bidirectional",
        ),
    )
    add(
        "wen-runtime",
        "Which model and runtime were deployed locally in the water-tank experiment?",
        wen,
        section(
            wen,
            "2.2. Step 2: Set up a data transmission and communication mechanism",
            contains="LLM used",
        ),
    )
    add(
        "wen-safety",
        "水箱论文为何需要限制 PID 增益变化？",
        wen,
        section(wen, "4. Conclusions and perspectives", contains="safety constraints"),
    )
    add(
        "meas-generality",
        "这项控制方法的物理泛化能力受到什么限制？",
        meas,
        section(
            meas,
            "5.6. Limitations and Generalizability",
            contains="physical generalizability",
        ),
    )
    add(
        "meas-robustness",
        "Do the non-nominal experiments establish superiority over every adaptive baseline?",
        meas,
        section(
            meas, "5.6. Limitations and Generalizability", contains="second limitation"
        ),
    )
    add(
        "meas-training",
        "Was the language model specialized using control trajectories or PID tuning examples?",
        meas,
        section(
            meas, "5.6. Limitations and Generalizability", contains="general purpose"
        ),
    )
    add(
        "meas-results",
        "What is reported for nominal-condition overall performance?",
        meas,
        section(meas, "4.2. Nominal-Condition Overall Performance"),
    )
    for doc, prefix, headings in [
        (
            wen,
            "wen",
            [
                "2. Methodology",
                "3. Results and discussion",
                "4. Conclusions and perspectives",
            ],
        ),
        (
            meas,
            "meas",
            [
                "3.1. Method Overview and Module Responsibilities",
                "4.2. Nominal-Condition Overall Performance",
                "5.6. Limitations and Generalizability",
                "6. Conclusions and Future Work",
            ],
        ),
    ]:
        gold = [requirement for h in headings for requirement in section(doc, h)]
        add(
            prefix + "-overview-zh",
            "请结合全文，分别总结研究方法、实验结果、局限性和结论。",
            doc,
            gold,
            "multi_section",
        )
        add(
            prefix + "-overview-en",
            "Summarize the methods, experimental results, limitations and conclusions across this paper.",
            doc,
            gold,
            "multi_section",
        )
    add(
        "taskbook-acceptance",
        "任务书最终验收矩阵有哪些场景？",
        md,
        section(md, "5. 最终验收矩阵", all_chunks=True),
        "section_complete",
    )
    dataset = {
        "version": 1,
        "gold_policy": "Queries and gold selected from source sections before baseline retrieval; individual quote hashes and original-file anchors are pinned.",
        "sources": audit,
        "cases": cases,
    }
    save(output / "dataset.json", dataset)
    return dataset


def evaluate(args):
    output = (ROOT / args.output).resolve()
    config = RagConfig.model_validate(SettingsManager().data.get("rag", {}))
    vector_path = (ROOT / config.vector_store.storage_path).resolve()
    state = vector_path.parent
    manifest = IndexManifest(state / "index_manifest.json")
    sparse = BM25SparseRetriever(state / "bm25_index.json")
    with LocalVectorRepository(vector_path, read_only=True) as repository:
        store = FaissVectorStore(
            config.vector_store,
            dimension=config.embedding.dimension,
            repository=repository,
        )
        store.ensure_collection()
        dataset = (
            build_dataset(manifest, sparse, store, output)
            if args.build_dataset
            else json.loads((output / "dataset.json").read_text(encoding="utf-8"))
        )
        for source in dataset["sources"]:
            if (
                sha256(source_path(source["source_uri"]).read_bytes()).hexdigest()
                != source["source_hash"]
                or manifest.get(source["document_id"]).generation_id
                != source["generation_id"]
            ):
                raise RuntimeError(
                    "source or active generation changed; rebuild dataset explicitly"
                )
        manager = ModelManager()
        embedding = create_embedding_provider(
            config.embedding.model_copy(update={"local_files_only": True}),
            model_manager=manager,
        )
        reranker = Qwen3RerankerProvider(
            config.reranker.model_copy(update={"local_files_only": True}),
            model_manager=manager,
        )
        retrieval_config = config.retrieval
        if args.pool:
            retrieval_config = retrieval_config.model_copy(
                update={"rerank_candidate_k": args.pool}
            )
        service = RetrievalService(
            embedding_provider=embedding,
            vector_store=store,
            sparse_retriever=sparse,
            manifest=manifest,
            reranker=reranker,
            config=retrieval_config,
        )
        if args.query_plan:
            from types import SimpleNamespace

            from backend.rag.query_planner import RagQueryPlan

            plan = RagQueryPlan.model_validate_json(
                Path(args.query_plan).read_text(encoding="utf-8")
            )
            case = next(c for c in dataset["cases"] if c["case_id"] == args.case_id)
            if plan.original_query != case["query"] or plan.fallback_reason:
                raise RuntimeError(
                    "query plan does not match the pinned case or is degraded"
                )
            retrieval_runs = []
            original_retrieve = service.retrieve

            def traced_retrieve(*positional, **keywords):
                result = original_retrieve(*positional, **keywords)
                retrieval_runs.append(
                    {
                        "query": result.query,
                        "metadata": result.metadata,
                        "returned_ids": [c.chunk.chunk_id for c in result.candidates],
                    }
                )
                return result

            service.retrieve = traced_retrieve
            companion = CompanionChatService(
                retrieval_service=service,
                query_planner=SimpleNamespace(plan=lambda *a, **kw: plan),
                rag_rewrite_enabled=True,
                rag_router_enabled=SettingsManager()
                .data.get("rag", {})
                .get("query_router_enabled", False),
            )
            grounding = companion.prepare_knowledge(
                case["query"], tuple(case["document_ids"])
            )
            ids = {e.metadata["chunk_id"] for e in grounding.evidence}
            hit_count = sum(
                bool(set(r["acceptable_chunk_ids"]) & ids) for r in case["requirements"]
            )
            report = {
                "case_id": case["case_id"],
                "query_plan": plan.model_dump(mode="json"),
                "gold_hits": hit_count,
                "requirements": len(case["requirements"]),
                "recall": hit_count / len(case["requirements"]),
                "evidence_ids": sorted(ids),
                "fallback_reason": grounding.fallback_reason,
                "debug": grounding.debug_metadata,
                "retrieval_runs": retrieval_runs,
                "scope_valid": all(
                    e.source_id in case["document_ids"] for e in grounding.evidence
                ),
                "note": "Actual Companion pipeline; recorded response from the configured planner, real local embedding and reranker. No answer generation/judging.",
            }
            save(output / (args.name + ".json"), report)
            print(
                json.dumps(
                    {
                        key: report[key]
                        for key in (
                            "case_id",
                            "gold_hits",
                            "recall",
                            "scope_valid",
                            "fallback_reason",
                        )
                    },
                    ensure_ascii=False,
                )
            )
            return
        rows = []
        for case in dataset["cases"]:
            intent = detect_structural_intent(case["query"])
            result = service.retrieve(
                case["query"],
                filters=VectorSearchFilter(document_ids=case["document_ids"]),
                section_hints=intent.section_aliases if intent else (),
                final_top_k=intent.final_top_k if intent else None,
                include_references=bool(intent and intent.name == "bibliography"),
            )
            if (
                result.metadata["fallback_reason"]
                or result.metadata["reranker_fallback_reason"]
            ):
                raise RuntimeError(f"model/channel degraded: {result.metadata}")
            service.validate_evidence_candidates(
                result, filters=VectorSearchFilter(document_ids=case["document_ids"])
            )
            evidence = build_agent_evidence(result)
            citations = build_evidence_citations(evidence)
            overrides = {
                f"evidence:{c.chunk.chunk_id}": CompanionChatService._supplemental_context(
                    c
                )
                for c in result.candidates
                if c.context_window
            }
            context = GroundedContextBuilder(
                max_context_tokens=args.context_tokens
            ).build(evidence, citations, context_overrides=overrides)
            returned = {c.chunk.chunk_id for c in result.candidates}
            included = {
                e.metadata["chunk_id"]
                for e in evidence
                if e.evidence_id in context.included_evidence_ids
            }
            stages = {
                "fusion": set(result.metadata["pre_rerank_chunk_ids"]),
                "rerank_input": set(result.metadata["rerank_input_chunk_ids"]),
                "retrieval": returned,
                "context": included,
            }
            hits = {
                stage: [
                    r["label"]
                    for r in case["requirements"]
                    if set(r["acceptable_chunk_ids"]) & ids
                ]
                for stage, ids in stages.items()
            }
            row = {
                "case_id": case["case_id"],
                "category": case["category"],
                "intent": intent.name if intent else None,
                "requirements": len(case["requirements"]),
                "hits": hits,
                "recall": {
                    s: len(h) / len(case["requirements"]) for s, h in hits.items()
                },
                "returned_ids": sorted(returned),
                "context_ids": sorted(included),
                "candidate_snapshots": [
                    c.model_dump(mode="json") for c in result.candidates
                ],
                "context_chars": len(context.text),
                "context_budget_chars": context.max_context_tokens * 4,
                "context_within_budget": context.estimated_tokens
                <= context.max_context_tokens,
                "source_scope_valid": all(
                    c.chunk.document_id in case["document_ids"]
                    for c in result.candidates
                ),
                "metadata": result.metadata,
            }
            rows.append(row)
            print(
                case["case_id"],
                row["intent"],
                row["recall"],
                "context_budget",
                row["context_within_budget"],
                flush=True,
            )
            save(
                output / (args.name + ".json"),
                {"config": retrieval_config.model_dump(), "cases": rows},
            )
        requirements = sum(r["requirements"] for r in rows)
        summary = {
            "case_count": len(rows),
            "requirement_count": requirements,
            "recall": {
                s: sum(len(r["hits"][s]) for r in rows) / requirements for s in stages
            },
            "complete_cases": {
                s: sum(r["recall"][s] == 1 for r in rows) for s in stages
            },
            "budget_violations": sum(not r["context_within_budget"] for r in rows),
            "scope_violations": sum(not r["source_scope_valid"] for r in rows),
        }
        save(
            output / (args.name + ".json"),
            {
                "config": retrieval_config.model_dump(),
                "summary": summary,
                "cases": rows,
            },
        )
        print(json.dumps(summary, ensure_ascii=False), flush=True)


def replay_context(args):
    """Compare identical retrieved evidence under the saved old/new builders."""
    import importlib.util

    from backend.rag.models import RetrievalCandidate, RetrievalResult

    output = (ROOT / args.output).resolve()
    baseline_path = output / "context_builder_before.py"
    spec = importlib.util.spec_from_file_location(
        "local_context_baseline", baseline_path
    )
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)
    snapshot = json.loads(
        (output / (args.replay_context + ".json")).read_text(encoding="utf-8")
    )
    dataset = json.loads((output / "dataset.json").read_text(encoding="utf-8"))
    config = RagConfig.model_validate(SettingsManager().data.get("rag", {}))
    manifest = IndexManifest(
        (ROOT / config.vector_store.storage_path).resolve().parent
        / "index_manifest.json"
    )
    for source in dataset["sources"]:
        if (
            sha256(source_path(source["source_uri"]).read_bytes()).hexdigest()
            != source["source_hash"]
            or manifest.get(source["document_id"]).generation_id
            != source["generation_id"]
        ):
            raise RuntimeError("source or generation changed since retrieval snapshot")
    gold = {c["case_id"]: c["requirements"] for c in dataset["cases"]}
    summaries = []
    for tokens in (1500, 2000, 6000):
        rows = []
        for case in snapshot["cases"]:
            result = RetrievalResult(
                query=case["case_id"],
                candidates=[
                    RetrievalCandidate.model_validate(c)
                    for c in case["candidate_snapshots"]
                ],
            )
            evidence = build_agent_evidence(result)
            citations = build_evidence_citations(evidence)
            overrides = {
                f"evidence:{c.chunk.chunk_id}": CompanionChatService._supplemental_context(
                    c
                )
                for c in result.candidates
                if c.context_window
            }
            row = {
                "case_id": case["case_id"],
                "requirements": len(gold[case["case_id"]]),
            }
            for label, builder in (
                ("before", baseline.GroundedContextBuilder),
                ("after", GroundedContextBuilder),
            ):
                context = builder(max_context_tokens=tokens).build(
                    evidence, citations, context_overrides=overrides
                )
                ids = {
                    e.metadata["chunk_id"]
                    for e in evidence
                    if e.evidence_id in context.included_evidence_ids
                }
                row[label] = {
                    "gold_hits": sum(
                        bool(set(r["acceptable_chunk_ids"]) & ids)
                        for r in gold[case["case_id"]]
                    ),
                    "included": len(ids),
                    "chars": len(context.text),
                    "within_budget": context.estimated_tokens <= tokens,
                }
            rows.append(row)
        denominator = sum(r["requirements"] for r in rows)
        summary = {
            "tokens": tokens,
            "cases": rows,
            "recall": {
                label: sum(r[label]["gold_hits"] for r in rows) / denominator
                for label in ("before", "after")
            },
            "budget_violations": {
                label: sum(not r[label]["within_budget"] for r in rows)
                for label in ("before", "after")
            },
        }
        summaries.append(summary)
        print(tokens, summary["recall"], summary["budget_violations"], flush=True)
    save(output / "context-replay.json", summaries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="test-results/local-rag-completeness")
    parser.add_argument("--build-dataset", action="store_true")
    parser.add_argument("--name", default="current")
    parser.add_argument("--pool", type=int)
    parser.add_argument("--context-tokens", type=int, default=6000)
    parser.add_argument(
        "--replay-context",
        help="Replay candidate snapshots from the named report without loading models.",
    )
    parser.add_argument(
        "--query-plan",
        help="Run the actual Companion pipeline with a saved real planner response.",
    )
    parser.add_argument("--case-id", default="wen-safety")
    arguments = parser.parse_args()
    if arguments.replay_context:
        replay_context(arguments)
    else:
        evaluate(arguments)
