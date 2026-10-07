"""`claimanatomy` 的判据测试（每条规则一正一反，断言打在判据上）。

对应规格：`draft/17-正式文稿体例（参考投影度量论）.md` §8.3（第 1021–1052 行）。

## 这个文件要证明的四件事

1. 12 个字段真的能存：带全部 §8.3 字段的 claim 过 `schema.Document.validate()`
   且过 store 往返后一字不差 —— 这条是本任务"不改 `schema.py` 也能落地"的前置事实，
   若它被否证，后面所有接线都要推翻重来（所以它是本文件里的第一条用例）。
2. 两个轴正交：`status`（生命周期）与 `evidence_kind`（证据类型）自由组合，
   只把已知的不一致组合写成门，判不了时返回第三态。
3. 三态不退化：`True` / `False` / `None`（含 reason）必须能分开，
   且"检查器自己没跑成"有独立出口。
4. `statement` / `text` 只有一份字段名：迁移、存储往返、冲突检测三处都钉住。
"""

from __future__ import annotations

import ast
import json
import pathlib
from typing import Mapping

import pytest

from agentflow import claimanatomy as CA
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import doc_tools as DT

from conftest import TS


# ============================================================ 夹具


def base_claim(**over: object) -> dict:
    """一条八字段老形态的合法断言（磁盘上历史行的样子）。"""
    claim = {
        "claim_id": "claim-1",
        "section": "主要结果",
        "text": "谱落在区间内。",
        "evidence_kind": "proof",
        "citations": ["rel:0000", "lit:0000#p.12-13"],
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": "",
    }
    claim.update(over)
    return claim


def full_claim(**over: object) -> dict:
    """一条12 字段齐全的断言（§8.3 的目标形态）。"""
    claim = {
        "claim_id": "claim-2",
        "kind": "定理",
        "statement": "谱落在区间内。",
        "status": "证",
        "proof_location": "code/p1.py:12",
        "numeric_evidence": {
            "script": "code/p1.py",
            "range": "d<=33",
            "n_cases": 256,
            "n_counterexamples": 0,
        },
        "counterexamples": [],
        "frozen": False,
        "freeze_reason": "",
        "allowed_use": "主结果",
        "scope_caveat": "",
        "revision_hash": "deadbeefdeadbeef",
        "errata_ids": [],
        # ---- 本框架既有的五个字段（参考体例里没有，必须保留）
        "evidence_kind": "proof",
        "citations": ["rel:0000"],
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": "",
        "section": "主要结果",
    }
    claim.update(over)
    return claim


def codes(spec: CA.ClaimSpec) -> set[str]:
    return {i.code for i in spec.issues}


# ============================================================ 1. 字段声明表


def test_declared_fields_cover_both_the_reference_table_and_our_own():
    """12 个 §8.3 字段 + 我们既有的 5 个，一个都不许少。"""
    reference = {
        "claim_id", "kind", "statement", "status", "proof_location", "numeric_evidence",
        "counterexamples", "frozen", "freeze_reason", "allowed_use", "scope_caveat",
        "revision_hash", "errata_ids",
    }
    ours = {"citations", "evidence_kind", "is_negative", "negation_kind", "disclaimer"}
    assert reference <= set(CA.CLAIM_FIELDS), f"§8.3 的字段缺了：{reference - set(CA.CLAIM_FIELDS)}"
    assert ours <= set(CA.CLAIM_FIELDS), f"本框架既有字段缺了：{ours - set(CA.CLAIM_FIELDS)}"
    assert "section" in CA.CLAIM_FIELDS


def test_required_fields_match_what_schema_already_enforces():
    """`required_field_names()` 只列 schema 已经在硬拦的那些（保守口径）。

    为什么这条重要：把 §8.3 新增字段设成必填会让磁盘上全部历史行立刻非法，
    而 `schema.py` 是 FC-27 禁改区，无法同步迁移。
    """
    required = set(CA.required_field_names())
    assert required == {"claim_id", "statement", "citations", "evidence_kind", "is_negative", "section"}
    assert required.isdisjoint(CA.new_field_names()), "新增字段不许是必填"
    assert set(CA.required_field_names()) | set(CA.optional_field_names()) == set(CA.CLAIM_FIELDS)
    assert set(CA.new_field_names()) <= set(CA.optional_field_names())


def test_every_field_spec_has_a_why_and_a_source():
    """每个字段都必须写清"为什么"与"出处"（`DEVELOPMENT.md` 的写作纪律）。"""
    for name, spec in CA.CLAIM_FIELDS.items():
        assert spec.why.strip(), f"{name} 没有 why"
        assert spec.source.strip(), f"{name} 没有 source"
        assert spec.name == name
        if spec.domain is not None:
            assert spec.domain, f"{name} 声明了受控词表却是空的"


def test_evidence_kinds_are_not_a_second_copy():
    """`evidence_kind` 的词表与 `schema.EVIDENCE_KINDS` 是同一个对象（FC-03）。"""
    assert CA._evidence_kinds() == tuple(S.EVIDENCE_KINDS)
    assert CA._negation_kinds() == tuple(S.NEGATION_KINDS)


def test_overclaim_markers_and_disclaimer_are_not_a_second_copy():
    """过度声称措辞与免责声明同样只有一处定义（惰性转发到 `doc_tools`）。"""
    assert CA._overclaim_markers() == tuple(DT.OVERCLAIM_MARKERS)
    assert CA._cross_check_disclaimer() == DT.CROSS_CHECK_DISCLAIMER


# ============================================================ 2. 存储往返（前置事实）


