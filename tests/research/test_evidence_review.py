from pathlib import Path

from app.research.evidence_review import EvidenceReviewStore
from backend.evaluation.evidence_review_benchmark import run_benchmark
from backend.services.evidence_review_service import EvidenceReviewService


def test_review_store_is_idempotent_and_workspace_scoped(tmp_path: Path) -> None:
    store = EvidenceReviewStore(storage_path=tmp_path / "ledger.sqlite3")
    first = store.set_review(
        workspace_id="ws-a",
        entry_id="entry-1",
        status="accepted",
        note="checked",
    )
    second = store.set_review(
        workspace_id="ws-a",
        entry_id="entry-1",
        status="accepted",
        note="checked",
    )
    assert first == second
    assert store.history_count(entry_id="entry-1") == 1
    assert store.get(workspace_id="ws-b", entry_id="entry-1") is None


def test_review_history_changes_only_on_real_adjudication_change(tmp_path: Path) -> None:
    store = EvidenceReviewStore(storage_path=tmp_path / "ledger.sqlite3")
    store.set_review(workspace_id="ws", entry_id="entry", status="accepted")
    store.set_review(workspace_id="ws", entry_id="entry", status="needs_review")
    assert store.history_count(entry_id="entry") == 2


def test_synthesis_policy_keeps_human_and_machine_status_separate() -> None:
    assert EvidenceReviewService.synthesis_bucket(
        machine_status="supported", review_status="accepted"
    ) == ("consensus", "accepted_supported")
    assert EvidenceReviewService.synthesis_bucket(
        machine_status="contested", review_status="accepted"
    ) == ("disagreement", "accepted_contested")
    assert EvidenceReviewService.synthesis_bucket(
        machine_status="stale", review_status="accepted"
    ) == ("excluded", "machine_stale")
    assert EvidenceReviewService.synthesis_bucket(
        machine_status="supported", review_status="unreviewed"
    ) == ("excluded", "review_unreviewed")


def test_stage20_benchmark_is_green() -> None:
    report = run_benchmark()
    assert report["case_count"] == 10
    assert report["failed"] == 0
