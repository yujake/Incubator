# -*- coding: utf-8 -*-
"""判据①（2026-11-08 业主 sylow5 的误报）：判定"发生过"必须**两本账合读**。

## 误报现场（改前）

B 主路走 `judge_statement_same(use_cache=False)`（`secretary.py` 的薄适配：候选逐页给，
按正文 sha 缓存会把"这一页没查到"沿用到下一页）⇒ 它**只写** `statement_same.jsonl`，
**不写** `proposition_verdicts.jsonl`。而 `closing.proposition_judgment_reading` 改前只数
后者 ⇒ 探针实测 `verdict_rows=0, registration_actions=1, judged_zero=true`，而
`seam_sources` 两条都说明判过 —— 收工读数在说谎。

## 这一份钉的四条

| 条 | 它要证明的事 |
|---|---|
| a | 只有 `statement_same`（stage=judge）那一本有行 ⇒ `judged_zero=False`、不报 warning |
| b | 两本账各自的读数都在（`judged_by_ledger` 逐本 + `judged_rows` 合计） |
| c | 反真空（只读一本 ⇒ 复现误报）：`verdict_rows==0 且 registration_actions>=1` 这个旧判据式仍成立，而 `judged_zero` 必须 False —— 证明绿是"合读"带来的 |
| d | 反真空之二：`statement_same` 里的 `keywords` / `retrieval` 行**不算**判过（否则"没判成的尝试"会被数成"判过了"） |

零网络、全部 tmp 工作区、不读写 `projects/`。
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
from agentflow.store import Store

FULL = "设 G 是有限群；则 G 的阶整除它的中心化子的阶的乘积。"
CODE = "proposition_judgment_never_ran"
CANDIDATES = [{"stmt_id": "000000", "label": "在册的那一条",
               "statement_full": "设 H 是另一个群；则 H 的阶是偶数。"}]


class _Seam:
    """一条"判了、判的是不同"的假模型缝（零网络：`ask_json` 立刻回合法 JSON）。"""

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


def _session_step(root: pathlib.Path) -> None:
    _path, problem = SS.append(root, {"kind": "agent_step",
                                      "payload": {"name": "own.register_statement",
                                                  "args": {}}}, sid="s1")
    assert not problem, problem


def _judge_only(tmp_path: pathlib.Path) -> Store:
    """造出误报现场：只走 `judge_statement_same`（只写 statement_same 那一本）。"""
    st = _ws(tmp_path)
    sec = SEC.for_role_wired("B", root=st.root, store=st, seam=_Seam())
    got = sec.judge_statement_same(statement_full=FULL, candidates=CANDIDATES,
                                   label="夹具", kind="theorem")
    assert got.get("checked") is True, got
    _session_step(st.root)
    return st


def _codes(rep: CL.ClosingReport) -> list[str]:
    return [str(f.to_dict().get("code") or "") for f in rep.findings]


# ============================================================ a：只有第二本账 ⇒ 不报

def test_a_statement_same_only_round_does_not_look_like_zero(tmp_path: pathlib.Path) -> None:
    """a：B 主路那一趟（`use_cache=False`）判过一场 ⇒ 不许报「一次都没判」。"""
    st = _judge_only(tmp_path)
    pj = CL.proposition_judgment_reading(st, sid="s1")
    assert pj.get("checked") is True, pj
    assert pj.get("verdict_rows") == 0, pj            # 第一本账确实是空的
    assert pj.get("statement_same_judged") >= 1, pj   # 第二本账里判过
    assert pj.get("judged_zero") is False, pj
    rep = CL.check_closing(st, checks=(), sid="s1")
    assert CODE not in _codes(rep), [f.to_dict() for f in rep.findings]
    reason = str(pj.get("reason") or "")
    assert "两本账合读" in reason, reason
    assert "statement_same" in reason, reason


# ============================================================ b：逐本读数

def test_b_each_ledger_has_its_own_reading(tmp_path: pathlib.Path) -> None:
    """b：`judged_by_ledger` 逐本给行数，`judged_rows` 是合计。"""
    st = _judge_only(tmp_path)
    pj = CL.proposition_judgment_reading(st, sid="s1")
    by = dict(pj.get("judged_by_ledger") or {})
    assert by.get("proposition_verdicts") == 0, pj
    assert by.get("statement_same") >= 1, pj
    assert pj.get("judged_rows") == sum(int(v) for v in by.values()), pj
    assert pj.get("judged_rows") >= 1, pj
    # 两本账的路径都摆出来（读的人能自己去看那两本）
    assert str(pj.get("verdict_path") or "").endswith("proposition_verdicts.jsonl"), pj
    assert str(pj.get("statement_same_path") or "").endswith("statement_same.jsonl"), pj
    assert int(pj.get("statement_same_rows") or 0) >= 1, pj


# ============================================================ c：反真空（只读一本 ⇒ 复现误报）

def test_c_reading_only_one_ledger_reproduces_the_false_alarm(tmp_path: pathlib.Path) -> None:
    """c（反真空）：旧判据式仍然成立，而 `judged_zero` 必须 False。

    若把 `judged_zero` 退回 `registration_actions >= 1 and verdict_rows == 0`，
    这一条会红 —— 绿只能来自"两本账合读"。
    """
    st = _judge_only(tmp_path)
    pj = CL.proposition_judgment_reading(st, sid="s1")
    # 旧式（只看第一本）在这一份夹具上恰好为真 —— 这正是 sylow5 的误报形态。
    assert int(pj.get("registration_actions") or 0) >= 1, pj
    assert int(pj.get("verdict_rows") or 0) == 0, pj
    assert (int(pj.get("registration_actions") or 0) >= 1
            and int(pj.get("verdict_rows") or 0) == 0) is True, pj
    # 合读之后必须不再误报。
    assert pj.get("judged_zero") is False, pj


# ============================================================ d：反真空之二（非 judge 行不算）

def test_d_keyword_and_retrieval_rows_do_not_count_as_judged(tmp_path: pathlib.Path) -> None:
    """d：`stage=keywords` / `retrieval` 的行是"还没判"的尝试，不许数成"判过"。"""
    st = _ws(tmp_path)
    SEC.append_statement_same(st.root, stage="keywords", statement_full=FULL,
                              checked=True, seam_source="body（夹具）",
                              why="夹具：只挑了词，没有判")
    SEC.append_statement_same(st.root, stage="retrieval", statement_full=FULL,
                              checked=True, seam_source="body（夹具）",
                              why="夹具：只检索，没有判")
    _session_step(st.root)
    pj = CL.proposition_judgment_reading(st, sid="s1")
    assert pj.get("statement_same_rows") == 2, pj
    assert pj.get("statement_same_judged") == 0, pj
    # 两本账都没有一次真判 ⇒ 误报必须成立（证明 a 的绿不是"什么都不报"）。
    assert pj.get("judged_zero") is True, pj
    rep = CL.check_closing(st, checks=(), sid="s1")
    assert CODE in _codes(rep), [f.to_dict() for f in rep.findings]
