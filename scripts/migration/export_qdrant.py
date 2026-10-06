"""Run only in the OLD environment. Never import this module in the sidecar."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target_collection_name(name: str, kind: str, dimension: int, distance: str) -> str:
    if kind == "visual":
        for suffix in (
            f"_2stage_mv{dimension}_{distance}",
            f"_mv{dimension}_{distance}",
        ):
            if name.endswith(suffix):
                return name[: -len(suffix)]
    return name


def export(
    source: Path,
    output: Path,
    *,
    text_collection: str = "aitrans_knowledge",
    url: str = "",
    state_root: Path | None = None,
    api_key_env: str = "",
    visual_collection: str = "",
    visual_index_version: str = "",
    config_snapshot: Path | None = None,
):
    from qdrant_client import QdrantClient

    source, output = source.resolve(), output.resolve()
    state = (state_root or source.parent).resolve()
    if url and (
        urlsplit(url).username or urlsplit(url).password or urlsplit(url).query
    ):
        raise ValueError("source URL must not contain credentials or query parameters")
    api_key = os.environ.get(api_key_env) if api_key_env else None
    if api_key_env and not api_key:
        raise ValueError("requested API key environment variable is missing")
    if (
        output.exists()
        or output.is_relative_to(source)
        or source.is_relative_to(output)
        or output.is_relative_to(state)
    ):
        raise ValueError("export directory must be new and separate from source")
    # Acquiring the old store ownership lock confirms the application is stopped.
    client = (
        QdrantClient(url=url, api_key=api_key)
        if url
        else QdrantClient(path=str(source))
    )
    try:
        output.mkdir(parents=True)
        backup = output / "rollback"
        backup.mkdir()
        if config_snapshot is not None:
            if config_snapshot.suffix.lower() == ".toml":
                import tomllib

                raw = tomllib.loads(config_snapshot.read_text(encoding="utf-8"))
            else:
                raw = json.loads(config_snapshot.read_text(encoding="utf-8"))
            raw = raw.get("rag", raw)
            # Explicit allowlists prevent chat/API credentials entering the bundle.
            keys = {
                "vector_store": (
                    "provider",
                    "storage_path",
                    "collection_name",
                    "distance",
                ),
                "embedding": (
                    "provider",
                    "model",
                    "model_path",
                    "dimension",
                    "normalize",
                    "precision",
                ),
                "visual_retrieval": (
                    "enabled",
                    "provider",
                    "model",
                    "model_path",
                    "dimension",
                    "precision",
                    "quantization",
                    "max_image_tokens",
                    "render_dpi",
                    "distance",
                ),
            }
            sanitized = {
                section: {
                    key: raw.get(section, {})[key]
                    for key in allowed
                    if key in raw.get(section, {})
                }
                for section, allowed in keys.items()
            }
            (output / "config-snapshot.json").write_text(
                json.dumps({"rag": sanitized}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if not url:
            # The lock file is process state, not recoverable data, and Windows
            # forbids reading its locked byte while this client owns the store.
            shutil.copytree(
                source, backup / source.name, ignore=shutil.ignore_patterns(".lock")
            )
        for name in (
            "index_manifest.json",
            "bm25_index.json",
            "graph.sqlite3",
            "assets",
            "visual_pages",
        ):
            path = state / name
            if path.is_dir():
                shutil.copytree(path, backup / name)
            elif path.is_file():
                if name.endswith(".sqlite3"):
                    import sqlite3

                    with (
                        sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as src,
                        sqlite3.connect(backup / name) as dst,
                    ):
                        src.backup(dst)
                else:
                    shutil.copy2(path, backup / name)
        manifest_path = backup / "index_manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists()
            else {"documents": {}}
        )
        fingerprints = {
            json.dumps(r["embedding_fingerprint"], sort_keys=True)
            for r in manifest["documents"].values()
            if r.get("status") == "ready" and r.get("embedding_fingerprint")
        }
        if len(fingerprints) > 1:
            raise ValueError(
                "multiple embedding spaces in one text collection; explicit rebuild required"
            )
        catalogue, excluded = [], []
        records = output / "vectors.jsonl"
        with records.open("w", encoding="utf-8", newline="\n") as stream:
            for collection in sorted(
                client.get_collections().collections, key=lambda c: c.name
            ):
                params = client.get_collection(collection.name).config.params.vectors
                is_named = isinstance(params, dict)
                primary = params.get("late") if is_named else params
                if primary is None:
                    raise ValueError(f"unsupported named vectors in {collection.name}")
                kind = "visual" if primary.multivector_config is not None else "text"
                if (
                    kind == "visual"
                    and visual_collection
                    and collection.name != visual_collection
                ):
                    excluded.append(
                        {
                            "collection": collection.name,
                            "reason": "not the selected visual collection",
                        }
                    )
                    continue
                target_name = target_collection_name(
                    collection.name, kind, primary.size, primary.distance.value.lower()
                )
                if any(schema["name"] == target_name for schema in catalogue):
                    raise ValueError(
                        "visual variants map to one target; select --visual-collection explicitly"
                    )
                if kind == "text" and collection.name != text_collection:
                    raise ValueError(
                        f"unknown text collection {collection.name}; specify --text-collection"
                    )
                schema = {
                    "name": target_name,
                    "source_name": collection.name,
                    "kind": kind,
                    "dimension": primary.size,
                    "distance": primary.distance.value.lower(),
                    "fingerprint": json.loads(next(iter(fingerprints)))
                    if kind == "text" and fingerprints
                    else "",
                    "count": 0,
                }
                versions = set()
                offset = None
                while True:
                    points, offset = client.scroll(
                        collection.name,
                        offset=offset,
                        limit=256,
                        with_payload=True,
                        with_vectors=True,
                    )
                    for point in points:
                        payload = dict(point.payload or {})
                        if (
                            kind == "visual"
                            and payload.get("visual_published") is False
                        ):
                            excluded.append(
                                {
                                    "collection": target_name,
                                    "point_id": str(point.id),
                                    "reason": "unpublished visual point",
                                }
                            )
                            continue
                        vector = point.vector["late"] if is_named else point.vector
                        version = (
                            str(payload.get("visual_index_version", ""))
                            if kind == "visual"
                            else ""
                        )
                        versions.add(version)
                        stream.write(
                            json.dumps(
                                {
                                    "collection": target_name,
                                    "legacy_point_id": str(point.id),
                                    "payload": payload,
                                    "vector": vector,
                                    "index_version": version,
                                },
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                        schema["count"] += 1
                    if offset is None:
                        break
                if kind == "visual":
                    if len(versions) > 1 and visual_index_version not in versions:
                        raise ValueError(
                            "multiple visual versions require --visual-index-version matching the current configuration"
                        )
                    schema["fingerprint"] = (
                        visual_index_version or next(iter(versions)) if versions else ""
                    )
                catalogue.append(schema)
        files = {
            p.relative_to(output).as_posix(): digest(p)
            for p in output.rglob("*")
            if p.is_file()
        }
        metadata = {
            "format_version": 1,
            "source": str(source),
            "source_url": url,
            "source_mode": "server" if url else "local",
            "state_root": str(state),
            "exported_at": datetime.now(UTC).isoformat(),
            "collections": catalogue,
            "excluded": excluded,
            "files": files,
            "rollback_notes": "Restore old application plus the entire rollback directory; freeze writes during cutover.",
        }
        (output / "bundle.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return metadata
    finally:
        client.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", "--qdrant-path", dest="source", type=Path)
    p.add_argument("--source-root", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--text-collection", default="aitrans_knowledge")
    p.add_argument("--url", "--source-url", dest="url", default="")
    p.add_argument("--api-key-env", default="")
    p.add_argument("--visual-collection", default="")
    p.add_argument("--visual-index-version", default="")
    p.add_argument("--config-snapshot", type=Path)
    p.add_argument("--server-writes-frozen", action="store_true")
    a = p.parse_args()
    if a.url and (a.source or not a.source_root or not a.server_writes_frozen):
        p.error(
            "server export requires --source-root and --server-writes-frozen, without --qdrant-path"
        )
    source = a.source or ((a.source_root / "qdrant") if a.source_root else None)
    if source is None:
        p.error("provide --source-root or --qdrant-path")
    if a.url and not all(
        (a.source_root / name).is_file()
        for name in ("index_manifest.json", "bm25_index.json")
    ):
        p.error("server export requires the frozen manifest and BM25 state")
    result = export(
        source,
        a.output,
        text_collection=a.text_collection,
        url=a.url,
        state_root=a.source_root,
        api_key_env=a.api_key_env,
        visual_collection=a.visual_collection,
        visual_index_version=a.visual_index_version,
        config_snapshot=a.config_snapshot,
    )
    print(
        json.dumps(
            {"collections": result["collections"], "excluded": result["excluded"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
