# -*- coding: utf-8 -*-
"""判据：引文占位不是欠签（业主 2026-11-14「引文收录阶段的 V 签由引文占位」）。

## 现场（真机 `projects/lp-ball`，只读取证）

42 行里 4 条 b-proof（73–115 字的引文转述：`000032` 73 / `000034` 115 / `000035` 80 /
`000036` 103）都是 `origin=external_lit` + `source_lit_id=000000` + `quote_verified=true`
+ 非空 `quote_span`，`bits.evidence.reviewed_source="citation"`（凭据
`{"evidence": "lit:000000"}` = V 签位填的是文献编号），而 `bits.reviewed=false`。
`closing.statements_unsigned_reading` 却把它们读成 `never_submitted` ⇒ 收工门卡住。

## 四条判据

| # | 造什么 | 期望 |
|---|---|---|
| a | 引文占位行（无真签） | 不进 `rows` / `count`；`cited_placeholder_count`=1；`by_class` 空（不与真签/欠签混算） |
| b | 同形行、但去掉占位标记（负控不许放宽） | 仍进 `rows`、`class=never_submitted` |
| c | 反真空：把占位读口 `_cited_placeholder_reading` 打桩成"不是占位" | a 必须红（行重新进 `count`） |
| d | 占位行 + 真签 | 真签赢：既不进 `rows` 也不进 `cited_placeholder` |

## 为什么"占位"只认 `reviewed_source`

占位签与真签在同一格（`bits.evidence.reviewed_source`）：写侧 `evidencebits.bits_of` 与
读侧 `evidencebits._citation_review_cleared` 都只落 `citation` / `v` 两个值，认签口
（`register_statement` / `secretary.record_statement`）在真签落地时把它改成 `v`。
所以本判据不另写"像不像引文占位"的第二份判断。
"""
from __future__ import annotations

import pathlib

from agentflow import closing as CL
from agentflow import evidencebits as EB
from agentflow import vsigns as VS
from agentflow.store import Store

TS = "2026-11-14T20:00:00+08:00"
#: 真机那 4 条里最短的一条（73 字）同形：一段逐字转述，不是证明过程。
PROOF = ("设 K 是中心对称凸体，则其任意截面的最大体积不超过中心截面；"
         "原文给出的理由是对每一族平行平面取凹函数的最大值。")
FULL = "中心对称凸体的截面最大值在过中心的平面上取到。"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store, sid: str = "000032", *, placeholder: bool = True,
         proof: str = PROOF) -> dict:
    """一条引文命题：`placeholder=True` 时 bits 与真机那 4 条逐格同形。"""
    if placeholder:
        bits = EB.bits_of(origin="external_lit", source_lit_id="000000",
                          quote_verified=True, proof=True, kind="conjecture")
        origin, lit = "external_lit", "000000"
        quote = {"quote_verified": True, "quote_mode": "verbatim",
                 "quote_span": "p1:norm[570:650]"}
    else:
        bits = EB.bits_of(kind="conjecture")
        origin, lit, quote = "own_result", "", {"quote_verified": None}
    row = {
        "stmt_id": sid, "origin": origin, "kind": "conjecture",
        "label": f"引文命题 {sid}", "statement_full": FULL, "statement_text": FULL,
        "proof_text": proof, "status": "active",
        "proof_no": 1, "created_at": TS, "created_by": "test", "bits": bits,
        "quote_reason": ("夹具：逐字转述自 lit:000000（占位签）" if placeholder
                         else "夹具：自产命题，没有引文要核"),
        **quote,
    }
    if lit:
        row["source_lit_id"] = lit
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _unsigned(st: Store) -> dict:
    return CL.statements_unsigned_reading(st, now="2026-11-14T21:00:00+08:00")


# ------------------------------------------------------------------ a 占位 ⇒ 不欠签
def test_a_cited_placeholder_is_not_counted_as_unsigned(tmp_path: pathlib.Path) -> None:
    """a：占位签不是欠签 —— 不进 `rows`/`count`，单列 `cited_placeholder`。"""
    st = _ws(tmp_path)
    _put(st)
    got = _unsigned(st)
    assert got["checked"] is True, got
    assert got["scanned"] == 1, got          # 反真空：这一行真的被扫到了
    assert got["count"] == 0, got
    assert got["rows"] == [], got
    assert got["by_class"] == {}, got["by_class"]
    assert got["cited_placeholder_count"] == 1, got
    one = got["cited_placeholder"][0]
    assert one["stmt_id"] == "000032", one
    assert one["class"] == "cited_placeholder", one
    assert one["proofs"][0]["class"] == "cited_placeholder", one["proofs"]
    assert "引文占位" in one["why"], one["why"]
    assert "cited_placeholder" in got["reason"], got["reason"]
    # 它也不与"稿上已签、册里没收录"混算
    assert got["pending_filing_count"] == 0, got


# ------------------------------------------------------------------ b 负控：没占位照旧欠签
def test_b_without_the_placeholder_it_still_counts_as_unsigned(
        tmp_path: pathlib.Path) -> None:
    """b（负控不许放宽）：同形行去掉占位标记 ⇒ 仍进 `rows`、`class=never_submitted`。"""
    st = _ws(tmp_path)
    _put(st, sid="000033", placeholder=False)
    got = _unsigned(st)
    assert got["scanned"] == 1, got
    assert got["count"] == 1, got
    assert got["by_class"] == {"never_submitted": 1}, got["by_class"]
    assert got["cited_placeholder_count"] == 0, got
    assert got["rows"][0]["stmt_id"] == "000033", got["rows"]


# ------------------------------------------------------------------ c 反真空：读口一空就红
def test_c_stubbing_the_placeholder_read_sending_it_back_to_unsigned(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c：把占位读口打桩成"不是占位" ⇒ a 必须红（行重新进 `count`）。"""
    st = _ws(tmp_path)
    _put(st)

    def _no_placeholder(row, *_a, **_k):
        return {"checked": True, "placeholder": False, "reviewed_source": "",
                "evidence": "", "why": "夹具：占位读口打桩成空"}

    monkeypatch.setattr(CL, "_cited_placeholder_reading", _no_placeholder)
    got = _unsigned(st)
    assert got["count"] == 1, got
    assert got["by_class"] == {"never_submitted": 1}, got["by_class"]
    assert got["cited_placeholder_count"] == 0, got


# ------------------------------------------------------------------ d 真签赢过占位
def test_d_a_real_sign_wins_over_the_placeholder(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """d：占位行真拿到签 ⇒ 既不进欠签、也不进占位那一档（占位不覆盖一次真审）。"""
    st = _ws(tmp_path)
    _put(st)

    def _signed(*_a, **_k):
        return {"checked": True, "state": "signed", "filed": True,
                "why": "夹具：真签复算通过"}

    monkeypatch.setattr(VS, "sign_reading", _signed)
    got = _unsigned(st)
    assert got["count"] == 0, got
    assert got["cited_placeholder_count"] == 0, got
