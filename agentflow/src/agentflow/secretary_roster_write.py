# -*- coding: utf-8 -*-
"""秘书的名册写口与名字身份（从 secretary.py 的 U06+U05 逐字搬出）。

我保证哪条不变式：被拒也是一条有落盘的決定；名字是身份，用过的名字永不回收。

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

from .secretary_axis import (  # noqa: F401 — 这些名字由 secretary_axis 定义
    ran_but_unnamed,
)

from .secretary_inbox import (  # noqa: F401 — 这些名字由 secretary_inbox 定义
    _task_text,
    brief_from_task,
)

from .secretary_ledger import (  # noqa: F401 — 这些名字由 secretary_ledger 定义
    _roster_guarded,
    append_jsonl,
    refusals_path,
    roster_index_path,
    roster_path,
    roster_pending,
)

from .secretary_roster_read import (  # noqa: F401 — 这些名字由 secretary_roster_read 定义
    registration_refusals,
)

from .secretary_time import (  # noqa: F401 — 这些名字由 secretary_time 定义
    _now_iso,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    BRIEF_MAX,
)


class RosterWriteMixin:
    """名册写口 + 名字身份（从 secretary.py 搬出的混入类）。"""

    def _used_names(self, owner: str) -> dict[str, str]:
        """该父名下"用过的所有名字"：名字 → 角色（含已收口、已销号、只在对照表里的）。

        三份盘上事实的并集，一处都不许漏：
        - 名册正文 `<父>.jsonl`（折叠后的一项一条：这是名册项的正文来源）；
        - 对照表 `<父>-index.jsonl` 的每一条调用记录里的 `name`（名册正文缺行时，
          名字只活在这里 —— D-66 的现场就是那个形态）；
        - 销号名单 `<父>-retired.jsonl`（销号的名字仍然"用过"，绝不回收）。

        为什么发号与占用判断都必须读这三份（业主 2026-10-24 的最终口径）：
        「如果一个子代理（例如 G1）被销号，且有 G2，再派 G 时追加写成 G3（不可复用 G1）」
        —— 只读正文会把"正文里没有、但确实用过"的名字算成空号，于是同一个名字被发给
        两个不同的子代理。名字是身份，用过的名字就不再是空号。
        """
        out: dict[str, str] = {}
        rows, _bad = self.roster_rows(owner)
        for row in rows:
            name = str(row.get("name") or "")
            if name:
                out.setdefault(name, str(row.get("role") or ""))
        index, _bad2 = self.roster_index(owner)
        for row in index:
            name = str(row.get("name") or "")
            if name:
                out.setdefault(name, str(row.get("role") or ""))
        for name in self._retired_used(owner):
            out.setdefault(name, "")
        return out

    def _roster_bindings(self, owner: str) -> tuple[list[tuple[str, str]], list[str]]:
        """“哪个号绑过谁”的全部历史：正文 `add` 行 ∪ 对照表 `bind` 行，按文件序。

        返回 `([(task_id, name)], 坏行)`。这是这一份历史的唯一解析器：两个读法
        （:meth:`_roster_history` 的"号 → 名字"、:meth:`_bound_task_ids` 的"名字 → 全部号"）
        都从它派生。为什么必须只有一处（`draft/151` 三-5）：这两处分别决定
        “自愈会不会把已登记的号再补一次”与“销号漏不漏号”，两个后果都不可逆；而两份
        逐字相同的解析器今天给出相同答案，改一处不会有任何判据变红。

        不读任何折叠视图：`_fold_index` 只留每个名字最新那条 `bind`，于是"一个名字接过
        的第二件活"会把第一件活从已知集里挤出去 —— 自愈据此把已经登记过的行再补一次
        （`draft/149` §4.5 的机制 B，零并发即可复现）。
        """
        from . import jsonlfile as JF

        body, bad_body = JF.read_jsonl(roster_path(self.root, owner))
        index, bad_index = JF.read_jsonl(roster_index_path(self.root, owner))
        rows: list[tuple[str, str]] = []
        for r in body:
            if str(r.get("kind") or "") != "add":
                continue
            tid = str(r.get("task_id") or "")
            if tid:
                rows.append((tid, str(r.get("name") or "")))
        for r in index:
            if str(r.get("kind") or "") != "bind":
                continue
            tid = str(r.get("task_id") or "")
            if tid:
                rows.append((tid, str(r.get("name") or "")))
        return rows, list(bad_body) + list(bad_index)

    def _roster_history(self, owner: str) -> tuple[dict[str, str], list[str]]:
        """这个父名下「这个号历史上登记给了谁」：全部 `add` 行 ∪ 全部 `bind` 行的 `task_id` 并集。

        返回 `({task_id: name}, 坏行)`；首个名字胜（:meth:`_roster_bindings` 的顺序）。
        写侧为什么读它（而不是读某个折叠项）：唯一性判据必须读全历史。`draft/150`
        §5.1-① 的读数：116/881 个名册项在"正文的号"与"对照表的当前号"之间分叉，
        拿任一份折叠视图当已知集都会把另一份判成"不存在"。
        """
        rows, bad = self._roster_bindings(owner)
        out: dict[str, str] = {}
        for tid, name in rows:
            out.setdefault(tid, name)
        return out, bad

    def _bound_task_ids(self, owner: str, name: str) -> list[str]:
        """这个名字绑过的全部号（正文 `add` 行 ∪ 对照表 `bind` 行，按出现顺序去重）。

        销号要标死的不是"当前号"而是这一格：复用是合法的一等功能，一个名字接过
        N 件活就有 N 个号；只写最后那条 `bind` 会让早先的号在唤醒闸那里仍读成
        "没销号"（`draft/150` §5.1-③ 的读数 H：`wake(t-000002)` 仍 `started=true`）。
        历史从 :meth:`_roster_bindings` 来（同一处解析；这里只做按名过滤）。
        """
        want = str(name or "")
        if not want:
            return []
        rows, _bad = self._roster_bindings(owner)
        out: list[str] = []
        for tid, who in rows:
            if who == want and tid not in out:
                out.append(tid)
        return out

    @_roster_guarded
    def roster_refusal_note(self, *, owner: str, task_id: str, name: str = "",
                            refusal_code: str = "", problem: str = "") -> tuple[bool, str]:
        """把"这一号被写口拒了"落成一条可跨进程读到的流水（业主 2026-11-02 的裁定）。

        写侧为什么必须做这件事：拒绝的那一刻名册三份一个字节都没写，于是"被拒过"这个
        事实在盘上原本只活在调用方的 `roster_problem` 里（而它随进程消失）。没有这条
        流水，收口兜底（`roster_repair`）就把这个号当成"漏登记的孤儿"补成新名字 ——
        等于把一次有记录的拒绝悄悄改写成一个子节点（`temp/probe_h11_leftovers.py` 的
        L 读数）。返回 `(写成了没有, 没写成的理由)`；写不成不抛（拒绝本身仍要如实交回）。
        """
        return append_jsonl(refusals_path(self.root, owner),
                            {"kind": "refused", "owner": str(owner),
                             "task_id": str(task_id),
                             "requested_name": str(name or ""),
                             "refusal_code": str(refusal_code or ""),
                             "problem": str(problem or ""), "at": _now_iso()})

    def _refused_task_ids(self, owner: str) -> tuple[set[str], list[str]]:
        """这个父名下"被写口拒过"的全部号 ⇒ `(号集合, 坏行)`（三态：坏行非空 ⇒ 不许当成没被拒）。

        坏行要不要 fail-closed：要。把它读成"没有拒绝记录"会让收口兜底把被拒的号补成新名字
        —— 这一步不可逆；而"这一份流水读不出来所以这次不补"是可逆的（补一次下回还有机会）。
        """
        from . import jsonlfile as JF

        rows, bad, state = JF.read_jsonl_state(refusals_path(self.root, owner))
        out: set[str] = set()
        for r in rows:
            tid = str(r.get("task_id") or "")
            if tid:
                out.add(tid)
        bad = list(bad)
        if state == "unreadable" and not bad:
            bad = ["拒绝流水读不出来（这一格不是「没人被拒」）"]
        return out, bad

    def _retired_used(self, owner: str) -> list[str]:
        """销号名单里的名字（"扫已销号的名字"这一步单独一处，判据可以把它打桩成跳过）。

        走 :meth:`retired_ledger`（写侧的分片名就是"我这个父"，所以 `trusted_shard=True`）：
        `bad` / `unattributable` 都在这一次的返回值里（`checked` 跟着它们变假）——"这一格
        读不全"是一个读得出来的事实，而不是一个被吞掉的返回值。本方法只取名字那一半；
        要"读不全"的调用方直接读那个字典。
        """
        got = self.retired_ledger(owner, trusted_shard=True)
        return [str(r.get("name") or "") for r in (got.get("rows") or [])
                if str(r.get("name") or "")]

    def next_name(self, owner: str, role: str) -> tuple[str, str]:
        """下一个可用的本地名（`<角色><序号>`；用过的名字绝不回收）。返回 `(名字, 问题)`。

        序号 = 该 owner 名下该角色"用过的最大序号 + 1"。"用过"包括活跃、已收口、
        已销号，以及只在对照表里留下调用记录的名字（见 :meth:`_used_names`）——
        这正是业主 2026-10-24 的最终口径：「G1 被销号，且有 G2，再派 G 时追加写成
        G3（不可复用 G1）」。
        """
        used = self._used_names(owner)
        seen = []
        for name in used:
            if name.startswith(role) and name[len(role):].isdigit():
                seen.append(int(name[len(role):]))
        return f"{role}{max(seen, default=0) + 1}", ""

    def _reuse_refusal(self, owner: str, name: str) -> tuple[str, str]:
        """`reuse=<名>` 这个目标能不能接活：`("", "")` = 能，否则是 `(一句受控拒绝的理由, 理由码)`。

        判据只有一条（业主 2026-10-24 的最终口径）："在册且未销号"就能再接活。
        「已收口子代理可再接收活，但已销号不可用」——
        - 收口（上一件活已交差、状态 done/ended，但名册项还在册）⇒ 只是闲下来了，
          可以再接一件活；
        - 销号（名册项标了 retired、名字进了销号名单）⇒ 这个子代理退场了，名字永久
          不复用（`reuse` 指向它一律受控拒绝）。

        理由码（2026-11-02 补，三态：父要能机器判"是哪种不许"）：
        - `member_retired`：这个名字销过号（与按名寻址那一档同一个词）；
        - `not_in_roster`：名册里根本没有这个名字。
        在此之前这两档只有人话、没有码，而 `Conductor._register_roster` 恰恰拿
        "有没有码"当"要不要跑兜底自愈"的开关 ⇒ 这两档拒绝之后那条子行会被自愈
        按新名字补进名册（`temp/probe_h11_leftovers.py` 的 H / I 读数：等于换个
        地方继续静默改名）。码在这里给全，那条开关才关得上。

        这一处刻意单独成一个方法：判据把它打桩成"只要在册就行"⇒ 销号那一档必须红；
        打桩成"只认活跃任务"⇒ 收口那一档必须红（`tests/test_roster_ownership_...`）。
        """
        if not self._name_exists(owner, name):
            return (f"名册里没有 {name} ⇒ 不猜（复用必须父先看名册）", "not_in_roster")
        if self._is_retired(owner, name):
            return (f"{name} 已销号（名字永久不复用，业主 B1）", "member_retired")
        return ("", "")

    @_roster_guarded
    def roster_add(self, *, owner: str, role: str, task_id: str, brief: str,
                   task: str = "", task_id_first: str = "", want_name: str = "",
                   reuse: str = "", surface: str = "", new: str = "") -> dict[str, Any]:
        """写口 + 拒绝留痕（真正的登记逻辑在 :meth:`_roster_add`，两半在同一个临界区里）。

        为什么单包这一层（业主 2026-11-02：「被拒是一次有记录的决定」）：拒绝时
        `_roster_add` 一个字节都不写，于是"被拒过"必须由写口自己在同一个 per-owner
        临界区里落一条流水（:func:`refusals_path`）—— 否则收口兜底（`roster_repair`）
        会把这个号当成"漏登记的孤儿"补成新名字，等于把一次有记录的拒绝悄悄改写成一个
        子节点（`temp/probe_h11_leftovers.py` 的 L 读数）。放在这一层而不是调用方，
        是为了让"拒了"与"记下拒了"之间没有任何时间窗。

        记录写不成不改变拒绝的结论（回执的 `problem` / `refusal_code` 逐字不变），
        只把"以后可能被收口兜底补上"写进回执的 `note`。
        """
        got = self._roster_add(owner=owner, role=role, task_id=task_id, brief=brief,
                              task=task, task_id_first=task_id_first,
                              want_name=want_name, reuse=reuse, surface=surface, new=new)
        problem = str(got.get("problem") or "")
        if not problem:
            return got
        ok, why = self.roster_refusal_note(
            owner=owner, task_id=task_id, name=str(got.get("name") or ""),
            refusal_code=str(got.get("refusal_code") or ""), problem=problem)
        if ok:
            return got
        out = dict(got)
        out["note"] = (f"拒绝记录没写成（{why}）"
                       "⇒ 收口兜底可能把这一条补成新名字")
        return out

    def _roster_add(self, *, owner: str, role: str, task_id: str, brief: str,
                    task: str = "", task_id_first: str = "", want_name: str = "",
                    reuse: str = "", surface: str = "", new: str = "") -> dict[str, Any]:
        """名册登记（增那一支）：`{"name","role","task_id","brief","brief_written","problem"}`。

        ## 两个入口，语义不同
        名册项是"一个常驻子代理"的身份（名字 / 角色 / 简介 / 读写面），不是一件活。
        一个子代理可以接好几件活，所以写入侧只有两条路：

        - `reuse=<名>`："同一个子代理再接一件活"。名册项一个字不动，只在对照表里
          追加一条调用记录（哪一件活落到了这个名字上）。合法目标 = 在册且未销号
          （收口了也可以再接活；已销号 ⇒ 受控拒绝，见 :meth:`_reuse_refusal`）。
        - `new=<角色>`（或 `want_name=<名>`，或两样都不给）："新建一个同类子代理"。
          名字由秘书发号（:meth:`next_name`）：用过的最大序号 + 1，用过的名字绝不回收
          （含已销号的）；`want_name` 点了一个用过的名字 ⇒ 受控拒绝并写清它是活跃 /
          已收口 / 已销号。要再派一个同类子代理时用这一支，不要拿旧名字挂新活。

        两个入口不许混着给（`reuse` 与 `new` / `want_name` 同时给 ⇒ 受控拒绝：那是
        两句互相矛盾的话，猜哪一句都会替调用方改主意）。

        ## 受控拒绝带机器码
        拒绝时回执多一格 `refusal_code`（成功回执逐键不变），取值只有这五个，一档一个语义：
        `name_taken`（这个名字用过：活跃 / 已收口 / 已销号）、`task_id_reused`（同一个号
        已经登记在别的名字名下）、`task_id_retired`（这个号销过号，不许再 add / bind）、
        `member_retired`（`reuse` 指向一个已销号的名字）、`not_in_roster`（`reuse` 指向
        名册里没有的名字）。前两个是 `want_name` / 新号两支的闸，后三个是 `reuse` 支的闸。
        父据此决定"换一个号 / 换一个名字 / 停止"，框架不替它改主意 ——
        `Conductor._register_roster` 也按这一格决定"不跑兜底自愈"。

        ## 盘上落什么（`task_id` 是调用流水读数，不是归属键）
        - 名册正文 `<父>.jsonl`：`kind="add"` 一行建项（名字、角色、简介、面、创建时间）；
          `kind="retire"` 一行销号；
        - 对照表 `<父>-index.jsonl`：`kind="bind"` 一条调用记录（名字 + 这一件活的编号
          + 时间）。`task_id` / `task_name_first` 这类字段只回答"这一条/这一项是为哪件
          活落的"，不回答"这个名册项是谁" —— 名册项的身份是 `owner` + `name`
          （读侧按名字归组：一个节点 + N 件活，见 `webui.readers.roster_face`）。

        ## 简介
        `brief` 缺失（空 / 纯空白）而 `task` 非空 ⇒ 秘书代写：由 `brief_from_task` 从
        任务原文派生一句（确定性、不调模型、不花钱，≤60 字、单行），登记行里那一格记
        `brief_source="secretary"`、返回 `brief_written=True`；父给的那一句记
        `brief_source="parent"`、`brief_written=False` —— 不许静默冒充"父给的"。
        `brief` 与 `task` 都空 ⇒ 拒（那句话是退役时认人的唯一依据，秘书不替它编）；
        父给的 `brief` 超长 / 多行 ⇒ 照旧拒（"超长属于内容，秘书不替它删"）。
        """
        text = str(brief or "").strip()
        source = "parent"
        if not text:
            text = brief_from_task(task)
            source = "secretary"
        if not text:
            return {"name": "", "role": str(role), "task_id": str(task_id),
                    "brief": "", "brief_written": False,
                    "problem": "没给一句任务简介（它进名册：退役时读的人靠它认人）"}
        if len(text) > BRIEF_MAX or "\n" in text:
            return {"name": "", "role": str(role), "task_id": str(task_id),
                    "brief": text, "brief_written": source == "secretary",
                    "problem": "任务简介必须是单行、不超过 60 字（超长属于内容，秘书不替它删）"}
        given = [key for key, value in
                 (("reuse", reuse), ("new", new), ("want_name", want_name)) if str(value or "")]
        if len(given) > 1:
            return {"name": str(reuse or want_name or ""), "role": str(role),
                    "task_id": str(task_id), "brief": text,
                    "brief_written": source == "secretary",
                    "problem": (f"{'、'.join(given)} 不能同时给：reuse 是「同一个子代理"
                                "再接一件活」，new / want_name 是「新建一个同类子代理」"
                                " —— 两句话互相矛盾，秘书不替调用方猜哪一句算数")}
        if str(new or "") and str(new) != str(role):
            return {"name": "", "role": str(role), "task_id": str(task_id), "brief": text,
                    "brief_written": source == "secretary",
                    "problem": f"new={new} 与 role={role} 对不上（新建的是哪个角色就写哪个）"}
        at = _now_iso()
        if reuse:
            name = str(reuse)
            refusal, refusal_code = self._reuse_refusal(owner, name)
            if refusal:
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "brief": text, "brief_written": source == "secretary",
                        "refusal_code": refusal_code, "problem": refusal}
            # ⑥（业主 2026-11-02）：已销号的号不许再绑给任何名字。名字那一侧封死
            # 而号那一侧敞开，会让"名字永久不复用"变成一句空话 —— 旧号换个名字又活了。
            retired_by = self._retired_name_of_task_id(owner, str(task_id))
            if retired_by:
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "brief": text, "brief_written": source == "secretary",
                        "refusal_code": "task_id_retired",
                        "problem": (f"{task_id} 已经销号（{retired_by}）⇒ 受控拒绝"
                                    "（task_id_retired）：已销号的号不许再绑活，也不许"
                                    "再登记给别的名字（否则它会变成永远销不掉的孤儿）")}
            # ④：一个号只属于一个名字。同一个号已经绑在别人身上 ⇒ 这不是"这件活
            # 落到这个名字上"，而是"两个名字指向同一个子代理"—— 读侧会静默取第一个。
            history, bad_hist = self._roster_history(owner)
            if bad_hist:
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "brief": text, "brief_written": source == "secretary",
                        "problem": (f"名册/对照表有 {len(bad_hist)} 行读不出来 ⇒ 不绑"
                                    f"（免得把同一个号绑给两个名字）：{bad_hist[0]}")}
            owner_name = str(history.get(str(task_id)) or "")
            if owner_name and owner_name != name:
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "brief": text, "brief_written": source == "secretary",
                        "refusal_code": "task_id_reused",
                        "problem": (f"{task_id} 已经绑在 {owner_name} 名下 ⇒ 受控拒绝"
                                    "（task_id_reused）：一个号只属于一个名字（要接这件活"
                                    "就 reuse 那个名字）")}
            bind: dict[str, Any] = {"kind": "bind", "owner": owner, "name": name,
                                    "role": str(role), "task_id": str(task_id), "at": at}
            if str(task or "").strip():
                # 任务原文跟着这一件活落盘（业主 2026-10-27：等子代理的目的自动用它填）。
                bind["task_text"] = _task_text(task)
            if source == "secretary":
                # 复用支不写名册项 ⇒ 这一次代写的那句话也得留痕（否则"谁写的"就丢了）。
                # 只在代写时补这两格：父给的那一支落盘逐字不变。
                bind.update({"brief": text, "brief_source": "secretary"})
            ok, why = append_jsonl(roster_index_path(self.root, owner), bind)
            if not ok:
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "problem": f"对照表没写成：{why}"}
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "brief": text, "brief_written": source == "secretary", "problem": ""}

        if want_name:
            name = str(want_name)
            if self._name_exists(owner, name):
                status = ("已销号" if self._is_retired(owner, name) else "已收口或还在用")
                problem = (f"{name} 已经用过（{status}）⇒ 受控拒绝（name_taken）："
                           "用过的名字不再发给另一个子代理（要新建一个同类子代理，"
                           "让秘书按序号发下一个未用名，或显式给一个没用过的名字）")
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "problem": problem, "refusal_code": "name_taken"}
        else:
            name = ""
        # ⑥ 已销号的号不许再登记（名字那一侧封死，号那一侧若不封：换个新名字重新 add
        # 成功，于是这个新名字永远销不掉、成为永久孤儿，父也永远不许销号）。
        retired_by = self._retired_name_of_task_id(owner, str(task_id))
        if retired_by:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "refusal_code": "task_id_retired",
                    "problem": (f"{task_id} 已经销号（{retired_by}）⇒ 受控拒绝"
                                "（task_id_retired）：已销号的号不许再登记给任何名字"
                                "（否则它会变成一个永远销不掉的孤儿项）")}
        # ④ 同一个号不许出现在两条 `add` 行。判据读全历史
        # （全部 add ∪ 全部 bind），不读折叠视图 —— 后者会把复用过的旧号判成"没见过"。
        history, bad_hist = self._roster_history(owner)
        if bad_hist:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": (f"名册/对照表有 {len(bad_hist)} 行读不出来 ⇒ 不登记"
                                f"（免得重名或重号）：{bad_hist[0]}")}
        owner_name = str(history.get(str(task_id)) or "")
        if owner_name:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "refusal_code": "task_id_reused",
                    "problem": (f"{task_id} 已经登记在 {owner_name} 名下 ⇒ 受控拒绝"
                                "（task_id_reused）：同一个号不许出现在两条 add 行"
                                "（要接这件活就 reuse 那个名字）")}
        if not want_name:
            name, problem = self.next_name(owner, role)
            # 死分支·契约出口：`next_name` 今天的第二个分量恒为空串（它自己的 docstring 与
            # `tests/test_no_dead_branch_on_a_field_that_is_always_empty.py` 钉着这件事），
            # 所以这一支永远不执行。留着是给"将来发号器能拒"的显式出口 —— 与
            # `roster_repair` 里那一支是同一件事：删/留必须成对，不许只改一处。
            if problem:
                return {"name": "", "role": str(role), "task_id": str(task_id),
                        "problem": problem}
        # S1n（业主 T23 / B2）：造一个新子代理时同时预订一个读写面（父可以点名要哪个槽位）。
        # 拿不到面 ⇒ 受控拒绝（不许先给名字后没有面：那会造出一个"能说话但不能干活"的项）。
        got_surface = self.surface_alloc(owner=owner, want=str(surface or ""), name=name)
        if got_surface.get("problem"):
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": f"读写面没定下来：{got_surface['problem']}"}
        bind_add: dict[str, Any] = {"kind": "bind", "owner": owner, "name": name,
                                    "role": str(role), "task_id": str(task_id), "at": at,
                                    "first": True}
        add_row: dict[str, Any] = {"kind": "add", "owner": owner, "name": name,
                                   "role": str(role), "task_id": str(task_id),
                                   "first_task_id": str(task_id_first or task_id),
                                   "brief": text, "brief_source": source,
                                   "surface": str(got_surface.get("slot") or ""),
                                   "at": at}
        if str(task or "").strip():
            # 任务原文（≤200 字，单行）：`clock` 的"目的自动填"读它（业主 2026-10-27）。
            # 落两份：名册项那一行（`add`）与对照表那一行（`bind`）—— 前者是这一项
            # 为哪件活建的，后者是这件活归了谁；读侧两条都能找到同一句原文。
            bind_add["task_text"] = _task_text(task)
            add_row["task_text"] = _task_text(task)
        ok, why = append_jsonl(roster_index_path(self.root, owner), bind_add)
        if not ok:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": f"对照表没写成：{why}"}
        ok2, why2 = append_jsonl(roster_path(self.root, owner), add_row)
        if not ok2:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": f"名册没写成（对照表那一行已经落了 ⇒ 读侧会报'半份登记'）：{why2}"}
        return {"name": name, "role": str(role), "task_id": str(task_id),
                "brief": text, "brief_written": source == "secretary",
                "surface": str(got_surface.get("slot") or ""), "problem": ""}

    def open_solo_entry(self, *, task_id: str, task: str = "", brief: str = "") -> dict[str, Any]:
        """给"用户指定单条执行"开一条名册行与一个读写面槽位（`owner` = 它自己的任务号）。

        ## 为什么需要这一格

        形式化验证成本极高 ⇒ 在全部研究和论文落定之后，用户指定有形式化验证需求时，
        要一条才做一条。而只有 B 可以派 L，所以这一格今天不只在 `run-agent L` 上用到：
        被 B 派的那一趟走父的秘书登记，而用户指定单条起的那一趟没有父，走本方法。
        "单条执行时同样有台账号、名册行、读写面"—— 那三样在"被父派活"那一档是由父的秘书在
        `Conductor._register_roster` 里落的，单条执行时没有父，于是没有任何人落它们。

        这里补的就是那一个缺失：把"这一趟"登记进它自己名下的名册（`owner` 与
        `task_id` 都是这一趟的绝对编号），并从池里取一个槽位。语义上它不是"父子关系"，
        而是"这一趟的名册里只有我一个"—— 退役、寻址、读写面切割读的都是同一份行，
        与派活那一档逐字同形（键集由 `roster_add` 决定，本方法不另写一份）。

        fail-open：拿不到面 / 登记被拒 ⇒ 返回 `problem`，不抛（少一份名册不许带走这一趟）。
        """
        owner = str(task_id or "").strip()
        if not owner:
            return {"name": "", "surface": "", "problem": "没有任务号 ⇒ 名册上没地方登记"}
        got = self.roster_add(owner=owner, role=str(self.role), task_id=owner,
                              brief=str(brief or ""), task=str(task or ""))
        return {"name": str(got.get("name") or ""),
                "surface": str(got.get("surface") or ""),
                "problem": str(got.get("problem") or "")}

    @_roster_guarded
    def roster_repair(self, *, owner: str,
                      named: list[dict[str, Any]] | None = None) -> tuple[int, str, list[str]]:
        """补登记（自愈）：把"台账里有、名册里没有"的代理行补上。

        返回 `(补了几条, 问题, 因为"在飞"而跳过的号)`。第三格是号清单而不是计数：
        "因为还没登记所以不补"必须在读数上看得见，否则它下次真变成"该补没补"时，
        没有任何入口能查出是哪个号、为什么被跳过。

        `named` 是"补成了谁"的出参（调用方给的清单，本方法往里追加；不给就不记）：
        补名之后两个读者（:meth:`retire` 的回执、`conductor` 的派活回执）都要说清"它
        当初点名要什么、现在叫什么"。此前这件事存在实例字段 `self.last_repair_named`
        上，读的人必须"刚跑完就立刻读"——那是构造之后补写的隐式上下文；出参把它变成
        调用方自己的一份读数，跨模块搬运时不会一半写、一半读（2026-11-20 SECSPLIT 前置）。

        只在写路径被调用（查只报不修）。补的时候按 `task_id` 升序，整段（读历史 → 判 →
        两笔 append）在 `_roster_section` 的 per-owner 临界区里，于是两个并发修复既不会
        重复分配、也不会各补一行；名字在锁内由 `next_name` 按已用最大序号推。

        ## 在飞集合：分得清"还没登记"与"从没登记"

        兄弟行竞态的形态：A 已落台账行、还没走到自己的 `roster_add`，B 在登记之后跑本方法，
        把 A 当成漏行补了名；A 随后自己的登记撞 `task_id_reused`。`_roster_section` 只串行化
        "写名册"，串行化不了"台账行已落、名册还没落"这个窗口 ⇒ `todo` 再并上
        :func:`roster_pending`。

        读序是判据的一部分：必须先读 `cond._tasks()`、后读在飞集合 —— 标记在 `tasks`
        事务提交之前落进集合，"看得见那一行"的读者之后一定看得见标记；两处一对调这条保证
        就没了，而所有正题仍会是绿的（负控钉在
        `tests/test_sibling_registration_race_is_not_backfilled.py`）。

        ## 只补"该有名字"的号（判据是"没跑过的号"，不是"被拒过的号"）

        ① 派活闸拒掉的号（`outcome="refused"`）：永远不补 —— 补了就是 phantom 名册项；
        ② 名册写口拒过的号（`refusals/<父>.jsonl` 有记录）：只有"真跑过"时才补。
           "这次派活被拒"与"这次名册登记被拒"是两件事，后者是部分拒绝
           （派活成功、子代理真跑、只有名字没落）；
        ③ 从没被拒过的孤儿（实例分派 / 队列入账 / 更早的形态）：老口径照补 —— 不许因为
           ② 的改动把它一起关掉。这一档只由 `roster_pending` 挡在飞、不要求 `ended_at`：
           一条 `running` 却没有结束时刻的行是"不知道跑没跑"，而"父按名销不掉它"
           （整棵树收不了工）比"补了一个可能没跑完的号"更不可逆。

        "真跑过"的判据不另写一份：就是模块级的 :func:`ran_but_unnamed`（收工门与网页那一格
        用的是同一个函数），用同一份 `status` / `outcome` / `ended_at` 三格。

        ## 补名之后的留痕

        add 行多三格：`named_after_run`（是不是跑过之后才补的名）、`requested_name`
        （它当初点名要的那个，原样保留 —— 那是"它曾经想叫 E2"的记录）、`refusal_code`
        （哪一档拒的）。名册是 JSONL、没有 schema 契约，加键不改旧键。回执逐条说清
        "你点的 E2 被拒，它叫 E4"；这两处读的是同一份出参：调用方传进来的 `named`。
        """
        cond = self._conductor()
        if cond is None:
            return 0, "没有 store ⇒ 读不到台账，补不了", []
        try:
            rows = [r for r in cond._tasks()
                    if r.get("parent_task_id") == owner and not str(r.get("kind") or "")]
        except Exception as exc:  # noqa: BLE001
            return 0, f"台账读不成（{type(exc).__name__}: {exc}）", []
        # 已知集 = 全部 `add` 行 ∪ 全部 `bind` 行的 task_id 并集。
        # 读 `roster_index` 的折叠视图不行：一个名字接过第二件活之后，第一件活从
        # `known` 里消失 ⇒ 自愈把已经登记过的行再补一次（零并发可复现）。
        known, bad = self._roster_history(owner)
        if bad:
            return 0, f"名册/对照表有 {len(bad)} 行读不出来 ⇒ 不补（免得重名）", []
        refused, bad_ref = self._refused_task_ids(owner)
        if bad_ref:
            return 0, f"拒绝流水有 {len(bad_ref)} 行读不出来 ⇒ 不补（免得把被拒的号补成新名字）", []
        # 拒绝流水里的那几格（`requested_name` / `refusal_code`）：只用来给补出来的 add 行
        # 留痕，不参与判据（判据读的是 `_refused_task_ids` 那份号集合，同一个文件）。
        asked_of: dict[str, dict[str, Any]] = {}
        try:
            for item in (registration_refusals(self.root, owner=owner).get("items") or []):
                rtid = str(item.get("task_id") or "")
                if rtid:
                    asked_of[rtid] = item
        except Exception:  # noqa: BLE001 —— 读不成只是少两格留痕（判据已由 bad_ref 先把过）
            asked_of = {}
        # 在飞集合：读序在 `cond._tasks()` 之后（见 docstring，判据钉着这一条）。
        pending = roster_pending(self.root, owner)
        cand: list[str] = []
        for r in rows:
            tid = str(r.get("task_id") or "")
            if not tid or tid in known:
                continue
            # ① 闸拒的号：永远不补（1cdacbf6，一字不动）。
            if str(r.get("outcome") or "") == "refused":
                continue
            # ② 写口拒过的号：只有真跑过才补（丁）；没跑过的照样不补（d9ebb7fe 的实质）。
            if tid in refused and not ran_but_unnamed(r, frozenset()):
                continue
            cand.append(tid)
        skipped = sorted(tid for tid in cand if tid in pending)
        todo = sorted(tid for tid in cand if tid not in pending)
        fixed = 0
        for tid in todo:
            row = next((r for r in rows if str(r.get("task_id") or "") == tid), {})
            role = str(row.get("role") or "")
            ran = ran_but_unnamed(row, frozenset())
            asked = asked_of.get(tid) or {}
            want_name = str(asked.get("requested_name") or "")
            refusal_code = str(asked.get("refusal_code") or "")
            name, problem = self.next_name(owner, role)
            # 死分支·契约出口：与 `_roster_add` 里那一支是同一件事（`next_name` 今天恒返回
            # 空问题串）。两处必须成对：删/留都一起改，并同步
            # `tests/test_no_dead_branch_on_a_field_that_is_always_empty.py` 的登记表。
            if problem:
                return fixed, problem, skipped
            # 补出来的行也要有面（`draft/158` 二-2 的副作用）：正常 add 行走 `surface_alloc`，
            # 补登记此前不带 `surface` ⇒ 81 那 13 条补登记行 13/13 无面，正常行 52/52
            # 有面；于是那 6 个真跑过的子代理在 `surface_of` 里读到空槽、一次都没切读写面。
            # 拿不到面不带走这一次补登记（fail-open）：少一个面是"这一项干不了活"，少一条
            # 名册行是"父根本销不掉它"（79 那趟的形态）；落一个空 `surface` 与改前同形，
            # 读侧读得出"名下有项、没面"。
            got_surface = self.surface_alloc(owner=owner, name=name)
            slot = str(got_surface.get("slot") or "")
            ok, why = append_jsonl(roster_index_path(self.root, owner),
                                   {"kind": "bind", "owner": owner, "name": name, "role": role,
                                    "task_id": tid, "at": _now_iso(), "repaired": True})
            if not ok:
                return fixed, f"补登记没写成：{why}", skipped
            ok2, why2 = append_jsonl(roster_path(self.root, owner),
                                     {"kind": "add", "owner": owner, "name": name, "role": role,
                                      "task_id": tid, "first_task_id": tid,
                                      "brief": "（补登记：这一条当时没写进名册）",
                                      # 这句话是秘书写的（不是父给的）⇒ 留痕那一格照写
                                      "brief_source": "secretary",
                                      "surface": slot,
                                      # 丁的三格留痕（业主 2026-11-01）：它是不是"跑过之后才补的
                                      # 名"、它当初点名要什么（原样保留 —— 那是"它曾经想叫 E2"
                                      # 的记录）、哪一档拒的。JSONL 无 schema 契约，加键不改旧键。
                                      "named_after_run": bool(ran),
                                      "requested_name": want_name,
                                      "refusal_code": refusal_code,
                                      "at": _now_iso(), "repaired": True})
            if not ok2:
                return fixed, f"名册补写没成：{why2}", skipped
            fixed += 1
            if named is not None:
                named.append({
                    "task_id": tid, "name": name, "role": role,
                    "named_after_run": bool(ran), "requested_name": want_name,
                    "refusal_code": refusal_code, "surface": slot})
        return fixed, "", skipped

    @staticmethod
    def _task_row(rows: Iterable[Mapping[str, Any]], task_id: str) -> Mapping[str, Any]:
        """在已经读出来的台账行里找那一号（找不到回空 dict —— 名字的持有者可能是历史行）。"""
        want = str(task_id or "")
        if not want:
            return {}
        for r in rows:
            if str(r.get("task_id") or "") == want:
                return r
        return {}

    def _name_holders(self, owner: str) -> dict[str, dict[str, Any]]:
        """这个父名下「名字现在挂在谁身上」：`名字 → {name, task_id, retired, retired_task_id}`。

        口径与 `_roster_history` 同一份（`add` ∪ `bind`，首个名字胜）：名字是身份，
        一个名字只该有一个当前号。销号名单上有的再补两格 —— 81 的 `E2` 正是这一档：
        名册项 `E2/t-000030`、04:46:50 已销号 ⇒ 持有者 `retired=True`。
        """
        out: dict[str, dict[str, Any]] = {}
        rows, _bad = self._roster_bindings(owner)
        for tid, name in rows:
            if name and name not in out:
                out[name] = {"name": name, "task_id": tid, "retired": False,
                             "retired_task_id": ""}
        got = self.retired_ledger(owner, trusted_shard=True)
        for r in got.get("rows") or []:
            name = str(r.get("name") or "")
            if name in out:
                out[name]["retired"] = True
                out[name]["retired_task_id"] = str(r.get("task_id") or "")
        return out

    def _name_exists(self, owner: str, name: str) -> bool:
        """这个名字在这个父名下用过没有（名册正文 + 对照表 + 销号名单，三份都算）。

        为什么要三份（D-66）：名册正文缺行时，一个用过的名字可能只在对照表的调用
        记录里、或只在销号名单里；只读正文会把它算成空号，于是同一个名字被发给
        另一个子代理。名字是身份，"用过"是永久事实。
        """
        return str(name) in self._used_names(owner)

    def _is_retired(self, owner: str, name: str) -> bool:
        """这个名字是不是销过号（写侧的复用闸）。

        走 :meth:`retired_ledger` 而不是 `retired_names`：语义一个字不改（"读到一行
        名字对得上"就是真），但坏行 / 认不出来的行在这一次的返回值里（`checked` 跟着
        变假）。写侧的"复活"风险（`draft/145` H14：`bad` 被 `_bad` 丢掉 ⇒ 已销号的名字
        还能被 `reuse` 回来）从这里开始有了一个可读的读数；本方法仍只回那个布尔。
        """
        got = self.retired_ledger(owner, trusted_shard=True)
        return any(str(r.get("name") or "") == str(name) for r in (got.get("rows") or []))

    def _retired_name_of_task_id(self, owner: str, task_id: str) -> str:
        """这个号在销号名单里吗 ⇒ 那一行的名字（空串 = 没命中）。

        与 :meth:`_is_retired` 同一个读口（名字那一半），这一格问的是"号"那一半：
        名字可以在销号后被复用检查挡住，而号那一侧改前完全敞开（`draft/149` §1.4-④：
        已销号的号换个新名字重新登记成功 ⇒ 新名字永远销不掉 ⇒ 永久孤儿）。
        """
        tid = str(task_id or "")
        if not tid:
            return ""
        got = self.retired_ledger(owner, trusted_shard=True)
        for r in got.get("rows") or []:
            if str(r.get("task_id") or "") == tid:
                return str(r.get("name") or "")
        return ""
