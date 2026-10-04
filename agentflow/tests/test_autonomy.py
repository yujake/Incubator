"""自主轮次与阶段汇报：跑一程、按节拍向用户报账、以及四条停止判据。

## 这一组测试要守住什么

`agentflow.autonomy` 把"跑一次循环"接成"跑一程"。它的价值全在几件容易退化的
工程事实上，所以每一条都单独钉一个用例：

- 阶段汇报真的发到了公共频道（不是只落一条事件、也不是只有提示词里的请求）；
- 节拍是真的（每 N 轮一次，且最后一轮必发 —— 否则提前停下的那些轮次没有交代）；
- 停止判据在"花掉钱、跑坏数据"之前生效（预算为零时一次模型调用都不许发生）；
- 停止开关与用户的一句话都真的能叫停，而不只是被写进提示词；
- 上一轮的结论真的进了下一轮的任务（否则多轮退化成把同一件事问 N 遍）；
- 发不出去这件事被记下来而不是被吞掉（三态纪律：没发成不许与发成了同形）。

替身模型与 `tests/test_agent_faculties.py` 同款：`complete(prompt, *, scope, system)`。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import autonomy
from agentflow import sessions as SS
from agentflow import userio
from agentflow.agent_loop import read_messages
from agentflow.autonomy import STOP_TOKEN, run_autonomous
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry


class ScriptedGateway:
    """照剧本回答的替身模型；可以在第 n 次调用时做一件"外部事件"（模拟运行中叫停）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str], *, on_call: Any = None) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.on_call = on_call

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        """记下这一次的 prompt，按次序回一句；剧本用完就重复最后一句。"""
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call(len(self.prompts))
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 5, "tokens_out": 5,
                                  "error_detail": "", "error_kind": ""})()


class ExplodingGateway:
    """被调用就抛的替身：用来证明某条判据让模型调用根本没有发生。"""

    spec = type("Spec", (), {"model": "boom", "api_key": "fake"})()

    def complete(self, *a: Any, **kw: Any) -> Any:
        """被调用即说明守卫失效（调用方会以这次抛错为红）。"""
        raise AssertionError("这条路上不该发起模型调用")


def _ws(tmp_path: pathlib.Path) -> tuple[Store, Any, pathlib.Path]:
    """造一个临时工作区 + 真工具层（角色不接线：模型驱动的动作走替身）。"""
    st = Store(tmp_path / "ws")
    st.init()
    cond = Conductor(st, backend=LocalBackend({}))
    registry = build_registry(store=st, conductor=cond, workspace_root=str(st.root)).registry
    return st, registry, st.root


def _finals(*texts: str) -> list[str]:
    """把若干句结论包成 `final` 形状的替身回复（省得每处都写一遍 json.dumps）。

    `notify` 是协议的一部分（`draft/39` §3.2：除主控外收工必须留一份交接手稿）——
    替身回复也要按协议说，否则被测的就不是"这一轮做完了"，而是"被强制 notify 打回"。
    """
    return [json.dumps({"final": t, "evidence": [],
                        "notify": {"to": "M", "summary": t, "body": f"## 结论\n{t}\n"}},
                       ensure_ascii=False) for t in texts]


def _events(root: pathlib.Path, sid: str) -> list[dict[str, Any]]:
    """读这段会话的全部事件（坏行会让本函数直接红：判据不许踩在坏记录上）。"""
    events, problems = SS.read_session(root, sid=sid)
    assert not problems, problems
    return events


def _report_rounds(events: list[dict[str, Any]]) -> list[int]:
    """会话里 `autonomy_report` 事件点名的轮次（按先后）。"""
    return [int(e["round"]) for e in events if e.get("kind") == "autonomy_report"]


def _public_messages(root: pathlib.Path, *, reader: str, sid: str) -> list[dict[str, Any]]:
    """第三方收件箱里的公共频道消息（读者不能是发言人，否则看不到自己的话）。"""
    messages, problems = read_messages(root, reader, sid=sid)
    assert not problems, problems
    return [m for m in messages if m["channel"] == "public"]


