# Tools implementation progress

## T00 — baseline and contracts

Implementation: complete. Contract/document verification: complete. Remote synchronization: recorded after push in the execution report.

Base: 56675625a24f0fe209202f86b19f3cad846867bb. Independent branch codex/tools-management. Original dirty checkout preserved. Design and taskbook copied into the branch.

System Python failed collection because faiss is absent; use existing aitrans Conda environment. No dependencies installed or upgraded. Runtime baseline test results will be appended after completion.

## T01 — typed management catalog

Implementation and API verification complete. Added full typed input/output schemas, separate native Chat profile, dependency information, filtered category counts and cursor binding. Legacy catalog unchanged. T00 remote SHA: 68b38c42440d7a8a69fc776773696abf1242f631 (verified).

Conda baseline: 24 passed. New management API + legacy API tests: 8 passed. Frontend API encoding, type checks and Ruff are checked before this stage push. No live model used.

## Remaining

## T02 — workspace and real library

Implemented /tools with lazy cached route, existing sidebar and an owned heading. Search debounce, state/category filters, group folding, cursor paging, URL selection, empty/error/retry states and responsive panels are implemented. Live isolated backend at port 8772 returned 23 actual tools; browser inspection at 1680×1050 confirmed the full workbench. Future-stage actions explicitly disabled.

Verification: 8 frontend behavior/API/navigation tests passed; test typecheck passed; lint completed with existing unrelated warnings; full build and PDF.js offline guard passed. Initial PDF guard failure was caused by Vite resolving the dependency junction outside this worktree. Dependencies were copied locally without upgrades; build then passed without changing the guard or Vite behavior.

T01 remote SHA: dd947d3542f5e0aabac453583db5981b34ef13af (verified).

## T03 — five detail tabs

Implemented Overview, Parameters, Returns, Permissions and Examples. Visual schema resolves referenced objects/array items and shows requirements/defaults/constraints, with full JSON fallback for alternatives and recursive schemas. Native Chat schema is separately identified. Copy and Use in test fill per-tool drafts; output data and execution envelope remain distinct. Keyboard arrow tab selection supported.

Verification: 4 detail/schema behavior tests passed; 4 backend management/example tests passed; input/output schema viewed against live backend in browser. Typecheck and application compilation passed after correcting the new test's locator options. T02 remote SHA: 9f8c1037bdd5c8f0da099641d1cee6dffe0746a0 (verified).

## T04 — persistent policy across entry points

Enabled state is persisted in tools.sqlite3 with atomic optimistic revisions. Management keeps disabled tools visible; Agent automatic/explicit choices, native Chat, full-document dependencies, fallback retrieval, and legacy calls share execution checks. Legacy scoped/confirmed calls now require the governed test endpoint because the old DTO cannot express scope or approval. UI keeps persisted state after failed updates, provides reload on conflicts, and periodically refreshes catalogs.

Verification: 99 registry/native/runtime/API regression tests passed, followed by 82 policy/management/native tests including the new entry-point checks. Five frontend behavior/schema tests, test typecheck and app compilation passed. T03 remote SHA: 43a5258c3b1b872dd9a4f29313207345658bab4b (verified). No live model used.

## T05 — governed real test execution

Implemented strict validation and async create/get/cancel/approve APIs. Context scope is separate from arguments, research and filesystem IDs are resolved independently, knowledge scope must be explicit, and callers cannot send confirmed/run/trace/call IDs. Test writes consume an ephemeral approval bound to the actual server-created call ID and input/config hash, then revalidate immediately before execution. AgentToolExecutionService gained an optional server-selected call ID; ordinary callers retain generated IDs. No safe retry is used for inspector calls.

Frontend has JSON validation, field error feedback, required context inputs, timeout, actual result envelope, bound approval review/rejection, response cancellation and reconnection polling. Cancellation and deadlines preserve running/unknown physical state until completion; late results cannot overwrite cancelled/timed-out status. This stage keeps runs in memory; durable history/events are T06.

Verification: 12 execution/approval/API tests passed, previous 14 execution/catalog tests passed, 5 Tools UI tests passed, test typecheck/app compilation/Ruff passed. T04 remote SHA: c7e18b48cbe9dc4944a4a8ae851badc29d36927a (verified).

## T06 — durable history and live lifecycle

Added inspector extension tables in agent_runtime.sqlite3, separate from Agent run queues. Immutable request hashes support durable idempotency; inputs and approval review text remain ephemeral. Lifecycle events have ordered sequence IDs, Last-Event-ID replay and polling fallback, without replaying execution. History pages are bound to the tool and use timestamp/ID cursors. Restart interrupts active tests and invalidates approvals; unknown physical completion stays protected. Retention is 100 finalized/stopped tests or 30 days globally, with events removed transactionally; unresolved and pending records are protected.

UI now restores last runs, offers paged history, Input/Result/Logs tabs, deduplicates SSE events and falls back to polling for results and stored logs. Results above 256 KiB expose an explicit preview marker; streaming is still truthfully unsupported by current executors.

Verification: 9 store/execution/API tests passed, including stable same-timestamp paging, retention/protected records, restart invalidation, durable duplicate requests and SSE cursor replay. Five frontend tests and typechecks passed. T05 remote SHA: 2fc3cdfc17160683caa0676293a863021039eeb5 (verified).

## T07 — real configuration presets and atomic imports

Implemented custom knowledge-search presets, default disabled, with immutable call names, disjoint fixed/exposed fields, typed defaults/examples and bounded timeout. Registry dynamically exposes persisted presets to Agent execution; primitive policy, trusted knowledge scope, search budget, grounding and trace minimization remain effective. Primitive timeout overrides also bound custom calls. Native Chat capability is explicitly unsupported for presets. Built-in metadata edits preserve executor authority and model validators.

Added create/edit/archive APIs and versioned JSON import preview. Imports validate all records before a transaction, bind preview to current configuration, require explicit replace for conflicts, disable imported/replaced tools and roll back the entire batch on failure. Archived names remain reserved and history links remain readable. UI includes data-only configuration editors, bounded JSON upload, preview/conflict resolution, edit and archive actions.

Verification: 23 preset/policy/execution/runtime tests passed, with actual Agent dispatch into a typed test executor; four preset tests cover scope/budget/primitive policy, immutable authority, stale preview/atomic rollback and archive identity. Seven frontend workflow tests and typechecks passed. T06 remote SHA: 03319fab8346963c91c1aa6028283fa1550c7759 (verified). Real indexed retrieval and desktop/browser acceptance remain T08.

T08 pending. Actual Electron interaction not yet verified.
