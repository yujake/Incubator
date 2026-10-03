# -*- coding: utf-8 -*-
"""「拒绝」只有一个形态，且它必须自报理由（`draft/37` §88）。

## 这一组守的是什么

T1 第 2 趟真机（2026-10-04）：`B.register_statement` 被召唤 14 次，其中 8 次返回
`{"ok": False, "kind": ..., "error": ...}`，而 `tasks` 台账把它们全记成 `outcome=ok`
（detail 还写着"按有产出处理"）—— 主控以为命题登记好了，于是不再改参数，
而 `statements` 是 0 行，整条链在这一步静默停住。同一趟里另外 6 次抛异常的调用
反倒记成 `failed`："拒绝"与"崩溃"同形，"成功"与"什么都没写"也同形。

修法分两处，判据也分两处：

1. 终态映射（`Conductor._end_from_payload`）不再把 `ok=False` 折叠成 `ok`
   —— 判据在 `tests/test_conductor_payload_outcomes.py`；
2. 角色动作的拒绝走同一个落点 :func:`agentflow.refusals.refuse`，并带上受控的
   `refusal_reason` —— 判据在本文件。

第 2 条为什么要机器守：它是一条形态纪律（"拒绝要自报理由"），而形态纪律
只能靠"新写的代码会被当场抓住"来维持。所以本文件用一个 AST 扫描盯住角色动作模块：
凡是手写的 `{"ok": False, ...}` 都必须逐条登记在下面的表里并写明理由
（那些是"执行了、没成功"的真失败，不是拒绝），扫描结果与表双向比对 ——
表里多一条（豁免腐烂）与少一条（新写的漏网）都会红。
"""
from __future__ import annotations

import ast
import pathlib
from collections import Counter

from agentflow import schema as S
from agentflow.refusals import PRECONDITION_REASON, refuse

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"

#: 手写 `{"ok": False, ...}` 的登记表：`(模块相对路径, kind)` → 为什么它不是"拒绝"。
#:
#: 判据是双向的：新出现一条没登记的就红（新写的动作漏用了 `refuse`），
#: 登记表里有一条扫不到的也红（豁免腐烂成"看起来还在挡着什么"）。
_FAILURES_NOT_REFUSALS: dict[tuple[str, str], str] = {
    ("agent_d/poll.py", ""):
        "工具 `research.poll_waiting` 自己失败了（不是参数不对、也不是前置条件不满足）"
        "⇒ 这是「执行了、没成功」，该落 `failed`，不该冒充 `refused`",
    ("agent_g/paper_package.py", "package_build_failed"):
        "渲染/编译是外部工具链，它失败不等于这次调用不成立 ⇒ `failed`",
    ("agent_g/paper_package.py", "state_failed"):
        "读锚失败是读盘失败，同上 ⇒ `failed`",
}


# ------------------------------------------------------------------ 一、共享落点

def test_refuse_shape_is_complete_and_controlled():
    """正控：`refuse` 四件套齐备，理由取自受控词表。"""
    out = refuse("bad_mode", "mode 不认识", mode="precise")
    assert out["ok"] is False
    assert out["kind"] == "bad_mode" and out["error"] == "mode 不认识"
    assert out["refusal_reason"] == PRECONDITION_REASON, out
    assert out["refusal_reason"] in S.REFUSAL_REASONS, (
        "拒绝理由必须是受控词表里的值 —— `Task.validate` 逐字要求"
        "（不许自由文本），不在表里会在写台账那一刻抛")
    assert out["mode"] == "precise", "动作自己的读数不许因为改形状而丢"


def test_the_precondition_reason_matches_the_vocabulary_note():
    """负控（判据的接点）：`invalid_params` 这一档必须仍在词表里、且语义仍是这一档。

    这一条挡的是"词表被人悄悄改名/删档"：那时 `refuse` 造出的每一条拒绝都会在
    写台账时抛异常 —— 而错误信息会指向词表，排查方向离这里很远。
    """
    assert PRECONDITION_REASON == "invalid_params"
    assert isinstance(S.REFUSAL_REASONS, tuple), "理由词表是元组（一处定义）"
    assert "invalid_params" in S.REFUSAL_REASONS


# ------------------------------------------------- 二、形态纪律：手写 ok=False 要登记

