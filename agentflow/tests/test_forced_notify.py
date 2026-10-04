# -*- coding: utf-8 -*-
"""强制 `notify` 表（`draft/39` §3.2/§3.3，用户 2026-10-05 裁）—— 这也是 E4 演练。

用户口径（逐字）：

> 由于每个除主控外的 Agent 干完活后都会有明确的"把成果通知给谁"的步骤作为结束，我们就让它每次
> 要结束时强制填一个参数表，说明它要通知谁，通知什么信息，然后在知道这些后用脚本生成这个交接
> 文件，并同样用脚本把这个交接文件信息发给目标 Agent，即 Agent 互相之间的通信通过脚本强制留痕
> 并代为转发。
> ……若 Agent 不会填参数表，但凡填错格式就打回充填再发一条带有对格式详细说明的警告给 Agent 看。
> ……连续打回两次接收方也要反思自己的问题。

E4 的三条演练（本文件逐条落地）：

| # | 场景 | 期望 |
|---|---|---|
| 1 | 收工带 `notify` | 账本多一行、编号 0000、收件人留言里带 `[手稿 0000]` |
| 2 | 收工不带 `notify` | 打回重填（不是代填）：这一步是 `invalid`，警告里有四件事；连续 3 次 ⇒ `no_notify` |
| 3 | 收工带错字段 | 打回并点名那个字段；连续两次的警告里多一句"先说明你上一次为什么没按格式填" |
"""
from __future__ import annotations

import json
from typing import Any

from agentflow import manuscripts as MS
from agentflow.agent_loop import (
    AgentLoop, LlmBackend, notify_shape_problem, read_messages, run_role,
)
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry


