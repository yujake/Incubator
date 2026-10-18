"""智能体 H（`agent_h.py`）与 `tools/review_tools.py` 的性质测试。

这里锁住六条性质，每一条都两个方向都测（好数据必须过 / 坏数据必须被拦）。

- 审校本身要有证据：每条 finding 的 `evidence` 必须含触发它的实际值；
- 依赖分级（FC-13）：`external_unavailable`（已记录的已知边界）= warning，
  `dangling`（没交代）= error；
- 三态：`dependencies` 没查 ⇒ `dep_check.checked is False`，且不许判 accepted；
- H 只读：默认注册面全 `none/read`，运行期知识表逐字节不变、
  `documents.json` 的唯一变化点是 `status`；
- 去重：同一份稿件再审一次不重复记发现；
- 复审有终止性：error 一直不修、跑到 `max_review_rounds` ⇒ `unresolved_review`，
  且必须列出未解决的发现（不许隐藏）。

关于坏样本的构造：`store.tx` 提交时会校验整张表，所以"无引用断言""否定型未分类"
这类行不可能经 store 写入。它们必须绕过校验直接改盘才能造出来 ——
而这恰好模拟了 H 真正要面对的场景（手工改坏的文件、旧版本写的行、
`rebuild` 之前的残骸）。后面的闸门不能假设前面的闸门一定跑过。
"""

from __future__ import annotations

import json

import pytest

from agentflow import schema as S
from agentflow import capabilities as C
from agentflow.agent_g import AgentG
from agentflow.agent_h import AgentH, ReviewError, filter_readonly_h_surface, install_h_tools
from agentflow.store import Store
from agentflow.tools import review_tools as RV
from agentflow.tools.base import ToolRegistry, ToolSpec
from agentflow.tools.doc_tools import CROSS_CHECK_DISCLAIMER, PROOF_REVIEW_DISCLAIMER

from conftest import add_concept, add_literature, add_relation

TS = "2026-01-01T00:00:00+00:00"
KNOWLEDGE_FILES = ("statements.json", "relations.json", "literature.json")


# ============================================================ 辅助


def sync_all_counters(st: Store) -> None:
    """把 counters.json 对齐到"每张表 max(已用)+1" —— 转发到 `conftest.sync_counters`。

    夹具直接写行（绕过 `alloc_id`）时必须补这一步：`verify` 会检查 counters 与
    已用 ID 的一致性，不补就会引入与本用例无关的 `counter_behind` 噪音
    —— 而噪音比不校验更糟：它会训练人忽略告警。

    本函数此前在这里写死了第二份 (kind, table) 名单（`lit`/`concept`/`relation`/…）——
    正是 `conftest.sync_counters` 的 docstring 点名的那种漂移："测试代码也是代码，
    写死第二份名单同样会漂移"。它今天真的漂了：并表过渡期新标准那一侧（`stmt`）
    不在名单里 ⇒ 夹具两处同号之后报 `counter_behind(stmt)`，而那条读数与本用例
    要验的东西毫无关系（`test_agent_h.py::test_h_output_does_not_break_the_global_verify`
    当场变红，第 125 轮的重测把它抓了出来）。所以改成转发：覆盖范围由
    `S.ID_COUNTERS` 反查，一处定义、一处维护。
    """
    from conftest import sync_counters as _sync

    _sync(st)


def clean_claim() -> dict:
    """一条完全合规的断言（schema 与审校都过得去）。

     `evidence_kind` 是 `cross_check` 而不是 `proof`：这条断言的引文是
    `rel:0000`（一条关系）与 `lit:0000#p.12-13`（一页文献），没有任何形式化
    检查器参与过。标成 `proof` 在语义上是错的，而 `D-1` 的写入期判据
    （`doc_tools.check_proofs`）会因此拒绝它。这与"为了绕过判据而改数据"无关：
    判据改正了一处误标（同一形态在 `test/test2/run_acceptance.py` 里也出现了，
    见 `temp/r2-e6-out7.txt`）。改后它仍然满足本文件的要求：0 error / 0 warning
    —— 前提是 `disclaimer` 一起填上（`cross_check` 的「不构成证明」声明是结构强制的）。
    """
    return {
        "claim_id": "claim-1",
        "section": "主要结果",
        "text": "谱落在区间内。",
        "evidence_kind": "cross_check",
        "citations": ["rel:0000", "lit:0000#p.12-13"],
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": CROSS_CHECK_DISCLAIMER,
    }


