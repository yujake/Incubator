# -*- coding: utf-8 -*-
"""判据：组内 AND / 组间 OR 在依赖图的每一层都成立（审计 B 线缺陷 1，业主已批准改语义）。

## 语义（唯一真身，`draft/141` 缺陷 1）

一条 `used_by` 的依赖图里：

```text
同一 (证明号, path_group) 内的多条边 = AND（都要走到根）
不同 (证明号, path_group)         = OR（任一条证明 / 任一组走到根即算到根）
到根 = 存在一条 (证明号, path_group) 分支，其组内每条边都到根
```

## 改前红在哪里

改前只有顶层满足 OR：`proof_chain` 在顶层逐 `(证明号, path_group)` 各走一遍再挑
（OR），而 `_grow` 下潜一层就变成"全走一遍、任一失败即整体失败"（AND）。于是同一个
孩子（子命题 `0002` 的 `#p1` 悬空、`#p2` 到根）在顶层读成 OR、在孩子那一层读成 AND。

| 判据 | 改前红在哪里 |
|---|---|
| ① 子命题层 OR | `reached=False`、`best_proof_no=None`、`length` 报最深那条（3 跳）而不是那条短路径（2 跳） |
| ② 顶层与子层同一条规则 | 顶层那棵树本来就绿（2 组、第 2 条证明），子层那棵读成 AND ⇒ 同构断言红 |
| ③ 组内 AND 仍成立 | 只有一组、组内一条边悬空那一半改前也绿；"另一组可行 ⇒ 整体到达"这一半改前红 |
| ④ 全不可行逐条说明 | 改前没有 `failures`（哪条分支、为什么），也没有显式的 `closed=False` |
| ⑤ 坏尾巴 + 没有可用分支 | 改前 `summary` 说"已经是根 ⇒ 闭合"、`closed=True`（审计缺陷 11） |
| ⑥ 反真空 | 把 `_or_holds` 换成 `all`（或把 `_and_holds` 换成 `any`）⇒ ①②③ 必须红 |

全部 tmp 工作区、零模型调用。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest  # noqa: E402

from agentflow import schema as S          # noqa: E402
from agentflow.agent_c import AgentC       # noqa: E402
from agentflow.store import Store          # noqa: E402

TS = "2026-10-22T00:00:00+08:00"


# ------------------------------------------------------------------ 夹具


def _store(root: pathlib.Path) -> Store:
    st = Store(root / "ws")
    st.init()
    return st


def _stmt(st: Store, sid: str, *, evidence: str = "cross_check",
          proof_text: str = "", kind: str = "theorem") -> None:
    row = S.Statement(stmt_id=sid, origin="own_result", kind=kind,
                      label=f"命题 {sid}", statement_text="短版",
                      statement_full="若假设 A 成立，则结论 B 成立",
                      proof_text=proof_text, source_lit_id=None,
                      quote_verified=None, quote_reason="夹具（还没核）",
                      evidence_kind=evidence, aliases=[], status="active",
                      created_at=TS)
    row.validate()
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict(), note="stmt")


def _lit(st: Store, lid: str) -> None:
    row = S.Literature(lit_id=lid, title=f"文献 {lid}", type="J", summary="s",
                       path=None, added_at=TS)
    row.validate()
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict(), note="lit")


def _dep(st: Store, did: str, used_by: str, *, stmt: str = "", lit: str = "",
         group: int = 1, status: str = "closed", reason: str = "") -> None:
    row = S.Dependency(dep_id=did, used_by=used_by,
                       kind="theorem" if stmt else "prior_art",
                       label=stmt or lit or "前提", status=status,
                       status_reason=reason, source_stmt_id=stmt or None,
                       source_experiment_id=None, source_lit_id=lit or None,
                       path_group=group, created_at=TS)
    row.validate()
    with st.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", row.to_dict(), note="dep")


def _tree_sub(root: pathlib.Path) -> Store:
    """目标 0001 的两条证明：`#p1` 断在一条不在册的文献，`#p2` 走子命题 0002。

    子命题 0002 自己的两条证明：`#p1` 是一条更深的死路（0002 → 0003 → 不在册的文献，
    2 跳），`#p2` 直接到根（1 跳）。改前子命题那一层把这两条证明读成 AND。
    """
    st = _store(root)
    _stmt(st, "0001")
    _stmt(st, "0002")
    _stmt(st, "0003")
    _lit(st, "0009")
    # 目标那一层：p1 断（1 跳）；p2 走子命题
    _dep(st, "0001", "stmt:0001", lit="0007")
    _dep(st, "0002", "stmt:0001#p2", stmt="0002")
    # 子命题那一层：p1 是更深的死路；p2 到根
    _dep(st, "0003", "stmt:0002", stmt="0003")
    _dep(st, "0004", "stmt:0003", lit="0007")
    _dep(st, "0005", "stmt:0002#p2", lit="0009")
    return st


def _tree_main(root: pathlib.Path) -> Store:
    """同一条规则挂在顶层：目标 0001 自己的两条证明，`#p1` 断、`#p2` 到根。"""
    st = _store(root)
    _stmt(st, "0001")
    _lit(st, "0009")
    _dep(st, "0001", "stmt:0001", lit="0007")
    _dep(st, "0002", "stmt:0001#p2", lit="0009")
    return st


def _tree_and_one_edge_dangling(root: pathlib.Path) -> Store:
    """同一条 (证明, 组) 内的两条边：一条到根、一条悬空 ⇒ 这一组不可行。"""
    st = _store(root)
    _stmt(st, "0001")
    _stmt(st, "0002")
    _lit(st, "0009")
    _dep(st, "0001", "stmt:0001", stmt="0002")
    _dep(st, "0002", "stmt:0002", lit="0009", group=1)
    _dep(st, "0003", "stmt:0002", group=1, status="dangling", reason="来源还没定")
    return st


def _tree_or_across_groups(root: pathlib.Path) -> Store:
    """子命题的组 1 不可行（组内 AND 挡住）、组 2 到根 ⇒ 组间 OR 让整体到根。"""
    st = _store(root)
    _stmt(st, "0001")
    _stmt(st, "0002")
    _lit(st, "0009")
    _dep(st, "0001", "stmt:0001", stmt="0002")
    _dep(st, "0002", "stmt:0002", lit="0009", group=1)
    _dep(st, "0003", "stmt:0002", group=1, status="dangling", reason="来源还没定")
    _dep(st, "0004", "stmt:0002", lit="0009", group=2)
    return st


def _tree_all_branches_broken(root: pathlib.Path) -> Store:
    """所有分支都断：目标 p1 断在不在册的文献；p2 走子命题（子命题 p1 深死路、p2 悬空）。"""
    st = _store(root)
    _stmt(st, "0001")
    _stmt(st, "0002")
    _stmt(st, "0003")
    _dep(st, "0001", "stmt:0001", lit="0007")
    _dep(st, "0002", "stmt:0001#p2", stmt="0002")
    _dep(st, "0003", "stmt:0002", stmt="0003")
    _dep(st, "0004", "stmt:0003", lit="0007")
    _dep(st, "0005", "stmt:0002#p2", status="dangling", reason="来源还没定")
    return st


# ------------------------------------------------------------------ 读数的断言本体
#
# 判据 ⑥（反真空）要把下面这三个函数在"规则被换掉"的实现上重跑一遍：它们必须是
# 真的落在"规则"上，而不是落在措辞上。


def _sub_reading(rep) -> None:
    """判据 ① 的断言本体：子命题层那一条 OR 成立。

    子命题 0002 的 `#p1` 悬空、`#p2` 到根 ⇒ 整体 `reached=True`、`best_proof_no=2`、
    `length` 是那条 2 跳的短路径（0001 → 0002 → lit:0009）。
    """
    p = rep.payload
    assert rep.ok is True, rep.error
    assert p["groups_total"] == 2, p
    assert p["best_proof_no"] == 2 and p["best_group"] == 1, (
        "子命题那一层的 OR 没成立：赢的不是第 2 条证明的第 1 组"
        f"（best_proof_no={p.get('best_proof_no')!r} best_group={p.get('best_group')!r}；"
        f"summary={rep.summary!r}）")
    by = {(int(g["proof_no"]), int(g["group"])): g for g in p["groups"]}
    best = by[(2, 1)]
    assert best["reached"] is True, (
        "子命题 0002 的 #p2 到根、#p1 悬空，这条路却读成没到根："
        f"{ {k: best[k] for k in ('reached', 'length', 'why')} }")
    assert best["length"] == 2, (
        "length 不是那条 2 跳的可行路径（0001 → 0002 → lit:0009），而是取了所有分支里"
        f"最深的那条：{best['length']}")
    assert best["why"] == "", best["why"]
    # 死路那条备选分支仍然逐条带出，但不许把整条路读成"没到根"。
    dead = [item for item in best["failures"] if item["status"] == "unwritten"]
    assert dead and dead[0]["blocking"] is False, best["failures"]
    assert by[(1, 1)]["reached"] is False, by[(1, 1)]
    assert "第 2 条证明" in rep.summary and "2 跳" in rep.summary, rep.summary


def _and_reading(rep) -> None:
    """判据 ③ 前半的断言本体：组内 AND 仍成立（一条边悬空 ⇒ 这一组不可行）。"""
    p = rep.payload
    assert rep.ok is True, rep.error
    assert p["groups_total"] == 1, p
    g = p["groups"][0]
    assert g["reached"] is False, g
    assert p["best_group"] is None and p["best_proof_no"] is None, p
    assert g["failures"], f"悬空那条边没有逐条带出：{g}"
    bad = [item for item in g["failures"] if item["status"] == "dangling"]
    assert bad, g["failures"]
    assert bad[0]["blocking"] is True and bad[0]["why"] and bad[0]["node"], bad[0]
    assert "没有可行分支" in g["why"], g["why"]
    assert p.get("closed") is False, p


def _same_rule_at_both_layers(main_rep, sub_rep) -> None:
    """判据 ② 的断言本体：顶层与子层的读数同构（只差一层深度）。"""
    assert _verdict(main_rep) == {"groups_total": 2,
                                  "reached": {(1, 1): False, (2, 1): True},
                                  "best_proof_no": 2, "best_group": 1}, main_rep.payload
    assert "第 2 条证明的第 1 组" in main_rep.summary, main_rep.summary
    assert "第 2 条证明的第 1 组" in sub_rep.summary, sub_rep.summary
    assert _verdict(sub_rep) == _verdict(main_rep), (
        "同一条规则在顶层与它下一层给出了不同的答案："
        f"顶层={_verdict(main_rep)!r} 子层={_verdict(sub_rep)!r}；"
        f"子层的 summary={sub_rep.summary!r}")
    assert _best_length(sub_rep) == _best_length(main_rep) + 1, (
        _best_length(sub_rep), _best_length(main_rep))


def _verdict(rep) -> dict:
    """把一份读数压成"哪条分支到根、赢的是哪一条"（判据 ② 的同构比较用它）。"""
    p = rep.payload
    return {"groups_total": p["groups_total"],
            "reached": {(int(g["proof_no"]), int(g["group"])): bool(g["reached"])
                        for g in p["groups"]},
            "best_proof_no": p["best_proof_no"],
            "best_group": p["best_group"]}


def _best_length(rep) -> int:
    """赢的那一组报的长度（`best_proof_no` / `best_group` 指的那一组）。"""
    p = rep.payload
    hit = [g for g in p["groups"]
           if (int(g["proof_no"]), int(g["group"]))
           == (p["best_proof_no"], p["best_group"])]
    assert len(hit) == 1, p["groups"]
    return int(hit[0]["length"])


# ------------------------------------------------------------------ ① 子命题层


def test_a_sub_proposition_with_one_dead_proof_still_reaches_the_root(
        tmp_path: pathlib.Path) -> None:
    """判据①：子命题 0002 的 `#p1` 悬空、`#p2` 到根 ⇒ `reached=True`、`best_proof_no=2`。

    改前红：`_grow` 把子命题的两条证明当 AND（任一失败即整组失败）⇒ 读数
    `summary = "命题 0001：2 组可选路径，没有一组走到根（见 warnings）"`、
    `(2,1).reached=False`、`best_proof_no=None`、`length=3`（取所有分支里最深的那条，
    而可行的那条只有 2 跳）。
    """
    _sub_reading(AgentC(_tree_sub(tmp_path)).proof_chain("0001"))


# ------------------------------------------------------------------ ② 顶层与子层同一条规则


def test_the_top_layer_and_a_sub_layer_follow_the_same_rule(tmp_path: pathlib.Path) -> None:
    """判据②：两条证明挂在顶层 target 上 ⇒ 与判据①的读数同构（只差一层深度）。

    改前红：顶层这一棵树本来就绿（"2 组可选路径，最短是第 2 条证明的第 1 组"），
    而同一形状下沉一层（判据①那棵树）读成 AND ⇒ 两层读数不同构。这一条红的正是
    "同一条规则在两层给出不同答案"，不是"顶层坏了"。
    """
    main_rep = AgentC(_tree_main(tmp_path / "main")).proof_chain("0001")
    sub_rep = AgentC(_tree_sub(tmp_path / "sub")).proof_chain("0001")
    _same_rule_at_both_layers(main_rep, sub_rep)


# ------------------------------------------------------------------ ③ 组内 AND 仍成立


def test_the_and_inside_a_group_and_the_or_across_groups_both_hold(
        tmp_path: pathlib.Path) -> None:
    """判据③：组内 AND 仍成立；另一组可行 ⇒ 整体仍 `reached=True`。

    改前红（后半）：子命题的两组路径被 AND 到一起（组 2 到根也救不了）⇒ 整体
    `reached=False`；前半（组内一条边悬空 ⇒ 那一组不可行）改前也绿，留作反真空的
    另一半（判据⑥ 把 AND 换成 OR，这一半必须红）。
    """
    _and_reading(AgentC(_tree_and_one_edge_dangling(tmp_path / "and")).proof_chain("0001"))
    rep = AgentC(_tree_or_across_groups(tmp_path / "or")).proof_chain("0001")
    p = rep.payload
    assert rep.ok is True, rep.error
    assert p["groups_total"] == 1, p
    g = p["groups"][0]
    assert g["reached"] is True, (
        "子命题的组 2 到根，整体却读成没到根（组间 OR 没成立）："
        f"{ {k: g[k] for k in ('reached', 'length', 'why')} }")
    assert g["length"] == 2, g["length"]
    assert g["why"] == "", g["why"]
    dangling = [item for item in g["failures"] if item["status"] == "dangling"]
    assert dangling and dangling[0]["path_group"] == 1, g["failures"]
    assert dangling[0]["blocking"] is False, dangling[0]


# ------------------------------------------------------------------ ④ 全不可行


def test_when_every_branch_is_broken_the_reasons_are_named_one_by_one(
        tmp_path: pathlib.Path) -> None:
    """判据④：所有分支都断 ⇒ `reached=False`，且逐条说明"哪条分支、为什么"。

    改前红：没有 `failures`（每条不可行分支的原因只在全局 warning 里）也没有显式的
    `closed=False`；`length` 还被读成所有分支里最深的那条而不加任何说明。
    """
    rep = AgentC(_tree_all_branches_broken(tmp_path)).proof_chain("0001")
    p = rep.payload
    assert p["best_group"] is None and p["best_proof_no"] is None, p
    assert "没有可行分支" in rep.summary, rep.summary
    statuses: set[str] = set()
    for g in p["groups"]:
        assert g["reached"] is False, g
        assert g["failures"], f"这一组没有逐条说明为什么不可行：{g}"
        for item in g["failures"]:
            assert {"node", "proof_no", "path_group", "status", "why",
                    "blocking"} <= set(item), item
            assert item["node"] and item["why"], item
            assert item["blocking"] is True, item
            statuses.add(str(item["status"]))
        assert g["why"].startswith("没有可行分支"), g["why"]
    assert {"unwritten", "dangling"} <= statuses, statuses
    assert p.get("closed") is False, p
    by = {(int(g["proof_no"]), int(g["group"])): g for g in p["groups"]}
    # 全不可行时才报"最深的那条已走前缀"：0001 → 0002 → 0003 → lit:0007 = 3 跳。
    assert by[(2, 1)]["length"] == 3, by[(2, 1)]
    assert by[(2, 1)]["why"].startswith("没有可行分支"), by[(2, 1)]["why"]


# ------------------------------------------------------------------ ⑤ 坏尾巴 + 无可用分支


def test_an_unreadable_dependency_is_not_reported_as_a_closed_root(
        tmp_path: pathlib.Path) -> None:
    """判据⑤：`bad_used_by` 非空且没有可用分支 ⇒ summary 说"没查成"，不许 `closed=True`。

    改前红（审计 B 缺陷 11）：唯一的依赖是坏尾巴时 `groups_of(命题号)` 是空的，
    而目标自己有 proof 证据 ⇒ 读数 `summary="…：已经是根（无依赖…）⇒ 这一条链闭合"`、
    `closed=True`、`roots=[命题号]`。事实是"这条依赖读不懂"，不是"没有依赖"。
    """
    only_bad = _store(tmp_path / "only-bad")
    _stmt(only_bad, "0001", evidence="proof", proof_text="Proof. 检查器核过……")
    _lit(only_bad, "0009")
    _dep(only_bad, "0001", "stmt:0001#pabc", lit="0009")
    rep = AgentC(only_bad).proof_chain("0001")
    p = rep.payload
    assert p["bad_used_by"] == ["stmt:0001#pabc"], p
    assert p.get("closed") is False, p
    assert "没查成" in rep.summary, rep.summary
    assert "已经是根" not in rep.summary and "闭合" not in rep.summary, rep.summary
    assert rep.ok is False and p.get("unknown") is True, rep.to_dict()

    # 另一半：还有一条读得懂、但到不了根的边 ⇒ 仍然不许说"闭合"。
    dead = _store(tmp_path / "dead")
    _stmt(dead, "0001")
    _lit(dead, "0009")
    _dep(dead, "0001", "stmt:0001#pabc", lit="0009")
    _dep(dead, "0002", "stmt:0001", lit="0007")
    rep2 = AgentC(dead).proof_chain("0001")
    p2 = rep2.payload
    assert p2["bad_used_by"] == ["stmt:0001#pabc"], p2
    assert p2["best_group"] is None and p2.get("closed") is False, p2
    assert "没查成" in rep2.summary, rep2.summary
    assert "闭合" not in rep2.summary and "已经是根" not in rep2.summary, rep2.summary


# ------------------------------------------------------------------ ⑥ 反真空


def test_the_criteria_go_red_when_the_rules_are_flipped(tmp_path: pathlib.Path,
                                                        monkeypatch) -> None:
    """判据⑥ 反真空：把 OR 换成 AND（或把 AND 换成 OR）⇒ 判据①②③ 必须红。

    这一条防的是"判据写着 OR、其实没落在 OR 上"：如果断言与组合规则无关，那么换掉
    规则之后它们仍然是绿的，`pytest.raises` 会当场红。
    """
    from agentflow.agent_c import proof_chain as PC

    # 先证明未打补丁时这些断言是绿的（否则"红了"可能是因为别的原因）。
    _sub_reading(AgentC(_tree_sub(tmp_path / "ok-sub")).proof_chain("0001"))
    _and_reading(AgentC(_tree_and_one_edge_dangling(tmp_path / "ok-and")).proof_chain("0001"))

    # ① 组间 OR 改成"每条分支都要"（AND）⇒ 子命题那一层读不到根。
    flip_or_sub = _tree_sub(tmp_path / "flip-or")
    flip_or_main = _tree_main(tmp_path / "flip-or-main")
    monkeypatch.setattr(PC, "_or_holds", all)
    monkeypatch.setattr(PC, "_or_length", max)
    with pytest.raises(AssertionError):
        _sub_reading(AgentC(flip_or_sub).proof_chain("0001"))
    with pytest.raises(AssertionError):
        _same_rule_at_both_layers(AgentC(flip_or_main).proof_chain("0001"),
                                 AgentC(_tree_sub(tmp_path / "flip-or-2")).proof_chain("0001"))

    # ② 组内 AND 改成"任一条就算"（OR）⇒ 悬空那条边不再挡住这一组。
    monkeypatch.setattr(PC, "_or_holds", any)
    monkeypatch.setattr(PC, "_or_length", min)
    monkeypatch.setattr(PC, "_and_holds", any)
    monkeypatch.setattr(PC, "_and_length", min)
    with pytest.raises(AssertionError):
        _and_reading(AgentC(_tree_and_one_edge_dangling(tmp_path / "flip-and")).proof_chain("0001"))
