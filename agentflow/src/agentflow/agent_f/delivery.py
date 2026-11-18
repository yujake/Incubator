# -*- coding: utf-8 -*-
"""F 的交差读数：按条读，不是「一条签到手就交差」。

口径：一个 F 可以产出多条成果，不许暗示它一拿到一条定理的证明就交差。F 是否收工靠它
自己评判：是否全面研究了 D 交给它的攻坚任务、是否尽力做出了足够多的成果（也可以是没
成果）、即使没完成原定任务是否产出了一些小的阶段性成果。

读数以「成果」为单位。一条成果 = 一个在册命题号（`stmt:<号>`）：同一号被重交（改稿再交）
仍是同一份成果，不是多条。每一条成果各自读一次签（`agent_f/vsign.delivery_reading` 的
四档），再汇总：

| 格 | 意思 |
|---|---|
| `signed_count` | 「已签」的条数 |
| `pending_count` | 「待签」的条数（还没送审，或审过、连续次数没到 —— 都不是「没过」） |
| `unsigned_count` | 「未签」的条数（V 判过、结论不是能签的那一档；或这一份根本没查成） |
| `coverage` | 已签 ÷ 总数，化成最简分数（0 条已签照实写 `0/N`） |
| `coverage_reading` | 未约分的「已签/总数」—— 要原始条数看这一格 |
| `coverage_ratio` | 0..1 的数；0 条成果时是 `None`（不是 0 —— 没有分母） |
| `state` | `signed_all` / `outputs_settled` / `outputs_unsigned` / `researched_no_output` / `not_started` |
| `delivered` | 「有成果、且每一条成果都已签」（不是「有一条签了」；0 条不算交差完成） |
| `proof_count` | 能叫「证明」的条数（`claim=proof`，只有已签的算） |
| `proof_output_count` | 证明稿份数（`claim=proof` 或 `proof_unsigned`）—— 「有稿、还没签」也是成果；它与 `proof_count` 是两个问题（INV7） |
| `still_unsubmitted` | 有稿、这一趟还没提交的逐条（`state=unsigned` / `rejected` / `unknown`），每行带 `next_action`（summon 形状：`role="V"`） |
| `unfinished` | 还没签、也没被明确放弃的成果（逐条：命题号 / 稿号 + 手稿 + 签的档位） |
| `legal_stop` | 现在收工合不合口径（未签成果没处置 ⇒ 假；「研究过、没成果」⇒ 真） |
| `self_assessment` | 三条自评判据各一档（见下），外加 F 自己写的 `next_move` / `why` 留痕 |

交差不许静默：收工的判据要拦着说"你还有哪些命题未签（也可以选择放弃那些命题），没签的
要继续完善直到拿到 V 签"。所以 `unfinished` 逐条点名（命题号 + 手稿路径 + 签的档位），
不只是一个数；它不替 F 决定下一步 —— `LEGAL_EXITS` 只是举例（换证明路线 / 拆成更弱的
引理 / 补缺工具 / 减弱断言 / 明确放弃 / 判断是误判再送一次），不是枚举、不是系统动作。
但 F 必须留痕：`self_assessment.next_move` 写选了什么、`why` 写理由；没留痕 ⇒
`trail.checked=False`、`close_problems` 点名「它申请收工却没说自己怎么办」。「明确放弃」
是合法出路，落法是台账那一行 `status=abandoned` +
`quote_reason=abandoned@<ISO8601>@<理由>`（三样缺一不可）；放弃之后的成果按 `abandoned`
读（不再算「未签」，也不计入「产出的证明数」）。

三条自评判据（`SELF_CRITERIA`）：`comprehensive`（是否全面研究了任务：`comprehensive` /
`partial` / `not_comprehensive`）、`enough_output`（是否尽力做出了足够多的成果：
`enough_output` / `some_output` / `no_output`）、`partial_output`（即使没完成原定任务，
是否产出了小的阶段性成果：`partial_output` / `none`）。自评由 F 自己在那一轮 JSON 的
`self_assessment` 格写（见 `agent_f.core._attack_prompt` 第 7 段）；F 没写或写得不成形时
这一格不冒充自评：`source="derived"` + `checked=False`，三档按盘上证据推（见
:func:`derived_self_assessment`），`why` 明说「这不是 F 的自评」。

「没成果」是合法的收工理由：`enough_output=no_output` ＋ 研究过（`researched=True`）⇒
`state=researched_no_output`、`is_failure=False`、`legal_stop=True`。它不是失败，也不是
「交差完成」—— 是第三种结局。
"""
from __future__ import annotations

from math import gcd
from typing import Any, Mapping, Sequence

from .submission import (  # noqa: F401 —— 回引：收工自动提交的读那一半（2026-11-11 拆出）
    FAMILY_F, SUBMISSION_FIELDS, SUBMISSION_PREFIX, SUBMISSION_SEP,
    VIA_CLOSING, VIA_SIGN,
    parse_submission, submission_candidates, submission_token, submissions_of,
)

