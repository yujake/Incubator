"""角色 F 的动作 `abandon_plan`：明确放弃一条计划（理由三档，见 `planabandon`）。"""
from __future__ import annotations

from ._support import Any, Mapping, PlanError, Sequence, TERMINAL_STATUSES
from .. import statementabandon as SA
from ..planabandon import (PLAN_ABANDON_EVIDENCE_REASONS, PLAN_ABANDON_NOT_NEEDED,
                           PLAN_ABANDON_REASONS)

#: 五条拒信的读指标签（写进拒信正文，便于人/模型逐条对得上）。
#:
#: 为什么它们只是正文里的标签、不是 `refuse()` 的 `kind`：这一层的拒绝是
#: `PlanError`（`ToolError` 子类）—— 走工具层时由 `attack_tools._guard` 落成受控的
#: `plan_error`，走召唤层时由 `conductor._business_refusal_code` 落成
#: `refused / invalid_params`（`PlanError` 在那张业务拒信名单里）。把细码塞进
#: `PlanError.kind` 会让工具层给出一档 `_guard` 契约之外的 kind，而那条契约由
#: `tests/test_tools_attack_graph_fixes.py::test_attack_handlers_are_wrapped_by_the_guard`
#: 逐工具钉着（每个 attack 工具只许 `plan_error` / `validation_error`）。
#: 细码仍然留在正文里，读的人与模型都不丢信息。
#:
#: 三档共用的形状码（`abandon_reason_missing` / `abandon_difficulty_required` /
#: `abandon_salvaged_missing`）不在这里重写：它们从 `statementabandon` 带过来
#: （业主口径：前两档沿用命题级那一套的必填/证据口径，不许另造一套）。
PLAN_ABANDON_MISSING_ID = "plan_abandon_missing_id"
PLAN_ABANDON_NOT_FOUND = "plan_not_found"
PLAN_ABANDON_REASON_NOT_ALLOWED = "plan_abandon_reason_not_allowed"
PLAN_ABANDON_ALREADY_TERMINAL = "plan_already_terminal"

#: 业主 2026-11-13 原话（逐字）：「需要调整是错误的，需要调整在放弃中应该是
#: 不再需要放弃掉原 plan 再开一个新 plan」——所以它不是一档理由，是组合操作。
#: 把它当 `reason` 传进来会走"词表外"那一支受控拒（下面那一段点名字说明）。
NOT_A_REASON = "需要调整"


