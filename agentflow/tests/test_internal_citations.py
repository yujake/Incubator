"""T4-A 的判据：内部引用（`doc:`）与稿件修订哈希（依据 `draft/30` §T4-A）。

这一组回答四件事，每件都有正控 + 注入负控：

1. 规范哈希的口径：只覆盖内容五字段（改 `status` 不换哈希、改一个字节就换）；
2. 引用要对得上：`doc:<稿件>#<断言>@<哈希前 16 位>` 三段都要真
   （稿件在 / 断言在 / 稿件已 `accepted` / 钉的哈希就是当前这一版）；
3. 行内自洽：行里存的 `content_sha256` 必须等于重算值；
4. 依赖的内部来源：`source_doc_id` / `source_claim_id` 必须指向真实且已审的稿件。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow import signatures as SIG
from agentflow import verify as V
from agentflow.store import Store

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


def _cited(st: Store, *, target_status: str = "accepted", target_title: str = "被引稿") -> dict:
    """造一条"引用内部断言"的稿子，返回被引稿那一行。

    稿件号用 0000 / 0001（连续 ⇒ 不引入 `id_gap` 这类与本案无关的噪音）。
    """
    _lit(st)
    target = _doc(st, "0000", [_claim("c1", ["lit:0000"])], status=target_status,
                  title=target_title)
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