def test_full_claim_passes_schema_validate_and_store_round_trip(store: Store):
    """本任务的前置事实：§8.3 的全部新字段今天就能写、能读、能过 JSON 往返。

    `Document.validate()` 只读它认识的键、不拒绝未知键，而 claim 是
    `documents.claims` 里的嵌套 dict —— 所以新增字段不需要改 `schema.py`
    （它在 FC-27 禁 AI 区，本任务无权编辑）。

    若这条被否证（例如某处会裁掉未知键），后面的接线全部作废 ——
    所以它是本文件的第一条，且断言是逐键相等而不是"有几个键在"。
    """
    claim = full_claim()
    row = S.Document(
        doc_id="0000",
        kind="paper",
        title="断言解剖学的往返测试",
        markdown_path=None,
        # 写入前必须转成磁盘形态（`statement` → `text`）：
        # `schema.Document.validate` 逐字读 `c.get("text")`，而它在 FC-27 禁 AI 区。
        # 这一行就是"新增字段今天就能存"的全部代价 —— 一次键名转换。
        claims=[CA.to_storage_claim(claim)],
        status="draft",
        created_at=TS,
        updated_at=TS,
    )
    # ① 过 writing-期硬约束
    row.validate()
    # ② 落盘 → 再读回来（store 的 JSON 往返）
    with store.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", row.to_dict())
    back = store.rows("documents")[0]
    got = dict(back["claims"][0])
    # 磁盘形态是 `text`（schema 读它），所以比较的是同一份内容的两种键名
    normalized = CA.migrate_claim(got)
    expected = CA.migrate_claim(claim)
    assert normalized == expected, f"往返后有字段变了：{ {k for k in set(normalized) | set(expected) if normalized.get(k) != expected.get(k)} }"
    # 逐字段点名（防止"整体相等"因为键被裁掉而误判）
    for name in CA.new_field_names():
        assert CA.presence_of(got, name) != "absent", f"新字段 {name} 在往返后丢了"
    for name in ("citations", "evidence_kind", "is_negative", "negation_kind", "disclaimer", "section"):
        assert CA.presence_of(got, name) != "absent", f"既有字段 {name} 在往返后丢了"


def test_documents_json_keeps_the_new_keys_verbatim(store: Store):
    """再加一道字节级的确认：盘上的 JSON 里那 12 个键真的在。"""
    claim = full_claim()
    row = S.Document(
        doc_id="0000", kind="paper", title="t", markdown_path=None,
        claims=[CA.to_storage_claim(claim)], created_at=TS, updated_at=TS,
    )
    row.validate()
    with store.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", row.to_dict())
    raw = json.loads((store.data / "documents.json").read_text(encoding="utf-8"))
    on_disk = dict(raw["rows"][0]["claims"][0])
    for name in CA.new_field_names():
        if name == "statement":
            assert on_disk.get("text") == claim["statement"], "statement 必须落成磁盘键 text（schema 读它）"
            continue
        assert name in on_disk, f"新字段 {name} 没有落盘"
        assert on_disk[name] == claim[name], f"新字段 {name} 落盘后值变了"


# ============================================================ 3. statement / text 迁移


def test_statement_is_the_canonical_name_and_text_is_its_alias():
    """`statement` 是正名、`text` 是别名 —— 只有一份字段名（FC-03）。"""
    spec = CA.CLAIM_FIELDS["statement"]
    assert spec.aliases == ("text",)
    # 老形态（只有 text）在 statement 这一项上是 `present`，不是 `absent`
    assert CA.presence_of(base_claim(), "statement") == "present"
    assert CA.claim_statement(base_claim()) == "谱落在区间内。"
    assert CA.claim_statement(full_claim()) == "谱落在区间内。"


def test_migrate_claim_renames_text_to_statement_and_drops_the_alias():
    """迁移后不许同时存在两个键（否则下游会看到两个不同的断言）。"""
    out = CA.migrate_claim(base_claim())
    assert "statement" in out and "text" not in out
    assert out["statement"] == "谱落在区间内。"


def test_migrate_claim_rejects_two_keys_with_different_content():
    """负控：`text` 与 `statement` 内容不同 ⇒ 抛，不许静默取其一。"""
    bad = full_claim()
    bad["text"] = "另一句话。"
    with pytest.raises(ValueError, match="内容不同"):
        CA.migrate_claim(bad)
    spec = CA.validate_claim(bad)
    assert spec.error_count == 1 and "bad_type" in codes(spec)


def test_migrate_claim_accepts_two_keys_with_the_same_content():
    """防误伤：两个键内容相同（迁移中途的正常形态）⇒ 允许，且只剩一个键。"""
    same = full_claim()
    same["text"] = same["statement"]
    out = CA.migrate_claim(same)
    assert "text" not in out and out["statement"] == same["statement"]


def test_storage_round_trip_preserves_every_new_field():
    """`statement ⇄ text` 的往返逐字段相等（写入路径依赖它）。"""
    canonical = CA.migrate_claim(full_claim())
    stored = CA.to_storage_claim(canonical)
    assert "text" in stored and "statement" not in stored
    assert CA.migrate_claim(stored) == canonical


# ============================================================ 4. 两个轴（正交）