def overclaim_claim(*, with_disclaimer: bool = True, citations: list[str] | None = None) -> dict:
    """把交叉验证说成证明的断言：schema 合法（有引用、有声明），审校必须拦。"""
    return {
        "claim_id": "claim-1",
        "section": "数值证据",
        "text": "数值抽样支持该结论，因此我们已证明它成立。",
        "evidence_kind": "cross_check",
        "citations": list(citations if citations is not None else ["lit:0000"]),
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": CROSS_CHECK_DISCLAIMER if with_disclaimer else "",
    }


def document_row(doc_id: str, claims: list[dict], *, status: str = "draft") -> dict:
    """构造一行 documents（不校验：坏样本要靠它造出来）。

    `T4-A` 之后每一行稿件都带内容哈希（G 的写侧口径是"每次写都钉"）——
    不能只在 `status="accepted"` 时补：H 会稍后把 draft 置成 accepted，
    而 `_set_doc_status` 只改 status，那时再补就晚了。
    """
    row = S.Document(
        doc_id=doc_id,
        kind="paper",
        title=f"稿件 {doc_id}",
        markdown_path=None,
        claims=[dict(c) for c in claims],
        status=status,
        review_rounds=0,
        created_at=TS,
        updated_at=TS,
    ).to_dict()
    if not row.get("content_sha256"):
        from agentflow import signatures as _SIG

        row["content_sha256"] = _SIG.content_sha256_of(row)
    return row


def seed_document(st: Store, doc_id: str, claims: list[dict], *, status: str = "draft") -> dict:
    """经 store 写一行合法稿件（校验会当场把关）。"""
    row = document_row(doc_id, claims, status=status)
    S.row_from_dict("documents", row).validate()
    with st.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", row)
    sync_all_counters(st)
    return row


def inject_raw_document(st: Store, row: dict) -> None:
    """绕过 store 校验直接改盘（见模块 docstring：坏数据只能这样造）。"""
    p = st.data / "documents.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["rows"] = [r for r in doc["rows"] if r.get("doc_id") != row["doc_id"]] + [row]
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sync_all_counters(st)


def add_dep(
    st: Store,
    dep_id: str,
    *,
    used_by: str,
    status: str,
    reason: str,
    source_lit_id: str | None = None,
) -> dict:
    row = S.Dependency(
        dep_id=dep_id,
        used_by=used_by,
        kind="theorem",
        label=f"依赖 {dep_id}",
        status=status,
        source_lit_id=source_lit_id,
        status_reason=reason,
        created_at=TS,
    )
    row.validate()
    with st.tx("dependencies", actor="test", note="fixture") as tx:
        tx.upsert("dependencies", row.to_dict())
    sync_all_counters(st)
    return row.to_dict()


def findings_of(st: Store, doc_id: str, *, kind: str | None = None) -> list[dict]:
    return [
        r
        for r in st.rows("review_findings")
        if str(r.get("doc_id")) == str(doc_id) and (kind is None or r.get("kind") == kind)
    ]


def only_finding(st: Store, doc_id: str, kind: str) -> dict:
    rows = findings_of(st, doc_id, kind=kind)
    assert len(rows) == 1, f"期望恰好 1 条 {kind}，实际 {len(rows)} 条：{rows}"
    return rows[0]


@pytest.fixture
def h_store(store: Store) -> Store:
    """带知识表的最小工作区（知识表要非空，逐字节比对才有意义）。"""
    add_literature(store, "0000", title="Spec S̃_m = [−m, m]", processed=True, sync=False)
    add_concept(store, "0000", "谱", definition="d", sync=False)
    add_concept(store, "0001", "区间", definition="d", sync=False)
    add_relation(
        store,
        "0000",
        ["0000", "0001"],
        "0000",
        quote="Spectrum lies in the interval.",
        description="谱落在区间内",
        quote_verified=True,
        sync=False,
    )
    sync_all_counters(store)
    return store


@pytest.fixture
def h(h_store: Store) -> AgentH:
    return AgentH(h_store)


# ============================================================ [1] 防误伤


