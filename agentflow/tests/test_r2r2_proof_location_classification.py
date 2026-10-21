"""`R2R2-R1` / `R2R2-R2` 的回归判据：`proof_location` 的形态分类只有一份实现。

## 为什么要有这个文件（重审实测的教训）

写入期（`tools/doc_tools.check_proofs`）与事后门（`gates.gate_g3`）过去各写一套正则，
彼此没有交叉断言。重审用同一份数据跑了 18 档，其中 9 档两处给出不同分类。
最难堪的一档：断言自己连 `claim_id` 都没有，`proof_location="claim-1:3"` ——
写入期报"指向一条不存在的断言"，事后门却判成 `file:line` 并 pass。

修法是抽一份 :func:`agentflow.tools.doc_tools.classify_proof_location`，两处共用。
本文件钉住三件事：

1. 两处对同一批输入给出同一个 `(kind, base)`（交叉断言）；
2. 分类函数的每一档都各有一条正控（否则"永远返回同一档"也能让交叉断言通过）；
3. `gate_g3` 的自述计数与实际一致（`R2R2-R2`：旧版把交叉引用算进 `file:line`）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentflow import gates as G
from agentflow.tools import doc_tools as DT


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """带 `code/p1.py` 与 `documents/0000.md` 的最小工作区。

    与 `tests/test_coverage_gates.py::ws` 同形（那边是模块级 fixture，本文件用不到）。
    """
    root = tmp_path / "ws"
    (root / "code").mkdir(parents=True)
    (root / "documents").mkdir(parents=True)
    (root / "code" / "p1.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "documents" / "0000.md").write_text("# 稿件\n", encoding="utf-8")
    return root

#: 本文档"已知"的 claim_id 集合（两处必须用同一份）。
KNOWN = {"claim-1", "claim-9b85fc39"}

#: `(proof_location, 期望分类)`。每一档都写清"为什么是这一档"。
CASES: list[tuple[str, str]] = [
    ("claim-1", "self_ref"),
    ("claim-1:12", "self_ref"),
    ("claim-9b85fc39:1-3", "self_ref"),
    ("not-a-claim:7", "cross_ref"),
    ("claim-2:12", "cross_ref"),
    ("proofs/real.lean", "file"),
    ("proofs/real.lean:3", "file"),
    ("../outside.lean", "file"),
    ("C:/ws/proofs/real.lean:3", "file"),
    #: 既没有扩展名、也没有路径分隔符 ⇒ 不是文件描述，而是"一个不存在的引用"。
    #: 这一档在旧版两处都判 fail（写入期 `proof_location_not_found`、
    #: 事后门"两者都不是"）。抽公共分类函数时如果不收窄，就会把事后门放宽。
    ("见上文所述", "cross_ref"),
]


@pytest.mark.parametrize(("loc", "want"), CASES)
def test_the_classifier_gives_the_declared_kind(loc: str, want: str) -> None:
    """正控（每一档一条）：分类函数必须真的能把这几档分开。

    没有这一条，"所有输入都返回 `file`"也能让下面的交叉断言通过 ——
    那正是"判据真空"（断言恒真）。
    """
    kind, _base = DT.classify_proof_location(loc, KNOWN)
    assert kind == want, (loc, kind, want)


def test_the_two_call_sites_agree_on_every_case(ws: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """交叉断言（`R2R2-R1` 的判据）：写入期与事后门对同一输入必须同分类。

    要判的不是"两处结论相同"（处置本来就不同），而是分类相同。

    `R6-AN-2`（本轮修）：旧版这里写的是`assert DT.classify_proof_location(loc, KNOWN) == DT.classify_proof_location(loc, KNOWN)`—
    — 同一次调用的同参数写了两遍，对任何纯函数、任何输入都恒真；用例名与上一版docstring 却声称守的是"两个调用点"，实际只有上面那条模块同一性断言在干活。现在改成真的把第二个调用点跑起来：
    把共享分类函数换成一个记账的替身，真跑一次 `gate_g3`，再看它是不是逐个走了这份函数、且用的已知集合就是该文档的`claim_id` 集合。事后门若改回内联正则（历史上就是这么错的），替身一条也记不到，
    下面那句"事后门只对 N 个输入调了共享分类函数"立刻红。
    """
    from agentflow.gates import doc_tools as gates_doc_tools
    from tests.test_coverage_gates import _ctx, _doc  # noqa: PLC0415

    assert gates_doc_tools is DT, (
        "`gates` 必须 import 写入期那一份 doc_tools（同一模块对象），"
        f"实际拿到 {gates_doc_tools!r}"
    )
    # 事后门的已知集合取自文档自身，所以要把 `KNOWN` 里的两个 id 都放进这份文档 ——
    # 两个调用点才是在"同一批输入 + 同一个已知集合"上比较。
    claims = [_claim(loc) for loc, _want in CASES]
    claims.append(_claim("proofs/real.lean", claim_id="claim-9b85fc39"))
    assert {c["claim_id"] for c in claims} == KNOWN

    seen: list[tuple[str, tuple[str, str]]] = []
    real = DT.classify_proof_location

    def spy(loc: str, known: set[str]) -> tuple[str, str]:
        out = real(loc, known)
        seen.append((loc, out))
        return out

    monkeypatch.setattr(DT, "classify_proof_location", spy)
    ctx = _ctx(ws)
    ctx.doc = _doc(claims)
    G.gate_g3(ctx)

    gate_side = dict(seen)
    missed = [loc for loc, _want in CASES if loc not in gate_side]
    assert not missed, (
        f"事后门没对这几个输入调用共享分类函数：{missed} —— 它要么没走 `doc_tools."
        "classify_proof_location`（改回内联正则就等于两个调用点各写一套），要么漏了输入"
    )
    for loc, _want in CASES:
        write_side = real(loc, KNOWN)
        assert gate_side[loc] == write_side, (
            f"写入期与事后门对 {loc!r} 的分类不同：写入期 {write_side}、事后门 {gate_side[loc]}。"
            "两个调用点要么共用一份实现、要么共用一份已知集合 —— 这里两样都不许分家"
        )
    # 事后门那一支必须真的 import 这个模块（不是自己再写一套正则）
    src = (DT.__file__ or "")
    assert src.endswith("doc_tools.py")


def _claim(proof_location: str, claim_id: str = "claim-1") -> dict[str, Any]:
    return {"claim_id": claim_id, "text": "命题。", "evidence_kind": "proof",
            "citations": ["exp:0000"], "proof_location": proof_location}


def test_gate_g3_counts_a_cross_reference_as_neither_id_nor_path(ws: Any) -> None:
    """`R2R2-R2`：交叉引用形态（id 不存在）必须记进"两者都不是"，不许记成 `file:line`。

    旧版把 `claim-1:12` 之类算成 `指向 file:line` —— 门在自述读数上撒谎，
    而"读数是假的"正是本项目最忌的形态（报告里的数字会被人当事实）。
    """
    from tests.test_coverage_gates import _ctx, _doc  # noqa: PLC0415

    ctx = _ctx(ws)
    ctx.doc = _doc([_claim("claim-2:12")])
    r = G.gate_g3(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["两者都不是"] == 1, r.counts
    assert r.counts["指向 file:line 形态"] == 0, r.counts


def test_gate_g3_counts_a_bare_claim_id_separately(ws: Any) -> None:
    """正控：裸写 `claim_id` 与"带行号的 `claim_id`"分开计数，且都算自指。"""
    from tests.test_coverage_gates import _ctx, _doc  # noqa: PLC0415

    ctx = _ctx(ws)
    ctx.doc = _doc([_claim("claim-1"), _claim("claim-1:9", claim_id="claim-2")])
    r = G.gate_g3(ctx)
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["指向本文档内 claim_id"] == 2, r.counts
    assert r.counts["其中裸写 claim_id"] == 1, r.counts
    assert r.counts["指向 file:line 形态"] == 0, r.counts


def test_gate_g3_still_rejects_a_claim_id_that_does_not_exist(ws: Any) -> None:
    """负控（不许放宽）：`not-a-claim:7` 形态 ⇒ 事后门必须 error（fail-closed）。

    事后门分不清"忘了登记"与"根本不存在"，所以它在这一档必须与写入期同结论。
    这一条在"抽公共分类函数"的改法里最容易掉：只要有人把 `cross_ref` 归进 `file`，
    它就会变成 pass。
    """
    from tests.test_coverage_gates import _ctx, _doc  # noqa: PLC0415

    ctx = _ctx(ws)
    ctx.doc = _doc([_claim("not-a-claim:7")])
    r = G.gate_g3(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["两者都不是"] == 1, r.counts
