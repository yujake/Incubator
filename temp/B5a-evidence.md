# B5-part-1（`b9f229e3`）证据：词表与契约（P-21 / P-22+P-23 / G-24③ / G-25 / P-17 / P-4 / P-5 / G-46 / X-1 / D-2.3+D-2.5）

> 工单：`temp/B5-workorder.md`（**指定子集**）。
> 观测时刻：本文件所有计数均为 **2026-09-26T03:26–03:52** 窗口内的观测值（区间 + 时刻，不给单一定值）。
> 环境：`$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'; cd D:\Incubator\agentflow`。
> 计数一律读退出码落文件、不接管道（除少数只为取文本的展示性命令）。

## 0. 范围与交还清单

### 0.1 本批做了（10 项）

| 节 | 项 | 落点 | 状态 |
|---|---|---|---|
| §1.1 | `P-21` | `schema.py`（注释护栏） | **撤回（前提不成立）**，见 §1.1 |
| §1.2 | `P-22`+`P-23` 登记表部分 | `tools/vocab_census.py` + 2 个测试 | 完成 |
| §1.3③ | `G-24` 第 3 小节 | `cancellation.py` + `tests/test_cancellation.py` | 完成（**口径更正**：`"user"` 是真的） |
| §1.4 | `G-25` | `fs_tools.py`、`ocr_tools.py` | 完成 2/3（第 3 处交还） |
| §1.5 | `P-17` | `schema.py` + `tests/test_schema.py` | 完成 |
| §1.6 | `P-4` | `interactions.py` + `tests/test_interactions.py` | 完成 |
| §1.7 | `P-5` | `textutil.py`（唯一实现）+ `doc_tools.py` + `verify.py` | 完成 |
| §1.9 | `G-46` | `scripts/noai_gate.py` + `tests/test_noai_gate.py` | 完成 |
| §1.10 | `X-1` | `scripts/release_check.py` | 完成 |
| §1.8b | `D-2.3`+`D-2.5` | `tools/release_all.py` + `tests/test_release_all.py` | 完成 |

### 0.2 交还给 **B5-part-2** 的项（我没做，逐条给理由）

1. **§1.3① `agent_e.py::check_formal` / `_formal_refusal` 的 `reason` 词表** —— 工单指定 B5-part-2；
   `agent_e.py` 正被 B4 改 `.call(` 调用面，且 B8-part-1 在改 `formalgw.STATUSES`（要接 `import_unavailable`）。
2. **§1.3② `agent_f.py::step` 的 `outcome` 局部词表** —— 工单指定 B5-part-2。
3. **§1.11 `R010` 对 `ocr.run` 的常驻 warning 归宿** —— 工单指定 B5-part-2；两个候选落点
   （`scripts/lint_rules.py` 的 R010 登记 / `DEVELOPMENT.md`）分别属于 B4 与 B6 的文件面。
   ⚠️ 我**没有**动 `ocr.run` 的任何声明（`side_effect=` / `declared_external=`），只改了同文件
   `## 副作用等级` 那一段的**散文**（见 §1.4）。
4. **§1.2 里 `scripts/lint_rules.py` 的 `R011` 改动** —— 工单指定 B5-part-2；`lint_rules.py` 由 B4 改。
   我在 `tools/vocab_census.py` 侧把接口备好了：`reserved` / `unclaimed` / **`registered_not_dead`**
   三个键 + `reserved_total` / `unclaimed_total` / `registered_not_dead_total` 三个计数，
   R011 直接读它们即可（见 §1.2 的"给 R011 的接口"）。
5. **`G-25` 第 3 处（`verify_tools.py:175` 的"折成三态"）** —— 主控明令不许改 `verify_tools.py`
   （B8-part-1 在改同一文件）。见 §1.4.3 的精确交还说明。
6. **`table_tools.py::assert_request_id_in_space` 的冗余上限守卫** —— `P-4` 的 `PROPOSALS` 提案
   说"随后删掉工具层那道守卫（判据只有一份）"，但工单 §1.6 只要求"上限下沉进该函数"。
   我**保留**了那道守卫（删它会改变工具层的错误类型：`ToolError` → `ValueError`，
   会波及 `table_tools` 的 fail 包装与既有测试）。见 §1.6.4 —— 这是一条**人裁项**。
7. **`table_tools.py` 里硬编码的 `9999`** —— 同一函数里写死了 `int(digits) > 9999`，
   而 `store.MAX_ID` 才是唯一定义处。我改的 `next_prefixed_id` 已 import `MAX_ID`；
   工具层那处仍是第二份字面量。**超出 §1.6 授予的范围，未动**，交人裁。

### 0.3 新发现的缺陷（本批顺带发现，未登记编号）

**`tools/release_all.py::Step.env` 默认空字典 ⇒ Windows 上 `CreateProcess` 失败（`WinError 87`）。**
见 §1.8b.4。已修（`env=step.env or None`），但它是一个**独立的、之前没有任何判据覆盖**的缺陷，
建议主控给它一个编号。

---

## 1.1 `P-21`：**撤回（前提不成立）** —— 我没有改 `verify.py` 的 `no_results`

### 1.1.1 工单 §1.1 的前提是错的（登记册串了两个词表）

工单原文说"`schema.SEARCH_OUTCOMES` 登记值是 `no_result`（`schema.py:76`）"。
**实测不是。** 原始输出（03:27）：

```
$ python -c "import agentflow.schema as S; print('SEARCH_OUTCOMES=', S.SEARCH_OUTCOMES); print('TASK_OUTCOMES=', S.TASK_OUTCOMES)"
SEARCH_OUTCOMES= ('ok', 'no_results', 'search_failed', 'gave_up')
TASK_OUTCOMES= ('ok', 'no_result', 'not_applicable', 'refused', 'failed', 'cancelled')
```

即：**`no_results`（复数）是 `SEARCH_OUTCOMES` 的真实登记值；`no_result`（单数）属于 `TASK_OUTCOMES`。**
两者是**两个字段的两个命名空间**：

- `SEARCH_OUTCOMES` → `search_requests.outcome`（一次搜索请求的终局）；
- `TASK_OUTCOMES` → `tasks.outcome`（一次召唤的终局）。

`verify.py` 里那 4 处 `no_results` 说的正是 `search_requests.outcome` ⇒ **它们是对的**。
若按工单字面去改，就会**制造** P-21 自己警告的那种伤害（教人写一个不在 `SEARCH_OUTCOMES` 里的值）。

### 1.1.2 "我没改"的证明

```
$ Select-String -Path src\agentflow\verify.py -Pattern 'no_results'   # 改后
current count=4 backup count=4
the no_results LINES are byte-identical (P-21 not applied)
```

⇒ `verify.py` 的 4 行 `no_results` 与改前备份**逐字节相同**。
（注：`verify.py` 的**整体** sha256 变了，但那是 `P-5` 的引用解析统一所致，见 §1.7；
`no_results` 相关的文本一个字都没动。）

改后词表真值（`SEARCH_OUTCOMES` 逐字不变 = P-21 的正控）：

```
SEARCH_OUTCOMES = ('ok', 'no_results', 'search_failed', 'gave_up')
TASK_OUTCOMES   = ('ok', 'no_result', 'not_applicable', 'refused', 'failed', 'cancelled')
no_results in SEARCH_OUTCOMES: True
no_result  in TASK_OUTCOMES  : True
```

### 1.1.3 交付的替代护栏（只加注释，不许动词表取值）

按主控指示，在 `schema.py` 两个词表旁各写了一段**互相指认**的护栏注释：

- `SEARCH_OUTCOMES`（`schema.py:76-88`）：写明本词表是**复数** `no_results`、属于
  `search_requests.outcome`；`TASK_OUTCOMES` 是**单数**；并写明"错一个字母不会有任何东西变红"；
  末尾**如实记录** `P-21` 曾经把两者读串、已撤回。
- `TASK_OUTCOMES`（`schema.py:1274-1283`）：反向指认 `SEARCH_OUTCOMES`，要求两处成对读。

词表**取值**未动（正控见 §1.1.2）。`lint` 后 `schema.py` 无新增 error
（它本就在 `R009` 的"禁改区 13 个文件"豁免名单里，见 §F）。

---

## 1.2 `P-22` + `P-23`：登记为"预留"（选项 c），两栏永不合并

