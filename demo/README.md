# demo — four research runs, exported end to end

Four runs produced by the `agentflow` system (this repository's [`agentflow/`](../agentflow/README-PRODUCT.md)).
Each directory is a self-contained showcase: the paper (LaTeX source and PDF), the compile
receipt, the acceptance table, the delivery report, the research manuscripts, and the scripts that
produced the numbers.

**Who reads it**: someone who wants to see what the system actually produces before installing it.

| dir | open problem | paper |
|---|---|---|
| [`mp1`](mp1/README.md) | Pyjama covering problem — how many rotated copies of the pyjama set cover the plane? | `mp1/out/paper/main.pdf` |
| [`mp2`](mp2/README.md) | Equichordal point problem — can a curve have two distinct equichordal points? | `mp2/out/paper/main.pdf` |
| [`mp3`](mp3/README.md) | If `U(g)` is Noetherian, must the Lie algebra `g` be finite-dimensional? | `mp3/out/paper/main.pdf` |
| [`mp4`](mp4/README.md) | Are the free group factors `W*(F_k)` pairwise non-isomorphic? | `mp4/out/paper/main.pdf` |

## What is in each directory

```
README.md                    one page: the problem, the deliverables, where to read further
out/paper/main.tex           the paper, English, theorems with proofs in section 3
out/paper/main.pdf           compiled paper
out/paper/COMPILE-RECEIPT.json   tex_sha256 of the source that produced the PDF
out/paper/ACCEPTANCE.md      the acceptance table, cell by cell, including what was not done
out/paper/ACCEPTANCE-CHECKS.json  the same cells as machine-readable data
out/review/REPORT.md         the delivery report written by the conductor
documents/                   research manuscripts produced during the run
reports/RESEARCH.md          the researcher's own research note
code/                        the scripts behind every number in the paper
```

`scripts/` and `verifications/` exist in some runs and not others — each `mpN/README.md` lists what
that run actually contains. `out/invalid/`, `out/roster/`, `out/secretary/`, and `out/tasks/` are
**run by-products** kept for fidelity (step-level traces and board rows), not deliverables.

## What is not here

- **No `data/`.** The ledger snapshots were not exported, so the prose readings cannot be
  recomputed from this directory. The authoritative readings are the two acceptance files and
  `out/review/REPORT.md`, which are themselves exports.
- **No way to re-run them from the repo.** These came from real-machine runs in `projects/`
  (git-ignored). They are *exported artifacts*: treat them as evidence, not as a reproducible build.

## Reading the papers

Section 3 of each paper is the mathematical content: theorems, lemmas, propositions, each with a
step-by-step proof. **Computational evidence lives only in `Appendix A`**, together with the
internal identifiers of the run that produced it. The body of the paper contains no internal
identifiers at all.

## Evidence strength

These runs had **no Lean toolchain**, so nothing here is machine-checked. Claims are at most
`proof_review` (a proof reviewed line by line), `cross_check` (numerical cross-validation) or
`heuristic`. The papers say so explicitly, and the acceptance tables record what was left open.
