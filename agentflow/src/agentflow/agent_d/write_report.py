"""角色 D 的动作 `write_report`（一动作一文件；判据 `tests/test_agent_split_is_one_action_one_file.py`）。"""
from __future__ import annotations

from ._support import Any, CONFIDENCE_LABELS, C_NO_EVIDENCE, Mapping, Path, S, _conf_label, _digest, json
from .. import statementledger as SL   # 命题台账的查口（按号 / 按关键词，只读、零模型）


def _carried_key(kind: str, ident: Any) -> str:
    """携带单的去重键：`stmt:<命题号>` / `exp:<实验号>`（这一个落点是唯一的一处）。

    为什么不能拿裸号去重：`statements` 与 `experiments` 的号各自从头编（都从 000000
    起），所以 `stmt:000000` 与 `exp:000000` 同时存在是常态。同一个 `seen` 收裸号
    时，先扫到的那一类会把另一类静默挤掉 —— 而携带单少一行、B 按清单寻址不到 E 的稿，
    与"那条 e-proof 没签"在读数上完全同形（`carried_missing` 还因为单非空而不报）。
    判据：`tests/test_carried_sheet_keeps_exp_rows_with_matching_numbers.py`。
    """
    return f"{str(kind or '').strip()}:{str(ident or '').strip()}"


