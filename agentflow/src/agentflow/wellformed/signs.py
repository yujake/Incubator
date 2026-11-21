# -*- coding: utf-8 -*-
"""
vsigns 那一类：`out/vsigns/<artifact_sha>.json` 侧文件的格、号、时刻与条数。
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .predicates import _is_hex64, _is_int, _is_iso, _shown
from .registry import _Ctx, _local_finding, _rule
from .states import Finding


# ---- vsigns：`out/vsigns/<artifact_sha>.json`

#: 侧文件必须带的格。`count` 不在里面：老盘（2026-10 那批）用 `streak` 装同一个数，
#: 两种写法读者都认（`vsigns._entry_of`），所以"数了几转"那一格按 `count` 或 `streak`
#: 任一存在即可（见下面的 passes 规则）。
_VSIGN_KEYS: tuple[str, ...] = (
    "schema", "artifact_sha", "artifact_path", "at", "need", "passes",
)


@_rule("vsigns", "required_keys")
def _rule_vsign_required(ctx: _Ctx) -> list[Finding]:
    """侧文件必须带的那几格（缺一格，签名就少一个可核的坐标）。"""
    out: list[Finding] = []
    obj = ctx.obj if isinstance(ctx.obj, Mapping) else {}
    for key in _VSIGN_KEYS:
        if key not in obj:
            out.append(_local_finding(
                ctx, "vsign_required_key",
                f"侧文件缺 `{key}` 这一格（现有键：{sorted(obj)}）⇒ 签名少一个可核坐标；"
                f"补写时按 `vsigns.write_sign` 的落点重发这一签，不手工拼"))
    return out


@_rule("vsigns", "schema")
def _rule_vsign_schema(ctx: _Ctx) -> list[Finding]:
    """`schema` 必须是 `vsign/1`（换版本要有迁移，不许静默混读）。"""
    obj = ctx.obj if isinstance(ctx.obj, Mapping) else {}
    got = obj.get("schema")
    if got != "vsign/1":
        return [_local_finding(ctx, "vsign_schema",
                               f"`schema` 读到 {_shown(got)}，应为 'vsign/1'",
                               field_name="schema", severity="warning")]
    return []


@_rule("vsigns", "artifact_sha")
def _rule_vsign_sha(ctx: _Ctx) -> list[Finding]:
    """`artifact_sha` 必须是 64 位小写十六进制，且等于文件名。"""
    out: list[Finding] = []
    obj = ctx.obj if isinstance(ctx.obj, Mapping) else {}
    got = obj.get("artifact_sha")
    if not _is_hex64(got):
        out.append(_local_finding(
            ctx, "vsign_artifact_sha",
            f"`artifact_sha` 读到 {_shown(got)}，不是 64 位小写十六进制 ⇒ "
            "这一签认不出被签的是哪一份正文", field_name="artifact_sha"))
        return out
    stem = ctx.path.stem if ctx.path is not None else ""
    if stem and stem != got:
        out.append(_local_finding(
            ctx, "vsign_name_mismatch",
            f"文件名是 `{stem}`，而文件里的 `artifact_sha` 是 `{got}` ⇒ 两者必须是同一个值"
            "（文件名就是这一签的键，对不上则按名找不到它）", field_name="artifact_sha"))
    return out


@_rule("vsigns", "passes")
def _rule_vsign_passes(ctx: _Ctx) -> list[Finding]:
    """`count` 与 `passes` 的条数必须相等，每一转都要能追溯到一条台账行。"""
    out: list[Finding] = []
    obj = ctx.obj if isinstance(ctx.obj, Mapping) else {}
    passes = obj.get("passes")
    count = obj.get("count", obj.get("streak"))
    if "count" not in obj and "streak" not in obj:
        return [_local_finding(ctx, "vsign_count_shape",
                               "既没有 `count` 也没有 `streak` ⇒ 这一签没有数过几转")]
    if not isinstance(passes, list):
        return [_local_finding(ctx, "vsign_passes_shape",
                               f"`passes` 读到 {_shown(passes)}，应为数组",
                               field_name="passes")]
    if not _is_int(count):
        out.append(_local_finding(ctx, "vsign_count_shape",
                                  f"`count` 读到 {_shown(count)}，应为整数",
                                  field_name="count"))
    elif count != len(passes):
        out.append(_local_finding(
            ctx, "vsign_count_mismatch",
            f"`count`={count}，而 `passes` 有 {len(passes)} 条 ⇒ 两者必须相等"
            "（count 是这张签自称数了几转）", field_name="count"))
    for i, one in enumerate(passes):
        if not isinstance(one, Mapping):
            out.append(_local_finding(ctx, "vsign_pass_shape",
                                      f"`passes[{i}]` 读到 {_shown(one)}，应为对象",
                                      field_name=f"passes[{i}]"))
            continue
        if not str(one.get("verification_id") or "").strip():
            out.append(_local_finding(
                ctx, "vsign_pass_verification_id",
                f"`passes[{i}]` 没有 `verification_id` ⇒ 这一转指不回台账行",
                field_name=f"passes[{i}].verification_id"))
        if not _is_hex64(one.get("proof_sha256")):
            out.append(_local_finding(
                ctx, "vsign_pass_proof_sha",
                f"`passes[{i}].proof_sha256` 读到 {_shown(one.get('proof_sha256'))}，"
                "不是 64 位小写十六进制", field_name=f"passes[{i}].proof_sha256"))
    need = obj.get("need")
    if _is_int(need) and _is_int(count) and count < need:
        out.append(_local_finding(
            ctx, "vsign_count_below_need",
            f"`count`={count} < `need`={need} ⇒ 这一签的自称凑不满门槛",
            field_name="count"))
    return out


@_rule("vsigns", "stamp")
def _rule_vsign_stamp(ctx: _Ctx) -> list[Finding]:
    """`at` 与 `artifact_path` 的形状（时刻要能解析、路径不许越界）。"""
    out: list[Finding] = []
    obj = ctx.obj if isinstance(ctx.obj, Mapping) else {}
    if not _is_iso(obj.get("at")):
        out.append(_local_finding(ctx, "vsign_at",
                                  f"`at` 读到 {_shown(obj.get('at'))}，不是可解析的 ISO 时刻",
                                  field_name="at", severity="warning"))
    rel = obj.get("artifact_path")
    if not isinstance(rel, str) or not rel.strip():
        out.append(_local_finding(ctx, "vsign_artifact_path",
                                  f"`artifact_path` 读到 {_shown(rel)}，应为工作区相对路径",
                                  field_name="artifact_path", severity="warning"))
    elif Path(rel).is_absolute() or ".." in Path(rel).parts:
        out.append(_local_finding(
            ctx, "vsign_artifact_path_escape",
            f"`artifact_path` 读到 {_shown(rel)}，越出工作区 ⇒ 这一签指不回本工作区的稿",
            field_name="artifact_path"))
    return out
