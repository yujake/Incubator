# draft/49 决策对照 05：角色 E/F 与 A–D/H 的待拍板项（11 个决策点）

> 用途：把 `draft/48-施工方案-06-角色EF.md`（下称 `48-06`）、`draft/48-施工方案-07-角色ABCD与H.md`（下称 `48-07`）
> 两册施工方案里**必须由人拍板**的条目，逐个写成「现状与证据 → 方案 A/B/C → 不裁的默认后果 → 取舍点」的对照。
>
> **本文件只取证、只给方案与成本，不给最终裁定建议**（正文里任何一处都不推荐某个方案）。
>
> **边界声明**：本文件只写这一个文件。没有改 `agentflow/src/`、没有改任何工作区文件、没有跑 pytest、
> 没有跑模型、没有联网。只读操作：`read` / `grep` / `glob` / `python -B -c`（只读统计）。
> 所有「会红哪些测试」都是**静态判读**，不是实跑结果。

---

## §0 取证基线与口径

### 0.1 来源与标记

| 标记 | 含义 |
|---|---|
| `[本次确认]` | 本次用 `read` / `grep` 亲自核过的源码行号或原文 |
| `[本次复算]` | 本次用 `python -B -c` 只读重算得到的读数（命令见 §0.3） |
| `[48-06 §Y]` / `[48-07 §Y]` | 逐字来自该施工方案册的节号，本次未重读原文件处 |
| `[46-06 §Y]` / `[46-07 §Y]` | 逐字来自对应施工级调查报告 |
| `[44 J-zz]` | 逐字来自 `draft/44-裁定登记册：全部待裁条目（分6批）.md` |
| `[判断类]` | 取舍或推断，不是读数 |

**两条已否证的说法，本文件不当依据**（逐字照任务给定）：

1. **「E 的 8 个零调用动作」复现不出来**：`E` 声明 5 个动作**全部被调用**（`run_experiment` 537 /
   `check_formal` 147 / `run_script_experiment` 176 / `list_experiments` 14 / `evidence_for` 5），
   `E` 的零调用动作 = **0**；框架级零调用动作是 10 条（B×4 / D×5 / G×1），没有一条属于 E（`[48-06 §0.4]`）。
2. **`46-06 §0③` 的两个 sha256 是日志内嵌脚本的哈希**，不是日志文件的哈希（`[48-06 §0.5]`；
   本次已独立核到 `_write_run_log` 的第 2 行确实是 `# 脚本 {script_path}  sha256={chash}`，
   `chash` 来自 `VT.code_hash(path)`，见 `agent_e/run_experiment.py:104` `[本次确认]`）。

**已知漂移**（逐字照任务给定，本次未再核）：`tools/graph_tools.py` 的 `from_store` 在 `:347-358`、
签名无 `service=`（`48-07 §0.7`）。

### 0.2 两根工作区（数字不许合并算，`47 §3-C3`）

| 代号 | 路径 | 本次复算的规模 |
|---|---|---|
| 根1 | `D:\Incubator\agentflow\projects` | `data/*.json` 57 份目录；`statements` 138 行；`research_questions` **46 行**（26 个工作区非空） |
| 根2 | `D:\Incubator\projects` | `data/*.json` 22 份目录；`statements` 0 行；`research_questions` **0 行** |

### 0.3 本次复算的承重读数（只读命令，workdir `D:\Incubator\agentflow`）

```text
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; $env:PYTHONDONTWRITEBYTECODE="1"
$env:PYTHONPATH="D:\Incubator\agentflow\src"
python -B -c "<遍历两根 <ws>/data/*.json 与 <ws>/out/tasks/*.json 的只读统计>"
```

| 读数 | 本次复算结果 | 与来源的一致性 |
|---|---|---|
| `p8c/out/experiments/{0000,0001,0002}.log` | 各 534 B；sha256[:16] = `2046b2f0aa04aea8` / `e268de5b7f7a1cac` / `e268de5b7f7a1cac`；三份首行都是 `# flt-small-enum`；**0001 与 0002 byte-identical** | 与 `48-06 §0.5` 逐格一致 |
| `role=E, action=run_experiment, status=failed` | **80** 次 / 21 个工作区；52 次（32+17+2+1）合计 **6643.0 s**；28 次 `ExperimentError: name / imports 只对 method='formal' 有效` = **0.0 s** | 与 `48-06 §0.3` 逐格一致 |
| 分钟级失败靶子 | `p6m` 6 次 **4205.0 s**、`p6i` 3 次 **1802.0 s**、`p6h` 2 次 **602.0 s**；`p6o` 6 次仅 3.0 s | 与 `48-06 §0.3` 的更正一致 |
| `p8f` 计划 0002 第 1 轮 `steps[].cites` | 去重 **11** 个 `lit:` 引用（Frey1986 / Ribet1990 / Serre1987 / SophieGermain1823 / Edwards1977 / Kummer1850 / Washington1997 / Wiles1995 / TaylorWiles1995 / Mazur1978 / KhareWintenberger2009）；该工作区 `literature.json` 的 `lit_id` = `0000`…`0007` | 与 `48-06 §0.7` 一致；**11 个一条都不在册** |
| `role=C` 的 `out/tasks/*.json` 产物 | 根1 **37** 份、`payload_keys` 空 **26**（hottest 11 / gaps 12 / cold 2 / paths 1）、非空 11（contradictions 8 / structural_duplicates 1 / neighbors 1 / relations_between 1）；根2 **22** 份、空 **21**（hottest 14 / gaps 7）、非空 1（contradictions 1） | 与 `48-07 §0.3` 逐格一致 |
| `analysis_reports` 行数 | 根1 **0** 行（文件 57 份存在）、根2 **0** 行（文件 22 份存在） | 与 `48-07 §0.2` 一致 |
| `D.write_report` 与盘上报告文件 | 根1 **45** 行调用、盘上 `reports/*research*.md` 只有 **5** 份（`p6d` 0002/0003、`p6n` 0000、`p8` 0001、`p8g` 0002）；根2 全 0 | 与 `48-07 §11.1` 一致（同名覆盖把 45 折成 5） |
| `statements.bits` | 根1 138 行、非空 **0** 行；根2 0 行 | 与 `48-07 §0.2` 一致（EE-12/EE-07 随本簇外的册，仅作背景） |
| `research_questions` | 根2 22 份文件全部是 `{"schema_version": 1, "rows": []}` ⇒ **0 行**；根1 46 行 | 与 `48-07 §汇总.2` 的「22 个工作区没有 `research_questions` 行」一致（**该句的准确范围是根2**） |

### 0.4 全量门基线（施工时第一次跑必须复现）

`python -B -m pytest -q -p no:randomly` + `python -B scripts/lint_rules.py`
（基线 **0 错 / 9 警 / 49 提示**；`--strict` **0/58/48**）。本文件**未跑**，逐字沿用册内基线。

---

## §1 逐决策点对照

### 决策 1 — R-03 的引用口径：裸号 `["0001"]` 算不算合法引用，`stmt:` 前缀归谁管

- **现状与证据**：
  - `attackround.py:155-177` 的 `_clean_step` 现只判「`cites` 非空 **或** `assumption: true`」
    （`:172-176` 逐字），**不查引用的 id 是否在册** `[本次确认]`。
  - `attackround.py:117` 是 `out["steps"] = [_clean_step(s, i) …]`；`attackround.py:29-33` 的模块 docstring
    论证 `parse_round` 是纯函数、**不许读 store** `[本次确认到 `:117`；docstring 为 `48-06 §7.1`]`。
  - 引用解析的唯一实现在 `textutil.citation_ref_parts`（`textutil.py:262-292`，P-5）：
    `partition(":")` 只切第一个冒号 ⇒ 裸号 `"0001"` 得 `("0001", "")`（**kind 是整串、ref 是空串**）；
    docstring `:289` 逐字给出这条边界 `[本次确认]`。
  - `verify.py:51` `CITATION_KINDS = ("rel","lit","exp","eval","doc")`、`:54` `_BRANCH_KINDS` 同值、
    `:55-57` 有一条导入期断言 `set(CITATION_KINDS) == set(_BRANCH_KINDS)`；**两处都没有 `stmt`**；
    `:962-967` 对 `kind not in CITATION_KINDS` 记 warning `unknown_citation_kind` `[本次确认]`。
  - `tools/doc_tools.py:319-324` `_CITATION_TABLES = {"rel":"relations","lit":"literature",
    "exp":"experiments","eval":"eval_results"}` —— **没有 `stmt`、也没有裸号**；`:315-318` 的注释逐字要求
    「写入期与审计期对同一个字符串给出同一个结论」；`:391-405` 对无法识别的前缀**写入期 fail-closed**
    `[本次确认]`。
  - `schema.py:2455` `statements.id_kind == "stmt"`、`:2451` `documents.id_kind == "doc"`
    ⇒ 「前缀 → 表」的权威来源是 `TABLES[*]["id_kind"]`，不是上面那两份手写表 `[本次确认]`。
  - 真机：`p8f-fermat-shorter-proof` 计划 0002 的 11 个 `lit:` 引用**一条都不在册**（§0.3）`[本次复算]`。
  - 会红的既有夹具（`44 J-05③` 点名）：`tests/test_attack_round.py:55/58`（引 `stmt:0004`）、
    `tests/test_attack_round.py:81/83`（`best_partial[].ids = ["stmt:0004"]`）、
    `tests/test_invalidation_cascade.py:143/146`（**裸号** `["0001"]` / `["0008"]`）`[48-06 §7.1]`。
- **方案 A：加 `stmt` 进三处（一份表）**
  - 做法：`"stmt"` 分别加进 `verify.CITATION_KINDS`（`verify.py:51`）、`_BRANCH_KINDS`（`:54`）、
    `doc_tools._CITATION_TABLES`（`:319-324`，映到 `statements`）；R-03 的「kind → 表」从
    `schema.TABLES[*]["id_kind"]` 现取，不自建第二份。
  - 理由：`verify.py:55` 的导入期断言要求两个常量同轮改；`doc_tools.py:315-318` 的注释要求写入期与
    审计期同答案 ⇒ 只有一份表才可能同时满足这两条。
  - 成本：文件 **3**（`verify.py` **禁改区**、`doc_tools.py`、`attackround.py`）、落点 **3**、
    约 **6 行**（三处各 1 个取值 + 注释同步）；**另需** R-03 本体的 `known_ids` 白名单（约 +40 行，
    `attackround.py` + `agent_f/core.py`）⇒ 本方案只解决「表」的一半。
    会红/需复核：`tests/` 里若有逐个钉 `CITATION_KINDS` 五元组的用例会红（本次未定位该文件，`[判断类]`）；
    `tests/test_attack_round.py:55/81`、`tests/test_invalidation_cascade.py:143` 的夹具改写（三条，`44 J-05③`）。
    快照与文档同步点：`verify.py:52-57` 的注释块；`48-02`/`48-03` 册内若有 `CITATION_KINDS` 的逐字引用。
    真机影响：`documents[].claims[].citations` 里现在记 `unknown_citation_kind` 的 `stmt:` 引用转绿；
    `stmt:` 引用**第一次**真的去 `statements` 表核对存在性 ⇒ 历史稿件里不存在的 `stmt:` 会变成悬空
    （读数变化，必须在 `draft/44` 写「从哪一趟起口径变了」）。
  - 风险与不可逆点：把 `stmt` 加进 `CITATION_KINDS` 等于**放宽审计口径** —— G 的稿件从此可以拿 F 的
    命题当引用依据，`documents` 的引用图会混入「本计划内部的 sid」；且 `verify.py` 是 auth-audit 禁改区，
    「测试全绿、上线即越权」是这一区被登记的理由原文（`AGENTS.md`）。
  - 兼容闸：两个常量都已存在，加取值是「放宽」；`verify.py:55` 的一致性断言是天然闸门。
  - 禁改区：`verify.py` **在册** `[category: auth-audit]` ⇒ 需 2 名人审，不许自签；
    `doc_tools.py`、`attackround.py` 不在册（`47 §3-C2`）。
- **方案 B：明说「F 的 `stmt:` 不归 `check_citations`」（第二份表 + 边界声明）**
  - 做法：`verify.py` / `doc_tools.py` 一个字不改；R-03 在 `attackround.py` 内建「kind → 表」映射，
    来源是 `schema.TABLES[*]["id_kind"]`（含 `stmt`/`doc`/`plan` 等），并在模块 docstring 与 `draft/44`
    明写「F 的 `cites` 只受 R-03 管，不经 `check_citations` / `doc_tools`」。
  - 理由：`CITATION_KINDS` 的语义是「G 的稿件允许引什么」，F 的 `steps[].cites` 是「这一轮论证引到哪些
    在册对象」—— 两个集合本来就不同（F 还会引本计划的 sid）。把 `stmt` 塞进去是让两个不同问题共用一张表。
  - 成本：文件 **2**（`attackround.py`、`agent_f/core.py:411` 的调用点；都不在册）、落点 **2**、
    约 **40–60 行**（映射 + 「逐 step 逐 cite 展开」生成器 + `_known_ids`）；另加一条
    **导入期一致性判据**（「F 认的 kind 集合 == `schema` 里 `id_kind` 的集合」，约 +10 行 + 1 条测试，
    `46-06 §7.5` 点名要它，否则 R-03 会与 `verify.py` 的 `dangling_citation` 分家）。
    会红：与方案 A **同一批三条夹具**（改法相同，或让它们走 `known_ids=None`）；`tests/test_agent_f_products.py:92-93`
    用合成 id `["exp:0001","stmt:0007"]` 断言 `best_partial.ids` ⇒ **不许**把 `best_partial[].ids`
    纳入 cite 判据（一纳入就红）。
    快照与文档同步点：`draft/44` 写明「从这一批起 F 的 proof 步引用不真实会当场拒收」（`46-06 §5.6` 风险 B）。
    真机影响：`p8f` 计划 0002 从 `progress` 变 `blocked`，`detail` 里能看到「这些 id 不在册」。
  - 风险与不可逆点：**两份表** —— `FC-03` 禁止的形态正是「同一件事两处各写一份」；`attackround` 从
    `schema.TABLES` 现取能缓解，但「什么算合法引用」从此有两个答案（写入期 fail-closed vs R-03 白名单）。
  - 兼容闸：`known_ids=None` 时与今天**逐字同形** ⇒ 15 条既有 `parse_round` 用例零改动。
  - 禁改区：两个文件都不在册；**不动 `verify.py`**。
- **方案 C：B + 裸号定义成「先本计划 sid、再 `statements`」**
  - 做法：在 B 的基础上显式定义裸号语义：先查本计划 `plan` 的 sid 集（本轮调用前已存在 ∪ 本轮 deploy
    已造，含已 closed 的），查不到再查 `statements`，仍查不到 ⇒ `RoundError`。
  - 理由：真机 `tests/test_invalidation_cascade.py:143` 的形态就是裸号；若裸号一律拒收，那条夹具与
    F 的历史写法会被判死（`46-06 §5.6` 风险 A 点名两条快照一致性：引 `stmt:9999` ⇒ 拒；引**本轮之前**的
    `s2` ⇒ 放）。
  - 成本：B 的成本 + 约 **10–15 行** + 2 条负控；会红：同 A/B 三条夹具 + 两条新增快照一致性断言
    （改前必红）。真机影响：同 B，但 `p8f` 的 11 个 `lit:` 仍被拒（它引的不是本计划 sid）。
  - 风险与不可逆点：「先本计划、再 statements」的判定顺序一旦反了，F 会引到一张与研究问题无关的
    statements 行，而看上去仍然「引到了一个存在的 id」—— 这类错误没有任何下游判据能发现。
  - 兼容闸：同 B（`known_ids=None` 退化为今天）。
  - 禁改区：同 B。
