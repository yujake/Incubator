"""智能体 H：审校（**只读**）。

## 为什么 H 必须是只读的

若审校者能直接改稿，它就同时是"发现者"与"修正者"，于是
**"发现问题"与"掩盖问题"在结构上无法区分** —— 这不是分工洁癖，
而是"审校记录能不能被信任"的前提。把这条做成结构约束（而不是写在提示词里），
是它唯一可靠的落地方式。

## "H 只读"在这里由三件事共同保证（缺一条就只剩口号）

1. **工具面只读**：`install_h_tools()` 只把 `side_effect in ("none","read")`
   的工具放进 H 的自由工具箱，并在**构造时断言**这一点（拿到不合规的注册表
   就 fail-closed 拒绝启动）。被拒的写工具会记进 `registry.refused_write_tools`，
   **不静默丢弃**。
2. **落库代理被钉死**：H 唯一会写盘的动作（写 `review_findings`、
   改 `documents.status`）走的是显式的"代理注册表"（`self.writers`，
   `include_writers=True`），而这两个工具的落点固定：**不碰 `claims`，
   不碰任何知识表**。
3. **可核对的运行期断言**：审校前后 `concepts/relations/literature` 逐字节不变；
   `documents.json` 的**唯一**变化点是 `status`（连 `updated_at` 都不碰）。

## H 的三态纪律

`dependencies` 没查（显式 `None`）与"查了、依赖都闭合"是两件事：
前者必须报 `dep_check.checked is False` 且**不许**判 `accepted`。
AgentD 的 `_UNSPECIFIED` 哨兵在这里沿用同一种语义。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import schema as S
from .store import Store
from .tools import build_registry
from .tools import review_tools as RV
from .tools.base import ToolRegistry, ToolSpec
from .tools.doc_tools import CROSS_CHECK_DISCLAIMER

__all__ = ["AgentH", "ReviewError", "filter_readonly_h_surface", "install_h_tools"]


class ReviewError(RuntimeError):
    """审校流程本身失败（工具未接线 / 注册表不合规 / 稿件不存在）。"""


#: 默认值哨兵：不传 = "自己去库里读依赖"；显式 `None` = "调用方没给清单 ⇒ 没查"。
_UNSPECIFIED: Any = object()

#: H 允许持有的副作用等级。写成常量而不是散落的字面量：
#: 它是一条**结构约束**，必须只有一处定义（FC-03）。
_H_READONLY_SIDE_EFFECTS = ("none", "read")


# ---------------------------------------------------------------- 工具装配


def filter_readonly_h_surface(
    specs: Iterable[ToolSpec],
) -> tuple[list[ToolSpec], list[dict]]:
    """把 H 的角色面裁成"只读面"，并把被拒的写工具**记录**下来。

    ## 为什么需要这一层（这是当前工具层的一个真实缺陷）

    `table.*` / `fs.*` 这批通用工具的 `roles` 是**全部角色**，其中
    `table.create` / `table.update` / `table.delete` / `fs.write` / `fs.delete` /
    `fs.move` 都是 `write_local`。也就是说，直接按角色过滤得到的"H 的工具面"里
    **混着能改任何一张表的刀**：只要 H 手里有 `table.update`，它就能改
    `documents.claims`，于是"发现问题"与"掩盖问题"重新变得无法区分。

    本模块不改别人的文件（`tools/__init__.py`、`table_tools.py`、`fs_tools.py`
    都不属于本次交付），因此在这里**显式拒绝并留痕**：拒绝清单会挂在注册表的
    `refused_write_tools` 上，出现在自检与报告里。这比"悄悄继承一个与设计意图
    相反的权限面"诚实得多（FC-08：降级必须显式，不得静默）。
    """
    kept: list[ToolSpec] = []
    refused: list[dict] = []
    for s in specs:
        if s.side_effect in _H_READONLY_SIDE_EFFECTS:
            kept.append(s)
        else:
            refused.append(
                {
                    "name": s.name,
                    "side_effect": s.side_effect,
                    "reason": "H 的工具面必须全部 none/read：能改表的工具会让审校者同时成为修正者",
                }
            )
    return kept, refused


def install_h_tools(
    store: Store, *, workspace_root: str | Path | None = None
) -> ToolRegistry:
    """装配 H 的**只读**工具栏（并把被拒的写工具记录在注册表上）。"""
    root = Path(workspace_root).resolve() if workspace_root else Path(store.root).resolve()
    build = build_registry(store=store, workspace_root=root)
    raw = build.registry.for_role("H")
    kept, refused = filter_readonly_h_surface(raw)
    reg = ToolRegistry(name="agent-H")
    for spec in kept:
        reg.register(spec)
    # 留痕：降级/拒绝必须是可观测的事实，而不是"少几个工具没人知道"。
    setattr(reg, "refused_write_tools", refused)
    #: 裁剪前的角色面大小。有了它，"拒绝清单 + 保留清单 == 原面"这条不变量才能被断言
    #: （否则"静默丢弃"与"显式拒绝"在断言里长得一模一样）。
    setattr(reg, "raw_surface_size", len(raw))
    setattr(reg, "assembly_skipped", build.skipped)
    return reg


# ---------------------------------------------------------------- AgentH


class AgentH:
    """审校智能体。

    两个注册表是刻意分开的，它们的区别就是"H 只读"这条约束本身：

    - `self.tools`：H 的**自由工具箱**（只读）。H 可以任意反复调用，不需要审批。
    - `self.writers`：H 的**落库代理**（`write_local`）。只在固定流程里被调用，
      落点被钉死在 `review_findings` 与 `documents.status` 上。
    """

    def __init__(
        self,
        store: Store,
        *,
        config: Mapping[str, Any] | None = None,
        log: Callable[[str], None] | None = None,
        tools: ToolRegistry | None = None,
        writers: ToolRegistry | None = None,
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = str(self.cfg.get("actor", "agent-H"))
        self.workspace_root = Path(store.root).resolve()
        self.log = log
        self.logs: list[str] = []
        self.tool_calls: list[dict] = []

        #: 复审轮数上限。**必须有上限**：没有它，"error 一直不修"会变成一个
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
        if writers is None:
            RV.register(self.writers, store=self.store, include_writers=True, actor=self.actor)

    # ------------------------------------------------------------ 小工具

    def _emit(self, message: str, **extra: Any) -> None:
        line = message if not extra else f"{message} {extra}"
        self.logs.append(line)
        if callable(self.log):
            try:
                self.log(line)
            except Exception:  # noqa: BLE001 - 日志钩子坏了不该打断审校
                pass

    def _writer(self, name: str, /, **params: Any) -> dict:
        res = self.writers.call(name, **params)
        self.tool_calls.append({"tool": name, "ok": res.ok, "error": res.error})
        if not res.ok:
            # 不可静默：审校动作没做成，调用方必须知道（否则会以为"审过了、没问题"）。
            raise ReviewError(f"{name} 调用失败：{res.error}")
        return res.data

    # ------------------------------------------------------------ 审校

    def review(
        self,
        doc_id: str,
        *,
        round_no: int | None = None,
        dependencies: Any = _UNSPECIFIED,
    ) -> dict:
        """审一份稿件：落发现 + 更新文档状态（转发 `review.review_document`）。

        返回 ``{"doc_id","checked","round","new_findings","duplicate_skipped",
        "reopened","error_count","warning_count","info_count","dep_check","status",
        "status_updated","status_error","verdict","reason"}``。

        `dependencies` 三态：不传 = 从库里读该稿件的依赖；显式 `None` = **没查**
        （此时 `dep_check["checked"] is False`，verdict 是 `"unverified"` ——
        「依赖都闭合」这句话在没有查过的情况下不许说出口）。
        """
        params: dict[str, Any] = {"doc_id": str(doc_id)}
        if round_no is not None:
            params["round_no"] = int(round_no)
        if dependencies is not _UNSPECIFIED:
            params["dependencies"] = None if dependencies is None else [dict(d) for d in dependencies]
        data = self._writer("review.review_document", **params)
        self._emit(
            f"审校 doc:{doc_id} round={data.get('round')}：verdict={data.get('verdict')}，"
            f"新增 {len(data.get('new_findings') or [])} 条、跳过重复 "
            f"{data.get('duplicate_skipped')} 条，error={data.get('error_count')}，"
            f"status={data.get('status')}"
            + ("" if data.get("status_updated") else f"（状态未更新：{data.get('status_error')}）")
        )
        return data

    def verify_fixes(self, doc_id: str, *, round_no: int) -> dict:
        """复审：重跑检查判 `fixed` / 仍 `open`（转发 `review.verify_fixes`）。

        `error` 级发现一直不修、且已到 `max_review_rounds` ⇒ 文档置
        `unresolved_review`，并且返回值里 `unresolved_findings` **明确列出**
        未解决的发现（不许隐藏）。
        """
        data = self._writer(
            "review.verify_fixes",
            doc_id=str(doc_id),
            round_no=int(round_no),
            max_review_rounds=self.max_review_rounds,
        )
        self._emit(
            f"复审 doc:{doc_id} round={round_no}：verdict={data.get('verdict')}，"
            f"resolved={len(data.get('resolved') or [])}，still_open={len(data.get('still_open') or [])}，"
            f"未解决(error)={len(data.get('unresolved_findings') or [])}"
        )
        return data

    def list_findings(self, **filters: Any) -> dict:
        """只读列举发现（走 H 的自由工具箱）。"""
        res = self.tools.call("review.list_findings", **filters)
        self.tool_calls.append({"tool": "review.list_findings", "ok": res.ok, "error": res.error})
        if not res.ok:
            raise ReviewError(f"review.list_findings 调用失败：{res.error}")
        return res.data

    # ------------------------------------------------------------ 自检

    def selftest(self) -> int:
        """对**当前 store** 做一次最小自检：工具面是否只读、发现是否可写。

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


