"""名册登记必须覆盖每一条派活路径，而且恰好一次（2026-10-21 真机缺陷的回归判据）。

## 事故（`projects/p3-verify`，只读盘上读数）

`tasks` 里 5 个带父的代理行（`t-000001 M d1` / `t-000002 A d2` / `t-000003 E d2` /
`t-000005 D d2` / `t-000006 E d3`），而 `out/roster/` 连目录都没有、三份秘书台账里
提到 roster 的行数 = 0。两条各自独立的缺口（都有盘上证据）：

1. 主控第 9 步调的是**原生工具** `conductor.summon_many`（3 个 target，`instance`
   分别是 lit / num / audit34）⇒ `tools/conductor_tools.py` → `Conductor.run_plan`
   → `scheduler` → `Conductor.summon`。这条链上改前一次 `roster_add` 都没有 ——
   登记只写在 `agent_loop` 的两条形状路上（`_do_summon` / `_do_summon_many`），
   而真机用的是工具那条路。
2. `t-000006`（`called_by=D` / `parent=t-000005` / `depth=3`）的派活卡在
   `Conductor.summon` 里被 `cli stop --force` 杀掉 ⇒ D 那一步连 `agent_step` 事件
   都没有（事件在 handler 返回之后才落）。改前登记排在 `summon` 返回**之后**
   ⇒ 被杀在途中的子代理永远不会登记，批量那一路还要等整批跑完。

## 修法（本文件钉的就是它）

登记收口到 `Conductor.summon` 的第 [5b] 步：**受理那一行落盘之后、子代理跑起来之前**，
只此一处；`brief` / `task` 随 `summon(..., roster={...})` 带进来（`schema.Task` 里
没有这两格，从行里读会恒空）。各派活路径只读回 `SummonResult.roster_*`，不再自己
调 `roster_add`（同一子代理两条同名项就是"登记两次"的形态）。

## 六条判据（每条都配一条负控或对照，红绿成对）

| 编号 | 这条问什么 |
|---|---|
| ① | 三条真实路径（`_do_summon` / `_do_summon_many` / 两个 `conductor.*` 工具）各派一次 ⇒ `out/roster/<父>.jsonl` 在盘上，行数 == 受理子数，每行 `task_id` 与台账子行一致 |
| ② | 被拒的那一次不登记（同一次派活里另有一条受理的子代理 ⇒ 名册里只有它） |
| ③ | 未受理（取消在落行之前 / 没有父编号）⇒ 0 行 + 理由；对照：已受理但后来 failed ⇒ 名册里有它，`outcome=failed` 在台账上读得出来 |
| ④ | 没有秘书 ⇒ 不许抛；`roster_problem` 里出现"没有秘书 / 名册不在手上"（不许静默） |
| ⑤ | 同一次派活只登记一次（行数 == 1，不是 2；名册名不重复） |
| ⑥ | 端到端：`webui.readers.roster_face(root)` 读回来 `answer="ok"`、`count == 受理子数`、每个节点都不是 `registered=False` |

另加一条（同一处时序缺陷的另一半，改前面切割从来没生效过）：

| 判据 | 这条问什么 |
|---|---|
| ⑦ | 登记发生在子代理跑起来**之前**：假后端在自己的 `call` 里按 `surface_of(owner=父, task_id=子)` 读面，读得到 |

## 纪律

全部用 tmp 工作区 + 假后端 + 假缝，一次模型调用都不发（`_Gate.complete` 只回 `{}`）。
盘上读数一律读文件（`secretary.roster_path`），不读视图 —— 这条问的就是"写没写进去"。
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import secretary as SEC  # noqa: E402
from agentflow.agent_loop import AgentLoop  # noqa: E402
from agentflow.cancellation import CancelToken  # noqa: E402
from agentflow.conductor import Conductor, calling_as  # noqa: E402
from agentflow.llmseam import LlmSeam  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402
from agentflow.tools import conductor_tools as CT  # noqa: E402
from agentflow.webui import readers as RD  # noqa: E402

SID = "s-roster-every-path"
#: 我是顶层主控（`M` 的出边覆盖 A–H ⇒ 派活这一层不吃边表）。
MY_ROLE = "M"
#: 子代理角色（`M` 能派它；它在夹具里不需要任何真实依赖）。
CHILD = "E"


class _Gate:
    """seam 的替身：这一组判据只碰名册与台账，不碰模型（一次调用都不发）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        return type("Reply", (), {"ok": True, "text": "{}", "tool_calls": (),
                                  "tokens_in": 1, "tokens_out": 1,
                                  "error_detail": "", "error_kind": ""})()