def test_review_accepts_a_clean_document(h: AgentH, h_store: Store):
    """防误伤：一份干净稿件必须 0 error、判 accepted（好数据必须过）。"""
    seed_document(h_store, "0000", [clean_claim()])
    res = h.review("0000", dependencies=[])
    assert res["checked"] is True
    assert res["error_count"] == 0 and res["warning_count"] == 0 and res["info_count"] == 0
    assert res["verdict"] == "accepted"
    assert res["new_findings"] == [] and res["duplicate_skipped"] == 0
    assert res["dep_check"]["checked"] is True
    assert res["status"] == "accepted" and res["status_updated"] is True
    assert h_store.rows("review_findings") == []
    assert h_store.rows("documents")[0]["status"] == "accepted"


# ============================================================ [2]-[5] 负控：坏稿件必须被抓


def test_review_reports_an_unsupported_claim_with_its_real_evidence(h: AgentH, h_store: Store):
    """最重要的一条：无引用断言必须报 unsupported_claim(error)，且 evidence 含实际值。"""
    bad = clean_claim()
    bad["citations"] = []
    inject_raw_document(h_store, document_row("0001", [bad]))

    res = h.review("0001")
    f = only_finding(h_store, "0001", "unsupported_claim")
    assert f["level"] == "error"
    assert f["target"] == "claim-1"
    assert f["evidence"].strip(), "审校发现必须带证据"
    assert "citations" in f["evidence"], "evidence 必须写清触发它的实际值（citations=[]）"
    assert f["round"] == 1 and f["status"] == "open"
    assert res["error_count"] == 1 and res["verdict"] == "rejected"
    assert len(res["new_findings"]) == 1
    # 这份稿件本身不合 schema ⇒ 连状态都写不进去。此时必须如实报告，
    # 而不是假装审校流程正常结束（发现照样落库了）。
    assert res["status_updated"] is False
    assert res["status_error"] and "citations" in res["status_error"]


def test_review_reports_a_cross_check_claim_without_disclaimer(h: AgentH, h_store: Store):
    """负控：`cross_check` 缺「不构成证明」声明 ⇒ overclaim + error。"""
    bad = overclaim_claim(with_disclaimer=False)
    bad["text"] = "数值抽样支持该结论。"
    inject_raw_document(h_store, document_row("0001", [bad]))

    res = h.review("0001")
    f = only_finding(h_store, "0001", "overclaim")
    assert f["level"] == "error"
    assert "disclaimer" in f["evidence"]
    assert res["verdict"] == "rejected"


def test_review_reports_a_disclaimer_that_is_not_the_controlled_one(h: AgentH, h_store: Store):
    """跨层：声明写了、但不是受控那一句 ⇒ `uncontrolled_disclaimer`，kind 必须语义正确。

    为什么这条要单独钉（2026-10-15）：`uncontrolled_disclaimer`（2026-10-13 加）
    漏登记进了 `review_tools._H_FINDING_KIND_OF_CA_CODE`，而那张表的兜底是
    `garbled` ⇒ "声明不是受控那句"被**静默**读成"表述无法解析"，
    而 `kind` 是审校分档的判据。与 G 侧同族、故障形态相反（G 侧当场抛 `KeyError`）。
    这里断言的是 `kind` 本身，所以兜底那条路一旦复辟，这条就红。
    """
    bad = clean_claim()
    # 串档：拿 `proof_review` 的受控声明去配 `cross_check`
    # （`clean_claim` 其余各栏都合规，所以这一条发现是唯一变量）。
    bad["disclaimer"] = PROOF_REVIEW_DISCLAIMER
    seed_document(h_store, "0000", [bad])

    res = h.review("0000", dependencies=[])
    rows = [
        f for f in findings_of(h_store, "0000")
        if "code=uncontrolled_disclaimer" in str(f.get("message") or "")
    ]
    assert len(rows) == 1, rows
    f = rows[0]
    assert f["kind"] == "unsupported_claim", f      # 旧形态在这里是 `garbled`
    assert f["level"] == "error"
    assert f["target"] == "claim-1"
    assert "disclaimer" in f["evidence"]
    assert res["verdict"] == "rejected"
    # 兜底路（garbled）没被走到 —— 声明不对不是"读不懂"。
    assert findings_of(h_store, "0000", kind="garbled") == []


