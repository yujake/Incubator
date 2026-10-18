"""角色 D 的动作 `write_report`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import CONFIDENCE_LABELS, C_NO_EVIDENCE, Mapping, Path, S, _conf_label, _digest, json

class _WriteReport:
    def write_report(self, out_path: str | Path | None = None) -> str:
        """汇总成较详细的初步研究报告（结构照 §4.5），返回写出的路径。

        每个问题一节：``问题 → 为什么值得研究（引用 C 的证据）→ 现有证据
        （L1/L2 的逐字引用 + 代号链）→ 缺口与已提交的查询 → 初步分析 →
        结论与置信度 → 后续建议``。

        报告末尾额外给一节审计信息（每条判据的中间值、用了真身还是降级替身、
        工具错误），因为"结论可复核"是本系统的核心诉求 —— 一份说不出自己
        依据的报告，读者只能选择全信或全不信。

        ## `out_path` 相对谁解析（`draft/37` §118：T2 第 1 趟的真机读数）

        缺省落点是 `<工作区>/<reports_subdir>/<qid>-research.md`（`reports_subdir`
        来自配置，缺省 `reports`）。传进来的「相对」 `out_path` 一律按「工作区根」
        解析 —— 原先是 `Path(out_path)` 直接写，于是按进程当前目录解析：

        ```text
        T2 第 1 趟：主控传 out_path="out\\review\\D-analysis.md"（工作区内的合法落点）
        ⇒ 文件写到 agentflow/out/review/D-analysis.md（工作区根相对；进程 cwd）
        ⇒ 交付物静默离开工作区，而台账记的是 outcome=ok、报告里写着"执行完成"
        ```

        规则与工具层的写盘同一个实现（`doc_tools.resolve_out_path`）：
        越界（绝对路径跳出去、`..`）一律拒 —— 工作区边界是沙箱契约，不是建议。
        返回值是「绝对」路径（与传绝对路径时的旧行为一致，`pipeline._rel_to_root`
        等调用方照旧能用）。
        """
        rows = sorted(self.store.rows("research_questions"), key=lambda r: str(r.get("question_id")))
        analyses = getattr(self, "last_research", {}) or {}
        run_id = rows[-1]["question_id"] if rows else "0000"
        from ..tools.doc_tools import resolve_out_path

        _rel, path = resolve_out_path(Path(self.store.root).resolve(), out_path,
                                      f"{run_id}-research", self.reports_subdir)
        path.parent.mkdir(parents=True, exist_ok=True)

        conf_count = {"high": 0, "medium": 0, "low": 0}
        for qid, res in analyses.items():
            conf_count[res.get("confidence", "low")] = conf_count.get(res.get("confidence", "low"), 0) + 1

        lines: list[str] = []
        lines.append("# D 初步研究报告")
        lines.append("")
        lines.append(f"- 生成时间：{self._stamp()}")
        lines.append(f"- 智能体：`{self.actor}`；问题总数：{len(rows)}")
        conf_desc = "，".join(
            f"{CONFIDENCE_LABELS.get(k, k)}={v}" for k, v in conf_count.items() if v
        ) or "（本轮尚未形成任何结论）"
        lines.append(
            f"- 置信度分布：{conf_desc}（**低就是低，不因篇幅或措辞调整**；括号内为受控词表取值）"
        )
        lines.append(f"- 溯源模式：{'外部 trace_tools' if self._trace_mode_of(analyses) == 'external' else '内置降级替身'}")
        lines.append("")
        lines.append("## 0. 阅读须知")
        lines.append("")
        lines.append("1. 每条问题都带**代号溯源**（`origin` + 概念/关系代号）：任何一句结论都能回到")
        lines.append("   关系表里对应的 `quote` 去核对，这是「完全引用参考文献」要求的延续。")
        lines.append("2. 置信度由**可核实的证据量**算出（通过引文校验的条数、度数、矛盾对数），")
        lines.append("   LLM 只能调低、不能调高。")
        lines.append("3. 「知识不足」由三条可核实判据触发（关键词零命中 / 度数低且无可核验引文 / 表述互相矛盾），")
        lines.append("   不使用「感觉不够」这类无法反驳的判据。")
        lines.append("4. 每个问题都列出**对 C 的按需查询**（I1）：查了就写拿到什么，没查到就写"
                     f"{C_NO_EVIDENCE}，并且那一节的结论不作确定语气。")
        lines.append("5. 矛盾驱动的问题（I2）走**裁决闭环**：追问有轮数上限与全局配额，"
                     "用尽即标 `persistent`（交人复核），不会无限追问。")
        lines.append("")

        # ---- 状态统计
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
        lines.append("## 1. 问题台账总览")
        lines.append("")
        lines.append("| 状态 | 数量 |")
        lines.append("|---|---|")
        for k in S.QUESTION_STATUSES:
            if by_status.get(k):
                lines.append(f"| {k} | {by_status[k]} |")
        lines.append("")
        lines.append("| 问题 | 类型 | 优先级 | 状态 | 来源（代号溯源） | 等待中的请求 |")
        lines.append("|---|---|---|---|---|---|")
        for r in rows:
            kind = str(r.get("kind") or "gap")
            if kind == "contradiction":
                kind = f"contradiction({r.get('contradiction_verdict') or '待裁决'}, {r.get('contradiction_rounds') or 0} 轮)"
            lines.append(
                f"| {r.get('question_id')} | {kind} | {r.get('priority')} | {r.get('status')} | "
                f"`{_digest(r.get('origin'), 60)}` | {', '.join(r.get('waiting_request_ids') or []) or '-'} |"
            )
        lines.append("")

        # ---- 逐问题
        lines.append("## 2. 逐个问题")
        lines.append("")
        for r in rows:
            qid = str(r.get("question_id"))
            res = analyses.get(qid)
            conf = (res or {}).get("confidence", "low")
            lines.append(f"### {qid}. {r.get('question')}")
            lines.append("")
            lines.append(f"- **优先级**：{r.get('priority')}；**状态**：{r.get('status')}")
            lines.append(f"- **结论置信度**：**{_conf_label(conf)}**")
            lines.append(f"- **代号溯源**：`origin={r.get('origin')}`；")
            lines.append(
                f"  相关概念 `{', '.join(r.get('related_concept_ids') or []) or '-'}`；"
                f"相关关系 `{', '.join(r.get('related_relation_ids') or []) or '-'}`"
            )
            if str(r.get("kind") or "gap") == "contradiction":
                lines.append(
                    f"- **矛盾对（I2）**：{' vs '.join(r.get('contradiction_relation_ids') or [])}；"
                    f"裁决={r.get('contradiction_verdict') or '尚未裁决'}；追问轮数={r.get('contradiction_rounds') or 0}"
                    f"（上限 {self.max_rounds_per_contradiction}）；"
                    f"矛盾驱动请求={', '.join(r.get('contradiction_request_ids') or []) or '-'}"
                )
            lines.append("")

            lines.append("**为什么值得研究（引用 C 的证据）**")
            lines.append("")
            origin_note = self._origin_note(r)
            lines.append(f"- C 的证据：{origin_note}")
            lines.append("")

            lines.append("**现有证据（L1/L2 逐字引用 + 代号链）**")
            lines.append("")
            ev = (res or {}).get("evidence")
            # "没做"与"做了但没结果"必须分开写（本文件里反复出现的同一条原则）。
            # 早先这里把两种情况统一写成"未能取到任何关系表述（L1/L2 均为空）——这本身
            # 就是一个重要事实"，于是在"问题还没进入研究步骤"时，报告会断言一个
            # 从未做过的查询没有结果 —— 那是在报告里造假。
            # 现在：没有研究记录 ⇒ 就地补一次溯源（只读，不改任何状态），并如实标注
            # 这次证据是"本轮未研究、报告期补取"的；溯源真的返回空 ⇒ 才说 L1/L2 为空。
            traced_now = False
            if not ev:
                try:
                    ev = self.trace_question(qid)
                    traced_now = True
                except Exception as e:
                    self.last_tool_errors.append({"tool": "trace_question", "error": f"{type(e).__name__}: {e}"})
                    ev = None
            if ev is None:
                lines.append(
                    "- **溯源未执行**（`trace_question` 调用失败）：本节没有证据，"
                    f"但这不等于「查询过且没有结果」。失败原因见审计一节。"
                )
                claims = []
            else:
                claims = ev.get("claims") or []
                if traced_now and not claims:
                    lines.append(
                        f"- 本问题本轮**未进入研究步骤**（状态 {r.get('status')}）；"
                        f"此处证据为报告期补取的溯源结果：trace_mode={ev.get('trace_mode')}，L1/L2 均为空。"
                    )
                elif not claims:
                    lines.append(
                        f"- 溯源已执行（trace_mode={ev.get('trace_mode')}），但 L1/L2 **确实没有取到任何关系表述**"
                        "——这本身就是一个重要事实。"
                    )
            marker = "（报告期补取）" if traced_now else ""
            claims = list(claims)
            chain_ids = [str(x) for x in ((ev or {}).get("chain_ids") or [])]
            by_rid = {str(c["relation_id"]): c for c in claims}
            # ---- 分段：链条自身的步子（L1）vs 相关概念带来的上下文（L2）
            # 这个划分不是美化排版，而是"按代号溯源"的可读性前提：读者要能顺着链读。
            chain_claims = [by_rid[r] for r in chain_ids if r in by_rid]
            context_claims = [c for c in claims if str(c["relation_id"]) not in set(chain_ids)]

            if chain_claims:
                lines.append("")
                lines.append("**链条自身的表述（L1，按跳序）**")
                lines.append("")
                lines.extend(self._render_claims(chain_claims, marker=marker, numbered=True))
            if context_claims:
                lines.append("")
                lines.append("**相关概念的其它表述（L2，上下文，未参与本链）**")
                lines.append("")
                shown = context_claims[: self.max_l2_context]
                lines.extend(self._render_claims(shown, marker=marker, numbered=False))
                rest = len(context_claims) - len(shown)
                if rest > 0:
                    lines.append(
                        f"- …另有 **{rest}** 条上下文未展开（共 {len(context_claims)} 条）。"
                        "它们是相关概念的邻居表述，用于判断证据广度；要逐条看可用 `trace.concept`。"
                    )
            if not chain_claims and not context_claims and claims:
                # 只有链条代号却没有对应关系（链条断裂）时的兜底
                lines.extend(self._render_claims(claims, marker=marker, numbered=False))

            l2 = (ev or {}).get("l2") or []
            if l2:
                lines.append("")
                lines.append("**相关概念的定义与度数（L2）**")
                lines.append("")
            for c in l2:
                lines.append(
                    f"- `C{c['concept_id']}`「{c.get('name') or '（概念名未知）'}」定义："
                    f"{_digest(c.get('definition'), 160) or '（无定义）'}；度数 {c.get('degree')}"
                )
            for pc in (ev or {}).get("path_chains") or []:
                lines.append("")
                lines.append(f"- 关系链 `{'->'.join(pc.get('relation_ids') or [])}` 的逐步表述（`trace.chain`）：")
                lines.append("")
                lines.append("```text")
                lines.append(str(pc.get("chain_text") or "")[:2000])
                lines.append("```")
                if pc.get("missing"):
                    lines.append(f"  ⚠️ 链条断裂：关系表里找不到 {pc['missing']}")
            for t in (ev or {}).get("l3") or []:
                lines.append(
                    f"- L3 下钻 `L{t.get('lit_id')}`《{_digest(t.get('title'), 80)}》："
                    f"文件存在={t.get('file_exists')}，"
                    # 外部 trace_tools 用 has_text_layer，降级替身用 text_available；
                    # 两者都认，缺失时如实写 None 而不是假装 False。
                    f"正文可得={t.get('has_text_layer', t.get('text_available'))}，"
                    f"download_status={t.get('download_status', t.get('status'))}"
                )
            lines.append("")

            # ---- I1：C 侧按需查询（点菜记录）。这一节的存在本身就是设计：
            # "无 C 侧证据"必须是一句写在报告里的话，而不是读者自己发现的空缺。
            lines.append("**C 侧按需查询（I1）**")
            lines.append("")
            cq = [q for q in ((ev or {}).get("c_queries") or []) if isinstance(q, Mapping)]
            if not cq:
                lines.append(
                    "- 本轮**未对 C 发起按需查询**（该问题未进入研究/评估步骤，`evidence.c_queries` 为空）"
                    f"⇒ 本节{C_NO_EVIDENCE}：下面的判断未经 C 的图查询核对。"
                )
            else:
                csum = self._c_summary(cq)
                if not csum["any_success"]:
                    lines.append(
                        f"- **{C_NO_EVIDENCE}**：{csum['attempted']} 次 C 查询**全部没有成功**："
                    )
                    for f in csum["failures"]:
                        lines.append(f"  - `{f.get('api')}`：{_digest(f.get('reason'), 240)}")
                    lines.append(
                        "  - ⇒ 本节的结论只基于 D 侧溯源到的关系表述，**不作为确定结论**引用"
                        "（「没问到」不等于「不存在」）。"
                    )
                else:
                    lines.append(
                        f"- C 查询成功 {csum['ok']}/{csum['attempted']} 次（参数由本问题的代号现场推导）"
                    )
                for q in cq:
                    lines.append(
                        f"- `{q.get('api')}`(params={json.dumps(q.get('params') or {}, ensure_ascii=False, default=str)}) "
                        f"checked={q.get('checked')} truncated={q.get('truncated')} "
                        f"digest={json.dumps(q.get('digest'), ensure_ascii=False, default=str)}"
                        + (f"；reason={_digest(q.get('reason'), 200)}" if q.get("reason") else "")
                    )
            lines.append("")

            lines.append("**缺口与已提交的查询**")
            lines.append("")
            wait = r.get("waiting_request_ids") or []
            if wait:
                lines.append(f"- 已提交（等待中）：{', '.join(wait)}")
            req_index = {str(x.get("request_id")): x for x in self.store.rows("search_requests")}
            for rid in wait:
                req = req_index.get(rid) or {}
                lines.append(
                    f"  - `{rid}`：done={req.get('done')} outcome={req.get('outcome')} "
                    f"结果文献={req.get('result_lit_ids') or []}"
                )
            if not wait:
                lines.append("- 尚未提交查询请求（证据已足够，或受预算限制；详见审计一节）。")
            if (res or {}).get("criteria_detail"):
                lines.append("- 触发的可核实判据：")
                for c in res["criteria_detail"]:
                    lines.append(f"  - `{c['id']}`：{c['detail']}")
            lines.append("")

            lines.append("**初步分析**")
            lines.append("")
            if res and res.get("analysis"):
                lines.append(res["analysis"])
            elif res:
                lines.append("（有研究记录但分析为空，见审计一节的工具错误。）")
            else:
                lines.append(
                    "（本轮未运行到研究步骤：该问题未进入 `researching`，因此没有分析。"
                    "上一节给出的是报告期补取的溯源证据，不是研究结论。）"
                )
            lines.append("")

            lines.append("**结论与置信度**")
            lines.append("")
            if res and res.get("conclusion"):
                lines.append(res["conclusion"])
            elif res:
                lines.append(f"**置信度：{_conf_label(conf)}** —— 尚未形成结论。")
            else:
                # 没研究过就不给置信度：置信度是"对某组证据的判断"，
                # 没有判断却写一个"低"，看起来像结论，实则是一个没算过的数。
                lines.append(
                    "**本轮未形成结论**：该问题还没进入研究步骤（无 `research()` 记录），"
                    "因此不给出置信度 —— 没有可评估的证据时，任何档位都是编出来的。"
                )
            lines.append("")

            lines.append("**后续建议**")
            lines.append("")
            for s in (res or {}).get("suggestions") or ["（无）"]:
                lines.append(f"- {s}")
            lines.append("")
            if r.get("notes"):
                lines.append("<details><summary>研究笔记（原始记录）</summary>")
                lines.append("")
                lines.append("```")
                lines.append(str(r["notes"])[:4000])
                lines.append("```")
                lines.append("</details>")
                lines.append("")

        # ---- 审计
        lines.append("## 3. 审计信息（结论可复核性）")
        lines.append("")
        # 模型三态（`R1-A1`）：这一趟报告里的分析是不是模型给的、以及为什么不是
        # —— 不折成一句 `LLM=no`（那会把"没接线"与"接了但失败"混成一件事）。
        readings = [dict(res.get("llm_reading") or {})
                    for res in (getattr(self, "last_research", {}) or {}).values()]
        if readings:
            by_state: dict[str, int] = {}
            for r in readings:
                state = str(r.get("state") or "unknown")
                by_state[state] = by_state.get(state, 0) + 1
            detail = "，".join(f"{k}={v}" for k, v in sorted(by_state.items()))
            calls = sum(int(r.get("calls") or 0) for r in readings)
            lines.append(f"- 模型三态（本次报告覆盖的问题）：{detail}；"
                         f"其中这一次召唤内共 {calls} 次模型调用"
                         "（记账粒度是召唤级，见 `tokenmeter.usd_for` / `usd_reading`）")
            failed = [r for r in readings if str(r.get("state") or "") == "failed"]
            for r in failed[:10]:
                lines.append(f"  - 失败：kind={r.get('kind')} reason={_digest(r.get('reason'), 200)}")
            unlinked = sorted({str(r.get("task_id") or "") for r in readings if not r.get("task_id")})
            if unlinked:
                lines.append("  - 注意：这些调用没有带上召唤号（`task_id` 为空）⇒ "
                             "花销挂在缝的会话事件里，账本按 `task_id` 读不到这一笔")
        else:
            lines.append("- 模型三态：这一趟还没有任何 `research` 记录 ⇒ 没有可判的调用"
                         "（不是「都用了」，也不是「都没接线」）")
        lines.append("")
        lines.append("- 工具调用错误 / 降级记录：")
        errs = getattr(self, "last_tool_errors", [])
        if not errs:
            lines.append("  - 无")
        for e in errs[-30:]:
            lines.append(f"  - `{e.get('tool')}`：{_digest(e.get('error'), 200)}")
        lines.append("")
        lines.append("- 本轮 ingest 情况：")
        ing = getattr(self, "last_ingest", {}) or {}
        lines.append(f"  - 报告 `{ing.get('report_id')}`（kind={ing.get('kind')}）：候选 {len(ing.get('candidates') or [])} 个，"
                     f"新建 {len(ing.get('created') or [])} 个")
        for s in ing.get("skipped") or []:
            lines.append(f"  - 跳过：{_digest(s, 200)}")
        # ---- §3.1：等价类合并必须可区分于"新建"（"命中了所以没建" ≠ "建了"）
        eqm = ing.get("equivalent_matched") or []
        lines.append(
            f"  - §3.1 等价类：命中已有问题而**未新建** {len(eqm)} 个；内容键合并 {len(ing.get('merged') or [])} 个"
        )
        for m in eqm:
            lines.append(
                f"    - `{m.get('origin')}` ⇒ 已存在问题 `{m.get('question_id')}`（by={m.get('by')}；{_digest(m.get('detail'), 160)}）"
            )
        cing = ing.get("contradictions") or {}
        if cing:
            lines.append(
                f"  - I2 矛盾吸收：来源={cing.get('source')} checked={cing.get('checked')} "
                f"读入 {cing.get('raw_count')} 条；{_digest(cing.get('reason'), 200)}"
            )
            for s in cing.get("skipped") or []:
                lines.append(f"    - 跳过：{_digest(s, 200)}")
            weak = cing.get("weak_clues") or []
            if weak:
                lines.append(
                    f"  - I2 **弱线索（不追问）** {len(weak)} 条：`strength != strong` 的矛盾对只记录为线索，"
                    "不建矛盾问题、不向 A 提问（弱信号假阳性极高）"
                )
                noted = {tuple(x.get("relation_ids") or []): x for x in (ing.get("weak_clues_noted") or [])}
                for w in weak:
                    key = tuple(w.get("relation_ids") or [])
                    where = noted.get(key) or {}
                    lines.append(
                        f"    - 关系 {'、'.join(key)}：{_digest(w.get('signals'), 160)}"
                        f"；落痕={where.get('question_id') or '（无共享代号的问题，仅存于本报告与 last_ingest）'}"
                    )
        lines.append("")
        lines.append("- I1 C 服务接线：")
        cw = getattr(self, "c_wiring", {}) or {}
        lines.append(f"  - mode={cw.get('mode')}：{_digest(cw.get('reason'), 240)}")
        lines.append("- I2 本轮矛盾裁决：")
        adjs = getattr(self, "last_adjudications", []) or []
        if not adjs:
            lines.append("  - 本轮没有可裁决的矛盾问题（没有 kind=contradiction 的问题，或都还有在途请求）")
        for a in adjs:
            lines.append(
                f"  - `{a.get('question_id')}`：checked={a.get('checked')} action={a.get('action')} "
                f"verdict={a.get('verdict')} code={a.get('code')} rounds={a.get('rounds_before')}→{a.get('rounds_after')} "
                f"新请求={a.get('request_ids') or []} 新问题={a.get('new_question_ids') or []}；"
                f"{_digest(a.get('reason'), 200)}"
            )
        budget = self._contradiction_budget()
        lines.append(
            f"  - 全局矛盾检索配额：{budget['used']}/{budget['limit']}"
            f"（用尽后不再追问，一律标 persistent 交人复核）"
        )
        lines.append("")
        lines.append("- poll 复检：")
        pol = getattr(self, "last_poll", {}) or {}
        lines.append(f"  - 就绪 {pol.get('ready') or []}；未就绪 {pol.get('waiting') or []}；拉回 researching {pol.get('promoted') or []}")
        for h in pol.get("held") or []:
            lines.append(
                f"  - 未推进 `{h.get('question_id')}`：{h.get('why')}"
                + (f"（优先级 {h.get('priority_before')}→{h.get('priority')}）" if h.get("why") == "irrelevant" else "")
                + f"；{_digest(h.get('reason'), 200)}"
            )
        lines.append("")
        lines.append("- 每条判据的中间值（命中数 / 度数 / 校验分布）见各问题的「触发判据」一节；")
        lines.append("  完整数值由 `AgentD.last_assessment` 保留在内存中，可另行落盘。")
        lines.append("")

        text = "\n".join(lines) + "\n"
        path.write_text(text, encoding="utf-8")
        self.last_report_path = path
        return str(path)
