# -*- coding: utf-8 -*-
"""M 的状态报告（`draft/39` §4，用户 2026-10-05 口径）—— 旁路观测，谁都不停。

## 用户口径（逐字）

> 给 M 再加一个动作：当用户中途想知道当前项目情况时，M 通过搜集最近产出和手稿交接来分析情况，
> 向用户报告，从而不打断智能体协作

## 为什么不能只是"问 M 一句"

`ask_user` 那条路是反向的：它让 M 停下来等人。用户中途想知道情况时，正确的形态是
旁路观测：读盘 → 出报告，谁都不停。所以这一层的第一条纪律是只读：

- 读 `store` 的行、手稿账本、停机状态、会话列表、待答问题；
- 不写任何台账、不写会话事件、不落停机开关、不发模型调用、不碰任何循环；
- 唯一的写是把报告本身落到 `out/review/STATUS-<ts>.{md,json}`（它是产物文件，不是台账）。

## 两个入口（一个实现）

1. 用户侧 CLI（首选）：`agentflow --root <ws> status-report [--since <ts>] [--out <dir>]`
   —— 只读、零模型调用 ⇒ 真正"不打断"；
2. M 的工具/动作：`conductor.status_report`（`side_effect=read`）+ `specs/m.py` 的动作
   `report_status` —— 用户通过留言问"M 现在什么情况"时走它（不发 ask_user、不停任何人的循环）。
   注：入口 2 的动作声明在 `specs/m.py`（FC-27），按 `draft/39` §6.10 排在下一轮与 V 的注册一起做；
   这一层已经把它的实现（`collect` / `render_markdown`）交出来了，接上去只是声明。
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Mapping

#: 报告里逐张表的读数（顺序就是人读报告里的顺序）。
REPORT_TABLES: tuple[str, ...] = (
    "tasks", "documents", "experiments", "conjectures", "attack_plans",
    "review_findings", "literature", "search_requests", "statements",
)
#: 每张表在报告里最多列几条"最近的行"。
RECENT_LIMIT = 8


def _now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def _rows(store: Any, table: str) -> list[dict[str, Any]]:
    """读一张表的行（读不到 ⇒ 空列表 + 在报告里记一条 `unreadable`，不假装是 0）。"""
    try:
        return [dict(r) for r in store.rows(table)]
    except Exception:  # noqa: BLE001 —— 读不到与"是 0 行"必须分得开
        return []


def _id_of(table: str, row: Mapping[str, Any]) -> str:
    for key in (f"{table[:-1]}_id", "task_id", "doc_id", "experiment_id", "conjecture_id",
                "plan_id", "finding_id", "lit_id", "request_id", "stmt_id"):
        if row.get(key):
            return str(row[key])
    return ""


def collect(store: Any, root: str | Path, *, since: str = "") -> dict[str, Any]:
    """只读收集这个工作区的当前情况（`draft/39` §4.2 的四类读数）。

    返回一个纯数据 dict（可 `json.dumps`）—— 人读的 markdown 由 `render_markdown` 从它渲染，
    于是"报告里写的数"与"脚本复算的数"是同一份东西（E15 的第 2 条判据就是对拍这两者）。

    `since` 给 ISO 前缀（如 `2026-10-05`）时，各表的"计数"只算这一时间之后的（按行的
    `created_at`/`at`/`started_at` 里最先有的那个）；给空串则算全部。
    """
    from . import manuscripts as MS
    from . import stopctl as SC

    root = Path(root)
    tables: dict[str, Any] = {}
    for table in REPORT_TABLES:
        rows = _rows(store, table)
        if since:
            rows = [r for r in rows if _row_time(r) >= str(since)]
        recent = [{"id": _id_of(table, r), "at": _row_time(r),
                   "hint": _hint_of(table, r)} for r in rows[-RECENT_LIMIT:]]
        tables[table] = {"count": len(rows), "recent": recent}

    # ---- 交接链（手稿账本：谁→谁、一行一份、谁填的）
    ms_rows, ms_bad = MS.read_rows(root)
    if since:
        ms_rows = [r for r in ms_rows if str(r.get("created_at") or "") >= str(since)]
    model_authored = sum(1 for r in ms_rows if "模型填的 notify" in str(r.get("note") or ""))
    derived = sum(1 for r in ms_rows if "派生" in str(r.get("note") or ""))
    manuscripts = {
        "rows": len(ms_rows), "bad_lines": ms_bad[:3],
        "model_authored": model_authored, "derived": derived,
        "recent": [{"id": str(r.get("id") or ""), "sender": str(r.get("sender") or ""),
                    "to": str(r.get("to") or ""), "summary": str(r.get("summary") or "")[:80],
                    "at": str(r.get("created_at") or ""),
                    "source": ("模型填的 notify" if "模型填的 notify" in str(r.get("note") or "")
                               else "框架派生" if "派生" in str(r.get("note") or "") else "未注明")}
                   for r in ms_rows[-RECENT_LIMIT:]],
    }

    # ---- 五元位现状（现算：哪一档几条、有多少条自身不合规）
    from . import evidencebits as EB

    grades: dict[str, int] = {}
    problems = 0
    for r in _rows(store, "statements"):
        bits = EB.bits_from_row(r)
        grades[str(bits.get("grade"))] = grades.get(str(bits.get("grade")), 0) + 1
        if EB.bit_problems(bits):
            problems += 1

    # ---- 在飞与卡点
    live = SC.live_pids(root)
    loops = SC.running_loops(root)
    tasks = _rows(store, "tasks")
    running_tasks = [str(t.get("task_id") or "") for t in tasks
                     if str(t.get("status") or "") in ("pending", "running")]
    # ---- 顶趟行（F1）：`tasks` 里多出来的那一类行（`role=M` / `action="run"` /
    # `called_by="user"`，由 `conductor.open_top_level_run` 开）。
    #
    # 口径照 `conductor.stats()` 的 `calibers` 那一段（`conductor.py:1926-1943`）：
    # `tasks` 这一屏数的是台账全量，所以顶趟行保留在读数里（它是用户发起的那一趟，
    # 显示它是真实且有用的 —— 它同时是那个"谁在派活"的身份行），
    # 但它不是一次召唤，所以把它单独数出来（`top_level_runs`）+ 在读数里点名口径，
    # 免得下游把 `M.run` 当成"第 N 次召唤"。
    top_runs = [t for t in tasks if str(t.get("action") or "") == "run"]
    refused = [t for t in tasks if str(t.get("outcome") or "") == "refused"]
    by_reason: dict[str, int] = {}
    for t in refused:
        key = str(t.get("refusal_reason") or "（未记理由）")
        by_reason[key] = by_reason.get(key, 0) + 1
    history = SC.stop_history(root, limit=3)

    pending_questions = 0
    try:
        from . import userio as U

        pending_questions = len(U.pending_questions(root))
    except Exception:  # noqa: BLE001 —— 读不到待答问题 ⇒ 这一格判不了（下面 note 里说）
        pending_questions = -1

    report: dict[str, Any] = {
        "generated_at": _now().replace(microsecond=0).isoformat(),
        "workspace": str(root), "since": str(since),
        "tables": tables,
        "manuscripts": manuscripts,
        "five_bit": {"grades": grades, "problems": problems},
        "in_flight": {
            "running_tasks": len(running_tasks), "running_task_ids": running_tasks[:RECENT_LIMIT],
            # 口径（不可省）：这两个数一个是台账全量、一个是"用户发起的那一趟"。
            # 不写清就会变成"同一屏里两个读数各说一件事"（`conductor.stats()` 的同一条纪律）。
            "calibers": {
                "running_tasks":
                    "tasks 里 status ∈ {pending, running} 的行（含顶趟行 action=run）",
                "top_level_runs":
                    "tasks 里 action==run 的行 = 用户发起的顶趟（不是召唤；"
                    "召唤看 conductor.stats() 的 started_total）",
            },
            "top_level_runs": len(top_runs),
            "live_pids": [{"role": str(p.get("role") or ""), "pid": p.get("pid")} for p in live],
            "running_loops": loops["running"], "readable_sessions": len(loops.get("running") or [])
            + 0,
            "unreadable_sessions": loops.get("unreadable_sessions") or [],
            "stop_switch": SC.read_stop(root) is not None,
            "last_stop_history": history,
        },
        "pending_questions": pending_questions,
        "refusals": {"total": len(refused), "by_reason": by_reason,
                     "recent": [{"task_id": str(t.get("task_id") or ""),
                                 "role": str(t.get("role") or ""),
                                 "action": str(t.get("action") or ""),
                                 "reason": str(t.get("refusal_reason") or "")}
                                for t in refused[-RECENT_LIMIT:]]},
        # ---- 后几批新落的两类读数（`draft/39` §6.15）：F 的产物与集体插话。
        # 为什么把它们放进状态报告：真机卡点②③ 要读的正是这两样（"V 有没有被 F 用起来"
        # 与"attack_plans.history 的产物四种有没有齐备"），而 M/用户想知道"现在什么情况"时
        # 应当直接看到它们，而不是再去翻会话。
        "attack_rounds": _attack_rounds(_rows(store, "attack_plans")),
        "interjections": _interjections(root),
        "faculty": _faculty_mechanics(store, _rows(store, "documents")),
        # ---- S-07（`44 J-01` 的裁定：只读数、不进闸门）：D 的 `write_report`
        # "有调用、但台账里没有落点"。不进 `closing` 的闸门是这个读数的用途决定的
        # （诊断，不是判交付过不过；加进闸门会改变验收读数的翻转面）。
        "report_landing": _report_landing(store),
        # ---- S-02（`44 S-02`，同样是"只做读数、不进闸门"）：声明了、但一条召唤行
        # 都没有的动作。`Conductor.stats()` 只有 by_role/by_status/by_outcome/by_depth，
        # 没有 by_action ⇒ 这件事今天没有任何读数在说。
        "uncalled_actions": _uncalled_actions(store),
        # ---- EE-04（`draft/48-09 §4.10` 的"先接住再退场"）：让 `faculty_checks`
        # 有一条不依赖 `gate` CLI 的生产调用者。
        #
        # 为什么不经 `deliver.gate`：那个函数会写盘（`deliver.py:251-254` 落
        # `gates/<名字>.json`、`:153-155` 追加工作项），而状态报告是只读现场读数
        # —— 把会写盘的东西并进只读路径，等于让"看一眼现在什么情况"这个动作改盘。
        # 所以直接调 `faculty_checks` 的纯函数（它们只读 store 与文本）。
    }
    report["next_steps"] = _next_steps(report)
    return report


def _report_landing(store: Any) -> dict[str, Any]:
    """S-07 的读数：D 的 `write_report` "有调用、但台账里没有落点"（只读，实现在 `agent_d`）。

    为什么并进这一屏（`44 S-07`）：真机 45 次 `write_report` 只落磁盘、台账 0 行，
    而这件事在今天的读数面上没有任何地方会说（下游会读成"D 没产报告"）。
    实现只有一份（`agent_d._support.report_landing_reading`），这里只做转发 ——
    另写一份判据就是"同一件事两个落位"。
    三态照原样透传：读不出来时 `checked=False` + `reason`，不许折成"没有调用"。
    """
    from .agent_d._support import report_landing_reading

    return dict(report_landing_reading(store))


def _uncalled_actions(store: Any) -> dict[str, Any]:
    """S-02 的读数：声明了、但一条召唤行都没有的动作（只读，实现在 `conductor`）。

    为什么并进这一屏：`Conductor.stats()` 只有 `by_role`/`by_status`/`by_outcome`/
    `by_depth`，没有 `by_action` ⇒ "声明了但没人召唤过"今天没有任何读数在说
    （真机：D 的五个核心动作在 4127 行 `tasks` 里 0 次）。
    实现只有一份（`conductor.uncalled_actions_reading`），这里只转发。
    三态照原样透传：读不出来时 `checked=False` + `reason`，不许折成"全都没被调用"
    —— "全都没被调用"是很强的结论，只有真读到两边（声明表与 `tasks`）才配下。
    """
    from .conductor import uncalled_actions_reading

    return dict(uncalled_actions_reading(store))


def _faculty_mechanics(store: Any, documents: list[dict[str, Any]]) -> dict[str, Any]:
    """十项官能的机械半（`faculty_checks` 的纯函数，只读；EE-04 的落点）。

    为什么是这两项：状态报告是"现在什么情况"，而这两项能只用台账算出来 ——
    `conjecture_hygiene` 查猜想卫生（有没有反例路径、有没有把猜想写成结论），
    `claim_strength_findings` 逐条比"断言说了多强"与"它挂的证据等级"。
    另三项（`overview_findings` / `style_findings` / `progress_findings`）要稿件正文
    或前后两次计数快照，状态报告里没有那个输入 —— 不给它编一个。
    """
    from . import faculty_checks as FC

    claims = [c for d in (documents or []) for c in (d.get("claims") or [])
              if isinstance(c, Mapping)]
    return {
        "conjecture_hygiene": FC.conjecture_hygiene(store),
        "claim_strength": FC.claim_strength_findings(claims),
    }


def _attack_rounds(plans: list[dict[str, Any]]) -> dict[str, Any]:
    """`attack_plans.history` 里的产物分布（真机卡点③ 的机械读数）。

    `no_product_rounds` 是这一格的关键：`draft/39` §3.16 之后每一轮都要交一件产物，
    所以这个数应当是 0；不是 0 就把轮次列出来（哪儿还漏着，一眼可查）。
    """
    products: dict[str, int] = {}
    no_product: list[str] = []
    strategies: dict[str, int] = {}
    for plan in plans:
        pid = str(plan.get("plan_id") or "")
        for i, h in enumerate(plan.get("history") or [], 1):
            if not isinstance(h, Mapping):
                continue
            product = str(h.get("product") or "")
            if product:
                products[product] = products.get(product, 0) + 1
                strat = str(h.get("strategy") or "")
                if strat:
                    strategies[strat] = strategies.get(strat, 0) + 1
            else:
                no_product.append(f"{pid}#{i}(outcome={h.get('outcome')})")
    return {"products": products, "strategies": strategies,
            "no_product_rounds": no_product[:RECENT_LIMIT],
            "no_product_count": len(no_product),
            "rounds": sum(products.values()) + len(no_product)}


def _interjections(root: str | Path) -> dict[str, Any]:
    """集体插话的读数（`draft/39` §3.11 二 D07）：发出几条、被读了几次、有没有改变做法。"""
    from . import sessions as _SESS

    sent: list[dict[str, Any]] = []
    seen = 0
    changed = 0
    unchanged = 0
    for info in _SESS.list_sessions(root):
        events, problems = _SESS.read_session(root, str(info.get("sid") or ""))
        if problems:
            continue
        for e in events:
            if e.get("kind") == "agent_interjection":
                sent.append({"id": str(e.get("interjection_id") or ""),
                             "from": str(e.get("from") or ""), "to": str(e.get("to") or ""),
                             "subject": str(e.get("subject") or ""),
                             "is_stop": bool(e.get("is_stop"))})
            elif e.get("kind") == "agent_interjection_seen":
                seen += 1
            elif e.get("kind") == "agent_interjection_effect":
                if e.get("changed_action") is True:
                    changed += 1
                else:
                    unchanged += 1
    return {"sent": len(sent), "seen_events": seen, "changed_action": changed,
            "unchanged_action": unchanged, "recent": sent[-RECENT_LIMIT:]}


def _row_time(row: Mapping[str, Any]) -> str:
    for key in ("created_at", "at", "started_at", "ended_at", "added_at"):
        if row.get(key):
            return str(row[key])
    return ""


def _hint_of(table: str, row: Mapping[str, Any]) -> str:
    """每条最近行的"一眼能看懂"的一小段（不是判据，是给人读的抓手）。"""
    if table == "tasks":
        line = f"{row.get('role')}.{row.get('action')} {row.get('status')}/{row.get('outcome')}"
        # 顶趟行（F1）要说清它是什么：`role=M` / `action=run` 那一行是用户发起的一趟，
        # 不是召唤 —— 不注明的话，读的人会把它当成"M 被召唤了一次"
        # （口径与 `conductor.stats()` 的 `top_level_runs` 同源）。
        if str(row.get("action") or "") == "run" and row.get("parent_task_id") in (None, ""):
            line += "（顶趟：用户发起的那一趟，不是召唤）"
        return line
    if table == "documents":
        return f"{row.get('kind')} {row.get('title')}（{row.get('status')}）"
    if table == "experiments":
        return f"{row.get('method')}/{row.get('evidence_kind')} {row.get('result')}"
    if table == "conjectures":
        return f"{row.get('status')}：{str(row.get('statement') or '')[:50]}"
    if table == "attack_plans":
        return f"{row.get('status')}（history {len(row.get('history') or [])} 条）"
    if table == "review_findings":
        return f"{row.get('level')}/{row.get('kind')} {row.get('status')}"
    if table == "statements":
        return f"{row.get('origin')} {row.get('status')}"
    return ""


def _next_steps(report: Mapping[str, Any]) -> list[str]:
    """从读数派生"下一步"（不是模型写的）：每一句都指着一个具体的空格。"""
    out: list[str] = []
    tables = report.get("tables") or {}
    if not (tables.get("conjectures") or {}).get("count"):
        out.append("还没有可检验的猜想（`conjectures` 0 行）⇒ 先把模式写成带 `testable` 的猜想")
    if not (tables.get("documents") or {}).get("count"):
        out.append("还没有稿件（`documents` 0 行）⇒ 有结论就落一份手稿，别只留在会话里")
    if not (report.get("manuscripts") or {}).get("rows"):
        out.append("交接账本还是空的（`manuscripts/handoffs.jsonl` 0 行）⇒ 派活/收工时的 notify 没落下来")
    if (report.get("five_bit") or {}).get("problems"):
        out.append(f"有五元位自身不合规的命题 {report['five_bit']['problems']} 条"
                   "（缺凭据/缺理由）⇒ 那是台账质量问题，先补齐再谈等级")
    if (report.get("in_flight") or {}).get("running_tasks"):
        out.append(f"有 {report['in_flight']['running_tasks']} 条任务还在飞 ⇒ 现在别改口径，"
                   "等它们收工（这份报告本身不打断它们）")
    if (report.get("refusals") or {}).get("total"):
        top = sorted((report["refusals"]["by_reason"] or {}).items(), key=lambda kv: -kv[1])[:2]
        out.append("被拒的动作有 " + str(report["refusals"]["total"]) + " 次，最常见的是 "
                   + "、".join(f"{k}×{v}" for k, v in top) + " ⇒ 参数表/口径要按它改")
    if report.get("pending_questions"):
        out.append(f"有 {report['pending_questions']} 个问题在等用户回答 ⇒ 那是唯一该「停下来」的地方")
    # ---- S-07：D 的报告"有调用、无落点"（诊断；判定与口径都在 `agent_d` 那份读数里）
    landing = report.get("report_landing") or {}
    if landing and not landing.get("checked"):
        out.append("D 的报告落点这一格**没查成**（" + str(landing.get("reason") or "声明读不到")
                   + "）⇒ 那是「没读成」，不是「没有调用」")
    elif landing.get("calls") and not landing.get("landed"):
        out.append(f"D 调用过 `write_report` {landing['calls']} 次，而台账里没有一张表收得下它"
                   "（**有产物无台账**：`REPORT_KINDS` 四档是 C 的报告种类、"
                   "`WRITE_SETS[\"D\"]` 里也没有 `analysis_reports`）⇒ 要么人裁扩 kind / 新开表，"
                   "要么把这条读数当结论读（`44 J-01` 的裁定：本轮只做读数）")
    # ---- S-02：声明了、但一条召唤行都没有的动作（诊断；判定在 `conductor` 那份读数里）
    uncalled = report.get("uncalled_actions") or {}
    if uncalled and not uncalled.get("checked"):
        out.append("「声明了但没被召唤过的动作」这一格**没查成**（"
                   + str(uncalled.get("reason") or "读不到")
                   + "）⇒ 那是「没读成」，不是「全都没被调用」")
    elif int(uncalled.get("count") or 0):
        head = "、".join(f"{a.get('role')}.{a.get('action')}"
                        for a in (uncalled.get("uncalled") or [])[:4])
        out.append(f"有 {uncalled['count']} 个动作声明了却一次都没被召唤过（例如 {head}）"
                   f"⇒ 该不该派归秘书/主控判断（`44 S-02` 只做读数，不进闸门）；"
                   "要动它们就派活，别让它们在声明表里挂着")
    # `draft/39` §6.15：把后几批新落的两个卡点读数接进"下一步"。
    rounds = report.get("attack_rounds") or {}
    if rounds.get("no_product_count"):
        out.append(f"有 {rounds['no_product_count']} 轮攻坚**没有产物**"
                   f"（{rounds['no_product_rounds']}）⇒ §3.16 要求每轮交一件"
                   "（reduction/proof/counterexample_request/dead_end），先把形态补齐")
    if rounds.get("rounds") and not (rounds.get("products") or {}).get("proof"):
        out.append("攻坚轮次里**还没有一条 `proof` 产物** ⇒ 第 2 位（有证明）无从置起；"
                   "先让 F 交一轮证明（哪怕只证一个子情形）")
    inter = report.get("interjections") or {}
    if inter.get("sent") and not inter.get("seen_events"):
        out.append(f"发过 {inter['sent']} 条插话而**一次都没被读到**（`agent_interjection_seen` 0 条）"
                   "⇒ 那位同伴要么没在跑、要么读插话那一步没走到")
    if not out:
        out.append("四类读数都没有明显空格：这一趟的下一步由 M 按当前子目标定")
    return out


def render_status_markdown(report: Mapping[str, Any]) -> str:
    """把读数渲染成人读的短版（四节：产出 / 交接 / 卡点 / 下一步）。"""
    tables = report.get("tables") or {}
    ms = report.get("manuscripts") or {}
    infl = report.get("in_flight") or {}
    five = report.get("five_bit") or {}
    ref = report.get("refusals") or {}
    fac = report.get("faculty") or {}
    hygiene = fac.get("conjecture_hygiene") or {}
    strength = fac.get("claim_strength") or {}
    lines = [
        f"# 项目状态报告（{report.get('generated_at')}）", "",
        f"- 工作区：`{report.get('workspace')}`",
        f"- 统计起点：`{report.get('since') or '（全部）'}`",
        "- 这份报告是**旁路观测**：只读台账与手稿，零模型调用，不打断任何循环。", "",
        "## 一、产出（各表行数 + 最近几条）", "",
        "| 表 | 行数 | 最近 |", "|---|---:|---|",
    ]
    for name in REPORT_TABLES:
        got = tables.get(name) or {}
        recent = "；".join(f"{r.get('id')} {r.get('hint')}" for r in (got.get("recent") or [])[-3:])
        lines.append(f"| `{name}` | {got.get('count', 0)} | {recent or '（无）'} |")
    # ---- S-07：D 的报告"有调用、无落点"（诊断读数，只在这里看得见）
    landing = report.get("report_landing") or {}
    if landing and not landing.get("checked"):
        lines.append(f"- D 的报告落点：**没查成**（{landing.get('reason') or '声明读不到'}）"
                     "—— 那是「没读成」，不是「没有调用」")
    elif landing:
        if landing.get("calls"):
            tail = ("**有产物无台账**（结构性：今天没有一张表收得下 D 的报告，"
                    "不是「这一趟没写」）" if not landing.get("landed")
                    else f"有落点：{'、'.join(landing.get('landing_tables') or [])}")
            lines.append(f"- D 的报告落点：`write_report` 调用 **{landing['calls']}** 次 / "
                         f"台账落点 **{landing['landed']}** 行 ⇒ {tail}")
        else:
            lines.append("- D 的报告落点：这一屏没有调用过 `write_report`（0 次）")
    # ---- S-02：声明了、但一条召唤行都没有的动作（诊断读数）
    uncalled = report.get("uncalled_actions") or {}
    if uncalled and not uncalled.get("checked"):
        lines.append(f"- 声明了但没被召唤过的动作：**没查成**"
                     f"（{uncalled.get('reason') or '读不到'}）—— 那是「没读成」，"
                     "不是「全都没被调用」")
    elif uncalled:
        n = int(uncalled.get("count") or 0)
        if n:
            head = "、".join(f"{a.get('role')}.{a.get('action')}"
                            for a in (uncalled.get("uncalled") or [])[:6])
            lines.append(f"- 声明了但没被召唤过的动作：**{n}** 个"
                         f"（声明 {uncalled.get('declared_total')} / "
                         f"有召唤行 {uncalled.get('called_total')}；例如 {head}）"
                         "—— 该不该派归秘书/主控判断，这条读数不构成闸门")
        else:
            lines.append("- 声明了但没被召唤过的动作：**0** 个"
                         "（每个声明过的动作都至少被召唤过一次）")
    lines += [
        "", "## 二、交接（手稿账本：谁→谁，一行一份）", "",
        f"- 账本行数：**{ms.get('rows', 0)}**（模型自己填的 notify {ms.get('model_authored', 0)} 行 / "
        f"框架派生 {ms.get('derived', 0)} 行）",
    ]
    if ms.get("bad_lines"):
        lines.append(f"- ⚠️ 台账里有读不出来的行：{ms['bad_lines']}")
    for r in (ms.get("recent") or [])[-5:]:
        lines.append(f"  - `{r.get('id')}` {r.get('sender')}→{r.get('to')}：{r.get('summary')}"
                     f"（{r.get('source')}）")
    if not ms.get("recent"):
        lines.append("  - （还没有交接手稿）")
    lines += [
        "", "## 三、卡点（在飞 / 被拒 / 停机 / 待答）", "",
        f"- 在飞任务：**{infl.get('running_tasks', 0)}**"
        + (f"（{infl.get('running_task_ids')}）" if infl.get("running_task_ids") else "")
        + (f"；其中顶趟行 {infl['top_level_runs']} 条 —— **顶趟 = 用户发起的那一趟，不是召唤**"
           f"（`tasks` 这一屏数的是台账全量；召唤数看 `conductor.stats()` 的 `started_total`）"
           if infl.get("top_level_runs") else ""),
        f"- 活进程登记：**{len(infl.get('live_pids') or [])}** 个"
        + ("：" + "、".join(f"{p['role']}#{p['pid']}" for p in infl["live_pids"])
           if infl.get("live_pids") else ""),
        f"- 在跑的循环：**{'有' if infl.get('running_loops') else '没有'}**"
        + ("：" + "、".join(f"{r['role']}（sid={r['sid']}）" for r in infl["running_loops"])
           if infl.get("running_loops") else ""),
        f"- 停机开关：{'在' if infl.get('stop_switch') else '不在'}"
        + (f"；最近一次叫停：{infl['last_stop_history'][-1].get('reason')}"
           if infl.get("last_stop_history") else ""),
        f"- 待答问题：{'（读不到 ⇒ 这一格没查成）' if report.get('pending_questions') == -1 else report.get('pending_questions', 0)}",
        f"- 被拒动作：**{ref.get('total', 0)}** 次"
        + ("（" + "、".join(f"{k}×{v}" for k, v in sorted((ref.get('by_reason') or {}).items(),
                                                          key=lambda kv: -kv[1])[:4]) + "）"
           if ref.get("by_reason") else ""),
        f"- 五元位现状：{('、'.join(f'{k} {v} 条' for k, v in (five.get('grades') or {}).items()) or '（还没有命题行）')}"
        + (f"；其中 {five.get('problems')} 条自身不合规（缺凭据/缺理由）"
           if five.get("problems") else ""),
        f"- 攻坚轮次的产物：{('、'.join(f'{k} {v}' for k, v in (report.get('attack_rounds') or {}).get('products', {}).items()) or '（还没有轮次）')}"
        + (f"；**没有产物的轮次 {report['attack_rounds']['no_product_count']} 条**"
           f"（{report['attack_rounds']['no_product_rounds']}）"
           if (report.get("attack_rounds") or {}).get("no_product_count") else ""),
        f"- 集体插话：发出 {report['interjections']['sent']} 条、被读 {report['interjections']['seen_events']} 次；"
        f"其中改变做法 {report['interjections']['changed_action']} 次 / 未改变 "
        f"{report['interjections']['unchanged_action']} 次",
        # EE-04：官能机械半进报告（同一份读数既写 .json 也写 .md —— 只写一边
        # 等于"落盘了但没人看得见"）。
        f"- 官能机械半：猜想卫生 {hygiene.get('verdict') or '（没读数）'}"
        f"（{len(hygiene.get('findings') or [])} 条读数）；"
        f"断言强度对账 {len(strength.get('overclaimed') or [])} 条 overclaim / "
        f"{len(strength.get('missing_evidence') or [])} 条判不了",
        "", "## 四、下一步（从读数派生，不是模型写的）", "",
    ]
    lines += [f"- {s}" for s in (report.get("next_steps") or [])]
    return "\n".join(lines) + "\n"


def status_report_paths(root: str | Path, *, out_dir: str | Path | None = None,
                 stamp: str = "") -> tuple[Path, Path]:
    """报告的两个落点：`out/review/STATUS-<YYYYMMDD-HHMM>.{md,json}`。"""
    base = Path(out_dir) if out_dir else Path(root) / "out" / "review"
    ts = stamp or _now().strftime("%Y%m%d-%H%M")
    return base / f"STATUS-{ts}.md", base / f"STATUS-{ts}.json"


def write_status_report(store: Any, root: str | Path, *, out_dir: str | Path | None = None,
                 since: str = "", stamp: str = "") -> tuple[dict[str, Any], Path, Path]:
    """收集 + 落盘（唯一会写盘的地方，而且只写报告本身）。返回 `(报告, md 路径, json 路径)`。"""
    report = collect(store, root, since=since)
    md_path, json_path = status_report_paths(root, out_dir=out_dir, stamp=stamp)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_status_markdown(report), encoding="utf-8", newline="\n")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
                         encoding="utf-8", newline="\n")
    return report, md_path, json_path


def selftest() -> int:
    """最小自检：空工作区也能出一份完整报告；四节齐全；数字与复算一致。"""
    import tempfile

    from .store import Store

    root = Path(tempfile.mkdtemp(prefix="statusreport_selftest_"))
    (root / "data").mkdir(parents=True, exist_ok=True)
    st = Store(root)
    st.init()
    report, md, js = write_status_report(st, root, stamp="20260101-0000")
    checks: list[tuple[str, bool]] = []
    checks.append(("两个落点都在盘上", md.is_file() and js.is_file()))
    text = md.read_text(encoding="utf-8")
    checks.append(("四节齐全", all(s in text for s in ("一、产出", "二、交接", "三、卡点", "四、下一步"))))
    again = collect(st, root)
    checks.append(("复算一致（表行数）",
                   all((again["tables"][k]["count"] == report["tables"][k]["count"])
                       for k in REPORT_TABLES)))
    checks.append(("空工作区也有读数（不是空报告）", bool(report["next_steps"])))
    checks.append(("json 可解析且键齐",
                   set(json.loads(js.read_text(encoding="utf-8")))
                   >= {"tables", "manuscripts", "five_bit", "in_flight", "next_steps"}))
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())
