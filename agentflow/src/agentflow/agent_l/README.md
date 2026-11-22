# agent_l —— L：Lean 形式化

**职责（声明原文）**：Lean 形式化 —— 把 B 登记的那条命题与它的证明链路**忠实**搬进 Lean 源码，
交给检查器真跑，并如实报 `verified` / `failed` / `unknown`。
**典型误根**：把没跑成的检查写成 `verified` 或 `failed`（`unknown` 被折进另外两档，
读者就分不出"命题可疑"还是"我们没验"）。

- 声明在 [`../specs/l.py`](../specs/l.py)：3 个动作（`formalize` / `check_formal` / `record`）、
  入边只有 `B`、出边只有 `C`、写集只有 `experiments` 一格。实现类 `agent_l:AgentL`。
- "L 绕不过 V 签给命题升档"的真拦点是 `store.direct_write_refusal`（通用写口拒写
  `statements` / `dependencies`）＋ 秘书那一道 not_statement_writer 判据 —— 不是写集。
- **谁读**：改形式化桥接 / Lean 证据读数的人。

## 文件

| 文件 | 是什么 |
|---|---|
| `core.py` | `AgentL` 骨架：构造期 / 路径守卫 / 自检闸 / 结论形状 |
| `formalize.py` | 动作 `formalize`：命题 → `.lean` 落盘（`code/formal/<声明名>.lean`）→ 真跑检查器 |
| `check_formal.py` | 动作 `check_formal`：`_CheckFormalL`，继承 E 的实现体 + 前置自检闸 |
| `record.py` | 动作 `record`：一次形式化检查登记成 `experiments` 一行（`method="formal"`） |
| `report.py` | 向 **B** 汇报形式化困难这一格（走既有的 `agent_message` 收件箱） |
| `_support.py` | 受控词表与小工具（理由词表从 `agent_e._support` 借，只追加本角色两档） |
| `__init__.py` | 导出 `AgentL`（**没有 `__main__.py`**：不能用 `python -m agentflow.agent_l` 自检） |

## 怎么用

```powershell
# 没有 __main__；要跑就经工具面或经 B 派活
python -m agentflow.cli --root D:\Incubator\temp\ws run-agent L --task "把这条命题形式化并交给检查器"

# Lean 在这台机器上可用吗（真自检：版本 / sha256 / 正例 / 反例）
python -c "import sys; sys.path.insert(0,'src'); from agentflow import toolchain as TC; r=TC.toolchain_report(); print(r['lean_ready'], r['lean_path'], r['lean_version'])"

# 本目录声明的动作数（现算；本文件开头写的那个数字就是它的输出）
python -c "import sys;sys.path.insert(0,'src');from agentflow import specs;print(len(specs.builtin_specs()['L'].actions))"
```

Lean 不可用时每一次形式化都以 `unknown` 落，原因是 `lean_disabled` / `no_backend` 之一 ——
两档分开，因为改法不同。

## 邻居

入边只有 **B**（派形式化）；出边只有 **C**（梳理证明链）。它与 **E** 的边界：
E 的动作面已经没有形式化（`formal_not_in_e`），`agent_e/check_formal.py` 的实现体仍在原处、
由 L 继承 —— 桥接层与路径守卫只有一份。
