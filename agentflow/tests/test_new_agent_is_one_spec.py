# -*- coding: utf-8 -*-
""""新建一个 agent = 一个模块 + 一次登记"—— 到哪一步是真的？（`goal-7f5116c1` M5）

这条判据不解释、只演示：在测试里造一个角色 Z —— 不碰 `specs/`、不碰 `capabilities`、
不碰 `host`，只写一份 `AgentSpec` 注册进一张局部注册表 —— 然后逐步看它到哪一步为止是自由的：

1. 被装配：`spec.build(BuildDeps(...))` 造出实例；
2. 被召唤：`Conductor(specs=那张局部注册表)` 的闸门认它（含"它能召唤谁"）；
3. 被审计：`audit_registry(那张局部注册表)` 通过；召唤之后台账里留下可核的行；
4. 工具面：这里停下来 —— `build_for_role("Z")` 会被工具层拒，理由逐字是
   "声明了不在 `TOOL_ROLES(...)` 里的角色：['Z']"。

第 4 步是本轮量出来的真实代价，不是缺陷：角色名是跨模块约定，`TOOL_ROLES` 在
`tools/__init__.py`（FC-27 禁改区）里，加一个角色得有人审。也就是说准确的说法是

 新建一个 agent = 一个模块（`specs/<角色>.py`）+ 一次登记（`tools/__init__.py::TOOL_ROLES`）

而这"一次登记"由判据点名（下面的断言逐字认那句话），不会被静默漏掉。
"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile

import pytest

from agentflow import policy as P
from agentflow import schema
from agentflow import schema as S
from agentflow import tools as tools_pkg
from agentflow.agentspec import (
    ActionSpec,
    AgentBrief,
    AgentRegistry,
    AgentSpec,
    BuilderDeps,
    audit_registry,
    builtin_registry,
)
from agentflow.conductor import Conductor
from agentflow.store import Store
from agentflow.tools import TOOL_ROLES, build_for_role, build_registry
from agentflow.verify import verify_all

PROBE_PARAMS = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
FACULTY_NAMES = ("眼睛", "耳朵", "脑子", "手", "能讨论", "高观点", "能互动", "能思辨", "有品位", "能收敛")


class ProbeAgent:
    """临时角色的"实现"：一个方法就够 —— 它要证明的是装配路径，不是业务。"""

    def __init__(self, store: object, *, tag: str = "") -> None:
        self.store = store
        self.tag = tag
        self.calls: list[dict] = []

    def peek(self) -> dict:
        """Z 唯一的动作：记下被调用过（测试据此判断"真的派到它头上了"）。"""
        self.calls.append({"called": True})
        return {"ok": True, "calls": len(self.calls), "tag": self.tag}


def _probe_build(d: BuilderDeps) -> ProbeAgent:
    return ProbeAgent(d.store, tag=f"built-by-{d.role}")


def probe_spec(*, edges: tuple[str, ...] = ("A",), **over) -> AgentSpec:
    """一份 `AgentSpec` —— 新增一个角色要写的全部声明（就是这个函数里的东西）。"""
    base = AgentSpec(
        role="Z",
        brief=AgentBrief(
            duty="证明新角色只靠一份声明就能被装配、被召唤、被审计",
            boundary=("不碰任何真实数据表（它唯一的动作只记一次调用）",),
            policy=(),
            signature_error="把'演示通过'说成'业务正确'",
            deliverable="一次可核的调用记录",
            stance=("这一条判据问的是装配路径，不是数学结论",),
        ),
        emphasis={f: "minor" for f in FACULTY_NAMES},
        local_notes={"眼睛": "只看这一次调用有没有真的落到实现上。"},
        read_only=True,
        summonable=True,
        edges=edges,
        write_set=frozenset(),
        class_path="",                      # 可选：实现由 build 负责
        actions=(ActionSpec(
            role="Z",
            action="peek",
            summary="记一次调用（演示用）",
            params=PROBE_PARAMS,
            returns="{'ok','calls','tag'}",
            side_effect="read",
            handler_name="peek",
            external="none",
        ),),
        build=_probe_build,
    )
    return dataclasses.replace(base, **over) if over else base


def temp_registry(*, m_edges: tuple[str, ...] | None = None, spec: AgentSpec | None = None
                  ) -> AgentRegistry:
    """内置注册表 + Z（可选：让主控多一条到 Z 的边）—— 这就是全部"登记"。"""
    reg = AgentRegistry()
    for role in builtin_registry().roles():
        base = builtin_registry().get(role)
        if role == S.CONDUCTOR_ROLE and m_edges is not None:
            base = dataclasses.replace(base, edges=tuple(m_edges))
        reg.add(base)
    reg.add(spec or probe_spec())
    return reg


def _ws(tmp: str) -> tuple[Store, pathlib.Path]:
    ws = pathlib.Path(tmp) / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return st, ws


# ---------------------------------------------------------------- ① 被装配


def test_one_spec_is_enough_to_be_built() -> None:
    """`spec.build(BuildDeps(...))` 直接造出实例（装配不需要 `host` 认识这个角色）。"""
    inst = probe_spec().build(BuilderDeps(role="Z", store=object()))
    assert isinstance(inst, ProbeAgent) and inst.tag == "built-by-Z"
    assert inst.peek()["calls"] == 1


# ---------------------------------------------------------------- ② 被召唤


def test_one_spec_is_enough_to_pass_the_gate() -> None:
    """闸门读的是注册表：传了就认，不传就不认（后者是有意的）。"""
    reg = temp_registry(m_edges=("Z",))
    assert P.check_action("Z", "peek", registry=reg) is None
    assert P.check_action("Z", "nope", registry=reg).reason == "unknown_action"
    assert P.check_action("Z", "peek").reason == "unknown_role"      # 不传注册表 ⇒ 不认

    pol = P.Policy()
    assert P.check(pol, P.Decision(frm=S.CONDUCTOR_ROLE, to="Z", action="peek"),
                   registry=reg) is None, "主控 → Z 应当放行（那条边在注册表里）"
    refused = P.check(pol, P.Decision(frm="Z", to="B", action="run_once"), registry=reg)
    assert refused is not None and refused.reason == "forbidden_edge", refused


def test_one_spec_is_enough_to_be_summoned_and_audited(monkeypatch) -> None:
    """端到端：真的召唤一次、落台账、审计不挑毛病 —— 但要补上两处登记。

    量出来的真实代价（这条用例就是它的读数）：只写一份 spec 时，召唤会在写台账那一步
    被数据面拒（`schema.Task.validate`：`role 必须是 ('A'…'M') 之一，收到 'Z'`）——
    因为 `tasks` 行的 `role` 是受控词表。所以在测试里临时补上那两处登记：

    - `schema.ROLES`（数据面的角色词表，禁改区）
    - `tools.TOOL_ROLES`（工具层的角色词表，禁改区）

    补完之后端到端跑通 ⇒ "新建一个 agent = 一个模块 + 两处登记（都要人审）"。
    这两处要人审不是麻烦，而是"角色即权限面"的应有之义。
    """
    monkeypatch.setattr(schema, "ROLES", (*schema.ROLES, "Z"))
    monkeypatch.setattr(tools_pkg, "TOOL_ROLES", (*TOOL_ROLES, "Z"))
    reg = temp_registry(m_edges=("Z",))
    with tempfile.TemporaryDirectory(prefix="probe-role-") as td:
        st, _ws_path = _ws(td)
        probe = ProbeAgent(st, tag="from-backend")
        cond = Conductor(st, registry={"Z": ("object", probe)}, specs=reg)
        res = cond.summon("Z", "peek", input_key="probe-1")
        assert res.status == "done", res
        assert probe.calls, "召唤没有真的落到实现上"
        assert [r for r in st.rows("tasks") if r.get("task_id") == res.task_id], \
            "召唤应当落一行 tasks"
        assert not [i for i in verify_all(st).issues
                    if i.code in ("task_without_input_key", "dangling_usage_task")
                    and getattr(i, "row_id", "") == res.task_id], "审计挑了这次召唤的毛病"


# ---------------------------------------------------------------- ③ 被审计


def test_the_audit_passes_for_the_temp_role_and_catches_broken_specs() -> None:
    """审计：临时角色通过；七类"写坏的声明"各自被点名。"""
    assert audit_registry(temp_registry()) == []
    cases = {
        "role 对不上": probe_spec(role="Y"),
        "边指向不存在的角色": probe_spec(edges=("不存在的角色",)),
        "peers 指向不存在的角色": probe_spec(peers=("Q",)),
        "needs 写错名字": probe_spec(needs=("provider",)),
        "没有职责": probe_spec(brief=AgentBrief(duty="", boundary=())),
        "没有 build": probe_spec(build=None),
        "handler 不存在": probe_spec(
            class_path="agentflow.agent_a:AgentA",
            actions=(dataclasses.replace(probe_spec().actions[0], handler_name="不存在的方法"),)),
    }
    for label, spec in cases.items():
        reg = AgentRegistry()
        for role in builtin_registry().roles():
            if role != "Z":
                reg.add(builtin_registry().get(role))
        reg.add(spec)
        assert audit_registry(reg), f"这一类坏声明没被抓住：{label}"


# ---------------------------------------------------------------- ④ 真实代价：工具层的那一次登记


def test_the_tool_layer_names_the_one_missing_registration() -> None:
    """工具层会点名缺的那一次登记；补上它（在测试里临时补）工具面就出现了。

    两条路径要分清（实测出来的口径）：
    - `build_for_role("Z")`：装全表再按角色过滤，所以它不报错、只是一个工具都没有
      （没有哪个工具的 roles 里有 Z）；
    - `build_registry(roles=("Z",))`：把 Z 当装配角色传下去时，`fs_tools` / `table_tools`
      会把 Z 注进声明 —— 那一刻 `ToolRegistry.register` 按 `TOOL_ROLES` 校验并点名拒绝。

    这正是 goal ④ 要的形态：漏登记不会被静默吞掉，而由判据点名。
    """
    with tempfile.TemporaryDirectory(prefix="probe-role-") as td:
        st, ws = _ws(td)
        assert build_for_role("Z", store=st, workspace_root=ws).registry.names() == []

        built = build_registry(store=st, workspace_root=ws, roles=("Z",))
        skipped = {s["module"]: s["error"] for s in built.skipped}
        assert {"table_tools", "fs_tools"} <= set(skipped), skipped
        joined = " ".join(skipped.values())
        assert "TOOL_ROLES" in joined and "'Z'" in joined, joined


def test_registering_the_role_in_the_tool_vocabulary_is_the_whole_cost(monkeypatch) -> None:
    """补上 `TOOL_ROLES` 里的那一次登记 ⇒ 临时角色拿到"注入式角色"的工具面。

    `TOOL_ROLES` 在 `tools/__init__.py`（FC-27 禁改区）—— 所以这一次登记需要人审，
    这正是"角色即权限面"的应有之义（`monkeypatch` 只在这个用例里生效，不改生产文件）。
    """
    monkeypatch.setattr(tools_pkg, "TOOL_ROLES", (*TOOL_ROLES, "Z"))
    with tempfile.TemporaryDirectory(prefix="probe-role-") as td:
        st, ws = _ws(td)
        built = build_registry(store=st, workspace_root=ws, roles=("Z",))
        assert not built.skipped, built.skipped
        names = built.registry.for_role("Z")
        got = sorted(s.name for s in names)
        assert [n for n in got if n.startswith(("fs.", "table."))], got
        assert not [n for n in got if n.startswith(("search.", "ocr.", "conductor."))], got


def test_the_proof_touched_no_production_declaration() -> None:
    """反真空/边界：Z 不在内置注册表里，也不在工具层的角色表里。"""
    assert "Z" not in builtin_registry().roles()
    assert "Z" not in TOOL_ROLES
    with pytest.raises(KeyError):
        builtin_registry().get("Z")
