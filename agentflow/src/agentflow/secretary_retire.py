# -*- coding: utf-8 -*-
"""秘书的销号（静默闸 + 级联 + 台账落终态，从 secretary.py 的 U09 逐字搬出）。

我保证哪条不变式：只销静默的对象；销一项等于销它绑过的全部号（台账里不留半个名字）。

## 为什么它能单独成文件（依赖方向）

`secretary_retire` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_retire` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import clock
from . import manuscripts as MS
from . import schema as S
from . import sysguard as SG

from .secretary_addressing import (  # noqa: F401 — 这些名字由 secretary_addressing 定义
    _clip_text,
)

from .secretary_ledger import (  # noqa: F401 — 这些名字由 secretary_ledger 定义
    _roster_section,
    append_jsonl,
    retired_path,
    roster_index_path,
    roster_path,
)

from .secretary_time import (  # noqa: F401 — 这些名字由 secretary_time 定义
    _now_iso,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    LIVE_TASK_STATUSES,
)


def retire_reason(branch: str, by_task_id: str) -> str:
    """销号行的 `reason` 那一格在调用方没给时的补值（唯一一处算它）。

    为什么补而不是拒：销号本身是"腾出名额"的动作，拒掉会把一次已经判定的退场
    留在半路上（名字还在册），代价比"理由写得朴素"大。补出来的那一句必须可复核：
    它点名就绪读数里的那一支（`branch`）与发起的号（`by_task_id`），于是读的人
    知道这句不是模型编的，而是写点按此刻盘面折出来的。

    这一句只用于落盘那一格；它不改变任何判据，也不改 `settle_retired_row` 的口径
    （那里本来就有自己的兜底括号）。
    """
    why = str(branch or "").strip()
    text = f"销号退场：{why}" if why else "销号退场：父决定销号"
    by = str(by_task_id or "").strip()
    return text + (f"（发起 {by}）" if by else "")


class RetireMixin:
    """销号（静默闸 + 级联）（从 secretary.py 搬出的混入类）。"""

    def latest_report_of(self, *, task_id: str, role: str = "") -> dict[str, Any]:
        """某个实例最近的工作报告（退役第①支要端给父的东西）。

        口径：优先 `handoffs` 里 `task_id == 该实例` 的那些行；一条都没有时退回
        "发信人是该角色"的最新一行（历史 595 行没有 `task_id`，`draft/94` §3 ——
        这条退路要写明，否则那段历史读起来像"它从没报过"）。
        体积：默认只给摘要 + 编号 + 正文前 300 字（全文由父自己 `manuscripts.read`）。
        """
        try:
            rows, bad = MS.read_rows(self.root)
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "reason": f"手稿读不成（{type(exc).__name__}: {exc}）"}
        mine = [r for r in rows if str(r.get("task_id") or "") == str(task_id)]
        source = "task_id"
        if not mine and role:
            mine = [r for r in rows if str(r.get("sender") or "") == str(role)]
            source = "sender"
        if not mine:
            return {"checked": True, "handoff_id": "", "summary": "",
                    "head": "", "at": "", "source": "", "bad_rows": len(bad),
                    "reason": "这个实例名下没有找到报告行"}
        mine.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("id") or "")))
        last = mine[-1]
        return {"checked": True, "handoff_id": str(last.get("id") or ""),
                "summary": str(last.get("summary") or ""),
                "head": _clip_text(str(last.get("body") or ""), 300),
                "at": str(last.get("created_at") or ""), "source": source,
                "bad_rows": len(bad), "reason": ""}

    def active_children_of(self, *, task_id: str) -> dict[str, Any]:
        """退役第②支：它自己名下的活跃子代理（代理轴，不是父的）。"""
        cond = self._conductor()
        if cond is None:
            return {"checked": False, "rows": [], "reason": "没有 store ⇒ 读不到台账"}
        try:
            return cond.active_children(task_id)
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "rows": [],
                    "reason": f"{type(exc).__name__}: {exc}"}

    def settle_retired_row(self, task_id: str, *, name: str = "",
                           reason: str = "") -> dict[str, Any]:
        """销号落定台账那一行：还在飞的（`status ∈ {pending, running}`）⇒ 写终态 `cancelled`。

        ## 为什么销号必须动台账
        扇出名额的分子是"父名下 `status ∈ {pending, running}` 的直接子"
        （`Conductor._in_flight_children_of`，单时刻口径）。销号若只写名册 / 对照表 /
        销号名单三份 jsonl —— 台账那一行一个字节都不动，于是
        「销号一个静默子代理腾出名额」这句话在盘上是空话：占位数不变，下一次 `summon`
        照旧 `fanout_exceeded`。这一笔就是那句承诺的落点：销号 = 让它从"占位"里退出。

        ## 为什么只有"还在飞的"才写
        绝大多数静默子代理早就落了终态（`done` / `failed` / `cancelled` 带 `ended_at`），
        它们本来就不占名额 —— 那些行一个字节都不动（谁什么时候交了差是历史，不许改写）。
        真正需要落终态的是"父已记为静默、而台账行还没收口"的那一档（交差之后收尾没走完 /
        可抢占派活的后台线程被掐断 / 进程退出），它占着名额却永远不会自己返回。

        ## 三态与代价
        读不成 / 写不成 ⇒ `checked=False` + `reason`，调用方（`retire`）据此拒绝整笔销号
        （先写这一笔、再写名册：反过来的顺序会让"名册已销、台账没落终态"这种半笔无路可退）。

        与"它自己刚好收了尾"的赛跑：闸门看过之后、这一笔落下之前它自己落了终态 ⇒ 这里
        读到的是终态、一行不动；反过来（这一笔先落）由 `Task` 的"终态先到先得"兜住 ——
        两笔都是终态，读者看到的是先落的那一笔，谁也不改写历史。

        返回 `{"checked","was_occupying","status_before","status_after","task_id","reason"}`。
        """
        tid = str(task_id or "")
        out: dict[str, Any] = {"checked": False, "was_occupying": False,
                               "status_before": "", "status_after": "", "task_id": tid,
                               "reason": ""}
        if not tid:
            out["reason"] = "没有编号 ⇒ 不知道落定哪一行"
            return out
        if self.store is None:
            out["reason"] = "没有 store ⇒ 读不到台账（没查成，不是『它不占名额』）"
            return out
        try:
            rows = [r for r in self.store.rows("tasks")
                    if str(r.get("task_id") or "") == tid]
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            out["reason"] = f"台账读不成（{type(exc).__name__}: {exc}）"
            return out
        row = dict(rows[0]) if rows else {}
        status = str(row.get("status") or "")
        out["status_before"] = status
        if not row:
            out["reason"] = f"台账里没有 {tid} 这一行（查过了、确实没有）"
            return out
        if status not in LIVE_TASK_STATUSES:
            # 已经收口：不占名额，也不许改写历史。
            out.update({"checked": True, "status_after": status})
            return out
        why = ("销号退场：" + (str(reason or "").strip() or "父决定销号"))
        row["status"] = "cancelled"
        row["outcome"] = "cancelled"
        row["ended_at"] = S.now_iso()
        row["detail"] = ((str(row.get("detail") or "").strip() + "；") if str(row.get("detail") or "").strip() else "") \
            + f"销号退场（{name or tid}）：这一行由销号落定终态，腾出扇出名额（{why[:120]}）"
        try:
            S.Task(**{k: v for k, v in row.items()
                      if k in S.Task.__dataclass_fields__}).validate()
            with self.store.tx("tasks", actor=f"secretary-{self.role}",
                               note=f"retire:settle:{tid}") as tx:
                tx.upsert("tasks", row, note=f"retire:settle:{tid}")
        except Exception as exc:  # noqa: BLE001 —— 写不成 ⇒ 名额没腾出来，必须如实说
            out["reason"] = f"台账那一行没落成终态（{type(exc).__name__}: {exc}）"
            return out
        out.update({"checked": True, "was_occupying": True, "status_after": "cancelled"})
        return out

    def retire(self, *, owner: str, name: str, by_task_id: str = "",
               reason: str = "") -> dict[str, Any]:
        """退役（三分支）。返回：

        `{"ok","action":"retired"|"reported"|"refused","report":{…},"why":[…], "reading":{…}}`

        - 目标不是静默（在飞 / 待机 / 读不到）⇒ `refused`（销号只可针对静默子代理），
          带 `refusal_code`（`target_not_silent`）、`target_state` 与逐条 `blocking`；
          `report` 仍把"它最近报了什么 / 它名下的子代理在干什么"端给父 —— 拒了不等于什么都不给；
        - `active` ⇒ `reported`：把最近的工作报告端给父，不退役（静默闸之外的第二道保险）；
        - `waiting_with_children` ⇒ `reported`：把那些子代理在它名册里的任务简介端给父；
        - `waiting_no_children` ⇒ `retired`：写退役事件 + 销号名单 + 对照表标退役 +
          `conductor.note_edge_release`（父侧那一笔幂等落痕）；
        - 未登记 / 读不成 / 已销号 ⇒ `refused`（没读成 ≠ 可以退役）。

        `cascade` 在每一档都有：`{"count","ids","levels","kept"}` —— `count` 是这一笔实际
        销掉了几个（`retired` 档恒为 1），`ids` / `levels` 是编号与相对层深（目标恒为 0），
        `kept` 是"没销、还占着名册的那几个"，逐条 `{"id","name","why"}`。理由：回执要说清
        "我没销它是为了什么"，`why` 给人读、`kept` 给下一步判断用。

        ## 程序闸

        销号前先读一次"这一支还有没有程序在跑"（`conductor.programs_in_subtree`，与
        `conductor.retire_child` 读同一份），有就受控拒绝、一个字节都不落盘。它排在静默闸
        之前：静默闸的三样（无工作 / 无计时器 / 无活跃子）都读不出"一台程序还在跑"——
        无主的程序计时器（`task_id` 空）在三态里一句话都没有。拒信措辞只有
        `conductor.programs_refusal` 一处：点名 program / pid / 已跑秒数，并只指一条正路。

        ## 孤儿闸

        目标自己静默、但名下还有没销号的静默子代理 ⇒ 受控拒绝。为什么必须有：销号只发给
        直接子代理，一支的子代理只有它这一个父能销；父先销了、名字永久不复用（B1）、
        不会再有下一轮 ⇒ 那些子代理再没有任何代理有权销它们，`Conductor.retire_integrity`
        永远不 complete、`final` 被结构完整性闸永久拒。正路是 `conductor.retire_child`
        （从最深的开始把这一支一起销）。这一闸排在静默闸之后：父非静默时由静默闸先说话；
        父静默而子只是"没销"时才轮到它。它不误伤级联 —— 级联先深后浅。

        ## 静默的定义（与 `conductor.agent_state` 同一份）

        无工作 ∧ 无任何计时器 ∧ 无活跃子代理。销号不可逆（名字永久不复用），所以一律
        fail-closed：读不到是不是静默就不销。三档拒信各说各的下一步 —— 在飞就让它收工；
        待机就让那些计时器的事先发生、或显式让它停（停止 ≠ 销号）；读不到就重读一次。

        ## `reason`

        父发起销号时那一句理由，逐字落进三份台账（名册行 / 对照表行 / 销号名单行，
        `reason` 键）。缺省空串 ⇒ 对既有调用方的落盘行只多一个键、不改任何既有键。
        """
        cond = self._conductor()
        if cond is None:
            return {"ok": False, "action": "refused", "report": {},
                    "why": ["没有 store ⇒ 读不到台账（没读成，不是'不在跑'）"]}
        # ---- 收工兜底：销号之前先把"台账有、名册没有"的那几条补上。
        #
        # 分工：治本在登记侧 —— `Conductor._register_roster` 一件活登记一次；撞名字是
        # `name_taken` 受控拒绝、交父决定，框架不替它换名。兜底在这里 —— 收工/销号是
        # "这一支要收口了"还缺行，那些子代理连名字都没有，父根本无法按名册名去销它。
        # 补一行只写名册与对照表，不动台账、不动进程。
        #
        # 两件事不是同一件事：派活时不自作主张、收口时必须给得出名字。而"必须给得出"
        # 的对象是"真跑过"的号 —— 没跑过的号（被派活闸拒掉的）永远没有名字；写口拒过
        # 但真跑了的号，会在这里拿到一个从未发过的新名字（`roster_repair` 补，add 行带
        # `named_after_run` / `requested_name` / `refusal_code` 三格留痕，被拒的那个名字不复用）。
        # 下面把"谁补成了什么"原样写进回执 —— 否则读回执的人会以为名字丢了。
        repaired = 0
        repair_named: list[dict[str, Any]] = []
        try:
            repaired, _repair_why, _repair_skipped = self.roster_repair(
                owner=str(owner), named=repair_named)
        except Exception as exc:  # noqa: BLE001 —— 兜底失败不许带走这次销号
            repaired, _repair_why, _repair_skipped = 0, f"{type(exc).__name__}: {exc}", []
        named_notes: list[str] = []
        for x in repair_named:
            if str(x.get("requested_name") or ""):
                named_notes.append(
                    f"补名：{x.get('task_id')} 当初点名的 {x.get('requested_name')} 被拒"
                    f"（{x.get('refusal_code')}），它现在叫 {x.get('name')}"
                    "（跑过之后补的新名字；被拒的那个不复用）")
            else:
                named_notes.append(f"补名：{x.get('task_id')} 补成 {x.get('name')}")
        tid, problem = self.resolve_roster_item(owner=owner, name=str(name))
        if problem:
            if self._is_retired(owner, str(name)):
                return {"ok": False, "action": "refused", "report": {},
                        "why": [f"{name} 已经销号过（业主 B1：名字永久不复用）"]}
            return {"ok": False, "action": "refused", "report": {}, "why": [problem]}
        if self._is_retired(owner, str(name)):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"{name} 已经销号过（业主 B1）"]}
        # ---- 这一项绑过的全部号（复用是合法的一等功能，2026-11-17 缺陷 ③）-------
        #
        # 一个子代理可以接 N 件活 ⇒ 一个名字绑着 N 个号。销号销的是"这一项"，
        # 而 `retire_integrity` 数的是台账行：只落定名册项自己那个号，其余几次调用
        # 会永远"还在册"（真机 lp-ball-3：D1 的复用行 t-000110 就是这么留下的）。
        # 判据与两条 fail-closed 在 `_bound_agent_ids` 里（读不成 / 撞到别人名下的号 ⇒ 整笔不销）。
        bound, bound_problem = self._bound_agent_ids(
            owner=str(owner), name=str(name), item_id=tid)
        if bound_problem:
            return {"ok": False, "action": "refused", "report": {},
                    "why": [bound_problem], "task_ids": list(bound)}
        # 其余绑过的号也必须是静默的（静默前置对每一个会被落定终态的号都成立）：
        # 还在跑的那一个号不许因为"它兄弟已经交差"被顺手销掉。
        for one in bound[1:]:
            row_one = cond._task(one) or {}
            if not row_one:
                continue
            if str(row_one.get("status") or "") in LIVE_TASK_STATUSES:
                return {
                    "ok": False, "action": "refused", "report": {},
                    "why": [(f"{name} 绑过的另一个号 {one} 还在跑"
                             f"（status={row_one.get('status') or 'unknown'}）⇒ 整笔不销："
                             "销号 = 这一项退场，而它名下的号必须都先停下来")],
                    "refusal_code": "target_not_silent",
                    "task_ids": list(bound),
                }
        # ---- 程序闸（G2，业主 2026-10-26 第 ① 条：「注销前检测的能力」）
        #
        # 这一闸挡的是"名字销了、程序还在跑"：昨晚盘上有十五个野 python 进程，谁起的、
        # 谁该停都读不出来，而销号之后连"这台程序是谁的"这个线索也没有了。
        #
        # 为什么"还在跑"这一档排在静默闸之前：静默闸读的是"无工作 ∧ 无计时器 ∧ 无活跃子"，
        # 而一台程序可以在三样都读成"没有"的情况下继续跑 —— 无主的程序计时器（`task_id`
        # 空：框架自己的八个 `program_span` 调用点一个都不传台账号）在时钟读数里是一条不挂
        # 名字的流水，在三态里一句话都没有；而"账上说收口了、进程还在"那一档连计时器都
        # 不是。所以"它名下还有程序在跑"这句话必须由读得到程序的那一格先说：静默闸的拒信
        # 会把一台程序读成"一条挂着到点时刻的计时器"（到点时刻读不到），父照着那句话
        # 处置不了它。
        #
        # 为什么"读不成"那一档反过来排在静默闸之后：时钟簿记坏掉时，静默闸与这一闸都读
        # 不成，而"读不到它是不是静默"是更根本的那一句（它连三态都定不了）。让静默闸按
        # 既有口径先说话，这一闸在后面兜底：静默闸放行了而程序那一格没查成 ⇒ 仍然不销
        # （fail-closed，把"没查成"折成"没有在跑的程序"正是这一闸最该挡的那一次折叠）。
        from .conductor import programs_refusal as _programs_refusal

        try:
            progs = cond.programs_in_subtree(tid)
        except Exception as exc:  # noqa: BLE001 —— 读侧自己炸了也是"没查成"
            progs = {"checked": False, "running_count": 0, "running": [],
                     "reason": f"{type(exc).__name__}: {exc}"}
        if progs.get("checked") and int(progs.get("running_count") or 0) > 0:
            ref = _programs_refusal(progs, lead=f"{name}（{tid}）")
            return {"ok": False, "action": "refused", "report": {},
                    "why": [ref["why"]], "reading": dict(progs),
                    "blocking": list(ref["blocking"]),
                    "missing": list(ref["missing"]),
                    # 空串：拦它的不是静默闸（三态那一格），而是"账上还有进程在跑"。
                    "refusal_code": ref["code"],
                    "programs": list(ref["programs"])}
        # ---- 静默闸（业主 2026-10-26：「销号可以也只可针对静默子代理」）
        #
        # 落点与理由：销号是不可逆的那一类动作（名字永久不复用，业主 B1），而"它还会不会
        # 醒过来"只有时钟读得出来。不静默的三档各自给人一条不同的下一步，所以拒信要分开说。
        from .conductor import (AGENT_STATE_FLYING, AGENT_STATE_STANDBY,
                                AGENT_STATE_UNKNOWN, RETIRE_REFUSAL_TARGET_NOT_SILENT,
                                retire_refusal)

        def _refused_not_silent(got: Mapping[str, Any]) -> dict[str, Any]:
            """目标不静默的拒信：措辞只有 `conductor.retire_refusal` 一处。"""
            ref = retire_refusal(got, tid=tid, name=str(name))
            report: dict[str, Any] = {}
            state = str(got.get("state") or "")
            if state == AGENT_STATE_FLYING:
                report = self.latest_report_of(task_id=tid, role=str(got.get("role") or ""))
            elif state == AGENT_STATE_STANDBY and not got.get("waiters"):
                kids = self.active_children_of(task_id=tid)
                briefs: list[dict[str, Any]] = []
                if kids.get("checked"):
                    child_rows, _bad = self.roster_rows(tid)
                    for k in kids.get("rows", []):
                        kid_name, _why = self.name_of(owner=tid,
                                                      task_id=str(k.get("task_id") or ""))
                        brief = next((str(x.get("brief") or "") for x in child_rows
                                      if str(x.get("name") or "") == kid_name), "")
                        briefs.append({"name": kid_name or "（未登记）",
                                       "role": str(k.get("role") or ""),
                                       "brief": brief, "state": str(k.get("state") or "")})
                if briefs:
                    report = {"children": briefs}
            return {"ok": False, "action": "refused", "report": report,
                    "why": [ref["why"]], "reading": dict(got),
                    "refusal_code": ref["code"],
                    "target_state": state,
                    "target_state_label": str(got.get("state_label") or ""),
                    "blocking": list(ref["blocking"])}

        try:
            gate = cond.retire_state_of(tid)
        except Exception as exc:  # noqa: BLE001 —— 读侧自己炸了也是"没读成"
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"三态读数没读成（{type(exc).__name__}: {exc}）⇒ "
                            "读不到它是不是静默，不许销（fail-closed）"],
                    "refusal_code": RETIRE_REFUSAL_TARGET_NOT_SILENT,
                    "target_state": AGENT_STATE_UNKNOWN, "blocking": []}
        if not gate.get("silent"):
            return _refused_not_silent(gate)
        # ---- 程序闸的兜底那一档：静默闸放行了，而程序那一格没查成 ⇒ 仍然不销。
        # 排在这里的理由见上面那一段（时钟坏了时"读不到它是不是静默"是更根本的那一句）。
        if not progs.get("checked"):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [(f"{name}（{tid}）这一支的程序读数没查成"
                             f"（{progs.get('reason') or '没查成'}）⇒ 不知道它名下还有没有"
                             "程序在跑，不许销（fail-closed）；这一格不是『一个都没有』")],
                    "reading": dict(progs)}
        try:
            ready = cond.retire_ready(owner)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"就绪读数没读成（{type(exc).__name__}: {exc}）"]}
        if not ready.get("checked"):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"就绪读数没读成（{ready.get('reason')}）"]}
        row = next((r for r in ready.get("ready", []) if str(r.get("task_id")) == tid), None)
        if row is None:
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"{name}（{tid}）不在就绪清单里（已经退过，或它不在这个父名下）"]}
        branch = str(row.get("branch") or "")
        reading = dict(row.get("reading") or {})
        if branch == "active":
            report = self.latest_report_of(task_id=tid, role=str(row.get("role") or ""))
            return {"ok": False, "action": "reported", "report": report,
                    "why": [f"{name} 还在跑 ⇒ 先看它最近报了什么，不退役"],
                    "reading": reading}
        if branch == "waiting_with_children":
            kids = self.active_children_of(task_id=tid)
            if not kids.get("checked"):
                return {"ok": False, "action": "refused", "report": {},
                        "why": [f"{name} 名下的活跃子代理没读成（{kids.get('reason')}）"]}
            briefs = []
            for k in kids.get("rows", []):
                kid_name, _why = self.name_of(owner=tid, task_id=str(k.get("task_id") or ""))
                child_rows, _bad = self.roster_rows(tid)
                brief = next((str(x.get("brief") or "") for x in child_rows
                              if str(x.get("name") or "") == kid_name), "")
                briefs.append({"name": kid_name or "（未登记）",
                               "role": str(k.get("role") or ""),
                               "brief": brief, "state": str(k.get("state") or "")})
            return {"ok": False, "action": "reported", "report": {"children": briefs},
                    "why": [f"{name} 名下还有活跃子代理 ⇒ 不退役（它还在干什么活见 report）"],
                    "reading": reading}
        # ---- 孤儿闸（「最终 final 时应该是 M 下整棵树都已销号」）
        #
        # 这一闸只挡一件事：先销父、把静默的子留到以后。它必须存在，因为那种销法
        # 会永久孤儿化——销号只发给"直接子代理"（`_do_retire` 与 `conductor.retire_child`
        # 都只认自己名册里的那一层），一支的子代理只有它这一个父能销；父一销号，名字
        # 永久不复用、不会再有下一轮，那些子代理就再也没有任何代理有权限销它们。
        # 于是 `Conductor.retire_integrity` 永远不 complete、`final` 被结构完整性闸永久拒
        # —— 这就是"深树永远清不完"的真身。
        #
        # 为什么放在静默闸之后：静默闸说的是"它自己能不能销"（在飞/待机/读不到三档
        # 各有各的下一步，且各带 `refusal_code`），而这一闸说的是"销了它会不会留下孤儿"。
        # 父非静默时（名下有活跃子）根本走不到这里，所以两闸不会抢话；反过来，父静默、
        # 子也静默（子只是"没销"而不是"还在跑"）时，静默闸放行，这一闸接住。
        #
        # 为什么级联那条路不会被它误伤：级联是"先深后浅"，轮到 A1 时 B1 的名册项已经
        # 标了 retired（`retire` 先写台账、再写名册，两处都落完才返回），所以这里读到的
        # `retired` 为真、`rows` 为空、放行。判据见
        # `tests/test_cascade_retire_closes_the_tree.py::test_a_the_cascade_path_does_not_trip_the_orphan_gate`。
        left = self._children_left_behind(tid)
        if not left.get("checked"):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [(f"{name}（{tid}）名下还有没有未销的子代理这一格读不成"
                             f"（{left.get('reason')}）⇒ 不知道销它会不会留下孤儿，"
                             "不许销（fail-closed）")],
                    "reading": reading,
                    "cascade": {"count": 0, "ids": [], "levels": [], "kept": []}}
        if left.get("rows"):
            rows_left = list(left["rows"])
            named = "、".join(f"{r['name']}（{r['id'] or '编号未读到'}）"
                              for r in rows_left[:8])
            more = f" 等 {len(rows_left)} 个" if len(rows_left) > 8 else ""
            return {"ok": False, "action": "refused", "report": {},
                    "why": [(f"还没销 {name}：它名下还有 {len(rows_left)} 个名册项没有销号"
                             f"（{named}{more}）。为什么不许先销父、把子留到以后：销号只发给"
                             "直接子代理，而这一支的子代理只有它这一个父能销 —— 父一旦销号，"
                             "名字永久不复用（业主 B1）、不会再有下一轮，那些子代理就再也"
                             "没有任何代理有权限销它们（别的代理都不是它们的父）⇒ 整棵树"
                             "永远清不完、`final` 被结构完整性闸永久拒。正路只有一条：用 "
                             f"`conductor.retire_child(child_name={name})` —— 那一件会从最深"
                             "的开始把这一支一起销号（先叶子后父），销完这一支就没有"
                             "「留下没销的子」了")],
                    "reading": reading,
                    "cascade": {"count": 0, "ids": [], "levels": [],
                                "kept": [{"id": str(r["id"] or r["name"]),
                                          "name": r["name"],
                                          "why": "还在它名下的名册上、没销号（父一销号，"
                                                 "就再没有任何代理有权限销它）"}
                                         for r in rows_left]}}
        # ---- 先撤兜底计时器（静默可销号，但销号必须把那条表
        #      撤掉并落抑制标记，否则"号已销、计时器又长回来"是不可逆的鬼读数）。
        #
        # 为什么放在台账那一笔之前：两个方向都会留半笔，但只有一个是可重试的 ——
        #   clock-first 失败 ⇒ "叫不醒了、名字还没销"（可重试）；
        #   settle-first 失败 ⇒ "已销号但仍会醒"（不可逆）。
        killed = clock.kill_lifeline(getattr(self.store, "root", "") or "",
                                     task_id=str(tid), reason=str(reason or ""))
        if not killed.get("checked"):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [(f"{name}（{tid}）的兜底计时器没撤成"
                             f"（{killed.get('reason') or '没查成'}）⇒ 一个字节都没落盘，"
                             "重试即可（反方向会是『已销号却还会被叫醒』，不可逆）")],
                    "lifeline": killed}
        # ---- 销号行那一格 `reason`（写点补值）
        #
        # `out/roster/<父>-retired.jsonl` 的 `reason` 是框架自己写的一格：模型没有机会
        # 发现它空着（SIGNMAL 形态）。真机普查（2026-11-21）在 15 个工作区里读到 36 条
        # `reason=""` 的销号行 —— 那些行当时完全合法地落盘了，因为写点接受空串。
        # 处置：调用方给了就用；没给就按此刻已经读到的就绪分支在同一处补一句可复核的，
        # 并把这一次补值记成读数（`retired_reason_derived`）。补值必须发生在写点，
        # 读侧不许猜一个理由。
        reason_text = str(reason or "").strip()
        if not reason_text:
            reason_text = retire_reason(branch, by_task_id)
            SG.record_reading(self.root, SG.derived(
                "secretary_retire.retire", code="retired_reason_derived",
                where=f"out/roster/{owner}-retired.jsonl（{name} / {tid}）",
                detail=(f"调用方没给 reason ⇒ 按就绪读数那一支补："
                        f"{branch or '（空）'}"),
                how_to_fix=("销号行必须带理由：调用方给 `reason`；没给时由写点按就绪分支"
                            "补一句 —— 空理由的销号行在盘点时无法复核")))
        # ---- 落定台账那一行
        #
        # 顺序是判据本身：先落台账、再写名册。反过来先写名册时，台账那一笔要是炸了，
        # 盘上就是"名字已销、那一行还占着扇出名额"—— 重试会被"已经销号过"挡住，
        # 名额永远回不来。这个方向失败时两处都还没动（可重试），而它成功时
        # "销号即腾出名额"在盘上已经成立。
        settled = self.settle_retired_row(tid, name=str(name), reason=reason_text)
        if not settled.get("checked"):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [(f"{name}（{tid}）的台账那一行没落定终态"
                             f"（{settled.get('reason') or '没查成'}）⇒ 名额没腾出来，"
                             "整笔销号不作数（先写台账、再写名册，两处一起才算销号）")],
                    "reading": reading, "slot_freed": False, "settle": dict(settled)}
        ok, why = cond.note_edge_release(owner, child_task_id=tid, attempt=1)
        if not ok and "已经记过" not in why:
            return {"ok": False, "action": "refused", "report": {}, "why": [why],
                    "reading": reading}
        # ---- 同一个名字绑过的其余号：边也要认掉（2026-11-17 缺陷 ③）------------
        #
        # `Conductor.retire_integrity` 读的是父行 `inputs` 里的 `edge-released:` 落痕
        # ⇒ 只认名册项自己那一笔，早先那几次调用会永远"还在册"（真机 lp-ball-3 的
        # `t-000008` 就是这样被 M 看见的）。这些号已在上面核过：都是本父名下的代理行、
        # 且都不在跑（所以只认边，不改它们的历史状态行）。
        released_extra: list[str] = []
        for one in bound[1:]:
            ok_one, why_one = cond.note_edge_release(owner, child_task_id=one, attempt=1)
            if not ok_one and "已经记过" not in why_one:
                return {"ok": False, "action": "refused", "report": {},
                        "why": [(f"{name}（{one}）的边没认掉（{why_one}）⇒ 整笔销号不作数："
                                 f"已经认下的是 {[tid, *released_extra]}，名册三份还没写")],
                        "reading": reading, "task_ids": list(bound)}
            released_extra.append(one)
        at = _now_iso()
        # ⑤（业主 2026-11-02）：销号要标死这个名字绑过的全部号，不只当前号。
        # "读 bind 历史 + 写销号三笔"必须在同一个 per-owner 临界区：临界区外新来的
        # bind 会落在"读历史"与"写销号"之间，那个号就漏掉了（漏号 = 永久可唤醒，
        # 不可逆）。锁序不变：`settle` 与 `note_edge_release` 都在这一句之前做完。
        slot = ""
        surface_note = ""
        with _roster_section(self.root, owner):
            retired_ids = self._bound_task_ids(owner, name=str(name))
            if str(tid) not in retired_ids:
                retired_ids.append(str(tid))
            wrote_roster, why_r = append_jsonl(roster_path(self.root, owner),
                                               {"kind": "retire", "owner": owner, "name": str(name),
                                                "task_id": tid, "task_ids": retired_ids,
                                                "branch": branch, "by": str(by_task_id),
                                                "reason": reason_text,
                                                "reading": reading, "at": at})
            wrote_index, why_i = append_jsonl(roster_index_path(self.root, owner),
                                              {"kind": "retire", "owner": owner, "name": str(name),
                                               "task_id": tid, "task_ids": retired_ids,
                                               "reason": reason_text, "at": at})
            wrote_retired, why_x = True, ""
            for one in retired_ids:
                ok_one, why_one = append_jsonl(retired_path(self.root, owner),
                                               {"owner": owner, "name": str(name),
                                                "task_id": one,
                                                "role": str(row.get("role") or ""), "at": at,
                                                "reason": reason_text,
                                                "branch": branch})
                if not ok_one:
                    wrote_retired, why_x = False, why_one
                    break
            if not (wrote_roster and wrote_index and wrote_retired):
                return {"ok": False, "action": "refused", "report": {},
                        "why": [f"退役没写全（名册={wrote_roster}/{why_r} "
                                f"对照表={wrote_index}/{why_i} "
                                f"销号={wrote_retired}/{why_x}）"],
                        "reading": reading}
            # S1n（业主补充）：退役 ⇒ 面归还"可分配池"（名字不回收、面回收）。
            # 归还前先归档；归档失败 ⇒ 槽位停在"待释放"，读数里如实写（不入池）。
            slot = next((str(r.get("surface") or "") for r in self.roster_rows(owner)[0]
                         if str(r.get("name") or "") == str(name)), "")
            if slot:
                state, why_s = self.surface_release(owner=owner, name=str(name), slot=slot)
                surface_note = (f"面 {slot} 已归还池里" if state == "空闲"
                                else f"面 {slot} 停在待释放（{why_s}）")
        return {"ok": True, "action": "retired", "report": {},
                # 级联读数（Q13）：这一笔实际销掉的只有目标本身 —— 逐层收掉静默子树
                # 那件事在 `conductor.retire_child`（先深后浅、整笔不销或整支销完）。
                # 这一格在这里给，是为了让两个入口的回执同一套键（形那一入口的模型
                # 也读得到"这一笔销了几个 / 还有谁没销"），而不是让"没级联"看起来像
                # "级联了但没读出来"。
                "cascade": {"count": 1, "ids": [tid], "levels": [0], "kept": []},
                "why": [f"{name} 退役：{branch}（子已停 + 它名下无活跃子代理）"]
                       + (["名额已腾出：它那一行还在飞（"
                           f"{settled.get('status_before')}）⇒ 已落终态 "
                           f"{settled.get('status_after')}，下一次 summon 重新算占位"]
                          if settled.get("was_occupying") else [])
                       + ([surface_note] if surface_note else [])
                       + named_notes,
                "surface": slot, "reading": reading,
                "slot_freed": bool(settled.get("was_occupying")),
                "settle": dict(settled),
                # 这一项退场时一起落定/认边的那几个号（名册项自己那个排最前）。
                # 读它的人不用再翻名册历史就知道"这一笔到底让哪几个号不在册了"；
                # 只给一个号正是 2026-11-17 真机那处"名册与台账对不上"的来源。
                "task_ids": list(bound),
                "released_extra": list(released_extra)}
