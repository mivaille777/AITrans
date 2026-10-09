"""Independent, deterministic checks of actual tool outputs and persisted effects.

Checks consume authoritative adapters, never executable assertions from the model.
An unsupported effect is unknown rather than a fabricated verification pass.
"""
from dataclasses import replace
from hashlib import sha256
from pathlib import PurePath

from backend.agent_tools.base import AgentToolExecutionResult


def acceptance_criteria_for(name, effect="read"):
    criteria = {
        "read_workspace_file": ["文件在授权工作区内，回读正文与请求分页一致；全文请求需连续覆盖全部正文。"],
        "python_execute": ["实际执行结束，退出码为 0，未超时或触发资源限制。"],
        "command_execute": ["实际执行结束，退出码为 0，未超时或触发资源限制。"],
        "export_markdown_document": ["生成非空 UTF-8 Markdown 文档，文件名和正文通过检查。"],
        "save_research_note": ["研究笔记已持久化，可回查且写入正文一致。"],
        "update_research_note": ["目标研究笔记存在，回查更新正文一致。"],
        "save_knowledge_card": ["知识卡、来源关系和写入正文可回查且一致。"],
        "search_knowledge_base": ["候选来源在授权范围内；搜索命中本身不代表任务完成。"],
        "read_knowledge_chunk": ["实际片段与请求位置、授权范围及引用证据一致。"],
        "read_knowledge_section": ["实际章节片段与请求位置、授权范围及引用证据一致。"],
    }
    return criteria.get(name, ["实际写入效果可回查；缺少回查时结果待核对。"] if effect == "write" else ["返回内容通过结构检查；内容质量另行核验。"])


