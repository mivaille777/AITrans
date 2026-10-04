from __future__ import annotations

import multiprocessing
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from backend.rag.exceptions import RagRetrievalError
from backend.rag.inference_worker import (
    ProcessInferenceProvider,
    inference_cancellation,
)


class BlockingProvider:
    def __init__(self, signal_path: str):
        self.signal = Path(signal_path)

    def embed_query(self, query):
        self.signal.write_text(str(multiprocessing.current_process().pid))
        if query == "hang":
            while True:
                sleep(0.1)
        if query == "error":
            raise ValueError("original model failure")
        return [1.0, 0.0]

    def record(self, query):
        with self.signal.open("a") as handle:
            handle.write(query + "\n")
        return query


def make_worker(tmp_path, timeout=5):
    return ProcessInferenceProvider(SimpleNamespace(dimension=2), kind="test", timeout_seconds=timeout,
        factory_path="tests.rag.test_inference_worker:BlockingProvider",
        factory_options={"signal_path": str(tmp_path / "started")})


def test_native_hang_deadline_terminates_process_and_next_call_recovers(tmp_path):
    worker = make_worker(tmp_path)
    try:
        assert worker.embed_query("ready") == [1.0, 0.0]
        process = worker._process
        worker._timeout = 0.15
        started = monotonic()
        with pytest.raises(TimeoutError, match="worker terminated"):
            worker.embed_query("hang")
        assert monotonic() - started < 2.5
        assert process._closed
        assert worker._process is None
        worker._timeout = 5
        assert worker.embed_query("recovered") == [1.0, 0.0]
    finally:
        worker.close()


def test_cancellation_terminates_blocked_worker_with_no_live_child(tmp_path):
    worker = make_worker(tmp_path, timeout=30)
    cancel = Event()
    errors = []
    try:
        worker.embed_query("ready")
        (tmp_path / "started").unlink()
        pid = worker._process.pid
        def run():
            try:
                with inference_cancellation(cancel):
                    worker.embed_query("hang")
            except RagRetrievalError as exc:
                errors.append(exc)
        thread = Thread(target=run)
        thread.start()
        deadline = monotonic() + 5
        while not (tmp_path / "started").exists() and monotonic() < deadline:
            sleep(0.01)
        assert (tmp_path / "started").exists()
        started = monotonic()
        cancel.set()
        thread.join(timeout=2.5)
        assert not thread.is_alive()
        assert monotonic() - started < 2.5
        assert len(errors) == 1 and isinstance(errors[0], RagRetrievalError)
        assert "cancelled" in str(errors[0])
        assert pid not in [child.pid for child in multiprocessing.active_children()]
    finally:
        cancel.set()
        worker.close()


def test_worker_preserves_model_error_and_close_is_final(tmp_path):
    worker = make_worker(tmp_path)
    with pytest.raises(RagRetrievalError, match="original model failure"):
        worker.embed_query("error")
    assert worker.embed_query("ready") == [1.0, 0.0]
    worker.close()
    with pytest.raises(RagRetrievalError, match="closed"):
        worker.embed_query("ready")


def test_worker_timings_are_per_thread_and_keep_execution_error(tmp_path):
    worker = make_worker(tmp_path)
    measurements = []
    try:
        assert worker.last_call_timings == {}
        worker.embed_query("ready")
        owner = worker.last_call_timings
        assert owner["total_ms"] >= owner["queue_ms"] + owner["execution_ms"] >= 0

        def run():
            assert worker.last_call_timings == {}
            with pytest.raises(RagRetrievalError, match="original model failure"):
                worker.embed_query("error")
            measurements.append(worker.last_call_timings)

        thread = Thread(target=run)
        thread.start()
        thread.join(5)
        assert not thread.is_alive() and len(measurements) == 1
        assert measurements[0]["execution_ms"] >= 0
        assert worker.last_call_timings == owner
    finally:
        worker.close()


def test_failed_spawn_releases_handles_and_next_call_recovers(tmp_path, monkeypatch):
    worker = make_worker(tmp_path)
    original_start = multiprocessing.process.BaseProcess.start
    def fail_start(process):
        raise OSError("injected process startup failure")
    try:
        monkeypatch.setattr(multiprocessing.process.BaseProcess, "start", fail_start)
        with pytest.raises(OSError, match="startup failure"):
            worker.embed_query("ready")
        assert worker._process is None and worker._connection is None
        monkeypatch.setattr(multiprocessing.process.BaseProcess, "start", original_start)
        assert worker.embed_query("ready") == [1.0, 0.0]
    finally:
        worker.close()


def test_cancelled_waiter_does_not_terminate_another_requests_worker(tmp_path):
    worker = make_worker(tmp_path)
    worker._lock.acquire()
    cancel = Event()
    cancel.set()
    try:
        with inference_cancellation(cancel), pytest.raises(RagRetrievalError, match="waiting"):
            worker.embed_query("ready")
        assert worker._process is None
        assert not worker._pending
    finally:
        worker._lock.release()
        worker.close()


def test_waiting_requests_keep_fifo_order_without_starvation(tmp_path):
    worker = make_worker(tmp_path)
    threads = []
    errors = []
    held = False
    try:
        worker.embed_query("ready")
        (tmp_path / "started").unlink()
        worker._lock.acquire()
        held = True

        def run(query):
            try:
                assert worker._call("record", query) == query
            except (AssertionError, RagRetrievalError, TimeoutError, OSError) as exc:
                errors.append(exc)

        for index in range(3):
            thread = Thread(target=run, args=(str(index),))
            thread.start()
            threads.append(thread)
            deadline = monotonic() + 2
            while monotonic() < deadline:
                with worker._queue_changed:
                    if len(worker._pending) == index + 1:
                        break
                sleep(0.01)
            assert len(worker._pending) == index + 1
        worker._lock.release()
        held = False
        for thread in threads:
            thread.join(5)
        assert not errors and all(not thread.is_alive() for thread in threads)
        assert (tmp_path / "started").read_text().splitlines() == ["0", "1", "2"]
        assert not worker._pending
    finally:
        if held:
            worker._lock.release()
        for thread in threads:
            thread.join(5)
        worker.close()


def test_agent_tool_timeout_terminates_its_native_worker(tmp_path):
    from backend.agent_core.exceptions import AgentToolTimeoutError
    from backend.agent_core.reliability import (
        AgentRunControl,
        run_safe_tool_with_timeout,
    )
    worker = make_worker(tmp_path, timeout=30)
    try:
        worker.embed_query("ready")
        pid = worker._process.pid
        with pytest.raises(AgentToolTimeoutError):
            run_safe_tool_with_timeout(lambda: worker.embed_query("hang"),
                control=AgentRunControl(), tool_name="search_knowledge_base", timeout_seconds=0.15)
        assert worker._process is None
        assert pid not in [child.pid for child in multiprocessing.active_children()]
    finally:
        worker.close()


def test_bounded_agent_node_preserves_trace_context_without_leaking():
    from backend.agent_core.reliability import (
        AgentRunControl,
        run_node_operation_with_timeout,
    )
    from backend.rag.observability import bind_rag_trace, current_rag_trace

    with bind_rag_trace("node-request"):
        assert run_node_operation_with_timeout(current_rag_trace, control=AgentRunControl(),
            node_timeout_seconds=1, stage="trace") == ("node-request", None)
    assert current_rag_trace() == (None, None)
