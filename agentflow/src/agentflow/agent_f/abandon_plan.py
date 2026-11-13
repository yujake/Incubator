"""角色 F 的动作 `abandon_plan`：明确放弃一条计划（理由只认「不再需要」）。"""
from __future__ import annotations

from ._support import Any, Mapping, TERMINAL_STATUSES
from ..planabandon import PLAN_ABANDON_REASONS

#: plan 级放弃理由的受控词表 —— **只有一档**（业主 2026-11-13 裁定 Q2）。
#:
#: 真身在 `agentflow.planabandon`（工具声明那边的参数 enum 也读那一份：`attack_tools`
#: 被本包在模块加载期导入，反过来 import 这里会成环）。这里只把名字带进来给读的人看：
#: 为什么不复用 `statementabandon.ABANDON_KINDS`（`math_error` / `difficulty` /
#: `counterexample` / `space_too_large`）—— 那四档是**命题级**的换号理由，每一档都带
#: 自己的证据要求（`defect_ref` / `salvaged` / `experiment_id` / `space`），而 plan 没有
#: 这些证据面。业主的口径也只有一条：「F 应该有新的放弃理由为不再需要」⇒ 只加这一档。


#: 三个受控码（`refuse` 的 `kind`；终态一律落 `refused / invalid_params`）。
PLAN_ABANDON_MISSING_ID = "plan_abandon_missing_id"
PLAN_ABANDON_NOT_FOUND = "plan_not_found"
PLAN_ABANDON_REASON_NOT_ALLOWED = "plan_abandon_reason_not_allowed"
PLAN_ABANDON_ALREADY_TERMINAL = "plan_already_terminal"


class _AbandonPlan:
    def abandon_plan(self, plan_id: str, *, reason: str = "") -> dict:
        """明确放弃一条计划：`status → abandoned` ＋ `history` 落一行（含「不再需要」）。

        ## 三条硬规矩（业主 2026-11-13 裁定 Q2）

        1. **只有 F 自己有权**：这是 F 的动作（`specs/f.py` 的动作表），工具侧也只登记给
           `_WRITE_ROLES = ("F",)`；别的角色的动作表里没有它、写集里也没有 `attack_plans`。
        2. **理由只认一档**：`reason` 必须逐字是 :data:`PLAN_ABANDON_REASONS` 之一。
           词表外的值受控拒 —— 不拿自由文本兜底（那等于给"理由"开一条无判据的后门）。
        3. **已终态的不许再放弃**：`resolved` / `abandoned` / `stalled` /
           `supported_not_proved` 都已经"不再推进"（`ATTACK_TERMINAL_STATUSES` 那一列）。
           再放弃一次是改写历史：受控拒并点名现在的状态 —— 想重新攻就另立一条计划，
           不要在这条行上翻烙饼。

        ## 落点（不加列、不做 schema 迁移）
        `status` 改 `abandoned`，`history` 追加一行 `{action:"abandon", outcome:"abandoned",
        detail:"不再需要", …}`。`history` 是既有格（`AttackPlan.history` 的 docstring 写着
        "轮次历史（append-only）"），所以这一笔不动磁盘契约。
        **不收工读数**：`closing._round_advanced` 只认 `outcome=="progress"`，这一行的
        `outcome="abandoned"` 不会被读成"又推进了一轮"（放弃 ≠ 推进）。

        ## 为什么不是"再推一轮让它停"
        停下来的计划（`stalled`）与放弃的计划在收工门上是两件事：`agent_loop._sign_gate_f`
        只把 `status=="abandoned"` 当"已放弃"放行；`stalled` 仍然欠一份 V 签。所以"不再需要"
        必须真的落到那一格上，不能靠"不再调用它"表达。
        """
        out: dict[str, Any] = {
            "ok": False, "kind": "", "error": "", "refusal_reason": "",
            "plan_id": str(plan_id or ""), "status": "", "reason": "",
            "abandoned": False, "history_len": 0, "at": "",
        }
        pid = str(plan_id or "").strip()
        if not pid:
            return self._abandon_refusal(
                out, PLAN_ABANDON_MISSING_ID,
                "拒绝放弃：plan_id 不能为空（没有它就不知道要放弃哪一条）")
        got = str(reason or "").strip()
        if got not in PLAN_ABANDON_REASONS:
            return self._abandon_refusal(
                out, PLAN_ABANDON_REASON_NOT_ALLOWED,
                f"拒绝放弃：reason 只许 {list(PLAN_ABANDON_REASONS)} 之一，收到 {reason!r}。"
                "这一档词表只有「不再需要」一条（业主 2026-11-13 的裁定：plan 级没有"
                "「失败 / 冲突」的对应物，不许自己编）")
        rows = [dict(r) for r in self.store.rows("attack_plans")]
        row = next((r for r in rows if str(r.get("plan_id") or "") == pid), None)
        if row is None:
            return self._abandon_refusal(
                out, PLAN_ABANDON_NOT_FOUND,
                f"拒绝放弃：计划 {pid} 不在台账里（没有可放弃的对象）")
        status = str(row.get("status") or "")
        if status in TERMINAL_STATUSES:
            return self._abandon_refusal(
                out, PLAN_ABANDON_ALREADY_TERMINAL,
                f"拒绝放弃：计划 {pid} 已经是终态 {status!r}（{list(TERMINAL_STATUSES)} 都算"
                "「不再推进」）⇒ 再放弃一次是改写历史。要重新攻就另立一条计划")
        at = self._stamp()
        row["status"] = "abandoned"
        row["updated_at"] = at
        row["history"] = list(row.get("history") or []) + [{
            "round": int(row.get("rounds") or 0),
            "sid": "",
            "action": "abandon",
            "outcome": "abandoned",
            # 业主点名的那四个字必须逐字落在这里（读的人一眼看得出为什么放弃）
            "detail": got,
            "evidence": [],
            "at": at,
        }]
        self._write_plan(row, note="f.abandon_plan")
        out.update(ok=True, plan_id=pid, status="abandoned", reason=got,
                   abandoned=True, history_len=len(row["history"]), at=at)
        self._log(f"plan {pid} abandoned", reason=got)
        return out

    @staticmethod
    def _abandon_refusal(out: Mapping[str, Any], kind: str, message: str) -> dict:
        """受控拒（键集合与成功支逐字相同）。"""
        got = dict(out)
        got.update(ok=False, kind=str(kind), error=str(message),
                   refusal_reason="invalid_params")
        return got
