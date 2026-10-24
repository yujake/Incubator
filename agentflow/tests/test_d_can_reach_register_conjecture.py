# -*- coding: utf-8 -*-
"""判据 ④：模型驱动模式下 D 够得着 `register_conjecture`（工具面里真有它）。

## 改前是什么形态（"已映射"这句话是假的）

`capabilities.unmapped_actions()` 判一个动作"已对上"时读的是声明那一侧：`_TOOL_MODULES`
里除了 `tools._MODULES` 还多读了 `_TOOL_MODULE_EXTRAS`（今天只有 `conjecture_tools`）。
于是 `D.register_conjecture` 被算成"已对上"：名字对上了
`conjecture.register_conjecture` 的声明，而 `build_registry` 根本装配不到那个模块
⇒ 工具面上没有它 ⇒ `agent_loop._own_actions_to_expose` 也不注入
`own.register_conjecture` ⇒ 模型按手册喊短名 `register_conjecture`，拿到的拒信是
"并列候选（0 个）"。

## 走的是哪一条（二选一里的 (b)）

(b) 让"已映射"只认 `tools._MODULES` 里真装配过的组，于是这条动作诚实地落进
`_KNOWN_UNMATCHED_ACTIONS`，由循环把它包成 `own.register_conjecture` 注入这一趟。
选它而不是 (a)（把 `conjecture_tools` 加进 `tools._MODULES`）的理由有两条，都是结构性的：

1. (a) 会改变广告出去的整份工具面（`tests/golden/tool_surface_snapshot.json` 里
   每个角色的工具清单都会多一件），而"不重冻 golden"是本批的硬边界；
2. (a) 还要把那个模块的装配依赖（`roles` / store / 注册入口）一起接进 `build_registry`，
   改动的面比这条判据大得多 —— 而这一格要的只是"D 够得着自己那个动作"。

## 判据

1. `("D", "register_conjecture")` 在 `unmapped_actions()` 里（判据说的那一格）；
2. 模型驱动那一趟的注册表里真有 `own.register_conjecture`，且广告名那一侧也有它
   （`build_tool_face` 是本仓广告工具面的唯一入口 —— 只进注册表没进广告面等于没有）；
3. 反真空：共享工具面（`build_registry`）里没有 `conjecture.register_conjecture`
   （这就是走 (b) 的代价与读数的分界：它诚实地是"没装配"，而不是"装配了但没广告"），
   而一个真的已对上的 D 动作不会被重复注入（注入清单由 `_KNOWN_UNMATCHED_ACTIONS` 驱动，
   不是"每个动作都塞一件"）。
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


def test_d_can_reach_register_conjecture_in_model_driven_mode(tmp_path: pathlib.Path) -> None:
    """④ 模型驱动模式下 D 调 `register_conjecture` ⇒ `own.register_conjecture` 真在广告面上。

    改前红：`("D", "register_conjecture")` 不在 `unmapped_actions()` 里
    （它被算成"已对上"），于是注入清单里没有它，`own.register_conjecture`
    既不进注册表、也不进广告面 —— 模型喊这个短名只拿到"并列候选（0 个）"。
    """
    st, stub, backend = _world(tmp_path)

    assert ("D", "register_conjecture") in C.unmapped_actions(), (
        "`D.register_conjecture` 又被算成'已对上'了：它对应的工具不在 `tools._MODULES` 里，"
        "工具面上没有它 ⇒ 模型驱动模式下 D 会再拿到'并列候选 0 个'")

    base = build_registry(store=st, workspace_root=str(st.root)).registry
    scoped = backend._registry_with_own_action(base, role="D", action="")
    names = set(scoped.names())
    assert "own.register_conjecture" in names, (
        f"这一趟的注册表里没有 `own.register_conjecture`：{sorted(names)[:8]}…")
    # 广告面（原生工具调用的唯一入口）里也必须有它：只进注册表、不进广告面等于"模型看不见"
    face = build_tool_face("D", scoped)
    advertised = {value.split(":", 1)[1] if value.startswith("tool:") else value
                  for value in face.names.values()}
    assert "own.register_conjecture" in advertised, sorted(advertised)[:8]

    # 真调一次（参数取自这条动作的声明面）：走的是内层确定性实现
    res = scoped.call("own.register_conjecture", role="D",
                      statement="谱落在 [-m, m] 内。", origin="own_result")
    assert res.ok is True, (res.error, res.meta)
    assert stub.calls and stub.calls[0].get("statement") == "谱落在 [-m, m] 内。", stub.calls


def test_the_injection_list_is_driven_by_the_unmatched_registry(tmp_path: pathlib.Path) -> None:
    """④ 反真空：共享工具面里没有 `conjecture.register_conjecture`；已对上的动作不重复注入。

    前半句是"走 (b) 而没走 (a)"的读数（选了另一条路这里会红）；
    后半句防的是"为了让这条绿，把每个动作都包一件 own.*"—— 那会让工具面凭空长大，
    而"已对上"的动作本来就有自己的工具。
    """
    st, _stub, backend = _world(tmp_path)
    base = build_registry(store=st, workspace_root=str(st.root)).registry
    assert "conjecture.register_conjecture" not in set(base.names()), (
        "共享工具面里出现了 `conjecture.register_conjecture` ⇒ 那个模块被 `tools._MODULES`"
        "装配进来了（那是另一条路：它会改变整份广告面与 golden 快照）")

    # D 这一趟的注入清单必须与"没有工具层的那些动作"逐条相同（不多不少）
    exposed = sorted(backend._own_actions_to_expose("D", action=""))
    expected = sorted(a for r, a in C.unmapped_actions() if r == "D")
    assert exposed == expected, (exposed, expected)

    # 已对上的动作不许被重复注入（换一个真有工具层的角色来证：注入清单由登记表驱动，
    # 不是"每个动作都塞一件 own.*"）
    compared = [where for where, _tool in C.two_layer_reconciliation()["compared"]]
    assert compared, "对账面上一条已对上的动作都没有 ⇒ 这条反真空没有对象"
    role, action = compared[0].split(".", 1)
    assert action not in backend._own_actions_to_expose(role, action=""), (
        f"{role}.{action} 已经对上了工具，却被重复包成 own.*")
