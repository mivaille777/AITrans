from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class QasperAblationVariant:
    variant_id: str
    name: str
    dense: bool
    sparse: bool
    reranker: bool
    structural: bool
    small_to_big: bool
    multi_query: bool
    evidence_gate: bool

    def as_dict(self) -> dict[str, bool | str]:
        return asdict(self)


QASPER_ABLATION_VARIANTS: tuple[QasperAblationVariant, ...] = (
    QasperAblationVariant(
        "B0", "Dense only", True, False, False, False, False, False, False
    ),
    QasperAblationVariant(
        "B1", "BM25 only", False, True, False, False, False, False, False
    ),
    QasperAblationVariant(
        "B2", "Dense + BM25 + RRF", True, True, False, False, False, False, False
    ),
    QasperAblationVariant(
        "B3", "B2 + Reranker", True, True, True, False, False, False, False
    ),
    QasperAblationVariant(
        "B4", "B3 + Structural Retrieval", True, True, True, True, False, False, False
    ),
    QasperAblationVariant(
        "B5", "B4 + Small-to-Big", True, True, True, True, True, False, False
    ),
    QasperAblationVariant(
        "B6", "B5 + Query Rewrite / Multi-query", True, True, True, True, True, True, False
    ),
    QasperAblationVariant(
        "B7", "B6 + Evidence Gate / Re-Retrieve", True, True, True, True, True, True, True
    ),
    QasperAblationVariant(
        "FULL",
        "Current AITrans full RAG path",
        True,
        True,
        True,
        False,
        True,
        True,
        False,
    ),
)

ABLATION_VARIANT_BY_ID = {
    variant.variant_id: variant for variant in QASPER_ABLATION_VARIANTS
}
DEFAULT_QASPER_VARIANT = QasperAblationVariant(
    "CURRENT",
    "Current benchmark baseline",
    True,
    True,
    True,
    False,
    True,
    False,
    False,
)


def get_qasper_ablation_variant(
    variant: QasperAblationVariant | str | None,
) -> QasperAblationVariant:
    if variant is None:
        return DEFAULT_QASPER_VARIANT
    if isinstance(variant, QasperAblationVariant):
        return variant
    normalized = str(variant).strip().upper()
    try:
        return ABLATION_VARIANT_BY_ID[normalized]
    except KeyError as exc:
        choices = ", ".join(ABLATION_VARIANT_BY_ID)
        raise ValueError(f"variant must be one of: {choices}") from exc


__all__ = [
    "ABLATION_VARIANT_BY_ID",
    "DEFAULT_QASPER_VARIANT",
    "QASPER_ABLATION_VARIANTS",
    "QasperAblationVariant",
    "get_qasper_ablation_variant",
]
