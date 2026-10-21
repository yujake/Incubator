"""判据：主控对间接角色的出边设限（今天是 `F` 与 `V` 两个）。
## 这份文件的现状（2026-10-20 更正读数）
业主 2026-10-10 裁定第 4 条逐字：「M 的出边设限（不许直接控制 B、F、V，只可间接由父代理转达）」；此后由业主加回一条、又撤回一条：
- 2026-10-13 裁定「补 M 到 B」⇒ `M→B` 恢复；
- 2026-10-18 裁定「给 M 开 V 出边」⇒ `M→V` 恢复（`projects/t3d` 三·1 的读数：
`reviewed_proof_rows = 0`）；
- 2026-10-20 业主裁定：撤掉 `M→V`；派 V 只有 F 与 B 两个入口 ⇒ `M→V` 又变成不许的边
（`M → {A,B,C,D,E,G,H}`，边总数 32）。V 的两跳路仍在：`M→B→V`（B 入库文献侧内容时请 V 签）。
所以今天又有两个角色只走间接：`F`（`M→D→F`）与 `V`（`M→B→V`）。本文件的判据跟着边表走：每一条都按新事实改正读数，一条也没删。
## 这一批为什么两层都要判
权限面（`capabilities.ALLOWED_EDGES`）与行为面（`Conductor.summon` 的判决）是同一件事的两处实现：只判边表，改坏了 `forbidden_edge` 那条路照样静默；只判行为，边表被人加回去（"反正行为层还会拒"）
就没人管。所以三层各判一次：
- 边表 = `F` 与 `V` 都不在主控的直接出边里；`B` 在（2026-10-13 的裁定）；
- 行为 = 主控直接派 F 或 V ⇒ `refused` / `forbidden_edge`（受控拒绝，不是崩溃、不是静默）；
- 间接路径 = 同一张 Conductor 上 `M→D→F` / `M→D→F→V` / `M→B→V` 三条链各走通一次
（裁定要的是"间接转达"，所以"拒了直接边"只证明了一半：另外一半是这几条链还在）。
改前的盘上读数（2026-10-10）：`M → {A,B,C,D,E,F,G,H,V}`；2026-10-10 裁定后`M → {A,C,D,E,G,H}`；2026-10-13 加回 `M→B` ⇒ `M → {A,B,C,D,E,G,H}`；
2026-10-18 加回 `M→V` ⇒ `M → {A,B,C,D,E,G,H,V}`（边总数 32 → 33）；2026-10-20 撤掉 `M→V` ⇒ `M → {A,B,C,D,E,G,H}`（边总数 33 → 32）。
"""

from __future__ import annotations

import pathlib
import re

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

#: 今天只走间接的那两个角色。2026-10-20 业主裁定撤掉 `M→V` 之后，`V` 回到这一组
#: （`F` 自 2026-10-10 起一直在这里）—— 期望值改了，判据强度没改。
INDIRECT = ("F", "V")
#: 已经被加回主控出边的那个（判据的"另一半正控"：它必须被受理）。
#: 2026-10-20 之后这一组只剩 `B`（2026-10-13「补 M 到 B」）。
DIRECT_NOW = ("B",)


def _direct_edge_problems(edges) -> list[str]:
    """M 的出边里那些今天不该在的角色（空列表 = 一条都没有）。

    抽成函数是为了让负控能直接把 `V` 塞回去再判一次 —— 只写一个 `assert not (got & ...)`
    的话，"把 V 又加回出边"这件事只能靠人眼，判据本身说不清自己咬的是什么。
    """
    got = set(edges) & set(INDIRECT)
    return [
        f"{role} 又在 M 的出边里（2026-10-20 业主裁定：撤掉 `M→V`；派 V 只有 F 与 B 两个入口）"
        for role in sorted(got)
    ]


#: 提示词/手册里必须读得到的几处字面（`_flat` 之后按"读到的意思"判）：
#: `B 你可以直接派`（B 是直接边）＋ 经 B 的两跳路 `M→B→V` ＋ F 唯一的进路 `M→D→F`
#: ＋ 被拒时的读数 `forbidden_edge`。
_ROUTE_KEEP = ("B你可以直接派", "M→B→V", "经B", "M→D→F", "forbidden_edge")
#: 2026-10-18 那一版的旧口径：任何一种命中 ⇒ "V 能直接从 M 派"这句话还在。
_ROUTE_BAN = ("B与V你可以直接派", "出边里已有V", "直接派V", "M→V")
#: 撤 V 直连之后不许被顺手删掉的义务句（业主：义务挪给 D，不是取消）。
_HANDOVER_KEEP = ("D去核", "由D让F补签")

#: 强调符号与空白：`派 **D** 去核` 与 `派 D 去核` 是同一句话。
_EMPHASIS = re.compile(r"[\s*`]+")


def _flat(text: str) -> str:
    """去掉强调符号与所有空白 —— 判"读到的意思"，不判排版。"""
    return _EMPHASIS.sub("", text)


