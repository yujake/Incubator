# -*- coding: utf-8 -*-
"""开稿口：三族（F 的 f-proof、E 的 e-proof / e-num、B 的 b-proof）共用的唯一入口。

## 业主口径（2026-11-13 裁定，逐字）

「统一 B、E、F 注册稿和写稿的流程：写命题 → 命题形式过审 → 拿稿号 → 写稿
（稿允许慢慢 edit，不必一次成稿）」

## 这四步落在这里

1. 写命题：调用方给一段字符串（F 的 `product.proposition` / E 的 `claim` / B 的
   `statement_full` 或稿上 `## 命题`）；
2. 过审：判据只有一处（`Secretary.judge_proposition_form`，按命题正文 sha 缓存、
   跨 role）。本模块只回答「什么时候问」与「判不过怎么办」；
3. 拿稿号：`manuscriptids.next_manuscript_id(root, family=…)` —— 过审之后才发，
   判不过时号源一个字节都不动（判据 `peek_manuscript_counter` 不变）；
4. 落骨架：稿头 + `## 命题`（逐字） + 空的分节 + 空的 `## 依赖`。骨架之后由
   `write_section`（框架侧）或 `fs.edit`（模型侧）一次一次填；提交审阅 / 登记发生
   在「稿写好了」之后，不是写稿的前提。

## 为什么骨架不走 `manuscriptform.commit_manuscript`

`commit_manuscript` 的校验（`manuscriptform.formal_shape_problem`）要求 `## 证明`
那一节存在且非空，而骨架的 `## 证明` 就是空的 —— 走它会把骨架判成
`empty_proof_section`。`exhaustionreport.land_manuscript` 同理（它把「`## 证明` 读不出
正文」当落稿失败）。骨架是「稿已开、内容未写」这一档，与「一份写完的稿」是两个对象，
所以写口分开。这仍然不是第三套渲染：分节名与 `## 命题` 的字节都从 `depsection` 与
调用方取，本模块不自己发明格式。

## 未签稿的写口（判据本体在这里，`tools/fs_tools.py` 只接线）

`write_allowed` 是「谁能在什么时候改这份稿」的唯一判据：角色-族绑定（F 只能改
f-proof、E 只能改 e-proof / e-num、B 只能改 b-proof）、号必须在自家号段已发、已签只读
（`manuscriptfreeze.freeze_reading`，数据只来自 V 的颁发表）、只许改正文（不许换名 /
删 / 整份覆盖）、`## 命题` 只许开稿口写（改它等于绕过形态闸）。

## 三态

`checked=False` 只出现在「没查成」（号源写不进去 / 稿读不出来）；「判不过」「没判成」
都折成受控拒，绝不折成放行。所有拒信都带 `fix` / `next_step`，一个字节都不写。
"""
from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from . import depsection as _DS
from . import manuscriptfamily as _MFAM
from . import manuscriptfreeze as _FZ
from . import manuscriptids as _MID
from .manuscriptwrite import _atomic_write

#: 角色 ⇒ 它自己那一族（手稿写口的角色面；不在这张表里的角色不产出手稿）。
#: `E` 有两族（穷举证明 / 普通数值），`B` 只有 `b-proof`，`F` 只有 `f-proof`。
ROLE_FAMILIES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "F": ("f-proof",),
    "E": ("e-proof", "e-num"),
    "B": ("b-proof",),
})

#: 族 ⇒ 渲染稿头时署的角色名（与 `manuscriptform.render_proof_manuscript` 同一取舍：
#: 稿头那句「X 的证明手稿」写的是产出侧角色）。
_ROLE_OF_FAMILY: Mapping[str, str] = MappingProxyType({
    "f-proof": "F",
    "b-proof": "B",
    "e-proof": "E",
    "e-num": "E",
})

#: 骨架的节序（`## 命题` 之后的分节）：`e-num` 没有 `## 证明`，它写 `## 数值结果`。
#: 数值结果那一节的节名与 `depsection.SECTION_TITLES` 末位同一字面量。
NUMERIC_RESULT_HEADING = _DS.SECTION_TITLES[-1]

#: 受控码：proof 档没有命题（与 `agent_f/manuscript.py` 的 `PROPOSITION_MISSING` 同名
#: 同义的既有码；本模块不另立一个名字）。
PROPOSITION_MISSING = "proposition_missing"

#: 受控码：这一笔的族不属于这个角色（角色-族绑定）。
FAMILY_NOT_OWNED = "manuscript_family_not_owned"

