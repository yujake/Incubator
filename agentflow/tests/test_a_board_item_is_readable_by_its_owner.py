# -*- coding: utf-8 -*-
"""`tasks` 读侧：义务项（板项）的收件人必须读得到自己那一行。

## 改前的现场（真机 `projects/lp-ball-6`，逐字证据 `agentflow/temp/inv2/REPORT.md` §2.3）

签落地那一刻开了义务项 `t-000079`（`kind=notice`、`expects=work`、`called_by=V`、
`parent_task_id=t-000064`、`input_key=b-register@000000@d36fadcb…`），而 B 在续跑 run 里
`table.get(table="tasks", id="t-000079")` 拿到 `found=false`（`table.list("tasks")`
只回 2 行）—— 它只能改成 `fs.search("b-register")` 去翻 `events.jsonl` 的原文，才知道
自己欠的是哪一条义务。根因是 `_visible_tasks` 只把 `kind == ""` 的实例行算成"直接下级"，
板项行一律排除在可见面外（`tools/table_tools.py` 的 `and not str(r.get("kind") or "")`）。

## 判据（先红后绿）

| # | 判据 | 改前为什么红 |
|---|---|---|
| d | owner（板项的 `parent_task_id` = 我这一趟的台账号）读它 ⇒ `found=true`；`input_key` / `expects` / `called_by` / `detail`（义务正文）/ `role` / `item_state` 都在；`table.list("tasks")` 的可见面里也点得到它 | 板项行被排除在可见面外 ⇒ `found=false`、`list` 里没有它 |
| e | 非 owner 读同一行 ⇒ 仍 `found=false`（同角色、同父的兄弟读不到；父也读不到） | 改前连 owner 也读不到；这一条把"改后不许放宽"钉住（只修 owner 这一档） |
| f | 反真空：把 owner 判定打掉（`_is_board_item_for_me` 恒 False）⇒ d 的同一段断言必红 | 同 d（没有这一条，d 可能靠"夹具里恰好没有别人看得见"变绿） |

零模型调用：`Conductor(st, policy=None, backend=LocalBackend({}))` + 真
`build_registry`；工作区在 `tmp_path` 里自建，`projects/*` 一个字节都不碰。
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow import conductor as CND
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
import agentflow.tools.table_tools as MT

SID = "board-item-visible-to-owner"

#: 与真机那条义务项同形（`obligations.registration_after_unregistered_sign` 开的那一条）。
KEY = "b-register@000000@d36fadcb1adbd97026e52758d9fe0591affa5fbee0e2fd6c3fd1301c1b6d5a5b"
SUMMARY = "待收录：000000#p1（稿上已有成立的 V 签，statements 里还没入库）"
DETAIL = ("这是一条必须收录的义务，不是通知：把 reports/f-proof-000000.md 收进 statements。"
          "收口要凭证据（`b-register@` 那一族只认落地行）。")


def _child(cond: Conductor, *, role: str, parent: str, depth: int, key: str) -> str:
    """建一条子代理实例行（`kind == ""`）—— 与 `summon` 建的那种行同形。"""
    row = {"role": role, "action": "notice", "called_by": "M",
           "parent_task_id": parent, "depth": depth, "input_key": key,
           "status": "running", "outcome": None, "refusal_reason": None,
           "instance": "", "detail": f"派给 {role} 的活（{key}）", "error": None,
           "started_at": "2026-11-17T19:43:40+08:00", "ended_at": None,
           "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": []}
    return cond._write_new_row(row, note="start:test")


def _fixture(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一条 `M -> D -> B1 / B2` 的链 + 一条开在 B1 名下的义务项。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, workspace_root=ws, conductor=cond).registry
    top = cond.open_top_level_run("M", "顶层那一趟的活")
    d1 = _child(cond, role="D", parent=top, depth=2, key="d1@1")
    b1 = _child(cond, role="B", parent=d1, depth=3, key="b1@1")
    b2 = _child(cond, role="B", parent=d1, depth=3, key="b2@1")
    item = cond.open_item(kind="notice", role="B", expects="work", action="notice",
                          summary=SUMMARY, called_by="V", parent_task_id=b1,
                          depth=4, input_key=KEY)
    cond.set_item_detail(item, DETAIL)
    return {"ws": ws, "st": st, "cond": cond, "reg": reg, "top": top,
            "d1": d1, "b1": b1, "b2": b2, "item": item}


def _as(ws: pathlib.Path, task_id: str, role: str, parent_task_id: str = "",
        parent_role: str = ""):
    """以某个实例的身份跑一段（生产路径上由 `AgentLoop._do_tool` 挂，判据里显式挂）。"""
    return calling_as(str(task_id), role, parent_task_id=str(parent_task_id),
                      parent_role=parent_role, session_root=str(ws), sid=SID)


def _visible_ids(fx: dict[str, Any], *, task_id: str, role: str,
                 parent_task_id: str, parent_role: str = "") -> set[str]:
    with _as(fx["ws"], task_id, role, parent_task_id, parent_role):
        listed = fx["reg"].call("table.list", role=role, table="tasks")
    assert listed.ok, listed.to_dict()
    return {str(r["task_id"]) for r in listed.data["rows"]}


def _read(fx: dict[str, Any], *, task_id: str, role: str,
          parent_task_id: str, parent_role: str = "") -> Any:
    with _as(fx["ws"], task_id, role, parent_task_id, parent_role):
        return fx["reg"].call("table.get", role=role, table="tasks", id=fx["item"])


def _assert_owner_can_read(fx: dict[str, Any]) -> None:
    """d 的那一段断言（f 打桩之后必须在这里红）。"""
    got = _read(fx, task_id=fx["b1"], role="B", parent_task_id=fx["d1"], parent_role="D")
    assert got.ok, got.to_dict()
    assert got.meta.get("found") is True, ("owner 读不到自己的义务项：", got.to_dict())
    row = dict(got.data or {})
    for key in ("role", "input_key", "expects", "called_by", "detail", "item_state"):
        assert key in row, (f"板项行缺 {key!r}：", sorted(row))
    assert row["input_key"] == KEY, row["input_key"]
    assert row["expects"] == "work", row["expects"]
    assert row["called_by"] == "V", row["called_by"]
    assert row["role"] == "B", row["role"]
    assert str(row["item_state"]) != "done", row["item_state"]
    assert DETAIL in str(row["detail"]), ("义务正文（why）没读到：", row["detail"])
    # 可见面（`table.list`）里也点得到它 —— 只看 `get` 会漏掉"列表把板项过滤掉"这一档。
    ids = _visible_ids(fx, task_id=fx["b1"], role="B", parent_task_id=fx["d1"],
                       parent_role="D")
    assert ids == {fx["b1"], fx["d1"], fx["item"]}, (
        "owner 的可见面 = 自己 + 自己的父 + 开给我的板项：", ids)


# ============================================================ d owner 读得到自己的义务
def test_d_the_owner_can_read_its_own_work_item(tmp_path: pathlib.Path) -> None:
    """d：B1 读开在它名下的义务项 ⇒ `found=true`，四格齐，`list` 里也在。

    改前红（真机 `projects/lp-ball-6`，`temp/inv2/REPORT.md` §2.3）：`t-000079` 是
    `kind=notice` / `expects=work` 的义务项，B 用自己的台账号读它回 `found=false`。
    """
    fx = _fixture(tmp_path)
    _assert_owner_can_read(fx)


# ============================================================ e 非 owner 仍看不见
def test_e_a_non_owner_still_cannot_see_the_same_row(tmp_path: pathlib.Path) -> None:
    """e：非 owner 读同一行 ⇒ 仍 `found=false`（放宽可见面 ≠ 谁都能看见）。

    两档非 owner：
    - 同角色、同父的兄弟（B2）：行上的 `role` 与它一样是 B，但 `parent_task_id` 不是它
      —— 这一档证明"可见"靠的是 owner 那一格，不是角色那一格；
    - 父（D1）：它是 B1 的召唤者，但条子是开给 B1 的，不是开给它的。
    """
    fx = _fixture(tmp_path)
    sibling = _read(fx, task_id=fx["b2"], role="B", parent_task_id=fx["d1"],
                    parent_role="D")
    assert sibling.ok, sibling.to_dict()
    assert sibling.meta.get("found") is False, ("兄弟读到了别人的义务项：", sibling.to_dict())
    parent = _read(fx, task_id=fx["d1"], role="D", parent_task_id=fx["top"],
                   parent_role="M")
    assert parent.ok, parent.to_dict()
    assert parent.meta.get("found") is False, ("父读到了子名下那条项：", parent.to_dict())
    # 两档的可见面里也没有它（不只是 get 那一格被挡）。
    sib_ids = _visible_ids(fx, task_id=fx["b2"], role="B", parent_task_id=fx["d1"],
                           parent_role="D")
    assert fx["item"] not in sib_ids, ("兄弟的 list 里出现了别人的义务项：", sib_ids)
    assert sib_ids == {fx["b2"], fx["d1"]}, sib_ids


# ============================================================ f 反真空：打掉 owner 判定
def test_f_without_the_owner_check_the_owner_cannot_read_it(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f：把 owner 判定打掉 ⇒ d 的那一段断言必红（d 的绿真的来自那一格）。"""
    fx = _fixture(tmp_path)
    monkeypatch.setattr(MT, "_is_board_item_for_me",
                        lambda row, *, me, role: False)
    blind = _read(fx, task_id=fx["b1"], role="B", parent_task_id=fx["d1"],
                  parent_role="D")
    assert blind.ok and blind.data is None and blind.meta.get("found") is False, (
        "打掉 owner 判定之后 owner 仍然读得到 ⇒ 这条反真空是假的：", blind.to_dict())
    with pytest.raises(AssertionError):
        _assert_owner_can_read(fx)


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