class _Backend:
    """假后端：任何 (角色, 动作) 都跑成同一件事，并把"这次调用"记下来。

    为什么不用 `LocalBackend`：形状路（`_do_summon` / `_do_summon_many`）派活时
    `action` 一律是空串（口径 S2「M 只派活」），而 `LocalBackend` 对空动作会走
    `NotWiredError` ⇒ 那是"没接线"，不是"跑完了"，判据会红在与名册无关的事上。
    真机那条路上空动作由 `LlmBackend` 跑循环，这里用一个只回结果的假后端代替。
    """

    name = "fake"

    def __init__(self, *, outcome: str = "ok", raises: BaseException | None = None) -> None:
        self.outcome = outcome
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def call(self, role: str, action: str, params: Any, *, token: Any,
             instance: str = "", task_id: str = "") -> Any:
        self.calls.append({"role": role, "action": action, "task_id": str(task_id),
                           "instance": str(instance), "params": dict(params or {})})
        if self.raises is not None:
            raise self.raises
        return {"outcome": self.outcome, "detail": "跑完了", "payload": {"ok": True}}


def _env(tmp_path: pathlib.Path, *, secretary: bool = True, parent: bool = True,
         top: bool = True, backend: Any = None) -> dict[str, Any]:
    """一个工作区 + 一趟顶趟 + 一个主控循环（秘书按参数装配或不装配）。

    `top=False` ⇒ 连顶趟都不开（"连父编号都没有"那一档，见判据③）。
    `parent=False` ⇒ 开了顶趟，但循环自己还不知道（`my_task_id` 为空）。
    """
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    be = backend or _Backend()
    cond = Conductor(st, policy=None, backend=be)
    reg = build_registry(store=st, conductor=cond).registry
    top_id = cond.open_top_level_run(MY_ROLE, "顶层这一趟") if top else ""
    loop = AgentLoop(role=MY_ROLE, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=MY_ROLE, session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2,
                     auto_secretary=bool(secretary))
    loop.my_task_id = top_id if parent else ""
    return {"ws": ws, "st": st, "cond": cond, "reg": reg, "loop": loop,
            "sec": loop.secretary, "me": top_id, "backend": be}


def _adds(ws: pathlib.Path, owner: str) -> list[dict[str, Any]]:
    """盘上那一份名册的 `add` 行（读文件，不读视图）。"""
    path = SEC.roster_path(ws, owner)
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return [r for r in rows if str(r.get("kind")) == "add"]


def _task_row(ws: pathlib.Path, task_id: str) -> dict[str, Any]:
    rows = json.loads((pathlib.Path(ws) / "data" / "tasks.json")
                      .read_text(encoding="utf-8"))["rows"]
    got = [r for r in rows if str(r.get("task_id")) == str(task_id)]
    assert len(got) == 1, (task_id, [r.get("task_id") for r in rows])
    return got[0]


# ---------------------------------------------------------------- 判据①（三条真实路径）