#: 受控码：手稿形名字但不是规范落点（`-v2` / 别的目录 ⇒ 落成规范名再改）。
NOT_CANONICAL = "manuscript_name_not_canonical"

#: 受控码：号不是这一族号段发出去的（不猜一个号出来）。
ID_NOT_ISSUED = "manuscript_id_not_issued"

#: 受控码：这一份不在盘上（骨架由开稿口写，改要有对象）。
NOT_ON_DISK = "manuscript_not_on_disk"

#: 受控码：这一节不是「写内容」能碰的（`## 命题` 归开稿口；未知节名不受理）。
SECTION_NOT_WRITABLE = "manuscript_section_not_writable"

#: 受控码：所属命题已经退休（`abandoned` / `refuted`）⇒ 这份稿一并作废、只读。
#:
#: 与 `manuscriptfreeze.MANUSCRIPT_FROZEN` 是两件事：冻结说的是"它拿过签"，
#: 这一档说的是"命题已经不做了"。一份没签过的稿也会落这一档（引文侧的占位签稿）。
MANUSCRIPT_RETIRED = "manuscript_retired"

#: 受控码：这一份稿读不出来 / 写不进去（没查成，不是没毛病）。
UNREADABLE = "manuscript_unreadable"
WRITE_FAILED = "manuscript_write_failed"

#: 受控码：号源发不出号（计数器写不进去 / 号段用尽）。
ID_UNAVAILABLE = "manuscript_id_unavailable"

#: 受控码：形态闸那一格没接上（没判成，fail-closed）。
FORM_UNAVAILABLE = "proposition_form_unavailable"


def families_of(role: Any) -> tuple[str, ...]:
    """这个角色能开哪几族的稿（不在表里 ⇒ 空，不猜）。"""
    return tuple(ROLE_FAMILIES.get(str(role or "").strip(), ()))


def owns_family(role: Any, family: Any) -> bool:
    """这个角色是不是这一族的产出侧（角色-族绑定；写口与开稿口共用这一处）。"""
    return str(family or "").strip() in families_of(role)


def sections_of(family: Any) -> tuple[str, ...]:
    """这一族骨架的分节（含 `## 命题` 那一节；顺序固定）。"""
    fam = str(family or "").strip()
    if fam == "e-num":
        return (_DS.SECTION_STATEMENT, NUMERIC_RESULT_HEADING)
    return (_DS.SECTION_STATEMENT, _DS.SECTION_PROOF, _DS.SECTION_HEADING)


def writable_sections(family: Any) -> tuple[str, ...]:
    """`write_section` 能写的那几节：除 `## 命题` 之外的分节。

    `## 命题` 只许开稿口写 —— 它是形态闸判过的那段字节；让第二个口改它等于
    「判过的」与「在盘上的」重新分家（W1 真机缺陷的同一种病）。
    """
    return tuple(s for s in sections_of(family) if s != _DS.SECTION_STATEMENT)


def _short(text: Any, width: int = 60) -> str:
    """单行化 + 截断（与 `manuscriptform._short` 同一口径，本模块不依赖它）。"""
    s = " ".join(str(text or "").split())
    return s if len(s) <= width else s[: width - 1] + "…"


def _norm_rel(rel: Any) -> str:
    """工作区相对路径的归一（只换分隔符；不猜、不补前缀）。"""
    return str(rel or "").strip().replace("\\", "/")


def _refusal(code: str, why: str, **extra: Any) -> dict[str, Any]:
    """受控拒的统一形状（键集固定：调用方不必按分支猜哪几格在）。"""
    out: dict[str, Any] = {
        "ok": False, "checked": True, "refused": code, "kind": code,
        "why": str(why or ""), "fix": "", "next_step": "", "problems": [],
        "path": "", "manuscript_id": "", "family": "", "role": "",
        "proposition": "", "text": "", "written": False, "preserved": False,
        "draft": False, "existing": False, "form": {}, "task_id": "",
    }
    out.update(extra)
    return out


