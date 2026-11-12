# -*- coding: utf-8 -*-
"""角色 L 的动作 `check_formal`：E 那条路的同一个实现 + 前置自检闸。

为什么是继承而不是复制：E 的 `AgentE.check_formal` 里有四件必须逐字一致的事 ——
路径守卫（`self._resolve` + `ExperimentError` → `path_outside_workspace`）、受控拒绝
的九键形状、理由的收口与透传（`_FORMAL_REASON_BY_TOOL_REASON` + `verifier_status`）、
把 `checker_name` 翻译给工具层。复制一份就等于把四件事各写两遍，而它们分家的症状
是"E 说 verified、L 说 decl_unregistered"这种没人会去查的漂移。闸门放在最前，是因为
"这台机器上的 lean 到底是不是检查器"必须先回答 —— 不回答就去问它，得到的每一条结论
都建在一个没验过的假设上（`leantoolchain` 的模块 docstring 有逐字论证）。

闸门之后逐字走 E：自检 `usable` 时行为与 E 逐字相同；不是 `usable` 时不去问检查器，
返回形状固定的 dict（`checked=False` / `verified=None` / `status="unknown"` /
`reason=<自检理由码>`），原因压成一行，不抛栈、不重试。两种情况都不改 E 那一侧的
一个字节 —— 继承是只读关系。

形参名为什么是 `declaration_name`：E 的方法形参叫 `name`（它不经
`ToolRegistry.call`，所以撞不上那个第一个形参）。L 的动作同时挂在工具面上
（`formal.check_formal`），而工具层声明的属性名就是 handler 的形参名 ⇒ 叫 `name`
会永远无法按名传入（`verify_tools` 的 `C3` 登记过这一跤）。所以 L 从第一行起就叫
`declaration_name`，动作面与工具面因此没有"名字对不上"的接缝要登记。
"""
from __future__ import annotations

from typing import Any

from ..agent_e.check_formal import _CheckFormal as _ECheckFormal
from ._support import one_line


class _CheckFormalL(_ECheckFormal):
    """E 的 `check_formal` + 一道自检闸（见模块 docstring）。"""

    def check_formal(
        self,
        claim: str,
        *,
        script_path: str | None = None,
        source: str | None = None,
        declaration_name: str | None = None,
        imports: Any = None,
        timeout_sec: float | None = None,
    ) -> dict:
        """把源码交给检查器真跑一次；自检不是 usable 时如实回 unknown。

        返回的键集合在每一条分支上都成立：E 的九个（`checked` / `verified` /
        `claim` / `reason` / `detail` / `verifier_output` / `missing_imports` /
        `verifier_status` / `exit_code`）加 L 的四格（`status` / `problems` /
        `lean` / `lean_path`）。
        """
        state, why = self._lean_selfcheck()
        if state != "usable":
            return self._refusal(claim, self._selfcheck_reason(state), one_line(why))
        # `super().check_formal` 每条分支交出的都是新建的 dict（E 那边 `data =
        # dict(res.data or {})` / `_formal_refusal` 现造的键表），而 `_finalize`
        # 自己会 `dict(data)` 再改 `out` —— 这里不再多拷一层。
        data = super().check_formal(
            claim,
            script_path=script_path,
            source=source,
            # 本方法的形参叫 declaration_name，E 的方法叫 name：这一格是两套名字
            # 之间唯一的映射点（与 E 把 name 翻成 checker_name 的那一处同族）。
            name=declaration_name,
            imports=imports,
            timeout_sec=timeout_sec,
        )
        return self._finalize(data)
