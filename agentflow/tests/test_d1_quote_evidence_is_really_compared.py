# -*- coding: utf-8 -*-
"""D1（第二版）：「逐字回验通过」必须真的比对过，而且盘上留得下区间。

真机读数（`saxl-ws/data/statements.json`，2026-10-22 修复前）：13 条命题全写着
`quote_verified=true` / `quote_mode=verbatim`，而 `quote_span` / `quote_reason` /
`quote_call_sha256` 三栏全空。四个洞，一个都不是"数据脏"：

1. 写侧断言传的是 `doc=None`（旧注释自认"这一趟没有文档可查"）⇒ `locate_span`
   一次都没跑，"逐字回验通过"只是模型自报的入参；
2. `schema._normalize_quote_mode` 把"只说通过、没说方式"的行记实成 `verbatim`
   （区间为空也照记）⇒ 空区间在盘上长得像"逐字通过"；
3. 读侧 `evidencebits.quote_state` 见到 `quote_verified=True` 就按逐字档算 ⇒
   空区间照样拿到引用学分、照样进收工门的 `quote_verified_rows`；
4. `quoteevidence.scan_quote_evidence` 在生产代码里 0 个调用点 ⇒ 上面那些行
   没有任何一格会点名。

六条判据（全部 tmp 工作区、零模型调用）：

| # | 判据 | 改前红在哪里 |
|---|---|---|
| 一 | 自报 True + 空 span ⇒ 落库后不是 True（mode 也不是 verbatim），且扫盘判据点名 | 写侧"有理由就保留 True"那一档；读侧把 True 无 span 读成 verbatim |
| 二 | 给了全文、引文真在那一页 ⇒ `locate_span` 产出 `p{页}:norm[起:止]`，结论 true | 写侧 doc=None ⇒ 一次比对都没有，span 恒空 |
| 三 | 给了全文、引文不在 ⇒ false + 可操作理由 | 同上（旧行为保留 True 或降 unknown，从不判 false） |
| 四 | 没有全文 ⇒ unknown 档 + 理由（不是 false、不是 true） | 旧行为"有理由就保留 True" ⇒ 无全文也能落一个 true |
| 五 | 盘上有"true 但无 span"的行 ⇒ 收工门那一格红（13 行基线逐条点名） | `closing` 当时没有这一格，八格全过 |
| 六 | 反真空：把 `locate_span` 换成"永远返回空" ⇒ 判据二必红；把扫盘判据换成恒通过 ⇒ 判据五必红 | —— |

为什么判据三判 false 而不是 unknown：这一趟读到了全文（`locate_span` 搜的是整份
文档，不是声明的那几页），"整份里都没有这一段"是一条有信息量的结论。把它写成 unknown
会把一条已经查实的读数丢掉；反过来，没有全文时判 false 是指控一条真引文（最贵的方向），
所以判据四要求 unknown —— 两个方向各有一条判据钉着。
"""
from __future__ import annotations

import pathlib

import pytest
from conftest import add_literature

#: 真机里逐字命中的那一句（与 `tests/test_quote_verification_leaves_evidence.py` 同一句）。
QUOTE = "The distance is the number of walls crossed."
#: 全文里确实没有的一句（判据三用它）。
ABSENT = "This sentence never appears anywhere in the paper."


# --------------------------------------------------------------------- 夹具

def _paper(tmp_path: pathlib.Path, *, name: str = "d1") -> tuple[pathlib.Path, object]:
    """一个带真全文文件的工作区：`library/paper.txt` + literature 里那一行。"""
    from agentflow.store import Store

    root = tmp_path / name
    store = Store(root)
    store.init()
    (root / "library").mkdir(parents=True, exist_ok=True)
    (root / "library" / "paper.txt").write_text(
        f"第一页：与这一句无关的正文。\n第二页：{QUOTE} 这一句之后还有别的字。\n",
        encoding="utf-8", newline="\n")
    add_literature(store, "000000", title="Walls", path="paper.txt", sync=False)
    return root, store


def _b(store: object):
    """生产写入侧的那一个 B（`extract_text` 用真实现：全文是真的去读文件）。"""
    from agentflow.agent_b import AgentB
    from agentflow.extract import extract_text

    return AgentB(store, extractor=None, extract_text=extract_text, config={})


