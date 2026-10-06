# draft/46 施工级调查 01：`schema.py` / `store.py`（R-02 · R-05 · R-06 · F-01 · P-06 · P-07 · P-08 · E-09 · EE-06 · EE-07）

> 只读调查。除本文件外**未改动仓库任何文件**；未跑模型、未跑网络、未跑全量 pytest、未跑 Lean、未跑会写盘的 `rebuild`。
> 方法：`read` / `grep` / `glob` / `python -B -c`（只读统计与快照校验）。行号均为本次实测 `file:line`，原文引用逐字。
> 每文件七栏：现状 / 逐改动点（贴原文 + 伪码）/ 调用面 / 数据结构与历史数据影响 / 可行性与改动量 / 风险与验证 / 不做部分。
> 姊妹件：`draft/46-施工级调查-06-角色EF.md`（R-02「日志半」与 E 侧在校，本件只做 store/schema 半）。

## §0 实测基线（可复算）

**① 历史快照兼容基线（本任务硬要求的那一次实测）**

```
命令: python -B -c "…glob 两根 */data/*.json；逐份 schema.validate_table；分计 ValueError 与非 ValueError…"
agentflow/projects/*/data/*.json = 1029 个（counters.json 57）｜ D:\Incubator\projects\*/data/*.json = 375 个（counters 22）
落到 TABLES = 1322（17 表 × 79 工作区 − statements 缺 21 份）；非 TABLES：counters 79、research_request_ledger 3
通过 = 1322   失败(ValueError) = 0   逃逸(非 ValueError) = 0
```

对 `draft/41` §3.7 的 969 份基线：口径一致，本次样本更大（两根全量 1322）。

**② 三个候选改动的兼容性模拟（同进程改判据后重跑 1322 份，只读）**：`baseline PASS=1322 FAIL=0`；
A `claims[].status` 必填 ⇒ `PASS=1270 FAIL=52`（52 份 documents.json 红）；C `LIT_MATCH_STATUSES += ("none",)`
⇒ 1322/0（兼容 ≠ 可做，见 1.2-f）；E `Statement.grade` 必填 ⇒ `PASS=1289 FAIL=33`。

**③ 题库读数（两根合计）+ ④ R-02 真机直接证据（`p8c-fermat-shorter-proof`）**

```
statements 138：bits 非空 0；evidence_kind {cross_check:124, heuristic:8, proof:6}；origin {external_lit:125, own_result:13}
  quote_verified {None:111, False:18, True:9}；own_result 13 行 proof_text 全非空 ⇒ bits_from_row 现算等级 = conjecture 13/13
experiments 406：{numeric:302, formal:80, exhaustive_search:24}；formal 80 行 exit_code {None:45, 0:35}
documents 76 行 / claims 449 条：status 非空 0、allowed_use 非空 0；claims 键全集 18 个不含二者
relations 1772：quote_verified {True:1754, False:18}（无 None）｜ literature 1736：matched {"":1003, None:733}，三档各 0
R-02：台账 4 行 0000 formal([]) / 0001 formal([]) / 0002 exhaustive_search(["out/experiments/0002.log"]) / 0003 formal([])
  盘上 0000.log(534B 2046b2f0aa04aea8) 0001.log(534B e268de5b7f7a1cac) 0002.log(534B e268de5b7f7a1cac)
  ⇒ 0001.log 与 0002.log 逐字节相同；0001.log 无任何台账行引用，而台账 0001 是 formal
  全档案：406 行 / 226 个 log；221 行引用日志、185 行 artifact_paths 为空；孤日志 3 工作区 5 个（p5-review-t1:0000、p6e:0006,0008、p8c:0000,0001）
```

---

## §1 `src/agentflow/schema.py`（2791 行）

### 1.1 现状

| 符号 | 位置 | 关系 |
|---|---|---|
| `SCHEMA_VERSION = 1` | `schema.py:18` | 磁盘契约；`src/agentflow/__init__.py:19` 有副本 |
| `LIT_MATCH_STATUSES` | `:122`（说明 `:103-121`） | E-09 |
| `EVIDENCE_KINDS` | `:876` | EE-07 / F-01 |
| `STATEMENT_STATUSES` / `_UNUSABLE_` | `:959` / `:963` | F-01 |
| `class Document` / `.validate` | `:1326` / `:1359` | P-07 · EE-06（claims 段 `:1387-1451`） |
| `class Statement` / `.validate` | `:1544` / `:1626` | F-01 · P-06 · EE-07（bits 段 `:1678-1696`） |
| `class Relation` / `.validate` | `:386` / `:413` | R-05（内联件 `:418`） |
| `class Concept` / `.validate` | `:336` / `:360` | R-05（内联件 `:374`） |
| `ARRAY_FIELD_KINDS` | `:2361` | R-05（17 个 set 字段） |
| `check_array_invariants` | `:2411`（问题行 `:2432`） | R-05 |
| `TABLES` | `:2439` | 17 表；改动会进提示词 |
| `validate_table` / `row_from_dict` | `:2696` / `:2746` | R-05 的抛出点 |

**位置**：`src/` 里 60 处 `from . import schema as S`；主要消费者 `store.py:50`、`verify.py:29`、`closing.py`、
`gates.py`、`interactions.py`、`conductor.py:59`、`capabilities.py:43`、`tools/*`、`specs/*`、`agent_*/\_support.py`。
它只 import 标准库 + 一处**惰性** `from .store import MAX_ID`（`:2665`，理由 `:2663-2664`）。导入期跑三条对账断言
（`:2688`/`:2689`/`:2119`）⇒ **`TABLES` 加表而不同时登记 `ID_COUNTERS`/`PROCESS_ID_PREFIXES` 会让
`import agentflow.schema` 直接失败**（`:2677-2685`）。`specs/*` 不是本文件的镜像，但**词表经 specs 进提示词**：
`specs/b.py:122`（`STATEMENT_ORIGINS`）、`specs/b.py:131`（`EVIDENCE_KINDS`）、`specs/a.py:83`、`specs/d.py:126-127`、
`specs/e.py:34`、`specs/g.py:53`；另 `agent_prompts.py:1728` 把 `S.SCHEMA_VERSION` 与 `S.TABLES` 的键逐字渲染进
每个角色的提示词 ⇒ 动 `TABLES`/`SCHEMA_VERSION` 会红 `tests/test_agent_surface_snapshot.py:207`（重冻命令在该文件 `:25`）。

### 1.2 逐改动点

#### (a) R-05：`check_array_invariants` 混类型抛 `TypeError`

**位置**：`check_array_invariants`（`:2411-2435`），问题行 `:2432`；权威调用点 `validate_table`（`:2724`）；
store 侧调用点 `store.py:947`（写者锁外）/ `store.py:1374`（写者锁内）。

**当前代码**（`:2429-2434`）

```python
        if not isinstance(val, (list, tuple)):
            bad.append(f"{fname} 声明为集合但值不是数组：{type(val).__name__}")
            continue
        if list(val) != sorted(set(val), key=lambda v: (str(type(v)), v) if False else v):
            # 上面的 key 参数是为了让混合类型也能比较；实际值域只有 str/int。
```