def test_path_one_single_summon_writes_the_roster(tmp_path: pathlib.Path) -> None:
    """判据①之一：`_do_summon`（形状路）⇒ 名册一行，`task_id` 与台账子行一致、brief 是父给的。"""
    env = _env(tmp_path)
    out = env["loop"]._do_summon({"role": CHILD, "task": "干一件", "brief": "甲这件活"})
    assert out.get("ok") is True, out
    kid = str(out.get("task_id") or "")
    assert kid, out
    adds = _adds(env["ws"], env["me"])
    assert [str(a.get("task_id")) for a in adds] == [kid], adds
    assert str(adds[0].get("owner")) == env["me"], adds[0]
    # 台账里那个子行的父就是这一趟的绝对编号（父子关系的唯一权威来源）。
    child = _task_row(env["ws"], kid)
    assert str(child.get("parent_task_id")) == env["me"], child
    assert int(child.get("depth") or 0) == 2, child
    # 父给的那句简介原样落进名册（不是任务原文顶替，也不是秘书代写）。
    assert str(adds[0].get("brief")) == "甲这件活", adds[0]
    assert str(adds[0].get("brief_source")) == "parent", adds[0]
    assert str(out.get("roster_name") or "") == str(adds[0].get("name")), out


def test_path_two_summon_many_writes_every_accepted_child(tmp_path: pathlib.Path) -> None:
    """判据①之二：`_do_summon_many`（批量形状路）⇒ 每个受理的子各一行，逐项 brief 各是各的。"""
    env = _env(tmp_path)
    targets = [{"role": CHILD, "task": f"干第 {i} 件", "brief": f"第 {i} 件活"}
               for i in (1, 2)]
    out = env["loop"]._do_summon_many({"targets": targets})
    assert out.get("ok") is True, out
    ids = [str(r.get("task_id") or "") for r in out.get("results") or []]
    assert len(ids) == 2 and all(ids), out
    adds = _adds(env["ws"], env["me"])
    assert [str(a.get("task_id")) for a in adds] == ids, (adds, ids)
    assert [str(a.get("brief")) for a in adds] == [t["brief"] for t in targets], adds
    assert "roster_problems" not in out, out


def test_path_three_the_conductor_tools_are_covered_too(tmp_path: pathlib.Path) -> None:
    """判据①之三（真机那条路）：`conductor.summon` / `conductor.summon_many` 两个原生工具。

    `projects/p3-verify` 的主控第 9 步用的就是 `conductor.summon_many` —— 改前这两个
    工具走完 `Conductor.run_plan` 之后一个登记点都没有。这一条同时钉住"工具派出去的
    子行必须带父"（改前单个工具那条连 `parent_task_id` 都不传 ⇒ 孤儿，名册没处登记）。
    """
    env = _env(tmp_path)
    with calling_as(env["me"], MY_ROLE):
        one = CT.conductor_summon(lambda: env["cond"], target_role=CHILD,
                                  task="工具派的单件活", params=None, input_key="")
        many = CT.conductor_summon_many(
            lambda: env["cond"],
            targets=[{"target_role": CHILD, "task": f"工具派的第 {i} 件"}
                     for i in (1, 2)], why="")
    assert one.ok is True, one
    assert many.ok is True, many
    ids = [str(one.data.get("task_id") or "")]
    ids += [str(r.get("task_id") or "") for r in many.data.get("results") or []]
    assert len(ids) == 3 and all(ids), (one.data, many.data)
    adds = _adds(env["ws"], env["me"])
    assert [str(a.get("task_id")) for a in adds] == ids, (adds, ids)
    for kid in ids:
        assert str(_task_row(env["ws"], kid).get("parent_task_id")) == env["me"], kid
    # 读数面：工具体自己也要能回答"这一条进名册没有"（改前这里一个字都没有）。
    assert str(one.data.get("roster_name") or ""), one.data
    assert one.data.get("roster_considered") is True, one.data


# ---------------------------------------------------------------- 判据②（被拒不登记）


