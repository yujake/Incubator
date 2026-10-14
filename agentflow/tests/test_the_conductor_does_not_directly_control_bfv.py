"""判据：主控不许直接控制 F / V，只可间接由父代理转达。

业主 2026-10-10 裁定第 4 条逐字：「M 的出边设限（不许直接控制 B、F、V，只可间接由父代理转达）」；
**2026-10-13 裁定「补 M 到 B」把它收窄成两个角色**（逐字见 `specs/m.py`：
「**B 你可以直接派**（业主 2026-10-13：「补 M 到 B」）……要 V 的复核 ⇒ 走 D → F 那条链」）。
本文件跟这条现状判：B 在主控的直接出边里，F / V 不在。

## 这一批为什么两层都要判

权限面（`capabilities.ALLOWED_EDGES`）与行为面（`Conductor.summon` 的判决）是同一件事的
两处实现：只判边表，改坏了 `forbidden_edge` 那条路照样静默；只判行为，边表被人加回去
（"反正行为层还会拒"）就没人管。所以三层各判一次：

- 边表 = F / V 不在主控的直接出边里（B **在**，那是 2026-10-13 的裁定）；
- 行为 = 主控直接派 F / V ⇒ `refused` / `forbidden_edge`（受控拒绝，不是崩溃、不是静默）；
- 间接路径 = 同一张 Conductor 上 `M→D→F` / `M→D→F→V` 两条链各走通一次，外加 `M→B` 一条**直接**边
  （裁定要的是"间接转达"，所以"拒了直接边"只证明了一半：另外一半是这三条链还在）。

改前的盘上读数（本文件写之前现算）：`M → {A,B,C,D,E,F,G,H,V}`，
`B ← {A,D,E,F,M}`、`F ← {D,G,M,V}`、`V ← {F,M}`。
改后（2026-10-10）：`M → {A,C,D,E,G,H}`；2026-10-13 加回 `M → B` 之后：
`M → {A,B,C,D,E,G,H}`，`F ← {D,G,V}`、`V ← {F}`。
"""

from __future__ import annotations

import pathlib

from agentflow import capabilities as C
from agentflow import schema as S
from agentflow.agent_a.core import AgentA
from agentflow.agent_b.core import AgentB
from agentflow.agent_d.core import AgentD
from agentflow.agent_f.core import AgentF
from agentflow.agent_v.core import AgentV
from agentflow.conductor import Conductor
from agentflow.policy import Policy
from agentflow.store import Store

INDIRECT = ("F", "V")


class _Stub(AgentA):
    """一个把所有链上动作都给出来的替身（签名与真实类一致，见 `test_scheduler` 的同款理由）。

    为什么继承真类而不是 `type("X", (), {...})`：能力表的 `params` schema 会拒未声明的参数，
    而"替身签名与真实方法差一个参数"是最容易被忽略的漂移。
    """

    def __init__(self) -> None:  # 不建工具面：这条链测的是边，不是抽取质量
        pass

    def run_once(self):  # type: ignore[override]
        return {"outcome": "ok", "detail": "step"}

    def probe_c(self, qid, qrow=None):
        return {"outcome": "ok", "detail": f"probe_c({qid})"}

    def status(self, plan_id):
        return {"outcome": "ok", "detail": f"status({plan_id})"}

    def list_verifications(self, statement_id="", limit=0):
        return {"outcome": "ok", "detail": "list_verifications"}


def _world(tmp_path: pathlib.Path) -> Conductor:
    """一张把 A/B/D/F/V 都接上的 Conductor（链要真的走通，所以五个角色都得在）。"""
    st = Store(tmp_path / "ws")
    st.init()
    stub = _Stub()
    return Conductor(
        st,
        policy=Policy(max_concurrency=4, max_fanout=5, max_tasks_per_run=100,
                      wall_clock_sec=60),
        registry={r: ("object", stub) for r in ("A", "B", "D", "F", "V")},
        fanout_wait_sec=0.0,
    )


# --------------------------------------------------------------- 权限面

def test_the_conductor_has_no_direct_edge_to_the_two_indirect_roles() -> None:
    """正控（权限面）：主控的直接出边里没有 F / V，但**有** B（2026-10-13 裁定）。

    这一条刻意写成"不含这两个"而不是"等于那七个"：前者是裁定的字面内容，
    后者会把声明的形态抄成第二份定义（改一次要改两处，而漂移是静默的）。
    """
    got = set(C.ALLOWED_EDGES[S.CONDUCTOR_ROLE])
    assert not (got & set(INDIRECT)), f"主控仍然直接控制着 {sorted(got & set(INDIRECT))}"
    assert "B" in got, "2026-10-13 裁定「补 M 到 B」：主控可以直接派 B"
    # 反真空：判据扫得到东西（出边不是空集、被限的就是这两个）。
    assert got >= {"A", "C", "D", "E", "G", "H"}, got
    assert len(INDIRECT) == 2


def test_each_indirect_role_still_has_a_parent_that_can_reach_it() -> None:
    """正控（权限面）：这三个角色各自还有别的进路（否则"间接转达"没有路可走）。"""
    for role in INDIRECT:
        inbound = {frm for frm, tos in C.ALLOWED_EDGES.items() if role in tos}
        assert inbound - {S.CONDUCTOR_ROLE}, f"{role} 只能由主控召唤 ⇒ 它已经没人派得动了"
        assert inbound & {"A", "D", "F", "G", "E"}, (role, sorted(inbound))


