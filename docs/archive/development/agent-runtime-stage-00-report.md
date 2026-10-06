# Agent Runtime Stage 0 Report

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

Status: **PASS — baseline classification complete**  
Date: 2026-09-28  
Working-tree HEAD: `824236e00cfb44d4353558572331e4154de688d4`  
Clean baseline: `75fad6ed75ea794d2f0489e001bf5be4b3cfac83`

## Environment and switches

- Python 3.11.15; LangGraph 1.2.11; `langgraph-checkpoint-sqlite` 3.1.1; pytest 9.0.3.
- `AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT`, `AITRANS_MULTI_AGENT_ENGINE`, and `AITRANS_MULTI_AGENT_ROLLOUT` were unset in the shell. Defaults remain `false`, `typed`, and `single`.
- The clean baseline was checked in a separate Codex-managed worktree. Each suite run received its own temporary `AITRANS_DATA_ROOT`; existing databases and workspace files were preserved.

## Baseline comparison

| Checkout | Non-Docker suite | Focused contracts | Docker integration |
| --- | --- | --- | --- |
| Clean baseline | 751 passed, 6 failed, 1 deselected; 2 warnings; 81.13 s | 20 passed; 8.73 s | 1 passed, 3 deselected; 1 warning |
| Working tree | 759 passed, 6 failed, 1 deselected; 2 warnings; 77.66 s | 23 passed; 6.77 s | 1 passed, 3 deselected; 1 warning |

Commands:

```powershell
python -m pytest -q tests/agent tests/multi_agent -m "not docker_integration" --tb=short
python -m pytest -q tests/multi_agent/test_migration_switch.py tests/multi_agent/test_subgraph_checkpoint.py tests/agent/test_agent_checkpoint_persistence.py
python -m pytest -q tests/agent/test_python_execute_agent_integration.py -m docker_integration
```

The working-tree focused command also included `tests/multi_agent/test_lg00_baseline_fixture.py`, which does not exist at the clean baseline commit. Its total of 23 passes therefore includes the new fixture contract.

## Reproduced baseline debts

The same six failures and first causes occur at the clean baseline and the working tree:

| Tests | First cause | Ownership and resolution point |
| --- | --- | --- |
| `test_canvas_context_reaches_final_model_prompt_without_reading_mode`; `test_canvas_structure_query_uses_direct_answer_path` | `_build_request()` rejects unexpected `filesystem_workspace_files` | Canvas/companion-chat request contract; resolve in that workstream before Stage 11 stable release. |
| `test_partially_verified_answer_is_preserved_with_notice`; `test_trailing_citation_preserves_multi_sentence_academic_paragraph`; `test_paragraph_level_one_in_three_citation_coverage_is_preserved`; `test_answer_with_too_little_citation_coverage_still_falls_back` | Grounded-synthesis citation coverage and claim attribution differ from the test contract | Grounded synthesis/evidence verifier; resolve before Stage 11 stable release. Do not alter citation semantics in Runtime migration. |

No Runtime-specific regression was introduced. Eight additional working-tree tests pass relative to the baseline. The formerly reported Docker daemon timeout did not reproduce: Docker Desktop exposed Linux engine 29.8.0 and the pinned sandbox image, and the marked Python integration test passed on both checkouts.

## Fixture and compatibility review

`tests/multi_agent/fixtures/lg00-baseline.json` contains a synthetic two-task plan/result and a stable semantic-event envelope. It omits timestamp fields during comparison, uses deterministic identifiers, and contains no user document content. The checkpoint expectation preserves completed task `a` at attempt 1 and resumes only interrupted task `b` at attempt 2. The fixture contract test passes on the working tree.

The migration tests confirm `AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT` defaults to `false`; the existing `typed|legacy|off` engine and `simple|single|workflow` rollout defaults/behavior remain unchanged. No production code or user database was changed for Stage 0.

## Gate and follow-up

Stage 0 passes its classification gate: clean baseline and working-tree failures match, there are no added failures, the six deterministic debts have evidence and owners, and Docker was tested separately. The six debts remain release gates and prevent marking the overall full suite green. Recheck them before the Stage 11 stable rollout.

Rollback for this stage is limited to reverting this report and the corresponding baseline/taskbook documentation updates. There were no Stage 0 code or database changes.

Manual Electron acceptance is recorded separately: the app started and health passed, but the Sandbox Debug page reports `sandbox_disabled`; do not enable that security setting as part of this stage.

## Stage 11 resolution follow-up (2026-09-28)

The six deterministic failures above were resolved in their owning workflows, without changing the Stage 0 baseline result. Canvas/companion chat now accepts a bounded, relative-path-only `filesystem_workspace_files` manifest and passes it as reference metadata to the final chat prompt. Grounded synthesis now counts only citations attached to individual claims in strict sentence metrics, while retaining its separate paragraph-level partial-release rule. The verifier contract test was updated to express that distinction.

The focused Canvas and grounded-synthesis suite passed **24 tests**. The full non-Docker Stage 11 Python suite passed **890 tests, 1 deselected**. The historical clean-baseline failures remain documented above; they are no longer open Stage 11 release debts in the current working tree.
