# B6 证据（文档与数字）—— 执行者：文档/登记子智能体

> **观测窗口：2026-09-26T04:43–05:10**（本节所有计数都是该窗口内的实测）。
> **纪律**：所有计数写成"**区间 + 观测时刻**"（`G-32`）；**未碰** `src/**`、`scripts/**`、`tests/**`、
> `.noai-*`、`AGENTS.md`、`draft/24`、**`docs/PROPOSALS.md`**；**未写 `reviewers`**（`reviewers_total = 0`）。
> **我推翻了谁**：见 §9（本轮推翻 **4 条文档/工单前提** + **1 条 X-8 判据的可行性**）。

---

## 0. 交付摘要（改动文件与行数）

| 文件 | 行数（观测 05:09:45） | 本轮改了什么 |
|---|---:|---|
| `agentflow/DEVELOPMENT.md` | 1315 | §0.2/§0.3/§0.3b/§0.4/§1.4/§1.5/§4.3/§8.2b/§9.1/§9.2/§9.3 |
| `agentflow/README.md` | 331 | §1 角色表（两根轴 + "唯一联网角色"更正）、§6 开头（`P-11`）、**§6.1（`G-28`）**、**§6.2（`X-5`）**、§4 目录树、§4/§6 的规则号 |
| `agentflow/DESIGN-TOOLS.md` | 390 | 第 49/54/63/67 行所在的 §1（**词表两轴**；工单写 `docs/DESIGN-TOOLS.md` —— 见 §9 第 1 条） |
| `agentflow/docs/TOOLBOX-DRAFT-roles.md` | 224 | §3 前的取值域说明（原 81/82 行）+ `search.harvest` 行（原 107 行） |
| `agentflow/docs/ROLE-SPECS.md` | 2214 | §0.3 工具面 census（`H` 23→22 + **两口径表**）、附录 S2 第 11 行（`G-15`） |
| `D:\Incubator\draft\25-…md` | 471 | 抬头、§10.1（**+`G-46`…`G-50` 与两条口径更正**）、§10.2、§10.3、**§10.5（新）**、`D-4.2`、`D-4.3`、`D-5.1` |
| `D:\Incubator\draft\22-…md` | 2167 | §12 抬头、§12.1、§12.2、§12.3、§12.7.1/§12.7.2 + **§12.32（新）** |
| `agentflow/docs/INDEX.md` | 54 | **未改**（复核后无过期数字/无词表；见 §8） |

---

## 1. `G-30`/`G-32`：工具面与测试的**重跑复算**（逐条命令 + 原始输出）

### 1.1 两个口径（⭐ 工单 §1b-2 要求"每个工具条数必须写明对应哪条装配命令"）

命令（观测 **2026-09-26T04:44:35**）：

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
# （脚本形式：build_registry 两次装配 + Counter）
```

原始输出：

```text
store=None n= 50
  side_effect {'read': 30, 'write_local': 15, 'none': 5}
  external   {'none': 44, 'egress': 4, 'exec': 2}
  needs_approval 18
    A n= 20 {'read': 12, 'write_local': 8} {'none': 17, 'egress': 3}
    B n= 18 {'read': 10, 'write_local': 8} {'none': 17, 'egress': 1}
    C n= 17 {'read': 17} {'none': 17}
    D n= 32 {'read': 21, 'write_local': 6, 'none': 5} {'none': 32}
    E n= 21 {'read': 14, 'write_local': 7} {'none': 19, 'exec': 2}
    F n= 32 {'read': 18, 'write_local': 9, 'none': 5} {'none': 30, 'exec': 2}
    G n= 32 {'read': 18, 'write_local': 9, 'none': 5} {'none': 30, 'exec': 2}
    H n= 22 {'read': 17, 'none': 5} {'none': 22}
with-store n= 55
  side_effect {'read': 32, 'write_local': 18, 'none': 5}
  external   {'none': 49, 'egress': 4, 'exec': 2}
  needs_approval 21
    A n= 20 … B n= 18 … C n= 17 …
    D n= 37 {'read': 23, 'write_local': 9, 'none': 5} {'none': 37}
    E n= 21 … F n= 32 … G n= 32 … H n= 22 {'read': 17, 'none': 5} {'none': 22}
