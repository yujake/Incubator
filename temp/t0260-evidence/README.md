# `t-0260` 的两行原始读数（从 `review-task-20260930-111332` 摘出）

**这份目录是什么**：一条真机运行（2026-09-30 11:13–11:18 那一趟 review 任务）的
台账读数摘录。它存在的唯一理由是：`src/agentflow/agent_loop.py` 与
`tests/test_agent_loop.py` 各有一条判据引用它 —— 那两条判据说的是同一个 bug：
子循环的 `summoned_by` / `depth` 以前读的两个键**全仓没有任何地方生产**
⇒ 每一次被同伴唤起的角色都以为"是主控直接派的、深度 1"，
协同链在孩子自己的认知里断掉（`§198` 修的就是这个）。

**为什么不是整份工作区**：源目录实测 202 个文件 / 10.66 MB，
是机器本地的运行产物（`ws/data/`、`ws/out/`、`ws/sessions/`、`ws/runs/`）。
为一处引用整仓入库不成比例，所以只入库两样东西：
① 本文件（两行读数逐字 + 复算命令）；② `tasks.json`（**逐字节拷**，未改一个字段）。
**没入库的**：其余 201 个文件（含 `ws/sessions/review-task.jsonl` 1.1 MB、
`ws/data/events.jsonl` 2.7 MB、`ws/out/paper/` 的编译产物），它们仍在
`temp/review-task-20260930-111332/` 下（机器本地，随时可删）。

## 读数一：台账（`tasks` 表的行，`called_by` / `depth` 都在上面）

摘自 `tasks.json` 的 `rows`（该文件逐字节拷自
`temp/review-task-20260930-111332/ws/data/tasks.json`，
sha256 `5a8fc091e4ca75af43d9253c11604920f6bf9f0a4f1267258eb5ebd6b1413487`，161232 字节，268 行）：

```json
{"task_id": "t-0259", "role": "F", "action": "step", "called_by": "M", "parent_task_id": null, "depth": 1, "input_key": "", "status": "done", "outcome": "ok", "refusal_reason": null, "detail": "执行完成（handler 未声明 outcome，按有产出处理）", "error": null, "started_at": "2026-09-30T11:13:55+08:00", "ended_at": "2026-09-30T11:15:22+08:00", "tokens": 0, "usd": 0.0, "artifacts": ["out/tasks/t-0259.json"], "inputs": ["tokenmeter:settled"]}
```

```json
{"task_id": "t-0260", "role": "E", "action": "run_experiment", "called_by": "F", "parent_task_id": "t-0259", "depth": 2, "input_key": "", "status": "done", "outcome": "ok", "refusal_reason": null, "detail": "执行完成（handler 未声明 outcome，按有产出处理）", "error": null, "started_at": "2026-09-30T11:14:06+08:00", "ended_at": "2026-09-30T11:14:41+08:00", "tokens": 0, "usd": 0.0, "artifacts": ["out/tasks/t-0260.json"], "inputs": ["tokenmeter:settled"]}
```

读法：`t-0260`（E 的 `run_experiment`）是 `called_by=F`、`parent_task_id=t-0259`、
`depth=2` —— 它是被 **F** 唤起的，在第 **2** 层；而 `t-0259`（F 的 `step`）才是
`called_by=M`、`depth=1`。

## 读数二：E 自己的认知（`agent_run_start`）

摘自 `temp/review-task-20260930-111332/ws/sessions/review-task.jsonl`
（那一行不在入库面里，逐字贴在这里）：

```json
{"depth": 1, "kind": "agent_run_start", "prompt_sha256": "2bb27b13e4fd5400b4fdfacda9323e3cf54384e015f355db0e37dd61c503bc3f", "prompt_version": "p16", "role": "E", "summoned_by": "M", "task": "E.run_experiment：调用方给了这些参数：\n- claim：lem:varconst 的剖面方差与变分常数 V_m = 8m(m+1)/3 对 m=1..6 成立\n- claim_key：lem:varconst\n- script_path：out/p2-claims-ledger.md", "task_id": "t-0260", "ts": "2026-09-30T11:14:06+08:00"}
```

读法：同一次调用，E 自己记的是 `summoned_by=M`、`depth=1` —— 与台账那一行
（`called_by=F`、`depth=2`）**对不上**。这就是那两条判据引用的现象。

## 复算命令（在源目录还在的机器上）

```powershell
# 读数一（台账）
python -c "import json,pathlib;rows=json.loads(pathlib.Path('ws/data/tasks.json').read_text(encoding='utf-8'))['rows'];print([r for r in rows if r['task_id'] in ('t-0259','t-0260')])"
# 读数二（E 自己的认知）
Select-String -Path ws/sessions/review-task.jsonl -Pattern 'agent_run_start' |
  Where-Object { $_.Line -match '"role": "E"' }
```

## 这份摘要的边界（别把它读成更多东西）

- 它证明的是"**那一次运行里出现了认知与台账不一致**"这个现象本身，
  以及"权威来源应当是台账那一行"这个判断的依据；
- 它**不**证明今天的代码仍然如此 —— 恰恰相反：`§198` 之后子循环改读台账那一行，
  判据是 `tests/test_agent_loop.py::test_a_child_loop_knows_who_summoned_it_and_how_deep_it_is`；
- 两行读数都是**机器写出来的原始记录**，我没有改过任何字段（`tasks.json` 逐字节拷、
  `agent_run_start` 那行逐字贴）。要验前者，比 sha256；要验后者，回源目录看那一行。
