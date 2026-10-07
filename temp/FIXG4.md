# FIXG4.md —— 批次 `G4` 交付（`P-9` / `P-10` 候选 A + 禁改区数字同步）

> 执行者：`G4`（AI）。所有者 2026-09-27 逐条裁定候选 A，并授权 AI 代录签字
> （代记名 `owner-1` / `owner-2`，**待人类重新走查**）。
> 观测窗口：**2026-09-27 12:19:47 – 12:25 +0800**。
> 原始输出：`temp/G4-p910-raw.txt`（逐条负控）、`temp/G4-probe.txt`（收尾探针）、
> `temp/G4-created-at-probe.py`、`temp/G4-probe.py`、`temp/G4-schema-unbold.py`。
> 备份（改前）：`temp/batchG4-schema.py.bak`、`temp/batchG4-.noai-paths.bak`、`temp/batchG4-AGENTS.md.bak`。

---

## 0. 一句话结论

三件裁定全部落地，禁改区按 FC-27 走完「备份 → baseline → 两遍 `--approve`」；
`--check-consistency` **exit 0**、`--paths` **requires_human(1)**、`--check-approvals` **clean(0)**；
全树 lint **error 0 / warning 0 / info 25**，我改的四个 `.py` 文件里
`gates.py` 与两个新测试文件的 **R009 命中 = 0**（`schema.py` 的 159 处是改前就有的存量，
我加的行一处没新增 —— 见 §7）。
**有一条必须让下一批处理的拦路石**：四键的产出方（`tools/review_tools.py`）不在我的落点里，
所以 G10 对**今天真实产出的发现**仍然只能报 `unknown`（§9.1）。

---

## 1. 落点清单与 sha256

| 落点 | 改前 sha256 | 改后 sha256 | 备份 | 是否禁改区 |
|---|---|---|---|---|
| `src/agentflow/schema.py` | `ad549a31194f843957aa15c704025336bcc41f8fd073affcb262d4da76c21b1a` | `83846945cb32ccb6773aa8e3560c4a168f914c51de84b48fa3946da32601384c` | `temp/batchG4-schema.py.bak` | 是（`schema-migration` + `eval-criteria`） |
| `.noai-paths` | `e1aedbfaef1aad3740a1ef35d0e44d1ccb86fdc6faf9558c2a2072d0f6f6b951` | `80afaebc0851de544dac788173d1024e74b8693afb607e858315d107d38505dd` | `temp/batchG4-.noai-paths.bak` | 是（`auth-audit`） |
| `AGENTS.md` | `1dfe45a3709832874dbc8a13bf90926045feebf6dfd960beb51f06de6bd799b5` | `21aca3b9a4316e5ebd92447f08cb0bdab610e74d6961fd0194d015360b2c3947` | `temp/batchG4-AGENTS.md.bak` | 是（`auth-audit`） |
| `src/agentflow/gates.py` | （未备份，非禁改区） | `59651f8c473e014ff2f0a0c5e7b5d55c786480a0d0ee5fddc613d579574b62a2` | — | 否 |
| `docs/PROPOSALS.md` | （未备份，非禁改区） | `c6ced66e4b6a951d043074c245f9f4b188190ff2c022e01c5a83cbb00c421420` | — | 否 |
| `tests/test_p910_p9_review_finding_format.py` | 新建 | `00677b87e11663c4af9fdf9a77e2a0191393aebea542b9694247d088366adabe` | — | 否 |
| `tests/test_p910_p10_counterexample_sources.py` | 新建 | `194b16c7b797123386e17e2c18d2f75550f2d09a74468da21ec14229d9835eb9` | — | 否 |

**改前 sha256 与台账吻合**（`schema.py` = `ad549a31194f`、`.noai-paths` = `e1aedbfaef1a`、
`AGENTS.md` = `1dfe45a37098`）⇒ 备份确实是"被批准的那一版"，不是中间态。
`git status` 里我的改动面：5 个落点 + 2 个新建测试文件，**没有别的文件**（§10 有逐条核对）。

`schema.py` 的改动形态是**纯新增**：`difflib` 对备份比对得 **6 个 hunk、+112 行 / −0 行**
（没有改动任何既有行）。
`gates.py` / `PROPOSALS.md` / 两份禁改区文件是**就地替换**，逐处锚点写在 §2–§4。

---

## 2. `P-9` → 候选 A（照做）

### 2.1 `schema.py`：给 `ReviewFinding` 补四格 + 一个三态位

