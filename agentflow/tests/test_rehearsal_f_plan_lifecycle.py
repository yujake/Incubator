# -*- coding: utf-8 -*-
"""彩排判据 C7：F 的 plan 生命周期（立项 → 推进 → 放弃三档 / 调整 / 上限 / D 的建议）。

## 业主口径（逐字，见 p281 那批提交）

> 「`math_error` 和 `difficulty` 是正确的，不再需要是正确的，需要调整是错误的，
>   需要调整在放弃中应该是不再需要放弃掉原 plan 再开一个新 plan。」
>
> 「若一个 F 开了多 plan 且未 finish 的同时推进的大于 2 个（已 finish 或放弃的不计入
>   该数），系统需拦截并给出提醒，内容类似"同时推进的 plan 个数已达上限 2，请先推进
>   已有 plan，或将新 plan 的计划汇报父 D，让父派其它 F 攻坚"。」
>
> 「D 可以查 F 的 plan 且发信息给 F 说关于 plan 的建议。」

## 这一条链钉的七段（每段都能单独红）

| 段 | 走什么真入口 | 终态读数（盘上可查） |
|---|---|---|
| a | `AgentF.create_plan` → `AgentF.step` → `AgentF.abandon_plan(reason=math_error)` | 同一 `plan_id` 的行：`status=abandoned`、`rounds=1`、`history` 两行（推进一行 + 放弃一行）、`abandon_kind=math_error` |
| b | 另两条 plan 各走 `create_plan` → `step` → 放弃 `difficulty` / `不再需要` | 两行各自 `abandoned`；`difficulty` 档的 `history` 带 `difficulty` 与归一后的 `salvaged`；「不再需要」那行逐字含四个字 |
| c | 「需要调整」当 `reason` 传 | 受控拒 `plan_abandon_reason_not_allowed`（不是一档理由），行一个字节不改；随后按口径做组合操作：放弃原 plan + 新开一条 |
| d | 两条在推 ⇒ 第三条 `create_plan` | 拒信逐字含业主那句提醒；`attack_plans` 不多一行；反真空：把上限打桩成 3 ⇒ 同一条必须建成 |
| e | D 用 `attack.status` / `attack.list_plans` 读 plan，用 `Secretary.handoff_add` 发建议，F 照建议放弃 | 消息落在 `manuscripts/handoffs.jsonl`（sender=D）；被点名的那条变 `abandoned`，另一条仍 `open` |
| f | D 的秘书审派活（`dispatch_fit`） | 只落 `out/secretary/dispatch_fit.jsonl` 一行并改「建议」、不拦派活：随后 `create_plan` 照常成功 |
| g | 反真空：把 `_write_plan` 打桩成空 | `abandon_plan` 仍回 `ok=True`，而盘上计划仍是 `open` ⇒ a/b/e 的终态断言不是读返回值 |

## 计数读数（第三条要求）

本文件所有「成功」都从台账数：`attack_plans` 行数与每行 `history` 长度。模型调用
为零（`step` 的子目标 owner=C，走既有的未接线分支并落 `dead_end` 产物），所以没有
金额可读；计数就是这一条链的账。

## 不做什么

- 不 mock `abandon_plan` / `create_plan` 本体（只有反真空那一段打桩写盘）；
- 不新增 schema 列、不改工具面；
- 不跑全量。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_f as AF  # noqa: E402
from agentflow import manuscripts as MAN  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import statementabandon as SA  # noqa: E402
from agentflow.agent_f import create_plan as CP  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}
REASON = "不再需要"
NOT_A_REASON = "需要调整"
#: 业主原话（逐字；a 段只断言这一句在拒信里）。
OWNER_TEXT = ("同时推进的plan个数已达上限2，请先推进已有plan，"
              "或将新plan的计划汇报父D，让父派其它F攻坚。")

#: 一个不会花钱的子目标：owner=C 走既有的未接线分支（dead_end 产物 + 一行 history）。
#: 为什么不用 owner=F：那要模型缝，而这一段量的是"生命周期"，不是推理本身。
SUBGOALS = [{"sid": "s1", "text": "把这一方向的可试路径列出来", "owner": "C",
             "testable": "列出的路径能被下一位接手的人直接照着做"}]


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _f(store: Store) -> AF.AgentF:
    return AF.AgentF(store, config={"workspace_root": store.root},
                     actor="agent-F-F1")


def _row(store: Store, pid: str) -> dict:
    return next(dict(r) for r in store.rows("attack_plans")
                if str(r.get("plan_id") or "") == pid)


def _history(store: Store, pid: str) -> list[dict]:
    return [dict(h) for h in (_row(store, pid).get("history") or [])]


def _create(f: AF.AgentF, key: str, *, problem: str = "难题") -> str:
    got = f.create_plan(problem, key, budget=dict(BUDGET),
                        subgoals=[dict(s) for s in SUBGOALS])
    assert got.get("ok") is True and got.get("created") is True, got
    return str(got["plan_id"])


def _step(f: AF.AgentF, pid: str) -> dict:
    got = f.step(pid)
    assert got.get("plan_id") == pid, got
    return got


# ============================================================ a：create → step → 放弃
def test_a_create_step_then_abandon_math_error(tmp_path: pathlib.Path) -> None:
    """a：立项 → 推进一轮 → `math_error` 放弃；终态从台账读，不回执读。"""
    st = _ws(tmp_path)
    f = _f(st)
    pid = _create(f, "PK-A")

    before = _row(st, pid)
    assert before["status"] == "open" and before["rounds"] == 0, before
    assert before["history"] == [], before

    stepped = _step(f, pid)
    assert stepped.get("round") == 1, stepped
    assert stepped.get("action") == "no_change", stepped
    assert stepped.get("outcome") == "no_change", stepped

    out = f.abandon_plan(pid, reason=SA.ABANDON_KIND_MATH_ERROR,
                         basis="第 3 步把 n=2 的情形当成了任意 n，结论不成立")
    assert out.get("ok") is True and out.get("status") == "abandoned", out

    row = _row(st, pid)
    assert row["status"] == "abandoned", row
    assert row["plan_id"] == pid, row
    assert int(row["rounds"]) == 1, row
    hist = _history(st, pid)
    assert len(hist) == 2, hist
    # 第一行是推进（step），第二行是放弃；放弃行刻意没有 outcome。
    assert hist[0].get("action") == "no_change", hist
    assert hist[1].get("action") == "abandon", hist
    assert hist[1].get("abandon_kind") == "math_error", hist
    assert "第 3 步" in str(hist[1].get("detail") or ""), hist
    assert "outcome" not in hist[1], hist
    # 终态先到先得：再放弃一次是受控拒，盘上不改。
    with pytest.raises(AF.PlanError) as ei:
        f.abandon_plan(pid, reason=REASON)
    assert "plan_already_terminal" in str(ei.value), str(ei.value)
    assert _row(st, pid) == row, "终态计划被改写了"

    # 计数读数：一条 plan、两行 history（这就是这一条链的账）。
    assert len(list(st.rows("attack_plans"))) == 1
    assert len(_history(st, pid)) == 2


# ============================================================ b：另两档
def test_b_difficulty_and_not_needed_tiers_land_on_disk(tmp_path: pathlib.Path) -> None:
    """b：`difficulty` 与「不再需要」两档各走一条完整生命周期。"""
    st = _ws(tmp_path)
    f = _f(st)

    hard = _create(f, "PK-B-HARD", problem="难题乙")
    _step(f, hard)
    out = f.abandon_plan(
        hard, reason="difficulty",
        basis="卡在紧性估计：需要一条与主链独立的界",
        difficulty="紧性引理拿不到一致常数",
        salvaged=[{"label": "部分紧性", "stmt_id": "000051"}])
    assert out.get("ok") is True, out
    hist = _history(st, hard)
    assert hist[-1]["abandon_kind"] == "difficulty", hist
    assert "紧性" in str(hist[-1].get("difficulty") or ""), hist
    assert hist[-1].get("salvaged") == [{"label": "部分紧性", "stmt_id": "000051"}], hist

    unneeded = _create(f, "PK-B-NEED", problem="难题丙")
    _step(f, unneeded)
    assert f.abandon_plan(unneeded, reason=REASON,
                          basis="目标已改为另一条方向").get("ok") is True
    hist2 = _history(st, unneeded)
    assert hist2[-1]["abandon_kind"] == REASON, hist2
    assert REASON in str(hist2[-1].get("detail") or ""), hist2

    rows = [dict(r) for r in st.rows("attack_plans")]
    assert len(rows) == 2, rows
    assert {str(r["status"]) for r in rows} == {"abandoned"}, rows
    assert sum(len(list(r.get("history") or [])) for r in rows) == 4, rows


# ============================================================ c：「需要调整」是组合操作
def test_c_adjust_is_abandon_plus_a_new_plan_not_a_reason(tmp_path: pathlib.Path) -> None:
    """c：「需要调整」不是理由值；按口径做组合操作：放弃原 plan + 新开一条。"""
    st = _ws(tmp_path)
    f = _f(st)
    old = _create(f, "PK-C-OLD", problem="原方向")
    before = _row(st, old)

    with pytest.raises(AF.PlanError) as ei:
        f.abandon_plan(old, reason=NOT_A_REASON)
    err = str(ei.value)
    assert "plan_abandon_reason_not_allowed" in err, err
    assert REASON in err, err
    assert "组合操作" in err, err
    assert _row(st, old) == before, "被拒的那一笔写了库"

    assert f.abandon_plan(old, reason=REASON,
                          basis="按新方向重排").get("ok") is True
    new = _create(f, "PK-C-NEW", problem="新方向")
    assert new != old, (old, new)
    rows = [dict(r) for r in st.rows("attack_plans")]
    assert len(rows) == 2, rows
    assert _row(st, old)["status"] == "abandoned", _row(st, old)
    assert _row(st, new)["status"] == "open", _row(st, new)
    assert len(_history(st, old)) == 1, _history(st, old)
    assert _history(st, new) == [], _history(st, new)


# ============================================================ d：并发上限
def test_d_the_third_concurrent_plan_is_refused_with_the_owner_wording(
        tmp_path: pathlib.Path) -> None:
    """d：两条在推 ⇒ 第三条受控拒，拒信逐字含业主那句；台账零写入。"""
    st = _ws(tmp_path)
    f = _f(st)
    first = _create(f, "PK-D-A")
    second = _create(f, "PK-D-B")
    before = len(list(st.rows("attack_plans")))

    out = f.create_plan("难题丁", "PK-D-C", budget=dict(BUDGET),
                        subgoals=[dict(s) for s in SUBGOALS])
    assert out.get("ok") is False, out
    assert out.get("kind") == "parallel_plans_limit", out
    assert out.get("created") is False and out.get("plan_id") is None, out
    err = str(out.get("error") or "")
    assert OWNER_TEXT in err, err
    assert first in err and second in err, err
    assert out.get("refusal_reason") == "invalid_params", out
    assert len(list(st.rows("attack_plans"))) == before, st.rows("attack_plans")


def test_d2_anti_vacuum_a_wider_cap_lets_the_third_plan_in(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d2（反真空）：把上限打桩成 3 ⇒ 同一条第三 plan 必须建成。

    证明 d 的拒信来自这一格上限，而不是"第三条本来就建不出来"。
    """
    monkeypatch.setattr(CP, "PARALLEL_PLANS_LIMIT", 3)
    st = _ws(tmp_path)
    f = _f(st)
    _create(f, "PK-D2-A")
    _create(f, "PK-D2-B")
    out = f.create_plan("难题丁", "PK-D2-C", budget=dict(BUDGET),
                        subgoals=[dict(s) for s in SUBGOALS])
    assert out.get("ok") is True and out.get("created") is True, (
        "上限放宽到 3 之后仍然被拒 ⇒ d 的拒信不来自这一格", out)
    assert len(list(st.rows("attack_plans"))) == 3


