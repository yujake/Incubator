# -*- coding: utf-8 -*-
"""判据：依赖面（引用面）审核异常时，反馈必须可操作（业主 2026-11-06 口径）。

## 业主原话（逐字）

    「引用面（依赖面）审核异常时，反馈给提交证明者的信息需指出具体是哪条，
      是引用命题时表述错误，还是该条不存在，还是该条等级不到能引用的……」

⇒ 每一条异常都给出四元组六格（`:data:agentflow.depsection.FINDING_CELLS`）：

    ① 是哪一条引用：`stmt:<号>`，以及它在哪一步 / 依赖表第几行
    ② 是哪一类问题：受控码 + 一码一名的类别名（不在册 / 等级不到 / 表述错误三种）
    ③ 期望 vs 实得
    ④ 怎么改：一句话可执行

## 判据（a–e，先红后绿 + 反真空）

| 编号 | 它要证明的事 |
|---|---|
| a | 不在册：V 的 finding 与 B 的拒信逐字含号 / 在哪一步 / 不在册 / 怎么改 |
| b | 等级不到：逐字含号 / 等级 x / 门槛 pre_theorem / 怎么改 |
| c | 引错内容（表述错误 a 类）：逐字含号 / 引文 / 与被引命题原文的对比 / 怎么改 |
| d | 步号对不上、表与正文不一致：各自逐字含号 + 哪一行哪一步 + 怎么改 |
| e | 反真空：把六格里任一格从人话里摘掉 ⇒ 同一条判据必须红 |
| g | 两类不许混成一句：不在册与等级不到的人话类别名互不相似、且各说各的 |

## 两处落点的形状（如实说）

- `depsection.dependency_review` 的 `findings` 项同时带四格（level / step / kind /
  detail）与六格（`stmt_id` / `where` / `expected` / `got` / `fix` 等）；
- 台账那一行的 finding 形状是 `verifications.parse_verdict` 钉死的四格，六格的值
  因此全部写进 `detail` 那句人话 —— 判据读的是那一句（读的人也只有那一句）。
"""
from __future__ import annotations

import pathlib

import pytest

from test_the_v_audits_the_dependency_face import (
    _agent, _bits, _manuscript as _v_manuscript, _put, _row,
)

from agentflow import depsection as DS
from agentflow.store import Store

TS = "2026-11-06T00:00:00+08:00"
SID = "000007"
CITE = "000001"
WEAK = "000002"
GONE = "000099"
FULL = "主命题：这一份手稿的依赖面要被逐条核。"
CITE_FULL = "引理甲：对任意有限图 G 都成立。"
WEAK_FULL = "引理乙：存在一个反例图。"
HEAD = ("| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | "
        "路径号（第几条证明） |\n|---|---|---|---|\n")


# ---------------------------------------------------------------- 夹具


def _manuscript(*, body: str, rows: str = "", sid: str = "") -> str:
    """一份最小手稿（证明一节 + 依赖一节；三列表头逐字与解析器对齐）。"""
    return ("# F 的证明手稿：判据\n\n"
            + (f"- 命题号：stmt:{sid}\n\n" if sid else "")
            + "## 命题\n\n判据命题（夹具）。\n\n## 证明\n\n" + body + "\n\n"
            + "## 依赖\n\n" + HEAD + rows)


def _ledger(*, cite_grade: str = "pre_theorem") -> list[dict]:
    """台账三档：够格的一条、不够格的一条（两条都在册）。"""
    reviewed = cite_grade == "pre_theorem"
    return [
        {"stmt_id": CITE, "status": "active", "kind": "theorem",
         "statement_full": CITE_FULL, "statement_text": "引理甲",
         "label": "引理甲", "proof_text": "证明：由定义直接得到。",
         "bits": _bits(reviewed=reviewed)},
        {"stmt_id": WEAK, "status": "active", "kind": "theorem",
         "statement_full": WEAK_FULL, "statement_text": "引理乙",
         "label": "引理乙", "proof_text": "证明：尚无 V 签。",
         "bits": _bits(reviewed=False)},
    ]


def _body_unknown() -> str:
    return f"1. 由 stmt:{GONE} 直接推出结论。\n2. 于是主命题成立。"


def _body_cite() -> str:
    return f"1. 由 stmt:{CITE} 的结论直接推出。\n2. 于是主命题成立。"


# ---------------------------------------------------------------- 判据工具


