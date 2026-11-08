# -*- coding: utf-8 -*-
"""判据：全仓"是不是同一条命题"的判定只剩一处实现（2026-11-08 块丙）。

## 改前是什么形态

两套判定各自成立、各自发模型调用、各自给答案：
- `Secretary.adjudicate_proposition`：题面 `_judge_system("proposition_identity")`，
  读 `decision` + `same_as`；
- `Secretary.judge_statement_same`：题面 `_statement_same_system`，读 `found` + `why`。

业主 2026-11-08 问的「语义判定」正是这一处 —— 同一件事两个实现，迟早给出两个答案。
这一份钉住：`judge_statement_same` 只剩形状翻译（它不再有自己的题面、不再自己发调用）。

## 四条

| 条 | 它要证明的事 |
|---|---|
| a | `judge_statement_same` 把候选递给 `adjudicate_proposition`（`candidates=` / `note=` / `use_cache=False`），自己不判 |
| b | 反向：把 `adjudicate_proposition` 的结论改成 different ⇒ 它的 `found` 当场变空（说明它没有第二套判据） |
| c | 源码层面：`judge_statement_same` 函数体里没有任何 `ask_json(`；`_statement_same_system` 已删 |
| d | 行为层面：同一条待收命题、同一批候选 ⇒ 两个入口给出同一个 `checked` / `verdict` / `same_as` |

## 边界

全部 tmp 工作区、零真实模型调用；`projects/` 只读；不碰 `agent_b/**`
（它今天还在调 `judge_statement_same`；下一笔改成 `adjudicate_proposition` 之后
本文件的 a/b 仍然成立）。
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.secretary import Secretary
from agentflow.store import Store

from conftest import seed_statement_row

IN_LEDGER = "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在。"
PARAPHRASE = "若 G 为有限群且 p 为素数，则它的 Sylow p-子群一定存在。"

_SOURCE = pathlib.Path(SEC.__file__).read_text(encoding="utf-8")


class _Call:
    ok = True
    problem = ""
    detail = ""


class _Seam:
    """按 note 回两问：挑词 → 关键词；判定 / 认定 → 两档结论。"""

    wired = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def ask_json(self, prompt, *, system: str = "", task_id: str = "", note: str = ""):
        self.calls.append(str(note))
        if str(note).endswith("statement_keywords"):
            return ({"keywords": ["Sylow", "p-子群"],
                     "why": "打桩：这两个数学词能把同义的那条捞出来"}, _Call())
        data = _material(prompt)
        candidates = [c for c in (data.get("candidates") or []) if isinstance(c, dict)]
        same_as = str(candidates[0]["stmt_id"]) if candidates else ""
        return ({
            "decision": "same" if same_as else "different",
            "same_as": same_as,
            "canonical_name": "Sylow I", "route": "",
            "condition": "打桩：都是有限群 + p 是素数",
            "conclusion": "打桩：都是 Sylow p-子群存在",
            "reason": "打桩：条件与结论一致" if same_as else "打桩：没有可并的候选",
            "basis": ["条件：一致", "结论：一致"],
        }, _Call())


def _material(prompt: str) -> dict:
    import json

    text = str(prompt or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return {}


def _ws(base: pathlib.Path) -> Store:
    st = Store(base / "ws")
    st.init()
    return st


def _seed(st: Store) -> str:
    row = seed_statement_row(st, statement_full=IN_LEDGER, statement_text=IN_LEDGER[:24],
                             kind="theorem", label="Sylow I")
    return str(row["stmt_id"])


def _sec(st: Store, seam=None) -> Secretary:
    return Secretary("B", root=st.root, store=st, seam=seam, enable_model=seam is not None)


# ============================================================ a：它只是把候选递过去

def test_judge_statement_same_only_hands_the_candidates_over(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """a：`judge_statement_same` 调 `adjudicate_proposition`（带 candidates/note/use_cache=False）。"""
    st = _ws(tmp_path)
    sid = _seed(st)
    seen: dict[str, Any] = {}

    def _sentinel(self, stmt_like, **kw):
        seen["payload"] = dict(stmt_like)
        seen["kw"] = dict(kw)
        return {"checked": True, "verdict": SEC._PK.STATE_SAME, "same_as": sid,
                "canonical_name": "Sylow I", "route": "", "condition": "c",
                "conclusion": "d", "basis": "打桩：条件与结论一致",
                "reason": "打桩：条件与结论一致", "candidates": [],
                "keywords": [], "hits_total": 1, "hits_named": [], "judged": True}

    monkeypatch.setattr(Secretary, "adjudicate_proposition", _sentinel)
    sec = _sec(st)
    got = sec.judge_statement_same(statement_full=PARAPHRASE, label="Sylow I",
                                   kind="conjecture",
                                   candidates=[{"stmt_id": sid, "label": "Sylow I",
                                                "statement_full": IN_LEDGER}])
    assert got["checked"] is True and got["found"] == sid, got
    assert seen["payload"]["statement_full"] == PARAPHRASE, seen
    assert [str(c.get("stmt_id") or "") for c in seen["kw"].get("candidates") or []] == [sid], seen
    assert seen["kw"].get("note") == "secretary:statement_same", seen
    assert seen["kw"].get("use_cache") is False, (
        f"这一档的候选是逐页给的，按正文 sha 缓存会把「这一页没查到」用到下一页：{seen['kw']}")


# ============================================================ b：它没有第二套判据

def test_flipping_the_one_judgment_flips_the_adapter(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """b：把唯一那一处判定改成 different ⇒ `judge_statement_same` 的 `found` 当场变空。"""
    st = _ws(tmp_path)
    sid = _seed(st)

    def _different(self, stmt_like, **kw):
        return {"checked": True, "verdict": SEC._PK.STATE_DIFFERENT, "same_as": "",
                "canonical_name": "", "route": "", "condition": "", "conclusion": "",
                "basis": "打桩：不同", "reason": "打桩：不同", "candidates": [],
                "keywords": [], "hits_total": 1, "hits_named": [], "judged": True}

    monkeypatch.setattr(Secretary, "adjudicate_proposition", _different)
    got = _sec(st).judge_statement_same(
        statement_full=PARAPHRASE, candidates=[{"stmt_id": sid}])
    assert got["checked"] is True, got
    assert got["found"] == "", got
    assert got["verdict"] == SEC._PK.STATE_DIFFERENT, got


# ============================================================ c：源码层面只有一处判定

def test_there_is_no_second_judgment_prompt_or_call(tmp_path: pathlib.Path) -> None:
    """c：`judge_statement_same` 的函数体里没有 `ask_json(`；重复题面已删。"""
    start = _SOURCE.index("    def judge_statement_same(")
    end = _SOURCE.index("    def _note_statement_same(", start)
    body = _SOURCE[start:end]
    assert "self.adjudicate_proposition(" in body, body
    assert "ask_json(" not in body, "这一档还在自己发模型调用 ⇒ 它还是第二套判定"
    assert "def _statement_same_system" not in _SOURCE, "重复的判定题面还在"
    assert not hasattr(SEC, "_statement_same_system"), "重复的判定题面还在"
    # 反真空：判定那一处真的存在（否则上面的"只剩一处"可能只是"一处都没有"）
    assert "def adjudicate_proposition(" in _SOURCE


# ============================================================ d：两个入口给同一个答案

def test_both_entries_give_the_same_answer(tmp_path: pathlib.Path) -> None:
    """d：同一条待收命题、同一批候选 ⇒ 主动查询与历史入口给出同一个判定。"""
    st = _ws(tmp_path)
    sid = _seed(st)
    seam = _Seam()
    sec = _sec(st, seam)
    active = sec.adjudicate_proposition({"statement_full": PARAPHRASE,
                                         "label": "Sylow I", "kind": "conjecture"})
    adapter = _sec(st, seam).judge_statement_same(
        statement_full=PARAPHRASE, label="Sylow I", kind="conjecture",
        candidates=[{"stmt_id": sid, "label": "Sylow I", "statement_full": IN_LEDGER}])
    assert active["checked"] is True and adapter["checked"] is True, (active, adapter)
    assert active["verdict"] == adapter["verdict"] == SEC._PK.STATE_SAME, (active, adapter)
    assert active["same_as"] == adapter["same_as"] == adapter["found"] == sid, (active, adapter)
    # 两个入口各自一次判定调用（挑词只在主动查询那一趟发生）——不是两次判定。
    assert seam.calls.count("secretary:proposition_identity") == 1, seam.calls
    assert seam.calls.count("secretary:statement_same") == 1, seam.calls


if __name__ == "__main__":          # pragma: no cover - 手动跑这一份时用
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
