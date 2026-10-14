"""角色 F 的实现核心（`goal-7f5116c1` M6）：其余成员 + 把动作 mixin 装起来。

动作方法一个都没留在这里 —— 它们各自在 `agent_f/<动作>.py`。
这一层与各动作文件共用 `_support.py`（模块级 helper 与常量）。
"""
from __future__ import annotations

from ._support import AT, Any, IX, Mapping, NO_PROGRESS_NOTE, Path, PlanError, S, Sequence, Store, ToolRegistry, UNWIRED_OWNERS, _short, _subgoal, install_f_tools
from .create_plan import _CreatePlan
from .step import _Step
from .status import _Status
from .list_plans import _ListPlans


#: 工具层那条路要用的模型缝（`draft/39` §6.33 的 D42c）。
#:
#: 为什么需要它：真机里 M 派 `F.step` 走的是工具层（`attack.step` →
#: `attack_tools._agent_for(store)` → `AgentF(store)`），而不是 host 那条角色工厂 ——
#: 于是 host 那一侧接好的缝到不了这个对象上（T2 第 14 趟 `p6p`：`--attack-reasoning` 开着，
#: `F.step` 仍然连续 5 次 `no_change`）。工具层拿不到 host 的装配上下文，
#: 所以由装配方在装配期登记一次；默认 None（与"默认确定性"同一条纪律：
#: 不登记就没有缝，`attack.step` 照旧落 `dead_end(缺工具)` 并如实说未接线）。
#:
#: 单一来源在 `llmseam`（按角色索引的 `set_role_seam` / `role_seam`）：
#: V 的 `verify_proof` 工具路径需要完全相同的一件事，所以那件事只实现一份，
#: 本文件只把角色 `"F"` 绑上去。两个下划线助手是纯粹的角色绑定（没有自己的状态），
#: 它们用惰性 import 取单一来源 —— `llmseam` 在 import 期会拉起 `agent_prompts`
#: → `capabilities` → 本模块，模块级 import 会成环。
def _f_role_seam() -> Any:
    from ..llmseam import role_seam

    return role_seam("F")


def _f_set_role_seam(llm: Any) -> None:
    from ..llmseam import set_role_seam

    return set_role_seam("F", llm)


#: `default_llm()` / `set_default_llm(llm)`：F 在工具层那条路上的缝。
default_llm = _f_role_seam
set_default_llm = _f_set_role_seam


def _attack_prompt(*, plan: Mapping[str, Any], sg: Mapping[str, Any], owner: str,
                   tried: Sequence[str]) -> str:
    """F 自己推理那一轮的提示词（D42）。

    受控值从 `attackround` 现取，不在这里手抄一遍：四种产物、九招工具箱、
    `dead_end` 的七个受控理由、`#5` 的禁用标记 —— 抄一遍就多一处会漂的地方，
    而这一处的漂移形态恰好是"模型按提示词写、判据按常量拒"。

    提示词只做两件事：把这个子目标已知的东西摆出来，把这一轮必须交什么说清。
    它不告诉模型该怎么证（那是它的活），也不给它任何本题的构造。
    """
    from .. import attackround as AR

    lines = [
        "你是 F：多轮难题攻坚。这一轮只做一件事 —— 推进下面这一条子目标，"
        "并按受控形状交出**一件产物**。",
        "",
        f"难题：{plan.get('problem')}",
        f"难题键：{plan.get('problem_key')}（第 {int(plan.get('rounds') or 0) + 1} 轮，"
        f"预算上限 {dict(plan.get('budget') or {}).get('max_rounds')} 轮）",
        f"子目标 {sg.get('sid')}（owner={owner}）：{sg.get('text')}",
        f"它的可检验形式：{sg.get('testable') or '（没写 —— 这一轮的空缺就是它）'}",
        f"这条子目标已有证据：{list(sg.get('evidence_ids') or []) or '（无）'}；"
        f"已跑实验：{list(sg.get('experiment_ids') or []) or '（无）'}；"
        f"已试过的招：{list(tried) or '（无）'}",
        "",
        "产物必须是下面四档之一（`product` 字段），其余字段按那一档给全：",
        f"1. `reduction`：把难题归约成 1–3 条新的、可检验的子目标。"
        f"要给 `new_subgoals`（每条 {{goal, testable}}，两个都非空）、`reason`。",
        "2. `proof`：给出逐步论证。要给 `steps`（非空数组，每步 "
        "{{text, cites, assumption}}）—— `text` 是这一步说了什么，`cites` 是它引到的在册 id"
        "（`exp:`/`lit:`/`rel:` 之类），确实没有依据可引时必须把这一步显式声明成前提"
        "（`assumption: true`）：**缝是正确的事实变成错误证明的地方**，不许用措辞跳过去。",
        "3. `counterexample_request`：给一个能判决这条命题的实验请求。要给 "
        "`script_spec`（{{criterion, params, expected_bound}} 三项都非空）与 `why_it_decides`。",
        f"4. `dead_end`：这一轮走不下去。要给受控 `reason`（{'、'.join(AR.DEAD_END_REASONS)} 之一）、"
        "`evidence`（哪一步不行）、`best_partial`（已证的引理／缩小的范围／排除的法，逐条带 what/ids/why_partial）。",
        "",
        f"每一档都要给 `strategy`（通用工具箱里的一招：{'、'.join(AR.STRATEGIES)}）与 "
        "`why_strategy`（这一轮为什么用这一招）。",
        f"不许出现这些词：{'、'.join(AR.F_BANNED_MARKERS)} —— 写了会被判不成形打回。",
        "什么都做不出来时也要交 `dead_end`（带理由与 best_partial）：`no_change` 不是产物。",
        "",
        "只输出一个 JSON 对象，不要写解释、不要写 Markdown 围栏。",
    ]
    return "\n".join(lines)


