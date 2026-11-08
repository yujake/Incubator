# -*- coding: utf-8 -*-
"""判据①：收工读数要能抓住「命题同一性判定从未发生」（业主 2026-11-08」。

## 真机背景（`secretary.seam_for_secretary` 的 docstring 逐字记着）

真机 sylow5：B 的秘书在 `agent_b/core.py` 用 `for_role_wired`（带缝）；而"设置里
`secretary` 那一档没有 key"时 `seam_for_secretary` 返回 `None` ⇒ 这一趟的判定整条链
是死的。后果：同一条定理被登记 2–3 次，而 `out/secretary/proposition_verdicts.jsonl`
一次都没建出来。会话里没有任何一格说"这一条判定根本没发生"。

## 这一份钉的四条

| 条 | 它要证明的事 |
|---|---|
| a | 有登记动作、判定 0 次 ⇒ 读数 `judged_zero=true` + 一条 warning 命中（贴读数） |
| b | 正常带缝的一趟 ⇒ 判定台账有行、不报 |
| c | 读不成（没有工作区根）⇒ `checked=false` + 原因（没查成不是"0 次"） |
| d | 反真空：0 次登记 + 0 行判定 ⇒ 不报（证明触发条件不是恒真） |
| e | 出现过 `seam_source=none` ⇒ 即使有判定行也报 |

## 分级

这一格是 warning（不是 blocker）：同类的接线 / 可见性读数（`statements_unoptimized`
/ `suspected_splits` / `proposition_form`）都是 readings + warning；而且裸秘书工作区
（既有判据里那批）不该因为"没缝"就收不了工 —— 那是改门强度，不是加读数。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import closing as CL
from agentflow import secretary as SEC
from agentflow import sessions as SS
from agentflow.secretary import Secretary
from agentflow.store import Store

FULL = "设 G 是 3-正则群；则弦长函数不是常值。"
CODE = "proposition_judgment_never_ran"


class _Seam:
    """一条"判了、判的是不同"的假模型缝（零网络：`ask_json` 立刻回一份合法 JSON）。"""

    class _Call:
        ok = True
        problem = ""
        detail = ""

    def ask_json(self, prompt, **kw):
        return ({"decision": "different", "canonical_name": "", "same_as": "",
                 "route": "", "condition": "", "conclusion": "",
                 "basis": ["夹具：判 different"], "reason": "夹具：判 different"},
                self._Call())


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _own(full: str = FULL) -> dict:
    return {"statement_full": full, "statement_text": full[:24],
            "origin": "own_result", "kind": "conjecture", "doc_id": "0000",
            "quote_reason": "我方自产命题，没有外部引文要比对"}


def _findings(rep: CL.ClosingReport) -> list[dict]:
    return [f.to_dict() for f in rep.findings]


def _codes(rep: CL.ClosingReport) -> list[str]:
    return [str(f.get("code") or "") for f in _findings(rep)]


def _session_step(root: pathlib.Path, name: str = "own.register_statement",
                  sid: str = "s1") -> None:
    """在会话台账里落一条"登记动作"步（`agent_step` + payload.name）。"""
    _path, problem = SS.append(root, {"kind": "agent_step",
                                      "payload": {"name": name, "args": {}}}, sid=sid)
    assert not problem, problem


# ============================================================ a：有登记、判定 0 次

def test_a_registration_without_any_judgment_is_reported(tmp_path: pathlib.Path) -> None:
    """a：裸秘书（没有判断面）登记一条 ⇒ 判定台账 0 行、有登记动作 ⇒ warning。"""
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    # 夹具：造出"装配处没有缝"的那一档读数（真机 sylow5 的形态）。
    sec.model_source = "none（夹具：设置里 secretary 那一档没有 key）"
    got = sec.record_statement(_own(), role="B")
    assert got.get("created") is True, got
    _session_step(st.root)
    rep = CL.check_closing(st, checks=(), sid="s1")
    pj = dict(rep.readings.get("proposition_judgment") or {})
    assert pj.get("checked") is True, pj
    assert pj.get("verdict_rows") == 0, pj
    assert pj.get("registration_actions") == 1, pj
    assert pj.get("registration_scope") == "session", pj
    assert pj.get("judged_zero") is True, pj
    hits = [f for f in _findings(rep) if f.get("code") == CODE]
    assert hits, f"没有报出来：{_findings(rep)}"
    assert hits[0].get("level") == "warning", hits[0]
    assert "判定台账 0 行" in str(hits[0].get("detail") or ""), hits[0]


# ============================================================ b：正常带缝 ⇒ 不报

def test_b_a_wired_round_does_not_report(tmp_path: pathlib.Path) -> None:
    """b：带缝的一趟真的判了一次（台账 1 行）⇒ 同一格不报。"""
    st = _ws(tmp_path)
    sec = SEC.for_role_wired("B", root=st.root, store=st, seam=_Seam())
    got = sec.record_statement(_own(), role="B")
    assert got.get("created") is True, got
    _session_step(st.root)
    rep = CL.check_closing(st, checks=(), sid="s1")
    pj = dict(rep.readings.get("proposition_judgment") or {})
    assert pj.get("verdict_rows") == 1, pj
    assert pj.get("judged_zero") is False, pj
    assert pj.get("seam_none") == 0, pj
    assert CODE not in _codes(rep), _findings(rep)
    # 判词也落了行（`_proposition_adjudication` 带 seam_source，这是"分布"的来源）。
    rows = [dict(r) for r in st.rows("statements")]
    adj = dict((rows[0].get("_proposition_adjudication") or {}))
    assert adj.get("seam_source"), adj
    assert adj.get("checked") is True, adj


# ============================================================ c：读不成

def test_c_unreadable_is_not_zero() -> None:
    """c：没有工作区根 ⇒ `checked=False` + 原因（没查成不是"0 次判定"）。"""
    pj = CL.proposition_judgment_reading(None)
    assert pj.get("checked") is False, pj
    assert pj.get("reason"), pj


# ============================================================ d：反真空

def test_d_no_registration_and_no_judgment_does_not_report(tmp_path: pathlib.Path) -> None:
    """d（反真空）：0 次登记 + 0 行判定 ⇒ 不报（触发条件不是恒真）。"""
    st = _ws(tmp_path)
    rep = CL.check_closing(st, checks=())
    pj = dict(rep.readings.get("proposition_judgment") or {})
    assert pj.get("registration_actions") == 0, pj
    assert pj.get("verdict_rows") == 0, pj
    assert pj.get("judged_zero") is False, pj
    assert CODE not in _codes(rep), _findings(rep)


# ============================================================ e：seam_source=none

def test_e_seam_source_none_alone_reports(tmp_path: pathlib.Path) -> None:
    """e：`seam_source=none` 出现 ⇒ 即使判定台账不为 0 也要报（装配坏了的直接读数）。"""
    st = _ws(tmp_path)
    SEC.append_statement_same(
        st.root, stage="keywords", statement_full=FULL, checked=False,
        seam_source="none（夹具：设置里 secretary 那一档没有 key）",
        why="夹具：没有判断面")
    rep = CL.check_closing(st, checks=())
    pj = dict(rep.readings.get("proposition_judgment") or {})
    assert pj.get("seam_none") == 1, pj
    sources = [str(x.get("source") or "") for x in (pj.get("seam_sources") or [])]
    assert any(x.startswith("none") for x in sources), pj
    hits = [f for f in _findings(rep) if f.get("code") == CODE]
    assert hits, _findings(rep)
    assert "seam_source=none" in str(hits[0].get("detail") or ""), hits[0]
