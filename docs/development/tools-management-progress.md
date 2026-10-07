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

T05–T08 pending. Actual Electron interaction not yet verified.
