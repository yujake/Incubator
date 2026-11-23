# -*- coding: utf-8 -*-
"""秘书的签（决定 ≠ 落地，从 secretary.py 的 U26 逐字搬出）。

我保证哪条不变式：发签决定与落签是两件事（决定可以先出、落签要等收方）；收方身份只有一个来源，不从签的内容里推断。

## 为什么它能单独成文件（依赖方向）

`secretary_sign` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_sign` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import proofregistry as _PR
from typing import Mapping
import json

from .secretary_prompts import (  # noqa: F401 — 这些名字由 secretary_prompts 定义
    JUDGE_MATERIAL_CAP,
    _judge_material,
    _wash_v_system,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    JUDGE_UNCHECKED,
    KIND_DECISION,
    SIGN_ISSUE,
    SIGN_WITHHOLD,
    V_REPLY_AXIS,
    V_REPLY_VERDICTS,
)


class SignMixin:
    """签（决定 ≠ 落地）（从 secretary.py 搬出的混入类）。"""

    def judge_v_reply(self, *, reply: str, verdict: str = "", defect_step: Any = None,
                      statement_id: str = "", proof_no: Any = 1,
                      task_id: str = "", proof_text: str = "",
                      materials: Any = None) -> dict[str, Any]:
        """V 这段审阅回复到底有没有指出缺陷（两档不许折平）。

        ## 材料只给两样（这是本方法的判据，不是实现细节）
        V 的回复正文 + 该台账行的 `verdict` / `defect_step`。不给 F 的证明
        （I12：V 的秘书读叙述本来就被 `may_read_narrative` 禁，这里不开那个口子）。
        所以 `proof_text` / `materials` 两个形参是受控拒绝口：调用方若真把它们塞进来，
        本方法拒判（`checked=False` + `refused="proof_text_not_allowed"`），
        而不是"收了但没用"—— 后者会让"秘书看过 F 的证明"这件事在盘上查不出来。

        ## 返回
        `checked` / `answer`（模型原话那一格；没查成时是 `JUDGE_UNCHECKED`） /
        `axis`（只有 `clean` / `fault` 两档；没查成时是空串） / `unwired`（这一趟有没有
        判断面） / `reason` / `basis` / `material`（真递给模型的那一份，供判据逐字核） /
        `refused` / `cost` / `verdict`（台账那一行的结论原文）。

        「不可能有判不了…只要不是完全没毛病都叫有毛病」。
        于是结论只有两格（`没问题` / `有缺陷要指出`）：拿不准、只挑出一处小记号问题、
        只说"我没逐行验证"——每一档在题面里都明文算「有缺陷要指出」。模型若仍答历史
        那一格（`判不了`）或任何词表外的写法 ⇒ `checked=False` + `axis=""`：
        那是"没查成"（框架失败），不是一种结论，更不是"没问题"（连续计数里既不算票、
        也不清零；上层见 `agent_v.core` 的 `secretary_unjudged` 那一支）。

        ## 轴是唯一的判定来源；判 fault 时由本方法定出那一步
        「V 的判词只是陈述」「每一转的轴（clean / fault）一律由 V 秘书做语义分析后给出」
        「判 fault 而 V 没给 defect_step ⇒ 秘书定出那一步」。
        所以：① `verdict` 只作为材料里的原话递给模型，本方法不按它的字面定轴；
        ② 模型判「有缺陷要指出」时还要给出 `defect_step`（题面要求），本方法把它带回去；
        ③ V 给了步号就以 V 的为准？不 —— 轴与步号都是秘书这一问的产物：V 的 `defect_step`
        只是材料，返回值里的 `defect_step` 是秘书定下的那一步（V 给同一值时二者相同）。
        """
        from . import verifications as _VR   # 惰性：此处只借它的轴词表与 `row_signable`

        out: dict[str, Any] = {
            "checked": False, "answer": JUDGE_UNCHECKED, "axis": "",
            "unwired": bool(self.seam is None or not self.enable_model),
            "reason": "", "basis": [], "refused": "", "cost": {},
            "verdict": str(verdict or ""), "defect_step": defect_step,
            #: 这四个键每一行都写（值可以为空串）。键在不在是"新行 / 老行"的唯一分界
            #: （`verifications.fault_kind_of` 读的就是它）；没判成时它们也在，值为空。
            "fault_kind": "", "fault_cause": "", "report_gap": "",
            "statement_id": str(statement_id or ""), "proof_no": 0,
            "material": {},
        }
        try:
            out["proof_no"] = int(_VR.as_proof_no(proof_no) or 0)
        except (TypeError, ValueError):
            out["proof_no"] = 0
        if str(proof_text or "").strip() or materials is not None:
            out["refused"] = "proof_text_not_allowed"
            out["reason"] = ("材料里被塞进了 F 的证明正文（或额外的 materials）⇒ 拒判："
                             "V 的秘书只读 V 的回复与那一签的 verdict/defect_step"
                             "（I12：V 的秘书不读 F 的叙述）。请把证明正文拿掉再来问")
            self.note_decision(
                duty=2, kind=KIND_DECISION, decision=JUDGE_UNCHECKED,
                reason=out["reason"], target={"judge": "v_reply_defect"},
                judge=dict(out), fail_open=False,
                before=f"reply_chars={len(str(reply or ''))}", )
            return out
        body = str(reply or "").strip()
        if not body:
            out["reason"] = "V 的回复正文是空的 ⇒ 没有可判的对象（不是「没问题」）"
            return out
        # 递给模型的材料：只有这两样（键集合固定，判据可以逐字核）。
        material = {
            "v_reply": body[:JUDGE_MATERIAL_CAP],
            "ledger_row": {"verdict": str(verdict or ""), "defect_step": defect_step},
        }
        out["material"] = dict(material)
        got = self.judge("v_reply_defect", material, task_id=task_id)
        out["cost"] = dict(got.get("cost") or {})
        out["reason"] = str(got.get("reason") or "")
        out["basis"] = list(got.get("basis") or [])
        if not got.get("checked"):
            # 没查成 ⇒ 没有轴（不是 clean、也不是 fault）。`judge` 已经把这一趟
            # 落进决定台账了（`_record_judge`），这里不重复落。
            out["answer"] = JUDGE_UNCHECKED
            out["axis"] = ""
            return out
        answer = str(got.get("decision") or "").strip()
        if answer not in V_REPLY_AXIS:
            # 词表外（`judge` 已经挡过一次，这里是第二道：本方法的取值只由 V_REPLY_AXIS 定）。
            # `判不了` 不是一种结论 ⇒ 它落到这里（"不采信"），不许
            # 折成 fault 去凑一条判词，也不许折成 clean 放过去。
            out["answer"] = JUDGE_UNCHECKED
            out["axis"] = ""
            out["reason"] = f"结论 {answer!r} 不在 {list(V_REPLY_VERDICTS)} 里 ⇒ 不采信"
            return out
        out.update(checked=True, answer=answer, axis=V_REPLY_AXIS[answer])
        # ---- 把这一问的答案读成四个类别格（写侧分类第一半） --------------
        #
        # 轴仍由 `V_REPLY_AXIS` 定（两档不动）；这一支只多读两格 —— `defect_kind`
        # 与 `report_gap` —— 并把它们翻译成台账那一格里要落的
        # `fault_kind` / `fault_cause` / `report_gap`。"只缺反例尝试记录不算缺陷"
        # 在这里被编码成 `kind=""` + `cause="report_gap"`；要不要把它
        # 翻成 clean 轴由写行处决定（那里才拿得到 findings / defect_step —— 护栏只许
        # 往更严的方向折，见 `agent_v/core.py` 的 `_write_fault_cell`）。
        _reading = v_reply_fault_reading(
            decision=answer,
            defect_kind=got.get("defect_kind"),
            report_gap=got.get("report_gap"),
            reason=got.get("reason"))
        out.update(axis=str(_reading["axis"]),
                   fault_kind=str(_reading["fault_kind"]),
                   fault_cause=str(_reading["fault_cause"]),
                   report_gap=str(_reading["report_gap"]))
        #: p247：判 fault 时那一步由秘书这一问定（V 没给就以秘书给的为准；V 给了同一步
        #: 时二者相同）。判 clean ⇒ null（没有要改的那一步）。
        out["defect_step"] = (got.get("defect_step")
                              if V_REPLY_AXIS[answer] == "fault" else None)
        out["defect_step_basis"] = (str(got.get("defect_step_basis") or "")
                                    if V_REPLY_AXIS[answer] == "fault" else "")
        return out

    def decide_sign_issuance(self, *, statement_id: str, proof_text: str = "",
                             proof_no: Any = 1, verdict: Mapping[str, Any] | None = None,
                             task_id: str = "", row: Mapping[str, Any] | None = None,
                             within_call: int | None = None,
                             review_call: str = ""
                             ) -> dict[str, Any]:
        """这一签发不发（发签决定权在 V 的秘书；2026-11-16 裁定 ①②③）。

        ## 判据只有一层：同一趟送审内的连续 clean 达到门槛
        `verifications.review_standing` 现算的读数只作历史回放。门槛 = `sign_counting`
        现数（系统计次，2026-11-17 业主裁定）：同一 `review_call` 内 `review_pass=1..need`
        连续 clean 的台账轮数（:func:`sign_counting.count_registered` 从台账现读；跨送审
        不累计、同号重放不增加）。`within_call` 只是调用方自报的读数 —— 它多了 / 少了一轮
        都不改变发不发签。门槛够了且这一签的轴是 clean ⇒ 由秘书直接发签，不再问模型
        （裁定 ③ 删掉了那次"模型点头"）。次数不够 ⇒ `不签发`，同样不问模型（省一次调用，
        也不给它推翻门槛的机会）。

        不给 `within_call`、行上也没有 `review_call`（旧直调路径 / 夹具）⇒ 保持历史台账
        地板（`sign_counting.legacy_tail`：台账尾部连续 clean 的条数）；那一档仍要求
        秘书有判断面（"没有秘书就不发签"的装配纪律），但那条纪律不是模型判定，
        也不改变本方法"地板过了即发"的规则。

        ## 两态（"没查成"绝不被读成"没问题"）
        | 结局 | 返回 |
        |---|---|
        | 地板过了 | `checked=True` + `issue=True` + `decision=签发` |
        | 地板没过 | `checked=True` + `issue=False` + `decision=不签发` |
        | 没缝 / 开关关着（仅旧直调）/ 台账读不成 / 坏 JSON | `checked=False` + `issue=False` + 理由 |

        `checked=False` ⇒ 不发签（装配没接上时秘书判定必须报
        `checked=False`，且不放签）。返回键：`checked` / `issue` / `decision` / `streak` /
        `need` / `streak_ok` / `projected` / `same_sha` / `state` / `reason` / `basis` /
        `reading` / `cost` / `material`。

        ## 落痕
        走 `note_decision`（那本账：`before` = 台账读数、`after` = 决定、`judge` = 这一趟判词）。
        2026-11-16 之后这一趟只有"决定"一行 —— 不再有模型判定那一行（没有模型调用了）。
        """
        from . import verifications as _VR   # 惰性：与 `merge_into_*` 那条同一处依赖

        v = dict(verdict or {})
        if row is not None and not v:
            # 调用方只给了台账那一行：这一签的结论与未解决 error 从行上读（同一份事实，
            # 不要求调用方抄第二遍）。
            v = {"verdict": row.get("verdict"),
                 "unresolved_errors": row.get("unresolved_errors"),
                 "defect_step": row.get("defect_step")}
        # 2026-11-11：`proof_no` 在 V 签侧退役 —— 返回值不再写这一格，但它仍是
        # 「这一趟审的是哪一份」的材料标签（递给模型的那一小段仍要说清）。
        try:
            proof_number = int(_VR.as_proof_no(proof_no) or 0)
        except (TypeError, ValueError):
            proof_number = 0
        out: dict[str, Any] = {
            "checked": False, "issue": False, "issued": False,
            "decision": JUDGE_UNCHECKED, "landed": False, "writeback": {},
            "streak": 0, "need": int(_VR.SIGN_STREAK_NEED), "streak_ok": False,
            "projected": 0, "same_sha": False, "state": "", "reason": "",
            #: 2026-11-02：单次送审内的轮数（None = 没给，走历史台账兼容门）/
            #: 那一趟的调用 id / 台账尾部的历史连续数（只作读数，不参与判定）。
            "within_call": None, "review_call": str(review_call or ""),
            "ledger_streak": 0,
            #: 2026-11-17（系统计数）：这一签的门槛是框架从台账现数的那几格。
            #: 键无条件存在（两条分支都写；不给的旧直调那一支是空串 = 没数过）。
            "counted_by": "", "sign_count": {},
            "basis": [], "reading": {}, "cost": {}, "material": {},
            "statement_id": str(statement_id or ""),
            # 2026-11-11：`proof_no` 在 V 签侧退役 —— 这一格不再写（顶层读数同口径）。
        }
        #: `within_call` 归一：负数按 0 收（"这一趟一轮都没判"不是"次数够了"）。
        within: int | None = None
        if within_call is not None:
            try:
                within = max(0, int(within_call))
            except (TypeError, ValueError):
                within = None
        out["within_call"] = within
        root = self.store.root if self.store is not None else self.root
        reading_problem = ""
        try:
            reading = _VR.review_standing(root, statement_id=str(statement_id or ""),
                                          proof_text=str(proof_text or ""),
                                          proof_no=proof_no)
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不是"没问题"
            if within is None:
                out["reason"] = (f"台账读不成（{type(exc).__name__}: {exc}）⇒ 这一格没查成："
                                 "不放签（不是「可以签」）")
                self._note_sign_issuance(out, task_id=task_id)
                return out
            # 给了 `within_call` 时台账只是历史读数 —— 历史读不成不许反过来否决这一趟
            # （台账不以任何形式参与发不发签）。
            reading_problem = f"{type(exc).__name__}: {exc}"
            reading = {}
        out["reading"] = dict(reading)
        out["ledger_streak"] = int(reading.get("streak") or 0)
        out["streak"] = out["ledger_streak"]
        out["state"] = str(reading.get("state") or "")
        sha = str(reading.get("sha") or "")
        same_sha = bool(sha) and sha == _PR.proof_sha(str(proof_text or ""))
        out["same_sha"] = same_sha
        # 这一签落下去之后的连续次数：同一份正文 ⇒ 前一票 + 这一票；换了一份 ⇒ 从 1 起。
        #
        # 两种调用顺序都要对（生产走的是第二种）：
        # · 先问后做：台账里还没有这一签 ⇒ `streak + 1`（预测）；
        # · 先落台账后问（V 的秘书这一条路：`record_verification(flip=False)` 已经把行落了）
        #   ⇒ 这一签就是尾部那一签 ⇒ 连续次数就是 `streak`，不许再加一票。
        # 判据是 `verification_id` 与尾部那一签同号（不是靠调用方自己说落没落）。
        landed = (isinstance(row, Mapping)
                  and str(row.get("verification_id") or "")
                  and str(row.get("verification_id") or "")
                  == str(reading.get("verification_id") or ""))
        out["landed"] = bool(landed)
        # ---- 候选这一签的资格只看秘书给的轴，不看 V 的 verdict 字面 ----
        #
        # 「streak / 签发只看秘书给出的轴，不看 V 自己写的那两个字」。所以这里读
        # `secretary_axis`（row 已经有这一格；直调路径可以从
        # `verdict` 的 `secretary_judge` / `axis` 带进来），不再用 `verdict == "成立"`。
        candidate_axis = ""
        if isinstance(row, Mapping):
            candidate_axis = _VR.ledger_axis(row)
        if not candidate_axis:
            got_judge = v.get(_VR.SECRETARY_JUDGE_KEY)
            if isinstance(got_judge, Mapping):
                candidate_axis = _VR.secretary_axis({_VR.SECRETARY_JUDGE_KEY: got_judge})
        if not candidate_axis and str(v.get("axis") or "") in _VR.SECRETARY_JUDGE_AXES:
            candidate_axis = str(v.get("axis") or "")
        if not candidate_axis:
            #: 老调用点 / 直调夹具：只给了 `verdict`，没有秘书那一格 ⇒ 没有轴。
            #: `historical_axis` 一律空轴（按 `verdict` 字面给 clean/fault，那正是
            #: "绕过秘书登记成立"的后半截）。这一档因此是
            #: "判不了"：`candidate_ok` 为假 ⇒ 不签发，不是"没问题"。
            candidate_axis = _VR.historical_axis(v)
        candidate_ok = (candidate_axis == "clean"
                        and int(v.get("unresolved_errors") or 0) == 0)
        #: 这一签的送审身份：行上带 `review_call`（V 这一趟的三轮）⇒ 新形态。
        _row_call = str((row or {}).get("review_call") or "").strip() \
            if isinstance(row, Mapping) else ""
        counted: dict[str, Any] = {}
        if within is not None or _row_call:
            # ---- 2026-11-17（业主：「是系统计数落签」）----------------------
            #
            # 门槛只有一个来源：框架从台账现数（同一 `review_call` 内
            # `review_pass=1..need` 连续 clean，跨送审不累计、同号重放不增加）。
            # `within_call`（V 那一趟的 `pass_no`）只作读数：它多一轮 / 少一轮都不
            # 改变发不发签 —— 这正是"决定权在框架"那一条的可测形态。
            from . import sign_counting as _SC

            counted = _SC.count_registered(
                root, statement_id=str(statement_id or ""), proof_no=proof_number,
                proof_sha256=str((row or {}).get("proof_sha256") or sha),
                review_call=_row_call or str(review_call or ""), need=out["need"])
            out["sign_count"] = dict(counted)
            out["counted_by"] = str(counted.get("counted_by") or "")
            #: 2026-11-17（业主）：门槛随这一档走 —— E 的单轮会审是 1（实验侧报告不承重），
            #: F / B 仍是 3。计数层给了它用的数，读数就报那个数（不许"数用 1、报 3"）。
            out["need"] = int(counted.get("need") or out["need"])
            out["streak"] = int(counted.get("count") or 0)
            out["projected"] = out["streak"] if candidate_ok else 0
            out["streak_ok"] = bool(counted.get("ok")) and candidate_ok
            out["basis"] = [
                f"system_count={out['streak']}", f"need={out['need']}",
                (f"within_call={within}（调用方自称，只作读数）" if within is not None
                 else f"review_call={_row_call or '（空）'}"),
                f"counted_by={out['counted_by'] or '（没读到）'}",
            ]
            if not counted.get("checked"):
                out.update(checked=False, issue=False, decision=JUDGE_UNCHECKED,
                           reason=("系统计数没查成（"
                                   + str(counted.get("why") or "没有任何读数")
                                   + "）⇒ 不放签（不是「没问题」，也不是「次数不够」）"))
                self._note_sign_issuance(out, task_id=task_id)
                return out
        else:
            if landed:
                out["projected"] = out["streak"] if candidate_ok else 0
            else:
                out["projected"] = ((out["streak"] + 1) if (same_sha and candidate_ok)
                                   else (1 if candidate_ok else 0))
            out["streak_ok"] = bool(out["projected"] >= int(out["need"]))
            out["basis"] = [f"streak={out['streak']}", f"need={out['need']}",
                            f"same_sha={same_sha}"]
        if not bool(reading.get("checked")) and within is None:
            out["reason"] = (f"台账那一格没查成（{str(reading.get('why') or '')[:160]}）"
                             "⇒ 不放签（不是「没问题」）")
            self._note_sign_issuance(out, task_id=task_id)
            return out
        # 递给模型的材料：只有读数，没有证明正文（I12 同一条纪律）。
        #
        # 要求 ④（2026-11-02）：`within_call` 一旦给出，台账就是历史读数 ——
        # 材料里「不放」任何台账派生的格子（`state` / `ledger_streak_history` /
        # 台账算出来的 `same_sha`）。同一趟送审的三轮由 V 的循环保证是同一份正文，
        # 所以这里给 `same_sha=True` 是"这一趟的事实"，不是台账读数。
        if within is not None or counted:
            material = {
                "statement_id": str(statement_id or ""), "proof_no": proof_number,
                "within_call": within,
                #: 2026-11-17：材料里放的是框架现数的那几格（`within_call` 只作
                #: 调用方自称的读数，不参与判定）。
                "counted_by": out.get("counted_by") or "",
                "count": int(out.get("streak") or 0),
                "streak": out["projected"], "need": out["need"],
                "projected": out["projected"], "streak_ok": out["streak_ok"],
                "same_sha": True,
                "candidate_verdict": str(v.get("verdict") or ""),
                "candidate_axis": candidate_axis,
                "candidate_defect_step": v.get("defect_step"),
                "reading_why": ("这一签的门槛由框架按这一趟送审自己数（跨趟不累计、"
                                "同号重放不增加）；调用方递进来的轮数只作读数"),
            }
        else:
            material = {
                "statement_id": str(statement_id or ""), "proof_no": proof_number,
                "state": out["state"],
                "streak": out["streak"],
                "need": out["need"],
                "projected": out["projected"], "streak_ok": out["streak_ok"],
                "same_sha": same_sha, "candidate_verdict": str(v.get("verdict") or ""),
                "candidate_axis": candidate_axis,
                "candidate_defect_step": v.get("defect_step"),
                "reading_why": str(reading.get("why") or reading_problem)[:400],
            }
        out["material"] = dict(material)
        # ---- 没有判断面：只对旧直调（没给 `within_call`）保留装配纪律 -------------
        #
        # 2026-11-16 裁定 ③ 之后，发签不再问模型；`within_call` 给了就说明这是 V 的
        # 连判循环（那一转的 clean 已经由 `judge_v_reply` 判过），本方法只按地板发签。
        # 不给 `within_call` 的旧直调没有上面那道语义判定，于是仍要求这一名秘书有
        # 判断面 —— 否则"没有秘书"会被读成"再签几次就有了"。
        if within is None and (self.seam is None or not self.enable_model):
            out["reason"] = ("这一名秘书没有判断面（没有缝 / 开关关着）⇒ 判定没查成："
                             "不放签（checked=False 不是「可以签」，也不是「次数不够」）")
            self._note_sign_issuance(out, task_id=task_id)
            return out
        if not out["streak_ok"]:
            # 地板没过 ⇒ 这一签不发（也不问模型：没有"模型点头"这一层了）。这一句只是
            # "这一转还不算一票"的读数，不是终局：终局由 `agent_v.core` 的循环给。
            out.update(checked=True, issue=False, decision=SIGN_WITHHOLD,
                       reason=(f"系统计数 {out['projected']}/{out['need']}"
                               f"（{out['counted_by'] or 'legacy:ledger_tail'}）"
                               "⇒ 这一签不发；门槛还没到（由框架从台账现数，"
                               "不是调用方递进来的那个数）"
                               + ("" if within is None else "；调用方的轮数只作读数")),
                       basis=list(out["basis"]))
            self._note_sign_issuance(out, task_id=task_id)
            return out
        # ---- 2026-11-16 裁定 ①②③：地板过了 ⇒ 系统自动发签 ----------------------
        #
        # 系统计数够门槛（`sign_counting` 数到 `count >= need`，且这一签的轴是 clean）
        # 就是发签的唯一条件；调用方自报的轮数（`within_call`）只作读数。原先这里还有
        # 一次"问模型签发 / 不签发"（`SIGN_ISSUANCE_VERDICTS` 的消费处），已按裁定 ③
        # 删除：发签不由模型点头，签名由秘书直接落进稿里。
        out.update(checked=True, issue=True, decision=SIGN_ISSUE,
                   reason=(f"系统计数 {out['projected']}/{out['need']}"
                           f"（{out['counted_by'] or 'legacy:ledger_tail'}）"
                           f"⇒ 地板已过：由 V 的秘书自动发签（不问模型）"),
                   basis=list(out["basis"]) + ["auto_issue:floor_passed"])
        self._land_sign_issuance(out, proof_text=str(proof_text or ""),
                                 proof_no=proof_no, row=row)
        self._note_sign_issuance(out, task_id=task_id)
        return out

    def sign_recipient(self) -> str:
        """这一签的收方秘书（`secretary:F` / `secretary:B`；读不到 ⇒ 空串）。

        2026-11-02 业主口径：V 只颁发，手稿块与台账位由收方秘书落；收方 = V 的
        parent（谁送审谁收签）。身份只有一个来源：`conductor.current_parent()`（运行期
        `calling_as` 挂上来的那一位，不是模型给的一个参数，也不是"谁是 V 就谁落"）。
        读不到就回空串 —— 那一档能颁发、不能落块（`vsigns.land` 会受控拒绝
        `not_a_secretary`），不许拿 `self.role`（那是 V 自己的角色）去凑一个收方。
        """
        from . import conductor as _CND

        _pid, prole = _CND.current_parent()
        try:
            from . import vsigns as _VS

            return _VS.secretary_id(prole)
        except Exception:  # noqa: BLE001 —— 读不到就"没有收方秘书"，不猜
            return ""

    @property
    def actor_label(self) -> str:
        """这一名秘书在"落签"这一步的身份值（`secretary:F` / `secretary:B`；读不到 ⇒ 空串）。

        为什么不是简单的 `secretary:{self.role}`：V 的秘书不是收方 —— 收方是 V 的 parent
        那一侧（`sign_recipient()` 读的就是它）。只有收方秘书自己的实例（角色 F / B）才按
        自己的角色。V 的秘书拿 `secretary:V` 去凑一个 `by=` 会被 `vsigns.land` 受控拒绝
        `not_a_secretary`；把它折成"随便一个 F/B"更是猜。
        """
        from . import vsigns

        own = vsigns.secretary_id(self.role)
        return own or self.sign_recipient()

    def land_unregistered_sign(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        """落一份未在册的 V 签（2026-11-03 件三：落签只经秘书这一侧）。

        `envelope` = :func:`vsigns.issue` 的整份返回（不是里面那个 `envelope` 子字典）：
        V 只把这一份交过来，落点（块 + 台账位）由本方法判 ——

        - 块：签文件里的 `artifact_path`（未在册没有命题号，落点就是那一份手稿）；
        - 台账位：未在册没有命题行可翻 ⇒ `ledger_bit=False`（不在这里造一格）；
        - 落签者：`self.actor_label`（收方那一位；空串 ⇒ `vsigns.land` 的
          `not_a_secretary` 会把它拒掉，校验不绕过）。

        返回 `vsigns.land` 的读数（另带 `envelope_to` / `artifact_sha`，供调用方核对）。
        不在颁发这一档里落签：`issue` 没成功（`written` / `idempotent` 都不是真）⇒
        `code="not_issued"`、零字节 —— 盘上可能残留旧签文件，不许拿它冒充这一趟。
        """
        from . import vsigns

        issued = dict(envelope) if isinstance(envelope, Mapping) else {}
        doc = dict(issued.get("sign") or {}) if isinstance(issued.get("sign"), Mapping) else {}
        out: dict[str, Any] = {
            "checked": False, "landed": False, "state": "refused", "code": "",
            "by": self.actor_label, "artifact_sha": "", "manuscript_id": "",
            "body_mismatch": False, "manuscript_write": {}, "ledger_bit": "not_attempted",
            "ledger_why": "", "sign_recorded": False, "reason": "",
            "envelope_to": "",
        }
        if not (issued.get("written") or issued.get("idempotent")):
            out.update(code="not_issued",
                       reason=("这一份签没有颁发成功（`written` / `idempotent` 都不是真）⇒ "
                               "没有可落的东西：不落块、不翻位（零字节）"))
            return out
        if out["by"] not in vsigns.SECRETARY_OF:
            out.update(code=vsigns.NOT_A_SECRETARY,
                       reason=(f"`by={out['by']!r}` 不是收方秘书 ⇒ 不落签（一个字节都不写）："
                               f"只认 {list(vsigns.SECRETARY_OF)}"))
            return out
        sha = str(doc.get("artifact_sha") or "")
        if not sha:
            # `issue` 的返回里 `path` 是 `out/vsigns/<sha>.json`：文件名就是 sha。
            name = str(issued.get("path") or "").rsplit("/", 1)[-1]
            sha = name[:-5] if name.endswith(".json") else name
        out["artifact_sha"] = sha
        env = vsigns.sign_envelope(doc)
        out["envelope_to"] = str(env.get("to") or "")
        # 与 `vsigns.land` 同一条判据：信封写了收件人才比对；旧签没有信封（`to=""`）
        # 按落签那一侧的规矩走，不在秘书这一层凭空收紧（84 的未在册签就是旧写法）。
        if env.get("to") and env.get("to") != out["by"]:
            out.update(code="addressed_to_another_secretary",
                       reason=(f"这一签的信封写给 {out['envelope_to']!r}，不是 {out['by']!r} ⇒ "
                               "不落（零字节：别的秘书的签不许被这一位落）"))
            return out
        root = self.store.root if self.store is not None else self.root
        landed = vsigns.land(
            root, artifact_sha=sha, by=out["by"],
            manuscript_path=str(doc.get("artifact_path") or ""),
            store=None, statement_id="", proof_no=doc.get("proof_no"),
            # 未在册没有命题行可翻：台账位这一路不翻、也不许在这里造一格。
            ledger_bit=False)
        out.update(landed)
        out["by"] = str(landed.get("by") or out["by"])
        out["artifact_sha"] = str(landed.get("artifact_sha") or out["artifact_sha"])
        return out

    def _land_sign_issuance(self, out: dict[str, Any], *, proof_text: str,
                            proof_no: Any, row: Mapping[str, Any] | None) -> None:
        """把"签发"这个决定落成一份签（2026-11-08 起：不碰 `statements`）。

        三态：签颁发了（`issued=True`）/ 没有可落的那一行（没有 store 或没有 row）/
        颁发了但块没落（`vsign` / `manuscript_write` 自己报的理由）。三种都不改变
        `issue` 这一个决定 —— 决定是决定，落地是落地（`draft/125` 三态纪律）。

        为什么不再调 `verifications.sign_statement`：那条会在
        `store.tx("statements")` 里翻第 3 位、抬 `kind`、现算 `grade`。业主 2026-11-08
        的口径是「V 现在只对手稿负责，不该看台账了」「第几份证明、什么等级都是 B 秘书
        录入时关心且需负责的」⇒ V 的签只落在稿上（侧文件 + 九格块），命题行由 B 收录时
        按正文 sha 认领。`sign_statement` 保留给历史直调 / 夹具（`flip=True` 那条兼容门）。
        """
        from . import verifications as _VR

        # 这一格是"在原句上追加一句"：原先五条支各读一次 `out.get("reason")`，
        # 而它在本方法里直到写回之前没有任何一处改过 ⇒ 读一次就够。
        prior = str(out.get("reason") or "")
        if self.store is None:
            out["reason"] = (f"{prior}；但这一名秘书没有 store "
                             "⇒ 决定是「签发」，而落签那一步落不了（换装配："
                             "`for_role_wired(..., store=<本工作区的 store>)`）")
            return
        if not isinstance(row, Mapping) or not str(row.get("verification_id") or ""):
            out["reason"] = (f"{prior}；但没有可落的那一行"
                             "（`record_verification` 的返回行没递进来）⇒ 只落了决定")
            return
        try:
            writeback = _VR.land_sign_without_ledger(
                self.store, row=dict(row),
                within_call=out.get("within_call"),
                need=out.get("need"), review_call=str(out.get("review_call") or ""),
                by=self.sign_recipient(),
                manuscript=str(row.get("manuscript") or ""))
        except Exception as exc:  # noqa: BLE001 —— 落签失败要如实报（台账那一行已在盘上）
            name = type(exc).__name__
            out["writeback"] = {"written": False, "sign_issued": False,
                                "reason": f"落签没成（{name}: {exc}）"}
            out["reason"] = (f"{prior}；落签没成"
                             f"（{name}: {exc}）⇒ 签没落，台账那一行留着")
            return
        out["writeback"] = dict(writeback)
        out["manuscript_write"] = dict(writeback.get("manuscript_write") or {})
        out["issued"] = bool(writeback.get("sign_issued"))
        if not out["issued"]:
            out["reason"] = (f"{prior}；但落签没落成："
                             f"{str(writeback.get('reason') or '没有理由')}")
        elif not out["manuscript_write"].get("written"):
            out["reason"] = (f"{prior}；签已颁发，但手稿块没落"
                             f"（{str(writeback.get('reason') or '没有理由')}）")
        else:
            out["reason"] = (f"{prior}；签已颁发并由收方秘书落回手稿"
                             "（命题行由 B 收录时按正文 sha 认领）")

    def _note_sign_issuance(self, out: Mapping[str, Any], *, task_id: str = "") -> None:
        """把"发不发签"这一行落进决定台账（`before` = 台账读数，`after` = 决定）。

        为什么单独一个私有方法（而不再塞进 `decide_sign_issuance` 的每一支）：返回句有
        六条路（读不成 / 没查成 / 地板没过 / 判不了 / 词表外 / 判了），而每一条都要
        留痕 —— 六处各写一遍必然漏一处，而漏的那一处正好会是"没发签"的那条路。
        """
        self.note_decision(
            duty=2, kind=KIND_DECISION,
            decision=str(out.get("decision") or JUDGE_UNCHECKED),
            reason=str(out.get("reason") or ""),
            basis=list(out.get("basis") or []),
            target={"sign_issuance": str(out.get("statement_id") or "")},
            judge={k: out.get(k) for k in
                   ("checked", "issue", "decision", "streak", "need", "streak_ok",
                    "projected", "same_sha", "state", "reading", "cost",
                    "within_call", "ledger_streak", "review_call")},
            before=json.dumps(dict(out.get("material") or {}), ensure_ascii=False,
                              sort_keys=True, default=str)[:2000],
            after=(f"issue={bool(out.get('issue'))}；decision={out.get('decision')!r}"
                   f"；连续 {out.get('projected')}/{out.get('need')}"),
            fail_open=False,
        )

    def wash_v_reply(self, *, reply: str, verdict: str = "", defect_step: Any = None,
                     statement_id: str = "", proof_no: Any = 1,
                     task_id: str = "", label: str = "") -> dict[str, Any]:
        """把 V 的意见洗成能转达给 F 的文本（业主 2026-10-29 的 C 段）。

        仿 :meth:`wash_dependency_face` 的三态，但有一处刻意不同：那一支洗失败时
        返回原稿（那是 F 自己的稿子，退回原文不是泄露），这一支洗失败时不输出原文
        —— V 的回复正文不许原样递到 F 面前（业主口径：洗稿转达；`draft/125` §二 C
        「洗不出来 ⇒ 受控拒绝、不输出原文」）。所以 `refused=True` 时 `text` 恒空串。

        ## findings 必须逐字可回溯（`judges._ground` 的纪律）
        模型给的每条 `findings[*].quote` 都要在 V 的回复原文里逐字找到（只压空白差异），
        找不到的落进 `dropped` 并不采信；一条都没落地、而模型又给了 findings ⇒
        `refused="findings_not_grounded"`（说明这一次洗出来的话在原文里没有着落）。
        洗过的那份文本 = 模型给的 `text`（那是转述，不是原文）。

        ## 落痕
        进 `decisions_path()` 那本账（`before` = V 原文、`after` = 洗过的文本、
        `changes` = 逐条改了哪几处、`judge` = 这一趟的洗稿读数）。不写 `relay.jsonl`
        —— 那一份是转达链自己的账，两件事写在同一处会让"谁洗的"与"谁转达的"分不开。

        返回键：`checked` / `washed` / `text` / `findings` / `dropped` / `refused` /
        `reason` / `actor` / `changes` / `cost` / `material`。
        """
        from . import judges as _J   # 惰性：落地判据（`judges._ground`）的唯一实现在这里
        from . import verifications as _VR

        out: dict[str, Any] = {
            "checked": False, "washed": False,
            #: 洗不动时恒空串：这一格不许退化成"原文"（那正是要挡的那件事）。
            "text": "", "findings": [], "dropped": [], "refused": "",
            "reason": "", "actor": f"secretary-{self.role}", "changes": [], "cost": {},
            "material": {}, "statement_id": str(statement_id or ""), "proof_no": 0,
        }
        try:
            out["proof_no"] = int(_VR.as_proof_no(proof_no) or 0)
        except (TypeError, ValueError):
            out["proof_no"] = 0
        body = str(reply or "").strip()
        if not body:
            out.update(checked=True, refused="empty_reply",
                       reason="V 的回复正文是空的 ⇒ 没有可洗的东西（也就没有可转达的意见）")
            self._note_wash(out, reply="", task_id=task_id)
            return out
        if self.seam is None or not self.enable_model:
            out.update(refused="secretary_unavailable",
                       reason=("这一名秘书没有判断面（没有缝 / 开关关着）⇒ 洗不出来："
                               "受控拒绝，不输出 V 的原文（洗稿转达是这一档的唯一出口）"))
            self._note_wash(out, reply=body, task_id=task_id)
            return out
        material = {"v_reply": body[:JUDGE_MATERIAL_CAP],
                    "ledger_row": {"verdict": str(verdict or ""), "defect_step": defect_step},
                    "label": str(label or "")}
        out["material"] = dict(material)
        prompt = (
            "把下面这段验证者（V）的审阅回复改写成转达给作者（F）的工作意见。"
            "只回一个 JSON 对象，字段：\n"
            "text（改写后的正文：第三人称、按「指到哪一步 / 问题是什么 / 下一步补什么」"
            "分条写；不要照抄原文的句子，不要复述 V 的第一人称口气，"
            "不要评价作者的思路好不好；只写能据以动手的结论）、\n"
            "findings（字符串数组或对象数组：每一条给 `quote` = 你在原文里逐字引用的那一句、"
            "`why` = 它说明什么问题。`quote` 必须与原文逐字相同（只允许空白差异），"
            "改了字就不采信）、\n"
            "step（整数或 null：这一条意见指向第几步）。\n"
            "不许写原文里没有的意思；原文没指出缺陷时，text 就写「这一轮没有指出缺陷」"
            "与它实际核过的东西，findings 给空数组。\n\n"
            + _judge_material(material))
        try:
            data, call = self.seam.ask_json(prompt, system=_wash_v_system(),
                                            task_id=task_id, note="secretary:wash_v_reply")
        except Exception as exc:  # noqa: BLE001 —— 调用失败 = 洗不出来（受控拒绝）
            out.update(refused="wash_call_failed",
                       reason=f"洗稿调用失败（{type(exc).__name__}: {exc}）⇒ 不输出原文")
            self._note_wash(out, reply=body, task_id=task_id)
            return out
        if not getattr(call, "ok", False) or not isinstance(data, Mapping):
            out.update(refused="wash_no_reply",
                       reason=(f"洗稿没拿到可用的 JSON（{getattr(call, 'problem', '') or 'no_reply'}:"
                               f"{str(getattr(call, 'detail', '') or '')[:160]}）⇒ 不输出原文"))
            self._note_wash(out, reply=body, task_id=task_id)
            return out
        washed = str(data.get("text") or "").strip()
        kept, dropped = _J._ground(body, data.get("findings"))
        out["findings"] = kept
        out["dropped"] = dropped
        proposed = data.get("findings")
        if not washed:
            out.update(refused="wash_empty_text",
                       reason="模型没有给出改写后的正文 ⇒ 洗不出来（不输出原文）")
            self._note_wash(out, reply=body, task_id=task_id)
            return out
        if isinstance(proposed, (list, tuple)) and proposed and not kept:
            # 给了 findings、而一条都引不回原文 ⇒ 这一遍洗出来的话没有着落。
            out.update(refused="findings_not_grounded",
                       reason=(f"模型给了 {len(proposed)} 条 findings，没有一条能逐字落回 "
                               "V 的原文 ⇒ 不采信这一遍（不输出原文）"))
            self._note_wash(out, reply=body, task_id=task_id)
            return out
        if washed == body:
            # 逐字相同 = 没有洗过（这一档最危险：它长得像"洗好了"）。
            out.update(refused="wash_verbatim",
                       reason="改写后的正文与 V 的原文逐字相同 ⇒ 不算洗过（不输出原文）")
            self._note_wash(out, reply=body, task_id=task_id)
            return out
        out.update(checked=True, washed=True, text=washed,
                   reason=(f"洗过：{len(kept)} 条 findings 逐字落回原文"
                           + (f"，{len(dropped)} 条引不到被丢弃" if dropped else "")))
        out["changes"] = [{"field": "text", "from": "（V 的原文，不转达）", "to": washed,
                           "why": "洗稿转达：原文不外发（业主 2026-10-29 的 C 段）"}]
        out["changes"].extend(
            {"field": "findings", "from": str(d.get("quote") or ""),
             "to": "（丢弃）", "why": str(d.get("why") or "引文落不回原文")}
            for d in dropped)
        self._note_wash(out, reply=body, task_id=task_id)
        return out

    def _note_wash(self, out: Mapping[str, Any], *, reply: str, task_id: str = "") -> None:
        """把洗稿这一行落进决定台账（`before` = 原文、`after` = 洗过的文本）。

        与 :meth:`_note_sign_issuance` 同一条理由：返回句有六条路，每一条都要留痕。
        注意 `before` 落的是原文：那本账是秘书自己的账（不是给 F 看的），
        而"洗的时候原文长什么样"是复核这一遍洗得对不对的唯一依据。
        """
        self.note_decision(
            duty=2, kind=KIND_DECISION,
            decision=("已洗稿" if out.get("washed") else "洗不出来"),
            reason=str(out.get("reason") or ""),
            basis=[f"refused={out.get('refused') or '（没拒）'}",
                   f"findings={len(out.get('findings') or [])}",
                   f"dropped={len(out.get('dropped') or [])}"],
            target={"wash_v_reply": str(out.get("statement_id") or "")},
            judge={k: out.get(k) for k in
                   ("checked", "washed", "refused", "findings", "dropped",
                    "statement_id", "proof_no")},
            before=str(reply or "")[:2000],
            after=str(out.get("text") or "")[:2000],
            changes=[dict(c) for c in (out.get("changes") or [])][:20],
            fail_open=False,
        )


def v_reply_fault_reading(*, decision: str, defect_kind: Any = "",
                          report_gap: Any = "", reason: Any = "") -> dict[str, Any]:
    """把 `v_reply_defect` 那一问的答案读成 `(axis, fault_kind, fault_cause, report_gap)`。

    这是写侧分类的第一半（纯函数，零 IO、不碰模型）：秘书那一问的
    `decision` / `defect_kind` / `report_gap` 三格 + 它自己的 `reason`，在这里翻译成
    台账 `secretary_judge` 格里要落的那几个键。第二半（写行处的护栏与兜底）在
    `agent_v/core.py` 的 `_write_fault_cell`：那里才拿得到 findings / defect_step。

    判据（与 D3 §3.1 / §5.3 逐条对得上）：

    1. `decision` 不在两档词表里（`判不了` / 空 / 别的写法）⇒ `axis=""`：那不是一种
       结论（"没有判不了"这条纪律），四个类别格全部留空，由调用方按"没查成"处置。
    2. `decision=没问题` ⇒ `axis="clean"`、`kind=""`；`report_gap` 非空时
       `cause="report_gap"`（报告质量读数，不影响投票）。模型若同时给了 `defect_kind`
       ⇒ 不采信（clean 行带 kind 是自相矛盾行；`is_a_vote` 会 fail-closed 把它吞掉，
       所以归一必须在写侧做 —— D3 §5.3）。
    3. `decision=有缺陷要指出` ⇒ `axis="fault"`，`kind` 只认
       `verifications.FAULT_KINDS` 里的四类；不认识的写法一律留空（写行处按 `math`
       兜底 —— 缺 kind 的新行不许静默解锁，D3 §5.3）。
    4. `defect_kind="report_gap"`（模型把"只缺反例尝试记录"写进这一格）⇒ 归到
       `kind=""`、`cause="report_gap"`：它不是缺陷。`axis` 这里仍是 `fault`，
       由写行处（拿到 findings / defect_step 之后）决定要不要翻成 clean ——
       只有"没有数学证据"时才翻（护栏只许往更严的方向折）。
    5. `kind="procedural"` ⇒ `cause="self_declared"`（V 自己说没逐行验证）；
       其余类别 `cause=""`。

    返回键固定四个，每一行都写：`fault_kind` 可以为空串、
    `fault_cause` 可以为空串，但键必须在 —— 键在不在是"新行 / 老行"的唯一分界
    （`verifications.fault_kind_of` 读的就是它）。
    """
    out: dict[str, Any] = {
        "axis": "", "fault_kind": "", "fault_cause": "", "report_gap": "",
    }
    gap = str(report_gap or "").strip()
    kind = str(defect_kind or "").strip()
    axis = V_REPLY_AXIS.get(str(decision or "").strip(), "")
    if axis == "clean":
        out.update(axis="clean", fault_kind="",
                   fault_cause=("report_gap" if gap else ""), report_gap=gap)
        return out
    if axis != "fault":
        # 词表外（`判不了` / 空串 / 历史写法）：不是一种结论 ⇒ 没有轴、没有类别。
        return out
    if kind == "report_gap":
        # 模型把"只缺反例尝试记录"写进 kind（批 1 的旧写法）：按裁定 ① 归到 cause。
        out.update(axis="fault", fault_kind="", fault_cause="report_gap",
                   report_gap=(gap or str(reason or "").strip()))
        return out
    from . import verifications as _VR   # 惰性：词表本体只有一处（`FAULT_KINDS`）

    if kind not in _VR.FAULT_KINDS:
        # 不认识的写法 / 没给：kind 留空，写行处按 math 兜底（缺 kind 的新行不许静默解锁）。
        kind = ""
    cause = "self_declared" if kind == "procedural" else ""
    out.update(axis="fault", fault_kind=kind, fault_cause=cause, report_gap=gap)
    return out
