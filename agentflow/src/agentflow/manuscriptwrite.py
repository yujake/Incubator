# -*- coding: utf-8 -*-
"""手稿落盘的三个零件：原子写 / 受控拒绝的返回形状 / "目标名上签住的是不是别的正文"。

## 为什么拆出来

`manuscriptform.py` 在 2026-11-10 的 p274 / p275 两批之后到 810 行（越过 `>800` 的
体量软基线）。它的主职责是"命名 / 渲染 / 搬签 / 落盘事务"；这里搬出来的是落盘事务的
三件零件（它们都只被 `commit_manuscript` 调用），于是 `manuscriptform` 仍只回答
"一份手稿怎么命名、怎么渲染、怎么搬签、怎么落盘"。

## 口径不变

三个函数逐字搬移（含 docstring），`commit_manuscript` 的调用点一个字没改；
`manuscriptform` 回引它们，所以 `manuscriptform._atomic_write` 这个既有名字
（`proofregistry` 也在用）照旧可读。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import proofregistry as _PR
from . import vsigns as _VS


def _atomic_write(path: Path, text: str) -> None:
    """同目录临时文件 + `os.replace`（读侧要么看到旧文件、要么看到新文件）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:  # noqa: BLE001 - 临时文件删不掉不影响主文件已落盘
            pass


def _refusal(out: dict[str, Any], code: str, why: str, *, stage: str,
             **extra: Any) -> dict[str, Any]:
    out.update(ok=False, checked=bool(out.get("checked", True)), refused=code,
               why=str(why or ""),
               problem={"kind": code, "stage": stage, "why": str(why or "")})
    out.update(extra)
    return out


def _signed_version_reading(root: Any, target_rel: str, titled: str,
                            statement_id: str) -> dict[str, Any]:
    """目标名上是不是签住了一份别的正文（与 publish / promote 同一条判据）。

    返回 `{"checked", "blocked", "old_sha", "new_sha", "why"}`；读不出来时
    `checked=False, blocked=True`（"没查成"不许折成"没签"）。
    """
    target = Path(root) / target_rel
    out: dict[str, Any] = {"checked": True, "blocked": False, "old_sha": "",
                           "new_sha": "", "why": ""}
    if not target.is_file():
        return out
    try:
        target_text = target.read_text(encoding="utf-8")
    except OSError as exc:
        out.update(checked=False, blocked=True,
                   why=(f"按号命名的那份稿读不出来（{type(exc).__name__}: {exc}）"
                        "⇒ 不敢覆盖它（它可能已经是签住的那一版）"))
        return out
    block_now = _VS.manuscript_sign_reading(target_text, manuscript_path=target_rel)
    old_sha = _PR.proof_sha(_VS.manuscript_proof_body(target_text))
    new_sha = _PR.proof_sha(_VS.manuscript_proof_body(titled))
    new_block = _VS.manuscript_sign_reading(titled, manuscript_path=target_rel)
    new_signed = bool(new_block.get("found") and new_block.get("signed")
                      and new_block.get("proof_sha256") == new_sha)
    out.update(old_sha=old_sha, new_sha=new_sha)
    if (block_now.get("found") and block_now.get("signed")
            and block_now.get("proof_sha256") == old_sha
            and old_sha != new_sha and not new_signed):
        out.update(blocked=True,
                   why=(f"`{target_rel}` 已经是签住的那一版（正文 sha {old_sha[:12]}…），"
                        f"而这一份的正文是 {new_sha[:12]}… 且它自己没有覆盖它的签 "
                        "⇒ 不覆盖（签另算不是毁签）"))
    return out
