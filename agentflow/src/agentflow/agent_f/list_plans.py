"""角色 F 的动作 `list_plans`（`goal-7f5116c1` M6：从 `agent_f.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import TERMINAL_STATUSES

class _ListPlans:
    def list_plans(self, *, problem_key: str | None = None, include_terminal: bool | None = True) -> dict:
        """列出攻坚计划。`include_terminal=False` 只给"还活着的"计划。
        
        ## 为什么参数收 `None`，以及为什么 `None` 必须等于 `True`
        
        `attack.list_plans` 的 schema 把 `include_terminal` 声明成``{"type": "boolean"}``，默认值是 
        `True`（`attack_tools.py` 的 handler）。但 JSON 里的 `null` 会通过参数校验（`base.validate_params` 对 
        `None`跳过类型检查），于是"模型明确写了个 null"和"模型没给这个键"是两条不同的输入路径，而省略键得到 `True`。
        
        修之前这里是 `if not include_terminal:`：`not None is True` ⇒ 显式 `null`被静默当成 `False`，与声明的默认值正
        好相反。同一个意图（"我没有偏好"）在两条输入路径上给出相反的答案，而且不报错、不留痕 —— 这是本项目最忌讳的"把'没给'折叠成'给了 False'"。所以这里把 
        `None` 显式解读为声明的默认值，让"省略"与"显式 null"重新一致；要过滤终局计划必须明确写 `False`。
        """
        if include_terminal is None:
            include_terminal = True
        rows = [r for r in self.store.rows("attack_plans") if problem_key is None or r.get("problem_key") == problem_key]
        rows.sort(key=lambda r: str(r.get("plan_id") or ""))
        if not include_terminal:
            rows = [r for r in rows if str(r.get("status")) not in TERMINAL_STATUSES]
        return {
            "checked": True,
            "total": len(rows),
            "plans": [
                {
                    "plan_id": r.get("plan_id"),
                    "problem_key": r.get("problem_key"),
                    "status": r.get("status"),
                    "rounds": r.get("rounds"),
                    "max_rounds": (r.get("budget") or {}).get("max_rounds"),
                    "subgoals": len(r.get("subgoals") or []),
                    "depth": r.get("depth"),
                }
                for r in rows
            ],
            "reason": f"共 {len(rows)} 个计划（include_terminal={include_terminal}）",
        }
