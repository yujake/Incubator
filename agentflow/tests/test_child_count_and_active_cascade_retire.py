# -*- coding: utf-8 -*-
"""两个读数（子代理数 / 活跃子代理数）＋ 销号的级联规则（业主 2026-10-26 裁定）。

## 业主原话（唯一权威，逐字）

```
「未销号的子代理数叫子代理数，工作未做完还在做的子代理数叫活跃子代理数，销号时需保证被销号子代理
  无活跃子代理，且自动帮它的子代理销号（从最深的开始销号）。若一子代理自身不活跃，但有活跃的子代理
  甚至孙代理，它还是叫活跃的，但这是病态形状（应该是这个孙辈或重孙辈的父代理在等它，爷爷辈在等父，
  有"等"这个动作还是算活跃的）」
```

## 这一份钉住的六件事

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_two_counts_are_named_and_counted_separately` | 一个父带 3 个未销号子、其中 2 个有未收口任务 ⇒ `子代理数=3`、`活跃子代理数=2`，且两个数在名册面/读数面各自出现 | 改前只有一个数：`roster_view` 逐行给 `state`，没有任何"这一个父名下有几人 / 其中几个在干"的读数，`child_count` / `active_child_count` 这两格根本不存在（读到的是 KeyError） |
| b) `test_active_is_inherited_upward` | 链 A→B→C、C 在跑、B 空闲、A 空闲 ⇒ A、B 都算活跃，且两者都被标成"靠等下级才活跃"（病态形状） | 改前 `active_children` 只看自己那一行的 `status`：B 已收口就报"在等待"、A 已收口也报"在等待" —— "等"这件事在读数上一个字都没有 |
| c) `test_refuses_when_the_subtree_still_has_an_active_node` | 销 A 而 A 的子树里有活跃节点 ⇒ 受控拒绝，点名那个节点与它的任务号，且一处都不销（负控） | 改前销号只看 A 自己那一行的 `status` 与直接子是 `waiting_no_children` ⇒ 孙代 C 在跑也会照销 A，销完之后 C 就成了名册外的孤儿 |
| d) `test_cascade_retires_the_whole_subtree_deepest_first` | 销 A 而 A 的子树全都不活跃 ⇒ 级联销号整棵子树，次序从最深到最浅（事件序断言） | 改前一次调用只销一个名字：B、C 留在名册上，而它们的父已经退场（再也叫不醒、也没人再给它们销号） |
| e) `test_stubbing_the_inheritance_makes_b_red` / `test_stubbing_the_cascade_makes_d_red` | 反真空：把"活跃继承"打桩成只看自身 ⇒ b 必红；把"级联"打桩成只销自己 ⇒ d 必红 | 不适用（它们守的是 a–d 不是真空的那些条） |
| f) `test_stubbing_the_cascade_to_shallow_first_makes_d_order_red` | 反真空：把"级联"打桩成从最浅到最深 ⇒ d 的次序断言必红 | 同上 |

b / c / d 的判据本体各自只写一份（`_b_problems` / `_c_problems` / `_d_problems`），
反真空那两条调同一份判据：打桩之后它必须报出问题 —— 否则"打桩 ⇒ 必红"证明的是打桩坏了，
而不是判据真的在看那件事。

## 三态纪律在这一份里的落点

`child_count` / `active_child_count` 读不成时是 `None`，不是 `0`（`0` 是"名册空了"这个
很强的结论）；销号的三档是 `retired` / `refused` / `unknown`，"销一半"不在这三档里 ——
它是 `unknown` 加一份"已经销掉的是哪几个"的点名。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import readouts as RO
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.secretary import Secretary, retired_path
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT
from agentflow.tools.base import ToolRegistry

#: 父代理唯一的销号入口。
TOOL = "conductor.retire_child"

TS = "2026-01-01T00:00:00+00:00"


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path) -> dict[str, object]:
    """一个工作区 + 一个主控 + 父那一趟的秘书（`roster_sink` 接上，与生产同一条取法）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    # 生产里由 `AgentLoop._bind_roster_sink` 接上；这里显式接，是为了让"销号"与
    # "登记名册"落「同一份」名册文件（否则两条链各读一份名册，判据测的就不是生产形态）。
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "夹具：父这一趟"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, parent: str, *, role: str = "D",
           status: str = "done") -> str:
    """造一个子代理的台账行（`kind` 空 = 代理行）。"""
    row = {
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"fixture:{role}:{status}",
        "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": "夹具子代理",
        "error": None, "started_at": TS,
        "ended_at": (TS if status in ("done", "cancelled") else None),
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }
    return cond._write_new_row(row, note="fixture:child")


