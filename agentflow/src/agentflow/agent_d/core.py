"""角色 D 的实现核心（`goal-7f5116c1` M6）：其余成员 + 把动作 mixin 装起来。

动作方法一个都没留在这里 —— 它们各自在 `agent_d/<动作>.py`。
这一层与各动作文件共用 `_support.py`（模块级 helper 与常量）。
"""
from __future__ import annotations

from collections.abc import Mapping

from ._support import Any, C_API_MISSING_REASON, C_NO_EVIDENCE, IX, KIND_CLIENT, KIND_NONE, Mapping, Path, RT, S, STATE_FAILED, STATE_NOT_WIRED, Sequence, Store, StoreError, ToolRegistry, _C_AUTO, _digest, _json_object, _rank, _rank_min, current_summon_task_id, install_d_tools, invented_facts, json, load_trace_tools, model_json_call, model_kind, re, spend_reading
from .. import conceptrows as _CR   # 并表过渡期：概念行读合成视图（老表 + 新标准同号去重）
from .probe_c import _ProbeC
from .ingest import _Ingest
from .ingest_detailed import _IngestDetailed
from .trace_question import _TraceQuestion
from .trace_l3 import _TraceL3
from .assess import _Assess
from .submit_gaps import _SubmitGaps
from .consider import _Consider
from .poll import _Poll
from .adjudicate import _Adjudicate
from .research import _Research
from .run_round import _RunRound
from .propose_question import _ProposeQuestion
from .write_report import _WriteReport
from .register_conjecture import _RegisterConjecture


