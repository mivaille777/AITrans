import pytest

from scripts.load_test_rag import run_load


def test_load_counts_failures_and_each_request_once():
    def operation(index):
        if index == 3:
            raise TimeoutError("injected fault")
        return {"hits": index}
    result = run_load(operation, queries=10, concurrency=3)
    assert result["errors"] == 1
    assert result["error_rate"] == .1
    assert len({row["request"] for row in result["per_request"]}) == 10
    assert "injected fault" in result["per_request"][3]["error"]
    assert result["p99_ms"] >= result["p95_ms"] >= result["p50_ms"]
    with pytest.raises(ValueError):
        run_load(operation, queries=0)
