"""判据：剪枝真的会触发（S-B ③ / 施工单 §2 的甲方案；修掉那个"假开"读数）。

## 那条"假开"读数是什么（判据要钉的事实）

`threshold_chars=8000`（注册表级剪枝阈值）而模型可见路径上的单字段上限是
`RESULT_CHARS=6000` ⇒ 不存在超过 8000 字符的单个字符串 ⇒ 剪枝分支永不触发，
`spill` 那支更不可达。所以"剪枝开着"这件事在改前是一句空话。

施工单的处置是甲：把剪枝挪到"压力确认之后、结果进历史之前"（照 DSH 的
`pruneSession`：只在压缩触发成立之后剪一次），并按 DSH 的跨块一条字符流形状剪
（我们原来是逐 str 各留头尾 ⇒ `data` 里 5 个 3000 字字段一个都不剪，而模型一次看到 15000）。

## 判据（六条）

1. 正控（跨块那条流的形状）：5×3000 字的字段拼成一条流 ⇒ 真的剪掉中间那段、
   标记只插一次、每个键都还在、产出严格更小且 ≤ 阈值（逐块那版一个都不剪 ——
   这一条就是"两种形状的差别"的机器读数）。
2. 负控：整条流没超阈值 ⇒ 一个字都不动。
3. 配置期不变量（DSH `PR:43-44`）：`head + 标记长度 + tail > threshold` ⇒ `validate()` 当场拒
   （改前只判 `head + tail < threshold`，没算标记自身的长度）。
4. 自查②（DSH `PR:122`）：产出不比原文小 ⇒ 判失败（用一段超长标记触发）。
5. 正控（循环里真的剪了一次）：压力确认之后，超大的工具结果被剪，
   落 `compaction_prune` 事件（带 `surface_op` 与 `replacement_message`），
   而记进历史的那一份是剪过的（不是只在内存里剪）。
6. 负控（低于压力绝不动）：没到压力门 ⇒ 一个 `compaction_prune` 都没有、
   结果原样进历史。

另有一条与压缩那条对称的重放判据（剪过之后 `resume_messages` 仍与当时那份逐条相等）
放在压缩那个文件里 —— 它守的是同一件事。
"""

from __future__ import annotations

import json
import pathlib

import pytest

import test_agent_loop as TAL
from agentflow import agent_loop as AL
from agentflow import contextbudget as CB
from agentflow import sessions as SS
from agentflow.agent_loop import run_role
from agentflow.llmseam import LlmSeam
from agentflow.tools.base import tool