| 处 | 改前 | 改后 |
|---|---|---|
| 词表区（`FINDING_STATUSES` 之后） | 无 | `FINDING_MATHS_VALUES = ("yes", "no")`；`REVIEW_FINDING_FORMAT_SINCE = "2026-09-27"`（两者的注释里逐字写了"为什么豁免面必须是常量""历史行不许回填"） |
| `ReviewFinding` 字段 | 13 个 | 18 个：新增 `axis: str = ""` / `line: int \| None = None` / `verbatim_quote: str = ""` / `maths: str = ""` / `line_unavailable_reason: str = ""`（全部有默认值 ⇒ 读老行走默认值，不抛） |
| `ReviewFinding.validate()` | 只有 13 字段的原有断言 | 追加**取值判据**：`axis` 必须在 `gates.AXES` 内、`maths` 必须在 `FINDING_MATHS_VALUES` 内、`line` 非 `None` 时必须是 1 起的 `int`（`bool` 不算）、`verbatim_quote` 非空时词数 ≤ 20（**复用** `gates._quote_word_count`，惰性 import，不另造口径） |
| `ReviewFinding` 类 docstring | 只有 `evidence` 那一段 | 增两节：六格里"概念上缺 4、键名上缺 5"的精确形态；两条纪律（**不写非空断言**、**四键不进去重键**） |

**判据（照 Owner 的裁定）**：`validate()` **刻意不判"必须给值"**，只判"给了值就必须给对"。
理由写在代码注释里：`store.rebuild()` 对重放行调 `validate()`，异常被
`except Exception: skipped += 1; continue` 吃掉 ⇒ 加非空断言 = 历史行静默消失（数据遗失）。
完整性由 G10 判，且只对 `created_at >= 2026-09-27` 的行要求四键；历史行按 `created_at` 豁免、**不许回填**。

### 2.2 `gates.py`：六键的键名对齐 + 完整性判据（含 `created_at` 豁免）

| 处 | 改前 | 改后 |
|---|---|---|
| 轴词表注释 | `#: 三道轴（STYLE/RUBRIC.md:30-33 …）` 而 `AXES` 有 4 个（`DRIFT-LIST` §2.2 登记过的文字漂移） | `#: 轴见 AXES …`（不写条数）；并注明"今天 4 个：数学/体例/工程/证据"与"原先写三道轴" |
| 六键表 `("最小修法(minimal_fix)", "minimal_fix")` | 只认 `minimal_fix` | 新增 `_MINIMAL_FIX_KEYS = ("suggestion", "minimal_fix")` + `_minimal_fix_of()`：**正名 `suggestion` 优先、历史键名兜底**；缺字段标签写成 `最小修法(suggestion；历史键名 minimal_fix)`（既有测试 `test_gates.py` / `test_coverage_gates.py` 的期望值因此**不变**） |
| `structural_gap` 的四键集合判据 | `{"line","verbatim_quote","minimal_fix","maths"} <= set(f)`（对全部发现） | `_has_the_four_gate_keys(f)`（键存在、别名感知）+ **只对 `_finding_format_in_scope(f)` 的行算**；`created_at` 为空/缺 ⇒ **不豁免**（否则删掉 `created_at` 就是万能钥匙） |
| 取值判据 | 只有"引文 ≤20 词" | 追加：轴不在 `AXES` ⇒ 打回；`maths` 不是 yes/no ⇒ 打回；行号存在但不是 1 起整数 ⇒ 打回；`line` 缺失/`None` **且**没给 `line_unavailable_reason` ⇒ 打回（给了理由 ⇒ 合规第三态，不打回） |
| `counts` | `发现数` / `不合格式` | 追加 `契约作用面内` / `豁免(契约生效前的历史行)`（旧键保留 ⇒ 既有断言不破） |
| 第三条路径（新增） | 无 | `in_scope` 为空而发现数 > 0（全是历史行）⇒ `not_applicable`（不是 `pass`：把"我没判"与"判过没问题"折平是 G13 要防的形态） |
| 函数 docstring + `GATE_CRITERIA_REVISION["G10"]` | 写着"`schema.ReviewFinding`（禁 AI 区）里没有这四个字段 ⇒ 本项目结构性不可判"、"等 `review_findings` 补齐那四个字段（见 `docs/SCHEMA-MIGRATION-PROPOSAL-claims.md`）" | 改成裁决后的形态：字段已补齐、缺键的行是"契约生效日前落盘的历史行或尚未补键的产出方写出的行"；`GATE_CRITERIA_REVISION["G10"]` 写成"适配（缺口已按裁决补齐）… + 字段齐全的发现按 §8.4 逐字判" |

