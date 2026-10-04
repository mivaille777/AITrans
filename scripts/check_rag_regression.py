from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def compare_reports(baseline, candidate, *, quality=False):
    reasons = []
    if not baseline.get("dataset_fingerprint") or baseline.get("dataset_fingerprint") != candidate.get("dataset_fingerprint"):
        reasons.append("dataset fingerprint mismatch")
    for key in ("scope", "generation", "source_span", "function"):
        if candidate.get("checks", {}).get(key) is not True:
            reasons.append(f"hard gate failed or missing: {key}")
    old, new = baseline.get("per_case", {}), candidate.get("per_case", {})
    if not old or old.keys() != new.keys():
        reasons.append("case identity mismatch or empty suite")
    reasons.extend(f"regression: {key}" for key, passed in old.items() if passed and new.get(key) is not True)
    if quality:
        for key in ("recall_at_5", "mrr", "citation_accuracy"):
            before, after = baseline.get("metrics", {}).get(key), candidate.get("metrics", {}).get(key)
            if before is None or after is None or after < before:
                reasons.append(f"quality regression or missing measurement: {key}")
    return {"passed": not reasons, "reasons": reasons, "quality_acceptance": "enabled" if quality else "deferred"}


def run_suite(manifest_path, suite):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    entries = manifest["suites"][suite]
    if not entries:
        raise ValueError("regression suite cannot be empty")
    paths = []
    for entry in entries:
        path = (REPO_ROOT / entry["path"]).resolve()
        if REPO_ROOT not in path.parents or not path.is_file():
            raise ValueError("invalid regression path")
        if hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != entry["sha256"]:
            raise ValueError(f"regression manifest is stale: {entry['path']}")
        paths.append(entry["path"])
    return subprocess.run([sys.executable, "-m", "pytest", *paths, "-q"], cwd=REPO_ROOT, check=False).returncode


def main():
    parser = argparse.ArgumentParser(description="Run frozen functional RAG gates or compare matched reports.")
    parser.add_argument("--suite", choices=["ci"])
    parser.add_argument("--manifest", default="docs/development/rag-production-luna/regression-manifest.json")
    parser.add_argument("--baseline")
    parser.add_argument("--candidate")
    parser.add_argument("--quality", action="store_true")
    args = parser.parse_args()
    if args.suite:
        return run_suite(args.manifest, args.suite)
    if not args.baseline or not args.candidate:
        parser.error("provide --suite or both --baseline and --candidate")
    result = compare_reports(json.loads(Path(args.baseline).read_text()), json.loads(Path(args.candidate).read_text()), quality=args.quality)
    print(json.dumps(result))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