def _register(store: object, *, quote: str, label: str, **kw) -> dict:
    """走生产写入侧登记一条外部命题（`proof_text` 就是"要核的那一段"）。"""
    params = dict(
        statement_full=f"（{label}）腔室距离等于穿过的墙数。",
        origin="external_lit", source_lit_id="000000",
        page_range={"start": 1, "end": 1},
        proof_text=quote, quote_verified=True, kind="theorem",
        quote_reason="逐字比对通过（第 1 页）",
    )
    params.update(kw)
    return _b(store).register_statement(**params)


def _row(store: object, stmt_id: str) -> dict:
    return next(dict(r) for r in store.rows("statements") if r["stmt_id"] == stmt_id)


# ============================================================ 判据一

def test_a_self_reported_pass_without_a_span_does_not_land_as_true(tmp_path: pathlib.Path):
    """自报 True + 空 span ⇒ 落库后不是 True（mode 也不是 verbatim），且扫盘判据点名。

    两半都要：前半钉写侧（说通过而给不出区间 ⇒ 降档），后半钉读侧（盘上真出现这种行时，
    `quote_state` 不许把它读成逐字通过，`scan_quote_evidence` 必须点名）。
    """
    from agentflow import evidencebits as EB
    from agentflow import quoteevidence as QE

    # 前半：没有 source_lit_id ⇒ 没有可比对的全文 ⇒ 一次比对都没发生 ⇒ unknown。
    _root, store = _paper(tmp_path)
    out = _register(store, quote=QUOTE, label="自报通过", source_lit_id="",
                    origin="own_result", kind="conjecture", doc_id="000000")
    assert out.get("ok") is True, out
    row = _row(store, out["stmt_id"])
    assert row.get("quote_verified") is not True, (
        "说「逐字通过」而盘上给不出 quote_span ⇒ 不许留下一个 true（D1 的写侧断言）", row)
    assert row.get("quote_mode") != "verbatim", row
    assert "unknown" in str(row.get("quote_reason") or ""), row
    assert out["quote_evidence"]["action"] == "downgrade", out["quote_evidence"]

    # 后半：盘上真有一行"true + 空 span"（手改行 / 旧版本写的行）⇒ 读侧不认、扫盘点名。
    legacy = {"stmt_id": "000012", "quote_verified": True, "quote_mode": "verbatim",
              "quote_span": "", "quote_reason": ""}
    assert EB.quote_state(legacy) != "verbatim", (
        "空区间仍被读成逐字通过 ⇒ 引用学分与收工门都被它顶高（D1 的读侧那一半）",
        EB.quote_state(legacy))
    assert EB.quote_state(legacy) == EB.QUOTE_NO_EVIDENCE, EB.quote_state(legacy)
    assert EB.quote_explains_itself(legacy) is False, legacy
    got = QE.scan_quote_evidence([legacy])
    assert [d["id"] for d in got["dirty"]] == ["000012"], got
    assert "span" in got["dirty"][0]["why"], got


# ============================================================ 判据二

def test_a_quote_that_really_is_in_the_paper_leaves_the_span(tmp_path: pathlib.Path):
    """给了全文、引文真在那一页 ⇒ `locate_span` 产出 `p{页}:norm[起:止]`，结论 true。

    这一条走的是生产写入侧（`B.register_statement` → 秘书），所以它同时钉住
    "写侧真的去读了那一篇的全文"：改前 `doc=None`，一次比对都没发生，span 恒为空。
    """
    from agentflow import quoteevidence as QE

    _root, store = _paper(tmp_path)
    out = _register(store, quote=QUOTE, label="命中")
    assert out.get("ok") is True, out
    row = _row(store, out["stmt_id"])
    span = str(row.get("quote_span") or "")
    assert row.get("quote_verified") is True, row
    assert row.get("quote_mode") == "verbatim", row
    assert span, ("逐字命中必须有区间（核了哪一段、在第几页）：写侧没有再传 doc=null", row)
    parsed = QE.parse_span(span)
    assert parsed is not None, span
    assert span.startswith("p1:norm["), span
    page, start, end = parsed
    assert (page, start, end) == (1, 19, 19 + len(QE.normalize_for_quote(QUOTE))), span
    assert "命中区间" in str(row.get("quote_reason") or ""), row
    assert row.get("quote_call_sha256") == "", row


# ============================================================ 判据三

