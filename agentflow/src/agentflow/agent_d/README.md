# agent_d —— D：研究循环

**职责（声明原文）**：研究循环 —— 把一个研究方向收敛成一个有证据支撑的结论，或如实说证据不足。
**典型误根**：把没有证据写成没有争议。

- 声明在 [`../specs/d.py`](../specs/d.py)：14 个动作、出边 `A/B/C/E/F`、写集
  `research_questions` + `search_requests`。实现类 `agent_d:AgentD`。
- 跨趟交付物是 `manuscripts/D/RESEARCH.md`（七节：成果概述 / 定义与已知 / 已确定的结论 /
  尝试与失败 / 例子与反例 / 未解问题 / 下一步）—— 下一趟接手的人先读它。
- **谁读**：改研究循环的人；D 的动作数最多，每个动作一个文件。

## 文件

| 文件 | 是什么 |
|---|---|
| `core.py` | `AgentD` 骨架（装 mixin） |
| `propose_question.py` | 动作 `propose_question`：一句话研究问题 → `research_questions` 一行 |
| `run_round.py` | 动作 `run_round`：把 ingest → … → research 串成一圈（有界 `limit`） |
| `ingest.py` / `ingest_detailed.py` | 动作：把一份 C 报告消化成研究问题（后者带逐条明细） |
| `poll.py` | 动作 `poll`：新到的文献是否答上了在等的问题 |
| `assess.py` | 动作 `assess`：判证据是否就绪（决定要不要向 A 要检索） |
| `submit_gaps.py` | 动作 `submit_gaps`：把缺口提交成检索请求 |
| `research.py` | 动作 `research`：回答一个证据就绪的问题 |
| `write_report.py` | 动作 `write_report`：把研究结果渲染成 markdown（缺省 `manuscripts/D/<qid>-research.md`；旧落点 `reports/` 已退役） |
| `probe_c.py` | 动作 `probe_c`：按问题向 C 点菜并记录问答 |
| `consider.py` | 动作 `consider`：重新考虑一个问题（可能提到 researching） |
| `adjudicate.py` | 动作 `adjudicate`：裁决一条矛盾问题（I2 闭环） |
| `trace_question.py` | 动作 `trace_question`：把问题溯源到 L1/L2/L3 证据 |
| `trace_l3.py` | 动作 `trace_l3`：按需下钻到文献正文那一段 |
| `_support.py` | 包内共用的小工具（与其它角色同形） |

## 怎么用

```powershell
python -m agentflow.agent_d        # 零模型自检
python -m agentflow.cli --root D:\Incubator\temp\ws run-agent D --task "把这个问题研究到有结论或如实说证据不足"

# 本目录声明的动作数（现算；本文件开头写的那个数字就是它的输出）
python -c "import sys;sys.path.insert(0,'src');from agentflow import specs;print(len(specs.builtin_specs()['D'].actions))"
```

## 邻居

上游：**C** 的分析报告 + **B** 的命题台账。下游：**A**（要检索）、**F**（攻坚）、**E**（实验）、
**B**（结论入库）。D **不许**把证明稿正文塞给别人 —— 它只递指针（判据
`tests/test_d_does_not_land_the_proof.py` 一族）。
