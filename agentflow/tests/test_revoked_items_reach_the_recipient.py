# -*- coding: utf-8 -*-
"""撤销通知必须"真能提醒到"：最近被撤销的项要进收件人那一侧的提示词。

## 补的是哪个缺口（上一笔自己报的取舍）

业主要求（逐字）：

    3.父代理修改子代理板项后是否提醒子代理板项修改且提醒是自动的
    → 自动提醒，且要真能提醒到

上一笔把「撤销时自动投一条通知」落成了行：

    kind=notice · expects="" · item_state=done · item_close=expired ·
    called_by=system · input_key=revoke-notice@<被撤项>

但那一行是 `done` 的记录，`open_items_of` 按定义只数未消项 ⇒ 它不在收件人的
板面摘要/提示词里：子代理实际看不见"我名下那条被撤了"，只能自己去翻台账才发现
—— 等于没通知。这一笔把"最近被撤销的项"另开一格送到收件人那一侧。

## 为什么读口挂在 `mailbox_digest`（而不是 `board_view` / `_board_cell` / `board_digest`）

- `conductor.board`（`board_view`）与 `conductor.patrol`（`_board_cell`）的 `roles`
  都是 `("M",)`：收件人（子代理）根本拿不到这两件工具。把这一格放过去等于
  "父亲看得见、本人看不见"，正是这一笔要补的那个缺口；
- `board_digest` 是 `_hear` 的板摘要、也是开场读数，它的渲染被"这一拍有新板项"
  门着（`if board_ids`）—— 名下项全被撤光时它一个字都不会出现，同样漏；
- 收件人那一侧唯一真能读到的地方是 `mailbox_digest`：每一拍 `ask_step` 之前由
  `_deliver_mailbox` 投进去的增量（D-52 的唯一投递点）。

## 这一份钉什么

| 格 | 用例 |
|---|---|
| a | `test_a_the_revoked_item_is_visible_in_the_recipients_mailbox_prompt` |
| a · 真提示词 | `test_a2_a_real_loop_puts_the_revoked_line_into_the_models_prompt` |
| b | `test_b_the_four_open_readings_are_untouched` |
| c | `test_c_without_a_revocation_the_cell_is_empty_and_the_prompt_stays_quiet` |
| d | `test_d_removing_the_revoked_section_turns_the_first_criterion_red`（反真空） |

## 硬约束（业主 2026-11-06 的第二笔）

`open_items_of` / `board_view` 的 `board_open_count` / patrol 的
`child_open_count` / `board_digest` 的既有读数一个都不许变：新格另开，只由
`Conductor.revoked_recent_of` 与 `mailbox_digest` 渲染。b 条把这四个读数在
撤销前后逐条钉住。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

from agentflow import agent_loop as AL
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import conductor_tools as CT

SID = "revoked-reaches-recipient"


# ---------------------------------------------------------------- 夹具


def _workspace(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Conductor]:
    """M（根）→ D1（父）→ F1 / F2（兄弟）；F1 → G1（孙代）。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return ws, Conductor(st, policy=None, backend=LocalBackend({}))


def _agent(box: Conductor, *, role: str, parent: str | None, detail: str,
           status: str = "running") -> str:
    ended = None if status in ("pending", "running") else "2026-11-06T08:00:00+08:00"
    return box._write_new_row({
        "role": role, "action": "run", "called_by": (parent and "M") or "user",
        "parent_task_id": parent, "depth": (1 if parent is None else 2),
        "input_key": f"test:{role}:{detail}", "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": detail, "error": None,
        "started_at": "2026-11-06T08:00:00+08:00", "ended_at": ended,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        "kind": "", "expects": "", "item_state": "", "item_close": "",
        "seen_by": "", "seen_step": None, "keep_alive": False,
    }, note=f"test:agent:{role}")


def _item(box: Conductor, *, owner: str, role: str, expects: str,
          kind: str, summary: str) -> str:
    return box.open_item(kind=kind, role=role, expects=expects, action=kind,
                         summary=summary, called_by="test", parent_task_id=owner,
                         depth=2, input_key=f"test:{kind}:{owner}:{summary}")


