from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import zip_longest

from backend.rag.models import RetrievalCandidate, RetrievalResult


@dataclass(frozen=True, slots=True)
class StructuralRetrievalIntent:
    name: str
    section_aliases: tuple[str, ...]
    search_terms: tuple[str, ...]
    final_top_k: int = 8


_INTENTS: tuple[tuple[StructuralRetrievalIntent, tuple[re.Pattern[str], ...]], ...] = (
    (
        StructuralRetrievalIntent(
            name="methods",
            section_aliases=(
                "methods",
                "method",
                "methodology",
                "materials and methods",
            ),
            search_terms=("Methods", "Methodology", "Materials and Methods"),
        ),
        (
            re.compile(r"\bmethods?\b|\bmethodology\b", re.IGNORECASE),
            re.compile(r"研究方法|方法部分|方法章节|实验方法"),
        ),
    ),
    (
        StructuralRetrievalIntent(
            name="results",
            section_aliases=(
                "results",
                "experimental results",
                "experimental design and results",
            ),
            search_terms=("Results", "Experimental Results"),
        ),
        (
            re.compile(r"\bresults\b", re.IGNORECASE),
            re.compile(r"实验结果|研究结果|结果部分|结果章节"),
        ),
    ),
    (
        StructuralRetrievalIntent(
            name="bibliography",
            section_aliases=(
                "references",
                "reference",
                "bibliography",
                "works cited",
                "reference list",
            ),
            search_terms=(
                "References",
                "Bibliography",
                "Works Cited",
                "reference list",
            ),
            final_top_k=12,
        ),
        (
            re.compile(r"\breferences?\b", re.IGNORECASE),
            re.compile(r"\bbibliograph(?:y|ies)\b", re.IGNORECASE),
            re.compile(r"\bworks cited\b", re.IGNORECASE),
            re.compile(r"\bcited (?:papers?|works?|literature)\b", re.IGNORECASE),
            re.compile(
                r"参考文献|引用文献|文献列表|引用了哪些|用了哪些文献|参考了哪些文献"
            ),
        ),
    ),
    (
        StructuralRetrievalIntent(
            name="conclusion",
            section_aliases=(
                "conclusion",
                "conclusions",
                "concluding remarks",
                "discussion and conclusions",
                "conclusion and future work",
            ),
            search_terms=(
                "Conclusion",
                "Conclusions",
                "concluding remarks",
                "final findings",
            ),
            final_top_k=10,
        ),
        (
            re.compile(r"\bconclusions?\b", re.IGNORECASE),
            re.compile(r"\bconclud(?:e|es|ed|ing)\b", re.IGNORECASE),
            re.compile(r"\bconcluding remarks?\b", re.IGNORECASE),
            re.compile(
                r"\bfinal (?:finding|findings|conclusion|conclusions)\b", re.IGNORECASE
            ),
            re.compile(r"结论|最终结论|最后的观点|最后观点|最终观点|主要结论"),
        ),
    ),
    (
        StructuralRetrievalIntent(
            name="limitations",
            section_aliases=(
                "limitations",
                "limitation",
                "limitations and future work",
            ),
            search_terms=("Limitations", "limitation", "study limitations"),
            final_top_k=8,
        ),
        (
            re.compile(r"\blimitations?\b", re.IGNORECASE),
            re.compile(r"局限|局限性|不足之处|研究不足"),
        ),
    ),
    (
        StructuralRetrievalIntent(
            name="future_work",
            section_aliases=(
                "future work",
                "future research",
                "outlook",
                "conclusion and future work",
                "limitations and future work",
            ),
            search_terms=("Future Work", "future research", "outlook"),
            final_top_k=8,
        ),
        (
            re.compile(r"\bfuture (?:work|research|directions?)\b", re.IGNORECASE),
            re.compile(r"未来工作|未来研究|研究展望|未来方向|展望"),
        ),
    ),
    (
        StructuralRetrievalIntent(
            name="discussion",
            section_aliases=("discussion", "discussion and conclusions"),
            search_terms=("Discussion", "discussion section"),
            final_top_k=8,
        ),
        (
            re.compile(r"\bdiscussion\b", re.IGNORECASE),
            re.compile(r"讨论部分|讨论章节|讨论了什么"),
        ),
    ),
    (
        StructuralRetrievalIntent(
            name="table",
            section_aliases=("table", "tables"),
            search_terms=("Table", "Tables", "tabulated results"),
            final_top_k=10,
        ),
        (
            re.compile(r"\btable\s*\d*\b", re.IGNORECASE),
            re.compile(r"表格|表\s*\d+"),
        ),
    ),
    (
        StructuralRetrievalIntent(
            name="figure",
            section_aliases=("figure", "figures", "fig"),
            search_terms=("Figure", "Fig.", "Figures"),
            final_top_k=10,
        ),
        (
            re.compile(r"\bfig(?:ure)?\.?\s*\d*\b", re.IGNORECASE),
            re.compile(r"图\s*\d+|图表"),
        ),
    ),
    (
        StructuralRetrievalIntent(
            name="equation",
            section_aliases=("equation", "equations", "formula", "formulae"),
            search_terms=("Equation", "Eq.", "Formula"),
            final_top_k=10,
        ),
        (
            re.compile(r"\beq(?:uation)?\.?\s*\(?\d*\)?\b", re.IGNORECASE),
            re.compile(r"\bformulae?\b", re.IGNORECASE),
            re.compile(r"公式|方程|式\s*\(?\d+\)?"),
        ),
    ),
)

