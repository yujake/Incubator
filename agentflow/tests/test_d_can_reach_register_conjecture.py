# -*- coding: utf-8 -*-
"""判据 ④：模型驱动模式下 D 够得着 `register_conjecture`（工具面里真有它）。

## 这一格的历史（两次走法，读数都留着）

改前（"已映射"这句话是假的）：`capabilities.unmapped_actions()` 判一个动作"已对上"时
读的是声明那一侧 —— `_TOOL_MODULES` 除了 `tools._MODULES` 还多读 `_TOOL_MODULE_EXTRAS`
（当年只有 `conjecture_tools`）。于是 `D.register_conjecture` 被算成"已对上"：名字对上了
`conjecture.register_conjecture` 的声明，而 `build_registry` 根本装配不到那个模块 ⇒ 工具面
上没有它 ⇒ `agent_loop._own_actions_to_expose` 也不注入 `own.register_conjecture` ⇒
模型按手册喊短名 `register_conjecture`，拿到的是"并列候选（0 个）"。

上一版走 (b)：让"已映射"只认 `tools._MODULES` 里真装配过的组，于是这条动作诚实落进
`_KNOWN_UNMATCHED_ACTIONS`，由循环把它包成 `own.register_conjecture` 注入这一趟。
当年不选 (a) 的理由是"不重冻 golden"这个硬边界。

现在走 (a)（2026-10-27，`R-BE4` 的 D1 Phase A，业主批准）：`conjecture_tools` 进了
`tools._MODULES` ⇒ `conjecture.register_conjecture` 就在工具面上，D 直接调它，不再需要
`own.*` 那一层包装。连带的三处登记一起退场（`_TOOL_MODULE_EXTRAS` /
`_KNOWN_UNMATCHED_ACTIONS` / `ACTION_ONLY_PARAMS` 里那三条），`tool_surface_snapshot.json`
的 `summary.count` 由 117 重冻成 118。

## 判据（口径随走法换，但问的问题没换：D 够不够得着）

1. `("D", "register_conjecture")` 不在 `unmapped_actions()` 里 —— 它现在"对得上"，
   而"对得上"必须是装配面上的对得上（走 (a) 时这一条与第 2 条互为反真空：
   把 `conjecture_tools` 从 `_MODULES` 撤掉，第 2 条红；把它留在 `_KNOWN_UNMATCHED_ACTIONS`
   里，第 1 条红）。
2. `build_registry` 的共享工具面上真有 `conjecture.register_conjecture`，且
   只有 D 的角色面里有它（`roles=("D",)`：其余十格一个字节都不该动）。
3. 广告面（`build_tool_face`，本仓广告工具面的唯一入口）里也真有它：只进注册表、不进
   广告面等于"模型看不见"。
4. 真调一次走得通（内层确定性实现被调到）。
5. 反真空：D 这一趟不再注入 `own.register_conjecture`（已对上的动作不重复包一层，
   否则同一件事有两个入口）；而另一个真已对上的动作同样不被注入。
"""
from __future__ import annotations

import pathlib

from agentflow import capabilities as C
from agentflow import schema as S
from agentflow.agent_loop import LlmBackend
from agentflow.conductor import LocalBackend
from agentflow.llmseam import build_tool_face
from agentflow.store import Store
from agentflow.tools import build_registry

_TOOL = "conjecture.register_conjecture"
_OWN = "own.register_conjecture"


class _StubD:
    """D 的确定性替身：只实现 `register_conjecture`（这一条判的是"那条路通不通"）。"""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.calls: list[dict] = []

    def register_conjecture(self, **params) -> dict:
        """最小形态：记下参数并回一个号（真实现里这一步写 `conjectures` 一行）。"""
        self.calls.append(dict(params))
        return {"ok": True, "conjecture_id": S.format_id(1), "params": dict(params)}