def skeleton_text(family: Any, *, proposition: Any, title: Any = "",
                  header_lines: Sequence[Any] = ()) -> str:
    """一份骨架的字节（纯函数，逐字节可复现）。

    形状固定：`# <角色> 的证明手稿：<标题>` → 调用方给的稿头行 → `## 命题` + 逐字
    命题 → 每一节标题 + 空行。空的分节就是「还没写」，不是「写了空内容」——
    两者在 `## 证明` 上由 `depsection.proof_body` 读成同一个空串，但骨架没有登记
    元信息，读侧据此认得出它是一份未登记的稿。
    """
    fam = str(family or "").strip()
    role = str(_ROLE_OF_FAMILY.get(fam) or "")
    heading = _short(title or proposition or "（这一条还没有标题）")
    lines: list[str] = [f"# {role} 的证明手稿：{heading}", ""]
    for line in header_lines or ():
        text = str(line or "").strip()
        if not text or text.startswith("## "):
            continue
        lines.append(text)
    if len(lines) > 2:
        lines.append("")
    for section in sections_of(fam):
        lines.extend([section, ""])
        if section == _DS.SECTION_STATEMENT:
            lines.append(str(proposition or "").strip())
            lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _form_refusal(form: Mapping[str, Any], *, fix: str, next_step: str,
                  problems: list[str]) -> dict[str, Any]:
    """把形态闸的读数折成一次受控拒（判不过 / 没判成共用这一处）。"""
    from .secretary import PROPOSITION_FORM_REFUSED

    return _refusal(
        str(form.get("refused") or PROPOSITION_FORM_REFUSED),
        str(form.get("reason") or "命题形态闸没放行"),
        fix=str(fix or ""), next_step=str(next_step or ""),
        problems=list(problems), form=dict(form))


def _ask_gate(*, proposition: str, kind: str, label: str, task_id: str,
              judge: Callable[..., Mapping[str, Any]] | None,
              secretary: Any) -> dict[str, Any]:
    """问一次形态闸，并把读数折成 `submittable`（两态；没判成也是拒）。

    判据本体只有一处：调用方传进来的 `judge` 就是这一族自己的包装
    （`_proposition_form_gate`），它最终调 `Secretary.judge_proposition_form`。
    这里只做「递给它哪几个键」与「折成两态」两件事，不另写一份判据。
    """
    from .secretary import NOT_APPLICABLE_KINDS

    out: dict[str, Any] = {
        "checked": False, "well_formed": False, "submittable": False,
        "conditions": "", "conclusion": "", "problems": [], "decision": "",
        "refused": "", "reason": "", "actor": "", "cached": False,
        "raw": {},
    }
    if str(kind or "").strip().lower() in NOT_APPLICABLE_KINDS:
        out.update(checked=True, well_formed=True, submittable=True,
                   reason=(f"kind={kind!r} 落在 concept/definition 那一档：它不是命题"
                           "（没有「条件 → 结论」）⇒ 不受这道闸管"))
        return out
    try:
        if judge is not None:
            got = dict(judge(full=str(proposition or ""), kind=str(kind or ""),
                             label=str(label or ""), task_id=str(task_id or "")) or {})
        elif secretary is not None:
            got = dict(secretary.judge_proposition_form(
                statement_full=str(proposition or ""), kind=str(kind or ""),
                label=str(label or ""), task_id=str(task_id or "")) or {})
        else:
            out.update(refused=FORM_UNAVAILABLE,
                       reason=("这一笔没有形态闸可问（既没给 `judge`，也没有秘书）"
                               "⇒ 没判成：受控拒（没判成不等于没毛病）"))
            return out
    except Exception as exc:  # noqa: BLE001 —— 判定那一问炸了 = 没判成（受控拒）
        out.update(refused=FORM_UNAVAILABLE,
                   reason=(f"形态判定调用失败（{type(exc).__name__}: {exc}）⇒ "
                           "没判成：受控拒（没判成不等于没毛病）"),
                   problems=[str(exc)[:200]])
        return out
    out.update(
        checked=bool(got.get("checked")), well_formed=bool(got.get("well_formed")),
        conditions=str(got.get("conditions") or ""),
        conclusion=str(got.get("conclusion") or ""),
        problems=[str(x) for x in (got.get("problems") or []) if str(x).strip()],
        decision=str(got.get("decision") or ""),
        actor=str(got.get("actor") or ""),
        refused=str(got.get("refused") or ""),
        reason=str(got.get("reason") or ""),
        cached=bool(got.get("cached")), raw=got)
    out["submittable"] = bool(out["checked"] and out["well_formed"])
    if not out["checked"]:
        out["refused"] = out["refused"] or FORM_UNAVAILABLE
    return out


