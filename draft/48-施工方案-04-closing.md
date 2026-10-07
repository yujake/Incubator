# draft/48 施工方案 04：`src/agentflow/closing.py`

> 本文件把**已经完成**的逐文件施工级调查（`draft/46-施工级调查-04-closing.md`）转写成**可执行施工方案**。
> 本文件**不新增任何调查结论**：所有"改哪儿、怎么改、代价、会红什么"都来自 `46-04` 与 `44/47/43-C`；
> 本文件只把它们按"一条一个块、块内固定六项"重排，并补上**本次确认**的行号与**本次现算**的基线。
> 本文件只写这一个文件：不改 `agentflow/src/`、不改工作区、不跑 pytest / 模型 / 网络。

---

## 文件头

### 范围

| 项 | 内容 |
|---|---|
| 唯一施工对象 | `D:\Incubator\agentflow\src\agentflow\closing.py`（盘上 **2087 行** `[本次现算：`len(src.splitlines())==2087`]`） |
| 直接调用点（本方案一同交代，不一定本批改） | `src/agentflow/tools/conductor_tools.py` 的两个验收入口（`conductor.acceptance:813/838-875`、`conductor.closing:930-998`）、`src/agentflow/cli.py:2082-2098`、`src/agentflow/reviewaccept.py:105/451/476-478/506`、`src/agentflow/statusreport.py`（今天零引用） |
| 覆盖条目 | **E-04a · E-04b · E-05 · E-06（附件半 / 九节半）· E-08 · S-05a · S-05b · S-05c · F-06 · CC-03 · CC-05 · CC-06 · EE-05 · EE-10**（共 14 个块；E-04 按硬纪律拆成 a/b 两条） |
| 本文件不覆盖 | E-07（签名覆盖 `revised`）/ E-15（`statusreport` 接管现场读数）/ CC-01 / CC-02 / CC-09 / P-03 / F-01 / EE-12（它们是本组的**依赖**，只在"依赖与批次"里点名） |

### 依据清单

| 文件 | 本方案用它的哪一部分 |
|---|---|
| `D:\Incubator\draft\46-施工级调查-04-closing.md`（700 行） | §1 顶层对象与 30 档起始行、§2.1–§2.11 逐改动点、§3 验收表真实用法基线、§4 调用面、§5 可行性与依赖图、§6.1 会红的既有测试、§6.2 负控、§6.3 真机回放命令与逐格预测、§6.4 不可逆点、**§6.5 不可行/高风险五条判定**、§7 边界 |
| `D:\Incubator\draft\44-裁定登记册：全部待裁条目（分6批）.md` | **§19 续二 J-17…J-24**（逐条裁定与同批关系） |
| `D:\Incubator\draft\47-子代理报告登记与证据可信度分级.md` | §0 三级标记（`[我复核]`/`[子代理]`/`[判断类]`）、§2 第 20 组（`ARTIFACTS` 4575 行、抽样 77 ok/3 changed；分根全量仍是 `[子代理]`）、§3-C2（`closing.py` **不在** FC-27 清单）、§3-C12/J-24（EE-10 措辞收窄）、§4 未复核清单、§5 人裁点 |
| `D:\Incubator\draft\43-旧设计调查-C-两套评审口径.md` | **C-01…C-16**：C-03（30 档同处一表、两处时代分界注释、一行坏⇒全表坏）、C-04/C-05（同名两套算法）、C-06（`manuscript_edited` 唯一要只读基线）、C-10（报告九节两套判据、`reviewaccept.py:117` 起点偏移）、C-16（第七格/八环/`na` 出口/声明面缺 `c_analysis_runs`） |
| `draft/46-05` §5.3 | CC-06 删 `reviewaccept.py`（555 行）会红的清单 |
| `D:\Incubator\agentflow\AGENTS.md` / `.noai-paths` | 禁改区名册（用于"边界"一栏） |

### 口径声明（两根工作区根）

**任何读数必须标明是哪个根。本方案的默认口径如下，凡例外逐处标注。**

| 代号 | 盘上路径 | 实测目录数 | 验收表 | `RENDER-ANCHOR.json` | `REPORT.md`（`out/review/`） | `ARTIFACTS.jsonl` |
|---|---|---:|---:|---:|---:|---:|
| **根 A**（=`46-04` 的"根 A"、`43-C` 的 `ag`） | `D:\Incubator\agentflow\projects` | **58** `[本次现算]` | **33**（全在根 A） | 32（`46-04` §1） | **46** `[本次现算]` | 57 个目录（`46-04` §2.10） |
| **根 B**（=`46-04` 的"根 B"、`43-C` 的 `in`） | `D:\Incubator\projects` | **23** `[本次现算]` | **0** `[本次现算]` | 8（`46-04` §1） | **0** `[本次现算]` | 8 个目录（`46-04` §2.10） |

四条口径纪律：

1. **"33 份表 / 204 行"这一族统计只代表根 A。** 根 B **0 份**验收表（`46-04` §7.5、`43-C` §3 同）。
   本方案凡写"真机表"而未标根者，均指根 A；凡写"两根合计"者逐处点名。
2. **根 B 的 8 份 `ARTIFACTS.jsonl` 只用于 EE-05 的完整性读数**（`46-04` §2.10/§7.5），
   不参与任何"验收表逐格"统计。
3. **回放一律 `sid=None`（CLI 口径）**：`46-04` §7.7 记着这条边界 —— 六格 `user_pending` 全 `pass`，
   与 `conductor.closing` 走 `sid=<这一趟>` 的差异**本次未逐趟核对**。
4. **行号口径**：全部按**盘上当前版本**。`46-04` 的行号与盘上当前版本一致（`46-04` §序言：`closing.py` 无未提交改动）；
   本方案另用 `read`/AST 复核了本方案引用到的每一个关键锚点，逐处标 `[本次确认]`。

### 本文引用的分级（照 `draft/47` §0）

- `[46-04 §Y]` = 直接照抄 `46-04` 的读数（`46-04` 本身是 `[子代理]` 级，`draft/47` §1）。
- `[本次现算 + 命令]` = 本方案用只读命令独立复算过（命令原文在 §0）。
- `[判断类]` = 可行性与批次取舍，不是测量值。

---

## §0 基线（开工前必须逐条对齐）

### 0.1 常量与词表 `[本次现算 + 命令]`

命令（workdir `D:\Incubator\agentflow`，`$env:PYTHONPATH="D:\Incubator\agentflow\src"`）：

```powershell
python -B -c "from agentflow import closing as CL; print(len(CL.LEG_CHECK_KINDS), CL.DEFAULT_CHECKS, len(CL.RESEARCH_CHAIN_GROUPS), len(CL.REPORT_SECTIONS), CL.ATTACHMENT_FIELDS, CL.SPLIT_MARKERS, CL.REVIEWED_DOC_STATUSES, CL.ACCEPTANCE_CHECKS_NAME)"
```

读数：

| 项 | 值 | 落点 |
|---|---|---|
| `LEG_CHECK_KINDS` | **30 档** | `closing.py:80-244` `[46-04 §1.1]` |
| `RESEARCH_CHAIN_GROUPS` | **8 环 20 档** | `closing.py:272-319` `[46-04 §1.1]` |
| 8 环标签（逐字） | `立题` / `检索（真的取回）` / `算或造` / `想（猜想或判决性证据）` / `看（关系分析）` / `攻（攻坚推进）` / `交（手稿落盘）` / `闭（请求闭环）` | 同上 |
| `DEFAULT_CHECKS` | **7 格**：`anchor` / `contradictions` / `load_bearing` / `report_shape` / `user_pending` / `substance` / `acceptance` | `closing.py:49` `[本次确认]` |
| `REPORT_SECTIONS` | **9 节** | `closing.py:1415-1425` |
| `ATTACHMENT_FIELDS` | `("origin=own_result", "依据", "sha")` | `closing.py:1428` `[本次确认]` |
| `SPLIT_MARKERS` | `("我们补的", "原文的")` | `closing.py:1431` `[本次确认]` |
| `REVIEWED_DOC_STATUSES` | `("accepted", "revised")` | `closing.py:252` `[本次确认]` |
| `ACCEPTANCE_CHECKS_NAME` | `out/paper/ACCEPTANCE-CHECKS.json` | `closing.py:76` `[本次确认]` |

顶层对象行号（AST 复核 `[本次现算]`，与 `46-04` §1.1/§1.2 一致）：
`research_chain_gaps:322-364` · `citation_fit:395-467` · `_leg_reading:470-1126` ·
`_acceptance_unknown:1129-1142` · `_check_acceptance:1145-1401` · `resolve_under_workspace:1530-1553` ·
`_check_report_shape:1902-1942` · `check_closing:2044-2078` · `tri_state_exit_code:2081-2087`。

### 0.2 33 份 `ACCEPTANCE-CHECKS.json` 逐格 = 32 fail / 1 unknown / 0 pass `[本次现算 + 命令]`

命令：

```powershell
python -B -c "
import pathlib, collections
from agentflow import closing as CL
from agentflow.store import Store
files = sorted(pathlib.Path('projects').glob('*/out/paper/ACCEPTANCE-CHECKS.json'))
c = collections.Counter()
for p in files:
    rep = CL.check_closing(Store(p.parents[2]), project_dir='.', checks=('acceptance',))
    c[rep.status.get('acceptance')] += 1
print(len(files), dict(c))"
```

读数：`files 33 {'fail': 32, 'unknown': 1}` —— **0 pass**。

与 `46-04` §3.2 逐字一致（32 `acceptance_unmet` / 1 `acceptance_leg_unreadable`=`p6i-research-from-zero` / 0 pass）；
`draft/44` **J-20** 已由主控复核过同一层（"33 份表逐格实跑得 `{'fail': 32, 'unknown': 1}`"）。

**这一条就是本组回放口径的根据（J-20 改判）：门今天对真机是全红 ⇒ 不许比状态词，必须比 `findings.detail` 的原因行。**

### 0.3 204 行验收行 `[本次现算 + 命令]`

命令：

```powershell
python -B -c "
import pathlib, json, collections
files = sorted(pathlib.Path('projects').glob('*/out/paper/ACCEPTANCE-CHECKS.json'))
c = collections.Counter(); used = set(); na = []
for p in files:
    data = json.loads(p.read_text(encoding='utf-8'))
    for r in (data if isinstance(data, list) else (data.get('checks') or [])):
        k = str(r.get('kind') or ''); used.add(k)
        if r.get('na') is True: na.append((p.parents[2].name, r.get('id'), k))
        if 'min' not in r: c['absent'] += 1
        elif int(r.get('min') or 0) == 0: c['zero'] += 1
        else: c['gt0'] += 1
print(c, len(used), len(na), na)"
```

读数：

| 读数 | 值 | 备注 |
|---|---:|---|
| 总行数 | **204** | 与 `46-04` §3.1 一致 |
| 用到档位 | **26 / 30** | 与 `46-04` §3.1 一致 |
| 未出现的 4 档 | `reviewed_current_rows` / `document_body_rows` / `document_claim_rows` / `claim_evidence_fit_rows` | **正是四条自动分支认的四个档**（`46-04` §2.7 末） |
| `na` 行 | **4** | `p7b` `B1`(`numeric_experiment_rows`) / `p7b` `D2`(`supported_claims`) / `p8d` `A2`(`reviewed_proof_rows`) / `p8g` `C10`(`proof_experiment_rows`)；**与 `46-04` §2.1 逐字一致** |
| 阈值声明（按 `'min' in row` 轴） | `min>0` **184** / `min` 字面为 `0` **11** / 未写 `min` **9** | `[本次现算]` |

**与 `46-04` §3.1 / J-18 的口径差（必须记账，不许折平）：**
`46-04` 写的是"`min>0` **184**、`min=0` **8**、未写 `min` **8**"（合计 200，另有 4 行 `na` 未计入），
它用的是**排除 4 行 `na` 后**的轴；本次现算用的是**全 204 行**轴 ⇒ `184 / 11 / 9`。
两轴的 `min>0` 一致（**184**），差异只在 `min=0` 与"未写"的边界（本次现算里 `p8g` `C10` 既 `na` 又未写 `min`；另有 3 行字面 `min: 0` 落在 `na` 之外的统计方式上）。
**施工时以"`min>0` = 184"为共同锚点；`8/8` 与 `11/9` 两个小口径不许混用**（照 `draft/47` §3-C8 的纪律）。

### 0.4 "表里 `min` ≠ 该档 `implicit_min`" = **0** `[本次现算 + 命令]`（复核 J-18）

命令：

```powershell
python -B -c "
import pathlib, json, collections
from agentflow import closing as CL
from agentflow.store import Store
files = sorted(pathlib.Path('projects').glob('*/out/paper/ACCEPTANCE-CHECKS.json'))
hit = collections.Counter(); mismatch = []
for p in files:
    data = json.loads(p.read_text(encoding='utf-8'))
    ws = p.parents[2]
    for r in (data if isinstance(data, list) else (data.get('checks') or [])):
        if r.get('na') is True: continue
        k = str(r.get('kind') or '')
        if k not in CL.LEG_CHECK_KINDS: continue
        try: got, detail = CL._leg_reading(Store(ws), k, ws)
        except Exception: continue
        im = detail.get('implicit_min')
        if im is None: continue
        hit[k] += 1
        if 'min' in r and int(r.get('min') or 0) != int(im): mismatch.append((ws.name, r.get('id'), k, r.get('min'), im))
print(sum(hit.values()), dict(hit)); print(len(mismatch), mismatch)"
```

读数：

- 该档产出 `implicit_min` 的行 = **9**（`citation_records_vs_bibitems` **6** + `unfinished_request_rows` **2** + `retrieval_ok_rows` **1**）—— **与 `46-04` §2.2 逐字一致**。
- 其中 `min` 与该档 `implicit_min` **不一致的行 = 0** —— **与 J-18 逐字一致**（"表里 `min` ≠ 该档 `implicit_min` = 0"）。
- 补充读数（`46-04` §2.2 没单列，本次现算）：**真正吃到 `implicit_min`（即 `min` 未写或写 0）的只有 8 行**；
  第 9 行（`p8g` `C2` `retrieval_ok_rows`，`min: 3`、`implicit_min: 3`）**写了显式 `min` 且恰好相等** ⇒ 今天走"显式优先"，
  改后走"取大"**产出不变**。这正是 E-05"收紧不误伤历史"的逐行证据。

**结论（照抄 J-18 的判定）：E-05 在盘上是"潜在风险、零翻转"，不是有真机证据的缺陷。**

### 0.5 46 份 `REPORT.md` 的形状读数 `[46-04 §2.3]`

- 报告总数 **46**（根 A 46 / 根 B 0）`[本次现算]`。
- 严格标题 + 节体非空：**45/46 本来就已经合格**，只有 `p5-run6` 是 5 节（缺六/七/八/九）。
- 附件三件套"真的判"后**红 9/46**：`p5-run6`（缺 `origin=own_result`）、
  `p6-research-from-zero`/`p6e`/`p6k`/`p6o`/`p8f`（缺 `origin=own_result`+`依据`）、
  `p6n`/`p6q`（缺 `origin=own_result`+`sha`）、`p7-open-questions`（缺 `origin=own_result`）。
