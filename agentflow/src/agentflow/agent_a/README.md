# agent_a —— A：文献检索

**职责（声明原文）**：文献检索 —— 把搜索请求变成已登记的文献行，并如实报告每一次失败。
**典型误根**：把"一条候选被丢掉"说成"这篇文献不存在"。

- 声明在 [`../specs/a.py`](../specs/a.py)（禁改区族）：6 个动作、出边只有 `B`、
  写集 `literature` + `search_requests`、可召唤。
- 实现类是 `agent_a:AgentA`；本目录只放"怎么做"，不重复声明。
- **谁读**：要改 A 的人。模型读的是渲染后的提示词与 `skills/`，不是本文件。

## 文件

| 文件 | 是什么 |
|---|---|
| `core.py` | `AgentA` 骨架：把下面各动作的 mixin 装起来 |
| `run_once.py` | 动作 `run_once`：领一条待办检索请求并跑完（搜索 + 登记 + 下载） |
| `run.py` | 动作 `run`：连续领跑到没有可领的（有界 `max_requests`） |
| `search_literature.py` | 动作 `search_literature`：按主题现查一次，过 I7 准入闸门 |
| `ingest_local.py` | 动作 `ingest_local`：把盘上文件登记成 `literature` 行（按 sha256 幂等） |
| `shelf_search.py` | 动作 `shelf_search`：本地书架检索（不联网） |
| `walk_citations.py` | 动作 `walk_citations`：沿引文图走一步（回溯 / 前推） |
| `clear_stage.py` | 收尾自驱：这一拍结束时清掉该清的表（不是声明动作） |
| `selftest.py` | 零模型的离线自检（`__main__.py` 调它） |
| `_support.py` | 包内共用的小工具 |

## 怎么用

```powershell
# 零模型自检：把 A 的动作逐条在临时工作区里跑一遍
python -m agentflow.agent_a

# 真跑一条角色循环（要模型 key；没有 key ⇒ 退出码 2 + 一行说明）
python -m agentflow.cli --root D:\Incubator\temp\ws run-agent A --task "检索 abelian group 的经典结果"

# 本目录声明的动作数（现算；本文件开头写的那个数字就是它的输出）
python -c "import sys;sys.path.insert(0,'src');from agentflow import specs;print(len(specs.builtin_specs()['A'].actions))"
```

## 邻居

派它的是 **M**（或 D 经 M 的路）⇒ 它交给 **B** 收编；检索失败要如实落 `search_requests` 的
`outcome` 与 `last_error`，不许把"没查成"写成"没有"。判据见
`tests/test_a_*.py` 与 `tests/test_user_quickstart.py` 的离线 A 路径。
