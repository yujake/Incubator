# -*- coding: utf-8 -*-
"""D-52 的 mailbox 投递点 + D-53 的唤醒消费（判据全部"改前红"）。

## 这一份钉的是哪两件事

D-52（`draft/146` 钉到根因）：`_opening_transcript` 把 `board` / `inbox` 渲染进
开卷那条消息（唯一注入点），之后不再刷新 ⇒ 中途投进来的板项永远读不到。
真机现场（`projects/sylow3`，只读读数）：t-000031 / t-000038 在 17:45:45 落成
`item_state=queued`，而收件人 t-000003 直到 18:05（阻塞式派活返回之后）才第一次
读到它们 —— 19 分钟里它一步都没有机会读队列。

D-53（同一族的另一面）：父在等子期间没有回合。M（t-000001）的步在 17:34:25
的第 5 次调用上停住，此后 33 分钟一步都没有（子代理还在跑）⇒ 它既读不到队列，
也无从"定期监控全树"。D-53 的正确处理方式的第 ② 条逐字：

    「等待判据里要读 clock.pending_wakes 并折进它本来有的 wake_pending」

## 七条判据（每条都对应"改前红"）

1. 回合中途投一条 notice ⇒ 该 agent 下一次 `llm_call` 的提示词里出现、且只出现
   一次，`item_state → seen`（改前：只有"一步执行完之后 `_hear`"那条耳朵会送，
   而 `invalid` 步根本走不到它 ⇒ 这一条红在"一次都没出现"上）；
2. 超过上限 ⇒ 按到达序投前 N 条、其余下一次、一条不丢；
3. 开卷那段不再包含 board / inbox 两格（否则同一条既在快照又在增量里）；
4. 续跑：`rebuilt == run.messages` 仍逐字相同（既有判据不许破 —— 投递事件是
   输入流的一部分，重放就能拼回同一段）；
5. 唤醒：父名下有在飞的子、时钟到点 ⇒ 父立刻拿到一个回合，该回合的提示词里
   有树形读数与该支的 queued 项；同一个回合的出口被收窄成 watch / guide / 补派 / 收口；
6. 反真空：把投递点打桩成空 ⇒ 1 红；把 `mark_item_seen` 打桩成不动 ⇒ 1 红
   （状态不动就会每一步重投一遍 —— 去重只有状态机那一处）；
7. 负控：子全部 done 且无唤醒 ⇒ 不产生空转回合（不许无限烧钱）。

## 这一份不假装比实际更强的地方

第 5 条里的"等"是名下有在飞的子（台账读数是 `status=running`），不是"父正在
`summon` 的调用栈里阻塞"。后者在今天的架构下没法被抢占（子代理与父在同一个进程里
同步跑），所以本文件不声称"立刻结束阻塞等待"；它守的是"父回到自己回合的第一个边界
上就消费唤醒、并且那一回合是监控回合"。真机读数（sylow3）说明这两件事的差：
D1 那次阻塞等了 29 分钟，而它一回到回合就看到了 17:45 落下的那两条 notice。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Callable, Mapping, Sequence

import pytest

from agentflow import agent_loop as AL
from agentflow import clock as CLK
from agentflow import sessions as SS
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry
from _d68_board_fixture import children_clean_their_boards  # noqa: E402 - D-68 夹具助手（替身角色不会自己 ack，见该模块 docstring）

SID = "mailbox"
TASK = "把这一趟的活做完（D-52/D-53 的判据夹具）"

#: 一条"根本不是 JSON"的回复 ⇒ `judge_bad_json` 的 `invalid` 步。用它当"这一步什么都没
#: 执行"的替身：`invalid` 那一支在 `_hear` 之前就 `continue`，于是"改前那唯一一条投递
#: 通道"不成立。
#:
#: 为什么不用 `{"oops": 1}`（一个解析得出、但形状认不出的对象）：那一支在改前就有
#: 一处重建不一致（live 把原始 `data` 塞进 assistant 消息的 `arguments`、而事件里存的是
#: `payload={}` ⇒ `resume_messages` 拼不回来）。那是另一条缺陷（已记进回报），
#: 不该让它把这一份判据的"改前红"搅浑。
BAD_JSON = "这不是 JSON：我想想再说"

#: 收工那一句（M 免 `notify`）。
FINAL = json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)


class _Gate:
    """照剧本回答的替身：记 prompt 与 system，`on_call(i)` 在这次调用返回之前跑。

    `on_call` 就是"回合中途投一条 notice"的注入点：那一刻模型这次调用还没返回，
    所以这条 board 项是在"上一步执行完之后、下一步的提示词拼出来之前"到达的。
    """

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: Sequence[str],
                 on_call: Callable[[int], None] | None = None) -> None:
        self.replies = list(replies)
        self.on_call = on_call
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        index = len(self.prompts)
        self.prompts.append(prompt)
        self.systems.append(system or "")
        if self.on_call is not None:
            self.on_call(index)
        text = self.replies[min(index, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


def _ws(tmp_path: pathlib.Path) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    children_clean_their_boards(cond)
    return st, cond, ws


def _me(cond: Conductor, task: str = TASK) -> str:
    return cond.open_top_level_run("M", task)


def _notice(cond: Conductor, owner: str, *, key: str, detail: str) -> str:
    """开一条发给 `owner` 的 notice 板项（`item_state=queued`）—— 中途到达的那种。"""
    item = cond.open_item(kind="notice", role="M", expects="ack", action="notice",
                          summary=detail[:120], called_by="F", parent_task_id=owner,
                          depth=2, input_key=key)
    cond.set_item_detail(item, detail)
    return item


def _child(cond: Conductor, parent: str, *, status: str, key: str,
           role: str = "D") -> str:
    """造一行子代理（实例行，`kind=""`）—— "父在等子"那一半的台账夹具。"""
    tid = cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": status,
        "outcome": None if status in ("pending", "running") else "ok",
        "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-24T17:34:25+08:00",
        "ended_at": None if status in ("pending", "running")
                   else "2026-10-24T17:50:00+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")
    # D-68 夹具（业主 2026-10-26：「最终 final 时应该是 M 下整棵树都已销号，
    # 否则不记 final」）：这一行只是"树里有节点"的上下文，本判据考的是信箱投递
    # ⇒ 夹具直接把它记成已销号（生产里那一笔由 `Secretary.retire` 写在父行 `inputs`
    # 的 `edge-released:` 落痕上，`Conductor.retire_integrity` 读的就是它）。
    # 还在跑的那一档不记：销号对"还在飞的子"本来就该被拒。
    if status not in ("pending", "running"):
        cond.note_edge_release(parent, child_task_id=tid, attempt=1)
    return tid


def _run(cond: Conductor, st: Store, ws: pathlib.Path, gate: _Gate, me: str, *,
         max_steps: int = 6, workspace_root: pathlib.Path | None = None,
         monitoring_of: str = "") -> Any:
    reg = build_registry(store=st, conductor=cond,
                         workspace_root=workspace_root or ws).registry
    loop = AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=max_steps,
                     workspace_root=str(workspace_root or ws))
    # `monitor_of` 用 setattr 而不是构造参数：这样这份判据在改前那棵树上也能跑
    # （没有这个字段）—— "改前红"必须是行为红（投递/唤醒没发生），而不是
    # "构造参数对不上"那一类红。
    loop.monitor_of = str(monitoring_of or "")
    return loop.run(TASK, summoned_by="user", my_task_id=me, depth=1)


def _row(st: Store, item_id: str) -> dict[str, Any]:
    return next(r for r in st.rows("tasks") if str(r.get("task_id")) == item_id)


def _events(ws: pathlib.Path, kind: str) -> list[dict[str, Any]]:
    events, problems = SS.read_session(ws, sid=SID)
    assert not problems, problems
    return [e for e in events if e.get("kind") == kind]


@pytest.fixture()
def real_clock():
    """判据前后都把时钟换回真时钟（`clock.use` 是进程级的，串了会污染别的判据）。"""
    CLK.reset()
    try:
        yield CLK
    finally:
        CLK.reset()


# ---------------------------------------------------------------- 1. 回合中途投递

def test_a_notice_arriving_mid_run_is_delivered_once_and_marked_seen(
        tmp_path: pathlib.Path) -> None:
    """判据 1：回合中途投一条 notice ⇒ 下一次 `llm_call` 的提示词里有它、只一次、state→seen。

    改前红在哪：那条 notice 是在第 0 次模型调用期间到达的，而第 0 步的回复是 `invalid`
    —— `invalid` 那一支在 `_hear()` 之前就 `continue`，于是改前唯一那条投递通道
    （"一步执行完之后听一次"）根本没有被调用；开卷那一段也早就在这一刻之前渲染完了。
    实测的改前形态就是 sylow3 的 D1：一条 queued 的 notice 挂了 19 分钟没人读到。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    marker = "承重引理（conjecture 000002）已证出"
    made: list[str] = []

    def inject(index: int) -> None:
        if index == 0:
            made.append(_notice(cond, me, key="mid@1",
                                detail=f"{marker} —— 这是跑到一半才到的通报"))

    gate = _Gate([BAD_JSON, FINAL], on_call=inject)
    run = _run(cond, st, ws, gate, me)
    assert run.stop_reason == "final", run.to_dict()
    assert len(gate.prompts) >= 2, ("夹具没造出第二次调用 ⇒ 这条判据什么也没测到",
                                    gate.prompts)

    # 出现：在第 1 次（0 起算）调用的提示词里；且只出现一次。
    assert marker in gate.prompts[1], (
        "中途投进来的 notice 没进下一次调用的提示词（D-52 的形态）", gate.prompts[1][-1200:])
    total = sum(p.count(marker) for p in gate.prompts)
    assert total == 1, (f"同一条 notice 在提示词里出现了 {total} 次（要求恰好一次）",
                        [p.count(marker) for p in gate.prompts])

    # state 推进：queued → seen → done。D12（业主 2026-10-27）之后 notice 是信息型：
    # 被拼进提示词那一拍就已经办完了（"seen 就是 ack"，`Conductor._settle_if_informational`），
    # 所以终态是 `done` + `item_close="acked"`，而不是停在 `seen` 等模型再调 `conductor.ack`。
    # `seen_step` 是"读它的那一步"= 1（第 0 步的回复是 invalid，那条 notice 是在
    # 第 0 次调用期间到达的，所以它的第一次投递点落在第 1 步的 `ask_step` 之前）。
    row = _row(st, made[0])
    assert row["item_state"] == "done", row
    assert row["item_close"] == "acked", row
    assert row["seen_by"] == me, row
    assert int(row["seen_step"]) == 1, row

    # 投递记录（append-only）：一条 `agent_mailbox`，键是 item_id。
    delivered = _events(ws, AL.MAILBOX_EVENT)
    assert delivered, "投递没有落 append-only 事件 ⇒ 「投过没有」不可复算"
    hits = [e for e in delivered if made[0] in (e.get("item_ids") or [])]
    assert len(hits) == 1, delivered
    assert hits[0]["shape"] == "turn", hits[0]
    assert hits[0]["step"] == 1, hits[0]
    assert marker in str(hits[0].get("text") or ""), hits[0]

    # 收口读数：这一趟投递了多少条（`agent_run_end` 那两格）。
    end = _events(ws, "agent_run_end")[-1]
    assert made[0] in (end.get("mailbox_items") or []), end.get("mailbox_items")
    assert int(end.get("mailbox_delivered") or 0) >= 1, end.get("mailbox_delivered")


