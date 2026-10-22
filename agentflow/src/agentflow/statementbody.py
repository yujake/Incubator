"""命题正文的唯一真身（D2）：`statement_full` 是真身，`statement_text` 是派生的短版。

## 现场（真机读数，`saxl-ws/data/statements.json`，2026-10-22 修复前）

13 条命题里 13 条的 `statement_text` 长度是 0，而同 13 条的 `statement_full` 有正文
（几十到几百字符）。于是同一份正文有两个字段，一个空一个满 —— 读侧读哪一个都能给出
另一种答案：`closing._provable_in_ledger` 先读 `statement_text` 再读 `statement_full`，
`agent_v` 反过来先读 `statement_full`、`webui` 的台账列先读短版。谁对？没有答案，
因为盘上没有"哪个是真身"这句话。

## 取值：`statement_full` 是真身

四条理由，都在盘上/代码里读得出来：

1. 判据要求它：`Statement.validate` 对 `status="active"` 要求 `statement_full` 非空
   （"省掉假设的命题会被下游当成无条件成立"），对 `statement_text` 只说"可以为空"；
2. 写入侧只有它必填：`register_statement(statement_full=...)` 是唯一必填的内容参数；
3. 下游靠它做事：`paperledger` 逐字搬正文、`reviewaccept` 审"缺 statement_full"、
   `agent_f` 用它查重、`secretary` 用它做幂等键（`T.normalize(statement_full)`）；
4. 老数据只有它：那 13 行全都有它。把真身定在 `statement_text` 上等于宣布盘上
   13 条命题全都没有正文。

## `statement_text` 怎么留

不删（`schema.py` 是禁改区，删字段等于改磁盘格式契约），而是明确成派生值：
写入时若调用方没给短版，就由 `statement_full` 派生（逐字复制，不截断、不摘要 ——
截断出来的"短版"是另一条命题，不是同一条的更短写法）。读侧一律走 :func:`body_of`，
回退顺序只有一条：`statement_full` 优先，空则退回 `statement_text`（历史行里
`statement_text` 单独有字的那些，例如只登记了短版的旧行）。

## 判据

:func:`text_gaps` 是读侧判据：`statement_full` 非空而 `statement_text` 为空 ⇒ 进脏清单。
它不假装修好历史数据 —— 那 13 行照样会被点名（把它们当基线钉住，而不是放过）。
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

    回退顺序：`statement_full` → `statement_text` → 空串。第一步就是"真身"，
    第二步只服务那些 `statement_full` 为空的历史行（`statement_text` 单独有字的旧行、
    或者手改过的行）；两者都空 ⇒ 返回空串（调用方必须自己判"空正文"该怎么处理，
    这里不替它编一句话）。
    """
    full = str(row.get(BODY_FIELD) or "").strip()
    if full:
        return full
    return str(row.get(TEXT_FIELD) or "").strip()


def derive_text(full: str, text: str = "") -> str:
    """短版的派生：调用方给了就照用（去首尾空白），没给就从真身逐字复制。

    为什么是"逐字复制"而不是截断/摘要：短版是给人引用时用的那一句，截断出来的
    前半句往往正好丢掉假设（"设 G 是有限群；则……" ⇒ "设 G 是有限群"），那是一句
    不同的话。宁可与真身一样长，也不要造一句没被任何人核过的正文。
    """
    given = str(text or "").strip()
    if given:
        return given
    return str(full or "").strip()


def text_gaps(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """读侧判据：点名"真身有正文而短版为空"的行（D2 的脏数据钉）。

    返回 `[{id, why}]`；空清单 = 这一批行没有这个毛病。判据只读两个字段，
    不修数据：历史行该被点名，而不是被"读侧兜住"之后假装没发生过。
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
