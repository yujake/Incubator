# -*- coding: utf-8 -*-
"""C 的关系推断：索引一次建好、局部树按需展开（`draft/181` 的 A + B 批）。

## 这一份钉什么（业主 2026-11-10 逐条点名的 a–h）

| # | 判据 | 为什么值得一条 |
|---|---|---|
| a | 索引的正 / 反邻接对得上（A ← B ← C 三层），`doc:` / `relation:` / `experiment:` 不入节点 | 索引是"一次建成"的唯一落点；正反两向对不上 ⇔ 上下展开走的是两本账 |
| b | `resolve` 按号 / 按标签命中、找不到时明白说没有、返回不含证明正文 | 它是"选根"，不是"偷偷给一棵树"；空列表会被读成"还没查" |
| c | `expand` 缺 `depth` ⇒ 缺参数提示（含"层数由你决定、必填"与可照抄的例子），不返回树 | 层数由 C 决定；静默用默认值等于替它做了这个决定 |
| d | `expand(depth=1)` 的节点七样齐（关系 / 号 / 类别 / 内容 / 等级 / 依赖面 / 被引面）；`statement_full` 在、`proof_text` 不在 | 七样是业主逐条点名的显示字段；证明正文进上下文既费 token 又越权 |
| e | 依赖面全路径 + 按证明路径分组：`#p1` / `#p2` 两组分开、各自到根；断链标 `broken` 并指出断点 | "全展开、但不许悄悄少给几层"是这一面唯一的诚实形态 |
| f | 被引面只一层：三层场景下只出现直接引用者 | 被引面是"谁靠我站着"的第一圈；多给一层就把全图漏回上下文 |
| g | 同一 `node` 再 `expand` ⇒ 增量：`already_known` 命中、`nodes` 不重复 | 无句柄的"拼接扩张"靠这一条成立（否则 C 每接一次就把同一批字段再读一遍） |
| h | 三条反真空：depth 有默认值 ⇒ c 红；依赖面只展开一层 ⇒ e 红；证明正文塞进节点 ⇒ d 红 | 没有反真空的判据是橡皮图章（本仓的既有纪律） |

## 口径来自哪里

- 索引与展开的形状：`draft/181` §3 / §4.2 / §4bis；
- 概念平权（业主 2026-11-10 追加）：「概念只是命题台账里的一个标签，处理方式和命题平权」
  ⇒ 概念行就是 `statements` 里 `kind=concept` 的那一行，同一套 `resolve` / `expand`，
  不读 `relations` 表、不借概念图、没有特例分支；没有入边 / 出边时如实给空并说明原因；
- 节点多带一格 `kind`（命题类别，取 `statements.kind` 原值，不翻译）。

零模型调用、零网络；夹具只落 `statements` / `dependencies` 两张表（直接铺行，与
`conftest.seed_statement_row` 同一形态：测的是"这个状态被读成什么"，不是写入路径）。
"""
from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import replace
from functools import partial
from typing import Any

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import ledgerindex as LI  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import ledger_tools as LT  # noqa: E402
from agentflow.tools.base import ToolRegistry  # noqa: E402

#: 证明正文的哨兵：它出现在树里 / 候选里就说明"证明了什么"漏进了上下文。
PROOF_MARKER = "PROOF-MARKER-不许进上下文"

#: 节点七样（业主逐条点名；`kind` 是 2026-11-10 追加的那一格）。
REQUIRED_NODE_FIELDS: tuple[str, ...] = (
    "relation", "stmt_id", "kind", "statement_full", "grade",
    "dependency_face", "cited_face",
)


# ---------------------------------------------------------------- 夹具


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _seed_stmt(store: Store, stmt_id: str, *, kind: str = "theorem",
               label: str = "", full: str = "", proof: str = PROOF_MARKER,
               status: str = "active", origin: str = "own_result") -> dict:
    """直接铺一行 `statements`（同 `conftest.seed_statement_row` 的形态）。"""
    row = {
        "stmt_id": stmt_id, "origin": origin, "kind": kind, "label": label,
        "statement_text": full, "statement_full": full, "proof_text": proof,
        "status": status, "quote_verified": None,
        "quote_reason": "夹具：直接铺行（历史形态：无 V 签）",
        "bits": {}, "created_at": S.now_iso(), "created_by": "fixture",
    }
    with store.tx("statements", actor="fixture") as tx:
        tx.upsert("statements", row)
    return row


