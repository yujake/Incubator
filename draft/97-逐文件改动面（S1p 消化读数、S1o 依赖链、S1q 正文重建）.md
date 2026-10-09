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

> **业主复审（2026-10-09）**：「要我审的都看过了，感觉可以」—— 指本页 §1/§4 那两处禁改区
> 改动（`specs/c.py` 与 `specs/b.py` 的**设计**）与并表设计。**如实记两条边界**：
> ① 这句是**口头复审通过**，`.noai-approvals.json` **一个字节没动**（正式台账要 2 名
> reviewer 的登记，是人的动作）⇒ `noai_gate` 仍会报 `requires_human`，**那不是"没通过"，
> 是"台账没登记"**；② 复审通过的是**设计**，`specs/c.py` 的 `proof_chain` 与 `specs/b.py`
> 的 `deps` **本页写作时尚未施工**（S1o/S1r 还没做），所以"感觉可以"不改变施工纪律：
> 仍然一次一批、每批带读数与偏差。

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

### 10.3b **只读预演的真实读数**（`temp/_s1r_rehearsal.py`，2026-10-09，59 个工作区全扫）

| 读数 | 值 |
|---|---|
| 有 `concepts` 行的工作区 | **28**（`projects/` 下扫到的全部工作区） |
| `concepts` 行总数 | **2233**（按折叠规则全部可折：`folio=2233`） |
| `relations` 行 | 1752 |
| `relations.concept_ids` 悬空 | **0**（关系里的号都在册 —— 这一条干净） |
| 名字为空 | 0 |
| **定义为空** | **94 条**（分布在 `p6c`/`p6e` 等"从零研究"工作区） |
| **号与既有 `statements` 行冲突** | 有（`p6e`/`p6g`/`p6h` 的 `concept 0000`/`0001` …） |
| 概念最多的 5 个工作区 | `p7b-open-questions` 294、`p6c-research-from-zero` 294、`p7-open-questions` 156、`p8b-fermat-shorter-proof` 144、`p8g-fermat-shorter-proof` 143 |
| **边界问题合计** | **116 条** |

⇒ 迁移前必须先裁**两条**（在设计里定死之前不许动 schema）：

- **待裁 A（94 条空定义）**：折出来的 `statement_full` 会是空的。三条候选：
  **(甲)** 照折、`statement_full=""`，并在行里落一个受控读数（`quote_reason` 或 `notes` 写
  "迁移自 concepts：原定义为空"）—— 不许编定义；**(乙)** 这些行**不折**，留在 legacy 表里
  等人工补定义；**(丙)** 折但把该工作区标成"迁移不完整"（读数里可见）。**建议甲**。
- **待裁 B（号冲突）**：`concept_id` 与既有 `stmt_id` 撞号时 **(甲)** 迁移报错、人工处理该工作区；
  **(乙)** 给冲突的概念**重新分配号**（于是 `relations.concept_ids` 要一起改 —— 1752 行里那几条）。
  **建议乙**（自动化程度高），但要在迁移里把"改过哪些号"逐条落账。

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

## §11 业主 2026-10-09 新裁：B 的写入全走秘书 + 五元状态映射 + 证明完善协作链 + D6/D8/D9

### 11.1 **写入侧都是 B 的活，但 B 不直接写**：秘书实际操作"增 / 改 / 查"

业主逐字：

> 「写入侧应该都是B的活，让B的秘书帮它洗格式、拿编号、改表、查重，即B不直接用增工具，
> 秘书实际操作增、改（比如一个定理在两个文献中都有证明，可以互相借鉴把证明写好点；
> 如果证明路径不唯一，可增另一组依赖，实现用二维列表）、查工具，B纯粹负责消化理解。」

⇒ 一句话：**B 交内容，秘书落盘**。四件活各有落点（都能在现有代码里找到同一族的先例）：

| 秘书要做 | 落点（先例） |
|---|---|
| **洗格式** | `Secretary.wash_delegation`（S1g）对派活那一族；这里要一条同族的 `wash_statement`：键名归一 / 顶层折叠 / 去空白，**内容一个字不动** |
| **拿编号** | `store.alloc_id`（唯一分配器）—— 与 D2 同一条口径：同表同分配器 ⇒ 撞号在结构上不可能 |
| **查重** | 规范化去重（`register_conjecture` 的 D13 规范化判重是同一族的先例）：同一条 `statement_full` 不重复建行，`force_new` 才另起 |
| **改表** | 落 `statements` / 概念行（`kind="concept"`）/ `dependencies` 三处一次性写（一笔事务），**B 自己一次写工具都不调** |

**判据（S1o 同批）**：正控 —— B 交一条消化结果 ⇒ 三张表各多一行且号来自 `alloc_id`；
负控 —— 同一个内容交两次 ⇒ 第二次是"重复"读数（不新建行）；**反真空** —— 秘书没装（无 store）
⇒ 明确拒（`secretary_unavailable`），**不许"B 自己写"这条后备路**（那正是业主要去掉的形态）。

**多证明路径（业主指定的形状）**：一条定理**可以有多组依赖**（两个文献各有证明、
或一条更漂亮的路径）。输入是**二维列表**：`deps = [[组1的步骤…], [组2的步骤…]]`
（外层 = 可选路径，内层 = 一条路径上的步骤）。落地两条候选：

- **甲（零 schema 改动）**：一行一条边，用**受控前缀**带组号（`status_reason` 或 `quote` 写
  `group:<n>`），读数按组还原成二维列表；**建议先用甲**（与"schema 零变更"的既有纪律一致）；
