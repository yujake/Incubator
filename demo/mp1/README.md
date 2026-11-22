# mp1 — Pyjama covering problem

**Open problem.** How many rotated copies of the pyjama set are needed to cover R^2?

**Who reads it**: someone checking what this run actually delivered, before installing the system.

**Read in this order**: `out/paper/main.pdf` (the result) → `out/paper/ACCEPTANCE.md` (what was and
was not done) → `out/review/REPORT.md` (the conductor's delivery report) → `reports/RESEARCH.md`
(the researcher's own note).

## What is here

| file | what |
|---|---|
| `out/paper/main.tex` | the paper (LaTeX source) |
| `out/paper/main.pdf` | compiled paper |
| `out/paper/COMPILE-RECEIPT.json` | compile receipt (`tex_sha256` must match the source) |
| `out/paper/ACCEPTANCE.md` | acceptance table, cell by cell |
| `out/paper/ACCEPTANCE-CHECKS.json` | the same cells as data |
| `out/review/REPORT.md` | delivery report |
| `out/review/000000-review.md` | the reviewer's report on the manuscript |
| `out/review/m-verdicts.jsonl` | the conductor's verdict rows |
| `documents/000000.md` | research manuscript produced during the run |
| `reports/RESEARCH.md` | the researcher's own research note |
| `reports/attack-000000.md` | the attack plan and its rounds |
| `code/`, `scripts/` | the scripts behind every number in the paper |
| `verifications/` | proof-verification receipts |
| `out/invalid/`, `out/roster/`, `out/secretary/`, `out/tasks/` | run by-products (step traces, roster and board rows), not deliverables |

## Note on evidence strength

This run had **no Lean toolchain**, so nothing here is machine-checked. Every claim is at most
`proof_review` / `cross_check` / `heuristic`, and the paper says so. Internal ledger ids
(`exp:` / `stmt:` / `lit:`) live **only** in `Appendix A: Computational evidence`.

## Provenance

Exported from a real-machine run (the live workspace under `projects/` is git-ignored). There is no
`data/` here, so the ledger readings cannot be recomputed from this directory; the acceptance files
are the exported readings.