def _seed_dep(store: Store, dep_id: str, used_by: str, *, source_stmt_id: str = "",
              source_lit_id: str = "", path_group: int = 1, label: str = "",
              quote: str = "", status: str = "closed",
              status_reason: str = "") -> dict:
    """直接铺一行 `dependencies`（依赖行四选一来源；这里只用 stmt / lit 两种）。"""
    row = {
        "dep_id": dep_id, "used_by": used_by, "kind": "theorem",
        "label": label or used_by, "status": status, "path_group": int(path_group),
        "source_stmt_id": source_stmt_id or None,
        "source_lit_id": source_lit_id or None,
        "quote": quote, "status_reason": status_reason,
        "page_range": {}, "created_at": S.now_iso(), "created_by": "fixture",
    }
    with store.tx("dependencies", actor="fixture") as tx:
        tx.upsert("dependencies", row)
    return row


def _chain(tmp_path: pathlib.Path) -> Store:
    """A ← B ← C ← E 三层依赖 + 两条外部引用 + 一条文献根（判据 a / f 的现场）。

        000001 A（无依赖边 ⇒ 根：无前提）
        000002 B 依赖 A
        000003 C 依赖 B
        000004 E 依赖 C
        000007 G 依赖文献 0001（外部根）
    """
    st = _store(tmp_path)
    _seed_stmt(st, "000001", label="A", full="若 p 整除 |G|，则 G 有 p 阶元。")
    _seed_stmt(st, "000002", label="B", full="由 A 可得 B。", kind="lemma")
    _seed_stmt(st, "000003", label="C", full="由 A 可得 C。", kind="proposition")
    _seed_stmt(st, "000004", label="E", full="由 C 可得 E。", kind="theorem")
    _seed_stmt(st, "000007", label="G", full="由文献 [1] 可得 G。", kind="theorem")
    _seed_dep(st, "000101", "stmt:000002", source_stmt_id="000001",
              label="第 1 步：用 A", quote="由 A 可得")
    _seed_dep(st, "000102", "stmt:000003", source_stmt_id="000002",
              label="第 2 步：用 B", quote="由 B 可得")
    _seed_dep(st, "000103", "stmt:000004", source_stmt_id="000003",
              label="第 3 步：用 C", quote="由 C 可得")
    _seed_dep(st, "000107", "stmt:000007", source_lit_id="000001",
              label="文献 [1] 定理 1.5")
    # 外部引用方：这三族的 used_by 不是命题 ⇒ 不建节点（只作为边的外部根读数）。
    _seed_dep(st, "000201", "doc:0001#claim-3", source_stmt_id="000001",
              label="本仓另一份稿的断言引了 A")
    _seed_dep(st, "000202", "relation:0007", source_stmt_id="000002",
              label="概念关系引了 B")
    _seed_dep(st, "000203", "experiment:0002", source_stmt_id="000003",
              label="实验引了 C")
    return st


def _paths(tmp_path: pathlib.Path) -> Store:
    """两条证明路径（#p1 / #p2）+ 两条断链（不在册 / 未闭合）+ 一条概念行。

        000010 D
          #p1 (path_group 1) → B（000002）→ A（000001）     ⇒ 到根
          #p2 (path_group 1) → C（000003）→ B → A           ⇒ 到根
          #p3               → 000099（不在台账里）           ⇒ broken（断在不在册）
          #p4               → 没有来源、status=dangling      ⇒ broken（断在未闭合）
        000020 概念（kind=concept）：没有入边 / 出边 —— 如实给空并说明原因。
    """
    st = _store(tmp_path)
    _seed_stmt(st, "000001", label="A", full="A 的正文。")
    _seed_stmt(st, "000002", label="B", full="B 的正文。", kind="lemma")
    _seed_stmt(st, "000003", label="C", full="C 的正文。", kind="proposition")
    _seed_stmt(st, "000010", label="D", full="D 的正文（引两条路径）。")
    _seed_dep(st, "000101", "stmt:000002", source_stmt_id="000001",
              label="第 1 步：用 A")
    _seed_dep(st, "000102", "stmt:000003", source_stmt_id="000002",
              label="第 2 步：用 B")
    _seed_dep(st, "000301", "stmt:000010", source_stmt_id="000002",
              label="路径 1 第 1 步：用 B", quote="由 B 可得", path_group=1)
    _seed_dep(st, "000302", "stmt:000010#p2", source_stmt_id="000003",
              label="路径 2 第 1 步：用 C", quote="由 C 可得", path_group=1)
    _seed_dep(st, "000303", "stmt:000010#p3", source_stmt_id="000099",
              label="路径 3（断在不在册）", path_group=1)
    _seed_dep(st, "000304", "stmt:000010#p4", label="路径 4（未闭合）",
              status="dangling", status_reason="夹具：来源拿不到", path_group=1)
    _seed_stmt(st, "000020", kind="concept", label="原始概念",
               full="原始概念的定义（没有命题依赖它）。")
    return st


