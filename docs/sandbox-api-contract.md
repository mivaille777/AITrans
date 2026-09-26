# Sandbox API Contract

This document freezes the P0 contracts shared by the backend, Agent tools, and
Sandbox Debug Studio. The Pydantic models in `backend/models/` and
`backend/sandbox/` remain the validation source of truth. Objects reject unknown
fields unless stated otherwise.

## Trust boundaries

- The backend selects the permission profile and evaluates every permission
  request. Agent arguments cannot choose a profile, add capabilities, or run a
  host command.
- A workspace is referred to by its opaque `workspace_id`. Host absolute paths
  stay in backend-only services and must not appear in API responses or traces.
- Workspace edits are captured in a disposable copy. Host writes require an
  explicit approval and a single-use grant bound to the run, tool call, action,
  workspace, and exact changeset.
- Secrets and the full host environment are not part of any Sandbox request,
  result, approval, or trace contract.

## Permission policy

The backend defines these profiles: `read_only`, `workspace_write`, and
`restricted_network`. A profile is server-selected; it is not an Agent-supplied
request field. The default command allowlist is `python` and `pytest`.

Permission actions used by P0 are:

```text
filesystem.read
filesystem.write_sandbox
filesystem.apply_host
network.connect
command.execute
secret.read
```

`PermissionRequest` contains `action`, `target`, `reason`, `tool_name`, `run_id`,
and `tool_call_id`. `PermissionDecision` contains:

```json
{
  "decision": "allow | deny | approval_required",
  "reason_code": "policy-specific code",
  "reason": "human-readable explanation",
  "granted_scope": {}
}
```

Unknown actions and profiles are denied. A host filesystem apply decision is
`approval_required`; it is never directly allowed by the Agent.

## Approval and grant

`SandboxApprovalRequest` contains:

```text
approval_id, run_id, tool_call_id, permission_action, target, reason,
requested_scope, requested_changes, status, created_at, expires_at
```

Status is `pending`, `approved`, `denied`, `expired`, or `consumed`.
`requested_changes` lists each `create`, `modify`, or `delete` path and its
before/after sizes. Approvals expire. Approval creates an internal
`PermissionGrant` with `grant_id`, `approval_id`, `action`, `scope`, `run_id`,
`tool_call_id`, `expires_at`, and `single_use: true`. The grant itself is not
returned to the Agent; the approval ID is used when applying its exact changeset.
Approval state and grants are held in process memory; a backend restart clears
them and invalidates any unconsumed authority.

Routes:

| Method | Route | Result |
| --- | --- | --- |
| `GET` | `/api/sandbox/approvals/pending` | Pending approval requests |
| `POST` | `/api/sandbox/approvals/{approval_id}/approve` | Request with `approved` status |
| `POST` | `/api/sandbox/approvals/{approval_id}/deny` | Request with `denied` status |

An approval API error uses FastAPI's `detail` object with `code` and `message`.
Consumed and expired requests cannot be reused.

## Command tool

`GET /api/agent/tools` advertises `command_execute` when Sandbox is enabled and
available. Its argument object is:

```json
{
  "argv": ["python", "-m", "pytest", "-q"],
  "cwd": ".",
  "timeout_seconds": 30,
  "network_host": null,
  "network_approval_id": null
}
```

`argv` is an array (1–64 strings); shell syntax is not accepted. `cwd` must be a
safe relative path. Timeout is greater than zero and at most 30 seconds. An
explicit `network_host` requests approval for that exact hostname. Repeating
the command with the returned `network_approval_id` consumes that single-use
network grant.

The Agent invocation context may include `filesystem_workspace_id`, `run_id`,
and `tool_call_id`; these are not command arguments. The result data includes
`sandbox_id`, `argv`, `status`, `exit_code`, bounded `stdout`/`stderr`,
`duration_ms`, timeout/OOM/output-limit flags, runtime/image, optional
`permission_decision`, optional `approval_id`, and optional
`workspace_changeset`.