def test_review_reports_overclaim_wording_in_a_cross_check_claim(h: AgentH, h_store: Store):
    """负控：`cross_check` 正文写「已证明」⇒ overclaim + error（这份稿件 schema 合法！）。"""
    seed_document(h_store, "0000", [overclaim_claim()])
    res = h.review("0000")
    f = only_finding(h_store, "0000", "overclaim")
    assert f["level"] == "error"
    assert "已证明" in f["evidence"]
    assert res["error_count"] == 1 and res["verdict"] == "rejected"
    # schema 合法 ⇒ 状态能落地：error 未修 ⇒ in_review
    assert res["status_updated"] is True and res["status"] == "in_review"
    assert h_store.rows("documents")[0]["status"] == "in_review"


def test_review_reports_a_negative_claim_without_negation_kind(h: AgentH, h_store: Store):
    """负控：否定型断言未分类 ⇒ missing_negation_kind + error。"""
    bad = clean_claim()
    bad["text"] = "该推广不成立。"
    bad["is_negative"] = True
    bad["negation_kind"] = None
    inject_raw_document(h_store, document_row("0001", [bad]))

    res = h.review("0001")
    f = only_finding(h_store, "0001", "missing_negation_kind")
    assert f["level"] == "error"
    assert "negation_kind" in f["evidence"]
    assert res["verdict"] == "rejected"


# ============================================================ [6] 依赖分级（FC-13）


def test_review_grades_dependencies_both_ways(h: AgentH, h_store: Store):
    """FC-13 两个方向都要断言：已知边界=warning，没交代=error。"""
    seed_document(h_store, "0000", [clean_claim()])
    add_dep(
        h_store,
        "0000",
        used_by="doc:0000#claim-1",
        status="external_unavailable",
        reason="companion book 不在本项目可得范围内（Remark 1.6 自己这么说）",
    )
    add_dep(
        h_store,
        "0001",
        used_by="doc:0000#claim-1",
        status="dangling",
        reason="引了但还没找到来源",
    )
    res = h.review("0000")
    by_id = {f["target"]: f for f in findings_of(h_store, "0000", kind="dangling_dep")}
    assert set(by_id) == {"0000", "0001"}
    assert by_id["0000"]["level"] == "warning", "已记录的已知边界不该报成 error（否则红灯会变噪音）"
    assert by_id["0001"]["level"] == "error", "悬空且没交代必须报 error"
    assert "已知边界" in by_id["0000"]["message"]
    # 计数必须按级别分列，且 error 的那条决定 verdict
    assert res["warning_count"] == 1 and res["error_count"] == 1
    assert res["verdict"] == "rejected"
    # 依赖没闭合 ⇒ 不许 accepted
    assert h_store.rows("documents")[0]["status"] == "in_review"


# ============================================================ [7] 三态


def test_dependency_check_is_three_state(h: AgentH, h_store: Store):
    """三态：没查 ≠ 查了没有。不许把"没查"读成"依赖都闭合"。"""
    seed_document(h_store, "0000", [clean_claim()])
    doc = h_store.rows("documents")[0]

    # ---- 纯函数层
    unchecked = RV.scan_document(doc)
    assert unchecked["dep_check"]["checked"] is False
    assert "没查" in unchecked["dep_check"]["reason"]
    assert unchecked["dep_check"]["open"] == [], "空列表是「没查」的结果，不是「都闭合」的证据"
    # 2026-10-17（业主「通过标准和 V 一样」）：**通过**要求语义层也判过 —— 只查依赖闭合
    # 还不够（工具面与这条纯函数入口同口径）。这里接一个"判过且一致"的替身。
    _judge = lambda claim, document: {"verdict": "consistent"}
    checked = RV.scan_document(doc, dependencies=[], semantic_judge=_judge)
    assert checked["dep_check"]["checked"] is True
    assert checked["findings"] == [] and checked["verdict"] == "accepted"

    # ---- AgentH 层：显式 dependencies=None
    res = h.review("0000", dependencies=None)
    assert res["dep_check"]["checked"] is False
    assert res["verdict"] != "accepted", "没查依赖就不许判 accepted"
    assert res["verdict"] == "unverified"
    assert "不能判 accepted" in res["reason"]
    assert h_store.rows("documents")[0]["status"] == "in_review"
    # 落盘的状态也不能是 accepted
    assert res["status"] == "in_review"


# ============================================================ [8] H 只读（工具面）


