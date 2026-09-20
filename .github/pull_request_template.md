## Summary

Describe what changed and why.

## Verification

- [ ] Backend changes: `./scripts/verify.ps1 -Scope Backend`
- [ ] Frontend changes: `./scripts/verify.ps1 -Scope Frontend`
- [ ] Tauri changes: `./scripts/verify.ps1 -Scope Tauri`
- [ ] Cross-stack/API contracts updated when an interface changed
- [ ] New behavior has automated tests, or the reason for not adding them is documented below
- [ ] No secrets, local databases, generated runtime data, or model artifacts are committed

## Test notes

List any targeted tests, manual checks, skipped hardware-dependent checks, or known limitations.

## Risk / rollback

Describe the main regression risk and how to revert or disable the change if needed.
