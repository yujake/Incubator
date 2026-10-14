# -*- coding: utf-8 -*-
"""S1q：论文正文从台账重建 —— 逐字搬 / 序号重写 / `stmt:` 引用 / 映射落 `dependencies`。

业主 `draft/97` §7 那张表给了四条判据名，§9.5 给了映射行的字段组合，§16.1 是施工前
补写的定死版（四步 + 五条判据）。这一组就是那四步的红/绿成对判据：

- 正控：搬两条定理进正文 ⇒ 两段与台账逐字相等 + 各带一条 `stmt:` 引用 +
  `dependencies` 里两条映射（论文号互不相同、`used_by` 指到论文那一处断言）；
- 负控①：正文里没有 `stmt:` 引用 ⇒ 红（"搬了但从哪来"不可复算）；
- 负控②：`\\ref` 悬空 ⇒ 红；两个不同 `stmt:` 映射到同一个论文号 ⇒ 红；
- 负控③：论文里出现 `doc:` ⇒ 红（两阶段引用口径：论文不许引别的稿子）；
- 反真空：映射表比正文多一行 ⇒ 红；正文改了字（不再逐字）⇒ 红 ——
  "只判一个方向"会让这两种事没人看得见；
- 三态：输入读不成 ⇒ `checked=False` + 理由（"没查成"不是"全对得上"）。
"""

from __future__ import annotations

from conftest import TS
from agentflow import paperledger as PL
from agentflow import schema as S


def _stmts() -> list[dict]:
    return [
        {"stmt_id": "0007", "kind": "theorem", "label": "主定理", "doc_id": "0001",
         "origin": "own_result", "statement_full": "设 G 是有限群；则命题 ph 成立。"},
        {"stmt_id": "0008", "kind": "lemma", "label": "辅助引理", "doc_id": "0001",
         "origin": "own_result", "statement_full": "若 H 是 G 的子群，则命题 q 成立。"},
    ]


def _paper(*, citations_extra: list[str] | None = None, drop: str = "") -> dict:
    stmts = _stmts()
    nums = PL.assign_paper_numbers(stmts, section="1")
    moved = [PL.move_theorem(s, nums[s["stmt_id"]]) for s in stmts]
    claims = []
    for m in moved:
        cites = [] if m["citation"] == drop else [m["citation"]]
        claims.append({"claim_id": f"c-{m['paper_number']}", "section": "1",
                       "text": m["text"], "citations": cites + list(citations_extra or [])})
    paper = {"doc_id": "0009", "kind": "paper", "title": "重建出来的正文",
             "claims": claims, "status": "draft", "created_at": TS, "created_by": "G"}
    return {"paper": paper, "moved": moved, "numbers": nums}


def _deps(moved: list[dict], stmts: list[dict], *, number_of=None) -> list[dict]:
    by_id = {s["stmt_id"]: s for s in stmts}
    out = []
    for i, m in enumerate(moved):
        num = (number_of or {}).get(m["stmt_id"], m["paper_number"])
        out.append(PL.dep_row_for_mapping(
            dep_id=f"000{i}", statement_row=by_id[m["stmt_id"]], paper_doc_id="0009",
            claim_id=f"c-{m['paper_number']}", paper_number=num, created_at=TS))
    return out


# ==================================================== 一、正控

def test_the_paper_rebuilds_verbatim_with_citations_and_one_mapping_each():
    """正控：逐字 + `stmt:` 引用 + 一对一映射，四条判据一条都不响。"""
    fx = _paper()
    got = PL.check_paper_ledger(fx["paper"], fx["moved"], _stmts(), _deps(fx["moved"], _stmts()))
    assert got["checked"] is True, got
    assert got["problems"] == [], got["problems"]
    assert got["counts"]["moved"] == 2 and got["counts"]["mapped"] == 2, got["counts"]
    # 论文号互不相同、且形如 "1.x"
    assert sorted(fx["numbers"].values()) == ["1.1", "1.2"], fx["numbers"]
    # 正文里那两段与台账逐字相等（搬的时候一个字都没改写）
    for m in fx["moved"]:
        src = next(s for s in _stmts() if s["stmt_id"] == m["stmt_id"])
        assert m["text"] == src["statement_full"], (m, src)
        assert m["citation"] == f"stmt:{m['stmt_id']}", m


def test_a_mapping_row_has_the_field_combination_from_the_spec(store):
    """正控（写入侧）：`map_theorem` 落一行 `dependencies`，字段组合照 §9.5，号由分配器给。"""
    stmts = _stmts()
    with store.tx("statements", "dependencies", actor="test") as tx:
        tx.upsert("statements", S.Statement(
            stmt_id=S.format_id(7), origin="own_result", kind="theorem", label="主定理",
            statement_full=stmts[0]["statement_full"], quote_verified=None,
            quote_reason="（判据夹具）", doc_id=S.format_id(1), created_at=TS).to_dict())
        row = PL.map_theorem(tx, statement_row=stmts[0], paper_doc_id=S.format_id(9),
                             claim_id="c-1.1", paper_number="1.1")
    assert row["dep_id"] == S.format_id(0), row["dep_id"]
    assert row["used_by"] == f"doc:{S.format_id(9)}#c-1.1", row["used_by"]
    assert row["kind"] == "theorem" and row["label"] == "1.1", row
    # 来源手稿号取自**那一行自己**（`stmts[0]` 是夹具里的行，号由夹具给）——
    # 判据断言的是"抄对了来源"，不是"来源恰好是哪个十进制写法"。
    assert row["source_doc_id"] == str(stmts[0]["doc_id"]), row
    assert row["source_claim_id"] == "c-1.1", row
    # "四选一"是硬闸：这一行只挂手稿那一端，不许再挂 `source_stmt_id`
    assert not row.get("source_stmt_id"), (
        "同时给 source_doc_id 与 source_stmt_id 会被 `Dependency.validate` 拒"
        f"（给两个就说不清这条边到底依赖谁）：{row}")
    assert row["status"] == "closed", row
    assert store.rows("dependencies")[0]["dep_id"] == S.format_id(0), store.rows("dependencies")


