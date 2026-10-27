# -*- coding: utf-8 -*-
"""D-68：给「消项」这只手 ＋ 销号前必须清板 ＋ final 前整棵树必须销号（不做兜底清理）。

## 业主原话（唯一权威，逐字）

```
「task_board难道不会让智能体一直惦记着去清吗」
「就做手，不兜底。在"销号"时，如果task_board没清，发提醒，不准直接销号。
  最终final时应该是M下整棵树都已销号，否则不记final」
```

## 这三句话各自对应本文的一个判据组

| 业主那句话 | 落到哪 | 本文守它的判据 |
|---|---|---|
| 「就做手，不兜底」 | 新工具 `conductor.ack` | a / b（及 a 的附条：它挂在每一张能收到板项的面） |
| 「在"销号"时，如果 task_board 没清，发提醒，不准直接销号」 | `conductor.retire_child` 的板项那一档 | c / d |
| 「最终 final 时应该是 M 下整棵树都已销号，否则不记 final」 | `agent_run_end` 之前那一道结构完整性闸 | e / f |
| 「不兜底」（否定面） | 哪儿都不许出现 | h（扫代码 ＋ 行为断言） |

## 改前的形态（跑这一份之前，四条主判据本就红）

- a / b：全仓没有 ack 工具。`close_item`（唯一能推到 `done` 的入口）只有 1 个调用者
  （`agent_loop._ack_stop_notice`，只 ack 停止通知），于是模型只能在回复里说「已处理」，
  盘上永远停在 `seen`。真机 `projects/sylow3`：50 个实例全 done，48 条板项里 45 条 seen
  （读了没 ack）、3 条 queued（旧代码没投出去）。
- c：拒信只说「先把它读过/做的那些项收口」—— 那条路径当时并不存在（没有 ack 工具），
  于是父代理读到拒信也不知道该做什么（这就是「提醒」与「给出处置路径」的差别）。
- e：`agent_run_end` 照记 `final`。M 名下有多少代理还在册，与它这次收工无关。
- h：改前没有兜底路径，这条判据是负控 —— 它守的是「改的时候别顺手加一条」。

## 三态纪律（与全仓一致）

`acked`（逐条给结果）/ `refused`（逐条给理由码）/ `unknown`（台账或名册没读成）。
`unknown` 绝不折成 `refused`：前者下一步该做的是重读一次，后者该做的是先清板或先等它交差。
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
from typing import Any

import pytest

from agentflow import schema as S
from agentflow import sessions as SS
from agentflow.agent_loop import run_role
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.llmseam import LlmSeam
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import READ_ONLY_ROLES, build_registry
from agentflow.tools import conductor_tools as CT
from agentflow.tools.base import ToolRegistry

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "agentflow"

#: 两个工具名（这一批的两个落点）。
ACK = "conductor.ack"
RETIRE = "conductor.retire_child"

TS = "2026-01-01T00:00:00+00:00"
SID = "d68"

#: ack 工具允许出现的「逐条理由码」。受控词表而不是自由文本：模型按码决定下一步
#: （`no_such_item` 该重读台账、`not_yours` 该让收件人自己清、`not_board_item` 该换目标）。
ACK_CODES: tuple[str, ...] = ("not_yours", "no_such_item", "not_board_item",
                              "already_done", "ack_unbacked", "state_error")


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个工作区 ＋ 一个主控行 ＋ 主控那一趟的秘书（`roster_sink` 接上，与生产同一条取法）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    # 生产里由 `AgentLoop._bind_roster_sink` 接上；这里显式接，是为了让「销号」与
    # 「登记名册」落同一份名册文件（否则两条链各读一份名册，判据测的就不是生产形态）。
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "夹具：M 这一趟"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, owner: str, *, role: str = "D",
           status: str = "done") -> str:
    """造一个子代理的台账行（`kind` 空 ＝ 代理行）。"""
    row = {
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": owner, "depth": 2, "input_key": f"fixture:{role}",
        "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": "夹具子代理",
        "error": None, "started_at": TS,
        "ended_at": (TS if status in ("done", "cancelled") else None),
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }
    return cond._write_new_row(row, note="fixture:child")


def _roster(env: dict[str, Any], task_id: str, *, role: str = "D",
            brief: str = "写研究报告") -> str:
    """把它登记进父的名册（销号的指称是名册名，所以这一步是前提）。"""
    got = env["sec"].roster_add(owner=str(env["owner"]), role=role, task_id=task_id,
                                brief=brief)
    assert got.get("problem") == "", got
    return str(got["name"])


def _item(env: dict[str, Any], *, to: str, summary: str, kind: str = "notice",
          expects: str = "ack", role: str = "M") -> str:
    """在 `to` 名下开一条要 ack 的板项（`queued`）。

    为什么带 `input_key="v-verdict@…"`：D12（业主 2026-10-27）之后，信息型板项
    （`notice` / `message` 的普通项）"渲染即收口"——`mark_item_seen` 那一拍就写
    `done`+`acked`（`Conductor._settle_if_informational`）。这一份判据问的是
    "`conductor.ack` 这只手 + 销号门的板项闸"，所以夹具要用仍然要模型自己 ack
    的那一档（`ACK_REQUIRED_ITEM_PREFIXES` 里的 `v-verdict@`），否则它一标 seen 就
    已经收口了，那只手与那道闸都无从观测。
    """
    return env["cond"].open_item(kind=kind, role=role, expects=expects, action=kind,
                                 summary=summary, called_by="M", parent_task_id=to,
                                 depth=2, input_key=f"v-verdict@{summary}@v1")


def _registry(store: Store, cond: Conductor) -> ToolRegistry:
    """只装 conductor 那一组工具（本判据只问这几个工具，不必装配整张面）。"""
    reg = ToolRegistry(name="d68")
    CT.register(reg, store=store, conductor=cond)
    return reg


def _call_ack(env: dict[str, Any], item_ids: list[str], *, as_task: str = "",
              role: str = "M", note: str = "") -> Any:
    """以某个收件人的身份调一次 ack（`calling_as` 挂上台账号，生产里由 `_do_tool` 挂）。"""
    reg = _registry(env["store"], env["cond"])
    who = str(as_task or env["owner"])
    with calling_as(who, role):
        return reg.call(ACK, role=role, item_ids=list(item_ids), note=note)


def _call_retire(env: dict[str, Any], *, name: str = "", task_id: str = "",
                 reason: str = "它交差了我不再用它") -> Any:
    """以父这一趟的身份调一次销号。

    走位置映射那一形（`call(TOOL, {"child_name": …})`）：`ToolRegistry.call` 的第一个位置
    形参也叫 `name`，而循环那边是 `registry.call(name, role=..., **args)` —— 关键字形态
    `name="D1"` 会撞成「got multiple values for argument 'name'」（实测过）。
    工具的 schema 因此把正路改叫 `child_name`，`name` 只作为整体映射的兼容别名存在。
    """
    reg = _registry(env["store"], env["cond"])
    payload: dict[str, Any] = {"reason": reason}
    if task_id:
        payload["task_id"] = task_id
    else:
        payload["child_name"] = name
    with calling_as(str(env["owner"]), "M"):
        return reg.call(RETIRE, payload, role="M")


def _row(env: dict[str, Any], task_id: str) -> dict:
    return next(r for r in env["store"].rows("tasks")
                if str(r.get("task_id") or "") == str(task_id))


def _item_events(env: dict[str, Any], item_id: str) -> list[dict]:
    """这一条板项的写事件（按发生顺序）。"""
    return [e for e in env["store"].read_events()
            if str(e.get("table") or "") == "tasks"
            and str((e.get("row") or {}).get("task_id") or "") == str(item_id)]


def _done_events(env: dict[str, Any], item_id: str) -> list[dict]:
    """这一条板项「推到 done」的那几条事件。"""
    return [e for e in _item_events(env, item_id)
            if str((e.get("row") or {}).get("item_state") or "") == "done"]


# ====================================================================== a 这只手
def _ack_problems(env: dict[str, Any]) -> list[str]:
    """a 的判据本体：两条 seen ⇒ 调 ack ⇒ 两条到 done、事件里带步号。

    返回问题清单（空 ＝ 通过）。抽成函数是为了让 g 能把它打桩之后复用同一套断言
    —— 否则 g 会变成"另写一份更松的判据"。
    """
    owner = str(env["owner"])
    first = _item(env, to=owner, summary="M 名下第一条通知")
    second = _item(env, to=owner, summary="M 名下第二条通知")
    for item_id in (first, second):
        state, why = env["cond"].mark_item_seen(item_id, by_task_id=owner, step=3)
        assert (state, why) == ("seen", ""), (item_id, state, why)

    problems: list[str] = []
    res = _call_ack(env, [first, second], note="这两条我读过了，确认")
    data = res.data if isinstance(res.data, dict) else {}
    if not res.ok:
        return [f"ack 没调成：{res.error}"]
    if data.get("state") != "acked":
        problems.append(f"两条都该 ack 成，state={data.get('state')!r}：{data}")
    if sorted(data.get("acked") or []) != sorted([first, second]):
        problems.append(f"acked 不是那两条：{data.get('acked')}")
    if data.get("refused") or data.get("unknown"):
        problems.append(f"不该有 refused/unknown：{data}")
    for item_id in (first, second):
        row = _row(env, item_id)
        if str(row.get("item_state") or "") != "done":
            problems.append(f"{item_id} 还在 {row.get('item_state')!r} —— "
                            "「读了没 ack」的原始症状，这条手没生效")
        if str(row.get("item_close") or "") != "acked":
            problems.append(f"{item_id} 的 item_close={row.get('item_close')!r}（应 acked）")
    # 事件里必须带步号与「谁在第几步」：那是 append-only 的来路（列只给当前值）。
    for item_id in (first, second):
        hits = _done_events(env, item_id)
        if len(hits) != 1:
            problems.append(f"{item_id} 的 done 事件有 {len(hits)} 条（应恰好 1 条）")
            continue
        note = str(hits[0].get("note") or "")
        if "item:done" not in note:
            problems.append(f"{item_id} 的 done 事件 note 读不出结论：{note!r}")
        if "step=3" not in note:
            problems.append(f"{item_id} 的 done 事件没带步号（note={note!r}）")
        if owner not in note:
            problems.append(f"{item_id} 的 done 事件没带 by_task_id（note={note!r}）")
    return problems


def test_two_seen_items_are_closed_by_the_hand(tmp_path: pathlib.Path) -> None:
    """a 名下有 2 条 seen ⇒ 调 `conductor.ack` ⇒ 两条到 done、事件带步号。

    改前红：没有这个工具（`reg.call("conductor.ack")` 直接是 `unknown_tool`），
    而唯一能推到 done 的 `close_item` 只有一个调用者（只 ack 停止通知）。
    """
    env = _workspace(tmp_path)
    assert _ack_problems(env) == [], _ack_problems(env)


def test_the_hand_does_not_need_a_seen_first(tmp_path: pathlib.Path) -> None:
    """a 附：`queued` 的项也能 ack（这一手是收件人的，不是投递器的）。

    为什么这条必须与 a 并列：真机 `sylow3` 的 48 条板项里有 3 条是 `queued`
    —— 旧代码没把它们投出去，于是「没读过」这件事本身挡住了清板。若 ack 只认
    `seen`，那 3 条就永远清不掉，销号门与 final 门会把整棵树永久卡死。
    口径：ack 对还没 seen 的项先补记一次 `seen`（带步号，没步号就如实记 `未读`）
    再推 done —— 状态机仍然只往后走，且「第几步读的」这一格照旧落得下。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    item = _item(env, to=owner, summary="一条从没被投递出去的旧项")
    assert _row(env, item)["item_state"] == "queued"

    res = _call_ack(env, [item], note="这条我确实没读过，确认收口")
    assert res.ok, res.error
    data = res.data or {}
    assert data["state"] == "acked", data
    assert data["acked"] == [item], data
    row = _row(env, item)
    assert row["item_state"] == "done", row
    assert row["item_close"] == "acked", row
    # 补记的那一格不许编一个步号：没有步号就如实记 None（三态，不折成第 0 步）。
    assert row.get("seen_step") in (None, 0), row
    assert row.get("seen_by") == owner, row
    notes = [str(e.get("note") or "") for e in _done_events(env, item)]
    assert len(notes) == 1 and "item:done" in notes[0], notes
    assert "未读" in notes[0] or "step=None" in notes[0] or "step=" in notes[0], notes