**改成什么**（三步缺一不可）

```
STEP-1（表级）：先判元素类型、不比较异类型
  if any(not isinstance(v, str) for v in val):
      bad.append(f"{fname} 声明为集合但元素不是字符串：{[type(v).__name__ for v in val]}"); continue
  if list(val) != sorted(set(val)): bad.append(f"{fname} 声明为集合但未升序去重：{list(val)}")
STEP-2（行级内联件 7 处必须同步，否则 TypeError 仍从 validate() 先抛出）：:374 Concept.related_concepts /
  :418 Relation.concept_ids / :577 ReprocessRequest.relation_ids / :659 ResearchQuestion.contradiction_relation_ids /
  :669-672 {related_concept_ids,related_relation_ids,evidence_lit_ids} / :811 Conjecture.experiment_ids /
  :1672 Statement.derived_from —— 推荐改为复用同一私有谓词 _set_problems(field,val)->list[str]。
STEP-3（可选，诊断）：store.py:947/:1374 外把非 ValueError 翻成 StoreError 并带表名。
```

**依据**：`draft/44` R-05（`禁`(schema)；`store.py:947/1374`）；`draft/41` §3.1。**本次只读实测（决定性）**：

```
1 Concept.validate -> TypeError '<' not supported between instances of 'str' and 'int'
2 check_array_invariants -> TypeError  3 validate_table -> ESCAPED TypeError
4 Relation.validate -> TypeError       5 check_array_invariants(relations.supporting_lit_ids 混类型) -> TypeError
```

⇒ **只改 `:2432` 不成立**：`validate_table:2722` 先调 `obj.validate()`，7 处行级内联件先抛；另 `verify.py:156-159`
同样只 `except ValueError` ⇒ 混类型会让 `verify_all` 第 1 段崩。顺带（F-07 同族）：`tests/test_fc05_contract.py:66`
断言"集合字段由 `validate_table` **集中**检查（唯一权威点）"，而 17 个 set 字段里 **9 个**另有一份行级内联件。

#### (b) F-01：等级机制

**位置**：`Statement.bits`（`:1607-1613`）、bits 段校验（`:1678-1696`）、`evidence_kind` 声明（`:1604-1606`）
与校验（`:1635-1636`）；读侧 `evidencebits.py:64/108/186`、`closing.py:885-914`、`statusreport.py:108-109`。

**当前代码**（`:1604-1613` 节选）

```python
    #: 证据等级（复用 `EVIDENCE_KINDS`）：proof / cross_check / heuristic。
    #: `draft/39` §3.14 起它是**派生只读视图**：真正判等级的是 `bits`（五元证据位）。
    evidence_kind: str = "heuristic"
    #: …等级**不落盘**，由 `evidencebits.derive_grade` 现算（盘上存缓存 = 给出"自报等级"的口子）
    bits: dict = field(default_factory=dict)
```

**改成什么（一半可行、一半不可行）**

```
可行半（Statement）：不加字段，补产出方。落点 = 写入口 agent_b/register_statement.py:179-199，构造前算一次：
  bits = EB.bits_of(proof=bool(proof_text.strip()) or origin=="external_lit", proof_process=proof_text,
                    origin=origin, source_lit_id=lit_id, quote_verified=quote_verified)
  S.Statement(..., bits=bits)；只想先出声就把 proof_text 折成第 2 位（proof_process）——零新字段。
  读侧一律走 evidencebits.bits_from_row(row)["grade"]（closing.py:899、statusreport.py:108 已如此）。
不可行半（Document.claims / Relation）：derive_grade 的入参是**五元位**；这两处没有五位、也没有 bits 等价物
  （实测 grep '\bbits\b' claimanatomy.py doc_tools.py = 0 命中）⇒ 要先发明 claim→bits / relation→bits 映射
  （新设计）。⇒ draft/45 的"各一处由 derive_grade 计算"不成立。
```

**依据**：`draft/44` F-01（`禁`(schema) `行`）。实测：`statements.bits` 非空 **0/138**；`grep 'bits=' src/` **0 命中**；
`apply_cascade` 只有定义（`evidencebits.py:361`）零调用；13 条 `own_result` 现算等级全 `conjecture`。
**不许把 grade 落盘**：`evidencebits.bits_shape_problems:176-181` 逐字"等级不许自报（判据永远现算）"、
`schema.py:1611` 逐字"等级**不落盘**"。只读属性可行，但二阶坑：`table_tools._build_row` 的
`known = {f.name for f in dataclasses.fields(cls)}`（`table_tools.py:114-117`）⇒ **只在 `to_dict()` 里多吐 `grade`
键，模型把该行原样回写时会被 `table.upsert/update` 拒掉**（"没有字段 ['grade']"）。`closing.py:1454-1464` 另有
逐字边界：`statements` 没有指向 `experiments` 的字段 ⇒ `MUST_T3_CONDITIONS` 的 ②④ 今天只能 `counted_only`。
形式化 `exit_code` 的折叠点在 `agent_e/core.py:402`（不在本文件），见姊妹件 §2。

#### (c) P-06：`proof_text` 硬要求改为"缺 ⇒ 降级 + 待办"

**位置**：`Statement.validate`（`:1657-1663`）；写入口 `agent_b/register_statement.py:141-142`（`missing_proof_text`）。

**当前代码**（`:1657-1663`）

```python
        # ---- 自产结果：证明是它与"一句声称"的唯一分界（§10 的自产入库门）
        if self.origin == "own_result" and not self.proof_text.strip():
            raise ValueError(
                "origin='own_result' 必须给 proof_text：自产的命题没有证明就入库，"
                "等于把我们自己的猜测抬成事实（§10 的'自产定理该不该进事实库'那一问…）"
            )
```

**改成什么**

```
schema.py:1658：删掉这条 raise（不拦）。等级侧不用另写：第 2 位空 ⇒ derive_grade 已给 conjecture。
agent_b/register_statement.py:141：missing_proof_text 从"拒"改"落库 + 返回 pending=[{kind,stmt_id}]"。
（refusals.py:43-44 的导入期断言 `PRECONDITION_REASON in S.REFUSAL_REASONS` 的对象不是它，不受影响——已核。）
```

**依据**：`draft/44` P-06（`禁`(schema)）。实测关键：**13 条 `own_result` 全带 `proof_text`，而现算等级 13/13
全是 `conjecture`** ⇒ "降级"在数据面**已经发生**；schema 侧实质只是删一条 raise，收益在提示词与写入口。

#### (d) P-07：`cross_check` 必带 disclaimer 改为框架自动补

**位置**：`Document.validate`（`:1412-1417`）；同题另有 `verify.py:985-987`、`claimanatomy.py:1282-1291`、
`review_tools.py:432-438`。

**当前代码**（`:1412-1417`）