def _register(env: dict[str, object], owner: str, task_id: str, *,
              role: str = "D", brief: str = "写研究报告") -> str:
    """把它登记进 `owner` 那份名册（销号的正路指称是名册名，所以这一步是前提）。"""
    got = env["sec"].roster_add(owner=str(owner), role=role, task_id=task_id, brief=brief)
    assert got.get("problem") == "", got
    return str(got["name"])


def _call(env: dict[str, object], **kwargs: object):
    """以"父这一趟"的身份调一次销号（`calling_as` 挂上台账号，生产里由 `_do_tool` 挂）。

    参数走 `args` 映射而不是逐个关键字：`ToolRegistry.call` 的第一个形参本身就叫
    `name`（工具名），而工具的一格指称也叫名册名 —— 逐个传会撞成
    `call() got multiple values for argument 'name'`。工具层因此把正路那一格叫
    `child_name`（`name` 只作兼容别名收），这条判据走的就是正路。
    """
    reg = ToolRegistry(name="cascade-retire")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    with calling_as(str(env["owner"]), "M"):
        return reg.call(TOOL, dict(kwargs), role="M")


def _retired_rows(root: object, owner: str) -> list[dict]:
    path = retired_path(str(root), str(owner))
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _finish(env: dict[str, object], task_id: str) -> None:
    """把一行为从 `running` 收成 `done`（schema 要求 done 必须带 outcome 与 ended_at）。

    为什么不直接改 `status`：`schema.Task.validate` 会把"done 却没有 outcome"判成坏行
    （"跑完了"与"跑完了有没有结果"是两件事）。夹具必须走真的那一套字段。
    """
    for row in env["store"].rows("tasks"):
        if str(row.get("task_id") or "") != str(task_id):
            continue
        row["status"] = "done"
        row["outcome"] = "ok"
        row["ended_at"] = TS
        with env["store"].tx("tasks", actor="M", note="fixture:done") as tx:
            tx.upsert("tasks", row, note="fixture:done")
        return
    raise AssertionError(f"台账里没有 {task_id}")