def test_status_and_evidence_kind_are_two_independent_axes():
    """ⓘ 本模块的核心设计点：允许自由组合，只把已知矛盾写成门。

    这里穷举 4×3 = 12 种组合，断言"能自由写"且只有明确列出的那两种被判不一致。
    """
    legal_consistent = [
        ("证", "proof"),
        ("验", "cross_check"),
        ("验", "heuristic"),
        ("待精化", "proof"),
        ("待精化", "cross_check"),
        ("待精化", "heuristic"),
        ("作废", "proof"),
        ("作废", "cross_check"),
        ("作废", "heuristic"),
    ]
    for status, ek in legal_consistent:
        claim = full_claim(status=status)
        claim["evidence_kind"] = ek
        if status == "作废":
            claim["errata_ids"] = ["E-01"]
        if ek == "cross_check":
            claim["disclaimer"] = DT.CROSS_CHECK_DISCLAIMER
        spec = CA.validate_claim(claim)
        assert spec.verdict == CA.CONSISTENT, (status, ek, spec.verdict, spec.undecided_reason)
        assert "inconsistent_status" not in codes(spec)

    inconsistent = [("证", "cross_check"), ("证", "heuristic"), ("验", "proof")]
    for status, ek in inconsistent:
        claim = full_claim(status=status)
        claim["evidence_kind"] = ek
        if ek == "cross_check":
            claim["disclaimer"] = DT.CROSS_CHECK_DISCLAIMER
        spec = CA.validate_claim(claim)
        assert spec.verdict == CA.DECIDED_INCONSISTENT, (status, ek)
        assert "inconsistent_status" in codes(spec)
        assert spec.decided is False


def test_retracted_is_not_an_evidence_kind_but_a_lifecycle_state():
    """`作废` 是生命周期，与证据类型无关：它必须能表达，且必须有原因。"""
    retracted = full_claim(status="作废", errata_ids=["E-01"])
    spec = CA.validate_claim(retracted)
    assert spec.verdict == CA.CONSISTENT
    assert CA.is_retracted(retracted) is True
    assert CA.is_retracted(full_claim(status="证")) is False

    # 负控：作废但不说为什么 ⇒ error（第 4 族「生命周期自洽」，`draft/39` §3.11 四起
    # 它有自己的 code —— 族号要能直接印在拒信里）
    no_reason = full_claim(status="作废", errata_ids=[], freeze_reason="")
    spec2 = CA.validate_claim(no_reason)
    assert spec2.error_count >= 1
    assert "lifecycle_incomplete" in codes(spec2)

    # 防误伤：作废 + 冻结理由（合法的另一种原因）⇒ 通过
    frozen_reason = full_claim(status="作废", errata_ids=[], freeze_reason="连败 5 次，结论作废")
    assert CA.validate_claim(frozen_reason).verdict == CA.CONSISTENT


def test_status_evidence_consistency_returns_three_states():
    """交叉轴门返回三态，且第三态带 reason（不是布尔）。"""
    ok, reason = CA.status_evidence_consistency("证", "proof")
    assert ok == CA.CONSISTENT and reason.strip()
    bad, reason2 = CA.status_evidence_consistency("证", "heuristic")
    assert bad == CA.DECIDED_INCONSISTENT and reason2.strip()
    unknown, reason3 = CA.status_evidence_consistency(None, "proof")
    assert unknown == CA.CONSISTENCY_UNKNOWN
    assert "没判" in reason3, "第三态必须说清『这是没判，不是判过一致』"


# ============================================================ 5. 三态纪律不退化


def test_missing_axis_is_unknown_not_consistent_and_not_error():
    """缺 `status` 的老行 ⇒ 判不了（既不是 error，也不是"一致"）。"""
    spec = CA.validate_claim(base_claim())
    assert spec.checked is True
    assert spec.decided is False
    assert spec.verdict == CA.CONSISTENCY_UNKNOWN
    assert spec.undecided_reason.strip()
    assert spec.error_count == 0, "缺新字段不是作者的错（历史数据），不许报 error"
    assert "unknown_status_axis" in codes(spec)


def test_lifecycle_verdict_is_three_state():
    """`lifecycle_verdict` 返回 `True` / `False` / `None` 三种，且都带 reason。"""
    yes, why_yes = CA.lifecycle_verdict(full_claim())
    assert yes is True and why_yes.strip()
    no, why_no = CA.lifecycle_verdict(full_claim(status="验"))
    assert no is False and why_no.strip()
    unknown, why_unknown = CA.lifecycle_verdict(base_claim())
    assert unknown is None and why_unknown.strip()


def test_checker_error_has_its_own_exit(monkeypatch: pytest.MonkeyPatch):
    """"检查器自己没跑成"必须有别于"检查过了没问题"（独立出口）。

    做法：把 `migrate_claim` 打桩成抛 `RuntimeError`（不是 `ValueError`）——
    于是判据层自己崩了。返回值必须是 `checked=False` + `checker_error`，
    不许是"通过"，也不许把异常抛给调用方。
    """
    def boom(_claim):
        raise RuntimeError("模拟判据层内部异常")

    monkeypatch.setattr(CA, "migrate_claim", boom)
    spec = CA.validate_claim(base_claim())
    assert spec.checked is False
    assert spec.decided is False
    assert "checker_error" in codes(spec)
    assert "RuntimeError" in spec.undecided_reason


def test_presence_of_separates_absent_from_empty():
    """`absent`（没提这件事）与 `empty`（明确写了空）必须分开。"""
    assert CA.presence_of({"frozen": False}, "frozen") == "present"
    assert CA.presence_of({"frozen": None}, "frozen") == "empty"
    assert CA.presence_of({}, "frozen") == "absent"
    assert CA.presence_of({"kind": ""}, "kind") == "empty"
    # 空清单是合法形态（"我查过、没有"），不是 empty
    assert CA.presence_of({"counterexamples": []}, "counterexamples") == "present"


# ============================================================ 6. 字段级门（正 + 负）


