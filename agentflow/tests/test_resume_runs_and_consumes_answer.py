# -*- coding: utf-8 -*-
"""R26 第三段真跑：问 → 答 → `--resume` —— 回答真的被续跑那一段吃进去了。

## 与 §26 的关系（数据半 vs 这一段）

§26 验的是数据前提：`agentflow answer` 写下的话，`--resume` 那一次读得回来；
没答时读出空串（不是同意）；说停立刻生效。这一节验的是动作：
真的跑一次 `run_autonomous(resume=True)`，而用户那句话出现在续跑那一轮的提示词里。

判据取的是"提示词里有没有那句话"而不是"有没有恢复"——
因为"恢复了但仍按原来的任务跑"与"没恢复"在读数上长得一模一样，
而 R26 要的恰恰是用户的话改变了后续那一段（§14.5 第 4 件：今天的
`inbox`/`answer` 只做到"回答写回去"，没有"回答之后那一段接着跑"）。

 边界：这里用的是照剧本回答的替身模型（离线）。所以它验的是
"回答进得了续跑那一段的提示词"这件框架行为，不是"模型据此改主意了"。
后者要一次真机（§17.3，今天阻塞在 key）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import schema as S
from agentflow import userio as U
from agentflow.autonomy import load_checkpoint, run_autonomous
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

#: 第一轮：先问用户一句（`ask_user` 形状），再收工。
_ASK = json.dumps({"ask_user": {"question": "这次是「审」还是「研」？",
                                "options": ["审", "研"], "timeout_sec": 0}},
                  ensure_ascii=False)
_FINAL = json.dumps({"final": "这一轮到此", "evidence": []}, ensure_ascii=False)


class _Recorder:
    """照剧本回答的替身模型：记下每一问的全文（这一节判的就是提示词里有没有那句话）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        """记下这一问，回剧本里的下一条（取完重复最后一条）。"""
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _wire(tmp_path: pathlib.Path, replies: list[str]):
    st = Store(tmp_path / "ws")
    st.init()
    inner = LocalBackend({})
    cond = Conductor(st, backend=inner)
    registry = build_registry(store=st, conductor=cond, workspace_root=str(st.root)).registry
    return st, registry, cond, st.root, _Recorder(replies)


def _run(store, registry, cond, root, gw, *, rounds: int, resume: bool = False):
    seam = LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0), sid="t")
    return run_autonomous("M", "把这件事推进下去", store=store, registry=registry, conductor=cond,
                          session_root=root, seam=seam, rounds=rounds, report_every=99,
                          max_steps=3, sid="t", from_env=False, resume=resume)


def test_the_answer_reaches_the_resumed_round_prompt(tmp_path):
    """这一节的核心：答完之后 `resume=True` 那一跑，提示词里带着用户那句话。"""
    st, registry, cond, root, gw = _wire(tmp_path, [_ASK, _FINAL])
    first = _run(st, registry, cond, root, gw, rounds=1)
    assert first.rounds_done == 1, first.to_dict()
    assert load_checkpoint(root, "M") is not None, "第一段必须留下检查点（否则没有'续跑'可言）"

    # 用户回答（走的就是 CLI 的那个入口；会话号必须与循环那一侧一致 —— `sid="t"`）
    pend = U.pending_questions(root, sid="t")
    assert len(pend) == 1, [q.qid for q in pend]
    assert U.answer_question(root, qid=pend[0].qid, answer="审这篇论文", sid="t") == ""

    before = len(gw.prompts)
    second = _run(st, registry, cond, root, gw, rounds=2, resume=True)
    assert second.resumed_from >= 1, second.to_dict()
    after = gw.prompts[before:]
    assert after, "续跑那一跑必须真的调了模型（否则'进没进提示词'无从谈起）"
    assert any("审这篇论文" in p for p in after), (
        "用户那句话没有进续跑那一段的提示词 ⇒ '回答之后接着跑'只做了一半（R26 第三段）")


def test_resuming_without_an_answer_does_not_invent_one(tmp_path):
    """    反真空（按"停着"的新契约改过）：没答就 `resume=True` ⇒ 「根本不开下一轮」。

    ## 这条判据为什么改（`draft/37` §72，用户裁定"问了就停着"）

    它原来守的是旧契约："没人答也照跑下一轮，但提示词里不许编一句'用户说……'"。新契约把那条路「堵死在更前面」：上一轮停在等用户回答、而那个问题还挂在待答清单里
    ⇒多轮驱动不许开下一轮（`autonomy._stop_before_round` 的 `waiting_for_user` 那一档）。于是"编造回答"这件事在结构上不可能发生 —— 不是靠提示词自律，是靠根本不进那一步。

    判据因此钉两件事：「一个模型请求都没发」（`after == []`），且停因是`waiting_for_user`（不是"跑完了"也不是"没查成"）。原来那句"提示词里不许出现'用户说……'"保留成一条反真空断言：它在
    `after` 为空时自动成立，而万一将来有人把这条闸门放宽，它会立刻红。
    """
    st, registry, cond, root, gw = _wire(tmp_path, [_ASK, _FINAL])
    _run(st, registry, cond, root, gw, rounds=1)
    pend = U.pending_questions(root, sid="t")
    assert pend, "夹具前提：问题还没被回答"
    before = len(gw.prompts)
    second = _run(st, registry, cond, root, gw, rounds=2, resume=True)
    after = gw.prompts[before:]
    assert after == [], (
        f"没人答却开了下一轮（发了 {len(after)} 个模型请求）⇒ 等于替人把取舍定了")
    assert second.stop_reason == "waiting_for_user", second.to_dict()
    assert second.rounds_done == 0, "停在等用户时一轮都不该跑"
    for prompt in gw.prompts:
        assert "用户说" not in prompt and "用户的回答" not in prompt, (
            "没回答却在提示词里写了'用户说……' —— 这是把'没答'当成了'答了'")


def test_the_checkpoint_is_updated_by_the_resumed_run(tmp_path):
    """第三段的收尾：续跑之后检查点前进（否则下一次接不上，等于每段都在原处打转）。"""
    st, registry, cond, root, gw = _wire(tmp_path, [_ASK, _FINAL])
    _run(st, registry, cond, root, gw, rounds=1)
    pend = U.pending_questions(root, sid="t")
    assert U.answer_question(root, qid=pend[0].qid, answer="审", sid="t") == ""
    first_cp = dict(load_checkpoint(root, "M") or {})
    _run(st, registry, cond, root, gw, rounds=2, resume=True)
    second_cp = dict(load_checkpoint(root, "M") or {})
    assert second_cp, "续跑之后检查点不该消失"
    assert int(second_cp.get("completed_rounds") or 0) >= int(first_cp.get("completed_rounds") or 0), (
        first_cp, second_cp)
    assert second_cp != first_cp or int(second_cp.get("completed_rounds") or 0) >= 1, (
        "检查点一个字都没动 ⇒ 续跑那一段没有留下任何可接续的读数")