def _registry(index: LI.LedgerIndex) -> ToolRegistry:
    """把 `ledger.` 两件装进一张只含它们的注册表（索引外部传入）。"""
    reg = ToolRegistry(name="ledger-probe")
    LT.register(reg, index=index)
    return reg


# ---------------------------------------------------------------- a 索引


def test_a_forward_and_backward_adjacency_agree(tmp_path: pathlib.Path) -> None:
    """a：正 / 反邻接对得上；A ← B ← C 三层两向都查得到；外部族不入节点。"""
    st = _chain(tmp_path)
    index = LI.LedgerIndex.from_store(st)

    assert {"000001", "000002", "000003"} <= set(index.nodes), sorted(index.nodes)
    # 正邻接：source_stmt_id → (used_by, 依赖行读数)。外部引用方（doc:/relation:/
    # experiment:）也在这一侧，但它们不是命题 ⇒ 只作为边的读数（见下）。
    stmt_citers = lambda sid: [e["citer_stmt_id"] for e in index.by_source[sid]
                               if e["citer_stmt_id"]]
    assert stmt_citers("000001") == ["000002"], index.by_source["000001"]
    assert stmt_citers("000002") == ["000003"]
    # 反邻接：used_by → (source_stmt_id, 依赖行读数)
    assert [e["source_stmt_id"] for e in index.by_user["000002"]] == ["000001"]
    assert [e["source_stmt_id"] for e in index.by_user["000003"]] == ["000002"]
    # 两侧是同一批边（dep_id 逐条对得上）。
    for source, edges in index.by_source.items():
        for edge in edges:
            if not edge["citer_stmt_id"]:
                continue
            reverse = index.by_user.get(edge["citer_stmt_id"], [])
            assert any(r["dep_id"] == edge["dep_id"] and r["source_stmt_id"] == source
                       for r in reverse), (source, edge, reverse)
    for citer, edges in index.by_user.items():
        for edge in edges:
            if not edge["source_stmt_id"]:
                continue
            forward = index.by_source.get(edge["source_stmt_id"], [])
            assert any(f["dep_id"] == edge["dep_id"] and f["citer_stmt_id"] == citer
                       for f in forward), (citer, edge, forward)

    # 外部族（doc: / relation: / experiment:）不入节点，只作为边的外部根读数。
    assert not [n for n in index.nodes if n.split(":")[0] in ("doc", "relation", "experiment")]
    ext = [e for e in index.by_source["000001"] if e["external_citer"]]
    assert [e["used_by_head"] for e in ext] == ["doc:0001#claim-3"], ext
    assert index.nodes["000001"]["kind"] == "theorem"
    # 文献来源是依赖账里的合法根（不是断链）。
    lit = index.by_user["000007"][0]
    assert lit["source_root"]["kind"] == "literature", lit
    assert lit["source_root"]["id"] == "000001", lit
    # 读数：两边都数到了、外部引用方单独计。
    summary = index.summary()
    assert summary["node_count"] == 5, summary
    assert summary["external_citers"] == 3, summary


def test_a_index_is_read_only_and_statement_counts_are_honest(
        tmp_path: pathlib.Path) -> None:
    """a（续）：索引是只读快照 —— 建索引前后盘上两本账逐字不变。"""
    st = _chain(tmp_path)
    before = (json.dumps(st.rows("statements"), ensure_ascii=False, sort_keys=True),
              json.dumps(st.rows("dependencies"), ensure_ascii=False, sort_keys=True))
    index = LI.LedgerIndex.from_store(st)
    assert index.nodes and index.dependency_rows_total == len(st.rows("dependencies"))
    after = (json.dumps(st.rows("statements"), ensure_ascii=False, sort_keys=True),
             json.dumps(st.rows("dependencies"), ensure_ascii=False, sort_keys=True))
    assert before == after, "建索引写了盘（它只许读）"


# ---------------------------------------------------------------- b resolve


