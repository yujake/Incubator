# -*- coding: utf-8 -*-
"""手稿的族 / 号 / 后缀的唯一判定表。

## 为什么必须是一个新模块

族判定原来散落在各模块（前缀表、名字解析、候选名拼接、路径拼法…），它们"恰好一致"
只是因为字符串没被人改过。本模块把那一列事实收成一张表：族 → 前缀 → 允许目录 →
号形 → 证明号后缀 → 签要不要 → 允许格 / 派生列 / `evidence_kind` / `kind` 缺省 /
出处。其余模块只做派生（re-export），不再各写字面量。

## 边界

纯函数、零 I/O、零内部依赖（只 import 标准库）。判据在
`tests/test_manuscript_family_is_one_table.py`。

## 五档读数

`tier` 是权威的读法：`family`（规范名）/ `legacy`（历史名，可列出、可 preview、
不可签、不可收录）/ `bad_name`（像手稿但号解析不出）/ `unrecognized`（不是手稿）。
`-v2` 一类历史后缀只读成 `legacy`，`proof_no` 恒为 0：把它读成 `-p2` 等于把一份
未审、且已知有缺陷的稿变成正式证明。
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

#: 规范手稿所在的那一层目录（目录是身份的一部分：名字对了、目录不对 ⇒ `legacy`）。
MANUSCRIPT_DIR = "reports"

#: 四族的固定顺序（拼名、遍历、报错都按它，避免"字典序"成为第二份口径）。
FAMILY_ORDER: tuple[str, ...] = ("f-proof", "b-proof", "e-proof", "e-num")

#: 读档名（不是族）。它出现在 `FAMILIES` 里只为让"表里查一下"对五档都成立。
LEGACY_FAMILY = "legacy"

#: 四档名字读数（`bad_name` 与 `unrecognized` 是两件事：前者像手稿、号解析不出）。
TIER_FAMILY = "family"
TIER_LEGACY = "legacy"
TIER_BAD = "bad_name"
TIER_UNRECOGNIZED = "unrecognized"
TIERS: tuple[str, ...] = (TIER_FAMILY, TIER_LEGACY, TIER_BAD, TIER_UNRECOGNIZED)

#: 收录格的闭集。族的 `allowed` 只能是它的子集。
INGEST_CELLS: tuple[str, ...] = (
    "statement_full", "proof_text", "dependencies", "kind", "numeric_evidence")

#: 受控码。`bad_manuscript_name` 与 vsigns 既有取值的字面量相同（历史读法不变）。
CODE_LEGACY = "legacy_manuscript_name"
CODE_BAD = "bad_manuscript_name"
CODE_NOT_MANUSCRIPT = "manuscript_not_in_family"
CODE_NUMERIC_NOT_SIGN = "numeric_manuscript_is_not_a_sign_carrier"
CODE_PLAN_NOT_SIGN = "plan_is_not_a_sign_carrier"


@dataclass(frozen=True)
class FamilySpec:
    """一族手稿的全部声明（身份列 + 行为列）。

    为什么用冻结的 dataclass 而不是字典：表是唯一真身，冻结之后"某处在运行时改一格"
    这种漂移在结构上不可能发生；字段名也让"哪一格是签、哪一格是派生列"在读者面前
    是显式的，而不是靠键名猜。
    """

    family: str
    prefix: str
    directories: tuple[str, ...]
    id_pattern: str
    proof_suffix: bool
    needs_sign: bool
    tier: str
    allowed: tuple[str, ...]
    default: tuple[str, ...]
    derived: tuple[str, ...]
    evidence_kind: str
    evidence_kind_from_sign: bool
    kind_default: str
    kind_default_from_ledger: bool
    line_range_origin: str


#: 唯一判定表：四族 + `legacy` 读档。
#:
#: 各列的含义：
#: - `prefix` / `directories` / `id_pattern` / `proof_suffix`：身份（`reports/` 是唯一
#:   允许目录；`f-proof` 的号可以是 `plan-<数字>`；`e-num` 不设 `-pN`）；
#: - `needs_sign`：要不要 V 的签（`e-num` 走绿色通道）；
#: - `allowed` / `default`：可请求格与缺省格（`statement_full` 只在 register 可写）；
#: - `derived`：写口顺带写的列（五元位 / 证明号 / 正文 sha / 签后升档的 kind / proofs）；
#: - `evidence_kind`：`b-proof` 为空串是有意的 —— 它按签现算，不是表里一个定值；
#: - `kind_default`：`b-proof` 为空串是有意的 —— 它取台账现值，不覆写；
#: - `line_range_origin`：出处那一格读哪里（`manuscript_path` 读稿路径，
#:   `experiment_id` 读 `exp:<实验号>`）。
FAMILIES: Mapping[str, FamilySpec] = MappingProxyType({
    "f-proof": FamilySpec(
        family="f-proof", prefix="f-proof-", directories=(MANUSCRIPT_DIR,),
        id_pattern=r"\d{4,6}|plan-\d+", proof_suffix=True, needs_sign=True,
        tier=TIER_FAMILY,
        allowed=("statement_full", "proof_text", "dependencies", "kind"),
        default=("statement_full", "proof_text", "dependencies"),
        derived=("bits", "proof_no", "proof_sha256", "kind", "proofs"),
        evidence_kind="heuristic", evidence_kind_from_sign=False,
        kind_default="conjecture", kind_default_from_ledger=False,
        line_range_origin="manuscript_path",
    ),
    "b-proof": FamilySpec(
        family="b-proof", prefix="b-proof-", directories=(MANUSCRIPT_DIR,),
        id_pattern=r"\d{4,6}", proof_suffix=True, needs_sign=True,
        tier=TIER_FAMILY,
        allowed=("proof_text", "dependencies", "kind"),
        default=("proof_text", "dependencies"),
        derived=("bits", "proof_no", "proof_sha256", "kind", "proofs"),
        evidence_kind="", evidence_kind_from_sign=True,
        kind_default="", kind_default_from_ledger=True,
        line_range_origin="manuscript_path",
    ),
    "e-proof": FamilySpec(
        family="e-proof", prefix="e-proof-", directories=(MANUSCRIPT_DIR,),
        id_pattern=r"\d{4,6}", proof_suffix=True, needs_sign=True,
        tier=TIER_FAMILY,
        allowed=("statement_full", "proof_text", "dependencies", "kind"),
        default=("statement_full", "proof_text", "dependencies"),
        derived=("bits", "proof_no", "proof_sha256", "kind", "proofs"),
        evidence_kind="proof", evidence_kind_from_sign=False,
        kind_default="theorem", kind_default_from_ledger=False,
        line_range_origin="experiment_id",
    ),
    "e-num": FamilySpec(
        family="e-num", prefix="e-num-", directories=(MANUSCRIPT_DIR,),
        id_pattern=r"\d{4,6}", proof_suffix=False, needs_sign=False,
        tier=TIER_FAMILY,
        allowed=("statement_full", "numeric_evidence"),
        default=("statement_full", "numeric_evidence"),
        derived=("bits", "grade"),
        evidence_kind="cross_check", evidence_kind_from_sign=False,
        kind_default="conjecture", kind_default_from_ledger=False,
        line_range_origin="experiment_id",
    ),
    LEGACY_FAMILY: FamilySpec(
        family=LEGACY_FAMILY, prefix="", directories=(), id_pattern="",
        proof_suffix=False, needs_sign=False, tier=TIER_LEGACY,
        allowed=(), default=(), derived=(),
        evidence_kind="", evidence_kind_from_sign=False,
        kind_default="", kind_default_from_ledger=False,
        line_range_origin="",
    ),
})

#: 号形（按族：`f-proof` 多一个 `plan-<数字>`）。
_ID_RE: Mapping[str, re.Pattern[str]] = MappingProxyType({
    "f-proof": re.compile(r"^(?:\d{4,6}|plan-\d+)$"),
    "b-proof": re.compile(r"^\d{4,6}$"),
    "e-proof": re.compile(r"^\d{4,6}$"),
    "e-num": re.compile(r"^\d{4,6}$"),
})

#: 证明号后缀（`-p<N>`，N 是 >=1 的十进制；`-p0` / `-pabc` 不认）。`e-num` 不设。
_PROOF_REST_RE = re.compile(r"^(?P<id>\d{4,6}|plan-\d+)(?:-p(?P<no>[1-9]\d*))?$")
_PROOF_REST_NUM_RE = re.compile(r"^(?P<id>\d{4,6})(?:-p(?P<no>[1-9]\d*))?$")
_NUM_REST_RE = re.compile(r"^(?P<id>\d{4,6})$")
#: 历史后缀（`-v<N>`，N 含 0）：只读成历史档，不当 `-pN`。
_LEGACY_REST_RE = re.compile(r"^(?P<id>\d{4,6})-v(?P<v>\d+)$")


def _spec(family: Any) -> FamilySpec:
    """族名 ⇒ 表里那一行；未知族抛 `ValueError`（不猜一个前缀出来）。"""
    got = FAMILIES.get(str(family or "").strip())
    if got is None:
        raise ValueError(
            f"未知手稿族 {family!r}：只有 {', '.join(FAMILY_ORDER)}；"
            f"`{LEGACY_FAMILY}` 是读档、不是可写的族")
    return got


def _split_rel(rel: Any) -> tuple[str, str]:
    """工作区相对路径 ⇒ `(目录, 去掉 .md 的文件名)`（路径分隔符统一成 `/`）。

    目录取 `rsplit` 之前的那一段。`reports/b-proof-000001.md` ⇒ `("reports", "b-proof-000001")`；
    `b-proof-000001.md`（没有目录）⇒ `("", "b-proof-000001")`。判据只认目录恰好是
    `reports` 这一种，深层目录（`a/reports/...`）不算。
    """
    raw = str(rel or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts:
        return "", ""
    name = parts[-1]
    if name.lower().endswith(".md"):
        name = name[:-3]
    return "/".join(parts[:-1]), name


def _is_file_name(rel: Any) -> bool:
    """这个名字是不是「一份真文件的名字」：末段以 `.md` 结尾（大小写不敏感）。

    只读字符串、不 stat 盘：盘上有没有这一份不是名字的问题。这一格是「签的载体」
    判定的一部分（:func:`sign_carrier`）—— 载体是真文件的名字，
    `reports/f-proof-000000`（缺扩展名）不是。`vsigns` 的两条口（签载体 / pending
    载体）都只读这里，判据没有第二份 `.md` 判定。
    """
    raw = str(rel or "").strip().replace("\\", "/")
    tail = raw.rsplit("/", 1)[-1] if raw else ""
    return tail.lower().endswith(".md")


def _shape_of_name(name: str) -> dict[str, Any]:
    """只看文件名 ⇒ 五档读数（目录不参与；`classify_name` 与 `classify_manuscript` 共用这一处）。

    为什么把"名字形状"与"目录"分开：`sign_carrier` 要两者都判（`notes/b-proof-*`
    不是签的载体），而 fs 保留表只拿得到文件名（它判"这个名字是不是手稿形"）。
    两件事分在一个函数的输入边界上，比在一个函数里写两条正则更不容易漂。
    """
    out: dict[str, Any] = {
        "tier": TIER_UNRECOGNIZED, "name_family": "", "manuscript_id": "",
        "proof_no": 0, "suggested_no": 1, "code": CODE_NOT_MANUSCRIPT,
        "why": "", "checked": True, "name": name,
    }
    if not name:
        out["why"] = "没有文件名 ⇒ 不是手稿（签要有对象，稿要有名字）"
        return out
    for family in FAMILY_ORDER:
        spec = _spec(family)
        if not name.startswith(spec.prefix):
            continue
        rest = name[len(spec.prefix):]
        out["name_family"] = family
        # 1) 规范名：号 + 可选的 -pN（e-num 不设后缀）。
        matched = None
        if family == "e-num":
            matched = _NUM_REST_RE.match(rest)
        elif family == "f-proof":
            matched = _PROOF_REST_RE.match(rest)
        else:
            matched = _PROOF_REST_NUM_RE.match(rest)
        if matched is not None:
            no = int(matched.groupdict().get("no") or 1)
            out.update(tier=TIER_FAMILY, manuscript_id=str(matched.group("id")),
                       proof_no=no, suggested_no=no, code="",
                       why=(f"`{name}` ⇒ 族 {family}、稿号 {matched.group('id')}、"
                            f"证明号 {no}"))
            return out
        # 2) 历史名：规范的号 + 非规范后缀 -vN（只读档）。
        legacy = _LEGACY_REST_RE.match(rest)
        if legacy is not None:
            version = int(legacy.group("v"))
            out.update(tier=TIER_LEGACY, manuscript_id=str(legacy.group("id")),
                       proof_no=0, suggested_no=max(version, 1),
                       code=CODE_LEGACY,
                       why=(f"历史后缀 -v{version}：不可签、不可收录；"
                            "它不能当第 N 份证明（-v2 不是 -p2）"))
            return out
        # 3) 像手稿、号却解析不出（受控拒那一档）。
        out.update(tier=TIER_BAD, proof_no=0, code=CODE_BAD, checked=False,
                   why=(f"手稿名 {name!r} 认不出号：要 "
                        f"{spec.prefix}<号>[-p<N>].md（号是 4-6 位十进制"
                        + ("，或 plan-<数字>" if family == "f-proof" else "")
                        + "；-p<N> 的 N 是 >=1 的十进制）"))
        return out
    out["why"] = (f"不是手稿族的名字（没有 {', '.join(s.prefix for s in FAMILIES.values() if s.prefix)}"
                  " 前缀）")
    return out


def _canonical_of(name_family: str, manuscript_id: str, proof_no: int) -> str:
    """历史名 ⇒ 规范名（`reports/<族>-<号>[-pN].md`）；拼不出 ⇒ 空串。"""
    if not name_family or not manuscript_id:
        return ""
    try:
        return relpath(name_family, manuscript_id, proof_no)
    except ValueError:
        return ""


def classify_manuscript(rel: Any) -> dict[str, Any]:
    """工作区相对路径 ⇒ 五档读数（目录参与身份判定）。

    为什么不叫 `classify`：`projects.classify` 先存在，判的是项目目录状态
    （workspace / archive …），与"这份稿属于哪一族"是两个语义；短名撞车还会让 R003
    （公开名在多模块里有独立实现）报两条告警，而它们本来就不该合并。

    返回键：`tier` / `family` / `name_family` / `id` / `proof_no` / `code` / `why` /
    `checked` / `name` / `directory` / `canonical`。

    - `reports/<四族规范名>` ⇒ `tier=family`，`family` 是族名；
    - 同一个名字换到别的目录（`notes/`、`out/`）⇒ `tier=legacy`（名字对、目录不对）；
    - `-vN` ⇒ `tier=legacy`，`proof_no=0`；
    - `f-proof-abc` ⇒ `tier=bad_name`（像手稿、号解析不出）；
    - `RESEARCH.md` / `notes/A.md` ⇒ `tier=unrecognized`。

    为什么 `legacy` 的 `proof_no` 恒为 0：所有"按号认签 / 按号寻址"的读侧遇到 0 都会
    自然拒（`as_proof_no` 那一族的既有口径），不需要每一处再加分支；而且 `-v2` 与 `-p2`
    本来就不是同一个东西。

    `family` 在 `legacy` 档返回 `legacy`（不是族，是读档）；名字本来属于哪一族放在
    `name_family` 里 —— 拼规范名、看"它本来是 b-稿"时读后者。
    """
    directory, name = _split_rel(rel)
    shape = _shape_of_name(name)
    tier = str(shape["tier"])
    family = str(shape["name_family"])
    proof_no = int(shape["proof_no"])
    code = str(shape["code"])
    why = str(shape["why"])
    canonical = ""
    if tier == TIER_FAMILY:
        spec = _spec(family)
        if directory not in spec.directories:
            tier = TIER_LEGACY
            code = CODE_LEGACY
            proof_no = 0
            canonical = _canonical_of(family, str(shape["manuscript_id"]),
                                      int(shape["suggested_no"]))
            why = (f"名字是 {family} 的规范名，但目录 {directory or '(根)'!r} 不是 "
                   f"`{MANUSCRIPT_DIR}/` ⇒ 读成历史档：可列出、可 preview、不可签、不可收录；"
                   f"规范名是 {canonical or '（拼不出）'}")
    elif tier == TIER_LEGACY:
        canonical = _canonical_of(family, str(shape["manuscript_id"]),
                                  int(shape["suggested_no"]))
        why = f"{why}；规范名是 {canonical or '（拼不出）'}"
    return {
        "tier": tier,
        "family": family if tier == TIER_FAMILY else (LEGACY_FAMILY if tier == TIER_LEGACY else ""),
        "name_family": family,
        "id": str(shape["manuscript_id"]),
        "manuscript_id": str(shape["manuscript_id"]),
        "proof_no": proof_no,
        "code": code,
        "why": why,
        "checked": bool(shape["checked"]),
        "name": name,
        "directory": directory,
        "canonical": canonical,
    }


def classify_name(name: Any) -> dict[str, Any]:
    """只按文件名判五档（fs 保留表用）：目录不参与。

    为什么与 `classify_manuscript` 分开：`tools/fs_tools.py` 的保留表在 `fs.write` 那一刻只拿到
    文件名（它判"这个名字该不该被拒写"），而"目录是不是 `reports/`"是收录/签的那一层
    才有的坐标。`notes/b-proof-000001.md` 在这里是 `family`（名字过表），在
    `classify_manuscript` 里是 `legacy`（目录不对）—— 两处都拒写，但读法不同，不许折平。
    """
    shape = _shape_of_name(_split_rel(name)[1])
    tier = str(shape["tier"])
    family = str(shape["name_family"])
    canonical = ""
    if tier == TIER_LEGACY:
        canonical = _canonical_of(family, str(shape["manuscript_id"]),
                                  int(shape["suggested_no"]))
    elif tier == TIER_FAMILY:
        canonical = _canonical_of(family, str(shape["manuscript_id"]),
                                  int(shape["proof_no"]))
    return {
        "tier": tier,
        "family": family if tier == TIER_FAMILY else (LEGACY_FAMILY if tier == TIER_LEGACY else ""),
        "name_family": family,
        "id": str(shape["manuscript_id"]),
        "manuscript_id": str(shape["manuscript_id"]),
        "proof_no": int(shape["proof_no"]) if tier == TIER_FAMILY else 0,
        "code": str(shape["code"]),
        "why": str(shape["why"]),
        "checked": bool(shape["checked"]),
        "name": str(shape["name"]),
        "directory": "",
        "canonical": canonical,
    }


def parse(rel: Any) -> dict[str, Any]:
    """兼容 `vsigns.parse_manuscript_name` 的返回，外加 `tier` / `canonical`。

    与旧读法不同的三处：
    - `-v2` ⇒ `checked=True, tier=legacy, proof_no=0`；
    - `e-num` ⇒ 进族（`family="e-num"`）；
    - `notes/b-proof-*` ⇒ `tier=legacy`（目录不对）。

    `family` 这一格给的是族名（`e-num` 时逐字等于 `"e-num"`）；"名字有族形"这个
    布尔读法在 `is_family` 里（含 `bad_name`）。
    """
    reading = classify_manuscript(rel)
    tier = str(reading["tier"])
    return {
        "checked": bool(reading["checked"]),
        "family": str(reading["family"]),
        "is_family": bool(reading["name_family"]) and tier != TIER_UNRECOGNIZED,
        "manuscript_id": str(reading["manuscript_id"]),
        "proof_no": int(reading["proof_no"]),
        "code": str(reading["code"]),
        "reason": str(reading["why"]),
        "name": str(reading["name"]),
        "tier": tier,
        "canonical": str(reading["canonical"]),
    }


def sign_carrier(rel: Any) -> dict[str, Any]:
    """这一份稿是不是「签的载体」。

    判据：`tier=family`、族要签（`f-proof` / `b-proof` / `e-proof`）、目录是
    `reports/`，且它是一份真文件的名字（末段 `.md`，见 :func:`_is_file_name`）——
    `reports/f-proof-000000`（缺扩展名）不是载体。三类读法因此与旧的两条正则不同：

    - `-v2` / `notes/b-proof-*` ⇒ `ok=False`、码 `legacy_manuscript_name`；
    - `e-num` ⇒ `ok=False`（绿色通道不签）；
    - `f-proof-plan-*`：老盘上的只读兼容名，与数字名同等（`ok=True`，可签）——
      不再新写这种名字，`CODE_PLAN_NOT_SIGN` 只留给老读数解释。

    返回 `{ok, code, why, name, family, tier}`；`ok=False` 不许折成"可以签"。
    """
    reading = classify_manuscript(rel)
    tier = str(reading["tier"])
    family = str(reading["name_family"])
    name = str(reading["name"])
    out: dict[str, Any] = {"ok": False, "code": "", "why": "", "name": name,
                           "family": family, "tier": tier}
    if tier == TIER_FAMILY and family in ("f-proof", "b-proof", "e-proof"):
        if not _is_file_name(rel):
            out.update(code=CODE_BAD,
                       why=(f"`{str(rel or '').strip()}` 缺 `.md` 扩展名 ⇒ 不是一份真文件的"
                            "名字：签的载体只认真文件名（pending 载体同一把尺）"))
            return out
        out.update(ok=True, why=f"`{name}` 是 {family} 的签载体（reports/ 下的规范名）")
        return out
    if tier == TIER_FAMILY and family == "e-num":
        out.update(code=CODE_NUMERIC_NOT_SIGN,
                   why=(f"`{name}` 是 e-num（普通数值档）：绿色通道不收签 —— "
                        "它没有 `## 证明` 可签，收录走 numeric_evidence"))
        return out
    if tier == TIER_LEGACY:
        out.update(code=CODE_LEGACY,
                   why=(f"`{name}` 是历史档：不可签、不可收录；"
                        f"规范名是 {reading['canonical'] or '（拼不出）'}"))
        return out
    if tier == TIER_BAD:
        out.update(code=CODE_BAD,
                   why=f"手稿名 {name!r} 认不出号 ⇒ 不能当签的载体")
        return out
    out.update(code=CODE_NOT_MANUSCRIPT,
               why=f"`{name}` 不是手稿族的名字 ⇒ 不是签的载体")
    return out


def is_sign_carrier(rel: Any) -> bool:
    """`sign_carrier(rel)["ok"]` 的布尔读法（判据只走那一个函数）。

    这是载体判定（族 + 目录 + 真文件名），不是「名字属于签的族」这种形状判定：
    `reports/f-proof-000000`（缺 `.md`）在 :func:`classify_manuscript` 里是
    `tier=family`，但它不是载体 —— `vsigns.is_sign_carrier` 与这里同源，缺 `.md`
    在两边都是 False。
    """
    return bool(sign_carrier(rel).get("ok"))


def relpath(family: Any, id: str = "", proof_no: int = 1, *,
            strict: bool = True) -> str:
    """族 + 号 + 证明号 ⇒ 唯一拼名（`reports/<前缀><号>[-p<N>].md`）。

    为什么要集中拼名：手写拼法散在各处，拼错时的症状是"文件不在盘上"，而每一处都会以
    "查不到"的形式静默通过。这里对号形与证明号做同一套校验，拼出来的名字一定能被
    `parse` 读回原值（往返判据 `tests/test_manuscript_family_is_one_table.py`）。

    `f-proof` 的号可以是 `plan-<数字>`；`e-num` 不设 `-pN`（proof_no 只能是 1）。
    未知族 / 号形不对 / proof_no 不是 >=1 的整数 ⇒ `ValueError`（不猜）。

    `strict=False` 是给"旧调用方本来就把非法输入读成空串"的那一处（`bmanuscript.relpath`
    的返回值契约）：同一套校验，失败时回空串而不是抛。默认永远是 fail-closed。
    """
    def _fail(message: str) -> str:
        if strict:
            raise ValueError(message)
        return ""

    try:
        spec = _spec(family)
    except ValueError as exc:
        return _fail(str(exc))
    if spec.tier != TIER_FAMILY:
        return _fail(f"`{LEGACY_FAMILY}` 是读档，不是可写的族：拼不出规范名")
    got_id = str(id or "").strip()
    if not _ID_RE[spec.family].match(got_id):
        return _fail(
            f"族 {spec.family} 的号形不对：{got_id!r}（要 {spec.id_pattern}；"
            "`plan-<数字>` 只属于 f-proof）")
    try:
        no = int(proof_no)
    except (TypeError, ValueError):
        return _fail(f"证明号要是 >=1 的整数，收到 {proof_no!r}")
    if no < 1:
        return _fail(f"证明号要是 >=1 的整数，收到 {proof_no!r}")
    suffix = f"-p{no}" if spec.proof_suffix and no >= 2 else ""
    if not spec.proof_suffix and no != 1:
        return _fail(f"{spec.family} 不设证明号后缀（一份数值手稿只对应一次实验），"
                     f"收到 proof_no={no}")
    return f"{MANUSCRIPT_DIR}/{spec.prefix}{got_id}{suffix}.md"


def allowed_cells(family: Any) -> tuple[str, ...]:
    """这一族允许请求的格（闭集 `INGEST_CELLS` 的子集；`legacy` 为空）。"""
    return tuple(_spec(family).allowed)


def default_cells(family: Any) -> tuple[str, ...]:
    """这一族的缺省格（调用方没点名时该填哪几格）。"""
    return tuple(_spec(family).default)


def derived_cells(family: Any) -> tuple[str, ...]:
    """这一族的派生列（写口顺带写、调用方永远不能指定的列）。"""
    return tuple(_spec(family).derived)


def needs_sign(family: Any) -> bool:
    """这一族要不要 V 的签（`e-num` 走绿色通道，不要）。"""
    return bool(_spec(family).needs_sign)


def evidence_kind(family: Any) -> str:
    """这一族的 `evidence_kind`；`b-proof` 返回空串（按签现算，不是表里一个定值）。"""
    return str(_spec(family).evidence_kind)


def kind_default(family: Any) -> str:
    """这一族的 `kind` 缺省；`b-proof` 返回空串（取台账现值，不覆写）。"""
    return str(_spec(family).kind_default)


def line_range_origin(family: Any) -> str:
    """出处那一格读哪里：`manuscript_path`（稿路径）或 `experiment_id`（`exp:<号>`）。"""
    return str(_spec(family).line_range_origin)


def prefix_of(family: Any) -> str:
    """族 ⇒ 文件名前缀（`legacy` 没有前缀，返回空串）。"""
    return str(_spec(family).prefix)