def open_manuscript(root: Any, *, role: str, family: str, proposition: str,
                    judge: Callable[..., Mapping[str, Any]] | None = None,
                    secretary: Any = None,
                    form_reading: Mapping[str, Any] | None = None,
                    kind: str = "conjecture", label: str = "", task_id: str = "",
                    title: str = "", header_lines: Sequence[Any] = (),
                    manuscript_id: str = "", fix: str = "", next_step: str = "") -> dict:
    """开一份稿：先过形态闸，再过号源，最后只落骨架。

    返回固定键集（成功与受控拒同形）：
    `{ok, checked, refused, kind, why, fix, next_step, problems, path,
      manuscript_id, family, role, proposition, text, written, preserved, draft,
      existing, form, task_id}`。

    ## 次序是判据

    闸在发号之前：判不过 / 没判成 ⇒ 号源一个字节都不动、盘上零字节。发号在写盘之前：
    写失败时号已经发出去（那个号留在号源里，调用方拿同一个 `manuscript_id` 重试即可，
    不会覆盖别人的稿）。号在写盘之后才叫「拿到稿号」—— 所以 `path` / `manuscript_id`
    只在过审之后才出现在返回值里。

    ## 已存在的稿

    目标路径上已经有一份（同一稿号重开 / 上一轮开过）⇒ 一个字节都不写，`preserved=True`
    并带回盘上那一份正文。开稿口绝不覆盖一份已有的稿 —— 覆盖是 `write_section` /
    `fs.edit` 的事，而被签住的那一份由 `manuscriptfreeze` 拒。

    ## `form_reading`

    调用方已经在更早一步判过（F 的写前闸、E 的 [4e]）⇒ 传进来复用，本模块不再问
    第二次（同一段字节不重复花钱，形态台账也不多写一行）。
    """
    fam = str(family or "").strip()
    who = str(role or "").strip()
    out: dict[str, Any] = {
        "ok": False, "checked": True, "refused": "", "kind": "", "why": "",
        "fix": str(fix or ""), "next_step": str(next_step or ""), "problems": [],
        "path": "", "manuscript_id": "", "family": fam, "role": who,
        "proposition": str(proposition or "").strip(), "text": "",
        "written": False, "preserved": False, "draft": False, "existing": False,
        "form": {}, "task_id": str(task_id or ""),
    }
    if not who or not owns_family(who, fam):
        return _refusal(
            FAMILY_NOT_OWNED,
            (f"{who!r} 不是 {fam!r} 这一族的产出侧（角色-族绑定："
             f"{ {k: list(v) for k, v in ROLE_FAMILIES.items()} }）⇒ 不开稿"),
            family=fam, role=who, task_id=str(task_id or ""))
    text_prop = str(proposition or "").strip()
    if not text_prop:
        return _refusal(
            PROPOSITION_MISSING,
            ("没有命题正文 ⇒ 稿上 `## 命题` 没有可渲染的那段文字（一个字节都不写、"
             "号源不动）。先给这条定理的完整陈述（前提 → 结论）"),
            family=fam, role=who, fix=str(fix or ""),
            next_step=str(next_step or ""), task_id=str(task_id or ""))
    # ---- 已有这一份（同一稿号重开）⇒ 不问闸、不写字节、不覆盖 --------------------
    #
    # 这一段刻意放在闸之前：开稿口对同一份稿是幂等的（判据 b 的重开那一格），而
    # 「闸只在新开一份稿时判一次」是业主 2026-11-13 的口径（同一段字节不重复花钱，
    # 形态台账也不多写一行）。
    mid = str(manuscript_id or "").strip()
    if mid and not _MID.is_manuscript_id(mid):
        return _refusal(NOT_CANONICAL,
                        f"手稿号 {mid!r} 不是六位号 ⇒ 这一份稿不落盘", family=fam,
                        role=who, manuscript_id=mid, proposition=text_prop,
                        task_id=str(task_id or ""))
    if mid:
        rel_now = _MID.canonical_rel(mid, family=fam)
        out.update(manuscript_id=mid, path=rel_now)
        if not rel_now:
            return _refusal(NOT_CANONICAL,
                            f"手稿号 {mid!r} 拼不出 {fam} 的规范路径 ⇒ 这一份稿不落盘",
                            family=fam, role=who, manuscript_id=mid,
                            proposition=text_prop, task_id=str(task_id or ""))
        target_now = Path(str(root or ".")) / rel_now
        if target_now.is_file():
            frozen = _FZ.freeze_reading(root, rel_now)
            if frozen.get("frozen"):
                return _refusal(
                    str(_FZ.MANUSCRIPT_FROZEN), str(frozen.get("message") or ""),
                    family=fam, role=who, manuscript_id=mid, proposition=text_prop,
                    path=rel_now, task_id=str(task_id or ""))
            try:
                existing = target_now.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                return _refusal(
                    UNREADABLE,
                    (f"`{rel_now}` 读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成，"
                     "不覆盖它"),
                    family=fam, role=who, manuscript_id=mid, proposition=text_prop,
                    path=rel_now, task_id=str(task_id or ""))
            out.update(ok=True, checked=True, text=existing, preserved=True,
                       existing=True, draft=True)
            return out
    # ---- ② 过审（号源还没动） ----------------------------------------------------
    if form_reading is not None:
        form = dict(form_reading)
        form.setdefault("submittable", bool(form.get("checked") and form.get("well_formed")))
    else:
        form = _ask_gate(proposition=text_prop, kind=str(kind or ""),
                         label=str(label or ""), task_id=str(task_id or ""),
                         judge=judge, secretary=secretary)
    out["form"] = dict(form)
    if not form.get("submittable"):
        problems = [str(x) for x in (form.get("problems") or []) if str(x).strip()]
        refused = _form_refusal(form, fix=str(fix or ""),
                                next_step=str(next_step or ""), problems=problems)
        refused.update(family=fam, role=who, proposition=text_prop,
                       task_id=str(task_id or ""), form=dict(form))
        return refused
    # ---- ③ 拿稿号（过审之后） ----------------------------------------------------
    if not mid:
        try:
            mid = str(_MID.next_manuscript_id(root, family=fam) or "")
        except Exception as exc:  # noqa: BLE001 —— 号发不出来要受控报，不是「没号可用」
            return _refusal(
                ID_UNAVAILABLE,
                (f"这一族的稿号发不出来（{type(exc).__name__}: {exc}）⇒ 一个字节都没写；"
                 "修好 `data/counters.json` 再开稿"),
                family=fam, role=who, proposition=text_prop,
                task_id=str(task_id or ""))
    rel = _MID.canonical_rel(mid, family=fam)
    out.update(manuscript_id=mid, path=rel)
    if not rel:
        return _refusal(NOT_CANONICAL,
                        f"手稿号 {mid!r} 拼不出 {fam} 的规范路径 ⇒ 这一份稿不落盘",
                        family=fam, role=who, manuscript_id=mid,
                        proposition=text_prop, task_id=str(task_id or ""))
    target = Path(str(root or ".")) / rel
    if target.is_file():
        # 并发/重开：闸放行之后发现已经有一份 ⇒ 同样一个字节都不写。
        frozen = _FZ.freeze_reading(root, rel)
        if frozen.get("frozen"):
            return _refusal(
                str(_FZ.MANUSCRIPT_FROZEN), str(frozen.get("message") or ""),
                family=fam, role=who, manuscript_id=mid, proposition=text_prop,
                path=rel, task_id=str(task_id or ""))
        try:
            existing = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return _refusal(
                UNREADABLE,
                (f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成，"
                 "不覆盖它"),
                family=fam, role=who, manuscript_id=mid, proposition=text_prop,
                path=rel, task_id=str(task_id or ""))
        out.update(ok=True, checked=True, text=existing, preserved=True,
                   existing=True, draft=True)
        return out
    # ---- ④ 落骨架 ----------------------------------------------------------------
    body = skeleton_text(fam, proposition=text_prop, title=title,
                         header_lines=header_lines)
    try:
        _atomic_write(target, body)
    except OSError as exc:
        return _refusal(
            WRITE_FAILED,
            f"骨架没写成（{type(exc).__name__}: {exc}）⇒ 号已发出、盘上零字节",
            family=fam, role=who, manuscript_id=mid, proposition=text_prop,
            path=rel, task_id=str(task_id or ""))
    try:
        written = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        written = body
    # ---- 产物归属（`ARTIFACTS.jsonl`）：骨架已经落到盘上，补"这个路径归谁产"。
    # 登记失败 ⇒ 受控拒（`WRITE_FAILED`：骨架在盘上、归属没落成），不静默。
    from . import artifacts as A

    _reg_entry, _reg_problem = A.record_or_problem(
        root, path=rel, producer=who, kind=f"{fam}-manuscript",
        task_id=str(task_id or ""),
        note=f"手稿骨架 `{rel}`（manuscriptopen.open_manuscript）")
    if _reg_problem:
        return _refusal(
            WRITE_FAILED,
            (f"骨架写成了（{rel}），但产物归属没登记成：{_reg_problem} ⇒ 这一笔按失败报"
             f"（补登记：`agentflow artifacts record {rel} --producer {who}`）"),
            family=fam, role=who, manuscript_id=mid, proposition=text_prop,
            path=rel, task_id=str(task_id or ""), written=True, draft=True)
    out.update(ok=True, checked=True, text=written, written=True, draft=True)
    return out