def test_b_resolve_by_number_label_and_the_honest_miss(tmp_path: pathlib.Path) -> None:
    """b：按号命中 / 按标签命中 / 找不到时明白说"没有"；候选不含证明正文。"""
    st = _chain(tmp_path)
    index = LI.LedgerIndex.from_store(st)

    by_number = index.resolve("stmt:000001")
    assert by_number["checked"] is True and by_number["found"] is True, by_number
    assert by_number["mode"] == "id", by_number
    assert by_number["hits_total"] == 1 and by_number["scanned"] == 5, by_number
    assert by_number["candidates"][0] == {
        "stmt_id": "000001", "kind": "theorem", "status": "active",
        "grade": "conjecture", "label": "A"}, by_number["candidates"]
    # 不带 `stmt:` 前缀与少写前导零都指同一条（同一套按号口径）。
    assert index.resolve("000001")["candidates"] == by_number["candidates"]
    assert index.resolve("0001")["candidates"] == by_number["candidates"]

    by_label = index.resolve("由 A 可得")
    assert by_label["checked"] is True and by_label["mode"] == "keywords", by_label
    assert [c["stmt_id"] for c in by_label["candidates"]] == ["000002", "000003"], by_label
    assert by_label["candidates"][0]["label"] == "B", by_label["candidates"]

    missing = index.resolve("999999")
    assert missing["checked"] is True and missing["found"] is False, missing
    assert missing["candidates"] == [], missing
    assert "没有编号 999999" in missing["why"], missing
    zero = index.resolve("根本不存在的一个词")
    assert zero["checked"] is True and zero["hits_total"] == 0, zero
    assert "命中 0 条" in zero["why"] and "不是「台账里没有」" in zero["why"], zero

    # 候选只五格：不含证明正文（也不含命题全文）。
    payload = json.dumps(by_number["candidates"] + by_label["candidates"],
                         ensure_ascii=False)
    assert PROOF_MARKER not in payload, payload
    assert "proof_text" not in payload, payload
    assert set(by_number["candidates"][0]) == {"stmt_id", "kind", "status", "grade",
                                               "label"}


def test_b_concept_rows_are_ordinary_nodes_with_not_applicable_grade(
        tmp_path: pathlib.Path) -> None:
    """b（续，概念平权）：概念行按同一套口径查得到，等级如实给 not_applicable。"""
    st = _paths(tmp_path)
    index = LI.LedgerIndex.from_store(st)
    got = index.resolve("000020")
    assert got["found"] is True, got
    candidate = got["candidates"][0]
    assert candidate["kind"] == "concept", candidate
    assert candidate["grade"] == LI.EB.GRADE_NOT_APPLICABLE, candidate
    # 概念节点就是普通节点：同一套字段、没有为它开的特例。
    tree = index.expand("000020", 1)
    node = tree["nodes"][0]
    assert set(REQUIRED_NODE_FIELDS) <= set(node), sorted(node)
    assert node["kind"] == "concept"
    assert node["grade"] == "not_applicable"
    # 没有入边 / 出边 ⇒ 如实给空 + 说明原因（"台账里没有命题依赖它" ≠ "它没有关系"）。
    assert node["dependency_face"]["groups"] == []
    assert node["dependency_face"]["root_kind"] == "primitive_concept"
    assert "没有一条依赖边" in node["dependency_face"]["why"], node["dependency_face"]
    assert node["cited_face"]["citations"] == []
    assert "没有一条依赖边" in node["cited_face"]["why"], node["cited_face"]


# ---------------------------------------------------------------- c 缺 depth


def _missing_depth_problem(result: Any) -> list[str]:
    """判据（c）的判据本体：返回问题清单（空 = 这一问合口径）。

    抽成函数是为了让反真空能直接打在它身上（h 的第一条）：一个"有默认值"的
    `expand` 会返回树 ⇒ 这里必须报红。
    """
    problems: list[str] = []
    if result.ok:
        problems.append("缺 `depth` 却返回了结果（工具层不许替 C 决定层数）")
    if result.data is not None:
        problems.append("缺 `depth` 却给了 data（返回值里有树）")
    text = str(result.error or "")
    if "层数由你决定、必填" not in text:
        problems.append("缺参数提示里没写清『层数由你决定、必填』")
    if "ledger.expand(node=\"stmt:000123\", depth=2)" not in text:
        problems.append("缺参数提示里没有可照抄的例子")
    return problems


