from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from backend.api.knowledge_dependencies import get_rag_runtime
from backend.api.dependencies import get_companion_chat_service, get_rag_debug_service, get_rag_debug_store_service
from backend.models.rag_debug import (
    RagDebugCase,
    RagDebugCompareRequest,
    RagDebugCompareResponse,
    RagDebugConfigCreate,
    RagDebugConfigProfile,
    RagDebugConfigUpdate,
    RagDebugDataset,
    RagDebugDatasetCreate,
    RagDebugDatasetExport,
    RagDebugDatasetImport,
    RagDebugDocument,
    RagDebugEvaluationRequest,
    RagDebugEvaluationResponse,
    RagDebugRunAccepted,
    RagDebugRunEventsResponse,
    RagDebugRunRequest,
    RagDebugTraceResponse,
)
from backend.services.rag_debug_service import RagDebugService
from backend.services.rag_debug_store_service import RagDebugStoreService


router = APIRouter(prefix="/api/rag/debug", tags=["rag-debug"])
RuntimeDependency = Annotated[Any, Depends(get_rag_runtime)]
DebugServiceDependency = Annotated[RagDebugService, Depends(get_rag_debug_service)]
DebugStoreDependency = Annotated[RagDebugStoreService, Depends(get_rag_debug_store_service)]
CompanionChatDependency = Annotated[Any, Depends(get_companion_chat_service)]


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _case_payload(raw: object) -> RagDebugCase:
    if not isinstance(raw, dict):
        raise ValueError("Each dataset record must be a JSON object.")
    payload = dict(raw)
    aliases = {
        "case_id": ("case_id", "id"),
        "relevant_chunk_ids": ("relevant_chunk_ids", "goldChunks", "gold_chunks"),
        "expected_answer": ("expected_answer", "answer"),
        "query_type": ("query_type", "type"),
    }
    for target, keys in aliases.items():
        source = next((key for key in keys if key in payload), None)
        if source is not None:
            payload[target] = payload[source]
        for key in keys:
            if key != target:
                payload.pop(key, None)
    if "categories" not in payload:
        payload["categories"] = []
    if isinstance(payload["categories"], str):
        payload["categories"] = [payload["categories"]]
    if isinstance(payload.get("relevant_chunk_ids"), str):
        payload["relevant_chunk_ids"] = [payload["relevant_chunk_ids"]]
    if "answerable" in payload and "no_answer" not in payload:
        payload["no_answer"] = not bool(payload["answerable"])
    if isinstance(payload.get("tags"), str):
        payload["tags"] = [payload["tags"]]
    return RagDebugCase.model_validate(payload)


def _records_from_import(content: str, file_format: str | None) -> list[object]:
    normalized_format = (file_format or "").strip().lower()
    def parse_jsonl() -> list[object]:
        records: list[object] = []
        for line in content.splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                records.append(json.loads(line))
        return records

    if normalized_format == "jsonl":
        return parse_jsonl()

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        if normalized_format == "json":
            raise
        return parse_jsonl()

    if isinstance(payload, dict):
        payload = payload.get("cases", payload.get("data", [payload]))
    if not isinstance(payload, list):
        raise ValueError("JSON datasets must contain an array of cases.")
    return payload


@router.get("/configs", response_model=list[RagDebugConfigProfile])
def list_configs(runtime: RuntimeDependency, store: DebugStoreDependency) -> list[RagDebugConfigProfile]:
    store.ensure_default_config(runtime.config)
    return store.list_configs()