def _hand_rolled_ok_false(text: str) -> list[tuple[int, str]]:
    """扫一个源文件里手写的 `{"ok": False, "kind": ...}` ⇒ `[(行号, kind)]`。

    判据取的是"字典字面量里同时出现 `"ok": False`"，因为它对返回与
    `out.update({...})` 两种写法都一样 —— 后者正是 `G.paper_package` 的写法
    （只扫 `return` 会漏掉它，第一版就是这么漏的）。
    """
    tree = ast.parse(text)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        pairs = {k.value: v for k, v in zip(node.keys, node.values)
                 if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        ok = pairs.get("ok")
        if not (isinstance(ok, ast.Constant) and ok.value is False):
            continue
        kind = pairs.get("kind")
        found.append((node.lineno, kind.value if isinstance(kind, ast.Constant)
                      and isinstance(kind.value, str) else ""))
    return found


def _role_action_modules() -> list[tuple[str, pathlib.Path]]:
    """角色动作模块清单（`agent_a` … `agent_h` 下的 `.py`）。"""
    out: list[tuple[str, pathlib.Path]] = []
    for d in sorted(SRC.glob("agent_?")):
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.py")):
            out.append((p.relative_to(SRC).as_posix(), p))
    return out


def test_the_scanner_sees_a_synthetic_hit():
    """负控（反真空）：扫描器在人造样本上必须命中，否则"没扫到"无法与"干净"区分。"""
    hits = _hand_rolled_ok_false('def f():\n    return {"ok": False, "kind": "x"}\n')
    assert hits == [(2, "x")], hits
    assert _hand_rolled_ok_false('def f():\n    return {"ok": True, "kind": "x"}\n') == []


def test_every_hand_rolled_failure_is_registered_and_the_table_is_not_stale():
    """双向判据：手写 `ok=False` 的每一处都要登记；表里每一条都要还能扫到。

    少一条 = 新写的动作漏用了 `refuse`（那一次拒绝又会被记成 ok，回到 T1 的坑）；
    多一条 = 豁免腐烂（登记的理由已经不成立，表在假装还挡着什么）。
    """
    live: Counter[tuple[str, str]] = Counter()
    scanned = 0
    for rel, path in _role_action_modules():
        text = path.read_text(encoding="utf-8")
        scanned += 1
        for _lineno, kind in _hand_rolled_ok_false(text):
            live[(rel, kind)] += 1
    assert scanned >= 8, f"只扫到 {scanned} 个角色动作模块 ⇒ 扫描面接错了"

    want = Counter(dict.fromkeys(_FAILURES_NOT_REFUSALS, 1))
    # `paper_package` 的 package_build_failed 目前有两处（渲染失败 / 编译失败）
    want[("agent_g/paper_package.py", "package_build_failed")] = 2

    missing = live - want
    stale = want - live
    assert not missing, (
        "这些手写的 ok=False 没有登记，也没有走 `agentflow.refusals.refuse`："
        f"{sorted(missing)} ⇒ 它们的拒绝会再次被台账记成 ok")
    assert not stale, f"登记表里这些条目已经扫不到了（豁免腐烂，请删）：{sorted(stale)}"
    for (rel, kind), reason in _FAILURES_NOT_REFUSALS.items():
        assert len(reason) > 20, f"{rel}:{kind} 的登记理由太短，等于没写为什么"


def test_the_three_refusing_actions_really_return_a_controlled_refusal(tmp_path):
    """正控（端到端）：三条动作的拒绝现在都带受控理由 —— 而不是只改了源码形状。

    为什么要落到真对象上：上面那条 AST 判据只能看出"没手写 ok=False"，
    看不出"它真的调了 refuse"。这一条把两个最容易漏的动作各调一次，
    断言那一笔零写入且带 `refusal_reason`。
    """
    from agentflow.agent_a import AgentA
    from agentflow.store import Store

    ws = tmp_path / "ws"
    ws.mkdir()
    st = Store(ws)
    st.init()
    a = AgentA(st, providers=[])

    empty = a.ingest_local(books_dir="  ")
    assert empty["ok"] is False and empty["kind"] == "bad_books_dir", empty
    assert empty["refusal_reason"] == PRECONDITION_REASON, empty

    missing = a.ingest_local(books_dir="没有这个目录")
    assert missing["ok"] is False and missing["kind"] == "dir_not_found", missing
    assert missing["refusal_reason"] == PRECONDITION_REASON, missing
    assert missing["resolved"], "解析出来的路径要给出来（'我指对了没有'不用猜）"

    no_provider = a.search_literature(topic="stable norm of periodic graphs")
    assert no_provider["ok"] is False and no_provider["kind"] == "no_provider", no_provider
    assert no_provider["refusal_reason"] == PRECONDITION_REASON, no_provider

    assert st.rows("literature") == [] and st.rows("search_requests") == [], (
        "被拒的调用不许留下半行")