#: 三条自评判据的键（业主原话的三问，键名就是读数格名）。
SELF_CRITERIA: tuple[str, ...] = ("comprehensive", "enough_output", "partial_output")

#: 三条自评判据各自在问什么（逐字对齐业主原话的三问）。
SELF_QUESTIONS: dict[str, str] = {
    "comprehensive": "是否全面研究了 D 交给它的攻坚任务",
    "enough_output": "是否尽力做出了足够多的成果（也可以是没成果）",
    "partial_output": "即使没完成原定任务，是否产出了一些小的阶段性成果",
}

#: 每条判据的受控档位（第一个是"这一条成立"的那一档）。
SELF_TIERS: dict[str, tuple[str, ...]] = {
    "comprehensive": ("comprehensive", "partial", "not_comprehensive"),
    "enough_output": ("enough_output", "some_output", "no_output"),
    "partial_output": ("partial_output", "none"),
}

#: 档位 -> 给人看的标签（读数与手册用同一份词，别处不再各写一份）。
SELF_TIER_LABELS: dict[str, str] = {
    "comprehensive": "全面研究了",
    "partial": "只研究了一部分",
    "not_comprehensive": "还没开始研究",
    "enough_output": "成果足够（都已签）",
    "some_output": "有成果、还没全签",
    "no_output": "没成果（研究了、尽力了 —— 合法的收工理由）",
    "partial_output": "有小的阶段性成果",
    "none": "没有阶段性成果",
}

#: 交差的五档（三态 + 「已处置」 + 「还没开始」）。
STATE_SIGNED_ALL = "signed_all"
STATE_OUTPUTS_SETTLED = "outputs_settled"
STATE_OUTPUTS_UNSIGNED = "outputs_unsigned"
STATE_RESEARCHED_NO_OUTPUT = "researched_no_output"
STATE_NOT_STARTED = "not_started"

#: 固定顺序：从"交差完成"到"还没开始"。
DELIVERY_STATES: tuple[str, ...] = (STATE_SIGNED_ALL, STATE_OUTPUTS_SETTLED,
                                    STATE_OUTPUTS_UNSIGNED,
                                    STATE_RESEARCHED_NO_OUTPUT, STATE_NOT_STARTED)

STATE_LABELS: dict[str, str] = {
    STATE_SIGNED_ALL: "有成果已签",
    STATE_OUTPUTS_SETTLED: "有成果、未全签但都已有结局（签或放弃）",
    STATE_OUTPUTS_UNSIGNED: "有成果未全签",
    STATE_RESEARCHED_NO_OUTPUT: "研究过但无成果",
    STATE_NOT_STARTED: "还没研究",
}

#: 未签成果的出路 —— 「举例，不是枚举」（业主 2026-11-02：「F 自己调控」）。
#: 系统只许做两件：如实列出未签的、要求留痕；不许替它选，也不许把选择变成系统动作。
LEGAL_EXITS: tuple[str, ...] = (
    "换一条证明路线重做那一步",
    "把这条命题拆成几条更弱的引理",
    "去补原证明里缺的工具/引理",
    "减弱自己的断言（定理→条件性结论/猜想）",
    "明确放弃该命题（台账 status=abandoned + quote_reason=abandoned@<ISO8601>@<理由>）",
    "判断这是 V 的误判、带理由再送一次（代价由自己承担）",
)

EXITS_NOTE = ("以上只是举例，不是枚举：选哪条、要不要继续，由 F 自己定；"
              "它必须把「选了什么 + 理由」写进 self_assessment.next_move / why，"
              "系统不替它决定、也不替它驱动")

#: 台账里「明确放弃」那一行的口径（三样缺一不可；只写状态的行仍按未签计）。
ABANDONED_PREFIX = "abandoned@"

#: `delivered` 现在的意思（逐字进读数，别处不再猜）。
DELIVERED_MEANS = ("有成果、且每一条成果都已签 —— 不是「有一条签了」；0 条成果时它是假"
                   "（「没成果」是另一种收工理由，与「交差完成」不是一回事）")

#: 一条成果「凭什么可以叫「证明」」的受控三档（业主 2026-11-02：「如果某命题无V签，
#: F侧就不能声称自己产出了『证明』」）。判定只一处：:func:`claim_of`。
CLAIM_PROOF = "proof"
CLAIM_PROOF_UNSIGNED = "proof_unsigned"
CLAIM_DRAFT = "draft"

#: 受控词表（顺序 = 从"算证明"到"不算"）。
OUTPUT_CLAIMS: tuple[str, ...] = (CLAIM_PROOF, CLAIM_PROOF_UNSIGNED, CLAIM_DRAFT)