@pytest.mark.parametrize(
    "mutate,expect_code",
    [
        (lambda c: c.update({"kind": "猜想"}), "bad_enum"),
        (lambda c: c.update({"status": "已证"}), "bad_enum"),
        (lambda c: c.update({"allowed_use": "附录"}), "bad_enum"),
        (lambda c: c.update({"evidence_kind": "prooof"}), "bad_enum"),
        (lambda c: c.update({"frozen": "yes"}), "bad_type"),
        (lambda c: c.update({"counterexamples": "反例"}), "bad_type"),
        (lambda c: c.update({"numeric_evidence": [1, 2]}), "bad_type"),
        (lambda c: c.update({"errata_ids": "E-01"}), "bad_type"),
        # 第 7 族（数值证据四元组）在 `draft/39` §3.11 四之后有了自己的 code：
        # 族号要能直接印在拒信里，而"缺 `numeric_evidence` 的键"与"必填字段为空"
        # 是两族不同的判据（前者是结构不全，后者是字段在不在）。
        (lambda c: c.update({"numeric_evidence": {"script": "s.py"}}),
         "incomplete_numeric_evidence"),
        (lambda c: c.update({"frozen": True, "freeze_reason": ""}), "empty_required"),
        (lambda c: c.update({"citations": []}), "empty_required"),
        (lambda c: c.update({"citations": ["", "  "]}), "bad_type"),
        (lambda c: c.update({"statement": ""}), "empty_required"),
        (lambda c: c.pop("claim_id"), "empty_required"),
    ],
)
def test_field_gates_reject_bad_values(mutate, expect_code):
    """负控：字段存在但非法 —— 必须报出指定的那个 code（不是"有个错误"）。"""
    claim = full_claim()
    mutate(claim)
    spec = CA.validate_claim(claim)
    assert expect_code in codes(spec), f"期望 {expect_code}，实际 {codes(spec)}"
    assert spec.error_count >= 1


def test_field_gates_accept_the_full_claim():
    """正控：12 字段齐全且合法的断言必须零 error 且 decided。"""
    spec = CA.validate_claim(full_claim())
    assert spec.error_count == 0
    assert spec.warning_count == 0
    assert spec.decided is True
    assert spec.verdict == CA.CONSISTENT
    assert spec.fields_used == ("status", "evidence_kind")


def test_unknown_field_is_reported_but_does_not_break_the_claim():
    """未声明的键要报出来（warning），但不让整条断言变成非法。"""
    claim = full_claim()
    claim["favourite_colour"] = "blue"
    spec = CA.validate_claim(claim)
    assert "undeclared_field" in codes(spec)
    assert spec.error_count == 0


def test_strict_mode_asks_for_the_full_twelve_fields_but_only_warns():
    """`strict=True` 要求补齐 12 字段，但只报 warning（不是 error）。"""
    spec_lax = CA.validate_claim(base_claim(), strict=False)
    spec_strict = CA.validate_claim(base_claim(), strict=True)
    assert spec_lax.warning_count == 0
    assert spec_strict.warning_count > 0
    assert spec_strict.error_count == 0, "缺新字段永远不是 error（历史数据）"
    assert any(i.code == "missing_field" for i in spec_strict.issues)


# ============================================================ 7. 稿件级判定与汇总


def test_validate_document_claims_reports_duplicate_ids():
    """同一 claim_id 对应两段不同文字 ⇒ error（审校将无法定位）。"""
    doc = {"doc_id": "0000", "claims": [full_claim(), full_claim(statement="另一句话。")]}
    issues = CA.validate_document_claims(doc)
    dups = [i for i in issues if i.code == "duplicate_claim_id"]
    assert len(dups) == 1 and dups[0].level == "error"


def test_validate_document_claims_without_claims_is_unknown_not_empty():
    """没有 `claims` 键 ⇒ 没查（不是"没有断言"）——三态纪律在稿件层的形态。"""
    issues = CA.validate_document_claims({"doc_id": "0000"})
    assert len(issues) == 1
    assert issues[0].code == "missing_field" and issues[0].level == "error"
    assert "没查" in issues[0].message


def test_consolidate_issues_keeps_the_undecidable_bucket_separate():
    """汇总必须单独给出"判不了"这一档（FC-10：禁止单一通过率）。"""
    issues = CA.validate_document_claims({"doc_id": "0000", "claims": [base_claim()]})
    agg = CA.consolidate_issues(issues)
    assert agg["undecidable_count"] == 1
    assert agg["decided"] is False
    assert agg["has_errors"] is False
    assert agg["codes"] == ["unknown_status_axis"]
    text = CA.summary_counts(issues)["message"]
    assert "判不了=1" in text


def test_has_issue_and_count_by_code_are_queryable():
    """判据必须能被机器查询（门要用它，而不是再写一遍判断）。"""
    issues = CA.validate_document_claims({"doc_id": "0000", "claims": [base_claim()]})
    assert CA.has_issue(issues, "unknown_status_axis") is True
    assert CA.has_issue(issues, "checker_error") is False
    assert CA.count_by_code(issues) == {"unknown_status_axis": 1}


# ============================================================ 8. 版本 hash（G11）


def test_revision_hash_is_stable_and_content_addressed():
    """内容不变 ⇒ hash 不变；内容一变 ⇒ hash 变。"""
    a = {"doc_id": "0000", "kind": "paper", "title": "t", "claims": [full_claim()]}
    b = {"doc_id": "0000", "kind": "paper", "title": "t", "claims": [full_claim()]}
    assert CA.revision_hash(a) == CA.revision_hash(b)
    c = {"doc_id": "0000", "kind": "paper", "title": "t", "claims": [full_claim(statement="改了。")]}
    assert CA.revision_hash(a) != CA.revision_hash(c)


def test_revision_hash_ignores_review_bookkeeping():
    """`status` / `review_rounds` 不参与 hash。

    否则"审校改了稿件状态"这件事本身会改变被审版本的 hash ——
    于是报告里的 hash 永远对不上被审对象（G11 就自相矛盾了）。
    """
    a = {"doc_id": "0000", "kind": "paper", "title": "t", "status": "draft", "review_rounds": 0, "claims": [full_claim()]}
    b = {"doc_id": "0000", "kind": "paper", "title": "t", "status": "accepted", "review_rounds": 3, "claims": [full_claim()]}
    assert CA.revision_hash(a) == CA.revision_hash(b)