```python
            # ---- 硬约束 2：cross_check 的断言**必须**自带"不构成证明"声明（FC-22）
            if ek == "cross_check" and not str(c.get("disclaimer") or "").strip():
                raise ValueError(
                    f"claims[{cid}] 的 evidence_kind='cross_check'，必须给 disclaimer"
                    "（如'数值交叉验证，不构成证明'）。**这句话由结构强制，不靠人记得写**"
                )
```

**改成什么**：**不在 `schema.py` 里补**。`doc_tools.py:1115-1118` 逐字："这里刻意不自动补 disclaimer（虽然
`compose_claim` 会补）：…让闸门顺手把违规项改好，会让'调用方漏写了声明'这件事从此不可见 —— 那正是本框架
最忌讳的静默修复。" 可行落点（**局部**）= `doc_tools.normalize_claims`（`:1112-1169`）在 `scan_claim`（`:1167`）之前补并留痕：

```
if str(row.get("evidence_kind") or "")=="cross_check" and not str(row.get("disclaimer") or "").strip():
    row["disclaimer"] = CROSS_CHECK_DISCLAIMER          # 常量在 doc_tools.py:67
    row.setdefault("_autofilled", []).append("disclaimer")
# `_` 前缀诊断字段被 table_tools._build_row:115 与 store.rebuild 的合并逻辑刻意保留
```

若同时在 schema 侧"减"，只应删**必填性**并同步 `claimanatomy.FIELD_SPECS.disclaimer.required`
（`claimanatomy.py:221/447-456`，其口径逐字来自 `Document.validate`），否则写入期与审校期两套口径（FC-03）。
**依据**：`draft/44` P-07。**未核实**：按逐字常量数，`src/`+`tests/` 共 **24 行 / 13 个文件**（`claimanatomy.py`4、
`doc_tools.py`3、`schema.py`1、`tests/test_closing_gate.py`5…；`specs/` 0 命中）；**draft/44 的"81 处"本轮未能复现**，口径未核实。

#### (e) P-08："没有逐字引文不许产出关系"改为三态 + 待核队列

**位置**：**这句话不在 `schema.py`**，是提示词文字 `agent_prompts.py:595-597`（= `specs/b.py` 的 B 边界第 4 条，
进 golden 快照）。schema 侧对关系引文只有纯三态、**没有"必须 True"**（`:430-431`）；落库侧
`agent_b/run_once.py:249-274` 已经在"没核过也落库、降 `status=suspect`"。

**当前代码**（`:430-431`；落库侧 `run_once.py:257/267`）

```python
        if self.quote_verified is not None and not isinstance(self.quote_verified, bool):
            raise ValueError("quote_verified 必须是 bool 或 None（三态：通过 / 不一致 / 没校验）")
# run_once.py:  quote_verified=chk.verified,  …  d["_quote_check"] = chk.to_dict()   # 诊断字段，rebuild 刻意保留
```

**改成什么**：schema **不改**（现状方向正确）。改提示词 + `specs/b.py` 镜像；"待核队列"的落点不在本文件（F-05）。
**依据**：`draft/44` P-08（`禁`(schema) `提`）。实测：`relations` 1772 行 `quote_verified` = True 1754 / False 18 /
**None 0** ⇒ 三态中间档从未出现；真缺的落点是 `not_found`/`no_text_layer` 这些 **reason** 只躺在 `_quote_check`
诊断字段里，没有可查询的列。

#### (f) E-09：`LIT_MATCH_STATUSES` 补 `none` —— **判定不可行**

**位置**：`LIT_MATCH_STATUSES`（`:122`，说明 `:103-121`）；校验 `Literature.validate`（`:324-328`）；
暴露 `tools/table_tools.py:461/863-864`；判据 `verify.py:317-328`。

**当前代码**（`:113-122` 节选）

```python
#:   - 本栏（§2 R1b）：问"**这一篇**是不是我要的那一篇"（文献身份）⇒ `mismatch`；
#:   - §5.2 / §16 P2 / §2 R14：问"**这条定理在不在这篇里**"（文内定位）⇒ 第三态叫 `none`，**不落本栏**。
LIT_MATCH_STATUSES = ("exact", "partial", "mismatch")
```

**判定**：不可行。`:118-121` 逐字否证："把它们折成一个字段会让'我下错了论文'与'论文里没有这条定理'在台账上
同形 —— 而这两件事在真机里各自都发生过一次"。文内定位那一问的出口在 `agent_prompts.py:573` / `specs/a.py:152`
（"回报定位结论（matched ∈ exact/partial/**none**）"），在回报文本里。**依据**：`draft/44` E-09、`draft/45` §1.1③。
兼容实测：加 `none` ⇒ `PASS=1322 FAIL=0`（不影响历史）；但真机三档零产出，加 `none` 只把死取值 3→4
（`tools/vocab_census.py` 会多报一条）。**正确方向**：给"文内定位三态"新落点列（如 `literature.finding_matched`）
——要新列 = 加字段，属人裁，本件不做。

#### (g) EE-06：`documents[].claims` 的 `status` / `allowed_use` 0/449

**位置**：容器形状 `schema.py:1344`（`claims: list[dict]`），claim 级校验 `Document.validate:1387-1451`；
**两个字段本身不在 `schema.py`**，在 `claimanatomy.py:130/135/139/142`（四张词表）与 `:226`（`CLAIM_FIELDS`）。

**当前代码**（`:1387-1393`，证明它只认固定键、**不拒绝未知键**）

```python
        for i, c in enumerate(self.claims):
            if not isinstance(c, dict):
                raise ValueError(f"claims[{i}] 必须是对象")
            cid = str(c.get("claim_id") or "")
            if not cid:
                raise ValueError(f"claims[{i}] 缺少 claim_id")
```

**改成什么（三条互斥路线，只有路线 2 今天能走）**

```
路线1（draft/45 字面："加进必填"）——不可行：实测 PASS 1322→1270，52 份 documents.json 当场变红。仓库内已有
  同题未实施提案 docs/SCHEMA-MIGRATION-PROPOSAL-claims.md：状态逐字"未实施（schema.py 一个字都没动）"，
  §3.2 逐字给出同一结论（默认值会把"从没问过"伪造成"待精化"），§3.3 的分段建议 = "第一次：只加受控词表常量
  与'打了这些字段才检查'的取值域校验，SCHEMA_VERSION 不动"。
路线2（只在字段存在时校验取值域，不加必填、不升版）——可行，0 红：
  if (st := c.get("status")) is not None and st not in CA.STATUS_VALUES: raise ValueError(...)
  if (au := c.get("allowed_use")) is not None and au not in CA.ALLOWED_USE_VALUES: raise ValueError(...)
  前置：先把 claimanatomy 的四个常量搬到 schema（唯一来源）、claimanatomy 改为转发（提案 §2.3 的 diff）并加
  "同一个对象"断言。这一步**不解决"0 产出方"**。路线3（"去掉空转字段"）做不到字面意义：字段不在 schema.py，
  删不掉；能删的是消费侧 gates.py:2143-2216（G14 三条分支）、claimanatomy.py:345-353、doc_tools.py:1544，
  删它们 = 改读数口径（draft/45 §0 第 2 条）。**建议改为加产出方**：compose_claim(:700/778) 已收 allowed_use，
  改成"按 evidence_kind 由框架渲染默认值 + 区分'没写'与'写了空'"（三态工具已在 claimanatomy.presence_of:865）。
```

