"""`gates.py` 里 19 个零直接测试函数的逐函数判据测试（全部等级 2：判据/决策）。

为什么必须逐函数点名：`tests/test_gates.py` 对 15 道门只跑一个泛化循环，它证明不了任何一道门的
判据 —— 一个"15 道门全部无条件返回 `pass` 并附带合法自证"的实现照样让 `verdict in (...)` 成立、
`GateResult.__post_init__` 照样满足，于是 `gate_g1` … `gate_g15` 从未被点名调用过（零直接测试：
不是"没跑过"，而是"跑了但没有任何一条断言能因它而红"）。

两条纪律：① 每道门一条正向 + 一条负控，负控打在 `verdict` 的四态语义上
（`pass` / `fail` / `unknown` / `not_applicable`），不是"返回了 GateResult"；
② 夹具不写死受控词表取值（§5.3）：`axis` 来自 `G.AXES`，`claim_id` / `status` 取自
`claimanatomy` 的常量或本文件自建的契约常量。

四态语义（逐条来自 `gates.py` 的模块 docstring）：`pass` = 查过了没问题；`fail` = 查过了有问题；
`unknown` = 没查成（缺输入 / 依赖读不到 / 本轮没跑过）；`not_applicable` = 这道门在本项目的
数据模型上没有可判定的对象（附理由）。负控的重点因此是："缺输入"绝不等于 `pass`。"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from agentflow import claimanatomy as CA
from agentflow import gates as G
from agentflow.tools.doc_tools import CROSS_CHECK_DISCLAIMER

from conftest import TS


# ============================================================ 夹具


def _claim(**over: object) -> dict:
    """一条在每个轴上都自洽的断言（12 字段齐全）。

    字段值刻意从 `claimanatomy` 的受控词表取（`status="证"` 等），
    不在这里另写一份"哪些 status 合法"的表。
    """
    base = {
        "claim_id": "claim-1",
        "kind": "定理",
        "statement": "谱落在区间内。",
        "status": "证",
        "proof_location": "code/p1.py:12",
        "numeric_evidence": {
            "script": "code/p1.py", "range": "d<=33", "n_cases": 256, "n_counterexamples": 0,
        },
        "counterexamples": [],
        "frozen": False,
        "freeze_reason": "",
        "allowed_use": "主结果",
        "scope_caveat": "",
        "revision_hash": "deadbeefdeadbeef",
        "errata_ids": [],
        "evidence_kind": "proof",
        "citations": ["rel:0000"],
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": "",
        "section": "主要结果",
    }
    base.update(over)
    return base


def _doc(claims: list[dict] | None = None, **over: object) -> dict:
    base = {
        "doc_id": "0000",
        "kind": "paper",
        "title": "门测试稿件",
        "markdown_path": "documents/0000.md",
        "claims": claims if claims is not None else [_claim()],
        "open_problems": [],
        "status": "draft",
        "review_rounds": 0,
        "created_at": TS,
        "updated_at": TS,
    }
    base.update(over)
    return base


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """带 `code/p1.py` 与 `documents/0000.md` 的最小工作区。"""
    root = tmp_path / "ws"
    (root / "code").mkdir(parents=True)
    (root / "documents").mkdir(parents=True)
    (root / "code" / "p1.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "documents" / "0000.md").write_text("# 稿件\n", encoding="utf-8")
    return root


def _ctx(ws: Path, proof_location: str = "code/p1.py:12", **over: object) -> G.GateContext:
    """一个所有输入都齐的上下文。

    这是本文件和 `test_gates.py` 的关键差别：这里的每条断言都点名一道门，
    并断言它在这一份"全绿"上下文下的具体 verdict（而不是"是四态之一"）。

    `proof_location` 是一个显式参数（而不是让调用方去改 `ctx.doc`）：
    G1 有两条引用来源（`ctx.files` 与 `claims[*].proof_location`），
    而只有后者会经过 `_looks_like_path` 过滤 —— 想点名测第二条来源的用例
    必须能一行改到它，否则很容易像本文件早先那样"只测了一条来源"。
    """
    kw: dict = {
        "dependencies": [],
        "files": ["code/p1.py"],
        "workspace_root": ws,
        "run_evidence": {
            "checked": True,
            # 回执必须带退出码（业主 2026-10-18：G8 要能分出"跑过且绿"与"跑过且红"）——
            # 这一格是"合格回执"的正样本，所以四个键都齐。
            "commands": [{"claim_id": "claim-1", "command": "python code/p1.py",
                          "exit_code": 0, "output_tail": "ALL CHECKS PASS"}],
        },
        "findings": [],
        "claim_counts": {"declared_claim_count": 1, "declared_counterexample_count": 0,
                         "declared_script_count": 1},
        "banned_words": [],
        "literals": {},
        "observed_hash": None,
        "own_errors": [],
    }
    kw.update(over)
    return G.GateContext.build(_doc([_claim(proof_location=proof_location)]), **kw)


def _frozen_ctx(ws: Path, **over: object) -> G.GateContext:
    """与 `_ctx` 相同，但把 `observed_hash` 设成本轮算出的 hash ⇒ G11 可判。"""
    ctx = _ctx(ws, **over)
    ctx.observed_hash = ctx.revision_hash
    return ctx


# ============================================================
# G1 自含性门：正文不得引用工作区外的路径
# ============================================================


def test_gate_g1_counts_paths_inside_the_workspace(ws: Path):
    """正向：`files` 与 `proof_location` 都是工作区内的相对路径 ⇒ `pass`。

    断言打在判据上：不仅要 `pass`，还要 `counts` 里真的数过路径
    （`检查的路径数 >= 1`）。一个"一条路径都没抽到就报 pass"的实现
    会用零发现伪装成通过 —— 那正是 G13 要抓的形态。
    """
    r = G.gate_g1(_ctx(ws))
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["工作区外"] == 0 and r.counts["工作区内"] >= 1, r.counts


def test_gate_g1_accepts_a_windows_drive_path_inside_the_workspace(ws: Path):
    """正控（修 G-6 时的受控实验）：盘符绝对路径指向工作区内 ⇒ 仍然 `pass`。

    为什么必须有：修 G-6 最省事的错法是"看见盘符就判 `fail`"（把 `^[A-Za-z]:` 当成"包外"的同义词）
    —— 那样上面的负控会全绿，而一条合法的工作区内绝对路径会被误判成阻断交付；两种错法在
    "五档负控"下无法区分，只有这条正控能把它们分开。它同时钉住第二件事：
    `C:<工作区>/code/p1.py:12` 这种盘符 + 尾部行号的写法，行号只能被尾部那一次切分吃掉；
    若实现又一次"在第一个 `:` 处切"，`path_text` 会变成 `"C"` 而报错。

    平台相关处如实 `skip` 并说明原因（不是判据失败，不许折算成 `pass`）：把工作区写成绝对路径需要
    真实盘符，`tmp_path` 与工作区在同一棵树里（本夹具正是这么建的）⇒ 盘符必然相同；POSIX 取不到就跳过。"""
    drive = ws.resolve().drive
    if not drive:
        pytest.skip("本平台的工作区路径没有盘符概念（POSIX）⇒ 这条盘符正控不适用")
    # 用真实的工作区路径构造绝对引用：写成 `<盘符>/<工作区>/code/p1.py:12`。
    # 不能写成 `f"{drive}/{ws.name}/..."` —— 那假设工作区就在盘符根下
    # （实测 `tmp_path` 是 `C:\Users\…\pytest-…\test_…\ws`，这么写会真的指向
    #  `C:\ws`，于是这条正控会"因为夹具写错"而红，而不是因为实现错了）。
    inside_abs = ws.resolve().as_posix() + "/code/p1.py:12"
    ctx = _ctx(ws, files=[], proof_location=inside_abs)
    r = G.gate_g1(ctx)
    assert r.verdict == "pass", (inside_abs, r.verdict, r.reason, dict(r.counts))
    assert r.counts["工作区内"] == 1 and r.counts["工作区外"] == 0, r.counts


def test_gate_g1_rejects_a_dotdot_escape_via_files(ws: Path):
    """负控：`files` 里用 `..` 逃出工作区（相对路径逃逸）⇒ `fail` + 逐条带证据的发现。

    这个夹具的形状是实测校准过的，不是随手写的：G1 的候选来源有两条
    （`ctx.files` 与 `claims[*].proof_location`），而只有
    `proof_location` 会经过 `_looks_like_path` 过滤。见我在这里踩的坑 ——
    下一条 `test_gate_g1_rejects_a_dotdot_escape_via_proof_location`
    才是"两条来源都测"的完整形态。

    为什么必须点名 `gate_g1`：`relative_to` 这条判据是这道门的全部内容，
    泛化循环里的 `verdict in (...)` 对"路径逃逸"没有任何断言。
    """
    ctx = _ctx(ws, files=["code/p1.py", "../outside/p1.py"])
    r = G.gate_g1(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["工作区外"] == 1, r.counts
    assert all(f.get("evidence", "").strip() for f in r.findings)


def test_gate_g1_rejects_a_dotdot_escape_via_proof_location(ws: Path):
    """负控（第二条来源）：`claims[*].proof_location` 用 `..` 逃逸 ⇒ `fail`。

    为什么与上一条分开：`proof_location` 走 `_looks_like_path` 过滤，
    而 `files` 不走。同一份判据的两条输入路径必须各自被证明 ——
    只测一条会留下"另一条被短路"的空档。
    """
    ctx = _ctx(ws, files=[])
    ctx.doc = _doc([_claim(proof_location="../outside/p1.py:12")])
    r = G.gate_g1(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["工作区外"] == 1, r.counts


@pytest.mark.parametrize(
    "label,proof_location",
    [
        ("C:/ 盘符 + 行号", "C:/outside/p1.py:12"),
        ("C:/ 盘符 + 无行号", "C:/outside/p1.py"),
        ("C:\\ 盘符 + 反斜杠", "C:\\outside\\p2.py"),
        ("/ POSIX 绝对", "/abs/outside/p3.py:3"),
        ("Windows 工作区外的绝对路径", str(Path("C:/Windows/System32/drivers/etc/hosts"))),
    ],
)
def test_gate_g1_rejects_a_windows_drive_absolute_proof_location(
    ws: Path, label: str, proof_location: str
):
    """负控（盘符 / 绝对路径这一档，缺陷 G-6 的原形状）：⇒ `fail` + `工作区外` 计数。

    修之前：`_looks_like_path("C:/outside/p1.py:12")` 为真 ⇒ 成为候选；但 `rel = raw.split(":")[0].strip()`
    得到 `"C"`（盘符被当成 `file:line` 分隔符切掉）⇒ `root / "C"` = `<root>/C` ⇒ 落在工作区内 ⇒
    `工作区外=0` ⇒ G1 报 `pass`，而相对逃逸（`../outside/p1.py`）判 `fail`：盘符这一档被静默判成
    "包内"，而 G1 的失败处置是阻断交付 ⇒ `claims[*].proof_location` 里最典型的"包外引用"被漏掉。
    五档必须各自被拒：`C:/outside/p1.py`（无行号）、`/abs/outside/p3.py:3`（POSIX 绝对）、
    `C:\outside\p2.py`（反斜杠盘符）、`/outside/p1.py`、`/outside/p1.py:12` —— 只测带行号那条，
    `split(":")` 型实现照样能过（修法：按字符串形态判绝对 + 只切尾部 `:行号`）。
    平台无关性：`/abs/outside/p3.py:3` 若用 `Path.is_absolute()` 判，在 Windows 得 `False`（POSIX 根
    路径算相对），正是本缺陷在另一平台的镜像，所以断言不能只写在 `sys.platform == "win32"` 分支里。
    期望 `verdict == "fail"`（不是 `pass` / `unknown`）且 `counts["工作区外"] == 1`、`counts["工作区内"] == 0`。"""
    claim = _claim(proof_location=proof_location)
    claim.pop("numeric_evidence")
    ctx = _ctx(ws, files=[])
    ctx.doc = _doc([claim])
    r = G.gate_g1(ctx)
    assert r.verdict == "fail", (label, proof_location, r.verdict, r.reason, dict(r.counts))
    assert r.counts["工作区外"] == 1, (label, proof_location, r.counts)
    assert r.counts["工作区内"] == 0, (label, proof_location, r.counts)
    assert all(f.get("evidence", "").strip() for f in r.findings), r.findings


# ---- G1 的 `_strip_line_suffix`（G-12 顺带发现的那条测试盲点） ----------------


def test_strip_line_suffix_only_cuts_a_numeric_suffix_at_the_very_end():
    """点名单测 `_strip_line_suffix`：只切尾部且其后必须是数字。

    为什么必须单独点名（G-12 顺带发现的盲点）：把 `_LINE_SUFFIX_RE` 的 `$` 锚点去掉
    （`r":(\d+)$"` → `r":(\d+)"`）之后没有任何 `verdict` 会变 —— 见证串 `C:/out12:30/p1.py` 被
    `re.search` 切成 `C:/out12:30/p1`（撞上第一个 `:<数字>`，即 `:30`），而整个
    `tests/test_coverage_gates.py` 里 32 条 G1 断言全绿（切出来仍是绝对路径 ⇒ G1 仍 `fail`、
    `counts` 不变）：判据只看"是不是绝对路径 + 在不在工作区内"，不看路径本体对不对。

    所以证据补在函数本身上：尾部不是 `:<数字>` 的必须原样返回；四档一起断言是刻意的 ——
    只断言"见证串原样返回"，一个 `return raw`（恒等函数）也能过（那样 G1 会把 `code/p1.py:12`
    当成文件名、行号切分整条失效），所以必须同时断言尾部 `:<数字>` 仍要被切掉。"""
    assert G._strip_line_suffix("C:/out12:30/p1.py") == "C:/out12:30/p1.py", (
        "尾部不是 `:<数字>` ⇒ 必须原样返回；被切成 `C:/out12:30/p1` 这类残缺串说明 "
        "`_LINE_SUFFIX_RE` 丢了 `$` 锚点（只在中间切、不管尾部）"
    )
    assert G._strip_line_suffix("C:/out12:30/p1.py:9") == "C:/out12:30/p1.py"
    assert G._strip_line_suffix("code/p1.py:12") == "code/p1.py"
    assert G._strip_line_suffix("C:/x/y.py:abc") == "C:/x/y.py:abc"


def test_gate_g1_returns_unknown_without_a_workspace_root(ws: Path):
    """负控（三态）：没给工作区根 ⇒ `unknown`，不是 `pass`。

    "判不了一个路径在不在工作区内"与"路径都在工作区内"是两件事。
    """
    ctx = _ctx(ws)
    ctx.workspace_root = None
    r = G.gate_g1(ctx)
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert "workspace_root" in r.reason


# ============================================================
# G2 引用解析门 / G3 交叉引用门
# ============================================================


def test_gate_g2_accepts_resolvable_citation_prefixes(ws: Path):
    """正向：`lit:`/`rel:`/`exp:`/`eval:` 前缀 + 非空代号 ⇒ `pass`。"""
    r = G.gate_g2(_ctx(ws))
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["前缀可解析"] == 1 and r.counts["前缀不可解析"] == 0, r.counts


def test_gate_g2_rejects_an_unparseable_citation(ws: Path):
    """负控：空代号（`"rel:"`）⇒ `fail`，reason 说"无法解析"。

    这一档是语法级缺陷（与 G3 的存在性缺陷不同）。判据是
    "前缀可识别吗？代号非空吗？"，所以负控要用空代号而不是"不存在的代号"。
    """
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(citations=["rel:"])])
    r = G.gate_g2(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["解析失败"] == 1, r.counts
    assert "无法解析" in "".join(f["message"] for f in r.findings)


def test_gate_g2_warns_but_does_not_fail_on_an_unknown_prefix(ws: Path):
    """负控（防误伤，照 §8.4 "假阳性须逐条留痕"）：未知前缀只 `warning`。

    为什么它是负控而不是"又一条正向"：把未知前缀判成 `fail` 会让
    "我们用了 `doi:` 这种前缀"变成阻断交付的缺陷 —— 而参考体例明确要求
    这一档逐条留痕但不阻断（docstring 逐字："只报 warning 并逐条留痕"）。
    """
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(citations=["doi:10.1000/x"])])
    r = G.gate_g2(ctx)
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["前缀不可解析"] == 1, r.counts
    assert [f["severity"] for f in r.findings] == ["warning"], r.findings


def test_gate_g3_accepts_a_proof_location_pointing_into_the_document(ws: Path):
    """正向：`proof_location` 是本文档内真实存在的 claim_id ⇒ `pass`（"允许自指"）。"""
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(proof_location="claim-1")])
    r = G.gate_g3(ctx)
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["指向本文档内 claim_id"] == 1, r.counts


def test_gate_g3_rejects_a_proof_location_that_is_neither_id_nor_path(ws: Path):
    """负控：`proof_location` 既不是本文档内的 claim_id、也不是 `file:line` ⇒ `fail`。

    这道门的适配判据被显式登记过（`criterion_revision`），所以负控必须正好打在
    这两条互补的合法形态上：换成一个像人话的字符串就必须红。
    """
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(proof_location="见上文所述")])
    r = G.gate_g3(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["两者都不是"] == 1, r.counts
    assert "既不是" in "".join(f["message"] for f in r.findings)

# ============================================================
# G4 账本对账门
# ============================================================


def test_gate_g4_accepts_a_consistent_ledger(ws: Path):
    """正向：`markdown_path` 在盘上 + 声明断言数 == 实际断言数 ⇒ `pass`。

    两个条件是独立的，所以正向断言必须把 `counts` 里那两项都核一遍 ——
    "文件存在"成立而"计数一致"不成立的实现不该拿到 `pass`（见下一条负控）。
    """
    r = G.gate_g4(_ctx(ws))
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["markdown_path 存在"] is True, r.counts
    assert r.counts["实际断言数"] == r.counts["声明的断言数"] == 1, r.counts


def test_gate_g4_rejects_a_missing_markdown_file(ws: Path):
    """负控（账实不符之一）：`markdown_path` 点名的文件不在盘上 ⇒ `fail`。"""
    ctx = _ctx(ws)
    ctx.doc = _doc(markdown_path="documents/does-not-exist.md")
    r = G.gate_g4(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert any("不存在" in f["message"] for f in r.findings), r.findings


def test_gate_g4_rejects_a_claim_count_drift(ws: Path):
    """负控（账实不符之二）：声明的断言数与实际不一致 ⇒ `fail`（计数漂移）。

    与上一条分开是刻意的：它们走两个不同的 `findings.append` 分支。
    合成一条会让"只查了文件存在性"的实现通过 —— 而"十处计数漂移"正是
    §1.4 记录的那个真实教训。
    """
    ctx = _ctx(ws, claim_counts={"declared_claim_count": 7})
    r = G.gate_g4(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert any("计数漂移" in f["message"] for f in r.findings), r.findings


# ============================================================
# G5 禁词/手糊门
# ============================================================


def test_gate_g5_returns_not_applicable_without_a_word_list(ws: Path):
    """负控（三态纪律的教科书形态）：没给词表 ⇒ `not_applicable`，而不是 `pass`。

    docstring 逐字："缺词表时报 not_applicable 而不是 pass"。
    一个报 `pass` 的实现会让"这道门本轮没跑"伪装成"文风没问题"。
    """
    r = G.gate_g5(_ctx(ws))
    assert r.verdict == "not_applicable", (r.verdict, r.reason)
    assert r.counts["提供的禁词数"] == 0, r.counts
    assert "没有可判定的对象" in r.reason


def test_gate_g5_accepts_when_no_banned_word_is_present(ws: Path):
    """正向：给了词表且正文不含它 ⇒ `pass`，并如实给出扫描条数与命中数。

    注意"给了词表但零命中"与上一条"没给词表"必须都能区分 ——
    这两条测试合起来就是这个区分的钉子。
    """
    ctx = _ctx(ws, banned_words=["显然"])
    r = G.gate_g5(ctx)
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts == {"扫描的断言数": 1, "禁词数": 1, "命中数": 0}, r.counts


def test_gate_g5_rejects_a_banned_word_hit_with_context(ws: Path):
    """负控：正文命中禁词 ⇒ `fail`，且发现里带 ±30 字上下文供人工裁。

    为什么要断言上下文：docstring 逐字说命中"须逐条人工裁"，
    没有上下文的发现等于无法裁 —— 而"不可裁的告警"会被训练成噪音。
    """
    ctx = _ctx(ws, banned_words=["显然"])
    ctx.doc = _doc([_claim(statement="这个结论显然是错的。")])
    r = G.gate_g5(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["命中数"] == 1, r.counts
    f = r.findings[0]
    assert "显然" in f["evidence"] and "上下文" in f["evidence"], f


# ============================================================
# G6 虚证门
# ============================================================


def test_gate_g6_accepts_an_existing_script(ws: Path):
    """正向：点名的脚本在工作区里真的存在 ⇒ `pass`，且数过"点名的脚本数"。"""
    r = G.gate_g6(_ctx(ws))
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["点名的脚本数"] == 1 and r.counts["虚证数"] == 0, r.counts


def test_gate_g6_rejects_a_phantom_script(ws: Path):
    """负控：点名的脚本不存在 ⇒ `fail`（虚证）—— 这道门的全部意义。"""
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(numeric_evidence={"script": "code/ghost.py", "n_counterexamples": 0})])
    r = G.gate_g6(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["虚证数"] == 1, r.counts
    assert any("虚证" in f["message"] for f in r.findings), r.findings


def test_gate_g6_rejects_a_glob_that_matches_nothing(ws: Path):
    """负控（最容易伪装成"存在"的形态，docstring 逐字点名）：通配符零命中 ⇒ `fail`。

    为什么要单独一条：`glob` 返回空列表是静默的。一个把
    `if any(ch in script for ch in "*?[")` 分支写成"有通配符就算存在"的实现
    能通过"点名文件存在"的正向断言，但过不了这条。
    """
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(numeric_evidence={"script": "code/*.nope", "n_counterexamples": 0})])
    r = G.gate_g6(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["虚证数"] == 1, r.counts


def test_gate_g6_returns_not_applicable_when_no_script_is_named(ws: Path):
    """负控（三态）：一条数值证据都没点名 ⇒ `not_applicable`，不是 `pass`。

    docstring 逐字："这与『脚本都存在』是两件事 —— 所以判 not_applicable 而不是 pass"。
    """
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(numeric_evidence={})])
    r = G.gate_g6(ctx)
    assert r.verdict == "not_applicable", (r.verdict, r.reason)
    assert "没有任何一条点名数值脚本" in r.reason


# ============================================================
# G7 台账完整门
# ============================================================


def test_gate_g7_accepts_a_numeric_claim_with_structured_evidence(ws: Path):
    """正向：数值型断言有 `numeric_evidence.script` ⇒ `pass`。"""
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(statement="对 256 个样本做了枚举。")])
    r = G.gate_g7(ctx)
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["有台账行"] == 1 and r.counts["缺台账行"] == 0, r.counts


def test_gate_g7_rejects_a_numeric_claim_without_a_ledger_row(ws: Path):
    """负控：正文出现"枚举"却没有 `numeric_evidence` ⇒ `fail`（"仅泛证型"）。

    docstring 逐字："正文里出现『验/数值/枚举/穷举』这类字样却没有
    `numeric_evidence` 的行，就是『仅泛证型』"。
    """
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(statement="我们枚举了所有小参数情形。", numeric_evidence={}, status=None)])
    r = G.gate_g7(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["缺台账行"] == 1, r.counts
    assert any("仅泛证型" in f["message"] for f in r.findings), r.findings


def test_gate_g7_rejects_a_proved_status_without_a_ledger_row(ws: Path):
    """负控（识别的第二个入口）：`status='验'` 而没有台账行 ⇒ 同样 `fail`。

    识别数值型断言有两条入口（正文关键词 / `status=='验'`）。只测关键词那条
    会留下"status 分支被写坏"的空档 —— 而它正是结构化稿件的主要入口。
    """
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(statement="没有任何关键词的一句话。", status="验", numeric_evidence={})])
    r = G.gate_g7(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["缺台账行"] == 1, r.counts


# ============================================================
# G8 可复跑门
# ============================================================


def test_gate_g8_accepts_when_run_evidence_covers_every_numeric_claim(ws: Path):
    """正向：本轮实跑记录按 `claim_id` 覆盖了全部数值断言 ⇒ `pass`。"""
    r = G.gate_g8(_ctx(ws))
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["需要命令的数值断言数"] == 1 and r.counts["缺命令"] == 0, r.counts


def test_gate_g8_returns_unknown_without_run_evidence(ws: Path):
    """负控（docstring 说这道门是"必须能返回『没做』"的最典型例子）：
    没给 `run_evidence` ⇒ `unknown`，绝不是 `pass`。

    这条断言直接对应 `draft/17` 的教训："多数脚本不设退出码，于是
    『未报错』被误读为『无问题』"。
    """
    ctx = _ctx(ws)
    ctx.run_evidence = None
    r = G.gate_g8(ctx)
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert r.counts["本轮实跑记录"] == "未提供", r.counts
    assert "无法判定" in r.reason


def test_gate_g8_returns_unknown_when_caller_declares_it_did_not_run(ws: Path):
    """负控（第三态）：调用方显式声明 `checked=False` ⇒ `unknown`。

    与上一条是不同的输入、也可能来自不同原因：上一条是"没给"，这条是
    "给了但说没跑"。两者都必须是 `unknown`，但 reason 必须能分开 ——
    所以这条额外断言 reason 引出调用方给的原因。
    """
    ctx = _ctx(ws, run_evidence={"checked": False, "reason": "本轮只改措辞，没跑脚本"})
    r = G.gate_g8(ctx)
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert "本轮只改措辞，没跑脚本" in r.reason, r.reason


def test_gate_g8_rejects_a_numeric_claim_missing_from_run_evidence(ws: Path):
    """负控：数值断言没有对应的本轮实跑命令 ⇒ `fail`（差集非空）。"""
    ctx = _ctx(ws, run_evidence={"checked": True, "commands": []})
    r = G.gate_g8(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["缺命令"] == 1, r.counts


# ============================================================
# G9 计数一致门
# ============================================================


def test_gate_g9_accepts_when_declared_counts_match_the_recomputation(ws: Path):
    """正向：声明的三个计数与从稿件重算的一致 ⇒ `pass`，且数过"对账的计数项"。"""
    r = G.gate_g9(_ctx(ws))
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["对账的计数项"] == 3 and r.counts["不一致项"] == 0, r.counts


def test_gate_g9_returns_unknown_without_declared_counts(ws: Path):
    """负控（三态）：没有声明侧 ⇒ `unknown`。

    docstring 逐字："单看一处数字永远不能判『一致』——
    那正是 §1.4 十处漂移始终没被发现的原因（没有任何脚本在查）"。
    一个"没给声明就返回 pass"的实现会永远报一致。
    """
    ctx = _ctx(ws, claim_counts=None)
    r = G.gate_g9(ctx)
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert "没有『另一个文件』可对账" in r.reason


def test_gate_g9_rejects_a_counterexample_count_drift(ws: Path):
    """负控：反例数声明与实际不一致 ⇒ `fail`（不只是断言数那一项）。

    为什么单测这一项：三个计数项（断言数/反例数/脚本数）走同一个循环，
    但只有"反例数"需要真的去 `sum(len(counterexamples))`。
    只测断言数会留下"反例数恒等于 0"的实现照样通过的空档。
    """
    ctx = _ctx(ws, claim_counts={
        "declared_claim_count": 1, "declared_counterexample_count": 5, "declared_script_count": 1,
    })
    r = G.gate_g9(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["实际反例数"] == 0, r.counts
    assert any("反例数" in f["target"] for f in r.findings), r.findings


def test_gate_g9_rejects_a_per_kind_count_drift(ws: Path):
    """负控：`declared_kind_counts` 里某一类与实际不符 ⇒ `fail`。

    这是第四条对账路径（按 `kind` 分类型），只有在调用方给出该映射时才启用。
    它是"U0 说 121 条、V2 说 116 条"最接近的形态。
    """
    ctx = _ctx(ws, claim_counts={
        "declared_claim_count": 1, "declared_counterexample_count": 0, "declared_script_count": 1,
        "declared_kind_counts": {"定理": 3},
    })
    r = G.gate_g9(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert any(f["target"] == "kind=定理" for f in r.findings), r.findings


# ============================================================
# G10 审校格式门
# ============================================================


def test_gate_g10_returns_unknown_without_a_findings_list(ws: Path):
    """负控（三态，docstring 逐字）：没给 `findings` ⇒ `unknown`。

    "没有可判定的对象"与"没有发现"必须分开 —— 后者才可能判 `pass`。
    """
    ctx = _ctx(ws, findings=None)
    r = G.gate_g10(ctx)
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert "与『没有发现』不同" in r.reason


def test_gate_g10_is_unknown_when_a_finding_lacks_the_four_fields(ws: Path):
    """判据（键不全的那一半）：这一条发现的键不全 ⇒ `unknown`。

    `gates.gate_g10` 的 docstring 逐字："键不全的行：仍然报 `unknown` 并把缺的键逐条列出来（不删门、
    不判 pass）。这些行是契约生效日之前落盘的历史行，或尚未补键的产出方写出的行 —— 两种都要看得见。"

    旧名字与旧 docstring 已过期，`X-96.3-3` 就地更正：它此前叫
    `test_gate_g10_is_unknown_because_schema_lacks_the_four_fields`，理由是 `schema.ReviewFinding`
    只有 `kind/level/target/message/evidence/status/round/resolution_note`、没有 `line` /
    `verbatim_quote` / `minimal_fix` / `maths`（这道门不可能逐字判定）。那句话已不成立：`P-9`
    候选 A 之后 `ReviewFinding` 带上了这四个字段（`axis` 也一并补上），所以 `unknown` 的成因不再是
    "schema 缺字段"而是"这一条发现键不全"（历史行，或还没补键的产出方）；行为与判据一个字没动。
    关键断言仍是：如实报 `unknown` 并逐条列出缺失字段，而不是删门或报 pass。"""
    ctx = _ctx(ws, findings=[{
        "finding_id": "0000", "kind": "overclaim", "level": "error", "target": "claim-1",
        "message": "m", "evidence": "e", "status": "open", "round": 1, "resolution_note": "",
    }])
    r = G.gate_g10(ctx)
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert r.counts["发现数"] == 1, r.counts
    ev = " ".join(f["evidence"] for f in r.findings)
    for field in ("line", "verbatim_quote", "minimal_fix", "maths"):
        assert field in ev, f"缺失字段 {field} 没被逐条列出：{ev}"
    assert "禁 AI 区" in r.reason, r.reason


def test_gate_g10_rejects_an_overlong_verbatim_quote(ws: Path):
    """负控（判据可判定的那一半）：`verbatim_quote` 超过 20 词 ⇒ 必须报出来。

    这道门的六个字段里，只有"≤20 词"这条在给了字段时可判定。
    上一条测的是"缺字段 ⇒ unknown"，这条测的是"字段齐了但引文太长 ⇒ 有发现"。
    """
    long_quote = " ".join(f"w{i}" for i in range(25))
    ctx = _ctx(ws, findings=[{
        "finding_id": "0000", "kind": "overclaim", "level": "error", "target": "claim-1",
        "message": "m", "evidence": "e", "line": 12, "verbatim_quote": long_quote,
        "minimal_fix": "改措辞", "maths": "yes", "axis": G.AXES[0],
    }])
    r = G.gate_g10(ctx)
    assert any("超过 20 词" in f["message"] for f in r.findings), r.findings


def test_gate_g10_accepts_a_conforming_finding_list(ws: Path):
    """正向（字段齐全且引文合规的那一半 ⇒ `pass`）。

    为什么这条可行：上一条的夹具只要补上四个字段，`structural_gap` 就变成 0，
    这道门就走可判定的分支。所以"字段齐全 ⇒ 能判"这件事本身是可验证的 ——
    它证明了 G10 报 `unknown` 不是"实现懒得判"，而是那一行自己键不全
    （`X-96.3-3` 更正：这句此前写的是"schema 缺字段"，而 `P-9` 候选 A 之后
    `ReviewFinding` 已经带上那四个字段）。
    """
    ctx = _ctx(ws, findings=[{
        "finding_id": "0000", "kind": "overclaim", "level": "warning", "target": "claim-1",
        "message": "m", "evidence": "e", "line": 12, "verbatim_quote": "已证明",
        "minimal_fix": "改成『交叉验证』", "maths": "yes", "axis": G.AXES[0],
    }])
    r = G.gate_g10(ctx)
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["不合格式"] == 0, r.counts


# ============================================================
# G11 版本冻结门
# ============================================================


def test_gate_g11_accepts_when_the_observed_hash_matches(ws: Path):
    """正向：上一轮钉住的 hash 与本轮重算一致 ⇒ `pass`（版本冻结）。"""
    r = G.gate_g11(_frozen_ctx(ws))
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["是否冻结"] is True, r.counts


def test_gate_g11_returns_unknown_without_the_previous_hash(ws: Path):
    """负控（三态，docstring 逐字）：没给上一轮的 hash ⇒ `unknown`。

    "本轮已经钉住 hash" ≠ "审校期间没被改过"。一个把这两件事
    折叠成 `pass` 的实现会让"没人比对过"读成"没被改过"。
    """
    r = G.gate_g11(_ctx(ws))
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert "钉住 hash ≠ 验证没被改" in r.reason
    assert r.counts["上一轮钉住的 hash"] == "未提供", r.counts


def test_gate_g11_rejects_when_the_document_changed_after_review(ws: Path):
    """负控：上一轮 hash 与本轮不一致 ⇒ `fail` + "本次审校结论作废"。"""
    ctx = _frozen_ctx(ws)
    ctx.observed_hash = "0" * 16
    r = G.gate_g11(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["是否冻结"] is False, r.counts
    assert any("改过" in f["message"] for f in r.findings), r.findings


# ============================================================
# G12 反方门
# ============================================================


def test_gate_g12_accepts_a_proved_claim_with_counter_search_traces(ws: Path):
    """正向：`status='证'` 的断言带 `counterexamples` 键或 `n_counterexamples` ⇒ `pass`。"""
    r = G.gate_g12(_ctx(ws))
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["标『证』的断言数"] == 1 and r.counts["有反例搜索痕迹"] == 1, r.counts


def test_gate_g12_returns_not_applicable_when_nothing_is_proved(ws: Path):
    """负控（三态）：没有任何 `status='证'` 的断言 ⇒ `not_applicable`。

    docstring 逐字："这不是『反例都搜过了』"。
    """
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(status=None)])
    r = G.gate_g12(ctx)
    assert r.verdict == "not_applicable", (r.verdict, r.reason)
    assert "没有任何 `status='证'`" in r.reason


def test_gate_g12_rejects_a_proved_claim_with_an_actual_counterexample(ws: Path):
    """负控（自相矛盾）：有反例却标 `status='证'` ⇒ `fail`（error 级）。"""
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(counterexamples=[{"d": 33, "why": "越界"}], status="证")])
    r = G.gate_g12(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert any("自相矛盾" in f["message"] for f in r.findings), r.findings
    assert all(f["severity"] == "error" for f in r.findings if "自相矛盾" in f["message"])


def test_gate_g12_warns_but_does_not_fail_when_counter_search_left_no_trace(ws: Path):
    """负控（防误伤）：标了『证』但没有反例搜索痕迹 ⇒ 只 `warning`，不 `fail`。

    为什么这是负控而非正向：把这一档判 `fail` 会让每一份历史稿件都阻断交付
    （老行没有这个字段）。docstring 的处置是"『没搜过』不许读成『没有反例』"，
    也就是留痕而不是阻断 —— 这个差别只有断言 `verdict` 与 `severity` 才钉得住。
    """
    ctx = _ctx(ws)
    claim = _claim(status="证")
    claim.pop("counterexamples")
    claim["numeric_evidence"] = {"script": "code/p1.py"}
    ctx.doc = _doc([claim])
    r = G.gate_g12(ctx)
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert [f["severity"] for f in r.findings] == ["warning"], r.findings
    assert "没搜过" in r.findings[0]["evidence"], r.findings[0]


def test_gate_g12_reads_a_present_counterexamples_key_as_a_counter_search_trace(ws: Path):
    """差分：唯一改动是 `counterexamples` 键在不在，"有反例搜索痕迹"必须跟着变。

    为什么这条必须单独存在：本文件的 `_claim` 夹具（第 60-82 行）同时给了
    `counterexamples: []` 与 `numeric_evidence.n_counterexamples: 0`，于是上面那条正向
    用例对这一格是免疫的 —— 实测把判据里"键存在算留痕"那一句删掉，
    `test_coverage_gates.py + test_gates.py -k g12` 仍然 7 passed / 0 failed
    （变异存活）。所以这里用"同一条 claim、只弹掉一个键"的差分把它钉住：
    正向与负控在同一个用例里成对出现，任一侧被抹平都会红。
    """
    ctx = _ctx(ws)
    keyed = _claim()
    keyed["numeric_evidence"] = {"script": "code/p1.py"}  # 故意不给 n_counterexamples
    bare = _claim()
    bare["numeric_evidence"] = {"script": "code/p1.py"}
    bare.pop("counterexamples")

    ctx.doc = _doc([keyed])
    r_keyed = G.gate_g12(ctx)
    ctx.doc = _doc([bare])
    r_bare = G.gate_g12(ctx)

    assert r_keyed.counts["有反例搜索痕迹"] == 1, r_keyed.counts
    assert r_bare.counts["有反例搜索痕迹"] == 0, r_bare.counts
    assert (
        r_keyed.counts["有反例搜索痕迹"] != r_bare.counts["有反例搜索痕迹"]
    ), "差分没做出来：两边被抹平成同一个数，这条用例就没在测判据"
    assert [f["severity"] for f in r_keyed.findings] == [], r_keyed.findings
    assert [f["severity"] for f in r_bare.findings] == ["warning"], r_bare.findings


# ============================================================
# G13 空结论自证门
# ============================================================


def test_gate_g13_returns_unknown_without_the_other_gates_results(ws: Path):
    """负控（三态）：没给其余各门的结论 ⇒ `unknown`（"缺了报告就没有对象"）。"""
    r = G.gate_g13(_ctx(ws))
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert r.counts["检查的门数"] == 0, r.counts


def test_gate_g13_accepts_when_every_zero_finding_gate_is_self_attested(ws: Path):
    """正向：其余各门凡报"零发现"，都带自证过程与数字 ⇒ `pass`。

    做法：用真实的 `run_all_gates` 产出 `results` —— 不手捏 GateResult
    （手捏会让"结构强制"这条设计失去意义）。
    """
    ctx = _frozen_ctx(ws)
    results = G.run_all_gates(ctx)
    r = G.gate_g13(ctx, results)
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["报零发现的门数"] == r.counts["自证齐全"], r.counts
    assert r.counts["报零发现的门数"] >= 1, "没有任何门报零发现 ⇒ 这条断言失去对象"


def test_gate_g13_rejects_a_zero_finding_gate_without_self_attestation(ws: Path):
    """负控（唯一能构造出违规对象的方式）：手工塞一个缺自证的 `pass` 门 ⇒ `fail`。

    为什么必须用 `object.__new__` 绕过 `__post_init__`：`GateResult.__post_init__`
    已经让"pass + 零发现 + 无自证"的对象构造不出来（这是 G13 的结构强制形态）。
    所以"G13 独立数一遍"这条防线只能用一个绕过构造器的对象来证明它真的在工作
    —— 这条测试正是 docstring 里那句"若有人从别处塞进一个 GateResult
    （或未来加了旁路），这里仍然会红"的可执行形式。
    """
    ctx = _frozen_ctx(ws)
    real = G.run_all_gates(ctx)
    rogue = object.__new__(G.GateResult)
    object.__setattr__(rogue, "gate_id", "G1")
    object.__setattr__(rogue, "name", "冒充的自含性门")
    object.__setattr__(rogue, "axis", G.AXES[0])
    object.__setattr__(rogue, "criterion", "c")
    object.__setattr__(rogue, "verdict", "pass")
    object.__setattr__(rogue, "reason", "")
    object.__setattr__(rogue, "findings", ())
    object.__setattr__(rogue, "self_attestation", "")   # ← 关键：零发现却没有自证
    object.__setattr__(rogue, "counts", {})
    object.__setattr__(rogue, "evidence_used", ())
    # `criterion_revision` 从声明表取：这里不写第三份文本
    # （G13 不判这一栏，取哪一份都不影响本条的结论；写死字面量只会多一份副本）。
    object.__setattr__(rogue, "criterion_revision", G.GATE_CRITERIA_REVISION["G1"])

    r = G.gate_g13(ctx, {**real, "G1": rogue})
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert any(f["target"] == "G1" for f in r.findings), r.findings
    assert any("格式违规" in f["message"] for f in r.findings), r.findings


# ============================================================
# G14 降级合规门
# ============================================================


def test_gate_g14_accepts_a_proof_backed_main_result(ws: Path):
    """正向：`evidence_kind='proof'` + `allowed_use='主结果'` ⇒ `pass`（无需降级）。"""
    r = G.gate_g14(_ctx(ws))
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["须降级却标主结果"] == 0 and r.counts["作废却在正文"] == 0, r.counts


def test_gate_g14_rejects_a_cross_check_claim_used_as_a_main_result(ws: Path):
    """负控（硬性降级规则）：`cross_check` 标 `allowed_use='主结果'` ⇒ `fail`。

    docstring 逐字："把交叉验证写进主结果"是这道门要拦的核心形态。
    """
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(evidence_kind="cross_check", allowed_use="主结果",
                           disclaimer=CROSS_CHECK_DISCLAIMER)])
    r = G.gate_g14(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["须降级却标主结果"] == 1, r.counts
    assert any("必须降为" in f["message"] for f in r.findings), r.findings


def test_gate_g14_rejects_a_retracted_claim_in_the_main_body(ws: Path):
    """负控（第二条独立判据）：`status='作废'` 的断言出现在正文 ⇒ `fail`。

    与上一条分开是刻意的：它们走两个不同的分支，且这条依赖
    `claimanatomy.is_retracted` / `_retraction_reason`（同一份判据）。
    合成一条会留下"降级规则写对了但作废规则没写"的空档。
    """
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(status=CA.STATUS_RETRACTED if hasattr(CA, "STATUS_RETRACTED") else "作废")])
    r = G.gate_g14(ctx)
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["作废却在正文"] == 1, r.counts
    assert any("只能进附录" in f["message"] for f in r.findings), r.findings


def test_gate_g14_warns_but_does_not_fail_on_move_to_open(ws: Path):
    """负控（防误伤）：`allowed_use='移入 open'` ⇒ 只 `warning`，不 `fail`。

    docstring 的处置是"它不应出现在主结果区（须进开放问题区）"——
    即留痕而非阻断。把它判 fail 会让一份已经按规矩降级的稿件被拦下。
    """
    ctx = _ctx(ws)
    ctx.doc = _doc([_claim(evidence_kind="proof", allowed_use="移入 open")])
    r = G.gate_g14(ctx)
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert [f["severity"] for f in r.findings] == ["warning"], r.findings


# ============================================================
# G15 自己的错入册
# ============================================================


def test_gate_g15_accepts_an_explicit_zero_own_errors(ws: Path):
    """正向：调用方显式声明 `own_errors=[]` ⇒ `pass`，并写明"显式声明零错误"。

    这条与下一条合起来是"显式声明"与"没写"的区分 —— 正是三态纪律在报告字段上的形态。
    """
    r = G.gate_g15(_ctx(ws, own_errors=[]))
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["显式声明零错误"] is True, r.counts
    assert "与『没写』严格区分" in r.reason


def test_gate_g15_rejects_when_own_errors_was_never_written(ws: Path):
    """负控（唯一一个"没给输入判 fail"的门）：`own_errors=None` ⇒ `fail`。

    docstring 逐字："『我没犯错』必须由人写出来，不许由『没写』默认成立"。
    所以这道门刻意与其它门相反 —— 缺输入不是 `unknown` 而是 `fail`。
    这条断言把这个反直觉的设计钉住：若有人"统一"成 unknown，它会红。
    """
    r = G.gate_g15(_ctx(ws, own_errors=None))
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["自身错误条数"] == "未登记", r.counts
    assert "退回" in r.reason


def test_gate_g15_lists_the_registered_own_errors(ws: Path):
    """正向（有内容的那一档）：登记了自身错误 ⇒ `pass` 且条数被数出来。"""
    ctx = _ctx(ws, own_errors=["把 cross_check 写成了 proof", "漏了一条引用"])
    r = G.gate_g15(ctx)
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["自身错误条数"] == 2, r.counts


# ============================================================
# known_gate_ids / run_gate / run_all_gates
# ============================================================


def test_known_gate_ids_matches_the_hardcoded_tuple_exactly():
    """正向：`known_gate_ids()`（从声明表派生）与 `GATE_IDS`（硬编码）逐条一致。

    docstring 逐字："必须与 `GATE_IDS` 逐条一致"。这两者分处"派生"与"硬编码"
    两个来源，所以它们的一致性是一个真实的不变量，不是一个恒等式。
    """
    assert G.known_gate_ids() == G.GATE_IDS
    assert G.known_gate_ids() == tuple(sorted(G.GATE_IDS, key=lambda g: int(g[1:])))


def test_known_gate_ids_rejects_a_missing_or_extra_gate(monkeypatch: pytest.MonkeyPatch):
    """负控（变异试验）：往声明表里塞一个 `G16` ⇒ `known_gate_ids()` 必须变红。

    为什么等价于"测试会红"：这条断言把"派生值 == 硬编码值"变成可执行的判据。
    注入一个多余门之后 `known_gate_ids() != GATE_IDS`，
    所以上一条测试的断言会失败 —— 这证明它依赖这份一致性，
    而不是"永远为真"。
    """
    monkeypatch.setitem(G.GATES, "G16", dict(G.GATES["G1"], name="冒充的门"))
    try:
        assert G.known_gate_ids() != G.GATE_IDS, "塞了 G16 之后两者仍然相等 ⇒ 上一条断言是恒真的"
    finally:
        G.GATES.pop("G16", None)
    assert G.known_gate_ids() == G.GATE_IDS


def test_run_gate_returns_the_named_gate_and_only_that_gate(ws: Path):
    """正向：`run_gate(gid, ctx)` 返回的 `gate_id` / `name` / `axis` 取自该门自己的声明行。

    为什么重要（`test_gates.py` 那条泛化循环欠缺的）：一个"总是返回 G1 的结论"的实现在泛化循环里
    照样过（`r.gate_id == gid` 只抓门号、抓不到"门内容错配"），这里额外断言内容取自 `G.GATES[gid]`。

    `criterion` 曾经只能断言前缀：那时有三份文本（① `GATES[gid]["criterion"]` 声明表、② 每个
    `gate_gN` 里的局部变量、③ `GateResult(...)` 构造时传的那个），实测 15 道门里 6 道的 ①③ 不一致
    （`docs/PROPOSALS.md` G-7）。已修：每个门只在函数体开头写一句
    `criterion = GATES[gate_id]["criterion"]`，所以抽样这三门（G1 / G5 / G15）与声明表逐字相同。
    同一形态的第二个字段（G-12）：`criterion_revision` 现在也从 `GATE_CRITERIA_REVISION` 取；
    穷尽式的 15 门断言在下一条 `test_gate_criterion_revision_texts_are_a_single_source`。"""
    ctx = _frozen_ctx(ws)
    for gid in ("G1", "G5", "G15"):
        r = G.run_gate(gid, ctx)
        assert r.gate_id == gid, (gid, r.gate_id)
        assert r.name == G.GATES[gid]["name"], gid
        assert r.axis == G.GATES[gid]["axis"], gid
        assert r.criterion == G.GATES[gid]["criterion"], (
            gid, r.criterion, G.GATES[gid]["criterion"])
        assert r.criterion_revision == G.GATE_CRITERIA_REVISION[gid], (
            gid, r.criterion_revision, G.GATE_CRITERIA_REVISION[gid])


def test_gate_criterion_texts_are_a_single_source(ws: Path):
    """反漂移（单一来源，缺陷 G-7）：15 道门的 `GateResult.criterion` 逐字等于声明表那一份。

    修之前：`run_gate(gid, ctx)` × 15 与 `GATES[gid]["criterion"]` 比对，一致 9 / 不一致 6；六道都取
    声明表并补齐实现缺的那块：G2 补「含通配符」+ 显式失败处置；G3 取"目标标签真实存在"（参考体例
    `draft/17-…md:1062` 逐字是"目标标签"，实现丢了"标签"这个受控词）；G4 补「卷内文件全被列出、
    字数在容差内」（缺的两档在 `criterion_revision` 里登记为"本项目对不上"）；G7 禁止『仅泛证』
    （参考体例 §8.4 逐字；`仅泛证型` 是别名）；G11 补「不二次编辑」（实现丢了参考体例 `:1070` 的
    第四个分句）；G15 补「缺失则退回」——`:1074` 的失败处置。另外每个 `gate_gN` 函数体原先各有
    一个 `criterion` 字面量，而 `_no_doc()` 用的又是函数内那份 ⇒ 同一门号在不同返回路径打印不同判据。
    这是真缺陷（FC-03）：与 `schema.py` 的"受控词表单一来源"、`cli.cmd_tools` 的"角色清单必须来自
    `ROLES`"同一条纪律；`gate_report` 写进报告的 `criterion` 与声明表不能是两份。期望每个门只从声明
    表取（`criterion = GATES[gate_id]["criterion"]`），取值那一句必须唯一（`_no_doc()` 与各条 `return` 都读它）。"""
    ctx = _frozen_ctx(ws)
    mismatched: dict[str, tuple[str, str]] = {}
    for gid in G.GATE_IDS:
        r = G.run_gate(gid, ctx)
        declared = G.GATES[gid]["criterion"]
        if r.criterion != declared:
            mismatched[gid] = (declared, r.criterion)
    assert mismatched == {}, f"{len(mismatched)} 道门的 criterion 与声明表不一致：{mismatched}"


def test_gate_criterion_revision_texts_are_a_single_source(ws: Path):
    """反漂移（单一来源，缺陷 G-12）：15 道门的 `GateResult.criterion_revision`
    逐字等于声明表 `GATE_CRITERIA_REVISION[gid]` —— 两条返回路径都算；`GATE_CRITERIA_REVISION` 修前在
    运行期从未被读到（`gates.py` 唯一用处 `if _gid not in GATE_CRITERIA_REVISION` 键检查），真值来自
    函数体字面量；第三份是 `GateResult` 的默认值 `"逐字照搬 §8.4"`：没传 `criterion_revision=` 的返回
    路径都打印它（14 门的 `_no_doc`，`G13` 不走，+ 10 个"缺某项输入"分支如 `G1`/`G6` 无 `workspace_root`、
    `G8`、`G9`、`G10`、`G11`、`G15`，共 24 条）；探针 `temp/probe_g12_baseline.py` 修前 15 / 15 不一致，
    修完 210 个 (门, 输入档) 组合 0 处不一致。
    逐门裁决：多数取实现（带 §8.3/§8.5 出处与"为什么"），少数两份互补合成；G6 只核
    `numeric_evidence.script`、G14 的 `main_body_claims` 同判据。G10 是核心：`unknown` 侧管
    `line`/`verbatim_quote`/`minimal_fix`/`maths` 缺失（`schema.ReviewFinding` 早先没有这四字段，
    `P-9` 补上，`X-96.3-3`；证据 `test_gate_g10_is_unknown_when_a_finding_lacks_the_four_fields`），
    逐字侧管六字段齐全按 §8.4 判（`test_gate_g10_accepts_a_conforming_finding_list` / `test_gate_g10_rejects_an_overlong_verbatim_quote`）⇒ 合成一句。"""
    ctx = _frozen_ctx(ws)
    no_doc_ctx = G.GateContext.build(None)
    mismatched: dict[str, tuple[str, str]] = {}
    for gid in G.GATE_IDS:
        declared = G.GATE_CRITERIA_REVISION[gid]
        for label, c in (("全输入齐", ctx), ("doc=None（_no_doc 路径）", no_doc_ctx)):
            got = G.run_gate(gid, c).criterion_revision
            if got != declared:
                mismatched[f"{gid}/{label}"] = (declared, got)
    assert mismatched == {}, (
        f"{len(mismatched)} 处 criterion_revision 与 GATE_CRITERIA_REVISION 不一致：{mismatched}"
    )


def test_gate_criteria_revision_table_is_read_not_merely_key_checked(
    ws: Path, monkeypatch: pytest.MonkeyPatch
):
    """"声明表真的被读到"（G-12 的第 4 条要求）：把表里的值换成哨兵 ⇒ 报告必须跟着换。

    为什么选"动态哨兵"而不是"源码里出现在取值位置"：① 它判的是运行期事实 —— 报告里那句
    `criterion_revision` 到底从表里取，还是从别处（函数体字面量 / `GateResult` 的默认值）来；
    ② 静态做法更弱：一句没人用的死代码（`_ = GATE_CRITERIA_REVISION[gid]`）或"读了却不用"的
    取值都能让它过，而哨兵不能造假（注入什么，报告里就必须出现什么）；③ 单纯的"逐字相等"也不够
    （那是上一条）：把表里的文本抄回函数体的实现能让它全绿而表已经是死的，哨兵试验对它必红。
    两条合起来才是"文本一致" + "来源唯一"。

    覆盖两条路径：全输入齐 + `doc=None`（`_no_doc` 那条）；修之前 `_no_doc` 打印 `GateResult` 的
    默认值 `"逐字照搬 §8.4"` ⇒ 15 门在哨兵试验下全红。哨兵用 `monkeypatch.setitem` 原地注入、
    teardown 还原，断言只比返回值；`GATE_CRITERIA_REVISION` 的读法在 `gates.py` 里，不改文件。"""
    ctx = _frozen_ctx(ws)
    no_doc_ctx = G.GateContext.build(None)
    misses: list[tuple[str, str, str, str]] = []
    for gid in G.GATE_IDS:
        sentinel = f"哨兵：{gid} 的判据修订状态（测试注入，只在本条断言的生命期内存活）"
        monkeypatch.setitem(G.GATE_CRITERIA_REVISION, gid, sentinel)
        for label, c in (("全输入齐", ctx), ("doc=None", no_doc_ctx)):
            r = G.run_gate(gid, c)
            if r.criterion_revision != sentinel:
                misses.append((label, gid, r.verdict, r.criterion_revision))
    assert misses == [], (
        "这些 (输入档, 门) 组合**没有读声明表**（照旧打印了函数体里的字面量或 "
        f"GateResult 的默认值）⇒ GATE_CRITERIA_REVISION 又变成死表了：{misses}"
    )


#: 反漂移扫描里允许出现的例外（门函数名 → 为什么需要动态拼 `criterion` /
#: `criterion_revision`）。目前为空，而且刻意留空：判据文本与判据修订状态都是
#: "这一门判什么、我们与参考体例差在哪"的声明，它们不该随输入变形 ——
#: 一份会随输入变形的"判据"无法被人核对。
#: 按函数名生效，同时覆盖两个字段（G-12 把扫描从 `criterion` 扩到两栏）。
CRITERION_LITERAL_EXCEPTIONS: dict[str, str] = {}


def test_no_gate_function_holds_a_second_criterion_or_revision_literal():
    """反漂移（AST 级）：`gate_g*` 函数体里不许再有第二份判据文本。

    三件事都是结构上的（与"跑一遍看输出"无关）：① `Assign` 的右值是字符串常量 ⇒ 又写了一份字面量
    （G-7 的 `criterion`、G-12 的 `criterion_revision` 一起扫）；② 把字面量直接当关键字实参传进
    `GateResult(...)` ⇒ "只在某一条 return 上生效的第二份文本"（G-10/G-12 的形状，正则抓不到、AST 能）；
    ③ `gate_g*` 里每个 `GateResult(...)` 必须传 `criterion_revision=`，否则 `GateResult` 的默认值会替
    这道门打印一句它没登记过的修订状态（修 G-12 前 14 门的 `_no_doc` + 10 个分支共 24 条返回路径漏了它）。

    为什么必需（"逐字相等"与哨兵试验都不够）：`GateResult.criterion_revision` 是运行时输出，只有走到
    某条 return 才被比对；把字面量写回去的函数只要抄对了今天照样过，下次改声明表就重新漂移 ——
    G-7 修好 `criterion` 后 G-12 立刻在同一形状上复发就是实证。用 `ast` 不用正则：正则会把注释与
    docstring 里的逐字引文一起误伤。例外通道 `CRITERION_LITERAL_EXCEPTIONS`（目前为空）；正控两处：必须真扫到 15 个 `gate_g*` 函数、且真数到 ≥15 个 `GateResult(...)` 构造点。"""
    import ast

    src = (Path(__file__).resolve().parents[1] / "src" / "agentflow" / "gates.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    #: 两个字段的唯一来源都是声明表 —— 扫描同时覆盖它们。
    guarded_fields = ("criterion", "criterion_revision")
    offenders_literal: list[tuple[str, int, str]] = []
    offenders_missing_kw: list[tuple[str, int]] = []
    scanned: list[str] = []
    scanned_other: list[str] = []
    gate_result_calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_gate = node.name.startswith("gate_g")
        if is_gate:
            scanned.append(node.name)
        elif node.name == "_no_doc":
            # `_no_doc` 也是"打印这两栏"的出口（`doc=None` 那条路径），一并扫。
            scanned_other.append(node.name)
        else:
            continue
        if node.name in CRITERION_LITERAL_EXCEPTIONS:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                targets = {t.id for t in sub.targets if isinstance(t, ast.Name)}
                hit = targets & set(guarded_fields)
                if hit and isinstance(sub.value, ast.Constant) and isinstance(sub.value.value, str):
                    offenders_literal.append((node.name, sub.lineno, sorted(hit)[0]))
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == "GateResult"
            ):
                gate_result_calls += 1
                kwargs = {kw.arg: kw for kw in sub.keywords}
                for field in guarded_fields:
                    kw = kwargs.get(field)
                    if (
                        kw is not None
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        offenders_literal.append((node.name, sub.lineno, field))
                if "criterion_revision" not in kwargs:
                    offenders_missing_kw.append((node.name, sub.lineno))
    # 正控（防"扫了个空"）：必须真的扫到 15 个门函数，否则下面的空结果毫无意义。
    assert len(scanned) == len(G.GATE_IDS), (
        f"只扫到 {len(scanned)} 个 `gate_g*` 函数（期望 {len(G.GATE_IDS)}）⇒ 扫描本身失效：{sorted(scanned)}"
    )
    assert scanned_other == ["_no_doc"], (
        f"没有扫到 `_no_doc`（它是 `doc=None` 那条路径的唯一出口，必须一起扫）：{scanned_other}"
    )
    assert gate_result_calls >= len(G.GATE_IDS), (
        f"只数到 {gate_result_calls} 个 `GateResult(...)` 构造点（期望 ≥ {len(G.GATE_IDS)}）⇒ 扫描本身失效"
    )
    assert offenders_literal == [], (
        "这些门函数里又写了第二份判据文本字面量"
        f"（两栏的唯一来源分别是 `GATES[*]['criterion']` 与 `GATE_CRITERIA_REVISION[*]`）：{offenders_literal}"
    )
    assert offenders_missing_kw == [], (
        "这些 `GateResult(...)` 没传 `criterion_revision=` ⇒ 会漏用 dataclass 默认值，"
        f"让一道适配过的门自称『逐字照搬』（G-12 的形状）：{offenders_missing_kw}"
    )


def test_run_gate_g13_runs_the_others_itself(ws: Path):
    """正向（特殊分支）：`G13` 需要 `results` 时，`run_gate` 自动先跑其余各门。

    docstring 逐字："跑单独一道门（`G13` 需要 `results` 时自动先跑其余各门）"。
    这条分支是 `run_gate` 里的一个 `if`，泛化循环覆盖不到"它真的把 results 传进去了"。
    """
    ctx = _frozen_ctx(ws)
    r = G.run_gate("G13", ctx)
    assert r.gate_id == "G13"
    assert r.verdict != "unknown", (r.verdict, r.reason)
    assert r.counts["检查的门数"] == len(G.GATE_IDS) - 1, r.counts


def test_run_all_gates_returns_every_gate_id_and_a_consistent_verdict(ws: Path):
    """正向：`run_all_gates` 覆盖全部 15 个门号，且总体判定与各门结论一致。

    断言打在判据上：不是"拿到了 15 个键"，而是"`gate_verdict` 的分档
    与逐门结论逐条对应"（fail 优先 → unknown → not_applicable → accepted）。
    """
    ctx = _frozen_ctx(ws)
    out = G.run_all_gates(ctx)
    assert tuple(out) == G.GATE_IDS, tuple(out)
    agg = G.gate_verdict(out)
    fails = [g for g, r in out.items() if r.verdict == "fail"]
    unknowns = [g for g, r in out.items() if r.verdict == "unknown"]
    if fails:
        assert agg["verdict"] == "rejected", agg
    elif unknowns:
        assert agg["verdict"] == "unverified", agg
    else:
        assert agg["verdict"] in ("accepted", "accepted_with_gaps"), agg
    assert agg["pass"] + agg["fail"] + agg["unknown"] + agg["not_applicable"] == len(G.GATE_IDS), agg


def test_run_all_gates_is_accepted_when_g10_sees_zero_findings(ws: Path):
    """正控（`R2b-AN-1` 的下游后果）：全绿的上下文 + `findings=[]` ⇒ 总体 `accepted`。

    守的是什么：`G10` 在 `findings == []` 时曾落 `not_applicable`（修前 `gate_g10` 那一句少了
    `all_findings and` 这半句守卫）。后果不在 `G10` 自己身上而在汇总表：`gate_verdict` 只要看见
    任何一个 `not_applicable` 就报 `accepted_with_gaps` ⇒ 一篇没有任何发现的稿件被读成"有门没判"。
    所以守卫必须打在下游：总体结论、`pass` 计数、`not_applicable_gates` 三者一起断言。

    为什么夹具要额外给禁词表：`G5` 的对象是词表，不给词表它判 `not_applicable`（三态纪律，不是缺陷），
    所以"15 门全绿"的上下文除 `_frozen_ctx` 之外还需要一份非空词表（正文不含该词 ⇒ `G5` 落 `pass`）；
    "缺词表就进不了全绿"由 `test_gate_g5_returns_not_applicable_without_a_word_list` 单独钉着。
    最后一个差分块把 `G10` 的结论改回修前那一档（`not_applicable`），断言总体判定与那三个数同时变 ——
    这就是"不是恒真"的证据：谁删掉 A1 的守卫，上面三条断言当场红，差值读出的正是红成什么样。"""
    ctx = _frozen_ctx(ws, banned_words=["显然"])
    assert ctx.findings == [], "夹具前提：这一份上下文里确实是零发现"
    out = G.run_all_gates(ctx)
    agg = G.gate_verdict(out)
    print("[R2b-AN-1 下游] 逐门 " + str({g: r.verdict for g, r in out.items()}))
    print(f"[R2b-AN-1 下游] 总体={agg['verdict']} pass={agg['pass']} "
          f"not_applicable_gates={agg['not_applicable_gates']}")
    assert out["G10"].counts["发现数"] == 0, out["G10"].counts
    assert out["G10"].verdict == "pass", (out["G10"].verdict, out["G10"].reason)
    assert agg["verdict"] == "accepted", agg
    assert agg["pass"] == len(G.GATE_IDS), agg
    assert agg["not_applicable_gates"] == [], agg

    degraded = {**out, "G10": dataclasses.replace(out["G10"], verdict="not_applicable")}
    agg_degraded = G.gate_verdict(degraded)
    print(f"[R2b-AN-1 下游 差分] 总体={agg_degraded['verdict']} pass={agg_degraded['pass']} "
          f"not_applicable_gates={agg_degraded['not_applicable_gates']}")
    assert agg_degraded["verdict"] == "accepted_with_gaps", agg_degraded
    assert agg_degraded["pass"] == len(G.GATE_IDS) - 1, agg_degraded
    assert agg_degraded["not_applicable_gates"] == ["G10"], agg_degraded


def test_run_all_gates_is_unknown_not_accepted_when_inputs_are_missing(ws: Path):
    """负控（全模块最重要的一条）：把所有可选输入都撤掉之后，
    总体判定绝不许是 `accepted`。

    为什么这是本文件的核心：15 道门里有 6 道（G5/G8/G9/G10/G11/G12）在缺输入时
    该报 `unknown` / `not_applicable`。一个把"缺输入"折叠成 `pass` 的实现，
    在"全输入齐备"的夹具下与正确实现完全无法区分 —— 只有这条负控能分开它们。
    这正是 `draft/17` 的教训（"未报错被误读为无问题"）在本模块的可执行形式。
    """
    ctx = G.GateContext.build(_doc())          # 除 doc 之外什么都不给
    out = G.run_all_gates(ctx)
    agg = G.gate_verdict(out)
    assert agg["verdict"] != "accepted", agg
    assert agg["verdict"] != "accepted_with_gaps", agg
    # 至少 6 道门必须落在"没查成/无对象"这两档里。
    assert agg["unknown"] + agg["not_applicable"] >= 6, agg
    assert agg["pass"] < len(G.GATE_IDS), agg


def test_gate_verdict_rejects_an_empty_result_set_is_not_accepted():
    """负控（边界）：空结果集 ⇒ `accepted`，但这不是一个"没查"的合法输入。

    这条断言的是实测到的实现行为，而且我认为它是一个可疑的设计
    （零门在场 ⇒ "全 pass" ⇒ `accepted`）。它被登记进 `docs/PROPOSALS.md` 的
    G-5 条，而不是在这里被改成"我觉得应该的样子" —— 我的任务是暴露缺陷，
    不是改 `src`。

    所以这条测试的作用是把这个可疑行为钉在纸上：一旦有人修它，
    这条会红，提醒他同时更新 G-5 的登记。
    """
    agg = G.gate_verdict({})
    assert agg["verdict"] == "accepted", agg
    assert agg["pass"] == 0 and agg["fail"] == 0 and agg["unknown"] == 0, agg
