# AITrans Agent Runtime v1 验收报告

## 1. 基本信息

| Item | Value |
|---|---|
| Validated implementation commit | `934f3e611fd37bc834372fbd240eeb3588e50547` |
| Branch | `WebReBuild` |
| GitHub Actions run | `35694123313` |
| CI result | **SUCCESS** |
| Python | 3.11.9 (primary), 3.12 compatibility |
| LangGraph | 1.2.12 in validation environment |
| LangGraph checkpoint SQLite | 3.1.1 in validation environment |
| OS | GitHub Actions `windows-latest` |
| Test date | 2026-09-22 |
| Runtime profile used by long-task acceptance | `long_task` |

This report records the Stage 8 release-acceptance evidence for Agent Runtime v1. The validated CI run completed with all required jobs green: Python 3.11, Python 3.12 compatibility, Python quality, Agent Runtime v1 acceptance, React lint/tests/build, Tauri shell build, and the aggregate CI quality gate.

## 2. P0-1 Runtime

| ID | Test | Expected | Actual | Evidence | Result |
|---|---|---|---|---|---|
| RT-C01 | Run state transition | Invalid transition rejected | Invalid transitions are rejected by the runtime contract | `tests/agent/test_runtime_contract.py::test_rt_c01_run_status_allows_only_declared_transitions` | PASS |
| RT-S02 | SQLite restart | Run persists | Run survives store close/reopen with identity and status intact | `tests/agent/test_agent_run_store.py::test_rt_s02_run_survives_reopened_store` | PASS |
| RT-S04 | concurrent claim | Exactly one owner | 100 concurrent claims produce exactly one owner | `tests/agent/test_agent_run_store.py::test_rt_s04_one_hundred_concurrent_claims_have_exactly_one_owner` | PASS |
| RT-W03 | worker crash | Lease expires | Expired lease is detected and stale worker ownership is removed | `tests/agent/test_agent_runtime_scheduler.py::test_rt_w03_w04_expired_lease_can_be_reclaimed` | PASS |
| RT-W04 | reclaim | Second worker resumes | Replacement worker reclaims the run as recovery work | `tests/agent/test_agent_runtime_scheduler.py::test_rt_w03_w04_expired_lease_can_be_reclaimed` | PASS |
| RT-G03 | multi-step | All steps complete | Bounded multi-step graph executes and retains plan state | `tests/agent/test_multi_step_graph.py` | PASS |

### P0-1 acceptance

**P0-1 Runtime = PASS**

Additional process-level concurrency evidence: `tests/integration/test_agent_runtime_concurrency.py::test_multiple_process_workers_execute_one_run_exactly_once` starts eight Python worker processes against the same SQLite Runtime Store and verifies one physical execution only.

## 3. P0-2 Checkpoint / Resume / Crash Recovery

| ID | Test | Expected | Actual | Evidence | Result |
|---|---|---|---|---|---|
| CP-R01 | planner/route resume | Completed routing work is not repeated | Resume continues after the durable boundary without repeating the completed route stage | `tests/agent/test_agent_pause_resume.py::test_cp_r01_pause_after_route_resumes_without_repeating_route` | PASS |
| CP-R02 | retrieval resume | Completed retrieval is not repeated | Resume does not replay the completed read Tool | `tests/agent/test_agent_pause_resume.py::test_cp_r02_pause_after_retrieval_does_not_repeat_read_tool` | PASS |
| CP-R03 | completed resume | Zero execution | Reopening/resuming a completed checkpoint is idempotent | `tests/agent/test_agent_checkpoint_persistence.py::test_resuming_completed_checkpoint_is_idempotent_after_reopen` | PASS |
| CP-01 | checkpoint isolation | Runs do not share checkpoints | Checkpoint state is scoped by Run ID | `tests/agent/test_agent_checkpoint_persistence.py::test_cp01_checkpoints_are_scoped_to_their_run_id` | PASS |
| CP-02 / CP-03 | unsupported versions | Reject unknown/future checkpoint versions | Unsupported checkpoint versions are rejected instead of silently recovered | `tests/agent/test_agent_checkpoint_persistence.py::test_cp02_cp03_unsupported_checkpoint_versions_are_rejected` | PASS |
| CP-04 | legacy migration | Explicit migration | Legacy checkpoint loads only through the explicit migration path | `tests/agent/test_agent_checkpoint_persistence.py::test_cp04_legacy_checkpoint_loads_through_explicit_migration` | PASS |
| CP-Crash | real process restart | Run recovers | Process A exits during execution; Process B reopens DB, marks RECOVERING, resumes, and completes with the same run_id/trace_id | `tests/integration/test_agent_crash_recovery.py::test_crashed_process_reclaims_without_repeating_checkpointed_node` | PASS |
| CP-W01 | write crash | One physical write | Physical write occurs once even when the process exits before Tool result persistence | `tests/integration/test_agent_write_crash_recovery.py::test_write_side_effect_is_not_replayed_after_real_process_crash` | PASS |
| CP-W02 | uncertain write | No automatic replay | Recovered RUNNING write becomes `BLOCKED_RECOVERY`; second physical write is rejected | same integration test + `tests/agent/test_agent_write_recovery.py` | PASS |
| CP-W03 | read crash | Safe retry | Recovered read ToolCall can return to pending/retry path | `tests/agent/test_agent_write_recovery.py::test_cp_w03_read_call_can_be_retried_after_reclaim` | PASS |

