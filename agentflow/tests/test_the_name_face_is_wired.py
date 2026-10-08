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


def test_the_native_face_advertises_the_two_new_shapes():
    """正控（S1k-4）：原生广告面（`llmseam.META_FUNCTIONS`）与接受面同源。

    "广告一份、执行另一份"是本仓记过的坑（模型按广告写、框架说不认识）⇒ 两头都断言：
    广告面有 `framework_roster` / `framework_retire` 且必填键对得上；
    接受面（`_decode_shape`）真收 `retire`，并真把 `summon` 的 `brief`/`name`/`reuse` 带过去。
    """
    from agentflow import llmseam as LL
    from agentflow.agent_loop import _decode_shape

    table = {shape: (san, schema) for san, shape, schema in LL.META_FUNCTIONS}
    assert "retire" in table and "roster" in table, sorted(table)
    assert table["retire"][1].get("required") == ["name"], table["retire"][1]
    assert table["roster"][1].get("required") == [], table["roster"][1]
    props = table["summon"][1].get("properties", {})
    assert {"brief", "name", "reuse"} <= set(props), sorted(props)

    shape, _payload, problem = _decode_shape({"retire": {"name": "D1"}})
    assert (shape, problem) == ("retire", ""), (shape, problem)
    shape2, payload2, problem2 = _decode_shape(
        {"summon": {"role": "D", "action": "write_report", "params": {},
                    "brief": "把 X 补齐", "name": "D3"}})
    assert (shape2, problem2) == ("summon", ""), (shape2, problem2)
    assert payload2.get("brief") == "把 X 补齐" and payload2.get("name") == "D3", payload2
    assert "reuse" not in payload2, ("没给就不该凭空多一个键", payload2)


def test_summon_many_targets_carry_the_roster_keys():
    """正控（S1k-4）：一批派活的目标各带自己的 `brief` / `name` / `reuse`（没给就不带）。"""
    from agentflow.agent_loop import _decode_shape

    shape, payload, problem = _decode_shape({"summon_many": {"targets": [
        {"role": "D", "action": "write_report", "brief": "甲"},
        {"role": "E", "action": "run_experiment"},
    ], "why": "一批"}})
    assert (shape, problem) == ("summon_many", ""), (shape, problem)
    first, second = payload["targets"]
    assert first.get("brief") == "甲", first
    assert "brief" not in second and "name" not in second, second


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


# ---------------------------------------------------------------- 解码器那一段（真机抓出来的）

def test_the_two_new_shapes_survive_the_decoder(tmp_path: pathlib.Path):
    """正控（**真机抓出来的缺口**）：`retire` / `roster` 必须过得了解码器。

    M2 的 K1 探针实测（2026-10-09）：模型**完全按提示词**写了 `{"retire": {"name": "D1"}}`，
    而 `_decode_shape` 当时没有这两支 ⇒ 它们一路掉进 `final` 兜底 ⇒ payload 变成
    `{"final": "{\\"name\\": \\"D1\\"}"}` ⇒ `_do_retire` 读不到 `name`、连拒 6 次
    「要退谁：`name` 是名册名，不能空」、12 步用尽（`outcome=no_result`）。
    S1k-3 的判据**直接打在 `_do_retire` / `_do_roster` 上**，所以单测全绿 ——
    这一条补的就是"从模型的原始回复到形状"那一段路（`_shape_of` 是唯一入口）。
    """
    from agentflow.agent_loop import _shape_of

    for raw, shape, want in (
        ({"retire": {"name": "D1"}}, "retire", {"name": "D1"}),
        ({"roster": {"of": "self"}}, "roster", {"of": "self"}),
        ({"roster": {}}, "roster", {"of": "self"}),
    ):
        got_shape, payload, problem = _shape_of(raw)
        assert (got_shape, payload, problem) == (shape, want, ""), (raw, got_shape, payload, problem)
    # 负控：没有 name ⇒ 受控拒绝（不是"退一个空名字"）；不是对象也拒
    assert _shape_of({"retire": {}})[2], "没有 name 必须拒"
    assert _shape_of({"retire": "D1"})[2], "不是对象必须拒"
    assert _shape_of({"roster": {"of": "D7"}})[0] == "roster", "名册名要能带过去（越界由读侧判）"


def test_the_decoder_path_really_retires(tmp_path: pathlib.Path):
    """正控（端到端）：原始回复 ⇒ `loop.run()` ⇒ 退役真的落盘（走完整条路）。"""
    import json

    _st, cond, _reg, ws, me, loop, gate = _env(tmp_path)
    child = _child(cond, me, key="s1k3@decode", status="done")
    assert loop.secretary.roster_add(owner=me, role="D", task_id=child,
                                     brief="可以退的那件")["name"] == "D1"
    # 替身模型照提示词的写法回一句（这正是真机上那一句），然后收工
    gate.replies = [{"text": json.dumps({"retire": {"name": "D1"}}, ensure_ascii=False)},
                    {"text": json.dumps({"final": "退完了", "evidence": []}, ensure_ascii=False)}]
    run = loop.run("把 D1 退役", summoned_by="user", my_task_id=me)
    assert run.stop_reason == "final", run.to_dict()
    step = run.steps[0]
    assert step.shape == "retire", step.shape
    assert step.payload == {"name": "D1"}, step.payload
    assert step.result.get("action") == "retired", step.result

    from agentflow.secretary import retired_path

    assert "D1" in retired_path(ws, me).read_text(encoding="utf-8")
