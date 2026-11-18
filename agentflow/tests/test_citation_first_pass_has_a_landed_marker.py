# -*- coding: utf-8 -*-
"""判据：引文「第一遍摘录」必须是落盘标记，三处读数共用它（2026-11-18）。

## 现场（`temp/vplace1/VPLACE1-REPORT.md`，只读取证）

「引用占位签」不是签：它是 `statements` 行上的一个凭据档标记
（`bits.evidence.reviewed_source == "citation"`），写侧要求
`quote_verified is True`。于是：

- 缺口 (a)：引文没核成（`enforce_quote_evidence` 把 `quote_verified` 降成
  `None`）的第一遍摘录没有落盘标记 ⇒ 写闸（`register_statement.py`）与
  收工门（`agent_loop._sign_gate_b`）只看 `origin + source_lit_id` 就放行，
  而 `closing.statements_unsigned_reading` 把它记成 `never_submitted`（进
  `count`）⇒ 同一条行两套相反结论；
- 缺口 (b)：收工门的豁免是行级的、不看"这一份是不是第一遍载体" ⇒ 同一
  引文命题的第二遍改写 b-稿也在豁免里。

## 本文件钉的读法

「第一遍载体」是一个落盘标记（`statements` 行上的扩展键 `quote_carrier`，
不是 schema 字段），写侧在引文侧登记那一笔落（`first`），第二遍改写那一笔
覆盖成 `second`。三处读数都只读这一格（唯一判据
`evidencebits.quote_carrier_reading`）：

| 读口 | 第一遍载体 | 第二遍改写载体 |
|---|---|---|
| 写闸 `_unsigned_proof_gate` | 放行 | 要签（没签 ⇒ 拒） |
| 收工门 `_sign_gate_b` | 不报 problem | 报 problem |
| `closing.statements_unsigned_reading` | `cited_placeholder`（不进 `count`） | `never_submitted`（进 `count`） |

存量行（本改造之前落的）没有新标记：旧代码已经落盘的两格仍认 ——
`reviewed_source == "citation"`（第一遍逐字核过）读成第一遍；其余按"判不了"
处理（三处一致地欠签，宁可欠签不静默放过）。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | 第一遍摘录 + `quote_verified` 降成 `None` + 落盘标记 `first` | 写闸放行、收工门放行、读数记 `cited_placeholder` |
| b | 第二遍改写 b-稿 + 落盘标记 `second` | 三处都欠签（写闸拒 / 收工门报 problem / 读数进 `count`） |
| c | 同一条行在三处读数一致 | a 与 b 各是一张同向的真值表 |
| d | 负控：`own_result` 稿 / 普通 `external_lit`（第一遍逐字核过） | 行为不变 |
| e | 反真空：只把行上那一格落盘标记摘掉 | 收工门 / `closing` 必红（a 不再成立） |
| e2 | 反真空：把三处共用的唯一判据打桩成"从不是第一遍载体" | a 的三个读口全红 |
| f | 真登记一笔引文侧命题（逐字核不过） | 行上真的落了 `quote_carrier=first`；收工门放行、读数 `cited_placeholder` |
| g | 真跑第二遍优化重写 | 行上的标记被改写成 `second`（生产上真的有人写这一格） |
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
_TESTS = pathlib.Path(__file__).resolve().parent
for _path in (_SRC, _TESTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from agentflow import closing as CL  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow.agent_b.register_statement import _RegisterStatement  # noqa: E402
from agentflow.agent_loop import _sign_gate_b  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-11-18T10:00:00+08:00"
LIT = "000000"
SID = "000032"
MID = "000009"
REL = f"reports/b-proof-{MID}.md"
FULL = "中心对称凸体的截面最大值在过中心的平面上取到。"
#: 第一遍摘录（逐字引文）。
QUOTE = ("设 K 是中心对称凸体，则其任意截面的最大体积不超过中心截面；"
         "原文给出的理由是对每一族平行平面取凹函数的最大值。")
#: 第二遍改写（B 优化后的表述，不再是逐字引文）。
OPT = ("（B 优化后的表述）对中心对称凸体 K，任意方向的截面面积都不超过"
       "过中心那一刀；理由是把每一族平行截面的面积看成凹函数取极值。")
HISTORY = [{"text": QUOTE, "sha": "0" * 64, "at": TS, "replaced_by": "1" * 64}]


def _key() -> str:
    """落盘标记的键名（唯一出处是 `evidencebits`；本夹具不另写一份名字）。"""
    return str(getattr(EB, "QUOTE_CARRIER_KEY", "quote_carrier"))


def _mark(pass_: str, *, body: str, mid: str = MID, rel: str = REL) -> dict:
    """一条落盘标记（形状与写侧一致；夹具直铺行用）。"""
    make = getattr(EB, "quote_carrier_mark", None)
    if callable(make):
        return dict(make(pass_=pass_, manuscript_id=mid, manuscript=rel,
                         body=body, at=TS))
    return {"pass": str(pass_), "manuscript_id": mid, "manuscript": rel,
            "body_sha256": str(EB._sign_sha(body)), "at": TS}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _seed(st: Store, *, origin: str = "external_lit", marker: str | None = "first",
          quote_verified=None, proof_text: str = QUOTE, sid: str = SID,
          mid: str = MID, rel: str = REL, history=None,
          bits: dict | None = None) -> dict:
    """铺一行（三态同形真机：`statements` 行 + 稿号两格）。"""
    if bits is None:
        bits = EB.bits_of(origin=origin, source_lit_id=(LIT if origin == "external_lit" else ""),
                          quote_verified=quote_verified, kind="conjecture")
    row = {
        "stmt_id": sid, "origin": origin, "kind": "conjecture",
        "label": "引文命题", "statement_full": FULL, "statement_text": FULL,
        "proof_text": proof_text, "status": "active",
        "created_at": TS, "created_by": "test",
        "quote_verified": quote_verified,
        "quote_mode": ("verbatim" if quote_verified else ""),
        "quote_span": ("p1:norm[570:650]" if quote_verified else ""),
        "quote_reason": "夹具：引文核验读数（不是通过也要说清为什么）",
        "bits": bits,
        "manuscript_id": mid, "manuscripts": {"1": rel},
    }
    if origin == "external_lit":
        row["source_lit_id"] = LIT
    if marker is not None:
        row[_key()] = _mark(marker, body=proof_text, mid=mid, rel=rel)
    if history:
        row["proof_history"] = list(history)
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _write_gate(st: Store, *, row, body: str = QUOTE, origin: str = "external_lit") -> dict:
    return _RegisterStatement._unsigned_proof_gate(
        origin=origin, lit_id=(LIT if origin == "external_lit" else ""),
        proof_text=body, proofs_listed=[], row=row, v_sign={}, store=st,
        proof_no=1)


def _close_gate(st: Store, *, mid: str = MID, rel: str = REL) -> dict:
    out = {"problems": [], "checked": True, "complete": True}
    cands = {("b-proof", mid): {"signed": False, "manuscript": rel,
                                "state": "unsigned", "statement_id": ""}}
    _sign_gate_b(st, st.root, cands, out)
    return out


def _closing(st: Store) -> dict:
    return CL.statements_unsigned_reading(st, now="2026-11-18T11:00:00+08:00")


# ============================================================ a 第一遍摘录
def test_a_the_first_pass_excerpt_is_exempt_and_read_as_cited_placeholder(
        tmp_path: pathlib.Path) -> None:
    """a：`quote_verified=None` 的第一遍摘录 ⇒ 三处都认它是第一遍载体。"""
    st = _ws(tmp_path)
    _seed(st, marker="first", quote_verified=None)

    gate = _write_gate(st, row=None)          # 新命题的那一笔：还没有行
    assert gate.get("refused") == "", gate
    assert gate.get("applicable") is True, gate

    close = _close_gate(st)
    assert close.get("problems") == [], close
    assert close.get("checked") is True, close

    got = _closing(st)
    assert got.get("checked") is True, got
    assert got.get("count") == 0, got
    assert got.get("rows") == [], got
    assert got.get("by_class") == {}, got["by_class"]
    assert got.get("cited_placeholder_count") == 1, got
    one = got["cited_placeholder"][0]
    assert one["stmt_id"] == SID, one
    assert one["class"] == "cited_placeholder", one


def _row_of(st: Store, sid: str = SID) -> dict:
    return dict(next(r for r in st.rows("statements")
                     if str(r.get("stmt_id") or "") == sid))


def _as_second(st: Store, *, proof_text: str = OPT) -> dict:
    """把这一行改成"第二遍改写已经落盘"的状态（正文 + 落盘标记同一笔）。"""
    row = _row_of(st)
    row["proof_text"] = proof_text
    row[_key()] = _mark("second", body=proof_text)
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


# ============================================================ b 第二遍改写
def test_b_the_rewritten_second_pass_is_unsigned_everywhere(
        tmp_path: pathlib.Path) -> None:
    """b：第二遍改写 ⇒ 写闸要签；落盘之后收工门报 problem、读数进 `count`。"""
    st = _ws(tmp_path)
    _seed(st, marker="first", quote_verified=True)

    # ① 改写那一笔本身：行上还是第一遍（标记 first、正文是逐字引文），
    #    交来的正文已经换成优化后的那一版 ⇒ 这不是第一遍摘录 ⇒ 写闸要签。
    gate = _write_gate(st, row=_row_of(st), body=OPT)
    assert str(gate.get("refused") or "") == "proof_without_v_sign", gate
    assert gate["reading"]["quote_carrier"][0]["first_pass"] is False, gate["reading"]

    # ② 改写落地之后（标记 second）：收工门与读数都认它欠签。
    _as_second(st)
    close = _close_gate(st)
    assert close.get("problems"), close
    where = str(close["problems"][0].get("where") or "")
    assert MID in where, close["problems"]     # 点名的是这一份稿

    got = _closing(st)
    assert got.get("count") == 1, got
    assert got.get("by_class") == {"never_submitted": 1}, got["by_class"]
    assert got.get("cited_placeholder_count") == 0, got


# ============================================================ c 三处一致
def test_c_the_three_readings_agree_on_the_same_row(
        tmp_path: pathlib.Path) -> None:
    """c：同一行的三处读数同向（第一遍全放行，第二遍全欠签）。"""
    first = _ws(tmp_path / "first")
    _seed(first, marker="first", quote_verified=None)
    assert (_write_gate(first, row=None).get("refused") == ""
            and _close_gate(first).get("problems") == []
            and _closing(first).get("count") == 0
            and _closing(first).get("cited_placeholder_count") == 1), (
        "第一遍载体在三处读数上不一致")

    # 第二遍：改写那一笔（行上仍是第一遍）写闸要签；落盘之后收工门 / 读数欠签。
    second = _ws(tmp_path / "second")
    _seed(second, marker="first", quote_verified=True)
    assert _write_gate(second, row=_row_of(second), body=OPT).get("refused") != "", (
        "第二遍改写那一笔，写闸仍按行级 origin 放行")
    _as_second(second)
    assert (_close_gate(second).get("problems") != []
            and _closing(second).get("count") == 1
            and _closing(second).get("cited_placeholder_count") == 0), (
        "第二遍改写载体在三处读数上不一致")


# ============================================================ d 负控
def test_d_own_result_and_ordinary_external_lit_are_unchanged(
        tmp_path: pathlib.Path) -> None:
    """d：负控 —— `own_result` 稿 / 普通 `external_lit`（第一遍逐字核过）行为不变。"""
    own = _ws(tmp_path / "own")
    own_bits = EB.bits_of(kind="conjecture")
    _seed(own, origin="own_result", marker=None, quote_verified=None,
          proof_text=QUOTE, bits=own_bits)
    assert _write_gate(own, row=_row_of(own), body=OPT,
                       origin="own_result").get("refused") == "proof_without_v_sign"
    assert _close_gate(own).get("problems"), "own_result 的未签 b-稿不该被豁免"
    got = _closing(own)
    assert got.get("count") == 1 and got.get("cited_placeholder_count") == 0, got

    # 普通 external_lit：第一遍逐字核过。存量行（没有新标记）仍按旧的那一格
    # `reviewed_source=="citation"` 读成第一遍 —— 行为逐字不变。
    legacy = _ws(tmp_path / "legacy")
    _seed(legacy, marker=None, quote_verified=True)
    assert _close_gate(legacy).get("problems") == [], "存量占位行被误判成欠签"
    got = _closing(legacy)
    assert got.get("count") == 0 and got.get("cited_placeholder_count") == 1, got

    marked = _ws(tmp_path / "marked")
    _seed(marked, marker="first", quote_verified=True)
    assert _close_gate(marked).get("problems") == [], "落盘标记的第一遍被误判成欠签"
    got = _closing(marked)
    assert got.get("count") == 0 and got.get("cited_placeholder_count") == 1, got


# ============================================================ e 反真空
def test_e_removing_the_landed_marker_sends_the_first_pass_back_to_unsigned(
        tmp_path: pathlib.Path) -> None:
    """e：把行上的落盘标记摘掉 ⇒ a 必红（收工门改口欠签、读数重新进 count）。

    只摘行上那一格（不把正文 / 出处 / bits 动一个字）：这就是"① 的落盘标记
    是不是在承重"的负控。写闸那一档不受影响 —— 它问的是"新命题这一笔"
    （行还不存在，标记也还不存在），那一档的放行是结构性的；标记承重的是
    两条按行读的口（收工门 / closing）与第二遍改写那一笔。
    """
    st = _ws(tmp_path)
    row = _seed(st, marker="first", quote_verified=None)
    assert _close_gate(st).get("problems") == [], "夹具前提不成立：有标记时收工门就拦了"
    assert _closing(st).get("cited_placeholder_count") == 1, "夹具前提不成立"

    row.pop(_key(), None)
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)

    assert _close_gate(st).get("problems"), "摘掉标记之后收工门仍然放行 ⇒ 标记没有承重"
    got = _closing(st)
    assert got.get("count") == 1, got
    assert got.get("cited_placeholder_count") == 0, got


def test_e2_stubbing_the_single_criterion_flips_all_three_readings(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e2：把三处共用的唯一判据打桩成"从不是第一遍载体" ⇒ a 的三个读口全红。"""
    def _never_first_pass(*_a, **_k):
        return {"checked": True, "marked": False, "first_pass": False, "pass": "",
                "manuscript_id": "", "manuscript": "", "body_sha256": "",
                "why": "夹具：落盘标记读口被打桩成『从不是第一遍载体』"}

    monkeypatch.setattr(EB, "quote_carrier_reading", _never_first_pass)
    st = _ws(tmp_path)
    _seed(st, marker="first", quote_verified=None)

    assert _write_gate(st, row=None).get("refused") == "proof_without_v_sign", (
        "标记读口摘掉之后写闸仍然放行 ⇒ 写闸没有走这条判据")
    assert _close_gate(st).get("problems"), "标记读口摘掉之后收工门仍然放行"
    got = _closing(st)
    assert got.get("count") == 1, got
    assert got.get("cited_placeholder_count") == 0, got


