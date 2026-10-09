"""Bounded, provider-independent telemetry and writable-directory monitoring."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any


def directory_usage(
    root: Path, *, byte_limit: int, entry_limit: int
) -> tuple[int, int, bool]:
    """Never follow links; stop scanning once a budget is exceeded."""
    total = entries = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        if directory.is_symlink():
            return total, entries, True
        try:
            with os.scandir(directory) as children:
                for child in children:
                    entries += 1
                    if entries > entry_limit:
                        return total, entries, True
                    try:
                        info = child.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue  # A task may remove a file during sampling.
                    if getattr(info, "st_file_attributes", 0) & 0x400:
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(Path(child.path))
                    elif stat.S_ISREG(info.st_mode):
                        total += info.st_size
                    else:
                        continue  # Links/special files are rejected during collection.
                    if total > byte_limit:
                        return total, entries, True
        except FileNotFoundError:
            continue
        except OSError:
            return total, entries, True
    return total, entries, False


def docker_resource_sample(
    current: dict[str, Any], previous: dict[str, Any] | None
) -> dict[str, Any]:
    """Missing measurements stay unknown rather than becoming fabricated zeroes."""
    cpu = current.get("cpu_stats", {})
    prior = (previous or {}).get("cpu_stats", current.get("precpu_stats", {}))
    cpu_usage = cpu.get("cpu_usage", {})
    prior_usage = prior.get("cpu_usage", {})
    percent = None
    if "total_usage" in cpu_usage and "total_usage" in prior_usage:
        delta = cpu_usage["total_usage"] - prior_usage["total_usage"]
        system = cpu.get("system_cpu_usage", 0) - prior.get("system_cpu_usage", 0)
        cores = cpu.get("online_cpus") or len(cpu_usage.get("percpu_usage", [])) or 1
        if system > 0:
            percent = max(0.0, delta / system * cores * 100)
    return {
        "cpu_percent": percent,
        "memory_bytes": current.get("memory_stats", {}).get("usage"),
        "pids": current.get("pids_stats", {}).get("current"),
    }
