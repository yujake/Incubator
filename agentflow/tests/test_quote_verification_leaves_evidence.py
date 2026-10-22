"""D1/D2 的判据：回验必须落「可复核的证据」，命题正文只能有一个真身。

真机读数（`D:\\Incubator\\saxl-ws\\data\\statements.json`，2026-10-22 本批修复前）：
8 条命题 `quote_verified=true` / `quote_mode=verbatim`，而 `quote_span` / `quote_reason` /
`quote_call_sha256` 三栏全空；13 条命题 `statement_text` 长度 0、`statement_full` 有正文。
于是"逐字回验通过"这句话在盘上没有任何可复核的读数（D1），正文有两个字段而只有一个有字（D2）。

六条判据（全部 tmp、零模型调用）：
1. 逐字命中 ⇒ `quote_verified=true` ＋ `quote_span` 非空 ＋ reason 可读（并且这四栏真的落盘）；
2. 引文不在那一页 ⇒ `false` ＋ reason 点名页码（不是空串）；
3. 无全文 / 抽取失败 ⇒ unknown 档（既不是 true 也不是 false），理由可读；
4. 盘上历史行（`quote_verified=true` 而 span 与 reason 全空）⇒ 判据要红（钉住基线脏数据）；
5. `statement_full` 非空而 `statement_text` 为空 ⇒ 红（D2 的写入侧），且读侧回退顺序可读；
6. 反真空：把"必须落 span"那条断言 monkeypatch 掉 ⇒ 判据 1 的核心断言必红。
"""
from __future__ import annotations

import pathlib

import pytest

#: 真机里逐字命中的那一句（`tests/test_agent_b_gates.py` 用的是同一句）。
QUOTE = "The distance is the number of walls crossed."


class _Doc:
    """`quoteverify.check_quote` 认的最小文档替身（有 `pages`、可选"不可读页"）。"""

    def __init__(self, pages: list[str], *, unreadable: bool = False) -> None:
        self.pages = list(pages)
        self._unreadable = bool(unreadable)

    def page_unreadable(self, start: int | None, end: int | None) -> bool:
        """`[start, end]` 里有没有抽取失败的页（本替身只有一个开关）。"""
        return self._unreadable


def _pages_with_quote() -> list[str]:
    return ["第一页：与这一句无关的正文。", "第二页：" + QUOTE + " 这一句之后还有别的字。"]


# --------------------------------------------------------------------- 判据 1

def test_a_verbatim_hit_leaves_a_span_and_a_readable_reason(tmp_path: pathlib.Path):
    """逐字命中：四栏都落地，而且这四栏能过秘书那一层真的写进台账。

    为什么两句都判：`quote_span` 曾经在秘书那一层被静默丢掉（`_statement_from` 只搬了
    `quote_verified` / `quote_reason`）⇒ 生产方算出了 span 也到不了盘上。
    """
    from agentflow import quoteevidence as QE
    from agentflow.schema import PageRange

    out = QE.verify_quote_evidence(doc=_Doc(_pages_with_quote()), quote=QUOTE,
                                   page_range=PageRange(2, 2, "p. 2"), field="proof_text")
    assert out["quote_verified"] is True, out
    assert out["quote_mode"] == "verbatim", out
    assert str(out["quote_span"]).strip(), ("逐字命中必须有区间（核了哪一段、在第几页）："
                                            f"{out}")
    assert "p2" in out["quote_span"], out
    assert "命中" in out["quote_reason"], out
    assert out["quote_call_sha256"] == "", out
    assert "没有模型调用" in out["quote_reason"], out

    from agentflow.secretary import Secretary
    from agentflow.store import Store

    ws = tmp_path / "d1ws"
    st = Store(ws)
    st.init()
    sec = Secretary("B", root=st.root, store=st)
    got = sec.record_statement(
        {"statement_full": "设 G 是有限群；则 G 的阶有限。", "origin": "own_result",
         "kind": "theorem", "doc_id": "000000", "proof_text": "证明：由定义直接得到。",
         "quote_verified": out["quote_verified"], "quote_mode": out["quote_mode"],
         "quote_span": out["quote_span"], "quote_call_sha256": out["quote_call_sha256"],
         "quote_reason": out["quote_reason"]},
        role="B")
    assert got.get("created"), got
    row = dict(st.rows("statements")[0])
    assert row.get("quote_span") == out["quote_span"], (
        "秘书那一层把 quote_span 丢了：生产方算出的区间到不了盘上", row)
    assert row.get("quote_mode") == "verbatim", row