# ============================================================ f 真登记会落标记
def _real_store(tmp_path: pathlib.Path) -> Store:
    st = _ws(tmp_path)
    (pathlib.Path(st.root) / "library").mkdir(parents=True, exist_ok=True)
    (pathlib.Path(st.root) / "library" / "paper.txt").write_text(
        "Preamble.\n" + QUOTE + "\n", encoding="utf-8", newline="\n")
    with st.tx("literature", actor="opt") as tx:
        tx.upsert("literature", {
            "lit_id": LIT, "title": "夹具文献", "type": "J", "summary": "夹具",
            "path": "paper.txt", "processed": True, "created_at": TS,
            "created_by": "opt"})
    return st


def _real_b(st: Store):
    from test_b_optimized_pass_is_not_verbatim_gated import _Seam

    from agentflow import secretary as SEC
    from agentflow.agent_b import AgentB

    sec = SEC.Secretary("B", root=st.root, store=st, seam=_Seam(), enable_model=True)
    return AgentB(st, extractor=None, extract_text=None, config={}, secretary=sec)


def test_f_a_real_citation_registration_writes_the_marker(
        tmp_path: pathlib.Path) -> None:
    """f：真跑一笔引文侧登记（逐字核不过）⇒ 行上真的落了 `quote_carrier=first`。"""
    st = _real_store(tmp_path)
    got = _real_b(st).register_statement(
        statement_full=FULL, statement_text="", kind="theorem", label="主定理",
        origin="external_lit", source_lit_id=LIT, page_range={"start": 1},
        quote_verified=True, quote_reason="夹具：这一句原文里没有 ⇒ 必被降档",
        proof_text="这一段原文里根本没有，是伪造的摘录（不是逐字）。")
    assert got.get("ok") is True, got
    # 换一个 Store 实例读盘：标记必须是真落盘的（不是同一进程内存里那一份）。
    row = dict(next(iter(Store(st.root).rows("statements"))))
    assert row.get("quote_verified") is not True, row
    mark = dict(row.get(_key()) or {})
    assert mark.get("pass") == "first", (mark, row)
    assert str(mark.get("manuscript_id") or ""), mark
    assert str(mark.get("body_sha256") or ""), mark

    mid = str(row.get("manuscript_id") or "")
    rel = str(mark.get("manuscript") or "")
    assert mid and rel, row
    close = _close_gate(st, mid=mid, rel=rel)
    assert close.get("problems") == [], close
    got_read = _closing(st)
    assert got_read.get("count") == 0, got_read
    assert got_read.get("cited_placeholder_count") == 1, got_read


