# -*- coding: utf-8 -*-
"""秘书的发件口（不替本体表态，从 secretary.py 的 U17 逐字搬出）。

我保证哪条不变式：不替本体表态；不符收件面就一个字节都不出（宁可不出，不许出一份「大概能发」的）。

## 为什么它能单独成文件（依赖方向）

`secretary_outbound` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_outbound` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import refusals as R
from typing import Mapping
import json
import re
import time

from .secretary_judge import (  # noqa: F401 — 这些名字由 secretary_judge 定义
    declarations_candidates,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    ACCEPT_PROPOSAL,
    CLUE_NOTE,
    CLUE_VERB,
    DECISION_ACCEPTED,
    DECISION_PROPOSED,
    DECISION_READDRESS,
    DECISION_REARRANGE,
    DECISION_REJECTED,
    DISPATCH_FIT_UNSUITABLE,
    DISPATCH_VERB,
    KIND_OPTIMIZED,
    KIND_PROPOSAL,
    PROPOSAL_KEYS,
    REJECT_PROPOSAL,
)


class OutboundMixin:
    """发件口（不替本体表态）（从 secretary.py 搬出的混入类）。"""

    def _message_alarms(self, payload: Mapping[str, Any], *, admission: Any = None) -> list[str]:
        """`message`（跨智能体的结构化交互）的预筛：准入判据 + 两个必填字段。

        三态纪律：判据没接上时如实报"这一格判不了（没查成不是没问题）"，绝不因为拿不到判据就当它通过。
        为什么不自己判协作边：判据本体只有一份（`agent_loop.message_admission`），由 `AgentLoop._outbound_hook`
        通过 `admission=` 注入进来。本文件里再查一次协作边（`agent_prompts` 那一支）就是长出了第二份实现，而
        两份漂了没有任何东西会红（判据：`tests/test_secretary.py` 里那条 AST 扫描 —— 它扫的是调用，不是措辞）。
        缺 `subject`/`body` 只报警、不替它编内容（职责 1 的既有纪律：秘书给建议，不改实质、不代笔）。
        """
        out: list[str] = []
        to = str(payload.get("to") or "")
        reply_to = str(payload.get("reply_to") or "")
        if admission is None:
            out.append("message 的协作边准入判据没接上 ⇒ 这一格判不了（没查成不是没问题）")
        else:
            try:
                reason = str(admission(self.role, to, reply_to) or "")
            except Exception as exc:  # noqa: BLE001 - 判据自己坏了也是"判不了"
                reason = f"message 的准入判据自己出错了（{type(exc).__name__}: {exc}）⇒ 这一格判不了"
            if reason:
                out.append(reason)
        for field in ("subject", "body"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                out.append(f"message 的 `{field}` 要是非空字符串（缺了不替它编内容）")
        return out

    #: 发出口这条判据管的两条通道（其余形状没有"内容 ↔ 收件面"这件事：
    #: `summon_many` 本来就是一次派 N 件，`summon` 的收件人是 `role` 一格）。
    FACE_SHAPES: tuple[str, str] = ("handoff", "message")

    def _face_text(self, shape: str, payload: Mapping[str, Any]) -> str:
        """这一条真正会被读的那一段正文（`handoff` 的 summary+body；`message` 的 subject+body）。

        为什么是这两段而不是整个载荷：收件人读到的是正文，JSON 的键名不是内容。
        旧名（`brief` / `title`）与正名 `summary` 一样算，判据认的是它会怎么被读。
        """
        body = payload.get("body") if isinstance(payload, Mapping) else ""
        if str(shape) == "message":
            head = str(payload.get("subject") or "")
        else:
            head = str(payload.get("summary") or payload.get("brief")
                       or payload.get("title") or "")
        return f"{head}\n{body or ''}"

    def split_dispatch_reason(self, shape: str, tokens: Sequence[str]) -> str:
        """「这一条里有 N 件派活」那一句拒信 —— 拆分方案逐字写全（给谁一条、怎么发）。

        业主点名的形态是一条稿子里装着给 A 与给 D 两件活，所以拒信必须回得出
        "给 A 一条、给 D 一条"这个形状，而不是一句"请重写"。收件人写法用原稿里的那个
        （`A` / `A1` 都行：它认得自己写的那一个）。
        """
        names = [str(t) for t in tokens]
        count = len(names)
        if count < 2:
            return ""
        if count == 2:
            options = f"`{shape}(to={names[0]})` 与 `{shape}(to={names[1]})`"
        else:
            options = ("、".join(f"`{shape}(to={t})`" for t in names[:-1])
                       + f" 与 `{shape}(to={names[-1]})`")
        given = "、".join(f"给 {t}" for t in names)
        return (f"这一条里有 {count} 件派活（{given}），一份稿子只能交给一个收件人 ⇒ "
                f"请按收件人拆成 {count} 条：{options}"
                "（或直接用 `summon` 的台账，不要在稿子里抄一遍）。")

    def judge_recipient_face(self, shape: str, payload: Mapping[str, Any], *,
                             face: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """发出口的第二件事（业主 2026-10-26）：这一份内容与它的收件面相符吗。

        它与 :meth:`judge` 那一族是同一件事的两半：:meth:`judge` 判"这活该怎么派"
        （要叫模型），这一格判"这份稿子的内容与收件面配不配"（纯机械、零模型调用）。
        判断落在发出口，所以两条通道（`handoff` 手稿 / `message` 投递）共用一份，
        不再各写一道 if 链。

        两档（都得由 :meth:`optimize_outbound` 在写盘之前问）：

        - 公告栏里点名并下指令 ⇒ 不符：`to` 是公共频道而正文点名了名册成员、又带指令语气，
          那是对一个具体代理下指令，不是公告（判据本体是 `_public_addressee` +
          `PUBLIC_DIRECTIVE_MARKS`，由调用方注入，本文件不抄第二份）；
        - 一份稿子里装了多件派活 ⇒ 不符：正文里有两个以上名册成员落在"派活对象"的位置上
          （判据见 :func:`dispatch_targets`），而一次派活只能有一个收件人。

        返回（三态不许折平，`fits` 就是那一格）：

        | 结局 | 返回 |
        |---|---|
        | 相符 | `fits=True` + `targets` / `named` 读数 |
        | 不符 | `fits=False` + `refused`（既有码）+ `reason`（给本体读的改法） |
        | 判不了 | `fits=None` + `reason`（名册读不成 / 不是这两条通道）⇒ 放行并留痕 |

        `refused` 用的是既有码：公告那一档沿用 `public_is_not_a_conversation`（与
        `message` 那条路同一个词，它同时是那条投递闸的读数取值），多件派活那一档用
        `refusals.PRECONDITION_REASON`（`invalid_params` = 这次调用本身不成立）。
        判据不新造理由码。两档的 `refusal_reason` 因此不一样：后者是任务台账那张受控词表里
        的取值，前者不是（公告那条码从来只在读数里用）—— 照各自的既有落点写，不互相冒充。
        """
        out: dict[str, Any] = {"checked": False, "fits": None, "refused": "",
                               "refusal_reason": "", "reason": "", "targets": [],
                               "named": "", "shape": str(shape), "to": "", "decision": ""}
        if str(shape) not in self.FACE_SHAPES:
            out["reason"] = (f"{shape} 不在发出口这条判据的面上（"
                             "一次派活只能有一个收件人，说的是 handoff / message）")
            return out
        body = payload if isinstance(payload, Mapping) else {}
        out["to"] = str(body.get("to") or body.get("role") or "")
        got = dict(face) if isinstance(face, Mapping) else {}
        if not got:
            out["reason"] = ("收件面没接上（调用方没有注入名册与公告那两条判据）"
                             "⇒ 这一格判不了（没查成不是相符）")
            return out
        if not got.get("checked"):
            out["reason"] = (f"收件面没读成（{got.get('problem') or '名册不可用'}）"
                             "⇒ 这一格判不了（没查成不是相符）")
            return out
        out["checked"] = True
        out["named"] = str(got.get("named") or "")
        public = got.get("public_refusal")
        public = dict(public) if isinstance(public, Mapping) else {}
        if str(public.get("refused") or ""):
            out.update(fits=False, refused=str(public["refused"]),
                       reason=str(public.get("error") or ""),
                       decision=DECISION_READDRESS)
            return out
        members = [m for m in (got.get("members") or ()) if isinstance(m, Mapping)]
        if not members:
            # 名册读成了，可上面一个人都没有（顶层还没派过活）⇒ 正文里点名谁都对不上，
            # 这一格判不了。三态：它不是"相符"（那是把没查成折成查过了）。
            out["reason"] = ("名册上没有一个可通话的人 ⇒ 正文里的派活对象一个都对不上，"
                             "这一格判不了（没查成不是相符）")
            return out
        tokens = dispatch_targets(self._face_text(shape, body), members)
        if len(tokens) >= 2:
            shown = [str(t["token"]) for t in tokens]
            out.update(fits=False, targets=shown, refused=R.PRECONDITION_REASON,
                       refusal_reason=R.PRECONDITION_REASON,
                       reason=self.split_dispatch_reason(str(shape), shown),
                       decision=DECISION_REARRANGE)
            return out
        out.update(fits=True, targets=[str(t["token"]) for t in tokens],
                   reason=("收件面相符：正文里没有第二个落在『派活对象』位置上的人"
                           if not tokens else
                           f"收件面相符：正文里只点到 {tokens[0]['token']} 一个派活对象"))
        return out

    def optimize_outbound(self, shape: str, payload: Mapping[str, Any], *,
                          admission: Any = None, base: str = "",
                          face: Mapping[str, Any] | None = None
                          ) -> dict[str, Any]:
        """职责 1：格式与内容优化（发件前）。

        不改变实质主张：不替本体承诺、不改结论、不加证据（`draft/53` §2 的"不许做"）。所以这里的产物是
        "建议 + 并列候选"，而不是改写后的载荷：本体读到的仍是它自己那一份（改不改由它决定）。两段分得很清
        （这是"切勿全写死成机器判据"的落点）：
        - 第一段是预筛（确定性）：参数表 / 必填 / 工具真名的检查，来自既有声明；
        - 第二段是判断（只有 :meth:`should_engage` 说该介入时才走）：错名映到哪一个候选（:meth:`judge` 的
          `tool_name` 一类，一次模型调用 + 台账）。判断没查成 ⇒ 结论仍是预筛那一份，且台账里
          `judge.checked=False` 写明。
        另加一件同样是判断的事：内容与收件面相符吗 ——
        :meth:`judge_recipient_face`（`face=` 是它要的收件面读数，由调用方注入；判据本体不在这里）。
        判"不符"的那一档是受控拒绝：这一条一份稿子都不出去，拒信与结论一起进返回值与台账。
        fail-open：超时/自己出错 ⇒ 原样放行 + 台账留痕（`fail_open=True`）。
        """
        original = dict(payload)
        # ---- 两段式：确认/拒绝那两个字段是协议字段，
        # 不进洗格式的输入、也不进"原稿/洗后"这两份被并列记录的内容面载荷。
        # 分开取而不是洗完之后再删：`original` 与 `washed` 必须是同一件事的两份，
        # 否则"逐字段 diff"会把一个协议字段算成内容差异。
        accept = str(payload.get(ACCEPT_PROPOSAL) or "")
        reject = str(payload.get(REJECT_PROPOSAL) or "")
        body = {k: v for k, v in original.items() if k not in PROPOSAL_KEYS}
        t0 = time.monotonic()
        try:
            if time.monotonic() - t0 > self.deadline_sec:
                raise TimeoutError("秘书超过单次调用上限")
            # ---- 洗格式。位置：判"该不该介入"之前 ——
            # 预筛要核的是洗过之后那一份（否则"错名"永远是错的，洗了白洗）。
            # 内容面一个字不动（`wash_delegation` 的边界逐条写在它的 docstring 里）。
            wash = self.wash_delegation(shape, body)
            if wash.get("refused"):
                # 硬拒也要把预筛读数算出来：这一趟是死了，但"它另外还把工具名写错了、
                # 候选是这几个"是有用的东西（真机上模型下一步就得靠它改）。
                # 只是不判（不叫模型）：没有可发的载荷，判断没有意义。
                r_to = str(original.get("to") or original.get("role") or "")
                r_params = (original.get("params") if isinstance(original.get("params"),
                                                                 Mapping) else {})
                r_tool = str(original.get("name") or original.get("tool") or "")
                alarms = self.prescreen(to=r_to, action=str(original.get("action") or ""),
                                        params=r_params or {}, tool=r_tool)
                rec = self.note_decision(
                    duty=1, kind=KIND_OPTIMIZED, decision="洗不动 ⇒ 受控拒绝",
                    reason="；".join([str(wash.get("reason") or ""), *alarms]).strip("；"),
                    basis=["specs/<role>.py 的参数表", "tools.build_registry() 的真名"],
                    target={"to": r_to, "action": str(original.get("action") or "")},
                    before=json.dumps(original, ensure_ascii=False, sort_keys=True, default=str)[:2000],
                    changes=list(wash.get("changes") or ()), fail_open=False)
                return {"problem": "；".join([str(wash.get("reason") or ""), *alarms]).strip("；"),
                        "payload": original, "after": original, "wash": wash, "changes": [],
                        "washed": False, "refused": True, "alarms": alarms,
                        "surface": self.surface_readings(shape, original, base=base),
                        "judge": {"checked": False, "reason": "硬拒：没有可判的载荷"},
                        "engaged": False, "fail_open": False, "seq": rec.get("seq")}
            washed = dict(wash.get("payload") or body) if wash.get("checked") else body
            # ---- 两段式的判据本体（纯决定，不写盘）：这一次执行哪一份 / 要不要请示。
            # 编号在下面那一行台账里发（同一个临界区），所以这里只拿到"要不要发"。
            plan = self.plan_wash(original=body, wash=wash, accept=accept, reject=reject)
            to = str(washed.get("to") or washed.get("role") or "")
            action = str(washed.get("action") or "")
            params = (washed.get("params") if isinstance(washed.get("params"), Mapping) else {})
            tool = str(washed.get("name") or washed.get("tool") or "")
            # ---- 发出口的第二件事（业主 2026-10-26）：这一份内容与它的收件面相符吗。
            # 纯机械、零模型调用；`face=` 是收件面读数（名册成员 + 公告里点名了谁），
            # 由调用方注入 —— 与 `admission=` 同一种做法，判据本体不在这里。
            face_reading = self.judge_recipient_face(shape, washed, face=face)
            face_refused = face_reading.get("fits") is False
            if shape == "message":
                # `R8`：`message` 是跨智能体的结构化交互 ⇒ 秘书接管（所有者裁定逐字
                # "如果有些形状涉及到结构化交互，则需要秘书接管"）。接管 = 预筛报警 +
                # 建议 + 台账（不替代 `_do_message` 的硬闸，也不改载荷）。
                #
                # 为什么这一支不跑上面那条委派预筛：`message` 没有 `action`/`params`/`tool`
                # 三件，而预筛会把 `to` 当角色名去查能力表 —— 对公共频道收件人（`ALL`）会报出
                # 两条"读不到这个收件人的角色定位"的假警（频道名不是角色）。它的整个预筛面
                # 就是下面这两格：共用准入判据 + 两个必填字段。
                alarms = self._message_alarms(body, admission=admission)
            else:
                alarms = self.prescreen(to=to, action=action, params=params or {}, tool=tool)
            # 预筛报警不是"判决"：它只说"照声明看不合规"，改法（映到哪个名字、
            # 补哪个字段）是判断 ⇒ 只有该介入时才叫模型。
            judged: dict[str, Any] = {"checked": False, "reason": "预筛没有报警 ⇒ 不必判断"}
            engage = self.should_engage(alarms=alarms, duplicates=0, overdue=0, novel=bool(tool))
            # 请示/受控拒绝/确认这三档都没有要发出去的载荷 ⇒ 不叫模型判
            # （判断的对象是"这次派活该怎么写"，而这次派活根本不发生）。
            if not plan["outcome"] and not plan["problem"] and plan["accepted"] is None:
                if engage and tool and any("真名" in a for a in alarms):
                    judged = self.judge("tool_name", {"tool": tool, "to": to,
                                                      "candidates": declarations_candidates(
                                                          tool, self._tool_names())})
            decision = ("已优化" if not alarms else "建议重排")
            if judged.get("checked"):
                decision = str(judged.get("decision") or decision)
            # 内容与收件面不符时，结论沿用 `DECISIONS` 里既有的那一档
            # （建议重排 = 按收件人拆开；建议改派 = 改成给那一个人的私聊）。
            if face_refused:
                decision = str(face_reading.get("decision") or decision)
            changes = list(wash.get("changes") or ())
            # ---- 台账那一行（一次调用一行；两段式的三档各带自己的 `decision`/`kind`）
            proposal_arg: str | None = None
            fingerprint = ""
            reason = "；".join(alarms) or "没有触发预筛报警（原样放行）"
            if face_refused:
                # 这一条不出去了：台账里的那一句就是退回本体的理由（逐字含拆分方案 / 改法）。
                reason = str(face_reading.get("reason") or reason)
            if plan["outcome"]:
                # 第一段：请示。编号由本秘书在锁内发（`proposal=""` 那一档）；
                # 同一份载荷已经请示过 ⇒ 复用那个编号（`proposal="<id>"` 那一档），
                # 于是"同一件事的两步"在读数上逐字相同（否则原地打转判不出来）。
                decision = DECISION_PROPOSED
                # 指纹随行落账：确认那一步要拿它核"这个编号是对哪份载荷发的"。
                fingerprint = self.proposal_fingerprint(body)
                prior = self.find_proposal_by_fingerprint(fingerprint)
                if prior is not None:
                    proposal_arg = str(prior.get("proposal_id") or "")
                    plan["proposal_id"] = proposal_arg
                else:
                    proposal_arg = ""
                reason = ("；".join(plan["changes"]) or "（改了格式格）"
                          ) + "｜没有执行：等父用 accept_proposal / reject_proposal 表态"
            elif plan["problem"]:
                decision = "洗格式请示：这个编号不成立 ⇒ 受控拒绝"
                proposal_arg = plan["proposal_id"] or None
                reason = plan["problem"]
            elif plan["accepted"] is True:
                decision = DECISION_ACCEPTED
                proposal_arg = plan["proposal_id"]
                reason = "按洗过的那一份执行（parent 接受了格式洗）"
            elif plan["accepted"] is False:
                decision = DECISION_REJECTED
                proposal_arg = plan["proposal_id"]
                reason = "按原稿执行（parent 拒绝了秘书的格式洗）"
            judge_cell = dict(judged)
            if face_reading.get("checked"):
                # 这一格与 `judge` 是同一行里的两件不同的事：判"这活该怎么派"叫了模型，
                # 判"内容与收件面配不配"没叫。`fits` 三态（True / False / None）必须原样落盘，
                # 否则"没查成"与"相符"在纸上长得一样。
                judge_cell.update({"checked": True,
                                   "fits": face_reading.get("fits"),
                                   "targets": list(face_reading.get("targets") or ()),
                                   "named": str(face_reading.get("named") or ""),
                                   "reason": str(face_reading.get("reason") or "")})
                if face_reading.get("decision"):
                    judge_cell["decision"] = str(face_reading["decision"])
            rec = self.note_decision(
                duty=1,
                kind=KIND_PROPOSAL if plan["outcome"] else KIND_OPTIMIZED,
                decision=decision,
                reason=reason,
                basis=["specs/<role>.py 的参数表", "tools.build_registry() 的真名"],
                target={"to": to, "action": action}, judge=judge_cell,
                before=json.dumps(original, ensure_ascii=False, sort_keys=True, default=str)[:2000],
                # S1g：洗过的那一份与原稿并列落账（`before`/`after` + 逐格 `changes`）。
                # 只有一份摆在那里时，"模型说错了"与"秘书替它补对了"在纸上分不开。
                after=json.dumps(washed, ensure_ascii=False, sort_keys=True, default=str)[:2000],
                changes=changes,
                fail_open=False,
                proposal=proposal_arg,
                fingerprint=fingerprint,
            )
            if plan["issue"]:
                # 编号从落盘那一行回来（同一个 `seq`）⇒ "这个编号指向哪一行"不可能漂。
                plan["proposal_id"] = str(rec.get("proposal_id") or "")
                if not str(rec.get("proposal_id") or ""):
                    # 发号失败（台账写不成）⇒ 不许回一个"无法确认"的请示：
                    # 受控拒绝，并把原因写清（fail-open 只剩这一档是安全的）。
                    plan.update(outcome="", issue=False, proposal_id="", problem=(
                        "请示编号没能发出（台账写不成）⇒ 这一趟没有派活："
                        f"{rec.get('ledger_problem') or '未知原因'}"))
            ret = {"problem": "；".join(alarms), "payload": original, "after": washed,
                   "wash": wash, "changes": changes,
                   "washed": bool(wash.get("washed")), "refused": False,
                   "alarms": alarms, "judge": judge_cell, "engaged": bool(engage),
                   "surface": self.surface_readings(shape, washed, base=base),
                   "fail_open": False, "seq": rec.get("seq")}
            if face_reading.get("checked"):
                # 只在真的判过时才给这一格：老载荷（不是 handoff / message、或收件面没接上）
                # 的键集因此一个字节不变。
                ret["face"] = dict(face_reading)
            if face_refused:
                # 受控拒绝：这一条一份稿子都不出去（循环据此不执行 `_do_handoff`）。
                # 三个键一起给，是因为读的人不同：`problem` 给日志、`face` 给台账、
                # 那一句拒信（`reason`）是给本体下一步照着改的。
                ret.update({"problem": str(face_reading.get("reason") or ""),
                            "refused": True})
                return ret
            if plan["outcome"] or plan["problem"] or plan["accepted"] is not None:
                # 只在真的进了第二段时给这一格：老载荷的键集因此一个字节不变
                # （没差异的那条路不是"两段式"，多一格会让人以为它也请示过）。
                ret["wash_proposal"] = plan
            return ret
        except Exception as exc:  # noqa: BLE001 - fail-open：超时/出错一律放行
            self.note_decision(duty=1, kind=KIND_OPTIMIZED, decision="已优化",
                               reason="秘书没跑成 ⇒ 原样放行", fail_open=True,
                               error=f"{type(exc).__name__}: {exc}",
                               before=json.dumps(original, ensure_ascii=False, sort_keys=True, default=str)[:2000])
            self._log(f"秘书优化没跑成（原样放行）：{type(exc).__name__}: {exc}")
            return {"problem": f"{type(exc).__name__}: {exc}", "payload": original,
                    "after": original, "wash": {"checked": False, "washed": False,
                                                "refused": "", "changes": [],
                                                "reason": f"没跑成：{type(exc).__name__}"},
                    "changes": [], "washed": False, "refused": False,
                    "alarms": [], "fail_open": True,
                    "surface": {"checked": False, "fits": None,
                                "reason": "秘书没跑成 ⇒ 面这一维没查成（不是通过）"}}

    def assess_delegation(self, *, to: str, action: str, params: Mapping[str, Any],
                          input_key: str = "", duplicates: Sequence[Mapping[str, Any]] = (),
                          novel: bool = False, reuse: str = "", base: str = "",
                          task: str = "") -> dict[str, Any]:
        """职责 2：委派评估（"收件方真做得到吗、该不该派"）。

        结论 ∈ :data:`DECISIONS` 的四档（`draft/55` §2 的 B 类）+ 理由 + 依据。不擅自改派（改派权在 M）：它只给
        建议，本体可拒绝并写明理由。同 key 的既有终态行是最重要的一条输入（`draft/53` §10：派活去重归发件方
        秘书，"该不该派"含"是不是重复"）—— 机器只把那些行摆出来，判"算重复还是正当重试"由秘书做。不止"任务
        是否符合角色设计"（业主 2026-10-09）：`surface` 那一格是"这件活在被派人的读写面里做不做得成"
        （`draft/90` §1.11）。`reuse` 给了一个名册名（复用已有子代理）时它的面是已知的 ⇒ 判得最准；新起一个时
        槽位还没分，但"越界"与"父视角有、面内没有"两档仍判得出来。`fits=False` 时它进 `reason`（当成一条"该不该
        派"的理由），但不拦（处置权在父）。
        """
        dups = [dict(r) for r in duplicates]
        alarms = self.prescreen(to=to, action=action, params=params)
        mismatch = [a for a in alarms if "动作表里没有" in a or "缺必填参数" in a]
        face = self._face_of_name(owner=str(self.task_id or ""), name=reuse) if reuse else ""
        surface = self.surface_readings("summon", {"action": action, "params": dict(params or {})},
                                        face=face, base=base)
        face_bad = surface.get("fits") is False
        if dups and not mismatch:
            decision, reason = "建议重排", (f"同 (role={to}, action={action}, "
                                          f"input_key={input_key}) 已有 {len(dups)} 条终态行"
                                          "（先看一眼是不是同一件事的重试）")
        elif mismatch:
            decision, reason = "建议重排", "；".join(mismatch)
        elif not str(action or "").strip():
            # 2026-10-21 真机缺陷（业主："秘书拦了好几回派活，看看到底是真的派活不准确还是系统缺陷"）：
            # 这一条没有点名具体动作（role 级派活：把一件活派给某个角色，而不是"调某个动作"），
            # 而下面那条判据是"这个动作在不在你的动作表里" —— 拿空动作去查，答案必然是"不在"，
            # 于是每一次 role 级派活都被建议改派。真机上 M 派 A/E/D 全被判「能力面里没有 」，
            # 而它们其实都派成了（`tasks` 里那四行就是证据）。这不是派活不准，是判据用错了对象。
            #
            # 口径：没点名动作时不拿动作表卡它（动作表管的是"调什么"，不是"派给谁"）；
            # 角色存在性与可召唤性由 `prescreen` 那一侧管。判"可派"，并在 basis 里说清为什么没查动作。
            decision, reason = "可派", ("这一条没点名具体动作（role 级派活）⇒ "
                                        "不拿动作表去卡它；角色存在性由预筛管")
            basis_note = "没点名动作 ⇒ 跳过动作表那一格（动作表管「调什么」，不管「派给谁」）"
        elif face_bad:
            # 面这一维与"能力面"是两回事：能力面说"这个动作你能做"，面说"那块盘
            # 不在你手里"—— 后者今天没有任何别的地方能在派活那一刻看出来。
            decision, reason = "建议改派", (f"{to} 这趟的面里做不成这一件："
                                          f"{surface.get('reason')}"
                                          "（要它做，就把它要用的那一块切进它的面，"
                                          "或者把这一件记成『职责之外』那一档）")
        else:
            decision, reason = "可派", "没有发现重复候选，能力面与参数都对得上"
        basis = ["specs/<role>.py 的动作表", "tasks: 同 key 的既有终态行"]
        if not str(action or "").strip():
            basis.append("没点名动作 ⇒ 动作表那一格不适用")
        if surface.get("checked"):
            basis.append("out/surfaces/<父>/<槽位>：这件活点名的路径在不在里面")
        # ---- 判断类：只有该介入时才叫模型（"切勿全写死成机器判据"的落点）。
        # 两条判断分开问，因为它们是两个问题：同 key 那些行算不算重复（`duplicate_retry`）、
        # 以及该把这条委托重排成什么（`rearrange`）。
        judged: dict[str, Any] = {"checked": False, "reason": "预筛没有报警、也没有重复候选 ⇒ 不必判断"}
        engaged = self.should_engage(alarms=alarms, duplicates=len(dups), overdue=0,
                                    novel=bool(novel))
        if engaged:
            kind = "duplicate_retry" if dups else "rearrange"
            judged = self.judge(kind, {"to": to, "action": action, "params": dict(params or {}),
                                       "input_key": input_key, "duplicates": dups[:5],
                                       "alarms": alarms,
                                       "preliminary": decision})
            if judged.get("checked"):
                # 模型的结论覆盖"预筛给的初步结论"，但它只能给建议（改派权在 M），
                # 而且只在 `checked=True` 时才被采信 —— "没查成"不冒充"可派"。
                decision = str(judged.get("decision") or decision)
                if judged.get("reason"):
                    reason = f"{reason}；判断：{judged['reason']}"
                basis = list(basis) + list(judged.get("basis") or [])
        # ---- 派活审阅（业主 2026-11-13 R2）：D 派 F 的活是不是一个研究方向 ------
        #
        # 与上面那条判断分两问、两本账：
        # - 上面问"这一件该怎么派"（`duplicate_retry` / `rearrange`，落角色台账）；
        # - 这一问"这条派活是不是把一堆方向塞给了一个 F"（`dispatch_fit`，落轴台账
        #   `out/secretary/dispatch_fit.jsonl`）—— 业主：「D秘书要审D的派活，不合适需要
        #   给出提醒」。只提醒不拦：结论并进 `reason`（本体读得到），派活照发。
        # 只在 D→F 且拿到了派活原文时问：`conductor._note_delegation_quality` 那条路
        # 没有原文（`task=""`），在那里问只会拿空材料去问一次模型（白花钱，还可能编一个
        # "不合适"出来）。
        if str(self.role) == "D" and str(to) == "F" and str(task or "").strip():
            fit = self.judge_dispatch_fit(task=task, to=str(to), action=str(action or ""),
                                          params=dict(params or {}))
            if fit.get("checked") and fit.get("verdict") == DISPATCH_FIT_UNSUITABLE:
                # 处置沿用派活轴既有的词（"建议重排" = 按研究方向拆成多个 F），
                # 提醒正文由模型给（它写清了该怎么拆）。不改派活：这只是建议。
                decision = "建议重排"
                reason = f"{reason}；派活审阅：{fit.get('why')}"
                basis = list(basis) + list(fit.get("basis") or [])
        rec = self.note_decision(
            duty=2, kind=KIND_PROPOSAL, decision=decision, reason=reason, basis=basis,
            target={"to": to, "action": action, "input_key": input_key},
            judge=judged, fail_open=False,
        )
        return {"decision": decision, "reason": reason, "basis": basis,
                "duplicates": dups, "alarms": alarms, "novel": bool(novel),
                "surface": surface,
                "judge": judged, "engaged": bool(engaged), "seq": rec.get("seq")}

    def rework_inbound(self, item: Mapping[str, Any]) -> dict[str, Any]:
        """职责 4：按本角色定位把收到的委托加工成贴切版本。

        不加码不减码（`draft/53` §2 的"不许做"）：只改"怎么说"，不改"要什么"。
        所以产物是"补上下文 + 明确产出物与验收口径"的补充段，原文一字不动
        （并列留痕：`draft/55` §5.1 第 3 条）。
        """
        original = dict(item)
        try:
            brief = self._role_brief(self.role)
            tail = []
            deliverable = str(brief.get("deliverable") or "").strip()
            if deliverable:
                tail.append(f"我的产出物口径：{deliverable}")
            duty = str(brief.get("duty") or "").strip()
            if duty:
                tail.append(f"我在本条线上的位置：{duty}")
            note = "\n".join(tail)
            problem = ""
            if not tail:
                problem = ("读不到本角色的 `deliverable`/`duty` ⇒ 这一格判不了"
                           "（没读成不是没问题）")
            self.note_decision(duty=4, kind=KIND_OPTIMIZED, decision="已优化",
                               reason=problem or "按本角色定位补上下文（不加码不减码）",
                               basis=["agent_prompts.ROLE_BRIEFS"],
                               before=json.dumps(original, ensure_ascii=False, sort_keys=True, default=str)[:2000],
                               after=note[:2000])
            return {"item": original, "addendum": note, "problem": problem, "fail_open": False}
        except Exception as exc:  # noqa: BLE001 - fail-open
            self.note_decision(duty=4, kind=KIND_OPTIMIZED, fail_open=True,
                               error=f"{type(exc).__name__}: {exc}",
                               reason="秘书没跑成 ⇒ 原样交给本体")
            return {"item": original, "addendum": "", "problem": f"{type(exc).__name__}: {exc}",
                    "fail_open": True}


#: 「点名之后跟一句说明」的括号写法（派活清单在正文里就是这种形态）。
_TARGET_OPENERS: dict[str, str] = {"（": "）", "(": ")", "【": "】", "[": "]", "〔": "〕"}


def _dispatch_clue(body: str, token: str) -> tuple[int, str]:
    """这个写法在正文里有没有落在"派活对象"位置上的形态；返回 `(第一次命中的下标, 线索名)`。

    整词判据：左右不许再粘 ASCII 字母/数字/下划线（`A1` 里的 `A`、`ACC` 里的 `A` 都不算命中，
    否则正文里每一个 `A` 都会变成"点名"）。两条位置线索（任一成立即可）：

    - :data:`CLUE_NOTE`：名字后面紧跟一个括注，且括注里不是空的（`A（派活：检索文献）`）；
    - :data:`CLUE_VERB`：名字紧跟在「派活」/「派给」后面（可带「给」与冒号，`派活：A`）。

    没有命中返回 `(-1, "")`。
    """
    want = str(token or "")
    if not want:
        return -1, ""
    pattern = re.compile(r"(?<![0-9A-Za-z_])" + re.escape(want) + r"(?![0-9A-Za-z_])")
    for hit in pattern.finditer(body):
        start, end = hit.span()
        j = end
        while j < len(body) and body[j] in " \t\u3000":
            j += 1
        if j < len(body) and body[j] in _TARGET_OPENERS:
            close = body.find(_TARGET_OPENERS[body[j]], j + 1)
            note = body[j + 1: close if close >= 0 else len(body)]
            if note.strip():
                return start, CLUE_NOTE
        if re.search(r"(?:派活|派给)\s*给?\s*[:：]?\s*$", body[:start]):
            return start, CLUE_VERB
    return -1, ""


def dispatch_targets(text: Any,
                     members: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """正文里被点名、且落在"派活对象"位置上的那些名册成员（确定性：不调模型、不花钱）。

    ## 判据（三条，全部机械可判）
    1. 正文里出现 :data:`DISPATCH_VERB`（「派活」）—— 没有这个字样，这一段就不当派活清单读；
    2. 名册成员的三种写法各算一种指称：名册名 / 绝对编号 / 角色代号（`A`…`M`），整词匹配
       （判据见 :func:`_dispatch_clue`）；
    3. 命中的位置还必须落在"派活对象"的位置上（:data:`CLUE_NOTE` 或 :data:`CLUE_VERB`）。

    返回按第一次出现排序的 `[{key, token, name, role, kind, clue, at}]`；`key` 是成员身份
    （`task_id` 优先），同一成员的两种写法（`A1` 与角色代号 `A`）折成一个对象 ——
    于是"同一件事写了两遍"不会被数成两件派活。

    角色代号那一格要单独说一句：同一个角色在名册上有两个实例（`A1` / `A2`）时，正文里的
    `A（派活：…）` 指的不是某一个实例 —— 它折成 `role:A` 这一个指称。不这么折的话，
    一个 `A（…）` 会被数成两个对象（每个 A 实例各算一个），于是一次正常的派活被误拒。

    ## 误判方向（写在这里，因为这条判据靠结构线索，不靠语义）
    - 漏判（宁漏不误拒的那一侧）：正文用散文写的（"这两件事分别交给检索组与研究组"）、
      或只写"派 B 去查"而不出现「派活」/「派给」的，判不出来 —— 这一格不猜语义。
    - 误判：一条真正的公告若逐个点名并各带一句括注（"这一轮 A（查文献）、D（做分析）各干一段"），
      而正文别处又出现了「派活」两个字，会被读成两件派活 ⇒ 退回本体。方向是有意的：
      这条闸的处置只是"按收件人拆开重发一步"，代价一步；而放过去一次就是一次
      "一条稿子里塞几件活"的静默越界（业主点名的正是那个形态）。
    - 名册读不成（`members` 是空表）⇒ 返回空表：那是"这一格没查成"，由调用方按三态处理，
      不许当成"已经相符"。
    """
    body = str(text or "")
    if DISPATCH_VERB not in body:
        return []
    rows = [dict(m) for m in (members or ()) if isinstance(m, Mapping)]
    by_key: dict[str, dict[str, Any]] = {}
    #: `(写法, 指称键)`：名册名 / 绝对编号各指一个成员；角色代号按"同角色是否唯一"折
    #: （见 docstring 里那一句）。
    tokens: list[tuple[str, str]] = []
    role_keys: dict[str, list[str]] = {}
    for m in rows:
        key = str(m.get("task_id") or m.get("name") or m.get("role") or "")
        if not key:
            continue
        by_key.setdefault(key, m)
        for token in (str(m.get("name") or ""), str(m.get("task_id") or "")):
            if token:
                tokens.append((token, key))
        role = str(m.get("role") or "")
        if role:
            role_keys.setdefault(role, []).append(key)
    for role, keys in role_keys.items():
        tokens.append((role, keys[0] if len(keys) == 1 else f"role:{role}"))
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for token, key in tokens:
        if (token, key) in seen:
            continue
        seen.add((token, key))
        at, clue = _dispatch_clue(body, token)
        if not clue:
            continue
        m = by_key.get(key) or {}
        hits.append({"key": key, "token": token, "at": at, "clue": clue,
                     "name": str(m.get("name") or ""),
                     "role": str(m.get("role") or ""),
                     "kind": str(m.get("kind") or "")})
    hits.sort(key=lambda t: (int(t.get("at") or 0), t["key"]))
    found: list[dict[str, Any]] = []
    taken: set[str] = set()
    for hit in hits:
        if hit["key"] in taken:
            continue
        taken.add(hit["key"])
        found.append(hit)
    return found


def reach_fit(role: str, action: str) -> dict[str, Any]:
    """这件活由被派的人（连同它出边上的子代理们）合起来做不做得成（纯计算，只报不改）。

    业主 2026-10-14：「秘书侧……评估派发出的任务能否由子代理及子代理的出边共同完成」。`surface_fit` 判的是
    路径面，这一条判的是能力面：那个动作，被派人自己有没有？没有的话，它出边上的伙伴（再由伙伴的出边……直到
    `policy.max_depth`）里有谁有？走哪几跳？四档（与三态纪律同形，`unknown` 不许折成"做得到"）：
    | `verdict` | 意思 |
    |---|---|
    | `in_self` | 被派人自己的动作表里就有这一件（一跳都不用） |
    | `via_edges` | 要靠出边上的伙伴：`hops` 给出那条链（含每一跳的 role） |
    | `unreachable` | 它那一支闭包里没有任何人有这一件 ⇒ 「面内做不成」，该改派或走上报那一档 |
    | `unknown` | 角色或动作名认不出（`capabilities` 里没有）⇒ 判不了 |
    为什么按"闭包"而不是按"角色"="能做什么"的静态印象：真机形态是二层、三层地派（M→B→H 这种）—— 子代理
    自己拿不到某件工具，但它的伙伴拿得到，而那正是"派得出去"与"派不出去"的分界。旧口径只看被派人自己的动作
    表，于是「B 要把引文交给 H 判语义」会被读成"面内做不成"，而它其实是走得通的（`B → H` 那条边 +
    `H.judge_quote_semantics`）。与 `surface_fit` 的分工：这一条判"谁能做"，`surface_fit` 判"在哪做"（路径落点）。
    """
    from . import capabilities as C
    from . import policy as P

    who = str(role or "").strip()
    want = str(action or "").strip()
    out: dict[str, Any] = {"checked": False, "verdict": "unknown", "hops": [],
                           "reason": ""}
    roles = set(C.CAPABILITIES)
    if who not in roles:
        out["reason"] = f"角色 {who!r} 不在能力表里（{sorted(roles)}）⇒ 判不了"
        out["checked"] = True
        return out
    if want == "":
        out["reason"] = "没给动作名 ⇒ 判不了这一维（不适用不是通过）"
        out["checked"] = True
        return out
    known = {a.action for acts in C.CAPABILITIES.values() for a in acts}
    if want not in known:
        out["reason"] = f"动作 {want!r} 不在任何角色的动作表里 ⇒ 判不了"
        out["checked"] = True
        return out

    def _has(r: str) -> bool:
        return any(a.action == want for a in C.CAPABILITIES.get(r, ()))

    if _has(who):
        out.update({"checked": True, "verdict": "in_self", "hops": [who],
                    "reason": f"{who} 自己的动作表里就有 {want}"})
        return out

    # BFS：一层一层看出边上的伙伴（闭包），并把最短那条链记下来。
    # 深度上限取策略本体的默认值（唯一来源：`policy.Policy`），不从调用方另带一份。
    depth_cap = int(getattr(P.Policy(), "max_depth", 5) or 5)
    seen = {who}
    frontier: list[tuple[str, list[str]]] = [(who, [who])]
    for _step in range(max(0, depth_cap - 1)):
        nxt: list[tuple[str, list[str]]] = []
        for node, path in frontier:
            for peer in sorted(C.ALLOWED_EDGES.get(node, ())):
                if peer in seen:
                    continue
                seen.add(peer)
                chain = path + [peer]
                if _has(peer):
                    out.update({"checked": True, "verdict": "via_edges", "hops": chain,
                                "reason": (f"{who} 自己没有 {want}，但出边上的 "
                                           f"{' → '.join(chain[1:])} 有（"
                                           f"{len(chain) - 1} 跳）")})
                    return out
                nxt.append((peer, chain))
        frontier = nxt
        if not frontier:
            break
    out.update({"checked": True, "verdict": "unreachable", "hops": sorted(seen),
                "reason": (f"{who} 那一支（{'、'.join(sorted(seen))}）里没有任何角色有 "
                           f"{want} ⇒ 这一件在它的面内做不成：改派给有它的那一支，"
                           "或如实记成「职责之外」那一边")})
    return out