**依据**：`draft/44` EE-06（`禁`(schema)）。本次实测复核：`status` 0/449、`allowed_use` 0/449，claims 键全集 18 个
不含二者；消费方 `gates.py:2178/2191`（G14）、`claimanatomy.py:1748`（`main_body_claims`）、`doc_tools.py:966/1100`
（渲染）⇒ **有读者、有声明、无产出方**。

#### (h) EE-07：`evidence_kind` 声明为"派生只读视图"却被手填

**位置**：声明 `schema.py:1604-1606`（见 (b) 的原文）；校验 `:1635-1636`；
写入口 `agent_b/register_statement.py:69-86`（参数表，`:80` 缺省 `"cross_check"`）与 `:192`。

**当前代码**（`register_statement.py:180-193` 节选）

```python
            row = S.Statement(
                stmt_id=stmt_id,
                origin=origin,
                quote_reason=str(quote_reason or ""),
                evidence_kind=evidence_kind,      # ← 手填；整个构造里没有 bits=
                status="active",
            )
```

**改成什么（两条互斥路线，必须选一条并写明另一条为什么不做）**

```
路线A（降成真·派生，"加"）：① Statement 不再收 evidence_kind（去掉字段或标 deprecated）；② 读侧唯一入口 =
  由 bits 现算（evidencebits 加 kind_of(bits)->"proof"|"cross_check"|"heuristic"，口径与 derive_grade 同源：
  formal verified ⇒ proof；proof 位/numeric verified ⇒ cross_check；否则 heuristic）；③ 影响面（实测）：
  specs/b.py:131 的 enum 消失 ⇒ 提示词变 ⇒ 重冻 golden；register_statement 的 bad_evidence_kind 分支（:98-101）
  退场；closing.py:1440/1450/1854/1877 与 claimanatomy 的读法改走 kind_of ⇒ 牵动接口（≥6 文件 + 快照）。
路线B（承认它手填，"减"注释）：把 schema.py:1604-1605 那两行改成事实，并把读法统一到"手填 + 一条一致性判据"；
  最小改动（2 行 + 1 条判据），但 EE-07 的实质（三条判据各说各话）留着。
```

**依据**：`draft/44` EE-07（`禁`(schema) `行`）。实测给出"注释是假的"的硬读数：`grep 'bits=' src/` = 0；
`statements.evidence_kind = {cross_check:124, heuristic:8, proof:6}` 而 `bits` 非空 0 ⇒ **一条
`evidence_kind="proof"` 且 `bits={}` 的行今天完全合法**（6 行就是），`validate_table` 全过。三条口径：
`evidencebits.derive_grade`（读 bits）、`claimanatomy.status_evidence_consistency:917`（读 status×evidence_kind）、
`closing.py:1438-1451`（读 evidence_kind）。顺带（本件登记）：`schema.py:1684` 的 `if self.bits:` ⇒ **空 bits 直接跳过**，
"声明了五元位却一位都没记"在数据面**没有任何判据**。

### 1.3 调用面

| 符号 | `src/` 生产调用点 | `tests/` 覆盖 |
|---|---|---|
| `check_array_invariants` | `schema.py:2724`（唯一生产）；`verify.py:1173` 用 `array_kinds` | `tests/test_coverage_schema.py:50/64/77/94/110/127/145`（7 例，**无混类型**）；`tests/test_fc05_contract.py:66` |
| `validate_table` | `store.py:947`、`store.py:1374`、`verify.py:157` | `tests/test_schema.py:169/177`；`tests/test_idem_key_writers.py:150/213`；`tests/test_usage_ledger_idem_key.py:93/105/111/120/125` |
| `row_from_dict` | 15 处：`agent_a/run_once.py:228`、`agent_d/*`（`adjudicate:241,380`、`ingest:145,173`、`core:539,956,1535`、`poll:90,112,142`、`research:61`）、`agent_f/core.py:866`、`agent_g/revise.py:125`、`pipeline.py:740`、`tools/{research,search,table}_tools.py` | `tests/test_statements_table.py:81`；`tests/test_coverage_schema.py` |
| `Document.validate`（claims） | `store.py:947`→`validate_table`；构造期另一套 `doc_tools.py:1112-1169` | `tests/test_agent_h.py:261`；`tests/test_verify_extended.py:433`；`tests/test_tools_audit_fixes.py:53-67`；`tests/test_closing_gate.py:132-139` |
| `Statement.validate`（proof_text） | 同上；写入口 `agent_b/register_statement.py:200` | `tests/test_statements_table.py:142-147`（**P-06 会红它**）、`:150/163/173` |
| `LIT_MATCH_STATUSES` | `tools/table_tools.py:461/863-864` | `tests/test_literature_match.py:126-127` |
| `EVIDENCE_KINDS` | `specs/b.py:131`、`register_statement.py:98`、`schema.py:1635` | `tests/test_evidence_bits.py`、`tests/test_agent_b.py` |
| `SCHEMA_VERSION`/`TABLES` | `store.py:551/642/757/862`、`runflow.py:1534`、`agent_prompts.py:1728`、`table_tools.py:837-879` | `tests/test_fc05_contract.py:171`；`tests/test_release_all.py:1039`；`tests/test_agent_surface_snapshot.py:207` |
| CLI/文档/快照 | `README.md:378`（"SCHEMA_VERSION=1、17 张表"）、`DEVELOPMENT.md:171`（`schema_tables=17`+复跑命令）、`DEVELOPMENT.md:1151`（发布门第 7 项）、`release_check.py:1059` | — |

`specs/*` 镜像：`schema.py` 本身不进任何镜像；但上述词表/接口改动**经 specs 进提示词**，必须重冻
`tests/golden/agent_surface_snapshot.json`（`python -B tests/test_agent_surface_snapshot.py --write`）。

### 1.4 数据结构与历史数据影响

| 条目 | 动表/字段 | 动 `SCHEMA_VERSION` | 历史 1322 份实测 |
|---|---|---|---|
| R-05 | 否（纯判据） | 否 | 0（0 混类型样本） |
| F-01（Statement 补产出方） | 否（`bits` 已在） | 否 | 0 |
| F-01（claims/Relation 加 grade） | 是（加字段/键） | 否 | 只读属性 0；**存储字段且必填 ⇒ 33 份 statements.json 红**（1289） |
| P-06 / P-07 | 否（删校验） | 否 | 0（放宽方向） |
| P-08 / E-09（`+= none`，扩词表） | 否 | 否 | 0 |
| EE-06 路线 1 / 路线 2 | 是（claims 键 / 四张词表搬入） | 否 | **52 份 documents.json 红**（1270） / 0 |
| EE-07 路线 A | 是（减字段） | 否 | 0（历史行靠 `row_from_dict` 忽略未知键读进） |