- **乙**：`dependencies` 加一列 `path_group`；更干净，但动 `schema-migration`（要人审）。

### 11.2 五元状态在哪张表 —— 已核实，并给出映射与判据

业主问：「再确认一条命题的五元状态是哪张表在维护，要做好映射（如果五元状态里说有证明，
证明应该在B维护的表里可查）」。

**答案（现算，`agentflow/evidencebits.py`）**：

| 五元位 | 谁产生（`BIT_OWNERS`） | 取值（`BIT_STATES`） |
|---|---|---|
| `numeric` | **E** | `pending` / `na` / `failed` / `verified` |
| `proof` | **F** | 同上 |
| `reviewed` | **V** | 同上 |
| `formal` | **E** | 同上 |
| `audited` | **H** | 同上 |

- **落在哪**：`statements.bits` 这一格（**不是**另一张表；等级 `conjecture → strong_conjecture
  → pre_theorem → theorem`（`GRADES`）**不落盘**，由 `evidencebits.derive_grade` 现算）；
  形状与四态纪律的唯一判据来源是 `agentflow/evidencebits.py`（`Statement.validate()` 只转发
  `bits_shape_problems`，不抄第二份口径）。
- **映射要做的判据（业主点名的那一条）**：`bits["proof"] == "verified"` ⇒ 那条证明必须能在
  **B 维护的表**里查到：`statements.proof_text` 非空 **且** 有指向的 proof 证据行
  （`experiments` 里 `evidence_kind="proof"` 且检查器 verified），或一条 `dependencies` 边指出它。
  **改前必红**（这一条今天没有任何判据），判据落 `verify_all`：
  "五元位里说 verified 的那几位，各自都要在对应的表里查得到"——逐位给"去哪张表查"的映射表
  （`numeric`/`formal` → `experiments`；`proof` → `statements.proof_text` + `experiments`；
  `reviewed` → `review_signatures`/`doc-signatures`；`audited` → 签名台账）。

### 11.3 D7 改成**协作链**（不做机器验证）：C → D → F+V → D → B

业主逐字：「D7先不搞机器验证，但做一个协作链：C整理好后交给D整理，D联系F让F和V配合
一个写一个审完善过程，发还给D定成手稿，由B消化后确认此证明路径。」

| 步 | 谁 | 做什么 | 产出落哪 |
|---|---|---|---|
| 1 | **C** | 整理（哪条成果缺证明、哪几条路径可选、依赖链） | `C.proof_chain` 的返回 + 一条给 D 的报文/手稿 |
| 2 | **D** | 整理成"证明完善任务"（要证哪条、允许哪几条路径、验收口径） | 手稿（`handoffs.jsonl`）给 F |
| 3 | **F** | 写过程（一条路径一份过程；多路径各写一份） | 实验行 / 手稿 |
| 4 | **V** | 审那几份过程（独立核） | `review_findings` / 签名 |
| 5 | **D** | 收到 V 的裁决 ⇒ 定成**手稿**（`G.build_document` 那一档的产物，或 D 自己的手稿行） | `documents` 行 + `manuscripts` |
| 6 | **B** | 消化：确认此证明路径（写 `dependencies` 组 + `bits.proof`） | `statements` / `dependencies`（**经 B 的秘书**，见 11.1） |

**判据（S1o 同批，红前必红）**：这条链上每一步都要有**可读的载体**（C 的返回、D 的手稿、
F 的实验行、V 的裁决、D 定的手稿行、B 登记的依赖组）——**缺哪一步就点名哪一步**
（与 `escalation_gaps` 同一族的读数），而不是"链跑没跑过没人知道"。

### 11.4 D6 / D8 / D9（业主 2026-10-09 裁定）

- **D6 认可**：`escalation_gaps` 把"写进交付说明"算上报载体，读数分四档
  `via: question / message / handoff / report`（实现落 `closing._escalation_reading` + 一条判据）。
- **D8 修**：接上面装配点（`run-agent` 与 `webui` 两处的 `registry_factory`），
  并加判据"检查的基准 == 执行的基准"（E23）。
- **D9 收窄**：`_check_artifact_ledger` 改成"按路径取最新一次登记比对"，`changed ⇒ pass + warning`
  （1c-1），并加一条判据钉住"正常改写不再把这一格读成 unknown"。

### 10.5 批次顺序（被这两次裁定改了一处）

**S1r（并表迁移，要人审）→ S1p（消化读数）→ S1o（依赖链）→ S1q（正文重建）**：
S1p/S1o 读的就是 `statements`（并表之后的唯一落点）⇒ 迁移必须在它们**之前**，
否则两批要写两遍。S1r 未过审期间，S1p/S1o 按 §10.3 的**过渡期读法**写（两处同号合并），
于是"迁移卡在人审"不会让后面三批停摆。
**本页 §11 的三件（B 的写入全走秘书 / 五元位映射判据 / C→D→F+V→D→B 协作链）并入 S1o 那一批**；
**D8（E23）与 D9（第八格收窄）各是一批**，排在 S1o 前后（D8 优先，它属"权限面说两句话"）。

## §12 B 走乙（多依赖落成字段）+ C 的分析适配（业主 2026-10-09）

业主逐字：

> 「B走乙。由于B这边出了多依赖写法，C的分析需要做适配」

### 12.1 乙档定死：`dependencies` 加一列 `path_group`

