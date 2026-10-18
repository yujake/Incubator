# 提案：只读角色的不变量从"**全只读**"改成"**写面钉死**"

> 提案性质：**禁改区（auth-audit）**改动的前置文档。涉及
> `src/agentflow/tools/base.py`（`for_role` / `_role_surface` / `READONLY_CALL_EXCEPTIONS`）、
> `src/agentflow/tools/__init__.py`（`READ_ONLY_ROLES`）、`src/agentflow/tools/review_tools.py`（`register` 的 `include_writers`）。
> 按 `AGENTS.md`：需**人编写或人逐行走查** ＋ **2 名 reviewer approve**。
>
> 业主裁定（2026-10-17）：**方案 1**（写能力长在角色自己身上，而不是靠谁点名动作）。

---

## 1. 今天的矛盾（有代码与真机两头的证据）

**口径 A（2026-10-16 S2，业主）**："M 只派活，不点动作"。
实现见 `agent_loop.py:4639-4650`：`_do_summon` **不读** `payload["action"]`，调
`conductor.summon(role, "", params, …)` 时那个 `""` 是**写死**的
（注释逐字："完全不要有填 action 的位置"）。

**口径 B（今天）**："H 审过要落台账（`review_findings`）"，而 H 的**唯一写入口**是
`H.review` 这一次**固定流程**（`review_tools.register(..., include_writers=True)` 造出的
`self.writers` 落库代理）。

⇒ 两者不能同时成立：M 永远不能点 `action=review` ⇒ `H.review` 永远不被触发 ⇒
**H 的写入口不可达**。

**真机证据（`projects/t5e`，2026-10-17）**：

- M 的 `summon` 形状里**多次显式写了** `"action": "review"`（会话日志 `sessions/t5e-4.jsonl`，8 条里多条含该键）；
- 落下的任务行却是 `action=''`（S2 的实现直接把 action 丢了）；
- H 被派了 **4 趟**、每趟 17–24 步，反复读写、反复回报"写入口不可达"；
- 结果：`data/review_findings.json` **0 行**，而 H 的 3 条发现只在 `out/review/000000-review.md` 里。

## 2. 提案（改不变量，不动 S2）

**把"H/C 的工具面必须全部 `side_effect ∈ {"none","read"}`"改成
"H/C 的**写面**必须恰好是它们各自台账的落点（逐条钉死）"。**

| 角色 | 可见面 = 只读部分（不变） | **新增可见的写面（钉死）** |
|---|---|---|
| **H** | `review.scan_document`、`review.list_findings`、以及原有的全部只读工具 | **`review.review_document`**（只写 `review_findings` ＋ `documents.status`）、**`review.review_report`**（只落 markdown 报告，不碰任何表） |
| **C** | 原有全部只读工具 | **它自己的落点**（分析报告 / note；具体件名列在实现时按 `specs/c.py` 的 `write_set` 定，本提案不预先发明） |

**为什么这不动 S2**：M 仍然"只派活、不点动作"；H 收到派活后，**用自己的可见工具**去写
（不再依赖"被点名动作"）。

## 3. 实现落点（三处，必须同时改，逐处人审）

1. `review_tools.register(..., include_writers=True)` 的行为：从"**装配到独立代理**"改成
   "**装配进主注册表，但可见性只对 H**"（即 `roles=("H",)` ＋ 由例外表放行可见）；
2. `tools/base.py::for_role`：`READONLY_CALL_EXCEPTIONS[role]` 里的工具**应当出现在该角色的可见面**
   （今天的语义只是"允许调用"，于是模型看不见 ⇒ 也就想不起来调）；
3. `tools/base.py::call/_callable_for`：**保持不变**（可调用面本来就允许例外表里的工具）。

## 4. 必须的负控（这条改动最危险的地方）

| 负控 | 断言 |
|---|---|
| 别的角色看不见 | `for_role("G")` / `for_role("B")` … 里**没有** `review.review_document` |
| C 拿不到 H 的写 | `for_role("C")` 里**没有** `review.review_document` |
| 写面不扩张 | H 的可见写工具**恰好**是那两件（集合相等，不是"包含"） |
| 写集不扩张 | 那两件的 `tx.upsert` 目标**只能**是 `review_findings` / `documents`（AST 判据或逐字登记） |
| S2 不回归 | `_do_summon` 仍然不读 `payload["action"]`；任务行 `action` 仍为 `""` |

## 5. 判据清单（正控）

1. `"review.review_document" in for_role("H")` ⇒ 可见；
2. H 调 `review.review_document(doc_id=<真实稿>)` ⇒ **`review_findings` 真的 +1 行**（真机/集成级）；
3. **"审过 ≠ 通过"**（与 schema 提案联动）：`review_verdict="有毛病"` ⇒ 审过 ≥1 而 `accepted_documents == 0`。

## 6. 不在本提案范围

- **schema 的审核轴**（`review_verdict`/`reviewed_at`/`reviewed_by`）⇒ 另一份提案
  `docs/SCHEMA-MIGRATION-PROPOSAL-review-axis.md`（已按业主裁定**不抬 `SCHEMA_VERSION`**）；
- **H 的"通过标准与 V 同形"** 的行为面（逐条硬禁令 / 依赖闭合查过 / `unverified` 不许判通过）
  ⇒ `specs/h.py` 的措辞改动，与本节分开走；
- **C 的具体写件名**：实现时按 `specs/c.py` 的 `write_set` 落地，不在提案里发明。