**以上全部条目都不需要动 `SCHEMA_VERSION`。** 若将来要动，代价（本次核实）：`validate_table:2702-2703` 拒掉全部
1322 份旧快照；须同步 `src/agentflow/__init__.py:19`（`tests/test_fc05_contract.py:171` 与 `release_check.py:1059`
对账）、提案 §3.3 的迁移三步、`agent_prompts.py:1728` 的提示词读数（→ 快照重冻）。`draft/45` §5 第 1 条的
"倾向不升版"与实测一致。

### 1.5 可行性与改动量

| 条目 | 档次 | 估行数 | 文件数 | 必须的前置 |
|---|---|---|---|---|
| R-05 | **局部**（表级 + 行级 7 处） | 20–35 | 1（+1 若抽公共谓词） | 无 |
| F-01（Statement 补产出方） | **局部** | 10–25 | 2 | "逐条 T3 背书"须加 `proof_experiment_id`（人裁）；exit_code 半在 `agent_e` |
| F-01（claims/Relation 的 grade） | **牵动接口** | ≥60 | ≥4 | 先设计 claim→bits 映射（未立项） |
| P-06 | **牵动接口** | 15–30 | 4（+4 测试） | F-05 待办队列 |
| P-07 | **局部**（落 doc_tools，不在 schema） | 8–15 | 3 | 若改 schema 必填性须同步 `claimanatomy.FIELD_SPECS` |
| P-08 | **纯提示词级**（本文件 0 改动） | 0 | 0 | F-05 待核队列 |
| E-09 | **不可行** | — | — | 需新列（人裁） |
| EE-06 | 路线2 **局部** / 路线1 **不可行** / 路线3 **牵动判据口径** | 10 / — / 20 | 2–4 | 词表单一来源搬迁 |
| EE-07 | 路线A **牵动接口** / 路线B **局部** | 80 / 6 | 6 / 2 | 路线A 先定 kind_of 口径表 |

### 1.6 风险与验证

**会红的测试**：R-05 → `tests/test_coverage_schema.py:77`、`:110`（本方案 STEP-1 不动这两条文案路径，应保持绿；
须新增混类型负控）。P-06 → `tests/test_statements_table.py:142`、`tests/test_action_surface_matches_acceptance.py:226`、
`tests/test_conductor_payload_outcomes.py:126/133`、`tests/test_intake_actions.py:407`。P-07 →
`tests/test_verify_extended.py:433`、`tests/test_agent_h.py:261`（只要"schema 放宽、判据不放宽"就仍绿）、
`tests/test_refusal_family_numbers.py:61`。EE-06 路线1 → **无既有测试会红，这正是它的危险**。EE-07 路线A →
`tests/test_agent_surface_snapshot.py:207`、`tests/test_release_all.py:1039`。动 `TABLES`/`SCHEMA_VERSION` →
`tests/test_fc05_contract.py:171`、`test_release_all.py:1039`。

**"改前必红"的负控**

```
1) test_check_array_invariants_reports_mixed_type_elements_instead_of_raising（tests/test_coverage_schema.py 新增）
   obj = Concept.__new__(Concept); obj.related_concepts = ["0001", 2]; bad = S.check_array_invariants("concepts", obj)
   assert bad and "元素不是字符串" in bad[0]                                     # ①改前 TypeError ⇒ 必红
2) test_validate_table_reports_mixed_type_rows_as_value_error（tests/test_schema.py 新增；6 个类各一条）
   with pytest.raises(ValueError): S.validate_table("concepts", {…["related_concepts":["0001",2]]…})   # ①改前逃逸 ⇒ 必红
3) test_an_own_result_without_proof_text_is_recorded_and_downgraded（替代 tests/test_statements_table.py:142）
   r = register_statement(statement_full="我们猜…", origin="own_result", proof_text="")
   assert r["ok"] is True and EB.bits_from_row(r["row"])["grade"]=="conjecture" and pending 含 missing_proof_text  # ①必红
4) test_a_cross_check_claim_gets_the_disclaimer_autofilled_with_a_trace
   out = doc_tools.normalize_claims([{"claim_id":"c1","text":"x","evidence_kind":"cross_check","citations":["lit:0001"]}])
   assert out[0]["disclaimer"]==DT.CROSS_CHECK_DISCLAIMER and "disclaimer" in out[0]["_autofilled"]  # ①改前抛 ⇒ 必红
   （配反控：显式写了别的 disclaimer ⇒ 不许被覆盖）
5) test_claims_status_is_checked_only_when_present（EE-06 路线2）
   缺 status 的 claim 通过；with pytest.raises(ValueError): status="已证"                          # ①改前后者不被拦 ⇒ 必红
6) test_evidence_kind_is_not_a_second_grade_source（EE-07）
   row = {"stmt_id":"0000","origin":"own_result","proof_text":"证明","evidence_kind":"proof","bits":{}}
   assert S.row_from_dict("statements",row).validate() is None and EB.bits_from_row(row)["grade"]=="conjecture"
```

**真机回放（只读）**：R-05/兼容闸 → §0① 的命令（改前 1322/0/0，改后失败数不增）。F-01 →
`p8c-fermat-shorter-proof`、`p6e-research-from-zero`；读数 = `EB.bits_from_row(r)["grade"]` 分布（改前全 `conjecture`）。
P-06/P-07/EE-06 → `p8f-fermat-shorter-proof`；读数 = 受影响 claims 条数与 `status`/`allowed_use`/`disclaimer`
三键非空计数（改前 0 / 0 / 逐条）。EE-07 → `p8e-fermat-shorter-proof`；读数 = `evidence_kind=="proof"` 行数与
`bits` 非空行数（改前 **6 与 0**，不相等即 EE-07 的读数形态）。

**不可逆点与防法**：只有两个 —— `SCHEMA_VERSION` 与"给历史行加必填"。防法：本批全部条目不升版、不加必填；
每次 `schema.py` 改动后**先跑 §0① 兼容命令**再跑测试（`draft/45` §3 兼容闸）。半张不可逆：EE-06 路线3 会改
历史裁定口径 ⇒ 在 `draft/44` 该行写明"从哪一趟起口径变了"。

### 1.7 本文件"不做"的部分

1. 不动 `SCHEMA_VERSION`（`:18`）与 `src/agentflow/__init__.py:19`；不动 `TABLES`（`:2439`）与
   `ID_COUNTERS`/`PROCESS_ID_PREFIXES`（导入期断言 `:2677-2685` 的对象）——E-09 的"新列"、F-01 的
   "`proof_experiment_id`"都是新增字段，本批不做；不动 `Experiment.validate`（`:1085-1186`，R-01 在姊妹件 §1）。
2. 不动 `ReviewFinding` 的四键设计与 `REVIEW_FINDING_FORMAT_SINCE`（`:1024/1727-1735/1815`）：那是"刻意不加非空
   断言"的既有边界，与 R-06 相邻但不同条。
3. 不动 `Document.validate` 的四条既有硬约束（FC-02 引用 / FC-22 disclaimer / FC-25 否定分类 / P-10 反例两源）：
   本批只谈"放宽或自动补"，**不删任何一条**。