def tmpdir_factory_root(out: dict) -> str:
    """给判据 1 的第二半一个临时根（`tmp_path` 在函数里拿不到时用它兜底）。"""
    import tempfile

    base = out.get("_root") or tempfile.mkdtemp(prefix="d1-evidence-")
    return str(base)


# --------------------------------------------------------------------- 判据 2

def test_a_quote_that_is_not_on_that_page_is_false_with_a_named_reason():
    """引文不在声明的那一页（全篇也没有）⇒ `false` ＋ reason 点名页码。"""
    from agentflow import quoteevidence as QE
    from agentflow.schema import PageRange

    out = QE.verify_quote_evidence(
        doc=_Doc(["第一页只有无关的正文，没有那句引文。"]), quote=QUOTE,
        page_range=PageRange(1, 1, "p. 1"), field="quote")
    assert out["quote_verified"] is False, out
    assert str(out["quote_reason"]).strip(), ("不通过必须给可操作的 reason："
                                             "缺页码 / 引文不在那一页 / 归一化后仍不匹配", out)
    assert "不在" in out["quote_reason"] and "1" in out["quote_reason"], out
    assert out["quote_span"] == "", out
    assert "模型调用" in out["quote_reason"], out


# --------------------------------------------------------------------- 判据 3

def test_no_text_layer_or_an_unreadable_page_is_unknown_not_false():
    """没查成（无全文 / 抽取失败的页）⇒ unknown 档：既不是 true 也不是 false。"""
    from agentflow import quoteevidence as QE
    from agentflow.schema import PageRange

    no_text = QE.verify_quote_evidence(doc=_Doc([]), quote=QUOTE,
                                       page_range=PageRange(1, 1, "p. 1"), field="quote")
    assert no_text["quote_verified"] is None, no_text
    assert no_text["quote_mode"] == "", no_text
    assert "没有可读文本" in no_text["quote_reason"], no_text
    assert no_text["quote_span"] == "", no_text

    unreadable = QE.verify_quote_evidence(doc=_Doc(["第一页有字但没有那一句。"], unreadable=True),
                                          quote=QUOTE, page_range=PageRange(1, 1, "p. 1"),
                                          field="quote")
    assert unreadable["quote_verified"] is None, unreadable
    assert "抽取失败" in unreadable["quote_reason"], unreadable
    assert unreadable["quote_verified"] is not False, (
        "读不到那一页不等于引文不存在（把 false 判给一条真引文是最贵的方向）", unreadable)


# --------------------------------------------------------------------- 判据 4

def test_a_historical_row_that_says_verified_without_any_evidence_is_red():
    """基线脏数据要钉住：`quote_verified=true` 而 span 与 reason 全空的行必须被点名。"""
    from agentflow import quoteevidence as QE

    historical = {"stmt_id": "000000", "quote_verified": True, "quote_mode": "verbatim",
                  "quote_span": "", "quote_reason": "", "quote_call_sha256": ""}
    got = QE.scan_quote_evidence([historical])
    assert got["checked"] == 1, got
    assert got["dirty"], ("盘上说'逐字回验通过'而没有任何区间/理由的行必须被点名，"
                          "不许当成通过放过")
    assert got["dirty"][0]["id"] == "000000", got
    assert "span" in got["dirty"][0]["why"], got

    clean = dict(historical, quote_span="p2:norm[4:44]",
                 quote_reason="逐字命中（归一化后 substring_match）")
    assert QE.scan_quote_evidence([clean])["dirty"] == [], "干净的行不许被误报（反真空）"
    # `quote_verified` 不是 true 的行不进这一档：没通过/没查成的行本来就没有区间。
    assert QE.scan_quote_evidence([dict(historical, quote_verified=None)])["dirty"] == []


# --------------------------------------------------------------------- 判据 4 的写侧那一半