@router.post("/configs", response_model=RagDebugConfigProfile, status_code=status.HTTP_201_CREATED)
def create_config(payload: RagDebugConfigCreate, store: DebugStoreDependency) -> RagDebugConfigProfile:
    try:
        return store.create_config(
            name=payload.name,
            description=payload.description,
            config=payload.config,
            activate=payload.activate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/configs/{config_id}", response_model=RagDebugConfigProfile)
def update_config(config_id: str, payload: RagDebugConfigUpdate, store: DebugStoreDependency) -> RagDebugConfigProfile:
    try:
        profile = store.update_config(
            config_id,
            name=payload.name,
            description=payload.description,
            config=payload.config,
            activate=payload.activate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if profile is None:
        raise _not_found("RAG config profile not found.")
    return profile


@router.post("/configs/{config_id}/activate", response_model=RagDebugConfigProfile)
def activate_config(config_id: str, store: DebugStoreDependency) -> RagDebugConfigProfile:
    profile = store.activate_config(config_id)
    if profile is None:
        raise _not_found("RAG config profile not found.")
    return profile


@router.post("/configs/{config_id}/clear-reindex", response_model=RagDebugConfigProfile)
def clear_config_reindex(config_id: str, store: DebugStoreDependency) -> RagDebugConfigProfile:
    profile = store.clear_requires_reindex(config_id)
    if profile is None:
        raise _not_found("RAG config profile not found.")
    return profile


@router.delete("/configs/{config_id}")
def delete_config(config_id: str, store: DebugStoreDependency) -> dict[str, Any]:
    if not store.delete_config(config_id):
        raise _not_found("RAG config profile cannot be deleted or does not exist.")
    return {"config_id": config_id, "deleted": True}


@router.get("/documents", response_model=list[RagDebugDocument])
def list_documents(runtime: RuntimeDependency, service: DebugServiceDependency) -> list[RagDebugDocument]:
    return service.list_documents(runtime)


@router.get("/chunks")
def list_chunks(
    runtime: RuntimeDependency,
    service: DebugServiceDependency,
    document_id: Annotated[str, Query(max_length=256)] = "",
    q: Annotated[str, Query(alias="query", max_length=4_000)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
):
    return service.list_chunks(
        runtime,
        document_id=document_id,
        query=q,
        page=page,
        page_size=page_size,
    )


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str, runtime: RuntimeDependency, service: DebugServiceDependency):
    chunk = service.get_chunk(runtime, chunk_id)
    if chunk is None:
        raise _not_found("RAG chunk not found.")
    return chunk


@router.post("/runs", response_model=RagDebugRunAccepted, status_code=status.HTTP_202_ACCEPTED)
def start_run(
    payload: RagDebugRunRequest,
    runtime: RuntimeDependency,
    service: DebugServiceDependency,
    answer_service: CompanionChatDependency,
) -> RagDebugRunAccepted:
    service.ensure_default_config(runtime.config)
    if service.store.get_config(payload.config_id) is None:
        raise _not_found("RAG config profile not found.")
    return service.start_trace(payload, runtime=runtime, answer_service=answer_service)


@router.get("/runs/{run_id}", response_model=RagDebugTraceResponse)
def get_run(run_id: str, service: DebugServiceDependency) -> RagDebugTraceResponse:
    response = service.get_run(run_id)
    if response is None:
        raise _not_found("RAG debug run not found.")
    return response


@router.get("/runs/{run_id}/events", response_model=RagDebugRunEventsResponse)
def get_run_events(
    run_id: str,
    service: DebugServiceDependency,
    after: Annotated[int, Query(ge=-1)] = -1,
) -> RagDebugRunEventsResponse:
    response = service.get_events(run_id, after=after)
    if response is None:
        raise _not_found("RAG debug run not found.")
    return response


@router.post("/runs/{run_id}/cancel", response_model=RagDebugTraceResponse)
def cancel_run(run_id: str, service: DebugServiceDependency) -> RagDebugTraceResponse:
    response = service.cancel(run_id)
    if response is None:
        raise _not_found("RAG debug run not found.")
    return response


@router.websocket("/runs/{run_id}/stream")
async def stream_run(websocket: WebSocket, run_id: str, service: DebugServiceDependency) -> None:
    await websocket.accept()
    cursor = -1
    try:
        while True:
            events = service.get_events(run_id, after=cursor)
            if events is None:
                await websocket.send_json({"type": "error", "message": "RAG debug run not found."})
                return
            for event in events.events:
                cursor = max(cursor, event.sequence)
                await websocket.send_json({"type": "activity", "event": event.model_dump(mode="json")})
            response = service.get_run(run_id)
            if response is None:
                return
            if response.status in {"completed", "failed", "cancelled"}:
                await websocket.send_json({"type": "done", "trace": response.model_dump(mode="json")})
                return
            await asyncio.sleep(0.12)
    except WebSocketDisconnect:
        return


@router.get("/datasets", response_model=list[RagDebugDataset])
def list_datasets(store: DebugStoreDependency) -> list[RagDebugDataset]:
    return store.list_datasets()


@router.post("/datasets", response_model=RagDebugDataset, status_code=status.HTTP_201_CREATED)
def create_dataset(payload: RagDebugDatasetCreate, store: DebugStoreDependency) -> RagDebugDataset:
    try:
        return store.create_dataset(payload.name, payload.description)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, store: DebugStoreDependency) -> dict[str, Any]:
    if not store.delete_dataset(dataset_id):
        raise _not_found("RAG evaluation dataset not found.")
    return {"dataset_id": dataset_id, "deleted": True}


@router.get("/datasets/{dataset_id}/cases", response_model=list[RagDebugCase])
def list_cases(dataset_id: str, store: DebugStoreDependency) -> list[RagDebugCase]:
    if store.get_dataset(dataset_id) is None:
        raise _not_found("RAG evaluation dataset not found.")
    return store.list_cases(dataset_id)


@router.post("/datasets/{dataset_id}/cases", response_model=RagDebugCase, status_code=status.HTTP_201_CREATED)
def save_case(dataset_id: str, payload: RagDebugCase, store: DebugStoreDependency) -> RagDebugCase:
    try:
        return store.save_case(dataset_id, payload)
    except KeyError as exc:
        raise _not_found("RAG evaluation dataset not found.") from exc


@router.patch("/datasets/{dataset_id}/cases/{case_id}", response_model=RagDebugCase)
def update_case(dataset_id: str, case_id: str, payload: RagDebugCase, store: DebugStoreDependency) -> RagDebugCase:
    if payload.case_id != case_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="case_id does not match the path.")
    try:
        return store.save_case(dataset_id, payload)
    except KeyError as exc:
        raise _not_found("RAG evaluation dataset not found.") from exc