### 1.2.1 主控裁定与理由（原样照抄，工单 §1.2）

> 选 (c)：**最便宜且不撒谎**（P-23 自己推荐 (c)）。删词表值（选项 b）要动 `schema.py`
> 且有"追溯性"争议；补产出（选项 a）对 `quote_mismatch` **不是接线而是新能力**
> —— 实测证据：`quoteverify.check_quote` 的 `reason` 取值只有
> `no_text_layer` / `empty_quote` / `substring_match` / `substring_match_declared_range` /
> `substring_match_fulltext` / `not_found` / `not_found_page_unknown` —— **根本没有
> "找到了但不一样"这一档**。所以 (a) 会正好撞上 P-22 自己的负控
> （"只写了名字、没有 code 能算出它 ⇒ 审计必须仍然报死取值"）。
>
> - **登记表只能有一处**：`tools/vocab_census.py` 的 `RESERVED_VALUES`
>   （现已存在但为空）。**不许**在 `schema.py` 里另写一份"预留"标记（FC-03）。
> - **两栏永不合并**：`reserved`（无产出但已登记）/ `unclaimed`（无产出且无人认领）。
>   `reserved` **不是"通过"**，它必须照样打印出来（静默豁免是本项目最忌的形态）。

（我把这段理由同时写进了 `vocab_census.py::RESERVED_VALUES` 的注释里，出处标注为工单裁定。）

### 1.2.2 改前（观测 03:27）

```
$ python tools\vocab_census.py
[vocab-census] 词表 20 个 / 产出点 50776 行（0.4s）
[vocab-census] 栏一：已登记为预留 0 个
[vocab-census] 栏二：无人认领 4 个
  DEP_KINDS：2 个取值在 src/ 里找不到产出点 —— ['proposition', 'prior_art']
  DOC_KINDS：1 个取值在 src/ 里找不到产出点 —— ['reproduction_report']
  FINDING_KINDS：1 个取值在 src/ 里找不到产出点 —— ['quote_mismatch']
[vocab-census] 两栏合计 4 个（这一行只是诊断；判定请分别看两栏，不许用合计代替分栏）
exit=1
```

### 1.2.3 改后（观测 03:38）—— 两栏分开打印

```
$ python tools\vocab_census.py
[vocab-census] 词表 20 个 / 产出点 50884 行（0.4s）
[vocab-census] 栏一：已登记为预留 7 个（其中 3 个今天普查看不见它是死取值 —— 见栏一附）
  DEP_KINDS.prior_art：预留 —— 死取值。留着的理由：FC-23 的『先行工作』……
  DEP_KINDS.proposition：预留 —— 死取值。agent_g.register_dependency 的 kind 取值里没有 proposition。……
  DOC_KINDS.reproduction_report：预留 —— 死取值。agent_g 只写 note/paper 一类的稿件……
  FINDING_KINDS.quote_mismatch：预留 —— 死取值。两条 code→kind 的生产映射都没有它……
[vocab-census] 栏一附：已登记为预留、但今天普查**看不见它是死取值** 3 个 ⇒ 需人确认是『同形不同义』还是『登记已过期』
  DEP_KINDS.dataset：预留（普查未见其为死取值）—— …文献类型码 `"dataset": "Z"`…
  DEP_KINDS.lemma：预留（普查未见其为死取值）—— …`formalgw._DECL_KEYWORDS` 的 Lean 关键字 `"lemma"`…
  DOC_KINDS.survey：预留（普查未见其为死取值）—— …`providers.py` 里是主题类别…
[vocab-census] 栏二：无人认领 0 个
[vocab-census] 死取值合计 4 个（这一行只是诊断；判定请分别看两栏，不许用合计代替分栏）
[vocab-census] 已知缺口：反向（漏词表…）本版未实现 —— 它的口径是 P-22/P-23 的人类裁决项
exit=1
```

每一条登记都带**逐条理由**（值 / 为什么现在无产出 / 留着的理由）。

### 1.2.4 ⚠️ 口径更正：`survey` / `lemma` / `dataset` **不是** `dead`，所以另立"栏一附"

工单要求"至少覆盖 `survey`"，并自己写明"它在 `providers.py` 里是**主题类别** ⇒
**机械普查看不见它**"。这与"登记表 = 死取值的豁免名单"直接冲突：

- 原实现里 `RESERVED_VALUES` **只在给 `dead` 分栏时被查**：
  `bucket = reserved if (name, v) in RESERVED_VALUES else unclaimed`。
  一个**不在 `dead` 里**的值，登记了也**一个字都不会打印** —— 那比静默豁免更糟
  （登记表看上去处理了它，输出里却查无此条）。
- 我把栏一改成**按登记表原样打印**，并把"登记了但普查不认为它是死的"单独标成
  **栏一附**。于是 `survey` / `lemma` / `dataset` 三条都**可见**，
  且"同形不同义"与"这条登记其实过期了（已经接线）"两种成因都必须被人看见。
- `capabilities:UNKNOWN_SIDE_EFFECT` **只写在模块 docstring 里、不进登记表**：
  它不是任何词表里的取值，而是 `capabilities.py` 的一个模块级常量
  （`UNKNOWN_SIDE_EFFECT = "unknown"`），本工具的判据是"以 `VOCAB_SUFFIXES` 结尾的
  字符串元组"，单个常量不在扫描范围内。给一个不存在于任何词表里的键登记"预留"没有意义。

### 1.2.5 负控（成对，注入是真的）

**注入**（把一条已登记为预留的值的键改坏，于是登记不再匹配）：

```diff
-    ("FINDING_KINDS", "quote_mismatch"): (
+    ("FINDING_KINDS", "quote_mismatch_INJECTED_OFF"): (
```

注入后运行（原始输出）：

```
[vocab-census] 栏一：已登记为预留 7 个（其中 4 个今天普查看不见它是死取值 —— 见栏一附）
[vocab-census] 栏一附：已登记为预留、但今天普查**看不见它是死取值** 4 个 ⇒ 需人确认是『同形不同义』还是『登记已过期』
  FINDING_KINDS.quote_mismatch_INJECTED_OFF：预留（普查未见其为死取值）—— 死取值。……
[vocab-census] 栏二：无人认领 1 个
  FINDING_KINDS：1 个取值在 src/ 里找不到产出点 —— ['quote_mismatch']
exit=1
```

⇒ `quote_mismatch` **从 `reserved` 挪到了 `unclaimed`**（"栏二：无人认领 1 个"）。

放回后（原始输出）：

```
[vocab-census] 栏一：已登记为预留 7 个（其中 3 个今天普查看不见它是死取值 —— 见栏一附）
  FINDING_KINDS.quote_mismatch：预留 —— 死取值。……
[vocab-census] 栏二：无人认领 0 个
```

⇒ 回到 `reserved`。三次运行的完整输出另存 `temp/_b5a_negctl.txt`。

### 1.2.6 给 `R011`（B5-part-2）的接口

`census()` 现在返回：

```
"reserved"                    # 登记 ∩ 死取值（会被打印，带理由）
"unclaimed"                   # 死取值 − 登记（无人认领）
"registered_not_dead"         # 登记 − 死取值（同形不同义 / 登记过期）
"dead_total" / "reserved_total" / "unclaimed_total" / "registered_not_dead_total"
"reserved_reasons"            # {"词表.取值": 理由}
```

恒等式（有测试守）：`reserved_total + unclaimed_total == dead_total`。
R011 按工单口径：`unclaimed` 非空 ⇒ `error`（或既有等级），`reserved` 和
`registered_not_dead` 非空 ⇒ `info`，**两栏分开打印**。

### 1.2.7 测试

`tests/test_vocab_census.py`：`10 passed`（观测 03:38）。
其中新增：真仓库上 4 条真死值在 `reserved` 且不在 `unclaimed`；
3 条同形不同义在 `registered_not_dead`；每条登记必须有理由；
以及"摘掉一条 ⇒ 挪到 unclaimed；放回 ⇒ 回到 reserved"的负控用例。

---

## 1.3③ `G-24` 第 3 小节：`cancellation.py::CancelReason.by`

### 1.3.1 ⚠️ 口径更正：docstring 里的 `"user"` **是代码里真实存在的**

工单说"删掉 docstring 里那个代码里不存在的 `"user"`"，负控是
`rg '"user"' src/agentflow/cancellation.py ⇒ 0`。**实测两处都不成立**：

