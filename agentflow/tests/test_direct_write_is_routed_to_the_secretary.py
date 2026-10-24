# -*- coding: utf-8 -*-
"""判据：直写请求由系统兜底接管（业主 2026-10-24 裁定），不再"拒 + 提醒走秘书"。

业主原话（唯一权威，两段同一份口径）：
1. 「关于直写statements的问题，不应该是提醒智能体要走秘书，而是自动将直写请求路由到秘书接管」
2. 「还有哪些动作是被"需要经秘书"拦截的？都走自动路由。甚至包装得足够好后可以让智能体
   对秘书的存在无感，只是知道某些动作会有人帮他兜底。」

## 这一组钉的八件事（缺一条"接管"就会以某种方式变成"放行"或"还是拒"）

| # | 判什么 | 改前为什么红 |
|---|---|---|
| ① | 角色直写 `statements`（合法内容）⇒ 路由成功、行真的落盘、`backstop=secretary` | 改前直接 `direct_write_refused`，一行不落 |
| ② | 直写非法内容（缺必填 / 词表外取值）⇒ 兜底方拒、理由原样带回、行不落盘 | 改前连"兜底方的判据跑没跑"都看不出来（一律同一句拒信） |
| ③ | 野路（`bits` / 只改 `proof_text` / 迁移账本类表 / 依赖边的就地改）⇒ 仍拒 | 改前不成立（没有"可路由"这一说），但它必须在新口径下继续红 |
| ④ | 反真空：清空路由表 ⇒ ① 必红；把"就地改"那条路补进表 ⇒ ③ 必红 | 改前两条都无从谈起（路由表不存在） |
| ⑤ | 统计：同一份夹具，路由过后 `direct_write` 为 0、`routed_to_backstop` 有数 | 改前它会记成 `direct_write` |
| ⑥ | 每张表每类意图各一条路由；意图不明 ⇒ 拒 | 改前只有"一律拒" |
| ⑦ | 返回值里不含指路语（"请用 / 改走 / 应改用"…） | 改前拒信逐字指路（`own.register_statement`） |
| ⑧ | 统计的两种兜底方分开计（`routed_to_backstop.secretary` / `.literal`） | 改前没有这一档 |

## 两点口径（读断言之前先看一眼，否则会以为判据比实际更强）

- 发起方身份从 `conductor.calling_as(...)` 挂的 ContextVar 读：`AgentLoop._do_tool` 包住每一次
  工具调用（agent_loop.py:6169），所以生产路径上它总有值。单测里要用 `calling_as` 显式挂上，
  否则读出来是空串 —— 而空串不是"随便一个角色"，秘书那条路会按它自己的判据拒
  （`not_statement_writer`）。这一条是"路由不替兜底方放宽判据"的读数，不是漏测。
- 这里判的是"这次写请求去了哪条路、那条路自己的判据跑没跑"，不是"秘书写得对不对"
  （那一层由 `tests/test_statement_write_is_the_secretarys_only.py` 钉着）。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentflow import errorstats as ES
from agentflow import schema as S
from agentflow import store as store_mod
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import table_tools as TT
from agentflow.tools.base import ToolRegistry

from conftest import add_literature, add_request

TS = "2026-01-01T00:00:00+00:00"

#: 指路语（业主 2026-10-24 追加口径："理由里不出现'请改用某个工具'的指路语"）。
#: 只扫"人话"那几格（`error` / `what_happened` / `refused_by_backstop`），不扫 `routed_to`
#: 那种机器读数：`routed_to` 是"这次走的哪条路"的审计栏（业主第 1 条裁定要求的正是它），
#: 它不是在派活给模型。
HINT_WORDS: tuple[str, ...] = ("请用", "改走", "应改用", "请调", "请改用", "改用",
                               "你应该", "你要用")

#: 一份合法的命题载荷（形状照 `projects/r34c/sessions/r34c.jsonl` 里 B 真的交过的那一份）。
LEGAL: dict = {
    "origin": "external_lit",
    "kind": "theorem",
    "label": "R(3,4) = 9",
    "statement_full": ("设 R(k, m) 是二色 Ramsey 数：最小的 N0，使得任意 N > N0 个顶点的完全图"
                       "把每条边染成红或蓝之一，都必出现 k 点红团或 m 点蓝团。则 R(3, 4) = 9。"),
    "statement_text": "R(3,4) = 9",
    "proof_text": ("Theorem 2 may now be used to remove the doubt as to the values n(3,4) < 9. "
                   "Since n(2,5) = 5 one readily obtains that n(3,4) = 9."),
    "source_lit_id": "0000",
    "page_range": {"start": 3, "end": 3},
    "quote_verified": None,
    "quote_reason": "还没逐字回验（本判据只核'路由去没去、行落没落'）",
    "evidence_kind": "heuristic",
}


# ---------------------------------------------------------------- 夹具


def _ws(tmp_path: pathlib.Path) -> Store:
    """一个小工作区：一篇在册文献（命题的出处要能核到）。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_request(st, "r-0001", done=True, result_lit_ids=["0000"])
    add_literature(st, "0000", title="Combinatorial Relations and Chromatic Graphs",
                   path=None, processed=True, source_request_ids=["r-0001"],
                   dedup_key="doi:10.4153/CJM-1955-001-4", doi="10.4153/CJM-1955-001-4",
                   year=1955)
    return st


