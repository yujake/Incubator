# -*- coding: utf-8 -*-
"""D12：信息型板项「渲染即收口」—— seen 就是 ack（业主 2026-10-27 逐字）。

## 业主原话（唯一权威）

```
「我们的实现是所有message都是板项，我们要做的只是让message类的seen=ack」
```

## 这一份钉住的四件事

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_a_clock_wake_notice_is_closed_on_the_tick_it_is_rendered` | 时钟报醒（`kind=notice`、`input_key=clock:…`）被拼进提示词那一拍就收口：`item_state="done"` + `item_close="acked"` | 改前它停在 `seen` 再也不动（真机 `projects/mp3-r3`：12 条板项全部 `seen`、`conductor.ack` 调用 0 次） |
| b) `test_b_a_work_item_is_not_acked_by_being_read` | 真正要办的项（V 判「有毛病」⇒ 补第 N 步，`v-verdict@…`）读了仍然是 `seen`：不 ack 就不算清 | 反向：把「要办的事」也代 ack，会让"还没补"这件事从盘上消失 |
| c) `test_c_a_child_with_only_wake_notices_can_be_retired` | 只挂着若干条报醒 notice 的静默子代理 ⇒ 销号门不再被「板项没清」假拦 | 改前同一份夹具被拒：「名下还有 N 条未消的板项 ⇒ task_board 没清，不许直接销号」 |
| d) `test_d_stubbing_the_settle_step_makes_a_and_c_red` | 反真空：把「渲染即收口」打桩成不执行 ⇒ a 与 c 的判据本体必须报红 | 不适用（它守的是 a/c 不是真空的那两条） |

## 「渲染」在这里是哪一拍（判据的机器形态）

生产里只有一个入口会"把项拼进提示词"：`agent_loop.board_digest` 渲染 + 紧接着
`Conductor.mark_item_seen`（`_hear` 与 `run` 的 `pending_seen` 两处都只经它）。
所以这一份用同一对调用模拟那一拍：先 `board_digest` 拿到"这一拍渲染了哪几条"，
再对它们调 `mark_item_seen` —— 与生产的次序、判据集合完全一致。

收口落在 `Conductor.mark_item_seen` → `_settle_if_informational` 里，理由是它才是
"先看到被渲染"的那个函数（两处渲染点都只经它，`agent_loop.py` 一个字都不用改）。

## 为什么不给 `expects` 新开一档

`ITEM_EXPECTS` 只有 `ack` / `work` 两档，而 `item_close="acked"` 只与 `expects="ack"`
配对（`schema.Task.validate` 的交叉校验）。"信息型"不是第三档 expects，它是
"这一档项被消费在'读它'本身"这一个事实 —— 所以收口用既有的 `done` + `acked`，
一个取值都不新造。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import agent_loop as AL
from agentflow import schema as S
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT
from agentflow.tools.base import ToolRegistry

TS = "2026-01-01T00:00:00+00:00"
SID = "d12info"
RETIRE = "conductor.retire_child"


# ====================================================================== 夹具
def _ws(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个工作区 ＋ 一个主控 ＋ 父那一趟的秘书（与 `test_retire_only_for_the_silent` 同一条取法）。"""
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=st)
    # 生产里由 `AgentLoop._bind_roster_sink` 接上；这里显式接，让销号与名册落同一份文件。
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "D12：信息型板项"))
    return {"root": root, "store": st, "cond": cond, "sec": sec, "owner": owner}


