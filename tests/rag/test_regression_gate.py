from scripts.check_rag_regression import compare_reports


def test_hard_gate_and_case_regression_block_even_when_quality_is_deferred():
    baseline = {"dataset_fingerprint": "f", "checks": dict.fromkeys(["scope", "generation", "source_span", "function"], True), "per_case": {"fixed": True}}
    assert compare_reports(baseline, baseline)["passed"]
    assert not compare_reports(baseline, {**baseline, "per_case": {"fixed": False}})["passed"]
    assert not compare_reports(baseline, {**baseline, "checks": {}})["passed"]
    assert not compare_reports(baseline, {**baseline, "dataset_fingerprint": "other"})["passed"]
    assert not compare_reports(baseline, baseline, quality=True)["passed"]


def test_frozen_suite_accepts_checkout_newlines_but_rejects_content_changes(tmp_path, monkeypatch):
    import hashlib
    import json
    from types import SimpleNamespace

    import pytest

    from scripts import check_rag_regression

    test_file = tmp_path / "test_case.py"
    content = b"def test_case():\n    assert True\n"
    test_file.write_bytes(content.replace(b"\n", b"\r\n"))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"suites": {"ci": [{"path": "test_case.py", "sha256": hashlib.sha256(content).hexdigest()}]}}))
    monkeypatch.setattr(check_rag_regression, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_rag_regression.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    assert check_rag_regression.run_suite(manifest, "ci") == 0
    test_file.write_bytes(content + b"# changed\n")
    with pytest.raises(ValueError, match="manifest is stale"):
        check_rag_regression.run_suite(manifest, "ci")
