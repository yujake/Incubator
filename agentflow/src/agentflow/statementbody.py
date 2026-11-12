"""命题正文的唯一真身：`statement_full` 是正文，`statement_text` 是派生短版。

同一份正文曾有两个字段（一个空一个满），读侧各读一个 ⇒ 同一行能读出两种答案，
而盘上没有"哪个是真身"这句话。定在 `statement_full` 上的依据：判据对
`status="active"` 要求它非空、写入侧只有它必填、下游（`paperledger` / `reviewaccept` /
`agent_f` 查重 / `secretary` 的幂等键）都靠它、老数据也只有它。

`statement_text` 不删（改字段等于改磁盘格式契约），而是明确成派生值：写入时调用方
没给短版就由真身逐字复制（不截断、不摘要 —— 截断出来的"短版"是另一条命题）。
读侧一律走 :func:`body_of`，回退只有一条：真身优先，空则退回短版（服务只登记了短版的历史行）。

:func:`text_gaps` 是读侧判据：真身有正文而短版为空 ⇒ 进脏清单；它不假装修好历史数据。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

#: 命题正文的真身（唯一来源）。
BODY_FIELD = "statement_full"
#: 派生的短版（写入时由真身派生；读侧只在真身为空时退回它）。
TEXT_FIELD = "statement_text"


def body_of(row: Mapping[str, Any]) -> str:
    """读一条命题的正文（唯一入口；回退顺序写死在这里）。

    `statement_full` → `statement_text` → 空串。第二步只服务真身为空的历史行；
    两者都空 ⇒ 返回空串（"空正文怎么处理"由调用方判，这里不替它编一句话）。
    """
    full = str(row.get(BODY_FIELD) or "").strip()
    if full:
        return full
    return str(row.get(TEXT_FIELD) or "").strip()


def derive_text(full: str, text: str = "") -> str:
    """短版的派生：调用方给了就照用（去首尾空白），没给就从真身逐字复制。

    不截断/不摘要：截断出来的前半句往往正好丢掉假设，那是一句不同的话；
    宁可与真身一样长，也不造一句没人核过的正文。
    """
    given = str(text or "").strip()
    if given:
        return given
    return str(full or "").strip()


def text_gaps(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """读侧判据：点名"真身有正文而短版为空"的行。

    返回 `[{id, why}]`；空清单 = 这一批行没这个毛病。只读两个字段、不修数据：
    历史行该被点名，而不是被读侧兜住之后假装没发生过。
    """
    gaps: list[dict[str, Any]] = []
    for row in rows or ():
        full = str(row.get(BODY_FIELD) or "").strip()
        if not full:
            continue
        if str(row.get(TEXT_FIELD) or "").strip():
            continue
        rid = str(row.get("stmt_id") or row.get("id") or "")
        gaps.append({
            "id": rid,
            "why": ("statement_full 有正文而 statement_text 为空 ⇒ 同一份正文两个字段、"
                    "一个空一个满（读侧读哪个都能给出另一种答案）；写入侧应当派生短版"),
        })
    return gaps
