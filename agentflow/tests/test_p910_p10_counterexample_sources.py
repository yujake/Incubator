"""`P-10` 候选 A（2026-09-27 所有者裁定）的成对正控/负控。
## 这一批落地了什么
不新增字段、不改语义，只把两个反例来源的分工写清，并加一条判据：
* `counterexamples` = 人 / 文献已知的反例清单（可能来自别处）；
它是空清单时只说"没有已知反例"，不说"机器没扫到反例"；
* `numeric_evidence.n_counterexamples` = 那一次数值运行机器扫到的条数
（与 `script` / `range` / `n_cases` 同属一个四元组）；
* 两者都非空且不相等时 `scope_caveat` 必填（判据落在
`schema.Document.validate()` 的写入期路径上，不在任何门上）。
## 为什么这条判据不在 G12 里（本文件钉住的那一半）
`P-10` 原文最后一句是硬约束："在裁定之前，不许为它加门" —— 加门等于替项目选口径（"哪个数更权威"）。所以本文件里有一条反向负控：两源不等时 G12 的判决必须仍是 `pass`（不是 `error`/`fail`）。
判据只在"差异要有一句可判定的话"这一层，它不判定谁更权威。
## 负控的形态
与 `test_p910_p9_review_finding_format.py` 相同：把违规注入正控夹具的文本副本，断言锚点恰好命中 1 次、字节确实变了、打印副本 sha256，再断言下游由绿变红。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agentflow import claimanatomy as CA
from agentflow import gates as G
from agentflow import schema as S
from agentflow.store import Store

from test_coverage_gates import _claim, _doc

#: 正控夹具（"当前字节"）：两个反例来源不相等、且差异已经自证。
#: 这正是 `P-10` 原文说的"两者本来就不该相等"的正确形态。
GOOD_DOC: dict = {
    "doc_id": "0000",
    "kind": "paper",
    "title": "反例两源分工的夹具",
    "markdown_path": None,
    "sections": [],
    "claims": [
        {
            "claim_id": "claim-1",
            "kind": "定理",
            "text": "谱落在区间内。",
            "evidence_kind": "cross_check",
            "disclaimer": "数值交叉验证，不构成证明",
            "citations": ["rel:0000"],
            "is_negative": False,
            "negation_kind": None,
            "counterexamples": ["n=3,d=7 时 f<0", "n=5,d=11 时 f<0"],
            "numeric_evidence": {
                "script": "code/p1.py", "range": "d<=33", "n_cases": 256, "n_counterexamples": 3,
            },
            "scope_caveat": "两条来自文献，第三条是本次运行扫到的",
        }
    ],
    "open_problems": [],
    "status": "draft",
    "review_rounds": 0,
    "created_at": "2026-09-27T12:00:00+08:00",
    "updated_at": "2026-09-27T12:00:00+08:00",
    "created_by": "agent-G",
}


def _fixture_text() -> str:
    return json.dumps(GOOD_DOC, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _inject(tmp_path: Path, anchor: str, replacement: str, tag: str) -> tuple[dict, str, str]:
    """把一处违规注入正控夹具的文本副本 ⇒ `(副本的行, 正控 sha256, 副本 sha256)`。"""
    original = _fixture_text()
    hits = original.count(anchor)
    assert hits == 1, f"注入锚点必须恰好命中 1 次，实际 {hits} 次：{anchor!r}"
    mutated = original.replace(anchor, replacement)
    assert mutated != original, "注入没有改变字节 ⇒ 这条负控什么都没测"
    copy = tmp_path / f"copy-{tag}.json"
    copy.write_text(mutated, encoding="utf-8")
    src_sha, dst_sha = _sha(original), _sha(mutated)
    print(f"[负控 {tag}] 注入 {anchor!r} -> {replacement!r}；锚点命中 {hits} 次")
    print(f"[负控 {tag}] 正控副本 sha256={src_sha}")
    print(f"[负控 {tag}] 注入副本 {copy.name} sha256={dst_sha}")
    return json.loads(mutated), src_sha, dst_sha


def _expect_validate_rejects(row: dict, tag: str) -> str:
    try:
        S.Document(**row).validate()
    except ValueError as exc:
        print(f"[负控 {tag}] 写入期原始输出：ValueError: {exc}")
        return str(exc)
    raise AssertionError(f"负控 {tag} 没有被写入期判据拒绝 —— 注入没生效")


def _g12(claim: dict) -> G.GateResult:
    """跑 G12（只用一条断言：判据只读 `status` 与两个反例来源）。"""
    ctx = G.GateContext.build(_doc([claim]))
    r = G.gate_g12(ctx)
    print(f"[G12] verdict={r.verdict} counts={r.counts} reason={r.reason}")
    for f in r.findings:
        print(f"[G12] finding: severity={f['severity']} message={f['message']} evidence={f['evidence']}")
    return r


# ============================================================ 正控


def test_p10_positive_control_the_current_fixture_passes(tmp_path: Path):
    """正控：当前字节上两个来源不等但自证了差异 ⇒ 写入期判据通过。"""
    text = _fixture_text()
    copy = tmp_path / "copy-positive.json"
    copy.write_text(text, encoding="utf-8")
    print(f"[正控] 当前字节副本 {copy.name} sha256={_sha(text)}")
    row = json.loads(text)
    S.Document(**row).validate()  # 不抛 = 通过
    claim = row["claims"][0]
    assert len(claim["counterexamples"]) != claim["numeric_evidence"]["n_counterexamples"]
    assert claim["scope_caveat"].strip(), "夹具前提：差异确实自证了"


def test_p10_positive_control_both_empty_is_fine():
    """正控：两边都空（清单空、机器扫到 0 条）⇒ 不需要 `scope_caveat`。"""
    row = json.loads(_fixture_text())
    row["claims"][0]["counterexamples"] = []
    row["claims"][0]["numeric_evidence"]["n_counterexamples"] = 0
    S.Document(**row).validate()


def test_p10_positive_control_machine_found_three_and_the_human_knows_none():
    """正控（`P-10` 点名的真实情形）：清单空、机器扫到 3 条 ⇒ 通过。

    这一格是本候选与候选 B 的分水岭：B 会把它判成 `error`，于是写数据的人
    只有两条路 —— 手工转抄机器产出，或把 `n_counterexamples` 改成 0。
    A 只要求 `scope_caveat` 把差异说清，所以它在这里必须通过。
    """
    row = json.loads(_fixture_text())
    row["claims"][0]["counterexamples"] = []
    row["claims"][0]["numeric_evidence"]["n_counterexamples"] = 3
    row["claims"][0]["scope_caveat"] = "机器扫到 3 条候选反例，尚未逐条人工确认"
    S.Document(**row).validate()


def test_p10_positive_control_absent_keys_are_not_a_violation():
    """正控：`counterexamples` 整键缺失而只有机器计数 ⇒ 通过（G12 认它为痕）。"""
    row = json.loads(_fixture_text())
    row["claims"][0].pop("counterexamples")
    S.Document(**row).validate()
    _g12(_claim(**row["claims"][0]))


# ============================================================ 负控：写入期判据


def test_p10_negative_control_differing_sources_without_a_caveat(tmp_path: Path):
    """负控 1：两源不等而 `scope_caveat` 是空的 ⇒ 写入期拒收（消息点名 scope_caveat）。"""
    row, _src, _dst = _inject(
        tmp_path,
        '"scope_caveat": "两条来自文献，第三条是本次运行扫到的"',
        '"scope_caveat": ""',
        "no-caveat",
    )
    msg = _expect_validate_rejects(row, "no-caveat")
    assert "scope_caveat" in msg, msg
    assert "counterexamples 有 2 条" in msg, msg


def test_p10_negative_control_the_judgement_is_not_a_second_implementation(tmp_path: Path):
    """负控 2（FC-03）：`claimanatomy.validate_claim` 不重写这条判据。

    判据落在 `schema.Document.validate()` 的写入期路径上（`P-10` 候选 A 的落点）。
    这里断言"另一条字段级判据通路不给同一条问题第二个结论"：
    `validate_claim` 在两源不等、缺 `scope_caveat` 时仍然不报 counterexample 类问题。
    若有人日后把它也补进 `claimanatomy`，这一条会红，提醒他这是第二处落地。
    """
    row, _src, _dst = _inject(
        tmp_path,
        '"scope_caveat": "两条来自文献，第三条是本次运行扫到的"',
        '"scope_caveat": ""',
        "single-source",
    )
    claim = row["claims"][0]
    spec = CA.validate_claim(claim)
    codes = [getattr(i, "code", "") for i in spec.issues]
    print(f"[负控 single-source] validate_claim issues={codes}")
    assert not [c for c in codes if "counterexample" in c], codes


def test_p10_negative_control_the_write_path_is_loud(store: Store):
    """负控 3：走存储层提交同样的行 ⇒ 在提交那一刻抛（不是静默落盘）。

    `store.tx` 的提交块对每张脏表跑 `schema.validate_table`，所以"两源不等又缺
    `scope_caveat`"的稿件进不了库。这条与 P-9 那两条 rebuild 用例同源：
    写入期响、重建期静默，是两件必须分开说的事。
    """
    row = json.loads(_fixture_text())
    row["claims"][0]["scope_caveat"] = ""
    with pytest.raises(ValueError, match="scope_caveat"):
        with store.tx("documents", actor="test") as tx:
            tx.upsert("documents", row, note="两源不等且缺 scope_caveat")
    assert store.rows("documents") == [], store.rows("documents")


# ============================================================ 反向负控：不许加门


def test_p10_reverse_control_g12_does_not_judge_the_difference(tmp_path: Path):
    """反向负控（`P-10` 的硬约束）：机器扫到 3 条而清单是空的，G12 的判决必须仍是 `pass`。

    这一格正是 `P-10` 点名的矛盾形态（`counterexamples=[]` 而
    `n_counterexamples=3`）。逐字钉住"在裁定之前，不许为它加门" ——
    而裁定（候选 A）的结论同样是"不加门"：谁更权威是人/文献的判断，不是门的判断。
    若有人把候选 B 的一致性门偷偷实现进 G12，这一条会红。

    注入作用在断言文本的副本上（锚点是 `n_counterexamples` 这一个数），
    于是"绿变红"只可能由这一处改动引起 —— 而这里要求的是"它不许变"。
    """
    original = json.dumps(_claim(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    anchor = '"n_counterexamples": 0'
    hits = original.count(anchor)
    assert hits == 1, f"注入锚点必须恰好命中 1 次，实际 {hits} 次：{anchor!r}"
    mutated = original.replace(anchor, '"n_counterexamples": 3')
    assert mutated != original, "注入没有改变字节 ⇒ 这条负控什么都没测"
    copy = tmp_path / "copy-no-gate-claim.json"
    copy.write_text(mutated, encoding="utf-8")
    print(f"[反向负控 no-gate] 注入 {anchor!r} -> '\"n_counterexamples\": 3'；锚点命中 {hits} 次")
    print(f"[反向负控 no-gate] 注入前 sha256={_sha(original)}")
    print(f"[反向负控 no-gate] 注入后 {copy.name} sha256={_sha(mutated)}")
    before, after = json.loads(original), json.loads(mutated)
    assert before["counterexamples"] == [] and after["counterexamples"] == [], "夹具前提：清单是空的"
    # 正控：注入前 G12 就该 pass（否则"不变红"这件事没有意义）。
    assert _g12(before).verdict == "pass", "夹具前提不成立：注入前 G12 就不是 pass"
    # 负控：注入后必须仍然 pass —— 门不许替项目选口径。
    r = _g12(after)
    assert r.verdict == "pass", (r.verdict, r.reason, r.findings)
    assert r.counts["有反例搜索痕迹"] == 1, r.counts
    assert not [f for f in r.findings if f["severity"] == "error"], r.findings
    # 写入期判据对这一格也不拦：清单是空的 ⇒ 两源差异不需要 scope_caveat。
    row = json.loads(_fixture_text())
    row["claims"][0]["counterexamples"] = []
    row["claims"][0]["numeric_evidence"]["n_counterexamples"] = 3
    row["claims"][0]["scope_caveat"] = ""
    S.Document(**row).validate()


def test_p10_reverse_control_g12_still_bites_a_claim_with_real_counterexamples():
    """反向负控的对照（G12 的牙还在）：清单非空而标 `证` ⇒ 仍然 `error` 阻断。"""
    claim = _claim()  # `counterexamples=[]`、`status="证"`
    claim["counterexamples"] = ["n=3,d=7 时 f<0"]
    r = _g12(claim)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert any("自相矛盾" in f["message"] for f in r.findings), r.findings
