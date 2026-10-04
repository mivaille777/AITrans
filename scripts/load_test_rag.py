from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter, process_time

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.rag.benchmarks.common import atomic_write_json
from backend.rag.evaluation import percentile


def run_load(operation, *, queries: int, concurrency: int = 1):
    if queries < 1 or not 1 <= concurrency <= 32:
        raise ValueError("positive request count and concurrency 1..32 required")
    def invoke(index):
        started = perf_counter()
        try:
            details = operation(index)
            return {"request": index, "elapsed_ms": (perf_counter()-started)*1000, "error": "", **details}
        except Exception as exc:  # noqa: BLE001 - a failed request is measured, never hidden
            return {"request": index, "elapsed_ms": (perf_counter()-started)*1000, "error": f"{type(exc).__name__}: {exc}"}
    started, cpu = perf_counter(), process_time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        rows = list(pool.map(invoke, range(queries)))
    elapsed = perf_counter()-started
    latencies = [row["elapsed_ms"] for row in rows]
    errors = sum(bool(row["error"]) for row in rows)
    return {"requests": queries, "concurrency": concurrency, "elapsed_seconds": elapsed,
            "qps": queries/elapsed, "p50_ms": percentile(latencies, 50), "p95_ms": percentile(latencies, 95),
            "p99_ms": percentile(latencies, 99), "cpu_seconds": process_time()-cpu,
            "errors": errors, "error_rate": errors/queries, "per_request": rows}


def main():
    parser = argparse.ArgumentParser(description="Measure frozen functional RAG requests, including faults.")
    parser.add_argument("--scenario", choices=["mixed", "warm", "cold"], default="mixed")
    parser.add_argument("--queries", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--manifest", default="docs/development/rag-production-luna/regression-manifest.json")
    parser.add_argument("--output", default="data/benchmarks/rag-final/load.json")
    args = parser.parse_args()
    from scripts.run_rag_final_benchmark import (
        build_functional_runtime,
        functional_operation,
    )
    runtime, graph, cases, inputs = build_functional_runtime(args.manifest)
    try:
        operation = functional_operation(runtime, graph, cases, scenario=args.scenario)
        # Warm initialization is measured separately from concurrent requests.
        warmup = run_load(operation, queries=len(cases), concurrency=1) if args.scenario != "cold" else None
        if warmup is not None and warmup["errors"]:
            atomic_write_json(args.output, {"status": "failed_warmup", "warmup": warmup})
            return 2
        result = run_load(operation, queries=args.queries, concurrency=args.concurrency)
        result.update({"input_kind": "synthetic_functional_fixture_real_models_and_storage",
                       "quality_acceptance": "deferred", "scenario": args.scenario, "warmup": warmup,
                       "fingerprints": inputs,
                       "final_generations": runtime.manifest.list_active_generations()})
        try:
            import psutil
            result["rss_bytes_after"] = psutil.Process().memory_info().rss
        except ImportError:
            result["rss_bytes_after"] = None
        import torch
        result["peak_gpu_allocated_bytes"] = torch.cuda.max_memory_allocated() if torch.cuda.is_available() else None
        atomic_write_json(args.output, result)
        print(json.dumps({key: value for key, value in result.items() if key not in {"per_request", "warmup"}}))
        return 0 if result["errors"] == 0 else 2
    finally:
        runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
