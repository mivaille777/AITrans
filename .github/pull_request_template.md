## Summary

Describe what changed and why.

## Verification

Run the checks that match the changed area before requesting review.

- [ ] Python/API: `python -m pytest -q tests/api tests/unit tests/test_backend_health.py`
- [ ] RAG: `python -m pytest -q tests/rag -m "not rag_gpu"`
- [ ] Sandbox: `python -m pytest -q tests/sandbox -m "not docker_integration"`
- [ ] Frontend: `cd apps/desktop; npm run lint; npm run test; npm run build`
- [ ] Electron (when present): `cd apps/desktop; npm run electron:compile; npm run test:electron-contracts`
- [ ] Tauri (when present): `./scripts/verify.ps1 -Scope Tauri`
- [ ] Cross-stack/API contracts updated when an interface changed
- [ ] New behavior has automated tests, or the reason for not adding them is documented below
- [ ] No secrets, local databases, generated runtime data, or model artifacts are committed

## CI expectations

The required merge signal is **CI quality gate**. The Extended Regression workflow is intentionally separate so the repository can surface legacy/full-suite regressions without weakening the required fast gate.

## Test notes

List targeted tests, manual checks, skipped hardware-dependent checks, or known limitations.

## Risk / rollback

Describe the main regression risk and how to revert or disable the change if needed.
