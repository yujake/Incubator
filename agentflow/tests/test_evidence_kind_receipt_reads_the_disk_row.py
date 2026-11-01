# -*- coding: utf-8 -*-
"""判据：`register_statement` 的 duplicate 回执要回读盘上的 `evidence_kind`。

## 现场（真机 82，2026-11-01 · A-4）

B 在 20:54:53 / 20:55:22 两次把同一份内容再交一次、请求 `evidence_kind="proof_review"`，
回执两次都说 `evidence_kind="proof_review"`（`new_row=false`）；而盘上 000006 一直是
`heuristic`（没有 V 的连续签，升档没有发生）。B 据此以为档位已经升上去了，
下一步去 `table.update` 改 `quote_reason`，撞墙。

机制：`register_statement` 的 duplicate 分支把入参 `evidence_kind` 原样回显，
没有回读 `data/statements.json` 那一行。

## 这一份钉的三条（改前红）

| 条 | 它要证明的事 | 改前为什么红 |
|---|---|---|
| a | 请求 proof_review、盘上 heuristic ⇒ 回执 `evidence_kind="heuristic"` | 改前回执是请求值 `proof_review` |
| b | 请求值另起一格 `requested_evidence_kind`（模型看得到自己要求过什么） | 改前没有这一格 |
| c | 盘上读不到那一行 ⇒ `unknown`（不是拿请求值顶） | 改前没有任何一档读盘 |

边界：全部 tmp 工作区、零真实模型调用（秘书不带缝 ⇒ 同一性判定走 unknown/机械档，
与 A-4 现场同形）；不读写 `projects/`。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import schema as S
from agentflow.agent_b import AgentB
from agentflow.store import Store

FULL = "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在。"
PROOF = ("证明：对 |G| 作归纳。取阶最大的 p-幂子群 P，用共轭作用数轨道，"
         "得 P 的共轭类大小与 p 互素，故 Sylow p-子群存在。")


def _agent(tmp_path: pathlib.Path) -> tuple[AgentB, Store]:
    st = Store(tmp_path / "ws")
    st.init()
    return AgentB(st, extractor=None, extract_text=None, config={}), st


def _body() -> dict:
    """自产命题的必填件（首登按猜想；`quote_verified` 不传 ⇒ 说清为什么没查）。"""
    return {"statement_full": FULL, "statement_text": FULL[:24],
            "origin": "own_result", "kind": "conjecture",
            "doc_id": S.format_id(0),
            "quote_reason": "我方自产命题，没有外部引文要比对"}


def _register(b: AgentB, *, evidence_kind: str) -> dict:
    return b.register_statement(**_body(), proof_text=PROOF, evidence_kind=evidence_kind)


# ============================================ a + b：回读盘上真值，请求值另起一格


def test_the_duplicate_receipt_reads_the_tier_off_the_disk_row(tmp_path):
    """a+b：请求 proof_review、盘上 heuristic ⇒ 回执 evidence_kind 必须是 heuristic。

    改前红：duplicate 分支 `out = {..., "evidence_kind": evidence_kind, ...}` 直接回显
    入参 ⇒ 回执说 proof_review，而 `data/statements.json` 里那一行写的是 heuristic。
    """
    b, st = _agent(tmp_path)
    first = _register(b, evidence_kind="heuristic")
    assert first.get("ok") is True, first
    sid = str(first.get("stmt_id") or "")
    row = next(r for r in st.rows("statements") if str(r.get("stmt_id") or "") == sid)
    assert row.get("evidence_kind") == "heuristic", row

    second = _register(b, evidence_kind="proof_review")
    # 这一笔确实没有升档（没有 V 的连续签）：它落在 duplicate 那一档。
    assert second.get("new_row") is not True, second
    if not second.get("ok"):
        assert str(second.get("kind") or "") == "duplicate_statement", second
    assert second.get("evidence_kind") == "heuristic", (
        f"回执把请求的档位当成了盘上的档位：{second}")
    assert second.get("requested_evidence_kind") == "proof_review", second
    # 盘上没有被动过（升档没有发生，回执也不许暗示它发生了）。
    row2 = next(r for r in st.rows("statements") if str(r.get("stmt_id") or "") == sid)
    assert row2.get("evidence_kind") == "heuristic", row2


# ============================================ c：读不到 ⇒ unknown


def test_an_unreadable_row_reads_unknown_not_the_requested_tier(tmp_path):
    """c：盘上读不到那一行 ⇒ `unknown`（绝不拿请求值顶）。

    改前红：根本没有回读这一格；这里同时钉住"读不到"不许折成"就是你要的那个值"。
    """
    b, _st = _agent(tmp_path)

    class _BrokenStore:
        """读 `statements` 就抛的替身：模拟 `data/statements.json` 读不出来。"""

        def rows(self, table):
            raise OSError(f"{table} 读不出来（打桩）")

    b.store = _BrokenStore()  # type: ignore[assignment]
    assert b._evidence_kind_on_disk("000000") == "unknown"
    # 行不存在也是 unknown（不是空串、不是请求值）。
    b.store = _st  # type: ignore[assignment]
    assert b._evidence_kind_on_disk("000999") == "unknown"