def _reg(st: Store) -> ToolRegistry:
    """通用写口那一张面（A–D 共用的三个写口 + 读口）。"""
    reg = ToolRegistry(name="dw")
    TT.register(reg, store=st)
    return reg


def _as(role: str, fn):
    """在"这一趟是 role 发起的"这个挂点里跑一次（生产里由 `AgentLoop._do_tool` 挂）。"""
    with calling_as("t-000001", role):
        return fn()


def _blob(res) -> str:
    """一次工具结果的全文（data + meta + error 都算"返回值"）。"""
    return json.dumps({"error": res.error, "data": res.data, "meta": res.meta},
                      ensure_ascii=False, default=str)


def _session_record(res) -> dict:
    """把一次工具结果写成 `agent_step` 记录（形状与 `agent_loop._do_tool` 落档那一份同形）。"""
    return {"kind": "agent_step", "role": "B", "index": 1, "shape": "tool",
            "payload": {"name": "table.create"},
            "result": {"tool": "table.create", "ok": bool(res.ok), "data": res.data,
                       "error": res.error or "", "meta": dict(res.meta or {})}}


def _stats_for(st: Store, *results) -> ES.ErrorStats:
    """同一份工作区 + 同一批工具结果 ⇒ 落成会话记录再读 `error_action_stats`。"""
    path = pathlib.Path(str(st.root)) / "sessions" / "s1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(_session_record(r), ensure_ascii=False,
                                         default=str) for r in results) + "\n",
                    encoding="utf-8")
    return ES.error_action_stats(st)


def _seed_statement(st: Store) -> str:
    """在工作区里铺一行命题（夹具用：走不带 `tool:` 记号的普通事务，与 `conftest` 的造法同形）。

    为什么不走工具层：这一格要造的是"盘上已经有一行"这个前提，
    而不是再验一次路由（那是 ① 的活）。于是 ③ 的绿/红与 ① 无关。
    """
    with st.tx("statements", "counters", actor="fixture", note="fixture") as tx:
        stmt_id = tx.alloc_id("stmt")
        row = S.Statement(stmt_id=stmt_id, origin="external_lit", kind="theorem",
                          label="夹具行", statement_full="盘上已经有的一行（夹具）",
                          proof_text="夹具证明", source_lit_id="0000",
                          page_range=S.PageRange(start=1, end=1),
                          quote_verified=None,
                          quote_reason="夹具：这一格不参与本轮判据",
                          evidence_kind="heuristic")
        row.validate()
        tx.upsert("statements", row.to_dict(), note="fixture")
    return str(stmt_id)


