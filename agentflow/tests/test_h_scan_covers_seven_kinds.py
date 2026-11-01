# -*- coding: utf-8 -*-
"""块 2 的判据：七类每一类都要能经 `review.scan` 真的跑出来（不是只有 text_integrity）。

## 为什么单立一份

块 1 只接了 `text_integrity`（业主的分块要求：先只开既有那条路），其余六类在工具层
如实报"还没接线"。块 2 把 `_WIRED_KINDS` 扩到七类 —— 而"扩了"这件事必须有读数：
只改一个元组、不加判据，下一个人把元组改窄时没有任何东西会红。

所以这一份是每类一组正控：在同一个夹具工作区上，七类各自跑一次，断言
① `detail[kind].checked` 为真（查成了）；② `counts.by_kind[kind]` 是这一类自己的数；
③ 该报的那条真的报了（cites 缺一条、refs 悬空一条、inputs 指不到、proofs 缺证明、
duplicates 重名、ledger_match 多出环境、text_integrity 零宽）。
外加一条反真空：七类的 `checked` 必须不是全靠"没查成"混过去。

夹具刻意造成"每类都有恰好一条该报的"：这样的读数最好认 —— 少了哪一类，红的就是
那一条 parametrize。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import texaudit as TEX
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import review_tools as RV

#: 夹具正文。每一类各留一处该报的：
#: `\cite{ghost}`（参考文献里没有）、`\ref{nope}`（标签不存在）、`\input{chapters/nope}`
#: （文件不在盘上）、`lemma` 不带 proof、`\label{thm:a}` 重复一次、行内一个零宽空格。
TEX_BODY = (
    "\\documentclass{article}\n"
    "\\newtheorem{theorem}{Theorem}\n"
    "\\begin{document}\n"
    "\\section{Main}\\label{sec:main}\n"
    "\\begin{theorem}\\label{thm:a}\n"
    "A statement cited as \\cite{knuth84,ghost}, see \\ref{sec:main} and \\ref{nope}.\n"
    "A zero\u200bwidth space hides in this line.\n"
    "\\end{theorem}\n"
    "\\begin{proof}\n"
    "Proof of A.\n"
    "\\end{proof}\n"
    "\\input{chapters/nope}\n"
    "\\begin{lemma}\\label{thm:a}\n"
    "Unproved lemma with a duplicate label.\n"
    "\\end{lemma}\n"
    "\\begin{thebibliography}{9}\n"
    "\\bibitem{knuth84} Knuth.\n"
    "\\end{thebibliography}\n"
    "\\end{document}\n"
)


def _workspace(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """造一个"每类都有恰好一条该报的"工作区（论文包 + 台账一格）。"""
    ws = tmp_path / "ws"
    project = ws / "projects" / "p1"
    paper = project / "out" / "paper"
    paper.mkdir(parents=True)
    (paper / "main.tex").write_text(TEX_BODY, encoding="utf-8", newline="")
    data = ws / "data"
    data.mkdir(parents=True)
    (data / "statements.json").write_text(json.dumps({"rows": [{
        "stmt_id": "000001", "kind": "theorem", "label": "thm:a",
        "statement_full": "A statement.", "statement_text": "A statement.",
    }]}), encoding="utf-8")
    return ws, project


def _registry(ws: pathlib.Path):
    store = Store(ws)
    store.init()
    return build_registry(store=store, workspace_root=ws).registry


def _scan(ws: pathlib.Path, project: pathlib.Path, kind: str) -> dict:
    reg = _registry(ws)
    res = reg.call("review.scan", role="H", kinds=[kind],
                   paths=["projects/p1/out/paper"], project="projects/p1")
    assert res.ok, res.error
    return res.data


def test_all_seven_kinds_are_wired() -> None:
    """块 2 的核心事实：接线面 == 契约面（`_WIRED_KINDS` 与 `SCAN_KINDS` 逐字相等）。"""
    assert tuple(RV._WIRED_KINDS) == tuple(TEX.SCAN_KINDS), (  # noqa: SLF001
        sorted(set(TEX.SCAN_KINDS) ^ set(RV._WIRED_KINDS)))


@pytest.mark.parametrize("kind", TEX.SCAN_KINDS)
def test_each_kind_really_runs(tmp_path: pathlib.Path, kind: str) -> None:
    """每类一组正控：查成了、`by_kind` 是这一类自己的数、该报的那条报了。

    `ledger_match` 那一类例外：它的"该报的那条"（正文多出来的定理类环境）要求对应表
    在盘上（`papermapping` 只在有表时才判孤儿），而本夹具刻意不造表 —— 所以它这一格
    断言的是"五个数读得出来"，另有一条单独的判据钉它的形状。
    """
    ws, project = _workspace(tmp_path)
    data = _scan(ws, project, kind)
    detail = next(d for d in data["detail"] if d["kind"] == kind)
    assert detail["checked"] is True, (kind, detail)
    assert not [b for b in data["bad"] if b["kind"] == kind], (kind, data["bad"])
    findings = [f for f in data["findings"] if f["kind"] == kind]
    facts = data["counts"]["facts"]
    if kind == "ledger_match":
        for key in ("proof_envs", "statement_envs", "ledger_propositions",
                    "ledger_theorem_kinds", "mapping_rows"):
            assert key in facts, (key, sorted(facts))
        assert facts["ledger_theorem_kinds"] == 1, facts
    else:
        assert findings, (kind, data["counts"])
        assert data["counts"]["by_kind"][kind] >= 1, (kind, data["counts"])


def test_the_seven_kinds_do_not_all_fall_back_to_unchecked(tmp_path: pathlib.Path) -> None:
    """反真空：七类全部 `checked=True`（"每类都跑不成"也能让上面那条通过）。"""
    ws, project = _workspace(tmp_path)
    reg = _registry(ws)
    res = reg.call("review.scan", role="H", kinds=list(TEX.SCAN_KINDS),
                   paths=["projects/p1/out/paper"], project="projects/p1")
    assert res.ok, res.error
    checked = [d["kind"] for d in res.data["detail"] if d["checked"]]
    assert len(checked) == len(TEX.SCAN_KINDS), res.data["bad"]


def test_the_fixture_reports_exactly_one_finding_per_kind(tmp_path: pathlib.Path) -> None:
    """夹具的"每类恰好一条"是真读数（不是靠 where 模糊匹配凑出来的）。

    这一条同时是"七类不会互相串台"的读数：每一类的条数就是它自己的那一条。
    """
    ws, project = _workspace(tmp_path)
    reg = _registry(ws)
    res = reg.call("review.scan", role="H", kinds=list(TEX.SCAN_KINDS),
                   paths=["projects/p1/out/paper"], project="projects/p1")
    assert res.ok, res.error
    by_kind = res.data["counts"]["by_kind"]
    for kind in TEX.SCAN_KINDS:
        if kind == "ledger_match":
            continue
        assert by_kind[kind] == 1, (kind, by_kind)


def test_ledger_match_returns_the_five_numbers_and_the_surplus(tmp_path: pathlib.Path) -> None:
    """`ledger_match` 那一类的形状：五个数 + `statement_surplus`（不判 `==`）。"""
    ws, project = _workspace(tmp_path)
    data = _scan(ws, project, "ledger_match")
    facts = data["counts"]["facts"]
    assert facts["statement_envs"] == 2, facts
    assert facts["ledger_propositions"] == 1, facts
    assert isinstance(facts["statement_surplus"], list), facts
    assert "==" not in json.dumps(facts, ensure_ascii=False), (
        "这一档只回数：facts 里不许出现任何『相等/不等』的结论")


def test_a_narrowed_wiring_is_honest_not_silent(tmp_path: pathlib.Path) -> None:
    """把接线面收窄（模拟块 1 那一档）⇒ 未接的类如实进 `bad[]`，不是悄悄跳过。

    这一条是"契约 vs 接线"那一步的反面：块 2 之后 `_WIRED_KINDS` 是全量，但机制本身
    必须还在 —— 它由 `texaudit.scan_tex(wired=...)` 承载，工具只是把常量传下去。
    """
    ws, project = _workspace(tmp_path)
    got = TEX.scan_tex(ws / "projects" / "p1", kinds=["cites", "refs"],
                       files=[project / "out" / "paper" / "main.tex"],
                       wired=["cites"])
    assert got["checked"] is False
    assert "refs" in {b["kind"] for b in got["bad"]}, got["bad"]
    assert "还没接线" in next(b["reason"] for b in got["bad"] if b["kind"] == "refs")
    # 这一份夹具还有一处 `\input{chapters/nope}`：它让"正文没读全"成为一条 `corpus`
    # 读数（全局 `checked` 因此为假），而那与"接线"是两件事 —— 两条同时在 `bad[]` 里
    # 正是要的：一条说"这一类没接"、一条说"这一段正文没读到"。
    assert "corpus" in {b["kind"] for b in got["bad"]}, got["bad"]
