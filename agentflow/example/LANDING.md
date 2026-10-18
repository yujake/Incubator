# 每个智能体的标志性产物 —— 落地审查（$0）

这一份由 `example/land_artifacts.py` 生成：**每个角色用它自己的声明动作**把标志性产物落一遍（经 `Conductor.summon` 那条真路，含边/深度/扇出准入），再逐条查「台账行 + 盘上文件 + 文件非空 + 该动作特有的那一件」。

- 工作区：`example/ws/`（可重跑：`python -B example/land_artifacts.py`）
- 模型调用：**0 次**（不接线模型 + `RuleExtractor`）；`usage_ledger` **9 行** / **$0.000000**
- 判定：**7 条没落成**

| 角色 | 动作 | 标志性产物 | 台账 | 盘上文件 | 字节 | 判定 |
|---|---|---|---|---|---|---|
| A | `ingest_local` | 文献登记 + 全文入库 | 0 | — | — | ❌ |
| B | `run` | 概念与关系（抽取产物） | 0 | — | — | ❌ |
| C | `hottest` | 关系分析报告 | 0 | — | — | ❌ |
| D | `propose_question` | 研究问题一行 | 1 | — | — | ✅ |
| E | `run_experiment` | 实验行 + 原始输出日志 | 1 | `out/experiments/000000.log` | 317 | ✅ |
| F | `create_plan` | 攻坚计划一行 | 1 | — | — | ✅ |
| B | `register_statement` | 命题一行 | 0 | — | — | ❌ |
| V | `verify_proof` | 逐行走查的回执 | — | — | — | ❌ |
| G | `build_document` | 稿件一行 + 渲染出的正文 | 0 | — | — | ❌ |
| H | `review` | 审校：稿件状态被它改过 | — | — | — | ❌ |
| 共用 | `状态报告（md）` | 状态报告（md） | — | `out/review/STATUS-20261015-1705.md` | 3236 | ✅ |
| 共用 | `状态报告（json）` | 状态报告（json） | — | `out/review/STATUS-20261015-1705.json` | 10088 | ✅ |
| 共用 | `交接手稿` | 交接手稿 | — | `manuscripts/handoffs.jsonl` | 624 | ✅ |

## 十次召唤的结局（`summon` 的返回值，逐条）

| 角色 | 动作 | 召唤方 | status | outcome | 拒绝理由 |
|---|---|---|---|---|---|
| A | `ingest_local` | M | done | refused | not_wired |
| B | `run` | M | done | no_result | — |
| C | `hottest` | M | done | ok | — |
| D | `propose_question` | M | done | ok | — |
| D | `write_report` | M | done | ok | — |
| E | `run_experiment` | M | done | ok | — |
| F | `create_plan` | D | done | ok | — |
| B | `register_statement` | M | done | refused | invalid_params |
| G | `build_document` | M | done | refused | invalid_params |

> 结局不是 `ok` 的那几条，原文如下：

- `A.ingest_local`（召唤方 M）：refused / not_wired — A 没有接线（registry 里没有它）
- `B.run`（召唤方 M）：no_result / 无理由 — 真消化 0 篇（新建概念 0 / 复用 0 / 新增关系 0 / 引文判定 0）；没有本地全文 0 篇、缺抽取器 0 篇、放弃 0 篇、失败 0 篇；队列：no_unprocessed_literature ⇒ 这一趟**没有任何产出**（不是成功，别按成功读）
- `B.register_statement`（召唤方 M）：refused / invalid_params — [handler_ok=False kind=missing_source] origin='external_lit' 时必须给 source_lit_id —— 从文献摘的命题必须有出处（没有出处的摘录就是二手结论）
- `G.build_document`（召唤方 M）：refused / invalid_params — G.build_document 拒绝了这次调用：doc.build_document 调用失败：校验失败：断言原文：「交换群的每个子群都是正规子群（引自本地夹具文献）。」（claims[1]／claim-1）未通过机械检查：断言 claim-1 的 disclaimer 不是这一档的受控那一句。应当逐字写「数值交叉验证，不构成证明」，而现在是「示例用：证据链只到「本地夹具文献」这一级」—— 三态

## 读数明细（机器可复核）