- ⇒ **"九节查节体"只翻 1 份；"附件三件套真的判"翻 9 份**（J-19 的收益不对称）。

### 0.6 `ARTIFACTS` 分根 `[46-04 §2.10]`（`draft/47` §2 第 20 组只复核了抽样口径）

| 根 | 台账目录数 | `ok` | `changed` | missing | 备注 |
|---|---:|---:|---:|---:|---|
| 根 A | 57 | **1387** | 0 | —— | `[子代理]`（`draft/47` §4 列为未复核） |
| 根 B | 8 | **2599** | **589**（≈18.75%） | —— | `[子代理]`（同上） |

`draft/47` §2 第 20 组的 `[我复核]` 只到**抽样**一层：`ARTIFACTS` 共 **4575** 行、抽验 80 行 = **77 ok / 3 changed / 0 missing**。
两口径不冲突（抽样 vs 分根全量），但**分根全量两次都由子代理给出** ⇒ 本方案把它列为**未核实项**（见 §汇总）。

---

## §1 逐条施工方案（`closing.py`）

**块格式固定 6 项**：改什么 / 怎么改 / 改的依据 / 怎么算过 / 不许这么改·边界 / 依赖与批次。
"怎么算过"固定四层：**负控（改前必红）· 真机回放（比原因行，不比状态词）· 会红的既有判据 · 全量门**。

**全局全量门（每一块都跑同一套，后面不再重复展开）：**

```powershell
python -B -m pytest -q -p no:randomly
python -B scripts/lint_rules.py
```

- `pytest` 全量：基线由施工时第一次跑的读数确定；`46-04` §7.2 明确 **"哪些测试会红"是静态判读，施工时必须先跑一遍确认**（照抄，不许当成已核实）。
- `lint_rules.py` 基线：**0 错 / 9 警 / 49 提示**；`--strict` 为 **0 / 58 / 48** `[46-04 §6 引 `draft/45` 基线口径]`。
- **两条命令本方案都没跑**（硬纪律：不许跑 pytest）；施工时**必须先跑一次留基线**，改完再跑一次比。

---

### 块 CL-01 · E-04a：一行 `na` 不许关掉四条自动分支（分支守卫）

**改什么**
把四条自动分支的"这一档没写进表里"判据，从**看 `out` 里所有行**（含 `na` 行）改成**只看真算过的行**；
并把四条分支的**本体**从"另算一遍"改成"**读台账**"（先跑 `_leg_reading`，读到缺陷才 `unmet.append`）。
`na` 只许关掉**本行自己的阈值判定**（`:1233-1245` 现有语义保留），不许关掉分支。

**怎么改（接口级）**
1. 在 `_check_acceptance` 里拆两个集合（`closing.py:1145-1401` 内，`:1210` 附近已有 `out`/`na_rows`）：
   伪码 `computed_kinds = {r["kind"] for r in out if not r.get("na")}`、`na_kinds = {r["kind"] for r in out if r.get("na")}`。
2. 四条守卫改为对 `computed_kinds` 求集合（原文逐字，`[本次确认]`）：

```python
1319:    if "reviewed_current_rows" not in {str(r.get("kind") or "") for r in out}:      # -> computed_kinds
1340:    if "document_body_rows" not in {str(r.get("kind") or "") for r in out}:         # -> computed_kinds
1360:    if "claim_evidence_fit_rows" not in {str(r.get("kind") or "") for r in out}:    # -> computed_kinds
1378:    if "manuscript_rows" not in {str(r.get("kind") or "") for r in out}:            # -> computed_kinds
```

3. 分支本体四键统一（`46-04` §6.2 负控二要求 `detail` 里出现这四个键）：
   `stale_signoffs`（`:1326`）、`empty_section_docs`（`:1347`）、`mismatches`（`:1365`）、`derived_rows`（`:1385`）——
   今天已分别存在，改成"统一从 `_leg_reading` 的 `detail` 取并并列进读数"。
4. 新增读数 `na_covered_groups`（哪些环只被 `na` 行覆盖）与 `na_hidden_defects`
   （哪些缺陷本会被分支报出、却因缺那一行而被 `na` 顶掉）。
5. **不做**：`research_chain_gaps` 的 `marked`（`:347`）**一字不改**。

**改的依据**
- `draft/46-04 §2.1`（机理与内存复算：`p7b` +6 行、`p5-review-t17`/`p8g` 各 +3 行 `na` ⇒ `acceptance=pass`）；
  `§1.3`（四条分支的触发条件与行号）、`§6.1`（`:1860` 是既有反判据）、`§6.2`（两条负控）。
- `draft/44` **J-17**（"修法 = 四条自动分支的守卫改为对'真算过的 kind'求集合 + 分支本体改读台账（对 33 份真表 0 处翻转）"）；
  `draft/44:155`。
- `draft/43-C` **C-04**（`closing.py:1319` 的 `if ... not in {...}` 让"验收表里写的"与"门实际判的"不是同一组行）、
  **C-16**（`na` 第三态出口的来历是 D49）。
- 关键证据：`tests/test_closing_gate.py:1860` 夹具（`:1867-1874`）+ 断言 `:1877` `assert rep.status["acceptance"] == "pass"`。

**怎么算过**

- **负控（改前必红，必须先跑）：**
  - `tests/test_closing_gate.py::test_an_na_row_cannot_silence_an_automatic_branch`（新写，`46-04` §6.2）——
    夹具：有 stale 签名的稿 + 表里写 `{"kind":"reviewed_current_rows","na":true,"note":"x"}`；
    断言原文（`46-04` §6.2 逐字）：`acceptance == "fail"` 且 `detail` 含"现行版本没有被审校记录钉住"。**改前必红**（今天这条 `pass`）。
  - `tests/test_closing_gate.py::test_the_four_auto_branches_read_the_ledger_not_the_table`（新写）——
    断言：表里不写那四档时，四条分支的 `detail` 键（`stale_signoffs`/`empty_section_docs`/`mismatches`/`derived_rows`）都要出现。
    **改前必红**（今天分支只在"表里没有该 kind"时跑，没有统一的四键）。
  - 负控纪律（`draft/45:83`，`46-04` §6.2 引）：判据用**独立口径**算（例如直接读台账再数一遍），不抄实现里的表达式。
- **真机回放（比 `findings.detail` 的原因行，不比状态词）：**
  用 `46-04` §6.3 命令 1（六格回放集）与命令 2（33 份逐格）。
  - 33 份：**改前 32 fail / 1 unknown / 0 pass**（§0.2 `[本次现算]`）；**改后逐格仍应为同一组原因行**——
    J-17 的判定是"对 33 份真表 **0 处翻转**"，因为 4 行 `na` 落在的四档（`numeric_experiment_rows`/`supported_claims`/
    `reviewed_proof_rows`/`proof_experiment_rows`）**一行都不在四条分支认的四个档上**（`46-04` §2.1 末段）。
  - `p8e` / `p8g` / `p7b` / `p5-review-t17`：`--`（原因行逐字不变）。逐条改前原因（`46-04` §3.2 逐字照抄）：
    - `p8e`：覆盖面缺「检索（真的取回）」+「闭（请求闭环）」；`reviewed_current_rows` 陈旧签名（`0000` 现行 `68bfc4c7…` vs 签名 `e7346eb7…`，`status=revised, revision=2`）；`claim_evidence_fit_rows` mismatch（`0000/claim-4`）。
    - `p8g`：`document_body_rows`：`0000` 三节 body 全空；`claim_evidence_fit_rows`：`claim-1/2/3` 全 mismatch（含两条 exp 数字互换）。
    - `p7b`：覆盖面缺 4 环（`['检索（真的取回）','看（关系分析）','攻（攻坚推进）','闭（请求闭环）']`，`46-04` §3.4）；`claim_evidence_fit_rows` mismatch（`0000/claim-3`、`0000/claim-11`）。
    - `p5-review-t17`：`document_body_rows`：`0000` 五节 body 全空；`claim_evidence_fit_rows` mismatch（`claim-2/claim-3`）；`manuscript_rows` 92 行全是框架派生。
    - `p8f`：覆盖面缺「检索（真的取回）」+「交（手稿落盘）」；`manuscript_rows` 62 行全是框架派生。
    - `p6q`：覆盖面缺 3 环；`manuscript_rows` 96 行全是框架派生。
  - 改后预期的原因行变化：**本块单独上线时为 0 处**；只有"被改过的表"（人工追加 `na`）才从 `pass` 回到 `fail` ——
    `46-04` §6.3 逐字："**（仅在被改过表的场景）**`p7b` / `p8g` / `p5-review-t17` 追加 3–6 行 `na` 后会从 `pass` 回到 `fail` —— 这正是 E-04 要堵的洞，不是回放里的真实格子"。
- **会红的既有判据（逐条 `file:line`）：**
  - `tests/test_closing_gate.py:1860`（`test_an_na_row_is_the_way_to_ship_a_deliberately_unreviewed_revision`）——
    红的断言是 `:1877` `assert rep.status["acceptance"] == "pass"`。**必须改**（`:1879` 的
    `rows["P2"]["na"] is True and rows["P2"]["got"] is None` 保留）。
    处置（`46-04` §6.1 逐字）：语义改写 —— 断言"`fail` + 读数里有 `na` 行 + detail 点名 `stale_signoffs`"。
  - `:1705`（`test_an_na_row_is_the_way_to_leave_a_request_open_on_purpose`）与 `:1312`
    （`test_an_na_row_counts_as_marked_and_leaves_a_reading`）：**本块不动它们**（`marked` 不改 ⇒ 不红）；
    它们属于块 CL-02 的连坐面。
- **快照/文档/计数同步：** 新增的两个读数键要进 `check_closing` 的 `readings` 面；
  `conductor.closing` 的 `returns`（`conductor_tools.py:952-957`）**不需要改**（它按 `readings` 整包透传）。
  无 `DEFAULT_CHECKS` 计数变化（仍 7 格）⇒ 无工具描述同步。
- **全量门：** 见上方全局两条命令。

**不许这么改 / 边界**
- **必须单裁的那一条不许顺手做**：`46-04` §6.5 逐字 —— "E-04 顺带收紧'`na` 不算覆盖面 `marked`'"判 **高风险，须单独裁定**，
  会把 `p7b` `B1`/`D2`、`p8d` `A2`、`p8g` `C10` 四行**合法** `na` 一起变红（`p7b` 的"算或造"整环正是被 `B1` 一行覆盖，§3.4）
  —— 那是 D49 明确要保留的出口。该条拆到 **CL-02（E-04b）**。
- **`closing.py` 不在 FC-27 清单里**（`.noai-paths` 逐条比对后无 `closing.py`；`draft/44:167` 的 E-16 同此说；
  `draft/47` §3-C2 已复核）⇒ 可按普通改动走，**仍建议先改后报备**。
- 不许把 `na` 行的 `ok=True`/`got=None`（`:1243-1244`）改成 `ok=False` —— 三态纪律：`na` ≠ 通过 ≠ 失败。

**依赖与批次**
- 无前置依赖；可独立上线（`46-04` §5 表：档次 **高**，可独立做）。
- **本组建议顺序：第 3 位**（`44` J-21 的 CL 组顺序 = E-06 附件 → E-06 九节 → **E-04a** → E-05+CC-05 → F-06+P-03 → CC-03+CC-09 → CC-06）。

---

### 块 CL-02 · E-04b：覆盖面 `marked` 是否收紧（**单裁，未裁前不开工**）

**改什么**
"某环只被一行 `na` 覆盖"时，`research_chain_gaps` 今天算**已覆盖**（`:344` `marked` + `:347` `not marked`）；
若要收紧，就是把 `marked` 从"算覆盖"降成"不算覆盖 + 读数警告"。

**怎么改（接口级）**
- **未裁定前：不动。** `closing.py:342-349` 一字不改（原文逐字，`[本次确认]`）：

```python
342:    for label, members in RESEARCH_CHAIN_GROUPS:
343:        hit = [k for k in members if k in used]
344:        marked = [k for k in members if k in na_used]
345:        groups[label] = hit
346:        na_groups[label] = marked
347:        if researched and not hit and not marked:
```

- 若人裁"收紧"，**形态只能是读数级**（新键 `na_only_groups`），不改 `missing` 的算法 —— 因为 `missing` 直接进 blocker `acceptance_stage_uncovered`。

**改的依据**
- `draft/46-04 §2.1` 末段（"必须裁定的分叉"）、**§6.5**（"高风险，须单独裁定"）、`§3.4`（`na` 覆盖面真机事实）。
- `draft/44` **J-17** 逐字："**但**覆盖面判据里的 `marked`（`:347`）**不许同批收紧**"；
  "**E-04b**（覆盖面 `marked`）单裁 —— 后者会连坐 **4 行合法 `na`**（`p7b` B1/D2、`p8d` A2、`p8g` C10）"。
- `draft/47` §5（`46-04` §6.5/§7 的人裁点① = E-04b 单裁）。
- `draft/43-C` **C-16**（`na` 出口来自 `draft/39` D49，是**明确要保留**的第三态出口）。

**怎么算过（仅在已裁定"收紧"后启动）**
- **负控（改前必红）：** 新增用例，夹具 = `p7b` 形态（`numeric_experiment_rows` 一行 `na` 撑起"算或造"整环）⇒
  断言 `chain["missing"]` 含「算或造」。**改前必红**（今天 `p7b` 的 `missing` 里**没有**「算或造」，`46-04` §3.4）。
- **真机回放（比原因行）：** 33 份逐格。**预期 4 处原因行变化**（这是本块唯一预期会翻的格子）：
  - `p7b`：改前 `missing = ['检索（真的取回）','看（关系分析）','攻（攻坚推进）','闭（请求闭环）']`；
    改后**预期新增「算或造」**（被 `B1` 的 `na` 覆盖的那一环）。
  - `p8d`（`A2 reviewed_proof_rows` na）、`p8g`（`C10 proof_experiment_rows` na"未核到（na）"）、`p7b`（`D2 supported_claims` na）
    三行所在的环：改前算覆盖、改后**预期**在 `missing` 里出现对应环标签（`算或造` / `想（猜想或判决性证据）`）。
  - **这三处的"改前原因行"本方案未逐格采录**（`46-04` §6.3 只给了六格回放集）⇒ 施工时必须先跑命令 2 采录，再比。
- **会红的既有判据：**
  - `tests/test_closing_gate.py:1312`（`test_an_na_row_counts_as_marked_and_leaves_a_reading`）—— 断言在 `:1350-1351`
    附近：`chain["na_groups"]["算或造"]` 非空、`chain["missing"] == []`（`46-04` §6.1 逐字引）。
  - `tests/test_closing_gate.py:1705` —— `:1728` 断言 `"R8" not in blockers`（`46-04` §6.1 逐字引）。
  - `tests/test_closing_gate.py:1860` —— 同块 CL-01（`marked` 与分支守卫同时收紧会双重红）。