def test_g_a_real_second_pass_rewrites_the_marker_to_second(
        tmp_path: pathlib.Path) -> None:
    """g：第二遍优化重写真跑一遍 ⇒ 行上的标记被改写（first → second）。

    这一条防的是"判据读得对、而生产上没人写标记"：只测读口的话，写口漏掉
    `second` 也会全绿，而盘上第二遍仍会被读成第一遍。
    """
    import conftest

    st = _real_store(tmp_path)
    b = _real_b(st)
    first = b.register_statement(
        statement_full=FULL, statement_text="", kind="theorem", label="主定理",
        origin="external_lit", source_lit_id=LIT, page_range={"start": 1},
        quote_verified=True, quote_reason="逐字比对通过", proof_text=QUOTE)
    assert first.get("ok") is True, first
    row = dict(next(iter(st.rows("statements"))))
    sid = str(row.get("stmt_id") or "")
    assert dict(row.get(_key()) or {}).get("pass") == "first", row

    # 第二遍改写要走"先拿签，再入库"（`_apply_canonical_proof` 的硬口径）。
    conftest.sign_for_the_gate(st.root, statement_id=sid, proof_text=OPT, store=st)
    second = b.register_statement(
        statement_full=FULL, statement_text="", kind="theorem", label="主定理",
        origin="external_lit", source_lit_id=LIT, page_range={"start": 1},
        proof_text=OPT)
    assert second.get("ok") is True, second
    row = dict(next(iter(st.rows("statements"))))
    assert str(row.get("proof_text") or "") == OPT, row
    mark = dict(row.get(_key()) or {})
    assert mark.get("pass") == "second", (mark, row)
    assert str(mark.get("body_sha256") or ""), mark


def _row_of(st: Store, sid: str = SID) -> dict:
    return dict(next(r for r in st.rows("statements")
                     if str(r.get("stmt_id") or "") == sid))