def test_c_missing_depth_is_a_hint_and_never_a_tree(tmp_path: pathlib.Path) -> None:
    """c：缺 `depth` ⇒ 缺参数提示（含口径与例子），不返回树。"""
    index = LI.LedgerIndex.from_store(_chain(tmp_path))
    reg = _registry(index)
    res = reg.call("ledger.expand", role="C", node="stmt:000002")
    assert not res.ok, res
    assert res.data is None, res
    assert _missing_depth_problem(res) == [], res.error
    # 参数面也别写默认值：`depth` 不在 required（否则模型看到的是通用缺参，
    # 读不到"层数由你决定"这句），也不带 `default`。
    spec = LT.ledger_expand.__tool_spec__
    assert "depth" not in (spec.params.get("required") or []), spec.params
    assert "default" not in spec.params["properties"]["depth"], spec.params


# ---------------------------------------------------------------- d 七样字段


def _node_field_problem(tree: dict[str, Any]) -> list[str]:
    """判据（d）的判据本体：节点七样齐、且不许带证明正文。"""
    problems: list[str] = []
    nodes = tree.get("nodes") or []
    if not nodes:
        return ["树里一个节点都没有 ⇒ 判据失去对象（不是通过）"]
    for node in nodes:
        missing = [f for f in REQUIRED_NODE_FIELDS if f not in node]
        if missing:
            problems.append(f"{node.get('stmt_id')}：缺字段 {missing}")
        if "proof_text" in node:
            problems.append(f"{node.get('stmt_id')}：节点里带了 proof_text")
        rel = node.get("relation") or {}
        for key in ("direction", "distance", "via", "via_text"):
            if key not in rel:
                problems.append(f"{node.get('stmt_id')}：relation 缺 {key}")
    payload = json.dumps(tree, ensure_ascii=False)
    if PROOF_MARKER in payload:
        problems.append("证明正文进了树（哨兵出现在返回值里）")
    if '"proof_text"' in payload:
        problems.append("树里出现了 proof_text 这一格")
    return problems


def test_d_every_node_carries_the_seven_fields_and_no_proof_text(
        tmp_path: pathlib.Path) -> None:
    """d：`expand(depth=1)` 七样齐；`statement_full` 在、`proof_text` 不在。"""
    st = _chain(tmp_path)
    index = LI.LedgerIndex.from_store(st)
    tree = index.expand("000002", 1)
    assert tree["checked"] is True and not tree["truncated"], tree.get("reasons")
    assert _node_field_problem(tree) == [], _node_field_problem(tree)

    by_id = {n["stmt_id"]: n for n in tree["nodes"]}
    assert set(by_id) == {"000001", "000002", "000003"}, sorted(by_id)
    root = by_id["000002"]
    assert root["relation"] == {"direction": "root", "distance": 0,
                                "via": [], "via_text": "（选定节点）"}, root["relation"]
    up = by_id["000001"]
    assert up["relation"]["direction"] == "up" and up["relation"]["distance"] == 1
    assert up["relation"]["via"][-1]["to"] == "stmt:000001", up["relation"]
    down = by_id["000003"]
    assert down["relation"]["direction"] == "down" and down["relation"]["distance"] == 1
    assert root["kind"] == "lemma" and up["kind"] == "theorem", (root["kind"], up["kind"])
    assert root["statement_full"] == "由 A 可得 B。", root["statement_full"]
    assert root["grade"] == "conjecture", root
    # 依赖面 / 被引面都在（形状由 e / f 逐条钉）。
    assert root["dependency_face"]["groups"], root["dependency_face"]
    assert [c["citer_stmt_id"] for c in root["cited_face"]["citations"]
            if c["citer_stmt_id"]] == ["000003"]


# ---------------------------------------------------------------- e 依赖面全路径 + 分组


