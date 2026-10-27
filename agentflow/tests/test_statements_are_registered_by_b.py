# -*- coding: utf-8 -*-
"""D8：`statements` 只允许 B 的登记写（F 与非 B 角色的直写一律受控拒绝）。

## 真机形态（`projects/mp3-r3`，2026-10-26）

`statements` 的 `000000` / `000001` 两行由 `agent_f/core._proof_outlet` 直接 upsert：
`created_by=agent-F`、`bits={}`、`dependencies` 0 行、`out/secretary/nontriviality.jsonl`
不存在、label 还是「F 攻坚 000000 子目标 s1」。那一笔的 `note` 是
`f.step:proof:<sid>`（不是 `tool:` 记号），于是 `Store.tx` 提交块的那道闸整段跳过。

## 四条判据

| 判据 | 它要的红 |
|---|---|
| a | F 对 `statements` 的直写（`table.create` / `table.update`）⇒ 拒 + 码正确 + 盘上 0 行 |
| b | 非 B 角色（A/C/D/E/G/H/M/V）同样被拒；正控：B 的 `register_statement` 照常成功 |
| c | 新登记的命题行 `bits` 非空，且 `out/secretary/nontriviality.jsonl` 有一行 |
| d | 反真空：把"只许 B 登记"判据打桩成恒放行 ⇒ a/b 的码断言必红 |

判据 d 用的是同一个钩子（`tools.table_tools._statements_are_registered_by_b`），
所以它证明的是 a/b 的绿确实由那一道判据带来，不是"这些角色本来就写不进"。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import secretary as SEC
from agentflow.agent_b import AgentB
from agentflow.agent_f import AgentF
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import table_tools as TT

#: 一次 F 会交上来的命题（`own_result` 的出处用 `line_range` 的 label，不编页码）。
ROW: dict[str, Any] = {
    "origin": "own_result",
    "kind": "conjecture",
    "label": "椭圆无等弦点",
    "statement_text": "椭圆不存在等弦点",
    "statement_full": "设 a≠b 为半轴，椭圆 x²/a²+y²/b²=1 不存在等弦点（弦长函数非常值）。",
    "proof_text": "1. 设弦长函数为 L；2. 若 L 恒为常数则与半轴不等矛盾。",
    "quote_verified": None,
    "quote_reason": "自产证明，没有第二份文本可比对",
    "evidence_kind": "heuristic",
    "line_range": {"label": "reports/attack-000000.md"},
}


def _world(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _ctx(st: Store) -> TT.TableContext:
    return TT.TableContext(store=st)


def _as(role: str, fn):
    """在"这一趟是 role 发起的"挂点里跑一次（生产里由 `AgentLoop._do_tool` 挂）。"""
    with calling_as("t-000001", role):
        return fn()


def _create(st: Store, role: str):
    """直接调 handler（绕过工具面的角色过滤）：这一条要测的是写口自己的判据。"""
    return _as(role, lambda: TT.table_create(_ctx(st), table="statements", row=dict(ROW)))


def _update(st: Store, role: str, sid: str = "000000"):
    return _as(role, lambda: TT.table_update(
        _ctx(st), table="statements", id=sid, patch={"label": "改个名字"}))


def _kind(res) -> str:
    return str((res.meta or {}).get("kind") or "")


# ==================================================== a：F 的直写被拒
def test_f_direct_write_is_refused_with_the_code_and_lands_nothing(tmp_path):
    """a：F 直写 `statements` ⇒ 拒 + `statements_are_registered_by_b` + 盘上 0 行。

    改前红：同一笔会走兜底路由到秘书，秘书按角色拒（`routed_to_backstop.secretary_refused`），
    码不对；若载荷带 `bits`，则落 `direct_write_refused`，同样不是这一档。
    """
    st = _world(tmp_path)
    for res in (_create(st, "F"), _update(st, "F")):
        assert res.ok is False, (res.data, res.meta)
        assert _kind(res) == TT.STATEMENTS_REGISTERED_BY_B, (res.meta, res.error)
        assert TT.STATEMENTS_BY_B_REFUSAL in str(res.error or ""), res.error
        assert "五元位" in str(res.error or "") and "非平凡度" in str(res.error or ""), res.error
    assert st.rows("statements") == [], "拒了就不许落行"


# ==================================================== b：非 B 角色同样被拒 + B 正控
def test_every_non_b_role_is_refused_and_b_still_registers(tmp_path):
    """b：A/C/D/E/G/H/M/V 的直写都被拒；正控：B 的 `register_statement` 照常成功。"""
    st = _world(tmp_path)
    for role in ("A", "C", "D", "E", "G", "H", "M", "V"):
        res = _create(st, role)
        assert res.ok is False, (role, res.data, res.meta)
        assert _kind(res) == TT.STATEMENTS_REGISTERED_BY_B, (role, res.meta)
    assert st.rows("statements") == [], "被拒的角色一个字节都不许落"

    # 正控：B 的登记那一笔照常成功（五元位、定理名、行都由它落）
    b = AgentB(st, extractor=None, extract_text=None)
    got = b.register_statement(
        statement_full=ROW["statement_full"], statement_text=ROW["statement_text"],
        proof_text=ROW["proof_text"], kind="conjecture", label=ROW["label"],
        origin="own_result", evidence_kind="heuristic", quote_verified=None,
        quote_reason=ROW["quote_reason"], line_range=dict(ROW["line_range"]))
    assert got.get("ok") is True, got
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    assert rows[0]["created_by"] == "secretary-B", rows[0]["created_by"]
    assert dict(rows[0].get("bits") or {}), rows[0]


# ==================================================== c：五元位与非平凡度账本
def test_the_registered_row_has_bits_and_a_nontriviality_line(tmp_path, monkeypatch):
    """c：新登记的命题行 `bits` 非空，且 `out/secretary/nontriviality.jsonl` 有一行。

    改前红：F 直写那两行 `bits={}`、账本文件根本不存在。

    非平凡度这一步在 B 的循环里是 `AgentLoop._statement_filing_tier` 调
    `Secretary.judge_statement`；这里把 `judge` 打成"判过"（零模型），让同一段落账代码跑起来。
    """
    st = _world(tmp_path)

    def _judge(self, kind, context, task_id=""):
        return {"checked": True, "decision": "合格", "nontriviality": 2,
                "nontriviality_basis": "夹具判词", "reason": "夹具判词",
                "cost": {"ledger": "", "reason": "夹具"}}

    monkeypatch.setattr(SEC.Secretary, "judge", _judge, raising=True)
    f = AgentF(st, config={"workspace_root": st.root})
    sg = {"sid": "s1", "text": "判定这条", "testable": "存在反例或有限界"}
    product = {"product": "proof", "strategy": "反证",
               "steps": [{"n": 1, "text": "反设存在反例，取最小者", "assumption": True}]}
    out = f._proof_outlet(product, sg, plan={"plan_id": "000000"})
    assert out["ok"] is True, out
    row = next(r for r in st.rows("statements")
               if str(r.get("stmt_id") or "") == str(out["statement_id"]))
    assert dict(row.get("bits") or {}), row
    assert row["created_by"] == "secretary-B", row["created_by"]
    path = pathlib.Path(st.root) / "out" / "secretary" / "nontriviality.jsonl"
    assert path.is_file(), f"盘上没有 {path}"
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert lines, path.read_text(encoding="utf-8")
    # 台账按命题正文的 sha 折叠：读侧能用同一份正文把这一行找回来才算数。
    reading = SEC.nontriviality_of(st.root, str(row["statement_full"]))
    assert reading.get("tri") == "computed", reading
    assert reading.get("level") is not None, reading


# ==================================================== 角色读不出来那一档（fail-open 的边界）
def test_no_caller_role_is_not_a_way_in(tmp_path):
    """没有角色挂点（脚本 / 单测直调）时判据放行，但秘书那一道仍然拒，盘上 0 行。

    这一条是把"放行"与"能写"分开：`_statements_are_registered_by_b("")` 返回真，
    不是因为"空角色等于 B"，而是"没有挂点"与"检查过、不是 B"是两件事（三态纪律）。
    兜底仍在：干净载荷会被秘书按 `not_statement_writer` 拒，带 `bits` 会被
    `_NOT_ROUTABLE_KEYS` 拒 —— 两条都不落行。
    """
    st = _world(tmp_path)
    ctx = _ctx(st)
    clean = TT.table_create(ctx, table="statements", row=dict(ROW))
    assert clean.ok is False, (clean.data, clean.meta)
    assert _kind(clean) == "routed_to_backstop.secretary_refused", (clean.meta, clean.error)
    hand = TT.table_create(ctx, table="statements", row=dict(ROW, bits={}))
    assert hand.ok is False, (hand.data, hand.meta)
    assert _kind(hand) == "direct_write_refused", (hand.meta, hand.error)
    assert st.rows("statements") == [], "没有角色挂点不等于可以写"


# ==================================================== d：反真空
def test_stubbing_the_criterion_reopens_the_wild_road(tmp_path, monkeypatch):
    """d：把"只许 B 登记"判据打成恒放行 ⇒ a/b 的码断言必红（不落行不是靠角色面）。

    这一条与 a/b 用的是同一个钩子：打桩之后 F 的请求会继续路由到秘书，
    秘书按自己的角色判据拒 ⇒ 码变成 `routed_to_backstop.secretary_refused`。
    """
    st = _world(tmp_path)
    monkeypatch.setattr(TT, "_statements_are_registered_by_b", lambda role: True, raising=True)
    for role in ("F", "A", "D"):
        res = _create(st, role)
        assert res.ok is False, (role, res.data, res.meta)
        assert _kind(res) != TT.STATEMENTS_REGISTERED_BY_B, (
            role, "判据被打桩成恒放行之后仍然报同一个码 ⇒ a/b 的绿是恒真的")
    assert st.rows("statements") == [], "这一条不核落行，只核码确实由那道判据给"
