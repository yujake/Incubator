# mp3 — Noetherian `U(g)` and finite-dimensional `g`

**Open problem.** If the universal enveloping algebra `U(g)` is Noetherian, must the Lie algebra `g`
be finite-dimensional?

**Who reads it**: someone checking what this run actually delivered, before installing the system.

**Read in this order**: `out/paper/main.pdf` → `out/paper/ACCEPTANCE.md` →
`out/review/REPORT.md` → `reports/RESEARCH.md`.

## What is here

| file | what |
|---|---|
| `out/paper/main.tex` / `main.pdf` | the paper and its compiled PDF |
| `out/paper/COMPILE-RECEIPT.json` | compile receipt (`tex_sha256` must match the source) |
| `out/paper/ACCEPTANCE.md` / `ACCEPTANCE-CHECKS.json` | acceptance table (prose and data) |
| `out/review/REPORT.md` | delivery report |
| `out/review/REPORT-CLOSING-NOTES.md` | notes written while closing the run |
| `out/review/000000-review.md`, `000002-review.md`, `000003-review.md` | reviewer reports per manuscript |
| `documents/000000.md` … `documents/000003.md` | research manuscripts produced during the run |
| `reports/RESEARCH.md`, `reports/000000-research.md` | the researcher's notes |
| `reports/attack-000000.md`, `attack-000000-lemma-S1.md`, `attack-000001.md` | attack plans and their rounds |
| `code/` | the scripts behind the paper's computations (`e*_`, `exp*_`) |
| `notes/A.md`, `notes/C.md`, `notes/G.md`, `notes/H.md` | per-role notes |
| `out/invalid/`, `out/roster/`, `out/secretary/`, `out/tasks/` | run by-products, not deliverables |

This run has **no `scripts/` and no `verifications/`** (unlike mp1/mp2/mp4): the paper's numbers
come from `code/`.

## Note on evidence strength

No Lean toolchain in this run, so nothing is machine-checked. The paper marks each result as
proved, conditionally argued, or open, and the acceptance table records the open cells. Internal
ledger ids live only in `Appendix A`.

## Provenance

Exported from a real-machine run (the live workspace under `projects/` is git-ignored). No `data/`
here, so ledger readings cannot be recomputed; the acceptance files are the exported readings.