```
$ python -c "from agentflow.conductor import Conductor; import inspect; print(inspect.signature(Conductor.cancel))"
Conductor.cancel signature: (self, reason: 'str' = 'user', *, detail: 'str' = '', by: 'str' = 'user') -> 'dict'
```

⇒ `by="user"` 是**公开 API 的默认值**，是一条真实可产出的取值（`conductor.py:1050`）。
且 `cancellation.py` 里 `"user"` 的 4 处出现**全部合法**：

```
87: "user",              # 人/调用方显式取消          ← CANCEL_CODES 的成员
109: #:   user               —— `Conductor.cancel` 的默认 `by="user"`   ← 我新增的产出点注释
115: "user",            ← CANCEL_BY_VALUES 的成员
210: def cancel(self, reason: str = "user", *, detail: str = "", by: str = "unknown") -> CancelReason:
```

故工单那条负控（⇒ 0）**不可能达成**，除非删掉 `CANCEL_CODES` 里真实的 `code` 取值。
⇒ 我按**代码事实**立词表，未删 `"user"`（与 §1.1 的处置同一纪律：以盘上代码为准）。

### 1.3.2 交付物

新增 `cancellation.py::CANCEL_BY_VALUES = ("unknown", "user", "deadline", "budget", "conductor.dispose")`，
每条注明产出点；docstring 从散文改成指向该词表。并写明 **`by` 刻意不是硬枚举**
（`Conductor.cancel(by=...)` 是公开参数，调用方用它标自己是谁；锁成枚举会拒掉合法调用方
并让"谁喊的停"这条审计信息**变少**）——与封闭的 `code`（`CANCEL_CODES`）形成对照。

### 1.3.3 负控（成对，注入是真的）

**注入**：往 `CANCEL_BY_VALUES` 里塞一个不存在的取值。

```diff
 CANCEL_BY_VALUES: tuple[str, ...] = (
     "unknown",
     "user",
     "deadline",
     "budget",
     "conductor.dispose",
+    "INJECTED_invented_source",
 )
```

变红（原始输出）：

```
>           assert f'by="{v}"' in blob or f'by: str = "{v}"' in blob, (
                f"CANCEL_BY_VALUES 里的 {v!r} 在 src/ 里找不到产出点 ⇒ 这是一个编造的值"
            )
E           AssertionError: CANCEL_BY_VALUES 里的 'INJECTED_invented_source' 在 src/ 里找不到产出点 ⇒ 这是一个编造的值
FAILED tests/test_cancellation.py::test_cancel_by_values_are_all_really_produced_in_src
1 failed, 21 passed in 1.30s
```

取回后：`22 passed`（观测 03:35）。⇒ 判据真的读代码，不是"恰好对字面量成立"。

---

## 1.4 `G-25`：三处 docstring 与实现不符（2/3 完成，第 3 处交还）

### 1.4.1 ① `tools/fs_tools.py::_effective_roles`（整段抄错）

**文档原话（改前）**：

> 为什么要在这里做：`build_registry` 会把全部 `ROLES` 传进来，
> 于是本模块的 **8 个表工具（含 `create/update/delete`）** 会被声明给所有角色 ——
> 包括只读的 C 与 H。**实测过：`AgentH` 的工具面里出现了 `table.update`**，
> 即 审校者手里有能改稿件的刀。

**实现事实**（实测）：

```
$ python -c "from agentflow.tools import fs_tools as F; print([f.__name__ for f in F._TOOL_FUNCTIONS]); print(sorted(s.name for s in F.tool_specs()))"
['fs_list', 'fs_read', 'fs_write', 'fs_delete', 'fs_move', 'fs_stat', 'fs_search']   ← 7 个
['fs.delete', 'fs.list', 'fs.move', 'fs.read', 'fs.search', 'fs.stat', 'fs.write']
```

⇒ 本模块只注册 **7 个 `fs.*`**，`_TOOL_FUNCTIONS` 全是 `fs_*`，**`table.*` 一个都不来自本模块**。
那段 docstring 与 `table_tools.py::_effective_roles` **逐字相同**（整段复制），
读它的人会以为 `fs_tools` 在管表工具。

**改后**：docstring 改为本模块自己的事实（7 个 `fs.*`、写类落在 `SIDE_EFFECTS_WRITE`
的被摘掉），并写明"这段曾经是 `table_tools` 的整段复制"。

**行为中性证明**（函数体逐字节未变）：

```
co_code (bytecode) identical : True
co_names identical           : True
co_consts identical          : False     ← 只因为 docstring 常量变了
docstring changed (expected) : True
```

⚠️ **并发提示**：我编辑前 `fs_tools.py` 已被 **B4** 改动（03:33:23 的 re-backup
sha256 `350BDA2307A9…`，含 B4 新增的 `reg.bound_role = "A"` 自检行）。
我改的是另一处（`_effective_roles` 的 docstring），改后 B4 那 4 行仍在原位（`fs_tools.py:925`）。

### 1.4.2 ② `tools/ocr_tools.py` 的模块 docstring（探测行为被编造）

**文档原话（改前，`## 副作用等级` 一节）**：

> `EasyOcrBackend.available`（`:220`）会对 easyocr 的真实模型目录 `mkdir(parents=True, exist_ok=True)`
> ……；`PytesseractBackend` **还会起一个 `tesseract --version` 子进程**。

**实现事实**（读码）：

1. 那次 `mkdir` **不是无条件的**：它在 `available()` 的**前置检查守卫**之内
   （`if import_ok:` 才走到 `model_dir.mkdir`，`ocr_tools.py:236`）；前置检查失败时
   `checks["model_dir"] = "SKIPPED（前置检查已失败）"`（`:246`），**目录不会被创建**。
2. **没有任何地方**"起一个 `tesseract --version` 子进程"。`PytesseractBackend.available`
   调的是 `pytesseract.get_tesseract_version()`（`ocr_tools.py:318`）；那个版本查询内部
   若起进程，起在**第三方库 `pytesseract` 里**，本模块源码里没有任何 subprocess 字面。
   原文把"库内部可能起进程"写成了"本模块起子进程"。

**改后**：两处都改成与实现一致（并保留 mkdir 是 `write_local` 的正当理由）。
另外**顺带**改正同段上方第一条的项目符号 —— 那里写 `ocr.run ⇒ network`，
而 `network` **已从 `SIDE_EFFECTS` 里删除**，代码声明的是 `write_local` + `egress`：

```
$ python -c "import agentflow.tools.base as B; print('network' in B.SIDE_EFFECTS)"
False
```

⇒ 留着 `network` 会让读文档的人以为有一个代码里已不存在的档（同属 G-25 的缺陷类）。
**我没有动任何声明**（`side_effect=` / `declared_external=` 一个字未改）——
§1.11 是 B5-part-2 的，且工单明令"不许顺手动 `ocr.run` 的声明"。改动是纯散文。

### 1.4.3 ③ `verify_tools.py:175` 的"折成三态" —— **交还 B5-part-2**

主控明令不许改 `verify_tools.py`（B8-part-1 在改同一文件做 `G-18`）。我把要改的那一处写清楚：

- **文件/位置**：`src/agentflow/tools/verify_tools.py:175`（`check_formal` 的 docstring），
  原文逐字为：
  > 3. 把它的八值受控词表**折成调用方看得懂的三态**，并按本工具既有的六键形态返回。

- **为什么是编造**：实现是 `"reason": raw["status"]` 之类的**原样透传**
  （`check_formal` 只把 `status` 塞进 `reason`），**没有任何折叠/映射表**。
  `PROPOSALS.md` 的 `G-25` ③ 原文也说"实现**只把 `status` 原样塞进 `reason`**，没有任何折叠 / 映射表"。
- **与 §1.3①（B5-part-2 的 `G-24`①）是同一处代码的两个面**，必须一起做：
  要么**真的实现**折叠并给出映射表，要么把 docstring 改成"原样透传 `status`"。
  `PROPOSALS` 明令："**不许**只改文档而留着'八值混装'当无事"。
- **我没有碰 `capabilities.py`**：`ActionSpec("E","check_formal")` 的说明文字
  （`capabilities.py:871` "转发到形式化检查器；没有后端时如实回答『没做』"）与实现**一致**，
  不需要改；折叠那句话只在 `verify_tools.py:175`。

