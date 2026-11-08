# -*- coding: utf-8 -*-
"""判据（p263 第 4 步）：每个角色的「查」都接在 `statementledger` 那组查口上。

## 这一份钉什么

不是「角色会查」这句声明，而是行为：每条用例只走角色自己的入口，
然后用两种方式证明它真的经过了查口 ——

1. 只给一种输入：按编号的角色只给编号（不给正文、不给标签），
   按关键字的角色只给关键词（不给编号）。查成了，说明这条口子在用。
2. 反真空：把该角色用到的那条查口降级（`by_id` 永远查不到 /
   `by_keywords` 永远 0 命中 / `rows_of` 读不成）⇒ 该角色原有的判据必须变红 ——
   否则它没走查口（自己扫全表、或自己留了一份实现）。

## 为什么不用「扫源码找 `rows("statements")`」当主判据

业主口径：「能行为验证就行为验证」。源码扫描只能证明"这一句不在"，
证明不了"这条角色真的问查口要过答案"；上面第 2 条能。角色侧的
`rows("statements")` 计数作为读数贴在交付报告里（工具
`temp/_p263_role_query_sites.py`），不进常驻判据。

## 每个角色用到哪种口径

| 角色 | 口径 | 为什么 |
|---|---|---|
| C | 按编号 | `proof_chain` 的目标解析：「号优先、别名兜底」，号那一支走 `by_id` |
| L | 按编号 | `_pick_statement` 只认「显式编号」与「正文逐字全等」；前者走 `by_id` |
| V（三个库模块） | 按编号 / 全表→索引 | 签档、回填、重送都按号读；没有关键词检索面 |
| B | 编号 + 关键字 | 收录前：逐字全等（`duplicate_hits`）+ 秘书的检索判定链（`by_keywords`） |
| D | 关键字 | 「已知成果」按内容词找（`by_keywords`，池由调用方给） |
| F | 编号 + 掩码 | 按号读在册那一行；可引清单只列等级够的（掩码由调用方给） |
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import seed_statement_row  # noqa: E402
from agentflow import statementledger as SL  # noqa: E402
from agentflow.store import Store  # noqa: E402


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _degraded_id(*_a, **_k):
    """把口径一降级成「永远查不到（但算查过）」。"""
    return {"checked": True, "mode": SL.MODE_ID, "stmt_id": "", "found": False,
            "hits_total": 0, "row": {}, "scanned": 0, "source": "rows",
            "matched_by": SL.MATCHED_BY_ID, "why": "降级：永远查不到",
            "reason": "", "error": {}}


def _degraded_keywords(*_a, **_k):
    """把口径二降级成「永远 0 命中（但算查过）」。"""
    return {"checked": True, "mode": SL.MODE_KEYWORDS, "keywords": [], "hits": [],
            "hits_total": 0, "scanned": 0, "checked_rows": 0, "source": "rows",
            "matched_by": SL.MATCHED_BY_KEYWORDS, "why": "降级：永远 0 命中",
            "reason": "", "error": {}}


def _unreadable_rows_of(*_a, **_k):
    """把唯一取数口降级成「读不成」（不是 0 行）。"""
    return (None, "`statements` 台账读不出来（夹具：降级）⇒ 这一问没查成"
                  "（不是「台账里没有这一行」，也不是「0 行」）",
            {"type": "RuntimeError", "message": "夹具：降级"})


# ===================================================== ① C：按编号
def test_c_takes_the_chain_target_by_number_and_returns_its_content(
        tmp_path: pathlib.Path) -> None:
    """只给编号（`stmt:0001`，不给正文/标签）⇒ 解析到那一行、内容按号取到。"""
    from agentflow import agent_c

    st = _store(tmp_path)
    seeded = seed_statement_row(
        st, stmt_id="0001", label="A⇒B", statement_full="若 A 成立，则 B 成立。",
        kind="theorem", evidence_kind="proof", proof_text="Proof. 检查器核过。")
    rep = agent_c.AgentC(st).proof_chain("stmt:0001")
    assert rep.ok, rep.to_dict()
    # 「号」那一支走的是查口口径一（不是别名、不是关键词）：
    assert rep.payload["matched_by"] == "stmt_id", rep.payload
    assert rep.payload["node"]["stmt_id"] == "0001", rep.payload
    # 内容确实是按号从台账取回来的那一行（标签 + 种类都在）：
    assert rep.payload["node"]["label"] == seeded["label"], rep.payload
    assert rep.payload["node"]["kind"] == seeded["kind"], rep.payload


def test_c_a_degraded_id_mode_loses_the_chain_target(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：口径一降级 ⇒ 只给编号的链目标解析不到（它的判据红）。"""
    from agentflow import agent_c

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="A⇒B",
                       statement_full="若 A 成立，则 B 成立。",
                       kind="theorem", evidence_kind="proof",
                       proof_text="Proof. 检查器核过。")
    monkeypatch.setattr(SL, "by_id", _degraded_id)
    rep = agent_c.AgentC(st).proof_chain("stmt:0001")
    assert rep.ok is False, rep.to_dict()
    assert rep.error == "target_not_found", rep.to_dict()


def test_c_a_degraded_rows_of_is_not_an_empty_graph(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：唯一取数口降级 ⇒ 链读成「读不成」，不是「没有依赖」。"""
    from agentflow import agent_c

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="A⇒B",
                       statement_full="若 A 成立，则 B 成立。",
                       kind="theorem", evidence_kind="proof",
                       proof_text="Proof. 检查器核过。")
    monkeypatch.setattr(SL, "rows_of", _unreadable_rows_of)
    rep = agent_c.AgentC(st).proof_chain("0001")
    assert rep.ok is False, rep.to_dict()
    assert rep.payload["checked"] is False, rep.payload
    assert "读不成" in rep.summary, rep.summary


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