```json
{
 "steps": [
  {
   "role": "A",
   "action": "ingest_local",
   "label": "文献登记 + 全文入库",
   "table": "literature",
   "rows": 0,
   "path": "",
   "bytes": 0,
   "ok": false,
   "extra": ""
  },
  {
   "role": "B",
   "action": "run",
   "label": "概念与关系（抽取产物）",
   "table": "relations",
   "rows": 0,
   "path": "",
   "bytes": 0,
   "ok": false,
   "extra": ""
  },
  {
   "role": "C",
   "action": "hottest",
   "label": "关系分析报告",
   "table": "analysis_reports",
   "rows": 0,
   "path": "",
   "bytes": 0,
   "ok": false,
   "extra": ""
  },
  {
   "role": "D",
   "action": "propose_question",
   "label": "研究问题一行",
   "table": "research_questions",
   "rows": 1,
   "path": "",
   "bytes": 0,
   "ok": true,
   "extra": ""
  },
  {
   "role": "E",
   "action": "run_experiment",
   "label": "实验行 + 原始输出日志",
   "table": "experiments",
   "rows": 1,
   "path": "out/experiments/000000.log",
   "bytes": 317,
   "ok": true,
   "extra": ""
  },
  {
   "role": "F",
   "action": "create_plan",
   "label": "攻坚计划一行",
   "table": "attack_plans",
   "rows": 1,
   "path": "",
   "bytes": 0,
   "ok": true,
   "extra": ""
  },
  {
   "role": "B",
   "action": "register_statement",
   "label": "命题一行",
   "table": "statements",
   "rows": 0,
   "path": "",
   "bytes": 0,
   "ok": false,
   "extra": ""
  },
  {
   "role": "V",
   "action": "verify_proof",
   "label": "逐行走查的回执",
   "table": "",
   "rows": null,
   "path": "",
   "bytes": 0,
   "ok": false,
   "extra": ""
  },
  {
   "role": "G",
   "action": "build_document",
   "label": "稿件一行 + 渲染出的正文",
   "table": "documents",
   "rows": 0,
   "path": "",
   "bytes": 0,
   "ok": false,
   "extra": ""
  },
  {
   "role": "H",
   "action": "review",
   "label": "审校：稿件状态被它改过",
   "table": "",
   "rows": null,
   "path": "",
   "bytes": 0,
   "ok": false,
   "extra": " → (没读回)（review 返回：{}）"
  },
  {
   "role": "共用",
   "action": "状态报告（md）",
   "label": "状态报告（md）",
   "table": "",
   "rows": null,
   "path": "out/review/STATUS-20261015-1705.md",
   "bytes": 3236,
   "ok": true,
   "extra": ""
  },
  {
   "role": "共用",
   "action": "状态报告（json）",
   "label": "状态报告（json）",
   "table": "",
   "rows": null,
   "path": "out/review/STATUS-20261015-1705.json",
   "bytes": 10088,
   "ok": true,
   "extra": ""
  },
  {
   "role": "共用",
   "action": "交接手稿",
   "label": "交接手稿",
   "table": "",
   "rows": null,
   "path": "manuscripts/handoffs.jsonl",
   "bytes": 624,
   "ok": true,
   "extra": ""
  }
 ],
 "summons": [
  {
   "role": "A",
   "action": "ingest_local",
   "by": "M",
   "status": "done",
   "outcome": "refused",
   "refusal_reason": "not_wired",
   "detail": "A 没有接线（registry 里没有它）",
   "task_id": "t-000001"
  },
  {
   "role": "B",
   "action": "run",
   "by": "M",
   "status": "done",
   "outcome": "no_result",
   "refusal_reason": "",
   "detail": "真消化 0 篇（新建概念 0 / 复用 0 / 新增关系 0 / 引文判定 0）；没有本地全文 0 篇、缺抽取器 0 篇、放弃 0 篇、失败 0 篇；队列：no_unprocessed_literature ⇒ 这一趟**没有任何产出**（不是成功，别按成功读）",
   "task_id": "t-000002"
  },
  {
   "role": "C",
   "action": "hottest",
   "by": "M",
   "status": "done",
   "outcome": "ok",
   "refusal_reason": "",
   "detail": "执行完成",
   "task_id": "t-000003"
  },
  {
   "role": "D",
   "action": "propose_question",
   "by": "M",
   "status": "done",
   "outcome": "ok",
   "refusal_reason": "",
   "detail": "执行完成（handler 未声明 outcome，按有产出处理）",
   "task_id": "t-000004"
  },
  {
   "role": "D",
   "action": "write_report",
   "by": "M",
   "status": "done",
   "outcome": "ok",
   "refusal_reason": "",
   "detail": "执行完成",
   "task_id": "t-000005"
  },
  {
   "role": "E",
   "action": "run_experiment",
   "by": "M",
   "status": "done",
   "outcome": "ok",
   "refusal_reason": "",
   "detail": "执行完成（handler 未声明 outcome，按有产出处理）",
   "task_id": "t-000006"
  },
  {
   "role": "F",
   "action": "create_plan",
   "by": "D",
   "status": "done",
   "outcome": "ok",
   "refusal_reason": "",
   "detail": "执行完成（handler 未声明 outcome，按有产出处理）",
   "task_id": "t-000007"
  },
  {
   "role": "B",
   "action": "register_statement",
   "by": "M",
   "status": "done",
   "outcome": "refused",
   "refusal_reason": "invalid_params",
   "detail": "[handler_ok=False kind=missing_source] origin='external_lit' 时必须给 source_lit_id —— 从文献摘的命题必须有出处（没有出处的摘录就是二手结论）",
   "task_id": "t-000008"
  },
  {
   "role": "G",
   "action": "build_document",
   "by": "M",
   "status": "done",
   "outcome": "refused",
   "refusal_reason": "invalid_params",
   "detail": "G.build_document 拒绝了这次调用：doc.build_document 调用失败：校验失败：断言原文：「交换群的每个子群都是正规子群（引自本地夹具文献）。」（claims[1]／claim-1）未通过机械检查：断言 claim-1 的 disclaimer 不是这一档的受控那一句。应当逐字写「数值交叉验证，不构成证明」，而现在是「示例用：证据链只到「本地夹具文献」这一级」—— 三态",
   "task_id": "t-000009"
  }
 ],
 "spent_usd": 0.0,
 "ledger_rows": 9,
 "status_before": "",
 "status_after": ""
}
```