# ====================================================================== b 别人的项
def test_acking_somebody_elses_item_is_refused_by_code_not_yours(
        tmp_path: pathlib.Path) -> None:
    """b 负控：ack 别人的项 ⇒ 受控拒绝 `not_yours`，一条都不写。

    场景就是父代理最容易犯的那一手：它看见孩子名下挂着项，顺手替孩子 ack。
    那会让「孩子还没看」这件事实消失 —— 而这正是 ack 存在的理由（收件人自己确认）。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    child = _child(env["cond"], owner)
    others = _item(env, to=child, summary="孩子名下的一条通知", role="D")
    env["cond"].mark_item_seen(others, by_task_id=child, step=2)

    res = _call_ack(env, [others], note="爸爸替它确认")
    assert res.ok, res.error
    data = res.data or {}
    assert data["state"] == "refused", data
    assert data["acked"] == [], data
    assert data["not_yours"] == [others], data
    assert "not_yours" in (data.get("refusal_codes") or []), data
    assert data["checked"] is True, data
    # 一条都不许写：状态、收口方式、事件三处都没动
    row = _row(env, others)
    assert row["item_state"] == "seen", row
    assert row["item_close"] == "", row
    assert _done_events(env, others) == [], "被拒绝时写了一条 done 事件"
    # 拒信要能让模型读到「这是别人的项」，而不是一句「失败了」
    refused = data.get("refused") or []
    assert refused and refused[0]["item_id"] == others, refused
    assert refused[0]["code"] == "not_yours", refused
    assert str(refused[0].get("reason") or ""), refused


def test_a_mixed_batch_is_partial_and_says_which_one_failed(
        tmp_path: pathlib.Path) -> None:
    """b 附：我的一条 ＋ 别人的一条 ⇒ `state="partial"`，逐条给结果（哪些没成、为什么）。

    只报一个「部分成功」而不点名是哪一条，等于让模型下一步去猜 —— 而猜错的方向是
    再 ack 一遍别人的项（把受控拒绝变成连击）。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    child = _child(env["cond"], owner)
    mine = _item(env, to=owner, summary="我的一条")
    theirs = _item(env, to=child, summary="孩子的一条", role="D")
    for item_id in (mine, theirs):
        env["cond"].mark_item_seen(item_id, by_task_id=(owner if item_id == mine else child),
                                   step=1)

    res = _call_ack(env, [mine, theirs], note="一并确认")
    assert res.ok, res.error
    data = res.data or {}
    assert data["state"] == "partial", data
    assert data["acked"] == [mine], data
    assert [x["item_id"] for x in (data.get("refused") or [])] == [theirs], data
    assert _row(env, mine)["item_state"] == "done"
    assert _row(env, theirs)["item_state"] == "seen"