```

⇒ **`50` 与 `55` 是两个口径，已写进 `docs/ROLE-SPECS.md` §0.3 的对照表**（`store=None` ⇒ 50；
含 store 的完整装配 ⇒ 55）。**两数不许互换。**

### 1.2 `cli tools`（含 store 口径）—— 注意 `H` 是 **22**，不是文档里的 23

```powershell
$env:PYTHONPATH='src'; python -m agentflow.cli tools     # 观测 2026-09-26T04:44:31
```

```text
工具总数：55（已装模块 11：table_tools, fs_tools, search_tools, ocr_tools, graph_tools,
        trace_tools, research_tools, verify_tools, attack_tools, doc_tools, review_tools）

各角色工具数：{'A': 20, 'B': 18, 'C': 17, 'D': 37, 'E': 21, 'F': 32, 'G': 32, 'H': 22}
只读角色写工具泄漏：{'C': [], 'H': []}（空 = 正常）
```

⭐ **`H` 由 23 变 22 的原因（不是漂移，是 B3 的直接后果）**：`verify.check_formal` 现在声明
`external="exec"`，被 `for_role` 从只读角色手里结构性剥离。判据（观测 04:44:41）：

```text
registry external!=none: ['ocr.run', 'search.download', 'search.literature',
                          'search.providers', 'verify.check_formal', 'verify.run_experiment']
