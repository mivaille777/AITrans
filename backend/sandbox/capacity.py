"""Bound container concurrency across managers within the backend process."""

from functools import wraps
from threading import BoundedSemaphore
from backend.sandbox.errors import SandboxExecutionError

_slots = BoundedSemaphore(4)


def bounded_execution(execute):
    @wraps(execute)
    def wrapped(*args, **kwargs):
        if not _slots.acquire(blocking=False):
            raise SandboxExecutionError(
                "Sandbox concurrency budget is full; wait for an active run to finish."
            )
        try:
            return execute(*args, **kwargs)
        finally:
            _slots.release()

    return wrapped
