# 97 · 逐文件改动面（S1p 消化读数 / S1o 依赖链 / S1q 正文重建 + B 的 `deps`）

> **进度（2026-10-09）**：**S1p 已落地** —— 机器侧 `ef88511`（`closing.LEG_CHECK_KINDS` +
> `_leg_reading` 新支 + 判据 5 条）、M 侧 `0de66bf`（档名进 M 的档位清单，真身与镜像同改，
> `PROMPT_VERSION` p53→p54）。本节其余（S1r / S1o / S1q）仍是**设计**，未施工。

口径与设计见 `draft/83` §5.3 的 (3b)(3c)(3d)；本页只回答**动哪些文件的哪些符号、
动完长什么样、拿什么证明没动坏**。每条都带**真实依据**（现场查到的文件/行/符号），
没查到的**逐条标出"待核"**，不写成已核。

> 现场核实时间：2026-10-09。行号只作"人读时去找"的线索（锚点纪律 A：行号会漂），
> 判据一律打在**符号名**上。

## §0 三条已核实的现场事实（后面每一节都靠它们）

| # | 事实 | 依据（现场读数） |
|---|---|---|
| F1 | **C 的动作表真身在 `src/agentflow/specs/c.py` 的 `ACTIONS: tuple[ActionSpec, ...]`**，实现是 `src/agentflow/agent_c/<动作>.py` 一个动作一个文件，最后在 `agent_c/core.py:1132` 用 `class AgentC(_Hottest, _Paths, _Cold, _Gaps, _Neighbors, _RelationsBetween, _Contradictions, _StructuralDuplicates, _Handle, _Core)` 拼起来 | `specs/c.py` 的 `ACTIONS` 逐条 `ActionSpec("C", "<名>", …, handler_name="<名>")`；`agent_c/` 目录实测 10 个动作文件 + `core.py`/`_support.py`/`handle.py` |
| F2 | **`dependencies.used_by` 接受 `stmt:` 形态**：字段注释写 `"doc:0001#claim-3" / "relation:0007" / "experiment:0002"`，而 `schema.py` 的 `Dependency` 文档紧接着写"`used_by` → 本表的 `stmt_id` 是自然延伸"；`validate()` 只要求 `used_by` 非空 + `kind`/`status` 在词表内 | `schema.py` 的 `Dependency.used_by` 注释与 `validate()` 那两行；词表 `DEP_KINDS = (theorem, definition, lemma, proposition, dataset, experiment, prior_art)`、`DEP_STATUSES = [closed, dangling, external_unavailable, refuted, disputed]`（现算） |
| F3 | **`capabilities` 的动作从 `specs/` 派生**（`from . import specs as _specs`），并要求 `handler_name` 在 `agent_x` 里真的存在；有 `unmapped_actions()` 这个读数 | `capabilities.py` 头部注释"动作来自真实代码：`ActionSpec.handler_name` 必须是 `agent_x.py` 里真的存在"、`from . import specs as _specs`、`def unmapped_actions()` |

**待核两处**（写进 §5，施工第一步先核）：
- **V1（已核，2026-10-09）**：`src/agentflow/specs/c.py` **确实登记在 `.noai-paths`**
  （`[category: auth-audit]` 角色 C 的声明真身，与 `specs/a.py`/`specs/b.py`/`specs/m.py` 同一档）
  ⇒ §1 的改动走**"业主授权先改后审"**的流程：改完跑 `noai_gate --git --since <ref>`、
  把 `requires_human(required_approvals=2)` 的读数如实记进提交信息、**不跑 `--approve`**。
- **V2**：C 的动作加进 `ACTIONS` 之后，**哪些计数合同会跟着动**（`docs/` 的角色动作数、`role_spec` 相关快照、`tests/golden/agent_surface_snapshot`）——实测命令见 §5。

## §1 `src/agentflow/specs/c.py`（**禁改区，按业主 2026-10-09 授权先改后审**）

- **加一条 `ActionSpec`**（放在 `ACTIONS` 末尾，紧跟现有的 `structural_duplicates`）：

