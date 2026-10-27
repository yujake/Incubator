# -*- coding: utf-8 -*-
"""触深的拒信要指向上行：到了第 5 个代理就不再自己派，把这件事交给父代理去协调。

## 业主原话（唯一权威，逐字）

```
「如果一个d5层的想派子代理（触发深度上限5），报错信息要提醒它将任务上报给父代理去协调，
  不要自己再派」
```

## 这一份钉住的五件事

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_the_refusal_names_the_depth_the_escalation_and_the_ban` | 触深拒信四样齐全：深度现算（测试档 `max_chain_depth=2` ⇒ 报文里只许出现 2 / 3 / 4，一个 5 都不许有）、点名"上报父代理去协调"、`conductor.escalate` 与三个真实形参名、明确禁令"不要再自己派"；四样还必须落在循环真的交给模型的那 400 字里 | 改前的报文只有一句"换个做法（自己收口或交给同级伙伴），不要再往深里派"：一个字的 `escalate` 都没有，而"交给同级伙伴"是同一层再派一次 —— 还是同一句"不"，等于没指路 |
| b) `test_b_escalating_from_the_fifth_layer_lands_in_the_parent_and_spawns_nothing` | 端到端：第 5 层派子被拒 ⇒ 用 `conductor.escalate` 把事交给父 ⇒ 父名下多一条能读到的留言、它自己没有多出子任务、这一趟以 `stop_reason=escalated` 收工 | 机制本来通（`tests/test_escalate_goes_up_and_stops.py` 已钉住父子通道），缺的是"拒信点名它"。所以这一条改前也绿 —— 它的职责是证明 a 指的那条路真走得通，否则 a 只是一句空话 |
| c) `test_c_the_fourth_layer_still_dispatches_the_fifth` | 正控：第 4 个代理派第 5 个照常成功（闸不能提前一格）；第 5 个再派才拒 | 改前绿（闸的位置本来就对）—— 它守的是"改这几句话时不许把闸挪动" |
| d) `test_d_the_depth_refusal_and_the_fanout_refusal_are_one_shape` | 形状一致：两种触顶的拒信都带"现算的读数 + 点名工具与真实形参名（形参名逐个过工具的声明）+ 前提 + 同一条收尾纪律" | 改前的触深拒信四样里只有"结构闸门"一句，`conductor.escalate` 与前提一字没有 ⇒ 与扇出那条（同一批的 `tests/test_retiring_a_silent_child_frees_a_fanout_seat.py` a 条）不是一个形状 |
| e) `test_e_stubbing_the_old_wording_turns_a_red` | 反真空：把"加这几句"打桩成旧文案 ⇒ a 必红（且红在缺哪几句上） | 不适用（它守的是 a 不是真空的那一条） |

## 为什么拒信必须点名"上游"，而不是只说"此路不通"

`depth_exceeded` 是结构闸门：它判的是这一趟在链上的位置（`Decision.depth` 对
`Policy.max_chain_depth`），与目标角色、动作、参数、扇出全无关。也就是说
被拒之后，同一层能做的任何一次 summon 都会吃到同一句"不"（换角色、换参数、
拆成两件事都一样）。报文若只说"换个做法"，读的人最容易试的就是"换一个角色再派"
—— 那是同一个闸门，重试只会烧回合。

唯一立刻能走的路在另一根轴上：把孩子这件事交给上一级（父代理），由它在
自己的深度上派、或者它再往上转。这条通道是现成的（`Conductor.escalate`，
业主 2026-10-19「父子天然双向」），而且它自带结局：成功即以
`stop_reason=escalated` 收工（退出码 5），不空转。

## 400 字那一格为什么是判据

`AgentLoop._do_summon` 把拒绝报文交给模型时是 `_clip(res.detail, 400)`
（`agent_loop.py` 里那一行）。写到 400 字之外的句子，台账里看着"说了"，
模型一个字都读不到 —— 那是本项目最忌讳的形态（说了等于没说，而且读不出来）。
所以 a) 用同一把尺子（`AL._clip`）量一遍，四样必须在模型真能看到的那一段里。
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from agentflow import agent_loop as AL
from agentflow import conductor as CD
from agentflow import policy as P
from agentflow.agent_loop import AgentLoop, read_messages
from agentflow.conductor import Conductor
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import conductor_tools as CT

#: 触深拒信必须点名的工具（名字与真身一致：`Conductor.escalate`）。
TOOL = "conductor.escalate"

#: 扇出那条拒信点名的工具（d) 拿它比形状）。
FANOUT_TOOL = "conductor.retire_child"

SID = "depth8"


# ====================================================================== 测试替身
class FakeA:
    """A 的替身：`run_once` 不接参数（链上只需要"这一行造得出来"）。"""

    def run_once(self) -> dict[str, Any]:
        return {"outcome": "ok", "detail": "夹具：A 跑完"}


class FakeB:
    """B 的替身：同上。"""

    def run_once(self) -> dict[str, Any]:
        return {"outcome": "ok", "detail": "夹具：B 跑完"}


class FakeD:
    """D 的替身：`probe_c` 的形参与声明一致（`qid` 必填）。"""

    def probe_c(self, qid: str, qrow: Any = None) -> dict[str, Any]:
        return {"outcome": "ok", "detail": f"夹具：D.probe_c({qid})"}


class FakeF:
    """F 的替身：`status` 的形参与声明一致（`plan_id` 必填）。"""

    def status(self, plan_id: str) -> dict[str, Any]:
        return {"outcome": "ok", "detail": f"夹具：F.status({plan_id})"}


class FakeE:
    """E 的替身：`evidence_for` 这一趟不会被派出去（它就是要被深度拒的那一件）。"""

    def evidence_for(self, claim_key: str = "", for_question_id: Any = None) -> dict[str, Any]:
        return {"outcome": "ok", "detail": f"夹具：E.evidence_for({claim_key})"}


class _Gateway:
    """照剧本回答的替身模型（与 `test_escalate_goes_up_and_stops` 同一个形状）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path) -> dict[str, Any]:
    """造一条 `M → A → B → D` 的链（四个代理），返回各层的台账号。

    第 5 个代理（F）由调用方自己派：c) 要证明它派得出去，b) 要站在它那一层说话。
    默认策略（`max_chain_depth=4`）下：A 的 depth=1、B=2、D=3、F=4 ⇒ F 就是业主
    数法里的"第 5 个代理"，它再派（depth=5）才触顶。
    """
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(
        store,
        policy=P.Policy(max_concurrency=8, max_direct_children=25,
                        max_tasks_per_run=500, wall_clock_sec=600),
        registry={"A": ("object", FakeA()), "B": ("object", FakeB()),
                  "D": ("object", FakeD()), "F": ("object", FakeF()),
                  "E": ("object", FakeE())},
        # 这一份判的是拒信与上行，不是"触顶只可等待"。
        fanout_wait_sec=0.0,
    )
    rows: dict[str, str] = {}
    a = cond.summon("A", "run_once", {}, by="M", input_key="q8-a")
    assert a.outcome == "ok", f"造链失败（A）：{a.outcome}/{a.refusal_reason}"
    rows["A"] = str(a.task_id)
    b = cond.summon("B", "run_once", {}, by="A", parent_task_id=rows["A"], input_key="q8-b")
    assert b.outcome == "ok", f"造链失败（B）：{b.outcome}/{b.refusal_reason}"
    rows["B"] = str(b.task_id)
    d = cond.summon("D", "probe_c", {"qid": "q-1"}, by="B", parent_task_id=rows["B"],
                    input_key="q8-d")
    assert d.outcome == "ok", f"造链失败（D）：{d.outcome}/{d.refusal_reason}"
    rows["D"] = str(d.task_id)
    assert (a.depth, b.depth, d.depth) == (1, 2, 3), (a.depth, b.depth, d.depth)
    return {"root": root, "store": store, "cond": cond, "rows": rows}