def test_three_rounds_report_each_round_and_stop_on_rounds(tmp_path: pathlib.Path):
    """三轮回合每轮一份阶段汇报：公共频道收得到、事件逐轮落、以 rounds 收工。

    回归的是：汇报只发一次、只落事件不发消息、或轮次没跑满 —— 任一条都会让
    "按节拍报账"退化成提示词里的一句请求（说了不等于做了）。
    """
    st, registry, root = _ws(tmp_path)
    gw = ScriptedGateway(_finals("第 1 轮结论", "第 2 轮结论", "第 3 轮结论"))
    run = run_autonomous("D", "把这件事做完", store=st, registry=registry, gateway=gw,
                         rounds=3, max_steps=3, sid="t")

    assert run.rounds_done == 3 and run.stop_reason == "rounds", run.to_dict()
    assert [r.index for r in run.reports] == [1, 2, 3]
    assert all(r.report_sent == "" for r in run.reports), [r.report_sent for r in run.reports]
    assert [r.final for r in run.reports] == ["第 1 轮结论", "第 2 轮结论", "第 3 轮结论"]

    public = _public_messages(root, reader="H", sid="t")
    assert len(public) == 3, [m["subject"] for m in public]
    assert all(m["from"] == "D" and m["to"] == autonomy.PUBLIC for m in public)

    body = public[0]["body"]
    for needle in ("第 1/3 轮", "本轮结论", "本轮唤起过", "本轮留言给", "剩余预算"):
        assert needle in body, (needle, body)

    events = _events(root, sid="t")
    assert _report_rounds(events) == [1, 2, 3]
    assert [e["index"] for e in events if e.get("kind") == "autonomy_round"] == [1, 2, 3]


def test_report_every_two_reports_on_the_beat_and_at_the_end(tmp_path: pathlib.Path):
    """report_every=2 且跑三轮：只发第 2 轮与最后一轮（第 3 轮），不多不少。

    回归的是：把"每 N 轮"实现成"每次都发"（刷屏），或者最后一轮因为不在节拍上
    而不发 —— 后者会让提前停下的那些轮次永远没有交代。
    """
    st, registry, root = _ws(tmp_path)
    gw = ScriptedGateway(_finals("第 1 轮结论", "第 2 轮结论", "第 3 轮结论"))
    run = run_autonomous("D", "把这件事做完", store=st, registry=registry, gateway=gw,
                         rounds=3, report_every=2, max_steps=3, sid="t")

    assert run.rounds_done == 3 and run.stop_reason == "rounds", run.to_dict()
    assert _report_rounds(_events(root, sid="t")) == [2, 3]
    assert len(_public_messages(root, reader="H", sid="t")) == 2
    assert run.reports[0].report_sent != "", "第 1 轮不在节拍上，必须写下'为什么没报'"
    assert run.reports[1].report_sent == "" and run.reports[2].report_sent == ""


def test_an_exhausted_budget_runs_no_round_and_calls_no_model(tmp_path: pathlib.Path):
    """usd_budget 已耗尽：零轮、以 budget 停，而且一次模型调用都不发起。

    回归的是：预算判据挪到"跑完一轮之后"（或直接交给每一轮各自的缝）——
    那时钱已经花了，而"到顶就不再请求"这条纪律在整程上就失效了。
    """
    st, registry, root = _ws(tmp_path)
    run = run_autonomous("D", "别花钱", store=st, registry=registry, gateway=ExplodingGateway(),
                         rounds=3, usd_budget=0.0, sid="t")

    assert run.rounds_done == 0 and run.reports == [], run.to_dict()
    assert run.stop_reason == "budget", run.to_dict()
    events = _events(root, sid="t")
    assert not [e for e in events if e.get("kind") in ("autonomy_round", "autonomy_report")], (
        "一轮都没跑，会话里不该有轮次或汇报事件")


def test_a_stop_file_present_before_the_run_stops_it_immediately(tmp_path: pathlib.Path):
    """停止开关先于运行就存在：零轮、以 stop_file 停，且不碰模型。

    回归的是：人工开关只在"跑完一轮之后"才被看 —— 那时该停的那一轮已经跑过了，
    而人工叫停的整个意义就是"别再往下跑"。
    """
    st, registry, root = _ws(tmp_path)
    switch = root / "STOP"
    switch.write_text("停", encoding="utf-8")
    run = run_autonomous("D", "干活", store=st, registry=registry, gateway=ExplodingGateway(),
                         rounds=3, stop_file=switch, sid="t")

    assert run.rounds_done == 0 and run.stop_reason == "stop_file", run.to_dict()
    assert not [e for e in _events(root, sid="t") if e.get("kind") == "autonomy_round"]