---

## 1.5 `P-17`：`task_id` 不占 4 位编号空间（断言 + 形态可判定）

### 1.5.1 问题与"同义反复"陷阱（口径更正）

工单要求"`set(ID_COUNTERS)` 与过程前缀的交集为 ∅（单一来源取 `schema.ID_COUNTERS`，
不许另写名单）"。**但纯派生是空转的**：`process_id_kinds()` 若定义为
"`id_field` 不被 `ID_COUNTERS` 覆盖的表"，那么往 `ID_COUNTERS` 里塞 `"task": "task_id"`
会让 `tasks` **同时从派生面掉出去**，交集照样为空 —— **判据一声不响**。
（这正是我第一版写的断言：负控**没红**，实测 `DID NOT RAISE AssertionError`。）

⇒ 交付的是**声明面与派生面互相对账**（本项目对"同一件事两个落位"的标准做法，
同 `.noai-paths` ↔ `AGENTS.md` 的按位比对）：

- **声明面** `PROCESS_ID_PREFIXES = {"request": "r", "reprocess": "p", "task": "t"}`
  （每条注明产出点）；
- **派生面** `process_id_kinds()`（由 `TABLES` + `ID_COUNTERS` 推出）；
- `assert_process_id_contract()` 四条判据：① `set(ID_COUNTERS) ∩ {r,p,t} == ∅`；
  ② `set(PROCESS_ID_PREFIXES) == process_id_kinds()`；③ 过程表的 `id_field`
  不在 `ID_COUNTERS` 的值里；④ `task_id` 形态可判定且与 4 位判据**互斥**。
- 导入期自动跑一次（写错这张表的人未必跑测试，但一定会 import 这个模块）。

### 1.5.2 正控（真仓库）

```
$ python -c "
from agentflow import schema as S
S.assert_process_id_contract(); print('import + assert OK')
print('PROCESS_ID_PREFIXES =', S.PROCESS_ID_PREFIXES)
print('process_id_kinds() =', sorted(S.process_id_kinds()))
print('disjoint =', not (set(S.ID_COUNTERS) & set(S.PROCESS_ID_PREFIXES.values())))"
import + assert OK
PROCESS_ID_PREFIXES = {'request': 'r', 'reprocess': 'p', 'task': 't'}
process_id_kinds() = ['reprocess', 'request', 'task']
disjoint = True
```

形态可判定（互斥）：

```
is_valid_process_id(t-0001) = True    is_valid_id(t-0001) = False
is_valid_process_id(0000)   = False   is_valid_id(0000)   = True
```

### 1.5.3 负控（成对，注入是真的；三条独立路径）

| 注入 | 期望 | 实测 |
|---|---|---|
| `S.ID_COUNTERS["t"] = "task_id"`（塞一个**过程前缀**） | 红（判据①） | 红，消息含"过程记录前缀" |
| `S.ID_COUNTERS["task"] = "task_id"`（给过程表装计数器） | 红（判据②声明面≠派生面） | 红，消息含"声明面" |
| `S.TABLES["tasks"]["id_field"] = "lit_id"` | 红（判据③） | 红 |

三条都在 `try/finally` 里恢复，并断言**恢复后重新变绿**（防"负控把模块状态改坏"）。
测试：`tests/test_schema.py` → `30 passed`（观测 03:41）。
（第一版判据在这三条里**只红一条**，是负控逼我改对了判据 —— 这条记录本身就是"负控证明注入生效"的意义。）

---

## 1.6 `P-4`：`interactions.next_prefixed_id` 的 4 位上限下沉

### 1.6.1 改前（正控基线，03:39 采集）

```
"empty": "r-0001"        "one": "r-0002"        "gap": "r-0004"
"at_9998": "r-9999"      "junk_rows": "r-0008"  "p_prefix": "p-0043"   "t_prefix": "t-0006"
"already_5digit": "r-10001"
"cross_ceiling_sequence": ["r-9999", "r-10000", "r-10001", "r-10002"]   ← 静默产出 5 位号
```

⇒ 越界**静默产出** `r-10000` 及以后。`SearchRequest.validate` 只查非空 ⇒ 会一路落库。

### 1.6.2 改后（同一探针，同一批输入）

```
"empty": "r-0001"  "one": "r-0002"  "gap": "r-0004"  "at_9998": "r-9999"
"junk_rows": "r-0008"  "p_prefix": "p-0043"  "t_prefix": "t-0006"          ← 全部逐字不变
"already_5digit": {"ok": false, "error": "ValueError: r-NNNN 的 4 位编号空间已用尽（上限 9999）：下一个要发的号是 r-10001，它是 5 位，……"}
"cross_ceiling_sequence": ["r-9999", {"ok": false, ...上限 9999...}, {...}, {...}]
```

⇒ 正控：正常范围内**逐字不变**（diff 只有 `already_5digit` 与跨上限那一段）；
负控：到上限即抛，且**错误信息给出上限值 `9999`** 并回显越界号。

**上限只有一个定义处**：`interactions.py` 新增 `from .store import MAX_ID`
（`store.py` 只依赖 `schema`，与 `interactions` 不成环——已核）。
不在本文件里另写 `9999`。

### 1.6.3 测试

`tests/test_interactions.py`：新增 4 条（正常序列逐字不变 / 到上限抛且消息含上限 /
表里已有 5 位号也拒 / 带连接号的前缀仍拒）。
`tests/test_interactions.py tests/test_store_alloc_guard.py tests/test_agent_c_service.py` → `87 passed`（03:42）。

### 1.6.4 未做（交人裁）

`PROPOSALS` 的 `P-4` 提案还说"随后**删掉**工具层那道守卫（判据只有一份）"，
即 `table_tools.py::assert_request_id_in_space`。工单 §1.6 **没有**要求它。我**保留**了它：
删它会把这处的失败类型从 `ToolError`（工具层 fail 包装）变成 `ValueError`（直接抛），
会波及 `table_tools`/`research_tools` 的调用方与既有测试。**这是人裁项**。
另：该函数里硬编码 `int(digits) > 9999`（第二份字面量，应为 `MAX_ID`），也未动。

---

## 1.7 `P-5`：引用解析合成一份

### 1.7.1 方向按依赖图定（工单要求写清依据）

改前实测的依赖事实：

- `tools/table_tools.py:1135`：`from ..verify import verify_all` ⇒ **工具层依赖 `verify`**；
- `verify.py` 的 import 面：`dedup` / `schema` / `textutil` / `quoteverify` / `store` —— **不 import 工具层**；
- `tools/doc_tools.py` 的 import 面含 `from .. import textutil as T`；`verify.py` 也**已经** `from . import textutil as T`；
- `textutil.py` 只 import `schema`（**叶子**）。

⇒ 若把实现放 `verify.py` 并让 `doc_tools` 转发，就引入 `verify → 工具层`这条**新边**，
会把工具包的装配（`tools/__init__`）拉进审计模块的 import 图里（而反向那条边已存在）。
把实现放 **`textutil`** 是**零新边、结构上不可能成环**的方向：两边本来就都 import 它。
`PROPOSALS` 的提案建议"`verify.py` 导出 `parse_citation()`"，但工单 §1.7 明确说
"方向按依赖图定" ⇒ 我按依赖图选了 `textutil`，并把这段理由写进了函数 docstring。

### 1.7.2 交付物

- `textutil.py::citation_ref_parts` —— **唯一实现**（原样保留语义：
  `partition(":")` 只切第一个冒号 + `split("#")[0]` 去掉断言内锚点）；
- `tools/doc_tools.py::citation_ref_parts` —— 改成**纯转发**（R003 的转发判据也认这个形状）；
- `verify.py` 三处引用解析改调同一函数（`proof_claim_rests_on_weaker_evidence` 那条、
  `dangling_citation` 那条、`number_without_eval_scope` 的 kinds 计算）。

### 1.7.3 正控：两个入口逐字相同

18 组输入（含 `rel:0001#claim-1` / 无冒号 / 空串 / `:` / `:0001` / `rel:` /
多个 `#` / 前后空格 / 非字符串 `123`、`None` / 列表），三方比对
（`textutil` 实现 vs `doc_tools` 入口 vs `verify.py` 改前的内联口径）：

```
MISMATCHES: 0
```

