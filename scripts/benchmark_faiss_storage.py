"""Isolated CPU storage benchmark; never loads models or opens production vectors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from threading import Event, Thread
from time import perf_counter

import numpy as np
import psutil

from backend.rag.config import RagVectorStoreConfig, RagVisualRetrievalConfig
from backend.rag.models import DocumentChunk
from backend.rag.stores.faiss import FaissVectorStore
from backend.rag.stores.faiss_visual import FaissVisualMultiVectorStore
from backend.rag.visual_retrieval import visual_retrieval_index_version


def timed(call, repeats=100):
    values = []
    for _ in range(repeats):
        started = perf_counter()
        call()
        values.append((perf_counter() - started) * 1000)
    return {
        "p50_ms": float(np.percentile(values, 50)),
        "p95_ms": float(np.percentile(values, 95)),
        "samples_ms": values,
    }


def benchmark(output: Path):
    from app.infrastructure.paths import data_root
    from backend.rag.benchmarks.runtime import _resolved_root

    _resolved_root(
        output,
        production_storage_paths=[
            data_root() / "config/rag/faiss",
            data_root() / "config/rag/qdrant",
        ],
    )
    output.mkdir(parents=True, exist_ok=False)
    stop = Event()
    peak = [0]
    process = psutil.Process()

    def monitor():
        while not stop.wait(0.05):
            peak[0] = max(peak[0], process.memory_info().rss)

    thread = Thread(target=monitor, daemon=True)
    thread.start()
    rng = np.random.default_rng(937)
    report = {"text": [], "visual": []}
    text = FaissVectorStore(
        RagVectorStoreConfig(storage_path=str(output / "text")), dimension=1024
    )
    try:
        previous = 0
        for size in (10000, 50000, 100000):
            started = perf_counter()
            for start in range(previous, size, 1000):
                count = min(1000, size - start)
                chunks = [
                    DocumentChunk(
                        chunk_id=f"text-{i}",
                        document_id=f"doc-{i // 1000}",
                        chunk_index=i,
                        text=f"Synthetic evidence {i}.",
                    )
                    for i in range(start, start + count)
                ]
                matrix = rng.normal(size=(count, 1024)).astype("float32")
                text.upsert_chunks(chunks, matrix, generation_id="g1")
            write_ms = (perf_counter() - started) * 1000
            active = {f"doc-{i}": "g1" for i in range((size + 999) // 1000)}
            query = rng.normal(size=1024).astype("float32")
            start = perf_counter()
            assert len(text.search(query, top_k=10, active_generations=active)) == 10
            cold_ms = (perf_counter() - start) * 1000
            warm = timed(
                lambda query=query, active=active: text.search(
                    query, top_k=10, active_generations=active
                )
            )
            narrow = timed(
                lambda query=query, active=active: text.search(
                    query,
                    top_k=10,
                    active_generations=active,
                    allowed_document_ids=["doc-0"],
                )
            )
            report["text"].append(
                {
                    "size": size,
                    "incremental_write_ms": write_ms,
                    "cold_ms": cold_ms,
                    "warm": warm,
                    "single_document": narrow,
                    "rss_bytes": process.memory_info().rss,
                }
            )
            print("text", size, "warm p95", warm["p95_ms"], flush=True)
            previous = size
    finally:
        text.close()
    config = RagVisualRetrievalConfig(
        enabled=True,
        dimension=128,
        storage_path=str(output / "visual"),
        prefetch_top_k=48,
    )
    visual = FaissVisualMultiVectorStore(config)
    version = visual_retrieval_index_version(config)
    try:
        previous = 0
        query = rng.normal(size=(8, 128)).astype("float32")
        for size in (100, 1000, 10000):
            for i in range(previous, size):
                chunk = DocumentChunk(
                    chunk_id=f"page-{i}",
                    document_id=f"v-{i}",
                    chunk_index=0,
                    text=f"Synthetic page {i}.",
                )
                visual.replace_document(
                    chunk.document_id,
                    [chunk],
                    [rng.normal(size=(128, 128)).astype("float32")],
                    index_version=version,
                )
            cold_started = perf_counter()
            visual.search(query, top_k=10)
            cold_ms = (perf_counter() - cold_started) * 1000
            warm = timed(lambda: visual.search(query, top_k=10))
            full = timed(lambda: visual.search_full_maxsim(query, top_k=10), repeats=1)
            report["visual"].append(
                {
                    "pages": size,
                    "tokens_per_page": 128,
                    "cold_ms": cold_ms,
                    "prefetch": warm,
                    "full_scan": full,
                    "rss_bytes": process.memory_info().rss,
                }
            )
            print("visual", size, "prefetch p95", warm["p95_ms"], flush=True)
            previous = size
    finally:
        visual.close()
        stop.set()
        thread.join()
    report["peak_rss_bytes"] = peak[0]
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    benchmark(parser.parse_args().output.resolve())