CLAIM_LABELS: dict[str, str] = {
    CLAIM_PROOF: "证明（有 V 签）",
    CLAIM_PROOF_UNSIGNED: "待签（还没 V 签，不算证明）",
    CLAIM_DRAFT: "草稿（V 判过没过 / 没查成，不算证明）",
}


def claim_of(state: str, *, signed: bool = False) -> str:
    """这一条成果现在「能不能叫「证明」」（业主原话：无 V 签就不能声称产出了证明）。

    三档：

    - `proof`：有 V 签（`state="signed"` 或 `signed=True`）—— 只有这一档计入「产出的证明数」；
    - `proof_unsigned`：正文在、签还没到（`state="waiting"`：没送审，或审过、连续次数没到）
      —— 它是一份待签的证明，但「还不是」证明；
    - `draft`：V 判过、结论不是能签的那一档，或这一份根本没查成（`rejected` / `unknown`）
      —— 它是草稿/待改稿，「不是」证明。

    为什么要有这一格（而不是看 `signed_count` 就够了）：`signed_count` 回答"签了几条"，
    这一格回答"有几条能叫证明"。把无签的正文说成"我产出了证明"，正是这一批要挡的那句话。
    """
    if signed or str(state or "") == "signed":
        return CLAIM_PROOF
    if str(state or "") == "waiting":
        return CLAIM_PROOF_UNSIGNED
    return CLAIM_DRAFT


def abandoned_of(statement_row: Mapping[str, Any] | None) -> dict[str, Any]:
    """这一条命题被「明确放弃」了没有（三样缺一不可：状态、时间、理由）。

    台账口径（与 `agent_skills` 的 F 手册同源）：`status=abandoned` 且
    `quote_reason=abandoned@<ISO8601>@<理由>`。只写状态、不写时间与理由的行
    「仍按未签计」 —— "我放弃了"这句话本身不是处置，处置要留得下时间与理由。

    放弃是合法出路（业主 2026-11-02：「也可以选择放弃那些命题」）：它之后那一条
    「不再算「未签」」（`unfinished` 里不再出现），但它也「不计入「产出的证明数」」
    （`proof_count` 只数已签的）—— 放弃不等于证明了。
    """
    row = dict(statement_row or {})
    status = str(row.get("status") or "")
    reason = str(row.get("quote_reason") or "")
    out: dict[str, Any] = {"abandoned": False, "checked": True, "at": "", "why": "",
                           "problems": [], "status": status}
    if status != "abandoned":
        return out
    if not reason.startswith(ABANDONED_PREFIX):
        out["problems"].append(
            f"status=abandoned 但 quote_reason 不是 `{ABANDONED_PREFIX}<ISO8601>@<理由>`"
            "（只写状态的行仍按未签计）")
        return out
    rest = reason[len(ABANDONED_PREFIX):]
    at, _, why = rest.partition("@")
    out["at"] = str(at or "").strip()
    out["why"] = str(why or "").strip()
    if not out["at"] or not out["why"]:
        out["problems"].append(
            "放弃那条线缺时间或理由（`abandoned@<ISO8601>@<理由>` 三样缺一不可）"
            f"：收到 {reason!r}")
        return out
    out["abandoned"] = True
    return out


def trail_of(raw: Any) -> dict[str, Any]:
    """F 对「还没签的那些怎么办」的「留痕」：选了什么（`next_move`）+ 理由（`why`）。

    系统只要求"留得下"，「不判它选了哪条」（业主 2026-11-02：「F 自己调控」；
    出路只是举例，不是枚举）。没写 ⇒ `checked=False`，读数里点名"它没留痕"。
    """
    out: dict[str, Any] = {"checked": False, "choice": "", "why": "",
                           "problems": []}
    if not isinstance(raw, Mapping):
        out["problems"].append("F 没写 self_assessment（更没有 next_move / why 留痕）")
        return out
    out["choice"] = str(raw.get("next_move") or raw.get("choice") or "").strip()
    out["why"] = str(raw.get("why") or "").strip()
    if not out["choice"]:
        out["problems"].append("没写 `self_assessment.next_move`：未签的那些它打算怎么办，"
                               "读数里读不到")
    if not out["why"]:
        out["problems"].append("没写 `self_assessment.why`：选了这条路没留理由")
    out["checked"] = not out["problems"]
    return out


