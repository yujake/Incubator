# -*- coding: utf-8 -*-
"""秘书的档位判据（力气读数 + 指路，从 secretary.py 的 U25 前半逐字搬出）。

我保证哪条不变式：档位由力气读数定，不由分数定；材料被截断时必须在读数里点名截断了什么 —— 截断而不说，等于把「没看到」记成「看到了」。

## 为什么它能单独成文件（依赖方向）

`secretary_tier_judge` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_tier_judge` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from typing import Mapping
import hashlib
import json
import re

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    EMPTY_STATEMENT_TEXT,
    NONTRIVIALITY_UNJUDGED,
    NOT_APPLICABLE_KINDS,
)

from .secretary_prompts import (  # noqa: F401 — 这些名字由 secretary_prompts 定义
    JUDGE_MATERIAL_CAP,
)

from .secretary_tier_ledger import (  # noqa: F401 — 这些名字由 secretary_tier_ledger 定义
    _judged_body_sha,
    _statement_sha,
    _tier_from_judge_reply,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    JUDGE_UNCHECKED,
    KIND_DECISION,
    _nontriviality_level,
    nontriviality_label,
)


class TierJudgeMixin:
    """档位判据（力气读数 + 指路）（从 secretary.py 搬出的混入类）。"""

    def judge_statement(self, *, statement_full: str, statement: str = "",
                        source: str = "", basis_hint: str = "",
                        proof_text: str = "", proofs: list | None = None,
                        task_id: str = "", kind: str = "",
                        stmt_id: str = "", record: bool = False) -> dict[str, Any]:
        """B 的秘书专属：这条待入库的命题落在非平凡性的哪一档。

        ## 判与落拆成两段（NT2，2026-11-15 业主裁定）

        这个方法只判、不写盘（缺省 `record=False`）。业主口径：B 处理一条录入任务时，
        第一个动作是判非平凡度；等登记/匹配那一笔拿到 `stmt_id` 与 `path_group` 之后，
        才由 :meth:`record_nontriviality` 追加台账行。判在这里落行的旧形状有两个毛病：

        - 号还没发下来 ⇒ 真机落了 6 行 `stmt_id` 为空的孤儿读数（其中 4 行正文 sha
          对不上任何命题行，钱花了、读数读不到任何一条命题）；
        - 判档挂在"工具返回之后"（`agent_loop._do_tool`）⇒ 台账写发生在判之前，
          与业主"先判再录"的顺序正好相反。

        `record=True` 只为"没有登记这一笔动作、直调判档"的旧调用面（判据 / 存量补写）
        留着：它落一行 statement-scope 的行（`path_group=0`）。生产面（B 的收录动作、
        F 交稿、概念行的幂等补写）一律走 :meth:`record_nontriviality` —— 那条路要求
        `stmt_id` 与路径号，拿不到就不落（并留 `unrecorded` 痕迹）。

        `stmt_id` 是这条命题在 `statements` 里的号（只在 `record=True` 时被用到）：
        台账那一行靠它对上命题行（按正文 sha 关联会把"改了一个字"读成"没判过"）。

        为什么是"秘书"而不是又一条机器判据：平凡与否不是字符串能判的事（`a+b=b+a` 与一条
        真定理的字面形态可能很像），它属于本仓划给秘书的那一类判断 —— 机器只摆材料，
        结论由本体自己的缝给。

        ## 两态（判不了退场为"没查成"）

        | 结局 | 返回 |
        |---|---|
        | 有档 | `checked=True` + `decision ∈ {"T0"…"T4"}` + `nontriviality` 同值 + `label` |
        | 没查成 | `checked=False` + `reason`；不落档位行；决定台账写 `decision="没查成"` |
        | 不是 B 的秘书 | `checked=False` + 理由（这一问只属于 B） |
        | 正文 0 字 | `checked=False` + `code=empty_statement_text`（不判档、不发调用、不落台账） |

        "没查成"的来路：模型给 null / 旧词 / 坏 JSON、调用失败、正文被截断、一项力气读数都
        取不到。处置都是"重试 / 重交 / 人看" —— 所以盘上不许留一条 `nontriviality: null`
        的行冒充"判过了但没档"。

        ## 材料里的 `effort` 只是参考读数

        机器数好的四项（体量 / 步骤 / 引理 / 工具簇跨度）外加绕路与分数
        （:func:`proof_effort_readings`）只作材料；档位由秘书按五档定义判，
        `proof_effort_readings` 不落格、也不拿来补一个档位。

        三条"谁是权威"：档位由模型判；读数缺项或正文被截断 ⇒ `checked=False`（不发调用、
        不落档位行，reason 点名缺哪项，不许落 0 冒充"基础定理"）；`decision` 是唯一主字段
        （审美轴三格已退场），给 `T0`…`T4` 就是档位，给 null / 旧词一律"没查成"。

        ## 旧行怎么读

        新行只写 `T0`…`T4`；旧台账里的三个旧词由 :func:`_tier_from_legacy_decision` 折算
        （太平凡 ⇒ T0；合格 ⇒ 读 `judge.nontriviality` / 同号档位行，都没有 ⇒ 未判；
        判不了 ⇒ 未判）。2026-11-01 之前的两字段判词形状（`decision="合格"` +
        `nontriviality=2`）仍按旧别名读，decision 能解析时以 decision 为准。

        `proof_text` / `proofs` 可选：正文里自带证明小节时读数照样读得到，
        真读不到就是"缺证明正文"那一支。

        ## 概念 / 定义行：判档"不适用"

        判据是"这份证明花了多大力气"，而概念行没有证明正文（`conceptrows.concept_statement`
        明令 `proof_text` 留空）⇒ 四项读数一项都取不到。`kind` 落在
        :data:`NOT_APPLICABLE_KINDS` 时在取材料之前就早退：不发调用、不判力气，
        只落一条"不适用"（台账里 `applicable: false`）。这一支放在角色那一关之前 ——
        概念的"力气"这一问与哪一名的秘书无关。
        """
        if _is_not_applicable_kind(kind):
            return self.not_applicable_nontriviality(
                statement_full=statement_full, kind=kind, task_id=task_id,
                stmt_id=stmt_id, record=record)
        if str(self.role) != "B":
            return {"checked": False, "decision": "", "basis": [],
                    "reason": f"这一问只属于 B 的秘书（本条秘书属于 {self.role!r}）⇒ 这一格没查成",
                    "cost": {"ledger": "", "reason": "没发调用（不是 B 的秘书）"}}
        # ---- 0 字命题：不进判档流程（B2 的第 1 条，2026-10-24）
        #
        # 空正文那一行根本不该存在：空正文不是一个"判不了的对象"，它是"没有对象" ——
        # 判它一次要花一次模型调用，而结论只能是"没东西可判"。所以这一格在取材料之前
        # 就受控拒绝：不发调用、不落台账（判不了的读数也不留 —— 它会被读成"有人判过"）。
        body_full = str(statement_full or "")
        if not body_full.strip():
            return {"checked": False, "decision": "", "basis": [],
                    "code": EMPTY_STATEMENT_TEXT,
                    "reason": ("这一条命题的正文是 0 字 ⇒ 不进判档位（受控拒绝）。"
                               "空正文不是「材料不足」：它没有可判的对象，四项力气读数"
                               "（体量/步骤/引理/跨度）一项都取不到。把含完整假设的正文"
                               "交上来再判；`kind=\"concept\"` 的空定义走登记那条路，"
                               "不经过这一问"),
                    "nontriviality": NONTRIVIALITY_UNJUDGED, "label": "",
                    "nontriviality_tri": "unjudged", "nontriviality_basis": "",
                    "effort": {}, "text_truncated": False,
                    "cost": {"ledger": "", "reason": "没发调用（正文 0 字 ⇒ 不进判档位）"}}
        # ---- 力气读数（B2 的机器侧：只是参考读数，判档位的是秘书的模型）
        #
        # `proofs` 是 B 一次交上来的多份证明（多证明模型）：任一份都算这份证明的力气，
        # 所以拼成一段一起读。`statement_full` 在它像一份证明正文时也参与（见
        # `_looks_like_a_proof`：真机上 B 有时把整段证明写进这一栏）。
        proof_bodies = [str(proof_text or "")]
        for item in (proofs or []):
            if isinstance(item, Mapping):
                proof_bodies.append(str(item.get("text") or item.get("proof_text") or ""))
        proof_joined = "\n\n".join(x for x in proof_bodies if str(x).strip())
        readings = proof_effort_readings(statement_full=body_full, proof_text=proof_joined,
                                         basis_hint=basis_hint)
        # 这几格都开到判据输入够用的上限，不做静默截断：秘书要判的是"这条命题
        # 平不平凡"，而命题的长尾（限定条件、量词顺序）正是决定平凡与否的部分。
        # 截到 2000 字符意味着它可能在对半条命题下结论，而那个结论会变成
        # "这条别收"。
        # 注意 `statement_full` 同时是缓存键的输入（见下面的 sha256）：键必须
        # 跟着一起变 —— 它变了是好事，"同一命题问第二遍不重复花钱"仍然成立，
        # 而两条前 2000 字符相同、之后不同的命题不再被误认成同一条。
        #
        # 多一格 `effort`（力气读数）。它按 `sort_keys` 排在材料最前面 ——
        # 万一材料真的被截断，模型至少已经看到读数本身，而不是只看到半句正文。
        context = {
            "effort": {k: readings.get(k) for k in
                       ("chars", "steps", "lemmas", "clusters", "cluster_names",
                        "detour", "score", "missing", "text_truncated", "truncated_at")},
            "statement_full": body_full[:20_000],
            "statement": str(statement or "")[:20_000],
            "source": str(source or "")[:4_000],
            "why_this_is_not_trivial": str(basis_hint or "")[:8_000],
        }
        # 截断读数：正文超上限、或材料 JSON 超上限，两种都算"输入不完整"。
        material_cut = material_truncation(context)
        body_cut = bool(readings.get("text_truncated"))
        text_truncated = bool(body_cut or material_cut["truncated"])
        if body_cut:
            at = int(readings.get("truncated_at") or PROOF_BODY_CAP)
            trunc_note = (f"这一条正文在 {at} 字处被截断（正文共 "
                          f"{int(readings.get('body_chars') or 0)} 字，判档位读的上限是 "
                          f"{at} 字）—— 档位判不了是因为输入不完整，不是因为材料不足")
        elif material_cut["truncated"]:
            trunc_note = (f"这一条正文在 {material_cut['at']} 字处被截断（材料共 "
                          f"{material_cut['chars']} 字，材料上限是 {material_cut['at']} 字）"
                          "—— 档位判不了是因为输入不完整，不是因为材料不足")
        else:
            trunc_note = ""

        def _unjudged(reason: str, *, cost_reason: str) -> dict[str, Any]:
            """这一格没查成：落一条 `decision=没查成` 的决定台账行，不落档位行。

            2026-11-01（第二刀）：判档只有两态。"没拿到判定"不是第四档，也不是一条
            `nontriviality: null` 的行 —— 后者会让"没人判过"在盘上冒充"判过了但没档"。
            """
            reason = str(reason)[:900]
            self.note_decision(
                duty=2, kind=KIND_DECISION, decision=JUDGE_UNCHECKED,
                reason=reason, target={"judge": "statement_aesthetic"}, basis=[],
                before=json.dumps({"statement_full": body_full,
                                   "why_this_is_not_trivial": str(basis_hint or "")},
                                  ensure_ascii=False, default=str)[:2000],
                fail_open=False,
            )
            return {"checked": False, "decision": "", "basis": [], "reason": reason,
                    "nontriviality": None, "label": "",
                    "nontriviality_tri": "unjudged", "nontriviality_basis": "",
                    "effort": readings, "text_truncated": bool(text_truncated),
                    "cost": {"ledger": "", "reason": cost_reason}}

        # 输入不完整 ⇒ 这一格没查成（不发调用、不落档位行）。这两支都必须在缓存/调用
        # 之前：截断的正文发去判档只会白花一次调用，而且回来也没有可用判定。
        if text_truncated:
            return _unjudged(trunc_note + "。这一格没查成：把正文拆段重交（分段登记）再判",
                             cost_reason="没发调用（正文被截断）")
        if not readings.get("chars"):
            return _unjudged(
                "这一条一项力气读数都取不到（最常见的是没有证明正文）⇒ 这一格没查成："
                "把完整证明交进 proof_text（或 statement_full 的证明小节）再判",
                cost_reason="没发调用（缺证明正文）")

        # 缓存键：命题正文 + B 写的素材 + 证明正文的摘要。第三项是 2026-10-24 加的 ——
        # 同一条定理的第二份证明是另一次判断（力气不同），拿正文键去沿用会把它判成第一次那一档。
        key = hashlib.sha256(
            (context["statement_full"] + "\x00" + context["why_this_is_not_trivial"]
             + "\x00" + hashlib.sha256(proof_joined.encode("utf-8")).hexdigest())
            .encode("utf-8")).hexdigest()
        prior = self._statement_verdicts.get(key)
        if prior is not None:
            # 同一个命题问第二遍：不花钱、结论不变（并在台账里留一行说清是沿用）。
            self.note_decision(
                duty=2, decision=str(prior.get("decision") or ""), fail_open=False,
                target="statement_aesthetic",
                before=json.dumps({"statement_full": context["statement_full"],
                                   "why_this_is_not_trivial": context["why_this_is_not_trivial"]},
                                  ensure_ascii=False, default=str)[:2000],
                after=str(prior.get("reason") or ""),
                reason="沿用本趟第一次的判断（同一个命题不重复花钱；结论与第一次逐字相同）",
                basis=[f"reused_sha256={key[:12]}"],
            )
            return {**prior, "reused": True, "reused_key": key[:12],
                    "cost": {"ledger": "", "reason": "没发调用（沿用本趟第一次的结论）"}}
        got = self.judge("statement_aesthetic", context, task_id=task_id)
        if not got.get("checked"):
            # `judge` 已经把这一趟落进决定台账（"没查成"），这里不再落第二条。
            return got
        # 2026-11-01（第二刀）：判档只有两态 —— 有 T0..T4，或者没查成。
        # `decision` 是唯一主字段；`nontriviality` 只剩旧形状的读别名。
        decided = str(got.get("decision") or "")
        level = _tier_from_judge_reply(got)
        if level is None:
            # checked=True 却没有可解析档位（旧替身 / 坏判词）⇒ 仍是"没查成"，不折档。
            return _unjudged(
                f"判词里没有可解析的档位（decision={decided!r}）⇒ 这一格没查成",
                cost_reason="没发调用（判词没有档位）")
        model_note = str(got.get("nontriviality_basis") or "")
        notes = [f"档位以秘书判定为准：{nontriviality_label(level)}"
                 f"（机器力气读数只作参考，score={int(readings.get('score') or 0)}）"]
        if level == 0:
            notes.append(f"降为 {nontriviality_label(0)}：力气读数只作参考"
                         f"（档位由秘书按五档定义判）；秘书原话："
                         f"{str(got.get('reason') or '')[:200]}")
        if model_note:
            notes.append(f"秘书原报档位依据：{model_note}")
        basis_note = "；".join(n for n in notes if n)[:900]
        got = {**got, "nontriviality": level, "label": nontriviality_label(level),
               "nontriviality_basis": basis_note,
               "nontriviality_tri": "computed",
               "effort": readings, "effort_score": int(readings.get("score") or 0),
               "text_truncated": False}
        # ---- 判与落拆开（NT2）：这里只判，正常路径一个字节都不写盘 -------------
        #
        # `record=True` 是旧直调面的兼容档（没有"登记这一笔"可依附）：它落一行
        # statement-scope 的行（`path_group=0`），并与旧行为逐字一致地按正文 sha 关联。
        # 生产面不许用它 —— B 的收录动作在拿到 `stmt_id` / `path_group` 之后走
        # `record_nontriviality`（见 `agent_b.register_statement._register_statement_impl`）。
        if record:
            judged_sha = _judged_body_sha(body_full, proof_joined)
            self.record_nontriviality(
                got, stmt_id=stmt_id, path_group=0, statement_full=body_full,
                landed_body_sha256=_statement_sha(body_full),
                judged_body_sha256=judged_sha)
        # 只记判过的结论（没查成不缓存，见 `_statement_verdicts` 的说明）。
        self._statement_verdicts[key] = dict(got)
        return got


#: 判档位读"力气"的那份正文最多读多少字（超出 ⇒ 这一趟的档位落「判不了 + 被截断」）。
#:
#: 与 :data:`JUDGE_MATERIAL_CAP` 分开：前者是"材料 JSON 有多长"，后者是"证明正文有多长"。
#: 两个数都必须显式，且都必须被 :func:`proof_effort_readings` 读到 —— 一处截断、另一处
#: 不知道，就是 2026-10-24 之前那个形态。
PROOF_BODY_CAP = 20_000


#: "不适用"那一格的理由（写进台账的 `basis`，也是页面上那句说明的出处，唯一一处）。
#:
#: 概念行的非平凡度不是"未判"，是"不适用（无证明）"。
#: 前者说的是"该判而没判"，后者说的是"这一问对它不成立"—— 两个词不许折平。
NONTRIVIALITY_NOT_APPLICABLE_BASIS = "不适用：概念行没有证明正文，不做力气判档"


def _is_not_applicable_kind(kind: Any) -> bool:
    """这个 kind 有没有"证明正文"这一档（概念/定义都没有 ⇒ 判档这一格不适用）。"""
    return str(kind or "").strip().lower() in NOT_APPLICABLE_KINDS


def _is_trivial_verdict(decision: Any) -> bool:
    """这一次判断的档位是不是 T0（唯一口径；不认旧词）。

    为什么要单独一个函数：T0 这一档有两个后果（落 T0 + 不在入库口拒收），两处必须问
    同一个问题。而这一条是"把'懂平凡'这一档打桩"的注射点 —— 判据要把"恒判平凡"
    打进去看非平凡那一支会不会红，就得有一个名字。

    只认档位（`"T0"` / `0` / `"0"`）。旧词到档位的折算只在读旧行时做
    （:func:`_tier_from_legacy_decision`）。
    """
    return _nontriviality_level(decision) == 0


#: 五项力气读数 → 各自的加分台阶（唯一一处定义在 `proof_effort_readings`）。
#:
#: 为什么这张表住在这一层（NT2 从 `agent_loop` 搬来）：note 是给模型看的指路牌
#: （"补哪一项能升档"），而档位本身由秘书（模型）按五档定义判 —— 这里一个字都不算档位，
#: 只把"这一条哪几项还在 0 分"翻成一句人话。判档搬进 B 的收录动作之后，这份读数也
#: 跟着走：它是"判"的产物，不是"循环"的产物。
_EFFORT_UPGRADE_STEPS: tuple[tuple[str, str, str], ...] = (
    ("体量", "chars", "每 2000 字 +1"),
    ("步骤", "steps", "每 6 步 +1"),
    ("引理", "lemmas", "每 2 条引理 +1"),
    ("工具簇跨度", "clusters", "跨到第 2 个工具簇才 +1"),
    ("绕路", "detour", "记下走过的一段死路 +1"),
)


def filing_tier_note(got: Mapping[str, Any]) -> str:
    """落 T0 那一格读数里的指路牌：按力气口径说清"还差哪一项、补哪一项能升档"。

    为什么不再是旧的两问（业主 2026-10-24 的裁定原话）：「不一定一条定理后面要用，
    也不一定存在"已知那条"，看证明花的力气就能判非平凡度」。旧口径的两个问题留在这句
    note 里，模型就会去编"谁会用到它"来升档 —— 而档位只由五项力气读数落格，
    那两个问题一个字都不参与（B 仍可以把它们写在 `why` 里给秘书看，只是不作判据，
    也不再是这一格教给模型的升档路径）。

    两档文案：材料里没有证明正文时点名"缺「证明正文」"并指到 `proof_text` /
    `proofs`；有力气读数时点名还在 0 分的那几项（每一项各 +1）。
    """
    head = ("证明里没有承重步骤 ⇒ 落 T0，照旧收录（业主 2026-10-23："
            "秘书不再因「太平凡」拦收录；2026-11-25：T0 判的是证明的力气，"
            "不是命题重不重要）。档位由秘书按五档定义判（业主 2026-10-29）："
            "五项读数 = 体量 / 步骤 / 引理 / 工具簇跨度 / 绕路")
    effort = got.get("effort")
    effort = dict(effort) if isinstance(effort, Mapping) else {}
    if not effort or list(effort.get("missing") or []):
        return (head + "。这一条缺「证明正文」这一项：五项读数一项都取不到 ⇒ 档位落「未判」。"
                "补上 proof_text（或 proofs=[{proof_no, text}] 里的正文）再交一次"
                "就能判出档位")
    chars = int(effort.get("chars") or 0)
    steps = int(effort.get("steps") or 0)
    lemmas = int(effort.get("lemmas") or 0)
    clusters = int(effort.get("clusters") or 0)
    detour = bool(effort.get("detour"))
    score = int(effort.get("score") or 0)
    label = str(got.get("label") or "") or "T0"
    still_zero = {"chars": chars // 2000 == 0, "steps": steps // 6 == 0,
                  "lemmas": lemmas // 2 == 0, "clusters": clusters < 2,
                  "detour": not detour}
    how = "、".join(f"{name}（{hint}）"
                    for name, key, hint in _EFFORT_UPGRADE_STEPS if still_zero[key])
    return (head + f"。这一条现在读到：体量 {chars} 字、步骤 {steps}、引理 {lemmas} 条、"
            f"工具簇 {clusters} 个、绕路{'有' if detour else '无'}"
            f"（力气分数 {score} ⇒ {label}）。"
            f"还在 0 分的项：{how or '（无，五项都进分了）'} —— 补哪一项就升档；"
            "证明正文写在 proof_text 里，多份证明写在 proofs=[{proof_no, text}]")


def filing_tier_reading(got: Mapping[str, Any] | None, *,
                        stmt_id: str = "") -> dict[str, Any] | None:
    """把一次判档（或一条台账读数）翻成"模型看得见的那一格"；不加档位就返回 `None`。

    业主 2026-10-23 的裁定：平凡不是"不许进"，是"进哪一档"（T0 = 证明里没有承重步骤，
    2026-11-25 把这句从事实级收成过程级 —— 见 :func:`judge_statement` 的说明）。
    所以只在两种情形给读数：判了 T0（`tier` + 指路 note）与"没查成"（未判 + 原因，
    且拿到号之后才给 —— 没有号的那一笔本来就不会有命题行可指）。

    这里不判档、不写盘：判在 B 的收录动作里（写之前），落由
    `record_nontriviality`（拿到号之后）。这一格只做整形，所以"档位是谁给的"不会在
    这一层分叉。台账读数形状（`tri` / `level`）与判词形状（`checked` / `decision`）
    都收：前者是 `_do_tool` 从刚落的那一行读回来的，后者是 B 动作层手里的原始判词。
    """
    if not isinstance(got, Mapping) or not got:
        return None
    if "tri" in got or "nontriviality_tri" in got:
        tri = str(got.get("tri") or got.get("nontriviality_tri") or "")
        level = _nontriviality_level(got.get("level", got.get("nontriviality")))
        checked = tri in ("computed", "not_applicable")
        reason = str(got.get("reason") or "")
    else:
        checked = bool(got.get("checked"))
        # 判词形状：`decision` 是唯一主字段，`nontriviality` 只是旧别名
        # （与 `judge_statement` 同一个读法：`_tier_from_judge_reply`）。
        level = _tier_from_judge_reply(got)
        reason = str(got.get("reason") or "判档没查成")
    if not checked or level is None:
        # 没有号的那一笔本来就没有命题行可指 ⇒ 不给"未判"读数（与判/落拆段之前
        # 那一支的边界逐字一致：有号才给原因）。
        if not str(stmt_id or "").strip():
            return None
        return {"tier": "", "label": "", "nontriviality": None,
                "nontriviality_tri": "unjudged", "matched_by": "",
                "downgraded": False, "decision": "",
                "reason": reason[:300],
                "judged_by": "secretary", "judge": "statement_aesthetic"}
    # 判词形状里 `decision` 是唯一主字段（T0 才是"平凡 ⇒ 落 T0"）；台账读数形状
    # 没有 `decision`，按 `level == 0` 读。两条都过同一个判据函数
    # （`_is_trivial_verdict` 是"这一档是不是 T0"的唯一口径，也是判据的打桩点）。
    decision = str(got.get("decision") or "").strip()
    if decision:
        if not _is_trivial_verdict(decision):
            return None
    elif level != 0:
        return None
    label = str(got.get("label") or "") or nontriviality_label(level)
    effort = got.get("effort")
    effort = dict(effort) if isinstance(effort, Mapping) else {}
    return {
        "tier": label or nontriviality_label(0),
        "label": label,
        "nontriviality": level,
        "nontriviality_tri": "computed",
        # 只带判档用得上的那几格读数：note 里的指路牌与台账里那一行都是按它们写的，
        # 模型不必去猜"为什么是这一档"（`cluster_evidence` 那类明细留在秘书台账里）。
        "effort": {k: effort.get(k) for k in
                   ("chars", "steps", "lemmas", "clusters", "detour", "score",
                    "missing", "body_from")},
        "downgraded": True,
        "decision": label,
        "reason": str(got.get("reason") or "")[:300],
        "basis": list(got.get("basis") or []),
        "note": filing_tier_note(got),
        "judged_by": "secretary",
        "judge": "statement_aesthetic",
    }


#: "跨度"读数的单位：工具簇。一个簇 = 一类论证工具；簇的个数就是"跨了几个领域"的机器读数。
#:
#: 为什么按簇数而不是按"领域"这个名字：数学里的领域边界是人的约定，而一份证明用了哪几类
#: 工具是文本里读得出来的。判据只认后者（可复算），前者留在 basis 的一句话里。
EFFORT_TOOL_CLUSTERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("group-action", ("群作用", "轨道", "稳定化子", "共轭", "陪集", "正规化子", "中心化子")),
    ("counting", ("同余", "模 p", "mod p", "Frobenius", "Lucas", "二项式", "计数",
                  "整除", "素因子")),
    ("linear", ("线性", "矩阵", "特征值", "张量", "维数", "对角", "秩")),
    ("analysis", ("连续", "极限", "测度", "积分", "收敛", "范数", "可微")),
    ("homology", ("同调", "上同调", "范畴", "函子", "层", "谱序列")),
    ("combinatorics", ("生成函数", "容斥", "双射", "极值", "图论", "Ramsey")),
    ("probability", ("期望", "方差", "随机", "概率", "大数")),
    ("formal", ("Lean", "Coq", "Isabelle", "形式化", "证明助手")),
)


#: 步骤读数的三个模式（取各自命中数的最大值，不求和：同一行可能被两条同时数到）。
_EFFORT_STEP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(\d+)[.、)．]\s", re.M),
    re.compile(r"^\s*#{2,4}\s", re.M),
    re.compile(r"(?:步骤|第)\s*(\d+)\s*步"),
    re.compile(r"Step\s*(\d+)", re.I),
)


#: 引理号（"引入了哪几条引理"）：引理 / 推论 / Lemma / Corollary 后面那个号。
_EFFORT_LEMMA_RE = re.compile(r"(?:引理|推论|Lemma|Corollary)\s*([0-9]+(?:\.[0-9]+)?)", re.I)


#: 引到的既有定理号（只作 basis 里的读数列出，不单独计分：它们已经通过"工具簇"与"引理数"
#: 两条读数进入了分数，再计一次就是同一个力气算两遍）。
_EFFORT_THEOREM_RE = re.compile(r"(?:定理|Theorem|命题|Proposition)\s*([0-9]+(?:\.[0-9]+)?)", re.I)


#: "绕了远路"的自述词：命中即说明这份证明自己说了"我避开了某条熟路"。
#: 它只认文本自述，不替作者判断"世上有没有更短的路"（那件事机器判不了）。
_EFFORT_DETOUR_WORDS: tuple[str, ...] = (
    "绕开", "绕远", "另证", "不依赖", "不使用", "避开", "非标准", "自足", "重新证明",
)


#: 一段文本"像不像一份证明正文"的判据（用于 statement_full 这一栏的回退读法）。
#:
#: 为什么需要它：业主写进 `specs/b.py` 的口径是"证明正文交在 proof_text 里"，而真机上
#: B 有时把整段证明写进 statement_full（sylow4 的那条 8375 字就是）。这一格只回答
#: "这段文本能不能当证明正文去读力气"，不回答"它是不是好证明"。
#:
#: ## 为什么只认结构标记、不认"证明正文"这四个字（2026-10-24 真机复算改的口径）
#: 第一版把 `证明正文` 与 `###` 也算标记，于是 sylow4 那几条 500 字上下的命题正文
#: 全被当成证明读了：它们写着"完整逐字证明见本行 proof_text""三者的证明只使用引理 0…"，
#: 于是"引理 0/1/2/3/4"被数成 5 条引理、档位凭空到 T2。提到证明不等于它是证明。
#: 现在只认真的开证/收证那一类标记；长正文（>= 2000 字）仍然直接算（真机那条 8375 字
#: 的整段证明就是这么认的）。
_EFFORT_PROOF_MARKERS: tuple[str, ...] = (
    "证明：", "证：", "证毕", "∎", "QED", "归纳法", "反证",
)


def _looks_like_a_proof(text: str) -> bool:
    """这段文本能不能当"证明正文"来读力气（判据见 :data:`_EFFORT_PROOF_MARKERS`）。

    太短的（< 40 字）一律不算：一条命题正文里出现"证："这种字眼时，40 字以下连一行
    推导都放不下，把它当证明读只会让读数虚高。
    """
    body = str(text or "")
    if len(body) >= 2000:
        return True
    if len(body.strip()) < 40:
        return False
    return any(mark in body for mark in _EFFORT_PROOF_MARKERS)


def proof_effort_readings(*, statement_full: str = "", proof_text: str = "",
                          basis_hint: str = "") -> dict[str, Any]:
    """这份证明花了多大力气（四项读数 + 绕路 + 分数），以及"哪一项读不到"。

    这是 B2 的机器侧：判档位的唯一判据。它是纯函数（不打桩、不读盘、不调模型），
    所以"档位是不是按力气判的"这件事可以被复算 —— 判据
    `tests/test_nontriviality_is_judged_by_effort.py` 的 (f) 就是把这里的输出打桩成全 0 /
    恒 T3，看 (c)/(d) 会不会跟着红。

    正文从哪来（按优先级，只取一处）：
    1. `proof_text`（`specs/b.py` 规定的"逐字证明摘录"那一栏）；
    2. `statement_full` 且它像一份证明正文（:func:`_looks_like_a_proof`）——
       真机上 B 有时把整段证明写进这一栏；
    3. 都没有 ⇒ `missing=["proof_body"]`：四项读数一项都取不到，档位必须落「判不了」。

    `basis_hint`（`why_this_is_not_trivial`）刻意不参与读数：那是 B 自己写的素材声明，
    把它当证据等于让被评的人自己报分数。它照旧进材料（模型看得到），但不进读数。

    返回的键：`chars` / `steps` / `lemmas` / `lemma_names` / `theorems` / `clusters` /
    `cluster_names` / `cluster_evidence` / `detour` / `detour_words` / `score` /
    `body_chars` / `body_from` / `missing` / `text_truncated` / `truncated_at`。
    """
    primary = str(proof_text or "")
    if primary.strip():
        body, body_from = primary, "proof_text"
    else:
        whole = str(statement_full or "")
        if _looks_like_a_proof(whole):
            body, body_from = whole, "statement_full"
        else:
            body, body_from = "", ""
    out: dict[str, Any] = {
        "chars": 0, "steps": 0, "lemmas": 0, "lemma_names": [], "theorems": 0,
        "clusters": 0, "cluster_names": [], "cluster_evidence": {},
        "detour": False, "detour_words": [], "score": 0,
        "body_chars": len(body), "body_from": body_from,
        "missing": [], "text_truncated": False, "truncated_at": 0,
    }
    if not body.strip():
        out["missing"] = ["proof_body"]
        return out
    # 截断先判：这一趟能读的只有前 PROOF_BODY_CAP 字，读不完就不许给档位
    # （业主口径：档位判不了是因为输入不完整，不是因为材料不足）。
    if len(body) > PROOF_BODY_CAP:
        out["text_truncated"] = True
        out["truncated_at"] = PROOF_BODY_CAP
    seen = body[:PROOF_BODY_CAP]
    steps = 0
    for pattern in _EFFORT_STEP_PATTERNS:
        steps = max(steps, len(pattern.findall(seen)))
    lemmas = sorted(set(_EFFORT_LEMMA_RE.findall(seen)))
    theorems = sorted(set(_EFFORT_THEOREM_RE.findall(seen)))
    evidence: dict[str, str] = {}
    for name, words in EFFORT_TOOL_CLUSTERS:
        hit = next((w for w in words if w in seen), "")
        if hit:
            evidence[name] = hit
    detour_words = [w for w in _EFFORT_DETOUR_WORDS if w in seen]
    chars = len(seen)
    score = ((chars // 2000) + (steps // 6) + (len(lemmas) // 2)
             + max(0, len(evidence) - 1) + (1 if detour_words else 0))
    out.update({
        "chars": chars, "steps": steps, "lemmas": len(lemmas),
        "lemma_names": lemmas, "theorems": len(theorems),
        "clusters": len(evidence), "cluster_names": sorted(evidence),
        "cluster_evidence": evidence, "detour": bool(detour_words),
        "detour_words": detour_words[:4], "score": score,
    })
    return out


def material_truncation(context: Mapping[str, Any]) -> dict[str, Any]:
    """判档位的那段材料会不会被截断 ⇒ `{"truncated", "at", "chars", "cap"}`。

    与 :func:`_judge_material` 用同一个渲染与同一个上限：两处各算一次长度，是这一格
    唯一能自证"我报的截断点就是模型看到的截断点"的办法（读侧不另抄一份口径）。
    """
    body = json.dumps(dict(context), ensure_ascii=False, sort_keys=True, default=str)
    chars = len(body)
    return {"truncated": chars > JUDGE_MATERIAL_CAP, "at": JUDGE_MATERIAL_CAP,
            "chars": chars, "cap": JUDGE_MATERIAL_CAP}
