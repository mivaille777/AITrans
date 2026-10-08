"""File action hints come only from the current user's request, never documents."""
import re


def file_intent(message):
    text = str(message or "").strip()
    if re.search(r"^(?:请问)?(?:如何|怎么|怎样|是否|能否|有没有|支持|你能|你可以)|^(?:how\b|can\s+(?:you|i)\b)", text, re.I):
        return ""
    if re.search(r"^(?:请)?(?:帮我)?(?:解释|说明).*(?:如何|怎么|命令|流程|意思)|^explain\b.*\b(?:how|command|meaning)\b", text, re.I):
        return ""
    # Literal file content and quoted examples cannot grant write access.
    actionable = re.split(r"(?:内容(?:为|是|：|:)|里面(?:只)?写|content\s*[:=])", text, maxsplit=1, flags=re.I)[0]
    actionable = re.sub(r"[‘'\"“「][^‘'\"”」]*[’'\"”」]", "", actionable)
    actionable = re.sub(r"(?:不要|不用|无需|别|do not|don't)\s*[^，。；;\n]*", "", actionable, flags=re.I)
    if not re.search(r"文件|文档|文件夹|目录|工作区|folder|directory|workspace|file|\.[a-z0-9]{1,8}\b", actionable, re.I):
        return ""
    if re.search(r"撤销|恢复.*变更|\bundo\b", actionable, re.I):
        return "undo"
    if re.search(r"新建|创建|保存|写入|修改|编辑|替换|覆盖|重写|追加|\b(?:create|save|write|edit|replace|overwrite|append)\b", actionable, re.I):
        if not re.search(r"新建|创建|修改|编辑|替换|覆盖|重写|追加|\b(?:create|edit|replace|overwrite|append)\b|[\w-]+\.[a-z0-9]{1,8}\b|文件夹|目录|工作区|本地|folder|directory|workspace|local", actionable, re.I):
            return ""
        return "write"
    if re.search(r"浏览|列出|查看|读取|阅读|搜索|查找|\b(?:list|browse|read|search|find)\b", actionable, re.I):
        return "read"
    return ""


def explicit_new_file_request(message, relative_path):
    if file_intent(message) != "write":
        return False
    text = re.split(r"(?:内容(?:为|是|：|:)|里面(?:只)?写|content\s*[:=])", str(message), maxsplit=1, flags=re.I)[0]
    return bool(re.search(r"新建|创建|\bcreate\b", text, re.I) and relative_path in text)