def _text_cells(text: str, sid: str, *, kind: str = "") -> None:
    """人话必须逐字带四件：号 / 在哪一步 / 类别（受控码与类别名）/ 怎么改。"""
    assert f"stmt:{sid}" in text, text
    assert "在哪一步" in text, text
    assert "怎么改" in text, text
    assert "期望：" in text and "实得：" in text, text
    if kind:
        assert kind in text, text
        assert DS.CITATION_KIND_LABELS[kind] in text, text


def _six_cells(record: dict) -> None:
    """结构化六格必须齐且非空（空串 = 那一格没给，读的人要多猜一次）。"""
    for key in DS.FINDING_CELLS:
        assert str(record.get(key) or "").strip(), (key, record)
    _text_cells(str(record.get("detail") or ""), str(record.get("stmt_id") or ""),
                kind=str(record.get("kind") or ""))


# ============================================================ a 不在册
def test_a_v_feedback_names_the_missing_statement_and_the_step() -> None:
    """a（V）：正文点一个不在册的号 ⇒ finding 逐字含号 / 在哪一步 / 不在册 / 怎么改。"""
    body = _body_unknown()
    got = DS.dependency_review(
        _manuscript(body=body, rows=f"| 某条不存在的引理 | stmt:{GONE} | 第 1 步 | 1 |\n"),
        _ledger())

    assert got.get("checked") is True and got.get("ok") is False, got
    finding = next(f for f in got["findings"] if f.get("stmt_id") == GONE)
    _six_cells(finding)
    assert finding["kind"] == DS.REFUSED_UNKNOWN_SOURCE, finding
    assert DS.CITATION_KIND_LABELS[finding["kind"]] in finding["detail"], finding
    assert "不在册" in finding["detail"], finding
    assert "F 读不到它" in finding["detail"], finding
    assert "第 1 步" in finding["detail"], finding


def test_a_v_finding_survives_into_the_ledger_row_and_the_return(
        tmp_path: pathlib.Path) -> None:
    """a（V 的台账那一行）：六格的值进 `detail`，返回读数里逐字可读。

    台账那一行的 finding 形状由 `verifications.parse_verdict` 钉死为四格（level /
    step / kind / detail，另一个落点）—— 所以这里读的是 `detail` 那句人话，
    不是 `stmt_id` 键（键只在 `depsection.dependency_review` 的返回里有）。
    """
    st = Store(tmp_path / "ws")
    st.init()
    body = _body_unknown()
    _put(st, SID, full=FULL, bits=_bits(), label="主命题", proof_text=body)
    rel = _v_manuscript(st, body=body, rows=[_row(GONE, "某条不存在的引理")])
    agent, _review = _agent(st)

    got = agent.verify_proof(SID, proof_text=body, proof_manuscript=rel)

    assert got.get("verdict") == "有毛病", got
    finding = next(f for f in got["findings"]
                   if f"stmt:{GONE}" in str(f.get("detail") or ""))
    _text_cells(str(finding.get("detail") or ""), GONE, kind=str(finding["kind"]))
    # 2026-11-08：V 不读册 ⇒ 它不能声称"不在册"，能说的是"盘上没有这一条命题的手稿"。
    assert "盘上没有" in finding["detail"], finding
    assert "手稿" in finding["detail"], finding
    assert finding["kind"] == DS.REFUSED_LEVEL_UNREADABLE, finding


def test_a_b_refusal_letter_names_the_missing_statement(tmp_path: pathlib.Path) -> None:
    """a（B）：收方拒信（`error` 那句 + `findings` 六格）逐字含号 / 在哪一步 / 不在册 / 怎么改。"""
    from agentflow.agent_b import AgentB

    store = Store(tmp_path / "ws")
    store.init()
    body = _body_unknown()
    manuscript = _manuscript(body=body, rows=f"| 某条引理 | stmt:{GONE} | 第 1 步 | 1 |\n",
                             sid=SID)
    got = AgentB(store, extractor=None, extract_text=None, config={}).register_statement(
        statement_full=FULL, statement_text=FULL[:24], proof_text=body,
        proof_manuscript=manuscript, origin="own_result", kind="conjecture",
        quote_reason="判据夹具：自产命题", doc_id=SID)

    assert got.get("ok") is False, got
    assert got.get("kind") == DS.REFUSED_UNKNOWN_SOURCE, got
    err = str(got.get("error") or "")
    _text_cells(err, GONE, kind=str(got.get("kind") or ""))
    assert "不在册" in err and "F 读不到它" in err, err
    finding = next(f for f in (got.get("findings") or [])
                   if f.get("stmt_id") == GONE)
    _six_cells(finding)
    assert store.rows("dependencies") == [], store.rows("dependencies")