```python
ActionSpec(
    "C", "proof_chain",
    "一条成果的最短证明依赖链（走到根：文献，或无前提的自证定理）",
    _obj({"target": _S,                      # stmt:0007 / exp:0004 / doc:0001#claim-2
          "max_depth": {**_I, "minimum": 1},
          "k": {**_I, "minimum": 1},
          "weights": _OBJ},                  # 可选：按 kind 给代价（缺省按跳数）
         ("target",)),
    "AnalysisReport（内存对象；与 C 其余动作同形）",
    side_effect="read", handler_name="proof_chain",
),
```

- **依据（真实）**：`specs/c.py` 里现有 8 条 `ActionSpec` 的写法逐条照抄形状（`_obj(...)` 必填元组、
  `side_effect="read"`、`handler_name=<动作名>`）；`_S`/`_I`/`_OBJ` 都在该文件顶部的导入里。
- **判据**：`capabilities.unmapped_actions()` 不含 `("C","proof_chain")`（实现真的在）；
  `AgentRegistry` 装配成功（`handler_name` 解析得到）。

## §2 `src/agentflow/agent_c/proof_chain.py`（**新文件**）

- **实现体**：`class _ProofChain:` + `def proof_chain(self, target, *, max_depth=4, k=1, weights=None) -> dict`，
  与 `agent_c/hottest.py` 同形（`_Hottest.hottest(...)` 那一档的类/方法命名）。
- **读**（只读，零模型调用）：`dependencies`（有向边）、`statements`（`evidence_kind`/`proof_text`/`quote_verified`）、
  `experiments`（proof 行）、`literature`（叶子）。
- **算法**：从 `target` 沿 `used_by → source_*` 走；缺省 BFS（最少跳数），`weights` 给了就 Dijkstra；
  根 = `lit:` 行 或 **无前提自证定理**（该 `stmt:` 没有任何 `dependencies` 行 + `evidence_kind="proof"`
  + 检查器 verified）；环报 `cycle` 跳过；`dangling` 边不算到根；超 `max_depth` ⇒ `truncated=True`。
- **返回**：见 `draft/83` §5.3(3b) 的 `preconditions` 三态 + (3d) 的 `chains`。
- **依据（真实）**：`agent_c/` 下 8 个动作文件都是"一个文件一个 `_Xxx` mixin、方法名 = 动作名"这一形态
  （实测文件名 `hottest.py` / `paths.py` / `gaps.py` / `contradictions.py` / `cold.py` / `neighbors.py` /
  `relations_between.py` / `structural_duplicates.py`）；`_support.py` 里有 `AnalysisReport`/`S`/`Store` 等共用名
  （`core.py` 的导入行逐个列出了它们）。
- **判据**：`test_proof_chain_*`（新文件，见 §6）：三跳链取最短 / 无前提自证定理作根 / 环 / "没有边且无 proof 证据"不许当根 / 悬空边不算根 / 依赖表读不成 ⇒ `checked=False`。

## §3 `src/agentflow/agent_c/core.py`（**一处 import + 一处基类**）

- 第 9–17 行那一片 import 里加 `from .proof_chain import _ProofChain`；
- 第 1132 行的 `class AgentC(...)` 基类列表里加 `_ProofChain`（放在 `_StructuralDuplicates` 之后）。
- **依据（真实）**：`core.py:1132` 的基类列表逐字是
  `AgentC(_Hottest, _Paths, _Cold, _Gaps, _Neighbors, _RelationsBetween, _Contradictions, _StructuralDuplicates, _Handle, _Core)`；
  `core.py:9-17` 是那九个 mixin 的 import。
- **判据**：`AgentC` 上 `hasattr(AgentC, "proof_chain")`；`capabilities.unmapped_actions()` 空。

## §4 `src/agentflow/specs/b.py` + `src/agentflow/agent_b/register_statement.py`（**禁改区，按授权**）

- **`specs/b.py`**：`register_statement` 那条 `ActionSpec` 的 `params` 里加一格 `deps`
  （`{"type": "array", "items": {"type": "object", …}}`，**可选**）；描述里写明"给了就逐条落
  `dependencies`；没给 ⇒ 依赖那一格 `unknown`（不许落成'无前提'）"。