# ==================================================== 二、负控（三种造假各一条）

def test_a_body_without_the_stmt_citation_is_red():
    """负控①：正文里没有 `stmt:` 引用 ⇒ 红。"""
    fx = _paper(drop="stmt:0008")
    got = PL.check_paper_ledger(fx["paper"], fx["moved"], _stmts(), _deps(fx["moved"], _stmts()))
    codes = [p["code"] for p in got["problems"]]
    assert "missing_citation" in codes, got["problems"]
    assert [p["stmt_id"] for p in got["problems"] if p["code"] == "missing_citation"] == ["0008"], got


def test_a_dangling_ref_and_a_shared_paper_number_are_red():
    """负控②：`\\ref` 悬空 ⇒ 红；两个不同 `stmt:` 共用一个论文号 ⇒ 红。"""
    fx = _paper()
    # (a) 悬空 `\ref`：映射行给的号在正文的交叉引用里没有
    got = PL.check_paper_ledger(fx["paper"], fx["moved"], _stmts(),
                                _deps(fx["moved"], _stmts()),
                                refs=["\\ref{thm:1.1}"])
    assert "dangling_ref" in [p["code"] for p in got["problems"]], got["problems"]
    # (b) 两个不同 stmt 映射到同一个论文号
    same = {"0007": "1.1", "0008": "1.1"}
    got2 = PL.check_paper_ledger(fx["paper"], fx["moved"], _stmts(),
                                 _deps(fx["moved"], _stmts(), number_of=same))
    codes2 = [p["code"] for p in got2["problems"]]
    assert "duplicate_paper_number" in codes2, got2["problems"]
    assert "missing_mapping" in codes2, ("1.2 这一号没人映射", got2["problems"])
    # 重号那一条必须点名是几号被几条映射行共用（§9.5 判的是映射行，不是正文那一侧）
    dup = next(p for p in got2["problems"] if p["code"] == "duplicate_paper_number")
    assert "1.1" in dup["why"] and "2 条映射行" in dup["why"], dup


def test_a_doc_reference_in_a_paper_is_red():
    """负控③：论文里出现 `doc:` ⇒ 红（两阶段引用口径：论文不许引别的稿子）。"""
    fx = _paper(citations_extra=["doc:0002#claim-1"])
    got = PL.check_paper_ledger(fx["paper"], fx["moved"], _stmts(), _deps(fx["moved"], _stmts()))
    hits = [p for p in got["problems"] if p["code"] == "doc_reference_in_paper"]
    assert hits and "两阶段引用" in hits[0]["why"], got["problems"]


# ==================================================== 三、反真空（两个方向都判）

def test_a_mapping_that_the_body_does_not_have_is_red():
    """反真空：映射表比正文多一行 ⇒ 红（只判"缺映射"会让这一半永远没人看得见）。"""
    fx = _paper()
    deps = _deps(fx["moved"], _stmts())
    deps.append(PL.dep_row_for_mapping(dep_id="0009", statement_row=_stmts()[0],
                                       paper_doc_id="0009", claim_id="c-幽灵",
                                       paper_number="1.9", created_at=TS))
    got = PL.check_paper_ledger(fx["paper"], fx["moved"], _stmts(), deps)
    assert "orphan_mapping" in [p["code"] for p in got["problems"]], got["problems"]


def test_a_body_that_is_not_verbatim_is_red():
    """反真空：正文里那一段被改过字 ⇒ 红（逐字是回验的前提）。"""
    fx = _paper()
    fx["moved"][0]["text"] = fx["moved"][0]["text"].replace("有限群", "有限交换群")
    got = PL.check_paper_ledger(fx["paper"], fx["moved"], _stmts(), _deps(fx["moved"], _stmts()))
    assert "not_verbatim" in [p["code"] for p in got["problems"]], got["problems"]


# ==================================================== 四、三态 + 复算

def test_an_unreadable_input_is_not_a_clean_bill():
    """三态：输入读不成 ⇒ `checked=False` + 理由（"没查成"不是"全对得上"）。"""
    got = PL.check_paper_ledger(None, [], None, None)   # type: ignore[arg-type]
    assert got["checked"] is False and got["reason"], got
    assert got["problems"] == [], got


def test_the_numbers_are_assigned_in_a_recomputable_order():
    """复算：论文号按 `stmt_id` 升序发（换个入参次序得到同一份映射）。"""
    stmts = _stmts()
    a = PL.assign_paper_numbers(stmts, section="1")
    b = PL.assign_paper_numbers(list(reversed(stmts)), section="1")
    assert a == b == {"0007": "1.1", "0008": "1.2"}, (a, b)
    assert PL.assign_paper_numbers(stmts, section="") == {"0007": "1", "0008": "2"}
    assert PL.assign_paper_numbers(stmts, section="2", start=3) == {"0007": "2.3", "0008": "2.4"}