def test_a_stop_file_created_mid_round_stops_after_that_round(tmp_path: pathlib.Path):
    """运行中有人放下停止开关：这一轮跑完就停（以 stop_file 收工），只跑一轮。

    回归的是：开关只在进程启动时读一次（那样运行中叫停要等一程跑完才生效），
    或者反过来在轮中被砍掉 —— 半截运行会让审计面出现一条没有终态的轮次。
    """
    st, registry, root = _ws(tmp_path)
    switch = root / "STOP"

    def on_call(n: int) -> None:
        """第 1 次模型调用之后放下停止开关（模拟运行中的人工叫停）。"""
        if n == 1:
            switch.write_text("停", encoding="utf-8")

    gw = ScriptedGateway(_finals("第 1 轮做完了"), on_call=on_call)
    run = run_autonomous("D", "干活", store=st, registry=registry, gateway=gw, rounds=3,
                         stop_file=switch, sid="t")

    assert run.rounds_done == 1 and run.stop_reason == "stop_file", run.to_dict()
    assert run.reports[0].stop_reason == "final", "这一轮必须是正常收工的，不是被砍断的"


def test_a_user_answer_with_stop_addressed_to_the_role_stops_the_run(tmp_path: pathlib.Path):
    """用户答了一句带 STOP 的话给这个角色：零轮、以 user_stop 停，且不碰模型。

    回归的是：用户的叫停只写在提示词里"请模型自觉" —— 而"停"这件事必须有一条
    不经过模型的实现，否则用户说的话在与不在，只取决于模型这一轮怎么想。
    """
    st, registry, root = _ws(tmp_path)
    SS.append(root, {"kind": "user_question", "qid": "q0001", "role": "D",
                     "text": "还要继续吗？"}, sid="t")
    assert userio.answer_question(root, qid="q0001", answer=f"{STOP_TOKEN} 先停一停",
                                  sid="t") == ""

    run = run_autonomous("D", "接着做", store=st, registry=registry, gateway=ExplodingGateway(),
                         rounds=3, sid="t")

    assert run.rounds_done == 0 and run.stop_reason == "user_stop", run.to_dict()
    assert any(STOP_TOKEN in n for n in run.notes), run.notes


def test_a_stop_answer_addressed_to_another_role_does_not_stop_this_one(tmp_path: pathlib.Path):
    """负控：写给别人的 STOP 不算叫停本角色（否则对一个人说的话会停掉整队）。

    回归的是：停止判据只看"有没有 STOP"，不看这句话是对谁说的。
    """
    st, registry, root = _ws(tmp_path)
    SS.append(root, {"kind": "user_question", "qid": "q0001", "role": "E",
                     "text": "E 这边还要继续吗？"}, sid="t")
    assert userio.answer_question(root, qid="q0001", answer=f"{STOP_TOKEN} 先停",
                                  sid="t") == ""

    gw = ScriptedGateway(_finals("D 照常做完了"))
    run = run_autonomous("D", "接着做", store=st, registry=registry, gateway=gw,
                         rounds=1, max_steps=2, sid="t")

    assert run.rounds_done == 1 and run.stop_reason == "rounds", run.to_dict()
    assert run.reports[0].final == "D 照常做完了"


def test_the_next_round_task_carries_the_previous_conclusion(tmp_path: pathlib.Path):
    """第 N>1 轮的任务里带着上一轮的结论与"还差什么"（断言替身记下的 prompt）。

    回归的是：每一轮都把原始任务原样重发 —— 于是"自主多轮"退化成"把同一件事
    问 N 遍"，上一轮已经得出的结论被丢掉，模型只能从头再来。
    """
    st, registry, root = _ws(tmp_path)
    gw = ScriptedGateway(_finals("第一轮结论：约束只在 n<=5 时成立", "第二轮收工"))
    run = run_autonomous("D", "把约束定下来", store=st, registry=registry, gateway=gw,
                         rounds=2, max_steps=3, sid="t")

    assert run.rounds_done == 2 and run.stop_reason == "rounds", run.to_dict()
    assert len(gw.prompts) >= 2, "两轮至少要各发一次模型调用"
    assert "第一轮结论：约束只在 n<=5 时成立" in gw.prompts[1], gw.prompts[1][-600:]
    assert "还差什么" in gw.prompts[1]
    assert "把约束定下来" in gw.prompts[1], "原始任务不许被上一轮的块顶掉"


