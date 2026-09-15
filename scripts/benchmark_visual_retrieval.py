from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.api.knowledge_dependencies import close_rag_runtime, get_rag_runtime
from backend.evaluation.visual_retrieval_benchmark import (
    load_visual_retrieval_benchmark_cases,
    run_visual_retrieval_benchmark,
)
from backend.rag.visual_adaptive import AdaptiveQdrantTwoStageVisualStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark Stage 3.2 adaptive visual prefetch against fixed candidate "
            "pools and a full-MaxSim oracle."
        )
    )
    parser.add_argument(
        "--queries",
        required=True,
        type=Path,
        help=(
            "JSONL cases: {query, optional case_id, relevant_chunk_ids, document_ids}."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("test-results/visual-retrieval-benchmark.json"),
    )
    parser.add_argument(
        "--prefetch-k",
        nargs="+",
        type=int,
        default=[24, 48, 96],
        dest="prefetch_ks",
    )
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    return parser


def main() -> int:
    args = _parser().parse_args()
    runtime = get_rag_runtime()
    try:
        provider = runtime.visual_embedding_provider
        store = runtime.visual_vector_store
        if provider is None or store is None:
            raise RuntimeError(
                "native visual retrieval is disabled; enable "
                "AITRANS_RAG_VISUAL_RETRIEVAL_ENABLED=1 first"
            )
        if not isinstance(store, AdaptiveQdrantTwoStageVisualStore):
            raise RuntimeError(
                "Stage 3.2 benchmark requires Stage 3.1 prefetch to be enabled"
            )

        cases = load_visual_retrieval_benchmark_cases(args.queries)
        report = run_visual_retrieval_benchmark(
            cases,
            provider=provider,
            store=store,
            config=runtime.config.visual_retrieval,
            fixed_prefetch_ks=args.prefetch_ks,
            top_k=args.top_k,
            repeats=args.repeats,
            warmup=args.warmup,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = report.model_dump(mode="json")
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        close_rag_runtime()


if __name__ == "__main__":
    raise SystemExit(main())
