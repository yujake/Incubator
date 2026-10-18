# demo — four open problems, end to end

Four research runs produced by the `agentflow` system (this repository's `agentflow/` package).
Each directory is a self-contained showcase: the paper (LaTeX source and PDF), the compile
receipt, the acceptance table, the delivery report, the research manuscripts, and the scripts
that produced the numbers.

| dir | open problem | paper |
|---|---|---|
| `mp1` | Pyjama covering problem — how many rotated copies of the pyjama set cover the plane? | `mp1/out/paper/main.pdf` |
| `mp2` | Equichordal point problem — can a curve have two distinct equichordal points? | `mp2/out/paper/main.pdf` |
| `mp3` | If `U(g)` is Noetherian, must the Lie algebra `g` be finite-dimensional? | `mp3/out/paper/main.pdf` |
| `mp4` | Are the free group factors `W*(F_k)` pairwise non-isomorphic? | `mp4/out/paper/main.pdf` |

## What is in each directory

```
README.md                    one page: the problem, the deliverables, the readings
out/paper/main.tex           the paper, English, theorems with proofs in section 3
out/paper/main.pdf           compiled paper
out/paper/COMPILE-RECEIPT.json   tex_sha256 of the source that produced the PDF
out/paper/ACCEPTANCE.md      the acceptance table, cell by cell, including what was not done
out/review/REPORT.md         the delivery report written by the conductor
documents/                   research manuscripts produced during the run
reports/RESEARCH.md          the researcher's own research note
code/, scripts/              the scripts behind every number in the paper
```

## Reading the papers

Section 3 of each paper is the mathematical content: theorems, lemmas, propositions, each with a
step-by-step proof. **Computational evidence lives only in `Appendix A`**, together with the
internal identifiers of the run that produced it. The body of the paper contains no internal
identifiers at all.

## Evidence strength

These runs had **no Lean toolchain**, so nothing here is machine-checked. Claims are at most
`proof_review` (a proof reviewed line by line), `cross_check` (numerical cross-validation) or
`heuristic`. The papers say so explicitly, and the acceptance tables record what was left open.
