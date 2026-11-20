# -*- coding: utf-8 -*-
"""秘书的名册读侧与视图（事件流折叠与三态读数，从 secretary.py 的 U04 逐字搬出）。

我保证哪条不变式：名册是四态读（在册 / 已退役 / 读不出 / 查不到）；`roster_view` 只读，且一拍一快照。

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

from . import manuscripts as MS
from pathlib import Path
from typing import Mapping

from .secretary_axis import (  # noqa: F401 — 这些名字由 secretary_axis 定义
    _diagnose_line,
    _state_reading,
    _status_enum,
)

from .secretary_ledger import (  # noqa: F401 — 这些名字由 secretary_ledger 定义
    ROSTER_DIR,
    _ROSTER_SIDECAR_SUFFIXES,
    refusals_path,
    retired_path,
    roster_index_path,
    roster_path,
)


class RosterReadMixin:
    """名册读侧 + 视图（从 secretary.py 搬出的混入类）。"""

    def _conductor(self) -> Any:
        """能读台账的那个句柄（`store` 造一个只读用的 `Conductor`）。

        为什么不要求调用方传：秘书的读面本来就是"`store` + 手稿 + registry"
        （`draft/91` §2），名册要读台账里的代理行 ⇒ 用同一把 `store` 现造一个即可。
        造不出来 ⇒ 返回 `None`，调用方按三态如实报（不许当"名下没有子代理"）。

        ## 为什么是同一个实例（2026-10-27）
        改前每调一次都现造一个：造一个 `Conductor` 要连 `TokenMeter` / `LocalBackend` /
        `MemoryBudgetTracker` 一起建，而秘书一拍里要问它十来次。更要紧的是读数身份：
        `roster_view` 把整段包进 `Conductor.reading_snapshot()`（一拍一份台账快照），
        而作用域挂在实例上 —— 若每次调用换一个新实例，作用域就只罩住了"造它的那一行"，
        拍内其余读照样各读一遍（实测：作用域因此从 1 次退化成 18 次）。
        缓存只保存这一个只读句柄；它的 `store` 在 `Secretary` 生命周期内不变，
        所以"哪个工作区"这件事不会变。写入口一个都不在这里走（秘书的写集是
        `STATEMENT_WRITE_TABLES`，见 `self.writes`）。
        """
        if self.store is None:
            return None
        cached = getattr(self, "_cond_cache", None)
        if cached is not None and getattr(cached, "store", None) is self.store:
            return cached
        from .conductor import Conductor, LocalBackend

        try:
            made = Conductor(self.store, policy=None, backend=LocalBackend({}))
        except Exception:  # noqa: BLE001
            return None
        self._cond_cache = made
        return made

    def roster_rows(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """名册的折叠后状态（`(项列表, 坏行)`）：一项 = 名字 / 角色 / 简介 / 状态。

        事件流折叠口径：`add` 建项；`bind` 只推当前调用；`retire` 标退役；
        `keep_alive` 只改那一格读数。只追加、不物理删。
        """
        from . import jsonlfile as JF

        rows, bad = JF.read_jsonl(roster_path(self.root, owner))
        return _fold_roster(rows), bad

    def roster_index(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """对照表（电话簿）的折叠后状态：一项 = 名字 → `first_task_id` / `task_id`（当前）。"""
        from . import jsonlfile as JF

        rows, bad = JF.read_jsonl(roster_index_path(self.root, owner))
        return _fold_index(rows), bad

    def retired_names(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """销号名单：名字一经退役永久不复用。`(行列表, 坏行)`。

        这是 :meth:`retired_ledger` 的薄包装：`bad` 的口径是"某行不是
        合法 JSON / 不是对象"，所以既有读者不受影响。"这一份名单够不够回答否"那一格
        不在这里 —— 它在 `retired_ledger` 的 `checked` / `unattributable` 上。
        """
        got = self.retired_ledger(owner, trusted_shard=True)
        return list(got.get("rows") or []), list(got.get("bad") or [])

    def retired_ledger(self, owner: str, *, trusted_shard: bool) -> dict[str, Any]:
        """销号名单的四态读数 ＋ 逐行读数。

        返回 `{"checked","state","rows","bad","unattributable","unattributable_rows",
        "reason"}`。`state` 是 `jsonlfile.READ_STATES` 之一（`absent` / `empty` / `ok` /
        `unreadable`），`checked` 的含义只有一句：这一份名单的否定结论（「这一号没
        销过」）信不信得过（整片口径）。`unattributable` 是那一档的逐条说明，
        `unattributable_rows` 是同一批行的结构化读数（哪一行、哪个键还用得了），
        给调用方"按号 / 按名逐个排除：这一行可能是谁"用（判据在
        :func:`retired_row_gaps`）。

        为什么要多出 `unattributable` 这一档（没有它，下面这些全会被读成"没销号"）：
        一行是合法 JSON、也是对象，但认不出它是哪一号 / 哪一名 —— 少 `task_id`、
        少 `name`、或两者类型不是非空字符串；
        又或者那一行的 `owner` 与它所在的分片名字对不上（"张冠李戴"那一半）。
        这种行今天既不在 `bad` 里、也不命中任何键 ⇒ 闸门读成"这一份里没有它" ⇒
        已销号的号照样被叫醒。判据只认"非空字符串"两件事，刻意不校验格式
        （格式校验会变成第二份发号口径）。

        `trusted_shard`：这个分片名是怎么来的，必须由调用方显式说。
        - `True`：来自台账那一行自己的 `parent_task_id`（或写侧的"我就是这个父"）⇒
          文件不存在就是"还没人销过号"这条查过的事实（`absent` + `checked=True`）；
        - `False`：来自扫目录 / 调用方猜的 ⇒ 文件不存在证明不了任何事（`checked=False`）。
        把这两档折在一起，就是那条洞（"读不成"被写成"查过了、没有"）。

        「读不全」只从这一次的返回值读：`checked` / `bad` / `unattributable` 三格是
        它唯一的落点，不另存实例字段。另存一份"最后一次"会让"这是哪一次读的"变成一个
        没有答案的问题（同一名秘书上两次读之间，字段会盖掉前一次的坏行）；调用方那一层
        的同一份事实由 `Conductor.last_retired_reading` 承担，那一格有读者。
        """
        from . import jsonlfile as JF

        rows, bad, state = JF.read_jsonl_state(retired_path(self.root, owner))
        bad = list(bad)
        unattributable, unattributable_rows = retired_row_gaps(rows, owner)
        out: dict[str, Any] = {"checked": True, "state": str(state), "rows": list(rows),
                               "bad": bad, "unattributable": unattributable,
                               "unattributable_rows": unattributable_rows, "reason": ""}
        if state == "unreadable":
            # 一个坏字节（R14）/ 一个占成目录的路径（R15）：这一片一条都读不出来。
            # 这一档绝不是"这一片里没有销号"—— 它是"整份失效"，所以 `checked=False`。
            out["checked"] = False
            out["reason"] = ("整份读不出来（这一格不是「没有销号」）："
                             + (bad[0] if bad else "读文本失败"))
        elif state == "absent" and not trusted_shard:
            out["checked"] = False
            out["reason"] = (f"{owner or '?'} 这一份名单不存在，而分片名不可信"
                             "（不是从台账那一行来的）⇒ 「没有这份名单」证明不了任何事")
        else:
            problems = bad + unattributable
            if problems:
                out["checked"] = False
                out["reason"] = f"{len(problems)} 行读不全（{problems[0]}）"
            elif state == "absent":
                out["reason"] = ("还没有人销过号（这一份名单还不存在；分片名来自台账那一行）")
        return out

    def roster_view(self, *, owner: str, scope: str = "self",
                    limit: int = 20) -> dict[str, Any]:
        """名册视图（只读，不许修补 —— I-15）。

        真身在 :meth:`_roster_view_body`：本方法只负责把它包进"一拍一份台账快照"那一个
        只读作用域（2026-10-27）。为什么包在这里而不是让每一处读侧自己缓存：这一份视图
        一拍里要问台账 15 次以上（逐名册项问一次"它名下最新的派活项声明过待命吗"、
        逐层问一次"这一层哪几项可退役"、还有三态快照与 `children_facts`），而它们读的是
        同一份台账的同一个时刻 —— 一拍一份快照是这条口径的唯一落点。
        `roster_view` 从 I-15 起就是"只读、不许修补"，所以作用域内不会有写（真写了会抛）。
        """
        cond = self._conductor()
        if cond is None:
            return self._roster_view_body(owner=owner, scope=scope, limit=limit)
        # 作用域开不起来也是"没读成"，不是让异常穿出去（2026-10-27）：
        # `roster_view` 的三态契约说"读不成 ⇒ checked=False + reason"，
        # 而 `reading_snapshot()` 自己要读一次台账 —— 它抛的话，穿出去就成了崩溃而不是读数
        # （判据 `test_roster_view_reports_and_never_writes` 的 `_Broken` 替身钉的正是这一档）。
        try:
            snapshot = cond.reading_snapshot()
        except Exception as exc:  # noqa: BLE001 - 读不成要有读数
            return self._roster_view_unreadable(f"名册没读成（{type(exc).__name__}: {exc}）", owner, scope, limit)
        try:
            with snapshot:
                return self._roster_view_body(owner=owner, scope=scope, limit=limit)
        except RuntimeError as exc:
            # 作用域内写台账会被 `_refuse_write_in_snapshot` 拒（程序错，不是读不成）⇒ 照旧抛；
            # 其余 RuntimeError（台账读不成）按三态降级。判据两支都要能区分，所以按拒信原话认。
            if "只读快照作用域" in str(exc):
                raise
            return self._roster_view_unreadable(f"名册没读成（{type(exc).__name__}: {exc}）", owner, scope, limit)
        except Exception as exc:  # noqa: BLE001 - 同上，读不成要有读数
            return self._roster_view_unreadable(f"名册没读成（{type(exc).__name__}: {exc}）", owner, scope, limit)

    def _roster_view_unreadable(self, reason: str, owner: str, scope: str,
                                limit: int) -> dict[str, Any]:
        """名册视图"没读成"的那一份读数（三态里的第三态，形状与真身那个分支逐键相同）。

        为什么单列一个方法而不是在 `roster_view` 里内联：那个 `checked=False` 的行有 11 个键
        ，内联一份就多一处会漂的形状；这里与 `_roster_view_body` 里的
        同形返回逐键相同，靠 `test_roster_view_reports_and_never_writes` 与
        `test_roster_state_is_checkable` 一起钉住（它们会读 `checked` / `reason` 与每格的存在性）。
        """
        from .conductor import (ACTIVE_CHILD_COUNT_KEY, CHILD_COUNT_KEY)  # 与真身同一来源
        diagnostics: dict[str, Any] = {
            "owner": owner, "scope": scope, "limit": int(limit), "unreadable": reason}
        return {"checked": False, "rows": [], "more": 0, "scope": scope,
                "diagnostics": diagnostics, "parent": owner, "reason": reason,
                "counts": None, "states": None, CHILD_COUNT_KEY: None,
                ACTIVE_CHILD_COUNT_KEY: None}

    def _roster_view_body(self, *, owner: str, scope: str = "self",
                          limit: int = 20) -> dict[str, Any]:
        """`roster_view` 的真身（口径与返回值见上一份 docstring）。：`{"checked","rows","more","reason","diagnostics"}`。

        每一行：`name` / `role` / `brief` / `brief_source`（`parent` 父给的原话 / `secretary` 秘书从任务原文代写 /
        `""` 缺这一格的行）/ `state`（活跃 / 待命 / 已停 / 已退役 / 未登记）/ `retirable`（按 `conductor.retire_ready`
        的三分支）/ `items_open`（只报不拦）/ `task_id`（当前调用），外加三格：`status`（机器
        可判的那一格：`running` / `idle` / `ready` / `retired` —— 中文那五档是给人读的，而"父要不要现在动手"需要
        一格能直接判的）、`in_flight`（它名下此刻还在跑的任务数，`Conductor.children_facts` 现算）、`last_reading`
        （它最近一条工作报告的摘要，`latest_report_of` 的同一份数据，但一次读一份手稿再逐行取）。DSH 的
        `list_agents` 没有这一格，我们的比它全 ⇒ "净减一样别丢"。`scope="descendants"` 时给全树（每
        一行多 `parent` 与 `depth`）—— 改前只有下一层。规模：默认只回 20 项 + `more`（与 `inbox_digest` 同族口径）。
        ## 父是谁（「名册 = 父 + 子 + 绝对编号」）：每一份视图都带一格 `parent`（见
        :meth:`parent_of`：绝对编号 + 角色 + 名册名），`scope="descendants"` 的行另带 `parent_task_id` —— 改前
        那些行只有相对名 `parent`，而"相对名"没法拿去发消息（那正是这一轮要补的那一格）。于是"我能通话的是谁"
        这件事在同一份读数里自足了，寻址不必再另造一个视图。
        ## 逐行 diagnostic（不再一行坏就整份拒）：改前名册里有一行读不出来 ⇒ `{"checked": False, "rows": []}`
        （整体拒）。DSH 的 `list-agents.js:30-47` 是逐行报 `corrupt/unsupported/unavailable`。现在照它：好行照常
        渲染，坏行逐条落进 `diagnostics`（带行号与类别）。只有一种情形仍然整体拒：一条好行都没有而坏行有（三态纪律挡的正是"名册是空的"与"名册读不成"被折成同一句话）。
        ## 两个读数各占一格
        这一份视图顶上带 `children_unretired`（子代理数 = 名下未销号的名册项数）与
        `active_child_count`（活跃子代理数 = 其中非静默的数量 = 在飞 + 待机），
        另有一格 `counts`（`Secretary.child_counts` 的整份读数：`owner` / `states` /
        `waiting_only` / `unjudged` / `note`）与一格 `states`（四档各几个）。
        两个数不许相加、不许互相代替 —— 口径与三态都在 :meth:`child_counts` 里，
        这里只转发。每一行另带 `agent_state`（三态：在飞 / 待机 / 静默 / 未读到 ——
        名字不叫 `state`，因为那一格已经是给人读的五档中文）、`active` /
        `waiting_only` / `waiting_note`：`active` 是"按继承口径算，它算不算活跃"，
        与 `state`（它自己此刻在不在跑）是两件事（"在等"也算活跃）。
        读不成 ⇒ 两个数与 `states` 都是 `None`（不是 0）。
        """
        from .conductor import (ACTIVE_CHILD_COUNT_KEY, AGENT_STATE_UNKNOWN,
                                CHILD_COUNT_KEY)

        cond = self._conductor()
        rows, bad = self.roster_rows(owner)
        diagnostics = [_diagnose_line(line) for line in bad]
        # 「我自己的父是谁」那一格（名册 = 父 + 子 + 绝对编号）。
        # 只有"我名下的子代理"时，父是谁只能从 `AgentLoop.parent_task_id` 那个内存字段
        # 读到，而名册自己（盘上那一份）答不上来。现在六条 return 都带上它。
        parent = self.parent_of(owner=owner)

        def _fail(reason: str) -> dict[str, Any]:
            """这一份视图"没查成"的统一形状（两个读数都是 None，不是 0）。"""
            return {"checked": False, "rows": [], "more": 0, "scope": scope,
                    "diagnostics": diagnostics, "parent": parent, "reason": reason,
                    "counts": None, "states": None, CHILD_COUNT_KEY: None,
                    ACTIVE_CHILD_COUNT_KEY: None}

        if not rows and bad:
            return _fail(f"名册有 {len(bad)} 行读不出来、且没有一行读得出来：{bad[0]}")
        if cond is None:
            return _fail("没有 store ⇒ 读不到台账（状态判不了）")
        try:
            ready = cond.retire_ready(owner)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"就绪读数没读成（{type(exc).__name__}: {exc}）")
        if not ready.get("checked"):
            return _fail(f"就绪读数没读成（{ready.get('reason')}）")
        # 活跃读数只取一次（逐行调 `active_reading` 会把同一张台账读 N 遍）：
        # `counts` 与逐行那三格共用这一份快照。
        # `retired` 是本层的事实（名册项上那一格）：传给三态判定，让"已销号 ⇒ 静默"
        # 仍然只由 `conductor.agent_state` 那一处判（这里不再写第二遍）。
        retired_map = {str(r.get("task_id") or ""): True for r in rows
                       if r.get("retired") and str(r.get("task_id") or "")}
        snap = cond.activity_snapshot(retired=retired_map)
        counts = self.child_counts(owner=owner, snapshot=snap)
        activity = dict(snap.get("by_task") or {}) if snap.get("checked") else {}
        name_of_tid = {str(r.get("task_id") or ""): str(r.get("name") or "") for r in rows}
        by_child = {str(r["task_id"]): r for r in ready.get("ready", [])}
        # 一份手稿读数，逐行取"它最近报了什么"（每行读一次会把名册变成 N 次全表读）。
        reports: dict[str, str] = {}
        try:
            mrows, _mbad = MS.read_rows(self.root)
            for r in mrows:
                tid = str(r.get("task_id") or "")
                if tid and str(r.get("summary") or ""):
                    reports[tid] = str(r.get("summary") or "")
        except Exception:  # noqa: BLE001 —— 手稿读不成 ⇒ 那几格空着（不是"它没报过"）
            reports = {}
        targets = self._roster_targets(owner=owner, rows=rows, scope=scope, cond=cond)
        out: list[dict[str, Any]] = []
        for t in targets:
            r, parent_name, depth = t["row"], t["parent"], t["depth"]
            parent_tid = str(t.get("parent_tid") or "")
            tid = str(r.get("task_id") or "")
            branch = str(t.get("branch") or "")
            facts = t["facts"]
            # 三态位与 `state` 同出（2026-10-27）：`state` 五档不变，另给 `state_checked`
            # 与 `state_reason` —— "它停了"与"它判不了"因此在同一份读数里分得开。
            reading = _state_reading(branch, bool(r.get("retired")), cond, tid,
                                     branch_checked=bool(t.get("branch_checked", True)))
            state = str(reading["state"])
            row: dict[str, Any] = {
                "name": str(r.get("name") or ""), "role": str(r.get("role") or ""),
                "brief": str(r.get("brief") or ""), "state": state,
                "state_checked": bool(reading["state_checked"]),
                "state_reason": str(reading["state_reason"]),
                # 简介是谁写的（`parent` 父给的原话 / `secretary` 秘书代写 / `""` 改前的行）
                "brief_source": str(r.get("brief_source") or ""),
                "retirable": branch == "waiting_no_children",
                "items_open": int(((by_child.get(tid) or {}).get("reading") or {})
                                  .get("items_open") or 0),
                "task_id": tid,
                "status": _status_enum(facts, retired=bool(r.get("retired"))),
                "in_flight": int(facts.get("in_flight") or 0),
                "last_reading": reports.get(tid, ""),
                # 活跃按继承口径算（业主 2026-10-26：有活跃的下级，自己已收口也算活跃），
                # 与 `state` 是两件事；`waiting_note` 是"靠等"的那一句人话。
                "active": bool((activity.get(tid) or {}).get("active")),
                "waiting_only": bool((activity.get(tid) or {}).get("waiting_only")),
                "waiting_note": str((cond.active_reading(
                    tid, names=name_of_tid, snapshot=snap).get("note") or "")
                    if snap.get("checked") else ""),
                # 三态（`conductor.agent_state` 是唯一实现）。名字刻意不叫 `state`：
                # 上面那一格 `state` 已经是给人读的五档中文（活跃 / 待命 / 已停 /
                # 已退役 / 未登记），两个取值域共用一个键会让"活跃"与"在飞"混成一件事。
                # "已销号 ⇒ 静默"不在这一行判：`retired_map` 已经随快照传进
                # `agent_state`（那一处才是判定本体）。
                "agent_state": str((activity.get(tid) or {}).get("state")
                                   or AGENT_STATE_UNKNOWN),
            }
            if scope == "descendants":
                row["parent"] = parent_name
                # 业主 2026-10-19：`parent` 记的是相对名，而通话要的是绝对编号。
                # 两格都给（相对名给人读，绝对编号给机器判）；改前只有相对名。
                row["parent_task_id"] = parent_tid
                row["depth"] = depth
            out.append(row)
        more = max(0, len(out) - int(limit))
        return {"checked": True, "rows": out[:int(limit)], "more": more, "scope": scope,
                "diagnostics": diagnostics, "parent": parent, "reason": "",
                "counts": counts, "states": counts.get("states"),
                CHILD_COUNT_KEY: counts.get(CHILD_COUNT_KEY),
                ACTIVE_CHILD_COUNT_KEY: counts.get(ACTIVE_CHILD_COUNT_KEY)}

    def _roster_targets(self, *, owner: str, rows: list[dict[str, Any]], scope: str,
                        cond: Any) -> list[dict[str, Any]]:
        """要渲染的那几行（`scope="descendants"` 时是全树，带 `parent`/`depth`）。

        深度上限 64：坏链不许把这里变成死循环（与 `inside_subtree` 的上行链同一条纪律）。
        每一层的 `facts` 现算一次（`children_facts`）—— 只在要渲染的那几行上算。
        """
        def parent_facts(tid: str) -> dict[str, Any]:
            try:
                got = cond.children_facts(tid)
            except Exception:  # noqa: BLE001
                return {"checked": False}
            return got

        out: list[dict[str, Any]] = []
        root_by = dict((parent_facts(owner).get("by_child") or {}))
        # 每一层的"可退役分支"（`branch` 是 `_state_reading` 折四态的那一格）。
        #
        # 2026-10-20（真机读数驱动，`projects/tree-check`）：改前 `by_child`（在 `roster_view`
        # 里由 owner 那一层的 `retire_ready` 构造）只覆盖直接子，于是全树视图里
        # 孙代及以下的 `branch` 恒为空 ⇒ `_state_reading` 落到「未登记」，而它们明明在名册上。
        # 实测那一份工作区：7 行里有 5 行（C1/F1/B1/B2/E1 --- 深度 2/3）被读成「未登记」，
        # 只有直接子 D1 读对（已停）。这与 `draft/90` §1.4「必须看到名册名 + 一句简介 +
        # 工作状态」直接冲突，也是机制②（M 看整棵树）唯一的真缺口。
        # 修法：逐层问它父那一层的 `retire_ready`（同一处实现，不另写一份分支判据），
        # 每个父只问一次（`branch_by_parent` 缓存）。
        branch_by_parent: dict[str, dict[str, str]] = {}

        #: 每一层的就绪读数"读成了没有"（2026-10-27）：`branch` 为空有两种原因 ——
        #: 那一层真没有可退役的项，或者那一层的读数根本没读成。两者不许折成同一句话，
        #: 所以这里把三态位带出去，`roster_view` 落进 `state_checked`。
        branch_checked_by_parent: dict[str, bool] = {}

        def branches_of(parent_id: str) -> dict[str, str]:
            if parent_id in branch_by_parent:
                return branch_by_parent[parent_id]
            got: dict[str, Any]
            try:
                got = cond.retire_ready(parent_id)
            except Exception:  # noqa: BLE001 —— 读不成 ⇒ 这一层没有分支（状态如实落到"未登记"）
                got = {"checked": False}
            found = ({str(r.get("task_id") or ""): str(r.get("branch") or "")
                      for r in (got.get("ready") or [])} if got.get("checked") else {})
            branch_by_parent[parent_id] = found
            branch_checked_by_parent[parent_id] = bool(got.get("checked"))
            return found
        root_id = str(owner or "")
        if scope != "descendants":
            top = branches_of(root_id)
            top_checked = bool(branch_checked_by_parent.get(root_id, False))
            for r in rows:
                tid = str(r.get("task_id") or "")
                out.append({"row": r, "parent": "", "parent_tid": "", "depth": 1,
                            "branch": top.get(tid, ""),
                            "branch_checked": top_checked,
                            "facts": dict(root_by.get(tid) or {})})
            return out
        # 全树：逐层往下，每一层的 facts 从它的父那一格里取。
        # 这一格最容易写错（第一版就是）：`children_facts(X)` 给的是"X 名下"的读数，
        # 而某一行要的是"它父名下的它自己"那一格 —— 拿 X 去查 X 只会得到空表，
        # 于是全树的每一行都会读成 `ready`（一个安静的错误：没有任何地方会报错）。
        top_branches = branches_of(root_id)
        top_checked = bool(branch_checked_by_parent.get(root_id, False))
        queue: list[tuple[dict[str, Any], str, str, int, dict[str, Any], str, bool]] = []
        for r in rows:
            tid = str(r.get("task_id") or "")
            queue.append((r, "", root_id, 1, dict(root_by.get(tid) or {}),
                          top_branches.get(tid, ""), top_checked))
        # 队列用游标取头（原先 `pop(0)` 每次把整个列表前移一格）：先来先处理
        # 的顺序一个字没变，只是取头从 O(队列长) 变成 O(1)。
        head = 0
        seen = 0
        while head < len(queue) and seen < 512:
            r, parent_name, parent_tid, depth, facts, branch, checked = queue[head]
            head += 1
            seen += 1
            out.append({"row": r, "parent": parent_name, "parent_tid": parent_tid,
                        "depth": depth, "branch": branch, "branch_checked": checked,
                        "facts": facts})
            if depth >= 64:
                continue
            tid = str(r.get("task_id") or "")
            kids, _bad = self.roster_rows(tid)
            if not kids:
                continue
            by = dict((parent_facts(tid).get("by_child") or {}))
            their = branches_of(tid)
            their_checked = bool(branch_checked_by_parent.get(tid, False))
            for k in kids:
                kt = str(k.get("task_id") or "")
                queue.append((k, str(r.get("name") or ""), tid, depth + 1,
                              dict(by.get(kt) or {}), their.get(kt, ""), their_checked))
        return out


def registration_refusals(root: str | Path, *, owner: str = "") -> dict[str, Any]:
    """名册写口拒过的那些号 —— 只读读数。

    为什么要一个读数面：这条流水（`refusals_path`）从 2026-11-02 起就在盘上，但唯一的读者
    是收口兜底 `Secretary.roster_repair` —— "这一号曾被拒过"在人的读数面上完全不可见。
    "这一号曾被拒过"在人的读数面上必须可见。

    名字为什么叫 `registration_refusals`（而不是 `refusals`）：全仓 `refusals` 一词已有三义
    —— 动作被拒的行（`statusreport` 的 `refusal_reason`）、收工被拒的事件
    （`patrol` 的 `final_refused`）、以及这一份名册写口的拒绝流水。三件事各一个词：
    `action_refusals` / `final_refusals` / `registration_refusals`（前两个的改名与 U-07 同轮）。

    返回 `{"checked", "count", "items", "bad", "owner", "path"}`：
    - `checked=False` ⇒ 这一份流水读不出来（坏行见 `bad`）—— 不是"没人被拒"；
    - `items` 每条 `{task_id, requested_name, refusal_code, problem, at}`（原样透传流水里的格）；
    - `owner` 给空串 ⇒ 读 `out/roster/refusals/` 下全部父的流水（跨父合计）。
    """
    from . import jsonlfile as JF

    base = Path(root).joinpath(*ROSTER_DIR, "refusals")
    paths: list[Path] = []
    if str(owner or ""):
        paths = [refusals_path(root, str(owner))]
    else:
        try:
            paths = sorted(base.glob("*.jsonl"))
        except OSError:
            paths = []
    items: list[dict[str, Any]] = []
    bad: list[str] = []
    checked = True
    for path in paths:
        rows, bad_rows, state = JF.read_jsonl_state(path)
        if state == "unreadable":
            checked = False
            bad.append(f"{path.name} 读不出来（这一格不是「没人被拒」）")
        bad.extend(str(x) for x in bad_rows)
        for row in rows:
            items.append({
                "task_id": str(row.get("task_id") or ""),
                "requested_name": str(row.get("requested_name") or ""),
                "refusal_code": str(row.get("refusal_code") or ""),
                "problem": str(row.get("problem") or ""),
                "at": str(row.get("at") or ""),
            })
    return {"checked": checked and not bad, "count": len(items), "items": items,
            "bad": bad, "owner": str(owner or ""),
            "path": str(paths[0]) if len(paths) == 1 else str(base)}


def retired_row_gaps(rows: Iterable[Any], owner: str = "") -> tuple[list[str], list[dict[str, Any]]]:
    """销号名单每一行"认不认得出是哪一号 / 哪一名" ⇒ `(逐条说明, 逐条结构化读数)`。

    为什么这一档单列（`draft/145` R8/R10/R11/R18）：`jsonlfile.read_jsonl` 只回答
    "这一行是不是合法 JSON / 是不是对象"，不回答"这一行说的是谁"。于是下面这些都
    读成"这一份里没有它"、进而被叫醒（已销号却仍被叫醒是不可逆的那一边）：

    ```text
    少 task_id（只有名字）      ⇒ 唤醒闸手里只有号 ⇒ 认不出
    task_id 写成 int / name 写成 list ⇒ str(...) 出来的东西永远不等于真键 ⇒ 认不出
    owner 与所在分片不符         ⇒ 归属键自相矛盾（R19 的"张冠李戴"那一半）
    ```

    判据只说两件事（§3.1 注 2）：`task_id` 与 `name` 是不是非空字符串，
    外加 `owner` 与分片名对不对得上。刻意不校验"号看起来像不像 `t-000123`"——
    格式校验会变成第二份发号口径。

    返回第二格给"这一行可能是谁"用（按号 / 按名逐个排除）：`task_id` / `name`
    非空字符串就原样带着，否则空串（= 用不了这个键）。名字那一半要靠调用方去名册里
    换算出"这一号叫什么"才能排除（见 `Conductor._retired_names_of_key`）。
    """
    messages: list[str] = []
    rows_out: list[dict[str, Any]] = []
    for i, row in enumerate(rows or (), 1):
        if not isinstance(row, Mapping):
            # 一行就是一个号 / 一个名字（老 dict 替身、`retired_names = ["t-1"]`）
            if not str(row or "").strip():
                msg = f"第 {i} 行认不出来（空行）"
                messages.append(msg)
                rows_out.append({"line": i, "task_id": "", "name": "", "why": msg})
            continue
        tid = row.get("task_id")
        name = row.get("name")
        use_tid = str(tid).strip() if (isinstance(tid, str) and tid.strip()) else ""
        use_name = str(name).strip() if (isinstance(name, str) and name.strip()) else ""
        why = ""
        if not use_tid:
            why = f"第 {i} 行认不出来（task_id 不是非空字符串：{tid!r}）"
        elif not use_name:
            why = f"第 {i} 行认不出来（name 不是非空字符串：{name!r}）"
        elif owner and str(row.get("owner") or "") not in ("", str(owner)):
            why = (f"第 {i} 行的 owner={row.get('owner')!r} 与分片不符"
                   f"（分片是 {owner!r}）")
        if not why:
            continue
        messages.append(why)
        rows_out.append({"line": i, "task_id": use_tid, "name": use_name, "why": why})
    return messages, rows_out


def roster_owners(root: str | Path) -> tuple[list[str], str]:
    """`out/roster/` 下有哪些父名册（`(父编号列表, 问题)`）。

    只认 `<父>.jsonl`：三种旁支（对照表 / 面池 / 销号名单）按
    `_ROSTER_SIDECAR_SUFFIXES` 排除。目录不存在 ⇒ `([], "")`（那是"还没有人派过活"，
    不是读失败）；目录读不出来 ⇒ `([], 理由)`（三态，不折成"一份名册都没有"）。
    """
    folder = Path(root).joinpath(*ROSTER_DIR)
    if not folder.is_dir():
        return [], ""
    try:
        names = [p.name for p in folder.iterdir() if p.is_file()]
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
        return [], f"名册目录读不成（{type(exc).__name__}: {exc}）"
    out: list[str] = []
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        if any(name.endswith(s) for s in _ROSTER_SIDECAR_SUFFIXES):
            continue
        owner = name[: -len(".jsonl")]
        if owner:
            out.append(owner)
    return sorted(out), ""


def _fold_roster(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把名册事件流折叠成"当前状态"（一项一条 = 一个常驻子代理）。

    口径：`add` 建项（一项 = 一个子代理的身份：名字 / 角色 / 简介 / 面）；
    `bind` 只推这一项"最近一次接的活"的编号读数；`retire` 标退役；`keep_alive` 只记
    那一格。名字是身份：同一个名字不会有两项。

    `task_id` / `first_task_id` 是"调用流水读数"（这一项是为哪件活建的、最近一次
    是哪件活），不是身份，也不是归属键 —— 一个子代理可以接 N 件活，名册里仍是
    一项（一个子代理可以接多个任务；名册不按任务号记）。
    """
    items: dict[str, dict[str, Any]] = {}
    for raw in rows:
        r = dict(raw)
        name = str(r.get("name") or "")
        if not name:
            continue
        item = items.setdefault(name, {"name": name, "role": str(r.get("role") or ""),
                                       "brief": "", "brief_source": "", "task_id": "",
                                       "task_text": "", "retired": False})
        kind = str(r.get("kind") or "")
        if str(r.get("role") or ""):
            item["role"] = str(r.get("role") or "")
        if kind == "add":
            item["brief"] = str(r.get("brief") or "")
            # 简介是谁写的（简介没写时秘书帮忙写）：
            # `parent` = 父给的原话；`secretary` = 秘书从任务原文派生的一句；
            # `""` = 这一格缺失的行（不许倒填成"父给的"）。
            item["brief_source"] = str(r.get("brief_source") or "")
            item["task_id"] = str(r.get("task_id") or "")
            item["first_task_id"] = str(r.get("first_task_id") or r.get("task_id") or "")
            item["surface"] = str(r.get("surface") or "")
        elif kind == "bind":
            item["task_id"] = str(r.get("task_id") or item.get("task_id") or "")
        elif kind == "retire":
            item["retired"] = True
            item["retired_branch"] = str(r.get("branch") or "")
        elif kind == "keep_alive":
            # 读侧先落地的那一格：今天没有任何生产者（全仓没有一处往名册写
            # `kind="keep_alive"` 的行）。
            # 「做完还待命」这条事实的唯一来源是台账那一侧的派活项（
            # `conductor.keep_alive_of` 读 `kind="delegation"` 行的 `keep_alive`），
            # `_state_reading` 走的正是那一条路。
            # 为什么留着而不是删：它是名册事件的合法一格，删掉之后
            # 将来真要写它的人会在别处再写一份 fold —— 而"同一份事件流的两种折法"正是
            # 本仓栽过的那一类。读数侧的代价为零（这一行永远不会命中）。
            # 反过来说：如果哪天有人开始写它，`keep_alive_of` 与这一格就是两份口径，
            # 那时必须合并成一处 —— 所以这一行在此点名，免得它继续静默。
            item["keep_alive"] = bool(r.get("value"))
        # 任务原文（自动以 task 填充目的）：它是父派下来的那件事
        # 本身，`add` 与 `bind` 两行都可能带着它（复用支只写 bind）。改前落的行没有
        # 这一格 => 空格（不许拿 brief 冒充：brief 是 60 字摘要，不是原文）。
        text = str(r.get("task_text") or "")
        if text:
            item["task_text"] = text
    return [items[k] for k in sorted(items)]


def _fold_index(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把对照表折叠成"名字 → 当前调用（+ 第一次那个）"。

    `bind` 推当前；`retire` 标退役（行保留：编码不回收，反查还要用）。
    """
    items: dict[str, dict[str, Any]] = {}
    for raw in rows:
        r = dict(raw)
        name = str(r.get("name") or "")
        if not name:
            continue
        item = items.setdefault(name, {"name": name, "role": str(r.get("role") or ""),
                                       "task_id": "", "first_task_id": "",
                                       "retired": False})
        if str(r.get("role") or ""):
            item["role"] = str(r.get("role") or "")
        if str(r.get("kind") or "") == "retire":
            item["retired"] = True
            continue
        item["task_id"] = str(r.get("task_id") or item.get("task_id") or "")
        if r.get("first") or not item.get("first_task_id"):
            item["first_task_id"] = str(r.get("task_id") or item.get("first_task_id") or "")
    return [items[k] for k in sorted(items)]