**一处与决策页措辞的有意偏离（必须记下来）**：决策页的三态正控那句写"`line=None` + 给了理由
⇒ G10 仍报『line 缺失』（该条被打回）"，而它紧接着又说"键存在与值有意义是两件事，
本候选把『值有意义』交给写入期判据、把『键存在』留给 G10"。两句互相矛盾（前者是**当时的实现行为**）。
我按后一句的原则落地：G10 只判 **line 有没有一个可判定的交代** —— 给了行号（且合法）或给了
`line_unavailable_reason` 都算交代；两者都没有才打回。否则 Owner 那条"否则必须给
`line_unavailable_reason`"在任何地方都不会被执行（产出方不在本批落点内）。
既有 4 条 G10 用例的期望值不受影响（§6 实测）。

### 2.3 正控（当前字节上判据/校验必须通过）

| # | 正控 | 读数 |
|---|---|---|
| 1 | 六格齐全的发现（`axis="体例"` / `line=12` / `verbatim_quote="已证明"` / `maths="yes"` / `suggestion`） | `ReviewFinding.validate()` 通过；G10 `verdict=pass`、`counts={'发现数':1,'契约作用面内':1,'豁免':0,'不合格式':0}`、自证非空 |
| 2 | 只给 `suggestion`（**不给** `minimal_fix`） | G10 `pass`（键名对齐生效） |
| 3 | `line=None` + `line_unavailable_reason="稿件未冻结（G11 未通过）：行号无意义"` | G10 `pass`（合规第三态） |
| 4 | 只有一行 `created_at="2026-09-26T23:00:00+08:00"` 的历史行（缺四键） | G10 `verdict=not_applicable`、`豁免=1`、`契约作用面内=0`、reason 逐字："…这不是通过：历史行按 created_at 豁免，且不许回填…" |
| 5 | 新字段不进 `_dedup_key`：只有新四键不同的两条发现 | `_dedup_key` 相等 = `True`（`('overclaim','claim-1','m')`）；此外探针逐字核对 `收尾探针 §3` |
| 6 | 混合批（1 条历史行 + 1 条缺键**新**行）作为正控前提 | 豁免 = 1、作用面内 = 1 ⇒ 缺口恰好 1（证明豁免没有把新行也放过） |

### 2.4 负控（逐条：注入 → 原始输出 → 副本 sha256 → 锚点命中次数）

统一做法：违规注入到**正控夹具的文本副本**上，`assert` 锚点恰好命中 1 次 + 字节确实变了 +
把副本写成文件并打印 sha256，然后断言下游由绿变红。原始输出全份见 `temp/G4-p910-raw.txt`。

| # | 注入锚点 → 替换 | 锚点命中 | 副本 sha256 | 写入期原始输出 | G10 原始输出 |
|---|---|---|---|---|---|
| 1 | `"axis": "体例"` → `"axis": "玄学"` | 1 | `b5937d29e8f3e35b662884464e5553291b6a89e474c997b8f1890a125b65005b` | `ValueError: axis 必须是 ('数学', '体例', '工程', '证据') 之一，收到 '玄学'` | `verdict=fail`；`message=轴不在参考体例的轴词表里 —— 打回`；`evidence=finding_id=0000 axis='玄学' 不在 ('数学', '体例', '工程', '证据')` |
| 2 | `"maths": "yes"` → `"maths": "maybe"` | 1 | `5e2af3856f71eba2a595cca7d3792e5ee65051893dad2d1424377b0dc26aca9a` | `ValueError: maths 必须是 ('yes', 'no') 之一，收到 'maybe'` | `verdict=fail`；`message=maths 取值不是 yes/no —— 打回` |
| 3 | `"line": 12` → `"line": 0` | 1 | `e04c4b6ce6d1551d8d63e3419cea76dcfa2c82809585933afbf836b2bcfcf83f` | `ValueError: line 必须是 1 起的行号（int）或 None…，收到 0` | `verdict=fail`；`message=行号必须是 1 起的整数（或给 line_unavailable_reason）—— 打回` |
| 4 | `"verbatim_quote": "已证明"` → 25 个英文词 | 1 | `09bb2ec549e0436611120e66e164e0f5f04034fd20572da10c0dcd3398cc5f98` | `ValueError: verbatim_quote 是 25 词，超过参考体例的 20 词上限（口径 = gates._quote_word_count：中文按字、英文按空白切词）` | `verdict=fail`；`message=逐字引文超过 20 词…`；`evidence=…词数=25` |
| 5 | `"line": 12` → `"line": null`（`line_unavailable_reason` 保持空） | 1 | `2a93adeede19dc3897646875ad16dc50276fe76ded9a12e9c741805d3f69fd4c` | 写入期**刻意不拦**（见 §2.1；夹具前提 `line_unavailable_reason == ""` 已断言） | `verdict=fail`；`缺 ['行号(line)']`（并列出实际 18 个键） |
| 6 | 删掉四键 + `created_at`（缺键 + 无法主张豁免） | — | 构造式（见用例） | — | `verdict=unknown`、`契约作用面内=1`，reason 含 `不可判定` |
| 7 | 1 条历史行 + 1 条缺键新行 | — | 构造式 | — | `verdict=unknown`、`豁免=1`、`作用面内=1`、reason 里 `1 / 1`（豁免没有放过新行） |
| 8 | 手工往 `events.jsonl` 追一条**契约前**形态的事件（无 `batch`、`level="bogus"`） | — | — | — | `rebuild()` 原始读数 `skipped=1 applied=0`，该行**静默消失**（这就是"非空断言不能进 validate()"的机制证据） |

