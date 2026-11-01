# -*- coding: utf-8 -*-
"""谁写的这份证明：B 登记的那一刻把它记到 statements 行上（业主 2026-11-01 裁定）。

## 为什么需要它

V 回执的收件人 = 送审者（召唤 V 的那个 task）。"送审者该不该是这个人"只能拿
"作者是谁"来判：业主的口径是「F 写的证明，F 送审，F 拿到 V 签，B 侧收录」「不
存在 F 写证明 B 送审」。而在这一笔之前，statements 行上没有作者 —— 81 的 8 条
回执因此只能记 `author_not_recorded`（见 `vreceipts._author_of`），运行期永远
判不出"替人送审"。

## 只认两种来源（读不出来就记"作者未记录"，不猜）

1. 调用方显式交 `proof_authors`（B 自己写的那一份走这条：`["B"]`）；
2. 从登记时读到的来源路径推：`reports/` ⇒ F（F 的研究稿），`out/paper/` ⇒ G
   （G 的论文正文），`documents/` ⇒ B（B 的登记稿）。

`origin="own_result"` 不是作者证据：F 与 B 都会交自产命题。`created_by` 也不是
（它是登记口，恒为 `secretary-<角色>`）。

## 三态

`checked=True` + `author`：记下来了；`checked=False` + `reason`：读不出来源 ⇒
调用方不写这一格（读数记 `author_not_recorded`），不许默认成 B、也不许默认成
送审者。

## 只加数据

不改 `bits`、不改收录行为、不改 `created_by`；这一格不在 `schema.Statement` 的
字段表里，按行上的附加键落盘（`store` 的 upsert 原样保留，`statements` 表校验
不拒未知键 —— 判据 `test_proof_authors_survives_a_round_trip` 钉住）。
"""
from __future__ import annotations

from typing import Any, Mapping

from . import schema as _S

#: 角色词表：唯一来源是 `schema.ROLES`（不在这里抄第二份，R005）。
ROLES = tuple(_S.ROLES)

#: 来源路径前缀 ⇒ 写它的角色。次序即优先级（同一份 payload 里出现多个时取第一个）。
SOURCE_RULES: tuple[tuple[str, str], ...] = (
    ("reports/", "F"),
    ("out/paper/", "G"),
    ("documents/", "B"),
)

#: 从 payload 里找来源路径的键（按次序取第一个能认出来的）。
PATH_KEYS: tuple[str, ...] = (
    "line_range", "doc_id", "source", "source_path", "origin_path", "path",
    "source_doc_id",
)


def _role_of(text: Any) -> str:
    got = str(text or "").strip()
    for prefix in ("agent-", "agent_", "secretary-", "secretary_"):
        if got.lower().startswith(prefix):
            got = got[len(prefix):]
            break
    got = got.strip().upper()
    return got if got in ROLES else ""


def _paths_of(value: Any) -> list[str]:
    """把一个键的值摊成若干条路径字符串（`line_range` 可能是 `{label: ...}`）。"""
    out: list[str] = []
    if isinstance(value, Mapping):
        for key in ("label", "path", "file", "source"):
            if value.get(key):
                out.append(str(value[key]))
    elif isinstance(value, (list, tuple)):
        for one in value:
            out.extend(_paths_of(one))
    elif value is not None:
        out.append(str(value))
    return [p.replace("\\", "/").strip().lstrip("./") for p in out if p.strip()]


def author_reading(*, body: Mapping[str, Any] | None, root: Any = "") -> dict[str, Any]:
    """这一次登记的作者读数：`{checked, author, source, reason}`。"""
    out: dict[str, Any] = {"checked": False, "author": "", "source": "", "reason": ""}
    payload = dict(body or {})
    # ① 显式登记（B 自己写的那一份：`proof_authors=["B"]`）。
    explicit = payload.get("proof_authors")
    if isinstance(explicit, str):
        explicit = [explicit]
    if isinstance(explicit, (list, tuple)):
        for one in explicit:
            role = _role_of(one)
            if role:
                out.update(checked=True, author=role, source="payload",
                           reason=f"调用方显式交的 proof_authors={role}")
                return out
    # ② 来源路径（登记时读的是哪一份稿）。
    for key in PATH_KEYS:
        for path in _paths_of(payload.get(key)):
            for prefix, role in SOURCE_RULES:
                if path.startswith(prefix):
                    out.update(checked=True, author=role, source=f"path:{prefix}",
                               reason=f"登记来源 {path} 属于 {prefix} ⇒ 作者 {role}")
                    return out
    out["reason"] = ("读不出这份证明的来源（没有显式 proof_authors，也没有可认的"
                     "来源路径）⇒ 作者未记录，不猜")
    return out


def recorded(reading_result: Mapping[str, Any]) -> list[str]:
    """读数 ⇒ 要写进 statements 行的 `proof_authors`（读不出来 ⇒ 空列表，不写这一格）。"""
    author = str((reading_result or {}).get("author") or "")
    return [author] if author else []
