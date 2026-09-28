"""`gate_g1` 的存在性判据（criterion 第二句）与它自述读数的断言点。

## 这个文件补的是哪两个洞

`R2b-gates-2`：`D-7` 补上的"每个被引材料必须在工作区内存在"在 tests/ 里
一个断言点都没有 —— `grep -rn '工作区内不存在|未展开的通配符|存在性无法判定' tests/*.py`
0 命中，把 `gate_g1` 里 `if not exists: …` 那一段删掉，整套测试仍然全绿。
本文件的每一条都点名那个分支，删掉它必然有红。

`R2b-gates-1`：门的 `reason` 与 `counts` 不自洽 ——
一条"工作区内不存在"的发现被自述成"有 0 条引用指向工作区外的路径"，
而"未展开的通配符"与"存在性无法判定"两条旁路在 `reason` 里一个字都不出现
（后者还会被 `findings` 分支永久吃掉）。本文件把三档读数各自钉一条。

## 断言点为什么都打在"读数"上

`R2R2-R2` 登记过"门在自述读数上撒谎"这一族：旁路被正确计进 `counts`、
却不在 `reason` 里出现，等于门对外说的是另一件事。所以这里的断言同时看：
`verdict` 的四态、`counts` 里那一档的数、以及 `reason` 里有没有那个数。
"""

from __future__ import annotations

import unittest.mock as mock
from pathlib import Path

import pytest

from agentflow import gates as G


# ============================================================ 夹具

_TS = "2026-01-01T00:00:00+00:00"


def _doc(proof_location: str) -> dict:
    """一条最小稿件：只有 `claims[0].proof_location` 会进 G1 的候选集合。

    刻意不放 `dependencies`：`_iter_doc_files` 对依赖标签用的正则抽不出
    `materials/*.pdf` 这种形态（`*` 不在它的字符类里），而"通配符引用"
    这一档要测的正是候选筛选之后那一步，所以线索从 `proof_location` 给。
    """
    return {
        "doc_id": "0001",
        "kind": "paper",
        "title": "G1 材料存在性夹具",
        "status": "draft",
        "created_at": _TS,
        "updated_at": _TS,
        "claims": [
            {
                "claim_id": "claim-1",
                "statement": "命题。",
                "citations": [],
                "evidence_kind": "heuristic",
                "proof_location": proof_location,
            }
        ],
    }


def _doc_locs(*locs: str) -> dict:
    """每条 `proof_location` 一条 claim 的稿件（N 个候选同时进 G1 的候选集合）。"""
    doc = _doc(locs[0])
    claims = [doc["claims"][0]]
    for i, loc in enumerate(locs[1:], start=2):
        extra = dict(claims[0])
        extra["claim_id"] = f"claim-{i}"
        extra["proof_location"] = loc
        claims.append(extra)
    doc["claims"] = claims
    return doc


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """带一个真实材料的最小工作区（`real.lean` 是盘上真的有的那一个）。"""
    root = tmp_path / "ws"
    root.mkdir(parents=True)
    (root / "real.lean").write_text("theorem t : True := trivial\n", encoding="utf-8")
    return root


def _run(ws: Path, proof_location: str) -> G.GateResult:
    return G.gate_g1(G.GateContext.build(_doc(proof_location), workspace_root=ws))


# ============================================================ 存在性判据本身


def test_gate_g1_fails_and_says_the_material_is_missing(ws: Path):
    """正控（`R2b-gates-2` ①）：工作区内、盘上不存在的材料 ⇒ fail，且读数如实。

    "在工作区内"与"在盘上存在"是两件事（`_resolve_against_root` 的 docstring
    逐字写了这一条）：这条路径 resolve 之后落在工作区里，所以旧实现只做
    `relative_to` 时它是 `pass`。这条断言就是 criterion 第二句的唯一牙齿。
    """
    r = _run(ws, "ghost.lean:1")
    assert r.verdict == "fail", (r.verdict, r.reason, dict(r.counts))
    assert r.counts["工作区内"] == 1, r.counts
    assert r.counts["工作区内不存在"] == 1, r.counts
    assert r.counts["工作区外"] == 0, r.counts
    assert len(r.findings) == 1, (r.findings, r.reason)
    assert "不存在" in r.findings[0]["message"], r.findings[0]
    # 自述读数：这一条发现不是"区外引用"来的，`reason` 不许那么说
    # （`R2b-gates-1` 的正控）。
    assert "0 条引用指向工作区外" not in r.reason, r.reason
    assert "1 条指向工作区内" in r.reason, r.reason