def test_over_the_limit_delivers_the_first_n_and_keeps_the_rest(
        tmp_path: pathlib.Path) -> None:
    """判据 2：超上限 ⇒ 按到达序投前 `MAILBOX_LIMIT` 条，其余下一次，一条不丢。

    "一条不丢"的机器形态：全部 10 条最后都 `done`（D12 起 notice 被渲染那一拍就收口，
    见 `Conductor._settle_if_informational` —— 改前是"全部 `seen`"），且"还有 K 项
    没渲染"这句话出现在受窗口限制的那一次提示词里（积压必须是可读的事实）。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    # 上限从被测模块现读（改前那棵树上没有这个常量 ⇒ 用 8 兜底，好让这条判据在改前
    # 红在行为上（投递那一段不存在），而不是红在 AttributeError 上）。
    n = int(getattr(AL, "MAILBOX_LIMIT", 8)) + 2
    made: list[str] = []

    def inject(index: int) -> None:
        if index == 0:
            made.extend(_notice(cond, me, key=f"cap@{i}", detail=f"第 {i} 条通报")
                        for i in range(n))

    gate = _Gate([BAD_JSON, BAD_JSON, FINAL], on_call=inject)
    run = _run(cond, st, ws, gate, me)
    assert run.stop_reason == "final", run.to_dict()
    assert len(gate.prompts) >= 3, gate.prompts

    first, second = gate.prompts[1], gate.prompts[2]
    # 前 N 条：按到达序（编号序 = 到达序，`open_item` 取号）在第一次投递里。
    limit = int(getattr(AL, "MAILBOX_LIMIT", 8))
    for i, item in enumerate(made[:limit]):
        assert item in first, (f"第 {i} 条没进第一次投递", first[-1200:])
    for item in made[limit:]:
        assert item not in first, ("超上限的项不该出现在受窗口限制的那一次投递里", first)
        assert item in second, ("超上限的项没在下一次投递里补上 ⇒ 丢了一条", second)
    assert f"还有 {n - limit} 项没渲染" in first, first[-800:]
    # 一条不丢：全部收口（信息型渲染即收口 ⇒ 终态是 done/acked；改前这里要的是"全部 seen"）。
    left = [i for i in made if _row(st, i)["item_state"] != "done"]
    assert not left, ("这些项到最后还没收口（丢了 / 停在 queued 或 seen）", left)
    assert all(_row(st, i)["item_close"] == "acked" for i in made), (
        [(_row(st, i)["task_id"], _row(st, i)["item_close"]) for i in made])


def test_the_opening_message_no_longer_carries_board_or_inbox(
        tmp_path: pathlib.Path) -> None:
    """判据 3：开卷那段不再包含 board / inbox 两格（流水不塞进快照）。

    改前红：两格就在开头第一条消息里（`你的收件箱：…` / `挂在你名下的工作项…`），
    而它是唯一注入点 ⇒ 中途到达的东西读不到。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    early = _notice(cond, me, key="open@1", detail="这一条在开卷那一刻就在板上")
    gate = _Gate([FINAL])
    run = _run(cond, st, ws, gate, me)
    assert run.stop_reason == "final", run.to_dict()

    opening = str(run.messages[0].get("content") or "")
    assert "你的收件箱：" not in opening, opening[:800]
    assert "挂在你名下的工作项（板；可能为空）：" not in opening, opening[:800]
    # 同一条事实仍然读得到 —— 只是落点变成了增量段（这一条在第一步就投进去了）。
    assert early in gate.prompts[0], ("板项既不在开卷、也不在增量里 ⇒ 信息被删了",
                                      gate.prompts[0][-1200:])