# ==================================================== ① 路由成功


def test_a_role_writing_statements_directly_is_taken_over_not_refused(tmp_path):
    """① 角色直写 `statements`（合法内容）⇒ 系统接管、行真的落盘、读数说"这次是路由的"。

    改前红：同一个调用得到 `ok=False` + `kind=direct_write_refused`，盘上 0 行。
    """
    st = _ws(tmp_path)
    reg = _reg(st)
    res = _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                    row=dict(LEGAL)))
    assert res.ok is True, (res.error, res.meta)
    body = dict(res.data or {})
    assert body.get("backstop") == "secretary", body
    assert body.get("routed_from") == "direct_write", body
    assert body.get("routed_to") == "Secretary.record_statement", body
    assert body.get("state") == "routed", body
    stmt_id = str(body.get("id") or "")
    assert stmt_id, body
    # 行真的落盘，且就是秘书那条路落的（写入者与事件流的 note 都由它给）
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    assert rows[0]["stmt_id"] == stmt_id
    assert rows[0]["created_by"] == "secretary-B", rows[0]["created_by"]
    notes = [str(e.get("note") or "") for e in st.read_events()
             if str(e.get("table")) == "statements"]
    assert notes and all(n.startswith("record_statement") for n in notes), notes
    # 读数里也看得出来"这次是路由的"（errorstats 读的就是 `result.error` 那一格）
    assert res.meta.get("kind") == "routed_to_backstop.secretary", res.meta
    assert "routed_to_backstop.secretary" in str(res.error or "")


def test_the_routed_write_reports_who_asked_and_where_it_landed(tmp_path):
    """①b 返回形状：改前"谁要写 / 落到哪一行"这两格都不存在（一律同一句拒信）。"""
    st = _ws(tmp_path)
    reg = _reg(st)
    res = _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                    row=dict(LEGAL, stmt_id=""))
              )
    body = dict(res.data or {})
    # 盘上那一行真的在（row 是落盘的那一份，不是"将要落的那一份"）
    row = dict(body.get("row") or {})
    assert row and row == next(r for r in st.rows("statements")
                               if r["stmt_id"] == row["stmt_id"])
    assert body.get("changes") == [] or isinstance(body.get("changes"), list)
    assert body.get("refused_by_backstop") == "", body
    assert body.get("what_happened"), body


# ==================================================== ② 负控：非法内容不许被"接管"洗白


@pytest.mark.parametrize("broken, needle", [
    ({"statement_full": ""}, "statement_full"),
    ({"origin": "编的出处档"}, "origin"),
    ({"quote_verified": "yes"}, "quote_verified"),
])
def test_illegal_content_is_refused_by_the_backstop_and_nothing_lands(tmp_path, broken, needle):
    """② 直写非法内容 ⇒ 兜底方按它自己的判据拒、理由原样带回、行不落盘。

    改前红：改前根本走不到兜底方（工具层先拒），"秘书的判据跑没跑"在读数上是空白。
    """
    st = _ws(tmp_path)
    reg = _reg(st)
    row = dict(LEGAL)
    row.update(broken)
    res = _as("B", lambda: reg.call("table.create", role="B", table="statements", row=row))
    assert res.ok is False, res
    assert res.meta.get("kind") == "routed_to_backstop.secretary_refused", res.meta
    refused = str(res.meta.get("refused_by_backstop") or "")
    assert refused, res.meta
    # 理由原样带回（兜底方自己的字），且确实说的是这一格的事
    assert needle in refused or needle in str(res.meta.get("detail") or {}), refused
    # 负控：路由不许变成后门 —— 一行都不许落
    assert st.rows("statements") == []