class _Scripted:
    """一份"会照着 replies 说"的假模型（每一步一句 JSON）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        got = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": json.dumps(got, ensure_ascii=False),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _run(tmp_path, replies, *, role: str = "D", max_steps: int = 6):
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    gw = _Scripted(replies)
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=ws,
                         seam_factory=lambda r: LlmSeam(role=r, session_root=ws, gateway=gw,
                                                        price=(0.0, 0.0), sid="n1"),
                         max_steps=max_steps, store=st, sid="n1")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond).registry
    backend.registry = reg
    run = run_role(role, "收工演练", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role=role, session_root=ws, gateway=gw, price=(0.0, 0.0), sid="n1"),
                   session_root=ws, workspace_root=str(ws), sid="n1",
                   max_steps=max_steps, from_env=False)
    return ws, run


# ============================================================ 演练 1：带 notify ⇒ 留痕 + 转发

def test_e4_1_a_final_with_notify_writes_the_handoff_and_forwards_it(tmp_path):
    ws, run = _run(tmp_path, [
        {"final": "本轮把 X 推到了 Y",
         "notify": {"to": "F", "summary": "交给 F：X 的族构造证据",
                    "body": "## 我做了什么\n扫了 n≤12。\n## 依据\nexp:0002\n## 要你做什么\n"
                            "判定 n=14。\n## 我卡在哪\n界推不动。",
                    "refs": []}},
    ])
    assert run.stop_reason == "final", run.to_dict()
    assert run.notify_rejections == 0, run.to_dict()
    assert run.handoffs == ["0000"], run.to_dict()
    rows = MS.rows(ws)
    assert [r["id"] for r in rows] == ["0000"], rows
    assert rows[0]["to"] == "F" and rows[0]["summary"] == "交给 F：X 的族构造证据", rows[0]
    # 脚本代为转发：收件人收件箱里有那条带编号 + 一句话的留言
    msgs, problems = read_messages(ws, "F", sid="n1")
    assert not problems, problems
    body = "\n".join(str(m.get("body") or "") for m in msgs)
    assert "[手稿 0000]" in body and "交给 F：X 的族构造证据" in body, msgs
    # 读数落在这一趟的记录里（谁交给了谁、哪一份）
    assert run.steps[-1].result.get("notify_handoff", {}).get("id") == "0000", run.steps[-1]


def test_the_conductor_is_exempt_because_its_final_goes_to_the_user(tmp_path):
    """边界：主控 M 的 `final` 是给用户的回复 ⇒ 免填（用户原话"向用户回复不搞这种操作"）。"""
    ws, run = _run(tmp_path, [{"final": "给用户的汇报：本轮做完三件事"}], role="M")
    assert run.stop_reason == "final", run.to_dict()
    assert run.notify_rejections == 0 and run.handoffs == [], run.to_dict()
    assert MS.rows(ws) == [], MS.rows(ws)


# ============================================================ 演练 2：不带 notify ⇒ 打回重填

def test_e4_2_a_final_without_notify_is_bounced_not_autofilled(tmp_path):
    """打回那一步是 `invalid`（不是"框架替它写"）：警告里四件事齐全，账本一行都不许有。"""
    ws, run = _run(tmp_path, [
        {"final": "我做完了"},                     # ① 不带 notify ⇒ 打回
        {"final": "我做完了",
         "notify": {"to": "D", "summary": "交给 D", "body": "正文"}},   # ② 改对了 ⇒ 收工
    ])
    assert run.stop_reason == "final", run.to_dict()
    assert run.notify_rejections == 1, run.to_dict()
    bad = run.steps[0]
    assert bad.shape == "invalid" and bad.problem, bad.to_dict()
    warn = bad.problem
    # 四件事：① 命中字段 ② 正例 ③ 反例 ④ 只改这一个字段
    assert "命中字段" in warn and "正例" in warn and "反例" in warn, warn
    assert "只改这一个字段" in warn, warn
    assert "notify" in warn, warn
    # 打回不代填、也不丢结论：账本只有"改对那一次"写下的那一行
    assert [r["id"] for r in MS.rows(ws)] == ["0000"], MS.rows(ws)
    assert "我做完了" in run.final, run.final


def test_a_run_that_never_fills_notify_stops_with_no_notify(tmp_path):
    """连续 3 次不填 ⇒ `stop_reason=\"no_notify\"`，不代填，但它自己的结论照原样留着。"""
    ws, run = _run(tmp_path, [{"final": "我第一次收工"}, {"final": "我第二次收工"},
                              {"final": "我第三次收工"}, {"final": "第四次"}])
    assert run.stop_reason == "no_notify", run.to_dict()
    assert run.notify_rejections == 3, run.to_dict()
    assert MS.rows(ws) == [], "不代填：账本里一份都不许凭空出现"
    assert "我第一次收工" not in run.final      # 最后一次的结论才是它要给的那份
    assert "我第三次收工" in run.final, run.final
    assert "没有留下交接手稿" in run.final, run.final
    assert [s.shape for s in run.steps] == ["invalid", "invalid", "invalid"], \
        [s.shape for s in run.steps]


def test_the_bounce_is_counted_and_visible_in_the_run_record(tmp_path):
    """读数可见：`notify_rejections` 进 `to_dict()`（"被打回几次"必须能查）。"""
    _ws, run = _run(tmp_path, [{"final": "没填"}, {"final": "还是没填"},
                               {"final": "改对了", "notify": {"to": "ALL", "summary": "广播",
                                                              "body": "正文"}}])
    assert run.notify_rejections == 2, run.to_dict()
    assert run.to_dict()["notify_rejections"] == 2, run.to_dict()
    assert run.to_dict()["handoffs"] == ["0000"], run.to_dict()


# ============================================================ 演练 3：带错字段 ⇒ 点名 + 反思

def test_e4_3_a_wrong_field_is_named_and_the_second_bounce_demands_reflection(tmp_path):
    """带错字段：第一次点名那个字段；连续第二次多一句"先说明你上一次为什么没按格式填"。"""
    _ws, run = _run(tmp_path, [
        {"final": "做完了", "notify": {"to": "D", "body": "缺 summary"}},       # ① 缺字段
        {"final": "做完了", "notify": {"to": "Z", "summary": "s", "body": "b"}},  # ② 坏收件人
        {"final": "做完了", "notify": {"to": "D", "summary": "s", "body": "b"}},  # ③ 改对
    ])
    first, second = run.steps[0].problem, run.steps[1].problem
    assert "notify.summary" in first, first
    assert "反思" not in first and "先说明你上一次" not in first, first
    assert "notify.to" in second, second
    assert "先说明你上一次为什么没按格式填" in second, second
    assert run.stop_reason == "final" and len(run.steps) == 3, run.to_dict()


def test_an_unknown_field_in_notify_is_named():
    """拼错的字段要当场点名（静默忽略会让它与"没填"长得一样）。"""
    problem = notify_shape_problem({"to": "D", "summry": "拼错了", "body": "b"})
    assert "不认识的字段" in problem and "summry" in problem, problem


def test_a_dangling_ref_is_bounced_before_the_handoff_is_written(tmp_path):
    """`refs` 悬空 ⇒ 打回（写入期同一份判据），账本不许留下半成品。"""
    ws, run = _run(tmp_path, [
        {"final": "做完了", "notify": {"to": "D", "summary": "引了 0009", "body": "b",
                                       "refs": ["0009"]}},
        {"final": "改成不引了", "notify": {"to": "D", "summary": "不引了", "body": "b"}},
    ])
    assert "0009" in run.steps[0].problem or "悬空" in run.steps[0].problem, \
        run.steps[0].problem
    assert [r["id"] for r in MS.rows(ws)] == ["0000"], MS.rows(ws)
    assert MS.rows(ws)[0]["summary"] == "不引了", MS.rows(ws)


def test_the_shape_decoder_passes_notify_through_and_the_gate_validates_it():
    """解码层只认形状（`final` 认出来了就把 notify 原样带过）；校验在 `_notify_gate` 一处。

    为什么校验不放解码层：打回要附"四件事"的警告，而警告只在"被打回"这个上下文里生成
    （它需要角色与"连续第几次"）。两份措辞必然分家 —— 分家之后模型看到的警告就取决于
    它是被哪一层拒的（同一个错误两种说法）。
    """
    from agentflow.agent_loop import _shape_of

    shape, payload, problem = _shape_of({
        "final": "结论", "evidence": ["exp:0002"],
        "notify": {"to": "all", "summary": "广播一句", "body": "正文", "refs": ["0000"]}})
    assert (shape, problem) == ("final", ""), (shape, problem)
    assert payload["notify"]["to"] == "all", payload          # 原样带过（归一在写入时做）
    from agentflow.agent_loop import clean_notify
    assert clean_notify(payload["notify"])["to"] == "ALL", clean_notify(payload["notify"])
    shape, _p, problem = _shape_of({"final": "结论", "notify": {"to": "D"}})
    assert (shape, problem) == ("final", ""), (shape, problem)  # 形状对（缺字段由闸门判）


def test_the_notify_requirement_is_documented_in_the_loop_protocol():
    """提示词与判据同源：`LOOP_PROTOCOL` 里必须写着 "notify" 是强制项（否则模型无从知道）。"""
    from agentflow import agent_prompts as AP

    text = AP.LOOP_PROTOCOL
    assert "notify" in text and "强制" in text and "不代填" in text, text
    assert "no_notify" in text, "停止理由也要写进协议（不然被停了不知道为什么）"
    assert AgentLoop.max_notify_rejections == 3, AgentLoop.max_notify_rejections
