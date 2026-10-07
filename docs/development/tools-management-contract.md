# Tools management contract v1

Frozen at T00, 2026-10-07. Detailed requirements: [taskbook](tools-management-taskbook-2026-10-07.md).

Identity: builtin:<name>, custom:<uuid>; invocation name unchanged for built-ins. Device-level enabled policy, revision optimistic concurrency. enabled differs from available; effective_enabled requires both. Automatic [] remains automatic within allowed catalog. Disabled primitives also block derived custom presets and composite native reads.

Catalog GET /api/tools?q=&category=&status=all&limit=100&cursor= returns items, categories (filtered counts), total/enabled/disabled (whole catalog), matched_total, next_cursor, catalog_revision. GET /api/tools/{id} includes full input_schema/output_schema, optional native input profile, context_requirements, permissions, limits, examples, execution_capabilities, editable_fields, revision. JSON Schema references remain intact. Risk is unknown when not declared; effect alone cannot assert low risk.

PATCH /api/tools/{id}: enabled/config + revision. Immutable schema, executor, effect and authority. Error detail object: code/message/field_errors/trace_id; 404 unknown, 403 disabled/scope, 409 stale/conflict, 422 invalid input, 503 dependency. Legacy HTTP contract retained while checks are added.

Test input: arguments (strict object), context_selection (workspace_id, filesystem_workspace_id, selected source_text and bounded reading fields), timeout_seconds (positive, max 120), stream_output (only if supported), client_request_id. IDs, scopes and approvals are constructed/verified by server. Unknown or server-owned arguments rejected. POST validate is side-effect free; create returns 202 and run. Approval action references a server approval with exact run/config/input binding.

State queued/running/awaiting_approval/succeeded/failed/timed_out/cancelled/interrupted; execution_state stopped/running/unknown. Cancellation/timeout never implies a worker stopped. No replay of uncertain writes. Before start/resume recheck policy and resource scope. Same request key and input returns original run; conflicting input 409.

History uses SQLite in writable_config_dir; 100 finalized records / 30 days, result <= 256 KiB with explicit truncation. No credentials or source text in event logs. Persist immutable configuration/input fingerprints. Unresolved and awaiting records protected; on restart mark unresolved workers interrupted/unknown and invalidate process approvals. UTC timestamps.

SSE GET /api/tool-test-runs/{id}/events emits monotonic seq, supports Last-Event-ID; reconnection does not execute. Lifecycle events available to ordinary tools; no output_delta unless executor truly streams. Capability controls expose unsupported streaming/cancellation honestly.

Custom tools: config presets over an allowlisted typed executor template; initial template knowledge search. Versioned JSON imports preview conflicts then atomically apply. Default disabled. Fixed parameters cannot be overwritten by invocation. Presets preserve primitive policy and permission checks. Built-in Edit can change description/examples/defaults/shorter timeout only. Archive retains history. Unknown fields and executable imports rejected.
