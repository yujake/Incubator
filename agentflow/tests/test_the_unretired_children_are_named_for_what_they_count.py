# -*- coding: utf-8 -*-
"""判据（先红 · 未修）：收工那格的键名要说出它数的是什么（2026-11-03，153-U-13 的另一半）。

## 背景

同一个 `child_count` 在两面指两个量（U-13 的网页那半已改叫 `children_in_ledger`）：

| 落点 | 数的是什么 | 范围 |
|---|---|---|
| `webui.readers.roster_face` 的节点格（已改名 `children_in_ledger`） | 这个节点在**台账**里挂了几个子 | 这一个节点 |
| `Secretary.child_counts()` 的 `child_count`（收工读数经 `closing.child_counts_reading` 转发） | 名册里还有几个**没销号**的项 | 全工作区 / 按 owner |

业主 2026-11-03 的裁决 4：网页那格叫 `children_in_ledger`，**收工那格叫 `children_unretired`**，
两处都加"这个名字量的是什么"的一句说明。

## 这条判据钉住什么

1. 收工读数那格的名字是 `children_unretired`（`conductor.CHILD_COUNT_KEY` 与 `child_counts()`
   的返回同一个来源），且同一份返回里**不再**出现 `child_count`（同义两键 = 又一处各说一套）；
2. 它数的是**名册里未销号的项**（不是台账子数）：造 2 个名册项 ⇒ 这一格是 2；
3. 读数里带一句"这个名字量的是什么"的说明（`labels` 或 note 里点明"名册"与"未销号"）；
4. 与网页那格并排看得懂：`children_in_ledger` 的说明里点到"台账"，`children_unretired` 的
   说明里点到"名册"。
"""
from __future__ import annotations

import pathlib

from agentflow import closing as CL
from agentflow import conductor as COND
from agentflow import secretary as SEC
from agentflow.store import Store


def _ws(tmp_path: pathlib.Path):
    root = tmp_path / "ws"
    root.mkdir()
    st = Store(root)
    st.init()
    sec = SEC.Secretary("M", root=root, store=st)
    for role, tid in (("D", "t-000002"), ("D", "t-000003")):
        got = sec.roster_add(owner="t-000001", role=role, task_id=tid, brief=f"{role} {tid}")
        assert got.get("problem") == "", got
    return root, st, sec


def test_the_key_is_named_for_what_it_counts(tmp_path: pathlib.Path) -> None:
    """① 名字 = `children_unretired`，且同一份返回里没有同义的 `child_count`（今天红）。"""
    root, _st, sec = _ws(tmp_path)
    got = sec.child_counts(owner="t-000001")
    assert str(COND.CHILD_COUNT_KEY) == "children_unretired", (
        f"`CHILD_COUNT_KEY` 还是 {COND.CHILD_COUNT_KEY!r} ⇒ 收工那格与网页那格仍在各说一套")
    assert "children_unretired" in got, sorted(got)
    assert "child_count" not in got, (
        "同一份返回里 `child_count` 与 `children_unretired` 同时存在 ⇒ 同义两键，读者不知道信哪个")
    assert int(got["children_unretired"]) == 2, got


def test_the_closing_reading_carries_the_new_name(tmp_path: pathlib.Path) -> None:
    """①（续）收工读数（`closing.child_counts_reading`）里也是这个名字。"""
    root, st, _sec = _ws(tmp_path)
    got = CL.child_counts_reading(root, store=st)
    assert "children_unretired" in got, sorted(got)
    assert "child_count" not in got, sorted(got)
    assert int(got["children_unretired"]) == 2, got


def test_the_name_says_what_it_measures() -> None:
    """③ 读数里要有一句"这个名字量的是什么"。"""
    from agentflow.conductor import CHILD_COUNT_LABELS

    assert "children_unretired" in CHILD_COUNT_LABELS, CHILD_COUNT_LABELS
    label = str(CHILD_COUNT_LABELS["children_unretired"])
    assert "名册" in label and "未销号" in label, (
        f"`CHILD_COUNT_LABELS` 里那句没说清它数的是名册里未销号的子：{label!r}")