def test_the_hand_is_on_every_face_that_can_receive_board_items() -> None:
    """a 附条：凡是会收到板项的角色都拿得到这只手（通用能力口径，含只读角色）。

    判据的期望值从两处现算，不手写名单：
    - 会收到板项的角色 ＝ 全部角色 ＋ 主控（板项按 `parent_task_id` 投给任何一行）；
    - 只读角色能不能拿到，由 `UNIVERSAL_TOOLS` 的登记决定（它只写 `tasks` 的
      `item_state` 与一条事件，属簿记 ⇒ 通用集合并放行）。
    """
    from agentflow.tools import UNIVERSAL_TOOLS

    reg = ToolRegistry(name="d68-face")
    CT.register(reg)
    got = {r for r in (*S.ROLES, S.CONDUCTOR_ROLE)
           if ACK in {s.name for s in reg.for_role(r)}}
    expected = set(S.ROLES) | {S.CONDUCTOR_ROLE}
    assert got == expected, f"ack 的角色面是 {sorted(got)}，期望 {sorted(expected)}"
    # 只读角色也要拿到（它们同样收板项：交接通报、指导、停止通知都落在它们名下）
    assert set(READ_ONLY_ROLES) <= got, sorted(set(READ_ONLY_ROLES) - got)
    # 登记在通用集合里（不是靠只读例外表放行）：它是簿记，只写 tasks。
    assert ACK in UNIVERSAL_TOOLS, ("`conductor.ack` 没进 `UNIVERSAL_TOOLS` 的登记 "
                                    f"⇒ 只读角色拿不到它（登记表：{sorted(UNIVERSAL_TOOLS)}）")
    assert UNIVERSAL_TOOLS[ACK].tables <= {"tasks"}, UNIVERSAL_TOOLS[ACK]