4. 不动 `PageRange` 的单边 None 形态（`draft/41` §3.8）与 `USAGE_SCOPES` 一族（`:2119`）；不真删
   `Statement.evidence_kind`（EE-07 路线 A 只给方案与代价）。

---

## §2 `src/agentflow/store.py`（1449 行）

### 2.1 现状

| 符号 | 位置 | 关系 |
|---|---|---|
| `LOCK_ORDER`（18 项，`counters` 恒最后） | `store.py:66-90` | 事务取锁次序 |
| `MAX_ID = 9999` | `:93` | 与 `schema._ID_RE` 由导入期断言对账（`schema.py:2670`） |
| `class Tx` / `.alloc_id` | `:154` / `:306` | R-02 |
| `Tx._record` / `.info` | `:427` / `:441` | 事件形状唯一定义处 |
| `class Store` / `._writer_lock` | `:446` / `:465` | `init`/`rebuild`/`set_counters` 共用 |
| `set_counters` / `_merge_counters_for_commit` | `:583` / `:651` | counters 的两个写入口 |
| `_atomic_write` | `:761` | 唯一落盘通道（临时名+fsync+replace，重试 6 次） |
| `_check_version` / `_load` / `read` | `:831` / `:858` / `:881` | 读期 fail-closed |
| `tx` | `:890`（提交块 `:930-993`，`finally` `:994-1008`） | R-02 的 draft/44 引用点 |
| `_append_events` / `read_events` | `:1011` / `:1090` | 批次 + commit 标记 |
| `rebuild` / `_snapshot_keys` / `_rebuild_locked` | `:1106` / `:1171` / `:1197` | R-06 · R-05 调用点 |

**位置**：import 标准库 + `filelock`（`:48`）+ `from . import schema as S`（`:50`）。被生产 import 的：`cli.py:22`、
`conductor.py:63`（只 `StoreError`）、`deliver.py:304`、`demo.py:25`、`faculty_checks.py:376`、`host.py:578`、
`locallib.py:47`、`modelcost.py:474`、`pipeline.py:41`、`projects.py:48`、`renderanchor.py:249`、`runflow.py:1902`、
`statusreport.py:379`；`paperbuild.py:381-387` 把它写进生成的脚本模板。`rebuild()` 的唯一生产消费者是
`cli.py:328-336`，而它**只打印 `applied`/`skipped`/`counters` 三个键**（`:334-335`）。

### 2.2 逐改动点

#### (a) R-02：实验日志被覆盖（store 半）—— **拟议改法不可行，须换落点**

**位置**：store 侧 = `tx` 的提交块 `:930-993`（counters 只在写者锁内合成、**只在提交成功时落盘**）与
`finally`（`:994-1008`，`:999` 无条件清进程内缓存）；**真凶在写日志侧** = `agent_e/run_experiment.py:159-177`
（在事务体内用 `eid` 命名并**立即写盘**）+ `agent_e/_support.py:682-705`（`target.write_text(...)` = 覆盖写）。

**当前代码**（`store.py:962-967`；`run_experiment.py:165-172`）

```python
                if counters_pending:
                    to_write.append((self.data / "counters.json", self._merge_counters_for_commit(t)))
                if t._events:
                    self._append_events(t._events)
```

```python
        with self.store.tx("experiments", actor=self.actor, note="e.run_experiment") as tx:
            eid = tx.alloc_id("experiment")
            log_rel = f"out/experiments/{eid}.log"
            log_error = _write_run_log(self.workspace_root / log_rel, claim=claim, …)
```

**改成什么**：`draft/45` §1.1 的"①事务回滚时推进计数器（或让 `alloc_id` 只在提交后生效）"**两条都不可行**：

```
反驳①（回滚推进计数器）与两条既有测试逐字相反 —— tests/test_store_concurrency.py:212
  test_failed_tx_does_not_leak_id_allocation：:229 assert counters.get("concept",0)==0（"磁盘计数器应保持回滚后的值"）、
  :234 assert cid=="0000"（"回滚后重新分配应仍从 0000 开始"）；同文件 :152
  test_failed_validation_rolls_back_literature_and_counters 的 :164 assert read_data_bytes(store)==before
  （推进计数器要写 counters.json ⇒ 必红）。另 3 处 docstring 同侧：search_tools.py:1085（"同一事务里的分配号
  也会随回滚作废"）、store.py:995-998（逐字解释 finally 为何清缓存）、store.py:350-358（R6-AN-1）。
反驳②（独立于测试）rebuild 的 counters 只由事件里的 alloc 推出（store.py:1327-1332），而回滚事务的 alloc 事件
  **不在** events.jsonl（事件只在提交块追加，:966-967）⇒ 即使推进 counters.json，下一次 rebuild 会把它退回去。
反驳③（"alloc_id 只在提交后生效"）不可实现为接口：调用方要在事务体内用 eid（命名日志、写 artifact_paths、
  返回 {"experiment_id": eid}），号不能推迟到提交后。
可行改法（不动计数器语义，只改日志落盘时机/命名，任一）：(a) 把 _write_run_log 移到 with 块之后（提交成功再写，
  artifact_paths 提交后补一次 upsert）；(b) 日志名带唯一后缀 <eid>.<pid>-<tid>.log，提交成功后 os.replace 成
  <eid>.log；(c) 先写 out/experiments/.pending/<eid>.<唯一>.log，提交后 rename。三者都保持 artifact_paths 记的仍是
  out/experiments/<eid>.log ⇒ 不动存储契约。与姊妹件 §3.2(b) 的 _write_run_log(..., overwrite=False) 同族，
  建议合并为一处：**改 agent_e（≈15–30 行），store.py 0 改动**。
```

**依据**：`draft/44` R-02（`禁`(store) `行`）；真机证据见 §0④。

#### (b) R-06：`rebuild` 的行级失败静默丢行

**位置**：`_rebuild_locked` 的重放循环 `:1337-1342`；返回值 `:1377-1411`。

**当前代码**（`:1337-1342`）

```python
            try:
                obj = S.row_from_dict(table, row)
                obj.validate()
            except Exception:
                skipped += 1
                continue
```

**改成什么**（`skipped` 的类型**不许变** —— 3 处测试直接断言它的数值）

```
STEP-1 细分原因但保留 skipped 这个整数键：skipped_by_reason: dict[str,int]（键 = unrecognized_table /
  schema_rejected / shape_broken；原 :1334-1336 的 `table not in S.TABLES` 支也走 skipped）；
  skipped_details: list[dict]（每条 = {"table","id","reason","error":f"{type}: {msg}","event_index"}）。
STEP-2 **不许**把 except Exception 收窄成 except ValueError：S.row_from_dict 对缺必填位置参数的行抛 TypeError
  （tools/table_tools.py:121-123 专门 except TypeError 就是承认这一点）⇒ 收窄后这类行会让整次 rebuild 崩，
  比静默丢更糟。正确做法是分类捕获并两支都记明细：
      except ValueError as e:  reason = "schema_rejected"
      except Exception as e:   reason = "shape_broken"
STEP-3 让明细看得见：cli.py:334 后加一行、skipped_by_reason 非空时打印它（约 3 行）。
```

