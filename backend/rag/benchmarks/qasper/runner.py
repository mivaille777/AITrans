from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from app.ai.chat.models import ChatContext, ChatRequest
from app.ai.chat.service import AIChatService
from app.ai.gateway import LLMGateway
from backend.models.agent_react import AgentRetrievalObservation
from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.rag.benchmarks.cache import qasper_sample_hash
from backend.rag.benchmarks.common import (
    REPOSITORY_ROOT,
    atomic_write_json,
    atomic_write_jsonl,
    benchmark_root,
    read_json,
)
from backend.rag.benchmarks.qasper.ablation import (
    QASPER_ABLATION_VARIANTS,
    QasperAblationVariant,
    get_qasper_ablation_variant,
)
from backend.rag.benchmarks.qasper.alignment import align_qasper_evidence
from backend.rag.benchmarks.qasper.answer_contract import (
    QasperAnswerContract,
    QasperContractAnswer,
    parse_qasper_contract_answer,
    render_contract_answer,
    render_contract_for_verification,
)
from backend.rag.benchmarks.qasper.index import build_qasper_index
from backend.rag.benchmarks.qasper.sampling import (
    read_question_ids_file,
    sample_qasper_dataset,
)
from backend.rag.benchmarks.qasper.schema import QasperDataset, QasperQuestion
from backend.rag.citation_service import build_evidence_citations
from backend.rag.config import RagConfig
from backend.rag.embeddings import EmbeddingProvider, create_embedding_provider
from backend.rag.evaluation import percentile
from backend.rag.evidence_builder import build_agent_evidence
from backend.rag.evidence_requirements import (
    EvidenceRequirement,
    assess_evidence_requirements,
    evidence_requirement_coverage,
    infer_evidence_requirements,
)
from backend.rag.evidence_selection import (
    ContextualEvidenceExcerptProvider,
    EvidenceExcerptProvider,
    EvidenceSelectionService,
    ExtractiveEvidenceExcerptProvider,
)
from backend.rag.fusion import rrf_fuse
from backend.rag.model_manager import ModelManager
from backend.rag.models import RetrievalCandidate, RetrievalResult
from backend.rag.query_planner import RagQueryPlan, merge_query_results
from backend.rag.raptor import (
    ExtractiveRaptorSummaryProvider,
    RaptorSearchHit,
    RaptorSummaryProvider,
    RaptorTree,
    RaptorTreeBuilder,
    rank_summary_nodes,
)
from backend.rag.rerankers import Qwen3RerankerProvider
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.structure_retrieval import detect_structural_intent
from backend.services.agent_claim_evidence_verifier import AgentClaimEvidenceVerifier
from backend.services.agent_evidence_gate_service import AgentEvidenceGateService
from backend.services.grounded_synthesis_service import GroundedSynthesisService

RUN_LIMITS: dict[str, int | None] = {
    "smoke": 20,
    "dev": 100,
    "full": None,
}
BENCHMARK_FINAL_TOP_K = 20
DEFAULT_EVIDENCE_SELECTION_PROFILE: dict[str, Any] = {
    "profile_id": "p1q1-evidence-selection-v2",
    "profile_version": 2,
    "retrieval_variant": "CURRENT",
    "candidate_pool_size": 20,
    "default_variants": [
        "current_top20",
        "rerank_top5",
        "rerank_top8",
        "rerank_top10",
        "evidence_selection",
    ],
    "selected_top_k_by_variant": {
        "current_top20": 20,
        "rerank_top5": 5,
        "rerank_top8": 8,
        "rerank_top10": 10,
        "evidence_selection": 5,
    },
    "maximum_excerpt_tokens": 180,
    "excerpt_extractor": "extractive-sentence-spans-v1",
    "selection_order": "candidate_rank",
    "max_spans_per_source_chunk": 1,
    "fallback_to_source_chunk_for_multi_paragraph_coverage": True,
}
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_ANSWER_ONLY_RECOVERY_NOTICE = (
    "未展示未通过依据核验的补充说明，仅保留已核验的直接答案。"
)
_DIRECT_ANSWER_GENERIC_TERMS = {
    "a", "an", "and", "answer", "are", "as", "at", "based", "by", "data",
    "dataset", "datasets", "described", "describes", "does", "evidence", "for",
    "from", "has", "have", "in", "include", "includes", "included", "is", "it",
    "method", "methods", "model", "models", "of", "on", "or", "paper", "result",
    "results", "show", "shows", "study", "system", "the", "this", "to", "use",
    "used", "uses", "using", "was", "were", "with", "work",
}


def _verify_direct_contract_answer(
    answer: QasperContractAnswer,
    *,
    verifier: AgentClaimEvidenceVerifier,
    evidence: Sequence[AgentEvidenceItem],
    citations: Sequence[AgentCitationRef],
) -> tuple[QasperContractAnswer, Any] | None:
    """Keep a short answer only when its own cited claims pass strict grounding."""

    if answer.answer_type != "short" or answer.is_unanswerable:
        return None

    available_labels = {item.label for item in citations}
    labels = [label for label in answer.citations if label in available_labels]
    if not labels:
        return None

    def verify_labels(
        selected_labels: Sequence[str],
    ) -> tuple[QasperContractAnswer, Any] | None:
        if not selected_labels:
            return None
        candidate = replace(
            answer,
            citations=tuple(selected_labels),
            supporting_explanation="",
        )
        citation_text = " ".join(candidate.citations)
        output_text = f"Answer: {candidate.answer} {citation_text}".strip()
        result = verifier.verify(
            output_text=output_text,
            evidence=evidence,
            citations=citations,
        )
        if (
            not result.strict_passed
            or result.claim_count <= 0
            or result.unsupported_claim_count > 0
            or result.invalid_citation_count > 0
        ):
            return None
        return candidate, result

    verified = verify_labels(labels)
    if verified is None:
        return None

    recovered_answer, _ = verified
    evidence_by_id = {item.evidence_id: item for item in evidence}
    cited_evidence = [
        evidence_by_id[evidence_id]
        for citation in citations
        if citation.label in labels
        for evidence_id in citation.evidence_ids
        if evidence_id in evidence_by_id
    ]
    answer_claims = [
        claim.strip()
        for claim in re.split(r"(?<=[.!?。！？；;])\s+|\n+", recovered_answer.answer)
        if claim.strip()
    ]
    for claim in answer_claims:
        claim_terms = set(re.findall(r"[a-z0-9]+", claim.casefold()))
        claim_terms.difference_update(_DIRECT_ANSWER_GENERIC_TERMS)
        if len(claim_terms) < 2:
            return None
        if not any(
            len(
                claim_terms
                & (
                    set(re.findall(
                        r"[a-z0-9]+",
                        f"{item.title} {item.location} {item.excerpt}".casefold(),
                    ))
                    - _DIRECT_ANSWER_GENERIC_TERMS
                )
            )
            >= 2
            for item in cited_evidence
        ):
            return None

    # Remove labels that do not need to support the direct answer. The labels
    # still map to the exact evidence made available to the answer model.
    for label in tuple(labels):
        reduced = [item for item in labels if item != label]
        reduced_verification = verify_labels(reduced)
        if reduced_verification is not None:
            labels = reduced
            verified = reduced_verification
    return verified


@dataclass(frozen=True, slots=True)
class QasperGeneratedAnswer:
    answer: str
    provider: str = ""
    model: str = ""
    latency_ms: float = 0.0
    metadata: dict[str, Any] | None = None
    user_visible_answer: str | None = None


@dataclass(frozen=True, slots=True)
class QasperAnswerInput:
    """Gold-free input passed to any runtime answerer."""

    question_id: str
    paper_id: str
    question: str


class QasperAnswerer(Protocol):
    def __call__(
        self,
        question: QasperAnswerInput,
        retrieval: RetrievalResult,
    ) -> QasperGeneratedAnswer | str: ...


@dataclass(frozen=True, slots=True)
class QasperBenchmarkRunResult:
    run_id: str
    run_directory: Path
    manifest_path: Path
    predictions_path: Path
    retrieval_trace_path: Path
    metrics_path: Path
    errors_path: Path
    qrels_path: Path
    question_count: int
    error_count: int
    run_status: str


@dataclass(frozen=True, slots=True)
class QasperAblationSuiteResult:
    suite_id: str
    suite_directory: Path
    manifest_path: Path
    comparison_path: Path
    variant_count: int
    status: str


@dataclass(frozen=True, slots=True)
class QasperRaptorAblationSuiteResult:
    suite_id: str
    suite_directory: Path
    manifest_path: Path
    comparison_path: Path
    variant_count: int
    tree_count: int
    status: str


@dataclass(frozen=True, slots=True)
class QasperEvidenceSelectionSuiteResult:
    suite_id: str
    suite_directory: Path
    manifest_path: Path
    comparison_path: Path
    variant_count: int
    status: str


@dataclass(frozen=True, slots=True)
class QasperAdaptiveRetrievalSuiteResult:
    suite_id: str
    suite_directory: Path
    manifest_path: Path
    comparison_path: Path
    variant_count: int
    status: str


class _GroundedChatAdapter:
    def __init__(
        self,
        chat_service: AIChatService,
        *,
        answer_contract: QasperAnswerContract | None = None,
    ) -> None:
        self._chat_service = chat_service
        self._answer_contract = answer_contract
        self.last_raw_model_output = ""
        self.last_normalized_output = ""
        self.last_contract_answer: QasperContractAnswer | None = None
        self.last_contract_error = ""

    def send(self, **kwargs: Any) -> Any:
        user_message = str(kwargs.get("user_message", "") or "")
        self.last_raw_model_output = ""
        self.last_normalized_output = ""
        self.last_contract_answer = None
        self.last_contract_error = ""
        if self._answer_contract is not None:
            user_message = self._answer_contract.append_prompt(user_message)
        request = ChatRequest(
            session_id=str(kwargs.get("session_id", "qasper") or "qasper"),
            user_message=user_message,
            context=ChatContext(),
            tool_name=str(kwargs.get("tool_name", "search_knowledge_base") or ""),
            tool_context=str(kwargs.get("tool_context", "") or ""),
        )
        answer = self._chat_service.execute(request)
        self.last_raw_model_output = str(answer.output_text or "")
        if self._answer_contract is None:
            self.last_normalized_output = self.last_raw_model_output
            return answer
        try:
            parsed = parse_qasper_contract_answer(
                self.last_raw_model_output,
                contract=self._answer_contract,
                allowed_citations=kwargs.get("answer_contract_citation_labels", ()),
            )
        except (TypeError, ValueError) as exc:
            self.last_contract_error = str(exc)
            self.last_normalized_output = self.last_raw_model_output
            return answer
        self.last_contract_answer = parsed
        self.last_normalized_output = render_contract_for_verification(parsed)
        return replace(answer, output_text=self.last_normalized_output)


