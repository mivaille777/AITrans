# Stage 0 Report

## 1. Git

- branch: `WebReBuild`
- baseline parent commit: `75d41ace90e41af5aa000dd321f55341ef5d9553`
- stage commit: recorded by Git history for this report

## 2. Baseline

- profile: `rag-improvement-baseline-v1`
- profile path: `backend/rag/benchmarks/qasper/profiles/rag-improvement-baseline-v1.json`
- Smoke28 manifest: `validation-p1q2-smoke28-seed42.txt`
- Dev100 manifest: `validation-dev100-seed42.txt`

## 3. Only Variable Changed

No retrieval or answer behavior is intentionally changed in Stage 0. This stage only adds experiment identity and reproducibility metadata.

## 4. Unit Tests

Added coverage for deterministic profile SHA256 and run-manifest profile/prompt identity.

## 5. Retrieval Metrics

Pending real Smoke28 / Dev100 baseline runs.

## 6. Evidence Metrics

Pending real Smoke28 / Dev100 baseline runs.

## 7. Answer Metrics

Pending real Smoke28 / Dev100 baseline runs.

## 8. Runtime Metrics

Pending real Smoke28 / Dev100 baseline runs.

## 9. Paired Bootstrap

Not applicable to Stage 0 baseline freeze.

## 10. Challenge Cases

Not applicable until baseline runs exist.

## 11. Regressions

Push CI is expected to run the full repository regression suite. CI result must be reviewed before this stage is considered implementation-complete.

## 12. Gate

**PENDING / NO-GO for Stage 1 default enablement.**

The code/profile freeze is committed, but the taskbook requires reproducible Smoke28 and Dev100 real runs. Those run IDs are not fabricated in this report.

## 13. Decision

Keep the baseline strategy unchanged. Produce and audit Smoke28 and Dev100 runs with the frozen profile before promoting Stage 1.