| 项 | 定死 |
|---|---|
| 字段 | `path_group: int = 1`（`dependencies` 的**新列**）；**同一 `used_by` + 同一 `path_group` 的那些行 = 一条路径（组内是"都要"= AND）**；不同 `path_group` = **可选路径（组间是"任一"= OR）** |
| 缺省 | `1`（历史行与"只有一条路径"的写法不需要改一个字） |
| 校验 | 正整数；同一 `used_by` 下组号从 1 连续（缺号要报，因为它会让"组"这件事在读数上缺一角） |
| 迁移 | 与并表**同一笔**：`SCHEMA_VERSION 1 → 2`（一次迁移、一次人审，别开两次） |
| 为什么不留"受控前缀"（甲） | 业主要的是**结构上**的多路径：前缀编码会让"组"只能靠解析字符串才看得见，而字段让 `verify`/`closing`/C 都能**直接**按组读 |

**二维列表 ↔ 字段的对应（B 交的形状不变）**：B 交 `deps = [[步骤…], [步骤…]]`
⇒ 秘书按外层下标写 `path_group=1,2,…`，内层逐条落行；读回来按 `path_group` 分组就还原成二维列表。

### 12.2 C 的适配（`proof_chain` 从"一条链"变成"每组一条链 + 挑最短那组"）

- **长度定义**：一条**路径（组）的长度 = 组内步骤数**（组内是 AND，全都要重建）；
  一个节点的"最短" = **组间取最短的那一组**（OR ⇒ 挑最省的一条路重建）。
- **返回形状（改）**：
  `{"checked", "target", "preconditions", "groups": [{"group": 1, "hops": [...],
  "length": n, "leaves": [...], "why": ""}], "best_group": 1|None,
  "groups_total": k, "truncated", "reason"}`。
  `hops` 的每跳仍带 `via_dep_id`（**并带 `path_group`**）—— 逐跳可复算到"哪条边、哪一组"。
- **并列**：`best_group` 取长度最小者；长度相同按 `group` 升序，并在 `why` 里写明"并列，取了第 n 组"。
- **一条边出现在多个组里**：**逐组各算一次**（它确实是两条不同路径的一步）；
  但**跨组汇总的读数**（例如"这条成果一共牵动几个节点"）要**按节点去重**——
  否则多写一组路径会把"依赖规模"读数吹大（这是本仓最忌的"计数好看于事实"）。
- **环 / 悬空 / 截断**：逐组判（某一组有环 ⇒ 那一组报 `cycle` 并跳过，**不牵连别的组**）；
  `max_depth` 仍按"从 target 出发的边数"，**按组**计。
- **权重**：`weights` 表照旧；组内求和（AND ⇒ 成本相加），组间取最小（OR ⇒ 挑最便宜）。
- **不直接受影响的分析（已核）**：C 的 `hottest` / `paths` / `gaps` / `contradictions` /
  `relations_between` 读的是 **`relations` 与 `concepts`**（现算：`specs/c.py` 的
  `ACTIONS` 里这几条的参数与 `agent_c/*.py` 的读表），**不读 `dependencies`**
  ⇒ 多依赖写法不改变它们的口径；**唯一的接口是 `dependencies`**。

### 12.3 判据（并在 S1r / S1o 两批里）

- **S1r（schema v2 同一笔）**：正控 —— 一条 `used_by` 下三行、`path_group` 1/1/2 ⇒ 读侧还原成
  `[[两条],[一条]]`；负控 —— 组号缺号（1,3）⇒ 报读数；迁移后历史 `dependencies` 行**逐字不变**
  （只多一列 = 1）。
- **S1o（C 侧）**：正控 —— 两组路径（长 2 / 长 1）⇒ `best_group` 取长 1 那组，`groups_total=2`；
  负控① —— 某一组有环 ⇒ 只那一组报 `cycle`，另一组照给；
  负控② —— **跨组汇总的节点数按去重算**（同一条边写进两组不会把规模读数吹大）；
  反真空 —— `path_group` 读不成 ⇒ 整条读数 `checked=False`（不许当成"只有一组"）。

## §13 逐文件改动设计（伪代码）+ 真实系统证据

**先订正本页草案里一处写错的符号（诚实项）**：§11.1 与 §12 我写成 `store.alloc_id` ——
**`Store` 上没有这个方法**。现场核实（2026-10-09）：
`class Tx`（`store.py:154`）才有 `def alloc_id(self, kind: str) -> str`（`store.py:306`），
`store.py:286` 的写入路径是 `row[id_field] = self.alloc_id(id_kind)`；
`Store` 上只有 `_next_seq()`（`store.py:1044`）与 `rebuild(backup=True)`。
**⇒ 正确口径：编号由事务的 `tx.alloc_id(kind)` 分配**（下文一律用这个）。

**本案的"真实依据"清单**（都是现场读出来的，不是推想）：

