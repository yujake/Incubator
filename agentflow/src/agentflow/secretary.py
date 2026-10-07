# -*- coding: utf-8 -*-
"""「秘书」：每个智能体自带的随员（`draft/53` v3 定位 · `draft/55` 接口规范 · `draft/54 §2`）。

## 它与其它角色的分别（一句话）

它不是一个同级角色：不占 `schema.ROLES`、不加注册工具、不改权限面声明、
不改 `llmseam` 的 enum、不重冻快照 ⇒ 一个计数都不变（`draft/54 §2.2` 的"明确不动"）。
它是"每个智能体都有的"那一个：同一个类，每角色一份配置（自己的角色定位 + 自己的
收发箱），先建 M 的，再批量给 A–H 装（批量 = 配置 + 每角色一条测试，不是新代码）。

## 四条职责（用户 2026-10-06 逐字裁定，`draft/53` §2）

| # | 职责 | 谁的秘书做 | 本模块的落点 |
|---|---|---|---|
| 1 | 格式与内容优化 | 发件方 | :meth:`Secretary.optimize_outbound`（对齐参数表/必填/工具真名；不替本体承诺） |
| 2 | 委派评估 | 发件方 | :meth:`Secretary.assess_delegation`（收件方真做得到吗 + 该不该派） |
| 4 | 委托加工 | 收件方 | :meth:`Secretary.rework_inbound`（按本角色定位改说法，不加码不减码） |
| 3 | 闭环提醒 | 收件方 | :meth:`Secretary.remind_closure`（未接手 / 未反馈；经 M） |

两条实质性红线（`draft/53` §2）：格式补不全、或加工后发现实质缺陷
（错的对象 / 缺前提 / 结论与证据不符）⇒ 与对方协商，不静默修。
本模块的形态是 :meth:`Secretary.negotiate`（≤2 轮）+ 台账留痕 —— 它从不替本体表态。

## 它另外持有的：手稿通道的增 / 改 / 查（`draft/55` §3）

用户原话："至少要能读 handoffs，且由于所有信息交互都由秘书过一遍手，
所以 handoffs 的增改查能力都该给秘书，智能体只保留'查'的能力。"

- 增 = :meth:`Secretary.handoff_add`（既有 `manuscripts.write`；行里的 `sender`
  仍是被服务的角色 —— 作者=角色、执笔=秘书，`manuscript_rows` 口径不变）；
- 改 = :meth:`Secretary.handoff_revise`（新增 `manuscripts.revise`，追加修订行、不改旧行）；
- 查 = :meth:`Secretary.handoff_query`（既有 `manuscripts.read/list_all/query/...`）。

智能体侧只保留"查"：`agent_loop` 的循环形状 `handoff` 与 `summon` 的 `notify`
派生写都改由本模块执笔（`agent_loop.AgentLoop._do_handoff`）。

## 权限与失败姿态（`draft/55` §4）

- 库表只读（写集 ∅）；文件两处写：手稿通道 + 自己的台账 `out/secretary/<role>.jsonl`；
- 不使用注册工具（工具面为空：只有"手稿通道增改查 + 只读读数 + 自己台账"三类内部能力）；
- 信息面 ≤ 本体，且 V 的秘书不读 F 的叙述（I12 的审校独立性不许被秘书绕过，
  `draft/55` §1.5）；
- fail-open：超时/出错 ⇒ 原样放行 + 留痕（阻塞一条委托比放行更贵 —— 那就是 #1）。
  唯一例外：手稿执笔失败必须报错留痕（静默放行会让手稿缺行，而"缺行"
  与"没交接"在账本上长得一样）；
- 不做任何统计：不计算拒绝率 / 重复率 / 闭环率，也不做花销统计与花销告警
  （用户 2026-10-06：那套统计是坏设计，去掉）。它是判断者，不是仪表盘 ——
  效果由机器读数与人评估（`tasks`/`sessions` 本来就能算）。

## 成本控制：机器预筛 + 按需介入（`draft/53` §6）

每条消息都过一次模型 ⇒ 调用量与花销翻倍。所以 :meth:`Secretary.should_engage`
只在预筛报警 / 出现重复候选 / 闭环逾期 / 首次遇见该形态时才说"叫秘书"。
本模块的默认路径是确定性的（不需要模型、不需要网络）：这是刻意的 ——
"能机器判的"不许推给模型，而秘书拿到的是读数 + 候选，不是判决书。
"""
from __future__ import annotations

import datetime as _dt
import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import manuscripts as MS
from . import schema as S

#: 台账落点：`<工作区>/out/secretary/<role>.jsonl`（追加式、脚本发号，`draft/53` §11.2）。
SECRETARY_DIR = ("out", "secretary")
#: 发件/收件的单次模型调用上限（`draft/55` §5.2：1 次调用、≤3 秒，超时放行）。
DEFAULT_DEADLINE_SEC = 3.0
#: 秘书 ⇄ 秘书协商的轮数上限（`draft/55` §5.2：最多 2 轮，之后上报本体）。
MAX_NEGOTIATION_ROUNDS = 2
#: 一次最多几条闭环提醒（`draft/55` §5.2：默认 5，避免刷屏）。
MAX_REMINDERS = 5
#: 六种事件名（`draft/55` §5.1）—— 常量在这里是为了让"冒充本体"这件事结构上不可能：
#: 秘书发出的每一条都带 `secretary/` 前缀。
KIND_OPTIMIZED = "secretary_optimized"
KIND_HANDOFF = "secretary_handoff"
KIND_NOTICE = "secretary_notice"
KIND_PROPOSAL = "secretary_proposal"
KIND_QUESTION = "secretary_question"
KIND_NEGOTIATION = "secretary_negotiation"
KIND_DECISION = "secretary_decision"
#: 秘书的判断结论词表（`draft/55` §2 的 B 类）。
DECISIONS = ("可派", "建议重排", "建议改派", "建议不派", "已优化", "已提醒", "已执笔")


