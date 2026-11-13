# -*- coding: utf-8 -*-
"""彩排判据 C5：B 收编那一刻的三个出口（业主 2026-11-13 更正后的口径）。

## 业主口径（逐字，2026-11-13 更正）

> 「B 侧只对 B 自己登记的命题审注册名（如来自引文的内容），E 和 F 手稿侧录入放行。」

推出来的三条出口：

- 出口①（命题形态闸）只对 B 自己登记的命题生效。E / F 的手稿（`f-proof-*` /
  `e-proof-*` / `e-num-*`）在写稿那一刻已经由自己的闸判过（F 侧
  `_proposition_form_precheck`、E 侧数值通道闸），B 侧不再判、也不该为它花钱；
- 出口②：命题已经入册 ⇒ 不许用「改命题节」换命题，走重新登记
  （`proposition_already_registered`，点名 `stmt:<号>`）；
- 出口③：未入册 ⇒ 允许原位改写 `## 命题`，但要过二态语义同一性门：同一条 ⇒ 成功且
  签仍有效；不是同一条 ⇒ `proposition_identity_refused`；没判成 ⇒
  `proposition_identity_unjudged`（fail-closed、零写入）。

## 甲的最终形态（38c53b01 落地后对锚）

1. E / F 的族（`f-proof-*` / `e-proof-*` / `e-num-*`）由
   `MANUSCRIPT_FORM_RELEASED_FAMILIES` 放行：`_manuscript_form_refusal` 在
   `register_statement.py:1487` 早退，回执读数 `judged=False / released=True /
   family=<族> / model_calls=0 / ledger_appended=False`，形态台账不新增行；
2. 「B 自己登记的命题」= 引文侧（`origin="external_lit"`、无稿、未在册）：
   `_own_registration_form_refusal`（`:1588`）在落任何文件之前判形态 —— 判不过 ⇒
   `proposition_form_refused` + `fix` / `next_step`，稿 0 字节、号未发、statements 0 行；
   判过 ⇒ 先落 `reports/b-proof-<B 稿号>.md`（稿号与命题号解耦）再登记；
   引文侧必须带逐字引文（`proof_text` 就是原文摘录），没有 ⇒
   `citation_manuscript_needs_quote`；
3. 出口②/③（已入册不许改写 / 未入册可原位改写，二态同一性门）不变。

所以本文件的 b 段夹具用 `origin="external_lit"` + 逐字 `proof_text`（按 `own_result`
写永远不会走这一路判）；a 段读 `released=True` 那五格。

## 缓存事实读数

`secretary.py:3854` 按命题正文 sha256 命中 `out/secretary/proposition_form.jsonl`
（写入口 `:3941 _note_form` / `:14188 append_proposition_form`，键 `:14236` 起），
跨 role 读、不筛 role。「上游已判过、B 侧同一段字节」会 `cached=True`、不再调模型
（本文件 `test_f_*` 钉住这一格）。

## 不做什么

- 不测「命题对不对」（V 的轴）；判定面是替身，不花钱。
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
from agentflow import proofregistry as PR  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_f import AgentF  # noqa: E402
from agentflow.store import Store  # noqa: E402

REL = "reports/f-proof-000002.md"
MID = "000002"

#: 真机 `reports/f-proof-000002.md` 的 `## 命题` 节（逐字：一段修订说明）。
NOTE = ("按 V u-000005 的唯一缺陷修订第 7 步：把「2|P_1| = 2/√(u²+v²)」改为"
        "「2|P_1| = 2√(u²+v²)/(u+v) = 2/(u+v)（用 u²+v² = 1）」，其余八步一字不动；"
        "同一份稿 reports/f-proof-000002.md 就地重写后重送 V。"
        "；这一条的可检验形式：V 对这一版正文给出两态结论「成立」。")

#: 改后的正确陈述（同一条定理：只是把「改法说明」换成「条件 → 结论」）。
PROPOSITION = ("设 a = 1/√2、O_a = {(x,y,z) : |x|+|y|+|z| ≤ a}；则对任意单位向量 n 与"
               "任意实数 t，截面面积 A_n(t) ≤ 2a²，且等号成立当且仅当 n 平行于某坐标轴"
               "且 t = 0。")

PROOF = ("1. 口径与齐次缩放：O_a = a·O_1，area(a·K) = a²·area(K)，故只需证 a=1 时 ≤ 2。\n"
         "2. 由 Brunn 凹性与 O_1 的中心对称得 A_n(t) ≤ A_n(0)：最大值在中心截面。\n"
         "3. 中心截面为六边形，面积闭式 2s/D ≤ 2，等号当且仅当 n=±e_i。")

#: 引文侧登记的出处（一条 `literature` 行）与它那段逐字引文（甲：`## 证明` = 原文摘录）。
LIT = "000000"
TS = "2026-11-13T10:00:00+08:00"
QUOTE = ("Theorem 1.2. Let a = 1/sqrt(2). For every unit vector n and every real t, "
         "the central section area A_n(t) is at most 2a^2, with equality iff n is "
         "parallel to a coordinate axis and t = 0.")


class _Seam:
    """判定面替身：形态那一问按 `well_formed` 回，同一性那一问按 `identity` 回。

    `form_calls` 数的是「B 真的为这份稿问了形态闸几次」—— a 段的核心读数。
    """

    class _Call:
        ok = True
        problem = ""
        detail = ""

    def __init__(self, *, well_formed: bool = True, identity: str = "same"):
        self.well_formed = bool(well_formed)
        self.identity = str(identity)
        self.form_calls: list[str] = []
        self.identity_calls: list[str] = []

    def ask_json(self, prompt, **kw):
        note = str(kw.get("note") or "")
        if note.endswith("secretary:proposition_form"):
            self.form_calls.append(str(prompt))
            if self.well_formed:
                return ({"well_formed": True, "conditions": "设 a = 1/√2、n 为单位向量",
                         "conclusion": "则 A_n(t) ≤ 2a²，等号当且仅当 n ∥ 坐标轴且 t = 0",
                         "problems": [], "decision": "前提与结论都写清了"}, self._Call())
            return ({"well_formed": False, "conditions": "", "conclusion": "",
                     "problems": ["这是修订与送审的流程要求，不是「从什么条件导出什么结论」"
                                  "的数学命题"],
                     "decision": "不是命题"}, self._Call())
        if note.endswith("secretary:proposition_identity"):
            self.identity_calls.append(str(prompt))
            return ({"decision": self.identity, "reason": f"夹具：判 {self.identity}",
                     "basis": ["夹具：条件一句", "夹具：结论一句"]}, self._Call())
        if note.endswith("statement_keywords"):
            return ({"keywords": ["截面", "面积", "单位向量"],
                     "why": "打桩：这几个词能把同一条命题捞出来"}, self._Call())
        return ({"decision": "different", "canonical_name": "截面面积上界",
                 "same_as": "", "route": "", "condition": "打桩：条件未读",
                 "conclusion": "打桩：结论未读", "reason": "打桩：在册没有逐字同一条命题",
                 "basis": ["打桩"]}, self._Call())


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _b(st: Store, seam: _Seam) -> AgentB:
    sec = SEC.Secretary("B", root=st.root, store=st, seam=seam, enable_model=True)
    return AgentB(st, extractor=None, extract_text=None, config={}, secretary=sec)


def _cite_lit(st: Store) -> None:
    """一条 `literature` 行：引文侧登记要 `source_lit_id` 立得住。"""
    with st.tx("literature", actor="夹具") as tx:
        tx.upsert("literature", {
            "lit_id": LIT, "title": "夹具文献", "type": "J", "summary": "夹具",
            "path": f"{LIT}/source.txt", "processed": True,
            "created_at": TS, "created_by": "夹具"})


def _citation(st: Store, seam: _Seam, *, text: str = NOTE,
              quote: str = QUOTE) -> dict:
    """引文侧登记一条命题（B 自己登记的那一路；形状由 `text` 决定）。"""
    return _b(st, seam).register_statement(
        statement_full=text, statement_text="", kind="theorem", label="主定理",
        origin="external_lit", source_lit_id=LIT,
        page_range={"start": 1, "end": 2}, evidence_kind="cross_check",
        quote_verified=False, quote_reason="夹具：还没有逐字比对", proof_text=quote)


def _manuscript(proposition: str = NOTE) -> str:
    head = ("# F 的证明手稿：按 V u-000005 的唯一缺陷修订第 7 步\n\n"
            "- 计划：000002 · 子目标：S4\n"
            "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n")
    return (head + "## 命题\n\n" + proposition + "\n\n"
            "## 证明\n\n" + PROOF + "\n\n" + DS.render_dependency_section([]) + "\n")


def _write(st: Store, *, proposition: str = NOTE) -> pathlib.Path:
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_manuscript(proposition).encode("utf-8"))
    return path


def _sections(text: str) -> dict[str, str]:
    _head, got = PR.split_sections(text)
    return {name: body.strip() for name, body in got}


def _rows(st: Store, table: str) -> list[dict]:
    return [dict(r) for r in st.rows(table)]


def _reports(st: Store) -> list[str]:
    base = pathlib.Path(st.root) / "reports"
    return sorted(p.name for p in base.glob("*.md")) if base.is_dir() else []


def _f(st: Store, *, identity: str = "same", well_formed: bool = True) -> AgentF:
    f = AgentF(st, config={"workspace_root": st.root, "plan_id": "0002"})
    f.f_secretary = SEC.Secretary("F", root=st.root, store=st,
                                  seam=_Seam(well_formed=well_formed, identity=identity),
                                  enable_model=True)
    return f


def _rewrite(f: AgentF, *, proposition: str = PROPOSITION) -> dict:
    return f.rewrite_manuscript_proposition(
        manuscript=REL, proposition=proposition, label="F 攻坚 0002 子目标 S4")


def _pending_bytes(st: Store) -> dict[str, bytes]:
    base = VR.pending_dir(st.root)
    if not base.is_dir():
        return {}
    return {p.name: p.read_bytes() for p in sorted(base.glob("*.jsonl"))}


# ============================================================ a：F / E 手稿放行
def test_a_an_f_manuscript_with_a_revision_note_is_allowed(tmp_path: pathlib.Path) -> None:
    """a：F 稿的 `## 命题` 是修订说明 ⇒ 放行；B 不为它问形态闸、形态台账零新增。

    「上游已判过」：F 在写稿那一刻已经由自己的 `_proposition_form_precheck` 问过同一道
    判据（`agent_f/core.py:3235`）；B 侧再判一次既白花钱、又把判据放到错误的持有者手里。
    这一条是设计故意放行，不是缺陷。
    """
    st = _ws(tmp_path)
    _write(st)
    conftest.sign_before_registration(st.root, proof_text=PROOF)
    seam = _Seam(well_formed=False, identity="different")  # 若 B 真问了，它会判「不是命题」
    got = _b(st, seam).ingest_manuscript(manuscript=REL, mode="register")

    assert got.get("ok") is True, (
        "F 手稿仍被 B 侧的形态闸拦（产品待改：register_statement.py:1384 / :1414 / :7187）："
        f"{got.get('refused')!r} {str(got.get('reason') or '')[:160]}")
    assert seam.form_calls == [], (
        "B 为 F 手稿问了形态闸（上游已经判过，这一问不该再花）", seam.form_calls)
    assert SEC.proposition_form_rows(st.root) == [], SEC.proposition_form_rows(st.root)
    rows = _rows(st, "statements")
    assert len(rows) == 1, rows
    assert str(rows[0].get("statement_full") or "") == NOTE, rows[0]
    read = dict(got.get("proposition_form") or {})
    assert read.get("released") is True, read
    assert read.get("judged") is False, read
    assert read.get("family") == "f-proof", read
    assert read.get("model_calls") == 0 and read.get("ledger_appended") is False, read
    assert "B 侧放行" in str(read.get("reason") or ""), read


# ============================================================ b：B 自己登记 ⇒ 受控拒
def test_b_b_own_registration_with_a_bad_form_is_refused(tmp_path: pathlib.Path) -> None:
    """b：B 自己登记（引文侧）一条形状不合格的命题 ⇒ 受控拒 + fix / next_step，零写入。"""
    st = _ws(tmp_path)
    _cite_lit(st)
    seam = _Seam(well_formed=False, identity="different")
    got = _citation(st, seam)

    assert got.get("ok") is False, (
        "引文侧登记的命题没有过形态闸（甲：闸在落 b-稿之前）："
        f"{got.get('refused')!r} {str(got.get('error') or '')[:160]}")
    assert str(got.get("refused") or got.get("kind") or "") == "proposition_form_refused", got
    fix = str(got.get("fix") or "")
    assert fix and "条件" in fix and "结论" in fix and "引文" in fix, fix
    nxt = str(got.get("next_step") or "")
    assert nxt.strip() and "不用 D 裁" in nxt, nxt
    assert "改法：" in str(got.get("error") or ""), got.get("error")
    assert _reports(st) == [], _reports(st)
    assert _rows(st, "statements") == [], _rows(st, "statements")
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1 and rows[0].get("role") == "B", rows
    assert rows[0].get("checked") is True and rows[0].get("well_formed") is False, rows


# ============================================================ c：已入册 ⇒ 拒改写
def test_c_a_registered_proposition_is_not_rewritten(tmp_path: pathlib.Path) -> None:
    """c：命题已入册 ⇒ 拒 `proposition_already_registered`，点名号与「重新登记」。"""
    st = _ws(tmp_path)
    path = _write(st)
    conftest.seed_statement_row(st, stmt_id="000001", statement_full=NOTE,
                                kind="conjecture", manuscript_id=MID)
    before = path.read_bytes()
    got = _rewrite(_f(st, identity="same"))
    assert got.get("ok") is False, got
    assert got.get("refused") == "proposition_already_registered", got
    assert "stmt:000001" in str(got.get("why") or ""), got.get("why")
    assert "重新登记" in str(got.get("why") or ""), got.get("why")
    assert path.read_bytes() == before, "受控拒却动了稿"
    assert len(_rows(st, "statements")) == 1, _rows(st, "statements")


# ============================================================ d1：未入册 + 同一条
def test_d1_an_unregistered_same_proposition_is_rewritten_and_b_ingests(
        tmp_path: pathlib.Path) -> None:
    """d1：未入册 + 判「同一条」⇒ 只换命题节；正文 sha 未变、签仍有效、B 能收编。"""
    st = _ws(tmp_path)
    path = _write(st)
    conftest.sign_before_registration(st.root, proof_text=PROOF)
    pending_before = _pending_bytes(st)
    assert pending_before, "夹具的 pending 签没落成，这条证明不了「签不动」"
    before_text = path.read_text(encoding="utf-8")

    got = _rewrite(_f(st, identity="same"))
    assert got.get("ok") is True and got.get("wrote") is True, got
    assert got.get("refused") == "", got
    assert got.get("attempted") is True, got
    assert got["proposition_before"].startswith("按 V u-000005"), got
    assert got["proposition_after"] == PROPOSITION, got

    text = path.read_text(encoding="utf-8")
    assert _sections(text)["命题"] == PROPOSITION, _sections(text)["命题"]
    assert PR.proof_sha(text) == PR.proof_sha(before_text), (
        "`## 证明` 的正文 sha 变了 ⇒ 这一笔动了签盖的那段字节")
    assert got.get("body_unchanged") is True, got
    entry = PR.parse_entry(text)
    assert entry.get("fingerprint") == PR.proposition_fingerprint(PROPOSITION), entry
    assert entry.get("sha256") == PR.parse_entry(before_text).get("sha256"), entry
    assert list(got.get("declarations") or []) == list(
        __import__("agentflow.propositionrewrite", fromlist=["x"]).DECLARATIONS), got
    assert _pending_bytes(st) == pending_before, "改命题节却动了 pending 签"
    assert _rows(st, "statements") == [], "改写那一笔不该写 statements"

    # 同一份稿重交 B：签按同一正文 sha 认领，入册的是新陈述，路径号由秘书分配。
    ing = _b(st, _Seam(well_formed=True, identity="different")).ingest_manuscript(
        manuscript=REL, mode="register")
    assert ing.get("ok") is True, ing
    sid = str((ing.get("target") or {}).get("stmt_id") or "")
    row = _row(st, sid)
    assert str(row.get("statement_full") or "") == PROPOSITION, row
    assert str(row.get("manuscript_id") or "") == MID, row


def _row(st: Store, sid: str) -> dict:
    return next(dict(r) for r in st.rows("statements")
                if str(r.get("stmt_id")) == sid)


# ============================================================ d2/d3：另两条出口
def test_d2_a_different_proposition_is_refused(tmp_path: pathlib.Path) -> None:
    """d2：未入册 + 判「另一条」⇒ `proposition_identity_refused`，盘上一个字节没动。"""
    st = _ws(tmp_path)
    path = _write(st)
    before = path.read_bytes()
    got = _rewrite(_f(st, identity="different"))
    assert got.get("ok") is False, got
    assert got.get("refused") == "proposition_identity_refused", got
    assert "另一条命题" in str(got.get("why") or ""), got.get("why")
    assert path.read_bytes() == before, "受控拒却动了稿"
    assert _rows(st, "statements") == [], _rows(st, "statements")


def test_d3_an_unjudged_identity_is_fail_closed(tmp_path: pathlib.Path) -> None:
    """d3：同一性没判成（词表外）⇒ `proposition_identity_unjudged`，零写入。"""
    st = _ws(tmp_path)
    path = _write(st)
    before = path.read_bytes()
    got = _rewrite(_f(st, identity="maybe"))
    assert got.get("ok") is False, got
    assert got.get("refused") == "proposition_identity_unjudged", got
    assert "没判成" in str(got.get("why") or ""), got.get("why")
    assert path.read_bytes() == before, "没判成却动了稿"
    assert _rows(st, "statements") == [], _rows(st, "statements")


# ============================================================ d4：冻结面
def test_d4_a_moving_proof_body_blocks_the_write(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d4：落盘前核 `## 证明` 的 sha；换命题节时正文变了 ⇒ `proof_body_would_move`、零写入。"""
    st = _ws(tmp_path)
    path = _write(st)
    before = path.read_bytes()
    real = PR.replace_section

    def _also_moves(text, name, body):
        new_text, ok = real(text, name, body)
        if ok:
            new_text = new_text.replace(PROOF, PROOF + "\n（夹具：篡改正文）")
        return new_text, ok

    monkeypatch.setattr(PR, "replace_section", _also_moves)
    got = _rewrite(_f(st, identity="same"))
    assert got.get("ok") is False, got
    assert got.get("refused") == "proof_body_would_move", got
    assert got.get("body_unchanged") is False, got
    assert path.read_bytes() == before, "核不过却写了盘"


