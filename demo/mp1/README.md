# mp1 — Pyjama covering problem

**Open problem.** How many rotated copies of the pyjama set are needed to cover R^2?

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
| experiments | 25 |
| statements | 37 |
| statements at `proof_review` | 10 |
| research questions | answered |
| conjectures | supported_not_proved |
| paper pages | 10 |
| spend | $4.662 of $5 |

## Note on evidence strength

These runs were made **without a Lean toolchain**, so nothing here is machine-checked.
Every claim is at most `cross_check` / `proof_review` / `heuristic`, and the papers say so.
Internal ledger ids (`exp:` / `stmt:` / `lit:`) live **only** in `Appendix A: Computational evidence`.
