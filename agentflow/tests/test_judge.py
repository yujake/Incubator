"""`judge`（LLM 判定的唯一缝）的判据：正控 + 四类坏法各一条负控 + 一条三态纪律。

依据 `draft/30` §T0-8。这一层守的是"没查成"与"查过了没有"分得开：

- 正控：接线的 llm 给一份合法 JSON ⇒ 判定到手、原因为空；
- 负控：没接线 / 超时 / 坏 JSON / 抛别的异常 / 预算耗尽 / 判定方拒绝 ⇒
  各自归到受控词表里的名字，而且一个都不许折成"没找到"；
- 三态：`reason_of` 只在真有原因时给话，"查成了"没有理由可写。
"""
from __future__ import annotations

import pytest

from agentflow import judge as J


class _Llama:
    """最简接线：`complete` 返回预先给好的东西（或按脚本抛异常）。"""

    def __init__(self, *, returns: str = "", raises: BaseException | None = None) -> None:
        self.returns = returns
        self.raises = raises
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self.raises is not None:
            raise self.raises
        return self.returns


def test_positive_wired_llm_returns_a_judgement():
    """正控：合法 JSON ⇒ 判定到手，原因为空，且 prompt 真的发出去了。"""
    llm = _Llama(returns='{"keep": true, "why": "相关"}')
    data, why = J.judge_json(llm, "probe", point="L-A2")
    assert why == "" and data == {"keep": True, "why": "相关"}
    assert llm.calls == ["probe"]


def test_not_wired_is_a_problem_not_a_verdict():
    """负控：没接线 ⇒ `judge_not_wired`，而且不返回任何判定。"""
    data, why = J.judge_json(None, "probe")
    assert data is None and why == "judge_not_wired"
    assert J.is_judge_problem(why)


def test_timeout_is_classified():
    """负控：超时 ⇒ `judge_timeout`（可重试这一判断留给调用方）。"""
    _data, why = J.judge_json(_Llama(raises=TimeoutError("slow")), "p")
    assert why == "judge_timeout"


def test_bad_json_is_classified():
    """负控：返回不是 JSON ⇒ `judge_bad_json`（LLM 输出形态不可控）。"""
    _data, why = J.judge_json(_Llama(returns="这不是 JSON"), "p")
    assert why == "judge_bad_json"


def test_other_exception_carries_its_type():
    """负控：别的异常 ⇒ `judge_failed:<类名>`，类名逐字带上。"""
    _data, why = J.judge_json(_Llama(raises=ValueError("boom")), "p")
    assert why == "judge_failed:ValueError"
    assert J.is_judge_problem(why), "带后缀的形态也必须被认成失败码"


def test_budget_exhausted_and_refused_are_classified():
    """负控：预算耗尽 / 判定方拒绝 ⇒ 各自的名字（不是"没找到"）。"""
    assert J.judge_json(_Llama(raises=J.BudgetExhausted("no")), "p")[1] == "judge_over_budget"
    assert J.judge_json(_Llama(raises=J.JudgeRefused("policy")), "p")[1] == "judge_refused"


def test_mapping_result_is_accepted_but_json_is_the_normal_path():
    """接缝容忍"已经是 mapping"的接线（有些实现直接给结构化结果）。"""

    class _Mapping:
        def complete(self, prompt: str) -> dict:
            return {"ok": 1}

    data, why = J.judge_json(_Mapping(), "p")
    assert why == "" and data == {"ok": 1}


def test_non_dict_json_is_bad_json():
    """负控：JSON 合法但不是对象 ⇒ `judge_bad_json`（判定必须是一份对象）。"""
    _data, why = J.judge_json(_Llama(returns="[1, 2]"), "p")
    assert why == "judge_bad_json"


def test_reason_of_only_speaks_when_there_is_a_reason():
    """三态：查成了就没有理由可写；没查成时理由里带判断点。"""
    assert J.reason_of("") == ""
    assert "L-H1" in J.reason_of("judge_timeout", point="L-H1")
    assert "judge_timeout" in J.reason_of("judge_timeout", point="L-H1")


def test_vocabulary_covers_every_code_the_function_can_return():
    """反真空：函数能返回的每个码都必须在受控词表里（否则"受控"是句空话）。"""
    produced = {
        J.judge_json(None, "p")[1],
        J.judge_json(_Llama(raises=TimeoutError()), "p")[1],
        J.judge_json(_Llama(returns="x"), "p")[1],
        J.judge_json(_Llama(raises=J.BudgetExhausted()), "p")[1],
        J.judge_json(_Llama(raises=J.JudgeRefused()), "p")[1],
        J.judge_json(_Llama(raises=RuntimeError()), "p")[1],
    }
    assert produced, "一个码都没产出 ⇒ 判据空了"
    for code in produced:
        assert J.is_judge_problem(code), f"{code!r} 不在受控词表 {J.JUDGE_PROBLEMS} 里"


def test_unknown_code_is_not_a_problem():
    """负控（判据自身）：不在词表里的串不许被认成失败码（防"什么都算没查成"）。"""
    assert not J.is_judge_problem("not_found")
    assert not J.is_judge_problem("")


@pytest.mark.parametrize("code", J.JUDGE_PROBLEMS)
def test_every_vocabulary_entry_is_recognised(code: str):
    """词表里每一条都要被 `is_judge_problem` 认出来（含前缀形态）。"""
    assert J.is_judge_problem(code)
    assert J.is_judge_problem(f"{code}:detail")


def test_the_json_asker_accepts_both_seam_shapes():
    """判据（`draft/39` §6.44 的 D55）：`ask_json` 形状的缝（真机那个）也必须能用。

    真机读数（T5 第 4 趟 `p8d`）：F 的攻坚推理两条计划都卡在
    `judge_failed:AttributeError` —— 因为 `judge_json` 只认 `complete`，
    而真机接进来的 `llmseam.LlmSeam` 实现的是 `ask` / `ask_json`（没有 `complete`）。
    「要一份 JSON 判定」这件事只有这一处缝，两种形状都得收。
    """
    class _AskJsonSeam:
        def __init__(self, payload: dict | None = None, problem: str = ""):
            self.payload = payload
            self.problem = problem

        def ask_json(self, prompt: str, **kw):
            call = type("C", (), {"problem": self.problem, "ok": not self.problem})()
            return (dict(self.payload) if self.payload is not None else None), call

    got, problem = J.judge_json(_AskJsonSeam({"product": "reduction"}), "p", point="F.step")
    assert (got, problem) == ({"product": "reduction"}, ""), (got, problem)

    # 没查成时把缝自己报的码原样带出来（坏 JSON 不许折成"没找到"）
    got2, problem2 = J.judge_json(_AskJsonSeam(None, "judge_bad_json"), "p")
    assert got2 is None and problem2 == "judge_bad_json", (got2, problem2)

    # 旧形状（只有 `complete`）不受影响 —— 兼容按 `draft/30` §T0-8 写的替身。
    class _CompleteOnly:
        def complete(self, prompt: str) -> str:
            return '{"ok": true}'

    assert J.judge_json(_CompleteOnly(), "p") == ({"ok": True}, "")