| # | 依据 | 现场 |
|---|---|---|
| E1 | `SCHEMA_VERSION = 1`；`TABLES['dependencies']['id_field'] = 'dep_id'` | 现算 `schema.SCHEMA_VERSION` / `S.TABLES['dependencies']` |
| E2 | `Dependency` 字段表**没有** `source_stmt_id`、**没有** `path_group` | 现算 `Dependency.__dataclass_fields__`（`dep_id/used_by/kind/label/status/source_lit_id/source_experiment_id/page_range/quote/status_reason/created_at/source_doc_id/source_claim_id/created_by`） |
| E3 | `Dependency.validate()` 只要求 `used_by` 非空 + `kind`/`status` 在词表内 | `schema.py` 那一段正文 |
| E4 | `Relation.concept_ids` 是 `list[str]`（迁号时要一起改） | 现算 `.type` |
| E5 | `Tx.alloc_id`（`store.py:306`）/ `Store.rebuild`（签名 `(backup: bool = True)`） | `inspect.signature` |
| E6 | `doc_tools.register_dependency(store, used_by, kind, label, *, source_lit_id=None, source_experiment_id=None, page_range=None, quote='', status='dangling', status_reason='', actor='agent-G')` | `inspect.signature` |
| E7 | `evidencebits` 的公共函数：`bits_of` / `bits_from_row` / `bits_shape_problems` / `derive_grade` / `apply_cascade` / `void` / `void_refusal` / `normalize_raw` / `clean_statement_ids`；常量 `BIT_NAMES=(numeric,proof,reviewed,formal,audited)`、`BIT_OWNERS={numeric:E, proof:F, reviewed:V, formal:E, audited:H}`、`BIT_STATES=(pending,na,failed,verified)`、`GRADES=(conjecture,strong_conjecture,pre_theorem,theorem)` | 现算 |
| E8 | `Secretary` 已有 `wash_delegation` / `surface_fit`；模块级 `append_jsonl` 是唯一追加口 | `hasattr` 现算 |
| E9 | `closing._check_artifact_ledger(rep, store, project_dir)`、`_leg_reading(store, kind, project_root)`、`LEG_CHECK_KINDS`（32 档，S1p 已加一档） | `inspect.signature` / 现算 |
| E10 | C 的动作真身 `specs/c.py` 的 `ACTIONS`，拼装在 `agent_c/core.py:1132` 的 `AgentC(...)` 基类表 | 现场读文件 |

### 13.1 `src/agentflow/schema.py`（禁改区 `schema-migration`，与并表同一笔）

```python
# ① `Dependency` 加两列（E2 说今天都没有）
path_group: int = 1          # 组内 AND / 组间 OR；缺省 1 ⇒ 历史行语义不变
source_stmt_id: str = ""     # "这条定理用到的那条命题/概念"（E2：今天没有这一格，
                             #  所以"定理→定理"这条边**现在无处安放** —— 这是乙档的必需项）

def validate(self) -> None:
    ...                                   # 既有检查一字不动（E3）
    if int(self.path_group) < 1: raise ValueError("path_group 必须是正整数")
    # 被依赖的那一端必须**恰好有一个**：lit / experiment / doc+claim / stmt
    ends = [bool(self.source_lit_id), bool(self.source_experiment_id),
            bool(self.source_stmt_id), bool(self.source_doc_id)]
    if sum(ends) != 1: raise ValueError("被依赖端必须恰好给一个（lit/experiment/stmt/doc）")
    if self.source_stmt_id: require_id(self.source_stmt_id, "source_stmt_id")

# ② `Concept.validate()` 补"定义三态"（D1：空串为什么能写进来）
if not self.definition.strip():
    if not (self.definition_source_lit_id or self.definition_reason.strip()):
        raise ValueError("定义为空 ⇒ 必须给出定义来源或理由（三态：不许静默写空）")

# ③ 并表：`TABLES` 去掉 `concepts`；`SCHEMA_VERSION = 2`
```

- **依据**：E1/E2/E3/E4 逐条现算；`Concept.validate` 正文里**确实没有**定义非空那一条（D1 已核）。
- **判据**：正控（`path_group=1` 的历史行 `validate()` 照过）；负控（`path_group=0` / 两个被依赖端 / 空定义无来源 ⇒ 各自拒）；反真空（`SCHEMA_VERSION == 2` 与 `TABLES` 里没有 `concepts`）。

### 13.2 `src/agentflow/store.py`

```python
def rebuild(self, *, backup: bool = True) -> dict:      # 签名不变（E5）
    events = self._read_events()
    for ev in events:
        if ev["table"] == "concepts":                    # 折成 statements（draft/97 §10.3）
            row = {"stmt_id": ev["row"]["concept_id"],   # 号由本笔迁移统一重发（见下）
                   "kind": "concept", "origin": "own_result",
                   "label": ev["row"]["name"],
                   "statement_full": ev["row"]["definition"],
                   "proof_text": "concept:primitive" if not ev["row"]["definition"].strip()
                                 else "",               # 空定义 ⇒ 受控标记，**不编**
                   "created_at": ev["row"]["created_at"]}
            seen_new_ids[row["stmt_id"]] = True
        ...
    # 号：概念行统一走 **同一个分配器**（`Tx.alloc_id("statements")`，E5）
    # ⇒ 结构上不可能与既有命题撞号（业主 D2 定调）
    # relations.concept_ids 同步改号（E4：它是 list[str]），改号映射落 migrate-map.jsonl
```

- **依据**：E4/E5。
- **判据**：`temp/_s1r_rehearsal.py` 的 2233 条逐条对得上；迁移后 `dependencies` 行**逐字不变**（只多两列缺省值）；改号映射逐条可复算。

### 13.3 `src/agentflow/tools/doc_tools.py` + `agent_b/*` + `secretary.py`（B 走秘书）

```python
# doc_tools：边多两格（E6 的签名 + 两格）
def register_dependency(store, used_by, kind, label, *, source_lit_id=None,
                        source_experiment_id=None, source_stmt_id=None,   # 新
                        path_group: int = 1,                              # 新
                        page_range=None, quote="", status="dangling",
                        status_reason="", actor="agent-G") -> dict: ...

# secretary：B 的写入代理（四件活，E8 说秘书已有同族先例）
def wash_statement(self, payload) -> dict:      # 洗格式：键名归一/顶层折叠/去空白（内容一字不动）
def record_statement(self, *, role, payload) -> dict:
    """B 交内容 ⇒ 秘书落盘：同 key 查重 → `tx.alloc_id('statements')` 拿号 →
    一笔事务写 statements（+ 概念行 kind='concept'）/ dependencies（二维列表按 path_group 展开）。"""
    # 秘书没装（无 store）⇒ 明确拒 `secretary_unavailable`（不许"B 自己写"这条后备路）

# agent_b/register_statement.py：B 只交内容（`deps` 是二维列表）
deps = [[{"kind": "theorem", "stmt": "0003"}, {"kind": "experiment", "exp": "0004"}],   # 路径 1
        [{"kind": "definition", "stmt": "0001"}]]                                        # 路径 2
```