_HEADING_PREFIX = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*)|(?:[ivxlcdm]+)|(?:[a-z]))[\s.():\-]+",
    re.IGNORECASE,
)
_NON_WORD = re.compile(r"[^a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)
_ANSWER_FORMAT = re.compile(
    r"(?:一|1)句话(?:的)?结论|\bone[-\s]+sentence[-\s]+conclusions?\b",
    re.IGNORECASE,
)
_SECTION_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)*)(?:\.|\s)\s*\D")


def normalize_section_heading(value: str) -> str:
    normalized = _HEADING_PREFIX.sub("", str(value or "").strip().casefold())
    return _NON_WORD.sub(" ", normalized).strip()


def detect_structural_intent(query: str) -> StructuralRetrievalIntent | None:
    text = _ANSWER_FORMAT.sub("", str(query or "").strip())
    if not text:
        return None
    matching = [
        intent
        for intent, patterns in _INTENTS
        if any(pattern.search(text) for pattern in patterns)
    ]
    if not matching:
        return None
    if len(matching) == 1:
        return matching[0]
    # Bibliography/artifact requests retain their existing dedicated behavior.
    # Combine substantive section requests so a conclusion keyword cannot
    # silently discard an explicitly requested methods/results/limitations part.
    substantive = [
        intent
        for intent in matching
        if intent.name
        in {
            "methods",
            "results",
            "conclusion",
            "limitations",
            "future_work",
            "discussion",
        }
    ]
    if len(substantive) < 2 or len(substantive) != len(matching):
        return next(
            (intent for intent in matching if intent not in substantive), matching[0]
        )
    return StructuralRetrievalIntent(
        name="multi_section",
        section_aliases=tuple(
            dict.fromkeys(
                alias for intent in substantive for alias in intent.section_aliases
            )
        ),
        search_terms=tuple(
            dict.fromkeys(
                term for intent in substantive for term in intent.search_terms
            )
        ),
        final_top_k=max(intent.final_top_k for intent in substantive),
    )


def build_structural_queries(
    base_queries: tuple[str, ...] | list[str],
    *,
    original_query: str,
    intent: StructuralRetrievalIntent | None,
    max_queries: int = 3,
) -> tuple[str, ...]:
    if max_queries <= 0:
        return ()
    normalized_base = [
        str(item or "").strip() for item in base_queries if str(item or "").strip()
    ]
    if intent is None:
        return tuple(dict.fromkeys(normalized_base))[:max_queries]

    primary = (
        normalized_base[0] if normalized_base else str(original_query or "").strip()
    )
    structural_terms = " ".join(intent.search_terms)
    candidates = [
        f"{primary} {structural_terms}".strip(),
        structural_terms,
        *normalized_base[1:],
        primary,
    ]
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.casefold()
        if candidate and key not in seen:
            unique.append(candidate)
            seen.add(key)
        if len(unique) >= max_queries:
            break
    return tuple(unique)


