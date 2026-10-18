# mp4 — Free group factors

**Open problem.** Are W*(F_k) and W*(F_m) isomorphic for k != m?

## Deliverables

| file | what |
|---|---|
| `out/paper/main.tex` | the paper (LaTeX source) |
| `out/paper/main.pdf` | compiled paper |
| `out/paper/COMPILE-RECEIPT.json` | compile receipt (`tex_sha256` must match the source) |
| `out/paper/ACCEPTANCE.md` | acceptance table, cell by cell |
| `out/review/REPORT.md` | delivery report |
| `documents/` | research manuscripts produced during the run |
| `reports/RESEARCH.md` | the researcher's own research note |
| `code/`, `scripts/` | reproducible computation scripts |

## Readings (from the ledger at export time)

| metric | value |
|---|---|
| experiments | 11 |
| statements | 2 |
| statements at `proof_review` | 0 |
| research questions | dropped |
| conjectures | needs_evidence |
| paper pages | 11 |
| spend | $4.306 of $5 |

## Note on evidence strength

These runs were made **without a Lean toolchain**, so nothing here is machine-checked.
Every claim is at most `cross_check` / `proof_review` / `heuristic`, and the papers say so.
Internal ledger ids (`exp:` / `stmt:` / `lit:`) live **only** in `Appendix A: Computational evidence`.