@router.delete("/datasets/{dataset_id}/cases/{case_id}")
def delete_case(dataset_id: str, case_id: str, store: DebugStoreDependency) -> dict[str, Any]:
    if not store.delete_case(dataset_id, case_id):
        raise _not_found("RAG evaluation case not found.")
    return {"dataset_id": dataset_id, "case_id": case_id, "deleted": True}


@router.post("/datasets/import", response_model=RagDebugDataset, status_code=status.HTTP_201_CREATED)
def import_dataset(payload: RagDebugDatasetImport, store: DebugStoreDependency) -> RagDebugDataset:
    try:
        records = _records_from_import(payload.content, payload.format)
        cases = [_case_payload(item) for item in records]
        if len({case.case_id for case in cases}) != len(cases):
            raise ValueError("Dataset case_id values must be unique.")
        dataset = store.create_dataset(payload.name, payload.description)
        return store.replace_cases(dataset.dataset_id, cases)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/datasets/{dataset_id}/export", response_model=RagDebugDatasetExport)
def export_dataset(
    dataset_id: str,
    store: DebugStoreDependency,
    file_format: Annotated[str, Query(alias="format")] = "json",
) -> RagDebugDatasetExport:
    dataset = store.get_dataset(dataset_id)
    if dataset is None:
        raise _not_found("RAG evaluation dataset not found.")
    cases = [case.model_dump(mode="json") for case in store.list_cases(dataset_id)]
    normalized_format = file_format if file_format in {"json", "jsonl"} else "json"
    content = (
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases)
        if normalized_format == "jsonl"
        else json.dumps(cases, ensure_ascii=False, indent=2)
    )
    return RagDebugDatasetExport(dataset=dataset, format=normalized_format, content=content)


@router.post("/evaluation", response_model=RagDebugEvaluationResponse)
def evaluate_dataset(
    payload: RagDebugEvaluationRequest,
    runtime: RuntimeDependency,
    service: DebugServiceDependency,
    store: DebugStoreDependency,
) -> RagDebugEvaluationResponse:
    store.ensure_default_config(runtime.config)
    if store.get_dataset(payload.dataset_id) is None:
        raise _not_found("RAG evaluation dataset not found.")
    if store.get_config(payload.config_id) is None:
        raise _not_found("RAG config profile not found.")
    try:
        report = service.evaluate_dataset(
            dataset_id=payload.dataset_id,
            config_id=payload.config_id,
            top_k=payload.top_k,
            case_ids=payload.case_ids,
            runtime=runtime,
        )
    except KeyError as exc:
        raise _not_found("RAG evaluation dataset not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return RagDebugEvaluationResponse(dataset_id=payload.dataset_id, config_id=payload.config_id, report=report)


@router.post("/compare", response_model=RagDebugCompareResponse)
def compare_dataset(
    payload: RagDebugCompareRequest,
    runtime: RuntimeDependency,
    service: DebugServiceDependency,
    store: DebugStoreDependency,
) -> RagDebugCompareResponse:
    store.ensure_default_config(runtime.config)
    if store.get_dataset(payload.dataset_id) is None:
        raise _not_found("RAG evaluation dataset not found.")
    if store.get_config(payload.baseline_config_id) is None:
        raise _not_found("Baseline RAG config profile not found.")
    if store.get_config(payload.candidate_config_id) is None:
        raise _not_found("Candidate RAG config profile not found.")
    try:
        return service.compare_dataset(
            dataset_id=payload.dataset_id,
            baseline_config_id=payload.baseline_config_id,
            candidate_config_id=payload.candidate_config_id,
            top_k=payload.top_k,
            case_ids=payload.case_ids,
            runtime=runtime,
        )
    except KeyError as exc:
        raise _not_found("RAG evaluation dataset or config profile not found.") from exc


__all__ = ["router"]