def _matches_alias(value: str, aliases: tuple[str, ...]) -> bool:
    return bool(value) and any(
        alias and (value == alias or value.startswith(alias) or alias in value)
        for alias in aliases
    )


def section_match_priority(
    candidate: RetrievalCandidate,
    section_aliases: tuple[str, ...],
) -> int:
    if not section_aliases:
        return 0
    aliases = tuple(
        normalized
        for normalized in (normalize_section_heading(item) for item in section_aliases)
        if normalized
    )
    chunk = candidate.chunk

    chunk_type = normalize_section_heading(chunk.chunk_type)
    labels = chunk.metadata.get("special_labels", [])
    normalized_labels = (
        tuple(
            normalize_section_heading(str(item)) for item in labels if str(item).strip()
        )
        if isinstance(labels, list)
        else ()
    )
    artifact_aliases = {
        "table",
        "tables",
        "figure",
        "figures",
        "fig",
        "equation",
        "equations",
        "formula",
        "formulae",
        "references",
        "reference",
        "bibliography",
    }
    if _matches_alias(chunk_type, aliases) or (
        artifact_aliases.intersection(aliases)
        and any(_matches_alias(label, aliases) for label in normalized_labels)
    ):
        return 4

    heading = normalize_section_heading(chunk.section_heading)
    hierarchy = tuple(
        normalize_section_heading(item)
        for item in (
            *chunk.section_path,
            *candidate.metadata.get("structural_parent_headings", ()),
        )
        if item
    )
    if heading in aliases or any(item in aliases for item in hierarchy):
        return 3
    if _matches_alias(heading, aliases) or any(
        _matches_alias(item, aliases) for item in hierarchy
    ):
        return 2

    # A mention of "method" in the introduction/authorship statement does not
    # turn that known section into Methods. Prefix fallback is for legacy chunks
    # that actually lack section provenance.
    if heading or hierarchy:
        return 0
    prefix = normalize_section_heading(chunk.text[:180])
    if _matches_alias(prefix, aliases):
        return 1
    return 0


def infer_structural_parents(
    candidates: list[RetrievalCandidate],
) -> list[RetrievalCandidate]:
    """Recover numbered ancestors from this scope/generation's own headings.

    Some PDF parsers emit flat section paths. Keep source chunks unchanged;
    inferred headings are retrieval metadata, never invented source content.
    """
    catalogue = {}
    for candidate in candidates:
        chunk = candidate.chunk
        scope = (chunk.document_id, chunk.metadata.get("index_generation"))
        for heading in (
            chunk.section_heading,
            *candidate.metadata.get("structural_parent_headings", ()),
        ):
            if match := _SECTION_NUMBER.match(heading):
                catalogue.setdefault((*scope, match.group(1)), heading)
    enriched = []
    for candidate in candidates:
        chunk = candidate.chunk
        scope = (chunk.document_id, chunk.metadata.get("index_generation"))
        match = _SECTION_NUMBER.match(chunk.section_heading)
        parts = match.group(1).split(".") if match else []
        parents = [
            catalogue[(*scope, ".".join(parts[:i]))]
            for i in range(1, len(parts))
            if (*scope, ".".join(parts[:i])) in catalogue
        ]
        enriched.append(
            candidate.model_copy(
                update={
                    "metadata": {
                        **candidate.metadata,
                        "structural_parent_headings": parents,
                    }
                }
            )
        )
    return enriched


