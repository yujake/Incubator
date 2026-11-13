# -*- coding: utf-8 -*-
"""业主 2026-11-13 裁决（甲）的判据：引文侧登记先判形态、再落一份 b-稿，E/F/D 放行。

## 业主口径（逐字）

> 「B 侧只对 B 自己登记的命题审注册名（如来自引文的内容），E 和 F 手稿侧录入放行。」

> 「要审的命题名是：不是从 E 和 F 侧进（随 D 进）的，且不是 B 做优化表述的
> （这个命题已保证在台账上肯定审过），其它手稿录入。其实将审的闸设在录入侧是错误的，
> 应该设在 B 侧写手稿侧（形状同 F 和 E），请检查从引文侧录入命题是否每个命题落手稿
> （落是正确的），于是可以在那时审核。」

## 为什么闸落在「B 自己登记 + 落稿」这一格

实测（`temp/z1_fact_probe/corpus.py`）：本仓 `projects/` 里 `origin="external_lit"` 的
非 concept 命题 49 条，带 `b-proof-*` 稿的 0 条；全部 17 份 `b-proof-*` 稿回查稿头
都是 `own_result` —— "从引文侧录入的命题都会落一份手稿"这个前提在原代码里不成立。
甲把它补成真的：引文侧新命题登记那一刻先落一份 b-稿（稿号来自 B 自己的号段，
与命题号解耦），闸就在写那份稿之前。

## 判据（红 → 绿）

| # | 造什么 | 期望 | 改前为什么红 |
|---|---|---|---|
| a | 引文侧新命题、形状是修订说明 | 受控拒 `proposition_form_refused` + `fix`（点「条件 / 结论」）+ `next_step`；`reports/` 零字节、稿号计数器未动、`statements` 零行 | 改前 `ok=True`、落 1 行（探针 `temp/z1_fact_probe/probe.py`） |
| b | 引文侧新命题、形状合规 | `reports/b-proof-<稿号>.md` 落盘（稿号 != 命题号）；`statements` 1 行且 `manuscript_id` / `manuscripts` 指向它；稿三节齐、`## 命题` 是这条命题 | 改前不落稿（0/49 的语料读数） |
| c | E / F 的 `f-proof-*`（`## 命题` 是修订说明） | 收编成功；形态闸 0 次调用、形态台账不新增行；读数写「由产出侧闸负责，B 侧放行」 | 改前被 `_manuscript_form_refusal` 拦（W2 真机 `f-proof-000002`） |
| d | `e-proof` / `e-num` | 同一张放行表（不判、0 调用、台账零新增） | 改前 `e-proof` 仍判 |
| e | 反真空①：把写前闸打桩成恒放行 | a 必红（那条修订说明会连同稿一起落盘） | 证明 a 的拒来自这道闸 |
| f | 反真空②：把落稿打桩成不写 | b 必红（登记被拒 / 没有稿） | 证明 b 的绿来自落稿这一步 |
| g | 缓存：同一段字节第二次问 | `cached=True`、模型调用不再增加、台账仍 1 行 | 复用 `out/secretary/proposition_form.jsonl` |
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

import conftest  # noqa: E402

from agentflow import depsection as DS  # noqa: E402
from agentflow import manuscriptids as MID  # noqa: E402
from agentflow import proofregistry as PR  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-11-13T10:00:00+08:00"
LIT = "000000"

#: 真机 `reports/f-proof-000002.md` 的 `## 命题`（逐字：修订说明，不是定理陈述）。
NOTE = ("按 V u-000005 的唯一缺陷修订第 7 步：把「2|P_1| = 2/√(u²+v²)」改为"
        "「2|P_1| = 2√(u²+v²)/(u+v) = 2/(u+v)（用 u²+v² = 1）」，其余八步一字不动；"
        "同一份稿 reports/f-proof-000002.md 就地重写后重送 V。"
        "；这一条的可检验形式：V 对这一版正文（新 sha）给出两态结论「成立」（零 finding）；"
        "判据：F.step 返回的 v_sign.label == '已签'。")

#: 同一份引文正文；`## 命题` 才是变量（正控用规范陈述）。
PROPOSITION = ("设 a = 1/√2、O_a = {(x,y,z) : |x|+|y|+|z| ≤ a}；则对任意单位向量 n 与"
               "任意实数 t，截面面积 A_n(t) ≤ 2a²，且等号成立当且仅当 n 平行于某坐标轴"
               "且 t = 0。")

#: 引文侧登记的 `proof_text`：回验要比对的那一段逐字引文（甲：它进 `## 证明`）。
QUOTE = ("Theorem 1.2. Let a = 1/sqrt(2). For every unit vector n and every real t, "
         "the central section area A_n(t) is at most 2a^2, with equality iff n is "
         "parallel to a coordinate axis and t = 0.")

PROOF = ("1. 口径与齐次缩放：O_a = a·O_1，area(a·K) = a²·area(K)。\n"
         "2. 由 Brunn 凹性与 O_1 的中心对称得 A_n(t) ≤ A_n(0)：最大值在中心截面。\n"
         "3. 中心截面为六边形，面积闭式 2s/D ≤ 2，等号当且仅当 n=±e_i。")

F_REL = "reports/f-proof-000002.md"


class _Seam:
    """判定面替身：只替换"问模型"那一格，别的照旧（台账 / 读稿走真秘书）。

    `form_calls` 数的是 B 真的为某条命题问了形态闸几次 —— 放行与拒收两条判据的核心读数。
    """

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
                return ({"well_formed": True,
                         "conditions": "设 a = 1/√2、n 为单位向量",
                         "conclusion": "则 A_n(t) ≤ 2a²，等号当且仅当 n ∥ 坐标轴且 t = 0",
                         "problems": [], "decision": "前提与结论都写清了"}, self._Call())
            return ({"well_formed": False, "conditions": "", "conclusion": "",
                     "problems": ["这是修订与送审的流程要求，不是「从什么条件导出什么结论」"
                                  "的数学命题"],
                     "decision": "不是命题"}, self._Call())
        if _note.endswith("secretary:statement_keywords"):
            return ({"keywords": ["截面", "面积", "单位向量"],
                     "why": "夹具：这几个词能把同一条命题捞出来"}, self._Call())
        return ({"decision": "different", "canonical_name": "夹具",
                 "same_as": "", "route": "", "condition": "夹具", "conclusion": "夹具",
                 "reason": "夹具：在册没有逐字同一条命题", "basis": ["夹具"]},
                self._Call())


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("literature", actor="z1") as tx:
        tx.upsert("literature", {
            "lit_id": LIT, "title": "夹具文献", "type": "J", "summary": "夹具",
            "path": f"{LIT}/source.txt", "processed": True,
            "created_at": TS, "created_by": "z1"})
    return st


def _b(st: Store, seam: _Seam) -> AgentB:
    sec = SEC.Secretary("B", root=st.root, store=st, seam=seam, enable_model=True)
    return AgentB(st, extractor=None, extract_text=None, config={}, secretary=sec)


def _citation(st: Store, seam: _Seam, *, text: str = NOTE,
              quote: str = QUOTE) -> dict:
    """引文侧登记一条命题（出处三件齐全；形状由 `text` 决定）。"""
    return _b(st, seam).register_statement(
        statement_full=text, statement_text="", kind="theorem", label="主定理",
        origin="external_lit", source_lit_id=LIT, page_range={"start": 1, "end": 2},
        evidence_kind="cross_check", quote_verified=False,
        quote_reason="夹具：还没有逐字比对", proof_text=quote)


def _rows(st: Store, table: str) -> list[dict]:
    return [dict(r) for r in st.rows(table)]


def _reports(st: Store) -> list[str]:
    base = pathlib.Path(st.root) / "reports"
    return sorted(p.name for p in base.glob("*.md")) if base.is_dir() else []


# ============================================================ a 引文侧坏形状 ⇒ 受控拒
def test_a_a_citation_side_proposition_with_a_bad_form_is_refused(
        tmp_path: pathlib.Path) -> None:
    """a：形状不合格 ⇒ 受控拒 + 可执行改法；稿 0 字节、号未发、statements 0 行。"""
    st = _store(tmp_path)
    seam = _Seam(well_formed=False)
    counter_before = MID.peek_manuscript_counter(st.root, family="b-proof")
    got = _citation(st, seam)

    assert got.get("ok") is False, got
    assert str(got.get("refused") or got.get("kind") or "") == "proposition_form_refused", got
    fix = str(got.get("fix") or "")
    assert "条件" in fix and "结论" in fix, fix
    assert "引文" in fix, fix
    nxt = str(got.get("next_step") or "")
    assert nxt.strip(), nxt
    assert "不用 D 裁" in nxt, nxt
    assert "改法：" in str(got.get("error") or ""), got.get("error")

    assert _reports(st) == [], _reports(st)
    assert MID.peek_manuscript_counter(st.root, family="b-proof") == counter_before, (
        "受控拒却发了一个稿号")
    assert _rows(st, "statements") == [], _rows(st, "statements")
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1, rows
    assert rows[0]["role"] == "B" and rows[0]["checked"] is True, rows
    assert rows[0]["well_formed"] is False, rows
    assert len(seam.form_calls) == 1, seam.form_calls


# ============================================================ b 引文侧正控 ⇒ 落稿 + 登记
def test_b_a_well_formed_citation_lands_a_b_manuscript_and_the_row(
        tmp_path: pathlib.Path) -> None:
    """b：形状合规 ⇒ 先落 `b-proof-<稿号>.md`（稿号 != 命题号），再登记、行指向它。"""
    st = _store(tmp_path)
    # 先把 B 的稿号段推到 000000（两根号段是独立的：命题号从 000000 起、
    # 稿号从 000000 起；这一笔要证明的是"稿名用的是稿号，不是命题号"）。
    MID.next_manuscript_id(st.root, family="b-proof")
    seam = _Seam(well_formed=True)
    got = _citation(st, seam, text=PROPOSITION, quote=QUOTE)

    assert got.get("ok") is True, got
    sid = str(got.get("stmt_id") or "")
    assert sid, got
    ms = dict(got.get("citation_manuscript") or {})
    mid = str(ms.get("manuscript_id") or "")
    rel = str(ms.get("path") or "")
    assert mid and mid != sid, (mid, sid)
    assert rel == MID.canonical_rel(mid, family="b-proof"), (rel, mid)
    path = pathlib.Path(st.root) / rel
    assert path.is_file(), f"引文侧登记没有落稿：{rel}"
    text = path.read_text(encoding="utf-8")
    for heading in ("## 命题", "## 证明", "## 依赖"):
        assert heading in text, heading
    sections = dict(PR.split_sections(text)[1])
    assert str(sections.get("命题") or "").strip() == PROPOSITION, sections
    assert str(sections.get("证明") or "").strip() == QUOTE, (
        "引文侧 b-稿的 `## 证明` 应当是逐字引文（业主 2026-11-13）")
    # 稿头不写命题号（业主 2026-11-13 后续裁定：「稿里没有命题号，任何稿里都没有命题号」）
    # —— 这份稿与命题行的对应关系只在台账那一行的 `manuscript_id` / `manuscripts` 上。
    assert PR.parse_entry(text).get("statement_id") == "", PR.parse_entry(text)

    rows = _rows(st, "statements")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["statement_full"] == PROPOSITION, row
    assert str(row.get("manuscript_id") or "") == mid, row
    per_path = dict(row.get("manuscripts") or {})
    assert rel in per_path.values(), (per_path, rel)
    assert len(seam.form_calls) == 1, seam.form_calls


# ============================================================ c F 手稿 ⇒ 放行
def test_c_a_signed_f_manuscript_with_a_revision_note_is_released(
        tmp_path: pathlib.Path) -> None:
    """c：F 的 `f-proof-*`（`## 命题` 是修订说明）⇒ 收编成功、不判、台账零新增。"""
    st = _store(tmp_path)
    path = pathlib.Path(st.root) / F_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# F 的证明手稿：夹具\n\n- 命题号：stmt:（还没落号）\n"
        "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
        "## 命题\n\n" + NOTE + "\n\n## 证明\n\n" + PROOF + "\n\n"
        + DS.render_dependency_section([]) + "\n", encoding="utf-8")
    conftest.sign_before_registration(st.root, proof_text=PROOF)
    seam = _Seam(well_formed=False)   # 若 B 真问了，它会判"不是命题"
    got = _b(st, seam).ingest_manuscript(manuscript=F_REL, mode="register")

    assert got.get("ok") is True, got
    assert seam.form_calls == [], (
        "B 为 F 手稿问了形态闸（上游已经判过，这一问不该再花）", seam.form_calls)
    assert SEC.proposition_form_rows(st.root) == [], SEC.proposition_form_rows(st.root)
    rows = _rows(st, "statements")
    assert len(rows) == 1, rows
    assert str(rows[0]["statement_full"]) == NOTE, rows[0]
    read = dict(got.get("proposition_form") or {})
    assert read.get("released") is True, read
    assert read.get("family") == "f-proof", read
    assert read.get("model_calls") == 0 and read.get("ledger_appended") is False, read
    assert "由产出侧闸负责" in str(read.get("reason") or ""), read


# ============================================================ d E 手稿 ⇒ 放行
def test_d_e_proof_and_e_num_are_released_by_the_same_table(
        tmp_path: pathlib.Path) -> None:
    """d：`e-proof` / `e-num` 与 F 同一张放行表 —— 不判、0 调用、台账零新增。"""
    st = _store(tmp_path)
    b = _b(st, _Seam(well_formed=False))
    reading = {"cells": {"statement_full": {"outcome": "present", "value": NOTE}},
               "head_statement_id": "", "declared_kind": "theorem"}
    for family in ("f-proof", "e-proof", "e-num"):
        refusal, read = b._manuscript_form_refusal(
            reading=reading, family=family, rel=f"reports/{family}-000001.md")
        assert refusal == {}, (family, refusal)
        assert read.get("released") is True, (family, read)
        assert read.get("family") == family, (family, read)
        assert read.get("model_calls") == 0 and read.get("ledger_appended") is False, read
        assert "B 侧放行" in str(read.get("reason") or ""), read
    assert SEC.proposition_form_rows(st.root) == [], SEC.proposition_form_rows(st.root)


# ============================================================ e 反真空①
def test_e_stubbing_the_gate_open_lands_the_revision_note(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：把写前闸打桩成恒放行 ⇒ a 必红（修订说明连同 b-稿一起落盘）。"""
    monkeypatch.setattr(
        AgentB, "_proposition_form_gate",
        lambda self, **_kw: {"checked": True, "well_formed": True, "submittable": True,
                             "conditions": "夹具", "conclusion": "夹具", "problems": [],
                             "decision": "夹具：放行", "refused": "", "reason": "夹具",
                             "actor": "secretary-B", "cached": False})
    st = _store(tmp_path)
    got = _citation(st, _Seam(well_formed=False))

    assert got.get("ok") is True, (
        "把形态闸打成恒放行之后 B 仍然拒 ⇒ a 的拒不来自这一格", got)
    assert _reports(st), "闸放行之后没有落稿 ⇒ a 的「稿 0 字节」证明不了闸在承重"
    rows = _rows(st, "statements")
    assert len(rows) == 1 and rows[0]["statement_full"] == NOTE, rows


