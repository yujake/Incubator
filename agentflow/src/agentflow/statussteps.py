# -*- coding: utf-8 -*-
"""状态报告的"下一步"派生：`_next_steps` 的真身（2026-11-22 从 `statusreport.py` 搬出）。

## 这一层管什么

`collect` 收集的是读数，这一层把读数折成"下一步该干什么"：每一句都指着一个具体的
空格（哪张表 0 行、哪一格没查成、哪一轮没交产物），而且只用报告里已经有的数派出来 ——
模型不参与，句子也不许出现报告里没有的事实。

它是一个纯函数：只吃那份 `report` dict，不读 store、不写盘、不碰模块里的任何别的状态。
正因为这样，它才能整块搬走而不改变行为 —— 搬的是位置，不是口径。

## 为什么搬出来（2026-11-22）

`statusreport.py` 这一批被顶在 800 行软基线上（缺省报告落点改认
`review_tools.DEFAULT_REPORT_SUBDIR` 之后连一行余量都没有了）。业主口径是"不许抬体量
软基线"，于是处置是搬、不是改（位置变了，口径一个字没变）：`_next_steps` 逐字搬到这里，
而 `statusreport.py` 在原位 `from .statussteps import _next_steps` 按名字回引
（`statusreport._next_steps` 照旧可用，判据与 `render_status_markdown` 都按那个名字取）。
搬前/搬后两次 `dir()` 快照与关键读数 sha256 相同（探针见 `temp/basefix2/`：
`_equiv_live.py` 先把拆前那一版逐字节反推出来、再在同一进程里与拆后对拍）。
"""
from __future__ import annotations

from typing import Any, Mapping


def _next_steps(report: Mapping[str, Any]) -> list[str]:
    """从读数派生"下一步"（不是模型写的）：每一句都指着一个具体的空格。"""
    out: list[str] = []
    tables = report.get("tables") or {}
    bad_tables = sorted(k for k, v in tables.items() if (v or {}).get("unreadable"))
    if bad_tables:
        out.append("有这几张表读不出来：" + "、".join(bad_tables)
                   + " ⇒ 报告里它们的 0 是「没查成」，不是「没有」")
    if not (tables.get("conjectures") or {}).get("count"):
        out.append("还没有可检验的猜想（`conjectures` 0 行）⇒ 先把模式写成带 `testable` 的猜想")
    if not (tables.get("documents") or {}).get("count"):
        out.append("还没有稿件（`documents` 0 行）⇒ 有结论就落一份手稿，别只留在会话里")
    if not (report.get("manuscripts") or {}).get("rows"):
        out.append("交接账本还是空的（`work/handoffs.jsonl` 0 行）⇒ 派活/收工时的 notify 没落下来")
    if (report.get("five_bit") or {}).get("problems"):
        out.append(f"有五元位自身不合规的命题 {report['five_bit']['problems']} 条"
                   "（缺凭据/缺理由）⇒ 那是台账质量问题，先补齐再谈等级")
    # ---- D1：说通过而无区间的那几行（与收工门那一格同一份读数）
    qe = report.get("quote_evidence") or {}
    if qe and not qe.get("checked"):
        out.append("引文证据那一格**没查成**（" + str(qe.get("reason") or "读不到")
                   + "）⇒ 那是「没读成」，不是「都核过了」")
    elif qe.get("dirty"):
        ids = "、".join(str(x.get("id") or "") for x in (qe.get("dirty") or [])[:4])
        out.append(f"有 {len(qe['dirty'])} 行写着「逐字回验通过」而盘上没有 quote_span"
                   f"（{ids}）⇒ 收工门会因此拦门：要么重核一次并把区间写实"
                   "（走 `B.register_statement` 且给 `source_lit_id`），"
                   "要么把那一行的 quote_verified 改成 None 并写清为什么还没核")
    if (report.get("in_flight") or {}).get("running_tasks"):
        out.append(f"有 {report['in_flight']['running_tasks']} 条任务还在飞 ⇒ 现在别改口径，"
                   "等它们收工（这份报告本身不打断它们）")
    if (report.get("action_refusals") or {}).get("total"):
        top = sorted((report["action_refusals"]["by_reason"] or {}).items(),
                     key=lambda kv: -kv[1])[:2]
        out.append("被拒的动作有 " + str(report["action_refusals"]["total"]) + " 次，最常见的是 "
                   + "、".join(f"{k}×{v}" for k, v in top) + " ⇒ 参数表/口径要按它改")
    if report.get("pending_questions"):
        out.append(f"有 {report['pending_questions']} 个问题在等用户回答 ⇒ 那是唯一该「停下来」的地方")
    # ---- S-07：D 的报告"有调用、无落点"（诊断；判定与口径都在 `agent_d` 那份读数里）
    landing = report.get("report_landing") or {}
    if landing and not landing.get("checked"):
        out.append("D 的报告落点这一格**没查成**（" + str(landing.get("reason") or "声明读不到")
                   + "）⇒ 那是「没读成」，不是「没有调用」")
    elif landing.get("calls") and not landing.get("landed"):
        out.append(f"D 调用过 `write_report` {landing['calls']} 次，而 `documents` 里一行"
                   "（`kind=research`）都没有 ⇒ **有产物无台账**：盘上的报告下游按台账读不到"
                   "（要么写侧没落行、要么词表那一档被摘了；见 `agent_d._support` 的 S-07 读数）")
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
