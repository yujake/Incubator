# 文献种子包（历史真机下载）

这是 25 份历史真机工作区里下载成功、且抽读无乱码的 PDF，共 17845452 字节。
它们只是文件，不是入库记录。

## 为什么不能直接入库

种子口径只回答两件事：下载真的成功了、正文真的抽得出来。它不回答
「与当前研究相关吗」「该不该收录」。入库（分配 lit_id、写 literature 行）
是 A 的判收动作，业主明令这批种子不直接入库。所以投放只把文件放进
工作区的 library/，绝不写 data/literature.json 或任何台账。

## 怎么投放

新建工作区时加显式开关（默认关）：

    agentflow start --project <名字> --mode cold --task "..." --seed-literature

或：

    agentflow init --root <新工作区> --seed-literature

投放只做三件事：把 files/ 里的 PDF 原样复制到 <工作区>/library/、
在工作区根落一份 SEED-README.md、别的什么都不写。已有 data/ 的热启动不投。

## 谁判收

A。A 必须走候选链，不许把这批文件当已入库（顺序与工具名如下，一步都不能省）：

1. **发现（只发现、零写入）**：`search.ingest_local(books_dir="library", dry_run=True)` —— dry_run=True 只发现、零写入：它只读盘上文件、算同一个 sha256 / 页数 / 文本层，`lit_candidates` / `literature` / 两个台账一个字节都不写；读数里的 `count` / `books[]` 就是候选清单（`ingested` 是「会登记」的预告，不是入库）。
2. **建候选（只对用户点名的那些）**：用户提示词里点名的文件/目录由 M 逐字记在工作区根的 `RELIABLE-REFERENCES.json`（`{"paths": ["a.pdf", "b/"], "verbatim": "<用户原话>"}`）；**只有清单里的才可入库**，清单外的只能当研究参考。逐份 `lit.stage_add(request_id=<委托号>, entries=[{title: …, url: <发现读数里那一份的盘上路径>, relevance: "工作区里已有的本地文献，不是检索来的"}])` —— 这一步只写候选表，`literature` 仍是 0 行。
3. **判收**：`lit.stage_list` 回读 → `text.extract(lit_id="cand:<槽位>")` 抽正文 → `fs.read` 读到那份 `.txt`（读到同一版抽出来的正文）→ `lit.admit(items=[{slot, availability: "readable"}])`（**`content_read` 才算过**，机器现算不是自报）→ 逐委托 `lit.admit_all`（提交、回填号、清表）。
4. **收进 `literature` 之后**：下一步派 B 的 `run_once` 整理（抽概念、建关系、落命题线索）。

⚠️ **非 dry 档跳过判收、不要用**：`search.ingest_local` 不带 `dry_run=True` 时，它把盘上文件直接写成 `literature` 行、跳过了判收 —— 那等于把「下载成功」冒充成「判收过了」，收进来的是一批没有判据的文献。何况未在 `RELIABLE-REFERENCES.json` 里点名的文件会被它按 `not_declared_reference` 受控拒（零写入）：未点名的只能当研究参考，不入库。

收进 `literature` 之后才有 lit_id，B 的 `run_once` 才处理得到它们。

## 怎么复算

在 `agentflow/` 下跑：

    python scripts/seed_corpus.py --verify

（或在仓库根跑 `python agentflow/scripts/seed_corpus.py --verify`。）
它按 MANIFEST.json 逐份重算 sha256、字节数、抽读字数与 U+FFFD；
任何一份被改动、缺失或字数对不上都以退出码 1 结束。

## 口径

- 下载成功：download.status == "ok"、bytes > 0、文件在盘上、sha256 与台账一致。
- 无乱码：extract_text 抽到的内容确实是 PDF、正文 >= 200 字符、0 个 U+FFFD、
  至少 20 个长度 >= 4 的完整英文词、英文字母占非空白字符 >= 0.25。
  HTML 落地页 / 扫描件（无文本层）不进种子：投放目录按 *.pdf 收编。
- 去重：dedup.literature_keys（DOI -> 标题+年 -> 标题|*）。
- 血统：默认只收 lp-ball* / dct-min* / abelian-smoke*（这十几轮真机）；
  审阅 / 演示 / 探针工作区不进种子。

逐份来源、判重理由与读数见 MANIFEST.json。
