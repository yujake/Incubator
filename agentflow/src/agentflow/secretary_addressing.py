# -*- coding: utf-8 -*-
"""秘书的寻址与父子计数（从 secretary.py 的 U08 前半逐字搬出）。

我保证哪条不变式：一个号对一个名字；同一个号读出两个意思时判不了（受控拒），不许挑一个用。

## 为什么它能单独成文件（依赖方向）

`secretary_addressing` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_addressing` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from pathlib import Path

from .secretary_axis import (  # noqa: F401 — 这些名字由 secretary_axis 定义
    ran_but_unnamed,
)

from .secretary_roster_read import (  # noqa: F401 — 这些名字由 secretary_roster_read 定义
    registration_refusals,
    roster_owners,
)


class AddressingMixin:
    """寻址/父子/计数/孤儿（从 secretary.py 搬出的混入类）。"""

    def resolve_down(self, *, owner: str, name: str) -> tuple[str, str]:
        """下行译码：我名下名册里的名字 → 当前调用行。"""
        return self._resolve(owner, name)

    def resolve_roster_item(self, *, owner: str, name: str) -> tuple[str, str]:
        """销号口径的下行译码：名册名 → 这个名册项自己的那个号（不是"它最近在跑哪一件活"）。

        两格分工（2026-11-17 真机 `projects/lp-ball-3` 缺陷 ③ 之后定死）：

        - :meth:`resolve_down` 答"这个名字此刻在跑哪一件活"：消息投递要它，取最新那条
          `bind` 的号；
        - 这一格答"这个名册项是哪个号"：销号要它，取名册项创建时那个号
          （`first_task_id` —— `out/roster/<父>.jsonl` 的 `add` 行 / 第一条 `bind`）。

        为什么不能拿 `resolve_down` 去销号：名字可以被复用（同一个子代理再接一件活，
        `_roster_add` 的 `reuse` 支），于是同一个名字绑着 N 个号。`resolve_down` 给的是
        最新那个，销号就只销最新那一趟；而 `Conductor.retire_integrity` 数的是台账里
        每一个代理行（按父行 `inputs` 里的 `edge-released:` 落痕算），早先那个号不在
        落痕里 ⇒ 整棵树永远"还有人在册"。真机现场：`D1` 绑过 `t-000008`（名册项）与
        `t-000110`（复用那一趟），按名销号销的是 `t-000110`，`t-000008` 留在册 ⇒
        `final` 被结构完整性闸拒、M 三次试销号都读到"名册与台账对不上"。

        读法与 `_fold_roster` 同一份折叠（`first_task_id`）；折叠里没有它时退回
        `_roster_bindings` 的第一条命中（H7 的"半份登记"），再没有才回空 + 一句为什么。
        三态：名册正文 / 对照表读不出来 ⇒ 空号 + 理由（不猜一个号，那会把别人的行销掉）。
        """
        try:
            rows, bad = self.roster_rows(owner)
        except Exception as exc:  # noqa: BLE001 —— 读侧自己炸了也是"没读成"
            return "", f"名册读不成（{type(exc).__name__}: {exc}）"
        if bad:
            return "", f"名册正文有 {len(bad)} 行读不出来 ⇒ 名字换不成编号（没读成）"
        for r in rows:
            if str(r.get("name") or "") != str(name):
                continue
            tid = str(r.get("first_task_id") or r.get("task_id") or "")
            if tid:
                return tid, ""
            break
        # 名册正文缺行（H7 / D-66：名字只活在对照表的调用记录里）⇒ 退回全历史。
        # 第一条命中就是"这一项是拿哪个号建的"（`add` 行在前、`bind` 行在后）。
        binds, bad_binds = self._roster_bindings(owner)
        if bad_binds:
            return "", f"对照表有 {len(bad_binds)} 行读不出来 ⇒ 名字换不成编号（没读成）"
        for tid, who in binds:
            if who == str(name):
                return tid, ""
        return "", f"对照表里没有 {name!r}（未登记或已退役）"

    def _bound_agent_ids(self, *, owner: str, name: str, item_id: str) -> tuple[list[str], str]:
        """这个名字绑过的、本父名下的每一个代理行：`([号...], 为什么一个都不销)`。

        销号销的是"一个名册项"（= 一个子代理的身份），而这个身份可能绑过 N 个号
        （复用是合法的一等功能）。`retire_integrity` 数的是台账行 ⇒ 只销一个号会把
        其余的号留在"在册"。所以这里把"这一项绑过的号"一次收齐（名册项自己那个号排最前）。

        两条 fail-closed（销一半比不销更坏，销到别人头上更坏）：
        - 名册 / 对照表读不出来 ⇒ 整笔不销（不知道还漏着哪个号）；
        - 某个号不是本父名下的代理行 ⇒ 整笔不销（一个号只属于一个父，销错不可逆）。
        台账里根本没有这一行 / 它是板项 ⇒ 跳过（没有可落终态的对象，那不是"别人的号"）。
        """
        out: list[str] = [str(item_id)] if str(item_id) else []
        binds, bad = self._roster_bindings(owner)
        if bad:
            return out, (f"名册/对照表有 {len(bad)} 行读不出来 ⇒ 不知道 {name} 还绑过哪些号"
                         "（销一半比不销更坏，整笔不销）")
        cond = self._conductor()
        if cond is None:
            return out, "没有 store ⇒ 读不到台账（销号没有对象）"
        for tid, who in binds:
            if who != str(name) or tid in out:
                continue
            try:
                row = cond._task(tid) or {}
            except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
                return out, (f"{tid}（{name} 绑过的另一个号）读不成"
                             f"（{type(exc).__name__}: {exc}）⇒ 整笔不销")
            if not row:
                continue
            if cond._is_board_item(row):
                continue
            if str(row.get("parent_task_id") or "") != str(owner):
                return out, (f"{tid}（{name} 绑过的另一个号）不是你的子代理"
                             f"（它的父是 {row.get('parent_task_id') or '（顶层）'}）⇒ "
                             "整笔不销：销号只许销本父名下的号")
            out.append(tid)
        return out, ""

    def resolve_up(self, *, my_task_id: str, name: str) -> tuple[str, str]:
        """上行译码：我父名册里的名字 → 当前调用行（父的代号从我那一行读）。"""
        cond = self._conductor()
        if cond is None:
            return "", "没有 store ⇒ 读不到我那一行（不知道父是谁）"
        try:
            row = cond._task(str(my_task_id or ""))
        except Exception as exc:  # noqa: BLE001
            return "", f"台账读不成（{type(exc).__name__}: {exc}）"
        if not row:
            return "", f"台账里没有我这一行（{my_task_id!r}）"
        parent = str(row.get("parent_task_id") or "")
        if not parent:
            return "", "我是顶层发起 ⇒ 没有父名册（上行只能发给用户/主控）"
        return self._resolve(parent, name)

    def name_of(self, *, owner: str, task_id: str) -> tuple[str, str]:
        """反查：某个调用行属于这个名册里的哪一个名字（一个号两个名字 ⇒ 不猜）。

        为什么必须在本层拒歧义（`draft/151` 三-4）：写口从 2026-11-02 起拒"同一个号
        出现在两条 add"（`task_id_reused`），但 `projects/ 下` 里的历史名册有这一形态；
        按号寻址那一侧（`agent_loop.roster_addresses`）已经因此拒 `ambiguous_in_roster`，
        而这里改前 `return` 第一个命中 —— `surface_of` 就会按第一个名字的槽位去切
        读写面，两个人的面重叠等于跨代理写同一份文件。三态纪律：多匹配不是"查到了
        一个"，它是"这一格判不了"，回空名 + 一句点名（读者退回用编号）。

        ## 读全历史，不读折叠视图（2026-11-17，真机 `projects/lp-ball-3` 缺陷 ③）
        改前这里读 `roster_index` 的折叠结果，而 `_fold_index` 对每个名字只留最新
        那条 `bind` 的 `task_id`。于是"同一个名字接过两件活"时，早先那个号在这里
        读成"未登记"：真机 `D1` 绑过 `t-000008`（名册项自己的号）与 `t-000110`
        （复用那一趟），折叠后只剩 `t-000110` ⇒
        `name_of(owner="t-000001", task_id="t-000008")` 回 `""`，
        而 `retire_child(child_name="D1")` 走的是 `t-000110` —— 两个入口给出两种答案：
        按名销掉的是复用那一趟、按号那一侧被读成"名册里没有它"，那个号在
        `retire_integrity` 里永远"还在册"（`_released_pairs` 没被写到它名下）。
        判据 `tests/test_retire_by_name_and_by_task_id_agree.py` 的 a 钉着这件事。
        """
        rows, bad = self._roster_bindings(owner)
        if bad:
            return "", f"名册/对照表有 {len(bad)} 行读不出来"
        names = sorted({who for tid, who in rows
                        if who and str(tid) == str(task_id)})
        if len(names) > 1:
            return "", (f"对照表里 {task_id} 对应 {len(names)} 个名字（{'、'.join(names)}）"
                        "⇒ 不猜（同一个号两个名字；按号寻址的同一档是 "
                        "`ambiguous_in_roster`，这一份名册要人核）")
        if names:
            return names[0], ""
        return "", f"对照表里没有 {task_id}（未登记）"

    def parent_of(self, *, owner: str) -> dict[str, Any]:
        """这个台账号（`owner`）的「父代理」：`{"checked","task_id","role","name","why"}`。

        业主 2026-10-19：名册 = 「一个代理能看到的：自己的父代理是谁（含绝对编号）、自己的子代理是谁（含绝对
        编号）」。改前这一份名册只答得出后一半 —— 父是谁只躺在 `AgentLoop.parent_task_id` 那个内存字段里，盘上
        的名册一个字都没有；于是"给父发一条"在位址这一步无据可依（只能按角色名发，那就绕开了名册）。四个格：
        - `task_id`：「绝对编号」（我那一行的 `parent_task_id`）。空串 = 顶层发起（`open_top_level_run` 建的那一行
          是它自己的父 ⇒ 也当"没有父"）；
        - `role`：父那一行的 `role`（读不到 ⇒ 空串 + `why`）；
        - `name`：父的「名册名」。它记在「祖父」的名册索引里（相对名 vs 绝对编号：`name_of(owner=祖父, task_id=父)` 这一步就是换算），读不到 ⇒ 空串 + `why`；
        - `checked`：这一格读成了没有。`False` 「不等于」"没有父"（三态纪律）。
        只读（`draft/92` I-15：查只报不修）：一行都不写。
        """
        out: dict[str, Any] = {"checked": False, "task_id": "", "role": "", "name": "",
                               "why": ""}
        cond = self._conductor()
        if cond is None:
            out["why"] = "没有 store ⇒ 读不到台账（父是谁判不了）"
            return out
        mine = str(owner or "")
        if not mine:
            out["why"] = "没给台账号 ⇒ 不知道问谁的父"
            return out
        try:
            row = cond._task(mine) or {}
        except Exception as exc:  # noqa: BLE001 —— 读不成要如实说
            out["why"] = f"台账读不成（{type(exc).__name__}: {exc}）"
            return out
        if not row:
            out["why"] = f"台账里没有 {mine} 这一行 ⇒ 父是谁读不出来"
            return out
        pid = str(row.get("parent_task_id") or "")
        out["checked"] = True
        if not pid or pid == mine:
            out["why"] = "顶层发起（没有父代理）"
            return out
        out["task_id"] = pid
        try:
            prow = cond._task(pid) or {}
        except Exception as exc:  # noqa: BLE001
            out["why"] = f"父那一行读不成（{type(exc).__name__}: {exc}）"
            return out
        out["role"] = str(prow.get("role") or "")
        gp = str(prow.get("parent_task_id") or "")
        if gp and gp != pid:
            try:
                name, _why = self.name_of(owner=gp, task_id=pid)
            except Exception:  # noqa: BLE001
                name = ""
            out["name"] = name
        out["why"] = "" if out["name"] else "父的名册名读不到（它记在祖父的名册里）"
        return out

    def child_counts(self, *, owner: str = "",
                     snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """两个读数：子代理数 / 活跃子代理数（本方法是它们唯一的实现）。

        ## 两个数各自的定义（见 `conductor` 那几个常量）
        - 子代理数 = 名册里还没销号的名册项数（在册、未退役）；
        - 活跃子代理数 = 其中非静默的数量（「活跃子代理」的定义就是非静默子代理）：
          非静默 = 在飞 + 待机，三态判定只有 `conductor.agent_state`
          一处；`unknown`（判不了）既不算活跃也不算静默，它进 `states["unknown"]`
          并让 `complete=False`。

        两个数必须各自出现、不许相加也不许互相代替：前者回答"这一支还有几个名字在用"，
        后者回答"其中几个还在干活或还在等"。折成一个数之后，"名册只增不减"与
        "活都干完了"会长得一模一样。

        ## 三态的读法（业主原话：「『在飞』的读数要随着时钟式待机进行适配」）
        `states` 是四档各几个（`flying` / `standby` / `silent` / `unknown`）＋
        `active`（= 在飞 + 待机）＋ `total`；`by_owner` 每一项同样带这四格。
        已销号的名册项不进 `items`（子代理数只数未销号的那些），所以"已销号 ⇒ 静默"
        在这一份读数里表现为"它根本不在分母里"——与 `roster_view` / 网页名册面
        逐行给 `state` 的那一处是同一条口径的两个落点。
        口径取"名册项当前那一件活那一行"（`item.task_id`）：一个常驻子代理接过 N 件活时，
        那 N 行的三态在 `activity_snapshot` 里各自可得，而"它现在在哪一态"问的是现在。
        网页名册面（`readers.roster_face`）对同一项按 `tasks[]` 里全部活取最活跃的一格
        —— 两处都是"这一层知道多少就判多少"，谁也没有把不知道的当成静默。

        ## 范围
        `owner` 给了 ⇒ 只看那一个父的名册；不给 ⇒ 全工作区（`roster_owners` 扫
        `out/roster/<父>.jsonl`，三种旁支排除）。`by_owner` 是同一个口径的分父读数。

        ## 三态与"判不了"（不许折平）
        名册读不成 / 台账读不成 ⇒ `checked=False` + `reason`，两个数都是 `None`
        （`0` 是"名册空了"这个很强的结论，而"没读成"什么都不说）。
        某一项的名册行读得出来、但台账里没有它那一行 ⇒ 它的三态判不了 ⇒ 进 `unjudged`
        且 `complete=False`，同时 `active_child_count` 只数判得了的那些（读数里
        `complete` 那一格就是这件事的显式声明，不许靠"大概都判得了"糊过去）。

        ## `waiting_only`（病态形状）
        每一项 `standby and not self_busy` 的节点都进 `waiting_only`，带一句人话
        「它自己不忙，是在等 D2（active）」。那不是错，但父必须看得见 ——
        这一支的活积在下级身上，而中间那几层只是挂着名字在等。
        """
        from .conductor import (ACTIVE_CHILD_COUNT_KEY, CHILD_COUNT_KEY,
                                CHILD_COUNT_LABELS, AGENT_STATE_LABELS,
                                AGENT_STATE_UNKNOWN, ACTIVE_AGENT_STATES,
                                state_counts)

        labels = dict(CHILD_COUNT_LABELS)
        out: dict[str, Any] = {"checked": False, "reason": "", "owner": str(owner or ""),
                               CHILD_COUNT_KEY: None, ACTIVE_CHILD_COUNT_KEY: None,
                               "labels": labels, "waiting_only": [], "unjudged": [],
                               "states": None, "state_labels": dict(AGENT_STATE_LABELS),
                               "complete": False, "by_owner": {}, "bad_roster_lines": [],
                               "note": ""}
        want = str(owner or "")
        if want:
            owners, why_dir = [want], ""
        else:
            owners, why_dir = roster_owners(self.root)
        if why_dir:
            out["reason"] = why_dir
            return out
        items: list[dict[str, Any]] = []
        bad_lines: list[str] = []
        for own in owners:
            rows, bad = self.roster_rows(own)
            bad_lines.extend(str(x) for x in bad)
            for it in rows:
                if it.get("retired"):
                    continue
                items.append({"owner": own, "name": str(it.get("name") or ""),
                              "role": str(it.get("role") or ""),
                              "task_id": str(it.get("task_id") or "")})
        out["bad_roster_lines"] = bad_lines
        if bad_lines and not items:
            out["reason"] = (f"名册有 {len(bad_lines)} 行读不出来、且没有任何一项读得出来："
                             f"{bad_lines[0]}")
            return out
        cond = self._conductor()
        if cond is None:
            out["reason"] = "没有 store ⇒ 读不到台账（活跃子代理数判不了）"
            return out
        snap = dict(snapshot) if snapshot is not None else cond.activity_snapshot()
        if not snap.get("checked"):
            out["reason"] = f"台账读不成（{snap.get('reason')}）⇒ 活跃子代理数判不了"
            return out
        by_task = dict(snap.get("by_task") or {})
        per_owner: dict[str, dict[str, int]] = {}
        # 全量的三态读数在下面那一趟里顺手攒下来：原先建一张 `tid -> state` 的表，
        # 再拿 items 逐条查表扫第二遍（同一批项走两趟）。逐项 append 与逐项查表同值，
        # 同号多项时也是逐项各记一次（与原来的生成器一致）。
        states_seen: list[str] = []
        waiting: list[dict[str, Any]] = []
        unjudged: list[dict[str, Any]] = []
        for it in items:
            slot = per_owner.setdefault(it["owner"], {CHILD_COUNT_KEY: 0,
                                                      ACTIVE_CHILD_COUNT_KEY: 0,
                                                      "flying": 0, "standby": 0,
                                                      "silent": 0, "unknown": 0})
            slot[CHILD_COUNT_KEY] = int(slot[CHILD_COUNT_KEY]) + 1
            tid = it["task_id"]
            cell = by_task.get(tid)
            if cell is None:
                # 台账里没有它那一行 ⇒ 三态判不了（`unknown`），而 `unknown` 不是静默：
                # 把它折成静默会让"判不了"与"它就是收工了"长得一模一样。
                states_seen.append(AGENT_STATE_UNKNOWN)
                slot["unknown"] = int(slot["unknown"]) + 1
                unjudged.append({"owner": it["owner"], "name": it["name"],
                                 "task_id": tid, "state": AGENT_STATE_UNKNOWN,
                                 "why": "台账里没有它那一行 ⇒ 它有没有未收口的活判不了"})
                continue
            state = str(cell.get("state") or AGENT_STATE_UNKNOWN)
            states_seen.append(state)
            # 词表外的取值记进 `unknown`（`conductor.state_counts` 的同一条口径）：
            # 先算出要落的键再累加 —— 直接 `slot[key] = int(slot.get(state)) + 1`
            # 会读到"另一格"的旧值，于是 `unknown` 每遇到一个词表外取值就被
            # 覆盖成 1（实测：两项判不了 + 一项词表外 ⇒ `by_owner` 说 1、`states` 说 3，
            # 而 `note` 里那句"另有 3 项判不了"用的是后者）。
            bucket = state if state in slot else AGENT_STATE_UNKNOWN
            slot[bucket] = int(slot.get(bucket) or 0) + 1
            if state not in ACTIVE_AGENT_STATES:
                continue
            slot[ACTIVE_CHILD_COUNT_KEY] = int(slot[ACTIVE_CHILD_COUNT_KEY]) + 1
            if not cell.get("waiting_only"):
                continue
            kids = [str(k) for k in (cell.get("waiting_for") or [])]
            wait_names: list[str] = []
            for k in kids:
                nm, _why = self.name_of(owner=tid, task_id=k)
                if nm:
                    wait_names.append(nm)
                else:
                    krow = by_task.get(k) or {}
                    wait_names.append(f"{krow.get('role') or '?'}（{k}）")
            waiting.append({"owner": it["owner"], "name": it["name"],
                            "role": it["role"], "task_id": tid, "state": state,
                            "waiting_for": kids, "for_names": wait_names,
                            "note": ("它自己不忙，是在等 " + "、".join(wait_names)
                                     + "（active）")})
        counts = state_counts(states_seen)
        active_count = counts["active"]
        note = (f"{labels[CHILD_COUNT_KEY]}={len(items)}，"
                f"{labels[ACTIVE_CHILD_COUNT_KEY]}={active_count}"
                f"（在飞 {counts['flying']} · 待机 {counts['standby']} · "
                f"静默 {counts['silent']}）")
        if counts["unknown"]:
            note += f"；另有 {counts['unknown']} 项判不了（{AGENT_STATE_LABELS['unknown']}）"
        if waiting:
            note += f"（其中 {len(waiting)} 个靠等下级才活跃）"
        if unjudged:
            note += (f"；有 {len(unjudged)} 项判不了活跃"
                     "（台账里没有它那一行）⇒ 活跃子代理数只数了判得了的那些")
        out.update({"checked": True, "reason": "",
                    CHILD_COUNT_KEY: len(items),
                    ACTIVE_CHILD_COUNT_KEY: active_count,
                    "states": counts,
                    "waiting_only": waiting, "unjudged": unjudged,
                    # `unknown` 非 0 就不算完整：那一档既不是活跃也不是静默，
                    # 只是"这一项没判成"，而"完整性"这一格正是这件事的显式声明。
                    "complete": (not unjudged) and counts["unknown"] == 0,
                    "by_owner": {k: dict(v) for k, v in sorted(per_owner.items())},
                    "note": note})
        return out

    def unnamed_children(self, *, owner: str = "") -> dict[str, Any]:
        """
        「真跑但无名」的逐条读数（只读，不修）。

        ## 它回答的问题

        「这一支里，有没有真跑过、却在任何一个父的名册上都找不到名字的子代理？」
        —— 真跑、`done/ok`、有产物，而名册三份里一行都没有：父永远叫不出它的名字
        （`retire(name=…)` 叫不到，只能用 `retire_child(task_id=…)` 走 unrostered 那一支认边收口，
        收完仍然没有名字）。

        ## 判据只有一处

        「真跑过」的条件全在模块级 :func:`ran_but_unnamed` 里，这里只负责取数、join、按父归组。
        网页那一格（`webui.readers._roster_unrostered_children`）用同一个函数给每条打 `ran` 标记 ——
        两个面说的是同一句话，不是各写一份。

        ## 口径：台账 join 名册历史，不读会话

        会话里那条 `roster_problem` 不可靠：可抢占派活在句柄没落定时提前返回，名册读数那一行在后面。
        所以这一格只读盘上的事实：`tasks`（谁真跑过）+ 名册三份（谁有名字）+ 拒绝流水
        （它当初点的那个名字，现在在谁手里）。

        ## 三态（`checked` 绝不折成"没有"）

        - 台账读不成 ⇒ `checked=False` + `reason`，`count=None`（不是 0：0 是"查过了，一个都没有"）；
        - 某个父的名册 / 拒绝流水有坏行 ⇒ 同样 `checked=False` + `bad` 逐条点名 ——
          "读不全"不许折成"这一支没有无名子代理"（fail-closed，与 :meth:`roster_repair` 同一条纪律）。

        ## 返回

        `{"checked","count","scanned","rows","bad","owners","reason"}`；`rows` 每一条：

        - `task_id` / `role` / `parent_task_id` / `status` / `outcome` / `started_at` / `ended_at`；
        - `artifacts`（台账里那一格原样）+ `artifacts_missing`（在盘上找不到的那几个）；
        - `edge_released`：父有没有已经认掉这条边（收口了仍然没有名字，正是这一格要让人看见的事）；
        - `requested_name` / `refusal_code`：它当初点名要的是什么、被哪一档拒绝；
        - `held_by`：那个名字现在挂在谁身上（`null` = 没人用）—— 这一格回答"是哪个号占掉了它的名字"。
        """
        out: dict[str, Any] = {"checked": False, "count": None, "scanned": 0,
                               "rows": [], "bad": [], "owners": [], "reason": ""}
        cond = self._conductor()
        if cond is None:
            out["reason"] = "没有 store ⇒ 读不到台账（这一格不是「没有无名子代理」）"
            return out
        try:
            rows = [r for r in cond._tasks() if not str(r.get("kind") or "")]
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            out["reason"] = f"台账读不成（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
            return out
        out["scanned"] = len(rows)
        want = str(owner or "")
        # 先按父归组一趟：原先外层每换一个父就把整张台账再扫一遍挑自己的子行
        # （父数 × 全表）。归组只改"从哪儿取"，桶内顺序仍是台账顺序。
        by_parent: dict[str, list[Mapping[str, Any]]] = {}
        for r in rows:
            pid = str(r.get("parent_task_id") or "")
            if pid:
                by_parent.setdefault(pid, []).append(r)
        owners = [want] if want else sorted(by_parent)
        out["owners"] = list(owners)
        bad: list[str] = []
        got: list[dict[str, Any]] = []
        for own in owners:
            known, bad_hist = self._roster_history(own)
            bad.extend(f"{own}：{x}" for x in bad_hist)
            # 认边落痕写在父那一行上（`Conductor.note_edge_release` 的落点），不在子行：
            # 81 的 `t-000106` 那一条是 `t-000016.inputs` 里的 `edge-released:t-000106#1`。
            parent_row = self._task_row(rows, own)
            refusals: dict[str, dict[str, Any]] = {}
            try:
                ref = registration_refusals(self.root, owner=own)
            except Exception as exc:  # noqa: BLE001 —— 读不成按坏行处理（fail-closed）
                ref = {"checked": False, "items": [],
                       "bad": [f"拒绝流水读不成（{type(exc).__name__}: {exc}）"]}
            bad.extend(f"{own}：{x}" for x in (ref.get("bad") or []))
            for item in ref.get("items") or []:
                tid = str(item.get("task_id") or "")
                if tid:
                    refusals[tid] = item
            holders = self._name_holders(own) if refusals else {}
            for row in by_parent.get(own, ()):
                if not ran_but_unnamed(row, known):
                    continue
                tid = str(row.get("task_id") or "")
                refusal = refusals.get(tid) or {}
                asked = str(refusal.get("requested_name") or "")
                held = dict(holders.get(asked) or {}) if asked else {}
                if held:
                    hrow = self._task_row(rows, str(held.get("task_id") or ""))
                    held["task_status"] = str(hrow.get("status") or "")
                    held["task_outcome"] = str(hrow.get("outcome") or "")
                arts = [str(a) for a in (row.get("artifacts") or []) if str(a)]
                got.append({
                    "task_id": tid,
                    "role": str(row.get("role") or ""),
                    "parent_task_id": own,
                    "status": str(row.get("status") or ""),
                    "outcome": str(row.get("outcome") or ""),
                    "started_at": str(row.get("started_at") or ""),
                    "ended_at": str(row.get("ended_at") or ""),
                    "artifacts": arts,
                    "artifacts_missing": [a for a in arts if not self._artifact_on_disk(a)],
                    "edge_released": self._edge_released(parent_row, tid),
                    "requested_name": asked,
                    "refusal_code": str(refusal.get("refusal_code") or ""),
                    "held_by": held or None,
                })
        got.sort(key=lambda x: (x["parent_task_id"], x["task_id"]))
        out.update({"rows": got, "count": len(got), "bad": bad})
        if bad:
            out["reason"] = (f"名册 / 拒绝流水有 {len(bad)} 处读不出来 ⇒ 这一格不许当成"
                             f"「只有 {len(got)} 个」（读不全不是查过了）")
            return out
        out["checked"] = True
        return out

    def _artifact_on_disk(self, rel: str) -> bool:
        """台账里那一格产物在不在盘上（相对路径按工作区根解析）。"""
        text = str(rel or "")
        if not text:
            return False
        p = Path(text)
        if not p.is_absolute():
            p = Path(self.root).joinpath(text)
        try:
            return p.is_file()
        except OSError:
            return False

    @staticmethod
    def _edge_released(row: Mapping[str, Any], task_id: str) -> bool:
        """父那一行的 `inputs` 里有没有认掉这条边（`edge-released:<子号>#<n>`）。

        落点在父行（`Conductor.note_edge_release` 写的是派活方那一行），所以调用方
        传进来的必须是父行 —— 传子行会恒为 False（81 的 `t-000106` 就是这么验的）。
        """
        want = f"edge-released:{task_id}"
        return any(str(x).startswith(want) for x in (row.get("inputs") or []))

    def _children_left_behind(self, tid: str) -> dict[str, Any]:
        """销 `tid` 之前：它名下还有哪些"只有它这一个父能销"的名册项。

        返回 `{"checked","rows":[{"id","name","role"}],"reason"}` —— 三态：
        `checked=False` 是"读不成"（调用方一律 fail-closed 不销），空 `rows` 才是
        "一个都没落下"（那是查过了的结论）。

        ## 为什么读名册而不读台账
        能被销的对象只有名册项：`resolve_down` 只认名册名，`conductor.retire_child`
        也只用名册名指称。所以"孤儿"的精确定义就是"还在这个父的名册上、没销号的那几个"
        —— 台账里有行而名册里没名字的那一类（`unrostered`）本来就没有名字可销，
        它在工具那一侧已经逐条点名，不归这一闸管。

        ## 为什么读折叠后的 `retired` 而不是销号名单文件
        `retire` 写盘是"先台账、再名册"（那一处的注释写了为什么），名册事件的
        `retire` 那一行与销号名单是同一笔的两次落盘。读折叠状态就是读"这一项现在
        算不算销过"，而级联"先深后浅"靠的正是这个格子在轮到父时已经变真。
        """
        out: dict[str, Any] = {"checked": True, "rows": [], "reason": ""}
        try:
            kids, bad = self.roster_rows(tid)
        except Exception as exc:  # noqa: BLE001 —— 读侧自己炸了也是"没读成"
            out["checked"] = False
            out["reason"] = f"{type(exc).__name__}: {exc}"
            return out
        if bad:
            out["checked"] = False
            out["reason"] = f"它名下名册有 {len(bad)} 行读不出来"
            return out
        for kid in kids:
            if bool(kid.get("retired")):
                continue
            name = str(kid.get("name") or "")
            out["rows"].append({"id": str(kid.get("task_id") or ""), "name": name,
                                "role": str(kid.get("role") or "")})
        return out


def _clip_text(text: str, limit: int) -> str:
    """剪一段可读的正文（多余部分写清"还有多少字没进来"，不许静默截断）。"""
    body = str(text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit] + f"…（还有 {len(body) - limit} 字没进来，全文用 manuscripts.read 读）"