def _shape(rel: Any) -> dict[str, Any]:
    """这个名字是不是手稿形、属于哪一族、号是几（名字级判定）。"""
    raw = _norm_rel(rel)
    shape = _MFAM.classify_name(raw)
    tier = str(shape.get("tier") or "")
    fam = str(shape.get("name_family") or "")
    return {
        "rel": raw, "tier": tier, "family": fam,
        "manuscript_id": str(shape.get("manuscript_id") or ""),
        "is_manuscript": tier in (_MFAM.TIER_FAMILY, _MFAM.TIER_LEGACY),
    }


def write_allowed(*, rel: Any, role: Any, root: Any, store: Any = None) -> dict[str, Any]:
    """这一笔能不能改这份稿（`fs.edit` 与 `write_section` 共用的唯一判据）。

    返回 `{checked, is_manuscript, owns, allowed, code, why, family,
    manuscript_id, rel, state, retirement}`。`is_manuscript=False` ⇒ 不归这一层管
    （调用方照旧走 `RESERVED_ARTIFACT_TABLE` 那张表）。

    逐条：① 角色必须在 `ROLE_FAMILIES` 里，且族是它自己那一族；② 路径必须是
    `reports/<族前缀><六位号>.md` 这一种规范名（`-v2` / 别的目录 ⇒ 先落成规范名）；
    ③ 号必须是这一族号段已经发出去的（`peek_manuscript_counter(family) - 1`；
    读不出来 ⇒ 不放行）；④ 所属命题已退休 ⇒ 这份稿一并作废、只读（2026-11-13
    业主裁定「放弃命题时就是这个稿也一并作废」；判据 `manuscriptretire.retire_reading`）；
    ⑤ 拿签之后只读（`manuscriptfreeze`，四档里只放 `unsigned`；`unchecked` 按只读处理）；
    ⑥ 这一份得在盘上。

    ## `store` 为什么是可选的
    退休判据要读 `statements` 台账，所以只有拿得到 store 的调用方判得了这一格。
    不带 `store` 时这一条不说话（`retirement.checked=False`），不折成"没退休"：
    读数里明写"这一格没查"，`fs_tools` 那一层转发时把 store 带进来就生效。
    """
    shape = _shape(rel)
    out: dict[str, Any] = {
        "checked": True, "is_manuscript": bool(shape["is_manuscript"]),
        "owns": False, "allowed": False, "code": "", "why": "",
        "family": str(shape["family"]), "manuscript_id": str(shape["manuscript_id"]),
        "rel": str(shape["rel"]), "state": "unsigned",
        "retirement": {"checked": False, "retired": False, "why": "这一笔没带 store"},
    }
    if not shape["is_manuscript"]:
        out["why"] = "不是手稿形名字 ⇒ 不归手稿写口管"
        return out
    who = str(role or "").strip()
    fam = str(shape["family"])
    out["owns"] = owns_family(who, fam)
    if not out["owns"]:
        out.update(code=FAMILY_NOT_OWNED,
                   why=(f"`{shape['rel']}` 是 {fam} 族的稿，而这一笔是 {who!r} 发的"
                        "⇒ 别人的稿不可改（角色-族绑定）"))
        return out
    canonical = _MFAM.classify_manuscript(shape["rel"])
    if str(canonical.get("tier") or "") != _MFAM.TIER_FAMILY:
        out.update(code=NOT_CANONICAL,
                   why=(f"`{shape['rel']}` 不是规范落点（"
                        f"{str(canonical.get('why') or '目录不对 / 历史后缀')}）⇒ 先把它"
                        f"落成 `reports/{_MFAM.prefix_of(fam)}<六位号>.md` 再改"))
        return out
    try:
        issued = int(_MID.peek_manuscript_counter(root, family=fam)) - 1
    except Exception as exc:  # noqa: BLE001 —— 读不出号源 = 判不出，按不放行
        out.update(checked=False, code=ID_NOT_ISSUED,
                   why=(f"{fam} 的号源读不出来（{type(exc).__name__}: {exc}）"
                        "⇒ 判不出这个号是不是发过的，按不放行处理"))
        return out
    try:
        mid_no = int(shape["manuscript_id"])
    except (TypeError, ValueError):
        mid_no = -1
    if mid_no < 0 or mid_no > issued:
        out.update(code=ID_NOT_ISSUED,
                   why=(f"稿号 {shape['manuscript_id']!r} 还没被 {fam} 的号段发出去"
                        f"（现在发到 {issued:06d}）⇒ 这不是一份由框架开出来的稿"))
        return out
    target = Path(str(root or ".")) / shape["rel"]
    if not target.is_file():
        out.update(code=NOT_ON_DISK,
                   why=f"`{shape['rel']}` 不在盘上 ⇒ 没有可改的对象（骨架由开稿口写）")
        return out
    # ---- ④ 所属命题已退休 ⇒ 这份稿一并作废、只读 --------------------------------
    #
    # 位置在冻结之前：一份已签的稿所属命题被作废之后，正确的处置不是"开优化副本
    # 继续改"（那是冻结那句拒信指的路），而是"这份稿随命题作废、不再动"。
    # 判据本体 `manuscriptretire.retire_reading`（三源并集反查所属命题）。
    if store is not None:
        from . import manuscriptretire as _MR

        retired = _MR.retire_reading(store, shape["rel"])
        out["retirement"] = dict(retired)
        if retired.get("retired"):
            out.update(code=MANUSCRIPT_RETIRED, why=str(retired.get("message") or ""))
            return out
    frozen = _FZ.freeze_reading(root, shape["rel"])
    out["state"] = str(frozen.get("state") or "")
    if frozen.get("frozen"):
        out.update(code=str(_FZ.MANUSCRIPT_FROZEN),
                   why=str(frozen.get("message") or ""))
        return out
    out.update(allowed=True, why="未签、自家号段、规范落点、命题未退休 ⇒ 可以改")
    return out