def empty_reading(why: str, *, state: str = "") -> dict[str, Any]:
    """没查成时的交差读数（键一个不少，值一律 `None` —— 不许靠"少给键"表达没查成）。"""
    return {
        "checked": False, "outputs": [],
        "total": None, "signed_count": None, "pending_count": None,
        "unsigned_count": None, "proof_count": None, "proof_statements": [],
        "proof_output_count": None,
        "draft_count": None, "abandoned_count": None, "abandoned_statements": [],
        "unfinished": [], "unfinished_count": None,
        "trail": {"checked": False, "choice": "", "why": "", "problems": []},
        "trail_required": False, "legal_stop": False, "is_failure": False,
        "close_problems": [], "coverage": "", "coverage_reading": "",
        "coverage_ratio": None, "coverage_why": why,
        # 收工自动提交的三格（键无条件存在；没查成 ⇒ 空表 + 计数 None）。
        "auto_submitted": [], "auto_submitted_count": None,
        "still_unsubmitted": [],
        "state": state, "state_label": STATE_LABELS.get(state, ""),
        "delivered": False, "delivered_means": DELIVERED_MEANS,
        "researched": {}, "staged": {},
        "self_assessment": {"checked": False, "source": "absent", "why": why,
                            "criteria": {}, "problems": []},
        "conflicts": [], "why": why,
    }


def coverage_of(signed: int, total: int) -> dict[str, Any]:
    """覆盖率三格（`coverage` 最简分数 / `coverage_reading` 原样 / `coverage_ratio`）。

    为什么最简分数：3 条全签时 `coverage` 读作 `1/1`（覆盖率 = 1），1/3 读作 `1/3`；
    要"几条签了、总共几条"看 `signed_count` / `total` / `coverage_reading` —— 那是两个
    不同的问题，别让一个格同时回答。
    """
    total = max(0, int(total))
    signed = max(0, min(int(signed), total))
    if total <= 0:
        return {"coverage": "", "coverage_reading": "0/0", "coverage_ratio": None,
                "coverage_why": "0 条成果 ⇒ 覆盖率没有分母（不是 0%，也不是 100%）"}
    if signed <= 0:
        # 0 没有可约的东西：写 0/1 会把「2 条全没签」读成「只有 1 条」。分母照实给。
        return {"coverage": f"0/{total}", "coverage_reading": f"0/{total}",
                "coverage_ratio": 0.0, "coverage_why": ""}
    g = gcd(signed, total) or 1
    return {"coverage": f"{signed // g}/{total // g}",
            "coverage_reading": f"{signed}/{total}",
            "coverage_ratio": round(signed / total, 4),
            "coverage_why": ""}