- **`agent_b/register_statement.py`**：同笔写 `dependencies` 行 —— 每条 `deps` 落一行
  `{"dep_id": …, "used_by": "stmt:<本行 stmt_id>", "kind": <DEP_KINDS 之一>,
  "label": …, "source_lit_id"/"source_experiment_id"/"source_doc_id"/"source_claim_id": …,
  "status": "closed"|"dangling"}`；**没给 `deps` ⇒ 一行都不落**，并在返回值里给
  `deps_written: 0` / `deps_state: "unknown"`（三态）。
- **依据（真实）**：`specs/b.py` 的 `register_statement` 注释自己写着"**本文件是 FC-27 禁改区**"，
  且它的"第四条必填"逐档写了 `own_result` 的出处（`doc_id`/`line_range`）—— 与本节同一条口径；
  `Dependency` 的字段表（`dep_id/used_by/kind/label/status/source_lit_id/source_experiment_id/page_range/
  quote/status_reason/created_at/source_doc_id/source_claim_id/created_by`）是现算的。
- **判据**：正控 —— 给了 `deps` 的 `own_result` 命题 ⇒ `dependencies` 行数 = `len(deps)`，
  `used_by` 指向本行 `stmt_id`；负控 —— 不给 `deps` ⇒ **0 行**且 `deps_state="unknown"`
  （不许变成"无前提"）；反真空 —— `deps` 指向不存在的号 ⇒ 拒（与 `check_citations` 同一条纪律）。

## §5 **定义也入库**（业主 2026-10-09：「新概念的定义也是依赖项，是特殊形式的"定理"，
也入库。这样 C 的职责面就统一了」）—— 逐文件见下

- **`specs/b.py`**：`register_statement` 的**描述文字**里加一句"新概念的定义也走这个动作
  （`kind` 写'定义'），并把它的依赖（它建立在哪些概念/定义上）写进 `deps`"。
  **`params` 不用加任何一格**：`kind` 已经是自由字符串（见下面的依据）。
- **`agent_b/register_statement.py`**：无需改判据分支 —— 加一条**自检**：
  `kind == "定义"` 时**允许** `proof_text` 为"（定义，无需证明）"这类说明、
  并**要求** `deps` 里至少写清它用到的上游（没有上游=原始定义 ⇒ 落 `deps_state="primitive"`）。
- **依据（真实，2026-10-09 现算）**：`schema.py` 里 `Statement.kind` 的注释逐字写着
  「`kind`（theorem / lemma / …）：**刻意不是受控词表**。理由：它不参与任何判据分支
  （分支只看 `origin` / `status` / `evidence_kind` / `bits`）」⇒ 写"定义"不需要改 schema；
  `CLAIM_KINDS` 现算 = `('定义','定理','命题','引理','推论','例','注','反例')`（稿件侧本来就有这一档）；
  `DEP_KINDS` 现算含 `"definition"`（边上能说"这条定理用到那个定义"）。
- **待核 V3**：`Statement.validate()` 对 `kind="定义"` 的行**在 `proof_text` / `quote_verified`
  上有没有硬要求**（若有，定义那一档要给出合规的写法，或按人裁放宽）——施工第一步读一遍
  `Statement.validate()` 并把读数记进提交信息。
- **判据（S1p/S1o 各加一条）**：
  - S1p：一份手稿过审后，它**引入的新定义**也进了库（`kind="定义"` 的 `statements` 行）——
    与"成果逐条入库"同一档读数（`reviewed_then_digested_rows` 的 `detail` 里分列
    "定理 N 条 / 定义 M 条"）；
  - S1o：负控④ —— 一条 `kind="定义"` 且**没有任何 `dependencies` 行**的行**可以当根**
    （原始定义），而一条 `kind="定理"` 且没有边、又没有 proof 证据的行**不许当根**（依赖没写）。

## §6 计数合同与"待核"清单（施工第一步跑这三条命令）