def test_a_refused_summon_is_not_registered(tmp_path: pathlib.Path) -> None:
    """判据②：被拒的那一次不进名册 —— 同一次派活里另有一条受理的子代理做对照。

    红点在哪（改前）：受理的那一条**也**没登记（整条路 0 行）⇒ 对照那一半先红，
    而被拒的那一条"恰好没登记"就变得不可判定（0 行既可能是"没登记"，也可能是
    "根本没走过漏斗"）。这一条把两件事分开：名册里必须恰好有受理的那一个编号。
    """
    env = _env(tmp_path)
    good = env["loop"]._do_summon({"role": CHILD, "task": "会受理的那件", "brief": "甲的活"})
    assert good.get("ok") is True, good
    bad = env["loop"]._do_summon({"role": MY_ROLE, "task": "会被拒的那件"})  # M 不可被召唤
    assert bad.get("ok") is False, bad
    assert str(bad.get("refusal_reason") or "") == "forbidden_edge", bad
    # 被拒也落台账（拒绝要可审计）—— 但它不在名册上。
    refused_tid = str(bad.get("task_id") or "")
    assert refused_tid, bad
    assert str(_task_row(env["ws"], refused_tid).get("outcome")) == "refused"
    adds = _adds(env["ws"], env["me"])
    assert [str(a.get("task_id")) for a in adds] == [str(good.get("task_id"))], adds


# ---------------------------------------------------------------- 判据③（未受理 / 受理后失败）


def test_an_unadmitted_summon_writes_no_roster_line_but_says_why(tmp_path: pathlib.Path) -> None:
    """判据③：未受理（取消在落行之前 / 没有父编号）⇒ 名册 0 行，且理由读得出来。

    两档各有一个对照：
    * 取消：`token` 已置位 ⇒ `Conductor.summon` 在 [0] 就返回，没有子行；
    * 没有父：`agent_loop._do_summon` 的受控拒绝 `no_owner`，一行子行都不落。
    改前的红点：同一工作区里随后那次**受理**的派活不登记 ⇒ 名册 0 行，于是
    "未受理的没登记"与"受理的也没登记"分不开。
    """
    env = _env(tmp_path, top=False)
    no_owner = env["loop"]._do_summon({"role": CHILD, "task": "没有父的那件"})
    assert no_owner.get("ok") is False and no_owner.get("refused") == "no_owner", no_owner
    # 现在才有顶趟：下面两档都在"有父编号"的前提下发生。
    env["me"] = env["cond"].open_top_level_run(MY_ROLE, "后来才开的顶趟")
    env["loop"].my_task_id = env["me"]
    tok = CancelToken()
    tok.cancel("user")
    cancelled = env["cond"].summon(CHILD, "", {"task": "取消的那件"}, by=MY_ROLE,
                                   parent_task_id=env["me"], token=tok)
    assert cancelled.status == "cancelled" and cancelled.task_id is None, cancelled
    assert "名册" in str(getattr(cancelled, "roster_problem", "")), cancelled
    assert _adds(env["ws"], env["me"]) == [], "未受理的召唤不许在名册上留行"
    # 对照：同一个工作区里受理一次 ⇒ 名册里正好是它（改前这里恒为 0 行）。
    ok = env["loop"]._do_summon({"role": CHILD, "task": "受理的那件", "brief": "乙的活"})
    assert ok.get("ok") is True, ok
    assert [str(a.get("task_id")) for a in _adds(env["ws"], env["me"])] == [ok["task_id"]]


def test_an_admitted_child_that_fails_is_still_on_the_roster(tmp_path: pathlib.Path) -> None:
    """判据③的对照半：已受理（子行落盘）之后才 failed ⇒ 名册里有它，失败在台账上。

    名册回答"它被建立过没有"，`tasks` 回答"跑成没有" —— 两者不许互相冒充。改前
    这条路把它记成"没登记"，于是"跑了但崩了"与"根本没被建立"在名册上长得一样。
    """
    env = _env(tmp_path, backend=_Backend(raises=RuntimeError("脚本炸了")))
    out = env["loop"]._do_summon({"role": CHILD, "task": "会炸的那件", "brief": "丙的活"})
    assert str(out.get("status")) == "failed", out
    kid = str(out.get("task_id") or "")
    assert kid, out
    adds = _adds(env["ws"], env["me"])
    assert [str(a.get("task_id")) for a in adds] == [kid], adds
    child = _task_row(env["ws"], kid)
    assert str(child.get("status")) == "failed", child
    assert str(child.get("outcome")) == "failed", child


