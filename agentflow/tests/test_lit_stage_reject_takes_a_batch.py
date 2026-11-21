# -*- coding: utf-8 -*-
"""判据：`lit.stage_reject` 一次调用可以判拒多个槽位（FIXBATCH 第 ① 条）。

## 改前的现场（`temp/reconA/REPORT.md` §1.2 ①）

lp-ball-11 收工时 `lit_candidates` 剩 60 条 pending（65 行 = 60 pending + 5
admitted），跨 6 个委托；`data/events.jsonl` 里 `lit.stage_reject` 0 条，60 条行上
`relevance` / `reason_code` / `cleared_at` 全空。

A 第三趟 final 逐字给了它的理由：

> 「全表另有 60 条待裁候选…逐槽判拒需 60 次调用，超出剩余预算（$3.23）」

算术不成立（60 × $0.0030 ≈ $0.18 = 剩余额度的 5.6%）—— 但工具面给了它一个真的
接口理由：`lit.stage_reject` 一次只收一个 `slot`（`tools/search_tools.py` 的
`_h_lit_stage_reject(ctx, slot, ...)`，写口是 `litstage.reject` 的逐行
`_terminal`）。于是「按委托分批」这件事在工具面上不存在，60 行只能 60 次调用。

这一份守的是「批量」这件事本身，四条：

| # | 判据 | 改前红的样子 |
|---|---|---|
| a | 一次带 10 个 `slots` ⇒ 10 行全部 `rejected`（且每行都带受控 `reason_code` 与 `reject_reason`） | `slots` 不是形参 ⇒ `kind="unexpected"`，0 行变 |
| b | 单槽形（`slot=…`）行为逐字不变：只改那一行，返回那七格 | 正控（改后必须仍绿） |
| c | 混合：有效槽 + 无效槽 ⇒ 有效的落、无效的受控拒并点名（`refused[]`），不许整笔失败 | 批量形不存在，混合无从谈起 |
| d | 反真空：把批量循环打桩成"只处理第一个"（其余返回一个看起来成功的回执、不落盘）⇒ a 必红 | 证明 a 量的是盘上的行，不是返回的那份 payload |

「批量」的边界与 `lit.admit` 的逐条拒收同族：每一条仍然走 `litstage.reject`
（受控理由码 + 逐行写 `reject_reason`），批量只省调用次数，不省逐条判定。
所以写口本身（`litstage._terminal`）一个字不用动 —— 判据 d 正是在钉这件事。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import litstage as L
from agentflow.store import Store
from agentflow.tools import build_for_role

RID = "r-000001"
REASON = "rejected_off_topic"
NOTE = "与本次检索无关（判据探针）"


@pytest.fixture
def store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


@pytest.fixture
def reg(store: Store):
    registry = build_for_role("A", store=store, workspace_root=store.root).registry
    registry.bound_role = "A"
    return registry


def _stage(reg, titles: list[str], *, rid: str = RID) -> list[str]:
    """暂存一批候选，返回槽位号（与 `lit.stage_list` 读得到的顺序一致）。"""
    entries = [{"title": t, "doi": f"10.9/{i}", "provider": "stub",
                "year": 2020 + i, "type_code": "J",
                "relevance": f"与本次检索相关（{t}）"}
               for i, t in enumerate(titles)]
    res = reg.call("lit.stage_add", request_id=rid, entries=entries)
    assert res.ok, res.error
    return [str(x["slot"]) for x in res.unwrap()["staged"]]


def _states(store: Store) -> dict[str, str]:
    """槽位号 → 三态（`litstage.judged_state`：pending / admitted / rejected）。"""
    return {str(r.get("slot") or ""): L.judged_state(r)
            for r in store.rows("lit_candidates")}


def _row(store: Store, slot: str) -> dict:
    for r in store.rows("lit_candidates"):
        if str(r.get("slot") or "") == str(slot):
            return dict(r)
    raise AssertionError(f"盘上没有槽位 {slot!r}")


def _landed_problems(store: Store, slots: list[str]) -> list[str]:
    """a 用的那条判据本体：这些槽位里还没落成 rejected 的（空列表 = 全部落了）。

    单独成函数是为了让反真空（d）打在同一条判据上：把循环打成「只处理第一个」之后，
    这里必须报出剩下的那几个 —— 否则 a 量的是别的东西。
    """
    states = _states(store)
    return [f"{s}={states.get(s)}" for s in slots if states.get(s) != "rejected"]


# ====================================================================== a 批量落盘


def test_a_one_call_rejects_every_slot_it_names(store: Store, reg) -> None:
    """a. 一次调用带 10 个槽位 ⇒ 10 行全部 `rejected`（改前：形参只收一个）。"""
    slots = _stage(reg, [f"批量判拒样本 {i}" for i in range(10)])
    assert len(slots) == 10, slots

    res = reg.call("lit.stage_reject", slots=slots, reason_code=REASON, note=NOTE)
    assert res.ok, f"批量判拒没跑通：kind={res.meta.get('kind')} error={res.error}"
    data = res.unwrap()
    assert data["count"] == 10, data
    assert [str(x["slot"]) for x in data["rejected"]] == slots, data["rejected"]
    assert data["refused"] == [], data["refused"]

    states = _states(store)
    assert [states[s] for s in slots] == ["rejected"] * 10, (
        "十行里只有一部分落了 rejected —— 『批量』必须逐条真的写盘："
        f"{ {s: states[s] for s in slots} }")
    assert _landed_problems(store, slots) == [], _landed_problems(store, slots)
    for slot in slots:
        row = _row(store, slot)
        assert row["reason_code"] == REASON, (slot, row["reason_code"])
        # 2026-11-21（GARBLECHK）：判拒理由按槽位生成 —— 调用方那一句保留，但
        # 每条只讲自己那份（真机 lp-ball-15 的三行曾逐字相同）。
        reason = str(row["reject_reason"]).strip()
        assert NOTE in reason, (slot, reason)
        # 逐条仍是「判过」那一档：`reason_code` 不是唯一的证据，受控码与那一句都要在。
        assert row["status"] == "rejected", (slot, row["status"])


# ====================================================================== b 单槽不变


def test_b_the_single_slot_form_still_returns_exactly_the_same_seven_cells(
        store: Store, reg) -> None:
    """b. 单槽形（`slot=`）行为不变：只改那一行，返回老的七格（正控）。"""
    slots = _stage(reg, ["单槽甲", "单槽乙"])
    res = reg.call("lit.stage_reject", slot=slots[0], reason_code=REASON, note=NOTE)
    assert res.ok, res.error
    data = res.unwrap()
    assert set(data) == {"slot", "status", "reason_code", "reason", "title",
                         "request_id", "batch"}, (
        "单槽形的返回格变了 —— 老读者（报告 / 归档 / A 的读数）读的就是这七格", data)
    assert data["slot"] == slots[0] and data["status"] == "rejected", data
    assert data["reason_code"] == REASON, data
    assert NOTE in data["reason"], data
    assert data["request_id"] == RID, data
    states = _states(store)
    assert states[slots[0]] == "rejected", states
    assert states[slots[1]] == "pending", "单槽形只该改它点名的那一行"
    # 失败支也照旧：不存在的槽位 ⇒ ok=False + kind=unknown_slot（不是批量那份 refused[]）。
    bad = reg.call("lit.stage_reject", slot="999999", reason_code=REASON, note=NOTE)
    assert not bad.ok and bad.meta.get("kind") == "unknown_slot", (
        bad.ok, bad.meta.get("kind"), bad.error)


# ====================================================================== c 混合


def test_c_a_mixed_batch_lands_the_valid_slots_and_names_the_invalid_ones(
        store: Store, reg) -> None:
    """c. 有效槽 + 无效槽 ⇒ 有效的落、无效的受控拒并点名，不许整笔失败。"""
    good = _stage(reg, ["混合甲", "混合乙"])
    bad_slot = "999998"  # 序号不复用 ⇒ 这个号盘上永远不存在（`unknown_slot`）

    res = reg.call("lit.stage_reject", slots=[good[0], bad_slot, good[1]],
                   reason_code=REASON, note=NOTE)
    assert res.ok, (
        "混合批次整体失败了 —— 一条无效槽位不该把有效的那些一起否掉："
        f"kind={res.meta.get('kind')} error={res.error}")
    data = res.unwrap()
    assert data["count"] == 2, data
    assert [str(x["slot"]) for x in data["rejected"]] == good, data["rejected"]
    refused = data["refused"]
    assert len(refused) == 1, refused
    assert str(refused[0]["slot"]) == bad_slot, refused
    assert str(refused[0]["code"]).strip(), "受控拒必须给理由码（否则只是「失败了」）"
    assert bad_slot in str(refused[0]["why"]), refused
    states = _states(store)
    assert [states[s] for s in good] == ["rejected", "rejected"], states


def test_c2_a_batch_whose_slots_are_all_invalid_is_refused_not_silently_ok(
        store: Store, reg) -> None:
    """c2. 全部无效 ⇒ 不许回 ok=True（"一条都没落"与"都落了"必须分得开）。"""
    res = reg.call("lit.stage_reject", slots=["999997", "999996"],
                   reason_code=REASON, note=NOTE)
    assert not res.ok, ("两条都是无效槽位，却回了 ok=True —— "
                        "那 A 会以为判拒已经落盘")
    assert res.meta.get("kind") == "all_refused", (res.meta.get("kind"), res.meta)


# ====================================================================== d 反真空


def test_d_stubbing_the_loop_to_handle_only_the_first_slot_turns_a_red(
        store: Store, reg, monkeypatch: pytest.MonkeyPatch) -> None:
    """d. 反真空：批量循环只处理第一个（其余回一个看起来成功的回执）⇒ a 必红。"""
    slots = _stage(reg, [f"反真空样本 {i}" for i in range(5)])
    real = L.reject
    seen: list[str] = []

    def only_first(store_, slot, reason_code, note="", *, actor="agent-A"):
        """只有第一次真的落盘；其余返回一份"看起来判过了"的回执，不写盘。"""
        seen.append(str(slot))
        if len(seen) == 1:
            return real(store_, slot, reason_code, note, actor=actor)
        return {"slot": str(slot), "status": "rejected", "reason_code": reason_code,
                "reason": str(note or ""), "title": "", "request_id": RID, "batch": 1}

    monkeypatch.setattr(L, "reject", only_first)
    res = reg.call("lit.stage_reject", slots=slots, reason_code=REASON, note=NOTE)
    assert res.ok, ("反真空的前提：打桩之后这一次调用本身仍然「成功」"
                    "（否则红的原因会变成别的）", res.error)
    assert res.unwrap()["count"] == len(slots), "桩把回执都发成了成功 ⇒ 计数应当是多少？"
    # a 的那一条判据本体（`_landed_problems`）在同一个注入之下必须红：
    problems = _landed_problems(store, slots)
    assert problems != [], (
        "打桩成『只处理第一个』之后，盘上居然十行都落了 rejected —— "
        "那说明 a 量的是回执里的计数，不是盘上的行")
    states = _states(store)
    assert [s for s in slots if states[s] == "rejected"] == [slots[0]], (
        "红的原因必须正好是『只有第一行落了盘』", problems)
