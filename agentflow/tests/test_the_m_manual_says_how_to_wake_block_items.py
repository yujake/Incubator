# -*- coding: utf-8 -*-
"""M 的可见手册必须写清 `conductor.wake_blocked` 怎么用（业主 2026-10-29 第二段）。

## 这份判据守的是什么

能力层（`Conductor.wake_blocked`）上一棒就已经在册了，但模型看不到它 —— 它当时只是
一个方法。第二段要做的第一件事是"让它出现在模型的面上"，而工具描述只给一句话口径：
步骤、三档、以及两条会咬人的后果写在手册里。所以这一份判据问的不是"源码里有没有
这句话"，而是"M 现读的那份手册里有没有"：

```text
可见面 = agent_skills.skills_for("M") 的正文（fs.read 读的就是它）
      + agent_skills.index_block("M")  （前置提示词里那一段索引：索引里没有 = 没人会读它）
```

三条必须出现的事实（业主 2026-10-29 断的那三条，逐字符串断言）：

1. 它是逐条审批唤醒，不是一键全醒；
2. 默认 `dry_run=True` 只看不写、`approve="yes"` 才动；
3. block 板项也会永久挡收工：它让 `retire_integrity` 的 `dirty` 非空 ⇒ `complete=False`。
   那几格读数的真名有两处（`retire_integrity` 的顶层叫 `root_open_items`，逐节点才叫
   `open_items`）—— 手册点名哪一个都算说清，见 `GATE_ANCHOR` / `GATE_CELLS`。

## 反真空（每条断言都自带方向）

- 同样的字符串在别的角色的可见手册里必须不出现 —— 否则这份判据只是在测"文件里有
  这句话"，而不是"这句话落在 M 的面子上"（`skills_for("D")` 是负控）；
- 索引那一格必须点到这份手册：正文写好了却不进索引，等于写在该被读的那份手册的隔壁；
- 手册点名的那件工具必须真的在 M 的工具面上（点名一件它拿不到的工具 = 一句做不到的指令，
  `agent_skills.validate()` 对这件事另有一条判据，这里再钉一次"是这件工具"）。

## 边界

零模型、零网络：只读 `agent_skills` 的目录与 `tools.build_registry` 的工具面。
"""

from __future__ import annotations

import pathlib
from typing import Any

from agentflow import agent_skills as A
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.tools import build_registry

#: 那条手册的 slug（索引里按它生成路径）。
SLUG = "唤醒-逐条审批而不是一键全醒"

#: 三条事实的逐字符串读数（少一条就要么模型不知道该怎么批，要么它以为唤醒就清了板项）。
FACTS: dict[str, str] = {
    "① 逐条审批（不是一键全醒）": "逐条审批唤醒",
    "② 默认只看不写": "默认 `dry_run=True` 只看不写",
    "② 批准才动": '`approve="yes"` 才动',
    "③ block 板项挡收工": "block 板项也会永久挡收工",
    "③ 脏节点那一档": "`dirty`",
    "③ 收工门的结论格": "`complete=False`",
}

#: ③ 的「挡收工的判据格」：顶层与逐节点是两个不同的真名 —— `retire_integrity`
#: 的顶层那一格叫 `root_open_items`（`conductor.py::retire_integrity` 返回 dict 的键），
#: 逐节点那一格才叫 `open_items`（`nodes[]` 每项里的键）。
#:
#: 判据同时接受两种读法：手册点名哪一个都算说清。但它必须挂在 `retire_integrity`
#: 上 —— 以及旧形状里那个编出来的格名 `retire_integrity.open_items` 不算说清：
#: 那个名字顶层不存在（顶层叫 `root_open_items`），逐节点也不叫这个全名。
GATE_ANCHOR = "`retire_integrity`"
GATE_CELLS: tuple[str, ...] = ("`root_open_items`", "`open_items`")


def _bodies(role: str) -> str:
    """某个角色可见的手册正文（自己的 + `shared`，与 `skills_for` 同口径）。"""
    return "\n\n".join(s.body for s in A.skills_for(role))


def _index(role: str) -> str:
    """前置提示词里那一段索引（正文不在里面，只有路径 + 一句话 + 何时读）。"""
    return A.index_block(role)


def _m_surface(tmp_path: pathlib.Path) -> Any:
    """M 的工具面（生产同一条装配路径）。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    return build_registry(store=st, conductor=cond).registry, cond


def _gate_problems(body: str) -> list[str]:
    """③ 的判据格说清了吗（空表 = 说清了）：挂在 `retire_integrity` 上、用了两个真名之一。

    两向都要报：只写了工具名没写格名 ⇒ 报；格名用了编出来的形状 ⇒ 也报。
    """
    problems: list[str] = []
    if GATE_ANCHOR not in body:
        problems.append(f"M 的可见手册里没有点到 {GATE_ANCHOR} —— "
                        "挡收工的是它返回的那几格读数")
    if not any(cell in body for cell in GATE_CELLS):
        problems.append(
            "M 的可见手册里没有用真格名（顶层 / 逐节点任一个都行：" + " / ".join(GATE_CELLS)
            + "）—— `retire_integrity.open_items` 那个形状顶层不存在："
            "顶层叫 `root_open_items`，逐节点那一格才叫 `open_items`")
    return problems


def test_the_three_facts_are_in_the_visible_m_manual() -> None:
    """三条事实必须逐字出现在 M 的可见手册里（缺一条就是一句没写下来的口径）。"""
    body = _bodies("M")
    missing = [f"{name}（{needle}）" for name, needle in FACTS.items()
               if needle not in body]
    missing += _gate_problems(body)
    assert missing == [], f"M 的可见手册里缺这几条：{missing}"


def test_the_index_points_at_that_manual(tmp_path: pathlib.Path) -> None:
    """索引必须点到这份手册：正文写好了却不进索引 = 模型不知道有它。

    为什么这一条与上一条分开：`index_block` 只印路径 + 一句话 + 何时读，正文不在里面
    —— 所以"正文里有"与"索引里有"是两件独立的事，任何一件缺了，手册都读不到。
    """
    index = _index("M")
    path = A.skill_path("M", SLUG)
    problems: list[str] = []
    if path not in index:
        problems.append(f"索引里没有这份手册的路径（{path}）")
    if "wake_blocked" not in index:
        problems.append("索引里那一行没有点明它讲的是 conductor.wake_blocked")
    assert problems == [], problems


def test_the_manual_names_a_tool_m_actually_has(tmp_path: pathlib.Path) -> None:
    """手册点名的那件工具必须真的在 M 的工具面上（否则是一句做不到的指令）。"""
    registry, _cond = _m_surface(tmp_path)
    names = {str(spec.name) for spec in registry.for_role("M")}
    assert "conductor.wake_blocked" in names, sorted(n for n in names if "wake" in n)
    body = _bodies("M")
    assert "conductor.wake_blocked" in body


def test_the_three_facts_do_not_leak_into_another_roles_manual() -> None:
    """负控：这三条是 M 的口径，不许靠在"文件里搜得到"上。

    D 的手册与 M 的手册是从同一份 `agent_skills.py` 印出来的：若判据实际上只读了整个
    文件（或读错了角色），这一条会立刻红 —— 它证明上一条断言读的真是 M 的面子。
    判据格那两个真名也一并算进负控：D 的手册里一个都不该有。
    """
    other = _bodies("D")
    leaked = [needle for needle in (*FACTS.values(), *GATE_CELLS) if needle in other]
    assert leaked == [], f"这些字句不该出现在 D 的可见手册里：{leaked}"
