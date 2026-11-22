# agent_h —— H：审校（只读角色）

**职责（声明原文）**：审校（只读）—— 只判稿件有没有把自己说清楚，不判数学对不对。
**典型误根**：把"这一轮没查出 error"说成"这份稿子没问题"（只有 warning 不等于审过了）。

- 声明在 [`../specs/h.py`](../specs/h.py)：5 个动作、出边 `A/E`、写集
  `documents` + `review_findings`、`read_only=True`。实现类 `agent_h:AgentH`。
- 只读角色在结构上拿不到写工具；它能落库的那几个代理动作逐条登记在
  `../tools/base.py` 的 `READONLY_CALL_EXCEPTIONS`。
- **谁读**：改审校规则的人；H 只判"说清楚没有"，**不判数学对错**（那是 V 的事）。

## 文件

| 文件 | 是什么 |
|---|---|
| `core.py` | `AgentH` 骨架（装 mixin） |
| `review.py` | 动作 `review`：审一份稿件（落发现 + 更新文档状态） |
| `verify_fixes.py` | 动作 `verify_fixes`：复审，逐条判 fixed / 仍 open |
| `list_findings.py` | 动作 `list_findings`：只读列举审校发现 |
| `judge_quote_semantics.py` | 动作：判引文与来源是不是说同一件事（语义档，交回 B 回填） |
| `review_report.py` | 动作 `review_report`：G1–G15 完整审校报告（markdown 落盘） |
| `mapping_judge.py` | 语义审校里"论文对应表"那一档 |
| `_support.py` | 包内共用小工具 |

## 怎么用

```powershell
python -m agentflow.agent_h        # 零模型自检
python -m agentflow.cli tools --role H   # 只读面：应当没有 fs.write / table.create

# 本目录声明的动作数（现算；本文件开头写的那个数字就是它的输出）
python -c "import sys;sys.path.insert(0,'src');from agentflow import specs;print(len(specs.builtin_specs()['H'].actions))"
```

## 邻居

上游：**G**（送稿）。下游：**G**（按 findings 改稿）。"审过"与"签过"是两件事：
H 的 `documents.status` 是审校裁决，V 的签在 `verifications/`；报告与台账是两条记录，
谁也不覆盖谁（`docs` 里有专门一段讲这个区分）。
