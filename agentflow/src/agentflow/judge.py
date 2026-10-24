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
  两条路都归它：缝抛 `TimeoutError`（走 `_problem_of`），或网关不抛、只回了
  `ok=False`/`error_kind="timeout"`（走 `problem_of_reply`）。
- `judge_output_limit`：输出预算被思考吃光（`finish_reason=length` + 正文为空 +
  思维链非空；2026-10-12 T2 真机读数 109,397 字思维链 / `max_tokens=32768`）。
  它与 `judge_timeout` 同族（都是"我们没拿到可用的回复"，不是"它说错了"），
  处置却不同：这一档要的是"把这一步拆小、把思考压短"，不是重发同一个请求。
- `judge_no_reply:<error_kind>`（2026-10-15 加）：其余"没查成"那一档
  （`modelgw.NOT_CHECKED` 里除上面两档以外的 `network` / `server_error` / `unknown` /
  `no_key`，以及重试完仍失败的 `rate_limited`）—— 后缀逐字带上网关自己的 `error_kind`。
  为什么它有资格占一个码（真机读数，T5 第 8 趟 `t5h`）：本机 DNS 中途失效，网关把
  `gaierror: [Errno 11002] getaddrinfo failed` 折成 `error_kind="network"`，
  而本函数当时只认两档 ⇒ 三次网络失败落成 `judge_failed:ModelReplyNotOk`、
  被循环按坏 JSON 计数、三次连击把整趟 run 判成 `bad_json_limit`，
  收场那句话是「连续 3 次没有给出可解析的 JSON」—— 模型一个字都没说，是我们没连上。
  这与 2026-10-12 那次（超时被当成坏 JSON）是同一个病，病根就在"只认两档"这一行。
- `judge_auth_failed`（2026-10-15 加）：key 无效/无权。它不是"没查成"
  （`modelgw.NOT_CHECKED` 里没有它：查过了、确定不行），也不是"它说错了"；
  处置只有一条（换 key / 查额度），所以调用方应当立刻停，不必等三次连击。
- `judge_bad_json`：返回的不是合法 JSON（LLM 的输出形态不可控）。
- `judge_over_budget`：预算耗尽（由调用方抛 `BudgetExhausted`，或由计量层拒绝）。
- `judge_refused`：判定方明确拒绝（由调用方抛 `JudgeRefused`）。
- `judge_failed:<异常类名>`：其它异常。逐字带上类名，便于事后归因。