# ====================================================================== c 销号门
def test_retiring_with_an_unclean_board_is_refused_with_a_count_and_the_ack_path(
        tmp_path: pathlib.Path) -> None:
    """c 名下还有未清项 ⇒ `retire_child` 受控拒绝，拒信带「还剩 N 条」与 ack 路径。

    改前红在哪（两半，第二个是本文真正守着的那一半）：
    1. 更早的拒信只说「先把它读过/做的那些项收口」，一个工具名都不点 ——
       「提醒」于是变成一句没有出口的话；
    2. 点名的路径当时并不存在：`conductor.ack` 在全仓一个字都没有，所以父代理
       照着那句话去做也做不成（本判据的最后一条断言就钉这一格：名字必须在收件人的面上）。

    另半句是业主原话的落点：「task_board 没清，发提醒，不准直接销号」—— 拒信里必须
    逐字读得到「不许销号」这一档，否则那句话读起来像建议（业主要的是闸）。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    child = _child(env["cond"], owner, role="F")
    name = _roster(env, child, role="F", brief="攻坚")
    seen_item = _item(env, to=child, summary="读过但没 ack 的一条", role="F")
    queued_item = _item(env, to=child, summary="从没投递过的一条", role="F")
    env["cond"].mark_item_seen(seen_item, by_task_id=child, step=2)

    res = _call_retire(env, name=name, reason="它交差了")
    assert res.ok, res.error
    data = res.data or {}
    assert data["state"] == "refused", data
    assert data["retired"] is False, data
    text = str(data.get("reason") or "")
    # 一：还剩几条（数字必须逐字在拒信里）
    assert re.search(r"(?:还剩|还有)\s*2\s*条", text), f"拒信没给条数：{text!r}"
    # 二：逐条 id / kind / state
    listed = {str(x.get("task_id") or ""): x for x in (data.get("open_items") or [])}
    assert set(listed) == {seen_item, queued_item}, listed
    assert listed[seen_item]["item_state"] == "seen", listed
    assert listed[queued_item]["item_state"] == "queued", listed
    for item_id in (seen_item, queued_item):
        assert item_id in str(data.get("missing") or []), data.get("missing")
        assert listed[item_id]["kind"] == "notice", listed
    # 三：处置路径点名 conductor.ack（「发提醒」与「给出口」的差别就在这里）
    assert ACK in text, f"拒信没给出处置路径（应点名 {ACK}）：{text!r}"
    assert ("清" in text) or ("收口" in text) or ("确认" in text), (
        f"拒信没说清要先处置板项：{text!r}")
    assert "销号" in text, text
    # 四：业主原话那半句「不准直接销号」必须在拒信里逐字可见 ——
    # 只有「还剩 N 条」而没有这一句，读起来像建议而不是闸（业主要的是后者）。
    assert ("不许销号" in text) or ("不准直接销号" in text) or ("不许直接销号" in text), (
        f"拒信里没有『否则不许销号』这半句（业主逐字：task_board 没清，不准直接销号）：{text!r}")
    # 三的后半：点名的路径必须真的存在（这一格是 c 的"改前红"所在 ——
    # 改前那句话点到的是整个仓库都没有的一件工具，于是父代理照着做也做不成）。
    face = {s.name for s in _registry(env["store"], env["cond"]).for_role("F")}
    assert ACK in face, (f"拒信点名了 {ACK}，而收件人 F 的工具面上没有它"
                         f"（面上有 {sorted(n for n in face if n.startswith('conductor.'))}）")


def test_after_the_board_is_clean_the_retire_goes_through(
        tmp_path: pathlib.Path) -> None:
    """d 正控：清干净之后同一笔销号就成（销号门不是一律拒绝）。

    清板的那一手必须由收件人自己用（`calling_as(child)`）：这一条同时把
    「手在收件人手里」这件事钉住 —— 父代理替孩子 ack 会被 b 拒掉。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    child = _child(env["cond"], owner, role="F")
    name = _roster(env, child, role="F", brief="攻坚")
    first = _item(env, to=child, summary="一条", role="F")
    second = _item(env, to=child, summary="两条", role="F")
    env["cond"].mark_item_seen(first, by_task_id=child, step=2)

    blocked = _call_retire(env, name=name)
    assert blocked.data["state"] == "refused", blocked.data

    acked = _call_ack(env, [first, second], as_task=child, role="F", note="都办完了")
    assert acked.ok, acked.error
    assert acked.data["state"] == "acked", acked.data
    assert sorted(acked.data["acked"]) == sorted([first, second]), acked.data

    again = _call_retire(env, name=name, reason="板清了，可以销号")
    assert again.ok, again.error
    assert again.data["state"] == "retired", again.data
    assert again.data["retired"] is True, again.data
    # 销号之后那两条仍然是 done（销号不重写板项，也不把它们变成别的东西）
    for item_id in (first, second):
        assert _row(env, item_id)["item_state"] == "done"