### P0-2 acceptance

**P0-2 Checkpoint / Recovery = PASS**

Observed crash-recovery invariants in the process-level acceptance test:

- completed checkpointed node re-execution: **0**
- run_id changes: **0**
- trace_id changes: **0**
- stale RUNNING run transitions to RECOVERING: **verified**
- final terminal status: **COMPLETED**

## 4. P0-3 Tool Runtime

| ID | Test | Expected | Actual | Evidence | Result |
|---|---|---|---|---|---|
| TL-T01 | read timeout | Timed-out read is not success | Timeout is persisted as non-success | `tests/agent/test_agent_tool_execution.py::test_timed_out_read_is_not_recorded_as_success` | PASS |
| TL-RT01 | transient retry | Safe read eventually succeeds | Read/compute path retries transient failure only | `tests/agent/test_agent_tool_execution.py::test_read_retries_transient_failure_only` | PASS |
| TL-RT03 | write retry | One write attempt | Failed write is persisted and never automatically replayed | `tests/agent/test_agent_tool_execution.py::test_failed_write_is_recorded_and_never_replayed` | PASS |
| TL-ID01 | duplicate write | One physical write | 100 concurrent callers share one idempotent write claim | `tests/agent/test_agent_tool_execution.py::test_write_is_claimed_once_by_100_concurrent_callers` | PASS |
| TL-PAR01 | parallel read | Concurrent execution | Independent reads execute in parallel | `tests/agent/test_agent_tool_execution.py::test_independent_reads_parallelize_but_dependencies_and_resources_serialize` | PASS |
| TL-PAR03 | write parallel | Prohibited/serialized | Dependencies, exclusive resources and unsafe writes do not execute concurrently | same parallel execution test | PASS |
| Write confirmation | unconfirmed write | Reject before side effect | Physical executor is not entered without confirmation | `tests/agent/test_agent_tool_execution.py::test_unconfirmed_write_is_rejected_before_physical_execution` | PASS |

### P0-3 acceptance

**P0-3 Tool Runtime = PASS**

## 5. Regression

Validated by GitHub Actions run `35694123313`.

| Suite / Gate | Result | Evidence |
|---|---|---|
| `tests/agent` | **478 passed, 0 failed** | Agent Runtime v1 acceptance job |
| `tests/multi_agent` | **197 passed, 0 failed** | Agent Runtime v1 acceptance job |
| `tests/integration` | **4 passed, 0 failed** | Crash / concurrency / long-task acceptance |
| Full Python 3.11 suite | **1407 passed, 2 skipped, 0 failed** | Python tests (3.11) |
| Python 3.12 compatibility | **PASS** | Python compatibility (3.12) |
| Python quality / critical Ruff / compile | **PASS** | Python quality |
| Frontend lint | **PASS** | React lint, tests, and build |
| Frontend tests | **72 files / 304 tests passed** | Vitest |
| Frontend production build | **PASS** | React build |
| Tauri Clippy | **PASS** | `cargo clippy -D warnings` |
| Tauri Rust tests | **1 passed, 0 failed** | `cargo test` |
| Tauri build/link | **PASS** | `cargo build --locked --no-default-features` |
| Aggregate CI quality gate | **PASS** | CI quality gate |

