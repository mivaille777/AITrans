"""Task acceptance is independent of the lifecycle's 'finished' state."""
import re
from backend.services.tool_capability_router import requested_capabilities


def verify_task_completion(state):
    items = []

    def add(key, label, status, *, evidence=None):
        items.append({"criterion_id": key, "label": label, "status": status,
                      "required": True, "evidence": evidence or {}})

    if state.browser_context.get("plan_rejected"):
        return {"status": "cancelled", "passed": 0, "total": 0, "criteria": [], "reason": "计划已取消。"}
    if state.response.get("status") == "confirmation_required":
        return {"status": "pending", "passed": 0, "total": 0, "criteria": [], "reason": "等待用户确认。"}
    results = state.tool_results
    assigned = set()
    for step in state.plan.steps:
        matches = [result for result in results if result.get("step_id") == step.step_id]
        if not matches and state.plan.mode == "single_step":
            matches = [result for result in results if result.get("tool_name") == step.tool_name]
        result = matches[-1] if matches else None
        if result is not None:
            assigned.add(id(result))
        status = (result.get("verification") or {}).get("status", "unknown") if result else "failed"
        add(f"step:{step.step_id}", f"{step.tool_name} 结果验证", status,
            evidence={"tool_call_id": (result or {}).get("tool_call_id", ""), "step_id": step.step_id})
    planned = {step.step_id for step in state.plan.steps}
    for index, result in enumerate(results):
        if result.get("step_id") in planned or id(result) in assigned:
            continue
        status = (result.get("verification") or {}).get("status", "unknown")
        add(f"call:{result.get('tool_call_id') or index}", f"{result.get('tool_name', '工具')} 结果验证", status,
            evidence={"tool_call_id": result.get("tool_call_id", "")})

    from backend.services.markdown_export_service import run_markdown_document
    from backend.agent_tools.base import AgentToolExecutionResult
    from backend.services.tool_result_validator import ToolResultValidator
    capabilities = requested_capabilities(state.user_input)
    if "export" in capabilities:
        document = state.browser_context.get("markdown_export") or run_markdown_document(state)
        if document:
            data = document.model_dump() if hasattr(document, "model_dump") else document
            report = ToolResultValidator().verify("export_markdown_document", {},
                AgentToolExecutionResult(tool_name="export_markdown_document", output_text=data["markdown"], effect="compute", data=data))
            add("markdown_deliverable", "Markdown 文档已生成并可下载", report.verification["status"],
                evidence=report.verification["checks"][0]["evidence"])
        else:
            add("markdown_deliverable", "Markdown 文档已生成并可下载", "failed")
    if "compute" in capabilities:
        executions = [result for result in results if result.get("tool_name") in {"python_execute", "command_execute"}]
        add("process_requested", "请求的计算／命令已实际执行", "passed" if executions else "failed")
    if "writeback" in capabilities:
        add("write_requested", "请求的保存／更新已实际执行", "passed" if any(result.get("effect") == "write" for result in results) else "failed")
    if "reading" in capabilities and state.browser_context.get("filesystem_workspace_id") and any(word in state.user_input for word in ("工作区", "文件", "workspace", "file")):
        add("file_read_requested", "工作区文件已实际读取", "passed" if any(result.get("tool_name") == "read_workspace_file" for result in results) else "failed")
        if re.search(r"全文|完整|全部|whole|entire|complete file", state.user_input, re.I):
            pages = {}
            for result in results:
                if result.get("tool_name") == "read_workspace_file" and (result.get("verification") or {}).get("status") == "passed":
                    data = result.get("data") or {}
                    pages.setdefault(data.get("relative_path", ""), []).append(data)
            for path, ranges in pages.items():
                end = 0
                total = max(item["total_chars"] for item in ranges)
                for item in sorted(ranges, key=lambda item: item["offset"]):
                    if item["offset"] > end:
                        break
                    end = max(end, item["next_offset"])
                add(f"file_coverage:{path}", f"{path} 全文读取覆盖", "passed" if end == total else "failed",
                    evidence={"covered_chars": end, "total_chars": total})
    # Preserve the authoritative research workflow's existing acceptance gate.
    workflow_status = state.orchestration_status
    if workflow_status in {"partial", "failed", "blocked"}:
        add("research_acceptance", "研究任务验收", "failed")
    research_results = {item["task_id"]: item for item in state.orchestration_results}
    for task in state.orchestration_plan.get("tasks", []):
        if not task.get("required", True):
            continue
        result = research_results.get(task["task_id"], {})
        add(f"research:{task['task_id']}", task.get("objective", "研究任务验收"),
            "passed" if result.get("status") == "succeeded" and not result.get("unmet_requirements") else "failed",
            evidence={"task_id": task["task_id"], "artifact_refs": result.get("artifact_refs", [])})
    if state.react.status == "limit_reached":
        add("runtime_budget", "任务在执行预算内完成", "failed")
    if state.evidence_sufficiency is not None and not state.evidence_sufficiency.sufficient and not state.evidence:
        add("document_evidence", "请求的文档证据充分", "failed",
            evidence={"reason": state.evidence_sufficiency.reason})
    add("response", "已生成回应内容", "passed" if state.response.get("output_text", "").strip() else "failed")
    passed = sum(item["status"] == "passed" for item in items)
    states = {item["status"] for item in items}
    status = "unknown" if "unknown" in states else "partial" if "failed" in states and passed else "failed" if "failed" in states else "completed"
    return {"status": status, "passed": passed, "total": len(items), "criteria": items,
            "semantic_quality": "not_assessed", "reason": "所有必要检查通过。" if status == "completed" else "有必要目标未通过验收或缺少执行证据。"}


def apply_task_completion(state):
    report = verify_task_completion(state)
    state.browser_context["task_completion"] = report
    if report["status"] in {"partial", "failed", "unknown"}:
        unresolved = [item["label"] for item in report["criteria"] if item["status"] != "passed"]
        # A generated conclusion must not contradict a failed deterministic check.
        receipt = "\n".join(f"- {item}" for item in unresolved)
        successful = [result for result in state.tool_results if (result.get("verification") or {}).get("status") == "passed"]
        content = "\n\n".join(str(result.get("output_text", ""))[:4000] for result in successful[-3:])
        if any(item["criterion_id"] == "document_evidence" and item["status"] != "passed" for item in report["criteria"]):
            receipt += "\n文档证据未通过验收，无法可靠回答需要来源支持的问题。"
        state.apply_response({**state.response, "output_text": f"任务验收：{'结果待核对' if report['status'] == 'unknown' else '部分完成' if report['status'] == 'partial' else '未通过'}。\n{receipt}" + (f"\n\n已取得的结果：\n{content}" if content else "")})
    return report