def _hierarchy(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Conductor,
                                                dict[str, str]]:
    ws, box = _workspace(tmp_path)
    ids = {"M": _agent(box, role="M", parent=None, detail="顶趟"),
           "D1": "", "F1": "", "F2": "", "G1": ""}
    ids["D1"] = _agent(box, role="D", parent=ids["M"], detail="D1")
    ids["F1"] = _agent(box, role="F", parent=ids["D1"], detail="F1")
    ids["F2"] = _agent(box, role="F", parent=ids["D1"], detail="F2")
    ids["G1"] = _agent(box, role="G", parent=ids["F1"], detail="G1")
    return ws, box, ids


def _mailbox(box: Conductor, ws: pathlib.Path, who: str, *,
             rendered: tuple[str, ...] = ()) -> dict[str, Any]:
    """收件人那一侧的增量读数（`_deliver_mailbox` 每一拍调的就是它）。"""
    return AL.mailbox_digest(box, ws, "F", my_task_id=who, sid=SID,
                             rendered=list(rendered))


def _revoke(box: Conductor, ids: Mapping[str, str], *items: str) -> dict[str, Any]:
    return box.void_items(list(items), by_task_id=ids["D1"],
                          why="方向已砍：这条不再需要做", revoke=True)


def _a_problems(tmp_path: pathlib.Path) -> list[str]:
    """(a) 的判据本体：撤销之后，收件人那一侧的提示词里真能读到那一条。"""
    problems: list[str] = []
    ws, box, ids = _hierarchy(tmp_path)
    item = _item(box, owner=ids["F1"], role="F", expects="work",
                 kind="delegation", summary="一条待撤的活")

    before = _mailbox(box, ws, ids["F1"])
    if before.get("revoked_recent") != [] or before.get("revoked_ids") != []:
        problems.append(f"还没撤过，这一格却不是空表：{before.get('revoked_recent')!r}")
    if "最近被撤销" in str(before.get("text") or ""):
        problems.append(f"还没撤过，提示词里却有一段「最近被撤销」：{before.get('text')!r}")

    # 最常见的情形：这一条作为未消项已经被渲染过（渲染集里已经有它）——
    # 撤销提醒不许因为这个渲染集被滤掉（键必须另起一个空间）。
    assert box.mark_item_seen(item, by_task_id=ids["F1"], step=1)[0] == "seen"

    got = _revoke(box, ids, item)
    if got.get("voided") != [item]:
        problems.append(f"撤销本身没成：{got!r}")
        return problems
    trace = next(dict(t) for t in (got.get("traces") or ())
                 if str(t.get("item_id")) == str(item))

    after = _mailbox(box, ws, ids["F1"], rendered=(item,))
    cell = list(after.get("revoked_recent") or ())
    if len(cell) != 1:
        problems.append(f"收件人那一侧的 revoked_recent 应当恰好多一条，实测 {cell!r}")
        return problems
    entry = dict(cell[0])
    want = {"item_id": item, "by": ids["D1"],
            "reason": "方向已砍：这条不再需要做",
            "at": str(trace.get("at") or ""),
            "summary": "一条待撤的活"}
    if entry != want:
        problems.append(f"revoked_recent 那一格不是约定的五格：{entry!r} ≠ {want!r}")

    text = str(after.get("text") or "")
    if "【最近被撤销的项】" not in text:
        problems.append(f"提示词里没有「最近被撤销的项」那一段：{text!r}")
    for needle in (item, ids["D1"], "方向已砍", "你不需要再处理它", "一条待撤的活"):
        if needle not in text:
            problems.append(f"提示词那一段里没念到 {needle!r}：{text!r}")
    # 它不欠任何动作：这一条不许冒充"还在等你处理"的板项
    if item in str(before.get("text") or "") and item in after.get("item_ids", []):
        problems.append("被撤项又被当成新板项投了一次（它会冒充待办）")
    return problems


def test_a_the_revoked_item_is_visible_in_the_recipients_mailbox_prompt(
        tmp_path: pathlib.Path) -> None:
    """a：撤销之后，收件人那一侧的增量里真能读到"我名下那条被撤了"。"""
    assert _a_problems(tmp_path) == [], _a_problems(tmp_path)


