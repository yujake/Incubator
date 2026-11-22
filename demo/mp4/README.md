# mp4 — Are the free group factors `W*(F_k)` pairwise non-isomorphic?

**Open problem.** For `k ≠ m`, are the free group factors `W*(F_k)` and `W*(F_m)` non-isomorphic?

**Who reads it**: someone checking what this run actually delivered, before installing the system.

**Read in this order**: `out/paper/main.pdf` → `out/paper/ACCEPTANCE.md` →
`out/review/REPORT.md` → `reports/RESEARCH.md` → `reports/conj000000_infeasible_record.json`
(why the conjectured route was recorded as infeasible).

## What is here

| file | what |
|---|---|
| `out/paper/main.tex` / `main.pdf` | the paper and its compiled PDF |
| `out/paper/COMPILE-RECEIPT.json` | compile receipt (`tex_sha256` must match the source) |
| `out/paper/ACCEPTANCE.md` / `ACCEPTANCE-CHECKS.json` | acceptance table (prose and data) |
| `out/review/REPORT.md` | delivery report |
| `out/review/000000-review.md` | the reviewer's report |
| `out/experiments/conj000000_verdict.json`, `conj000000_readings.json` | the machine verdict and readings for conjecture 000000 |
| `reports/RESEARCH.md`, `reports/000000-research.md` | the researcher's notes |
| `reports/attack-000000.md` | the attack plan and its rounds |
| `reports/conj000000_infeasible_record.json` | the recorded infeasibility finding |
| `documents/note-fk-fm-research.md` | research manuscript produced during the run |
| `code/`, `scripts/` | the scripts behind every number (`fk_*`, `f_conj000000_*`, `conj000000_*`) |
| `verifications/000001.jsonl` | the proof-verification receipt |
| `notes/A.md`, `notes/G.md`, `notes/H.md` | per-role notes |
| `out/invalid/`, `out/roster/`, `out/secretary/`, `out/tasks/` | run by-products, not deliverables |

## Note on evidence strength

No Lean toolchain in this run, so nothing is machine-checked. The paper separates decided,
conditional, and undecided statements; the acceptance table and the infeasibility record say what
was not established. Internal ledger ids live only in `Appendix A`.

## Provenance

Exported from a real-machine run (the live workspace under `projects/` is git-ignored). No `data/`
here, so ledger readings cannot be recomputed; the acceptance files are the exported readings.