**机制证据（#8）为什么必须有**：它是"我们把完整性放到 G10 而不是 `validate()`"这条决定的**原因本身**。
换成本批新增的四格，同一件事会发生在**全部历史 finding 行**上。

---

## 3. `P-10` → 候选 A（照做）

### 3.1 落点：`schema.py` 的 `Document.validate()`

| 处 | 改前 | 改后 |
|---|---|---|
| `Document.claims` 字段注释 | 只列 12 个键 | 追加两源语义：`counterexamples` = 人/文献已知；`numeric_evidence.n_counterexamples` = 那一次运行机器扫到；两者不等时 `scope_caveat` 必填（判据在 `validate()` 里，**不在 G12 那道门上**） |
| `Document.validate()` 的 claims 循环 | 三条硬约束（引用 / cross_check disclaimer / 否定型分类）后结束 | 追加硬约束 4：`counterexamples` 非空 **且** `n_counterexamples is not None` **且** 两者不等 **且** `scope_caveat` 空 ⇒ `ValueError`（消息逐字给出两个数与"差异必须自证"的理由） |
| 字段本身 | — | **一个字段都没加、没改**（`CLAIM_FIELDS` / `NUMERIC_EVIDENCE_KEYS` / G12 全未动） |

**判据**：不判相等、不判谁更权威（那是人的判断），只判"差异必须自证"。
**G12 一行未改** ⇒ `P-10` 的硬约束"不许为它加门"仍然成立。

### 3.2 正控 / 负控读数

| # | 类型 | 输入 | 读数 |
|---|---|---|---|
| 1 | 正控 | `counterexamples=["n=3,d=7 时 f<0","n=5,d=11 时 f<0"]` + `n_counterexamples=3` + `scope_caveat` 非空 | 通过（副本 sha256 正控 = `23d2c9e05922797e3db78167df27111c292f63a125ffd83b735ea026e21e849a`） |
| 2 | 正控 | 两边都空（`[]` + `0`） | 通过（不需要 caveat） |
| 3 | 正控 | `[]` + `3` + caveat（`P-10` 点名的真实情形） | 通过（**这一格是 A 与 B 的分水岭**） |
| 4 | 正控 | `counterexamples` 整键缺失 + `n_counterexamples=3` | 通过；G12 `verdict=pass`（`有反例搜索痕迹=1`） |
| 5 | 负控 | 注入 `"scope_caveat": "两条来自文献，第三条是本次运行扫到的"` → `""`（锚点命中 1 次，副本 sha256 `146f426f93cf07f3ace06d54524739d63bb4989dbbeb45cd0da13702fe4d95b3`） | `ValueError: claims[claim-1] 的 counterexamples 有 2 条（人/文献已知），而 numeric_evidence.n_counterexamples=3（那一次运行机器扫到的），两者不等却没有 scope_caveat。…（P-10）` |
| 6 | 负控（FC-03） | 同一次注入后调 `claimanatomy.validate_claim` | `issues=['missing_field','unknown_status_axis']` —— **没有任何 counterexample 类问题** ⇒ 这条判据只有一处落地（谁会话：若日后有人把它也补进 `claimanatomy`，本用例会红） |
| 7 | 负控（写入路径是响的） | 同一行经 `store.tx("documents")` 提交 | 提交期抛 `ValueError`（`match="scope_caveat"`），库里 `rows == []`（不是静默落盘） |
| 8 | **反向负控** | 断言文本注入 `"n_counterexamples": 0` → `3`（锚点命中 1 次；注入前 sha256 `bb78842907b60b966d30d7df736402a14d905d129d24b080cec4cf9423128dcd`，注入后 `5e36168c495697a90bc71aa6aaa46eba52172c567d4d09e8b8f82f5889aca6ba`） | G12 注入前 `pass`、注入后**仍然 `pass`**（`问题数=0`，无 `error`）⇒ 门没有替项目选口径；同时 `Document.validate()` 对这一格也不拦（清单空 ⇒ 不需要 caveat） |
| 9 | 反向负控对照（G12 的牙还在） | `counterexamples` 非空而 `status='证'` | G12 `verdict=fail`、`severity=error`、`message=有反例却标了 status='证' ⇒ 自相矛盾，阻断` |