def _dependency_face_problem(face: dict[str, Any]) -> list[str]:
    """判据（e）的判据本体：每组都到根、断链必须点名、组间不许并。"""
    problems: list[str] = []
    if not face.get("checked"):
        return ["依赖面没查成 ⇒ 判据失去对象（不是通过）"]
    groups = face.get("groups") or []
    if not groups:
        return ["没有依赖组 ⇒ 判据失去对象（不是通过）"]
    for group in groups:
        chains = group.get("chains") or []
        if not chains:
            problems.append(f"{group.get('group')}：一条链都没有（悄悄少给了）")
        for chain in chains:
            if chain.get("status") == "ok":
                root = chain.get("root") or {}
                if not root.get("kind"):
                    problems.append(
                        f"{group.get('group')}：链 {chain.get('chain')} 标 ok 却没有根")
                if not chain.get("chain"):
                    problems.append(f"{group.get('group')}：链是空的")
            elif chain.get("status") == "broken":
                if not (chain.get("break_at") or {}).get("why"):
                    problems.append(
                        f"{group.get('group')}：断链没指出断在哪（break_at 空）")
                if not group.get("broken"):
                    problems.append(f"{group.get('group')}：有断链却没标 broken")
            else:
                problems.append(f"{group.get('group')}：status 既不是 ok 也不是 broken")
    return problems


def test_e_dependency_face_is_full_path_grouped_by_proof(tmp_path: pathlib.Path) -> None:
    """e：`#p1` / `#p2` 两组分开、各自到根；断链标 broken 并指出断点。"""
    st = _paths(tmp_path)
    index = LI.LedgerIndex.from_store(st)
    face = index.dependency_face("000010")
    assert _dependency_face_problem(face) == [], _dependency_face_problem(face)

    groups = {g["group"]: g for g in face["groups"]}
    assert set(groups) == {"#p1", "#p2", "#p3", "#p4"}, sorted(groups)
    # 两条真路径各自到根（A 没有依赖边 ⇒ 无前提根），链上保留每一跳与"用在哪一步"。
    p1 = groups["#p1"]["chains"][0]
    assert p1["chain"] == ["stmt:000010", "stmt:000002", "stmt:000001"], p1
    assert p1["root"]["kind"] == "no_premise", p1["root"]
    assert [s["used_at"] for s in p1["steps"]] == ["路径 1 第 1 步：用 B",
                                                   "第 1 步：用 A"], p1["steps"]
    p2 = groups["#p2"]["chains"][0]
    assert p2["chain"] == ["stmt:000010", "stmt:000003", "stmt:000002", "stmt:000001"], p2
    assert p2["root"]["kind"] == "no_premise", p2["root"]
    # 两组不并：`#p1` 的直接边只有 B 那条、`#p2` 的直接边只有 C 那条。
    assert [e["citer_stmt_id"] for e in groups["#p1"]["edges"]] == ["000010"]
    assert [e["source_stmt_id"] for e in groups["#p1"]["edges"]] == ["000002"]
    assert [e["source_stmt_id"] for e in groups["#p2"]["edges"]] == ["000003"]
    # 断链两档：不在册 / 未闭合 —— 都标 broken 并指出断在哪一条边。
    p3 = groups["#p3"]
    assert p3["broken"] is True and p3["chains"][0]["status"] == "broken", p3
    assert p3["chains"][0]["break_at"]["dep_id"] == "000303", p3["chains"][0]
    assert "不在册" in p3["chains"][0]["break_at"]["why"], p3["chains"][0]
    p4 = groups["#p4"]
    assert p4["broken"] is True, p4
    assert p4["chains"][0]["break_at"]["status"] == "dangling", p4["chains"][0]
    assert "没有闭合" in p4["chains"][0]["break_at"]["why"], p4["chains"][0]


def test_e_literature_is_a_root_not_a_broken_chain(tmp_path: pathlib.Path) -> None:
    """e（续）：`source_lit_id` 那一端是根（文献），不是断链。"""
    st = _chain(tmp_path)
    index = LI.LedgerIndex.from_store(st)
    face = index.dependency_face("000007")
    assert _dependency_face_problem(face) == [], _dependency_face_problem(face)
    chain = face["groups"][0]["chains"][0]
    assert chain["status"] == "ok", chain
    assert chain["root"]["kind"] == "literature" and chain["root"]["id"] == "000001", chain


# ---------------------------------------------------------------- f 被引面只一层