# ============================================================ e：D 读 plan → 建议 → F 放弃
def test_e_d_reads_plans_advises_and_f_abandons(tmp_path: pathlib.Path) -> None:
    """e：D 的读口 → 既有消息面 → F 的写入口，终点是台账上的 `abandoned`。"""
    st = _ws(tmp_path)
    f = _f(st)
    keep = _create(f, "PK-E-KEEP", problem="方向一：把界算出来")
    drop = _create(f, "PK-E-DROP", problem="方向二：把同构类数出来")

    reg = build_registry(store=st).registry
    d_specs = {s.name: s for s in reg.for_role("D")}
    assert {"attack.status", "attack.list_plans"} <= set(d_specs), sorted(d_specs)
    status = reg.call("attack.status", role="D", plan_id=drop)
    assert status.ok, status
    view = dict(status.data or {})
    assert view.get("status") == "open", view
    assert "方向二" in str(view.get("problem") or ""), view
    listed = reg.call("attack.list_plans", role="D")
    assert listed.ok, listed
    names = {str(p.get("plan_id")) for p in (dict(listed.data or {}).get("plans") or [])}
    assert {keep, drop} <= names, (names, listed.data)

    sec = SEC.Secretary("D", root=st.root, store=st)
    rec = sec.handoff_add(
        to="F", summary=f"计划 {drop} 不再需要",
        body=(f"计划 {drop}（方向二）不再需要了：方向已改，请把它放弃成「不再需要」；"
              f"计划 {keep} 继续推进。"),
        refs=[f"plan:{drop}"])
    assert rec.get("id") or rec.get("mid"), rec
    rows = [dict(r) for r in MAN.rows(st.root)]
    mine = [r for r in rows if drop in str(r.get("body") or "")]
    assert mine, rows
    assert str(mine[-1].get("sender") or "") == "D", mine[-1]

    out = f.abandon_plan(drop, reason=REASON, basis="D 的建议：方向已改")
    assert out.get("ok") is True and out.get("status") == "abandoned", out
    assert _row(st, drop)["status"] == "abandoned", _row(st, drop)
    assert _row(st, keep)["status"] == "open", _row(st, keep)
    assert len(list(st.rows("attack_plans"))) == 2