def foreign_refusal(*, rel: Any, role: Any, root: Any, edit: bool,
                    store: Any = None) -> dict[str, Any] | None:
    """`RESERVED_ARTIFACT_TABLE` 没管到的那一半：手稿形名字的「谁能写」。

    只在表会放行的那几档上给结论（跑在表之后）：
      · 产出侧角色的别族稿 ⇒ 拒（改前 F 能写 b/e 三族、E 能写任何手稿 —— 那是洞）；
      · 自己的族但这一笔不是 `edit`（写 / 删 / 挪）⇒ 拒（骨架与正文只认开稿口 +
        `write_section` / `fs.edit`，整份覆盖会把「判过的命题」与「在盘上的命题」分家）；
      · 自己的族 + `edit` + 未签 ⇒ 放行（返回 None；B 那一格既有行为逐字不变）。
    返回 `{"kind", "why"}` 或 None（None = 表 / 别的闸已经有了结论，别抢它的拒信）。
    """
    shape = _shape(rel)
    if not shape["is_manuscript"]:
        return None
    who = str(role or "").strip()
    if who not in ROLE_FAMILIES:
        return None  # A / D / M 那一档仍归保留表
    fam = str(shape["family"])
    if not owns_family(who, fam):
        return {
            "kind": "reserved_framework_artifact",
            "why": (f"拒绝 {shape['rel']}：这是 {fam} 族的稿，而这一笔是 {who!r} 发的 —— "
                    "手稿只由它自己那一族的产出侧开与改（角色-族绑定；改前这一格是"
                    "一个洞：E 能改任何手稿、F 能改 b/e 两族）"),
        }
    reading = write_allowed(rel=shape["rel"], role=who, root=root, store=store)
    if edit:
        if reading.get("allowed"):
            return None
        code = str(reading.get("code") or "")
        if code == NOT_ON_DISK:
            # 不在盘上不是"权限"问题：让 `fs.edit` 自己报 `not_found`（同一句话，
            # 不要抢它的拒信）。
            return None
        # `kind` 留在工具层既有的闭集里（`reserved_framework_artifact` /
        # `manuscript_frozen` 两档）：具体是哪一条判据拒的写在 why 里 —— 既有判据按
        # `kind` 分档，不按"码"分档。退休那一档的细码另给一格 `code`
        # （`manuscript_retired`）：转发层要单独认这一档时读它，不必去解 why 那句话。
        kind = (_FZ.MANUSCRIPT_FROZEN if code == _FZ.MANUSCRIPT_FROZEN
                else "reserved_framework_artifact")
        return {"kind": kind, "code": code, "why": str(reading.get("why") or "")}
    return {
        "kind": "reserved_framework_artifact",
        "why": (f"拒绝 {shape['rel']}：自家未签稿也不许整份覆盖 / 删除 / 换名（"
                f"{str(reading.get('code') or '')}）—— 开稿口只落一次骨架，之后用 "
                "`fs.edit` 定点改，或由框架的 `write_section` 换一节"),
    }


