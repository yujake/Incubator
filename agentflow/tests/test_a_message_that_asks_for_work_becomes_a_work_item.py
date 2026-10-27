# -*- coding: utf-8 -*-
"""D12：要求做事的 message ⇒ 收件人自己落一条 work 板项（业主 2026-10-27 逐字）。

## 业主原话

```
「如果message是要求做事，智能体需自己写任务塞进task_board，这样就消费了真正有信息的message」
```

配上同一批的另一句（`tests/test_information_items_are_acked_when_read.py` 的模块头）：
```
「所有message都是板项，我们要做的只是让message类的seen=ack」
```

合起来是两种结局：只是告知 ⇒ 读到就消费（`seen` 即 ack，板项收口）；要求做事 ⇒
收件人自己落一条 work 板项（`conductor.post_task`），消息本身仍然在读到那一拍消费。

## 判据分两层（这一条边界是业主认的）

- 机器可判层（这一份钉的）：当模型决定"这事要办"时，它有没有一条合法手
  （`conductor.post_task` 在工具面上、只许给自己、落的行是 `delegation`/`work`/`queued`）；
  以及"名下的 work 板项"这件事在不执行那一步时必然观测不到（反真空）。
- 不可判层：模型这一次判得对不对 —— "是不是要求做事"没有机器可判的客观量。
  这一份用脚本化模型（`_Gate`）演，不许把它当成语义正确性的判据。

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_a_message_that_asks_for_work_becomes_a_work_item` | 模型走了那条手 ⇒ 名下出现一条 work 板项，且那条 message 已收口 | 改前没有这条手（工具面 96 件里没有"给自己派活"）：`conductor.summon` 只造子任务、`conductor.ack` 只收口，唯一的野路是未设防的 `table.create(tasks)` |
| b) `test_b_a_plain_message_does_not_create_work` | 正控：纯告知的 message ⇒ 不许产生 work 板项（别把所有消息都变成任务） | 不适用（它守的是"别过度反应"） |
| c) `test_c_the_hand_only_posts_to_itself` | 只许 target=自己（"别人办一件事"走 `conductor.summon`） | 改前 `table.create(tasks)` 能把板项种到任何人名下（实测 `agentflow/temp/_d12_probe_write_width.py`） |
| d) `test_d_stubbing_the_post_makes_a_red` | 反真空：把"落 work 板项"那一步打桩成不执行 ⇒ (a) 的判据本体必红 | 不适用（它守的是 a 不是真空的那一条） |
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import schema as S
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

TS = "2026-01-01T00:00:00+00:00"
SID = "d12work"
FINAL = json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)
POST = json.dumps({"tool": "conductor.post_task",
                   "args": {"summary": "把第 2 步补上（V 判有毛病）"}}, ensure_ascii=False)
NOTE = json.dumps({"tool": "table.list", "args": {"table": "tasks"}}, ensure_ascii=False)


class _Gate:
    """脚本化模型：按次序回放固定的几句（`complete` 的签名与 `LlmSeam` 的缝一致）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


# ====================================================================== 夹具
def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    me = str(cond.open_top_level_run("M", "D12：要求做事的 message"))
    return {"ws": ws, "store": st, "cond": cond, "me": me,
            "reg": build_registry(store=st, conductor=cond,
                                  workspace_root=str(ws)).registry}


def _message(cond: Conductor, to: str, *, detail: str, key: str) -> str:
    item = cond.open_item(kind="message", role="M", expects="ack", action="message",
                          summary=detail[:120], called_by="B", parent_task_id=to,
                          depth=2, input_key=key)
    cond.set_item_detail(item, detail)
    return item