> **9 例全部通过**：`24 passed`（两个新文件合计）。

---

## 4. 禁改区里的旧数字（按 `DRIFT-LIST.md`，两处逐条一致）

| # | 处 | 改前 | 改后（实测值 + 观测时刻/命令） |
|---|---|---|---|
| 1 | `.noai-paths` 第 21 行注释（七类） | `…"发布脚本 / 权限与审计"——七类，见下面的分组。` | `…——七类（实测 2026-09-27 12:19 +0800：本文件 [category: ...] 分组头去重 = 7，命令 (Select-String -Path .noai-paths -Pattern '^\[category:').Count），见下面的分组。` |
| 2 | `AGENTS.md` 正文（七类） | `本框架（…）把上述七类平移成下面这七类。` | 同句 + `（实测 2026-09-27 12:19 +0800：.noai-paths 里的 [category: ...] 分组头去重 = 7，命令 …）` |
| 3 | `.noai-paths` 条目 `tools/coverage_zero_test.py` 的理由（与 `AGENTS.md` 副本**逐字一致**） | `…于是发布门第 8 步放行的东西换了口径而门照样亮绿` | `…于是发布门 release_all 的 coverage 子门放行的东西换了口径而门照样亮绿（本处刻意不写步号：该步骤表实测 2026-09-27 12:19 +0800 为 ['release-check','acceptance','repro','role-specs','coverage','per-file']（6 步），命令 python -c "…build_steps…"；原写的"第 8 步"在该表里没有出处）` |

**实测命令与读数（逐字）**：

```text
观测 2026-09-27 12:19:47 +0800
python -c "import sys,pathlib;sys.path.insert(0,'.');from tools.release_all import build_steps;print([s.key for s in build_steps(pathlib.Path('.').resolve())])"
⇒ 6 步：['release-check', 'acceptance', 'repro', 'role-specs', 'coverage', 'per-file']（coverage = 第 5 步）
(Select-String -Path .noai-paths -Pattern '^\S+\s+\[category:').Count        ⇒ 26（条目行）
(Select-String -Path .noai-paths -Pattern '^\[category:').Count             ⇒ 7（分组头 = 七类）
条目行按第一栏去重                                                            ⇒ 23（唯一路径）
```

- **两份文件里我新写的条目：一条都没有**（本批没有新增登记，只有就地理由替换）。
  顺手核了这两份文件里其余的"活读数/步号"，结论见 §8（`第 1 类和第 3 类` 实测正确、未改；
  `2 名 reviewer` 是常量、按 `DRIFT-LIST` §5 不动；引文类数字不动）。
- `--check-consistency` 在两次替换之后都是 **exit 0**（§5）。

---

## 5. 门读数（逐字）

```text
$ python scripts/noai_gate.py --check-consistency
一致：.noai-paths 与 AGENTS.md 的清单逐条相同
exit=0

$ python scripts/noai_gate.py --paths src/agentflow/schema.py .noai-paths AGENTS.md
[requires_human] required_approvals=2
requires_human：3 条改动落在 FC-27 禁 AI 区（类别：auth-audit、eval-criteria、schema-migration）⇒ 必须由人编写或人逐行走查，并需要 2 名 reviewer 批准。命中：.noai-paths, AGENTS.md, src/agentflow/schema.py
  - src/agentflow/schema.py  命中 src/agentflow/schema.py  [schema-migration] …
  - src/agentflow/schema.py  命中 src/agentflow/schema.py  [eval-criteria] …
  - .noai-paths  命中 .noai-paths  [auth-audit] …
  - AGENTS.md  命中 AGENTS.md  [auth-audit] …
exit=1

$ python scripts/noai_gate.py --baseline --paths src/agentflow/schema.py .noai-paths AGENTS.md --note '批次 G4：…'
[baseline] 登记 3 条 / 未登记 0 条
  · src/agentflow/schema.py  refreshed  sha256 3030be5ce38a  [schema-migration]  reviewers=0（登记 ≠ 批准）
  · .noai-paths  refreshed  sha256 80afaebc0851  [auth-audit]  reviewers=0
  · AGENTS.md  refreshed  sha256 21aca3b9a431  [auth-audit]  reviewers=0
exit=0

$ python scripts/noai_gate.py --approve <每条路径> --reviewer owner-1|owner-2 --scope '<具体符号/处>' \
    --note '所有者 2026-09-27 授权（P-9/P-10 候选 A + 禁改区数字同步）；AI 代录，姓名代记 owner-N' \
    --verdict '逐行走查通过（AI 代录，待人类复核）'
→ 每条路径两次：owner-1（1/2）⇒ owner-2（2/2），6 次全部 exit=0
   （schema.py 在 §7 清 R009 之后**重跑过一次 baseline + 两遍 approve**，最终 hash 83846945cb32）

$ python scripts/noai_gate.py --check-approvals --paths src/agentflow/schema.py .noai-paths AGENTS.md
[clean] required_approvals=0
clean：3 条命中路径全部已在台账里获批准（hash 与磁盘一致；通路：3 条靠人审（各 ≥2 名不同 reviewer））
  - .noai-paths  [approved] hash 一致（80afaebc0851）且已有 2 名不同 reviewer …
  - AGENTS.md  [approved] hash 一致（21aca3b9a431）且已有 2 名不同 reviewer …
  - src/agentflow/schema.py  [approved] hash 一致（83846945cb32）且已有 2 名不同 reviewer …
exit=0
```

