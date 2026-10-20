"""能互动：问用户、等回答、以及"没答"不许被当成默许（离线，替身模型）。

## 这一组守什么

"能互动"在提示词里写多少句都不算数，必须有一条真实的路：问题送达人面前、回答带回来、
等不到就是等不到。三条纪律各配一条判据：

1. 问到就带回来：回答进下一步的 prompt，模型据此改做法；
2. 等不到落成 `user_no_answer`：它是"没查成"，不是"用户同意"；而且这条结论要出现在
   下一步的 prompt 里（否则模型会以为问了就等于批了）；
3. 迟到的回答不丢：超时之后用户才答的那一句，下一次运行照样看得到。
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any

from agentflow import sessions as SS
from agentflow import userio as U
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

LOOPS: dict[tuple[str, str], dict[str, Any]] = {}


class ScriptedGateway:
    """照剧本回答的替身模型；可以在第 n 次调用时做一件外部事件（这里用来扮用户）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str], *, on_call: Any = None) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.on_call = on_call

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        self.systems.append(str(system or ""))
        if self.on_call is not None:
            self.on_call(len(self.prompts))
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 4, "tokens_out": 4,
                                  "error_detail": "", "error_kind": ""})()


def _ws(tmp_path: pathlib.Path) -> tuple[Store, Any, Conductor, pathlib.Path]:
    st = Store(tmp_path / "ws")
    st.init()
    backend = LlmBackend(inner=LocalBackend({}), loops=LOOPS, session_root=st.root,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=st.root,
                                                           gateway=None, sid="t"),
                         store=st, sid="t")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    registry = build_registry(store=st, conductor=cond, workspace_root=str(st.root)).registry
    backend.registry = registry
    return st, registry, cond, st.root


def _run(tmp_path: pathlib.Path, role: str, replies: list[str], *, on_call: Any = None,
         task: str = "干活", max_steps: int = 4, user_timeout_sec: float = 0.0,
         registry_bundle: Any = None) -> tuple[Any, ScriptedGateway, pathlib.Path]:
    if registry_bundle is None:
        st, registry, cond, root = _ws(tmp_path)
    else:
        st, registry, cond, root = registry_bundle
    gw = ScriptedGateway(replies, on_call=on_call)
    run = run_role(role, task, store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role=role, session_root=root, gateway=gw, price=(0.0, 0.0),
                                sid="t"), workspace_root=str(root), sid="t",
                   max_steps=max_steps, from_env=False)
    return run, gw, root


def test_the_question_is_durable_and_the_answer_comes_back(tmp_path: pathlib.Path):
    """正控：问题落进用户频道，回答被带回，模型在下一步看到了它。

    这里用一条真等的路（timeout 2 秒）而不是"先答后问"的技巧：
    扮用户的线程盯着待答清单，看到问题就答 —— 这正是人在终端里会做的事，
    而且它顺带证明"提问真的写进了频道"（否则线程永远看不到）。
    """
    st, registry, cond, root = _ws(tmp_path)
    answered: dict[str, str] = {}

    def be_the_user() -> None:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            pend = U.pending_questions(root, sid="t")
            if pend:
                answered["qid"] = pend[0].qid
                U.answer_question(root, qid=pend[0].qid, answer="用 n<=5 的口径", sid="t")
                return
            time.sleep(0.05)

    import threading

    user = threading.Thread(target=be_the_user, daemon=True)
    user.start()
    gw = ScriptedGateway([json.dumps({"ask_user": {"question": "口径用哪个？",
                                                   "options": ["n<=5", "全体"],
                                                   "timeout_sec": 2}},
                                     ensure_ascii=False),
                          json.dumps({"final": "按用户口径继续", "evidence": []},
                                     ensure_ascii=False)])
    run = run_role("M", "把口径定下来", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0),
                                sid="t"), workspace_root=str(root), sid="t", max_steps=3,
                   from_env=False)
    user.join(timeout=2.0)
    step = run.steps[0]
    assert step.shape == "ask_user" and step.result.get("ok") is True, step.result
    assert step.result.get("answer") == "用 n<=5 的口径", step.result
    assert "n<=5" in gw.prompts[1], "回答没有进下一步的 prompt"
    events, _ = SS.read_session(root, sid="t")
    assert any(e.get("kind") == "user_question" for e in events), "问题没有落档"
    assert any(e.get("kind") == "user_answer" for e in events), "回答没有落档"
    assert answered.get("qid") == step.result.get("asked"), (answered, step.result)


