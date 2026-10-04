import sqlite3
from types import SimpleNamespace

import pytest

from backend.rag.bad_cases.models import FAILURE_STAGES, RagBadCase
from backend.rag.bad_cases.store import BadCaseStore
from backend.rag.bad_cases.triage import first_failed_stage
from backend.rag.evaluation_dataset import RagEvaluationCase
from backend.services.rag_debug_store_service import RagDebugStoreService
from scripts.replay_rag_bad_case import replay


@pytest.mark.parametrize("stage", FAILURE_STAGES)
def test_first_loss_preserves_every_failure_layer(stage):
    assert first_failed_stage({stage: ["a"]}, [["a", "b"]]) == stage


def test_bad_case_store_is_immutable_and_redacted_by_default(tmp_path):
    store = BadCaseStore(RagDebugStoreService(storage_path=tmp_path / "debug.sqlite3"))
    case = RagBadCase(case=RagEvaluationCase(case_id="c", query="private question"), trace_id="t",
                      generations={"d": "g"}, fingerprints={"model": "m"}, answer="private answer")
    identity = store.save(case)
    payload = store.load(identity)
    assert "private" not in repr(payload)
    assert payload["generations"] == {"d": "g"}
    assert payload["source_redacted"]
    with pytest.raises(sqlite3.IntegrityError):
        store.save(case)


def test_replay_rejects_missing_frozen_generation_before_retrieval():
    case = RagBadCase(case=RagEvaluationCase(case_id="c", query="q"), trace_id="t", generations={"d": "old"}, fingerprints={})
    runtime = SimpleNamespace(manifest=SimpleNamespace(list_active_generations=lambda: {"d": "new"}))
    with pytest.raises(ValueError, match="frozen generation"):
        replay(case, runtime)