- **依据**：E6/E8；`register_statement` 今天的"第四条必填"逐字支持 `origin=own_result` + `doc_id`/`line_range`。
- **判据**：正控（交一条 ⇒ 三表各多一行、号来自 `tx.alloc_id`、`path_group` 按外层下标）；负控（同内容两次 ⇒ "重复"读数不新建行）；**反真空**（无秘书 ⇒ 拒，且**不落任何行**）。

### 13.4 `evidencebits.py` + `verify.py`（五元位的映射判据；E7）

```python
# evidencebits：加一条纯函数（唯一实现，verify 只转发它）
def bit_table_map(bits) -> dict[str, str]:        # 每一位"去哪张表查"的映射
    return {"numeric": "experiments", "formal": "experiments", "proof": "statements.proof_text",
            "reviewed": "signatures", "audited": "signatures"}

# verify_all：新不变量（D7 的"机器侧"只到这里 —— 业主说 D7 先不做 used_by 的机器验证）
for stmt in statements:
    for bit, state in bits.items():
        if state == "verified":
            # `proof` 那一档：证明必须能在 **B 维护的表** 里查到（`proof_text` 非空 +
            # 有指向的 proof 证据行，或一条 dependencies 边指出它）—— 业主点名的那条
            ...issue("bits_verified_without_evidence", ...)
```

- **依据**：E7（函数名与词表现算）。
- **判据**：正控（`bits={"proof":"verified"}` + `proof_text` 非空 + proof 行在 ⇒ 无 issue）；负控（`proof:"verified"` 而 `proof_text` 空 ⇒ 报 `bits_verified_without_evidence`）；反真空（`statements` 读不成 ⇒ 报"没查成"，不许当成"都对上了"）。

### 13.5 `specs/c.py` + `agent_c/proof_chain.py` + `agent_c/core.py`（C 的组语义；E10）

```python
# specs/c.py 的 ACTIONS 末尾加一条（形状照抄现有 8 条）
ActionSpec("C", "proof_chain", "一条成果的最短证明依赖链（按路径组）",
           _obj({"target": _S, "max_depth": _I, "k": _I, "weights": _OBJ}, ("target",)),
           "AnalysisReport", side_effect="read", handler_name="proof_chain")

# agent_c/proof_chain.py（新文件，与 hottest.py 同形：一个 _Xxx mixin）
class _ProofChain:
    def proof_chain(self, target, *, max_depth=4, k=1, weights=None) -> dict:
        edges = group_by_path_group(dependencies_of(target))     # 组内 AND / 组间 OR
        groups = [{"group": g, "hops": BFS(g.edges), "length": len(g.edges)} for g in edges]
        best = min(groups, key=lambda x: (x["length"], x["group"])) if groups else None
        return {"checked": ..., "groups": groups, "best_group": best["group"] if best else None,
                "groups_total": len(groups), "hops 带 via_dep_id+path_group",
                "truncated": ..., "reason": ...}

# agent_c/core.py：两处接线（E10：import 那一片 + 1132 行的基类表）
from .proof_chain import _ProofChain
class AgentC(..., _StructuralDuplicates, _ProofChain, _Handle, _Core): ...
```

- **依据**：E10。
- **判据**：§12.3 那四条（`best_group` / 单组环不牵连 / 跨组去重 / `path_group` 读不成 ⇒ `checked=False`）。

### 13.6 `closing.py`（D6 + D9）与 `agent_loop.py`/`cli.py`/`webui`（D8）

```python
# D9：第八格收窄（1c-1）
def _check_artifact_ledger(rep, store, project_dir):     # E9 的签名不变
    # 改：按**路径**取最新一次登记比对（append-only 历史逐行比必然把改写读成 changed）
    # `changed` ⇒ rep.status["artifact_ledger"] = "pass" + warning 读数（不再 unknown）

# D6：上报载体四档
def _escalation_reading(root, sid, tasks):
    # 匹配表加一档：`out/review/REPORT.md` 里点名 ⇒ via="report"（读数四档不折平）

# D8：面装配点（E23）——两处各一行
# cli.py（run-agent 装配）与 webui 装配处：
backend.registry_factory = lambda face: build_registry(workspace_root=face, ...)
# 判据：`_surface_refusal` 的基准目录 == fs 工具实际 root（同一条断言）
```

- **依据**：E9 + `draft/90` §2 的 E23（实现行号在那里）。
- **判据**：D9 正控（框架幂等重写 `out/tasks/*.json` ⇒ 那一格 `pass` + warning）；负控（产物真被删 ⇒ 仍 `fail`）；D8 正控（子代理写相对路径 ⇒ 落在**它自己的面**里）；D6 一条（报告里点名 ⇒ `via="report"`）。

### 13.7 还未核到的（施工第一步核，核法写在括号里）

- **V5**：`Tx.alloc_id("statements")` 的 `counters` 键是否与"既有 statements 的最大号"一致
  （核法：读 `counters.json` 里那一格 + 一次 `alloc_id` 的返回）；
