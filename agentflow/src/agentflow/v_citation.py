# -*- coding: utf-8 -*-
"""引用核实：V 核 F 在 `dependencies` 上登记的引用，够不够格被引。

F 登记的是自然语言（"由引理 2"、"由 Sylow I 可知"），不是逐字引文 ⇒ 判据不是
"字面像不像"，而是"F 对这一条被引命题的用法成不成立、以及这一条够不够格被引"。
签字前置（`verifications.signs_bit3` 调本模块的 `citation_gate`）：`stronger` /
`unrelated` / `inadmissible` / `unknown` 任一命中，这一签不许落地；`weaker` 可以签，
但读数里点名"只用到了弱形式"。档位门槛由 `depsection.CITATION_MIN_LEVEL` 现算，
这里不写第二份字面量。

2026-11-20 从 `verifications.py` 逐字搬出（VERSPLIT）：纯搬移，函数体一个字没动，
逐名 AST dump 与 HEAD 全等。搬出它的理由是它是 18 个目标模块里唯一一个
"整块都不被测试打桩"的模块：`verifications.py` 其余 17 个模块都至少有一个名字被
`monkeypatch.setattr(verifications, ...)` 打桩，而打桩点与"调用者在哪个模块里查这个
名字"是同一个边界（`from .mod import X` 是快照）。
"""

from __future__ import annotations

from typing import Any
from typing import Mapping
from typing import Sequence

from . import depsection as _DS
from . import evidencebits as EB
from . import schema as S


def admissible_evidence_kinds() -> tuple[str, ...]:
    """够格被引的等级（按由强到弱的顺序；唯一来源是 `depsection.CITATION_LEVELS`）。

    返回空元组 = 判不了（门槛定义读不到）：空集会让每一条引用都判 `inadmissible`，
    那是可见的失败；反过来在门槛坏掉时放行，就是"没查成"折成"通过"。
    """
    try:
        levels = tuple(_DS.CITATION_LEVELS)
    except Exception:  # noqa: BLE001 —— 读不到门槛 ⇒ 空集（fail-closed）
        return ()
    return tuple(g for g in reversed(EB.GRADES) if g in levels)


def citation_grade_admissible(grade: Any) -> bool:
    """这一级够不够格被引（空串 / 认不出的等级 ⇒ 不够格；判据只有一处）。"""
    return _DS.citation_level_allowed(str(grade or "").strip())


def evidence_kind_admissible(kind: Any) -> bool:
    """历史档位入参的兼容口：先按 `GRADE_TO_KIND` 反算成等级，再走等级门槛。

    为什么保留这个名字：`agent_v` 的缝与 V 的审查材料仍按历史档位字段取值（那是存量行的
    形状）。但它不另有门槛 —— 档位在这里只是"等级的反算名"的逆读，两步都不离开
    `depsection.CITATION_MIN_LEVEL` 那一个定义。判定面请直接用 `citation_grade_admissible`。
    """
    grade = EB.KIND_TO_GRADE.get(str(kind or "").strip(), "")
    return citation_grade_admissible(grade)


