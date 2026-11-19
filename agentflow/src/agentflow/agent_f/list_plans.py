"""角色 F 的动作 `list_plans`。"""
from __future__ import annotations

from .. import lifecycle as L


class _ListPlans:
    def list_plans(self, *, problem_key: str | None = None, include_terminal: bool | None = True) -> dict:
        """列出攻坚计划。`include_terminal=False` 只给"还活着的"计划。

        ## 归属（K3）：只列自己名下
        F 的实例调用只列 `created_by` 是自己（或没有归属读数）的那些；D/G/H 的读口与
        "没有实例身份"的直调不收窄（`specs/d.py:254-267`）。每条都显式带 `created_by`，
        `reason` 里写明"过滤前有几条" —— 收窄了哪一档不许只体现在条数上。
        
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
        # ---- 归属（K3）：「只列自己名下」。
        #
        # 改前列的是全表（`total` = 盘上所有计划），于是两个 F 各读一次会看到同一份
        # 清单，"这条计划是谁的"只能靠 `created_by` 自己去猜 —— 而它连这一格都不给。
        # 过滤判据只有一份（`_plan_scope` + `_plan_owner_of`）：
        #   · F 的实例调用 ⇒ 只留 `created_by` 是我（或没有归属读数）的那些；
        #   · D/G/H 那个读口与"没有实例身份"的直调 ⇒ 不收窄（`specs/d.py:254-267`）。
        scope = self._plan_scope()
        all_total = len(rows)
        if scope.get("scoped"):
            rows = [r for r in rows if self._plan_owner_of(r)["owned"]]
        if not include_terminal:
            # 「还活着」只有一份判据：`lifecycle` 的活跃集（完工 / 放弃都不在内）。
            rows = [r for r in rows if L.plan_is_active(r)]
        return {
            "checked": True,
            "total": len(rows),
            "plans": [
                {
                    "plan_id": r.get("plan_id"),
                    "problem_key": r.get("problem_key"),
                    # 原始 status 保留（审计），另给一格三态：判据只读 `lifecycle_state`
                    # （FIX186-A：`include_terminal` 的过滤已经是 `L.plan_is_active`）。
                    "status": r.get("status"),
                    "lifecycle_state": L.state_of_plan(r).get("state"),
                    "rounds": r.get("rounds"),
                    "max_rounds": (r.get("budget") or {}).get("max_rounds"),
                    "subgoals": len(r.get("subgoals") or []),
                    "depth": r.get("depth"),
                    # 归属（K3）：每一条都显式带 `created_by` —— 读者不必再猜"这是谁的"。
                    "created_by": r.get("created_by"),
                }
                for r in rows
            ],
            "reason": (f"共 {len(rows)} 个计划（include_terminal={include_terminal}；"
                       + ("只列你名下" if scope.get("scoped")
                          else "不按归属过滤")
                       + f"，过滤前 {all_total} 条）"),
        }
