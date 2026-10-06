"""Source-pinned semantic ranking checks using real models and frozen query plans.

Capture sends only questions to the configured planner. Replay is offline, does
not mutate production stores, and exercises Companion's actual evidence path.
Private plans, source quotes and reports stay under ignored test-results/.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.infrastructure.settings import SettingsManager
from backend.api.llm_dependencies import (
    build_rag_query_planner,
    get_planner_text_service,
)
from backend.rag.config import RagConfig
from backend.rag.embeddings import create_embedding_provider
from backend.rag.index_manifest import IndexManifest
from backend.rag.model_manager import ModelManager
from backend.rag.query_planner import RAG_QUERY_PLANNER_PROMPT, RagQueryPlan
from backend.rag.rerankers import Qwen3RerankerProvider
from backend.rag.retrieval_service import RetrievalService
from backend.rag.sparse import BM25SparseRetriever
from backend.rag.stores.faiss import FaissVectorStore
from backend.rag.stores.local_repository import LocalVectorRepository
from backend.services.companion_chat_service import CompanionChatService
from scripts.evaluate_local_rag_completeness import save, source_path


def cases_from(dataset):
    cases = [{**c, "group": "core"} for c in dataset["cases"]]
    original = next(c for c in cases if c["case_id"] == "wen-safety")
    variants = [
        original["query"],
        "文中为何要约束 PID 增益更新？",
        "为什么需要给 PID 增益的变化设置边界？",
        "Why does the water tank paper require limiting changes in PID gains?",
        "Why should changes to PID gains be bounded?",
        "Why are PID gain updates constrained in this paper?",
    ]
    cases.extend(
        {
            **original,
            "case_id": f"semantic-safety-{i}",
            "query": query,
            "group": "variants",
        }
        for i, query in enumerate(variants)
    )
    cases.extend(
        {**original, "case_id": f"original-repeat-{i}", "group": "repeat"}
        for i in range(3)
    )
    return cases


def capture(args, output, dataset):
    # At task start query_planner.py matched HEAD's 1.4.0 implementation.
    # Keep that exact implementation as a local baseline, without reverting code.
    source = subprocess.run(
        ["git", "show", "HEAD:backend/rag/query_planner.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout
    if 'version="1.4.0"' not in source:
        raise RuntimeError("HEAD no longer contains the audited 1.4.0 baseline")
    path = output / "semantic_planner_baseline.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_semantic_baseline", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    before = module.RagQueryPlanner(text_service=get_planner_text_service())
    after = build_rag_query_planner()
    payload = {
        "dataset_hash": sha256((output / "dataset.json").read_bytes()).hexdigest(),
        "sources": dataset["sources"],
        "prompts": {
            "before": asdict(module.RAG_QUERY_PLANNER_PROMPT),
            "after": asdict(RAG_QUERY_PLANNER_PROMPT),
        },
        "cases": [],
    }
    for case in cases_from(dataset):
        plans = {}
        for stage, planner in (("before", before), ("after", after)):
            plan = (
                planner.plan(
                    case["query"], single_document_scope=len(case["document_ids"]) == 1
                )
                if stage == "after"
                else planner.plan(case["query"])
            )
            if plan.fallback_reason:
                raise RuntimeError(
                    f"planner degraded: {case['case_id']} {plan.fallback_reason}"
                )
            plans[stage] = plan.model_dump(mode="json")
        payload["cases"].append({**case, "plans": plans})
        save(output / args.plans, payload)
        print(
            case["case_id"],
            plans["after"]["rewritten_query"],
            plans["after"]["subqueries"],
            flush=True,
        )


def replay(args, output, dataset):
    import backend.rag.query_planner as planner_module

    frozen = json.loads((output / args.plans).read_text(encoding="utf-8"))
    if frozen["prompts"]["after"] != asdict(RAG_QUERY_PLANNER_PROMPT):
        raise RuntimeError("planner prompt changed after plan capture")
    if (
        frozen["dataset_hash"]
        != sha256((output / "dataset.json").read_bytes()).hexdigest()
    ):
        raise RuntimeError("gold dataset changed after plan capture")
    config = RagConfig.model_validate(SettingsManager().data.get("rag", {}))
    if args.pool is not None:
        config.retrieval = type(config.retrieval).model_validate(
            {**config.retrieval.model_dump(), "rerank_candidate_k": args.pool}
        )
    if not config.query_rewrite_enabled or not config.query_router_enabled:
        raise RuntimeError(
            "this acceptance run requires the audited production rewrite/router settings"
        )
    vector_path = ROOT / config.vector_store.storage_path
    state = vector_path.parent
    manifest = IndexManifest(state / "index_manifest.json")
    for source in frozen["sources"]:
        if (
            sha256(source_path(source["source_uri"]).read_bytes()).hexdigest()
            != source["source_hash"]
            or manifest.get(source["document_id"]).generation_id
            != source["generation_id"]
        ):
            raise RuntimeError("source or active generation changed")
    watched = [
        state / "index_manifest.json",
        state / "bm25_index.json",
        vector_path / "vector_store.sqlite3",
    ]
    hashes = {str(p): sha256(p.read_bytes()).hexdigest() for p in watched}
    manager = ModelManager()
    embedding = create_embedding_provider(config.embedding, model_manager=manager)
    reranker = Qwen3RerankerProvider(config.reranker, model_manager=manager)
    query_coverage = planner_module.retain_list_coverage
    stages = {
        "baseline": ("before", False),
        "planner": ("after", False),
        "merge": ("after", True),
        "rerank": ("after", False),
        "final": ("after", True),
    }
    rows = []
    selected_stages = args.stages.split(",")
    if set(selected_stages) - stages.keys():
        raise ValueError("unknown ablation stage")

    def plain_cutoff(fused, _lists, *, limit, **_kwargs):
        return fused[:limit]

    with LocalVectorRepository(vector_path, read_only=True) as repository:
        store = FaissVectorStore(
            config.vector_store,
            dimension=config.embedding.dimension,
            repository=repository,
        )
        store.ensure_collection()
        service = RetrievalService(
            embedding_provider=embedding,
            vector_store=store,
            sparse_retriever=BM25SparseRetriever(state / "bm25_index.json"),
            manifest=manifest,
            reranker=reranker,
            config=config.retrieval,
        )
        for case in frozen["cases"]:
            if args.group and case["group"] != args.group:
                continue
            for stage in selected_stages:
                plan_name, preserve_queries = stages[stage]
                # Force the historical Top8 admission for baseline and single
                # changes. Rerank/final use the audited current production policy.
                service._config = (
                    config.retrieval
                    if stage in ("rerank", "final")
                    else config.retrieval.model_copy(update={"rerank_candidate_k": 8})
                )
                planner_module.retain_list_coverage = (
                    query_coverage if preserve_queries else plain_cutoff
                )
                plan = RagQueryPlan.model_validate(case["plans"][plan_name])
                if plan.original_query != case["query"] or plan.fallback_reason:
                    raise RuntimeError("frozen plan changed question or is degraded")
                traces = []
                original_retrieve = service.retrieve

                def traced(
                    *positional, _retrieve=original_retrieve, _traces=traces, **keywords
                ):
                    result = _retrieve(*positional, **keywords)
                    _traces.append(
                        {
                            "query": result.query,
                            "metadata": result.metadata,
                            "candidates": [
                                c.model_dump(mode="json") for c in result.candidates
                            ],
                        }
                    )
                    return result

                service.retrieve = traced
                try:
                    grounding = CompanionChatService(
                        retrieval_service=service,
                        query_planner=SimpleNamespace(
                            plan=lambda *a, _plan=plan, **kw: _plan
                        ),
                        rag_rewrite_enabled=True,
                        rag_router_enabled=True,
                    ).prepare_knowledge(case["query"], tuple(case["document_ids"]))
                finally:
                    service.retrieve = original_retrieve
                ids = {e.metadata["chunk_id"] for e in grounding.evidence}
                hits = sum(
                    bool(set(r["acceptable_chunk_ids"]) & ids)
                    for r in case["requirements"]
                )
                row = {
                    "case_id": case["case_id"],
                    "group": case["group"],
                    "stage": stage,
                    "query": case["query"],
                    "gold_hits": hits,
                    "requirements": len(case["requirements"]),
                    "evidence_ids": sorted(ids),
                    "fallback_reason": grounding.fallback_reason,
                    "scope_valid": all(
                        e.source_id in case["document_ids"] for e in grounding.evidence
                    ),
                    "context_within_budget": len(grounding.tool_context) <= 6000 * 4,
                    "query_count": len(traces),
                    "debug": grounding.debug_metadata,
                    "traces": traces,
                }
                rows.append(row)
                save(
                    output / (args.name + ".json"),
                    {"config": config.retrieval.model_dump(), "rows": rows},
                )
                if grounding.fallback_reason or any(
                    t["metadata"].get("fallback_reason")
                    or t["metadata"].get("reranker_fallback_reason")
                    for t in traces
                ):
                    raise RuntimeError(
                        "model/channel/planner degraded; see saved report"
                    )
                if (
                    not row["scope_valid"]
                    or not row["context_within_budget"]
                    or len(traces) > 3
                ):
                    raise RuntimeError("scope or budget violation")
                print(
                    case["case_id"], stage, f"{hits}/{row['requirements']}", flush=True
                )
    planner_module.retain_list_coverage = query_coverage
    summary = {}
    for group in sorted({r["group"] for r in rows}):
        summary[group] = {}
        for stage in selected_stages:
            group_rows = [
                r for r in rows if r["group"] == group and r["stage"] == stage
            ]
            summary[group][stage] = {
                "cases": len(group_rows),
                "complete": sum(
                    r["gold_hits"] == r["requirements"] for r in group_rows
                ),
                "gold_hits": sum(r["gold_hits"] for r in group_rows),
                "requirements": sum(r["requirements"] for r in group_rows),
            }
    unchanged = all(
        sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items()
    )
    save(
        output / (args.name + ".json"),
        {
            "config": config.retrieval.model_dump(),
            "plans_file": args.plans,
            "summary": summary,
            "production_files_unchanged": unchanged,
            "rows": rows,
        },
    )
    if not unchanged:
        raise RuntimeError("production store file changed during replay")
    print(
        json.dumps(summary, ensure_ascii=False),
        "stores unchanged",
        unchanged,
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="test-results/local-rag-completeness")
    parser.add_argument("--plans", default="semantic-ranking-plans.json")
    parser.add_argument("--capture-plans", action="store_true")
    parser.add_argument("--group", choices=("core", "variants", "repeat"))
    parser.add_argument("--stages", default="baseline,final")
    parser.add_argument("--name", default="semantic-ranking")
    parser.add_argument("--pool", type=int)
    args = parser.parse_args()
    output = ROOT / args.output
    dataset = json.loads((output / "dataset.json").read_text(encoding="utf-8"))
    if args.capture_plans:
        capture(args, output, dataset)
    else:
        replay(args, output, dataset)
