# -*- coding: utf-8 -*-
"""L 的「向 B 汇报形式化困难」这一格（业主 2026-10-22 晚裁定的第三句）。

## 裁定原文（逐字）

> 「可向 B 汇报形式化过程中遇到的困难、要求 B 完善证明并重新得到 V 签」

它有三条落点，缺一条这一句就只是口号：

1. 谁听：只有 B（`specs/b.py` 的 `edges` 里有 `L`，`specs/l.py` 的 `summonable=True`
   —— 那一侧是"B 可以派 L"，这一侧是"L 可以跟 B 说话"）。递送走既有的 `message`
   通道（`agent_loop.send_message` / `read_messages`），准入判据是
   `agent_loop.message_admission` —— 与私聊同一条闸，不另开一条绕过边表的缝；
2. 说什么：受控形态在 `proofreport`（`FAILURE_TYPES` 四档 + 步号 + 建议 B 补什么 +
   严重度两档）。不写整段自由文本，是因为 B 下一趟要按类分派；
3. 什么时候说：`formalize` 判"形式化失败或对不上"时自己说（`_maybe_report_failure`），
   不靠模型记得去发一条消息 —— "会记得"不是判据，`formalize` 的结论才是。

## 三类不汇报的失败（刻意）

- 检查器说 `compile_error` / `extra_axioms` / `decl_mismatch`：那是 L 自己写的源码
  有毛病（`agent_l/formalize.py` 的失败分类），B 改不动它；
- 自检不是 `usable`（`lean_selfcheck_*`）：环境问题，与 B 的证明无关；
- 台账里一行命题都没有（`no_ledger`）：没有对象可汇报。

这三类都留在返回值里（`reason` / `coverage`），也留在 `report.state="skipped"` 的
理由里 —— "没汇报"与"汇报了"分得开，且"为什么不汇报"有读数。
"""
from __future__ import annotations

from typing import Any, Mapping

from .. import proofreport as PR


class _Report:
    """L 的汇报入口（`AgentL` 的一个混入，见 `agent_l/core.py` 的类声明）。"""

    #: 台账那一道闸里"与 B 的登记对不上"的那几档（`formalize.STATEMENT_REASONS` 的子集）。
    #:
    #: 口径：这几档意味着"要形式化的那一条与 statements 对不上"，B 是唯一能改它的人
    #: （登记 / 补证明 / 改正文）。`statement_ledger_unreadable` 不在里面 —— 那是我们
    #: 没读成台账，不是 B 的账错。
    STATEMENT_MISMATCH_REASONS: tuple[str, ...] = (
        "statement_not_found",
        "statement_id_ambiguous",
        "statement_without_body",
        "statement_without_proof",
        "claim_mismatch",
    )

    #: 检查器自己说的那几档（L 的源码有毛病，不该退回给 B）。
    CHECKER_FAULT_REASONS: tuple[str, ...] = (
        "compile_error",
        "uses_sorry",
        "extra_axioms",
        "decl_mismatch",
    )

    #: 本地/环境那一档（自检不过、没有检查器、超时、写盘失败、参数不成立）：
    #: 与 B 的证明无关，"退回给 B"只会把一件环境问题变成一次无用的往返。
    LOCAL_FAULT_REASONS: tuple[str, ...] = (
        "lean_selfcheck_off",
        "lean_selfcheck_unusable",
        "lean_selfcheck_unknown",
        "no_backend",
        "timeout",
        "import_unavailable",
        "tool_failed",
        "path_outside_workspace",
        "param_error",
    )

    def report_to_b(self, *, statement_id: str, failure_type: str, step: Any = 0,
                    suggestion: str = "", severity: str = "normal", detail: str = "",
                    statement_label: str = "", proof_chars: Any = 0,
                    dependency_steps: Any = 0, session_root: Any = "",
                    sid: Any = "") -> dict[str, Any]:
        """把一条形式化困难投进 B 的收件箱（受控形态见 `proofreport`）。

        返回值就是 :func:`proofreport.deliver` 的形态 + `payload`；`state` 三档
        （`reported` / `refused` / `skipped`）里只有 `reported` 表示"B 真的收到了"。
        """
        item = PR.payload(
            statement_id=statement_id, failure_type=failure_type, step=step,
            statement_label=statement_label, suggestion=suggestion, severity=severity,
            detail=detail, proof_chars=proof_chars, dependency_steps=dependency_steps)
        bad = PR.violations(item)
        if bad:
            return {"attempted": True, "state": "refused", "reason": "invalid_params",
                    "why": "；".join(bad), "msg_id": "", "to": "B",
                    "session_root": "", "sid": "", "payload": item}
        out = PR.deliver(
            sender="L", to="B", item=item, subject=PR.report_subject(item),
            body=PR.report_body(item), extra_key="formal_failure",
            session_root=session_root or self.cfg.get("session_root"),
            sid=sid or self.cfg.get("sid"),
            fallback_root=getattr(self.store, "root", ""))
        self._log(f"formalize：向 B 汇报（{out.get('state')} / {item['failure_type']} / "
                  f"{item['statement_id']}）", msg_id=out.get("msg_id", ""))
        return out

    def _maybe_report_failure(self, *, out: Mapping[str, Any],
                              coverage: Mapping[str, Any],
                              b_library: Mapping[str, Any],
                              statement_label: str = "",
                              session_root: Any = "", sid: Any = "") -> dict[str, Any]:
        """`formalize` 的失败分支上的那一句"要不要向 B 汇报"。

        三档理由（都写进 `why`，不折平）：没有可汇报的失败项（并且说清那是哪一类：
        检查器/本地环境/真的没有失败项）/ 这一条不该打扰 B / 没有可递送的会话。
        """
        reason = str(out.get("reason") or "")
        failed = PR.issues(reason=reason, coverage=coverage,
                           statement_reasons=self.STATEMENT_MISMATCH_REASONS)
        if not failed:
            if reason in self.CHECKER_FAULT_REASONS:
                skip, why = "checker_fault", f"{reason} 是 L 的源码问题，B 改不动它"
            elif reason in self.LOCAL_FAULT_REASONS:
                skip, why = "local_fault", f"{reason} 是本地/环境那一档，与 B 的证明无关"
            else:
                skip, why = "nothing_to_report", "这一趟没有「形式化失败或对不上」的失败项"
            return {"attempted": False, "state": "skipped", "reason": skip,
                    "why": why, "msg_id": "", "to": "B", "session_root": "",
                    "sid": "", "payload": {}}
        first = dict(failed[0])
        return self.report_to_b(
            statement_id=str(b_library.get("stmt_id")
                             or coverage.get("statement_id") or ""),
            failure_type=str(first["failure_type"]),
            step=first.get("step") or 0,
            detail=str(first.get("detail") or ""),
            statement_label=str(statement_label or ""),
            severity=PR.severity_for(str(first["failure_type"])),
            proof_chars=b_library.get("proof_chars") or 0,
            dependency_steps=b_library.get("dependency_steps") or 0,
            session_root=session_root, sid=sid)


__all__ = ["_Report"]
