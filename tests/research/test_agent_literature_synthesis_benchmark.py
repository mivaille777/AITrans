from backend.evaluation.agent_literature_synthesis_benchmark import run_benchmark


def test_stage20_1_agent_literature_synthesis_benchmark_is_green() -> None:
    report = run_benchmark()
    assert report["stage"] == "20.1"
    assert report["case_count"] == 8
    assert report["failed"] == 0
