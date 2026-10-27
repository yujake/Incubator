# -*- coding: utf-8 -*-
"""「待新增文献列表」的三态判据（业主 2026-10-26 Q16：待裁 / 入库 / 拒收）。

业主原话：「A 确实读过、逐篇决定过」落成对待新增列表的每一项有待裁、入库、拒收三态。
刚收进待新增列表注册时自动标记是待裁，如果 A 没全读过（数没全更新为入库和拒收），
禁止提交待新增列表入库。

## 这一份守的六条（每条都有改前读数）

| 判据 | 守的是 | 改前红的样子 |
|---|---|---|
| a `test_a_the_real_48_rows_are_refused_by_the_submit_gate` | 真机 `projects/mp3-r3` 那 48 行喂进提交闸 ⇒ 逐委托整批被拒，拒信逐条点名 | 改前 `lit.admit_all` 一并放行（它只挑 `pending`，一条 pending 都没有 ⇒ 直接 ok） |
| b `test_b_a_fully_judged_delegation_submits_ok` | 正控：没有待裁 ⇒ 提交成功（收口、不再搬库） | 改前也一样 ok —— 但改后 ok 的含义窄了：只有"全判完"才 ok |
| c `test_c_staging_registers_pending_and_a_row_without_relevance_cannot_be_admitted` | 注册即待裁；没有 relevance 的槽位不许入库；判收时带 relevance 重进同一篇要补进原槽（2026-10-27 G9：改前这条钉的是"先撤掉再重进一个新槽"，而那条正路正是重复登记的来源 —— 真机 5 条 admitted 对应 5 条被取代的槽） | 改前 stage 完直接 `lit.admit` 就进去了（relevance 空着也进）；改前"补 relevance"只能靠换新槽 |
| d `test_d_over_cap_is_folded_into_rejected_and_legacy_rows_read_that_way` | 配额满折进 `rejected`+`over_cap`；盘上的旧 `cleared` 读成 `rejected`（兼容正控） | 改前写 `status="cleared"` + `cleared_at`（第四态） |
| e `test_e_negative_control_stubbing_the_pending_check_lets_the_real_rows_through` | 反真空：把"检查待裁"打桩成恒空 ⇒ a 必红 | —— |
| f `test_f_a_same_second_batch_is_recorded_as_a_reading_and_is_not_a_gate` | 信息格（不是门）：`admitted_at` 同一秒超过 N 条 ⇒ 记一条"疑似批量入库" | 改前没有任何地方留这个痕 |

## 判据定义只此一处

"判过没有"的定义在 `litstage.judged_state`（`admitted` 且 `relevance` 非空 / `rejected`
带受控理由码 / 其余都算没判）。这一份不重写它：a 与 e 打的是同一个函数，
b/c/d 打的是工具面（`lit.*` 那四件）与 `litstage` 的公开入口。

## 为什么 a 要拿真机那 48 行

真机读数是 33 admitted / 14 cleared(over_cap) / 1 rejected，`relevance` 48/48 全空，
分 4 次委托（r-000001 15 行、r-000002 15 行、r-000003 3 行、r-000004 15 行），
`admitted_at` 四个秒各 10/10/3/10 条。这一批正是"整批搬库"的产物：按"只看 pending"
的口径它一条待裁都没有 ⇒ 改前会被直接放行。盘上有那份工作区就照读，
没有就按上面的实测读数复刻同一形状（夹具不是判据，形状才是）。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

import pytest

from agentflow import litstage as L
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_for_role
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]

#: 真机工作区（只读；本项目不许改它，但判据可以照它的形状取证）。
REAL = REPO / "projects" / "mp3-r3" / "data" / "lit_candidates.json"

RID = "r-000001"
TS = "2026-10-26T21:05:15+08:00"


# ====================================================================== 夹具


def _ws(tmp_path: pathlib.Path, name: str = "ws") -> tuple[pathlib.Path, Store]:
    root = tmp_path / name
    root.mkdir()
    store = Store(root)
    store.init()
    return root, store


def _reg(store: Store):
    registry = build_for_role("A", store=store, workspace_root=store.root).registry
    registry.bound_role = "A"
    return registry


def _put(store: Store, rows: list[dict]) -> None:
    """直接把一批行写进 `lit_candidates`（真机那批行就是这么躺在盘上的）。"""
    with store.tx("lit_candidates", "counters", actor="t", note="q16 fixture") as tx:
        for raw in rows:
            row = dict(raw)
            if row.get("slot") is None:
                row["slot"] = tx.alloc_id("candidate")
            S.LitCandidate(**{k: row[k] for k in row
                              if k in S.LitCandidate.__dataclass_fields__}).validate()
            tx.upsert("lit_candidates", row, note="q16 fixture")


def _real_rows() -> list[dict]:
    """真机那 48 行：盘上有就照读，没有就按 2026-10-26 实测读数复刻同一形状。"""
    if REAL.is_file():
        payload = json.loads(REAL.read_text(encoding="utf-8"))
        rows = [dict(r) for r in (payload.get("rows") or [])]
        if rows:
            return rows
    # 形状复刻（读数逐条来自真机）：每委托 10 admitted + 余下 cleared(over_cap)，
    # r-000003 只有 3 条、r-000004 多一条 rejected。
    plan = {
        "r-000001": {"admitted": 10, "cleared": 5, "rejected": 0},
        "r-000002": {"admitted": 10, "cleared": 5, "rejected": 0},
        "r-000003": {"admitted": 3, "cleared": 0, "rejected": 0},
        "r-000004": {"admitted": 10, "cleared": 4, "rejected": 1},
    }
    rows: list[dict] = []
    n = 0
    for rid, counts in plan.items():
        for _ in range(counts["admitted"]):
            rows.append({"slot": S.format_id(n), "batch": 1, "status": "admitted",
                         "title": f"Real machine admitted {n}", "request_id": rid,
                         "relevance": "", "lit_id": S.format_id(n),
                         "admitted_at": TS, "added_at": TS})
            n += 1
        for _ in range(counts["cleared"]):
            rows.append({"slot": S.format_id(n), "batch": 1, "status": "cleared",
                         "title": f"Real machine over cap {n}", "request_id": rid,
                         "relevance": "", "reason_code": "over_cap",
                         "cleared_at": TS, "clear_reason": "本次委托的入库配额已满",
                         "added_at": TS})
            n += 1
        for _ in range(counts["rejected"]):
            rows.append({"slot": S.format_id(n), "batch": 1, "status": "rejected",
                         "title": f"Real machine rejected {n}", "request_id": rid,
                         "relevance": "", "reason_code": "overlap_without_new_content",
                         "reject_reason": "与本地库重叠且没有新内容", "added_at": TS})
            n += 1
    return rows


def _delegation(rows: list[dict], rid: str) -> list[dict]:
    return [dict(r) for r in rows if str(r.get("request_id") or "") == rid]


def _lit_rows(store: Store, n: int) -> None:
    """给 n 篇写合法的 `literature` 行（f 那一条要看文献库面的显示）。"""
    with store.tx("literature", "counters", actor="t", note="q16 fixture") as tx:
        for i in range(n):
            lit_id = tx.alloc_id("lit")
            row = S.Literature(lit_id=lit_id, title=f"Work {i}", type="J", summary="夹具",
                               path=None, processed=True,
                               dedup_key=f"title:work {i}|*", added_at=TS)
            row.validate()
            tx.upsert("literature", row.to_dict(), note="q16 fixture")


# ====================================================================== a 真机 48 行


def test_a_the_real_48_rows_are_refused_by_the_submit_gate(tmp_path: pathlib.Path) -> None:
    """a. 真机那 48 行喂进提交闸 ⇒ 四次委托逐次整批被拒，拒信逐条点名。

    改前读数：`lit.admit_all` 只挑 `status == "pending"`，而这 48 行一条 pending 都没有
    ⇒ 它走"本委托没有待审的行"那一支直接 ok —— 33 条没有任何 relevance 的入库
    就这样被当成了"判完了"。
    """
    root, store = _ws(tmp_path)
    rows = _real_rows()
    assert len(rows) == 48, f"真机那份候选台账该是 48 行，读到 {len(rows)} 行"
    _put(store, rows)
    reg = _reg(store)
    before = len(store.rows("literature"))

    refused_any = 0
    for rid in ("r-000001", "r-000002", "r-000003", "r-000004"):
        mine = _delegation(rows, rid)
        bare_admitted = [r for r in mine if str(r.get("status")) == "admitted"
                         and not str(r.get("relevance") or "").strip()]
        res = reg.call("lit.admit_all", request_id=rid)
        assert not res.ok, f"{rid}：还有 {len(bare_admitted)} 条没判，整批居然通过了"
        assert res.meta["kind"] == "undecided_items", res.meta
        message = str(res.error or "")
        assert f"还有 {len(bare_admitted)} 条没判" in message, message
        # 拒信逐条点名：每一条没判的槽位号都在里面（题名前 40 字也在）
        for row in bare_admitted:
            assert str(row["slot"]) in message, (row["slot"], message)
        assert "做法" in message, "拒信必须给做法（业主 Q16 第 ③ 条）"
        refused_any += 1
        # 被拒之后盘上一行都没多
        assert len(store.rows("literature")) == before, f"{rid} 被拒却写进了 literature"

    assert refused_any == 4
    # 折并那一条同时成立：14 条 cleared 一律读成 rejected + over_cap
    listing = L.list_candidates(store, request_id="*")
    assert listing["counts"]["cleared"] == 0 and listing["counts"]["withdrawn"] == 0, \
        listing["counts"]
    assert listing["counts"]["rejected"] == 15, listing["counts"]
    folded = [r for r in listing["rows"] if r["reason_code"] == "over_cap"]
    assert len(folded) == 14, folded
    assert all(r["status"] == "rejected" and r["reject_reason"] for r in folded), folded


# ====================================================================== b 正控


def test_b_a_fully_judged_delegation_submits_ok(tmp_path: pathlib.Path) -> None:
    """b. 正控：三态都落定（每一条 admitted 都带 relevance / 每一条 rejected 都带理由码）
    ⇒ 提交成功（`registered == 0`：该入的在逐条那一步已经入了，这一步是收口）。"""
    root, store = _ws(tmp_path)
    _put(store, [
        {"batch": 1, "status": "admitted", "title": "Judged and admitted", "request_id": RID,
         "relevance": "标题与本次检索的频谱稳定性直接相关", "lit_id": "000000",
         "admitted_at": TS, "added_at": TS},
        {"batch": 1, "status": "rejected", "title": "Judged and rejected", "request_id": RID,
         "relevance": "同一主题但只讨论有限维", "reason_code": "rejected_off_topic",
         "reject_reason": "与本次检索的方向无关", "added_at": TS},
    ])
    reg = _reg(store)
    res = reg.call("lit.admit_all", request_id=RID)
    assert res.ok, res.error
    data = res.unwrap()
    assert data["registered"] == 0, data
    assert data["report_path"], data
    text = pathlib.Path(data["report_path"]).read_text(encoding="utf-8")
    assert L.report_violations(text) == [], L.report_violations(text)
    assert "## 待裁（0 条）" in text, text


# ====================================================================== c 注册即待裁


def test_c_staging_registers_pending_and_a_row_without_relevance_cannot_be_admitted(
        tmp_path: pathlib.Path) -> None:
    """c. 注册进列表自动是待裁；没有 relevance 的槽位入不了库（改前它直接就能进）。

    改前读数：`lit.stage_add` 之后 `lit.admit(slots=[...])` 立刻入库，两条的
    `relevance` 都是空，而没有任何一处拒绝 —— 真机那 33 条就是这么来的。
    """
    root, store = _ws(tmp_path)
    reg = _reg(store)
    staged = reg.call("lit.stage_add", request_id=RID, entries=[
        {"title": "Staged one", "doi": "10.30/one", "provider": "stub", "year": 2001},
        {"title": "Staged two", "doi": "10.30/two", "provider": "stub", "year": 2002},
    ])
    assert staged.ok, staged.error
    slots = [item["slot"] for item in staged.unwrap()["staged"]]
    listing = L.list_candidates(store, request_id=RID)
    assert listing["counts"]["pending"] == 2, listing["counts"]
    assert all(r["status"] == "pending" for r in listing["rows"]), listing["rows"]

    # 没有 relevance ⇒ 逐条入库被拒，且行保持 pending（可补证据、可判拒）
    got = reg.call("lit.admit", slots=slots, request_id=RID)
    assert got.ok, got.error
    assert not got.unwrap()["admitted"], got.unwrap()
    assert [r["code"] for r in got.unwrap()["refused"]] == ["missing_relevance"] * 2, \
        got.unwrap()["refused"]
    assert len(store.rows("literature")) == 0
    assert L.list_candidates(store, request_id=RID)["counts"]["pending"] == 2

    # 整批提交同样是拒的（闸看到的是同一件事）
    whole = reg.call("lit.admit_all", request_id=RID)
    assert not whole.ok and whole.meta["kind"] == "undecided_items", whole.meta
    assert "还有 2 条没判" in str(whole.error), whole.error

    # 判拒：受控理由码 ⇒ 变成 rejected，行还在（不物理删）
    rej = reg.call("lit.stage_reject", slot=slots[0], reason_code="rejected_low_quality",
                   note="只有一行摘要")
    assert rej.ok, rej.error
    assert rej.unwrap()["status"] == "rejected", rej.unwrap()
    # 判收：带 relevance 重进同一篇 ⇒ 补进原槽，不发新号（G9 修法 ①）。
    #
    # 改前这条判据钉的是"先撤掉、再重进一个新槽"，而那条正路正是重复的来源：
    # 2026-10-27 真机 `mp3-r4` 实测 5 条 admitted 对应 5 条被取代的槽，
    # `reports/lit-r-000001.md` 因此同时写着"已入库 3 篇"与"未入库 3 篇"（同一批题名）。
    # 病灶范围（同一晚的第二个读数）：`r-000005` 的 5 条 admitted 是 A 自己 stage 时
    # 就带了 relevance ⇒ 零重复 —— 留疤的只是"先由自动链路暂存（无 relevance）、
    # A 后来判收"这个交叉点，不是每条 admitted 都留疤。
    again = reg.call("lit.stage_add", request_id=RID, entries=[
        {"title": "Staged two", "doi": "10.30/two", "provider": "stub", "year": 2002,
         "relevance": "同一主题的另一条路线（带证据重进）"}])
    assert again.ok, again.error
    assert again.unwrap()["staged"] == [], again.unwrap()
    assert [u["slot"] for u in again.unwrap()["updated"]] == [slots[1]], again.unwrap()
    assert again.unwrap()["updated"][0]["fields"] == ["relevance"], again.unwrap()
    assert len([r for r in store.rows("lit_candidates")
                if r["request_id"] == RID]) == 2, "同一篇被登记成了两个槽"
    done = reg.call("lit.admit", slots=[slots[1]], request_id=RID)
    assert done.ok, done.error
    assert len(done.unwrap()["admitted"]) == 1, done.unwrap()
    assert len(store.rows("literature")) == 1


# ====================================================================== d 折并


def test_d_over_cap_is_folded_into_rejected_and_legacy_rows_read_that_way(
        tmp_path: pathlib.Path) -> None:
    """d. 配额满那一档：新写的落 `rejected`+`over_cap`，盘上的旧 `cleared` 读成 `rejected`。

    改前读数：盘上是 `status="cleared"` + `cleared_at` + `clear_reason`（第四态），
    `list_candidates` 的 counts 里 `cleared` 会涨到 14。
    """
    root, store = _ws(tmp_path)
    # ---- 兼容正控：盘上就是旧的 cleared 行（14 条一档，与真机同一形状）
    _put(store, [{"batch": 1, "status": "cleared", "title": f"Legacy cleared {i}",
                  "request_id": RID, "reason_code": "over_cap", "cleared_at": TS,
                  "clear_reason": "本次委托的入库配额已满", "added_at": TS}
                 for i in range(14)])
    listing = L.list_candidates(store, request_id=RID)
    assert listing["counts"]["cleared"] == 0, listing["counts"]
    assert listing["counts"]["rejected"] == 14, listing["counts"]
    folded = listing["rows"]
    assert all(r["status"] == "rejected" for r in folded), folded
    assert all(r["reason_code"] == "over_cap" for r in folded), folded
    assert all(r["reject_reason"] for r in folded), folded
    # 按老名字查仍然查得到那 14 条（"查历史"这条路没被折丢）
    assert L.list_candidates(store, request_id=RID, status="cleared")["count"] == 14

    # ---- 折并（写侧）：同一条 truncate 判据落盘时写 rejected + over_cap
    root2, store2 = _ws(tmp_path, "ws2")
    reg2 = _reg(store2)
    staged = reg2.call("lit.stage_add", request_id=RID, entries=[
        {"title": f"Over cap topic {i}", "doi": f"10.31/{i}", "provider": "stub",
         "year": 2000 + i, "relevance": f"与本次检索相关（第 {i} 条）"}
        for i in range(12)])
    assert staged.ok, staged.error
    plan = L.admission_plan(store2, request_id=RID, batch=1, on_over_cap="truncate")
    assert plan["ok"] and len(plan["cleared"]) == 2, plan
    with store2.tx("lit_candidates", actor="t", note="over cap settle") as tx:
        L.apply_settlement(tx, L.decisions_from_plan(
            plan, {item["slot"]: item["slot"] for item in plan["admitted"]}))
    raw = store2.rows("lit_candidates")
    assert {str(r["status"]) for r in raw} <= {"pending", "admitted", "rejected"}, \
        sorted({str(r["status"]) for r in raw})
    assert not [r for r in raw if r["status"] in ("cleared", "withdrawn")], raw
    over = [r for r in raw if r["reason_code"] == "over_cap"]
    assert len(over) == 2 and all(r["status"] == "rejected" for r in over), over
    assert all(r["reject_reason"] for r in over), over


# ====================================================================== e 反真空


def test_e_negative_control_stubbing_the_pending_check_lets_the_real_rows_through(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e. 反真空：把"检查待裁"（`litstage.undecided`）打桩成恒空 ⇒ a 必须变红。

    不这么做的话，"48 行被拒"可能来自别的什么东西（配额、重叠、槽位），
    而判据 a 就成了一盏被别的原因点亮的灯。
    """
    root, store = _ws(tmp_path)
    rows = _real_rows()
    _put(store, rows)
    reg = _reg(store)

    ok_before = reg.call("lit.admit_all", request_id="r-000001")
    assert not ok_before.ok, "打桩之前它就该被拒"

    monkeypatch.setattr(L, "undecided", lambda scoped: [])
    after = reg.call("lit.admit_all", request_id="r-000001")
    assert after.ok, ("打桩成恒空之后仍然被拒 ⇒ 那一道闸不是长在 `litstage.undecided` 上"
                      f"（{after.error}）")