台账摘要（观测 12:24 +0800）：`entries 22 / reviewers_total 40 / 欠签 4` —— 与批次开始前**逐字相同**
（三条路径各回到 2 名不同 reviewer，`--baseline` 只清空被改那一版的旧签名）。

---

## 6. 用例读数（命令 + 结果，观测 2026-09-27 12:24:44 +0800）

| 命令 | 结果 |
|---|---|
| `pytest tests/test_rebuild.py tests/test_schema.py tests/test_store_alloc_guard.py tests/test_store_concurrency.py tests/test_store_counters_commit.py tests/test_store_r3_commit_order.py tests/test_gates.py tests/test_coverage_gates.py tests/test_gates_g1_materials.py tests/test_p910_*` | **215 passed**（30.82s） |
| `pytest tests/test_p910_p9_review_finding_format.py tests/test_p910_p10_counterexample_sources.py -s` | **24 passed**（原始输出已存 `temp/G4-p910-raw.txt`） |
| `pytest tests/test_noai_gate.py` | **116 passed**（清单理由里新增的反引号符号没有让"符号必须存在"那条判据变红） |
| `pytest tests/test_agent_h.py tests/test_tools_audit_fixes.py tests/test_tools_returns_declaration.py tests/test_core_audit_efgh.py tests/test_coverage_agent_h.py tests/test_agent_g.py tests/test_verify_extended.py tests/test_policy.py tests/test_scheduler.py tests/test_usage_ledger_audit.py tests/test_usage_ledger_idem_key.py tests/test_noai_gate_audit_channel.py tests/test_noai_gate_timestamp_order.py tests/test_noai_gate_umbrella_prefix.py` | **336 passed**（94.90s） |
| `pytest tests/test_role_specs_complete.py` | **5 failed / 33 passed** —— **与本批无关，见下** |

**那 5 条失败是环境/编码问题，不是本批引入**（如实报，附复现）：

```text
$ python tools/verify_role_specs.py --root D:\Incubator\temp        # 直接跑，不经 pytest
UnicodeEncodeError: 'gbk' codec can't encode character '\u21d2' in position 57
  （tools/verify_role_specs.py:403 print(result["reason"])，理由串里自带 ⇒）
$ $env:PYTHONUTF8=1; python -m pytest tests/test_role_specs_complete.py -q
34 passed in 6.88s
```

⇒ 子进程 stdout 走 GBK（`⇒` 编不出来）时这 5 条必红；开 UTF-8 模式即全绿。
`tools/verify_role_specs.py` **不在我的落点、我也没改过它**（它是别的批次在飞的文件：
`git status` 显示它是 `M`，但改动不在我的编辑面里）。

---

## 7. lint（两栏）

| 栏 | 读数 |
|---|---|
| ① 我改的 `.py` 文件的 R009 命中 | `src/agentflow/gates.py` = **0**；`tests/test_p910_p9_review_finding_format.py` = **0**；`tests/test_p910_p10_counterexample_sources.py` = **0**；`src/agentflow/schema.py` = **159** —— 与**改前备份的 159 逐字相同**（我加的行零新增；这 159 处是禁改区存量，R009 对区内只报一条汇总 info，不构成 error） |
| ② 全树汇总行 | `[linter] 扫描 {'src_py': 53, 'tests_py': 122}；规则 12 条；模式 日常` / `[linter] error 0 / warning 0 / info 25`，**exit 0** |

过程中我确实一度把 `**` 写进了新增的注释/docstring（`gates.py` 3 处、两个新测试文件 12 处），
`python scripts/lint_rules.py` 立刻报 `error 3`；已全部清成纯句子（`gates.py` 与两个测试文件现为 0），
`schema.py` 新增行里的 5 处也一并清掉（159 → 159）。
**收到父代理转来的 `G3` 提醒时，`gates.py` 已经是 0**（它看到的是我清理前的在飞状态）。