role_filter_notes = {}
C exec tools: []
H exec tools: []
```

### 1.3 全量测试（**无并发** vs **有并发**，两个观测都留）

| 观测时刻 | 命令 | 原始末行 | 退出码 |
|---|---|---|---|
| 04:43:55 → 04:48:40 | `python -m pytest -q`（`agentflow` 根，无并发） | `1925 passed, 8 deselected, 1 xfailed, 1 warning in 283.86s (0:04:43)` | 0 |
| 04:54:45 → 04:59:39 | `python tools/release_all.py --since 4293989 --only release-check`（其 `tests` 项） | `2 failed, 1948 passed, 1 skipped, 8 deselected, 1 xfailed in 277.76s` | 1 |
| **05:10:23 → 05:15:43** | `python -m pytest -q -p no:cacheprovider`（**收尾复跑**） | `1956 passed, 1 skipped, 8 deselected, 1 xfailed, 1 warning in 318.42s (0:05:18)` | **0** |

⭐ **这是 `G-32` 最好的实证**：同一小时内两次全量得到 `1925 passed` 与 `1956 passed`
（**差 31 条**，退出码都是 0），而两次之间**我一行业务代码都没改** ——
差来自**别的执行体持续往 `tests/` 加用例**。⇒ **任何"实测 N 条测试"都必须带观测时刻**。

⚠️ **`tests/` 的两个失败单跑都绿**（观测 05:00:03）：

```text
python -m pytest tests/test_agent_f_step_outcomes.py -q -p no:cacheprovider
⇒ 3 passed in 0.18s
python -m pytest tests/test_core_audit_efgh.py -q -p no:cacheprovider -k "resolve_accepts"
⇒ 1 passed, 41 deselected in 16.46s
```

⇒ 形态是**全量下的顺序依赖 / 并发态**（`G-27` 族），**且实测同一时刻别的执行体正在改测试文件**
（`tests/test_agent_f_step_outcomes.py` mtime `04:57:39`、`tests/test_lint_rules_r011_dead_vocab.py` `04:59:31`
都在我这次 `release_all` 窗口内）。⇒ 文档里**两个数都写**，并注明口径（`G-32`）。

### 1.4 `tests/` 文件数与结构数（观测 04:48:44 / 05:09）

```text
tests/test_*.py = 89           （文档原写 65）
test function count = 1730     （新口径；文档原有的"1329 个测试函数"已删，因为口径未定义）
data/*.json = 16
src/agentflow/*.py = 40
src/agentflow/tools/*.py = 13
```

---

## 2. `G-31`：`usage_ledger` 的写入方（**文档说"零写入方"，已接线**）

命令与原始输出（观测 04:49）：

```powershell
Select-String -Path src\agentflow\*.py,src\agentflow\tools\*.py -Pattern 'usage_ledger|UsageEntry'
```

关键命中（**写入方 = `TokenMeter.charge`，不是 `agent_*.py`** —— 文档原先那条 grep 的口径是错的）：

```text
tokenmeter.py:20  1. 记：`charge()` 把每一笔（包括零值）写进 `usage_ledger`。
tokenmeter.py:317 def charge(self, c: Charge, *, now: str | None = None) -> dict:
tokenmeter.py:335 with self.store.tx("usage_ledger", "counters", actor=f"tokenmeter:{c.role}",
tokenmeter.py:341 tx.upsert("usage_ledger", row.to_dict(), note=f"charge:{c.scope}")
tokenmeter.py:362 def charge_once(self, c: Charge, *, idem_key: str, now: str | None = None) -> dict:
tokenmeter.py:433 tx.upsert("usage_ledger", row.to_dict(), note=f"charge:{c.scope}")
modelcost.py:275  def charge_reply(meter: TokenMeter | None, reply: Any, *, role: str = DEFAULT_ROLE,
runflow.py:812    charge = charge_reply(
conductor.py:841  # ---- [7] 记账：权威账是 `usage_ledger`，`tasks.tokens/usd` 由它派生
```

⇒ 文档改法：`DEVELOPMENT.md` §9.3 第 5 条 ⇒ **已关闭**，并给出判据指向
（`grep -n 'tx.upsert("usage_ledger"' src/agentflow/tokenmeter.py` ⇒ 两处）。

---

## 3. `README.md` 的"**唯一联网角色**"——**先核实再写**（本轮核实结论：**不成立**）

命令（**真实的 `build_registry`**，观测 **2026-09-26T05:01:28**）：

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
# 脚本：tempfile 建 Store ⇒ build_registry(store=st, workspace_root=..., roles=ROLES)
#       然后逐条打印 s.external != "none" 的工具
```

**原始输出（逐字）**：

```text
ocr.run                      external=egress  effect=write_local  roles=['B']
search.download              external=egress  effect=write_local  roles=['A']
search.literature            external=egress  effect=read         roles=['A']
search.providers             external=egress  effect=read         roles=['A']
verify.check_formal          external=exec    effect=read         roles=['E', 'F', 'G']
verify.run_experiment        external=exec    effect=write_local  roles=['E', 'F', 'G']
```

**核实结论**：
- `external != "none"` 的工具 **6 件**（`egress` 4 件 + `exec` 2 件）；
- 覆盖的**角色集合 = `{A, B, E, F, G}`**（`C` / `D` / `H` 一件都没有）；
- ⇒ **"A 是唯一联网角色"这句话不成立**（`B` 也有 `egress`：`ocr.run`；`E`/`F`/`G` 有 `exec`）。
- **写进文档的口径**：`README.md` §1 的角色表已改成两根轴 + 逐角色外部轴 + 一句
  "**不是唯一联网角色**" + 覆盖集合 + 复跑命令 + "两个工具条数口径不许互换"。

> ⭐ 这一条正是登记子智能体**没核实所以没改**的那一处 —— 本轮把它核实了，结论是**不能写"唯一"**。

---

## 4. `G-31b`：`-m network` 的实测（**已跑绿**，证明什么/不证明什么）

沿用主控实测（观测 **2026-09-26T02:42:12 → 02:42:41**；原始输出 `temp/pytest-network-run1.txt`）：

```text
start=2026-09-26T02:42:12.7676711+08:00
exit=0
........                                                                 [100%]
8 passed, 1873 deselected in 28.42s
```

采集清单 `temp/network-collect.txt` 的 8 条（**全部在 `tests/test_providers_online.py`**）：

```text
test_crossref_all_modes_do_not_400[broad] / [topical] / [precise]
test_openalex_all_modes_return_something[broad] / [topical] / [precise]
test_precise_results_are_on_topic
test_openalex_returns_wellformed_candidates
```

分域现状（`temp/network-and-key-status.md`）：

```text
api.crossref.org        200（1734 B）      通，返回真内容
api.openalex.org        200（8068 B）      通
export.arxiv.org        200（1844 B）      通
api.semanticscholar.org 429（174 B）       可达但被限流
api.unpaywall.org       404（207 B）       可达（假 DOI ⇒ 服务端语义响应）
github.com              EXC CERTIFICATE_VERIFY_FAILED（unable to get local issuer certificate）
```

⇒ **文档写"8 条已跑绿"**，并**同时**写明：
- **证明**：Crossref + OpenAlex 两条真实 HTTP 通路可用；"`precise` 恒为 0"与"Crossref `select` 全 400"
  这两个**只有真实往返才能发现**的缺陷被这 8 条守住；
- **不证明**：**不是"所有域都通"**（Semantic Scholar 429 ⇒ 只能验"限流被正确处置"）；
  **`ocr.run` 的 `egress` 通路未被覆盖**（`github.com` 证书链验证失败 ⇒ easyocr 的 ~100MB 模型下不来）；
  也无 LLM/provider 端到端（无真实 key）。

---

## 5. `X-5`：清单 glob / 唯一路径 / 台账条目 / 类别 **四数**（判据三条命令）

### 5.1 清单侧（观测 04:43:06 与 05:01）

```powershell
cd D:\Incubator\agentflow
$globs = Get-Content .noai-paths | Where-Object { $_ -match '^[^#\s\[]' } | ForEach-Object { ($_ -split '\s+')[0] }
$globs.Count ; ($globs | Select-Object -Unique).Count
```

```text
GLOB_COUNT=21
UNIQUE_COUNT=18
```

21 条逐条（原始输出）：

```text
src/agentflow/providers.py      src/agentflow/dedup.py        src/agentflow/extract.py
src/agentflow/tools/verify_tools.py  src/agentflow/quoteverify.py
src/agentflow/dedup.py          src/agentflow/providers.py    src/agentflow/schema.py
src/agentflow/store.py          src/agentflow/schema.py       src/agentflow/release_check.py
scripts/release_check.py        tools/release_all.py          pyproject.toml
src/agentflow/tools/__init__.py src/agentflow/tools/base.py   src/agentflow/verify.py
src/agentflow/interactions.py   .noai-approvals.json          .noai-paths        AGENTS.md
```

存在性（原始输出）：

```text
src/agentflow/release_check.py  exists=False      ← 唯一不存在的（刻意先登记路径）
（其余 17 条 unique 全部 exists=True）
```

`[category:` 行数 = **7**。

### 5.2 台账侧（观测 04:43–04:49）

```text
.noai-approvals.json: ledger_version=1, entries len=16
逐条（reviewers 全部 = 0）：
.noai-paths | AGENTS.md | pyproject.toml | scripts/release_check.py | src/agentflow/dedup.py |
src/agentflow/extract.py | src/agentflow/interactions.py | src/agentflow/providers.py |
src/agentflow/quoteverify.py | src/agentflow/schema.py | src/agentflow/store.py |
src/agentflow/tools/__init__.py | src/agentflow/tools/base.py | src/agentflow/tools/verify_tools.py |
src/agentflow/verify.py | tools/release_all.py
```

### 5.3 三条判据命令的原始输出

**判据 1 —— 一致性**（观测 05:08:58，exit 0）：

```text
一致：.noai-paths 与 AGENTS.md 的清单逐条相同
```

**判据 2 —— 台账**（观测 04:49:14）：

```text
[requires_human] required_approvals=2
requires_human：命中 16 条禁改区路径，其中 **16 条未获批准**（insufficient_reviewers 16 条）⇒ 必须由人编写或人逐行走查，并需要 2 名 reviewer 批准。
```

⇒ **16 条 / 欠签 32 / stale 0**。

**判据 3 —— 差集逐条核实**（观测 04:44 左右）：

```text
python scripts/noai_gate.py --check-approvals --paths .noai-approvals.json
⇒ requires_human：命中 1 条 …（ledger_self_approval 1 条）
python scripts/noai_gate.py --check-approvals --paths src/agentflow/release_check.py
⇒ requires_human：命中 1 条 …（unregistered 1 条）
```

⭐⭐ **差集只有 2 条**（`18 − 16`）：`src/agentflow/release_check.py`（盘上不存在）与
`.noai-approvals.json`（**台账不能批准自己**）。
**`21 − 18 = 3` 是同一文件重复登记**（`dedup.py` / `providers.py` / `schema.py`）。
⇒ **工单 §X-5 的候选清单猜错了两处**：`.noai-paths` 与 `AGENTS.md` **各自都有台账条目**；
"差集是 5 条"**不成立**（是 2 条）。见 §9 第 2 条。

---

## 6. `X-1`：发布检查还会不会改写**被跟踪**文件

| 观测 | 命令 | 原始输出 | 判读 |
|---|---|---|---|
| 04:55:14 | `Get-FileHash .release-lint.json` → 跑 `python scripts/lint_rules.py` → 再取 hash | `before=D6C5D70D…` `after=D6C5D70D…` `changed_by_lint=False` | ✅ **lint 不写它** |
| 04:54:55 | `python scripts/release_check.py --skip tests` | `发布检查总判定：FAIL pass=5 fail=1 unknown=1`；`git status --porcelain -- agentflow/.release-lint.json` ⇒ **空** | ✅ **`release_check` 的 lint 项也不再写它**（产物挪到 `temp/release-lint.json`） |
| 04:48 | `git ls-files agentflow/data` + `git status --porcelain -- agentflow/data` | `tracked count = 17`；status ⇒ **空** | ✅ 与工单口径一致：**只有 mtime 变、内容未变** |
| 04:55 | `git status --porcelain -- agentflow/demo/run/data` | **`M` 5 个文件**（`concepts.json` / `events.jsonl` / `literature.json` / `relations.json` / `search_requests.json`） | ⚠️ **真的改了内容** |
| 04:55 | `git diff --stat -- agentflow/demo/run/data` | `5 files changed, 79 insertions(+), 79 deletions(-)`；`concepts.json` 的 `created_at/updated_at` 由 `2026-09-24T08:13:00` 刷成 **`2026-09-26T04:50:37`** | ⚠️ **时间戳字段被刷新**（`events.jsonl` 全 61 行重写） |

⭐ **主控原先的落点判断"错了一半"**：不是 `lint_rules.py` 写、是 **`release_check` 的 lint 步写** ——
**以实测为准**（`temp/X1-lint-side-effect.txt` / `temp/X1-releasecheck-linter.txt` 各有一份前后 hash）。
⭐ **未核实**：`agentflow/demo/run/data/*` **是谁写的**（全仓 `grep 'demo/run'` 只命中 3 处**注释**；
`cli.py` 的 `demo` 子命令默认 root 是**包外**的 `parents[2]`）⇒ 我**不写成"某条用例写的"**。
⭐ **`X-1` 的负控（连跑两次 `release_all` ⇒ 无 `M`）本轮未跑** ⇒ 如实写"未跑"，**不写"通过"**。

### `X-2` 的现状（观测 04:43–05:09）

```text
D:\Incubator 根：entries = .git .pytest_cache agentflow draft temp test      （无 pytest-of-*）
D:\Incubator\agentflow：无 pytest-* 目录
D:\Incubator\.pytest_cache   存在（LastWriteTime 2026/9/25 17:55:35）
.gitignore 第 3 节：.pytest_cache/ 与 pytest-of-unknown/ 均已排除
git check-ignore -v agentflow/.pytest_cache ⇒ .gitignore:40:.pytest_cache/
agentflow/.gitignore 不存在（Test-Path=False）；git ls-files 里只有根 .gitignore
pyproject.toml 无 --basetemp；tests/conftest.py 无 basetemp
```

⇒ **"跑一次全量 ⇒ 仓库根不新增目录"这一条本轮观测成立**（跑完 1925 passed 之后，仓库根仍无 `pytest-of-*`）；
⚠️ **"钉 basetemp"这一步没做**（成因仍在：用户名解析失败时 basetemp 会落 cwd）。

---

## 7. `X-8`：`draft/22` §12 排期表的判据（**原样输出**）

### 7.1 判据命令与原始输出（观测 **2026-09-26T05:08:54**）

```powershell
cd D:\Incubator
$n1 = '在' + '飞'                                       # 刻意拼出来：见下"悖论"
Select-String -Path "draft\22-企业级交付与竞争力方案（200万预算）.md" -Pattern $n1 -SimpleMatch
```

**原始输出：空（0 行）**

```text
pattern=在飞                          count=0
pattern=与在[飞]包并行|并行[？]        count=0
pattern=\| ❌.*排                     count=0
```

（三条一起跑，观测 05:08:54。）

### 7.2 ⭐ 一条**必须点名的判据可行性问题**（我推翻了工单 §X-8 的一个隐含前提）

原文判据是"**表里不再出现"在飞"字样**（贴 `rg` 原样输出）"。**它的字面版本与它自己的证据冲突**：
**"贴出 `rg` 原样输出"这条要求，必然把被判据的词写进同一份文件** ⇒ 若把
`... -Pattern '在飞'` 原样贴进 `draft/22`，那么文件里**永远至少有一处命中**（那条命令本身），
判据**结构上不可能为 0**。这不是文字游戏：**判据与其证据同处一个文件时，"0 命中"必须靠
"把被搜的字面量拼出来"（`'在' + '飞'` 或字符类 `[飞]`）才能成立**。
⇒ 我的处置：**命令用拼接写成，于是判据真的为 0**；并在 §12.32.1 里把这件事**写出来**
（而不是贴一条自己会命中的命令、再声称 0）。**判据本身已完成：0 命中。**

### 7.3 改动前后对照

| 命令 | 改前 | 改后 |
|---|---:|---:|
| `-Pattern '在' + '飞'`（拼接） | **17 行** | **0 行** |
| 六张表的列头旧写法 | 6 处 | **0 处** |
| 排期表"结论列"的 `⇒ 排…` / `❌ …排其后` | 12 处 | **0 处** |

**B3 之后真实存在的约束（已写进文档）**：① **不可逆操作要备份**（`SCHEMA_VERSION` / `LOCK_ORDER` /
`_atomic_write` / ID 分配 / **删词表取值** / 迁移）；② **禁改区改动要人审**（FC-27 ⇒ 2 名 reviewer）。
**"人审按批次付"保留**（它不是文件级互斥，是成本口径）。

---

## 8. 逐条落点（工单 §1 / §1b / §1c）

| 条 | 状态 | 落点 |
|---|---|---|
| `G-30` | ✅ 已改 | `DEVELOPMENT.md` §0.2（加"本表是历史"警示 + 逐行"现在"）、§0.3（13+1 条基线全部重跑）、§1.4（`H` 23→22 + 两轴）、`README.md` §1（角色表两根轴） |
| `G-31` | ✅ 已改 | `DEVELOPMENT.md` §9.3 第 5 条（写入方 = `TokenMeter.charge` + `grep` 判据） |
| `G-31b` | ✅ 已改 | `DEVELOPMENT.md` §9.3 第 12 条（8 passed + 证明/不证明） |
| `G-32` | ✅ 已改 | `DEVELOPMENT.md` **§0.3b（新）**：规矩本身（注明它是 `D-1.6` 的要求）|
| `X-1` | ✅ 已改（部分未核实） | `draft/22` §12.32.4 + `DEVELOPMENT.md`（`X-1` 的处置在 `X-2` 行附近的口径）|
| `X-2` | ⚠️ 部分 | 现状写进 `draft/22` §12.32.8；**`--basetemp` 未钉**（未做） |
| `X-5` | ✅ 已改 | `README.md` **§6.2（新）** + `DEVELOPMENT.md` **§1.5（新）** + `draft/25` **`D-4.2`**（差集逐条）|
| `X-7` | ❌ **未做** | `temp/README.md` **不在授权写域内** ⇒ 只登记（`draft/22` §12.32.8）|
| `X-8` | ✅ 已改 | `draft/22` **§12.32（新）** + §12/§12.1/§12.2/§12.3/§12.7 的逐处标注 |
| `G-15` | ✅ 已改 | `docs/ROLE-SPECS.md` 附录 S2 第 11 行（`104 passed / 0 skipped`、`Length=69446`）|
| `G-16` | ✅ 已改 | `DEVELOPMENT.md` §9.1 的 **FC-17** / **FC-19** 两行 + §9.2 抬头 + §9.2 表（`FC-17`/`FC-19` 两行删除、"完全未落地"⇒ 0 条）|
| `P-16` | ✅ 已改 | `DEVELOPMENT.md` §4.3 第 1 项（**六件套逐件**）+ 第 13 项（`R006` → **`R010`**）|
| `P-11` | ✅ 已改（选 (b)） | `README.md` §6 开头（八项逐项 + "验收由 `acceptance` 步承担" + (a) 已否决的理由）|
| `G-28` | ✅ 已改 | `README.md` **§6.1（新）** + `DEVELOPMENT.md` **§8.2b（新）**（总判定 `FAIL`；`noai` 的红 = 待 2 名 reviewer 签字）|
| §1b 词表三处 | ✅ 已改 | `DESIGN-TOOLS.md` §1（原 49/54/63/67 行所在）、`README.md:38` 原处、`TOOLBOX-DRAFT-roles.md` 原 81/82/107 行 |
| §1c-1 `P-23` 口径 | ✅ 已写 | `draft/22` §12.32.3 + `draft/25` §10.1（**未写 `PROPOSALS.md`**）|
| §1c-2 `G-24③` 口径 | ✅ 已写 | 同上 |
| §1c-3 `proved` ↔ `verified` | ✅ 已登记为 **`G-50`** | `draft/22` **§12.32.6** + `draft/25` §10.1（**未写 `PROPOSALS.md`**）|

**`docs/INDEX.md`：未改**。复核结论：它没有"工具条数/测试条数/清单条数"这类会漂的实测数字，
也没有 `network` 词表；唯一提及 `release_check.py` 的八项与 `P-11` 的那段
（"`release_check.py` 在禁改区，加一项要人审，见 `PROPOSALS.md` P-11"）**与 B6 后的新口径一致**（选 (b) 更强化了它）。

---

## 9. ⭐ 我推翻/更正了谁（本轮 5 条）

| # | 谁说的 | 盘上事实 | 处置 |
|---|---|---|---|
| 1 | 工单 §1b-3 写 `docs/DESIGN-TOOLS.md` | **该文件不存在**（`docs/` 下 13 个文件里没有它）。真正有那 4 行 `network` 词表的是 **`agentflow/DESIGN-TOOLS.md`**（工单给的行号 49/54/63/67 **与它逐字吻合**） | 改了 `agentflow/DESIGN-TOOLS.md`（它在授权写域内），并在此点名 |
| 2 | 工单 §X-5 的候选差集（`src/agentflow/release_check.py`、`.noai-paths`、`AGENTS.md`、`.noai-approvals.json`、一处重复 glob）⇒ 暗示 **5 条** | **差集只有 2 条**：`src/agentflow/release_check.py`（盘上不存在）与 `.noai-approvals.json`（不许自批）。**`.noai-paths` 与 `AGENTS.md` 各自都在台账里**（有 `--baseline` 记录） | 文档按 2 条写 |
| 3 | 工单 §1c-2 / `G-24` 原文说 `cancellation.py` 的 `"user"` "代码里根本没有" | B5a 已核实**代码里真实存在** ⇒ **登记册错一条** | 写进口径更正（`draft/22` §12.32.3 + `draft/25` §10.1）|
| 4 | 工单 §1c-1 把 `capabilities:UNKNOWN_SIDE_EFFECT` 当"预留取值" | 它是**模块级常量**（`UNKNOWN_SIDE_EFFECT = "unknown"`），**不在** `SIDE_EFFECTS` 词表里 | 写进"**不许登记为预留**"（同上）|
| 5 | 工单 §X-8 的判据"表里不再出现『在飞』字样（**贴 `rg` 原样输出**）" | **该判据与它的证据互斥**（见 §7.2）：贴命令 ⇒ 命令自身即命中 ⇒ 结构上不可能为 0 | 用**字面量拼接**写命令，使判据真的为 **0**；并在 §12.32.1 把这件事写出来 |

**另有一处是我自己的更正**（不是推翻别人）：`draft/22` §12.1 的 `N-7` 行原文写
"今天 `14 0`，走查后 `14 28`" —— 按 §10.2 的口径应是 **`16 0` / `16 32`**；已改。

### 9.1 `draft/25` 的另一处漂移（我点名了它，但它不在工单里）

`draft/25` §1 的抬头原文写"`docs/PROPOSALS.md` 全部 **75 条**登记（P 1..25 / G 1..40 / N 1..10）"
—— 现在是 **P 1..26 / G 1..49 / N 1..10**（另有 `G-50` 未入册）。
**两处都在同一份文件里**（抬头 vs §10.2），属于同一类"交付标准文档自身的漂移"。
已在抬头加警示（不删原值）。

---

## 10. 未核实 / 未做（**不许读成"已通过"**）

| # | 项 | 状态 |
|---|---|---|
| 1 | `agentflow/demo/run/data/*` 的写者 | **未核实**（见 §6）|
| 2 | `X-1` 的负控（连跑两次 `release_all` ⇒ 无 `M`） | **未跑** |
| 3 | `G-46` 的 `--changed-file` 通路是否同形受逗号输入影响 | **未核实** |
| 4 | `ocr.backends` 的 `external` 取值（P-13 §4.3 第 9 条） | **仍未裁决** |
| 5 | `UNKNOWN_SIDE_EFFECT` 是否单列条目 | **交人裁决**（本轮只做口径更正）|
| 6 | `X-7` 的 `temp/README.md` | **未做**（不在授权写域）|
| 7 | `X-2` 的 `--basetemp` 钉法 | **未做**（现状已测）|
| 8 | `release_all` 的 `acceptance` / `repro` / `role-specs` / `coverage` / `per-file` 五步 | **未跑**（本轮只跑 `--only release-check`）⇒ 记 `unknown`，**不是通过** |
| 9 | 是否要把 `G-50` 写进 `PROPOSALS.md` | **不写**（登记册由登记子智能体收口；落点 `draft/22` §12.32.6 + `draft/25` §10.1）|

---

## 11. 改完必跑的三条（**原始输出**）

观测 **2026-09-26T05:08:58**（全部在不改写代码的文档改动之后）：

```text
1) python -m pytest tests/test_proposals_register.py tests/test_role_specs_complete.py -q -p no:cacheprovider
   ⇒ ....................... [100%]
     23 passed in 2.72s                 exit=0

2) python tools/verify_role_specs.py
   ⇒ [OK ] §M 主控（Conductor）   行 1851 子节 10 工具条数 []
     （其余角色节全 [OK]，含 §H 行 1667 工具条数 [22]）   exit=0

3) python scripts/lint_rules.py
   ⇒ [linter] error 0 / warning 0 / info 21        exit=0
     （规则 11 条；R004/R006 已退休。⚠️ warning 由 1 变 0、info 由 14 变 21 是
       **并发执行体在 04:47–05:09 之间改了 lint_rules.py 的判据**，
       不是我改的 —— 我只改了 .md；`error 0` 这一条判据全程成立）

4) python -m pytest -q -p no:cacheprovider        （收尾复跑，观测 05:10:23→05:15:43）
   ⇒ 1956 passed, 1 skipped, 8 deselected, 1 xfailed, 1 warning in 318.42s (0:05:18)
     exit=0   ← 比 04:48 那次多 31 条（并发执行体加的用例），**不是我加的任何东西**
```

另附一致性判据（观测 05:08:58）：`python scripts/noai_gate.py --check-consistency`
⇒ `一致：.noai-paths 与 AGENTS.md 的清单逐条相同`，`exit=0`。

⭐ **`PROPOSALS.md` 指针行复核**（工单禁写项，观测 05:09:45）：行数 **4602**，
`P 1..26 / G 1..49 / N 1..10`（gaps 全空），**本轮未写入一个字节**。

---

## 12. 对 `DESIGN-TOOLS.md` §1.1 的一处**我自己也写粗了**的更正（观测 05:10:26）

第一版我把那一列的"表 CRUD / 文件 CRUD"两组照抄成 `write_local`（沿用原文），
**实测推翻了它**：一个 CRUD 组里读写是混的。实测（`build_registry(store=…)` 逐条打印）：

```text
table.create/update/delete = write_local ; table.list/get/count/schema/search = read  （external 全 none）
fs.write/delete/move        = write_local ; fs.list/read/stat/search            = read  （external 全 none）
ocr.detect_text_layer = read ; ocr.run / ocr.backends = write_local（external: run=egress，其余 none）
research.list_gaps = read ; research.submit_gap / write_note = write_local（external 全 none）
graph.* / trace.*   = read（external 全 none）
```

⇒ 已按实测重写该表，并加一句"**第一根轴也不是全 `write_local`** ——那两行在写作时就写粗了"。
**教学点**：这条正是"**照抄旧表 = 把旧表的错一起抄进来**"的实例；`G-32` 要求"每个数字都真跑一次"
在这张表上**立刻抓出了一个原文错误**（原文那两行连"第一根轴"都不对）。

