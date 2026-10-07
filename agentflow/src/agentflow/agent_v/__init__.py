# -*- coding: utf-8 -*-
"""智能体 V：证明级验证（只读）。

H 是稿件级正式审查（五元位第 5 位），V 是证明级验证（第 3 位）——
两个粒度、两套凭据、两个台账。把"证明级"塞进 H 会把 H 的语义撑宽，
而"一个人身上的两个判断面"在读数上分不开（`draft/39` §3.21 五 的用户定案）。

"V 只读"由三件事共同保证（缺一条就只剩口号）：

1. 声明：`specs/v.py` 的 `read_only=True` / `write_set=frozenset()`（FC-27 禁改区）；
2. 工具面：`tools.READ_ONLY_ROLES` 含 `"V"` ⇒ `ToolRegistry.for_role` 结构性剥掉
   一切 `side_effect` 为写的工具（`tools/base._role_surface`）；
3. 接口：拼审校提示词的 `verifications.cold_start_prompt` 只收字符串，
   没有任何 store / conductor / registry 句柄参数（I12 的冷启动是结构性质）。

它唯一的产物是 `<工作区>/verifications/<命题号>.jsonl` 里的一行 —— 一个文件，
不是一张表，所以 `WRITE_SETS["V"]` 是空集。
"""
from __future__ import annotations

from ..specs.v import SPEC
from .core import (DEFAULT_VERIFIER, AgentV, VerificationWiringError, _read_only_facts,
                   default_llm, selftest, set_default_llm)

__all__ = ["AgentV", "SPEC", "VerificationWiringError", "DEFAULT_VERIFIER",
           "_read_only_facts", "default_llm", "selftest", "set_default_llm"]