def test_h_tool_surface_is_read_only(h_store: Store):
    """H 的工具面必须全部 `none`/`read`；写入口只能显式打开，且被拒的写工具要留痕。"""
    reg = install_h_tools(h_store)
    surface = reg.describe()
    assert surface, "H 至少要有只读工具"
    assert all(t["side_effect"] in ("none", "read") for t in surface)
    assert all(t["needs_approval"] is False for t in surface)
    assert {"review.scan_document", "review.list_findings"} <= {t["name"] for t in surface}

    refused = reg.refused_write_tools
    assert all(r["side_effect"] not in ("none", "read") for r in refused)
    assert len(surface) + len(refused) == reg.raw_surface_size, "被拒的工具必须有记录，不许静默丢弃"
    assert not ({t["name"] for t in surface} & {r["name"] for r in refused})

    # ---- 负控：过滤函数对"混进来的写工具"必须真的拒（而不是碰巧当前没有写工具）
    write_spec = ToolSpec(
        name="x.write",
        summary="s",
        params={"type": "object", "properties": {}},
        handler=lambda: None,
        side_effect="write_local",
        roles=("H",),
    )
    read_spec = ToolSpec(
        name="x.read",
        summary="s",
        params={"type": "object", "properties": {}},
        handler=lambda: None,
        side_effect="read",
        roles=("H",),
    )
    kept, refused2 = filter_readonly_h_surface([write_spec, read_spec])
    assert [s.name for s in kept] == ["x.read"]
    assert [r["name"] for r in refused2] == ["x.write"]
    assert refused2[0]["side_effect"] == "write_local"
    assert "修正者" in refused2[0]["reason"]

    # ---- fail-closed：被塞进一个写工具的 H 注册表必须拒绝启动
    poisoned = ToolRegistry(name="poisoned")
    poisoned.register(write_spec)
    with pytest.raises(ReviewError, match="非只读"):
        AgentH(h_store, tools=poisoned)

    # ---- review_tools 的默认注册面只读；写工具要显式 include_writers
    default_reg = ToolRegistry(name="review-default")
    RV.register(default_reg, store=h_store)
    assert default_reg.names() == ["review.list_findings", "review.scan_document"]
    assert all(s.side_effect in ("none", "read") for s in default_reg.for_role("H"))

    writer_reg = ToolRegistry(name="review-writers")
    RV.register(writer_reg, store=h_store, include_writers=True)
    assert writer_reg.get("review.review_document").side_effect == "write_local"
    assert writer_reg.get("review.verify_fixes").side_effect == "write_local"
    assert writer_reg.get("review.list_findings").side_effect == "read"
    assert writer_reg.get("review.scan_document").side_effect == "none"


# ============================================================ [9] H 只读（运行期）


def test_review_does_not_touch_knowledge_tables_and_only_changes_status(h: AgentH, h_store: Store):
    """运行期的只读：知识表逐字节不变；documents.json 的唯一变化点是 status。"""
    seed_document(h_store, "0000", [overclaim_claim()])
    before_knowledge = {n: (h_store.data / n).read_bytes() for n in KNOWLEDGE_FILES}
    docs_before = json.loads((h_store.data / "documents.json").read_text(encoding="utf-8"))

    res = h.review("0000")
    assert res["new_findings"], "这份稿件本来就该被抓到（否则本用例测不到变更）"

    for name in KNOWLEDGE_FILES:
        assert (h_store.data / name).read_bytes() == before_knowledge[name], f"{name} 被 H 改动了"
    docs_after = json.loads((h_store.data / "documents.json").read_text(encoding="utf-8"))
    changed: list[tuple[str, list[str]]] = []
    for rb, ra in zip(docs_before["rows"], docs_after["rows"]):
        diff = sorted({k for k in set(rb) | set(ra) if rb.get(k) != ra.get(k)})
        if diff:
            changed.append((str(rb.get("doc_id")), diff))
    # 2026-10-17（业主：「H 审过和通过是完全不同的状态」）：审校现在**同一次事务**里
    # 多写审核轴三字段（`review_verdict`/`reviewed_at`/`reviewed_by`）——
    # 这仍然是"只改这一行、不碰知识表、不碰 claims"，只是多记了"谁在什么时候判了什么"。
    _AXIS = ["review_verdict", "reviewed_at", "reviewed_by"]
    assert changed == [("0000", sorted(_AXIS + ["status"]))], f"变化点不止 status＋审核轴：{changed}"
    assert docs_after["rows"][0]["claims"] == docs_before["rows"][0]["claims"], "H 不许改 claims"