# ---------------------------------------------------------------- 自检（模块级）


def _seed_document(
    st: Store,
    *,
    doc_id: str,
    claims: Sequence[Mapping[str, Any]],
    status: str = "draft",
) -> dict:
    """在自检里直接写一行 schema 合法的稿件（不经过 G，保持 H 的自检自足）。"""
    row = S.Document(
        doc_id=doc_id,
        kind="paper",
        title="自检稿件",
        markdown_path=None,
        claims=[dict(c) for c in claims],
        status=status,
        created_at=S.now_iso(),
        updated_at=S.now_iso(),
    )
    row.validate()
    with st.tx("documents", actor="seed", note="selftest") as tx:
        tx.upsert("documents", row.to_dict())
    return row.to_dict()


def _inject_raw_document(st: Store, row: Mapping[str, Any]) -> None:
    """**绕过 store 校验**直接改盘（自检用）。

    为什么需要它：schema 会拒绝"无引用断言"这类行，所以那些坏数据**不可能**
    经由 `store.tx` 写入。而 H 要面对的恰恰包括"盘上已经存在的坏行"
    （手工改坏的、旧版本写的、rebuild 之前的残骸）—— 那正是 FC-09 关心的场景：
    后面的闸门不能假设前面的闸门一定跑过。
    """
    import json

    p = st.data / "documents.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["rows"] = [r for r in doc["rows"] if r.get("doc_id") != row["doc_id"]] + [dict(row)]
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _selftest() -> int:
    # 运行方式：cd D:\Incubator\test\test1\src && python -m abflow.agent_h
    import json
    import sys
    import tempfile

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="abflow-agenth-"))
    st = Store(root)
    st.init()
    print(f"[0] 临时工作区：{root}")

    # ---- 知识表（用于"运行期只读"的逐字节比对）
    with st.tx("concepts", "relations", "literature", actor="seed", note="fixture") as tx:
        tx.upsert("concepts", S.Concept(concept_id="0000", name="谱", definition="d", created_at=S.now_iso(), updated_at=S.now_iso()).to_dict())
        tx.upsert("concepts", S.Concept(concept_id="0001", name="区间", definition="d", created_at=S.now_iso(), updated_at=S.now_iso()).to_dict())
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
    clean = _seed_document(
        st,
        doc_id="0000",
        claims=[
            {
                "claim_id": "claim-1", "section": "主要结果", "text": "谱落在区间内。",
                "evidence_kind": "proof", "citations": ["rel:0000", "lit:0000#p.12-13"],
                "is_negative": False, "negation_kind": None, "disclaimer": "",
            }
        ],
    )
    # ---- 第二份：**schema 合法但审校不合规**（把 cross_check 说成"已证明"）。
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
    before = {n: (st.data / n).read_bytes() for n in ("concepts.json", "relations.json", "literature.json")}
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
    with st.tx("documents", actor="fake-G", note="fix") as tx:
        row = tx.find("documents", doc_id="0002")
        row["claims"] = [dict(c) for c in clean["claims"]]
        row["status"] = "revised"
        row["review_rounds"] = int(row.get("review_rounds") or 0) + 1
        tx.upsert("documents", row)
    b2 = h.verify_fixes("0002", round_no=3)
    print(f"    修好后 → 复审 verdict={b2['verdict']} resolved={len(b2['resolved'])} "
          f"still_open={len(b2['still_open'])} 库中状态={b2['status']}")
    if b2["verdict"] != "accepted" or b2["status"] != "accepted":
        print("    ❌ 修好后应判 accepted")
        return 1

    # ---- 最后才把"schema 不合法的坏行"注入盘上。
    # 顺序很重要：`store.tx` 提交时会校验**整张表**，一条坏行会让之后所有对
    # documents 的写入都失败。这本身就是一条值得展示的事实 —— 而 H 正是要在
    # 这种局面下仍然能把发现落库（发现写的是另一张表）。
    bad = dict(clean)
    bad["doc_id"] = "0001"
    bad["claims"] = [
        {"claim_id": "claim-9", "section": "x", "text": "这是一条没有任何引用的断言。",
         "evidence_kind": "heuristic", "citations": [], "is_negative": False,
         "negation_kind": None, "disclaimer": ""},
        {"claim_id": "claim-10", "section": "x", "text": "该推广不成立。",
         "evidence_kind": "heuristic", "citations": ["lit:0000"], "is_negative": True,
         "negation_kind": None, "disclaimer": ""},
    ]
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


if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    raise SystemExit(_selftest())
