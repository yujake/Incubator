# -*- coding: utf-8 -*-
"""判据（B2）：非平凡性档位按「证明花的力气」判，不按「会不会被用到 / 比已知强在哪」。

## 业主口径（逐字，唯一权威）

「"后面哪一步会用到它 / 比已知那条强在哪"这俩和非平凡度有啥关系？不一定一条定理后面
要用，也不一定存在"已知那条"，「看证明花的力气就能判非平凡度」。

## 真机证据（sylow4 的 `out/secretary/nontriviality.jsonl`，11 行 / 8 个 sha）

- `e3b0c442…`（0 字）⇒ 档位 None，"无任何命题或证明内容，无法定档" —— 这种行根本不该
  走到判档，应该在写侧/判档位入口受控拒绝；
- `2620321f…`（8375 字）⇒ 档位 None，basis "待判命题未明确且证明截断，无法定档" ——
  正文被截断（材料 JSON 在 4000 字处被切）却报成"材料不足"；
- 其余 6 条全部 T0，理由全是旧口径那两句 ⇒ 说明业主的裁定还没落地。

## 六条判据与各自的「改前红」

改前 = 这一批之前 HEAD 上的三份文件（`secretary.py` / `register_statement.py` /
`specs/b.py`）。下面每条都写明它在改前为什么红 —— 判据自己的读取面就是证据，
不靠"我记得它以前会错"。

| 判据 | 它要证明的事 | 改前为什么红 |
|---|---|---|
| a | 0 字命题 / 0 字证明受控拒绝，且不落档位台账 | 改前 `judge_statement("")` 照样发一次判断、落一行 None；写侧报 `bad_statement` 而不是 `empty_statement_text` |
| b | 正文被截断 ⇒ `text_truncated` + "输入不完整" | 改前超 4000 字静默切断，没有这个键（KeyError 级红） |
| c | 体量大 + 多条引理 + 跨两簇 ⇒ T2 以上 | 旧判据（"没人用到"）把它压成 T0 |
| d | 三行、只用定义 ⇒ T0（正控） | 改前档位直接取模型自报的 3 ⇒ 判成 T3 |
| e | 旧口径那两格留空 / 写反 ⇒ 档位仍按力气给 | 旧判据把留空当成"答不上来" ⇒ 压 T0 |
| f | 反真空：读数全 0 ⇒ c 红；落格恒 T3 ⇒ d 红 | （这一条测的是上面两条有没有牙） |

零模型钱：这一份里所有判断都走打桩的 `Secretary.judge`（它只吃材料、按剧本回结论），
一次真实模型调用都不发；工作区全在 `tmp_path`。
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any, Mapping

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import refusals as R
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.agent_b import AgentB
from agentflow.store import Store


def _register_statement_module() -> Any:
    """写侧那个模块（延迟导入：改前它没有这一批符号，(a)(b) 的"红"就落在这一行上）。

    为什么不在文件头上直接 import：那样整份判据会在收集期就 ImportError，
    六条判据一条都跑不到 —— 而"改前红"要能逐条读，不能只有一句收集失败。
    """
    from agentflow.agent_b import register_statement as module

    return module

#: 判「太平凡」的旧口径判官：`why_this_is_not_trivial` 为空 ⇒ 太平凡 + 0 档；
#: 写了 ⇒ 合格 + 自报 3 档。它逐字复刻改前那两条判据的行为，所以下面 (c)(d)(e) 的
#: "改前红"是这份剧本给的，不是我口头说的。
_OLD_CRITERIA_REASON = "材料未指出后续哪条证明会用到它，也没说明它比已知的强在哪"


def _old_criteria_judge(kind: str, context: Mapping[str, Any], *,
                        task_id: str = "") -> dict[str, Any]:
    assert kind == "statement_aesthetic", kind
    hint = str(context.get("why_this_is_not_trivial") or "").strip()
    if not hint:
        return {"checked": True, "decision": "太平凡", "reason": _OLD_CRITERIA_REASON,
                "basis": ["没有使用者", "不比已知强"], "nontriviality": 0,
                "nontriviality_basis": "两条判据都答不上 ⇒ 按基础定理记 0"}
    return {"checked": True, "decision": "合格", "reason": "有使用者、也比已知强",
            "basis": [hint[:80]], "nontriviality": 3,
            "nontriviality_basis": "自报三档"}


def _secretary(tmp_path: pathlib.Path, judge: Any = _old_criteria_judge) -> tuple[SEC.Secretary, pathlib.Path]:
    """一个 B 的秘书（打桩判断面，零模型调用）；返回 `(秘书, 工作区根)`。"""
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    sec = SEC.Secretary("B", root=root)
    sec.judge = judge  # type: ignore[assignment]
    return sec, root


def _ledger_rows(root: pathlib.Path) -> list[dict[str, Any]]:
    path = SEC.nontriviality_path(root)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------- 夹具：两份证明

#: (d) 的正控：三行、只用定义。力气读数应当全 0（体量小、步骤不到 6、没有引理、单一工具簇）。
_SMALL_PROOF = """证明：由定义直接得到。
1. 按定义，向量空间的零元唯一。
2. 设 x 与 y 都是零元，则 x = x + y = y。
3. 所以零元唯一。∎"""


def _big_proof(*, chars: int = 6000, lemmas: int = 6, steps: int = 12) -> str:
    """(c) 的夹具：体量大 + 引了 6 条引理 + 跨两个工具簇（群作用 / 计数同余）。

    刻意不含"不使用 / 绕开"这类词：那会让绕路读数也 +1，掩盖"前三项就能到 T2"这件事。
    """
    lines = ["证明正文（判据夹具：体量大 + 多条引理 + 跨两簇）"]
    for i in range(1, lemmas + 1):
        lines.append(f"引理 {i}：由群作用与轨道—稳定化子得到 |G| = |轨道| · |稳定化子|。")
    for i in range(1, steps + 1):
        lines.append(f"{i}. 第 {i} 步：把链长记作 m，按同余 mod p 与整除关系统计计数。")
    body = "\n".join(lines)
    pad = "（此处为推导细节，逐字展开略）"
    while len(body) < chars:
        body += pad
    return body


# ---------------------------------------------------------------- a）0 字正文

def test_a_empty_statement_text_is_refused_by_the_write_side() -> None:
    """(a) 写侧：0 字命题 ⇒ 受控拒绝 `empty_statement_text`（改前是 `bad_statement`）。

    改前读数是 `bad_statement`（那一档把"只有短版"与"0 字"混在一起），而判档位那一侧
    根本没有这一格 —— 于是同一种输入在两个地方拿到两个名字。
    """
    got = _register_statement_module()._RegisterStatement().register_statement(statement_full="   ")
    assert got["ok"] is False, got
    assert got["kind"] == R.EMPTY_STATEMENT_TEXT, got
    assert R.EMPTY_STATEMENT_TEXT == "empty_statement_text", R.EMPTY_STATEMENT_TEXT
    assert got["refusal_reason"] == "invalid_params", got


def test_a_a_declared_empty_proof_is_refused_at_both_write_points() -> None:
    """(a) 写侧：声明了第 N 份证明而正文是空的 ⇒ `empty_proof_text`，两个写入口同一句话。

    两个写入口：登记入口（`_normalize_proofs`）与追加入口（`_attach_proofs`）。
    只拦一个 = 清单从另一条路进来时静默写一条空证明。
    """
    from agentflow.agent_b.register_statement import _normalize_proofs

    _listed, _canon, bad = _normalize_proofs([{"proof_no": 2, "text": "   "}], proof_text="")
    assert bad is not None and bad["kind"] == R.EMPTY_PROOF_TEXT, bad
    attach = _register_statement_module()._RegisterStatement()._attach_proofs(
        "stmt:000001", [{"proof_no": 2, "text": " \n "}])
    assert attach["written"] is False, attach
    assert attach["refused"] == R.EMPTY_PROOF_TEXT, attach


def test_a_an_empty_statement_is_not_judged_and_leaves_no_tier_row(tmp_path: pathlib.Path) -> None:
    """(a) 判档位侧：0 字正文不进判档流程 —— 不发判断、不落台账（改前会落一行 None）。"""
    calls: list[str] = []

    def _should_not_be_called(kind: str, context: Mapping[str, Any], *, task_id: str = "") -> dict:
        calls.append(kind)
        return {"checked": True, "decision": "判不了", "reason": "无任何命题或证明内容",
                "basis": [], "nontriviality": None, "nontriviality_basis": ""}

    sec, root = _secretary(tmp_path, _should_not_be_called)
    got = sec.judge_statement(statement_full="", task_id="t-a")
    assert calls == [], f"0 字正文不该发判断（发了 {calls}）"
    assert got["checked"] is False, got
    assert got["code"] == R.EMPTY_STATEMENT_TEXT, got
    assert got["nontriviality"] is None and got["nontriviality_tri"] == "unjudged", got
    assert _ledger_rows(root) == [], "0 字正文落了一行档位台账（改前那个形态）"

    # 反真空：同一名秘书、换一条有正文的命题 ⇒ 判断真的发生、台账真的落一行。
    ok = sec.judge_statement(statement_full=_SMALL_PROOF, task_id="t-a2")
    assert calls == ["statement_aesthetic"], calls
    assert ok["checked"] is True and ok["nontriviality"] == 0, ok
    assert len(_ledger_rows(root)) == 1, _ledger_rows(root)


# ---------------------------------------------------------------- b）截断要显式报

def test_b_a_truncated_body_is_reported_as_incomplete_input(tmp_path: pathlib.Path) -> None:
    """(b) 正文超上限 ⇒ 结果带 `text_truncated`，文案说"输入不完整"，且档位是 None。

    改前：材料 JSON 在 4000 字处静默切断，结果里没有 `text_truncated` 这一格，
    模型只能回一句"证明截断，无法定档"，台账把它记成"材料不足"。
    """
    body = _big_proof(chars=SEC.PROOF_BODY_CAP + 5000)
    assert len(body) > SEC.PROOF_BODY_CAP

    def _says_insufficient_material(kind: str, context: Mapping[str, Any], *, task_id: str = "") -> dict:
        return {"checked": True, "decision": "判不了", "reason": "材料不足，无法定档",
                "basis": [], "nontriviality": None, "nontriviality_basis": ""}

    sec, root = _secretary(tmp_path, _says_insufficient_material)
    got = sec.judge_statement(statement_full=body, task_id="t-b")
    assert got.get("text_truncated") is True, got
    assert got["nontriviality"] is None and got["nontriviality_tri"] == "unjudged", got
    basis = str(got["nontriviality_basis"])
    assert "输入不完整" in basis, basis
    assert "被截断" in basis, basis
    assert f"{SEC.PROOF_BODY_CAP} 字处" in basis, basis
    # "材料不足"只许出现在"不是因为材料不足"这一句里（别处出现就是在甩锅）。
    assert basis.count("材料不足") == 1, basis
    assert "不是因为材料不足" in basis, basis
    rows = _ledger_rows(root)
    assert len(rows) == 1 and rows[0]["text_truncated"] is True, rows
    assert rows[0]["nontriviality"] is None, rows[0]


def test_b_the_write_side_reports_the_same_truncation_reading(tmp_path: pathlib.Path) -> None:
    """(b) 写侧：同一份超长正文 ⇒ 工具结果里带同一格 `text_truncated`（不写盘不动库）。"""
    body = _big_proof(chars=SEC.PROOF_BODY_CAP + 1000)
    reading = _register_statement_module()._text_truncation_reading(statement_full=body, proof_text="", proofs=None)
    assert reading.get("text_truncated") is True, reading
    assert "输入不完整" in str(reading.get("text_truncated_note")), reading
    assert reading["tier_material"]["cap"] == SEC.PROOF_BODY_CAP, reading
    # 短正文不报（否则"每一条都截断"会变成噪音，读数贬值）。
    assert _register_statement_module()._text_truncation_reading(statement_full=_SMALL_PROOF, proof_text="", proofs=None) == {}

    # 真走一次登记（零模型调用）：这一笔的证明正文超了判档位的读取上限 ⇒ 结果里带那三格。
    store = Store(tmp_path / "ws-b")
    store.init()
    agent = AgentB(store, extractor=None, extract_text=None, config={})
    out = agent.register_statement(
        statement_full="设 G 是 3-正则群；则弦长函数不是常值。",
        statement_text="弦长函数不是常值", origin="own_result", kind="conjecture",
        doc_id=S.format_id(0), quote_reason="我方自产命题，没有外部引文要比对",
        proof_text=body)
    assert out["ok"] is True, out
    assert out.get("text_truncated") is True, out
    assert "输入不完整" in str(out.get("text_truncated_note")), out.get("text_truncated_note")


# ---------------------------------------------------------------- c/d/e）按力气判

def _tier_of(sec: SEC.Secretary, statement_full: str, *, hint: str = "") -> dict[str, Any]:
    return sec.judge_statement(statement_full=statement_full, basis_hint=hint, task_id="t-tier")


def test_c_a_big_proof_with_many_lemmas_and_two_clusters_is_t2_or_above(
        tmp_path: pathlib.Path) -> None:
    """(c) 体量大 + 6 条引理 + 跨两簇 ⇒ T2 以上（改前：旧判据"没人用到"压成 T0）。"""
    sec, root = _secretary(tmp_path)
    body = _big_proof()
    got = _tier_of(sec, body)
    effort = dict(got.get("effort") or {})
    assert effort.get("chars", 0) >= 6000, effort
    assert effort.get("lemmas", 0) >= 6, effort
    assert effort.get("clusters", 0) >= 2, effort
    assert got["nontriviality"] is not None, got
    assert got["nontriviality"] >= 2, (got["nontriviality"], effort, got["nontriviality_basis"])
    assert got["nontriviality_tri"] == "computed", got
    assert "力气" in str(got["nontriviality_basis"]), got["nontriviality_basis"]
    assert _ledger_rows(root)[-1]["nontriviality"] == got["nontriviality"], _ledger_rows(root)


def test_d_a_three_line_proof_that_only_uses_definitions_stays_t0(tmp_path: pathlib.Path) -> None:
    """(d) 三行、只用定义 ⇒ T0（正控；改前：档位取模型自报的 3 ⇒ 判成 T3）。"""
    sec, _root = _secretary(tmp_path)
    got = _tier_of(sec, _SMALL_PROOF, hint="它有使用者，也比已知的强")
    effort = dict(got.get("effort") or {})
    assert effort.get("chars", 0) < 2000, effort
    assert effort.get("lemmas", 0) == 0, effort
    assert got["nontriviality"] == 0, (got["nontriviality"], effort, got["nontriviality_basis"])
    assert got["label"] == "T0", got
    # 模型自报 3 与读数不一致 ⇒ 以读数为准，并且这件事要写进 basis（不许静默改）。
    assert "不一致" in str(got["nontriviality_basis"]), got["nontriviality_basis"]


def test_e_the_two_old_questions_are_not_criteria(tmp_path: pathlib.Path) -> None:
    """(e) 「会用到它 / 比已知强在哪」留空或写反 ⇒ 档位仍按力气给（改前：留空 ⇒ T0）。"""
    body = _big_proof()
    blank = _secretary(tmp_path / "blank")
    denied = _secretary(tmp_path / "denied")
    got_blank = _tier_of(blank[0], body, hint="")
    got_denied = _tier_of(denied[0], body,
                          hint="后面没有任何一条证明会用到它；它也不比已知的 Sylow 强在哪")
    assert got_blank["nontriviality"] is not None, got_blank
    assert got_blank["nontriviality"] >= 2, (got_blank["nontriviality"], got_blank["nontriviality_basis"])
    # 两格写不同的话，档位一模一样 ⇒ 那两格确实不作判据。
    assert got_denied["nontriviality"] == got_blank["nontriviality"], (
        got_blank["nontriviality"], got_denied["nontriviality"])
    # 档位要归因到力气读数上，而不是归因到旧那两问（旧口径的原话不该出现在 basis 里当理由）。
    assert "按力气读数判" in str(got_blank["nontriviality_basis"]), got_blank["nontriviality_basis"]
    assert _OLD_CRITERIA_REASON not in str(got_blank["nontriviality_basis"]), (
        got_blank["nontriviality_basis"])


# ---------------------------------------------------------------- f）反真空

def test_f_zeroed_effort_readings_break_the_big_proof_case(monkeypatch: pytest.MonkeyPatch,
                                                           tmp_path: pathlib.Path) -> None:
    """(f) 反真空：把力气读数打桩成全 0 ⇒ (c) 必须红（说明 T2+ 真是读数给的）。"""
    zeros = {"chars": 0, "steps": 0, "lemmas": 0, "lemma_names": [], "theorems": 0,
             "clusters": 0, "cluster_names": [], "cluster_evidence": {},
             "detour": False, "detour_words": [], "score": 0, "body_chars": 0,
             "body_from": "", "missing": [], "text_truncated": False, "truncated_at": 0}
    monkeypatch.setattr(SEC, "proof_effort_readings", lambda **kw: dict(zeros))
    sec, _root = _secretary(tmp_path)
    got = _tier_of(sec, _big_proof())
    assert got["nontriviality"] == 0, (
        "读数全 0 之后那份「体量大 + 6 条引理 + 跨两簇」的证明仍然不是 T0 ⇒ "
        f"档位不是读数给的：{got.get('nontriviality')} / {got.get('nontriviality_basis')}")


def test_f_a_stuck_t3_faller_breaks_the_three_line_case(monkeypatch: pytest.MonkeyPatch,
                                                        tmp_path: pathlib.Path) -> None:
    """(f) 反真空：把落格函数打桩成恒 T3 ⇒ (d) 必须红（说明 T0 真是落格给的）。"""
    monkeypatch.setattr(SEC, "nontriviality_from_effort",
                        lambda readings: {"level": 3, "label": "T3", "band": "T3",
                                          "score": 99, "missing": [], "why": "打桩恒 T3"})
    sec, _root = _secretary(tmp_path)
    got = _tier_of(sec, _SMALL_PROOF, hint="它有使用者，也比已知的强")
    assert got["nontriviality"] == 3, (
        "落格恒 T3 之后三行证明不是 T3 ⇒ 档位不是落格给的："
        f"{got.get('nontriviality')} / {got.get('nontriviality_basis')}")