- **快照/文档/计数同步：** 新读数键 + `research_chain_gaps` 的 `note`（`:356-363`）里"某一档天然不适用就写 `na`"那一句要同步改写，否则读数与说明互相矛盾。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **不许"与 E-04a 同批顺手做"**（J-17）。
- **不许把 `na` 从词表/出口删掉**：D49 的合法出口是"调查型任务没有算或造那一步"的唯一诚实表达（`43-C` C-16）。
- 不许把 `marked` 折成 `hit`（那就等于承认 `na` 是"做过"）。

**依赖与批次**
- 前置：**人裁**（`46-04` §6.5 / `draft/47` §5 第①点）。
- 批次：**独立批次**，不进 CL 组主序；裁定为"不收紧"时本块直接关闭（默认建议不收紧）。

---

### 块 CL-03 · E-05：阈值不许被压低 / 不许自证

**改什么**
三处：
① `want_min` 从"显式优先"改成"**取大**"（`min` 从此只能把阈值**提高**）；
② `citation_records_vs_bibitems` 的分母从"主稿优先"改成"**只读基线 `source/main.tex`**"；
③ `manuscript_edited` 从"比 sha（一个字节即算改过）"改成"**去空白规范化后仍有差异**"。

**怎么改（接口级）**
1. 阈值取大（`closing.py:1266-1278`，原文逐字 `[本次确认]`）：

```python
1266:        if not want_min:
1267:            # 调用方没写 `min` ⇒ 用这一档自己算出来的阈值 ...
1269:            implicit = detail.get("implicit_min")
1270:            if implicit is None:
1273:                want_min = 0 if detail.get("implicit_max") is not None else 1
1274:            else:
1275:                want_min = int(implicit)
1278:        ok_row = got >= want_min and (want_max is None or got <= want_max)
```

伪码：`declared = int(row.get("min") or 0)`；`kind_min = int(detail.get("implicit_min") or 0)`；
`effective = max(declared, kind_min)`（两者皆 0 且该档有 `implicit_max` 时仍为 0，见 `:1273` 的既有语义）；
新增读数 `min_overridden: {"declared": declared, "kind_min": kind_min, "effective": effective}`。
**给 `implicit_min` 的档共 6 处**（`:660 :686 :700 :717 :540 :592`，`46-04` §2.2 列出）：产出不变，但同样不可被更小的 `min` 覆盖。
2. 分母换基线（`closing.py:575-596`，原文逐字 `[本次确认]`）：

```python
575:        draft = project_root / "out" / "paper" / "main.tex"
576:        base = project_root / "source" / "main.tex"
577:        src = draft if draft.is_file() else base        # <- 改成：只读 base
578:        if not src.is_file():
579:            raise ValueError(f"主稿与基线都不在盘上（{draft} / {base}）⇒ 数不出 bibitem 条数")
592:            "implicit_min": bibitems,
593:            "counted_from": "out/paper/main.tex" if src is draft else "source/main.tex",
```

改成：`src = base`；`base` 不在 ⇒ **`LegNotApplicable`（第四态，见块 CL-05）**，不再是"整格 unknown"；
读数并列 `denominator_from`（恒 `"source/main.tex"`）与 `draft_bibitems`（只为对照，不参与判据）。
3. 实质改动（`closing.py:549-568`，原文逐字 `[本次确认]`）：

```python
560:        d_sha = RA.file_digest(draft)
561:        b_sha = RA.file_digest(base)
562:        same = d_sha == b_sha
563:        return (0 if same else 1), { ... "edited": not same }
```

改成：读文本 → `re.sub(r"\s+", " ", text).strip()` → 比规范化后的哈希；读数并列 `raw_changed` 与 `substantive`，**取值用后者**。

**改的依据**
- `draft/46-04 §2.2`（三处原文 + 33 份表实测：184 行显式 `min>0`；9 行吃到自算 `implicit_min`；
  **表里 `min` 与该档 `implicit_min` 不一致 = 0**；引文档 6 次使用中主稿与基线 `\bibitem` **都是 7**；
  `manuscript_edited` 9 次 `got=1` 逐字节差 1258/262/1195/182/614/138/555/1012 字节，**去空白后仍全不相同**）。
- `draft/44` **J-18**（E-05/E-08 在盘上是"潜在风险、零翻转"）、`draft/44:156`。
- `draft/43-C` **C-05**（`quote_verified_rows` vs `citation_records_vs_bibitems` 同一行两套阈值；
  "写表的人可以合法地挑松的那一套"）、**C-06**（`manuscript_edited` 是唯一要只读基线的档）。
- 关键证据：`closing.py:1213` 注释逐字 `# 0 = 让这一档自己定阈值`、`:1267` 注释逐字"调用方没写 `min` ⇒ 用这一档自己算出来的阈值"。

**怎么算过**

- **负控（改前必红，必须先跑）：**
  - `test_a_smaller_min_cannot_lower_the_kinds_own_threshold`（新写，`46-04` §6.2）——
    夹具：`research_questions` 3 行、`outcome=ok` 的检索 1 条、行里写 `"min":1`；
    断言原文：该行 `ok is False` 且 `min_overridden.effective == 3`。**改前必红**（今天 `:1213` 的"显式优先"让它 `ok is True`）。
  - `test_the_citation_denominator_comes_from_the_read_only_baseline`（新写）——
    夹具：主稿 1 条 `\bibitem`、基线 3 条、台账 1 条；断言：`ok is False`、`denominator_from == "source/main.tex"`。
    **改前必红**（今天分母取主稿 `:577` ⇒ 读成 1 并 `ok is True`）。
  - `test_a_whitespace_only_change_is_not_an_edit`（新写）—— 断言 `got == 0`。**改前必红**（今天比 sha ⇒ `got == 1`）。
- **真机回放（比原因行）：**
  - 33 份逐格：**本块预期 0 处原因行变化**（J-18："零翻转"）。逐条依据：
    ①9 行吃到 `implicit_min` 中只有 8 行真走"自算"，其中 6 行 `citation_records_vs_bibitems` 的主稿/基线 `\bibitem` **都是 7**
    ⇒ 分母换基线**不改读数**；②`min` 与 `implicit_min` 不一致 = 0 ⇒ 取大**不改任何一行**；
    ③`manuscript_edited` 9 次去空白后仍全不同 ⇒ 规范化**不改读数**（§0.4 `[本次现算]` 已复核 ①②）。
  - 六格回放集：`p8e` / `p8f` / `p8g` / `p7b` / `p6q` / `p5-review-t17` 的 `acceptance` 原因行 **`--`（逐字不变）**（`46-04` §6.3 逐格预测）。
  - `p6i`（CC-05 用）：本块单独上线时 `acceptance` 仍 `unknown`；**与块 CL-05 同批上线后**变成
    `rows: 0→11`、`unknown→fail`，**原因行** = "缺覆盖面 + `P10 document_literature_citations` `got=0`"（`46-04` §6.3）。
- **会红的既有判据（逐条 `file:line`）：**
  - `tests/test_closing_gate.py:371`（`test_the_per_citation_leg_counts_against_the_number_of_bibitems`）——
    夹具在 `:386` **只写 `out/paper/main.tex`**；红的断言：`:397` `row["min"] == 3`、`:408` `fail`、`:420` `pass`。
    处置（`46-04` §6.1 逐字）：夹具补 `source/main.tex`（同 3 条），并新增"只有主稿 ⇒ 该行不适用而非整格 unknown"。
  - `tests/test_closing_gate.py:322`（`test_the_manuscript_edited_leg_compares_the_draft_with_the_read_only_baseline`）——
    断言 `:351` `fail`、`:360` `pass`、`:366` `unknown` + `:367-368` `== ["acceptance_leg_unreadable"]`。
    夹具差异是**实质的**（`:333` vs `:357` 差"改过了"三字）⇒ 只需补一条"仅空白不同 ⇒ `got=0`"负控（`46-04` §6.1）。
    **注意**：`unknown` 那一条会被块 CL-05 改成"该行不适用" ⇒ **本块必须与 CL-05 同批**。
  - `tests/test_closing_gate.py:793`（`test_the_report_shape_check_goes_red_alone`）：**与本块无关**（列在此处只为提示 E-06 会碰它）。
- **快照/文档/计数同步（重要，本块有不可逆面）：**
  - `46-04` §6.4 第 1 条逐字："33 份表 / 204 行今天读出的 `got` 是**旧口径下的数**。…… 按 `draft/45:12`：
    **每改一次口径必须在 `draft/44` 那一行写下'从哪一趟起口径变了'**。建议同批在 `readings["acceptance"]` 里落一个 `"reading_version"`（今天没有），
    并以 `p8g`（唯一覆盖面 8/8 齐的工作区）作口径锚点。"
  - 三处新读数键（`min_overridden` / `denominator_from` / `substantive`）要进 `check_closing` 的 `readings` 面。
  - `specs/m.py:75` 关于"`min` 缺省时按该档的口径"的措辞要同步（否则人与门两套口径）。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **不许改 `kind` 的字符串契约**（`46-04` §6.4 第 2 条：30 档的名字不能删、不能改名，204 行历史表按字面引用）。
- 不许把 `max` 也做成"取小"—— `46-04` §2.2 只裁了 `min` 一侧；`unfinished_request_rows` 的 2 行（`p8f` `C5`、`p8g` `C8`）只写 `max: 0`（`46-04` §3.1）。
- **分母换基线必须与 CC-05 同批**（否则 `:371` 夹具整格 unknown —— `46-04` §5 表逐字）。
- 不许把 `manuscript_edited` 的"基线不在盘上"折成 `got=0`（那就把"比不出"折成"没改"，正是 `43-C` C-06 ②记的 §96 原话禁止的）。

**依赖与批次**
- 三处内部依赖：②③ 需要 **CL-05（CC-05 第四态）**；① 可独立。
- 批次（J-21）：**第 4 位**，与 **CC-05（CL-05）同批**。

---

### 块 CL-04 · E-06 附件半：附件三件套"真的判"（**先做**）

**改什么**
`_check_report_shape` 里算出来了却从不参与判定的 `has_attach`（`closing.py:1923`），
改成 `missing_attach` 并**进 `problems`**。

**怎么改（接口级）**
原文逐字（`closing.py:1919-1942`，`[本次确认]`）：

```python
1919:    text = path.read_text(encoding="utf-8")
1920:    missing = [f"{num}、{name}" for num, name in REPORT_SECTIONS
1921:               if f"{num}、" not in text and name not in text]
1922:    missing_split = [m for m in SPLIT_MARKERS if m not in text]
1923:    has_attach = [f for f in ATTACHMENT_FIELDS if f in text]
1924:    rep.readings["report_shape"] = {
1926:        "missing_sections": missing, "missing_split_markers": missing_split,
1927:        "attachment_fields": has_attach, }
1929:    problems: list[str] = []
1930:    if missing:
1931:        problems.append(f"缺 {len(missing)} 节（{'、'.join(missing[:4])}）")
1932:    if missing_split:
1933:        problems.append(f"缺分栏标记（{'、'.join(missing_split)}）—— …")
```

伪码：`missing_attach = [f for f in ATTACHMENT_FIELDS if f not in text]`；
`if missing_attach: problems.append(...)`；读数新增键 `missing_attachment_fields`（保留 `attachment_fields` 作兼容读数）。
`grep has_attach` 全仓只命中 `:1923` / `:1927`（`46-04` §2.3）⇒ 改动面收敛在这两行。

**改的依据**
- `draft/46-04 §2.3`（改成什么 + 46 份真机实测：附件改后**红 9/46**）。
- `draft/44` **J-19** 逐字："E-06 两半收益极不对称：'九节查节体非空'只翻 **1** 份（`p5-run6`），'附件三件套真的判'翻 **9** 份（含回放集里的 `p8f`、`p6q`）；且附件问题必须**并入同一个 `report_incomplete` code**"；
  "E-06 的落地顺序：**先附件**（收益 9 份）再九节；code 不许新增第二个（否则既有断言红）"。
- `draft/43-C` **C-10** ①（`ATTACHMENT_FIELDS` 是收工门那套判据的一部分）。
- 关键证据：`grep has_attach` 只命中 `closing.py:1923` / `:1927`（`[46-04 §2.3]`）。

**怎么算过**

- **负控（改前必红，必须先跑）：**
  `test_the_attachment_triple_is_judged_not_just_read`（新写，`46-04` §6.2）——
  夹具：缺 `origin=own_result`；断言：`fail`，`missing_attachment_fields == ["origin=own_result"]`。
  **改前必红**（今天 `has_attach` 只进读数不参与 `problems`，`:1923/1927`）。
- **真机回放（比原因行）：**
  - 46 份（根 A 46 / 根 B 0）：**本块预期改 9 份的 `report_shape` 原因行**（逐份见 §0.5）。
  - 六格回放集（`46-04` §2.3 表 + §6.3 逐格预测），**改前 → 改后**：
    - `p8e` / `p8g` / `p7b` / `p5-review-t17`：`report_shape` pass → **pass**（原因行 `--`，三件套齐）。
    - `p8f`：pass → **fail**，原因行 = "缺 `origin=own_result`、`依据`"（改前原因行为空）。
    - `p6q`：pass → **fail**，原因行 = "缺 `origin=own_result`、`sha`"（改前原因行为空）。
  - 命令 5（`46-04` §6.3）可直接采录 46 份的"缺哪几件"。
- **会红的既有判据（逐条 `file:line`）：**
  - `tests/test_closing_gate.py:793`（`test_the_report_shape_check_goes_red_alone`）——
    红的断言 `:799` `assert [f.code for f in rep.blockers] == ["report_incomplete"]`。
    **处置（必须照做）：附件问题并入同一个 `report_incomplete` code 即不红；新开 code 则本条必改**（`46-04` §6.1）。
  - `tests/test_closing_gate.py:803-804`（同测试内）断言其余六格全 `pass` ⇒ 新读数键**不许影响状态面**。
  - `tests/test_review_acceptance.py:65-66,238`（从 `closing.REPORT_SECTIONS` 取九节）—— 本块**不红**，留给块 CL-08。
- **快照/文档/计数同步：** `readings["report_shape"]` 新增 `missing_attachment_fields` 键。
  `46-04` §2.3 ③ 要求同时新增 `empty_sections` / `section_bodies` —— 那两条属**九节半（CL-05 之后）**，本块不提前加。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **不许新增第二个 finding code**（J-19 逐字；否则 `:799` 当场红）。
- 不许把附件判据做成 blocker 之外的 `warning` —— 9 份真机报告会因此"看起来通过"。
- `ATTACHMENT_FIELDS`（`:1428`）的**三个字符串**不许改（`origin=own_result` / `依据` / `sha` 是既有报告的字面契约）。

**依赖与批次**
- 无前置依赖；可独立上线（`46-04` §5：档次 **中**）。
- 批次（J-21）：**第 1 位**（E-06 附件 → E-06 九节 → …）。

---

### 块 CL-05 · E-06 九节半：九节改为"标题级 + 节体非空"（+ 每节有读数待裁）

**改什么**
`_check_report_shape` 的九节判据从"节名或序号出现在正文任意位置就算齐"（`closing.py:1920-1921`）
改成"**markdown 标题级 + 节体非空**"；`_SECTION_RE` 从 `reviewaccept.py:54` **搬**来并**修掉 `reviewaccept.py:117` 的起点偏移 bug**。

