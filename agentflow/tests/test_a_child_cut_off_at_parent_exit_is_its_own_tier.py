# -*- coding: utf-8 -*-
"""D22：一个子代理的结局有三档，且三档从同一处判出来（业主 2026-10-26）。

## 这一份钉的是哪一件事

改前"被父代理退场掐断"这一档在台账上没有位置：`_settle_children_at_exit` 只写一条
`agent_children` 事件（`settled` 恒空）与一句 `run.notes`，一个字段都不落到子行上。
后果有两种，都实测过（`agentflow/temp/_probe_d22_exit.py`，零模型钱）：

- 父进程活下来 ⇒ 子在自己的线程里照常写成 `done`/`ok`，与正常交付的子逐字同形；
- 父进程被杀 ⇒ 子行永远留在 `running`（谁也没结算它）。

于是"这批子里哪几个是被掐断的"在台账上答不出来（这正是 D22）。

## 五条判据

| 条 | 判据 | 改前红在哪 |
|---|---|---|
| a | 父 final 被拒 + 有子在跑 ⇒ 退场后子行 `outcome=cut_off_by_parent` 且 `settled_at_parent_exit=True` | 改前子行是 `running`/`None`，一个标记都没有 |
| b | 父行 `detail` 同时含 `stop_reason` + "掐断了 N 个还在跑的子" + 每个编号 | 改前 `detail` 只有 `顶趟收工：<stop_reason>；闭环提醒 …`（`final_refused` 那趟 `run.final` 是空的） |
| c | 正控：正常交付的子不带标记、`outcome` 仍是 `ok` | 这一条改前就绿（守住"别把所有子都标成被掐断"） |
| d | 正控：被 `stop` 叫停的子走它自己那一档（`cancelled`），不被并进"父退出掐断" | 这一条改前也绿（守住"别把两个档合并"） |
| e | 反真空：把"打标记"那一步打桩掉 ⇒ a 与 b 必红 | 证明 a / b 真的在测那一步，而不是在测"子行恰好有个终态" |

## 出口为什么是 `waiting_for_user`

"父 final 被拒之后仍然退出"在今天有三条路：`stop` / 预算 / 等用户。前两条会先经
`stopctl.block_remaining_tasks` 把直接子行翻成 `block`（那是"优雅停止"自己的档，
判据 d 守它）—— 于是它们测不到"没有终态的子被掐断"这一档。`waiting_for_user`
（模型问用户、超时没人答 ⇒ 停在等）不动子行，是这一档唯一干净的出口。

## 夹具为什么不睡觉

"跑很久"由 `threading.Event` 造：孩子的 handler 卡在等放行上，判据自己决定什么时候放行
（与 `tests/test_summon_is_preemptible.py` 同一手法）。三个等待（派完等多久 / 返场等多久 /
退场排空多久）在 `fast_loop` 里压到毫秒：这一份判的是"退场那一步写了什么"，不是那几个数。
"""
from __future__ import annotations

import json
import pathlib
import threading
import time
from typing import Any, Mapping

import pytest

from agentflow import agent_loop as AL
from agentflow import schema as S
from agentflow.agent_loop import AgentLoop, run_role
from agentflow.conductor import Conductor
from agentflow.llmseam import LlmSeam
from agentflow.policy import Policy
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "d22"
#: 父是谁：主控 M。为什么必须是 M —— "问用户"那条通道归主控（非 M 调 `ask_user` 会被
#: `not_conductor` 当场拒，那一趟于是不会停在等，也就到不了"退场"这一步）；而这条路
#: 恰好是唯一不动子行的出口（stop / 预算会先把直接子翻成 block，见判据 d）。
ROLE = "M"
KID = "C"           # 子（C 没有出边 ⇒ 不会有孙辈搅进读数）
TASK = "D22 判据夹具：父退场时还在跑的子"

FINAL = json.dumps({"final": "都回来了，收工", "evidence": []}, ensure_ascii=False)
MANY = json.dumps({"summon_many": {"targets": [
    {"role": KID, "task": f"第 {i} 件长活", "instance": str(i)} for i in (1, 2)]}},
    ensure_ascii=False)
#: 问用户、零超时 ⇒ `state="pending"` ⇒ 这一趟停在等（不再发模型请求）。
ASK = json.dumps({"ask_user": {"question": "口径用哪个？", "timeout_sec": 0}},
                 ensure_ascii=False)