# ============================================================ e：反真空
def test_e1_stubbing_the_gate_open_makes_b_registration_green(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e1（反真空）：把形态闸打桩成「恒放行」⇒ b 的受控拒必须消失。"""
    monkeypatch.setattr(
        AgentB, "_proposition_form_gate",
        lambda self, **_kw: {"checked": True, "well_formed": True, "submittable": True,
                             "conditions": "夹具", "conclusion": "夹具", "problems": [],
                             "decision": "夹具：放行", "refused": "", "reason": "夹具",
                             "actor": "secretary-B", "cached": False})
    st = _ws(tmp_path)
    _cite_lit(st)
    got = _citation(st, _Seam(well_formed=False, identity="different"))
    assert got.get("ok") is True, (
        "把形态闸打成恒放行之后 B 仍然拒 ⇒ b 的拒信不来自这一格", got)
    assert _reports(st), "闸放行之后没有落 b-稿 ⇒ b 的「零写入」证明不了闸在承重"
    rows = _rows(st, "statements")
    assert len(rows) == 1 and rows[0].get("statement_full") == NOTE, rows


def test_e2_the_note_really_is_ill_formed_when_judged(tmp_path: pathlib.Path) -> None:
    """e2（反真空）：直接问秘书 ⇒ 那段修订说明确实判「不是命题」。

    这条证明 a 的放行是「故意豁免」，不是「这段正文本来就合格」。
    """
    st = _ws(tmp_path)
    sec = SEC.Secretary("B", root=st.root, store=st, seam=_Seam(well_formed=False),
                        enable_model=True)
    got = sec.judge_proposition_form(statement_full=NOTE, kind="conjecture")
    assert got.get("checked") is True, got
    assert got.get("well_formed") is False, got
    assert got.get("refused") == "proposition_form_refused", got
    assert got.get("problems"), got


# ============================================================ f：缓存事实
def test_f_upstream_form_judgement_is_cached_for_b_without_a_second_call(
        tmp_path: pathlib.Path) -> None:
    """f：F 判过之后，B 侧同一段字节命中台账缓存（`cached=True`）、不再花钱。"""
    st = _ws(tmp_path)
    seam_f = _Seam(well_formed=True)
    sec_f = SEC.Secretary("F", root=st.root, store=st, seam=seam_f, enable_model=True)
    first = sec_f.judge_proposition_form(statement_full=PROPOSITION, kind="conjecture")
    assert first.get("checked") is True and first.get("well_formed") is True, first
    assert len(seam_f.form_calls) == 1, seam_f.form_calls

    seam_b = _Seam(well_formed=False)
    sec_b = SEC.Secretary("B", root=st.root, store=st, seam=seam_b, enable_model=True)
    second = sec_b.judge_proposition_form(statement_full=PROPOSITION, kind="conjecture")
    assert second.get("cached") is True, (
        "B 侧同一段字节没有命中缓存（上游 F 已经判过，这一问该免费）："
        f"{second!r}")
    assert second.get("checked") is True and second.get("well_formed") is True, second
    assert seam_b.form_calls == [], (
        "命中了缓存却仍然调了模型", seam_b.form_calls)
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1, rows
    assert rows[0].get("role") == "F", rows


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