- **不裁的默认后果**：`attackround.py:172-176` 继续只判「非空」 ⇒ `p8f` 计划 0002 的 11 个不在册
  `lit:` 引用继续被记成 `progress`（真机 §0.3），这 11 个 id 继续被下游（`closing` / 报告）当有效依据读；
  `44 J-05①` 与 `46-06 §8` 人裁①继续挂空，`46-06 §9` 的**第 ⑦ 步（最后一步）**无法开工。
- **取舍点**：分歧在「`stmt:` 这一档要不要动 `verify.py` 的受控词表（一份表，但要碰 auth-audit 禁改区）」，
  以及「裸号该解释成本计划内的 sid，还是 `statements` 的行号」。

---

### 决策 2 — `DEAD_END_REASONS` 是否新增 `tool_failure`

- **现状与证据**：
  - `attackround.py:53-55` `DEAD_END_REASONS` 七值：反例 / 方法不适用 / 缺定义 / 缺文献 / 缺工具 /
    超出本轮预算 / 需要先证别的命题 `[本次确认]`。
  - `attackround.py:131-133` 校验：不在词表即 `RoundError`（消息里带全部受控值）`[本次确认]`。
  - 提示词广告面：`agent_f/core.py:72` 逐字 `f"4. \`dead_end\`：…要给受控 \`reason\`（{'、'.join(AR.DEAD_END_REASONS)} 之一）…"`
    ⇒ **词表一变，提示词文本就变** `[本次确认]`。
  - 全仓 `DEAD_END_REASONS` 只有 6 处命中：`attackround.py:53/132/133`、`agent_f/core.py:72`、
    `tests/test_agent_f_products.py:41`、`tests/test_attack_round.py:205` `[本次确认，全仓 grep]`。
  - G-3 的两条失败路径（接口坏 / 轮次不成形）现状返回的 dict **没有 `product`** 且 `count_attempt=False`
    （`agent_f/core.py:397-409`、`:410-425`）`[48-06 §5.1]`。
  - 真机：76 个计划的 `history.dead_end_reason` = 缺定义 7 / 缺工具 4 / **自由文本 3**（全是 reduction 行，
    来自 `attackround.py:112` 把归约的 `reason` 写进 `out["reason"]`，而 `agent_f/step.py:264-265` 见
    `product["reason"]` 就写 `dead_end_reason` —— 一个字段名装两种语义）`[48-06 §0.6 / §6.1]`；
    `history.product` = `None` 289 / `dead_end` 11 `[48-06 §0.6]`。
  - `draft/45:71` 逐字建议「`dead_end.reason` 加一档 `tool_failure`，与数学理由分开」；
    `44 J-05②` 把它列为人裁（「加 `tool_failure` 要动受控词表 + 广告面；不加则要加
    `dead_end_reason_source="seam"`」）`[来源]`。
- **方案 A：加 `tool_failure` 第八值**
  - 做法：`attackround.py:53-55` 加 `"tool_failure"`；G-3 的两条失败路径落
    `AR.dead_end_row(reason="tool_failure", …)`；`count_attempt=True`。
  - 理由：`缺工具` 的语义是「数学上需要一个我们没有的工具」，G-3 说的是「推理缝这个接口坏了」——
    混在一格会让「缺工具」的计数失真，而真机 4 条 `缺工具` 里有没有这一类，现有读数分不出来。
  - 成本：文件 **2**（`attackround.py`、`agent_f/core.py`；都不在册）、落点 **3**（词表 + 两条失败路径）、
    约 **8 行**；提示词广告面**自动跟随**（`core.py:72` 是现取 `join`）⇒ `agent_prompts.py` 若有逐字镜像
    要同步（本次未核实镜像点，`[判断类]`）。
    受控词表 ⇒ `tools/vocab_census.py` 的 R011（死取值）会扫它：本方案里 `tool_failure` **有代码产出点**
    （G-3 两条路径），不是死取值。
    会红：`tests/test_agent_f_inference.py:178`（`:188` 逐字 `assert rec.get("product_detail") is None`）、
    `tests/test_agent_f_inference.py:193`（`:202` 逐字 `assert rec.get("product_detail") is None, rec`）
    ⇒ 两条**必须改、改前必红**（`44 J-05③` 点名）；`tests/test_agent_f_products.py:41`
    （`dead_end_reason in AR.DEAD_END_REASONS`）新值自动满足；`tests/test_attack_round.py:205` 只断言非空。
    快照与文档同步点：`draft/44` G-3 行 + `draft/45:71` 的「办法」句落地。
    真机影响：G-3 的 6 条靶子（`p8b` 0000 第 1/2 轮、`p8c` 0001 第 1/2 轮、`p8d` 0000 第 1 轮、
    `p8d` 0001 第 1 轮）从 `product=None` 变 `dead_end`，`dead_end_reason` 首次出现 `tool_failure`。
  - 风险与不可逆点：`tool_failure` 一旦进词表，**模型也会在提示词里看到它**（`:72` 现取）⇒ 模型可能在
    「不会做」时用它兜底（把不会写成工具坏了），而这一档恰恰无法从文本上分辨；回滚要同时回滚词表与
    6 条真机读数的口径说明。
  - 兼容闸：词表**加取值**是「放宽」；历史行（3 条自由文本、4 条缺工具）**不回填**；读侧不需要认识新值
    （`tests/test_agent_f_products.py:41` 是唯一成员判据，自动通过）。
  - 禁改区：`attackround.py`、`agent_f/core.py` 都不在 FC-27 清单（`47 §3-C2`）；`specs/f.py` 在册
    （auth-audit）—— 本方案不动它，但**若广告面镜像在 `specs/f.py`，则需 2 名人审**。
- **方案 B：不加值，用 `history.dead_end_reason_source="seam"` 区分（自由字符串）**
  - 做法：G-3 落 `dead_end_row(reason="缺工具")`（受控 7 值里最贴近「接口坏」的一格），
    `_deploy` 显式给 `dead_end_reason_source="seam"`；`agent_f/step.py:254-265` 把它写进 history 行，
    缺省 `"model"`。
  - 理由：这一档的判据是「谁给的 reason」，不是「reason 是什么词」；`source` 是机器留痕，
    `agent_f/core.py:70-77` 的广告面**不广告它** ⇒ 模型看不见、不能冒充。
  - 成本：文件 **3**（`agent_f/core.py`、`agent_f/step.py`、测试；前两者不在册）、落点 **3**
    （两条失败路径 + `step.py:254-265`）、约 **25 行**（`core.py` +20 / `step.py` +5）。
    会红：同 A 的两条（`tests/test_agent_f_inference.py:188/202`，必改、改前必红）；
    `tests/test_agent_f_products.py:41` 自动绿（`缺工具` 在词表内）。
    快照与文档同步点：`history` 是 `list[dict]`，schema 只校验 sid/status/owner/blocked_reason/round/长度
    （`schema.py:1259-1315`，`48-06 §6.1`）⇒ **加键安全、不重冻**。
    真机影响：同 A（6 条靶子 `product=None → dead_end`），但 `dead_end_reason` 仍是 `缺工具`，
    新增 `dead_end_reason_source="seam"`。
  - 风险与不可逆点：`缺工具` 这一格的计数被污染（真机 4 条 + 未来所有接口坏），下游按
    `dead_end_reason` 分档的读数（`closing.py` / `statusreport.py` 读 `history.dead_end_reason`，
    `48-06 §6.1` 未逐行走查）分不出两类；`source` 是新键 ⇒ 需要一条明确的读法登记（缺键一律按
    `"model"` 读）。
  - 兼容闸：不加词表取值 ⇒ 词表与提示词面**零变化**；`dead_end_reason_source` 是「带默认值新增」。
  - 禁改区：同 A，且**完全不碰 `attackround.py`**。
- **方案 C：加第二个轴，但把 `source` 也做成受控词表**
  - 做法：新增 `DEAD_END_REASON_SOURCES = ("model", "seam")`；`step.py` 按 `dead_end.reason_source`
    分档并落 history；`reason` 仍用 `缺工具`。词表本体落在 `attackround.py`（与 `DEAD_END_REASONS` 同处）。
  - 理由：B 的 `source` 是自由字符串 ⇒ 打错一个字就得到第三种「来源」，而它没有任何校验；受控词表能让
    「来源」这一轴也有 `attackround.py:131-133` 那样的校验。
  - 成本：B 的成本 + 约 **10 行**（词表 + 校验 + 测试）。
    会红：`tests/test_attack_round.py:205` 一类「断言词表非空」的用例仍绿；新增的
    `DEAD_END_REASON_SOURCES` 需要一个产出点，否则 `tools/vocab_census.py` 的 R011 会把它扫成 dead vocab
    （G-3 两条路径给 `"seam"`，但 `"model"` 的产出点在 `step.py` 的默认值上 ⇒ 需确认 R011 认不认默认值，
    本次未核实，`[判断类]`）。
    真机影响：同 B。
  - 风险与不可逆点：多一个受控词表就多一处「加取值 = 改词表」的人裁面；`step.py` 的默认值算不算
    「产出点」决定了这个词表会不会一开始就带一个死取值。
  - 兼容闸：同 B（`reason` 面零变化）。
  - 禁改区：`attackround.py` 不在册。
- **不裁的默认后果**：`44 J-05②` 继续挂空，G-3 只能按 `48-06 §5.1` 边界①的临时档落地（落 `缺工具` +
  `seam`），于是 `缺工具` 这一格继续同时承担「数学缺工具」与「接口坏」两个事实，真机 4 条 `缺工具` 的
  归属永远分不出来；提示词面与词表不变。
- **取舍点**：分歧在「接口坏要不要有自己的受控取值（可被模型看见、可被机器统计，但模型也能拿它兜底）」
  与「这一档只让机器看得见（`source` 不进广告面，但按 `reason` 的统计会混档）」。

---

### 决策 3 — R-02 的日志落盘三方案

- **现状与证据**：
  - `agent_e/run_experiment.py:170` 的注释逐字「文件名用实验号 —— 同一脚本跑两次（不同种子）输出不同，
    按**脚本哈希**命名会撞」；`:171` `log_rel = f"out/experiments/{eid}.log"`；`:172-174` 调
    `_write_run_log`；`:175-177` 把失败原因落 `notes` 的 `[log]` 分支 `[本次确认]`。
  - `agent_e/_support.py:682-705`：`:691` `target.write_text(..., encoding="utf-8")` **无条件覆盖**；
    docstring `:686-687` 逐字「不许因为日志写不了就丢掉这条实验」；`:704-705` 只 `except OSError`
    返回原因串（**没有部分写入的破损态判据**）`[本次确认]`。
  - 生产调用点**只有** `run_experiment.py:172`（另 3 处命中是 `_support.py:682` 定义、
    `run_experiment.py:7` 导入、`agent_e/__init__.py:129` re-export）`[本次确认，grep]`。
  - `store.py:994-999` 失败事务 `finally: self._dirty_counters = None` ⇒ 计数器不推进、`eid` 复用；
    `tests/test_store_concurrency.py:212-234` 逐字钉住「回滚后仍从 0000 开始」（`:234`）——
    它是 R-02 的**反判据**，且 `store.py` 是禁改区 `[本次确认]`。
  - 真机（§0.3）：`p8c` 三份日志各 534 B，sha256[:16] = `2046b2f0aa04aea8` / `e268de5b7f7a1cac` /
    `e268de5b7f7a1cac`，**0001 与 0002 byte-identical**，三份首行都是 `# flt-small-enum` `[本次复算]`。
  - **日志里嵌的脚本哈希与文件哈希是两码事**：`_write_run_log` 的第 2 行是
    `# 脚本 {script_path}  sha256={chash}`，`chash` = `VT.code_hash(path)`（`run_experiment.py:104`）
    ⇒ `46-06 §0③` 的 `fb6863d8eefeb91c` / `a475de43f8b03d63` 是**内嵌脚本哈希**，不是日志文件哈希
    `[本次确认]`。
  - 真机错配/孤儿共 **5 处**（`p8c` 0000/0001、`p6e` 0006 为 MISMATCH；`p6e` 0008、`p5-review-t1` 0000
    为 LOG_WITHOUT_ROW）`[48-06 §0.5]`。
  - 会红：`tests/test_agent_e_run_log.py:50` 逐字
    `assert arts == [f"out/experiments/{row['experiment_id']}.log"], arts` `[本次确认]`；
    `:41-58` 是同文件正控（`:51-57` 逐字断言正文含 stdout/stderr/`REPRO_RESULT:`/`sha256=`/`exit_code=`）；
    `:71-81` 是注入写失败负控 `[本次确认到 `:74` 之前]`。
- **方案 A：`_write_run_log` 加 `overwrite=False`（存在即返回原因），命名不动**
  - 做法：`_support.py:682` 签名加 `overwrite: bool = False`；`target.exists() and not overwrite` ⇒
    直接返回原因串（调用方走 `run_experiment.py:175-177` 的 `[log]` 分支）。
  - 理由：改动最小、不动命名、不动 store；`:686-687` 的契约（写不了不许丢实验行）自然延续 ——
    「返回原因」是既有形状（`:703`/`:705`）。
  - 成本：文件 **1**（`agent_e/_support.py`，不在册）、落点 **2**（签名 + 新分支，+4–6 行；
    `run_experiment.py:172` 传参可选 +1 行）、合计约 **5–7 行**。
    会红：`tests/test_agent_e_run_log.py:50` **不红**（命名未变）；`:71-81` 的注入路径「目录位置是文件」
    ⇒ `target.exists()` 为假、`write_text` 抛 `OSError` ⇒ 不经过新分支（`[48-06 §3.2]` 判「不会红，但要复跑」）。
    快照与文档同步点：无；`grep -rn "out/experiments" tests/ docs/ *.md` 施工时先跑（`[48-06 §1.2]` 未核实）。
    真机影响：`p8c` 三份历史日志**一份都不会被改写**（不回填）；重跑时 `0001`/`0002` 这类复用号
    **不落盘**并把原因写进 notes ⇒ `artifact_paths` 变空、**旧的 5 处错配仍在**、不会新增。
  - 风险与不可逆点：「不覆盖」= 新日志直接丢、`artifact_paths=[]` ⇒ 任何按「有 log」读数的下游
    （`closing.py` 的 `report_files` 一族）会掉，而这是**判据生效不是回归**，必须写进 `draft/44`。
  - 兼容闸：默认值变化只影响 `run_experiment.py:172` 一个调用点；`agent_e/__init__.py:129` 的 re-export
    签名同步。
  - 禁改区：`agent_e/*` 不在册；**`store.py` 一字不动**（在册 + 反判据）。