def test_claim_content_hash_excludes_its_own_revision_hash():
    """自指必须排除：给一条断言打 hash 不能改变它自己的 hash。"""
    c1 = full_claim()
    c2 = full_claim(revision_hash="0000000000000000")
    assert CA.claim_content_hash(c1) == CA.claim_content_hash(c2)
    # 而正文变了 ⇒ hash 必须变
    assert CA.claim_content_hash(c1) != CA.claim_content_hash(full_claim(statement="另一句。"))


# ============================================================ 9. 渲染层降级门（G14）


def test_main_body_claims_excludes_retracted_and_open():
    """正文主结果区不得出现作废断言与"移入 open"的断言（G14 的渲染层落地）。"""
    claims = [
        full_claim(claim_id="a"),
        full_claim(claim_id="b", status="作废", errata_ids=["E-01"]),
        full_claim(claim_id="c", allowed_use="移入 open"),
    ]
    body = CA.main_body_claims(claims)
    assert [c["claim_id"] for c in body] == ["a"]
    assert [c["claim_id"] for c in CA.retracted_claims(claims)] == ["b"]


def test_render_markdown_puts_retracted_claims_in_the_appendix_only(store: Store):
    """渲染层门：作废断言不在正文，但必须出现在附录（并带撤销原因）。

    只把作废断言删掉，读者会把"作者改过主意"读成"这些结论从来没存在过"。
    """
    good = DT.compose_claim(
        "谱落在区间内。", citations=["rel:0000"], evidence_kind="proof", section="主要结果",
        claim_id="claim-1", kind="定理", status="证",
    )
    dead = DT.compose_claim(
        "这个不等式对所有 n 成立。", citations=["rel:0000"], evidence_kind="cross_check",
        section="主要结果", claim_id="claim-2", kind="命题", status="作废",
        errata_ids=["E-01"],
        scope_caveat="反例 n=3",
    )
    doc = {
        "doc_id": "0000", "kind": "paper", "title": "t", "status": "draft",
        "review_rounds": 0, "claims": [good, dead], "open_problems": [],
    }
    md = DT.render_markdown(doc, dependencies=[])
    body, _, appendix = md.partition("## 附录 A.")
    assert "谱落在区间内。" in body
    assert "这个不等式对所有 n 成立。" not in body, "作废断言不许出现在正文"
    assert "已作废 1" in md, "正文头必须显式承认有多少条被移出去"
    assert "这个不等式对所有 n 成立。" in appendix, "作废断言必须在附录里留痕（不许凭空消失）"
    assert "E-01" in appendix, "附录必须写出撤销原因"


def test_compose_claim_carries_the_lifecycle_fields(store: Store):
    """构造期就带上 §8.3 字段（而不是"写完再补"）。"""
    claim = DT.compose_claim(
        "谱落在区间内。", citations=["rel:0000"], evidence_kind="cross_check", section="数值",
        claim_id="claim-9", kind="命题", status="验",
        numeric_evidence={"script": "code/s.py", "range": "d<=10", "n_cases": 9, "n_counterexamples": 0},
        counterexamples=[], allowed_use="Remark only", scope_caveat="仅限有限阶 θ",
    )
    assert claim["kind"] == "命题" and claim["status"] == "验"
    assert claim["allowed_use"] == "Remark only"
    assert claim["scope_caveat"] == "仅限有限阶 θ"
    assert claim["numeric_evidence"]["n_cases"] == 9
    assert claim["disclaimer"] == DT.CROSS_CHECK_DISCLAIMER


def test_ee06_compose_claim_derives_status_and_allowed_use_from_the_evidence_kind():
    """EE-06 产出方：`status` / `allowed_use` 从这条断言自己的证据等级派生。

    改前这两个字段从来没有产出方（真机读数 `status` 0/449、`allowed_use` 0/449），
    而消费方一直在（`gates.py` 的 G14、`claimanatomy.main_body_claims`、渲染层）。
    依据是 `claimanatomy` 已写死的两条一致性规则，不是这里新造判据：
    `proof` ⇒ `证`（"证"必须有 proof 级证据，FC-22）；`cross_check` ⇒ `验` + `Remark only`
    （只有数值支撑的结论不得进摘要/主结果）。
    """
    proof = DT.compose_claim("存在无穷多个素数。", citations=["exp:0000"], evidence_kind="proof",
                             section="主要结果")
    assert proof["status"] == "证", proof
    assert "allowed_use" not in proof, "proof 级断言不该被降级成 Remark"

    cross = DT.compose_claim("谱落在区间内。", citations=["lit:0000"], evidence_kind="cross_check",
                             section="主要结果")
    assert cross["status"] == "验", cross
    assert cross["allowed_use"] == "Remark only", "只有数值支撑的结论必须降为 Remark"


def test_ee06_no_basis_means_no_value_and_explicit_input_wins():
    """反负控（三态）：没有依据就不写，而且派生不许覆盖调用方显式给的值。

    这是 EE-06 最容易做错的方向：把"从没问过"伪造成"待精化"
    （`docs/SCHEMA-MIGRATION-PROPOSAL-claims.md` §3.2 逐字警告过）。
    """
    weak = DT.compose_claim("这可能是对的。", citations=["lit:0000"], evidence_kind="heuristic",
                            section="s")
    assert "status" not in weak and "allowed_use" not in weak, weak

    explicit = DT.compose_claim("存在无穷多个素数。", citations=["exp:0000"],
                                evidence_kind="proof", section="s", status="待精化")
    assert explicit["status"] == "待精化", "派生不许覆盖调用方显式给的值"