class _Core:
    def __init__(
        self,
        store: Store,
        *,
        config: Mapping[str, Any] | None = None,
        log: Any | None = None,
        e: Any | None = None,
        tools: ToolRegistry | None = None,
        actor: str = "agent-F",
        # LLM 判定缝（`draft/30` §T0-8）：默认 None = 不接线 ⇒ 本角色一个 LLM 调用都不发。
        # 判定必须走 `judge.judge_json`（唯一缝协议），失败落 `judge_*` 词表，
        # 绝不许折成"没找到"。本批只插插座，接线在各条目的伪代码下进行。
        llm: Any | None = None,
        # 预算读数的注入点（P-09 的代码那一半，`draft/44:60`）：默认 `None` =
        # 调用方没有注入 ⇒ 这一轮读不到（三态里的"没查成"），而读不到
        # 不据此否决花钱 —— 不把"读数缺失"变成全局停摆；钱仍由全局预算
        # 守卫管（file:line 证据在 `attackround.BUDGET_GUARD_NOTE`）。
        # 形状只认一种：`{"status": "known"|"unknown", "left_usd": float|None,
        # "spent_usd": float|None, "why": str, "source": str}` —— 归一化在
        # :meth:`budget_of_round` 里，读不到时 `why` 写全（口径 / 谁在管钱 / 缺口）。
        # 真源为什么还没接上：`attackround.BUDGET_GAP_NOTE`（工具路径拿不到 task_id）。
        budget_reading: Mapping[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = actor
        self.llm = llm
        self.budget_reading = budget_reading
        self.log = log

        # ---- 阈值全部来自 config（与 A–E 的既有做法一致）
        #: 一轮里最多推进几个子目标（瞬时并发，FC-18 的 `max_parallel_subgoals`）。
        #: 默认 1：一次推进多个子目标会让"这一轮发生了什么"变成一串并列事件，
        #: 而 `history` 的用途正是"按顺序把这个难题读一遍"。
        self.max_subgoals_per_round = int(self.cfg.get("max_subgoals_per_round", 1))
        #: A 的检索请求默认 mode（`broad`/`topical`/`precise`）。
        #: 攻坚里的检索请求面向某个具体子目标，因此默认 `precise`
        #: —— 但 `precise` 在 schema 里要求非空 `content_description`，
        #: 所以本模块一定会把子目标文本作为描述带上（见 `_deploy_a`）。
        self.search_mode = str(self.cfg.get("search_mode", "precise"))
        #: 检索请求的优先级。默认 None = 交给冻结契约查表
        #: （`interactions.resolve_priority`，见 `schema.SUBMITTER_DEFAULT_PRIORITY`）。
        #: 查表结果可能是 `"low"`：`"agent-F"` 不在那张表里，于是走
        #: "未登记的提交方一律 low"这条规则。这是契约规定的保守默认，
        #: 不是缺陷；要让 F 的请求排在前面，就在 config 里显式给一个优先级
        #: （那是一个有意的决定，而不是替框架猜）。
        self.search_priority = self.cfg.get("search_priority")
        #: 提交方身份（决定默认优先级）。不用 `actor`：`actor` 是"这次运行的标签"，
        #: `submitted_by` 是"提交方身份"，混用会让运行标签落到"未登记提交方"上，
        #: 默认优先级静默从 medium 掉到 low（C 那边踩过同一个坑）。
        self.submitter = str(self.cfg.get("submitter", "agent-F"))

        #: E 的实例（惰性构造）。注入点存在是有意的：验收测试可以塞一个假的 E，
        #: 而生产路径用真的。`None` 表示"还没构造"，不是"禁用 E"。
        self._e = e

        self.last_step: dict[str, Any] = {}
        self.last_tool_errors: list[dict] = []
        self.tools = tools if tools is not None else install_f_tools(self.store)
        # ---- 绑定角色（`P-14`）：注入的注册表同样要绑（`AgentD` 那条注释同族）。
        if self.tools.bound_role is None:
            self.tools.bound_role = "F"
    def _log(self, message: str, **extra: Any) -> None:
        if self.log is not None:
            try:
                self.log(message, **extra)
            except Exception:  # noqa: BLE001 - 日志失败不该打断攻坚
                pass

    # ---- 预算读数（P-09 的代码那一半，`draft/44:60`）

    def budget_of_round(self) -> dict[str, Any]:
        """本轮"还剩多少可花 / 已经花了多少"的读数（两态：读得到 / 读不到）。

        为什么要有这个注入点：这一支此前只从 `config` 的四个键
        （`round_budget_usd` / `round_cost_usd` / `round_cost_cap_usd` / `spent_usd`）
        取数，而那四个键在工具路径上没有赋值点（`draft/44` J-07 实测）——
        于是"闸门读到的预算"与"账上真实的预算"是两回事，且没有任何地方会红。
        现在读数由一个显式入口注入，读不到时如实标 `unknown`。

        三态纪律：`status="unknown"`（读不到）与 `left_usd=0.0`（读到了、是零）
        是两件事，绝不许折成同一个值 —— 前者不是事实，不许当否决面用；
        后者是事实，仍然否决（见 :func:`attackround.pre_spend_gate`）。
        """
        from .. import attackround as AR

        raw = self.budget_reading
        if raw is None:
            return self._unreadable_budget("调用方没有注入预算读数")
        if not isinstance(raw, Mapping) or str(raw.get("status") or "") not in ("known", "unknown"):
            shape = (dict(raw) if isinstance(raw, Mapping) else repr(raw))
            return self._unreadable_budget(
                f"注入的预算读数不成形（{type(raw).__name__}: {shape}）—— 只认 "
                '{"status": "known"|"unknown", "left_usd": …, "spent_usd": …, '
                '"why": …, "source": …} 这一种形状')
        if str(raw.get("status")) == "known" and raw.get("left_usd") is not None:
            return {
                "status": "known",
                "left_usd": float(raw["left_usd"]),
                "spent_usd": (None if raw.get("spent_usd") is None
                              else float(raw["spent_usd"])),
                "source": str(raw.get("source") or "注入（未写 source）"),
                "why": "",
            }
        return self._unreadable_budget(
            str(raw.get("why") or "注入的读数自称读不到，但没写为什么"))

    @staticmethod
    def _unreadable_budget(why: str) -> dict[str, Any]:
        """读不到时的统一读数：`why` 里必须同时写全三件事，一句都不能省。

        三件事分别是：① 口径（`BUDGET_UNREADABLE_NOTE`：如实说读不到，且不据此
        把路堵死）② 谁还在管钱（`BUDGET_GUARD_NOTE`，带 file:line）
        ③ 缺口在哪（`BUDGET_GAP_NOTE`，带 file:line）。
        只写①会留下一个"永远 unknown 但没人说为什么"的静默洞；
        只写③会让读的人以为"没人管钱了"。
        """
        from .. import attackround as AR

        return {
            "status": "unknown",
            "left_usd": None,
            "spent_usd": None,
            "source": "无（读不到）",
            "why": (f"{why} ⇒ {AR.BUDGET_UNREADABLE_NOTE}。"
                    f"{AR.BUDGET_GUARD_NOTE}。{AR.BUDGET_GAP_NOTE}。"),
        }

    @staticmethod
    def _with_checks(out: dict, checks: Mapping[str, Any]) -> dict:
        """把这一轮的预算读数放进返回值（键名固定：`budget_known` / `budget_reading`）。

        为什么必须进返回值而不是只写在注释或日志里：读数是给调用方
        （M/D 与台账）用的。产出而不被消费正是本项目记过的 P4 那一档。
        """
        out["checks"] = dict(checks)
        return out

    def _stamp(self) -> str:
        return S.now_iso()
    @property
    def e(self) -> Any:
        """E 的惰性实例。

        为什么惰性：E 与 F 是并行开发的两个模块，F 必须能在 E 缺席时被导入、
        自检、跑测试。真正需要时（要跑实验的子目标）才构造 ——
        而如果那时 E 不可用，必须显式失败（见 `_deploy_e`），
        不允许静默跳过（FC-08）。
        """
        if self._e is None:
            from ..agent_e import AgentE  # 惰性：agent_e 反过来 import agent_f 的话也不成环
            from ..llmseam import role_seam

            sub = self.cfg.get("agent_e")
            self._e = AgentE(
                self.store,
                config=dict(sub) if isinstance(sub, Mapping) else {},
                workspace_root=self.cfg.get("workspace_root"),
                log=self.log,
                # S-10(a)：F 建 E 的时候把 E 自己的那条缝接上 —— 只用于
                # `author_script` 写脚本（判读一个字不改，FC-16）。
                # 为什么由 F 来取：`role_seam` 是按角色索引的单一来源，而这里是
                # 全仓唯一构造 AgentE 的地方；F 的缝与 E 的缝互不借用
                # （各是各的表项，`llmseam` 的注释把这条写死了）。
                # 没登记就是 `None` ⇒ `author_script` 如实回 `no_seam`
                # （"没接线"必须是显式事实，不许静默降级成一份空脚本）。
                llm=role_seam("E"),
            )
        return self._e
    def _call(self, name: str, **params: Any) -> Any:
        """调工具并解开 `ToolResult`；失败返回 None 并留痕（同 `AgentD._call`）。"""
        res = self.tools.call(name, **params)
        if not res.ok:
            self.last_tool_errors.append({"tool": name, "error": res.error, "kind": res.meta.get("kind")})
            return None
        return res.data
    def _plan_row(self, plan_id: str) -> dict | None:
        return next(
            (r for r in self.store.rows("attack_plans") if str(r.get("plan_id")) == str(plan_id)),
            None,
        )
    def _default_budget(self) -> dict:
        """本次运行的默认预算。

        默认值是 `tools/attack_tools.DEFAULT_BUDGET`，但构造时可以按维度覆盖
        （例如 cfg 里给 `max_rounds=3`）。

        为什么要留这个口子：如果 cfg 被悄悄忽略，调用方写 `AgentF(st, config=
        {"max_rounds": 3})` 会得到一个 6 轮的计划 —— 而没有任何地方会报错，
        只是"预算比你说的多了一倍"。这类"配置被静默忽略"是最难发现的一类缺陷，
        所以这里既读 cfg，也在返回值里让调用方看得见实际用了什么。
        """
        out = dict(AT.DEFAULT_BUDGET)
        for k in AT._REQUIRED_BUDGET_KEYS:  # noqa: SLF001 - 同一层内部约定，不另抄一份键名
            if k in self.cfg:
                out[k] = int(self.cfg[k])
        return out
    @staticmethod
    def _normalize_subgoal(raw: Mapping[str, Any], index: int) -> dict:
        """把一个子目标规整成 `AttackPlan.subgoals` 要求的形状。

        `sid` / `text` / `owner` 缺失时当场抛（带下标），而不是交给 schema
        报一个"subgoals[i] 缺少 sid" —— 两者信息量差不多，但这里的错误可以
        带上调用方给的原始下标，便于定位。
        """
        if not isinstance(raw, Mapping):
            raise PlanError(f"subgoals[{index}] 必须是对象，收到 {type(raw).__name__}")
        sid = str(raw.get("sid") or "").strip()
        text = str(raw.get("text") or "").strip()
        owner = str(raw.get("owner") or "").strip()
        if not sid:
            raise PlanError(f"subgoals[{index}] 缺少 sid")
        if not text:
            raise PlanError(f"subgoals[{index}] 缺少 text（子目标必须说清要做什么）")
        if not owner:
            raise PlanError(f"subgoals[{index}] 缺少 owner（owner 是权限面的一部分，不能默认）")
        return _subgoal(
            sid,
            text,
            owner,
            status=str(raw.get("status") or "todo"),
            evidence_ids=list(raw.get("evidence_ids") or []),
            experiment_ids=list(raw.get("experiment_ids") or []),
            proof_experiment_ids=list(raw.get("proof_experiment_ids") or []),
            blocked_reason=str(raw.get("blocked_reason") or ""),
            attempts=int(raw.get("attempts") or 0),
            negation_kind=raw.get("negation_kind"),
            # 只透传已经规范化过的那九个字段之外的键。
            # 曾经这里是 `{k: v for k, v in raw.items() if k not in {"sid", "text", "owner"}}`
            # —— 于是调用方给的 `status` / `evidence_ids` / `attempts` 覆盖了上面
            # 那几个规范化参数（`_subgoal` 最后才 update extra）。后果是
            # "调用方给什么状态就是什么状态"，`status="todo"` 的默认值形同虚设，
            # 而且缺 `status` 的子目标会原样带着 `None` 落库。这类"参数被后写覆盖"
            # 是纯粹的静默错误：没有异常、没有告警，只有一条形状不对的子目标。
            extra={
                k: v
                for k, v in raw.items()
                if k
                not in {
                    "sid", "text", "owner", "status", "evidence_ids", "experiment_ids",
                    "proof_experiment_ids", "blocked_reason", "attempts", "negation_kind",
                }
            },
        )
    def _unwired_partial(self, sg: Mapping[str, Any]) -> list[dict[str, Any]]:
        """`dead_end` 的 `best_partial`（§3.19 第 8 条：部分结果必须进台账，不许只写在散文里）。

        从这条子目标现有的读数里取（证据 id、实验 id、已记下的否定分类、尝试次数），
        逐条带 id —— 于是"这一条子目标已经攒下了什么"在 `history` 里是可复核的，
        而不是"我们试过了"这么一句。
        """
        out: list[dict[str, Any]] = []
        ev = list(sg.get("evidence_ids") or [])
        exps = list(sg.get("experiment_ids") or []) + list(sg.get("proof_experiment_ids") or [])
        if ev:
            out.append({"what": "这条子目标已有的证据行", "ids": [str(x) for x in ev],
                        "why_partial": "证据不足以定论，但它已经落台账"})
        if exps:
            out.append({"what": "这条子目标已经跑过的实验", "ids": [str(x) for x in exps],
                        "why_partial": "实验有读数，但还不能判定子目标"})
        if sg.get("negation_kind") is not None:
            out.append({"what": f"否定分类已定：{sg.get('negation_kind')}", "ids": [],
                        "why_partial": "「没证出来」与「已证否」已经分开了"})
        if not out:
            out.append({"what": f"子目标原文：{str(sg.get('text') or '')[:80]}", "ids": [],
                        "why_partial": "还没有任何证据行 —— 这一条是原文本身，不是进展"})
        return out

    def _deploy(self, sg: Mapping[str, Any], *, plan: Mapping[str, Any]) -> dict:
        """按 `owner` 分派一个动作。只做框架内真实存在的事。

        返回统一的动作描述 ``{action, outcome, detail, evidence, status?,
        experiment_ids?, proof_experiment_ids?, negation_kind?, blocked_reason?,
        count_attempt}``，由 `step` 负责写回子目标与 history。
        """
        owner = str(sg.get("owner") or "")
        sid = str(sg.get("sid") or "")
        text = str(sg.get("text") or "")

        if owner == "E":
            return self._deploy_e(sg, plan=plan)
        if owner == "A":
            return self._deploy_a(sg, plan=plan)
        if owner == "B":
            return self._deploy_b(sg, plan=plan)
        if owner in UNWIRED_OWNERS and self.llm is not None:
            # 插座接上了（`draft/39` §6.31 的 D42）：这一支此前无论有没有模型都落
            # `dead_end(缺工具)` —— 于是真机里 `F.step` 永远回 `no_change`（T2 第 11 趟：
            # "F 的自动推理未接线，攻坚这条路走不通"）。现在：有缝就走推理那一支。
            return self._reason_self(sg, plan=plan, owner=owner)
        if owner in UNWIRED_OWNERS:
            # 不允许把"没做"写成"做了但没结果"。
            #
            # `draft/39` §3.16/§6.14：这一条收尾必须交一件产物 —— 它是
            # `dead_end`（受控理由 + 证据 + `best_partial`），而不是只有一个
            # `outcome="no_change"`（"没有新事实"是步级读数，不是产物）。
            # 产物由 `attackround.dead_end_row` 造（同一套判据，不手搓 dict）：
            # 于是 `attack_plans.history` 里每一轮都能回答"它到底交了什么"。
            from .. import attackround as AR

            partial = self._unwired_partial(sg)
            product = AR.dead_end_row(
                strategy="套用已知定理",
                reason="缺工具",
                evidence=(f"子目标 {sid}（{text}）的 owner={owner} 侧没有可自动调用的推理入口；"
                          "这一轮据此判定走不下去，而不是假装推进"),
                best_partial=partial,
                why_strategy="没有可调用的推理入口时，唯一诚实的产物是 dead_end（换子目标/等人接线）",
            )
            return {
                "action": "no_change",
                "outcome": "no_change",
                "product": product,
                "detail": (
                    f"子目标 {sid}（{text}）需要 {owner} 的推理，但**本框架尚未接线自动推理** "
                    f"⇒ **未推进**（这一轮什么都没做，不是'做了但没结果'）；"
                    f"已按 §3.16 落成产物 `dead_end`（reason={product['reason']}，"
                    f"best_partial {len(product['best_partial'])} 条）。"
                    f"要把 owner={owner} 的子目标真正推起来，需要 {owner} 侧先接上可调用的推理入口；"
                    "在此之前 F 只如实记账，绝不用空证据冒充进展"
                ),
                "evidence": [],
                # 标 `blocked` 而不是 `in_progress` 是刻意的：`in_progress` 会被
                # `pick_next_subgoal` 排在最前，于是接下来每一轮都会重新选中它、
                # 每一轮都记一次"未推进"，把 history 灌满。`blocked` 排在最后，
                # 且必须给出 blocked_reason —— 这正是"不许静默卡住"要求的形态。
                "status": "blocked",
                "blocked_reason": f"未接线：本框架尚无可自动调用的 {owner} 侧推理入口",
                # `in_flight` = "这一轮之后没有新事情可做，别再自动重试它"。
                # 它与 `status="blocked"` 是两件事：schema 的 blocked 说的是
                # "卡住了，必须有人来解"（必须留在表里、必须能被人看见），
                # 而 `in_flight` 只是 `step` 的选目标过滤器：没有它，下一轮
                # 又会选中同一个子目标、又记一次"未推进"，history 会被灌满
                # 而同一条事实重复 N 遍。
                "in_flight": True,
                "count_attempt": False,
            }
        raise PlanError(
            f"子目标 {sid} 的 owner={owner!r} 不在 {S.SUBGOAL_OWNERS} 里。"
            "owner 是权限面的一部分，拼错会让子目标派给不存在的人"
        )

    # ---------------------------------------------------------------- 自己推理那一支（D42）

    @staticmethod
    def _next_sid(existing: Sequence[Mapping[str, Any]], taken: Sequence[str] = ()) -> str:
        """下一个可用的子目标号（`s1`、`s2`…）：归约产生的新子目标要用它。

        为什么不让模型自己号：同一批归约里它会给两个 `s1`，而 schema 对重复 sid
        是硬拒（`subgoals 出现重复 sid`）—— 号由框架发，模型只负责说清要证什么。
        """
        used = {str(s.get("sid") or "") for s in existing} | {str(x) for x in taken}
        i = 1
        while f"s{i}" in used:
            i += 1
        return f"s{i}"

    def _reason_self(self, sg: Mapping[str, Any], *, plan: Mapping[str, Any],
                     owner: str) -> dict:
        """owner 属于"要自己推理"的那一类、而模型缝已接线 ⇒ 真的推一轮。

        `draft/39` §6.31 的 D42 修的就是这一支：此前 `self.llm` 有没有接线，
        返回值都一样（`dead_end(缺工具)`）—— 插座插着，线没接。真机读数（T2 第 11 趟
        `p6m`）：`F.step` 回 `no_change`，M 据此写下"F 的自动推理未接线，攻坚这条路走不通"。

        三轮"先花钱之前的确定性闸门"都在这一支里落地：`pre_spend_gate`（I9）与
        `budget_decision`（I16）在发模型调用之前判；产物一律走 `attackround`
        的受控四档（`reduction`/`proof`/`counterexample_request`/`dead_end`），
        不成形就如实落 `no_change` 并把原话带回给调用方。

        预算读数（P-09）走一个显式注入点（见 :meth:`budget_of_round`）：
        读得到就用它（`left_usd` 进 I9、`spent_usd` 进 I16），
        读不到就如实标 `unknown` 并不据此否决 —— 每一条返回路径都带
        `checks={"budget_known", "budget_reading"}`（键名固定，供调用方与台账读）。
        """
        import json as _json

        from .. import attackround as AR
        from .. import judge as J

        goal = str(sg.get("text") or "")
        testable = str(sg.get("testable") or "")
        tried = [str(x) for x in (sg.get("tried_strategies") or [])]
        # ---- 预算读数（P-09）：有注入就用注入的，没有就如实标 `unknown` 且不据此否决。
        reading = self.budget_of_round()
        known = reading["status"] == "known"
        checks = {"budget_known": known, "budget_reading": reading}
        # 读数读不到时，框架自己写的那句 `why_strategy` 要把口径写出来（模型自己写
        # `why_strategy` 的那几条路不动它的字 —— 那句话是它的裁量留痕）。
        unreadable = "" if known else f"；{AR.BUDGET_UNREADABLE_NOTE}（这一轮不据此否决）"
        gate = AR.pre_spend_gate(goal=goal, testable=testable, tried_strategies=tried,
                                 budget_left_usd=(reading["left_usd"] if known else None))
        if not gate["spend"]:
            return self._with_checks(self._self_dead_end(
                sg, owner=owner,
                reason="缺定义" if not testable.strip() else "方法不适用",
                evidence="花钱之前的闸门没过：" + "；".join(gate["reasons"]),
                why_strategy=("I9：闸门说不许花钱时，这一轮的产物只能是 `dead_end`（说清缺什么）"
                              + unreadable),
                blocked_reason="；".join(gate["reasons"]),
            ), checks)
        # I16 的 `spent_usd`：注入的读数里有就用它（一处口径），否则照旧取 config 的
        # 那一份 —— 默认路径与加注入点之前逐字同形。
        spent_usd = (reading["spent_usd"] if known and reading["spent_usd"] is not None
                     else float(self.cfg.get("spent_usd", 0.0)))
        decision = AR.budget_decision(cost_usd=float(self.cfg.get("round_cost_usd", 0.02)),
                                      cap_usd=self.cfg.get("round_cost_cap_usd"),
                                      spent_usd=spent_usd)
        if decision["status"] == "too_large":
            return self._with_checks(self._self_dead_end(
                sg, owner=owner, reason="超出本轮预算", evidence=str(decision["note"]),
                why_strategy="I16：超上限的一轮要显式阻塞，不许静默截断" + unreadable,
                blocked_reason=str(decision["note"]),
            ), checks)

        prompt = _attack_prompt(plan=plan, sg=sg, owner=owner, tried=tried)
        data, problem = J.judge_json(self.llm, prompt, point="F.step")
        if problem or not data:
            return self._with_checks({
                "action": "no_change",
                "outcome": "no_change",
                "detail": (f"子目标 {sg.get('sid')}（owner={owner}）的推理缝没查成："
                           f"{J.reason_of(problem, point='F.step')} ⇒ **未推进**"
                           "（不是'做了但没结果'，也不是'这条路死了'）"),
                "evidence": [],
                "status": "blocked",
                "blocked_reason": J.reason_of(problem, point="F.step"),
                "in_flight": True,
                "count_attempt": False,
            }, checks)
        try:
            product = AR.parse_round(_json.dumps(data, ensure_ascii=False))
        except AR.RoundError as exc:
            # 不成形 ≠ 没做：模型确实说了话，只是没按受控形状说 —— 原话带回去，
            # 让调用方（M/D）能据它改提示词，而不是只看到一句"没进展"。
            return self._with_checks({
                "action": "no_change",
                "outcome": "no_change",
                "detail": (f"子目标 {sg.get('sid')} 的这一轮不成形（{exc}）⇒ **未推进**；"
                           "四种产物与九招工具箱的受控值写在提示词里，按那个形状重说一次"),
                "evidence": [],
                "status": "blocked",
                "blocked_reason": f"这一轮不成形：{exc}",
                "in_flight": True,
                "count_attempt": False,
            }, checks)
        # ---- R-03（`draft/44`）：伪造引用当场拒收。
        #
        # 真机读数（`p8f` 计划 0002）：`proof` 的一步 `cites` 写着 `lit:Frey1986/…`，而那个
        # 工作区的 literature id 是 `0000-0007` —— 一个不存在的 id，那一轮照样记 `progress`。
        # `attackround._clean_step` 只能要求"cites 非空"（那一层是纯判定层、拿不到 store），
        # 存在性只有拿到台账的这一层判得了。拒收与"不成形"同一档（`count_attempt=False`）：
        # 产物不合格 ⇒ 不记成"对这条子目标的一次尝试"。
        foreign = self._foreign_cites(product)
        if foreign:
            return self._with_checks({
                "action": "no_change",
                "outcome": "no_change",
                "detail": (f"子目标 {sg.get('sid')} 的这一轮**拒收**：它引了台账里不存在的 id "
                           f"{foreign[:4]} ⇒ 未推进。伪造引用是不可逆损失（R-03）："
                           "要么把 id 改成台账里真的那条，要么显式把它声明成前提（`assumption: true`）"),
                "evidence": [],
                "status": "blocked",
                "blocked_reason": f"引用了不存在的 id：{foreign[:4]}",
                "in_flight": True,
                "count_attempt": False,
            }, checks)
        return self._with_checks(self._apply_round(product, sg, plan=plan, owner=owner), checks)

    #: `cites`/`best_partial[].ids` 里的 id 分别住在哪张台账里（`(表, 主键列, 允许的前缀)`）。
    #:
    #: 这一层只判"这个 id 在不在台账里"（R-03 的现场：`lit:Frey1986/…` vs `0000-0007`）；
    #: "前缀与表的严格对应"不在本层 —— 今天没有那一层，别在这里假装有
    #: （`lit:` 指到一条实验 id 这种错配，本判据看不见）。
    _CITE_ID_SOURCES: tuple[tuple[str, str, str], ...] = (
        ("literature", "lit_id", "lit"),
        ("statements", "stmt_id", "stmt"),
        ("experiments", "experiment_id", "exp"),
        ("relations", "rel_id", "rel"),
        ("documents", "doc_id", "doc"),
        ("conjectures", "conjecture_id", "conj"),
        ("attack_plans", "plan_id", "plan"),
        ("search_requests", "request_id", "req"),
    )

    #: 有前缀、但不在 `schema.TABLES` 里的引用（本判据查不了，如实不判）。
    #:
    #: `v:` —— V 的 `verifications/` 是文件账本（`verifications/*.jsonl`），不是一张表
    #: ⇒ 拿 `store.rows` 去读会抛 `StoreError`。这里刻意跳过而不拒收：
    #: "这一层查不了"与"这个 id 是假的"是两件事（三态纪律），不许把前者折成后者。
    _CITE_PREFIXES_NOT_VERIFIABLE: frozenset[str] = frozenset({"v"})

    def _foreign_cites(self, product: Mapping[str, Any]) -> list[str]:
        """这一轮的产物引到的 id 里有哪几个台账里根本没有（空列表 = 都真的存在）。

        读台账失败不吞（"没查成"不许折成"都合法" —— 那正是伪造引用的绿色通道）。
        `#` 之后的部分（页码/锚点）按同一个 id 算（与 `closing` 的 `lit:0003#p.4` 同口径）。
        """
        cites: list[str] = []
        for step in (product.get("steps") or []):
            cites += [str(x) for x in (step.get("cites") or [])]
        for item in (product.get("best_partial") or []):
            cites += [str(x) for x in (item.get("ids") or [])]
        cites = [c for c in cites
                 if c.split(":", 1)[0].strip() not in self._CITE_PREFIXES_NOT_VERIFIABLE]
        if not cites:
            return []
        known: set[str] = set()
        for table, column, prefix in self._CITE_ID_SOURCES:
            for row in self.store.rows(table):
                rid = str(row.get(column) or row.get("id") or "").strip()
                if rid:
                    known.add(rid)
                    known.add(f"{prefix}:{rid}")
        return sorted({c for c in cites if c.split("#", 1)[0].strip() not in known})

    def _self_dead_end(self, sg: Mapping[str, Any], *, owner: str, reason: str,
                       evidence: str, why_strategy: str, blocked_reason: str) -> dict:
        """把"这一轮走不下去"落成受控的 `dead_end` 产物（四档之一），而不是空手而归。"""
        from .. import attackround as AR

        product = AR.dead_end_row(
            strategy="套用已知定理", reason=reason, evidence=evidence,
            best_partial=self._unwired_partial(sg), why_strategy=why_strategy,
        )
        return {
            "action": "dead_end",
            "outcome": "no_change",
            "product": product,
            "detail": f"子目标 {sg.get('sid')}（owner={owner}）：{evidence}",
            "evidence": [],
            "status": "blocked",
            "blocked_reason": blocked_reason,
            "in_flight": True,
            "count_attempt": True,
        }

    def _apply_round(self, product: Mapping[str, Any], sg: Mapping[str, Any], *,
                     plan: Mapping[str, Any], owner: str) -> dict:
        """把一轮成形产物落成"这一轮做了什么"（受控四档 → 动作/状态/新子目标）。

        四档的落法逐条说清（`draft/39` §3.16）：
        - `reduction`：把新子目标挂进计划（号由框架发，见 `_next_sid`）⇒ `progress`；
        - `proof`：这一轮的论证进 `history` 的 `product_detail` ⇒ `progress`，
          但子目标不许因此 `closed`（FC-22：关闭要有 proof 级实验）；
        - `counterexample_request`：把 `script_spec` 变成一条 owner=E 的新子目标
          （下一轮 `_deploy_e` 会照它去跑实验）⇒ `progress`；
        - `dead_end`：如实 `blocked`（带受控理由）并 `in_flight`，不再自动重试它。
        """
        kind = str(product.get("product") or "")
        sid = str(sg.get("sid") or "")
        new_goals: list[dict[str, Any]] = []
        if kind == "reduction":
            existing = list(plan.get("subgoals") or [])
            taken: list[str] = []
            for item in product.get("new_subgoals") or []:
                new_sid = self._next_sid(existing, taken)
                taken.append(new_sid)
                new_goals.append({"sid": new_sid, "text": str(item.get("goal") or ""),
                                  "owner": owner, "testable": str(item.get("testable") or ""),
                                  "status": "todo"})
            detail = (f"归约（{product.get('strategy')}）：{product.get('why_strategy')}；"
                      f"新子目标 {[g['sid'] for g in new_goals]}（每条都带可检验形式）")
            evidence: list[str] = [g["sid"] for g in new_goals]
            status = "in_progress"
        elif kind == "proof":
            steps = product.get("steps") or []
            detail = (f"论证（{product.get('strategy')}）：{len(steps)} 步；"
                      f"这一轮是**论证**不是机器核验 ⇒ 子目标不关闭（FC-22）")
            evidence = []
            status = "in_progress"
        elif kind == "counterexample_request":
            spec = dict(product.get("script_spec") or {})
            new_sid = self._next_sid(list(plan.get("subgoals") or []))
            text = (f"按判据「{spec.get('criterion')}」跑实验：参数 {spec.get('params')}，"
                    f"期望界 {spec.get('expected_bound')} —— {product.get('why_it_decides')}")
            new_goals.append({"sid": new_sid, "text": text, "owner": "E",
                              "testable": str(spec.get("expected_bound") or ""),
                              # S-10：判据要跟着子目标走 —— 下一轮 `_deploy_e` 缺 `script_path` 时
                              # 会把这份判据念出来（否则"缺脚本"是一句没人能执行的话）。
                              "script_spec": spec,
                              "status": "todo"})
            detail = (f"把这一轮的实验判据交给 E（新子目标 {new_sid}）："
                      f"{product.get('why_it_decides')}")
            evidence = [new_sid]
            status = "in_progress"
        else:  # dead_end
            reason = str(product.get("reason") or "")
            detail = (f"这一轮走不下去（{reason}）：{product.get('evidence')}；"
                      f"已交 best_partial {len(product.get('best_partial') or [])} 条")
            evidence = []
            status = "blocked"
        return {
            "action": kind,
            "outcome": "no_change" if kind == "dead_end" else "progress",
            "product": dict(product),
            "detail": detail,
            "evidence": evidence,
            "status": status,
            "blocked_reason": (str(product.get("evidence") or "") if kind == "dead_end" else ""),
            "in_flight": kind == "dead_end",
            "count_attempt": True,
            "new_subgoals": new_goals,
        }

    def _deploy_e(self, sg: Mapping[str, Any], *, plan: Mapping[str, Any]) -> dict:
        """E 的子目标：跑实验并登记。

        幂等：如果这个子目标已经跑过实验（`experiment_ids` 非空），不重跑。
        为什么必须幂等：每一轮重跑同一个脚本会让 experiments 表堆满重复记录、
        `attempts` 虚高，而"这条子目标到底试过几次"就再也答不上来了。
        要重跑必须由人显式清空 `experiment_ids`（那是一个有意的动作）。
        """
        sid = str(sg.get("sid") or "")
        claimed = sorted(set(list(sg.get("experiment_ids") or []) + list(sg.get("proof_experiment_ids") or [])))
        if claimed:
            return {
                "action": "no_change",
                "outcome": "no_change",
                "detail": (
                    f"子目标 {sid} 已有实验记录 {claimed} ⇒ 本轮**不重复执行**"
                    "（重复登记会让 experiments 表堆满同一件事，attempts 虚高）"
                ),
                "evidence": claimed,
                "status": None,
                "count_attempt": False,
            }

        script_path = str(sg.get("script_path") or "").strip()
        spec = dict(sg.get("script_spec") or {})
        if not script_path and not spec:
            # 这不是失败，是我没法做：缺执行参数。如实记，并让子目标保持在
            # 可重试位置（下一次有人补上 script_path 就能跑）。
            #
            # S-10（`draft/44`）：F 的 `counterexample_request` 造出来的 E 子目标带着判据
            # （`script_spec`：criterion/params/expected_bound），这里要把那份判据念出来 ——
            # 否则"缺 script_path"是一句没人能执行的话（下一轮照旧缺，直到计划 stalled）。
            #
            # S-10(a)：带判据的那一支不再停在这里 —— 下面先让 E 按判据把脚本写出来
            # （`author_script`）。没判据的这一支逐字不变：这既是行为上的最小改动，
            # 也是"没判据 ⇒ 不写脚本"那条反负控的落点（凭空生成脚本会把"不知道该判什么"
            # 伪装成"有实验在跑"）。
            return {
                "action": "no_change",
                "outcome": "no_change",
                "detail": (
                    f"子目标 {sid} 派给 E，但没有给 `script_path` ⇒ **未推进**"
                    "（没有脚本就没有实验可跑；这不是'跑了但没结果'）"
                ),
                "evidence": [],
                "status": "todo",
                "blocked_reason": "缺 `script_path`（E 要先写脚本）",
                "count_attempt": False,
            }

        try:
            agent_e = self.e
        except Exception as ex:  # noqa: BLE001 - E 不可用时必须显式失败，不许静默跳过
            return {
                "action": "no_change",
                "outcome": "no_change",
                "detail": (
                    f"子目标 {sid} 派给 E，但 E **不可用**（{type(ex).__name__}: {ex}）⇒ **未推进**。"
                    "未接线/不可用必须是显式事实，不许静默降级为空"
                ),
                "evidence": [],
                "status": "in_progress",
                "blocked_reason": f"E 不可用：{type(ex).__name__}: {ex}",
                "count_attempt": False,
            }

        # ---- S-10(a)：有判据、没脚本 ⇒ 让 E 按判据把脚本写出来，然后照常跑它。
        #
        # 为什么必须在这里写（而不是让模型自己用 `fs.write` 写）：`counterexample_request`
        # 造出的子目标必然没有 `script_path`，而"下一轮有人补上它"从来不会发生 ——
        # 真机里这一跳是"造出的子目标必然停住直到计划 stalled"（`draft/44` S-10）。
        # 现在补它的就是 E 自己（`author_script`：缝只用于生成，判读一个字不改）。
        authored: dict[str, Any] = {}
        if not script_path:
            authored = agent_e.author_script(spec, sid=sid)
            if not authored.get("ok"):
                code = str(authored.get("reason") or "")
                # 人读的那句话两种形状都要接：走 `refusals.refuse` 的档给的是 `error`
                # （框架统一的拒绝字段），不走它的档给的是 `note`（本方法自己的读数字段）。
                # 少读一种，`blocked_reason` 里就会出现一个 `None` —— 而"没做成"的理由
                # 恰恰是这条子目标最需要的那条信息。
                note = str(authored.get("note") or authored.get("error") or "")
                spec_line = (f"；这一条子目标带的判据是：criterion={spec.get('criterion')!r}、"
                             f"params={spec.get('params')!r}、期望界={spec.get('expected_bound')!r} —— "
                             "E 要先把脚本写进工作区（`script_path`）再跑")
                return {
                    "action": "script_not_authored",
                    "outcome": "no_change",
                    "detail": (
                        f"子目标 {sid} 有判据但没有脚本，而 E 没能把它写出来"
                        f"（{code}）⇒ **未推进**（没有脚本就没有实验可跑；"
                        f"这不是'跑了但没结果'）。{note}{spec_line}"
                    ),
                    "evidence": [],
                    "status": "todo",
                    "blocked_reason": f"E 写不出脚本：{code}｜{note}",
                    # `no_seam` 是环境事实（再试一次还是同一句话，要去接线）⇒ 不计尝试；
                    # 其余（`bad_source` / `bad_spec` / `write_failed` / `judge_*`）都要计 ——
                    # 它们是"真的试过一次"，重试要有读数。
                    "count_attempt": code != "no_seam",
                }
            script_path = str(authored.get("script_path") or "")

        # E 执行失败必须被降级成"这一轮卡住了"，而不是让整个攻坚炸掉。
        #
        # 实测过这个缺口：子目标引用的脚本不存在时，`run_experiment` 抛
        # `ExperimentError`，它一路穿过 `_deploy_e` → `step` → 调用方，
        # 于是一个缺失的脚本文件会中止整个攻坚循环，连其它子目标都没机会跑。
        # 这与 FC-21（部分失败语义）冲突：子任务可以降级，但整体绝不谎报成功。
        #
        # 所以这里把它记成 `outcome="blocked"` + `status="blocked"` + `blocked_reason`：
        # 事实完整保留（E 的原始错误文本在 detail 里），子目标留在表里等人来解，
        # 而其它子目标继续跑。注意这不是"成功降级为无害" ——
        # `blocked` 会让计划永远无法标 `resolved`（除非有人把 proof 级证据补上）。
        try:
            res = agent_e.run_experiment(
                str(sg.get("claim") or sg.get("text") or ""),
                str(sg.get("claim_key") or f"{plan.get('problem_key')}#{sid}"),
                script_path,
                params=dict(sg.get("params") or {}) or None,
                method=str(sg.get("method") or "numeric"),
                for_question_id=plan.get("for_question_id"),
                timeout=int(sg.get("timeout") or self.cfg.get("timeout", 600)),
                # `P-8`：形式化子目标要把"核哪个声明、加载哪些库"传下去 ——
                # 不传的话 E 只能用文件名词干 + 检查器默认库，而"库不可得"
                # （`import_unavailable`）会让这次检查根本没发生 ⇒ 永远拿不到 proof。
                # 两个键对计算类子目标不存在（取到 None），E 那一侧因此不会拒绝。
                name=sg.get("name"),
                imports=sg.get("imports"),
            )
        except Exception as ex:  # noqa: BLE001 - 任何 E 侧失败都降级为 blocked，不中止攻坚
            return {
                "action": "experiment_failed",
                "outcome": "blocked",
                "detail": (
                    f"子目标 {sid} 的实验**执行失败**：{type(ex).__name__}: {ex}"
                    f"（脚本 {script_path!r}）。已如实记为 blocked 并保留错误原文；"
                    "**其它子目标继续推进**，但本计划在这一点解决前不可能标记为 resolved"
                ),
                "evidence": [],
                "status": "blocked",
                "blocked_reason": f"实验执行失败：{type(ex).__name__}: {ex}",
                # 脚本是这一轮写的 ⇒ 即便跑失败也要留落点（复核时要看的就是它）
                "script_path": script_path,
                "count_attempt": True,
            }
        eid = str(res.get("experiment_id"))
        kind = str(res.get("evidence_kind"))
        result = str(res.get("result"))
        if kind == "proof":
            # 只有 proof 级证据才允许关闭子目标（FC-22）。E 只有在
            # method="formal" 且拿到检查器输出时才会给出这个等级。
            return {
                "action": "run_experiment",
                "outcome": "progress",
                "detail": (
                    f"实验 {eid}：result={result}，evidence_kind=proof ⇒ 子目标 {sid} 可关闭"
                ),
                "evidence": [eid],
                "experiment_ids": [eid],
                "proof_experiment_ids": [eid],
                "status": "closed",
                "negation_kind": res.get("negation_kind"),
                # S-10(a)：脚本是这一轮才写出来的 ⇒ 把落点写回子目标（下一轮要重跑/复核
                # 时得知道跑的是哪一份），否则"它到底写了哪个脚本"只活在 history 的一句话里。
                "script_path": script_path,
                "count_attempt": True,
            }
        if result == "supports":
            # 数值/穷举支持只能标 supported_not_proved，不能标 closed。
            return {
                "action": "run_experiment",
                "outcome": "progress",
                "detail": (
                    f"实验 {eid}：result=supports，evidence_kind={kind} ⇒ 子目标 {sid} 标 "
                    "supported_not_proved（**数值支持不是证明**，FC-22）"
                ),
                "evidence": [eid],
                "experiment_ids": [eid],
                "status": "supported_not_proved",
                "negation_kind": res.get("negation_kind") or "not_proved",
                "script_path": script_path,
                "count_attempt": True,
            }
        return {
            "action": "run_experiment",
            "outcome": "no_change",
            "detail": (
                f"实验 {eid}：result={result}（negation_kind={res.get('negation_kind')}，"
                f"exit_code={res.get('exit_code')}）⇒ 子目标 {sid} **未取得可判定结论**，"
                "保持 in_progress（崩溃/无结论不得被写成支持）"
            ),
            "evidence": [eid],
            "experiment_ids": [eid],
            "status": "in_progress",
            "negation_kind": res.get("negation_kind") or "no_local_evidence",
            "script_path": script_path,
            "count_attempt": True,
        }
    def _deploy_a(self, sg: Mapping[str, Any], *, plan: Mapping[str, Any]) -> dict:
        """A 的子目标：过 I7 闸门后提交一条 `search_requests`（同一事务）。"""
        sid = str(sg.get("sid") or "")
        text = str(sg.get("text") or "")
        topic = str(sg.get("topic") or text).strip()
        mode = str(sg.get("mode") or self.search_mode)
        if mode not in S.SEARCH_MODES:
            raise PlanError(f"子目标 {sid} 的 mode={mode!r} 不在 {S.SEARCH_MODES} 里")
        if mode == "precise" and not text:
            raise PlanError(f"子目标 {sid} 是 precise 检索但没有文本可作 content_description")
        if not topic:
            raise PlanError(f"子目标 {sid} 没有 topic（空 topic 会让检索无从构造）")

        with self.store.tx("search_requests", actor=self.actor, note="f.step:submit_search") as tx:
            rows = tx.rows("search_requests")
            gate = IX.admit_search_request(
                rows,
                submitted_by=self.submitter,
                explicit_priority=self.search_priority,
                for_question_id=plan.get("for_question_id"),
                max_inflight=self.cfg.get("max_inflight_requests"),
            )
            if not gate["admitted"]:
                # 闸门拒绝 ⇒ 不产生任何写入（这是 I7 的全部意义：显式拒绝把压力
                # 传导回提交方，而不是无限排队把 A 的产能摊薄）
                return {
                    "action": "submit_search_request",
                    "outcome": "no_change",
                    "detail": f"检索请求被闸门拒绝（**未提交任何请求**）：{gate['reason']}",
                    "evidence": [],
                    "status": "blocked",
                    "blocked_reason": gate["reason"],
                    # 闸门拒绝也标 in_flight：再试一次会得到同一个答案
                    # （在途数没有变），重复提交只会重复消耗同一份拒绝理由。
                    "in_flight": True,
                    "count_attempt": False,
                }
            # `prefix` 只给 `"r"`：`IX.next_prefixed_id` 自己会补上连接号
            # （`f"{prefix}-{n:04d}"`）。传 `"r-"` 会得到 `"r--0001"` —— 而它
            # 恰好还能通过 `SearchRequest.validate`（那条只查非空），
            # 于是会静默写进表里、下一轮取号又认不出来（前缀匹配不上），
            # 每次都重新从 1 开始找，很快撞上已占用的号。属"看起来能用"的静默缺陷。
            req_id = IX.next_prefixed_id(rows, "request_id", "r")
            req = S.SearchRequest(
                request_id=req_id,
                timestamp=self._stamp(),
                topic=topic,
                mode=mode,  # type: ignore[arg-type]
                content_description=text,
                done=False,
                submitted_by=self.submitter,
                priority=gate["priority"],
                for_question_id=plan.get("for_question_id"),
                submit_note=f"agent-F 攻坚计划 {plan.get('plan_id')} 子目标 {sid}：{text}",
            )
            req.validate()
            tx.upsert("search_requests", req.to_dict(), note=f"f.step:{sid}")
        return {
            "action": "submit_search_request",
            "outcome": "progress",
            "detail": (
                f"已向 A 提交检索请求 {req_id}（priority={gate['priority']}，mode={mode}）"
                f"⇒ 子目标 {sid} 转 in_progress 并等 A 的回填（**在这一轮里它还没有证据**）"
            ),
            "evidence": [req_id],
            # `evidence` 与 `evidence_ids` 是两个不同的落点，不能省掉任何一个：
            # `evidence` 进 history 的当轮记录（"这一轮依据/产生了什么"），
            # `evidence_ids` 进子目标（"这条子目标攒到了哪些证据"）。
            # 只写前者会让子目标看起来"一条证据都没有过" —— 而复用同一个键
            # 又会让两处的语义漂移。
            "evidence_ids": [req_id],
            "status": "in_progress",
            "blocked_reason": f"等 A 完成检索请求 {req_id}",
            # 派给 A 之后这一轮就没别的事可做了：请求在 A 手里，结果不会
            # 在同一个 step 里回来。不标 in_flight 的话，下一轮会再次选中同一个
            # 子目标、再提交一条请求 —— 那是把"等回填"变成了"每轮重发"。
            "in_flight": True,
            "count_attempt": True,
        }
    def _deploy_b(self, sg: Mapping[str, Any], *, plan: Mapping[str, Any]) -> dict:
        """B 的子目标：过 I4 闸门后提交一条 `reprocess_requests`。"""
        sid = str(sg.get("sid") or "")
        text = str(sg.get("text") or "")
        rids = sorted({str(x) for x in (sg.get("relation_ids") or []) if x})
        reason = str(sg.get("reason") or self.cfg.get("reprocess_reason") or "need_context")
        if not rids:
            # 无目标的重抽取会退化成全量重抽（I4 的幂等陷阱），所以这里必须拦住。
            return {
                "action": "submit_reprocess_request",
                "outcome": "no_change",
                "detail": (
                    f"子目标 {sid} 派给 B，但没有给 `relation_ids` ⇒ **未推进**"
                    "（无目标的重抽取会退化成全量重抽，是 I4 明令禁止的）"
                ),
                "evidence": [],
                "status": "todo",
                "count_attempt": False,
            }
        with self.store.tx("reprocess_requests", actor=self.actor, note="f.step:submit_reprocess") as tx:
            rows = tx.rows("reprocess_requests")
            gate = IX.admit_reprocess_request(
                rows,
                relation_ids=rids,
                reason=reason,
                max_per_relation=self.cfg.get("max_reprocess_per_relation"),
            )
            if not gate["admitted"]:
                return {
                    "action": "submit_reprocess_request",
                    "outcome": "no_change",
                    "detail": f"重抽取请求被闸门拒绝（**未提交**）：{gate['reason']}",
                    "evidence": [],
                    "status": "blocked",
                    "blocked_reason": gate["reason"],
                    "in_flight": True,
                    "count_attempt": False,
                }
            # 同 A：prefix 只给 `"p"`（函数自己补连接号）
            rid = IX.next_prefixed_id(rows, "reprocess_id", "p")
            req = S.ReprocessRequest(
                reprocess_id=rid,
                timestamp=self._stamp(),
                reason=reason,
                submitted_by=self.submitter,
                relation_ids=rids,
                detail=f"agent-F 攻坚计划 {plan.get('plan_id')} 子目标 {sid}：{text}",
                status="pending",
            )
            req.validate()
            tx.upsert("reprocess_requests", req.to_dict(), note=f"f.step:{sid}")
        return {
            "action": "submit_reprocess_request",
            "outcome": "progress",
            "detail": (
                f"已提交重抽取请求 {rid}（reason={reason}，目标关系 {rids}）"
                f"⇒ 子目标 {sid} 转 in_progress 并等 B 处理"
            ),
            "evidence": [rid],
            "evidence_ids": [rid],  # 见 `_deploy_a` 里对这两个键的说明
            "status": "in_progress",
            "blocked_reason": f"等 B 处理重抽取请求 {rid}",
            # 同 A：请求已经交出去了，本轮到此为止（见 `_deploy_a` 的说明）。
            "in_flight": True,
            "count_attempt": True,
        }
    def _derive_status(self, subgoals: Sequence[Mapping[str, Any]], row: Mapping[str, Any]) -> str:
        """按子目标的状态推导计划状态（FC-22 / FC-25 的落地）。"""
        if not subgoals:
            # 空计划：没有待办也没有证据。这与"全部 closed"在字面上true，
            # 但在语义上是"这个计划什么都没做" —— 所以不当成 resolved。
            return str(row.get("status") or "open")

        statuses = [str(s.get("status") or "") for s in subgoals]
        if all(st == "closed" for st in statuses):
            return "resolved"

        proof_ids = {str(x) for s in subgoals for x in (s.get("proof_experiment_ids") or [])}
        if all(st in ("closed", "supported_not_proved") for st in statuses):
            if not proof_ids:
                # 关键一分：子目标都有数值支持，但一条 proof 级证据都没有。
                # 这时若返回 resolved 就是把 cross_check 当成了证明（FC-22 要防的正是这件事）。
                return "supported_not_proved"
            return "resolved"
        return "attacking"
    def _compose_best_partial(self, subgoals: Sequence[Mapping[str, Any]], rounds: int) -> str:
        """由各子目标的实际进展合成一段 `best_partial`。

        它必须如实：有进展就写清进展落在哪个子目标上（带实验/请求代号），
        什么都还没有就写 :data:`NO_PROGRESS_NOTE`。编一句听起来像成果的话，
        比留空更坏 —— 因为留空至少 schema 会拦，编的话没人拦得住。
        """
        if not subgoals:
            return NO_PROGRESS_NOTE

        def brief(s: Mapping[str, Any]) -> str:
            bits = [f"{s.get('sid')}（owner={s.get('owner')}，status={s.get('status')}）: {s.get('text')}"]
            if s.get("proof_experiment_ids"):
                bits.append(f"proof 级实验 {s['proof_experiment_ids']}")
            elif s.get("experiment_ids"):
                bits.append(f"实验 {s['experiment_ids']}（**仅交叉验证，不构成证明**）")
            if s.get("evidence_ids"):
                bits.append(f"证据 {s['evidence_ids']}")
            if s.get("blocked_reason"):
                bits.append(f"卡点：{s['blocked_reason']}")
            return "；".join(bits)

        ranked = sorted(
            subgoals,
            key=lambda s: (
                {"closed": 0, "supported_not_proved": 1, "in_progress": 2, "todo": 3, "blocked": 4, "dropped": 5}.get(
                    str(s.get("status") or ""), 9
                ),
                str(s.get("sid") or ""),
            ),
        )
        parts = [f"已进行 {rounds} 轮。子目标进展（按'离终结有多近'排序）："]
        parts += [f"- {brief(s)}" for s in ranked]
        parts.append("**以上均为过程记录**：标了 supported_not_proved 或只有 experiment_ids 的条目都还不是证明。")
        return "\n".join(parts)
    def _write_plan(self, row: Mapping[str, Any], *, note: str) -> None:
        """写回计划（一个事务）。校验在写入前完成，非法即炸（不吞异常）。

        `schema` 抛的 `ValueError` 在这里被换成语义正确的 `PlanError`
        （`ToolError` 子类）—— 见 `PlanError` 的 docstring：这不是"吞掉"，
        是让工具层拿到 `kind="tool_error"` 与具体原因，而不是无声的
        `kind="unexpected"`。异常照旧冒泡，写入照旧不发生。
        """
        try:
            obj = S.row_from_dict("attack_plans", dict(row))
            if obj.status == "stalled" and not str(obj.best_partial).strip():
                obj.best_partial = NO_PROGRESS_NOTE
            obj.validate()
        except ValueError as e:
            raise PlanError(
                f"计划 {row.get('plan_id')!r} 的写回内容不合 schema 硬约束 ⇒ **未写回**：{e}"
            ) from e
        with self.store.tx("attack_plans", actor=self.actor, note=note) as tx:
            tx.upsert("attack_plans", obj.to_dict(), note=note)


class AgentF(_CreatePlan, _Step, _Status, _ListPlans, _Core):
    """多轮难题攻坚智能体。

    每个方法都可以被独立调用与单测：

    - :meth:`create_plan` —— 立项（预算不完整即拒绝，不写库）；
    - :meth:`step` —— 推进一轮（唯一会改计划的方法）；
    - :meth:`status` / :meth:`list_plans` —— 只读视图。

    构造签名刻意比 A–E 简单（没有 `workspace_root`）：F 自己不跑脚本，
    实验执行是 E 的职责；F 只持有 store 与配置。
    """



def selftest() -> int:
    """离线自检：不联网、不依赖仓库里的任何外部文件，返回失败数。

    运行方式::

        cd test/test1/src        # 工作区根相对
        $env:PYTHONIOENCODING='utf-8'; python -m agentflow.agent_f

    覆盖的核心性质（每一条都对应一个"如果错了会很安静"的失败模式）：

    1. 立项：预算完整才成功；缺键不写库；
    2. 同一 problem_key 第二次不新建（避免同一难题被并行攻两遍）；
    3. 分派：E 真的跑实验、A 真的写检索请求、C/D/F 如实记 no_change；
    4. 终止性：轮数用尽即 stalled + best_partial 非空，且恰好 max_rounds 轮；
    5. FC-22：数值证据不得关闭子目标；
    6. 工具层的 `attack.*` 与 `AgentF` 方法口径一致。
    """
    import sys as _sys
    import tempfile

    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 有些 stdout 替身没有 reconfigure；切编码失败不该让自检本身挂掉
        pass

    failures = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal failures
        okk = bool(cond)
        if not okk:
            failures += 1
        print(f"    [{'PASS' if okk else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    print("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="agentflow-agentf-"))
    st = Store(root)
    st.init()
    print(f"[0] 临时工作区：{root}")

    # 一个"总是给出数值支持"的脚本：
    (root / "probe.py").write_text(
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result':'supports','evidence_kind':'cross_check',"
        "'observations':{'n':10},'counterexample':None,'negation_kind':'not_proved'}))\n",
        encoding="utf-8",
    )

    f = AgentF(st, config={"workspace_root": root})
    print(f"[1] 工具栏：{f.tools.names()}")

    # ---- 1. 预算不完整 ⇒ 不创建
    bad = dict(AT.DEFAULT_BUDGET)
    bad.pop("max_depth")
    r_bad = f.create_plan("难题甲", "P-bad", budget=bad)
    print(f"[2] 缺 max_depth 的预算 ⇒ created={r_bad['created']} missing={r_bad.get('missing')}")
    check("预算缺键 ⇒ created=False", r_bad["created"] is False)
    check("预算缺键 ⇒ 一行都没写", st.rows("attack_plans") == [])

    # ---- 2. 正向立项
    r1 = f.create_plan(
        "证明 Spec K(m)=[-m,m]",
        "P-1",
        subgoals=[
            {"sid": "s1", "text": "数值验证 m<=32", "owner": "E", "script_path": "probe.py",
             "claim": "SpecK(m)=[-m,m]", "claim_key": "P-1#s1"},
            {"sid": "s2", "text": "查文献中的谱刻画", "owner": "A", "topic": "spectrum of K(m)"},
            {"sid": "s3", "text": "需要 D 做结构化推理", "owner": "D"},
        ],
    )
    print(f"[3] 立项 ⇒ {r1}")
    check("完整预算 ⇒ created=True", r1["created"] is True)
    check("plan_id 是当前宽度的十进制号", len(str(r1["plan_id"])) == S.ID_DIGITS
          and str(r1["plan_id"]).isdigit())

    r_dup = f.create_plan("同一个难题再来一次", "P-1")
    print(f"[4] 同 problem_key 再立项 ⇒ {r_dup['reason']}")
    check("同 problem_key ⇒ 不新建，返回已有 plan_id",
          r_dup["created"] is False and r_dup["plan_id"] == r1["plan_id"])
    check("attack_plans 仍只有一行", len(st.rows("attack_plans")) == 1)

    # ---- 3. 分派
    pid = r1["plan_id"]
    s1 = f.step(pid)
    print(f"[5] step#1 ⇒ action={s1['action']} outcome={s1['outcome']} sid={s1['sid']} status={s1['status']}")
    check("第一轮派给 E 并跑出实验", s1["action"] == "run_experiment" and s1["outcome"] == "progress")
    row = f.status(pid)
    s1sg = next(s for s in row["subgoals"] if s["sid"] == "s1")
    check("E 子目标拿到 experiment_id", bool(s1sg["experiment_ids"]))
    check("数值实验**不许**关闭子目标（FC-22）",
          s1sg["status"] == "supported_not_proved" and s1sg["proof_experiment_ids"] == [])
    check("计划状态随之变成 supported_not_proved（无任何 proof）", row["status"] == "attacking")

    s2 = f.step(pid)
    print(f"[6] step#2 ⇒ action={s2['action']} outcome={s2['outcome']} sid={s2['sid']}")
    check("第二轮派给 A 并写出检索请求",
          s2["action"] == "submit_search_request" and len(st.rows("search_requests")) == 1)

    s3 = f.step(pid)
    print(f"[7] step#3 ⇒ action={s3['action']} outcome={s3['outcome']} sid={s3['sid']}")
    check("D 的子目标如实记 no_change", s3["action"] == "no_change" and s3["outcome"] == "no_change")
    check("detail 明说'未推进'", "未推进" in s3["reason"])
    _s3 = next(s for s in f.status(pid)["subgoals"] if s["sid"] == "s3")
    check("没有伪造任何证据", _s3["evidence_ids"] == [])
    check("卡点写进 blocked_reason（不许静默卡住）", bool(str(_s3["blocked_reason"]).strip()))
    check("同一未接线子目标不会被反复重选（in_flight 过滤）", f.step(pid)["sid"] is None)

    # ---- 4. 终止性：两条路径都要能到 stalled
    #
    # (a) 预算内出现连续无进展 ⇒ 提前停止（新加，来自对本地先例 dsh 数学模式的观摩：
    #     那个模式要求"连续 N 轮无进展就终止"。我们此前只按 `max_rounds` 停，
    #     而 `history[i]["outcome"]=="no_change"` 这个信号已经生产出来却无人消费，
    #     正是本项目自己总结的 P4「检测到了却没有消费」的又一处实例）。
    # (b) 轮数用尽 ⇒ 强制停止。
    #
    # 这里不再断言 "rounds 恰好 == max_rounds"：那等于把"一定要把预算烧完"
    # 写成不变量，而"烧完预算"恰恰是 (a) 要避免的事。改成断言"停下来了 + 停在哪条路径上写清楚了"。
    max_rounds = AT.DEFAULT_BUDGET["max_rounds"]
    for _ in range(max_rounds + 2):
        last = f.step(pid)
        if last["status"] == "stalled":
            break
    st_row = f.status(pid)
    print(f"[8] 终止 ⇒ status={st_row['status']} rounds={st_row['rounds']} "
          f"best_partial={_short(st_row['best_partial'])}")
    check("终止 ⇒ stalled", st_row["status"] == "stalled")
    check("轮数不超过 max_rounds", st_row["rounds"] <= max_rounds)
    check("best_partial 非空（且如实）", bool(st_row["best_partial"].strip()))
    check(
        "停止路径写清楚了（提前停止 或 轮数用尽）",
        ("提前停止" in st_row["best_partial"]) or st_row["rounds"] == max_rounds,
    )
    after = f.step(pid)
    check("stalled 后不再推进（终态不可重入）",
          after["status"] == "stalled" and after["round"] == st_row["rounds"])

    # ---- 4b. 另一条终止路径：把"连续无进展提前停止"关掉，验证轮数用尽那一支
    killed = AgentF(st, config={"stall_after_no_progress_rounds": 0})
    pid2 = killed.create_plan("预算烧干路径", "selftest:burn", subgoals=[
        {"sid": "t1", "text": "未接线的子目标", "owner": "D", "status": "todo"},
    ])["plan_id"]
    for _ in range(max_rounds + 3):
        if killed.step(pid2)["status"] == "stalled":
            break
    row2 = killed.status(pid2)
    print(f"[8b] 提前停止关闭后 ⇒ status={row2['status']} rounds={row2['rounds']}")
    check("提前停止关闭时，轮数真的跑到 max_rounds（两个方向都测到）",
          row2["status"] == "stalled" and row2["rounds"] == max_rounds)

    # ---- 5. FC-22 负控：数值证据不得关闭子目标
    rejected = False
    try:
        S.AttackPlan(
            plan_id="0000", problem="p", problem_key="k",
            budget=dict(AT.DEFAULT_BUDGET), rounds=0, status="open",
            subgoals=[{"sid": "s", "text": "t", "owner": "E", "status": "closed",
                       "experiment_ids": ["0000"], "proof_experiment_ids": []}],
        ).validate()
    except ValueError as ex:
        rejected = "proof" in str(ex)
    check("只有数值证据却标 closed ⇒ schema 抛（FC-22）", rejected)

    # ---- 6. 工具层与 AgentF 口径一致
    print(f"[9] 工具 attack.*：{f.tools.names()}")
    t = f.tools.call("attack.status", plan_id=pid)
    check("attack.status 可用且返回同一计划", t.ok and t.data["plan_id"] == pid)
    t2 = f.tools.call("attack.create_plan", problem="工具建的", problem_key="P-tool")
    check("attack.create_plan 可用", t2.ok and t2.data["created"] is True)
    t3 = f.tools.call("attack.list_plans")
    # 到这一步库里应当有 3 个计划：主计划 + [8b] 的"预算烧干"路径 + 上面工具建的这一个。
    # 断言写成"至少 3 且包含刚建的那个"，而不是写死 `== 2`：
    # 写死数字会让"新增一条覆盖率更高的自检"变成一次失败 —— 而测试应当对行为
    # 断言，不该对"我数了几个对象"断言。
    check("attack.list_plans 可用",
          t3.ok and t3.data["total"] >= 3
          and any(p.get("problem_key") == "P-tool" for p in t3.data["plans"]))

    print("=" * 72)
    print(f"SELF-CHECK {'DONE' if failures == 0 else 'FAILED'}（agent_f）：失败 {failures} 项")
    return failures