**怎么改（接口级）**
伪码（照 `46-04 §2.3` 的伪码，逐字）：

```python
_SECTION_RE = re.compile(r"^#{2,3}\s*([一二三四五六七八九])、(.+)$", re.M)   # 与 reviewaccept.py:54 同形态
# 逐节取"标题 -> 下一标题"之间文本，要求 strip() 非空
# 新增读数：empty_sections / section_bodies
# 可选再加 reviewaccept._LEDGER_REF_RE 的"有读数"要求（与 CC-06 同批决定）
```

原文定位（`closing.py:1920-1921`，`[本次确认]`）：

```python
1920:    missing = [f"{num}、{name}" for num, name in REPORT_SECTIONS
1921:               if f"{num}、" not in text and name not in text]
```

**修 `reviewaccept.py:117` 的 bug**（原文逐字 `[本次确认]`）：

```python
reviewaccept.py:113:    sections = _SECTION_RE.findall(text)
reviewaccept.py:117:        start = text.find(f"{num}、")     # <-- 没有起点偏移：取到前言里第一次出现
reviewaccept.py:121:        if not re.search(r"\d", body) and not _LEDGER_REF_RE.search(body):
reviewaccept.py:122:            empty.append(f"{num}、{name.strip()}")
```

**改的依据**
- `draft/46-04 §2.3`（伪码 + 46 份实测：**45/46 本来就已经合格**，只翻 `p5-run6`）。
- `draft/44` **J-19**（"先附件（收益 9 份）**再九节**"）。
- `draft/43-C` **C-10**（两套判据、强度不同；`reviewaccept.py:117-120` 的机制；`p5-review-t10` 实测两个相反结论）。
- `draft/46-04 §2.9`（CC-06 的落点与"顺序必须是先严格判据、后删模块"）。

**怎么算过**

- **负控（改前必红，必须先跑）：**
  - `test_a_section_name_in_the_preamble_does_not_count_as_a_section`（新写，`46-04` §6.2）——
    夹具：正文只写"本文按一、任务与范围……九、诚实边界组织"，无 `##` 标题；
    断言：`fail` 且 `missing_sections` 有 9 项。**改前必红**（今天 `:1920-1921` 会判 `pass`）。
  - `test_an_empty_section_body_is_not_a_section`（新写）—— 九个 `## 一、…` 标题、每节 body 为空；
    断言：`fail` 且 `empty_sections` 有 9 项。**改前必红**（今天只看节名 ⇒ `pass`）。
- **真机回放（比原因行）：**
  - 46 份：**本块预期只翻 1 份** —— `p5-run6`（5 节，缺六/七/八/九）；改前原因行为空、改后
    原因行 = "缺 4 节（六、七、八、九）"形态（具体格式由 `:1931` 的 `f"缺 {len(missing)} 节（{'、'.join(missing[:4])}）"` 决定）。
  - 六格回放集：**全部 `--`**（`p8e`/`p8f`/`p8g`/`p7b`/`p6q`/`p5-review-t17` 的九节本来就合格）。
  - 命令 5（`46-04` §6.3）采录 46 份。
- **会红的既有判据（逐条 `file:line`）：**
  - `tests/test_closing_gate.py:793` —— 同块 CL-04（`:799` 的 `== ["report_incomplete"]`；`_write_report(tmp_path, drop_section="七", drop_split=True)` 在 `:796`，
    新判据下"缺七节"仍应是 `missing_sections` 非空 ⇒ 断言 `:801` `any("我们做的补救" in m for m in rd["missing_sections"])` 需确认仍成立）。
  - `tests/test_review_acceptance.py:65-66,238` —— 本块**不动**（模块还在），留给块 CL-08。
- **快照/文档/计数同步：** 新读数键 `empty_sections` / `section_bodies`；`REPORT_SECTIONS`（`:1415-1425`）**九节字符串不改**。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **"每节要有读数"（`_LEDGER_REF_RE`）与 CC-06 同批决定**（`46-04` §2.3 ③ 逐字："可选再加 …… 的'有读数'要求（与 CC-06 同批决定）"）。
  本块只做"标题级 + 节体非空"两件。
- **不许在 `closing` 之前删 `reviewaccept`**（顺序错了就没有任何判据承担 `report_sections_have_readings`，`46-04` §2.9 / `draft/46-05 §5.3`）。
- `rep.readings["report_shape"]` 的既有键（`path` / `chars` / `missing_sections` / `missing_split_markers`）**不许改名**（`:1924-1927` 已被测试读）。

**依赖与批次**
- 前置：块 CL-04（附件半）先落地。
- 批次（J-21）：**第 2 位**。

---

### 块 CL-06 · E-08：锚与验收表解耦（**两侧对称过滤**）

**改什么**
让 `RENDER-ANCHOR.json` 的 `files` 集合**不收**"交付时还会被改写的流程产物"（`ACCEPTANCE-CHECKS.json` / `ACCEPTANCE.md`），
从而使"交付时改一次验收表"不再把 `anchor` 打红。

**怎么改（接口级）**
落点两处、**必须同时改**（`46-04` §2.4，原文逐字）：

```python
 renderanchor.py:74: def package_files(package_dir: Path) -> dict[str, str]:
 81:    for p in sorted(package_dir.rglob("*")):
 82:        if not p.is_file() or p.name in (ANCHOR_NAME, RECEIPT_NAME):
 83:            continue
 84:        if p.name in COMPILE_PRODUCTS or p.suffix in COMPILE_SUFFIXES:
 85:            continue
 86:        files[p.relative_to(package_dir).as_posix()] = file_digest(p)
```

```python
 276:    files_now = package_files(out)
 277:    files_was = {k: v for k, v in (anchor.get("files") or {}).items()
 278:                 if k not in COMPILE_PRODUCTS and not any(k.endswith(s) for s in COMPILE_SUFFIXES)}
```

伪码：新增与 `COMPILE_PRODUCTS` 同族的 `PROCESS_PRODUCTS = ("ACCEPTANCE-CHECKS.json", "ACCEPTANCE.md")`（或前缀 `ACCEPTANCE-`）；
`package_files` 的 `:84` 加一条；`check_package` 的 `:277-278` **同时**加同一条。
**按文件名匹配而不是按相对路径**——`p6i` 的锚键是 `out/paper/main.tex` 这种带前缀的形状（`46-04` §2.4 ③）。
读数新增 `excluded_process_products`。
`closing.py` 侧只是一个常量落点（`:76` `ACCEPTANCE_CHECKS_NAME = "out/paper/ACCEPTANCE-CHECKS.json"`），**本块不改它**。

**改的依据**
- `draft/46-04 §2.4`（原文 + 实测：32 份锚中 **10 份**的 `files` 含 `ACCEPTANCE-CHECKS.json`，当前全 `consistent`；
  在 `p5-review-t17` 上把验收表 sha 改掉后 `verdict=drifted`、`dims.files=drifted`、`drift=[...]`）；
  `§6.4` 第 3 条（"锚的 `files` 集合是逐字节记录的。E-08 的过滤必须**两侧对称**；只过滤 `files_now` 一侧会让 10 份老锚立刻 `drifted`，
  而'重渲染'会改写 `RENDER-ANCHOR.json` 并**追加** `BUILD-HISTORY.jsonl`（回滚恢复不了）"）；`§6.5` 末（`renderanchor.py` 不在禁改区）。
- `draft/44` **J-18** 逐字："E-08 的耦合**实测到了**（改验收表 ⇒ `anchor=drifted`），但**两侧对称过滤后 10 份含该文件的老锚全部保持 consistent**"；
  "E-08 的施工必须**两侧同改**（写入侧与校验侧的 files 过滤），否则老锚集体漂移"。
- `draft/43-C` **C-09**（`renderanchor` 的锚与回执、`anchor` 格、`_has_paper_package`）。
- 关键证据：`draft/45:45` 记的风险（`46-04` §2.4 ③ 引用）。

**怎么算过**

- **负控（改前必红，必须先跑）：**
  `test_editing_the_acceptance_table_does_not_drift_the_anchor`（新写，`46-04` §6.2）——
  夹具：渲染锚 → 改 `ACCEPTANCE-CHECKS.json` → `check_package` 仍 `consistent`；含该文件的**老锚**也 `consistent`。
  **改前必红**（`46-04` §2.4 实测：`p5-review-t17` 改后 `verdict=drifted`，
  `drift: ["文件 ACCEPTANCE-CHECKS.json：内容与渲染时不同（3bc8778efbf2 ≠ 000000000000）"]`）。
- **真机回放（比原因行）：**
  - 命令 4（`46-04` §6.3）跑 32 份锚：**改前逐份 `verdict=consistent`（10 份含验收表的老锚也 `consistent`）**；
    **改后预期全部仍 `consistent`**（J-18："0 处翻转"）。
  - 六格回放集：`p5-review-t17` 的 `anchor` 维 `consistent` **`--`**（`46-04` §6.3 逐格预测："`--`（10 份含表的老锚保持 `consistent`）"）。
  - **本块的真机判据是"逐份 verdict 不变"**（这一格今天不是全红，与 acceptance 那一格口径不同 —— J-20 的"比原因行"只约束 `acceptance` 格）。
- **会红的既有判据（逐条 `file:line`）：**
  - `46-04` §6.1 表：**E-08 无直接会红的既有测试**（`tests/test_closing_gate.py` 里没有锚漂移用例）；
    相关面是 `tests/test_render_anchor*.py` 一族的既有锚回归 —— **本方案未逐条采录其行号**（列为未核实项）。
  - `tests/test_closing_gate.py:733`（`test_the_anchor_check_goes_red_alone`）—— 与验收表无关，**不应红**（作为"没误伤"的对照跑一次）。
- **快照/文档/计数同步：**
  - **不许"重渲染"旧锚来对齐**：`46-04` §6.4 第 3 条明确"重渲染会改写 `RENDER-ANCHOR.json` 并追加 `BUILD-HISTORY.jsonl`（回滚恢复不了）"。
  - `renderanchor.py` 的模块 docstring 若枚举了 `files` 的收录范围，要同步加 `PROCESS_PRODUCTS` 一句。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **两侧必须对称**（只改一侧 = 老锚集体漂移 = `46-04` §6.4 第 3 条点名的不可逆点）。
- **只按文件名过滤**，不许按目录/后缀（`p6i` 的锚键带 `out/paper/` 前缀）。
- **不许顺带把 `closing.py` 的 `ACCEPTANCE_CHECKS_NAME` 改掉**（块 CL-10 的 F-06 生成器要用它）。
- `closing.py` / `renderanchor.py` / `signatures.py` / `artifacts.py` **都不在 FC-27 清单**（`draft/44:167` E-16、`draft/47` §3-C2）⇒ 可普通改动走，仍建议先改后报备。

**依赖与批次**
- 无前置依赖（`46-04` §5：档次 **高**，可独立做）。
- 批次：**独立批次**（不与本组主序耦合；`46-04` §5.1 只要求"`closing.py` 与 `renderanchor.py` 同批"）。

---

### 块 CL-07 · S-05a：研究产出读数（腿 1 = 有结论的实验）**可做**

**改什么**
词表**只加档**（不改既有档口径），新增 `conclusive_experiment_rows` 并挂进"算或造"环（或新开一环）；
读数必须并列分母。

**怎么改（接口级）**
三处落点 + 三处镜像（`46-04` §2.5 ①）：

```python
  23:    ("立题", ("research_question_rows",))
 287:    ("算或造", ("numeric_experiment_rows", "search_frontier_rows",
 288:                "enumeration_optimization_rows", "reviewed_proof_rows",
 289:                "counterexample_or_proof_rows")),
 290:    ("想（猜想或判决性证据）", ("conjecture_rows", "statement_rows",
 291:                                "counterexample_or_proof_rows")),
```

伪码（照 `46-04` §2.5 ③，逐字）：

```
conclusive_experiment_rows = experiments 里 result ∈ {supports, refutes} 且
                             (claim/certificate/search_bound 至少一项非空) 的行数
```

- 落点：`:80-244`（词表加一档）+ `:470-1126`（`_leg_reading` 加一段 `if kind == "conclusive_experiment_rows":`）+ `:287-291`（挂环）。
- 读数并列分母 `experiments_total`。
- 镜像三处：`agent_prompts.py:1009-1110`（八环点名段）、`agent_prompts.py:1095-1106`（逐字清单）、`specs/m.py:69-79`（平铺清单）——
  **镜像属块 CL-09（CC-03/CC-09）；本块只改 `closing.py`，镜像同步挂在 CL-09 同批**。

**改的依据**
- `draft/46-04 §2.5`（伪码 + 实测基线：根 A `experiments` 217 = `supports` 55 / `refutes` 24 / `inconclusive` 138（63.6%）；
  根 B 189 = 124 / 0 / 65（34.4%）；**合计 406 中 `inconclusive` 203（50.0%）** —— 与 `draft/44:41` 一致）。
- `draft/44` **J-22** 逐字："①**腿 2 不可行**……；②**腿 3 字段面撑不住**……"；
  影响栏："S-05 拆成 S-05a（有结论的实验，可做）/ S-05b（我方派生命题，等 F-01）/ S-05c（交稿↔问题，降级或单裁）"。
- `draft/44:41`（"`inconclusive` 203/406 = 50% 仍可全绿"）；`draft/41-F` §1.6/§1.7（129-158 行）。
- `draft/43-C` **C-16**（研究链八环的成员是"受控档"口径的一部分：加档就是改覆盖面判据的可用成员）。

**怎么算过**

- **负控（改前必红，必须先跑）：**
  自写用例（`46-04` §6.2 未给 S-05 的负控 ⇒ 本块需新拟，标 `[判断类]`）：
  夹具造 `experiments` 3 行（`supports` 1 / `refutes` 1 / `inconclusive` 1，前两行带 `claim`）；表里写 `conclusive_experiment_rows` `min: 2`。
  断言：`got == 2`。**改前必红**（该 `kind` 今天在词表外 ⇒ `:1246-1253` 整表 `unknown` `acceptance_unknown_kind`）。
- **真机回放（比原因行）：**
  - 33 份逐格：**本块预期 0 处原因行变化** —— 新档**不在任何一份历史表里**（204 行里没有它），
    所以 `_check_acceptance` 的逐行走法一模一样；唯一可能变的是 `research_chain_gaps` 的 `groups`（覆盖成员集合变大，
    但"覆盖"看的是"那一行在不在"（`:342-349`），加成员不会让已有环变"未覆盖"）。
  - 六格回放集：`--`。
  - 口径锚点：`p8g` 是唯一覆盖面 8/8 齐的工作区（`46-04` §6.4 第 1 条建议以它作口径锚点）——
    本块上线后跑一遍确认 `p8g` 的 `research_chain.missing` 仍为 `[]`。
  - **本块的真机读数（新档的 `got`）今天没有样本**：`46-04` §7.6 明确"不核 3 档的语义边界"，
    且列出的 4 档是 `reviewed_current_rows`/`document_body_rows`/`document_claim_rows`/`claim_evidence_fit_rows`；
    `conclusive_experiment_rows` 是**新档**，其 `got` 只能靠 5) 命令在两根上现算（`46-04` §2.5 给了分母基线，没给逐工作区的 `got`）。