- **方案 B：内容哈希命名（`<eid>-<content_sha256[:8]>.log`）+ 不覆盖**
  - 做法：先渲染日志正文、算其 sha256，再按内容哈希落盘；`overwrite=False` 同 A。
  - 理由：内容哈希直接对应「这份日志是谁的」；`p8c` 的 `0001`/`0002` 两份 **byte-identical** 会**收敛成
    同一个文件名**（这正是它们在盘上的真相），而 `0000` 与它们不同 ⇒ 三个号得两个文件，
    「日志内容与 rows 的 `claim_key` 错配」在文件层不再可能发生。
  - 成本：文件 **2**（`agent_e/_support.py`、`agent_e/run_experiment.py`；都不在册）、落点 **3**
    （渲染与写盘拆分 + 命名 + 调用点）、约 **12–18 行**。
    会红：`tests/test_agent_e_run_log.py:50` **必红**（命名变）⇒ 必须同批改断言（先跑确认红、再改断言、
    再改实现）；`tests/test_agent_e.py:125`（`experiment_id == "0000"`）与 `:604`（下一个 id）
    钉的是 **id 分配**、不是文件名 ⇒ 不受影响（`[48-06 §1.2]`）。
    快照与文档同步点：同 A（先跑 grep）。
    真机影响：重跑 `p8c` 只产生与历史不同名的文件；历史三份按 sha256 可分辨出「两份同一内容」。
  - 风险与不可逆点：`run_experiment.py:170` 的既有注释明确拒绝「按**脚本**哈希命名」（同脚本两次输出
    不同 ⇒ 撞名）；**内容**哈希不受这条反驳，但注释会与实现看起来矛盾 ⇒ 必须同批改注释，否则下一个人
    会按注释回退；「同号同内容」被折叠成一个文件 ⇒ 丢掉「跑过两次」这个事实（rows 仍 4 行，日志只 1–2 份）。
  - 兼容闸：`self.workspace_root` 与 `artifact_paths` 的工作区相对路径这一对不许破坏（`run_experiment.py:171-174`）；
    改名后 `tests/test_agent_e_run_log.py:50` 必须同批改。
  - 禁改区：同 A。
- **方案 C：追加写（同名文件 append，带分隔与轮次标记）**
  - 做法：`_write_run_log` 目标已存在时**追加**一段分隔头（带 `claim_key` / 脚本哈希 / `exit_code`）
    与本趟正文，而不是覆盖；命名不动。
  - 理由：正文本来就带 `claim_key`/脚本哈希/`exit_code`（`:692-696`）⇒ 追加段天然可分辨；
    「一份日志丢掉一次运行」变成「一份日志带多次运行」。
  - 成本：文件 **1–2**、落点 **2**、约 **10–15 行**。
    会红：`tests/test_agent_e_run_log.py:41-58` 命名不变 ⇒ `:50` 不红，但 `:51-57` 逐字断言正文内容
    ⇒ 追加后仍含这些串，**需复跑**。
    真机影响：`p8c` 的 `0001`/`0002` 若重跑会长成一份双段文件，与历史两份 byte-identical 的关系
    从「两份文件」变成「一份文件两段」。
  - 风险与不可逆点：**日志不再是「一次运行的快照」**；`_write_run_log` 从「纯 IO 覆盖写」变成
    「有状态的追加写」；追加中途 `OSError` 会让文件停在两段之间的破损态，而现有代码只返回原因串
    （`:704-705`），**破损态没有任何判据**。
  - 兼容闸：返回契约（`None` 或原因串）不变；`agent_e/__init__.py:129` re-export 同步。
  - 禁改区：同 A。
- **不裁的默认后果**：`_support.py:691` 继续 `write_text` 无条件覆盖，而 `store.py:994-999` 的计数器回滚
  继续让 `eid` 复用 ⇒ 真机 5 处错配/孤儿继续增加；「有 log 无行」的日志继续被 `report_files` 一类读数
  当产物；`44 J-03` 的 agent_e 半继续挂空，`46-06 §9` 第 ④ 步无法开工。
- **取舍点**：分歧在「同名时是丢新日志、改名、还是把两趟并进一份」，以及「要不要让 `p8c` 的两份
  byte-identical 在**文件层**被折叠成一个文件」。

---

### 决策 4 — S-07 的改判方向（D 的报告落点）

- **现状与证据**：
  - `schema.py:442` `REPORT_KINDS = ("hottest", "paths", "cold", "gaps")`；`:842-843` `validate()` 对表外
    `kind` 抛 `ValueError` `[本次确认]`。
  - `specs/d.py:232-235` D 的 `write_set = frozenset(("research_questions", "search_requests"))`
    ⇒ **不含 `analysis_reports`**；`capabilities.py:1109` `WRITE_SETS = _specs.write_sets()`
    ⇒ `WRITE_SETS["D"]` 就是它 `[本次确认]`。
  - `agent_d/core.py:66` `self.enabled_kinds = tuple(self.cfg.get("enabled_kinds") or S.REPORT_KINDS)`
    ⇒ **D 的 `ingest.enabled_kinds` 默认等于 `S.REPORT_KINDS`**（4 个）；`agent_d/ingest.py:66-67` 按它过滤
    `[本次确认]`。
  - `agent_d/write_report.py:38-45`（`run_id = rows[-1]["question_id"]`、`resolve_out_path(...)`）与
    `:407-410`（只有 `path.write_text`，**没有落库**）`[48-07 §11.1 逐字；本次未逐行打开]`。
  - 真机（§0.3）：根1 `write_report` **45** 行、盘上 `reports/*research*.md` 只有 **5** 份；
    两根 `analysis_reports` **全 0 行** `[本次复算]`。
  - `closing.py:165` 的 `analysis_report_rows` 档「分析报告行数（`analysis_reports`）」（`:823` 是它的取值分支）
    —— 它会第一处把「C 的产出」与「D 的报告」混成一档 `[本次确认到行号；混档论证为 `48-07 §11.1`]`。
  - `44 J-01` 已裁定「S-07 改判为『不可按原形态做』…**不许**为它扩 `REPORT_KINDS`」`[来源]`。
- **方案 A：新增 D 自己的报告落点（新表）**
  - 做法：`schema.TABLES` 新增一张研究报告表（自有 `id_kind`、自有 `kind` 词表或字段面），
    `AgentD.write_report` 双写（文件 + 登记行），`specs/d.py` 的 `write_set` 加该表，`closing` 新增一档读数。
  - 理由：`REPORT_KINDS`（`schema.py:442`）是「C 的四个分析器」的枚举；D 的研究报告没有合法 kind；
    新表的字段面可以按研究报告设计（九节/五段结构），不必迁就 C 的 `params`/`payload` 形状。
  - 成本：文件 **5+**（`schema.py` **禁改区**、`specs/d.py` **禁改区**、`capabilities.py` **禁改区**、
    `agent_d/write_report.py`、`agent_d/core.py`、`closing.py`）、落点 **6+**、约 **150–250 行**
    （表定义 + 行类型 + validate + ID 分配器 + 双写 + 读数 + 快照重冻）。
    会红/需重冻：`tests/test_schema_*`、`tests/test_capabilities*.py`、
    `tests/test_tool_surface_snapshot.py` + `tests/golden/tool_surface_snapshot.json`、
    `tests/test_closing*.py` 的档位表、`tests/test_scheduler.py:828-839`（用 `WRITE_SETS` 相交观察分波，
    D 的写集一变要复算）。
    快照与文档同步点：`SCHEMA_VERSION` 是否 bump 要另裁（`48 总 §2.5`）；`draft/44 J-01` 回填分界；
    `draft/45 §1.4` 改判。
    真机影响：`write_report` 的 45 次从「只有文件」变成「文件 + 表行」；`analysis_reports` 仍是 0 行
    （本方案不动它）。
  - 风险与不可逆点：新表是**磁盘格式契约**（`schema-migration` 禁改区的登记理由逐字是「改它等于改磁盘
    格式契约」）；`SCHEMA_VERSION` 一旦 bump，历史工作区的读侧兼容要一次性处理；5 份历史 md 的回填与否
    是第二个人裁。
  - 兼容闸：不许加必填字段；新表只增不改；`closing` 新档必须按「在什么工作区算得出数」分组
    （`44 J-23`：30 档名字不能删、不能改名，只能加分组标注）。
  - 禁改区：`schema.py`、`specs/d.py`、`capabilities.py` 三处**都在册** ⇒ 三处都要 2 名人审，不许自签。
- **方案 B：随 L-01/L-03 走 `documents`**
  - 做法：`write_report` 的产物登记进 `documents`（或 `manuscripts`），沿用既有表与既有 `doc_id` 分配；
    `specs/d.py` 的 `write_set` 加 `documents`。
  - 理由：`documents` 已有 `id_kind="doc"`、`status`、`revision`、`review_rounds`（真机两根各 76 行，
    `48-06 §0.10`）⇒ 正是「一份可交稿的文本」的形状；L-01/L-03 本来就在动 `documents` 这条线，
    同批做不新增表。
  - 成本：文件 **3**（`specs/d.py` **禁改区**、`agent_d/write_report.py`、`closing.py`）、落点 **3**、
    约 **60–120 行**。
    会红/需复核：`tests/test_scheduler.py:828-839`（`WRITE_SETS` 相交 ⇒ D 与 G/H 的分波会变）、
    `tests/test_closing_gate.py` 的 `report_files`/`documents` 档、`tests/test_core_audit_agent_d*` 一族；
    `specs/d.py` 需 2 名人审。
    真机影响：D 的报告会与 G 的稿件混在同一张表的同一批行里，读数必须靠 `created_by` / `kind` 分辨。
  - 风险与不可逆点：**与 G 混档** —— `documents.status` 是审校线的判据（`verify.py:945-961` 逐字按
    `documents.status` 判「内部断言引用所在稿件 status 不是 accepted」）⇒ D 的报告行若拿到 `accepted`，
    会被别的审计当真稿；若给一个非 accepted 的状态，`internal_citation_not_accepted` 的语义又被污染。
  - 兼容闸：`documents` 不加必填字段；D 写入的行必须带 `created_by="agent-D"` 与可分辨的 kind。
  - 禁改区：`specs/d.py` 在册；`documents` 的表定义在 `schema.py`（本方案可不改它，只写既有字段）。
- **方案 C：挂起（本批不施工，只登记改判 + 加一条反向门）**
  - 做法：照 `44 J-01` 与 `46-07 §14`（S-07 可行性 = **低（当前形态不可行）**）照抄：产出是「改判 + 登记」
    而不是代码；只加一条负控 —— 造 `S.AnalysisReport(kind="research", …)` ⇒ `validate()` **必须抛**
    （`schema.py:842-843`），用它钉住「不许为 S-07 扩 `REPORT_KINDS`」。
  - 理由：两条正确落点都要动禁改区（`schema.py`）；S-01 落地后 `analysis_reports` 是 **C 的产出表**，
    S-07 若同批进来会把两件事混成一档 —— 这正是 `44 J-01` 要防的。
  - 成本：文件 **1**（测试文件，新增 1 条反向门；不动 `src/`）、落点 **1**、约 **10 行**。
    会红：无（这条是**反向门**：改前改后都应绿；一旦有人扩了词表它就变红）。
    真机影响：无（`46-07 §14` 判「部分（文件数 vs 表行数）可证伪」，本块不改代码 ⇒ 不做回放）。
  - 风险与不可逆点：挂起的代价是 `draft/45 §1.4` 的错口径继续在册（「`write_report` 也落台账」）
    ⇒ 挂起**必须同批改 `draft/45 §1.4` 的措辞**，否则接手的人照它施工就会撞 `REPORT_KINDS`。
  - 兼容闸：不产生代码 diff。
  - 禁改区：不动 `schema.py` / `specs/d.py`。
- **不裁的默认后果**：`write_report` 继续只写文件不登记 ⇒ 根1 的 45 次调用继续只对应盘上 5 份 md
  （同名覆盖把 45 折成 5），两根 `analysis_reports` 继续 0 行；`draft/45 §1.4` 的错口径继续在册；
  `44 J-01` 继续挂空，S-07 进入下一批时仍要重做一遍可行性判断；而 D 的 `ingest` 也继续没有报告可吸收
  （见决策 6）。
- **取舍点**：分歧在「D 的报告该有自己的表和 kind（干净，但动三处禁改区、可能 bump schema）」
  与「借 `documents` 的既有形状（省一张表，但与 G 的审校状态机混档）」，以及「这一批到底是挂起还是落地」。

---

### 决策 5 — S-02 / S-08 / S-09「真机不可证伪」的处置

- **现状与证据**：
  - 真机（§0.3）：根2 的 **22 个工作区** `data/research_questions.json` 全部是
    `{"schema_version": 1, "rows": []}` ⇒ **0 行**；根1 46 行（26 个工作区非空）`[本次复算]`。
  - D 的五个核心动作两根全 0：`assess` 0 / `submit_gaps` 0 / `adjudicate` 0 / `trace_question` 0 /
    `trace_l3` 0；根1 的 D 其余动作 `research` 70 / `run_round` 18 / `write_report` 45 /
    `consider` 3 / `ingest` 2 / `ingest_detailed` 5 / `poll` 2 / `probe_c` 1 / `propose_question` 89 /
    `register_conjecture` 122 `[48-07 §0.4]`。
  - **D 未接 LLM**（本次确认到装配面）：`host.py:501-505` 只把 `role_llm["H"]` 与 `role_llm["F"]`
    登记进 `llm_by_role`；`specs/d.py:167` 用 `llm=d.llm` 构造 `AgentD`，而 `d.llm` 就是 `None`；
    `agent_d/core.py:41` `self.llm = llm`，`:1152` `if self.llm is not None:` 才走 LLM 分支
    `[本次确认]`。⇒ S-09 的「模型原话直出」（`:1265-1269` 的 `setdefault`）在真机上从未发生。
  - `46-07 §14` 对 S-02 / S-08 / S-09 的「真机可证伪」一列逐字是 **不可**（S-02 行注「表不存在、动作 0 次」；
    S-09 行注「未接 LLM，只能替身」）；`44 J-08` 判定真机闸改为「探针 + 单元负控」并写明「不可证伪」
    `[来源]`。
  - S-08 的核心风险（`46-07 §10` 逐字）：`trusted` 一旦来自 D 自己（「我看了一遍没毛病」），
    就等于**把自证重新引入**，而整套设计的核心是「自报不算凭据」（`evidencebits.py:118-120` 逐字）
    `[来源]`。
