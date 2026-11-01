# -*- coding: utf-8 -*-
"""`table.update` 的「没有这条主键」拒信：一句原因 + 一句真的走得通的建议。

业主 2026-11-02 的口径（逐字）：

> 「同理，其它拒都最好要回复一句原因，一句建议」
> 「建议侧务必保证真实可达，不是误导」

这一条拒信是模型真看得到的那一条（真机 82/83 的 `table.update(table="statements")`
写错号时由 `tools/table_tools.py` 的兜底路由先拒，不是秘书内部那句）。所以判据做两件事：

① 断言拒信含 `建议：`，且在 400 字以内；它点名的三个符号都在真实面上存在
   （`table.list` 工具 / `stmt_id` 主键 / `own.register_statement` 动作）；
② 照那句建议「真的走一步」：先用 `table.list` 读出在册的 `stmt_id`，再拿那个号
   重交同一笔 `table.update` ⇒ 到达下一步（成功落盘）。

零模型调用；夹具用真写口（`store.tx` 落一条命题行，与
`test_statements_unsigned_and_resubmit.py` 同一套形状）。
"""
from __future__ import annotations

import pathlib

from agentflow import capabilities as C
from agentflow import schema as S
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import table_tools
from agentflow.tools.base import ToolRegistry

TS = "2026-11-02T10:00:00+08:00"
FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store, sid: str = "000001") -> dict:
    row = {"stmt_id": sid, "origin": "own_result", "kind": "theorem",
           "label": f"探针命题 {sid}", "statement_full": FULL,
           "statement_text": FULL, "proof_text": PROOF,
           "evidence_kind": "heuristic", "status": "active",
           "quote_verified": None, "quote_reason": "夹具：自产命题",
           "created_at": TS, "created_by": "test", "bits": {}}
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _reg(st: Store) -> ToolRegistry:
    reg = ToolRegistry(name="tables")
    reg.bound_role = "B"
    table_tools.register(reg, store=st)
    return reg


def _refusal(st: Store, *, sid: str):
    reg = _reg(st)
    with calling_as("t-b1", "B"):
        return reg.call("table.update", table="statements", id=sid,
                        patch={"kind": "lemma"})


# ---------------------------------------------------------------- ① 拒信本身
def test_the_missing_statement_id_refusal_carries_a_reachable_next_step(tmp_path):
    """① 拒信：原因一句 + `建议：` 一句；点名的符号都在真实面上。"""
    st = _ws(tmp_path)
    _put(st)
    res = _refusal(st, sid="999999")
    assert res.ok is False, (res.data, res.meta)
    assert res.meta.get("kind") == "not_found", res.meta
    text = str(res.error or "")
    assert "statements 里没有主键 999999" in text, text
    assert "建议：" in text, f"拒信没有「建议：」：{text}"
    advice = text.split("建议：", 1)[1].strip()
    assert advice, f"「建议：」后面是空的：{text}"
    assert len(text) < 400, (len(text), text)

    # 点名的三个符号必须在真实面上存在（不是编一个模型点不到的名字）。
    assert "table.list" in advice and "`stmt_id`" in advice, advice
    assert "`own.register_statement`" in advice, advice
    assert "table.list" in _reg(st).names(), "建议里点名的工具不在这张工具面上"
    id_field = S.TABLES["statements"]["id_field"]
    assert id_field == "stmt_id", id_field
    spec = C.find_action("B", "register_statement")
    assert spec is not None and str(getattr(spec, "action", "")) == "register_statement", (
        "建议里点名的动作在 B 的声明面上不存在")
    assert f"own.{spec.action}" == "own.register_statement"


# ---------------------------------------------------------------- ② 照那句走一步
def test_following_the_advice_reaches_the_next_step(tmp_path):
    """② 可达性：照 `建议：` 那句做（`table.list` 读号 → 拿号重交）⇒ 真的到了下一步。"""
    st = _ws(tmp_path)
    row = _put(st, "000001")
    res = _refusal(st, sid="999999")
    advice = str(res.error or "").split("建议：", 1)[1]
    assert "table.list" in advice, advice

    reg = _reg(st)
    with calling_as("t-b1", "B"):
        listed = reg.call("table.list", table="statements")
    assert listed.ok is True, listed.to_dict()
    ids = [str(r.get("stmt_id") or "") for r in (listed.data or {}).get("rows") or []]
    assert ids == [row["stmt_id"]], (ids, listed.data)

    with calling_as("t-b1", "B"):
        again = reg.call("table.update", table="statements", id=ids[0],
                         patch={"kind": "lemma"})
    assert again.ok is True, (again.error, again.data, again.meta)
    got = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == row["stmt_id"])
    assert str(got.get("kind") or "") == "lemma", got


# ---------------------------------------------------------------- ③ 反真空
def test_the_advice_is_not_emitted_when_the_row_exists(tmp_path):
    """③ 反真空：行在册时这一笔照常成功、不出现这句拒信（判据不是恒红）。"""
    st = _ws(tmp_path)
    _put(st, "000001")
    res = _refusal(st, sid="000001")
    assert res.ok is True, (res.error, res.meta)
    assert "建议：" not in str(res.error or ""), res.error