class _Core:
    def __init__(
        self,
        store: Store,
        config: Mapping[str, Any] | None = None,
        actor: str = "agent-D",
        tools: ToolRegistry | None = None,
        llm: Any | None = None,
        *,
        trace_tools: Any | None = None,
        c: Any = _C_AUTO,
        b: Any = None,
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = actor
        self.llm = llm
        #: D 递给 B 的那条路（业主 2026-10-26 晚：「D 到 B 没有路吗？加」）。
        #:
        #: 装配层在构造期把它绑进来（`specs/d.py::_build` 的 `peers["B"]`，接线层按
        #: `(角色, 库)` 单例保证就是 M 召唤的那个 B）。直调 `AgentD(store)` 时它是
        #: `None` —— 那时交付路径会如实写"没有 B 的入口"，绝不假装递过去了。
        self.b = b
        #: 最近一次"把稿递给 B"的读数（`_deliver_carried_to_b` 写；没有 B 时也留痕）。
        self.last_delivery: dict[str, Any] = {}
        #: 这一趟召唤的 `task_id`（`R1-A1` 的 P-09 口径：模型花销要挂到当次召唤上）。
        #:
        #: 默认空串 = 没有挂点：装配层（`host._Builder._build` → `specs/d.py::_build`）
        #: 现在不把召唤号交给角色实例，于是缝那边 `ask(task_id="")` 记的 `llm_call` 事件
        #: 带不出召唤号，`tokenmeter.usd_for(task_id)` 也就读不到这一笔。
        #: 这一格是留给装配层的挂点（谁拿到了召唤号就 `d.llm_task_id = tid`），
        #: 而现在读数会如实写 `task_id` 为空 —— 不许把"没挂点"读成"没花钱"。
        self.llm_task_id: str = str(self.cfg.get("llm_task_id") or "")
        #: 最近一次 `_compose` 的模型三态读数（`{kind,state,reason,model,calls,task_id}`）。
        self.last_llm_reading: dict[str, Any] = {"kind": KIND_NONE, "state": STATE_NOT_WIRED,
                                                 "reason": "还没调用过", "model": "", "calls": 0}
        #: 工具栏。要么外部注入，要么这里装配（含降级替身）。
        self.tools = tools if tools is not None else install_d_tools(self.store, trace_tools=trace_tools)
        # ---- 绑定角色（`P-14`）：`AgentD._call` 的每次调用都要能回答"这次是谁在调"。
        # 注入进来的注册表（测试与调用方都用这条路径）同样要绑 —— 绑不上就等于
        # D 的每一次工具调用都会以"调用方没有声明角色"被拒，那不是"更安全"，
        # 那是把 D 的手砍掉了。
        if self.tools.bound_role is None:
            self.tools.bound_role = "D"

        # ---- 阈值全部来自 config，不写死在代码里（与 config.yaml 的既有做法一致）
        self.max_questions = int(self.cfg.get("max_questions", 5))  # §8 待决问题 2
        self.degree_threshold = int(self.cfg.get("degree_threshold", 2))
        self.max_requests_per_question = int(self.cfg.get("max_requests_per_question", 2))  # §8 待决问题 3
        self.max_total_requests = int(self.cfg.get("max_total_requests", 20))  # §8 待决问题 3
        self.max_l3_lits = int(self.cfg.get("max_l3_lits", 3))
        #: 报告里 L2 上下文最多展开几条。链条自身（L1）不设上限（它就是重点），
        #: 但上下文必须限量：一个枢纽概念能牵出十几条邻居关系，全列出来会把
        #: 链条淹掉（读者要顺着链读，不是拿到一堆）。截断后报告会写"另有 N 条未展开"。
        self.max_l2_context = int(self.cfg.get("max_l2_context", 6))
        #: L3 是否强制下钻（默认关闭：L3 贵，只在证据互相矛盾或"要写结论但没有一条
        #: 可核验的引文"时才下钻 —— 这正是 §4.3 说的"按需"）。
        self.force_l3 = bool(self.cfg.get("force_l3", False))
        self.reports_subdir = str(self.cfg.get("reports_subdir", "reports"))
        #: 每份 C 报告最多提几个问题；报告 kind -> 允许提取的 kind（便于只跑一类）
        self.enabled_kinds = tuple(self.cfg.get("enabled_kinds") or S.REPORT_KINDS)
        #: ingest 去重开关：同一 origin 已经提过就不再提（跨轮次幂等）
        self.dedup_by_origin = bool(self.cfg.get("dedup_by_origin", True))
        #: ingest 是否从 C 报告/C 服务读矛盾（I2）。关掉它 = 只提取缺口类问题。
        self.ingest_contradictions = bool(self.cfg.get("ingest_contradictions", True))

        # ---- I2 的终止条件（它们必须是可配置的上限，而不是"跑到收敛为止"）
        #: 单条矛盾最多追问几轮。用尽后不是继续，而是标 `persistent` 交人复核。
        self.max_rounds_per_contradiction = int(
            self.cfg.get("max_rounds_per_contradiction", IX.DEFAULTS["max_rounds_per_contradiction"])
        )
        #: 全局最多提交几条矛盾驱动的检索请求（统计口径见 :meth:`_contradiction_budget`）。
        self.max_contradiction_requests = int(
            self.cfg.get("max_contradiction_requests", IX.DEFAULTS["max_contradiction_requests"])
        )
        #: 单个问题最多向 C 点几次菜（I1）。C 是服务，不等于可以无限点单。
        self.max_c_neighbor_queries = int(self.cfg.get("max_c_neighbor_queries", 2))
        self.max_c_pair_queries = int(self.cfg.get("max_c_pair_queries", 2))
        self.max_c_contradictions = int(self.cfg.get("max_c_contradictions", 20))
        #: 单轮最多裁决几条矛盾问题（防"一份报告带进来 20 对矛盾"时一轮打出 20 条请求）。
        self.max_adjudications_per_round = int(self.cfg.get("max_adjudications_per_round", 10))

        # ---- I1：C 服务（点菜用的那只手）
        self.c: Any = None
        #: 工具/事务失败记录（报告审计一节会打印）。在这里就初始化：
        #: 早先它只在 `trace_question` 里惰性建立，于是任何"先失败、后溯源"的路径
        #: （例如 `adjudicate` 里的异常分支）都会以 AttributeError 收场 ——
        #: 记录失败的代码本身炸掉，比失败更坏。
        self.last_tool_errors: list[dict[str, Any]] = []
        #: C 的接线方式与理由（三态：injected / auto / auto_failed / disabled）。
        #: 它必须可审计：报告要能说清"本轮到底有没有能力问 C"。
        self.c_wiring: dict[str, Any] = {}
        self._resolve_c(c)
    def _stamp(self) -> str:
        return S.now_iso()
    def _reports_dir(self) -> Path:
        return Path(self.store.root) / self.reports_subdir
    def _call(self, name: str, **params: Any) -> Any:
        """调工具并解开 ``ToolResult``；失败返回 ``None`` 并记下原因。

        为什么把失败"吃掉"并返回 None：D 的循环不该因为一次工具失败而中断
        （与 ``ToolRegistry`` 的设计一致）。失败原因进 ``self.last_tool_errors``，
        最终会出现在报告的"审计"一节里，而不是被静默吞掉。
        """
        res = self.tools.call(name, **params)
        if not res.ok:
            self.last_tool_errors.append({"tool": name, "error": res.error, "kind": res.meta.get("kind")})
            return None
        return res.data
    def _resolve_c(self, c: Any) -> None:
        """决定 D 用哪个 C 服务（I1），并把"怎么接上的"写进 ``self.c_wiring``。

        三种来源，每一种都留下可审计的痕迹（三态纪律）：

        - 显式注入实例 ⇒ ``mode="injected"``；
        - 显式传 ``None`` ⇒ ``mode="disabled"``，之后所有 C 查询都记
          ``checked=False`` + 理由"D 未接入 C 服务"（这是"没接线"，不是"查了没有"）；
        - 默认哨兵 ⇒ ``mode="auto"``，惰性装配 ``agent_c.AgentC``。
          为什么不硬依赖 pipeline 把 C 传进来：C 与 D 是并行开发的模块，
          D 必须能在 C 缺席（或版本不匹配）时照常跑完，并且在报告里说清
          它这轮其实没有能力问 C。自动装配失败时记 ``mode="auto_failed"``。
        """
        if c is _C_AUTO:
            try:
                from ..agent_c import AgentC  # 惰性导入：C 模块缺席时 D 依然可用
            except Exception as e:
                self.c = None
                self.c_wiring = {"mode": "auto_failed", "reason": f"无法导入 agent_c：{type(e).__name__}: {e}"}
                return
            sub = self.cfg.get("agent_c")
            try:
                self.c = AgentC(self.store, config=dict(sub) if isinstance(sub, Mapping) else {})
            except Exception as e:
                self.c = None
                self.c_wiring = {"mode": "auto_failed", "reason": f"构造 AgentC 失败：{type(e).__name__}: {e}"}
                return
            self.c_wiring = {
                "mode": "auto",
                "reason": "调用方未注入 C 服务，D 自行装配 agent_c.AgentC（只读服务，不写盘）",
                "c_type": type(self.c).__name__,
            }
            return
        self.c = c
        if c is None:
            self.c_wiring = {
                "mode": "disabled",
                "reason": "显式传入 c=None ⇒ 本轮不做任何 C 查询（所有记录为 checked=False，报告会标注「无 C 侧证据」）",
            }
        else:
            self.c_wiring = {"mode": "injected", "reason": f"使用调用方注入的 C 服务：{type(c).__name__}"}
    def _c_call(self, api: str, **params: Any) -> dict:
        """防御式调用 C 的服务方法（I1）。
        ## 为什么必须是防御式的
        C 的四个只读服务方法由另一个并行开发的任务提供，D 现在既不能假定它们存在，也不能假定签名与冻结契约完全一致。三种情况必须给出三种不同的记录，因为它们对读者的含义完全不同：
        ========================================  ==========================================情况
        记录========================================  ==========================================
        拿不到方法（版本不匹配）                    ``checked=False`` + "C 未提供该方法"方法抛异常
        ``checked=False`` + 异常文本（报告里可见）返回值不是 dict / 缺少 ``checked`` 三态位    ``checked=False`` + 
        理由========================================  ==========================================
        绝对不允许把"没调用成功"静默当成"没有结果"。这是本项目最痛的历史缺陷：D 曾因"没接工具"而静默拿到空证据，却把"查不到"写成了一条听起来很合理的研究发现。失败路径在这
        里一律返回带 reason 的记录。
        """
        c = getattr(self, "c", None)
        if c is None:
            return {
                "checked": False,
                "reason": "D 未接入 C 服务（c=None 或装配失败）⇒ **没查**，不是查了没有",
            }
        fn = getattr(c, api, None)
        if fn is None or not callable(fn):
            return {"checked": False, "reason": C_API_MISSING_REASON}
        try:
            data = fn(**params)
        except Exception as e:  # noqa: BLE001 - 对方模块的任何异常都不能打断 D 的循环
            return {"checked": False, "reason": f"{type(e).__name__}: {e}"}
        if not isinstance(data, Mapping):
            return {
                "checked": False,
                "reason": f"C.{api} 返回 {type(data).__name__}，不是冻结契约要求的 dict ⇒ 视为没查成功",
            }
        out = dict(data)
        if not out.get("checked"):
            # C 自己说"没查"，或返回值根本没有三态位 ⇒ 保持"没查"，并保证理由非空。
            if not str(out.get("reason") or "").strip():
                out["reason"] = f"C.{api} 返回 checked={out.get('checked')!r} 且未给理由 ⇒ 视为没查成功"
        return out
    @staticmethod
    def _c_digest(api: str, res: Mapping[str, Any]) -> dict:
        """把 C 的返回值压成"看得出实际得到了什么"的摘要（I1）。

        摘要不许只写一个布尔：只有布尔时，"查了、什么也没有"与"没查"
        在报告里长得一模一样，读者无法判断该不该信这个结论。所以每种服务都要
        给出可核对的落点（关系代号、节点代号、矛盾对数与配对）。
        """
        if api == "neighbors":
            nodes = [n for n in (res.get("nodes") or []) if isinstance(n, Mapping)]
            return {
                "concept_id": res.get("concept_id"),
                "depth": res.get("depth"),
                "node_count": len(nodes),
                "nodes": [str(n.get("concept_id")) for n in nodes][:20],
                "edge_count": len(res.get("edges") or []),
                "empty": bool(res.get("empty")),
            }
        if api == "relations_between":
            rids = [str(x) for x in (res.get("relation_ids") or [])]
            return {
                "a": res.get("a"),
                "b": res.get("b"),
                "relation_ids": rids,
                "relation_count": len(rids),
                "empty": bool(res.get("empty")),
            }
        if api == "contradictions":
            cs = [c for c in (res.get("contradictions") or []) if isinstance(c, Mapping)]
            return {
                "scope": res.get("scope"),
                "scanned": res.get("scanned"),
                "contradiction_count": len(cs),
                "relation_pairs": [list(c.get("relation_ids") or []) for c in cs][:10],
                "method": res.get("method"),
            }
        if api == "structural_duplicates":
            cs = [c for c in (res.get("candidates") or []) if isinstance(c, Mapping)]
            return {
                "candidate_count": len(cs),
                "concept_pairs": [list(c.get("concept_ids") or []) for c in cs][:10],
            }
        return {"keys": sorted(str(k) for k in res.keys())[:12]}
    def _c_record(self, api: str, params: Mapping[str, Any], res: Mapping[str, Any]) -> dict:
        """把一次 C 调用规整成证据记录 ``{api, params, checked, truncated, digest, reason}``。

        ``checked`` 严格照抄 C 的三态位（缺失即视为没查成功，而不是乐观地当
        成 True）：一个"乐观默认"会把版本不匹配的 C 变成"查过了、什么都没有"。
        """
        checked = bool(res.get("checked"))
        truncated = res.get("truncated")
        if truncated is not None:
            truncated = bool(truncated)
        reason = str(res.get("reason") or "").strip()
        if not checked and not reason:
            reason = f"C.{api} 未成功返回且未给理由 ⇒ 视为没查（不是'查了没有'）"
        rec: dict[str, Any] = {
            "api": api,
            "params": dict(params),
            "checked": checked,
            "truncated": truncated,
            "digest": self._c_digest(api, res) if checked else None,
            "reason": reason,
        }
        if not checked:
            rec["failure"] = True  # 让报告能一眼筛出"这轮没问到"
        return rec
    @staticmethod
    def _c_summary(queries: Sequence[Mapping[str, Any]]) -> dict:
        """C 查询的三态汇总（I1）。

        ``any_success`` 为 False 时，基于该问题产生的结论必须标注
        「无 C 侧证据」并放弃确定语气（见 :meth:`_apply_c_evidence_caveat`）。
        """
        ok = [q for q in queries if q.get("checked")]
        failed = [q for q in queries if not q.get("checked")]
        return {
            "attempted": len(queries),
            "ok": len(ok),
            "failed": len(failed),
            "any_success": bool(ok),
            "apis": [str(q.get("api")) for q in queries],
            "failures": [{"api": q.get("api"), "reason": q.get("reason")} for q in failed],
        }
    def _candidates_from(self, report: dict) -> list[dict]:
        """从 ``report.payload`` 里提取候选问题（确定性 + 可解释）。
        ## 假设的 payload 形状（按契约读取，全部用 ``.get`` 容错）
        与 ``agent_c`` 当前实现核对过（字段名以它为准，未命中的别名一并兼容）：
        - ``hottest``：``payload["entries"] = [{"concept_id","name","occurrences","relation_count","group_count","degree","representative_relations":[...]}]``；
        - ``paths``：``payload["paths"] = [{"concept_path": [...], "relation_chain": [...],"hops": N, "level": "high|medium|low", "score": 3.4, "score_breakdown": {...}}]``
        —— 注意链字段叫 relation_chain（旧别名 ``relation_path`` 也认）；- ``cold``：
        ``payload["entries"] = [{"concept_id","name","degree","undervalued": bool,"relations_to_hot": [{"relation_id","weak_points": 0|1|2,"weak_score": 0.5,...}]}]``，
        ``undervalued is True``（或 ``relations_to_hot`` 里有 ``weak_points == 0`` 的）即"冷门但连接强"；- 
        ``gaps``：``payload["candidate_gaps"] = [{"concept_ids": [...],"related_relation_ids": [...], "positive_signals": [...], "reason": "...","confidence": "..."}]``。
        字段名不符时退化为"就地找代号数组"，不会因为形状变化而抛异常 ——C 与 D 是并行开发的，D 必须能容忍对方的小幅字段改名；容错的代价是可能少提几个问题（可观测：报告的
        "候选提炼"一节会写明 skipped 原因）。
        """
        kind = str(report.get("kind") or "")
        payload = report.get("payload") or {}
        rid = str(report.get("report_id") or "????")
        out: list[dict] = []

        def _entries(*names: str) -> list:
            """按候选键名依次取第一个非空列表（兼容字段改名）。"""
            for n in names:
                v = payload.get(n)
                if isinstance(v, list) and v:
                    return v
            return []

        if kind == "hottest":
            concepts = _entries("entries", "concepts", "top_concepts", "hot")[:3]
            top = [c for c in concepts if isinstance(c, Mapping)]
            cids = [str(c.get("concept_id") or c.get("id") or "") for c in top]
            cids = [c for c in cids if S.is_valid_id(c)]
            names = [str(c.get("name") or cid) for c, cid in zip(top, cids)]
            if cids:
                out.append(
                    {
                        "kind": "hottest",
                        "origin": f"C:hottest:{rid}:" + ",".join(cids),
                        "question": f"最热门的 {len(cids)} 个概念（{'、'.join(names)}）为何成为关系网络的枢纽？"
                        "它们之间的联结是否构成一个可检验的共同机制？",
                        "related_concept_ids": cids,
                        "related_relation_ids": self._relation_ids_touching(cids),
                        "seed_names": names,
                        "priority": "medium",
                        "why": f"C 报告 {rid} 统计出这些概念的出现次数最高："
                        + "、".join(
                            f"{n}(occurrences={c.get('occurrences')},relation_count={c.get('relation_count')})"
                            for n, c in zip(names, top)
                        ),
                    }
                )

        elif kind == "paths":
            paths = _entries("paths")
            high = [p for p in paths if isinstance(p, Mapping) and str(p.get("level")) in ("high", "medium")]
            for p in high[:3]:
                cpath = [str(x) for x in (p.get("concept_path") or [])]
                rpath = [str(x) for x in (p.get("relation_chain") or p.get("relation_path") or [])]
                if len(cpath) < 2:
                    continue
                chain = "->".join(rpath) if rpath else "-"
                # 概念名优先用 C 已经翻译好的（口径以 C 为准），缺失再本地查
                cnames = [str(x) for x in (p.get("concept_names") or [])]
                names = cnames if len(cnames) == len(cpath) else [self._concept_name(c) for c in cpath]
                out.append(
                    {
                        "kind": "paths",
                        "origin": f"C:paths:{rid}:" + chain,
                        "question": f"从「{names[0]}」到「{names[-1]}」经由关系链 [{chain}] 的推导是否成立？"
                        "该链条的每一步是否都有原文支撑、能否被反例削弱？",
                        "related_concept_ids": [c for c in cpath if S.is_valid_id(c)],
                        "related_relation_ids": [r for r in rpath if S.is_valid_id(r)],
                        "seed_names": names,
                        "priority": "high" if str(p.get("level")) == "high" else "medium",
                        "why": f"C 报告 {rid} 判定该路径信息量为 {p.get('level')}"
                        f"（score={p.get('score')}，breakdown={p.get('score_breakdown')}，hops={p.get('hops')}）",
                    }
                )

        elif kind == "cold":
            concepts = _entries("entries", "concepts", "cold_concepts")
            selected: list[tuple[Mapping, list]] = []
            for c in concepts:
                if not isinstance(c, Mapping):
                    continue
                links = list(c.get("strong_links") or c.get("strong_relations") or [])
                if not links:
                    # agent_c 的口径：undervalued 为真，或 relations_to_hot 里有
                    # weak_points == 0 的强连接（§3.3(3) 第 4 条）
                    links = [
                        r
                        for r in (c.get("relations_to_hot") or [])
                        if isinstance(r, Mapping) and r.get("weak_points") == 0
                    ]
                if c.get("undervalued") or links:
                    selected.append((c, links))
            for c, links in selected[:3]:
                cid = str(c.get("concept_id") or "")
                if not S.is_valid_id(cid):
                    continue
                rids = [str(x.get("relation_id")) for x in links if isinstance(x, Mapping) and x.get("relation_id")]
                name = str(c.get("name") or self._concept_name(cid))
                out.append(
                    {
                        "kind": "cold",
                        "origin": f"C:cold:{rid}:{cid}",
                        "question": f"冷门概念「{name}」却与热门概念存在强连接（关系 {','.join(rids) or '-'}）——"
                        "它是否是一个被低估的研究切入点？该连接为何长期无人跟进？",
                        "related_concept_ids": [cid],
                        "related_relation_ids": [r for r in rids if S.is_valid_id(r)],
                        "seed_names": [name],
                        "priority": "medium",
                        "why": f"C 报告 {rid} 把 {cid} 归入「冷门但连接强」（degree={c.get('degree')}，"
                        f"undervalued={c.get('undervalued')}），这类最可能是被低估的研究点",
                    }
                )

        elif kind == "gaps":
            gaps = _entries("candidate_gaps", "candidates")[:3]
            for g in gaps:
                if not isinstance(g, Mapping):
                    continue
                cids = [str(x) for x in (g.get("concept_ids") or g.get("concepts") or [])]
                cids = [c for c in cids if S.is_valid_id(c)]
                if len(cids) < 2:
                    continue
                rids = [str(x) for x in (g.get("related_relation_ids") or g.get("relation_ids") or [])]
                cnames = [str(x) for x in (g.get("concept_names") or [])]
                names = cnames if len(cnames) == len(cids) else [self._concept_name(c) for c in cids]
                out.append(
                    {
                        "kind": "gaps",
                        "origin": f"C:gaps:{rid}:" + ",".join(cids),
                        "question": f"「{names[0]}」与「{names[1]}」之间是否应当存在直接关系？"
                        f"（C 的信号：{_digest(g.get('reason'), 120)}）",
                        "related_concept_ids": cids,
                        "related_relation_ids": [r for r in rids if S.is_valid_id(r)],
                        "seed_names": names,
                        "priority": "high" if str(g.get("confidence")) == "high" else "medium",
                        "why": f"C 报告 {rid} 的候选缺口：reason={_digest(g.get('reason'), 160)}，"
                        f"confidence={g.get('confidence')}，positive_signals={g.get('positive_signals')}",
                    }
                )

        # 通用兜底：payload 里直接给了概念/关系代号但没有可识别的分组
        if not out:
            cids = self._collect_ids(payload, ("concept_id", "concept_ids"))
            rids = self._collect_ids(payload, ("relation_id", "relation_ids"))
            if cids or rids:
                names = [self._concept_name(c) for c in cids[:3]]
                out.append(
                    {
                        "kind": kind or "unknown",
                        "origin": f"C:{kind or 'unknown'}:{rid}",
                        "question": (
                            f"C 报告（{kind}）涉及概念 {','.join(cids[:5]) or '-'} 与关系 {','.join(rids[:5]) or '-'}："
                            "这些代号指向的表述之间是否存在尚未被研究的关联？"
                        ),
                        "related_concept_ids": cids[:5],
                        "related_relation_ids": rids[:5],
                        "seed_names": names,
                        "priority": "medium",
                        "why": f"C 报告 {rid} 的 payload 结构未被识别（key={sorted(payload)[:8]}），"
                        "按代号集合生成兜底问题（这是容错路径，不是主路径）",
                    }
                )
        return out
    def _collect_ids(self, node: Any, keys: Sequence[str], *, depth: int = 0) -> list[str]:
        """递归收集 payload 里形如代号的值（容错用，深度受限防环）。"""
        found: list[str] = []
        if depth > 4:
            return found
        if isinstance(node, Mapping):
            for k, v in node.items():
                if k in keys:
                    if isinstance(v, str) and S.is_valid_id(v):
                        found.append(v)
                    elif isinstance(v, list):
                        found.extend(str(x) for x in v if S.is_valid_id(x))
                else:
                    found.extend(self._collect_ids(v, keys, depth=depth + 1))
        elif isinstance(node, (list, tuple)):
            for item in node:
                found.extend(self._collect_ids(item, keys, depth=depth + 1))
        return sorted(set(found))
    def _concept_name(self, cid: str) -> str:
        # 合成视图（并表过渡期）：名字这一格两边都要看得到，否则报告里会出现"概念0007"
        for row in _CR.view(self.store, shape="legacy")["rows"]:
            if row.get("concept_id") == cid:
                return str(row.get("name") or cid)
        return f"概念{cid}"
    def _relation_ids_touching(self, concept_ids: Sequence[str]) -> list[str]:
        want = set(concept_ids)
        return sorted(
            str(r.get("relation_id"))
            for r in self.store.rows("relations")
            if want & set(r.get("concept_ids") or [])
        )
    @staticmethod
    def _content_key(kind: str, concept_ids: Sequence[str], relation_ids: Sequence[str]) -> tuple:
        """问题的内容键：决定"两个问题是不是同一个研究点"。

        用户要 D 评估的是"问题"，不是"报告条目"。同一份 C 分析跑两次会产生
        两个 ``report_id``（``AgentC.handle`` 每次都新发一个号），但关系链是同一
        条 —— 只按 ``origin`` 去重的话，第二个报告会把同样两条问题再提一遍，
        后果是 D 重复研究、以及（更贵的）向 A 问同一件事两次。

        键取 ``(kind, 排序后的关系代号)``；问题不带关系代号时（hottest/cold/gaps
        的某些形状）退回概念代号。必须在排序后比较 —— C 的路径可能以不同
        遍历顺序给出同样的链。
        """
        rels = tuple(sorted({str(x) for x in relation_ids if x}))
        concepts = tuple(sorted({str(x) for x in concept_ids if x}))
        return (str(kind), rels) if rels else (str(kind), "concepts", concepts)
    def _note_weak_clues(self, clues: Sequence[Mapping[str, Any]]) -> list[dict]:
        """把弱矛盾线索追加进"与之共享关系代号"的已有问题 notes，返回落痕记录。

        为什么要落痕而不是只写在内存里：线索的价值在于"以后证据变了能回头查"。
        只放在 `last_ingest` 里，进程一结束就没了；写进问题的 notes 才留在台账中。
        找不到共享关系代号的问题时如实记空（不编一个落点）。
        """
        noted: list[dict] = []
        try:
            with self.store.tx("research_questions", actor=self.actor, note="ingest_weak_clue") as tx:
                rows = tx.rows("research_questions")
                for clue in clues:
                    rids = {str(x) for x in (clue.get("relation_ids") or [])}
                    target = next(
                        (r for r in rows if rids & {str(x) for x in (r.get("related_relation_ids") or [])}),
                        None,
                    )
                    if target is None:
                        noted.append({"relation_ids": sorted(rids), "question_id": None,
                                      "reason": "没有共享这些关系代号的已有问题 ⇒ 只留在报告与 last_ingest 里"})
                        continue
                    line = (
                        f"[ingest] weak_conflict_clue: 关系 {'、'.join(sorted(rids))} 出现"
                        f"「{_digest(clue.get('signals'), 160)}」。strength={clue.get('strength')} ⇒ "
                        "只记录为线索，不建矛盾问题、不自动追问（弱信号的假阳性极高，"
                        "不能让 A 的产能烧在假矛盾上）。若后续证据让其中一方明确被否定，再走 I2。"
                    )
                    old = target.get("notes") or ""
                    if line not in old:
                        target["notes"] = (old + "\n" + line)[:20000]
                        target["updated_at"] = self._stamp()
                        S.row_from_dict("research_questions", target).validate()
                        tx.upsert("research_questions", target, note="weak_clue_noted")
                    noted.append({"relation_ids": sorted(rids), "question_id": str(target.get("question_id")),
                                  "reason": "已落进该问题的研究笔记"})
        except Exception as e:
            self.last_tool_errors.append({"tool": "tx:weak_clue", "error": f"{type(e).__name__}: {e}"})
        return noted
    @staticmethod
    def _kind_of_origin(origin: str) -> str:
        """从 ``C:<kind>:<report_id>[:...]`` 里取回 kind（内容键需要它）。

        ``contradictions`` 要规范化成 ``contradiction``：矛盾问题的
        ``origin`` 契约是 ``C:contradictions:<rid_a>+<rid_b>``（来源名），而问题
        的 kind 是 ``contradiction``（schema 词表）。不归一化的话，内容键
        "报告里读回来的行"与"候选"会永远不相等，跨报告的矛盾去重会静默失效。
        """
        parts = str(origin).split(":")
        kind = parts[1] if len(parts) > 1 else ""
        return "contradiction" if kind == "contradictions" else kind
    def _contradiction_candidates(
        self,
        info: Mapping[str, Any],
        c_contradictions: Mapping[str, Any] | None = None,
    ) -> dict:
        """把"矛盾"转成 ``kind="contradiction"`` 的候选问题（I2 的入口）。
        1. ``payload["contradictions"]`` —— C 报告里已经算出来的矛盾（最直接）； 2. 调用方通过 ``ingest(..., c_contradictions=...)`` 传进来的 I1 结果（D 
        在研究某个问题时点的那次菜，可以顺手交给 ingest 吸收）；
        第 3 条刻意不用 ``relation_ids=None`` 扫全图：那会在每份报告 ingest 时引入一个与本次分析无关的全局扫描，把无关矛盾灌进 D 的台账，表现是"一份 hottest 报告忽然带来十几条矛盾问题"。
        只有 ``strength == "strong"`` 才建问题（这是一次真实缺陷的对策）``interactions.detect_contradictions`` 会给出 ``strength``：
        - ``strong`` —— 一方明确断言肯定式、另一方明确断言对应的否定式（"A 是 B" vs "A 不是 B"）⇒ 允许建 ``kind="contradiction"`` 问题并自动追问；- ``weak`` —— 只是"
        否定标记出现与否不一致"（"不"/"not "）⇒ 假阳性极高（实测 25 条真实关系里 weak 报了 24%，且没有一条是真矛盾）。这一类只记成线索（``weak_clues`` + 落进相关问题的 notes + 报告），绝不
        触发检索请求 —— 否则 D 会把 A 的产能烧在一堆假矛盾上，而 I7 的配额本来就是为保护产能而设的。
        报告里的 ``strength`` 可能缺失或来自旧版，因此不信任它：缺失时就地用 ``interactions.detect_contradictions`` 对这两条关系重判一次（判据仍只有一份）。
        返回 ``{"candidates", "source", "checked", "reason", "skipped", "raw_count","weak_clues"}``。``checked`` 是三态：``True`` 查
        过、``False`` 查了但失败、``None`` 没查（没接线 / 没有可推导的范围）—— 后两者必须能被分开读。
        """
        if not self.ingest_contradictions:
            return {"candidates": [], "source": "disabled", "checked": None,
                    "reason": "config.ingest_contradictions=False ⇒ 本次 ingest 不吸收矛盾（没查，不是没有矛盾）",
                    "skipped": [], "raw_count": 0, "weak_clues": []}
        payload = info.get("payload") if isinstance(info.get("payload"), Mapping) else {}
        raw: Any = None
        source = "none"
        checked: bool | None = None
        reason = ""

        payload_contras = payload.get("contradictions") if payload else None
        if isinstance(payload_contras, list):
            # 字段存在（哪怕是空列表）就表示报告已经给过这项检查的结论：
            # 空列表 = "查过、范围内没有矛盾"，与"没查"是两件事，所以不退回自动拉取。
            source, checked, raw = "report_payload", True, payload_contras
        elif c_contradictions is not None:
            source = "c_service_explicit"
            checked = bool(c_contradictions.get("checked"))
            reason = str(c_contradictions.get("reason") or "")
            raw = list(c_contradictions.get("contradictions") or []) if checked else []
            if not checked and not reason:
                reason = "调用方传入的 C.contradictions 结果 checked=False 且无理由 ⇒ 视为没查"
        elif getattr(self, "c", None) is not None:
            rids = self._collect_ids(payload, ("relation_id", "relation_ids"))
            if rids:
                res = self._c_call("contradictions", relation_ids=sorted(rids), limit=self.max_c_contradictions)
                source = "c_service"
                checked = bool(res.get("checked"))
                reason = str(res.get("reason") or "")
                raw = list(res.get("contradictions") or []) if checked else []
                if not checked and not reason:
                    reason = "C.contradictions 未成功返回且未给理由 ⇒ 视为没查"
            else:
                source = "c_service"
                checked = None
                raw = []
                reason = (
                    "报告 payload 里没有关系代号，无法推导矛盾查询范围 ⇒ **没查**"
                    "（刻意不退回全图扫描：那会把无关矛盾灌进本报告的台账）"
                )
        else:
            source, checked, raw = "none", None, []
            reason = "D 未接入 C 服务且报告 payload 里没有 contradictions ⇒ **没查**（不是没有矛盾）"

        out: list[dict] = []
        skipped: list[str] = []
        weak_clues: list[dict] = []
        for item in raw or []:
            if not isinstance(item, Mapping):
                skipped.append(f"矛盾记录不是对象：{type(item).__name__} ⇒ 跳过")
                continue
            rids = [str(x) for x in (item.get("relation_ids") or item.get("relation_id_pair") or []) if x]
            if len(rids) != 2 or rids[0] == rids[1]:
                skipped.append(f"矛盾记录必须恰有 2 条**不同**的关系代号，收到 {rids!r} ⇒ 跳过")
                continue
            rids = sorted(set(rids))
            rel_rows: list[dict] = []
            for rid in rids:
                row = next((r for r in self.store.rows("relations") if str(r.get("relation_id")) == rid), None)
                if row is not None:
                    rel_rows.append(row)
            strength = str(item.get("strength") or "")
            if strength not in ("strong", "weak"):
                # 报告里的字段可能是旧版/缺失 ⇒ 就地用唯一权威判据重判，
                # 而不是默认成 strong（那会让一堆弱线索去烧 A 的产能）。
                rec = None
                if len(rel_rows) == 2:
                    rec = next(
                        (x for x in IX.detect_contradictions(rel_rows) if set(x["relation_ids"]) == set(rids)),
                        None,
                    )
                strength = str((rec or {}).get("strength") or "weak")
                if rec:
                    item = {**item, "signals": item.get("signals") or rec.get("signals") or []}
            signals = "；".join(str(x) for x in (item.get("signals") or [])) or "（C 未给出可核实的信号文本）"
            cids = sorted({str(x) for x in (item.get("concept_ids") or []) if x})
            if not cids:
                # 概念集必须由关系行现场推导（C 报告里可能没带）——
                # related_concept_ids 是 D 后续判"新证据是否相关"的依据，不能空着。
                for row in rel_rows:
                    cids.extend(str(x) for x in (row.get("concept_ids") or []) if x)
                cids = sorted(set(cids))
            if strength != "strong":
                # ---- 弱线索：只记录，不建问题、不追问
                weak_clues.append(
                    {
                        "relation_ids": rids,
                        "concept_ids": cids,
                        "strength": strength,
                        "signals": signals,
                        "detection": item.get("detection") or "literal",
                        "note": (
                            "strength != strong ⇒ 只是线索（'否定标记出现与否不一致'的假阳性极高，"
                            "实测 24% 的报警都不是矛盾）⇒ 不建矛盾问题、不提交检索请求"
                        ),
                    }
                )
                skipped.append(
                    f"弱线索（{'、'.join(rids)}，strength={strength or '未知'}）：只记录，不建问题/不追问"
                )
                continue
            names = [self._concept_name(c) for c in cids] or [f"关系{rids[0]}", f"关系{rids[1]}"]
            out.append(
                {
                    "kind": "contradiction",  # 内容键用的"来源类型"
                    "question_kind": "contradiction",  # schema 的问题 kind
                    "origin": f"C:contradictions:{rids[0]}+{rids[1]}",
                    "question": (
                        f"关系 {rids[0]} 与 {rids[1]} 的陈述互相矛盾，需要判定哪一方成立"
                        f"（涉及概念：{'、'.join(names)}；C 的信号：{_digest(signals, 160)}）"
                    ),
                    "related_concept_ids": cids,
                    "related_relation_ids": rids,
                    "contradiction_relation_ids": rids,
                    "seed_names": names,
                    "priority": "high",  # §1 I2：矛盾是最强信号，一律 high
                    "strength": strength,
                    "why": (
                        f"C 检测到矛盾对 {rids[0]} vs {rids[1]}"
                        f"（detection={item.get('detection') or 'literal'}，strength=strong，"
                        f"scope={item.get('scope') or IX.CONFLICT_SCOPE}）：{_digest(signals, 200)}"
                    ),
                    "source": source,
                }
            )
        return {
            "candidates": out,
            "source": source,
            "checked": checked,
            "reason": reason,
            "skipped": skipped,
            "raw_count": len(raw or []),
            "weak_clues": weak_clues,
        }
    @staticmethod
    def _chain_order(qrow: Mapping[str, Any]) -> list[str]:
        """从 ``origin`` 里读回按跳序的关系链；读不到时退回升序的 ``related_relation_ids``。

        为什么必须从 ``origin`` 读：``ResearchQuestion.related_relation_ids`` 是
        schema 规定"升序去重"的字段，跳序在那里已经丢失。而 C 在 ``origin``
        里写的是它分析出来的真实链条（``C:paths:0000:0009->0010->0005``）。
        报告要让人"顺着链读"，就必须用这个顺序。

        读不到（非 paths 来源、或 origin 被人改过）时退回升序 —— 顺序可能是错的，
        但绝不编一个不存在的链条；报告里会写成"直接相关的关系（无跳序信息）"。
        """
        origin = str(qrow.get("origin") or "")
        parts = origin.split(":")
        if len(parts) >= 4 and parts[1] == "paths":
            ids = [x.strip() for x in parts[3].split("->") if x.strip()]
            ids = [x for x in ids if S.is_valid_id(x) or x == "-"]
            ids = [x for x in ids if S.is_valid_id(x)]
            if ids:
                return list(dict.fromkeys(ids))
        return [str(x) for x in (qrow.get("related_relation_ids") or []) if x]
    def _chain_concept_path(self, qrow: Mapping[str, Any], chain_ids: Sequence[str]) -> list[str]:
        """从原始 C 报告里取回这条链的概念路径（用来标注每一跳的方向）。

        为什么值得多查一次：``trace.relation`` 只知道一条关系连接了哪几个概念
        （``concept_ids`` 是升序的），所以它给出的"素理想 → 环同态"可能把方向
        写反。而 C 在报告 payload 的 ``paths[].concept_path`` 里明确记了这条链的
        走向（群→环同态→素理想→域）。报告要让人"顺着链读"，方向就必须来自
        C 的分析结果，而不是我按代号大小猜一个。

        找不到（报告被移走、payload 形状不符、链不匹配）时返回 ``[]`` ——
        此时渲染退回"概念组"的写法，不编方向。
        """
        origin = str(qrow.get("origin") or "")
        parts = origin.split(":")
        if len(parts) < 3 or not S.is_valid_id(parts[2]):
            return []
        rid = parts[2]
        rep = next((x for x in self.store.rows("analysis_reports") if str(x.get("report_id")) == rid), None)
        if rep is None:
            # R002 的例外，理由（不是把"没做"折叠成"没有"）：
            # 这是渲染层的辅助函数，问的是"C 的报告里有没有记过这条链的方向"。
            # 报告不在库里时，正确答案就是"我没有依据 → 退回概念组的写法"，
            # 而不是"方向是空的"。调用方（`trace_question`）拿到 `[]` 后走的是
            # "不编方向"的分支，不会把 `[]` 当成一个关于世界的断言。
            # 真正的三态由上层负责：证据是否就绪是 `assess()` 的结论，不是这里。
            return []
        wanted = [str(x) for x in chain_ids]
        for p in (rep.get("payload") or {}).get("paths") or []:
            if not isinstance(p, Mapping):
                continue
            if [str(x) for x in (p.get("relation_chain") or [])] == wanted:
                cpath = [str(x) for x in (p.get("concept_path") or [])]
                if len(cpath) == len(wanted) + 1:
                    return cpath
        return []
    def _trace_one(self, tool_name: str, **params: Any) -> Any:
        """调一个溯源工具，返回其 ``data``；工具不存在 / 调用失败返回 None。

        为什么不用 ``self._call``：溯源工具可能压根没被注册（外部的
        ``trace_tools`` 还没写好）；那种情况下我们要的是"安静地降级"，
        而不是往 ``last_tool_errors`` 里灌一堆噪声 —— 降级本身会在证据包的
        ``trace_mode`` 字段里如实写明。
        """
        if tool_name not in self.tools:
            return None
        res = self.tools.call(tool_name, **params)
        if not res.ok:
            if res.meta.get("kind") != "unknown_tool":
                self.last_tool_errors.append({"tool": tool_name, "error": res.error, "kind": res.meta.get("kind")})
            return None
        return res.data
    def _relations_by_id(self) -> dict[str, dict]:
        rels = {str(r.get("relation_id")): r for r in self.store.rows("relations")}
        for r in rels.values():
            # `concept_pair_key` 是派生态，这里顺手补上（D 自己的判据计算要读它）。
            #
            # 注意：`interactions.detect_contradictions` 现在自己就会就地推导
            # 这个键（表里存的字段叫 `concept_group_key`，早先直接读 `concept_pair_key`
            # 会让"从表里读出来的行"恒返回空结果 —— 完全静默，看起来像"没有矛盾"）。
            # 所以这里的补字段不再是正确性的前提，只是让 D 侧读起来一致；
            # 谁要是删掉它，矛盾判据也不会再静默失效。
            r["concept_pair_key"] = IX.concept_pair_key([str(c) for c in (r.get("concept_ids") or []) if c])
        return rels
    def _local_relation_claim(self, rid: str) -> dict:
        """L1 的本地兜底：只读关系行，逐字返回，不做任何转写。"""
        row = next((r for r in self.store.rows("relations") if r.get("relation_id") == rid), None)
        if row is None:
            return {"found": False, "relation_id": rid, "source": "fallback"}
        return {
            "found": True,
            "source": "fallback",
            "relation_id": rid,
            "concept_ids": list(row.get("concept_ids") or []),
            "lit_id": row.get("lit_id"),
            "quote": row.get("quote") or "",
            "description": row.get("description") or "",
            "statement": row.get("statement") or "",
            "page_range": row.get("page_range") or {},
            "status": row.get("status"),
            "quote_verified": row.get("quote_verified"),
        }
    def _local_concept(self, cid: str) -> dict:
        """L2 的本地兜底。"""
        row = next((c for c in _CR.view(self.store, shape="legacy")["rows"]
                    if c.get("concept_id") == cid), None)
        rels = [
            {
                "relation_id": r.get("relation_id"),
                "concept_ids": list(r.get("concept_ids") or []),
                "quote": r.get("quote") or "",
                "description": r.get("description") or "",
                "status": r.get("status"),
                "quote_verified": r.get("quote_verified"),
                "lit_id": r.get("lit_id"),
            }
            for r in self.store.rows("relations")
            if cid in (r.get("concept_ids") or [])
        ]
        if row is None and not rels:
            return {"found": False, "concept_id": cid, "source": "fallback"}
        return {
            "found": True,
            "source": "fallback",
            "concept_id": cid,
            "name": (row or {}).get("name") or "",
            "definition": (row or {}).get("definition") or "",
            "aliases": list((row or {}).get("aliases") or []),
            "related_concepts": list((row or {}).get("related_concepts") or []),
            "relations": rels,
            "degree": len(rels),
        }
    def _local_literature(self, lid: str) -> dict:
        row = next((r for r in self.store.rows("literature") if r.get("lit_id") == lid), None)
        if row is None:
            return {"found": False, "lit_id": lid, "source": "fallback"}
        path = None
        try:
            path = self.store.library_path(row.get("path"))
        except StoreError:
            path = None
        return {
            "found": True,
            "source": "fallback",
            "lit_id": lid,
            "title": row.get("title") or "",
            "type": row.get("type"),
            "year": row.get("year"),
            "doi": row.get("doi"),
            "processed": bool(row.get("processed")),
            "download_status": (row.get("download") or {}).get("status"),
            "file_exists": bool(path and path.exists()),
            "text_available": False,
        }
    def _l3_needed(self, verdict: dict, evidence: dict) -> bool:
        """是否必须下钻到正文（L3）。判据可核实，不用"感觉需要更多细节"。"""
        if self.force_l3:
            return True
        if verdict.get("contradictions"):
            return True  # 矛盾要靠原文语境判定谁对
        claims = evidence.get("claims") or []
        # 2026-10-17（agents #4 同族，真身在这里）：`claims` 可能是 str / 字典 ——
        # 只对 Mapping 元素取 `.get`，否则 `c.get` 在字符上抛 AttributeError。
        claims = [c for c in claims if isinstance(c, Mapping)] if isinstance(claims, (list, tuple)) else []
        if claims and not any(c.get("quote_verified") is True for c in claims):
            return True  # 要写结论却一条可核验的引文都没有
        return False
    def _budget(self) -> dict:
        """请求预算（§8 待决问题 3）。
        
        两道闸：每个问题最多 2 轮、全局最多 20 个请求。没有预算的话，一个措辞有问题的判据就能让 D 对着同一个问题无限提问，而 A 的队列是共享资源（别的智能体也在用）。
        
        账本来自 :meth:`_d_requests`（含矛盾闭环那些带后缀的行 —— CS-3 的另一半）。从前这里按 `== self.actor` 精确过滤，于是矛盾那一支
        提交的请求不被计入：全局上限与"每问题 2 轮"都少算一整类，而 `submit_gaps` 用的正是这两个数。
        
        返回里另附 `by_channel`：本角色提交的请求按通道分组（缺省通道 `gap` = 缺口那一支，带后缀的按后缀名）。它是纯读数，不参与任何判定 —— 存在的理由是"
        总额少了/多了"这句话必须能一眼看出是哪条通道贡献的。
        """
        mine = self._d_requests()
        per_q: dict[str, int] = {}
        by_channel: dict[str, int] = {}
        for r in mine:
            who = str(r.get("submitted_by") or "")
            # 通道名 = `actor` 之后那个冒号后面剩下的部分；没有冒号 ⇒ 缺口那一支（缺省通道）。
            by_channel[who.split(":", 1)[1] if ":" in who else "gap"] = (
                by_channel.get(who.split(":", 1)[1] if ":" in who else "gap", 0) + 1
            )
            # 归属优先读结构化字段（`for_question_id`，`schema.py:226-228`）；
            # 只有老行（那个字段还是空的）才回落到描述文本里的 `[q:NNNN]`。
            # 为什么要有这条回落：并表/加字段之前落下的行没有那个键，
            # 而"读不到"与"不属于任何问题"必须分得开（三态纪律）——
            # 于是这里按"字段空 ⇒ 试正则 ⇒ 都空 ⇒ 不计入 per_q"三档走。
            qid = str(r.get("for_question_id") or "").strip()
            if not qid:
                m = re.search(rf"\[q:({S.ID_OR_LEGACY_PATTERN})\]", str(r.get("content_description") or ""))
                qid = m.group(1) if m else ""
            if qid:
                per_q[qid] = per_q.get(qid, 0) + 1
        return {
            "total": len(mine),
            "total_limit": self.max_total_requests,
            "remaining": max(0, self.max_total_requests - len(mine)),
            "per_question": per_q,
            "per_question_limit": self.max_requests_per_question,
            "by_channel": by_channel,
        }
    def _d_requests(self) -> list[dict]:
        """本角色提交过的全部检索请求行（含带通道后缀的那些）。
        这本账只此一处：`_budget` 与 `_contradiction_budget` 都从这里取。从前两处各读一次 `search_requests`、按各自的口径过滤 ⇒ 同一件事有两套计数（CS-3）。
        ## 为什么必须认后缀（CS-3 的另一半）
        矛盾闭环提交的行写的是 `submitted_by="agent-D:contradiction"`（`agent_d/adjudicate.py` 写行那一处）。那个后缀是有意的：
        `interactions.resolve_priority` 按它把优先级分成 high 与 medium 两档，`schema.SUBMITTER_DEFAULT_PRIORITY` 里也是两
        个独立的键。而旧的过滤是 `== self.actor` 的精确比较 ⇒ 矛盾那一支提交的请求一条都不进这本账：全局上限（缺省 20）少算一整类请求，"每个问题最多 2 轮"也看不见它们 ——而这
        两道闸门管的是共享资源（A 的产能），少算的方向恰好是"闸门看起来在、实际更松"。
        ## 为什么只认冒号后缀，不认"以 actor 开头"
        本仓的通道后缀用冒号（`agent-D:contradiction` 是登记过的键），实例后缀用连字符（`agent-A-egr` 那种，见 `draft/108` 四·CS-15）。
        `startswith(actor)` 会把 `agent-D2` 这类别的实例一起吞进来；`startswith(actor + "-")` 会把实例轴也拉进这本账 —— 那是 CS-15 要裁
        的政策，不该在这里顺手决定。所以只认冒号。
        """
        prefix = f"{self.actor}:"
        return [
            dict(r)
            for r in self.store.rows("search_requests")
            if (who := str(r.get("submitted_by") or "")) == self.actor or who.startswith(prefix)
        ]
    def _pending_of(self, qrow: dict) -> list[dict]:
        return RT.pending_requests_of(qrow, self.store.rows("search_requests"))
    def _search_topic_and_desc(self, qrow: dict, evidence: dict) -> tuple[str, str]:
        """构造提交给 A 的 topic 与内容描述。

        topic 用问题的概念名而不是整句问题：A 的 provider 是关键词检索，
        把一整句疑问句扔过去只会得到噪声。缺概念名时退化为问题前 60 字。
        """
        concepts = evidence.get("l2") or []
        names = [c.get("name") for c in concepts if c.get("name")][:4]
        question = str(qrow.get("question") or "")
        topic = " ".join(names) if names else _digest(question, 40)
        desc = (
            f"[q:{qrow.get('question_id')}] origin={qrow.get('origin')}；"
            f"研究问题：{_digest(question, 200)}；"
            f"需要检索的是：能补充该问题证据的文献"
            f"（现有相关关系 {len(evidence.get('claims') or [])} 条，"
            f"其中 quote_verified=True 的 "
            f"{sum(1 for c in evidence.get('claims') or [] if c.get('quote_verified') is True)} 条）"
        )
        return topic, desc
    def _note(self, qid: str, text: str) -> None:
        """追加研究笔记（走工具，保持"所有写操作都经过工具层"这条一致性）。"""
        self._call("research.write_note", question_id=qid, note=text)
    def _promote_to_researching(self, qid: str, *, reason: str = "") -> None:
        """把问题的状态推进到 ``researching``（直写 store 的降级路径）。

        只在工具层不可用/失败时走这里；正常路径一律经 ``research.set_status``，
        以便所有写操作都留在工具层（可审计、可加审批）。这里同样过一遍 schema
        校验，绝不允许"为了推进状态"而写入非法行。
        """
        try:
            with self.store.tx("research_questions", actor=self.actor, note="promote") as tx:
                row = tx.find("research_questions", question_id=qid)
                if row is None:
                    return
                row["status"] = "researching"
                row["updated_at"] = self._stamp()
                if reason:
                    old = row.get("notes") or ""
                    row["notes"] = (old + "\n" + reason)[:20000]
                S.row_from_dict("research_questions", row).validate()
                tx.upsert("research_questions", row, note="promote_researching")
        except Exception as e:
            self.last_tool_errors.append({"tool": "tx:promote", "error": f"{type(e).__name__}: {e}"})
    @staticmethod
    def _append_note_once(row: Mapping[str, Any], line: str) -> str:
        """把一条笔记追加进 notes，同一类内容只写一次。

        为什么必须去重：poll 每轮都会重新看到同一批"已完成"的请求。若每次都追加，
        一个查不到东西的问题会在几轮内把 notes 撑到 20000 字的截断线，
        真正有用的研究笔记会被挤掉 —— 那是不可逆的信息损失。
        """
        old = str(row.get("notes") or "")
        marker = line.split("：", 1)[0].split(":", 1)[0]
        if marker and marker in old:
            return old
        return (old + "\n" + line)[:20000]
    @staticmethod
    def _lower_priority(row: dict) -> str:
        """按 ``S.PRIORITIES`` 降一档（high→medium→low）；已是 low 就不再降。"""
        cur = str(row.get("priority") or "low")
        idx = S.PRIORITIES.index(cur) if cur in S.PRIORITIES else len(S.PRIORITIES) - 1
        row["priority"] = S.PRIORITIES[min(idx + 1, len(S.PRIORITIES) - 1)]
        return str(row["priority"])
    def _contradiction_budget(self) -> dict:
        """全局矛盾检索配额（I2 的硬上限之一）。
        统计口径：所有 ``kind="contradiction"`` 问题的 ``contradiction_request_ids``之和 —— 不是"本轮提交了几条"，也不
        是"还在途几条"。只有用"历史上提交过几条"才能保证这个循环一定在有限步内停下来；用"在途条数"会在请求完成之后重新腾出配额，循环又活了（这正是"看起来有闸门、实际没有"的
        形态）。
        ## 读侧对账（CS-3 的另一半）
        上面那本账记在问题行上（`contradiction_request_ids`），而请求行自己只记`submitted_by`。两者今天由 `adjudicate` 在同一
        笔事务里一起写 ⇒ 必然一致，但没有任何判据守这件事：一次手工补行、一次中途失败的迁移、或将来某条新路径只写一边，都会让"配额统计"与"盘上到底有几条"悄悄分家，而两边的读
        数看起来都正常。所以这里把另一个方向也数出来（:meth:`_d_requests` 里挂在矛盾问题上的那些行）：
        - `used`      —— 问题行上的台账口径（判定用，不变）；- `by_rows`   —— 请求行口径：本角色提交的、`for_question_id` 指向矛
        盾问题的行数；- `reconciled` —— 两者相等。不许把它当成"配额是否用完"的判据（那是 `exhausted`），它只回答"这两本账今天对不对得上"。
        """
        rows = self.store.rows("research_questions")
        contradiction_qids = {
            str(r.get("question_id")) for r in rows if str(r.get("kind")) == "contradiction"
        }
        used = sum(
            len(r.get("contradiction_request_ids") or []) for r in rows if str(r.get("kind")) == "contradiction"
        )
        by_rows = sum(
            1 for r in self._d_requests() if str(r.get("for_question_id") or "") in contradiction_qids
        )
        limit = int(self.max_contradiction_requests)
        return {
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
            "exhausted": used >= limit,
            "by_rows": by_rows,
            "reconciled": used == by_rows,
        }
    def _contradiction_scope(self, rel_ids: Sequence[str]) -> list[dict]:
        """同一概念组的全部关系（重新从表里读，I2 要求"复核"而不是"回忆"）。
        
        为什么范围是"同概念组"而不是"那两条关系本身"：裁决要判的是"这一对是否还对立"，而对立的判据（``detect_contradictions``）本来就只在同概念组内成
        立；把同组关系全带上，才能同时发现新冒出来的矛盾对 ——``new_contradiction`` 这一支的全部输入都来自这里。
        
        这里给每行补 ``concept_pair_key`` 是为了 D 侧读起来一致：`interactions.detect_contradictions` 已改成缺字段时就
        地推导，所以它不再是正确性的前提（早先漏补这个键会让矛盾检测静默返回空）。
        
        两条关系都已经不在表里（被删/被合并）时返回 ``[]``：那是"争议双方都已消失"的证据，``adjudicate_contradiction`` 会据此判 
        ``side_removed``。
        """
        rows = self.store.rows("relations")
        keys: set[str] = set()
        wanted = {str(x) for x in rel_ids}
        keyed: list[tuple[str, str | None, dict]] = []
        for r in rows:
            key = r.get("concept_pair_key") or IX.concept_pair_key(
                [str(c) for c in (r.get("concept_ids") or []) if c]
            )
            keyed.append((str(r.get("relation_id")), key, dict(r)))
            if str(r.get("relation_id")) in wanted and key:
                keys.add(str(key))
        if not keys:
            return []
        out: dict[str, dict] = {}
        for rid, key, row in keyed:
            if key in keys:
                row["concept_pair_key"] = key
                out[rid] = row
        return [out[k] for k in sorted(out)]
    def _contradiction_request_text(
        self,
        qrow: Mapping[str, Any],
        observed: Sequence[Mapping[str, Any]],
        round_no: int,
        verdict: Mapping[str, Any],
    ) -> tuple[str, str]:
        """构造矛盾追问的 ``topic`` 与内容描述。

        与普通缺口一样，``topic`` 用概念名而不是整句疑问句：A 的 provider 是
        关键词检索，一整句疑问句只会得到噪声。矛盾链的代号也一并写进描述，
        让 A/人看得出"这次追问是为了判定哪两条表述"。
        """
        rids = [str(x) for x in (qrow.get("contradiction_relation_ids") or [])]
        names = [self._concept_name(str(c)) for c in (qrow.get("related_concept_ids") or [])][:4]
        topic = " ".join(n for n in names if n) or f"关系 {rids[0] if rids else '?'} 矛盾"
        quotes = "；".join(
            f"{o.get('relation_id')}：{_digest(o.get('statement') or o.get('description'), 100)}"
            for o in observed
        )
        desc = (
            f"[q:{qrow.get('question_id')}] kind=contradiction 第 {round_no} 轮追问；"
            f"矛盾对 {' vs '.join(rids)}；当前两条表述：{quotes}；"
            f"需要检索的是：能判定该分歧哪一方成立的文献"
            f"（上次裁决 {verdict.get('code')}：{_digest(verdict.get('reason'), 160)}）"
        )
        return topic, desc
    def _adjudicate_ready_contradictions(self) -> list[dict]:
        """本轮先裁决"可裁决"的矛盾问题（I2），返回裁决结果列表。

        什么叫"可裁决"：``kind="contradiction"``、未终结（不是 answered/dropped、
        也没标 persistent）、且没有未完成的检索请求。

        最后一条很关键：请求还没回来就裁决，只会把同一轮追问重复提交一遍
        （等待集里已经挂着一个在途的请求），把 A 的队列刷爆 —— 那是"闸门看起来
        存在但没起作用"的典型。

        单轮设有 ``max_adjudications_per_round`` 上限：一份报告可能一次带进来
        十几对矛盾，全放出去等于一轮之内打十几条 high 请求。
        """
        rows = [r for r in self.store.rows("research_questions") if str(r.get("kind")) == "contradiction"]
        requests = self.store.rows("search_requests")
        out: list[dict] = []
        for row in sorted(rows, key=lambda r: str(r.get("question_id"))):
            if len(out) >= self.max_adjudications_per_round:
                self.last_tool_errors.append(
                    {
                        "tool": "adjudicate",
                        "error": f"本轮裁决数达到上限 {self.max_adjudications_per_round}，其余矛盾问题留到下一轮",
                    }
                )
                break
            qid = str(row.get("question_id"))
            if str(row.get("status") or "") in ("answered", "dropped"):
                continue
            if str(row.get("contradiction_verdict") or "") == "persistent":
                continue
            pending = RT.pending_requests_of(row, requests)
            if pending:
                out.append(
                    {
                        "question_id": qid,
                        "checked": True,
                        "action": "skipped",
                        "reason": (
                            f"仍有未完成的检索请求 {[r.get('request_id') for r in pending]}，"
                            "等它回来（且有新证据）再裁决"
                        ),
                    }
                )
                continue
            try:
                out.append(self.adjudicate(qid))
            except Exception as e:  # 单条矛盾的失败不能打断整轮
                self.last_tool_errors.append({"tool": "adjudicate", "error": f"{type(e).__name__}: {e}"})
                out.append(
                    {"question_id": qid, "checked": False, "action": "failed",
                     "reason": f"{type(e).__name__}: {e}"}
                )
        self.last_adjudications = out
        return out
    def _apply_c_evidence_caveat(
        self,
        ev: Mapping[str, Any],
        verdict: Mapping[str, Any],
        conclusion: str,
        suggestions: list[str],
    ) -> tuple[str, list[str]]:
        """I1 的硬要求：一条 C 查询都没成功时，结论必须显式标注「无 C 侧证据」。

        为什么不能只是"悄悄少写一段"：C 的图查询是"这两个概念之间到底有哪些
        链条、还有没有别的矛盾关系"的唯一来源。缺了它，D 的结论只建立在问题
        自己引用的那几条关系上，而报告读起来与有 C 侧证据时一模一样 ——
        读者会把"没查"当成"查过了，就是这样"。

        所以这里做三件事（都是可判定的，不依赖措辞自觉）：
        1. 结论前面加显式标注与失败原因（哪个 api、什么错）；
        2. 结论后面加一条"不得作为确定结论引用"的提醒（覆盖 LLM 写出的确定语气）；
        3. 追加一条后续建议（怎么修）。
        """
        summary = verdict.get("c_evidence") or self._c_summary(ev.get("c_queries") or [])
        if summary.get("any_success"):
            return conclusion, suggestions
        why = "；".join(f"{f.get('api')}: {f.get('reason')}" for f in summary.get("failures") or []) or "未发起任何 C 查询"
        head = (
            f"**{C_NO_EVIDENCE}**：本问题对 C 的按需查询**全部没有成功**"
            f"（共 {summary.get('attempted')} 次；{why}）。以下判断只基于 D 侧溯源到的"
            "关系表述，未经 C 的图查询核对，因此不作确定结论 —— "
            "「没问到」不等于「不存在」。"
        )
        tail = (
            f"⚠️ 本条结论**{C_NO_EVIDENCE}**（失败原因见上）：在 C 服务可用并成功查询之前，"
            "不得把本节的措辞当作已核实的判断引用。"
        )
        return f"{head}\n\n{conclusion}\n\n{tail}", suggestions + [
            f"修复 C 服务接线（I1）后重跑本问题：当前{C_NO_EVIDENCE}，结论未经图查询核对。"
        ]
    def _compose(self, ev: dict, verdict: dict) -> tuple[str, str, list[str], bool]:
        """产出（初步分析, 结论, 后续建议, 是否用了 LLM）。
        
        确定性回退（``llm=None``）是基线而非残次品：它逐条罗列可核实的证据（命中数、度数、quote_verified 分布、矛盾对），措辞朴素但每一句都能被回到表里核
        对。LLM 只被允许在这之上"写得更通顺"，且结论必须能回指证据。
        
        ## 三态（`R1-A1`：`llm_used=False` 不许再折叠"没接线"与"接了但失败"）
        
        这一次调用落在 :attr:`last_llm_reading` 里（`{kind, state, reason, model, calls}`，
        `state ∈ {not_wired, used, failed, unknown_object}`）：`False` 只是"这一趟的结论不是模型给的"，而为什么由这一格
        回答。`except` 保留（LLM 失败绝不能打断循环），但它现在会把失败如实记进读数而不是只丢一条 `last_tool_errors` —— 接口错（例如给了一个既没
        有 `ask_json`也没有 `complete` 的对象）因此不再伪装成"没接线"。
        """
        self.last_llm_reading = {"kind": KIND_NONE, "state": STATE_NOT_WIRED,
                                 "reason": "没有接线（llm is None）", "model": "", "calls": 0}
        if self.llm is not None:
            try:
                out, reading = self._llm_refine(ev, verdict)
                self.last_llm_reading = reading
                if out is not None:
                    return out["analysis"], out["conclusion"], out["suggestions"], True
            except Exception as e:  # LLM 失败绝不能打断循环
                self.last_tool_errors.append({"tool": "llm", "error": f"{type(e).__name__}: {e}"})
                self.last_llm_reading = {
                    "kind": model_kind(self.llm), "state": STATE_FAILED,
                    "reason": f"{type(e).__name__}: {e}",
                    "model": str(getattr(self.llm, "model_name", "") or ""), "calls": 0,
                    "note": "异常被 `_compose` 的 fail-open 兜住；这一格记的是原始异常",
                }
        return self._deterministic_compose(ev, verdict)
    def _deterministic_compose(self, ev: dict, verdict: dict) -> tuple[str, str, list[str], bool]:
        claims = ev.get("claims") or []
        hits = verdict.get("hits") or {}
        conf = verdict.get("confidence")
        lines: list[str] = []
        if not claims:
            lines.append("溯源到 L1/L2 后**没有取到任何关系表述**：这个问题目前完全没有可引用的证据。")
        for c in claims:
            lines.append(
                f"- 关系 {c['relation_id']}（文献 {c.get('lit_id')}，status={c.get('status')}，"
                f"quote_verified={c.get('quote_verified')}）逐字引用：「{_digest(c.get('quote'), 120)}」"
                f"；关系描述：「{_digest(c.get('description'), 120)}」"
            )
        # 置信度的因果必须写出来，否则"低"看起来像敷衍
        why = (
            f"命中关键词 {hits.get('distinct_hit_keywords')}/{hits.get('keyword_count')}，"
            f"相关概念度数上限 {verdict.get('degree')}，"
            f"quote_verified=True 的关系 {verdict.get('verified_count')} 条，"
            f"矛盾对 {len(verdict.get('contradictions') or [])} 对"
        )
        analysis = "\n".join(lines) + f"\n\n证据量：{why}。"
        if verdict.get("criteria"):
            analysis += "\n触发的可核实判据：" + "；".join(f"{c['id']}（{c['detail']}）" for c in verdict["criteria"])

        if conf == "low":
            conclusion = (
                "**置信度：低** —— 现有证据不足以支持任何实质性结论；本节的措辞刻意停在"
                "「可能存在/尚未证实」，不作为可引用的判断。"
            )
        elif conf == "medium":
            conclusion = "**置信度：中** —— 证据方向一致但样本有限（且部分引文未通过校验），结论应视为待复核的假设。"
        else:
            conclusion = "**置信度：高** —— 有多条通过引文校验的关系互相支撑，结论可进入后续论证。"
        if verdict.get("contradictions"):
            conclusion += " 注意：现有表述之间存在矛盾，分歧本身即研究价值所在。"

        suggestions: list[str] = []
        if not claims:
            suggestions.append("先补齐最基本的表述：向 A 提交针对性查询（本轮已按判据提交，见「缺口」一节）。")
        if not any(c.get("quote_verified") is True for c in claims):
            suggestions.append("逐条复核引文：当前没有一条关系的 quote 通过校验，无法判断表述是否忠于原文。")
        if verdict.get("contradictions"):
            suggestions.append("围绕矛盾双方各自下钻到文献正文（L3），确认分歧是实质性的还是措辞差异。")
        if verdict.get("degree", 0) < self.degree_threshold:
            suggestions.append("该方向度数偏低，建议扩大检索面（mode=broad）以确认「冷门」是否为真实空白。")
        if not suggestions:
            suggestions.append("证据已初步成形，建议进入下一层验证（构造反例 / 与其它链条交叉核对）。")
        return analysis, conclusion, suggestions, False
    def _summon_task_id(self) -> str:
        """这一趟召唤的号：显式配置 > 执行上下文（装配层挂点）> 实例属性 > 空串。

        为什么不只读实例属性：`resolve(role)` 按角色缓存实例，并发召唤共享同一个对象
        ⇒ 实例属性会被别人覆盖（`conductor.py:247-249` 已把这条理由写给取消令牌，
        `R1-A1-a` 之后号也走同一支 ContextVar）。所以每次都现算，
        并把"最终拿到什么号"如实留在读数里（空串 = 没号）。

        第三档（实例属性 `self.llm_task_id`）保留：它是单线程夹具专用的落点
        （离线测试与手工构造直接 `d.llm_task_id = "t-0001"`）；并发召唤里用它等于串味
        —— 生产路径由 ContextVar 那一档答，谁都不许把它当并发下的台账号来源。
        """
        for cand in (self.cfg.get("llm_task_id"), current_summon_task_id(),
                     getattr(self, "llm_task_id", "")):
            if str(cand or "").strip():
                return str(cand).strip()
        return ""

    def _llm_refine(self, ev: dict, verdict: dict) -> tuple[dict | None, dict]:
        """LLM 钩子：把证据包写成更通顺的分析。返回 `(payload, reading)`。
        硬规则（写在提示词里、也在代码里强制）：- 只能引用证据包中出现过的 ``relation_id`` / ``quote``，不得引入新事实（:func:
        `invented_facts` 现算，发现新事实就整份丢弃这次精修）；- 置信度只能等于或低于确定性算出的那一档（``_rank_min``）——这条在代码里兜底，不依赖
        模型守规矩。
        ## 模型对象只认两类，判据只有一处（`R1-A1`）
        走 :func:`model_json_call`（`agent_d/_support.py`）：标准缝用它的真 API`ask_json`，裸 client 走 
        `.complete`，两条路共用同一个 JSON 解析口径与同一个三态读数。这里不再有 `hasattr(llm, "complete")` 那种猜法 ——改前那一行是 
        `self.llm.complete(prompt) if hasattr(...) else self.llm(prompt)`，而 `LlmSeam` 既没有 
        `complete` 也不可调用 ⇒ 拿到标准缝必然抛`TypeError: 'LlmSeam' object is not callable`（读数：
        `temp/_r1a1_status_probe.py`）。
        """
        prompt = json.dumps(
            {
                "task": "基于给定的证据包写一段初步分析。只能引用给出的 relation_id 与 quote，不得引入外部事实。",
                "question": ev.get("question"),
                "evidence": [
                    {
                        "relation_id": c["relation_id"],
                        "quote": c.get("quote"),
                        "description": c.get("description"),
                        "lit_id": c.get("lit_id"),
                        "quote_verified": c.get("quote_verified"),
                        "status": c.get("status"),
                    }
                    for c in ev.get("claims") or []
                ],
                "criteria": verdict.get("criteria"),
                "max_confidence": verdict.get("confidence"),
                "output_format": {
                    "analysis": "字符串",
                    "conclusion": "字符串",
                    "suggestions": ["字符串"],
                    "confidence": "high|medium|low",
                },
            },
            ensure_ascii=False,default=str)
        payload, text, reading = model_json_call(self.llm, prompt, task_id=self._summon_task_id(),
                                                 note="D.research 的初步分析")
        reading["task_id"] = self._summon_task_id()
        # 花销读数（召唤级）：号在 ⇒ 用 `usd_reading(号)` 答"这一趟花了多少"；
        # 号不在 ⇒ `attached=False`（"没挂点"，不是 0 花销）；
        # 同一个召唤内多次调用 ⇒ 成本挂在当次召唤上，`calls` 说清"内几次调用"。
        reading["spend"] = spend_reading(self.store, reading["task_id"])
        text = text.strip()
        if payload is None:
            if not text or reading.get("kind") != KIND_CLIENT:
                # 两条早退，理由不同，都要 by reading 说清：
                # - 空回复 / 调用失败：这一档由 reading 说明是哪一种（不折成"没接线"）；
                # - 缝回了坏 JSON（`judge_bad_json`）：缝自己的词表把这一档算失败，
                #   于是回退到确定性那一档（`llm_used=False`）——
                #   只有裸 client 才走下面那条"把原文当分析文字用"的旧路
                #   （它没有 `problem` 词表，历史上就是这么处理的）。
                return None, reading
            # 裸 client：解析不出来（回了散文）就当作"分析文字"用，
            # 但结论与置信度仍走确定性路径 —— 宁可少用一点 LLM 的产出，
            # 也不让无法解析的东西进报告。
            base = self._deterministic_compose(ev, verdict)
            return {
                "analysis": text,
                "conclusion": base[1],
                "suggestions": base[2],
                "confidence": verdict.get("confidence"),
            }, reading
        invented = invented_facts(
            "\n".join([str(payload.get("analysis") or ""), str(payload.get("conclusion") or "")]),
            known_relation_ids=[str(c.get("relation_id") or "") for c in ev.get("claims") or []],
            known_lit_ids=[str(c.get("lit_id") or "") for c in ev.get("claims") or []
                           if c.get("lit_id")],
            known_quotes=[str(c.get("quote") or "") for c in ev.get("claims") or []],
        )
        if invented:
            # 引入新事实 = 整份丢弃（降级到确定性那一档），并把"引了什么"如实留在读数里。
            self.last_tool_errors.append(
                {"tool": "llm", "error": f"LLM 引入了证据包里没有的引用，已丢弃本次精修：{invented}"}
            )
            reading["state"] = STATE_FAILED
            reading["reason"] = f"llm_invented_facts: {invented}"
            return None, reading
        forced = _rank_min(str(payload.get("confidence") or "low"), verdict.get("confidence") or "low")
        reading["confidence_clamped"] = bool(forced != payload.get("confidence"))
        if forced != payload.get("confidence"):
            self.last_tool_errors.append(
                {
                    "tool": "llm",
                    "error": f"LLM 试图把置信度从 {verdict.get('confidence')} 拔高到 {payload.get('confidence')}，已强制降回 {forced}",
                }
            )
        payload["confidence"] = forced
        payload.setdefault("analysis", "")
        payload.setdefault("conclusion", "")
        sugg = payload.get("suggestions") or []
        payload["suggestions"] = [str(s) for s in sugg] if isinstance(sugg, list) else [str(sugg)]
        return payload, reading
    @staticmethod
    def _parse_json_block(text: str) -> dict | None:
        """取文本里第一个 JSON 对象（实现只有一份：`_support._json_object`）。"""
        return _json_object(text)
    def _render_claims(self, claims: Sequence[Mapping[str, Any]], *, marker: str = "",
                       numbered: bool = False) -> list[str]:
        """把一组 L1 表述渲染成报告行。

        ``numbered=True`` 用于链条自身的步子：带上跳序（1./2./3.）并写出
        "概念A → 概念B"，让人能顺着读；``numbered=False`` 用于上下文，只给代号
        与出处，避免抢走链条的注意力。

        每条都带代号 + 逐字引文 + 文献与页码：这三个是一组，缺任何一个，
        "按代号溯源到相关表述"就不完整（代号是索引，引文是证据，出处是可核对性）。
        """
        out: list[str] = []
        for i, c in enumerate(claims, 1):
            pr = c.get("page_range") or {}
            pr_label = pr.get("label") or (f"pp.{pr.get('start')}-{pr.get('end')}" if pr.get("start") else "页码未知")
            names = [str(n) for n in (c.get("concept_names") or []) if n]
            if not names:
                names = [self._concept_name(str(x)) for x in (c.get("concept_ids") or [])]
            # 链条自身的步子优先用 C 给的方向（见 AgentD._chain_concept_path）：
            # 一条关系的 concept_ids 是升序的，"素理想 → 环同态"会把方向写反。
            if numbered and c.get("hop_from") and c.get("hop_to"):
                arrow = f"{c['hop_from']} → {c['hop_to']}"
            else:
                arrow = " → ".join(names) if names else "(概念名未知)"
            prefix = f"{i}. " if numbered else "- "
            head = (
                f"{prefix}`R{c['relation_id']}` {arrow}（status={c.get('status')}，"
                f"quote_verified={c.get('quote_verified')}）{marker}："
            )
            out.append(head)
            desc = str(c.get("description") or "").strip()
            if desc:
                out.append(f"   {_digest(desc, 220)}")
            out.append(f"   引文 > {_digest(c.get('quote'), 300) or '（无引文）'}")
            out.append(f"   ← 文献 `{c.get('lit_id')}`，{pr_label}")
        return out
    def _trace_mode_of(self, analyses: dict) -> str:
        for res in analyses.values():
            if (res.get("trace_mode") or "external") != "external":
                return "fallback"
        return "external"
    def _origin_note(self, qrow: Mapping[str, Any]) -> str:
        """把 origin 里的报告号还原成 C 的报告摘要（引用 C 的证据）。"""
        origin = str(qrow.get("origin") or "")
        m = re.search(rf"C:(\w+):({S.ID_OR_LEGACY_PATTERN})", origin)
        if not m:
            return f"来源 `{origin}`（无法解析出报告号）"
        kind, rid = m.group(1), m.group(2)
        rep = next((x for x in self.store.rows("analysis_reports") if str(x.get("report_id")) == rid), None)
        if rep is None:
            return f"C 报告 `{rid}`（kind={kind}）未在 analysis_reports 中登记（报告文件可能已被移走）"
        return (
            f"C 报告 `{rid}`（kind={rep.get('kind')}，需求原文：{_digest(rep.get('request'), 80)}）的摘要："
            f"{_digest(rep.get('summary'), 300)}"
        )


class AgentD(_ProbeC, _Ingest, _IngestDetailed, _TraceQuestion, _TraceL3, _Assess, _SubmitGaps, _Consider,
             _ProposeQuestion, _Poll, _Adjudicate, _Research, _RunRound, _WriteReport, _RegisterConjecture, _Core):
    """研究智能体。§4.1 的状态机在这里被实现成一组可单独调用的方法。

    每个方法都可以被独立调用与单测（``ingest`` / ``trace_question`` /
    ``assess`` / ``submit_gaps`` / ``poll`` / ``research`` / ``write_report``），
    ``run_round`` 只是把它们按状态机串起来。这样"流程可中断、可续跑"才有可能：
    中断之后可以从任意一步接着跑，而不是只能从头再跑一遍。
    """



def _selftest() -> int:
    # 运行方式：在 src/ 下执行 `python -m agentflow.agent_d`（或设 PYTHONPATH=src 后在任意目录执行）
    #
    # 自检刻意不依赖 trace_tools.py / graph_tools.py / agent_c.py：
    # 造 3~4 个概念、4~5 条关系、一个假的 C 报告对象，走完
    # ingest → trace_question → assess → submit_gaps → poll → research → write_report。
    # trace_tools 缺失时用的是 install_d_tools 注册的内置最小替身（见本文件
    # 的同名函数），自检输出里会写明实际用的是哪一种。
    import sys
    import tempfile

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 —— 理由：控制台不支持重配置（被重定向 / 非交互）时，
        # 唯一后果是中文输出乱码；而"因为控制台编码问题自检根本没跑成"是更坏的结局
        # （那会把一次真实的判定失败伪装成"没输出"）。自检的目的是报告判定结果，不是设编码。
        pass

    print("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="agentflow-agentd-"))
    st = Store(root)
    st.init()
    print(f"[0] 临时 store：{root}")

    # ---- 造数据：4 个概念、5 条关系、2 篇文献
    concepts = [
        ("0000", "阿贝尔群", "满足交换律的群"),
        ("0001", "非交换环", "乘法不满足交换律的环"),
        ("0002", "域", "每个非零元可逆的交换环"),
        ("0003", "交换性条件", "使得运算可交换的附加条件"),
    ]
    relations = [
        # rid, concept_ids, quote, verified, status, lit
        ("0000", ["0000", "0002"], "An abelian group is a group in which the commutative law holds.", True, "active", "0000"),
        ("0001", ["0000", "0003"], "The commutativity condition can be relaxed for finite rings.", True, "active", "0000"),
        ("0002", ["0001", "0003"], "交换性条件不能推广到非交换环。", None, "suspect", "0001"),
        ("0003", ["0001", "0003"], "交换性条件可以推广到非交换环。", None, "suspect", "0001"),
        ("0004", ["0000", "0001"], "Abelian groups are never non-commutative rings.", False, "suspect", "0001"),
    ]
    with st.tx(*_CR.tables_for_concept_write("relations", "literature", "analysis_reports"),
               actor="seed", note="fixture") as tx:
        for cid, name, definition in concepts:
            _CR.upsert_legacy_shaped(
                tx,
                S.Concept(concept_id=cid, name=name, definition=definition,
                          normalized_name=name, created_at=S.now_iso(), updated_at=S.now_iso()).to_dict(),
                note="seed",
            )
        for rid, cids, quote, ver, status, lid in relations:
            row = S.Relation(
                relation_id=rid,
                concept_ids=sorted(cids),
                description=quote,
                lit_id=lid,
                page_range=S.PageRange(12, 13, "pp. 12–13"),
                quote=quote,
                # 让"矛盾"这一条在真实数据里也成立：关系 0002/0003 谈同一对概念
                # （0001,0003）却给出相反表述 —— 这正是 §4.4 判据 3 要发现的。
                # 注意：0002 带否定、0003 不带，故 detect_contradictions 判定为矛盾。
                statement=quote,
                concept_group_key="|".join(sorted(cids)),
                dedup_key=f"k{rid}",
                status=status,
                quote_verified=ver,
                created_at=S.now_iso(),
            )
            row.validate()
            tx.upsert("relations", row.to_dict(), note="seed")
        for lid, title in (("0000", "Commutativity in algebra"), ("0001", "Non-commutative ring theory")):
            tx.upsert(
                "literature",
                S.Literature(lit_id=lid, title=title, type="J", summary="s", path=None,
                             processed=True, added_at=S.now_iso()).to_dict(),
                note="seed",
            )
        # 一行 C 报告登记（供 write_report 的"引用 C 的证据"使用）
        tx.upsert(
            "analysis_reports",
            S.AnalysisReport(
                report_id="0000",
                kind="paths",
                request="查询 阿贝尔群 与 域 之间的关系",
                summary="找到 2 条高信息量路径，1 条的引文通过校验，另 1 条存在互相矛盾的表述。",
                payload={"paths": []},
                markdown_path="reports/0000-paths.md",
                created_at=S.now_iso(),
            ).to_dict(),
            note="seed",
        )
    print(f"[1] 造数据：概念 {len(concepts)} 个，关系 {len(relations)} 条，文献 2 篇")

    # ---- 假的 C 报告对象（字段名与契约一致：kind/request/params/summary/payload/markdown/warnings/truncated/persist）
    class FakeCReport:
        def __init__(self) -> None:
            self.kind = "paths"
            self.request = "查询 阿贝尔群 与 域 之间的关系"
            self.params = {"a": "0000", "b": "0002"}
            self.summary = "找到 1 条高信息量路径（0000->0002）"
            # 假设的 payload 形状（与 agent_c 当前实现一致，见 _candidates_from 的 docstring）
            self.payload = {
                "paths": [
                    {
                        "concept_path": ["0000", "0002"],
                        "concept_names": ["阿贝尔群", "域"],
                        "relation_chain": ["0000"],
                        "hops": 1,
                        "level": "high",
                        "score": 3.4,
                        "score_breakdown": {"quote_verified": 2.0, "hops": 1.2, "diversity": 0.2},
                    },
                    {
                        # 这一条会落到"互相矛盾"的判据上：0001<->0003 的两条关系
                        "concept_path": ["0001", "0003"],
                        "concept_names": ["非交换环", "交换性条件"],
                        "relation_chain": ["0002", "0003"],
                        "hops": 2,
                        "level": "high",
                        "score": 2.1,
                        "score_breakdown": {"quote_verified": 0.0, "hops": 1.2, "diversity": 0.9},
                    },
                ]
            }
            self.markdown = "# fake"
            self.warnings = ["fake warn"]
            self.truncated = False

        def persist(self) -> dict:
            return {"report_id": "0000"}

    reg = install_d_tools(st)
    trace_external = load_trace_tools() is not None
    print(f"[2] 工具栏：{reg.names()}")
    print(f"    trace_tools 外部模块存在？{trace_external}（False 时用的是内置降级替身）")

    d = AgentD(st, config={"max_questions": 5, "degree_threshold": 2}, actor="agent-D", tools=reg, llm=None)

    print("[3] ingest：从假 C 报告提取候选问题")
    new_ids = d.ingest(FakeCReport())
    print(f"    新建 {len(new_ids)} 个问题：{new_ids}")
    for c in d.last_ingest["candidates"]:
        print(f"    候选：origin={c['origin']} kind={c['kind']} priority={c['priority']}")
    for s in d.last_ingest["skipped"]:
        print(f"    跳过：{s}")
    print(f"    重复 ingest（幂等性）：{d.ingest(FakeCReport())}（应为 []，origin 去重）")

    for qid in new_ids:
        print(f"[4] trace_question({qid})：L1 claims / trace_mode")
        ev = d.trace_question(qid)
        print(f"    claims={len(ev['claims'])} l2={len(ev['l2'])} trace_mode={ev['trace_mode']}")
        for c in ev["claims"][:3]:
            print(f"      R{c['relation_id']} verified={c['quote_verified']} quote={_digest(c['quote'], 60)!r}")

        print(f"[5] assess({qid})：可核实判据")
        v = d.assess(qid, ev)
        print(f"    sufficient={v['sufficient']} criteria={[c['id'] for c in v['criteria']]} "
              f"priority={v['priority']} confidence={v['confidence']} degree={v['degree']} "
              f"命中关键词={v['hits']['distinct_hit_keywords']}/{v['hits']['keyword_count']} "
              f"矛盾对={len(v['contradictions'])}")
        for c in v["criteria"]:
            print(f"      判据 {c['id']}: {_digest(c['detail'], 140)}")

        print(f"[6] submit_gaps({qid})")
        before = len(st.rows("search_requests"))
        rids = d.submit_gaps(qid)
        after = len(st.rows("search_requests"))
        print(f"    新提交请求={rids}（请求表 {before} -> {after}）")
        print(f"    再提交一次（查重）：{d.submit_gaps(qid)}  "
              f"skip={getattr(d, 'last_submit_skip', {}).get('reason')}")
        assert len(st.rows("search_requests")) == after, "查重失败：重复提交了查询请求"

    print("[7] poll：A/B 都还没跑")
    print(f"    {json.dumps(d.poll(), ensure_ascii=False, default=str)}")

    print("[8] 模拟 A 跑完 + B 消化，再次 poll")
    open_reqs = [r for r in st.rows("search_requests") if not r.get("done")]
    with st.tx("search_requests", "literature", actor="sim", note="simulate") as tx:
        for i, req in enumerate(open_reqs):
            lid = S.format_id(10 + i)
            tx.upsert(
                "literature",
                S.Literature(lit_id=lid, title=f"simulated paper {i}", type="J", summary="s", path=None,
                             processed=False, added_at=S.now_iso()).to_dict(),
                note="sim",
            )
            req["done"] = True
            req["outcome"] = "ok"
            req["result_lit_ids"] = [lid]
            S.row_from_dict("search_requests", req).validate()
            tx.upsert("search_requests", req, note="sim_A")
    half = d.poll()
    print(f"    A 完成、B 未消化：ready={half['ready']} waiting={half['waiting']} "
          f"原因={list(half['reasons'].values())[:1]}")
    with st.tx("literature", actor="sim", note="simulate") as tx:
        for r in tx.rows("literature"):
            r["processed"] = True
            tx.upsert("literature", r, note="sim_B")
    full = d.poll()
    print(f"    A+B 都完成：ready={full['ready']} promoted={full['promoted']} merged={full['merged_relations']}")

    print("[9] research：对 researching 的问题做初步研究")
    for qid in full["promoted"] or new_ids:
        res = d.research(qid)
        print(f"    {qid} 置信度={res['confidence']} 判据={res['criteria']} llm_used={res['llm_used']} "
              f"结论={_digest(res['conclusion'], 90)}")
        print(f"      分析：{_digest(res['analysis'], 160)}")
        print(f"      建议：{res['suggestions']}")

    print("[10] LLM 不许拔高置信度：用一个「想拔高」的假 LLM 验证")
    ev = d.trace_question(new_ids[0])
    base = d.assess(new_ids[0], ev)["confidence"]

    class FakeLLM:
        def complete(self, prompt: str) -> str:
            return json.dumps(
                {"analysis": "（LLM 写的分析）", "conclusion": "（LLM 写的结论）",
                 "suggestions": ["（LLM 建议）"], "confidence": "high"},
                ensure_ascii=False,default=str)

    d2 = AgentD(st, config={"max_questions": 5}, actor="agent-D", tools=reg, llm=FakeLLM())
    d2.trace_question(new_ids[0])
    # `R1-A1`：`_llm_refine` 现在返回 `(payload, reading)`（三态读数与产出一起回去）
    got, _reading = d2._llm_refine(d2.trace_question(new_ids[0]), d2.assess(new_ids[0]))
    print(f"    确定性置信度={base}；LLM 声称=high；强制后={got['confidence']}"
          f"；读数={_reading.get('state')}")
    assert _rank(got["confidence"]) <= _rank(base), "置信度被拔高了！"
    assert _reading.get("confidence_clamped") is True, "读数要如实记下'夹过'"

    print("[11] write_report")
    out = d.write_report()
    text = Path(out).read_text(encoding="utf-8")
    print(f"    写出：{out}")
    print(f"    字数：{len(text)}；行数：{text.count(chr(10))}")
    print(f"    含「置信度」小节：{'结论置信度' in text}；含代号溯源：{'origin=' in text}")

    print("[12] run_round：再来一份 gaps 报告，走完整一轮")
    class FakeGapsReport:
        kind = "gaps"
        request = "完善关系图"
        params = {"limit": 10}
        summary = "发现 1 个候选结构洞"
        payload = {
            "verdict": "有",
            "has_candidates": True,
            "candidate_gaps": [
                {"concept_ids": ["0002", "0003"], "concept_names": ["域", "交换性条件"],
                 "related_relation_ids": [], "common_neighbors": [{"concept_id": "0001", "name": "非交换环"}],
                 "reason": "有共同邻居 0001 但彼此无直接关系", "positive_signals": ["结构洞", "两概念均在热门集"],
                 "confidence": "medium"}
            ],
        }
        markdown = "# fake gaps"
        warnings: list = []
        truncated = False

    rr = d.run_round(FakeGapsReport())
    print(f"    ingested={rr['ingested']} assessed={[a['criteria'] for a in rr['assessed']]} "
          f"submitted={rr['submitted']}")
    print(f"    poll.ready={rr['poll']['ready']} researched={[(x['question_id'], x['confidence']) for x in rr['researched']]}")
    print(f"[13] 最终状态：{[ (r['question_id'], r['status'], r['priority']) for r in st.rows('research_questions') ]}")

    print("=" * 72)
    print("SELF-CHECK DONE（agent_d）")
    return 0
