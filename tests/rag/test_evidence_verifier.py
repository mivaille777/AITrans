import pytest

from backend.rag.evidence_verifier import (
    AtomicClaimRequirement,
    EvidenceQuote,
    verify_claim_evidence,
)


@pytest.mark.parametrize("text", ["A inhibits B.", "A", "B activates A."])
def test_correct_id_cannot_replace_complete_supporting_quote(text):
    requirement = AtomicClaimRequirement(
        claim_id="direction", alternatives=[[EvidenceQuote(chunk_id="c", quote="A activates B.")]],
    )
    assert verify_claim_evidence([requirement], {"c": text}).status == "relevant_insufficient"


def test_or_of_and_requires_every_member_of_one_alternative():
    requirement = AtomicClaimRequirement(claim_id="claim", alternatives=[
        [EvidenceQuote(chunk_id="a", quote="not effective"), EvidenceQuote(chunk_id="b", quote="in children")],
        [EvidenceQuote(chunk_id="c", quote="not effective in children")],
    ])
    assert verify_claim_evidence([requirement], {"a": "not effective"}).status == "relevant_insufficient"
    assert verify_claim_evidence([requirement], {"c": "not effective in children"}).status == "sufficient"
    assert verify_claim_evidence([requirement], {}).status == "absent"
