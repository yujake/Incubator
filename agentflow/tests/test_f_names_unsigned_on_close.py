# -*- coding: utf-8 -*-
"""③ 交差时点名未签成果 + 留痕（业主 2026-11-02 追加口径）。

业主原话（收口版）：

    应该是收工的判据拦着说你还有哪些命题未签（也可以选择放弃那些命题），
    没签的要继续完善直到拿到V签。
    如果V反馈的是真缺陷，可能F需要减弱自己的断言并再启攻坚，这是它自己调控的。

口径边界（同一天的更正）：出路只是「举例，不是枚举」 —— 系统只许做两件：
① 把未签的成果逐条点名；② 要求 F 「留痕」（它选了什么、理由）。
「不许」替它选，也「不许」把它的选择当成系统动作去驱动（不写循环 / 重试 / 催办）。

| # | 造什么 | 期望 |
|---|---|---|
| a | F 名下 2 条未签、它走到收工出口 | 收工读数逐条点名这 2 条（命题号 + 手稿）+ 出路举例；`legal_stop` 假 |
| b | 同上，但 F 写了 `next_move` / `why` | 留痕被读到（不判它选了哪条）；未签仍拦着收工 |
| c | 研究了、尽力了、0 条成果 | 自评=没成果；`is_failure` 假、`legal_stop` 真（合法收工） |
| d | 明确放弃一条（带时间与理由） | 不再算未签；`state=outputs_settled`、`legal_stop` 真 |
| e | 反真空：把「点名未签」打桩成空 | a 那组断言必须红（静默收工不许通过） |
"""
from __future__ import annotations

import pathlib

import pytest
from conftest import seed_statement_row
from agentflow import depsection as _DS
from agentflow.agent_f import AgentF
from agentflow.agent_f import delivery as FD
from agentflow.store import Store

AT = "2026-11-02T10:00:00+08:00"