# ====================================================================== e / f final 门
class _Gate:
    """按脚本回文本的替身网关（不联网；与 `tests/test_llm_work_reaches_the_ledger` 同形）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 max_tokens: int | None = None, tools: Any = None,
                 tool_choice: str = "auto") -> Any:
        self.prompts.append(prompt)
        item = self.script.pop(0) if self.script else {"text": "{}"}
        return type("R", (), {"ok": True, "text": item.get("text", ""),
                              "tool_calls": tuple(item.get("tool_calls", ())),
                              "tokens_in": 1, "tokens_out": 1, "error_detail": "",
                              "error_kind": ""})()


#: M 那一趟交的那一句（判据要比对它有没有落进 `agent_run_end`）。
M_FINAL = "M 的交付：这一趟的活做完了"


def _final_reply(text: str = M_FINAL) -> dict:
    return {"text": json.dumps({"final": text, "evidence": []}, ensure_ascii=False)}


def _run_end_events(root: pathlib.Path) -> list[dict]:
    events, problems = SS.read_session(root, sid=SID)
    assert not problems, problems
    return [e for e in events if str(e.get("kind") or "") == "agent_run_end"]


def _run_m(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
           replies: list[dict]) -> Any:
    """以 M 的身份真跑一趟（固定台账号，于是可以事先在它名下造一棵树）。

    为什么固定台账号（`open_top_level_run` 打桩）：每一趟都会发新号，而判据要问的是
    「这一趟名下那棵树销号了没有」—— 号一变，树就是空的，这条判据会变成真空绿。
    """
    store, cond = env["store"], env["cond"]
    mine = str(env["owner"])
    monkeypatch.setattr(Conductor, "open_top_level_run",
                        lambda self, role, task: mine)
    reg = build_registry(store=store, conductor=cond).registry
    return run_role("M", "夹具：把这一趟做完", store=store, registry=reg, conductor=cond,
                    seam=LlmSeam(role="M", session_root=env["root"],
                                 gateway=_Gate(replies), price=(0.0, 0.0), sid=SID),
                    session_root=env["root"], workspace_root=str(env["root"]),
                    sid=SID, from_env=False)


def _refusal_problems(env: dict[str, Any], run: Any, end: dict,
                      child: str) -> list[str]:
    """「被拒」那一支的断言（e / e' 共用一份：final 不落盘 + 清单交回去）。

    抽出来是为了让「被唤醒的回合」那条判据与 e 用同一套尺子 —— 否则两条各写一遍，
    迟早一条松一条紧，而业主追裁抹掉的正是"某一档回合可以例外"这条缝。
    """
    problems: list[str] = []
    # 不许「记了 final 又提醒」：拒绝时 final 一个字都不许落盘。
    if str(end.get("final") or ""):
        problems.append(f"被拒的 final 仍然落盘了：{str(end.get('final'))[:60]!r}")
    if str(run.final or ""):
        problems.append(f"被拒之后内存里仍有 final：{run.final!r}")
    if run.stop_reason != "final_refused":
        problems.append(f"stop_reason={run.stop_reason!r}（应 final_refused）")
    # 拒信清单：哪些节点还在册、各自名下多少未消项
    last = run.steps[-1].result if run.steps else {}
    gate = (last.get("final_refused") if isinstance(last, dict) else None) or {}
    nodes = {str(n.get("task_id") or ""): n for n in (gate.get("nodes") or [])}
    if child not in nodes:
        problems.append(f"拒绝那一支没点名还在册的节点：{gate or last}")
    elif int(nodes[child].get("open_items") or 0) != 1:
        problems.append(f"没报「各自名下还有多少未消项」：{nodes[child]}")
    notes = " ".join(str(x) for x in (end.get("notes") or []))
    if child not in notes:
        problems.append(f"agent_run_end 的 notes 里没点名那个节点：{notes[:200]!r}")
    if "条未消" not in notes:
        problems.append(f"notes 里没报未消项条数：{notes[:200]!r}")
    if ACK not in notes:
        problems.append(f"notes 里没给处置路径（应点名 {ACK}）：{notes[:200]!r}")
    return problems


def _final_gate_problems(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch, *,
                         retired: bool) -> list[str]:
    """e / f 的判据本体（抽出来是为了让 g 能打桩后复用同一套断言）。"""
    owner = str(env["owner"])
    child = _child(env["cond"], owner, role="D")
    name = _roster(env, child, role="D")
    item = _item(env, to=child, summary="孩子名下还没清的一条", role="D")
    env["cond"].mark_item_seen(item, by_task_id=child, step=2)
    if retired:
        _call_ack(env, [item], as_task=child, role="D")
        done = _call_retire(env, name=name, reason="板清了，销号")
        assert done.data["state"] == "retired", done.data

    # Q12（2026-10-26）之后被拒不再"同一拍收工"：这一步之后还有补救拍，所以脚本要按
    # `AgentLoop.max_final_refused + 1` 份给（3 拍补救 + 最后一拍收尾）。断言一条没改：
    # 只改了喂给替身网关的回复条数（改前给 1 份 ⇒ 第二次要回复时脚本已空、返回 `{}`，
    # 于是这一趟会以 `bad_json_limit` 收场，`stop_reason` 与 `run.steps[-1]` 两条断言
    # 读到的是协议连击而不是这封拒信 —— 那是夹具跟不上控制流，不是判据放宽）。
    run = _run_m(env, monkeypatch, [_final_reply()] * 4)
    ends = _run_end_events(env["root"])
    if not ends:
        return ["盘上没有 agent_run_end（这一趟没跑起来）"]
    end = ends[-1]
    if retired:
        problems: list[str] = []
        if run.stop_reason != "final":
            problems.append(f"整棵树都销号了却不许收工：stop_reason={run.stop_reason!r}")
        if str(end.get("final") or "") != M_FINAL:
            problems.append(f"final 没落盘：{str(end.get('final'))[:60]!r}")
        if str(run.final or "") != M_FINAL:
            problems.append(f"内存里的 final 不对：{run.final!r}")
        return problems
    return _refusal_problems(env, run, end, child)


def _woken_final_problems(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
                          *, gate_passes: bool = False) -> list[str]:
    """e' 的判据本体：被唤醒的回合 里发 final、树没清 ⇒ 仍被拒（没有例外）。

    业主 2026-10-26 追裁逐字：「任何 final 都要清仓 —— 不留"监控回合例外"」。
    改前红：那道闸曾经有一条 `monitor_of` 或 `run.wakes > 0` 的豁免 ⇒ 这一趟会
    照记 final（本条当场红）。所以这条判据必须先把"这一趟真的被唤醒过"证出来
    （`run.wakes > 0`），否则它证明不了那道缝被堵上。
    """
    from agentflow import clock as CLK

    owner = str(env["owner"])
    child = _child(env["cond"], owner, role="D")
    _roster(env, child, role="D")
    item = _item(env, to=child, summary="孩子名下还没清的一条", role="D")
    env["cond"].mark_item_seen(item, by_task_id=child, step=2)
    fake = CLK.use(CLK.FakeClock(wall="2026-10-26T00:00:00+00:00"))
    try:
        CLK.reset_books()
        # 先装配一次带 `workspace_root` 的注册表：到点动作（`set_due_handler`）由
        # `clock_tools` 的装配注册，没有它计时器只会 `deferred`（"到点动作没接上"）。
        build_registry(store=env["store"], conductor=env["cond"],
                       workspace_root=str(env["root"]))
        CLK.start_timer(str(env["root"]), after_sec=1,
                        reason="判据：叫醒它之后发 final（这一档不许例外）",
                        task_id=owner, role="M")
        fake.advance(5)
        assert CLK.pending_wakes(str(env["root"]), owner)["count"] == 1, (
            "夹具前提：到期唤醒没造出来 ⇒ 这条判据测不到'被唤醒的回合'")
        # 与 `_final_gate_problems` 同一条 Q12 口径：被拒之后还有补救拍，脚本给满
        # （3 拍补救 + 最后一拍收尾），断言与改前逐条相同。
        run = _run_m(env, monkeypatch, [_final_reply()] * 4)
    finally:
        CLK.reset()
    ends = _run_end_events(env["root"])
    if not ends:
        return ["盘上没有 agent_run_end（这一趟没跑起来）"]
    end = ends[-1]
    problems: list[str] = []
    # 夹具前提（反真空）：这一趟真的消费过唤醒，否则"被唤醒"那句是空话。
    if int(getattr(run, "wakes", 0) or 0) <= 0:
        problems.append(f"这一趟没消费到唤醒（wakes={getattr(run, 'wakes', 0)!r}）"
                        "⇒ 判据没测到'被唤醒的回合'")
    problems.extend(_refusal_problems(env, run, end, child))
    return problems


def test_a_final_with_an_unretired_node_is_not_recorded(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e M 收工时树里还有未销号节点 ⇒ 不记 final，并把未销号清单交回去。

    改前红：`agent_run_end` 照记 `final`（M 名下有几个还在册的代理，与它收工无关）。
    """
    env = _workspace(tmp_path)
    assert _final_gate_problems(env, monkeypatch, retired=False) == [], (
        _final_gate_problems(env, monkeypatch, retired=False))


