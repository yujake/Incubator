# 97 · 逐文件改动面（S1p 消化读数 / S1o 依赖链 / S1q 正文重建 + B 的 `deps`）

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