def _citation_checks_raw(raw: Any) -> list[dict[str, Any]]:
    """把 V 输出里的 `citation_checks` 洗成规整的五格；形状不对 ⇒ 抛 `VerificationError`。

    它是"没查成"那一档：`verdict` 不在词表里 / `stmt_id` 不是命题号形态，
    都不是"这一条判成什么"，而是这一次输出不可解析 —— 不许折成 `unknown`
    （`unknown` 是一条诚实的结论，而坏输出不是）。

    `in_material` 的缺省是 `True`（不是 `False`）：V 自己给的那几条默认就是"这一份
    证明登记过的引用"；只有 `reconcile_citation_checks` 会显式标 `False`（V 多给的）。
    缺键读成 `False` 会把"V 说的"当成"材料外的"，那是往放行的方向走。
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise VerificationError("citation_checks 必须是数组（每条被引命题一项）")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, Mapping):
            raise VerificationError(f"citation_checks 第 {i} 项必须是对象")
        sid = str(item.get("stmt_id") or "").strip()
        if not S.is_valid_id(sid):
            raise VerificationError(
                f"citation_checks 第 {i} 项的 stmt_id 不是命题号形态（收到 {sid!r}）"
                f"：它必须是被引命题的 {S.ID_DIGITS} 位号（旧四位号仍可读）")
        verdict = str(item.get("verdict") or "").strip()
        if verdict not in CITATION_VERDICTS:
            raise VerificationError(
                f"citation_checks 第 {i} 项的 verdict 必须是 {CITATION_VERDICTS} 之一，"
                f"收到 {verdict!r}")
        flagged = item.get("quote_verbatim")
        if isinstance(flagged, str):
            verbatim = flagged.strip().lower() in ("1", "true", "yes", "y", "是", "逐字")
        else:
            verbatim = bool(flagged)
        in_material = item.get("in_material")
        out.append({
            "stmt_id": sid, "verdict": verdict, "quote_verbatim": verbatim,
            "note": str(item.get("note") or "").strip(),
            "in_material": True if in_material is None else bool(in_material),
        })
    return out


def reconcile_citation_checks(checks: Sequence[Mapping[str, Any]],
                             material: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把 V 给的那几条结论与"材料里有哪几条被引命题"对齐（缺一条就按 `unknown` 算）。

    四条规矩，都是三态纪律在这一格上的落法：
    - 材料里每一条被引命题都必须有一条结论；V 没给 ⇒ 补一条 `unknown`
      （note 写明"没有给出结论"）。判不了与没判是两件事，但两者都不能签「成立」；
    - 被引命题的档位不够格（`evidence_kind` 低于 `proof_review`，含空串）⇒ 一律改判
      `inadmissible`，不管 V 判的是"用法一致"还是别的。这一档是事实而不是判断：
      业主口径逐字「proof_review级及以上才可引用」，所以它不交给模型自由裁量（模型说
      `consistent` 也照样改判，原文附在 note 里）。判据本体是
      :func:`evidence_kind_admissible`（禁止词表从 `schema.EVIDENCE_KINDS` 现算）；
    - 被引命题不在册（`statement_missing`）⇒ 若 V 写了 `consistent` / `weaker`，
      改判 `unknown`（它读不到的那条命题，判不了"一致"；这一格不许凭印象签字）；
    - V 多给的（材料里没有那条被引命题）仍然交回去，但标 `in_material=False`：
      它不是这一份证明登记的引用，不计入挡不挡签字（挡签字只认材料里的那几条）。
    """
    by_id: dict[str, dict[str, Any]] = {}
    for chk in checks:
        row = {key: chk.get(key) for key in CITATION_CHECK_KEYS}
        row["stmt_id"] = str(row.get("stmt_id") or "").strip()
        row["verdict"] = str(row.get("verdict") or "unknown").strip()
        row["quote_verbatim"] = bool(row.get("quote_verbatim"))
        row["note"] = str(row.get("note") or "").strip()
        # 缺键 ⇒ 材料内（`in_material` 的缺省不许往放行方向走，见
        # `_citation_checks_raw` 的同一条说明）。
        row["in_material"] = row.get("in_material") is not False
        by_id.setdefault(row["stmt_id"], row)
    out: list[dict[str, Any]] = []
    for item in material:
        sid = str(item.get("stmt_id") or "")
        got = by_id.pop(sid, None)
        if got is None:
            got = {"stmt_id": sid, "verdict": "unknown", "quote_verbatim": False,
                   "note": "V 没有对这条被引命题给出结论（材料里有它）",
                   "in_material": True}
        grade = str(item.get("grade") or "")
        # 先判"这一条在不在册"（它比等级更根本：不在册的命题连等级都没有），
        # 再判等级 —— 两档都是挡签的，但点名要说清是哪一种。
        if bool(item.get("statement_missing")) and got["verdict"] in CITATION_SIGNABLE:
            got = dict(got, verdict="unknown",
                       note=(f"被引命题 {sid} 不在册 ⇒ 判不了「一致」"
                             f"（V 原文：{got['note'] or '（无）'}）"))
        admitted = item.get("admissible")
        if admitted is None:
            # 兼容旧材料的形状：没有 `grade` 那一格时，先把历史档位反算成等级
            # （`evidence_kind_admissible` 只做这一步换算，门槛仍是同一个）。新材料
            # （`agent_v.core._citation_material` 的返回）一定带 `grade`，走的是上面那条正路。
            admitted = (citation_grade_admissible(grade) if "grade" in item
                        else evidence_kind_admissible(item.get("evidence_kind")))
        if not bool(item.get("statement_missing")) and not admitted:
            tail = f"（V 原文：{got['note']}）" if got["note"] else ""
            got = dict(got, verdict="inadmissible",
                       note=(f"被引命题 {sid} 现在只是 {grade or '（空：等级算不出来）'}，"
                             f"够不上 {CITATION_EVIDENCE_FLOOR} 级 ⇒ 不够格被引{tail}"))
        out.append(dict(got, in_material=True))
    for sid, got in by_id.items():
        out.append(dict(got, in_material=False))
    return out


