# -*- coding: utf-8 -*-
"""R13 的第一跳（离线夹具）：B 消化一条定理 → 台账落库 → 下游读得到。

## 为什么单挑这一跳

`draft/37` §16 P2 把"B 把命题的完整假设与证明逐字摘出来、页码写进台账"
写成了提示词口径 —— 而口径要能落地，前提是 B 在自己的工具面上真的写得进去、
下游（D / H）真的读得出来。这正是本项目反复踩的那类坑：
"写好的提示词产出的东西无处可放"（§16 的 ② 数据面存在的理由）。

所以这一组不接模型，直接把"B 到底怎么写进 `statements`"按角色走一遍：

| 判据 | 它挡的形态 |
|---|---|
| B 交内容、秘书落盘，一行完整命题真的落库 | 提示词要求的东西在**正路**上做不到 |
| 缺 `statement_full`（完整假设）的行**在正路上**被拒 | 数据层的闸门只在单测里有效、真跑时绕过 |
| 拼错的 `status` / 词表外的取值在参数期被拒（词表已登记） | 写进去一个谁都不认识的取值而没人响 |
| `table.create("statements")` 这条野路被拒 | 模型的手绕过秘书（真机 `mp2-7.jsonl` 第 97 行） |
| 只读角色（C / H）的面上没有写工具 | 只读角色靠"没写"拿到刀 |
| 下游角色读得回来（`table.get` / `table.list`） | "每一跳都有下游可见的产物"（R13 判据①） |
| 交给 D 的消息里带 `stmt_id`（R13 判据③） | 下游知道"有定理了"却不知道去查哪一行 |

## 2026-10-19 晚改过一次口径（`projects/mp2` 的真机读数）

这一组原先把 `table.create(table="statements")` 当成"B 的正路" —— 那正是
`mp2-7.jsonl` 第 97 行的形态：B 拿到 `unknown_tool` 之后用手写表落了
`bits={}` + `evidence_kind="heuristic"` 的一行。现在那条约会被
`store.direct_write_refusal` 受控拒绝（`direct_write_refused`），
所以本文件的"正路"改成 **B 交内容、秘书落盘**（`Secretary.record_statement`），
并**新增**一条判据盯着野路被拒。断言没有放宽：每一格判的还是同一件事
（"提示词要求的东西真的做得成"），只是做得成的那条路换了。
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


def _create(reg, *, role: str, row: dict, table: str = "statements"):
    return reg.call("table.create", role=role, table=table, row=row)


def _register(st, row: dict) -> dict:
    """B 交内容、秘书落盘（**正路**；`table.create("statements")` 已被受控拒绝）。"""
    from agentflow.secretary import Secretary

    sec = Secretary("B", root=st.root, store=st)
    payload = dict(row)
    payload.setdefault("quote_reason", "夹具：引文回验的读数在 quote_verified 那一格")
    return sec.record_statement(payload, role="B")


def test_b_lands_a_complete_statement_by_handing_it_to_its_secretary(tmp_path):
    """正控：B 交内容 ⇒ 秘书落一行完整命题（这是提示词口径的落地前提）。

    落盘那一笔的留痕必须是秘书（`created_by="secretary-B"`）：B 自己一次写工具都不调
    —— 业主 2026-10-09 的口径，`Secretary.record_statement` 的 docstring 逐字写着。
    """
    st, reg = _world(tmp_path)
    out = _register(st, dict(_ROW))
    assert out["checked"] and out["created"], out
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    got = rows[0]
    assert got["statement_full"] == _ROW["statement_full"], "含完整假设那一栏必须逐字落库"
    assert got["proof_text"] == _ROW["proof_text"] and got["quote_verified"] is True
    assert got["source_lit_id"] == "0000" and got["page_range"]["start"] == 7
    assert got["created_by"] == "secretary-B", got["created_by"]
    assert got["stmt_id"] == out["stmt_id"] and got["stmt_id"].isdigit()


def test_the_wild_road_through_table_create_is_refused(tmp_path):
    """负控（`mp2-7.jsonl` 第 97 行那个形态）：B 用通用写口直写 `statements` ⇒ 被拒。

    判据落在**工具层**（模型的手）：`ok=False`、`kind=direct_write_refused`，
    而拒信里必须逐字写着该走哪条路（`Secretary.record_statement` / `own.register_statement`）
    —— 模型据此能改，而不是只知道"不行"。盘上一条都不许落。
    """
    st, reg = _world(tmp_path)
    res = _create(reg, role="B", row=dict(_ROW))
    assert res.ok is False, res
    assert res.meta.get("kind") == "direct_write_refused", res.meta
    assert "Secretary.record_statement" in res.error, res.error
    assert "own.register_statement" in res.error, res.error
    assert st.rows("statements") == [], "被拒之后**一个字节都不许落库**"


def test_the_guard_fires_through_the_front_door_not_only_in_a_unit_test(tmp_path):
    """负控：缺完整假设的命题**在正路上**被拒（数据层的闸门在真跑路径上同样有效）。"""
    st, reg = _world(tmp_path)
    bad = dict(_ROW)
    bad["statement_full"] = ""
    out = _register(st, bad)
    assert not out.get("created"), out
    assert "statement_full" in str(out.get("reason") or ""), out.get("reason")
    assert st.rows("statements") == [], "被拒之后**一个字节都不许落库**"


def test_a_bogus_status_is_rejected_at_the_parameter_layer(tmp_path):
    """负控：词表外的取值在参数期被拒 —— 词表登记过才谈得上这件事。

    样品换成 `literature.type`（`LIT_TYPES`）：`statements`/`dependencies` 已不由
    通用写口直写，而"参数期词表校验"这条判据要说的是**登记过就会校验**，
    与挂在哪张表上无关（`_VOCAB_BY_FIELD` 是那张登记表）。
    """
    st, reg = _world(tmp_path)
    res = _create(reg, role="B", table="literature",
                  row={"title": "T", "type": "Jx", "summary": "s", "path": None})
    assert not res.ok, res
    err = str(res.error or "")
    assert "type" in err and ("J" in err or "enum" in err.lower()), err
    assert st.rows("literature").__len__() == 1, "只有夹具那一篇，坏行不许落"


def test_read_only_roles_do_not_have_the_write_tool(tmp_path):
    """只读角色（C / H）的面上没有 `table.create` —— 只读不是靠自觉。"""
    st, reg = _world(tmp_path)
    # 样品表取 `literature`：`statements` 那一条已经被"野路受控拒绝"挡在任何角色之前，
    # 用它来测"只读角色没有写工具"会变成一条恒真的断言（两件事必须分得开）。
    lit_row = {"title": "T", "type": "J", "summary": "s", "path": None}
    for role in ("C", "H"):
        names = {s.name for s in reg.for_role(role)}
        assert "table.create" not in names, (role, sorted(names))
        assert not _create(reg, role=role, table="literature", row=dict(lit_row)).ok, role
    for role in ("B", "D", "G"):
        assert "table.create" in {s.name for s in reg.for_role(role)}, role


def test_the_downstream_role_can_read_the_statement_back(tmp_path):
    """R13 判据①：每一跳都有下游可见的产物 —— D 拿得到这一行（按号与按表两条路）。"""
    st, reg = _world(tmp_path)
    out = _register(st, dict(_ROW))
    assert out["created"], out
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
    assert _register(st, dict(_ROW))["created"]
    sid = st.rows("statements")[0]["stmt_id"]
    body = f"定理已入库：stmt_id={sid}，出处 lit:0000，页码 pp. 7-8；完整假设与逐字证明见该行。"
    path, problem = AL.send_message(st.root, sender="B", to="D",
                                    subject="定理已消化", body=body, sid="t")
    assert problem == "", (path, problem)
    heard, ids, _sent = AL.inbox_digest(st.root, "D", sid="t")
    assert ids, heard
    assert sid in heard and "pp. 7-8" in heard, heard
    assert "stmt_id" in heard, heard
