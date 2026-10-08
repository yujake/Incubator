# -*- coding: utf-8 -*-
"""S1k-3：名字面的判据（S1k-2 落地时欠下的那一半）。

`draft/92` §3.2 的两件事在这一批被钉住：
① 两个新形状（`retire` / `roster`）真能到秘书那一侧、并只转发不判定；
② 派活时按 `brief` 登记名册；消息按名册名投递（落到收件人名下的板项）、越界受控拒绝。

## 判据（正控 3 / 负控 2 / 反真空 2）

正控：① `{"retire":{"name":"D1"}}` ⇒ 秘书执行退役（销号名单 + 父侧落痕）
② `{"roster":{"of":"self"}}` ⇒ 回名册视图（名字 + 简介 + 状态）
③ 带 `brief` 的派活 ⇒ 名册里出现 D1（这一条走真 `LlmBackend`，子循环也真跑）。
负控：① 给未登记的名字发消息 ⇒ `receipt="unknown"` 且不开项
② 查兄弟的名册 ⇒ 受控拒绝（可见面 = 我自己的 + 我名下子代理的）。
反真空：没有秘书（`auto_secretary=False`）⇒ 退役与查名册都如实拒绝/三态，不许当成功。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s1k3"


class _Gate:
    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[dict]) -> None:
        self.replies = replies
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.systems.append(system or "")
        item = self.replies[min(len(self.systems) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": item.get("text", ""),
                                  "tool_calls": tuple(item.get("tool_calls", ())),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _env(tmp_path: pathlib.Path) -> tuple[Store, Conductor, Any, pathlib.Path, str, AgentLoop, _Gate]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    me = cond.open_top_level_run("M", "我这一趟的活")
    gate = _Gate([{"text": json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)}])
    loop = AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    loop.my_task_id = me
    return st, cond, reg, ws, me, loop, gate


def _child(cond: Conductor, parent: str, *, key: str, status: str = "done") -> str:
    return cond._write_new_row({
        "task_id": "", "role": "D", "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": status,
        "outcome": None if status in ("pending", "running") else "ok",
        "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-08T22:00:00+08:00",
        "ended_at": None if status in ("pending", "running") else "2026-10-08T22:05:00+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")


def test_the_retire_shape_reaches_the_secretary(tmp_path: pathlib.Path):
    """正控：`{"retire": {"name": "D1"}}` ⇒ 秘书真执行（销号名单 + 父侧幂等落痕）。"""
    st, cond, _reg, ws, me, loop, _gate = _env(tmp_path)
    child = _child(cond, me, key="s1k3@a")
    assert loop.secretary.roster_add(owner=me, role="D", task_id=child,
                                     brief="可以退的那件")["name"] == "D1"
    got = loop._do_retire({"name": "D1"})            # noqa: SLF001 —— 判据要的就是这一层
    assert got["ok"] is True and got["action"] == "retired", got
    assert cond.released_edges(me)["edges"] == [{"child_task_id": child, "attempt": 1}]

    from agentflow.secretary import retired_path

    text = retired_path(ws, me).read_text(encoding="utf-8")
    assert '"name": "D1"' in text, text


def test_the_roster_shape_returns_the_roster_view(tmp_path: pathlib.Path):
    """正控：查名册回"名字 + 一句简介 + 状态"（业主："代理的查自己调用工具看"）。"""
    _st, cond, _reg, _ws, me, loop, _gate = _env(tmp_path)
    child = _child(cond, me, key="s1k3@b")
    loop.secretary.roster_add(owner=me, role="D", task_id=child, brief="看得见的那件")
    got = loop._do_roster({})                        # noqa: SLF001
    assert got["checked"] is True and got["rows"][0]["name"] == "D1", got
    assert got["rows"][0]["brief"] == "看得见的那件", got["rows"]
    assert got["rows"][0]["state"] in ("活跃", "待命", "已停"), got["rows"]


def test_a_summon_with_a_brief_registers_the_roster(tmp_path: pathlib.Path):
    """正控（走真 `LlmBackend`）：带 `brief` 的派活 ⇒ 名册里出现 D1。

    这一条跑真的子循环（脚本化网关），所以它同时钉住"登记发生在受理之后"：
    没跑成的派活（`refused`）不该留名册项。
    """
    from test_agent_loop import LOOPS, _wired
    from agentflow.agent_loop import LlmBackend, run_role

    st, cond, reg, gateways, root = _wired(
        tmp_path,
        {"M": [json.dumps({"summon": {"role": "D", "action": "write_report", "params": {},
                                      "brief": "把 X 的族构造证据补齐", "why": "试一试"}},
                          ensure_ascii=False),
               json.dumps({"final": "派完了", "evidence": []}, ensure_ascii=False)],
         "D": [json.dumps({"final": "干完了", "evidence": []}, ensure_ascii=False)]},
        max_steps=3)
    run = run_role("M", "派一件活给 D", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gateways["M"],
                                price=(0.0, 0.0), sid="test-run"),
                   session_root=root, workspace_root=str(root), sid="test-run",
                   max_steps=3, from_env=False)
    assert run.stop_reason == "final", run.to_dict()
    # 名册落在 `out/roster/`（owner = 父的台账号）；从盘上读回来，不依赖 `prompt_audit` 的键
    from agentflow.secretary import roster_path

    roster_files = sorted((root / "out" / "roster").glob("*.jsonl"))
    assert roster_files, "名册没落盘（这一条问的就是'登记发生了没有'）"
    text = "\n".join(p.read_text(encoding="utf-8") for p in roster_files)
    assert '"name": "D1"' in text and "把 X 的族构造证据补齐" in text, text
    owner = roster_files[0].stem
    assert roster_path(root, owner).is_file()
    assert LOOPS  # 这一条靠 `_wired` 的接线表；引用一下免得 lint 说它没用


def test_a_message_to_an_unknown_name_is_refused_without_opening_an_item(tmp_path: pathlib.Path):
    """负控：未登记的名字 ⇒ `receipt="unknown"`，且一个项都不许开。"""
    _st, cond, _reg, _ws, me, loop, _gate = _env(tmp_path)
    before = {r["task_id"] for r in cond.open_items_of(me)}
    got = loop._do_message({"to": "D9", "subject": "喂", "body": "在吗"})   # noqa: SLF001
    assert got["ok"] is False and got["receipt"] == "unknown", got
    assert "受控拒绝" in got["note"] or "名册里没有" in got["note"], got
    assert {r["task_id"] for r in cond.open_items_of(me)} == before, (
        "没译出来就不许开项", cond.open_items_of(me))


def test_a_message_by_name_lands_on_the_recipients_board(tmp_path: pathlib.Path):
    """正控（下行）：给 `D1` 发一条 ⇒ 板项挂在D1 的台账号下（只有它读得到，父不代读）。"""
    _st, cond, _reg, _ws, me, loop, _gate = _env(tmp_path)
    child = _child(cond, me, key="s1k3@c")
    loop.secretary.roster_add(owner=me, role="D", task_id=child, brief="收信的那件")
    got = loop._do_message({"to": "D1", "subject": "题目", "body": "正文"})  # noqa: SLF001
    assert got["ok"] is True and got["to_task_id"] == child, got
    items = {str(r["task_id"]): r for r in cond.open_items_of(child)}
    assert str(got["item_id"]) in items, items
    assert str(items[str(got["item_id"])].get("kind")) == "message"
    assert str(items[str(got["item_id"])].get("expects")) == "ack"
    assert not cond.open_items_of(me), ("父名下不许出现这一条（不许代读）", cond.open_items_of(me))


def test_roster_of_a_sibling_is_refused_and_no_secretary_is_three_state(tmp_path: pathlib.Path):
    """负控（可见面）+ 反真空（没有秘书）：越界查 ⇒ 拒；没秘书 ⇒ 如实三态/拒绝。"""
    _st, cond, reg, ws, me, loop, _gate = _env(tmp_path)
    other_parent = cond.open_top_level_run("A", "另一个父")
    sibling = _child(cond, other_parent, key="s1k3@sib")
    # 兄弟的孩子不在我名册里 ⇒ 我查不到（可见面只给"我自己的 + 我名下子代理的"）
    got = loop._do_roster({"of": "D7"})              # noqa: SLF001
    assert got["checked"] is False and "越界" in got["reason"], got
    assert sibling  # 它就是那个不该可见的对象

    bare = AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=_gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=None, sid=SID, auto_secretary=False)
    bare.my_task_id = me
    retired = bare._do_retire({"name": "D1"})        # noqa: SLF001
    assert retired["ok"] is False and "没有秘书" in "".join(retired["why"]), retired
    view = bare._do_roster({})                       # noqa: SLF001
    assert view["checked"] is False and "没有秘书" in view["reason"], view
