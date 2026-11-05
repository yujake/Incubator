"""E 收得下的三种计算法：`numeric` / `symbolic` / `exhaustive_search`。

`formal` 不在这个表里 —— 形式化归 L（`formal.record` 仍写 `method="formal"` 的
`experiments` 行，`schema.EXPERIMENT_METHODS` 因此仍保留四个值）。本常量只回答
"模型可见的 `method.enum` 该广告哪三种"，是 E 的动作面（`specs/e.py`）与工具面
（`tools/verify_tools.py` 的 `verify.run_experiment`）的同一份来源。

为什么是一个中立模块（不属于任何 `agent_*` 包）：那两个落点必须读同一个常量，
而 `specs/e.py` 从 `agent_e._support` 取它会成环 —— `_support` 末尾反向
`from ..specs.e import SPEC`，先导入 `specs.e` 时 `SPEC` 还没定义。常量先落地到
本模块，两条导入方向才各自成立（判据见
`tests/test_e_method_enum_does_not_advertise_formal.py::test_either_import_order_works`）。
"""

COMPUTATIONAL_METHODS = ("numeric", "symbolic", "exhaustive_search")