def test_the_resumed_sequence_still_equals_the_live_one(tmp_path: pathlib.Path) -> None:
    """判据 4：续跑 `rebuilt == run.messages` 仍逐字相同（既有判据不许破）。

    改前红的方式与 D-52 无关（那一条一直绿）：这一条守的是"新增投递消息之后仍能
    逐条拼回去" —— 投递事件是输入流的一部分，`resume_messages` 按事件序把它重放回
    同一个位置（`shape="turn"` 那一档）；`step_tail` 那一档不另加消息。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)

    def inject_and_stop(index: int) -> None:
        from agentflow import stopctl

        if index == 0:
            _notice(cond, me, key="resume@1", detail="续跑那一条：跑到一半才到")
        if index == 1:
            # 第 2 条回答之后写停机开关 ⇒ 第 3 步开头读到它 ⇒ 恰好做完 2 步。
            stopctl.request_stop(ws, reason="判据：够步数了")

    gate = _Gate([BAD_JSON, json.dumps({"tool": "fs.list", "args": {"path": "."}},
                                       ensure_ascii=False), FINAL],
                 on_call=inject_and_stop)
    run = _run(cond, st, ws, gate, me)
    assert run.stop_reason == "stop_file", run.to_dict()
    assert len(run.steps) >= 2, run.to_dict()

    rebuilt, step0 = AL.resume_messages(ws, "M", SID, task=TASK)
    assert step0 >= 2, step0
    assert rebuilt == run.messages, (
        "重建的序列与当时那一份不逐条相等（投递那一条没按事件序重放回去）",
        [i for i, (a, b) in enumerate(zip(rebuilt, run.messages)) if a != b][:5],
        len(rebuilt), len(run.messages))
    assert AL.render_messages(rebuilt) == run.transcript


# ---------------------------------------------------------------- 5. 唤醒消费

def test_a_due_timer_wakes_the_waiting_parent_with_the_tree_reading(
        tmp_path: pathlib.Path, real_clock) -> None:
    """判据 5：父名下有在飞的子、时钟到点 ⇒ 父拿到一个带树形读数的监控回合。

    造法（全部走生产路径，不手写提示词）：
    ① 建工作区 + 主控行 + 两条 `status=running` 的子代理行（"父在等子"的台账形态）；
    ② `build_registry(workspace_root=ws)` 把 `clock.*` 与到点动作接上；
    ③ 起一个 1 分钟的计时器，`FakeClock.advance()` 让它到点 ⇒ `_deliver_due` 落一条
       notice 板项 + 一条 `out/clock/wake.json` 的唤醒标记；
    ④ 跑循环：第一个回合边界上 `fire_due` + 读唤醒 ⇒ 消费 ⇒ 监控回合。

    改前红：`agent_loop` 全文 0 处读唤醒标记（`clock.py` 的 docstring 逐字承认
    "消费端还没接"），所以这条唤醒永远不会变成回合，树形读数也不会出现在提示词里。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    kids = [_child(cond, me, status="running", key="wake@a"),
            _child(cond, me, status="running", key="wake@b")]
    fake = CLK.use(CLK.FakeClock(wall="2026-10-24T17:40:00+00:00"))
    CLK.reset_books()
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    reason = "每 10 分钟看一次全树（D-53 的业主口径）"
    timer = CLK.start_timer(ws, after_sec=60, reason=reason, task_id=me, role="M")
    fake.advance(90)                     # 到点 ⇒ notice 板项 + 唤醒标记
    assert CLK.pending_wakes(ws, me)["count"] == 1, CLK.read_wakes(ws)

    # D-68（业主 2026-10-26 追裁：「任何 final 都要清仓，没有例外」）：这一条夹具的
    # 两个子按设计整段都在飞（树形读数靠它们），所以这一趟不许发 final
    # —— 发了会被结构完整性闸拒。改用停机开关在这一步之后收工（`stop_file`），
    # 判据要问的东西（监控回合 / 树形读数 / 唤醒消费 / 到点投递）一样都在。
    def stop_after_first(index: int) -> None:
        from agentflow import stopctl

        if index == 0:
            stopctl.request_stop(ws, reason="判据：看完这一回合就收工（不发 final）")

    gate = _Gate([json.dumps({"tool": "fs.list", "args": {"path": "."}},
                             ensure_ascii=False), FINAL], on_call=stop_after_first)
    loop = AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=5, workspace_root=str(ws))
    run = loop.run(TASK, summoned_by="user", my_task_id=me, depth=1)
    assert run.stop_reason == "stop_file", run.to_dict()

    # ① 父立刻拿到一个回合，而那个回合是监控回合（行为读数在前：改前这里一条都没有）。
    first = gate.prompts[0]
    assert "【监控回合】" in first, first[-1500:]
    assert reason in first, ("唤醒的理由没进提示词 ⇒ 父不知道为什么被叫醒", first[-1500:])
    assert "树形读数" in first, first[-1500:]
    assert int(getattr(run, "wakes", 0)) == 1, ("到点的唤醒没有被消费", run.to_dict())
    assert int(getattr(run, "monitor_turns", 0)) == 1, run.to_dict()
    # ② 树形读数里读得到那两条在飞的子代理（"谁在飞"）。
    for kid in kids:
        assert kid in first, (f"树形读数里没有 {kid}（在飞的子没被念出来）", first[-1500:])
    assert "在飞" in first, first[-1500:]
    # ③ 同一条唤醒产生的 notice 板项在同一个增量里投到（唤醒 → 投递 → 处理）。
    items = [r for r in st.rows("tasks")
             if str(r.get("kind") or "") == "notice"
             and str(r.get("input_key") or "") == f"clock:{timer.timer_id}"]
    assert len(items) == 1, items
    # 到点项既是"被投到了"又是"被消费了"：D12 起 notice 的 seen 就是 ack，
    # 于是终态是 done/acked（改前它永远停在 seen，且没有任何人 ack 它）。
    assert items[0]["item_state"] == "done", ("到点项没被投到 / 没被收口", items[0])
    assert items[0]["item_close"] == "acked", items[0]
    # ④ 唤醒写进了 append-only 事件与收工读数。
    wakes = _events(ws, "agent_wake")
    assert len(wakes) == 1 and wakes[0]["wake_ids"] == ["wk-000001"], wakes
    end = _events(ws, "agent_run_end")[-1]
    assert end["wakes"] == 1 and end["monitor_turns"] == 1, end
    assert end["wake_ids"] == ["wk-000001"], end["wake_ids"]