# ============================================================ f：dispatch_fit 只提醒
class _FakeSeam:
    """判定面替身：直接回写死的 JSON（D 的秘书用）。"""

    def __init__(self, data: dict) -> None:
        self.data = dict(data)

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        call = type("Call", (), {"ok": True, "problem": "", "detail": ""})()
        return dict(self.data), call


_BUNDLED = {"decision": "不是一个方向",
            "reason": "这条派活里捆了两个方向 ⇒ 建议拆成两条：各派一个 F",
            "basis": ["task 里同时出现两个方向"]}
_ONE = {"decision": "是一个方向", "reason": "只写了一个方向",
        "basis": ["task 只写了一个方向"]}


def test_f_dispatch_fit_reminds_but_never_blocks(tmp_path: pathlib.Path) -> None:
    """f：派活审阅改「建议」、落一行台账；派活本身照发（不拦）。"""
    st = _ws(tmp_path)
    sec = SEC.Secretary("D", root=st.root, store=st, seam=_FakeSeam(_BUNDLED),
                        enable_model=True)
    out = sec.assess_delegation(to="F", action="", params={},
                                task="方向甲：把界算出来；方向乙：把同构类数出来")
    assert out.get("decision") == "建议重排", out
    assert "派活审阅" in str(out.get("reason") or ""), out
    rows = SEC.dispatch_fit_rows(st.root)
    assert len(rows) == 1 and rows[0].get("verdict") == "不是一个方向", rows
    assert "方向甲" in str(rows[0].get("task") or ""), rows
    # 只提醒不拦：随后真的立项，台账多一行。
    f = _f(st)
    pid = _create(f, "PK-F-AFTER-REMINDER", problem="研究方向甲")
    assert _row(st, pid)["status"] == "open", _row(st, pid)