def _fifth(env: dict[str, Any], *, key: str = "q8-f") -> str:
    """把第 5 个代理（F）派出来，返回它的台账号（正控 c 与 b 都走这一格）。"""
    got = env["cond"].summon("F", "status", {"plan_id": "p-1"}, by="D",
                             parent_task_id=env["rows"]["D"], input_key=key)
    assert got.outcome == "ok", f"第 4 个代理派第 5 个竟然失败：{got.outcome}/{got.refusal_reason}"
    assert got.depth == 4, got.depth
    env["rows"]["F"] = str(got.task_id)
    return str(got.task_id)


def _over_the_depth(env: dict[str, Any], *, key: str = "q8-e") -> Any:
    """第 5 个代理（F）再派一件给 E ⇒ 深度拒（`depth_exceeded`）。"""
    return env["cond"].summon("E", "evidence_for", {"claim_key": "k-1"}, by="F",
                              parent_task_id=env["rows"]["F"], input_key=key)


def _children_of(env: dict[str, Any], task_id: str) -> list[dict[str, Any]]:
    """`task_id` 名下的子代理行（`kind == ""` 的代理行，不含板项行）。"""
    return [dict(r) for r in env["store"].rows("tasks")
            if str(r.get("parent_task_id") or "") == str(task_id)
            and not str(r.get("kind") or "")]