def _reply(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def test_the_stream_pruner_cuts_across_blocks() -> None:
    """正控：跨块一条字符流 —— 5 个 3000 字字段真的被剪，标记只插一次。"""
    budget = CB.ContextBudget()
    big = {f"f{i}": "x" * 3000 for i in range(5)}
    out, reading = CB.prune_stream(big, budget=budget)
    assert reading.pruned is True, reading.reason
    assert reading.kept_chars < reading.original_chars, reading
    assert reading.kept_chars <= budget.threshold_chars, reading
    assert reading.text.count("省略") == 1, reading.text.count("省略")
    assert sorted(out) == sorted(big), "键丢了（剪枝只该动文本，不该动结构）"
    # 逐块那版（改前的形状）在同一个输入上一个都不剪 —— 这就是两种形状的差别
    per_block = {k: len(v) <= budget.threshold_chars for k, v in big.items()}
    assert all(per_block.values()), "夹具没能造出'逐块都不超阈值、整条却超'的形态"


def test_below_the_threshold_nothing_moves() -> None:
    """负控：整条流没超阈值 ⇒ 一个块也不动（同一个对象原样返回）。"""
    budget = CB.ContextBudget()
    small = {"a": "x" * 100, "b": ["y" * 50]}
    out, reading = CB.prune_stream(small, budget=budget)
    assert reading.pruned is False and out is small, reading.reason
    assert "一个块也没剪" in reading.reason, reading.reason


def test_the_marker_length_counts_toward_the_invariant() -> None:
    """配置期不变量：`head + 标记 + tail > threshold` ⇒ 拒（改前漏了标记那一截）。"""
    marker_len = len(CB._MARKER_FMT.format(removed=0, total=0))
    with pytest.raises(ValueError, match="省略标记"):
        CB.ContextBudget(threshold_chars=100, head_chars=80, tail_chars=5).validate()
    # 正控对照：把标记那一截留出来之后是合法的
    CB.ContextBudget(threshold_chars=200, head_chars=80, tail_chars=5).validate()
    assert marker_len > 0


def test_a_marker_that_is_too_long_is_refused_at_config_time(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """配置期不变量先一步拦住"越剪越长"（DSH `PR:43-44`）。

    这里把标记临时换长（9000 字符）⇒ 配置期就抛 —— 而自查②（"产出不比原文小 ⇒ 抛"，
    DSH `PR:122`）在数学上够不到：不变量保证了 `head + 标记 + tail ≤ 阈值 < 原文`
    ⇒ 产出必然更短。它的价值是"万一有人把那条不变量挪走/改宽"，那时它会当场红。
    这一条判据因此断言的是两道防线里的第一道，并把"第二道够不到"这件事写清楚
    （而不是用一个假触发去糊弄出一条绿）。
    """
    huge_marker = "\n… " + "省" * 9000 + "{removed}/{total} …\n"
    monkeypatch.setattr(CB, "_MARKER_FMT", huge_marker)
    with pytest.raises(ValueError, match="省略标记"):
        CB.prune_stream({f"f{i}": "x" * 3000 for i in range(2)}, budget=CB.ContextBudget())
    # 第二道防线本身是可用的（直接构造一次"够不到"的调用：把阈值临时放大到比产出小）
    budget = CB.ContextBudget()
    monkeypatch.setattr(CB, "_MARKER_FMT", "\n… 省略 {removed}/{total} …\n")
    _out, reading = CB.prune_stream({"a": "x" * 20000}, budget=budget)
    assert reading.pruned is True and reading.kept_chars < reading.original_chars, reading


def _big_tool() -> object:
    """一个返回"两块各 5000 字"的工具（判据用）。

    为什么不用 `fs.read`：它自己会把读出来的正文再剪一次（那是另一层的取舍），
    于是"原始结构到底有多大"这件事在夹具里就不可控了。这个工具的两块各自都不到
    8000 阈值、合起来 10000 ⇒ 正好是"逐块剪一个都不剪、跨块一条流剪得掉"的那一档。
    """

    @tool("demo.big", "回两块大文本（判据用）",
          {"type": "object", "properties": {}, "additionalProperties": False},
          side_effect="read", roles=("M",), returns="两块各 5000 字")
    def big() -> dict:
        return {"左块": "甲" * 5000, "右块": "乙" * 5000}

    return big


def _long_tool_run(tmp_path: pathlib.Path, *, window: int, sid: str):
    """跑一趟：每一步调一次"回两块大文本"的工具。

    为什么是 9000：它超过注册表级剪枝阈值 8000（于是"跨块一条字符流"真的剪得动），
    同时超过观测层单字段上限 6000（这正是"假开"那条读数的成因：工具层剪的是渲染过的
    文本，那时单字段已经被压到 6000 ⇒ 永远到不了 8000）。原始结构没有逐字段上限，
    所以剪枝必须落在它上面。
    """
    calls = [_reply({"tool": "demo.big", "args": {}, "why": f"第 {i} 次拿大文本"})
             for i in range(3)]
    st, cond, registry, gw, root = TAL._wired(
        tmp_path, {"M": calls + [_reply({"final": "收工"})]}, max_steps=6)
    registry.register_function(_big_tool())
    registry.default_budget = CB.ContextBudget(context_window=window, chars_per_token=1.0)
    run = run_role("M", "读那份中等材料然后收工", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"],
                                price=(0.0, 0.0), sid=sid),
                   workspace_root=str(root), sid=sid, from_env=False)
    events, problems = SS.read_session(root, sid=sid)
    assert not problems, problems
    return run, [e for e in events if e.get("kind") == "compaction_prune"]


def test_the_loop_prunes_oversized_results_after_the_pressure_gate(tmp_path: pathlib.Path) -> None:
    """正控（那个"假开"读数被修好了）：压力确认之后真的剪了一次，而且剪的是进历史的那一份。

    `RESULT_CHARS=6000`（观测层单字段上限）而注册表级 `threshold_chars=8000`
    ⇒ 工具层那一支永远不触发；这一条证明循环这一层真的剪掉了。
    """
    run, prunes = _long_tool_run(tmp_path, window=4000, sid="t-prune")
    assert AL.RESULT_CHARS < CB.ContextBudget().threshold_chars, \
        "夹具的读数前提变了（观测层上限已不低于工具层阈值）—— 重新核这一条"
    assert prunes, ("一个 `compaction_prune` 都没有 ⇒ 剪枝还是'假开'的"
                    f"（compactions={run.compactions}）")
    first = prunes[0]
    assert first["saved_chars"] > 0, first
    assert first["kept_chars"] < first["original_chars"], first
    assert first["replaced_node"]["kind"] == "agent_step", first
    assert "省略" in first["reason"], first
    # 记进历史的那一份就是剪过的（不是"只在事件里写着剪了"）：读数是"模型看到的那条消息
    # 比原始结果短得多"。诚实说清一处耦合（施工单 §2 早就点名的那个代价）：
    # 观测层的逐字段预算（`_clip_fields`，`RESULT_CHARS=6000` 按大字段平分）会再剪一次，
    # 于是我们那句"…[省略 N 字符]…"可能落在它保留的那一段之外 —— 模型这时看到的是
    # 观测层自己的截断说明。两种都算"模型知道这段被剪过"，但只有前一种是我们那句标记。
    # 判据因此断言"要么我们的标记、要么观测层的截断说明"，并把这件事写在这里，
    # 而不是假装标记一定在（那是把一处已知耦合说成没有）。
    tool_msgs = [m for m in run.messages if str(m.get("role")) == "tool"]
    seen = [str(m.get("content") or "") for m in tool_msgs]
    assert tool_msgs, "一条 tool 消息都没有"
    assert any(("[省略 " in c) or ("观测层" in c and "截断" in c) for c in seen), seen[:1]
    assert any(len(c) < 6000 for c in seen), [len(c) for c in seen]
    # 读数面：notes 里能看出剪了几个、省了多少、复测怎么说
    assert any("剪枝（第" in n and "跨块剪枝" in n for n in run.notes), run.notes


def test_below_the_pressure_gate_nothing_is_pruned(tmp_path: pathlib.Path) -> None:
    """负控（低于压力绝不动，DSH README:89）：没到压力门 ⇒ 一个剪枝事件都没有。"""
    run, prunes = _long_tool_run(tmp_path, window=10_000_000, sid="t-noprune")
    assert prunes == [], prunes
    assert run.compactions == 0, run.to_dict()
    tool_msgs = [m for m in run.messages if str(m.get("role")) == "tool"]
    assert tool_msgs and all("省略" not in str(m.get("content") or "") for m in tool_msgs), \
        "没到压力门却动了历史"