def _chain_env(tmp_path: pathlib.Path) -> dict[str, object]:
    """链 A→B→C，C 在跑、B 空闲、A 空闲；三个都登记在各自父的名册里。

    深度：A 是父的直接子（相对深度 0），B 是 A 的子（1），C 是 B 的子（2）。
    "从最深的开始销号"在这一支上给出的唯一次序就是 C、B、A。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    a = _child(env["cond"], owner, role="D", status="done")
    b = _child(env["cond"], a, role="F", status="done")
    c = _child(env["cond"], b, role="B", status="running")
    env["chain"] = {"a": a, "b": b, "c": c,
                    "name_a": _register(env, owner, a, role="D", brief="梳理证明链"),
                    "name_b": _register(env, a, b, role="F", brief="攻坚"),
                    "name_c": _register(env, b, c, role="B", brief="建文献库")}
    return env


# ====================================================================== a) 两个读数
def test_a_two_counts_are_named_and_counted_separately(tmp_path: pathlib.Path) -> None:
    """a) 一个父带 3 个未销号子、其中 2 个有未收口任务 ⇒ 子代理数=3、活跃子代理数=2。

    ## 改前红在哪
    改前这套框架只有一个近邻读数：`roster_view` 逐行给 `state`（活跃 / 待命 / 已停 /
    已退役 / 未登记）。"这个父名下有几个未销号的名字""其中几个还在干活"这两件事
    没有一处读数说得出来 —— 所以 `child_count` / `active_child_count` 这两格读到的是
    KeyError，而"只有一个数"的形态正是业主点名要拆开的那一个。

    ## 两个数必须分得开
    这条判据把"3"与"2"同时钉住，并额外断言两者不相等 —— 如果哪天两个数被折成同一个
    来源（例如 `active_child_count` 直接抄 `child_count`），夹具里那两个 running 的子
    就再也体现不出来，而这条判据会红。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    for i, status in enumerate(("running", "running", "done")):
        tid = _child(env["cond"], owner, role="D", status=status)
        _register(env, owner, tid, role="D", brief=f"第 {i} 件活")

    counts = env["sec"].child_counts(owner=owner)
    assert counts["checked"] is True, counts
    assert counts["child_count"] == 3, counts
    assert counts["active_child_count"] == 2, counts
    assert counts["complete"] is True, counts
    # 名字：机器键与中文名同源，两个数各自有名，不许共用一个
    assert counts["labels"] == {"child_count": "子代理数",
                                "active_child_count": "活跃子代理数"}, counts["labels"]
    assert counts["child_count"] != counts["active_child_count"], (
        "两个数相等 ⇒ 这条判据证明不了『分得开』：夹具里明明 2 个在跑")
    assert "子代理数=3" in counts["note"] and "活跃子代理数=2" in counts["note"], counts["note"]

    # 名册面（父与子看的那一份视图）上两个数各自出现
    view = env["sec"].roster_view(owner=owner)
    assert view["checked"] is True, view
    assert view["child_count"] == 3, view
    assert view["active_child_count"] == 2, view
    assert view["counts"]["child_count"] == 3, view["counts"]

    # 读数面（`readouts.READOUTS["roster"]`，`agentflow status-report` 与将来的网页从这里取）
    face = RO.READOUTS["roster"](env["root"])
    assert face["checked"] is True, face
    assert face["data"]["child_count"] == 3, face["data"]
    assert face["data"]["active_child_count"] == 2, face["data"]
    assert face["data"]["labels"]["child_count"] == "子代理数", face["data"]
    assert face["data"]["labels"]["active_child_count"] == "活跃子代理数", face["data"]
    # 两个数在同一份读数里各自占一格（不是拼在一个字符串里）
    assert "child_count" in face["data"] and "active_child_count" in face["data"], face["data"]

    # 负控：把 3 个都收口之后活跃数必须归 0（否则那 2 是编出来的）
    for tid in [str(r.get("task_id") or "") for r in
                env["store"].rows("tasks")
                if str(r.get("parent_task_id") or "") == owner]:
        _finish(env, tid)
    again = env["sec"].child_counts(owner=owner)
    assert again["child_count"] == 3, again
    assert again["active_child_count"] == 0, again