def test_the_backstop_reason_is_verbatim_not_translated(tmp_path):
    """②b 兜底方的理由逐字带回（改前：模型读到的是一句与内容无关的"该走哪条路"）。"""
    st = _ws(tmp_path)
    reg = _reg(st)
    res = _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                    row=dict(LEGAL, source_lit_id="999999")))
    assert res.ok is False, res
    refused = str(res.meta.get("refused_by_backstop") or "")
    assert refused.startswith("unknown_lit_id"), refused
    assert "literature" in refused and "999999" in refused, refused
    assert st.rows("statements") == []


def test_an_unknown_caller_role_is_refused_by_the_secretary_not_waved_through(tmp_path):
    """②c 发起方身份读不到 ⇒ 秘书按它自己的判据拒（路由不替它放宽）。

    这一条是"路由只换入口、不换判据"的读数：`not_statement_writer` 是秘书那条路
    原本就有的规矩，路由把它原样传过去，而不是替它认定"这是 B 在写"。
    """
    st = _ws(tmp_path)
    reg = _reg(st)
    res = reg.call("table.create", role="B", table="statements", row=dict(LEGAL))
    assert res.ok is False, res
    assert res.meta.get("kind") == "routed_to_backstop.secretary_refused", res.meta
    assert "not_statement_writer" in str(res.meta.get("refused_by_backstop") or "")
    assert st.rows("statements") == []


# ==================================================== ③ 野路仍然要拒


def test_the_wild_roads_are_still_refused(tmp_path):
    """③ 真正野路 ⇒ 仍拒（负控）：`bits` / 只改 `proof_text` / 迁移账本类表 / 依赖边就地改。"""
    st = _ws(tmp_path)
    reg = _reg(st)
    # (1) 手写五元位（`mp2-7.jsonl:97` 的真机形态）—— 接管它等于把"绕开推导"洗成"系统代劳"
    hand = dict(LEGAL, bits={})
    res = _as("B", lambda: reg.call("table.create", role="B", table="statements", row=hand))
    assert res.ok is False, res
    assert res.meta.get("kind") == "direct_write_refused", res.meta
    assert "#" not in str(res.error or "")
    # (2) 先铺一行，再试"只改 proof_text"（证明正文变了就是另一条命题）
    seeded = _seed_statement(st)
    upd = _as("B", lambda: reg.call("table.update", role="B", table="statements",
                                    id=seeded, patch={"proof_text": "换一份证明"}))
    assert upd.ok is False, upd
    assert upd.meta.get("kind") == "direct_write_refused", upd.meta
    # (3) 迁移 / 账本类表：不在路由表里，通用写口连"路由"这一步都不进
    for table in ("counters", "tasks", "usage_ledger", "eval_results"):
        res = _as("B", lambda t=table: reg.call("table.create", role="B", table=t, row={}))
        assert res.ok is False, (table, res)
        assert "routed_to_backstop" not in _blob(res), (table, _blob(res))
    # (4) 依赖边的"就地改"：没有这条正路
    res = _as("B", lambda: reg.call("table.update", role="B", table="dependencies",
                                    id="0000000", patch={"status": "closed"}))
    assert res.ok is False, res
    assert res.meta.get("kind") == "direct_write_refused", res.meta


def test_the_guard_itself_is_unchanged(tmp_path):
    """③b 判据那一层没被路由删掉：`store.direct_write_refusal` 对那三张表仍然非空。"""
    for table in ("statements", "dependencies", "lit_candidates"):
        assert store_mod.direct_write_refusal(table).startswith(
            store_mod.DIRECT_WRITE_REFUSED), table
    for table in ("literature", "relations", "tasks", "counters", ""):
        assert store_mod.direct_write_refusal(table) == "", table


