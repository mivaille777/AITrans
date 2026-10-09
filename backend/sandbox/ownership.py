"""Identify local backend owners without ever killing another live backend's runs."""

from __future__ import annotations
import os
import time
import math
import psutil

OWNER_PID_LABEL = "com.aitrans.owner_pid"
OWNER_STARTED_LABEL = "com.aitrans.owner_started"


def current_owner() -> dict:
    return {
        "pid": os.getpid(),
        "started": psutil.Process().create_time(),
        "created": time.time(),
    }


def owner_alive(owner: dict) -> bool:
    try:
        return (
            abs(
                psutil.Process(int(owner["pid"])).create_time()
                - float(owner["started"])
            )
            < 0.01
        )
    except (psutil.NoSuchProcess, ValueError, KeyError, TypeError):
        return False
    except (psutil.AccessDenied, OSError):
        return True  # Unverifiable owners are never cleaned automatically.


def owner_valid(owner: dict) -> bool:
    try:
        started = float(owner["started"])
        return (
            int(owner["pid"]) > 0
            and math.isfinite(started)
            and 0 < started <= time.time() + 5
        )
    except (KeyError, ValueError, TypeError, OverflowError):
        return False


def owner_labels() -> dict[str, str]:
    owner = current_owner()
    return {
        OWNER_PID_LABEL: str(owner["pid"]),
        OWNER_STARTED_LABEL: str(owner["started"]),
    }