def _in_flight_children_of(env: dict[str, Any], task_id: str) -> list[dict[str, Any]]:
    """`task_id` 名下此刻还在飞的子代理（口径与 `_in_flight_children_of` 逐字一致）。"""
    return [r for r in _children_of(env, task_id)
            if str(r.get("status") or "") in ("pending", "running")]


def _inbox_escalations(root: pathlib.Path, role: str, *, sid: str = SID) -> list[dict]:
    """某个角色收件箱里带 `escalation` 那一格的留言（按结构捞，不按正文字面）。"""
    msgs, _problems = read_messages(root, role, sid=sid)
    return [m for m in msgs if isinstance(m.get("escalation"), dict)]


def _escalate_reply(need: str, kind: str = "reroute") -> str:
    return json.dumps({"tool": TOOL,
                       "args": {"need": need, "kind": kind,
                                "evidence": ["exp:0001"]}},
                      ensure_ascii=False)


def _summon_reply(role: str, task: str) -> str:
    return json.dumps({"summon": {"role": role, "task": task}}, ensure_ascii=False)


# ====================================================================== a) 拒信四样
def _depth_detail(policy: P.Policy, *, depth: int) -> str:
    """纯策略那一层拿到的拒信原文（不经过台账、不经过循环）。"""
    got = P.check(policy, P.Decision(frm="F", to="E", action="evidence_for", depth=depth))
    assert got is not None, f"depth={depth} 竟然被放行（policy={policy.to_dict()}）"
    assert got.reason == "depth_exceeded", got.reason
    return str(got.detail)


def _a_problems(detail: str, *, hops: int, agents: int,
                forbidden: tuple[str, ...] = ()) -> list[str]:
    """a) 的判据本体（单独抽出来，好让 e) 拿旧文案把它判红）。"""
    problems: list[str] = []
    for want in (
            f"max_chain_depth={hops}",          # ① 现算深度（台账数法）
            f"第 {agents} 个代理",               # ① 业主数法（第几个代理）
            f"不能再派第 {agents + 1} 个",
            f"= {hops} + 1 = {agents}",          # ① 那个数是加出来的，不是抄来的
            "现算",
            "上报父代理去协调",                  # ② 方向：交给上一级，不是"你自己再想想"
            TOOL,                               # ③ 点名工具
            "need=", "kind=", "evidence=",      # ③ 点名真实形参名
            "不要再自己派",                      # ④ 禁令
            "not_caller",                       # ③ 前提：顶层没有父
            "同时确认自己没有把同一件事",          # 与扇出那条同一个收尾纪律
    ):
        if want not in detail:
            problems.append(f"拒信里缺 {want!r}")
    for bad in forbidden:
        if bad in detail:
            problems.append(f"拒信里出现了写死的 {bad!r}（本次的深度是现算的 {hops}/{agents}）")
    return problems