- **方案 A：替身 + 负控（照 `44 J-08`）**
  - 做法：三块全部用注入式替身（照 `tests/test_semantic_review.py` 的 `_Model` 返回合规 JSON 的写法）
    与单元负控验证；真机侧只留「探针 + 读数落 `draft/44`」，明写「本条无法用真机证伪」。
  - 理由：`46-07 §14` 已判「不可」，且根2 的 0 行是**结构性**的（不是样本不足）；
    `48 总 §2` 闸三原文要求这类条目「只配探针 + 负控」。
  - 成本：文件 **3–5**（`agent_d/{consider,submit_gaps,research,assess}.py`、`agent_d/_support.py`、
    `agent_d/core.py`，都不在册；改动面三块：`_verdict` 单一来源 / `trusted` / `_conclusion_for`）、
    落点 **5–7**、约 **120–200 行**（含 3–5 条新负控）。
    会红：S-02 是纯重构 ⇒ `tests/test_agent_d.py`（`assess` 2 / `submit_gaps` 3 / `trace_question` 1）、
    `tests/test_agent_d_interactions.py`（`write_report` 3）、`tests/test_dup_consolidation.py`
    （`submit_gaps` 1 / `trace_question` 1）**必须全绿**；
    S-09 的 `tests/test_coverage_agent_d_demo.py`（`write_report` 5 处）里若钉了结论小节的固定文本会红；
    S-08 若改判据 b 的触发条件，`tests/test_agent_d.py` 里凡断言「度数低且无 `quote_verified` ⇒
    `insufficient is True`」的用例必须同批复跑，且**不传 `trusted` 的既有用例必须仍绿**（它们是
    「不误伤」对照）。
    快照与文档同步点：`draft/44 J-08` 写「不可证伪」；S-08 改的是**判据**（不是措辞）⇒ 必须在 `draft/44`
    登记「从哪一趟起口径变了」并写明「这是用户点名的那条口径，与 `evidencebits` 的位机制不冲突」。
    真机影响：**0**（无靶子可回放；历史 46 行 `research_questions` 全是根1 且不受影响）。
  - 风险与不可逆点：替身验证的是「改动的内部一致性」，不是「真机上 D 会怎么做」；`_verdict` 的缓存键
    （`(qid, 关系表 sha/行数, 概念表行数)`）在真机上从未跑过 ⇒ 缓存的失效条件只是**理论上**的；
    `conclusion_body` 若只进返回值、`write_report` 不读它，等于「审计原话」没有人读
    （`46-07 §12` 第 6 条风险一要求「让 `write_report` 在某一处能读它，或明确『原话只进返回值』」
    —— 施工时必须**二选一并写明**）。
  - 兼容闸：S-02 对外动作面一字不改（`specs/d.py` 的 12 个动作不动）；S-08 加的是**可选**参数
    （不给就是今天，`analyze_gaps` 签名 `agent_d/_support.py:241-249` 现状无 `trusted`）；
    S-09 的 `llm=None` 分支输出必须与今天**逐字相同**（可用 `tests/test_agent_d.py` 的固定串做快照）。
  - 禁改区：三块都不在 FC-27 清单；**不许**走 `specs/d.py` 的 `params` 改动（`trace_l3` 的签名改动 =
    auth-audit，`48-07 §10` 已否掉方案甲）。
- **方案 B：先给 D 接 LLM，再做 S-02 / S-08 / S-09**
  - 做法：先在装配面把 D 的模型缝接上（`host.py:501-505` 的 `role_llm` 加 `"D"`，或让 `specs/d.py:167`
    拿到非 `None` 的 `llm`），跑真机产生 `research_questions` 行与 `research`/`write_report` 的 LLM
    分支读数，再做三块改动。
  - 理由：D 未接 LLM 是「不可证伪」的直接原因（`agent_d/core.py:1152` 的 LLM 分支从未执行）；接上之后
    S-09 的「模型写出高置信度口吻、数字是 low」才有真实靶子。
  - 成本：文件 **2–4**（`host.py` 不在册；`specs/d.py` **在册** auth-audit ⇒ 若走它需 2 名人审；
    `agent_d/core.py`）、落点 **2–3**、约 **20–60 行**装配改动；
    **再加真机成本**：D 的 `research` 45 次 + `propose_question` 89 次 + `register_conjecture` 122 次
    （根1，`48-07 §0.4`）一旦接上模型就是实打实的 token 账单。
    会红：`tests/test_agent_spec_reconciliation.py`、`tests/test_capabilities*.py` 的两层动作表、
    `tests/golden/agent_surface_snapshot.json`（若动声明面）；`host.py` 侧的装配读数断言
    （本次未定位具体行号，`[判断类]`）。
    快照与文档同步点：`draft/44` 要记「D 从这一趟起接了 LLM」这条**能力变更**（比口径变更更重）。
    真机影响：`research_questions` 首次非 0（根2 从 0 行起）；`research`/`write_report` 的 `conclusion`
    首次由模型产出。
  - 风险与不可逆点：**先接 LLM 再做判据**把两件不可逆的事叠在一起 —— D 一接模型，根2 的 22 个工作区
    会开始产出 `research_questions` 行（**首次非 0**），而 S-02/S-08/S-09 的口径尚未定 ⇒ 这批历史读数
    会被「接 LLM 之前/之后」与「判据改之前/之后」两条分界同时切；且接线本身要动 `specs/d.py`（禁改区）。
  - 兼容闸：接 LLM 不许改变 `llm=None` 的行为（`agent_d/core.py:1152` 的分支必须保留）；
    `research_questions` 首次非 0 必须写进 `draft/44` 并说明分界。
  - 禁改区：`specs/d.py` 在册（auth-audit，理由串逐字「改这里等于改权限面本身」）；`host.py` 不在册。
- **方案 C：挂起三块，只登记不可证伪**
  - 做法：S-02/S-08/S-09 本批不施工；只在 `draft/44 J-08` 补「不可证伪」的正式登记，并把
    `48-07 §汇总.2` 的未核实项升级为正式条目。
  - 理由：三条都不可证伪，且 S-08 的核心风险（`trusted` 来自 D 自己 = 把自证重新引入）没有真机读数能约束
    ⇒ 先做等于把「改对了没有」交给替身。
  - 成本：**0 行代码**；1 处登记；会红：无；真机影响：无。
  - 风险与不可逆点：`assess` / `submit_gaps` / `trace_question` / `trace_l3` / `adjudicate` 五个动作
    继续两根全 0 ⇒ D 的「减」与「接通」两个缺口继续存在；D 的报告继续完全是确定性的
    （`write_report` 45 次 ok 但 LLM 分支从没跑过）。
  - 兼容闸：不产生 diff。
  - 禁改区：不动任何禁改区。
- **不裁的默认后果**：三条继续停在「不可证伪、只能替身」的状态，具体是 —— D 的判据继续四处各算一遍
  （`assess.py:36-43` / `consider.py:24-25` / `submit_gaps.py:28-30` / `research.py:29-32`）；
  `trace_l3` 继续在 `tests/` 有 0 处调用点（`48-07 §10`），而 M 结构上造不出 `evidence`
  （它只经 `payload_preview` 露出）；`conclusion` 继续由模型原话直出（`agent_d/core.py:1265-1269` 的
  `setdefault`）而置信度由 `_rank_min` 夹取 ⇒ 「文本强度」与「数字档位」在真机上从来没有被分开验证过。
- **取舍点**：分歧在「先修判据、用替身担保（省真机钱，但判据与真机从未相遇）」与「先给 D 接 LLM、
  把不可证伪变成可证伪（把能力变更与判据变更叠在一起，且要动禁改区装配面）」。

---

### 决策 6 — `D.ingest.enabled_kinds` 是否扩

- **现状与证据**：
  - `agent_d/core.py:66` 默认等于 `S.REPORT_KINDS`（**4** 个：hottest/paths/cold/gaps）；
    `agent_d/ingest.py:66-67` 按它过滤，不在就进 `last_ingest["skipped"]` `[本次确认]`。
  - C 的动作与返回形状（本次逐个确认）：走 `_report()` 并返回 `AnalysisReport` 的有
    `hottest.py:37/108`、`cold.py:31/154`、`paths.py:26/37/293`、`gaps.py:301`，以及
    `handle.py:19/36`（kind = `"unknown"`）；**不走 `_report`** 的有 `contradictions`
    （`core.py:1091-1094`，直接返回 dict）、`structural_duplicates`（`core.py:1106`，直接返回 dict）、
    `neighbors` / `relations_between`（本次未定位其返回点，`[判断类]`）、`check_conflict`
    （纯函数，`core.py:1124-1127`）`[本次确认到所列行]`。
  - 工具面把 dataclass 转掉了：走 `_report` 的动作在注册时是
    `lambda …: self.hottest(...).to_dict()`（`core.py:969/992/1004/1016`）`[本次确认]`。
  - 真机（§0.3）：根1 C 产物 37 份、`payload_keys` 空 26（hottest 11 / gaps 12 / cold 2 / paths 1）、
    非空 11（contradictions 8 / structural_duplicates 1 / neighbors 1 / relations_between 1）；
    根2 22 份、空 21（hottest 14 / gaps 7）、非空 1（contradictions 1）`[本次复算]`。
  - `capabilities.py:1137` `READ_ONLY_WRITE_EXCEPTIONS["C"] = frozenset({"analysis_reports","search_requests"})`
    ⇒ C 的写面已登记，权限面不需要动 `[本次确认到 `:1137`；断言段为 `48-07 §6.1`]`。
  - `48-07 §汇总.5` 第 2 条裁定：`D.ingest.enabled_kinds` 默认等于 `S.REPORT_KINDS`
    ⇒ **只有那 4 个 kind 会被 D 吸收**，其余五个动作落盘也不会进 D，这一点必须在下一批的施工单里写明
    `[来源]`。
- **方案 A：保持 4 个 kind**
  - 做法：`enabled_kinds` 默认不动；只在 S-01 落地后把「D 只吸收四个 kind」写进施工单与
    `agent_d/ingest.py` 的 docstring / 读数。
  - 理由：`REPORT_KINDS`（`schema.py:442`，禁改区）就是「什么能落 `analysis_reports`」的判据，
    D 的 `enabled_kinds` 与它同源是**结构性一致**；真机上那 4 个非空 `payload_keys` 的动作
    （contradictions / structural_duplicates / neighbors / relations_between）本来就返回**自己的形状**
    （不是 `AnalysisReport`），D 也没有解析它们的逻辑（`ingest.py:66-67` 只按 kind 过滤）。
  - 成本：**0 行代码**（只写文档）；会红：无。
    快照与文档同步点：`48-07 §汇总.5` 第 2 条落地。
    真机影响：S-01 落地后 `analysis_reports` 首次非 0，D 只吸收其中 4 个 kind 的行。
  - 风险与不可逆点：D 永远看不到 C 的 `contradictions` 一族，而 `ingest_contradictions` 这个开关
    **已经存在**（`agent_d/core.py:70`，它读的是 C 报告 / C 服务里的矛盾，不是 C 的 `contradictions` 动作）
    ⇒ 两个「矛盾」入口的语义差别**没有任何判据守着**。
  - 兼容闸：不动词表、不动 `specs/c.py` / `specs/d.py` / `schema.py`。
  - 禁改区：无（0 行）。
- **方案 B：扩到 9 个动作的产物（扩 `REPORT_KINDS` 到 9）**
  - 做法：把 `contradictions` / `neighbors` / `relations_between` / `structural_duplicates` / `handle`
    五个 kind 加进 `schema.REPORT_KINDS`，`D.ingest` 跟着扩；C 的这 5 个动作改成走 `_report()`。
  - 理由：9 个动作都是「C 的分析产出」，真机上这 5 个动作确实产出了非空 `payload_keys` 的记录
    （根1 11 份非空里 10 份属于它们）⇒ 它们的产物在盘上有、但不在表里。
  - 成本：文件 **4–6**（`schema.py` **禁改区**、`agent_c/core.py` 与另 4 个动作文件、`agent_d/core.py`、
    `agent_d/ingest.py`、`closing.py`）、落点 **6–8**、约 **150–250 行**。
    会红/需重冻：`tests/test_agent_c.py`、`tests/test_agent_c_service.py`、`tests/test_closing*.py`
    的 `analysis_report_rows` 档、`tests/test_tool_surface_snapshot.py` +
    `tests/golden/tool_surface_snapshot.json`（若改返回形状）、`tests/test_capabilities*.py`
    （`WRITE_SETS["C"]` 的注释面）；`schema.py` 需 2 名人审。
    真机影响：`analysis_reports` 从 0 行起、S-01 落地后是每工作区 4 行，本方案再叠 5 类 ⇒ 读数口径要在
    `draft/44` 一次写清「哪些 kind 从哪一趟起有产出方」。
  - 风险与不可逆点：`handle` 的 `kind="unknown"` 是**分派失败**的产物
    （`agent_c/handle.py:19-27` 与 `:36-47`；`_support.py:274-277` 的 docstring 逐字说
    「`unknown` 不能落盘 —— 落进表里的 report 必须能被 D 按 `kind` 分派」）⇒ 把它加进 `REPORT_KINDS`
    等于**把失败写成产出**；且这 5 个 kind 的 payload 结构互不相同（裸 dict vs `AnalysisReport.to_dict()`），
    D 的 ingest 需要 5 套解析。
  - 兼容闸：`REPORT_KINDS` 加取值是「放宽」，但 `closing.py:165` 的 `analysis_report_rows` 会把 9 类
    折成一个数字 ⇒ 必须同时加分组标注（`44 J-23`：30 档不许改名，只能加分组）。
  - 禁改区：`schema.py`、`specs/c.py`、`specs/d.py` 三处都在册。
- **方案 C：让 D 只吸收自己产的**
  - 做法：`enabled_kinds` 的语义从「吸收 C 的哪几类」改成「吸收 D 自己产出的报告」；C 的报告一律不进 D，
    D 改从 `documents` / `research_questions` 自产自销。
  - 理由：`ingest` 的现状就是 D 读 C 的报告（`ingest.py:66` 的 `info["kind"]` 来自 C 产物）；
    若 S-08 的 `trusted` 要靠「D 自己读过」来支撑，就会把 `evidencebits.py:118-120` 的
    「自报不算凭据」绕过去 ⇒ 切断 C→D 是一种保守化。
  - 成本：文件 **2–3**（`agent_d/core.py`、`agent_d/ingest.py`，都不在册）、落点 **2–3**、约 **30–60 行**。
    会红：`tests/test_agent_d*.py` 里凡断言 ingest 从 C 报告提取问题的用例。
    真机影响：D 的 `ingest` 真机只有 2 次、`ingest_detailed` 5 次（根1，`48-07 §0.4`）⇒ 影响面小，
    但方向是「切断 C→D」。
  - 风险与不可逆点：切断之后 `ingest_contradictions`（`agent_d/core.py:70` 的开关）失去对象；
    `contradictions` 一族真机有 8 份产物，切了就没有任何下游。
  - 兼容闸：`enabled_kinds` 的取值语义变更 = 口径变更，要写进 `draft/44`。
  - 禁改区：无需动禁改区（`agent_d/*` 不在册）。
- **不裁的默认后果**：`D.ingest` 继续只吸收 4 个 kind；S-01 落地后 `analysis_reports` 第一次有行，
  D 会开始吸收「C 的 4 类报告」，而 C 的另 5 个动作的产物（真机根1 有 10 份非空 `payload_keys`）
  继续只躺在 `out/tasks/*.json` 里、没有任何下游；`48-07 §汇总.5` 要求的「必须写明」这句会缺。
- **取舍点**：分歧在「D 的问题来源该不该跟着 C 的产出面一起扩」，以及「`handle` 的分派失败产物
  （`kind="unknown"`）算不算一种可吸收的 kind」。

---

### 决策 7 — P-09 的代价真源

