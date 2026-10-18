# 迁移提案：给 `documents` 加一根**审核轴**（"审过" ≠ "通过"）

> 提案性质：**禁改区（schema-migration）**改动的前置文档。按 `AGENTS.md` 的规矩，
> 这类改动要**人编写或人逐行走查**并 **2 名 reviewer approve**。本文件是给那两位 reviewer 的输入，
> **不是**已批准的决议。
>
> 业主口径（2026-10-17 逐字）：**"H 审过和通过是完全不同的状态。通过标准和 V 一样。H 和 C 都能落 note。"**

---

## 1. 现状：一个字段兼任两种语义（代码与判据都有自述）

`closing.py:1009-1015`：

```python
if kind == "reviewed_documents":
    rows = [r for r in store.rows("documents")
            if str(r.get("status") or "") in REVIEWED_DOC_STATUSES     # 「通过」被当成「审过」
            or int(r.get("review_rounds") or 0) >= 1]                  # 「改过稿」被当成「审过」
```

`tests/test_closing_gate.py:336-342` 逐字解释了为什么只能这么写：

> *"第 9 趟实测：`documents/0000` 是 `status=accepted`、`review_rounds=0`（**H 审过并给了裁决**，
> 而"轮次"只在真的改过稿时才加）。按 `review_rounds >= 1` 判会把它读成"没审过" ——
> **判据恒红，于是没人再信它**。所以这一档要认 H 的裁决本身。"*

⇒ 根因：**台账里没有一个字段记录"审过"这件事**，于是收工门只能用"通过"（`status`）
或"改过几轮"（`review_rounds`）当**代理**。

`schema.py:1138`：`DOC_STATUSES = ("draft", "in_review", "revised", "accepted", "rejected", "unresolved_review")`
—— `accepted` 同时被读成"审过"和"通过"。

---

## 2. 提案（**纯增量**，向后兼容）

给 `Document`（`schema.py:1641`）加三个**带默认值**的字段：

| 字段 | 类型 | 默认 | 语义 | 唯一写入方 |
|---|---|---|---|---|
| `review_verdict` | `str` | `""` | 一次审核的**裁决**，取值与 V 的 `verify_proof` **同形**：`""`（**未审**）/ `成立` / `有毛病` / `看不出来` | **H** 的固定流程（`H.review`；经它的落库代理） |
| `reviewed_at` | `str` | `""` | 裁决写下时的时间戳（ISO） | 同上 |
| `reviewed_by` | `str` | `""` | 写下裁决的是谁（`agent-H`） | 同上 |

**`status` 的语义收敛**：只表示**稿件生命周期**（`draft` / `in_review` / `revised`）；
"通过"**不再由 `status` 承担**，而是 `review_verdict == "成立"`。

**为什么是纯增量**：三个字段都有默认值（`""`），旧行读回来就是"未审"，**磁盘上不需要重建**；
`SCHEMA_VERSION` 是否要抬一格由 reviewer 定（见 §5 的取舍）。

---

## 3. 随之要改的读数（收工门）

| 读数 | 现在 | 提案 |
|---|---|---|
| `reviewed_documents`（**审过**） | `status ∈ accepted/revised` **或** `review_rounds ≥ 1` | **`review_verdict != ""`** |
| **新增** `accepted_documents`（**通过**） | 不存在 | **`review_verdict == "成立"`**（这才是"通过标准和 V 一样"） |
| `reviewed_current_rows`（审的是不是现行版） | 已有（读 `doc-signatures` 的 `content_sha256`） | **保留**，与上面两根轴成三角形：**审过** / **通过** / **审的是现行版** |

## 4. 判据要跟着改（这是本提案最要紧的一半）

- `tests/test_closing_gate.py:336`（`test_the_reviewed_documents_leg_counts_hs_verdict_not_only_revision_rounds`）
  守的旧命题（"`status=accepted` 必须算审过"）**要按新口径重写**，改成三条：
  1. **审过 ≠ 通过**：`review_verdict="有毛病"` ⇒ `reviewed_documents ≥ 1` 但 `accepted_documents == 0`；
  2. **通过 = 与 V 同形**：`review_verdict="成立"` ＋ 依赖闭合查过 ⇒ 两条读数都 ≥ 1；
  3. **负控**：`review_verdict=""`（未审）而 `status=accepted` ⇒ **不许**算"审过"（这正是旧口径的错误形态）。
- 新增一条判据：**H 的落库代理只能写这三个字段 ＋ `status`／`review_rounds`**（写面钉死，不断扩）。

## 5. 取舍（**已裁定**）

1. **`SCHEMA_VERSION` 不抬**（业主 2026-10-17 裁定，逐字："SCEMA_VERSION不抬"）：
   三个字段是**纯增量、带默认值**，旧行读回来就是"未审" ⇒ **磁盘不需要重建**；抬版本会让旧工作区被判"版本不符"。
   ⇒ reviewer 只需审"字段与写面"，不必审版本号。
2. **`status` 是否允许保留 `accepted`**：本期**保留**（历史行还有这个值），但**读数不再用它当"审过"**；
   长期可否淘汰 → 另案。

## 6. 不在本提案范围（另行提案）

- **H 的"通过"标准与 V 一样**这件事里**行为**的一半（逐条硬禁令、依赖闭合查过、`unverified` 不许判通过）
  ⇒ 落在 `specs/h.py`（auth-audit 禁改区）的手册改动，与 schema 分开走；
- **H/C 落 note**：机制已存在（`note` 是循环协议的一个形状，落 `notes/<角色>.md`，不受工具面约束），
  只需在手册里点明。
