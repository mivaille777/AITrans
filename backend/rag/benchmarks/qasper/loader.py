from __future__ import annotations

import hashlib
import json
import os
import ssl
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.request import Request, urlopen

import certifi

from backend.rag.benchmarks.qasper.schema import (
    QasperAnswer,
    QasperDataset,
    QasperPaper,
    QasperParagraph,
    QasperQuestion,
    QasperSection,
)

DATASET_VERSION = "0.3"
QASPER_ARCHIVE_URL = (
    "https://qasper-dataset.s3.us-west-2.amazonaws.com/"
    "qasper-train-dev-v0.3.tgz"
)
_SPLIT_FILES = {
    "train": "qasper-train-v0.3.json",
    "dev": "qasper-dev-v0.3.json",
    "validation": "qasper-dev-v0.3.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, writer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _download_archive(path: Path) -> None:
    def write(handle) -> None:
        request = Request(
            QASPER_ARCHIVE_URL,
            headers={"User-Agent": "AITrans-QASPER-Benchmark/1.0"},
        )
        with urlopen(
            request,
            timeout=60,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response:
            while block := response.read(1024 * 1024):
                handle.write(block)

    _atomic_write(path, write)


def _extract_member(archive_path: Path, expected_name: str, destination: Path) -> None:
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = [
            member
            for member in archive.getmembers()
            if PurePosixPath(member.name).name == expected_name
            and member.isfile()
        ]
        if len(members) != 1:
            raise ValueError(
                f"expected one {expected_name!r} file in the QASPER archive; "
                f"found {len(members)}"
            )
        source = archive.extractfile(members[0])
        if source is None:
            raise ValueError(f"could not read {expected_name!r} from QASPER archive")

        def write(handle) -> None:
            while block := source.read(1024 * 1024):
                handle.write(block)

        _atomic_write(destination, write)


def download_qasper_split(
    split: str,
    raw_directory: str | Path,
    *,
    manifest_directory: str | Path | None = None,
    redownload: bool = False,
) -> Path:
    """Download and extract the official QASPER v0.3 train or dev JSON.

    ``validation`` is the benchmark-facing alias for the public ``dev`` split.
    Existing extracted data is reused by default, and both archive and JSON
    checksums are written to a local manifest.
    """

    normalized_split = split.strip().casefold()
    try:
        filename = _SPLIT_FILES[normalized_split]
    except KeyError as exc:
        raise ValueError("QASPER split must be train, dev, or validation") from exc

    raw_root = Path(raw_directory).expanduser().resolve()
    raw_root.mkdir(parents=True, exist_ok=True)
    target = raw_root / filename
    archive = raw_root / "qasper-train-dev-v0.3.tgz"
    archive_sha256 = ""
    downloaded_at = datetime.now(UTC).isoformat()
    if redownload:
        target.unlink(missing_ok=True)
        archive.unlink(missing_ok=True)
    if not target.exists():
        if not archive.exists():
            _download_archive(archive)
        archive_sha256 = _sha256(archive)
        _extract_member(archive, filename, target)
    elif archive.exists():
        archive_sha256 = _sha256(archive)

    # Parse once here so a partial download or incompatible archive is not
    # recorded as successfully prepared data.
    with target.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError("QASPER JSON root must be an object keyed by paper id")

    manifest_root = (
        Path(manifest_directory).expanduser().resolve()
        if manifest_directory is not None
        else raw_root.parent / "manifests"
    )
    manifest_root.mkdir(parents=True, exist_ok=True)
    public_split = "validation" if normalized_split in {"dev", "validation"} else "train"
    manifest = {
        "dataset": "qasper",
        "dataset_version": DATASET_VERSION,
        "split": public_split,
        "source_split": "dev" if public_split == "validation" else "train",
        "source_url": QASPER_ARCHIVE_URL,
        "archive_sha256": archive_sha256,
        "raw_file": target.name,
        "raw_sha256": _sha256(target),
        "paper_count": len(payload),
        "prepared_at": downloaded_at,
    }
    manifest_path = manifest_root / f"qasper-{normalized_split}-v{DATASET_VERSION}.json"
    serialized = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(manifest_path, lambda handle: handle.write(serialized))
    return target


def _string_tuple(value: Any, *, field: str, context: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if not isinstance(value, list):
        raise TypeError(f"{context}: {field} must be a string list")
    if any(not isinstance(item, str) for item in value):
        raise TypeError(f"{context}: {field} contains a non-string value")
    return tuple(item for item in value if item.strip())


def _answer_type(
    answer_data: dict[str, Any], annotation: dict[str, Any]
) -> tuple[str, bool, bool | None]:
    unanswerable = bool(answer_data.get("unanswerable", False))
    yes_no = answer_data.get("yes_no")
    if yes_no is not None and not isinstance(yes_no, bool):
        raise ValueError("QASPER yes_no must be true, false, or null")
    declared = str(
        answer_data.get("type")
        or answer_data.get("answer_type")
        or annotation.get("type")
        or ""
    ).strip().casefold()
    extractive = answer_data.get("extractive_spans") or []
    free_form = str(answer_data.get("free_form_answer") or "").strip()
    if unanswerable or declared in {"unanswerable", "none"}:
        return "none", True, yes_no
    if extractive or declared == "extractive":
        return "extractive", False, yes_no
    if free_form or declared == "abstractive":
        return "abstractive", False, yes_no
    if yes_no is not None or declared in {"boolean", "yes_no"}:
        return "boolean", False, yes_no
    if declared:
        return declared, False, yes_no
    return "abstractive", False, yes_no


def _paper_sections(
    raw_paper: dict[str, Any], paper_id: str, split: str
) -> tuple[QasperSection, ...]:
    raw_sections = raw_paper.get("full_text") or []
    if not isinstance(raw_sections, list):
        raise TypeError(f"paper {paper_id}: full_text must be a list")
    parsed: list[tuple[str, list[str]]] = []
    for section_index, section in enumerate(raw_sections):
        if not isinstance(section, dict):
            raise TypeError(f"paper {paper_id}: full_text[{section_index}] must be an object")
        name = str(section.get("section_name") or "").strip() or "Untitled section"
        raw_paragraphs = section.get("paragraphs") or []
        if not isinstance(raw_paragraphs, list):
            raise TypeError(
                f"paper {paper_id}: section {section_index} paragraphs must be a list"
            )
        paragraphs: list[str] = []
        for paragraph in raw_paragraphs:
            if not isinstance(paragraph, str):
                raise TypeError(
                    f"paper {paper_id}: section {section_index} has a non-string paragraph"
                )
            if paragraph.strip():
                paragraphs.append(paragraph)
        if paragraphs:
            parsed.append((name, paragraphs))

    abstract = str(raw_paper.get("abstract") or "").strip()
    if abstract and not any(
        name.casefold() == "abstract"
        or any(paragraph.strip() == abstract for paragraph in paragraphs)
        for name, paragraphs in parsed
    ):
        parsed.insert(0, ("Abstract", [abstract]))

    result: list[QasperSection] = []
    global_index = 0
    for section_index, (name, paragraphs) in enumerate(parsed):
        items = []
        for paragraph_index, text in enumerate(paragraphs):
            items.append(
                QasperParagraph(
                    paragraph_id=f"qasper:{split}:{paper_id}:p{global_index}",
                    global_index=global_index,
                    section_index=section_index,
                    section_name=name,
                    paragraph_index=paragraph_index,
                    text=text,
                )
            )
            global_index += 1
        result.append(
            QasperSection(name=name, section_index=section_index, paragraphs=tuple(items))
        )
    return tuple(result)


def load_qasper(path: str | Path, *, split: str = "validation") -> QasperDataset:
    """Load QASPER v0.3 while retaining every annotator and evidence field."""

    normalized_split = split.strip().casefold()
    if normalized_split not in _SPLIT_FILES:
        raise ValueError("QASPER split must be train, dev, or validation")
    source = Path(path).expanduser().resolve()
    try:
        raw_bytes = source.read_bytes()
        raw = json.loads(raw_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load QASPER JSON: {source}") from exc
    if not isinstance(raw, dict):
        raise TypeError("QASPER JSON root must be an object keyed by paper id")

    public_split = "validation" if normalized_split == "dev" else normalized_split
    papers: dict[str, QasperPaper] = {}
    questions: list[QasperQuestion] = []
    seen_question_ids: set[str] = set()
    for paper_id, raw_paper in raw.items():
        paper_id = str(paper_id).strip()
        if not paper_id or not isinstance(raw_paper, dict):
            raise ValueError("QASPER paper entries must be objects with non-empty ids")
        sections = _paper_sections(raw_paper, paper_id, public_split)
        raw_qas = raw_paper.get("qas") or []
        if not isinstance(raw_qas, list):
            raise TypeError(f"paper {paper_id}: qas must be a list")
        paper_question_ids: list[str] = []
        for qa_index, raw_qa in enumerate(raw_qas):
            if not isinstance(raw_qa, dict):
                raise TypeError(f"paper {paper_id}: qas[{qa_index}] must be an object")
            question_id = str(raw_qa.get("question_id") or "").strip()
            if not question_id:
                raise ValueError(f"paper {paper_id}: qas[{qa_index}] has no question_id")
            if question_id in seen_question_ids:
                raise ValueError(f"duplicate QASPER question_id: {question_id}")
            seen_question_ids.add(question_id)
            raw_answers = raw_qa.get("answers") or []
            if not isinstance(raw_answers, list):
                raise TypeError(f"question {question_id}: answers must be a list")
            answers: list[QasperAnswer] = []
            for annotation_index, annotation in enumerate(raw_answers):
                if not isinstance(annotation, dict):
                    raise TypeError(
                        f"question {question_id}: answers[{annotation_index}] must be an object"
                    )
                answer_data = annotation.get("answer") or annotation
                if not isinstance(answer_data, dict):
                    raise TypeError(
                        f"question {question_id}: answers[{annotation_index}].answer must be an object"
                    )
                answer_type, unanswerable, yes_no = _answer_type(answer_data, annotation)
                context = f"question {question_id}, annotation {annotation_index}"
                evidence = answer_data.get("evidence", annotation.get("evidence"))
                highlighted = answer_data.get(
                    "highlighted_evidence", annotation.get("highlighted_evidence")
                )
                answers.append(
                    QasperAnswer(
                        annotation_id=str(
                            annotation.get("annotation_id")
                            or answer_data.get("annotation_id")
                            or f"{question_id}:a{annotation_index}"
                        ),
                        answer_type=answer_type,
                        extractive_spans=_string_tuple(
                            answer_data.get("extractive_spans"),
                            field="extractive_spans",
                            context=context,
                        ),
                        free_form_answer=str(answer_data.get("free_form_answer") or ""),
                        yes_no=yes_no,
                        unanswerable=unanswerable,
                        evidence_texts=_string_tuple(
                            evidence, field="evidence", context=context
                        ),
                        highlighted_evidence=_string_tuple(
                            highlighted,
                            field="highlighted_evidence",
                            context=context,
                        ),
                    )
                )
            question = QasperQuestion(
                question_id=question_id,
                paper_id=paper_id,
                question=str(raw_qa.get("question") or "").strip(),
                answers=tuple(answers),
            )
            questions.append(question)
            paper_question_ids.append(question_id)
        papers[paper_id] = QasperPaper(
            paper_id=paper_id,
            title=str(raw_paper.get("title") or "").strip(),
            abstract=str(raw_paper.get("abstract") or ""),
            sections=sections,
            question_ids=tuple(paper_question_ids),
        )

    return QasperDataset(
        dataset_version=DATASET_VERSION,
        split=public_split,
        papers=papers,
        questions=tuple(questions),
        source_path=str(source),
        source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


__all__ = [
    "DATASET_VERSION",
    "QASPER_ARCHIVE_URL",
    "download_qasper_split",
    "load_qasper",
]