完整逐条结果：`temp/_b5a_p5_positive.txt`（18 条，每条 `all_equal: true`）。

另有一条"同一个对象"级的判据：`DT.citation_ref_parts is not T.citation_ref_parts`
（转发体不是同一个对象）但**调用结果逐字相同** —— 结果相同可能由两份碰巧一致的实现造成，
所以"只做转发"这一点由 R003 形状 + 逐条对拍一起守。

### 1.7.4 负控：改坏唯一实现 ⇒ 两个入口同时变红

注入（把唯一实现的分支改坏：忘了剥 `#` 锚点 —— 正是 `rel:0001#claim-9` 这类真实引文会踩的）：

```python
def broken(citation):
    kind, _, ref = str(citation).partition(":")
    return kind, ref          # 少了 .split("#")[0]
monkeypatch.setattr(T, "citation_ref_parts", broken)
```

两个入口同时红（`tests/test_verify_extended.py::test_negative_control_breaking_the_one_implementation_reddens_both_entries`）：

```
入口一（工具层转发体）：DT.citation_ref_parts("rel:0000#claim-1") == ("rel", "0000#claim-1")   ← 跟着坏
入口二（verify 的悬空引用检查）：dangling_citation 从 0 条变成 1 条                              ← 跟着红
```

正控的一半也在同一用例里：口径正确时 `rel:0000#claim-1`（指向存在的 `rel:0000`）
**不报** `dangling_citation`。⇒ "只有一个红"不可能发生，因为根本只有一份实现。

`tests/test_verify_extended.py tests/test_verify.py tests/test_verify_quote_levels.py` → `46 passed`（03:43）。

### 1.7.5 附带说明（未做，如实记）

`verify.py` 里还有两处 `partition(":")`，**语义不同、未合并**：
- `:538` 解析 `used_by` 形如 `doc:0001#claim-1`，**两段都要**（`docid` 与 `cid`）；
- `:708` 解析 `artifacts` 形如 `table:id`，是**产物引用**不是引文引用（且不剥 `#`）。
把它们并进 `citation_ref_parts` 会把"引文"与"产物"两个命名空间混起来。**如实记为未做。**

---

## 1.9 `G-46`：`noai_gate --paths` 的逗号/换行输入 ⇒ `unknown(2)`

### 1.9.1 负控（改前是 `clean(0)` 假绿）

```
##### NEGATIVE CONTROL (today exit 0 => must be 2) #####
$ python scripts/noai_gate.py --paths "src/agentflow/schema.py,src/agentflow/verify.py"
[unknown] required_approvals=0
unknown：`--paths` 里有 1 个取值含逗号或换行，而逗号/换行**不是**本门的分隔符 ⇒ 整串会被当成**一条**路径，
不匹配任何 glob 时就会报 clean（假绿）。可疑取值（原样回显）：'src/agentflow/schema.py,src/agentflow/verify.py'
正确用法：`--paths a b c`（**空格分隔**多条）或 `--stdin`（每行一条路径）或 `--git`（按 git 改动集）。
刻意**不**自动按逗号切分：逗号在 Windows 文件名里合法，切分同样是假话。
exit=2

##### NEGATIVE CONTROL 2: newline in value #####
[unknown] required_approvals=0
unknown：`--paths` 里有 1 个取值含逗号或换行 …… 可疑取值（原样回显）：'src/agentflow/schema.py\nsrc/agentflow/verify.py'
exit=2
```

⇒ 两条可疑形态都 ⇒ **exit 2**（改前是 exit 0），且**原样回显**那个取值。

### 1.9.2 正控：只有可疑形态被拒，正常通路行为不变

```
##### POSITIVE CONTROL 1: space-separated two forbidden paths #####
$ python scripts/noai_gate.py --paths "src/agentflow/schema.py" "src/agentflow/verify.py"
[requires_human] required_approvals=2
命中：src/agentflow/schema.py, src/agentflow/verify.py
exit=1                                        ← 与改前一致，仍命中两条

##### POSITIVE CONTROL 2: single non-forbidden path #####
$ python scripts/noai_gate.py --paths "tools/vocab_census.py"
[clean] required_approvals=0
exit=0                                        ← 仍 clean(0)

##### POSITIVE CONTROL 3: --stdin 通路 #####
$ "src/agentflow/schema.py" | python scripts/noai_gate.py --stdin
[requires_human] required_approvals=2
exit=1                                        ← 行为不变
```

### 1.9.3 只挡可疑形态、且挡在写动作之前

- 检查放在 `main()` 里**先于** `--baseline` / `--approve`：
  `--baseline --paths "a.py,b.py"` 会把整串当**一条 glob 登记进台账**，
  那比一次假 clean 更难发现（假 clean 只影响这一次判定，脏台账会一直在）。
  有专门用例断言"拒绝的动作没有写台账文件"。
- **不自动按逗号切分**（工单口径）：逗号在 Windows 文件名里合法，切分同样是假话。
- 门脚本**不在**禁改区 ⇒ 无需备份/台账（工单 §1.9）；改动仍写在这里。

### 1.9.4 一处口径更正：消息里没有提 `--changed-file`

工单说消息要给出"`--paths a b c` 或 `--changed-file`"。实测 **`noai_gate.py` 没有
`--changed-file` 这个参数**（它是 `scripts/release_check.py` 的旗标）。
点名一个不存在的旗标会把读者送到坑里，所以消息里给的是**本脚本真实存在的**替代通路：
`--paths a b c` / `--stdin` / `--git`。

### 1.9.5 测试

`tests/test_noai_gate.py` 新增 5 条（逗号 ⇒ 2 / 换行 ⇒ 2 / 判别函数原样回显 /
空格分隔仍照常 / `--baseline` 通路也被挡且不写台账）。
`tests/test_noai_gate.py` → `104 passed`（03:31）。

---

## 1.10 `X-1`：发布检查的产物会改仓库状态

### 1.10.1 落点确认（与主控实测一致）

`scripts/release_check.py::item_linter` 把 linter 结果写成
`<repo>/.release-lint.json`，而该文件**被 git 跟踪**：

```
$ git ls-files agentflow/.release-lint.json
agentflow/.release-lint.json          ← tracked
$ git check-ignore -v temp/
.gitignore:22:/temp/	temp/             ← /temp/ 已被排除（且前导斜杠锚定在仓库根）
```

### 1.10.2 成对控制（旧码 vs 新码，只跑 lint 项）

命令：`python scripts\release_check.py --skip tests selftests tools verify noai contract imports --json <临时>`

```
file to hash: agentflow/.release-lint.json
S0 (start)      = E25FCCA4FB07BCB2DA4D70C35077CF15E044440127382F93E5ABC92277BAC432
git-status-lines S0 = 124

--- step 1: 跑**改前**的 release_check（从备份拷回） ---
发布检查总判定：FAIL    pass=0 fail=1 unknown=0
S1 (after OLD)  = FA850573C0F32F2D013ADFF2239A6C15B73529C5DFDC90E4E951F1E2D3E7A7F5   ← 变了（缺陷复现）

--- step 2: 恢复**改后**的 release_check，连跑两次 ---
S2 (after NEW #1) = FA850573C0F32F2D013ADFF2239A6C15B73529C5DFDC90E4E951F1E2D3E7A7F5
S3 (after NEW #2) = FA850573C0F32F2D013ADFF2239A6C15B73529C5DFDC90E4E951F1E2D3E7A7F5
unchanged across NEW runs: True
artifact temp\release-lint.json exists: True
git-status-lines = 125
```

⇒ 改前：跑一次门就把 `.release-lint.json` 改脏（sha 变）。
改后：连跑两次 sha **不变**；产物仍在，但落在**被 `.gitignore` 排除的** `temp/`。

### 1.10.3 产物是**搬家**不是取消（产物本身是证据）

对拍 `temp/release-lint.json` 与 `.release-lint.json` 的结构：

```
same keys: True ['error_count', 'errors', 'info_count', 'infos', 'rules_run', 'scanned', 'warning_count', 'warnings']
error_count 相等 / warning_count 相等 / info_count 相等 / rules_run 相等 / scanned 相等
唯一差异：R009 的**汇总行**（"另有 N 个文件、合计 M 处"）与禁改区装饰计数
        —— 因为两次 lint 运行之间 B4 正在改别的文件，计数在漂移
```