# ============================================================ b 等级不到
def test_b_feedback_names_the_level_and_the_floor() -> None:
    """b（V）：在册但 `conjecture` 的号 ⇒ 逐字含号 / 等级 conjecture / 门槛 pre_theorem / 怎么改。"""
    body = f"1. 由 stmt:{WEAK} 的结论直接推出。\n2. 于是主命题成立。"
    got = DS.dependency_review(
        _manuscript(body=body, rows=f"| 上下文引理 | stmt:{WEAK} | 第 1 步 | 1 |\n"),
        _ledger())

    finding = next(f for f in got["findings"] if f.get("stmt_id") == WEAK)
    _six_cells(finding)
    assert finding["kind"] == DS.REFUSED_LEVEL_TOO_LOW, finding
    text = finding["detail"]
    _text_cells(text, WEAK, kind=str(finding["kind"]))
    assert "等级 conjecture" in text, text
    assert f"门槛 {DS.CITATION_MIN_LEVEL}" in text, text
    assert f"引用要求 {DS.CITATION_MIN_LEVEL} 级及以上" in text, text


def test_b_gate_rows_carries_the_same_four_tuple() -> None:
    """b（`gate_rows`）：同一句话从 gate 出来，带行号与表里写的步号。"""
    gate = DS.gate_rows([{"stmt_id": WEAK, "line": 9, "step": "第 2 步"}], _ledger())

    assert gate.get("ok") is False, gate
    assert gate.get("refused") == DS.REFUSED_LEVEL_TOO_LOW, gate
    _six_cells(gate["finding"])
    assert gate["finding"]["stmt_id"] == WEAK, gate["finding"]
    assert "依赖段第 9 行" in gate["reason"], gate["reason"]
    assert "第 2 步" in gate["reason"], gate["reason"]


# ============================================================ c 引错内容
def test_c_a_quote_that_belongs_to_another_statement_is_named() -> None:
    """c：引文那一格写的是另一条在册命题的原文 ⇒ 受控码 + 对比读数 + 怎么改。"""
    body = _body_cite()
    # 表里那一行点的是 CITE，引文却是 WEAK 的原文（引错内容）。
    got = DS.dependency_review(
        _manuscript(body=body, rows=f"| {WEAK_FULL} | stmt:{CITE} | 第 1 步 | 1 |\n"),
        _ledger())

    assert got.get("ok") is False, got
    finding = next(f for f in got["findings"]
                   if f.get("kind") == DS.REFUSED_QUOTE_MISMATCH)
    _six_cells(finding)
    text = finding["detail"]
    _text_cells(text, CITE, kind=DS.REFUSED_QUOTE_MISMATCH)
    assert "引文" in text, text
    # 对比读数两头都在：被引命题的原文 + 引文实际属于谁。
    assert CITE_FULL.rstrip("。")[:8] in text, text
    assert WEAK_FULL.rstrip("。")[:8] in text, text
    assert f"stmt:{WEAK}" in text, text
    assert "改号或改引文" in text, text


def test_c_a_step_quotation_of_the_cited_statement_is_not_a_defect() -> None:
    """c（正控）：引文对得上被引命题自己 ⇒ 不报（否则正常手稿会被判红）。"""
    body = _body_cite()
    got = DS.dependency_review(
        _manuscript(body=body, rows=f"| {CITE_FULL} | stmt:{CITE} | 第 1 步 | 1 |\n"),
        _ledger())

    assert [f for f in got["findings"]
            if f.get("kind") == DS.REFUSED_QUOTE_MISMATCH] == [], got["findings"]


# ============================================================ d 步号 / 表正文
def test_d_a_step_number_the_proof_does_not_have_is_named() -> None:
    """d（步号对不上）：表说第 3 步、正文只有第 1 步 ⇒ 号 + 哪一行哪一步 + 怎么改。"""
    body = _body_cite()
    got = DS.dependency_review(
        _manuscript(body=body, rows=f"| 上下文引理 | stmt:{CITE} | 第 3 步 | 1 |\n"),
        _ledger())

    finding = next(f for f in got["findings"]
                   if f.get("kind") == DS.REFUSED_STEP_MISMATCH)
    _six_cells(finding)
    text = finding["detail"]
    _text_cells(text, CITE, kind=DS.REFUSED_STEP_MISMATCH)
    assert "依赖段第" in text and "第 3 步" in text, text
    assert "怎么改" in text, text