def order_structural_candidates(
    candidates: list[RetrievalCandidate],
    section_aliases: tuple[str, ...],
) -> tuple[list[RetrievalCandidate], int]:
    candidates = infer_structural_parents(candidates)
    scored = [
        (index, candidate, section_match_priority(candidate, section_aliases))
        for index, candidate in enumerate(candidates)
    ]
    matching = [item for item in scored if item[2] > 0]
    matching_documents = {item[1].chunk.document_id for item in matching}
    single_matching_document = len(matching_documents) == 1

    if single_matching_document:
        matching.sort(
            key=lambda item: (
                -item[2],
                item[1].chunk.page_number
                if item[1].chunk.page_number is not None
                else 10**9,
                item[1].chunk.chunk_index,
                item[0],
            )
        )
    else:
        matching.sort(key=lambda item: (-item[2], item[0]))

    # Synonyms of one section form one bucket. Multiple requested sections take
    # turns, otherwise an early 30-chunk Methods section can consume every slot.
    normalized_aliases = {normalize_section_heading(alias) for alias in section_aliases}
    groups = [
        tuple(
            alias
            for alias in intent.section_aliases
            if normalize_section_heading(alias) in normalized_aliases
        )
        for intent, _patterns in _INTENTS
    ]
    groups = [group for group in groups if group]
    if len(groups) > 1:
        buckets: list[list] = [[] for _group in groups]
        for item in matching:
            priorities = [section_match_priority(item[1], group) for group in groups]
            buckets[max(range(len(groups)), key=lambda i: priorities[i])].append(item)
        for bucket_index, bucket in enumerate(buckets):
            leaves = {}
            for item in bucket:
                leaf = (item[1].chunk.document_id, item[1].chunk.section_heading)
                leaves.setdefault(leaf, []).append(item)
            leaf_lists = list(leaves.values())
            leaf_lists.sort(
                key=lambda leaf: (
                    all(
                        normalize_section_heading(item[1].chunk.text)
                        == normalize_section_heading(item[1].chunk.section_heading)
                        for item in leaf
                    ),
                    min(
                        (item[1].chunk.page_number or 10**9, item[1].chunk.chunk_index)
                        for item in leaf
                    ),
                )
            )
            for leaf in leaf_lists:
                leaf.sort(
                    key=lambda item: (
                        normalize_section_heading(item[1].chunk.text)
                        == normalize_section_heading(item[1].chunk.section_heading),
                        item[1].chunk.chunk_type not in {"paragraph_group", "table"},
                        -float(
                            item[1].rerank_score
                            if item[1].rerank_score is not None
                            else item[1].fusion_score or item[1].sparse_score or 0
                        ),
                    )
                )
            # A single long subsection must not occupy a whole section's quota.
            buckets[bucket_index] = [
                item
                for row in zip_longest(*leaf_lists)
                for item in row
                if item is not None
            ]
        matching = [
            item for row in zip_longest(*buckets) for item in row if item is not None
        ]

    non_matching = [item for item in scored if item[2] == 0]
    ordered = [candidate for _index, candidate, _priority in (*matching, *non_matching)]
    return ordered, len(matching)


def promote_structural_candidates(
    result: RetrievalResult,
    *,
    intent: StructuralRetrievalIntent | None,
    limit: int,
) -> RetrievalResult:
    if limit <= 0:
        raise ValueError("structural result limit must be positive")
    if intent is None or not result.candidates:
        return result.model_copy(update={"candidates": result.candidates[:limit]})

    ordered, matching_count = order_structural_candidates(
        result.candidates,
        intent.section_aliases,
    )
    candidates = [
        candidate.model_copy(update={"rank": rank})
        for rank, candidate in enumerate(ordered[:limit], start=1)
    ]
    metadata = dict(result.metadata)
    metadata.update(
        {
            "structural_intent": intent.name,
            "structural_section_hints": list(intent.section_aliases),
            "structural_match_count": matching_count,
        }
    )
    return result.model_copy(update={"candidates": candidates, "metadata": metadata})


__all__ = [
    "StructuralRetrievalIntent",
    "build_structural_queries",
    "detect_structural_intent",
    "normalize_section_heading",
    "order_structural_candidates",
    "promote_structural_candidates",
    "section_match_priority",
]