- **现状与证据**：
  - `agent_f/core.py:375-376` `pre_spend_gate(..., budget_left_usd=self.cfg.get("round_budget_usd"))`；
    `:385-387` `budget_decision(cost_usd=float(self.cfg.get("round_cost_usd", 0.02)),
    cap_usd=self.cfg.get("round_cost_cap_usd"), spent_usd=float(self.cfg.get("spent_usd", 0.0)))`
    `[本次确认]`。
  - 全仓 grep `round_budget_usd|round_cost_usd|round_cost_cap_usd`：**只有这 3 行读侧**，
    `src/`、`tests/`、`docs/` 里**没有任何赋值点** `[本次确认，全仓 grep]`。
  - `tools/attack_tools.py:281-289` `_agent_for(store)` ⇒ `return AgentF(store, llm=default_llm())`，
    **不传 config** `[本次确认]`。
  - `attack_tools.py` 的 F 类工具签名只有 `store` + `plan_id`（`:494` / `:531` / `:556` / `:585`）
    ⇒ **工具路径上没有任何 `task_id`** `[本次确认]`。
  - `agent_f/` 全目录 grep `task_id|TokenMeter|tokenmeter`：**0 命中** `[本次确认]`。
  - `tokenmeter.py:250-256` `usd_for(task_id)` 按 `usage_ledger` 行的 `task_id` 过滤求和（`:253-256`）
    `[本次确认]`。
  - `conductor.py:1022-1031` 权威账口径逐字「权威账是 `usage_ledger`，`tasks.tokens/usd` 由它派生」；
    `:664-697` 的记账粒度是**召唤级**（`Charge(scope="summon", …)`），docstring `:680-691` 逐字说
    「等各 agent 的 `_call` 也接上 `charge()`（细到每次工具调用 / 每次重试）之后，这里必须改成
    『只记零值兜底』」`[本次确认]`。
  - `attackround.py:231-241` `budget_decision(*, cost_usd, cap_usd, spent_usd=0.0)`；`cap_usd=None`
    ⇒ 恒 `{"status":"unbounded"}`（`[48-06 §5.3]`：`pre_spend_gate` 的 `budget_known=False` 在
    `attackround.py:223`、`budget_decision` 恒 `unbounded` 在 `:237-238`）。
  - 真机：76 个计划的 history 里「超出本轮预算」**0** 次、`budget_exceeded` **0** 次（`48-06 §0.6`）
    `[来源]`。
  - `44 J-07`：P-09 是「死开关套死闸门」；代价真源建议改用 `tokenmeter.TokenMeter.usd_for(task_id)`
    （与 `conductor.py:1022-1031` 的权威账同口径）；`48 总 §3` 硬约束 `C9`：P-09 **必须先接代价真源
    再谈裁量留痕** `[来源]`。
- **方案 A：接 `tokenmeter.TokenMeter.usd_for(task_id)`**
  - 做法：`AgentF` 侧新增「读账」入口（从 `self.store` 造 `TokenMeter` 或直接按 `usage_ledger` 求和），
    把真实花销写进 `history_row["cost"] = {"round_cost_usd":…, "spent_usd":…, "cap_usd":…,
    "source": "usage_ledger"}`，**不参与判据**；`budget_decision` / `pre_spend_gate` 的判定本身不动。
  - 理由：`44 J-07` 逐字要求；权威账口径在 `conductor.py:1022-1031` 已定，`usd_for` 是与它同口径的
    唯一读取口（`tokenmeter.py:250-256`）。
  - 成本：文件 **3–4**（`agent_f/core.py`、`agent_f/step.py`、可能 `tools/attack_tools.py` 传 `task_id`；
    都不在册）、落点 **3–4**、约 **25–40 行**。
    **另有结构性缺口**：`usd_for` 的入参是 `task_id`，而 `agent_f/` 与 F 的工具路径上都没有 `task_id`
    （本次 grep 0 命中，见上）⇒ 要么新增一条把 `task_id` 从 `conductor` 传到 `attack_tools` 再到
    `AgentF` 的**新接线**（跨 `conductor.py` / `tools/attack_tools.py` / `agent_f/core.py` 三文件），
    要么退化为「按整个工作区账本求和」（那既不是「这一轮」也不是「这一 task」的钱）。
    会红：四个键名在 `tests/` 里 **0 命中** ⇒ 无既有断言读它们；`tests/test_agent_f.py:501-516`
    （夹具 `budget(max_rounds=0)`）走 `AT.can_round` 的**轮数**分支 ⇒ 不受影响。
    新增 `history["cost"]` 键：`history` 是 `list[dict]`，schema 只校验 sid/status/owner/blocked_reason/
    round/长度 ⇒ **加键安全**。
    快照与文档同步点：`runflow.py:1690-1693` 的 `cost.json` 与 `usage_ledger` 对账口径不变；
    `draft/44 J-07` 回填。
    真机影响：**不可证伪**（76 个计划的历史行不回填；「超出本轮预算」与 `budget_exceeded` 改后仍应为 0）
    ⇒ 按 `48 总 §2` 闸三与 `44 J-08` 只配探针 + 单元负控。
  - 风险与不可逆点：`usd_for(task_id)` 拿到的是**整个 task** 的累计花销（`usage_ledger` 的粒度是召唤级，
    `conductor.py:682-691` 逐字），而 F 的一轮是在一个 task **内部**发生的 ⇒ 写进
    `history_row["cost"]["round_cost_usd"]` 的数字**不是这一轮的钱**；把它标成 `round_cost_usd`
    就是新增一处口径错位（真正的轮级细账要等各 agent 的 `_call` 接上 `charge()`，那是另一件事）。
  - 兼容闸：`pre_spend_gate` / `budget_decision` / `pick_parallel_routes` 的判定不许动
    （`46-06 §7.7`）；缺失的 `cost` 键不许变成新闸门；`budget.max_rounds` 的硬停不许退场（FC-18）。
  - 禁改区：`agent_f/core.py`、`agent_f/step.py`、`tools/attack_tools.py`、`tokenmeter.py`、
    `conductor.py` 都不在 FC-27 清单（`47 §3-C2`）⇒ 施工前仍应先跑
    `python -B scripts/noai_gate.py --git --since <基线>`。
- **方案 B：保留死开关（只改提示词 / 只登记）**
  - 做法：四个键原样保留（永远读不到值），只把「同一命题最多 3 次」从提示词硬规则改成
    「框架给读数 + 要 `decision` 留痕」；`history_row["cost"]` 不写。
  - 理由：判据一条都不动 ⇒ 零回归风险；`budget_decision` 恒 `unbounded` 是**现状**，改提示词不会更坏。
  - 成本：文件 **1–3**（`agent_f/core.py` 的提示词广告面、`agent_prompts.py` / `specs/m.py` 的镜像；
    `specs/m.py` **在册** auth-audit）、落点 **2–3**、约 **10–30 行**。
    会红：`tests/test_agent_prompts.py` 的提示词一致面（本次未定位行号，`[判断类]`）。
    真机影响：无（`history` 里仍无 `cost` 键；「超出本轮预算」仍 0 次）。
  - 风险与不可逆点：`48 总 §3` 硬约束 `C9` 明写「P-09 必须先接代价真源再谈裁量留痕」
    ⇒ 本方案**违反 C9 的先后**：在没有代价真源的情况下要求模型对一件框架自己都不知道的事做决定；
    `round_budget_usd` 一族继续是「死开关套死闸门」，`pre_spend_gate` 的 `budget_known` 永远 `False`。
  - 兼容闸：不动判定；提示词义务若加，必须与 `agent_prompts.py` / `specs/m.py` 的镜像同轮改
    （`48-06 §5.3`）。
  - 禁改区：`specs/m.py` 在册。
- **方案 C：直接删 `round_budget_usd` 一族**
  - 做法：删掉 `agent_f/core.py:375-376` / `:385-387` 的三处读与 `AR.budget_decision` /
    `pre_spend_gate` 的 `budget_left_usd` 分支；`_self_dead_end` 的「超出本轮预算」一档随之消失。
  - 理由：四个键全仓无赋值点 ⇒ 它们今天唯一的作用是把 `budget_decision` 钉死成 `unbounded`、
    把 `pre_spend_gate` 的 `budget_known` 钉死成 `False`；删掉等于把「假装有预算」变成「明确没有预算」，
    `round_budget_usd` 这个名字不再误导人。
  - 成本：文件 **2–3**（`agent_f/core.py`、`attackround.py`，都不在册）、落点 **3–5**、约 **20–40 行**
    （以删为主）。
    会红：`tests/test_agent_f.py` 里凡断言 `checks["budget_known"]` / `budget_decision` 档位的用例
    （本次未逐行核实行号，`[判断类]`）；`tests/test_attack_round.py` 的 `budget_decision` 一族。
    快照与文档同步点：`attackround.py:53-55` 的 `DEAD_END_REASONS` 里 `"超出本轮预算"` 会**没有产出点**
    ⇒ `tools/vocab_census.py` 的 R011（死取值）可能把它扫成新的 dead vocab，除非同批处理 ——
    而词表在 `attackround.py`，**加/删取值都是「改受控词表」**（与决策 2 同一类人裁）。
    真机影响：`DEAD_END_REASONS` 的取值面变化；历史 `dead_end_reason="超出本轮预算"` 的行真机 0 行
    ⇒ 无历史行受影响。
  - 风险与不可逆点：**删判据比加判据更难回头** —— `budget.max_rounds` 的硬停还在（FC-18），
    但「这一轮要不要花钱」这个闸门从此只剩 `pre_spend_gate` 的另外几条原因；一旦删了，未来接上代价真源时
    要重新设计「钱 + 裁量」两栏的接口，而那时的历史行里没有 `cost` 可对齐。
  - 兼容闸：`DEAD_END_REASONS` 删取值 = 受控词表**收窄** ⇒ `attackround.py:131-133` 的校验对**新写**的行
    生效（历史行真机 0 行）；`schema.py` 一侧不涉及。
  - 禁改区：`attackround.py` 不在册；但 `DEAD_END_REASONS` 是受控词表，改动属「改词表」类。
- **不裁的默认后果**：四个键继续只被读、不被写 ⇒ `pre_spend_gate` 的 `budget_known` 继续 `False`、
  `budget_decision` 继续恒 `{"status":"unbounded"}`；工具路径上的 F（`tools/attack_tools.py:289`）
  继续拿不到 config，于是即使有人在某处给 `AgentF` 传了这四个键，**走工具的那条真机路径也读不到**；
  `history` 里继续没有任何「这一轮花了多少」的读数；`44 J-07` 与 `48 总 C9` 继续挂空。
- **取舍点**：分歧在「真源接上之后写进 `history` 的那个数字该按 task 还是按轮（`usage_ledger` 今天
  只有召唤级粒度、F 的工具路径上连 `task_id` 都没有）」，以及「四个死键该留着当占位、还是删掉再重设计」。

---

### 决策 8 — E-11 / E-12 与既有断言冲突的处置顺序与范围

- **现状与证据**：
  - E-11 的现状判据：`agent_e/_support.py:392-397` 逐字「脚本打印了 N 行 REPRO_RESULT（多于一行）
    ⇒ 视为格式非法，拒绝在互相矛盾的结论里挑一个」并 `return None, notes` `[本次确认]`；
    `_parse_conclusion` 的签名与返回是 `:374-416` 的 `(dict | None, list[str])` `[本次确认]`。
  - **直接对立**：`tests/test_agent_e.py:303-315`，夹具 `:309-312` 打「行首形态 supports」+
    「JSON 键形态 refutes」，`:314` 逐字 `assert out["result"] == "inconclusive", out`、
    `:315` `assert "多于一行" in out["notes"], out["notes"]`；`:304-307` 的 docstring 逐字说
    「容错不等于允许『从两个互相矛盾的结论里挑一个』」`[本次确认]`。
    ⇒ 新口径（两行矛盾 ⇒ 取最后 + `protocol="conflict"`）会让 `:314` **必红**。
  - E-12 的现状：`agent_e/core.py:402` 为 `exit_code = 0 if verified else None`
    ⇒ `compile_error` / `decl_mismatch` / `uses_sorry` 与 `timeout` 在 `exit_code` 上**逐字相同**
    （`[48-06 §0.2]`）；真机 80 条 formal 行里 `timeout` / `import_unavailable` / `no_backend` /
    `tool_crashed` **一次都没有**（四态：`verified` 35 / `compile_error` 33 / `decl_mismatch` 9 /
    `uses_sorry` 3）`[48-06 §0.2]`。
  - **读侧地雷**：`agent_e/_support.py:706-709` 的 `_result_reason` 第一条分支逐字
    `if row.exit_code not in (0, None): return f"脚本 exit_code={row.exit_code} ⇒ 未正常跑完，
    记 inconclusive（崩溃不得当成支持）"` ⇒ E-12 让 concluded 落 `exit_code=1` 之后，
    「检查器说这份证明没通过」会被说成「崩溃」；`44 J-06` 逐字要求「**必须先判 `method=="formal"`**」
    `[本次确认 `:706-709`；J-06 为来源]`。
  - `44 J-06` 逐字：「两条都得**先改写测试再改代码（顺序不能反）**」`[来源]`。
  - 真机回放靶子：E-11 用 `p5-polish-20261001-234839` 五行（预期 `protocol` =
    missing / missing / multi_line / bad_json / invalid_result；其中 0002 是「10 行 `REPRO_RESULT`
    而 payload 不是 JSON」⇒ 落「无一行可用」⇒ `multi_line` + 维持拒收）`[48-06 §0.8]`；
    E-12 用 `p8g` 0002/0003/0004（`compile_error`）与 `p8e` 0002（`decl_mismatch`，
    `48-06 §0.9` 的更正）`[来源]`。
- **方案 A：先改测试再改代码（照 `44 J-06`）**
  - 做法：第一步（不动 `src/`）把 `tests/test_agent_e.py:303-315` 的期望改成新口径
    （断言 `protocol == "conflict"` 与 notes 含 `[conflict]`），跑一次确认它**红在实现上**；
    E-12 侧同批在 `tests/test_agent_e_formal_path.py:243-264` 与 `:322-338` 补两组断言
    （concluded 四档 ⇒ `exit_code == 1` 且 `check_outcome == "checked_not_proved"`；
    not-run 四档 ⇒ `None` / `not_checked` / `not_checked_kind == status`），并加 `_result_reason`
    的 formal 分叉负控（formal + `exit_code=1` ⇒ 文案含「检查器跑了但没通过」且**不含**「崩溃」；
    `numeric` + `exit_code=3` ⇒ 仍说「未正常跑完」）。第二步才改 `_support.py` / `core.py`。
  - 理由：`44 J-06` 逐字；且 E-11 的新旧口径**语义相反**（旧：矛盾 ⇒ 拒收；新：矛盾 ⇒ 取最后并留痕），
    若先改代码，测试会红在一个「看起来像实现坏了」的位置，无法区分「判据生效」与「改错了」。
  - 成本：文件 **4**（`tests/test_agent_e.py`、`tests/test_agent_e_formal_path.py`、
    `agent_e/_support.py`、`agent_e/core.py`；都不在册）、落点 **6–8**、约 **60–90 行**
    （测试约 40–55；实现约 25–35：`_parse_conclusion` 三返回 +20、`_derive` +6、`core.py` 三态 +12、
    `_result_reason` 分叉 +6）。
    会红（改测试后、改代码前）：`tests/test_agent_e.py:314`（预期红）、
    `tests/test_agent_e_formal_path.py:258` / `:336` 的**补充断言**（预期红）；改代码后必须全绿。
    需复跑：`tests/test_agent_e.py:237/254/264/276`（四条正控，结论面不变）与 `:811` / `:830`
    （钉 `agent_e/__init__.py` 的 docstring）。
    快照与文档同步点：`agent_e/__init__.py:35-57` 与 `agent_e/_support.py:35-57` 的「唯一权威表述」
    两处同改（相似度 0.972，`46-06 §3.1`）；两个 golden 快照若含 formal 行的 `observations` 要重冻
    （`48-06 §2.1` 未核实）。
    真机影响：`p5-polish-20261001-234839` 五行按 §0.8 逐行预测 `protocol`；`p8g` 0002/0003/0004 与
    `p8e` 0002 改后落 `exit_code=1` / `checked_not_proved`；**45 条历史 formal 行的 `exit_code` 不回填**。
  - 风险与不可逆点：先改测试 ⇒ 中间态是「测试红、代码旧」的**有意红**，若中途有人看到红就回退测试，
    会把「判据」误当回归；`exit_code` 从「0 或 None」变成「0/1/None」是**列语义变更**：
    任何按「非 0 即崩溃」读历史列的人/脚本都会把 45 条 concluded 行读成崩溃（必须写进 `draft/44`）。
  - 兼容闸：`exit_code` 本来就是 `int | None`，`schema.py:1151` 的硬约束 3 只要求「非 0/None 且
    `result != inconclusive` ⇒ 拒」⇒ `exit_code=1` + `inconclusive` **合规**；
    新增 `check_outcome` / `not_checked_kind` / `protocol` 都是「带默认值新增」，
    历史 406 行按「缺键 = 未分类」读，**不许默认成 `ok`**。
  - 禁改区：`agent_e/*` 不在册。