class _FSecretary:
    actor = "fake-F-secretary"
    seam = object()

    def wash_dependency_face(self, text: str, **_kw) -> dict:
        return {"checked": True, "text": str(text), "actor": self.actor,
                "washed": False, "deps_refused": "", "deps_refused_findings": [],
                "deps_section_filled": "", "deps_washing": [],
                "reason": "夹具：依赖面本来就合规"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _f(st: Store) -> AgentF:
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0000"})
    f.f_secretary = _FSecretary()
    return f


def _product(text: str) -> dict:
    return {"product": "proof", "strategy": "套用已知定理", "why_strategy": "直接按定义",
            "steps": [{"n": 1, "text": f"{text}：取 ε>0，按定义逐点验证。",
                       "cites": [], "assumption": False}]}


def _two_unsigned_outputs(st: Store) -> tuple[AgentF, str, list[str]]:
    """造一个两条成果、一条都没签的计划，并把轮数写成已用尽（收工出口）。

    2026-11-02 准入闸默认 strict 之后，这个现场不能再走 `_apply_round` 造：那条路
    经 B 的登记，而没有签的证明正文会被整笔拒（`proof_without_v_sign`）——
    "无签的成果"在正路上已经不存在了。所以夹具改成「直接铺 statements 行」：
    真机 3134 行 own_result 就是这种历史形态（`bits={}`、没有台账、没有签），
    这一组判据测的正是"这个状态在收工时被读成什么"。
    改的是"怎么造现场"，不是期望值。
    """
    f = _f(st)
    pid = f.create_plan("难题：判定这个族", "PK-179-CLOSE", subgoals=[
        {"sid": "s1", "text": "证明：紧集上的连续函数一致连续", "owner": "F",
         "testable": "存在反例或有限界"},
        {"sid": "s2", "text": "证明：序列紧空间的乘积紧", "owner": "F",
         "testable": "存在反例或有限界"},
    ], budget={"max_rounds": 2, "max_parallel_subgoals": 2,
               "max_persist_attempts": 1, "max_depth": 1})["plan_id"]
    row = next(dict(r) for r in st.rows("attack_plans")
               if str(r.get("plan_id")) == str(pid))
    sids: list[str] = []
    for i, (sg, text) in enumerate((("s1", "紧集上的连续函数一致连续"),
                                    ("s2", "序列紧空间的乘积紧")), 1):
        body = f"1. {text}：取 ε>0，按定义逐点验证。（前提）"
        seeded = seed_statement_row(
            st, proof_text=body,
            statement_full=f"{text}；这一条的可检验形式：存在反例或有限界",
            statement_text=text, kind="conjecture", label=f"F 攻坚 {pid} 子目标 {sg}",
            quote_reason="F 交来的论证，V 还没签（历史形态：直接铺行）")
        sid = str(seeded["stmt_id"])
        # F 的证明手稿落盘（收工读数按约定路径点名它；盘上没有签块 ⇒ 未签）。
        rel = pathlib.Path("reports") / f"f-proof-{sid}.md"
        path = pathlib.Path(st.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# F 的证明手稿\n\n- 命题号：stmt:{sid}\n\n## 命题\n\n{text}\n\n"
            f"## 证明\n\n{body}\n\n## 依赖\n\n（自足证明，空表就是声明。）\n",
            encoding="utf-8")
        sids.append(sid)
        row["history"].append({"round": i, "sid": sg, "action": "proof",
                               "outcome": "progress", "detail": "", "evidence": [],
                               "statement_id": sid, "at": AT})
    row["rounds"] = 2
    f._write_plan(row, note="test:two_unsigned")
    return f, str(pid), sids


def _close_reading(f: AgentF, pid: str) -> dict:
    """走到收工出口（轮数用尽 ⇒ stop），把那一趟的返回值拿回来。"""
    out = f.step(pid)
    assert out.get("action") == "stop", out
    return out


def _assert_close_names(reading: dict, sids: list[str]) -> None:
    """a 的断言（e 的反真空也走它 —— 静默收工的读数必须咬得住）。"""
    assert reading.get("state") == "outputs_unsigned", reading
    assert reading.get("unfinished_count") == 2, reading
    open_rows = [dict(x) for x in (reading.get("unfinished") or [])]
    named = {str(x.get("statement_id")) for x in open_rows}
    assert named == set(sids), (named, sids)
    for one in open_rows:
        assert str(one.get("manuscript") or "") == f"reports/f-proof-{one['statement_id']}.md", one
        assert one.get("claim") in ("proof_unsigned", "draft"), one
    # 出路：给的是举例（不替它选）
    exits = list(reading.get("legal_exits") or [])
    assert exits, reading
    assert any("减弱" in e for e in exits), exits
    assert any("放弃" in e for e in exits), exits
    assert "举例" in str(reading.get("exits_note") or ""), reading
    # 不许静默收工
    assert reading.get("legal_stop") is False, reading
    assert reading.get("close_problems"), reading


# ============================================================ a：2 条未签 ⇒ 逐条点名
def test_a_closing_with_two_unsigned_outputs_names_both(tmp_path):
    """a 造「F 名下 2 条未签、它走到收工出口」⇒ 逐条点名 + 两条出路（举例）+ 不许收工。"""
    st = _ws(tmp_path)
    f, pid, sids = _two_unsigned_outputs(st)
    out = _close_reading(f, pid)
    _assert_close_names(dict(out.get("delivery") or {}), sids)
    # 交差说明里也逐条点名了它们（不只在结构化读数里）
    reason = str(out.get("reason") or "")
    for sid in sids:
        assert f"stmt:{sid}" in reason, reason
    assert "不许静默收工" in reason or "没签" in reason, reason


# ============================================================ b：留痕
def test_b_the_trail_is_recorded_but_the_choice_is_the_agents(tmp_path):
    """b 造「F 写了 next_move / why」⇒ 留痕被读到；「不判它选了哪条」（业主：自己调控）。"""
    st = _ws(tmp_path)
    f, pid, sids = _two_unsigned_outputs(st)
    row = next(dict(r) for r in st.rows("attack_plans")
               if str(r.get("plan_id")) == str(pid))
    choice = "先把引理 B 拆成两条更弱的引理，再回来改 A 的第三步"
    row["history"][-1]["self_assessment"] = {
        "comprehensive": "partial", "enough_output": "some_output",
        "partial_output": "partial_output", "next_move": choice,
        "why": "A 的第三步缺一条工具引理，拆开更好核"}
    f._write_plan(row, note="test:trail")
    out = _close_reading(f, pid)
    delivery = dict(out.get("delivery") or {})
    trail = dict(delivery.get("trail") or {})
    assert trail.get("checked") is True, trail
    assert trail.get("choice") == choice, trail
    # 留痕不等于可以收工：未签的还在
    assert delivery.get("legal_stop") is False, delivery
    assert delivery.get("unfinished_count") == 2, delivery


# ============================================================ c：没成果是合法收工
def test_c_no_output_after_research_is_a_legal_close_not_a_failure(tmp_path):
    """c 造「研究了、尽力了、0 条成果」⇒ 自评=没成果；不算失败；合法收工。"""
    st = _ws(tmp_path)
    f = _f(st)
    plan = {"plan_id": "0007", "problem": "判定这个族", "problem_key": "PK-179-NONE",
            "rounds": 3, "status": "stalled", "depth": 0,
            "budget": {"max_rounds": 3, "max_parallel_subgoals": 2,
                       "max_persist_attempts": 1, "max_depth": 1},
            "best_partial": "排除三条路，缩小到一个更小的判定",
            "history": [
                {"round": 1, "sid": "s1", "action": "reduction", "outcome": "progress",
                 "product": "reduction", "detail": "",
                 "product_detail": {"new_subgoals": [{"goal": "判定小情形 n<=12"}]},
                 "at": AT},
                {"round": 2, "sid": "s2", "action": "dead_end", "outcome": "no_change",
                 "product": "dead_end", "best_partial": [{"what": "排除法一", "ids": []}],
                 "detail": "", "at": AT},
                {"round": 3, "sid": "s2", "action": "dead_end", "outcome": "no_change",
                 "product": "dead_end", "best_partial": [{"what": "排除法二", "ids": []}],
                 "detail": "", "at": AT},
            ],
            "subgoals": [
                {"sid": "s1", "text": "证引理 A", "owner": "F", "status": "blocked",
                 "blocked_reason": "缺一条工具引理", "experiment_ids": [],
                 "evidence_ids": [], "attempts": 2, "negation_kind": None},
                {"sid": "s2", "text": "证引理 B", "owner": "F", "status": "blocked",
                 "blocked_reason": "两条路都不通", "experiment_ids": [],
                 "evidence_ids": [], "attempts": 2, "negation_kind": None},
            ]}
    reading = f.delivery_reading(plan)
    # 不传自评 ⇒ 推出来的那三档也要读出「研究过、没成果」
    assert reading.get("total") == 0, reading
    assert reading.get("state") == "researched_no_output", reading
    assert reading.get("is_failure") is False, reading
    assert reading.get("legal_stop") is True, reading
    assert reading.get("self_assessment", {}).get("enough_output") == "no_output", reading
    # F 自己写自评那一档：三档照录 + 合法收工
    reading2 = f._delivery_reading(
        plan, assessment={"comprehensive": "comprehensive", "enough_output": "no_output",
                          "partial_output": "partial_output",
                          "why": "三条路都试过，缺一条工具引理"})
    assert reading2.get("self_assessment", {}).get("checked") is True, reading2
    for criterion, tier in (("comprehensive", "comprehensive"),
                            ("enough_output", "no_output"),
                            ("partial_output", "partial_output")):
        assert reading2["self_assessment"]["criteria"][criterion]["tier"] == tier, reading2
    assert reading2.get("legal_stop") is True, reading2
    assert reading2.get("is_failure") is False, reading2
    assert reading2.get("delivered") is False, reading2


# ============================================================ d：明确放弃
def test_d_an_abandoned_output_is_no_longer_counted_as_unsigned(tmp_path):
    """d 造「明确放弃一条（带时间与理由）」⇒ 不再算未签；它是放弃，不是证明。"""
    st = _ws(tmp_path)
    f, pid, sids = _two_unsigned_outputs(st)
    row = next(dict(r) for r in st.rows("attack_plans")
               if str(r.get("plan_id")) == str(pid))
    victim = sids[0]
    stmt = next(dict(r) for r in st.rows("statements")
                if str(r.get("stmt_id")) == victim)
    stmt["status"] = "abandoned"
    stmt["quote_reason"] = (f"abandoned@{AT}@第三步的界对不上，工具引理也补不出来")
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", stmt, note="test:abandon")
    reading = f.delivery_reading(row)
    assert reading.get("abandoned_count") == 1, reading
    assert victim in list(reading.get("abandoned_statements") or []), reading
    named = {str(x.get("statement_id")) for x in (reading.get("unfinished") or [])}
    assert victim not in named, named
    assert reading.get("unfinished_count") == 1, reading
    # 放弃的那条不计入证明数
    assert reading.get("proof_count") == 0, reading
    assert reading.get("legal_stop") is False, reading


def test_d2_abandoning_all_unsigned_outputs_settles_the_plan(tmp_path):
    """d2 全部未签都明确放弃 ⇒ 每一条都有结局（签或放弃），可以收工。"""
    st = _ws(tmp_path)
    f, pid, sids = _two_unsigned_outputs(st)
    row = next(dict(r) for r in st.rows("attack_plans")
               if str(r.get("plan_id")) == str(pid))
    for sid in sids:
        stmt = next(dict(r) for r in st.rows("statements")
                    if str(r.get("stmt_id")) == sid)
        stmt["status"] = "abandoned"
        stmt["quote_reason"] = f"abandoned@{AT}@攻不动，明确放弃"
        with st.tx("statements", actor="test") as tx:
            tx.upsert("statements", stmt, note="test:abandon")
    reading = f.delivery_reading(row)
    assert reading.get("abandoned_count") == 2, reading
    assert reading.get("unfinished_count") == 0, reading
    assert reading.get("state") == "outputs_settled", reading
    assert reading.get("legal_stop") is True, reading
    assert reading.get("delivered") is False, reading


def test_d3_an_unparseable_abandon_marker_still_counts_as_unsigned():
    """d3 只有状态、没有可解析的放弃标记 ⇒ 仍按未签计（三样缺一不可）。

    台账那一层（`schema`）对「新写入」硬拒这种行；这一条判的是读数侧的对旧行兼容：
    `abandoned_of` 读不出时间与理由时，`abandoned` 必须是假、并点明缺什么。
    """
    bare = FD.abandoned_of({"status": "abandoned", "quote_reason": "我想放弃了"})
    assert bare.get("abandoned") is False, bare
    assert bare.get("problems"), bare
    ok = FD.abandoned_of({"status": "abandoned",
                          "quote_reason": f"abandoned@{AT}@攻不动，明确放弃"})
    assert ok.get("abandoned") is True, ok
    assert ok.get("at") == AT and "攻不动" in str(ok.get("why") or ""), ok


# ============================================================ 手册正文
def test_the_f_manual_teaches_the_three_criteria_and_the_two_exits():
    """F 的手册正文要教到：三条自评判据、逐条读数、无签不算证明、没成果合法、留痕与出路。"""
    from agentflow import agent_skills as AS

    body = next(s for s in AS.CATALOG["F"] if s.slug == "交付-证明要能被别人复核").body
    for needle in ("comprehensive", "enough_output", "partial_output",
                   "signed_count", "pending_count", "unsigned_count", "coverage",
                   "proof_count", "unfinished", "next_move",
                   "没成果", "减弱自己的断言", "明确放弃", "留痕"):
        assert needle in body, (needle, body[-600:])
    # 只改正文：摘要仍是一句话（不把正文塞进摘要）
    skill = next(s for s in AS.CATALOG["F"] if s.slug == "交付-证明要能被别人复核")
    assert "\n" not in skill.summary and len(skill.summary) < 120, skill.summary


# ============================================================ e：反真空
def test_e_stubbing_the_naming_back_to_empty_turns_a_red(tmp_path, monkeypatch):
    """e 反真空：把「点名未签成果」打桩成空（静默收工）⇒ a 那组断言必须红。"""
    st = _ws(tmp_path)
    f, pid, sids = _two_unsigned_outputs(st)
    real = FD.delivery_summary

    def _silent(*a, **kw):
        got = real(*a, **kw)
        got["unfinished"] = []
        got["unfinished_count"] = 0
        got["close_problems"] = []
        got["legal_stop"] = True
        return got

    monkeypatch.setattr(FD, "delivery_summary", _silent)
    out = _close_reading(f, pid)
    silent = dict(out.get("delivery") or {})
    assert silent.get("legal_stop") is True, silent          # 打桩之后它"静默收工"了
    with pytest.raises(AssertionError):
        _assert_close_names(silent, sids)
