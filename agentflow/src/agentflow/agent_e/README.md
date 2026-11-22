# agent_e —— E：数值实验

**职责（声明原文）**：数值实验 —— 把一条断言变成可复现的实验或反例。
**典型误根**：把跑不过的代码块当成通过。

- 声明在 [`../specs/e.py`](../specs/e.py)：**4 个动作**、出边 `B/D/V`、写集
  `conjectures` + `experiments`。实现类 `agent_e:AgentE`。
- 形式化**不在 E**：`run_experiment(method="formal")` 在第一句就以 `formal_not_in_e`
  受控拒绝，一行不落；形式化归 **L**（`agent_e/check_formal.py` 的实现体仍被 L 继承，
  桥接层只有一份）。
- **谁读**：改实验口径 / 证据等级的人。

## 文件

| 文件 | 是什么 |
|---|---|
| `core.py` | `AgentE` 骨架（装 mixin） |
| `run_experiment.py` | 动作 `run_experiment`：跑脚本 → `experiments` 一行（`numeric` / `symbolic` / `exhaustive_search`） |
| `run_script_experiment.py` | 动作：上面那个的便捷封装（脚本路径必填） |
| `evidence_for.py` | 动作：三态查询（没查 / 查了没有 / 查到了什么） |
| `list_experiments.py` | 动作：只读列举实验 |
| `author_script.py` | 把一份判据写成工作区里的核验脚本（辅助；`--experiment-reasoning` 那条缝） |
| `proposition_form.py` | 数值证明型命题落库前的"命题形态闸"（辅助） |
| `check_formal.py` | 形式化检查的**实现体**（`_CheckFormal`，由 L 的 `_CheckFormalL` 继承） |
| `close.py` | E 的收工读数 |
| `autosubmit.py` | 收工自动提交名下未提交稿 |
| `_support.py` | 包内共用小工具与理由词表 |

## 怎么用

```powershell
python -m agentflow.agent_e        # 零模型自检
python -m agentflow.cli --root D:\Incubator\temp\ws run-agent E --task "把这条断言变成可复现的数值实验"

# 本目录声明的动作数（现算；本文件开头写的那个数字就是它的输出）
python -c "import sys;sys.path.insert(0,'src');from agentflow import specs;print(len(specs.builtin_specs()['E'].actions))"
```

## 邻居

上游：**D**（派实验）或 **B**（要证据）。下游：**V**（穷举那一档送审）、**B**（实验结果入库）。
每个实验都记 `method` / `result`（`supports|refutes|inconclusive`）/ `exit_code`，
脚本落 `<ws>/code/` 且路径记在行上 —— 结果可重跑。