def test_f_cited_face_is_one_layer_only(tmp_path: pathlib.Path) -> None:
    """f：三层场景下被引面只出现直接引用者（不往下多走一层）。"""
    st = _chain(tmp_path)
    index = LI.LedgerIndex.from_store(st)
    tree = index.expand("000002", 3, direction="down")
    assert {n["stmt_id"] for n in tree["nodes"]} == {"000002", "000003", "000004"}, (
        sorted(n["stmt_id"] for n in tree["nodes"]))
    by_id = {n["stmt_id"]: n for n in tree["nodes"]}
    cited = by_id["000002"]["cited_face"]
    assert cited["checked"] is True, cited
    assert [c["citer_stmt_id"] for c in cited["citations"] if c["citer_stmt_id"]] == [
        "000003"], cited
    # 外部引用方也如实给（`relation:0007` 引了 B），但它不是命题、只占边读数。
    assert [c["used_by"] for c in cited["citations"] if c["external_citer"]] == [
        "relation:0007"], cited
    assert "000004" not in [c["citer_stmt_id"] for c in cited["citations"]], (
        "被引面多给了一层（把间接引用者也算进来了）")
    # 子节点自己的被引面仍是一层：C 的被引面里有 E。
    assert [c["citer_stmt_id"] for c in by_id["000003"]["cited_face"]["citations"]
            if c["citer_stmt_id"]] == ["000004"]


# ---------------------------------------------------------------- g 增量


def test_g_second_expand_of_the_same_node_returns_only_the_increment(
        tmp_path: pathlib.Path) -> None:
    """g：同一 node 再 expand ⇒ `already_known` 命中、节点不重复。"""
    st = _chain(tmp_path)
    index = LI.LedgerIndex.from_store(st)
    reg = _registry(index)
    first = reg.call("ledger.expand", role="C", node="stmt:000002", depth=1)
    assert first.ok, first.error
    first_ids = {n["stmt_id"] for n in first.data["nodes"]}
    assert first_ids == {"000001", "000002", "000003"}, first_ids
    assert first.data["already_known"] == [], first.data["already_known"]

    second = reg.call("ledger.expand", role="C", node="stmt:000002", depth=1)
    assert second.ok, second.error
    assert second.data["added_nodes"] == [], second.data["added_nodes"]
    assert second.data["nodes"] == [], second.data["nodes"]
    known = {one["stmt_id"] for one in second.data["already_known"]}
    assert known == first_ids, known
    # 不重复同一批字段：already_known 只有身份四格，没有正文 / 依赖面。
    for one in second.data["already_known"]:
        assert set(one) == {"stmt_id", "kind", "status", "label"}, one
    # 换一层（不同参数）是另一问，不该被上一问的增量账吃掉。
    deeper = reg.call("ledger.expand", role="C", node="stmt:000002", depth=2)
    assert deeper.ok and {n["stmt_id"] for n in deeper.data["nodes"]} == {
        "000001", "000002", "000003", "000004"}, [
        n["stmt_id"] for n in deeper.data["nodes"]]


# ---------------------------------------------------------------- h 反真空


def _registry_with_default_depth(index: LI.LedgerIndex) -> ToolRegistry:
    """把 `depth` 改成有默认值的那一版（反真空：c 必须红）。"""
    reg = ToolRegistry(name="ledger-default-depth")
    holder = LI.LedgerHolder(index=index)

    def defaulted(holder: Any, node: str = "", depth: Any = 1,
                  direction: str = "both"):  # pragma: no cover - 只在反真空里用
        return LT.ledger_expand(holder, node, depth, direction)

    spec = replace(LT.ledger_expand.__tool_spec__, handler=partial(defaulted, holder))
    reg.register(spec)
    return reg


def test_h_a_default_depth_turns_c_red(tmp_path: pathlib.Path) -> None:
    """h①：把 `depth` 改成有默认值 ⇒ 缺参数那一问会悄悄返回树 ⇒ c 的判据红。"""
    index = LI.LedgerIndex.from_store(_chain(tmp_path))
    reg = _registry_with_default_depth(index)
    res = reg.call("ledger.expand", role="C", node="stmt:000002")
    assert res.ok is True and res.data is not None, res
    problems = _missing_depth_problem(res)
    assert problems, "depth 有默认值了，c 的判据却还是绿的 ⇒ 它没在核东西"


def test_h_a_one_layer_dependency_face_turns_e_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """h②：把依赖面只展开一层 ⇒ e 的判据红（链标 ok 却没有根）。"""
    st = _paths(tmp_path)
    index = LI.LedgerIndex.from_store(st)
    real = LI.LedgerIndex.dependency_face

    def one_layer(self: LI.LedgerIndex, stmt_id: Any,
                  **kwargs: Any) -> dict[str, Any]:
        face = real(self, stmt_id, **kwargs)
        for group in face.get("groups") or []:
            group["chains"] = [
                {"chain": chain["chain"][:2], "steps": chain["steps"][:1],
                 "root": {}, "status": "ok", "break_at": {}}
                for chain in group["chains"]]
            group["broken"] = False
        return face

    monkeypatch.setattr(LI.LedgerIndex, "dependency_face", one_layer)
    tree = LI.LedgerIndex.from_store(st).expand("000010", 1)
    problems = _dependency_face_problem(tree["nodes"][0]["dependency_face"])
    assert problems, "依赖面只给了一层，e 的判据却还是绿的 ⇒ 它没在核到根"