# ============================================================ [10] 去重


def test_review_dedups_findings_on_the_second_run(h: AgentH, h_store: Store):
    """连跑两次：第二次全部按 (kind,target,message) 去重，发现行数不增。"""
    seed_document(h_store, "0000", [overclaim_claim()])
    first = h.review("0000")
    assert len(first["new_findings"]) == 1 and first["duplicate_skipped"] == 0
    n_before = len(h_store.rows("review_findings"))

    second = h.review("0000")
    assert second["duplicate_skipped"] > 0
    assert second["new_findings"] == []
    assert len(h_store.rows("review_findings")) == n_before
    assert second["round"] == 2, "第二次审校必须是新一轮（轮次靠库里的既有事实递增）"


# ============================================================ [11] 复审：fixed / open


def _seed_overclaim_and_review(h: AgentH, st: Store, doc_id: str = "0000") -> dict:
    seed_document(st, doc_id, [overclaim_claim()])
    res = h.review(doc_id)
    assert res["error_count"] == 1
    return res["new_findings"][0]


def test_verify_fixes_marks_a_genuinely_fixed_finding_as_fixed(h_store: Store):
    """正向：真修好了 ⇒ resolved，finding 置 fixed，状态停在 `in_review` 等一次重审。

    ## 为什么不是"文档回归 accepted"（`R-59`，`draft/28` §161.4 / §172）

    本用例原来断言 `verify_fixes` 之后 `documents[0]["status"] == "accepted"`。
    那正是被修掉的形态：G 改稿之后内容哈希变了，而签名台账里那条钉的是旧版本 ——
    复审把状态置回 accepted，于是留下"状态 accepted + 签名钉旧版"，
    `verify_all` 报 `stale_signature`（"改稿之后旧审批不许沿用"）。

    现在的口径：`verify_fixes` 只在"台账里有签名钉住当前这一版"时才置 accepted；
    否则置 `in_review` 并在 reason 里点名要重新 review。所以本用例分两步断言：
    ① 复审判 accepted、发现置 fixed、状态停在 in_review（本用例的主题没变）；
    ② 再走一次 `review`（H 的唯一签发入口）⇒ 状态 accepted 且签名钉在当前这一版上。
    """
    agent = AgentH(h_store, config={"max_review_rounds": 3})
    finding = _seed_overclaim_and_review(agent, h_store)
    g = AgentG(h_store)
    fixed = g.compose_claim(
        "数值抽样支持该结论。",
        citations=["lit:0000"],
        evidence_kind="cross_check",
        section="数值证据",
        claim_id=str(finding["target"]),
    )
    out = g.revise("0000", fixed_findings=[finding["finding_id"]], new_claims=[fixed], note="删掉过度声称")
    assert out["replaced_claim_ids"] == [finding["target"]]
    assert h_store.rows("review_findings")[0]["status"] == "fixed"

    res = agent.verify_fixes("0000", round_no=2)
    assert res["verdict"] == "accepted"
    assert [f["finding_id"] for f in res["resolved"]] == [finding["finding_id"]]
    assert res["still_open"] == [] and res["unresolved_findings"] == []
    assert h_store.rows("review_findings")[0]["status"] == "fixed"
    assert h_store.rows("documents")[0]["status"] == "in_review", (
        "改稿之后旧签名不许沿用 ⇒ 复审不能把状态置回 accepted（R-59）"
    )
    assert "不置 `accepted`" in res["reason"]

    # ② 重审一次（H 的唯一签发入口）⇒ accepted 且有签名钉住这一版
    from agentflow import signatures as SIG

    again = agent.review("0000", dependencies=[])
    doc_now = h_store.rows("documents")[0]
    recs, bad = SIG.read_ledger(SIG.ledger_path(h_store.root))
    assert bad == []
    assert again["verdict"] == "accepted" and doc_now["status"] == "accepted"
    assert SIG.signed_revision(doc_now, recs) is not None, "接受了却没有签名钉在当前这一版上"


