# -*- coding: utf-8 -*-
"""
manuscripts 那一类：`reports/` 里手稿头的名字、标题、命题类型与签块身份。
"""

from __future__ import annotations

from typing import Mapping

from .. import manuscriptfamily as MFAM
from .. import manuscriptkind as MK
from .predicates import _shown
from .registry import _Ctx, _local_finding, _rule
from .states import Finding


# ---- manuscripts：`reports/` 里的稿头


def _manuscript_name(name: str) -> bool:
    """这个名字像不像四族手稿（不像的 `.md` 不归这一档管）。"""
    info = MFAM.classify_manuscript(f"{MFAM.MANUSCRIPT_DIR}/{name}")
    return str(info.get("tier") or "") in (MFAM.TIER_FAMILY, MFAM.TIER_LEGACY,
                                           MFAM.TIER_BAD)


def _proof_name(name: str) -> bool:
    """这个名字是不是"证明稿"（`e-num` 是数值实验稿，没有证明段）。"""
    info = MFAM.classify_manuscript(f"{MFAM.MANUSCRIPT_DIR}/{name}")
    if str(info.get("tier") or "") not in (MFAM.TIER_FAMILY, MFAM.TIER_LEGACY):
        return False
    return str(info.get("name_family") or "").endswith("-proof")


@_rule("manuscripts", "name")
def _rule_ms_name(ctx: _Ctx) -> list[Finding]:
    """像手稿却是 `bad_name` / `legacy`（名字解析不出、或不在 `reports/`）。"""
    out: list[Finding] = []
    info = MFAM.classify_manuscript(ctx.rel)
    tier = str(info.get("tier") or "")
    if tier == MFAM.TIER_BAD:
        out.append(_local_finding(
            ctx, "manuscript_bad_name",
            f"名字像手稿而号解析不出（{info.get('why')}）⇒ 这份稿不能被按号寻址",
            severity="warning"))
    elif tier == MFAM.TIER_LEGACY:
        out.append(_local_finding(
            ctx, "manuscript_legacy_name",
            f"{info.get('why')}", severity="info"))
    return out


@_rule("manuscripts", "title")
def _rule_ms_title(ctx: _Ctx) -> list[Finding]:
    """第一行必须是一级标题（`# `）。"""
    text = ctx.obj if isinstance(ctx.obj, str) else ""
    lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not lines:
        return [_local_finding(ctx, "manuscript_empty", "文件是空的（连标题行都没有）")]
    if not lines[0].startswith("# "):
        return [_local_finding(
            ctx, "manuscript_title",
            f"第一行读到 {_shown(lines[0], 80)}，不是一级标题（`# `）⇒ 稿件没有标题层",
            severity="warning")]
    return []


@_rule("manuscripts", "kind")
def _rule_ms_kind(ctx: _Ctx) -> list[Finding]:
    """稿头的 `- 命题类型：` 若在，值必须非空且在 `KIND_RANK` 里。

    缺这一行不是畸形：`manuscriptkind.kind_crosscheck` 把"稿头没声明"读成
    `manuscript_absent`（合法三态之一，台账才是权威）。声明了却读不出，才是畸形。
    """
    text = ctx.obj if isinstance(ctx.obj, str) else ""
    out: list[Finding] = []
    for mark in (MK.PROPOSITION_KIND_MARK, MK.LEGACY_PROPOSITION_KIND_MARK):
        for raw in text.replace("\r\n", "\n").split("\n"):
            line = raw.strip()
            if not line.startswith(mark):
                continue
            value = line[len(mark):].strip().strip("`").strip().lower()
            if not value:
                out.append(_local_finding(
                    ctx, "manuscript_kind_empty",
                    f"稿头这一行声明了命题类型但是空的：{_shown(line, 80)}"))
            elif value not in MK.KIND_RANK:
                out.append(_local_finding(
                    ctx, "manuscript_kind_vocab",
                    f"稿头声明的命题类型 {value!r} 不在 {tuple(MK.KIND_RANK)} 里"))
    return out


@_rule("manuscripts", "sign_identity")
def _rule_ms_sign_identity(ctx: _Ctx) -> list[Finding]:
    """稿上若有签块，块里的手稿号必须就是它所处那份稿的号。"""
    from .. import vsigns as VS

    text = ctx.obj if isinstance(ctx.obj, str) else ""
    reading = VS.manuscript_sign_reading(text, manuscript_path=ctx.rel)
    if not reading.get("found"):
        return []
    state = str(reading.get("identity_state") or "")
    if state == "unmatched":
        return [_local_finding(
            ctx, "manuscript_sign_identity",
            f"签块认不出属于哪一份稿：{reading.get('identity_why')}")]
    if reading.get("problem"):
        return [_local_finding(
            ctx, "manuscript_sign_block",
            f"签块读不成形：{reading.get('problem')}")]
    return []
