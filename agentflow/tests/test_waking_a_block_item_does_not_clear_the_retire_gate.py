# -*- coding: utf-8 -*-
"""接线小模拟（E 的后半）：唤醒解除的是"叫不醒"，不是"挡住销号"。

## 这一条要钉的事实

`draft/126` §五 与 `draft/119` §三 都把这条写在明面上，但此前没有一条判据把"唤醒之后
销号闸仍然挡着"这件事跑出来。它很容易被读反：既然 `wake_blocked` 把 block 项翻回了
`queued`，那"板项不是没了吗"。不是 —— 销号闸的判据是 `item_state != "done"`，
`queued` 与 `block` 一样都算"没清"。

模拟的形状（全部走真实入口，零模型）：

```text
① 一条 block 板项 ＋ 一支要销号的子代理（名册里已登记）
② 先销号一次            => 被板项闸挡（missing 点名 block 那一条）
③ 收件人自己 ack 一次    => 被状态机挡（block → done 是倒退，state_error）
   父替它 ack 一次        => 被收件人闸挡（not_yours）
④ wake_blocked 批准唤醒  => 真写：block → queued、owner 被叫起来
⑤ 同一支再销号一次        => 仍然被挡（missing 点名 queued 那一条）
⑥ 收件人把它 ack 掉      => 这一条才不再"未消"
⑦ 第三次销号             => 这次通过（state=retired）
```

⑦ 是反真空：若销号闸"永远拒"，⑤ 与 ⑦ 就分不开了 —— 那这条判据只是在测"拒得很稳定"。
"""

from __future__ import annotations

import pathlib
from typing import Any

from agentflow import stopctl as SC
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import ToolRegistry
from agentflow.tools import conductor_tools as CT

TS = "2026-01-01T00:00:00+00:00"