class GroundedQasperAnswerer:
    """Generate answers through AITrans chat and grounded synthesis services."""

    def __init__(
        self,
        text_service: Any | None = None,
        *,
        answer_contract: QasperAnswerContract | Mapping[str, Any] | None = None,
        answer_contract_sha256: str | None = None,
    ) -> None:
        if isinstance(answer_contract, Mapping):
            answer_contract = QasperAnswerContract.from_mapping(
                answer_contract,
                raw_sha256=answer_contract_sha256,
            )
        self._answer_contract = answer_contract
        self._text_service = text_service or LLMGateway().create_text_service(
            "agent_synthesis"
        )
        self._chat_service = AIChatService(self._text_service)
        self._chat_adapter = _GroundedChatAdapter(
            self._chat_service,
            answer_contract=answer_contract,
        )
        self._claim_verifier = AgentClaimEvidenceVerifier()
        self._repair_trace: dict[str, Any] = {}
        self._repair_initial_contract_answer: QasperContractAnswer | None = None
        self._grounded = GroundedSynthesisService(
            chat_service=self._chat_adapter,
            verifier=self._claim_verifier,
            repairer=self._repair_unsupported_answer,
        )

    @property
    def provider(self) -> str:
        return str(getattr(self._text_service, "provider_name", "") or "")

    @property
    def model(self) -> str:
        return str(getattr(self._text_service, "model", "") or "")

    @property
    def prompt_id(self) -> str:
        contract = self.answer_contract_manifest
        if isinstance(contract, dict):
            contract_id = str(contract.get("contract_id", "") or "").strip()
            if contract_id:
                return contract_id
        return "qasper-grounded-synthesis-v1"

    @property
    def answer_contract_manifest(self) -> dict[str, Any] | None:
        return (
            self._answer_contract.manifest()
            if self._answer_contract is not None
            else None
        )

    def _repair_unsupported_answer(
        self,
        *,
        output_text: str,
        verification: Any,
        evidence: Sequence[AgentEvidenceItem],
        citations: Sequence[AgentCitationRef],
        request: dict[str, Any],
    ) -> Any:
        self._repair_initial_contract_answer = self._chat_adapter.last_contract_answer
        self._repair_trace = {
            "initial_model_output": self._chat_adapter.last_raw_model_output,
            "initial_verification_input": output_text,
            "initial_normalized_output": self._chat_adapter.last_normalized_output,
            "initial_contract_error": self._chat_adapter.last_contract_error,
            "repair_prompt": "claim_evidence_repair_v1",
            "initial_claim_count": int(verification.claim_count),
            "initial_unsupported_claim_count": int(
                verification.unsupported_claim_count
            ),
            "initial_invalid_citation_count": int(
                verification.invalid_citation_count
            ),
            "initial_reason_codes": list(verification.reason_codes),
        }
        allowed_labels = request.get("answer_contract_citation_labels", ())
        label_text = ", ".join(str(item) for item in allowed_labels) or "none"
        repair_request = dict(request)
        repair_request["user_message"] = (
            f"Original question: {request.get('user_message', '')}\n\n"
            "The previous draft failed evidence and citation verification. Rewrite it "
            "using only the supplied paper evidence. Remove every unsupported claim, "
            "keep the direct answer concise, and cite only these available labels: "
            f"{label_text}. If the paper evidence cannot support an answer, use exactly "
            "Unanswerable (or the contract's designated unanswerable form). Do not add "
            "outside knowledge.\n\n"
            f"Previous draft:\n{output_text}\n\n"
            "Verification findings: "
            f"{', '.join(verification.reason_codes) or 'unsupported_claim'}."
        )
        repaired_answer = self._chat_adapter.send(**repair_request)
        repair_verification_input = self._chat_adapter.last_normalized_output
        repair_full_verification = self._claim_verifier.verify(
            output_text=repair_verification_input,
            evidence=evidence,
            citations=citations,
        )
        self._repair_trace.update(
            {
                "repair_model_output": self._chat_adapter.last_raw_model_output,
                "repair_verification_input": repair_verification_input,
                "repair_contract_error": self._chat_adapter.last_contract_error,
                "repair_full_claim_count": repair_full_verification.claim_count,
                "repair_full_unsupported_claim_count": (
                    repair_full_verification.unsupported_claim_count
                ),
                "repair_full_invalid_citation_count": (
                    repair_full_verification.invalid_citation_count
                ),
                "repair_full_strict_passed": repair_full_verification.strict_passed,
                "repair_full_reason_codes": list(
                    repair_full_verification.reason_codes
                ),
            }
        )

        if self._answer_contract is not None:
            recovery_candidates = [
                ("repair", self._chat_adapter.last_contract_answer),
                ("initial", self._repair_initial_contract_answer),
            ]
            for source, candidate in recovery_candidates:
                if candidate is None:
                    continue
                recovered = _verify_direct_contract_answer(
                    candidate,
                    verifier=self._claim_verifier,
                    evidence=evidence,
                    citations=citations,
                )
                if recovered is None:
                    continue
                recovered_answer, direct_verification = recovered
                self._chat_adapter.last_contract_answer = recovered_answer
                self._chat_adapter.last_normalized_output = (
                    render_contract_for_verification(recovered_answer)
                )
                self._repair_trace["answer_only_recovery"] = {
                    "used": True,
                    "source": source,
                    "answer": recovered_answer.answer,
                    "citations": list(recovered_answer.citations),
                    "claim_count": direct_verification.claim_count,
                    "unsupported_claim_count": (
                        direct_verification.unsupported_claim_count
                    ),
                    "invalid_citation_count": (
                        direct_verification.invalid_citation_count
                    ),
                    "reason_codes": list(direct_verification.reason_codes),
                }
                return replace(
                    repaired_answer,
                    output_text=self._chat_adapter.last_normalized_output,
                )

            self._repair_trace["answer_only_recovery"] = {"used": False}
        return repaired_answer

    def __call__(
        self,
        question: QasperAnswerInput | QasperQuestion,
        retrieval: RetrievalResult,
    ) -> QasperGeneratedAnswer:
        self._repair_trace = {}
        self._repair_initial_contract_answer = None
        self._chat_adapter.last_raw_model_output = ""
        self._chat_adapter.last_normalized_output = ""
        self._chat_adapter.last_contract_answer = None
        self._chat_adapter.last_contract_error = ""
        evidence = build_agent_evidence(retrieval)
        if not evidence:
            metadata: dict[str, Any] = {
                "abstained": True,
                "reason": "no_retrieved_evidence",
                "answer_llm_invocation_count": 0,
            }
            if self._answer_contract is not None:
                metadata["answer_contract_status"] = "not_invoked"
            return QasperGeneratedAnswer(
                answer="Unanswerable",
                provider="policy",
                model="insufficient-evidence",
                metadata=metadata,
                user_visible_answer="Unanswerable",
            )
        citations = build_evidence_citations(evidence)
        context_overrides = _supplemental_context_overrides(retrieval)
        started = perf_counter()
        result = self._grounded.send_verified(
            evidence=evidence,
            citations=citations,
            context_overrides=context_overrides,
            session_id=f"qasper-{question.question_id}",
            user_message=question.question,
            answer_contract_citation_labels=[item.label for item in citations],
        )
        if result.repair_attempted and not result.repair_succeeded:
            self._chat_adapter.last_contract_answer = (
                self._repair_initial_contract_answer
            )
            self._chat_adapter.last_contract_error = str(
                self._repair_trace.get("initial_contract_error", "") or ""
            )
            self._chat_adapter.last_normalized_output = str(
                self._repair_trace.get("initial_normalized_output", "") or ""
            )
        metadata = {
            "fallback_applied": result.fallback_applied,
            "partial_grounding": result.partial_grounding,
            "verification_passed": (
                bool(result.verification.passed)
                if result.verification is not None
                else None
            ),
            "claim_count": (
                int(result.verification.claim_count)
                if result.verification is not None
                else 0
            ),
            "unsupported_claim_count": (
                int(result.verification.unsupported_claim_count)
                if result.verification is not None
                else 0
            ),
            "unsupported_claim_rate": (
                result.verification.unsupported_claim_count
                / result.verification.claim_count
                if result.verification is not None
                and result.verification.claim_count > 0
                else None
            ),
            "claim_repair_attempted": result.repair_attempted,
            "claim_repair_succeeded": result.repair_succeeded,
            "claim_repair_error": result.repair_error,
            "extra_llm_invocation_count": int(result.repair_attempted),
            "answer_llm_invocation_count": (
                int(
                    bool(
                        self._repair_trace.get("initial_model_output")
                        or self._chat_adapter.last_raw_model_output
                    )
                )
                + int(result.repair_attempted)
            ),
            "claim_repair_trace": self._repair_trace,
            "initial_claim_count": (
                int(result.initial_verification.claim_count)
                if result.initial_verification is not None
                else 0
            ),
            "initial_unsupported_claim_count": (
                int(result.initial_verification.unsupported_claim_count)
                if result.initial_verification is not None
                else 0
            ),
            "repair_unsupported_claim_count": (
                self._repair_trace.get(
                    "repair_full_unsupported_claim_count",
                    (
                        int(result.repair_verification.unsupported_claim_count)
                        if result.repair_verification is not None
                        else None
                    ),
                )
            ),
            "repair_claim_count": (
                self._repair_trace.get(
                    "repair_full_claim_count",
                    (
                        int(result.repair_verification.claim_count)
                        if result.repair_verification is not None
                        else None
                    ),
                )
            ),
            "raw_model_output": str(
                self._repair_trace.get("initial_model_output")
                or self._chat_adapter.last_raw_model_output
            ),
            "repair_model_output": self._repair_trace.get("repair_model_output"),
            "grounded_verification_input": self._chat_adapter.last_normalized_output,
            "verified_final_output": result.answer.output_text,
        }
        answer_text = result.answer.output_text
        user_visible_answer = answer_text
        normalized_answer = answer_text.strip().casefold().rstrip(".!。！")
        metadata.update(
            {
                "abstained": normalized_answer in {"unanswerable", "no answer"},
                "abstention_reason": (
                    "model_unanswerable_after_claim_repair"
                    if result.repair_succeeded
                    and normalized_answer in {"unanswerable", "no answer"}
                    else (
                        "model_unanswerable"
                        if normalized_answer in {"unanswerable", "no answer"}
                        else ""
                    )
                ),
            }
        )
        if self._answer_contract is not None:
            parsed = self._chat_adapter.last_contract_answer
            answer_only_recovery = self._repair_trace.get(
                "answer_only_recovery", {}
            )
            answer_only_recovery_used = bool(
                isinstance(answer_only_recovery, Mapping)
                and answer_only_recovery.get("used")
            )
            contract_status = "valid" if parsed is not None else "invalid_format_fallback"
            verification_fallback = bool(result.fallback_applied)
            if parsed is None or verification_fallback:
                answer_text = "Unanswerable"
                user_visible_answer = "Unanswerable"
            else:
                answer_text = parsed.answer
                user_visible_answer = render_contract_answer(
                    parsed,
                    include_partial_grounding_notice=(
                        "部分解释未能逐句通过引用一致性校验。"
                        if result.partial_grounding
                        else (
                            _ANSWER_ONLY_RECOVERY_NOTICE
                            if answer_only_recovery_used
                            else ""
                        )
                    ),
                )
            metadata.update(
                {
                    "answer_contract_status": contract_status,
                    "answer_contract_id": self._answer_contract.contract_id,
                    "answer_contract_version": self._answer_contract.version,
                    "answer_contract_parse_error": self._chat_adapter.last_contract_error,
                    "answer_contract_answer_type": (
                        parsed.answer_type
                        if parsed is not None
                        else "invalid_format_fallback"
                    ),
                    "answer_contract_citations": (
                        list(parsed.citations) if parsed is not None else []
                    ),
                    "answer_contract_citation_reconciled": (
                        parsed.citation_reconciled if parsed is not None else False
                    ),
                    "answer_contract_citation_label_normalization_count": (
                        parsed.citation_label_normalization_count
                        if parsed is not None
                        else 0
                    ),
                    "answer_contract_normalized_extra_keys": (
                        list(parsed.normalized_extra_keys) if parsed is not None else []
                    ),
                    "answer_contract_boolean_prefix_normalized": (
                        parsed.boolean_prefix_normalized
                        if parsed is not None
                        else False
                    ),
                    "answer_contract_citation_validation_passed": parsed is not None,
                    "answer_contract_model_abstained": (
                        parsed.is_unanswerable if parsed is not None else False
                    ),
                    "answer_only_recovery_used": answer_only_recovery_used,
                    "answer_only_recovery": answer_only_recovery,
                    "abstained": bool(
                        parsed is None
                        or verification_fallback
                        or parsed.is_unanswerable
                    ),
                    "direct_answer": answer_text,
                    "supporting_explanation": (
                        parsed.supporting_explanation if parsed is not None else ""
                    ),
                    "raw_model_output": metadata["raw_model_output"],
                    "repair_model_output": metadata["repair_model_output"],
                    "grounded_verification_input": self._chat_adapter.last_normalized_output,
                    "verified_final_output": result.answer.output_text,
                    "user_visible_final_output": user_visible_answer,
                    "answer_token_estimate": (len(answer_text) + 3) // 4,
                    "user_visible_token_estimate": (len(user_visible_answer) + 3) // 4,
                    "abstention_reason": (
                        "invalid_answer_contract"
                        if parsed is None
                        else (
                    "grounding_verification_fallback"
                            if verification_fallback
                            else ("model_unanswerable" if parsed.is_unanswerable else "")
                        )
                    ),
                }
            )
        verifier_abstention = bool(result.fallback_applied) or bool(
            result.repair_attempted
            and not result.repair_succeeded
            and result.verification is not None
            and (
                result.verification.unsupported_claim_count > 0
                or result.verification.invalid_citation_count > 0
            )
        )
        if verifier_abstention:
            answer_text = "Unanswerable"
            user_visible_answer = "Unanswerable"
            metadata.update(
                {
                    "abstained": True,
                    "abstention_reason": (
                        "grounding_verification_fallback"
                        if result.fallback_applied
                        else "claim_repair_verification_failed"
                    ),
                    "direct_answer": "Unanswerable",
                    "claim_count": 0,
                    "unsupported_claim_count": 0,
                    "unsupported_claim_rate": None,
                    "user_visible_final_output": "Unanswerable",
                    "verified_final_output": "Unanswerable",
                }
            )
            if self._answer_contract is not None:
                metadata["answer_contract_final_answer_type"] = "unanswerable"
                metadata["answer_token_estimate"] = (len(answer_text) + 3) // 4
                metadata["user_visible_token_estimate"] = (
                    len(user_visible_answer) + 3
                ) // 4
        metadata["user_visible_final_output"] = user_visible_answer
        return QasperGeneratedAnswer(
            answer=answer_text,
            provider=result.answer.provider or self.provider,
            model=result.answer.model or self.model,
            latency_ms=(perf_counter() - started) * 1000,
            metadata=metadata,
            user_visible_answer=user_visible_answer,
        )

    def close(self) -> None:
        close = getattr(self._text_service, "close", None)
        if callable(close):
            close()


def _answer_fields(question: QasperQuestion, aligned: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "question_id": question.question_id,
        "paper_id": question.paper_id,
        "question": question.question,
        "expected_retrieval": True,
        "no_answer": bool(question.answers)
        and all(answer.unanswerable for answer in question.answers),
        "answers": [
            {
                "annotation_id": answer.annotation_id,
                "answer_type": answer.answer_type,
                "answer": answer.answer_text,
                "extractive_spans": list(answer.extractive_spans),
                "free_form_answer": answer.free_form_answer,
                "yes_no": answer.yes_no,
                "evidence_texts": list(answer.evidence_texts),
                "highlighted_evidence": list(answer.highlighted_evidence),
                "evidence_paragraph_ids": list(item.paragraph_ids),
                "evidence_complete": item.evidence_complete,
            }
            for answer, item in zip(question.answers, aligned, strict=True)
        ],
        "gold_evidence_paragraph_ids": sorted(
            {
                paragraph_id
                for item in aligned
                for paragraph_id in item.paragraph_ids
            }
        ),
    }


def _source_paragraph_ids(chunk: Any) -> list[str]:
    benchmark = chunk.metadata.get("benchmark", {})
    paragraph_ids = (
        benchmark.get("source_paragraph_ids", [])
        if isinstance(benchmark, dict)
        else []
    )
    return [item for item in paragraph_ids if isinstance(item, str)]


def _candidate_context_chunks(candidate: Any) -> list[Any]:
    context_window = candidate.context_window
    if context_window is not None and context_window.chunks:
        return context_window.chunks
    return [candidate.chunk]


def _supplemental_context_overrides(retrieval: RetrievalResult) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for candidate in retrieval.candidates:
        window = candidate.context_window
        if window is None:
            continue
        supplemental: list[str] = []
        for chunk in window.chunks:
            if chunk.chunk_id == candidate.chunk.chunk_id:
                continue
            location = " / ".join(chunk.section_path) or chunk.section_heading or "same section"
            supplemental.append(f"[Supplemental {location}]\n{chunk.text.strip()}")
        text = "\n\n".join(item for item in supplemental if item.strip())
        if text:
            overrides[f"evidence:{candidate.chunk.chunk_id}"] = text
    return overrides


def _candidate_trace(candidate: Any) -> dict[str, Any]:
    chunk = candidate.chunk
    context_window = candidate.context_window
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "rank": candidate.rank,
        "text": chunk.text,
        "title": chunk.title,
        "token_count": chunk.token_count,
        "section_heading": chunk.section_heading,
        "section_path": chunk.section_path,
        "source_paragraph_ids": _source_paragraph_ids(chunk),
        "scores": {
            "dense": candidate.dense_score,
            "sparse": candidate.sparse_score,
            "fusion": candidate.fusion_score,
            "rerank": candidate.rerank_score,
        },
        "metadata": candidate.metadata,
        "context_window": (
            {
                "anchor_chunk_id": context_window.anchor_chunk_id,
                "chunk_ids": [item.chunk_id for item in context_window.chunks],
                "source_paragraph_ids": list(
                    dict.fromkeys(
                        paragraph_id
                        for context_chunk in context_window.chunks
                        for paragraph_id in _source_paragraph_ids(context_chunk)
                    )
                ),
                "text": context_window.text,
                "token_count": context_window.token_count,
            }
            if context_window is not None
            else None
        ),
    }


_RETRIEVAL_COMPONENTS = (
    "query_planning_ms",
    "embedding_ms",
    "dense_search_ms",
    "sparse_search_ms",
    "structural_search_ms",
    "fusion_ms",
    "rerank_ms",
    "small_to_big_ms",
)
_RETRIEVAL_STAGE_IDS = (
    "dense_chunk_ids",
    "sparse_chunk_ids",
    "structural_chunk_ids",
    "pre_rerank_chunk_ids",
)


def _identity_query_plan(query: str) -> RagQueryPlan:
    return RagQueryPlan(original_query=query, rewritten_query=query, subqueries=[])


def _raptor_summary_candidates(
    hits: Sequence[RaptorSearchHit],
    *,
    index: Any,
) -> list[RetrievalCandidate]:
    candidates: list[RetrievalCandidate] = []
    seen_chunk_ids: set[str] = set()
    for hit in hits:
        for chunk_id in hit.node.descendant_chunk_ids:
            if chunk_id in seen_chunk_ids:
                continue
            chunk = index.runtime.sparse_retriever.get_chunk(chunk_id)
            if chunk is None or chunk.document_id != hit.node.document_id:
                continue
            seen_chunk_ids.add(chunk_id)
            candidates.append(
                RetrievalCandidate(
                    chunk=chunk,
                    fusion_score=hit.score,
                    rank=len(candidates) + 1,
                    metadata={
                        "raptor_summary_node_id": hit.node.node_id,
                        "raptor_summary_level": hit.node.level,
                        "raptor_summary_score": hit.score,
                    },
                )
            )
    return candidates


def _raptor_hit_trace(hits: Sequence[RaptorSearchHit]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": hit.node.node_id,
            "level": hit.node.level,
            "score": hit.score,
            "descendant_chunk_count": len(hit.node.descendant_chunk_ids),
            "descendant_paragraph_ids": list(hit.node.descendant_paragraph_ids),
        }
        for hit in hits
    ]


def _select_raptor_evidence(
    query: str,
    *,
    paper: Any,
    retrieval: RetrievalResult,
    selector: EvidenceSelectionService,
    profile: Mapping[str, Any],
) -> list[RetrievalCandidate]:
    """Apply the same source-owned excerpt/fallback policy to RAPTOR leaves."""
    pool = list(retrieval.candidates)
    top_k = _evidence_selection_variant_top_k("evidence_selection", profile)
    fallback_enabled = bool(
        profile.get("fallback_to_source_chunk_for_multi_paragraph_coverage", False)
    )
    if not fallback_enabled:
        raise ValueError("RAPTOR selection requires source-chunk coverage fallback")
    selection_input = pool[:top_k] if fallback_enabled else pool
    selection = selector.select(
        query,
        selection_input,
        top_n=len(selection_input),
        top_k=top_k,
        selection_order=str(profile.get("selection_order", "relevance")),
        max_spans_per_source_chunk=profile.get("max_spans_per_source_chunk"),
    )
    mapped = _retain_only_excerpt_paragraphs(
        [item.candidate for item in selection.selected], paper=paper
    )
    selected_by_source = {
        str(item.metadata.get("evidence_selection", {}).get("source_chunk_id")): item
        for item in mapped
    }
    selection_trace = selection.as_dict()
    selection_trace.update(
        {
            "selection_order": profile.get("selection_order", "relevance"),
            "max_spans_per_source_chunk": profile.get("max_spans_per_source_chunk"),
            "retrieval_candidate_pool_count": len(pool),
            "selection_input_candidate_count": len(selection_input),
        }
    )
    final: list[RetrievalCandidate] = []
    fallback_traces: list[dict[str, Any]] = []
    no_valid_excerpt_count = 0
    for source in selection_input:
        source_id = source.chunk.chunk_id
        excerpt = selected_by_source.get(source_id)
        original_ids = _source_paragraph_ids(source.chunk)
        matched_ids = _source_paragraph_ids(excerpt.chunk) if excerpt else []
        no_valid_excerpt = not bool(excerpt and matched_ids)
        covers_source = bool(original_ids) and set(original_ids).issubset(matched_ids)
        fallback = no_valid_excerpt or (fallback_enabled and not covers_source)
        if fallback:
            no_valid_excerpt_count += int(no_valid_excerpt)
            reason = (
                "no_scored_excerpt"
                if excerpt is None
                else (
                    "excerpt_has_no_source_paragraph_mapping"
                    if no_valid_excerpt
                    else "excerpt_does_not_cover_all_source_paragraphs"
                )
            )
            metadata = dict(source.metadata)
            metadata["evidence_selection"] = {
                "source_chunk_id": source_id,
                "fallback_applied": True,
                "fallback_reason": reason,
                "no_valid_excerpt": no_valid_excerpt,
                "source_paragraph_ids": original_ids,
                "matched_paragraph_ids": matched_ids,
            }
            chosen = source.model_copy(
                update={"context_window": None, "metadata": metadata}
            )
            fallback_traces.append(
                {
                    "source_chunk_id": source_id,
                    "final_action": "source_chunk_fallback",
                    "fallback_applied": True,
                    "fallback_reason": reason,
                    "no_valid_excerpt": no_valid_excerpt,
                    "source_paragraph_ids": original_ids,
                    "matched_paragraph_ids": matched_ids,
                }
            )
        else:
            chosen = excerpt.model_copy(
                update={"context_window": None, "rank": source.rank}
            )
        final.append(chosen)
    selection_trace.update(
        {
            "mapped_selected_span_count": sum(
                bool(_source_paragraph_ids(item.chunk)) for item in mapped
            ),
            "unmapped_selected_span_count": len(selection.selected)
            - sum(bool(_source_paragraph_ids(item.chunk)) for item in mapped),
            "fallback_count": len(fallback_traces),
            "fallbacks": fallback_traces,
            "no_valid_excerpt_count": no_valid_excerpt_count,
            "no_valid_excerpt": bool(no_valid_excerpt_count),
            "final_selected_evidence_count": len(final),
        }
    )
    retrieval.candidates = final
    retrieval.metadata.update(
        {
            "evidence_selection": selection_trace,
            "evidence_extraction_ms": selection.extraction_ms,
            "evidence_scoring_ms": selection.scoring_ms,
            "evidence_extractor_invocations": (
                0
                if selection.extractor_model
                in {"extractive-sentence-spans-v1", "extractive-contextual-spans-v1"}
                else selection.candidate_pool_count
            ),
            "evidence_selection_pool_chunk_ids": [item.chunk.chunk_id for item in pool],
            "candidate_pool_size": int(profile["candidate_pool_size"]),
            "selected_top_k": top_k,
            "no_valid_excerpt": bool(no_valid_excerpt_count),
        }
    )
    return pool


