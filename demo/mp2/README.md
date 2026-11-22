# mp2 — Equichordal point problem

**Open problem.** Can a plane curve have two distinct equichordal points?

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
| `out/review/000000-review.md` | the reviewer's report |
| `out/eq_s1/results.json` | machine-readable results of the `eq_s1` computation |
| `documents/000000.md` | research manuscript produced during the run |
| `reports/RESEARCH.md` | the researcher's note |
| `reports/attack-000000.md` | the attack plan and its rounds |
| `code/`, `scripts/` | the scripts behind every number in the paper (`eq_*`, `equichordal_scan`) |
| `notes/B.md`, `notes/C.md`, `notes/D.md` | per-role notes left by B, C, D |
| `out/invalid/`, `out/roster/`, `out/secretary/`, `out/tasks/` | run by-products, not deliverables |

## Note on evidence strength

This run had **no Lean toolchain**, so nothing here is machine-checked. Several numerical
experiments are `cross_check`; the paper states each claim's strength and the acceptance table
records what was left open. Internal ledger ids live only in `Appendix A`.

## Provenance

Exported from a real-machine run (the live workspace under `projects/` is git-ignored). There is no
`data/` here, so ledger readings cannot be recomputed; the acceptance files are the exported readings.