- **V6**：`relations` 表有没有**别的**字段也存概念号（现只核到 `concept_ids`；核法：读 `Relation` 全字段）；
- **V7**：WebUI 里读 `concepts` 的落点（`webui/readers.py`；核法：grep `concepts`）；
- **V8**：`agent_c/__main__.py` 那四处 `upsert("concepts")`（CLI 侧的探针命令）要不要跟着改。

## §14 补遗：§13 漏掉的十二处（业主 2026-10-09：「还是有漏写的点，仔细写」）

每条都是"按现有代码真会出事"的点，**带现场依据**。

### 14.1 **v1 数据在 v2 代码下读得成吗**（最要紧的一处：漏了会砸掉 59 个工作区）

现场：`schema.py` 里有一条快照校验 `f"{table} schema_version 应为 {SCHEMA_VERSION}，收到 …"`，
而盘上 59 个工作区的快照都是 **v1**。⇒ 只把 `SCHEMA_VERSION` 改成 2、不动读侧，
**所有老工作区会当场读不成**（不是"读出错数据"，是**报错**）。

**设计（必须写进 S1r 的同一笔）**：`store.py` 的读取侧接受"**版本 ≤ 当前**"，并在
**第一次写**时把快照升到 v2（`rebuild` 重放事件 → 写 v2 快照；旧事件保留）。
判据：**v1 夹具工作区**在 v2 代码下 `rows("statements")` 读得成；迁移后快照写着 2；
**不许**静默把 v1 快照当成 v2 读（要记账：读数里报"这一份是从 v1 升上来的"）。

### 14.2 **迁移行必须带 `quote_reason`**（`Statement.validate` 的硬要求）

现场（`Statement.validate` 正文逐行核过）：
`if self.quote_verified is not True and not self.quote_reason.strip(): raise` ——
即 **`quote_verified=None`（没校验）时 `quote_reason` 必须非空**。
`concepts` 折过来的行不会有 `quote_verified=True` ⇒ **迁移行不写 `quote_reason` 会被当场拒**。
⇒ 迁移规则补一条：`quote_verified=None` + `quote_reason="迁移自 concepts：<原样说明>"`。

### 14.3 `own_result` **不强制**出处（与 B 的预检不是同一处）

现场：`Statement.validate()` 对 `own_result` **不查** `doc_id`/`line_range`
（它只查 `external_lit` 的 `source_lit_id`；注释还写明曾经那条"own_result 必须给 proof_text"
的 `raise` **已删**）；"own_result 要给 doc_id 或 line_range" 是 **B 的预检**那条纪律。
⇒ 迁移行（没有 `doc_id`）**过得了 validate**，但要在读数里点名"这一行没有出处"（可见性不丢）。

### 14.4 **`Concept` 另外四个字段去哪**（§13 只映射了 name/definition）

| 原字段 | 去处 |
|---|---|
| `related_concepts` | 落 `relations`（已存在的那张表，本来就是它） |
| `merged_into` / `merge_reason` | **不许丢**（"这两个概念是一个"是审计材料）⇒ 需要承载点 |
| `aliases` / `normalized_name` | **不许丢**（查重键）⇒ 需要承载点 |

`Statement` 里**没有**承载这三样的字段 ⇒ 两条候选：**甲** 用既有的自由文本格编码
（`quote_reason` 里写受控前缀 `concept:merged_into=<id>` / `concept:aliases=<json>`，
零 schema 改动）；**乙** 给 `Statement` 加三格（`concept_meta`），动 schema。
**建议甲**（并表这一笔已经动了 schema，能少动一格就少动一格；甲的代价是"要解析前缀"）。
**这是本页新增的待裁项（记作 D10）**。

> **D10 是什么（大白话，业主 2026-10-09 问）**：`concepts` 表里除了"名字 + 定义"，
> 还存着**三样别的东西**，并表之后它们**没有地方放**：
> ① `merged_into` / `merge_reason` —— "概念 0031 其实和 0007 是同一个，所以并到 0007"，
>    这是**审计材料**（谁在什么时候为什么合并了两个概念）；
> ② `aliases`（别名）与 `normalized_name`（归一化名字）—— 这是**查重键**：
>    "Perfect Graph Theorem" 与 "perfect graph theorem" 靠它认成同一个概念。
> `statements` 表**没有对应的列**，所以并表时这三样要么**塞进一个已有的自由文本格**
> （甲：在 `quote_reason` 里写 `concept:merged_into=0007`、`concept:aliases=[...]` 这种
> 受控前缀，读的时候解出来 —— 不动 schema），要么**给 `statements` 加一列**
> （乙：`concept_meta`，结构干净但要再动一次禁改区的 schema）。
> **建议甲**。若你不裁，我按甲走。

#### 14.4b D10 结案（业主 2026-10-09 裁定 + 真实数据核对）

业主逐字：「由于秘书会查重，D10的合并概念不会发生，因为不会重复登记」
⇒ 再加上**现算的真实数据**（`temp/_s1r_rehearsal.py` 那一轮的同一份扫描，2233 条）：

