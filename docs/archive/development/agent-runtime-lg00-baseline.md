# LG00 Agent Runtime Baseline Lock

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

Date: 2026-09-27. Branch: `WebReBuild`. Baseline commit: `75fad6ed75ea794d2f0489e001bf5be4b3cfac83`. This replaces the taskbook's older planning baseline `4ffa8dbe86458c16bc23d3047c389dac4498d322` for this working tree.

## Installed contract

| Component | Observed version | Declared constraint |
| --- | --- | --- |
| Python | 3.11.15 | `langgraph.json`: 3.11 |
| LangGraph | 1.2.11 | `langgraph>=1.2,<1.3` |
| SQLite checkpoint | 3.1.1 | `langgraph-checkpoint-sqlite>=3,<4` |

The production factory is `backend/api/agent_dependencies.py:get_agent_runtime`. It constructs one `AgentRuntime` with `RootAgentGraph`. `langgraph.json` retains `reading_agent` as a Studio compatibility entry. The default migration engine is `typed`, and its rollout ceiling is `single`.

## Reproducible characterization

`tests/multi_agent/fixtures/lg00-baseline.json` captures a synthetic TaskPlan, terminal TaskResult, semantic event envelope and the checkpoint/resume expectation from `test_subgraph_checkpoint.py`. Time-dependent fields are omitted from the fixture. It contains no user document content. The checkpoint fixture records the established rule: completed task `a` stays at attempt 1, interrupted task `b` is retried at attempt 2, and the resumed executor only calls `b`.

Before the LG01 code change, the following existing contract suite passed: **83 passed, 1 warning, 11.55 seconds**. The warning is a Paramiko Blowfish deprecation warning.

```powershell
python -m pytest -q tests/multi_agent/test_parallel_scheduler.py tests/multi_agent/test_subgraph_checkpoint.py tests/multi_agent/test_result_reducer.py tests/multi_agent/test_plan_validation.py tests/multi_agent/test_supervisor_planner.py tests/multi_agent/test_root_orchestration_integration.py tests/multi_agent/test_temporary_workflow.py tests/multi_agent/test_task_events.py tests/multi_agent/test_memory_port_integration.py tests/multi_agent/test_memory_revocation_resume.py tests/multi_agent/test_cancellation_fencing.py tests/multi_agent/test_run_lease.py tests/multi_agent/test_commit_idempotency.py tests/multi_agent/test_migration_switch.py tests/agent/test_agent_checkpoint_persistence.py
```

## Migration switches and rollback

`AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT` is declared as a strict boolean with default `false`. LG00 only defines and validates this switch; it does not select a new execution path. `AITRANS_MULTI_AGENT_ENGINE=typed|legacy|off` and `AITRANS_MULTI_AGENT_ROLLOUT=simple|single|workflow` keep their existing semantics. To return to the baseline behavior during LG01, leave the native switch off and use the existing engine/rollout settings. The feature must not be advertised as an active native runtime before LG02–LG09 implementation and gates.

Acceptance of LG00 is limited to the deterministic baseline and the disabled switch. Real provider quality, manual UI behavior and full repository tests are outside this snapshot.

## 2026-09-28 clean-baseline recheck

The recheck used a managed clean worktree at `75fad6ed75ea794d2f0489e001bf5be4b3cfac83` and the existing `electronrebuild` working tree at `824236e00cfb44d4353558572331e4154de688d4`. Each pytest process used a separate temporary `AITRANS_DATA_ROOT`; no user databases were reset or reused. Python was 3.11.15, LangGraph 1.2.11, `langgraph-checkpoint-sqlite` 3.1.1, and pytest 9.0.3. The three migration switches were unset in the shell; their code defaults remain native `false`, engine `typed`, rollout `single`.

| Checkout | Command | Result |
| --- | --- | --- |
| Clean baseline | `python -m pytest -q tests/agent tests/multi_agent -m "not docker_integration" --tb=short` | 751 passed, 6 failed, 1 deselected; 2 warnings; 81.13 s |
| Working tree | `python -m pytest -q tests/agent tests/multi_agent -m "not docker_integration" --tb=short` | 759 passed, 6 failed, 1 deselected; 2 warnings; 77.66 s |
| Clean baseline | `python -m pytest -q tests/multi_agent/test_migration_switch.py tests/multi_agent/test_subgraph_checkpoint.py tests/agent/test_agent_checkpoint_persistence.py` | 20 passed; 8.73 s |
| Working tree | `python -m pytest -q tests/multi_agent/test_lg00_baseline_fixture.py tests/multi_agent/test_migration_switch.py tests/multi_agent/test_subgraph_checkpoint.py tests/agent/test_agent_checkpoint_persistence.py` | 23 passed; 6.77 s |
| Clean baseline and working tree | `python -m pytest -q tests/agent/test_python_execute_agent_integration.py -m docker_integration` | Each: 1 passed, 3 deselected; Docker Linux engine 29.8.0 and the pinned sandbox image were available |

All six non-Docker failures reproduce on the clean baseline, with identical first causes on the working tree:

1. `test_canvas_context_reaches_final_model_prompt_without_reading_mode` and `test_canvas_structure_query_uses_direct_answer_path` fail because `CompanionChatService._build_request()` rejects the Canvas-only `filesystem_workspace_files` argument. This belongs to the Canvas/companion-chat request contract and must be resolved in that workstream before the Stage 11 stable release gate; do not change it as part of Runtime migration.
2. `test_partially_verified_answer_is_preserved_with_notice`, `test_trailing_citation_preserves_multi_sentence_academic_paragraph`, `test_paragraph_level_one_in_three_citation_coverage_is_preserved`, and `test_answer_with_too_little_citation_coverage_still_falls_back` disagree with the grounded synthesis claim/citation-coverage expectations. This belongs to grounded synthesis/evidence-verifier semantics and must be resolved before the Stage 11 stable release gate; do not change RAG citation semantics as part of Runtime migration.

The current branch adds eight passing tests relative to the baseline; it adds no failures. The earlier Docker timeout was environmental and did not reproduce once Docker Desktop was running. The LG00 fixture is synthetic and stable: the plan/result contain no private document content, event timestamps are removed before comparison, and the resume contract keeps task `a` at attempt 1 while only interrupted task `b` is retried at attempt 2. The migration-switch suite confirms native remains opt-in and the old typed/legacy/off and simple/single/workflow behavior remains intact.

LG00 is **PASS for baseline classification**. The six deterministic baseline debts remain explicit pre-Stage-11 release gates; this status does not mean the full non-Docker suite is green. See [Stage 0 report](agent-runtime-stage-00-report.md) for the complete record.

## Stage 11 follow-up (2026-09-28)

The six recorded debts were subsequently fixed in the Canvas/companion-chat and grounded-synthesis/evidence-verifier workflows. Their historical Stage 0 baseline counts above are unchanged. The current full Stage 11 non-Docker Python suite passed **890 tests, 1 deselected**; see the [Stage 11 report](agent-runtime-stage-11-report.md) for the current release-gate status.