class _WriteReport:
    def write_report(self, out_path: str | Path | None = None) -> str:
        """汇总成较详细的初步研究报告（结构照 §4.5），返回写出的路径。
        每个问题一节：``问题 → 为什么值得研究（引用 C 的证据）→ 现有证据（L1/L2 的逐字引用 + 代号链）→ 缺口与已提交的查询 → 初步分析 →结论与置信度 → 后续建议``。
        报告末尾额外给一节审计信息（每条判据的中间值、用了真身还是降级替身、工具错误），因为"结论可复核"是本系统的核心诉求 —— 一份说不出自己依据的报告，读者只能选择全信或全不信。
        ## `out_path` 相对谁解析（`draft/37` §118：T2 第 1 趟的真机读数）
        缺省落点是 `<工作区>/<reports_subdir>/<qid>-research.md`（`reports_subdir`来自配置，缺省 `reports`）。传进来的「相对」
        `out_path` 一律按「工作区根」解析 —— 原先是 `Path(out_path)` 直接写，于是按进程当前目录解析：
        ```text
        T2 第 1 趟：主控传 out_path="out\\review\\D-analysis.md"（工作区内的合法落点）
        ⇒ 文件写到 agentflow/out/review/D-analysis.md（工作区根相对；进程 cwd）
        ⇒ 交付物静默离开工作区，而台账记的是 outcome=ok、报告里写着"执行完成"
        ```
        规则与工具层的写盘同一个实现（`doc_tools.resolve_out_path`）：越界（绝对路径跳出去、`..`）一律拒 —— 工作区边界是沙箱契约，不是建议。返回值是「绝对」
        路径（与传绝对路径时的旧行为一致，`pipeline._rel_to_root`等调用方照旧能用）。
        
        """
        rows = sorted(self.store.rows("research_questions"), key=lambda r: str(r.get("question_id")))
        analyses = getattr(self, "last_research", {}) or {}
        run_id = rows[-1]["question_id"] if rows else "0000"
        from ..tools.doc_tools import resolve_out_path

        _rel, path = resolve_out_path(Path(self.store.root).resolve(), out_path,
                                      f"{run_id}-research", self.reports_subdir)
        path.parent.mkdir(parents=True, exist_ok=True)

        conf_count = {"high": 0, "medium": 0, "low": 0}
        for res in analyses.values():
            key = res.get("confidence", "low")
            conf_count[key] = conf_count.get(key, 0) + 1

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
            status = r.get("status", "?")
            by_status[status] = by_status.get(status, 0) + 1
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
        # 请求表按报告期读一次：逐问题重建同一张索引是把全表重扫一遍（本节只读它）。
        req_index = {str(x.get("request_id")): x for x in self.store.rows("search_requests")}
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
            chain_set = set(chain_ids)
            context_claims = [c for c in claims if str(c["relation_id"]) not in chain_set]

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
        # ---- 携带给 B 的证明手稿（业主 2026-10-26：「是通过D传吗」，逐字） ----------
        #
        # 业主原话链：「依赖面登记是否是F在其手稿中写好，D的研究手稿引用F的证明手稿给B
        # 入库时，B侧读到F手稿处的依赖面，按此入库的？」→「是通过D传吗」。
        # 所以传递路径是 D→B：D 交研究手稿给 B 入库时，把 F 的证明手稿一并带上。
        # 这一节就是那份"携带单"（渲染在 `depsection.render_carried_section`，B 用
        # `depsection.read_carried_manuscript` 读同一节）：写在 D 自己渲染出来的报告里
        # 而不是靠模型记着去传 —— 模型忘一次，依赖面就静默地 0 行。
        carried_rows, carried_note = self._carried_manuscripts()
        carried_missing = self._carried_missing_reading(carried_rows)
        from .. import depsection as _DS

        lines.extend(_DS.render_carried_section(carried_rows, note=carried_note)
                     .rstrip("\n").split("\n"))
        lines.append("")
        # ---- 携带单缺口的读数（2026-10-27）：不许静默 -------------------------------
        #
        # 改前真机形态：D 手写 `reports/RESEARCH.md`（自由格式，没有携带单）⇒ B 那一侧
        # 读到的是"没有可携带的稿"，而那与"这条证明确实自足"在盘上长得一样，
        # `dependencies` 于是 0 行而没有任何一处报出这件事。现在它是一行写在报告里
        # 的读数（`carried_missing`），并且进 `last_delivery`。
        if carried_missing.get("carried_missing"):
            lines.append(f"- 携带单缺口（`carried_missing`）：{carried_missing.get('reason')}")
            lines.append("")

        text = "\n".join(lines) + "\n"
        path.write_text(text, encoding="utf-8")
        self.last_report_path = path
        # ---- D 直接把稿交给 B（业主 2026-10-26 晚：「D 到 B 没有路吗？加」） --------
        #
        # 位置在报告落盘之后：B 那一侧要按携带单（这份报告里的三列表）核对"这份稿是
        # D 带来的"，而核对读的是盘上的文件。这一笔是 D 的代码行为，不是模型的 args ——
        # 于是"携带"在真机路径上是必走的（判据见 tests/test_d_to_b_carried_road.py）。
        # 携带单缺口的读数挂在这一笔调用旁边（刻意不改 `_deliver_carried_to_b` 的签名：
        # 那条方法有既有判据按 `(self, rows)` 打桩，加形参会把"递没递"的判据变成
        # `TypeError` —— 那是判据坏了，不是实现坏了）。
        self.last_carried_missing = dict(carried_missing)
        delivery = self._deliver_carried_to_b(carried_rows)
        # ---- 子→父的完成汇报（业主 2026-11-11：D 不能指向 G，G 是父） ----------
        #
        # 时序：「B 收录之后」才汇报（这一行在 `_deliver_carried_to_b` 之后）。
        # 内容：只带指针（命题号 / 稿号 / 台账落点 / 判定），「不带正文」。
        # 机制：`send_message` + 收件箱（`inbox_digest` / `mark_delivered`）——
        # 这是既有的"子任务收尾汇报"通道，不是 summon 一条新边；`D 的出边` 不加 G。
        delivery["parent_report"] = self._report_delivery_to_parent(delivery)
        self.last_delivery = delivery
        lines.extend(self._delivery_section(delivery))
        lines.extend(self._parent_report_section(delivery["parent_report"]))
        lines.append("")

        text = "\n".join(lines) + "\n"
        path.write_text(text, encoding="utf-8")
        self.last_report_path = path
        return str(path)

    def _carried_manuscripts(self) -> tuple[list[dict], str]:
        """D 交研究手稿给 B 时"一并带上的证明手稿" ⇒ `(携带行, 附注)`。

        ## 为什么由代码生成，而不是让模型在报告里写
        模型写手稿（`reports/RESEARCH.md`）是自由的 markdown，它忘一次"把 F 的稿带上"，
        收方 B 那一侧就只是"没收到稿" —— 而那个形态与"这条证明确实自足"长得一样。
        这一节由 D 的事后渲染器算出来（命题行 + 盘上那份稿 + 文件字节的 sha256），
        于是"带没带"在盘上是可判的，不靠记性。

        ## 携带谁
        `statements` 里 `origin=own_result` 且 `status=active`、并且盘上真有一份按它的稿号
        命名的 `reports/f-proof-<稿号>.md`（稿号由 F 自己发，与命题号、计划号无关；
        行上的 `manuscript_id` 与稿内登记条目两处都读，按命题号拼名只当兜底）的那些行。
        散文里的声称不算：手稿文件才是要带的
        那一件东西。读不到台账 / 一份都没有时如实说（不是省略 —— 见渲染器的空表那一句）。

        ## 2026-11-04：E 的穷举证明手稿也走同一张单（业主：「E 的穷举论证和 V 签也是委托入库」）
        键是 `exp:<实验号>`，不是命题号：E 出这条稿的时候命题可能还没进台账
        （它不像 L —— L 一定是来验一条在册命题的）。携带的东西与 F 那份完全同形：
        地址 + 文件字节 sha256；B 那边按证明栏正文的 sha 寻址到它（`read_carried_manuscript`）。
        只带已签的那一份（`vsigns.manuscript_sign_standing` 的 `state="signed"`）：
        没签的稿不是"入库的证明"，带上它只会让 B 的入库闸当场拒一次。
        """
        import hashlib

        from .. import depsection as _DS

        statements, problem, error = SL.rows_of(self.store)
        if problem:
            return [], (f"（`statements` 这一趟读不出来：{error.get('type') or '?'}: "
                        f"{error.get('message') or problem} ⇒ 这张携带单"
                        "没有生成：那是「读不到」，不是「没有可携带的稿」。B 读它之前先让 D 重跑"
                        "一次 `write_report`。）")
        rows: list[dict] = []
        seen: set[str] = set()
        #: 同一个文件只许上一行（`stmt:` 与 `mss:` 两行指着同一份稿 = 重列，不是携带）。
        seen_paths: set[str] = set()
        # ---- 登记条目先读一次：F 的稿按自己的稿号命名，按命题号拼路径找不到它 ---
        #
        # 2026-11-10：稿名与命题号不再绑定 ⇒ "这一条的稿在哪"的可靠来源是
        # `statements` 行上的 `manuscript_id` 与逐路径记录（B 收录 / 落稿时记）；
        # 稿里没有命题号（业主 2026-11-13）⇒ 不再读稿头那一行，按命题号拼名只当兜底。
        note_prefix = ""
        try:
            from .. import proofregistry as _PR_CARRIED

            _entries = _PR_CARRIED.entries_on_disk(self.store.root)
        except Exception as exc:  # noqa: BLE001 —— 读不到要说出来，不许当成"没有稿"
            _entries = []
            note_prefix = (f"（手稿登记条目这一趟读不出来：{type(exc).__name__}: {exc} ⇒ "
                           "这张携带单可能少列了还没拿到命题号的那几份。）")
        _by_stmt: dict[str, str] = {}
        for _one in _entries:
            _sid_e = str(_one.get("statement_id") or "")
            if _sid_e and _sid_e not in _by_stmt:
                _by_stmt[_sid_e] = str(_one.get("path") or "")
        from .. import manuscriptids as _MID_CARRIED

        for row in statements:
            if str(row.get("origin") or "") != "own_result":
                continue
            if str(row.get("status") or "") != "active":
                continue
            sid = str(row.get("stmt_id") or "")
            key = _carried_key("stmt", sid)
            if not sid or key in seen:
                continue
            _mid_rel = _MID_CARRIED.canonical_rel(str(row.get("manuscript_id") or ""))
            _cands = tuple(x for x in (_mid_rel, _by_stmt.get(sid, "")) if x)
            if not _cands:
                # 2026-11-10：`reports/f-proof-<号>.md` 里的号现在是 F 的稿号，
                # 不再是命题号 —— 按命题号拼这个名字会把"恰好同号"的、或还没登记的
                # 草稿带上来。找不到"这一条自己的稿"（行上的 `manuscript_id` /
                # 登记条目的稿头）就不带：携带单不是"所有命题"，更不是"同号即我的"。
                continue
            got = _DS.read_manuscript(self.store.root, manuscript_paths=_cands)
            if str(got.get("source") or "") != _DS.SOURCE_DISK:
                continue
            try:
                blob = (Path(self.store.root) / str(got["path"])).read_bytes()
            except OSError:
                continue
            seen.add(key)
            # 2026-11-11 业主裁定：`proof_no` 在呈递侧退役 —— 携带行不再带这一格。
            # 老稿头里已有的 `- 证明号：N` / 老携带行第四列仍读得出（`depsection`
            # 那两处一个字没动），但新写的这一行不产生它（一稿一份）。
            one = {"statement_id": sid, "path": str(got["path"]),
                   "sha256": hashlib.sha256(blob).hexdigest()}
            rows.append(one)
            seen_paths.add(str(one.get("path") or ""))
        # ---- 2026-11-07（解耦落地）：F 的「登记条目」（还没拿到命题号的那一份） -----
        #
        # 上面那一圈按 `statements` 行找稿；而解耦之后 F 先落手稿登记条目、命题号由 B
        # 在 V 签之后才发 ⇒ 第一轮那一份稿在 `statements` 里还没有行。改前 D 只按命题行
        # 找稿，于是"F 落稿 → D 携带 → B 按 sha 认领"这条唯一交稿链在第一次就断在
        # D 这一侧（携带单 0 行），而那个形态与"这一条证明确实自足"长得一样。
        # 现在：登记条目里 `family=F`、命题号还空（或那一行不在 statements 里）的稿
        # 也上携带单，键用稿号（`mss:<稿号>`，`depsection.CARRIED_KEYS` 的第三档）。
        # 只带 `checked` 的登记条目（`proofregistry.parse_entry`）—— 手写稿没有登记
        # 元信息，不是"等 B 收录的那一份"。
        from .. import vsigns as _VS

        # 号集合的构造只有一处（查口 `index_by_id`）；没号的行由它跳过。
        _known_stmt_ids = set(SL.index_by_id(statements))
        for one in _entries:
            if str(one.get("family") or "") != "F":
                continue
            sid = str(one.get("statement_id") or "")
            if sid and sid in _known_stmt_ids:
                continue
            rel = str(one.get("path") or "")
            msid = str(_VS.manuscript_id_of(rel) or "")
            if not rel or not msid or rel in seen_paths:
                continue
            key = _carried_key("mss", msid)
            if key in seen:
                continue
            try:
                blob = (Path(self.store.root) / rel).read_bytes()
            except OSError:
                continue
            seen.add(key)
            row = {"statement_id": "", "manuscript_id": msid, "path": rel,
                   "sha256": hashlib.sha256(blob).hexdigest()}
            rows.append(row)
        # ---- 2026-11-11（业主裁定 ①③）：F 收工自动提交的拿签稿 -------------------
        #
        # 上面两圈都从「台账行 / 手稿登记条目」找稿；而 F 收工时由框架写下的提交记号
        # （`tasks.artifacts` 的 `mss:<稿号>`）是第三条、也是唯一一条「F 说它交了」的
        # 机械记录 —— 一份拿签稿在被 B 收录之前，只有这条记号能把它带到 D。
        # 「已收录」的那一份由上面两圈按台账行走（同一个文件只上一行由 `seen_paths` 守）。
        auto_rows, auto_note = self._auto_submitted_carried(
            statements, _known_stmt_ids)
        for one in auto_rows:
            msid = str(one.get("manuscript_id") or "")
            key = _carried_key("mss", msid)
            path = str(one.get("path") or "")
            if not msid or key in seen or (path and path in seen_paths):
                continue
            seen.add(key)
            if path:
                seen_paths.add(path)
            rows.append(one)
        # ---- E 的穷举证明手稿（2026-11-04：同一张单，键是 exp:<实验号>） -------------
        #
        # 判据全在盘上：台账里有一行 `evidence_kind="proof"` 的实验、它落了
        # `observations.proof_manuscript`、那份稿在盘上、而且稿里的签块
        # （`secretary:E` 落的）盖的就是它现在这一份正文。少任何一条都不带 ——
        # 半成品带过去只会让 B 的入库闸多拒一次，而"没带"与"没签"在读数上必须分得开。
        from .. import vsigns as _VS

        for row in (self.store.rows("experiments") or []):
            one = dict(row)
            if str(one.get("evidence_kind") or "") != "proof":
                continue
            if str(one.get("method") or "") == "formal":
                continue
            eid = str(one.get("experiment_id") or "")
            facts = one.get("observations") if isinstance(one.get("observations"), Mapping) else {}
            pocket = (facts or {}).get("proof_manuscript") if isinstance(facts, Mapping) else None
            rel = str((pocket or {}).get("path") or "") if isinstance(pocket, Mapping) else ""
            key = _carried_key("exp", eid)
            if not eid or not rel or key in seen or rel in seen_paths:
                continue
            try:
                blob = (Path(self.store.root) / rel).read_bytes()
                text = blob.decode("utf-8", errors="replace")
            except OSError:
                continue
            standing = _VS.manuscript_sign_standing(text, manuscript_path=rel)
            if str(standing.get("state") or "") != "signed":
                continue
            seen.add(key)
            one = {"statement_id": "", "experiment_id": eid, "path": rel,
                   "sha256": hashlib.sha256(blob).hexdigest()}
            #: 2026-11-11 业主裁定：`proof_no` 在呈递侧退役 —— 携带行不再带这一格
            #: （老行 / 老稿头里的号仍由 `depsection` 的读侧认，这里不再抄）。
            rows.append(one)
            seen_paths.add(str(one.get("path") or ""))
        note = auto_note
        if len(rows) > _DS.CARRIED_LIMIT:
            limit_note = (f"另有 {len(rows) - _DS.CARRIED_LIMIT} 条没列出来"
                          f"（这张单只列前 {_DS.CARRIED_LIMIT} 条）—— 它们仍在盘上，"
                          "B 可以按约定路径读（`depsection.read_manuscript`）。")
            note = (note + " " + limit_note).strip()
            rows = rows[:_DS.CARRIED_LIMIT]
        return rows, note

    def _auto_submitted_carried(self, statements, known_stmt_ids) -> tuple[list[dict], str]:
        """F 收工自动提交、而还没被收录的拿签稿 ⇒ `(携带行, 附注)`。

        ## 为什么新增这一源（业主 2026-11-11 裁定 ①）

        `_carried_manuscripts` 上面两圈都从「台账行 / 手稿登记条目」找稿：一份稿在
        被 B 收录之前，台账里没有它的行，登记条目也不一定在盘上 ⇒ 未收录的拿签稿
        到不了 D。F 收工时由框架写进 `tasks.artifacts` 的那条提交记号（`mss:<稿号>`）
        正是"F 说它交了"的机械记录，这一源就按它收。

        ## 判据（三件都要在盘上成立才带）

        1. 记号里的 `file_sha` / `body_sha` 与盘上现行文件一致（提交之后又改过 ⇒ 不带，
           那不是「已提交的那一版」）；
        2. 签复算通过（`vsigns.credential_reading`）—— 没签 / 签不住的稿不是入库的证明；
        3. 尚未收录：`statements` 里没有 `manuscript_id` 是这个稿号的行，
           记号里的 `statement_id` 也不在册 —— 已收录的由上面两圈按台账行走。

        返回的行与 F 那条完全同形：`{statement_id:"", manuscript_id, path, sha256}`，
        `sha256` 是盘上那份文件的字节 sha256（D→B 的地址判据）。
        """
        import hashlib

        from .. import depsection as _DS
        from .. import proofregistry as _PR
        from .. import vsigns as _VS
        #: 记号格式的唯一实现住在 F 的交付读数里（与 F 写 artifacts 那一侧同一份）。
        from ..agent_f import delivery as _FD

        rows: list[dict] = []
        skipped: list[str] = []
        registered = {str(one.get("manuscript_id") or "").strip()
                      for one in (statements or ())
                      if str(one.get("manuscript_id") or "").strip()}
        #: 台账里已经有一份同正文的证明 ⇒ 这一份「已收录」（不靠行上有没有记稿号）。
        registered_bodies: set[str] = set()
        for one in statements or ():
            pt = str(one.get("proof_text") or "")
            if pt.strip():
                registered_bodies.add(_PR.proof_sha(pt))
        latest: dict[str, dict] = {}
        for task in self.store.rows("tasks") or ():
            if str(task.get("role") or "") != "F":
                continue
            got, problems = _FD.submissions_of(task.get("artifacts") or ())
            for why in problems:
                skipped.append(f"{task.get('task_id')}: {why}")
            for mid, rec in got.items():
                cur = latest.get(mid)
                if (cur is None
                        or str(rec.get("submitted_at") or "")
                        >= str(cur.get("submitted_at") or "")):
                    latest[mid] = dict(rec)
        for mid in sorted(latest):
            rec = latest[mid]
            rel = str(rec.get("path") or "").strip().replace("\\", "/")
            if not rel:
                skipped.append(f"mss:{mid}：提交记号里没有地址 ⇒ 带不了")
                continue
            sid = str(rec.get("statement_id") or "")
            if mid in registered or (sid and sid in known_stmt_ids):
                # 已收录：那一份由上面两圈按台账行走，不因新增来源重复。
                continue
            try:
                blob = (Path(self.store.root) / rel).read_bytes()
                text = blob.decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                skipped.append(
                    f"mss:{mid}：`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ 不带")
                continue
            file_sha = hashlib.sha256(blob).hexdigest()
            body_sha = _PR.proof_sha(text)
            want_file = str(rec.get("file_sha") or "")
            if want_file and file_sha != want_file:
                skipped.append(
                    f"mss:{mid}：`{rel}` 在提交之后字节变了（提交时 {want_file[:12]}…"
                    f" / 现在 {file_sha[:12]}…）⇒ 不按「已提交的那一版」带")
                continue
            want_body = str(rec.get("body_sha") or "")
            if want_body and body_sha != want_body:
                skipped.append(
                    f"mss:{mid}：`{rel}` 的正文 sha 与提交记号不符（记号 "
                    f"{want_body[:12]}… / 现在 {body_sha[:12]}…）⇒ 不带")
                continue
            if body_sha in registered_bodies:
                # 台账里已经有一份同正文的证明：已收录，由上面两圈按台账行走。
                continue
            cred = _VS.credential_reading(self.store.root, body_sha)
            if not cred.get("recomputable"):
                skipped.append(
                    f"mss:{mid}：`{rel}` 这一份签复算不上"
                    f"（{cred.get('problem') or '?'}）⇒ 不带"
                    "（没签的稿不是入库的证明）")
                continue
            one = {"statement_id": "", "manuscript_id": mid, "path": rel,
                   "sha256": file_sha}
            # 2026-11-11：呈递侧退役 `proof_no` —— 提交记号里的那一格不再抄进携带行。
            rows.append(one)
        note = ""
        if skipped:
            note = ("（F 已提交但这一趟没带上，逐条："
                    + "；".join(skipped[:8])
                    + (f"；另有 {len(skipped) - 8} 条" if len(skipped) > 8 else "")
                    + "）")
        return rows, note

    def _carried_missing_reading(self, carried_rows: list[dict]) -> dict:
        """携带单缺口的读数（`carried_missing`）：这张单是空的而账上明明有依赖。

        ## 为什么要有这一格（2026-10-27，三件里的第三件：兜底审计）
        改前真机（sylow 那一趟）：D 用 `fs.write` 手写了 `reports/RESEARCH.md` ——
        自由格式、没有 `## 携带的证明手稿` 那一节 ⇒ B 读到"没有可携带的稿"，而
        那个形态与"这条证明确实自足"在盘上一模一样：`dependencies` 0 行、
        `manuscript_source=none`，没有任何一处把"这单是空的"报出来。

        判据（与业主口径逐字对齐："研究报告里缺携带单且 statement 引用了在册命题"）：
        携带单 0 行、而 `statements` 里存在引用了在册命题的行（`derived_from`，
        或证明正文里的 `stmt:` 引用）⇒ `carried_missing=True` 并逐条点名那几个命题号。
        携带单非空 ⇒ 它是 `False`（这一趟不缺）；读不到台账 ⇒ `checked=False` 且
        明确写"读不到"，绝不折成"不缺"。

        返回 `{carried_missing, checked, statement_ids, reason}`。
        """
        rows = carried_rows or []
        if rows:
            return {"carried_missing": False, "checked": True, "statement_ids": [],
                    "reason": f"携带单上有 {len(rows)} 条（这一趟不缺）"}
        from .. import depsection as _DS

        statements, problem, error = SL.rows_of(self.store)
        if problem:
            return {"carried_missing": False, "checked": False, "statement_ids": [],
                    "reason": (f"`statements` 读不出来（{error.get('type') or '?'}: "
                               f"{error.get('message') or problem}）⇒ "
                               "这一趟判不出携带单缺不缺（那是「读不到」，不是「不缺」）")}
        # 号集合的构造只有一处（查口 `index_by_id`）；没号的行由它跳过。
        on_ledger = set(SL.index_by_id(statements))
        refs: list[str] = []
        referenced: set[str] = set()
        for row in statements:
            sid = str(row.get("stmt_id") or "")
            used = [str(x) for x in (row.get("derived_from") or [])]
            used += _DS.stmt_refs(str(row.get("proof_text") or ""))
            hit = sorted({x for x in used if x in on_ledger and x != sid})
            if hit:
                refs.append(f"{sid}→{'、'.join(hit)}")
                referenced.update(hit)
        if not refs:
            return {"carried_missing": False, "checked": True, "statement_ids": [],
                    "reason": "携带单是空的，而账上没有任何一条在册命题被引用（自足 ⇒ 不缺）"}
        return {
            "carried_missing": True, "checked": True,
            "statement_ids": sorted(referenced),
            "reason": ("携带单是空的，而账上这几条命题引用了在册命题："
                       + "、".join(refs)
                       + " ⇒ 这份研究手稿缺携带单（缺的不是『没有可携带的稿』，是那几份稿"
                       "没有随报告交给 B）"),
        }

    def _deliver_carried_to_b(self, rows: list[dict]) -> dict:
        """把携带单上每一条 F 证明手稿递给 B 登记（收方读稿落依赖面）。

        ## 为什么这条调用必须写在 D 的代码里（业主 2026-10-26 晚）
        「D 到 B 没有路吗？加」「让携带是代码行为、不是模型记性」。改前 D 只能 `summon`
        派 B、args 由模型产出 ⇒ 携带这条链只能退化成"报告里由代码生成一张携带单，
        B 自己去读"，而 B 从来没有被 D 这样调用过（`dependencies` 真机 0 行）。

        这一笔交过去的东西（逐字就是 `AgentB.register_statement` 的入参）：
        `statement_full`（在册那一行的完整命题）、`proofs`（那一行的证明清单）、
        `proof_text`（canonical 正文）、`derived_from`（承重链）、
        `proof_manuscript`（盘上那份手稿的正文）—— B 的读数里会写
        `manuscript_source=carried_by_D`（它按这份报告里的携带单核 sha 之后才认）。

        三态：没有 B（直调 `AgentD(store)`）⇒ `checked=False` + why；B 收下 / 拒收
        逐条记（拒信原文进 `error`），绝不把"没递"写成"递了"。
        """
        out: dict[str, Any] = {"checked": False, "rows": 0, "delivered": 0,
                               "results": [], "why": "", "report": "",
                               #: E 的穷举证明稿（`exp:` 行）：不代 B 登记，按携带单寻址 ——
                               #: 这一格是"没被问"的读数，不是"拒收"，所以它不带 `ok` 那一格
                               #: （手写 `ok=False` 会被 `tests/test_refusals.py` 当成一次
                               #: 失败要登记；而这里根本没有人执行过任何登记）。
                               "addressed": [],
                               # 携带单缺口的读数（2026-10-27）：这一趟不管递没递出去，
                               # "这张单是空的而账上有依赖"这件事都跟着读数走，不许静默。
                               "carried_missing": bool(
                                   (getattr(self, "last_carried_missing", {}) or {}).get("carried_missing")),
                               "carried_missing_reason": str(
                                   (getattr(self, "last_carried_missing", {}) or {}).get("reason") or "")}
        if self.b is None:
            out["why"] = ("这一趟手上没有 B 的入口（直调 `AgentD(store)` 时没有 `b=`）⇒ "
                          "携带单生成了，但没有递出去；真机路径由 `specs/d.py::_build` 在"
                          "构造期绑进同一个 B 实例")
            return out
        out["checked"] = True
        out["rows"] = len(rows)
        for row in rows:
            sid = str(row.get("statement_id") or "")
            eid = str(row.get("experiment_id") or "")
            msid = str(row.get("manuscript_id") or "")
            if not sid and not eid and msid:
                # ---- 2026-11-07（解耦落地）：F 的登记条目（还没有命题号） ------------
                #
                # 唯一交稿链的第一环：F 落手稿登记条目（命题号还没发）→ D 携带 →
                # B 按正文 sha 认领、发号、落 statements 一行。这一支与 E 的 `exp:` 行
                # 同形：参数从"稿 + 稿头元信息"拼，命题号不需要先有。
                rec = self._deliver_f_manuscript_row(row)
                if rec is not None:
                    out["results"].append(rec)
                    if rec.get("ok"):
                        out["delivered"] = int(out["delivered"]) + 1
                continue
            if not sid and eid:
                # ---- 2026-11-04（业主裁定 B）：E 的 `exp:` 行也由 D 代递 ------------
                #
                # 改前这一支只记一条"没被问"的读数（"命题还没有号 ⇒ D 不代它登记"），
                # 于是 E 的穷举证明稿虽然写在携带单上，B 却从未被 D 直接调用过 ——
                # 业主的口径是「与 F 行同形」：F 行由 D 调 `register_statement` 递，
                # E 行也照同样的形状递（命题号不需要先有：B 的登记入口本来就接受
                # 首次登记）。参数从 experiment 行 + 稿拼（statement_full / 证明栏 /
                # doc_id / line_range），判据在 `_deliver_exp_row` 一处。
                rec = self._deliver_exp_row(row)
                if rec is not None:
                    out["results"].append(rec)
                    if rec.get("ok"):
                        out["delivered"] = int(out["delivered"]) + 1
                continue
            rec: dict[str, Any] = {"statement_id": sid, "ok": False, "stmt_id": "",
                                   "deps_written": 0, "manuscript_source": "",
                                   "manuscript_washed": False, "kind": "", "error": ""}
            stmt_row = None
            # 按号定位走查口（口径一）；读不到要说出来（不是「这一条不在册」）。
            by_id = SL.by_id(self.store, stmt_id=sid)
            if not by_id["checked"]:
                err = by_id.get("error") or {}
                rec["error"] = (f"读不到 statements：{err.get('type', '?')}: "
                                f"{err.get('message', '?')}")
            else:
                stmt_row = by_id["row"] if by_id["found"] else None
            text = ""
            try:
                text = (Path(self.store.root) / str(row.get("path") or "")).read_text(
                    encoding="utf-8")
            except OSError as exc:
                rec["error"] = (f"读不到手稿 {row.get('path')}（{type(exc).__name__}: {exc}）"
                                " ⇒ 这一条递不出去")
            if stmt_row is not None and text.strip() and not rec["error"]:
                # ---- 2026-11-08（业主三条裁定）：D 只递指针 -------------------------
                #
                # 改前这一笔把 `statement_full` / `statement_text` / `proof_text` /
                # `proofs` / `kind` / `evidence_kind` / `quote_reason` 从在册那一行抄进
                # 参数 —— 那是"把手稿内容转手一遍"：登记的那一份与稿里的那一份成了两个
                # 来源，没有任何东西保证它们逐字相同。现在只给三样指针：稿的工作区
                # 相对路径、命题号（这里就是 `row` 那一条在册行）、出处（稿本身）。
                # 命题正文 / 证明正文 / kind / evidence_kind 由 B 从稿里读
                # （`AgentB._register_pointer_manuscript`）；D 再传正文会被 B 受控拒。
                try:
                    got = dict(self.b.register_statement(
                        proof_manuscript=str(row.get("path") or ""),
                        line_range={"label": f"stmt:{sid}"},
                    ) or {})
                except Exception as exc:  # noqa: BLE001 —— B 炸了也要如实记
                    rec["error"] = f"B 的登记入口抛了：{type(exc).__name__}: {exc}"
                else:
                    rec.update(ok=bool(got.get("ok")),
                               stmt_id=str(got.get("stmt_id") or ""),
                               deps_written=int(got.get("deps_written") or 0),
                               manuscript_source=str(got.get("manuscript_source") or ""),
                               manuscript_washed=bool(got.get("manuscript_washed")),
                               kind=str(got.get("kind") or ""),
                               error=str(got.get("error") or ""))
                    if rec["ok"]:
                        out["delivered"] = int(out["delivered"]) + 1
            out["results"].append(rec)
        if not rows:
            out["why"] = "携带单是空的（盘上没有任何一条按命号命名的 F 证明手稿）"
        return out

    # ---------------------------------------------------------------- 子→父的完成汇报

    #: 向上汇报的标题前缀（机器可识别；测试与审计按它捞，不另造第二套）。
    PARENT_REPORT_SUBJECT = "D 交付汇报"

    def _parent_of_this_summon(self) -> tuple[str, str]:
        """这一趟的父 `(角色, 依据)`；`("", 依据)` = 判不出父是谁（不猜）。"""
        tid = ""
        try:
            from ..conductor import current_task_id as _ctid

            tid = str(_ctid() or "")
        except Exception:  # noqa: BLE001 —— 挂点坏了就按"没有号"读，不编一个父
            tid = ""
        if not tid:
            return "", "这一趟没有召唤号（直调 `AgentD` / 不在 summon 上下文里）"
        row = next((r for r in self.store.rows("tasks")
                    if str(r.get("task_id")) == tid), None)
        if row is None:
            return "", f"召唤号 {tid} 在 tasks 台账里读不到 ⇒ 判不出父是谁"
        called_by = str(row.get("called_by") or "")
        if called_by and called_by not in ("M", "user"):
            return called_by, f"tasks[{tid}].called_by={called_by}"
        return "", f"tasks[{tid}].called_by={called_by!r}（不是角色父）"

    def _report_delivery_to_parent(self, delivery: Mapping[str, Any]) -> dict[str, Any]:
        """把"B 收录成没成"如实汇报给父（只带指针，不带正文）。

        ## 为什么汇报必须发生在这一笔之后（业主 2026-11-11）
        「D 干完 ⇒ 向上汇报」—— 而 D 的活是"补材料 + 交台账"，所以"成没成"只有
        `_deliver_carried_to_b` 的返回值知道。汇报写在它之后，且「失败也汇报」
        （B 受控拒时写"没进台账、原因是…"），绝不把拒收说成办成了。

        ## 为什么走收件箱而不是 summon
        `D 的出边` 不含 `G`（业主：「D 不能指向 G，G 是 D 的父，是向上汇报完成任务」）。
        向上汇报的现成机制是子任务收尾的那条私聊：`send_message` 落一条
        `agent_message`，父下一趟进循环时由 `inbox_digest` 读进开场提示词。
        于是这里只写一条留言，不碰边表、不新增工具。

        ## 内容只有指针
        `stmt_id` / `manuscript_id` / `deps_written` / 拒信原文（截断）；命题正文与
        证明正文一律不写（G 拿东西一律去台账读，见 `specs/g.py` 的转交规则）。
        """
        results = [r for r in (delivery.get("results") or []) if isinstance(r, Mapping)]
        ok_rows = [r for r in results if r.get("ok")]
        bad_rows = [r for r in results if not r.get("ok")]
        if not results:
            return {"checked": False, "sent": False, "to": "", "msg_id": "",
                    "success": [], "failed": [],
                    "why": ("携带单是空的 ⇒ 这一趟没有向 B 递任何东西，也没有可汇报的收录结果"
                            "（不拿一条空汇报冒充「已完成」）")}
        to_role, basis = self._parent_of_this_summon()
        if not to_role:
            return {"checked": False, "sent": False, "to": "", "msg_id": "",
                    "success": [self._delivery_pointer(r) for r in ok_rows],
                    "failed": [self._delivery_pointer(r) for r in bad_rows],
                    "why": f"判不出父是谁：{basis} ⇒ 这条汇报没发（不猜收件人）"}
        lines = [f"父：{to_role}（依据 {basis}）。这是 D 交付这一笔的完成汇报（只带指针，正文在台账）。"]
        if ok_rows:
            lines.append(f"- B **收录成功** {len(ok_rows)} 条：")
            lines.extend(f"  - {self._pointer_text(r)}" for r in ok_rows)
            lines.append("  - 命题正文 / 证明正文请去台账读（`statements` 行 / `ledger.resolve`），"
                         "本条不含正文。")
        if bad_rows:
            lines.append(f"- B **受控拒 / 没进台账** {len(bad_rows)} 条（不是办成了）：")
            lines.extend(f"  - {self._pointer_text(r)}；拒信：{str(r.get('error') or '')[:240]}"
                         for r in bad_rows)
        if not bad_rows:
            lines.append("- 没有受控拒的条目。")
        body = "\n".join(lines)
        from .. import sessions as SS

        try:
            from ..conductor import current_session as _cs

            sroot, sid = _cs()
        except Exception:  # noqa: BLE001 —— 读不到会话身份就退回工作区根 + 当天会话
            sroot, sid = "", ""
        session_root = Path(sroot) if str(sroot or "") else Path(str(self.store.root))
        try:
            from ..agent_loop import send_message
        except Exception as exc:  # noqa: BLE001 —— 发不出去要如实记，不许静默
            return {"checked": True, "sent": False, "to": to_role, "msg_id": "",
                    "success": [self._delivery_pointer(r) for r in ok_rows],
                    "failed": [self._delivery_pointer(r) for r in bad_rows],
                    "why": f"消息通道不可用（{type(exc).__name__}: {exc}）⇒ 汇报没发出"}
        msg_id, problem = send_message(
            session_root, sender="D", to=to_role,
            subject=(f"{self.PARENT_REPORT_SUBJECT}：收录 {len(ok_rows)} 条"
                     + (f" / 拒 {len(bad_rows)} 条" if bad_rows else "")),
            body=body, sid=str(sid or "") or None, by_framework=True,
        )
        return {"checked": True, "sent": bool(msg_id) and not problem, "to": to_role,
                "msg_id": str(msg_id or ""), "session_root": str(session_root),
                "sid": str(sid or ""),
                "success": [self._delivery_pointer(r) for r in ok_rows],
                "failed": [self._delivery_pointer(r) for r in bad_rows],
                "why": str(problem or "")}

    @staticmethod
    def _delivery_pointer(row: Mapping[str, Any]) -> dict[str, Any]:
        """一条交付结果的指针（不含正文）。"""
        return {
            "stmt_id": str(row.get("stmt_id") or ""),
            "statement_id": str(row.get("statement_id") or ""),
            "manuscript_id": str(row.get("manuscript_id") or ""),
            "deps_written": int(row.get("deps_written") or 0),
            "ok": bool(row.get("ok")),
            "error": str(row.get("error") or "")[:240],
        }

    def _pointer_text(self, row: Mapping[str, Any]) -> str:
        p = self._delivery_pointer(row)
        bits = []
        if p["stmt_id"]:
            bits.append(f"stmt:{p['stmt_id']}")
        if p["statement_id"]:
            bits.append(f"在册行 stmt:{p['statement_id']}")
        if p["manuscript_id"]:
            bits.append(f"稿 {p['manuscript_id']}")
        bits.append(f"deps_written={p['deps_written']}")
        bits.append("台账落点 statements 行（读它拿正文）")
        return "；".join(bits)

    def _parent_report_section(self, report: Mapping[str, Any]) -> list[str]:
        """把"向上汇报"的读数画进报告（成没成、发给谁、消息号、逐条指针）。"""
        lines = ["## 8. 向上汇报（子→父；只带指针，不带正文）", ""]
        if not report:
            return lines + ["（这一版没有这一节）", ""]
        if not report.get("checked"):
            lines.append(f"- **没查成 / 没发**：{report.get('why') or ''}")
            return lines + [""]
        if not report.get("sent"):
            lines.append(f"- **没发出**（收件人 {report.get('to') or '?'}）："
                         f"{report.get('why') or ''}")
        else:
            lines.append(f"- 已发：`{report.get('msg_id')}` → {report.get('to')}"
                         f"（会话 `{report.get('sid') or '当天'}`）")
        for tag, key in (("收录成功", "success"), ("受控拒 / 没进台账", "failed")):
            rows = list(report.get(key) or [])
            lines.append(f"- {tag}：{len(rows)} 条")
            for r in rows:
                bits = [f"stmt:{r['stmt_id']}" if r.get("stmt_id") else "（未发号）",
                        f"稿 {r['manuscript_id']}" if r.get("manuscript_id") else "",
                        f"deps_written={r.get('deps_written')}",
                        ("正文在 statements 行，本条不含正文" if r.get("ok")
                         else f"拒信：{r.get('error') or ''}")]
                lines.append("  - " + "；".join(b for b in bits if b))
        return lines + [""]


    def _deliver_f_manuscript_row(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        """把携带单上一条"F 的登记条目（命题号还没发）"递给 B（2026-11-07 解耦）。

        ## 为什么这一支必须存在（唯一交稿链的第一环）

        业主 2026-11-07 最终裁定：「为了落实口径，裁去F到B的直接出边……F只能向上通过D
        向B交稿」＋「向上的意思是F向父代理D交稿」。于是交稿链路只有一条：
        F 落手稿 → 派 D 携带 → D 派 B 收录（V 签之后按 sha 认领）。
        F 的第一轮证明是一份登记条目、命题号还没发（号由 B 在 V 签之后发），
        而改前 D 只按 `statements` 行找稿 ⇒ 这一条链在第一次就断了。

        ## 递过去只有指针（2026-11-08 业主裁定：D 对命题台账只读）

        - `proof_manuscript`：稿的工作区相对路径（唯一的内容入口）；
        - 命题号 / 实验号与出处：F 的稿按路径本身点名；E 的 `exp:` 行另给
          `line_range={"label": "exp:<实验号>"}`。

        命题正文、证明正文、`kind`、`evidence_kind` 一律由 B 从稿里读
        （`B._register_pointer_manuscript`）；D 传正文会被 B 受控拒。下面这两段预读
        只为把"稿缺 `## 命题` / `## 证明`"在 D 这一侧就如实记成 `error`。

        三态：没有 B ⇒ 一条 `checked` 之外的原因；稿读不到 / 没有 `## 命题` 或
        `## 证明` ⇒ 不递并点名；B 拒收 ⇒ `ok=False` + 拒信原文。
        """
        from .. import depsection as _DS
        from .. import proofregistry as _PR

        rel = str(row.get("path") or "")
        rec: dict[str, Any] = {
            "statement_id": "", "manuscript_id": str(row.get("manuscript_id") or ""),
            "ok": False, "stmt_id": "", "deps_written": 0, "manuscript_source": "",
            "manuscript_washed": False, "kind": "", "error": ""}
        if self.b is None:
            rec["error"] = ("这一趟手上没有 B 的入口（直调 `AgentD(store)` 时没有 `b=`）"
                            " ⇒ 这一份 F 的登记条目没有递出去")
            return rec
        try:
            text = (Path(self.store.root) / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            rec["error"] = (f"读不到手稿 {rel}（{type(exc).__name__}: {exc}）"
                            " ⇒ 这一份 F 的登记条目递不出去")
            return rec
        _head, sections = _PR.split_sections(text)
        proposition = next((body.strip() for name, body in sections if name == "命题"), "")
        #: 2026-11-09（D4）：`## 证明` 缺节是没有这一块，不拿 `## 依赖` / 全文顶替。
        proof_reading = _DS.proof_body_reading(text)
        proof_text = str(proof_reading.get("body") or "").strip("\n")
        if not proposition:
            rec["error"] = f"{rel} 里没有 `## 命题` 那一节 ⇒ 不知道要给 B 登记哪一条命题"
            return rec
        if not proof_text.strip():
            _absent = str(proof_reading.get("state") or "") == _DS.PROOF_ABSENT
            rec["error"] = (
                f"{rel} 里没有 `{_DS.SECTION_PROOF}` 那一节 ⇒ 没有可登记的证明正文"
                "（缺节不等于「证明为空」；不拿 `## 依赖` 或整份全文顶替）"
                if _absent else
                f"{rel} 里 `{_DS.SECTION_PROOF}` 那一节是空的 ⇒ 没有可登记的证明正文")
            return rec
        try:
            # ---- 2026-11-08（业主三条裁定）：D 只递指针 -------------------------
            #
            # 改前这一笔把 `## 命题` / `## 证明` / 稿头 `- 命题类型` 抄进
            # `statement_full` / `proof_text` / `kind` —— 那是"把手稿内容转手一遍"。
            # 现在只给指针：稿的工作区相对路径；命题正文、证明正文、kind、
            # evidence_kind 全部由 B 从稿里读（`B._register_pointer_manuscript`）。
            # 上面那两段预读保留，只为把"稿缺 `## 命题` / `## 证明`"在 D 这一侧就
            # 如实记成 `error`（那是"这一条递不出去"的读数，不是登记参数）。
            got = dict(self.b.register_statement(
                proof_manuscript=rel,
            ) or {})
        except Exception as exc:  # noqa: BLE001 —— B 炸了也要如实记
            rec["error"] = f"B 的登记入口抛了：{type(exc).__name__}: {exc}"
            return rec
        rec.update(ok=bool(got.get("ok")),
                   stmt_id=str(got.get("stmt_id") or ""),
                   deps_written=int(got.get("deps_written") or 0),
                   manuscript_source=str(got.get("manuscript_source") or ""),
                   manuscript_washed=bool(got.get("manuscript_washed")),
                   kind=str(got.get("kind") or ""),
                   error=str(got.get("error") or ""))
        return rec

    def _deliver_exp_row(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        """把携带单上一条 E 的 `exp:` 稿递给 B（与 F 行同形；业主 2026-11-04 裁定 B）。

        ## 业主口径（逐字）

        > 「E 的 exp: 行也由 D 代递（与 F 行同形）」

        ## 递过去只有指针（2026-11-08）

        - `proof_manuscript`：稿的工作区相对路径（唯一的内容入口）；
        - `line_range.label`：出处 `exp:<实验号>` —— 指回 experiment 行，`doc_id` 不填
          （编一个不存在的 doc 号比留空更坏）。

        命题正文、证明正文、`kind`、`evidence_kind` 一律由 B 从稿里读。D 传正文会被
        B 受控拒。下面那两段预读只为把"稿缺 `## 证明` / 没有签"在 D 这一侧就记成
        `error`（那是"这一条递不出去"的读数，不是登记参数）。

        ## 三态（不折平）

        - 稿上没有覆盖它的签（`manuscript_sign_standing != signed`）⇒ 不递，读数
          `kind="exp_proof_unsigned"`：没签的稿不是"入库的证明"，带上它只会让 B 白拒一次；
        - 实验行读不到 / 稿读不到 ⇒ `checked=False` 的读数（`error` 里点名原因），不猜；
        - B 拒收 ⇒ `ok=False` + 拒信原文；B 收下 ⇒ `ok=True` + `stmt_id` / 依赖边数。

        返回一条 result（键与 F 行同形，另带 `experiment_id`）；`None` = 这一行不该由本方法
        处理（反真空打桩点就落在这里：摘掉它 ⇒ B 侧收不到、`statements` 里没有那一行）。
        """
        from .. import depsection as _DS
        from .. import vsigns as _VS

        eid = str(row.get("experiment_id") or "")
        rel = str(row.get("path") or "")
        rec: dict[str, Any] = {
            "statement_id": "", "experiment_id": eid, "ok": False, "stmt_id": "",
            "deps_written": 0, "manuscript_source": "", "manuscript_washed": False,
            "kind": "", "error": ""}
        if self.b is None:
            rec["error"] = ("这一趟手上没有 B 的入口（直调 `AgentD(store)` 时没有 `b=`）"
                            " ⇒ 这一条 exp 稿没有递出去")
            return rec
        exp_row = None
        try:
            exp_row = next((r for r in self.store.rows("experiments")
                            if str(r.get("experiment_id") or "") == eid), None)
        except Exception as exc:  # noqa: BLE001 —— 读不到要说出来，不许当成"没有这条实验"
            rec["error"] = f"读不到 experiments：{type(exc).__name__}: {exc}"
            return rec
        if exp_row is None:
            rec["error"] = f"携带单上的 exp:{eid} 在 experiments 台账里找不到 ⇒ 不递（不猜）"
            return rec
        try:
            text = (Path(self.store.root) / rel).read_text(encoding="utf-8")
        except OSError as exc:
            rec["error"] = (f"读不到手稿 {rel}（{type(exc).__name__}: {exc}）"
                            " ⇒ 这一条 exp 稿递不出去")
            return rec
        # ---- 没签的 exp 行不代递（沿用 `_carried_manuscripts` 的同一把尺） ----------
        #
        # 携带单理论上只收已签的稿（`_carried_manuscripts` 已筛过一遍），但这里是
        # 代递的最后一道：打桩/直调/清单漂移都可能把一份没签的稿送进来，而"没签"
        # 与"B 说不行"是两件事，不许在读数上混成一条 `ok=False` 的拒收。
        standing = _VS.manuscript_sign_standing(text, manuscript_path=rel)
        if str(standing.get("state") or "") != "signed":
            rec["kind"] = "exp_proof_unsigned"
            rec["error"] = (f"exp:{eid} 的稿没有覆盖它的 V 签块"
                            f"（{standing.get('state') or 'unsigned'}："
                            f"{standing.get('why') or '没有签'}）⇒ D 不代递："
                            "没签的稿不是入库的证明，先让 E 派 V 拿签再带")
            return rec
        proof_reading = _DS.proof_body_reading(text)
        proof_text = str(proof_reading.get("body") or "")
        if not proof_text.strip():
            _absent = str(proof_reading.get("state") or "") == _DS.PROOF_ABSENT
            rec["error"] = (
                f"exp:{eid} 的稿里没有 `{_DS.SECTION_PROOF}` 那一节 ⇒ 没有可登记的证明正文"
                "（缺节不等于「证明为空」；不拿 `## 依赖` 或整份全文顶替）"
                if _absent else
                f"exp:{eid} 的稿里 `{_DS.SECTION_PROOF}` 那一节是空的 ⇒ 没有可登记的证明正文")
            return rec
        try:
            # ---- 2026-11-08（业主三条裁定）：D 只递指针 -------------------------
            #
            # 改前这一笔把 experiment 行的 `claim` / `claim_key` 与稿里 `## 证明`
            # 抄进 `statement_full` / `statement_text` / `proof_text`。现在只给指针：
            # 稿的工作区相对路径 + 出处（`exp:<实验号>`）；命题正文、证明正文、
            # kind、evidence_kind 由 B 从稿里读。
            got = dict(self.b.register_statement(
                proof_manuscript=rel,
                line_range={"label": f"exp:{eid}"},
            ) or {})
        except Exception as exc:  # noqa: BLE001 —— B 炸了也要如实记
            rec["error"] = f"B 的登记入口抛了：{type(exc).__name__}: {exc}"
            return rec
        rec.update(ok=bool(got.get("ok")),
                   stmt_id=str(got.get("stmt_id") or ""),
                   deps_written=int(got.get("deps_written") or 0),
                   manuscript_source=str(got.get("manuscript_source") or ""),
                   manuscript_washed=bool(got.get("manuscript_washed")),
                   kind=str(got.get("kind") or ""),
                   error=str(got.get("error") or ""))
        return rec

    def _dependency_edges(self, stmt_id: str) -> tuple[int, int, str]:
        """这一条命题在 `dependencies` 台账里的依赖边读数 `(全部 N, 命题→命题 M, 读不到原因)`。

        为什么按台账现算而不是照抄 B 的 `deps_written`：报告是"这一刻盘上有什么"的书面
        痕迹，而 `deps_written` 只说"这一笔新落了几条"（幂等重交时它是 0，盘上却有边）。
        两件事都要读得出来，但报告里那一列问的是前者 —— 所以这里读台账，并在同一格里
        把"其中命题→命题几条"分开：文献/实验/文档来的边与命题来的边混成一个数，
        读者就看不出"这条定理在依赖图上到底有没有上游"。

        `used_by` 的 `#pN` 尾巴走 `proofloc.parse_used_by`（全仓唯一解析口）：
        `stmt:000004#p2` 与 `stmt:000004` 是同一个命题号。
        三态：台账读不出来 ⇒ `(-1, -1, 原因)`，报告里写"未读到"，不写 0。
        """
        from ..proofloc import parse_used_by

        total = 0
        from_statement = 0
        try:
            for row in self.store.rows("dependencies"):
                head, _no = parse_used_by(str(row.get("used_by") or ""))
                if head != f"stmt:{stmt_id}":
                    continue
                total += 1
                if str(row.get("source_stmt_id") or "").strip():
                    from_statement += 1
        except Exception as exc:  # noqa: BLE001 —— 读不到要如实说，不许折成 0
            return -1, -1, f"{type(exc).__name__}: {exc}"
        return total, from_statement, ""

    def _delivery_section(self, delivery: Mapping[str, Any]) -> list[str]:
        """这一趟"把稿交给 B"的回执（写进报告：递了没递、B 落了几条依赖边）。

        为什么写进报告而不是只留在内存：D 的报告是这一趟交接的唯一书面痕迹；
        "D 递了、B 收下了几条边"必须能被下一个人从盘上读到，而不是去翻会话记录。

        2026-11-05（缺陷 1c）：依赖边那一列拆成两个数 —— `全部 / 其中命题→命题`。
        改前只有一个数，于是 87 真机那种"3 条边全是文献来的、一条命题→命题都没有"
        在报告上与"依赖面建起来了"长得一模一样（见
        `temp/dep_probe/REPORT-dependency-surface.md` 第三节 B 表：`source_stmt_id` 非空 0 行）。
        """
        lines = ["## D 交给 B 的登记回执（D→B）", ""]
        if delivery.get("carried_missing"):
            lines.append(f"- 携带单缺口（`carried_missing`）："
                         f"{delivery.get('carried_missing_reason') or '（原因缺失）'}")
            lines.append("")
        if not delivery.get("checked"):
            lines.append(f"（这一趟没有递交：{delivery.get('why') or '（原因缺失）'}）")
            return lines
        results = list(delivery.get("results") or [])
        addressed = list(delivery.get("addressed") or [])
        lines.append(
            f"D 的这一笔代码调用（`AgentB.register_statement`）覆盖 "
            f"{int(delivery.get('rows') or 0)} 条携带行，B 收下 "
            f"{int(delivery.get('delivered') or 0)} 条。")
        # 依赖边读数（全部 N / 其中命题→命题 M）：逐条现算，合计写一行 —— 这一行是
        # "依赖面到底建起来没有"在报告里的唯一一句话（改前只有逐行的单个数）。
        edge_rows: list[tuple[str, int, int, str]] = []
        edge_by_stmt: dict[str, tuple[int, int, str]] = {}
        for r in results:
            sid = str(r.get("statement_id") or "")
            if not sid:
                continue
            total, from_statement, why = self._dependency_edges(sid)
            edge_rows.append((sid, total, from_statement, why))
            edge_by_stmt[sid] = (total, from_statement, why)
        unread = [(sid, why) for sid, total, _m, why in edge_rows if total < 0]
        if edge_rows:
            if unread:
                lines.append(
                    f"- 依赖边：未读到（{len(unread)} 条命题的 `dependencies` 台账读不出来："
                    + "、".join(f"stmt:{sid}（{why}）" for sid, why in unread[:4])
                    + "）⇒ 没查成不是「零依赖」")
            else:
                total_all = sum(total for _sid, total, _m, _why in edge_rows)
                from_stmt = sum(m for _sid, _t, m, _why in edge_rows)
                lines.append(
                    f"- 依赖边 {total_all} 条（其中命题→命题 {from_stmt} 条）—— "
                    "按 `dependencies` 台账现算（`used_by=\"stmt:<号>#pN\"`；"
                    "命题→命题 = `source_stmt_id` 非空）")
            lines.append("")
        lines.append("| 命题号 / 实验号 | B 的结果 | 依赖边（台账：全部 / 其中命题→命题） | "
                     "稿的来源 | 秘书洗过 | 拒因 |")
        lines.append("|---|---|---|---|---|---|")
        for r in results:
            key = (f"stmt:{r.get('statement_id')}" if str(r.get("statement_id") or "")
                   else f"exp:{r.get('experiment_id')}")
            sid = str(r.get("statement_id") or "")
            if sid:
                total, from_statement, _why = edge_by_stmt[sid]
                cell = ("未读到" if total < 0 else f"{total} / {from_statement}")
            else:
                cell = "-"
            lines.append(
                f"| {key} | {'收下' if r.get('ok') else '拒收'} | "
                f"{cell} | {r.get('manuscript_source') or '-'} | "
                f"{'是' if r.get('manuscript_washed') else '否'} | "
                f"{_digest(r.get('kind') or r.get('error'), 120) or '-'} |")
        if not results:
            lines.append("| （空） | - | 0 | - | - | - |")
        # 旧读数：改前 D 对 `exp:` 行只记"按携带单寻址、不代 B 登记"（`addressed`）。
        # 2026-11-04 起 exp 行也由 D 代递（与 F 行同形）⇒ 这一格正常情况下是空的，
        # 保留它只为读得回旧工作区里那一批报告。
        for one in addressed:
            lines.append("")
            lines.append(
                f"- `exp:{one.get('experiment_id')}` 的稿 `{one.get('path')}` 这一趟没有代 B 登记："
                f"{one.get('why') or '按携带单寻址'}")
        return lines