- **方案 B：改设计迁就测试（保住「多行即拒」与旧的 `exit_code` 折叠）**
  - 做法：E-11 只新增 `protocol` 键（`missing` / `bad_json` / `invalid_result` / `multi_line`），
    **不改**「多于一行即拒」；E-12 只新增 `check_outcome`，**不动** `exit_code`
    （继续 `0 if verified else None`），`_result_reason` 也就不需要 formal 分叉。
  - 理由：既有两个判据（`tests/test_agent_e.py:314-315`、
    `tests/test_agent_e_formal_path.py:258` / `:336`）都是「实测过的保守口径」，不改它们就没有中间态红；
    `check_outcome` 三值已经能把「查了没通过」与「没查成」分开，`exit_code` 是否跟着分三态可以晚做。
  - 成本：文件 **2–3**（`agent_e/_support.py`、`agent_e/core.py`；都不在册）、落点 **3–4**、
    约 **35–45 行**（比 A 少：无 `_result_reason` 分叉、无既有测试改写）。
    会红：**无**（`tests/test_agent_e.py:303-315` 保持绿；`tests/test_agent_e_formal_path.py` 只**补**
    not-run 四档的 `not_checked_kind` 断言 ⇒ 新断言改前必红但要新写）。
    真机影响：`p5-polish` 的 0002 行继续 `multi_line` + 拒收（与今天逐字相同，`protocol` 是新增留痕）；
    `exit_code` 列**零变化** ⇒ 45 条 concluded 行的读数不变。
  - 风险与不可逆点：`exit_code` 列继续把「检查器没通过」与「超时/后端不可用」压成同一个 `None`
    ⇒ 未来真机一旦出现 `timeout`（今天 0 条，但那是 `formalgw` 的 `_CONCLUDED_STATUSES` 之外的档位、
    结构上会出现），历史列仍然分不开；且 `44 J-06` 已逐字裁定「E-12 改 `exit_code`（concluded⇒1 /
    没查成⇒None）+ 新增 `observations.check_outcome` 三值」⇒ 本方案等于**不执行 J-06 的前半**，
    需要显式改判（相当于新增一条裁定）。
  - 兼容闸：最保守；`exit_code` 与既有断言面零改动。
  - 禁改区：`agent_e/*` 不在册。
- **方案 C：分两批（先只加 `protocol` 键，再改解析语义 + E-12 三态）**
  - 做法：批一：只加 `PROTOCOL_READINGS` 与 `observations["protocol"]`，「多行即拒」的语义**不动**
    ⇒ **无需**改 `tests/test_agent_e.py:303`；批二：E-11 的「两行矛盾取最后 + `[conflict]`」与
    E-12 的三态 + `_result_reason` 分叉**同批**做（两者都要先改测试）。
  - 理由：E-11 的「加键」与「改解析语义」是两件不同量级的事 —— 前者不动任何既有断言，
    后者与 `tests/test_agent_e.py:303` 语义相反；分批能把「红」限制在批二，批一单独就能让
    `p5-polish` 五行第一次有机器可读的 `protocol`。
  - 成本：同 A 的落点面，拆成两批（每批各跑一次全量门）；批一约 **15–20 行**、批二约 **45–70 行**。
    会红：批一无；批二同 A（`:314` + 两条补充断言）。
    风险：两批之间的中间态里 `protocol` 能报 `multi_line` 却**永远不会**出现 `conflict` ⇒
    `tools/vocab_census.py` 的 R011（死取值）可能把 `conflict` 扫成新 dead vocab
    ⇒ 批一必须把 `conflict` 从词表里**先不加**，或登记为 reserved。
    快照与文档同步点：`protocol` 词表被改两次（批一 5 值、批二 6 值），每次都是一次口径变更登记
    （`48-06 §3.1`：R011 会扫它，且 `_parse_conclusion` 是唯一产出点）。
  - 风险与不可逆点：受控词表分批改 ⇒ 两次登记、两次「死取值」风险窗口；其余同 A。
  - 兼容闸：批一的加键是纯增量（`48-06 §3.4` 的「不许默认成 `ok`」守着）；批二才是语义变更。
  - 禁改区：`agent_e/*` 不在册。
- **不裁的默认后果**：`tests/test_agent_e.py:314-315` 与 `_support.py:392-397` 的冲突继续存在
  ⇒ E-11 无法施工（`46-06 §9` 第 ② 步卡住），而它是 R-01（第 ③ 步）的前置（`48 总 C8`）；
  E-12 未裁则 `agent_e/core.py:402` 继续把 concluded 与 not-run 折成同一个 `None`，
  `observations` 里继续没有 `check_outcome`（`48-06 §0.2`：两个 `experiments` 表里 `protocol` 与
  `check_outcome` 各 0 行）。
- **取舍点**：分歧在「既有的两个保守判据（多行即拒、`exit_code` 折叠）算不算必须保住的契约」，
  以及「E-11 的加键与改语义要不要拆成两批（省一次中间态，但受控词表要改两次）」。

---

### 决策 9 — R-01 的迁移范围

- **现状与证据**：
  - 真机（§0.3）：`role=E, action=run_experiment, status=failed` 共 **80** 次 / 21 个工作区，两类：
    **52 次 = 6643.0 s**（32「穷举类必须给 certificate」+ 17「certificate 必须含 kind」+
    2「`for_question_id` 形态」+ 1「有 certificate 就必须给 `search_bound`」）；
    **28 次** `ExperimentError: name / imports 只对 method='formal' 有效` = **0.0 s** `[本次复算]`。
  - 分钟级靶子：`p6m` **4205.0 s** / `p6i` **1802.0 s** / `p6h` **602.0 s**（`p6o` 6 次合计只有 3.0 s，
    这正是 `48-06 §0.3` 对 `46-06 §1.6` 点名的更正）`[本次复算]`。
  - 28 次那批的判据**已经在起子进程之前**：`agent_e/run_experiment.py:84-89`（certificate / search_bound
    只对穷举类有效）与 `:90-95`（`name`/`imports` 只对 `formal` 有效）`[本次确认]`。
  - 52 次那批的判据在 schema：`schema.py:1135-1149`（`search_like` 与 certificate 三判据）与
    `:1186`（`require_id(self.for_question_id, "for_question_id")`）`[48-06 §1.1 给的锚点]`；
    E 侧的位置约束：必须在 `:98`（`path = self._resolve(script_path)`）与 `:109`（formal 分流）
    **之前** `[本次确认 `:97-100` 与 `:108-109`]`。
  - `48-06 §1.1` 边界①逐字：**不许**把 `run_experiment.py:84-95` 那两条更严判据搬进共享纯函数 ——
    那会给 `numeric` 新增两条 schema 级拒收，等于**收紧 schema 契约**
    （`48 总 §0` 硬约束 2：只允许「放宽必填」与「带默认值新增」）`[来源]`。
  - `schema.py` 在 FC-27 **双类**禁改区（`[category: schema-migration]` + `[category: eval-criteria]`）
    `[本次确认：`AGENTS.md` 清单逐条]`；`agent_e/*` 不在册（`47 §3-C2`）。
  - 既有判据不替它变绿：`tests/test_agent_e.py:746`
    `test_exhaustive_search_requires_a_certificate_and_a_bound` 只直调
    `S.Experiment(**base).validate()`（`:757` / `:761`），**不经过 `run_experiment`**
    ⇒ R-01 必须**新增**「拒绝发生在起子进程之前」的用例 `[48-06 §1.1]`。
- **方案 A：只固化/登记「参数门」那一类（28 次 / 0 秒那批）**
  - 做法：把 `run_experiment.py:84-95` 的两条更严判据的**位置与文案**统一到一处（不改判据、不改顺序），
    并把 28 次读作「参数门有效」的**正面读数**登记进 `draft/44 J-04`；**不动 `schema.py`**。
  - 理由：这 28 次已经零算力，它们的价值是**读数**（证明参数门在起作用）；`44 J-04` 的收益面是
    「110.7 分钟那一批」，与这 28 次无关。
  - 成本：文件 **1–2**、落点 **1–2**、约 **10–20 行**（纯搬运，判据字面不变）。
    会红：无（`tests/test_agent_e.py:746` 走 `validate()` 面；本次未核实是否还有别的用例钉
    `run_experiment` 的这两条文案，`[判断类]`）。
    快照与文档同步点：`draft/44 J-04` 回填「28 次读作参数门有效」。
    真机影响：**0 算力**（这 28 次的 reason 行会因文案变动而变，但状态与耗时不变）⇒ 主要产出是读数。
  - 风险与不可逆点：本方案**不解决** 6643 s 的浪费；且若把「28 次」写成 J-04 的收益，会重犯
    `46-06` 的原读数错误（`48-06 §0.3` 已更正：分钟级真靶子是 `p6m`/`p6i`/`p6h`）。
  - 兼容闸：判据字面不变；`tests/test_agent_e.py:746-761` 走 `validate()` 面不受影响。
  - 禁改区：`agent_e/run_experiment.py` 不在册；**不碰 `schema.py`**。
- **方案 B：连子进程后校验一起前移（52 次 / 6643 s 那批）**
  - 做法：`schema.py` 抽 `experiment_param_problems(method, certificate, search_bound, for_question_id)`
    纯函数（**只含四条**：穷举类缺 certificate、certificate 非对象或缺 `kind`、有 certificate 无
    `search_bound`、`for_question_id` 形态），`Experiment.validate` 改为转调它（逐条顺序不变 ⇒
    报错仍是第一条）；`run_experiment.py` 在 `:95` 之后、`:98` 与 `:109` **之前**调用它，
    命中即抛 `ExperimentError`（不落库、不起子进程）。
  - 理由：这是 R-01 的本体；真机收益 6643.0 s（其中 `p6m`/`p6i`/`p6h` 共 6609.0 s），
    而 52 次的失败原因**全部**是「参数不合法」，与算力无关 ⇒ 前移不改变任何一次调用的成败，
    只改变它花不花 4205 秒。
  - 成本：文件 **2**（`schema.py` **禁改区**、`agent_e/run_experiment.py` 不在册）、落点 **3–4**、
    约 **35–45 行**（`schema` 纯函数 ~25 + `validate` 转调 ~5 + E 侧插入 ~6）。
    会红：本次未找到会因 R-01 变红的既有用例（`48-06 §1.1`：全 `tests/` 里 `match="certificate"` 只有
    `tests/test_agent_e.py:757`，走 `validate()` 直调）；**但** `validate` 改成转调纯函数后必须复跑
    `tests/test_agent_e.py:364-436` 一组 schema 负控与全部 `tests/test_schema_*`。
    快照与文档同步点：`grep -rn "必须给出 certificate" tests/ docs/` 先跑
    （`48-06 §1.1` 未核实有无 golden 逐字引用）；`draft/44 J-04` 回填分界。
    真机影响：`p8e`/`p8f`/`p8g` 各 4 次 failed 改后**仍 failed**，但 `started_at == ended_at`，
    且 `tasks.error` 首句从 `ValueError: method='exhaustive_search'…必须给出 certificate` 变成
    `ExperimentError: E.run_experiment 在起子进程之前拒绝了这次调用：…`；分钟级另看
    `p6m` / `p6i` / `p6h`（**比原因行，不比状态词**，`44 J-20`）。
  - 风险与不可逆点：`schema.py` 是双类禁改区 ⇒ 需 2 名人审，**不许自签**（`48 总 §6`：不许用
    `--baseline` 把「登记」写成「批准」）；判据搬运时**顺序不能变**（`validate` 报错要仍是第一条），
    否则历史报错文案会整体位移；`certificate={}` **不许**规范化成 `None`
    （`schema.py:1136` 与 `:1142` 的两种文案是分开的：「必须给出」vs「必须含 kind」）。
  - 兼容闸：只搬字面、不改判据、不改顺序 ⇒ 「放宽必填」与「带默认值新增」两条硬约束都不触碰；
    `schema.py:1151` 的硬约束 3（`exit_code`）不动。
  - 禁改区：`schema.py` **在册**（`schema-migration` + `eval-criteria`）⇒ 报备 + 2 名 reviewer；
    `run_experiment.py` 不在册。
- **方案 C：两段都做，但分两批（先 52 次那批，再 28 次那批的搬运与读数）**
  - 做法：批一 = 方案 B（`schema` 纯函数 + 调用点前移 + 禁改区报备）；批二 = 方案 A 的搬运与读数登记
    （把 `:84-95` 两条更严判据统一到纯函数**之外**的调用面，判据本身仍不进共享函数）。
  - 理由：两批的禁改区属性不同（批一要 2 名人审、批二不动禁改区）；分批能让批二在人工审批等待期内
    **独立**落地，而批二不改判据 ⇒ 风险面小。
  - 成本：B 的成本 + A 的成本；两批各跑一次全量门。
    会红/复跑：批二必须复跑 `tests/test_agent_e.py` 全量（两条文案搬运）。
    真机影响：批一即可拿到 6643.0 s 的收益；批二只改文案与读数。
  - 风险与不可逆点：分批两次动 `run_experiment.py` 的同一段（`:84-98`）⇒ 行号漂移两次，
    批二再动同一段时要重新核对锚点；`48 总 C8`（R-01 必须先于/同批于调用点迁移）在批一已满足。
  - 兼容闸：同 B。
  - 禁改区：同 B（批一要审批）。
- **不裁的默认后果**：`schema.Experiment.validate` 的四条判据继续在**子进程跑完之后**才生效 ⇒
  真机 52 次失败继续各花掉一次完整实验的时间（合计 **6643.0 s ≈ 110.7 分钟**），`p6m` 的 6 次继续
  各花约 700 s；`44 J-04` 的收益面继续挂空，而它是 `48 总 §3` 硬约束 `C8` 的一端。
- **取舍点**：分歧在「值不值得为 110.7 分钟去碰**双类**禁改区的 `schema.py`（并等 2 名人审）」，
  以及「28 次那批该当成收益，还是当成既有参数门的正面读数」。

