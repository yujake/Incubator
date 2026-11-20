# -*- coding: utf-8 -*-
"""秘书的两段式洗/请示/确认（从 secretary.py 的 U18+U19+U23 的洗侧逐字搬出）。

我保证哪条不变式：洗不改实质；只要有差异就必须请示，且请示里带编号与指纹（同一个差异不许问两次）。

## 为什么它能单独成文件（依赖方向）

`secretary_wash` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_wash` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import schema as S
from typing import Mapping
import hashlib
import json

from .secretary_judge import (  # noqa: F401 — 这些名字由 secretary_judge 定义
    declarations_candidates,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    ACCEPT_PROPOSAL,
    OUTCOME_WASH_PROPOSED,
    PROPOSAL_KEYS,
    REJECT_PROPOSAL,
    SAME_AS_WRAPPER_CHARS,
)


class WashMixin:
    """洗/请示/确认 + 格式面洗 + 依赖步骤洗（从 secretary.py 搬出的混入类）。"""

    #: 洗格式只管派活这两个形状（`draft/90` §1.2 的格式面）：
    #: `handoff` / `message` 的 `to` 是内容面（"派给谁"一个字不许动）⇒ 只报不改。
    WASH_SHAPES: tuple[str, ...] = ("summon", "summon_many")

    #: 形状自己的键（不是 `params` 的键）：顶层折叠时要跳过它们，
    #: 否则一个恰好叫 `name` 的动作参数会把名册那一格（S1k）偷走。
    #: 两段式的确认/拒绝两个字段也在这里：它们是协议字段，既不是动作参数、
    #: 也不许被"顶层折叠"搬进 `params`（否则一次派活会带一个叫 `accept_proposal` 的参数
    #: 撞闸门，而"接受"这件事在语义上根本不是那件活的参数）。
    _SHAPE_KEYS: tuple[str, ...] = ("role", "action", "params", "brief", "name", "reuse",
                                    "input_key", "instance", "targets", "notify", "why",
                                    *PROPOSAL_KEYS)

    def wash_delegation(self, shape: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """洗一遍格式面（S1g / E5），内容面一个字不动。

        返回（三态必须分得开，这是本仓最忌折平的一处）：
        | 结局 | 返回 |
        |---|---|
        | 洗过了、本来就是受控形状 | `{"checked": True, "washed": False, "changes": []}` |
        | 洗过了、改了格式格 | `{"checked": True, "washed": True, "changes": [...]}` |
        | 这一格没洗成 | `{"checked": False, "reason": …}`（原样发出去，闸门照旧） |
        | 硬拒 | `{"checked": True, "refused": "<受控理由码>"}`（调用方一行都不落） |
        ## 可以洗什么（`draft/90` §1.2，逐条）：动作真名（`action` 不在该角色动作表里、而
        `declarations_candidates` 只给出唯一候选 ⇒ 映过去；多条 ⇒ 不猜，留给闸门拒）；`params` 键名（声明里
        没有这个键、而候选唯一 ⇒ 改名，值原样跟着走）；顶层折叠（动作声明的参数被摆在了顶层 ⇒ 收进 `params`）；
        `input_key` 归一（去空白 + 内部空白并成一个空格，它是环检测键）；`name` / `reuse` / `instance` / `role` /
        `action` 去首尾空白。一个字不许动什么（内容面）：`params` 里任何值、`role`（派给谁）、`notify` 的正文
        与主张、证据与结论 —— 只搬键、只去空白，从不把 `None`/缺键补成默认值。
        ## 硬拒只有一格（为什么这么窄）："洗不动 ⇒ 受控拒绝，一行都不落"（`draft/90` §1.2 步骤 1）落在
        `summon` 连"派给谁/做什么"都不全这一格：没有角色或没有动作时，一次派活在语义上不成立。其余"洗不动"
        （缺必填参数、参数值不对）照旧交给 `conductor` 的闸门去拒 —— 那一档今天会落一行 `refused` 并且可能转成
        "请主控代唤"（`_needs_relay`），秘书抢在它前面拒掉会把那条出路和那行证据一起弄丢。`summon_many` 不用硬拒：
        一批是 N 次派活，整批拒掉会把好的那几项一起带走（逐项 `refused` 行仍由闸门落）。为什么 `params` 只动顶层
        一层、且不深拷：噪声载荷里有自引用字典（`SELF_REF`）与 60 层深嵌套（`test_secretary_noise.py`），递归走一遍
        会当场炸掉这一次派活 —— 只搬顶层键、只去字符串空白，永远碰不到那些结构。
        """
        before = dict(payload or {})
        out: dict[str, Any] = {"checked": False, "washed": False, "refused": "",
                               "reason": "", "payload": before, "before": before,
                               "changes": []}
        if shape not in self.WASH_SHAPES:
            out["reason"] = (f"{shape} 不在洗格式的面上（派活以外只报不改："
                             "`to` 是内容面）")
            return out
        try:
            if shape == "summon_many":
                return self._wash_summon_many(before, out)
            return self._wash_one(before, out, field="")
        except Exception as exc:  # noqa: BLE001 —— 洗不动不许打断这一次派活
            out.update(checked=False, washed=False, refused="", payload=before,
                       reason=f"洗格式没跑成（{type(exc).__name__}: {exc}）⇒ 原样发出去")
            return out

    @staticmethod
    def _unique_rename(key: Any, props: Any, fixed: Mapping[str, Any]) -> str:
        """错名 → 唯一候选键名；候选不唯一 / 目标已在 `fixed` ⇒ 空串（一个字节都不动）。

        `params` 里那一支与顶层折算那一支问的是同一条判据（唯一候选、且不覆盖真值），
        原先两处各写一遍同一段 `declarations_candidates(...) + len == 1 + not in fixed`。
        """
        cand = declarations_candidates(str(key), props)
        return cand[0] if len(cand) == 1 and cand[0] not in fixed else ""

    def _wash_one(self, payload: dict[str, Any], out: dict[str, Any],
                  *, field: str, refuse: bool = True) -> dict[str, Any]:
        """洗一次派活的格式面（`field` 给了就把这一份摆在那个字段名下，用于批量）。"""
        where = f"{field}：" if field else ""
        after = dict(payload)
        changes: list[dict[str, Any]] = list(out.get("changes") or [])
        for key in ("role", "action", "name", "reuse", "instance"):
            got = after.get(key)
            if isinstance(got, str):
                stripped = got.strip()
                if stripped != got:
                    after[key] = stripped
                    changes.append({"where": field, "field": key, "why": "去首尾空白"})
        key_val = after.get("input_key")
        if isinstance(key_val, str):
            folded = " ".join(key_val.split())
            if folded != key_val:
                after["input_key"] = folded
                changes.append({"where": field, "field": "input_key", "why": "归一（空白并一个）"})
        # 角色那一格有两个写法（`role` 是派活形状的、`to` 是老调用方的）：
        # `optimize_outbound` 与 `prescreen` 都认两个 ⇒ 这里也认两个，
        # 否则一个用 `to=` 的调用方会被判成"没给角色"（真机判据当场抓出来的）。
        role = after.get("role")
        if not (isinstance(role, str) and role.strip()):
            raw_to = after.get("to")
            role = raw_to if isinstance(raw_to, str) else ""
        else:
            role = role.strip()
        raw_action = after.get("action")
        action = raw_action if isinstance(raw_action, str) else ""
        raw_params = after.get("params")
        # 2026-10-16（业主口径 S2「M 只派活」）：硬拒那一格从"没有角色或没有动作"
        # 收窄成"没有角色 或 既没有动作也没有活"。
        # 原话逐字：「一致改成 task 必填，action 不填」「action 完全不用父代理填」。
        # 真机读数（T5 第 12/13 趟）：M 六次/两次发出 `{"role":"A","task":…}`，而 `tasks`
        # 表里空动作的行 = 0 —— 全死在这一行（它不落行，所以连证据都没留下）。
        # 2026-10-16：活的写法有两处 —— 顶层的 `task`（形状/工具那一面），
        # 以及 `params["task"]`（派活那条路为了给被派者那一趟循环取用而并进去的那一份）。
        # 真机/判据现场：批量派活被拒的理由码是 `unknown_action`，而它其实写了活
        # （只是写在 `params` 里）⇒ 这一格必须两处都认，否则"派活"永远过不去。
        work = str(after.get("task") or (raw_params or {}).get("task") or "").strip()
        if not role or not (action or work):
            missing = ("角色（派给谁）" if not role
                       else ("动作（做什么）" if action else "活（做什么）"))
            # 理由码与闸门那一侧同名（`schema.REFUSAL_REASONS`）：空动作名字在
            # 闸门那里就是 `unknown_action`（红前读数见 S1g 的提交信息），这一档只是
            # "不落行"、码不改 —— 换一个码会让读了半年日志的人以为另出了一类拒绝。
            code = "unknown_role" if not role else "unknown_action"
            if refuse:
                out.update(payload=payload, changes=changes, checked=True, washed=False,
                           refused=code,
                           reason=f"{where}没给{missing} ⇒ 一次派活在语义上不成立（不落行）")
                return out
            out.update(payload=after, changes=changes, checked=True,
                       washed=bool(changes), reason=f"{where}没给{missing} ⇒ 这一项洗不了")
            return out
        spec = self._action_spec(role, action)
        table = self._action_table().get(role, [])
        note = ""
        # 2026-10-16（业主口径 S2）：`action` 为空时没有可映的动作 ⇒ 这一步跳过，
        # 不记 `note`。原先空动作会走到下面那个 `elif`，记成
        # "动作表里没有 ''（没有候选 ⇒ 不猜，留给闸门拒）" ⇒ "只派活"那一路被挂上一条
        # 无意义的格式说明（判据现场：`test_the_secretary_washes_the_format_face` 读到它）。
        if spec is None and str(action):
            close = declarations_candidates(action, table) if table else []
            if len(close) == 1:
                after["action"] = close[0]
                changes.append({"where": field, "field": "action",
                                "from": action, "to": close[0], "why": "动作真名（唯一候选）"})
                action = close[0]
                spec = self._action_spec(role, action)
            elif table:
                note = (f"{where}动作表里没有 {action!r}"
                        + (f"；并列候选 {close} ⇒ 不猜（留给闸门拒）" if close
                           else "（没有候选 ⇒ 不猜，留给闸门拒）"))
        # ---- `params` 键名归一 + 顶层折叠 —— 一次做完，因为它们是同一件事的两半：
        # 值在哪一格不重要，重要的是它得落在声明的那个键下面。
        props = self._param_props(spec)
        if props and (raw_params is None or isinstance(raw_params, Mapping)):
            fixed = dict(raw_params or {})
            for key in list(fixed):
                if key in props:
                    continue
                target = self._unique_rename(key, props, fixed)
                if target:
                    # 目标键已经在 `params` 里 ⇒ 不改（改名会覆盖一个真值：
                    # 那是动内容面，不是洗格式）。
                    fixed[target] = fixed.pop(key)
                    changes.append({"where": field, "field": f"params.{key}",
                                    "to": f"params.{target}", "why": "键名归一（唯一候选）"})
            for key in list(after):
                if key in fixed or key in self._SHAPE_KEYS or key == "params":
                    continue
                if key in props:
                    fixed[key] = after.pop(key)
                    changes.append({"where": field, "field": f"<顶层>.{key}",
                                    "to": f"params.{key}", "why": "顶层折叠"})
                    continue
                # 顶层的错名键：候选唯一 ⇒ 改名并收进 `params`（与 `params` 里
                # 那一支同一条口径）；候选不唯一 ⇒ 一个字节都不动，留在顶层
                # （它照样落在步骤记录里，"没洗"看得见）。
                target = self._unique_rename(key, props, fixed)
                if target:
                    fixed[target] = after.pop(key)
                    changes.append({"where": field, "field": f"<顶层>.{key}",
                                    "from": str(key), "to": f"params.{target}",
                                    "why": "顶层折算：键名归一（唯一候选）"})
            if fixed or raw_params is not None:
                if fixed != dict(raw_params or {}):
                    after["params"] = fixed
        elif raw_params is not None and not isinstance(raw_params, Mapping):
            note = note or f"{where}params 不是键值对 ⇒ 这一格没洗（原样发出去）"
        # 三态：读到了声明（表非空）就是"查过了"；表读不到才是"这一格没读成"。
        checked = bool(spec or table)
        out.update(payload=after, changes=changes, checked=checked,
                   washed=bool(changes), refused="",
                   reason=note if not changes else "")
        return out

    def _wash_summon_many(self, payload: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        """批量：逐项洗，不整批硬拒（一批是 N 次派活）。"""
        targets = payload.get("targets")
        after = dict(payload)
        changes: list[dict[str, Any]] = []
        bad: list[str] = []
        if not isinstance(targets, (list, tuple)):
            out.update(reason="targets 不是数组 ⇒ 这一格没洗（原样发出去）", payload=payload)
            return out
        washed: list[Any] = []
        for i, item in enumerate(targets):
            if not isinstance(item, Mapping):
                washed.append(item)
                bad.append(f"targets[{i}] 不是键值对")
                continue
            sub: dict[str, Any] = {"changes": [], "washed": False}
            got = self._wash_one(dict(item), sub, field=f"targets[{i}]", refuse=False)
            if got.get("reason") and not got.get("washed"):
                bad.append(str(got["reason"]))
            changes.extend(list(got.get("changes") or []))
            washed.append(dict(got.get("payload") or {}))
        after["targets"] = washed
        out.update(payload=after, changes=changes, checked=True, washed=bool(changes),
                   refused="",
                   reason="；".join(bad[:3]) if bad else "")
        return out

    def proposal_prefix(self) -> str:
        """请示编号的前缀：`W-<role>-<实例>-`，编号本身由台账锁内的 `seq` 发。

        为什么带实例：台账是分片的（`out/secretary/<role>-<task_id>.jsonl`），
        `seq` 只在片内唯一 ⇒ 只带角色的话，同角色两个并发实例会发出同名编号。
        （判据：新判据文件里"编号唯一 + 指得回那一行"那一条。）
        """
        return f"W-{self.role}-{self.task_id or 'x'}-"

    def proposal_fingerprint(self, payload: Mapping[str, Any]) -> str:
        """这份载荷的指纹（12 hex）：确认那一步用它判"这个编号是不是对这份载荷发的"。

        为什么要有它：只按编号回查，接受方就可以拿 A 的编号去确认 B 的载荷 ——
        编号存在、执行成立、接受的那份内容却不是它看过的那份。
        为什么让它抛（而不是把算不出来的折成空串）：空串会与另一份同样算不出来的载荷
        撞成同一个指纹 ⇒ 冒充成同一份。调用方在 try 里 ⇒ 成环/怪对象一律 fail-open 原样放行。
        """
        text = json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    def find_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """按编号回查那条请示（回查范围 = 本实例的账：老文件 + 本片）。

        只认"请示行"—— 也就是带着指纹的那一行（`:meth:`note_decision` 的 `fingerprint=`）。
        为什么必须这么筛：接受/拒绝/受控拒绝那几行也带同一个 `proposal_id`（那是留痕，
        让"这个编号后来被谁接受过"读得回来）。若不筛，倒序扫到的第一行会是最近那次确认，
        它没有指纹 ⇒ "指纹对不上"这一格永远轮不到判 ⇒ 拿 A 的编号确认 B 的载荷会静默通过。
        （实测：本函数第一版就是这样，探针第 6 格读不到"指纹不一致"。）

        三态不折平：没有这一行 返回 `None`（调用方必须按受控拒绝处理），
        而"台账读不成"由 `_read_ledger` 的坏行读数另行报出 —— 不许把读不成当成"没有"。
        """
        want = str(proposal_id or "")
        if not want:
            return None
        rows, _bad = self._read_ledger()
        for row in reversed(rows):
            if (str(row.get("proposal_id") or "") == want
                    and str(row.get("proposal_fingerprint") or "")):
                return row
        return None

    def find_proposal_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        """同一份载荷已经请示过 ⇒ 把那条请示找回来（编号复用，不另发一个）。

        为什么必须复用：模型很可能"看到了请示、但下一步又把同一句话重说一遍"
        （它没有改格式，只是没表态）。若每一步都新发一个号，步骤结果的读数就每步不同
        ⇒ 循环那一层的"同一条路 + 同一读数"判据（`_call_reading`）永远判不出原地打转
        （实测：本函数还没有时，同一份载荷在两步里拿到 `…-0001` 与 `…-0004` 两个号）。
        "一次派活一个"也是业主的原话：同一份载荷的同一次请示，编号就该是同一个。
        """
        want = str(fingerprint or "")
        if not want:
            return None
        rows, _bad = self._read_ledger()
        for row in reversed(rows):
            if (str(row.get("proposal_fingerprint") or "") == want
                    and str(row.get("proposal_id") or "")):
                return row
        return None

    @staticmethod
    def _value_at(payload: Mapping[str, Any], field: str) -> Any:
        """从 `changes[].field` 的那种写法里取值（`params.k` / `<顶层>.k` / `k`）。"""
        text = str(field or "")
        if text.startswith("<顶层>."):
            return payload.get(text[len("<顶层>."):])
        if text.startswith("params."):
            params = payload.get("params")
            return params.get(text[len("params."):]) if isinstance(params, Mapping) else None
        return payload.get(text)

    def _same_value(self, a: Any, b: Any) -> bool:
        """两个值是不是同一份（成环对象只认 `is`，绝不递归比）。"""
        if a is b:
            return True
        try:
            return bool(a == b)
        except Exception:  # noqa: BLE001 —— 比不了就按"不同"处理（宁可多报一处差异）
            return False

    def _wash_diff(self, original: Mapping[str, Any], washed: Mapping[str, Any],
                   changes: Sequence[Mapping[str, Any]]) -> tuple[list[str], dict[str, Any]]:
        """逐字段 diff：只列改了哪几个键（值原样摆出来，供人核"值其实没动"）。

        为什么从 `changes` 反推、而不是递归比两棵载荷：`changes` 是洗函数自己记的
        "我动了哪几格"（唯一事实），而递归比一份 60 层深/成环的载荷会当场炸掉
        （`test_secretary_noise.py` 的那两口噪声）。
        """
        keys: list[str] = []
        diff: dict[str, Any] = {}
        for c in changes or ():
            where = str(c.get("where") or "").strip("：: ")
            field = str(c.get("field") or "")
            path = f"{where}.{field}" if where else field
            why = str(c.get("why") or "")
            #: 每一条洗出来的改动都只可能在格式面上（真名 / 键名 / 位置）——
            #: 内容面那一半由 `tests/test_the_wash_is_proposed_not_applied.py` 的
            #: `_boundary_problems` 逐个值核（值多重集不变、正文逐字不变）。
            line: dict[str, Any] = {"why": why, "face": "格式面"}
            if "from" in c:
                line["from"] = c.get("from")
            if "to" in c:
                line["to"] = c.get("to")
            before = self._value_at(original, field)
            # `to` 有两种写法：键路径（`params.statement_text`）与值（动作真名
            # `register_statement`）。按有没有路径分隔判，别把后者当键名去查
            # （第一版就是这么错的：`value_after` 恒为 null，"改了真名"看起来像"值被清了"）。
            target = str(c.get("to") or field)
            if "." not in target and "<顶层>" not in target:
                target = field
            after = self._value_at(washed, target)
            if before is not None or after is not None:
                # `value_changed=False` 是关键读数：键换了位置而值逐字没动
                line["value_before"] = before
                line["value_after"] = after
                line["value_changed"] = not self._same_value(before, after)
            keys.append(path)
            diff[path] = line
        return keys, diff

    def _change_line(self, change: Mapping[str, Any]) -> str:
        """一条改动写成一句话（业主给的形状：`动作名 own.register_statement → register_statement`）。"""
        where = str(change.get("where") or "").strip("：: ")
        field = str(change.get("field") or "")
        to = str(change.get("to") or "")
        why = str(change.get("why") or "")
        frm = str(change.get("from") or change.get("field") or "")
        head = f"{where} " if where else ""
        if "动作真名" in why:
            return f"{head}动作名 {frm} → {to}"
        if "折叠" in why or "键名归一" in why:
            return f"{head}参数键 {field} → {to}"
        if why:
            return f"{head}{field}：{why}"
        return f"{head}{field} → {to}"

    def plan_wash(self, *, original: Mapping[str, Any], wash: Mapping[str, Any],
                  accept: str = "", reject: str = "") -> dict[str, Any]:
        """两段式的判据本体：这一次派活执行哪一份、要不要先请示。

        判决表（每一格都只有一种结局，三态不折平）：
        | 输入 | 结局 | 谁执行 |
        |---|---|---|
        | 没带确认键、`washed == original` | `outcome=""`（无事发生） | 直接执行原稿（不进第二段） |
        | 没带确认键、`washed != original` | `outcome="wash_proposed"` + `issue=True` | 谁都不执行（0 行新任务、0 次子任务调用） |
        | `accept_proposal=<id>` 且编号与载荷都对得上 | `accepted=True` | 用 `washed` |
        | `reject_proposal=<id>` 且编号与载荷都对得上 | `accepted=False` | 用 `original` |
        | 编号查不到 / 指纹对不上 / 两个都给了 | `problem` 非空 | 谁都不执行（受控拒绝） |
        "洗不动/没洗成"（`wash.checked=False`）按"没有差异"处理 —— 这一格秘书什么都没主张，本来也不该挡下一步
        （`fail-open` 的同一条纪律）。
        """
        body = dict(original or {})
        checked = bool(wash.get("checked"))
        washed = dict((wash.get("payload") or body) if checked else body)
        changes = [dict(c) for c in (wash.get("changes") or ())]
        keys, diff = self._wash_diff(body, washed, changes)
        plan: dict[str, Any] = {
            "outcome": "", "proposal_id": "", "issue": False,
            "original": body, "washed": washed,
            "accepted": None, "executed_with": "", "execute": {},
            "changes": [self._change_line(c) for c in changes],
            "changed_keys": keys, "diff": diff,
            "problem": "",
        }
        want_accept = str(accept or "").strip()
        want_reject = str(reject or "").strip()
        if want_accept and want_reject:
            plan["problem"] = (f"同一步同时给了 {ACCEPT_PROPOSAL} 与 {REJECT_PROPOSAL} "
                               "⇒ 不知道该按哪一份派（两份都没派）")
            return plan
        want = want_accept or want_reject
        if want:
            row = self.find_proposal(want)
            if row is None:
                plan["problem"] = (f"台账里没有请示 {want!r}（编号由秘书发，不许自己拼）"
                                   "⇒ 这一趟没有派活")
                plan["proposal_id"] = ""
                return plan
            got_fp = str(row.get("proposal_fingerprint") or "")
            try:
                want_fp = self.proposal_fingerprint(body)
            except Exception as exc:  # noqa: BLE001 —— 算不出指纹 ⇒ 判不了，不许当成"对得上"
                plan["problem"] = (f"这份载荷算不出指纹（{type(exc).__name__}）⇒ "
                                   "确认不成立，这一趟没有派活")
                return plan
            if got_fp and got_fp != want_fp:
                plan["problem"] = (f"请示 {want!r} 是对另一份载荷发的（指纹不一致）⇒ "
                                   "不能拿它确认这一份，这一趟没有派活")
                plan["proposal_id"] = want
                return plan
            plan["proposal_id"] = want
            plan["accepted"] = bool(want_accept)
            plan["execute"] = dict(washed if want_accept else body)
            plan["executed_with"] = "washed" if want_accept else "original"
            return plan
        if checked and keys and washed != body:
            plan["outcome"] = OUTCOME_WASH_PROPOSED
            plan["issue"] = True
        return plan

    def _action_spec(self, role: str, action: str) -> Any:
        """该角色该动作的声明（读不到 ⇒ `None`，调用方按"这一格没洗成"处理）。"""
        try:
            from . import capabilities as C

            return C.find_action(role, action)
        except Exception:  # noqa: BLE001 —— 声明读不到不是"没有这个动作"
            return None

    def _param_props(self, spec: Any) -> list[str]:
        """该动作声明的参数键名（空列表 = 这一格判不了，绝不读成"没有参数"）。"""
        try:
            props = dict(getattr(spec, "params", None) or {}).get("properties") or {}
        except Exception:  # noqa: BLE001
            return []
        return [str(k) for k in props]

    def wash_statement(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """洗一条命题载荷的格式面（业主 2026-10-09 四件活的第一件）。

        业主逐字：「写入侧应该都是B的活，让B的秘书帮它洗格式、拿编号、改表、查重，即B不直接用增工具，秘书实际
        操作增、改（比如一个定理在两个文献中都有证明，可以互相借鉴把证明写好点；如果证明路径不唯一，可增另一组
        依赖，实现用二维列表）、查工具，B纯粹负责消化理解。」返回（三态必须分得开，与 :meth:`wash_delegation` 同族）：
        | 结局 | 返回 |
        |---|---|
        | 洗过了、本来就是受控形状 | `{"checked": True, "washed": False, "changes": []}` |
        | 洗过了、改了格式格 | `{"checked": True, "washed": True, "changes": [...]}` |
        | 这一格没洗成 | `{"checked": False, "reason": …}`（调用方按"洗不动"处理） |
        ## 可以洗什么（只动格式面）：键名归一（`STATEMENT_KEY_ALIASES` 里的别名 ⇒ 正名；正名已在 ⇒ 不覆盖，
        两条同名写法并存时原样留着，交给写入那一层去判"重复"）；顶层折叠（`params` / `statement` / `payload` 里
        裹着的那一份命题字段摊上来）；去空白（字符串值的首尾空白）；`deps` 摊平（二维列表是正形，给一维列表
        ⇒ 包成 `[一层]`）；每一步的键名归一（`stmt`/`stmt_id`/`statement_id` ⇒ `stmt_id`，`exp`/`experiment_id`
        ⇒ `experiment_id`，`lit`/`lit_id` ⇒ `lit_id`，`doc`/`doc_id` ⇒ `doc_id`）。
        ## 一个字不许动什么（内容面）：`statement_full` / `proof_text` / `label` / 别名 / 每一步的 id 本身。
        所以这里只搬键、只去空白，从不把缺键补成默认值（补默认值 = 替 B 编内容）。
        """
        before = dict(payload or {})
        out: dict[str, Any] = {"checked": True, "washed": False, "changes": [],
                               "payload": before, "before": before, "refused": "",
                               "reason": ""}
        try:
            folded = self._fold_statement(before, out)
            keyed, changes = self._normalize_statement_keys(folded, out)
            keyed["deps"], dep_changes = _wash_dep_groups(keyed.get("deps"))
            out["changes"].extend(dep_changes)
            out["payload"] = keyed
            out["washed"] = bool(out["changes"])
            return out
        except Exception as exc:  # noqa: BLE001 —— 洗不动不许打断这一次写入
            out.update(checked=False, washed=False, payload=before,
                       reason=(f"洗命题的格式没跑成（{type(exc).__name__}: {exc}）"
                               "⇒ 这一笔不写（写入路径上'洗不动'按受控拒绝处理，"
                               "不许拿没洗过的载荷去落盘）"))
            return out

    def _fold_statement(self, payload: dict[str, Any],
                        out: dict[str, Any]) -> dict[str, Any]:
        """把裹在 `params`/`statement`/`payload` 里的那一份摊到顶层（只摊认得的键）。"""
        folded = dict(payload)
        for wrapper in ("params", "statement", "payload", "result"):
            inner = folded.get(wrapper)
            if not isinstance(inner, Mapping):
                continue
            moved: list[str] = []
            for key, value in dict(inner).items():
                name = str(key)
                if name in STATEMENT_PARAM_KEYS and name not in folded:
                    folded[name] = value
                    moved.append(name)
            if moved:
                folded.pop(wrapper, None)
                out["changes"].append(f"{wrapper}: 顶层折叠 {sorted(moved)}")
        return folded

    def _normalize_statement_keys(self, payload: dict[str, Any],
                                  out: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """键名归一 + 字符串去空白（正名已在 ⇒ 不覆盖）。"""
        keyed: dict[str, Any] = {}
        changes: list[str] = []
        for raw_key, value in payload.items():
            key = str(raw_key)
            if key not in STATEMENT_PARAM_KEYS:
                candidate = _statement_key_candidate(key)
                if candidate:
                    if candidate in payload:
                        keyed[key] = value          # 两种写法并存 ⇒ 两条都留着，让写入层去判
                        continue
                    changes.append(f"{key} → {candidate}")
                    key = candidate
            if isinstance(value, str):
                stripped = value.strip()
                if stripped != value:
                    changes.append(f"{key}: 去首尾空白")
                value = stripped
            keyed[key] = value
        out["changes"].extend(changes)
        return keyed, changes


#: 一条命题载荷认得的字段（正名）。别名表见 `STATEMENT_KEY_ALIASES`。
STATEMENT_PARAM_KEYS: frozenset[str] = frozenset({
    "statement_full", "statement_text", "kind", "label", "proof_text", "origin",
    "source_lit_id", "doc_id", "page_range", "line_range", "evidence_kind",
    "quote_verified", "quote_reason", "derived_from", "aliases", "bits",
    # 回验的方式与证据三栏必须能过秘书这一道（回验保持语义相同即可；语义那一档必须
    # 留证据）—— 否则 B 传给 `register_statement` 的
    # `quote_mode` 会被这一层的白名单静默丢掉（那一栏就白填了）。
    "quote_mode", "quote_span", "quote_call_sha256",
    "deps", "concepts",
    # 概念行"确实是我们自己定义的新概念"的显式声明。
    # 它必须能过这一层的白名单 —— 否则调用方在概念条目里写的那一句
    # `self_authored=True` 会被静默丢掉，于是"声明了"与"没声明"落成同一件事，
    # 而 `origin="own_result"` 的受控判据（`conceptrows.concept_origin_problem`）
    # 就永远只能拒绝、无法放行。
    "self_authored",
    # 多段可选证明：B 自己分的段（每段一组 `path_group`）。不给就把
    # "定理内容 + 证明过程"当一段 —— 秘书不按空行/字样猜 B 想分几段。
    "proof_paths",
    # 表述几乎相同的定理要认出是同一个；证明方式几乎相同的视为同种证明，
    # 可选"各取所长混合成一份、重拿 V 签"：`merge=True` 是那一档可选项的开关。
    # 它必须能过这一层的白名单 —— 否则调用方交上来的合并稿会被静默当成"另一份新证明"。
    "merge",
})


#: 键名别名 ⇒ 正名（每一列的别名必须唯一，否则 `_statement_key_candidate` 返回空 =
#: "不猜"）。写在这里而不是散在代码里，是为了让"认哪些写法"可被一条判据逐条读出来。
STATEMENT_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "statement_full": ("full", "statement", "theorem", "content", "claim"),
    "statement_text": ("short", "text", "summary"),
    "kind": ("type", "statement_kind"),
    "label": ("name", "title"),
    "proof_text": ("proof", "proof_process"),
    "source_lit_id": ("lit_id", "lit"),
    "doc_id": ("document_id",),
    "page_range": ("pages",),
    "line_range": ("lines",),
    "evidence_kind": ("evidence",),
    "derived_from": ("uses",),
    "aliases": ("aka",),
    "deps": ("dependencies", "dep_groups", "paths"),
    "proof_paths": ("proof_groups", "proof_segments"),
    "concepts": ("definitions",),
}


def normalize_same_as(value: Any) -> tuple[str, int]:
    """把模型点名的号归一化成裸号。返回 `(裸号, 它给了几个号)`。

    真机 82（2026-11-01）：模型判 same 时把 `same_as` 写成 `"['000003']"`（本趟 52 处 /
    16 个会话行），而 `adjudicate_proposition` 的成员判据是"逐字等于某个候选号" ⇒
    判了 same 也不并、照旧落新行，造出 000001/000004、000003/000005 两个重复对。

    ## 口径（宽进严出）
    - 外层 `[]`、引号、反引号与空白一律剥掉：`"['000003']"` / `"000003"` /
      `" 000003 "` 都得到 `"000003"`；
    - 逗号分隔出多个号 ⇒ 不猜（返回 `("", n)`，n 是模型给了几个）：本趟真出现过
      `"['000001', '000004']"`，替它挑一个等于替它表态；
    - 空串 ⇒ `("", 0)`。

    归一化只在"模型给了什么"这一层做，成员判定（在候选表里）仍由调用方按裸号逐字核
    —— 这一格不是放宽，是把"外壳"与"指错号"两件事分开：前者是读数格式，后者是不许并。
    """
    raw = str(value or "").strip()
    if not raw:
        return "", 0
    body = raw.strip(SAME_AS_WRAPPER_CHARS)
    if not body:
        return "", 0
    pieces = [p.strip(SAME_AS_WRAPPER_CHARS) for p in body.split(",")]
    pieces = [p for p in pieces if p]
    if len(pieces) > 1:
        return "", len(pieces)
    if not pieces:
        return "", 0
    return pieces[0], 1


#: 一步依赖认得的来源键 ⇒ `(来源字段, 表, 表的 id 字段, 该给的 `kind` 缺省)`。
#: 顺序就是"先认哪一个"：一步最多给一个来源（`Dependency.validate` 的"四选一"）。
STEP_SOURCE_KEYS: tuple[tuple[str, str, str, str, str], ...] = (
    ("stmt_id", "source_stmt_id", "statements", "stmt_id", "theorem"),
    ("experiment_id", "source_experiment_id", "experiments", "experiment_id", "experiment"),
    ("lit_id", "source_lit_id", "literature", "lit_id", "theorem"),
    ("doc_id", "source_doc_id", "documents", "doc_id", "theorem"),
)


#: 一步依赖的键名别名（与 `STATEMENT_KEY_ALIASES` 同一套纪律：不唯一就不猜）。
STEP_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "stmt_id": ("stmt", "statement_id", "statement"),
    "experiment_id": ("exp", "exp_id", "experiment"),
    "lit_id": ("lit", "literature_id"),
    "doc_id": ("doc", "document_id"),
    "kind": ("type",),
    "label": ("name", "title"),
    "quote": ("quote_text",),
}


def _statement_key_candidate(key: str) -> str:
    """别名 ⇒ 正名；没有唯一候选时返回空串（不猜：两条正名都收它，就是歧义）。"""
    hits = [canon for canon, alts in STATEMENT_KEY_ALIASES.items() if key in alts]
    return hits[0] if len(hits) == 1 else ""


def _wash_dep_groups(raw: Any) -> tuple[list[list[dict[str, Any]]], list[str]]:
    """把 `deps` 洗成二维列表（外层 = 可选路径，内层 = 一条路径上的步骤）。

    一维列表（一串步骤）⇒ 包成 `[一层]`：那是"只有一条路径"的写法，语义不变；
    非列表 / 空 ⇒ `[]`（不补默认值：补一条空的路径等于替 B 编一条依赖）。
    每一步的键名按 `STEP_KEY_ALIASES` 归一（id 本身一个字不动）。
    """
    changes: list[str] = []
    if raw in (None, "", []):
        return [], changes
    if not isinstance(raw, (list, tuple)):
        changes.append("deps: 不是列表 ⇒ 按'没有依赖'读（不猜）")
        return [], changes
    groups_raw = list(raw)
    flat = all(isinstance(g, Mapping) for g in groups_raw)
    if flat:
        groups_raw = [groups_raw]
        changes.append("deps: 一维列表 ⇒ 包成一条路径（外层 = 可选路径）")
    groups: list[list[dict[str, Any]]] = []
    for grp in groups_raw:
        if not isinstance(grp, (list, tuple)):
            if isinstance(grp, Mapping):
                grp = [grp]
            else:
                changes.append("deps: 有一层不是列表（跳过这一层，不猜）")
                continue
        steps: list[dict[str, Any]] = []
        for st in grp:
            if not isinstance(st, Mapping):
                changes.append("deps: 有一步不是对象（跳过这一步，不猜）")
                continue
            step: dict[str, Any] = {}
            for k, v in dict(st).items():
                key = str(k)
                if key not in STEP_KEY_ALIASES and key not in (
                        "stmt_id", "experiment_id", "lit_id", "doc_id", "kind", "label", "quote"):
                    hits = [canon for canon, alts in STEP_KEY_ALIASES.items() if key in alts]
                    if len(hits) != 1:
                        step[key] = v
                        continue
                    changes.append(f"deps[].{key} → {hits[0]}")
                    key = hits[0]
                step[key] = v.strip() if isinstance(v, str) else v
            steps.append(step)
        groups.append(steps)
    return groups, changes


def _dep_label(step: Mapping[str, Any]) -> str:
    """一步依赖没给标签时，用"来源种类:号"顶一格（`Dependency.validate` 要求非空）。

    刻意不写人话标签：这一步的语义（它是哪条定理）只有 B 知道，
    替它编一个名字等于把"没写"变成"写了"。
    """
    for key, prefix in (("source_stmt_id", "stmt"), ("source_experiment_id", "exp"),
                        ("source_lit_id", "lit"), ("source_doc_id", "doc")):
        if str(step.get(key) or "").strip():
            return f"{prefix}:{step[key]}"
    return "依赖"


def _dep_step_key(row: Mapping[str, Any]) -> tuple:
    """一条依赖边的身份（幂等判据：同一使用点 + 路径组 + 来源 ⇒ 同一条边）。

    为什么需要它：`dependencies` 没有"唯一键"这回事（一张账本表，允许同一对
    (使用点, 来源) 出现在不同路径组里 —— 多证明模型）。而"同一份手稿再携带一次"
    必须不重复落边，所以身份要按"这条边说的是什么"来算，不能按 `dep_id`（每次
    分配都会变）。

    ## `kind` / `label` 不算身份（2026-11-05 走查 D3）
    改前这两格也算进身份，于是同一条边经两路描述时会落两行：`derived_from`
    那一支（证明正文扫描）落 `kind=theorem, label="stmt:000000"`，稿里 `## 依赖`
    表那一支落 `kind=proposition, label="手稿依赖段（第 22 行）：…"` —— 两行的
    `used_by` / `path_group` / 来源号三格逐字相同，只有这两格不同。同一对
    (使用点, 来源) 图上是一条边："这条引用是定理还是命题"与"它被写成哪句话"
    都是这条边的描述，不是它的身份。收紧之后 `dependencies` 不再虚高，两条不同
    的边（来源号 / 路径组 / 使用点任一不同）仍然各占一行。
    """
    return (
        str(row.get("used_by") or ""),
        int(row.get("path_group") or 1),
        str(row.get("source_stmt_id") or ""),
        str(row.get("source_lit_id") or ""),
        str(row.get("source_experiment_id") or ""),
        str(row.get("source_doc_id") or ""),
    )


def _dep_ref(step: Mapping[str, Any]) -> str:
    """一条依赖步骤在读数里的指称（形如 `stmt:000777`）。

    为什么不能只读 `label`（2026-11-05 裁定 A 的读数面）：手稿依赖段那一路的 `label`
    是人读的"手稿依赖段（第 N 行）：…"（它要落进依赖行），而 `deps_dangling` 的 `ref`
    必须点名那个号 —— 从来源字段现算，读的人一眼看到是哪一条。前缀只从
    `schema.CITATION_PREFIXES` 反查（前缀只有一处声明），查不到就退回 `label`。
    """
    for _key, field, table, _idf, _dkind in STEP_SOURCE_KEYS:
        val = str(step.get(field) or "").strip()
        if not val:
            continue
        prefix = next((p for p, t in S.CITATION_PREFIXES.items() if t == table), "")
        return f"{prefix}:{val}" if prefix else val
    return str(step.get("label") or step.get("code") or "")


def _stmt_edge_count(steps: Any) -> int:
    """这一批依赖步骤里有几条是"命题→命题"（`source_stmt_id` 非空）。

    为什么要它（2026-11-05 缺陷 1c）：台账里"依赖边 N 条"与"其中命题→命题 M 条"是两个
    数。87 真机的 3 条边全是文献来的 —— N=3、M=0，而报告/回执里只有一个 N 时，
    "依赖面建起来了"与"一条命题→命题都没有"长得一模一样
    （`temp/dep_probe/REPORT-dependency-surface.md` 第三节 B 表：五区合计 3 行、
    `source_stmt_id` 非空 0 行）。
    """
    return sum(1 for step in (steps or ())
               if isinstance(step, Mapping)
               and str(step.get("source_stmt_id") or "").strip())