- **会红的既有判据（逐条 `file:line`）：**
  - `tests/test_agent_prompts.py:196-201` —— `:200` `missing = [k for k in CL.LEG_CHECK_KINDS if k not in text]`
    ⇒ **加档后这条必红**，除非同批把该档写进 M 的 brief 与镜像。**必须与块 CL-09 同批**（J-21 的精神：
    `CC-03 必须与 CC-09 同批`；本块与 CC-03 同属"词表变动"）。
  - `tests/test_conductor_tools.py:101-115` —— `:113` 按 `CL.DEFAULT_CHECKS` 比，**不按 `LEG_CHECK_KINDS`** ⇒ 本块不红（只要不加第八格）。
  - `tests/test_closing_gate.py` —— 无按 `len(LEG_CHECK_KINDS)` 比数的断言（`46-04` §4.2 未列）⇒ 预期不红。
- **快照/文档/计数同步：**
  - `draft/46-04 §6.4` 第 1 条：**每改一次口径必须在 `draft/44` 那一行写下"从哪一趟起口径变了"**。
  - `draft/46-04 §5.1` 末：**S-05(新档进覆盖面) ⇒ 改 `research_chain` 的 `missing` 口径 ⇒ 必须登记"从哪一趟起口径变了"**。
  - 文档计数：`agent_prompts.py:1095-1106` 的逐字清单今天 **29 档**、代码 **30 档** ⇒ 加档后差更远（见块 CL-09）。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **不许改既有档的口径**（`46-04` §2.5 ③ 逐字："**只加档、不改既有档口径**"）。
- **不许把新档直接塞进 `RESEARCH_CHAIN_GROUPS` 造成历史环成员变化**而不登记——加成员属口径变更（`46-04` §5.1）。
- **腿 2 / 腿 3 不在本块**（见块 CL-08）。

**依赖与批次**
- 无前置依赖（`46-04` §5：腿 1 档次 **高**，可独立做）。
- 批次：与 **块 CL-09（CC-03+CC-09）同批**（因为 `tests/test_agent_prompts.py:196-201` 是共同反判据）。

---

### 块 CL-08 · S-05b / S-05c：**不可行 / 撑不住**（不得单独上线）

**改什么**
**不改。** 本块只登记两条判定与它们的前置，防止施工时"顺手做了"。

**怎么改（接口级）**
- **S-05b（我方派生命题 + 等级）**：伪码形态为
  `own_result_statement_rows = statements 里 origin=own_result 且 evidencebits.bits_from_row(r)["grade"] ∉ {conjecture} 的行数`。
  **今天不许实现** —— 它会恒为 0。
- **S-05c（交稿↔问题）**：伪码形态为
  `question_delivery_rows = documents.claims[].citations 经 exp:<id>/rel:<id> 回落到 experiments.for_question_id / conjectures.for_question_id 得到的**不同 question_id** 数`。
  **降级形态**：只做"**可判链**"读数并同列 `unlinked_claims`，**先进读数、不进覆盖面**。

**改的依据**
- `draft/46-04 §6.5` 逐字（两条判定）：
  - "S-05 腿 2 单独上线 | **不可行** | `statements` 138 行里 `own_result` 13 行，`bits_from_row` 的 `grade` **全部** `conjecture`（`pre_theorem` 6 行全是 `external_lit`）⇒ 这一档恒为 0，只会制造一条恒红判据（41-F B13）"。
  - "S-05 腿 3 按'直接读字段'实现 | **不可行** | `schema.py:2394` 的 `documents` 只有 `sections/claims/open_problems`；`experiments.for_question_id` 54/217 有值、`conjectures` 0/66、`statements` 0/138 ⇒ 只能走引用链或先改 schema（禁改区）"。
- `draft/44` **J-22** 逐字（腿 2 恒红、腿 3 要么动禁改区 `schema.py`，要么降级为"可判链"读数）。
- `draft/46-04 §2.5` 实测基线：根 A `statements` 138 行、`origin=own_result` **13** 行，`grade` **全 `conjecture`**；
  `for_question_id` 覆盖：根 A `experiments` 54/217（25%）、`conjectures` **0/66**、`statements` **0/138**；根 B 三项全 0。
- `draft/47` §2 第 17 组 `[我复核]`：`statements` 138 行、`bits` 非空 **0**。
- `draft/43-C` **C-12**（`documents` 的字段面）。

**怎么算过**
- **负控：不适用**（本块不产出实现）。
- **真机回放：不适用。**
- **会红的既有判据：** 若有人硬上腿 2，会新增一条**恒红判据**（33 份表里 `own_result` 13 行全 `conjecture` ⇒ `got=0`）；
  这不是"某条测试红"，而是"门永远红"（`46-04` §6.5 的判据本身）。
- **快照/文档/计数同步：** 本块只需在 `draft/44` 对应行保留"从哪一趟起口径变了"的**空白记录**（即"未变"）。
- **全量门：不适用。**

**不许这么改 / 边界**
- **腿 2 不许在 F-01 / EE-12 落地前上线**（`46-04` §5.1："S-05(腿2) ──必须晚于──> F-01 / EE-12"）。
- **腿 3 不许为了让字段有值去改 `schema.py`** —— `schema.py` 是 **FC-27 禁改区**（`.noai-paths` `[category: schema-migration]`，逐字：
  "`SCHEMA_VERSION` 与 `TABLES`：表结构与版本号 —— 改它等于改磁盘格式契约"）。
- **腿 3 不许进覆盖面**（`46-04` §2.5 ③ 逐字："第三档**先只做读数、不进覆盖面**"）。
- 不许把 `for_question_id` 的 25% 覆盖率当成"链路可用"的证明。

**依赖与批次**
- 前置：S-05b ← **F-01 / EE-12**（`register_statement.py` 写 `bits`）；S-05c ← **人裁**（是否动 `schema.py`）。
- 批次：**不进本组主序**（`46-04` §5 表：两条都是 **低** 档、**不可**独立做）。

---

### 块 CL-09 · CC-03：一个词表装两代 30 档（只加分组标注）

**改什么**
**30 档取值不变**；只加 `LEG_CHECK_GROUPS: dict[str, tuple[str, ...]]`（`review_only` / `research_only` / `shared`）
与 `LEG_CHECK_HINTS`，并让 `research_chain_gaps` 对"研究型工作区拿到 review-only 档"给**读数级警告**；
镜像三处补齐 `c_analysis_runs`，并把 `tests/test_agent_prompts.py:200` 的"子串包含"改成"**清单 == 词表**"（集合相等）。

**怎么改（接口级）**
段界注释两处（`closing.py:162` / `:210`，原文逐字 `[46-04 §2.7]`）：

```python
 161:                            "少了它，「请求提交了没人跑」在收工门上一个读数都没有",
 162:    # ---- 研究类（`draft/38` 的 T2：从零做一轮研究，考察 A/B/D/E/F 与 M 的调度）----
 163:    "research_question_rows": "立起来的研究问题行数（`research_questions`）…
 209:                        "（那正是这一档要逼出来的那句实话）",
 210:    # ---- 数学对象的进度（`draft/37` §133：判「数学」，不判「台账厚度」）----
 211:    "conjecture_rows": "可检验的猜想条数（`conjectures` 里 `statement` 与 `testable` 都非空的行）"
```

**正确分法（按"这一档在什么工作区能算出数"，不许按行号分段）**，照 `46-04` §2.7 ③ 逐字：

- `KIND_REQUIRES_BASELINE = ("manuscript_edited", "citation_records_vs_bibitems")`
  （实测：前者 9 次用于审阅型 + 1 次误用于 `p6i`；后者 6 次全在审阅型）。
- 研究型专用 16 档：`document_literature_citations` / `conjecture_rows` / `plan_progress_rows` / `search_frontier_rows` /
  `statement_rows` / `supported_claims` / `c_analysis_runs` / `counterexample_or_proof_rows` / `reviewed_proof_rows` /
  `unfinished_request_rows` / `claims_supported_by_their_evidence` / `enumeration_optimization_rows` / `manuscript_rows` /
  `analysis_report_rows` / `retrieval_ok_rows` / `document_rows`。
- 两代共用：`research_question_rows`（研究 22 + 其他 1）、`retrieval_attempts`（研究 14 + 审阅 5）、
  `numeric_experiment_rows`（研究 16）、`reviewed_documents`（审阅 10 + 研究 2）、`proof_experiment_rows`（审阅 10 + 研究 1）、
  `quote_verified_rows`、`report_files`、`attack_plan_rows`。
- 镜像：`agent_prompts.py:1095-1106` 逐字 **29** 档清单 + `specs/m.py:75` —— 必须补 `c_analysis_runs`。
  **`specs/m.py` 是 FC-27 禁改区**（`[category: auth-audit]`，逐字"角色 M 的声明真身（M3 起）……改这里等于改权限面本身"）
  ⇒ **动它要走人审**（见"边界"）。

**改的依据**
- `draft/46-04 §2.7`（分法与实测：33 份表 / 204 行用掉 **26 档**；**未出现的 4 档 = `reviewed_current_rows` / `document_body_rows` / `document_claim_rows` / `claim_evidence_fit_rows`**）；
  `§6.5`（"CC-03 按类型分两张表 | **高风险，不建议** | `kind` 是 204 行历史表的字面契约；分区会让一半历史行变词表外 ⇒ 整表 unknown（`:1246-1253`）"）；
  `§6.4` 第 2 条（"`kind` 取值是磁盘契约。30 档的**名字**不能删、不能改名"）。
- `draft/44` **J-23** 逐字："**CC-03 改判**：不能'按工作区分两张表'…… 且 `draft/45` 说的按行号分段（`:81-161`/`:163-209`/`:211-243`）**分不出评审向/研究向**（**5 个研究档住在第一段区间里**）"；
  "CC-03 的正确分法只能是'**按"在什么工作区算得出数"分组**'（即按可读性，不按行号/工作区类型），并且不许改 `kind` 的字符串契约"。
- `draft/43-C` **C-03**（14+9+7 = 30 的按行号切分 + "一行坏 ⇒ 全表坏"的机制）、**C-16** ④（`specs/m.py:75` 逐字清单 **29** 档，差的那一档正是 `c_analysis_runs`）。
- `draft/44` **J-21**（CC-03 必须与 CC-09 同批）。

**怎么算过**

- **负控（改前必红，必须先跑）：** `46-04` §6.2 未给 CC-03 的负控 ⇒ 本块需新拟，标 `[判断类]`：
  - 夹具：一份**研究型**验收表，只写 `quote_verified_rows`（review-only）；断言：`research_chain` 的读数里有"review-only 档用错了工作区"警告，且 `DEFAULT` 面**不受影响**。
  - 夹具：人为把 `LEG_CHECK_GROUPS` 里任一档改名 ⇒ 断言 `LEG_CHECK_GROUPS` 的键集合 **== `set(LEG_CHECK_KINDS)`**（防止分组表与词表脱节）。**改前必红**（今天没有 `LEG_CHECK_GROUPS`）。
- **真机回放（比原因行）：**
  - 33 份逐格：**本块预期 0 处原因行变化** —— 分组标注**不参与 `_check_acceptance` 的判据**
    （30 档取值不变 ⇒ `:1246-1253` 的整表 unknown 风险为零；覆盖面 `:342-349` 只看 `used`/`na_used`，不看分组）。
  - 六格回放集：`--`。
  - **新警告的真机命中面今天未采录**（`46-04` §2.7 给了"哪些档在哪些工作区出现过"的统计，但没给"研究型工作区里出现 review-only 档"的逐格清单）
    ⇒ 列为未核实项；`46-04` §2.7 ② 明确"后者（`citation_records_vs_bibitems`）6 次全在审阅型"。
- **会红的既有判据（逐条 `file:line`）：**
  - `tests/test_agent_prompts.py:196-201` —— `:200` `missing = [k for k in CL.LEG_CHECK_KINDS if k not in text]`；
    `46-04` §6.1 逐字："今天靠子串过（`c_analysis_runs` 在 `agent_prompts.py:1023/1138/1140` 的散文里）"。
    处置：改成"逐字清单解析出的集合 == `set(LEG_CHECK_KINDS)`"，并把该档补进两处镜像。
  - `tests/test_agent_prompts.py:808-825` —— 属 **F-06+P-03** 同批（块 CL-10），本块**不红**。
  - `tests/test_conductor_tools.py:101-115` —— 按 `DEFAULT_CHECKS` 比 ⇒ 本块**不红**。
- **快照/文档/计数同步：**
  - `agent_prompts.py:1095-1106` 的逐字清单 29 → **30 档**；`specs/m.py:75` 同（**禁改区，人审**）。
  - `draft/46-04 §6.4` 第 2 条：不许删/改名任何档。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **不许"按工作区分成两张表"**（`46-04` §6.5 判"**高风险，不建议**"；J-23 逐字）。
- **不许按行号分段**（J-23：5 个研究档住在第一段区间里；`43-C` C-03 的 14+9+7 是**行号**切分，不是语义切分）。
- **不许改 `kind` 的字符串契约**（`46-04` §6.4 第 2 条：204 行历史表按字面引用）。
- **`specs/m.py` 是 FC-27 禁改区** ⇒ 镜像那一处**必须人审**（`AGENTS.md`：命中禁改区"由人编写，或人逐行走查"+ **2 名 reviewer 批准**）。

**依赖与批次**
- 前置/同批：**CC-09**（清单 == 词表）、`agent_prompts.py` / `specs/m.py` 镜像同步（J-21）。
- 批次：**第 6 位**（CL 组顺序：… → F-06+P-03 → **CC-03+CC-09** → CC-06）。

---

### 块 CL-10 · F-06：验收表由台账生成（必须与 P-03 退场同批）

**改什么**
新增纯函数 `generate_acceptance_rows(store, project_root) -> list[dict]`；
"表不在"的分支（`closing.py:1160-1186`）从"研究型 ⇒ 直接 fail"改成"**先生成、再走同一套 `:1203-1392` 判定**"。

**怎么改（接口级）**
原文（`closing.py:1160-1186`，逐字 `[46-04 §2.6]`）：

```python
1160:    if not path.is_file():
1164:        try:
1165:            chain = research_chain_gaps(store, ())
1174:        if chain["researched"]:
1175:            rep.status["acceptance"] = "fail"
1176:            rep.findings.append(Finding(
1177:                "acceptance", "acceptance_missing_for_research", "blocker", …))
1183:        else:
1184:            rep.status["acceptance"] = "pass"
1185:            rep.readings["acceptance"]["note"] = f"这个项目没有 {ACCEPTANCE_CHECKS_NAME}"
1186:        return
```