def test_a2_a_real_loop_puts_the_revoked_line_into_the_models_prompt(
        tmp_path: pathlib.Path) -> None:
    """a · 真提示词：把一段真循环跑起来，模型第一条提示词里就有那一句。"""
    ws, box, ids = _hierarchy(tmp_path)
    item = _item(box, owner=ids["F1"], role="F", expects="work",
                 kind="delegation", summary="一条不再需要做的活")
    assert _revoke(box, ids, item).get("voided") == [item]
    marker = f"[{item}] 已被 {ids['D1']} 撤销"

    gate = _Gate([json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)])
    reg = build_registry(store=box.store, conductor=box).registry
    loop = AgentLoop(role="F", session_root=ws, registry=reg, conductor=box,
                     seam=LlmSeam(role="F", session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=box.store, sid=SID, max_steps=2)
    loop.run("把这一趟做完", summoned_by=ids["D1"], my_task_id=ids["F1"], depth=2)
    assert gate.prompts, "这一趟一次模型都没问"
    assert marker in gate.prompts[0], (
        "撤销提醒没有进模型的提示词 ⇒ 收件人还是只能自己翻台账", gate.prompts[0][-1200:])
    assert "【最近被撤销的项】" in gate.prompts[0], gate.prompts[0][-1200:]


class _Gate:
    """照剧本回答的替身（记录 user 提示词，不联网）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(str(prompt))
        self.systems.append(system or "")
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


# ---------------------------------------------------------------- b —— 四个 open 读数


def _readings(box: Conductor, ids: Mapping[str, str], who: str) -> dict[str, Any]:
    """四个既有 open 读数（一个都不许被这一格改动）。"""
    text, shown, problems = AL.board_digest(box, my_task_id=who)
    assert not problems, problems
    return {
        "open_items_of": [str(r.get("task_id")) for r in box.open_items_of(who)],
        "board_open_count": int(box.board_view(limit=100,
                                               by_task_id=ids["M"])["board_open_count"]),
        "child_open_count": int(CT._board_cell(box, who,
                                               by_task_id=ids["M"])["child_open_count"]),
        "board_digest": text,
    }


def test_b_the_four_open_readings_are_untouched(tmp_path: pathlib.Path) -> None:
    """b：撤销前后，四个 open 读数只按既有口径各少那一条 —— 新格一个字都没漏进去。"""
    ws, box, ids = _hierarchy(tmp_path)
    keep = _item(box, owner=ids["F1"], role="F", expects="ack",
                 kind="notice", summary="还留着的一条")
    drop = _item(box, owner=ids["F1"], role="F", expects="work",
                 kind="delegation", summary="要撤掉的一条")
    before = _readings(box, ids, ids["F1"])
    # 无关的另一支（F2）的四个读数：撤销与通知都不许漏到它身上 ⇒ 前后必须逐字相同。
    other_before = _readings(box, ids, ids["F2"])
    assert before["open_items_of"] == [keep, drop], before

    assert _revoke(box, ids, drop).get("voided") == [drop]
    after = _readings(box, ids, ids["F1"])
    other_after = _readings(box, ids, ids["F2"])

    expect_open = [x for x in before["open_items_of"] if x != drop]
    assert after["open_items_of"] == expect_open, (before, after)
    assert after["board_open_count"] == before["board_open_count"] - 1, (before, after)
    assert after["child_open_count"] == before["child_open_count"] - 1, (before, after)
    # board_digest：只少被撤那一条，其余逐字相同（新格不许出现在这里）
    expect_text = "\n".join(line for line in before["board_digest"].splitlines()
                            if drop not in line)
    assert after["board_digest"] == expect_text, (before["board_digest"], after["board_digest"])
    assert "最近被撤销" not in after["board_digest"], after["board_digest"]
    # 无关的那一支：名下的项 / patrol / 板摘要三个读数逐字相同（通知没落到别人身上）；
    # `board_open_count` 是全工作区的数（`board_view` 的口径），它按既有口径少 1。
    for key in ("open_items_of", "child_open_count", "board_digest"):
        assert other_after[key] == other_before[key], (key, other_before, other_after)
    assert other_after["board_open_count"] == other_before["board_open_count"] - 1, (
        other_before, other_after)


# ---------------------------------------------------------------- c —— 没有撤项


def _c_problems(tmp_path: pathlib.Path) -> list[str]:
    """(c) 的判据本体：没人撤过 ⇒ 那一格是空表，提示词里连标题都不出现。"""
    problems: list[str] = []
    ws, box, ids = _hierarchy(tmp_path)
    _item(box, owner=ids["F1"], role="F", expects="ack",
          kind="notice", summary="一条正常待办")
    got = _mailbox(box, ws, ids["F1"])
    if got.get("revoked_recent") != []:
        problems.append(f"没有撤项时 revoked_recent 不是空表：{got.get('revoked_recent')!r}")
    if got.get("revoked_ids") != []:
        problems.append(f"没有撤项时 revoked_ids 不是空表：{got.get('revoked_ids')!r}")
    if "最近被撤销" in str(got.get("text") or ""):
        problems.append(f"没有撤项时提示词里出现了那一段：{got.get('text')!r}")
    # 负控：另一条"旧口径作废"（void 而不是 revoke）也不该冒充"被撤销"
    voided = _item(box, owner=ids["F1"], role="F", expects="ack",
                   kind="notice", summary="被作废的一条")
    row = next(dict(r) for r in box._tasks()
               if str(r.get("task_id")) == str(voided))
    # 直接按 void 的留痕形态改写那一行（作废只对"叫不醒的收件人"开，夹具里不铺那套）
    from agentflow import schema as S
    with box.store.tx("tasks", actor="test", note="void-mark") as tx:
        cur = dict(tx.find("tasks", task_id=voided))
        cur["item_state"] = "done"
        cur["item_close"] = "expired"
        cur["expects_was"] = "ack"
        cur["expects"] = ""
        cur["inputs"] = list(cur.get("inputs") or [])
        cur["inputs"].append(f"void:expired:{ids['D1']}:夹具")
        S.Task(**{k: v for k, v in cur.items()
                  if k in S.Task.__dataclass_fields__}).validate()
        tx.upsert("tasks", cur, note="void-mark")
    got2 = _mailbox(box, ws, ids["F1"])
    if got2.get("revoked_recent") != []:
        problems.append(f"旧口径的作废（void）被读成了撤销：{got2.get('revoked_recent')!r}")
    if "最近被撤销" in str(got2.get("text") or ""):
        problems.append(f"旧口径的作废（void）也让提示词里冒出了那一段：{got2.get('text')!r}")
    return problems


def test_a3_the_window_covers_the_recent_revocations_and_stops_after_delivery(
        tmp_path: pathlib.Path) -> None:
    """a3：最近 N 条一次念全（按撤销时刻从新到旧），投过之后同一条不再重复念。"""
    ws, box, ids = _hierarchy(tmp_path)
    items = [_item(box, owner=ids["F1"], role="F", expects="work",
                   kind="delegation", summary=f"第 {i} 条要撤的活") for i in range(7)]
    assert _revoke(box, ids, *items).get("voided") == items
    got = _mailbox(box, ws, ids["F1"])
    shown = [str(r.get("item_id")) for r in (got.get("revoked_recent") or ())]
    # 最近 N 条（缺省 5）：从新到旧取前 5 条；更早的两条是台账里的历史，不再进提示词。
    assert shown == sorted(items, reverse=True)[:5], (shown, items)
    assert all(f"[{x}]" in str(got.get("text") or "") for x in shown), got.get("text")
    # 投过之后（渲染集里有那几个键）⇒ 同一批不再重复念（不许每拍刷一遍）
    again = _mailbox(box, ws, ids["F1"], rendered=tuple(got["revoked_ids"]))
    assert again.get("revoked_recent") == [] and again.get("revoked_ids") == [], again
    assert "最近被撤销" not in str(again.get("text") or ""), again.get("text")


def test_c_without_a_revocation_the_cell_is_empty_and_the_prompt_stays_quiet(
        tmp_path: pathlib.Path) -> None:
    """c：没人撤过 ⇒ 空表、提示词里没有那一段（没有撤项的人不该读到废话）。"""
    assert _c_problems(tmp_path) == [], _c_problems(tmp_path)


# ---------------------------------------------------------------- d —— 反真空


def test_d_removing_the_revoked_section_turns_the_first_criterion_red(
        tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    """d：把「最近被撤销」那一段摘掉 ⇒ a 当场红（证明 a 读的正是这一段）。"""
    assert _a_problems(tmp_path / "d0") == []

    monkeypatch.setattr(Conductor, "revoked_recent_of",
                        lambda self, task_id, **kw: [])
    problems = _a_problems(tmp_path / "d1")
    assert problems, "「最近被撤销」那一段被摘掉了，a 却仍然绿 ⇒ a 没在读它"
    assert any("最近被撤销" in p or "revoked_recent" in p for p in problems), problems
