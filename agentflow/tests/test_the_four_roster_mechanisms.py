# -*- coding: utf-8 -*-
"""名册的四个机制：实现位置 / 接在哪个运行路径上 / 实测有效（每条都配负控）。

业主点名的四个机制（设计正本 `draft/90` 与 `draft/104`，逐节对过；差异表见回报）：

| 机制 | 设计 | 实现 | 接在哪一行 |
|---|---|---|---|
| ① 父代理监控子代理 | `draft/90` §1.4「查」（名册名 + 一句简介 + 工作状态）、§1.5 两份读数 | `Secretary.roster_view`（`state`/`status`/`in_flight`/`items_open`/`last_reading`）＋ `Conductor._children_of`（退路） | `AgentLoop._children_text`（`agent_loop.py:2977`）→ 提示词那一格 `{{children}}`（`run` 里渲染一次） |
| ② M 监控整棵树 | `draft/104` §2.5 台账是唯一权威、§2.6 名册视图是快照 | `Secretary.roster_view(scope="descendants")`（每行带 `parent_task_id`/`depth`）＋ `statusreport.collect` ＋ `Conductor.stats()` 的 `by_depth` | `AgentLoop._do_roster`（`agent_loop.py:5243`）→ 工具 `roster`；`conductor.status_report` 工具（`tools/conductor_tools.py:1306`）→ `statusreport.write_status_report` |
| ③ 子代理销号 | `draft/90` §1.3 删、§1.9 三分支 | `Secretary.retire` / `retired_names` / `alive_path` / `roster_view` 的 `state` ＋ 寻址闸门 `member_retired` | `AgentLoop._do_retire`（`agent_loop.py:5219`）→ 工具 `retire`；`AgentLoop._address_of` → `member_retired`（`agent_loop.py:2213`） |
| ④ 子代理读写面切割 | `draft/90` §1.10 / §1.11（裁定 `draft/93` §T23） | `Secretary.surface_alloc` / `surface_of` / `-surfaces.jsonl` / `surface_fit` / `reach_fit` | `roster_add` → `surface_alloc`（`secretary.py:2358`）；`LlmBackend.call` → `surface_of` → `registry_factory(face)`（`agent_loop.py:6987-7002`）；硬拦 `_surface_refusal`（`agent_loop.py:5642`）；读数 `agent_tool_face.advertised`（`agent_loop.py:3661`） |

每一条的负控都问同一个问题：**把它关掉，读数或行为会不会变坏**。不会变坏的判据是假绿。
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import add_request

from agentflow import host as H
from agentflow import llmseam as LL
from agentflow import secretary as SEC
from agentflow import statusreport as SR
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s-four"
MY_ROLE = "M"


class _Gate:
    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        return type("Reply", (), {"ok": True, "text": "{}", "tool_calls": (),
                                  "tokens_in": 1, "tokens_out": 1,
                                  "error_detail": "", "error_kind": ""})()


def _row(cond: Conductor, parent: str | None, role: str, *, key: str,
         status: str = "done", action: str = "run_once", called_by: str = MY_ROLE,
         kind: str = "") -> str:
    prow = (cond._task(parent) or {}) if parent else {}
    terminal = status not in ("pending", "running")
    return cond._write_new_row({
        "task_id": "", "role": role, "action": action, "called_by": called_by,
        "parent_task_id": parent, "depth": int(prow.get("depth") or 0) + 1,
        "input_key": key, "status": status,
        "outcome": "ok" if terminal else None, "refusal_reason": None, "instance": "",
        "detail": f"一个 {role} 实例", "error": None,
        "started_at": "2026-10-19T10:00:00+08:00",
        "ended_at": "2026-10-19T10:05:00+08:00" if terminal else None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        "kind": kind,
    }, note=f"start:{role}.run_once")


def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    top = cond.open_top_level_run(MY_ROLE, "顶层这一趟")
    loop = AgentLoop(role=MY_ROLE, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=MY_ROLE, session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    loop.my_task_id = top
    cond.secretary = loop.secretary
    return {"ws": ws, "st": st, "cond": cond, "reg": reg, "loop": loop,
            "sec": loop.secretary, "me": top}


def _add_child(env: dict[str, Any], role: str = "E", *, brief: str = "一件子活") -> tuple[str, str]:
    """建一个子代理（台账行 + 名册项），返回 `(绝对编号, 名册名)`。"""
    kid = _row(env["cond"], env["me"], role, key=f"child@{role}")
    reg = env["sec"].roster_add(owner=env["me"], role=role, task_id=kid, brief=brief)
    assert reg.get("problem") == "", reg
    return kid, str(reg.get("name") or "")


# ============================================================ ① 父代理监控子代理


def _child_view_reading(view: dict[str, Any], child: str) -> dict[str, Any]:
    """判据①：父那一份视图里，这个子行的五格读数必须都在且非空/非缺。"""
    assert view.get("checked") is True, view
    row = next((r for r in view.get("rows") or [] if str(r.get("task_id")) == child), None)
    assert row is not None, ("父的名册里读不到这个子", view.get("rows"))
    for key in ("name", "role", "brief", "state", "status", "in_flight",
                "items_open", "last_reading"):
        assert key in row, (f"视图缺 {key!r} 这一格"
                            "（§1.4 要求：名册名 + 一句简介 + 工作状态）", row)
    assert str(row.get("state") or ""), row
    assert str(row.get("status") or "") in ("running", "idle", "ready", "retired"), row
    return row


def test_the_parent_reads_its_children_from_the_roster(tmp_path: pathlib.Path):
    """① 正控：父的名册视图给出五格读数，且 `{{children}}` 那一格真的渲染它。"""
    env = _env(tmp_path)
    child, name = _add_child(env, brief="把 X 的族构造证据补齐")
    # 工作项轴：挂在子名下的一条未消项 ⇒ `items_open` 必须数到它（两轴分开，§1.5）
    env["cond"].open_item(kind="message", role="E", expects="ack",
                          parent_task_id=child, called_by=MY_ROLE,
                          summary="一条还没消的项")
    row = _child_view_reading(env["sec"].roster_view(owner=env["me"]), child)
    assert str(row["name"]) == name and name.startswith("E"), row
    assert str(row["brief"]) == "把 X 的族构造证据补齐", row
    assert int(row["in_flight"]) == 0, ("子那一行已终态 ⇒ 在飞 0", row)
    assert int(row["items_open"]) == 1, ("件数轴没数到那条未消项", row)
    # 提示词那一格（`_children_text` 是 `run()` 里渲染进 `{{children}}` 的那个函数）
    text = env["loop"]._children_text()
    assert name in text and "把 X 的族构造证据补齐" in text, text
    assert str(row["state"]) in text, (text, row["state"])


def test_negctl_children_text_degrades_loudly_when_the_roster_is_unreadable(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """① 负控：关掉名册（`checked=False`）⇒ 那一格必须**如实说没读成**，不许变成"没有子代理"。

    "空串"在提示词层的含义是"名下没有子代理"（渲染成「（此刻名下没有子代理）」）——
    把"读不成"折成空串，就是让模型以为自己是光杆。这一条守的正是那个折平。
    """
    env = _env(tmp_path)
    child, name = _add_child(env)
    real = SEC.Secretary.roster_view
    monkeypatch.setattr(SEC.Secretary, "roster_view",
                        lambda self, **kw: {"checked": False, "rows": [], "more": 0,
                                            "reason": "夹具：台账读不成"})
    text = env["loop"]._children_text()
    assert text != "", "名册读不成时渲染成了空串（= 名下没有子代理）—— 三态被折平了"
    assert "没读成" in text, text
    monkeypatch.setattr(SEC.Secretary, "roster_view", real)
    assert name in env["loop"]._children_text(), "关掉再打开之后读数没回来（对照）"


# ============================================================ ② M 监控整棵树


def test_the_conductor_sees_the_whole_tree_with_parent_ids_and_depths(tmp_path: pathlib.Path):
    """② 正控：`scope="descendants"` 给全树（含孙代），每行带 `parent_task_id` 与 `depth`。

    读数（这一条本身）：`self` 只有 1 行（直接子），`descendants` 有 2 行（含孙代）。
    """
    env = _env(tmp_path)
    d_tid, d_name = _add_child(env, role="D", brief="D 那一支")
    c_tid = _row(env["cond"], d_tid, "C", key="grandchild@C")
    reg = env["sec"].roster_add(owner=d_tid, role="C", task_id=c_tid, brief="孙代那一件活")
    assert reg.get("problem") == "", reg
    self_view = env["sec"].roster_view(owner=env["me"])
    assert len(self_view["rows"]) == 1, self_view["rows"]
    tree = env["sec"].roster_view(owner=env["me"], scope="descendants", limit=50)
    assert tree.get("checked") is True, tree
    by_tid = {str(r.get("task_id")): r for r in tree["rows"]}
    assert set(by_tid) == {d_tid, c_tid}, by_tid
    assert int(by_tid[d_tid]["depth"]) == 1 and by_tid[d_tid]["parent_task_id"] == env["me"]
    assert int(by_tid[c_tid]["depth"]) == 2, ("孙代的深度读错了", by_tid[c_tid])
    assert by_tid[c_tid]["parent_task_id"] == d_tid, (
        "孙代的 `parent_task_id` 不是它父的绝对编号", by_tid[c_tid])
    # 另外两条 M 手上的整树读数：台账按深度的分布 + 状态报告里的顶趟数。
    # ⚠️ 两个 `depth` **同名不同义**（`draft/104` §4.5 登记过这件事）：
    # 台账那一格是**绝对**深度（顶趟 = 1 ⇒ D = 2 ⇒ C = 3），名册视图那一格是
    # **相对**层深（直接子 = 1 ⇒ 孙代 = 2）。两处都读、都写清口径，不许折成一个数。
    stats = env["cond"].stats()
    assert stats.get("by_depth") == {"1": 1, "2": 1, "3": 1}, stats.get("by_depth")
    rep = SR.collect(env["st"], env["ws"])
    assert rep["in_flight"]["top_level_runs"] == 1, rep["in_flight"]
    assert rep["tables"]["tasks"]["count"] == 3, rep["tables"]["tasks"]


def test_negctl_without_descendants_the_grandchild_is_invisible(tmp_path: pathlib.Path):
    """② 负控：把 `scope` 关回 `self` ⇒ 孙代从读数里消失（证明 descendants 真的在干活）。"""
    env = _env(tmp_path)
    d_tid, _d = _add_child(env, role="D")
    c_tid = _row(env["cond"], d_tid, "C", key="grandchild@C")
    env["sec"].roster_add(owner=d_tid, role="C", task_id=c_tid, brief="孙代那一件活")
    shallow = env["sec"].roster_view(owner=env["me"])
    assert c_tid not in {str(r.get("task_id")) for r in shallow["rows"]}, (
        "`self` 视图里居然有孙代 —— 说明这一格不是『只下一层』，上面那条正控就不是读数了",
        shallow["rows"])
    # 反真空：`self` 仍然要看得到直接子（关掉那一层不许连直接子也丢）
    assert d_tid in {str(r.get("task_id")) for r in shallow["rows"]}, shallow["rows"]


def test_a_grandchild_reports_its_state_not_unregistered(tmp_path: pathlib.Path,
                                                        monkeypatch: pytest.MonkeyPatch):
    """② 判据（真机读数驱动）：孙代那一行的 `state` 必须是四态之一，不许读成「未登记」。

    真机现场（`projects/tree-check`，只读取证）：`scope="descendants"` 的 7 行里，改前
    **5 行**（C1/F1 深度 2、B1/B2/E1 深度 3）读成「未登记」，只有直接子 D1 读对 ——
    因为 `branch` 只从**owner 那一层**的 `retire_ready` 取。这与 `draft/90` §1.4
    「必须看到 …**工作状态**」冲突：M 看得见孙代的名字，却看不出它在干什么。
    修法在 `secretary._roster_targets`（逐层问它父那一层的 `retire_ready`，每个父只问一次）。
    """
    env = _env(tmp_path)
    d_tid, _d = _add_child(env, role="D", brief="D 那一支")
    c_tid = _row(env["cond"], d_tid, "C", key="grandchild@state")
    env["sec"].roster_add(owner=d_tid, role="C", task_id=c_tid, brief="孙代那一件活")
    tree = env["sec"].roster_view(owner=env["me"], scope="descendants", limit=50)
    row_c = next(r for r in tree["rows"] if str(r.get("task_id")) == c_tid)
    assert str(row_c.get("state")) in ("活跃", "待命", "已停", "已退役"), (
        "孙代的状态读成了四态之外的东西（改前是「未登记」）", row_c)
    assert str(row_c.get("state")) == "已停", ("它已经收工，应当是「已停」", row_c)

    # 负控：把孙代那一层的分支读数关掉（那一层 `retire_ready` 判"没读成"）⇒ 立刻退回「未登记」，
    # 证明上面那一格读的就是逐层的分支（不是别处顺手补上的）。
    real = Conductor.retire_ready

    def _drop_child_level(self, parent_id):
        if str(parent_id) == d_tid:
            return {"checked": False, "ready": [], "reason": "夹具：这一层没读成"}
        return real(self, parent_id)

    monkeypatch.setattr(Conductor, "retire_ready", _drop_child_level)
    blind = env["sec"].roster_view(owner=env["me"], scope="descendants", limit=50)
    row_c2 = next(r for r in blind["rows"] if str(r.get("task_id")) == c_tid)
    assert str(row_c2.get("state")) == "未登记", ("关掉那一层之后状态没有退化", row_c2)
    monkeypatch.undo()
    assert str(next(r for r in env["sec"].roster_view(
        owner=env["me"], scope="descendants", limit=50)["rows"]
        if str(r.get("task_id")) == c_tid).get("state")) == "已停"


# ============================================================ ③ 子代理销号


def test_retiring_a_child_keeps_it_visible_but_refuses_to_be_addressed(tmp_path: pathlib.Path):
    """③ 正控：退役之后它**还在父的名册里**（标 retired），但**再被寻址就拒**（`member_retired`）。"""
    env = _env(tmp_path)
    child, name = _add_child(env, brief="可以退的那一件")
    # 退役前：寻址不落在 member_retired 上（对照，见下面的负控）
    before = env["loop"]._do_message({"to": name, "subject": "题", "body": "文"})
    assert str(before.get("refused") or "") != "member_retired", before
    got = env["loop"]._do_retire({"name": name})
    assert got.get("ok") is True and got.get("action") == "retired", got
    # 名册里还在（只追加退役事件，不物理删行 —— §1.3「这样"名册里少过谁"读得回来」）
    view = env["sec"].roster_view(owner=env["me"], limit=50)
    row = next((r for r in view["rows"] if str(r.get("name")) == name), None)
    assert row is not None, ("退役之后名册里读不到它了", view["rows"])
    assert str(row.get("status")) == "retired", row
    assert str(row.get("state")) in ("已退役", "退役"), row
    # 销号名单（名字永久不复用）
    retired, _bad = env["sec"].retired_names(env["me"])
    assert [str(r.get("name")) for r in retired] == [name], retired
    # 再被寻址 ⇒ 受控拒绝
    after = env["loop"]._do_message({"to": name, "subject": "题", "body": "文"})
    assert str(after.get("refused") or "") == "member_retired", (
        "退役之后还能被寻址（销号没有生效）", after)
    assert after.get("ok") is False, after


def test_negctl_before_retiring_the_same_name_is_not_refused(tmp_path: pathlib.Path):
    """③ 负控：同一句话在**退役之前**不会落在 `member_retired` 上 ⇒ 上面那条不是恒真。"""
    env = _env(tmp_path)
    _child, name = _add_child(env)
    got = env["loop"]._do_message({"to": name, "subject": "题", "body": "文"})
    assert str(got.get("refused") or "") != "member_retired", got
    assert str((got.get("addressing") or {}).get("how") or "") == "child", got


# ============================================================ ④ 子代理读写面切割


def test_every_child_gets_its_own_surface_and_the_tools_root_follows_it(
        tmp_path: pathlib.Path):
    """④ 正控：两个子代理拿到**不同的面**；按面造出来的注册表 `fs` 根就是那个面。

    真机读数那一格（`agent_tool_face.advertised`）也在这里量：它是**角色级**的数，
    两个面**应当相同** —— 面切在 `fs.*` 的根上，不在工具条数上（`draft/90` §1.10
    「`fs.*` 的 `root` 换成这个实例的面，其余判据一个字不改」）。所以"面切过"的
    证据只能是根，不可能是条数；判据两样都给，把这条口径钉在明处。
    """
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    wiring = H.wired_llm_conductor(st, loops={}, session_root=ws, sid=SID, max_steps=2)
    cond = wiring["conductor"]
    top = cond.open_top_level_run(MY_ROLE, "顶层这一趟")
    sec = SEC.Secretary(MY_ROLE, root=ws, store=st)
    kids = []
    for i in (1, 2):
        tid = _row(cond, top, "E", key=f"surface@{i}")
        reg = sec.roster_add(owner=top, role="E", task_id=tid, brief=f"第 {i} 个子的活")
        assert reg.get("problem") == "", reg
        got = sec.surface_of(owner=top, task_id=tid)
        assert got.get("checked") is True, got
        kids.append((tid, got))
    paths = [str(g["path"]) for _t, g in kids]
    assert len(set(paths)) == 2, ("两个子代理拿了同一个面（父没切开）", paths)
    assert [pathlib.Path(p).name for p in paths] == ["S01", "S02"], paths
    # 按面造注册表 ⇒ `fs.*` 的根就是那个面（执行基准 == 检查基准，E23 已收口）
    for face in paths:
        pathlib.Path(face).mkdir(parents=True, exist_ok=True)
        reg = wiring["backend"].registry_factory(face)
        res = reg.call("fs.write", role="E", path="笔记.md", content="落在面里")
        assert res.ok, (res.error, res.meta)
        assert (pathlib.Path(face) / "笔记.md").is_file(), list(pathlib.Path(face).iterdir())
    assert not (ws / "笔记.md").exists(), "相对路径落到了工作区根 ⇒ 面没有生效"
    # 工具面条数：两个面相同（角色级），所以"切过"的证据只能是上面那个根
    counts = [len(LL.build_tool_face("E", wiring["backend"].registry_factory(f)).functions)
              for f in paths]
    assert counts[0] == counts[1], ("工具条数随面变了 —— 那与 §1.10 的口径不一致", counts)


def test_negctl_an_out_of_face_path_is_refused_before_and_during_use(tmp_path: pathlib.Path):
    """④ 负控：关掉面（把路径指到面外）⇒ 预看读数与执行期硬拦都要拒。

    两处共用同一张"哪些参数是路径"的表（`surface_path_args`）：分两份写就会出现
    "预看说越界、硬拦放过去"而两边判据都绿。这里两处各咬一次。
    """
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    top = cond.open_top_level_run(MY_ROLE, "顶层这一趟")
    sec = SEC.Secretary(MY_ROLE, root=ws, store=st)
    tid = _row(cond, top, "E", key="face@neg")
    sec.roster_add(owner=top, role="E", task_id=tid, brief="越界那一件")
    face = sec.surface_of(owner=top, task_id=tid)["path"]
    pathlib.Path(face).mkdir(parents=True, exist_ok=True)
    inside = sec.surface_fit(action="fs.write", params={"path": "笔记.md"},
                             face=face, base=face)
    outside = sec.surface_fit(action="fs.write", params={"path": "../别人的面/x.md"},
                              face=face, base=face)
    assert inside.get("fits") is True, inside
    assert outside.get("fits") is False, ("面外的路径被判成做得成", outside)
    assert str((outside.get("paths") or [{}])[0].get("verdict") or "") == "escapes", outside
    assert "越出" in str(outside.get("reason") or ""), outside
    # 执行期那一侧（同一个判据的另一半）：`_surface_refusal`
    reg = build_registry(store=st, conductor=cond).registry
    loop = AgentLoop(role="E", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="E", session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    loop.surface = face
    loop.workspace_root = face
    assert loop._surface_refusal("fs.write", {"path": "笔记.md"}) == "", "面内路径被拦了"
    refused = loop._surface_refusal("fs.write", {"path": "../别人的面/x.md"})
    assert refused and "读写面" in refused, refused
    # `fs.move` 的两个参数（`src`/`dst`）也要被同一张表看到（E22）
    moved = loop._surface_refusal("fs.move", {"src": "笔记.md", "dst": "../外面.md"})
    assert moved and "dst" in moved, ("`fs.move` 的 dst 又漏了（E22 回归）", moved)


# ============================================================ 四条判据的"关掉就变坏"总表


def test_the_negative_controls_really_turn_the_readings_red(tmp_path: pathlib.Path,
                                                           monkeypatch: pytest.MonkeyPatch):
    """把四个机制**逐个关掉**，各取一条读数，证明它们不是"永远为真"的装饰。

    这一条不替代上面四条，而是把"关掉 ⇒ 变坏"压在一处可复核：
    ① 关名册 ⇒ `_children_text` 从"有名字"变成"没读成"；
    ② 关 descendants ⇒ 孙代消失；
    ③ 关退役（不写销号）⇒ `member_retired` 那条拒信不会出现；
    ④ 关面（去掉 surface）⇒ 面外路径不再被拦。
    """
    env = _env(tmp_path)
    child, name = _add_child(env)
    assert name in env["loop"]._children_text()

    # ① 名册关掉
    monkeypatch.setattr(SEC.Secretary, "roster_view", lambda self, **kw: {
        "checked": False, "rows": [], "more": 0, "reason": "关掉了"})
    assert "没读成" in env["loop"]._children_text()
    monkeypatch.undo()

    # ② descendants 关掉（用 self 视图代替）
    grand = _row(env["cond"], child, "C", key="grand@2")
    env["sec"].roster_add(owner=child, role="C", task_id=grand, brief="孙代")
    assert grand in {str(r.get("task_id")) for r in
                     env["sec"].roster_view(owner=env["me"], scope="descendants",
                                            limit=50)["rows"]}
    assert grand not in {str(r.get("task_id")) for r in
                         env["sec"].roster_view(owner=env["me"])["rows"]}

    # ③ 退役关掉（让视图不再标 retired ⇒ 寻址闸门不再拒）
    got = env["loop"]._do_retire({"name": name})
    assert got.get("action") == "retired", got
    real_view = SEC.Secretary.roster_view

    def _view_without_retired(self, **kw):
        out = real_view(self, **kw)
        for r in out.get("rows") or []:
            if str(r.get("status")) == "retired":
                r["status"] = "ready"
                r["state"] = "待命"
        return out

    monkeypatch.setattr(SEC.Secretary, "roster_view", _view_without_retired)
    reopened = env["loop"]._do_message({"to": name, "subject": "题", "body": "文"})
    assert str(reopened.get("refused") or "") != "member_retired", (
        "视图不再标 retired 之后仍然拒 ⇒ 那一条拒信不读名册", reopened)
    monkeypatch.undo()

    # ④ 面关掉（不设 surface ⇒ 老行为：不拦路径）
    reg = build_registry(store=env["st"], conductor=env["cond"]).registry
    loop = AgentLoop(role="E", session_root=env["ws"], registry=reg, conductor=env["cond"],
                     seam=LlmSeam(role="E", session_root=env["ws"], gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=env["st"], sid=SID, max_steps=2)
    assert loop.surface == ""
    assert loop._surface_refusal("fs.write", {"path": "../面外.md"}) == ""