def test_verify_fixes_keeps_an_unfixed_finding_open(h_store: Store):
    """负控：什么都没改 ⇒ still_open 非空、仍 open、verdict 是 revise_again。"""
    agent = AgentH(h_store, config={"max_review_rounds": 3})
    finding = _seed_overclaim_and_review(agent, h_store)

    res = agent.verify_fixes("0000", round_no=2)
    assert res["verdict"] == "revise_again"
    assert res["resolved"] == []
    assert [f["finding_id"] for f in res["still_open"]] == [finding["finding_id"]]
    assert res["still_open"][0]["level"] == "error"
    assert res["unresolved_findings"], "未解决的 error 必须被列出来"
    assert h_store.rows("review_findings")[0]["status"] == "open"
    assert h_store.rows("documents")[0]["status"] == "in_review"


# ============================================================ [12] 终止性


def test_verify_fixes_terminates_as_unresolved_review(h_store: Store):
    """error 一直不修、跑到 max_review_rounds ⇒ unresolved_review，且列出未解决项。"""
    agent = AgentH(h_store, config={"max_review_rounds": 2})
    finding = _seed_overclaim_and_review(agent, h_store)

    res = agent.verify_fixes("0000", round_no=2)
    assert res["verdict"] == "unresolved_review"
    assert len(res["unresolved_findings"]) == 1, "不许隐藏未解决的发现"
    unresolved = res["unresolved_findings"][0]
    assert unresolved["finding_id"] == finding["finding_id"]
    assert unresolved["kind"] == "overclaim" and unresolved["level"] == "error"
    assert "轮数上限" in res["reason"] and "未隐藏" in res["reason"]
    assert h_store.rows("documents")[0]["status"] == "unresolved_review"
    assert res["status"] == "unresolved_review"


def test_verify_fixes_reopens_a_finding_marked_fixed_without_fixing(h_store: Store):
    """负控（防"用错方式修好"）：G 把发现标成 fixed 但问题仍在 ⇒ 重开，不认这笔账。"""
    agent = AgentH(h_store, config={"max_review_rounds": 5})
    seed_document(h_store, "0000", [clean_claim()])
    add_dep(
        h_store,
        "0000",
        used_by="doc:0000#claim-1",
        status="dangling",
        reason="引了但还没找到来源",
    )
    reviewed = agent.review("0000")
    finding = only_finding(h_store, "0000", "dangling_dep")
    assert reviewed["error_count"] == 1

    # G 谎报：只把状态标成 fixed，依赖一个字没动
    AgentG(h_store).revise("0000", fixed_findings=[finding["finding_id"]], note="我说修好了")
    assert h_store.rows("review_findings")[0]["status"] == "fixed"

    res = agent.verify_fixes("0000", round_no=2)
    assert res["resolved"] == [], "依赖仍然悬空，不该被算成 resolved"
    reopened = [f for f in res["still_open"] if f.get("reopened")]
    assert reopened and reopened[0]["finding_id"] == finding["finding_id"]
    assert h_store.rows("review_findings")[0]["status"] == "open", "谎报的 fixed 必须被重开"
    assert "仍然复现" in h_store.rows("review_findings")[0]["resolution_note"]
    assert res["verdict"] != "accepted"


# ============================================================ 其它


def test_verify_fixes_rechecks_the_dependency_set_the_caller_hands_it(h_store: Store):
    """复审必须能拿到与 `review` 同一份依赖清单，否则会把未刊依赖静默判成 fixed。

    实测缺口（2026-09-29，P3 台账）：依赖行挂在 `paper/main.tex#<label>` 上，
    而 `dependencies_for_doc` 只认 `used_by` 的 `doc:` 前缀 ⇒ 复审"从库里读"
    读到的是空集，于是上一轮如实报出的 `dangling_dep`（`external_unavailable`）
    会被判成 `resolved ⇒ fixed` —— 把一个"已知拿不到的前提"静默宣告成"已解决"。

    两个方向都要断言，缺一个这条就是真空断言：
    ① 不传清单 ⇒ 那个缺口的形态复现（判成 fixed，本轮不算它 open）；
    ② 传了清单 ⇒ 同一份前提仍 open（复审维持"拿不到"这个事实）。
    """
    agent = AgentH(h_store, config={"max_review_rounds": 5})
    seed_document(h_store, "0000", [clean_claim()])
    add_dep(
        h_store,
        "0000",
        # 刻意挂在稿件之外的锚点上：这正是"复审自己去库里读就读不到"的那种依赖
        used_by="paper/main.tex#claim-1",
        status="external_unavailable",
        reason="未刊 companion 拿不到",
    )
    deps = h_store.rows("dependencies")

    reviewed = agent.review("0000", dependencies=deps)
    assert reviewed["warning_count"] == 1 and reviewed["error_count"] == 0
    finding = only_finding(h_store, "0000", "dangling_dep")

    blind = agent.verify_fixes("0000", round_no=2)
    assert [f["finding_id"] for f in blind["resolved"]] == [finding["finding_id"]], (
        "缺口的形态：复审读不到挂在外锚点上的依赖 ⇒ 如实报出的发现被判成 resolved"
    )
    assert blind["still_open"] == []

    honest = agent.verify_fixes("0000", round_no=2, dependencies=deps)
    assert [f["finding_id"] for f in honest["still_open"]] == [finding["finding_id"]]
    assert honest["still_open"][0]["status"] == "open"
    assert h_store.rows("review_findings")[0]["status"] == "open", "传了清单就不许被判成 fixed"
    assert "已知边界" in h_store.rows("review_findings")[0]["message"]