def test_the_tx_commit_gate_still_refuses_a_bare_tool_transaction(tmp_path):
    """③c 结构性的那一半：不经工具层、直接开一笔 `tool:` 事务 ⇒ 提交时仍被拒。

    路由只换"模型的手"那一层的入口；绕过工具层的裸事务根本没有"请求"可路由，
    所以判据（`Store.tx` 的提交块）一个字节都没动 —— 这一条防的是"路由顺手把
    结构性的兜底也拆了"。
    """
    st = _ws(tmp_path)
    with pytest.raises(ValueError):
        with st.tx("statements", actor="tool", note="tool:table.create:statements") as tx:
            tx.upsert("statements", {"stmt_id": S.format_id(0), "origin": "own_result",
                                     "kind": "theorem", "statement_full": "手写的",
                                     "quote_reason": "尚未逐字校验"})
    assert st.rows("statements") == []


# ==================================================== ④ 反真空


def test_empty_the_route_table_and_the_routing_criterion_turns_red(tmp_path, monkeypatch):
    """④a 反真空：把"可路由表"集合清空 ⇒ ① 必红（绿是那张表带来的）。"""
    st = _ws(tmp_path)
    reg = _reg(st)
    monkeypatch.setattr(store_mod, "DIRECT_WRITE_ROUTES", ())
    res = _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                    row=dict(LEGAL)))
    assert res.ok is False, res                     # ← ① 在这里是红的
    assert res.meta.get("kind") == direct_write_kind(), res.meta
    assert st.rows("statements") == []


def direct_write_kind() -> str:
    return store_mod.DIRECT_WRITE_REFUSED


def test_extend_the_route_table_to_amend_and_the_wild_road_criterion_turns_red(tmp_path,
                                                                              monkeypatch):
    """④b 反真空：把"依赖边就地改"那条路补进表 ⇒ ③ 的第四条必红。

    它证明 ③ 的绿是"表里没有这条正路"带来的，而不是"依赖边本来就不能改"。
    """
    st = _ws(tmp_path)
    reg = _reg(st)
    extra = ("dependencies", "literal", "amend", "doc.register_dependency",
             "src/agentflow/tools/doc_tools.py:1876（register_dependency）")
    monkeypatch.setattr(store_mod, "DIRECT_WRITE_ROUTES",
                        tuple(store_mod.DIRECT_WRITE_ROUTES) + (extra,))
    assert store_mod.direct_write_route("dependencies", "amend") is not None
    res = _as("B", lambda: reg.call("table.update", role="B", table="dependencies",
                                    id="0000000", patch={"status": "closed"}))
    assert "routed_to_backstop" in _blob(res), _blob(res)   # ← ③ 在这里是红的
    assert res.meta.get("kind") != direct_write_kind(), res.meta


# ==================================================== ⑤ 统计口径


def test_the_stats_read_routed_writes_as_routed_and_not_as_direct_write(tmp_path):
    """⑤ 对拍同一夹具：路由过后 `direct_write` 为 0、`routed_to_backstop` 有数。

    改前红：同一笔在改前会以 `direct_write_refused` 落进 `direct_write`。
    """
    st = _ws(tmp_path)
    reg = _reg(st)
    routed = _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                       row=dict(LEGAL)))
    assert routed.ok is True, (routed.error, routed.meta)
    stats = _stats_for(st, routed)
    assert stats.checked is True, stats.reason
    assert stats.count("B", "direct_write") == 0, stats.by_role
    assert stats.category_total("routed_to_backstop") == 1, stats.by_role
    assert stats.sources["hits"]["codes"]["B"]["routed_to_backstop.secretary"] == 1, (
        stats.sources["hits"])


def test_the_same_fixture_reads_as_direct_write_once_the_route_table_is_empty(tmp_path,
                                                                            monkeypatch):
    """⑤b 对拍的另一半：同一份夹具、同一笔写，把路由表清空 ⇒ 它真的会被读成 `direct_write`。

    没有这一条，"`direct_write` 为 0"可能只是因为那个码从来没被数出来过。
    """
    st = _ws(tmp_path)
    reg = _reg(st)
    monkeypatch.setattr(store_mod, "DIRECT_WRITE_ROUTES", ())
    refused = _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                        row=dict(LEGAL)))
    assert refused.ok is False, refused
    stats = _stats_for(st, refused)
    assert stats.count("B", "direct_write") == 1, stats.by_role
    assert stats.category_total("routed_to_backstop") == 0, stats.by_role


