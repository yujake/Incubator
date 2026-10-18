# -*- coding: utf-8 -*-
"""「派活不点动作」的判据（业主口径 2026-10-16，S1/S2）。

口径原话（两段，第二段是追加的）：

> 「M 只是个派活的，对所有角色都一样，只根据它们的能力范围派活，**不指定能力**。
> M 能看到的只是各角色描述，看不到具体的工具箱与动作，但可在角色描述中暗示它各角色能干什么。」
> 「对于其它智能体派子智能体，能看到的应该是一样的（就是描述）。」

落地形态：
  * 提示词那一侧（伙伴表、画像文件、`conductor.role_spec`）只给**描述**；
  * 派活那一侧 `summon` / `summon_many` 允许**不给 `action`** —— 那一趟由被派角色
    **跑自己的循环**、按自己的手册与工具面选动作；此时 `task` 必填。

这一份守三件事（含负控与反真空）：
  1. **边照拦**：空动作不是"绕过策略"的通行证 —— `M → F` 仍然 `forbidden_edge`；
  2. **schema 不许再要求动作**：`summon` / `summon_many` 的必填里不许有 `action`
     （否则模型根本写不出"只派活"那种调用）；
  3. **后端路由**：空动作**不许**落到内层处理器（那等于替它选了一个不存在的动作），
     必须走角色自己的循环。
"""
from __future__ import annotations

from typing import Any

import pytest

from agentflow import policy as P
from agentflow import schema as S


# ---------------------------------------------------------------- 1) 边照拦


def _edge_refusal(frm: str, to: str, action: str) -> str:
    """跑一遍策略门，返回理由码（放行时返回空串）。"""
    d = P.Decision(frm=frm, to=to, action=action)
    r = P.check(P.Policy(), d)
    return "" if r is None else str(r.reason)


def test_a_blank_action_still_checks_the_edge() -> None:
    """空动作**不是**绕过策略的通行证：该拦的边照拦。

    若这条破了：M 只要不写动作就能派 F/V —— 2026-10-10 那条"主控不许直接控制 F/V"
    的裁定会被一个空字符串整个架空，而**没有任何读数会报出来**。

    ⚠️ 2026-10-16 实测更正：**`B` 在 M 的出边里**（当时 `ALLOWED_EDGES['M']`
    = `['A','B','C','D','E','G','H']`，7 条）；**2026-10-18 业主「给 M 开 V 出边」之后
    `V` 也在里面**（8 条）。而 `partners_lines` 的注释与 `visible_partners` 的 docstring
    写着"主控不许直接控制 **B** / F / V" —— **那两句是旧读数**（边表才是权威）。
    这条判据按边表写：**只剩 F 拦**（V 现在是直接边，拿它当"该拦"的例子会变成假红）。
    """
    for to in ("F",):
        assert _edge_refusal("M", to, "") == "forbidden_edge", (
            f"M 用空动作派 {to} 竟然没被拦 —— 空动作成了越权的后门"
        )
    # 直接边 + 空动作 ⇒ 放行（这才是这一格要支持的东西）
    assert _edge_refusal("M", "D", "") == "", "M 派 D 一件活（不点动作）应当放行"
    assert _edge_refusal("M", "B", "") == "", "B 在 M 的出边里（实测 8 条含 B）"
    assert _edge_refusal("M", "V", "") == "", "V 于 2026-10-18 进了 M 的出边（8 条）"
    assert _edge_refusal("D", "F", "") == "", "D 派 F 一件活（不点动作）应当放行"
    # 反真空：这条判据仍然**真的拦过东西**（不然"succeed 的放行"三行说明不了什么）
    assert _edge_refusal("C", "A", "") == "forbidden_edge", "C 的边是空的，空动作也拦不住"


