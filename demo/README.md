# demo — real runs, exported file by file

Two **real-machine runs** produced by the `agentflow` system (product source: [`agentflow/`](../agentflow/README-PRODUCT.md)).
Each case directory is a complete export of one run: the paper (LaTeX + PDF), the compile receipt,
the mapping table, the acceptance table, the closing report, the manuscripts, the ledger snapshots,
the session/step traces, and the code behind every number.

**Who reads it**: someone who wants to see what the system actually produces — and to open the same
web UI the operators used — before installing anything.

| dir | problem | paper | closing gate | spend / wall clock |
|---|---|---|---|---|
| [`sylow-4`](sylow-4/) | Prove Sylow I/II/III for a finite group: existence, conjugacy, counting | `sylow-4/out/package/main.pdf` (7 pages) | **8/8 pass · can_close=true · exit 0** | $1.93 / 114 min |
| [`lp-ball-22`](lp-ball-22/) | Largest-area central section of the 3-D ℓ^p ball: direction and A_max(p) | `lp-ball-22/out/package/main.pdf` | 待加入 — 大真机跑完后放进来 | — |

> `lp-ball-22/` will appear next to `sylow-4/` with the same layout once that run closes.

## Open the web UI for a demo

There is nothing special to install or launch: it is the normal command, with **the workspace root set
to the case directory inside `demo/`** (not to `demo/` itself).

```bash
# Sylow demo — pick a free port and print the URL as one JSON line
python -m agentflow --root D:\Incubator\demo\sylow-4 web --port 0 --json --allow-writes

# same case, let the tool choose and open the browser
python -m agentflow --root D:\Incubator\demo\sylow-4 web --open

# ℓ^p ball demo (same command, different workspace)
python -m agentflow --root D:\Incubator\demo\lp-ball-22 web --port 0 --json --allow-writes
```

On Linux/macOS the only difference is the path:

```bash
python -m agentflow --root ./demo/sylow-4 web --port 0 --json --allow-writes
python -m agentflow --root ./demo/lp-ball-22 web --port 0 --json --allow-writes
```

Notes:

- `--allow-writes` turns on the write surfaces (start a run, interject, answer, stop, edit settings).
  Omit it for a read-only UI: every panel still renders.
- `--port 0` asks the OS for a free port and prints the exact URL.
- **Do not use `demo/` as the root** — each case is an independent workspace with its own `data/`,
  `sessions/`, `out/`, …; `demo/` is only the container.
- To read the artifacts you need no server at all: `out/package/main.pdf` is the paper,
  `out/report/REPORT.md` is the closing report, and `out/package/MAPPING.json` links every theorem in
  the paper to its ledger row, proof manuscript, body sha, and verifier verdict.

## What is in each case

```
out/package/main.tex | main.pdf        the paper (theorems with proofs; Appendix A holds numerical evidence)
out/package/MAPPING.json               paper theorem ↔ ledger statement ↔ proof manuscript ↔ body sha ↔ V verdict
out/package/ACCEPTANCE-TARGETS.json    machine-checkable acceptance targets (one row per claim)
out/package/COMPILE-RECEIPT.json       tex_sha256 of the source that produced the PDF (byte-exact)
out/report/REPORT.md                   closing report written by the conductor role
manuscripts/<role>/…                   proofs and research notes, numbered per role
work/<role>/…                          drafts and experiment notes (e.g. e-num-000002.md)
data/                                  ledger snapshots (statements, experiments, literature, tasks …) + events.jsonl
sessions/ · runs/ · out/steps/         step-by-step traces (who did what, when, at what cost)
verifications/ · out/vsigns/           per-statement verdicts and the signed envelopes
code/                                  scripts that produced every number in the paper
reference/                             seed literature actually used (present only in cases that ship it)
```

## What is in the export (in full)

Each case is a **complete copy** of the run's workspace — nothing was cherry-picked:

- `data/`, `sessions/`, `runs/`, `out/` (every subdirectory, including `out/clock/`, `out/steps/`,
  `out/roster/`), `manuscripts/`, `work/`, `verifications/`, `notes/`, `reference/`, plus the
  workspace-root files (`RELIABLE-REFERENCES.json`, `ARTIFACTS.jsonl`, `AGENT-PROFILES.md`,
  `DOC-SIGNATURES.jsonl`, `budget.json`, …).
- `library/` and toolchain caches (`.miktex/`, `__pycache__/`, `.locks/`) are included as-is too, so the
  directory can be opened and inspected without re-fetching anything. If this repository is ever made
  public, revisit `library/` first: it holds third-party PDFs.
- `demo/** -text` in the root `.gitattributes` keeps every byte as-is on checkout, so
  `COMPILE-RECEIPT.json:tex_sha256` still matches `main.tex` after a clone.

Verification: the export was checked file by file against the source workspace — same file count
(380), same sizes, and identical sha256 for the paper, the PDF, the mapping table, the compile
receipt, the closing report, and the ledger snapshots.

## Evidence strength (read this before quoting a paper)

- No Lean toolchain was attached to these runs, so nothing is machine-checked. Claims are at most
  `proof_review` (a proof reviewed line by line by the verifier role), `cross_check` (numerical
  cross-validation) or `heuristic`; each paper states its own levels.
- `sylow-4` closes with **8/8** gate cells and `can_close=true`. One theorem (`stmt:000064`) is marked
  in the paper as having **no independent review** — the export keeps that sentence rather than hiding it.
- The ℓ^p case is a numerical + proof mixture: its experiments include claims that were **refuted**
  (counterexamples kept in `data/experiments.json`), not only the ones that held.
