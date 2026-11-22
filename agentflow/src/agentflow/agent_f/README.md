# agent_f —— F：多轮难题攻坚

**职责（声明原文）**：多轮难题攻坚 —— 在预算内一轮一轮逼近平息或反例，并如实报告进展。
**典型误根**：把无变化写成有进展。

- 声明在 [`../specs/f.py`](../specs/f.py)：5 个动作、出边 `A/C/D/E/V`、写集
  `attack_plans` + `conjectures` + `reprocess_requests` + `search_requests`。
- 实现类 `agent_f:AgentF`。**交差要拿 V 签**：每份稿的 `v_sign` 必须是"已签"，
  没签不算交差（读数在 `vsign.py` / `delivery.py`）。
- **谁读**：改攻坚流程 / 稿与签那条链的人。

## 文件

| 文件 | 是什么 |
|---|---|
| `core.py` | `AgentF` 骨架（装 mixin） |
| `create_plan.py` | 动作 `create_plan`：立项（预算四键不齐即拒，不写库） |
| `step.py` | 动作 `step`：推进一轮（唯一会改计划的方法）；`product` 可直接交写好的证明/归约 |
| `status.py` | 动作 `status`：只读看一条计划的当前状态 |
| `list_plans.py` | 动作 `list_plans`：只读列举计划 |
| `abandon_plan.py` | 动作 `abandon_plan`：明确放弃（理由三档：数学错误 / 难以逾越 / 不再需要） |
| `manuscript.py` | 证明手稿：依赖段由 F 写在这里，依赖台账由 B 读稿登记 |
| `vsign.py` | "V 签"读数：拿到签才允许交差 |
| `delivery.py` | 交差读数：按条读，不是"一条签到手就交差" |
| `pending.py` | "已登记、V 签还没到"的稿：一处扫描、三个读者共用 |
| `submission.py` | 收工自动提交的读那一半 |
| `autosubmit.py` | 收工自动提交的写那一半（写进 F 自己那一行的 `tasks.artifacts`） |
| `_support.py` | 包内共用小工具 |

## 怎么用

```powershell
python -m agentflow.agent_f        # 零模型自检
python -m agentflow.cli --root D:\Incubator\temp\ws run-agent F --task "攻这条猜想，一轮一轮来"

# 本目录声明的动作数（现算；本文件开头写的那个数字就是它的输出）
python -c "import sys;sys.path.insert(0,'src');from agentflow import specs;print(len(specs.builtin_specs()['F'].actions))"
```

## 邻居

上游：**D**（派攻坚）。下游：**V**（送审拿签）、**E**（要实验）、**A**（要文献）、
**B**（收录）、**C**（梳理证明链）。计划关不关由稿决定：未拿签的计划**不关**
（连续无进展、轮数用尽都不关它）；要提前收场只能走 `abandon_plan`。
