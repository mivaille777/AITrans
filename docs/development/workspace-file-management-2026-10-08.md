# Workspace file management — 2026-10-08

AITrans can now create and edit actual files in the folder selected by the current chat. A request to create `a.md` containing only `abcd` uses a filesystem tool and produces exactly four UTF-8 bytes. Markdown downloads remain a separate capability.

## Scope and controls

- Eight typed tools: `list_workspace_files`, `search_workspace_text`, `read_workspace_text`, `create_workspace_file`, `edit_workspace_file`, `write_workspace_file`, `create_workspace_directory`, and `undo_workspace_change`.
- The session supplies the workspace and read/write permission. Model arguments contain relative paths, never a new root or permission grant. The server rechecks the live chat configuration before each filesystem call.
- ReAct can fulfill an explicit request for a named new file directly. Existing-file edits and overwrites show a diff for approval. Creation is exclusive and never overwrites an existing path.
- Plan–Execute prepares file diffs without writing. Approval binds tool arguments, workspace, content hashes, and sizes. An approved plan can create a directory followed by a file without a second approval. Changed versions or changed configured tool defaults invalidate the approved effect.
- The tools menu follows the session's server-owned workspace and access setting. The existing workspace control shows the actual folder and offers read-only/read-write access.
- The context panel provides directory browsing, paged text previews, current-session change receipts, opening/revealing local files in Electron, and undo with a diff confirmation. No component stylesheet or existing icons were changed.

## Data integrity

Text writes preserve the requested whitespace and line endings; edits preserve an existing UTF-8 BOM. Partial edits require exactly one matching old fragment. Existing-file writes require the SHA-256 version read from disk. Publication uses a complete temporary file, an exclusive create or replacement, and readback verification. SQLite records the intent before the effect and the verified receipt afterwards. Tool-call identifiers provide idempotency; an unresolved write is never automatically replayed.

Undo restores the prior bytes or removes an unchanged file created by this service. Directory creation can only be undone while that same directory remains empty. External edits cause a conflict and are preserved. UI undo approvals are short-lived, one-use, and bound to session, workspace, change, and preview.

Paths cannot escape the active workspace through traversal, Windows drive/UNC paths, alternate streams, symlinks, junctions, or hardlinks. Protected credentials, Git internals, and application runtime databases are inaccessible. File contents are data rather than instructions or authorization.

## Boundaries

Exact text reading and editing support UTF-8 files up to 2 MB; a single tool write accepts at most 100,000 characters. Browsing and reading are paged. Literal text search is bounded to 4,096 scanned files and reports truncation. Parsed PDF/DOCX reading remains available through the existing document reader; these tools do not rewrite those formats. Copy, move, rename, and general deletion are outside this first phase. Native filesystem effects use the scoped file service; existing Docker computation tools are unchanged.

## Verification

Tests cover physical byte counts, whitespace/BOM preservation, collision handling, conflict-aware undo after reopening the service, concurrent duplicate calls, read-only restrictions, Windows junctions, hardlinks, API confirmation tokens, plan approval/rejection, approved directory/file sequences, version binding, configured-default changes, false success claims, and contiguous full-text reading. React tests exercise preview, cancel, confirmation, and read-only behavior. Electron type/build checks and the desktop production build are also required.

The project-configured real model was exercised against isolated Windows folders in `.cache`: ReAct creation produced `abcd`; Plan–Execute creation kept the path absent until approval, then produced `abcd`; Plan–Execute editing kept `abcd` until approval, then produced `xyz`. Initial evidence is in `.cache/workspace-file-live-20261008/results.json`. A final repeat uses `.cache/workspace-files-live-final-20261008/results.json`. Native ReAct editing also kept `abcd` unchanged until diff approval, then produced `xyz`, with evidence in `.cache/workspace-file-react-edit-live-20261008/results.json` (run `run-7384f66699794b6883a5b50837b90115`). These folders contain test data, not user documents.

Verification runs use an index export at `.cache/workspace-files-staged-qa` to exclude unrelated local changes. Its desktop companion/adapter suite passed 167 tests and its Electron checks passed 66 tests, including compilation and test typechecking. The ordinary desktop production build passed the PDF.js offline guard. A build in the exported copy also compiled successfully, but its guard expected a `node_modules/` manifest key while the shared dependency junction generated an external path; the guard was therefore verified in the actual desktop project directory.

Final backend regression in the index export: **753 passed**. Command: `python -m pytest tests/agent tests/api/test_workspace_files_api.py tests/api/test_tool_management_api.py tests/test_chat_session_service.py tests/test_backend_product_agent.py tests/integration/test_native_write_recovery.py -q`. The native edit confirmation regression verifies that a legacy tool-name approval does not bypass the exact saved diff when configured content changes. Latest frontend changes also passed the five file-panel/session-control tests and `tsc -b`; `npm run build` passed after the final UI changes.

Restart the desktop process and backend to load the new backend tools and Electron file-location bridge.