**依据**：`draft/44` R-06（`禁`(store) `读`）；`draft/41` §3.5（57 工作区 `skipped=0`）。本次复核：1322 份
`validate_table` 全过 ⇒ 今天被 schema 挡下的行是 0，R-06 的收益在**未来加严判据**与**事件行形态坏**两类。
`store.py:1021-1023` 与 `schema.py:1021-1024` 逐字写明"静默丢"是数据遗失：R-06 不改"丢"这个决定，只改可不见度。

#### (c) R-05 的调用点（`store.py:947` / `store.py:1374`）

**位置**：`:947`（提交块，**写者锁之外**）；`:1374`（`_rebuild_locked`，**写者锁之内**；`rebuild` 已在
`:1207-1216` 做完备份，所以数据不丢，但"灾难恢复"这一唯一手段失败）。

**当前代码**（`:945-948`）

```python
                spec = S.TABLES[table]
                doc = {"schema_version": S.SCHEMA_VERSION, "rows": t.rows(table)}
                S.validate_table(table, doc)
                to_write.append((self.data / spec["file"], doc))
```

**改成什么**：**store 侧 0 改动**。R-05 必须在 schema 侧修完（§1.2a）。只在这里把 `except` 加宽等于把"库里有
混类型"变成静默通过 —— **不可行**。可选一层："把非 `ValueError` 翻成 `StoreError` 并带表名"（诊断改善，
不解决根因）。**依据**：`draft/44` R-05 把这两处列为调用点；`verify.py:156-159` 是第三个 `except ValueError`
的落点（实测同样会逃逸）。

### 2.3 调用面

| 符号 | `src/` 调用点 | `tests/` 覆盖 |
|---|---|---|
| `tx` | 全仓 100+ 处（每个写动作；写集见 `capabilities.WRITE_SETS`） | `tests/test_store_concurrency.py:133/152/165/212`；`tests/test_store_r3_commit_order.py`；`tests/test_tx_mark_dirty.py` |
| `Tx.alloc_id` | `agent_a/run_once.py`、`agent_b/run_once.py:137`、`agent_b/register_statement.py:179`、`agent_e/run_experiment.py:166`、`agent_e/core.py:405`、`agent_f/create_plan.py`、`agent_g/*`、`tools/*` | `tests/test_store_alloc_guard.py:40/58/72/85/111/127`；`tests/test_store_concurrency.py:115/122/212` |
| `rebuild` | `cli.py:333`（唯一生产） | `tests/test_rebuild.py:58/75/89`；`tests/test_store_r3_commit_order.py:79/127/145/182/301`；`tests/test_store_delete_events.py:70-158`；`tests/test_p910_p9_review_finding_format.py:512/527/540`；`tests/test_conductor.py:569/589`；`tests/test_task_instance.py:102`；`tests/test_r5_orchestration_cost.py:896`；`tests/test_usage_ledger_audit.py:158/186`；`tests/test_usage_ledger_idem_key.py:299/336`；`tests/test_agent_b_gates.py:444/882` |
| `_merge_counters_for_commit` / `set_counters` | `store.py:964`；`tools/probe_gap_ledger.py` | `tests/test_store_counters_commit.py` |
| `_atomic_write` | `store.py:645/979/1375/1376`、`init` | `tests/test_store_init_guard.py`；`tests/test_store_r3_commit_order.py` |
| `LOCK_ORDER` / `MAX_ID` | `store.py:895/932`；`schema.py:2665`（对账） | 导入期断言（`tests/test_fc05_contract.py`） |

CLI/文档/快照：`cli.py:328-336`（**需同步**）；`README.md:378`、`DESIGN.md:480`（17 表快照 + `events.jsonl`）、
`DEVELOPMENT.md:171/486`（`data/` 18 个 JSON）。`store.py` **不进任何 specs 镜像、不进 golden 快照**。

### 2.4 数据结构与历史数据影响

| 条目 | 动表/字段 | 动 `SCHEMA_VERSION` | 历史 1322 份实测 |
|---|---|---|---|
| R-02（改日志落盘，`agent_e` 侧） | 否 | 否 | 0 |
| R-02（回滚推进计数器） | 否，但改 `counters.json` 语义 | 否 | 0（快照不含 counters）——代价在 2 条测试 + 3 处 docstring，不在数据 |
| R-06（新返回键） | 否（返回值形状） | 否 | 0；3 条断言 `skipped == N` 的用例仍绿（键只增） |
| R-05（store 侧） | 无改动 | 否 | 0 |

历史兼容那条必须实测的（逐份 `schema.validate_table`）见 §0①：**1322 通过 / 0 失败 / 0 逃逸**；`store.py` 自身的
改动不改变这个数字（它不改行形状）。唯一会影响它的是 `rebuild` 的重放**结果**，但那要真跑 `rebuild`（写盘），
本任务未跑；只读替代品 = `D:\Incubator\draft\_probe_c_rebuild_dryrun.py`（逐工作区模拟折叠、不落盘；
`draft/41` §1.2 记 57 工作区 `skipped=0 snapshot_ahead=0 incomplete=0`）。

### 2.5 可行性与改动量

| 条目 | 档次 | 估行数 | 文件数 | 前置 |
|---|---|---|---|---|
| R-02（store 半） | **不改 store**；真改动在 `agent_e`（**局部**） | 0 / 15–30 | 1–2 | 与姊妹件 §3.2(b) 合并为一处 |
| R-02（回滚推进计数器） | **不可行** | — | — | 需先改 2 条测试 + 3 处 docstring + `rebuild` 的 counters 折叠（= 重新设计 ID 生命周期，人裁） |
| R-06 | **局部** | 15–25（store）+3（cli） | 2 | 无 |
| R-05（调用点） | **0 改动** | 0 | 0 | schema 侧先修 |

### 2.6 风险与验证

**会红的测试**：R-02 若走"回滚推进计数器" → `tests/test_store_concurrency.py:212`（`:229`/`:234`）、`:152`（`:164`）、
`tests/test_store_alloc_guard.py:111` 一族。R-02 若走"事务后写日志" → `tests/test_agent_e_run_log.py`。
R-06 → **加键不动** `tests/test_p910_p9_review_finding_format.py:557`（`skipped==1`）与 `tests/test_rebuild.py:69`
（`skipped==0`）；反之若把 `skipped` 改名或改成 list，这两条 + `tests/test_rebuild.py:104` 一起红。
R-05 若只改 store 的 `except` → 不红但**引入静默入库**（本件明确否定）。

**"改前必红"的负控**