⇒ 落点搬家**没有降级产物**，差异来自并发编辑而非我的改动。

### 1.10.4 `git status` 剩余脏行归谁（如实报）

`git-status-lines` 现在是 **125 行**（03:47 观测；区间 123→125 因我自己的改动与 B4 并发而增长）。
逐类归属（观测 03:47）：

- **`.release-lint.json` 仍是脏的** —— **这不是本轮引入的**：工单 §1.10 已写明
  "此刻已经是脏的（多轮跑门留下的）"。改后门不再写它，但**它此前被改脏的那一版还留在盘上**。
  ⚠️ **未做**：我没有 `git checkout` 它（那会覆盖掉历史证据，且是一次仓库操作）。
  建议主控决定是"恢复成 HEAD 版"还是"把它从跟踪里移除"。
- **B4 在飞**：`tools/base.py`(03:30:33)、`tools/__init__.py`(03:29:19)、`fs_tools.py`、
  `agent_*.py`、`lint_rules.py`、`tests/**` —— 本轮 40+ 条 `role_denied` 失败即来自它的
  P-14 运行期角色强制**尚未铺完**（见 §E）。
- `agentflow/demo/run/data/*`、`test/test2/**` 等 —— 早已登记的验收/演示产物，与门无关。

### 1.10.5 顺带观察（照工单口径，不当结论）

工单提到观察 `agentflow/data/events.jsonl`（03:15:50）与 `agentflow/demo/run/data/*`（03:12:49）被重写。
我核到的事实（03:47）：

```
$ git status --porcelain -- agentflow/data     （空）
```

⇒ 与主控结论一致：`agentflow/data/` 下 **只有 mtime 变、内容未变**。
**结论只能是"本次未发现内容污染"，不是"这套件不写仓库"。**
`agentflow/demo/run/data/*` 是另一件事（它本来就是脏的，早已登记）。
**未核实**：具体是哪条用例写的、写的是不是"同内容覆盖"（我没深挖，工单说"不必深挖"）。

---

## 1.8b `D-2.3` + `D-2.5`：发布检查 JSON 要能读出真实状态

### 1.8b.1 缺口在编排层（与主控更正后的口径一致）

`scripts/release_check.py --json` **本来就**逐项输出
`items[]`（每项 `key`/`title`/`verdict`/`detail`（含 `tail`）/`notes`）
+ `counts{pass,fail,unknown}` + `overall`。
缺的是 `tools/release_all.py`：它调完子进程只留最后 12 行 `tail`，
**把子进程已经算好的逐项结构丢掉了**。
⇒ 修在 `release_all.py`，**没有**在 `release_check.py` 里再造并列结构。

### 1.8b.2 `D-2.5` 正控：三个数分开、与 stdout 同源

```
$ python tools\release_all.py --skip release-check,acceptance,repro,role-specs,coverage,per-file \
    --json D:\Incubator\temp\_b5a_allskip.json
  [unknown] release-check  全量测试 + 全部自检 + verify + 工具普查 + linter + 禁 AI 区 + 契约 + 导入
  [unknown] acceptance     验收测试（P1–P9，正式版 target=formal）
  [unknown] repro          论文独立复现（5 个实验 + 7 条负控）
  [unknown] role-specs     角色规格结构完整性（9 节 × 8 必备子节）
  [unknown] coverage       零测试公开函数的**风险分档**清单（等级 1/2 应为 0）
  [unknown] per-file       逐文件单跑测试（把顺序依赖/跨文件状态泄漏变成可判定的门）
一键发布检查总判定：UNKNOWN    pass=0 fail=0 unknown=6
exit=2
```

JSON：

```
top-level keys: ['counts', 'exit_code', 'steps', 'verdict']
verdict: unknown exit_code: 2
counts: {'pass': 0, 'fail': 0, 'unknown': 6}
counts.unknown == 6 : True
```

⇒ 6 步全 `unknown`（不是 `pass`）、退出码 **2**、`counts.unknown == 6`；
顶层 `counts` 与 stdout 那一行**来自同一个 dict**（只算一次，不许各算一遍）。

### 1.8b.3 `D-2.3`：逐项明细被原样嵌进编排层的 JSON

`release_all.py` 现在：
1. 给 release-check 那一步加 `--json <临时文件>`（`Step.json_out`）；
2. `run_step` 读回那份 JSON，把 `items[]` **原样**放进 `Result.subitems`、
   `counts{}` 放进 `Result.subcounts`；
3. 该步的结论**按子项汇总**（任一 `fail` ⇒ `fail`；无 `fail` 但任一 `unknown` ⇒ `unknown`），
   与 `release_check.Report.overall` 同一口径 —— 编排层于是能**独立重算**一遍；
4. 两者不一致时以逐项明细为准，并在 `notes` 里留下"总判定与逐项明细分家了"。

**反真空（三态）**：子 JSON 读不到 / 结构不合规时，`subitems` 保持**空**并附一条 `note`，
**不猜**、也**不返回一个"看起来像全通过"的空结构**。

**端到端（判据命令）**：

```
$ python tools\release_all.py --only release-check --json D:\Incubator\temp\_b5a_rc_full.json
$ python ..\temp\_check_release_json.py ..\temp\_b5a_rc_full.json
```

结果见 §1.8b.5。

### 1.8b.4 新发现的缺陷：`Step.env` 默认空字典 ⇒ Windows 上步骤"没跑成"

写 D-2.3 的用例时，一个**手写** `Step(...)`（不传 `env`）让 `run_step` 直接失败：

```
verdict: unknown exit: None
subitems: []
notes: ['该步骤声明了逐项 JSON 但没找到文件：C:\\...\\sub.json']
tail: ['OSError: [WinError 87] 参数错误。']
```

根因：`Step.env` 的默认是 `field(default_factory=dict)` = **空字典**，
而 `run_step` 写的是 `subprocess.run(..., env=step.env)` ⇒ 传给子进程一个**空环境块**，
Windows 上 `CreateProcess` 以 `ERROR_INVALID_PARAMETER (87)` 失败。
三态把它记成 `unknown`（"没跑成"），而真因是编排层传了空环境。

为什么一直没被发现：`build_steps` 造的每一步都带完整环境（`_env()`），
所以只有"手写 Step 去跑"时才会炸 —— **也就是只在测试里炸**，正是最容易被忽略的形态。

**修复**：`subprocess.run(..., env=step.env or None)`（空 = 继承当前环境），
并在 `Step.env` 上写清理由（空环境没有任何正当用途：连 `PATH` 都没有，解释器都起不来）。

### 1.8b.5 端到端原始输出（D-2.3 判据）

```
$ python tools\release_all.py --only release-check --json D:\Incubator\temp\_b5a_rc_full.json
  [fail   ] release-check  全量测试 + 全部自检 + verify + 工具普查 + linter + 禁 AI 区 + 契约 + 导入
  [unknown] acceptance / repro / role-specs / coverage / per-file
一键发布检查总判定：FAIL    pass=0 fail=1 unknown=5
exit=1        （release-check 跑了 315.9s）
```

`release-check` 那一步的键（**逐项结构在里面**）：

```
release-check 的键：['argv','exit_code','key','notes','seconds','subcounts','subitems','tail','title','verdict']
subcounts: {'pass': 5, 'fail': 2, 'unknown': 1}
subitems count: 8
  tests      verdict=fail     title=全量测试（pytest -q）                detail.tail_lines=12
  selftests  verdict=pass     title=模块自检（8 个 agent + pipeline）     detail.tail_lines=0
  tools      verdict=pass     title=工具普查（数量可复现 + 只读角色 0 泄漏） detail.tail_lines=0
  verify     verdict=pass     title=全库校验（verify_all error = 0）     detail.tail_lines=0
  lint       verdict=fail     title=linter（error = 0）                detail.tail_lines=6
  noai       verdict=unknown  title=禁 AI 区门（清单一致 + 改动集判定）    detail.tail_lines=0
  contract   verdict=pass     title=契约版本与 schema 版本一致            detail.tail_lines=0
  imports    verdict=pass     title=源码树可导入（无循环依赖）             detail.tail_lines=0

all subitems have a legal verdict: True
8 个子检查按 key 全部在场: True ['tests','selftests','tools','verify','lint','noai','contract','imports']
step verdict: fail    step notes: []
```

