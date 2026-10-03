# -*- coding: utf-8 -*-
"""角色动作的「拒绝」只有一个形态（`draft/37` §88）。

## 为什么需要这个模块

角色动作拒绝一次调用时，此前各写各的：`{"ok": False, "kind": ..., "error": ...}`。
形状看着一致，但终态映射看不见它 —— `Conductor._end_from_payload` 原先只看
"handler 有没有返回 dict"，于是 `ok=False` 被记成 `outcome=ok`。

T1 第 2 趟真机读数（2026-10-04）：`B.register_statement` 的 8 次拒绝在 `tasks` 台账里
全是 `outcome=ok`（detail 还写着"按有产出处理"），而 `statements` 是 0 行 ——
主控以为命题登记好了，于是不再改参数，整条链在这一步静默停住；同一趟里另外 6 次
抛异常的调用反倒记成 `failed`。"拒绝"与"崩溃"同形，"成功"与"什么都没写"也同形。

## 修法：拒绝要自报理由，理由取受控词表里的那一档

`schema.REFUSAL_REASONS` 里 `invalid_params` 的定义就是这一档：
"参数/前置条件不满足：这次调用本身不成立（不是『角色没这个本事』）"。
`schema.Task.validate` 逐字要求 `outcome=refused` 必须带受控理由
（"拒绝的理由必须是受控词表，不许自由文本"），所以理由不能由各动作自造。

显式声明它之后，终态映射能落 `refused / invalid_params`；不声明的
（只 `ok=False`）只能落 `failed` —— 那是"执行了、没成功"，与"这次调用本身不成立"
是两件事，混在一起的代价就是这个模块存在的原因。

`kind` 仍然逐字保留：它比 `invalid_params` 细一档（`missing_proof_text` /
`bad_id` / `bad_mode`…），是调用方真正据以改参数的那一格。
"""
from __future__ import annotations

from typing import Any

from . import schema as S

#: 前置条件不满足时用的那一档受控理由。集中在这里，是为了让"动作拒绝"这件事
#: 只有一个落点：散在各文件里的字面量一旦漂移，`Task.validate` 会在写库那一刻抛，
#: 而那时"拒绝"已经变成"崩溃"了。
PRECONDITION_REASON = "invalid_params"

#: 模块导入期自检：这一档必须真的在受控词表里。不在 ⇒ 每次拒绝都会把
#: `Task.validate` 撞红，而那时错误信息在别处（"outcome=refused 时必须给
#: refusal_reason ∈ (...)"），排查方向会被引到词表上而不是这里。
assert PRECONDITION_REASON in S.REFUSAL_REASONS, (
    f"{PRECONDITION_REASON!r} 不在 schema.REFUSAL_REASONS 里 ⇒ 所有动作拒绝都会"
    "在写台账时抛异常（拒绝被记成崩溃）"
)


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