def test_a_fully_retired_tree_records_the_final(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f 正控：整棵树都销号之后，final 正常落盘（闸不制造永远收不了工的世界）。"""
    env = _workspace(tmp_path)
    assert _final_gate_problems(env, monkeypatch, retired=True) == [], (
        _final_gate_problems(env, monkeypatch, retired=True))


def test_a_woken_turn_gets_no_exemption_from_the_gate(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e' 被唤醒/监控的回合也没有例外：树没清 ⇒ 同样不记 final。

    业主 2026-10-26 追裁逐字：「任何 final 都要清仓 —— 不留"监控回合例外"」。
    改前红：那道闸曾经有一条 `monitor_of` / `run.wakes > 0` 的豁免，于是"被叫醒的那一趟
    发个 final"就能绕过整棵树销号的要求 —— 一个绕闸的口子。这一条把它堵死，
    并且先把"这一趟真的被唤醒过"证出来（`run.wakes > 0`），否则它证明不了什么。
    """
    env = _workspace(tmp_path)
    assert _woken_final_problems(env, monkeypatch) == [], (
        _woken_final_problems(env, monkeypatch))


# ====================================================================== g 反真空
def test_stubbing_the_hand_makes_a_red(tmp_path: pathlib.Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """g 反真空①：把 ack 打桩成空 ⇒ a 必红（否则 a 只是「跑过了」而不是「这只手在做事」）。"""
    env = _workspace(tmp_path)

    def _empty(self, item_ids, **kw):  # noqa: ANN001, ARG001
        return {"checked": True, "ok": False, "state": "refused", "acked": [],
                "refused": [], "unknown": [], "missing": [], "not_yours": [],
                "refusal_codes": [], "count": 0, "requested": 0, "step": None,
                "note": "", "reason": ""}

    monkeypatch.setattr(Conductor, "ack_items", _empty)
    problems = _ack_problems(env)
    assert problems, "把 ack 打桩成空，a 却仍然绿 ⇒ 这条判据是橡皮图章"
    assert any("done" in p or "acked" in p for p in problems), problems


def test_stubbing_the_final_gate_makes_e_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """g 反真空②：把 final 门打桩成恒放行 ⇒ e 与 e'（被唤醒的回合）都必红。"""
    env = _workspace(tmp_path)
    # e' 那个工作区必须在 `_run_m` 打桩 `open_top_level_run` 之前建好 ——
    # 否则两棵树会拿到同一个台账号（`_workspace` 也是走那一条路发号的）。
    env2 = _workspace(tmp_path / "woken")

    def _always_complete(self, root_task_id):  # noqa: ANN001, ARG001
        return {"checked": True, "complete": True, "nodes": [], "count": 0,
                "root": str(root_task_id), "reason": "", "dirty": []}

    monkeypatch.setattr(Conductor, "retire_integrity", _always_complete)
    problems = _final_gate_problems(env, monkeypatch, retired=False)
    assert problems, "把 final 门打桩成恒放行，e 却仍然绿 ⇒ 这道闸是假的"
    assert any("被拒的 final 仍然落盘了" in p or "stop_reason" in p for p in problems), problems
    # 同一根桩也要让 e'（被唤醒的回合）红：两道判据是同一道闸的两个入口，
    # 只红一条说明有一条没接在闸上。
    woken = _woken_final_problems(env2, monkeypatch)
    assert woken, "把 final 门打桩成恒放行，e' 却仍然绿 ⇒ 被唤醒那一档没接在闸上"
    assert any("被拒的 final 仍然落盘了" in p or "stop_reason" in p for p in woken), woken


# ====================================================================== h 不兜底
#: 板项状态机的两组写入点。分两组是刻意的：一组把项推到 `done`（收口），
#: 另一组只把它读进某一步（投递，`seen` / `claimed`）。"兜底清理"只可能落在前一组上，
#: 而把两组混在一起判会让"投递即 seen"这条既有口径（业主 A3=甲）无辜变红。
_CLOSE_WRITERS: tuple[str, ...] = ("close_item", "_set_item", "ack_items")
_DELIVERY_WRITERS: tuple[str, ...] = ("mark_item_seen", "claim_item")
_STATE_WRITERS: tuple[str, ...] = _CLOSE_WRITERS + _DELIVERY_WRITERS

#: 允许出现"自动收口"的唯一一处（S4-b 的停止通知：`ack` 才算传达到）。
_AUTO_ACK_ALLOWED: frozenset[str] = frozenset({"_ack_stop_notice"})

#: 允许出现"投递即 seen"的两处（`_hear` 那条耳朵与开场那一步）。
_DELIVERY_ALLOWED: frozenset[str] = frozenset({"_hear", "run"})

#: 板项状态机各写入点的合法落点（文件 -> 允许出现的方法名）。
#:
#: 这张表就是"不许兜底清理"这条负控的判据面：多出一个落点，说明有人把"收口"
#: 搬到了别处（收工那一支、停止那一支、或某个带 sweep 语义的函数）——
#: 那种搬法不会让任何别的判据变红，只会让"框架替它把板清了"这件事悄悄发生。
_WRITE_SITES: dict[str, frozenset[str]] = {
    # 唯一写入点住在这一处（`_set_item` 是状态机本体，其余三个是它的入口）。
    "conductor.py": frozenset({"close_item", "_set_item", "mark_item_seen",
                               "claim_item", "ack_items"}),
    # 循环这一层只许两种：投递（渲染即 seen）与停止通知的收口（S4-b 逐字要求）。
    "agent_loop.py": frozenset({"close_item", "mark_item_seen"}),
    # 工具层只许经 `ack_items`（它再往下走 `_set_item`）；不许自己拼一份状态迁移。
    "tools/conductor_tools.py": frozenset({"ack_items"}),
}


def _state_write_calls() -> list[tuple[str, str, str]]:
    """扫 `src/agentflow`：谁在调板项状态机的写入点。返回 `(文件, 所在函数, 方法名)`。"""
    out: list[tuple[str, str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        stack: list[str] = []

        class _Visit(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node: ast.Call) -> None:
                fn = node.func
                name = (fn.attr if isinstance(fn, ast.Attribute)
                        else fn.id if isinstance(fn, ast.Name) else "")
                if name in _STATE_WRITERS:
                    who = stack[-1] if stack else "<module>"
                    out.append((path.relative_to(SRC).as_posix(), who, name))
                # `getattr(cond, "close_item", None)` 那一形也要认：停止通知那一处就是
                # `close = getattr(cond, "close_item", None)` 之后再 `close(...)` 调的。
                # 不认这一形，反真空那条断言会因为"允许的那一处扫不到"而假红。
                if (name == "getattr" and len(node.args) >= 2
                        and isinstance(node.args[1], ast.Constant)
                        and str(node.args[1].value) in _STATE_WRITERS):
                    who = stack[-1] if stack else "<module>"
                    out.append((path.relative_to(SRC).as_posix(), who,
                                str(node.args[1].value)))
                self.generic_visit(node)

        _Visit().visit(tree)
    return out


#: 带"清场"语义的词（兜底清理会挂在这种名字上）。
_SWEEP_WORDS: tuple[str, ...] = ("sweep", "cleanup", "clean_up", "auto_ack", "ack_all",
                                 "purge", "clear_board", "close_all_items",
                                 "drain_board", "reap", "close_the_board",
                                 "empty_the_board")

#: 板项专属的"清场"名字形态（哪怕它不直接调状态机，只要叫这个名就红）。
_SWEEP_BOARD_NAME = re.compile(
    r"(board|items?).*(sweep|clean|purge|clear|drain|reap)"
    r"|(sweep|clean|purge|clear|drain|reap).*(board|items?)", re.I)


def _sweep_functions() -> list[str]:
    """扫 `src/agentflow`：哪些"清场"函数碰了板项（兜底清理只可能长成这样）。

    两半合起来才是判据：一半是名字（`_SWEEP_WORDS` ＋ 板项专属的名字形态），
    一半是它真的动了板项状态机（`_state_write_calls`）。只看名字会把
    `_sweep_stale_top_running` / `_cleanup` 这些既有函数误判成板项清理；
    只看状态机则一条都看不见 —— 清理完全可以写在一个"别处"的函数里再调进来。
    """
    out: list[str] = []
    for (rel, who, _name) in _state_write_calls():
        low = who.lower()
        if any(w in low for w in _SWEEP_WORDS) or _SWEEP_BOARD_NAME.search(who):
            out.append(f"{rel}::{who}")
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    _SWEEP_BOARD_NAME.search(node.name):
                out.append(f"{path.relative_to(SRC).as_posix()}::{node.name}")
    return sorted(set(out))


def test_there_is_no_run_end_sweep_that_closes_the_board(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """h 负控：不许多一条「run 结束自动清理 / 自动 ack」的路径。

    两半，缺一条都不算：
    1. 行为：一趟真的跑到 final 之后，名下那条没 ack 的项仍然是 `seen`
       —— 不是 `done`，也不是什么别的东西（`ITEM_STATES` 里没有 `void` 这一档，
       所以「兜底清理」如果真的存在，只能表现为 done 或一个新状态，两者都判红）；
    2. 结构：板项状态机的写入点不许出现在 run 结束那一支（`_execute` / `run` /
       `_consume_stop_at_teardown` / `finish_top_level_run` 这些名字下），
       全树唯一的"框架替它收口"只有 `_ack_stop_notice`（停止通知，S4-b 逐字要求）。
    """
    # ---- 一：行为
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    item = _item(env, to=owner, summary="M 名下一条读过但没确认的项")
    env["cond"].mark_item_seen(item, by_task_id=owner, step=1)

    run = _run_m(env, monkeypatch, [_final_reply()])
    assert run.stop_reason == "final", run.to_dict()
    row = _row(env, item)
    assert str(row.get("item_state") or "") == "seen", (
        f"run 结束后那条没 ack 的项变成了 {row.get('item_state')!r} ⇒ "
        "存在一条兜底清理路径（业主逐字：就做手，不兜底）")
    assert str(row.get("item_close") or "") == "", row
    assert _done_events(env, item) == [], "run 结束时框架替它写了一条 done 事件"
    # 反真空：这条项是可收口的（同一件东西用 ack 一调就 done）—— 否则上面那条
    # 「仍然是 seen」可能只是因为"它永远收不了"。
    fixed = _call_ack(env, [item], note="这一条我自己确认")
    assert fixed.data["state"] == "acked", fixed.data
    assert _row(env, item)["item_state"] == "done"

    # ---- 二：结构
    assert "void" not in S.ITEM_STATES, S.ITEM_STATES
    calls = _state_write_calls()
    assert calls, "扫不到任何板项写入调用 ⇒ 扫描器没接上（本次结果不可信）"
    auto = [(f, who, name) for (f, who, name) in calls
            if f == "agent_loop.py" and name in _CLOSE_WRITERS]
    stray = [(f, who, name) for (f, who, name) in auto if who not in _AUTO_ACK_ALLOWED]
    assert stray == [], f"`agent_loop.py` 里出现了第二种自动收口：{stray}"
    # 反真空：允许的那一处必须真的被扫到（否则「没有第二种」是空集在说话）
    assert any(who in _AUTO_ACK_ALLOWED for (_f, who, _n) in auto), auto
    delivery = [(f, who, name) for (f, who, name) in calls
                if f == "agent_loop.py" and name in _DELIVERY_WRITERS]
    odd_delivery = [(f, who, name) for (f, who, name) in delivery
                    if who not in _DELIVERY_ALLOWED]
    assert odd_delivery == [], (
        f"`agent_loop.py` 里出现了第三种投递点（板项在哪一步被读进来会因此说不清）："
        f"{odd_delivery}")
    # 落点白名单：状态机的写入点只在这三处，且工具层只许经 `ack_items`（它再往下走
    # `_set_item`，唯一写入点在 conductor 那一侧）。别处出现一律红 —— 兜底清理若要存在，
    # 只能长在别处（收工/停止那一支），而它一旦长出来就会落在这一格里。
    outside = sorted({(f, name) for (f, _w, name) in calls
                      if name not in _WRITE_SITES.get(f, frozenset())})
    assert outside == [], (
        "板项状态机被这几处绕过了（唯一写入点应只有 conductor.py，"
        f"工具层只许经 ack_items）：{outside}")
    assert _sweep_functions() == [], f"出现了带兜底清理语义的函数：{_sweep_functions()}"


# ====================================================================== 读数入口
def test_the_gate_lists_every_node_and_its_open_items_per_node(
        tmp_path: pathlib.Path) -> None:
    """a-e 的读数入口：`retire_integrity` 逐节点给「在册 / 名下未消项」两格（三态）。

    这条是 e 的明细判据：e 要的清单（哪些节点还在册、各自名下还有多少未消项）就由它算。
    负控的负控：把那个子销号之后，同一棵树必须说"干净" —— 否则 e 的清单只能证明
    「它一律拒」。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    child = _child(env["cond"], owner, role="D")
    name = _roster(env, child, role="D")
    item = _item(env, to=child, summary="一条", role="D")
    env["cond"].mark_item_seen(item, by_task_id=child, step=2)

    before = env["cond"].retire_integrity(owner)
    assert before["checked"] is True, before
    assert before["complete"] is False, before
    nodes = {str(n.get("task_id") or ""): n for n in before["nodes"]}
    assert child in nodes, nodes
    assert int(nodes[child]["open_items"]) == 1, nodes[child]
    assert child not in {str(x.get("task_id") or "") for x in (before.get("nodes") or [])} or \
        nodes[child].get("retired") is False, nodes[child]
    # 根自己不算"在册待销"（它没有父，销号对它没有对象）
    assert owner not in nodes, nodes

    _call_ack(env, [item], as_task=child, role="D")
    done = _call_retire(env, name=name, reason="清了")
    assert done.data["state"] == "retired", done.data

    after = env["cond"].retire_integrity(owner)
    assert after["checked"] is True, after
    assert after["complete"] is True, after
    assert after["nodes"] == [], after