伪码（照 `46-04` §2.6 ③ 逐字）：对 `LEG_CHECK_KINDS` 逐档调 `_leg_reading`，产出
`{"id","name","kind","min","max","generated_by":"framework"}`；`min` 取该档 `implicit_min`（没有则 1），`max` 取 `implicit_max`；
表不在的分支改为"先生成、再走同一套 `:1203-1392` 判定"；读数新增 `generated: true` 与 `table_source: "file" | "generated"`；
**生成不出可判行时仍然红**（保留 `acceptance_missing_for_research` 语义）；**`na` 不由生成器写**（那是人或模型的知识）；
老表缺 `generated_by` **不报错**。

**改的依据**
- `draft/46-04 §2.6`（原文 + 实测：33/33 份真机工作区**都有**验收表 ⇒ F-06 在盘上 **0 处翻转**，它改的是"没有表"那条路）。
- `draft/44` **J-21** 逐字："F-06 必须与 P-03 退场 + `tests/test_agent_prompts.py:808` 同批"。
- `draft/46-04 §4.3`（**别混批**：`conductor.acceptance`（`conductor_tools.py:813/838-875`，读人读 `out/paper/ACCEPTANCE.md`，
  解析器 `:1100-1149`，结论列必须逐字"成立" `:1141`）与 `closing.acceptance`（读 JSON）**是两份不同的东西**；
  CC-02 的"8/54 份 `.md` 读成 0 行"属于前者）。
- `draft/46-04 §6.1`（F-06 的会红判据）、`§6.2`（负控）、`draft/43-C` **C-11**（报告落点与验收表落点：一条存在性断层）、**C-16** ③。

**怎么算过**

- **负控（改前必红，必须先跑）：**
  `test_a_missing_acceptance_table_is_generated_from_the_ledger`（新写，`46-04` §6.2）——
  夹具：研究型、无 JSON 表；断言：`table_source == "generated"` 且逐行 `got`/`ok` 都在；生成不出可判行时仍红。
  **改前必红**（今天走 `:1160-1186`，没有生成）。
- **真机回放（比原因行）：**
  - 33 份逐格：**本块预期 0 处原因行变化**（33/33 都有表 ⇒ 走不到那条分支）。
  - 六格回放集：`--`（六格都有表）。
  - **"没有表"那条路的真机样本存在**：`43-C` C-16 ③ 记"26 个工作区有 `research_questions` 行，其中 **4 个没有 `ACCEPTANCE-CHECKS.json`**（`p6f` / `p6h` / `p6j` / `p6l`）⇒ `_check_acceptance:1174-1182` 判 `acceptance_missing_for_research`（blocker，整格 fail）"
    —— 但这是 `43-C` 的读数、`46-04` §3.1 的"33 份表"口径里**不含**这 4 个 ⇒ 本块上线后应专门跑一次这 4 个，比"`acceptance_missing_for_research` 是否仍在、是否多了逐行读数"。
- **会红的既有判据（逐条 `file:line`）：**
  - `tests/test_closing_gate.py:948`（`test_a_research_project_must_leave_an_acceptance_checks_file`）——
    红的断言：`:959` `acceptance == "fail"`、`:960-961` `"acceptance_missing_for_research" in codes`、`:963` `len(chain["missing"]) == 8`。
    处置（`46-04` §6.1 逐字）：改成"生成的行必须逐行判、读数有 `generated: true`"。
  - `tests/test_agent_prompts.py:808-825`（`test_the_file_the_closing_gate_judges_is_named_in_the_prompt_that_writes_it`）——
    `:821` `assert name in text`；**P-03 退场后必红**。处置：改成"门与生成器同源"（文件名出现在 F-06 生成器的落点常量里）。
  - `tests/test_closing_gate.py:966` / `:989` / `:1011`（覆盖面三条）—— 同族；`46-04` §4.2 只点名 `:948` 会碰，另两条作为回归跑一次确认。
- **快照/文档/计数同步：**
  - 新读数键 `generated` / `table_source`；生成器用的文件名常量**必须复用** `ACCEPTANCE_CHECKS_NAME`（`:76`），
    否则 `tests/test_agent_prompts.py:808-825` 的"同源"判据无落点。
  - **`conductor.acceptance`（`.md` 解析器）不属本块**（`46-04` §4.3）。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **必须与 P-03 退场同批**（J-21；否则"教人写表"与"门自己生成表"两套口径并存）。
- **生成器不许写 `na` 行**（`46-04` §2.6 逐字："`na` **不由生成器写**（那是人或模型的知识）"）。
- **老表缺 `generated_by` 不报错**（向下兼容 204 行历史表）。
- 不许把"生成不出可判行"折成 `pass`（保留 `acceptance_missing_for_research` 语义）。
- 不许混做 `conductor.acceptance` 的 `.md` 解析（`conductor_tools.py:1100-1149`；CC-02 属另一批）。

**依赖与批次**
- 前置/同批：**P-03（M policy 退场）** + `tests/test_agent_prompts.py:808` 改写。
- 批次：**第 5 位**。

---

### 块 CL-11 · CC-05：缺基线 = 不适用，不是整表没查成

**改什么**
新增第四态 `LegNotApplicable(kind, reason)`；`manuscript_edited`（`:556-559`）与
`citation_records_vs_bibitems`（`:578-579`）在缺 `source/` 时抛它；
`_check_acceptance` 的 catch-all（`:1254-1265`）捕获后**不整格 return**，该行落
`{"ok": None, "not_applicable": true, "reason": …}` 且**不进 `unmet`**；
真正的读错（台账读不到、JSON 坏）**仍整格 unknown**（保留 `acceptance_leg_unreadable`）。

**怎么改（接口级）**
原文（逐字 `[本次确认]`）：

```python
1254:        try:
1255:            got, detail = _leg_reading(store, kind, Path(resolve_under_workspace(store, project_dir)))
1256:        except Exception as exc:  # noqa: BLE001
1257:            _acceptance_unknown(
1258:                rep, "acceptance_leg_unreadable",
1259:                f"验收行 {cid}（{kind}）的读数算不出来（{type(exc).__name__}: {exc}）" …)
1265:            return
```

```python
556:        if not draft.is_file():
557:            raise ValueError(f"可改的主稿不在盘上：{draft} ⇒ 这一档没查成")
558:        if not base.is_file():
559:            raise ValueError(f"只读基线不在盘上：{base} ⇒ 这一档没查成（比不出'改没改'）")
```

伪码：`except LegNotApplicable as na:` ⇒ 该行 `out.append({..., "ok": None, "not_applicable": True, "reason": na.reason})`；
新增读数 `rows_read` / `rows_not_applicable`；判据分界 = "**缺基线 = 不适用**" vs "**读不到台账 = 没查成**"。
**顺带**：`research_chain_gaps` 的 `marked`（`:344`）**也要认这些"不适用"行**，否则 `p6i` 会在两层各红一次（`46-04` §2.5/§2.9 逐字）。

**改的依据**
- `draft/46-04 §2.8`（原文 + 实测）：33 份表中 `manuscript_edited` 有 **23 处不可读**（缺 `source/`）、
  `citation_records_vs_bibitems` 有 **21 处**；**真表用到且踩中的只有 `p6i-research-from-zero` 一处**。
  当前：`acceptance=unknown`、`code=acceptance_leg_unreadable`、**`rows=0`**（后面 10 行连读数都没留下）。
  改后：`rows=11` 全部有读数，`acceptance=fail`（`P10 document_literature_citations` `got=0` + 覆盖面缺环），第一行变成 `not_applicable`。
- `draft/44` **J-20**（回放口径改判）、`draft/44:120`。
- `draft/46-04 §6.4` 第 4 条逐字："`na` 与'缺基线'的语义已经写进提示词与历史表。`agent_prompts.py:1107-1110` 逐字写着'算不出来 ⇒ 整张表没查成'，`p6i` 就是照这条写的。CC-05 改成'不适用'之后，**提示词那一段必须同批改**，否则人与门两套口径。"
- `draft/43-C` **C-06**（`p6i` 真机读数与 `draft/37` §96 的"任一文件不在盘上 ⇒ 抛"原话）、**C-03** ④（"一行坏 ⇒ 全表坏"的机制）、**C-16** ③。
- 关键证据：`closing.py:1135-1137` 的 docstring 逐字记着 `p6i` 那次事故（`46-04` §2.8 ④）。

**怎么算过**

- **负控（改前必红，必须先跑）：**
  `test_a_leg_that_needs_the_baseline_is_not_applicable_not_the_whole_cell`（新写，`46-04` §6.2）——
  夹具：研究型 + 表里 11 行、首行 `manuscript_edited`；断言：`rows` 有 11 条读数、首行 `not_applicable is True`、`acceptance` 由其余行决定。
  **改前必红**（今天 `rows == 0` 且整格 `unknown`，`p6i` 真机）。
- **真机回放（比原因行，**本组唯一预期 unknown→fail 的格子**）：**
  - `p6i-research-from-zero`：改前 `acceptance=unknown`、`code=acceptance_leg_unreadable`、`rows=0`、**原因行** = "验收行 P1（`manuscript_edited`）的读数算不出来（`ValueError`: 只读基线不在盘上：…）⇒ 这一行没查成……"；
    改后 **`rows: 0→11`**、`acceptance=fail`、**新的原因行** = 覆盖面缺环 + `P10 document_literature_citations` `got=0`，
    第一行的读数变成 `not_applicable`（`46-04` §6.3 逐格预测 + §2.8 实测）。
  - 其余 32 份：**原因行 `--`**（`manuscript_edited` 有 23 处不可读、`citation_records_vs_bibitems` 有 21 处，
    但"真表用到且踩中的只有 `p6i` 一处" ⇒ 其余表的行都不碰这两档的缺基线路径）。
  - 六格回放集：`p8e`/`p8f`/`p8g`/`p7b`/`p6q`/`p5-review-t17` 全 `--`（`46-04` §6.3 逐格预测）。
- **会红的既有判据（逐条 `file:line`）：**
  - `tests/test_closing_gate.py:1270`（`test_an_unreadable_leg_leaves_a_reason_in_the_reading_not_a_null`）——
    红的断言：`:1285` `acceptance == "unknown"`、`:1288` `reading["code"] == "acceptance_leg_unreadable"`、`:1291-1292` `== ["acceptance_leg_unreadable"]`。
    处置（`46-04` §6.1 逐字）：改成"该行 `not_applicable` + 其余行有读数"，另加一条"台账真读不到 ⇒ 整格 unknown"把两种情形分开。
  - `tests/test_closing_gate.py:322`（`manuscript_edited` 三态）—— `:366` `unknown` + `:367-368` 的 code 断言**会红**
    ⇒ **必须与块 CL-03 同批改**（`46-04` §5 表把 E-05 分母与 CC-05 标为"需同批"）。
  - `tests/test_closing_gate.py:371`（`citation_records_vs_bibitems`）—— 同批改（块 CL-03）。
- **快照/文档/计数同步（**本块有提示词硬依赖**）：**
  - `agent_prompts.py:1107-1110` 那段"算不出来 ⇒ 整张表没查成"**必须同批改**（`46-04` §6.4 第 4 条）。
  - 新读数键 `rows_read` / `rows_not_applicable`；`readings["acceptance"]["note"]` 与 `:356-363` 的 `note` 里"缺基线"那几句同步。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **不许把"读不到台账"也折成 `not_applicable`** —— 判据分界必须是"缺基线 = 不适用" vs "读不到台账 = 没查成"（`46-04` §2.8 ③ 逐字）。
- 不许删 `acceptance_leg_unreadable`（`tests/test_closing_gate.py:1270` 与 `:1295` 两条既有判据都靠它）。
- 不许只改 `closing.py` 不改提示词（`46-04` §6.4 第 4 条点名的"人与门两套口径"）。
- **`research_chain_gaps` 的 `marked` 要认"不适用"行**，但**语义仍是"这一环有出口"** —— 与本块 CL-02（E-04b 单裁）**不是同一件事**，别混。

**依赖与批次**
- 前置：**块 CL-03（E-05 分母换基线）**；同批。
- 批次（J-21）：**第 4 位**（E-05+CC-05 同批）。

---

### 块 CL-12 · CC-06：删掉重复的"报告九节"判据（**必须在 CL-05 之后**）

**改什么**
删 `reviewaccept.py` 全模块（**555 行**），`CRITERIA` 六条里唯一没落点的
`report_sections_have_readings` 由 `closing.report_shape` 唯一承担；
`closing` 侧**必须同时给出 `section_readings`**（逐节是否含数字/台账引用），否则"两处口径"变成"一处更弱的口径"。

**怎么改（接口级）**
顺序（`46-04` §2.9 ③ 逐字）："顺序**必须是**：先在 `closing` 做出 E-06 的严格判据（含'节体非空'与'每节有读数'两条，
`_SECTION_RE` 从 `reviewaccept` **搬**来并修掉 `:117`），跑通真机回放，**然后**才删 `reviewaccept` 全模块（555 行）"。
被删模块的关键原文（逐字 `[本次确认]`）：

```python
reviewaccept.py: 27: CRITERIA: tuple[tuple[str, str], ...] = (
reviewaccept.py: 54: _SECTION_RE = re.compile(r"^#{2,3}\s*([一二三四五六七八九])、(.+)$", re.M)
reviewaccept.py: 55: _LEDGER_REF_RE = re.compile(r"[a-z_]+:\d{4}|#\w[\w-]*|\bstmt\b|台账|页")
reviewaccept.py:105:    from .closing import resolve_under_workspace
reviewaccept.py:113:    sections = _SECTION_RE.findall(text)
reviewaccept.py:117:        start = text.find(f"{num}、")     # bug：没有起点偏移
reviewaccept.py:231:    from .closing import NO_SESSION
reviewaccept.py:451:    from .closing import resolve_under_workspace
reviewaccept.py:476-478:             gate = CL.check_closing(store, checks=("load_bearing",))
reviewaccept.py:506:    from .closing import resolve_under_workspace
```

连带：删 `tests/test_review_acceptance.py`；改 `tests/test_ledger_charging.py:33`、`tests/test_intake_actions.py`、
`tests/test_sid_scoped_questions.py`、`tests/test_relative_paths_under_workspace.py` 的引用。
`reviewaccept.py:476-478` 的 `check_closing(checks=("load_bearing",))` 随模块消失 ⇒ **`_check_load_bearing` 的调用方从两个减到一个**。

**改的依据**
- `draft/46-04 §2.9`（落点、顺序、连带清单）；`§6.1`（会红判据 `tests/test_review_acceptance.py` 整文件 + `tests/test_ledger_charging.py:33`）。
- `draft/46-05 §5.3`（删 `reviewaccept.py` 555 行会红的清单 —— **本方案照引它，未独立复核其逐条内容**）。
- `draft/44` **J-21** 逐字："E-06 必须先于 CC-06（删 `reviewaccept` 555 行）"；`draft/44:121`。
- `draft/43-C` **C-01**（`reviewaccept.check_review` 在生产代码里唯一的调用是自身 `check_review`，无生产调用点）、
  **C-10**（两套判据；`reviewaccept.py:117-120` 的起点偏移 bug；`p5-review-t10` 实测两个相反结论）、
  **C-15**（`reviewaccept` 自称"五条"、实现是 6 条）。