---

### 决策 10 — D-2（B 的租约不一致）的修法

- **现状与证据**：
  - `agent_b/core.py:96-99` 逐字 `for r in cands: if r.get("claimed_by") and not lease_expired(r.get("lease_until")): skipped_lease_active += 1; continue`
    ⇒ 跳过判据**同时要求 `claimed_by` 非空** `[本次确认]`。
  - 写入面：`agent_b/run_once.py:83-90`（抽取失败支）写 `row["claimed_by"] = None; row["lease_until"] = None`；
    同族的 `:48-59`（不可读，已置 `processed=True`）与 `:64-76`（回退抽取器拒抽，`:70` 注释逐字
    「刻意不置 `processed`：接线 LLM 之后这一行还要被重新领到」）本次逐行确认了形状；
    成功路径 `:303-309` 继续清空租约 `[本次确认到 `:48-76`；`:83-90` 为 `48-07 §2.1` 逐字]`。
  - 同族判据：`agent_b/core.py:260-262` `_claim_reprocess` 同一形状 `[本次确认]`；
    `agent_b/core.py:48-49`（`lease_seconds` 缺省 900 / `max_attempts` 缺省 3）**禁改**
    `[48-07 §1.1]`。
  - 对照实现：`agent_a/core.py:42-47` 的注释逐字「若判据额外要求 `claimed_by` 非空，这条租约就写了
    等于没写」`[48-07 §0.1；本次未逐行打开]`。
  - 真机探针（`48-07 §0.1` 逐字）：`after run_once #1..#4` 的 `claimed_by=None lease_until=None`，
    `mine_attempts` 从 1 涨到 3，第 4 次才 `skipped_reason='no_claimable_literature'` `[来源]`。
  - 会红：`tests/test_agent_b.py:182` 逐字
    `assert row["claimed_by"] is None and row["lease_until"] is None, "必须释放租约以便重试"`；
    `:183` `assert row["mine_attempts"] == 1`；`:163` 的 `assert rows["0000"]["claimed_by"] is None`
    （不可读支）`[本次确认]`。
  - `48-07 §1/§2` 的判定：写入面（`run_once.py`）先落、判据面（`core.py:97`）后落，**同批**。
- **方案 A：`core.py:97` 与 `run_once.py:85-90` 对齐租约（判据只看租约 + 写退避租约）**
  - 做法：`:97` 改成唯一判据 `if not lease_expired(r.get("lease_until"))`，并把「别人持着」与
    「自己的退避租约」分两档（新增 `skipped_lease_backoff` 与 `skipped_reason="pending_literature_all_in_backoff"`）；
    `run_once.py:83-90`（抽取失败）与 `:64-76`（`no_llm_extractor`）把 `lease_until = None` 改成
    `make_lease(self.retry_backoff_seconds)`（`__init__` 新增该配置、缺省 60）；
    `:48-59`（不可读支）**不改**；`:303-309`（成功清空租约）不改；`_claim_reprocess()`（`:260-262`）同一改法。
  - 理由：这是「判据与写入形状同源」的唯一修法；`agent_a/core.py:42-47` 的注释就是这条判据形态的现成依据；
    不退避会让「接口坏的一行」被同一轮无限重领（真机探针 4 次）。
  - 成本：文件 **3**（`agent_b/core.py`、`agent_b/run_once.py`、`agent_b/_support.py` 的数据类；
    都不在册）、落点 **6–8**、约 **60–90 行**（`core.py` ~35：判据 1 行 + 分档 ~8 + 四种 `skipped_reason`
    ~10 + `_claim_reprocess` ~8；`run_once.py` ~6；`_support.py` ~4）。
    会红：`tests/test_agent_b.py:182` **必须先跑、必须红**（`lease_until` 从 `None` 变非空），
    随后改成 `is not None`；`:183` 保持；`:163`（不可读支）**不许红**；
    `tests/test_core_audit_abc_cli.py:561/566/589`（`_add_leased_literature` 造
    `claimed_by="agent-B-other"` / `mine_attempts=3` 两档）必须仍绿（改动前后分档不变）
    `[48-07 §1.1]`。
    快照与文档同步点：`BClaimOutcome` / `BRunResult` 各 +1 字段 ⇒ 若 `BRunResult.to_dict()` 进 `res.task`
    一类落点有快照要重冻（`48-07 §汇总.2` 未核实）；`retry_backoff_seconds` 是新构造期配置键 ⇒
    若 `config` 有逐键清单（提示词面或 `host.py` 的装配置）要同步登记。
    真机影响：`p5-review-t14` 一类 `last_mine_error="no_llm_extractor"` 的工作区重跑 `B.run_once`
    ⇒ `mine_attempts` 不再跳档。
  - 风险与不可逆点：退避期间那一行**领不到**（今天是能领到的、只是领了也白领）⇒ 若退避秒数配大了，
    表现是「B 静默地什么都不做」；写入面与判据面若**不同批**，中间态是「写入面写退避租约、判据仍旧只看
    `claimed_by`」⇒ 租约**仍然**写了等于没写（正是 `agent_a/core.py:42-47` 警告的形态）
    ⇒ 两半必须同批且写入面先落。
  - 兼容闸：`lease_seconds` / `max_attempts` 缺省不动；不给 `literature` 加「退避次数」字段
    （`schema.py` 禁改区）；`_claim` 与 `_claim_reprocess` 不合并（准入判据不同）；
    不动 `_is_fallback_extractor`；不改「不可读 ⇒ 置 `processed`」的处置。
  - 禁改区：`agent_b/*` 不在 FC-27 清单（`47 §3-C2`）；`schema.py` 不碰。
- **方案 B：只在 `_claim` 加读数（不改写入面、不改判据）**
  - 做法：在 `core.py:97` 的跳过分支里把「`claimed_by` 为空但租约未过期」单独计数
    （`skipped_lease_backoff`）并写进 `skipped_reason`；判据**不改**（仍然 `claimed_by` 非空才跳过），
    `run_once.py` 一字不动。
  - 理由：先把「自己的退避租约被忽略」这件事**变成可见的读数**，再决定要不要改语义；
    真机探针给出的 `mine_attempts` 跳档就是这一档的症状。
  - 成本：文件 **2**（`agent_b/core.py`、`agent_b/_support.py`；都不在册）、落点 **2–3**、约 **15–25 行**。
    会红：**无**（判据不变 ⇒ `tests/test_agent_b.py:182` 保持绿）。
    真机影响：新增的 `skipped_lease_backoff` 在**没有写入面**的前提下**恒为 0**
    （今天没有任何代码写「`claimed_by=None` + 未来租约」这种形状）⇒ 这个读数是一个
    「判据看起来在、实则没有输入」的形态（`46-06 §5.6` 风险 C 的同族）。
  - 风险与不可逆点：本方案等于把 `48-07 §1` 要修的错**登记**下来而不修；且「读数恒 0」在后续可能被
    当作「没问题」的证据。
  - 兼容闸：零语义变更。
  - 禁改区：同 A。
- **方案 C：改 `tests/test_agent_b.py:182`（把「必须释放租约」这条断言改掉）**
  - 做法：不动 `src/`，只把 `:182` 的逐字断言改成不再要求 `lease_until is None`
    （例如只断言 `claimed_by is None`）。
  - 理由：断言原文「必须释放租约以便重试」表达的是一种**设计意图**（失败要能重试），而 D-2 的问题在于
    「释放成 `None` 让租约写了等于没写」⇒ 断言与实现之间确实有一处该对齐。
  - 成本：文件 **1**（`tests/`）、落点 **1**、约 **1–3 行**。
    会红：这条断言改绿之后，`src/` 的错**一条判据都没有了** —— 今天它是唯一逐字钉住「失败分支的租约形状」
    的地方（`run_once.py:83-90` 的 `lease_until = None` 靠它守着）。
    真机影响：0（行为未改）。
  - 风险与不可逆点：这是**删判据保现状**的形态：测试改了、行为没改，真机探针里的无限重领**照旧**；
    且它与 `44 J-02` 同族的口径相冲（`48-07 §4.1` 对 C 的两条反判据逐字要求「必须改写那两条反判据」，
    不许靠删测试绕过）—— 本方案的取舍正是「这一条算不算那类反判据」。
  - 兼容闸：不涉及。
  - 禁改区：无。
- **不裁的默认后果**：`agent_b/core.py:97` 与 `run_once.py:83-90` 的形状不一致继续存在 ⇒
  失败分支写的「退避租约」继续被 `claimed_by` 那一半判据忽略，`mine_attempts` 继续按探针那样在 4 次
  `run_once` 里从 1 跳到 3；`no_llm_extractor` 那一支（`:64-76` 刻意不置 `processed`）在接线 LLM 之后
  继续被无限重领（`agent_b/core.py:43-44` 的注释逐字预告了这件事）；`48-07 §汇总.3` 的「批 1」无法开工。
- **取舍点**：分歧在「先改判据与写入面（要动三文件、会红一条既有断言）还是先把这一档变成可见读数
  （读数在写入面改之前恒 0）」，以及「那条逐字的 `lease_until is None` 断言是必须改写的反判据、
  还是可以不动的正控」。

---

### 决策 11 — S-01 的落盘面