def test_a_the_refusal_names_the_depth_the_escalation_and_the_ban() -> None:
    """a) 触深拒信：现算深度 + 上报父代理 + 工具与真实形参名 + 禁令，四样都在。

    "现算"必须能分辨：测试档 `max_chain_depth=2`，报文里只许出现 2 / 3 / 4；
    出现任何一个 5，就说明那句"已经到第 5 个代理"是抄来的。
    """
    # ---- 测试档：深度上限 2（链上第 3 个代理触顶）
    shallow = P.Policy(max_chain_depth=2)
    detail = _depth_detail(shallow, depth=3)
    problems = _a_problems(detail, hops=2, agents=3, forbidden=("5",))
    assert not problems, "；".join(problems) + f"\n拒信原文：{detail}"

    # ---- 默认档（业主数法：第 5 个代理 / 台账 4 跳）
    deep = P.Policy()
    detail0 = _depth_detail(deep, depth=5)
    problems0 = _a_problems(detail0, hops=4, agents=5)
    assert not problems0, "；".join(problems0) + f"\n拒信原文：{detail0}"

    # ---- 四样必须在模型真能看到的那一段里（循环给的是 `_clip(res.detail, 400)`）
    seen = AL._clip(detail0, 400)
    for want in (f"max_chain_depth=4", "上报父代理去协调", TOOL, "不要再自己派"):
        assert want in seen, (f"模型看到的那 400 字里没有 {want!r}（报文 {len(detail0)} 字，"
                              f"超出 400 的部分模型读不到）")


# ====================================================================== b) 端到端
def test_b_escalating_from_the_fifth_layer_lands_in_the_parent_and_spawns_nothing(
        tmp_path: pathlib.Path) -> None:
    """b) 第 5 层：派子被拒 ⇒ `escalate` 交给父 ⇒ 父的收件箱多一条、自己没有多出子任务。

    这一趟走的是真的循环（拒信 → 模型读到 → 调 `conductor.escalate`），
    所以同时钉住"收工"那一半：`stop_reason=escalated`（不是靠重试把步数烧完）。
    """
    env = _workspace(tmp_path)
    fifth = _fifth(env)
    root, cond = env["root"], env["cond"]

    # ---- 它先自己派了一次（被深度拒），台账里只多一行 refused，没有子代理
    refused = _over_the_depth(env)
    assert refused.outcome == "refused" and refused.refusal_reason == "depth_exceeded", refused
    assert _in_flight_children_of(env, fifth) == [], "被拒的召唤不许留下在飞的子代理"

    # ---- 这一趟循环：第 1 步派子（被拒）→ 第 2 步按拒信指的路上报
    gateway = _Gateway([_summon_reply("E", "取证据"),
                        _escalate_reply("我把这件取证据的活交给你：第 5 层派不出去了")])
    seam = LlmSeam(role="F", session_root=root, gateway=gateway, price=(0.0, 0.0), sid=SID)
    loop = AgentLoop(role="F", session_root=root,
                     registry=build_registry(store=env["store"], conductor=cond).registry,
                     seam=seam, conductor=cond, store=env["store"], sid=SID,
                     auto_secretary=False)
    run = loop.run("把这件取证据的活派出去（第 5 层）", summoned_by="D", my_task_id=fifth,
                   parent_task_id=str(env["rows"]["D"]), depth=4)

    # ① 它自己按既有语义收工（不是空转、不是靠 max_steps）
    assert run.stop_reason == "escalated", (run.stop_reason, run.final)

    # ② 父（D）名下多一条能读到的留言，载荷是这条上行
    got = _inbox_escalations(root, "D")
    assert len(got) == 1, [m.get("subject") for m in got]
    up = got[0]
    assert up.get("escalation", {}).get("kind") == "reroute", up.get("escalation")
    assert str(up.get("escalation", {}).get("need") or "").startswith("我把这件取证据"), up
    assert str(up.get("escalation", {}).get("to_task_id") or "") == str(env["rows"]["D"]), up

    # ③ 它自己没有多出子任务：名下只有"被拒"的台账行，在飞的一个都没有、成功的一个都没有
    kids = _children_of(env, fifth)
    assert kids, "被深度拒掉的那次召唤该在台账里留一行（拒绝也可审计）"
    assert {str(k.get("refusal_reason") or "") for k in kids} == {"depth_exceeded"}, kids
    assert _in_flight_children_of(env, fifth) == []
    assert [k for k in kids if str(k.get("outcome") or "") == "ok"] == []