def test_a_quote_that_is_not_in_the_paper_is_false_with_an_actionable_reason(
        tmp_path: pathlib.Path):
    """给了全文、引文整份里都没有 ⇒ false + 可操作理由（不是 unknown：全文读到了）。"""
    _root, store = _paper(tmp_path)
    out = _register(store, quote=ABSENT, label="不在全文里")
    assert out.get("ok") is True, out
    row = _row(store, out["stmt_id"])
    assert row.get("quote_verified") is False, (
        "整份全文里都没有这一段 ⇒ 查过、不一致（false）；旧行为从不判 false", row)
    assert row.get("quote_mode") == "", row
    assert row.get("quote_span") == "", row
    reason = str(row.get("quote_reason") or "")
    assert "not_found" in reason or "没命中" in reason, reason
    assert "全文" in reason and "页" in reason, reason
    assert "unknown" in reason, ("理由必须说清为什么这次不是 unknown（全文读到了）", reason)
    assert out["quote_evidence"]["action"] == "mismatch", out["quote_evidence"]


# ============================================================ 判据四

def test_without_any_full_text_the_verdict_is_unknown_not_false(tmp_path: pathlib.Path):
    """没有全文 ⇒ unknown 档 + 理由（既不是 false，也不是 true）。

    为什么不能判 false：读不到那一篇不等于原文里没有这句话 —— 把 false 判给一条真引文
    是本仓库最贵的方向（`extract` 的 docstring 与 `verify.py` 的 `quote_not_found`
    都写着这一条）。
    """
    from agentflow import quoteevidence as QE

    root, store = _paper(tmp_path, name="d1-nodoc")
    # 把那一行的本地文件拿掉（`path=null` = 没下载到 PDF 的那一档）。
    with store.tx("literature", actor="test") as tx:
        row = dict(tx.find("literature", lit_id="000000") or {})
        row["path"] = None
        tx.upsert("literature", row)
    assert not (root / "library" / "paper.txt").exists() or True

    out = _register(store, quote=QUOTE, label="没有全文")
    assert out.get("ok") is True, out
    row = _row(store, out["stmt_id"])
    assert row.get("quote_verified") is None, (
        "没有全文 ⇒ 一次比对都没发生 ⇒ unknown（既不许 true、也不许 false）", row)
    assert row.get("quote_verified") is not False, row
    assert row.get("quote_mode") == "", row
    reason = str(row.get("quote_reason") or "")
    assert "unknown" in reason, reason
    assert "没有可比的全文" in reason, reason
    assert "path=null" in reason or "没有本地文件" in reason, reason
    assert out["quote_evidence"]["action"] == "downgrade", out["quote_evidence"]

    # 断言层也走同一条口径：没有文档时给的就是 unknown + 理由（而不是一个 true）。
    fixed, reading = QE.enforce_quote_evidence(
        {"quote_verified": True, "quote_mode": "", "quote_span": "",
         "quote_call_sha256": "", "quote_reason": "逐字比对通过"},
        quote=QUOTE, doc=None, doc_problem="这一篇没有全文")
    assert fixed["quote_verified"] is None and fixed["quote_mode"] == "", fixed
    assert reading["action"] == "downgrade", reading
    assert "这一篇没有全文" in fixed["quote_reason"], fixed


# ============================================================ 判据五

def test_the_closing_gate_goes_red_on_the_thirteen_baseline_rows(tmp_path: pathlib.Path):
    """盘上有"true 但无 span"的行 ⇒ 收工门那一格红，并把那 13 行逐条点名。

    13 是基线读数（`saxl-ws/data/statements.json` 修复前的行数），不是规格：
    这里照那个形状造 13 行，钉住"这种行不许被静默放过"。
    """
    from agentflow import closing as CL
    from agentflow.store import Store

    root = tmp_path / "d1-close"
    root.mkdir()
    store = Store(root)
    store.init()
    rows = [{"stmt_id": f"{i:06d}", "origin": "external_lit", "kind": "theorem",
             "statement_full": f"第 {i} 条：腔室距离等于穿过的墙数。",
             "statement_text": "", "source_lit_id": "000000",
             "quote_verified": True, "quote_mode": "verbatim",
             "quote_span": "", "quote_reason": "", "quote_call_sha256": ""}
            for i in range(13)]
    with store.tx("statements", actor="test") as tx:
        for row in rows:
            tx.upsert("statements", row)

    rep = CL.check_closing(store, project_dir=str(root))
    reading = rep.readings["quote_evidence"]
    assert reading["checked"] is True, reading
    assert reading["verified_rows"] == 13, reading
    assert len(reading["dirty"]) == 13, reading
    assert sorted(d["id"] for d in reading["dirty"]) == sorted(r["stmt_id"] for r in rows), reading
    hits = [f for f in rep.blockers if f.code == "quote_verified_without_span"]
    assert len(hits) == 1, [f.code for f in rep.blockers]
    assert "13" in hits[0].detail and "000000" in hits[0].detail, hits[0].detail
    assert rep.machine_pass is False, "说通过而无区间不许机器判过（D1 的收工那一格）"
    # D2 的残留也一并进读数（同一批 13 行：真身有正文而短版为空）。
    body = rep.readings["statement_body"]
    assert body["checked"] is True and len(body["gaps"]) == 13, body