def _route_text_problems(text: str) -> list[str]:
    """提示词里"派 V 的路"写错的地方（空列表 = 写对了）。"""
    flat = _flat(text)
    out = [f"提示词里读不到「{needle}」—— 那条路今天仍然在（2026-10-20 只撤了 M→V）"
           for needle in _ROUTE_KEEP if needle not in flat]
    out += [
        f"提示词里还写着旧口径「{needle}」—— 2026-10-20 业主裁定撤掉 M→V"
        f"（V 不在 M 的出边里；派 V 只有 F 与 B 两个入口）"
        for needle in _ROUTE_BAN if needle in flat
    ]
    return out


def _handover_text_problems(text: str) -> list[str]:
    """提示词里"义务已转交 D"那几句的缺失（空列表 = 都在）。"""
    flat = _flat(text)
    return [
        f"提示词里读不到「{needle}」—— 删假陈述不许连真义务一起删"
        f"（业主：这条义务**挪给 D**，不是取消）"
        for needle in _HANDOVER_KEEP if needle not in flat
    ]


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
    """正控（权限面）：主控的直接出边里没有 `F` 与 `V`，但有 `B`。

    这一条刻意写成"不含这些"而不是"等于那七个"：前者是裁定的字面内容，
    后者会把声明的形态抄成第二份定义（改一次要改两处，而漂移是静默的）。
    """
    got = set(C.ALLOWED_EDGES[S.CONDUCTOR_ROLE])
    problems = _direct_edge_problems(got)
    assert problems == [], "主控仍然直接控制着：\n  - " + "\n  - ".join(problems)
    for role in DIRECT_NOW:
        assert role in got, (
            f"2026-10-13「补 M 到 B」之后，主控必须能直接派 {role}"
        )
    # 反真空：判据扫得到东西（出边不是空集、被限的就是这两个）。
    assert got >= {"A", "C", "D", "E", "G", "H"}, got
    # 2026-10-20 业主裁定「撤 M→V」：这一组从 1 个（F）回到 2 个（F、V）。
    assert len(INDIRECT) == 2


def test_the_negative_control_putting_v_back_in_m_edges_is_named() -> None:
    """负控（权限面，2026-10-20 业主裁定）：真把 `V` 加回 `ALLOWED_EDGES["M"]` ⇒ ① 的前半红。

    而且报错必须能点名 V（"V 又在 M 的出边里"）—— 只说"某条边不对"，
    读的人还得自己去猜是哪一条，而下一条被加回来的边就没人守了。
    """
    original = C.ALLOWED_EDGES[S.CONDUCTOR_ROLE]
    C.ALLOWED_EDGES[S.CONDUCTOR_ROLE] = frozenset(set(original) | {"V"})
    try:
        got = _direct_edge_problems(C.ALLOWED_EDGES[S.CONDUCTOR_ROLE])
        assert got, "把 V 加回 M 的出边之后判据居然绿了"
        assert any("V" in p and "在 M 的出边里" in p for p in got), got
        # 另一条边不许被顺手带走（B 于 2026-10-13 加回，今天仍在）
        assert "B" in C.ALLOWED_EDGES[S.CONDUCTOR_ROLE]
    finally:
        C.ALLOWED_EDGES[S.CONDUCTOR_ROLE] = original
    # 收尾（负控的负控）：还原之后这一格必须重新是空的
    assert _direct_edge_problems(C.ALLOWED_EDGES[S.CONDUCTOR_ROLE]) == []


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

def test_a_direct_summon_of_f_and_v_is_refused_while_b_is_accepted(
        tmp_path: pathlib.Path) -> None:
    """正控（行为面）：主控直接派 `F` / `V` ⇒ `refused` / `forbidden_edge`；派 `B` 则受理。

    三态纪律：它是"查过了、这条边不存在"（受控拒绝），不是崩溃，也不是静默不派 ——
    主控拿到它才可能换一条链（提示词里那条政策的依据就是这个读数）。
    `B` 那一档是正控的另一半：2026-10-13「补 M 到 B」之后它必须被受理。

    # 2026-10-20 业主裁定：撤掉 M→V；派 V 只有 F 与 B 两个入口
    ⇒ `V` 从"必须被受理"那一档挪到"必须被拒"这一档（与 `tests/test_policy.py` 里
    `test_the_conductor_may_summon_b_and_v_but_not_f` 的 `forbidden_edge` 正控同口径）。
    """
    c = _world(tmp_path)
    ok = c.summon("B", "run_once", {}, input_key="direct-B")
    assert ok.outcome == "ok", (ok.status, ok.outcome, ok.refusal_reason)
    for role, action, params in (("F", "list_plans", {}),
                                 ("V", "list_verifications", {})):
        res = c.summon(role, action, params, input_key=f"direct-{role}")
        assert res.status == "done" and res.outcome == "refused", (role, res.status, res.outcome)
        assert res.refusal_reason == "forbidden_edge", (role, res.refusal_reason, res.detail)


