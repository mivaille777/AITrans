"""Offline real ColQwen page encoding and FAISS/MaxSim validation on a generated PDF."""

from __future__ import annotations

import argparse
import itertools
import json
from hashlib import sha256
from pathlib import Path
from time import perf_counter

import fitz
import numpy as np

from backend.evaluation.visual_retrieval_benchmark import (
    VisualRetrievalBenchmarkCase,
    run_visual_retrieval_benchmark,
)
from backend.rag.config import (
    RagEmbeddingConfig,
    RagVectorStoreConfig,
    RagVisualRetrievalConfig,
)
from backend.rag.embeddings.qwen3 import Qwen3EmbeddingProvider
from backend.rag.index_manifest import IndexManifest, IndexManifestRecord, IndexStatus
from backend.rag.retrieval_service import RetrievalService
from backend.rag.sparse import BM25SparseRetriever
from backend.rag.stores.faiss import FaissVectorStore
from backend.rag.stores.faiss_visual import FaissVisualMultiVectorStore
from backend.rag.visual_adaptive import AdaptivePrefetchPolicy
from backend.rag.visual_retrieval import (
    VisualRetrievalService,
    build_visual_index_items,
    create_visual_embedding_provider,
    visual_retrieval_index_version,
)


def validate(
    output: Path, *, cache_dir: str = "", model_path: str = "", embedding_path: str = ""
):
    output.mkdir(parents=True, exist_ok=False)
    source = output / "visual-corpus.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=500, height=500)
        page.insert_text((40, 55), "SALES GROWTH LINE CHART", fontsize=22)
        page.draw_line((65, 400), (460, 400))
        page.draw_line((65, 100), (65, 400))
        points = [(90, 350), (180, 310), (270, 220), (360, 155), (440, 110)]
        for a, b in itertools.pairwise(points):
            page.draw_line(a, b, color=(0, 0, 0.8), width=4)
        page.insert_text(
            (120, 445), "Sales increase steadily from January to May.", fontsize=13
        )
        page = pdf.new_page(width=500, height=500)
        page.insert_text((40, 55), "TASK DURATION BAR CHART", fontsize=22)
        for i, (name, height) in enumerate([("A", 70), ("B", 180), ("C", 110)]):
            x = 80 + i * 130
            page.draw_rect(
                (x, 400 - height, x + 70, 400),
                fill=(0.7, 0.1, 0.1),
                color=(0.7, 0.1, 0.1),
            )
            page.insert_text((x + 30, 430), name, fontsize=20)
        page = pdf.new_page(width=500, height=500)
        page.insert_text((40, 80), "PHYSICS EQUATION", fontsize=25)
        page.insert_text((100, 230), "E = m c^2", fontsize=44)
        page.insert_text(
            (60, 350),
            "Energy equals mass times the speed of light squared.",
            fontsize=14,
        )
        page = pdf.new_page(width=500, height=500)
        page.insert_text((40, 65), "TRANSLATION WORKFLOW", fontsize=25)
        page.insert_textbox(
            (40, 120, 460, 420),
            "Read the original document.\n\nTranslate the text into Chinese.\n\nReview the terminology.\n\nSave the final translation.",
            fontsize=19,
        )
        pdf.save(source)
    config = RagVisualRetrievalConfig(
        enabled=True,
        device="cuda",
        precision="bf16",
        quantization="nf4",
        max_image_tokens=256,
        local_files_only=True,
        model_path=model_path,
        cache_dir=cache_dir,
        dimension=128,
        render_dpi=96,
        visual_top_k=1,
        prefetch_top_k=4,
        storage_path=str(output / "faiss"),
        asset_storage_path=str(output / "assets"),
    )
    record = IndexManifestRecord(
        document_id="visual-real",
        generation_id="g1",
        status=IndexStatus.READY,
        source_uri=source.resolve().as_uri(),
        content_hash=sha256(source.read_bytes()).hexdigest(),
    )
    provider = create_visual_embedding_provider(config)
    items = build_visual_index_items(source, record, config)
    items = [
        (
            chunk.model_copy(
                update={
                    "metadata": {
                        **chunk.metadata,
                        "index_generation": record.generation_id,
                        "asset_sha256": sha256(path.read_bytes()).hexdigest(),
                    }
                },
                deep=True,
            ),
            path,
        )
        for chunk, path in items
    ]
    started = perf_counter()
    vectors = provider.embed_images([path for chunk, path in items])
    encode_ms = (perf_counter() - started) * 1000
    store = FaissVisualMultiVectorStore(
        config, policy=AdaptivePrefetchPolicy(min_k=2, max_k=4, candidate_ratio=0.5)
    )
    try:
        store.replace_document(
            record.document_id,
            [chunk for chunk, path in items],
            vectors,
            index_version=visual_retrieval_index_version(config),
        )
        cases = [
            VisualRetrievalBenchmarkCase(
                case_id=f"visual-{i}",
                query=query,
                relevant_chunk_ids=(items[page - 1][0].chunk_id,),
                document_ids=(record.document_id,),
            )
            for i, (query, page) in enumerate(
                [
                    ("Find the line chart showing increasing sales.", 1),
                    ("找到销量持续上升的折线图", 1),
                    ("Find the bar chart comparing task duration A B C.", 2),
                    ("Which page contains the formula E equals m c squared?", 3),
                    ("找到质能方程 E=mc² 所在页面", 3),
                    ("Find the translation workflow instructions.", 4),
                ]
            )
        ]
        active = {record.document_id: "g1"}
        report = run_visual_retrieval_benchmark(
            cases,
            provider=provider,
            store=store,
            config=config,
            fixed_prefetch_ks=(2, 4),
            top_k=1,
            repeats=2,
            warmup=1,
            active_generations=active,
        )
        # Compare a real model query against a direct, unblocked float32 oracle.
        query = np.array(provider.embed_query(cases[0].query), dtype=np.float32)
        expected = sorted(
            [
                (
                    chunk.chunk_id,
                    float(
                        (query @ np.array(page, dtype=np.float32).T).max(axis=1).sum()
                    ),
                )
                for (chunk, _), page in zip(items, vectors)
            ],
            key=lambda pair: (-pair[1], pair[0]),
        )
        actual = store.search_full_maxsim(
            query.tolist(), top_k=4, active_generations=active
        )
        assert [h.chunk.chunk_id for h in actual] == [h[0] for h in expected]
        assert np.allclose(
            [h.metadata["visual_score"] for h in actual],
            [h[1] for h in expected],
            atol=1e-4,
        )
        assert store.search(query.tolist(), top_k=1, active_generations={}) == []
        assert (
            store.get_chunk(actual[0].chunk.chunk_id, generation_id="g1")
            == actual[0].chunk
        )
        before = actual[0].chunk
        store.close()
        store = FaissVisualMultiVectorStore(config)
        assert store.get_chunk(before.chunk_id, generation_id="g1") == before
        assert (
            store.search_full_maxsim(
                query.tolist(), top_k=1, active_generations=active
            )[0].chunk
            == before
        )
        # Exercise the actual fusion service and its source/asset citation checks.
        manifest = IndexManifest(output / "index_manifest.json")
        record = record.model_copy(update={"chunk_ids": [c.chunk_id for c, _ in items]})
        manifest.begin_generation(record.document_id, "g1", record.chunk_ids)
        manifest.validate_generation(record.document_id, "g1", record.chunk_ids)
        manifest.publish_generation(record.document_id, "g1", manifest_record=record)
        text_store = FaissVectorStore(
            RagVectorStoreConfig(storage_path=str(output / "faiss")),
            dimension=1024,
            repository=store.repository,
        )
        embedding = Qwen3EmbeddingProvider(
            RagEmbeddingConfig(model_path=embedding_path, local_files_only=True)
        )
        base = RetrievalService(
            embedding_provider=embedding,
            vector_store=text_store,
            sparse_retriever=BM25SparseRetriever(output / "bm25.json"),
            manifest=manifest,
        )
        service = VisualRetrievalService(
            base=base,
            provider=provider,
            store=store,
            config=config,
            default_final_top_k=1,
        )
        fused = service.retrieve(
            cases[0].query,
            dense_enabled=False,
            reranker_enabled=False,
            small_to_big_enabled=False,
        )
        assert fused.metadata["visual_count"] == 1, fused.metadata
        assert fused.metadata["visual_fallback_reason"] == ""
        service.validate_evidence_candidates(fused)
        assert (
            service.get_active_chunk(fused.candidates[0].chunk.chunk_id)
            == fused.candidates[0].chunk
        )
        # A changed image must be rejected even though its durable tokens exist.
        image = items[0][1]
        image_bytes = image.read_bytes()
        try:
            image.write_bytes(b"changed visual asset")
            from backend.rag.exceptions import RagRetrievalError

            try:
                service.validate_evidence_candidates(fused)
            except RagRetrievalError:
                pass
            else:
                raise AssertionError("changed image accepted as evidence")
        finally:
            image.write_bytes(image_bytes)
        import torch

        payload = {
            "real_model": config.model,
            "quantization": config.quantization,
            "device": torch.cuda.get_device_name(0),
            "page_count": len(vectors),
            "token_shapes": [[len(v), len(v[0])] for v in vectors],
            "encode_ms": encode_ms,
            "cuda_peak_bytes": torch.cuda.max_memory_allocated(),
            "maxsim_oracle_equal": True,
            "reopen_equal": True,
            "real_visual_fusion_and_citations": True,
            "changed_asset_rejected": True,
            "faiss_execution": store.execution_info,
            "benchmark": report.model_dump(mode="json"),
        }
        (output / "report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {k: v for k, v in payload.items() if k != "benchmark"},
                ensure_ascii=False,
            )
        )
        return payload
    finally:
        store.close()
        provider.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--model-path", default="")
    parser.add_argument("--embedding-path", required=True)
    args = parser.parse_args()
    validate(
        args.output.resolve(),
        cache_dir=args.cache_dir,
        model_path=args.model_path,
        embedding_path=args.embedding_path,
    )
