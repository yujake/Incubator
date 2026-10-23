# -*- coding: utf-8 -*-
"""判据：依赖的读侧接上"证明 × path_group"的二维结构（S3 读侧，业主 2026-10-22）。

## 这一份守什么

多证明模型（`proofloc` / `verifications.PROOFS_KEY`）此前只接在"签名 → 命题行"那一侧：
`dependencies.used_by` 可以写成 `stmt:0004#p2`，而读侧（C 的依赖链、收工读数 R10）
仍把整条 `used_by` 当字符串比 —— 于是第 2 条证明的依赖要么被记成"另一条命題"，
要么与第 1 条合并（借光）。这一份逐条钉住四件事：

- 读侧的分组键是 `(证明号, path_group)` 两层，`path_group` 的语义一个字没改；
- `doc:` 前缀的 `used_by` 先分流再走 `proofloc`（它的 `#` 后面是 claim 号）；
- 坏尾巴（`#pabc` / `#p0` / 多段 …）在"这是不是一个证明号"这一问上返回 0，不许折成第 1 条；
- 收工读数 R10 的计数键是 `(stmt_id, proof_no)`。

## 判据与它们各自的改前形态

| 判据 | 改前红在哪里 |
|---|---|
| ① 向后兼容（真机那 8 行，现读 `tests/fixtures/p3-verify2-dependencies-8rows.json`） | `groups_of` 返回 `dict[int, list]`，`two_d[1]` 取不到"证明号那一层" |
| ② 二维：`#p2` + 两组路径 | 同上；且 `groups_of("000004")` 查不到 `stmt:000004#p2` 挂的边 |
| ③ 负控：`#p1` 与 `#p2` 不许合并 | 旧索引按整条 `used_by` 建键，`#p2` 的边落到 `"000004#p2"` 这个键上，查询 `000004` 读不到它（静默丢边） |
| ④ 负控：`doc:0001#claim-3` 走 `doc:` 分支 | 没有分流函数；直接送进 `proofloc` ⇒ `problem` 非空（正常 claim 引用被记成坏尾巴） |
| ⑤ 负控：`as_proof_no("stmt:000004#pabc")` = 0 | 旧实现 `parse_used_by(text)[1]` 把它折成 1 |
| ⑥ R10 按 `(stmt, proof)` 计数 | `counted` 里一条命题一行，读不出"是哪一条证明" |

全部 tmp 工作区、零模型调用（R10 那条只走 `record_verification` 的写入口）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑：
# "改前红"就是把 `git archive HEAD` 的整树铺到临时目录、再把这一份放进去跑）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import closing as CL
from agentflow import evidencebits as EB
from agentflow import proofloc as PL
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_c import AgentC
from agentflow.agent_c.proof_chain import _DepGraph
from agentflow.store import Store

TS = "2026-10-22T00:00:00+08:00"
SID = S.format_id(4)
PROOF1 = "1. 由定义直接得到。\n2. 由 1 与假设 n ≥ 3 得结论。"
PROOF2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
STATEMENT = "设 G 是 3-正则群；则弦长函数不是常值。"
STATEMENT_TEXT = "弦长函数不是常值"

#: 那一份真机读数的夹具：8 行、不带 `#pN`、全在 `path_group 1`。
#:
#: 为什么从 `projects/p3-verify2/data/dependencies.json` 搬成夹具（D7，2026-10-22 读数）：
#: 那份活数据被 `.gitignore` 了，且在真机上又写进了 5 行（13 行 vs 这里的 8 行断言），
#: 于是这条判据在干净树上只能靠"那个项目恰好还在盘上、且恰好还是 8 行"才绿 ——
#: 它读的是现场，不是契约。夹具是这 8 行逐字节的搬移（`schema_version` 一起搬），
#: 行数断言一个字没动：契约就是"这 8 行怎么分组"，不是"盘上现在有几行"。
FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "fixtures"
#: 真机读数搬过来的那一份（8 行）。判据只读它；`projects/` 下那份活数据不再是输入。
_REAL_DEPENDENCIES = FIXTURE_DIR / "p3-verify2-dependencies-8rows.json"


# ------------------------------------------------------------------ 小工具

def _real_rows(path: pathlib.Path | None = None) -> list[dict]:
    """那 8 行（缺省读夹具；`path` 只给"这条判据真的在读夹具"那条负控用）。

    行数断言（`== 8`）刻意不动：判据要的是"这 8 行怎么分组"，不是"盘上现在有几行"。
    """
    data = json.loads((path or _REAL_DEPENDENCIES).read_text(encoding="utf-8"))
    rows = data["rows"]
    assert isinstance(rows, list) and len(rows) == 8, rows
    return [dict(r) for r in rows]


def _edge(dep_id: str, used_by: str, *, stmt: str = "", lit: str = "",
          group: int = 1, status: str = "closed") -> dict:
    """一条只读图用的依赖行（形状与盘上那一行同键；`_DepGraph` 只读这几格）。"""
    return {"dep_id": dep_id, "used_by": used_by, "kind": "theorem" if stmt else "prior_art",
            "label": stmt or lit, "status": status, "status_reason": "",
            "source_lit_id": lit or None, "source_experiment_id": None,
            "source_stmt_id": stmt or None, "path_group": group}


def _graph(rows: list[dict]) -> _DepGraph:
    return _DepGraph(stmts=[], deps=rows, exps=[], lits=[])


def _one_dimensional(rows: list[dict], used_by: str) -> dict[int, list[dict]]:
    """改前的那一维口径：只按 `path_group` 分组，"一条证明一条路径"。

    这是判据 ① 的对照物 —— 自己写一遍（而不是调被测代码），否则"等价"就成了
    "同一个函数等于它自己"。
    """
    bare = used_by[5:] if used_by.startswith("stmt:") else used_by
    out: dict[int, list[dict]] = {}
    for r in rows:
        used = str(r.get("used_by") or "")
        key = used[5:] if used.startswith("stmt:") else used
        if key not in (bare, used_by) and used not in (bare, used_by):
            continue
        out.setdefault(int(r.get("path_group") or 1), []).append(dict(r))
    return out


def _flatten(two_d: dict[int, dict[int, list[dict]]], proof_no: int = 1) -> dict[int, list]:
    """把二维读数压回一维（只取某一条证明那一层）—— 用来与改前逐字比。

    前提是"证明号那一层"真的在（调用方先断言形状）；这里不替改前形态兜底：
    兜底会把"改前分组结果没有这一层"这个事实藏起来，而那正是判据 ① 要报的东西。
    """
    return {g: list(edges) for g, edges in (two_d[proof_no] or {}).items()}


def _router():
    """读侧的 `doc:` 分流函数（判据 ④ 用；改前形态里没有它）。"""
    from agentflow.agent_c import proof_chain as PC

    fn = getattr(PC, "_split_used_by", None)
    assert fn is not None, (
        "读侧没有 `doc:` 分流这一步：`used_by` 的尾巴必须先按 `stmt:` 前缀分流再交给"
        "`proofloc`，否则 `doc:0001#claim-3` 的 `#claim-3` 会被记成坏尾巴")
    return fn


def _dep_ids(by_group: dict[int, list[dict]]) -> dict[int, list[str]]:
    return {g: [str(d.get("dep_id") or "") for d in edges] for g, edges in by_group.items()}


def _one_dim_reading(got: list[dict]) -> list[dict]:
    """去掉"证明号"那一维之后的链读数（判据 ② 的同构比较用它）。"""
    out = []
    for g in got:
        item = {k: v for k, v in g.items() if k not in ("proof_no", "hops")}
        item["hops"] = [{k: v for k, v in h.items() if k != "proof_no"} for h in g["hops"]]
        out.append(item)
    return out


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _stmt(st: Store, sid: str, *, evidence: str = "cross_check",
          proof_text: str = "", kind: str = "theorem") -> None:
    row = S.Statement(stmt_id=sid, origin="own_result", kind=kind,
                      label=f"命题 {sid}", statement_text="短版",
                      statement_full="若假设 A 成立，则结论 B 成立",
                      proof_text=proof_text, evidence_kind=evidence,
                      quote_verified=None, quote_reason="夹具（还没核）",
                      status="active", created_at=TS)
    row.validate()
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())


def _lit(st: Store, lid: str) -> None:
    row = S.Literature(lit_id=lid, title=f"文献 {lid}", type="J", summary="s",
                       path=None, added_at=TS)
    row.validate()
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict())


def _dep(st: Store, did: str, used_by: str, *, stmt: str = "", lit: str = "",
         group: int = 1) -> dict:
    row = S.Dependency(dep_id=did, used_by=used_by, kind="theorem" if stmt else "prior_art",
                       label="前提", status="closed", status_reason="",
                       source_stmt_id=stmt or None, source_experiment_id=None,
                       source_lit_id=lit or None, path_group=group, created_at=TS)
    row.validate()
    with st.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", row.to_dict(), note="dep")
    return row.to_dict()


def _r10(store: Store) -> tuple[int, dict]:
    return CL._leg_reading(store, "reviewed_proof_rows", store.root)


# ================================================== ① 向后兼容（真机那 8 行，读夹具）

def test_the_eight_rows_come_from_the_fixture_and_nine_rows_turn_the_reading_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """负控（D7）：判据读的是夹具，不是 `projects/` 下那份活数据；夹具 9 行 ⇒ 必须红。

    这条是 ① 的反真空：把输入换成"另一份 9 行"之后，① 的行数断言必须照样响。
    没有这一条，"判据读夹具"就只是注释里的一句话 —— 它可能读的是盘上那份活数据，
    而活数据今天恰好不是 8 行（实测 13 行 ⇒ ① 在干净树上红）。
    """
    assert _REAL_DEPENDENCIES.parent == FIXTURE_DIR, _REAL_DEPENDENCIES
    assert "projects" not in _REAL_DEPENDENCIES.parts, (
        f"判据还在读 `projects/` 下的活数据：{_REAL_DEPENDENCIES}")
    doc = json.loads(_REAL_DEPENDENCIES.read_text(encoding="utf-8"))
    assert len(doc["rows"]) == 8, len(doc["rows"])

    nine = tmp_path / "p3-verify2-dependencies-9rows.json"
    doc["rows"].append(dict(doc["rows"][-1], dep_id="000008", used_by="stmt:000005"))
    nine.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8", newline="\n")
    monkeypatch.setattr(sys.modules[__name__], "_REAL_DEPENDENCIES", nine)
    with pytest.raises(AssertionError):
        _real_rows()


def test_the_real_eight_rows_group_exactly_as_the_one_dimensional_reading():
    """判据 ①：真机那 8 行（不带 `#pN`、全在 `path_group 1`）分组读数逐字不变。

    改前红：`groups_of` 返回 `dict[int, list]`（没有证明号那一层）⇒ `two_d[1]` 是
    `KeyError`，而这里要的正是"第 1 条证明那一层"与一维读数逐条相等。
    """
    rows = _real_rows()
    # 没有一条带 `#pN` ⇒ 证明号那一维只有 canonical 一条。
    assert PL.proof_nos_of([str(r["used_by"]) for r in rows]) == [1]

    graph = _graph(rows)
    for used_by, expected_dep_ids in (
        ("stmt:000001", {1: ["000000"]}),
        ("stmt:000002", {1: ["000001"]}),
        ("stmt:000003", {1: ["000002", "000003", "000004"]}),
        ("stmt:000004", {1: ["000005", "000006", "000007"]}),
    ):
        two_d = graph.groups_of(used_by)
        assert list(two_d) == [1], (used_by, sorted(two_d))
        # 第一层必须是"证明号"（`{1: {组: 边}}`）；改前形态 `{组: 边}` 没有这一层。
        assert isinstance(two_d[1], dict), (
            f"{used_by} 的分组结果第一层不是证明号（收到 {type(two_d[1]).__name__}）："
            "改前形态 `dict[int, list]` 里没有'第几条证明'这一维")
        flat = _flatten(two_d)
        assert _dep_ids(flat) == expected_dep_ids, (used_by, _dep_ids(flat))
        # 与"一条证明一条路径"的一维口径逐字等价（含行的字段，不只是 id）。
        assert flat == _one_dimensional(rows, used_by), used_by
        assert repr(flat) == repr(_one_dimensional(rows, used_by)), used_by

    # 裸号写法（`000004` 与 `stmt:000004`）读到同一批边 —— 两种写法一处口径。
    assert _flatten(graph.groups_of("000004")) == _flatten(graph.groups_of("stmt:000004"))


# ================================================== ② 二维

def test_proof_two_keeps_its_own_path_groups():
    """判据 ②：`stmt:000004#p2` 的两组路径 ⇒ `{2: {1: [...], 2: [...]}}`。

    改前红：旧索引按整条 `used_by` 建键 ⇒ `groups_of("000004")` 是空字典
    （`stated:000004#p2` 的边挂在 `"000004#p2"` 那个键上），断言 `list(two_d) == [2]` 直接失败。
    """
    rows = [
        _edge("000001", "stmt:000004#p2", stmt="000002", group=1),
        _edge("000002", "stmt:000004#p2", lit="0009", group=2),
    ]
    two_d = _graph(rows).groups_of("stmt:000004")
    assert list(two_d) == [2], two_d
    assert sorted(two_d[2]) == [1, 2], two_d
    assert _dep_ids(two_d[2]) == {1: ["000001"], 2: ["000002"]}, two_d
    # 证明号那一维不串门：`#p2` 的边不许出现在第 1 条证明下。
    assert 1 not in two_d


def test_the_group_readings_are_isomorphic_to_the_one_dimensional_ones(tmp_path: pathlib.Path):
    """判据 ②（后半）：同一条证明之内，组内 AND / 组间 OR 的读数与一维时同构。

    两棵一模一样的树，只有 `used_by` 的写法不同（`stmt:0004` 与 `stmt:0004#p2`）：
    去掉"证明号"那一维之后，逐组读数必须完全相等（`length` / `reached` / `hops` / …）。
    改前红：`proof_chain` 只按 `path_group` 展开 —— 二维那一棵树里 `#p2` 的边查不到，
    读数变成 0 组（`groups_total` 相等这一条先失败）。
    """
    def _build(root: pathlib.Path, used_by: str) -> Store:
        st = _ws(root)
        _stmt(st, "0004")
        _stmt(st, "0002")
        _lit(st, "0009")
        _dep(st, "0001", used_by, stmt="0002", group=1)     # 长路径：0004 → 0002 → lit:0009
        _dep(st, "0002", "stmt:0002", lit="0009", group=1)
        _dep(st, "0003", used_by, lit="0009", group=2)      # 短路径：0004 → lit:0009
        return st

    one = AgentC(_build(tmp_path / "one", "stmt:0004")).proof_chain("0004", k=2)
    two = AgentC(_build(tmp_path / "two", "stmt:0004#p2")).proof_chain("0004", k=2)
    assert one.ok and two.ok, (one.error, two.error)
    p1, p2 = one.payload, two.payload

    assert (p1.get("proof_nos"), p2.get("proof_nos")) == ([1], [2]), (p1, p2)
    assert p2["groups_total"] == p1["groups_total"] == 2, (p1["groups_total"], p2["groups_total"])
    assert p2["best_group"] == p1["best_group"] == 2, (p1["best_group"], p2["best_group"])
    assert p1.get("best_proof_no") == 1 and p2.get("best_proof_no") == 2, (p1, p2)
    # 同构：去掉证明号那一维，逐组读数（含每一跳）完全相等。
    assert _one_dim_reading(p2["groups"]) == _one_dim_reading(p1["groups"]), p2["groups"]
    # 二维那一侧每一组都真的带着"第 2 条证明"的标签（否则上面那条相等是真空的）。
    assert {g["proof_no"] for g in p2["groups"]} == {2}, p2["groups"]
    assert {g["proof_no"] for g in p1["groups"]} == {1}, p1["groups"]


# ================================================== ③ 负控：不许跨证明合并

def test_proof_one_and_proof_two_are_never_melted_into_one_path():
    """判据 ③：`stmt:000004`（p1, 组 1）与 `stmt:000004#p2`（p2, 组 1）是两条路径。

    改前红：旧索引里 `#p2` 那条边落在 `"000004#p2"` 键上，查询 `000004` 拿到的是
    "只有 p1 那一条边"的字典 —— 而这里要的 `dict` 有两层键，断言形状先失败；
    而如果谁把两条边并进同一组，`len(edges) == 1` 那一条会当场抓住（合并 = 借光）。
    """
    rows = [
        _edge("000001", "stmt:000004", lit="0009", group=1),
        _edge("000002", "stmt:000004#p2", lit="0007", group=1),
    ]
    two_d = _graph(rows).groups_of("stmt:000004")
    assert sorted(two_d) == [1, 2], two_d
    assert _dep_ids(two_d[1]) == {1: ["000001"]}, two_d
    assert _dep_ids(two_d[2]) == {1: ["000002"]}, two_d
    # 组 1 在第 1 条证明下只有一条边 —— 合并会把它变成两条。
    assert len(two_d[1][1]) == 1 and len(two_d[2][1]) == 1, two_d


def test_proof_one_and_proof_two_stay_two_candidate_paths(tmp_path: pathlib.Path):
    """判据 ③（链那一侧）：两条证明各一条路径 ⇒ 两条候选，不是"一条合并路径"。"""
    st = _ws(tmp_path)
    _stmt(st, "0004")
    _lit(st, "0009")
    _lit(st, "0007")
    _dep(st, "0001", "stmt:0004", lit="0009", group=1)
    _dep(st, "0002", "stmt:0004#p2", lit="0007", group=1)
    rep = AgentC(st).proof_chain("0004")
    p = rep.payload
    assert p.get("proof_nos") == [1, 2], p
    assert p["groups_total"] == 2, p
    assert [g["proof_no"] for g in p["groups"]] == [1, 2], p["groups"]
    # 每条路径只有自己那一条边（叶子各是各的文献）。
    assert [g["leaves"] for g in p["groups"]] == [["lit:0009"], ["lit:0007"]], p["groups"]


# ================================================== ④ 负控：doc: 分流

def test_a_doc_reference_is_not_mistaken_for_a_bad_proof_tail():
    """判据 ④：`doc:0001#claim-3` 走 `doc:` 分支，`problem` 必须为空。

    这一条同时给"改前形态"：把同一串字直接交给 `proofloc`，它会把 `#claim-3` 判成
    坏尾巴（`problem` 非空）—— 那正是"分流之前就调 `proofloc`"的后果：一条正常的
    claim 引用被记成坏尾巴，而坏尾巴的读法是"按 canonical 读"，于是读数看着没变。
    """
    head, no, problem = _router()("doc:0001#claim-3")
    assert (head, no, problem) == ("doc:0001#claim-3", 1, ""), (head, no, problem)
    # 改前形态（不分流）：`proofloc` 自己判它是坏尾巴。
    assert PL.parse_used_by_checked("doc:0001#claim-3")[2] != "", "分流之前的形态必须能被看见"

    # 图里那条边原样留在自己的键上，不串到命题号下面。
    rows = [_edge("000001", "doc:0001#claim-3", stmt="0002"),
            _edge("000002", "stmt:000004", lit="0009")]
    graph = _graph(rows)
    doc = graph.groups_of("doc:0001#claim-3")
    assert _dep_ids(_flatten(doc)) == {1: ["000001"]}, doc
    assert graph.groups_of("0001") == {}, "doc: 的 claim 号不许被当命题号索引"
    assert _dep_ids(_flatten(graph.groups_of("000004"))) == {1: ["000002"]}, rows

    # 坏尾巴不抛（三态：读侧拿不到答案比抛更坏），且它确实带着 problem。
    bad_head, bad_no, bad_problem = _router()("stmt:000004#pabc")
    assert bad_no == 1 and bad_problem, (bad_head, bad_no, bad_problem)


# ================================================== ⑤ 负控：坏尾巴 = 0

def test_a_bad_proof_tail_is_not_a_proof_number():
    """判据 ⑤：`as_proof_no("stmt:000004#pabc")` = 0，且不许是 1。

    改前红：`return _PL.parse_used_by(text)[1]` —— `parse_used_by` 的契约就是
    "坏尾巴按 canonical 读"，于是这里返回 1：一个根本不是证明号的尾巴被读成"第 1 条证明"。
    """
    bad = ["stmt:000004#pabc", "stmt:000004#p0", "stmt:000004#p-1", "stmt:000004#p",
           "stmt:000004#", "stmt:000004#p2#p3"]
    for text in bad:
        got = VR.as_proof_no(text)
        assert got == 0, (text, got)
        assert got != 1, (text, got)

    # 正控（反真空）：干净的写法照旧认，别为了"坏尾巴返回 0"把好尾巴也判死。
    for text, want in (("stmt:000004#p2", 2), ("stmt:000004#p1", 1),
                       ("#p2", 2), ("p2", 2), (2, 2), ("2", 2)):
        assert VR.as_proof_no(text) == want, (text, VR.as_proof_no(text))
    # 认不出（不是证明号、也不是坏尾巴）仍是 0 —— `used_by` 本体没有尾巴时不是证明号
    # （这一格由调用方的 `or 1` 兜底 canonical，两个取值分工见函数 docstring）。
    assert VR.as_proof_no("stmt:000004") == 0, VR.as_proof_no("stmt:000004")
    assert VR.as_proof_no("没写") == 0 and VR.as_proof_no(None) == 0


# ================================================== ⑥ R10 按 (stmt, proof)

def _statement_with_two_proofs(st: Store) -> dict:
    row = {
        "stmt_id": SID, "origin": "own_result", "kind": "theorem",
        "label": "弦长函数非常值", "statement_full": STATEMENT,
        "statement_text": STATEMENT_TEXT, "proof_text": PROOF1,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "我方自产命题，没有外部引文要比对",
        "created_at": TS, "created_by": "test",
        "bits": EB.bits_of(proof=True, proof_process=PROOF1, kind="theorem"),
        VR.PROOFS_KEY: [{"proof_no": 2, "proof_text": PROOF2}],
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def test_r10_counts_per_statement_and_proof_pair(tmp_path: pathlib.Path):
    """判据 ⑥：一条命题两条证明、只有 #p2 签过 ⇒ 计数 1，键是 `(stmt, 2)`。

    改前红：`counted` 里一条命题一行（`{"stmt_id", "grade", "label"}`）⇒
    `counted[0]["proof_no"]` 是 `KeyError` —— 读数答不出"被审过的是哪一条证明"，
    于是"#p2 签过"这件事在收工门上与"#p1 签过"完全同形。
    """
    st = _ws(tmp_path)
    _statement_with_two_proofs(st)

    n0, d0 = _r10(st)
    assert n0 == 0, d0
    assert d0["counted"] == [], d0

    # 只签第 2 条证明（写入口就是 V 用的那一个，不经模型）。
    signed = VR.record_verification(st.root, statement_id=SID, proof_text=PROOF2,
                                    verdict={"verdict": "成立", "findings": []},
                                    verifier="agent-V", store=st, proof_no=2)
    assert signed["proof_no"] == 2 and signed["proof_sha256"] == VR.proof_sha(PROOF2), signed

    n, detail = _r10(st)
    assert n == 1, detail
    pairs = [(c.get("stmt_id"), c.get("proof_no")) for c in detail["counted"]]
    assert pairs == [(SID, 2)], (pairs, detail["counted"])
    assert detail.get("counted_total") == 1, detail
    assert detail.get("counted_statements") == 1, detail
    # #p1 一次都没签 ⇒ 它进"还没审"那一档，不许借 #p2 的签。
    assert detail["proofs_unreviewed"] == [f"{SID}#p1"], detail
    assert detail["proofs_unreviewed_total"] == 1, detail
    assert detail["proofs_stale"] == [], detail

    # 再把 #p1 签掉：逐条证明的计数变成 2，而腿的读数（定理级汇总）仍是 1 条命题。
    VR.record_verification(st.root, statement_id=SID, proof_text=PROOF1,
                            verdict={"verdict": "成立", "findings": []},
                            verifier="agent-V", store=st, proof_no=1)
    n2, d2 = _r10(st)
    assert n2 == 1, d2
    assert d2["counted_total"] == 2, d2
    assert sorted((c["stmt_id"], c["proof_no"]) for c in d2["counted"]) == [(SID, 1), (SID, 2)], d2
    assert d2["counted_statements"] == 1, d2
    assert d2["proofs_unreviewed"] == [] and d2["proofs_stale"] == [], d2
    # 三档读数不许折平：`stale` 与"没有证明"是两件事（这里是"都签过了"那一档）。
    assert d2["review_states"]["signed"] == 1, d2