def test_a_blank_action_is_not_an_unknown_action() -> None:
    """空动作**不许**被判成 `unknown_action`。

    反例形态（改坏时会看到）：`check_action("D", "")` 返回"没有动作 ''" ⇒
    口径落地之后**每一次派活**都会被拒，而报的理由指向"你动作名写错了"，
    与真实原因（"我不该核动作"）完全无关。
    """
    assert _edge_refusal("D", "C", "") == "", "空动作被当成 unknown_action 了"
    assert "unknown_action" not in _edge_refusal("M", "D", "")
    # 负控：**写错的动作名**仍然要吃到 unknown_action（别把这一格改宽了）
    assert _edge_refusal("M", "D", "no_such_action") == "unknown_action"


# ---------------------------------------------------------------- 2) schema 面


def _summon_schemas() -> dict[str, dict]:
    from agentflow.llmseam import META_FUNCTIONS

    found: dict[str, dict] = {}
    for name, shape, schema in META_FUNCTIONS:
        if shape in ("summon", "summon_many"):
            found[shape] = schema
    return found


def test_the_summon_schemas_do_not_require_an_action() -> None:
    """`summon` / `summon_many` 的必填里**不许**有 `action`，且必须有 `task` 那一格。

    这是"模型能不能写出只派活那种调用"的唯一开关：schema 说必填，模型就不会省 ——
    而它一旦写了动作，就回到了"替别人做决定"的老路上。
    """
    schemas = _summon_schemas()
    assert set(schemas) == {"summon", "summon_many"}, schemas.keys()

    one = schemas["summon"]
    # 2026-10-16（口径 S2 **最终形态**，业主原话）：「一致改成 **task 必填，action 不填**」
    # 「**不是忽略 action，是完全不要有填 action 的位置**」⇒ `action` 这一格**整个不在**。
    assert one["required"] == ["role", "task"], one["required"]
    assert "task" in one["properties"], "`summon` 的 schema 里没有 `task`：写不出那件活"
    assert "action" not in one["properties"], (
        "`action` 这一格又回来了 —— 那等于留了一个「替被派者选动作」的位置"
    )

    many = schemas["summon_many"]
    item = many["properties"]["targets"]["items"]
    assert item["required"] == ["role", "task"], item["required"]
    assert "action" not in item["properties"], "`summon_many` 的每个 target 同样不许有 `action`"
    assert "task" in item["properties"], "`summon_many` 的每个 target 也要能写那件活"


# ---------------------------------------------------------------- 3) 后端路由


class _InnerSpy:
    """内层后端探针：**被调用就是失败**。

    为什么用"调用即炸"而不是断言返回值：这一格的契约是"**根本不该走到内层**" ——
    内层是确定性处理器，走它就是"替角色选了一个动作"，而那正是口径要禁的。
    """

    def __init__(self) -> None:
        self.called = 0

    def call(self, role: str, action: str, params: Any, *, token: Any,
             instance: str = "", task_id: str = "") -> Any:  # pragma: no cover - 只用于失败路径
        self.called += 1
        raise AssertionError(f"空动作不该落到内层处理器（role={role}, action={action!r}）")

    def known_roles(self) -> list[str]:
        return []

    def resolve(self, role: str) -> Any:
        return None


def _backend(inner: _InnerSpy, tmp_path, loops: dict | None = None) -> Any:
    from agentflow.agent_loop import LlmBackend

    return LlmBackend(inner=inner, loops=dict(loops or {}), session_root=tmp_path,
                      registry=None, conductor=None, store=None, max_steps=1)


def test_a_blank_action_is_routed_to_the_roles_own_loop(tmp_path) -> None:
    """空动作**不许**落到内层处理器。

    它应该走该角色自己的循环。这里不去把循环跑起来（那要 seam/store/工具面一整套），
    只钉**路由那一步**：内层探针一次都不许被调到。
    循环随后因为没接线而失败 —— 那是**另一件事**，不许与"路由错了"混起来。
    """
    inner = _InnerSpy()
    backend = _backend(inner, tmp_path)
    with pytest.raises(Exception) as exc:
        backend.call("D", "", {"task": "把这条猜想交给 F 攻坚"}, token=None)
    assert inner.called == 0, "空动作被交给了内层处理器（等于替角色选了动作）"
    assert "空动作不该落到内层" not in str(exc.value), str(exc.value)


