# src/agentflow —— 产品包本体

> 读这份的人：要在这个包里改东西的人，以及需要快速定位"某个概念住在哪个模块"的编码 agent。
> **改之前先读 [`../../AGENTS.md`](../../AGENTS.md)**；角色行为规格在 `docs/ROLE-SPECS.md`
> 与 `specs/`，本文件只是地图。

## 这个包是什么

"一句话研究意图 → 一份可复算的研究记录"。主控（`conductor.py` 的 `Conductor`，角色 M）
派十个角色（A–H、L、V）干活；每个动作都落在工作区的台账里，台账可重建、可审计。
入口是 `cli.py`，默认工作区是检出目录本身（`cli.DEFAULT_ROOT`）。

谁读它：人读模块与 docstring；**模型不读 Python 源码**，它拿到的是由 `specs/` 声明
派生的提示词与工具面（`python -m agentflow.cli tools --role <R>` 打印的那一份）。

## 模块地图（按"你要找什么"分组）

| 你找的是 | 去哪 |
|---|---|
| **角色实现** | `agent_a/` … `agent_v/` 十个子包（一个动作一个文件，判据 `tests/test_agent_split_is_one_action_one_file.py`），主控在 `conductor.py` |
| **角色的声明**（动作 / 边 / 写集 / 职责） | `specs/*.py`（禁改区族，FC-27 auth-audit）→ 由 `capabilities.py` 派生成四张表 |
| **工具面**（模型能调什么） | `tools/` 下 19 个 `*_tools.py` + `base.py`（装配、只读过滤、调用期权限判据）。见 [`tools/README.md`](tools/README.md) |
| **台账与存储** | `store.py`（锁 / 原子写 / 事务 / 事件日志 / ID / rebuild）、`schema.py`（表与校验）、`events` 相关在 `jsonlfile.py` / `sessions.py` |
| **派生读数的校验** | `verify.py`（不变量审计）、`closing.py`（收工门）、`gates.py` / `judges.py` / `judge.py` / `obligations.py` |
| **产物健全性** | `wellformed/`（21 个 `.py`：台账、稿件、签、roster、acceptance 各一档）。见 [`wellformed/README.md`](wellformed/README.md) |
| **稿件族** | `manuscript*.py`（14 个：形态、号、冻结、收编、退役、提交…） |
| **命题族** | `statement*.py`（6 个）与 `claimanatomy.py` / `claims.py` |
| **证明族** | `proof*.py`（6 个）、`v_*.py`（18 个，V 的逐项判据） |
| **秘书（跨角色消息与名册）** | `secretary*.py`（37 个）+ `interactions.py`（冻结契约与闸门） |
| **时间与预算** | `clock*.py`（17 个）、`budget.py` / `modelcost.py` / `tokenmeter.py` |
| **模型调用** | `llmseam.py`（统一的缝）、`modelgw.py` / `modelclient.py` / `llm.py` |
| **提示词** | `agent_prompts.py`（版本账在 `docs/PROMPT-HISTORY.md`；写死的正文含 A 的检索式教法 `specs/a.py::SEARCH_STYLE`）、`agent_skills.py`、`promptkit.py`（段与号段） |
| **循环与编排** | `agent_loop.py`（单角色循环）、`pipeline.py`（A→B→C→D）、`runflow.py` / `dispatchpolicy.py` / `stepdispatch.py` |
| **Web / 用户端** | `web/`（令牌与静态产物生成）、`webui/`（服务器、只读面、写面；**禁改区族**） |
| **离线与种子** | `seedinject.py`（离线演示 `demo.py` 已随 2026-11-22 DEMORETIRE 删除）；种子包在 [`../../seed/`](../../seed/README.md) |
| **证明工具链** | `toolchain.py`（"一处定义"）＋ `leantoolchain.py` / `formalgw.py` |

## 怎么用

```powershell
# 看命令行（首屏只列四个组，旧名仍可用；子命令数以 `--help` 现算为准）
python -m agentflow.cli --help

# 看某个角色真正拿到的工具面（权限面以调用期为权威，这份打印是同一处装配出来的）
python -m agentflow.cli tools --role A

# 每个角色包都有一份零模型的离线自检（L 没有 __main__，用 tools 面或判据验）
python -m agentflow.agent_a
python -m agentflow.agent_b
```

## 与谁相邻

- **上游**：同包内的 `specs/`（声明）与 `tools/`（装配）；提示词由 `specs` + `agent_prompts` 合成。
- **下游**：`../../tests/`（判据逐个模块对拍）、`../../scripts/`（门与审计）、`../../tools/`（发布门）。
- **工作区**：运行期一切落在 `<ws>/`，本包不写工作区外面的东西。

## 边界

- `specs/` 与 `webui/` 是 FC-27 禁改区：改它们要 2 名 reviewer（见 `AGENTS.md`）。
- 本包**不保存读数**：文件数、工具数、动作数一律现算（`cli tools`、`capabilities`、
  `schema.TABLES`），文档里抄的数字会漂。

## 上面这些数是现算的（在 `agentflow/` 下跑）

```powershell
python -c "import pathlib; b=pathlib.Path('src/agentflow'); print('tools', len(list((b/'tools').glob('*_tools.py')))); print('wellformed', len(list((b/'wellformed').glob('*.py')))); print('manuscript', len(list(b.glob('manuscript*.py')))); print('statement', len(list(b.glob('statement*.py')))); print('proof', len(list(b.glob('proof*.py')))); print('v_', len(list(b.glob('v_*.py')))); print('secretary', len(list(b.glob('secretary*.py')))); print('clock', len(list(b.glob('clock*.py'))))"
```

