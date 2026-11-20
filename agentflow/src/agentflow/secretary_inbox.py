# -*- coding: utf-8 -*-
"""秘书的收件箱与闭环提醒（两栏不混，从 secretary.py 的 U10+U28+U29 逐字搬出）。

我保证哪条不变式：在跑的子与待办项两栏不混；提醒不等于被处理 —— 提醒只是「该看一眼」这条读数，不写任何终态。

## 为什么它能单独成文件（依赖方向）

它只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import schema as S
from typing import Mapping

from .secretary_axis import (  # noqa: F401 — 这些名字由 secretary_axis 定义
    is_live_agent,
    row_axis,
)

from .secretary_time import (  # noqa: F401 — 这些名字由 secretary_time 定义
    _now_iso,
    _older_than,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    BRIEF_MAX,
    KIND_NEGOTIATION,
    KIND_NOTICE,
    MAX_NEGOTIATION_ROUNDS,
    MAX_REMINDERS,
    ROW_AXIS_AGENT,
    ROW_AXIS_ITEM_CLOSED,
    ROW_AXIS_ITEM_OPEN,
    ROW_AXIS_ROOT,
    TASK_TEXT_MAX,
    _SENTENCE_END,
)


class InboxMixin:
    """收件箱/闭环 + 两句摘要 + 时间戳（从 secretary.py 搬出的混入类）。"""

    def inbox_todos(self, *, limit: int = 20) -> dict[str, Any]:
        """F-05 的消费端：把"还没有处理 / 还没有反馈"的东西摆出来（只读，两栏）。

        ## 两栏（不许混成一句）
        | 栏 | 装什么 | 截断 |
        |---|---|---|
        | `running_agents` | 此刻真的在跑的子代理（数量 + 全部编号） | 永不截断 |
        | `pending_items` | 等着接手 / 等着收口的待办项（板项 + 队列请求） | 吃 `limit` 与 :data:`MAX_REMINDERS`，截断量写进 `truncated` |

        一行 `tasks` 落在哪一栏由两处判据决定，两处都在本模块：轴归 :func:`row_axis`
        （代理行 / 板项行 / 顶趟行 / 其它），"还算不算在跑"归 :func:`is_live_agent`
        （两问拆开，才分得清"这一行是什么"与"它还活不活"）。只按
        `status ∈ {pending, running}` 与 `action != "run"` 判，板项行（`status` 恒为
        `pending`）就会被写成 `state="running"` —— 板项与在跑的子代理在读数上同形。

        口径：生产端是机器（`search_requests` / `reprocess_requests`
        的 pending + 那些三态行），消费端是各角色自己的秘书 + M 的秘书（全局）；本方法
        只做"摆出来"这一半，判断归 :meth:`remind_closure`。

        ## 三态与"少了几行"
        `checked=False` + `reason` 是"这一格没读成"（没有 store / 表读不出来），与
        `todos=[]`（读成了、确实没有待办）分开报。两个 `excluded_*` 是"确实有行、但两根轴
        都不进"的显式读数（顶趟行 / 已收口的板项行）—— 少了几行要能被读出来，否则
        "少了几行"会被读成"本来就没有"（静默漂移的另一种形态）。

        ## 返回
        `{"checked","reason","running_agents":{"count","ids","rows"},
        "pending_items":{"count","ids","by_kind","rows"},"todos","count","by_kind",
        "excluded_top_level","excluded_item_closed","truncated":{"shown","total","more"}}`。
        两栏的 `count` / `ids` 都是截断前的真数；`todos` 是两栏的合并视图（既有读点兼容），
        每条 `todo` 是 `{"kind","id","who","state","since","axis"}`。
        """
        if self.store is None:
            return {"checked": False, "reason": "没有 store ⇒ 收件箱这一格没读成",
                    "todos": [], "count": 0, "by_kind": {},
                    "running_agents": {"count": 0, "ids": [], "rows": []},
                    "pending_items": {"count": 0, "ids": [], "by_kind": {}, "rows": []},
                    "excluded_top_level": 0, "excluded_item_closed": 0,
                    "truncated": {"shown": 0, "total": 0, "more": 0}}
        agents: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        problems: list[str] = []
        for table, kind in (("search_requests", "search_request"),
                            ("reprocess_requests", "reprocess_request")):
            try:
                rows = self.store.rows(table)
            except Exception as exc:  # noqa: BLE001 - 读不出来如实报，不折成"没有待办"
                problems.append(f"{table}: {type(exc).__name__}: {exc}")
                continue
            for row in rows:
                if row.get("done"):
                    continue
                who = str(row.get("claimed_by") or "")
                items.append({
                    "kind": kind,
                    "id": str(row.get("request_id") or ""),
                    "who": who or S.CONDUCTOR_ROLE,
                    "state": "pending" if who else "unclaimed",
                    "since": str(row.get("timestamp") or ""),
                    "attempts": int(row.get("attempts") or 0),
                    # 队列请求是"排队等接手"，不是在跑的子代理 ⇒ 归待办栏。
                    "axis": ROW_AXIS_ITEM_OPEN,
                })
        excluded_top = 0
        excluded_closed = 0
        try:
            for row in self.store.rows("tasks"):
                axis = row_axis(row)
                # "活着的代理"是另一问（`is_live_agent`，2026-10-26 Q27）：轴只说这一行
                # 是什么，"它还算不算在跑"由那个判据回答 —— 这里不许再写成 `axis == agent`，
                # 否则拆分就退化成两个名字指向同一句话（判据 d 钉的就是这件事）。
                if is_live_agent(row):
                    agents.append({"kind": "task", "id": str(row.get("task_id") or ""),
                                   "who": str(row.get("role") or ""), "state": "running",
                                   "since": str(row.get("started_at") or ""),
                                   "axis": ROW_AXIS_AGENT})
                elif axis == ROW_AXIS_ITEM_OPEN:
                    # 板项还没收口：`state` 用既有的 "pending"（没做完），不许再说 "running"
                    # —— 它没有在跑任何东西，是等着人消它。
                    items.append({"kind": "task", "id": str(row.get("task_id") or ""),
                                  "who": str(row.get("role") or ""), "state": "pending",
                                  "since": str(row.get("started_at") or ""),
                                  "axis": ROW_AXIS_ITEM_OPEN})
                elif axis == ROW_AXIS_ITEM_CLOSED:
                    excluded_closed += 1
                elif axis == ROW_AXIS_ROOT:
                    # 顶趟行是"用户发起的那一趟"本身：既不进待办栏，也不进在跑栏，
                    # 但排除了几行要留在读数里，否则"少了几行"会被读成"本来就没有"。
                    excluded_top += 1
                # 其余（代理行的历史终态行等）：两根轴都不进，也不计数 ——
                # 它们不是"被排除的候选"，是已经收过工的旧行。
        except Exception as exc:  # noqa: BLE001 - 同上
            problems.append(f"tasks: {type(exc).__name__}: {exc}")
        total = len(agents) + len(items)
        todos = (items + agents)[:max(1, int(limit))]
        shown = len(todos)
        by_kind: dict[str, int] = {}
        for t in todos:
            by_kind[t["kind"]] = by_kind.get(t["kind"], 0) + 1
        pending_by_kind: dict[str, int] = {}
        for it in items:
            pending_by_kind[it["kind"]] = pending_by_kind.get(it["kind"], 0) + 1
        return {"checked": not problems, "reason": "；".join(problems),
                "running_agents": {"count": len(agents),
                                   "ids": [str(x["id"]) for x in agents],
                                   "rows": agents},
                "pending_items": {"count": len(items),
                                  "ids": [str(x["id"]) for x in items],
                                  "by_kind": pending_by_kind,
                                  "rows": items},
                "todos": todos, "count": shown, "by_kind": by_kind,
                "excluded_top_level": excluded_top,
                "excluded_item_closed": excluded_closed,
                "truncated": {"shown": shown, "total": total,
                              "more": max(0, total - shown)}}

    #: `pending_inbox` 认的既有标记（不许新造字段/词表/工具）。
    PENDING_KINDS = ("missing_bit", "missing_proof", "unverified_quote")

    def pending_inbox(self, *, scope: str = "self", window_sec: int = 86400,
                      limit: int = 50) -> dict[str, Any]:
        """F-05 的消费端：待办/待核队列（只读扫表；落进决定台账）。

        `draft/53:181` 逐字："消费端 = 各角色秘书（自己的收件箱）+ M 的秘书（全局）" ⇒ 这就是那两个口径：
        | `scope` | 看什么 |
        |---|---|
        | `"self"` | 与本角色有关的那些行（按接手方过滤） |
        | `"global"` | 全部（M 的秘书的全局视图） |
        条目只来自既有标记（不新增表/字段/工具/`status` 取值，主控裁定）：
        1. `missing_bit`：`statements` 行的 `bits` 里那一位没有值（等级由 `evidencebits.derive_grade` 现算，
           所以缺位 = 等级会降，不是"没有等级"）；
        2. `missing_proof`：`origin="own_result"` 而 `proof_text` 空（自产命题没有证明 ⇒ 现算等级是"猜想"）；
        3. `unverified_quote`：`quote_verified is None` 且这一行已经过了窗口（够久了还"没核"= 待核；
           `quote_reason` 是它自己写的"为什么还没核"）。
        每条给出 `(表, 行 id, 缺什么, 谁该接手)`：接手方从声明派生（`capabilities.WRITE_SETS` 里谁能写这张表 /
        `evidencebits.BIT_OWNERS`），不另造一张路由表。三态（R002 口径）：`checked=False` + `reason` = 这一格没
        读成（表读不出来），与"读成了、确实没有待办"（`items=[]`）分开报。有内容时逐条落 :meth:`note_decision`
        —— 只记录，不写任何库表。
        """
        if str(scope) not in ("self", "global"):
            return {"checked": False, "reason": f"scope 只能是 'self' / 'global'，收到 {scope!r}",
                    "items": [], "count": 0, "by_kind": {}}
        if self.store is None:
            return {"checked": False, "reason": "没有 store ⇒ 收件箱这一格没读成",
                    "items": [], "count": 0, "by_kind": {}}
        try:
            from . import evidencebits as EB

            bit_names = tuple(EB.BIT_NAMES)
            bit_owners = dict(EB.BIT_OWNERS or {})
            #: 位的已定取值（`evidencebits.BIT_STATES`）：`na` / `failed` / `verified`
            #: 都是"这一位问过了、有结论" ⇒ 不是待办；只有 `pending`（以及没写）才待办。
            #: 这一格如果不看状态而只看"有没有值"，`na`（不适用）会被误报成待办。
            resolved = tuple(s for s in tuple(EB.BIT_STATES) if s != "pending")
        except Exception:  # noqa: BLE001 - 位表读不到 ⇒ 那一条判据不做（不许猜位的含义）
            bit_names, bit_owners, resolved = (), {}, ()
        try:
            from . import capabilities as C

            writers: dict[str, list[str]] = {}
            for role, tables in dict(C.WRITE_SETS or {}).items():
                for table in tables:
                    writers.setdefault(str(table), []).append(str(role))
        except Exception:  # noqa: BLE001 - 同上：不知道谁接手就如实写空串
            writers = {}

        def _who(table: str, bit: str = "") -> str:
            if bit and bit_owners.get(bit):
                return str(bit_owners[bit])
            cands = sorted(writers.get(table) or [])
            return cands[0] if cands else ""

        try:
            rows = self.store.rows("statements")
        except Exception as exc:  # noqa: BLE001 - 读不出来如实报，不折成"没有待办"
            return {"checked": False,
                    "reason": f"statements 读不出来：{type(exc).__name__}: {exc}",
                    "items": [], "count": 0, "by_kind": {}}
        now = _now_iso()
        items: list[dict[str, Any]] = []
        for row in rows:
            sid = str(row.get("stmt_id") or "")
            bits = row.get("bits") if isinstance(row.get("bits"), Mapping) else {}
            for bit in bit_names:
                state = (bits or {}).get(bit)
                if isinstance(state, Mapping):
                    # 二维位（第 4 位：`{证明号: 状态}`，业主 2026-10-22）。判据是
                    # "任一条路径有结论 ⇒ 这一位问过了 ⇒ 不待办；全都 pending ⇒ 待办"。
                    # 改前这里读 `state.get("state", state.get("value"))` —— 那是给
                    # 另一种形状留的口子，对 `{证明号: 状态}` 只会取到空 ⇒ 二维位一律
                    # 被读成待办（而它可能已经验过了）。
                    settled = [EB._path_state(item) for item in state.values()]
                    settled = [one for one in settled if one != "pending"]
                    state = settled[0] if settled else "pending"
                if str(state or "") in resolved:
                    continue
                who = _who("statements", bit)
                if scope == "self" and who and who != self.role:
                    continue
                items.append({"kind": "missing_bit", "table": "statements", "id": sid,
                              "missing": bit, "who": who, "state": "pending",
                              "since": str(row.get("created_at") or ""),
                              "why": f"证据位 {bit!r} 没有值 ⇒ 等级现算会降（`derive_grade`）"})
            if str(row.get("origin") or "") == "own_result" \
                    and not str(row.get("proof_text") or "").strip():
                who = _who("statements")
                if not (scope == "self" and who and who != self.role):
                    items.append({"kind": "missing_proof", "table": "statements", "id": sid,
                                  "missing": "proof_text", "who": who, "state": "pending",
                                  "since": str(row.get("created_at") or ""),
                                  "why": "自产命题没有证明 ⇒ 现算等级是『猜想』而不是证明级",
                                  "quote_reason": str(row.get("quote_reason") or "")})
            if row.get("quote_verified") is None and _older_than(row.get("created_at"), now,
                                                                int(window_sec)):
                who = _who("statements")
                if not (scope == "self" and who and who != self.role):
                    items.append({"kind": "unverified_quote", "table": "statements", "id": sid,
                                  "missing": "quote_verified", "who": who, "state": "pending",
                                  "since": str(row.get("created_at") or ""),
                                  "why": "过了窗口还没核（`quote_verified is None`）⇒ 待核",
                                  "quote_reason": str(row.get("quote_reason") or "")})
        items = items[:max(1, int(limit))]
        by_kind: dict[str, int] = {}
        for it in items:
            by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
        if items:
            # 职责 3 的闭环提醒就从这里取活：只记录，不改任何库表。
            self.note_decision(
                duty=3, kind=KIND_NOTICE, decision="已提醒",
                reason=f"F-05 待办 {len(items)} 条（scope={scope}，分档 {by_kind}）",
                basis=["statements.bits / proof_text / quote_verified（只读扫表）",
                       "capabilities.WRITE_SETS 派生接手方"],
                target={"scope": str(scope), "items": items[:10]}, fail_open=False)
        return {"checked": True, "scope": str(scope), "items": items,
                "count": len(items), "by_kind": by_kind}

    def remind_closure(self, items: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
        """职责 3：闭环提醒（收件方盯自己的收件箱；经 M）。

        判据只有"有没有处理、有没有反馈"两条事实（`draft/53` §2 的"不许做"：
        不替本体做事、不伪造反馈）。异步、不阻塞本体。

        `items=None` ⇒ 自己读收件箱（:meth:`closure_reading`，F-05 的消费端）：
        待办项一次最多 :data:`MAX_REMINDERS` 条，在跑的子代理全列不截（业主
        2026-10-26 Q18：截断只作用于待办项 —— 在跑的子必须一个不少地点名）。
        给了 `items` ⇒ 按给的那一份判（一律当待办项那一栏，吃 `MAX_REMINDERS`）——
        "谁盯哪个收件箱"由调用方决定（M 的秘书看全局）；要报在跑的子代理就读自己的
        收件箱，别在这里另判一次（判据只有 :func:`row_axis` / :func:`is_live_agent` 一处）。
        """
        if items is None:
            return list(self.closure_reading()["reminded"])
        given = list(items)
        out: list[dict[str, Any]] = []
        for it in given[:MAX_REMINDERS]:
            one = self._reminder_of(it)
            if one is not None:
                out.append(one)
        self._note_closure(out, running_count=0, pending_count=len(given))
        return out

    def closure_reading(self) -> dict[str, Any]:
        """职责 3 的收尾读数（唯一组装点，2026-10-26 Q18）：两栏真数 + 每条提醒。

        返回 `{"checked","reason","count","running_agents","pending_items",
        "reminded","by_state","by_to","truncated"}`：

        - `running_agents` / `pending_items`：两栏截断前的真数与全部编号；
        - `reminded`：这一次真的要点名的那些（两栏合并，每条带 `axis`）—— 待办项吃
          :data:`MAX_REMINDERS`，在跑的子代理全列不截；
        - `by_state` / `by_to`：只统计待办项，而且是全部待办行（不只是点名的那些）——
          "谁没接手 / 谁没有终态"这句话说的是待办项；在跑的子代理是另一栏（那一栏的
          `state` 恒为 `running`），把它们混进同一张分组表，正是改前那句"running 5 条"
          的来源；只数点名的那几条又会让"待办项 10 条 / pending 5 条"这种加不上的数出现；
        - `truncated`：两栏各自的 `{shown, total, more}`（在跑栏的 `more` 恒为 0）。

        三态与改前逐字一致：读不成 ⇒ `checked=False` + 理由，并落一条 `fail_open=True`
        的台账（"没读成"绝不当成"没有未闭环"）。
        """
        got = self.inbox_todos()
        if not got["checked"]:
            # 读不成不是"没有待办"：如实留痕，绝不当成清零。
            self.note_decision(duty=3, kind=KIND_NOTICE, decision="已提醒",
                               reason=f"待办那一格没读成：{got['reason']}",
                               basis=["tasks / search_requests / reprocess_requests"],
                               target={"role": self.role}, fail_open=True,
                               error=str(got["reason"]))
            return {"checked": False, "reason": str(got["reason"]), "count": 0,
                    "running_agents": {"count": 0, "ids": []},
                    "pending_items": {"count": 0, "ids": [], "named": 0},
                    "reminded": [], "by_state": {}, "by_to": {},
                    "truncated": {"running_agents": {"shown": 0, "total": 0, "more": 0},
                                  "pending_items": {"shown": 0, "total": 0, "more": 0}}}
        agent_rows = [dict(x) for x in (got["running_agents"]["rows"] or ())]
        item_rows = [dict(x) for x in (got["pending_items"]["rows"] or ())]
        #: 待办项的截断只在这里发生；在跑栏一个都不减。
        named_items = item_rows[:MAX_REMINDERS]
        # 两样东西分清楚：`shaped` 是两栏全部行的形状（`by_state` / `by_to` 按它数，
        # 于是"待办项 10 条"与"pending 10 条"说的是同一批东西，不会一个 10 一个 5）；
        # `out` 是这一次真的点名的那些（待办项吃 MAX_REMINDERS，在跑的子代理全列）。
        shaped = [x for x in (self._reminder_of(it) for it in (agent_rows + item_rows))
                  if x is not None]
        out = shaped[:len(agent_rows) + len(named_items)]
        by_state: dict[str, int] = {}
        by_to: dict[str, int] = {}
        for one in shaped:
            if one["axis"] != ROW_AXIS_AGENT:
                state = str(one["state"] or "unknown")
                by_state[state] = by_state.get(state, 0) + 1
            to = str(one["to"] or S.CONDUCTOR_ROLE)
            by_to[to] = by_to.get(to, 0) + 1
        self._note_closure(out, running_count=len(agent_rows),
                           pending_count=len(item_rows))
        return {"checked": True, "reason": "", "count": len(out),
                "running_agents": {"count": len(agent_rows),
                                   "ids": [str(x.get("id") or "") for x in agent_rows]},
                "pending_items": {"count": len(item_rows),
                                  "ids": [str(x.get("id") or "") for x in item_rows],
                                  "named": len(named_items)},
                "reminded": out, "by_state": by_state, "by_to": by_to,
                "truncated": {
                    "running_agents": {"shown": len(agent_rows),
                                       "total": len(agent_rows), "more": 0},
                    "pending_items": {"shown": len(named_items),
                                      "total": len(item_rows),
                                      "more": max(0, len(item_rows) - len(named_items))}}}

    def _reminder_of(self, it: Mapping[str, Any]) -> dict[str, Any] | None:
        """一条待办 → 一条提醒（`state` 已经处理过的那几档返回 None）。

        `axis` 由来源决定：收件箱给的行带着 :func:`row_axis` 的结论；调用方直接给的
        那一份没有轴 ⇒ 一律当待办项（不在这一层另判"算不算在跑的子代理"）。
        """
        state = str(it.get("state") or "")
        if state in ("handled", "feedback_seen", "closed"):
            return None
        axis = ROW_AXIS_AGENT if str(it.get("axis") or "") == ROW_AXIS_AGENT \
            else ROW_AXIS_ITEM_OPEN
        if axis == ROW_AXIS_AGENT:
            note = "这一条子代理还没有终态（在跑）⇒ 提醒本体（经 M）"
        else:
            note = "这一条委托没有终态 / 没有反馈 ⇒ 提醒本体（经 M）"
        return {"task_id": str(it.get("task_id") or it.get("id") or ""),
                "state": state or "unknown",
                "kind": str(it.get("kind") or ""),
                "to": str(it.get("by") or it.get("who") or S.CONDUCTOR_ROLE),
                "note": note, "axis": axis}

    def _note_closure(self, out: Sequence[Mapping[str, Any]], *,
                      running_count: int, pending_count: int) -> None:
        """把这一轮闭环提醒落台账（摘要 + 逐条），并记下"该不该叫秘书"的读数。

        摘要保留"留痕 ≠ 被处理"这句（它挡的是"提醒过了就当办过了"），只把条数拆成两栏
        —— 改前那句只有一个数，读者分不出"在跑的子"与"没接手的项"。
        逐条落台账仍是 2026-10-04 主控裁定的第 1 条：只落一行摘要的话，"提醒了谁、
        什么事、什么状态"在纸上查不到，而这一层唯一能自证的就是台账（`draft/55` §5.3）。
        """
        if out:
            self.note_decision(
                duty=3, kind=KIND_NOTICE, decision="已提醒",
                reason=(f"{len(out)} 条未闭环（在跑的子代理 {running_count} 个、"
                        f"待办项 {pending_count} 条；留痕 ≠ 被处理）"),
                basis=["tasks: 代理行无终态 / 板项未收口",
                       "queue: 请求没人接手"],
                target={"role": self.role}, fail_open=False)
            for one in out:
                self.note_decision(
                    duty=3, kind=KIND_NOTICE, decision="已提醒",
                    reason=f"未闭环：{one['state']}（{one['task_id'] or '无 id'}）",
                    basis=["tasks: 代理行无终态 / 板项未收口",
                           "queue: 请求没人接手"],
                    target={"task_id": one["task_id"], "state": one["state"],
                            "kind": one["kind"], "to": one["to"],
                            "axis": one["axis"]},
                    fail_open=False)

    def negotiate(self, *, with_role: str, point: str,
                  rounds: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
        """秘书 ⇄ 秘书协商（`draft/53` §3）：最多 2 轮，之后上报本体、再上报 M。

        本方法只记录协商这件事本身（轮次 + 结论）：真正的来回由两侧真身驱动，
        而"协商结论必须抄送本体"是硬要求（`draft/55` §5.1 第 2 条）——
        否则"任务是变过形的"这件事对本体不可见。
        """
        done = [dict(x) for x in rounds]
        if len(done) >= MAX_NEGOTIATION_ROUNDS:
            outcome, escalate = "上报本体", True
        else:
            outcome, escalate = "待回应", False
        rec = {"round": len(done) + 1, "with": f"secretary/{with_role}",
               "point": str(point), "outcome": outcome, "escalate_to_body": escalate}
        self._negotiations.append(rec)
        self.note_decision(duty=2, kind=KIND_NEGOTIATION, decision="建议重排",
                           reason=f"与 secretary/{with_role} 协商：{point}",
                           basis=["draft/53 §3"], negotiation=done + [rec],
                           target={"with": f"secretary/{with_role}"}, fail_open=False)
        return rec


def _task_text(task: Any) -> str:
    """任务原文的落盘形态：折平空白 + 截断到 `TASK_TEXT_MAX`。

    与 `brief_from_task` 的差别是口径本身：那一格是"给退役时认人的一句摘要"（60 字、
    取第一句），这一格是"父派下来的那件事"（原文，200 字）。两件不许互相顶替 ——
    把摘要当原文会让"等它的目的"读起来像另一件事。
    """
    flat = " ".join(str(task or "").split())
    return flat[:TASK_TEXT_MAX]


def brief_from_task(task: str, *, limit: int = BRIEF_MAX) -> str:
    """从任务原文派生一句名册简介（确定性：不调模型、不花钱、不随机）。

    业主 2026-10-20 裁定逐字：「简介没写，则秘书帮忙写，秘书的重要职责就是辅助通讯」⇒ 名册里那一句不再
    只能由父给：父没给而写了 `task` 时，由秘书代写并留痕（`brief_source="secretary"`），不许静默冒充"父给的"。
    规则（五步，逐条可复算；判据见 `tests/test_secretary_writes_the_brief.py`）：
    1. 折平：`str.split()` —— 换行 / 制表 / 连续空白一律折成一个半角空格、首尾去净（结果不含换行）；
    2. 取第一句：扫到第一个句末标点（`_SENTENCE_END`，含该标点）为止；一个都没有就取全文；
    3. 截断：`limit` 个字符（缺省 `BRIEF_MAX` = 内容闸的同一个数 60）；
    4. 去尾：`strip()` 掉截断留下的尾巴空白；
    5. 空就是空：给的全是空白 ⇒ `""` —— 调用方据此走"没给一句任务简介"那一档，不许编。
    """
    flat = " ".join(str(task or "").split())
    if not flat:
        return ""
    cut = len(flat)
    for i, ch in enumerate(flat):
        if ch in _SENTENCE_END:
            cut = i + 1
            break
    return flat[:min(cut, int(limit))].strip()
