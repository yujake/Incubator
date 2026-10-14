"""角色 H 的实现核心（`goal-7f5116c1` M6）：其余成员 + 把动作 mixin 装起来。

动作方法一个都没留在这里 —— 它们各自在 `agent_h/<动作>.py`。
这一层与各动作文件共用 `_support.py`（模块级 helper 与常量）。
"""
from __future__ import annotations

from .. import conceptrows as CR   # 并表过渡期：夹具/自检走这一处写口
from ._support import Any, CROSS_CHECK_DISCLAIMER, Callable, Mapping, Path, RV, ReviewError, S, SIDE_EFFECTS_WRITE, Store, ToolRegistry, _H_READONLY_SIDE_EFFECTS, _H_WRITABLE_TOOLS, _inject_raw_document, _seed_document, install_h_tools
from .review import _Review
from .verify_fixes import _VerifyFixes
from .list_findings import _ListFindings
from .review_report import _ReviewReport
from .judge_quote_semantics import _JudgeQuoteSemantics


class _Core:
    def __init__(
        self,
        store: Store,
        *,
        config: Mapping[str, Any] | None = None,
        log: Callable[[str], None] | None = None,
        tools: ToolRegistry | None = None,
        writers: ToolRegistry | None = None,
        # LLM 判定缝（`draft/30` §T0-8）：默认 None = 不接线 ⇒ 本角色一个 LLM 调用都不发。
        # 判定必须走 `judge.judge_json`（唯一缝协议），失败落 `judge_*` 词表，
        # 绝不许折成"没找到"。本批只插插座，接线在各条目的伪代码下进行。
        llm: Any | None = None,
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = str(self.cfg.get("actor", "agent-H"))
        self.llm = llm
        self.workspace_root = Path(store.root).resolve()
        self.log = log
        self.logs: list[str] = []
        self.tool_calls: list[dict] = []

        #: 复审轮数上限。必须有上限：没有它，"error 一直不修"会变成一个
        #: 无限循环（FC-18 的同族要求）。到顶不是继续跑，而是标 unresolved_review 交人。
        self.max_review_rounds = int(self.cfg.get("max_review_rounds", 2))
        if self.max_review_rounds < 1:
            raise ReviewError(f"max_review_rounds 至少为 1，收到 {self.max_review_rounds}")

        self.tools = tools if tools is not None else install_h_tools(self.store)
        # ---- 装配期断言（FC-03 的形态）：拿不到合规的注册表就拒绝启动。
        # 审校者手里若有一把能改稿的刀，整套"发现/掩盖可区分"的设计就当场失效，
        # 而它不会报任何错 —— 所以这里必须 fail-closed。
        bad = [t for t in self.tools.describe() if t["side_effect"] not in _H_READONLY_SIDE_EFFECTS]
        if bad:
            raise ReviewError(
                "H 的工具栏里出现了非只读工具："
                + "、".join(f"{t['name']}({t['side_effect']})" for t in bad)
                + "。审校者必须只能提发现，不能改稿 —— 若它能改，"
                "'发现问题'与'掩盖问题'在结构上就无法区分"
            )

        self.writers = writers if writers is not None else ToolRegistry(name="agent-H:writers")
        # ---- 落库代理绑定角色（`P-14`）：`self.writers` 代表 H，
        # 且它的可调用面就是 `READONLY_CALL_EXCEPTIONS["H"]` 那张表。
        # 不绑的话 `_writer` 的每次 `call` 都会被"调用方没声明角色"拒掉 ——
        # 那会把 H 写审校发现与报告的能力一起砍掉（`_H_WRITABLE_TOOLS` 的落点也就没了）。
        if self.writers.bound_role is None:
            self.writers.bound_role = "H"
        if writers is None:
            # `draft/28` §196：有 `llm` 就把它接成语义判据（"结论是否强于引文"），
            # 一路传给 `review.review_document` / `review.review_report`。
            # 没有 `llm` ⇒ 传 None ⇒ 报告里那一格是 `checked=False` + 逐字理由（没查），
            # 不是"判过、没问题"。默认路径（`llm=None`）一个 LLM 调用都不发。
            judge = None
            if self.llm is not None:
                from .. import judges as JG

                judge = JG.semantic_judge_for(self.llm)
            RV.register(self.writers, store=self.store, include_writers=True, actor=self.actor,
                        semantic_judge=judge)
        # ---- 落库代理的装配期断言（本次审计补上的缺口）。
        #
        # `tools` 上面已有一条 fail-closed 断言，而 `writers` 作为构造参数此前
        # 完全没有校验 —— 传进来一个带 `table.update` 的注册表，"落点被钉死
        # 在 review_findings 与 documents.status 上"就只剩一句注释。
        # （上面那条断言查的是 `self.tools`，结构上覆盖不到 `self.writers`。）
        # 判据复用工具层的 `SIDE_EFFECTS_WRITE`，不另写一份"哪些算写"。
        bad_writers = [
            t["name"]
            for t in self.writers.describe()
            if t["side_effect"] in SIDE_EFFECTS_WRITE and t["name"] not in _H_WRITABLE_TOOLS
        ]
        if bad_writers:
            raise ReviewError(
                "H 的落库代理里出现了不该有的写工具："
                + "、".join(bad_writers)
                + f"。只允许 {_H_WRITABLE_TOOLS} —— 否则 H 就能改稿，"
                "'发现问题'与'掩盖问题'在结构上再次无法区分"
            )
    def _emit(self, message: str, **extra: Any) -> None:
        line = message if not extra else f"{message} {extra}"
        self.logs.append(line)
        if callable(self.log):
            try:
                self.log(line)
            except Exception:  # noqa: BLE001 - 日志钩子坏了不该打断审校
                pass
    def _writer(self, name: str, /, **params: Any) -> dict:
        #: 这张注册表在 `__init__` 里已绑定 `bound_role="H"`（`P-14` 的调用期判据），
        #: 所以这里不必逐次传 `role=` —— 逐次传反而会让"它到底代表谁"有两个来源。
        res = self.writers.call(name, **params)
        self.tool_calls.append({"tool": name, "ok": res.ok, "error": res.error})
        if not res.ok:
            # 不可静默：审校动作没做成，调用方必须知道（否则会以为"审过了、没问题"）。
            raise ReviewError(f"{name} 调用失败：{res.error}")
        return res.data
    def selftest(self) -> int:
        """对当前 store 做一次最小自检：工具面是否只读、发现是否可写。

        返回 0（成功）/ 1（失败）。
        """
        try:
            surface = self.tools.describe()
            ok_surface = bool(surface) and all(
                t["side_effect"] in _H_READONLY_SIDE_EFFECTS for t in surface
            )
            rows = self.store.rows("documents")
            ok_write = True
            if rows:
                data = self.review(str(rows[0].get("doc_id")), dependencies=None)
                ok_write = data.get("checked") is True and data.get("dep_check", {}).get("checked") is False
            ok = ok_surface and ok_write
            self._emit(
                f"selftest：{'通过' if ok else '失败'}（自由工具箱 {len(surface)} 个只读工具；"
                f"拒绝的写工具 {len(getattr(self.tools, 'refused_write_tools', []))} 个）"
            )
            return 0 if ok else 1
        except Exception as e:  # noqa: BLE001 - 自检要给出结论，而不是把异常抛给调用方
            self._emit(f"selftest 失败：{type(e).__name__}: {e}")
            return 1


class AgentH(_Review, _VerifyFixes, _ListFindings, _ReviewReport,
             _JudgeQuoteSemantics, _Core):
    """审校智能体。

    两个注册表是刻意分开的，它们的区别就是"H 只读"这条约束本身：

    - `self.tools`：H 的自由工具箱（只读）。H 可以任意反复调用，不需要审批。
    - `self.writers`：H 的落库代理（`write_local`）。只在固定流程里被调用，
      落点被钉死在 `review_findings` 与 `documents.status` 上。
    """



def _selftest() -> int:
    # 运行方式：在 src/ 下执行 `python -m agentflow.agent_h`（或设 PYTHONPATH=src 后在任意目录执行）
    import json
    import sys
    import tempfile

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 有些 stdout 替身没有 reconfigure；切编码失败不该让自检本身挂掉
        pass

    print("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="agentflow-agenth-"))
    st = Store(root)
    st.init()
    print(f"[0] 临时工作区：{root}")

    # ---- 知识表（用于"运行期只读"的逐字节比对）
    with st.tx(*CR.tables_for_concept_write("relations", "literature"),
               actor="seed", note="fixture") as tx:
        CR.upsert_legacy_shaped(tx, S.Concept(concept_id="0000", name="谱", definition="d", created_at=S.now_iso(), updated_at=S.now_iso()).to_dict())
        CR.upsert_legacy_shaped(tx, S.Concept(concept_id="0001", name="区间", definition="d", created_at=S.now_iso(), updated_at=S.now_iso()).to_dict())
        tx.upsert(
            "literature",
            S.Literature(lit_id="0000", title="Spec S̃_m", type="J", summary="s", path=None, processed=True, added_at=S.now_iso()).to_dict(),
        )
        tx.upsert(
            "relations",
            S.Relation(
                relation_id="0000", concept_ids=["0000", "0001"], description="谱落在区间内",
                lit_id="0000", page_range=S.PageRange(12, 13, "pp. 12-13"), quote="Spectrum lies in the interval",
                statement="谱落在区间内", concept_group_key="0000|0001", dedup_key="k0", status="active",
                quote_verified=True, created_at=S.now_iso(),
            ).to_dict(),
        )
    print("[1] 造数据：概念 2 个、文献 1 篇、关系 1 条")

    # ---- 干净稿件（防误伤，schema 合法且审校也该干净）
    #
    # `evidence_kind` 是 `cross_check` 而不是 `proof`：这条断言的引文只有
    # `rel:0000`（一条关系）与 `lit:0000#p.12-13`（一页文献），没有形式化检查器
    # 参与过。标成 `proof` 是误标，而 `D-1` 的写入期判据（`doc_tools.check_proofs`）
    # 会在改写这条稿件的路径上拒绝它 —— 自检第 [7] 步就是这么红的。
    # 降级之后它仍然是"干净稿件"：审校判 `accepted`、`error=0`（见本自检第 [4] 步）。
    # `disclaimer` 必须跟着填：`cross_check` 的「不构成证明」声明是结构强制的。
    clean = _seed_document(
        st,
        doc_id="0000",
        claims=[
            {
                "claim_id": "claim-1", "section": "主要结果", "text": "谱落在区间内。",
                "evidence_kind": "cross_check", "citations": ["rel:0000", "lit:0000#p.12-13"],
                "is_negative": False, "negation_kind": None,
                "disclaimer": CROSS_CHECK_DISCLAIMER,
            }
        ],
    )
    # ---- 第二份：schema 合法但审校不合规（把 cross_check 说成"已证明"）。
    # 它存在的意义：坏数据并不总能被 schema 拦住，而也只有这样的稿件才允许
    # 状态真正被写进 unresolved_review（schema 不合法的稿件连状态都写不进去）。
    _seed_document(
        st,
        doc_id="0002",
        claims=[
            {
                "claim_id": "claim-1", "section": "数值证据",
                "text": "数值抽样支持该结论，因此我们已证明它成立。",
                "evidence_kind": "cross_check", "citations": ["lit:0000"],
                "is_negative": False, "negation_kind": None,
                "disclaimer": CROSS_CHECK_DISCLAIMER,
            }
        ],
    )
    # ---- 依赖：一条已知边界（external_unavailable）+ 一条悬空
    with st.tx("dependencies", actor="seed", note="fixture") as tx:
        for dep_id, status, reason in (
            ("0000", "external_unavailable", "companion book 不在本项目可得范围内（已知边界）"),
            ("0001", "dangling", "尚未找到来源"),
        ):
            row = S.Dependency(
                dep_id=dep_id, used_by="doc:0001#claim-9", kind="theorem",
                label=f"依赖 {dep_id}", status=status, status_reason=reason,
                created_at=S.now_iso(),
            )
            row.validate()
            tx.upsert("dependencies", row.to_dict())
    print("[2] 稿件 2 份（干净 1 份、把 cross_check 说成证明的 1 份）、依赖 2 条")

    h = AgentH(st, config={"max_review_rounds": 2})
    print(f"[3] H 的自由工具箱（{len(h.tools)} 个，全部应为 none/read）：")
    for t in h.tools.describe():
        print(f"      {t['name']:<28} side_effect={t['side_effect']}")
    refused = getattr(h.tools, "refused_write_tools", [])
    print(f"    被**显式拒绝**的写工具 {len(refused)} 个（H 若持有它们就能改稿）：")
    for r in refused[:8]:
        print(f"      ✗ {r['name']}（{r['side_effect']}）")

    print("[4] 干净稿件：防误伤（好数据必须过）+ 运行期只读的可核对形式")
    # 逐字节比对的取样面按当前 schema 取：S1r 并表之后概念行住 `statements.json`
    # （`concepts.json` 已退役、盘上不再有那个文件 ⇒ 写死它会当场 FileNotFoundError）。
    before = {n: (st.data / n).read_bytes()
              for n in ("statements.json", "relations.json", "literature.json")}
    docs_before = json.loads((st.data / "documents.json").read_text(encoding="utf-8"))
    r0 = h.review("0000", dependencies=[])
    docs_after = json.loads((st.data / "documents.json").read_text(encoding="utf-8"))
    max_round = docs_before["rows"][0].get("review_rounds")
    print(f"    verdict={r0['verdict']} error={r0['error_count']} warning={r0['warning_count']} "
          f"status={r0['status']} dep_checked={r0['dep_check']['checked']}")
    same = all((st.data / n).read_bytes() == before[n] for n in before)
    changed = []
    for rb, ra in zip(docs_before["rows"], docs_after["rows"]):
        diff = sorted({k for k in set(rb) | set(ra) if rb.get(k) != ra.get(k)})
        if diff:
            changed.append((rb.get("doc_id"), diff))
    print(f"    知识表逐字节不变={same}；documents.json 变化点={changed}（应只有 status）")
    if r0["error_count"] or r0["verdict"] != "accepted" or r0["status"] != "accepted":
        print("    ❌ 干净稿件被误伤（或没有被接受）")
        return 1
    if not same or changed != [("0000", ["status"])]:
        print("    ❌ 运行期只读被破坏（或变化点不止 status）")
        return 1
    _ = max_round

    print("[5] 终止性 + 状态落地（schema 合法但把 cross_check 说成证明）")
    b0 = h.review("0002")
    print(f"    review：verdict={b0['verdict']} error={b0['error_count']} status={b0['status']} "
          f"status_updated={b0['status_updated']}")
    for f in b0["new_findings"]:
        print(f"      [{f['level']}] {f['kind']} @{f['target']}：{f['message'][:40]}；evidence={f['evidence'][:70]!r}")
    b1 = h.verify_fixes("0002", round_no=2)
    now_status = next(r["status"] for r in st.rows("documents") if r["doc_id"] == "0002")
    print(f"    不修 → 复审 verdict={b1['verdict']} 未解决(error)={len(b1['unresolved_findings'])} 库中状态={now_status}")
    if b1["verdict"] != "unresolved_review" or now_status != "unresolved_review" or not b1["unresolved_findings"]:
        print("    ❌ 未到 unresolved_review（或状态没落地 / 未解决项被隐藏）")
        return 1
    for f in b1["unresolved_findings"]:
        print(f"      未解决：✗ {f['finding_id']} {f['kind']} @{f['target']} level={f['level']}")
    # 改稿是 G 的职责，不是 H 的。
    #
    # 这里此前直接 `st.tx("documents")` 改 `row["claims"]`（actor 写成 "fake-G"）。
    # 那是本模块最不该出现的东西：一份明文可抄的"绕过 H 只读"的写法，
    # 就写在"证明 H 只读"的那个文件里。FC-27 的教训正是"测试全绿、上线即越权" ——
    # 一句 `row["claims"] = ...` 加一个自嘲的 actor 名，足够让任何人以为这条约束
    # 只是建议。改成调用真正的改写方（`AgentG.revise`）：自检照样走完闭环，
    # 而 agent_h.py 里再也没有任何一处碰过 `documents.claims`。
    try:
        from ..agent_g import AgentG

        AgentG(st, config={"docs_subdir": "documents"}).revise(
            "0002",
            new_claims=[dict(c) for c in clean["claims"]],
            note="自检：由 G（稿件的所有者）按审校意见改稿",
        )
    except Exception as e:  # noqa: BLE001 - 拿不到 G 时必须显式失败，不许静默跳过
        print(f"    ❌ 拿不到 G（{type(e).__name__}: {e}）⇒ '修好后复审'这一步**未验证**")
        return 1
    b2 = h.verify_fixes("0002", round_no=3)
    print(f"    修好后 → 复审 verdict={b2['verdict']} resolved={len(b2['resolved'])} "
          f"still_open={len(b2['still_open'])} 库中状态={b2['status']}")
    # ---- `R-59`（`draft/28` §161.4 的口径 ②）之后的期望值。
    #
    # 本自检原来断言 `b2["status"] == "accepted"` —— 那正是被修掉的那个形态：
    # G 改稿之后内容哈希变了，而签名还钉着旧版本，复审却把状态置回 accepted
    # ⇒ `verify_all` 报 `stale_signature`（"改稿之后旧审批不许沿用"）。
    # 现在 `verify_fixes` 只在"台账里有签名钉住当前这一版"时才置 accepted；
    # 否则置 `in_review` 并在 reason 里点名要重新 review。
    #
    # 所以这一步拆成两条更强的断言：
    #   ① 复审判 accepted（判断本身没变），但状态停在 `in_review` 且理由写明；
    #   ② 再走一次 `review`（H 的唯一签发入口）⇒ 状态 accepted 且签名钉在这一版上。
    # ② 此前没有任何地方验过，而它恰是"接受 = 有一次针对这一版的审+签"的机器判据。
    if b2["verdict"] != "accepted" or b2["status"] != "in_review":
        print("    ❌ 修好后应判 accepted、状态停在 in_review（等一次针对这一版的审+签）")
        return 1
    if "不置 `accepted`" not in str(b2.get("reason") or ""):
        print("    ❌ 复审理由里没有逐字写明'不置 accepted'的原因 ⇒ 读者看不出状态为什么没回去")
        return 1
    from .. import signatures as _SIG

    b3 = h.review("0002", dependencies=[])
    _doc2 = next(r for r in st.rows("documents") if r["doc_id"] == "0002")
    _recs, _bad = _SIG.read_ledger(_SIG.ledger_path(root))
    _pinned = _SIG.signed_revision(_doc2, _recs) is not None
    print(f"    重新审一次 → verdict={b3['verdict']} 状态={b3['status']} "
          f"签名钉住这一版={_pinned}")
    if b3["verdict"] != "accepted" or b3["status"] != "accepted":
        print("    ❌ 重新审一次应判 accepted 并把状态落到 accepted")
        return 1
    if not _pinned:
        print("    ❌ 接受了却没有签名钉在当前这一版上 ⇒ 旧审批被沿用了（R-59 的形态）")
        return 1

    # ---- 最后才把"schema 不合法的坏行"注入盘上。
    # 顺序很重要：`store.tx` 提交时会校验整张表，一条坏行会让之后所有对
    # documents 的写入都失败。这本身就是一条值得展示的事实 —— 而 H 正是要在
    # 这种局面下仍然能把发现落库（发现写的是另一张表）。
    #
    # 这里写成一整行字面量，而不是"拿一份合法稿件把它的 claims 换掉"。
    # 后者（`bad = dict(clean); bad["claims"] = ...`）在源码里与
    # "绕过 H 只读、偷偷改稿"长得一模一样 —— 而这个文件是用来证明 H 只读的。
    # 我们现在要造的是"一份坏输入喂给 H"，不是"改动一行已有稿件"，
    # 字面量把这件事写清楚；同时 `tests/test_core_audit_efgh.py` 会扫源码，
    # 断言本文件里一处 `X["claims"] = ...` 都没有。
    bad = {
        "doc_id": "0001",
        "kind": "paper",
        "title": "自检坏稿件（绕过 schema 直接改盘）",
        "markdown_path": None,
        "sections": [],
        "claims": [
            {"claim_id": "claim-9", "section": "x", "text": "这是一条没有任何引用的断言。",
             "evidence_kind": "heuristic", "citations": [], "is_negative": False,
             "negation_kind": None, "disclaimer": ""},
            {"claim_id": "claim-10", "section": "x", "text": "该推广不成立。",
             "evidence_kind": "heuristic", "citations": ["lit:0000"], "is_negative": True,
             "negation_kind": None, "disclaimer": ""},
        ],
        "open_problems": [],
        "status": "draft",
        "review_rounds": 0,
        "created_at": S.now_iso(),
        "updated_at": S.now_iso(),
    }
    _inject_raw_document(st, bad)

    print("[6] 坏稿件（绕过 schema 直接改盘）：无引用 / 否定未分类 / 依赖分级")
    r1 = h.review("0001")
    print(f"    verdict={r1['verdict']} error={r1['error_count']} warning={r1['warning_count']} "
          f"status_updated={r1['status_updated']}")
    if not r1["status_updated"]:
        print(f"    （状态未更新，**如实记录**而不是假装成功：{str(r1['status_error'])[:90]}）")
    for f in r1["new_findings"]:
        print(f"      [{f['level']:^7}] {f['kind']:<22} @{f['target']:<10} {f['message'][:34]}")
        print(f"                 evidence = {f['evidence'][:88]}")
    f_rows = [f for f in st.rows("review_findings") if str(f["doc_id"]) == "0001"]
    lvl = {f["target"]: f["level"] for f in f_rows if f["kind"] == "dangling_dep"}
    uv = next((f for f in f_rows if f["kind"] == "unsupported_claim"), None)
    print(f"    依赖分级（FC-13）：external_unavailable={lvl.get('0000')}（应为 warning）、"
          f"dangling={lvl.get('0001')}（应为 error）")
    print(f"    unsupported_claim 的 evidence（必须含实际值）：{str(uv and uv['evidence'])[:80]!r}")
    if lvl.get("0000") != "warning" or lvl.get("0001") != "error" or uv is None or "citations" not in uv["evidence"]:
        print("    ❌ 依赖分级或发现证据不对")
        return 1

    print("[7] 去重：同一份坏稿件再审一次")
    n_before = len(st.rows("review_findings"))
    r3 = h.review("0001")
    n_after = len(st.rows("review_findings"))
    print(f"    新增={len(r3['new_findings'])} 重复跳过={r3['duplicate_skipped']} "
          f"finding 行数 {n_before} → {n_after}")
    if r3["duplicate_skipped"] <= 0 or n_after != n_before:
        print("    ❌ 去重失效")
        return 1

    print("[8] 复审：error 一直不修 ⇒ 到轮数上限必须置 unresolved_review 并列出未解决项")
    v1 = h.verify_fixes("0001", round_no=2)
    print(f"    verdict={v1['verdict']} resolved={len(v1['resolved'])} still_open={len(v1['still_open'])} "
          f"未解决(error)={len(v1['unresolved_findings'])} status={v1['status']}"
          + ("" if v1["status_updated"] else f"（状态未更新：{str(v1['status_error'])[:70]}）"))
    if v1["verdict"] != "unresolved_review" or not v1["unresolved_findings"]:
        print("    ❌ 到轮数上限仍未解决时应置 unresolved_review 并**列出**未解决发现")
        return 1

    print("[9] 三态：显式 dependencies=None ⇒ 依赖闭合**没查**，不许判 accepted")
    r2 = h.review("0002", dependencies=None)
    print(f"    dep_check.checked={r2['dep_check']['checked']} verdict={r2['verdict']} status={r2['status']}")
    print(f"    reason={r2['reason'][:170]}")
    if r2["dep_check"]["checked"] is not False or r2["verdict"] == "accepted":
        print("    ❌ 把'没查'当成了'依赖都闭合'")
        return 1

    print("=" * 72)
    print("SELF-CHECK DONE（agent_h）")
    return 0