# ====================================================================== b) 活跃向上继承
def _b_problems(env: dict[str, object]) -> list[str]:
    """(b) 的判据本体：链 A→B→C，C 在跑、B 与 A 都空闲 ⇒ A、B 都算活跃且都是"靠等"。"""
    chain = dict(env["chain"])          # type: ignore[arg-type]
    a, b, c = str(chain["a"]), str(chain["b"]), str(chain["c"])
    problems: list[str] = []
    cond = env["cond"]
    for tid, label in ((a, "A"), (b, "B")):
        got = cond.active_reading(tid)
        if not got.get("checked"):
            problems.append(f"{label}（{tid}）的活跃读数没读成：{got.get('reason')}")
            continue
        if not got.get("active"):
            problems.append(f"{label}（{tid}）自己没在跑、但下级在跑 ⇒ 按业主口径它算活跃")
        if not got.get("waiting_only"):
            problems.append(f"{label}（{tid}）该被标成『靠等下级才活跃』（病态形状）")
        note = str(got.get("note") or "")
        if "等" not in note:
            problems.append(f"{label}（{tid}）的读数缺那句人话：note={note!r}")
    top = env["sec"].child_counts(owner=str(env["owner"]))
    if top.get("child_count") != 1:
        problems.append(f"父名下只有 A 一个名册项，实际 child_count={top.get('child_count')}")
    if top.get("active_child_count") != 1:
        problems.append("A 自己在等，所以父的活跃子代理数该是 1，"
                        f"实际 {top.get('active_child_count')}")
    names = [str(w.get("name") or "") for w in (top.get("waiting_only") or [])]
    if str(chain["name_a"]) not in names:
        problems.append(f"父的读数里没标出靠等的 A（{chain['name_a']}）：{names}")
    mid = env["sec"].child_counts(owner=a)
    mid_names = [str(w.get("name") or "") for w in (mid.get("waiting_only") or [])]
    if str(chain["name_b"]) not in mid_names:
        problems.append(f"A 的读数里没标出靠等的 B（{chain['name_b']}）：{mid_names}")
    notes = [str(w.get("note") or "") for w in (mid.get("waiting_only") or [])]
    if not any("等" in n and str(chain["name_c"]) in n for n in notes):
        problems.append(f"靠等的那一句没点出它在等谁（期望含 {chain['name_c']}）：{notes}")
    # 反负控：C 自己是"在跑"，不是"靠等"
    leaf = cond.active_reading(c)
    if not leaf.get("self_busy"):
        problems.append("C 自己在跑 ⇒ self_busy 该为真")
    if leaf.get("waiting_only"):
        problems.append("C 自己在跑 ⇒ 不该被标成『靠等』")
    return problems


def test_active_is_inherited_upward(tmp_path: pathlib.Path) -> None:
    """b) 链 A→B→C，C 在跑、B 空闲、A 空闲 ⇒ A、B 都算活跃，且都标成"靠等"。

    业主逐字：「若一子代理自身不活跃，但有活跃的子代理甚至孙代理，它还是叫活跃的，
    但这是病态形状（应该是这个孙辈或重孙辈的父代理在等它，爷爷辈在等父，有"等"这个
    动作还是算活跃的）」。

    ## 改前红在哪
    改前唯一的活跃读数是 `active_children`（按自己那一行的 `status ∈ {pending, running}`），
    于是 B 与 A 都读成"在等待" —— 一个已经收口的节点在读数上与"干完了"完全分不开，
    而真相是它名下的活还在跑。反真空见
    `test_stubbing_the_inheritance_makes_b_red`（把继承打掉之后这条必红）。
    """
    env = _chain_env(tmp_path)
    assert _b_problems(env) == [], _b_problems(env)

    # 收口之后同一份判据必须安静（别把"在等"做成"永远活跃"）
    c = str(dict(env["chain"])["c"])          # type: ignore[arg-type]
    _finish(env, c)
    got = env["cond"].active_reading(str(dict(env["chain"])["a"]))  # type: ignore[arg-type]
    assert got["checked"] is True, got
    assert got["active"] is False, got
    assert got["waiting_only"] is False, got