def test_the_monitor_turn_only_lets_watch_guide_supplement_and_close(
        tmp_path: pathlib.Path, real_clock) -> None:
    """判据 5 的第二半（出口限定）：监控回合里别的动作被框架拒。

    改前红：没有"监控回合"这个概念（没有唤醒就没有这一档），也就没有任何闸 ——
    `fs.list` 在改前是正常执行的一步。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    _child(cond, me, status="running", key="gate@a")
    fake = CLK.use(CLK.FakeClock(wall="2026-10-24T18:00:00+00:00"))
    CLK.reset_books()
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    CLK.start_timer(ws, after_sec=5, reason="看一次全树", task_id=me, role="M")
    fake.advance(10)

    # D-68（业主 2026-10-26 追裁：「任何 final 都要清仓，没有例外」）：这里有一个按设计
    # 一直在飞的子（监控回合的存在前提），所以这一趟不发 final，改用停机开关收工。
    def stop_after_first(index: int) -> None:
        from agentflow import stopctl

        if index == 0:
            stopctl.request_stop(ws, reason="判据：这一回合被拒之后就看完了（不发 final）")

    gate = _Gate([json.dumps({"tool": "fs.list", "args": {"path": "."}},
                             ensure_ascii=False), FINAL], on_call=stop_after_first)
    loop = AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=5, workspace_root=str(ws))
    run = loop.run(TASK, summoned_by="user", my_task_id=me, depth=1)
    assert run.stop_reason == "stop_file", run.to_dict()
    refused = run.steps[0].result
    assert refused.get("refused") == "monitor_turn_restricted", refused
    assert "conductor.watch" in str(refused.get("error") or ""), refused
    assert any("出口限定" in n for n in run.notes), run.notes


# ---------------------------------------------------------------- 6. 反真空

def test_an_empty_delivery_point_makes_the_first_criterion_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 6（其一）：把投递点打桩成"永远没有新东西" ⇒ 判据 1 必红。

    这是"判据 1 真的在读投递点"的反真空：没有它，判据 1 有可能只是被别的东西
    （开卷、`_hear`、工具结果）满足了。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    marker = "承重引理（conjecture 000002）已证出"
    made: list[str] = []

    def inject(index: int) -> None:
        if index == 0:
            made.append(_notice(cond, me, key="vac@1", detail=marker))

    def empty_digest(*a: Any, **k: Any) -> dict[str, Any]:
        return {"checked": True, "text": "", "item_ids": [], "msg_ids": [],
                "problems": [], "backlog": 0, "reason": "", "items": []}

    # `raising=False`：改前那棵树上没有这个函数 —— 打桩本身就是"投递点不存在"。
    monkeypatch.setattr(AL, "mailbox_digest", empty_digest, raising=False)
    gate = _Gate([BAD_JSON, FINAL], on_call=inject)
    run = _run(cond, st, ws, gate, me)
    assert run.stop_reason == "final", run.to_dict()
    assert marker not in gate.prompts[1], (
        "投递点已经打桩成空，notice 却仍然进了提示词 ⇒ 判据 1 读的不是投递点", gate.prompts)
    assert _row(st, made[0])["item_state"] != "seen", _row(st, made[0])


def test_a_frozen_state_machine_makes_the_first_criterion_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 6（其二）：把 `mark_item_seen` 打桩成不动 ⇒ 判据 1 必红（跨趟无限重投）。

    去重的第二层就是状态机（`item_state == "queued"`）。状态不动 ⇒ 这一条永远不
    被认为是"读过了"：每一趟都会重新投它（同一趟之内由"渲染集"挡住重复渲染 ——
    那一层是"超上限时队尾要轮得到"的必要条件，两层各管一件事，见 `mailbox_digest`）。

    所以这一条判据打两次红：
    ① `item_state` 一直是 `queued`（判据 1 的 state 那一半红）；
    ② 第二趟（新的 `AgentLoop`，新的渲染集）又投了一次 —— 跨趟的重复投看得见。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    marker = "承重引理（conjecture 000002）已证出"
    made = [_notice(cond, me, key="frozen@1", detail=marker)]

    def frozen(self_: Any, task_id: str, *, by_task_id: str = "",
               step: int = 0) -> tuple[str, str]:
        return "", "判据打桩：状态机不动"

    monkeypatch.setattr(Conductor, "mark_item_seen", frozen)
    first_gate = _Gate([FINAL])
    run1 = _run(cond, st, ws, first_gate, me)
    assert run1.stop_reason == "final", run1.to_dict()
    assert first_gate.prompts[0].count(marker) == 1, (
        "同一趟里同一条被渲染了两遍 ⇒ 渲染集没挡住（超上限时队尾会轮不到）",
        first_gate.prompts[0].count(marker))
    assert _row(st, made[0])["item_state"] == "queued", (
        "state 推进被打桩成不动，项却已经不在 queued ⇒ 判据 1 的 state 那一半没在读状态机",
        _row(st, made[0]))
    assert any("没标成 seen" in n for n in run1.notes), run1.notes

    # 第六次：跨趟重投（新的循环 = 新的渲染集）。
    second_gate = _Gate([FINAL])
    run2 = _run(cond, st, ws, second_gate, me)
    assert run2.stop_reason == "final", run2.to_dict()
    assert marker in second_gate.prompts[0], (
        "状态不动、第二趟却不再投它 ⇒ 去重不在状态机上（那一层就不是承重的）",
        second_gate.prompts[0][-800:])


# ---------------------------------------------------------------- 7. 负控

def test_no_wake_and_all_children_done_produces_no_idle_turn(
        tmp_path: pathlib.Path, real_clock) -> None:
    """判据 7：子全部 done 且没有唤醒 ⇒ 不产生空转回合（不许无限烧钱）。

    "空转回合"的判据是三条一起：没有监控回合、没有消费到唤醒、脚本里的三条回复
    一条不多（第 4 次调用根本没发生）。
    """
    st, cond, ws = _ws(tmp_path)
    me = _me(cond)
    _child(cond, me, status="done", key="idle@a")
    _child(cond, me, status="done", key="idle@b")
    CLK.use(CLK.FakeClock(wall="2026-10-24T19:00:00+00:00"))
    CLK.reset_books()
    gate = _Gate([json.dumps({"tool": "fs.list", "args": {"path": "."}},
                             ensure_ascii=False),
                  json.dumps({"tool": "conductor.state", "args": {}},
                             ensure_ascii=False),
                  FINAL])
    run = _run(cond, st, ws, gate, me)
    assert run.stop_reason == "final", run.to_dict()
    assert int(getattr(run, "monitor_turns", 0)) == 0, run.to_dict()
    assert int(getattr(run, "wakes", 0)) == 0, run.to_dict()
    assert len(gate.prompts) == 3, ("子都 done 了还在多问 ⇒ 空转回合", gate.prompts)
    assert all("【监控回合】" not in p for p in gate.prompts), "没有唤醒却出现了监控回合"


def test_the_autonomy_round_boundary_folds_clock_wakes_into_wake_pending(
        tmp_path: pathlib.Path, real_clock) -> None:
    """判据 5 的第三个入口（`autonomy`）：轮边界把时钟唤醒折进它本来就有的 `wake_pending`。

    D-53 的施工单第 ② 条逐字："等待判据里要读 `pending_wakes` 并折进它本来有的
    `wake_pending`" —— 那个变量就在 `autonomy._stop_before_round`。改前它只认收件箱里
    没投递的留言 ⇒ 计时器到点在这一层看不见，"到点后时钟自动给 M 发消息检查"的后半段
    （M 真的多拿到一个回合）结构上不会发生。
    """
    from agentflow import autonomy as AU

    st, cond, ws = _ws(tmp_path)
    owner = _me(cond, "轮边界前的这一趟")
    _child(cond, owner, status="running", key="auto@a")
    fake = CLK.use(CLK.FakeClock(wall="2026-10-24T20:00:00+00:00"))
    CLK.reset_books()
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    CLK.start_timer(ws, after_sec=30, reason="轮边界上该醒来看全树",
                    task_id=owner, role="M")
    fake.advance(60)

    gate = _Gate([FINAL, FINAL, FINAL])
    run = AU.run_autonomous("M", TASK, store=st, registry=reg, conductor=cond,
                            gateway=gate, rounds=1, max_steps=3, sid=SID)
    assert run.rounds_done == 2, ("时钟唤醒没有多开一轮 ⇒ wake_pending 没折进判据",
                                  run.to_dict())
    assert run.woke_rounds == 1, run.to_dict()
    assert any("【监控回合】" in p for p in gate.prompts), (
        "多开的那一轮不是监控回合 ⇒ 提示词里没有树形读数", gate.prompts)
    monitor_prompts = [p for p in gate.prompts if "【监控回合】" in p]
    assert any("树形读数" in p for p in monitor_prompts), monitor_prompts
    rows = [e for e in _events(ws, "autonomy_wake")]
    assert len(rows) == 1 and rows[0]["wake_ids"] == ["wk-000001"], rows
    # 唤醒被消费掉（不许下一轮再开一轮 —— `WAKE_ALLOWANCE` 是有界的）。
    assert CLK.pending_wakes(ws, "M")["count"] == 0, CLK.read_wakes(ws)