# ====================================================================== 夹具
def _ws(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个工作区 ＋ 一个主控 ＋ 父那一趟的秘书（`roster_sink` 接上，与生产同一条取法）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    cond.roster_sink = sec
    calls: list[str] = []

    def _runner(tid: str, **_kw: Any) -> dict[str, Any]:
        calls.append(str(tid))
        return {"started": True, "task_id": str(tid), "reason": "夹具：叫起来了"}

    cond.resume_runner = _runner
    owner = str(cond.open_top_level_run("M", "夹具：唤醒不清板项"))
    return {"root": root, "store": store, "cond": cond, "sec": sec,
            "owner": owner, "calls": calls}


def _child(env: dict[str, Any], *, role: str = "D") -> str:
    """一支要销号的子代理（`running` —— 好让真实生产者把它翻成 block）。"""
    row = {"role": role, "action": "write_report", "called_by": "M",
           "parent_task_id": str(env["owner"]), "depth": 2,
           "input_key": f"gate:{role}", "status": "running", "outcome": None,
           "refusal_reason": None, "instance": "", "detail": "夹具子代理",
           "error": None, "started_at": TS, "ended_at": None,
           "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": []}
    return str(env["cond"]._write_new_row(row, note="fixture:gate"))


def _blocked_item(env: dict[str, Any], owner: str) -> str:
    """真开一条板项（queued），再由真实生产者翻成 block（不是手搓两根轴）。"""
    return str(env["cond"].open_item(kind="delegation", role="D", expects="work",
                                     action="write_report", summary="夹具：被停的活",
                                     parent_task_id=owner, depth=3,
                                     input_key=f"item:{owner}:gate"))


def _registry(env: dict[str, Any]) -> ToolRegistry:
    reg = ToolRegistry(name="wake-vs-retire")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    return reg


def _retire(env: dict[str, Any], reg: ToolRegistry, name: str) -> Any:
    with calling_as(str(env["owner"]), "M"):
        return reg.call("conductor.retire_child", role="M", child_name=name)


def _ack(env: dict[str, Any], reg: ToolRegistry, item: str, who: str,
         role: str = "D", close: str = "completed") -> Any:
    """以某个人的身份 ack 一条项（`close` 与那一行的 `expects` 必须配对）。

    夹具里那条是 `expects="work"`（要交付的活）⇒ 收口方式必须是 `completed`；
    用 `acked` 会被受控拒绝（`bad_close`："要交付的活不许靠'知道了'收掉"）——
    这条配对本身也是判据的一部分（见 ⑥）。
    """
    with calling_as(str(who), role):
        return reg.call("conductor.ack", role=role, item_ids=[item], close=close)


def _rows(env: dict[str, Any]) -> dict[str, dict]:
    return {str(r.get("task_id")): r for r in env["store"].rows("tasks")}


def _open_states(data: Any) -> list[str]:
    return [str((row or {}).get("item_state") or "")
            for row in ((data or {}).get("open_items") or ())]


# ====================================================================== 判据
def test_a_woken_item_still_blocks_the_retire_gate(tmp_path: pathlib.Path) -> None:
    """接线小模拟：block 挡销号，唤醒之后仍然挡 —— 挡销号要靠 ack 那条链。"""
    env = _ws(tmp_path)
    child = _child(env)
    item = _blocked_item(env, child)
    blocked = SC.block_remaining_tasks(env["store"], task_id=child, why="夹具：budget")
    name = str(env["sec"].roster_add(owner=str(env["owner"]), role="D",
                                     task_id=child, brief="写研究报告")["name"])
    reg = _registry(env)
    problems: list[str] = []

    if blocked.get("blocked_items") != [item]:
        problems.append(f"夹具自己没成立：生产者没把板项翻成 block（{blocked!r}）")
    if name != "D1":
        problems.append(f"夹具自己没成立：名册名该是 D1，实际 {name!r}")

    # ---- ② block 项还在时：销号被板项闸挡
    first = dict(_retire(env, reg, name).data or {})
    if first.get("state") != "refused":
        problems.append(f"block 项还在时销号该被拒，实际 {first.get('state')!r}")
    if _open_states(first) != ["block"]:
        problems.append(f"拒信该点名那一条 block 项，实际 {_open_states(first)!r}")
    if item not in str(first.get("missing") or ()):
        problems.append(f"missing 里该有 {item}：{first.get('missing')!r}")
    reason1 = str(first.get("reason") or "")
    if "wake_blocked" not in reason1:
        problems.append("板项闸的拒信要点到 wake_blocked（那是 block 那一档唯一的路），"
                        f"实际 reason={reason1!r}")
    if "block 那一档" not in reason1:
        problems.append(f"拒信要按 item_state 分档说（block 先唤醒 / 其余等 ack）：{reason1!r}")

    # ---- ③ ack 这条路两头都不通（这正是"让父去 ack"那条旧指路错在哪）
    by_self = dict(_ack(env, reg, item, child).data or {})
    if by_self.get("state") != "refused":
        problems.append(f"block 行连收件人都 ack 不掉，实际 {by_self.get('state')!r}")
    if "state_error" not in list(by_self.get("refusal_codes") or ()):
        problems.append(f"理由码该是 state_error（block → done 是倒退）："
                        f"{by_self.get('refusal_codes')!r}")
    by_parent = dict(_ack(env, reg, item, str(env["owner"]), role="M").data or {})
    if "not_yours" not in list(by_parent.get("refusal_codes") or ()):
        problems.append(f"父替子 ack 该被收件人闸挡（not_yours）："
                        f"{by_parent.get('refusal_codes')!r}")

    # ---- ④ 批准唤醒（真写）
    with calling_as(str(env["owner"]), "M"):
        woke = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
    if woke.get("state") != "woken" or int(woke.get("count") or 0) != 1:
        problems.append(f"唤醒该成：{woke.get('state')!r}/{woke.get('count')!r}")
    if str((_rows(env).get(item) or {}).get("item_state")) != "queued":
        problems.append("唤醒之后那一行该是 queued")
    if env["calls"] != [child]:
        problems.append(f"唤醒该叫的是 owner：calls={env['calls']}")
    cell = next((c for c in (woke.get("items") or ())
                 if str(c.get("item_id")) == item), {})
    why = str(cell.get("why") or "")
    if "收口" not in why or "ack" not in why:
        problems.append("唤醒成功的回执要说清「板项还在板上、收口要收件人 ack」，"
                        f"实际 {why!r}")

    # ---- ⑤ 同一支再销号：仍然被挡（唤醒不等于清了板项）
    second = dict(_retire(env, reg, name).data or {})
    if second.get("state") != "refused":
        problems.append("唤醒之后同一支销号仍然该被拒（queued 也不是 done），"
                        f"实际 {second.get('state')!r}（缺 {second.get('missing')!r}）")
    if _open_states(second) != ["queued"]:
        problems.append(f"拒信该点名那一条已翻成 queued 的项，实际 {_open_states(second)!r}")

    # ---- ⑥ 收件人把它 ack 掉（这才是"清板项"那条链）
    # 收口方式必须与那一行的 `expects` 配对（work ⇒ completed / ack ⇒ acked）：
    # 配错的形态由 `conductor.ack` 自己的判据守，这里只走正路。
    done = dict(_ack(env, reg, item, child).data or {})
    if done.get("state") != "acked":
        problems.append(f"唤醒之后收件人该 ack 得动了：{done.get('state')!r}"
                        f"（{done.get('reason')!r}）")

    # ---- ⑦ 反真空：这一条这才不再挡，销号第三次通过
    third = dict(_retire(env, reg, name).data or {})
    if third.get("state") != "retired":
        problems.append(f"板项真清干净之后销号该通过，实际 {third.get('state')!r}"
                        f"（缺 {third.get('missing')!r}）")
    assert problems == [], problems
