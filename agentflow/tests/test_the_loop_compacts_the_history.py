"""判据：压缩真的接进了循环（S-B 第②步 / 裁定 7乙 + 8乙 + 12-I=甲 + 12-J=甲）。

## 这一批判的是"接上了没有"（口径与不变量在 `test_the_token_pressure_gate_is_dsh_shaped.py`）

六件事：

1. 正控（真的压了一次）：历史超过阈值 ⇒ 步边界上压了一次，会话里能看到事件三件套
   （`compaction_start` / `compaction_summary` / `compaction_end`）与那条带 `surface_op` 的
   替换事件，而 `run.messages` 里被压的那一段换成了摘要那一条。
2. 反真空（节点 0 不变量）：压完那份发给模型的提示词里仍然有任务原文
   （压缩压不到"这一趟要做什么"）。
3. 负控（未到阈值 ⇒ 一次都不压）：`compactions == 0` 且一个压缩事件都没有。
4. 三态（容量读不到）：`context_window` 没配 ⇒ 不压 + 每趟只警告一次
   （会话里只有一条"读不到容量"，不是每一步一条）。
5. 摘要那一笔钱（12-J=甲）：摘要调用落一条 `llm_call` 且 `note="compaction"`，
   `compaction_summary` 事件里带上这次调用的读数（钱不会静默流走）。
6. 重建（12-I=甲 的另一半）：`resume_messages` 按 `surface_op` 重放 ⇒
   重建出的序列与当时那份逐条相等（含那条摘要消息）。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import test_agent_loop as TAL
from agentflow import agent_loop as AL
from agentflow import sessions as SS
from agentflow.agent_loop import run_role
from agentflow.contextbudget import ContextBudget
from agentflow.llmseam import LlmSeam


def _reply(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


class _SummaryGateway(TAL.ScriptedGateway):
    """照剧本回答；若是"压缩器"那一次调用（提示词里带指令首句）就回一句短摘要。"""

    def __init__(self, replies: list[str], *, summary: str = "检查点：任务与目标=读文件；下一步=收工",
                 fail_summary: bool = False) -> None:
        super().__init__(replies)
        self.summary = summary
        self.fail_summary = fail_summary
        self.summary_calls = 0

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        if "上下文压缩器" in str(system or ""):
            self.summary_calls += 1
            text = "" if self.fail_summary else self.summary
            return type("Reply", (), {"ok": not self.fail_summary, "text": text,
                                      "reasoning": "", "tokens_in": 20, "tokens_out": 8,
                                      "error_detail": "" if not self.fail_summary else "挡住了",
                                      "error_kind": "" if not self.fail_summary else "refused"})()
        return super().complete(prompt, scope=scope, system=system, **kw)


def _big_run(tmp_path: pathlib.Path, *, window: int, steps: int = 4,
             chars_per_token: float = 1.0, fail_summary: bool = False,
             sid: str = "t-compact") -> tuple[Any, _SummaryGateway, pathlib.Path]:
    """跑一趟"每一步都读一大段"的循环（历史涨得快 ⇒ 压力门会响）。"""
    big = "长" * 4000
    # 每一步读同一份大文件（读的是"内容在历史里占多少"这件事，不是"有没有新事实"）
    reads = [_reply({"tool": "fs.read", "args": {"path": "big.txt"}, "why": f"第 {i} 次读"})
             for i in range(steps)]
    st, cond, registry, gw, root = TAL._wired(
        tmp_path, {"M": reads + [_reply({"final": "收工"})]}, max_steps=steps + 2)
    # 材料必须在 `_wired`（= `Store.init()`）之后铺：工作区根的"外来目录守卫"
    # 会把 big.txt 当成别人的东西而拒绝 init（`draft/28` §136.3 事故 B 的那道守卫）。
    (root / "big.txt").write_text(big, encoding="utf-8", newline="")
    registry.default_budget = ContextBudget(context_window=window, chars_per_token=chars_per_token)
    gateway = _SummaryGateway(gw["M"].replies, fail_summary=fail_summary)
    run = run_role("M", "读那份大文件然后收工", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gateway,
                                price=(0.0, 0.0), sid=sid),
                   workspace_root=str(root), sid=sid, from_env=False)
    return run, gateway, root


def _events(root: pathlib.Path, sid: str = "t-compact") -> list[dict]:
    events, problems = SS.read_session(root, sid=sid)
    assert not problems, problems
    return events


def test_the_loop_compacts_when_the_history_exceeds_the_threshold(tmp_path: pathlib.Path) -> None:
    """正控（真的压了一次）：事件三件套 + 替换事件 + `run.messages` 里真的换了。"""
    run, gateway, root = _big_run(tmp_path, window=2000, steps=4)
    assert run.compactions >= 1, run.to_dict()
    assert run.stop_reason == "final", run.to_dict()
    evs = _events(root)
    kinds = [e.get("kind") for e in evs]
    assert "compaction_start" in kinds and "compaction_summary" in kinds, kinds
    assert "compaction_swap" in kinds and "compaction_end" in kinds, kinds
    summary = next(e for e in evs if e.get("kind") == "compaction_summary")
    assert summary["summarizer"] == "llm", summary           # 8乙：LLM 那一档
    assert summary["shadowed_tokens"] > summary["framed_tokens"] > 0, summary
    assert summary["shadowed_range"][0] >= 1, summary         # 节点 0 不进被遮区间
    swap = next(e for e in evs if e.get("kind") == "compaction_swap")
    assert swap["surface_op"]["op"] == "replace", swap
    assert swap["surface_op"]["end_seq"] >= swap["surface_op"]["start_seq"], swap
    # `run.messages` 里那一段真的换成了摘要那一条（不是只在事件里写着）
    assert gateway.summary_calls >= 1, "压缩器一次都没被调用"
    assert any("检查点：任务与目标" in str(m.get("content") or "")
               for m in run.messages), run.messages[:3]
    assert run.transcript.count("读那份大文件然后收工") >= 1


def test_the_task_text_survives_and_the_prompt_still_has_it(tmp_path: pathlib.Path) -> None:
    """反真空（节点 0 不变量）：压完的提示词里仍然有任务原文那一段。"""
    run, gateway, _root = _big_run(tmp_path, window=2000, steps=4, sid="t-node0")
    # 模型看到的最后一份提示词（`gateway.prompts` 里最后一条）仍带着任务原文
    assert "读那份大文件然后收工" in gateway.prompts[-1], gateway.prompts[-1][:300]
    assert run.compactions >= 1, run.to_dict()


def test_below_the_threshold_never_compacts(tmp_path: pathlib.Path) -> None:
    """负控（未到阈值 ⇒ 一次都不压）：`compactions == 0` 且没有任何压缩事件。"""
    run, gateway, root = _big_run(tmp_path, window=10_000_000, steps=4, sid="t-under")
    assert run.compactions == 0, run.to_dict()
    assert gateway.summary_calls == 0, "没到阈值却调了摘要模型 ⇒ 钱白花了"
    kinds = [e.get("kind") for e in _events(root, "t-under")]
    assert not [k for k in kinds if str(k).startswith("compaction_")], kinds


def test_no_capacity_warns_once_and_keeps_the_full_history(tmp_path: pathlib.Path) -> None:
    """三态（容量读不到）：不压 + 每趟只警告一次（不是每一步一条）。"""
    run, gateway, root = _big_run(tmp_path, window=0, steps=4, sid="t-nocap")
    assert run.compactions == 0 and gateway.summary_calls == 0, run.to_dict()
    notes = [e for e in _events(root, "t-nocap")
             if e.get("kind") == "agent_note" and "读不到容量" in str(e.get("note") or "")]
    assert len(notes) == 1, f"警告了 {len(notes)} 次（应当每趟一次）：{notes}"
    assert "带完整历史继续" in notes[0]["note"], notes[0]["note"]


def test_the_summary_call_is_charged_with_the_compaction_note(tmp_path: pathlib.Path) -> None:
    """正控（12-J=甲）：摘要那一笔钱记在现成的用量档上 + `note="compaction"`。"""
    run, gateway, root = _big_run(tmp_path, window=2000, steps=4, sid="t-money")
    evs = _events(root, "t-money")
    calls = [e for e in evs if e.get("kind") == "llm_call" and e.get("note") == "compaction"]
    assert calls, [e.get("note") for e in evs if e.get("kind") == "llm_call"]
    summary = next(e for e in evs if e.get("kind") == "compaction_summary")
    assert summary.get("usage", {}).get("note") == "compaction", summary
    # 摘要调用不进对话模型的历史（DSH：`summarizeWithLlm` 全程不 append）
    assert not any("上下文压缩器" in str(m.get("content") or "") for m in run.messages), \
        "摘要那一次的提示词进了历史 ⇒ 对话模型会看到「我在摘要」这件事"


def test_the_rebuild_replays_the_swap(tmp_path: pathlib.Path) -> None:
    """    正控（12-I=甲 的另一半）：`resume_messages` 按 `surface_op` 重放 ⇒ 逐条相等。

    这是 S-C 那条"逐条相等"判据在压缩之后的形态：只在内存里压（不落替换事件）会让续跑那一趟看到没压过的版本。

    ## 一处如实说清的上限（不是这一批引入的）

    允许的唯一差异是"落档截断"那一档：事件里存的是截到 `RECORD_CHARS` 的审计副本（`_for_record`），所以超过 2000 字的工具结果在重建那份里会带一句"…（落档截断，原 N 字）"。
    本判据把它逐条钉住：差异必须从标记处开始、被截掉的那一段必须正好是超出上限的那一段。上限本身写在 `resume_messages` 的docstring 里（"重建能力的上限，不是我漏了"）；
    "除它之外没有别的差异"由下一条判据守。
    """
    run, _gateway, root = _big_run(tmp_path, window=2000, steps=4, sid="t-replay")
    assert run.compactions >= 1, run.to_dict()
    rebuilt, step0 = AL.resume_messages(root, "M", "t-replay", task="读那份大文件然后收工")
    assert step0 > 0, step0
    assert len(rebuilt) == len(run.messages), (len(rebuilt), len(run.messages))
    for i, (a, b) in enumerate(zip(rebuilt, run.messages)):
        if a == b:
            continue
        assert a.get("role") == b.get("role"), (i, a, b)
        ra = str(a.get("content") or "")
        rb = str(b.get("content") or "")
        cut = ra.find("…（落档截断，原 ")
        assert cut >= 0, (f"第 {i} 条的差异不是落档截断 ⇒ 重建真的分家了", ra[-120:])
        assert ra[:cut] in rb, (f"第 {i} 条：截断前那一段与当时那份对不上", ra[:80])
        assert len(rb) > len(ra), (f"第 {i} 条：重建那份比当时那份还长？", len(ra), len(rb))
    assert any("检查点：任务与目标" in str(m.get("content") or "") for m in rebuilt), \
        "重建出来的那份里没有摘要那一条 ⇒ 续跑会看到没压过的版本"
    assert rebuilt[1].get("content") == run.messages[1].get("content"), \
        "摘要那一条（第 1 条）必须逐字相同 —— 替换事件里存的就是它"


def test_the_rebuild_is_exactly_equal_when_nothing_was_truncated(tmp_path: pathlib.Path) -> None:
    """正控（严格那一半）：没有超长字段时重建与当时那两份逐条相等。

    与上一条配对：上一条说清"截断那一档是上限"，这一条证明"除它之外没有别的差异"
    （否则上一条的宽容会变成一张网，把真正的分家也放过去）。
    """
    st, cond, registry, gw, root = TAL._wired(
        tmp_path, {"M": [_reply({"tool": "conductor.role_spec", "args": {"role_name": "C"},
                                 "why": "看一眼"}), _reply({"final": "收工"})]}, max_steps=3)
    registry.default_budget = ContextBudget(context_window=100, chars_per_token=1.0)
    run = run_role("M", "小历史的续跑重建", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"],
                                price=(0.0, 0.0), sid="t-small"),
                   workspace_root=str(root), sid="t-small", from_env=False)
    rebuilt, step0 = AL.resume_messages(root, "M", "t-small", task="小历史的续跑重建")
    assert step0 == 1, step0
    assert rebuilt == run.messages, "没有超长字段时重建必须逐条相等"


def test_a_blocked_summarizer_keeps_the_history_and_records_it(tmp_path: pathlib.Path) -> None:
    """负控（摘要拿不到 ⇒ 不压，但如实落一条）：warn-and-continue，照 DSH 自动路径。

    这一条挡的形态是"压了一半"：摘要没拿到而历史已经被替换 ⇒ 那一段真的没了
    （原文既不在历史里、也不在盘上的事件里）。
    """
    run, _gateway, root = _big_run(tmp_path, window=2000, steps=4, fail_summary=True,
                                   sid="t-fail")
    assert run.compactions == 0, run.to_dict()
    ends = [e for e in _events(root, "t-fail") if e.get("kind") == "compaction_end"]
    assert ends and ends[-1].get("ok") is False, ends
    assert "Refused" in str(ends[-1].get("error") or ""), ends[-1]
    # 历史没被动过（任务原文与每一次读都还在）
    assert run.transcript.count("读那份大文件然后收工") >= 1
    assert not any("检查点" in str(m.get("content") or "") for m in run.messages)