# ==================================================== ⑥ 路由表：每张表每类意图


def test_every_route_in_the_table_really_takes_the_request_over(tmp_path):
    """⑥ 路由表逐行真跑一遍：每张表每类意图都真的有兜底方接住（不是表上写着而已）。

    参数按意图现造：`statements` 一条合法命题、`dependencies` 一条来源在册的边、
    `lit_candidates` 的 add / withdraw / reject / admit 各自的最小载荷。
    """
    st = _ws(tmp_path)
    reg = _reg(st)
    seen: set[tuple[str, str]] = set()
    for table, backstop, intent, entry, _where in store_mod.DIRECT_WRITE_ROUTES:
        res = _drive_intent(st, reg, table=table, intent=intent)
        blob = _blob(res)
        assert res.meta.get("backstop") == backstop or (
            res.meta.get("backstop") == backstop), (table, intent, res.meta)
        assert res.meta.get("routed_to") == entry, (table, intent, res.meta)
        # 关键：它真的被转交了 —— 不是"又拒了一次"
        assert str(res.meta.get("kind") or "").startswith("routed_to_backstop"), (
            table, intent, blob)
        assert "direct_write_refused" not in blob, (table, intent, blob)
        seen.add((table, intent))
    assert seen == {(r[0], r[2]) for r in store_mod.DIRECT_WRITE_ROUTES}, seen
    # 反真空：三张表都在路由表里（少了哪一张，"接管"就漏一层）
    assert set(store_mod.routable_direct_write_tables()) == {
        "statements", "dependencies", "lit_candidates"}


def _drive_intent(st: Store, reg: ToolRegistry, *, table: str, intent: str):
    """按意图造一份最小合法载荷，真调一次通用写口。"""
    if table == "statements":
        return _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                         row=dict(LEGAL)))
    if table == "dependencies":
        return _as("B", lambda: reg.call("table.create", role="B", table="dependencies",
                                         row={"used_by": "stmt:0000000", "kind": "theorem",
                                              "label": "引理 1",
                                              "source_lit_id": "0000",
                                              "status": "closed", "quote": "q"}))
    # `lit_candidates`：先暂存一条，再按意图改它
    added = _as("B", lambda: reg.call("table.create", role="B", table="lit_candidates",
                                      row={"title": "A candidate", "request_id": "r-0001",
                                           "batch": 1, "status": "pending"}))
    if intent == "add":
        return added
    slot = str((added.data or {}).get("id") if isinstance(added.data, dict) else "")
    if intent == "withdraw":
        return _as("B", lambda: reg.call("table.update", role="B", table="lit_candidates",
                                         id=slot,
                                         patch={"status": "withdrawn",
                                                "reason_code": "withdrawn_by_reviewer",
                                                "withdrawn_reason": "判据夹具"}))
    if intent == "reject":
        return _as("B", lambda: reg.call("table.update", role="B", table="lit_candidates",
                                         id=slot,
                                         patch={"status": "rejected",
                                                "reason_code": "rejected_off_topic",
                                                "reject_reason": "判据夹具"}))
    if intent == "admit":
        return _as("B", lambda: reg.call("table.update", role="B", table="lit_candidates",
                                         id=slot, patch={"status": "admitted"}))
    raise AssertionError(f"路由表里多了一类意图 {intent!r}，本判据没有为它造载荷")