- `draft/46-04 §2.9` 实测：报告总数 46；`reviewaccept` 在生产代码里唯一的调用是自身 `check_review`（无生产调用点）；
  `p5-review-t10` 在本报告口径下 `closing.report_shape=pass`，而 `reviewaccept._c_report` 的 `:117` 会把节体截断到
  前言里第一次出现的 `f"{num}、"` ⇒ 误判"节里没有读数"。

**怎么算过**

- **负控（改前必红，必须先跑）：**
  `test_the_report_shape_criterion_lives_in_exactly_one_module`（新写，`46-04` §6.2）——
  断言：`sys.modules` 里没有 `agentflow.reviewaccept`，且 `closing._SECTION_RE` 存在。**改前必红**（今天两处都在）。
- **真机回放（比原因行）：**
  - 46 份 `report_shape`：**本块预期 0 处原因行变化**（判据已在块 CL-04/CL-05 里搬完并跑通；本块只删重复件）。
  - `p5-review-t10` 那一类"同一报告两个相反结论"：改后**只剩一个结论**（`closing.report_shape`）。
    改前对照（`43-C` C-10 ④ 逐字）：收工门 → `report_shape = pass`（`missing_sections=[]`、`missing_split_markers=[]`、`attachment_fields` 三件齐）；
    `reviewaccept` → `report_sections_have_readings = fail`，理由逐字"这些节里没有任何读数（既没有数字也没有台账引用）：二、逐条读数（对齐 P1–P9） —— 空标题不算交了这一节"。
  - 六格回放集：`--`。
- **会红的既有判据（逐条 `file:line`）：**
  - `tests/test_review_acceptance.py`（**整文件**，含 `:65-66` / `:238` 从 `closing.REPORT_SECTIONS` 取九节）—— 模块删除后 import 失败 ⇒ **与模块同批删**。
  - `tests/test_ledger_charging.py:33`（`import closing`）—— `46-04` §4.2 记它引 `closing`，`:33` 的引用要改；`46-04` §6.1 逐字把它列在 CC-06 行。
  - `tests/test_intake_actions.py` / `tests/test_sid_scoped_questions.py` / `tests/test_relative_paths_under_workspace.py` —— 逐条引用要改。
  - `tests/test_relative_paths_under_workspace.py:16,76,91,135`（`resolve_under_workspace` 四个落点）—— `reviewaccept` 那两个落点消失后仍要保证 `closing` 侧的落点覆盖不变。
  - `tests/test_sid_scoped_questions.py:13,43,52,63`（`sid` 三态）—— `reviewaccept.py:231-233` 的 `NO_SESSION` 用法消失后，`closing` 侧三态要单独有覆盖。
  - **`46-05 §5.3` 另列的会红项本方案未逐条采录**（引它而不复算，见"依据"一栏）。
- **快照/文档/计数同步：**
  - 删除后 `closing` 侧必须**同时给出 `section_readings`**（逐节是否含数字/台账引用），否则 `CRITERIA` 里
    `report_sections_have_readings` 这条口径会**变弱**（`46-04` §2.9 ③ 逐字）。
  - `attachment_is_honest` 的三件套正好被 E-06（块 CL-04）接住。
  - `statusreport.py` / `deliver.py` / `gates.py` / `faculty_checks.py` **零引用** `reviewaccept` 与 `closing`（`46-04` §4.1）⇒ 删除面不扩。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **不许先删后搬**（顺序倒过来 = 一段时间内没有任何判据承担九节口径）。
- **不许只删文件不补 `section_readings`**（`46-04` §2.9 ③）。
- `reviewaccept.py` **不在 FC-27 清单**（`draft/47` §3-C2 逐名比对未命中）⇒ 可普通改动走，仍建议先改后报备。
- 不许顺手删 `_check_load_bearing`（它被 `closing.check_closing` 的第七格与 `reviewaccept` 两处调用；删了后者仍有前者）。

**依赖与批次**
- 前置：**块 CL-04 + 块 CL-05（E-06 两半）**。
- 批次（J-21）：**第 7 位（最后）**。

---

### 块 CL-13 · EE-05：`ARTIFACTS.jsonl` 完整性读数（读数可独立；进第八格要单裁）

**改什么**
新增一档 `artifact_ledger_bad_rows`：`got = changed + missing + unreadable`，`implicit_max = 0`
（与 `unfinished_request_rows` 同一根轴：越少越好）；读数给 `{ok, changed, missing, unreadable}` 与明细（最多 8 条）。

**怎么改（接口级）**
`closing.py` 全文**零处**提到 `artifacts`（`46-04` §2.10 ① grep 确认）⇒ 要加只能新增三处：
`:80-244`（新档）+ `:470-1126`（新分支）+ `:49`（**仅在裁定进第八格时**）。

对照组（PDF 那一维是有的，逐字 `[46-04 §2.10]`）：

```python
 renderanchor.py:306:        elif file_digest(out / "main.pdf") != str(receipt.get("pdf_sha256") or ""):
 renderanchor.py:307:            receipt_verdict = "drifted"
 renderanchor.py:308:            drift.append("main.pdf：内容与编译回执不符（编译之后被换过？）")
```

**改的依据**
- `draft/46-04 §2.10`（落点 + 实测：根 A 57 个台账目录 = **1387 `ok`** / 0 changed；根 B 8 个 = **2599 `ok` / 589 `changed`**（≈18.75%）；
  kind 分布（根 B）：`paper` 2985 / `script` 105 / `task-result` 91 / `report` 7）。
- `draft/44:134` 逐字："加（红线：产物登记必须与盘上一致）"。
- `draft/44` **J-24**（EE-05 的 2599/589 由 04 号独立复现）。
- **"是否进 `DEFAULT_CHECKS` 第八格 = 独立裁定"**（`46-04` §2.10 ③、`§6.5`、`draft/47` §5 第③点）。

**怎么算过**

- **负控（改前必红，必须先跑）：**
  `test_the_artifact_ledger_must_match_the_disk`（新写，`46-04` §6.2）——
  夹具：造一条 sha 与盘上不同的 `ARTIFACTS.jsonl` 记录；断言：新档 `got >= 1` 且该行 `ok is False`。
  **改前必红**（今天没有这一档 ⇒ 表里写它会被 `:1246-1253` 判整表 `unknown`）。
- **真机回放（比原因行）：**
  - 命令 6（`46-04` §6.3）跑两个根的全部 `ARTIFACTS.jsonl` 目录：
    - **根 A**（57 个目录）：改前读数 = `1387 ok / 0 changed`；**改后预期逐目录 `got == 0`、该行 `ok is True`**（原因行 `--`，本来没有坏行）。
    - **根 B**（8 个目录）：改前读数 = `2599 ok / 589 changed`；**改后预期这些工作区里凡把该档写进表的一行 `got >= 1` ⇒ `ok is False`**，
      原因行形态 = "产物台账与盘上不一致：`changed` 589 条（例：<最多 8 条明细>）"。
    - **注意**：根 B **0 份验收表**（§0.1）⇒ 这条档**不会**出现在任何真机表里 ⇒ 真机"逐格原因行"变化面 = **0**；
      真机读数只能靠**直接调 `_leg_reading`**（命令 3 的形态）采录，不是靠 `check_closing`。
  - 六格回放集：`--`（那六个工作区没有 `artifacts` 相关 `kind`）。
- **会红的既有判据（逐条 `file:line`）：**
  - **读数版（不进第八格）：预期不红。** `46-04` §4.2 未列任何按 `LEG_CHECK_KINDS` 数量比对的断言；
    `tests/test_agent_prompts.py:196-201` 会红（`c_analysis_runs` 那一族的同一形态）⇒ **新档必须同批进 M 的 brief**（与块 CL-09 同批）。
  - **进第八格版：** `tests/test_conductor_tools.py:101-115` —— `:113` `missing = [name for name in CL.DEFAULT_CHECKS if name not in text]`、
    `:115` `assert "五条" not in text`。处置：工具描述同步加第八格（`conductor_tools.py:930-936` 的 `conductor.closing` 描述 + `:952-957` 的 `returns`）。
- **快照/文档/计数同步：**
  - 进第八格 ⇒ `DEFAULT_CHECKS 7→8` ⇒ `cli.py` / `conductor_tools.py` 描述 + `tests/test_conductor_tools.py`（`46-04` §5.1 末行逐字）。
  - `tests/test_release_all.py:2232`（发布说明里把 `closing.py` 的职责写成"五条"）—— **陈述陈旧（今天七格）**；
    进第八格后要一并改成八格（`46-04` §4.2 末行）。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **不进第八格时不许动 `DEFAULT_CHECKS`**（`46-04` §2.10 ③ 逐字："是否进 `DEFAULT_CHECKS` 第八格 = 独立裁定"）。
- **不许把两条台账合并成一条来读这一档**（那是磁盘契约，见块 CL-14 的边界）。
- **不许把 `missing`/`unreadable` 折成 `0`**（三态：读不到台账 ≠ 盘上一致）。
- 本块与 EE-10（块 CL-14）**不是同一件事**：本块是"产物台账与盘上一致吗"，CL-14 是"两条台账共用一个读法"。

**依赖与批次**
- 前置：**人裁"是否进第八格"**；读数版可独立做。
- 批次：读数版与**块 CL-09（CC-03+CC-09）同批**（共用 `tests/test_agent_prompts.py:196-201` 反判据）；进第八格另起一批。

---

### 块 CL-14 · EE-10：同一份产物在两个台账里各钉一次（**只合并"读法"**）

**改什么**
合并 `ledger_path` / `read_ledger` / `sha256_of` 到一处；`closing` 侧只改一处调用（`:513`），
并在 `reviewed_current_rows` 读数里新增 `ledger_module`。**不合并台账本体**（那是磁盘契约）。

**怎么改（接口级）**
`closing` 侧的实际接口点（原文逐字 `[本次确认]`）：

```python
closing.py:510:        from . import signatures as SIG
closing.py:513:        recs, bad_lines = SIG.read_ledger(SIG.ledger_path(project_root))
closing.py:521:        pinned = [d for d in claimed if SIG.signed_revision(d, recs) is not None]
closing.py:613:        from . import manuscripts as MS
closing.py:615:        all_rows, bad_lines = MS.read_rows(project_root)
```

重复实现清单（`46-04` §2.11 ② **按盘上真实情况更正 `44` 的措辞**）：

| 函数 | 落点一 | 落点二 | 备注 |
|---|---|---|---|
| `ledger_path` | `artifacts.py:79` | `signatures.py:153` | 两条台账的两个落点 |
| `read_ledger` | `artifacts.py:165` | `signatures.py:170` | 返回 `(records, bad_lines)`，形状相同 |
| `sha256_of` / `file_digest` | `artifacts.py:108` | `renderanchor.py:59` | 同一件事的两份实现 |
| `summarize` / `render_markdown` | `artifacts.py:249` / `:264` | **无对应** | `44` 说"signatures 也有一份"**不成立** |
| `slugify` | `textutil.py:164` | `fetch.py:233` | **不在 artifacts/signatures** |

**改的依据**
- `draft/46-04 §2.11`（清单 + 真机"双钉"实例）；
  `§5` 表（EE-10：`+10 / −30`，档次 **中**，可独立做，"只合并'读法'，不合并台账本体"）。
- `draft/44` **J-24** 逐字："`artifacts.py ∩ signatures.py` 的公开名交集**只有** `{ledger_path, read_ledger, selftest}`；
  `summarize`/`render_markdown` **只在 artifacts**（`43-E` 说'各有实现'**不成立**）；……
  登记册 §3-L/EE-10 的措辞按此收窄：**只合并同名的 `ledger_path`/`read_ledger`**，不许把 `summarize`/`render_markdown` 也算作重复"。
- `draft/47` §3-C12（同一更正）、`§2 第 20 组`（`ARTIFACTS` 4575 行的抽样复核）。
- `draft/43-E` EE-10 的原措辞（**已被更正**）。
- 关键证据（`46-04` §2.11 ④ 真机双钉）：根 B 的 `p2-review` 与 `p4-polish`：`ARTIFACTS.jsonl` 里 `out/paper/main.tex` 的
  `sha256=49404e4d159e180f…` 判 `ok`，同一份交付的 `DOC-SIGNATURES.jsonl` 钉的是稿件**内容哈希** `dc8a062c57cc4b01…`
  （现行版一致，旧版 `ac7ff9a33cd822b6…` 也在册）；而 `closing` **只读后者**。
  根 A 侧相反：57 个目录有产物台账，但 `out/paper/main.tex` **没有**一条进过它（`p5-review-t17` 只进签名台账）。

**怎么算过**

- **负控（改前必红，必须先跑）：**
  `test_the_two_ledgers_share_one_reader`（新写，`46-04` §6.2）——
  断言：`artifacts.read_ledger` 与 `signatures.read_ledger` 同源；`reviewed_current_rows` 读数含 `ledger_module`。
  **改前必红**（今天两份实现、读数里没有 `ledger_module`）。
- **真机回放（比原因行）：**
  - 33 份逐格：**本块预期 0 处原因行变化** —— `signatures.read_ledger` 与 `artifacts.read_ledger` 形状相同、
    合并后读的是**同一条** `DOC-SIGNATURES.jsonl`（`closing.py:513` 的语义不变）。
  - 六格回放集：`p5-review-t17` 的 `reviewed_current_rows` 陈旧签名原因行**逐字不变**
    （`0000` 现行 `68bfc4c7…` vs 签名 `e7346eb7…`，`status=revised, revision=2`）。
  - **根 A / 根 B 台账分布**（`46-04` §2.11 ③ 逐字，**不要据此合并台账本体**）：
    根 A **57** 个目录有 `ARTIFACTS.jsonl`、**40** 个有 `DOC-SIGNATURES.jsonl`（59 条签名记录）；根 B 是 **8** 与 **7**。
- **会红的既有判据（逐条 `file:line`）：**
  - `46-04` §6.1 表：**"EE-10 | 无直接测试 | —— | 合并后 `tests/test_closing_gate.py:1800/1827/1860` 三条 `reviewed_current_rows` 判据要走新入口"**。
    即：`:1800`（`test_the_reviewed_current_kind_reads_whether_the_signature_covers_this_version`）、
    `:1827`（`test_a_revision_after_the_signoff_turns_the_gate_red`）、`:1860`（同块 CL-01 已列）。
    处置：三条走新入口（读数键 `ledger_module` 出现即可，判据本身不变）。
  - `tests/test_ledger_charging.py:33` —— 属 CC-06 的连带面（块 CL-12），本块**不红**。
- **快照/文档/计数同步：**
  - 新读数键 `ledger_module`（`reviewed_current_rows` 的 `detail` 里）。
  - `draft/36:152` 的 T-6（`jsonlfile` 已并掉"怎么读 JSONL"那一层）—— 合并前先确认这一层已存在，别把已并掉的再并一次。
  - `signatures.py` / `artifacts.py` **都不在 FC-27 清单**（`draft/44:167`、`draft/47` §3-C2）⇒ 可普通改动走。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **不许把两条台账合并成一条**（`46-04` §2.11 ③ 逐字："**不要**把两条台账合并成一条——那是磁盘契约（`禁`）"）。