# ====================================================================== f 信息格


def test_f_a_same_second_batch_is_recorded_as_a_reading_and_is_not_a_gate(
        tmp_path: pathlib.Path) -> None:
    """f. 信息格：`admitted_at` 同一秒超过 N 条 ⇒ 文献库面记一条"疑似批量入库"。

    三件事一起判：它出现（阈值 5、真机是 10）、它不改显示（不是门）、
    以及"同一秒但每条都有 relevance"的合法批量不记。
    """
    root, store = _ws(tmp_path)
    _lit_rows(store, 6)
    _put(store, [{"batch": 1, "status": "admitted", "title": f"Work {i}", "request_id": RID,
                  "relevance": "", "lit_id": S.format_id(i), "admitted_at": TS,
                  "added_at": TS} for i in range(6)])

    view = R.library_face(root)
    codes = [p["code"] for p in view["problems"]]
    assert R.PROBLEM_BULK_ADMISSION_SUSPECTED in codes, codes
    detail = next(p["detail"] for p in view["problems"]
                  if p["code"] == R.PROBLEM_BULK_ADMISSION_SUSPECTED)
    assert "6 条" in detail and "relevance" in detail, detail
    # 不是门：显示与否一个字都没变（status=admitted 的 6 篇照旧全在）
    assert view["data"]["count"] == 6, view["data"]["count"]
    assert view["state"] == R.LIBRARY_STATE_COMPUTED

    # 反方向：同样的 6 条，每条都带 relevance ⇒ 不记（合法的一次批量入库）
    root2, store2 = _ws(tmp_path, "ws2")
    _lit_rows(store2, 6)
    _put(store2, [{"batch": 1, "status": "admitted", "title": f"Work {i}", "request_id": RID,
                   "relevance": "与本次检索相关（每条都写了证据）",
                   "lit_id": S.format_id(i), "admitted_at": TS, "added_at": TS}
                  for i in range(6)])
    view2 = R.library_face(root2)
    assert R.PROBLEM_BULK_ADMISSION_SUSPECTED not in [p["code"] for p in view2["problems"]], \
        view2["problems"]
