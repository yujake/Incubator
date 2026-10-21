# -*- coding: utf-8 -*-
"""「做我这一趟被派的那个动作」这件工具：`--drive` / `--subagents` 那一档的收尾。

## 这一组治的是真机上的一个结构性缺口（业主 2026-10-14 裁定 ③ 的收尾）

`--subagents`（`cli.py`，2026-09-30 上线）会把所有 `(角色, 动作)` 交给 LLM 循环 ——
包括那些带写库闸门的确定性动作。而被派的那个动作不在任何角色的工具面上
（`capabilities._KNOWN_UNMATCHED_ACTIONS` 逐条登记的就是这一族）⇒ 子代理拿不到
自己被派的活。真机读数（`p9-t1-nolean` 那一趟，父→子→孙三跳）：

- B 拿到 `unknown_tool`（原话："`register_statement` 不在 B 的工具面上"）；
- 它改去 `table.create(table="statements")` 手写行 ⇒ 绕过 `register_statement` 的
  出处核对、页码形状、引文证据、取号与查重五道预检，`quote_verified=true` 成了自报；
- 那一趟的 5 条孙代理活全废（3 条崩、2 条被并发上限拒）。

修法：把这一趟被派的动作原样包成一件只活在这一次循环里的工具（名字就是动作名），
handler 走内层确定性实现 —— 闸门一个不少。这一组按"正控两条 + 反负控一条"写。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from conftest import TS, add_literature
from agentflow import schema as S
from agentflow.agent_loop import LlmBackend
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

#: 这一趟把 `B.register_statement` 交给循环 —— 就是真机里出事的那一格。
LOOPS: dict[tuple[str, str], dict] = {("B", "register_statement"): {"max_steps": 4}}

_GOOD_ROW: dict = {
    "statement_full": "设 G 是有限连通图；则距离的标准化收敛到正态。",
    "source_lit_id": "000000", "origin": "external_lit", "kind": "theorem",
    "label": "Theorem 1.5", "proof_text": "Proof. 见 companion book 6.5。",
    "page_range": {"start": 7, "end": 8, "label": "pp. 7-8"},
    "quote_verified": True, "quote_mode": "verbatim", "quote_reason": "逐字命中 p.7",
}


class _Scripted:
    """照剧本回答的替身模型：每次取一条，取完重复最后一条。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None, **kw):
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


class _StubB:
    """B 的确定性替身：只实现 `register_statement`（这一组要的是"那条路通不通"）。"""

    def __init__(self, store: Store) -> None:
        self.store = store

    def register_statement(self, **params) -> dict:
        """真实现的最小形态：出处核对 + 页码形状 + 落一行（预检的形态照抄真实现）。"""
        lit = str(params.get("source_lit_id") or "")
        have = {str(r.get("lit_id")) for r in self.store.rows("literature")}
        if params.get("origin") == "external_lit" and lit not in have:
            return {"ok": False, "kind": "missing_source",
                    "reason": f"literature 里没有 lit_id={lit!r}（出处不在库整笔不写）",
                    "available_lit_ids": sorted(have)}
        page = params.get("page_range")
        if not isinstance(page, dict):
            return {"ok": False, "kind": "bad_page_range",
                    "reason": "page_range 必须是对象（{\"start\":7,\"end\":8} 这种）"}
        row = S.Statement(
            stmt_id=S.format_id(0), origin=str(params.get("origin") or "external_lit"),
            kind=str(params.get("kind") or "theorem"), label=str(params.get("label") or ""),
            statement_full=str(params.get("statement_full") or ""),
            proof_text=str(params.get("proof_text") or ""), source_lit_id=lit,
            page_range=S.PageRange.from_dict(page),
            quote_verified=params.get("quote_verified"),
            quote_reason=str(params.get("quote_reason") or ""), status="active",
            created_at=TS)
        row.validate()
        with self.store.tx("statements", actor="stub-B") as tx:
            tx.upsert("statements", row.to_dict())
        return {"ok": True, "stmt_id": row.stmt_id, "row": row.to_dict()}