def decisions_path(root: str | Path, role: str) -> Path:
    """这一名秘书的决定台账路径（每角色一份，绝不混写 —— `draft/53` §5 的防错①）。

    注意：名字刻意不叫 `ledger_path` —— 那个名字在 `artifacts.py`（产物归属台账）与
    `signatures.py`（签名台账）里各有一份独立实现，而秘书的决定台账与它们不是
    同一件事 —— 合并它们会把三件不同的事折成一个（lint R003 的口径是"同一判据
    的两份实现必须合并"，这里恰恰不是同一判据，所以正确的做法是改名字而不是合并）。
    """
    return Path(root).joinpath(*SECRETARY_DIR, f"{role}.jsonl")


def _as_mapping(value: Any) -> dict[str, Any]:
    """把一个"看起来像声明"的对象读成 dict（`RoleBrief` 是 dataclass，不是 Mapping）。

    读不出来（`None` / 别的类型）就返回空表，且只在最后一个分支返回它 ——
    调用方必须把"空表"读成"这一格判不了"，不是"没有定位"。
    """
    import dataclasses

    if isinstance(value, Mapping):
        return dict(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
    return {}


def declarations_candidates(name: str, names: Iterable[str], *, limit: int = 3) -> list[str]:
    """错名的并列候选（薄转发到 `tools.base.candidate_tool_names`，判据只有一份）。

    为什么在这里再包一层：秘书不使用注册工具，但它必须能回答
    "这个名字是不是真名"（职责 1）。转发而不是重写 —— 两份候选算法必然分叉，
    而分叉的形态是"机器给的候选与秘书给的候选不是同一批"。
    """
    from .tools.base import candidate_tool_names

    return candidate_tool_names(name, names, limit=limit)


class Secretary:
    """一名智能体的秘书（`draft/53` v3 §4：一个共享类 + 每角色一个实例）。

    参数
    ----
    role : 它服务的那名智能体（`"M"` / `"A"`…/`"V"`）。台账按它分文件。
    root : 工作区根（手稿通道与台账都挂在它下面）。
    store : 可选的 `Store`（只读：`tasks` / 会话事件）。给了就读，不给就跳过那一层读数。
    registry : 可选的工具注册表（只读：判"工具名是不是真名"）。
    seam : 可选的 `LlmSeam`（用本智能体自己的缝，`scope="secretary"`）。
        不给 ⇒ 判断那一格判不了（`judge()` 返回 `checked=False`），预筛与留痕照常。
    enable_model : 要不要用模型做"判断"（见 :meth:`judge`）。默认 False：
        确定性预筛是机器该做的，而"要不要为此花钱"是一次明确的取舍（`P-09` 的粒度）。
        生产装配把它打开是一行的事（`Secretary(..., seam=<本体的缝>, enable_model=True)`）。
    log : 可选日志口子（失败留痕的第二个落点）。

    本类没有写集：它不 `store.tx(...)`、不写任何库表、不改任何受保护文件。

    两类产物分得很清（这是本项目最忌的那种折平）：

    | 类 | 判据 | 形态 | 例子 |
    |---|---|---|---|
    | 预筛 | 确定性、来自既有声明 | 报警清单（字符串） | 参数缺必填 / 工具名不是真名 / 动作不在能力表 |
    | 判断 | 需要语义、"该不该" | :meth:`judge` 一次模型调用 + 台账 | 重复候选算不算正当重试 / 错名映到哪个 / 建议重排成什么 |
    """

    def __init__(self, role: str, *, root: str | Path, store: Any = None,
                 registry: Any = None, seam: Any = None, log: Any = None,
                 deadline_sec: float = DEFAULT_DEADLINE_SEC,
                 enable_model: bool = False, sid: str | None = None) -> None:
        self.role = str(role)
        self.root = Path(str(root))
        self.store = store
        self.registry = registry
        self.seam = seam
        self.log = log
        self.deadline_sec = float(deadline_sec)
        #: 会话号（花销归因要读 `llm_call` 事件；`None` = 缺省会话，与 `llmseam` 同一口径）。
        self.sid = sid
        #: 判断类要不要真发一次模型调用（`draft/53` §12 / `draft/55` §5.2）。
        #: 关着的时候 :meth:`judge` 仍然返回三态中的"没查成"（`checked=False` + 理由），
        #: 于是"判断没做"与"判断过了、可派"在台账上永远分得开。
        #:
        #: 生产装配由 `agent_loop._secretary_for` 打开它（主控裁定 A5）：
        #: 用本体自己的那一个缝（同一个实例 ⇒ 角色/scope/账本一致，钱记在同一条账上）。
        self.enable_model = bool(enable_model)
        #: 写集恒为 ∅ 的声明式落点：它让"秘书有没有写集"成为一个可读的事实，
        #: 而不是"读遍本文件找不到 store.tx 所以大概没有"。
        self.writes: frozenset[str] = frozenset()
        self._negotiations: list[dict[str, Any]] = []
        #: 最近一次判断的墙钟（秒）与最近一次闭环该不该介入的读数 —— 都是读数，
        #: 不是判据（fail-open 的代价要看得见，但不许拿它去卡任何一条委托）。
        self._last_judge_elapsed = 0.0
        self._last_closure_engage = False

    # ------------------------------------------------------------ 台账（E 类：记录）

    def decisions(self) -> list[dict[str, Any]]:
        """本角色台账里的全部行（坏行读不出来 ⇒ 如实报，不折成"没有决定"）。

        `read_jsonl` 把坏行单独报出来；这里只交回行，坏行由 :meth:`decision_problems` 报。
        """
        return self._read_ledger()[0]

    def decision_problems(self) -> list[str]:
        """台账里的坏行说明（空列表 = 全都读得出来）。"""
        return self._read_ledger()[1]

    def _read_ledger(self) -> tuple[list[dict[str, Any]], list[str]]:
        from . import jsonlfile as JF

        return JF.read_jsonl(decisions_path(self.root, self.role))

    def note_decision(self, *, duty: int, kind: str = KIND_DECISION, decision: str = "",
                      reason: str = "", basis: Sequence[str] = (), target: Any = None,
                      before: str = "", after: str = "", mid: str = "",
                      negotiation: Sequence[Mapping[str, Any]] = (), fail_open: bool = False,
                      error: str = "", judge: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """追加一行台账（`draft/55` §5.3 的字段表）。

        原文与加工后并列（`before` / `after`）：只留结论会让复核无从下手 ——
        "过程"是这一层唯一能自证的东西。
        """
        rows, _problems = self._read_ledger()
        seq = max((int(r.get("seq") or 0) for r in rows), default=0) + 1
        rec: dict[str, Any] = {
            "seq": seq,
            "at": _now_iso(),
            "role": self.role,
            "duty": int(duty),
            "kind": str(kind or KIND_DECISION),
            "from": f"secretary/{self.role}",
            "fail_open": bool(fail_open),
        }
        if target is not None:
            rec["target"] = target
        if before:
            rec["before"] = str(before)
        if after:
            rec["after"] = str(after)
        if decision:
            rec["decision"] = str(decision)
        if reason:
            rec["reason"] = str(reason)
        if basis:
            rec["basis"] = [str(x) for x in basis]
        if negotiation:
            rec["negotiation"] = [dict(x) for x in negotiation]
        if judge is not None:
            # 判断类的那一格：`checked` / `decision` / `reason` 一起落台账 ——
            # 只落结论会让"没查成"与"查过了没问题"在纸上长得一样。
            rec["judge"] = dict(judge)
        if mid:
            rec["mid"] = str(mid)
        if error:
            rec["error"] = str(error)
        path = decisions_path(self.root, self.role)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError as exc:
            # 台账写不成不许带走秘书的判断（fail-open 的第一层：留痕是手段不是目的）。
            # 但也不静默：日志口子与返回值两条路都留下这件事。
            self._log(f"秘书台账没写成：{type(exc).__name__}: {exc}")
            rec["ledger_problem"] = f"{type(exc).__name__}: {exc}"
        return rec

    # ------------------------------------------------------------ 知识面（只读，§1）

    def knowledge(self) -> dict[str, Any]:
        """秘书能读什么（全部只读，`draft/55` §1）。

        四层：硬性要求 / 全角色的定位（组织图全开）/ 委托事实 / 读数。
        返回一个可读的事实表（不是权限授予）：`writes` 恒为 `∅`，
        `reads_narrative` 回答"它读不读研究叙事正文"（一般角色不读、V 更严）。
        """
        briefs: dict[str, dict[str, Any]] = {}
        emphasis: dict[str, Any] = {}
        for role in S.ROLES:
            one = self._role_brief(role)
            if one:
                briefs[role] = dict(one)
        actions = self._action_table()
        return {
            "roles": sorted(set(S.ROLES) | {S.CONDUCTOR_ROLE}),
            "briefs": briefs,
            "emphasis": emphasis,
            "actions": actions,
            "tools": self._tool_names(),
            "writes": self.writes,
            "reads_narrative": False,
            "ledger": str(decisions_path(self.root, self.role)),
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

        ## 口径：预筛的准确度取决于装配时给它的那份注册表

        秘书只用已有声明判（注册表的真名 + `specs/<role>.py` 的参数表），
        不新增机器判据（`draft/55` §4）。所以"这份真名表全不全"直接决定预筛对不对：
        给错一份残缺的注册表，就会把真名报成"不是真名"（假阳性）。

        ## 为什么 fallback 必须带 `store`（2026-10-04 主控探针实测的缺陷）

        没有 `registry` 时的 fallback 原先是 `build_registry()` —— 不带 `store`。
        实测：`build_registry()` 出 68 件真名且 `fs.read` 不在里面；
        `build_registry(store=...)` 出 81 件、`fs.read` 在里面。
        于是任何 `registry=None` 的调用方（`for_role(..., registry=None)` 是默认）
        都会对 `fs.read` 这种真名报警
        `'fs.read' 不是注册表里的真名；并列候选：['manuscripts.read','table.create']`
        （真名被判成错名 ⇒ 预筛的第一类假阳性，而 `self.store` 就在手边）。

        三态：`store` 也没有 ⇒ 保持"造不出来就给空表"的老行为（`[]`），
        空表在调用方那一侧只能是"没读到"，不许读成"没有真名"。
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
        try:
            from .tools import build_registry

            return sorted(str(x) for x in build_registry(store=self.store).registry.names())
        except Exception:  # noqa: BLE001 - 造不出来 ⇒ 空表（"没读到"不许读成"没有真名"）
            return []

    # ------------------------------------------------------------ 机器预筛（§6）

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
        if table and want_role in table and str(action) not in table.get(want_role, []):
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

            spec = C.find_action(role, action)
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

    #: 三处"判断类"（`draft/55` §2 的 B 类；用户口径"切勿全写死成机器判据"）。
    JUDGE_KINDS = ("duplicate_retry", "tool_name", "rearrange")

    def judge(self, kind: str, context: Mapping[str, Any], *, task_id: str = "") -> dict[str, Any]:
        """判断类：用本智能体自己的缝做一次模型调用，把结论落台账。

        三处判断（`draft/53` §10 的三条"改判给秘书"）：

        - `duplicate_retry`：同 key 的既有终态行算重复还是正当重试（机器只摆出来）；
        - `tool_name`：错名映到哪一个候选（或一个都不映：那是"这次不该调工具"）；
        - `rearrange`：建议重排成什么（改派权仍在 M，这里只给建议）。

        三态（`R002`/P16 的口径）：

        | 结局 | 返回 |
        |---|---|
        | 判断做了 | `{"checked": True, "decision": …, "reason": …, "basis": […]}` |
        | 没缝 / 没开 / 超时 / 坏 JSON | `{"checked": False, "reason": …}` |

        "没查成"绝不被读成"可派"：调用方（:meth:`assess_delegation`）只在
        `checked=True` 时才采信 `decision`。

        每一次真的发起过调用的结局都带 `cost`（见 :meth:`last_judge_cost`）：
        "这次判断花了哪一笔钱"必须能从台账追回账本，否则它是一笔不可归因的花销。
        """
        if kind not in self.JUDGE_KINDS:
            return {"checked": False,
                    "reason": f"不认识的判断类别 {kind!r}（认 {list(self.JUDGE_KINDS)}）",
                    "cost": {"ledger": "", "reason": "没发调用（类别不认识）"}}
        if self.seam is None:
            return {"checked": False,
                    "reason": "没有装配模型缝（本智能体自己的 llmseam）⇒ 这一格没查成",
                    "cost": {"ledger": "", "reason": "没发调用（没有缝）"}}
        if not self.enable_model:
            return {"checked": False,
                    "reason": "enable_model=False（判断类的模型调用被显式关掉）⇒ 这一格没查成",
                    "cost": {"ledger": "", "reason": "没发调用（开关关着）"}}
        t0 = time.monotonic()
        try:
            data, call = self.seam.ask_json(_judge_prompt(kind, context),
                                            task_id=task_id, note=f"secretary:{kind}")
        except Exception as exc:  # noqa: BLE001 - fail-open：超时/出错 ⇒ 没查成 + 留痕
            return self._record_judge(kind, context, {
                "checked": False, "reason": f"调用失败：{type(exc).__name__}: {exc}",
                "cost": self.last_judge_cost(kind)})
        finally:
            self._last_judge_elapsed = round(time.monotonic() - t0, 3)
        cost = self.last_judge_cost(kind)
        if not getattr(call, "ok", False) or data is None:
            return self._record_judge(kind, context, {
                "checked": False,
                "reason": f"没查成（{getattr(call, 'problem', '') or 'no_reply'}）："
                          f"{str(getattr(call, 'detail', '') or '')[:200]}",
                "cost": cost})
        decision = str(data.get("decision") or "").strip()
        if decision not in DECISIONS:
            return self._record_judge(kind, context, {
                "checked": False,
                "reason": f"模型给的结论 {decision!r} 不在词表 {list(DECISIONS)} 里 ⇒ 不采信",
                "cost": cost})
        return self._record_judge(kind, context, {
            "checked": True, "decision": decision,
            "reason": str(data.get("reason") or "")[:500],
            "basis": [str(x) for x in (data.get("basis") or [])][:5],
            "elapsed_sec": self._last_judge_elapsed, "cost": cost})

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
        self.note_decision(
            duty=2, kind=KIND_DECISION,
            decision=str(result.get("decision") or "建议重排"),
            reason=str(result.get("reason") or ""),
            basis=basis, target={"judge": kind}, judge=result,
            before=json.dumps(dict(context), ensure_ascii=False, sort_keys=True,
                              default=str)[:2000],
            fail_open=False,
        )
        return result

    def last_judge_cost(self, kind: str) -> dict[str, Any]:
        """上一次该类别判断的花销归因（主控裁定 A5 的第 ③ 条）。

        权威来源是缝自己落的那条审计事件：`llmseam._land` 把"这次的钱记进账本了吗、
        记成哪一行"写进 `llm_call` 事件的 `ledger` 字段（`usage_id` / `reason`），
        所以这里读那条事件，而不是让秘书猜自己的花销。

        三态（取不到就如实写，不许折成"花了 0"）：

        | 情形 | 返回 |
        |---|---|
        | 入账了 | `ledger = "<usage_id>"` |
        | 没入账（`no_meter` / `duplicate` / 没发请求） | `ledger = ""` + `reason` 逐字来自事件 |
        | 读不到事件 / 读不出会话 | `ledger = ""` + `reason = "查不到：…"` |

        `call_index` 是与 `usage_id` 并列的第二归因口径（缝的幂等键就用它），
        两者都给，读的人才能把"账本行"与"第几次调用"对上。
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

    # ------------------------------------------------------------ 职责 1 / 2（发件侧）

    def _message_alarms(self, payload: Mapping[str, Any], *, admission: Any = None) -> list[str]:
        """`message`（跨智能体的结构化交互）的预筛：准入判据 + 两个必填字段。

        三态纪律：判据没接上时如实报"这一格判不了（没查成不是没问题）"，
        绝不因为拿不到判据就当它通过。

        为什么不自己判协作边：判据本体只有一份（`agent_loop.message_admission`），
        由 `AgentLoop._outbound_hook` 通过 `admission=` 注入进来。本文件里再查一次
        协作边（`agent_prompts` 那一支）就是长出了第二份实现，而两份漂了没有任何东西会红
        （判据：`tests/test_secretary.py` 里那条 AST 扫描 —— 它扫的是调用，不是措辞）。

        缺 `subject`/`body` 只报警、不替它编内容（职责 1 的既有纪律：秘书给建议，
        不改实质、不代笔）。
        """
        out: list[str] = []
        to = str(payload.get("to") or "")
        reply_to = str(payload.get("reply_to") or "")
        if admission is None:
            out.append("message 的协作边准入判据没接上 ⇒ 这一格判不了（没查成不是没问题）")
        else:
            try:
                reason = str(admission(self.role, to, reply_to) or "")
            except Exception as exc:  # noqa: BLE001 - 判据自己坏了也是"判不了"
                reason = f"message 的准入判据自己出错了（{type(exc).__name__}: {exc}）⇒ 这一格判不了"
            if reason:
                out.append(reason)
        for field in ("subject", "body"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                out.append(f"message 的 `{field}` 要是非空字符串（缺了不替它编内容）")
        return out

    def optimize_outbound(self, shape: str, payload: Mapping[str, Any], *,
                          admission: Any = None) -> dict[str, Any]:
        """职责 1：格式与内容优化（发件前）。

        不改变实质主张：不替本体承诺、不改结论、不加证据（`draft/53` §2 的
        "不许做"）。所以这里的产物是"建议 + 并列候选"，而不是改写后的载荷：
        本体读到的仍是它自己那一份（改不改由它决定）。

        两段分得很清（这是"切勿全写死成机器判据"的落点）：

        - 第一段是预筛（确定性）：参数表 / 必填 / 工具真名的检查，来自既有声明；
        - 第二段是判断（只有 :meth:`should_engage` 说该介入时才走）：错名映到
          哪一个候选（:meth:`judge` 的 `tool_name` 一类，一次模型调用 + 台账）。
          判断没查成 ⇒ 结论仍是预筛那一份，且台账里 `judge.checked=False` 写明。

        fail-open：超时/自己出错 ⇒ 原样放行 + 台账留痕（`fail_open=True`）。
        """
        original = dict(payload)
        t0 = time.monotonic()
        try:
            if time.monotonic() - t0 > self.deadline_sec:
                raise TimeoutError("秘书超过单次调用上限")
            to = str(payload.get("to") or payload.get("role") or "")
            action = str(payload.get("action") or "")
            params = payload.get("params") if isinstance(payload.get("params"), Mapping) else {}
            tool = str(payload.get("name") or payload.get("tool") or "")
            if shape == "message":
                # `R8`：`message` 是跨智能体的结构化交互 ⇒ 秘书接管（所有者裁定逐字
                # "如果有些形状涉及到结构化交互，则需要秘书接管"）。接管 = 预筛报警 +
                # 建议 + 台账（不替代 `_do_message` 的硬闸，也不改载荷）。
                #
                # 为什么这一支不跑上面那条委派预筛：`message` 没有 `action`/`params`/`tool`
                # 三件，而预筛会把 `to` 当角色名去查能力表 —— 对 `to=#public` 会报出两条
                # "读不到 #public 的角色定位"的假警（频道名不是角色）。它的整个预筛面
                # 就是下面这两格：共用准入判据 + 两个必填字段。
                alarms = self._message_alarms(payload, admission=admission)
            else:
                alarms = self.prescreen(to=to, action=action, params=params or {}, tool=tool)
            # 预筛报警不是"判决"：它只说"照声明看不合规"，改法（映到哪个名字、
            # 补哪个字段）是判断 ⇒ 只有该介入时才叫模型。
            judged: dict[str, Any] = {"checked": False, "reason": "预筛没有报警 ⇒ 不必判断"}
            engage = self.should_engage(alarms=alarms, duplicates=0, overdue=0, novel=bool(tool))
            if engage and tool and any("真名" in a for a in alarms):
                judged = self.judge("tool_name", {"tool": tool, "to": to,
                                                  "candidates": declarations_candidates(
                                                      tool, self._tool_names())})
            decision = ("已优化" if not alarms else "建议重排")
            if judged.get("checked"):
                decision = str(judged.get("decision") or decision)
            rec = self.note_decision(
                duty=1, kind=KIND_OPTIMIZED, decision=decision,
                reason="；".join(alarms) or "没有触发预筛报警（原样放行）",
                basis=["specs/<role>.py 的参数表", "tools.build_registry() 的真名"],
                target={"to": to, "action": action}, judge=judged,
                before=json.dumps(original, ensure_ascii=False, sort_keys=True)[:2000],
                fail_open=False,
            )
            return {"problem": "；".join(alarms), "payload": original, "alarms": alarms,
                    "judge": judged, "engaged": bool(engage), "fail_open": False,
                    "seq": rec.get("seq")}
        except Exception as exc:  # noqa: BLE001 - fail-open：超时/出错一律放行
            self.note_decision(duty=1, kind=KIND_OPTIMIZED, decision="已优化",
                               reason="秘书没跑成 ⇒ 原样放行", fail_open=True,
                               error=f"{type(exc).__name__}: {exc}",
                               before=json.dumps(original, ensure_ascii=False, sort_keys=True)[:2000])
            self._log(f"秘书优化没跑成（原样放行）：{type(exc).__name__}: {exc}")
            return {"problem": f"{type(exc).__name__}: {exc}", "payload": original,
                    "alarms": [], "fail_open": True}

    def assess_delegation(self, *, to: str, action: str, params: Mapping[str, Any],
                          input_key: str = "", duplicates: Sequence[Mapping[str, Any]] = (),
                          novel: bool = False) -> dict[str, Any]:
        """职责 2：委派评估（"收件方真做得到吗、该不该派"）。

        结论 ∈ :data:`DECISIONS` 的四档（`draft/55` §2 的 B 类）+ 理由 + 依据。
        不擅自改派（改派权在 M）：它只给建议，本体可拒绝并写明理由。

        同 key 的既有终态行是最重要的一条输入（`draft/53` §10：派活去重归发件方
        秘书，"该不该派"含"是不是重复"）—— 机器只把那些行摆出来，判"算重复
        还是正当重试"由秘书做。
        """
        dups = [dict(r) for r in duplicates]
        alarms = self.prescreen(to=to, action=action, params=params)
        mismatch = [a for a in alarms if "动作表里没有" in a or "缺必填参数" in a]
        if dups and not mismatch:
            decision, reason = "建议重排", (f"同 (role={to}, action={action}, "
                                          f"input_key={input_key}) 已有 {len(dups)} 条终态行"
                                          "（先看一眼是不是同一件事的重试）")
        elif mismatch:
            decision, reason = "建议重排", "；".join(mismatch)
        elif not self._can_take(to, action):
            decision, reason = "建议改派", (f"{to} 的能力面里没有 {action}"
                                          "（改派权在 M：这只是建议）")
        else:
            decision, reason = "可派", "没有发现重复候选，能力面与参数都对得上"
        basis = ["specs/<role>.py 的动作表", "tasks: 同 key 的既有终态行"]
        # ---- 判断类：只有该介入时才叫模型（"切勿全写死成机器判据"的落点）。
        # 两条判断分开问，因为它们是两个问题：同 key 那些行算不算重复（`duplicate_retry`）、
        # 以及该把这条委托重排成什么（`rearrange`）。
        judged: dict[str, Any] = {"checked": False, "reason": "预筛没有报警、也没有重复候选 ⇒ 不必判断"}
        engaged = self.should_engage(alarms=alarms, duplicates=len(dups), overdue=0,
                                    novel=bool(novel))
        if engaged:
            kind = "duplicate_retry" if dups else "rearrange"
            judged = self.judge(kind, {"to": to, "action": action, "params": dict(params or {}),
                                       "input_key": input_key, "duplicates": dups[:5],
                                       "alarms": alarms,
                                       "preliminary": decision})
            if judged.get("checked"):
                # 模型的结论覆盖"预筛给的初步结论"，但它只能给建议（改派权在 M），
                # 而且只在 `checked=True` 时才被采信 —— "没查成"不冒充"可派"。
                decision = str(judged.get("decision") or decision)
                if judged.get("reason"):
                    reason = f"{reason}；判断：{judged['reason']}"
                basis = list(basis) + list(judged.get("basis") or [])
        rec = self.note_decision(
            duty=2, kind=KIND_PROPOSAL, decision=decision, reason=reason, basis=basis,
            target={"to": to, "action": action, "input_key": input_key},
            judge=judged, fail_open=False,
        )
        return {"decision": decision, "reason": reason, "basis": basis,
                "duplicates": dups, "alarms": alarms, "novel": bool(novel),
                "judge": judged, "engaged": bool(engaged), "seq": rec.get("seq")}

    def _can_take(self, role: str, action: str) -> bool:
        """`role` 的动作表里有没有 `action`（读不到声明 ⇒ 判"能"：不冤枉）。"""
        table = self._action_table()
        if not table or str(role) not in table:
            return True
        return str(action) in table[str(role)]

    # ------------------------------------------------------------ 职责 4 / 3（收件侧）

    def rework_inbound(self, item: Mapping[str, Any]) -> dict[str, Any]:
        """职责 4：按本角色定位把收到的委托加工成贴切版本。

        不加码不减码（`draft/53` §2 的"不许做"）：只改"怎么说"，不改"要什么"。
        所以产物是"补上下文 + 明确产出物与验收口径"的补充段，原文一字不动
        （并列留痕：`draft/55` §5.1 第 3 条）。
        """
        original = dict(item)
        try:
            brief = self._role_brief(self.role)
            tail = []
            deliverable = str(brief.get("deliverable") or "").strip()
            if deliverable:
                tail.append(f"我的产出物口径：{deliverable}")
            duty = str(brief.get("duty") or "").strip()
            if duty:
                tail.append(f"我在本条线上的位置：{duty}")
            note = "\n".join(tail)
            problem = ""
            if not tail:
                problem = ("读不到本角色的 `deliverable`/`duty` ⇒ 这一格判不了"
                           "（没读成不是没问题）")
            self.note_decision(duty=4, kind=KIND_OPTIMIZED, decision="已优化",
                               reason=problem or "按本角色定位补上下文（不加码不减码）",
                               basis=["agent_prompts.ROLE_BRIEFS"],
                               before=json.dumps(original, ensure_ascii=False, sort_keys=True)[:2000],
                               after=note[:2000])
            return {"item": original, "addendum": note, "problem": problem, "fail_open": False}
        except Exception as exc:  # noqa: BLE001 - fail-open
            self.note_decision(duty=4, kind=KIND_OPTIMIZED, fail_open=True,
                               error=f"{type(exc).__name__}: {exc}",
                               reason="秘书没跑成 ⇒ 原样交给本体")
            return {"item": original, "addendum": "", "problem": f"{type(exc).__name__}: {exc}",
                    "fail_open": True}

    def inbox_todos(self, *, limit: int = 20) -> dict[str, Any]:
        """F-05 的消费端：把"还没有处理 / 还没有反馈"的委托摆出来（只读）。

        `draft/53` §10 的口径：F-05 待办/待核队列的生产端是机器
        （`search_requests` / `reprocess_requests` 的 pending，以及降级/待核那些三态行），
        消费端是各角色自己的秘书（自己的收件箱）+ M 的秘书（全局）。
        本方法只做"摆出来"这一半，判断归 :meth:`remind_closure`。

        三态（R002 的口径）：`checked=False` + `reason` 表示"这一格没读成"
        （没有 store / 表读不出来），与 `todos=[]`（读成了、确实没有待办）分开报。

        返回值：`{"checked", "reason", "todos": [...], "count", "by_kind"}`，
        每条 `todo` 是 `{"kind", "id", "who", "state", "since"}` —— `state` 说的是
        "为什么它算待办"（`pending` 没做完 / `unclaimed` 没人接 / `running` 没有终态）。
        """
        if self.store is None:
            return {"checked": False, "reason": "没有 store ⇒ 收件箱这一格没读成",
                    "todos": [], "count": 0, "by_kind": {}}
        todos: list[dict[str, Any]] = []
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
                todos.append({
                    "kind": kind,
                    "id": str(row.get("request_id") or ""),
                    "who": who or S.CONDUCTOR_ROLE,
                    "state": "pending" if who else "unclaimed",
                    "since": str(row.get("timestamp") or ""),
                    "attempts": int(row.get("attempts") or 0),
                })
        excluded_top = 0
        try:
            for row in self.store.rows("tasks"):
                if str(row.get("status") or "") not in ("pending", "running"):
                    continue
                # 顶趟行（`action="run"`，F1 加的）不算待办：它是"用户发起的那一趟
                # 正在跑"，不是"有人提交了却没人接手"——后者才是这份收件箱要摆出来的东西。
                # 排除了几行要留在读数里（`excluded_top_level`），否则"少了几行"会被读成
                # "本来就没有"（静默漂移的另一种形态）。
                if str(row.get("action") or "") == "run":
                    excluded_top += 1
                    continue
                todos.append({"kind": "task", "id": str(row.get("task_id") or ""),
                              "who": str(row.get("role") or ""), "state": "running",
                              "since": str(row.get("started_at") or "")})
        except Exception as exc:  # noqa: BLE001 - 同上
            problems.append(f"tasks: {type(exc).__name__}: {exc}")
        todos = todos[:max(1, int(limit))]
        by_kind: dict[str, int] = {}
        for t in todos:
            by_kind[t["kind"]] = by_kind.get(t["kind"], 0) + 1
        return {"checked": not problems, "reason": "；".join(problems),
                "excluded_top_level": excluded_top,
                "todos": todos, "count": len(todos), "by_kind": by_kind}

    #: `pending_inbox` 认的既有标记（不许新造字段/词表/工具）。
    PENDING_KINDS = ("missing_bit", "missing_proof", "unverified_quote")

    def pending_inbox(self, *, scope: str = "self", window_sec: int = 86400,
                      limit: int = 50) -> dict[str, Any]:
        """F-05 的消费端：待办/待核队列（只读扫表；落进决定台账）。

        `draft/53:181` 逐字："消费端 = 各角色秘书（自己的收件箱）+
        M 的秘书（全局）" ⇒ 这就是那两个口径：

        | `scope` | 看什么 |
        |---|---|
        | `"self"` | 与本角色有关的那些行（按接手方过滤） |
        | `"global"` | 全部（M 的秘书的全局视图） |

        条目只来自既有标记（不新增表/字段/工具/`status` 取值，主控裁定）：

        1. `missing_bit`：`statements` 行的 `bits` 里那一位没有值（等级由
           `evidencebits.derive_grade` 现算，所以缺位 = 等级会降，不是"没有等级"）；
        2. `missing_proof`：`origin="own_result"` 而 `proof_text` 空
           （自产命题没有证明 ⇒ 现算等级是"猜想"而不是证明级）；
        3. `unverified_quote`：`quote_verified is None` 且这一行已经过了窗口
           （够久了还"没核"= 待核；`quote_reason` 是它自己写的"为什么还没核"）。

        每条给出 `(表, 行 id, 缺什么, 谁该接手)`：接手方从声明派生
        （`capabilities.WRITE_SETS` 里谁能写这张表 / `evidencebits.BIT_OWNERS`），
        不另造一张路由表。

        三态（R002 口径）：`checked=False` + `reason` = 这一格没读成（表读不出来），
        与"读成了、确实没有待办"（`items=[]`）分开报。有内容时逐条落
        :meth:`note_decision` —— 只记录，不写任何库表。
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
                    state = state.get("state", state.get("value"))
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
        不替本体做事、不伪造反馈）。异步、不阻塞本体；
        一次最多 :data:`MAX_REMINDERS` 条（默认 5，避免刷屏）。

        `items=None` ⇒ 自己读待办（:meth:`inbox_todos`，F-05 的消费端）；
        给了就按给的那一份判 —— "谁盯哪个收件箱"由调用方决定（M 的秘书看全局）。
        """
        if items is None:
            got = self.inbox_todos()
            items = list(got["todos"])
            if not got["checked"]:
                # 读不成不是"没有待办"：如实留痕，绝不当成清零。
                self.note_decision(duty=3, kind=KIND_NOTICE, decision="已提醒",
                                   reason=f"待办那一格没读成：{got['reason']}",
                                   basis=["tasks / search_requests / reprocess_requests"],
                                   target={"role": self.role}, fail_open=True,
                                   error=str(got["reason"]))
                return []
        out: list[dict[str, Any]] = []
        for it in list(items)[:MAX_REMINDERS]:
            task_id = str(it.get("task_id") or it.get("id") or "")
            state = str(it.get("state") or "")
            if state in ("handled", "feedback_seen", "closed"):
                continue
            if not state:
                state = "unknown"
            out.append({"task_id": task_id, "state": state,
                        "kind": str(it.get("kind") or ""),
                        "to": str(it.get("by") or it.get("who") or S.CONDUCTOR_ROLE),
                        "note": "这一条委托没有终态 / 没有反馈 ⇒ 提醒本体（经 M）"})
        if out:
            self.note_decision(duty=3, kind=KIND_NOTICE, decision="已提醒",
                               reason=f"{len(out)} 条未闭环（留痕 ≠ 被处理）",
                               basis=["tasks: 无终态行 / sessions: 无 task_end"],
                               target={"role": self.role}, fail_open=False)
            # 逐条落台账（2026-10-04 主控裁定的第 1 条："每条进决定台账"）：
            # 只落一行摘要的话，"提醒了谁、什么事、什么状态"在纸上查不到 ——
            # 而这一层唯一能自证的就是台账（`draft/55` §5.3）。
            for one in out:
                self.note_decision(
                    duty=3, kind=KIND_NOTICE, decision="已提醒",
                    reason=f"未闭环：{one['state']}（{one['task_id'] or '无 id'}）",
                    basis=["tasks: 无终态行 / sessions: 无 task_end"],
                    target={"task_id": one["task_id"], "state": one["state"],
                            "kind": one["kind"], "to": one["to"]},
                    fail_open=False)
            # 闭环提醒是异步的（`draft/55` §5.2）：不阻塞本体，所以这一格只记
            # "该不该叫秘书"的读数（要不要真叫由调用方按 `should_engage` 走）。
        self._last_closure_engage = self.should_engage(alarms=[], duplicates=0,
                                                      overdue=len(out), novel=False)
        return out

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

    # ------------------------------------------------------------ 手稿通道（增 / 改 / 查）

    def handoff_add(self, *, to: str, summary: str, body: str, refs: Iterable[str] = (),
                    task_id: str = "", sid: str = "", note: str = "") -> dict[str, Any]:
        """增：替本体执笔一行交接手稿（`manuscripts.write`）。

        这一格不许 fail-open：写失败必须报错留痕（`draft/55` §5.2）。
        静默放行的后果是"手稿缺行"，而缺行与"没交接"在账本上长得一样 ——
        那会让下一次"这条是不是已经交接过"判错。所以这里 `raise` 之后再留痕。
        """
        try:
            rec = MS.write(self.root, sender=self.role, recipient=str(to).upper(),
                           summary=str(summary), body=str(body), refs=list(refs),
                           task_id=str(task_id), sid=str(sid), note=str(note))
        except Exception as exc:
            self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                               reason="手稿执笔失败（这一格不许静默放行）",
                               basis=["draft/55 §5.2"], mid="", fail_open=False,
                               error=f"{type(exc).__name__}: {exc}",
                               target={"to": str(to)})
            raise
        self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                           reason="替本体执笔一行交接手稿（sender 仍是被服务的角色）",
                           basis=["draft/55 §4 归属与审计"], mid=str(rec.get("id") or ""),
                           target={"to": str(to)}, fail_open=False)
        return rec

    def handoff_revise(self, *, mid: str, summary: str = "", body: str = "",
                       reason: str = "", note: str = "") -> dict[str, Any]:
        """改：追加一条修订行（`manuscripts.revise`，旧行保留）。

        与 :meth:`handoff_add` 同一条纪律：写失败必须报错留痕。
        """
        try:
            rec = MS.revise(self.root, mid=str(mid), summary=str(summary), body=str(body),
                            reason=str(reason), note=str(note))
        except Exception as exc:
            self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                               reason="手稿订正失败（这一格不许静默放行）",
                               basis=["draft/55 §5.2"], mid=str(mid), fail_open=False,
                               error=f"{type(exc).__name__}: {exc}")
            raise
        self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                           reason=f"追加修订行（订正 {mid}，旧行保留）",
                           basis=["draft/53 §2.1 改", "draft/55 §3.1"],
                           mid=str(rec.get("id") or ""), target={"revises": str(mid)})
        return rec

    def handoff_query(self, *, mid: str = "", to: str = "", sender: str = "",
                      refs: str = "", revises: str = "") -> list[dict[str, Any]]:
        """查：判"这条是不是重复委派 / 是不是已经交接过"（用户点名的"至少要能读 handoffs"）。

        纯只读；`revises` 非空时只回"订正过某一号"的那些行。
        """
        if revises:
            return MS.revisions_of(self.root, revises)
        if mid:
            got = MS.row_of(self.root, mid)
            return [got] if got else []
        out = MS.list_all(self.root, to=str(to), sender=str(sender), limit=50)
        if refs:
            out = [r for r in out if any(str(refs) in str(x) for x in (r.get("refs") or []))]
        return out

    def handoffs_digest(self, *, limit: int = 5) -> str:
        """一小段读数：最近几份交接（判重复时的起点，进提示词用）。"""
        return MS.digest(self.root, limit=limit)

    # ------------------------------------------------------------ 内部

    def _log(self, message: str) -> None:
        if self.log is None:
            return
        try:
            self.log(message)
        except Exception:  # noqa: BLE001 - 日志口子坏了不该带走秘书的判断
            pass


def _judge_prompt(kind: str, context: Mapping[str, Any]) -> str:
    """三类判断的提示词（`draft/55` §2 的 B 类）。

    契约三句：① 只回一个 JSON 对象；② `decision` 必须取自 :data:`DECISIONS` 的词表
    （词表外的结论一律不采信，见 :meth:`Secretary.judge`）；③ `basis` 写"你凭什么"。
    为什么把词表写进提示词：模型给的自由文本结论无法与台账的 `decision` 栏对齐，
    而"结论栏里出现第八种写法"正是同一件事两个名字的老毛病。
    """
    head = (f"你是「秘书」的判断面（类别：{kind}）。只回一个 JSON 对象，字段："
            f'decision（必须取自 {list(DECISIONS)}）、reason（一句话）、basis（字符串数组，'
            "写清你凭什么，例如 `specs/d.py` 的哪一条或 `tasks` 里的哪一行）。")
    body = json.dumps(dict(context), ensure_ascii=False, sort_keys=True, default=str)[:4000]
    if kind == "duplicate_retry":
        ask = ("问题：同一个 (role, action, input_key) 已经有下面这些终态行。这一次是"
               "正当的重试，还是重复委托？判『可派』= 这次该照派；判『建议不派』= 别重复派。")
    elif kind == "tool_name":
        ask = ("问题：本体写的工具名不在注册表里。要映到下面哪一个候选吗？"
               "判『建议重排』= 映到某一个（在 reason 里写清是哪一个）；"
               "判『建议不派』= 一个都不映（这次不该调工具）。")
    else:
        ask = ("问题：这条委托照声明看不合规（或与收件方的角色定位不匹配）。"
               "该重排成什么？判『建议重排』并在 reason 里给出重排后的说法；"
               "判『建议改派』= 换一个收件方更合适；判『建议不派』= 别派这条。")
    return f"{head}\n\n{ask}\n\n材料：\n{body}\n"


def for_role(role: str, *, root: str | Path, **kw: Any) -> Secretary:
    """造一名某角色的秘书（`draft/53` §5 的"批量给 A–H 装"：批量 = 配置 + 测试）。

    装配点只有两个：`agent_loop.run_role`（所有角色共用的驱动，经
    `agent_loop._secretary_for`）与 `conductor.Conductor`（M 的派活路径）——
    两者都不在 FC-27 名册。生产路径会传 `seam=<本角色自己的 LlmSeam>` 与
    `enable_model=True`（主控裁定 A5），于是三条判断真的发生、花销记在本体账上。
    """
    return Secretary(str(role), root=Path(str(root)), **kw)


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _older_than(stamp: Any, now: str, window_sec: int) -> bool:
    """`stamp` 比 `now` 早了超过 `window_sec` 秒吗（"够久了还没核"的判据）。

    三个"不知道"都回 `False`（不列，而不是"列成待核"）：没有时间戳 / 解析不了 /
    时钟反了。理由：待核队列一旦把"判不了"也列进去，它就会变成"什么都往里塞"的
    假阳性来源（主控点名的那条负控）。
    """
    raw = str(stamp or "").strip()
    if not raw:
        return False
    try:
        then = _dt.datetime.fromisoformat(raw)
        reference = _dt.datetime.fromisoformat(str(now))
    except ValueError:
        return False
    try:
        return (reference - then).total_seconds() > float(window_sec)
    except (TypeError, ValueError):
        return False


def selftest() -> int:
    """最小自检：台账分角色、手稿增改查、fail-open 与"执笔失败必须报错"。"""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="secretary_selftest_"))
    checks: list[tuple[str, bool]] = []
    s = Secretary("D", root=root)
    rec = s.handoff_add(to="F", summary="把猜想交给你", body="证明它。")
    checks.append(("执笔的 sender 是被服务的角色", rec.get("sender") == "D"))
    rev = s.handoff_revise(mid=rec["id"], summary="交接（订正）", body="证明它（第二版）。",
                           reason="引错了一处")
    checks.append(("旧行还在", MS.row_of(root, rec["id"]) is not None))
    checks.append(("订正指回旧行", (MS.row_of(root, rev["id"]) or {}).get("revises") == rec["id"]))
    checks.append(("查得到订正", [r["id"] for r in s.handoff_query(revises=rec["id"])] == [rev["id"]]))
    checks.append(("台账分角色", decisions_path(root, "D").is_file()
                   and not decisions_path(root, "M").exists()))
    loud = False
    try:
        s.handoff_add(to="F", summary="", body="")
    except ValueError:
        loud = True
    checks.append(("执笔失败必须报错（不静默放行）", loud))
    checks.append(("写集恒为 ∅", s.writes == frozenset()))
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())
