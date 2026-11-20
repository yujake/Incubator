# -*- coding: utf-8 -*-
"""秘书的装配口：造一名 `Secretary` 只经这一处（从混入模块来的那一侧）。

我保证哪条不变式：混入模块与组装层之间只有一个方向 —— `secretary.py` 单向 import 本模块
并在这里登记造秘书的那一个入口；本模块不 import 任何秘书模块（连 `secretary.py` 都不 import），
所以「组装层 -> 混入层」不会掉头成环。

## 为什么需要它（不是形式主义）

刀3–刀6 把 `class Secretary` 的 193 个方法搬进混入类，混入类仍然要造"下一跳秘书"：
`_peer_secretary`（转发链）与 `concept_identity_gate`（概念闸）各有一处 `Secretary(...)`。
混入模块里写 `from .secretary import Secretary`，就是混入层反向 import 组装层；而组装层为了
再导出又必须 import 混入模块 —— 两个 import 同时成立，`import agentflow.secretary` 当场
ImportError。把 import 塞进函数体可以绕过环，但那会改 `ast_sha`（逐字等价的判据当场红），
而且把依赖方向藏进运行时。

## 判据钉的是什么

`tests/test_secretary_has_one_assembly_port.py`：混入模块里 `Secretary(` 出现 0 次、
`from .secretary import` 出现 0 次；全仓造秘书的入口只剩 `secretary.py` 的组装函数与本模块
这一处；反真空用例把 `_FACTORY` 摘掉之后 `_peer_secretary` 必须如实报"造不出"，而不是
静默返回一个能用的秘书。

## 三态

没接上时抛错而不是返回 `None`：装配层没 import 就调它，是装配顺序错了（本仓的
`secretary.py` 在模块级登记），把它折成"没有秘书"会让调用方读到一条假的业务读数。
"""
from __future__ import annotations

from typing import Any

#: 造一名秘书的那一个入口（由 `secretary.py` 在类定义之后登记；本模块自己不认识 `Secretary`）。
_FACTORY: Any = None


def bind_factory(factory: Any) -> None:
    """装配层登记造秘书的入口（`secretary.py` 模块级调一次，参数就是那个类）。"""
    global _FACTORY
    _FACTORY = factory


def new_secretary(*args: Any, **kw: Any) -> Any:
    """造一名秘书：参数原样交给装配层登记的那一个入口。

    谁用这一处：`_peer_secretary`（转发链的下一跳）与 `concept_identity_gate`（概念闸的
    确定性判定）。两处都只是"需要一名秘书来做一件事"，不关心它是谁组装的。
    """
    if _FACTORY is None:
        raise RuntimeError(
            "装配口还没接上：本模块要由 `agentflow.secretary` 在类定义之后调用 "
            "`bind_factory(Secretary)`；在那之前造秘书是装配顺序错了，不是业务读数")
    return _FACTORY(*args, **kw)