```
7) test_rebuild_does_not_drop_a_row_without_saying_which_one（tests/test_rebuild.py 新增）
   追加一条 level="bogus" 的 review_findings upsert（无 batch/无版本号）；out = store.rebuild(backup=False)
   assert out["skipped"] == 1  and  out["skipped_details"] == [{"table":"review_findings","id":"0002",
   "reason":"schema_rejected", …}]                                    # ①改前 KeyError("skipped_details") ⇒ 必红
8) test_rebuild_counts_a_shape_broken_row_separately（tests/test_rebuild.py 新增）
   追加 {"op":"upsert","table":"concepts","row":{"concept_id":"0003"}}（缺 name）
   assert out["skipped_by_reason"]["shape_broken"] == 1                # ①改前 KeyError ⇒ 必红；钉住"不许收窄 except"
9) test_a_rolled_back_experiment_does_not_overwrite_the_previous_log（tests/test_agent_e_run_log.py 新增）
   同一 eid 第二次运行（第一次事务故意失败）之后，断言第一次的日志字节仍在   # ①改前 write_text 覆盖 ⇒ 必红
```

**真机回放（只读）**：R-02 → `D:\Incubator\agentflow\projects\p8c-fermat-shorter-proof`（另有
`p6e-research-from-zero`、`p5-review-t1`）；读数 = "无任何台账行引用的 `out/experiments/*.log` 个数" + "同一
`<eid>.log` 被多行引用" + "日志首行 sha256 与该 `eid` 行的 `code_hash` 是否一致"，命令（只读）
`python -B -c "…glob <ws>/out/experiments/*.log；与 <ws>/data/experiments.json 的 artifact_paths 做差集…"`；
改前实测 = p8c 2 个孤日志且 `0001.log` 与 `0002.log` 逐字节相同，改后要求 = 0。R-06 → **不能直接跑
`agentflow rebuild`（会写盘）**，只读替代 = `python -B D:\Incubator\draft\_probe_c_rebuild_dryrun.py`；
建议样本 `p6e-research-from-zero`。R-05 → `python -B -m agentflow.cli --root <ws> verify` 里 `schema_invalid`
条数（verify 只读）：改前 0，改后仍要求 0。

**不可逆点与防法**：唯一不可逆点是 **`counters.json` 的语义（ID 生命周期）**。防法：本批不动它；若将来要动，
必须先有"ID 空洞可接受/不可接受"的书面裁定，并同时处理 `rebuild` 的 counters 折叠（`:1327-1332`）与"回滚后
重建"的组合，否则会出现"提交后不复用号、重建后又复用号"两套口径。次不可逆点 = `events.jsonl` 的事件形状
（唯一定义处 `Tx._record:427-439`）：R-06 只读事件、不写事件 ⇒ 不触碰。

### 2.7 本文件"不做"的部分

1. 不动 `_atomic_write`（`:761-830`）的临时名/重试/异常类型（F-3 已修且有测试）；不动 `LOCK_ORDER`（`:66-90`）
   与 `Tx` 的取锁/释放语义（`:895-908`、`finally:994-1008`）。
2. 不动 `_merge_counters_for_commit`（`:651-759`）的 `max(盘上,缓存)` 与双向痕迹（R6-AN-1 / R7-AN-1 已有 4 条
   读数）；不动 `rebuild` 的 counters 折叠规则（`:1327-1332`）与"先事件后快照"的提交顺序（`:913-929`）。
3. 不动 `_snapshot_keys`/`snapshot_ahead`/`snapshot_rows_not_in_log`（`:1171-1195`、`:1290-1295`，R3-3 口径不变，
   R-06 的明细是**新增**键）；不动 `init`/`_foreign_dir_guard_should_refuse`/`library_path`（`:486/562/1414`）；
   不在 store 侧兜 schema 的 `TypeError`（只做诊断改善会掩盖数据问题）。

---

## §3 结论汇总：不可行 / 高风险项（必须先看见）

| 编号 | 拟议改动 | 判定 | 决定性证据 |
|---|---|---|---|
| R-02 | "事务回滚时推进计数器"（`draft/45` §1.1①） | **不可行** | `tests/test_store_concurrency.py:229/234`、`:164` 三条断言钉住反面；`search_tools.py:1085`+`store.py:995-998`+`store.py:350-358` 三处 docstring 同侧；`rebuild` 的 counters 折叠（`:1327-1332`）使该承诺在重建后失效。真凶在 `agent_e` 的日志落盘（`run_experiment.py:171-174` + `_support.py:691`），store 侧 0 改动 |
| R-05 | "改 `schema.py:2432`" | **必要但不充分** | 实测 `validate_table` 在 `:2722` 先调 `obj.validate()`；7 处行级内联件（`:374/418/577/659/669-672/811/1672`，覆盖 9 个 set 字段）先抛 `TypeError`；`verify.py:158` 也只吞 `ValueError` |
| R-06 | "把 `except Exception` 改窄" | **不可行** | `S.row_from_dict` 对缺参行抛 `TypeError`（`tools/table_tools.py:121-123` 逐字承认）；收窄后整次 rebuild 崩，比静默丢更糟。可行面 = 加 `skipped_details`/`skipped_by_reason` + 改 `cli.py:334` |
| E-09 | "`LIT_MATCH_STATUSES` 增 `none`"（`draft/45` §1.1③） | **不可行** | `schema.py:113-121` 逐字否证（两个 `matched` 是两问、第三态故意不同名、"折成一个字段会让两件事同形——而这两件事在真机里各自都发生过一次"）；`specs/a.py:152` 的 `none` 属**文内定位**那一问；真机三档零产出 |
| EE-06 | "把 `status` 加进必填集" | **不可行** | 实测 `PASS 1322 → 1270`（**52 份 documents.json 当场变红**）；`docs/SCHEMA-MIGRATION-PROPOSAL-claims.md` 是同题未实施提案，§3.2/§3.3 给出同一结论与分段建议 |
| F-01 | "`Statement`/`claims`/`Relation` 各加一处由 `derive_grade` 计算的 `grade`" | **半不可行** | `derive_grade` 入参是五元位；`claimanatomy.py`/`doc_tools.py` 全文 `bits` **0 命中**；`evidencebits.py:176-181` 与 `schema.py:1611` 逐字禁止等级落盘；只在 `to_dict()` 加键会被 `table_tools.py:114-117` 在回写时拒掉 |
| P-07 | "在 `schema` 里自动补 disclaimer" | **高风险（方向反了）** | `doc_tools.py:1115-1118` 逐字："让闸门顺手把违规项改好…正是本框架最忌讳的静默修复"；可行落点 = `normalize_claims` + `_autofilled` 留痕 |
| EE-07 | "把 `evidence_kind` 变成真派生" | **牵动接口（≥6 文件 + 快照重冻）** | 实测 `evidence_kind="proof"` 且 `bits={}` 的行今天**合法**（6 行就是）⇒ `schema.py:1604-1605` 的"派生只读视图"是**纯注释、无判据**；去掉它要动 `specs/b.py:131`（→ 提示词 → golden）与 `closing.py:1440/1450/1854/1877` |

**必做的前置（跨条目）**：F-05 待办队列（P-06/P-08 的"降级 + 待办"没有接手人就是空转）；
`statements` 指向 `experiments` 的字段（`closing.py:1454-1464` 逐字说 ②④ 两条今天只能 `counted_only`）。
