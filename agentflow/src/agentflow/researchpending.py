# -*- coding: utf-8 -*-
"""「研究还没做完」的可读判据：台账读数 + 下一动作（唯一实现）。

## 这一格修的是什么

真机 `projects/R-mk-infinite-93`（2026-11-06）：`tasks` 里 D 已经交了一份可用稿、
`experiments` 有 10 行（其中 7 行 `result` 是 `supports` / `refutes`），而
`statements` 与 `documents` 都是 0 行；`research_questions` 还有 1 条 `open`。
板上"未结项"是 0 —— 于是 `agent_loop._pending_work` 的三条判据（新投递 /
未消板项 / 待消费子产出）全不成立，M 每一拍都判"无事可做"并挂机：它每 20 分钟
醒来只查子任务与信箱，再 park。"研究还没做完"在盘上有读数，但没有任何一处把
它变成"不许挂机"的判据。

所以本模块只做一件事：把"研究未尽"从"感觉没活"换成台账上数得出来的判据，
并给出一条确定的下一动作。它不调模型、不写任何东西，纯读。

## 判据（按优先级；每一条都只读既有台账/既有读数）

| 档 | 判据（可读） | 下一动作（按 `specs/m.py` 的边表） |
|---|---|---|
| `candidate_unfiled` | 有结论的 `experiments`（`result ∈ supports/refutes` 且 `evidence_kind ∈ proof/cross_check`）> 0，而非概念 `statements` = 0 | 立命题并派 F 落稿：派 D 立项，由 D 派 F 写命题与证明（M 不直连 F） |
| `statements_unsigned` | `closing.statements_unsigned_reading` 的 `count` > 0（既没有 V 签、也没有被明确放弃的命题） | 派 D 让 F 补签（谁产出谁送 V）；命题已在册的缺签由 B 处置；拿不到签就明确放弃 |
| `signed_unregistered` | 板上开着的 `b-register@` 义务 > 0（稿上已有成立的 V 签、`statements` 里还没入库） | 派 B 收录 |
| `open_questions` | `research_questions` 里还有 `open` / `needs_evidence` / `researching` | 派 A 补检索 / 派 D 继续攻 |
| `manuscript_missing` | 非概念 `statements` > 0 而 `documents` = 0（研究已落成命题，稿子还没有一行） | 派 G 成文（或派 D 先出手稿） |

`pending = bool(gaps)`：任何一条非空都算"研究未尽"。"一件事都没开始"不算：
一个从来没有任何实验/命题/问题的空工作区不产生 gap —— 它是"没有研究对象"，不是
"研究没做完"，这一档不归本读数判（M 的其它政策照旧）。"做完了"也不产生 gap：
有命题、有签（`statements_unsigned = 0`）、没有未收录义务、没有开着的题、有稿
⇒ `pending=False`，挂机照旧允许（不许把 M 变成永动机）。

## 三态

`checked=False` 表示这一格没查成（某张表读不出来 / 未签读数读不出来）：
它同时把 `pending` 置真 —— "不知道"不许折成"研究做完了"，于是挂机那一条会按
fail-closed 挡住。连续挡住的次数上限由调用方（`agent_loop`）管，读数里给
`fingerprint` 当那一笔账的键。

## 与 `conductor.state` / `conductor.patrol` 的关系

两处都把本读数原样挂出来（`research` 那一格）：M 在轮查看盘时与挂机判据看到的是
同一份实现（唯一实现），不另写第二套口径。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from . import schema as S
from . import secretary as SEC
from . import vreceipts as VRC

# 这一档只认"算过、给出了结论"的实验；`inconclusive` 不是候选族。
# 值与 `closing.CONCLUSIVE_EXPERIMENT_RESULTS` 同源（这里不抄第二份字符串表）：
# 迁到函数里取，是为了不在导入期把 `closing` 整条链拖进来。
def _conclusive_results() -> tuple[str, ...]:
    """有结论的实验结果档（唯一真身在 `closing.CONCLUSIVE_EXPERIMENT_RESULTS`）。"""
    from . import closing as CL

    return tuple(CL.CONCLUSIVE_EXPERIMENT_RESULTS)


# "证据等级算核验过"的那两档（`heuristic` 不算：它没有可核的凭据）。
# 取自 `schema.EXPERIMENT_EVIDENCE_KINDS`，写成函数是为了"词表是唯一真身"。
def _verified_kinds() -> tuple[str, ...]:
    """算得上"核验"的证据等级（`heuristic` 排除）。"""
    return tuple(k for k in S.EXPERIMENT_EVIDENCE_KINDS if k != "heuristic")


#: 下一条动作的说明（按 gap code 取；`target` 是这条动作该落到谁身上）。
#: 为什么把"派谁"写在这里：M 的边表不许在这里重写一遍，但动作要能落到一个具体角色才叫"排出动作"；`target` 只是那句话的主语，不是权限面。
_GAP_ACTIONS: dict[str, dict[str, str]] = {
    "candidate_unfiled": {
        "target": "D",
        "summary": ("立命题并派 F 落稿：派 D 立项，由 D 派 F 把候选族写成命题与证明"
                    "（M 不直连 F；命题进册走 B）"),
    },
    "statements_unsigned": {
        "target": "D/B",
        "summary": ("未签稿要补签：派 D 让 F 把稿重新送 V（谁产出谁送审）；"
                    "命题已在册而缺签的由 B 处置；拿不到签就明确放弃原命题"),
    },
    "signed_unregistered": {
        "target": "B",
        "summary": "已签未收录：派 B 把稿上的签收进 statements（清掉板上 b-register 义务）",
    },
    "open_questions": {
        "target": "A/D",
        "summary": "还有开着的 research_questions：派 A 补检索 / 派 D 继续攻",
    },
    "manuscript_missing": {
        "target": "G",
        "summary": "落稿：派 G 成文（或派 D 先出手稿）—— documents 还是 0 行",
    },
}

#: `research_questions` 的两个终态；其余（open / needs_evidence / researching）都算
#: "还开着"。只点名终态、不抄整张词表：整表的唯一真身是 `schema.QUESTION_STATUSES`。
_CLOSED_QUESTION_STATUSES: tuple[str, ...] = ("answered", "dropped")


def _flag(value: Any) -> bool:
    """受控真值读法：`True` 才算真（`1` / `"true"` 这类手写值不许冒充）。"""
    return value is True


def _ids(rows: list[Mapping[str, Any]], field: str, limit: int = 12) -> list[str]:
    """逐条点名（前 `limit` 个，保序去重）。"""
    out: list[str] = []
    for row in rows:
        value = str(row.get(field) or "")
        if value and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return out


def pending_reading(store: Any) -> dict[str, Any]:
    """本工作区"研究还没做完"的读数（纯读；返回 `checked / pending / gaps ...`）。

    ## 返回键

    - `checked`：这一格查成了没有（`False` ⇒ `pending=True`，fail-closed）；
    - `pending`：`bool(gaps)` —— 还有未尽研究，挂机判据据此挡；读不成也置真；
    - `gaps`：按优先级排好的未尽项，每项 `{code, count, ids, why}`；
    - `next_action`：第一条 gap 的下一动作 `{code, target, summary}`（没有 gap ⇒ None）；
    - `counts`：判据用到的全部读数（人在报告里能逐格复核）；
    - `fingerprint`：`gaps` 的稳定指纹（`agent_loop` 的"同一读数连续 N 拍"用它记账）；
    - `reason`：一句话结论 / 没查成的原因。

    三态纪律见模块 docstring：读不出来时 `checked=False` 且 `pending=True`，
    绝不折成"研究做完了"。
    """
    out: dict[str, Any] = {
        "checked": False, "pending": True, "gaps": [], "next_action": None,
        "counts": {}, "fingerprint": "", "reason": "",
    }
    if store is None:
        out["reason"] = "没有工作区 ⇒ 研究是否做完读不了（不是「研究做完了」）"
        return out
    try:
        experiments = [dict(r) for r in store.rows("experiments")]
        statements = [dict(r) for r in store.rows("statements")]
        documents = [dict(r) for r in store.rows("documents")]
        questions = [dict(r) for r in store.rows("research_questions")]
        tasks = [dict(r) for r in store.rows("tasks")]
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不许折成"做完了"
        out["reason"] = f"台账读不出来（{type(exc).__name__}: {exc}）⇒ 研究是否做完判不了"
        return out

    conclusive_results = _conclusive_results()
    verified_kinds = _verified_kinds()
    active_experiments = [dict(r) for r in S.active_experiment_rows(experiments)]
    conclusive = [r for r in active_experiments
                  if str(r.get("result") or "") in conclusive_results
                  and str(r.get("evidence_kind") or "") in verified_kinds]
    propositions = [r for r in statements if str(r.get("kind") or "") != "concept"]
    # 被明确放弃的命题不算"在册的命题"：它的义务已经作废（`closing.statements_unsigned`
    # 对放过的那一档也不计入）。这里与它同一把尺。
    live_statements = [r for r in propositions
                       if str(r.get("status") or "") != "abandoned"]
    open_questions = [r for r in questions
                      if str(r.get("status") or "") not in _CLOSED_QUESTION_STATUSES]
    register_items = [r for r in tasks
                      if str(r.get("input_key") or "").startswith(VRC.REGISTER_PREFIX)
                      and SEC.row_axis(r) == SEC.ROW_AXIS_ITEM_OPEN]

    unsigned: dict[str, Any] = {"checked": True, "count": 0, "rows": [], "reason": ""}
    if live_statements:
        from . import closing as CL

        try:
            unsigned = dict(CL.statements_unsigned_reading(store))
        except Exception as exc:  # noqa: BLE001 —— 这一格没查成
            unsigned = {"checked": False, "count": 0, "rows": [],
                        "reason": f"{type(exc).__name__}: {exc}"}

    counts: dict[str, Any] = {
        "experiments_active": len(active_experiments),
        "experiments_conclusive": len(conclusive),
        "statements": len(live_statements),
        "statements_unsigned": int(unsigned.get("count") or 0),
        "documents": len(documents),
        "questions_open": len(open_questions),
        "registration_open": len(register_items),
    }
    out["counts"] = counts
    if not _flag(unsigned.get("checked")):
        out["reason"] = ("未签命题读数没查成（" + str(unsigned.get("reason") or "没查成")
                         + "）⇒ 研究是否做完判不了（不是「都签了」）")
        return out

    gaps: list[dict[str, Any]] = []
    if counts["experiments_conclusive"] > 0 and counts["statements"] == 0:
        ids = _ids(conclusive, "experiment_id")
        gaps.append({
            "code": "candidate_unfiled",
            "count": counts["experiments_conclusive"],
            "ids": ids,
            "why": (f"{counts['experiments_conclusive']} 条有结论的实验（"
                    f"{'、'.join(ids)}）还没有任何命题在册 —— 候选族还没有被立成命题"),
        })
    if counts["statements_unsigned"] > 0:
        rows = [dict(r) for r in (unsigned.get("rows") or ()) if isinstance(r, Mapping)]
        ids = _ids(rows, "stmt_id")
        gaps.append({
            "code": "statements_unsigned",
            "count": counts["statements_unsigned"],
            "ids": ids,
            "why": (f"{counts['statements_unsigned']} 条命题既没有 V 签、也没有被明确"
                    f"放弃（{'、'.join(ids)}）"),
        })
    if counts["registration_open"] > 0:
        ids = _ids(register_items, "task_id")
        gaps.append({
            "code": "signed_unregistered",
            "count": counts["registration_open"],
            "ids": ids,
            "why": (f"板上开着 {counts['registration_open']} 条「必须收录」义务"
                    f"（{'、'.join(ids)}）：稿上有成立的 V 签，statements 里还没入库"),
        })
    if counts["questions_open"] > 0:
        ids = _ids(open_questions, "question_id")
        gaps.append({
            "code": "open_questions",
            "count": counts["questions_open"],
            "ids": ids,
            "why": (f"{counts['questions_open']} 条 research_questions 还开着"
                    f"（{'、'.join(ids)}）"),
        })
    if counts["statements"] > 0 and counts["documents"] == 0:
        gaps.append({
            "code": "manuscript_missing",
            "count": counts["statements"],
            "ids": _ids(live_statements, "stmt_id"),
            "why": f"{counts['statements']} 条命题在册而 documents 是 0 行 —— 稿子还没有落行",
        })

    out["checked"] = True
    out["pending"] = bool(gaps)
    out["gaps"] = gaps
    out["reason"] = ("查过了：没有未尽研究（有命题 / 有签 / 没有未收录义务 / 没有开着的题"
                     " / 有稿）" if not gaps else
                     f"查过了：{len(gaps)} 类未尽研究 —— " + "；".join(
                         f"{g['code']}×{g['count']}" for g in gaps))
    if gaps:
        first = gaps[0]
        action = dict(_GAP_ACTIONS.get(str(first["code"])) or {})
        if action:
            out["next_action"] = {"code": str(first["code"]), **action}
    key = json.dumps([[g["code"], g["count"], g["ids"]] for g in gaps],
                     ensure_ascii=False, sort_keys=True)
    out["fingerprint"] = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] if gaps else ""
    return out