def test_f2_anti_vacuum_a_suitable_verdict_removes_the_reminder(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f2（反真空）：把判定内核打桩成恒「合适」⇒ f 的「建议重排」必须消失。"""
    st = _ws(tmp_path)
    sec = SEC.Secretary("D", root=st.root, store=st, seam=_FakeSeam(_BUNDLED),
                        enable_model=True)
    monkeypatch.setattr(
        SEC.Secretary, "_judge_core",
        lambda self, kind, context, **kw: {"checked": True, "decision": "是一个方向",
                                           "reason": "夹具：恒合适", "basis": []})
    out = sec.assess_delegation(to="F", action="", params={},
                                task="方向甲与方向乙一起做")
    assert out.get("decision") == "可派", out


# ============================================================ g：反真空（真写盘）
def test_g_stubbing_the_write_keeps_the_plan_open(tmp_path: pathlib.Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """g（反真空）：把 `_write_plan` 打桩成空 ⇒ 回执仍 `ok=True`，而盘上仍是 `open`。

    这是 a/b/e 终态断言的证明：它们读的是台账，不是回执。``json`` 只用在这里的
    读数打印，防止别处悄悄把 `json` 当成判据。
    """
    st = _ws(tmp_path)
    f = _f(st)
    pid = _create(f, "PK-G")
    monkeypatch.setattr(AF.AgentF, "_write_plan", lambda self, row, *, note: None)
    out = f.abandon_plan(pid, reason=REASON)
    assert out.get("ok") is True, out
    row = _row(st, pid)
    assert row["status"] == "open", (
        "写盘被打桩成空之后计划竟然变成 abandoned ⇒ 终态断言不是读盘", row)
    assert [h for h in (row.get("history") or [])
            if h.get("action") == "abandon"] == [], row
    # 计数读数：这一步之后仍然是 1 条 plan、0 行 history。
    assert len(list(st.rows("attack_plans"))) == 1
    assert len(_history(st, pid)) == 0


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
