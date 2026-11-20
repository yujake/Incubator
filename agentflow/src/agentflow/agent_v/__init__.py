# -*- coding: utf-8 -*-
"""智能体 V：证明级验证（只读）。

H 是稿件级正式审查（五元位第 5 位），V 是证明级验证（第 3 位）—— 两个粒度、两套凭据、
两个台账；把"证明级"塞进 H 会把 H 的语义撑宽，而"一个人身上的两个判断面"在读数上分
不开。

"V 只读"由三件事共同保证（缺一条就只剩口号）：① 声明 —— `specs/v.py` 的
`read_only=True` / `write_set=frozenset()`（FC-27 禁改区）；② 工具面 ——
`tools.READ_ONLY_ROLES` 含 `"V"` ⇒ `ToolRegistry.for_role` 结构性剥掉一切
`side_effect` 为写的工具；③ 接口 —— 拼审校提示词的
`verifications.cold_start_prompt` 只收字符串，没有 store / conductor / registry 句柄
参数。V 的产物是工作区里的三处、不是任何数据表：在册审校落
`verifications/<命题号>.jsonl` 一行；未在册审校先落 `verifications/pending/<正文 sha>.jsonl`
（B 登记拿到号后按正文 sha 认领）；签的侧文件落 `out/vsigns/<被审正文的 sha>.json`
（未在册档由 V 颁发，在册档由框架侧签发判定落盘）。手稿签块与五元位第 3 位由收方秘书落，
不在 V 手上。所以 `WRITE_SETS["V"]` 是空集 —— 空集说的是"不写任何数据表"，不是"没有写盘动作"。
"""
from __future__ import annotations

from ..specs.v import SPEC
from .core import (DEFAULT_VERIFIER, AgentV, _manuscript_facts,
                   default_llm, selftest, set_default_llm)

__all__ = ["AgentV", "SPEC", "DEFAULT_VERIFIER",
           "_manuscript_facts", "default_llm", "selftest", "set_default_llm"]