def test_a_named_action_still_goes_to_the_inner_backend(tmp_path) -> None:
    """负控（反真空）：**给了动作**的召唤照旧走内层处理器 —— 老行为逐字不变。

    没有这一条，上面那条可以被"什么都不走内层"这种改法骗过去。
    """
    inner = _InnerSpy()
    backend = _backend(inner, tmp_path)
    with pytest.raises(AssertionError, match="空动作不该落到内层"):
        backend.call("D", "run_round", {}, token=None)
    assert inner.called == 1, "给了动作却没走内层 —— 老路被改坏了"


def test_the_summon_tool_schema_does_not_require_an_action() -> None:
    """**工具面**那一份也要能写"不点动作"（2026-10-16，T5 第 13 趟的真机读数）。

    为什么单列：循环的 `summon` **形状**与 `llmseam` 的**广告面**都改过之后，
    M 手上那件 **`conductor.summon` 工具**漏了 —— 实测它的 `required` 里还挂着
    `action`、键集合里**根本没有 `task`**。真机现场（`projects/p8m-…`）：M 发了
    2 次空动作、`tasks` 表里 **0 行**（当工具调时这条入口写不出那个形状）。
    """
    from agentflow.store import Store
    from agentflow.tools import build_registry

    import tempfile
    from pathlib import Path

    root = Path(tempfile.mkdtemp(prefix="agentflow-dispatch-tool-"))
    store = Store(root)
    store.init()
    reg = build_registry(store=store, workspace_root=root).registry

    one = reg.get("conductor.summon").params
    assert one["required"] == ["target_role", "task"], one["required"]
    assert "task" in one["properties"], "`conductor.summon` 的键里没有 `task`"
    assert one.get("additionalProperties") is False, "封闭集合那一条不许松"

    many = reg.get("conductor.summon_many").params
    items = many["properties"]["targets"]["items"]
    assert "action" not in (items.get("required") or []), items.get("required")
    assert "task" in items["properties"], "`conductor.summon_many` 的每个 target 也要能写那件活"


def test_the_secretary_prescreen_does_not_alarm_on_a_blank_action(tmp_path) -> None:
    """**秘书预筛不许**因为"没点动作"而报警（2026-10-16，T5 第 12 趟的真机读数）。

    为什么单列：口径在提示词/策略门/后端/形状/schema 都改完之后，**预筛这一层漏了** ——
    `secretary.prescreen` 照旧核"动作表里有没有这个动作"，空动作于是被报成
    "`{角色}` 的动作表里没有 `''`"，那条派活被吞掉。真机现场（`projects/p8l-…`）：
    M **六次**发出 `{"role":"A","action":"","task":…}`，而 `tasks` 表里空动作的行 **= 0**
    —— 六次全死在这一行；M 于是退回"点名动作 + 自己写参数"，那一趟 12 条被拒。

    负控：**真写错的动作名**仍然必须报警（别把这一格改宽了）。
    """
    from agentflow.secretary import Secretary

    sec = Secretary("M", root=tmp_path, store=None)
    blank = sec.prescreen(to="D", action="", params={"task": "把这条猜想交给 F 攻坚"})
    assert not [a for a in blank if "动作表里没有" in a], (
        f"空动作被预筛报警了 —— 那条派活会被吞掉：{blank}"
    )
    # 负控：写错的动作名照旧报警
    wrong = sec.prescreen(to="D", action="no_such_action", params={})
    assert any("动作表里没有" in a for a in wrong), (
        f"写错的动作名竟然没报警（这一格被改宽了）：{wrong}"
    )


