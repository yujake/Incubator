"""长时驱动的检查点与恢复：分段续跑、跨段预算、指纹不符要拒。

## 为什么这一组必须存在

`run_autonomous` 的一次调用可能要跑几十分钟（每轮好几次模型调用），被打断是常态。
没有检查点时"重跑"会把做过的事再做一遍 —— 而每一轮都可能写了数据、发了汇报。
这一组守四件事：

1. 检查点真的落盘，内容里带任务指纹与已完成轮数；
2. 恢复时只跑没做过的轮（不重跑、不重复汇报），并且如实报 `resumed_from`；
3. 跨段预算：上一段的花销并进预算口径（否则每段从 0 算，总额会超）；
4. 拿 A 任务的检查点续 B 任务必须被拒（混进度比不恢复更坏）；
   已完成全部轮次的检查点续跑要如实说"没有要做的事"。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import sessions as SS
from agentflow.autonomy import (checkpoint_path, load_checkpoint, run_autonomous,
                                save_checkpoint, task_fingerprint)
from agentflow.llmseam import LlmSeam
from agentflow.store import Store

REPLY = json.dumps({"final": "本轮结论：还差一条引理", "evidence": []}, ensure_ascii=False)


class ScriptedGateway:
    """照剧本回答的替身模型；记录被调用了几次（用来证明"没重跑"）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.calls += 1
        return type("Reply", (), {"ok": True, "text": REPLY, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _wire(tmp_path: pathlib.Path) -> tuple[Store, Any, Any, pathlib.Path, ScriptedGateway]:
    from agentflow.conductor import Conductor, LocalBackend
    from agentflow.tools import build_registry

    st = Store(tmp_path / "ws")
    st.init()
    backend = LocalBackend({})
    cond = Conductor(st, backend=backend)
    registry = build_registry(store=st, conductor=cond, workspace_root=str(st.root)).registry
    gateway = ScriptedGateway()
    return st, registry, cond, st.root, gateway


def _run(store: Store, registry: Any, cond: Any, root: pathlib.Path, gw: ScriptedGateway,
         *, rounds: int, resume: bool = False, task: str = "把这件事推进下去",
         usd_budget: float | None = None) -> Any:
    seam = LlmSeam(role="D", session_root=root, gateway=gw, price=(1.0, 1.0), sid="t",
                   usd_budget=usd_budget)
    return run_autonomous("D", task, store=store, registry=registry, conductor=cond,
                          session_root=root, seam=seam, rounds=rounds, report_every=99,
                          usd_budget=usd_budget, max_steps=2, sid="t", from_env=False,
                          resume=resume)


def test_the_checkpoint_lands_with_fingerprint_and_completed_rounds(tmp_path: pathlib.Path):
    """正控：跑两轮之后检查点里有任务指纹与已完成轮数（下一段据此续跑）。"""
    st, registry, cond, root, gw = _wire(tmp_path)
    run = _run(st, registry, cond, root, gw, rounds=2)
    assert run.rounds_done == 2 and run.resumed_from == 0, run.to_dict()
    path = checkpoint_path(root, "D")
    assert path.is_file(), "检查点没有落盘"
    data = load_checkpoint(root, "D")
    assert data is not None
    assert data["fingerprint"] == task_fingerprint("D", "把这件事推进下去")
    assert data["completed_rounds"] == 2 and data["rounds"] == 2
    assert run.checkpoint == str(path)


def test_resume_skips_the_completed_rounds(tmp_path: pathlib.Path):
    """正控（核心）：第一段跑 2 轮、第二段 resume 到 4 轮 ⇒ 只跑第 3、4 轮。"""
    st, registry, cond, root, gw = _wire(tmp_path)
    first = _run(st, registry, cond, root, gw, rounds=2)
    assert first.rounds_done == 2
    calls_after_first = gw.calls
    second = _run(st, registry, cond, root, gw, rounds=4, resume=True)
    assert second.resumed_from == 2, second.to_dict()
    assert second.rounds_done == 2, "第二段只该跑没做过的两轮"
    # 每一轮 = 一次 run_role = 至少一次模型调用；第二段的调用次数应当只对应两轮
    assert gw.calls - calls_after_first > 0
    events, _ = SS.read_session(root, sid="t")
    rounds_ev = [e for e in events if e.get("kind") == "autonomy_round"]
    assert len(rounds_ev) == 4, f"总共应当只跑 4 轮（不重跑）：{len(rounds_ev)}"
    assert any("不重跑" in n for n in second.notes), second.notes


def test_resume_refuses_a_different_task(tmp_path: pathlib.Path):
    """负控（核心）：拿 A 任务的检查点续 B 任务 ⇒ 拒，且一轮都不跑。"""
    st, registry, cond, root, gw = _wire(tmp_path)
    _run(st, registry, cond, root, gw, rounds=2)
    calls = gw.calls
    other = _run(st, registry, cond, root, gw, rounds=4, resume=True, task="换一件事做")
    assert other.stop_reason == "checkpoint_mismatch", other.to_dict()
    assert other.rounds_done == 0 and gw.calls == calls, "不一致时不许发起任何调用"
    assert any("指纹" in n for n in other.notes), other.notes


def test_resume_after_all_rounds_says_there_is_nothing_to_do(tmp_path: pathlib.Path):
    """负控（三态）：检查点显示 4/4 已完成 ⇒ 停成 resumed_done，不空转。"""
    st, registry, cond, root, gw = _wire(tmp_path)
    _run(st, registry, cond, root, gw, rounds=4)
    calls = gw.calls
    again = _run(st, registry, cond, root, gw, rounds=4, resume=True)
    assert again.stop_reason == "resumed_done" and again.rounds_done == 0, again.to_dict()
    assert gw.calls == calls, "没有要做的事时不许调用模型"


def test_the_previous_segment_spend_counts_toward_the_budget(tmp_path: pathlib.Path):
    """正控（跨段预算）：上一段的花销并进预算口径 ⇒ 第二段在开跑前就停。"""
    st, registry, cond, root, gw = _wire(tmp_path)
    first = _run(st, registry, cond, root, gw, rounds=2)
    spent = float(first.spend["usd"])
    assert spent > 0, first.spend
    calls = gw.calls
    second = _run(st, registry, cond, root, gw, rounds=4, resume=True,
                  usd_budget=spent / 2.0)
    assert second.stop_reason == "budget", second.to_dict()
    assert second.rounds_done == 0 and gw.calls == calls, "预算已耗尽却还在调模型"


def test_resume_without_a_checkpoint_starts_from_the_first_round(tmp_path: pathlib.Path):
    """负控（不许假装恢复）：没有检查点时如实说"从第 1 轮开始"，而不是静默当已恢复。"""
    st, registry, cond, root, gw = _wire(tmp_path)
    run = _run(st, registry, cond, root, gw, rounds=1, resume=True)
    assert run.resumed_from == 0 and run.rounds_done == 1, run.to_dict()
    assert any("读不到检查点" in n for n in run.notes), run.notes


def test_save_checkpoint_round_trips_and_reports_write_failures(tmp_path: pathlib.Path):
    """正控（写检查点这一格）：写得进、读得回；写不进去时返回问题串而不是抛。"""
    root = tmp_path / "ws"
    root.mkdir()
    problem = save_checkpoint(root, "D", fingerprint="abc123", completed_rounds=3, rounds=5,
                              task="把这件事推进下去", spend={"usd": 0.25}, stop_reason="budget",
                              last_final="上一轮的结论")
    assert problem == "", problem
    data = load_checkpoint(root, "D")
    assert data is not None, "写成了却读不回来"
    assert data["completed_rounds"] == 3 and data["rounds"] == 5
    assert data["fingerprint"] == "abc123" and data["stop_reason"] == "budget"
    assert data["last_final"] == "上一轮的结论" and data["spend"]["usd"] == 0.25

    # 负控（不许静默）：把落点做成"父路径是个文件"⇒ 写不进去，必须如实返回原因
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "runs").write_text("我是一个文件，不是目录", encoding="utf-8")
    bad = save_checkpoint(blocked, "D", fingerprint="x", completed_rounds=1, rounds=2,
                          task="t", spend={"usd": 0.0})
    assert bad, "写失败却返回了空串（静默失败）"
    assert load_checkpoint(blocked, "D") is None

