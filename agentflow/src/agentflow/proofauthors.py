# -*- coding: utf-8 -*-
"""谁写的这份证明：B 登记的那一刻把它记到 statements 行上，运行期也能按号读回来。

## 为什么需要它

业主口径：「F 写的证明，F 送审，F 拿到 V 签，B 侧收录」；不存在 F 写证明 B 送审。
statements 行上没有作者，这类判断就只能记 `author_not_recorded`，运行期永远判不出
"替人送审"。所以本模块有两个读法，各管一个时机：

- :func:`author_reading`：登记那一刻（`secretary.record_statement` 写
  `proof_authors` 用的）—— 先认调用方显式交的，再按来源路径推；
- :func:`statement_author_of`：运行期（`vsigns.receipt_digest` 等读侧用）——
  按命题号从 `statements` 行上读 `proof_authors` / `created_by`。

两个读法的三态口径相同：读不出来就记"作者未记录"，不猜。

## 只认两种来源（读不出来就记"作者未记录"，不猜）

1. 调用方显式交 `proof_authors`（B 自己写的那一份走这条：`["B"]`）；
2. 从登记时读到的来源路径推：`reports/` ⇒ F，`out/package/` ⇒ G，`documents/` ⇒ B。

`origin="own_result"` 与 `created_by` 都不是作者证据：前者 F 与 B 都会交，
后者是登记口（恒为 `secretary-<角色>`）。唯一的例外是运行期读法认
`created_by="agent-F"`（那不是登记口，是谁创建了这一行）；`created_by="secretary-*"`
一律不算。

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

from . import manuscriptfamily as _MFAM
from . import schema as _S

#: 角色词表：唯一来源是 `schema.ROLES`（不在这里抄第二份，R005）。
ROLES = tuple(_S.ROLES)

#: 来源路径前缀 ⇒ 写它的角色。次序即优先级（同一份 payload 里出现多个时取第一个）。
#:
#: 目录从 `manuscriptfamily` 派生（正文按角色分目录）；退役的 `reports/` /
#: `documents/` 不再认 —— 那两个前缀在盘上已经不会写新文件，认了只会把"读不出来源"
#: 掩盖成"读到了"。
SOURCE_RULES: tuple[tuple[str, str], ...] = (
    (f"{_MFAM.dir_of('f-proof')}/", "F"),
    (f"{_MFAM.dir_of('b-proof')}/", "B"),
    (f"{_MFAM.dir_of('e-proof')}/", "E"),
    (f"{_MFAM.dir_of('e-num')}/", "E"),
    (f"{_MFAM.RESEARCH_DIR}/", "D"),
    (f"{_MFAM.LEGACY_RESEARCH_DIR}/", "G"),
    ("out/package/", "G"),
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


def statement_author_of(store: Any, label: str) -> dict[str, Any]:
    """运行期按命题号读作者（`{checked, author, source, reason}`，三态）。

    只认两种可信来源：

    - `statements.proof_authors`：显式登记的作者（穷举型证据那一档早就在写，
      普通证明由 :func:`author_reading` + `recorded` 在收录那一刻写）；
    - `statements.created_by` 且它点名的是角色（`agent-F`）：那是"谁创建了这一行"。

    `created_by="secretary-B"` 不算作者：B 的秘书写这一行 = B 把证明收录进册，
    那是登记动作，不是写作（「F 写的证明，F 送审……B 侧收录」）。认成作者会让
    "替人送审"这一档永远看不见。

    读不到作者时 `checked=False` + 原因；调用方记 `author_not_recorded`，
    不许默认成"作者就是送审者"（那是猜）。
    """
    from . import statementledger as SL

    out: dict[str, Any] = {"checked": False, "author": "", "source": "", "reason": ""}
    sid = str(label or "").split("#", 1)[0]
    if store is None or not sid:
        out["reason"] = "没有 store / 没有命题号 ⇒ 作者读不到"
        return out
    # 按号定位走查口（口径一）；读不到与不在册在这一层分得开。
    by_id = SL.by_id(store, stmt_id=sid)
    if not by_id["checked"]:
        err = by_id.get("error") or {}
        out["reason"] = (f"statements 读不出来（{err.get('type', '?')}: "
                         f"{err.get('message', '?')}）")
        return out
    row = by_id["row"]
    if not row:
        out["reason"] = f"命题 {sid} 不在册 ⇒ 作者读不到"
        return out
    authors = row.get("proof_authors")
    if isinstance(authors, (list, tuple)):
        for one in authors:
            role = _role_of(one)
            if role:
                out.update(checked=True, author=role, source="proof_authors",
                           reason=f"proof_authors 登记为 {role}")
                return out
    created = str(row.get("created_by") or "")
    if not created.lower().startswith(("secretary-", "secretary_")):
        role = _role_of(created)
        if role:
            out.update(checked=True, author=role, source="created_by",
                       reason=f"created_by={created} 点名了角色 {role}")
            return out
    out["reason"] = (f"作者没有登记（created_by={created or '（空）'} 是登记口，不是作者）"
                     "⇒ 这一格记作者未记录，不猜")
    return out