def test_compose_claim_rejects_retracted_without_a_reason():
    """负控：`status="作废"` 却不说为什么 ⇒ 构造时就抛。"""
    with pytest.raises(ValueError, match="作废"):
        DT.compose_claim(
            "这条不算了。", citations=["rel:0000"], evidence_kind="heuristic",
            section="s", status="作废",
        )


def test_compose_claim_rejects_frozen_without_a_reason():
    """负控：`frozen=True` 却没有 `freeze_reason` ⇒ 构造时就抛。"""
    with pytest.raises(ValueError, match="freeze_reason"):
        DT.compose_claim(
            "冻结但不说为什么。", citations=["rel:0000"], evidence_kind="heuristic",
            section="s", frozen=True,
        )


def test_compose_claim_does_not_invent_default_values_for_new_fields():
    """不给就是不写：不许替作者填一个假的默认值（三态纪律）。"""
    claim = DT.compose_claim(
        "没有生命周期字段的断言。", citations=["rel:0000"], evidence_kind="heuristic", section="s",
    )
    assert "status" not in claim and "kind" not in claim and "allowed_use" not in claim
    assert "frozen" not in claim


# ============================================================ 8. 断言台账的四列（`draft/31` P3）


def ledger_claim(**over: object) -> dict:
    """一条带台账四列 + 两列出处的断言（P3 的目标形态）。

    `text` 必须去掉：`base_claim` 是磁盘上的老形态（正文在 `text` 里），
    而这条要用正名 `statement` —— 两个键同时在场且不一致，`migrate_claim`
    会（正确地）判 `bad_type`。
    """
    claim = base_claim()
    claim.pop("text")
    claim.update(
        {
            "claim_id": "prop:step",
            "statement": "一步位移：Δ=2πρ，条件期望 0，二阶矩 8。",
            "evidence_kind": "cross_check",
            "citations": ["exp:0008"],
            "disclaimer": DT.CROSS_CHECK_DISCLAIMER,
            "source_kind": "文献",
            "our_check": "数值",
            "our_check_note": "复算 exp:0008 的位移集（|Δ|²=8），1121 个腔室全过。",
            "falsifiable": True,
            "falsifiable_note": "反例搜索 1121 个腔室，0 个不符。",
            "paper_ref": "source/main.tex:211#prop:step",
            "paper_excerpt": "[one-step displacement; \\cite{Companion5}]",
        }
    )
    claim.update(over)
    return claim


def test_ledger_columns_are_declared_optional_and_domain_controlled():
    """四列 + 两列出处进了声明表：可选、取值域受控、且不属于 §8.3 那 12 个字段。

    这一条是那个缺口的判据本身：实测 2026-09-29，P3 的 24 行台账被 H 审出
    240 条 `undeclared_field`（10 个自有键 × 24 条）—— 字段落了库，
    但门读不到它们。若有人把这几列从 `CLAIM_FIELDS` 里删掉，
    本条会失败，而不是让台账悄悄退回到"写进去没人看"的状态。
    """
    for name in ("source_kind", "our_check", "our_check_note", "falsifiable",
                 "falsifiable_note", "paper_ref", "paper_excerpt"):
        assert name in CA.CLAIM_FIELDS, f"台账的列 {name} 没进声明表"
        assert CA.CLAIM_FIELDS[name].required is False, f"{name} 不该是必填（历史行没有它）"
        assert name not in CA.new_field_names(), (
            f"{name} 不是 `draft/17` §8.3 的字段，不许混进 new_field_names()："
            "那张名单被 strict 模式的『补齐 12 字段』直接读"
        )
    assert CA.CLAIM_FIELDS["source_kind"].domain == CA.CLAIM_SOURCE_KINDS
    assert CA.CLAIM_FIELDS["our_check"].domain == CA.CLAIM_CHECK_KINDS
    assert CA.CLAIM_FIELDS["falsifiable"].domain is None, "bool 字段不该有词表"


def test_ledger_claim_has_no_errors_and_no_undeclared_field_warning():
    """正控：六列齐全的台账断言零 error、零 warning（含零 `undeclared_field`）。"""
    spec = CA.validate_claim(ledger_claim())
    assert spec.error_count == 0, codes(spec)
    assert spec.warning_count == 0, codes(spec)
    assert "undeclared_field" not in codes(spec)


@pytest.mark.parametrize(
    "field,value,expect_code",
    [
        ("source_kind", "自证证", "bad_enum"),
        ("source_kind", "文献 ", "bad_enum"),      # 尾随空格不许被宽容匹配
        ("source_kind", "文献来源", "bad_enum"),
        ("our_check", "大概看过", "bad_enum"),
        ("our_check", "数值验证", "bad_enum"),
        ("falsifiable", "是", "bad_type"),
        ("falsifiable", 1, "bad_type"),
        ("our_check_note", 3, "bad_type"),
        ("falsifiable_note", ["反例搜索"], "bad_type"),
        ("paper_ref", 211, "bad_type"),
        ("paper_excerpt", {"text": "…"}, "bad_type"),
    ],
)
def test_ledger_columns_reject_illegal_values(field, value, expect_code):
    """负控：取值域与类型都是判据，不是注释 —— 逐格报出指定的 code 与字段名。"""
    spec = CA.validate_claim(ledger_claim(**{field: value}))
    hits = [(i.code, i.field_name) for i in spec.issues if i.field_name == field]
    assert (expect_code, field) in hits, f"期望 {expect_code}@{field}，实际 {hits}"
    assert spec.error_count >= 1


def test_ledger_columns_do_not_soften_the_unknown_key_check():
    """负控：声明了台账的列，不等于"任何键都收"—— 别的键照样报 `undeclared_field`。"""
    spec = CA.validate_claim(ledger_claim(source_kind_typo="文献"))
    assert "undeclared_field" in codes(spec)
    assert spec.error_count == 0, "未声明的键是 warning（不许升级成 error 把红灯长亮）"