def test_a_long_previous_conclusion_is_clipped_before_the_next_round(tmp_path: pathlib.Path):
    """上一轮结论过长时先截断再进下一轮的任务（并写明原文多少字）。

    回归的是：把整段长结论原样塞进下游 prompt —— 于是轮次越多、prompt 越胖，
    真正要紧的"原始任务"反而被挤到看不见。
    """
    st, registry, root = _ws(tmp_path)
    long_final = "结论：" + "这是一段很长的推理过程。" * 40
    gw = ScriptedGateway(_finals(long_final, "收工"))
    run = run_autonomous("D", "接着做", store=st, registry=registry, gateway=gw,
                         rounds=2, max_steps=2, sid="t")

    assert run.reports[0].final.endswith("已截断）"), run.reports[0].final
    assert "已截断）" in gw.prompts[1]
    assert len(run.reports[0].final) < len(long_final)


def test_a_failed_report_publish_is_reported_and_noted(tmp_path: pathlib.Path, monkeypatch: Any):
    """汇报发不出去：report_sent 写下原因、notes 留下异常，而审计事件照样落。

    回归的是：把 send_message 返回的问题丢掉 —— 于是"用户到底收到没有"这件事
    在返回值里永远看不出，调用方只能自己去翻会话记录才能发现用户根本没收到。
    """
    st, registry, root = _ws(tmp_path)

    def refuse(*a: Any, **kw: Any) -> tuple[str, str]:
        """替身 send_message：永远发不出去（返回一个可读的问题串）。"""
        return "", "会话写不进去：磁盘满了"

    monkeypatch.setattr(autonomy, "send_message", refuse)
    gw = ScriptedGateway(_finals("做完了"))
    run = run_autonomous("D", "干活", store=st, registry=registry, gateway=gw,
                         rounds=1, max_steps=2, sid="t")

    assert run.rounds_done == 1, run.to_dict()
    assert run.reports[0].report_sent != "", "发失败必须写在 report_sent 里（空串 = 发出去了）"
    assert any("磁盘满了" in n for n in run.notes), run.notes
    events = _events(root, sid="t")
    published = [e for e in events if e.get("kind") == "autonomy_report"]
    assert len(published) == 1 and "做完了" in str(published[0].get("body")), (
        "发布失败不代表审计面可以缺一条：事件仍要落，并写明当时想报的是什么")


def test_the_min_usd_threshold_skips_a_beat_that_cost_too_little(tmp_path: pathlib.Path):
    """两次汇报之间花销不够就跳过这一拍，但最后一轮照样报（收工要有交代）。

    回归的是：节拍判据被实现成"每 N 轮无条件发" —— 一程很便宜也会刷出一堆
    没有信息量的汇报，把真正的阶段汇报淹掉。
    """
    st, registry, root = _ws(tmp_path)
    gw = ScriptedGateway(_finals("第 1 轮结论", "第 2 轮结论", "第 3 轮结论"))
    # 每次调用 5 个输入 token、单价每百万 1 美元 ⇒ 每次恰好 5.0 美元（确定性算术）。
    seam = LlmSeam(role="D", session_root=root, gateway=gw, price=(1_000_000.0, 0.0), sid="t")
    run = run_autonomous("D", "跑一程", store=st, registry=registry, seam=seam, rounds=3,
                         report_every=1, min_usd_between_reports=10.0, max_steps=2, sid="t")

    assert run.rounds_done == 3 and run.stop_reason == "rounds", run.to_dict()
    assert run.spend["usd"] == 15.0 and run.spend["calls"] == 3, run.spend
    assert _report_rounds(_events(root, sid="t")) == [2, 3]
    assert run.reports[0].report_sent != "", "第 1 轮没到间隔，必须写下'为什么没报'"
    assert run.reports[2].report_sent == "", "最后一轮不受间隔限制：收工要有交代"
