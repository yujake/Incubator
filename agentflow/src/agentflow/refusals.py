# -*- coding: utf-8 -*-
"""角色动作的「拒绝」只有一个形态。

各动作此前各写各的 `{"ok": False, "kind": ..., "error": ...}`：形状看着一致，但终态
映射看不见它 —— `Conductor._end_from_payload` 只看"handler 有没有返回 dict"，于是
`ok=False` 被记成 `outcome=ok`。"拒绝"与"崩溃"同形，"成功"与"什么都没写"也同形。

修法：拒绝自报受控理由（`schema.REFUSAL_REASONS` 里的 `invalid_params` 一档，定义是
"参数/前置条件不满足：这次调用本身不成立"）。`schema.Task.validate` 要求
`outcome=refused` 必须带受控理由，所以理由不许由各动作自造 —— 有理由才能落
`refused/invalid_params`，只有 `ok=False` 的只能落 `failed`（"执行了、没成功"）。

`kind` 逐字保留：它比 `invalid_params` 细一档（`missing_proof_text` / `bad_id` /
`bad_mode`…），是调用方真正据以改参数的那一格。
"""

from __future__ import annotations

from typing import Any

from . import schema as S

__all__ = ["PRECONDITION_REASON", "EMPTY_STATEMENT_TEXT", "EMPTY_PROOF_TEXT",
           "SAME_STATEMENT_UNJUDGED", "refuse"]

#: 前置条件不满足时用的那一档受控理由。集中一处：散在各文件的字面量一旦漂移，
#: `Task.validate` 会在写库那一刻抛 —— 那时"拒绝"已经变成"崩溃"了。
PRECONDITION_REASON = "invalid_params"

#: 导入期自检：这一档必须在受控词表里。不在 ⇒ 每次拒绝都撞红 `Task.validate`，
#: 而错误信息在别处，排查方向会被引到词表上而不是这里。
assert PRECONDITION_REASON in S.REFUSAL_REASONS, (
    f"{PRECONDITION_REASON!r} 不在 schema.REFUSAL_REASONS 里 ⇒ 所有动作拒绝都会"
    "在写台账时抛异常（拒绝被记成崩溃）"
)

#: 空正文的两个受控码（0 字命题 / 0 字证明要受控拒绝）。
#:
#: 必须只有一份：`register_statement`（写侧硬拦）与 `secretary.judge_statement`
#: （判档位那一侧）要说同一个词，否则同一输入在两处拿到两个 `kind`。
#:
#: 分工：`empty_statement_text` = 这一条命题没有正文（没有可判的对象）；
#: `empty_proof_text` = 这一笔声明了某份证明而它的正文是空的（声明了却没交）。
#: 后者刻意不管"整笔一条证明都没交"：自产命题的"证明还没做完"是合法登记态。
EMPTY_STATEMENT_TEXT = "empty_statement_text"
EMPTY_PROOF_TEXT = "empty_proof_text"

#: 「这一条是不是在册的某一条命题」没查成的受控码。
#:
#: 台账里有候选、而关键词没提取成或判定没成（没缝 / 超时 / 坏 JSON）⇒ 整笔不写。
#: 把"没查成"折成"不是同一条"会让同一条命题被登记成第二行，且盘上无迹可查。
SAME_STATEMENT_UNJUDGED = "same_statement_unjudged"


def refuse(kind: str, error: str, **extra: Any) -> dict:
    """造一条"这次调用本身不成立"的拒绝。

    返回的 dict 三件套齐备：`ok=False`（调用方据此知道没做成）、
    `kind`（细一档的原因，可读、可用于改参数）、`error`（一句话说清怎么办）、
    以及 `refusal_reason`（受控词表那一档，终态映射据此落 `refused`）。

    `**extra` 原样并进去：既有动作的返回里带着自己的读数
    （`source_lit_id` / `resolved` / `books_dir`…），那些不许因为改形状而丢。
    """
    out: dict[str, Any] = {"ok": False, "kind": str(kind),
                           "error": str(error),
                           "refusal_reason": PRECONDITION_REASON}
    out.update(extra)
    return out