class _BlockingBackend:
    """派出去就卡住的后端：它只保证"父退场那一刻子还在跑"。

    为什么不用 `LocalBackend`：形状路的派活不点动作（口径 S2），`LocalBackend` 会当场以
    `not_wired` 拒绝 —— 那条路上根本没有"在跑的孩子"，这一份判据就没有对象。
    """

    name = "blocks"

    def __init__(self) -> None:
        self.gate = threading.Event()
        self._lock = threading.Lock()
        self.calls: list[str] = []

    def known_roles(self) -> list[str]:
        return [KID]

    def resolve(self, role: str, instance: str = "") -> Any:  # pragma: no cover - 接口需要
        return self

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: Any,
             instance: str = "", task_id: str = "") -> Any:
        with self._lock:
            self.calls.append(str(task_id))
        self.gate.wait(timeout=60.0)
        return {"outcome": "ok", "detail": f"{role} 的活跑完了",
                "payload": {"final": f"{role}#{instance or '-'} 的结论"}}

    def release(self) -> None:
        self.gate.set()

    def entered(self) -> int:
        with self._lock:
            return len(self.calls)


class _Gate:
    """照剧本回答的替身模型（不联网、不花钱）。`on_call(i)` 在第 i 次调用返回之前跑。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[str], on_call: Any = None) -> None:
        self.replies = list(replies)
        self.on_call = on_call
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        index = len(self.prompts)
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call(index)
        text = self.replies[min(index, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


@pytest.fixture()
def fast_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """三个等待压到毫秒，并把挂机那一支隔离掉。

    挂机必须打桩的原因（不是图省事）：`_park_gate` 在"有计时器在挂、而本趟无事可做"时
    跳过模型调用，于是"父退场"会被推迟到孩子都跑完之后 —— 那样这一份判据测到的
    "退场时子还在跑"就永远不成立。挂机自己的判据在 `tests/test_park_is_a_real_stop.py`。
    """
    original = AL.AgentLoop.__init__

    def patched(self: Any, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        self.child_step_wait_sec = 0.01
        self.child_return_wait_sec = 0.01
        self.child_exit_drain_sec = 0.05

    monkeypatch.setattr(AL.AgentLoop, "__init__", patched)
    monkeypatch.setattr(
        AL.AgentLoop, "_park_gate",
        lambda self, **kw: {"skip_model": False, "decision": "run",
                            "checked": True, "reason": "判据：照常问模型"})


def _env(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store, Conductor, _BlockingBackend]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    backend = _BlockingBackend()
    cond = Conductor(st, policy=Policy(), backend=backend)
    return ws, st, cond, backend


def _registry(st: Store, cond: Conductor, ws: pathlib.Path) -> Any:
    return build_registry(store=st, conductor=cond, workspace_root=ws).registry


def _kids(st: Store, parent: str) -> dict[str, dict]:
    return {str(r["task_id"]): dict(r) for r in st.rows("tasks")
            if str(r.get("parent_task_id") or "") == parent
            and not str(r.get("kind") or "")}


def _top_row(st: Store) -> dict:
    rows = [dict(r) for r in st.rows("tasks") if str(r.get("action") or "") == "run"]
    assert rows, "台账里没有顶趟那一行（父这一趟没收行）"
    return rows[-1]


def _run_until_exit(ws: pathlib.Path, st: Store, cond: Conductor,
                    replies: list[str], *, on_call: Any = None) -> tuple[Any, _Gate]:
    """走完整的 `run_role`（含父行收行），父的出口由剧本决定。"""
    gate = _Gate(replies, on_call=on_call)
    run = run_role(ROLE, TASK, store=st, registry=_registry(st, cond, ws),
                   conductor=cond, session_root=ws, sid=SID, from_env=False,
                   seam=LlmSeam(role=ROLE, session_root=ws, gateway=gate,
                                price=(0.0, 0.0), sid=SID),
                   max_steps=20)
    return run, gate


def _wait(predicate: Any, *, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


# ============================================================ a + b：被父退场掐断那一档


def test_a_child_still_running_at_exit_gets_its_own_tier(
        tmp_path: pathlib.Path, fast_loop: None) -> None:
    """判据 a：父 final 被拒 + 有子在跑 ⇒ 退场后那些子带专用标记 + 独立档。

    改前红（`agentflow/temp/_probe_d22_exit.py` 的实测）：退场后子行是 `status=running`、
    `outcome=None`、行里没有 `settled_at_parent_exit`，键集与正常交付那一行逐字相同。
    """
    ws, st, cond, backend = _env(tmp_path)
    run, gate = _run_until_exit(ws, st, cond, [MANY, FINAL, ASK])
    parent = str(run.prompt_audit.get("task_id") or "") or _top_row(st)["task_id"]

    # 一、这一趟真的走到了"final 被拒"（否则这条判据测的不是那个出口）。
    assert any("收工被拒" in str(n) for n in run.notes), run.notes
    assert run.stop_reason == "waiting_for_user", run.to_dict()
    # 二、退出时那几个子确实还在跑（句柄那一侧，不是台账那一侧）。
    kids = _kids(st, parent)
    assert len(kids) == 2, kids
    written = list(run.cut_off_children)
    assert sorted(written) == sorted(kids), (written, list(kids))
    # 三、子行：独立档 + 专用标记 + 一句说得清来路的 detail。
    for tid in written:
        row = kids[tid]
        assert row["status"] == "done", row
        assert row["outcome"] == "cut_off_by_parent", row
        assert row["settled_at_parent_exit"] is True, row
        assert "父代理退场时它还在跑" in str(row.get("detail") or ""), row
        assert row.get("ended_at"), row
    # 四、子线程晚到的交付不许改写这一行（`finish` 幂等：终态先到先得）。
    backend.release()
    assert _wait(lambda: all(str(r["status"]) == "done" for r in _kids(st, parent).values()))
    time.sleep(0.1)                       # 让晚到的那一笔真的走完 `finish`
    after = _kids(st, parent)
    for tid in written:
        assert after[tid]["outcome"] == "cut_off_by_parent", after[tid]
        assert after[tid]["settled_at_parent_exit"] is True, after[tid]


def test_b_the_parent_row_names_every_child_it_cut_off(
        tmp_path: pathlib.Path, fast_loop: None) -> None:
    """判据 b：父行的读数同时点名 N 与每一个编号（不许只说"有 N 个"）。

    改前红：`final_refused` 那趟的 `run.final` 是空的（D-68「不记 final」），于是父行
    `detail` 只剩 `顶趟收工：<stop_reason>；闭环提醒 …` —— 5 个被掐断的子与正常交付的
    子在同一张台账上长得一模一样。
    """
    ws, st, cond, backend = _env(tmp_path)
    run, gate = _run_until_exit(ws, st, cond, [MANY, FINAL, ASK])
    backend.release()
    row = _top_row(st)
    detail = str(row.get("detail") or "")
    written = [str(x) for x in run.cut_off_children]
    assert written, ("父行这一条没有对象：退场时没有被结算的子", run.to_dict())
    # 三样必须同时在：停机原因 / 那一句人话（含 N）/ 那一句里的每一个编号。
    assert run.stop_reason in detail, (run.stop_reason, detail)
    # 为什么必须断"整句 + 逐编号"，而不是"detail 里出现过这个编号"：闭环提醒那一句
    # （`_closure_suffix`）也会点名在跑的子 —— 只断"出现过"的话，一个从没写过这一句的
    # 实现也能靠它变绿（判据 e 就是按这个口径把这种情况抓出来的）。
    head = "我退出时掐断了"
    assert head in detail, detail
    clause = detail[detail.find(head):]
    clause = clause[:clause.find("；")] if "；" in clause else clause
    assert clause == f"{head} {len(written)} 个还在跑的子：{'、'.join(written)}", clause
    for tid in written:
        assert tid in clause, (tid, clause)
    assert row["outcome"] == "no_result", row        # 不是 final ⇒ 不是 ok


# ============================================================ c：正常交付不带标记


def test_c_a_child_that_delivers_carries_no_mark(
        tmp_path: pathlib.Path, fast_loop: None) -> None:
    """判据 c（正控）：正常交付的子不带标记、`outcome` 仍是 `ok`。

    守的是反向错误：把"每一个子"都盖上被掐断的章（那会让台账从此再也分不出真假）。
    """
    ws, st, cond, backend = _env(tmp_path)
    parent = cond.open_top_level_run(ROLE, TASK)
    reg = _registry(st, cond, ws)
    loop = AgentLoop(role=ROLE, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=ROLE, session_root=ws, gateway=_Gate([FINAL]),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=4, workspace_root=str(ws))
    loop.my_task_id = parent
    out = loop._do_summon_many({"targets": [
        {"role": KID, "task": "一件短活", "instance": "1"}]})
    tid = str(out["results"][0].get("task_id") or "")
    assert tid, out
    backend.release()                      # 立刻放行：它正常交付
    assert _wait(lambda: not loop._children_running()), loop._child_handles
    loop._settle_children_at_exit(run=AL.LoopRun(role=ROLE, task=TASK))
    row = _kids(st, parent)[tid]
    assert row["status"] == "done" and row["outcome"] == "ok", row
    assert row["settled_at_parent_exit"] is False, row
    assert loop._children_running() == [], loop._child_handles


# ============================================================ d：stop 那一档不被并进来


def test_d_a_stopped_child_keeps_its_own_tier(
        tmp_path: pathlib.Path, fast_loop: None) -> None:
    """判据 d（正控）：被 `stop` 叫停的子走它自己那一档，不与"父退出掐断"混。

    两半都要在：
    ① 判定点那一半 —— `schema.child_ending(stop_code=…)` 给的是 `cancelled`，不是那一档；
    ② 台账那一半 —— `dispose`（叫停的兜底写者）把在跑的子写成 `cancelled/cancelled`、
       标记为假；随后父的退场结算不改写它（它是别人的档）。
    """
    # ① 判定点：三档互斥（同一份事实只可能落一档）。
    stopped = S.child_ending(stop_code="user")
    cut = S.child_ending(cut_off=True)
    delivered = S.child_ending(status="done", outcome="ok")
    assert stopped["ending"] == "stopped" and stopped["outcome"] == "cancelled", stopped
    assert cut["ending"] == "cut_off_by_parent" and cut["settled_at_parent_exit"] is True, cut
    assert delivered["ending"] == "delivered" and not delivered["settled_at_parent_exit"]
    assert len({stopped["ending"], cut["ending"], delivered["ending"]}) == 3

    # ② 台账：dispose 写 cancelled；父的退场结算看到它已是终态 ⇒ 不改写、不并档。
    ws, st, cond, backend = _env(tmp_path)
    parent = cond.open_top_level_run(ROLE, TASK)
    reg = _registry(st, cond, ws)
    loop = AgentLoop(role=ROLE, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=ROLE, session_root=ws, gateway=_Gate([FINAL]),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=4, workspace_root=str(ws))
    loop.my_task_id = parent
    out = loop._do_summon_many({"targets": [
        {"role": KID, "task": "一件长活", "instance": "1"}]})
    tid = str(out["results"][0].get("task_id") or "")
    cond.dispose()
    stopped_row = _kids(st, parent)[tid]
    assert stopped_row["status"] == "cancelled", stopped_row
    assert stopped_row["outcome"] == "cancelled", stopped_row
    assert stopped_row["settled_at_parent_exit"] is False, stopped_row

    run = AL.LoopRun(role=ROLE, task=TASK)
    loop._settle_children_at_exit(run=run)
    backend.release()
    row = _kids(st, parent)[tid]
    assert row["status"] == "cancelled" and row["outcome"] == "cancelled", row
    assert row["settled_at_parent_exit"] is False, row
    assert run.cut_off_children == [], run.cut_off_children


# ============================================================ e：反真空


def test_e_stubbing_the_mark_reddens_both_a_and_b(
        tmp_path: pathlib.Path, fast_loop: None,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 e（反真空）：把"打标记"那一步打桩掉 ⇒ a 与 b 必红。

    为什么这一条必须有：a / b 若只断"子行有个终态、父行说了点什么"，那么一个从没写过
    标记的实现也能绿（子线程自己会写 `done`/`ok`，父行总会有一句 `detail`）。打桩掉
    `_write_children_cut_off` 之后，两边的现象必须同时消失 —— 这就是"它们在测那一步"的
    机器证明。打桩的返回值是空的那一份（不是抛异常：抛异常会让"一条判据坏了"与
    "这一步没跑"混在一起）。
    """
    monkeypatch.setattr(
        AL.AgentLoop, "_write_children_cut_off",
        lambda self, tids, *, run, waited_sec=0.0: {
            "written": [], "already_terminal": [], "problems": []})

    ws, st, cond, backend = _env(tmp_path)
    run, gate = _run_until_exit(ws, st, cond, [MANY, FINAL, ASK])
    backend.release()
    parent = str(run.prompt_audit.get("task_id") or "") or _top_row(st)["task_id"]
    kids = _kids(st, parent)
    assert len(kids) == 2, kids

    # a 红：子行没有被结算成那一档（它们会稍后由自己的线程写成 done/ok）。
    assert run.cut_off_children == [], run.cut_off_children
    assert _wait(lambda: all(str(r["status"]) == "done" for r in _kids(st, parent).values()))
    for tid, row in _kids(st, parent).items():
        assert row["outcome"] != "cut_off_by_parent", (tid, row)
        assert row["settled_at_parent_exit"] is False, (tid, row)

    # b 红：父行没有那一句（也不许靠闭环提醒里"在跑的子代理 N 个（…）"那一句冒充点名）。
    detail = str(_top_row(st).get("detail") or "")
    assert "我退出时掐断了" not in detail, detail
    assert str(len(kids)) not in detail or "个还在跑的子" not in detail, detail