def _run(env: dict[str, Any], replies: list[str], *, steps: int = 4) -> Any:
    gate = _Gate(replies)
    loop = AgentLoop(role="M", session_root=env["ws"], registry=env["reg"],
                     conductor=env["cond"],
                     seam=LlmSeam(role="M", session_root=env["ws"], gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=env["store"], sid=SID, max_steps=steps)
    run = loop.run("把这一趟做完", summoned_by="user", my_task_id=env["me"], depth=1)
    return {"run": run, "gate": gate}


def _row(st: Store, item: str) -> dict:
    return next(r for r in st.rows("tasks") if str(r.get("task_id")) == str(item))


def _work_items(cond: Conductor, to: str) -> list[dict]:
    """`to` 名下"要办的一件活"：`kind=delegation` 且 `expects=work` 的板项。"""
    return [r for r in cond._board_rows()
            if str(r.get("parent_task_id") or "") == str(to)
            and str(r.get("kind") or "") == "delegation"
            and str(r.get("expects") or "") == "work"]


# ====================================================================== a) 要办事
def _a_problems(tmp_path: pathlib.Path) -> list[str]:
    """(a) 的判据本体：模型走了 `conductor.post_task` ⇒ 名下多一条 work 项，消息已收口。"""
    problems: list[str] = []
    env = _env(tmp_path)
    me = str(env["me"])
    before = {str(r["task_id"]) for r in _work_items(env["cond"], me)}
    incoming = _message(env["cond"], me, key="message@B:t-1->me",
                        detail="V 判有毛病，请把第 2 步补上后重送 V")
    _run(env, [POST, FINAL])
    after = _work_items(env["cond"], me)
    fresh = [r for r in after if str(r["task_id"]) not in before]
    if not fresh:
        problems.append("模型调了 `conductor.post_task`，名下却没有出现一条 work 板项"
                        f"（全部板项：{[(r.get('task_id'), r.get('kind'), r.get('expects')) for r in after]}）")
    else:
        row = fresh[0]
        # 它落下来之后，下一步的信箱投递就会把它渲染给"未来的我自己" ⇒ 状态可能是
        # queued（还没渲染到）或 seen（已渲染）。不许是 done：work 项读了不等于办了
        # （它要 `conductor.ack(close="completed")` 才收口）。
        if str(row.get("item_state")) not in ("queued", "seen"):
            problems.append(f"刚落的 work 项被代收口了：{row.get('item_state')!r}"
                            "（读了不等于办了）")
        if str(row.get("item_close")):
            problems.append(f"work 项被写了 item_close={row.get('item_close')!r}")
        if str(row.get("task_id")) not in {str(r["task_id"])
                                           for r in env["cond"].open_items_of(me)}:
            problems.append("刚落的 work 项不在'名下未消的项'里 ⇒ 销号门看不见它")
        if str(row.get("called_by")) != "M":
            problems.append(f"work 项的『谁开的』应当是调用者自己，收到 {row.get('called_by')!r}")
        if int(row.get("depth") or 0) != 2:
            problems.append(f"work 项的深度应当是收件人 + 1（=2），收到 {row.get('depth')!r}")
    msg = _row(env["store"], incoming)
    if (str(msg.get("item_state")), str(msg.get("item_close"))) != ("done", "acked"):
        problems.append(f"那条 message 被读到之后没有收口："
                        f"{msg.get('item_state')!r}/{msg.get('item_close')!r}")
    return problems


def test_a_a_message_that_asks_for_work_becomes_a_work_item(
        tmp_path: pathlib.Path) -> None:
    """a) 正控：要求做事的 message ⇒ 名下出现一条 work 板项，消息本身当拍收口。"""
    assert _a_problems(tmp_path) == [], _a_problems(tmp_path)


# ====================================================================== b) 纯告知
def test_b_a_plain_message_does_not_create_work(tmp_path: pathlib.Path) -> None:
    """b) 正控（反过度反应）：纯告知的 message 读到就消费，但不许产生 work 板项。"""
    env = _env(tmp_path)
    me = str(env["me"])
    incoming = _message(env["cond"], me, key="message@B:t-2->me",
                        detail="通知：今晚的巡查改到 23:00（只是告知，不用你办什么）")
    _run(env, [NOTE, FINAL])
    assert _work_items(env["cond"], me) == [], (
        "纯告知的 message 被读成了任务（所有消息都变成待办 = 另一种积压）",
        _work_items(env["cond"], me))
    msg = _row(env["store"], incoming)
    assert (str(msg.get("item_state")), str(msg.get("item_close"))) == ("done", "acked"), msg


# ====================================================================== c) 只许给自己
def test_c_the_hand_only_posts_to_itself(tmp_path: pathlib.Path) -> None:
    """c) 负控：`conductor.post_task` 只许给自己 —— 别人的活走 `conductor.summon`。"""
    env = _env(tmp_path)
    me = str(env["me"])
    other = env["cond"]._write_new_row({
        "role": "D", "action": "write_report", "called_by": "M",
        "parent_task_id": me, "depth": 2, "input_key": "d12c:child",
        "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "别人", "error": None, "started_at": TS, "ended_at": TS,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="fixture:child")
    with calling_as(me, "M"):
        res = env["reg"].call("conductor.post_task", {"summary": "给 D 派一件事"}, role="M")
    assert res.ok is True, (res.error, res.meta)
    item = str(res.data["item_id"])
    row = _row(env["store"], item)
    assert str(row.get("parent_task_id")) == me, ("收件人不是调用者自己", row)
    assert str(item) not in {str(r["task_id"]) for r in env["cond"].open_items_of(other)}, (
        "它在别人的板上落了项（这条手只许给自己）")
    # 工具形状里根本没有"给谁"这一格 —— 那是 `conductor.summon` 的事
    spec = next(s for s in env["reg"]._specs.values()
                if s.name == "conductor.post_task") if hasattr(env["reg"], "_specs") else None
    if spec is not None:
        assert "to" not in (spec.params or {}).get("properties", {}), spec.params


# ====================================================================== d) 反真空
def test_d_stubbing_the_post_makes_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 反真空：把「落 work 板项」那一步打桩成不执行 ⇒ (a) 的判据本体必红。"""
    assert _a_problems(tmp_path / "a0") == []

    real_open = Conductor.open_item

    def _refuse_self_post(self: Conductor, **kwargs: Any) -> str:
        if str(kwargs.get("action") or "") == "post_task":
            raise RuntimeError("打桩：这一步不执行")
        return real_open(self, **kwargs)

    monkeypatch.setattr(Conductor, "open_item", _refuse_self_post)
    got = _a_problems(tmp_path / "a1")
    assert got, "把落 work 项那一步打桩掉，(a) 却仍然绿 ⇒ 这条判据没在看那一件事"
    assert any("work 板项" in x for x in got), got