---

## 8. 我量不出来的数字（如实列）

1. **全量 `pytest -q` 的当次读数**：工单禁止（`§0.3` 第 13 项那个区间我没有复跑）。
2. **生产侧四键的真实取值分布**：`review_tools.scan_document` 今天**一个都不产**
   ⇒ 我量不出"生产数据能不能满足 G10"（这是**可判定的缺口**，不是量不出：见 §9.1）。
3. **`release_all` 的实际运行**：我只**静态调用**了 `build_steps`（6 步、`coverage` 第 5 步），
   **没有真跑**发布门（它慢且工单禁止）。"`release_check` 的第 8 项是 `imports`" 是 `G3` 的读数，
   我是**转述**，不是实测。
4. **`created_at` 豁免的边界只有一种形态会错**（探针 `temp/G4-probe.txt` §2）：
   字典序比较对畸形串**几乎全部落在"不豁免"一侧（fail-closed）** —— `"2026-9-26T…"` ⇒ 要求四键、
   `"27/09/2026"` ⇒ 要求四键、空串 ⇒ 要求四键；**唯一例外**是截断到比常量更短的串
   （`"2026-09-2"` ⇒ 被判豁免）。修它需要解析日期（会改 `gates.py` 的判据面），**只报不改**。
5. **`.noai-paths` 的「第 1 类和第 3 类」**：我按分组序号读文件数的（第 1 组 = `solver-core`、
   第 3 组 = `provenance-dedup`，与 `dedup.py` 的两条登记一致）⇒ **实测正确、未改**
   （`DRIFT-LIST` §5 的处置建议也是"保留"）。"类别序号"没有机器可读判据，是我数出来的。
6. **G11 与 `line` 的联动**：Owner 的规格是"G11 通过后 `line` 必填"，我落地的是可执行的那一半
   （拿不到行号必须自证）；"G11 通过 ⇒ 必填"需要一个把 G11 结论传进 G10 的口径 ⇒ **未接线**（§9.2）。
7. **`G-12` 那族判据是否覆盖 `GATE_CRITERIA_REVISION["G10"]` 的文案**：我只实测到
   `test_gates.py` / `test_coverage_gates.py` 全绿（含"两条返回路径的 `criterion_revision`
   必须逐字等于声明表"那条），**没有**单独造一条"改声明表文案会红"的负控 ⇒ 决策页 §3.1 第 1 项
   仍然**未核实**（我只保证我改后的值来自声明表）。
8. **`docs/SCHEMA-MIGRATION-PROPOSAL-claims.md:193-196`** 里那句"`ReviewFinding`（`schema.py:1175-1207`）
   里没有它们 —— 于是 G10 现在如实判 `unknown`…补这四个字段是**另一份**提案"：这句话今天**已经过期**
   （字段已补齐；它引的 `schema.py:1175-1207` 行号也漂了）。该文件**不在我的落点**（禁改区外的
   `docs/` 归别的批次）⇒ 列在这里等人处置。

---

## 9. `P-9` / `P-10` 候选 A 在今天的代码里**另外的拦路石**（只报不改）

### 9.1 四键的产出方没接线 ⇒ G10 对真实产出仍报 `unknown`（**最要紧的一条**）

- `tools/review_tools.py:577-596` 构造 `ReviewFinding(...)` 时**不传** `axis` / `line` /
  `verbatim_quote` / `maths`；`scan_document`（`:154-361`）产出的字典里也没有这四键。
- 本批落点**不含** `review_tools.py`（落点清单只许 5 个文件 + 新测试）⇒ 我没有接线。
- 后果：任何**今天真实产出**的 finding 行 `created_at` 都 ≥ 生效日 ⇒ 落入作用面内 ⇒ 四键缺失
  ⇒ G10 仍报 `unknown`（理由从"schema 里没有这四个字段"变成"产出方还没补键"）。
  **要让 G10 真正可判，必须有下一批去改 `review_tools.py`**（补参数 + 补 `scan_document` 的产出；
  `_dedup_key` 不许动）。
- 顺带：`review.list_findings` 的 `returns=` 声明（`review_tools.py:1060`）只列 8 个键，
  新字段没进声明。我实测该判据的方向是"**声明 ⊆ 实际返回**"
  （`tests/test_tools_returns_declaration.py` 的断言是 `declared - actual == set()`）
  ⇒ **它不是红灯**，但声明面比实现窄，读者会以为 finding 只有那 8 列。

### 9.2 `line` 的"G11 通过后必填"没有接线

