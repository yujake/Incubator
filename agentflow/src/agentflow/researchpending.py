# -*- coding: utf-8 -*-
"""「研究还没做完」的可读判据：台账读数 + 下一动作（唯一实现）。

## 这一格修的是什么

真机事故：`tasks` 里 D 已经交了一份可用稿、`experiments` 有几行有结论，而 `statements`
与 `documents` 都是 0 行；`research_questions` 还有一条 `open`。板上"未结项"是 0 ——
于是 `agent_loop._pending_work` 的三条判据（新投递 / 未消板项 / 待消费子产出）全不
成立，M 每一拍都判"无事可做"并挂机：它每 20 分钟醒来只查子任务与信箱，再 park。
"研究还没做完"在盘上有读数，但没有任何一处把它变成"不许挂机"的判据。

所以本模块只做一件事：把"研究未尽"从"感觉没活"换成台账上数得出来的判据，
并给出一条确定的下一动作。它不调模型、不写任何东西，纯读。

## 判据（按优先级；每一条都只读既有台账/既有读数）

| 档 | 判据（可读） | 下一动作（按 `specs/m.py` 的边表） |
|---|---|---|
| `concept_missing` | 研究型项目（有实验/开着的问题/文献/稿子）里，`statements` 的 concept 行 = 0 | 派 B 从已读文献/文档里登记概念行（概念行只由 B 经 `Secretary.write_concept_row` 写；C 的动作面只产 `AnalysisReport`，写不出概念行） |
| `candidate_unfiled` | 有结论的 `experiments`（`result ∈ supports/refutes` 且 `evidence_kind ∈ proof/cross_check`）> 0，而非概念 `statements` = 0 | 立命题并派 F 落稿：派 D 立项，由 D 派 F 写命题与证明（M 不直连 F） |
| `statements_unsigned` | `closing.statements_unsigned_reading` 的 `count` > 0（既没有 V 签、也没有被明确放弃的命题） | 派 D 让 F 补签（谁产出谁送 V）；命题已在册的缺签由 B 处置；拿不到签就明确放弃 |
| `manuscript_unsigned` | `agent_f.pending.unsubmitted_reading` 的 `count` > 0：盘上「已登记」（稿头元信息 `proofregistry.parse_entry` 的 `checked` 或产物台账那一行）、V 签还没到的稿（产出者 F / E / B 三族都算，业主 2026-11-18「谁写稿，谁就对稿负责」）。与 `statements_unsigned` 分开量：那量命题台账行，这一格量盘上的稿 —— 稿在 B 收录之前没有 `statements` 行，所以那一刻它读 0 | 转 D（由 D 派产出者把稿送 V）：M 的边表只到 D，不直连 F / E / V |
| `signed_unregistered` | 板上开着的 `b-register@` 义务 > 0（稿上已有成立的 V 签、`statements` 里还没入库） | 派 B 收录 |
| `open_questions` | `research_questions` 里还有 `open` / `needs_evidence` / `researching` | 派 A 补检索 / 派 D 继续攻 |
| `manuscript_missing` | 非概念 `statements` > 0 而 `documents` = 0（研究已落成命题，稿子还没有一行） | 派 G 成文（或派 D 先出手稿） |

`concept_missing` 与 `candidate_unfiled` 是两条独立的分支，缺一不可：
只排"再做一轮实验/穷举"而不看概念面时，概念行一行都不会长出来 —— 概念面空着，
说明文献整理这一环（B 的交付面）还没做完，这就是"研究未尽"里最先可读的那一格。

这一档的动作主语是 B 而不是 C：概念行的唯一写侧在
B 那一侧（`conceptrows` → `Secretary.write_concept_row`，契约第 4 条逐字"写经秘书"：
五元位 / 洗名 / 概念同一性同一份实现）；C 的动作面全是分析（`hottest` / `paths` /
`cold` / `gaps` / `neighbors` / `relations_between` 产 `AnalysisReport`），一行概念
都写不出来 ⇒ 派 C 是死路：派出去也长不出概念行，这条"未尽项"永远消不掉。理由也不是
"概念面是 F 的可引池"：可引池 = 在册 ∧ 等级 ≥ `pre_theorem` 的命题
（`depsection.citable_pool`），与 concept 行无关。

概念面那一档排在命题面之前（上表就是这么排的），两条各自的判据都必须能单独触发
（判据见 `tests/test_m_must_not_park_with_research_unfinished.py` 的 a1/a2 与 b1/b2）。

`manuscript_unsigned` 与 `statements_unsigned` 是相邻但不同阶段的两格（INV7，
`projects/lp-ball-7`）：10:02:18 F 把 `reports/f-proof-000001.md` 登记进盘
（正文 sha `ce0f72…`、`v_sign.state=unsigned`），而 B 的收录在 V 签之后 ⇒ 那一刻
`statements` 里没有这一行、`statements_unsigned` 读 0。M 的巡查读数于是只有
`statements=1 / statements_unsigned=0 / documents=0`，没有任何一格提醒它「该催签」。
这一格补的就是「盘上有稿、签还没到」，逐份点名（稿路径 + 正文 sha + 等待时长）；
它的扫描复用 `agent_f.pending`（同一个 `scan_registered` / `unsubmitted_reading`），
不另写一份「已登记」判据 —— 两份口径会让「产出者看到的稿」与「M 看到的稿」静默分家。
2026-11-18 业主裁定「谁写稿，谁就对稿负责」之后这一格覆盖 F / E / B 三族的稿
（产出者从台账 `producer` 字段读、缺台账行才退回稿族），处置建议按这份稿的
产出者现读：「转 D（由 D 派 F / E / B 把稿送 V）」—— M 没有直连 F / E / V 的边
（`capabilities._INDIRECT_FROM_M = {F, V}`），写「M 派 F / M 派 V」是越界指令。

`pending = bool(gaps)`：任何一条非空都算"研究未尽"。"一件事都没开始"不算：
一个从来没有任何实验/命题/问题/文献/稿子的空工作区不产生 gap —— 它是"没有研究
对象"，不是"研究没做完"，这一档不归本读数判（M 的其它政策照旧）。"做完了"也不
产生 gap：有 concept、有命题、有签（`statements_unsigned = 0`）、没有未收录义务、
没有开着的题、没有等签的稿（`manuscript_unsigned = 0`）、有稿 ⇒ `pending=False`，
挂机照旧允许（不许把 M 变成永动机）。

## 三态

`checked=False` 表示这一格没查成（某张表读不出来 / 未签读数读不出来 / 盘上稿那一格
列不出来）：它同时把 `pending` 置真 —— "不知道"不许折成"研究做完了"，于是挂机那一条
会按 fail-closed 挡住。连续挡住的次数上限由调用方（`agent_loop`）管，读数里给
`fingerprint` 当那一笔账的键。

## 与 `conductor.state` / `conductor.patrol` 的关系

本读数挂在两处：`conductor.patrol` 的异常清单（`_research_anomaly_line` 念的就是
它）与 M 的挂机判据（`_park_gate` 的 `run.park["research"]` 与提示词
`_research_block`）。三处读的是同一份实现（唯一实现），不另写第二套口径。
`conductor.state` 不挂这一格（它只给逐表计数）—— 别把"state 上没有"读成
"M 看不到"：巡查与挂机这两条路都看得到。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from . import schema as S
from . import secretary as SEC
from . import obligations as OBL

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
    "concept_missing": {
        "target": "B",
        "summary": ("派 B 从已读文献/文档里登记概念行（概念行只由 B 经 "
                    "`Secretary.write_concept_row` 写，C 只做分析）"),
    },
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
    "manuscript_unsigned": {
        "target": "D",
        # 逐字口径（INV7 业主指令）：M 的边表只到 D ⇒ 首跳必须是"转 D"；
        # 「派 <产出者> / 派 V」只出现在「（由 D …）」那一句里，那是 D 的动作，不是
        # M 的指令。这一句的主角按这一格逐份点名的产出者现读
        # （`_manuscript_action_text`）：只有 F 时逐字仍是「由 D 派 F …」。
        "summary": ("转 D（由 D 派产出者把稿送 V）：盘上已有登记、V 签还没到的稿 —— "
                    "M 的边表只到 D，不直连 F / E / V；送审与拿签都由 D 那一支走完"),
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
    seen: set[str] = set()
    for row in rows:
        value = str(row.get(field) or "")
        if value and value not in seen:
            out.append(value)
            seen.add(value)
        if len(out) >= limit:
            break
    return out


def _gap_concept_missing(counts: Mapping[str, Any]) -> dict[str, Any] | None:
    """分支甲：概念面是不是空的（研究型项目里 concept 行 = 0）。

    为什么这一条排在"候选族"前面：只排实验时概念行一行都没长出来 ——
    概念面是这一档最先可读的缺口。

    为什么动作对象是 B 而不是 C：概念行只由 B 经
    `Secretary.write_concept_row` 写，C 的动作面全是分析（产 `AnalysisReport`）——
    派 C 也长不出概念行，那条"未尽项"永远消不掉。

    作用域：只对"研究型项目"触发（`research_shaped=True`）。一个空工作区
    （没有实验 / 问题 / 文献 / 稿子）不产生这一条 —— 它是"没有研究对象"，
    不是"概念面缺席"，否则 M 在任何空工作区里都挂不了机（连"打个招呼"的任务
    也会被派去登记概念）。
    """
    if int(counts.get("concepts") or 0) > 0:
        return None
    if not bool(counts.get("research_shaped")):
        return None
    return {
        "code": "concept_missing",
        "count": 1,
        "observed": 0,
        "ids": [],
        "why": ("研究型项目里 statements 的 concept 行是 0 —— 概念面还没建："
                "概念行只由 B 经 `Secretary.write_concept_row` 写（C 只做分析），"
                "所以要派 B 登记概念行"),
    }


def _gap_candidate_unfiled(counts: Mapping[str, Any],
                           conclusive: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    """分支乙：已有核验结论、而对应命题不存在（非概念 statements = 0）。

    "对应命题不存在"取的是可读的那一格：非概念 `statements` = 0。不做"实验 claim
    与命题正文逐条配对"—— 那种配对要靠相似度，配不上时读数永远非空（永动机），
    而"一条命题都还没立"是它确定性的下界：只要还有任何一条命题在册，这一条就消失，
    剩下的候选族由 `open_questions` / 后续轮次继续盯。
    """
    if int(counts.get("experiments_conclusive") or 0) <= 0:
        return None
    if int(counts.get("statements") or 0) > 0:
        return None
    ids = _ids(list(conclusive), "experiment_id")
    return {
        "code": "candidate_unfiled",
        "count": int(counts["experiments_conclusive"]),
        "observed": int(counts["experiments_conclusive"]),
        "ids": ids,
        "why": (f"{counts['experiments_conclusive']} 条有结论的实验（"
                f"{'、'.join(ids)}）还没有任何命题在册 —— 候选族还没有被立成命题"),
    }


def _manuscript_cell_text(row: Mapping[str, Any]) -> str:
    """一份稿的人话读数（唯一实现：`agent_f.pending.manuscript_cell_text`）。"""
    from .agent_f import pending as FP

    return FP.manuscript_cell_text(row)


def _manuscript_action_text(rows: Any) -> str:
    """这一格下一动作的那句话：主角是这份稿的产出者（不写死 F）。

    只有 F 时逐字仍是「转 D（由 D 派 F 把稿送 V）」（INV7 的判据 b/c 就断言这一句）；
    产出者是 E / B 时换成它们；判不出产出者才退回「产出者」这个词（不猜一个角色）。
    """
    roles = sorted({str(r.get("producer_role") or "") for r in (rows or ())
                    if isinstance(r, Mapping) and str(r.get("producer_role") or "")})
    who = "/".join(roles) if roles else "产出者"
    return (f"转 D（由 D 派 {who} 把稿送 V）：盘上已有登记、V 签还没到的稿 —— "
            "M 的边表只到 D，不直连 F / E / V；送审与拿签都由 D 那一支走完")


def _manuscripts_unsigned(store: Any, *, role: str = "", instance: str = "") -> dict[str, Any]:
    """已登记、V 签还没到的稿（M 的读数；INV7 第 ⑤ 条 / 业主 2026-11-18）。

    `role` / `instance` 给了就只数这个实例名下的稿（K8）：M 的巡查默认不给
    （工作区级读数 —— M 是主控，全局就是它的"我名下"，见 K10 的 MP-01/02）；
    产出者实例自查时给实例标签，同族里没有实例归属的稿进 `unattributed`，
    不算给谁、也不静默丢掉。

    ## 为什么复用 `agent_f.pending` 而不是自己扫 `reports/`

    产出者那一侧（`delivery` / 挂机判据 / 收工门）已经有一份「已登记、V 签还没到」
    的唯一扫描（`agent_f.pending.scan_registered` → `unsubmitted_reading`）。M 这一格
    若另写一份 glob + `parse_entry`，两份口径就会在"什么算已登记 / 什么算未签"上
    静默分家，而分家不会有任何一处报错 —— 所以这里直接消费同一份扫描（判据
    `tests/test_m_reads_the_unsigned_manuscript_gap.py` 的 d：把共享扫描打桩成空 ⇒
    M 这一格必红；若抄了一份，打桩就不会影响它）。

    等待时长 / 登记时刻 / 稿路径 + sha 的读数也由那一份扫描给（`waiting_sec` /
    `waiting_text` / `registered_at`），这一格不再自己取时 —— 两个取时口会让同一份稿
    在 M 与产出者两侧读到两个"等了多久"。

    ## 返回

    `{checked, count, rows, problems, why}`；`rows` 每项
    `{manuscript, manuscript_id, sha, producer_role, registered_at, waiting_sec,
    waiting_text, state, state_label, why}`。三态：列不出来 / 读不成 ⇒ `checked=False`
    （调用方 fail-closed），不折成"没有等签的稿"。
    """
    out: dict[str, Any] = {"checked": True, "count": 0, "rows": [],
                           "problems": [], "why": "", "owner_instance": "",
                           "unattributed": []}
    try:
        from .agent_f import pending as FP

        got = dict(FP.unsubmitted_reading(
            getattr(store, "root", ""), store=store,
            producer=(str(role or "").strip() or None),
            owner=(str(instance or "").strip() or None)))
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不是"没有"
        out.update(checked=False,
                   why=f"已登记稿读数没查成（{type(exc).__name__}: {exc}）")
        return out
    out["owner_instance"] = str(instance or "").strip()
    out["unattributed"] = [{"manuscript": str(r.get("manuscript") or ""),
                            "producer_role": str(r.get("producer_role") or "")}
                           for r in (got.get("unattributed") or ())
                           if isinstance(r, Mapping)]
    out["problems"] = [str(x) for x in (got.get("problems") or ())]
    if not bool(got.get("checked")):
        out.update(checked=False,
                   why=str(got.get("why") or "已登记稿这一格没查成（不是「没有稿」）"))
        return out
    rows: list[dict[str, Any]] = []
    for item in got.get("items") or ():
        if not isinstance(item, Mapping):
            continue
        rows.append({
            "manuscript": str(item.get("manuscript") or ""),
            "manuscript_id": str(item.get("manuscript_id") or ""),
            "sha": str(item.get("sha") or ""),
            "producer_role": str(item.get("producer_role") or ""),
            "registered_at": str(item.get("registered_at") or ""),
            "waiting_sec": item.get("waiting_sec"),
            "waiting_text": str(item.get("waiting_text") or ""),
            "state": str(item.get("state") or ""),
            "state_label": str(item.get("state_label") or ""),
            "why": str(item.get("why") or ""),
        })
    out["rows"] = rows
    out["count"] = len(rows)
    out["why"] = (("；".join(_manuscript_cell_text(r) for r in rows[:6]))
                  if rows else str(got.get("why")
                                   or "没有「已登记、V 签还没到」的稿"))
    return out


def pending_reading(store: Any, *, role: str = "", instance: str = "") -> dict[str, Any]:
    """本工作区"研究还没做完"的读数（纯读；返回 `checked / pending / gaps ...`）。

    ## 返回键

    - `checked`：这一格查成了没有（`False` ⇒ `pending=True`，fail-closed）；
    - `pending`：`bool(gaps)` —— 还有未尽研究，挂机判据据此挡；读不成也置真；
    - `gaps`：按优先级排好的未尽项，每项 `{code, count, ids, why}`（`concept_missing`
      那一档另有 `observed=0`：缺的是概念面本身，不是"0 条待办"；`manuscript_unsigned`
      那一档另有 `manuscripts`：逐份 `{manuscript, sha, registered_at, waiting_sec, ...}`）；
    - `next_action`：第一条 gap 的下一动作 `{code, target, summary}`（没有 gap ⇒ None）；
    - `counts`：判据用到的全部读数（人在报告里能逐格复核）；`statements_unsigned` 与
      `manuscript_unsigned` 是两格：前者量命题台账行，后者量盘上已登记、V 签还没到
      的 F 稿 —— 任何一格都不从另一格推出来；
    - `fingerprint`：`gaps` 的稳定指纹（`agent_loop` 的"同一读数连续 N 拍"用它记账）；
    - `reason`：一句话结论 / 没查成的原因。

    三态纪律见模块 docstring：读不出来时 `checked=False` 且 `pending=True`，
    绝不折成"研究做完了"。

    ## `role` / `instance`：按实例读数（K8）

    不给 ⇒ 工作区级（M 的巡查；M 是主控，全局就是「我名下」）。给了 ⇒
    `manuscript_unsigned` 只数这个实例产出的稿，同族里没有实例归属的稿进
    `counts["manuscript_unsigned_unattributed"]`（不静默算给任何实例）。
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
        literature = [dict(r) for r in store.rows("literature")]
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
    propositions: list[Mapping[str, Any]] = []
    concepts: list[Mapping[str, Any]] = []
    for row in statements:
        if str(row.get("kind") or "") == "concept":
            concepts.append(row)
        else:
            propositions.append(row)
    # 被明确放弃的命题不算"在册的命题"：它的义务已经作废（`closing.statements_unsigned`
    # 对放过的那一档也不计入）。这里与它同一把尺。
    live_statements = [r for r in propositions
                       if str(r.get("status") or "") != "abandoned"]
    open_questions = [r for r in questions
                      if str(r.get("status") or "") not in _CLOSED_QUESTION_STATUSES]
    register_items = [r for r in tasks
                      if str(r.get("input_key") or "").startswith(OBL.REGISTER_PREFIX)
                      and SEC.row_axis(r) == SEC.ROW_AXIS_ITEM_OPEN]

    unsigned: dict[str, Any] = {"checked": True, "count": 0, "rows": [], "reason": ""}
    if live_statements:
        from . import closing as CL

        try:
            unsigned = dict(CL.statements_unsigned_reading(store))
        except Exception as exc:  # noqa: BLE001 —— 这一格没查成
            unsigned = {"checked": False, "count": 0, "rows": [],
                        "reason": f"{type(exc).__name__}: {exc}"}
    # 盘上「已登记、V 签还没到」的 F 稿（INV7）。与上面的命题行读数分开取、分开列：
    # 它们量的是不同阶段（命题台账行 vs 盘上的稿），一份稿在 B 收录之前没有 statements 行。
    manuscripts = _manuscripts_unsigned(store, role=role, instance=instance)

    counts: dict[str, Any] = {
        "concepts": len(concepts),
        "experiments_active": len(active_experiments),
        "experiments_conclusive": len(conclusive),
        "statements": len(live_statements),
        "statements_unsigned": int(unsigned.get("count") or 0),
        "manuscript_unsigned": int(manuscripts.get("count") or 0),
        "manuscript_unsigned_unattributed": len(manuscripts.get("unattributed") or ()),
        "documents": len(documents),
        "literature": len(literature),
        "questions_open": len(open_questions),
        "registration_open": len(register_items),
        # 「研究型项目」= 盘上已有任何可供研究的对象。空工作区不适用概念面那一条
        # （见 `_gap_concept_missing` 的 docstring）。
        "research_shaped": bool(active_experiments or open_questions
                                or literature or documents),
    }
    out["counts"] = counts
    if not _flag(unsigned.get("checked")):
        out["reason"] = ("未签命题读数没查成（" + str(unsigned.get("reason") or "没查成")
                         + "）⇒ 研究是否做完判不了（不是「都签了」）")
        return out
    if not _flag(manuscripts.get("checked")):
        out["reason"] = ("已登记稿读数没查成（" + str(manuscripts.get("why") or "没查成")
                         + "）⇒ 研究是否做完判不了（不是「没有等签的稿」）")
        return out

    gaps: list[dict[str, Any]] = []
    # 分支甲先于分支乙：概念面是这一档最先可读的缺口；两条各自独立、都能单独触发。
    concept_gap = _gap_concept_missing(counts)
    if concept_gap is not None:
        gaps.append(concept_gap)
    candidate_gap = _gap_candidate_unfiled(counts, conclusive)
    if candidate_gap is not None:
        gaps.append(candidate_gap)
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
    # 盘上已登记、V 签还没到的稿（INV7 第 ⑤ 条）：与上面的命题行那一格分开列。
    # 为什么排在命题未签之后、其它档之前：它是"已经走到送审这一步"的最短闭环 ——
    # 稿在盘上、只差一次送审；把它压到"派 A 补检索 / 派 D 继续攻"后面，M 就会先开
    # 新战场而把手上那份稿放着（真机 lp-ball-7 09:59:41 的 next_action 正是这样）。
    if counts["manuscript_unsigned"] > 0:
        rows = [dict(r) for r in (manuscripts.get("rows") or ())
                if isinstance(r, Mapping)]
        gaps.append({
            "code": "manuscript_unsigned",
            "count": counts["manuscript_unsigned"],
            "ids": _ids(rows, "manuscript"),
            "manuscripts": rows,
            "why": (f"{counts['manuscript_unsigned']} 份稿已登记、V 签还没到"
                    + ("（产出者：" + "、".join(sorted(
                        {str(r.get("producer_role") or "") for r in rows
                         if str(r.get("producer_role") or "")})) + "）"
                       if any(str(r.get("producer_role") or "") for r in rows) else "")
                    + " —— "
                    + "；".join(_manuscript_cell_text(r) for r in rows[:6])
                    + "（与 statements_unsigned 分开量：那量命题台账行，这一格量盘上的稿）"),
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
    out["reason"] = ("查过了：没有未尽研究（有概念面 / 有命题 / 有签 / 没有等签的稿"
                     " / 没有未收录义务 / 没有开着的题 / 有稿）" if not gaps else
                     f"查过了：{len(gaps)} 类未尽研究 —— " + "；".join(
                         f"{g['code']}×{g['count']}" for g in gaps))
    if gaps:
        first = gaps[0]
        action = dict(_GAP_ACTIONS.get(str(first["code"])) or {})
        if action and str(first["code"]) == "manuscript_unsigned":
            # 主角按这一格逐份点名的产出者现读（只有 F 时逐字仍是「由 D 派 F …」）。
            action["summary"] = _manuscript_action_text(first.get("manuscripts") or ())
        if action:
            out["next_action"] = {"code": str(first["code"]), **action}
    key = json.dumps([[g["code"], g["count"], g["ids"]] for g in gaps],
                     ensure_ascii=False, sort_keys=True, default=str)
    out["fingerprint"] = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] if gaps else ""
    return out