def _agent(cond: Conductor, parent: str, *, role: str = "D") -> str:
    """一行静默的子代理（`status=done` ⇒ 无工作、无计时器、无活跃子）。"""
    return cond._write_new_row({
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"d12:{role}",
        "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "静默的子代理", "error": None, "started_at": TS, "ended_at": TS,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="fixture:agent")


def _register(env: dict[str, Any], task_id: str, *, role: str = "D") -> str:
    got = env["sec"].roster_add(owner=str(env["owner"]), role=role, task_id=task_id,
                                brief="写研究报告")
    assert got.get("problem") == "", got
    return str(got["name"])


def _clock_notice(cond: Conductor, to: str, *, timer_id: str,
                  detail: str = "时间到：检查子代理是否回来｜等了 5 分钟") -> str:
    """落一条时钟报醒（与 `tools/clock_tools._open_mailbox_item` 逐字同形）。"""
    item = cond.open_item(kind="notice", role="M", expects="ack", action="notice",
                          summary=detail[:200], called_by="clock",
                          parent_task_id=to, depth=2,
                          input_key=f"clock:{timer_id}")
    cond.set_item_detail(item, detail)
    return item


def _message(cond: Conductor, to: str, *, key: str, detail: str = "开工前先写手稿") -> str:
    """落一条留言（`kind=message`，`called_by` 是同伴）。"""
    item = cond.open_item(kind="message", role="M", expects="ack", action="message",
                          summary=detail, called_by="M", parent_task_id=to, depth=2,
                          input_key=key)
    cond.set_item_detail(item, detail)
    return item


def _verdict(cond: Conductor, to: str, *, label: str = "thm:000001") -> str:
    """落一条 V 判「有毛病」的项（`v-verdict@…`，与 `deliver_v_verdicts` 逐字同形）。"""
    item = cond.open_item(
        kind="notice", role="M", expects="ack", action="notice",
        summary=f"V 判「有毛病」：{label}（错在第 2 步）", called_by="V",
        parent_task_id=to, depth=2, input_key=f"{AL.V_VERDICT_ITEM_PREFIX}{label}@v1")
    cond.set_item_detail(item, f"下一步该补的就是第 2 步；补完把这一份重新送 V")
    return item


def _row(st: Store, item: str) -> dict:
    return next(r for r in st.rows("tasks") if str(r.get("task_id")) == str(item))


def _render_once(cond: Conductor, owner: str, *, step: int = 1) -> list[str]:
    """模拟「被拼进提示词那一拍」：`board_digest` 渲染 → 对渲染到的每一条 `mark_item_seen`。"""
    _text, ids, problems = AL.board_digest(cond, my_task_id=owner)
    assert problems == [], problems
    for item in ids:
        state, why = cond.mark_item_seen(item, by_task_id=owner, step=step)
        assert state, why
    return [str(x) for x in ids]


def _retire(env: dict[str, Any], name: str) -> Any:
    reg = ToolRegistry(name="d12-retire")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    with calling_as(str(env["owner"]), "M"):
        return reg.call(RETIRE, {"child_name": name, "reason": "它交完了"}, role="M")


# ====================================================================== a) 报醒
def _a_problems(tmp_path: pathlib.Path) -> list[str]:
    """(a) 的判据本体：时钟报醒被渲染一拍之后必须是 done+acked，且不再占"未消项"。"""
    problems: list[str] = []
    env = _ws(tmp_path)
    owner = str(env["owner"])
    item = _clock_notice(env["cond"], owner, timer_id="t-000001")
    rendered = _render_once(env["cond"], owner)
    if item not in rendered:
        problems.append(f"报醒项 {item} 没被渲染到（这一拍什么也没测到）：{rendered}")
    row = _row(env["store"], item)
    if str(row.get("item_state")) != "done":
        problems.append(f"报醒项渲染一拍之后 item_state={row.get('item_state')!r}"
                        "（改前形态：永远停在 seen，见真机 projects/mp3-r3）")
    if str(row.get("item_close")) != "acked":
        problems.append(f"报醒项渲染一拍之后 item_close={row.get('item_close')!r}"
                        "（要 acked：它与 expects='ack' 配对）")
    if int(row.get("seen_step") if row.get("seen_step") is not None else -1) != 1:
        problems.append(f"seen_step 丢了（这一格是'谁在第几步读的'）：{row.get('seen_step')!r}")
    if str(row.get("seen_by")) != owner:
        problems.append(f"seen_by 丢了：{row.get('seen_by')!r}")
    if str(item) in {str(r["task_id"]) for r in env["cond"].open_items_of(owner)}:
        problems.append("收口之后它还挂在'名下未消的项'里（这正是永久积压的形态）")
    return problems


def test_a_a_clock_wake_notice_is_closed_on_the_tick_it_is_rendered(
        tmp_path: pathlib.Path) -> None:
    """a) 正控：起一条时钟报醒 ⇒ 渲染一拍之后 done + acked（改前红：永远 seen）。"""
    assert _a_problems(tmp_path) == [], _a_problems(tmp_path)


def test_a2_the_same_holds_for_a_plain_message(tmp_path: pathlib.Path) -> None:
    """a 的附条（业主原话的"所有 message"）：留言同样是信息型 ⇒ 渲染即收口。"""
    env = _ws(tmp_path)
    owner = str(env["owner"])
    item = _message(env["cond"], owner, key="message@B:t-000002->t-000001")
    rendered = _render_once(env["cond"], owner)
    assert item in rendered, rendered
    row = _row(env["store"], item)
    assert (str(row.get("item_state")), str(row.get("item_close"))) == ("done", "acked"), row


def test_a3_a_notice_that_was_never_rendered_stays_queued(tmp_path: pathlib.Path) -> None:
    """a 的负控：没渲染过的报醒不许被收口（"读过了"必须真读过）。

    这一条挡的是"到点就自动收口"那种写法：那会让"这一拍有没有醒过来"从盘上消失。
    """
    env = _ws(tmp_path)
    owner = str(env["owner"])
    item = _clock_notice(env["cond"], owner, timer_id="t-000002")
    row = _row(env["store"], item)
    assert (str(row.get("item_state")), str(row.get("item_close"))) == ("queued", ""), row
    assert str(item) in {str(r["task_id"]) for r in env["cond"].open_items_of(owner)}


# ====================================================================== b) 待办
def _b_problems(tmp_path: pathlib.Path) -> list[str]:
    """(b) 的判据本体：要你办事的项读了仍是 seen；不 ack 就不算清；ack 之后才 done。"""
    problems: list[str] = []
    env = _ws(tmp_path)
    owner = str(env["owner"])
    item = _verdict(env["cond"], owner)
    rendered = _render_once(env["cond"], owner)
    if item not in rendered:
        problems.append(f"V 判据项没被渲染到：{rendered}")
    row = _row(env["store"], item)
    if str(row.get("item_state")) != "seen":
        problems.append(f"要办的项被读一下就变成了 {row.get('item_state')!r}"
                        "（读了不等于办了：它会从销号门的清单里消失）")
    if str(row.get("item_close")):
        problems.append(f"要办的项被代写了 item_close={row.get('item_close')!r}")
    if str(item) not in {str(r["task_id"]) for r in env["cond"].open_items_of(owner)}:
        problems.append("要办的项不在'名下未消的项'里 ⇒ 销号门看不见它")
    # 它仍然要靠模型自己 ack 才收口（这只手没有退化）
    got = env["cond"].ack_items([item], by_task_id=owner, note="补完了")
    if not got.get("ok"):
        problems.append(f"conductor.ack 收不了这条要办的项：{got}")
    after = _row(env["store"], item)
    if (str(after.get("item_state")), str(after.get("item_close"))) != ("done", "acked"):
        problems.append(f"ack 之后应当是 done+acked，收到 {after.get('item_state')!r}/"
                        f"{after.get('item_close')!r}")
    return problems


def test_b_a_work_item_is_not_acked_by_being_read(tmp_path: pathlib.Path) -> None:
    """b) 正控（别把待办也取消）：V 判「有毛病」读了仍是 seen，必须模型自己 ack。"""
    assert _b_problems(tmp_path) == [], _b_problems(tmp_path)


# ====================================================================== c) 销号门
def _c_problems(tmp_path: pathlib.Path) -> list[str]:
    """(c) 的判据本体：只挂报醒 notice 的静默子 ⇒ 销得掉（不再被"板项没清"拦）。"""
    problems: list[str] = []
    env = _ws(tmp_path)
    owner = str(env["owner"])
    child = _agent(env["cond"], owner)
    name = _register(env, child)
    for timer_id in ("t-000010", "t-000011", "t-000012"):
        _clock_notice(env["cond"], child, timer_id=timer_id)
    _render_once(env["cond"], child, step=1)
    res = _retire(env, name)
    data = dict(getattr(res, "data", None) or {})
    if str(data.get("state")) != "retired":
        problems.append(f"只挂着报醒 notice 的静默子销不掉：state={data.get('state')!r}、"
                        f"reason={data.get('reason')!r}、open_items={data.get('open_items')!r}")
    if str(data.get("refusal_code") or ""):
        problems.append(f"它被静默闸/别的闸拦了（不该）：{data.get('refusal_code')!r}")
    return problems


def test_c_a_child_with_only_wake_notices_can_be_retired(tmp_path: pathlib.Path) -> None:
    """c) 正控：只挂着若干条报醒 notice 的静默子代理 ⇒ 销号门不再被假拦（改前红）。"""
    assert _c_problems(tmp_path) == [], _c_problems(tmp_path)


def test_c2_a_child_with_an_unacked_verdict_is_still_refused(tmp_path: pathlib.Path) -> None:
    """c 的负控：板上留着一条没办的项 ⇒ 销号门照旧拒（这道闸一个字都没改）。"""
    env = _ws(tmp_path)
    owner = str(env["owner"])
    child = _agent(env["cond"], owner)
    name = _register(env, child)
    _clock_notice(env["cond"], child, timer_id="t-000020")
    _verdict(env["cond"], child, label="thm:000009")
    _render_once(env["cond"], child, step=1)
    data = dict(getattr(_retire(env, name), "data", None) or {})
    assert str(data.get("state")) == "refused", data
    assert "未消的板项" in str(data.get("reason") or ""), data
    assert str(data.get("refusal_code") or "") == "", (
        "板项闸拒的那一档不该带 target_not_silent（它不是一个'不静默'的结论）", data)


# ====================================================================== d) 反真空
def test_d_stubbing_the_settle_step_makes_a_and_c_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 反真空：把「渲染即收口」打桩成不执行 ⇒ a 与 c 的判据本体都必红。"""
    # 基线：同一份判据在不打桩时必须绿（否则下面的"红"证明不了任何事）
    assert _a_problems(tmp_path / "a0") == []
    assert _c_problems(tmp_path / "c0") == []

    def _no_settle(self: Conductor, task_id: str, *, step: int) -> tuple[str, str]:
        return "seen", ""                      # 只读不收口（改前形态）

    monkeypatch.setattr(Conductor, "_settle_if_informational", _no_settle)
    a = _a_problems(tmp_path / "a1")
    c = _c_problems(tmp_path / "c1")
    assert a, "把收口打桩掉，(a) 却仍然绿 ⇒ 这条判据没在看收口这件事"
    assert c, "把收口打桩掉，(c) 却仍然绿 ⇒ 销号门那条判据没接在收口上"
    assert any("item_state" in x for x in a), a
    assert any("销不掉" in x or "state=" in x for x in c), c


# ====================================================================== 口径的机器形态
def test_the_settle_never_invents_a_new_item_state(tmp_path: pathlib.Path) -> None:
    """口径：收口用的两个取值都在既有词表里（不许为它新造 item_state / item_close）。"""
    from agentflow.conductor import ACK_REQUIRED_ITEM_PREFIXES, INFORMATIONAL_ITEM_KINDS

    assert "done" in S.ITEM_STATES
    assert "acked" in S.ITEM_CLOSES
    # 排除表必须非空，且每一条都是"要你办事"的那一档（反真空：清空它等于把所有项都代 ack）
    assert "v-verdict@" in ACK_REQUIRED_ITEM_PREFIXES
    assert "stop-notice@" in ACK_REQUIRED_ITEM_PREFIXES
    assert "notice" in INFORMATIONAL_ITEM_KINDS
    assert "message" in INFORMATIONAL_ITEM_KINDS
    assert "delegation" not in INFORMATIONAL_ITEM_KINDS