# ---------------------------------------------------------------- 判据④（没有秘书）


def test_no_secretary_is_a_named_problem_not_an_exception(tmp_path: pathlib.Path) -> None:
    """判据④：不传秘书 / 没有名册写入口 ⇒ 不抛，读数是"名册不在手上"。

    两处都要读得出来：循环那一层（`_do_summon` 的返回值）与 conductor 那一层
    （`SummonResult.roster_problem`）。改前 conductor 那一层连这两格都没有：
    派活照样跑、名册静默不动，事后没有任何读数能回答"为什么没登记"。
    """
    env = _env(tmp_path, secretary=False)
    assert env["loop"].secretary is None, "这一条要的是'没有秘书'那一档"
    out = env["loop"]._do_summon({"role": CHILD, "task": "没有秘书的那件"})
    assert out.get("ok") is True, out
    problem = str(out.get("roster_problem") or "")
    assert "没有秘书" in problem or "名册不在手上" in problem, out
    assert _adds(env["ws"], env["me"]) == [], "没有秘书时名册不许出现半行"
    res = env["cond"].summon(CHILD, "", {"task": "conductor 那一层"}, by=MY_ROLE,
                             parent_task_id=env["me"], roster={"task": "conductor 那一层"})
    assert getattr(res, "roster_considered", False) is True, res
    assert "名册" in str(getattr(res, "roster_problem", "")), res


# ---------------------------------------------------------------- 判据⑤（恰好一次）


def test_each_child_is_registered_exactly_once(tmp_path: pathlib.Path) -> None:
    """判据⑤：一次派活只登记一次（行数 == 1，名册名与编号都不重复）。

    为什么这条会红在"多登记"那一侧：漏斗放进 `Conductor.summon` 之后，如果调用点
    （`_do_summon` / `_do_summon_many`）还留着自己那次 `roster_add`，同一个子代理会
    在名册上出现两条同名项（`next_name` 按角色序号发号 ⇒ X1 与 X2）。
    """
    env = _env(tmp_path)
    out = env["loop"]._do_summon({"role": CHILD, "task": "只登一次的那件", "brief": "丁的活"})
    assert out.get("ok") is True, out
    adds = _adds(env["ws"], env["me"])
    assert len(adds) == 1, ("一次派活只该有一行", adds)
    assert str(out.get("roster_name") or "") == str(adds[0].get("name")), out
    # 批量那一路同理：两个 target 两行，不是四行。
    many = env["loop"]._do_summon_many({"targets": [
        {"role": CHILD, "task": "批一", "brief": "批一的活"},
        {"role": CHILD, "task": "批二", "brief": "批二的活"},
    ]})
    assert many.get("ok") is True, many
    adds = _adds(env["ws"], env["me"])
    assert len(adds) == 3, adds
    assert len({str(a.get("task_id")) for a in adds}) == 3, adds
    assert len({str(a.get("name")) for a in adds}) == 3, adds


# ---------------------------------------------------------------- 判据⑥（端到端读回来）


