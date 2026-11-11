# -*- coding: utf-8 -*-
"""F 的交差读数：按条读，不是「一条签到手就交差」（业主 2026-11-02 原话）。

口径唯一来源：`draft/179-证明优化两阶段录入口径（2026-11-02）.md` §二之三（逐字）：

    一个F可以产出多条成果，不要暗示它一拿到一条定理的证明就交差。
    F具体是否收工靠它自己评判：是否全面研究了D交给它的攻坚任务、是否尽力做出了
    足够多的成果（也可以是没成果）、即使没完成原定任务，是否产出了一些小的阶段性成果。

## 改前（这一格要修掉的读数）

`F.step` 的交差读数只有两格：`delivered: bool` + `delivery_state`（四档），
而它们读的是「这一轮那一份」证明的签（`agent_f/vsign.py`）。于是：

- 一个任务产出 3 条成果、只有最后那一条拿到签 ⇒ `delivered=True`
  —— 「有一个签」被读成了「交差完成」；
- 一个任务「研究了、尽力了、0 条成果」⇒ 没有能读的成果，交差读数无从说起；
  「什么都没交」与「还没开始」在读数上长得一样。

## 改后（逐条 + 自评）

读数以「成果」为单位。一条成果 = 一个在册命题号（`stmt:<号>`）：同一号被重交
（改稿再交）仍是同一份成果，不是多条 —— 84/85 的现场就有这种重交
（`projects/paper-rewrite-84` 计划 `000000` 的第 1–4 轮都是 `stmt:000001`）。

每一条成果各自读一次签（`agent_f/vsign.delivery_reading` 的四档），再汇总：

| 格 | 意思 |
|---|---|
| `signed_count` | 「已签」的条数 |
| `pending_count` | 「待签」的条数（还没送审，或审过、连续次数没到 —— 都不是「没过」） |
| `unsigned_count` | 「未签」的条数（V 判过、结论不是能签的那一档；或这一份根本没查成） |
| `coverage` | 已签 ÷ 总数，化成「最简分数」（3/3 读作 `1/1`、1/3 读作 `1/3`；0 条已签照实写 `0/N`） |
| `coverage_reading` | 未约分的「已签/总数」（`3/3`）—— 要原始条数看这一格 |
| `coverage_ratio` | 0..1 的数；0 条成果时是 `None`（不是 0 —— 没有分母） |
| `state` | `signed_all` / `outputs_settled` / `outputs_unsigned` / `researched_no_output` / `not_started` |
| `delivered` | 「有成果、且每一条成果都已签」（不是「有一条签了」；0 条不算交差完成） |
| `proof_count` | 能叫「证明」的条数（`claim=proof`，只有已签的算） |
| `unfinished` | 还没签、也没被明确放弃的成果（逐条：命题号 + 手稿 + 签的档位） |
| `legal_stop` | 现在收工「合不合业主口径」（未签成果没处置 ⇒ 假；「研究过、没成果」⇒ 真） |
| `self_assessment` | 三条自评判据各一档（见下），外加 F 自己写的 `next_move` / `why` 留痕 |

## 交差不许静默（业主 2026-11-02 追加口径）

「应该是收工的判据拦着说你还有哪些命题未签（也可以选择放弃那些命题），没签的要继续完善
直到拿到V签」。所以交差读数里：

- `unfinished` 「逐条点名」还没签的成果（命题号 + 手稿路径 + 签的档位），不只是一个数；
- 它「不替 F 决定」下一步：`LEGAL_EXITS` 只是「举例」（换证明路线 / 拆成更弱的引理 /
  补缺工具 / 减弱断言 / 明确放弃 / 判断是误判再送一次），不是枚举、不是系统动作；
- 但 F 「必须留痕」：`self_assessment.next_move` 写它选了什么、`why` 写理由；
  没留痕 ⇒ `trail.checked=False`、`close_problems` 点名「它申请收工却没说自己怎么办」；
- 「明确放弃」是合法出路，落法是台账那一行 `status=abandoned` +
  `quote_reason=abandoned@<ISO8601>@<理由>`（三样缺一不可）。放弃之后的成果
  按 `abandoned` 读：「不再算「未签」」（但那一条也不计入「产出的证明数」）。

## 三条自评判据（`SELF_CRITERIA`）

| 键 | 问的原话 | 档 |
|---|---|---|
| `comprehensive` | 是否全面研究了 D 交给它的攻坚任务 | `comprehensive` / `partial` / `not_comprehensive` |
| `enough_output` | 是否尽力做出了足够多的成果（也可以是没成果） | `enough_output` / `some_output` / `no_output` |
| `partial_output` | 即使没完成原定任务，是否产出了一些小的阶段性成果 | `partial_output` / `none` |

自评由 「F 自己」写（一轮的 JSON 里 `self_assessment` 那一格，见
`agent_f.core._attack_prompt` 第 7 段）。F 没写（或写得不成形）时这一格
「不冒充自评」：`source="derived"` + `checked=False`，三档按盘上证据推
（怎么推写在 :func:`derived_self_assessment` 里），`why` 明说「这不是 F 的自评」。

「没成果」是「合法的收工理由」（业主原话「也可以是没成果」）：`enough_output=no_output`
＋ 研究过（`researched=True`）⇒ `state=researched_no_output`、`is_failure=False`、
`legal_stop=True`。它不是失败，也不是「交差完成」—— 是第三种结局。
"""
from __future__ import annotations