def _world(tmp_path: pathlib.Path):
    """一个工作区 + 一个"只派活、不点动作"的模型驱动后端（真机 S2 口径的那一趟）。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    stub = _StubD(st)
    inner = LocalBackend({"D": ("object", stub)})
    inner.store = st
    backend = LlmBackend(
        inner=inner,
        # 只点角色、不点动作（`tasks.action=""` 那一档）：注入由 `_own_actions_to_expose` 决定
        loops={("D", ""): {"max_steps": 3}},
        session_root=ws, store=st, sid="t", workspace_root=str(ws),
        registry=build_registry(store=st, workspace_root=ws).registry,
    )
    return st, stub, backend


def test_d_can_reach_register_conjecture_in_model_driven_mode(
    tmp_path: pathlib.Path,
) -> None:
    """④ 模型驱动模式下 D 能直接调到 `conjecture.register_conjecture`。

    改前红（两次都红，红的理由不同）：
    - 最初：`("D","register_conjecture")` 被算成"已对上"，而工具面上没有它 ⇒ 两端都没有；
    - 走 (a) 之前：共享工具面上没有这件工具，只靠 `own.register_conjecture` 注入。
    """
    st, stub, backend = _world(tmp_path)

    assert ("D", "register_conjecture") not in C.unmapped_actions(), (
        "`D.register_conjecture` 又被算成『没有工具层』了：它对应的 "
        f"`{_TOOL}` 已经进了 `tools._MODULES` ⇒ 装配面上有它，"
        "这一格不该再落进 `_KNOWN_UNMATCHED_ACTIONS`")

    base = build_registry(store=st, workspace_root=str(st.root)).registry
    assert _TOOL in set(base.names()), (
        f"共享工具面上没有 `{_TOOL}` ⇒ `conjecture_tools` 没被装配（`_MODULES` 又少了它）")

    # 只有 D 的角色面里有它：`roles=("D",)` ⇒ 其余十格一件不多（权限面不许被顺手放宽）
    others = [role for role in tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)
              if role != "D" and _TOOL in {s.name for s in base.for_role(role)}]
    assert not others, f"这些角色的面里也出现了 `{_TOOL}`（它的 roles 只该有 D）：{others}"

    # 广告面：本仓广告工具面的唯一入口
    face = build_tool_face("D", base)
    advertised = {value.split(":", 1)[1] if value.startswith("tool:") else value
                  for value in face.names.values()}
    assert _TOOL in advertised, (
        f"广告面上没有 `{_TOOL}` ⇒ 模型看不见它：{sorted(advertised)[:8]}…")

    # 真调一次（参数取自这条动作的声明面）：走的是内层确定性实现
    # `status="needs_evidence"` + `notes` 是刻意的：`proposed` 必须带 `testable`（可检验形式），
    # 而这一条判的是"这条路通不通"，不是"猜想的九条单行判据对不对"。
    res = base.call(_TOOL, role="D", statement="谱落在 [-m, m] 内。", origin="own_result",
                    status="needs_evidence", notes="判据只验接线：这一条还没有可检验形式")
    assert res.ok is True, (res.error, res.meta)
    # 走的已经是真 handler（不再是 `own.*` 包的那层替身）：一行猜想真的落库了。
    # 这正是走 (a) 与走 (b) 的读数差别 —— (b) 那条路只调用内层替身，碰不到 `conjectures` 表。
    assert isinstance(res.data, dict) and res.data.get("conjecture_id"), res.data
    assert len(st.rows("conjectures")) == 1, st.rows("conjectures")
    assert stub.calls == [], (
        "内层替身被调到了 —— 说明这次走的仍是 `own.*` 那条注入路，而不是装配面上的真工具")

    # 反真空：已对上的动作不再被包成 own.*（同一件事不许有两个入口）
    assert _OWN not in backend._own_actions_to_expose("D", action=""), (
        f"`{_OWN}` 仍被注入 —— 那说明 `D.register_conjecture` 又被算成『没有工具层』了")


def test_the_injection_list_still_drives_the_remaining_unmatched_actions(
    tmp_path: pathlib.Path,
) -> None:
    """④ 反真空的另一半：注入清单仍由 `_KNOWN_UNMATCHED_ACTIONS` 驱动，不是"每件都塞"。

    两问：
    1. D 的注入清单里确实还有别的动作（否则"注入清单还在工作"这句话没有对象）；
    2. 一个真已对上的动作不被重复注入（换一个真有工具层的角色来证）。
    """
    st, _stub, backend = _world(tmp_path)

    exposed = sorted(backend._own_actions_to_expose("D", action=""))
    expected = sorted(a for r, a in C.unmapped_actions() if r == "D")
    assert exposed == expected, (exposed, expected)
    assert expected, (
        "D 名下一条『没有工具层』的动作都没有了 ⇒ 这一条反真空没有对象"
        "（真要变成这样，说明整张 `_KNOWN_UNMATCHED_ACTIONS` 都被清空了）")

    compared = [where for where, _tool in C.two_layer_reconciliation()["compared"]]
    assert compared, "对账面上一条已对上的动作都没有 ⇒ 这条反真空没有对象"
    role, action = compared[0].split(".", 1)
    assert action not in backend._own_actions_to_expose(role, action=""), (
        f"{role}.{action} 已经对上了工具，却被重复包成 own.*")
