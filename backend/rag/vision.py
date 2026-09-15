from __future__ import annotations

import base64
import mimetypes
import os
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from app.ai.openai_compatible import OpenAICompatibleClient
from backend.rag.config import RagVisualUnderstandingConfig
from backend.rag.models import DocumentElement, NormalizedDocument

VISUAL_DESCRIPTION_INDEX_VERSION = "visual-description-v1"
VISUAL_DESCRIPTION_PROMPT_ID = "rag.visual_description@1.0.0"
_MAX_ERROR_CHARS = 240

_SYSTEM_PROMPT = """You create retrieval-grounded descriptions of figures from documents.
Describe only information visibly supported by the image. Do not speculate or invent values.
Prioritize: visual/figure type; visible labels, axes, legends, annotations and text; compared
entities; explicit relationships, trends, ordering, or topology. Keep the description concise,
plain-text, and useful for semantic retrieval. Do not repeat metadata unless it helps identify
the figure. Limit the answer to roughly 120 words."""


@runtime_checkable
class VisualDescriptionProvider(Protocol):
    name: str
    model_name: str

    def describe(
        self,
        *,
        image_path: Path,
        title: str,
        caption: str,
        page_number: int | None,
        section_path: Sequence[str],
    ) -> str: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class VisualDescriptionStats:
    picture_count: int = 0
    generated_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    unavailable_count: int = 0


def visual_description_index_version(config: RagVisualUnderstandingConfig) -> str:
    """Return a bounded fingerprint that invalidates indexes when VLM semantics change."""

    if not config.enabled:
        return f"{VISUAL_DESCRIPTION_INDEX_VERSION}-off"
    payload = "\x1f".join(
        (
            config.provider,
            config.model.strip(),
            config.base_url.strip().rstrip("/"),
            config.detail,
            str(config.max_images_per_document),
            str(config.max_asset_bytes),
            str(config.max_output_tokens or ""),
            VISUAL_DESCRIPTION_PROMPT_ID,
        )
    ).encode("utf-8")
    return f"{VISUAL_DESCRIPTION_INDEX_VERSION}-{sha256(payload).hexdigest()[:12]}"


def _file_uri_to_path(uri: str) -> Path:
    parsed = urlparse(str(uri or ""))
    if parsed.scheme != "file":
        raise ValueError("visual asset URI must use the file scheme")
    raw_path = url2pathname(unquote(parsed.path))
    if os.name == "nt" and len(raw_path) >= 3 and raw_path[0] in "/\\" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    if parsed.netloc:
        raw_path = f"//{parsed.netloc}{raw_path}"
    return Path(raw_path).expanduser().resolve()


def _image_data_url(path: Path, *, max_asset_bytes: int) -> str:
    stat = path.stat()
    if stat.st_size <= 0:
        raise ValueError("visual asset is empty")
    if stat.st_size > max_asset_bytes:
        raise ValueError(
            f"visual asset exceeds configured size limit: {stat.st_size} > {max_asset_bytes}"
        )
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not mime_type.startswith("image/"):
        raise ValueError(f"visual asset is not a recognized image: {path.name}")
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def _user_prompt(
    *,
    title: str,
    caption: str,
    page_number: int | None,
    section_path: Sequence[str],
) -> str:
    metadata: list[str] = []
    if title.strip():
        metadata.append(f"Document title: {title.strip()}")
    if caption.strip():
        metadata.append(f"Figure caption: {caption.strip()}")
    if section_path:
        metadata.append(f"Section: {' > '.join(item for item in section_path if item)}")
    if page_number is not None:
        metadata.append(f"Page: {page_number}")
    context = "\n".join(metadata) or "No reliable textual figure metadata is available."
    return (
        "Describe this figure for document retrieval and later grounded answering.\n"
        "Use the metadata only as context; image-visible evidence has priority.\n"
        f"{context}"
    )


class OpenAICompatibleVisualDescriptionProvider:
    """VLM adapter over the existing OpenAI-compatible client and credential path."""

    name = "openai_compatible"

    def __init__(
        self,
        config: RagVisualUnderstandingConfig,
        *,
        client: OpenAICompatibleClient | Any | None = None,
    ) -> None:
        self._config = config.model_copy(deep=True)
        self.model_name = self._config.model.strip()
        if not self.model_name:
            raise ValueError("visual understanding model must not be empty")
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            self._client = OpenAICompatibleClient(
                base_url=self._config.base_url,
                model=self.model_name,
                timeout=self._config.timeout_seconds,
                max_retries=self._config.max_retries,
            )
            self._owns_client = True

    def describe(
        self,
        *,
        image_path: Path,
        title: str,
        caption: str,
        page_number: int | None,
        section_path: Sequence[str],
    ) -> str:
        data_url = _image_data_url(
            image_path,
            max_asset_bytes=self._config.max_asset_bytes,
        )
        result = self._client.complete_messages(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": _user_prompt(
                                title=title,
                                caption=caption,
                                page_number=page_number,
                                section_path=section_path,
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url,
                                "detail": self._config.detail,
                            },
                        },
                    ],
                },
            ],
            temperature=0.0,
            max_tokens=self._config.max_output_tokens,
        )
        return str(result or "").strip()

    def close(self) -> None:
        if not self._owns_client:
            return
        close = getattr(self._client, "close", None)
        if callable(close):
            close()