def test_roster_face_reads_back_the_whole_tree(tmp_path: pathlib.Path) -> None:
    """判据⑥：跑完三条路径之后，用 `webui.readers.roster_face(root)` 读回来。

    读侧的口径（见 `readers.roster_face`）：`nodes` 是整棵树，**根那一行也在里面**
    （根 = 名册文件的主人，它自己没有名册名；真机 p3 的读数是 `t-000001 M d1` 打头、
    `count=5`），所以 `count` = 1（根）+ 受理子数。断言：
    * `answer="ok"`（名册真读成了，不是台账兜底）；
    * `count == 1 + 受理子数`，子节点数与受理子数一致；
    * 每个**子**节点都不是 `registered=False`（名册节点不带 `registered` 那一格：
      它出现在名册里本身就是"登记了"；`False` 只出现在台账兜底那一档，那正是
      "名册没读到"的形态）；
    * `coverage.unrostered == 0`（台账里没有"有父却不在名册上"的行）。
    """
    env = _env(tmp_path)
    accepted: list[str] = []
    one = env["loop"]._do_summon({"role": CHILD, "task": "单件的活", "brief": "单件"})
    accepted.append(str(one.get("task_id") or ""))
    with calling_as(env["me"], MY_ROLE):
        many = CT.conductor_summon_many(
            lambda: env["cond"],
            targets=[{"target_role": CHILD, "task": f"批量的第 {i} 件"}
                     for i in (1, 2)], why="")
    accepted += [str(r.get("task_id") or "") for r in many.data.get("results") or []]
    assert len(accepted) == 3 and all(accepted), accepted

    face = RD.roster_face(env["ws"])
    assert face["answer"] == "ok", (face["answer"], face["reason"])
    assert face["count"] == 1 + len(accepted), face["count"]
    assert face["roots"] == [env["me"]], face["roots"]
    kids = [n for n in face["nodes"] if str(n.get("task_id")) != env["me"]]
    assert sorted(str(n.get("task_id")) for n in kids) == sorted(accepted), kids
    for node in kids:
        assert node.get("registered", True) is not False, node
        assert str(node.get("name") or ""), ("名册里的子节点必须有名字", node)
    assert face["coverage"]["unrostered"] == 0, face["coverage"]
    assert f"{env['me']}.jsonl" in face["files"], face["files"]


# ---------------------------------------------------------------- 判据⑦（面切割：登记在跑之前）


class _FaceWatchingBackend(_Backend):
    """在自己的 `call` 里读一次"我这一趟的面"：登记若排在返回之后，这里恒为空。"""

    def __init__(self, *, ws: pathlib.Path, st: Store, owner: str) -> None:
        super().__init__()
        self.ws = ws
        self.st = st
        self.owner = owner
        self.seen: list[dict[str, Any]] = []

    def call(self, role: str, action: str, params: Any, *, token: Any,
             instance: str = "", task_id: str = "") -> Any:
        got = SEC.Secretary("M", root=self.ws, store=self.st).surface_of(
            owner=self.owner, task_id=str(task_id))
        self.seen.append(dict(got))
        return super().call(role, action, params, token=token, instance=instance,
                            task_id=task_id)


def test_registration_happens_before_the_child_runs(tmp_path: pathlib.Path) -> None:
    """判据⑦：登记必须早于子代理跑起来 —— 子代理在自己的 `call` 里读得到面。

    这条是同一处时序缺陷的另一半：`LlmBackend.call` 给子代理起循环时按
    `surface_of(owner=父, task_id=子)` 从名册里读那一趟的读写面（S1n-b/c）。改前
    名册行是 `summon` 返回**之后**才有的 ⇒ 面切割从来没生效过（子代理永远拿到空面，
    回到父的工作区里读写）。登记提前之后，后端一进去就该读得到那一格。
    """
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    top = Conductor(st, policy=None, backend=_Backend()).open_top_level_run(MY_ROLE, "顶趟")
    be = _FaceWatchingBackend(ws=ws, st=st, owner=top)
    cond = Conductor(st, policy=None, backend=be)
    reg = build_registry(store=st, conductor=cond).registry
    loop = AgentLoop(role=MY_ROLE, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=MY_ROLE, session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    loop.my_task_id = top
    out = loop._do_summon({"role": CHILD, "task": "要切面的那件", "brief": "戊的活"})
    assert out.get("ok") is True, out
    assert be.seen, "后端一次都没被调用（夹具坏了）"
    face = be.seen[0]
    assert face.get("checked") is True, ("子代理跑起来时名册里还查不到它", face)
    assert str(face.get("path") or ""), face
    assert str(face.get("slot") or ""), face
