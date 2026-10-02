# -*- coding: utf-8 -*-
"""R13 的第一跳（离线夹具）：B 消化一条定理 → 台账落库 → 下游读得到。

## 为什么单挑这一跳

`draft/37` §16 P2 把"B 把命题的完整假设与证明逐字摘出来、页码写进台账"
写成了提示词口径 —— 而口径要能落地，前提是 B 在自己的工具面上真的写得进去、
下游（D / H）真的读得出来。这正是本项目反复踩的那类坑：
"写好的提示词产出的东西无处可放"（§16 的 ② 数据面存在的理由）。

所以这一组不接模型，直接把"模型会调的那两个工具"按角色调一遍：

| 判据 | 它挡的形态 |
|---|---|
| B 的 `table.create` 能落一行完整命题 | 提示词要求的东西在工具面上做不到 |
| 缺 `statement_full`（完整假设）的行通过工具面被拒 | 数据层的闸门只在单测里有效、真跑时绕过 |
| 拼错的 `status` 在参数期被拒（词表已登记） | 写进去一个谁都不认识的取值而没人响 |
| 只读角色（C / H）的面上没有写工具 | 只读角色靠"没写"拿到刀 |
| 下游角色读得回来（`table.get` / `table.list`） | "每一跳都有下游可见的产物"（R13 判据①） |
| 交给 D 的消息里带 `stmt_id`（R13 判据③） | 下游知道"有定理了"却不知道去查哪一行 |
"""
from __future__ import annotations

import pathlib

from conftest import TS, sync_counters
from agentflow import agent_loop as AL
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_registry

_ROW: dict = {
    "origin": "external_lit", "kind": "theorem", "label": "Theorem 1.5",
    "statement_text": "随机游走的距离有 CLT 型极限",
    "statement_full": "设 G 是有限连通图，各边电导有正下界；则 (d(X_0,X_n)-E d)/sqrt(n) 收敛到正态",
    "proof_text": "Proof. By Theorem 6.5 of the companion book ...",
    "source_lit_id": "0000", "page_range": {"start": 7, "end": 8, "label": "pp. 7-8"},
    "quote_verified": True, "quote_reason": "逐字比对通过（page 7）",
    "evidence_kind": "cross_check", "status": "active", "created_at": TS,
}


def _world(tmp_path: pathlib.Path):
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", S.Literature(lit_id="0000", title="Brown 1971", type="J",
                                             summary="室图", path=None, added_at=TS).to_dict())
    sync_counters(st)
    return st, build_registry(store=st, workspace_root=st.root).registry


def _create(reg, *, role: str, row: dict):
    return reg.call("table.create", role=role, table="statements", row=row)


def test_b_can_register_a_complete_statement_through_its_own_tool_face(tmp_path):
    """正控：B 用自己的工具面把一条完整命题写进台账（这是提示词口径的落地前提）。"""
    st, reg = _world(tmp_path)
    res = _create(reg, role="B", row=dict(_ROW))
    assert res.ok, (res.error, res.meta)
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    got = rows[0]
    assert got["statement_full"] == _ROW["statement_full"], "含完整假设那一栏必须逐字落库"
    assert got["proof_text"] == _ROW["proof_text"] and got["quote_verified"] is True
    assert got["source_lit_id"] == "0000" and got["page_range"]["start"] == 7


def test_the_guard_fires_through_the_tool_path_not_only_in_a_unit_test(tmp_path):
    """负控：缺完整假设的行通过工具面被拒（数据层的闸门在真跑路径上同样有效）。"""
    st, reg = _world(tmp_path)
    bad = dict(_ROW)
    bad["statement_full"] = ""
    res = _create(reg, role="B", row=bad)
    assert not res.ok, res
    assert "statement_full" in str(res.error or ""), res.error
    assert st.rows("statements") == [], "被拒之后**一个字节都不许落库**"


def test_a_bogus_status_is_rejected_at_the_parameter_layer(tmp_path):
    """负控：拼错的 `status` 在参数期被拒 —— 词表登记过才谈得上这件事。"""
    st, reg = _world(tmp_path)
    bad = dict(_ROW)
    bad["status"] = "activo"
    res = _create(reg, role="B", row=bad)
    assert not res.ok, res
    err = str(res.error or "")
    assert "status" in err and ("active" in err or "enum" in err.lower()), err
    assert st.rows("statements") == []


def test_read_only_roles_do_not_have_the_write_tool(tmp_path):
    """只读角色（C / H）的面上没有 `table.create` —— 只读不是靠自觉。"""
    st, reg = _world(tmp_path)
    for role in ("C", "H"):
        names = {s.name for s in reg.for_role(role)}
        assert "table.create" not in names, (role, sorted(names))
        assert not _create(reg, role=role, row=dict(_ROW)).ok, role
    for role in ("B", "D", "G"):
        assert "table.create" in {s.name for s in reg.for_role(role)}, role


def test_the_downstream_role_can_read_the_statement_back(tmp_path):
    """R13 判据①：每一跳都有下游可见的产物 —— D 拿得到这一行（按号与按表两条路）。"""
    st, reg = _world(tmp_path)
    assert _create(reg, role="B", row=dict(_ROW)).ok
    sid = st.rows("statements")[0]["stmt_id"]
    one = reg.call("table.get", role="D", table="statements", id=sid)
    assert one.ok and one.meta.get("found") is True, (one.data, one.meta)
    assert one.data["statement_full"] == _ROW["statement_full"], one.data
    listed = reg.call("table.list", role="D", table="statements")
    assert listed.ok and listed.data["total"] == 1, listed.data
    # 反真空：不存在的号是「没找到」（`found=False`、`data=None`），不是「有这一行」
    miss = reg.call("table.get", role="D", table="statements", id="9999")
    assert miss.ok and miss.meta.get("found") is False and miss.data is None, (miss.data, miss.meta)


def test_the_handoff_message_carries_the_stmt_id_and_the_page(tmp_path):
    """R13 判据③：交给 D 的消息必须带 `stmt_id` 与页码 —— 否则下游知道"有定理了"却查不到行。"""
    st, reg = _world(tmp_path)
    assert _create(reg, role="B", row=dict(_ROW)).ok
    sid = st.rows("statements")[0]["stmt_id"]
    body = f"定理已入库：stmt_id={sid}，出处 lit:0000，页码 pp. 7-8；完整假设与逐字证明见该行。"
    path, problem = AL.send_message(st.root, sender="B", to="D",
                                    subject="定理已消化", body=body, sid="t")
    assert problem == "", (path, problem)
    heard, ids, _sent = AL.inbox_digest(st.root, "D", sid="t")
    assert ids, heard
    assert sid in heard and "pp. 7-8" in heard, heard
    assert "stmt_id" in heard, heard