def outputs_of(history: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """从 `history` 里数出「成果」：一条成果 = 一个登记下来的 `stmt:<号>`。

    判据只有一条：这一轮的 history 行有没有 `statement_id`。同一号重交
    （改稿再交、或反复送同一份）仍是「同一份」成果 —— 否则 84 计划 `000000`
    的四轮重交会被读成「四条成果」，覆盖率的分母就假了。
    """
    by_sid: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in history or ():
        if not isinstance(row, Mapping):
            continue
        sid = str(row.get("statement_id") or "").strip()
        if not sid:
            continue
        try:
            rnd = int(row.get("round") or 0)
        except (TypeError, ValueError):
            rnd = 0
        cur = by_sid.get(sid)
        if cur is None:
            by_sid[sid] = {"statement_id": sid, "round": rnd,
                           "subgoal": str(row.get("sid") or ""),
                           "action": str(row.get("action") or ""),
                           "submissions": 1}
            order.append(sid)
            continue
        cur["submissions"] = int(cur["submissions"]) + 1
        if rnd >= int(cur.get("round") or 0):
            cur.update(round=rnd, subgoal=str(row.get("sid") or ""),
                       action=str(row.get("action") or ""))
    return [by_sid[sid] for sid in order]


def researched_of(*, history: Sequence[Mapping[str, Any]] = (),
                  subgoals: Sequence[Mapping[str, Any]] = (),
                  rounds: int = 0) -> dict[str, Any]:
    """「研究过没有」：推进过的轮次 + 被碰过的子目标（两样都读，缺一样就如实标）。

    「研究过」不是「有成果」：一个任务可以研究了 8 轮、0 条成果（业主原话：
    「也可以是没成果」）。反过来，一条 history 都没有 ⇒ 那是「还没研究」，
    不许折进「研究过但无成果」（三态纪律）。
    """
    touched: list[str] = []
    for row in history or ():
        if not isinstance(row, Mapping):
            continue
        sid = str(row.get("sid") or "").strip()
        action = str(row.get("action") or "").strip()
        if sid and action not in ("stop", "stall_detected") and sid not in touched:
            touched.append(sid)
    all_sids = [str(s.get("sid") or "") for s in (subgoals or ()) if str(s.get("sid") or "")]
    untouched = [sid for sid in all_sids if sid not in touched]
    return {"researched": bool(touched) or int(rounds or 0) > 0,
            "rounds": int(rounds or 0),
            "subgoals_touched": len(touched),
            "subgoals_total": len(all_sids),
            "untouched": untouched,
            "why": (f"研究过 {len(touched)} 条子目标（共 {len(all_sids)} 条）"
                    if touched else "一条子目标都没被推进过")}


def staged_of(*, history: Sequence[Mapping[str, Any]] = (),
              subgoals: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """「有没有小的阶段性成果」的机器读数（只认盘上写下来的东西，不认散文）。

    四类证据（任一类非空就 `partial_output`）：
    ① 归约轮（`product="reduction"`）：把目标化归成更小的子目标 —— 那本身就是阶段性成果；
    ② `dead_end` 带 `best_partial`：排除的路 / 缩小的范围（`attackround` 强制非空）；
    ③ 子目标上挂着 `experiment_ids` / `evidence_ids` / `proof_experiment_ids`；
    ④ 子目标已 `closed` / `supported_not_proved`（有数值或证明级支持）。
    """
    items: list[dict[str, Any]] = []
    for row in history or ():
        if not isinstance(row, Mapping):
            continue
        product = str(row.get("product") or row.get("action") or "")
        rnd = row.get("round")
        if product == "reduction":
            goals = [str(g.get("goal") or g.get("sid") or "")
                     for g in ((row.get("product_detail") or {}).get("new_subgoals") or [])]
            items.append({"kind": "reduction", "round": rnd,
                          "what": f"归约出 {len(goals) or '若干'} 条更小的子目标"
                                  + (f"：{goals[:3]}" if goals else "")})
        elif product == "dead_end" and row.get("best_partial"):
            items.append({"kind": "dead_end_partial", "round": rnd,
                          "what": f"排除记录 {len(row.get('best_partial') or [])} 条"})
    for sg in subgoals or ():
        if not isinstance(sg, Mapping):
            continue
        sid = str(sg.get("sid") or "")
        ids = (list(sg.get("experiment_ids") or ()) + list(sg.get("evidence_ids") or ())
               + list(sg.get("proof_experiment_ids") or ()))
        if ids:
            items.append({"kind": "subgoal_evidence", "subgoal": sid,
                          "what": f"{sid} 上挂着 {len(ids)} 条证据/实验"})
        if str(sg.get("status") or "") in ("closed", "supported_not_proved"):
            items.append({"kind": "subgoal_status", "subgoal": sid,
                          "what": f"{sid} 已 {sg.get('status')}"})
    return {"partial_output": bool(items), "items": items,
            "why": ("有小的阶段性成果：" + "；".join(str(i.get("what")) for i in items[:4])
                    if items else "盘上没有任何阶段性成果的落点")}


def _clean_tier(criterion: str, raw: Any) -> dict[str, Any]:
    """一条自评判据的一档：接受 `"tier"` 或 `{"tier": ..., "why": ...}`。"""
    why = ""
    if isinstance(raw, Mapping):
        tier = str(raw.get("tier") or raw.get("state") or "").strip()
        why = str(raw.get("why") or "").strip()
    else:
        tier = str(raw or "").strip()
    allowed = SELF_TIERS[criterion]
    return {"tier": tier, "ok": tier in allowed, "allowed": list(allowed),
            "label": SELF_TIER_LABELS.get(tier, ""), "why": why,
            "question": SELF_QUESTIONS[criterion]}


def normalize_self_assessment(raw: Any) -> dict[str, Any]:
    """F 自己写的自评（`self_assessment` 那一格）⇒ 三档读数（「不猜缺的那一档」）。

    三态：`checked=True, source="self"`（三档都受控）/ `checked=False,
    source="absent"`（F 这一趟没写）/ `checked=False, source="unreadable"`（写了，
    但缺格或档位不在词表里 —— 逐条列 `problems`）。缺席与乱写是两件事。
    """
    out: dict[str, Any] = {"checked": False, "source": "absent", "why": "",
                           "next_move": "", "criteria": {}, "problems": [], "raw": raw}
    if raw is None or (isinstance(raw, (str, bytes)) and not str(raw).strip()):
        out["why"] = ("F 这一趟没写自评（`self_assessment` 缺席）⇒ 下面三档是按盘上证据推的，"
                      "不是 F 的自评")
        return out
    if not isinstance(raw, Mapping):
        out.update(source="unreadable",
                   why=f"自评不是对象（收到 {type(raw).__name__}）⇒ 这一格没读成")
        out["problems"].append("self_assessment 必须是对象（三条判据各一档）")
        return out
    problems: list[str] = []
    for criterion in SELF_CRITERIA:
        got = _clean_tier(criterion, raw.get(criterion))
        out["criteria"][criterion] = got
        if not got["ok"]:
            problems.append(f"{criterion}={got['tier']!r} 不在 {got['allowed']} 里"
                            f"（问的是「{got['question']}」）")
    out["problems"] = problems
    out["why"] = str(raw.get("why") or "").strip()
    out["next_move"] = str(raw.get("next_move") or raw.get("choice") or "").strip()
    if problems:
        out["source"] = "unreadable"
        out["why"] = ("自评写得不成形 ⇒ 这一格没读成（不是没写）：" + "；".join(problems)
                      + (f"；F 自己的话：{out['why']}" if out["why"] else ""))
        return out
    out.update(checked=True, source="self",
               why=("F 自己的自评（三条判据逐条写在这一格）："
                    + "；".join(f"{c}=" + str(out["criteria"][c]["tier"])
                               for c in SELF_CRITERIA)))
    for criterion in SELF_CRITERIA:
        out[criterion] = out["criteria"][criterion]["tier"]
    return out


def derived_self_assessment(*, researched: Mapping[str, Any],
                            staged: Mapping[str, Any], total: int,
                            signed: int) -> dict[str, Any]:
    """F 没写自评时，按盘上证据推的三档（「明确标成推的，不是自评」）。

    推法逐条（每条都只读盘上写下来的东西）：

    - `comprehensive`：每条子目标都被推进过 ⇒ `comprehensive`；推过一部分 ⇒ `partial`；
      一条都没推 ⇒ `not_comprehensive`。子目标表是空的但推进过轮次 ⇒ 按轮次算
      （`comprehensive`，理由写"没有子目标表，按推进过的轮次算"）。
    - `enough_output`：0 条成果 ⇒ `no_output`（业主明说"也可以是没成果"）；成果全签 ⇒
      `enough_output`；其余 ⇒ `some_output`。
    - `partial_output`：`staged_of` 有任何一类落点 ⇒ `partial_output`；否则 `none`。
    """
    touched = int(researched.get("subgoals_touched") or 0)
    total_sg = int(researched.get("subgoals_total") or 0)
    if not researched.get("researched"):
        comp, comp_why = "not_comprehensive", "一轮都没推进过 ⇒ 没开始研究"
    elif total_sg <= 0:
        comp, comp_why = "comprehensive", "没有子目标表，按推进过的轮次算"
    elif touched >= total_sg:
        comp, comp_why = "comprehensive", f"{touched}/{total_sg} 条子目标都被研究过"
    elif touched > 0:
        comp, comp_why = ("partial",
                          f"{touched}/{total_sg} 条子目标被研究过；没碰的："
                          f"{list(researched.get('untouched') or [])[:6]}")
    else:
        comp, comp_why = "not_comprehensive", "一条子目标都没被推进过"
    if total <= 0:
        enough, enough_why = ("no_output",
                              "0 条成果 —— 按业主口径这是合法的收工理由"
                              "（研究了、尽力了、没有成果）")
    elif signed >= total:
        enough, enough_why = "enough_output", f"{signed}/{total} 条成果都已签"
    else:
        enough, enough_why = ("some_output",
                              f"有 {total} 条成果、其中 {signed} 条已签 ⇒ 还没全签")
    partial = "partial_output" if staged.get("partial_output") else "none"
    criteria = {
        "comprehensive": {**_clean_tier("comprehensive", comp), "why": comp_why},
        "enough_output": {**_clean_tier("enough_output", enough), "why": enough_why},
        "partial_output": {**_clean_tier("partial_output", partial),
                           "why": str(staged.get("why") or "")},
    }
    out: dict[str, Any] = {
        "checked": False, "source": "derived",
        "why": "F 这一趟没给（或没给成）自评 ⇒ 下面三档是按盘上证据推的，「不是 F 的自评」",
        "criteria": criteria, "problems": [],
    }
    for criterion in SELF_CRITERIA:
        out[criterion] = criteria[criterion]["tier"]
    return out


def _assessment_conflicts(assessment: Mapping[str, Any], *, total: int,
                          signed: int) -> list[str]:
    """自评与盘上事实打架的地方（自评照录，冲突照报 —— 不悄悄改成盘上的读数）。"""
    out: list[str] = []
    if str(assessment.get("source") or "") != "self":
        return out
    enough = str(assessment.get("enough_output") or "")
    if enough == "no_output" and total > 0:
        out.append(f"自评写「没成果」，但盘上有 {total} 条成果（{signed} 条已签）")
    if enough == "enough_output" and total > 0 and signed < total:
        out.append(f"自评写「成果足够」，但盘上只有 {signed}/{total} 条已签")
    return out


def delivery_summary(*, outputs: Sequence[Mapping[str, Any]],
            history: Sequence[Mapping[str, Any]] = (),
            subgoals: Sequence[Mapping[str, Any]] = (), rounds: int = 0,
            self_assessment: Any = None) -> dict[str, Any]:
    """逐条交差读数（纯函数：签的读法不在这里，`outputs` 每项自带 `state`/`signed`）。

    `outputs` 的每一项至少要有 `statement_id` 与 `state`（`vsign` 的四档之一），
    `signed=True` 也认。返回的键见模块 docstring 的那张表。
    """
    items: list[dict[str, Any]] = []
    signed = pending = unsigned = 0
    abandoned_count = 0
    proof_statements: list[str] = []
    proof_output_ids: list[str] = []
    abandoned_statements: list[str] = []
    unfinished: list[dict[str, Any]] = []
    still_unsubmitted: list[dict[str, Any]] = []
    for one in outputs or ():
        got = dict(one or {})
        state = str(got.get("state") or "")
        # 这一项的命题号只取一次：下面"叫不叫证明"那一格与"放弃/未签"那一支读的是同一个。
        sid = str(got.get("statement_id") or "")
        mid = str(got.get("manuscript_id") or "")
        manuscript = str(got.get("manuscript") or "")
        #: 这一条成果的身份：在册命题是 `stmt:<号>`；已登记稿是 `mss:<稿号>`
        #: （INV7：B 的收录在 V 签之后，所以「等签的稿」在 statements 里还没有号）。
        output_id = (f"stmt:{sid}" if sid else
                     (f"mss:{mid}" if mid else manuscript))
        got["output_id"] = output_id
        if state == "signed" or got.get("signed") is True:
            kind, signed = "signed", signed + 1
        elif state == "waiting":
            kind, pending = "pending", pending + 1
        else:
            kind, unsigned = "unsigned", unsigned + 1
        got["counted_as"] = kind
        # ---- 无签不许叫「证明」（业主 2026-11-02）：claim 是这一格唯一的口径。
        claim = claim_of(state, signed=(kind == "signed"))
        got["claim"] = claim
        got["claim_label"] = CLAIM_LABELS.get(claim, "")
        if claim == CLAIM_PROOF:
            if sid:
                proof_statements.append(sid)
            proof_output_ids.append(output_id)
        # ---- 明确放弃的成果：不再算「未签」（也不再计入证明数）。
        aband = dict(got.get("abandoned") or {}) if isinstance(got.get("abandoned"), Mapping) else {}
        if bool(aband.get("abandoned")):
            abandoned_count += 1
            abandoned_statements.append(sid)
            got["unfinished"] = False
        else:
            got["unfinished"] = claim != CLAIM_PROOF
            if got["unfinished"]:
                unfinished.append({
                    "statement_id": sid,
                    "manuscript_id": mid,
                    "output_id": output_id,
                    "manuscript": manuscript,
                    "state": state,
                    "label": str(got.get("label") or ""),
                    "claim": claim,
                    "claim_label": got["claim_label"],
                    "abandoned_problems": list(aband.get("problems") or []),
                    "why": str(got.get("why") or ""),
                })
            # ---- 「有稿、还没提交」的逐条（INV7）：签还没到的那一份稿也是待办。
            # 这一格与收工自动提交的 `still_unsubmitted` 同名同义（那边是「已拿签、还没
            # 写进 tasks.artifacts」；这边是「连签都还没到」）—— 两处都点同一个稿号。
            if (mid or manuscript) and not bool(aband.get("abandoned")):
                still_state = "unsigned" if state in ("waiting", "") else state
                still_unsubmitted.append({
                    "manuscript_id": mid,
                    "manuscript": manuscript,
                    "signed": False,
                    "signed_sha": str(got.get("signed_sha") or ""),
                    "current_sha": str(got.get("sha") or got.get("current_sha") or ""),
                    "sha_matches": bool(got.get("signed_sha")
                                        and str(got.get("signed_sha"))
                                        == str(got.get("sha") or "")),
                    "state": still_state,
                    "why": str(got.get("why") or "") or "未签 ⇒ 不入提交单",
                    "output_id": output_id,
                    "next_action": dict(got.get("next_action") or {}),
                })
        items.append(got)
    total = len(items)
    cov = coverage_of(signed, total)
    researched = researched_of(history=history, subgoals=subgoals, rounds=rounds)
    staged = staged_of(history=history, subgoals=subgoals)
    trail = trail_of(self_assessment)
    assessment = normalize_self_assessment(self_assessment)
    if not assessment.get("checked"):
        derived = derived_self_assessment(researched=researched, staged=staged,
                                          total=total, signed=signed)
        if assessment.get("source") == "unreadable":
            derived["problems"] = list(assessment.get("problems") or [])
            derived["why"] = assessment.get("why") + "；" + str(derived.get("why") or "")
        assessment = derived
    conflicts = _assessment_conflicts(assessment, total=total, signed=signed)
    unfinished_count = len(unfinished)
    trail_required = unfinished_count > 0
    close_problems: list[str] = []
    reopened = signed + abandoned_count
    #: 「证明稿份数」（含待签）：与 `proof_count` 是两个问题（INV7）。只算一次，
    #: `why` 与返回值读同一份 —— 两处各算一遍就会漂。
    proof_outputs = sum(1 for x in items
                        if str(x.get("claim") or "") in
                        (CLAIM_PROOF, CLAIM_PROOF_UNSIGNED))
    if total > 0 and signed >= total:
        state = STATE_SIGNED_ALL
        why = f"{total}/{total} 条成果全部已签 ⇒ 交差完成"
    elif total > 0 and reopened >= total:
        state = STATE_OUTPUTS_SETTLED
        why = (f"有 {total} 条成果：已签 {signed} 条、明确放弃 {abandoned_count} 条 ⇒ "
               "每一条都有结局（放弃的不算未签，但也不算「证明」—— `proof_count` 只数已签的）")
    elif total > 0:
        state = STATE_OUTPUTS_UNSIGNED
        named = "、".join(
            str(o.get("output_id") or f"stmt:{o.get('statement_id')}")
            + (f"（手稿 {o.get('manuscript')}）" if o.get("manuscript") else "")
            + f"[{o.get('claim_label')}]" for o in unfinished[:8])
        why = (f"有 {total} 条成果、其中 {signed} 条已签：待签 {pending} 条、未签 "
               f"{unsigned} 条 ⇒ 还没到收工的时候；"
               f"能叫「证明」的只有已签的那 {signed} 条（`proof_count`）；"
               f"产出的证明稿有 {proof_outputs} 份（`proof_output_count`，含待签）——"
               "有稿未签不是「没产出」；"
               f"还没签的 {unfinished_count} 条：" + (named or "（读不到命题号 / 稿号）"))
        close_problems.append(
            f"还有 {unfinished_count} 条成果没签、也没被明确放弃 ⇒ 不许静默收工")
    elif researched.get("researched"):
        state = STATE_RESEARCHED_NO_OUTPUT
        why = ("研究了、尽力了、0 条成果 ⇒ 合法收工（不是失败）；"
               f"自评=没成果（{assessment.get('enough_output')}）")
    else:
        state = STATE_NOT_STARTED
        why = "0 条成果 ⇒ 还没研究（不是「研究过但无成果」）"
    if trail_required and not trail.get("checked"):
        close_problems.append(
            "它申请收工却没留痕：未签的那些打算怎么办（`self_assessment.next_move`）"
            "与理由（`why`）读不到")
    legal_stop = bool(
        state in (STATE_SIGNED_ALL, STATE_OUTPUTS_SETTLED)
        or (state == STATE_RESEARCHED_NO_OUTPUT
            and str(assessment.get("enough_output") or "") == "no_output"
            and not close_problems)
    )
    if state == STATE_OUTPUTS_UNSIGNED and trail.get("checked"):
        close_problems.append(
            "留痕已读到（它选的是："
            + (trail.get("choice") or "（空）") + "）—— 但未签的还没变成签或放弃")
    return {
        "checked": True,
        "outputs": items,
        "total": total,
        # ---- 收工自动提交（业主 2026-11-11 裁定 ①）：收工那一趟由
        # `agent_f.step._close_reading` 用「已拿签、还没写进 artifacts」的那一版覆盖；
        # 推进轮次里这一格是「有稿、签还没到」的逐条（INV7：不许把等签的稿读成
        # 没有可提交的）。两处同名同义：都点稿号 + 逐条 `state` / `why`。
        "auto_submitted": [], "auto_submitted_count": None,
        "still_unsubmitted": still_unsubmitted,
        "signed_count": signed,
        "pending_count": pending,
        "unsigned_count": unsigned,
        # ---- 产出统计：`proof_count` 只数 claim=="proof" 的那些（业主：无 V 签不许叫证明）。
        # `proof_output_count` 是「证明稿份数」（含待签）—— 它回答"有没有产出"，
        # `proof_count` 回答"有几条能叫证明"（INV7：两个问题不许再混成一格）。
        "proof_count": len(proof_output_ids),
        "proof_statements": proof_statements,
        "proof_output_count": proof_outputs,
        "draft_count": total - len(proof_output_ids),
        # ---- 交差时点名未签成果 + 出路（举例，不替它选）+ 留痕
        "abandoned_count": abandoned_count,
        "abandoned_statements": abandoned_statements,
        "unfinished": unfinished,
        "unfinished_count": unfinished_count,
        "trail": trail,
        "trail_required": trail_required,
        "legal_exits": list(LEGAL_EXITS),
        "exits_note": EXITS_NOTE,
        "legal_stop": legal_stop,
        "is_failure": False,
        "close_problems": close_problems,
        **cov,
        "state": state,
        "state_label": STATE_LABELS[state],
        "delivered": bool(total > 0 and signed >= total),
        "delivered_means": DELIVERED_MEANS,
        "researched": researched,
        "staged": staged,
        "self_assessment": assessment,
        "conflicts": conflicts,
        "why": why + ("；自评与盘上打架：" + "；".join(conflicts) if conflicts else ""),
    }