def _retrieve_raptor_question(
    query: str,
    *,
    index: Any,
    document_id: str,
    tree: RaptorTree,
    variant: str,
) -> tuple[RetrievalResult, dict[str, Any]]:
    if variant not in {"R0", "R1", "R2", "R3"}:
        raise ValueError("RAPTOR variant must be R0, R1, R2, or R3")
    started = perf_counter()
    filters = VectorSearchFilter(document_ids=[document_id])
    summary_hits: list[RaptorSearchHit] = []
    summary_search_ms = 0.0
    fallback_reason = ""
    stage_metadata: dict[str, Any] = {}

    if variant == "R0":
        intent = detect_structural_intent(query)
        result = index.runtime.retrieval_service.retrieve(
            query,
            filters=filters,
            section_hints=intent.section_aliases if intent is not None else (),
            final_top_k=BENCHMARK_FINAL_TOP_K,
            dense_enabled=True,
            sparse_enabled=True,
            structural_enabled=True,
            reranker_enabled=True,
            small_to_big_enabled=False,
        )
        candidates = result.candidates
        strategy = "flat-structural"
    else:
        query_vector = index.runtime.embedding_provider.embed_query(query)
        summary_started = perf_counter()
        summary_hits = rank_summary_nodes(query_vector, tree, top_k=8)
        summary_search_ms = (perf_counter() - summary_started) * 1000
        summary_candidates = _raptor_summary_candidates(summary_hits, index=index)
        if not summary_candidates:
            fallback_result, fallback_round = _retrieve_raptor_question(
                query,
                index=index,
                document_id=document_id,
                tree=tree,
                variant="R0",
            )
            fallback_result.metadata.update(
                {
                    "raptor_variant": variant,
                    "raptor_fallback_reason": "empty_summary_candidates",
                    "raptor_summary_hits": _raptor_hit_trace(summary_hits),
                    "raptor_summary_search_ms": summary_search_ms,
                }
            )
            fallback_round["raptor_fallback_reason"] = "empty_summary_candidates"
            return fallback_result, fallback_round

        if variant == "R1":
            leaf_candidates = index.runtime.vector_store.search(
                query_vector,
                top_k=BENCHMARK_FINAL_TOP_K,
                filters=filters,
            )
            candidates = rrf_fuse(
                [leaf_candidates, summary_candidates],
                limit=BENCHMARK_FINAL_TOP_K,
            )
            stage_metadata = {
                "dense_count": len(leaf_candidates),
                "dense_chunk_ids": [item.chunk.chunk_id for item in leaf_candidates],
                "sparse_count": 0,
                "reranker_applied": False,
            }
            strategy = "raptor-mixed-leaf-summary"
        elif variant == "R2":
            candidates = rrf_fuse(
                [summary_candidates],
                limit=BENCHMARK_FINAL_TOP_K,
            )
            stage_metadata = {
                "dense_count": 0,
                "sparse_count": 0,
                "reranker_applied": False,
            }
            strategy = "raptor-collapsed-summary"
        else:
            base_result = index.runtime.retrieval_service.retrieve(
                query,
                filters=filters,
                final_top_k=BENCHMARK_FINAL_TOP_K,
                dense_enabled=True,
                sparse_enabled=True,
                structural_enabled=False,
                reranker_enabled=False,
                small_to_big_enabled=False,
            )
            stage_metadata = dict(base_result.metadata)
            candidates = rrf_fuse(
                [base_result.candidates, summary_candidates],
                limit=max(BENCHMARK_FINAL_TOP_K, index.runtime.config.retrieval.fusion_top_k),
            )
            try:
                candidates = index.runtime.reranker.rerank(
                    query,
                    candidates,
                    top_k=min(BENCHMARK_FINAL_TOP_K, len(candidates)),
                )
                stage_metadata["reranker_applied"] = True
            except Exception as exc:  # noqa: BLE001 - retain fused RAPTOR candidates
                fallback_reason = str(exc) or exc.__class__.__name__
                stage_metadata["reranker_applied"] = False
            strategy = "raptor-hybrid-rerank"

        if variant != "R2" and not candidates:
            fallback_reason = fallback_reason or "empty_raptor_candidate_pool"

        result = RetrievalResult(
            query=query,
            candidates=candidates,
            retrieval_strategy=strategy,
            elapsed_ms=(perf_counter() - started) * 1000,
            metadata=stage_metadata,
        )

    total_ms = (perf_counter() - started) * 1000
    result.metadata.update(
        {
            "raptor_variant": variant,
            "raptor_tree_fingerprint": tree.fingerprint,
            "raptor_tree_cache_hit": tree.cache_hit,
            "raptor_summary_node_count": len(tree.nodes),
            "raptor_summary_search_ms": summary_search_ms,
            "raptor_summary_hits": _raptor_hit_trace(summary_hits),
            "raptor_fallback_reason": fallback_reason,
            "query_planning_ms": 0.0,
        }
    )
    result.elapsed_ms = total_ms
    source_paragraph_ids = list(
        dict.fromkeys(
            paragraph_id
            for candidate in result.candidates
            for context_chunk in _candidate_context_chunks(candidate)
            for paragraph_id in _source_paragraph_ids(context_chunk)
        )
    )
    round_trace = {
        "round": 1,
        "query": query,
        "latency_ms": total_ms,
        "candidate_chunk_ids": [item.chunk.chunk_id for item in result.candidates],
        "source_paragraph_ids": source_paragraph_ids,
        "context_evidence_paragraph_ids": source_paragraph_ids,
        "context_token_count": sum(item.chunk.token_count for item in result.candidates),
        "new_chunk_count": len(result.candidates),
        "raptor_summary_hits": _raptor_hit_trace(summary_hits),
    }
    return result, round_trace


def _raptor_question_category(
    *,
    question: QasperQuestion,
    paper: Any,
    aligned_answers: Sequence[Any],
) -> str:
    section_by_paragraph = {
        paragraph.paragraph_id: paragraph.section_index
        for paragraph in paper.paragraphs
    }
    breadth = max(
        (
            len(
                {
                    section_by_paragraph[paragraph_id]
                    for paragraph_id in answer.paragraph_ids
                    if paragraph_id in section_by_paragraph
                }
            )
            for answer in aligned_answers
            if answer.paragraph_ids and answer.evidence_complete
        ),
        default=0,
    )
    if not breadth:
        if all(answer.unanswerable for answer in question.answers):
            return "unanswerable"
        return "unclassified"
    if breadth == 1:
        return "local"
    if breadth == 2:
        return "cross_section"
    return "global"


def _aggregate_retrievals(
    original_query: str,
    retrievals: list[RetrievalResult],
) -> RetrievalResult:
    if not retrievals:
        raise ValueError("at least one successful retrieval is required")
    if len(retrievals) == 1:
        merged = retrievals[0]
    else:
        merged = merge_query_results(
            original_query,
            retrievals,
            limit=BENCHMARK_FINAL_TOP_K,
        )

    metadata = dict(merged.metadata)
    for key in _RETRIEVAL_COMPONENTS:
        metadata[key] = sum(float(item.metadata.get(key, 0.0) or 0.0) for item in retrievals)
    for key in _RETRIEVAL_STAGE_IDS:
        metadata[key] = list(
            dict.fromkeys(
                chunk_id
                for item in retrievals
                for chunk_id in item.metadata.get(key, [])
                if isinstance(chunk_id, str) and chunk_id
            )
        )
    for key in ("dense_count", "sparse_count", "structural_count"):
        metadata[key] = sum(int(item.metadata.get(key, 0) or 0) for item in retrievals)
    metadata.update(
        {
            "query_count": len(retrievals),
            "retrieval_queries": [item.query for item in retrievals],
            "fusion_count": len(
                {
                    candidate.chunk.chunk_id
                    for item in retrievals
                    for candidate in item.candidates
                }
            ),
            "final_count": len(merged.candidates),
            "reranker_applied": any(
                bool(item.metadata.get("reranker_applied")) for item in retrievals
            ),
            "reranker_enabled": any(
                bool(item.metadata.get("reranker_enabled")) for item in retrievals
            ),
            "small_to_big_enabled": any(
                bool(item.metadata.get("small_to_big_enabled")) for item in retrievals
            ),
        }
    )
    return merged.model_copy(
        update={
            "query": original_query,
            "metadata": metadata,
        }
    )


def _gate_evidence(retrieval: RetrievalResult) -> list[AgentEvidenceItem]:
    items: list[AgentEvidenceItem] = []
    for candidate in retrieval.candidates:
        chunk = candidate.chunk
        score = (
            candidate.rerank_score
            if candidate.rerank_score is not None
            else candidate.fusion_score
        )
        items.append(
            AgentEvidenceItem(
                evidence_id=chunk.chunk_id,
                source_type="qasper_paper",
                source_id=chunk.document_id,
                title=chunk.title,
                location=" / ".join(chunk.section_path) or chunk.section_heading,
                excerpt=chunk.text,
                score=score,
                metadata={"source_paragraph_ids": _source_paragraph_ids(chunk)},
            )
        )
    return items


def _retrieve_variant_question(
    question: QasperQuestion,
    *,
    index: Any,
    document_id: str,
    variant: QasperAblationVariant,
    query_planner: Any | None,
) -> tuple[
    RetrievalResult,
    RagQueryPlan,
    list[dict[str, Any]],
    dict[str, Any] | None,
    float,
]:
    planning_started = perf_counter()
    plan = (
        query_planner.plan(question.question)
        if variant.multi_query and query_planner is not None
        else _identity_query_plan(question.question)
    )
    planning_ms = (perf_counter() - planning_started) * 1000
    retrieval_queries = list(plan.retrieval_queries) if variant.multi_query else [question.question]
    if variant.evidence_gate and len(retrieval_queries) < 2:
        follow_up_query = f"{question.question} supporting evidence"
        if follow_up_query.casefold() not in {item.casefold() for item in retrieval_queries}:
            retrieval_queries.append(follow_up_query)
    gate = AgentEvidenceGateService() if variant.evidence_gate else None
    successful_retrievals: list[RetrievalResult] = []
    round_traces: list[dict[str, Any]] = []
    last_gate: dict[str, Any] | None = None
    previous_chunk_ids: set[str] = set()

    for round_number, retrieval_query in enumerate(retrieval_queries[:3], start=1):
        intent = detect_structural_intent(retrieval_query) if variant.structural else None
        section_hints = intent.section_aliases if intent is not None else ()
        started = perf_counter()
        result = index.runtime.retrieval_service.retrieve(
            retrieval_query,
            filters=VectorSearchFilter(document_ids=[document_id]),
            section_hints=section_hints,
            final_top_k=BENCHMARK_FINAL_TOP_K,
            dense_enabled=variant.dense,
            sparse_enabled=variant.sparse,
            structural_enabled=variant.structural,
            reranker_enabled=variant.reranker,
            small_to_big_enabled=variant.small_to_big,
        )
        round_latency_ms = (perf_counter() - started) * 1000
        returned_document_ids = {item.chunk.document_id for item in result.candidates}
        if returned_document_ids.difference({document_id}):
            raise RuntimeError("known-paper retrieval returned a chunk from another paper")
        successful_retrievals.append(result)
        new_chunk_ids = {
            candidate.chunk.chunk_id for candidate in result.candidates
        }.difference(previous_chunk_ids)
        previous_chunk_ids.update(candidate.chunk.chunk_id for candidate in result.candidates)
        round_trace: dict[str, Any] = {
            "round": round_number,
            "query": retrieval_query,
            "latency_ms": round_latency_ms,
            "candidate_chunk_ids": [item.chunk.chunk_id for item in result.candidates],
            "source_paragraph_ids": list(
                dict.fromkeys(
                    paragraph_id
                    for item in result.candidates
                    for paragraph_id in _source_paragraph_ids(item.chunk)
                )
            ),
            "context_evidence_paragraph_ids": list(
                dict.fromkeys(
                    paragraph_id
                    for item in result.candidates
                    for context_chunk in _candidate_context_chunks(item)
                    for paragraph_id in _source_paragraph_ids(context_chunk)
                )
            ),
            "context_token_count": sum(
                item.context_window.token_count
                if item.context_window is not None
                else item.chunk.token_count
                for item in result.candidates
            ),
            "new_chunk_count": len(new_chunk_ids),
        }
        if gate is not None:
            cumulative = _aggregate_retrievals(question.question, successful_retrievals)
            assessment = gate.assess(
                evidence=_gate_evidence(cumulative),
                latest_retrieval=AgentRetrievalObservation(
                    query=retrieval_query,
                    retrieval_strategy=result.retrieval_strategy,
                    result_count=len(result.candidates),
                    evidence_count=len(cumulative.candidates),
                    novel_evidence_count=min(len(new_chunk_ids), len(cumulative.candidates)),
                    fallback_reason=str(result.metadata.get("fallback_reason", "") or ""),
                ),
                search_count=round_number,
                remaining_searches=max(0, min(3, len(retrieval_queries)) - round_number),
            )
            gate_sufficient = (
                assessment.action == "stop"
                and "evidence_sufficient" in assessment.reason_codes
            )
            last_gate = {
                "sufficient": gate_sufficient,
                "action": assessment.action,
                "reason_codes": list(assessment.reason_codes),
                "evidence_count": assessment.evidence_count,
                "quality_score": assessment.quality_score,
                "search_count": assessment.search_count,
                "remaining_searches": assessment.remaining_searches,
            }
            round_trace["gate"] = last_gate
        round_traces.append(round_trace)
        if gate is not None and last_gate and last_gate["action"] == "stop":
            break

    return (
        _aggregate_retrievals(question.question, successful_retrievals),
        plan,
        round_traces,
        last_gate,
        planning_ms,
    )


def _validated_evidence_selection_profile(
    profile: Mapping[str, Any] | None,
) -> dict[str, Any]:
    selected = dict(profile or DEFAULT_EVIDENCE_SELECTION_PROFILE)
    profile_id = str(selected.get("profile_id", "")).strip()
    version = selected.get("profile_version")
    candidate_pool_size = selected.get("candidate_pool_size")
    default_variants = selected.get("default_variants")
    top_k_by_variant = selected.get("selected_top_k_by_variant")
    if (
        not profile_id
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version not in {1, 2, 3}
    ):
        raise ValueError("quality profile must have a profile_id and supported profile_version")
    retrieval_variant = selected.get("retrieval_variant")
    if not isinstance(retrieval_variant, str) or not retrieval_variant.strip():
        raise ValueError("quality profile retrieval_variant must be a non-empty string")
    # Fail before creating benchmark artifacts if the profile names an unknown
    # retrieval path. CURRENT is the benchmark's explicit default alias.
    get_qasper_ablation_variant(
        None if retrieval_variant.strip().casefold() == "current" else retrieval_variant
    )
    if (
        isinstance(candidate_pool_size, bool)
        or not isinstance(candidate_pool_size, int)
        or candidate_pool_size <= 0
    ):
        raise ValueError("quality profile candidate_pool_size must be a positive integer")
    if not isinstance(default_variants, list) or not default_variants:
        raise ValueError("quality profile default_variants must be a non-empty list")
    if not isinstance(top_k_by_variant, dict):
        raise TypeError("quality profile selected_top_k_by_variant must be an object")
    supported = {
        "current_top20",
        "rerank_top5",
        "rerank_top8",
        "rerank_top10",
        "evidence_selection",
        # Preserve the earlier CLI names as aliases for existing local workflows.
        "raw_top_k",
        "rerank_top_k",
    }
    if any(str(item) not in supported for item in default_variants):
        raise ValueError("quality profile contains an unsupported evidence variant")
    for variant_id, top_k in top_k_by_variant.items():
        if str(variant_id) not in supported:
            raise ValueError(f"quality profile has an unsupported variant: {variant_id}")
        if (
            isinstance(top_k, bool)
            or not isinstance(top_k, int)
            or top_k <= 0
            or top_k > candidate_pool_size
        ):
            raise ValueError(
                f"quality profile selected_top_k for {variant_id} must be within candidate_pool_size"
            )
    if any(str(item) not in top_k_by_variant for item in default_variants):
        raise ValueError("every default variant must define selected_top_k")
    excerpt_limit = selected.get("maximum_excerpt_tokens")
    if (
        isinstance(excerpt_limit, bool)
        or not isinstance(excerpt_limit, int)
        or excerpt_limit <= 0
    ):
        raise ValueError("quality profile maximum_excerpt_tokens must be a positive integer")
    excerpt_extractor = selected.get("excerpt_extractor")
    if not isinstance(excerpt_extractor, str) or not excerpt_extractor.strip():
        raise ValueError("quality profile excerpt_extractor must be a non-empty string")
    expected_extractor = (
        "extractive-contextual-spans-v1"
        if version == 3
        else "extractive-sentence-spans-v1"
    )
    if excerpt_extractor != expected_extractor:
        raise ValueError(
            f"quality profile version {version} requires {expected_extractor}"
        )
    selection_order = selected.get("selection_order", "relevance")
    if selection_order not in {"relevance", "candidate_rank"}:
        raise ValueError("quality profile selection_order must be relevance or candidate_rank")
    max_spans_per_source_chunk = selected.get("max_spans_per_source_chunk")
    if max_spans_per_source_chunk is not None and (
        isinstance(max_spans_per_source_chunk, bool)
        or not isinstance(max_spans_per_source_chunk, int)
        or max_spans_per_source_chunk <= 0
    ):
        raise ValueError("quality profile max_spans_per_source_chunk must be a positive integer")
    multi_paragraph_fallback = selected.get(
        "fallback_to_source_chunk_for_multi_paragraph_coverage", False
    )
    if not isinstance(multi_paragraph_fallback, bool):
        raise TypeError(
            "quality profile fallback_to_source_chunk_for_multi_paragraph_coverage must be boolean"
        )
    return selected


def _profile_excerpt_provider(profile: Mapping[str, Any]) -> EvidenceExcerptProvider:
    if profile["excerpt_extractor"] == "extractive-contextual-spans-v1":
        return ContextualEvidenceExcerptProvider(
            maximum_excerpt_tokens=profile["maximum_excerpt_tokens"]
        )
    return ExtractiveEvidenceExcerptProvider()


def _evidence_selection_variant_top_k(
    variant_id: str,
    profile: Mapping[str, Any],
) -> int:
    top_k_by_variant = profile["selected_top_k_by_variant"]
    legacy_defaults = {"raw_top_k": 5, "rerank_top_k": 5}
    return int(top_k_by_variant.get(variant_id, legacy_defaults.get(variant_id, 0)))


