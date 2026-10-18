"""判据：主控对**间接角色**的出边设限（今天只剩 `F`）。

## 这份文件的现状（2026-10-18 更正读数）

业主 2026-10-10 裁定第 4 条逐字：「M 的出边设限（不许直接控制 B、F、V，只可间接由父代理转达）」；
此后两次由业主加回：

- 2026-10-13 裁定「补 M 到 B」⇒ `M→B` 恢复；
- 2026-10-18 裁定「给 M 开 V 出边」⇒ `M→V` 恢复（`projects/t3d` 三·1 的读数：
  `reviewed_proof_rows = 0`，V 只能经 `F→V`，那一趟没走那条链 ⇒ 证明级断言一行都没被
  逐行走查签过名）。

所以今天**只剩 `F` 一个角色**仍然只走间接（`M→D→F`）。本文件的判据跟着边表走：
每一条都按新事实改正读数，一条也没删。

## 这一批为什么两层都要判

权限面（`capabilities.ALLOWED_EDGES`）与行为面（`Conductor.summon` 的判决）是同一件事的
两处实现：只判边表，改坏了 `forbidden_edge` 那条路照样静默；只判行为，边表被人加回去
（"反正行为层还会拒"）就没人管。所以三层各判一次：

- 边表 = `F` 不在主控的直接出边里；`B` 与 `V` **在**（那是 2026-10-13 / 2026-10-18 的裁定）；
- 行为 = 主控直接派 F ⇒ `refused` / `forbidden_edge`（受控拒绝，不是崩溃、不是静默）；
- 间接路径 = 同一张 Conductor 上 `M→D→F` / `M→D→F→V` / `M→B→V` 三条链各走通一次
  （裁定要的是"间接转达"，所以"拒了直接边"只证明了一半：另外一半是这几条链还在）。

改前的盘上读数（2026-10-10）：`M → {A,B,C,D,E,F,G,H,V}`；2026-10-10 裁定后
`M → {A,C,D,E,G,H}`；2026-10-13 加回 `M→B` ⇒ `M → {A,B,C,D,E,G,H}`；
**2026-10-18 加回 `M→V` ⇒ `M → {A,B,C,D,E,G,H,V}`**（边总数 32 → 33）。
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

#: 今天仍然只走间接的那个角色。它只剩一个 —— 这不是"判据变弱"，而是两条边被
#: 业主分别加回之后的事实（`B` 2026-10-13、`V` 2026-10-18）。
INDIRECT = ("F",)
#: 已经被加回主控出边的那两个（判据的"另一半正控"：它们必须被受理）。
DIRECT_NOW = ("B", "V")


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

def test_the_conductor_has_no_direct_edge_to_the_indirect_roles() -> None:
    """正控（权限面）：主控的直接出边里没有 `F`，但**有** `B` 与 `V`。

    这一条刻意写成"不含这些"而不是"等于那八个"：前者是裁定的字面内容，
    后者会把声明的形态抄成第二份定义（改一次要改两处，而漂移是静默的）。
    """
    got = set(C.ALLOWED_EDGES[S.CONDUCTOR_ROLE])
    assert not (got & set(INDIRECT)), f"主控仍然直接控制着 {sorted(got & set(INDIRECT))}"
    for role in DIRECT_NOW:
        assert role in got, (
            f"2026-10-13「补 M 到 B」/ 2026-10-18「给 M 开 V 出边」之后，主控必须能直接派 {role}"
        )
    # 反真空：判据扫得到东西（出边不是空集、被限的就是这一个）。
    assert got >= {"A", "C", "D", "E", "G", "H"}, got
    assert len(INDIRECT) == 1


def test_each_indirect_role_still_has_a_parent_that_can_reach_it() -> None:
    """正控（权限面）：`F` 还有别的进路（否则"间接转达"没有路可走）。"""
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

def test_a_direct_summon_of_f_is_refused_while_b_and_v_are_accepted(
        tmp_path: pathlib.Path) -> None:
    """正控（行为面）：主控直接派 `F` ⇒ `refused` / `forbidden_edge`；派 B / V 则受理。

    三态纪律：它是"查过了、这条边不存在"（受控拒绝），不是崩溃，也不是静默不派 ——
    主控拿到它才可能换一条链（提示词里那条政策的依据就是这个读数）。
    B / V 那一档是**正控的另一半**：2026-10-13 与 2026-10-18 两次加回之后它们必须被受理。
    """
    c = _world(tmp_path)
    for role, action in (("B", "run_once"), ("V", "list_verifications")):
        ok = c.summon(role, action, {}, input_key=f"direct-{role}")
        assert ok.outcome == "ok", (role, ok.status, ok.outcome, ok.refusal_reason)
    for role, action, params in (("F", "list_plans", {}),):
        res = c.summon(role, action, params, input_key=f"direct-{role}")
        assert res.status == "done" and res.outcome == "refused", (role, res.status, res.outcome)
        assert res.refusal_reason == "forbidden_edge", (role, res.refusal_reason, res.detail)


def test_the_indirect_chains_are_still_walkable(tmp_path: pathlib.Path) -> None:
    """正控（行为面）：`M→A→B` / `M→D→F` / `M→D→F→V` / `M→B→V` 各走通一次。

    这一条是本文件里唯一能区分"设限"与"把角色锁死"的判据：
    上面那条只证明直接边被拒，拒完之后活还派不派得出去，只有这里回答。
    末一条（`M→B→V`）与 `M→V` 一起证明"V 有两跳/一跳两条进路"。
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

    # 链三：M → D → F → V（F→V 那条老路仍然成立）
    v1 = c.summon("V", "list_verifications", {}, by="F", parent_task_id=f1.task_id,
                  input_key="chain-v")
    assert v1.outcome == "ok", (v1.status, v1.outcome, v1.refusal_reason)
    assert v1.depth == 3, v1.depth

    # 链四：M → B → V（业主 2026-10-13「补 M 到 B」留下的两跳路，今天仍然通）
    b2 = c.summon("B", "run_once", {}, input_key="chain-b2")
    assert b2.outcome == "ok", (b2.status, b2.outcome, b2.refusal_reason)
    v2 = c.summon("V", "list_verifications", {}, by="B", parent_task_id=b2.task_id,
                  input_key="chain-v2")
    assert v2.outcome == "ok", (v2.status, v2.outcome, v2.refusal_reason)
    assert v2.depth == 2, v2.depth


def test_the_prompt_tells_the_conductor_which_routes_are_open(
        tmp_path: pathlib.Path) -> None:
    """正控（提示词）：M 的 brief 里写着"F 只走间接、B 与 V 可以直接派"。

    为什么它也算判据：设限之后主控会频繁撞到 `forbidden_edge`，而"被拒了就换一条路"
    这条既有政策只有在它知道换哪条路时才可执行 —— 提示词里没有那几条链，
    拒信就变成了死路（`t4g` 那种"派不动就停"的形态）。
    """
    from agentflow import agent_prompts as AP
    from agentflow import specs as SP

    for brief in (AP.ROLE_BRIEFS["M"], SP.builtin_specs()["M"].brief):
        text = "\n".join(brief.policy)
        # 2026-10-18 之后这条政策的第一句只剩 F（B 2026-10-13、V 2026-10-18 已加回）
        assert "F 仍然只能间接由父代理转达" in text, text[:200]
        assert "B 与 V 你可以直接派" in text, text[:200]
        for route in ("M→D→F", "M→V", "forbidden_edge"):
            assert route in text, f"提示词里没有 {route}"
