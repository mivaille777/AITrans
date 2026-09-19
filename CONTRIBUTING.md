# Contributing to AITrans

AITrans uses layered verification so failures are caught before changes reach `WebReBuild` or `main`.

## Recommended branch flow

1. Create a short-lived feature or fix branch from the latest `WebReBuild`.
2. Make focused commits.
3. Run the relevant local verification scope.
4. Open a pull request into `WebReBuild`.
5. Merge only after the required CI quality gate passes.
6. Promote tested changes from `WebReBuild` to `main` through a pull request.

Direct pushes to `WebReBuild` and `main` should be disabled by repository rules.

## Local verification

From the repository root:

```powershell
# Backend: Python 3.11, dependency consistency, Ruff, compile check, pytest
.\scripts\verify.ps1 -Scope Backend

# Frontend: lint, Vitest/typecheck, production build
.\scripts\verify.ps1 -Scope Frontend

# Tauri/Rust: fmt, Clippy, tests, locked build
.\scripts\verify.ps1 -Scope Tauri

# Everything
.\scripts\verify.ps1 -Scope All
```

Add `-Install` when dependencies need to be installed or refreshed:

```powershell
.\scripts\verify.ps1 -Scope All -Install
```

The backend verification intentionally requires Python 3.11 because that is the project's primary runtime. CI also runs a Python 3.12 compatibility smoke suite.

## CI layers

The normal CI workflow verifies:

- full Python 3.11 pytest suite and Agent/RAG regression benchmarks;
- Python dependency consistency and Ruff correctness checks;
- Python 3.12 compatibility smoke tests;
- React lint, Vitest/type checks, and production build;
- Rust formatting, Clippy, tests, and locked Tauri build;
- a final `CI quality gate` job that succeeds only when every required layer succeeds.

GPU/model tests remain opt-in because they require suitable hardware and local models.

## Pull request expectations

Changes that alter behavior should normally include or update automated tests. API/schema changes should update both backend contract tests and the corresponding frontend API/runtime tests. Keep generated data, local SQLite files, credentials, model files, and runtime artifacts out of commits.
