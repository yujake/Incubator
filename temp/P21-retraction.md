# `P-21` **撤回**：前提不成立（两个词表被串了）—— 观测 2026-09-26T03:27

## 登记册原文（`docs/PROPOSALS.md` 的 `P-21`）

> **现状**：`schema.py:SEARCH_OUTCOMES` 登记的值是 **`no_result`**；
> 而 `verify.py` 在注释与报错提示文案里写的是 **`no_results`**。
> **建议修法**：把 `verify.py` 的两处文案改成 `no_result`（**人改，禁改区**）。
> **不许**反过来把词表改成 `no_results`……

## 实测（`temp/_probe_p21.py` → `temp/p21-probe.txt`）

```
SEARCH_OUTCOMES = ('ok', 'no_results', 'search_failed', 'gave_up')          ← 登记值就是 no_results（复数）
TASK_OUTCOMES   = ('ok', 'no_result', 'not_applicable', 'refused', 'failed', 'cancelled')   ← 这里才是 no_result（单数）

SEARCH_OUTCOMES 里有 'no_results' = True ；有 'no_result'  = False
TASK_OUTCOMES   里有 'no_result'  = True ；有 'no_results' = False
```

逐文件（`src/`，词边界计数）：

| 文件 | `no_results` | `no_result` | 判读 |
|---|---|---|---|
| `agent_a.py` | 2 | 0 | 搜索请求的 `outcome` |
| `evidence.py` | 19 | 0 | 搜索/来源状态 |
| `verify.py` | 4 | 0 | 搜索请求审计 —— **与 `SEARCH_OUTCOMES` 一致** |
| `tools/research_tools.py` | 1 | 0 | 同上 |
| `conductor.py` | 0 | 5 | **另一个字段** `tasks.outcome` |
| `schema.py` | 3 | 3 | 两个词表各自的定义与提示文案 |

`schema.py` 里两处的原文：
```
 76: SEARCH_OUTCOMES = ("ok", "no_results", "search_failed", "gave_up")
220: "done=true 时必须给出 outcome（ok/no_results/search_failed/gave_up）"
1274: TASK_OUTCOMES = ("ok", "no_result", "not_applicable", "refused", "failed", "cancelled")
1371: "status=done 时必须给出 outcome（ok/no_result/not_applicable/refused）"
```

## 结论

**`P-21` 是错的，应当撤回**：`no_results` 是 `SEARCH_OUTCOMES` 的登记值（复数），
`verify.py` 写的就是它 ⇒ **两层本来就一致**。`no_result`（单数）属于**另一个词表**
`TASK_OUTCOMES`（`tasks.outcome`）。登记册把两个词表串了。

## ⚠️ 为什么这条必须公开撤回（不是"改个错别字"）

1. **照 `P-21` 修会制造它自己警告的伤害**：把 `verify.py` 的 `no_results` 改成 `no_result`
   ⇒ 审计文案开始**教人写一个不在 `SEARCH_OUTCOMES` 里的值**——正是 `P-21` 第一段说的
   "文档在教人写词表外的值，比错字严重"。
2. **我自己的 B5 工单 §1.1 就依据了这条错登记**（我照抄了 `P-21` 的建议修法）。
   是工单里那句"**先打出真值再动手、以代码为准**"救了它 —— 这正好印证本项目的纪律：
   **判据/工单不许把"登记册说的"当成"盘上事实"**。已就地更正工单 §1.1。
3. **真正的缺陷是另一件事（FC-22 形态）**：两个词表各有一个**只差一个 `s`** 的取值，
   分别用在 `search_requests.outcome` 与 `tasks.outcome` 上 ——
   "错一个字母、没有任何东西会红"。处置：在词表旁加**护栏注释**互相指认（只加注释，不动取值）。

## 处置

- `verify.py`：**不改**（sha256 应保持不变，由 B5-part-1 在证据里给出这一证明）。
- `schema.py`：加护栏注释（B5-part-1 做；`schema.py` 是禁改区 ⇒ 备份 + 台账基线照旧）。
- 登记册：`P-21` → **撤回（前提不成立）**，并把上面这段证据链附在条目里（由 B6/登记子智能体回写）。
