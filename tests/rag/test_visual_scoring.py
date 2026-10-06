import numpy as np
import pytest

from backend.rag.exceptions import RagVectorStoreError
from backend.rag.visual_scoring import maxsim, pool_multivector


def test_dot_cosine_negative_and_scale():
    q = np.array([[2.0, 0.0], [0.0, 3.0]], dtype=np.float32)
    p = np.array([[-1.0, -2.0], [-3.0, -1.0]], dtype=np.float32)
    assert maxsim(q, p) == -5.0
    assert maxsim(q, p * 2) == -10.0
    expected = (
        (
            (q / np.linalg.norm(q, axis=1, keepdims=True))
            @ (p / np.linalg.norm(p, axis=1, keepdims=True)).T
        )
        .max(axis=1)
        .sum()
    )
    assert maxsim(q, p, distance="cosine") == pytest.approx(expected)
    assert pool_multivector([[1.0, 0.0], [0.0, 1.0]], 2) == pytest.approx(
        [1 / np.sqrt(2)] * 2
    )


def test_blocking_matches_unblocked_and_uses_actual_tokens():
    rng = np.random.default_rng(15)
    q = rng.normal(size=(7, 8)).astype("float32")
    p = rng.normal(size=(131, 8)).astype("float32")
    assert maxsim(q, p, block_size=13) == pytest.approx(
        (q @ p.T).max(axis=1).sum(), abs=1e-5
    )
    # Padding must be removed by the model adapter before storage/scoring.
    assert maxsim([[-1.0, 0.0]], [[1.0, 0.0]]) == -1.0
    assert maxsim([[-1.0, 0.0]], [[1.0, 0.0], [0.0, 0.0]]) == 0.0


@pytest.mark.parametrize("value", [[], [[1.0]], [[1e50, 0.0]], [[float("inf"), 0.0]]])
def test_invalid_tokens(value):
    with pytest.raises(RagVectorStoreError):
        maxsim([[1.0, 0.0]], value)


def test_zero_energy_coarse_is_rejected():
    with pytest.raises(RagVectorStoreError):
        pool_multivector([[1.0, 0.0], [-1.0, 0.0]], 2)