```powershell
# V1：C 的声明真身是不是禁改区（决定走不走"授权先改后审"）
Select-String -Path .noai-paths -Pattern 'specs/(a|b|c)\.py'

# V2：加了 C 的一个动作之后，哪些计数/快照跟着动（改前跑一次、改后跑一次，对比）
python -B -m pytest tests/test_capabilities.py tests/test_agent_spec_reconciliation.py `
  tests/test_role_specs.py tests/test_agent_surface_snapshot.py -q

# V3：C 的动作面在文档与契约里有没有第二处计数
Select-String -Path docs\*.md,agentflow\docs\*.md -Pattern 'C 的[0-9]+ 个动作|actions_for\("C"\)'
```

- **已知会动的地方（依据：`capabilities.py` 里 `unmapped_actions()` 与 `action_axes()` 的报数口径）**：
  `capabilities` 的"覆盖 189 / 声明 189 个 property，59 个动作"这句导入期读数**会变**
  （每跑一次 pytest 都能在 stderr 看到它）——加一条动作 ⇒ 动作数与 property 覆盖数各 +1；
- **不准动的地方**：`schema.py` 一字不改（`dependencies` 的字段够用，F2 已核）；
  `tests/golden/*` 由人重冻（H-1）。

## §7 判据与测试文件（逐条对应到文件）

| 批次 | 新/改判据文件 | 判什么 |
|---|---|---|
| **S1p** | `tests/test_a_manuscript_is_digested_after_review.py`（新） | 新受控档 `reviewed_then_digested_rows`：审过+已消化 ⇒ 计 1；审过未消化 ⇒ 0 **且**报"先去 B 登记"；没审 ⇒ 不进这一档；读不成 ⇒ `unknown` |
| **S1o** | `tests/test_the_shortest_dependency_chain.py`（新） | `proof_chain` 六条（见 §2 判据）；并**改** `tests/test_internal_citations.py`/`tests/test_a_document_may_cite_our_own_statement.py` **不动**（那两条链是引文口径，与本批无关） |
| **S1q** | `tests/test_the_paper_rebuilds_from_the_ledger.py`（新） | 正控：搬进正文的定理有逐字片段 + `stmt:` 引用 + 一条"台账号 → 论文号"映射；负控①没引用 ⇒ 红；负控②`\ref` 悬空 / 两个 `stmt:` 映射到同一个论文号 ⇒ 红；负控③论文里 `doc:` ⇒ 红 |

**落点（S1q 的映射）**：写进 `dependencies`（`kind="theorem"`、`label`=论文号、`used_by`=论文里那一处断言）
—— **依据 F2**（`used_by` 接 `stmt:`/文档号形态，`label` 本来就是"人话标签"那一格）；
退路 `out/paper/THEOREM-MAP.json`（不动 schema）。

## §8 这一页**不动**的东西（写清楚，免得施工时"顺手"）

- `schema.py` / `store.py` / `projects.py` / `runflow.py`：零改动（硬约束）；
- `closing.PAPER_LEDGER_PREFIXES = ("stmt:", "exp:", "rel:")`：论文承载本轮结果那一维不动
  （新档 `reviewed_then_digested_rows` 是**验收表**的受控档，不是这一维）；
- `tests/golden/*`：由人重冻；
- 两阶段引用的口径（`doc:` 在论文里拒、手稿里可互引）：本批只**用**它，不重开。

## §9 口径细化：上一版里那些"模糊的地方"逐条定死（业主 2026-10-09：draft 有诸多缺陷与模糊）

上一版有十处是"说到了但没定死"。这一节逐条给出**可施工的定义**；凡是**我还没核到**的，
写"待核"并给出**核法**，不含糊过去。

### 9.1 concept 融进 statement（业主逐字裁定）

> 「concept融进statement，只是它的证明过程栏直接写concept」

**定死**：一条**新概念/定义**就是一个 `statements` 行，三格取值固定：

| 字段 | 取值 | 依据/说明 |
|---|---|---|
| `kind` | `"concept"`（英文小写；稿件侧 `CLAIM_KINDS` 的"定义"是**文档断言**的分类，不是这里的取值） | `Statement.kind` 刻意不是受控词表（依据见 §5），所以这是合法取值 |
| `proof_text` | **逐字 `"concept"`** | 业主指定的写法：概念没有证明过程，这一格直接写 concept（**不写空、不写"（定义，无需证明）"**） |
| `evidence_kind` | `"heuristic"`（缺省） | 待核 **V4**：`EVIDENCE_KINDS = (proof, cross_check, heuristic)` 里只有这三个；concept 既不是 proof 也不是 cross_check ⇒ 只能 `heuristic`。**核法**：读 `Statement.validate()` 看 `kind="concept"` 时 `evidence_kind`/`quote_verified` 有没有硬要求；若有，按人裁的缺省写法落，并把读数记进提交信息 |
| `origin` | `"own_result"`（我方引入的概念） | 与 B 的"第四条必填"一致：`own_result` 要 `doc_id` 或 `line_range` 作出处 |
| `derived_from` / `deps` | 它建立在上游哪些概念/定义/文献上（没有上游=原始概念） | §5 的那条 |

**两张图的关系（这一条把上一版的"待裁缺口"解掉）**：`concepts` 表是**关系图**的节点
（C 的 `hottest`/`gaps`/`contradictions` 在它和 `relations` 上跑），`statements` 里
`kind="concept"` 的行是**依赖图**的节点。**同一个概念在两边的号对齐**：
`Concept.concept_id` 与 `Statement.stmt_id` **取同一个值**（B 登记 concept 时先分配
`stmt_id`，再用它作 `concept_id`）——这样**不用加字段、不用动 schema**，
两张图靠**号**就能对上（比"按名字对"硬得多）。
`Concept.name` / `Concept.definition` 与 `Statement.label` / `Statement.statement_full`
是同一件事的两个视图：名字对名字、定义对定义。**判据**：B 登记一条 concept 之后，
`concepts` 与 `statements` 各有一行、**两个号相等**、`proof_text == "concept"`。

**要不要把 `concepts` 表整个并掉（真正"融进"）**：那是**迁移**（`schema.py` 在 FC-27 的
`schema-migration` 档，且盘上有 59 个工作区的历史数据）⇒ **本页不擅自做**，
作为待裁题交上去：**(甲)** 保留两张表、用同号对齐（本页实现的那条，零迁移）；
**(乙)** 把 `concepts` 并进 `statements`（要人写迁移 + 人审）。两条的**读数面一样**，
差别只在"历史数据要不要搬"。

### 9.2 `proof_chain` 的输入输出逐格定死

```python
proof_chain(target: str, *, max_depth: int = 4, k: int = 1,
            weights: Mapping[str, float] | None = None) -> dict
```

- **`target` 的合法形态**（不合法 ⇒ `checked=False` + 说清，不当"没有这条"）：
  `stmt:<4位>`（含 `kind="concept"` 的行）/ `exp:<4位>` / `doc:<稿件>#<断言>@<哈希>`
  （先译成它登记的那条 `stmt:`；译不出来 ⇒ 报 `target_not_registered`）。
- **节点集合**：`statements` 全部行（定理/定义/concept/引理…）+ `experiments` + `literature`。
- **边**：`dependencies` 行，方向 `used_by`（使用点）→ `source_*`（被依赖项）。
  只走 `status ∈ {closed, external_unavailable}`；`dangling` 记读数不算到根；
  `refuted` / `disputed` 记读数且**照走**（它们仍是"要重建的环节"，只是要在 `why` 里点名）。
- **边的权重（缺省表，可被 `weights` 覆盖）**：`lit` 0、`definition`/`concept` 1、
  `theorem`/`lemma`/`proposition` 1、`experiment` 3、`dataset` 2、`prior_art` 2。
  （理由：重建时"重跑一个实验"最贵、引用一篇真论文最便宜。）
- **"最短"的定义**：`weights` 为空按**跳数**（BFS）；给了按**权重和**（Dijkstra）。
  **并列时**（同长度）按 `hops` 里节点号的字典序，取前 `k` 条；并列的条数报在
  `chains_total`（不只给 k 条就假装只有 k 条）。
- **`hops` 的元素形态**：`{"node": "stmt:0003", "via_dep_id": "0007", "kind": "theorem",
  "status": "closed", "why": ""}` —— 每一跳都带**它是哪条依赖边**（`via_dep_id`），
  于是"这条链凭什么"可逐跳复算。
- **`max_depth`**：**从 target 出发的边数**（含到根的那一跳）；`max_depth=4` ⇒ 最多 4 条边。
  超了就 `truncated=True`（并且 `chains` 里给出**已走到的前缀**，不返回空）。
- **`preconditions` 三态怎么算**（逐键给判据，不许含糊）：

  | 键 | `yes` | `no` | `unknown` |
  |---|---|---|---|
  | `results_registered` | 目标那条成果在 `statements` 里有行（`own_result`） | 手稿在册、但它的 claims 一条也没对回 `statements` | 手稿/台账读不成 |
  | `document_reviewed` | 那条 `documents` 行 `status ∈ {accepted, revised}` 且签名钉着现行版（`reviewed_current_rows` 同一判据） | 手稿存在但没审/签名过期 | 签名台账读不成 |
  | `dependency_edges` | 目标行至少有 1 条 `dependencies` 边，或它按 §9.3 是"根" | 一条边都没有、又不是根 | `dependencies` 读不成 |

### 9.3 "根"的判定（把 §5 那条按 kind 分档写死）

```python
def _is_root(stmt_row, deps_of) -> tuple[bool, str]:
    if stmt_row["kind"] == "concept":                 return True,  "原始概念（无前提）"
    if not deps_of(stmt_row["stmt_id"]):              # 一条边都没有
        if stmt_row["evidence_kind"] == "proof" and _verified(stmt_row):
            return True, "无前提自证定理"
        return False, "依赖没写（没有边，也没有 proof 证据）"   # ⇒ unknown，不是根
    return False, ""
```

（`lit:` 行的根不用这个函数：`literature` 表里在册即根。）

### 9.4 `reviewed_then_digested_rows` 的确切算法（S1p）

- **分子**：`status ∈ {accepted, revised}` 的 `documents` 行中，满足"**它的断言至少有一条
  对回了 `kind != "concept"` 的 `own_result` `statements` 行**"的份数；
- **分母/阈值**：受控档按"**越多越好**、缺省阈值 = 1"（与 `reviewed_current_rows` 同族）；
- **`detail` 里必须分列**：`{"theorems": N, "concepts": M, "docs_reviewed": D,
  "docs_digested": X}` —— "定义也入库"这件事要能从读数里看出来（§5）；
- **未消化时给出路**（这一档红的时候的文案）："手稿 X 过了审，但它的成果没有逐条登记
  ⇒ 先派 B（`register_statement`，`deps` 要一起给）"。

### 9.5 S1q 的映射落 `dependencies`：字段组合定死

一条被搬进论文的定理 = 一行 `dependencies`：

| 字段 | 值 |
|---|---|
| `dep_id` | 由 `store.alloc_id` 分配（**不许手写**） |
| `used_by` | **论文里那一处断言**：`doc:<论文 document 号>#<claim_id>`（S1q 的"论文"也是 `documents` 行） |
| `kind` | 被搬那条的 `kind`（`theorem`/`lemma`/…；`concept` 也照写） |
| `label` | **论文号**：`"1.5"`（人话标签那一格，与 `\ref` 的自定义编号一致） |
| `source_doc_id` / `source_claim_id` | 被搬那条 `statements` 行的出处（`doc_id` / `claim_id`）—— 于是"从哪份手稿的哪条断言来的"可复算 |
| `status` | `closed`（搬成功了）/ `dangling`（被搬那条找不到了） |

**判据（改前必红）**：搬一条定理进正文但**不落这一行** ⇒ `\ref` 与映射对不上；
落两行指向同一个 `label` ⇒ 红（两个不同定理不许共用一个论文号）。

### 9.6 上一版其余几处模糊的收口

| 上一版的模糊处 | 定死 |
|---|---|
| `specs/c.py` 里 `weights` 的参数形态只写 `_OBJ` | `{"type":"object","additionalProperties":{"type":"number"}}`，键 = `DEP_KINDS` 的取值 + `"lit"`（多一个键 ⇒ `param_error`，不许静默忽略） |
| S1p 的判据文件里"审过未消化 ⇒ 0" | 见 §9.4 的分子/分母/出路三段 |
| §2 说"与 `hottest` 同形" | 具体到：文件 `agent_c/proof_chain.py`、类 `_ProofChain`、方法名 `proof_chain`、返回 `AnalysisReport`（C 其余动作的同一形）——`capabilities.unmapped_actions()` 是它的接线判据 |
| §6 的 V2 只说"哪些计数会动" | 改前/改后各跑一次并把两次数记进提交信息；**已知会动**：`capabilities` 的导入期读数（动作数 +1）；**待测**：`docs/` 角色动作数、`tests/golden/agent_surface_snapshot`（金标由人重冻） |
| §5 的"待核 V3" | 收窄成 V4（见 §9.1 表的 `evidence_kind` 那一行）：核 `Statement.validate()` 对 `kind="concept"` 的要求，并把缺省写法定下来 |

## §10 裁定升级：`concepts` **真并进** `statements`，`proof_text` 写**良定义性证明**（业主 2026-10-09）

业主逐字：

> 「concept表真并进statements。由于你用"类型"标记了concept的身份，proof里就证这个概念
> 为什么是良定义的」

⇒ 两件事：**(1)** 走 §9.1 的**乙档**（并表，不是"同号对齐"）；**(2)** §9.1 里那条
"`proof_text` 逐字写 `concept`"**作废** —— 身份由 `kind="concept"` 标记之后，
`proof_text` 这一栏空出来干**正事**：**证这个概念为什么是良定义的**
（不依赖选择、无歧义、存在性/非空、与既有定义不冲突）。

### 10.1 `kind="concept"` 的那些行，五格取值（**取代 §9.1 那张表**）

| 字段 | 取值 | 说明 |
|---|---|---|
| `kind` | `"concept"` | **身份标记**（`Statement.kind` 不是受控词表 ⇒ 合法，依据见 §5） |
| `proof_text` | **良定义性证明**（为什么这个概念是良定义的）；**原始概念**写受控标记 `"concept:primitive"` | 这是本次升级的核心：证明栏不再占位，而是承担"良定义"这道义务 |
| `evidence_kind` | 按**证明的强度**取：机器核过 ⇒ `proof`；交叉核对 ⇒ `cross_check`；只有论证 ⇒ `heuristic` | `EVIDENCE_KINDS = (proof, cross_check, heuristic)`（现算） |
| `quote_verified` | 三态照旧（`True`/`False`/`None` + `quote_reason`） | "还没查"与"查过不一致"分得开 |
| `origin` / `derived_from` / `deps` | 与 §5/§9.1 同 | `own_result` + 出处（`doc_id`/`line_range`）+ 它建立在哪些上游上 |

**三态纪律落在这一格上**：`proof_text` 为空 ⇒ **不是"原始概念"**，是"良定义性证明还没写"
（`unknown`）。"原始概念"必须**显式**写 `concept:primitive` —— 空与原始分得开，
这是本仓最忌折平的那一类。

### 10.2 于是"根"的判定改成**按义务**判（取代 §9.3）

```python
def _is_root(row, deps_of) -> tuple[bool, str]:
    if deps_of(row["stmt_id"]):            # 有依赖边 ⇒ 不是根
        return False, ""
    if row["kind"] == "concept":
        if row["proof_text"] == "concept:primitive":
            return True, "原始概念（良定义性义务为空，显式标记）"
        if row["proof_text"].strip() and row["evidence_kind"] in EVIDENCE_KINDS:
            return True, "概念：良定义性证明在"
        return False, "良定义性证明没写（不是原始概念）"      # ⇒ unknown
    if row["evidence_kind"] == "proof" and _verified(row):
        return True, "无前提自证定理"
    return False, "依赖没写（没有边，也没有 proof 证据）"
```

（`lit:` 在册即根，不走这个函数；C 的 `preconditions.results_registered` 对 concept
目标的"成果"含义 = **这个概念行 + 它的良定义性证明**。）

### 10.3 并表的迁移设计（**FC-27 `schema-migration` 档，要人审 2 名**）

- **`schema.py`**：`SCHEMA_VERSION` 由 **1 → 2**（现算：`S.SCHEMA_VERSION == 1`）；
  `TABLES` 去掉 `concepts`；`relations.concept_ids` 的语义改成"指向 `statements` 的 `stmt_id`"
  （字段名不动，**语义在迁移说明里写明**）。
- **`store.py` 的 `rebuild`**：重放旧事件时，`concepts` 的 upsert 折成 `statements` 的 upsert：
  `concept_id → stmt_id`、`name → label`、`definition → statement_full`、
  `kind="concept"`、`origin="own_result"`、**`proof_text="concept:primitive"`**（历史行没有
  良定义性证明 ⇒ **不许编一段**，落受控标记）、`related_concepts` **丢掉**（那是 `relations`
  的职责）。
- **影响面（现算：16 个文件提到 `"concepts"`）**：`cli.py` / `demo.py` / `extract.py` /
  `faculty_checks.py` / `llm.py` / `pipeline.py` / `projects.py` / `reviewaccept.py` /
  `schema.py` / `store.py` / `verify.py` / `agent_b/{core,decide_structural_duplicate,
  resolve_structural_duplicate,run_once}.py` / `agent_c/__main__.py`（另有测试与 WebUI 读侧）。
  每处都要按"读 `concepts` ⇒ 改读 `statements` 且 `kind="concept"`"逐个过一遍。
- **过渡期读法（S1r 未审期间的桥）**：`proof_chain` 与 S1p 的读数**同时看两处**（
  `statements` 里 `kind="concept"` 的行 + 遗留 `concepts` 表的行），按**同号**合并，
  并在读数里写明 `concept_source: "statements" | "legacy_table" | "both"` ——
  迁移落地后这一格自然变成 `"statements"`（**读数不减、口径可见**）。
- **不许做的事**：① 不许给迁移来的行编良定义性证明；② 不许在迁移里丢 `relations`
  （它不在本次处置面内）；③ 不许把 `concept:primitive` 当"查过了没问题"（它是
  "原始概念"这一档，不是"证明通过"）。

### 10.4 判据（S1r，改前必红）

| 档 | 判据 |
|---|---|
| 正控 | 迁移后：`concepts` 不在 `TABLES` 里、`SCHEMA_VERSION == 2`；每条旧 concept 行都有一条 `kind="concept"` 的 `statements` 行，**号相等**、`statement_full` 逐字等于旧 `definition`、`proof_text == "concept:primitive"` |
| 负控① | 迁移行的 `proof_text` 里出现"证明/证毕/Proof"这类字样 ⇒ 红（**不许编证明**） |
| 负控② | `relations.concept_ids` 里有一个号在 `statements` 里找不到 ⇒ 红（悬空） |
| 反真空 | `concepts` 表在盘上**读不成**（旧工作区）⇒ 报 `checked=False` + 说清，不许当成"没有概念" |
| 三态 | 一条 `kind="concept"` 而 `proof_text` 为空 ⇒ **既不是根、也不算"良定义"**：`proof_chain` 对它报"良定义性证明没写" |

### 10.5 批次顺序（被这一次裁定改了一处）

**S1r（并表迁移，要人审）→ S1p（消化读数）→ S1o（依赖链）→ S1q（正文重建）**：
S1p/S1o 读的就是 `statements`（并表之后的唯一落点）⇒ 迁移必须在它们**之前**，
否则两批要写两遍。S1r 未过审期间，S1p/S1o 按 §10.3 的**过渡期读法**写（两处同号合并），
于是"迁移卡在人审"不会让后面三批停摆。