def citation_gate(checks: Sequence[Mapping[str, Any]], *, problem: str = "") -> dict[str, Any]:
    """引用核实的签字前置读数（纯函数）：能不能签「成立」，被哪一条挡住。

    返回 `ok` / `blocking` / `weaker` / `problem` / `why`。`blocking` 与 `weaker` 里每项
    是 `{stmt_id, verdict, note}`（点名用）。`problem` 非空是"这一档没查成"（依赖台账
    读不出来）—— 它与"核过、没有引用"必须分开，所以它也挡住签字。
    """
    blocking: list[dict[str, Any]] = []
    weaker: list[dict[str, Any]] = []
    for chk in checks:
        # 材料之外的那几条（V 多给的）不计入签字前置：它们不是这一份证明登记的引用。
        if chk.get("in_material") is False:
            continue
        verdict = str(chk.get("verdict") or "")
        entry = {"stmt_id": str(chk.get("stmt_id") or ""), "verdict": verdict,
                 "note": str(chk.get("note") or "")}
        if verdict in CITATION_BLOCKING:
            blocking.append(entry)
        elif verdict in CITATION_SIGNABLE and verdict != "consistent":
            weaker.append(entry)
    why = ""
    if problem:
        why = (f"引用核实没查成（{problem}）⇒ 这一份不能判「成立」"
               "（没查成不是「核过、一致」）")
    elif blocking:
        shown = "；".join(
            f"{e['stmt_id'] or '（没有号）'} 判 {e['verdict']}"
            + (f"（{e['note']}）" if e["note"] else "")
            for e in blocking)
        why = (f"引用核实挡下了「成立」：{shown} —— "
               "stronger 是引用被夸大、unrelated 是引错了、"
               f"inadmissible 是被引命题的档位低于 {CITATION_EVIDENCE_FLOOR}（不够格被引）、"
               "unknown 是判不了，四档都不许签")
    elif weaker:
        shown = "；".join(
            f"{e['stmt_id'] or '（没有号）'}" + (f"（{e['note']}）" if e["note"] else "")
            for e in weaker)
        why = (f"引用核实通过，但有 {len(weaker)} 条只用到了弱形式：{shown} —— "
               "弱形式不是错，记下来给读的人一句情报")
    return {"ok": not blocking and not problem, "blocking": blocking, "weaker": weaker,
            "problem": str(problem or ""), "why": why}


