"""E 收得下的三种计算法：`numeric` / `symbolic` / `exhaustive_search`。

`formal` 不在这里：形式化归 L（`formal.record` 仍写 `method="formal"` 的 `experiments` 行，
`schema.EXPERIMENT_METHODS` 因此仍保留四个值）。本常量只回答"模型可见的 `method.enum`
该广告哪三种"，是 `specs/e.py` 与 `tools/verify_tools.py`（`verify.run_experiment`）的共同来源。

放中立模块的原因：那两个落点读同一个常量，而 `specs/e.py` 从 `agent_e._support` 取它会成环
（`_support` 末尾反向 `from ..specs.e import SPEC`）。判据见
`tests/test_e_method_enum_does_not_advertise_formal.py::test_either_import_order_works`。
"""

COMPUTATIONAL_METHODS = ("numeric", "symbolic", "exhaustive_search")
