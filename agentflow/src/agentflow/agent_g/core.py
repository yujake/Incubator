"""角色 G 的实现核心（`goal-7f5116c1` M6）：其余成员 + 把动作 mixin 装起来。

动作方法一个都没留在这里 —— 它们各自在 `agent_g/<动作>.py`。
这一层与各动作文件共用 `_support.py`（模块级 helper 与常量）。
"""
from __future__ import annotations

from ._support import Any, CA, Callable, DT, DocumentError, Mapping, Path, S, Sequence, Store, ToolRegistry, install_g_tools
from .compose_claim import _ComposeClaim
from .register_dependency import _RegisterDependency
from .build_document import _BuildDocument
from .render import _Render
from .refresh_markdown import _RefreshMarkdown
from .revise import _Revise


class _Core:
    def __init__(
        self,
        store: Store,
        *,
        config: Mapping[str, Any] | None = None,
        workspace_root: str | Path | None = None,
        log: Callable[[str], None] | None = None,
        tools: ToolRegistry | None = None,
        # LLM 判定缝（`draft/30` §T0-8）：默认 None = 不接线 ⇒ 本角色一个 LLM 调用都不发。
        # 判定必须走 `judge.judge_json`（唯一缝协议），失败落 `judge_*` 词表，
        # 绝不许折成"没找到"。本批只插插座，接线在各条目的伪代码下进行。
        llm: Any | None = None,
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = str(self.cfg.get("actor", "agent-G"))
        self.llm = llm
        self.workspace_root = (
            Path(workspace_root).resolve() if workspace_root else Path(store.root).resolve()
        )
        #: 可选的日志钩子。不传就只往内存里记 —— 自检与测试都要能拿到"做了什么"。
        self.log = log
        self.logs: list[str] = []
        self.tool_calls: list[dict] = []
        self.last_tool_errors: list[dict] = []

        #: 稿件 markdown 落在工作区的哪个子目录（相对路径的默认值）。
        self.docs_subdir = str(self.cfg.get("docs_subdir", "documents"))
        self.tools = (
            tools
            if tools is not None
            else install_g_tools(self.store, workspace_root=self.workspace_root)
        )
        # ---- 绑定角色（`P-14`）：注入的注册表同样要绑（`AgentD` 那条注释同族）。
        if self.tools.bound_role is None:
            self.tools.bound_role = "G"
    def _emit(self, message: str, **extra: Any) -> None:
        line = message if not extra else f"{message} {extra}"
        self.logs.append(line)
        if callable(self.log):
            try:
                self.log(line)
            except Exception:  # noqa: BLE001 - 日志钩子坏了不该打断写稿
                pass
    def _call(self, name: str, /, *, required: bool = True, **params: Any) -> Any:
        """调工具并解开 `ToolResult`。

        `required=True` 时把失败上抛（失败原因一并带出），因为写稿这类动作
        "做没做成"必须让调用方立刻知道；`required=False` 时返回 `None` 并把原因
        记进 `last_tool_errors`（供"读一读、拿不到就算了"的场景）。
        """
        res = self.tools.call(name, **params)
        self.tool_calls.append({"tool": name, "ok": res.ok, "error": res.error})
        if not res.ok:
            self.last_tool_errors.append(
                {"tool": name, "error": res.error, "kind": res.meta.get("kind")}
            )
            if required:
                raise DocumentError(f"{name} 调用失败：{res.error}")
            return None
        return res.data
    def check_claims(self, claims: Sequence[Mapping[str, Any]], *, strict: bool = False) -> dict:
        """用 `claimanatomy` 的判据逐条解剖一批断言（只读，不落库）。

        为什么 G 需要它：`build_document` 是"要么全过、要么全不写"的闸门，
        而在组装阶段（手里还在改稿）往往只想问"现在这版有几条不合格"。
        它返回的 `undecidable_count` 就是三态纪律第三态的落点
        （同一个返回里的 `decided` 是由它推出的布尔结论，不是第三个计数）：
        "字段缺失"与"字段非法"与"检查器没跑成"必须能分开处置 ——
        后者单独占 `undecidable_count` 一档，不许并进任何别的档。

        判据来自 `claimanatomy.CLAIM_FIELDS`（唯一来源），本方法只是汇总。
        """
        claims = [CA.migrate_claim(c) if isinstance(c, Mapping) else c for c in claims]
        issues = CA.validate_document_claims({"doc_id": "", "claims": list(claims)}, strict=strict)
        agg = CA.consolidate_issues(issues)
        return {
            "checked": True,
            "claim_count": len(claims),
            **agg,
            "summary": CA.summary_counts(issues)["message"],
            "issues": [i.to_dict() for i in issues],
        }
    def _resolve_inside(self, rel: str) -> Path:
        """把库里的相对路径解析成工作区内的绝对路径，越界即拒绝。

        为什么连库里的路径也要核：`markdown_path` 是数据，数据可以被手工改坏。
        写文件前再核一次边界，成本是几行代码，收益是"沙箱边界不依赖于写入时的正确性"。
        """
        target = (self.workspace_root / str(rel)).resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError as e:
            raise DocumentError(f"markdown_path 越界：{rel!r} 不在工作区 {self.workspace_root} 内") from e
        return target
    def selftest(self) -> int:
        """就地冒烟自检：只做"构造断言 + 内存渲染"两步，不碰 store。

        真正被调用的只有这两处（与实现逐条对应）：
        1. `self.compose_claim(...)` 造一条断言 —— 覆盖断言构造那一道闸
           （它直接转发工具层的纯函数，不走 `self._call`、不碰注册表）；
        2. `self.render({...}, dependencies=None)` 把它渲染成 markdown
           —— `dependencies=None` 是有意的"没查"：连依赖表都不读，
           于是这次自检对 store 连一次读都没有，更不会写；
           最后核对渲染结果里出现"自检断言"与 "lit:0000"。

        它刻意不做的事（读的人不要以为已被覆盖）：
        - 不调 `build_document`：稿件落盘与随之而来的 schema 校验
          没有任何就地检查，那一路的回归只能靠测试与模块级 `_selftest()`；
        - 不写 store：不落 `documents`，也不 `register_dependency`。
          自检不该改用户的库 —— `Store` 是用户的数据，一次冒烟检查
          没有资格往里写（顺带它也才能在只读工作区里被调用）。

        返回 0（成功）/ 1（失败）。它与模块级 `_selftest()` 的分工：
        后者建临时工作区跑一遍完整流程（含 build_document 与落盘）并打印，
        前者是"就地可调用"的冒烟检查。
        """
        try:
            claim = self.compose_claim(
                "本自检断言仅用于验证构造管线。",
                citations=["lit:0000"],
                evidence_kind="heuristic",
                section="自检",
            )
            markdown = self.render(
                {
                    "doc_id": "0000",
                    "kind": "note",
                    "title": "自检稿件",
                    "claims": [claim],
                    "review_rounds": 0,
                    "status": "draft",
                },
                dependencies=None,
            )
            ok = "自检断言" in markdown and "lit:0000" in markdown
            self._emit(f"selftest：{'通过' if ok else '失败'}（渲染 {len(markdown)} 字符）")
            return 0 if ok else 1
        except Exception as e:  # noqa: BLE001 - 自检要给出结论，而不是把异常抛给调用方
            self._emit(f"selftest 失败：{type(e).__name__}: {e}")
            return 1


class AgentG(_ComposeClaim, _RegisterDependency, _BuildDocument, _Render, _RefreshMarkdown, _Revise, _Core):
    """撰写智能体。每个方法都能被独立调用与单测（与 `AgentD` 同一种形态），
    因此"写到一半被打断"可以从任意一步接着跑。
    """



def _selftest() -> int:
    # 运行方式：在 src/ 下执行 `python -m agentflow.agent_g`（或设 PYTHONPATH=src 后在任意目录执行）
    #
    # 自检刻意不依赖 agent_e / agent_f（它们由另一路并行开发）：
    # 实验证据直接从 `experiments` 表读，自己造两条。
    # 走完：compose_claim → build_document → register_dependency → render
    #      →（若 agent_h 可用）H 审校 → G revise → H 复审。
    import json
    import sys
    import tempfile

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 有些 stdout 替身没有 reconfigure；切编码失败不该让自检本身挂掉
        pass

    def line(msg: str = "") -> None:
        print(msg)

    line("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="agentflow-agentg-"))
    st = Store(root)
    st.init()
    line(f"[0] 临时工作区：{root}")

    # ---- 造数据：2 篇文献 + 1 条 formal 实验 + 1 条 numeric 实验
    with st.tx("literature", "experiments", actor="seed", note="fixture") as tx:
        for lid, title in (("0000", "Spec S̃_m = [−m, m]（companion book 引文）"), ("0001", "谱图与区间")):
            tx.upsert(
                "literature",
                S.Literature(
                    lit_id=lid, title=title, type="J", summary="s", path=None,
                    processed=True, added_at=S.now_iso(),
                ).to_dict(),
            )
        tx.upsert(
            "experiments",
            S.Experiment(
                experiment_id="0000",
                claim="Spec K(m) = [-m, m]",
                claim_key="SpecK(m)=[-m,m]",
                method="formal",
                evidence_kind="proof",
                result="supports",
                negation_kind="not_proved",
                # 输出必须是绑了被检查声明名的检查器诊断（`R2-AN-2` /
                # `R2b-agentg-1`）：从前这里写的是 `"Lean4: no goals"`，那种输出里
                # 没有声明名 ⇒ 审计判据（`verify.verify_all` 的 `selfreported_proof`）
                # 只能把这一行读成"自报的 proof"，而夹具本身就在演示那个形态。
                # 写成 `'<声明名>' does not depend on any axioms` 才是 Lean 真跑过的形态。
                verifier_output="'SpecK(m)=[-m,m]' does not depend on any axioms",
                # `evidence_kind="proof"` 时 schema 硬要求这一字段，且必须
                # 与本行的 `claim_key` 逐字相等（判据在 `schema.Experiment.validate`）：
                # 检查器输出必须绑定到它管的那个命题，否则"把 A 命题的输出贴到 B 命题上"
                # 在结构上合法。少了它自检块直接退出码 1
                # （`DEVELOPMENT.md` 的 §8.4「待办」已把这条登记为本文件的待修项。
                #  这里刻意只写小节名不写行号：行号在并行开发下几十分钟就漂，
                #  而小节名与符号名可核 —— `.noai-paths` 的维护纪律）。
                verifier_subject_key="SpecK(m)=[-m,m]",
                created_at=S.now_iso(),
            ).to_dict(),
        )
        tx.upsert(
            "experiments",
            S.Experiment(
                experiment_id="0001",
                claim="Spec K(m) ⊂ [-m, m]（数值抽样）",
                claim_key="SpecK(m) subset [-m,m]",
                method="numeric",
                evidence_kind="cross_check",
                result="supports",
                negation_kind="not_proved",
                created_at=S.now_iso(),
            ).to_dict(),
        )
    line("[1] 造数据：文献 2 篇、实验 2 条（1 条 formal/proof、1 条 numeric/cross_check）")

    # [1b] 夹具自己必须过审计：这条 formal/proof 行的 `verifier_output` 要能读出
    # 被检查的声明名，否则它是一个"自报的 proof"（`selfreported_proof`，`R2b-agentg-1`）。
    # 从前没有人跑这一步 —— `_selftest` 不调 `verify_all`、也没有任何测试调 `_selftest`，
    # 于是那条矛盾的夹具不会以任何红的方式出现。这里把它接上（fail-closed：报告不出
    # 就退出码 1，不是打印一行了事）。
    from ..verify import verify_all

    audit = verify_all(st)
    selfreported = [i for i in audit.issues if i.code == "selfreported_proof"]
    if selfreported:
        for i in selfreported:
            line(f"    [红] 自检夹具产出了自报的 proof：{i.table}:{i.row_id} {i.message[:120]}")
        line("SELF-CHECK FAILED（agent_g；夹具的 proof 行读不出依据）")
        return 1
    line("[1b] 审计读数：本自检夹具的 selfreported_proof 命中 = 0（proof 行的依据可读）")

    g = AgentG(st, config={"docs_subdir": "documents"}, log=None)
    # `names()` 是注册面（含 G 调不到的写侧工具），`call_surface("G")` 才是可调用面。
    line(f"[2] G 的可调用面（call_surface('G')）：{sorted(g.tools.call_surface('G'))}")
    line(f"    注册面（names()，含 G 调不到的工具）：{len(g.tools.names())} 个；"
         f"可调用面 {len(g.tools.call_surface('G'))} 个")

    line("[3] compose_claim：三条正向 + 三条负控")
    # `D-1`：proof 级断言必须给出一个盘上真的存在的落点
    # （`doc_tools.check_proofs` 会在 `build_document` 里按工作区根解析并 `is_file()`）。
    # 自检自己造一份最小 Lean 文件当落点 —— 不写它，自检会在第 [4] 步被自己的新判据拦下。
    proof_dir = root / "proofs"
    proof_dir.mkdir(parents=True, exist_ok=True)
    (proof_dir / "selftest.lean").write_text(
        "theorem selftest_proof : True := trivial\n", encoding="utf-8"
    )
    proof = g.compose_claim(
        "由形式化检查器核验：Spec K(m) = [−m, m]。",
        citations=["exp:0000", "lit:0000"],
        evidence_kind="proof",
        section="主要结果",
        claim_id="claim-1",
        proof_location="proofs/selftest.lean:1",
    )
    cross = g.compose_claim(
        "数值抽样在 10^4 个点上支持 Spec K(m) ⊆ [−m, m]。",
        citations=["exp:0001"],
        evidence_kind="cross_check",
        section="数值证据",
        claim_id="claim-2",
    )
    negative = g.compose_claim(
        "本项目未能证明定理对非交换环成立。",
        citations=["lit:0001"],
        evidence_kind="heuristic",
        section="开放问题",
        is_negative=True,
        negation_kind="not_proved",
        claim_id="claim-3",
    )
    line(f"    cross_check 自动带上的 disclaimer：{cross['disclaimer']!r}")
    line(f"    否定型断言的分类：{negative['negation_kind']!r}")
    for label, fn in (
        ("citations=[]", lambda: g.compose_claim("x", citations=[], evidence_kind="proof", section="s")),
        (
            "cross_check 正文写'已证明'",
            lambda: g.compose_claim("我们已证明 X", citations=["lit:0000"], evidence_kind="cross_check", section="s"),
        ),
        (
            "is_negative 但没给 negation_kind",
            lambda: g.compose_claim("X 不成立", citations=["lit:0000"], evidence_kind="heuristic", section="s", is_negative=True),
        ),
    ):
        try:
            fn()
            line(f"    ❌ 负控未触发：{label}")
            return 1
        except ValueError as e:
            line(f"    ✅ 负控触发 {label}：{str(e)[:78]}…")

    line("[4] build_document（写库 + 渲染 markdown）")
    doc = g.build_document(
        "paper",
        "K(m) 的谱刻画：一份带引用的稿件",
        claims=[proof, cross, negative],
        sections=[{"heading": "主要结果", "body": "…"}, {"heading": "数值证据", "body": "…"}],
        open_problems=["非交换环情形尚未处理"],
    )
    doc_id = doc["doc_id"]
    line(f"    doc_id={doc_id} markdown_path={doc['markdown_path']}")

    line("[5] register_dependency（closed 必须核到真实来源）")
    d1 = g.register_dependency(
        f"doc:{doc_id}#claim-1", "theorem", "companion book [6, Thm 6.5]",
        source_lit_id="0000", page_range=(45, 46), status="closed",
        quote="Spec S̃_m = [−m, m]",
    )
    d2 = g.register_dependency(
        f"doc:{doc_id}#claim-1", "dataset", "外部数据集（本项目拿不到）",
        status="external_unavailable", status_reason="该数据集需机构订阅，本项目不可得（已知边界）",
    )
    line(f"    dep:{d1['dep_id']} status={d1['status']}；dep:{d2['dep_id']} status={d2['status']}")
    try:
        g.register_dependency(
            f"doc:{doc_id}#claim-2", "theorem", "不存在的引文",
            source_lit_id="9999", status="closed",
        )
        line("    ❌ 负控未触发：closed 指向不存在的 lit_id")
        return 1
    except ValueError as e:
        line(f"    ✅ 负控触发（closed 指向不存在的 lit_id）：{str(e)[:80]}…")

    md_path = g.refresh_markdown(doc_id)
    text = Path(md_path).read_text(encoding="utf-8")
    line(f"[6] 重渲染（补上依赖表）：{md_path}（{len(text)} 字符 / {text.count(chr(10))} 行）")
    for marker in (DT.CROSS_CHECK_DISCLAIMER, "证据等级统计", "否定型结论分类", "依赖（FC-23", "外部不可得"):
        line(f"    含「{marker}」：{marker in text}")
    line("    —— 渲染片段 ——")
    for ln in text.splitlines()[:14]:
        line(f"    | {ln}")

    # ---- 与 H 的闭环（H 由同一份交付提供；缺席时如实说明，不静默跳过）
    line("[7] 闭环：H 审校 → G revise → H 复审")
    try:
        from ..agent_h import AgentH
    except Exception as e:  # noqa: BLE001
        line(f"    ⚠️ agent_h 不可用（{type(e).__name__}: {e}）⇒ 本节的闭环**未验证**")
        line("=" * 72)
        line("SELF-CHECK DONE（agent_g；闭环部分未验证）")
        return 0

    h = AgentH(st, config={"max_review_rounds": 2})
    r1 = h.review(doc_id)
    line(f"    H.review：verdict={r1['verdict']} error={r1['error_count']} warning={r1['warning_count']} "
         f"新增发现={len(r1['new_findings'])} 重复跳过={r1['duplicate_skipped']}")
    for f in r1["new_findings"]:
        line(f"      [{f['level']}] {f['kind']} @{f['target']}：{f['message'][:46]}；evidence={f['evidence'][:60]!r}")
    if r1["new_findings"]:
        fid = r1["new_findings"][0]["finding_id"]
        rv = g.revise(doc_id, fixed_findings=[fid], note="已按审校意见调整")
        line(f"    G.revise：review_rounds={rv['review_rounds']} status={rv['status']} "
             f"替换={rv['replaced_claim_ids']} 标记 fixed={rv['fixed_findings']}")
        claimed = next(r["status"] for r in st.rows("review_findings") if r["finding_id"] == fid)
        line(f"    G 自称已修 ⇒ finding 状态={claimed}（但那条依赖其实一个字没动）")
    v = h.verify_fixes(doc_id, round_no=2)
    line(f"    H.verify_fixes：verdict={v['verdict']} resolved={len(v['resolved'])} still_open={len(v['still_open'])} "
         f"未解决(error)={len(v['unresolved_findings'])}")
    if r1["new_findings"]:
        after = next(r for r in st.rows("review_findings") if r["finding_id"] == fid)
        line(f"    复审后 finding 状态={after['status']}（G 的 fixed 被作废：checks 仍然复现 ⇒ 重新打开），"
             f"resolution_note={after['resolution_note'][:60]!r}")
    line(f"    文档状态：{v['status']}；原因：{v['reason'][:150]}")
    line(f"[8] 最终统计：{json.dumps(st.stats()['documents'], ensure_ascii=False, default=str)} "
         f"{json.dumps(st.stats()['dependencies'], ensure_ascii=False, default=str)} "
         f"{json.dumps(st.stats()['review_findings'], ensure_ascii=False, default=str)}")

    line("=" * 72)
    line("SELF-CHECK DONE（agent_g）")
    return 0