⇒ **8 项逐项明细全部读得出来、每项都带 verdict**（改前：只有 12 行 `tail`，`items` 被丢掉）。
该步的 `fail` 是**按子项汇总**得出的（`subcounts.fail=2 > 0` ⇒ `fail`）。

### 1.8b.6 负控（用真实数据 + 桩子两条路）

**真实数据**（`temp/_b5a_d23_negctl.txt`）：`fail` 子项的 verdict 与它的**输出尾部**都能从 JSON 读到，
且**其它子项的 verdict 各不相同** ⇒ 不是把总判定抄了 8 份：

```
tests.verdict = fail    tail: … "68 failed, 1841 passed, 8 deselected, 1 xfailed, 1 warning, 22 errors in 297.61s"
lint.verdict  = fail    tail: … R010 的 info 行
其它子项：{'tests':'fail','selftests':'pass','tools':'pass','verify':'pass',
          'lint':'fail','noai':'unknown','contract':'pass','imports':'pass'}
全部 8 项 verdict 都是 'fail' 吗（若是，说明只是抄了总判定）: False
```

**桩子**（`tests/test_release_all.py::test_negative_control_one_subitem_error_flips_only_that_step_not_the_others`）：
给一个子项注入 `fail` + 一段可识别的尾部 ⇒
该步 `fail`、**只有那一项**是 `fail`（另两项仍是 `pass`）、注入的尾部能在 `detail` 里读到、
**别的步骤仍是 `pass`**。

### 1.8b.7 ⚠️ 主控的 `_check_release_json.py` 只认到 7/8（判据工具的一处拼写不符）

`temp/_check_release_json.py` 的 `SUBS` 用的是 **`selftest`（单数）** 与 **`linter`**，
并用 `\b{name}\b` 搜整段 JSON 文本。而 `release_check.py` 的**子项 key** 是
**`selftests`（复数）** 与 **`lint`**（`linter` 只出现在它的 `title` 里，所以碰巧命中）：

```
在整段 JSON 文本里能找到名字的子检查：['tests','verify','tools','linter','noai','contract','imports']   ← 7 个
```

`\bselftest\b` **匹配不上** `selftests`（两者之间没有词边界）。
⇒ 这是**判据工具的拼写**与子进程 key 的不一致，**不是**"子检查没被读出来"：
上面 §1.8b.5 的原始输出显示 **8 项全部在场、每项都有 verdict**。

我**没有**为了让那个正则命中而改 `release_check.py` 的 item key
（那会把"改判据去迁就工具"变成一次注水），也没有在嵌入时另造一个 `selftest` 字段。
建议主控把 `SUBS` 改成
`("tests", "selftests", "verify", "tools", "lint", "noai", "contract", "imports")`
（或改成按 `subitems[i]["verdict"]` 读，而不是搜文本）。

### 1.8b.8 测试

`tests/test_release_all.py` → `29 passed`（观测 03:46；区间 22→29）。新增 8 条：
`verdict_from_subitems` 的优先级与"空 ⇒ None 不是 pass"；
`_read_step_json` 的缺文件/结构不合规/合规 round-trip；
`run_step` 真的嵌入 subitems 并按子项定结论；
以及负控"**一个**子项注入错误 ⇒ 只有那一步 `fail`，其它步骤与其它子项**不许**跟着变"
（防"把总判定抄成 N 份"）。

---

## F. 禁改区台账与一致性

改动的禁改区文件（5 个）：`src/agentflow/verify.py`、`src/agentflow/schema.py`、
`src/agentflow/interactions.py`、`scripts/release_check.py`、`tools/release_all.py`。

```
$ python scripts/noai_gate.py --paths src/agentflow/verify.py src/agentflow/schema.py \
    src/agentflow/interactions.py scripts/release_check.py tools/release_all.py --baseline
[baseline] 登记 5 条 / 未登记 0 条；台账：D:\Incubator\agentflow\.noai-approvals.json
  · src/agentflow/verify.py        refreshed  sha256 43894196ec15  [auth-audit]      reviewers=0
  · src/agentflow/schema.py        refreshed  sha256 5b8d5d130ce2  [schema-migration] reviewers=0
  · src/agentflow/interactions.py  refreshed  sha256 9f5f69ec15fd  [auth-audit]      reviewers=0
  · scripts/release_check.py       refreshed  sha256 d8dc2c9adaac  [release-deploy]  reviewers=0
  · tools/release_all.py           refreshed  sha256 2d3040bfcd25  [release-deploy]  reviewers=0
exit=0

$ python scripts/noai_gate.py --check-consistency
一致：.noai-paths 与 AGENTS.md 的清单逐条相同
exit=0

$ python -c "...读 .noai-approvals.json..."
entry count: 16
reviewers_total = 0
reviewers_total == 0 : True
```

⇒ **`reviewers` 一个字都没写**（登记 ≠ 批准），`reviewers_total` 仍为 **0**，
两处清单逐条一致（退出码 0）。

---

## G. 备份文件名清单