为什么把后两个做成异常而不是字符串：字符串靠调用方记得传，异常由本函数当场归类 ——
"记得传"与"结构上必然发生"是两件事（本仓库反复踩过前者）。
"""

from __future__ import annotations

from typing import Any, Mapping

from . import modelgw as MG
from .llm import parse_llm_json

#: 受控词表：`judge_failed` 是前缀，实际串是 `judge_failed:<异常类名>`。
#:
#: `judge_bad_args`（2026-10-03 加，`draft/37` §49/§50）：工具名是对的、参数不是合法 JSON。
#: 它与 `judge_bad_json` 必须分开，理由是"下一步该说什么"完全不同：
#: 坏 JSON 要提醒模型"只回一行 JSON"；而坏参数要提醒它"工具 X 的参数不是对象" ——
#: 名字已经从传输层的结构化字段拿到了，所以这条错误比"认不出的形状"精确得多
#: （与 DSH 的 `parseArguments` + `ToolArgsError(INVALID_ARGS)` 同一条纪律）。
JUDGE_PROBLEMS: tuple[str, ...] = (
    "judge_not_wired",
    "judge_timeout",
    # `judge_output_limit`（2026-10-12 加）：输出预算被思考吃光 —— 见模块 docstring 那一行。
    "judge_output_limit",
    # `judge_no_reply`（2026-10-15 加）：其余"没查成"（网络 / 5xx / 未知 / 没 key / 限流），
    # 实际串是 `judge_no_reply:<error_kind>`。加它的理由见模块 docstring。
    "judge_no_reply",
    # `judge_auth_failed`（2026-10-15 加）：key 无效/无权 —— 立刻停，不必等三次连击。
    "judge_auth_failed",
    "judge_bad_json",
    "judge_bad_args",
    # `judge_unknown_tool`（2026-10-26 加）：原生工具调用面里"点了一个没广告过的函数名"。
    # 它与 `judge_bad_json` 必须分开，理由是"下一步该说什么"完全不同：坏 JSON 要提醒模型
    # "只回一行 JSON"，而点错名字要提醒它"这一趟广告的是哪几个函数、并列候选是哪几个" ——
    # 后者在文本协议下记的是 `unknown_tool`（工具层那一档），于是同一件事在两种协议下
    # 之前各记一半（`errorstats` 里两个类目）。现在两者归同一个类目
    # （`unknown_tool`：名字不存在），码保留判据层自己的名字 —— 与 `judge_not_wired`
    # 归 `not_wired` 是同一手法：码说"哪一层看出来的"，类目说"这是个什么错"。
    "judge_unknown_tool",
    "judge_over_budget",
    "judge_refused",
    "judge_failed",
    # ---- `L-05b-1`（`draft/52` D3）：`judges.judge` 自造的两个码收进同一张表。
    #
    # 它们此前不在本表里 ⇒ `is_judge_problem("judge_bad_verdict")` 返回 `False`，
    # 于是"判定词表外的取值"与"凭印象的评审被降级"这两个本层产出的失败码
    # 在调用方看来不像失败码（`judges.py` 的 docstring 却逐字写着"复用 JUDGE_PROBLEMS"）。
    # 只加不删、只加不改名（旧码的历史读数要能原样对照，`46-05` §4.4）。
    "judge_bad_verdict",
    "judge_ungrounded_findings",
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


def _problem_of(exc: BaseException) -> str:
    """异常 → 失败码的唯一映射（`L-05b-3`，`draft/52` D3）。

    为什么单列一个函数（而不是在各个 `except` 链里各写一遍）：
    这套映射此前有两份（本模块的 `judge_json` 与 `judges.judge` 的裸 `ask_json`），
    而 `judges` 那份根本没有归类（`BudgetExhausted`/`JudgeRefused`/`TimeoutError`
    会落成 `judge_failed:<类名>`，词表外的异常也会）。两份实现必然漂移，
    漂移的症状是同一件事在两个入口上给两个码。

    只做归类不做判断：`judge_failed:<类名>` 里的类名刻意保留（`judge.py` 的
    docstring 第 19 行解释了为什么它不是一个受控枚举）。
    """
    if isinstance(exc, BudgetExhausted):
        return "judge_over_budget"
    if isinstance(exc, JudgeRefused):
        return "judge_refused"
    if isinstance(exc, TimeoutError):
        return "judge_timeout"
    return f"judge_failed:{type(exc).__name__}"


def problem_of_reply(reply: Any) -> str:
    """网关的一次结局对象（不是异常）→ 本层的失败码；成功给空串。

    为什么要有它：同一个"没查成"有两条路进本层，而它们此前给了两个码 ——
    抛异常那条走 `_problem_of`（`TimeoutError` ⇒ `judge_timeout`），
    不抛那条在 `llmseam` 里写死成 `judge_failed:ModelReplyNotOk`。
    后者不是罕见路径：`modelgw.ModelGateway.complete` 从不抛 —— 它把超时、网络、
    认证失败一律折成 `ok=False` 的回复，把"哪一档"放在 `error_kind` 里。

    真机读数（2026-10-12 无 Lean 模式 T2 步 1）：三次 `detail=超过 60.0s 未返回`
    落成的都是 `judge_failed:ModelReplyNotOk`，循环据此按"坏 JSON"计数、
    收场措辞写成"连续 3 次没有给出可解析的 JSON" —— 三句话没有一句是真的：
    它没有"给出"任何东西，是我们没等到。归因错在"码"这一格，不在读数。
    第二次真机读数（2026-10-15 T5 第 8 趟 `t5h`）：同一个病换了外衣 ——
    当时只认 `timeout` 与 `output_exhausted` 两档，于是本机 DNS 失效
    （`gaierror: getaddrinfo failed`，`error_kind="network"`）连续三次落成
    `judge_failed:ModelReplyNotOk`，又把整趟 run 判成 `bad_json_limit`。
    所以现在按 `modelgw.NOT_CHECKED` 这张已声明的词表分流，而不是列举两档：
    词表加了新档，这里自动跟着走（这正是"一处定义"要的效果）。

    分流表（只做归类，不做判断）：

    | 网关的 `error_kind` | 本层的码 | 为什么 |
    |---|---|---|
    | `timeout` | `judge_timeout` | 没等到 —— 历史读数点名的那一档 |
    | `output_exhausted` | `judge_output_limit` | 预算被思考吃光 —— 处置是拆小这一步 |
    | 其余 `NOT_CHECKED`（`network` / `server_error` / `unknown` / `no_key`） | `judge_no_reply:<kind>` | 都是"我们没拿到可用的回复"，却各有各的原因；后缀逐字保留原因，便于事后归因 |
    | `auth_failed` | `judge_auth_failed` | 查过了、确定不行（key 无效）—— 立刻停 |
    | `bad_response` 及其余 | `judge_failed:ModelReplyNotOk` | 它回了，只是那份回复不可用 —— 与上面几档分得开 |
    """
    if bool(getattr(reply, "ok", False)):
        return ""
    kind = str(getattr(reply, "error_kind", "") or "")
    if kind == "timeout":
        return "judge_timeout"
    if kind == "output_exhausted":
        return "judge_output_limit"
    if kind == "auth_failed":
        return "judge_auth_failed"
    # `rate_limited` 不在 `NOT_CHECKED` 里（它在 `RETRYABLE`：服务是活的、值得重试），
    # 但重试完之后它同样是"我们没拿到可用的回复" —— 归因与处置都跟"它说错了"相反
    # （该做的是退避/换时段，不是收紧输出协议）。所以它与 `NOT_CHECKED` 同归这一族。
    if kind in MG.NOT_CHECKED or kind == "rate_limited":
        return f"judge_no_reply:{kind or 'unknown'}"
    return "judge_failed:ModelReplyNotOk"


def is_no_reply(code: str) -> bool:
    """这个失败码属于「我们没拿到可用的回复」那一档吗（`LoopRun.no_reply` 的成员判据）。

    成员就是三样：`judge_timeout` / `judge_output_limit` / `judge_no_reply:<error_kind>`。

    为什么是函数而不是一张元组常量：`judge_no_reply:` 带后缀（与 `judge_failed:` 同形），
    拿 `in ("judge_timeout", "judge_output_limit")` 判会漏，而漏的表现就是
    它被算进坏 JSON —— 这件事在真机上已经发生过两次（2026-10-12 超时、2026-10-15 网络）。
    判据只许有这一处：计数、纠正行、停止理由三处都按它分流。
    """
    text = str(code or "")
    return (text in ("judge_timeout", "judge_output_limit")
            or text.startswith("judge_no_reply:"))


def seam_json(seam: Any, prompt: str, *,
              point: str = "") -> tuple[dict[str, Any] | None, str, Any]:
    """`ask_json` 形态的缝的共用入口：`(判定, 没查成的原因, 这次调用的审计事实)`。

    为什么把共用入口放在本文件（`L-05b-4` / `46-05` §4.2）：本模块是"失败码表 +
    异常类"的唯一定义处，把"调一次缝并把异常归成码"也放在这里最自然 ——
    `judges.judge` 与 `judge.judge_json` 从此都转调它，两个入口名都保留
    （`agent_f/core.py` 调 `judge_json`，`agent_h/core.py` 调 `judges.judge`）。

    `seam` 没有 `ask_json`（按 `draft/30` §T0-8 写的 `complete` 形态）不归这里管：
    那是 `judge_json` 的兼容分支，转调方自己分流。
    """
    if seam is None or not getattr(seam, "wired", True):
        return None, "judge_not_wired", None
    try:
        data, call = seam.ask_json(prompt, note=point)
    except BaseException as exc:  # noqa: BLE001 —— 逐类归类由 `_problem_of` 做，不吞
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return None, _problem_of(exc), None
    problem = str(getattr(call, "problem", "") or "")
    if data is None:
        return None, problem or "judge_bad_json", call
    if not isinstance(data, Mapping):
        return None, "judge_bad_json", call
    return dict(data), "", call


def judge_json(llm: Any, prompt: str, *, point: str = "") -> tuple[dict[str, Any] | None, str]:
    """向 LLM 要一份 JSON 判定：返回 `(判定, 没查成的原因)`。

    `point` 只用于留痕（调用方把它写进审计字段：这一格是哪一条判断点），
    不参与任何分支 —— 分支只由 `llm` 是否接线与异常类型决定。

    ## 两种缝的形状都收（`draft/39` §6.44 的 D55）

    调用约定（与 `draft/30` §T0-8 逐字一致）：`llm` 只需实现
    `complete(prompt: str) -> str`；解析走 `llm.parse_llm_json`。
    而真机里接进来的那个缝（`llmseam.LlmSeam`）没有 `complete` —— 它实现的是
    `ask(prompt) -> SeamCall` / `ask_json(prompt) -> (dict|None, SeamCall)`。
    于是任何拿真缝调本函数的调用点都会得到 `judge_failed:AttributeError`
    （真机读数 T5 第 4 趟 `p8d`：F 的攻坚推理两条计划都卡在这一句上，
    M 只好如实记"推理缝没查成"）。两件事都修在这一处（它是"要一份 JSON 判定"的唯一缝）：

    - 缝有 `ask_json` ⇒ 直接用它（它自己会把坏 JSON 归成 `judge_bad_json`，还带上解析原话）；
    - 只有 `complete` ⇒ 走原来的路（兼容按 `draft/30` §T0-8 写的替身与旧接线）。
    """
    if llm is None:
        return None, "judge_not_wired"
    if hasattr(llm, "ask_json"):
        # `L-05b-4`：共用入口只有一处（异常→码的映射也只有一处）
        data, problem, _call = seam_json(llm, prompt, point=point)
        return data, problem
    try:
        raw = llm.complete(prompt)
    except BaseException as exc:  # noqa: BLE001 —— 归类走 `_problem_of`
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return None, _problem_of(exc)
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
           "judge_json", "seam_json", "reason_of", "problem_of_reply"]
