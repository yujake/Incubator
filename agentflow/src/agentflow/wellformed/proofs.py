# -*- coding: utf-8 -*-
"""
proof_reports 那一类：`reports/*-proof-*.md` 的两节正文与签块正文 sha。
"""

from __future__ import annotations

import json
from typing import Mapping

from .. import manuscriptfamily as MFAM
from .predicates import _Unchecked, _is_hex64, _shown
from .reader import _read_json
from .registry import _Ctx, _local_finding, _rule
from .states import Finding


# ---- proof_reports：`reports/*-proof-*.md`


def _section_body(text: str, name: str) -> tuple[bool, str]:
    """切出 `## <name>` 那一节的正文（不含后续小节）。返回 `(小节在不在, 正文)`。"""
    lines = text.replace("\r\n", "\n").split("\n")
    starts = [i for i, ln in enumerate(lines)
              if ln.strip() == f"## {name}" or ln.strip().startswith(f"## {name} ")]
    if not starts:
        return False, ""
    head = starts[-1]
    body: list[str] = []
    for ln in lines[head + 1:]:
        if ln.startswith("## "):
            break
        body.append(ln)
    return True, "\n".join(body).strip()


@_rule("proof_reports", "sections")
def _rule_proof_sections(ctx: _Ctx) -> list[Finding]:
    """证明稿必须有 `## 命题` 与 `## 证明`，且两节正文非空。"""
    text = ctx.obj if isinstance(ctx.obj, str) else ""
    out: list[Finding] = []
    has_prop, prop = _section_body(text, "命题")
    has_proof, proof = _section_body(text, "证明")
    if not has_prop:
        out.append(_local_finding(ctx, "proof_proposition_section",
                                  "没有 `## 命题` 这一节 ⇒ 不知道这份稿证的是什么"))
    elif not prop:
        out.append(_local_finding(ctx, "proof_proposition_empty",
                                  "`## 命题` 这一节是空的", severity="warning"))
    if not has_proof:
        out.append(_local_finding(ctx, "proof_section_missing",
                                  "没有 `## 证明` 这一节 ⇒ 这份稿不是一份证明"))
    elif not proof:
        out.append(_local_finding(ctx, "proof_body_empty",
                                  "`## 证明` 这一节是空的 ⇒ 有节名没有正文"))
    return out


@_rule("proof_reports", "sign_sha")
def _rule_proof_sign_sha(ctx: _Ctx) -> list[Finding]:
    """签块里的 `正文sha` 要能对上 `out/vsigns/<sha>.json` 那一份侧文件。"""
    from .. import vsigns as VS

    text = ctx.obj if isinstance(ctx.obj, str) else ""
    reading = VS.manuscript_sign_reading(text, manuscript_path=ctx.rel)
    if not reading.get("found"):
        return []
    out: list[Finding] = []
    if reading.get("problem"):
        out.append(_local_finding(ctx, "proof_sign_block",
                                  f"签块读不成形：{reading.get('problem')}",
                                  severity="warning"))
    if not reading.get("signed"):
        return out
    sha = str(reading.get("proof_sha256") or "")
    if not _is_hex64(sha):
        return out
    if ctx.root is None:
        raise _Unchecked("没有工作区根，签块正文 sha 对应的侧文件查不了")
    sign_file = ctx.root / "out" / "vsigns" / f"{sha}.json"
    if not sign_file.is_file():
        out.append(_local_finding(
            ctx, "proof_sign_file_missing",
            f"签块说 `已签=true`、`正文sha={sha}`，而 `out/vsigns/{sha}.json` 不存在 ⇒ "
            "这一签没有侧文件（稿上说签过，盘上找不到那一签）"))
        return out
    try:
        side = _read_json(sign_file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _Unchecked(f"侧文件 {sign_file.name} 读不出来（{type(exc).__name__}）") from exc
    side_sha = side.get("artifact_sha") if isinstance(side, Mapping) else None
    if side_sha != sha:
        out.append(_local_finding(
            ctx, "proof_sign_sha_mismatch",
            f"签块 `正文sha={sha}`，而侧文件里的 `artifact_sha` 是 {_shown(side_sha)} ⇒ "
            "两份签不是同一份正文"))
    return out