class _AbandonPlan:
    def abandon_plan(self, plan_id: str, *, reason: str = "", basis: str = "",
                     difficulty: str = "", salvaged: Sequence[Mapping[str, Any]] | None = None,
                     ) -> dict:
        """明确放弃一条计划：`status → abandoned` ＋ `history` 落一行。

        ## 三档理由（业主 2026-11-13 更正后的词表，唯一真身 `planabandon`）

        | 档 | 什么时候用 | 要给的证据（沿用命题级那两档的口径） |
        |---|---|---|
        | `math_error` | 命题本身有实质数学错误 | `basis` 要点出错误（哪一步、错的是什么） |
        | `difficulty` | 证明过程中遇到难以逾越的困难 | `basis` 说清困难 ＋ `difficulty` 一句描述 ＋ `salvaged` 把旧证明里可取之处拆成引理写清 |
        | `不再需要` | plan 没毛病，但它已不是推进目标所必需的那一条 | 无（可以给 `basis` 说明为什么不需要） |

        「需要调整」不是一档理由：它是组合操作 —— 用 `不再需要` 放弃原 plan，
        再新开一条 plan。把它填进 `reason` 会被词表拒掉，拒信点名字说明。

        ## 三条硬规矩

        1. 只有 F 自己有权：这是 F 的动作（`specs/f.py` 的动作表），工具侧也只登记给
           `_WRITE_ROLES = ("F",)`；别的角色的动作表里没有它、写集里也没有 `attack_plans`。
        2. 理由只认三档：`reason` 必须逐字是 :data:`PLAN_ABANDON_REASONS` 之一。
           词表外的值受控拒 —— 不拿自由文本兜底（那等于给"理由"开一条无判据的后门）。
        3. 已终态的不许再放弃：`resolved` / `abandoned` / `stalled` /
           `supported_not_proved` 都已经"不再推进"（`ATTACK_TERMINAL_STATUSES` 那一列）。
           再放弃一次是改写历史：受控拒并点名现在的状态 —— 想重新攻就另立一条计划，
           不要在这条行上翻烙饼。

        ## 证据口径为什么是这几个格、而不是新造一套

        前两档的语义与证据要求沿用命题级（`statementabandon`）：
        - 形状码直接用 SA 的常量（`ABANDON_REASON_MISSING` /
          `ABANDON_DIFFICULTY_REQUIRED` / `ABANDON_SALVAGED_MISSING`），不另写字符串；
        - `salvaged` 的归一化直接用 SA 的同一个函数（`salvaged_items`：每条给
          `label` 与 `stmt_id`，空数组也拒）。
        不搬命题级里"必须指向一条在册命题的验证行"的那一半（`defect_ref` 的
        `fault` / sha / 陈旧判定）：那是被放弃的那条命题自己的证据，而这里被放弃的
        是一条 plan —— 它没有 `statements` 行，硬套只会把"证据不够"变成"这条路走不通"。
        业主的口径是"math_error 要点出错误、difficulty 要说清困难并把可取之处留存量
        写清"，所以这两档要求的就是那几格文字/清单。

        ## 落点（不加列、不做 schema 迁移）
        `status` 改 `abandoned`，`history` 追加一行
        `{action:"abandon", abandon_kind:<三档之一>, detail, …}`。
        `history` 是既有格，所以这一笔不动磁盘契约。
        这一行刻意没有 `outcome`：`history` 的 `outcome` 是"这一轮推进的结果"
        （`STEP_OUTCOMES` 三档，停滞检测读它），而放弃不是一轮推进。

        ## 为什么不是"再推一轮让它停"
        停下来的计划（`stalled`）与放弃的计划在收工门上是两件事：`agent_loop._sign_gate_f`
        只把 `status=="abandoned"` 当"已放弃"放行；`stalled` 仍然欠一份 V 签。所以"不再需要"
        必须真的落到那一格上，不能靠"不再调用它"表达。
        """
        pid = str(plan_id or "").strip()
        if not pid:
            raise PlanError(
                f"拒绝放弃（{PLAN_ABANDON_MISSING_ID}）：plan_id 不能为空"
                "（没有它就不知道要放弃哪一条）")
        got = str(reason or "").strip()
        if got not in PLAN_ABANDON_REASONS:
            raise PlanError(
                f"拒绝放弃（{PLAN_ABANDON_REASON_NOT_ALLOWED}）：reason 只许 "
                f"{list(PLAN_ABANDON_REASONS)} 之一，收到 {reason!r}。"
                + ("「需要调整」不是一个理由，是一个组合操作：用「不再需要」放弃原 plan，"
                   "再新开一条 plan。" if got == NOT_A_REASON else
                   "这三档之外的词一律不采信（业主 2026-11-13 的更正："
                   "「需要调整」是操作，不是理由）。"))
        said = str(basis or "").strip()
        if got in PLAN_ABANDON_EVIDENCE_REASONS and not said:
            raise PlanError(
                f"拒绝放弃（{SA.ABANDON_REASON_MISSING}）：reason={got!r} 必须给 `basis`"
                "（说清是哪一步、错/难在哪）—— 这一档与命题级放弃共用同一条证据口径")
        hard = ""
        salvaged_rows: list[dict[str, str]] = []
        if got == SA.ABANDON_KIND_DIFFICULTY:
            hard = str(difficulty or "").strip()
            if not hard:
                raise PlanError(
                    f"拒绝放弃（{SA.ABANDON_DIFFICULTY_REQUIRED}）：reason='difficulty' "
                    "必须给 `difficulty`（一句：卡在哪条引理 / 哪一步 / 哪条假设）")
            salvaged_rows, why = SA.salvaged_items(salvaged)
            if why or not salvaged_rows:
                # 2026-11-15：命题级的 `salvaged` 改成可空（业主语义：放弃之后再注册
                # 新命题），但 plan 级不变 —— 这一档仍要求把旧证明里可取之处拆成
                # 引理写清。别把"命题级可选"读成"plan 级也可选"。
                raise PlanError(
                    f"拒绝放弃（{SA.ABANDON_SALVAGED_MISSING}）："
                    + (why or "没给 salvaged（plan 级的 difficulty 仍要求把旧证明里"
                              "可取之处拆成引理写清，每条给 label 与 stmt_id）")
                    + "（业主口径：difficulty 要把旧证明里可取之处拆成引理、留存量写清）")
        rows = [dict(r) for r in self.store.rows("attack_plans")]
        row = next((r for r in rows if str(r.get("plan_id") or "") == pid), None)
        if row is None:
            raise PlanError(
                f"拒绝放弃（{PLAN_ABANDON_NOT_FOUND}）：计划 {pid} 不在台账里"
                "（没有可放弃的对象）")
        status = str(row.get("status") or "")
        if status in TERMINAL_STATUSES:
            raise PlanError(
                f"拒绝放弃（{PLAN_ABANDON_ALREADY_TERMINAL}）：计划 {pid} 已经是终态 "
                f"{status!r}（{list(TERMINAL_STATUSES)} 都算「不再推进」）⇒ 再放弃一次是"
                "改写历史。要重新攻就另立一条计划")
        at = self._stamp()
        row["status"] = "abandoned"
        row["updated_at"] = at
        entry: dict[str, Any] = {
            "round": int(row.get("rounds") or 0),
            "sid": "",
            "action": "abandon",
            # 档位进 history：读的人不必回推"这四个字是哪一档"（与命题级的
            # `abandon_kind` 同名同义）。字面量来自 `planabandon`，不在这里重写。
            "abandon_kind": got,
            # 这里没有 `outcome` 这一格，刻意不是漏写：`history` 里的 `outcome`
            # 是"这一轮推进的结果"（`STEP_OUTCOMES` 三档，停滞检测读它）。
            # 放弃不是一轮推进 —— 给它写一个词表外的 outcome 会把"这一轮发生了什么"
            # 与"这条计划怎么收场"折进同一格（`tests/test_agent_f_step_outcomes.py`
            # 的 AST 普查正是钉这件事的）。
            "detail": (f"{got}：{said}" if said else got),
            "evidence": [],
            "at": at,
        }
        if hard:
            entry["difficulty"] = hard
        if salvaged_rows:
            entry["salvaged"] = salvaged_rows
        row["history"] = list(row.get("history") or []) + [entry]
        self._write_plan(row, note="f.abandon_plan")
        self._log(f"plan {pid} abandoned", reason=got)
        return {"ok": True, "kind": "", "error": "", "refusal_reason": "",
                "plan_id": pid, "status": "abandoned", "reason": got,
                "abandoned": True, "history_len": len(row["history"]), "at": at}