def _evidence_selection_ablation_variant(
    variant_id: str,
    *,
    profile: Mapping[str, Any] | None = None,
) -> QasperAblationVariant:
    names = {
        "current_top20": "Current Top 20",
        "rerank_top5": "Rerank Top 5",
        "rerank_top8": "Rerank Top 8",
        "rerank_top10": "Rerank Top 10",
        "evidence_selection": "Query-conditioned evidence selection",
        "raw_top_k": "Raw Top-K",
        "rerank_top_k": "Rerank Top-K",
    }
    selected_profile = _validated_evidence_selection_profile(profile)
    retrieval_variant = str(selected_profile.get("retrieval_variant", "CURRENT"))
    base = get_qasper_ablation_variant(
        None if retrieval_variant.casefold() == "current" else retrieval_variant
    )
    return QasperAblationVariant(
        variant_id=f"ES_{variant_id.upper()}",
        name=names[variant_id],
        dense=base.dense,
        sparse=base.sparse,
        reranker=False if variant_id == "raw_top_k" else base.reranker,
        structural=base.structural,
        small_to_big=base.small_to_big,
        multi_query=False,
        evidence_gate=False,
    )


def _normalize_evidence_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _map_selected_excerpt_to_paragraphs(
    candidate: RetrievalCandidate,
    *,
    paper: Any,
) -> tuple[list[str], list[str]]:
    benchmark_metadata = candidate.chunk.metadata.get("benchmark", {})
    source_ids = (
        benchmark_metadata.get("source_paragraph_ids", [])
        if isinstance(benchmark_metadata, dict)
        else []
    )
    source_ids = [value for value in source_ids if isinstance(value, str)]
    excerpt = _normalize_evidence_text(candidate.chunk.text)
    matched_ids = [
        paragraph.paragraph_id
        for paragraph in paper.paragraphs
        if paragraph.paragraph_id in source_ids
        and excerpt
        and excerpt in _normalize_evidence_text(paragraph.text)
    ]
    return list(dict.fromkeys(source_ids)), list(dict.fromkeys(matched_ids))


def _retain_only_excerpt_paragraphs(
    candidates: Sequence[RetrievalCandidate],
    *,
    paper: Any,
) -> list[RetrievalCandidate]:
    mapped: list[RetrievalCandidate] = []
    for candidate in candidates:
        original_ids, matched_ids = _map_selected_excerpt_to_paragraphs(
            candidate,
            paper=paper,
        )
        chunk_metadata = dict(candidate.chunk.metadata)
        benchmark_metadata = dict(chunk_metadata.get("benchmark", {}))
        benchmark_metadata["source_paragraph_ids"] = matched_ids
        chunk_metadata["benchmark"] = benchmark_metadata
        candidate_metadata = dict(candidate.metadata)
        selection_metadata = dict(candidate_metadata.get("evidence_selection", {}))
        selection_metadata["source_paragraph_ids"] = original_ids
        selection_metadata["matched_paragraph_ids"] = matched_ids
        candidate_metadata["evidence_selection"] = selection_metadata
        mapped.append(
            candidate.model_copy(
                update={
                    "chunk": candidate.chunk.model_copy(
                        update={"metadata": chunk_metadata}
                    ),
                    "metadata": candidate_metadata,
                }
            )
        )
    return mapped


def _evidence_selection_round(
    *,
    query: str,
    retrieval: RetrievalResult,
    candidate_pool: Sequence[RetrievalCandidate] | None = None,
    latency_ms: float,
) -> dict[str, Any]:
    candidates = retrieval.candidates
    pool = list(candidate_pool) if candidate_pool is not None else candidates
    paragraph_ids = list(
        dict.fromkeys(
            paragraph_id
            for candidate in candidates
            for paragraph_id in _source_paragraph_ids(candidate.chunk)
        )
    )
    pool_paragraph_ids = list(
        dict.fromkeys(
            paragraph_id
            for candidate in pool
            for paragraph_id in _source_paragraph_ids(candidate.chunk)
        )
    )
    selection = retrieval.metadata.get("evidence_selection", {})
    return {
        "round": 1,
        "query": query,
        "latency_ms": latency_ms,
        "candidate_chunk_ids": [item.chunk.chunk_id for item in pool],
        "source_paragraph_ids": pool_paragraph_ids,
        "context_evidence_paragraph_ids": paragraph_ids,
        "context_token_count": sum(item.chunk.token_count for item in candidates),
        "new_chunk_count": len(pool),
        "evidence_selection": selection,
    }


def _adaptive_ablation_variant(variant_id: str) -> QasperAblationVariant:
    names = {
        "one_shot": "One-shot hybrid retrieval",
        "multi_query": "Multi-query hybrid retrieval",
        "evidence_gated": "Evidence-gated re-retrieval",
        "requirement_aware": "Requirement-aware re-retrieval",
    }
    return QasperAblationVariant(
        variant_id=f"AR_{variant_id.upper()}",
        name=names[variant_id],
        dense=True,
        sparse=True,
        reranker=True,
        structural=False,
        small_to_big=False,
        multi_query=variant_id in {"multi_query", "evidence_gated"},
        evidence_gate=variant_id == "evidence_gated",
    )


def _requirement_query_expansion(question: str, requirement_type: str) -> str:
    normalized_question = question.casefold()
    if requirement_type == "answer":
        if re.search(r"\binflection(?:s|al)?\b", normalized_question):
            return "morphology inflectional forms tense number gender case conjugation"
        if re.search(
            r"\b(?:detect|recognize|recognise|identify|classify|infer|automatic)\b",
            normalized_question,
        ):
            return (
                "automatic detection recognition classification demographic linguistic "
                "psychological traits dimensions"
            )
        return "answer evidence finding study experiment evaluation result method data"
    return {
        "method": "method approach methodology procedure algorithm technique",
        "result": "result finding outcome effect performance accuracy evaluation",
        "data": "dataset data sample participant corpus",
        "rationale": "reason rationale explanation cause",
        "limitation": "limitation weakness challenge failure constraint",
    }.get(requirement_type, "evidence answer finding result")


def _retrieve_requirement_aware_question(
    question: QasperQuestion,
    *,
    index: Any,
    document_id: str,
    query_planner: Any | None = None,
    maximum_rounds: int = 3,
    candidate_pool_size: int = BENCHMARK_FINAL_TOP_K,
    gate_top_k: int | None = None,
) -> tuple[
    RetrievalResult,
    list[dict[str, Any]],
    tuple[EvidenceRequirement, ...],
    float,
    int,
    str,
]:
    requirements = infer_evidence_requirements(question.question)
    retrievals: list[RetrievalResult] = []
    round_traces: list[dict[str, Any]] = []
    attempted_requirement_ids: set[str] = set()
    query_history: set[str] = set()
    query_planning_ms = 0.0
    query_planner_invocations = 0
    pending_query = question.question.strip()
    pending_query_source = "original_question"
    pending_requirement_id = ""
    pending_query_plan: dict[str, Any] | None = None
    stop_reason = "retrieval_budget_exhausted"
    maximum_rounds = max(1, min(3, int(maximum_rounds)))
    candidate_pool_size = max(1, int(candidate_pool_size))
    gate_top_k = (
        candidate_pool_size if gate_top_k is None else max(1, int(gate_top_k))
    )

    for round_number in range(1, maximum_rounds + 1):
        retrieval_query = pending_query
        if not retrieval_query or retrieval_query.casefold() in query_history:
            stop_reason = "no_distinct_requirement_query"
            break
        query_history.add(retrieval_query.casefold())
        started = perf_counter()
        result = index.runtime.retrieval_service.retrieve(
            retrieval_query,
            filters=VectorSearchFilter(document_ids=[document_id]),
            final_top_k=candidate_pool_size,
            dense_enabled=True,
            sparse_enabled=True,
            structural_enabled=False,
            reranker_enabled=True,
            small_to_big_enabled=False,
        )
        round_latency_ms = (perf_counter() - started) * 1000
        returned_document_ids = {item.chunk.document_id for item in result.candidates}
        if returned_document_ids.difference({document_id}):
            raise RuntimeError("known-paper retrieval returned a chunk from another paper")
        prior_chunk_ids = {
            candidate.chunk.chunk_id
            for retrieval in retrievals
            for candidate in retrieval.candidates
        }
        novel_chunk_ids = list(
            dict.fromkeys(
                candidate.chunk.chunk_id
                for candidate in result.candidates
                if candidate.chunk.chunk_id not in prior_chunk_ids
            )
        )
        retrievals.append(result)
        cumulative = _aggregate_retrievals(question.question, retrievals)
        gate_candidates = cumulative.candidates[:gate_top_k]
        requirements = assess_evidence_requirements(
            requirements,
            gate_candidates,
        )
        context_paragraph_ids = list(
            dict.fromkeys(
                paragraph_id
                for candidate in gate_candidates
                for paragraph_id in _source_paragraph_ids(candidate.chunk)
            )
        )
        missing = next(
            (
                item
                for item in requirements
                if item.status == "missing"
                and item.id not in attempted_requirement_ids
            ),
            None,
        )
        uncovered_requirements = [
            item for item in requirements if item.status == "missing"
        ]
        query_plan_ms = 0.0
        query_plan_invoked = 0
        query_planner_metadata: dict[str, Any] | None = None
        query_planner_output_queries: list[str] = []
        next_query = ""
        next_query_source = ""
        next_requirement_id = ""
        next_query_plan: dict[str, Any] | None = None
        reason_codes: list[str] = []
        if not uncovered_requirements:
            action = "stop"
            stop_reason = "evidence_requirements_covered"
            reason_codes.append("evidence_requirements_covered")
        elif round_number > 1 and not novel_chunk_ids:
            action = "stop"
            stop_reason = "no_novel_evidence"
            reason_codes.append("no_novel_evidence")
        elif round_number >= maximum_rounds:
            action = "stop"
            stop_reason = "retrieval_budget_exhausted"
            reason_codes.append("retrieval_budget_exhausted")
        elif missing is None:
            action = "stop"
            stop_reason = "requirement_queries_exhausted"
            reason_codes.append("requirement_queries_exhausted")
        else:
            attempted_requirement_ids.add(missing.id)
            query_plan_started = perf_counter()
            if query_planner is not None:
                query_planner_invocations += 1
                query_plan_invoked = 1
                planning_request = (
                    "Find a distinct passage in the supplied paper that can satisfy a missing "
                    "evidence requirement. Return a standalone retrieval query only; do not "
                    "answer the research question.\n"
                    f"Question: {question.question}\n"
                    f"Missing requirement ({missing.type}): {missing.query}\n"
                    f"Queries already run: {' | '.join(sorted(query_history))}"
                )
                try:
                    plan = query_planner.plan(planning_request)
                except (OSError, TimeoutError, TypeError, ValueError):
                    plan = None
                planner_metadata = getattr(query_planner, "last_plan_metadata", None)
                if isinstance(planner_metadata, dict):
                    query_planner_metadata = dict(planner_metadata)
                if plan is not None:
                    planned_queries = getattr(plan, "retrieval_queries", ())
                    if not isinstance(planned_queries, (list, tuple)):
                        planned_queries = ()
                    query_planner_output_queries = [
                        str(item or "").strip()
                        for item in planned_queries
                        if str(item or "").strip()
                    ]
                    for planned_query in planned_queries:
                        candidate_query = str(planned_query or "").strip()
                        if (
                            candidate_query
                            and candidate_query.casefold() != planning_request.casefold()
                            and candidate_query.casefold() not in query_history
                        ):
                            next_query = candidate_query
                            next_query_source = "query_planner"
                            dump_plan = getattr(plan, "model_dump", None)
                            if callable(dump_plan):
                                next_query_plan = dump_plan(mode="json")
                            else:
                                next_query_plan = {
                                    "retrieval_queries": list(planned_queries)
                                }
                            break
            query_plan_ms = (perf_counter() - query_plan_started) * 1000
            query_planning_ms += query_plan_ms
            if not next_query:
                expansion = _requirement_query_expansion(
                    question.question,
                    missing.type,
                )
                fallback_queries = (
                    missing.query,
                    f"{question.question} {expansion}",
                )
                for candidate_query in fallback_queries:
                    candidate_query = candidate_query.strip()
                    if candidate_query and candidate_query.casefold() not in query_history:
                        next_query = candidate_query
                        next_query_source = "requirement_expansion"
                        break
            if next_query:
                action = "retrieve"
                stop_reason = "retrieval_requested_for_missing_requirement"
                next_requirement_id = missing.id
                reason_codes.append("missing_evidence_requirement")
            else:
                action = "stop"
                stop_reason = "no_distinct_requirement_query"
                reason_codes.append("no_distinct_requirement_query")
        gate_trace = {
            "action": action,
            "sufficient": action == "stop" and stop_reason == "evidence_requirements_covered",
            "reason_codes": reason_codes,
            "requirement_coverage": evidence_requirement_coverage(requirements),
            "gate_top_k": gate_top_k,
            "gate_candidate_chunk_ids": [
                item.chunk.chunk_id for item in gate_candidates
            ],
            "remaining_searches": max(0, maximum_rounds - round_number),
        }
        round_trace: dict[str, Any] = {
            "round": round_number,
            "query": retrieval_query,
            "query_source": pending_query_source,
            "query_for_requirement_id": pending_requirement_id or None,
            "query_plan": pending_query_plan,
            "query_planner_invoked": pending_query_source == "query_planner",
            "query_planner_status": query_planner_metadata,
            "query_planner_output_queries": query_planner_output_queries,
            "query_planning_ms": query_plan_ms,
            "query_plan_invocation_count": query_plan_invoked,
            "next_query": next_query or None,
            "next_query_source": next_query_source or None,
            "next_query_for_requirement_id": next_requirement_id or None,
            "next_query_plan": next_query_plan,
            "latency_ms": round_latency_ms,
            "candidate_chunk_ids": [
                item.chunk.chunk_id for item in result.candidates
            ],
            "novel_chunk_ids": novel_chunk_ids,
            "source_paragraph_ids": list(
                dict.fromkeys(
                    paragraph_id
                    for candidate in result.candidates
                    for paragraph_id in _source_paragraph_ids(candidate.chunk)
                )
            ),
            "context_evidence_paragraph_ids": context_paragraph_ids,
            "context_is_cumulative": True,
            "context_token_count": sum(
                item.context_window.token_count
                if item.context_window is not None
                else item.chunk.token_count
                for item in gate_candidates
            ),
            "candidate_pool_context_token_count": sum(
                item.context_window.token_count
                if item.context_window is not None
                else item.chunk.token_count
                for item in cumulative.candidates
            ),
            "gate_top_k": gate_top_k,
            "gate_candidate_chunk_ids": [
                item.chunk.chunk_id for item in gate_candidates
            ],
            "new_chunk_count": len(novel_chunk_ids),
            "evidence_requirements": [item.as_dict() for item in requirements],
            "requirement_coverage": evidence_requirement_coverage(requirements),
            "missing_requirement_ids": [
                item.id for item in requirements if item.status == "missing"
            ],
            "stop_reason": stop_reason if action == "stop" else None,
            "gate": gate_trace,
        }
        round_traces.append(round_trace)
        if action == "stop":
            break
        pending_query = next_query
        pending_query_source = next_query_source
        pending_requirement_id = next_requirement_id
        pending_query_plan = next_query_plan

    merged = _aggregate_retrievals(question.question, retrievals)
    merged.metadata.update(
        {
            "adaptive_variant": "requirement_aware",
            "evidence_requirements": [item.as_dict() for item in requirements],
            "requirement_coverage": evidence_requirement_coverage(requirements),
            "requirement_round_count": len(retrievals),
            "requirement_retrieval_queries": [item.query for item in retrievals],
            "requirement_stop_reason": stop_reason,
            "query_planner_invocation_count": query_planner_invocations,
            "query_planning_ms": query_planning_ms,
        }
    )
    return (
        merged,
        round_traces,
        requirements,
        query_planning_ms,
        query_planner_invocations,
        stop_reason,
    )


