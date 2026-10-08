from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path

from backend.models.markdown_export import MarkdownDocument

_FORMAT = r"(?:markdown|(?<![a-z0-9_])\.?md(?![a-z0-9_]))"
_ACTION = r"(?:导出|下载|保存|生成|export|download|save)"


def wants_markdown_export(message: str) -> bool:
    """Classify only the current user's command, never attached document text."""
    value = message.strip().casefold()
    if not re.search(_FORMAT, value) or not re.search(_ACTION, value):
        return False
    if re.search(
        r"(?:不要|不用|无需|不需要|别|不|do not|don't)\s*(?:再|自动)?\s*" + _ACTION,
        value,
    ):
        return False
    return not re.search(
        r"(?:如何|怎么|怎样|是否|能否|有没有|支持|how\s+(?:do|to)|can\s+(?:you|i))",
        value,
    )


def is_markdown_export_only(message: str) -> bool:
    if not wants_markdown_export(message):
        return False
    value = message.strip().casefold().strip("。.!！?？ ")
    if re.search(
        r"(?:翻译|总结|改写|润色|整理|撰写|写一|生成|translate|summari[sz]e|rewrite|polish|draft|create)",
        value,
    ):
        return False
    return bool(
        re.fullmatch(
            r"(?:请)?(?:帮我|麻烦|please\s+)?(?:把|将)?\s*"
            r"(?:(?:上面|上述|之前|刚才|最后|这|当前|上一条|全部|整个|整段|所有|本次)[\s\S]{0,16}?)?"
            r"(?:导出|下载|保存)(?:(?:全部|整个|整段|所有|当前|上面|刚才)(?:的)?(?:会话|对话|聊天|回答|内容))?(?:为|成|成一个|为一个)?\s*(?:一个)?\s*"
            r"(?:markdown|\.?md)\s*(?:格式的?)?\s*(?:文档|文件|格式)?"
            r"|(?:please\s+)?(?:export|download|save)\s+"
            r"(?:(?:the\s+)?(?:previous|last|above|current|whole|entire)\s+)?"
            r"(?:response|answer|content|conversation|chat|this|it)?\s*(?:as|to|in)?\s*"
            r"(?:markdown|\.?md)(?:\s+(?:document|file|format))?",
            value,
        )
    )


def export_scope(message: str) -> str:
    return (
        "conversation"
        if re.search(
            r"(?:全部|整个|整段|所有|whole|entire).*(?:会话|对话|聊天|conversation|chat)",
            message,
            re.IGNORECASE,
        )
        else "answer"
    )


def markdown_document(content: str, filename: str = "document.md") -> MarkdownDocument:
    markdown = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    fenced = re.fullmatch(
        r"```(?:markdown|md)\s*\n([\s\S]*)\n```", markdown, re.IGNORECASE
    )
    if fenced:
        markdown = fenced.group(1).strip()
    if not markdown:
        raise ValueError("没有可导出的 Markdown 内容。")
    # Export names are basenames, never paths supplied by the model.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(" .")
    name = (
        re.sub(r"\.md$", "", name, flags=re.IGNORECASE)[:100].strip(" .") or "document"
    )
    if re.fullmatch(
        r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name, re.IGNORECASE
    ):
        name = "_" + name
    return MarkdownDocument(filename=name + ".md", markdown=markdown + "\n")


def conversation_markdown(title: str, messages) -> MarkdownDocument:
    parts = ["# " + title.replace("\n", " ").replace("\r", " ").strip()]
    for message in messages:
        if (
            message.role not in {"user", "assistant"}
            or message.status != "complete"
            or not message.content.strip()
        ):
            continue
        parts.append("## " + ("用户" if message.role == "user" else "AITrans"))
        parts.append(message.content.strip())
    if len(parts) == 1:
        raise ValueError("会话中没有已完成的消息可供导出。")
    return markdown_document("\n\n".join(parts), title)


def run_markdown_document(state) -> MarkdownDocument | None:
    if (
        state.response.get("status") != "completed"
        or state.browser_context.get("plan_rejected")
        or not wants_markdown_export(state.user_input)
        or state.browser_context.get("task_completion", {}).get("status", "completed") != "completed"
    ):
        return None
    exported = next(
        (
            result.get("data")
            for result in reversed(state.tool_results)
            if result.get("tool_name") == "export_markdown_document"
            and isinstance(result.get("data"), dict)
            and result["data"].get("markdown")
        ),
        None,
    )
    body = (
        exported["markdown"]
        if exported
        else str(state.response.get("output_text", "") or "")
    )
    if not body.strip():
        return None
    return markdown_document(
        body, exported.get("filename", "document.md") if exported else "document.md"
    )


def _connect(storage_path: str | Path):
    connection = sqlite3.connect(storage_path, timeout=5)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS conversation_markdown_exports (message_id TEXT PRIMARY KEY REFERENCES messages(message_id) ON DELETE CASCADE, document_json TEXT NOT NULL)"
    )
    return connection


def save_markdown_export(
    storage_path, message_id: str, document: MarkdownDocument
) -> None:
    with closing(_connect(storage_path)) as connection, connection:
        connection.execute(
            "INSERT INTO conversation_markdown_exports VALUES (?, ?) ON CONFLICT(message_id) DO UPDATE SET document_json=excluded.document_json",
            (message_id, document.model_dump_json()),
        )


def load_markdown_export(storage_path, message_id: str) -> MarkdownDocument | None:
    with closing(_connect(storage_path)) as connection, connection:
        row = connection.execute(
            "SELECT document_json FROM conversation_markdown_exports WHERE message_id=?",
            (message_id,),
        ).fetchone()
    return MarkdownDocument.model_validate_json(row[0]) if row else None
