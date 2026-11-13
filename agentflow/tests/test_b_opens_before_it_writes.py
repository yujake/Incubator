# -*- coding: utf-8 -*-
"""B 的开稿接线（2026-11-13 业主裁定 ④ · 统一四步的 B 接线）。

业主口径（逐字）：

> 「统一 B、E、F 注册稿和写稿的流程：写命题 → 命题形式过审 → 拿稿号 → 写稿」
> 「B 侧只对 B 自己登记的命题审注册名（如来自引文的内容），E 和 F 手稿侧录入放行。」

## 这个文件钉什么

| 编号 | 判据 | 用例 |
|---|---|---|
| a | 引文侧落稿「先开骨架」（写正文那一刻盘上已有 `## 命题`、`## 证明` 还空） | `test_a_*` |
| b | 开稿口用的是调用方刚判过的那份读数（形态闸只问一次、台账一行） | `test_b_*` |
| c | 一笔只发一个稿号（开稿口发号，写正文不另发） | `test_c_*` |
| d | 按稿收录的放行要「正面证据」：形态台账里有这段字节的判定才放行，没有就照判 | `test_d_*` |
| e | 反真空：把开稿口打桩成失败 ⇒ 零字节、号源不动、整笔拒 | `test_e_*` |

## 为什么 b-proof 的按稿收录还要证据

闸只剩开稿那一刻（④）。b-proof 的合法来源只有两个：引文侧开稿（判过才发号）与
优化副本（按 `open_polish_copy` 的来源记录放行）。引文侧的证据是「形态台账里真有一行
判过这段字节」（按 sha 命中、跨 role 读）—— 没有那一行就说明这份稿没经过开稿口
（记录被删 / 从别处拷进来），这时 fail-closed 照判，不拿"应该是判过"当放行。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import bmanuscript as BM  # noqa: E402
from agentflow import manuscriptids as MID  # noqa: E402
from agentflow import manuscriptopen as MO  # noqa: E402
from agentflow import proofregistry as PR  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-11-13T10:00:00+08:00"
LIT = "000000"
PROP = ("设 a = 1/√2、O_a = {(x,y,z) : |x|+|y|+|z| ≤ a}；则对任意单位向量 n 与"
        "任意实数 t，截面面积 A_n(t) ≤ 2a²，且等号成立当且仅当 n 平行于某坐标轴"
        "且 t = 0。")
QUOTE = ("Theorem 1.2. Let a = 1/sqrt(2). For every unit vector n and every real t, "
         "the central section area A_n(t) is at most 2a^2, with equality iff n is "
         "parallel to a coordinate axis and t = 0.")


class _Seam:
    """模型缝替身：只回形态判定与同命题检索两类答案（别的路径不碰）。"""

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "fake"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def __init__(self, *, well_formed: bool = True) -> None:
        self.well_formed = bool(well_formed)
        self.form_calls: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        _note = str(note or "")
        if _note.endswith("secretary:proposition_form"):
            self.form_calls.append(str(prompt))
            if self.well_formed:
                return ({"well_formed": True, "conditions": "设 a = 1/√2、n 为单位向量",
                         "conclusion": "则 A_n(t) ≤ 2a²，等号当且仅当 n ∥ 坐标轴且 t = 0",
                         "problems": [], "decision": "夹具：前提与结论都写清了"},
                        self._Call())
            return ({"well_formed": False, "conditions": "", "conclusion": "",
                     "problems": ["这是流程要求，不是「从什么条件导出什么结论」的命题"],
                     "decision": "夹具：不是命题"}, self._Call())
        if _note.endswith("secretary:statement_keywords"):
            return ({"keywords": ["截面", "面积"], "why": "夹具"}, self._Call())
        return ({"decision": "different", "canonical_name": "夹具", "same_as": "",
                 "route": "", "condition": "夹具", "conclusion": "夹具",
                 "reason": "夹具：在册没有逐字同一条命题", "basis": ["夹具"]},
                self._Call())


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("literature", actor="u") as tx:
        tx.upsert("literature", {
            "lit_id": LIT, "title": "夹具文献", "type": "J", "summary": "夹具",
            "path": f"{LIT}/source.txt", "processed": True,
            "created_at": TS, "created_by": "u"})
    return st


def _b(st: Store, seam: _Seam) -> AgentB:
    sec = SEC.Secretary("B", root=st.root, store=st, seam=seam, enable_model=True)
    return AgentB(st, extractor=None, extract_text=None, config={}, secretary=sec)


def _citation(st: Store, seam: _Seam) -> dict:
    return _b(st, seam).register_statement(
        statement_full=PROP, statement_text="", kind="theorem", label="主定理",
        origin="external_lit", source_lit_id=LIT, page_range={"start": 1, "end": 2},
        evidence_kind="cross_check", quote_verified=False,
        quote_reason="夹具：还没有逐字比对", proof_text=QUOTE)


def _reports(st: Store) -> list[str]:
    base = pathlib.Path(st.root) / "reports"
    return sorted(p.name for p in base.glob("*.md")) if base.is_dir() else []


def _section(text: str, name: str) -> str:
    _head, sections = PR.split_sections(text)
    return next((body for got, body in sections if got == name), "")


# ---------------------------------------------------------------- a：先开骨架
def test_a_the_citation_landing_opens_a_skeleton_first(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """写正文（`land_rewrite`）那一刻：盘上已经有骨架（命题在、`## 证明` 还空）。"""
    st = _store(tmp_path)
    seen: dict[str, object] = {}
    real = BM.land_rewrite

    def _spy(root, **kw):  # noqa: ANN001, ANN003 - 探针
        base = pathlib.Path(str(root)) / "reports"
        files = sorted(base.glob("b-proof-*.md")) if base.is_dir() else []
        seen["names"] = [p.name for p in files]
        seen["text"] = files[0].read_text(encoding="utf-8") if files else ""
        return real(root, **kw)

    monkeypatch.setattr(BM, "land_rewrite", _spy)
    got = _citation(st, _Seam(well_formed=True))

    assert got.get("ok") is True, got
    assert seen["names"] == ["b-proof-000000.md"], (
        "写正文之前必须先有骨架（开稿口在写正文之前）", seen["names"])
    assert _section(str(seen["text"]), "命题").strip() == PROP
    assert _section(str(seen["text"]), "证明").strip() == "", "那一刻 `## 证明` 还是空的"
    ms = dict(got.get("citation_manuscript") or {})
    text = (pathlib.Path(st.root) / str(ms.get("path") or "")).read_text(encoding="utf-8")
    assert QUOTE in _section(text, "证明"), "正文（逐字引文）写进去了"


# ---------------------------------------------------------------- b：闸只问一次
def test_b_the_open_reuses_the_gate_reading_and_asks_the_model_once(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """开稿口拿到调用方刚判过的那份读数：`_proposition_form_gate` 只被调一次。"""
    st = _store(tmp_path)
    calls: list[dict] = []
    real_gate = AgentB._proposition_form_gate

    def _count(self, **kw):  # noqa: ANN001 - 探针
        calls.append(dict(kw))
        return real_gate(self, **kw)

    monkeypatch.setattr(AgentB, "_proposition_form_gate", _count)
    seam = _Seam(well_formed=True)
    got = _citation(st, seam)

    assert got.get("ok") is True, got
    assert len(calls) == 1, ("形态闸被问了几次（同一段字节第二次问＝白花钱）", calls)
    assert len(seam.form_calls) == 1, seam.form_calls
    assert len(SEC.proposition_form_rows(st.root)) == 1, SEC.proposition_form_rows(st.root)


# ---------------------------------------------------------------- c：一个稿号
def test_c_one_manuscript_id_per_citation_landing(tmp_path: pathlib.Path) -> None:
    """一笔只发一个稿号：开稿口发号，写正文不再另发（盘上一份、号段只走一格）。"""
    st = _store(tmp_path)
    before = MID.peek_manuscript_counter(st.root, family="b-proof")
    got = _citation(st, _Seam(well_formed=True))
    after = MID.peek_manuscript_counter(st.root, family="b-proof")
    assert got.get("ok") is True, got
    assert after == before + 1, (before, after, "一笔发了不止一个稿号")
    assert _reports(st) == ["b-proof-000000.md"], _reports(st)
    ms = dict(got.get("citation_manuscript") or {})
    assert str(ms.get("manuscript_id") or "") == "000000", (ms, got)


# ---------------------------------------------------------------- d：放行要证据
def test_d_the_ingest_release_needs_positive_evidence(tmp_path: pathlib.Path) -> None:
    """按稿收录：台账里有这段字节的判定 ⇒ 放行；没有 ⇒ 照判（fail-closed）。"""
    reading = {"cells": {"statement_full": {"outcome": "present", "value": PROP}},
               "declared_kind": "theorem"}
    # ① 没有证据（新工作区）：照判，坏形状被拒
    st_bad = _store(tmp_path / "noleaf")
    bad = _b(st_bad, _Seam(well_formed=False))
    refused, read = bad._manuscript_form_refusal(
        reading=reading, family="b-proof", rel="reports/b-proof-000000.md")
    assert refused, ("没有形态台账那一行仍然放行 ⇒ 放行没在认证据", read)
    assert str(refused.get("refused")) == "proposition_form_refused", refused
    assert read.get("judged") is True, read

    # ② 有证据（引文侧开稿判过一次）：同一段字节 ⇒ 放行，basis=form_ledger，0 调用
    st_ok = _store(tmp_path / "leaf")
    assert _citation(st_ok, _Seam(well_formed=True)).get("ok") is True
    rows = SEC.proposition_form_rows(st_ok.root)
    assert len(rows) == 1 and rows[0]["checked"] is True, rows
    good = _b(st_ok, _Seam(well_formed=False))
    refusal, read = good._manuscript_form_refusal(
        reading=reading, family="b-proof", rel="reports/b-proof-000000.md")
    assert refusal == {}, (refusal, "台账里已有判定，按稿收录这一路不该再判")
    assert read.get("released") is True and read.get("judged") is False, read
    assert read.get("release_basis") == "form_ledger", read
    assert read.get("model_calls") == 0 and read.get("ledger_appended") is False, read


# ---------------------------------------------------------------- e：反真空
def test_e_without_the_open_port_nothing_is_written(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把开稿口打桩成失败 ⇒ 整笔拒、零字节、号源不动（b 红）。"""
    st = _store(tmp_path)
    before = MID.peek_manuscript_counter(st.root, family="b-proof")

    def _no_open(*_a, **_kw):
        return {"ok": False, "checked": True, "refused": "manuscript_id_unavailable",
                "why": "夹具：号源不发号", "path": "", "manuscript_id": "",
                "problems": [], "form": {}}

    monkeypatch.setattr(MO, "open_manuscript", _no_open)
    got = _citation(st, _Seam(well_formed=True))

    assert got.get("ok") is False, got
    assert str(got.get("refused") or got.get("kind") or "") in (
        "manuscript_id_unavailable", "citation_manuscript_not_landed"), got
    assert _reports(st) == [], "开稿口没成 ⇒ 零字节"
    assert MID.peek_manuscript_counter(st.root, family="b-proof") == before, "号源不许动"
    assert [dict(r) for r in st.rows("statements")] == [], "整笔不写"