# ====================================================================== c) 受控拒绝
def _c_problems(env: dict[str, object]) -> list[str]:
    """(c) 的判据本体：销 A 而 A 的子树里有活跃节点 ⇒ 受控拒绝并点名，且一处都不销。"""
    chain = dict(env["chain"])          # type: ignore[arg-type]
    a, c = str(chain["a"]), str(chain["c"])
    res = _call(env, child_name=str(chain["name_a"]))
    problems: list[str] = []
    if not res.ok:
        return [f"销号工具自己失败了：{res.error}"]
    data = dict(res.data or {})
    if data.get("state") != "refused":
        problems.append(f"子树里有活跃节点 ⇒ 该受控拒绝，实际 state={data.get('state')}")
    if data.get("retired") is not False:
        problems.append(f"被拒绝时 retired 该是 False，实际 {data.get('retired')}")
    if data.get("branch") != "waiting_with_children":
        problems.append(f"该报『名下还有活跃子代理』这一档，实际 branch={data.get('branch')}")
    nodes = [str(n.get("task_id") or "") for n in (data.get("active_nodes") or [])]
    for tid, label in ((c, "C"), (a, "A")):
        if tid not in nodes:
            problems.append(f"没点名还在活跃的 {label}（{tid}）：{nodes}")
    if list(data.get("busy_task_ids") or []) != [c]:
        problems.append(f"『卡在哪件任务上』该只点 C（{c}），"
                        f"实际 {data.get('busy_task_ids')}")
    reason = str(data.get("reason") or "")
    if c not in reason:
        problems.append(f"拒绝理由里没有 C 的任务号（{c}）：{reason}")
    if "还在活跃" not in reason:
        problems.append(f"拒绝理由没说清「还在活跃」这件事：{reason}")
    missing = "；".join(str(x) for x in (data.get("missing") or []))
    if c not in missing:
        problems.append(f"missing 里没点名 C（{c}）：{missing}")
    if int(data.get("retired_count") or 0) != 0:
        problems.append(f"被拒绝时一项都不许销，实际 retired_count={data.get('retired_count')}")
    if data.get("cascade"):
        problems.append(f"被拒绝时 cascade 该是空的，实际 {data.get('cascade')}")
    # 盘上：三份销号名单都必须还是空的（整笔不动）
    for owner in (str(env["owner"]), a, str(chain["b"])):
        rows = _retired_rows(env["root"], owner)
        if rows:
            problems.append(f"{owner} 的销号名单不该有行：{rows}")
    return problems


def test_refuses_when_the_subtree_still_has_an_active_node(tmp_path: pathlib.Path) -> None:
    """c) 销 A 而 A 的子树里有活跃节点（C 在跑）⇒ 受控拒绝并点名 C 与它的任务号。

    ## 改前红在哪
    改前销号只看"目标自己那一行 + 直接子的状态"：A 自己已收口、直接子 B 也已收口 ⇒
    `retire_ready` 说 `waiting_no_children`（可以销）⇒ A 被销掉，而孙代 C 还在跑。
    销完之后 C 既不在任何人的名册里、也没有人再能给它销号（D-59 的原始症状换了一层皮）。

    ## 负控的负控
    C 收口之后同一笔必须真的销得掉 —— 见 (d)：否则这条只证明"它一律拒绝"。
    """
    env = _chain_env(tmp_path)
    assert _c_problems(env) == [], _c_problems(env)
    # 负控的负控：C 交差之后同一笔能销（同一份夹具，不换判据）
    c = str(dict(env["chain"])["c"])
    _finish(env, c)
    res = _call(env, child_name=str(dict(env["chain"])["name_a"]))
    assert res.ok, res.error
    assert res.data["state"] == "retired", res.data