| 字段 | 真实现场 | 处置 |
|---|---|---|
| `merged_into` / `merge_reason` | **0 条**（2233 条里一条都没有） | **不设承载点** —— 业主判断被数据证实：秘书查重 ⇒ 不会重复登记 ⇒ "登记之后才发现是同一个"这件事不再发生。判据：迁移时**若**碰到非零值 ⇒ 报读数点名，**不静默丢**（历史若是真有过，也看得见） |
| `normalized_name` | 2233 条全有，但 **640 条与"名字 lower + 去空白"对不上** | **不存**。依据：读侧本来就是"存了就用、没存就现算"（`dedup.py:295` 与 `interactions.py:870-879` 都是 `row.get("normalized_name") or T.normalize(...)`），**唯一实现是 `textutil.normalize`**；而那 640 条的成因也查到了 —— `pipeline.py:627` 写的是 `normalized_name=name`（把**原始名字**塞进了这一格）⇒ 丢掉它反而修正了这个不一致，并把差异条数记成迁移读数 |
| `aliases` | **888 条有别名**（约 40%，且**不可现算**：如 "Petersen graph" ↔ "Kneser graph K(5,2)"） | **必须留** ⇒ 仍需一个承载点：**甲** `quote_reason` 里的受控前缀 `concept:aliases=[...]` / **乙** `statements` 加一格 `concept_meta`。**建议甲**（这一项记作 **D10′**，若你不裁按甲走） |

**⇒ 未来查重的键**：`T.normalize(label)` + 读出来的 `aliases` —— 一处口径
（`textutil.normalize` 是唯一实现，秘书不另写一份）。

#### 14.4c **D10′ 是什么**（业主 2026-10-09：「D10'没听懂」⇒ 用真名真例重讲）

**别名是什么（不是抽象的）**：同一个数学对象常常有好几个名字 —— 现场从 888 条里取的例子：

| 台账号 | 记的名字 | 别名（同一个东西的别的写法） |
|---|---|---|
| `p6/0000` | `vertex-girth-regular vgr(n, k, g, λ)` | `vertex-girth-regular graph`、`vgr(n, k, g, λ)-graph` |
| `p6/0001` | `(k, g)-cage` | `cage`、`cage problem` |
| `p6/0005` | `edge-girth-regular graph egr(n, k, g, λ)` | `egr(n, k, g, λ)-graph` |

**为什么必须有它**：秘书的**查重**是"按名字认同一个东西"。手稿里下一次写
"`vgr(n, k, g, λ)-graph`"时，如果台账里只存了主名字、没有别名表，
秘书就认不出它与 `p6/0000` 是同一个 ⇒ **又登记一行**（这正是"重复登记"从后门溜回来），
C 的图上同一个概念会变成两个节点。
**别名不能靠现算**（不像 `normalized_name` 只是大小写/空白的归一）：上表里
"`cage`" 与 "`cage problem`" 之间没有可计算的规则，那是**外部知识** ⇒ 必须**存**。

**D10′ 要你定的那一句话**：这份别名表存哪儿？（并表之后 `statements` **没有这一列**）

- **甲（建议）**：塞进一个**已有的自由文本格**（例如 `quote_reason`/备注），用**受控前缀**写
  `concept:aliases=["cage","cage problem"]`，读的时候解出来。**不动 schema**，
  代价是"别名要靠解析才能读"（不是一列，SQL 式查询看不见它，但 grep 得到、可审计）；
- **乙**：给 `statements` **加一列**（`concept_meta` 或干脆 `aliases`）。读起来干净、
  查询方便；代价是**再动一次禁改区的 schema**（并表这一笔已经要把 `SCHEMA_VERSION` 抬到 2），
  而且 888 条历史行要多走一次迁移。

**不裁的后果**：按甲走 —— 别名以受控前缀落在文本格里，秘书查重时先读它再比主名字。

### 14.5 **概念行不参与等级**（否则被读成"猜想"）

现场：等级由 `evidencebits.derive_grade` 现算，`bits={}`（概念没有证据位）时它会给出
最弱那一档。⇒ 设计：`derive_grade`（**唯一实现**）对 `kind == "concept"` **短路**：
返回"不适用"，**不参与 `conjecture → … → theorem` 这条链**。
判据：一条概念行现算等级**不是**"猜想"（改前必红）；报表里概念的等级那一栏写"不适用"。

### 14.6 **组内有一条悬空 ⇒ 整组不可达**（§12.2 只写了"悬空边不算到根"）

组内是 AND（都要）⇒ 一条 `status="dangling"` 的边让**那一组**不完整：
该组标 `incomplete`（读数），**不算到根**；同一条命的其他组不受影响。
`external_unavailable` 仍算到根（合法终局），但要在 `why` 里点名。

### 14.7 **`k` 与"组"的关系定死**

`k` = 返回的**组**数（组内不再分叉），`groups_total` = 全部组数；
并列（长度相同）按 `group` 升序取前 `k` 组，并在 `why` 里写明"并列，取了第 n 组"。
（§13 的伪代码里 `k` 没有定义，这处不能含糊。）

### 14.8 **D6 的 `report` 档从哪读**（三态）

`via="report"` 的那一档读的是**盘上的 `out/review/REPORT.md`**（不是会话）：
报告在盘上且项名出现在正文里 ⇒ `report`；报告不在盘上 ⇒ 这一档 `checked=False`
（"没查成"，不许当成"没上报"）；匹配仍是**字面**（项的 `what` 出现在正文里）。

### 14.9 **D9 的算法与可见性**

`_check_artifact_ledger` 改成：**按路径取最后一条登记行**比对（append-only 的历史逐行比
必然把任何改写读成 `changed`）；`missing`/`unreadable` **仍 `fail`**；
`changed ⇒ pass + warning`，且 **`changed_rows` 仍逐条列出**（可见性一格不减）。

### 14.10 **D8 的契约与代价**

`registry_factory(face: str) -> ToolRegistry`（`agent_loop.py` 已经在用这个名字）；
`cli.py` 的 `run-agent` 与 WebUI 装配处**各一行**把它接上；判据：
"`_surface_refusal` 的基准目录 == `fs` 工具实际 root"。
**代价读数**（必须记）：每实例一个注册表 ⇒ 构造一次/实例；实现里按面**缓存**
（同一个面复用同一个注册表），并把"构造了几次"记成读数。

