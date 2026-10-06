"""Validate/import a checksummed old export, without importing Qdrant or models."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from backend.rag.models import DocumentChunk
from backend.rag.stores.local_repository import (
    LocalVectorRepository,
    normalize_rows,
    vector_array,
)
from backend.rag.visual_scoring import pool_multivector


def load_bundle(bundle: Path):
    bundle = bundle.resolve()
    metadata = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    if metadata.get("format_version") != 1:
        raise ValueError("unsupported migration bundle")
    for name, expected in metadata["files"].items():
        path = (bundle / name).resolve()
        if (
            not path.is_relative_to(bundle)
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError(f"migration checksum mismatch: {name}")
    return metadata


def converted(record, schema):
    payload = dict(record["payload"])
    metadata = dict(payload.get("metadata") or {})
    generation = payload.pop("index_generation", None)
    if generation is not None:
        if metadata.get("index_generation") not in (None, "", generation):
            raise ValueError("inconsistent exported generation")
        metadata["index_generation"] = generation
    for name in (
        "source_kind",
        "visual_index_version",
        "visual_search_schema",
        "visual_published",
    ):
        value = payload.pop(name, None)
        if name in ("source_kind", "visual_index_version") and value is not None:
            if name in metadata and metadata[name] != value:
                raise ValueError(f"inconsistent reserved field {name}")
            metadata[name] = value
    payload["metadata"] = metadata
    chunk = DocumentChunk.model_validate(payload)
    visual = schema["kind"] == "visual"
    if visual and (
        metadata.get("visual_index_version") != record.get("index_version")
        or record.get("payload", {}).get("visual_published") is False
    ):
        raise ValueError("unpublished visual item or inconsistent visual index version")
    vector = vector_array(record["vector"], schema["dimension"], multivector=visual)
    if not visual and schema["distance"] == "cosine":
        vector = normalize_rows(vector)
    coarse = (
        vector_array(pool_multivector(vector, schema["dimension"]), schema["dimension"])
        if visual
        else None
    )
    return chunk, vector, record.get("index_version", ""), coarse


def validate_bundle(bundle: Path):
    """Validate identities, schemas and vectors without creating a target."""
    metadata = load_bundle(bundle)
    schemas = {s["name"]: s for s in metadata["collections"]}
    if len(schemas) != len(metadata["collections"]):
        raise ValueError("duplicate collection schema")
    for schema in schemas.values():
        if schema["kind"] not in ("text", "visual") or schema["dimension"] < 1:
            raise ValueError("unsupported collection kind or dimension")
        allowed = (
            ("dot", "cosine")
            if schema["kind"] == "visual"
            else ("dot", "cosine", "euclid", "manhattan")
        )
        if schema["distance"] not in allowed:
            raise ValueError("unsupported collection distance")
    counts = {name: 0 for name in schemas}
    keys = set()
    with (bundle / "vectors.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            rec = json.loads(line)
            chunk, _, version, _ = converted(rec, schemas[rec["collection"]])
            key = (
                rec["collection"],
                chunk.chunk_id,
                chunk.metadata.get("index_generation") or "",
                version,
            )
            if key in keys:
                raise ValueError(f"duplicate exported identity: {key}")
            keys.add(key)
            counts[rec["collection"]] += 1
    if counts != {name: s["count"] for name, s in schemas.items()}:
        raise ValueError("export counts disagree")
    return counts


def migrate(bundle: Path, destination: Path, *, resume=False, verify_only=False):
    bundle, destination = bundle.resolve(), destination.resolve()
    metadata = load_bundle(bundle)
    validate_bundle(bundle)
    if destination.is_relative_to(bundle) or bundle.is_relative_to(destination):
        raise ValueError("destination must be separate from bundle")
    identity = hashlib.sha256((bundle / "bundle.json").read_bytes()).hexdigest()
    ledger = destination / "migration.json"
    if ledger.exists():
        previous = json.loads(ledger.read_text(encoding="utf-8"))
        if previous["bundle_digest"] != identity:
            raise ValueError("resume bundle does not match target migration")
        if not resume and not verify_only:
            raise ValueError("use --resume for existing migration")
        if resume and previous.get("status") == "verified":
            return migrate(bundle, destination, verify_only=True)
    elif verify_only:
        raise ValueError("migration ledger is missing")
    elif destination.exists() and any(destination.iterdir()):
        raise ValueError("target must be a new empty staging directory")
    destination.mkdir(parents=True, exist_ok=True)
    if not verify_only:
        ledger.write_text(
            json.dumps({"bundle_digest": identity, "status": "importing"}),
            encoding="utf-8",
        )
    schemas = {s["name"]: s for s in metadata["collections"]}
    with LocalVectorRepository(destination, read_only=verify_only) as repository:
        for s in schemas.values():
            fp = (
                json.dumps(s["fingerprint"], sort_keys=True)
                if isinstance(s["fingerprint"], dict)
                else s["fingerprint"]
            )
            repository.ensure_collection(
                s["name"], s["kind"], s["dimension"], s["distance"], fp
            )
        # Validate the whole input before writing any vector batch.
        counts = {name: 0 for name in schemas}
        keys = set()
        with (bundle / "vectors.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                rec = json.loads(line)
                chunk, array, version, coarse = converted(
                    rec, schemas[rec["collection"]]
                )
                key = (
                    rec["collection"],
                    chunk.chunk_id,
                    chunk.metadata.get("index_generation") or "",
                    version,
                )
                if key in keys:
                    raise ValueError(f"duplicate exported identity: {key}")
                keys.add(key)
                counts[rec["collection"]] += 1
        if counts != {name: s["count"] for name, s in schemas.items()}:
            raise ValueError("export counts disagree")
        if not verify_only:
            batches = {name: [] for name in schemas}
            with (bundle / "vectors.jsonl").open(encoding="utf-8") as stream:
                for line in stream:
                    rec = json.loads(line)
                    name = rec["collection"]
                    batches[name].append(converted(rec, schemas[name]))
                    if len(batches[name]) >= 128:
                        repository.write(name, batches[name])
                        batches[name] = []
            for name, values in batches.items():
                if values:
                    repository.write(name, values)
        actual = {
            name: {
                (r.chunk.chunk_id, r.generation, r.index_version): r
                for r in repository.rows(name, with_vectors=True, with_coarse=True)
            }
            for name in schemas
        }
        if {name: len(rows) for name, rows in actual.items()} != counts:
            raise ValueError("target row counts disagree")
        with (bundle / "vectors.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                rec = json.loads(line)
                chunk, array, version, coarse = converted(
                    rec, schemas[rec["collection"]]
                )
                row = actual[rec["collection"]][
                    (
                        chunk.chunk_id,
                        chunk.metadata.get("index_generation") or "",
                        version,
                    )
                ]
                if row.chunk != chunk or not np.array_equal(row.vector, array):
                    raise ValueError("target payload/vector mismatch")
                if coarse is not None and not np.array_equal(row.coarse, coarse):
                    raise ValueError("target coarse vector mismatch")
        # Every READY manifest must have its exact active dense + sparse set.
        manifest_path = bundle / "rollback/index_manifest.json"
        sparse_path = bundle / "rollback/bm25_index.json"
        if manifest_path.exists():
            from backend.rag.index_manifest import IndexManifest
            from backend.rag.sparse import BM25SparseRetriever

            manifest = IndexManifest(manifest_path)
            sparse = BM25SparseRetriever(sparse_path)
            for record in manifest.list_records():
                if record.status.value != "ready":
                    continue
                wanted = set(record.chunk_ids)
                generation = record.generation_id or ""
                dense = {
                    row.chunk.chunk_id
                    for name, rows in actual.items()
                    if schemas[name]["kind"] == "text"
                    for row in rows.values()
                    if row.chunk.document_id == record.document_id
                    and row.generation == generation
                }
                sparse_ids = {
                    c.chunk_id
                    for c in sparse.list_chunks(
                        generation_id=record.generation_id or None
                    )
                    if c.document_id == record.document_id
                    and (c.metadata.get("index_generation") or "") == generation
                }
                if dense != wanted or sparse_ids != wanted:
                    raise ValueError(f"READY generation differs: {record.document_id}")
        if not verify_only:
            repository.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            ledger.write_text(
                json.dumps(
                    {"bundle_digest": identity, "status": "verified", "counts": counts}
                ),
                encoding="utf-8",
            )
    return counts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--destination", type=Path)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--verify", "--verify-only", dest="verify", action="store_true")
    p.add_argument("--validate-only", action="store_true")
    a = p.parse_args()
    if a.validate_only:
        print(json.dumps(validate_bundle(a.bundle), ensure_ascii=False))
        return
    if a.destination is None:
        p.error("--destination is required unless --validate-only")
    print(
        json.dumps(
            migrate(a.bundle, a.destination, resume=a.resume, verify_only=a.verify),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