from math import gcd
from typing import Any, Mapping, Sequence

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
    abandoned_statements: list[str] = []
    unfinished: list[dict[str, Any]] = []
    for one in outputs or ():
        got = dict(one or {})
        state = str(got.get("state") or "")
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
            proof_statements.append(str(got.get("statement_id") or ""))
        # ---- 明确放弃的成果：不再算「未签」（也不再计入证明数）。
        aband = dict(got.get("abandoned") or {}) if isinstance(got.get("abandoned"), Mapping) else {}
        sid = str(got.get("statement_id") or "")
        if bool(aband.get("abandoned")):
            abandoned_count += 1
            abandoned_statements.append(sid)
            got["unfinished"] = False
        else:
            got["unfinished"] = claim != CLAIM_PROOF
            if got["unfinished"]:
                unfinished.append({
                    "statement_id": sid,
                    "manuscript": str(got.get("manuscript") or ""),
                    "state": state,
                    "label": str(got.get("label") or ""),
                    "claim": claim,
                    "claim_label": got["claim_label"],
                    "abandoned_problems": list(aband.get("problems") or []),
                    "why": str(got.get("why") or ""),
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
    if total > 0 and signed >= total:
        state = STATE_SIGNED_ALL
        why = f"{total}/{total} 条成果全部已签 ⇒ 交差完成"
    elif total > 0 and reopened >= total:
        state = STATE_OUTPUTS_SETTLED
        why = (f"有 {total} 条成果：已签 {signed} 条、明确放弃 {abandoned_count} 条 ⇒ "
               "每一条都有结局（放弃的不算未签，但也不计入产出的证明数）")
    elif total > 0:
        state = STATE_OUTPUTS_UNSIGNED
        named = "、".join(
            f"stmt:{o.get('statement_id')}"
            + (f"（手稿 {o.get('manuscript')}）" if o.get("manuscript") else "")
            + f"[{o.get('claim_label')}]" for o in unfinished[:8])
        why = (f"有 {total} 条成果、其中 {signed} 条已签：待签 {pending} 条、未签 "
               f"{unsigned} 条 ⇒ 还没到收工的时候；"
               f"能叫「证明」的只有已签的那 {signed} 条（未签的不计入产出的证明数）；"
               f"还没签的 {unfinished_count} 条：" + (named or "（读不到命题号）"))
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
        # ---- 收工自动提交（业主 2026-11-11 裁定 ①）：只在收工那一趟由
        # `agent_f.step._close_reading` 填；推进轮次里这三格没有读数（None/[]），
        # 不许被读成「没有可提交的」—— 那一趟根本不读这一格。
        "auto_submitted": [], "auto_submitted_count": None,
        "still_unsubmitted": [],
        "signed_count": signed,
        "pending_count": pending,
        "unsigned_count": unsigned,
        # ---- 产出统计：`proof_count` 只数 claim=="proof" 的那些（业主：无 V 签不许叫证明）
        "proof_count": len(proof_statements),
        "proof_statements": proof_statements,
        "draft_count": total - len(proof_statements),
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


# ============================================================ 收工自动提交（业主 2026-11-11 裁定 ①）
#
# 业主逐字（这一节要落实的那一条）：
#
#     「F侧报告收工时自动提交其名下未提交的V签稿」
#
# 三个前提都写在裁定里，这一节按它排：
#
# 1. 事实来源是 V 的颁发表，不是新表（同日裁定 ②：「维护拿签稿的稿号表可以和
#    V 自动维护的颁发出V签的表进行复用」）⇒ 本模块只读 `out/vsigns/<正文sha>.json`
#    （逐份签 = 证据；`issued.json` 是派生归档，不拿它下结论），不落任何新账；
# 2. 「已提交」的持久记号只有一处：F 自己的 `tasks.artifacts`（框架写、append-only）。
#    判据是「里面有没有这个稿号」，与版本无关（同日追加裁定）；
# 3. 一个稿号 = 一份文件（同日追加裁定：「一个稿号就相当于是该稿的文件名，
#    不再细分 version 几」）⇒ 提交时看的就是该稿号当前那一份文件；签的 sha 与当前
#    正文 sha 不一致 ⇒ 不提交、如实报，不替它挑「哪一版」。

#: F 的稿族（`vsigns.parse_manuscript_name` 的 `family` 格；只认这一族）。
FAMILY_F = "f-proof"

#: 「已提交」记号的前缀（`tasks.artifacts` 里的一项，形态沿用 `table:id` 那一套）。
SUBMISSION_PREFIX = "mss:"

#: 记号的字段分隔符（路径、sha 与 ISO 时刻都不含 `#`）。
SUBMISSION_SEP = "#"

#: 记号里字段的固定顺序（读侧按 `key=value` 取，顺序只影响可读性）。
SUBMISSION_FIELDS: tuple[str, ...] = (
    "path", "body_sha", "sign_sha", "file_sha", "proof_no",
    "statement_id", "at", "submitted_at",
)


def _proof_no_of(raw: Any) -> int:
    """证明号归一：认不出 / <1 ⇒ 1（与 `vsigns` 的缺省 `#p1` 同一口径）。"""
    try:
        no = int(raw or 1)
    except (TypeError, ValueError):
        return 1
    return no if no >= 1 else 1


def submission_token(*, manuscript_id: Any, path: Any = "", body_sha: Any = "",
                     sign_sha: Any = "", file_sha: Any = "", proof_no: Any = 1,
                     statement_id: Any = "", at: Any = "",
                     submitted_at: Any = "") -> str:
    """一份「已提交」记号（`tasks.artifacts` 里的一项）。

    为什么要一格带四样东西（稿号 + 正文 sha + 签 sha + 文件字节 sha + 时刻）：
    D 的携带单要按「地址 + 文件字节 sha256」递稿、B 要按正文 sha 认签，而
    「提交时是哪一版」必须能自证 —— 只留一个稿号，事后没人能判「盘上这份是不是
    当初提交的那一份」。

    `body_sha` 是 V 签盖的那段正文的 sha（`artifact_sha`，全仓同一把尺）；
    `sign_sha` 是签文件（`out/vsigns/<body_sha>.json`）的字节 sha256 —— 它回答
    「凭的是哪一份签」；`file_sha` 是盘上那份 `.md` 的字节 sha256（D/B 认地址用）。
    """
    mid = str(manuscript_id or "").strip()
    if not mid:
        raise ValueError("提交记号必须有稿号（`mss:<稿号>`）—— 没有稿号就没有可判的对象")
    values = {
        "path": str(path or "").strip().replace("\\", "/"),
        "body_sha": str(body_sha or "").strip().lower(),
        "sign_sha": str(sign_sha or "").strip().lower(),
        "file_sha": str(file_sha or "").strip().lower(),
        "proof_no": str(_proof_no_of(proof_no)),
        "statement_id": str(statement_id or "").strip(),
        "at": str(at or "").strip(),
        "submitted_at": str(submitted_at or "").strip(),
    }
    parts = [f"{SUBMISSION_PREFIX}{mid}"]
    for key in SUBMISSION_FIELDS:
        if values[key]:
            parts.append(f"{key}={values[key]}")
    return SUBMISSION_SEP.join(parts)


def parse_submission(token: Any) -> dict[str, Any] | None:
    """一条记号 ⇒ 结构（不是 `mss:` 前缀 ⇒ `None`；坏格静默缺省，不猜值）。"""
    text = str(token or "").strip()
    if not text.startswith(SUBMISSION_PREFIX):
        return None
    chunks = text.split(SUBMISSION_SEP)
    mid = chunks[0][len(SUBMISSION_PREFIX):].strip()
    if not mid:
        return None
    out: dict[str, Any] = {
        "manuscript_id": mid, "token": text, "path": "", "body_sha": "",
        "sign_sha": "", "file_sha": "", "proof_no": 0, "statement_id": "",
        "at": "", "submitted_at": "",
    }
    for chunk in chunks[1:]:
        key, sep, value = chunk.partition("=")
        if sep and key in out:
            out[key] = value
    out["proof_no"] = _proof_no_of(out.get("proof_no"))
    return out


def submissions_of(artifacts: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """`tasks.artifacts` ⇒ `({稿号: 记号结构}, 问题)`。

    同一个稿号出现多条时保留最先读到的那一条（提交是 append-only；后来的重复
    不是第二次提交）。问题只收「长得像 `mss:` 却读不出稿号」的那些 —— 别的
    `artifacts` 项（路径、`file:` / 表行引用）不是这一格的事，不当问题。
    """
    out: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for token in artifacts or ():
        text = str(token or "").strip()
        if not text.startswith(SUBMISSION_PREFIX):
            continue
        rec = parse_submission(text)
        if rec is None:
            problems.append(f"`{text}` 不是一条可读的提交记号（`mss:<稿号>`）⇒ 跳过")
            continue
        out.setdefault(str(rec["manuscript_id"]), rec)
    return out, problems


def submission_candidates(root: Any) -> dict[str, Any]:
    """本工作区里 F 名下的稿 × V 的颁发表 ⇒ 每个稿号「该不该提交」的读数（纯读）。

    ## 事实来源（业主 2026-11-11 裁定 ②：复用 V 的颁发表）

    - 签：`out/vsigns/<正文sha>.json`（逐份）—— 用 `vsigns.credential_reading`
      读并复算（文件在不算签：复算不过就不是签）；`issued.json` 只是派生归档，不拿它下结论；
    - 稿：签文件自己写下的 `artifact_path` + `reports/` 下 F 族前缀的 `*.md`（前缀从
      `manuscriptfamily` 派生，不在这里再写一份；还没签的稿也要能读成「未签 ⇒ 不入提交单」）。

    ## 判据（业主 2026-11-11 追加裁定：一个稿号 = 一份文件）

    - `signed=True` 只在签的 `artifact_sha` == 该文件当前正文 sha、且签复算通过时；
    - 签过、之后正文又改了（两个 sha 不一致）⇒ `state="body_changed_after_sign"`，
      不提交，读数点名两个 sha；
    - 同一个稿号指到两份不同的文件 ⇒ `state="ambiguous_path"`，不提交（这里不替它
      挑「哪一版」：一稿号一文件是业主口径，挑本身就把那条纪律放过了）；
    - 没有签的稿 ⇒ `state="unsigned"`，`why` 逐字说「未签 ⇒ 不入提交单」。

    返回 `{checked, candidates, problems, why}`；`checked=False` = 颁发表/目录列不出来
    （「没查成」，不是「一份都没签」）。
    """
    import hashlib
    from pathlib import Path

    from .. import manuscriptfamily as _MFAM
    from .. import proofregistry as _PR
    from .. import vsigns as _VS

    out: dict[str, Any] = {"checked": True, "candidates": [], "problems": [], "why": ""}
    root_p = Path(str(root or "."))
    d = _VS.signs_dir(root)
    try:
        files = (sorted(p for p in d.glob("*.json") if p.name != _VS.INDEX_NAME)
                 if d.is_dir() else [])
    except OSError as exc:  # noqa: BLE001 —— 列不出来 = 没查成
        out.update(checked=False, why=(
            f"`{_VS.SIGNS_DIR}/` 列不出来（{type(exc).__name__}: {exc}）⇒ "
            "拿签稿这一格没查成（不是「一份都没签」）"))
        return out
    #: 稿号 ⇒ 这一号的签与文件（同号多条目在这里聚，最后一并判「一稿号一文件」）。
    by_mid: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def _bucket(mid: str) -> dict[str, Any]:
        one = by_mid.get(mid)
        if one is None:
            one = {"manuscript_id": mid, "paths": [], "signs": [],
                   "statement_id": "", "proof_no": 0, "at": ""}
            by_mid[mid] = one
            order.append(mid)
        return one

    for path in files:
        cred = _VS.credential_reading(root, path.stem)
        doc = dict(cred.get("sign") or {})
        if not doc:
            out["problems"].append(
                f"{path.name}：签读不出来（{cred.get('why') or '没有理由'}）"
                " ⇒ 这一份这次不提交（没查成，不是「没签」）")
            continue
        if not cred.get("checked"):
            # 签文件读到了、台账读不出来：仍进表（候选会落 `sign_unbacked`），
            # 这样「有签却这次没提交」有一句可读的理由，不是静默消失。
            out["problems"].append(
                f"{path.name}：签的复算没查成（{cred.get('why') or '没有理由'}）"
                " ⇒ 这一份这次不提交（没查成，不是「没签」）")
        rel = str(doc.get("artifact_path") or "").strip().replace("\\", "/")
        parsed = _VS.parse_manuscript_name(rel)
        if str(parsed.get("family") or "") != FAMILY_F:
            continue
        mid = str(parsed.get("manuscript_id") or "")
        if not mid:
            out["problems"].append(
                f"{path.name}：签的载体 {rel!r} 认不出 F 的稿号 ⇒ 不提交（不猜一个号）")
            continue
        try:
            sign_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:  # noqa: BLE001 —— 读不出来仍进表（只是没有签 sha）
            sign_sha = ""
            out["problems"].append(
                f"{path.name}：签文件读不出来（{type(exc).__name__}: {exc}）")
        one = _bucket(mid)
        if rel and rel not in one["paths"]:
            one["paths"].append(rel)
        one["signs"].append({
            "signed_sha": str(cred.get("artifact_sha") or path.stem).strip().lower(),
            "at": str(doc.get("at") or ""),
            "sign_file": _VS.rel(path, root),
            "sign_sha": sign_sha,
            "recomputable": bool(cred.get("recomputable")),
            "code": str(cred.get("problem") or ""),
            "why": str(cred.get("why") or ""),
        })
        if not one["statement_id"]:
            one["statement_id"] = str(doc.get("statement_id") or "").strip()
        if not one["proof_no"]:
            one["proof_no"] = _proof_no_of(doc.get("proof_no"))
        if str(doc.get("at") or "") > str(one["at"] or ""):
            one["at"] = str(doc.get("at") or "")
    # ---- 还没签的稿也要点名（判据 c：「未签 ⇒ 不入提交单」必须读得到）----
    # 前缀从 `manuscriptfamily` 派生（唯一真身）：本文件不再写 `f-proof-` 这个字面量。
    reports = root_p / _VS.SIGN_CARRIER_DIR
    try:
        report_paths = (sorted(reports.glob(f"{_MFAM.prefix_of(FAMILY_F)}*.md"))
                        if reports.is_dir() else [])
    except OSError as exc:  # noqa: BLE001 —— 列不出来 = 这一半没查成
        report_paths = []
        out["problems"].append(
            f"`{_VS.SIGN_CARRIER_DIR}/` 列不出来（{type(exc).__name__}: {exc}）"
            " ⇒ 未签的稿这一半没查成")
    for path in report_paths:
        rel = _VS.rel(path, root)
        parsed = _VS.parse_manuscript_name(rel)
        if str(parsed.get("family") or "") != FAMILY_F:
            continue
        mid = str(parsed.get("manuscript_id") or "")
        if not mid:
            continue
        one = _bucket(mid)
        if rel not in one["paths"]:
            one["paths"].append(rel)
        if not one["proof_no"]:
            one["proof_no"] = _proof_no_of(parsed.get("proof_no"))
    # ---- 每个稿号收成一格读数 ----
    for mid in order:
        one = by_mid[mid]
        paths = [str(x) for x in (one.get("paths") or []) if str(x)]
        signs = [dict(x) for x in (one.get("signs") or [])]
        cand: dict[str, Any] = {
            "manuscript_id": mid,
            "manuscript": paths[0] if paths else "",
            "proof_no": _proof_no_of(one.get("proof_no")),
            "statement_id": str(one.get("statement_id") or ""),
            "signed_sha": "", "sign_sha": "", "at": str(one.get("at") or ""),
            "current_sha": "", "file_sha": "",
            "signed": False, "state": "", "why": "",
            "signs": [{"signed_sha": s["signed_sha"], "at": s["at"],
                       "sign_file": s["sign_file"]} for s in signs],
        }
        if len(paths) > 1:
            cand.update(state="ambiguous_path", why=(
                "同一个稿号指到多份不同的文件（" + "、".join(paths) + "）⇒ "
                "一稿号一文件（业主 2026-11-11），这一份不提交 —— "
                "这里不替它挑「哪一版」"))
            out["candidates"].append(cand)
            continue
        rel = cand["manuscript"]
        if not rel:
            cand.update(state="manuscript_missing", why=(
                "颁发表里这一份签没有 `artifact_path` ⇒ 没有地址可提交"))
            out["candidates"].append(cand)
            continue
        try:
            blob = (root_p / rel).read_bytes()
        except OSError as exc:
            cand.update(state="manuscript_missing", why=(
                f"签的载体 `{rel}` 读不出来（{type(exc).__name__}: {exc}）"
                " ⇒ 不提交（没有可交的文件）"))
            out["candidates"].append(cand)
            continue
        cand["file_sha"] = hashlib.sha256(blob).hexdigest()
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError as exc:
            cand.update(state="manuscript_unreadable", why=(
                f"签的载体 `{rel}` 不是 UTF-8 文本（{exc}）⇒ 不提交"))
            out["candidates"].append(cand)
            continue
        cand["current_sha"] = _PR.proof_sha(text)
        matching = [s for s in signs if s["signed_sha"] == cand["current_sha"]]
        if matching:
            hit = matching[0]
            cand.update(signed_sha=hit["signed_sha"], sign_sha=hit["sign_sha"],
                        at=str(hit["at"] or cand["at"]))
            if hit["recomputable"]:
                cand.update(signed=True, state="signed", why=(
                    f"已拿签（签 sha={hit['signed_sha']}，与现行正文一致）⇒ 可提交"))
            else:
                cand.update(state="sign_unbacked", why=(
                    f"签文件在、sha 也与现行正文一致（{hit['signed_sha']}），但复算不上"
                    f"（{hit['code'] or '?'}）：{hit['why']} ⇒ 不提交"
                    "（这也是一条签，只是签不住）"))
        elif signs:
            latest = max(signs, key=lambda s: str(s.get("at") or ""))
            cand.update(signed_sha=latest["signed_sha"], sign_sha=latest["sign_sha"],
                        at=str(latest["at"] or ""), state="body_changed_after_sign",
                        why=(
                            f"这一份签过之后正文又变了（签 sha={latest['signed_sha']} / "
                            f"现在 sha={cand['current_sha']}）⇒ 按只读/冻结纪律这不该发生，"
                            "不提交（不是「取哪一版」）"))
        else:
            cand.update(state="unsigned", why=(
                "未签 ⇒ 不入提交单（V 的颁发表里没有这一份现行的签）"))
        out["candidates"].append(cand)
    out["why"] = (f"颁发表里 {len(files)} 份签、盘上 {len(report_paths)} 份 F 的稿 ⇒ "
                  f"{len(out['candidates'])} 个稿号"
                  + (f"；{len(out['problems'])} 条读数问题" if out["problems"] else ""))
    return out
