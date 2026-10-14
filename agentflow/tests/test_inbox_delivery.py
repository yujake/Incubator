# -*- coding: utf-8 -*-
"""投递的两个集合只有一个来源（`draft/83` §11 的 D75 / `draft/86` §4.1 的 S4 前半）。

真机读数（`draft/89` §2）：128 个会话里 `agent_message` 579 条，而 `agent_inbox`
（"这批已投递"）只有 12 次、涉及 8 条消息。旧形态的病根是一句话：

    渲染 `messages[-8:]`  ←→  标记 `fresh`（全部未投递）

两个集合不一样大 ⇒ 第 9 条及更早的留言既不进提示词、也不再是 fresh ⇒ 永久静默丢失。
这份文件钉三件事：

1. 渲染集合 == 标记集合（现在 `inbox_digest` 的第二个返回值就是"渲染过的"；
   调用方标它，两个集合只有一个来源）；
2. 未投递优先、老的先读（否则新留言不断到来会把老的永远挤在窗口外）；
3. 积压要看得见（窗口装不下时提示词里写"还有 K 条没渲染"）。
"""
from __future__ import annotations

import pathlib

from agentflow import schema as S
from agentflow import agent_loop as AL
from agentflow.store import Store


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return ws


def _send(ws: pathlib.Path, n: int, *, prefix: str = "m", sid: str | None = None) -> list[str]:
    ids: list[str] = []
    for i in range(n):
        mid, problem = AL.send_message(ws, sender="M", to="D",
                                       subject=f"{prefix}{i:02d}", body=f"正文 {i}", sid=sid)
        assert not problem, problem
        ids.append(mid)
    return ids


def test_a_message_to_a_role_without_a_reader_says_so(tmp_path: pathlib.Path):
    """正控（D76 / `draft/86` §4.2）：收件人没有 LLM 循环 ⇒ 回执是 `no_reader`，不是 `ok`。

    真机读数（`draft/89` §2）：579 条留言只有 8 条被读过，12 次投递登记全由 M 写 ——
    生产形态下只有 M 有循环。旧回执写的是 `ok: True` + "收件人下次运行时会看到它"，那是假话。
    """
    from agentflow.agent_loop import AgentLoop, PUBLIC
    from agentflow.conductor import Conductor, LocalBackend

    ws = _ws(tmp_path)
    st = Store(ws)
    # 只有 D 有循环（A 是确定性动作）—— 这正是真机的接线形态（生产里只有 M 有）
    loops = {("D", "consider"): {"max_steps": 3}}
    backend = type("B", (), {"loops": loops})()
    cond = Conductor(st, backend=LocalBackend({}))
    cond.backend = backend                     # 让 loop 看得见接线表
    loop = AgentLoop(role="M", session_root=ws, registry=None, seam=None,
                     conductor=cond, store=st, sid="rcpt", auto_secretary=False)
    got_a = loop._do_message({"to": "A", "subject": "s", "body": "b"})
    assert got_a["receipt"] == "no_reader" and got_a["ok"] is False, got_a
    assert "不会有任何进程读它" in got_a["note"], got_a
    got_d = loop._do_message({"to": "D", "subject": "s", "body": "b"})
    assert got_d["receipt"] == "queued" and got_d["ok"] is True, got_d
    got_pub = loop._do_message({"to": PUBLIC, "subject": "s", "body": "b"})
    # S6-a（业主 T20/T21 附二 乙）：公聊的可见面是"发信人的直接子代理" ⇒ 这一趟
    # 没有台账号时受控拒绝（`no_task_id`），不再回一个"queue 了"的乐观回执 ——
    # 那种回执正是"谁都能看的广播"的旧形态。有台账号时怎么判，见
    # `tests/test_the_public_channel_is_the_senders_children.py`。
    assert got_pub["ok"] is False and got_pub["refused"] == "no_task_id", got_pub
    assert "可见面" in got_pub["error"], got_pub


def test_the_receipt_is_unknown_when_the_wiring_table_is_invisible(tmp_path: pathlib.Path):
    """负控（三态）：看不见接线表 ⇒ `unknown`，不许按乐观猜成 `queued`。"""
    from agentflow.agent_loop import AgentLoop

    ws = _ws(tmp_path)
    st = Store(ws)
    loop = AgentLoop(role="M", session_root=ws, registry=None, seam=None,
                     conductor=None, store=st, sid="rcpt2", auto_secretary=False)
    got = loop._do_message({"to": "A", "subject": "s", "body": "b"})
    assert got["receipt"] == "unknown", got
    assert "不许折成" in got["note"], got


def test_messages_stay_fresh_when_no_model_call_ever_succeeds(tmp_path: pathlib.Path):
    """负控（D75 的后半，`draft/86` §4.1 的"推迟标记"）：这一趟一次模型调用都没成功
    ⇒ 留言仍然是 fresh（不许在首次 `ask_step` 之前就承认"送达"）。

    改前必红：旧实现一进 `run()` 就 `mark_delivered`，于是"在首次模型调用前就死掉"的那一趟
    会把消息的"新"标记永久吃掉 —— 消息还在盘上，但再也不会被念到。
    """
    from agentflow.agent_loop import run_role
    from agentflow.conductor import Conductor, LocalBackend
    from agentflow.llmseam import LlmSeam
    from agentflow.tools import build_registry

    ws = _ws(tmp_path)
    st = Store(ws)
    ids = _send(ws, 2, sid="dead")
    cond = Conductor(st, backend=LocalBackend({}))

    class _Dead:
        """一个必然失败的网关：`call.ok` 永远为假（模拟 auth_failed 这类"从没问成"）。"""

        spec = type("Spec", (), {"model": "dead", "api_key": "x"})()

        def complete(self, prompt: str, **kw: object) -> object:
            return type("R", (), {"ok": False, "text": "", "tool_calls": (), "tokens_in": 0,
                                  "tokens_out": 0, "error_detail": "注入的失败",
                                  "error_kind": "auth_failed"})()

    reg = build_registry(store=st, conductor=cond).registry
    run = run_role("D", "跑一趟", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="D", session_root=ws, gateway=_Dead(), sid="dead"),
                   session_root=ws, workspace_root=str(ws), sid="dead", from_env=False)
    assert run.stop_reason != "final", run.to_dict()
    _text, rendered, _problems = AL.inbox_digest(ws, "D", sid="dead")
    assert rendered == ids, ("留言被误标成已投递 —— 这一趟一次模型调用都没成功", rendered)