# ====================================================================== c) 正控
def test_c_the_fourth_layer_still_dispatches_the_fifth(tmp_path: pathlib.Path) -> None:
    """c) 正控：第 4 个代理（D）派第 5 个（F）照常成功；F 再派才拒。

    "闸提前一格"是这类改动最容易犯的错：把 `>` 写成 `>=`，第 5 个代理就派不出来
    （而业主的数法是"第 5 个能干活、它再派才不行"）。
    """
    env = _workspace(tmp_path)
    fifth = _fifth(env)
    assert _children_of(env, fifth) == [], "F 刚被派出来，名下不该有子代理"
    # F（第 5 个代理，台账 depth=4）派 E（depth=5）⇒ 拒
    over = _over_the_depth(env)
    assert over.outcome == "refused" and over.refusal_reason == "depth_exceeded", over
    # 反真空：同一条边、少一层就放行（D 派 E 是 depth=4，正好在边界上）
    edge = env["cond"].summon("E", "evidence_for", {"claim_key": "k-2"}, by="D",
                              parent_task_id=env["rows"]["D"], input_key="q8-edge")
    assert edge.outcome == "ok", f"depth=4 是边界内的那一格，不许拒：{edge.refusal_reason}"
    assert edge.depth == 4, edge.depth


# ====================================================================== d) 形状一致
_TOOL_RE = re.compile(r"conductor\.([a-z_]+)")
_KW_RE = re.compile(r"([a-z_]+)=")


def _tool_spec(name: str) -> Any:
    """工具的真身声明（`@tool` 把它挂在函数上；这里按名字找，不另抄一份）。"""
    for attr in dir(CT):
        fn = getattr(CT, attr)
        spec = getattr(fn, "__tool_spec__", None)
        if spec is not None and spec.name == name:
            return spec
    raise AssertionError(f"{name} 不是工具层里真实存在的工具（拒信点了一个不存在的名字）")


def _named_kwargs(detail: str, tool: str) -> list[str]:
    """拒信里紧跟工具名点出来的那些形参名（到那一组括号为止）。"""
    idx = detail.index(tool)
    tail = detail[idx + len(tool):]
    cuts = [cut for cut in (tail.find("）"), tail.find(")")) if cut >= 0]
    if cuts:
        tail = tail[:min(cuts)]
    return _KW_RE.findall(tail)