# ------------------------------------------- 六张断言词表的「单一来源」（`EE-06` / 题 2-B）

#: 六张断言语义词表（它们各自的取值域由 `CLAIM_FIELDS[...].domain` 承载）。
#: 含 `NUMERIC_EVIDENCE_KEYS`：它不是"枚举域"而是"四元组的键名表"，但它与
#: 其余五张一样是"真身在 `schema.py`、本模块只 import"的受控词表。
_VOCABS = ("CLAIM_KINDS", "CLAIM_STATUSES", "ALLOWED_USE_KINDS",
           "NUMERIC_EVIDENCE_KEYS", "CLAIM_SOURCE_KINDS", "CLAIM_CHECK_KINDS")

#: 真身所在的模块（相对 `claimanatomy` 所在包的路径）。
#: 2026-10-07 所有者裁定 `draft/68` 题 2 选 B（把真身搬进 `schema.py`，
#: 本次由所有者授权、主控代改）⇒ 判据从"不许搬"改成"只许在 `schema.py` 有一处"。
_VOCAB_HOME = "schema.py"


def _tree_sources() -> dict[str, str]:
    """整棵包的源码（口径：`claimanatomy` 所在包下所有 `.py`，排除 `__pycache__`）。"""
    root = pathlib.Path(CA.__file__).resolve().parent
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts}


def _vocabulary_definitions(sources: Mapping[str, str]) -> dict[str, list[str]]:
    """每个词表名在给定源码集合里的「模块级定义处」（口径：`Assign`/`AnnAssign` 的目标名）。

    只数定义（模块级赋值目标名），不数引用 —— `tools/doc_tools.py` 的
    `list(CA.CLAIM_KINDS)` 是对同一份词表的引用，它不该被算成第二处定义；
    `claimanatomy.py` 里的 `from .schema import CLAIM_KINDS` 是 `ImportFrom`，
    同样不是定义（否则"搬家"与"留副本"在读法上就分不开了）。
    """
    out: dict[str, list[str]] = {name: [] for name in _VOCABS}
    for rel, text in sources.items():
        for node in ast.parse(text).body:
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
            else:
                targets = []
            for name in _VOCABS:
                if name in targets:
                    out[name].append(f"{rel}:{node.lineno}")
    return out


def _inline_domain_problem(sources: Mapping[str, str]) -> list[str]:
    """工具侧的取值域必须是 `list(CA.<词表>)`（引用），不许内联成字面量（`EE-06` 的反面形态）。"""
    text = sources.get("tools/doc_tools.py", "")
    out: list[str] = []
    for name in ("CLAIM_KINDS", "CLAIM_STATUSES", "ALLOWED_USE_KINDS"):
        if f"list(CA.{name})" not in text:
            out.append(f"`tools/doc_tools.py` 里读不到 `list(CA.{name})` —— 取值域要么被内联、要么丢了")
    for name in _VOCABS:
        members = getattr(CA, name)
        literals = (", ".join(repr(m) for m in members))
        for probe in (f'"enum": ({literals})', f'"enum": [{literals}]'):
            if probe in text:
                out.append(f"`tools/doc_tools.py` 把 {name} 内联成了字面量（{probe[:44]}…）")
    return out


def test_the_six_claim_vocabularies_have_exactly_one_definition_in_schema():
    """`EE-06` ①：六张词表各只有一处定义，且那一处在 `schema.py`，工具侧只引用不内联。

    这条守的是 `EE-06` 的原意（"取值域校验存在、且只有一份"）加 2026-10-07 的裁定
    `draft/68` 题 2 选 B（真身搬进 `schema.py`，本次由所有者授权、主控代改）：
    判据从"不许有第二份"升级成"只有一份、且那一份在 `schema.py`" ——
    搬回去一半（在 `claimanatomy` 里再写一份同值字面量）会同时踩两条。

    为什么"位置"也值得判：同值但不共用的两份拷贝在改名、加值、删值时会静默漂移
    （`CAM` 那族缺陷的形态），而两侧各自自洽、没有任何东西会红。位置 + 唯一性
    一起判，才等价于"两边读的是同一份"。

    负控（同一条里，三半都验）：① 往源码集合里塞一份词表副本 ⇒ 同一个读法必须报出 2 处；
    ② 把 `doc_tools` 的 `list(CA.X)` 换成内联字面量 ⇒ `_inline_domain_problem` 必须报出来；
    ③ 把定义处从 `schema.py` 挪到别的文件 ⇒ `_VOCAB_HOME` 那一半必须报出来。
    """
    sources = _tree_sources()
    # 反真空：扫描器真的读到了整棵包（读不到时下面每一格都会"恰好一处"缺席，
    # 而不是恰好一处 —— 但把下限写出来，这条判据就不会因为"扫了个空树"而变绿）
    assert len(sources) >= 50, f"只扫到 {len(sources)} 个源文件 ⇒ 扫描器没接上"
    assert "schema.py" in sources and "claimanatomy.py" in sources, sorted(sources)[:5]

    copies = _vocabulary_definitions(sources)
    bad = {n: v for n, v in copies.items() if len(v) != 1}
    assert not bad, f"这些词表不是「只有一处定义」（要防的就是第二份）：{bad}"
    homeless = {n: v for n, v in copies.items() if not v[0].startswith(_VOCAB_HOME + ":")}
    assert not homeless, (
        f"这些词表的唯一一处定义不在 `{_VOCAB_HOME}`：{homeless}；"
        "真身按 2026-10-07 裁定（`draft/68` 题 2 选 B）在 `schema.py`")
    problem = _inline_domain_problem(sources)
    assert not problem, "；".join(problem)

    # 反负控①：造一份词表副本 ⇒ 必须红（逐张都试，不只第一张）
    for name in _VOCABS:
        doctored = dict(sources)
        doctored["_probe_copy.py"] = f"{name} = ('探针',)\n"
        assert len(_vocabulary_definitions(doctored)[name]) == 2, (
            f"反负控失效：{name} 的副本没被读出来")

    # 反负控②：把引用换成内联字面量 ⇒ 必须红
    doc = sources["tools/doc_tools.py"]
    inline = doc.replace('"enum": list(CA.CLAIM_KINDS)',
                         '"enum": (' + ", ".join(repr(m) for m in CA.CLAIM_KINDS) + ')')
    assert inline != doc, "反负控没改到 `doc_tools` 那处引用"
    assert _inline_domain_problem({**sources, "tools/doc_tools.py": inline}), (
        "把引用换成内联字面量之后判据一声不吭 ⇒ 它是真空的")

    # 反负控③：把真身挪出 `schema.py`（模拟"搬回去一半"）⇒ 位置那一半必须红
    moved = {k: v for k, v in sources.items() if k != _VOCAB_HOME}
    moved[_VOCAB_HOME] = "\n".join(
        line for line in sources[_VOCAB_HOME].splitlines()
        if not any(line.startswith(f"{n} =") or line.startswith(f"{n}: tuple")
                   for n in _VOCABS))
    moved["claimanatomy.py"] = sources["claimanatomy.py"] + "\nCLAIM_KINDS = ('定义',)\n"
    back = _vocabulary_definitions(moved)
    homeless_back = {n: v for n, v in back.items()
                     if not v or not v[0].startswith(_VOCAB_HOME + ":")}
    assert homeless_back, (
        "反负控失效：把真身挪出 `schema.py`（并在 `claimanatomy` 里放回一份局部定义）之后，"
        "位置判据一声不吭")