def citation_blocks(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """这一签里挡住「成立」的引用核实条目（空列表 = 没有被挡）。

    `signs_bit3` 用它：台账那一行写着 `成立`、而引用核实里有一条 `stronger` /
    `unrelated` / `unknown` ⇒ 这一签不许落地。硬闸放在这里（而不是只放在写路径上），
    因为"手写一条成立行"与"V 自己判了成立"在读者眼里没有区别。

    材料之外的那几条（`in_material=False`，V 多给的）不算挡签 —— 与
    :func:`citation_gate` 逐字同一条规则（2026-10-27 收口）：它们不是这一份证明
    登记的引用，挡不挡只看材料里的那几条。改前这里没有这一句，而
    `in_material` 又不落盘 ⇒ 落盘再读回来时两个判定口给出相反结论。
    老行没有这一格 ⇒ 按材料内读（`!= False`，不是 `is True`）。
    """
    checks = row.get("citation_checks")
    if not isinstance(checks, (list, tuple)):
        return []
    return [{"stmt_id": str(c.get("stmt_id") or ""), "verdict": str(c.get("verdict") or ""),
             "note": str(c.get("note") or "")}
            for c in checks if isinstance(c, Mapping)
            and c.get("in_material") is not False
            and str(c.get("verdict") or "") in CITATION_BLOCKING]


def apply_citation_gate(verdict: Mapping[str, Any],
                        gate: Mapping[str, Any]) -> dict[str, Any]:
    """把引用核实的结论并进 V 的结论（纯函数：`parse_verdict` 的形态进、同一形态出）。

    三档处置（业主 2026-10-26 的签字前置；2026-11-01 按两态结论改口径）：
    - 有 `stronger` / `unrelated` / `inadmissible` ⇒ 不许判「成立」：结论改判「有毛病」，
      逐条 error 落进 findings（点明哪一条被引命题、差在哪）。这就是受控拒绝：这一签
      签不成，而"为什么签不成"在台账里逐字可读；
    - 只有 `unknown` ⇒ 这一档是「没查成」，不是「没问题」：结论标签不动（V 没找到缺陷），
      但这一签不签发，理由写「引用核不了」—— `blocking` 里那条 `unknown` 同时是
      `findings` 里一条 error（⇒ `unresolved_errors > 0`）且进 :func:`citation_blocks`
      ⇒ :func:`row_signable` 为假 ⇒ 既不翻位、也不投"连续成立"那一票。
      改前这里把结论改判成第三态 `看不出来`；业主 2026-11-01 裁定那一档不存在，
      而"判不了挡签"这件事本来就有自己的落点（引用闸），不需要借一个假结论来说；
    - 只有 `weaker` ⇒ 结论不动（可签），但加一条 info 把"这一步只用到弱形式"记下来；
    - `gate["problem"]` 非空（依赖台账读不出来 ⇒ 这一档没查成）⇒ 与 `unknown` 同一档：
      结论不动、`citation_gate.problem` 随行落盘 ⇒ `signing_gate_problem` 挡住这一签。
      改前它也把结论改判成第三态；那是把"没查成"折成一个假结论，同一批改掉。

    改判时 `defect_step` 保留模型给的那一步（它可能仍是承重步）；模型没给就留 `None` ——
    这一档的缺陷是按"被引命题"定位的，不是按步号定位的（`parse_verdict` 因此允许
    "有毛病 + 有挡签的引用核实 + 没有步号"这一种组合）。
    """
    out = {
        "verdict": str(verdict.get("verdict") or ""),
        "defect_step": verdict.get("defect_step"),
        "quote": str(verdict.get("quote") or ""),
        "why": str(verdict.get("why") or ""),
        "findings": [dict(f) for f in (verdict.get("findings") or [])],
        "unresolved_errors": 0,
        "citation_checks": [dict(c) for c in (verdict.get("citation_checks") or [])],
        #: 折过档的那一行把模型原话带下去（`apply_citation_gate` 是纯函数，不许吃掉它）。
        "verdict_raw": str(verdict.get("verdict_raw") or ""),
    }
    blocking = list(gate.get("blocking") or [])
    defect = [e for e in blocking if str(e.get("verdict") or "") != "unknown"]
    for entry in blocking:
        kind = f"citation_{entry.get('verdict') or 'unknown'}"
        tail = f"：{entry['note']}" if entry.get("note") else ""
        sid = entry.get("stmt_id") or "（没有号）"
        verdict_text = str(entry.get("verdict") or "")
        if verdict_text == "unknown":
            detail = (f"引用核实：被引命题 {sid} 判不了（unknown）{tail}"
                      "；引用核不了 ⇒ 这一档没查成、这一份不签发（不是「没问题」）")
        elif verdict_text == "inadmissible":
            detail = (f"引用核实：被引命题 {sid} 的档位够不上 {CITATION_EVIDENCE_FLOOR}{tail}"
                      "；档位不够格是事实，与原文一致不一致无关 ⇒ 这一份不能判「成立」")
        else:
            detail = (f"引用核实：被引命题 {sid} 判 {verdict_text}"
                      f"{tail or '：V 没有写理由'}"
                      "；这一条使这一份不能判「成立」")
        out["findings"].append({"level": "error", "step": None, "kind": kind,
                                "detail": detail})
    for entry in (gate.get("weaker") or []):
        tail = f"（{entry['note']}）" if entry.get("note") else ""
        out["findings"].append({
            "level": "info", "step": None, "kind": "citation_weaker",
            "detail": (f"引用核实：这一步只用到了被引命题 "
                       f"{entry.get('stmt_id') or '（没有号）'} 的弱形式{tail}"
                       "；不等于错，但读的人要知道它没有被用满"),
        })
    if defect and out["verdict"] == "成立":
        # 引用被夸大 / 引错 / 档位不够 ⇒ 这是找到了缺陷（缺陷按被引命题定位）。
        out["verdict"] = "有毛病"
    # 只有 `unknown` / 依赖台账读不出来 ⇒ 结论不动（它没找到缺陷）：这一签由引用闸挡住
    # （那几条 error 让 `unresolved_errors > 0`，且 `citation_blocks` / `signing_gate_problem`
    # 也挡）⇒ 不翻位、不投连续成立那一票。这里刻意不造第三态（业主 2026-11-01）。
    if blocking or gate.get("problem"):
        gate_why = str(gate.get("why") or "")
        if gate_why:
            out["why"] = (out["why"] + "；" + gate_why) if out["why"] else gate_why
    out["unresolved_errors"] = sum(1 for f in out["findings"] if f.get("level") == "error")
    return out

# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相引用
# （顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点全部在函数体
# 里，所以只要定义都跑完了，谁先被导入都拿得到。
# 2026-11-20（VERSPLIT2）：指向**定义处**，不指向门面 —— 门面 `verifications` 要先
# import 完这 18 个模块才轮得到再导出本模块，从它取会撞上"还没再导出"的中间态。
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    VerificationError,
)
from .v_vocab import (  # noqa: F401 — 可引门槛的词表在 v_vocab.py
    CITATION_BLOCKING,
    CITATION_CHECK_KEYS,
    CITATION_EVIDENCE_FLOOR,
    CITATION_SIGNABLE,
    CITATION_VERDICTS,
)