def test_gate_g1_does_not_call_an_unexpanded_glob_existing(ws: Path):
    """正控（`R2b-gates-2` ②）：通配符候选不被算作"不存在"，也不被说成"都存在"。

    `Path("materials/*.pdf").exists()` 恒为假，所以通配符必须在判存在性之前
    被摘出去单独计数；而一旦摘出去了，`reason` 就不能再说"N 条路径全部
    在工作区内且都存在" —— 那句话说了一条本条不判的事（`R2b-gates-1`）。
    """
    r = _run(ws, "materials/*.pdf:3")
    assert r.counts["未展开的通配符"] == 1, r.counts
    assert r.counts["工作区内不存在"] == 0, r.counts
    assert r.counts["存在性无法判定"] == 0, r.counts
    assert not r.findings, (r.findings, r.reason)
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert "都存在" not in r.reason, r.reason
    assert "未展开的通配符" in r.reason, r.reason


def test_gate_g1_pass_reason_still_says_everything_exists(ws: Path):
    """负控（守新句子不是恒假）：同一夹具把通配符换成真实文件 ⇒ `reason` 说"都存在"。

    没有这一条，"通配符支不许说都存在"可以用一个恒不说那句话的 reason
    糊过去 —— 那样合规输入的自述读数就退化了，而上面两条照样全绿。
    """
    r = _run(ws, "real.lean:1")
    assert r.verdict == "pass", (r.verdict, r.reason, dict(r.counts))
    assert r.counts["未展开的通配符"] == 0, r.counts
    assert r.counts["工作区内不存在"] == 0, r.counts
    assert "全部在工作区内且都存在" in r.reason, r.reason


# ============================================================ 第三档：没查成


def test_gate_g1_reports_an_undecidable_existence_as_unknown(ws: Path):
    """负控（`R2b-gates-2` 的验收）：`exists()` 抛 `OSError` ⇒ `unknown`，不是 pass。

    注入点在 `Path.exists` 上（只对 `boom.lean` 抛），不是往被测函数里塞桩：
    判据读的是"这条路径问不出存在性"，而"问不出"必须落在第三态上。
    """
    real_exists = Path.exists

    def _boom(self: Path, *a: object, **kw: object) -> bool:
        if str(self).endswith("boom.lean"):
            raise OSError("存在性问不出来")
        return real_exists(self, *a, **kw)

    with mock.patch.object(Path, "exists", _boom):
        r = _run(ws, "boom.lean:1")
    assert r.verdict == "unknown", (r.verdict, r.reason, dict(r.counts))
    assert r.counts["存在性无法判定"] == 1, r.counts
    assert r.counts["工作区内不存在"] == 0, r.counts
    assert "存在性问不出来" in r.reason, r.reason
    # 档名与自己的数都要在（`R2b7-gates-1` 的另一半：这一支原来用的是另一个
    # 说法"存在性问不出来"，而 fail 支用的是"存在性没查成" —— 同一个计数键
    # 两支两个说法，读者要拿两句话去对同一个数）。号数也要出现。
    assert "存在性没查成" in r.reason, r.reason
    assert f"{r.counts['存在性无法判定']} 条" in r.reason, r.reason