def test_the_whole_role_space_is_still_reachable_from_the_conductor() -> None:
    """正控（可达性）：从主控出发顺着边图能到每一个角色（改前那条等式的正身）。"""
    reach = {S.CONDUCTOR_ROLE}
    while True:
        grew = {t for f in reach for t in C.ALLOWED_EDGES.get(f, ())} - reach
        if not grew:
            break
        reach |= grew
    assert reach >= set(S.ROLES), f"到不了：{sorted(set(S.ROLES) - reach)}"


def test_the_negative_control_putting_an_edge_back_is_rejected() -> None:
    """负控（权限面）：把 `M → F` 加回去 ⇒ 能力层自检当场炸。

    没有这一条，"不许直接控制"就只是一句写在注释里的话：边表加一条边，
    其余判据（键集、可达性）全都照样过。
    """
    original = C.ALLOWED_EDGES[S.CONDUCTOR_ROLE]
    C.ALLOWED_EDGES[S.CONDUCTOR_ROLE] = frozenset(set(original) | {"F"})
    try:
        try:
            C.assert_capabilities()
        except AssertionError as exc:
            assert "间接由父代理转达" in str(exc), exc
        else:
            raise AssertionError("把 M → F 加回去之后断言居然过了")
    finally:
        C.ALLOWED_EDGES[S.CONDUCTOR_ROLE] = original


# --------------------------------------------------------------- 行为面

def test_a_direct_summon_of_f_and_v_is_refused_not_crashed(tmp_path: pathlib.Path) -> None:
    """正控（行为面）：主控直接派 F / V ⇒ `refused` / `forbidden_edge`；派 B 则受理。

    三态纪律：它是"查过了、这条边不存在"（受控拒绝），不是崩溃，也不是静默不派 ——
    主控拿到它才可能换一条链（提示词里那条政策的依据就是这个读数）。
    B 这一档是**正控的另一半**：2026-10-13 之后它必须被受理（否则"补 M 到 B"没落地）。
    """
    c = _world(tmp_path)
    b0 = c.summon("B", "run_once", {}, input_key="direct-B")
    assert b0.outcome == "ok", (b0.status, b0.outcome, b0.refusal_reason)
    cases = (("F", "list_plans", {}), ("V", "list_verifications", {}))
    for role, action, params in cases:
        res = c.summon(role, action, params, input_key=f"direct-{role}")
        assert res.status == "done" and res.outcome == "refused", (role, res.status, res.outcome)
        assert res.refusal_reason == "forbidden_edge", (role, res.refusal_reason, res.detail)


def test_the_three_indirect_chains_are_still_walkable(tmp_path: pathlib.Path) -> None:
    """正控（行为面）：`M→A→B` / `M→D→F` / `M→D→F→V` 三条链同一张 Conductor 上各走通一次。

    这一条是本文件里唯一能区分"设限"与"把角色锁死"的判据：
    上面那条只证明直接边被拒，拒完之后活还派不派得出去，只有这里回答。
    """
    c = _world(tmp_path)

    # 链一：M → A → B（抽取/重抽取由 A 转达）
    a1 = c.summon("A", "run_once", {}, input_key="chain-a")
    assert a1.outcome == "ok", (a1.status, a1.outcome, a1.error)
    b1 = c.summon("B", "run_once", {}, by="A", parent_task_id=a1.task_id, input_key="chain-b")
    assert b1.outcome == "ok", (b1.status, b1.outcome, b1.refusal_reason)
    assert b1.depth == 2, b1.depth

    # 链二：M → D → F（F 的攻坚推进由 D 建计划并转达）
    d1 = c.summon("D", "probe_c", {"qid": "0000"}, input_key="chain-d")
    assert d1.outcome == "ok", (d1.status, d1.outcome, d1.error)
    f1 = c.summon("F", "status", {"plan_id": "0000"}, by="D", parent_task_id=d1.task_id,
                  input_key="chain-f")
    assert f1.outcome == "ok", (f1.status, f1.outcome, f1.refusal_reason)
    assert f1.depth == 2, f1.depth

    # 链三：M → D → F → V（V 改后只剩 F 这一条进路，于是"V 由谁派"钉在链上）
    v1 = c.summon("V", "list_verifications", {}, by="F", parent_task_id=f1.task_id,
                  input_key="chain-v")
    assert v1.outcome == "ok", (v1.status, v1.outcome, v1.refusal_reason)
    assert v1.depth == 3, v1.depth


def test_the_prompt_tells_the_conductor_the_three_routes(tmp_path: pathlib.Path) -> None:
    """正控（提示词）：M 的 brief 里写着这条限制与三条替代链。

    为什么它也算判据：设限之后主控会频繁撞到 `forbidden_edge`，而"被拒了就换一条路"
    这条既有政策只有在它知道换哪条路时才可执行 —— 提示词里没有那三条链，
    拒信就变成了死路（`t4g` 那种"派不动就停"的形态）。
    """
    from agentflow import agent_prompts as AP
    from agentflow import specs as SP

    for brief in (AP.ROLE_BRIEFS["M"], SP.builtin_specs()["M"].brief):
        text = "\n".join(brief.policy)
        assert "F / V 只能间接由父代理转达" in text, text[:200]
        assert "B 你可以直接派" in text, text[:200]
        # 路线名逐条现算：2026-10-13 之后 B 那条是**直接**边（`M→B`），
        # 另外两条仍是间接链与那条拒信读数 —— 写死旧路线名会让这条判据随
        # 业主的一句裁定变成假红（实测：`A.run_once` 已从 M 的 brief 里退场）。
        for route in ("M→B" if "M→B" in text else "B 你可以直接派",
                      "D → F", "forbidden_edge"):
            assert route in text, f"提示词里没有 {route}"