def _new_run_id(split: str, mode: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"qasper-{split}-{mode}-{stamp}-{uuid.uuid4().hex[:8]}"


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _config_hash(config: RagConfig) -> str:
    canonical = json.dumps(
        config.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _profile_sha256(path: str | Path) -> str:
    profile_path = Path(path).expanduser().resolve()
    return hashlib.sha256(profile_path.read_bytes()).hexdigest()


def _run_variant_label(
    selected_variant: QasperAblationVariant,
    *,
    adaptive_variant: str | None,
    evidence_selection_variant: str | None,
    raptor_variant: str | None,
) -> str:
    labels = [
        f"adaptive:{adaptive_variant}" if adaptive_variant else "",
        f"evidence:{evidence_selection_variant}" if evidence_selection_variant else "",
        f"raptor:{raptor_variant}" if raptor_variant else "",
    ]
    return "+".join(label for label in labels if label) or selected_variant.variant_id


def _hardware_manifest() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }


def run_qasper_benchmark(
    dataset: QasperDataset,
    *,
    root: str | Path | None = None,
    mode: str = "smoke",
    limit: int | None = None,
    seed: int = 42,
    config: RagConfig | None = None,
    config_profile_id: str | None = None,
    config_profile_sha256: str | None = None,
    embedding_provider: Any | None = None,
    reranker: Any | None = None,
    answerer: QasperAnswerer | None = None,
    query_planner: Any | None = None,
    variant: QasperAblationVariant | str | None = None,
    raptor_variant: str | None = None,
    raptor_trees: Mapping[str, RaptorTree] | None = None,
    evidence_selection_variant: str | None = None,
    evidence_selector: EvidenceSelectionService | None = None,
    quality_profile: Mapping[str, Any] | None = None,
    quality_profile_sha256: str | None = None,
    adaptive_variant: str | None = None,
    run_id: str | None = None,
    question_ids_file: str | Path | None = None,
    rebuild_index: bool = False,
) -> QasperBenchmarkRunResult:
    """Run the current AITrans RAG path with strict known-paper scoping."""

    normalized_mode = mode.strip().casefold()
    if normalized_mode not in RUN_LIMITS:
        raise ValueError(f"mode must be one of: {', '.join(RUN_LIMITS)}")
    if limit is None:
        limit = RUN_LIMITS[normalized_mode]
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    question_ids: tuple[str, ...] | None = None
    question_ids_file_sha256: str | None = None
    resolved_question_ids_file: Path | None = None
    if question_ids_file is not None:
        resolved_question_ids_file = Path(question_ids_file).expanduser().resolve()
        question_ids, question_ids_file_sha256 = read_question_ids_file(
            resolved_question_ids_file
        )
    selected = sample_qasper_dataset(
        dataset,
        limit=limit,
        seed=seed,
        question_ids=question_ids,
    )
    normalized_evidence_selection_variant = (
        str(evidence_selection_variant).strip().casefold()
        if evidence_selection_variant is not None
        else None
    )
    resolved_quality_profile = (
        _validated_evidence_selection_profile(quality_profile)
        if normalized_evidence_selection_variant is not None
        else None
    )
    resolved_quality_profile_sha256 = (
        quality_profile_sha256
        or (
            hashlib.sha256(
                json.dumps(
                    resolved_quality_profile,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if resolved_quality_profile is not None
            else None
        )
    )
    if normalized_evidence_selection_variant is not None and (
        normalized_evidence_selection_variant
        not in resolved_quality_profile["selected_top_k_by_variant"]
        and normalized_evidence_selection_variant not in {"raw_top_k", "rerank_top_k"}
    ):
        raise ValueError(
            "evidence_selection_variant must be defined by the active quality profile"
        )
    normalized_adaptive_variant = (
        str(adaptive_variant).strip().casefold()
        if adaptive_variant is not None
        else None
    )
    if normalized_adaptive_variant is not None and normalized_adaptive_variant not in {
        "one_shot",
        "multi_query",
        "evidence_gated",
        "requirement_aware",
    }:
        raise ValueError(
            "adaptive_variant must be one_shot, multi_query, evidence_gated, or requirement_aware"
        )
    if (
        normalized_evidence_selection_variant is not None
        and normalized_adaptive_variant not in {None, "one_shot", "requirement_aware"}
    ):
        raise ValueError(
            "evidence-selection can only be combined with one_shot or requirement_aware retrieval"
        )
    selected_variant = (
        _evidence_selection_ablation_variant(
            normalized_evidence_selection_variant,
            profile=resolved_quality_profile,
        )
        if normalized_evidence_selection_variant is not None
        else (
            _adaptive_ablation_variant(normalized_adaptive_variant)
            if normalized_adaptive_variant is not None
            else get_qasper_ablation_variant(variant)
        )
    )
    normalized_raptor_variant = (
        str(raptor_variant).strip().upper() if raptor_variant is not None else None
    )
    if normalized_raptor_variant is not None and normalized_raptor_variant not in {
        "R0",
        "R1",
        "R2",
        "R3",
    }:
        raise ValueError("raptor_variant must be one of R0, R1, R2, or R3")
    if normalized_raptor_variant is not None and raptor_trees is None:
        raise ValueError("raptor_trees are required for a RAPTOR benchmark run")
    benchmark_directory = benchmark_root(root)
    selected_run_id = run_id or _new_run_id(selected.split, normalized_mode)
    if not _RUN_ID.fullmatch(selected_run_id):
        raise ValueError("run_id may contain only letters, digits, dots, underscores, and hyphens")
    run_directory = benchmark_directory / "results" / selected_run_id
    if run_directory.exists():
        raise FileExistsError(f"QASPER run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = run_directory / "manifest.json"
    predictions_path = run_directory / "predictions.jsonl"
    trace_path = run_directory / "retrieval_trace.jsonl"
    metrics_path = run_directory / "metrics.json"
    errors_path = run_directory / "errors.jsonl"
    for output_path in (predictions_path, trace_path, errors_path):
        output_path.touch(exist_ok=False)
    started_at = datetime.now(UTC)
    alignment = align_qasper_evidence(selected)
    sample_hash = qasper_sample_hash(selected)
    qrels_path = benchmark_directory / "qrels" / f"{sample_hash}.jsonl"
    qrels_records = [
        _answer_fields(question, alignment.by_question[question.question_id])
        for question in selected.questions
    ]
    for question, qrel in zip(selected.questions, qrels_records, strict=True):
        paper = selected.papers[question.paper_id]
        section_by_paragraph = {
            paragraph.paragraph_id: paragraph.section_index
            for paragraph in paper.paragraphs
        }
        gold_paragraph_ids = set(qrel["gold_evidence_paragraph_ids"])
        for answer in qrel["answers"]:
            answer["evidence_section_indices"] = sorted(
                {
                    section_by_paragraph[paragraph_id]
                    for paragraph_id in answer["evidence_paragraph_ids"]
                    if paragraph_id in section_by_paragraph
                }
            )
        qrel["gold_evidence_section_indices"] = sorted(
            {
                paragraph.section_index
                for paragraph in paper.paragraphs
                if paragraph.paragraph_id in gold_paragraph_ids
            }
        )
    atomic_write_jsonl(qrels_path, qrels_records)
    source_config = (config or RagConfig()).model_copy(deep=True)
    config_digest = _config_hash(source_config)
    prompt_id = None
    if answerer is not None:
        prompt_id = str(getattr(answerer, "prompt_id", "") or "").strip() or None
    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "run_id": selected_run_id,
        "git_sha": _git_sha(),
        "status": "running",
        "dataset": "qasper",
        "dataset_version": selected.dataset_version,
        "split": selected.split,
        "source_path": selected.source_path,
        "source_sha256": selected.source_sha256,
        "sample_hash": sample_hash,
        "mode": normalized_mode,
        "limit": limit,
        "seed": seed,
        "variant": _run_variant_label(
            selected_variant,
            adaptive_variant=normalized_adaptive_variant,
            evidence_selection_variant=normalized_evidence_selection_variant,
            raptor_variant=normalized_raptor_variant,
        ),
        "config_hash": config_digest,
        "config_profile_id": config_profile_id,
        "config_profile_sha256": config_profile_sha256,
        "prompt_id": prompt_id,
        "index_fingerprint": None,
        "embedding_model": source_config.embedding.model,
        "reranker_model": source_config.reranker.model,
        "hardware": _hardware_manifest(),
        "cache_hits": {
            "index": None,
            "reused_paper_count": None,
            "indexed_paper_count": None,
        },
        "question_count": len(selected.questions),
        "paper_count": len(selected.papers),
        "selected_question_ids": [question.question_id for question in selected.questions],
        "question_id_selection": (
            {
                "file_name": resolved_question_ids_file.name,
                "file_sha256": question_ids_file_sha256,
                "question_ids_sha256": hashlib.sha256(
                    ("\n".join(question.question_id for question in selected.questions) + "\n").encode("utf-8")
                ).hexdigest(),
            }
            if resolved_question_ids_file is not None
            else None
        ),
        "qrels_path": str(qrels_path),
        "started_at": started_at.isoformat(),
        "rag_config": source_config.model_dump(mode="json"),
        "answer_generation": answerer is not None,
        "answer_contract": (
            getattr(answerer, "answer_contract_manifest", None)
            if answerer is not None
            else None
        ),
        "ablation_variant": selected_variant.as_dict(),
        "evidence_selection_variant": normalized_evidence_selection_variant,
        "quality_profile": resolved_quality_profile,
        "quality_profile_sha256": resolved_quality_profile_sha256,
        "adaptive_variant": normalized_adaptive_variant,
        "evidence_selection_parameters": (
            {
                "candidate_pool_size": resolved_quality_profile["candidate_pool_size"],
                "selected_top_k": _evidence_selection_variant_top_k(
                    normalized_evidence_selection_variant,
                    resolved_quality_profile,
                ),
                "maximum_excerpt_tokens": resolved_quality_profile[
                    "maximum_excerpt_tokens"
                ],
                "selection_order": resolved_quality_profile.get(
                    "selection_order", "relevance"
                ),
                "max_spans_per_source_chunk": resolved_quality_profile.get(
                    "max_spans_per_source_chunk"
                ),
                "retrieval_variant": resolved_quality_profile["retrieval_variant"],
                "extractor_model": (
                    evidence_selector.extractor_model
                    if evidence_selector is not None
                    else resolved_quality_profile["excerpt_extractor"]
                ),
                "prompt_version": (
                    evidence_selector.prompt_version
                    if evidence_selector is not None
                    else resolved_quality_profile["excerpt_extractor"]
                ),
            }
            if normalized_evidence_selection_variant is not None
            else None
        ),
        "raptor_variant": normalized_raptor_variant,
        "raptor_tree_fingerprints": (
            {
                document_id: tree.fingerprint
                for document_id, tree in sorted(raptor_trees.items())
            }
            if raptor_trees is not None
            else {}
        ),
        "files": {
            "predictions": predictions_path.name,
            "retrieval_trace": trace_path.name,
            "metrics": metrics_path.name,
            "errors": errors_path.name,
        },
    }
    atomic_write_json(manifest_path, manifest)

    retrieval_latencies: list[float] = []
    answer_latencies: list[float] = []
    strategy_counts: dict[str, int] = {}
    error_count = 0
    succeeded_retrievals = 0
    answer_count = 0
    index = None
    active_evidence_selector = evidence_selector
    try:
        index = build_qasper_index(
            selected,
            storage_root=benchmark_directory,
            config=source_config,
            embedding_provider=embedding_provider,
            reranker=reranker,
            rebuild=rebuild_index,
        )
        if (
            normalized_evidence_selection_variant == "evidence_selection"
            and active_evidence_selector is None
        ):
            active_evidence_selector = EvidenceSelectionService(
                extractor=_profile_excerpt_provider(resolved_quality_profile),
                embedding_provider=index.runtime.embedding_provider,
                maximum_excerpt_tokens=(
                    resolved_quality_profile["maximum_excerpt_tokens"]
                ),
            )
        manifest["index"] = {
            "fingerprint": index.result.fingerprint,
            "fingerprint_inputs": index.result.fingerprint_inputs,
            "index_root": str(index.result.index_root),
            "cache_hit": index.result.cache_hit,
            "reused_paper_count": index.result.reused_paper_count,
            "indexed_paper_count": index.result.indexed_paper_count,
            "chunk_count": index.result.chunk_count,
        }
        manifest["index_fingerprint"] = index.result.fingerprint
        manifest["embedding_model"] = index.runtime.embedding_provider.model_name
        manifest["cache_hits"] = {
            "index": bool(index.result.cache_hit),
            "reused_paper_count": int(index.result.reused_paper_count),
            "indexed_paper_count": int(index.result.indexed_paper_count),
        }
        manifest["embedding"] = {
            "provider": index.runtime.config.embedding.provider,
            "model": index.runtime.embedding_provider.model_name,
            "dimension": index.runtime.embedding_provider.dimension,
        }
        answer_provider = getattr(answerer, "provider", "") if answerer else ""
        answer_model = getattr(answerer, "model", "") if answerer else ""
        manifest["answer_model"] = {"provider": answer_provider, "model": answer_model}
        atomic_write_json(manifest_path, manifest)

        with (
            predictions_path.open("a", encoding="utf-8", newline="\n") as predictions_file,
            trace_path.open("a", encoding="utf-8", newline="\n") as trace_file,
            errors_path.open("a", encoding="utf-8", newline="\n") as errors_file,
        ):
            for question in selected.questions:
                retrieval_result: RetrievalResult | None = None
                retrieval_candidate_pool: list[RetrievalCandidate] = []
                predicted_answer = ""
                user_visible_answer = ""
                answer_info: dict[str, Any] = {}
                query_error = ""
                document_id = f"qasper:{selected.split}:{question.paper_id}"
                paragraph_section_indices = {
                    paragraph.paragraph_id: paragraph.section_index
                    for paragraph in selected.papers[question.paper_id].paragraphs
                }
                raptor_category = (
                    _raptor_question_category(
                        question=question,
                        paper=selected.papers[question.paper_id],
                        aligned_answers=alignment.by_question[question.question_id],
                    )
                    if normalized_raptor_variant is not None
                    else ""
                )
                retrieval_started = perf_counter()
                try:
                    if normalized_raptor_variant is not None:
                        tree = (raptor_trees or {}).get(document_id)
                        if tree is None:
                            raise ValueError(
                                f"RAPTOR tree is missing for {document_id!r}"
                            )
                        retrieval_result, raptor_round = _retrieve_raptor_question(
                            question.question,
                            index=index,
                            document_id=document_id,
                            tree=tree,
                            variant=normalized_raptor_variant,
                        )
                        if normalized_evidence_selection_variant == "evidence_selection":
                            if active_evidence_selector is None:
                                raise RuntimeError("evidence selector was not initialized")
                            retrieval_candidate_pool = _select_raptor_evidence(
                                question.question,
                                paper=selected.papers[question.paper_id],
                                retrieval=retrieval_result,
                                selector=active_evidence_selector,
                                profile=resolved_quality_profile,
                            )
                            raptor_round["final_evidence_selection"] = (
                                retrieval_result.metadata["evidence_selection"]
                            )
                            raptor_round["final_selected_evidence_chunk_ids"] = [
                                item.chunk.chunk_id for item in retrieval_result.candidates
                            ]
                        query_plan = _identity_query_plan(question.question)
                        retrieval_rounds = [raptor_round]
                        sufficiency = None
                        query_planning_ms = 0.0
                    else:
                        if normalized_evidence_selection_variant is not None:
                            candidate_pool_size = int(
                                resolved_quality_profile["candidate_pool_size"]
                            )
                            selected_top_k = _evidence_selection_variant_top_k(
                                normalized_evidence_selection_variant,
                                resolved_quality_profile,
                            )
                            selection_enabled = (
                                normalized_evidence_selection_variant
                                == "evidence_selection"
                            )
                            if normalized_adaptive_variant == "requirement_aware":
                                (
                                    retrieval_result,
                                    retrieval_rounds,
                                    _evidence_requirements,
                                    query_planning_ms,
                                    _query_planner_invocations,
                                    _requirement_stop_reason,
                                ) = _retrieve_requirement_aware_question(
                                    question,
                                    index=index,
                                    document_id=document_id,
                                    query_planner=query_planner,
                                    candidate_pool_size=candidate_pool_size,
                                    gate_top_k=selected_top_k,
                                )
                            else:
                                retrieval_result = index.runtime.retrieval_service.retrieve(
                                    question.question,
                                    filters=VectorSearchFilter(document_ids=[document_id]),
                                    final_top_k=candidate_pool_size,
                                    dense_enabled=selected_variant.dense,
                                    sparse_enabled=selected_variant.sparse,
                                    structural_enabled=selected_variant.structural,
                                    reranker_enabled=selected_variant.reranker,
                                    small_to_big_enabled=selected_variant.small_to_big,
                                )
                                retrieval_rounds = []
                                query_planning_ms = 0.0
                            retrieval_candidate_pool = list(retrieval_result.candidates)
                            retrieval_pool_chunk_ids = [
                                item.chunk.chunk_id for item in retrieval_candidate_pool
                            ]
                            query_plan = _identity_query_plan(question.question)
                            sufficiency = None
                            if selection_enabled:
                                if active_evidence_selector is None:
                                    raise RuntimeError(
                                        "evidence selector was not initialized"
                                    )
                                selection_order = str(
                                    resolved_quality_profile.get(
                                        "selection_order", "relevance"
                                    )
                                )
                                source_chunk_fallback_enabled = bool(
                                    resolved_quality_profile.get(
                                        "fallback_to_source_chunk_for_multi_paragraph_coverage",
                                        False,
                                    )
                                )
                                selection_input_candidates = (
                                    retrieval_candidate_pool[:selected_top_k]
                                    if source_chunk_fallback_enabled
                                    else retrieval_candidate_pool
                                )
                                selection_result = active_evidence_selector.select(
                                    question.question,
                                    selection_input_candidates,
                                    top_n=len(selection_input_candidates),
                                    top_k=selected_top_k,
                                    selection_order=selection_order,
                                    max_spans_per_source_chunk=(
                                        resolved_quality_profile.get(
                                            "max_spans_per_source_chunk"
                                        )
                                    ),
                                )
                                selected_candidates = _retain_only_excerpt_paragraphs(
                                    [item.candidate for item in selection_result.selected],
                                    paper=selected.papers[question.paper_id],
                                )
                                selection_trace = selection_result.as_dict()
                                selection_trace["selection_order"] = selection_order
                                selection_trace["max_spans_per_source_chunk"] = (
                                    resolved_quality_profile.get(
                                        "max_spans_per_source_chunk"
                                    )
                                )
                                selection_trace["retrieval_candidate_pool_count"] = len(
                                    retrieval_candidate_pool
                                )
                                selection_trace["selection_input_candidate_count"] = len(
                                    selection_input_candidates
                                )
                                excerpt_by_source_id: dict[str, RetrievalCandidate] = {}
                                selected_trace_by_source_id: dict[str, dict[str, Any]] = {}
                                for trace_item, candidate in zip(
                                    selection_trace["selected"],
                                    selected_candidates,
                                    strict=True,
                                ):
                                    selection_metadata = candidate.metadata.get(
                                        "evidence_selection", {}
                                    )
                                    source_chunk_id = str(
                                        selection_metadata.get(
                                            "source_chunk_id", candidate.chunk.chunk_id
                                        )
                                    )
                                    matched_paragraph_ids = _source_paragraph_ids(
                                        candidate.chunk
                                    )
                                    trace_item["matched_paragraph_ids"] = matched_paragraph_ids
                                    trace_item["final_action"] = "excerpt"
                                    excerpt_by_source_id.setdefault(
                                        source_chunk_id, candidate
                                    )
                                    selected_trace_by_source_id.setdefault(
                                        source_chunk_id, trace_item
                                    )
                                selection_trace["mapped_selected_span_count"] = sum(
                                    bool(item.get("matched_paragraph_ids"))
                                    for item in selection_trace["selected"]
                                )
                                selection_trace["unmapped_selected_span_count"] = (
                                    len(selection_trace["selected"])
                                    - selection_trace["mapped_selected_span_count"]
                                )

                                if source_chunk_fallback_enabled:
                                    selected_candidates = []
                                    fallback_count = 0
                                    no_valid_excerpt_count = 0
                                    fallback_traces: list[dict[str, Any]] = []
                                    for source_candidate in selection_input_candidates:
                                        source_chunk_id = source_candidate.chunk.chunk_id
                                        original_paragraph_ids = _source_paragraph_ids(
                                            source_candidate.chunk
                                        )
                                        excerpt_candidate = excerpt_by_source_id.get(
                                            source_chunk_id
                                        )
                                        matched_paragraph_ids = (
                                            _source_paragraph_ids(excerpt_candidate.chunk)
                                            if excerpt_candidate is not None
                                            else []
                                        )
                                        no_valid_excerpt = not bool(
                                            excerpt_candidate and matched_paragraph_ids
                                        )
                                        covers_source_paragraphs = bool(
                                            original_paragraph_ids
                                        ) and set(original_paragraph_ids).issubset(
                                            matched_paragraph_ids
                                        )
                                        fallback_needed = no_valid_excerpt or (
                                            resolved_quality_profile.get(
                                                "fallback_to_source_chunk_for_multi_paragraph_coverage",
                                                False,
                                            )
                                            and not covers_source_paragraphs
                                        )
                                        if fallback_needed:
                                            fallback_count += 1
                                            no_valid_excerpt_count += int(
                                                no_valid_excerpt
                                            )
                                            fallback_reason = (
                                                "no_scored_excerpt"
                                                if excerpt_candidate is None
                                                else (
                                                    "excerpt_has_no_source_paragraph_mapping"
                                                    if no_valid_excerpt
                                                    else "excerpt_does_not_cover_all_source_paragraphs"
                                                )
                                            )
                                            trace_item = selected_trace_by_source_id.get(
                                                source_chunk_id
                                            )
                                            if trace_item is None:
                                                trace_item = {
                                                    "source_chunk_id": source_chunk_id,
                                                    "matched_paragraph_ids": matched_paragraph_ids,
                                                }
                                                fallback_traces.append(trace_item)
                                            trace_item.update(
                                                {
                                                    "final_action": "source_chunk_fallback",
                                                    "fallback_applied": True,
                                                    "fallback_reason": fallback_reason,
                                                    "no_valid_excerpt": no_valid_excerpt,
                                                    "source_paragraph_ids": original_paragraph_ids,
                                                }
                                            )
                                            fallback_metadata = dict(
                                                source_candidate.metadata
                                            )
                                            fallback_metadata[
                                                "evidence_selection"
                                            ] = {
                                                "source_chunk_id": source_chunk_id,
                                                "fallback_applied": True,
                                                "fallback_reason": fallback_reason,
                                                "no_valid_excerpt": no_valid_excerpt,
                                                "source_paragraph_ids": original_paragraph_ids,
                                                "matched_paragraph_ids": matched_paragraph_ids,
                                            }
                                            final_candidate = source_candidate.model_copy(
                                                update={
                                                    "context_window": None,
                                                    "metadata": fallback_metadata,
                                                    "rank": source_candidate.rank,
                                                }
                                            )
                                        else:
                                            final_candidate = excerpt_candidate.model_copy(
                                                update={
                                                    "context_window": None,
                                                    "rank": source_candidate.rank,
                                                }
                                            )
                                        selected_candidates.append(final_candidate)
                                    selection_trace["fallback_count"] = fallback_count
                                    selection_trace["fallbacks"] = fallback_traces
                                    selection_trace[
                                        "no_valid_excerpt_count"
                                    ] = no_valid_excerpt_count
                                    selection_trace["no_valid_excerpt"] = (
                                        no_valid_excerpt_count > 0
                                    )
                                    selection_trace[
                                        "final_selected_evidence_count"
                                    ] = len(selected_candidates)
                                    if no_valid_excerpt_count:
                                        selection_trace[
                                            "no_valid_excerpt_reason"
                                        ] = "source_chunk_fallback_applied"
                                else:
                                    paragraph_mapped_candidates = [
                                        candidate.model_copy(
                                            update={"context_window": None}
                                        )
                                        for candidate in selected_candidates
                                        if _source_paragraph_ids(candidate.chunk)
                                    ]
                                    selection_trace[
                                        "mapped_selected_span_count"
                                    ] = len(paragraph_mapped_candidates)
                                    selection_trace[
                                        "unmapped_selected_span_count"
                                    ] = (
                                        len(selected_candidates)
                                        - len(paragraph_mapped_candidates)
                                    )
                                    selection_trace["no_valid_excerpt"] = not bool(
                                        paragraph_mapped_candidates
                                    )
                                    if selection_trace["no_valid_excerpt"]:
                                        selection_trace[
                                            "no_valid_excerpt_reason"
                                        ] = (
                                            "no_selected_span"
                                            if not selected_candidates
                                            else "no_source_paragraph_mapping"
                                        )
                                    selected_candidates = paragraph_mapped_candidates
                                retrieval_result.candidates = selected_candidates
                                retrieval_result.metadata.update(
                                    {
                                        "evidence_selection": selection_trace,
                                        "evidence_extraction_ms": selection_result.extraction_ms,
                                        "evidence_scoring_ms": selection_result.scoring_ms,
                                        "evidence_extractor_invocations": (
                                            selection_result.candidate_pool_count
                                            if selection_result.extractor_model
                                            not in {
                                                "extractive-sentence-spans-v1",
                                                "extractive-contextual-spans-v1",
                                            }
                                            else 0
                                        ),
                                        "evidence_selection_pool_chunk_ids": retrieval_pool_chunk_ids,
                                        "candidate_pool_size": candidate_pool_size,
                                        "selected_top_k": selected_top_k,
                                        "no_valid_excerpt": selection_trace[
                                            "no_valid_excerpt"
                                        ],
                                    }
                                )
                            else:
                                retrieval_result.candidates = retrieval_candidate_pool[
                                    :selected_top_k
                                ]
                                retrieval_result.metadata.update(
                                    {
                                        "candidate_pool_chunk_ids": retrieval_pool_chunk_ids,
                                        "candidate_pool_size": candidate_pool_size,
                                        "selected_top_k": selected_top_k,
                                    }
                                )
                            if normalized_adaptive_variant == "requirement_aware":
                                if retrieval_rounds:
                                    retrieval_rounds[-1]["final_evidence_selection"] = (
                                        retrieval_result.metadata.get(
                                            "evidence_selection", {}
                                        )
                                    )
                                    retrieval_rounds[-1][
                                        "final_selected_evidence_chunk_ids"
                                    ] = [
                                        item.chunk.chunk_id
                                        for item in retrieval_result.candidates
                                    ]
                            else:
                                retrieval_rounds = [
                                    _evidence_selection_round(
                                        query=question.question,
                                        retrieval=retrieval_result,
                                        candidate_pool=retrieval_candidate_pool,
                                        latency_ms=retrieval_result.elapsed_ms,
                                    )
                                ]
                        elif normalized_adaptive_variant == "requirement_aware":
                            (
                                retrieval_result,
                                retrieval_rounds,
                                _evidence_requirements,
                                query_planning_ms,
                                _query_planner_invocations,
                                _requirement_stop_reason,
                            ) = _retrieve_requirement_aware_question(
                                question,
                                index=index,
                                document_id=document_id,
                                query_planner=query_planner,
                            )
                            query_plan = _identity_query_plan(question.question)
                            sufficiency = None
                        else:
                            (
                                retrieval_result,
                                query_plan,
                                retrieval_rounds,
                                sufficiency,
                                query_planning_ms,
                            ) = _retrieve_variant_question(
                                question,
                                index=index,
                                document_id=document_id,
                                variant=selected_variant,
                                query_planner=query_planner,
                            )
                    if retrieval_result is not None and not retrieval_candidate_pool:
                        retrieval_candidate_pool = list(retrieval_result.candidates)
                    retrieval_result.metadata["query_planning_ms"] = query_planning_ms
                    retrieval_ms = (perf_counter() - retrieval_started) * 1000
                    if (
                        normalized_evidence_selection_variant is not None
                        and normalized_adaptive_variant != "requirement_aware"
                    ):
                        retrieval_rounds[0]["latency_ms"] = retrieval_ms
                    retrieval_latencies.append(retrieval_ms)
                    strategy_counts[retrieval_result.retrieval_strategy] = (
                        strategy_counts.get(retrieval_result.retrieval_strategy, 0) + 1
                    )
                    succeeded_retrievals += 1
                except Exception as exc:  # noqa: BLE001 - record per-query failures
                    error_count += 1
                    query_error = str(exc) or exc.__class__.__name__
                    retrieval_ms = (perf_counter() - retrieval_started) * 1000
                    errors_file.write(
                        json.dumps(
                            {
                                "question_id": question.question_id,
                                "paper_id": question.paper_id,
                                "stage": "retrieval",
                                "error_type": exc.__class__.__name__,
                                "error": query_error,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                    errors_file.flush()

                if retrieval_result is not None and answerer is not None:
                    answer_started = perf_counter()
                    try:
                        answer_input = QasperAnswerInput(
                            question_id=question.question_id,
                            paper_id=question.paper_id,
                            question=question.question,
                        )
                        generated = answerer(answer_input, retrieval_result)
                        measured_ms = (perf_counter() - answer_started) * 1000
                        if isinstance(generated, QasperGeneratedAnswer):
                            predicted_answer = generated.answer
                            user_visible_answer = (
                                generated.user_visible_answer
                                if generated.user_visible_answer is not None
                                else generated.answer
                            )
                            answer_info = {
                                "provider": generated.provider,
                                "model": generated.model,
                                "latency_ms": generated.latency_ms or measured_ms,
                                "metadata": generated.metadata or {},
                            }
                            answer_latencies.append(float(answer_info["latency_ms"]))
                        else:
                            predicted_answer = str(generated)
                            user_visible_answer = predicted_answer
                            answer_info = {"provider": answer_provider, "model": answer_model}
                            answer_latencies.append(measured_ms)
                        answer_count += 1
                    except Exception as exc:  # noqa: BLE001 - keep retrieval trace on LLM failure
                        error_count += 1
                        query_error = str(exc) or exc.__class__.__name__
                        answer_info = {
                            "error_type": exc.__class__.__name__,
                            "error": query_error,
                        }
                        errors_file.write(
                            json.dumps(
                                {
                                    "question_id": question.question_id,
                                    "paper_id": question.paper_id,
                                    "stage": "answer_generation",
                                    "error_type": exc.__class__.__name__,
                                    "error": query_error,
                                },
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                        errors_file.flush()

                selected_evidence_paragraph_ids = list(
                    dict.fromkeys(
                        paragraph_id
                        for candidate in (
                            retrieval_result.candidates
                            if retrieval_result is not None
                            else []
                        )
                        for paragraph_id in _source_paragraph_ids(candidate.chunk)
                    )
                )
                context_evidence_paragraph_ids = list(
                    dict.fromkeys(
                        paragraph_id
                        for candidate in (
                            retrieval_result.candidates
                            if retrieval_result is not None
                            else []
                        )
                        for context_chunk in _candidate_context_chunks(candidate)
                        for paragraph_id in _source_paragraph_ids(context_chunk)
                    )
                )
                prediction = {
                    "question_id": question.question_id,
                    "paper_id": question.paper_id,
                    "question": question.question,
                    "ablation_variant": selected_variant.variant_id,
                    "evidence_selection_variant": normalized_evidence_selection_variant,
                    "adaptive_variant": normalized_adaptive_variant,
                    "raptor_variant": normalized_raptor_variant,
                    "query_plan": (
                        query_plan.model_dump(mode="json")
                        if retrieval_result is not None
                        else None
                    ),
                    "query_planner_invoked": bool(
                        (selected_variant.multi_query and query_planner is not None)
                        or (
                            normalized_adaptive_variant == "requirement_aware"
                            and retrieval_result is not None
                            and retrieval_result.metadata.get(
                                "query_planner_invocation_count", 0
                            )
                        )
                    ),
                    "answer": predicted_answer,
                    "user_visible_answer": (
                        user_visible_answer if answerer is not None else predicted_answer
                    ),
                    "answer_generation": answer_info,
                    "error": query_error,
                    "retrieved_chunk_ids": (
                        [item.chunk.chunk_id for item in retrieval_candidate_pool]
                    ),
                    "selected_evidence_chunk_ids": [
                        item.chunk.chunk_id
                        for item in (
                            retrieval_result.candidates
                            if retrieval_result is not None
                            else []
                        )
                    ],
                    "predicted_evidence_paragraph_ids": selected_evidence_paragraph_ids,
                }
                evidence_paragraph_ids = prediction[
                    "predicted_evidence_paragraph_ids"
                ]
                paragraph_text_by_id = {
                    paragraph.paragraph_id: paragraph.text
                    for paragraph in selected.papers[question.paper_id].paragraphs
                }
                prediction["predicted_evidence"] = [
                    paragraph_text_by_id[paragraph_id]
                    for paragraph_id in evidence_paragraph_ids
                    if paragraph_id in paragraph_text_by_id
                ]
                trace = {
                    "question_id": question.question_id,
                    "paper_id": question.paper_id,
                    "query": question.question,
                    "scope_document_id": document_id,
                    "retrieval_strategy": (
                        retrieval_result.retrieval_strategy
                        if retrieval_result is not None
                        else "failed"
                    ),
                    "latency_ms": retrieval_ms,
                    "retrieval_metadata": (
                        retrieval_result.metadata if retrieval_result is not None else {}
                    ),
                    "stages": {
                        key: (retrieval_result.metadata.get(key, []) if retrieval_result else [])
                        for key in (
                            "dense_chunk_ids",
                            "sparse_chunk_ids",
                            "structural_chunk_ids",
                            "pre_rerank_chunk_ids",
                        )
                    },
                    "pre_rerank_candidates": (
                        [
                            {
                                "chunk_id": chunk_id,
                                "source_paragraph_ids": _source_paragraph_ids(
                                    index.runtime.sparse_retriever.get_chunk(chunk_id)
                                ),
                                "source_section_indices": sorted(
                                    {
                                        paragraph_section_indices[paragraph_id]
                                        for paragraph_id in _source_paragraph_ids(
                                            index.runtime.sparse_retriever.get_chunk(chunk_id)
                                        )
                                        if paragraph_id in paragraph_section_indices
                                    }
                                ),
                            }
                            for chunk_id in retrieval_result.metadata.get(
                                "pre_rerank_chunk_ids", []
                            )
                            if index.runtime.sparse_retriever.get_chunk(chunk_id)
                            is not None
                        ]
                        if retrieval_result is not None
                        else []
                    ),
                    "context_evidence_paragraph_ids": context_evidence_paragraph_ids,
                    "selected_evidence_paragraph_ids": evidence_paragraph_ids,
                    "ablation_variant": selected_variant.as_dict(),
                    "evidence_selection_variant": normalized_evidence_selection_variant,
                    "adaptive_variant": normalized_adaptive_variant,
                    "raptor_variant": normalized_raptor_variant,
                    "raptor_category": raptor_category or None,
                    "query_plan": (
                        query_plan.model_dump(mode="json")
                        if retrieval_result is not None
                        else None
                    ),
                    "query_planner_invoked": bool(
                        (selected_variant.multi_query and query_planner is not None)
                        or (
                            normalized_adaptive_variant == "requirement_aware"
                            and retrieval_result is not None
                            and retrieval_result.metadata.get(
                                "query_planner_invocation_count", 0
                            )
                        )
                    ),
                    "retrieval_rounds": (
                        retrieval_rounds if retrieval_result is not None else []
                    ),
                    "evidence_requirements": (
                        retrieval_result.metadata.get("evidence_requirements", [])
                        if retrieval_result is not None
                        else []
                    ),
                    "retrieval_stop_reason": (
                        retrieval_result.metadata.get("requirement_stop_reason")
                        if retrieval_result is not None
                        and normalized_adaptive_variant == "requirement_aware"
                        else None
                    ),
                    "sufficiency": sufficiency if retrieval_result is not None else None,
                    **(
                        {"second_round": len(retrieval_rounds) > 1}
                        if (
                            selected_variant.evidence_gate
                            or normalized_adaptive_variant == "requirement_aware"
                        )
                        and retrieval_result is not None
                        else {}
                    ),
                    "retrieval_candidate_pool": [
                        {
                            **candidate_trace,
                            "source_section_indices": sorted(
                                {
                                    paragraph_section_indices[paragraph_id]
                                    for paragraph_id in candidate_trace[
                                        "source_paragraph_ids"
                                    ]
                                    if paragraph_id in paragraph_section_indices
                                }
                            ),
                        }
                        for candidate_trace in (
                            [_candidate_trace(item) for item in retrieval_candidate_pool]
                        )
                    ],
                    "selected_evidence": [
                        {
                            "chunk_id": candidate.chunk.chunk_id,
                            "source_chunk_id": str(
                                candidate.metadata.get("evidence_selection", {}).get(
                                    "source_chunk_id", candidate.chunk.chunk_id
                                )
                            ),
                            "rank": candidate.rank,
                            "source_start_char": candidate.chunk.start_char,
                            "source_end_char": candidate.chunk.end_char,
                            "source_paragraph_ids": _source_paragraph_ids(
                                candidate.chunk
                            ),
                            "evidence_selection": candidate.metadata.get(
                                "evidence_selection"
                            ),
                        }
                        for candidate in (
                            retrieval_result.candidates
                            if retrieval_result is not None
                            else []
                        )
                    ],
                    "final_candidates": [
                        {
                            **candidate_trace,
                            "source_section_indices": sorted(
                                {
                                    paragraph_section_indices[paragraph_id]
                                    for paragraph_id in candidate_trace["source_paragraph_ids"]
                                    if paragraph_id in paragraph_section_indices
                                }
                            ),
                        }
                        for candidate_trace in (
                            [_candidate_trace(item) for item in retrieval_result.candidates]
                            if retrieval_result is not None
                            else []
                        )
                    ],
                    "answer": predicted_answer,
                    "answer_generation": answer_info,
                    "error": query_error,
                }
                predictions_file.write(
                    json.dumps(prediction, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
                trace_file.write(
                    json.dumps(trace, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
                predictions_file.flush()
                trace_file.flush()

        completed_at = datetime.now(UTC)
        run_status = "complete" if error_count == 0 else "partial"
        metrics = {
            "metric_version": 1,
            "status": "retrieval_complete" if answerer is None else "baseline_complete",
            "question_count": len(selected.questions),
            "retrieval_success_count": succeeded_retrievals,
            "answer_count": answer_count,
            "error_count": error_count,
            "retrieval_latency_ms": {
                "p50": round(percentile(retrieval_latencies, 50), 3),
                "p95": round(percentile(retrieval_latencies, 95), 3),
                "samples": len(retrieval_latencies),
            },
            "answer_latency_ms": {
                "p50": round(percentile(answer_latencies, 50), 3),
                "p95": round(percentile(answer_latencies, 95), 3),
                "samples": len(answer_latencies),
            },
            "retrieval_strategy_counts": dict(sorted(strategy_counts.items())),
        }
        atomic_write_json(metrics_path, metrics)
        manifest.update(
            {
                "status": run_status,
                "completed_at": completed_at.isoformat(),
                "elapsed_seconds": round((completed_at - started_at).total_seconds(), 3),
                "error_count": error_count,
                "retrieval_success_count": succeeded_retrievals,
                "answer_count": answer_count,
            }
        )
        atomic_write_json(manifest_path, manifest)
        return QasperBenchmarkRunResult(
            run_id=selected_run_id,
            run_directory=run_directory,
            manifest_path=manifest_path,
            predictions_path=predictions_path,
            retrieval_trace_path=trace_path,
            metrics_path=metrics_path,
            errors_path=errors_path,
            qrels_path=qrels_path,
            question_count=len(selected.questions),
            error_count=error_count,
            run_status=run_status,
        )
    except BaseException as exc:
        manifest.update(
            {
                "status": "failed",
                "completed_at": datetime.now(UTC).isoformat(),
                "error": str(exc) or exc.__class__.__name__,
            }
        )
        atomic_write_json(manifest_path, manifest)
        with errors_path.open("a", encoding="utf-8", newline="\n") as errors_file:
            errors_file.write(
                json.dumps(
                    {
                        "stage": "index_or_runner",
                        "error_type": exc.__class__.__name__,
                        "error": str(exc) or exc.__class__.__name__,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
        atomic_write_json(
            metrics_path,
            {
                "metric_version": 1,
                "status": "failed",
                "question_count": len(selected.questions),
                "error_count": error_count + 1,
            },
        )
        raise
    finally:
        if index is not None:
            index.close()


def run_qasper_ablation(
    dataset: QasperDataset,
    *,
    root: str | Path | None = None,
    mode: str = "smoke",
    limit: int | None = None,
    seed: int = 42,
    config: RagConfig | None = None,
    variants: Sequence[QasperAblationVariant | str] | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    reranker: Any | None = None,
    answerer: QasperAnswerer | None = None,
    query_planner: Any | None = None,
    suite_id: str | None = None,
    question_ids_file: str | Path | None = None,
) -> QasperAblationSuiteResult:
    """Run the query-time ablation matrix against one shared QASPER index."""

    benchmark_directory = benchmark_root(root)
    selected_variants = [
        get_qasper_ablation_variant(item)
        for item in (
            variants
            if variants is not None
            else [item.variant_id for item in QASPER_ABLATION_VARIANTS]
        )
    ]
    variant_ids = [item.variant_id for item in selected_variants]
    if not selected_variants:
        raise ValueError("at least one QASPER ablation variant is required")
    if len(set(variant_ids)) != len(variant_ids):
        raise ValueError("QASPER ablation variants must be unique")

    source_config = (config or RagConfig()).model_copy(deep=True)
    model_manager: ModelManager | None = None
    if embedding_provider is None or reranker is None:
        model_manager = ModelManager()
    shared_embedding = embedding_provider or create_embedding_provider(
        source_config.embedding,
        model_manager=model_manager,
    )
    shared_reranker = reranker or Qwen3RerankerProvider(
        source_config.reranker,
        model_manager=model_manager,
    )

    selected_suite_id = suite_id or _new_run_id(dataset.split, f"ablation-{mode}")
    if not _RUN_ID.fullmatch(selected_suite_id):
        raise ValueError("suite_id may contain only letters, digits, dots, underscores, and hyphens")
    suite_directory = benchmark_directory / "ablation" / selected_suite_id
    suite_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = suite_directory / "manifest.json"
    comparison_path = suite_directory / "comparison.json"
    suite_manifest: dict[str, Any] = {
        "manifest_version": 1,
        "suite_id": selected_suite_id,
        "dataset": "qasper",
        "split": dataset.split,
        "mode": mode,
        "limit": limit if limit is not None else RUN_LIMITS.get(mode),
        "seed": seed,
        "index_rebuild": False,
        "status": "running",
        "variants": [item.as_dict() for item in selected_variants],
        "completed_runs": [],
        "started_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_json(manifest_path, suite_manifest)

    comparison_rows: list[dict[str, Any]] = []
    try:
        for variant in selected_variants:
            run_id = f"{selected_suite_id}-{variant.variant_id.lower()}"
            result = run_qasper_benchmark(
                dataset,
                root=benchmark_directory,
                mode=mode,
                limit=limit,
                seed=seed,
                config=source_config,
                embedding_provider=shared_embedding,
                reranker=shared_reranker,
                answerer=answerer,
                query_planner=query_planner,
                variant=variant,
                run_id=run_id,
                question_ids_file=question_ids_file,
                rebuild_index=False,
            )
            from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run

            metrics = evaluate_qasper_run(result.run_directory, root=benchmark_directory)
            run_manifest = read_json(result.manifest_path) or {}
            row = {
                "variant_id": variant.variant_id,
                "name": variant.name,
                "run_id": result.run_id,
                "run_directory": str(result.run_directory),
                "run_status": result.run_status,
                "error_count": result.error_count,
                "index_cache_hit": bool(run_manifest.get("index", {}).get("cache_hit")),
                "ai_trans_retrieval": metrics["ai_trans_retrieval"],
                "paragraph_evidence": metrics["paragraph_evidence"],
                "official_qasper": metrics["official_qasper"],
                "performance_ms": metrics["performance_ms"],
                "context_metrics": metrics.get("context_metrics", {}),
                "adaptive_retrieval": metrics.get("adaptive_retrieval", {}),
                "evidence_gate_evaluation": metrics.get("evidence_gate_evaluation", {}),
                "adaptive_metrics": metrics["adaptive_metrics"],
            }
            comparison_rows.append(row)
            suite_manifest["completed_runs"].append(
                {
                    "variant_id": variant.variant_id,
                    "run_id": result.run_id,
                    "run_status": result.run_status,
                    "index_cache_hit": row["index_cache_hit"],
                }
            )
            atomic_write_json(manifest_path, suite_manifest)

        comparison = {
            "metric_version": 1,
            "suite_id": selected_suite_id,
            "variant_count": len(comparison_rows),
            "definition": {
                "index_rebuild": False,
                "shared_index_fingerprint": "all variants use identical corpus/chunking/embedding fingerprint",
                "small_to_big_focus": [
                    "official Answer F1",
                    "official Evidence F1",
                    "Context Evidence Coverage",
                    "Context Tokens",
                ],
            },
            "variants": comparison_rows,
        }
        atomic_write_json(comparison_path, comparison)
        suite_status = (
            "complete"
            if all(row["run_status"] == "complete" for row in comparison_rows)
            else "partial"
        )
        suite_manifest.update(
            {
                "status": suite_status,
                "completed_at": datetime.now(UTC).isoformat(),
                "comparison_path": str(comparison_path),
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
    except BaseException as exc:
        suite_manifest.update(
            {
                "status": "failed",
                "completed_at": datetime.now(UTC).isoformat(),
                "error": str(exc) or exc.__class__.__name__,
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
        raise

    return QasperAblationSuiteResult(
        suite_id=selected_suite_id,
        suite_directory=suite_directory,
        manifest_path=manifest_path,
        comparison_path=comparison_path,
        variant_count=len(comparison_rows),
        status=suite_manifest["status"],
    )


def run_qasper_evidence_selection_ablation(
    dataset: QasperDataset,
    *,
    root: str | Path | None = None,
    mode: str = "smoke",
    limit: int | None = None,
    seed: int = 42,
    config: RagConfig | None = None,
    variants: Sequence[str] | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    reranker: Any | None = None,
    answerer: QasperAnswerer | None = None,
    excerpt_provider: EvidenceExcerptProvider | None = None,
    evidence_selector: EvidenceSelectionService | None = None,
    suite_id: str | None = None,
    question_ids_file: str | Path | None = None,
    quality_profile: Mapping[str, Any] | None = None,
    quality_profile_sha256: str | None = None,
) -> QasperEvidenceSelectionSuiteResult:
    """Compare raw, reranked, and query-selected QASPER evidence on one index."""

    normalized_mode = mode.strip().casefold()
    if normalized_mode not in RUN_LIMITS:
        raise ValueError(f"mode must be one of: {', '.join(RUN_LIMITS)}")
    selected_limit = RUN_LIMITS[normalized_mode] if limit is None else limit
    if selected_limit is not None and selected_limit <= 0:
        raise ValueError("limit must be positive")
    resolved_quality_profile = _validated_evidence_selection_profile(quality_profile)
    selected_variants = [
        str(value).strip().casefold()
        for value in (
            variants
            if variants is not None
            else resolved_quality_profile["default_variants"]
        )
    ]
    allowed_variants = set(resolved_quality_profile["selected_top_k_by_variant"]) | {
        "raw_top_k",
        "rerank_top_k",
    }
    if not selected_variants:
        raise ValueError("at least one evidence-selection variant is required")
    if any(value not in allowed_variants for value in selected_variants):
        raise ValueError(
            "evidence-selection variants must be defined by the quality profile"
        )
    if len(set(selected_variants)) != len(selected_variants):
        raise ValueError("evidence-selection variants must be unique")

    benchmark_directory = benchmark_root(root)
    source_config = (config or RagConfig()).model_copy(deep=True)
    model_manager: ModelManager | None = None
    if embedding_provider is None or reranker is None:
        model_manager = ModelManager()
    shared_embedding = embedding_provider or create_embedding_provider(
        source_config.embedding,
        model_manager=model_manager,
    )
    shared_reranker = reranker or Qwen3RerankerProvider(
        source_config.reranker,
        model_manager=model_manager,
    )
    shared_selector = evidence_selector or EvidenceSelectionService(
        extractor=excerpt_provider or _profile_excerpt_provider(resolved_quality_profile),
        embedding_provider=shared_embedding,
        maximum_excerpt_tokens=resolved_quality_profile["maximum_excerpt_tokens"],
    )

    selected_suite_id = suite_id or _new_run_id(
        dataset.split,
        f"evidence-selection-{normalized_mode}",
    )
    if not _RUN_ID.fullmatch(selected_suite_id):
        raise ValueError("suite_id may contain only letters, digits, dots, underscores, and hyphens")
    suite_directory = benchmark_directory / "evidence_selection" / selected_suite_id
    suite_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = suite_directory / "manifest.json"
    comparison_path = suite_directory / "comparison.json"
    suite_manifest: dict[str, Any] = {
        "manifest_version": 1,
        "suite_id": selected_suite_id,
        "dataset": "qasper",
        "dataset_version": dataset.dataset_version,
        "split": dataset.split,
        "mode": normalized_mode,
        "limit": selected_limit,
        "seed": seed,
        "index_rebuild": False,
        "status": "running",
        "variants": selected_variants,
        "candidate_pool_size": resolved_quality_profile["candidate_pool_size"],
        "selected_top_k_by_variant": resolved_quality_profile[
            "selected_top_k_by_variant"
        ],
        "quality_profile": resolved_quality_profile,
        "quality_profile_sha256": (
            quality_profile_sha256
            or hashlib.sha256(
                json.dumps(
                    resolved_quality_profile,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        ),
        "extractor_model": shared_selector.extractor_model,
        "prompt_version": shared_selector.prompt_version,
        "answer_generation": answerer is not None,
        "answer_contract": (
            getattr(answerer, "answer_contract_manifest", None)
            if answerer is not None
            else None
        ),
        "completed_runs": [],
        "started_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_json(manifest_path, suite_manifest)

    comparison_rows: list[dict[str, Any]] = []
    try:
        for variant_id in selected_variants:
            run_suffix = variant_id.replace("_", "-")
            run_id = f"{selected_suite_id[:100]}-es-{run_suffix}"
            result = run_qasper_benchmark(
                dataset,
                root=benchmark_directory,
                mode=normalized_mode,
                limit=selected_limit,
                seed=seed,
                config=source_config,
                embedding_provider=shared_embedding,
                reranker=shared_reranker,
                answerer=answerer,
                evidence_selection_variant=variant_id,
                evidence_selector=shared_selector,
                quality_profile=resolved_quality_profile,
                quality_profile_sha256=quality_profile_sha256,
                run_id=run_id,
                question_ids_file=question_ids_file,
                rebuild_index=False,
            )
            from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run

            metrics = evaluate_qasper_run(result.run_directory, root=benchmark_directory)
            run_manifest = read_json(result.manifest_path) or {}
            row = {
                "variant_id": variant_id,
                "name": _evidence_selection_ablation_variant(
                    variant_id,
                    profile=resolved_quality_profile,
                ).name,
                "run_id": result.run_id,
                "run_directory": str(result.run_directory),
                "run_status": result.run_status,
                "error_count": result.error_count,
                "index_cache_hit": bool(run_manifest.get("index", {}).get("cache_hit")),
                "ai_trans_retrieval": metrics["ai_trans_retrieval"],
                "candidate_pool_evidence": metrics["candidate_pool_evidence"],
                "paragraph_evidence": metrics["paragraph_evidence"],
                "official_qasper": metrics["official_qasper"],
                "context_metrics": metrics.get("context_metrics", {}),
                "groundedness_metrics": metrics.get("groundedness_metrics", {}),
                "answer_provider_counts": metrics.get("answer_provider_counts", {}),
                "answerer_invocations": metrics.get("adaptive_retrieval", {}).get(
                    "answerer_invocations", 0
                ),
                "estimated_llm_invocations": metrics.get("adaptive_retrieval", {}).get(
                    "estimated_llm_invocations", 0
                ),
                "evidence_selection": metrics.get("evidence_selection", {}),
                "performance_ms": metrics.get("performance_ms", {}),
            }
            comparison_rows.append(row)
            suite_manifest["completed_runs"].append(
                {
                    "variant_id": variant_id,
                    "run_id": result.run_id,
                    "run_status": result.run_status,
                    "index_cache_hit": row["index_cache_hit"],
                }
            )
            atomic_write_json(manifest_path, suite_manifest)

        comparison = {
            "metric_version": 1,
            "suite_id": selected_suite_id,
            "variant_count": len(comparison_rows),
            "definition": {
                "index_rebuild": False,
                "shared_index_fingerprint": "all variants use identical corpus, chunking, and embedding configuration",
                "candidate_pool_size": resolved_quality_profile["candidate_pool_size"],
                "retrieval_variant": resolved_quality_profile["retrieval_variant"],
                "current_top20": "current retrieval/reranking configuration, all 20 candidates selected",
                "rerank_top_k_variants": "shared reranked candidate pool sliced to each profile selected_top_k",
                "evidence_selection": "shared reranked candidate pool, exact query-conditioned spans limited by the profile, with source offsets checked",
                "metrics": [
                    "paragraph evidence precision, recall, and F1",
                    "official QASPER Answer F1 and Evidence F1",
                    "Context Tokens",
                    "Unsupported Claim Rate",
                    "evidence extraction and scoring latency",
                ],
            },
            "variants": comparison_rows,
        }
        atomic_write_json(comparison_path, comparison)
        suite_status = (
            "complete"
            if all(row["run_status"] == "complete" for row in comparison_rows)
            else "partial"
        )
        suite_manifest.update(
            {
                "status": suite_status,
                "completed_at": datetime.now(UTC).isoformat(),
                "comparison_path": str(comparison_path),
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
    except BaseException as exc:
        suite_manifest.update(
            {
                "status": "failed",
                "completed_at": datetime.now(UTC).isoformat(),
                "error": str(exc) or exc.__class__.__name__,
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
        raise

    return QasperEvidenceSelectionSuiteResult(
        suite_id=selected_suite_id,
        suite_directory=suite_directory,
        manifest_path=manifest_path,
        comparison_path=comparison_path,
        variant_count=len(comparison_rows),
        status=suite_manifest["status"],
    )


def run_qasper_adaptive_retrieval_ablation(
    dataset: QasperDataset,
    *,
    root: str | Path | None = None,
    mode: str = "smoke",
    limit: int | None = None,
    seed: int = 42,
    config: RagConfig | None = None,
    variants: Sequence[str] = (
        "one_shot",
        "multi_query",
        "evidence_gated",
        "requirement_aware",
    ),
    embedding_provider: EmbeddingProvider | None = None,
    reranker: Any | None = None,
    answerer: QasperAnswerer | None = None,
    query_planner: Any | None = None,
    suite_id: str | None = None,
    question_ids_file: str | Path | None = None,
    evidence_selection_variant: str | None = None,
    quality_profile: Mapping[str, Any] | None = None,
    quality_profile_sha256: str | None = None,
) -> QasperAdaptiveRetrievalSuiteResult:
    """Compare one-shot, multi-query, gate, and requirement-aware retrieval."""

    normalized_mode = mode.strip().casefold()
    if normalized_mode not in RUN_LIMITS:
        raise ValueError(f"mode must be one of: {', '.join(RUN_LIMITS)}")
    selected_limit = RUN_LIMITS[normalized_mode] if limit is None else limit
    if selected_limit is not None and selected_limit <= 0:
        raise ValueError("limit must be positive")
    selected_variants = [str(value).strip().casefold() for value in variants]
    allowed_variants = {
        "one_shot",
        "multi_query",
        "evidence_gated",
        "requirement_aware",
    }
    if not selected_variants:
        raise ValueError("at least one adaptive-retrieval variant is required")
    if any(value not in allowed_variants for value in selected_variants):
        raise ValueError(
            "adaptive-retrieval variants must be one_shot, multi_query, evidence_gated, or requirement_aware"
        )
    if len(set(selected_variants)) != len(selected_variants):
        raise ValueError("adaptive-retrieval variants must be unique")
    normalized_evidence_selection_variant = (
        str(evidence_selection_variant).strip().casefold()
        if evidence_selection_variant is not None
        else None
    )
    resolved_quality_profile = (
        _validated_evidence_selection_profile(quality_profile)
        if normalized_evidence_selection_variant is not None
        else None
    )
    resolved_quality_profile_sha256 = (
        quality_profile_sha256
        or (
            hashlib.sha256(
                json.dumps(
                    resolved_quality_profile,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if resolved_quality_profile is not None
            else None
        )
    )
    if normalized_evidence_selection_variant is not None:
        if normalized_evidence_selection_variant not in {
            *resolved_quality_profile["selected_top_k_by_variant"],
            "raw_top_k",
            "rerank_top_k",
        }:
            raise ValueError(
                "evidence_selection_variant must be defined by the active quality profile"
            )
        if set(selected_variants).difference({"one_shot", "requirement_aware"}):
            raise ValueError(
                "evidence-selection ablations support one_shot and requirement_aware variants only"
            )
    if query_planner is None and set(selected_variants).intersection(
        {"multi_query", "evidence_gated", "requirement_aware"}
    ):
        raise ValueError(
            "a query_planner is required for multi_query, evidence_gated, and requirement_aware variants"
        )

    benchmark_directory = benchmark_root(root)
    source_config = (config or RagConfig()).model_copy(deep=True)
    model_manager: ModelManager | None = None
    if embedding_provider is None or reranker is None:
        model_manager = ModelManager()
    shared_embedding = embedding_provider or create_embedding_provider(
        source_config.embedding,
        model_manager=model_manager,
    )
    shared_reranker = reranker or Qwen3RerankerProvider(
        source_config.reranker,
        model_manager=model_manager,
    )
    selected_suite_id = suite_id or _new_run_id(
        dataset.split,
        f"adaptive-retrieval-{normalized_mode}",
    )
    if not _RUN_ID.fullmatch(selected_suite_id):
        raise ValueError("suite_id may contain only letters, digits, dots, underscores, and hyphens")
    suite_directory = benchmark_directory / "adaptive_retrieval" / selected_suite_id
    suite_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = suite_directory / "manifest.json"
    comparison_path = suite_directory / "comparison.json"
    suite_manifest: dict[str, Any] = {
        "manifest_version": 1,
        "suite_id": selected_suite_id,
        "dataset": "qasper",
        "dataset_version": dataset.dataset_version,
        "split": dataset.split,
        "mode": normalized_mode,
        "limit": selected_limit,
        "seed": seed,
        "index_rebuild": False,
        "status": "running",
        "variants": selected_variants,
        "query_planner": type(query_planner).__name__ if query_planner else None,
        "evidence_selection_variant": normalized_evidence_selection_variant,
        "quality_profile": resolved_quality_profile,
        "quality_profile_sha256": resolved_quality_profile_sha256,
        "answer_contract": (
            getattr(answerer, "answer_contract_manifest", None)
            if answerer is not None
            else None
        ),
        "requirement_max_retrieval_rounds": 3,
        "completed_runs": [],
        "started_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_json(manifest_path, suite_manifest)

    comparison_rows: list[dict[str, Any]] = []
    try:
        for variant_id in selected_variants:
            run_id = f"{selected_suite_id[:100]}-ar-{variant_id.replace('_', '-')}"
            result = run_qasper_benchmark(
                dataset,
                root=benchmark_directory,
                mode=normalized_mode,
                limit=selected_limit,
                seed=seed,
                config=source_config,
                embedding_provider=shared_embedding,
                reranker=shared_reranker,
                answerer=answerer,
                query_planner=query_planner,
                evidence_selection_variant=normalized_evidence_selection_variant,
                quality_profile=resolved_quality_profile,
                quality_profile_sha256=resolved_quality_profile_sha256,
                adaptive_variant=variant_id,
                run_id=run_id,
                question_ids_file=question_ids_file,
                rebuild_index=False,
            )
            from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run

            metrics = evaluate_qasper_run(result.run_directory, root=benchmark_directory)
            run_manifest = read_json(result.manifest_path) or {}
            row = {
                "variant_id": variant_id,
                "name": _adaptive_ablation_variant(variant_id).name,
                "run_id": result.run_id,
                "run_directory": str(result.run_directory),
                "run_status": result.run_status,
                "error_count": result.error_count,
                "index_cache_hit": bool(run_manifest.get("index", {}).get("cache_hit")),
                "paragraph_evidence": metrics["paragraph_evidence"],
                "official_qasper": metrics["official_qasper"],
                "performance_ms": metrics["performance_ms"],
                "context_metrics": metrics.get("context_metrics", {}),
                "adaptive_retrieval": metrics.get("adaptive_retrieval", {}),
                "evidence_gate_evaluation": metrics.get("evidence_gate_evaluation", {}),
                "evidence_requirement_evaluation": metrics.get(
                    "evidence_requirement_evaluation", {}
                ),
                "evidence_selection": metrics.get("evidence_selection", {}),
                "groundedness_metrics": metrics.get("groundedness_metrics", {}),
                "answer_provider_counts": metrics.get("answer_provider_counts", {}),
            }
            comparison_rows.append(row)
            suite_manifest["completed_runs"].append(
                {
                    "variant_id": variant_id,
                    "run_id": result.run_id,
                    "run_status": result.run_status,
                    "index_cache_hit": row["index_cache_hit"],
                }
            )
            atomic_write_json(manifest_path, suite_manifest)

        comparison = {
            "metric_version": 1,
            "suite_id": selected_suite_id,
            "variant_count": len(comparison_rows),
            "definition": {
                "index_rebuild": False,
                "shared_index_fingerprint": "all variants use identical corpus, chunking, and embedding configuration",
                "one_shot": "one hybrid Dense + BM25 + RRF retrieval followed by reranking",
                "multi_query": "bounded Query Planner rewrite and subqueries, fused through the existing retrieval merge",
                "evidence_gated": "multi-query retrieval with the existing evidence gate controlling bounded re-retrieval",
                "requirement_aware": "infer lightweight evidence requirements, plan distinct gap-driven retrieval queries, track novel chunks and lexical coverage, and stop on coverage, no new evidence, or a three-round budget",
                "requirement_coverage": "heuristic runtime coverage is reported separately from QASPER gold evidence recall",
            },
            "variants": comparison_rows,
        }
        atomic_write_json(comparison_path, comparison)
        suite_status = (
            "complete"
            if all(row["run_status"] == "complete" for row in comparison_rows)
            else "partial"
        )
        suite_manifest.update(
            {
                "status": suite_status,
                "completed_at": datetime.now(UTC).isoformat(),
                "comparison_path": str(comparison_path),
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
    except BaseException as exc:
        suite_manifest.update(
            {
                "status": "failed",
                "completed_at": datetime.now(UTC).isoformat(),
                "error": str(exc) or exc.__class__.__name__,
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
        raise

    return QasperAdaptiveRetrievalSuiteResult(
        suite_id=selected_suite_id,
        suite_directory=suite_directory,
        manifest_path=manifest_path,
        comparison_path=comparison_path,
        variant_count=len(comparison_rows),
        status=suite_manifest["status"],
    )


def run_qasper_raptor_ablation(
    dataset: QasperDataset,
    *,
    root: str | Path | None = None,
    mode: str = "smoke",
    limit: int | None = None,
    seed: int = 42,
    config: RagConfig | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    reranker: Any | None = None,
    summary_provider: RaptorSummaryProvider | None = None,
    answerer: QasperAnswerer | None = None,
    variants: Sequence[str] = ("R0", "R1", "R2", "R3"),
    suite_id: str | None = None,
    question_ids_file: str | Path | None = None,
    evidence_selection_variant: str | None = None,
    quality_profile: Mapping[str, Any] | None = None,
    quality_profile_sha256: str | None = None,
) -> QasperRaptorAblationSuiteResult:
    """Compare flat, mixed, collapsed, and hybrid RAPTOR retrieval variants."""

    normalized_mode = mode.strip().casefold()
    if normalized_mode not in RUN_LIMITS:
        raise ValueError(f"mode must be one of: {', '.join(RUN_LIMITS)}")
    selected_limit = RUN_LIMITS[normalized_mode] if limit is None else limit
    if selected_limit is not None and selected_limit <= 0:
        raise ValueError("limit must be positive")
    question_ids: tuple[str, ...] | None = None
    if question_ids_file is not None:
        question_ids, _ = read_question_ids_file(question_ids_file)
    selected_dataset = sample_qasper_dataset(
        dataset,
        limit=selected_limit,
        seed=seed,
        question_ids=question_ids,
    )
    selected_variants = [str(value).strip().upper() for value in variants]
    if not selected_variants:
        raise ValueError("at least one RAPTOR variant is required")
    if any(value not in {"R0", "R1", "R2", "R3"} for value in selected_variants):
        raise ValueError("RAPTOR variants must be selected from R0, R1, R2, and R3")
    if len(set(selected_variants)) != len(selected_variants):
        raise ValueError("RAPTOR variants must be unique")
    resolved_quality_profile = (
        _validated_evidence_selection_profile(quality_profile)
        if evidence_selection_variant is not None
        else None
    )
    if evidence_selection_variant not in {None, "evidence_selection"}:
        raise ValueError("RAPTOR suite supports the fixed evidence_selection variant")
    resolved_profile_sha256 = (
        quality_profile_sha256
        or (
            hashlib.sha256(
                json.dumps(
                    resolved_quality_profile,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if resolved_quality_profile is not None
            else None
        )
    )

    benchmark_directory = benchmark_root(root)
    source_config = (config or RagConfig()).model_copy(deep=True)
    model_manager: ModelManager | None = None
    if embedding_provider is None or reranker is None:
        model_manager = ModelManager()
    shared_embedding = embedding_provider or create_embedding_provider(
        source_config.embedding,
        model_manager=model_manager,
    )
    shared_reranker = reranker or Qwen3RerankerProvider(
        source_config.reranker,
        model_manager=model_manager,
    )
    shared_summarizer = summary_provider or ExtractiveRaptorSummaryProvider()

    selected_suite_id = suite_id or _new_run_id(
        selected_dataset.split,
        f"raptor-{normalized_mode}",
    )
    if not _RUN_ID.fullmatch(selected_suite_id):
        raise ValueError("suite_id may contain only letters, digits, dots, underscores, and hyphens")
    suite_directory = benchmark_directory / "raptor" / "ablation" / selected_suite_id
    suite_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = suite_directory / "manifest.json"
    comparison_path = suite_directory / "comparison.json"
    suite_manifest: dict[str, Any] = {
        "manifest_version": 1,
        "suite_id": selected_suite_id,
        "dataset": "qasper",
        "dataset_version": selected_dataset.dataset_version,
        "split": selected_dataset.split,
        "mode": normalized_mode,
        "limit": selected_limit,
        "seed": seed,
        "status": "building_trees",
        "index_rebuild": False,
        "variants": selected_variants,
        "summary_model": shared_summarizer.model_name,
        "prompt_version": shared_summarizer.prompt_version,
        "evidence_selection_variant": evidence_selection_variant,
        "quality_profile": resolved_quality_profile,
        "quality_profile_sha256": resolved_profile_sha256,
        "answer_contract": getattr(answerer, "answer_contract_manifest", None),
        "tree_cache_parameters": {
            "branching_factor": 4,
            "clustering_version": "greedy-cosine-medoid-v1",
            "query_parameters_included": False,
        },
        "completed_runs": [],
        "started_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_json(manifest_path, suite_manifest)

    index = None
    try:
        index = build_qasper_index(
            selected_dataset,
            storage_root=benchmark_directory,
            config=source_config,
            embedding_provider=shared_embedding,
            reranker=shared_reranker,
            rebuild=False,
        )
        chunks_by_document: dict[str, list[Any]] = {}
        expected_document_ids = {
            f"qasper:{selected_dataset.split}:{paper_id}"
            for paper_id in selected_dataset.papers
        }
        for chunk in index.runtime.sparse_retriever.list_chunks():
            if chunk.document_id in expected_document_ids:
                chunks_by_document.setdefault(chunk.document_id, []).append(chunk)

        tree_builder = RaptorTreeBuilder(
            embedding_provider=index.runtime.embedding_provider,
            summary_provider=shared_summarizer,
            cache_directory=benchmark_directory / "raptor" / "trees",
            branching_factor=4,
        )
        trees: dict[str, RaptorTree] = {}
        tree_manifest: dict[str, Any] = {}
        tree_build_total_ms = 0.0
        for document_id in sorted(expected_document_ids):
            chunks = chunks_by_document.get(document_id, [])
            if not chunks:
                raise ValueError(f"no leaf chunks found for RAPTOR document {document_id!r}")
            tree_started = perf_counter()
            tree = tree_builder.build(chunks)
            tree_build_ms = (perf_counter() - tree_started) * 1000
            tree_build_total_ms += tree_build_ms
            trees[document_id] = tree
            tree_manifest[document_id] = {
                "fingerprint": tree.fingerprint,
                "leaf_fingerprint": tree.leaf_fingerprint,
                "cache_path": str(tree.cache_path),
                "cache_hit": tree.cache_hit,
                "summary_node_count": len(tree.nodes),
                "summary_calls": tree.summary_calls if not tree.cache_hit else 0,
                "tree_build_ms": round(tree_build_ms, 3),
                "root_node_ids": list(tree.root_node_ids),
            }
        suite_manifest.update(
            {
                "status": "running",
                "index": {
                    "fingerprint": index.result.fingerprint,
                    "fingerprint_inputs": index.result.fingerprint_inputs,
                    "cache_hit": index.result.cache_hit,
                    "chunk_count": index.result.chunk_count,
                },
                "trees": tree_manifest,
                "tree_count": len(trees),
                "tree_build_total_ms": round(tree_build_total_ms, 3),
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
        index.close()
        index = None

        comparison_rows: list[dict[str, Any]] = []
        for variant in selected_variants:
            run_id = f"{selected_suite_id}-{variant.lower()}"
            result = run_qasper_benchmark(
                dataset,
                root=benchmark_directory,
                mode=normalized_mode,
                limit=selected_limit,
                seed=seed,
                config=source_config,
                embedding_provider=shared_embedding,
                reranker=shared_reranker,
                answerer=answerer,
                variant=None,
                raptor_variant=variant,
                raptor_trees=trees,
                evidence_selection_variant=evidence_selection_variant,
                quality_profile=resolved_quality_profile,
                quality_profile_sha256=resolved_profile_sha256,
                run_id=run_id,
                question_ids_file=question_ids_file,
                rebuild_index=False,
            )
            from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run

            metrics = evaluate_qasper_run(result.run_directory, root=benchmark_directory)
            run_manifest = read_json(result.manifest_path) or {}
            row = {
                "variant_id": variant,
                "run_id": result.run_id,
                "run_directory": str(result.run_directory),
                "run_status": result.run_status,
                "error_count": result.error_count,
                "index_cache_hit": bool(run_manifest.get("index", {}).get("cache_hit")),
                "raptor_category_metrics": metrics.get("raptor_category_metrics", {}),
                "ai_trans_retrieval": metrics["ai_trans_retrieval"],
                "paragraph_evidence": metrics["paragraph_evidence"],
                "official_qasper": metrics["official_qasper"],
                "performance_ms": metrics["performance_ms"],
                "context_metrics": metrics.get("context_metrics", {}),
                "groundedness_metrics": metrics.get("groundedness_metrics", {}),
                "answer_behavior": metrics.get("answer_behavior", {}),
                "answer_provider_counts": metrics.get("answer_provider_counts", {}),
                "estimated_llm_invocations": metrics.get(
                    "adaptive_retrieval", {}
                ).get("estimated_llm_invocations", 0),
            }
            comparison_rows.append(row)
            suite_manifest["completed_runs"].append(
                {
                    "variant_id": variant,
                    "run_id": result.run_id,
                    "run_status": result.run_status,
                    "index_cache_hit": row["index_cache_hit"],
                }
            )
            atomic_write_json(manifest_path, suite_manifest)

        comparison = {
            "metric_version": 1,
            "suite_id": selected_suite_id,
            "variant_count": len(comparison_rows),
            "definition": {
                "index_rebuild": False,
                "summary_cache_excludes_query_time_parameters": True,
                "R0": "current dense + BM25 + structural retrieval + reranker",
                "R1": "dense leaf retrieval mixed with ranked RAPTOR summaries, expanded to leaves",
                "R2": "ranked summary nodes only, collapsed to descendant leaf evidence",
                "R3": "current dense + BM25 + RRF joined with RAPTOR summary candidates before reranking",
                "category_definition": {
                    "Local": "gold evidence paragraphs all belong to one QASPER section",
                    "Cross-section": "a complete annotator gold set spans two sections",
                    "Global": "a complete annotator gold set spans at least three sections",
                    "Overall": "all questions, including questions without mapped evidence",
                },
            },
            "variants": comparison_rows,
        }
        atomic_write_json(comparison_path, comparison)
        suite_status = (
            "complete"
            if all(row["run_status"] == "complete" for row in comparison_rows)
            else "partial"
        )
        suite_manifest.update(
            {
                "status": suite_status,
                "completed_at": datetime.now(UTC).isoformat(),
                "comparison_path": str(comparison_path),
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
    except BaseException as exc:
        suite_manifest.update(
            {
                "status": "failed",
                "completed_at": datetime.now(UTC).isoformat(),
                "error": str(exc) or exc.__class__.__name__,
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
        raise
    finally:
        if index is not None:
            index.close()

    return QasperRaptorAblationSuiteResult(
        suite_id=selected_suite_id,
        suite_directory=suite_directory,
        manifest_path=manifest_path,
        comparison_path=comparison_path,
        variant_count=len(selected_variants),
        tree_count=len(trees),
        status=suite_manifest["status"],
    )


__all__ = [
    "RUN_LIMITS",
    "GroundedQasperAnswerer",
    "QasperAblationSuiteResult",
    "QasperAdaptiveRetrievalSuiteResult",
    "QasperAnswerInput",
    "QasperAnswerer",
    "QasperBenchmarkRunResult",
    "QasperEvidenceSelectionSuiteResult",
    "QasperGeneratedAnswer",
    "QasperRaptorAblationSuiteResult",
    "run_qasper_ablation",
    "run_qasper_adaptive_retrieval_ablation",
    "run_qasper_benchmark",
    "run_qasper_evidence_selection_ablation",
    "run_qasper_raptor_ablation",
]