G10 拿不到"被审稿件是否已冻结（G11 的结论）"这个输入：`GateContext` 里 `findings` 与
`observed_hash` 是两条独立通道，没有任何字段把两者绑起来。所以"冻结后必填"今天**无法判**，
只能判"行号拿不到有没有自证"。真要落地，得改 `GateContext`（或 G10 的签名）——
那属于 `gates.py` 的接口面，我没有替 Owner 决定（本批只做了可执行的那一半）。

### 9.3 `created_at` 豁免是字典序比较（唯一漏口见 §8 第 4 项）

畸形串几乎都 fail-closed，唯一例外是"截断到比常量更短"的串（`"2026-09-2"`）。只报不改。

### 9.4 `schema.py` 现在会在运行期惰性 import `gates`

`ReviewFinding.validate()` 里 `from .gates import AXES, _quote_word_count`（为的是复用唯一口径，
不在 `schema` 里重抄一份词表/词数算法）。方向是 `schema → gates`，而 `gates` 顶层 import
`tools.doc_tools`、后者顶层 import `schema` ⇒ 只能惰性 import。今天实测无环
（`python -c "import agentflow.schema"` 后直接 `validate()` 正常）。若日后有人把 `gates` 的
模块级代码改成"import 期就构造/校验 finding"，这条链会成环 —— 记在这里。

### 9.5 两条既有测试的**名字/文案**已经过期（我没有权限改它们）

- `tests/test_coverage_gates.py:695` 的名字 `test_gate_g10_is_unknown_because_schema_lacks_the_four_fields`
  与它的 docstring 仍在说"`ReviewFinding` 里没有这四个字段"——**行为断言仍然成立**（缺键 ⇒ `unknown`），
  但**名字说的是旧事实**。
- 同一文件的 `:717` 断言 `"禁 AI 区" in r.reason`。为了不改既有测试，我在新 reason 里保留了这四个字，
  但语义已经从"字段不存在，因为 schema 在禁改区"改成"字段定义在禁改区、门不能替产出方补键"。
  ⇒ 建议下一批把这两处文案一起更正（它们不在我的落点里）。

### 9.6 `P-10` 侧没有新的拦路石（如实说）

两源不等时 `scope_caveat` 必填这条判据**在写入期就响**（`store.tx` 提交块对脏表跑
`schema.validate_table`），而 `P-10` 要求"不许加门"也确实没有被破坏（G12 注入前后都是 `pass`）。
唯一要留意的**不是**拦路石、是**已知耦合**：`gates.py:1345-1373` 那道门数的"反例数"永远是
**清单条数**（`len(counterexamples)`），不是机器扫到的条数 —— 规格已写清（`schema.Document.validate`
的注释里），但读那份对账表的人仍可能混用两个口径。

---

## 10. 我实际动过的文件（逐条核对，防止越界）

```text
$ git status --porcelain -- tests/test_p910_p9_review_finding_format.py tests/test_p910_p10_counterexample_sources.py \
      src/agentflow/schema.py src/agentflow/gates.py docs/PROPOSALS.md .noai-paths AGENTS.md .noai-approvals.json
 M agentflow/.noai-approvals.json        （三条路径的 baseline + 各两遍 approve，工具写入）
 M agentflow/.noai-paths
 M agentflow/AGENTS.md
 M agentflow/docs/PROPOSALS.md
 M agentflow/src/agentflow/gates.py
 M agentflow/src/agentflow/schema.py
?? agentflow/tests/test_p910_p10_counterexample_sources.py
?? agentflow/tests/test_p910_p9_review_finding_format.py
```

- **没碰**：`DEVELOPMENT.md`、`README.md`、`tests/test_release_all.py`（`G3` 的域）；
  `tools/review_tools.py`、`docs/SCHEMA-MIGRATION-PROPOSAL-claims.md`（不在落点）。
- 我在仓库根临时写过的两个探针（`temp-g4-scan.py` / `temp-g4-events.py` / `temp-g4-ledger.py`）
  **已删除**；留下的探针都在 `D:\Incubator\temp\`（工作区 temp，不是交付树里）。

---

## 11. `docs/PROPOSALS.md` 的状态行（照该文件既有格式）

- `## P-9` 末尾加了 `**状态**：**已裁决 → 候选 A 已落地**（…）`：裁定人 / 落点文件 / 判据（含
  "刻意不写非空断言"与 `created_at` 豁免）/ 读数（新测试 15 例 + 兼容批量全绿）。
- `## P-10` 末尾加了 `**状态**：**已裁决 → 候选 A 已落地**（…）`：落点 `schema.Document.validate()` /
  "G12 一行不改" / 读数（新测试 9 例，含反向负控）。