def test_no_answer_is_not_permission(tmp_path: pathlib.Path):
    """负控（三态 + 「停着」）：问不到回答 ⇒ 这一趟停在等，而且一步模型都不再发。

    ## 这条判据为什么改了（2026-10-03 的口径变更）

    旧判据断言的是"下一步的 prompt 里要写明这是 `user_no_answer`（没查成）" ——
    它守的是"超时之后继续跑"那一版的行为：超时是「这一步」的结论，循环照旧往下走。
    用户 2026-10-03 裁定「就停着」之后，"继续跑"这件事本身被废掉了，
    于是旧断言里的 `gw.prompts[1]` 根本不存在（索引越界）—— 那不是判据变松了，
    是它所描述的那条路径不再存在。

    新的判据把同一件事（"没答不是默许"）钉在更硬的地方：这一趟停成
    `waiting_for_user`、记下 `waiting_for`、「并且没有再发模型请求」
    （停了之后还发请求 = 又在替用户做决定了，那正是要挡的形态）。
    """
    st, registry, cond, root = _ws(tmp_path)
    gw = ScriptedGateway([json.dumps({"ask_user": {"question": "要不要继续？",
                                                   "timeout_sec": 0}},
                                     ensure_ascii=False),
                          json.dumps({"final": "按最保守的做法继续", "evidence": []},
                                     ensure_ascii=False)])
    run = run_role("M", "问一下再决定", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0),
                                sid="t"), workspace_root=str(root), sid="t", max_steps=3,
                   from_env=False)
    step = run.steps[0]
    assert step.result.get("ok") is False, step.result
    assert step.result.get("problem") == U.NO_ANSWER, step.result
    assert step.result.get("state") == "pending", step.result
    assert "不许把它当成用户同意" in str(step.result.get("note") or ""), step.result
    assert run.stop_reason == "waiting_for_user", run.to_dict()
    assert run.waiting_for == step.result.get("asked"), run.to_dict()
    assert len(gw.prompts) == 1, "停在等之后又发了模型请求（停着 = 不烧钱）"
    assert run.final.startswith("停在等"), run.final


def test_a_late_reply_still_reaches_the_next_run(tmp_path: pathlib.Path):
    """正控（迟到的回答不丢）：超时之后用户才答，下一次运行照样看得到。"""
    st, registry, cond, root = _ws(tmp_path)
    # 第一次运行：问、超时
    run1, gw1, _ = _run(tmp_path, "M", [json.dumps({"ask_user": {"question": "继续吗？",
                                                                 "timeout_sec": 0}},
                                                   ensure_ascii=False),
                                        json.dumps({"final": "先停", "evidence": []},
                                                   ensure_ascii=False)],
                        registry_bundle=(st, registry, cond, root))
    assert run1.steps[0].result.get("problem") == U.NO_ANSWER
    qid = str(run1.steps[0].result.get("asked"))
    assert qid, run1.steps[0].result
    # 用户迟到了：现在才答
    assert U.answer_question(root, qid=qid, answer="继续，但只做一轮", late=True, sid="t") == ""
    # 第二次运行：这段回答必须在 prompt 里
    # （2026-10-21 起 `{{user_replies}}` 那一格从 system 挪进了开场那条 user 消息 ——
    #  它是一趟的事实，进 system 就把整条前缀绑死在这一趟上。信息没丢，只是换了位置。）
    run2, gw2, _ = _run(tmp_path, "M", [json.dumps({"final": "照办", "evidence": []},
                                                    ensure_ascii=False)],
                        registry_bundle=(st, registry, cond, root))
    assert "只做一轮" in gw2.prompts[0], "迟到的回答没有进提示词"
    assert "迟到送达" in gw2.prompts[0], "迟到的标记没写出来"
    assert "只做一轮" not in gw2.systems[0], "回答还在 system 里 ⇒ 前缀跨不过 run"
    assert run2.stop_reason == "final"


def test_answers_are_scoped_to_the_role_that_asked(tmp_path: pathlib.Path):
    """负控（不许串味）：别人的回答不许出现在我的提示词里。"""
    root = tmp_path / "ws"
    root.mkdir()
    # 先问（超时 0），再答：这样问题真的登记在案，回答才有归属
    c1 = U.ask_user(root, role="C", question="C 的第一个问题？", timeout_sec=0, sid="t")
    U.answer_question(root, qid=c1.qid, answer="这是给 C 的", sid="t")
    U.ask_user(root, role="D", question="D 的问题？", timeout_sec=0, sid="t")
    from agentflow.agent_prompts import user_replies_digest
    d_text = user_replies_digest(U.read_replies(root, role="D", sid="t"))
    c_text = user_replies_digest(U.read_replies(root, role="C", sid="t"))
    assert "这是给 C 的" not in d_text, d_text
    assert "这是给 C 的" in c_text, c_text


def test_pending_questions_surface_what_is_waiting(tmp_path: pathlib.Path):
    """正控（给人看的入口）：待答清单列出还没回答的问题，答完就消失。"""
    root = tmp_path / "ws"
    root.mkdir()
    out = U.ask_user(root, role="M", question="交付标准是哪一档？", timeout_sec=0, sid="t")
    pend = U.pending_questions(root, sid="t")
    assert [q.qid for q in pend] == [out.qid], pend
    assert "交付标准" in pend[0].text
    U.answer_question(root, qid=out.qid, answer="第二档", sid="t")
    assert U.pending_questions(root, sid="t") == []


def test_ask_user_shape_rejects_a_question_without_text(tmp_path: pathlib.Path):
    """负控（形状判据）：没有 question 的 ask_user 当场被判非法，不当成一次提问。"""
    st, registry, cond, root = _ws(tmp_path)
    gw = ScriptedGateway([json.dumps({"ask_user": {"options": ["A"]}}, ensure_ascii=False),
                          json.dumps({"final": "改主意", "evidence": []}, ensure_ascii=False)])
    run = run_role("M", "空问题", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0),
                                sid="t"), workspace_root=str(root), sid="t", max_steps=3,
                   from_env=False)
    assert run.steps[0].shape == "invalid" and "question" in run.steps[0].problem, run.steps[0]
    assert U.pending_questions(root, sid="t") == [], "非法提问不许落进待答清单"