def test_d_the_depth_refusal_and_the_fanout_refusal_are_one_shape() -> None:
    """d) 两条闸的拒信同一个形状：现算读数 + 工具与真实形参名 + 前提 + 同一条收尾。

    这一条是"别各写一套"的机器形态：它从两份报文里抽出工具名与形参名，
    逐个过工具的真身声明（`params.properties`），而不是看两句汉字像不像。
    """
    depth_detail = _depth_detail(P.Policy(), depth=5)
    fanout = P.check(P.Policy(max_direct_children=3),
                     P.Decision(frm="D", to="A", action="run_once", direct_children=3))
    assert fanout is not None and fanout.reason == "fanout_exceeded", fanout
    fanout_detail = str(fanout.detail)

    problems: list[str] = []
    for label, detail, wants, role, tool in (
            ("触深", depth_detail,
             ("现算", f"max_chain_depth={P.Policy().max_chain_depth}",
              "上报父代理去协调", "不要再自己派"), "F", TOOL),
            ("扇出", fanout_detail,
             ("现算", "上限 3", FANOUT_TOOL), "D", FANOUT_TOOL),
    ):
        for want in wants:
            if want not in detail:
                problems.append(f"{label}拒信里缺 {want!r}")
        # 同一个收尾纪律 + 同一句前提（四样里的最后两样，两条闸都点）
        for want in ("前提：", "同时确认自己没有把同一件事"):
            if want not in detail:
                problems.append(f"{label}拒信里缺 {want!r}（两条闸必须是同一个形状）")
        # 工具名：要点的那个必须在，且点到的每一个都是工具层里真的存在的
        # （`conductor.state` 这类"读数工具"也在扇出那条报文里出现，所以判据是
        # "点到的每个名字都得是真的"，不是"只许出现一个"）
        named = sorted({f"conductor.{n}" for n in _TOOL_RE.findall(detail)})
        if tool not in named:
            problems.append(f"{label}拒信没有点名 {tool}（它点的是 {named}）")
            continue
        specs = {name: _tool_spec(name) for name in named}
        spec = specs[tool]
        if role not in spec.roles:
            problems.append(f"{label}的发起方 {role} 拿不到 {tool}（roles={spec.roles}）")
        props = set((spec.params or {}).get("properties") or {})
        used = _named_kwargs(detail, tool)
        for kw in used:
            if kw not in props:
                problems.append(f"{label}拒信点了一个不存在的形参 {kw!r}（{tool} 只认 {sorted(props)}）")
        required = set((spec.params or {}).get("required") or ())
        missing = sorted(required - set(used))
        if missing:
            problems.append(f"{label}拒信没给必填形参 {missing}（{tool} 的 required 是 {sorted(required)}）")
    assert not problems, "；".join(problems)

    # 顺带钉住 `kind` 的取值也是真身里的那一档（"reroute" = 由父重新路由给别的角色）
    assert re.search(r'kind="([a-z_]+)"', depth_detail), depth_detail
    assert re.search(r'kind="([a-z_]+)"', depth_detail).group(1) in CD.ESCALATE_KINDS


# ====================================================================== e) 反真空
def test_e_stubbing_the_old_wording_turns_a_red(monkeypatch: Any) -> None:
    """e) 反真空：把拒信打桩成改前那句旧文案 ⇒ a 必红，且红在缺哪几句上。

    打桩打在 `P.check` 这一步：改前的文案就是这一步拼出来的，而 a) 量的是这一步
    交给台账的那段字符串。若有人把 a) 的断言删空，这一条会绿 —— 所以它同时断言
    新文案本身仍然过得了 a)（否则"打桩 ⇒ 红"证明的只是打桩坏了）。
    """
    shallow = P.Policy(max_chain_depth=2)
    old = (f"已经到第 3 个代理（业主原话里的 Z）了，链上最多 3 个代理 ⇒ 不能再派第 4 个。"
           f"台账数法：本次 depth=3 超过 max_chain_depth=2（主控的召唤 = 1，链上代理个数 = 跳数 + 1）。"
           "这是结构闸门，不是成本闸门 —— 换个做法（自己收口或交给同级伙伴），不要再往深里派")

    def _old_check(policy: P.Policy, d: P.Decision, **kw: Any) -> P.Refusal:
        return P.Refusal("depth_exceeded", old, "max_chain_depth")

    # 先证明判据本体不是空的：新文案过得了，旧文案过不了
    fresh = _depth_detail(shallow, depth=3)
    assert not _a_problems(fresh, hops=2, agents=3, forbidden=("5",)), "夹具坏了：新文案自己就不合格"

    monkeypatch.setattr(P, "check", _old_check)
    stubbed = _depth_detail(shallow, depth=3)
    assert stubbed == old
    problems = _a_problems(stubbed, hops=2, agents=3, forbidden=("5",))
    assert problems, "把拒信换回旧文案，a) 仍然全绿 —— 那说明 a) 量的不是那几句话"
    joined = "；".join(problems)
    for want in ("上报父代理去协调", TOOL, "need=", "不要再自己派"):
        assert want in joined, joined
