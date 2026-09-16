from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from backend.models.agent_artifacts import (
    ArtifactRef,
    ClaimRecord,
    ManuscriptSectionArtifact,
    OutlineArtifact,
    ReferenceRecord,
    RevisionArtifact,
    RevisionChange,
    VerificationIssue,
    VerificationReport,
    VerificationStatus,
)
from backend.models.writing_projects import (
    WritingExportResponse,
    WritingOperationReceipt,
    WritingParagraph,
    WritingProjectSnapshot,
    WritingRevisionPreviewRequest,
    WritingRevisionPreviewResponse,
    WritingSectionSnapshot,
)

WRITING_PROJECT_SCHEMA_VERSION = 1


class WritingProjectError(ValueError):
    pass


class WritingProjectConflictError(WritingProjectError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash_text(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _split_paragraphs(markdown: str) -> list[str]:
    return [item.strip() for item in str(markdown).replace("\r\n", "\n").split("\n\n") if item.strip()]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class WritingProjectService:
    """Persist user-approved writing drafts beside the versioned artifact store."""

    def __init__(
        self,
        *,
        artifact_store: Any,
        database_path: str | Path | None = None,
        workspace_service: Any | None = None,
    ) -> None:
        inferred = getattr(artifact_store, "database_path", None)
        if database_path is None and inferred is None:
            raise ValueError("database_path is required for a non-SQLite artifact store")
        self.database_path = Path(database_path or inferred).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._artifacts = artifact_store
        self._workspaces = workspace_service
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS writing_project_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS writing_projects (
                    project_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    writing_goal TEXT NOT NULL DEFAULT '',
                    outline_artifact_id TEXT NOT NULL DEFAULT '',
                    outline_artifact_version INTEGER NOT NULL DEFAULT 0,
                    outline_version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_writing_projects_workspace
                    ON writing_projects(workspace_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS writing_section_versions (
                    project_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    artifact_id TEXT NOT NULL,
                    artifact_version INTEGER NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    markdown TEXT NOT NULL DEFAULT '',
                    paragraphs_json TEXT NOT NULL DEFAULT '[]',
                    references_json TEXT NOT NULL DEFAULT '[]',
                    verification_status TEXT NOT NULL DEFAULT 'unverified',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, section_id, version),
                    FOREIGN KEY (project_id) REFERENCES writing_projects(project_id)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS writing_operations (
                    operation_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    result_version INTEGER NOT NULL,
                    artifact_id TEXT NOT NULL,
                    artifact_version INTEGER NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES writing_projects(project_id)
                        ON DELETE CASCADE
                );
                """
            )
            connection.execute(
                """
                INSERT INTO writing_project_state(key, value) VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(WRITING_PROJECT_SCHEMA_VERSION),),
            )

    def create(self, *, workspace_id: str, title: str, writing_goal: str = "") -> WritingProjectSnapshot:
        workspace = str(workspace_id).strip()
        if not workspace or not str(title).strip():
            raise WritingProjectError("workspace_id and title are required")
        if self._workspaces is not None and self._workspaces.get(workspace) is None:
            raise WritingProjectError("Research workspace not found")
        project_id = f"writing-{uuid4().hex}"
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO writing_projects(
                    project_id, workspace_id, title, writing_goal, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, workspace, str(title).strip(), str(writing_goal).strip(), now, now),
            )
        result = self.get(project_id)
        assert result is not None
        return result

    def list(self, *, workspace_id: str = "", limit: int = 100) -> tuple[WritingProjectSnapshot, ...]:
        bounded = max(1, min(500, int(limit)))
        query = "SELECT project_id FROM writing_projects"
        parameters: tuple[Any, ...]
        if str(workspace_id).strip():
            query += " WHERE workspace_id = ?"
            parameters = (str(workspace_id).strip(), bounded)
        else:
            parameters = (bounded,)
        query += " ORDER BY updated_at DESC LIMIT ?"
        with self._lock, self._connect() as connection:
            ids = [str(row["project_id"]) for row in connection.execute(query, parameters)]
        return tuple(item for item in (self.get(item_id) for item_id in ids) if item is not None)

    @staticmethod
    def _paragraphs(artifact: ManuscriptSectionArtifact) -> list[WritingParagraph]:
        markdown = _split_paragraphs(artifact.markdown)
        ids = list(artifact.paragraph_ids)
        if not ids:
            ids = [f"{artifact.section_id}:p{index}" for index in range(1, len(markdown) + 1)]
        if len(ids) != len(markdown) or len(ids) != len(set(ids)):
            raise WritingProjectError("paragraph_ids must uniquely match markdown paragraphs")
        return [
            WritingParagraph(
                paragraph_id=paragraph_id,
                markdown=text,
                content_hash=_hash_text(text),
                evidence_ids=list(artifact.claim_source_map.get(paragraph_id, [])),
            )
            for paragraph_id, text in zip(ids, markdown, strict=True)
        ]

    @staticmethod
    def _section_from_row(row: sqlite3.Row) -> WritingSectionSnapshot:
        return WritingSectionSnapshot(
            section_id=str(row["section_id"]),
            version=int(row["version"]),
            title=str(row["title"]),
            markdown=str(row["markdown"]),
            paragraphs=[WritingParagraph.model_validate(item) for item in json.loads(str(row["paragraphs_json"]))],
            artifact_ref=ArtifactRef(
                artifact_id=str(row["artifact_id"]),
                version=int(row["artifact_version"]),
                kind="manuscript_section",
                content_hash=str(row["artifact_hash"]),
            ),
            references=[ReferenceRecord.model_validate(item) for item in json.loads(str(row["references_json"]))],
            verification_status=str(row["verification_status"]),
            created_at=str(row["created_at"]),
        )

    def _latest_sections(self, connection: sqlite3.Connection, project_id: str) -> list[WritingSectionSnapshot]:
        rows = connection.execute(
            """
            SELECT versions.* FROM writing_section_versions AS versions
            JOIN (
                SELECT section_id, MAX(version) AS version
                FROM writing_section_versions WHERE project_id = ? GROUP BY section_id
            ) AS latest
            ON latest.section_id = versions.section_id AND latest.version = versions.version
            WHERE versions.project_id = ? ORDER BY versions.section_id
            """,
            (project_id, project_id),
        ).fetchall()
        return [self._section_from_row(row) for row in rows]

    def get(self, project_id: str) -> WritingProjectSnapshot | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM writing_projects WHERE project_id = ?",
                (str(project_id),),
            ).fetchone()
            if row is None:
                return None
            outline_ref = None
            if str(row["outline_artifact_id"]):
                artifact = self._artifacts.get(
                    str(row["outline_artifact_id"]),
                    int(row["outline_artifact_version"]),
                )
                if isinstance(artifact, OutlineArtifact):
                    outline_ref = artifact.ref()
            sections = self._latest_sections(connection, str(project_id))
        return WritingProjectSnapshot(
            project_id=str(row["project_id"]),
            workspace_id=str(row["workspace_id"]),
            title=str(row["title"]),
            writing_goal=str(row["writing_goal"]),
            outline_ref=outline_ref,
            outline_version=int(row["outline_version"]),
            sections=sections,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def save_outline(self, project_id: str, *, artifact_id: str, artifact_version: int, expected_version: int) -> WritingProjectSnapshot:
        artifact = self._artifacts.get(artifact_id, artifact_version)
        if not isinstance(artifact, OutlineArtifact):
            raise WritingProjectError("outline artifact not found or has the wrong type")
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT outline_version FROM writing_projects WHERE project_id = ?",
                (str(project_id),),
            ).fetchone()
            if row is None:
                raise WritingProjectError("Writing project not found")
            current = int(row["outline_version"])
            if current != int(expected_version):
                raise WritingProjectConflictError(
                    f"outline version conflict: expected {expected_version}, current {current}"
                )
            connection.execute(
                """
                UPDATE writing_projects SET outline_artifact_id = ?,
                    outline_artifact_version = ?, outline_version = ?, updated_at = ?
                WHERE project_id = ?
                """,
                (artifact.artifact_id, artifact.version, current + 1, _now(), str(project_id)),
            )
        result = self.get(project_id)
        assert result is not None
        return result

    def _current_section(self, connection: sqlite3.Connection, project_id: str, section_id: str) -> WritingSectionSnapshot | None:
        row = connection.execute(
            """
            SELECT * FROM writing_section_versions
            WHERE project_id = ? AND section_id = ? ORDER BY version DESC LIMIT 1
            """,
            (project_id, section_id),
        ).fetchone()
        return self._section_from_row(row) if row is not None else None

    def _insert_section(self, connection: sqlite3.Connection, project_id: str, artifact: ManuscriptSectionArtifact) -> WritingSectionSnapshot:
        paragraphs = self._paragraphs(artifact)
        now = _now()
        connection.execute(
            """
            INSERT INTO writing_section_versions(
                project_id, section_id, version, artifact_id, artifact_version,
                artifact_hash, title, markdown, paragraphs_json, references_json,
                verification_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                artifact.section_id,
                artifact.version,
                artifact.artifact_id,
                artifact.version,
                artifact.content_hash,
                artifact.title,
                artifact.markdown,
                _json([item.model_dump(mode="json") for item in paragraphs]),
                _json([item.model_dump(mode="json") for item in artifact.references]),
                artifact.verification_status.value,
                now,
            ),
        )
        connection.execute(
            "UPDATE writing_projects SET updated_at = ? WHERE project_id = ?",
            (now, project_id),
        )
        current = self._current_section(connection, project_id, artifact.section_id)
        assert current is not None
        return current

    def save_section(self, project_id: str, *, artifact_id: str, artifact_version: int, expected_version: int) -> WritingSectionSnapshot:
        artifact = self._artifacts.get(artifact_id, artifact_version)
        if not isinstance(artifact, ManuscriptSectionArtifact):
            raise WritingProjectError("manuscript section artifact not found or has the wrong type")
        with self._lock, self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM writing_projects WHERE project_id = ?", (str(project_id),)
            ).fetchone() is None:
                raise WritingProjectError("Writing project not found")
            current = self._current_section(connection, str(project_id), artifact.section_id)
            current_version = current.version if current is not None else 0
            if current_version != int(expected_version):
                raise WritingProjectConflictError(
                    f"section version conflict: expected {expected_version}, current {current_version}"
                )
            if artifact.version != current_version + 1:
                raise WritingProjectConflictError(
                    "artifact version must be the next section version"
                )
            return self._insert_section(connection, str(project_id), artifact)

    @staticmethod
    def _operation_hash(project_id: str, revision: RevisionArtifact, expected_version: int) -> str:
        return _hash_text(
            _json(
                {
                    "project_id": project_id,
                    "revision_ref": revision.ref().model_dump(mode="json"),
                    "expected_version": int(expected_version),
                }
            )
        )

    def apply_revision(
        self,
        project_id: str,
        *,
        artifact_id: str,
        artifact_version: int,
        expected_version: int,
        operation_id: str,
    ) -> WritingOperationReceipt:
        revision = self._artifacts.get(artifact_id, artifact_version)
        if not isinstance(revision, RevisionArtifact):
            raise WritingProjectError("revision artifact not found or has the wrong type")
        operation = str(operation_id).strip()
        if not operation:
            raise WritingProjectError("operation_id is required")
        payload_hash = self._operation_hash(str(project_id), revision, expected_version)
        with self._lock, self._connect() as connection:
            receipt = connection.execute(
                "SELECT * FROM writing_operations WHERE operation_id = ?", (operation,)
            ).fetchone()
            if receipt is not None:
                if str(receipt["payload_hash"]) != payload_hash:
                    raise WritingProjectConflictError(
                        "operation_id was already used for different revision content"
                    )
                return WritingOperationReceipt(
                    operation_id=operation,
                    project_id=str(receipt["project_id"]),
                    section_id=str(receipt["section_id"]),
                    result_version=int(receipt["result_version"]),
                    artifact_ref=ArtifactRef(
                        artifact_id=str(receipt["artifact_id"]),
                        version=int(receipt["artifact_version"]),
                        kind="manuscript_section",
                        content_hash=str(receipt["artifact_hash"]),
                    ),
                    replayed=True,
                )
            current = self._current_section(
                connection, str(project_id), revision.target_section_id
            )
            if current is None:
                raise WritingProjectError("target manuscript section not found")
            if current.version != int(expected_version) or revision.base_version != current.version:
                raise WritingProjectConflictError(
                    f"section version conflict: expected {expected_version}, current {current.version}"
                )
            base = self._artifacts.get(current.artifact_ref.artifact_id, current.artifact_ref.version)
            if not isinstance(base, ManuscriptSectionArtifact):
                raise WritingProjectError("base manuscript artifact is unavailable")
            allowed = set(revision.allowed_paragraph_ids)
            changes = {item.paragraph_id: item for item in revision.changes}
            if not set(changes).issubset(allowed):
                raise WritingProjectError("revision changes a paragraph outside the authorized range")
            paragraphs = {item.paragraph_id: item for item in current.paragraphs}
            if not set(changes).issubset(paragraphs):
                raise WritingProjectError("revision targets an unknown paragraph")
            available_evidence = {
                item.evidence_id for item in (*base.evidence_refs, *revision.evidence_refs)
            }
            claim_source_map = dict(base.claim_source_map)
            claims = list(base.claims)
            for paragraph_id, change in changes.items():
                paragraph = paragraphs[paragraph_id]
                if change.before_hash and change.before_hash != paragraph.content_hash:
                    raise WritingProjectConflictError(
                        f"paragraph {paragraph_id} changed after the revision was prepared"
                    )
                unknown_evidence = set(change.evidence_ids) - available_evidence
                if unknown_evidence:
                    raise WritingProjectError(
                        f"revision references unknown evidence: {sorted(unknown_evidence)}"
                    )
                if change.category == "fact" and not change.evidence_ids:
                    raise WritingProjectError("factual revision text requires evidence")
                paragraphs[paragraph_id] = WritingParagraph(
                    paragraph_id=paragraph_id,
                    markdown=change.replacement_markdown,
                    content_hash=_hash_text(change.replacement_markdown),
                    evidence_ids=list(change.evidence_ids),
                )
                claim_source_map[paragraph_id] = list(change.evidence_ids)
                if change.replacement_markdown.strip():
                    claims.append(
                        ClaimRecord(
                            claim_id=f"{revision.artifact_id}:{paragraph_id}",
                            statement=change.replacement_markdown,
                            category=change.category,
                            evidence_ids=list(change.evidence_ids),
                        )
                    )
            ordered = [paragraphs[item.paragraph_id] for item in current.paragraphs]
            markdown = "\n\n".join(item.markdown for item in ordered)
            missing = [
                item.paragraph_id
                for item in ordered
                if not item.evidence_ids and "[Missing" in item.markdown
            ]
            status = VerificationStatus.PARTIAL if missing else VerificationStatus.PASSED
            payload = base.model_dump(mode="python")
            payload.update(
                {
                    "version": base.version + 1,
                    "producer_task_id": revision.producer_task_id,
                    "markdown": markdown,
                    "paragraph_ids": [item.paragraph_id for item in ordered],
                    "claim_source_map": claim_source_map,
                    "claims": claims,
                    "evidence_refs": list(
                        {
                            item.evidence_id: item
                            for item in (*base.evidence_refs, *revision.evidence_refs)
                        }.values()
                    ),
                    "lineage": [base.ref(), revision.ref()],
                    "missing_inputs": sorted({*base.missing_inputs, *missing}),
                    "verification_status": status,
                    "verification_report": VerificationReport(
                        status=status,
                        checked_fields=["paragraph_scope", "before_hash", "claim_source_map"],
                        source_ids=sorted(
                            {item.source_id for item in (*base.evidence_refs, *revision.evidence_refs)}
                        ),
                        citation_count=sum(len(item.evidence_ids) for item in ordered),
                        issues=[
                            VerificationIssue(
                                code="missing_user_input",
                                message=f"Paragraph {item} remains a placeholder.",
                                field=item,
                            )
                            for item in missing
                        ],
                    ),
                    "content": {
                        **base.content,
                        "applied_revision_ref": revision.ref().model_dump(mode="json"),
                    },
                    "content_hash": "",
                    "created_at": datetime.now(UTC),
                }
            )
            updated = ManuscriptSectionArtifact.model_validate(payload)
            stored = self._artifacts.put(updated)
            section = self._insert_section(connection, str(project_id), stored)
            connection.execute(
                """
                INSERT INTO writing_operations(
                    operation_id, project_id, section_id, payload_hash, result_version,
                    artifact_id, artifact_version, artifact_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation,
                    str(project_id),
                    section.section_id,
                    payload_hash,
                    section.version,
                    stored.artifact_id,
                    stored.version,
                    stored.content_hash,
                    _now(),
                ),
            )
            return WritingOperationReceipt(
                operation_id=operation,
                project_id=str(project_id),
                section_id=section.section_id,
                result_version=section.version,
                artifact_ref=stored.ref(),
            )

    def prepare_revision(
        self,
        project_id: str,
        section_id: str,
        request: WritingRevisionPreviewRequest,
    ) -> WritingRevisionPreviewResponse:
        with self._lock, self._connect() as connection:
            current = self._current_section(connection, str(project_id), str(section_id))
        if current is None:
            raise WritingProjectError("target manuscript section not found")
        if current.version != request.expected_version:
            raise WritingProjectConflictError(
                f"section version conflict: expected {request.expected_version}, current {current.version}"
            )
        base = self._artifacts.get(current.artifact_ref.artifact_id, current.artifact_ref.version)
        if not isinstance(base, ManuscriptSectionArtifact):
            raise WritingProjectError("base manuscript artifact is unavailable")
        paragraphs = {item.paragraph_id: item for item in current.paragraphs}
        if len({item.paragraph_id for item in request.changes}) != len(request.changes):
            raise WritingProjectError("revision paragraph IDs must be unique")
        available_evidence = {item.evidence_id for item in base.evidence_refs}
        changes: list[RevisionChange] = []
        after: list[WritingParagraph] = []
        before: list[WritingParagraph] = []
        for item in request.changes:
            original = paragraphs.get(item.paragraph_id)
            if original is None:
                raise WritingProjectError(
                    f"revision targets unknown paragraph: {item.paragraph_id}"
                )
            unknown = set(item.evidence_ids) - available_evidence
            if unknown:
                raise WritingProjectError(
                    f"revision references unknown evidence: {sorted(unknown)}"
                )
            change = RevisionChange(
                paragraph_id=item.paragraph_id,
                before_hash=original.content_hash,
                replacement_markdown=item.replacement_markdown,
                rationale=item.rationale,
                evidence_ids=item.evidence_ids,
                category=item.category,
            )
            if change.category == "fact" and not change.evidence_ids:
                raise WritingProjectError("factual revision text requires evidence")
            changes.append(change)
            before.append(original)
            after.append(
                WritingParagraph(
                    paragraph_id=original.paragraph_id,
                    markdown=change.replacement_markdown,
                    content_hash=_hash_text(change.replacement_markdown),
                    evidence_ids=list(change.evidence_ids),
                )
            )
        digest = _hash_text(
            _json(
                {
                    "project_id": project_id,
                    "section_id": section_id,
                    "base_version": current.version,
                    "changes": [item.model_dump(mode="json") for item in changes],
                }
            )
        )
        evidence_ids = {item for change in changes for item in change.evidence_ids}
        revision = RevisionArtifact(
            artifact_id=f"revision:{digest[:24]}",
            producer_task_id="user-writing-preview",
            scope_ref=base.scope_ref,
            target_section_id=current.section_id,
            base_version=current.version,
            allowed_paragraph_ids=[item.paragraph_id for item in changes],
            changes=changes,
            content={"draft_only": True, "applied": False, "project_id": project_id},
            evidence_refs=[
                item for item in base.evidence_refs if item.evidence_id in evidence_ids
            ],
            lineage=[base.ref()],
            verification_status=VerificationStatus.PASSED,
            verification_report=VerificationReport(
                status=VerificationStatus.PASSED,
                checked_fields=["paragraph_scope", "before_hash", "claim_source_map"],
                source_ids=sorted(
                    {
                        item.source_id
                        for item in base.evidence_refs
                        if item.evidence_id in evidence_ids
                    }
                ),
                citation_count=len(evidence_ids),
            ),
        )
        stored = self._artifacts.put(revision)
        return WritingRevisionPreviewResponse(
            project_id=str(project_id),
            section_id=current.section_id,
            base_version=current.version,
            revision_ref=stored.ref(),
            before=before,
            after=after,
        )

    def export_markdown(self, project_id: str) -> WritingExportResponse:
        project = self.get(project_id)
        if project is None:
            raise WritingProjectError("Writing project not found")
        chunks = [f"# {project.title}"]
        if project.writing_goal:
            chunks.extend(["", f"> Writing goal: {project.writing_goal}"])
        if project.outline_ref is not None:
            outline = self._artifacts.get(project.outline_ref.artifact_id, project.outline_ref.version)
            if isinstance(outline, OutlineArtifact):
                chunks.extend(["", "## Outline"])
                chunks.extend(
                    f"- {item.title}: {item.objective}" for item in outline.sections
                )
        references: dict[str, ReferenceRecord] = {}
        for section in project.sections:
            chunks.extend(["", f"## {section.title or section.section_id}", "", section.markdown])
            for reference in section.references:
                existing = references.get(reference.source_id)
                if existing is None:
                    references[reference.source_id] = reference
                else:
                    references[reference.source_id] = existing.model_copy(
                        update={
                            "evidence_ids": sorted(
                                {*existing.evidence_ids, *reference.evidence_ids}
                            )
                        }
                    )
        if references:
            chunks.extend(["", "## Sources"])
            for index, reference in enumerate(references.values(), start=1):
                title = reference.title or f"Unknown title ({reference.source_id})"
                details = ", ".join(
                    item
                    for item in (
                        "; ".join(reference.authors),
                        reference.year,
                        reference.doi,
                    )
                    if item
                )
                chunks.append(f"{index}. {title}" + (f" — {details}" if details else ""))
        return WritingExportResponse(
            project_id=project.project_id,
            markdown="\n".join(chunks).strip() + "\n",
            references=list(references.values()),
            outline_version=project.outline_version,
            section_versions={item.section_id: item.version for item in project.sections},
        )


__all__ = [
    "WRITING_PROJECT_SCHEMA_VERSION",
    "WritingProjectConflictError",
    "WritingProjectError",
    "WritingProjectService",
]