# ====================================================================== d) 级联销号
def _spy_retire(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """记下 `Secretary.retire` 被调的次序（销号事件序：谁先被销、谁后被销）。"""
    real = Secretary.retire
    calls: list[tuple[str, str]] = []

    def spy(self, *, owner: str, name: str, by_task_id: str = "", reason: str = ""):
        calls.append((str(owner), str(name)))
        return real(self, owner=owner, name=name, by_task_id=by_task_id, reason=reason)

    monkeypatch.setattr(Secretary, "retire", spy)
    return calls


def _d_problems(env: dict[str, object], calls: list[tuple[str, str]]) -> list[str]:
    """(d) 的判据本体：子树全都不活跃 ⇒ 级联销号整棵子树，且次序从最深到最浅。"""
    chain = dict(env["chain"])          # type: ignore[arg-type]
    a, b, c = str(chain["a"]), str(chain["b"]), str(chain["c"])
    expected = [c, b, a]                # 从最深到最浅（先叶子后父）
    res = _call(env, child_name=str(chain["name_a"]))
    problems: list[str] = []
    if not res.ok:
        return [f"销号工具自己失败了：{res.error}"]
    data = dict(res.data or {})
    if data.get("state") != "retired":
        return [f"子树全都停了 ⇒ 该销成，实际 state={data.get('state')}：{data.get('reason')}"]
    if data.get("retired") is not True:
        problems.append(f"retired 该是 True，实际 {data.get('retired')}")
    order = [str(x) for x in (data.get("order") or [])]
    if order != expected:
        problems.append(f"销号次序不是从最深到最浅：{order}（期望 {expected}）")
    cascade = [str(x.get("task_id") or "") for x in (data.get("cascade") or [])]
    if cascade != expected:
        problems.append(f"cascade 的次序与 order 不一致：{cascade}（期望 {expected}）")
    if int(data.get("retired_count") or 0) != 3:
        problems.append(f"该销掉 3 项，实际 retired_count={data.get('retired_count')}")
    if int(data.get("subtree_size") or 0) != 3:
        problems.append(f"subtree_size 该是 3，实际 {data.get('subtree_size')}")
    # 事件序：秘书真正被调的次序（不是工具自己报的那一份）。
    # 次序必须是"最深的先走"：C 在 B 的名册里、B 在 A 的名册里、A 在父的名册里，
    # 所以事件序是 (B 的父=B, B1) → (A, F1) → (父, D1)。
    if calls != [(b, str(chain["name_c"])),
                 (a, str(chain["name_b"])),
                 (str(env["owner"]), str(chain["name_a"]))]:
        problems.append(f"秘书的销号事件序不对：{calls}")
    # 三份销号名单各有一行（级联是"各自的父给自己的孩子销号"，不是全塞进父那一份）
    for owner, want in ((str(env["owner"]), str(chain["name_a"])),
                        (a, str(chain["name_b"])), (b, str(chain["name_c"]))):
        got = [str(r.get("name") or "") for r in _retired_rows(env["root"], owner)]
        if got != [want]:
            problems.append(f"{owner} 的销号名单该只有 {want}，实际 {got}")
    # 销完之后父那份名册的两个读数：子代理数 0 —— A 已退场
    after = dict((data.get("readings") or {}).get("child_counts_after") or {})
    if after.get("child_count") != 0:
        problems.append(f"销完之后父名下该 0 项，实际 {after.get('child_count')}")
    # 幂等：同一笔再来一次 ⇒ 受控拒绝（不重复销），且次序表不再增长
    again = _call(env, child_name=str(chain["name_a"]))
    if again.data.get("state") != "refused":
        problems.append(f"第二次销同一支该受控拒绝，实际 {again.data.get('state')}")
    if len(calls) != 3:
        problems.append(f"重复销号又写了事件（总调用 {len(calls)} 次，期望 3 次）")
    return problems


def test_cascade_retires_the_whole_subtree_deepest_first(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 销 A 而 A 的子树全都不活跃 ⇒ 级联销号整棵子树，且次序从最深到最浅。

    业主逐字：「销号时需保证被销号子代理无活跃子代理，且自动帮它的子代理销号
    （从最深的开始销号）」。

    ## 改前红在哪
    改前一次调用只销一个名字（`retired_count` 这一格不存在，`order` / `cascade` 也不存在）：
    A 退场而 B、C 留在名册上 —— 它们的父已经走了，于是再也没有人给它们销号。
    次序也不是小事：从最浅往最浅销的话，父先退场，子就成了"没有父可寻址"的行
    （反真空见 `test_stubbing_the_cascade_to_shallow_first_makes_d_order_red`）。
    """
    env = _chain_env(tmp_path)
    _finish(env, str(dict(env["chain"])["c"]))     # C 交差 ⇒ 整支都不活跃
    # 判据只跑一遍：`_d_problems` 会真的销号，跑两遍第二遍就只剩"已经销过号"了。
    problems = _d_problems(env, _spy_retire(monkeypatch))
    assert problems == [], problems


# ====================================================================== e/f) 反真空
def _stub_inheritance_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """把"活跃继承"打桩成只看自身（`active = self_busy`）。

    这是业主那条规则的反面：一个自己不忙、下级在忙的节点会被读成"不活跃"。
    打桩之后 (b) 必须红 —— 否则 (b) 证明不了它在看"继承"这件事。
    """
    real = Conductor.activity_snapshot

    def stub(self) -> dict:
        got = real(self)
        if not got.get("checked"):
            return got
        by_task: dict[str, dict] = {}
        for tid, cell in (got.get("by_task") or {}).items():
            busy = bool(cell.get("self_busy"))
            by_task[tid] = dict(cell, active=busy, waiting_only=False,
                                waiting_for=[], busy_roots=[tid] if busy else [])
        return dict(got, by_task=by_task, waiting_only=[])

    monkeypatch.setattr(Conductor, "activity_snapshot", stub)


def _stub_cascade(monkeypatch: pytest.MonkeyPatch, *, mode: str) -> None:
    """把"级联"打桩成别的样子：`mode="only_root"` 只销自己；`mode="shallow_first"` 反序。"""
    real = Conductor.subtree_postorder

    def stub(self, root_task_id: str) -> dict:
        got = real(self, root_task_id)
        if not got.get("checked"):
            return got
        order = list(got.get("order") or [])
        order = order[-1:] if mode == "only_root" else list(reversed(order))
        inside = set(order)
        return dict(got, order=order,
                    depth_of={k: v for k, v in (got.get("depth_of") or {}).items()
                              if k in inside},
                    parent_of={k: v for k, v in (got.get("parent_of") or {}).items()
                               if k in inside},
                    rows=[r for r in (got.get("rows") or [])
                          if str(r.get("task_id") or "") in inside])

    monkeypatch.setattr(Conductor, "subtree_postorder", stub)


def test_stubbing_the_inheritance_makes_b_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e1) 反真空：把"活跃继承"打桩成只看自身 ⇒ (b) 必红。

    这条守的是"b 真的在看继承"：打桩之后 A、B 都读成不活跃，(b) 的每一条断言
    （active / waiting_only / 靠等那一句 / 活跃子代理数）都必须报出问题。
    """
    env = _chain_env(tmp_path)
    assert _b_problems(env) == [], "夹具前提：没打桩之前 b 是绿的"
    _stub_inheritance_off(monkeypatch)
    problems = _b_problems(env)
    assert problems, "把活跃继承打掉之后 (b) 仍然绿 ⇒ 这条判据是橡皮图章"


def test_stubbing_the_cascade_makes_d_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e2) 反真空：把"级联"打桩成只销自己 ⇒ (d) 必红。

    这条守的是"d 真的在看整棵子树"：只销 A 的话，`order` / `cascade` / `retired_count`
    与三份销号名单都会对不上。
    """
    env = _chain_env(tmp_path)
    c = str(dict(env["chain"])["c"])
    _finish(env, c)
    calls = _spy_retire(monkeypatch)
    _stub_cascade(monkeypatch, mode="only_root")
    problems = _d_problems(env, calls)
    assert problems, "只销自己之后 (d) 仍然绿 ⇒ 这条判据证明不了级联"


def test_stubbing_the_cascade_to_shallow_first_makes_d_order_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f) 反真空：把"级联"打桩成从最浅到最深 ⇒ (d) 的次序断言必红。

    为什么单独一条："销了整棵子树"与"按正确次序销了整棵子树"是两件事。只钉住
    "三项都销掉了"的话，从父到子地销（父先退场、子成为孤儿行）照样绿 ——
    而那正是业主那句"从最深的开始销号"要防的形态。
    """
    env = _chain_env(tmp_path)
    c = str(dict(env["chain"])["c"])
    _finish(env, c)
    calls = _spy_retire(monkeypatch)
    _stub_cascade(monkeypatch, mode="shallow_first")
    problems = _d_problems(env, calls)
    assert problems, "从最浅到最深之后 (d) 的次序断言仍然绿 ⇒ 次序这件事没人看着"
    assert any("次序" in p for p in problems), problems