### Full regression acceptance

**Full Regression = PASS**

## 6. Long Task Soak

### Automated deterministic soak

Evidence: `tests/integration/test_agent_long_task_soak.py::test_long_task_soak_survives_pause_reconnect_and_store_restart`.

| Check | Result |
|---|---|
| Runtime profile | `long_task` |
| Durable simulated steps | 12 |
| Pause → PAUSE_REQUESTED → PAUSED | PASS |
| Store close/reopen (backend restart simulation) | PASS |
| Resume → RECOVERING → RUNNING | PASS |
| Frontend reconnect via event sequence cursor | PASS |
| Completed Step re-execution | 0 |
| Duplicate Step events | 0 |
| Run ID changed | 0 |
| Trace ID changed | 0 |
| Final durable result | complete |
| Final Run status | COMPLETED |

### Real-process crash acceptance

The automated soak is complemented by true process-boundary tests:

- `tests/integration/test_agent_crash_recovery.py`: Process A exits and Process B reopens/reclaims the durable run.
- `tests/integration/test_agent_write_crash_recovery.py`: Process exits after a physical write but before result persistence; recovery prevents replay.
- `tests/integration/test_agent_runtime_concurrency.py`: eight worker processes compete for one Run; physical execution count remains one.

### Manual release soak

The P0 task specification separately requires a **10–15 minute manual soak before release**, including real frontend navigation, WebSocket disconnect/reconnect, Pause/Resume, backend restart and recovery.

Current evidence status:

| Manual check | Status |
|---|---|
| 10–15 minute real elapsed task | NOT RUN |
| Real UI page switch during active Run | NOT RUN |
| Real WebSocket disconnect/reconnect | NOT RUN |
| Real backend process restart during UI session | NOT RUN |
| Run ID preserved | PENDING MANUAL VERIFY |
| Trace ID preserved | PENDING MANUAL VERIFY |
| Completed Step not repeated | PENDING MANUAL VERIFY |
| Final Result complete | PENDING MANUAL VERIFY |

The automated CI does **not** claim to replace this human release exercise.

## 7. Release reliability metrics

| Metric | Requirement | Automated evidence | Result |
|---|---:|---|---|
| Duplicate Run Execution | 0 | 8-process worker concurrency test | PASS |
| Duplicate Write Side Effect | 0 | real-process write-crash test + 100-caller idempotency test | PASS |
| Completed Node Re-execution After Resume | 0 | pause/resume + crash recovery tests | PASS |
| Lost Terminal Status | 0 | durable worker/crash/soak tests | PASS |
| Crash Recoverable Run | 100% deterministic tests | true Process A → Process B test | PASS |
| Tool Schema / policy validation | enforced | Agent Tool tests | PASS |
| Unsafe Write Automatic Retry | 0 | write recovery fence | PASS |
| Event Sequence Conflict | 0 | concurrent event/store tests + reconnect replay | PASS |
| Unknown Checkpoint Silent Recovery | 0 | unsupported-version tests | PASS |
| CI Regression | 0 failing tests | full CI run 35694123313 | PASS |

## 8. Release Gate

Automated gate:

- [x] P0-1 PASS
- [x] P0-2 PASS
- [x] P0-3 PASS
- [x] Full Regression PASS
- [x] Crash Recovery PASS
- [x] Duplicate Write = 0
- [x] Automated Long Task Soak PASS
- [x] CI Quality Gate PASS

Manual release prerequisite:

- [ ] 10–15 minute manual Soak Test PASS

## 9. Final conclusion

### Automated Runtime v1 acceptance

**PASS**

Commit `934f3e611fd37bc834372fbd240eeb3588e50547` satisfies the automated Stage 8 acceptance gate with zero failing required CI jobs.

### Final release sign-off

**Agent Runtime v1 = REJECTED until the required manual Soak Test is executed and passes.**

This is a release-sign-off status, not an automated-test failure. No automated Runtime v1 acceptance item remains failing. Once the manual soak checklist above is executed successfully, the final release verdict can be changed to:

`Agent Runtime v1 = ACCEPTED`

without changing the Runtime implementation unless the manual exercise reveals a defect.