def test_the_indirect_chains_are_still_walkable(tmp_path: pathlib.Path) -> None:
    """正控（行为面）：`M→A→B` / `M→D→F` / `M→D→F→V` / `M→B→V` 各走通一次。

    这一条是本文件里唯一能区分"设限"与"把角色锁死"的判据：
    上面那条只证明直接边被拒，拒完之后活还派不派得出去，只有这里回答。
    末一条（`M→B→V`）是今天 M 够得着 V 的唯一一条路（`M→V` 已于 2026-10-20 撤掉）。
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
    """正控（提示词）：M 的 brief 里写着"F 只走间接、B 可以直接派、V 只能经 B 的两跳路"。

    为什么它也算判据：设限之后主控会频繁撞到 `forbidden_edge`，而"被拒了就换一条路"
    这条既有政策只有在它知道换哪条路时才可执行 —— 提示词里没有那几条链，
    拒信就变成了死路（`t4g` 那种"派不动就停"的形态）。

    # 2026-10-20 业主裁定：撤掉 M→V；派 V 只有 F 与 B 两个入口
    ⇒ 提示词那一句从「B 与 V 你可以直接派」改成「B 你可以直接派」＋「V 不在你的出边里、
    签字只走经 B 的 `M→B→V`」；这里跟着改期望值（并加负断言：不许再出现
    「B 与 V 你可以直接派」/「出边里已有 V」/「直接派 V」/`M→V` 直连）。
    """
    from agentflow import agent_prompts as AP
    from agentflow import specs as SP

    for brief in (AP.ROLE_BRIEFS["M"], SP.builtin_specs()["M"].brief):
        text = "\n".join(brief.policy)
        # 这一句原文一字未动（F 自 2026-10-10 起一直只走间接）
        assert "F 仍然只能间接由父代理转达" in text, text[:200]
        problems = _route_text_problems(text) + _handover_text_problems(text)
        assert problems == [], "\n  - " + "\n  - ".join(problems)


def test_the_negative_control_the_old_direct_v_sentence_is_caught() -> None:
    """负控（提示词文字面）：把 2026-10-18 那句旧口径加回 ⇒ 判据必须红（四种写法各自咬住）。

    没有这一条，"提示词里没有 M→V"就只是一句注释：那句话加回去，其余判据
    （F 那一句、`M→B→V` 那一句、`forbidden_edge`）全都照样过。
    """
    from agentflow import specs as SP

    text = "\n".join(SP.builtin_specs()["M"].brief.policy)
    assert _route_text_problems(text) == [], "夹具前提：真身上那句旧口径已经改掉了"
    # (a) 抬头那一句（"B 与 V 你可以直接派"）
    got = _route_text_problems(text + "\n**B 与 V 你可以直接派**。")
    assert any("B与V你可以直接派" in p for p in got), got
    # (b) 派生表里"已有 V"那一半（换个说法也照样是假权限陈述）
    got = _route_text_problems(text + "\n你的出边里已有 V。")
    assert any("出边里已有V" in p for p in got), got
    # (c) 口语形态"直接派 V"
    got = _route_text_problems(text + "\n要 V 走查就直接派 V。")
    assert any("直接派V" in p for p in got), got
    # (d) 直连那条边本身
    got = _route_text_problems(text + "\n`M→V` 仍是你的直接边。")
    assert any("M→V" in p for p in got), got
    # 收尾（负控的负控）：原样的提示词必须重新成立
    assert _route_text_problems(text) == []


def test_the_negative_control_dropping_the_handover_sentences_is_caught() -> None:
    """负控（反真空）：把写着"义务挪给 D"的那一段整段删掉 ⇒ 判据必须红。

    防的是"删掉≠转交"：把假陈述删干净，同时把"真发现缺签就派 D 去核、由 D 让 F 补签"
    一起删掉 —— 表面上"提示词里没有错话了"，实际上 V 的签字义务没人办。
    """
    from agentflow import specs as SP

    policy = SP.builtin_specs()["M"].brief.policy
    text = "\n".join(policy)
    assert _handover_text_problems(text) == [], "夹具前提：义务句还在"
    # "派 D 去核 / 由 D 让 F 补签"这几句分散在三段 policy 里 ⇒ 整段删要把它们一起删掉
    # （只删其中一段的话，另外两段还能读到 ⇒ 判据仍绿，那正好也是"删了一段不等于删干净"）。
    dropped = "\n".join(str(s) for s in policy
                        if not any(n in _flat(str(s)) for n in _HANDOVER_KEEP))
    assert dropped != text, "夹具前提：policy 里真有写着「派 D 去核 / 由 D 让 F 补签」的段落"
    got = _handover_text_problems(dropped)
    assert any("D去核" in p for p in got), got
    assert any("由D让F补签" in p for p in got), got
    # 收尾（负控的负控）
    assert _handover_text_problems(text) == []
