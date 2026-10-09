"""Bounded capability hints, intersected with server-owned availability.

Unknown language retains the available catalog for the existing semantic planner.
This router never grants permissions or reads instructions from attached content.
"""
import re


CAPABILITY_TOOLS = {
    "filesystem": {"list_workspace_files", "search_workspace_text", "read_workspace_text", "read_workspace_file",
                   "create_workspace_file", "edit_workspace_file", "write_workspace_file", "create_workspace_directory", "undo_workspace_change"},
    "reading": {"read_workspace_file", "inspect_reading_context", "explain_selection", "summarize_selection",
                "analyze_section_role", "define_terms", "analyze_equation", "summarize_current_section"},
    "translation": {"translate_selection", "polish_selection"},
    "knowledge": {"list_knowledge_documents", "search_knowledge_base", "read_knowledge_chunk", "read_knowledge_section"},
    "research": {"list_research_notes", "search_research_notes", "get_research_note", "save_research_note", "update_research_note"},
    "compute": {"python_execute", "command_execute"},
    "export": {"export_markdown_document"},
    "writeback": {"save_knowledge_card", "save_research_note", "update_research_note"},
}


def requested_capabilities(user_message):
    from backend.services.markdown_export_service import wants_markdown_export
    message = str(user_message or "")
    if re.search(r"^(?:请问)?(?:如何|怎么|怎样|是否|能否|有没有|支持)|^(?:how\b|can\s+(?:you|i)\b)", message.strip(), re.I):
        return set()
    # Quoted words, questions about capabilities and negated actions are not
    # execution requirements. Existing semantic routing handles ambiguity.
    actionable = re.sub(r"[‘'\"“「][^‘'\"”」]*[’'\"”」]", "", message)
    actionable = re.sub(r"(?:不要|不用|无需|别|do not|don't)\s*[^，。；;\n]*", "", actionable, flags=re.I)
    capabilities = set()
    from backend.services.script_plot_intent import wants_plot_execution
    if wants_plot_execution(message):
        capabilities.add("compute")
    from backend.services.workspace_file_intent import file_intent
    file_action = file_intent(message)
    if file_action:
        capabilities.add("filesystem")
    if re.search(r"阅读|读取|解释|总结|概括|分析|\bread\b|summari[sz]e|explain", actionable, re.I): capabilities.add("reading")
    if re.search(r"翻译|润色|translate|polish", actionable, re.I): capabilities.update({"translation", "reading"})
    if re.search(r"知识库|资料库|本地文档|knowledge|检索|查找|出处|引用|论文", actionable, re.I): capabilities.add("knowledge")
    if re.search(r"研究笔记|research note", actionable, re.I): capabilities.add("research")
    if re.search(r"运行|执行.*(?:代码|程序|命令)|计算|python|测试|\brun\b|compute", actionable, re.I): capabilities.add("compute")
    if wants_markdown_export(message) and file_action not in {"write", "undo"}: capabilities.add("export")
    if re.search(r"(?:保存|写入|更新).*(?:笔记|知识卡)|save.*(?:note|knowledge card)", actionable, re.I): capabilities.add("writeback")
    return capabilities


def filter_capabilities(tools, message, *, primitive_name=lambda name: name):
    capabilities = requested_capabilities(message)
    if not capabilities:
        return tuple(tools)
    # Reading often needs indexed documents; export may follow a generation.
    if "reading" in capabilities: capabilities.add("knowledge")
    allowed = set().union(*(CAPABILITY_TOOLS[capability] for capability in capabilities))
    return tuple(tool for tool in tools if primitive_name(tool.name) in allowed
                 or tool.category in capabilities)
