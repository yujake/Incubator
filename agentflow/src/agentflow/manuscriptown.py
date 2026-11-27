# -*- coding: utf-8 -*-
"""稿的归属：一个角色实例只对自己产出的稿负责，对别的实例产出的稿无写权。

业主口径（2026-11-27，逐字）：「一个角色实例只对自己产出的稿负责，对别的实例产出的稿无写权」。

## 归属记在哪
稿头那一行 `- 产出者：agent-B-B1`（各族的写口本来就会写）。这里只读它，不新开归属表 ——
同一件事两处记，迟早漂。

## 三态（不折平）
- 稿不在盘上 ⇒ `owner=""`、`checked=True`、`newly_created=True`：这是新建，归属由写它的实例登记；
- 稿在、有 `产出者` ⇒ `checked=True`，比对实例；
- 稿在、没有 `产出者`（旧盘 / 手写）⇒ `checked=False`：归属不明不等于"无主"，写入按受控拒处理，
  要改它得先在稿头补上产出者（或由人裁定），不许把"查不出"读成"我能写"。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

#: 稿头那一行的前缀（各族写口同一格式；行首可有 `- `）。
OWNER_PREFIX = "产出者："
OWNER_PREFIX_ASCII = "产出者:"

CODE_OWNED_BY_OTHER = "manuscript_owned_by_other_instance"
CODE_OWNER_UNKNOWN = "manuscript_owner_unknown"


def owner_of_text(text: str) -> str:
    """稿头的产出者实例（`agent-B-B1` 这种）；没有 ⇒ 空串。"""
    for line in str(text or "").splitlines()[:30]:
        raw = line.strip().lstrip("-").strip()
        if raw.startswith(OWNER_PREFIX):
            return raw[len(OWNER_PREFIX):].strip()
        if raw.startswith(OWNER_PREFIX_ASCII):
            return raw[len(OWNER_PREFIX_ASCII):].strip()
    return ""


def owner_reading(root: Any, rel: str) -> dict[str, Any]:
    """这一份稿归谁：`{checked, rel, exists, owner, why}`（三态，见模块 docstring）。"""
    out: dict[str, Any] = {"checked": True, "rel": str(rel or ""),
                           "exists": False, "owner": "", "why": ""}
    path = Path(str(root or "")) / str(rel or "")
    if not str(root or "") or not str(rel or ""):
        out.update(checked=False, why="没有工作区根或没有稿路径 ⇒ 这一格没查成")
        return out
    if not path.is_file():
        out["why"] = "稿不在盘上 ⇒ 这是新建（归属由写它的实例登记）"
        return out
    out["exists"] = True
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # noqa: BLE001 —— 读不成要说清
        out.update(checked=False, why=f"稿读不出来（{type(exc).__name__}: {exc}）⇒ 归属没查成")
        return out
    out["owner"] = owner_of_text(text)
    if not out["owner"]:
        out.update(checked=False,
                   why="稿上没有 `产出者` ⇒ 归属不明（不明不等于无主；要改先补产出者或由人裁定）")
    return out


def write_refusal(root: Any, rel: str, *, instance: str) -> dict[str, Any]:
    """这一笔写入允不允许：`{allowed, code, why, owner, checked}`。

    - 新建（稿不在盘上）⇒ 允许；
    - 归属 == 本实例 ⇒ 允许；
    - 归属是别的实例 ⇒ 拒（`manuscript_owned_by_other_instance`）；
    - 归属查不出（无 `产出者` / 读不出）⇒ 拒（`manuscript_owner_unknown`），不折成"允许"。
    """
    got = owner_reading(root, rel)
    who = str(instance or "").strip()
    out: dict[str, Any] = {"allowed": False, "code": "", "why": "", "checked": got["checked"],
                           "owner": got["owner"], "rel": got["rel"]}
    if not got["exists"]:
        out.update(allowed=True, why="新建这一份稿（盘上还没有）")
        return out
    if not got["checked"]:
        out.update(code=CODE_OWNER_UNKNOWN, why=got["why"])
        return out
    if got["owner"] == who and who:
        out.update(allowed=True, why=f"归属是本实例（{who}）")
        return out
    out.update(code=CODE_OWNED_BY_OTHER,
               why=(f"这一份稿的产出者是 {got['owner']!r}，而当前实例是 {who!r} ⇒ "
                    "一个实例只对自己产出的稿负责（写别人的稿无权限）"))
    return out


def same_owner(a: str, b: str) -> bool:
    """两个实例标签是不是同一个（`agent-C` 与 `agent-C-C1` 不算同一个实例）。

    归一只去 `agent-` 前缀与空白：实例粒度必须保留 —— 把"同一个角色"当"同一个实例"
    会让一个实例的稿号清单被另一个实例继承（那正是这次要堵的那条）。
    """
    def _k(v: str) -> str:
        s = str(v or "").strip()
        return s[len("agent-"):] if s.startswith("agent-") else s
    return _k(a) == _k(b) and bool(_k(a))