# ============================================================ f 反真空②
def test_f_stubbing_the_landing_away_makes_b_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f：把落稿打桩成"不写" ⇒ b 必红（登记不许退化成"无稿登记"）。"""
    monkeypatch.setattr(
        AgentB, "_land_citation_manuscript",
        lambda self, **_kw: {"ok": False, "written": False, "path": "",
                             "manuscript_id": "", "text": "",
                             "refused": "citation_manuscript_not_landed",
                             "why": "夹具：落稿被打桩成不写"})
    st = _store(tmp_path)
    got = _citation(st, _Seam(well_formed=True), text=PROPOSITION, quote=QUOTE)

    assert got.get("ok") is False, (
        "把落稿打桩成不写之后登记仍然成功 ⇒ b 证明不了落稿这一步在承重", got)
    assert _rows(st, "statements") == [], _rows(st, "statements")
    assert _reports(st) == [], _reports(st)


# ============================================================ g 缓存
def test_g_the_same_bytes_the_second_time_hit_the_ledger_cache(
        tmp_path: pathlib.Path) -> None:
    """g：同一段字节第二次问 ⇒ 命中台账缓存、不再调模型、台账仍 1 行。"""
    st = _store(tmp_path)
    seam = _Seam(well_formed=True)
    first = _citation(st, seam, text=PROPOSITION, quote=QUOTE)
    assert first.get("ok") is True, first
    calls_after_first = len(seam.form_calls)
    assert calls_after_first == 1, seam.form_calls

    # 同一条命题再交一次（同一段字节、同一出处）：形态这一问必须免费。
    got = _b(st, seam).register_statement(
        statement_full=PROPOSITION, statement_text="", kind="theorem", label="主定理",
        origin="external_lit", source_lit_id=LIT, page_range={"start": 3},
        evidence_kind="cross_check", quote_verified=False,
        quote_reason="夹具：第二次交同一段字节", proof_text=QUOTE)
    assert got.get("ok") in (True, False), got
    assert len(seam.form_calls) == calls_after_first, (
        "同一段字节第二次问仍然调了模型（缓存没命中）", seam.form_calls)
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1, rows
    assert rows[0]["role"] == "B", rows


# ============================================================ h 引文侧没有逐字引文 ⇒ 受控拒
def test_h_a_citation_without_a_quoted_text_cannot_land_a_manuscript(
        tmp_path: pathlib.Path) -> None:
    """h：引文侧登记要落稿，而 `## 证明` 的正文就是逐字引文 ⇒ 没有引文时受控拒。"""
    st = _store(tmp_path)
    got = _citation(st, _Seam(well_formed=True), text=PROPOSITION, quote="")

    assert got.get("ok") is False, got
    assert str(got.get("refused") or got.get("kind") or "") == (
        "citation_manuscript_needs_quote"), got
    assert "proof_text" in str(got.get("error") or ""), got.get("error")
    assert _reports(st) == [], _reports(st)
    assert _rows(st, "statements") == [], _rows(st, "statements")