def test_the_write_side_does_not_land_a_verified_without_any_evidence(tmp_path: pathlib.Path):
    """写侧断言：`quote_verified=True` 而 span 与 reason 全空 ⇒ 落盘时降成 unknown。

    这一条钉的是真机的形状本身（8 条命题 `quote_verified=true` / `quote_mode=verbatim`
    而三栏全空）：它不是"历史数据脏"，而是"写入口允许这么写"。走生产写入侧
    （`B.register_statement` → 秘书），落到盘上的那一行必须是 unknown 档，
    并且理由说得出为什么。
    """
    from agentflow.agent_b import AgentB
    from agentflow.store import Store

    ws = tmp_path / "d1exit"
    st = Store(ws)
    st.init()
    b = AgentB(st, extractor=None, extract_text=None, config={})
    out = b.register_statement(
        statement_full="设 G 是有限群；则 G 的阶有限。", origin="own_result",
        kind="theorem", doc_id="000000", proof_text="证明：由定义直接得到。",
        quote_verified=True)
    assert out.get("ok") is True, out
    row = next(r for r in st.rows("statements") if r["stmt_id"] == out["stmt_id"])
    assert row.get("quote_verified") is None, (
        "说'逐字通过'却给不出区间也给不出理由 ⇒ 盘上不许留下一个 true", row)
    assert row.get("quote_mode") == "", row
    assert "unknown" in str(row.get("quote_reason") or ""), row
    assert out["quote_evidence"]["action"] == "downgrade", out


# --------------------------------------------------------------------- 判据 5

def test_full_without_a_text_is_red_and_the_read_side_falls_back_to_full(tmp_path: pathlib.Path):
    """D2：正文只有一个真身。写入侧不许留下"full 有字、text 空"的行，读侧要有回退顺序。"""
    from agentflow.secretary import Secretary
    from agentflow.store import Store

    ws = tmp_path / "d2ws"
    st = Store(ws)
    st.init()
    sec = Secretary("B", root=st.root, store=st)
    full = "设 G 是有限群；则 G 的阶整除 |G|。"
    got = sec.record_statement(
        {"statement_full": full, "origin": "own_result", "kind": "theorem",
         "doc_id": "000000", "proof_text": "证明：拉格朗日。", "quote_verified": None,
         "quote_reason": "这一条还没做逐字比对（没有第二份文本可比）"},
        role="B")
    assert got.get("created"), got
    row = dict(st.rows("statements")[0])
    assert str(row.get("statement_full") or "").strip() == full, row
    assert str(row.get("statement_text") or "").strip(), (
        "statement_full 有正文而 statement_text 为空 ⇒ 红（正文有两个字段，"
        "读侧读哪个都能给出另一种答案）", row)

    from agentflow import statementbody as SB

    assert SB.body_of(row) == full, row
    assert SB.text_gaps([row]) == [], SB.text_gaps([row])

    # 老数据兼容：盘上那 13 行 `statement_text` 是空的，读侧必须读得出正文（不是空命题）
    legacy = {"stmt_id": "000012", "statement_full": "老数据的正文，只在 full 里。",
              "statement_text": ""}
    assert SB.body_of(legacy) == "老数据的正文，只在 full 里。", legacy
    assert SB.text_gaps([legacy]), "老行必须进脏清单（钉住基线，不许静默放过）"


# --------------------------------------------------------------------- 判据 6

def test_without_the_span_gate_criterion_one_goes_red(monkeypatch):
    """反真空：把"必须落 span"那条断言摘掉 ⇒ 判据 1 的核心断言必红。

    这一条是给判据 1 做的负控：它证明判据 1 不是恒真的（span 的唯一产出点就是那道断言）。
    """
    from agentflow import quoteevidence as QE
    from agentflow.schema import PageRange

    def _passthrough(fields, **kwargs):
        """把断言换成"什么都不做"：字段原样返回、判决恒 ok。"""
        return dict(fields), {"ok": True, "action": "keep", "why": "被 monkeypatch 掉了"}

    monkeypatch.setattr(QE, "enforce_quote_evidence", _passthrough)
    out = QE.verify_quote_evidence(doc=_Doc(_pages_with_quote()), quote=QUOTE,
                                   page_range=PageRange(2, 2, "p. 2"), field="proof_text")
    with pytest.raises(AssertionError):
        assert str(out["quote_span"]).strip(), (
            "断言被摘掉之后 span 必须为空 —— 否则判据 1 自己就是真空的")


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))