### 14.11 **"B 不直接用写工具"的接线机制** —— 业主 2026-10-09 裁定：**走乙**

业主逐字：「14.11关于B"写"工具用乙形式，B需要给的输入就是定理内容、证明过程。」

- **机制（乙）**：B 手里的写工具**留着**（工具面不动、不摘），但**执行点改道**：
  B 的那次写调用在 `AgentLoop` 的执行点被转到**秘书**的 `record_statement`，
  由秘书完成"洗格式 / 拿号 / 查重 / 改表"四件事 —— 真正落盘的手是秘书，
  B 只负责**消化理解**。
- **B 的输入契约（业主指定，只有两样）**：**定理内容**（要落的那条命题正文）
  + **证明过程**（那条定理的证明文本）。别的一概不要求 B 给 ——
  出处、依赖、编号、去重都由秘书从这两样里**推**出来：
  - **出处**：证明过程/定理内容里出现的 `lit:` / `exp:` / `stmt:` / `rel:` 引用
    （前缀表就是 `CITATION_PREFIXES`）⇒ 秘书扫出来写成 `dependencies` 的边；
  - **依赖（关键）**：**依赖 = 证明过程里引用到的那些号**。业主前面说"记录定理和证明时
    同样把依赖写清"，落的形态就是这个：B 不需要额外列一张依赖表，
    秘书**从证明文本里逐条扫出引用**（每条边一个 `path_group`，缺省 1）。
  - **多路径**：证明过程里若有**多段可选证明**（B 自己分段/标路径）⇒ 秘书按段分
    `path_group=1,2,…`（二维列表的来源）；**没有分段标记 ⇒ 全归第 1 组**（缺省，不猜）。
  - **编号**：`tx.alloc_id("statements")`；**查重**：规范化后的定理内容 + 归一化名字。
- **判据**：正控（B 交"定理内容 + 证明过程" ⇒ `statements` 一行 + 由证明文本扫出的
  `dependencies` 若干行，`used_by="stmt:<新号>"`）；负控（证明过程里出现一个**不存在的号**
  ⇒ 那条边落 `dangling` 并在读数里点名，**不整笔拒**）；反真空（证明过程里一个引用都没有
  ⇒ 该行的依赖是"空"而不是"没记录"：读数写 `deps_state="none_in_proof"`，
  与"没扫"（`unknown`）严格分开）。


### 14.12 V5–V8 的核法照旧（见 §13.7），并新增 **V9**：`schema.py` 里那条快照版本校验的
**调用点有几个**（核法：grep `schema_version 应为`），决定"版本 ≤ 当前"要改几处。

### 14.13 **抽不到定义的概念**：留空 + 待补（A 去搜 / B 自撰）—— 业主 2026-10-09 裁定，**取代 D1 的甲/乙**

业主逐字：

> 「抽不到定义的概念就让A去网上搜，写入时定义内容留空，等A返回后写入；如果概念很基础，
> 是数学基本概念，允许B自己写定义（我们相信LLM的智力）」

⇒ D1 那三个选项（照折 / 不折 / 标工作区）**作废**，正确口径是"**空着，但空得有交代，并且有人去补**"：

| 环节 | 定死 |
|---|---|
| **写入** | `statement_full`（定义内容）**可以为空**，但**必须**同时落一个**待补标记**（受控，见下）——**没有标记的空 = 拒**（三态：`未拿到` ≠ `就是空的`） |
| **补法（三条，受控取值）** | `pending_search`（等 A 上网搜）/ `self_authored`（B 自撰：**基本数学概念**，业主授权"相信 LLM 的智力"）/ `from_lit:<lit_id>`（已从某篇文献抽到 —— 有定义的行走这一档） |
| **谁来补** | `pending_search` ⇒ **A**（检索动作，落 `search_requests` 与结果）；`self_authored` ⇒ **B**（自撰，来源记 `self_authored`，**不是** `definition_source_lit_id`） |
| **补完怎么落** | A 返回 / B 自撰之后，**由秘书改表**（§11.1 的四件活之一），把定义写进那一行并把标记改成 `from_lit:…` / `self_authored`；**改动留痕**（`dependencies` 不掺这一档，用行内的 `quote_reason`/受控前缀记"哪一次补的"） |
| **良定义性证明（`proof_text`）** | 与"定义内容"是两件事：基本概念走 `concept:primitive`（义务为空）；由构造引入的概念要写良定义性（§10.1） |

**判据（S1r / S1o 各一条）**：
- **正控**：一条没抽到定义的概念 ⇒ 落行成功、`statement_full=""`、标记 `pending_search`、
  读数里点名"等 A 补"；A 那一边的检索请求（`search_requests`）**真的在队列里**；
- **负控**：`statement_full=""` 而**没有**待补标记 ⇒ **拒**（这正是 94 条历史行的病根：
  空得没有交代）；`self_authored` 时若把来源写成某篇 `lit_id` ⇒ 拒（自撰不是文献）；
- **反真空**：一条概念**既**没有定义**又**没有补法标记 —— 迁移与写入两条路都不许放过；
  读数里把 `pending_search` / `self_authored` / `from_lit` 三档**分开计数**（不折平）。
- **历史 94 条**（处理见 §10.3b + 本节）：全部**没有** `definition_source_lit_id`、
  名字是通用数学名词 ⇒ 迁移时落 `pending_search` 标记（**不编定义**），
  并在读数里点名 94 条待补（这 94 条正好就是 A 的第一批活）。





