"""角色 D 的动作 `register_conjecture`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`tests/test_agent_split_is_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, EvidenceError

class _RegisterConjecture:
    def register_conjecture(self, **params: Any) -> dict:
        """登记或更新一条猜想（转发 `conjecture.register_conjecture`；依据 `draft/31` P7 第 4 张表）。

        ## 为什么失败要抛，而不是像 `_call` 那样返回 `None`

        D 的读路径（`_call`）把失败吃掉是合理的：一次查不到不该中断整轮研究，
        原因落在 `self.last_tool_errors` 里。但写路径不一样：返回 `None` 会让
        `Conductor._end_from_payload` 记成 `outcome="ok"` 而 `payload=None` ——
        台账上看起来"这一步做成了"，而库里一行都没有。这正是本项目最忌的形态
        （"假装跑通并返回空"）。所以这里把失败原样抛出去，让终态是 `failed`。

        ## 三态

        `conjecture_id` 给了但库里没有 ⇒ 抛（不许静默新建一条重复的猜想）。
        `None` = 调用方没提这个字段 ⇒ 保留库里已有的值（更新语义见 `conjecture_tools`）。
        """
        res = self.tools.call("conjecture.register_conjecture", **params)
        if not res.ok:
            # 失败同时进 `last_tool_errors`（报告里的审计一节读它）与异常，
            # 两条路都要：前者让"这一轮 D 犯过什么错"可查，后者保证终态是 failed。
            self.last_tool_errors.append(
                {"tool": "conjecture.register_conjecture", "error": res.error,
                 "kind": res.meta.get("kind")}
            )
            raise EvidenceError(
                f"conjecture.register_conjecture 失败（kind={res.meta.get('kind')}）：{res.error}"
            )
        return dict(res.data)
