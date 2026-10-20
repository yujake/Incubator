# -*- coding: utf-8 -*-
"""S1i：板项进提示词 + 渲染即 seen（业主 A3=甲；`draft/95` 排期的第二批）。

## 这一批补的是哪一段链

`draft/94` §4 的实测：真机 2276 行 `tasks` 里 `kind` 非空 0 行 ⇒ 板项从来没有进过
任何提示词；`claim_item` / `mark_item_seen` / `close_item` 三个写入点在 `src/` 里
零调用者（`draft/90` `E13`）。结果是板"只写不读"：父读不到子那条交差通报，
"删"（退役）也就没有触发源。

## 本文件钉住四件事

1. 正控：挂在我名下的项进 `system` 提示词，且被标 `seen`（`seen_by`=我的台账号、
   `seen_step`=那一步）；
2. 负控（D75 的原形态）：没渲染的项不许被标 seen（窗口 8 之外的那些）；
3. 负控（不许越界）：别人的项（挂在别的实例名下的）不许出现在我的提示词里；
4. 反真空（三态）：读不到 conductor / 没有台账号 / 读失败 ⇒ 提示词里是带括号的问题，
   绝不是"（板上没有要你处理的事）"。

夹具：真 `Conductor` + 真盘 + 假网关（记录 `systems`），不手写提示词。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import agent_loop as AL
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s1i"


class _Gate:
    """照剧本回答的替身（记录 system 与 user 两条消息，不联网）。

    2026-10-21 起 `{{board}}` 那一格从 system 挪进了开场那条 user 消息
    （跨 run 会变的事实不再进前缀，见 `promptstability.STEP_VOLATILE_FACTS`），
    所以这里两条都记：判据据此同时断言"板项不进 system"与"板项确实进了 user"。
    """

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.systems: list[str] = []
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.systems.append(system or "")
        self.prompts.append(str(prompt))
        text = self.replies[min(len(self.systems) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _ws(tmp_path: pathlib.Path) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    return st, cond, ws


def _me(cond: Conductor) -> str:
    """造"我"这一行（顶层实例行），返回我的台账号。"""
    return cond.open_top_level_run("M", "我这一趟的活")


def _item(cond: Conductor, owner: str, *, key: str, summary: str = "派给你的活") -> str:
    return cond.open_item(kind="delegation", role="M", expects="work", action="run_once",
                          summary=summary, called_by="M", parent_task_id=owner,
                          depth=2, input_key=key)


def _run(cond: Conductor, st: Store, ws: pathlib.Path, gate: _Gate, me: str,
         task: str = "把这一趟做完") -> Any:
    reg = build_registry(store=st, conductor=cond).registry
    loop = AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    return loop.run(task, summoned_by="user", my_task_id=me, depth=1)


def _row(st: Store, tid: str) -> dict[str, Any]:
    return next(r for r in st.rows("tasks") if str(r.get("task_id")) == tid)


def test_a_board_item_reaches_the_prompt_and_is_marked_seen(tmp_path: pathlib.Path):
    """正控：项进 `system`、且被标 seen（`seen_by` = 我、`seen_step` = 那一步）。

    改前必红：提示词里没有 `{{board}}` 那一格，项也不会被标 seen（写入点零调用者）。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    item = _item(cond, me, key="s1i@1", summary="把 X 的族构造证据补齐")
    gate = _Gate([json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)])
    run = _run(cond, st, ws, gate, me)
    assert run.stop_reason == "final", run.to_dict()

    system = gate.systems[-1]
    user = gate.prompts[-1]
    assert "挂在你名下的工作项" in system, system[-600:]
    # 板项的**内容**在 user 消息里（2026-10-21 起它不再进 system：那一格是"这一趟的
    # 事实"，进了 system 就把整条前缀绑死在这一趟上）。
    assert item in user, ("板项没进提示词（编号都没出现）", user[-900:])
    assert "把 X 的族构造证据补齐" in user, user[-900:]
    assert item not in system, ("板项还在 system 里 ⇒ 前缀跨不过 run", system[-600:])

    row = _row(st, item)
    assert row["item_state"] == "seen", row
    assert row["seen_by"] == me, ("seen_by 必须是读它的那个实例", row)
    assert row["seen_step"] is not None and int(row["seen_step"]) >= 0, row


def test_an_item_outside_the_window_is_not_marked_seen(tmp_path: pathlib.Path):
    """负控（D75 的原形态）：没渲染的项不许被标 seen。

    做法：开 9 条项（窗口默认 8）⇒ 第 9 条不进这一步的提示词，
    因此它也不许被标 seen（渲染集合 = 标记集合；旧写法那种"渲染 8 条、标掉全部"
    会让第 9 条永久静默丢失）。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    items = [_item(cond, me, key=f"s1i@w{i}", summary=f"第 {i} 件活") for i in range(9)]
    gate = _Gate([json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)])
    _run(cond, st, ws, gate, me)

    seen = [i for i in items if _row(st, i)["item_state"] == "seen"]
    assert len(seen) == 8, ("窗口是 8：恰好 8 条被标 seen", len(seen))
    left = [i for i in items if _row(st, i)["item_state"] != "seen"]
    assert len(left) == 1, left
    assert "还有 1 项没渲染" in gate.prompts[-1], gate.prompts[-1][-900:]


def test_another_instances_items_never_enter_my_prompt(tmp_path: pathlib.Path):
    """负控（不许越界）：挂在别人名下的项不许出现在我的提示词里。

    这条防的是"渲染查询写错一层"（例如把 `in_flight_items` 那种全表过滤当读侧）——
    那会让父看到子的待办，等于绕过"发给谁的只有谁能读"。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    other = _item(cond, me, key="s1i@other", summary="别人的活")
    # 把它的收件人改成另一个实例（模拟"挂在你兄弟名下"）
    with st.tx("tasks", actor="test", note="reparent") as tx:
        row = tx.find("tasks", task_id=other)
        row["parent_task_id"] = "t-9999"
        tx.upsert("tasks", row, note="reparent")
    gate = _Gate([json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)])
    _run(cond, st, ws, gate, me)
    assert other not in gate.prompts[-1], ("别人的项进了我的提示词", gate.prompts[-1][-900:])
    assert other not in gate.systems[-1], ("别人的项进了我的 system", gate.systems[-1][-600:])
    assert _row(st, other)["item_state"] != "seen", _row(st, other)


def test_no_conductor_is_a_problem_string_not_an_empty_board(tmp_path: pathlib.Path):
    """反真空（三态）：读不到 / 没台账号 ⇒ 提示词里是带括号的问题。

    没有这一条，"读不成"会被折成"板上没事" —— 于是父以为子没交差，
    而实际上它压根没读到板（本仓最忌的形态）。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    _item(cond, me, key="s1i@3")

    text, ids, problems = AL.board_digest(None, my_task_id=me)
    assert text.startswith("（") and "conductor" in text, text
    assert ids == [] and problems == [], (ids, problems)

    text2, ids2, problems2 = AL.board_digest(cond, my_task_id="")
    assert text2.startswith("（") and "台账" in text2, text2
    assert ids2 == [] and problems2 == [], (ids2, problems2)


def test_board_digest_window_none_renders_everything(tmp_path: pathlib.Path):
    """边界：`window=None`（`_hear` 那一档）⇒ 全部未 seen 的项都渲染。"""
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    items = [_item(cond, me, key=f"s1i@n{i}") for i in range(9)]
    text, ids, problems = AL.board_digest(cond, my_task_id=me, window=None)
    assert not problems, problems
    assert sorted(ids) == sorted(items), (ids, items)
    assert "没渲染" not in text, text