def test_gate_g1_mentions_a_glob_alongside_an_undecidable_existence(ws: Path):
    """正控（`R2b7-gates-1` 的验收）：`unknown` 支里 `globbed` 也必须逐档自述。

    P12/P18 形态：通配符与"存在性没查成"同时非零、`findings` 为空 ⇒ verdict
    是 `unknown`（比 `pass` 严），`counts` 里两档各有数，但 `reason` 原来只报
    后一档 —— 读者（报告/CI 摘要/下一个人）会以为这一轮只碰到一档。
    方向不是假通过，所以这里断言的是"报告不实"这一半，不动 verdict。

    同一条用例带反向：把通配符换成真实不存在的材料（`globbed == 0`）⇒
    `reason` 不许出现通配符那半句（防"恒加一句"）。
    """
    real_exists = Path.exists

    def _boom(self: Path, *a: object, **kw: object) -> bool:
        if str(self).endswith("boom.lean"):
            raise OSError("存在性问不出来")
        return real_exists(self, *a, **kw)

    with mock.patch.object(Path, "exists", _boom):
        one = G.gate_g1(
            G.GateContext.build(_doc_locs("materials/*.pdf:3", "boom.lean:1"), workspace_root=ws)
        )
        two = G.gate_g1(
            G.GateContext.build(
                _doc_locs("materials/*.pdf:3", "a/*.pdf:1", "boom.lean:1"), workspace_root=ws
            )
        )
        no_glob = G.gate_g1(
            G.GateContext.build(_doc_locs("ghost.lean:1", "boom.lean:1"), workspace_root=ws)
        )
    assert one.verdict == "unknown", (one.verdict, one.reason, dict(one.counts))
    assert one.counts["未展开的通配符"] == 1 and one.counts["存在性无法判定"] == 1, one.counts
    assert "未展开的通配符" in one.reason, one.reason
    assert "1 条是未展开的通配符" in one.reason, one.reason
    assert two.verdict == "unknown", (two.verdict, two.reason, dict(two.counts))
    assert two.counts["未展开的通配符"] == 2, two.counts
    assert "2 条是未展开的通配符" in two.reason, two.reason
    # 反向：`globbed == 0` 时那半句不许出现（否则就是恒加一句，不是"非零才出现"）
    assert no_glob.counts["未展开的通配符"] == 0, no_glob.counts
    assert "未展开的通配符" not in no_glob.reason, no_glob.reason


def test_gate_g1_counts_an_undecidable_existence_even_alongside_a_real_finding(ws: Path):
    """正控（`R2b-gates-1` 的另一半）：第三档与真发现同时出现时不许被吃掉。

    旧实现里 `findings` 非空即 `fail` 且 `reason` 只写区外/不存在，
    于是 `existence_undecidable > 0` 这一档在报告里永久不可见
    —— "没查成"被折进了"查过了、有问题"那一边。这里的断言是：
    verdict 取更严的那一档（`fail`），但 `reason` 必须把这一档的条数写出来。
    """
    real_exists = Path.exists

    def _boom(self: Path, *a: object, **kw: object) -> bool:
        if str(self).endswith("boom.lean"):
            raise OSError("存在性问不出来")
        return real_exists(self, *a, **kw)

    with mock.patch.object(Path, "exists", _boom):
        r = _run(ws, "ghost.lean:1")
        r_mixed = G.gate_g1(
            G.GateContext.build(_doc_locs("ghost.lean:1", "boom.lean:1"), workspace_root=ws)
        )
    assert r.verdict == "fail", (r.verdict, r.reason)  # 单条 missing 仍是 fail
    assert r_mixed.verdict == "fail", (r_mixed.verdict, r_mixed.reason, dict(r_mixed.counts))
    assert r_mixed.counts["工作区内不存在"] == 1, r_mixed.counts
    assert r_mixed.counts["存在性无法判定"] == 1, r_mixed.counts
    assert "不存在" in r_mixed.reason, r_mixed.reason
    assert "存在性没查成" in r_mixed.reason, r_mixed.reason


def test_gate_g1_counts_a_glob_alongside_a_missing_material(ws: Path):
    """正控：通配符那一档在 fail 分支里也要自己出现在 `reason` 里。

    旧实现只在 `pass` 分支之外完全不提 `globbed`，所以"一条真不存在的材料"
    会把"另有一条通配符没判过"这句话整个盖掉。
    """
    r = G.gate_g1(
        G.GateContext.build(_doc_locs("ghost.lean:1", "materials/*.pdf:3"), workspace_root=ws)
    )
    assert r.verdict == "fail", (r.verdict, r.reason, dict(r.counts))
    assert r.counts["工作区内不存在"] == 1, r.counts
    assert r.counts["未展开的通配符"] == 1, r.counts
    assert "未展开的通配符" in r.reason, r.reason


# ============================================================ 守本文件自己


def test_the_probe_is_not_vacuous(ws: Path):
    """自校：同一判据对"真存在"与"不存在"给出不同 verdict（防本文件恒绿）。

    没有这一条，一个"永远 fail"或"永远 pass"的实现也能让上面的断言全绿。
    """
    assert _run(ws, "real.lean:1").verdict == "pass"
    assert _run(ws, "ghost.lean:1").verdict == "fail"
