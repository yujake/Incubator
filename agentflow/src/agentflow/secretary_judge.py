# -*- coding: utf-8 -*-
"""秘书的判断内核（一次模型判断的整条链，从 secretary.py 的 U15+U14 逐字搬出）。

我保证哪条不变式：一次判断只有三态（判了 / 没判成 / 为什么没判成），且判与记账分开：`judge` 只回判词，落账由 `note_decision` 那一侧做。

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
import json
import time

from .secretary_axes import (  # noqa: F401 — 这些名字由 secretary_axes 定义
    append_dispatch_fit,
)

from .secretary_ledger import (  # noqa: F401 — 这些名字由 secretary_ledger 定义
    decisions_path,
)

from .secretary_prompts import (  # noqa: F401 — 这些名字由 secretary_prompts 定义
    JUDGE_MATERIAL_CAP,
    _judge_material,
    _judge_system,
)

from .secretary_time import (  # noqa: F401 — 这些名字由 secretary_time 定义
    _as_mapping,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    JUDGE_VERDICTS,
    KIND_DECISION,
    _JUDGE_UNDECIDED,
    _nontriviality_level,
    nontriviality_label,
)


class JudgeMixin:
    """判断内核 + 知识面/预筛（从 secretary.py 搬出的混入类）。"""

    def knowledge(self) -> dict[str, Any]:
        """秘书能读什么（全部只读，`draft/55` §1）。

        四层：硬性要求 / 全角色的定位（组织图全开）/ 委托事实 / 读数。
        返回一个可读的事实表（不是权限授予）：`writes` 恒为 `∅`，
        `reads_narrative` 回答"它读不读研究叙事正文"（一般角色不读、V 更严）。
        """
        briefs: dict[str, dict[str, Any]] = {}
        emphasis: dict[str, Any] = {}
        # 业主 2026-10-22（「在Lean开关没开时隔绝L」）：这份事实表是读数面，
        # 开关关着时不存在的角色不许在这里留一行（"存在但没用到"正是要去掉的噪音）。
        # 判定读 `leanscope`（唯一入口），这里只过滤。
        from . import leanscope as _LEANSCOPE

        _visible = _LEANSCOPE.visible_roles(S.ROLES)
        for role in _visible:
            one = self._role_brief(role)
            if one:
                briefs[role] = dict(one)
        actions = self._action_table()
        return {
            "roles": sorted(set(_visible) | {S.CONDUCTOR_ROLE}),
            "briefs": briefs,
            "emphasis": emphasis,
            "actions": actions,
            "tools": self._tool_names(),
            "writes": self.writes,
            "reads_narrative": False,
            "ledger": str(decisions_path(self.root, self.role)),
            #: S1m 的两格：绑过实例 ⇒ 分片路径非空（"我这一名秘书"的账在这儿）；
            #: `ledger_legacy` 是历史那一份（老工作区里全部决定都在它里面）。
            #: 三格都给，是因为分片之后"这个角色的账在哪"必须读得出来（否则读侧会以为记录变少了）。
            "ledger_instance": str(self.decisions_path()) if self.task_id else "",
            "ledger_legacy": str(decisions_path(self.root, self.role)),
        }

    def may_read_narrative(self, role: str) -> bool:
        """本秘书能不能读 `role` 的叙述（研究数据面，不是定位面）。

        `draft/55` §1.5 ②：一般角色的秘书"数据面 ≤ 本体"；而 V 的秘书另有更严的
        隔离 —— 不读 F 的叙述、不读被审证明之外的上下文。理由逐字：
        I12 靠"冷启动不给 store 句柄、不给 F 的叙述"保证审校独立性 ⇒ 若 V 的秘书
        读全库（含 `handoffs` 正文、会话叙事），它就成了绕过 I12 的暗通道。

        本方法只回答"读不读得到"，不回答"读了要不要用" —— 后者是判断。
        """
        want = str(role or "")
        if self.role == "V":
            return False
        return want == self.role

    def _role_brief(self, role: str) -> Mapping[str, Any]:
        """某角色的六字段 brief（`agent_prompts.ROLE_BRIEFS` 真身；读不到 ⇒ 空表）。

        这里读的是定位（岗位定义），不是研究数据 —— 组织图对每名秘书全开
        （用户 2026-10-06 口径），而数据面另有约束（见 :meth:`may_read_narrative`）。

        `ROLE_BRIEFS` 的值是 `agent_prompts.RoleBrief`（dataclass，不是 Mapping）；
        两种形态都收，因为"它是 dataclass"是实现细节，而秘书要的是那六个字段。
        """
        try:
            from . import agent_prompts as AP

            got = (AP.ROLE_BRIEFS or {}).get(str(role))
        except Exception:  # noqa: BLE001 - 读不到定位不该让整条委托过不去
            return {}
        return _as_mapping(got)

    def _all_briefs(self) -> dict[str, dict[str, Any]]:
        """全部角色的 brief（组织图全开；读不到就空表 —— 空表 ≠ 没有角色）。"""
        try:
            from . import agent_prompts as AP

            table = AP.ROLE_BRIEFS or {}
        except Exception:  # noqa: BLE001 - 同上
            return {}
        out: dict[str, dict[str, Any]] = {}
        for role, got in dict(table).items():
            one = _as_mapping(got)
            if one:
                out[str(role)] = one
        return out

    def _action_table(self) -> dict[str, list[str]]:
        """每个角色声明了哪些动作（`capabilities.CAPABILITIES`：`{角色: (ActionSpec,…)}`）。"""
        out: dict[str, list[str]] = {}
        try:
            from . import capabilities as C

            table = getattr(C, "CAPABILITIES", None) or {}
            for role, specs in dict(table).items():
                names = [str(getattr(s, "action", "") or "") for s in specs]
                out[str(role)] = sorted({n for n in names if n})
        except Exception:  # noqa: BLE001 - 读不到声明 ⇒ 空表（"没读到"不许读成"没有动作"）
            return {}
        return out

    def _tool_names(self) -> list[str]:
        """注册表里的真名（判"工具名写错了没有"的唯一依据）。

        ## 口径：预筛的准确度取决于装配时给它的那份注册表：秘书只用已有声明判（注册表的真名 +
        `specs/<role>.py` 的参数表），不新增机器判据（`draft/55` §4）。所以"这份真名表全不全"直接决定预筛
        对不对：给错一份残缺的注册表，就会把真名报成"不是真名"（假阳性）。
        ## 为什么 fallback 必须带 `store`（2026-10-04 主控探针实测的缺陷）：没有 `registry` 时的 fallback 原先
        是 `build_registry()` —— 不带 `store`。实测：`build_registry()` 出 68 件真名且 `fs.read` 不在里面；
        `build_registry(store=...)` 出 81 件、`fs.read` 在里面。于是任何 `registry=None` 的调用方
        （`for_role(..., registry=None)` 是默认）都会对 `fs.read` 这种真名报警
        `'fs.read' 不是注册表里的真名；并列候选：['manuscripts.read','table.create']`
        （真名被判成错名 ⇒ 预筛的第一类假阳性，而 `self.store` 就在手边）。三态：`store` 也没有 ⇒ 保持
        "造不出来就给空表"的老行为（`[]`），空表在调用方那一侧只能是"没读到"，不许读成"没有真名"。
        """
        if self.registry is not None:
            try:
                return sorted(str(x) for x in self.registry.names())
            except Exception:  # noqa: BLE001 - 注册表坏了不该让委托过不去
                return []
        if self.store is None:
            # 空表在这里只有一个含义：这一格没读成（不是"没有真名"）。
            # 调用方 `prescreen` 只在真名表非空时才判错名 ⇒ 空表绝不会被读成
            # "这些名字都不存在"，所以这不是把"没做"折叠成"没有"。
            return []
        # 2026-10-27：兜底那一支要现造一整套工具（实测 12 ms/次），而工具面是静态的
        # （`tools/_MODULES` 在进程内不变）⇒ 读成功那次的名字表留在本实例上。
        # 只缓存非空结果：空表 = "这一格没读成"，缓存它会把一次失败变成永久没有真名。
        cached = self._tool_names_cache
        if cached is not None:
            return list(cached)
        try:
            from .tools import build_registry

            names = sorted(str(x) for x in build_registry(store=self.store).registry.names())
        except Exception:  # noqa: BLE001 - 造不出来 ⇒ 空表（"没读到"不许读成"没有真名"）
            return []
        if names:
            self._tool_names_cache = list(names)
        return names

    def prescreen(self, *, to: str, action: str, params: Mapping[str, Any],
                  tool: str = "") -> list[str]:
        """确定性预筛：返回"报警"清单（空 = 没有报警）。

        判据全部来自已有声明（`specs/<role>.py` 的参数表 / 注册表的真名），
        这里不新造机器判据（`draft/55` §4 末：秘书不新增机器判据）。
        它是"要不要叫秘书"的输入，不是判决 —— 报警之后仍然由秘书判断。
        """
        alarms: list[str] = []
        want_role = str(to or "")
        # 职责 2 的前提是读得到收件方的定位（`draft/55` §1.2：组织图全开）。
        # 读不到 ≠ 没问题：空 brief 与"这个角色没定位"是两件事，如实报成"这一格判不了"。
        if want_role and not self._role_brief(want_role) and self._all_briefs():
            alarms.append(f"读不到 {want_role} 的角色定位 ⇒ 『收件方真做得到吗』这一格判不了"
                          "（没读成不是没问题）")
        table = self._action_table()
        # 2026-10-16（业主口径 S2「M 只派活」）：`action` 为空时跳过这一条。
        # 空动作 = 派一件活、由被派者自己选动作 ⇒ 没有动作可核；照旧核就会报警
        # "{角色} 的动作表里没有 ''"，于是那条派活被吞掉。真机读数（T5 第 12 趟 `p8l`）：
        # M 六次发出 `{"role":"A","action":"","task":…}`，而 `tasks` 表里空动作的行
        # = 0 —— 六次全死在这一行；M 于是退回"点名动作+自己写参数"，那一趟 12 条被拒。
        # 其他地方同一套改法见 `policy.check` 第 [1] 步与 `LlmBackend.call`。
        if (str(action) and table and want_role in table
                and str(action) not in table.get(want_role, [])):
            close = declarations_candidates(str(action), table.get(want_role, []))
            alarms.append(f"{want_role} 的动作表里没有 {action!r}"
                          + (f"；并列候选：{close}" if close else ""))
        if tool:
            names = self._tool_names()
            if names and str(tool) not in names:
                close = declarations_candidates(str(tool), names)
                alarms.append(f"{tool!r} 不是注册表里的真名"
                              + (f"；并列候选：{close}" if close else ""))
        alarms += self._required_alarms(want_role, str(action), params)
        return alarms

    def _required_alarms(self, role: str, action: str, params: Mapping[str, Any]) -> list[str]:
        """必填字段：按 `specs/<role>.py` 的参数表核。

        三态（R002 的口径）：读不到参数声明不是"没有必填参数" —— 前者是"这一格
        判不了"，所以它返回一条 alarm，而不是空列表。空列表只有一个含义：读到了
        声明、而且必填项一个不缺。
        """
        problem = ""
        try:
            from . import capabilities as C

            # 2026-10-16（业主口径 S2）：`action` 为空时这一格不适用、不算报警 ——
            # 没有动作就没有"参数声明"可读，报警会让"只派活"那一路整条被判成"判不了"。
            # 真机/判据现场：`test_the_secretary_washes_the_format_face` 的读数逐字是
            # `读不到 E. 的参数声明（能力表里没有这个动作）⇒ 必填这一格判不了`。
            spec = C.find_action(role, action) if str(action) else None
            if not str(action):
                return []
        except Exception as exc:  # noqa: BLE001 - 读不到声明 ⇒ 这一格判不了
            spec, problem = None, f"{type(exc).__name__}: {exc}"
        else:
            if spec is None:
                problem = "能力表里没有这个动作"
        if problem:
            return [f"读不到 {role}.{action} 的参数声明（{problem}）⇒ 必填这一格判不了"]
        props = dict(getattr(spec, "params", None) or {}).get("properties") or {}
        required = list(dict(getattr(spec, "params", None) or {}).get("required") or [])
        got = set(params or {})
        missing = [k for k in required if k not in got]
        if not missing:
            return []
        return [f"{role}.{action} 缺必填参数 {missing}（声明里的键：{sorted(props)}）"]

    def should_engage(self, *, alarms: Sequence[str], duplicates: int = 0,
                      overdue: int = 0, novel: bool = False) -> bool:
        """要不要叫秘书（`draft/53` §6：花销与问题量成正比，不与委托量成正比）。

        四条任一成立就叫：预筛报警 / 出现重复候选 / 闭环逾期 / 首次遇见该形态。

        它有真调用点（否则"按需介入"就是一句空话）：:meth:`optimize_outbound`、
        :meth:`assess_delegation`、:meth:`remind_closure` 三处都是先算这四个数、
        再由本方法决定要不要走 :meth:`judge`（一次模型调用）。四个数全不成立 ⇒
        确定性路径直接给结论，一次模型调用都不发。
        """
        return bool(alarms) or int(duplicates) > 0 or int(overdue) > 0 or bool(novel)

    #: 判断类（`draft/55` §2 的 B 类；用户口径"切勿全写死成机器判据"）。
    #:
    #: 从 `JUDGE_VERDICTS` 派生（不是另抄一份名单）：那一张表同时管着"这一类允许哪些结论"，
    #: 两处各写一份的话，"加了一类判断却忘了给它词表"会静默落进 `DECISIONS` 的校验里。
    JUDGE_KINDS = tuple(JUDGE_VERDICTS)

    def _judge_core(self, kind: str, context: Mapping[str, Any], *, task_id: str = "",
                    note: str = "") -> dict[str, Any]:
        """判断类的内核：用本智能体自己的缝做一次模型调用，不写任何台账。

        ## 为什么把"判"与"记"拆开（业主 2026-11-13 裁定 Q5）
        有的判断只该落一本轴台账（`judge_dispatch_fit` → `out/secretary/dispatch_fit.jsonl`），
        不该再往角色台账（`out/secretary/<role>.jsonl`）里抄一行 —— 双写就是"同一件事两个
        落点"，读的人分不清哪一本算数。拆法只有一种：判据、词表校验、三态全在本方法
        （一处实现），谁记账由调用方决定（:meth:`judge` 记角色台账；`judge_dispatch_fit`
        记轴台账）。判据不允许复制第二份。

        `note` 是这一次调用的读数目（缺省 `secretary:<kind>`）：同一类判定有两问
        （挑词 / 认定）时，读数要分得开哪一问花的那一笔钱。判据本身仍按 `kind`。

        判断类别（`draft/53` §10 的三条"改判给秘书"，加业主 2026-10-14 裁决第 12 条前半）：`duplicate_retry`
        （同 key 的既有终态行算重复还是正当重试）、`tool_name`（错名映到哪一个候选，或一个都不映）、
        `rearrange`（建议重排成什么，改派权仍在 M）、`statement_aesthetic`（B 的秘书专属：这条待入库的命题够不够
        格 —— 三态 `合格` / `太平凡` / `判不了`，词表见 :data:`STATEMENT_VERDICTS`）。每一类只认自己那张词表
        （:data:`JUDGE_VERDICTS`）：把"可派"填进审美那一栏，在这一层就被拒 —— 两根轴的结论混进同一栏是查不出来
        的那种错。三态（`R002`/P16 的口径）：
        | 结局 | 返回 |
        |---|---|
        | 判断做了 | `{"checked": True, "decision": …, "reason": …, "basis": […]}` |
        | 没缝 / 没开 / 超时 / 坏 JSON | `{"checked": False, "reason": …}` |
        "没查成"绝不被读成"可派"：调用方（:meth:`assess_delegation`）只在 `checked=True` 时才采信 `decision`。
        每一次真的发起过调用的结局都带 `cost`（见 :meth:`last_judge_cost`）："这次判断花了哪一笔钱"必须能从
        台账追回账本，否则它是一笔不可归因的花销。
        """
        if kind not in self.JUDGE_KINDS:
            return {"checked": False,
                    "reason": f"不认识的判断类别 {kind!r}（认 {list(self.JUDGE_KINDS)}）",
                    "cost": {"ledger": "", "reason": "没发调用（类别不认识）"}}
        if self.seam is None:
            # ---- 2026-10-26（真机 sylow5）：这一句必须把"缝从哪来"的读数一并带出来。
            #
            # 改前它只说"没有装配模型缝"，而全仓五个构造点一个都没传 `seam=` ⇒
            # 命题同一性判定这一整条链在真机上一次都没发生过，没人能从返回值里看出
            # "这不是判过了、是根本没判"。装配读数（`model_source`）现在由
            # `for_role_wired` 写在秘书身上：`none（秘书那一档没有配模型 key …）`。
            why = "没有装配模型缝（本智能体自己的 llmseam）⇒ 这一格没查成"
            if str(self.model_source or ""):
                why = f"{why}（装配读数：{self.model_source}）"
            # `_no_ledger`：这一档不落角色台账（与改前逐字相同 —— 没缝是装配
            # 事实，`model_source` 已经记了；把这一趟的材料再 dump 一遍既没信息量，
            # 材料里带环时还会抛 `Circular reference detected`，见
            # `tests/test_secretary_noise.py::test_assess_delegation_survives_noise`）。
            return {"checked": False, "reason": why, "_no_ledger": True,
                    "cost": {"ledger": "", "reason": "没发调用（没有缝）"}}
        if not self.enable_model:
            return {"checked": False, "_no_ledger": True,
                    "reason": "enable_model=False（判断类的模型调用被显式关掉）⇒ 这一格没查成",
                    "cost": {"ledger": "", "reason": "没发调用（开关关着）"}}
        t0 = time.monotonic()
        try:
            # ---- 2026-10-21：稳定头进 system，材料留在 user（前缀缓存那一轴）
            #
            # 改前这里只有一条 user 消息（`ask_json(_judge_prompt(kind, context))`）：
            # 抬头 + 问题 + 材料全在同一格里，而材料每问一次都变 ⇒ 两趟之间的公共
            # 前缀只剩"抬头 + 问题"之前的那点字节，而它又不在 system 位上。真机实测
            # （2026-10-21，`scripts/warm_prompt_cache.py --roles secretary --hit-sample
            # secretary`）：连发两趟都是 `hit=0 / miss=175` —— 那 175 token 的稳定头
            # 一次都没进过索引。
            #
            # 现在：`_judge_system(kind)` 是逐字稳定的那一半（抬头 + 这一类自己的问题），
            # 走 `llmseam` 早就有的 `system=` 通道（`LlmSeam.ask` 的 `system` 参数，
            # `modelgw.ModelGateway.complete` 把它放进 messages 的第一条 `system` 位）；
            # `_judge_material(context)` 只装这一趟的材料。没有新造通道 ——
            # 十个角色的循环那条路（`agent_loop`）用的就是同一个参数。
            data, call = self.seam.ask_json(_judge_material(context),
                                            system=_judge_system(kind),
                                            task_id=task_id,
                                            note=note or f"secretary:{kind}")
        except Exception as exc:  # noqa: BLE001 - fail-open：超时/出错 ⇒ 没查成 + 留痕
            return {
                "checked": False, "reason": f"调用失败：{type(exc).__name__}: {exc}",
                "cost": self.last_judge_cost(kind)}
        finally:
            self._last_judge_elapsed = round(time.monotonic() - t0, 3)
        cost = self.last_judge_cost(kind)
        if not getattr(call, "ok", False) or data is None:
            return {
                "checked": False,
                "reason": f"没查成（{getattr(call, 'problem', '') or 'no_reply'}）："
                          f"{str(getattr(call, 'detail', '') or '')[:200]}",
                "cost": cost}
        raw_decision = data.get("decision")
        decision = str(raw_decision or "").strip()
        allowed = JUDGE_VERDICTS[kind]
        # ---- 2026-11-01（业主裁定：审美轴三格退场，判档那一问只剩 T0–T4）
        #
        # 三态（盘上必须分得开，见 STATEMENT_VERDICTS 的注释）：
        #   档位   ⇒ decision = "T0".."T4"（原样带下去，不再回写成旧词）；
        #   判不了 ⇒ decision 键在、值 null ⇒ checked=True + nontriviality=None；
        #   没查成 ⇒ checked=False（没缝 / 超时 / 坏 JSON / 词表外）。
        # 旧词（合格 / 太平凡 / 判不了）在这一层不采信：旧行只在读台账时折算
        # （`_tier_from_legacy_decision`），写侧与新行一个字都不再产生它们。
        # 2026-11-01（第二刀）：判档只有两态 —— 有 T0..T4，或者没拿到可用判定。
        # null / 旧词 / 坏 JSON 一律走"没查成"（checked=False），不落档位行：
        # "判不了"不是第四档，是我们没拿到判定（处置是重试 / 重交 / 人看）。
        if (decision not in allowed
                and (kind != "statement_aesthetic"
                     or _nontriviality_level(decision) is None)):
            if kind == "statement_aesthetic":
                why = (f"模型没给出可用判定（decision={raw_decision!r}）：档位只认 "
                       f"{list(allowed)} ⇒ 这一格没查成")
            else:
                why = f"模型给的结论 {decision!r} 不在 {kind} 的词表 {list(allowed)} 里 ⇒ 不采信"
            return {"checked": False, "reason": why, "cost": cost}
        level = _nontriviality_level(decision) if kind == "statement_aesthetic" else None
        if level is not None:
            # 容忍模型把档位给成 2 / "2"（老形状）：台账与读侧一律写 "T2"，不写数字串。
            decision = nontriviality_label(level)
        out = {
            "checked": True, "decision": decision,
            "reason": str(data.get("reason") or "")[:500],
            "basis": [str(x) for x in (data.get("basis") or [])][:5],
            "elapsed_sec": self._last_judge_elapsed, "cost": cost}
        if kind == "statement_aesthetic":
            # 档位就是 `decision` 本身（一根轴一个字段）。这里把它作为派生读数带回
            # （`judge_statement` 与旧替身都读这一格），不再单独向模型要第二个字段 ——
            # 两个字段就是"同一件事两个名字"。
            out["nontriviality"] = level
            out["nontriviality_basis"] = str(data.get("nontriviality_basis") or "")[:500]
        if kind == "v_reply_defect":
            # ---- 判 fault 而 V 没给步号时，由秘书定出那一步 ----------------
            #
            # 判 fault 而 V 没给 defect_step ⇒ 秘书定出那一步。所以这一问要多要一格；
            # 取值只有两种：正整数（指到 V 回复里
            # 说的那一步）或 null（这一档不是按步号定位的）。坏值一律 null —— 不猜。
            raw_step = data.get("defect_step")
            step: int | None = None
            if isinstance(raw_step, int) and not isinstance(raw_step, bool) and raw_step >= 1:
                step = raw_step
            out["defect_step"] = step
            out["defect_step_basis"] = str(data.get("defect_step_basis") or "")[:500]
            # ---- D3 批 2：两格新的读数（只解析、不在这里定轴） ------------------
            #
            # `defect_kind`：判 fault 时 fault 的内容是哪一类；`report_gap`：判
            # 「没问题」时那份报告缺了什么记录（裁定 ①：它不是判据）。两格都只做
            # 形状归一（字符串、截断），语义归类在 `v_reply_fault_reading` 一处。
            out["defect_kind"] = str(data.get("defect_kind") or "").strip()[:40]
            out["report_gap"] = str(data.get("report_gap") or "").strip()[:500]
        if kind == "proposition_identity":
            # ---- 同一趟判断的第二组输出。
            #
            # 这一类的判词不止一个词：还要把名字洗出来（canonical_name）、把标签里那条
            # 路线挪到证明那一层（route），并把"条件是什么 / 结论是什么"各自留一句比对
            # （condition / conclusion）。这一层只做放行与截断，不校验语义（校验与三态在
            # `adjudicate_proposition` 一处做）—— 与 `nontriviality` 那一支同一条纪律：
            # 这一格只管"别把它丢了"（丢了之后盘上只剩一个 same，人看不出凭什么）。
            out["canonical_name"] = str(data.get("canonical_name") or "")[:200]
            out["same_as"] = str(data.get("same_as") or data.get("same_stmt_id") or "")[:64]
            out["route"] = str(data.get("route") or "")[:500]
            out["condition"] = str(data.get("condition") or "")[:500]
            out["conclusion"] = str(data.get("conclusion") or "")[:500]
        if kind == "proof_kind":
            # 判 same 时模型要指到"哪一条在册路径"（拒信点名第 N 条）；坏值不采信，
            # 由调用方退回"第一条在册路径"（仍然拒收，不猜一条不存在的号）。
            try:
                out["same_path"] = int(data.get("same_path") or 0)
            except (TypeError, ValueError):
                out["same_path"] = 0
        return out

    def judge(self, kind: str, context: Mapping[str, Any], *, task_id: str = "",
              note: str = "") -> dict[str, Any]:
        """判断类：一次模型调用（判据与三态全在 :meth:`_judge_core`）＋ 落角色台账。

        这一层只做"记账"这一件事：`_record_judge` 把结果写成 `out/secretary/<role>.jsonl`
        的一行（花销归因与三态都在那里完整）。只落轴台账的那几问
        （:meth:`judge_dispatch_fit`）直接调 `_judge_core`、不经过这里 —— 判据只有
        一份，双写（角色台账 + 轴台账）是业主 2026-11-13 裁定 Q5 明确不要的形态。
        """
        result = self._judge_core(kind, context, task_id=task_id, note=note)
        if result.pop("_no_ledger", False):
            # 「没缝 / 开关关着」不落角色台账 —— 这一档与改前逐字相同（不是判定，
            # 是装配事实；`model_source` 已经记了它）。见 `_judge_core` 那一支。
            return result
        return self._record_judge(kind, context, result)

    def judge_dispatch_fit(self, *, task: str, to: str = "F", action: str = "",
                           params: Mapping[str, Any] | None = None,
                           task_id: str = "") -> dict[str, Any]:
        """D 的秘书专属：这一条派给 F 的活是不是一个研究方向（业主 2026-11-13）。

        业主原话（逐字）：

        > 「plan由F自己决定，所以D不可能做出按plan个数派F，于是D只能按研究方向开多个F
        >   而非把一堆方向委托给一个F（这里D秘书要审D的派活，不合适需要给出提醒）。」

        ## 它判什么、不判什么
        - 判：方向个数 —— 这一条派活交给 F 的是一件事，还是几件互不相干的事
          （或一张"计划列表 / 进度督办"，而 plan 由 F 自己决定）。
        - 不判：难不难 / 值不值得做 / F 能不能证出来（研究判断），也不判 F 该开几条计划。
        - 不用词面线索代替判断：一次模型调用，没有关键词表、没有字数阈值。

        ## 三态与"只提醒不拦"
        | 结局 | 返回 |
        |---|---|
        | 判了 | `{"checked": True, "verdict": "是一个方向"|"不是一个方向", "why", "basis", "cost"}` |
        | 判不了 | `{"checked": False, "verdict": "", "why": …}`（没缝 / 关着 / 超时 / 坏 JSON / 词表外） |
        调用方（:meth:`assess_delegation`）只在 `checked=True` 且
        `verdict==DISPATCH_FIT_UNSUITABLE` 时把结论并进建议与提醒正文 ——
        不改派活本身（业主：「不合适需要给出提醒」，不是拒收）。

        ## 台账（Q5：只落一本）
        走 :meth:`_judge_core`（判据与三态只有那一处），结果落
        `out/secretary/dispatch_fit.jsonl`（读侧 :func:`dispatch_fit_rows`），
        不写角色台账 —— 双写就是同一件事两个落点。
        """
        material = {"to": str(to or ""), "action": str(action or ""),
                    "task": str(task or "")[:JUDGE_MATERIAL_CAP],
                    "params": dict(params or {})}
        result = self._judge_core("dispatch_fit", material, task_id=task_id,
                                  note="secretary:dispatch_fit")
        checked = bool(result.get("checked"))
        verdict = str(result.get("decision") or "") if checked else ""
        why = str(result.get("reason") or "")
        root = str(getattr(self.store, "root", "") or self.root or "")
        row = append_dispatch_fit(
            root, to=to, task=task, checked=checked, verdict=verdict, why=why,
            basis=[str(x) for x in (result.get("basis") or [])],
            # 没查成时台账那一栏写 `没查成`（不是"合适"）——三态纪律。
            decision=str(result.get("decision") or _JUDGE_UNDECIDED["dispatch_fit"]),
            cost_ledger=str((result.get("cost") or {}).get("ledger") or ""),
            role=str(self.role), task_id=str(task_id or self.task_id or ""))
        return {"checked": checked, "verdict": verdict, "why": why,
                "decision": str(result.get("decision") or ""),
                "basis": [str(x) for x in (result.get("basis") or [])],
                "cost": dict(result.get("cost") or {}), "at": str(row.get("at") or "")}

    def _record_judge(self, kind: str, context: Mapping[str, Any],
                      result: dict[str, Any]) -> dict[str, Any]:
        """把这次判断自己记一行台账（主控裁定 A5 的第 ③ 条）。

        为什么判断要独立成行（而不是只搭在 `assess_delegation` 的提案行上）：
        那份花销的归因（`cost.ledger`）与三态只在这一刻是完整的，
        而"这次判断花了哪一笔钱"必须总能从台账追回账本 —— 不论调用方是谁
        （`optimize_outbound` / `assess_delegation` / 直接调用）。
        `before` 落的是判断的输入（材料摘要），`after` 落结论：人看过程、本体看结果。
        """
        basis = list(result.get("basis") or [])
        if result.get("cost"):
            basis = basis + [f"cost.ledger={result['cost'].get('ledger') or '查不到'}"]
        # 没判成时写哪个词：按类别（`_JUDGE_UNDECIDED`）。缺省仍是派活那一轴的
        # "建议重排"（历史读数逐字不变）；V 的两类与判档那一问写"没查成" —— 对它们写
        # "建议重排"是一句假话（它们里没有"重排"这件事）。
        #
        # 2026-11-01（第二刀）：判档只有两态，`checked=True` 时 `decision` 必然是
        # `"T0"`…`"T4"`；"没拿到判定"走 `checked=False`，落到这里的缺省"没查成"。
        self.note_decision(
            duty=2, kind=KIND_DECISION,
            decision=str(result.get("decision") or _JUDGE_UNDECIDED.get(kind, "建议重排")),
            reason=str(result.get("reason") or ""),
            basis=basis, target={"judge": kind}, judge=result,
            before=json.dumps(dict(context), ensure_ascii=False, sort_keys=True,
                              default=str)[:2000],
            fail_open=False,
        )
        return result

    def last_judge_cost(self, kind: str) -> dict[str, Any]:
        """上一次该类别判断的花销归因（主控裁定 A5 的第 ③ 条）。

        权威来源是缝自己落的那条审计事件：`llmseam._land` 把"这次的钱记进账本了吗、记成哪一行"写进
        `llm_call` 事件的 `ledger` 字段（`usage_id` / `reason`），所以这里读那条事件，而不是让秘书猜花销。
        三态（取不到就如实写，不许折成"花了 0"）：
        | 情形 | 返回 |
        |---|---|
        | 入账了 | `ledger = "<usage_id>"` |
        | 没入账（`no_meter` / `duplicate` / 没发请求） | `ledger = ""` + `reason` 逐字来自事件 |
        | 读不到事件 / 读不出会话 | `ledger = ""` + `reason = "查不到：…"` |
        `call_index` 是与 `usage_id` 并列的第二归因口径（缝的幂等键就用它），两者都给，读的人才能把"账本行"
        与"第几次调用"对上。
        """
        from . import sessions as SS

        want = f"secretary:{kind}"
        try:
            events, problems = SS.read_session(self.root, self.sid)
        except Exception as exc:  # noqa: BLE001 - 归因读不到就如实报
            return {"ledger": "", "reason": f"查不到：{type(exc).__name__}: {exc}"}
        calls = [e for e in events if e.get("kind") == "llm_call"]
        hit = [e for e in calls if str(e.get("note") or "") == want]
        if not hit:
            extra = f"（会话读不出：{problems[0]}）" if problems else ""
            return {"ledger": "", "reason": f"查不到：会话里没有这次判断的 llm_call 事件{extra}",
                    "call_index": len(calls)}
        ev = hit[-1]
        led = ev.get("ledger") if isinstance(ev.get("ledger"), Mapping) else {}
        out: dict[str, Any] = {
            "ledger": str((led or {}).get("usage_id") or ""),
            "charged": bool((led or {}).get("charged")),
            "ledger_reason": str((led or {}).get("reason") or ""),
            "call_index": len(calls) - 1,
            "prompt_sha256": str(ev.get("prompt_sha256") or ""),
            "tokens": int(ev.get("tokens_in") or 0) + int(ev.get("tokens_out") or 0),
            "usd": ev.get("usd"),
        }
        if not out["ledger"]:
            out["reason"] = (f"取不到 usage_id（{out['ledger_reason'] or '未知'}）"
                             "⇒ 用 call_index 归因")
        return out


def declarations_candidates(name: str, names: Iterable[str], *, limit: int = 3) -> list[str]:
    """错名的并列候选（薄转发到 `tools.base.candidate_tool_names`，判据只有一份）。

    为什么在这里再包一层：秘书不使用注册工具，但它必须能回答
    "这个名字是不是真名"（职责 1）。转发而不是重写 —— 两份候选算法必然分叉，
    而分叉的形态是"机器给的候选与秘书给的候选不是同一批"。
    """
    from .tools.base import candidate_tool_names

    return candidate_tool_names(name, names, limit=limit)