- **现状与证据**：
  - `agent_c/_support.py:256-324` 的 `AnalysisReport.persist()` 是**唯一写入口**：四道硬校验
    （`:284` kind ∈ `REPORT_KINDS`、`:289` markdown 非空、`:291` summary 非空、
    `:293-298` payload 可 JSON 序列化）+ `tx` 内 `alloc_id("report")` + 写文件 + 登记行；
    `:265-276` 的 docstring 逐字给出「先写文件再写登记行」的顺序理由 `[本次确认]`。
  - 全 `src/` 的 `.persist()` 生产调用点：只有 `cli.py:481` 与 `agent_c/__main__.py:382/393/398`；
    **conductor 路径上一次都没调** `[本次确认，全 `src/` grep]`。
  - `AgentC._finish_report` **不存在**（`agent_c/` 内 grep 0 命中）`[本次确认]`。
  - 收口点是 `agent_c/core.py:89-103` 的 `_report(...)`（唯一构造 `AnalysisReport` 的地方；
    `:102` 挂 `rep._store`）；四个动作文件都 `return self._report(...)`：
    `hottest.py:37/108`、`cold.py:31/154`、`paths.py:26/37/293`、`gaps.py:301`；
    `handle.py:19/36` 也走 `_report` 但 kind = `"unknown"` `[本次确认，grep `_report(`]`。
  - **另有 5 个动作不走 `_report`**：`contradictions`（`core.py:1091-1094` 返回 dict）、
    `structural_duplicates`（`core.py:1106` 返回 dict）、`neighbors` / `relations_between`
    （本次未定位返回点，`[判断类]`）、`check_conflict`（纯函数，`core.py:1124-1127`）
    `[本次确认到所列行]`。
  - **工具面把 dataclass 转掉了**：走 `_report` 的四个动作在注册时是
    `lambda …: self.hottest(...).to_dict()`（`core.py:969/992/1004/1016`）⇒ conductor 只拿到 dict、
    拿不到 `AnalysisReport` 对象（也就没有 `_store` 可 `persist()`）`[本次确认]`。
  - 真机（§0.3）：根1 C 产物 37 份、`payload_keys` 空 26（hottest 11 / gaps 12 / cold 2 / paths 1）、
    非空 11；根2 22 份、空 21、非空 1；两根 `analysis_reports` **全 0 行** `[本次复算]`。
  - 两条既有反判据（`44 J-02` 逐字要求「**必须改写那两条反判据**」，不许靠删测试绕过）：
    `tests/test_agent_c_service.py:641` 逐字
    `assert kn.rows("analysis_reports") == [], "gaps 不落报告表（要落盘必须显式 persist）"`；
    `tests/test_agent_c.py:522`（在 `test_persist_rejects_kind_outside_the_controlled_vocabulary` 内，
    `assert demo.rows("analysis_reports") == []`）`[本次确认]`。
  - 另需同批处置：`tests/test_core_audit_abc_cli.py:793` 逐字
    `assert len(st.rows("analysis_reports")) == 3, "它自己的产出（analysis_reports）应当照常登记"`
    （该用例显式调三次 `.persist()`，`:783-785`）⇒ 自动落盘后计数会变；
    `:425` 的 `assert st.rows("analysis_reports") == []`（`kind="unknown"` 不落盘）**不许红** `[48-07 §4.1/§5.1]`；
    `tests/test_agent_c.py:485-503`（`:486` 的 docstring 逐字「persist 必须双份落盘」、`:494` 读行）
    是显式调 `.persist()` 的正控 `[本次确认到 `:494`]`。
  - 权限面已登记：`capabilities.py:1137` `READ_ONLY_WRITE_EXCEPTIONS["C"]` 含 `analysis_reports`
    ⇒ `48-07 §6.1` 判定权限面**不需要动**（`assert_capabilities` 的 [6] 条先减已登记例外再判）
    `[本次确认到 `:1137`；断言段为 `48-07 §6.1`]`。
  - `48-07 §汇总.4` 分界①：`analysis_reports` 从 S-01 落地那一趟起才有产出方，且只覆盖 4 个 kind
    （`schema.py:442`，禁改区）`[来源]`。
- **方案 A：只在 conductor 路径调 `C.persist()`**
  - 做法：在编排层（`conductor.py`，或 conductor 调 C 动作的那一处）拿到 C 动作的返回值后调 `persist()`；
    `agent_c/*` 与工具面**一字不改**。
  - 理由：`44 J-02` 逐字说「C **已有 `persist()`**（`agent_c/__init__.py:53`、`__main__.py:381-398`），
    缺的是**在 conductor 路径上调用**」⇒ 这是 J-02 的字面落点；不改 C 的动作面 ⇒ 不动 `specs/c.py`。
  - 成本：文件 **1–2**（`conductor.py` 不在册；若同时改 `tools/conductor_tools.py` 的视图则 2）、
    落点 **1–2**、约 **20–40 行**。
    **结构性缺口**：工具面在 `agent_c/core.py:969/992/1004/1016` 就把 `AnalysisReport` `.to_dict()` 掉
    ⇒ conductor 手上没有可 `persist()` 的对象（也没有 `_store`）：要么把 `to_dict()` 的输出重新构造成
    `AnalysisReport`（那会在 conductor 里长第二份「报告对象」的构造口径，而 `_support.py:206-211`
    的 docstring 逐字警告「表里的行必须是 `schema.AnalysisReport`，两回事」），要么把工具面改成返回对象
    （那会改 `returns` 串 ⇒ 重冻 `tests/golden/tool_surface_snapshot.json`）。
    会红：`tests/test_agent_c_service.py:641` 与 `tests/test_agent_c.py:522`（两条反判据，`44 J-02`
    要求改写）在 conductor 路径上**不一定**会红 —— 它们走 `_report` / 服务路径，取决于本方案是否只挂在
    conductor 一处。
    快照与文档同步点：`closing.py:165`（`:823` 是取值分支）的 `analysis_report_rows` 档第一次有读数
    （`48-07 §汇总.4` 分界①）。
    真机影响：`analysis_reports` 首次非 0，但**只在 conductor 派单的那条路径上**
    （CLI 直调 `C.gaps` 仍然不落盘，而 `agent_c/__main__.py:398` 又显式调 `persist()`）
    ⇒ 同一个动作经不同入口行为不同。
  - 风险与不可逆点：**落盘面绑在入口上** —— 同一个 `C.gaps`，conductor 派单落盘、CLI 直调不落盘、
    `python -m agentflow.agent_c` 落盘；而「`analysis_reports` 有没有行」是 `closing` 的读数档
    ⇒ 读数会随入口而变。且要在 conductor 里补，就必须重新构造对象或改工具面返回值 ——
    两件都不是「只在 conductor 加一次调用」。
  - 兼容闸：`WRITE_SETS["C"]` / `READ_ONLY_WRITE_EXCEPTIONS["C"]` 已登记 `analysis_reports`
    ⇒ 权限面不用动；`graph.gaps` 的 `side_effect="read"` 不许改成 `write_local`
    （`capabilities.py:1086-1099`；改它会让 `ToolRegistry.for_role` 把 `graph.gaps` 从 C 的工具面里滤掉）。
  - 禁改区：`specs/c.py`（auth-audit）**不许动**；`conductor.py` 不在册；`capabilities.py` 在册
    （本方案不动它）。
- **方案 B：四个动作各自 `_report()` 收口（新增 `AgentC._finish_report`）**
  - 做法：新增 `AgentC._finish_report(rep)`（`rep.ok and rep.kind in S.REPORT_KINDS and
    rep.markdown.strip()` 才 `persist()`；异常不抛给调用方、记进 `rep.warnings`，保留 `ok=False` + `error`）；
    在 `_report()`（`agent_c/core.py:89-103`）末尾按开关调用；四个动作文件 **0 行改动**；
    开关走 `host.py` / `config`（**不改** `specs/c.py`）。
  - 理由：`_report` 是唯一构造 `AnalysisReport` 的地方（四个动作文件都只 `return self._report(...)`）
    ⇒ 收口在这里才能保证「落盘的是真对象、带 `_store`」，不必在 conductor 里重构对象；
    `handle` 的 `kind="unknown"` 天然被 `REPORT_KINDS` 挡住（`_support.py:284`）。
  - 成本：文件 **4–5**（`agent_c/_support.py`、`agent_c/core.py`、`host.py`、两个测试文件；
    都不在册）+ `agent_c/__init__.py` 的 re-export、落点 **4–5**、约 **70–110 行**
    （`_finish_report` ~15 + `to_task_payload` ~5 + `_report` 收口 ~6 + `to_dict()` 露
    `report_id`/`markdown_path` ~10 + `host.py` 开关 ~10 + 测试改写 ~25–40）。
    会红（`44 J-02` 要求改写）：`tests/test_agent_c_service.py:641` **必须先跑、必须红**，然后按新语义反向；
    `tests/test_agent_c.py:522` **必须先跑、必须红**，但**改后必须仍绿**（三条非法路径都不该落盘
    ⇒ 期望不改，改的是它前面的前提）；`tests/test_core_audit_abc_cli.py:793`（3 → 变）必须同批改；
    `tests/test_agent_c.py:485-503`（显式调 `.persist()`，`len(rows) == 1`）⇒ 要么显式关自动落盘、
    要么改成按落盘次数计（**不许删**）；`tests/test_core_audit_abc_cli.py:425` 不许红。
    快照与文档同步点：`returns` 串若改要重冻 `tests/test_tool_surface_snapshot.py` +
    `tests/golden/tool_surface_snapshot.json`；`closing.py` 的 `analysis_report_rows` 首次有读数（分界①）；
    `tests/test_agent_spec_reconciliation.py` 的两层动作表对账。
    真机影响：`analysis_reports` 首次非 0，四个 kind（hottest/paths/cold/gaps）各落一行 + 一份
    `reports/<rid>-<kind>.md`；`contradictions`/`neighbors`/`relations_between`/`structural_duplicates`/
    `handle` **仍然不落**（它们不走 `_report`、或 kind = `unknown`）。
  - 风险与不可逆点：**行为变更面覆盖所有入口**（CLI 直调也落盘）⇒ `tests/test_agent_c.py:485-503`
    一类显式调 `persist()` 的用例会**双写**（自动 + 显式）；`auto_persist` 缺省 `True` 还会让
    `pipeline._persist_report` 的旧路径重复（`48-07 §5.1` 因此选路由②：在 `host.py` / 配置里打开，
    而非缺省 `True`）；开关缺省值一旦定错，真机 `analysis_reports` 会突然多出一批行（不可逆的口径变更）。
  - 兼容闸：`_finish_report` 只在「`ok` 且 kind 合法 且 markdown 非空」时落 ⇒ `handle` 与 `ok=False`
    的档位不会进表；`WRITE_SETS["C"]` 不动；`graph.gaps` 的 `side_effect` 不动。
  - 禁改区：`specs/c.py`（auth-audit）**不许动** ⇒ 开关不能放 `specs/c.py` 的构造配置里，
    只能放 `host.py` / `config`；`schema.py:442` 不许动。
- **方案 C：落盘面挂起，先做「不改」条目 `graph_tools.py` 与摘要截断 `_payload_view`**
  - 做法：本批只落 `48-07 §7`（`tools/graph_tools.py` **不改**，作为钉住「不许在这里落盘」的显式条目）
    与 `§8`（`conductor._payload_view` 让 dataclass 返回值也有键集），落盘面挂起。
  - 理由：`44 J-10` 的 `payload_keys` 恒空是**结构性**的（`conductor.py:1213` 的
    `isinstance(payload, Mapping)` 为假，`[本次确认]`；`:1200-1214` 是 `_write_task_digest` 全体），
    它可以在不落盘的前提下单独修；而落盘面要动两条反判据 +
    一条计数断言，代价与风险都更大。
  - 成本：文件 **2–3**（`conductor.py`、`tools/conductor_tools.py`、测试；都不在册）、落点 **2–3**、
    约 **40–60 行**。
    会红/需重冻：`tests/golden/tool_surface_snapshot.json`（`conductor.summon` 的 `returns` 串逐字列了
    `payload_preview`/`payload_bytes`/`payload_keys`/`payload_truncated` ⇒ 改字段集必须重冻）、
    `tests/test_conductor.py`、`tests/test_core_audit_efgh.py`。
    真机影响：`p6j-research-from-zero` 派一次 `C.gaps` 后 `payload_keys` 含 `candidate_gaps`/`verdict`；
    历史 26 份（根1）/ 21 份（根2）文件**不会**被改写 ⇒「两根 `payload_keys` 恒空」这条读数从改后那一趟起
    **分裂**，必须写清分界点；`analysis_reports` 继续 0 行。
  - 风险与不可逆点：挂起落盘面 ⇒ `analysis_reports` 继续 0 行，D 继续没有可吸收的报告
    （`D.ingest.enabled_kinds` 的 4 个 kind 没有输入，见决策 6）；`44 J-02` 继续挂空，
    而它是 `48-07 §汇总.3` 的「批 3」入口。
  - 兼容闸：`payload_keys` 的语义边界不许变（「不是对象就没有键集」）；`payload_preview` 的长度 2000
    不许变（`specs/m.py:69` 的读法建立在它上面，`48-07 §8.1`）。
  - 禁改区：`tasks` 表在 FC-27 禁改区（`payload` 本来就不进表）；`specs/m.py` 在册；
    `tools/graph_tools.py` 不在册（`48-07 §0.7` 的行号漂移只影响锚点，不影响结论）。
- **不裁的默认后果**：两根 `analysis_reports` 继续 **0 行**（文件 57 / 22 份存在）⇒
  `closing.py:165` 的 `analysis_report_rows` 档继续没有读数、D 的 `ingest` 继续没有报告可吸收、
  `44 J-02` 继续挂空；`_report()` 继续只返回对象而调用方（工具面）`.to_dict()` 掉它，
  conductor 侧的 `payload_keys` 继续恒空（真机根1 26/37、根2 21/22）。
- **取舍点**：分歧在「落盘面绑在哪个入口（conductor 一处 vs 所有入口统一收口）」，
  以及「两条既有反判据（`tests/test_agent_c_service.py:641`、`tests/test_agent_c.py:522`）该按新语义
  反向，还是把落盘面收窄到不触碰它们」。

---

## §2 汇总表

| # | 决策点 | 方案数 | 主要落点 | 是否碰禁改区 | 会红的既有测试（行号） | 真机可证伪性 |
|---|---|---|---|---|---|---|
| 1 | R-03 引用口径 | 3 | `attackround.py:155-177`；`verify.py:51/54`；`doc_tools.py:319-324` | A 碰 `verify.py`（auth-audit，2 人审）；B/C 不碰 | `tests/test_attack_round.py:55/81`、`tests/test_invalidation_cascade.py:143` | 可（`p8f` 计划 0002 的 11 个 `lit:`） |
| 2 | `DEAD_END_REASONS` 加 `tool_failure` | 3 | `attackround.py:53-55`；`agent_f/core.py:397-409/410-425`；`step.py:254-265` | 否（`specs/f.py` 若镜像广告面则在册） | `tests/test_agent_f_inference.py:188`、`:202` | 可（6 条 `judge_failed` 靶子） |
| 3 | R-02 日志落盘 | 3 | `agent_e/_support.py:682-705`；`run_experiment.py:170-177` | 否（`store.py` **不动**，在册 + 反判据） | A 不红；B 红 `tests/test_agent_e_run_log.py:50`；C 需复跑 `:41-58` | 可（`p8c` 三份日志的 sha256 与 byte-identical） |
| 4 | S-07 改判方向 | 3 | `schema.py:442`；`specs/d.py:232-235`；`agent_d/write_report.py:38-45/407-410` | A/B 各碰 2–3 处在册文件；C 不碰 | A/B 未逐条定位（`tests/test_scheduler.py:828-839` 必复算）；C 无 | 部分（文件数 vs 表行数） |
| 5 | S-02/S-08/S-09 处置 | 3 | `agent_d/{consider,submit_gaps,research,assess}.py`、`_support.py`、`core.py`；B 另涉 `host.py:501-505`/`specs/d.py:167` | A/C 不碰；B 若走 `specs/d.py` 则 2 人审 | A：`tests/test_agent_d.py` 等必须全绿；B：装配面与快照族 | **不可**（根2 22 个工作区 0 行、D 未接 LLM） |
| 6 | `D.ingest.enabled_kinds` 是否扩 | 3 | `agent_d/core.py:66`、`ingest.py:66-67`；`schema.py:442`；`agent_c/{core,handle}.py` | A 否；B 碰 `schema.py`/`specs/c.py`/`specs/d.py`；C 否 | B：`tests/test_agent_c*.py`、`tests/test_closing*.py`、快照 | 部分（4 个 kind 的行在 S-01 落地后可证伪） |
| 7 | P-09 代价真源 | 3 | `agent_f/core.py:375-376/385-387`；`tokenmeter.py:250-256`；`conductor.py:1022-1031`；`tools/attack_tools.py:281-289` | 否（均不在册）；B 若动 `specs/m.py` 则在册 | A 无既有断言读四键；B：`tests/test_agent_prompts.py` 族；C：`tests/test_agent_f.py` 族（未逐行定位） | **不可**（76 个计划的 `cost` 只能看新增行） |
| 8 | E-11/E-12 冲突处置 | 3 | `agent_e/_support.py:374-416/682-705/706-709`；`agent_e/core.py:402`；`tests/test_agent_e.py:303-315` | 否（`agent_e/*` 不在册） | A：`tests/test_agent_e.py:314` + `tests/test_agent_e_formal_path.py:258/336`；B/C 无 | 可（`p5-polish` 五行 + `p8g`/`p8e` formal 行） |
| 9 | R-01 迁移范围 | 3 | `schema.py:1135-1149/1186`；`run_experiment.py:84-98` | B/C 碰 `schema.py`（双类，2 人审） | 本次未找到；必复跑 `tests/test_agent_e.py:364-436` 与 `tests/test_schema_*` | 可（原因行 + `started_at==ended_at`；`p6m`/`p6i`/`p6h`） |
| 10 | D-2 租约不一致 | 3 | `agent_b/core.py:96-99/260-262`；`run_once.py:83-90`；`_support.py` 数据类 | 否（`agent_b/*` 不在册） | `tests/test_agent_b.py:182` 必红（不改 `:163`） | 可（探针 + `mine_attempts` 不跳档） |
| 11 | S-01 落盘面 | 3 | `agent_c/_support.py:256-324`；`agent_c/core.py:89-103/969-1016`；`conductor.py:1200-1214` | A/B 不碰；C 动 `conductor.py`（不在册） | `tests/test_agent_c_service.py:641`、`tests/test_agent_c.py:522`、`tests/test_core_audit_abc_cli.py:793` | 可（`analysis_reports` 首次非 0） |

**成本量级速览**（估计行数，仅改动面，不含测试重冻的机械成本）：

```text
决策 1  R-03 引用口径        A ~6 行        B ~40-60 行    C ~50-75 行
决策 2  tool_failure 第八值   A ~8 行        B ~25 行       C ~35 行
决策 3  R-02 日志落盘         A ~5-7 行      B ~12-18 行    C ~10-15 行
决策 4  S-07 落点             A ~150-250 行  B ~60-120 行   C ~10 行（仅反向门）
决策 5  S-02/08/09            A ~120-200 行  B ~20-60 行装配 + 真机 token 成本  C 0 行
决策 6  enabled_kinds         A 0 行         B ~150-250 行  C ~30-60 行
决策 7  P-09 代价真源         A ~25-40 行    B ~10-30 行    C ~20-40 行（以删为主）
决策 8  E-11/E-12 顺序        A ~60-90 行    B ~35-45 行    C ~60-90 行（拆两批）
决策 9  R-01 迁移范围         A ~10-20 行    B ~35-45 行    C ~45-65 行（拆两批）
决策 10 D-2 租约              A ~60-90 行    B ~15-25 行    C ~1-3 行（仅改测试）
决策 11 S-01 落盘面           A ~20-40 行    B ~70-110 行   C ~40-60 行
```

**跨决策点的耦合**（用于判断「能不能分开拍」）：

1. 决策 8（E-11）与决策 9（R-01）：`48 总 §3` 硬约束 `C8` 要求 E-12/E-11 是 R-01 的前置
   （`46-06 §9` 第 ①② 步先于第 ③ 步）⇒ 决策 8 不定，决策 9 的批一无法开。
2. 决策 3（R-02）依赖决策 8 的第 ② 步完成（`46-06 §9` 第 ④ 步在 ② 之后）。
3. 决策 2（`tool_failure`）与决策 7（P-09）**同一族**：`DEAD_END_REASONS` 里
   `"超出本轮预算"` 这一格在方案 C（删四键）下会变成死取值 ⇒ 两条决策的「改词表」面重叠。
4. 决策 6（`enabled_kinds`）在 S-01（决策 11）落地前**没有输入**（`analysis_reports` 0 行）
   ⇒ 决策 11 挂起（方案 C）时，决策 6 的方案 A/B/C 都只能停留在文档层。
5. 决策 5（S-08 的 `trusted`）与决策 6 的方案 C（让 D 只吸收自己产的）方向一致：
   两者都在处理「D 自证」这条风险的边界。
6. 决策 10（D-2）与决策 5（S-03 的 A 侧自动消费）**不同批**（`48-07 §9` 末段），
   虽然都走 `run_once` 链，但两条队列不共享判据。
