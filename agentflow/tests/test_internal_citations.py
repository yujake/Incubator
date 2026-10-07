"""T4-A 的判据：内部引用（`doc:`）与稿件修订哈希（依据 `draft/30` §T4-A）。

这一组回答五件事，每件都有正控 + 注入负控：

1. 规范哈希的口径：只覆盖内容五字段（改 `status` 不换哈希、改一个字节就换）；
2. 引用要对得上：`doc:<稿件>#<断言>@<哈希前 16 位>` 三段都要真
   （稿件在 / 断言在 / 稿件已 `accepted` / 钉的哈希就是当前这一版）；
3. 行内自洽：行里存的 `content_sha256` 必须等于重算值；
4. 依赖的内部来源：`source_doc_id` / `source_claim_id` 必须指向真实且已审的稿件；
5. 三段判据只有一份实现（题 5/5a 把写入期与审计期原先那两份合成了一份）：
   结构级 + 行为级两条判据，各自配能红的负控。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow import signatures as SIG
from agentflow import verify as V
from agentflow.store import Store
from agentflow.tools import doc_tools as DT

TS = "2026-01-01T00:00:00+00:00"


def _store(tmp_path: Path) -> Store:
    """初始化过的临时工作区。"""
    st = Store(tmp_path)
    st.init()
    return st


def _claim(cid: str, cites: list[str], text: str = "谱落在区间内。") -> dict:
    """一条合法断言（`cross_check` 必须带 disclaimer，这是既有硬约束）。"""
    return {"claim_id": cid, "text": text, "citations": cites,
            "evidence_kind": "cross_check", "disclaimer": "仅为交叉核对，不是证明。"}


def _doc_row(doc_id: str, claims: list[dict], *, status: str = "draft",
             title: str = "稿", **kw) -> dict:
    """构造一行稿件（accepted ⇒ 由写侧口径补上内容哈希）。"""
    row = {"doc_id": doc_id, "kind": "paper", "title": title, "sections": [],
           "claims": claims, "open_problems": [], "status": status,
           "created_at": TS, "updated_at": TS}
    row.update(kw)
    if status == "accepted" and not row.get("content_sha256"):
        row["content_sha256"] = SIG.content_sha256_of(row)
    return row


def _put(st: Store, table: str, row: dict) -> dict:
    """直接落库一行（专测 verify，不走工具层）。"""
    with st.tx(table, actor="test") as tx:
        tx.upsert(table, row)
    return row


def _doc(st: Store, doc_id: str, claims: list[dict], **kw) -> dict:
    """落一行稿件。"""
    return _put(st, "documents", _doc_row(doc_id, claims, **kw))


def _deps(st: Store, dep_id: str, **kw) -> dict:
    """落一行依赖。"""
    base = {"dep_id": dep_id, "used_by": "doc:0001#c1", "kind": "theorem", "label": "内部断言",
            "status": "closed", "created_at": TS}
    base.update(kw)
    return _put(st, "dependencies", base)


def _codes(st: Store, table: str) -> list[str]:
    """`verify_all` 就某张表报出的判据码（排序）。"""
    return sorted(i.code for i in V.verify_all(st).issues if i.table == table)


# ---------------------------------------------------------------- ① 规范哈希的口径

def test_canonical_hash_covers_content_only():
    """正控：键序无关、改内容换哈希、`status` 与时间戳都不参与。"""
    a = {"kind": "paper", "title": "谱的界", "sections": [], "claims": [],
         "open_problems": [], "status": "draft", "created_at": TS}
    assert SIG.content_sha256_of(a) == SIG.content_sha256_of({**a, "created_at": "2026-09-29"})
    assert SIG.content_sha256_of(a) == SIG.content_sha256_of({**a, "status": "accepted"})
    assert SIG.content_sha256_of(a) != SIG.content_sha256_of({**a, "title": "谱的界!"})
    assert len(SIG.content_sha256_of(a)) == 64
    assert SIG.ref_hash_of(a) == SIG.content_sha256_of(a)[:SIG.REF_HASH_LEN]


def test_canonical_hash_treats_missing_list_and_empty_list_alike():
    """回归（T4-A 实测踩到的坑）：缺 `sections` 键与 `sections: []` 必须同哈希。

    夹具与调用方给的字典常常没有那几个列表键，而落库后的行是 `[]`。
    若两者算出不同哈希，`content_hash_mismatch` 会在完全干净的库上开火
    （实测：`test_fully_clean_workspace_has_no_errors` 就是这样红的）。
    """
    with_key = {"kind": "paper", "title": "t", "sections": [], "claims": [],
                "open_problems": []}
    without_key = {"kind": "paper", "title": "t"}
    assert SIG.content_sha256_of(without_key) == SIG.content_sha256_of(with_key)
    assert SIG.content_sha256_of({**without_key, "sections": None}) == \
        SIG.content_sha256_of(with_key)
    # 反向：真的加一节内容还是必须换哈希（别把这条修成"列表字段一律不参与哈希"）
    assert SIG.content_sha256_of({**with_key, "sections": [{"id": "s1"}]}) != \
        SIG.content_sha256_of(with_key)


def test_doc_ref_round_trip():
    """正控：`doc_ref` 与 `parse_doc_ref` 自洽；非 `doc:` 形状返回 None（不抛）。"""
    row = _doc_row("0001", [_claim("c1", ["lit:0000"])])
    ref = SIG.doc_ref("0001", "c1", row)
    assert SIG.parse_doc_ref(ref) == ("0001", "c1", SIG.ref_hash_of(row))
    assert SIG.parse_doc_ref("lit:0003#p.4") is None
    assert SIG.parse_doc_ref("doc:0001") is None


# ---------------------------------------------------------------- ② 引用要对得上

def _lit(st: Store, lit_id: str = "0000") -> dict:
    """落一条合法文献行（引用 `lit:` 必须解析得到，否则会多出 `dangling_citation` 噪音）。"""
    row = S.Literature(lit_id=lit_id, title="某文献", type="J", summary="", path=None,
                       added_at=TS)
    return _put(st, "literature", row.to_dict())


def _sign(st: Store, doc_row: dict, *, name: str = SIG.SIGNER_NAME,
          verdict: str = "accepted") -> dict:
    """给一行稿件签一条（T4-B 之后，"accepted 却没人签"本身也是一种缺陷）。"""
    cur = SIG.content_sha256_of(doc_row)
    return SIG.append_signature(st.root, {
        "doc_id": str(doc_row["doc_id"]),
        "content_sha256": cur,
        "name": name,
        "at": TS,
        "scope": "document",
        "verdict": verdict,
        "instance_id": f"test@{TS}",
        "inputs": {"doc_sha256": cur, "evidence_hashes": []},
        "basis": {"codes_checked": [], "finding_ids": [], "rounds": 1, "dimensions": []},
    })


def _cited(st: Store, *, target_status: str = "accepted", target_title: str = "被引稿") -> dict:
    """造一条"引用内部断言"的稿子，返回被引稿那一行。

    稿件号用 0000 / 0001（连续 ⇒ 不引入 `id_gap` 这类与本案无关的噪音）。
    被引稿是 `accepted` 时顺手签一条 —— 否则会多出 `accepted_without_signature`
    （那是 `draft/30` §T4-B 的判据，与本案要测的内部引用无关）。
    """
    _lit(st)
    target = _doc(st, "0000", [_claim("c1", ["lit:0000"])], status=target_status,
                  title=target_title)
    if target_status == "accepted":
        _sign(st, target)
    _doc(st, "0001", [_claim("c1", [SIG.doc_ref("0000", "c1", target)])])
    return target


def test_positive_internal_citation_is_clean(tmp_path: Path):
    """正控：引一条存在、已 accepted、哈希对得上的内部断言 ⇒ 不报。"""
    st = _store(tmp_path)
    _cited(st)
    assert _codes(st, "documents") == [], [i.to_dict() for i in V.verify_all(st).issues]


def test_negative_dangling_doc_citation_bites(tmp_path: Path):
    """注入：引用不存在的稿件 / 不存在的断言 ⇒ `dangling_doc_citation`。"""
    st = _store(tmp_path)
    _doc(st, "0001", [_claim("c1", ["lit:0000"])], status="accepted")
    _doc(st, "0002", [_claim("c1", ["doc:9999#c1@deadbeefdeadbeef"])])
    assert "dangling_doc_citation" in _codes(st, "documents")

    st2 = _store(tmp_path / "b")
    _doc(st2, "0001", [_claim("c1", ["lit:0000"])], status="accepted")
    _doc(st2, "0002", [_claim("c1", [SIG.doc_ref("0001", "nope",
                                                 _doc_row("0001", [_claim("c1", [])]))])])
    assert "dangling_doc_citation" in _codes(st2, "documents")


def test_negative_internal_citation_to_unreviewed_doc_bites(tmp_path: Path):
    """注入：目标稿件退回 `in_review` ⇒ `internal_citation_not_accepted`。"""
    st = _store(tmp_path)
    target = _cited(st, target_status="in_review")
    assert target["status"] == "in_review"
    assert "internal_citation_not_accepted" in _codes(st, "documents")


def test_negative_stale_internal_citation_bites(tmp_path: Path):
    """注入：被引稿件改了内容（哈希变了）而引用仍钉旧哈希 ⇒ `internal_citation_stale`。"""
    st = _store(tmp_path)
    target = _cited(st)
    old_ref = SIG.doc_ref("0000", "c1", target)
    # 直接改内容（模拟 G 改稿）：标题变 ⇒ 内容哈希变，引用没跟着改
    with st.tx("documents", actor="test") as tx:
        row = dict(tx.find("documents", doc_id="0000"))
        row["title"] = "被引稿（改过）"
        tx.upsert("documents", row)
    rep = V.verify_all(st)
    stale = [i for i in rep.issues if i.code == "internal_citation_stale"]
    assert stale, [i.to_dict() for i in rep.issues if i.table == "documents"]
    assert SIG.ref_hash_of(target) in stale[0].message, stale[0].message


def test_negative_citation_without_hash_bites(tmp_path: Path):
    """注入：引用没钉哈希（`doc:0001#c1`）⇒ 也算 stale（不许"没钉"被读成"对得上"）。"""
    st = _store(tmp_path)
    _doc(st, "0001", [_claim("c1", ["lit:0000"])], status="accepted")
    _doc(st, "0002", [_claim("c1", ["doc:0001#c1"])])
    assert "internal_citation_stale" in _codes(st, "documents")


# ---------------------------------------------------------------- ③ 行内自洽

def test_negative_content_hash_mismatch_bites(tmp_path: Path):
    """注入：把行里存的哈希改成别的值 ⇒ `content_hash_mismatch`。"""
    st = _store(tmp_path)
    row = _doc_row("0000", [_claim("c1", ["lit:0000"])])
    row["content_sha256"] = "0" * 64
    _put(st, "documents", row)
    assert "content_hash_mismatch" in _codes(st, "documents")


def test_negative_accepted_without_content_hash_is_rejected_by_schema(tmp_path: Path):
    """注入（写入期）：`accepted` 却没有内容哈希 ⇒ schema 直接拒（审批钉不住版本）。"""
    row = _doc_row("0000", [_claim("c1", ["lit:0000"])], status="accepted")
    row["content_sha256"] = ""
    with pytest.raises(ValueError, match="content_sha256"):
        S.Document(**row).validate()


def test_negative_malformed_content_hash_is_rejected_by_schema():
    """注入（写入期）：哈希形状不对（长度/字符）⇒ 拒。"""
    row = _doc_row("0000", [_claim("c1", ["lit:0000"])])
    row["content_sha256"] = "not-a-hash"
    with pytest.raises(ValueError, match="64 位小写十六进制"):
        S.Document(**row).validate()


# ---------------------------------------------------------------- ④ 依赖的内部来源

def test_positive_internal_dependency_is_clean(tmp_path: Path):
    """正控：依赖指向一条已 accepted 的内部断言 ⇒ 不报。"""
    st = _store(tmp_path)
    _doc(st, "0001", [_claim("c1", ["lit:0000"])], status="accepted")
    _deps(st, "0000", source_doc_id="0001", source_claim_id="c1")
    assert _codes(st, "dependencies") == [], [i.to_dict() for i in V.verify_all(st).issues]


def test_negative_internal_dependency_on_missing_doc_bites(tmp_path: Path):
    """注入：`source_doc_id` 指向不存在的稿件 ⇒ `dangling_dep`。"""
    st = _store(tmp_path)
    _deps(st, "0000", source_doc_id="9999", source_claim_id="c1")
    assert "dangling_dep" in _codes(st, "dependencies")


def test_negative_internal_dependency_on_missing_claim_bites(tmp_path: Path):
    """注入：稿件在、但那条断言不在 ⇒ `dangling_dep`。"""
    st = _store(tmp_path)
    _doc(st, "0001", [_claim("c1", ["lit:0000"])], status="accepted")
    _deps(st, "0000", source_doc_id="0001", source_claim_id="c9")
    assert "dangling_dep" in _codes(st, "dependencies")


def test_negative_internal_dependency_on_unreviewed_doc_bites(tmp_path: Path):
    """注入：内部来源的稿件不是 `accepted` ⇒ `internal_dep_not_accepted`。"""
    st = _store(tmp_path)
    _doc(st, "0001", [_claim("c1", ["lit:0000"])], status="in_review")
    _deps(st, "0000", source_doc_id="0001", source_claim_id="c1")
    assert "internal_dep_not_accepted" in _codes(st, "dependencies")


def test_negative_claim_without_doc_is_rejected_by_schema():
    """注入（写入期）：给了 `source_claim_id` 却没给 `source_doc_id` ⇒ 拒。"""
    with pytest.raises(ValueError, match="source_doc_id"):
        S.Dependency(dep_id="0000", used_by="doc:0001#c1", kind="theorem", label="l",
                     status="closed", source_claim_id="c1").validate()


# ---------------------------------------------------------------- 注入无效自检

def test_injection_that_changes_nothing_relevant_does_not_bite(tmp_path: Path):
    """注入无效自检：改一个与本批判据无关的字段（依赖的 label）⇒ 一条新码都不许出现。"""
    st = _store(tmp_path)
    _doc(st, "0001", [_claim("c1", ["lit:0000"])], status="accepted")
    _deps(st, "0000", source_doc_id="0001", source_claim_id="c1", label="内部断言")
    assert _codes(st, "dependencies") == []
    _deps(st, "0001", source_doc_id="0001", source_claim_id="c1", label="换了个标签")
    assert _codes(st, "dependencies") == []


# --------------------------------------- 写入期也认 `doc:`（`R-03` 主控裁 2）


def test_write_side_accepts_a_valid_doc_ref(tmp_path: Path):
    """正控：写入期 `check_citations` 现在也认 `doc:`。

    改前 `doc_tools._CITATION_TABLES` 里没有 `doc` ⇒ 它被判成"前缀无法识别"，
    而审计期 `verify` 一直有 `elif kind == "doc"` 那一档认它 ⇒ 同一个字符串
    "写入期拒、审计期认"（该文件自己的注释逐字："两处对同一个字符串给出不同结论则不行"）。
    """
    st = _store(tmp_path)
    target = _doc(st, "0001", [_claim("c1", ["lit:0000"])], status="accepted")
    ref = SIG.doc_ref("0001", "c1", target)
    got = DT.check_citations(lambda t: st.rows(t), [_claim("c2", [ref])])
    assert got["checked"] is True, got
    assert not got["missing"], got
    assert got["resolved"] == 1, got


def test_write_side_refuses_each_broken_part_of_a_doc_ref(tmp_path: Path):
    """负控四层：形状 / 稿件 / 断言 / 哈希 —— 坏哪一段都必须被拒。

    最要紧的是哈希那一段：通用存在性检查只比 `citation_ref_parts` 切出来的
    `ref`（`#` 之后已被切掉）⇒ 它最多只能核"稿件在不在"。只加表项而走通用检查，
    就会让改稿之后的旧引用静默沿用 —— 那比"错误拒收"更坏，所以 `doc:` 单独一支。
    """
    st = _store(tmp_path)
    target = _doc(st, "0001", [_claim("c1", ["lit:0000"])], status="accepted")
    ref = SIG.doc_ref("0001", "c1", target)
    rows_of = lambda t: st.rows(t)

    def _why(cite: str) -> str:
        got = DT.check_citations(rows_of, [_claim("c2", [cite])])
        assert got["missing"], f"这一条本该被拒：{cite!r}"
        return str(got["missing"][0]["why"])

    assert "形状不对" in _why("doc:0001")                             # 缺 #断言@哈希
    assert "没有 doc_id" in _why(f"doc:9999#c1@{SIG.ref_hash_of(target)}")
    assert "没有断言" in _why(f"doc:0001#cX@{SIG.ref_hash_of(target)}")
    stale = "0" * SIG.REF_HASH_LEN if SIG.ref_hash_of(target) != "0" * SIG.REF_HASH_LEN \
        else "1" * SIG.REF_HASH_LEN
    assert "改稿之后旧引用失效" in _why(f"doc:0001#c1@{stale}")
    # 反真空：原样那一条仍然通过 —— 否则上面四条可能是靠"一律拒"通过的
    assert not DT.check_citations(rows_of, [_claim("c2", [ref])])["missing"]


def test_write_side_still_accepts_stmt_and_refuses_a_bare_number(tmp_path: Path):
    """`R-03` 方案 A 的另一半：`stmt:` 被认（含存在性），裸号仍被拒且理由与"未知前缀"分开。

    裸号白名单 = 空（主控 2026-10-07 裁 1），依据是真机上 593 条 `citations` 全带前缀、
    0 条裸号；而 `citations` 是混合列表，给裸号猜一张表就会静默错配。
    """
    st = _store(tmp_path)
    _put(st, "statements", {"stmt_id": "0004", "origin": "own_result", "kind": "lemma",
                            "statement_full": "某命题", "statement_text": "", "proof_text": "",
                            "doc_id": "0000", "line_range": {"start": None, "end": None, "label": None},
                            "quote_verified": None, "quote_reason": "证明还没做完（本用例只测引用解析）",
                            "evidence_kind": "cross_check",
                            "status": "active", "created_at": TS, "created_by": "test",
                            "derived_from": []})
    rows_of = lambda t: st.rows(t)

    ok_ref = DT.check_citations(rows_of, [_claim("c1", ["stmt:0004"])])
    assert not ok_ref["missing"], ok_ref
    missing_stmt = DT.check_citations(rows_of, [_claim("c1", ["stmt:9999"])])
    assert "statements 表里没有 stmt_id='9999'" in str(missing_stmt["missing"][0]["why"]), missing_stmt

    bare = DT.check_citations(rows_of, [_claim("c1", ["0004"])])
    why = str(bare["missing"][0]["why"])
    assert "是裸号" in why and "无法定表" in why, why
    # 判别式必须与"未知前缀"那一支不同（否则调用方会去改一个没错的前缀词表）：
    # 裸号这一支说的是"没有 kind、无法定表"，而那一支说的是"前缀无法识别"。
    assert "无法识别" not in why, f"裸号的理由不该说成'前缀无法识别'：{why!r}"
    assert "stmt:0004" in why, f"裸号的改法要给一个可抄的例子：{why!r}"
    unknown = DT.check_citations(rows_of, [_claim("c1", ["foo:0004"])])
    assert "前缀 'foo' 无法识别" in str(unknown["missing"][0]["why"]), unknown


# ------------------------------- ⑤ 三段的唯一实现（题 5/5a 把两份合成一份）
#
# 判据两条，各自配一条能红的负控：
# ① 只有一份实现（结构级）：三段判据用的原语只许出现在 `signatures.py`，
#    写入期与审计期这两个调用点只许把判定码翻成文案；
# ② 两个调用点真的走同一个函数（行为级）：给共用函数打 spy/替身，
#    两侧都必须经过它，而且两侧的结论由它决定。
# 反真空：每一侧都必须统计到调用 —— 一个调用点都没走过就不许算通过
# （否则"两侧都走同一个函数"会因为"两侧都没走"而变绿）。

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_AUDIT_REL = "src/agentflow/verify.py"
_WRITE_REL = "src/agentflow/tools/doc_tools.py"
_SHARED_REL = "src/agentflow/signatures.py"
_SHARED_NAME = "doc_ref_verdict"
#: 三段判据的原语。某一支的源码里出现任何一个 ⇒ 它在自己判（= 第二份实现）。
_SEGMENT_PRIMITIVES = ("parse_doc_ref", "content_sha256_of", "ref_hash_of")
#: 审计期那一支里"叫共用实现"的那一行（负控要把它换成偷回来的局部实现）。
#: 含行首缩进：这样负控换的是整行，替换体的缩进不会与原文叠在一起。
_SHARED_CALL_LINE = "                    verdict = SIG.doc_ref_verdict(str(x), doc_by_id.get)"
#: 负控用的注入体：改前那一份的自判三行 + 原来那一行（缩进与审计期那一支一致）。
_LOCAL_IMPL_INJECTION = "\n".join([
    "                    parts = SIG.parse_doc_ref(str(x))",
    "                    tdoc = doc_by_id.get(parts[0]) if parts else None",
    "                    if tdoc is not None and str(parts[2]) != "
    "SIG.content_sha256_of(tdoc)[:SIG.REF_HASH_LEN]:",
    "                        pass",
    _SHARED_CALL_LINE,
])


def _read_src(rel: str) -> str:
    """项目内某个源文件的文本。"""
    return (_PROJECT_ROOT / rel).read_text(encoding="utf-8")


def _dotted(node: ast.AST) -> str:
    """`a.b.c` 形式的调用名；其余返回空串。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _calls_under(node: ast.AST) -> set[str]:
    """节点下出现的全部调用名（含 `a.b(...)` 形式）。"""
    return {_dotted(sub.func) for sub in ast.walk(node) if isinstance(sub, ast.Call)}