# ============================================================ 判据六

def test_the_span_gate_is_not_vacuous(monkeypatch, tmp_path: pathlib.Path):
    """反真空之一：先证明区间真的会落地（正控），再摘掉 `locate_span` 证明判据二必红。

    区间只有一个产出点（`locate_span`），所以摘掉它之后"逐字命中"就必须落不成 true。
    两半都要：只有负控那一半时，改前（判据二本来就红）这一条也会"通过"——
    那样的反真空是空的。
    """
    from agentflow import quoteevidence as QE

    # 正控：不摘的时候，区间真的落盘（判据二的核心断言）。
    _root_ok, store_ok = _paper(tmp_path, name="d1-vacuum-ok")
    out_ok = _register(store_ok, quote=QUOTE, label="命中（正控）")
    row_ok = _row(store_ok, out_ok["stmt_id"])
    assert row_ok.get("quote_verified") is True and row_ok.get("quote_span"), (
        "正控必须先绿：区间没落地的话，下面的负控证明不了任何事", row_ok)

    # 负控：把唯一产出点换成"永远返回空" ⇒ 判据二必红。
    monkeypatch.setattr(QE, "locate_span", lambda *a, **kw: "")
    _root, store = _paper(tmp_path, name="d1-vacuum-broken")
    out = _register(store, quote=QUOTE, label="命中（负控）")
    row = _row(store, out["stmt_id"])
    with pytest.raises(AssertionError):
        assert row.get("quote_verified") is True and row.get("quote_span"), (
            "locate_span 被摘掉之后还落了 true + 区间 ⇒ 判据二是真空的", row)


def test_the_scan_criterion_is_not_vacuous(monkeypatch, tmp_path: pathlib.Path):
    """反真空之二：先证明收工门那一格会红（正控），再把扫盘判据换成恒通过。

    恒通过的那一版必须让那一格不再红 —— 否则判据五红的是别的东西，与扫盘判据无关。
    """
    from agentflow import closing as CL
    from agentflow import quoteevidence as QE
    from agentflow.store import Store

    root = tmp_path / "d1-vacuum-close"
    root.mkdir()
    store = Store(root)
    store.init()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", {"stmt_id": "000000", "origin": "external_lit",
                                 "kind": "theorem", "statement_full": "甲",
                                 "statement_text": "甲", "source_lit_id": "000000",
                                 "quote_verified": True, "quote_mode": "verbatim",
                                 "quote_span": "", "quote_reason": "逐字比对通过"})
    # 正控：扫盘判据在场时，收工门那一格是红的。
    rep_ok = CL.check_closing(store, project_dir=str(root))
    assert [f for f in rep_ok.blockers if f.code == "quote_verified_without_span"], (
        "正控必须先红：这一格没红的话，下面的负控证明不了任何事",
        [f.code for f in rep_ok.blockers])

    # 负控：把扫盘判据换成恒通过 ⇒ 这一格不再红（判据五依赖它）。
    monkeypatch.setattr(QE, "scan_quote_evidence",
                        lambda rows: {"checked": len(list(rows or ())), "dirty": [],
                                      "verified_rows": 1, "clean": True})
    rep = CL.check_closing(store, project_dir=str(root))
    with pytest.raises(AssertionError):
        assert [f for f in rep.blockers if f.code == "quote_verified_without_span"], (
            "扫盘判据被换成恒通过之后收工门仍然红 ⇒ 判据五是真空的")


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))