def test_schema_and_claimanatomy_read_the_same_vocabulary_objects():
    """`EE-06` ②：搬完之后两边读到的是同一份（值相等，且 `is` 同一个对象）。

    为什么"相等"不够：两张同值的中文词表可以各自被改一格而另一方不知道 ——
    `CLAIM_FIELDS[*].domain` 走 `claimanatomy`、将来的读侧可能走 `schema`，
    两边给出不同取值域就是 FC-03 的形态，而它们"值相等"时这个风险照样存在。
    `is` 把"同一份"变成可机械判的事实（`DEVELOPMENT.md` §3 纪律 2 的原型：
    `tools.ROLES is schema.ROLES`）。

    负控：把 `claimanatomy` 侧换成同值但新造的一个 tuple ⇒ 值那一半仍过、
    `is` 那一半必须红（这一条就是"同值拷贝"与"同一份"的分界线）。
    """
    from agentflow import schema as S

    assert S is not CA, "夹具前提：两者不是同一个模块"
    for name in _VOCABS:
        mine, theirs = getattr(CA, name), getattr(S, name)
        assert mine == theirs, f"{name}：两边值不等（{mine!r} != {theirs!r}）"
        assert mine is theirs, (
            f"{name}：两边只是值相等、不是同一个对象 ⇒ 存在第二份拷贝，"
            "改一格不会有任何东西响（`is` 是这条判据的全部要点）")

    # 负控：同值拷贝 ⇒ 值那一半过、`is` 那一半红。
    # 用 `tuple(list(...))` 造一个新元组（`tuple(元组)` 会原样返回同一个对象，
    # 那种写法做不出"同值但不同对象"的样本）。
    probe = tuple(list(CA.CLAIM_KINDS))
    assert probe == S.CLAIM_KINDS and probe is not S.CLAIM_KINDS, (
        "反负控前提不成立：同值拷贝本该是另一个对象")
    assert not (probe is S.CLAIM_KINDS), "同值拷贝与同一份必须分得开"


def test_the_bits_shape_judge_has_exactly_one_definition():
    """`evidencebits` 单一来源：判 `bits` 形状的两个函数各只有一处定义。

    为什么只钉「定义唯一」、不钉「`schema.py` 是唯一调用点」：本判据要抓的缺陷是
    "又有人写了一份判形状的实现"，而那种实现哪怕只有一个新调用点也照样是第二份口径；
    反过来，钉死调用点集合会让将来任何合法的读侧消费者因为一条与缺陷无关的理由变红，
    而"改这条判据"就变成走形式。定义唯一是可机械判的、且直接对应缺陷本身 ——
    将来若真要在别处判形状，正确做法是调 `bit_problems`（`schema.py:1739` 就是这么做的）。

    负控：在别处造第二个判形状的函数 ⇒ 同一个读法必须报出两处。
    """
    authors: dict[str, list[str]] = {}
    for rel, text in _tree_sources().items():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.FunctionDef) and node.name in ("bits_shape_problems", "bit_problems"):
                authors.setdefault(node.name, []).append(f"{rel}:{node.lineno}")
    bad = {n: v for n, v in authors.items() if len(v) != 1}
    assert not bad, f"判 `bits` 形状的函数定义不止一处（`EE-06` 要防的第二份口径）：{bad}"

    # 反负控：在别处造第二个判形状的函数 ⇒ 必须红
    doctored = dict(_tree_sources())
    doctored["_probe_second_judge.py"] = (
        "def bits_shape_problems(raw):\n"
        "    return [] if isinstance(raw, dict) else ['坏']\n")
    seen: dict[str, list[int]] = {}
    for rel, text in doctored.items():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.FunctionDef) and node.name == "bits_shape_problems":
                seen.setdefault(rel, []).append(node.lineno)
    assert len(seen) == 2, f"反负控失效：第二份判形状的实现没被读出来（{seen}）"