def _is_doc_kind_test(node: ast.AST) -> bool:
    """`node` 是不是形如 `kind == "doc"` 的判断。

    按结构比而不是按 `ast.unparse` 的文本比：unparse 的引号形态会随版本/内容变
    （实测 `kind == 'doc'` 与 `kind == "doc"` 两种都出现过），比文本的判据会
    因为一个引号而把"找到那一支"读成"没找到"。
    """
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    if not isinstance(node.ops[0], ast.Eq):
        return False
    left, right = node.left, node.comparators[0]
    return (isinstance(left, ast.Name) and left.id == "kind"
            and isinstance(right, ast.Constant) and right.value == "doc")


def _doc_branch_segment(source: str) -> tuple[str, set[str]]:
    """`verify.py` 里 `elif kind == "doc":` 那一支的源码段与它调到的名字。

    找不到那一支 ⇒ 抛（"判据没接上"不许读成"判据通过"，三态纪律）。
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.If) and _is_doc_kind_test(node.test):
            calls: set[str] = set()
            for stmt in node.body:
                calls |= _calls_under(stmt)
            return ast.get_source_segment(source, node) or "", calls
    raise AssertionError('verify.py 里找不到 `elif kind == "doc":` 那一支 ⇒ 本次没查成')


def _func_segment(source: str, name: str) -> str:
    """某个顶层函数的源码段（找不到 ⇒ 抛）。"""
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"找不到函数 {name} ⇒ 本次没查成")


def _local_impl_problems(segment: str, calls: set[str]) -> list[str]:
    """一段调用点源码里还有没有第二份三段逻辑。空列表 = 没有。"""
    out = [f"源码里仍有三段原语 {p!r}" for p in _SEGMENT_PRIMITIVES if p in segment]
    if not any(c.endswith(_SHARED_NAME) for c in calls):
        out.append(f"没有调用共用实现 {_SHARED_NAME}（调用名：{sorted(calls)}）")
    return out


def test_only_one_doc_citation_implementation():
    """① 结构级：三段原语只许出现在 `signatures.py`，两个调用点都不许自己判。"""
    owners: dict[str, set[str]] = {p: set() for p in ("parse_doc_ref", "ref_hash_of")}
    for path in sorted((_PROJECT_ROOT / "src/agentflow").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for primitive in owners:
            if primitive in text:
                owners[primitive].add(path.relative_to(_PROJECT_ROOT).as_posix())
    assert owners["parse_doc_ref"] == {_SHARED_REL}, owners
    assert owners["ref_hash_of"] == {_SHARED_REL}, owners

    audit_seg, audit_calls = _doc_branch_segment(_read_src(_AUDIT_REL))
    assert _local_impl_problems(audit_seg, audit_calls) == [], audit_seg

    write_seg = _func_segment(_read_src(_WRITE_REL), "_doc_citation_problem")
    assert _local_impl_problems(write_seg, _calls_under(ast.parse(write_seg))) == [], write_seg

    # 反真空：唯一实现自己必须真的做着那三段（空壳也能让上面三条变绿）。
    # 它用的是 `parse_doc_ref` 与 `ref_hash_of`（后者按定义就是
    # `content_sha256_of` 的前 16 位，见本文件 ① 的第一条断言）。
    shared_seg = _func_segment(_read_src(_SHARED_REL), _SHARED_NAME)
    for primitive in ("parse_doc_ref", "ref_hash_of"):
        assert primitive in shared_seg, f"唯一实现 {_SHARED_NAME} 里没有 {primitive}"


def test_negative_control_a_local_implementation_is_caught():
    """负控（①的牙）：把一份局部实现放回审计期那一支 ⇒ 结构判据必须红。

    做法：在真源码上把"叫共用实现"那一行换成"自己 parse + 自己算哈希"的几行
    （= 改前那一份），再让同一条判据去看它。下面那句 `mutated != source` 是这条
    负控自己的反真空检查：锚行一旦漂了，替换会无声地什么都不做，
    而负控会变成"没改也通过"。
    """
    source = _read_src(_AUDIT_REL)
    assert _SHARED_CALL_LINE in source, "锚行漂了 ⇒ 这条负控没查成（不是通过）"
    mutated = source.replace(_SHARED_CALL_LINE, _LOCAL_IMPL_INJECTION)
    assert mutated != source, "变异没落在源码上 ⇒ 负控无效"

    seg, calls = _doc_branch_segment(mutated)
    problems = _local_impl_problems(seg, calls)
    assert problems, "把局部实现放回去了而判据没红 ⇒ ① 是一条永远绿的灯"
    assert any("parse_doc_ref" in p for p in problems), problems

    # 正控：同一条判据在未变异的源码上是干净的（判据分得清两种源码）。
    clean_seg, clean_calls = _doc_branch_segment(source)
    assert _local_impl_problems(clean_seg, clean_calls) == []


def _spy_shared(monkeypatch, *, verdict_code: str | None = None) -> list[str]:
    """把共用实现换成计数替身；给了 `verdict_code` 时它一律返回那个判定码。

    替身是打在「模块属性」上的：两个调用点都是运行期取 `SIG.doc_ref_verdict`
    （`verify` 模块级 import、`doc_tools` 惰性 import 同一模块对象），所以两侧
    都会打到同一个替身上 —— 这正是"走的是同一个函数"的行为级证据。
    """
    calls: list[str] = []
    real = SIG.doc_ref_verdict

    def fake(raw, doc_of):
        calls.append(str(raw))
        if verdict_code is None:
            return real(raw, doc_of)
        return SIG.DocRefVerdict(verdict_code, "0000", "c1", "deadbeefdeadbeef",
                                 doc_of("0000"), "")
    monkeypatch.setattr(SIG, _SHARED_NAME, fake)
    return calls


def test_both_call_sites_go_through_the_shared_function(tmp_path: Path, monkeypatch):
    """② 行为级：写入期与审计期都必须经过共用实现（反真空：两侧各自统计到调用）。"""
    st = _store(tmp_path)
    target = _cited(st)
    ref = SIG.doc_ref("0000", "c1", target)
    rows_of = lambda t: st.rows(t)  # noqa: E731

    calls = _spy_shared(monkeypatch)
    n0 = len(calls)
    DT._doc_citation_problem(ref, rows_of)
    assert len(calls) - n0 >= 1, "写入期那一支没有经过共用实现 ⇒ 它自己又判了一遍"

    n1 = len(calls)
    V.verify_all(st)
    assert len(calls) - n1 >= 1, "审计期那一支没有经过共用实现 ⇒ 它自己又判了一遍"
    # 反真空：同一个替身被两侧各打到一次，且两侧递进去的是同一个字符串。
    assert calls.count(ref) >= 2, calls


def test_the_verdict_is_dictated_by_the_shared_function(tmp_path: Path, monkeypatch):
    """② 的第二个方向：两侧的结论由共用实现决定（换成"形状不对" ⇒ 两侧都改口）。

    若某一侧还留着自己的判据，它对一个合法引用仍会说通过 —— 这条就是那种情形的牙。
    """
    st = _store(tmp_path)
    target = _cited(st)
    ref = SIG.doc_ref("0000", "c1", target)
    assert _codes(st, "documents") == [], "夹具本身不干净 ⇒ 下面的读数不可信"

    _spy_shared(monkeypatch, verdict_code=SIG.DOC_REF_BAD_SHAPE)
    why = DT._doc_citation_problem(ref, lambda t: st.rows(t))
    assert "形状不对" in why, why
    assert "dangling_doc_citation" in _codes(st, "documents")


def test_negative_control_spy_catches_a_local_implementation(tmp_path: Path, monkeypatch):
    """负控（②的牙）：一份自己判的局部实现必须被判成"没经过共用实现"。

    同一个"经过了吗"的检查，一次喂给局部实现（必须红）、一次喂给真调用点
    （必须绿）：只红不绿说明检查坏了，只绿不红说明它是永远绿的灯。
    """
    st = _store(tmp_path)
    target = _cited(st)
    ref = SIG.doc_ref("0000", "c1", target)
    calls = _spy_shared(monkeypatch)

    def local_impl(raw: str) -> str:
        """改前那一份的形状：自己 parse、自己算哈希，一次都不碰共用实现。"""
        parts = SIG.parse_doc_ref(raw)
        if parts is None:
            return "形状不对"
        tdoc_id, tclaim_id, thash = parts
        row = next((r for r in st.rows("documents")
                    if str(r.get("doc_id")) == str(tdoc_id)), None)
        if row is None:
            return "稿件不在"
        if str(thash) != SIG.content_sha256_of(row)[:SIG.REF_HASH_LEN]:
            return f"旧引用（{tclaim_id}）"
        return ""

    n0 = len(calls)
    local_impl(ref)
    assert len(calls) == n0, "负控样本居然经过了共用实现 ⇒ 它不是一个局部实现"

    n1 = len(calls)
    DT._doc_citation_problem(ref, lambda t: st.rows(t))
    assert len(calls) > n1, "真调用点没有经过共用实现 ⇒ 判据该红"


def _case_store(root: Path, raw: str, *, target_status: str = "accepted") -> Store:
    """一份只为一条引用准备的工作区（被引稿 0000 + 引用者 0001）。"""
    st = _store(root)
    _lit(st)
    target = _doc(st, "0000", [_claim("c1", ["lit:0000"])], status=target_status,
                  title="被引稿")
    if target_status == "accepted":
        _sign(st, target)
    _doc(st, "0001", [_claim("c1", [raw])])
    return st


#: 拒收理由的公共口径：`(写入期报文片段, 审计期判据码)`。
_REFUSE_EXPECT: dict[str, tuple[str, str]] = {
    "shape": ("形状不对", "dangling_doc_citation"),
    "doc": ("没有 doc_id", "dangling_doc_citation"),
    "claim": ("没有断言", "dangling_doc_citation"),
    "stale": ("改稿之后旧引用失效", "internal_citation_stale"),
}


def test_two_sides_agree_on_the_seven_inputs(tmp_path: Path):
    """改后的常驻回归表：七个输入上两侧的判定与拒收理由逐条对得上。

    这是差分读数（`agentflow/temp/probe_doc_citation_two_sides_5a.py` 的改前/改后四格）
    的常驻版本：那边证"搬一处没改口径"，这边守住"此后也不许分家"。
    两侧的文案与粒度本来就不同（审计期把"稿件不存在"与"断言不存在"合成一条
    `dangling_doc_citation`），所以比的是"拒在哪一段"。
    """
    probe = _case_store(tmp_path / "probe", "lit:0000")
    target = [r for r in probe.rows("documents") if str(r.get("doc_id")) == "0000"][0]
    cur = SIG.ref_hash_of(target)
    cases = [
        ("合法引用", SIG.doc_ref("0000", "c1", target), "ok"),
        ("缺哈希", "doc:0000#c1", "stale"),
        ("哈希长度不对", f"doc:0000#c1@{cur[:-1]}", "stale"),
        ("形式不对", "doc:0000", "shape"),
        ("稿件不存在", f"doc:9999#c1@{cur}", "doc"),
        ("断言不存在", f"doc:0000#cX@{cur}", "claim"),
    ]
    seen: set[str] = set()
    for i, (label, raw, kind) in enumerate(cases):
        st = _case_store(tmp_path / f"case{i}", raw)
        got = DT.check_citations(lambda t: st.rows(t), [_claim("c2", [raw])])
        audit = [x for x in V.verify_all(st).issues
                 if x.table == "documents" and str(x.row_id) == "0001"]
        if kind == "ok":
            assert not got["missing"], (label, got)
            assert not audit, (label, [x.to_dict() for x in audit])
            continue
        seen.add(kind)
        why_expect, code_expect = _REFUSE_EXPECT[kind]
        assert got["missing"], (label, got)
        assert why_expect in str(got["missing"][0]["why"]), (label, got["missing"][0])
        assert [x.code for x in audit] == [code_expect], (label, [x.to_dict() for x in audit])
    # 反真空：四个拒收段都真的被走到过（否则上表可能靠"一律拒"通过）。
    assert seen == set(_REFUSE_EXPECT), seen

    # 非 `doc:` 前缀：两侧都把它交给"前缀路由"那一支（不是这三段），判定同 = 都拒。
    # 这一行的用处是让"没走三段"与"走了三段判通过"分得开。
    st = _case_store(tmp_path / "nondoc", "lit:9999")
    got = DT.check_citations(lambda t: st.rows(t), [_claim("c2", ["lit:9999"])])
    assert got["missing"] and got["missing"][0]["kind"] == "lit", got
    audit = [x for x in V.verify_all(st).issues
             if x.table == "documents" and str(x.row_id) == "0001"]
    assert [x.code for x in audit] == ["dangling_citation"], [x.to_dict() for x in audit]


def test_audit_only_status_gate_is_unchanged(tmp_path: Path):
    """审计期独有的那一档原样保留：目标稿件不是 `accepted` 时审计期拒、写入期不拒。

    这条不是三段判据的一部分（三段是"稿件在 / 断言在 / 钉的哈希对得上"），
    而是写入期与审计期刻意的口径差。题 5/5a 只搬三段，所以这里把它钉住：
    哪天有人"顺手统一"了，这条测试必须红。
    """
    row = _doc_row("0000", [_claim("c1", ["lit:0000"])], status="in_review", title="被引稿")
    ref = f"doc:0000#c1@{SIG.ref_hash_of(row)}"
    st = _case_store(tmp_path, ref, target_status="in_review")

    got = DT.check_citations(lambda t: st.rows(t), [_claim("c2", [ref])])
    assert not got["missing"], got
    issues = [x for x in V.verify_all(st).issues if x.code == "internal_citation_not_accepted"]
    assert issues, [x.to_dict() for x in V.verify_all(st).issues if x.table == "documents"]
    assert "不是 accepted" in issues[0].message, issues[0].message