def test_an_unreadable_intent_is_refused_not_guessed(tmp_path):
    """⑥b 意图不明 ⇒ 拒（"猜一个入口"等于换判据，比拒更坏）。"""
    st = _ws(tmp_path)
    reg = _reg(st)
    added = _as("B", lambda: reg.call("table.create", role="B", table="lit_candidates",
                                      row={"title": "A candidate", "request_id": "r-0001",
                                           "batch": 1, "status": "pending"}))
    assert added.ok is True, (added.error, added.meta)
    slot = str((added.data or {}).get("id") or "")
    res = _as("B", lambda: reg.call("table.update", role="B", table="lit_candidates",
                                    id=slot, patch={"title": "改个标题"}))
    assert res.ok is False, res
    assert res.meta.get("kind") == direct_write_kind(), res.meta
    assert "意图读不出来" in str(res.error or ""), res.error


# ==================================================== ⑦ 无感：返回值里没有指路语


def test_no_return_value_tells_the_agent_which_tool_to_go_and_use(tmp_path):
    """⑦ 返回值里不含指路语（业主 2026-10-24：「让智能体对秘书的存在无感」）。

    扫的是整个返回值（`data` / `meta` / `error`）—— 拒信与成功读数都算。
    """
    st = _ws(tmp_path)
    reg = _reg(st)
    cases = [
        _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                  row=dict(LEGAL))),                      # 路由成功
        _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                  row=dict(LEGAL, statement_full=""))),   # 兜底方拒
        _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                  row=dict(LEGAL, bits={}))),             # 野路（仍拒）
        reg.call("table.create", role="B", table="statements",
                 row=dict(LEGAL, statement_full="又一条")),                # 没挂发起方
    ]
    for res in cases:
        meta = dict(res.meta or {})
        data = dict(res.data or {}) if isinstance(res.data, dict) else {}
        prose = " ".join(str(x) for x in (res.error, data.get("what_happened"),
                                          meta.get("refused_by_backstop"),
                                          meta.get("what_happened"),
                                          meta.get("detail")))
        hit = [w for w in HINT_WORDS if w in prose]
        assert not hit, (hit, prose)


def test_the_routed_success_says_what_happened_instead_of_nagging(tmp_path):
    """⑦b 成功那一格说的是"系统替你办成了"，不是"你该去找谁"。"""
    st = _ws(tmp_path)
    reg = _reg(st)
    res = _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                    row=dict(LEGAL)))
    body = dict(res.data or {})
    assert body.get("backstop") == "secretary"
    assert "代为" in str(body.get("what_happened") or ""), body
    assert re.search(r"请|应|改走", str(body.get("what_happened") or "")) is None, body


# ==================================================== ⑧ 两种兜底方分开计


def test_the_two_kinds_of_backstop_are_counted_separately(tmp_path):
    """⑧ 统计的两种兜底方分开计（`routed_to_backstop.secretary` / `.literal` 各有数）。"""
    st = _ws(tmp_path)
    reg = _reg(st)
    a = _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                  row=dict(LEGAL)))
    b = _as("B", lambda: reg.call("table.create", role="B", table="dependencies",
                                  row={"used_by": "stmt:0000000", "kind": "theorem",
                                       "label": "引理 1", "source_lit_id": "0000",
                                       "status": "closed"}))
    assert a.ok is True, (a.error, a.meta)
    assert b.ok is True, (b.error, b.meta)
    stats = _stats_for(st, a, b)
    codes = stats.sources["hits"]["codes"]["B"]
    assert codes.get("routed_to_backstop.secretary") == 1, codes
    assert codes.get("routed_to_backstop.literal") == 1, codes
    assert stats.count("B", "direct_write") == 0, stats.by_role
    assert stats.category_total("routed_to_backstop") == 2, stats.by_role


def test_every_runtime_code_is_registered_in_the_stats_table():
    """⑧b 反真空：运行时拼得出来的码必须已经在 `errorstats` 那张表里（否则它就数不到）。"""
    for backstop in ("secretary", "literal"):
        for state in ("", "refused", "unavailable"):
            code = TT._route_code(backstop, state)
            assert code in TT.ROUTED_CODES, code
            assert ES.CODE_TO_CATEGORY.get(code) == "routed_to_backstop", code
