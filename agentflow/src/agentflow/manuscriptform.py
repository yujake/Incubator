# -*- coding: utf-8 -*-
"""证明手稿的唯一实现：命名 / 渲染 / 搬签 / 落盘事务（F 与 B 两族共用）。

## 业主裁定（2026-11-04）

    F 落证明手稿（`reports/f-proof-<号>.md`）与 B 优化证明落稿
    （`reports/b-proof-<号>.md`）在形式上必须完全统一。

改前两族各有一份实现：

| 面 | F 侧（`agent_f/manuscript.py`） | B 侧（`bmanuscript.py`） |
|---|---|---|
| 命名 | `_DS.manuscript_relpath` + `manuscript_path` | `_ID_RE` + `relpath`（自己的正则） |
| 渲染 | `proof_manuscript` 里逐行拼 | `render` 里逐行拼（另一套页头） |
| 搬签 | 模块级 `carry_sign_block` | `land_rewrite` 里的内联"已签就不覆盖" |
| 落盘 | `publish` / `promote` 各一份 | `land_rewrite` 一份 |
| 拒信 | `formal_shape_problem` 的码 | 自己的一组 `why` 文本 |

两份实现必然漂：两份页头一开始就不一样（F 写 `- 计划：`、B 写 `- 标签：`），
而"漂"这件事没有任何一条测试会报 —— 它只会在读稿的那一侧表现成"这份稿不是这一族"。
本模块把上面五面收成一份，`agent_f/manuscript.py` 与 `bmanuscript.py` 只做转发。

## 口径（逐条对应判据）

- 命名：`<prefix>-proof-<号>[-p<N>].md`，解析只走
  :func:`vsigns.parse_manuscript_name`；认不出 ⇒ 受控拒绝 `bad_manuscript_name`。
- 渲染：三节（`## 命题` / `## 证明` / `## 依赖`）+ 洗稿元信息行 +
  `- 命题号：stmt:<号>` 那一行，两族由 :func:`render_proof_manuscript` 同一段代码产出，
  前缀与角色名只是参数。
- 搬签：:func:`carry_sign_block` 只有一份；签块按 sha 相符才搬，第 9 格
  `手稿号` 按新名重算。
- 落盘事务：:func:`commit_manuscript` 一处；写稿 + `## 依赖` 段 + 落
  `dependencies` 边（调用方给 `write_dependencies` 时）同成功同失败 —— 落边失败会把
  刚写的稿回滚到写前（没有过 ⇒ 删掉），不留半截。
- 拒信码：`multiple_propositions` / `not_washed` / `bad_manuscript_name` /
  `no_proof_section` / `dependency_section_missing` 与它们的 detail 文本模板全部在
  本模块定义一次，两族共用。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import depsection as _DS
from . import verifications as _VR
from . import vsigns as _VS

#: 手稿落点（与 `depsection.MANUSCRIPT_DIR` 同一处）。
MANUSCRIPT_DIR = _DS.MANUSCRIPT_DIR

#: 两族的族名（渲染时只影响标题里的角色名，命名时只影响前缀）。
FAMILY_F = "F"
FAMILY_B = "B"
FAMILIES: tuple[str, ...] = (FAMILY_F, FAMILY_B)

#: 族 ⇒ 文件名前缀（命名的唯一来源；别处不许再写一遍字面量）。
#: F 的前缀直接取 `depsection` 那一份（低层常量仍由它持有），B 只有本处一个落点。
PREFIX = {FAMILY_F: _DS.MANUSCRIPT_STMT_PREFIX, FAMILY_B: "b-proof-"}
#: 计划名前缀（只有 F 立项那一轮用；与 `depsection.MANUSCRIPT_PLAN_PREFIX` 同源）。
PLAN_PREFIX = {FAMILY_F: _DS.MANUSCRIPT_PLAN_PREFIX}

#: 稿头里那几行元信息的前缀（渲染与读侧共用）。
STATEMENT_MARK = "- 命题号："
PLAN_MARK = "- 计划："
PROOF_NO_MARK = "- 证明号："
LABEL_MARK = "- 标签："

#: 转正只收工作区相对路径里的这两种根（`notes/` 草稿本、`reports/` 正式落点）。
PROMOTE_SOURCE_ROOTS: tuple[str, ...] = ("notes", "reports")

# ---------------------------------------------------------------- 拒信码（唯一来源）
#
# 业主点名的五个码。detail 模板也只写一次：两族的同一件事必须给人看同一句话，
# 否则"受控拒绝"就退化成"两边各说各的"。

MULTIPLE_PROPOSITIONS = "multiple_propositions"
NOT_WASHED = "not_washed"
BAD_MANUSCRIPT_NAME = _VS.MANUSCRIPT_NAME_BAD
NO_PROOF_SECTION = "no_proof_section"
DEPENDENCY_SECTION_MISSING = _DS.REFUSED_SECTION_MISSING
#: 落边那一步没成 ⇒ 整笔回滚（不是"稿在、边缺一条"）。
DEPENDENCY_EDGES_NOT_WRITTEN = "dependency_edges_not_written"

REFUSAL_CODES: tuple[str, ...] = (
    MULTIPLE_PROPOSITIONS, NOT_WASHED, BAD_MANUSCRIPT_NAME, NO_PROOF_SECTION,
    DEPENDENCY_SECTION_MISSING, DEPENDENCY_EDGES_NOT_WRITTEN)

#: 五个共用的 detail 文本模板（`.format` 的键逐条写在函数里，别在调用点手拼）。
DETAILS: dict[str, str] = {
    MULTIPLE_PROPOSITIONS:
        "稿里有 {count} 节 `## 命题`：一份正式稿只承载一条命题（机械转正只能把整份"
        "文件落成一个命题号的正式稿，其余命题的正文会跟着挂到这一条头上）⇒ 拒绝；"
        "按命题拆成一份一份再交",
    NO_PROOF_SECTION:
        "稿里没有 `## 证明` 那一节 ⇒ 没有可签的正文",
    NOT_WASHED:
        "这一份稿没有 `- 依赖面洗稿：` 那一行（或 `已洗` 不是 true）⇒ 它不是秘书洗过的"
        "那一版，落稿会绕过 B 的洗稿闸；先洗一遍再落稿",
    BAD_MANUSCRIPT_NAME:
        "手稿名 {name!r} 认不出号：要 `<prefix>-proof-<号>[-p<证明号>].md`（号是 4–6 位"
        "十进制，或 `plan-<数字>`；`-p<N>` 的 N 是 ≥1 的十进制）",
    DEPENDENCY_SECTION_MISSING:
        "手稿里没有 `## 依赖` 这一节：依赖面不会按格式登记（证明正文里现在有 {refs} 条"
        " `stmt:` 引用）⇒ B 会整笔拒收 `dependency_section_missing`",
    DEPENDENCY_EDGES_NOT_WRITTEN:
        "依赖边没有落成（{reason}）⇒ 这一笔整笔回滚：稿也回到写前，不留半截",
}

_PROPOSITION_HEAD_RE = re.compile(r"^##\s*命题", re.M)
_PROOF_HEAD_RE = re.compile(r"^##\s*证明", re.M)


def detail(code: str, **kw: Any) -> str:
    """取一条共用 detail 文本（缺键时如实报错，不拼一句缺字的半句）。"""
    return DETAILS.get(code, "{reason}").format(**kw)


def family_prefix(family: Any) -> str:
    """族 ⇒ 文件名前缀；未知族返回空串（不猜一个前缀出来）。"""
    return PREFIX.get(str(family or ""), "")


def _short(text: Any, width: int = 60) -> str:
    """单行化 + 截断（与 `agent_f._support._short` 同一条口径，但本模块不依赖 F）。"""
    s = " ".join(str(text or "").split())
    return s if len(s) <= width else s[: width - 1] + "…"


def _norm_rel(rel: Any) -> str:
    """工作区相对路径的归一（只换分隔符；不猜、不补前缀）。"""
    return str(rel or "").strip().replace("\\", "/")


def is_safe_relpath(rel: Any, roots: Sequence[str] = PROMOTE_SOURCE_ROOTS) -> bool:
    """`rel` 是不是一个安全的工作区相对路径、且落在 `roots` 之一里（`.md`）。"""
    text = _norm_rel(rel)
    if not text or text.startswith("/") or ":" in text:
        return False
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return False
    if len(parts) < 2:
        return False
    return parts[0] in set(roots) and text.casefold().endswith(".md")


# ---------------------------------------------------------------- 命名（唯一解析入口）

def name_reading(family: Any, *, statement_id: Any = "", plan_id: Any = "",
                 proof_no: Any = 1) -> dict[str, Any]:
    """这一族、这个号 ⇒ 约定路径（工作区相对）；认不出就受控拒绝。

    返回 `{"checked", "ok", "family", "path", "name", "manuscript_id",
    "proof_no", "code", "why"}`。解析本体只走 :func:`vsigns.parse_manuscript_name`
    —— 本函数只负责"按族拼出候选名，再让那一个解析器判它认不认得"。
    """
    fam = str(family or "")
    prefix = family_prefix(fam)
    sid = str(statement_id or "").strip()
    pid = str(plan_id or "").strip()
    try:
        no = int(proof_no or 1)
    except (TypeError, ValueError):
        no = 0
    out: dict[str, Any] = {
        "checked": True, "ok": False, "family": fam, "path": "", "name": "",
        "manuscript_id": "", "proof_no": 0, "code": "", "why": "",
    }
    if not prefix:
        out.update(checked=False, code=BAD_MANUSCRIPT_NAME,
                   why=f"未知的手稿族 {family!r}（只认 {FAMILIES}）")
        return out
    if sid:
        name = f"{prefix}{sid}" + (f"-p{no}" if no >= 2 else "")
    elif pid:
        # 计划名只有 F 那一族有（立项那一轮还没有命题号）。
        name = f"{PLAN_PREFIX.get(fam) or (prefix + 'plan-')}{pid}"
    else:
        name = prefix.removesuffix("-")
    rel = f"{MANUSCRIPT_DIR}/{name}.md"
    parsed = _VS.parse_manuscript_name(rel)
    out.update(name=str(parsed.get("name") or name), path=rel,
               manuscript_id=str(parsed.get("manuscript_id") or ""),
               proof_no=int(parsed.get("proof_no") or 0))
    if not (parsed.get("checked") and parsed.get("family")):
        out.update(checked=False, code=BAD_MANUSCRIPT_NAME,
                   why=detail(BAD_MANUSCRIPT_NAME, name=str(parsed.get("name") or name)))
        return out
    if not str(parsed.get("name") or "").startswith(prefix):
        out.update(code=BAD_MANUSCRIPT_NAME,
                   why=(f"手稿名 {parsed.get('name')!r} 不是 {prefix} 这一族的名"
                        f"（这一笔要落的是 {prefix}proof-...）"))
        return out
    if pid and not sid and fam != FAMILY_F:
        out.update(code=BAD_MANUSCRIPT_NAME,
                   why=f"{fam} 这一族没有 `plan-` 名（计划名是 F 立项那一轮的名字）")
        return out
    if out["proof_no"] != (no if no >= 1 else 1):
        out.update(code=BAD_MANUSCRIPT_NAME,
                   why=(f"证明号 {no!r} 拼不出可解析的名字（`-p<N>` 的 N 是 ≥1 的整数）"))
        return out
    want_id = sid if sid else f"plan-{pid}"
    if str(out["manuscript_id"]) != want_id:
        out.update(code=BAD_MANUSCRIPT_NAME,
                   why=(f"手稿名 {rel!r} 解析出来的稿号是 {out['manuscript_id']!r}，"
                        f"而这一笔要的是 {want_id!r}"))
        return out
    out.update(ok=True, why="")
    return out


# ---------------------------------------------------------------- 渲染（唯一实现）

def render_proof_manuscript(
    family: Any, *, title: Any = "", statement_id: Any = "",
    proposition: Any = "", proof_text: Any = "",
    dependency_rows: Iterable[Mapping[str, Any]] = (),
    dependency_section: str = "",
    plan_id: Any = "", sid: Any = "", label: Any = "",
    proof_no: Any = 1, wash_actor: Any = "", wash_filled: Any = "",
) -> str:
    """渲染一份证明手稿（纯函数，逐字节可复现；两族只差前缀与角色名）。

    页头顺序固定：标题 → `- 命题号：` → `- 计划：` → 洗稿行 → `- 证明号：` →
    `- 标签：`。三节顺序固定：`## 命题` / `## 证明` / `## 依赖`。
    `- 计划：`、`- 证明号：`、`- 标签：`、洗稿行都是"给了才写"，但位置不随族变。
    """
    fam = str(family or "")
    role = fam if fam in FAMILIES else FAMILY_F
    sid_text = str(statement_id or "").strip()
    pid = str(plan_id or "").strip()
    sgid = str(sid or "").strip()
    label_text = " ".join(str(label or "").split())
    heading = _short(title or proposition or label_text or "（这一条没有写命题）")
    try:
        no = int(proof_no or 0)
    except (TypeError, ValueError):
        no = 0
    head: list[str] = [
        f"# {role} 的证明手稿：{heading}",
        "",
        f"{STATEMENT_MARK}stmt:{sid_text or '（还没落号）'}",
    ]
    if pid or sgid:
        head.append(f"{PLAN_MARK}{pid} · 子目标：{sgid}")
    if str(wash_actor or "").strip() or str(wash_filled or "").strip():
        parts = [f"{_DS.WASH_MARK_TAG}=true"]
        if str(wash_actor or "").strip():
            parts.append(f"{_DS.WASH_MARK_ACTOR}={str(wash_actor).strip()}")
        if str(wash_filled or "").strip():
            parts.append(f"{_DS.WASH_MARK_FILLED}={str(wash_filled).strip()}")
        head.append(_DS.WASH_MARK + "；".join(parts))
    if no >= 1:
        head.append(f"{PROOF_NO_MARK}{no}")
    if label_text:
        head.append(f"{LABEL_MARK}{label_text}")
    head.extend([
        "",
        "## 命题",
        "",
        str(proposition or "").strip(),
        "",
        "## 证明",
        "",
        str(proof_text or "").strip(),
        "",
        dependency_section or _DS.render_dependency_section(dependency_rows),
    ])
    return "\n".join(head)


# ---------------------------------------------------------------- 形状 / 洗稿 / 依赖段

def formal_shape_problem(text: Any) -> tuple[str, str]:
    """这份稿能不能当一份正式手稿：`(受控码, 人话)`；空串 = 可以。

    机械判据只有两条（不判数学对错）：`## 命题` 恰好一节、`## 证明` 恰好一节且非空。
    """
    body = str(text or "").replace("\r\n", "\n")
    props = _PROPOSITION_HEAD_RE.findall(body)
    proofs = _PROOF_HEAD_RE.findall(body)
    if not props:
        return ("no_proposition_section",
                "稿里没有 `## 命题` 那一节 ⇒ 这不是一份可转正的正式手稿")
    if len(props) > 1:
        return MULTIPLE_PROPOSITIONS, detail(MULTIPLE_PROPOSITIONS, count=len(props))
    if not proofs:
        return NO_PROOF_SECTION, detail(NO_PROOF_SECTION)
    if len(proofs) > 1:
        return ("multiple_proof_sections",
                f"稿里有 {len(proofs)} 节 `## 证明`：一份正式稿只承载一条命题的一份证明")
    if not _DS.proof_body(body).strip():
        return "empty_proof_section", "`## 证明` 那一节是空的 ⇒ 没有可签的正文"
    return "", ""


def dependency_section_problem(text: Any) -> tuple[str, str]:
    """`## 依赖` 那一节读不读得回：`(受控码, 人话)`；空串 = 可以。

    与收方（B）读稿时同一条判据：段读不懂 ⇒ `dependency_section_unreadable`；
    段缺了而证明正文里有 `stmt:` 引用 ⇒ `dependency_section_missing`（同一句模板）；
    段在、表 0 行、而正文点了在册号 ⇒ `deps_table_disagrees_with_proof`（表与正文
    对不上，整份退回并点名第几步 —— 判据本体在
    `depsection.dependency_consistency_problem`，两处共用同一份）；
    段缺了而正文一条引用都没有 ⇒ 合法（自足的证明）。

    ## 这一层拿不到台账 ⇒ 只比表与正文（可引池那一道在收方与 V）

    `dependency_consistency_problem` 的完整判据是"正文里的号必须是可引的（在册 ∧
    等级 ≥ `pre_theorem`）"，再加"表与正文对不上就退"。这一层是落稿 / 落 B 稿的
    校验，手里没有 store ⇒ 交不出可引池，只能比表与正文。这一档至多把一份
    "正文点了号、表 0 行"的手写稿多退回一次；它不会把一条读不到的引用静默放过 ——
    可引池那一道在 B 的登记入口（`register_statement`）与 V 的依赖面审计
    （`depsection.dependency_review`）各有一份，两处都真读台账。
    """
    raw = str(text or "")
    section = _DS.parse_dependency_section(raw)
    if section.get("refused"):
        return str(section.get("refused")), str(section.get("reason") or "")
    if section.get("present"):
        # 2026-11-05（缺陷甲）：那一节在、但表 0 行，而正文点了在册命题 ⇒ 表与正文对不上。
        # 改前这一档直接放行（`present` 就算合格），于是"正文引了、表里没写"整份静默通过。
        return _DS.dependency_consistency_problem(raw)
    refs = _DS.stmt_refs(_DS.proof_body(raw))
    if refs:
        return DEPENDENCY_SECTION_MISSING, detail(
            DEPENDENCY_SECTION_MISSING, refs=len(refs))
    return "", ""


def validate_manuscript(text: Any, *, require_washed: bool = False) -> dict[str, Any]:
    """形状 / 洗稿 / 依赖段三态一次判完（两族共用同一批码与模板）。

    返回 `{"checked", "ok", "code", "why"}`。顺序：形状 → 洗稿 → 依赖段
    （先报更能让人立刻改对的那一条）。
    """
    code, why = formal_shape_problem(text)
    if code:
        return {"checked": True, "ok": False, "code": code, "why": why}
    if require_washed and not bool(_DS.manuscript_wash_reading(text).get("washed")):
        return {"checked": True, "ok": False, "code": NOT_WASHED,
                "why": detail(NOT_WASHED)}
    code, why = dependency_section_problem(text)
    if code:
        return {"checked": True, "ok": False, "code": code, "why": why}
    return {"checked": True, "ok": True, "code": "", "why": ""}


# ---------------------------------------------------------------- 补 / 改「命题号」行

def ensure_statement_line(text: str, statement_id: str) -> tuple[str, bool]:
    """稿头那行 `- 命题号：stmt:<号>`：有就改、没有就插在标题之后（前 12 行内）。"""
    sid = str(statement_id or "").strip()
    raw = str(text or "").replace("\r\n", "\n")
    if not sid:
        return raw, False
    lines = raw.split("\n")
    want = f"{STATEMENT_MARK}stmt:{sid}"
    for i, line in enumerate(lines[:12]):
        if line.strip().startswith(STATEMENT_MARK):
            if line.strip() == want:
                return raw, True
            lines[i] = want
            return "\n".join(lines), True
    at = 1 if lines and lines[0].lstrip().startswith("# ") else 0
    lines.insert(at, want)
    return "\n".join(lines), True


def retitle_statement_line(text: str, statement_id: str) -> tuple[str, bool]:
    """只改已有的 `- 命题号：` 行（没有就不插）—— 改名那一笔的"只是改名不是改稿"。"""
    sid = str(statement_id or "").strip()
    raw = str(text or "").replace("\r\n", "\n")
    if not sid:
        return raw, False
    want = f"{STATEMENT_MARK}stmt:{sid}"
    lines = raw.split("\n")
    for i, line in enumerate(lines[:12]):
        if line.strip().startswith(STATEMENT_MARK):
            if line.strip() == want:
                return raw, True
            lines[i] = want
            return "\n".join(lines), True
    return raw, False


# ---------------------------------------------------------------- 搬签块（唯一实现）

def carry_sign_block(root: Any, titled: str, *, old_rel: str, new_rel: str,
                     statement_id: str) -> dict[str, Any]:
    """把「覆盖这一份正文」的签块搬到新稿名上（纯字符串 + 只读旧稿；不写盘）。

    三态（都不是"失败"）：没块 ⇒ `moved=False`、`problem={}`（签另算）；有块但 sha
    不符 ⇒ `moved=False` + `sign_sha_mismatch`；读块抛异常 ⇒ `sign_block_unreadable`
    （"没查成"不是"没签"）。搬的时候第 9 格 `手稿号` 按新名重算。
    """
    out: dict[str, Any] = {
        "text": titled, "moved": False,
        "reading": {"checked": False, "found": False, "sha_match": None,
                    "moved": False, "candidates": [], "why": ""},
        "problem": {},
    }
    try:
        body_sha = _VR.proof_sha(_VS.manuscript_proof_body(titled))
        candidates: list[tuple[str, str]] = []
        for rel in (old_rel, new_rel):
            rel = _norm_rel(rel)
            if not rel or any(rel == seen for seen, _text in candidates):
                continue
            path = Path(root) / rel
            if not path.is_file():
                continue
            try:
                candidates.append((rel, path.read_text(encoding="utf-8")))
            except OSError:
                continue
        out["reading"]["candidates"] = [rel for rel, _text in candidates]
        for rel, cand in candidates:
            block = _VS.manuscript_sign_reading(cand, manuscript_path=rel)
            if not block.get("found"):
                continue
            out["reading"].update(checked=True, found=True)
            if block.get("proof_sha256") != body_sha:
                out["reading"].update(
                    sha_match=False,
                    why=(f"`{rel}` 里的签块盖的是 "
                         f"{str(block.get('proof_sha256') or '（空）')[:12]}…，"
                         f"而这一份正文是 {body_sha[:12]}… ⇒ 不搬（那不是这一份的签）"))
                continue
            stamped = _VS.stamp_manuscript_sign(
                titled, proof_sha=body_sha,
                streak=block.get("streak"), need=block.get("need"),
                verdict=str(block.get("verdict") or "成立"),
                signer=str(block.get("signer") or "V"),
                at=str(block.get("at") or ""),
                ledger=str(block.get("ledger") or ""),
                statement_id=str(statement_id or ""),
                signed=bool(block.get("signed")),
                manuscript_id=_VS.manuscript_id_of(new_rel))
            out.update(text=stamped, moved=True)
            out["reading"].update(
                sha_match=True, moved=True,
                why=(f"`{rel}` 里的签块与这份正文 sha 相符（{body_sha[:12]}…）"
                     "⇒ 跟着改名搬过来，第 9 格按新稿号重算"))
            return out
        if out["reading"]["found"]:
            # 「搬失败」要真的不搬：把旧块留着会让读侧读成 `stale`/`unmatched`。
            out["text"] = "\n".join(
                line for line in str(titled or "").replace("\r\n", "\n").split("\n")
                if not line.strip().startswith(_VS.SIGN_MARK))
            out["problem"] = {
                "kind": "sign_sha_mismatch", "stage": "sign",
                "why": (str(out["reading"].get("why") or "")
                        + "；改名照做，签块不搬（签另算）"),
            }
        return out
    except Exception as exc:  # noqa: BLE001 —— 搬块失败不许静默，也不带走改名
        out["reading"].update(
            checked=False,
            why=f"搬签块这一格没跑成（{type(exc).__name__}: {exc}）")
        out["problem"] = {
            "kind": "sign_block_unreadable", "stage": "sign",
            "why": (f"搬签块这一格没跑成（{type(exc).__name__}: {exc}）"
                    "⇒ 这一格没查成，不是「没有签」"),
        }
        return out


# ---------------------------------------------------------------- 落盘（唯一事务）

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
    old_sha = _VR.proof_sha(_VS.manuscript_proof_body(target_text))
    new_sha = _VR.proof_sha(_VS.manuscript_proof_body(titled))
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


def commit_manuscript(
    root: Any, *, family: Any, text: str | None = None,
    statement_id: Any = "", plan_id: Any = "", sid: Any = "",
    title: Any = "", proposition: Any = "", proof_text: Any = "",
    label: Any = "", proof_no: Any = 1,
    dependency_rows: Sequence[Mapping[str, Any]] | None = None,
    dependency_section: str = "",
    old_rel: Any = "", retitle: str = "ensure",
    require_washed: bool = False, delete_old: bool = False,
    write_dependencies: Callable[[Sequence[Mapping[str, Any]]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """写一份证明手稿（三节 + 洗稿行 + 命题号行），并把依赖边一起落盘。

    `text is None` ⇒ 用 :func:`render_proof_manuscript` 现渲染；否则按给定正文落盘
    （`publish` / `promote` 那一档：正文是作者的作品，只改文件名与稿头那一行）。

    ## 事务

    1. 名字：只走 :func:`name_reading`（内部只走 `vsigns.parse_manuscript_name`）；
       认不出 ⇒ `bad_manuscript_name`，零写入。
    2. 形状 / 洗稿 / 依赖段：:func:`validate_manuscript`（同一批码与模板）。
    3. 不毁签：目标名上签住的是另一版正文 ⇒ `target_holds_a_signed_version`，零写入。
    4. 搬签：:func:`carry_sign_block`（sha 相符才搬，第 9 格按新名重算）。
    5. 落盘：内容没变 ⇒ 不写（`preserved=True`）。
    6. 落边：`write_dependencies(rows)` 返回 `checked=False` / 抛异常 ⇒ 把第 5 步
       写的稿回滚到写前（原本没有就删掉）⇒ `dependency_edges_not_written`。

    返回 `{"ok", "checked", "path", "written", "preserved", "signed", "text",
    "why", "problem", "refused", "sign_moved", "sign_step", "retitled",
    "renamed_from", "old_name_kept", "deps_written", "rows"}`。
    """
    out: dict[str, Any] = {
        "ok": False, "checked": True, "path": "", "written": False,
        "preserved": False, "signed": False, "text": "", "why": "",
        "problem": {}, "refused": "", "sign_moved": False,
        "sign_step": {"checked": False, "found": False, "sha_match": None,
                      "moved": False, "candidates": [], "why": ""},
        "retitled": False, "renamed_from": "", "old_name_kept": False,
        "deps_written": 0, "rows": [],
    }
    name = name_reading(family, statement_id=statement_id, plan_id=plan_id,
                        proof_no=proof_no)
    out["path"] = str(name.get("path") or "")
    if not name.get("ok"):
        return _refusal(out, str(name.get("code") or BAD_MANUSCRIPT_NAME),
                        str(name.get("why") or ""), stage="name")
    fam = str(family or "")
    new_rel = str(name["path"])
    rows = list(dependency_rows or [])
    if text is None:
        body = render_proof_manuscript(
            fam, title=title, statement_id=statement_id, proposition=proposition,
            proof_text=proof_text, dependency_rows=rows,
            dependency_section=dependency_section, plan_id=plan_id, sid=sid,
            label=label, proof_no=proof_no)
    else:
        body = str(text or "").replace("\r\n", "\n")
    if str(statement_id or "").strip():
        if str(retitle) == "ensure":
            body, applied = ensure_statement_line(body, str(statement_id))
        elif str(retitle) == "replace":
            body, applied = retitle_statement_line(body, str(statement_id))
        else:
            applied = True
        out["retitled"] = bool(applied)
    if not rows and dependency_rows is None:
        section = _DS.parse_dependency_section(body)
        if section.get("present") and not section.get("refused"):
            rows = [dict(r) for r in (section.get("rows") or [])]
    out["rows"] = rows
    verdict = validate_manuscript(body, require_washed=bool(require_washed))
    if not verdict.get("ok"):
        return _refusal(out, str(verdict.get("code") or ""),
                        str(verdict.get("why") or ""), stage="shape")
    signed_now = _signed_version_reading(root, new_rel, body, str(statement_id))
    if not signed_now.get("checked"):
        return _refusal(out, "target_unreadable", str(signed_now.get("why") or ""),
                        stage="read")
    if signed_now.get("blocked"):
        return _refusal(out, "target_holds_a_signed_version",
                        str(signed_now.get("why") or ""), stage="write")
    carried = carry_sign_block(root, body, old_rel=_norm_rel(old_rel),
                               new_rel=new_rel, statement_id=str(statement_id))
    body = str(carried.get("text") or body)
    out["text"] = body
    out["sign_moved"] = bool(carried.get("moved"))
    out["sign_step"] = dict(carried.get("reading") or {})
    if carried.get("problem") and not out["problem"]:
        out["problem"] = dict(carried["problem"])
    target = Path(root) / new_rel
    before: str | None = None
    existed = target.is_file()
    if existed:
        try:
            before = target.read_text(encoding="utf-8")
        except OSError as exc:
            return _refusal(out, "target_unreadable",
                            (f"目标稿读不出来（{type(exc).__name__}: {exc}）"
                             "⇒ 不敢覆盖它"), stage="read")
    changed = (not existed) or (before != body)
    if changed:
        try:
            _atomic_write(target, body)
        except OSError as exc:
            return _refusal(out, "write_failed",
                            f"手稿没写成（{type(exc).__name__}: {exc}）", stage="write")
    out["written"] = bool(changed)
    out["preserved"] = bool(existed and not changed)
    block = _VS.manuscript_sign_reading(body, manuscript_path=new_rel)
    out["signed"] = bool(block.get("found") and block.get("signed")
                         and block.get("proof_sha256")
                         == _VR.proof_sha(_VS.manuscript_proof_body(body)))
    # ---- 依赖边：与写稿同一次事务（落边失败 ⇒ 稿回滚） ---------------------------
    if write_dependencies is not None and rows:
        try:
            got = dict(write_dependencies(rows) or {})
        except Exception as exc:  # noqa: BLE001 —— 落边失败必须整笔回滚，不留半截
            got = {"checked": False,
                   "reason": f"{type(exc).__name__}: {exc}"}
        if not got.get("checked", True) or got.get("refused"):
            reason = str(got.get("reason") or got.get("refused") or "未知原因")
            try:
                if existed and before is not None:
                    _atomic_write(target, before)
                elif not existed and target.is_file():
                    target.unlink()
            except OSError as exc:  # noqa: BLE001 —— 回滚失败要如实说
                reason += f"；回滚也没成（{type(exc).__name__}: {exc}）"
            out["written"] = False
            return _refusal(out, DEPENDENCY_EDGES_NOT_WRITTEN,
                            detail(DEPENDENCY_EDGES_NOT_WRITTEN, reason=reason),
                            stage="dependencies", deps=got)
        out["deps_written"] = int(got.get("deps_written") or 0)
    # ---- 旧名：新名写成功之后才删（事务顺序） ------------------------------------
    old = _norm_rel(old_rel)
    if delete_old and old and old != new_rel:
        old_path = Path(root) / old
        if old_path.is_file():
            try:
                old_path.unlink()
                out["renamed_from"] = old
            except OSError as exc:  # noqa: BLE001 - 旧名删不掉不影响新名可读
                out.update(old_name_kept=True,
                           problem={"kind": "old_name_kept", "stage": "cleanup",
                                    "why": (f"新名写成了，旧名 {old} 没删掉"
                                            f"（{type(exc).__name__}: {exc}）"
                                            "—— 盘上会有两份同一份稿")})
                out["why"] = out["problem"]["why"]
    out.update(ok=True, checked=True, why="")
    return out


def promote_formal(root: Any, *, family: Any = FAMILY_F, statement_id: Any = "",
                   source: Any = "", text: Any = "", delete_source: bool = False,
                   store: Any = None,
                   write_dependencies: Callable[[Sequence[Mapping[str, Any]]],
                                                Mapping[str, Any]] | None = None,
                   ) -> dict[str, Any]:
    """把盘上已有的一份稿转成 `<prefix>-proof-<号>.md`（两族共用；签块跟着搬）。

    只搬不写：正文一个字不改，只补/改稿头 `- 命题号：` 那一行；源稿默认留着。
    """
    out: dict[str, Any] = {
        "promoted": False, "path": "", "source": _norm_rel(source),
        "renamed_from": "", "retitled": False, "sign_moved": False,
        "sign_step": {"checked": False, "found": False, "sha_match": None,
                      "moved": False, "candidates": [], "why": ""},
        "problem": {}, "source_kept": False, "why": "", "refused": "",
        "deps_written": 0,
    }
    name = name_reading(family, statement_id=statement_id)
    out["path"] = str(name.get("path") or "")
    if not name.get("ok"):
        out.update(problem={"kind": str(name.get("code") or BAD_MANUSCRIPT_NAME),
                            "stage": "arg", "why": str(name.get("why") or "")},
                   refused=str(name.get("code") or BAD_MANUSCRIPT_NAME),
                   why=str(name.get("why") or ""))
        return out
    rel = _norm_rel(source)
    if root is None:
        out.update(problem={"kind": "no_workspace_root", "stage": "read",
                            "why": "没有工作区根 ⇒ 读不到攻坚稿，也写不出正式稿"})
        return out
    if rel and not is_safe_relpath(rel, PROMOTE_SOURCE_ROOTS):
        why = (f"转正的源稿只收工作区相对路径、且落在 "
               f"{'/'.join(PROMOTE_SOURCE_ROOTS)}/ 下（`.md`），收到 {source!r}")
        out.update(problem={"kind": "bad_source_path", "stage": "arg", "why": why},
                   refused="bad_source_path", why=why)
        return out
    body = str(text or "")
    if not body.strip():
        if not rel:
            out.update(problem={"kind": "source_missing", "stage": "read",
                                "why": "没有给源稿路径，也没有给正文 ⇒ 没有可转正的东西"},
                       refused="source_missing")
            return out
        try:
            body = (Path(root) / rel).read_text(encoding="utf-8")
        except OSError as exc:
            why = (f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ 没有可转正的稿")
            out.update(problem={"kind": "source_missing", "stage": "read",
                                "why": why}, refused="source_missing", why=why)
            return out
    got = commit_manuscript(
        root, family=family, text=body, statement_id=statement_id,
        old_rel=rel, retitle="ensure", require_washed=True,
        delete_old=bool(delete_source), write_dependencies=write_dependencies)
    out.update(path=str(got.get("path") or out["path"]),
               retitled=bool(got.get("retitled")), sign_moved=bool(got.get("sign_moved")),
               sign_step=dict(got.get("sign_step") or {}),
               renamed_from=str(got.get("renamed_from") or ""),
               source_kept=bool(rel and str(got.get("renamed_from") or "") != rel),
               deps_written=int(got.get("deps_written") or 0),
               refused=str(got.get("refused") or ""),
               why=str(got.get("why") or ""))
    if got.get("problem"):
        out["problem"] = dict(got["problem"])
    if got.get("old_name_kept"):
        out["old_name_kept"] = True
    out["promoted"] = bool(got.get("ok"))
    if out["promoted"]:
        out["source_kept"] = not bool(delete_source)
        out["why"] = ""
    return out