Command status is `succeeded`, `failed`, `cancelled`, `timed_out`, `oom_killed`,
`output_limit_exceeded`, `denied`, or `approval_required`.

## Workspace change set

When a command runs with a selected workspace, its result includes a
`WorkspaceChangeSet` for the sandbox copy (the `changes` array may be empty):

```json
{
  "sandbox_id": "sb_<opaque-id>",
  "workspace_id": "fsw_<opaque-id>",
  "base_snapshot_hash": "<sha256>",
  "changes": [
    {
      "operation": "modify",
      "path": "src/main.py",
      "before_sha256": "<sha256>",
      "after_sha256": "<sha256>",
      "size_before": 10,
      "size_after": 12,
      "mode_before": 420,
      "mode_after": 420
    }
  ],
  "changeset_hash": "<sha256>"
}
```

Change operations are `create`, `modify`, and `delete`. Paths must be safe,
workspace-relative paths. The changeset hash covers the canonical changeset
content. P0 limits changes to 50 files, 5 MiB per file, and 20 MiB total. Modes
are numeric permission bits.
Protected paths include `.git`, `.env` files, `*.pem`, and `*.key`.

The apply API accepts the exact changeset returned by the command result:

| Method | Route | Request body |
| --- | --- | --- |
| `POST` | `/api/sandbox/workspaces/changesets/approval` | `{ "changeset": <WorkspaceChangeSet> }` |
| `POST` | `/api/sandbox/workspaces/changesets/apply` | `{ "changeset": <WorkspaceChangeSet>, "approval_id": "..." }` |
| `GET` | `/api/sandbox/workspaces/apply-audit` | Optional `limit` query, default 100, maximum 500 |

Apply rechecks the workspace snapshot and each target, verifies the stored
payload hashes, consumes the exact grant, and atomically writes each file. A
stale snapshot fails with `workspace_conflict`; grant replay fails with
`approval_grant_replayed`.

## Debug trace

Routes:

| Method | Route | Result |
| --- | --- | --- |
| `GET` | `/api/sandbox/debug/health` | Runtime availability and image information |
| `GET` | `/api/sandbox/debug/runs` | Recent run summaries |
| `POST` | `/api/sandbox/debug/runs` | Start a manual Python run; responds `202` |
| `GET` | `/api/sandbox/debug/runs/{sandbox_id}` | Full `SandboxDebugTrace` |
| `POST` | `/api/sandbox/debug/runs/{sandbox_id}/cancel` | Updated run summary |
| WebSocket | `/api/sandbox/debug/runs/{sandbox_id}/stream` | Live trace events |

`SandboxDebugTrace` includes `run`, `stages`, `stdout`, `stderr`, `activities`,
`resources`, effective `policy`, `input_files`, `output_files`,
`workspace_changes`, and `error`. Stage keys are `request`, `permission`,
`approval`, `workspace`, `staging`, `create`, `start`, `execute`, `network`,
`changes`, `apply`, `collect`, and `cleanup`.

Each activity includes `sequence`, `timestamp`, `kind`, `action`, `target`,
`decision`, `reason`, `permission_action`, `policy_rule`, `approval_id`, and
`grant_id`. The event log covers permission requests and decisions, approval
transitions, command start/exit, filesystem reads/changes/applies, and network
requests/decisions.

The WebSocket sends envelopes with `type` equal to `trace`, `stage`, `activity`,
or `terminal`, and the matching `trace`, `stage`, or `activity` value. Traces
must redact host absolute paths and known credentials. They do not store code,
full environment variables, API keys, tokens, or passwords.

## Compatibility

Consumers should treat additive optional fields and new stage/activity enum
values as forward-compatible. Missing `activities` and `workspace_changes` in
older trace payloads normalize to empty arrays. Unknown request fields remain
invalid so callers cannot silently add authority.