class ToolResultValidator:
    def __init__(self, *, filesystem=None, research=None, library=None, workspace=None, chunks=None):
        self.filesystem = filesystem
        self.research = research
        self.library = library
        self.workspace = workspace
        self.chunks = chunks

    def verify(self, name, payload, result: AgentToolExecutionResult):
        data = result.data or {}
        checks = []

        def check(code, ok, detail, *, evidence=None):
            checks.append({"code": code, "status": "passed" if ok else "failed",
                           "detail": detail, "evidence": evidence or {}})

        if name == "export_markdown_document":
            body = data.get("markdown", "")
            filename = data.get("filename", "")
            check("markdown_document", bool(body.strip()) and filename.endswith(".md")
                  and PurePath(filename).name == filename and "/" not in filename
                  and "\\" not in filename
                  and data.get("mime_type") == "text/markdown;charset=utf-8",
                  "已检查 Markdown 内容、文件名及 UTF-8 下载格式。",
                  evidence={"filename": filename, "sha256": sha256(body.encode("utf-8")).hexdigest(),
                            "delivery_state": "generated"})
            expected = payload.get("markdown") or payload.get("ai_content") or payload.get("source_text")
            if expected:
                from backend.services.markdown_export_service import markdown_document
                check("markdown_content", body == markdown_document(str(expected), filename).markdown, "导出内容与请求正文一致。")
        elif name in {"create_workspace_file", "edit_workspace_file", "write_workspace_file", "create_workspace_directory", "undo_workspace_change"}:
            service = getattr(self, "workspace_files", None)
            if service is None:
                checks.append({"code": "workspace_adapter", "status": "unknown", "detail": "文件回读服务不可用。"})
            else:
                from backend.services.workspace_file_service import WorkspaceFileError
                valid = True
                try:
                    service.verify(payload.get("filesystem_workspace_id", ""), data)
                except WorkspaceFileError:
                    valid = False
                check("file_effect_readback", valid and data.get("workspace_id") == payload.get("filesystem_workspace_id"),
                      "已核对本地文件实际内容、大小与工作区。",
                      evidence={key: data.get(key) for key in ("relative_path", "sha256", "size_bytes", "change_id")})
                if name in {"create_workspace_file", "write_workspace_file"}:
                    encoding = "utf-8" if name == "create_workspace_file" else service.read(data["workspace_id"], data["relative_path"])["encoding"]
                    check("exact_file_content", data["sha256"] == sha256(payload["content"].encode(encoding)).hexdigest(), "文件内容与请求写入内容逐字节一致。")
        elif name == "read_workspace_text":
            service = getattr(self, "workspace_files", None)
            if service is None:
                checks.append({"code": "workspace_adapter", "status": "unknown", "detail": "文件回读服务不可用。"})
            else:
                actual = service.read(payload["filesystem_workspace_id"], payload["relative_path"], payload.get("start_line", 1), payload.get("max_lines", 200))
                check("exact_text_readback", actual == data, "已核对原始文本及文件版本。")
        elif name == "read_workspace_file":
            if not self.filesystem:
                checks.append({"code": "workspace_adapter", "status": "unknown", "detail": "文件回读适配器不可用。"})
            else:
                filesystem = self.filesystem() if callable(self.filesystem) else self.filesystem
                actual = filesystem.read_file(payload.get("filesystem_workspace_id", ""),
                    payload["relative_path"], payload.get("offset", 0), payload.get("limit", 8000))
                check("workspace_readback", {**actual, "text": actual["text"].strip()} == data, "已在授权工作区回读并核对文件内容与分页范围。",
                      evidence={"relative_path": payload["relative_path"], "offset": data.get("offset"),
                                "has_more": data.get("has_more"),
                                "sha256": sha256(str(data.get("text", "")).encode()).hexdigest()})
        elif name in {"python_execute", "command_execute"}:
            check("process_exit", data.get("exit_code") == 0 and not any(data.get(key) for key in
                  ("timed_out", "oom_killed", "output_limit_exceeded"))
                  and data.get("status") not in {"failed", "cancelled", "timed_out", "blocked", "approval_required", "denied", "storage_limit_exceeded"},
                  "核对沙箱退出码、超时、内存和输出限制。",
                  evidence={key: data.get(key) for key in ("sandbox_id", "status", "exit_code", "timed_out")})
        elif name in {"read_knowledge_chunk", "read_knowledge_section", "search_knowledge_base"}:
            items = data.get("chunks", []) if name.startswith("read_") else data.get("results", [])
            allowed = set(payload.get("knowledge_document_ids") or [])
            global_allowed = bool(payload.get("knowledge_scope_allow_global", False))
            check("source_scope", all(item.get("document_id") and (item["document_id"] in allowed or (not allowed and global_allowed))
                  for item in items), "核对检索结果所属文档范围。")
            if name.startswith("read_"):
                check("read_location", any(item.get("chunk_id") == payload.get("chunk_id") for item in items),
                      "核对实际读取的片段与请求位置。")
                if self.chunks and checks[0]["status"] == "passed":
                    actual = [self.chunks.get_chunk(item["chunk_id"]) for item in items]
                    check("chunk_readback", all(chunk is not None and chunk.document_id == item["document_id"]
                        and chunk.text.strip() == item["text"].strip() for chunk, item in zip(actual, items)),
                        "从片段存储回读，核对来源与正文。")
            evidence = data.get("evidence", [])
            ids = {item.get("evidence_id") for item in evidence}
            check("citation_links", all(set(item.get("evidence_ids", [])) <= ids for item in data.get("citations", [])),
                  "核对引用与证据的关联；搜索候选本身不代表任务已完成。")
            if evidence or data.get("citations"):
                from backend.models.agent_runtime import AgentEvidenceItem, AgentCitationRef
                from backend.rag.citation_service import CitationService
                CitationService().validate([AgentCitationRef.model_validate(item) for item in data.get("citations", [])],
                    [AgentEvidenceItem.model_validate(item) for item in evidence])
        elif name in {"save_research_note", "update_research_note"} and self.research:
            note_id = data.get("note_id") or (data.get("note") or {}).get("note_id") or payload.get("note_id")
            note = self.research.get(note_id) if note_id else None
            check("note_readback", note is not None, "回查已持久化的研究笔记。", evidence={"note_id": note_id})
            if note is not None:
                for key in ("user_note", "ai_content"):
                    if key in payload:
                        check(f"note_{key}", getattr(note, key, None) == payload[key], "核对笔记写入内容。")
        elif name == "save_knowledge_card" and self.workspace:
            card = self.workspace.get_item(data.get("item_id", ""))
            relation = self.workspace.get_relation(data.get("relation_id", ""))
            source_id = data.get("source_item_id", "")
            check("knowledge_readback", card is not None and relation is not None
                  and relation.source_item_id == data.get("item_id") and relation.target_item_id == source_id,
                  "回查知识卡片及其来源关系。", evidence={"item_id": data.get("item_id"), "relation_id": data.get("relation_id")})
            if card is not None:
                expected = str(payload.get("ai_content") or payload.get("translated_text") or payload.get("source_text") or "").strip()[:50000]
                check("knowledge_content", card.summary == expected and card.metadata.get("source_item_id") == source_id,
                      "核对知识卡内容与来源。")
        elif result.effect == "write":
            checks.append({"code": "effect_readback", "status": "unknown",
                           "detail": "此写入工具尚无可用回查，不能确认实际效果。"})
        else:
            check("typed_output", True, "工具输出已通过工具定义的结构校验。")
            if not data:
                check("nonempty_output", bool(result.output_text.strip()), "核对工具是否返回内容。")

        statuses = {item["status"] for item in checks}
        status = "failed" if "failed" in statuses else "unknown" if "unknown" in statuses else "passed"
        report = {"status": status, "checks": checks,
                  "scope": "deterministic_result", "semantic_quality": "not_assessed"}
        return replace(result, verification=report,
                       status="failed" if status == "failed" else "unknown" if status == "unknown" else "success",
                       error_code="result_verification_failed" if status == "failed" else "")