def test_d_a_table_row_the_body_never_cites_is_named() -> None:
    """d（表多一行）：正文没点它 ⇒ 号 + 第几行 + 怎么改（两条都要能改对方向）。"""
    body = "1. 由定义直接计算。\n2. 于是主命题成立。"
    got = DS.dependency_review(
        _manuscript(body=body, rows=f"| 表里多出来的那一行 | stmt:{CITE} | 第 1 步 | 1 |\n"),
        _ledger())

    finding = next(f for f in got["findings"]
                   if f.get("kind") == DS.REFUSED_TABLE_DISAGREES)
    _six_cells(finding)
    text = finding["detail"]
    _text_cells(text, CITE, kind=DS.REFUSED_TABLE_DISAGREES)
    assert "依赖段第" in text, text
    assert "没有点" in text, text


def test_d_a_body_citation_missing_from_the_table_is_named() -> None:
    """d（正文点了表里没有）：`dependency_consistency_findings` 逐条给号 + 哪一步 + 怎么改。"""
    body = _body_cite()
    findings = DS.dependency_consistency_findings(
        _manuscript(body=body), known_ids={CITE}, statement_rows=_ledger())

    assert len(findings) == 1, findings
    _six_cells(findings[0])
    assert findings[0]["kind"] == DS.REFUSED_TABLE_DISAGREES, findings[0]
    _text_cells(findings[0]["detail"], CITE, kind=str(findings[0]["kind"]))
    assert "第 1 步" in findings[0]["detail"], findings[0]["detail"]
    code, why = DS.dependency_consistency_problem(
        _manuscript(body=body), known_ids={CITE}, statement_rows=_ledger())
    assert code == DS.REFUSED_TABLE_DISAGREES, (code, why)
    assert "怎么改" in why, why


# ============================================================ e 反真空
#: 六格里每一格的"摘掉"方式（值都从同一句人话里删；删了之后判据必须红）。
_CELL_DROPS: dict[str, tuple[str, str]] = {
    "号": (f"`stmt:{GONE}`", "stmt:"),
    "在哪一步": ("在哪一步", "在哪一步"),
    "类别": (DS.CITATION_KIND_LABELS[DS.REFUSED_UNKNOWN_SOURCE], "类别名"),
    "期望": ("期望：", "期望："),
    "实得": ("实得：", "实得："),
    "怎么改": ("怎么改", "怎么改"),
}


@pytest.mark.parametrize("cell", sorted(_CELL_DROPS))
def test_e_dropping_any_cell_turns_the_criterion_red(monkeypatch, cell: str) -> None:
    """e：把六格里任一格从人话里摘掉 ⇒ 同一条四元组判据必须红（不是永远绿）。"""
    needle, label = _CELL_DROPS[cell]
    real = DS.finding_sentence

    def crippled(record, _needle: str = needle):
        return str(real(record)).replace(_needle, "")

    monkeypatch.setattr(DS, "finding_sentence", crippled)
    record = DS.uncitable_statement_finding(GONE, _ledger(), where="证明正文", step=1)
    with pytest.raises(AssertionError):
        _text_cells(str(record.get("detail") or ""), GONE,
                    kind=DS.REFUSED_UNKNOWN_SOURCE)
    # 对照：不打桩时同一格是能过的（证明上面那条红来自被摘掉的那一格）。
    monkeypatch.undo()
    good = DS.uncitable_statement_finding(GONE, _ledger(), where="证明正文", step=1)
    _text_cells(str(good.get("detail") or ""), GONE, kind=DS.REFUSED_UNKNOWN_SOURCE)
    assert label, cell


# ============================================================ g 不许混类
def test_g_two_kinds_never_share_one_sentence() -> None:
    """g：不在册与等级不到各有各的类别名，人话互不借用对方的类别。"""
    missing = DS.uncitable_statement_finding(GONE, _ledger(), where="证明正文", step=1)
    low = DS.uncitable_statement_finding(WEAK, _ledger(), where="证明正文", step=1)

    assert missing["kind"] != low["kind"], (missing, low)
    labels = list(DS.CITATION_KIND_LABELS.values())
    assert len(labels) == len(set(labels)), "类别名必须一码一名（有两条码共用一个名字）"
    assert DS.CITATION_KIND_LABELS[missing["kind"]] not in low["detail"], low["detail"]
    assert DS.CITATION_KIND_LABELS[low["kind"]] not in missing["detail"], missing["detail"]
    assert "不在册" not in low["detail"], low["detail"]
    assert "等级" not in missing["detail"], missing["detail"]