| 文件 | 备份（`D:\Incubator\temp\`） |
|---|---|
| `tools/vocab_census.py` | `tools_vocab_census.py.bak-b5a-20260926-032611` |
| `tests/test_vocab_census.py` | `tests_test_vocab_census.py.bak-b5a-20260926-032611` |
| `src/agentflow/verify.py` | `src_agentflow_verify.py.bak-b5a-20260926-032611` |
| `src/agentflow/schema.py` | `src_agentflow_schema.py.bak-b5a-20260926-032611` |
| `src/agentflow/interactions.py` | `src_agentflow_interactions.py.bak-b5a-20260926-032611` |
| `scripts/release_check.py` | `scripts_release_check.py.bak-b5a-20260926-032611`（另有 `.bak-b5a-NEW-20260926` = 我改后的版本） |
| `tools/release_all.py` | `tools_release_all.py.bak-b5a-20260926-032611` |
| `src/agentflow/cancellation.py` | `src_agentflow_cancellation.py.bak-b5a-20260926-032611` |
| `src/agentflow/tools/fs_tools.py` | `src_agentflow_tools_fs_tools.py.bak-b5a-20260926-032611`（B4 改前）＋ `.bak-b5a-re-20260926-033323`（**我改前**，含 B4 的改动） |
| `src/agentflow/tools/ocr_tools.py` | `src_agentflow_tools_ocr_tools.py.bak-b5a-20260926-033700`（= **我改前**的状态，由"反转我的编辑"重建；见 §H 的"未核实项"） |
| `src/agentflow/tools/doc_tools.py` | `src_agentflow_tools_doc_tools.py.bak-b5a-20260926-032611` |
| `scripts/noai_gate.py` | `scripts_noai_gate.py.bak-b5a-20260926-032611` |
| `src/agentflow/tools/verify_tools.py` | `src_agentflow_tools_verify_tools.py.bak-b5a-20260926-032611`（**备了但没改**，交还 B5-part-2） |

其余我改过的 `tests/*.py` 与 `src/agentflow/textutil.py`、`tools/release_all.py` 等
都在禁改区外，未单独备份（其改前形态可由 `git show HEAD:agentflow/<path>` 取得，见 §H 的 EOL 表）。

---

## H. EOL 形态与改前/改后 sha256（判据 = 与改前**形态**一致，G-48）

完整表见 `temp/_b5a_eol_after.txt`。摘要（观测 03:47）：

```
file                                       before after  ok    sha_before    sha_after
tools/vocab_census.py                      CRLF   CRLF   OK    D28D53FB3938  370EC5EB3C6C
tests/test_vocab_census.py                 CRLF   CRLF   OK    46D23FDA0004  4B78D087A945
src/agentflow/verify.py                    CRLF   CRLF   OK    46197051A7CE  43894196EC15
src/agentflow/schema.py                    CRLF   CRLF   OK    12CD4170ADFF  5B8D5D130CE2
src/agentflow/interactions.py              CRLF   CRLF   OK    E0D65DC6C136  9F5F69EC15FD
scripts/release_check.py                   LF     LF     OK    EFC625021377  D8DC2C9ADAAC
tools/release_all.py                       LF     LF     OK    82645D6F441B  2D3040BFCD25
src/agentflow/cancellation.py              CRLF   CRLF   OK    CA007F72255B  4BB0851EDC72
src/agentflow/tools/fs_tools.py            CRLF   CRLF   OK    350BDA2307A9  F1C450A8CB76
src/agentflow/tools/ocr_tools.py           CRLF   CRLF   OK    A0F6D797A65F  49E06413A122
src/agentflow/tools/doc_tools.py           CRLF   CRLF   OK    5AAE40422A15  62CA365E20E2
scripts/noai_gate.py                       CRLF   CRLF   OK    7AD32A040602  D71B6F946F5B
tests/test_cancellation.py                 CRLF   CRLF   OK    （git HEAD）    8300493CAAB9
src/agentflow/textutil.py                  CRLF   CRLF   OK    （git HEAD）    A5E51DB188F1
tests/test_noai_gate.py                    CRLF   CRLF   OK    （git HEAD）    0C3C5E34F502
tests/test_schema.py                       CRLF   CRLF   OK    （git HEAD）    C72C76D3A52B
tests/test_interactions.py                 CRLF   CRLF   OK    （git HEAD）    0080A8014CA9
tests/test_verify_extended.py              CRLF   CRLF   OK    （git HEAD）    FEA39A01E3A3
tests/test_release_all.py                  CRLF   CRLF   OK    （git HEAD）    A764128169A1

形态与改前不一致： 无
出现 MIXED 的文件： 无
```

⚠️ 判据是**形态**（纯 CRLF / 纯 LF）而不是"CRLF 计数相等"（后者是我第一版写错的，
已按 `G-48` 更正）。行数变了、形态没变。

**写文件方式**：全程用 `edit`/`write` 工具或 `open(..., newline="")`；
本次我还把 `tools/release_all.py` 里既有的 `Path.write_text()` 改成了
`open(..., newline="")`（`G-42`）。
（`scripts/release_check.py:548` 的 `Path.write_text()` **仍在**，那是禁改区既有代码，未动。）

---

## E. 已知失败与它们属于谁（本批不改判据、不掩盖）

### E.1 B4 在飞的 `role_denied`（**不是 B5 的**）

```
$ python -m pytest tests/test_tools_search_ocr.py::test_ocr_detect_text_layer_fails_clearly_for_missing_file -q
>       assert res.meta.get("kind") == "file_missing"
E       AssertionError: assert 'role_denied' == 'file_missing'
```

`role_denied` 的文案来自 **`tools/base.py:878`**（B4 的 P-14 运行期角色强制，
该文件 mtime 03:30:33，在我 03:26 的基线之后）。**`fs_tools.py` 的 `_effective_roles`
字节码改前改后完全相同**（§1.4.1），所以不是我引起的。

观测（03:48）：我改到的模块相关测试里共 **14 failed / 308 passed**；
失败的每一条都是 `role_denied` 形状。**我没有为了让它们变绿而改任何判据。**

全量套件（D-2.3 那次端到端跑的 `tests` 子项，观测 03:57）：

```
68 failed, 1841 passed, 8 deselected, 1 xfailed, 1 warning, 22 errors in 297.61s
```

⇒ 全量现在是**红的**，失败绝大多数来自 B4 在飞的 P-14（`role_denied` / `tools/__init__` 装配面）。
**这是 B4 铺完之前的中间态**，主控复跑全量两环境应在 B4 收官之后。
我的相关测试文件（`tests/test_vocab_census.py`、`test_schema.py`、`test_store_alloc_guard.py`、
`test_cancellation.py`、`test_interactions.py`、`test_noai_gate.py`、`test_release_all.py`、
`test_verify_extended.py`）在 03:59 的观测是 **278 passed / 0 failed**。

**最终快照（观测 04:06，我改到的全部 12 个测试文件）**：

```
$ python -m pytest tests/test_vocab_census.py tests/test_noai_gate.py tests/test_cancellation.py \
    tests/test_schema.py tests/test_interactions.py tests/test_verify_extended.py tests/test_verify.py \
    tests/test_verify_quote_levels.py tests/test_release_all.py tests/test_store_alloc_guard.py \
    tests/test_agent_c_service.py tests/test_tools_table_fs.py -q
350 passed in 61.04s (0:01:01)
```

（`test_tools_table_fs.py` 在 03:48 还是 40 条 `role_denied` 失败，04:06 已全过 ——
说明 B4 在窗口内继续推进了 P-14。**这进一步证明那些失败属于 B4，不属于 B5。**）

最终三态快照（04:06）：

```
python scripts/noai_gate.py --check-consistency     → exit 0
python -c "import agentflow.capabilities"           → exit 0
python tools/vocab_census.py                        → exit 1（有已登记预留，预期；unclaimed=0）
python scripts/lint_rules.py                        → error 6 / warning 1 / info 14（6 条全在我改的文件之外）
```

### E.2 lint 的 6 条 `error`（**全部在我改的文件之外**）

```
$ python scripts/lint_rules.py
[linter] error 6 / warning 1 / info 14
  ERROR R009 src/agentflow/agent_h.py:58      7 处…   ← 既有
  ERROR R009 tests/test_dup_consolidation.py:420  2 处… ← 既有
  ERROR R009 tests/test_tools_base.py:166     2 处…   ← B4
  ERROR R009 tests/test_tools_returns_declaration.py:597  2 处… ← B4
  ERROR R009 tests/test_usage_scope_attribution.py:72  2 处… ← 既有
  ERROR R009 <linter>:0                       另有 16 个文件、合计 20 处同类问题
```

**`NO lint ERRORS in my files`**（用我的 19 个改动文件名去筛 lint 输出，无一条 `ERROR`）。

唯一的 `warning` 是 **`R010 ocr.run`**（`ocr_tools.py:962`）—— 它**仍然在**，
即我的 `G-25`② docstring 改动**没有把它静默掉**（那是 B5-part-2 的 §1.11）。
（改前是 3 条 warning：另两条是 B4 的 `agent_e`/`agent_f` 的 `R004`，B4 补了
`validate_tool_roles` 调用之后消失了 —— 与 B5 无关。）

⚠️ 我在过程中**自己**制造过 R009 error（注释里的 `**强调**` 与 `⚠️`），
逐次跑 lint 后已全部清除，涉及 9 个文件：`tools/vocab_census.py`、
`tests/test_vocab_census.py`、`scripts/noai_gate.py`、`src/agentflow/cancellation.py`、
`tests/test_cancellation.py`、`tests/test_release_all.py`、`tests/test_schema.py`、
`tests/test_verify_extended.py`、`src/agentflow/tools/doc_tools.py`。
这正是工单纪律 #1 说的那个自伤形态 —— 我复现了它，也逐条清掉了。
（其中一次清理脚本因为 `replace("  ", " ")` 把**行首缩进**也折叠了，
导致 `test_verify_extended.py` 一度 `IndentationError`；已逐行修回并用 `AST OK` + `66 passed` 复核。）

---

## 未核实项（如实登记）

1. **`ocr_tools.py` 的"改前"sha256 是重建的**。它不在我最初的备份清单里，
   我编辑后才发现漏了。我通过**用 `edit` 工具反转我自己那一次编辑**恢复出改前内容，
   存为 `src_agentflow_tools_ocr_tools.py.bak-b5a-20260926-033700`
   （sha256 `A0F6D797A65FA3…`），并据此算 EOL 形态。**该文件在我编辑前后没有第三方改动**
   （mtime 03:33:31 只有一次写入）—— 但"没有第三方改动"这一条是**推断**，非独立证据。
2. **`.release-lint.json` 仍未恢复成 HEAD 版**（见 §1.10.4）。它此前被改脏，改后门不再写它。
   是否 `git checkout` / 从跟踪里移除，交主控。
3. **`git status` 剩余 125 行的逐行归属**只做到分类（B4 / 验收产物 / `.release-lint.json`），
   没有逐条点名。
4. **§1.10.5 的"哪条用例重写了 `agentflow/data/*`"未深挖**（工单说不必）。
5. **B4 的 40+ 条 `role_denied` 失败**：我确认了形状与来源文件，但**没有**复跑"全量两环境"
   ——按纪律 #4，全量两环境 + 逐文件那一遍由主控复跑。
6. **D-2.3 的端到端运行期间 `tests` 子项是 `fail`**（B4 在飞）。所以该次 JSON 里
   `counts.fail >= 1`；这不影响"逐项明细读得出来"这一判据，但**不构成**"八项都绿"的证据。