def test_review_and_verify_fixes_declare_dependencies_as_row_sequences():
    """声明面：三个动作的 `dependencies` 都必须声明成"行序列"，不是对象/字符串。

    这一格此前是 `_OBJ`（`review` / `verify_fixes`）与 `_ARR_S`（`review_report`），
    而实现侧交下去的都是 `[dict(d) …]` —— 于是"把依赖逐条交给 H"的派活
    会在参数门被判 `dependencies. 必须是对象，收到 array`。
    工具层四条声明一直写的是 array-of-objects，这里断言两层终于一致。
    """
    for action in ("review", "verify_fixes", "review_report"):
        spec = C.find_action("H", action)
        assert spec is not None, f"H 没有动作 {action}"
        dep = (spec.params.get("properties") or {}).get("dependencies")
        assert dep == {"type": "array", "items": {"type": "object"}}, (
            f"H.{action}.dependencies 的声明是 {dep!r}，与实现（行序列）不符"
        )


def test_agent_h_selftest_passes(h_store: Store):
    """`AgentH.selftest()` 就地冒烟：只读工具面 + 三态。"""
    seed_document(h_store, "0000", [clean_claim()])
    agent = AgentH(h_store)
    assert agent.selftest() == 0
    assert any("selftest" in line for line in agent.logs)


def test_review_rejects_an_unknown_document(h: AgentH):
    """负控：审一份不存在的稿件必须报错，而不是"没有发现 ⇒ accepted"。"""
    with pytest.raises(ReviewError, match="不存在"):
        h.review("0007")


def test_h_output_does_not_break_the_global_verify(h: AgentH, h_store: Store):
    """接线检查（N11）：H 的产出必须过 `verify` 的跨表检查，且不制造新的 error。

    `verify` 由另一路交付，它会自己重算"finding 是否指向真实稿件/是否带证据/
    稿件是否在还有未处置 error 时被标成 accepted"。这里锁住的是两侧口径一致：
    H 写下的每一行都必须是 verify 认得下的行。
    """
    from agentflow.verify import verify_all

    seed_document(h_store, "0000", [overclaim_claim()])
    res = h.review("0000")
    assert res["error_count"] == 1 and h_store.rows("documents")[0]["status"] == "in_review"
    errors = [(i.code, i.table, i.row_id, i.message[:70]) for i in verify_all(h_store).errors]
    assert errors == [], f"verify 在 H 的产出上报了 error：{errors}"


def test_verify_does_not_write_findings_of_its_own(h_store: Store):
    """复审不发明新账：发现是 `review` 的产出；状态没变时也不写盘。"""
    agent = AgentH(h_store, config={"max_review_rounds": 3})
    finding = _seed_overclaim_and_review(agent, h_store)
    n_before = len(h_store.rows("review_findings"))
    res = agent.verify_fixes("0000", round_no=2)
    assert len(h_store.rows("review_findings")) == n_before
    kinds = {f["kind"] for f in h_store.rows("review_findings")}
    assert kinds == {"overclaim"}
    # 它不是"没查"：仍然复现的发现照样被列出来（不许隐藏）
    assert [f["finding_id"] for f in res["still_open"]] == [finding["finding_id"]]
    # 这条发现本来就是 open ⇒ 没有状态需要改，于是一条也没写（"没做"≠"做了没结果"）
    assert res["finding_updates"] == []
    assert h_store.rows("review_findings")[0]["status"] == "open"
