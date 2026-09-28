"""LLM 判定的唯一缝协议：一个函数、一套失败词表、一条"没查成不等于没找到"的纪律。

## 这一层解决什么

`draft/29` §3.1 要求所有角色用同一个 LLM 缝：角色自己不做 prompt 拼装与结果解析的
分支（那是"把智能体写成大程序"），而是调这里的一个函数，拿到
"判定 + 没查成的原因"。原因非空时，调用方必须走确定性回退并把它留痕 ——
既不许当成功，也不许折成"没找到"。

## 三态在这里的落点

`judge_json` 返回 `(dict | None, problem)`，`problem` 为空串才算"查成了"：

- `judge_not_wired`：没接线（`llm is None`）。这是"没查成"，不是"没有这个结论"。
- `judge_timeout`：超时。可以重试，但重试策略在调用方（受预算约束）。
- `judge_bad_json`：返回的不是合法 JSON（LLM 的输出形态不可控）。
- `judge_over_budget`：预算耗尽（由调用方抛 `BudgetExhausted`，或由计量层拒绝）。
- `judge_refused`：判定方明确拒绝（由调用方抛 `JudgeRefused`）。
- `judge_failed:<异常类名>`：其它异常。逐字带上类名，便于事后归因。

为什么把后两个做成异常而不是字符串：字符串靠调用方记得传，异常由本函数当场归类 ——
"记得传"与"结构上必然发生"是两件事（本仓库反复踩过前者）。
"""

from __future__ import annotations

from typing import Any, Mapping

from .llm import parse_llm_json

#: 受控词表：`judge_failed` 是前缀，实际串是 `judge_failed:<异常类名>`。
JUDGE_PROBLEMS: tuple[str, ...] = (
    "judge_not_wired",
    "judge_timeout",
    "judge_bad_json",
    "judge_over_budget",
    "judge_refused",
    "judge_failed",
)


class BudgetExhausted(RuntimeError):
    """预算耗尽：计费层拒绝这一次判定时抛它（由 `judge_json` 归成 `judge_over_budget`）。"""


class JudgeRefused(RuntimeError):
    """判定方明确拒绝：例如额度策略、内容策略（由 `judge_json` 归成 `judge_refused`）。"""


def is_judge_problem(code: str) -> bool:
    """这个串是不是本层的失败码（含 `judge_failed:<类名>` 形态）。

    为什么要有它：调用方要判断"拿到的是判定还是没查成"，而 `judge_failed` 带后缀，
    直接 `in JUDGE_PROBLEMS` 会漏。判据只有这一处，别处不许再写一遍。
    """
    text = str(code or "")
    return any(text == p or text.startswith(p + ":") for p in JUDGE_PROBLEMS)


def judge_json(llm: Any, prompt: str, *, point: str = "") -> tuple[dict[str, Any] | None, str]:
    """向 LLM 要一份 JSON 判定：返回 `(判定, 没查成的原因)`。

    `point` 只用于留痕（调用方把它写进审计字段：这一格是哪一条判断点），
    不参与任何分支 —— 分支只由 `llm` 是否接线与异常类型决定。

    调用约定（与 `draft/30` §T0-8 逐字一致）：`llm` 只需实现
    `complete(prompt: str) -> str`；解析走 `llm.parse_llm_json`。
    """
    if llm is None:
        return None, "judge_not_wired"
    try:
        raw = llm.complete(prompt)
    except BudgetExhausted:
        return None, "judge_over_budget"
    except JudgeRefused:
        return None, "judge_refused"
    except TimeoutError:
        return None, "judge_timeout"
    except Exception as exc:  # 其它异常按类型归类，绝不吞掉
        return None, f"judge_failed:{type(exc).__name__}"
    if isinstance(raw, Mapping):
        # 已经是一份 mapping（有些接线直接给结构化结果）：接受它，但不代表它是"对"的
        return dict(raw), ""
    try:
        data = parse_llm_json(str(raw))
    except Exception:
        return None, "judge_bad_json"
    if not isinstance(data, dict):
        return None, "judge_bad_json"
    return data, ""


def reason_of(problem: str, *, point: str = "") -> str:
    """把失败码翻成给人读的一句话（带 point 时写进去），供产物里的理由字段直接使用。

    只做翻译，不做判断：`problem` 为空串时返回空串（"查成了"没有理由可写）。
    """
    if not problem:
        return ""
    where = f"（判断点 {point}）" if point else ""
    return f"LLM 判定没查成{where}：{problem}"


__all__ = ["JUDGE_PROBLEMS", "BudgetExhausted", "JudgeRefused", "is_judge_problem",
           "judge_json", "reason_of"]