- **不许把 `summarize` / `render_markdown` 也算作重复**（J-24：它们**只在 artifacts**）。
- **不许动 `providers._normalize_basic` 或 `slugify` 的归一化算法**（`slugify` 的两个落点在 `textutil.py:164` / `fetch.py:233`，
  不在 artifacts/signatures；`draft/44` J-12 已判"不动归一化算法"）。
- 两条台账钉的是**不同哈希空间**（`49404e4d…` vs `dc8a062c…`），历史行**无法机械合一**（`46-04` §6.4 第 5 条）。

**依赖与批次**
- 无前置依赖（`46-04` §5：档次 **中**，可独立做）。
- 批次：**独立批次**，可与块 CL-13 并行。

---

### 块 CL-15 · 调用面与 `statusreport`（E-15 前置；本组只登记，不改）

**改什么**
不改。登记两件事：
① `conductor_tools.py` 的两个验收入口**不是同一件事**（`46-04` §4.3）；
② `statusreport.py` 今天**零引用** `closing`，E-15 要接管现场读数时**最省事的做法是直接调 `closing._leg_reading`**，
并需把 `_leg_reading` 从私有名提升为稳定接口，或加批量入口 `leg_readings(store, kinds, root)`（`46-04` §5 末）。

**怎么改（接口级）**
- 本组**不改**这两个入口的语义；只在块 CL-09/CL-13 改词表/加格时**同步它们的描述**：
  - `conductor.closing`（`conductor_tools.py:930-998`）描述里逐字写着"**七格**"，`returns`（`:952-957`）逐字列了七个 key + "status 的键是七格检查（anchor/contradictions/load_bearing/report_shape/user_pending/substance/acceptance）"。
  - `conductor.acceptance`（`:813/838-875`）读的是 `out/paper/ACCEPTANCE.md`（解析器 `:1100-1149`，结论列必须逐字"成立" `:1141`）—— **与 `closing.acceptance` 不是同一份东西**。
- 顶部工具表（`conductor_tools.py:30-31`）逐字："`conductor.closing` | read | 跑收工门**五条**（三态读数；`can_close` 只在五条全过时为真）" —— **陈旧陈述（今天七格）**，本组顺手改成七格并在进第八格时改成八格。

**改的依据**
- `draft/46-04 §1.5`（生产调用面逐条 `file:line`）、`§4.1`（零引用清单）、`§4.3`（两个验收入口的区别）、
  `§5.1` 末（E-15 的施工前提）、`§7.4`（不覆盖 E-07/E-15/CC-01/CC-02/CC-09）。
- `draft/44` **J-21**（批次关系里不含 E-15，但 `46-04` §5 明确要一起排期）。
- `draft/43-C` **C-01**（`reviewaccept` 无生产调用点）、**C-02**（`conductor.acceptance` 的 P1–P11 解析器，8/54 份读成 0 行属它）。

**怎么算过**
- **负控：不适用**（本块不改实现）。
- **真机回放：** 本组施工后跑一次 `conductor.closing` 与 `conductor.acceptance` 各一次（**只读**），
  确认 ① 描述里的格数与 `DEFAULT_CHECKS` 一致；② 两者的读数面没有互相污染。
- **会红的既有判据：** `tests/test_conductor_tools.py:101-115`（按 `DEFAULT_CHECKS` 比 + `"五条" not in text`）
  —— 本块改描述即满足；**注意 `:31` 的"五条"是 docstring 级描述，`:115` 的断言只查工具 `spec` 的 summary+returns**，
  故改 `:31` 属"顺手更正陈旧陈述"，不改也不红。
- **快照/文档/计数同步：** `tests/test_release_all.py:2232`（发布说明里 `closing.py` 职责写成"五条"）同批更正。
- **全量门：** 见全局两条。

**不许这么改 / 边界**
- **不许把 `conductor.acceptance` 与 `closing.acceptance` 合并**（`46-04` §4.3 逐字："CC-02（8/54 份 `.md` 读成 0 行）属于前者，**与 E-04/E-05/E-06 不是同一批**"）。
- **不许为了 E-15 提前把 `_leg_reading` 改名**（本组 11 条不含 E-15；改名会牵动 `_acceptance_unknown` 一族与 990 次实跑的口径）。
- `conductor_tools.py` **不在 FC-27 清单**（`draft/47` §3-C2：`tools/` 下只有 `__init__.py`、`base.py`、`verify_tools.py`、`vocab_census.py`、`release_all.py`、`coverage_zero_test.py`、`run_each_test_file.py` 在清单里）⇒ 可普通改动走。

**依赖与批次**
- 前置：无；**为 E-15 排期**（`46-04` §5 末逐字："**这是 E-15 的施工前提**，不属本次 11 条，但要一起排期"）。
- 批次：**随块 CL-09 / CL-13 的描述同步批次**。

---

## §汇总

### 汇总一 · 条目总表

| 块 | 条目 | 落点（`closing.py` 及直接调用点） | 可行性 | 是否禁改区 | 批次 | 依赖 |
|---|---|---|---|---|---|---|
| CL-01 | **E-04a** 分支守卫 | `:1233-1245` + `:1319/1340/1360/1378` + `:347`（不动） | **高**（可独立上线） | 否 | **3** | 无（须先裁定 E-04b 不动） |
| CL-02 | **E-04b** 覆盖面 `marked` | `:342-349` | 高风险 | 否 | **独立（须人裁）** | 人裁 |
| CL-03 | **E-05** 阈值取大 / 分母换基线 / 实质改动 | `:1213` `:1266-1278` `:575-596` `:549-568` | 高（阈值）/ 中（分母+实质） | 否 | **4** | 分母半 → **CL-11** |
| CL-04 | **E-06 附件半** | `:1919-1942` + `:1428` | 中 | 否 | **1** | 无 |
| CL-05 | **E-06 九节半** | `:1919-1942` + `reviewaccept.py:54/117` | 中 | 否（`reviewaccept.py` 不在清单） | **2** | CL-04 |
| CL-06 | **E-08** 锚解耦 | `renderanchor.py:74-87` `:277-278` + `closing.py:76`（常量） | 高 | 否 | **独立** | 两侧对称 |
| CL-07 | **S-05a** 腿 1 | `:80-244` `:470-1126` `:287-291` + 三镜像 | 高 | `specs/m.py` 是（镜像） | **6**（与 CL-09） | 无 |
| CL-08 | **S-05b / S-05c** | 同上 | **不可行 / 撑不住** | `schema.py` 是 | 不进主序 | F-01 / EE-12 / 人裁 |
| CL-09 | **CC-03** 分组标注 | `:80-244` + `agent_prompts.py:1095-1106` + `specs/m.py:75` | 中 | **`specs/m.py` 是** | **6** | **CC-09** |
| CL-10 | **F-06** 生成式验收表 | `:1160-1186` `:1187-1196` `:1246-1253` + 新函数 | 中 | 否 | **5** | **P-03 退场** + `test_agent_prompts.py:808` |
| CL-11 | **CC-05** 第四态 | `:1254-1265` `:556-559` `:578-579` `:1129-1142` | 中 | 否 | **4** | **CL-03**；+ `agent_prompts.py:1107-1110` 同批 |
| CL-12 | **CC-06** 删 `reviewaccept` | 删 555 行 + 5 个测试文件 + `closing` 补 `section_readings` | 中 | 否 | **7（最后）** | **CL-04 + CL-05** |
| CL-13 | **EE-05** 产物台账档 | `:80-244` `:470-1126`（+`:49` 若进第八格） | 高（读数）/ 中（第八格） | 否 | 与 **CL-09** 同批（读数版）；第八格单裁 | 人裁（第八格） |
| CL-14 | **EE-10** 合并读法 | `artifacts.py:79/165` `signatures.py:153/170` + `closing.py:513` | 中 | 否 | **独立** | 无 |
| CL-15 | **调用面 + E-15 前置** | `conductor_tools.py:30-31/813/930-998/1049`、`statusreport.py`（零引用） | 登记 | 否 | 随 CL-09/CL-13 | E-15 排期 |
| —— | `resolve_under_workspace` 越界（41-F B14） | `:1530-1553` | **本次不改** | 否 | 不入本组 | 属 E-13 家族（`46-04` §6.5 末行） |

**同批关系（照抄 `draft/44` J-21，不许自行拆开）：**
E-05（分母换基线）↔ CC-05（第四态） · E-06 必须先于 CC-06 · F-06 必须与 P-03 退场 + `tests/test_agent_prompts.py:808` 同批 ·
CC-03 必须与 CC-09 同批 · E-08 两侧对称 · S-05 腿 2 晚于 F-01/EE-12 · S-05 腿 3 晚于 schema 裁定 ·
S-05 新档进覆盖面 ⇒ 登记口径变更 · EE-05 进第八格 ⇒ `DEFAULT_CHECKS 7→8` ⇒ CLI / 工具描述 / `tests/test_conductor_tools.py`。

### 汇总二 · 未核实项（不许折成"没问题"，照 `draft/47` §4 的纪律）

| 项 | 出处 | 为什么没核实 |
|---|---|---|
| **30 档 × 33 工作区的可读性矩阵**（990 次实跑） | `46-04` §3.3 | `draft/47` §4 逐字："我复核了 `33 份表逐格 = {'fail': 32, 'unknown': 1}` 这一层（J-20），**30 档 × 33 工作区的可读性矩阵未复算**"。本方案只现算了"哪些档产出 `implicit_min`"（§0.4），**没复算抛错次数**。 |
| **`ARTIFACTS` 分根全量 1387 ok / 2599 ok + 589 changed** | `46-04` §2.10 | `draft/47` §4 逐字："我只抽验 80 行"。本方案**未复算分根全量**（§0.6）。 |
| **"哪些测试会红"是静态判读** | `46-04` §7.2 | `46-04` 自己逐字写明："**不跑模型、不跑网络、不跑全量 pytest**。'哪些测试会红'是**静态判读**（读测试源码 + 读实现判据），每条都给了 `file:line` 与红色断言原文；**施工时必须先跑一遍确认**。" —— 本方案**照抄这句**：CL-01…CL-14 的"会红的既有判据"一栏全部继承这一句。 |
| **`46-05 §5.3` 的 CC-06 会红清单** | `46-05 §5.3` | 本方案**引它而未逐条复算**（块 CL-12 已注明）。 |
| **`tests/test_render_anchor*.py` 一族的既有锚回归行号** | —— | `46-04` §6.1 只写"E-08 无直接测试"，未给该族的行号；本方案**未采录**（块 CL-06 已注明）。 |
| **块 CL-02（E-04b）与块 CL-07/CL-09/CL-13 的新负控** | 本方案 | `46-04` §6.2 没有给这四处的负控 ⇒ 本方案新拟，全部标 `[判断类]`（不是测量值）。 |
| **E-04b 三处真机的"改前原因行"** | 本方案 | `46-04` §6.3 只给了六格回放集的原因行；`p8d` 与 `p8g` `C10` 所在环的改前 `missing` **未采录**（块 CL-02 已注明：施工时必须先跑命令 2）。 |
| **CC-03 新警告的真机命中面** | 本方案 | `46-04` §2.7 给了"哪些档在哪些工作区出现过"，**没给**"研究型工作区里出现 review-only 档"的逐格清单（块 CL-09 已注明）。 |
| **`conductor.acceptance` 的 `.md` 解析器逐格读数** | `46-04` §4.3 / `43-C` C-02 | 属 CC-02，**不在本组**；本方案只登记边界。 |
| **会话侧读数**（`sid=<这一趟>` 与 `sid=None` 的差异） | `46-04` §7.7 | `46-04` 逐字："回放用 `sid=None`（CLI 口径）⇒ 六格 `user_pending` 全 `pass`；`conductor.closing` 走的是 `sid=<这一趟>`，两处差异本次未在 `projects/*/sessions` 上逐趟核对"。 |
| **`specs/m.py:75` 与 `LEG_CHECK_KINDS` 的逐条措辞比对** | `43-C` §4.4 | `43-C` 逐字："只做了集合比较（结论：只差 `c_analysis_runs` 一处），未逐条比措辞"。 |
| **`pytest` / `lint_rules.py` 的实际基线跑分** | 本方案 | 硬纪律不许跑 pytest；`0 错 / 9 警 / 49 提示`（`--strict` `0/58/48`）是**引 `46-04` §6 的基线口径**，非本次现算。 |

### 汇总三 · 施工顺序（照抄 `draft/44` J-21 的 CL 组顺序，逐位对应块）

```
1. 块 CL-04   E-06 附件半（收益 9/46，先做）
2. 块 CL-05   E-06 九节半（收益 1/46，严格标题 + 节体非空；修 reviewaccept.py:117 的 bug）
3. 块 CL-01   E-04a 分支守卫（对 33 份真表 0 处翻转，可独立上线）
4. 块 CL-03 + 块 CL-11   E-05 + CC-05（同批；分母换基线必须与第四态同批）
5. 块 CL-10   F-06 + P-03 退场 + tests/test_agent_prompts.py:808 改写（同批）
6. 块 CL-09 + 块 CL-07 + 块 CL-13（读数版）   CC-03 + CC-09 + S-05a + EE-05（共用 tests/test_agent_prompts.py:196-201 反判据）
7. 块 CL-12   CC-06 删 reviewaccept.py 555 行（必须在块 CL-04/CL-05 之后）
————————————————————————————————————————————
独立批次（不进主序）：
  块 CL-02   E-04b 覆盖面 marked —— 须人裁（建议不收紧）
  块 CL-06   E-08 锚解耦（两侧对称过滤）
  块 CL-14   EE-10 只合并"读法"
  块 CL-15   调用面与 E-15 前置（随 CL-09/CL-13 同步描述）
  块 CL-08   S-05b / S-05c（不可行，禁单独上线）
  块 CL-13 进第八格版（须人裁；DEFAULT_CHECKS 7→8）
```

### 汇总四 · 本文件的边界

1. **本文件不改任何代码、不改任何工作区文件。** 只写 `draft/48-施工方案-04-closing.md`；
   所有"改后"结论要么照抄 `46-04`（多为内存复算），要么来自本文件 §0 的**只读现算**。
2. **未跑模型、未跑网络、未跑全量 pytest、未跑 lint。** 硬纪律与 `46-04` §7.2 同。
3. **未裁定任何条目。** 四处人裁点照抄 `46-04` §6.5 / `draft/47` §5：E-04b 的覆盖面 `marked`、
   S-05 腿 3 是否动 `schema.py`、EE-05 是否进第八格、CC-03 的分组形态。
4. **`closing.py` 不在 FC-27 清单**（`draft/47` §3-C2 已复核）⇒ 本组 11 条可按普通改动走，**仍建议先改后报备**；
   反过来，本组的镜像落点里 `specs/m.py`（`agent_prompts.py` 不在清单）**是禁改区**，必须人审 + 2 名 reviewer（块 CL-09）。
5. **每改一次口径必须在 `draft/44` 那一行写下"从哪一趟起口径变了"**（`46-04` §6.4 第 1 条引 `draft/45:12`）；
   建议同批在 `readings["acceptance"]` 里落 `"reading_version"`，以 `p8g` 作口径锚点。
