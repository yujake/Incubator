# -*- coding: utf-8 -*-
"""业主裁定：优雅停的作用范围就是「M 把整棵树停了」。

一个停机开关落下后，M 那一趟**以及它派出去的所有子孙循环**都必须停，不许出现
"第一个读到的人把开关撤掉、别人静默继续跑"。

## 改前 / 改后（`AgentLoop._stop_applies` + `_consume_stop_at_teardown`）

改前全工作区那一档（开关里没有 `root_task_id`）是"读到的第一个撤掉它"（§140 的
一次性信号）。问题是并行的子孙循环各有各的步边界：谁先读到谁撤，其余的人下一刻
读到的就是"没人叫停"⇒ 它们静默继续跑 —— 与 §140 那个 bug 同一族，方向反过来。

第一次修（"只有树根撤"）只挡住了一半：树根**在自己的步边界读到**那一刻就把文件删了，
还没走到步边界的兄弟/子孙下一刻同样读不到 —— 真机读数：第 1 趟
`s1 stop_reason='stop_file' … 开关还在=False`，第 2 趟 `s2 stop_reason='final'`
⇒ 继续跑。

改后：**删除从"读到时"推迟到"这一趟收工时"，且只有树根删**。

| 开关 | 我 | 结论 |
|---|---|---|
| 全工作区 | 树根（没有台账号 / 没有父任务） | 停；**读时不撤**，`consume_at_end=True` ⇒ 收尾时撤 |
| 全工作区 | 成员 | 停，**不撤**（`remove=False`、`consume_at_end=False`） |
| 子树 | 那一支的根 | 停 + 读时即撤（这一档一个字没动） |
| 子树 | 那一支的成员 | 停，不撤 |
| 子树 | 我不在那一支里 | 不停 |
| 子树 | 判不了 | 不停 + 读数 |

`force` 与 `stop_file` 两种 level 走的是同一条判据（`_user_stop_reason` 只在理由码上
分岔），所以两档各打一遍。

## 判据

既有 8 条（改后重新对齐，全部保留）：正控 5（①②成员停/不撤·成员读过别人仍然停、
③ `force` 档逐条同上、④ 没有台账号的那一趟也算树根、⑤ 子树那四档一个字没动）；
负控 2（① 把"成员也 `remove=True`"改回去 ⇒ 正控当场红；② 子树开关不许停到别的支）；
现状读数 2（一个工作区一份开关文件、两棵独立的树共用它）。

**追加 5 条（业主「删除推迟到收尾」那一半）**：

① 读时不删：成员与树根读完，开关都**还在**；
② 收工才删：树根这一趟收尾后开关消失，`stop-history.jsonl` 里 `removed=True`
  记在**收尾那一笔**、`consumed_by_sid` 是收尾那一趟的 sid；
③ 窗口闭合（核心）：树根读 → 成员此刻再读仍 `stop_file` → 第二个成员仍 `stop_file`
  → 树根收尾，开关才消失（这一条必须能复现前代理实测到的那个洞）；
④ 成员永不删：成员读完、成员收尾之后开关仍在；
⑤ 负控：把"读时删除"改回去（monkeypatch 让 `remove` 在读取时返回 `True`）⇒ ③ 必须红。

## 现状读数（**不是规格**，第 4 项实测）

一个工作区一份开关文件，与 sid 无关 ⇒ 同一个工作区的不同 sid 之间会互相消费；
两棵各自独立的树共用一份文件时，第一个树根收尾撤走之后第二个树根读不到。
详见本文件最后两条。
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow import stopctl
from agentflow.agent_loop import AgentLoop, LoopRun
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

SID = "tree"


def _env(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    top = cond.open_top_level_run("M", "顶趟")
    return st, cond, ws, top


def _child(cond: Conductor, parent: str, *, role: str, key: str) -> str:
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-09T00:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:%s.run_once" % role)


def _loop(ws: pathlib.Path, cond: Conductor, *, task_id: str = "", parent: str = "",
          role: str = "D", sid: str = SID) -> AgentLoop:
    """造一个循环并**直接摆好**它的身份（`_stop_applies` 只读这两格）。

    `parent` 为什么显式给：真机上它是 `run()` 里 `_resolve_parent` 算出来的 —— 顶趟
    没有父时它落回**自己**（`parent_task_id == my_task_id`），这正是 `_is_tree_root`
    的第三档。把身份直接摆好，判据就打在这一格上，不必起一整趟。
    """
    loop = AgentLoop(role=role, session_root=ws, registry=None, seam=None, conductor=cond,
                     sid=sid, store=None, max_steps=1, auto_secretary=False)
    loop.my_task_id = task_id
    loop.parent_task_id = parent
    return loop


def _member_reading_keeps_the_switch(loop: AgentLoop, state: dict[str, Any]) -> None:
    """判据本体：**成员**读到全工作区开关 ⇒ 停、而且不撤（负控就打在这一条上）。"""
    verdict = loop._stop_applies(state)
    assert verdict["stop"] is True, f"成员读到全工作区开关必须停：{verdict}"
    assert verdict["remove"] is False, (
        f"成员不许撤开关（别人还要读到它）：{verdict}")
    assert verdict.get("consume_at_end") is False, (
        f"成员收尾时也不许撤（只有树根收尾才撤）：{verdict}")


def _finish_the_pass(loop: AgentLoop) -> str:
    """让这一趟走到自己的收尾（`run()` 末尾那一步：`agent_run_end` 落盘之后才调它）。

    这就是生产路径上 `run()` 里那一行（`self._consume_stop_at_teardown()`）：
    直接调它，判据打的才是"收尾"这个落点本身，而不是另写一份模拟。
    """
    return loop._consume_stop_at_teardown()


def _the_window_stays_open_until_the_root_finishes(ws: pathlib.Path, cond: Conductor,
                                                   top: str, d: str, g: str,
                                                   e: str) -> None:
    """判据③的本体：树根读 → 两个成员此刻再读仍 `stop_file` → 树根收尾才消失。

    负控⑤把它整条跑一遍并期望 `AssertionError`（把"读时删除"改回去 ⇒ 第一条
    "树根读完开关还在"就红）—— 于是"这条判据真的能抓住那个洞"有机器证明。
    """
    root = _loop(ws, cond, task_id=top, parent=top, role="M", sid="s-root")
    assert root._user_stop_reason(LoopRun(role="M", task="t")) == "stop_file", (
        "树根读到全工作区开关必须停")
    assert stopctl.read_stop(ws) is not None, (
        "树根读完的下一刻开关必须还在 —— 这就是前代理实测到的那个洞")

    first = _loop(ws, cond, task_id=d, parent=top, role="D", sid="s-d")
    assert first._user_stop_reason(LoopRun(role="D", task="t")) == "stop_file", (
        "树根读完之后，成员再读仍必须是 stop_file（不是 ''）")
    assert stopctl.read_stop(ws) is not None

    second = _loop(ws, cond, task_id=g, parent=d, role="G", sid="s-g")
    assert second._user_stop_reason(LoopRun(role="G", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None

    third = _loop(ws, cond, task_id=e, parent=top, role="E", sid="s-e")
    assert third._user_stop_reason(LoopRun(role="E", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None, "三个成员都读完了，开关还得在"

    assert _finish_the_pass(root) == ""
    assert stopctl.read_stop(ws) is None, "只有树根这一趟收尾之后，开关才消失"


# ---------------------------------------------------------------- 正控 ①②


def test_members_stop_without_removing_and_later_members_still_stop(tmp_path: pathlib.Path):
    """正控①②：全工作区（`stop_file`）—— 成员停且不撤；成员读过后，另一个成员**仍然**停。

    这条就是业主那句裁定的机器形态：不许出现"第一个读到的人把开关撤掉、别人静默继续跑"。
    三个成员分别在两支上（D 与 D 的孙 G、另一支的 E），**都**必须停 —— 全工作区 = 整棵树。
    树根读到也不撤；它这一趟收尾时（`_finish_the_pass`）才撤。
    """
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="tree@d")
    g = _child(cond, d, role="G", key="tree@g")
    e = _child(cond, top, role="E", key="tree@e")
    stopctl.request_stop(ws, reason="user", by="user")
    state = stopctl.read_stop(ws)
    assert state is not None and stopctl.stop_scope(state)["scope"] == "all", state

    # 成员①（D 那一支的成员）：停，不撤
    d_loop = _loop(ws, cond, task_id=d, parent=top, role="D")
    _member_reading_keeps_the_switch(d_loop, state)
    assert d_loop._user_stop_reason(LoopRun(role="D", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None, "成员读到之后开关必须还在（别人还要读）"

    # 成员②（同支的孙）：**仍然**停 —— 这一格就是那个静默洞的反面
    g_loop = _loop(ws, cond, task_id=g, parent=d, role="G")
    _member_reading_keeps_the_switch(g_loop, state)
    assert g_loop._user_stop_reason(LoopRun(role="G", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None, "第二个成员读完之后开关还得在"

    # 成员③（另一支）：全工作区 = 整棵树，另一支也停（这是"全"那个字）
    e_loop = _loop(ws, cond, task_id=e, parent=top, role="E")
    _member_reading_keeps_the_switch(e_loop, state)
    assert e_loop._user_stop_reason(LoopRun(role="E", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None

    # 反真空：成员那三笔都记了，且都是 `removed=False`
    hist = stopctl.stop_history(ws, limit=10)
    assert [h["removed"] for h in hist] == [False, False, False], hist
    assert [h["level"] for h in hist] == ["stop_file", "stop_file", "stop_file"], hist

    # 树根（M 自己的那一趟，`parent_task_id` 落在自己身上）：停；**读时不撤**
    root = _loop(ws, cond, task_id=top, parent=top, role="M")
    root_run = LoopRun(role="M", task="t")
    assert root._user_stop_reason(root_run) == "stop_file"
    assert stopctl.read_stop(ws) is not None, "树根读到时也不许删（兄弟/子孙还没读到）"
    hist = stopctl.stop_history(ws, limit=10)
    assert [h["removed"] for h in hist] == [False, False, False], hist

    # 这一趟自己的收尾：现在才撤（业主裁定：删除推迟到收工时）
    assert _finish_the_pass(root) == ""
    assert stopctl.read_stop(ws) is None, "撤销落在这棵树这一趟的收尾（不是读取那一刻）"
    hist = stopctl.stop_history(ws, limit=10)
    assert [h["removed"] for h in hist] == [False, False, False, True], hist
    assert hist[-1]["level"] == "stop_file", hist
    assert hist[-1]["consumed_by_sid"] == SID, hist


def test_the_force_level_follows_the_same_table(tmp_path: pathlib.Path):
    """正控③：`force` 档逐条同上（理由码 `force_stop`，撤的责任仍然只在树根收尾）。

    为什么单列：`force` 是"直接停"那一档，很容易被写成"谁都直接把它删掉"。
    改后它走的是同一条 `_stop_applies`，只有 `reason` 那一格分岔 —— 这条钉住它。
    """
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="tree@force-d")
    g = _child(cond, d, role="G", key="tree@force-g")
    stopctl.request_stop(ws, reason="user", by="user", force=True)
    state = stopctl.read_stop(ws)
    assert state is not None and bool(state["force"])

    member = _loop(ws, cond, task_id=d, parent=top, role="D")
    _member_reading_keeps_the_switch(member, state)
    assert member._user_stop_reason(LoopRun(role="D", task="t")) == "force_stop"
    assert stopctl.read_stop(ws) is not None, "强制档也不许成员撤"

    second = _loop(ws, cond, task_id=g, parent=d, role="G")
    assert second._user_stop_reason(LoopRun(role="G", task="t")) == "force_stop"
    assert stopctl.read_stop(ws) is not None, "第二个成员仍然读到强制停"

    root = _loop(ws, cond, task_id=top, parent=top, role="M")
    assert root._user_stop_reason(LoopRun(role="M", task="t")) == "force_stop"
    assert stopctl.read_stop(ws) is not None, "强制档读时也不删（收尾才撤）"
    assert _finish_the_pass(root) == ""
    assert stopctl.read_stop(ws) is None, "强制的同一档：树根收尾才撤"

    hist = stopctl.stop_history(ws, limit=10)
    assert [h["level"] for h in hist] == ["force_stop", "force_stop", "force_stop"], hist
    assert [h["removed"] for h in hist] == [False, False, True], hist


def test_a_pass_without_a_task_id_counts_as_the_root(tmp_path: pathlib.Path):
    """正控④：没有台账号的那一趟也是树根（`run_role` 落台账之前就是这一态）。

    为什么它不算"判不了"：台账号是被召唤那一刻由调用方给的，没有台账号的循环
    **不可能**是别人派出来的 —— 这一档是"确定没有父"，不是"不知道"。
    """
    _st, cond, ws, _top = _env(tmp_path)
    stopctl.request_stop(ws, reason="user", by="user")
    state = stopctl.read_stop(ws)
    assert state is not None
    assert _loop(ws, cond, task_id="", parent="", role="M")._stop_applies(state) == {
        "stop": True, "remove": False, "consume_at_end": True, "why": ""}
    # 而"有台账号、有父"的那一格不许撤（同一条判据的另一半）
    d = _child(cond, _top, role="D", key="tree@no-tid-d")
    assert _loop(ws, cond, task_id=d, parent=_top, role="D")._stop_applies(state) == {
        "stop": True, "remove": False, "consume_at_end": False, "why": ""}


# ---------------------------------------------------------------- 正控⑤


def test_the_subtree_table_is_unchanged(tmp_path: pathlib.Path):
    """正控⑤：子树那一档的四格一个字没动（本支根撤 / 成员不撤 / 不在本支不停 / 判不了不停）。"""
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="tree@sub-d")
    g = _child(cond, d, role="G", key="tree@sub-g")
    e = _child(cond, top, role="E", key="tree@sub-e")
    stopctl.request_stop(ws, reason="user", by="M", root_task_id=d)
    state = stopctl.read_stop(ws)
    assert stopctl.stop_scope(state)["scope"] == "subtree", state

    # ① 我不在那一支里 ⇒ 不停 + 一句读数
    outside = LoopRun(role="E", task="t")
    assert _loop(ws, cond, task_id=e, parent=top, role="E")._user_stop_reason(outside) == ""
    assert outside.notes and "不在那一支里" in outside.notes[-1], outside.notes
    assert stopctl.read_stop(ws) is not None, "没停就不许撤掉别人的开关"

    # ② 判不了（台账里没有我这一行）⇒ 不停 + 一句读数
    blind = LoopRun(role="M", task="t")
    assert _loop(ws, cond, task_id="t-没这一行", role="M")._user_stop_reason(blind) == ""
    assert blind.notes and "判不了" in blind.notes[-1], blind.notes
    assert stopctl.read_stop(ws) is not None

    # ③ 本支的成员（孙）⇒ 停，但不撤
    member = _loop(ws, cond, task_id=g, parent=d, role="G")
    assert member._stop_applies(state) == {"stop": True, "remove": False, "why": ""}
    assert member._user_stop_reason(LoopRun(role="G", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None

    # ④ 本支的根 ⇒ 停，并且由它撤（子树这一档仍是读时即撤）
    root = _loop(ws, cond, task_id=d, parent=top, role="D")
    assert root._stop_applies(state) == {"stop": True, "remove": True, "why": ""}
    assert root._user_stop_reason(LoopRun(role="D", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is None

    hist = stopctl.stop_history(ws, limit=10)
    assert [h["removed"] for h in hist] == [False, True], hist
    assert [str(h.get("root_task_id") or "") for h in hist] == [d, d], hist


# ---------------------------------------------------------------- 负控


def test_negative_control_members_removing_would_silence_the_rest(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """负控①（核心）：把"成员也 `remove=True`"改回去 ⇒ 正控那条判据必须红。

    做法是 monkeypatch `AgentLoop._stop_applies`：全工作区那一档原样复原成改前的
    `{"stop": True, "remove": True}`（"读到的第一个撤掉它"，连成员也撤），
    **不碰生产代码**。演示两件事：

    ① 正控用的 `_member_reading_keeps_the_switch` 当场 `AssertionError`；
    ② 那个洞的具体形态：成员 A 读完之后开关没了，成员 B 读到的是"没人叫停"⇒ 静默继续跑。
    """
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="tree@neg-d")
    g = _child(cond, d, role="G", key="tree@neg-g")
    original = AgentLoop._stop_applies

    def _everyone_removes(self: AgentLoop, state: dict[str, Any]) -> dict[str, Any]:
        """改前那一格：全工作区 ⇒ 谁读到谁撤（子树那四档原样交回去）。"""
        verdict = original(self, state)
        if "consume_at_end" in verdict:
            return {"stop": True, "remove": True, "why": ""}
        return verdict

    monkeypatch.setattr(AgentLoop, "_stop_applies", _everyone_removes)

    stopctl.request_stop(ws, reason="user", by="user")
    state = stopctl.read_stop(ws)
    assert state is not None

    first = _loop(ws, cond, task_id=d, parent=top, role="D")
    with pytest.raises(AssertionError):
        _member_reading_keeps_the_switch(first, state)

    assert first._user_stop_reason(LoopRun(role="D", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is None, "老行为：第一个读到的把它撤了"
    assert stopctl.stop_history(ws, limit=10)[-1]["removed"] is True, "老行为：成员也撤"

    second = _loop(ws, cond, task_id=g, parent=d, role="G")
    assert second._user_stop_reason(LoopRun(role="G", task="t")) == "", (
        "老行为的静默洞：第二个成员读不到任何东西 ⇒ 它继续跑")

    # 树根在老行为下也是停的（所以只盯"停没停"看不出这个洞 —— 必须盯"撤没撤"）
    root = _loop(ws, cond, task_id=top, parent=top, role="M")
    assert root._stop_applies(state)["stop"] is True


def test_negative_control_a_subtree_switch_still_never_stops_another_branch(
        tmp_path: pathlib.Path):
    """负控②（反方向）：子树开关不许因为"盘上有开关"就停到别的支上去。"""
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="tree@neg2-d")
    e = _child(cond, top, role="E", key="tree@neg2-e")
    stopctl.request_stop(ws, reason="user", by="M", root_task_id=d)
    run = LoopRun(role="E", task="t")
    assert _loop(ws, cond, task_id=e, parent=top, role="E")._user_stop_reason(run) == ""
    assert stopctl.read_stop(ws) is not None
    assert run.notes and "不在那一支里" in run.notes[-1], run.notes


# ---------------------------------------------------------------- 追加 ①：读时不删


def test_reading_the_switch_deletes_nothing(tmp_path: pathlib.Path):
    """追加①：成员与树根读完，开关都**还在**；读的那一刻一笔 `removed=True` 都没有。

    这一条与追加③分开写，是因为它盯的是"读"这个动作本身：即使树根还没走到
    "收尾那一行"，读也不许改变盘上的开关（`_stop_applies` 的 `remove` 恒为
    `False`，删除责任只在 `consume_at_end`）。
    """
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="tree@read-d")
    stopctl.request_stop(ws, reason="user", by="user", sid="writer")
    state = stopctl.read_stop(ws)
    assert state is not None

    member = _loop(ws, cond, task_id=d, parent=top, role="D")
    _member_reading_keeps_the_switch(member, state)
    assert member._user_stop_reason(LoopRun(role="D", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None, "成员读完开关还在"

    root = _loop(ws, cond, task_id=top, parent=top, role="M")
    assert root._user_stop_reason(LoopRun(role="M", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None, "树根读完开关也必须还在（读不是消费）"

    hist = stopctl.stop_history(ws, limit=10)
    assert [h["removed"] for h in hist] == [False], hist
    assert not [h for h in hist if h["removed"]], "读的那一刻不许记 `removed=True`"


# ---------------------------------------------------------------- 追加 ②：收工才删


def test_the_root_removes_the_switch_when_its_pass_ends(tmp_path: pathlib.Path):
    """追加②：树根这一趟**收尾之后**开关消失；`removed=True` 记在收尾那一笔。

    三样读数：`removed=True`、`consumed_by_sid` 是收尾那一趟的 sid、
    `sid` 仍是写开关的那一趟（"谁写的"与"谁撤的"分得开）。
    """
    _st, cond, ws, top = _env(tmp_path)
    _child(cond, top, role="D", key="tree@end-d")
    stopctl.request_stop(ws, reason="user", by="user", sid="writer")
    root = _loop(ws, cond, task_id=top, parent=top, role="M", sid="s-root")

    assert root._user_stop_reason(LoopRun(role="M", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None, "读时不许删"

    assert _finish_the_pass(root) == ""
    assert stopctl.read_stop(ws) is None, "树根这一趟收尾之后开关才消失"

    hist = stopctl.stop_history(ws, limit=10)
    assert [h["removed"] for h in hist] == [True], (
        "读不记一笔、收尾记一笔 ⇒ 唯一那一笔就是删除那笔（且它在收尾）")
    last = hist[-1]
    assert last["consumed_by_sid"] == "s-root", last
    assert last["sid"] == "writer", "开关是谁写的（sid）与谁撤的（consumed_by_sid）分得开"
    assert last["level"] == "stop_file", last


# ---------------------------------------------------------------- 追加 ③：窗口闭合


def test_the_window_stays_open_until_the_root_finishes(tmp_path: pathlib.Path):
    """追加③（核心）：树根读 → 成员此刻再读仍 `stop_file` → 树根收尾才消失。

    这正是前代理实测到的那个洞的机器形态：改前树根读到即删，成员下一刻读到 `""`
    （静默继续跑）。顺序读数写在 `_the_window_stays_open_until_the_root_finishes` 里，
    负控⑤把它整条跑一遍并期望红。
    """
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="tree@win-d")
    g = _child(cond, d, role="G", key="tree@win-g")
    e = _child(cond, top, role="E", key="tree@win-e")
    stopctl.request_stop(ws, reason="user", by="user", sid="writer")

    _the_window_stays_open_until_the_root_finishes(ws, cond, top, d, g, e)

    hist = stopctl.stop_history(ws, limit=10)
    assert [h["removed"] for h in hist] == [False, False, False, True], hist
    assert hist[-1]["consumed_by_sid"] == "s-root", hist
    assert hist[-1]["sid"] == "writer", hist


# ---------------------------------------------------------------- 追加 ④：成员永不删


def test_a_member_finishing_its_pass_never_removes_the_switch(tmp_path: pathlib.Path):
    """追加④：成员读完、也走完自己的收尾之后，开关仍在（别人还要读到它）。

    为什么"成员的收尾"也要打一遍：`_consume_stop_at_teardown` 是树根/成员共用的收尾
    落点，如果成员的 `_stop_to_consume_at_end` 被谁挂上，它就会替整棵树把开关撤掉
    —— 这一条钉住"只有树根挂得上"。
    """
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="tree@memb-d")
    stopctl.request_stop(ws, reason="user", by="user", sid="writer")
    member = _loop(ws, cond, task_id=d, parent=top, role="D", sid="s-member")

    assert member._user_stop_reason(LoopRun(role="D", task="t")) == "stop_file"
    assert _finish_the_pass(member) == "", "成员收尾没有可撤的东西（不是失败）"
    assert stopctl.read_stop(ws) is not None, "成员收尾之后开关必须还在"
    hist = stopctl.stop_history(ws, limit=10)
    assert [h["removed"] for h in hist] == [False], hist


# ---------------------------------------------------------------- 追加 ⑤：负控


def test_negative_control_read_time_removal_reopens_the_silent_hole(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """追加⑤（负控，核心）：把"读时删除"改回去 ⇒ 追加③当场红。

    做法：monkeypatch `AgentLoop._stop_applies`，让全工作区那一档在**读取时**就返回
    `remove=True`（= 改前行为"读到的第一个撤掉它"），`consume_at_end` 一并消失。
    不碰生产代码。演示两件事：

    ① 追加③的本体在"树根读完开关还在"那一句上 `AssertionError`；
    ② 洞的具体形态：树根一读文件就没了，成员随后读到 `""`（静默继续跑）。
    """
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="tree@neg5-d")
    g = _child(cond, d, role="G", key="tree@neg5-g")
    e = _child(cond, top, role="E", key="tree@neg5-e")
    original = AgentLoop._stop_applies

    def _read_time_removal(self: AgentLoop, state: dict[str, Any]) -> dict[str, Any]:
        """改前那一格：全工作区 ⇒ 读到就撤（子树那四档原样交回去）。"""
        verdict = original(self, state)
        if "consume_at_end" in verdict:
            return {"stop": True, "remove": True, "why": ""}
        return verdict

    monkeypatch.setattr(AgentLoop, "_stop_applies", _read_time_removal)
    stopctl.request_stop(ws, reason="user", by="user", sid="writer")

    with pytest.raises(AssertionError):
        _the_window_stays_open_until_the_root_finishes(ws, cond, top, d, g, e)

    # 洞的具体形态：树根一读，文件没了；成员随后读到的就是"没人叫停"
    assert stopctl.read_stop(ws) is None, "改回读时删除：树根读完文件就没了"
    later = _loop(ws, cond, task_id=d, parent=top, role="D", sid="s-later")
    assert later._user_stop_reason(LoopRun(role="D", task="t")) == "", (
        "改回读时删除 ⇒ 成员读不到任何东西 ⇒ 它继续跑（前代理实测的那个洞）")
    hist = stopctl.stop_history(ws, limit=10)
    assert hist[-1]["removed"] is True, "改回之后：删除那一笔发生在读取时，不在收尾"


# ---------------------------------------------------------------- 第 4 项：多趟共享一个开关文件


def test_one_workspace_has_one_switch_file_whatever_the_sid(tmp_path: pathlib.Path):
    """第 4 项实测：`--stop-file` / `.agentflow-stop` 都是「一个工作区一份」，与 sid 无关。

    三件事逐条打出来：

    1. 路径不带 sid：`stop_path(ws)` 恒为 `<ws>/.agentflow-stop`（`--stop-file` 给的也只是
       一个路径，CLI 的缺省是 `None` ⇒ 循环回落到 `read_stop(session_root)`）；
    2. `read_stop` / `consume_stop` 只认路径，sid 只写进 `runs/stop-history.jsonl` 的
       `consumed_by_sid`（"被哪一趟用掉"）；
    3. ⇒ **同一个工作区的不同 sid 之间会互相消费**：一把开关只有一个文件，谁撤都是撤它。
       改后成员不撤（`remove=False`）、树根在**自己收尾**时撤，所以同一棵树里不同 sid 的
       成员读多少次都在 —— 这一格是**好的**方向，下面直接断言。
    """
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="tree@sid-d")
    assert stopctl.stop_path(ws) == ws / ".agentflow-stop"
    assert stopctl.stop_path(ws, explicit="") == ws / ".agentflow-stop"

    stopctl.request_stop(ws, reason="user", by="user", sid="s1")
    state = stopctl.read_stop(ws)
    # 同一个成员那一趟，sid 换成 s2：照样读到、照样不撤
    other_sid = _loop(ws, cond, task_id=d, parent=top, role="D", sid="s2")
    _member_reading_keeps_the_switch(other_sid, state)
    assert other_sid._user_stop_reason(LoopRun(role="D", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None

    # 树根（sid=s1）读时不撤，收尾才撤 —— 撤的是那个文件，不区分是谁的
    root = _loop(ws, cond, task_id=top, parent=top, role="M", sid="s1")
    assert root._user_stop_reason(LoopRun(role="M", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None
    assert _finish_the_pass(root) == ""
    assert stopctl.read_stop(ws) is None
    hist = stopctl.stop_history(ws, limit=10)
    assert [h["consumed_by_sid"] for h in hist] == ["s2", "s1"], hist
    assert hist[0]["sid"] == "s1", "开关是谁写的（`sid`）与谁读的（`consumed_by_sid`）分得开"


def test_two_independent_trees_in_one_workspace_still_share_one_switch(
        tmp_path: pathlib.Path):
    """现状读数（**不是规格**）：两棵各自独立的树共用一个开关文件 ⇒ 第一个树根收尾撤离后，
    第二棵树的循环读不到任何东西。

    这是"一个工作区一份文件 + 只有树根收尾撤"两条合起来的**残差**：树根是"这一棵树的根"，
    而一个工作区里可以并行跑两趟互不相识的 M（不同 `--sid`）。第一棵树停并撤走文件，
    第二棵树下一刻就是"没人叫停" —— 与业主这条裁定要防的形态同族，只是层次在"工作区
    里有多棵树"这一档，不在"一棵树里谁是第一个读到的"那一档。

    为什么仍然写成一条判据：它把现状钉在盘上（改前是"谁都撤"，连一棵树内部都不成立；
    改后一棵树内部成立了，这一档留给下一批）。真要修，两条路留在报告里：
    按 sid 分文件，或者把开关改成"带已消费标记"而不是删文件。
    """
    _st, cond, ws, top = _env(tmp_path)
    second_top = cond.open_top_level_run("M", "第二趟")
    stopctl.request_stop(ws, reason="user", by="user")
    assert stopctl.read_stop(ws) is not None

    first = _loop(ws, cond, task_id=top, parent=top, role="M", sid="s1")
    assert first._user_stop_reason(LoopRun(role="M", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None, "读时不撤"
    assert _finish_the_pass(first) == ""
    assert stopctl.read_stop(ws) is None

    later = _loop(ws, cond, task_id=second_top, parent=second_top, role="M", sid="s2")
    assert later._user_stop_reason(LoopRun(role="M", task="t")) == "", (
        "现状：同一个工作区的两棵树共用一份开关文件 ⇒ 第二个树根读不到")
    assert stopctl.stop_history(ws, limit=10)[-1]["consumed_by_sid"] == "s1", (
        "读数：是 s1 那一趟收尾撤走的（s2 没有任何记录）")
