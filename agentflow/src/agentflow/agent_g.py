"""智能体 G：论文撰写。

## G 到底在做什么

把 D（研究结论）/ F（攻坚过程）/ E（实验证据）的结论汇编成一份
每条断言都带引用的稿件，并把它渲染成人能读的 markdown。

G 的产出被两条结构性约束钉死：

1. 无引用的断言不可能进稿。这不是文风要求 —— 数学断言的价值完全取决于
   "它来自哪里"，允许无引用断言就等于允许一份"听起来很合理"的文本。
   `schema.Document.validate` 是最后一道闸，G 侧的第一道闸在
   :meth:`AgentG.compose_claim` / :meth:`AgentG.build_document`：
   在构造断言的那一刻就报错，因为那时手里还拿着"是哪一句话"。
2. 证据等级不许被夸大。`cross_check`（数值/穷举交叉验证）的断言由结构
   强制带上"不构成证明"的声明（FC-22），"已证明"这类措辞出现在非 proof 断言里
   直接抛错。

## G 与 H 的分工（为什么这个分工是结构性的，而不是礼貌性的）

H 提发现（`review_findings`），G 改稿（`documents`）。G 只能改自己的稿：

- 改稿：`revise()` 只动 `documents.claims/status/review_rounds`；
- 对 H 的发现，G 只能改它的 `status` 与 `resolution_note`，
  `kind/level/target/evidence/message` 一个字都不许动 —— 那是 H 当初的判断依据；
- 而且 G 自称"已修复"不作数：H 的 `verify_fixes` 会重跑检查，
  仍复现就把发现重新打开（`review_tools._apply_finding_status`）。

## 工具面（FC-06：角色即权限面）

`install_g_tools()` 按角色 `"G"` 装配。写工具（`doc.build_document` /
`doc.register_dependency`）的角色被收窄到 `("G",)`：H 拿不到它们，
于是"发现问题的人"与"改写稿件的人"在结构上不是同一个。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import claimanatomy as CA
from . import schema as S
from . import signatures as SIG
from .store import Store
from .tools import build_registry
from .tools import doc_tools as DT
from .tools.base import ToolRegistry

__all__ = ["AgentG", "DocumentError", "install_g_tools"]


class DocumentError(ValueError):
    """稿件层面的问题（稿件不存在 / 发现不属于本稿 / 工具调用失败）。

    继承 `ValueError`：调用方无论是"参数拿错了"还是"数据不合规"，
    处置都一样 —— 立刻失败并说清是哪一件。不发明第二个异常体系。
    """


#: 默认值哨兵（沿用 `agent_d._UNSPECIFIED` 的用法）：
#: 不传 = "自己去库里读依赖"；显式传 `None` = "调用方没有依赖清单 ⇒ 没查"。
#: 「没查」与「查了、没有依赖」必须能分开（FC-01 三态纪律）。
_UNSPECIFIED: Any = object()


# ---------------------------------------------------------------- 工具装配


def install_g_tools(
    store: Store,
    *,
    workspace_root: str | Path | None = None,
    registry: ToolRegistry | None = None,
) -> ToolRegistry:
    """装配 G 的工具栏。

    为什么按角色装配（`build_registry(...).scoped_to("G")`）而不是手工挑几个工具：
    角色即权限面（FC-06），装配结果必须可枚举、可比对；手工挑会在"新增工具时忘了
    给 G"这种地方静默漏水。

    「注册面」与「可调用面」是两件事，混起来会多算工具（`R7-AN-2` 的教训）：
    `scoped_to("G")` 给的是同一个注册表的视图，它仍然登记全部 spec
    （`names()` 是全集，含 G 根本调不到的写侧工具）；"G 到底能调什么"必须问
    `call_surface("G")` 或 `for_role("G")` —— 实测两者相等。
    `build_for_role` 那条老路会先把 spec 裁成子表（于是 `names()` 恰好等于工具面），
    代价是装配期的属性（FC-17 的 `default_budget` / `default_spill_root`、`P-14` 的
    `bound_role`）静默留空 —— 所以这里走 `scoped_to`，方向是拿回那两格，
    不是放宽权限面。

    为什么还要检查 `doc.*` 是否在里面：装配会容忍模块缺失
    （并行开发的现实），而 G 没有 doc 工具就什么也做不了。这种降级必须
    显式补上并留痕，而不是让 G 悄悄少一只手（FC-08：不得静默降级为空）。
    """
    root = Path(workspace_root).resolve() if workspace_root else Path(store.root).resolve()
    if registry is not None:
        reg = registry
    else:
        # `scoped_to` 不裁 spec 表（`names()` 仍是全集），`build_for_role` 会裁成子表
        # （`names()` 就等于工具面）。这里要的是 `build_registry` 的完整装配：FC-17 的
        # 上下文预算（`default_budget` / `default_spill_root`）与 `P-14` 的
        # `bound_role="G"` 跟着过来，走 `build_for_role` 那两格会静默留空。
        # G 只通过 `self.tools.call(...)` 用工具，没有绑定角色的注册表会让每次调用都被拒。
        # "G 到底能调什么"由 `call_surface("G")` / `for_role("G")` 回答，不是 `names()`。
        reg = build_registry(store=store, workspace_root=root).registry.scoped_to("G")
    if not any(n.startswith("doc.") for n in reg.names()):
        DT.register(reg, store=store, root=root, workspace_root=root)
        setattr(reg, "doc_fallback_reason", "这次 scoped_to('G') 装配的结果里没有任何 doc.* 工具")
    if reg.bound_role is None:
        reg.bound_role = "G"
    return reg


# ---------------------------------------------------------------- AgentG


class AgentG:
    """撰写智能体。每个方法都能被独立调用与单测（与 `AgentD` 同一种形态），
    因此"写到一半被打断"可以从任意一步接着跑。
    """

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

    # ------------------------------------------------------------ 小工具

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

    # ------------------------------------------------------------ 构造断言

    def compose_claim(
        self,
        text: str,
        *,
        citations: Sequence[str],
        evidence_kind: str,
        section: str,
        is_negative: bool = False,
        negation_kind: str | None = None,
        claim_id: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        proof_location: str | None = None,
        numeric_evidence: Mapping[str, Any] | None = None,
        counterexamples: Sequence[Any] | None = None,
        frozen: bool = False,
        freeze_reason: str = "",
        allowed_use: str | None = None,
        scope_caveat: str = "",
        revision_hash: str = "",
        errata_ids: Sequence[str] | None = None,
    ) -> dict:
        """构造一条合规断言（转发 `doc_tools.compose_claim`）。

        判据只有一份：这里不重新实现检查，直接复用工具层的纯函数 ——
        两套判据必然漂移，而漂移的后果是"G 认为合规、H 认为违规"这种
        没有任何报错的静默分裂。

        委托给工具层而不是直接 import 一个私有实现，也让"G 与 LLM 用同一套构造入口"
        成为事实：`doc.compose_claim` 工具最终调的就是这个函数。

        ## §8.3 的生命周期字段（本轮新增，全部可选）

        `kind` / `status` / `proof_location` / `numeric_evidence` /
        `counterexamples` / `frozen`+`freeze_reason` / `allowed_use` /
        `scope_caveat` / `revision_hash` / `errata_ids`。

        不给就是不写（不是写一个假默认）：`status='验'` 与"没有 `status`"
        是两件事，前者是"这条断言当前只被数值验过"，后者是"这条断言的生命周期
        还没被登记" —— 把后者悄悄当成前者，正是 `DEVELOPMENT.md` §3 纪律 1
        说的那个坑（"下游把'我们没查'读成了'查了没有'"）。
        """
        return DT.compose_claim(
            text,
            citations=citations,
            evidence_kind=evidence_kind,
            section=section,
            is_negative=is_negative,
            negation_kind=negation_kind,
            claim_id=claim_id,
            kind=kind,
            status=status,
            proof_location=proof_location,
            numeric_evidence=numeric_evidence,
            counterexamples=counterexamples,
            frozen=frozen,
            freeze_reason=freeze_reason,
            allowed_use=allowed_use,
            scope_caveat=scope_caveat,
            revision_hash=revision_hash,
            errata_ids=errata_ids,
        )

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

    # ------------------------------------------------------------ 依赖（FC-23）

    def register_dependency(
        self,
        used_by: str,
        kind: str,
        label: str,
        *,
        source_lit_id: str | None = None,
        source_experiment_id: str | None = None,
        page_range: Any = None,
        quote: str = "",
        status: str = "dangling",
        status_reason: str = "",
    ) -> dict:
        """登记外部依赖（转发 `doc.register_dependency`，第一道闭合闸在工具层）。

        `status="closed"` 时会用真实数据核 `literature`/`experiments` 表：
        schema 只能查"字段非空"，查不出"这个 lit_id 根本不存在"。
        引用一篇不存在的文献，就是把外部结论当成了自己的结论。
        """
        data = self._call(
            "doc.register_dependency",
            used_by=used_by,
            kind=kind,
            label=label,
            source_lit_id=source_lit_id,
            source_experiment_id=source_experiment_id,
            page_range=list(page_range) if isinstance(page_range, (list, tuple)) else page_range,
            quote=quote,
            status=status,
            status_reason=status_reason,
        )
        self._emit(f"登记依赖 dep:{data.get('dep_id')} status={data.get('status')}")
        return data

    # ------------------------------------------------------------ 落库

    def build_document(
        self,
        kind: str,
        title: str,
        *,
        claims: Sequence[Mapping[str, Any]],
        sections: Sequence[Mapping[str, Any]] | None = None,
        open_problems: Sequence[str] | None = None,
        out_path: str | Path | None = None,
    ) -> dict:
        """写一行 `documents` 并把 markdown 渲染到工作区内（转发 `doc.build_document`）。

        `out_path=None` 时用 `<workspace_root>/<docs_subdir>/<doc_id>.md`。
        给了 `out_path` 就必须落在工作区内：越界一律 `ValueError`，
        不许"写到外面再警告" —— 允许一次越界就等于承认沙箱边界可以被绕开。

        渲染是无条件的（不是"给了 out_path 才渲染"）：`markdown_path` 是
        FC-02 追溯链的一环，稿件必须有一个能被人打开的落点，否则
        "H 审的是哪个版本"无法回答。
        """
        data = self._call(
            "doc.build_document",
            kind=kind,
            title=title,
            claims=[dict(c) for c in claims],
            sections=[dict(s) for s in (sections or [])] or None,
            open_problems=[str(x) for x in (open_problems or [])] or None,
            out_path=str(out_path) if out_path is not None else None,
        )
        self._emit(f"写出稿件 doc:{data.get('doc_id')} → {data.get('markdown_path')}")
        return data

    # ------------------------------------------------------------ 渲染

    def render(self, doc: Mapping[str, Any], *, dependencies: Any = _UNSPECIFIED) -> str:
        """渲染 markdown（转发 `doc_tools.render_markdown`）。

        风格沿用 `agent_d.write_report`：中文、表格优先、每条断言带代号。
        `dependencies` 不传 = 自己去库里读该稿件的依赖；显式传 `None` = "没查"
        （渲染结果会如实写"未提供"，而不是写"0 条"）。
        """
        deps: Any = dependencies
        if deps is _UNSPECIFIED:
            doc_id = str(doc.get("doc_id") or "")
            deps = DT.dependencies_for_doc(self.store.rows("dependencies"), doc_id)
        elif deps is not None:
            deps = [dict(d) for d in deps]
        return DT.render_markdown(doc, dependencies=deps)

    def refresh_markdown(self, doc_id: str) -> str | None:
        """把稿件的 markdown 文件按库里当前的数据重画一遍（不改任何数据行）。

        为什么需要它：依赖是稿件写完之后才登记的（`used_by="doc:0001#claim-1"`
        必须等 doc_id 存在），而渲染层要把依赖表画出来。没有这一步，
        盘上的 markdown 会永远显示"0 条依赖"——一份与库不一致的稿件。
        """
        doc = next(
            (r for r in self.store.rows("documents") if str(r.get("doc_id")) == str(doc_id)), None
        )
        if doc is None:
            raise DocumentError(f"稿件 {doc_id} 不存在")
        rel = doc.get("markdown_path")
        if not rel:
            return None
        target = self._resolve_inside(rel)
        deps = DT.dependencies_for_doc(self.store.rows("dependencies"), str(doc_id))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DT.render_markdown(doc, dependencies=deps), encoding="utf-8")
        self._emit(f"重渲染 doc:{doc_id} → {rel}")
        return str(target)

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

    # ------------------------------------------------------------ 修订

    def revise(
        self,
        doc_id: str,
        *,
        fixed_findings: Sequence[str] | None = None,
        new_claims: Sequence[Mapping[str, Any]] | None = None,
        note: str = "",
    ) -> dict:
        """按 H 的发现修订稿件。

        - `review_rounds += 1`、`status = "revised"`、并重渲染 markdown；
        - `new_claims` 里代号已存在的断言会替换原断言（修订），
          新代号则追加。没有这条替换语义，G 就只能"再加一句新话"，
          永远改不掉那句错话 —— 那 `revise` 就修不好任何一条审校发现；
        - `fixed_findings` 里的 finding 只改 `status`/`resolution_note`，
          内容一个字不改（那是 H 的判断依据）。发现不属于本稿 ⇒ 抛错：
          G 不许借"修订"去动别人的稿件上的发现。

        这里标的 `fixed` 不是终局判定：H 的 `verify_fixes` 会重跑检查，
        仍复现就把状态改回 `open`。

        ## 修订同样要核"引用是否真的存在"（此前的缺口）

        `build_document` 有两道闸：`normalize_claims`（`citations` 非空）与
        `check_citations`（引用指向的对象真的在库里）。`revise` 此前只过了
        第一道，于是 `revise(new_claims=[claim citing "lit:9999"])` 会成功写库 ——
        一份用"改写"这条路绕开引用存在性检查的稿件。这比"没有引用"更隐蔽：
        读者看到的是一个像模像样的 `lit:9999`，而库里根本没有这篇文献。

        现在两条路复用同一个 `DT.check_citations`（不另写第二份判据），
        并把它放在同一笔事务里读表，避免"核引用"与"写 documents"看到不同快照。
        """
        doc_id = str(doc_id)
        with self.store.tx(
            "documents", "dependencies", "review_findings",
            # 下面四张表只为 `check_citations` 而声明：`Store.tx` 按 `LOCK_ORDER`
            # 统一排序加锁，多声明几张表不会引入加锁顺序问题。
            "literature", "relations", "experiments", "eval_results",
            actor=self.actor, note=f"revise doc:{doc_id} {note}".strip(),
        ) as tx:
            doc = tx.find("documents", doc_id=doc_id)
            if doc is None:
                raise DocumentError(f"稿件 {doc_id} 不存在 ⇒ 不能修订一份不存在的稿件")

            merged = [dict(c) for c in (doc.get("claims") or [])]
            replaced: list[str] = []
            appended: list[str] = []
            for raw in new_claims or []:
                if not isinstance(raw, Mapping):
                    raise DocumentError(f"new_claims 的元素必须是对象，收到 {type(raw).__name__}")
                c = dict(raw)
                cid = str(c.get("claim_id") or "").strip()
                idx = next(
                    (i for i, e in enumerate(merged) if cid and str(e.get("claim_id")) == cid), None
                )
                if idx is not None:
                    merged[idx] = c
                    replaced.append(cid)
                else:
                    merged.append(c)
                    appended.append(cid or f"（自动编号，第 {len(merged)} 条）")

            # 合规闸门：修订后的整份稿子要重过一遍机械检查。
            # 只查"新加的那几条"是不够的 —— 替换语义下，旧的错话可能被换掉，
            # 也可能被换坏，只有全量重查才说得清现在的稿子是否合规。
            normalized = DT.normalize_claims(merged)

            # 第二道闸：引用存在性。与 `doc.build_document` 复用同一个判据，
            # 理由见本方法 docstring —— 少了它，"修订"就是绕过引用检查的后门。
            cites = DT.check_citations(tx.rows, normalized)
            if not cites["checked"]:
                # 理论上不可达（这里必然有 tx）。留着是为了让"没法查"这条状态
                # 有出口，而不是在某次重构里悄悄退化成"当作查过了"。
                raise DocumentError(
                    f"修订 doc:{doc_id} 时无法核对引用是否存在：{cites['reason']} ⇒ 整笔不写库"
                )
            if cites["missing"]:
                bad = "；".join(
                    f"[{m['claim_id']}] {m['citation']!r}：{m['why']}" for m in cites["missing"]
                )
                raise DocumentError(
                    f"修订 doc:{doc_id} 被拒：{len(cites['missing'])} 条引用指向**不存在**的对象，"
                    f"整笔不写库（documents/review_findings 都不动）：{bad}。"
                    "引用一个不存在的代号，等于把外部结论当成自己的结论（FC-02）——"
                    "`normalize_claims` 只看 citations 非空，查不出这一点"
                )

            # 第三道闸：proof 级断言的证据锚（`D-1`）。与 `doc.build_document`
            # 复用同一个 `DT.check_proofs`，理由与上面那条逐字相同 ——
            # 少一道，"修订"就是绕过它的后门。这条不是推演：实测把 `revise` 的
            # 新断言换成一条只引 `lit:`、没有 `proof_location` 的 proof 断言，
            # 它能成功写库（`temp/r2-revise-bypass.txt`，本文件修之前跑出来的）。
            proofs = DT.check_proofs(tx.rows, normalized, workspace_root=self.workspace_root)
            if not proofs["checked"]:
                raise DocumentError(
                    f"修订 doc:{doc_id} 时无法核对 proof 级断言的证据：{proofs['reason']} ⇒ 整笔不写库"
                )
            if proofs["problems"]:
                bad = "；".join(f"[{p['claim_id']}] {p['detail']}" for p in proofs["problems"])
                raise DocumentError(
                    f"修订 doc:{doc_id} 被拒：{len(proofs['problems'])} 条 proof 级断言的证据"
                    f"不成立，整笔不写库（documents/review_findings 都不动）：{bad}。"
                    "`evidence_kind='proof'` 享受最高一档的证据待遇，所以改写这条路"
                    "也必须指向一条真的跑过检查器的实验行、并给出盘上真的存在的落点"
                )

            doc["claims"] = normalized
            doc["review_rounds"] = int(doc.get("review_rounds") or 0) + 1
            doc["status"] = "revised"
            doc["updated_at"] = S.now_iso()
            # 改稿 = 新的一版（`draft/30` §T4-A）：`revision` 前进一格、内容哈希重算。
            # 旧审批因此自动失效（它钉的是上一版的哈希），这是设计要的：
            # "审批过的版本"与"被引用的版本"不许静默分家。
            doc["revision"] = int(doc.get("revision") or 0) + 1
            doc["content_sha256"] = SIG.content_sha256_of(doc)
            row = S.row_from_dict("documents", doc)
            row.validate()
            payload = row.to_dict()
            tx.upsert("documents", payload)

            fixed_ids: list[str] = []
            for fid in fixed_findings or []:
                f = tx.find("review_findings", finding_id=str(fid))
                if f is None:
                    raise DocumentError(f"发现 {fid} 不存在 ⇒ 不能把一条不存在的发现标成已修")
                if str(f.get("doc_id")) != doc_id:
                    raise DocumentError(
                        f"发现 {fid} 属于稿件 {f.get('doc_id')}，不是 {doc_id}："
                        "**G 只能改自己稿件上的发现状态**（跨稿改动是掩盖问题的入口）"
                    )
                f["status"] = "fixed"
                stamp = f"[round {payload['review_rounds']}] G 在 revise 中声明已处理"
                if note:
                    stamp += f"：{note}"
                f["resolution_note"] = (str(f.get("resolution_note") or "").strip() + " " + stamp).strip()
                tx.upsert("review_findings", f)
                fixed_ids.append(str(fid))

            rendered: str | None = None
            rel = payload.get("markdown_path")
            if rel:
                target = self._resolve_inside(str(rel))
                deps = DT.dependencies_for_doc(tx.rows("dependencies"), doc_id)
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(DT.render_markdown(payload, dependencies=deps), encoding="utf-8")
                except OSError as e:
                    raise DocumentError(
                        f"修订后重渲染失败（{target}）：{type(e).__name__}: {e}。"
                        "宁可整笔回滚，也不留下一份'库与磁盘不一致'的稿件"
                    ) from e
                rendered = str(target)

        self._emit(
            f"修订 doc:{doc_id} → review_rounds={payload['review_rounds']}，"
            f"替换 {len(replaced)} 条、新增 {len(appended)} 条断言，标记 {len(fixed_ids)} 条发现为 fixed"
        )
        return {
            "doc_id": doc_id,
            "review_rounds": payload["review_rounds"],
            "status": payload["status"],
            "claim_count": len(payload["claims"]),
            "replaced_claim_ids": replaced,
            "appended_claim_ids": appended,
            "fixed_findings": fixed_ids,
            "markdown_path": rel,
            "rendered_path": rendered,
        }

    # ------------------------------------------------------------ 自检

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


# ---------------------------------------------------------------- 自检（模块级）


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
    from .verify import verify_all

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
        from .agent_h import AgentH
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
    line(f"[8] 最终统计：{json.dumps(st.stats()['documents'], ensure_ascii=False)} "
         f"{json.dumps(st.stats()['dependencies'], ensure_ascii=False)} "
         f"{json.dumps(st.stats()['review_findings'], ensure_ascii=False)}")

    line("=" * 72)
    line("SELF-CHECK DONE（agent_g）")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    raise SystemExit(_selftest())