def test_the_message_id_is_max_plus_one_not_a_count(tmp_path: pathlib.Path):
    """正控（`draft/83` D79 / `draft/86` §5）：编号取最大号 + 1，不是"数条数 + 1"。

    造法：先发一条（`m0001`），再手工追加一条带大号 `m0009` 的消息（append-only 会话里
    这等价于"中间有坏行占过号"）。"数条数 + 1" 会给出 `m0003`，"取最大 + 1" 给出 `m0010`。
    """
    from agentflow import sessions as SS

    ws = _ws(tmp_path)
    _send(ws, 1)
    SS.append(ws, {"kind": "agent_message", "msg_id": "m0009", "from": "M", "to": "D",
                   "subject": "手工占号", "body": "x", "channel": "private"}, sid=None)
    mid, problem = AL.send_message(ws, sender="M", to="D", subject="新的一条", body="y")
    assert not problem, problem
    assert mid == f"m{S.format_id(10)}", mid


def test_a_message_line_without_an_id_is_a_bad_line_not_a_substitute(tmp_path: pathlib.Path):
    """负控（同一个 D79）：缺 `msg_id` 的行报坏行，不许按事件序号编一个替身号。

    替身号会与真实号重复（那个序号是"全部事件"的序号，不是消息序号），而 `delivered`
    以 msg_id 为键 ⇒ 会把别人的"已投递"状态读到这条身上（三态塌成一态）。
    """
    from agentflow import sessions as SS

    ws = _ws(tmp_path)
    ids = _send(ws, 1)
    SS.append(ws, {"kind": "agent_message", "from": "M", "to": "D",
                   "subject": "没有号的一条", "body": "x", "channel": "private"}, sid=None)
    msgs, problems = AL.read_messages(ws, "D", sid=None)
    assert problems and "没有 msg_id" in problems[0], problems
    assert [m["msg_id"] for m in msgs] == ids, ("坏行不许被编一个号混进来", msgs)


def test_the_rendered_set_is_exactly_what_gets_marked(tmp_path: pathlib.Path):
    """正控（D75 的核心）：12 条未投递 ⇒ 开场窗口渲染 8 条，标记的恰好是这 8 条。

    改前必红：旧实现标记的是全部 12 条，于是第 9-12 条下次再也不出现。
    """
    ws = _ws(tmp_path)
    ids = _send(ws, 12)
    text, rendered, problems = AL.inbox_digest(ws, "D", sid=None)
    assert not problems, problems
    assert len(rendered) == 8, rendered
    assert rendered == ids[:8], (rendered, ids)          # 老的先读（时间升序）
    assert "还有 4 条留言没渲染" in text, text            # 积压是看得见的事实
    assert text.splitlines()[0].startswith(f"- （新）[m{S.format_id(1)}]"), text
    assert AL.mark_delivered(ws, "D", rendered, sid=None) == ""
    # 剩下的 4 条仍然是 fresh ⇒ 下一步会读到它们（这正是"不再丢"的机器形态）
    text2, rendered2, _ = AL.inbox_digest(ws, "D", sid=None)
    assert rendered2 == ids[8:], (rendered2, ids[8:])
    assert "（新）" in text2, text2


def test_the_other_window_renders_everything_it_hears(tmp_path: pathlib.Path):
    """负控/口径对照：`window=None`（`_hear` 那条路）把新到的一次性全渲染、全标记。

    这一步的结果会把 `heard` 里每一条都并进上下文 ⇒ "渲染多少标多少"在那里等价于
    "标全部新到的"；两处窗口不同、纪律同一条。
    """
    ws = _ws(tmp_path)
    ids = _send(ws, 12)
    _text, rendered, _ = AL.inbox_digest(ws, "D", sid=None, window=None)
    assert rendered == ids, (rendered, ids)


def test_delivered_messages_are_background_not_priority(tmp_path: pathlib.Path):
    """正控（优先级的另一半）：窗口先给未投递的，已投递的只当背景。"""
    ws = _ws(tmp_path)
    ids = _send(ws, 3)
    AL.mark_delivered(ws, "D", ids, sid=None)
    new_ids = _send(ws, 2, prefix="n")
    text, rendered, _ = AL.inbox_digest(ws, "D", sid=None)
    # 两条新的必须都在（窗口 8 > 2 条新的 ⇒ 余量给已投递的背景）
    assert set(new_ids) <= set(rendered), (new_ids, rendered)
    first_line = text.splitlines()[0]
    assert first_line.startswith(f"- （新）[m{S.format_id(4)}]") and "n00" in first_line, text


def test_an_empty_inbox_is_not_a_problem(tmp_path: pathlib.Path):
    """反真空：空收件箱是"读成了、没有留言"，不是"没读成"（三态不许折平）。"""
    ws = _ws(tmp_path)
    text, rendered, problems = AL.inbox_digest(ws, "D", sid=None)
    assert text == "（没有收到留言）" and rendered == [] and problems == [], (text, rendered, problems)