def test_h_proof_text_in_a_node_turns_d_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """h③：把证明正文塞进节点 ⇒ d 的判据红。"""
    st = _chain(tmp_path)
    real = LI.LedgerIndex._read_node

    def with_proof_text(self: LI.LedgerIndex, sid: str,
                        relation: dict[str, Any]) -> dict[str, Any]:
        reading = real(self, sid, relation)
        row = next((r for r in self.rows if r.get("stmt_id") == sid), {})
        reading["proof_text"] = str(row.get("proof_text") or "")
        return reading

    monkeypatch.setattr(LI.LedgerIndex, "_read_node", with_proof_text)
    tree = LI.LedgerIndex.from_store(st).expand("000002", 1)
    problems = _node_field_problem(tree)
    assert problems, "证明正文塞进了节点，d 的判据却还是绿的 ⇒ 它没在核这一格"


# ---------------------------------------------------------------- i 题面（并入本批）


def _prompt_teaching_problem(text: str) -> list[str]:
    """判据（i）的判据本体：C 的渲染题面必须教"选根 → 展开 → 拼接"，不许再教手算。"""
    problems: list[str] = []
    if "ledger.resolve" not in text:
        problems.append("题面里没有 `ledger.resolve`（选根）")
    if "ledger.expand" not in text:
        problems.append("题面里没有 `ledger.expand`（按层展开）")
    if "层数由你决定、必填" not in text:
        problems.append("题面没写清『层数由你决定、必填』")
    if "frontier" not in text:
        problems.append("题面没教『不够就对 frontier 拼接』")
    for banned in ('table.list(table="dependencies"', "table.list(table='dependencies'"):
        if banned in text:
            problems.append(f"题面里还留着按 dependencies 表手算的多跳指令：{banned}")
    return problems


def test_i_c_prompt_teaches_the_local_tree_instead_of_hand_computation(
        tmp_path: pathlib.Path) -> None:
    """i：C 的渲染题面出现 `ledger.resolve` / `ledger.expand`，且字面禁止手算指令。"""
    from agentflow import agent_prompts as AP
    from agentflow.tools import build_for_role

    st = _store(tmp_path)
    built = build_for_role("C", store=st, workspace_root=str(st.root))
    text = AP.system_prompt("C", registry=built.registry, task="判据夹具",
                            workspace_root=str(st.root))
    assert _prompt_teaching_problem(text) == [], _prompt_teaching_problem(text)
    # 污染面只许作为"查询模式"出现，不许被写成一件工具。
    assert "污染面是一种查询模式" in text, text[-1200:]
    assert "不是一件工具" in text, text[-1200:]


def test_i_the_old_hand_computation_prompt_turns_the_criterion_red() -> None:
    """i（反真空）：改前那段手算教法喂进同一判据 ⇒ 必须红（它不是橡皮图章）。"""
    old = (
        "被问「这条结论靠什么站着」时给两样读数：最短依赖链与污染面。"
        '用 `table.list(table="dependencies", filter={"source_stmt_id": "<这条命题号>"})` '
        "读依赖行；取 `used_by` 里 `stmt:` 前缀的那些，再对每个号重复一遍、去重、直到不再长出新号。"
    )
    problems = _prompt_teaching_problem(old)
    assert problems, "改前那段手算教法喂进来却判绿 ⇒ 这条题面判据是空的"
    assert any("ledger.resolve" in one for one in problems), problems
    assert any("table.list" in one for one in problems), problems


def test_the_ledger_box_is_read_only_and_model_free() -> None:
    """结构判据：索引模块里没有写盘 / 判定 / 事务调用（只读是结构，不是自觉）。"""
    text = (SRC / "agentflow" / "ledgerindex.py").read_text(encoding="utf-8")
    for banned in ("tx.upsert", "alloc_id", "mark_dirty", "judge(", "write_text",
                   "open("):
        assert banned not in text, f"索引模块里出现了写 / 判定调用：{banned}"


if __name__ == "__main__":  # pragma: no cover - 手工跑这一份时用
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
