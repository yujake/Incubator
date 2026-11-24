# SEED-README

这个工作区在建立时被投放了一批历史真机下载的文献种子。

## 它们是什么

- 25 份 PDF，共 17845452 字节，落在 `reference/`（工作区的**输入区**）。
- 来源：`agentflow/seed/literature/`（清单 `MANIFEST.json`）；原样字节，没有改名、没有改写内容。
- 每份都满足种子口径：下载成功、字节 > 0、盘上文件存在、sha256 与清单一致、正文抽得出来。

## 它们不是什么（重要）

- **未入库、也不在已登记书架上**：`library/` 是已登记书架（`literature.path` 指向它），
  本批文件一份都没有进去；`data/literature.json` 仍是 0 行，没有 lit_id、摘要或处置。
- 未判收：种子口径只证明“下载成功且抽得出来”，不证明“与本研究相关、可收录”。
- 不是已验证全文：清单里的抽读字数只是筛选读数，不是收录判据。

## 怎么声明（用户信任这个文件夹）

只有用户点名过的文件才可入库。声明落在工作区根的 `RELIABLE-REFERENCES.json`：

```json
{
  "paths": ["reference/"],
  "verbatim": "reference/ 里的文件都是用户提供的可靠参考文献，可入库；其它地方的文件只作参考、不可入库"
}
```

声明里写 `reference/` 就是把整个输入区点名；**没有声明 ⇒ 一份都不许入库**。

## 怎么用（A 的候选链，一步都不能省）

1. **发现（只发现、零写入）**：`search.ingest_local(books_dir="reference", dry_run=True)` —— 只读盘上文件、算 sha256/页数/文本层；`lit_candidates` / `literature` / 台账一个字节都不写。
2. **建候选**：逐份 `lit.stage_add(request_id=<委托号>, entries=[{title: …, url: <发现读数里那一份的盘上路径>, relevance: "工作区里已有的本地文献，不是检索来的"}])` —— 只写候选表，`literature` 仍是 0 行。
3. **判收**：`lit.stage_list` 回读 → `text.extract(lit_id="cand:<槽位>")` 抽正文 → `fs.read` 读到同一版 `.txt` → `lit.admit(items=[{slot, availability: "readable"}])`（`content_read` 由机器现算）→ 逐委托 `lit.admit_all` 提交（发号、回填、清表）。
4. **收进 `literature` 之后**：派 B 的 `run_once` 整理（抽概念、建关系、落命题线索），直到这一批 `literature.processed` 全真。

⚠️ **非 dry 档跳过判收、不要用**：`search.ingest_local` 不带 `dry_run=True` 时直接把盘上文件写成 `literature` 行，等于把“下载成功”冒充成“判收过了”。

## 怎么复算

在 `agentflow/` 下跑：

```
python scripts/seed_corpus.py --verify
```

它按 `agentflow/seed/literature/MANIFEST.json` 逐份重算 sha256 与抽读字数；任何一份被改动、缺失或字数对不上都以退出码 1 结束。

## 这一批的清单

- `reference/08359e313da3-on-the-volume-of-hyperplane-sections-of-a-d-cube.pdf` — On the volume of hyperplane sections of a d-cube
- `reference/290c7eb63abe-resilience-of-cube-slicing-in-lp.pdf` — Resilience of cube slicing in ℓp
- `reference/52375fd6b18c-estimates-on-the-decay-of-the-laplacepolya-integral.pdf` — Estimates on the decay of the Laplace–Pólya integral
- `reference/5d236efcb7ea-critical-central-sections-of-the-cube.pdf` — Critical central sections of the cube
- `reference/64498329b65e-an-introduction-to-measure-theory.pdf` — An Introduction to Measure Theory
- `reference/66cf70c235d2-maximal-perimeters-of-polytope-sections-and-origin-symmetry.pdf` — Maximal Perimeters of Polytope Sections and Origin-Symmetry
- `reference/6c8afb33fc1a-the-geometry-of-minkowski-spaces-a-survey-part-i.pdf` — The geometry of Minkowski spaces — A survey. Part I
- `reference/7a7ab07fb74f-measure-integration-real-analysis.pdf` — Measure, Integration & Real Analysis
- `reference/92378bba55bc-the-cross-section-body-plane-sections-of-convex-bodies-and-a.pdf` — The cross-section body, plane sections of convex bodies and approximation of convex bodies, I
- `reference/929d246e1f5b-cube-slicing-in-r-n.pdf` — Cube Slicing in R n
- `reference/9ec6189b98ee-on-extremal-sections-of-subspaces-of-l-p.pdf` — On Extremal Sections of Subspaces of $$L_p$$
- `reference/a7344ad13416-plane-sections-of-the-unit-ball-of-l-p.pdf` — Plane sections of the unit ball of L_p
- `reference/acb5dd61859c-generalized-integrals-and-convergence-theorems.pdf` — Generalized Integrals and Convergence Theorems
- `reference/b53daf49eb45-hyperplane-projections-of-the-unit-ball-of-l-p-n.pdf` — Hyperplane projections of the unit ball of ℓ_p^n
- `reference/bd62474e88b1-non-central-sections-of-the-regular-n-simplex.pdf` — Non-central sections of the regular n-simplex
- `reference/c2398a987031-paraconsistent-dominated-convergence.pdf` — Paraconsistent Dominated Convergence
- `reference/d0a9f661eb23-plane-sections-of-convex-bodies-of-maximal-volume.pdf` — Plane Sections of Convex Bodies of Maximal Volume
- `reference/daac9fe7d2e3-on-maximal-hyperplane-sections-of-the-unit-ball-of-l-p-n-for.pdf` — On maximal hyperplane sections of the unit ball of l_p^n for p>2
- `reference/dc44da69df46-non-central-sections-of-convex-bodies.pdf` — Non-central sections of convex bodies
- `reference/de5d051e7e09-measure-theory-and-integration-by-and-for-the-learner.pdf` — Measure Theory and Integration By and For the Learner
- `reference/e370bf2a2c26-on-a-reverse-form-of-the-brascamp-lieb-inequality.pdf` — On a reverse form of the Brascamp-Lieb inequality
- `reference/e52716c8c83e-a-cube-slice-that-is-not-a-zonoid.pdf` — A cube Slice that is not a Zonoid
- `reference/e835f5f27173-an-isoperimetric-inequality-for-hyperplane-sections-of-a-con.pdf` — An Isoperimetric Inequality for Hyperplane Sections of a Convex Body
- `reference/f69890810ecb-szarek-and-ball-made-simple.pdf` — Szarek and Ball made simple
- `reference/f79129be94de-non-diagonal-critical-central-sections-of-the-cube.pdf` — Non-diagonal critical central sections of the cube

