"""`G-24②`：`agent_f.step` 的 `outcome` 是一轮推进的结果，另立局部词表。

## 裁定（读代码得来，不是猜）

`step` 把 `outcome` 写进 `AttackPlan.history` 的那一条
（`{"round","sid","action","outcome","detail","evidence","at"}`）—— 它记的是
一个子目标的一轮，而计划要跑很多轮才可能到终局。终局走的是
`schema.ATTACK_STATUSES`（`row["status"]`），不是这个词表；
`schema.TASK_OUTCOMES` 管的是 `tasks.outcome`（一次召唤的终局）。
所以：两套命名空间，取值不重叠，不许互相赋值 —— 裁定写进
`STEP_OUTCOMES` 的注释里，这里用机器判据把它钉住。

## 本文件锁的三条

1. `STEP_OUTCOMES` 与 `schema.TASK_OUTCOMES` 无交集（互相赋值在结构上就不可信）；
2. `agent_f.py` 里所有 `"outcome"` 字面量都在 `STEP_OUTCOMES` 里（AST 普查：
   "代码产出的值词表里没有"正是 `G-24` 的形态）；
3. 写入路径真的过了收口（负控：塞一个词表外的值 ⇒ 抛，而不是照写进 history）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agentflow import agent_f as AF
from agentflow import schema as S

ROOT = Path(__file__).resolve().parents[1]
#: `goal-7f5116c1` M7：`agent_f.py` 拆成了包（`step` 这个动作现在住在 `agent_f/step.py`），
#: 所以下面那条 AST 普查扫整包，不是扫一个文件 —— 否则拆包后判据会静默变真空
#: （`agent_f.py` 不存在 ⇒ 读文件就抛，那还算好的；写成 glob 却漏了目录才是真的静默）。
AGENT_F_SRC = ROOT / "src" / "agentflow" / "agent_f"


def _agent_f_sources() -> list[Path]:
    return sorted(AGENT_F_SRC.glob("*.py"))


def test_step_outcomes_and_task_outcomes_are_disjoint_namespaces():
    """两套词表不许有交集：有交集的话"互相赋值"就再也拦不住。"""
    assert set(AF.STEP_OUTCOMES) == {"no_change", "progress", "blocked"}, AF.STEP_OUTCOMES
    assert not (set(AF.STEP_OUTCOMES) & set(S.TASK_OUTCOMES)), (
        "STEP_OUTCOMES（一轮推进的结果）与 TASK_OUTCOMES（一次任务的终局）取值重叠了"
    )
    # 反向都要成立：把 TASK_OUTCOMES 的值当 step 的 outcome 用 ⇒ 收口必须拒绝
    for value in S.TASK_OUTCOMES:
        with pytest.raises(AF.PlanError):
            AF._step_outcome(value)
    for value in AF.STEP_OUTCOMES:
        assert AF._step_outcome(value) == value


def test_every_outcome_literal_in_agent_f_is_registered():
    """AST 普查：`agent_f`（包）里出现的 `"outcome"` 字面量全部在词表内。

    这就是 `G-24` 的判据形态（代码产出的值必须能被词表登记）。用一个真的解析
    而不是正则，是为了不把注释与字符串里的巧合算进来。
    """
    found: set[str] = set()
    files = _agent_f_sources()
    assert files, f"扫不到任何源码文件：{AGENT_F_SRC} —— 判据的输入面没了"
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if (isinstance(k, ast.Constant) and k.value == "outcome"
                            and isinstance(v, ast.Constant)):
                        found.add(str(v.value))
    assert found, "AST 普查一个 outcome 字面量都没找到 ⇒ 判据本身失效（不是没问题）"
    outside = sorted(found - set(AF.STEP_OUTCOMES))
    assert not outside, (
        f"agent_f 里出现了词表外的 outcome 字面量：{outside}（词表 {AF.STEP_OUTCOMES}）"
    )


def test_the_collection_is_actually_consumed_by_the_write_path():
    """负控：`step` 的写入路径必须真的过收口（登记了却没人读 = 装饰）。

    做法是替换 `_deploy` 让它返回一个词表外的 outcome：`step` 必须在写入前抛，
    而不是把它写进 history —— 若写成 history，停滞检测会静默失效。
    """
    import tempfile

    from agentflow.store import Store

    root = Path(tempfile.mkdtemp(prefix="f-step-outcome-"))
    st = Store(root)
    st.init()
    f = AF.AgentF(st)
    plan = f.create_plan(
        "难题", "k-outcome",
        subgoals=[{"sid": "s1", "text": "子目标", "owner": "E", "script_path": "probes/x.py"}],
        # 三维预算缺一不可（FC-18）：少一个键时 `create_plan` 会拒绝立项，
        # 而"夹具没立项"会让下面的负控在真空里变绿。
        budget={"max_rounds": 3, "max_concurrency": 1, "max_depth": 1,
                "max_parallel_subgoals": 1, "max_persist_attempts": 2},
    )
    assert plan.get("created") is True, plan
    before = st.rows("attack_plans")[0]
    f._deploy = lambda sg, *, plan: {  # type: ignore[assignment]
        "action": "no_change", "outcome": "progres", "detail": "（桩）拼错的值",
        "evidence": [],
    }
    with pytest.raises(AF.PlanError) as ei:
        f.step(plan["plan_id"])
    msg = str(ei.value)
    assert "'progres'" in msg, "错误信息要点名收到的那个值"
    assert all(v in msg for v in AF.STEP_OUTCOMES), "错误信息要给出受控词表（可动作）"
    after = st.rows("attack_plans")[0]
    assert after["history"] == before["history"], "词表外的 outcome 不许落进 history"