def write_section(root: Any, *, role: str, rel: Any, section: str, body: Any,
                  task_id: str = "", store: Any = None) -> dict[str, Any]:
    """把稿上某一节换成给定正文（框架侧的「写内容」写口；不是整份重渲）。

    只换那一节，其余字节原样（判据：`## 命题` 一个字节都不动 —— 它只许开稿口写）。
    先过 `write_allowed`（未签、自家号段、规范落点、命题未退休、在盘上），再过节名白名单。
    """
    from . import proofregistry as _PR  # 只借它的换节实现，不借它的整份重渲

    out: dict[str, Any] = {
        "ok": False, "checked": True, "refused": "", "kind": "", "why": "",
        "path": str(_norm_rel(rel)), "section": "", "written": False,
        "preserved": False, "sha256": "", "body_sha": "", "task_id": str(task_id or ""),
    }
    reading = write_allowed(rel=rel, role=role, root=root, store=store)
    if not reading.get("is_manuscript"):
        out.update(refused=FAMILY_NOT_OWNED, kind=FAMILY_NOT_OWNED,
                   why=str(reading.get("why") or "不是手稿"))
        return out
    if not reading.get("allowed"):
        code = str(reading.get("code") or "manuscript_write_refused")
        out.update(refused=code, kind=code, checked=bool(reading.get("checked")),
                   why=str(reading.get("why") or ""))
        return out
    fam = str(reading.get("family") or "")
    name = str(section or "").strip().lstrip("#").strip()
    if name not in _section_names(fam):
        out.update(refused=SECTION_NOT_WRITABLE, kind=SECTION_NOT_WRITABLE,
                   why=(f"`{section!r}` 不是可以在这一族写的节（{fam} 能写："
                        f"{'、'.join(writable_sections(fam))}；`## 命题` 只归开稿口）"))
        return out
    target = Path(str(root or ".")) / str(reading.get("rel") or "")
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        out.update(checked=False, refused=UNREADABLE, kind=UNREADABLE,
                   why=f"`{out['path']}` 读不出来（{type(exc).__name__}: {exc}）")
        return out
    out["section"] = name
    try:
        from . import proofregistry as _PR2

        new_text, replaced = _PR2.replace_section(text, name, str(body or ""))
    except Exception as exc:  # noqa: BLE001 —— 换节失败是没查成，不是写成了
        out.update(checked=False, refused=WRITE_FAILED, kind=WRITE_FAILED,
                   why=f"换 `## {name}` 这一节没跑成（{type(exc).__name__}: {exc}）")
        return out
    if not replaced:
        out.update(refused=SECTION_NOT_WRITABLE, kind=SECTION_NOT_WRITABLE,
                   why=f"稿里没有 `## {name}` 这一节 ⇒ 没有可替换的板块")
        return out
    if new_text == text:
        out.update(ok=True, preserved=True, sha256=_file_sha(target),
                   body_sha=_PR.proof_sha(str(body or "")))
        return out
    try:
        _atomic_write(target, new_text)
    except OSError as exc:
        out.update(refused=WRITE_FAILED, kind=WRITE_FAILED,
                   why=f"`{out['path']}` 没写成（{type(exc).__name__}: {exc}）")
        return out
    out.update(ok=True, written=True, sha256=_file_sha(target),
               body_sha=_PR.proof_sha(str(body or "")))
    # ---- 产物归属（`ARTIFACTS.jsonl`）：这一节已经换到盘上，补"这个路径归谁产"。
    # `written=True` 才登记：`preserved` 那一档一个字节都没动，不该多一行归属。
    from . import artifacts as A

    _reg_rel = str(reading.get("rel") or out["path"])
    _reg_entry, _reg_problem = A.record_or_problem(
        root, path=_reg_rel, producer=str(role or ""),
        kind=f"{fam}-manuscript" if fam else "manuscript",
        task_id=str(task_id or ""),
        note=f"手稿 `{_reg_rel}` 的 `## {name}` 节改写（manuscriptopen.write_section）")
    if _reg_problem:
        out.update(ok=False, refused=WRITE_FAILED, kind=WRITE_FAILED,
                   why=(f"`{_reg_rel}` 的 `## {name}` 换成了，但产物归属没登记成："
                        f"{_reg_problem} ⇒ 这一笔按失败报"
                        f"（补登记：`agentflow artifacts record {_reg_rel} --producer {role}`）"))
        return out
    return out


def _section_names(family: Any) -> tuple[str, ...]:
    """节标题 ⇒ 不带 `## ` 的节名（`replace_section` 的入参形状）。"""
    return tuple(s.lstrip("#").strip() for s in writable_sections(family))


def _file_sha(path: Path) -> str:
    """整份文件的 sha256（没读成 ⇒ 空串，不猜）。"""
    import hashlib

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""