def test_the_secretary_wash_lets_a_harmless_delegation_through(tmp_path) -> None:
    """**无害侧**：一条"只给活、不点动作"的派活**过得了秘书的洗格式**（不许被硬拒）。

    为什么必须单列（2026-10-16，真机读数）：`secretary.wash_delegation` 的硬拒那一格
    原本判的是"没有角色 **或** 没有动作"⇒ 任何"只给 `task`"的派活**在写行之前**就被拒，
    而且**一行都不落**。现场：T5 第 12/13 趟 M 六次/两次发出 `{"role":"A","task":…}`，
    而 `tasks` 表里空动作的 **= 0** —— 全死在这一格，连"被拒"的证据都没留下。
    这一格修完**此前没有任何判据**（全仓测试里 `wash_delegation` 零出现）⇒ 补在这里。

    负控：**既没有动作、又没有活**的一条仍必须硬拒（别把这一格改宽了）。
    """
    from agentflow.secretary import Secretary

    sec = Secretary("M", root=tmp_path, store=None)
    ok = sec.wash_delegation("summon", {"role": "D", "task": "把这条猜想交给 F 攻坚"})
    assert not ok.get("refused"), f"无害的派活被洗格式硬拒了：{ok}"
    assert ok.get("checked") is True, ok

    # 负控：空动作 + 没活 ⇒ 仍要硬拒（这一格的本意不许丢）
    bad = sec.wash_delegation("summon", {"role": "D"})
    assert bad.get("refused"), f"既没动作又没活，竟然放过去了：{bad}"

    # 负控（第三档，**按它自己的设计**）：动作名写错**且没有活** ⇒ 洗格式**不硬拒**，
    # 而是把理由记下来交给闸门（"候选不唯一/没有候选 ⇒ 不猜"是这一格刻意的窄）。
    # 我第一版把这里写成"必须硬拒"，实测读数 `{'checked': True, 'washed': False,
    # 'refused': '', 'reason': "动作表里没有 'no_such_action'（没有候选 ⇒ 不猜，留给闸门拒）"}`
    # ⇒ 是我的断言越界了，不是它坏。
    wrong = sec.wash_delegation("summon", {"role": "D", "action": "no_such_action"})
    assert not wrong.get("refused") and wrong.get("checked") is True, wrong
    assert "动作表里没有" in str(wrong.get("reason")), wrong


def test_a_dispatch_without_a_task_is_refused_at_both_entries(tmp_path) -> None:
    """**有害侧的两条**：不点动作**又不给活** ⇒ 两个入口都当场拒。

    口径原话：「一致改成 **task 必填**，action 不填」—— 活是必说的。
    这里只做**行为侧**判据（工具入口的拒绝形态），不去 grep 源码里的字符串 ——
    "某句话还在不在源码里"是机械判据，守不住行为（改个措辞它就红、而行为真坏了它可能还绿）。
    """
    from agentflow.store import Store
    from agentflow.tools import build_registry

    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    reg = build_registry(store=store, workspace_root=root).registry

    # 工具层把拒绝转成 `ok=False` 的结果（**不抛给调用方**，见本仓既有的约定）
    res = reg.call("conductor.summon", role="M", target_role="E")
    assert res.ok is False, f"不点动作又不给活，工具入口竟然放过去了：{res}"
    assert "task" in str(res.error), res.error

    # 台账里不许留下一行"看起来跑过"的记录（拒绝要发生在落行之前）
    assert store.rows("tasks") == [], store.rows("tasks")


def test_schema_roles_are_all_covered_by_the_dispatch_faces() -> None:
    """反真空：这一份判据必须真的评在"全体角色"上（口径说的是"对所有角色都一样"）。

    若哪天角色表长大而这一份判据只覆盖了 M，它就变成了一句关于 M 的话，
    而口径要的是"**其它智能体派子智能体，能看到的应该是一样的**"。
    """
    from agentflow import capabilities as C

    roles = [r for r in S.ROLES]
    assert len(roles) >= 9, f"角色表只有 {roles} —— 先解释清楚再改这条下限"
    checked = 0
    for frm in roles:
        for to in roles:
            if frm == to:
                continue
            _edge_refusal(frm, to, "")
            checked += 1
    assert checked >= 72, f"只评了 {checked} 对（下限 72）"
    # 至少有一条已知的"能派"与一条已知的"不能派"，否则这一格是空的
    assert _edge_refusal("M", "D", "") == ""
    assert _edge_refusal("M", "F", "") == "forbidden_edge"
