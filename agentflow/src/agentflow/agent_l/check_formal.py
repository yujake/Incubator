# -*- coding: utf-8 -*-
"""角色 L 的动作 `check_formal`：E 那条路的同一个实现 + 前置自检闸。

## 为什么是继承而不是复制

E 的 `AgentE.check_formal`（`agent_e/check_formal.py`）里有四件必须逐字一致的事：

1. 路径守卫（`self._resolve` + `ExperimentError` -> `path_outside_workspace`）；
2. 受控拒绝的形状（`_formal_refusal` 的九个键，`E-12(a)` 那条键集合契约）；
3. 理由的收口与透传（`_FORMAL_REASON_BY_TOOL_REASON` + `verifier_status`，
   `G-24①`：收口之后仍然拿得到工具层原样报的值）；
4. 把 `checker_name` 这一格翻译给工具层（`C3` 那处撞名的唯一映射点）。

复制一份就等于把四件事各写两遍，而它们分家的症状是"E 说 verified、L 说
decl_unregistered"这种没人会去查的漂移。所以 L 的 `_CheckFormalL` 直接继承
E 的那个混入，只在前面加一道自检闸：闸门放在最前，是因为"这台机器上的
lean 到底是不是检查器"必须先回答 —— 不回答就去问它，得到的每一条结论都建在
一个没验过的假设上（`leantoolchain` 的模块 docstring 逐字论证过这件事）。

## 闸门之后逐字走 E：这带来了什么

- 自检 `usable` 时，L 的行为与 E 的 `check_formal` 逐字相同（同一份代码）；
- 自检不是 `usable` 时，L 不去问检查器：返回一个形状固定的 dict
  （`checked=False, verified=None, status="unknown", reason=<自检理由码>`），
  原因压成一行。不抛栈、不重试；
- 两种情况都不改 E 那一侧的一个字节 —— 继承是只读关系。

## 形参名为什么是 `declaration_name`

E 的方法形参叫 `name`（它不经 `ToolRegistry.call`，所以撞不上那个第一个形参）。
L 的动作同时挂在工具面上（`formal.check_formal`），而工具层声明的属性名就是
`Handler` 的形参名 ⇒ 叫 `name` 会永远无法按名传入（`verify_tools` 的 `C3` 逐字
登记过这一跤）。所以 L 从第一行起就叫 `declaration_name`，动作面与工具面因此
没有"名字对不上"的接缝要登记。
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
        data = dict(super().check_formal(
            claim,
            script_path=script_path,
            source=source,
            # 本方法的形参叫 declaration_name，E 的方法叫 name：这一格是两套名字
            # 之间唯一的映射点（与 E 把 name 翻成 checker_name 的那一处同族）。
            name=declaration_name,
            imports=imports,
            timeout_sec=timeout_sec,
        ))
        return self._finalize(data)