def create_visual_description_provider(
    config: RagVisualUnderstandingConfig,
) -> VisualDescriptionProvider | None:
    """Best-effort runtime factory; optional VLM setup must never block RAG startup."""

    if not config.enabled:
        return None
    if config.provider != "openai_compatible":
        return None
    if not config.model.strip() or not config.base_url.strip():
        return None
    try:
        return OpenAICompatibleVisualDescriptionProvider(config)
    except Exception:
        return None


def _status_metadata(
    element: DocumentElement,
    *,
    config: RagVisualUnderstandingConfig,
    status: str,
    provider: VisualDescriptionProvider | None,
    description: str = "",
    error: str = "",
) -> dict[str, Any]:
    metadata = {
        **element.metadata,
        "image_understanding_enabled": bool(config.enabled),
        "visual_description_status": status,
        "visual_description_provider": (
            str(getattr(provider, "name", "") or "") if provider is not None else ""
        ),
        "visual_description_model": (
            str(getattr(provider, "model_name", "") or "") if provider is not None else ""
        ),
        "visual_description_prompt_id": VISUAL_DESCRIPTION_PROMPT_ID,
    }
    if description:
        metadata["visual_description"] = description
    if error:
        metadata["visual_description_error"] = error[:_MAX_ERROR_CHARS]
    return metadata


def _merge_surrogate(base_text: str, description: str) -> str:
    base = str(base_text or "").strip()
    visual = str(description or "").strip()
    if not visual:
        return base
    suffix = f"Visual description: {visual}"
    if not base:
        return suffix
    return f"{base} {suffix}"


def enrich_document_with_visual_descriptions(
    document: NormalizedDocument,
    *,
    config: RagVisualUnderstandingConfig,
    provider: VisualDescriptionProvider | None,
) -> NormalizedDocument:
    """Enrich picture surrogates with VLM descriptions without making VLM mandatory."""

    elements: list[DocumentElement] = []
    picture_count = 0
    generated = 0
    failed = 0
    skipped = 0
    unavailable = 0
    attempted = 0

    for element in document.elements:
        if element.modality != "picture":
            elements.append(element)
            continue
        picture_count += 1

        if not config.enabled:
            skipped += 1
            elements.append(
                element.model_copy(
                    update={
                        "metadata": _status_metadata(
                            element,
                            config=config,
                            status="disabled",
                            provider=provider,
                        )
                    }
                )
            )
            continue

        if provider is None:
            unavailable += 1
            elements.append(
                element.model_copy(
                    update={
                        "metadata": _status_metadata(
                            element,
                            config=config,
                            status="unavailable",
                            provider=None,
                        )
                    }
                )
            )
            continue

        if attempted >= config.max_images_per_document:
            skipped += 1
            elements.append(
                element.model_copy(
                    update={
                        "metadata": _status_metadata(
                            element,
                            config=config,
                            status="limit_skipped",
                            provider=provider,
                        )
                    }
                )
            )
            continue

        attempted += 1
        try:
            image_path = _file_uri_to_path(element.asset_uri)
            description = provider.describe(
                image_path=image_path,
                title=document.document.title,
                caption=element.caption,
                page_number=element.page_number,
                section_path=element.section_path,
            )
            if not description:
                raise ValueError("visual description provider returned empty content")
        except Exception as exc:
            failed += 1
            elements.append(
                element.model_copy(
                    update={
                        "metadata": _status_metadata(
                            element,
                            config=config,
                            status="failed",
                            provider=provider,
                            error=str(exc) or exc.__class__.__name__,
                        )
                    }
                )
            )
            continue

        generated += 1
        elements.append(
            element.model_copy(
                update={
                    "surrogate_text": _merge_surrogate(
                        element.surrogate_text,
                        description,
                    ),
                    "metadata": _status_metadata(
                        element,
                        config=config,
                        status="generated",
                        provider=provider,
                        description=description,
                    ),
                }
            )
        )

    stats = VisualDescriptionStats(
        picture_count=picture_count,
        generated_count=generated,
        failed_count=failed,
        skipped_count=skipped,
        unavailable_count=unavailable,
    )
    applied = generated > 0
    mode = (
        "surrogate_text_asset_and_vlm_description"
        if applied
        else str(
            document.metadata.get("visual_content_mode")
            or document.document.metadata.get("visual_content_mode")
            or "surrogate_text_and_asset"
        )
    )
    metadata_update = {
        "image_understanding_enabled": bool(config.enabled),
        "image_understanding_available": provider is not None,
        "image_understanding_applied": applied,
        "visual_description_picture_count": stats.picture_count,
        "visual_description_generated_count": stats.generated_count,
        "visual_description_failed_count": stats.failed_count,
        "visual_description_skipped_count": stats.skipped_count,
        "visual_description_unavailable_count": stats.unavailable_count,
        "visual_content_mode": mode,
        "visual_description_index_version": visual_description_index_version(config),
    }
    return document.model_copy(
        update={
            "document": document.document.model_copy(
                update={
                    "metadata": {
                        **document.document.metadata,
                        **metadata_update,
                    }
                }
            ),
            "elements": elements,
            "metadata": {
                **document.metadata,
                **metadata_update,
            },
        }
    )


__all__ = [
    "OpenAICompatibleVisualDescriptionProvider",
    "VISUAL_DESCRIPTION_INDEX_VERSION",
    "VISUAL_DESCRIPTION_PROMPT_ID",
    "VisualDescriptionProvider",
    "VisualDescriptionStats",
    "create_visual_description_provider",
    "enrich_document_with_visual_descriptions",
    "visual_description_index_version",
]