def _world(tmp_path: pathlib.Path, replies: list[str]):
    """一个工作区 + 一张"B 被派去 register_statement"的台账行（`task_id=child`）。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    add_literature(st, "000000", title="Brown 1971")
    gw = _Scripted(replies)
    inner = LocalBackend({"B": ("object", _StubB(st))})
    inner.store = st
    backend = LlmBackend(
        inner=inner, loops=LOOPS, session_root=ws, store=st, sid="t",
        workspace_root=str(ws),
        registry=build_registry(store=st, workspace_root=ws).registry,
        seam_factory=lambda role: LlmSeam(role=role, session_root=ws, gateway=gw,
                                          price=(0.0, 0.0), sid="t"))
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    backend.registry = build_registry(store=st, conductor=cond,
                                      workspace_root=str(ws)).registry
    child = cond._write_new_row({
        "task_id": "", "role": "B", "action": "register_statement", "called_by": "A",
        "parent_task_id": None, "depth": 2, "input_key": "own@child", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "被派的那个动作",
        "error": None, "started_at": TS, "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:B.register_statement")
    return st, cond, backend, child


def _tool(name: str, args: dict) -> str:
    """一步 `tool` 形状的替身回复（形状照 AgentLoop 的协议：`{"tool":名,"args":{…}}`）。"""
    return json.dumps({"tool": name, "args": args, "why": "夹具这一步"}, ensure_ascii=False)


def _final(text: str) -> str:
    return json.dumps({"final": text, "evidence": []}, ensure_ascii=False)


def _steps(res: dict) -> list[dict]:
    """这一趟的每一步（`LlmBackend` 把完整记录写盘，结果里只给路径）。"""
    path = str(res.get("llm_run_path") or "")
    if path and pathlib.Path(path).is_file():
        return list(json.loads(pathlib.Path(path).read_text(encoding="utf-8")).get("steps") or [])
    return list((res.get("llm_run") or {}).get("steps") or [])


def test_the_driven_child_can_call_the_action_it_was_summoned_for(tmp_path):
    """正控：循环里能直接调 `register_statement`，走的是带闸门的真实现。

    两件事一起判：① 返回是动作自己的受控拒绝（`kind=bad_page_range`）——证明它调到了
    真实现而不是被兜成 `unknown_tool`；② 盘上 statements 一条没有 —— 证明它没有
    绕道 `table.create` 手写表。
    """
    bad = dict(_GOOD_ROW, page_range="343-414")   # 真机里那个"页码写成字符串"
    st, cond, backend, child = _world(tmp_path, [
        _tool("own.register_statement", dict(bad)),
        _final("登记被拒，见 reason"),
    ])
    res = backend.call("B", "register_statement", {}, token=None, instance="", task_id=child)
    assert res["stop_reason"] == "final", res
    steps = _steps(res)
    assert steps, res
    first = next(s for s in steps if s.get("shape") == "tool")
    got = first.get("result") or {}
    assert got.get("ok") is False, got
    # 拒绝是哪一层给的都算"真判据挡下了"：工具层按动作声明面的参数 schema 先拦
    # （`page_range` 必须是对象），真实现那一层还有自己的 `bad_page_range`。
    assert "page_range" in json.dumps(got, ensure_ascii=False), got
    assert st.rows("statements") == [], (
        "被拒的那一笔居然落了库（或者绕道手写表）："
        + json.dumps(st.rows("statements"), ensure_ascii=False)[:300])


def test_the_injected_tool_writes_through_the_real_implementation(tmp_path):
    """正控之二：参数合规时，行是那套实现写下的（出处栏与证据栏都在）。"""
    st, cond, backend, child = _world(tmp_path, [
        _tool("own.register_statement", dict(_GOOD_ROW)),
        _final("已登记"),
    ])
    res = backend.call("B", "register_statement", {}, token=None, instance="", task_id=child)
    assert res["stop_reason"] == "final", res
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    assert rows[0]["stmt_id"] == S.format_id(0), rows[0]
    assert rows[0]["source_lit_id"] == "000000", rows[0]
    assert rows[0]["page_range"]["start"] == 7, rows[0]


def test_without_the_injection_the_child_is_back_to_writing_tables_by_hand(tmp_path, monkeypatch):
    """反负控：把注入关掉 ⇒ 这一趟两条路都断（正路没有、野路被拒）。
    ## 这一条的口径在 2026-10-19 晚换过（`projects/mp2` 的真机读数）
    改前它断的是"关掉注入之后 `table.create` 那条路真的走得通" —— 那时野路还开着，于是"绿是注入带来的"用"手写表落了库"来证明。
    现在野路被`store.direct_write_refusal` 受控拒绝（`mp2-7.jsonl` 第 97 行就是它的真机形态），所以本判据改成更强的那一版：
    1. `own.register_statement` 没了 ⇒ 这一步是 `unknown_tool`（正路真的断在这件工具上）；
    2. `table.create("statements")` 也落不了库 ⇒ `ok=False` + `direct_write_refused`，
    且拒信把模型指回正路；
    3. 盘上 statements 0 行 —— 于是正向用例里那一行，除了"注入真的发生了"以外
    没有任何别的解释（改前那条"手写表也能落库"的出口已经被封掉）。
    """
    monkeypatch.setattr(LlmBackend, "_registry_with_own_action",
                        lambda self, base, **kw: base, raising=True)
    # 手写表这一笔连形状都合规（它能过 `table.create` 的字段校验），
    # 可它违反的是动作自己的出处预检（`source_lit_id=999999` 不在 literature 里）
    # 与"这两张表只经秘书"这条规矩 —— 两条都该把它挡在外面。
    bad = dict(_GOOD_ROW, source_lit_id="999999")
    st, cond, backend, child = _world(tmp_path, [
        _tool("own.register_statement", dict(bad)),
        _tool("table.create", {"table": "statements",
                               "row": dict(bad, statement_full="手写的那一行")}),
        _final("两条路都不通"),
    ])
    res = backend.call("B", "register_statement", {}, token=None, instance="", task_id=child)
    assert res["stop_reason"] == "final", res
    steps = _steps(res)
    tool_steps = [s for s in steps if s.get("shape") == "tool"]
    first, second = tool_steps[0], tool_steps[1]
    assert "unknown_tool" in json.dumps(first.get("result") or {}, ensure_ascii=False), first
    got = second.get("result") or {}
    assert got.get("ok") is False, got
    assert (got.get("meta") or {}).get("kind") == "direct_write_refused", got
    assert "Secretary.record_statement" in str(got.get("error") or ""), got
    assert st.rows("statements") == [], (
        "野路居然落库了 —— 那正向用例的绿就说明不了'绿是注入带来的'："
        + str(st.rows("statements"))[:200])


# ---------------------------------------------------------------------------
# 名字那一格：带下划线的广告名 vs 本趟没注册的动作名（`own_register_statement` 的真机形态）。真机读数：
# `projects/fb-cover/sessions/fb-1.jsonl` 那次同时有 `own.register_statement`（6 次）与 `own_register_statement`（1 次）。
# 根因（2026-10-20）：接住它的是 `AgentLoop._do_tool` 的广告名那一格（`face.names.get(raw)`），不是「短名 →
# `own.<动作名>`」那一格（后者拼出 `own.own_register_statement`，本趟注册表里没有它）。广告名由
# `llmseam.build_tool_face` 按本趟真在注册表里的那张面算出（`_sanitize` 把 `[A-Za-z0-9_-]` 之外全换 `_`），
# 且 `_do_tool` 要求解析出的真名 `in known` ⇒ 不打开任何权限。判据：正控 = 带下划线变体映到同一件；
# 负控 = 未注册名（`own_not_registered_thing`）必须 `unknown_tool`、`aliased_from` 为空 —— 只测正控的话
# "宽映射"与"窄映射"长得一模一样，这一条才是分辨率所在。
def test_the_underscored_advertised_name_reaches_the_same_action_and_nothing_else(tmp_path):
    """正控：带下划线的广告名映回同一件真实现；负控：没注册的名字必须 `unknown_tool`。为什么两条必须写在同一条里：它们守的是同一张表的两侧（`face.names` 里有什么 /没有什么）。分两条写时，"正控绿、
    负控也绿"无法排除"负控那一步其实根本没跑到"—— 这里两步出自同一趟的同一个注册表，读数可以直接对起来。

    ## 剧本为什么是三条回复（第二条会"多花"一次调用）

    顺控是先负后正：负控那一步（`own_not_registered_thing`）名字不在注册表里 ⇒`_statement_filing_refusal` 那一道不触发（它的第一句就是
    `name != own.register_statement⇒ None`），所以那一步就是干净的一步。紧接着的正控会多花一次模型调用
    ——入库前秘书那句"太平凡吗"（`secretary.judge_statement`）走的是同一个网关，它吃掉剧本里的第 3 条（`_final`）；`_Scripted` 的"取完重复最后一条"于是让循环下一步照样拿到
    `_final`。反过来读这第 3 条回复：它被吃掉本身就是读数 ——带下划线的那个名字走的是同一件 `own.register_statement`（连同它入库前的闸门），不是另一条旁路。
    """
    st, cond, backend, child = _world(tmp_path, [
        _tool("own_not_registered_thing", {}),              # 负控：本趟没有这一件
        _tool("own_register_statement", dict(_GOOD_ROW)),   # 正控：广告名的下划线变体
        _final("一真一假两条路都试过"),
    ])
    res = backend.call("B", "register_statement", {}, token=None, instance="", task_id=child)
    assert res["stop_reason"] == "final", res
    tool_steps = [s for s in _steps(res) if s.get("shape") == "tool"]
    assert len(tool_steps) >= 2, (
        "这一趟没跑出两步工具调用 —— 最可能的形态是**负控那一步被某个宽映射接住了**"
        "（它本该一步就 `unknown_tool` 返回，于是后面那一步还得再占一脚）："
        + json.dumps(tool_steps, ensure_ascii=False)[:300])
    first, second = tool_steps[0], tool_steps[1]

    # ---- 负控：没注册的动作名必须被拒成 `unknown_tool`，并且不是被别名格接住之后才失败。
    bad = first.get("result") or {}
    assert bad.get("ok") is False, bad
    assert "unknown_tool" in json.dumps(bad, ensure_ascii=False), bad
    assert not bad.get("aliased_from"), (
        "一个本趟没注册的名字被别名格接住了 —— 那正是这条判据要挡的宽映射："
        + json.dumps(bad, ensure_ascii=False)[:300])
    # 负控那一步没有进工具层：`meta.kind` 是 `unknown_tool`，且这一步不带任何工具数据
    # （`data` 为空 —— 一次"名字不认识"的调用什么都没碰）。
    assert (bad.get("meta") or {}).get("kind") == "unknown_tool", bad
    assert not bad.get("data"), bad

    # ---- 正控：映回同一件（真名带点），并把"模型写的是哪个名字"如实带回来。
    got = second.get("result") or {}
    assert got.get("ok") is True, got
    assert got.get("tool") == "own.register_statement", got
    assert got.get("aliased_from") == "own_register_statement", got
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    assert rows[0]["stmt_id"] == S.format_id(0), rows[0]
    assert rows[0]["source_lit_id"] == "000000", rows[0]
    assert rows[0]["page_range"]["start"] == 7, rows[0]
