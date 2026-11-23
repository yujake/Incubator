# seed/ —— 文献种子包

> 这是**历史真机下载成功、且抽读无乱码的 PDF** 的留档。它们**只是文件，不是入库记录**：
> 放进来不改变任何台账，判收归 A。

## 谁读

要给新工作区投放种子的人，以及要复核"这批 PDF 还能不能用"的人。

## 里面是什么

| 路径 | 是什么 | 谁生成 |
|---|---|---|
| `literature/files/*.pdf` | 种子 PDF 本体（文件名 = `<sha256前12>-<标题 slug>.pdf`） | `scripts/seed_corpus.py`（从历史真机 `library/` 挑） |
| `literature/MANIFEST.json` | 逐份来源、sha256、字节数、抽读读数、去重选择与理由 | 同上 |
| `literature/README.md` | **投放与判收的口径**（怎么投、谁判收、怎么复算）。先读它 | 人 |

## 怎么用（命令在 `agentflow/` 下跑）

```powershell
# 复算：按 MANIFEST.json 逐份重算 sha256 / 字节 / 抽读字数 / U+FFFD；任何一份不符 ⇒ 退出码 1
python scripts/seed_corpus.py --verify

# 投放：新建工作区时加显式开关（默认关；只复制文件到输入区 + 落 SEED-README.md，不写台账）
python -m agentflow.cli --root D:\Incubator\temp\ws init --seed-literature
python -m agentflow.cli --root D:\Incubator\temp\ws start --mode cold --task "…" --seed-literature
```

## 边界

- **种子不等于已入库**：`data/literature.json` 一行都不会被写。A 必须走候选链判收，
  顺序与工具名逐字见 [`literature/README.md`](literature/README.md)（那份文件与生成器
  逐字对拍，别顺手改它）。
- **投放落点是工作区根的输入区 `reference/`，不是已登记书架 `library/`**：
  `library/` 里只放被 `literature` 行引用到的文件；种子进去了就是书架结构异常
  （业主 2026-11-22：「为什么你直接往library里塞文献？这会导致A侧维护的文献库结构异常」）。
  `SEED-README.md` 也落在 `reference/` 里。
- 只收 `*.pdf`；HTML 落地页 / 扫描件（无文本层）/ 抽读乱码的不进种子。
- 去重口径是 `dedup.literature_keys`（DOI → 标题+年 → 标题|*）；逐份理由在 `MANIFEST.json`。

## 邻居

上游：`../scripts/seed_corpus.py`、历史真机的 `projects/*/library/`（不入库）。
下游：`../src/agentflow/seedinject.py`（投放实现）、`../src/agentflow/agent_a/`（判收）。
