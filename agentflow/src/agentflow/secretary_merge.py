# -*- coding: utf-8 -*-
"""秘书的并进在册（同一命题 / 第 N 份证明，从 secretary.py 的 U22 的合并侧逐字搬出）。

我保证哪条不变式：第 N 份证明就是第 N 条路径；判不了不并（并错一条路径，命题的档位读数就换了口径）。

## 为什么它能单独成文件（依赖方向）

它只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import propositionkey as _PK
from . import refusals as R
from . import schema as S
from . import statementledger as SL
from typing import Mapping

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    PROOF_ROUTES_KEY,
    PROPOSITION_KINDS,
    _is_concept_kind,
)

from .secretary_deps import (  # noqa: F401 — 这些名字由 secretary_deps 定义
    _assign_path_group_in_tx,
    _deps_missing_reading,
    _note_path_material,
    _path_material_numbers,
    _stamp_path_number,
)

from .secretary_evidence import (  # noqa: F401 — 这些名字由 secretary_evidence 定义
    proof_text_manuscript_sign_gate,
)

from .secretary_identity import (  # noqa: F401 — 这些名字由 secretary_identity 定义
    _is_proposition_kind,
    _proposition_judgment_missing,
)

from .secretary_label import (  # noqa: F401 — 这些名字由 secretary_label 定义
    wash_working_name,
)

from .secretary_proofkind import (  # noqa: F401 — 这些名字由 secretary_proofkind 定义
    PROOF_KIND_UNJUDGED,
    PROOF_SAME_KIND,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    LABEL_WASH_ROUTE,
)

from .secretary_wash import (  # noqa: F401 — 这些名字由 secretary_wash 定义
    _stmt_edge_count,
)


class MergeMixin:
    """并进在册（同一命题 / 第 N 份证明）（从 secretary.py 搬出的混入类）。"""

    @staticmethod
    def _adjudication_reading(adj: Mapping[str, Any]) -> dict[str, Any]:
        """命题同一性判定的读数（进返回值与台账；不把内部候选表整份甩出去）。

        两档在这一格里必须一眼能分辨：`checked=False` 是"没判成"（没缝 / 超时 / 坏 JSON /
        same 点不出号 / 词表外结论），`checked=True` + `verdict="different"` 是"查过了、
        确实不是"。折平这两个会让"没人判过"看起来像"判过了、确实不同"。
        """
        got = dict(adj or {})
        return {
            "checked": bool(got.get("checked")),
            "attempted": bool(got.get("attempted")),
            "verdict": str(got.get("verdict") or ""),
            "canonical_name": str(got.get("canonical_name") or ""),
            "same_as": str(got.get("same_as") or ""),
            "route": str(got.get("route") or ""),
            "condition": str(got.get("condition") or ""),
            "conclusion": str(got.get("conclusion") or ""),
            "basis": str(got.get("basis") or ""),
            "reason": str(got.get("reason") or ""),
            "reused": bool(got.get("reused")),
            "cached": bool(got.get("cached")),
            #: 这一条判定用哪条缝（三档见 `seam_for_secretary`）。没有缝时它连着为什么 ——
            #: "没判成"的原因不能只活在秘书的台账里：调用方（B 的工具返回、直写路由的
            #: detail）拿到的就是这一份读数。
            "seam_source": str(got.get("seam_source") or ""),
            "candidates": [(str(c.get("stmt_id") or "") if isinstance(c, Mapping)
                            else str(c))
                           for c in (got.get("candidates") or [])],
            #: 检索读数（"它确实自己查过"必须看得见，2026-11-08）：
            #: 关键词 / 命中几条 / 实际交给模型看的是哪几条 / 判定那一趟发没发。
            "keywords": [str(x) for x in (got.get("keywords") or ())],
            "hits_total": int(got.get("hits_total") or 0),
            "hits_named": [dict(x) if isinstance(x, Mapping) else {"stmt_id": str(x)}
                           for x in (got.get("hits_named") or ())],
            "judged": bool(got.get("judged")),
            "why": str(got.get("why") or ""),
            "cost": dict(got.get("cost") or {}),
            #: 分页读数（2026-11-08 缺陷 ②）：看了几页 / 几个候选 / 是否页尽。
            "keyword_checked": bool(got.get("keyword_checked")),
            "candidates_total": int(got.get("candidates_total") or 0),
            "pages_total": int(got.get("pages_total") or 0),
            "pages_judged": int(got.get("pages_judged") or 0),
            "candidates_seen": int(got.get("candidates_seen") or 0),
            "page_exhausted": bool(got.get("page_exhausted")),
        }

    def _same_proposition_candidate(self, tx: Any, full: str, *,
                                    kind: str = "",
                                    key_only: bool = False) -> dict[str, Any] | None:
        """在册的命题里找"同一条"：命中就返回那一条（含依据与读数），否则 `None`。

        判据只有一处（`propositionkey.same_proposition`）：先比确定性键，键不同再比
        词面相似度。`key_only=True` 时只认"键相同"那一档 —— 秘书判定没查成时走的就是
        这一支（业主 2026-11-04：「词面相似度只许用于候选表排序，不许决定并」）。
        本函数只做"在哪儿找、怎么选"这两件本层的事：
        - 只在命题性的 kind 之间判（`PROPOSITION_KINDS`；定义/概念/认不出的 kind 不并，
          理由见 `PROPOSITION_KINDS`）；
        - 跳过概念行（概念不是命题，键与相似度对它没有意义）；
        - 跳过 `schema.STATEMENT_UNUSABLE_STATUSES` 里的行（被否证/被取代的行不许
          当依据用，"并进一条已经被取代的命题"等于把新证明挂在一条废行上）；
        - 多条命中时取相似度最高的、同分取号最小的（确定性：同一次登记不能因为
          行的物理顺序不同而并进不同的一条）。
        「哪一批」这一问不在这里：池过滤是 `statementledger.pool`（唯一实现，与
        `_ledger_pool` 同一处口径）。
        """
        if not _is_proposition_kind(kind):
            return None
        candidates: list[dict[str, Any]] = []
        for r in SL.pool(tx.rows("statements"), kinds=PROPOSITION_KINDS):
            sid = str(r.get("stmt_id") or "")
            other = str(r.get("statement_full") or "")
            verdict = _PK.same_proposition(full, other,
                                           threshold=self.same_proposition_jaccard)
            if str(verdict.get("state") or "") != _PK.STATE_SAME:
                continue
            if key_only and str(verdict.get("basis") or "") != _PK.BASIS_KEY:
                # 词面相似度那一档不决定并（业主 2026-11-04）：它只给候选表排序用。
                # 「设 p 是素数；则 p 是奇数」与「设 p 是奇素数；则 p 是奇数」相似度
                # 0.8889 —— 条件的强弱关系正是业主点名的不一致形态，不许并。
                continue
            candidates.append({"similarity": float(verdict.get("similarity") or 0.0),
                               "stmt_id": sid, "row": dict(r), "verdict": verdict})
        if not candidates:
            return None
        candidates.sort(key=lambda c: (-c["similarity"], str(c["stmt_id"])))
        return candidates[0]

    def _proposition_owner(self, tx: Any, full: str, *, kind: str,
                           adj: Mapping[str, Any],
                           out: dict[str, Any]) -> dict[str, Any] | None:
        """这一笔归属于哪一条在册命题（`None` = 不归任何一条 ⇒ 调用方照常新建）。

        判据只有两档，顺序固定（业主 2026-10-24 定、2026-11-04 收紧兜底）：

        | 档 | 谁说了算 | 命中 |
        |---|---|---|
        | `adjudication.checked`（秘书判成了） | 它：`same` + 点名的 `same_as` 且那一行还在/还可并 | 那一条 |
        | 没有判断面（没缝 / 开关关着） | 2026-11-04 的确定性兜底：只认「确定性键相同」这一档等价改写；词面相似度不决定并 | 键相同那一条 |

        "试过而没判成"（`attempted=True` + `checked=False`）与"判了 same 却指不到一条
        在册行"都不进这张表：它们由 `_merge_into_proposition` 按受控拒处置（2026-11-08
        业主：「没有判不了」⇒ 判不了就是没判成，不许拿它去新建一行）。

        读数全在这一处写（`adjudication` / `proposition_state` / `proposition_reason`）：
        判 different 与"没判成"都不许折成"并"，也不许把"没判成"折成"判过了、不同"。
        「这一笔带不带证明正文」不参与这个判断（2026-11-04：没有正文的重复登记也要
        判归属）—— 它只决定命中之后落成"第 N 份证明"还是"一次重复读数"。
        """
        if adj.get("checked"):
            verdict_word = str(adj.get("verdict") or "")
            out["adjudication"] = self._adjudication_reading(adj)
            out["proposition_reason"] = (str(adj.get("basis") or "")
                                         or str(adj.get("reason") or ""))
            if verdict_word != _PK.STATE_SAME:
                out["proposition_state"] = _PK.STATE_DIFFERENT
                # 判 different ⇒ 不并，这一支一个字节都不写（调用方照常新建）。
                return None
            target_id = str(adj.get("same_as") or "")
            # 与 `_same_proposition_candidate` 同一组过滤：模型点名的是判定那一刻的候选，
            # 到了事务里它可能已经被否证/被取代/改成非命题 kind —— 那时不许把新证明挂上去。
            # 定位走查口那唯一一处（`statementledger.by_id`）；「可不可并」是本层自己的
            # 判据（它读 kind 与 status 两格），两件事不混在一个函数里。
            # 这里传 `rows=`（事务快照）而不是 `tx`：锁内读失败必须照旧抛出、整笔不写，
            # 不许被查口折成「没查到这一条」。
            found = SL.by_id(rows=tx.rows("statements"), stmt_id=target_id)
            row = dict(found.get("row") or {})
            hit = ({"row": row, "stmt_id": str(row.get("stmt_id") or ""),
                    "verdict": {"state": _PK.STATE_SAME,
                                "basis": MERGED_BY_ADJUDICATION,
                                "similarity": 0.0,
                                "reason": str(adj.get("basis") or "")}}
                   if (found.get("found")
                       and _is_proposition_kind(row.get("kind"))
                       and str(row.get("status") or "")
                       not in S.STATEMENT_UNUSABLE_STATUSES) else None)
            if hit is None:
                # 判了 same、点名的号却读不到/不可并 ⇒ 这一笔判不成：不并，也不新建
                # （`_merge_into_proposition` 按受控拒处置）。
                out["proposition_state"] = ""
                out["proposition_reason"] = (
                    f"秘书判 same 并点名 stmt:{target_id or '（空）'}，而事务快照里读不到那一条"
                    "（或它的状态已不可并）⇒ 受控拒：不在一条读不到的行上写证明，"
                    "也不另建一行")
                out["adjudication"]["fail_closed"] = True
                return None
            return hit
        # ---- 没有判断面：确定性兜底
        #
        # 退回 `_same_proposition_candidate` 的"键相同或词面相似度达阈值"两档会把
        # 「设 p 是素数；则 p 是奇数」与「设 p 是奇素数；则 p 是奇数」（键不同、
        # 词面相似度 0.8889 ≥ 0.85）并成一行。而"素数 / 奇素数"正是
        # 「条件强弱关系」⇒ 语义不一致 ⇒ 不并。
        #
        # 现在的口径（两条，缺一条都不成立）：
        # - 确定性键相同 ⇒ 仍并：那是"条件与结论的等价改写 + 分句顺序 / 记号排版"
        #   （「条件只是等价改写 ⇒ 一致」正好落这一档），零模型、可复算，
        #   不是阈值判据；
        # - 词面相似度一个字节都不决定并：它只在读数里报"离阈值有多远"
        #   （`_fail_closed_reason`）。
        # 这一档必须留下读数（`adjudication.checked=False` + `fail_closed` +
        # `why_not_merged`）：「没有判断面」不许折成"查过了、不同"。
        out["adjudication"] = self._adjudication_reading(adj)
        hit = self._same_proposition_candidate(tx, full, kind=kind, key_only=True)
        if hit is None:
            why = self._fail_closed_reason(tx, full, kind=kind)
            out["proposition_state"] = ""
            out["proposition_reason"] = why
            out["adjudication"]["fail_closed"] = True
            out["adjudication"]["why_not_merged"] = why
            return None
        return hit

    def _fail_closed_reason(self, tx: Any, full: str, *, kind: str = "") -> str:
        """没查成时"为什么没并"的那句话（读数，不是判据；不改任何一格的去向）。

        为什么要有它：fail-closed 之后最常见的追问就是"它明明看起来是同一条，凭什么都
        不并"。答案必须落在返回值里 —— 而且要点名那个相似度读数（读的人才核得动
        "阈值那一档当年会不会并"），同时说清它现在只是读数、不决定并。

        相似度取自 `propositionkey.same_proposition`（判据唯一那一处），不另算一遍：
        同一个对子在两处给出不同的读数，是本仓反复登记过的缺陷形态。
        """
        head = ("没有判断面（adjudication.attempted=False：没有模型缝 / 开关关着）"
                " ⇒ fail-closed 不并：")
        if not _is_proposition_kind(kind):
            return head + f"kind={kind!r} 不是命题性的那几档，本来就不并"
        best: tuple[float, str] | None = None
        for r in SL.pool(tx.rows("statements"), kinds=PROPOSITION_KINDS):
            sid = str(r.get("stmt_id") or "")
            other = str(r.get("statement_full") or "")
            got = _PK.same_proposition(full, other, threshold=self.same_proposition_jaccard)
            score = float(got.get("similarity") or 0.0)
            if best is None or score > best[0]:
                best = (score, sid)
        threshold = float(self.same_proposition_jaccard)
        if best is None:
            return (head + "在册没有「键相同」的等价改写，而词面相似度不决定并"
                    "（这一条与在册各行都判不了 ⇒ 连相似度读数都没有）")
        score, sid = best
        reach = ("达到阈值" if score >= threshold else "未达阈值")
        return (head + f"在册 stmt:{sid} 与这一条的词面相似度 {score:.4f} {reach} "
                f"{threshold:.2f}，但词面相似度不参与判定、不决定并"
                "（词面重合不等于条件与结论一致）；确定性键不同 ⇒ 两条")

    def _merge_into_proposition(self, tx: Any, body: Mapping[str, Any], *, full: str,
                                groups: list[list[dict[str, Any]]], kind: str = "",
                                force_new: bool, out: dict[str, Any],
                                adjudication: Mapping[str, Any] | None = None,
                                proof_kind: Mapping[str, Any] | None = None
                                ) -> dict[str, Any] | None:
        """
        同一命题 / 同种证明两道判断的落点。

        命中之后这一笔的去向只有这几种，每一种都如实写进 `out`：

        | 结局 | 返回里的读数 |
        |---|---|
        | 并成第 N 份证明 | `merged=True` + `merged_into` + `proof_no=N` + `matched_by` |
        | 同一条命题、但这一笔没有证明正文 | `duplicate=True` + `no_proof=True` + `stmt_id=<既有>` |
        | 同种证明、且没给 merge | `refused="proof_same_kind"` + 点名第几份 |
        | merge=True 且命中同种 | `merged=True` + `merged_same_kind=True` + `resign_required=True` |
        | 同一个概念（概念行） | `duplicate=True` + `matched_by="concept_label"` 或 `"concept_defined_term"` |
        | 判不了（试过而没判成） | `refused="same_statement_unjudged"` + `adjudication.fail_closed` + 原因 |
        | 同种证明这一问没判成 | `refused="proof_kind_unjudged"` + 点名哪几份判不了 |
        | 概念同一性没判成 | `refused="concept_identity_unjudged"` + 原因 |
        | 没命中 | `None`（调用方照常新建；这一支一个字节都不写） |

        概念行走 :meth:`_merge_into_concept`：它没有"条件 ⇒ 结论"，判据是"定义项相同"
        （`propositionkey.same_concept`，确定性、零模型调用）。

        ## 为什么落在秘书这一层

        "B 交内容、秘书实际操作增改查"：判"这两条是不是同一条定理"正是查重那一件活，
        而查重的读数必须与落盘在同一笔事务里 —— 分两处就会出现"读的时候判了同一条、
        写的时候建了新行"。
        """
        from . import verifications as VR   # 惰性：证明清单 / 签名状态的唯一读口径

        adj = dict(adjudication or {})
        # "这一笔被判成什么"的初值：判成了才有词，没判成是空串（不是某一档结论）。
        probe = _PK.judgeable(full)
        out["proposition_state"] = "" if not probe["ok"] else _PK.STATE_DIFFERENT
        out["proposition_reason"] = str(
            probe["reason"] or "没命中在册的同一条命题（判 different：条件与结论不同）")
        # ---- 判不了 = 没判成（业主 2026-11-08：「没有判不了」）-----------------------
        #
        # 位置在 `force_new` 之前：调用方明确要"另起一条"也不能替一次失败的判定说话 ——
        # 那一笔的语义仍是"还没查清这是不是同一条"，先查清再谈新建。
        missing = _proposition_judgment_missing(kind, adj)
        if missing:
            reading = self._adjudication_reading(adj)
            reading["fail_closed"] = True
            reading["why_not_merged"] = missing
            out.update(checked=False, refused=R.SAME_STATEMENT_UNJUDGED,
                       proposition_state="", proposition_reason=missing,
                       reason=missing, adjudication=reading)
            return out
        if force_new:
            # 调用方明确要"另起一条" ⇒ 不并（`force_new` 的含义就是不许替它合并）。
            out["proposition_reason"] = "force_new：调用方明确要另起一条，跳过同一性合并"
            return None
        if _is_concept_kind(kind):
            # ---- 概念行那一档（D2）：判据是"定义项相同"，与命题那一套不是同一件事。
            # 位置必须在这里：下面那条"没有证明正文就不并"会把概念行直接放过
            # （概念不参与等级链、本来就没有证明），而"同一概念登记两行"正是从那个
            # 缺口漏出来的（真机 mp3-r2 的 000003 / 000004）。
            return self._merge_into_concept(tx, body=body, full=full, kind=kind, out=out)
        if not _is_proposition_kind(kind):
            # 一条定义/概念不是命题："表述几乎相同的两条命题是同一个"这句话对它不成立。
            out["proposition_reason"] = (
                f"kind={kind!r} 不在命题性的那几档 {list(PROPOSITION_KINDS)} 里 ⇒ "
                "不参与同一命题判定（不并）")
            return None
        proof = str(body.get("proof_text") or "")
        # ---- 归属判断（"这一笔是不是在册某一条命题的又一次登记"）只在这一处判 ------
        #
        # 带不带证明正文都先问这一句（2026-11-04 业主裁定）：改前"没有证明正文"在下面
        # 直接返回 None，于是同一命题换一种写法、两次都没带证明时会落第二行 —— 而它
        # 并不产生第二份证明，也没有任何读数说"这是同一条"。
        hit = self._proposition_owner(tx, full, kind=kind, adj=adj, out=out)
        if (hit is None and adj.get("checked")
                and str(adj.get("verdict") or "") == _PK.STATE_SAME):
            # 判了 same、点名的号却在事务快照里读不到/不可并 ⇒ 这一笔判不成：
            # 受控拒（不新建、不合并），不拿"读不到那一条"冒充"不是同一条"。
            why = str(out.get("proposition_reason") or "") or (
                "秘书判 same 却指不到一条可并的在册行 ⇒ 受控拒：不新建、不合并")
            reading = self._adjudication_reading(adj)
            reading["fail_closed"] = True
            reading["why_not_merged"] = why
            out.update(checked=False, refused=R.SAME_STATEMENT_UNJUDGED,
                       proposition_state="", proposition_reason=why,
                       reason=why, adjudication=reading)
            return out
        if not proof.strip():
            if hit is None:
                out["proposition_reason"] = (
                    str(out.get("proposition_reason") or "")
                    + "；这一笔没有带证明正文 ⇒ 不进「第 N 份证明」那一支，"
                    "但归属判断已经做过：没命中 ⇒ 照常新建一行")
                return None
            sid = str(hit["stmt_id"])
            basis = str(dict(hit.get("verdict") or {}).get("basis") or "")
            out["proposition_state"] = _PK.STATE_SAME
            out["proposition_reason"] = str(dict(hit.get("verdict") or {}).get("reason") or "")
            out.update(checked=True, created=False, duplicate=True, stmt_id=sid,
                       matched_by=basis, no_proof=True,
                       reason=(f"同一条命题已在册（stmt:{sid}；依据："
                               f"{self._basis_text(basis, 0.0)}）⇒ 不新建第二行；"
                               "这一笔没有带证明正文，所以也不产生第 N 份证明"
                               "（没有正文的重复登记是一次重复读数，不是第 2 份证明）"))
            return out
        if hit is None:
            return None
        row = dict(hit["row"])
        sid = str(hit["stmt_id"])
        verdict = dict(hit["verdict"])
        out["proposition_state"] = _PK.STATE_SAME
        out["proposition_reason"] = str(verdict.get("reason") or "")
        basis = str(verdict.get("basis") or "")
        similarity = float(verdict.get("similarity") or 0.0)
        # ---- 「难以自证」的空号 ⇒ 整条替换（业主 2026-11-13 裁定）----------------
        #
        # 位置在"同种证明 / 合并"这两个问题之前：空号上的那一份正文不是"已有证明"，
        # 拿它去判"同种"正是业主担心的拒收（见 `_same_kind_hits` 那一格）。
        # 返回 False ⇒ 这一行没有空号（或这一笔不是替换）⇒ 下面逐字照旧。
        if self._fill_vacant_path_if_any(
                tx, sid=sid, proof_text=proof, groups=groups, out=out,
                manuscript=str(body.get("manuscript_path") or "")):
            return out
        # 同种证明这一问在事务外已经问过（锁内不许发模型）：这里只读结论。
        # `proof_kind` 为空 = 这一笔没有在册可比的证明（新命题 / 首份）⇒ 不是同种。
        kind_got = dict(proof_kind or {})
        kind_hits, unjudged_proofs = (list(kind_got.get("hits") or []),
                                      list(kind_got.get("unjudged") or []))
        merge = body.get("merge") is True
        existing = VR.proof_list(row)
        # ---- 同一份正文再交一次：不新增证明号，也不算「同种证明」（2026-11-02） ------
        #
        # 真机读数（projects/paper-rewrite-85/sessions/20261102.jsonl:2980，22:03:20）：
        # B 为了把 proof_no 落成 1，拿同一份正文（8454 字、与在册 canonical 逐字同源）
        # 以 proofs=[{proof_no:1,…}] 重交 ⇒ _same_kind_hits 拿它与在册 #1 比，
        # 相似度 1.0000 >= 0.80 ⇒ 整笔 proof_same_kind 拒。那不是"两种同门证法被并列
        # 记录"，而是同一条记录再交一次 —— 判据在这里分不开的代价是：B 再也不敢交
        # 带证明的那一笔（proofs=0 的绕行就是这么来的）。
        #
        # 判据取原样 sha（verifications.text_sha，"逐字同一份"），不比相似度：
        # "逐字同一份"是确定性的事实，不需要阈值。命中 ⇒ 一个字节都不写（那一份已经在册），
        # 回执说清"就是第几份"，调用方据此收工。
        same_sha = VR.text_sha(proof)
        same_text_no = next(
            (int(no) for no, text in existing
             if str(text or "").strip() and VR.text_sha(str(text)) == same_sha), 0)
        if same_text_no and not merge:
            out.update(checked=True, created=False, duplicate=False, merged=True,
                       merged_into=sid, stmt_id=sid, proof_no=int(same_text_no),
                       matched_by=basis, similarity=similarity, same_kind=[],
                       canonical_written=False,
                       reason=(f"这一份正文与 stmt:{sid} 的第 #{int(same_text_no)} 份证明"
                               "逐字相同（sha 一致）⇒ 不新增证明号、也不算「同种证明」："
                               "同一条记录再交一次不是第二种证法。盘上一个字节都没动"
                               "（那一份已在册）；要换这一份的正文就把新正文交上来"
                               "（proof_text 或 proofs 里那一号），旧正文会进 proof_history，"
                               "并请 V 对新正文重签（resign_required）"))
            return out
        # ---- 同种证明这一问没判成：不许折成"不同"照旧新增证明号（2026-11-08）------
        #
        # 位置：在"逐字同一份"那一档之后（那是确定性事实、不需要判定），merge 之前
        # （合并要落到具体哪一份，判不了就不许猜）。判不了不等于不同 —— 折成不同就会
        # 新增证明号，同一种证法被并列记录，正是这一轴要防的形态。
        if unjudged_proofs:
            names = "、".join(f"第 {int(h['proof_no'])} 条路径" for h in unjudged_proofs)
            out.update(checked=False, created=False, duplicate=False, merged=False,
                       refused=PROOF_KIND_UNJUDGED, stmt_id=sid, merged_into=sid,
                       matched_by=basis, similarity=similarity, same_kind=[],
                       unjudged_proofs=list(unjudged_proofs),
                       reason=(f"这一份证明与 stmt:{sid} 的 {names} 没判成是不是同种"
                               "（没判成 ≠ 不同）⇒ 不收录、不新增路径：折成不同，同一套"
                               "证法会被并列记录。这一档只在判定面没给出可用结论时出现"
                               "（超时 / 坏 JSON / 没给可用答案）。改法：重交这一份，"
                               "或换一条真正不同的证法再交"))
            return out
        # ---- merge=True：合成一份，覆盖那一份证明的正文（要 V 重签）
        #
        # 这里刻意不去要求"合并稿本身与某一份同种"：合并稿是各取所长写出来的，
        # 它当然与原稿都不像（实测：两份 0.84 同种的原稿合成之后，合并稿与每一份
        # 的相似度掉到 0.67 / 0.59）。判据是"这一笔声明了自己是合并稿，而这条命题
        # 确实已在册"—— 后者由上面的同一性判定给出，前者由调用方声明。
        if merge:
            target, how = self._merge_target(row, proof, body, existing)
            if target < 1:
                out.update(checked=False, created=False, duplicate=False, merged=False,
                           refused="bad_merge_target", stmt_id=sid, merged_into=sid,
                           matched_by=basis, similarity=similarity,
                           reason=(f"`proof_no` 指的是这条命题在册的那一份证明，{how} ⇒ "
                                   "整笔不写（合并要落到一份具体的证明上：合并稿覆盖谁的正文、"
                                   "谁的旧正文进 proof_history、谁的签要重拿，都由它决定）"))
                return out
            # 合并稿也是"要进 statements.proof_text 的正文"：落到哪一条在册行已经由
            # 同一性判定给出（`sid`），这里用同一个闸判一次 —— 不满足 ⇒ 整笔不写。
            _mgate = proof_text_manuscript_sign_gate(
                self.store, statement_id=sid, proof_text=proof,
                proof_no=int(target), origin=str(body.get("origin") or ""),
                source_lit_id=str(body.get("source_lit_id") or ""))
            out["proof_text_gate"] = dict(_mgate)
            if _mgate.get("refused"):
                out.update(checked=False, created=False, duplicate=False, merged=False,
                           refused=str(_mgate.get("refused") or ""),
                           reason=str(_mgate.get("reason") or ""))
                return out
            return self._merge_same_kind_version(tx, row=row, sid=sid, full=full,
                                                 proof_no=int(target), merged_text=proof,
                                                 verdict=verdict, kind_hits=kind_hits,
                                                 merge_note=how, out=out,
                                                 body=body, groups=groups)
        # ---- 同种证明：不新增证明号
        if kind_hits:
            top = kind_hits[0]
            path_no = int(top["proof_no"])
            _sim = float(top.get("similarity") or 0.0)
            out.update(checked=False, created=False, duplicate=False, merged=False,
                       refused=PROOF_SAME_KIND, stmt_id=sid, merged_into=sid,
                       matched_by=basis, similarity=similarity, proof_no=0,
                       same_kind=kind_hits,
                       #: 相似度只作材料读数（不参与收不收）：人看得见"机械读数长什么样"。
                       same_kind_material={"similarity": _sim},
                       reason=(f"这一份证明与 stmt:{sid} 的第 {path_no} 条路径同种"
                               "（秘书的语义判定：两套证法是同一路，不是两条独立路径）"
                               "⇒ 不收录、不新增路径（并列记录会让一条定理看起来有好几条"
                               "独立证法）。材料读数（只作参考，不作判据）：相似度 "
                               f"{_sim:.4f}。两条处置：① 换一条真正不同的证法再交；"
                               "② 这一份不再提交 —— 同一套证法在册已经有一份。"
                               "参数面没有「合并到第几条路径 / 改号」这一类键："
                               "同种证法的正文修订由人看过稿之后处理"))
            return out
        # ---- 落成第 N 份证明（或 canonical 那一格还是空的时候的 #p1）
        #
        # 号由秘书在这一笔事务里分配（`assign_path_group`）：同一命题已有 N 条路径
        # ⇒ 这一份排 N+1；同一份正文 sha 重复收录 ⇒ 沿用原号（上一格"逐字同一份"
        # 已经处理了那条路，走到这里的一定是新的正文）。分配必须在锁里，理由见
        # `_assign_path_group_in_tx`。
        #
        # 交付里写的号（`body["proof_no"]`，改前从稿头 `- 证明号：` / 携带单读来）
        # 不再采信：产出侧不写那个号了，留着它当权威就是第二套口径。给了就只
        # 记读数（`proof_no_ignored`），号仍由分配给出。
        canonical_was_empty = not VR.proof_text_of(row, 1).strip()
        try:
            requested_no = int(body.get("proof_no") or 0)
        except (TypeError, ValueError):
            requested_no = 0
        if requested_no >= 1:
            out["proof_no_ignored"] = {
                "given": requested_no,
                "why": ("证明号由秘书按路径面分配（`assign_path_group`）⇒ 交付里写的"
                        "这个数一个字节都不采信；回执里的 `proof_no` 才是这一份的号"),
            }
        if canonical_was_empty:
            # 先登记命题、后补证明：这一份填 canonical 那一格（#p1），不新增路径。
            _alloc = _assign_path_group_in_tx(
                tx, root=self.root, statement_id=sid,
                manuscript=str(body.get("manuscript_path") or ""),
                body_sha=VR.text_sha(proof))
            if not _alloc.get("checked"):
                out.update(checked=False, created=False, duplicate=False, merged=False,
                           refused="path_group_unreadable",
                           reason=("路径数读不出来 ⇒ 这一份的正文不落（不猜第几条）："
                                   + str(_alloc.get("why") or "未知原因")))
                return out
            proof_no = 1
            out["path_group"] = 1
            out["path_group_reading"] = dict(_alloc, path_group=1)
            row["proof_text"] = proof
        else:
            _alloc = _assign_path_group_in_tx(
                tx, root=self.root, statement_id=sid,
                manuscript=str(body.get("manuscript_path") or ""),
                body_sha=VR.text_sha(proof))
            if not _alloc.get("checked"):
                out.update(checked=False, created=False, duplicate=False, merged=False,
                           refused="path_group_unreadable",
                           reason=("路径数读不出来 ⇒ 这一份不并、不新增证明号（不猜第几条）："
                                   + str(_alloc.get("why") or "未知原因")))
                return out
            proof_no = int(_alloc.get("path_group") or 1)
            out["path_group"] = proof_no
            out["path_group_reading"] = dict(_alloc)
            listed = [dict(p) if isinstance(p, Mapping) else p
                      for p in (row.get(VR.PROOFS_KEY) or [])]
            listed.append({"proof_no": proof_no, "text": proof,
                           "created_at": S.now_iso()})
            row[VR.PROOFS_KEY] = listed
        _note_path_material(out, _path_material_numbers(groups)
                            if len(groups) <= 1 else [], decided=proof_no)
        written = ["statements"]
        # ---- 洗定理名 + 路线进证明层（「路线写在证明这一层」）。
        #
        # 这一笔的 label 已经被洗成 `canonical_name`（见 `_record_statement_tx`），但并进去之后
        # label 用的是那条在册行的。所以这里两件都要做：
        # ① 在册那一条的名字如果与洗过的名字不同 ⇒ 顺手把它洗掉（第一条带着
        #    "（路线一：…）"落了盘，后来的两份证明并进来时把它洗净）；
        # ② 这一笔自己的路线说明落到"第 N 份证明"上（`PROOF_ROUTES_KEY`），不丢。
        route = str(adj.get("route") or "").strip() if adj.get("checked") else ""
        canonical = str(adj.get("canonical_name") or "").strip() if adj.get("checked") else ""
        if canonical and str(row.get("label") or "") != canonical:
            old_label = str(row.get("label") or "")
            # 只在"在册那个名字是本名加修饰"时洗（`Sylow 三定理（路线一：…）` ⇒ `Sylow 三定理`）。
            # 两个都干净、却不完全同名的（`Sylow 三定理` 与 `Sylow 定理`）不动它：名字不参与
            # 同一性判定（「不看名称」），先落盘的那个名字赢 —— 否则每并一份证明就改名
            # 一次，而"这一条现在叫什么"会跟着最后一次提交漂。
            if canonical in old_label:
                out["label_washed"] = {"from": old_label, "to": canonical,
                                       "class": LABEL_WASH_ROUTE, "stmt_id": sid,
                                       "why": ("在册那一行标签里的路线 / 自证草稿 / 待 V 审签"
                                               "那一类修饰被洗掉了；被洗掉的路线落进这一份"
                                               "证明的路线说明里，不丢")}
                row["label"] = canonical
        # ---- 在册那一行的名字如果是内部工作名，并这一笔时顺手洗掉（修名那一半）。
        # 为什么修名放在这一支：要修的正是在册那一行，而它与"这一笔的 label"无关。
        # 判据与新建那一支同一处
        # （`wash_working_name`），所以两处不会给出两个洗法；这一支只动 label，不动内容。
        working = wash_working_name(row.get("label"), kind=str(row.get("kind") or ""),
                                    stmt_id=sid,
                                    statement_full=str(row.get("statement_full") or ""))
        if working:
            out["label_washed"] = dict(working, stmt_id=sid)
            row["label"] = str(working["to"])
            out["canonical_name"] = str(working["to"])
        if route:
            out["proof_route"] = route
            routes = dict(row.get(PROOF_ROUTES_KEY) or {})
            routes[str(int(proof_no))] = route
            row[PROOF_ROUTES_KEY] = routes
        if canonical:
            out["canonical_name"] = canonical
        # 变体留痕：这一笔是"同一条命题的另一种写法"，盘上要读得出"它凭什么并进来"。
        # 有界（只留最近 20 条）：这是读数，不是账本；无界列表会让一行无限长大。
        matches = [dict(m) for m in (row.get("_proposition_matches") or [])
                   if isinstance(m, Mapping)]
        matches.append({"statement_full": full, "basis": basis,
                        "similarity": similarity, "proof_no": proof_no,
                        "label": str(body.get("label") or ""),
                        "route": route, "at": S.now_iso(),
                        "by": f"secretary-{self.role}"})
        row["_proposition_matches"] = matches[-20:]
        body_for_deps = dict(body)
        body_for_deps["proof_no"] = proof_no
        steps = self._resolve_write_steps(tx, body_for_deps, out, groups)
        if steps is None:
            return out
        # 这一份的路径号由秘书刚分配（见上）：手稿依赖段那一路的 `used_by` 尾巴与
        # `path_group` 都从它来；证明正文里分段扫出来的那一路 `path_group` 保留段落
        # 下标（一份证明里的几条可选路径，不是几份证明）。
        steps = _stamp_path_number(steps, path_group=proof_no, proof_no=proof_no,
                                   single_group=len(groups) <= 1)
        deps_written = self._write_dep_steps(tx, steps, stmt_id=sid, body=body_for_deps)
        if deps_written:
            written.append("dependencies")
        tx.upsert("statements", row, note="record_statement:merged_proof")
        out["deps_missing"] = _deps_missing_reading(
            proof_text=proof, deps_written=deps_written,
            derived_from=body.get("derived_from") or (), stmt_id=sid,
            proof_no=proof_no,
            scan={"refs": sum(len(g) for g in (groups or []))})
        out.update(checked=True, created=False, duplicate=False, merged=True,
                   merged_into=sid, stmt_id=sid, proof_no=proof_no,
                   #: 这个号是秘书按路径面分配的（唯一来源 `assign_path_group`）。
                   proof_no_source="path_group",
                   matched_by=basis, similarity=similarity, same_kind=[],
                   tables=written, row=row, deps_written=deps_written,
                   #: 其中"命题→命题"几条（2026-11-05 缺陷 1c：两个数分开读）。
                   deps_stmt_edges=_stmt_edge_count(steps),
                   path_groups=len(groups or []), canonical_written=canonical_was_empty,
                   reason=(f"并入已有命题 stmt:{sid}，作为第 {proof_no} 份证明"
                           f"（依据：{self._basis_text(basis, similarity)}）；"
                           f"这一份的依赖落在 `used_by=\"stmt:{sid}#p{proof_no}\"`"
                           f"（{deps_written} 条、{len(groups or [])} 组），"
                           "与既有证明的依赖面按证明号分开；第 3 位（审过）由 V 逐份签，"
                           f"登记不等于审过（`bits.evidence.reviewed_by_proof` 支持逐份）"
                           # 洗名与路线各一句：读的人要能看出"标签被改过"与"路线去哪了"。
                           + (f"；定理名按秘书的判定洗成 {out['label_washed']['to']!r}"
                              f"（原标签 {out['label_washed']['from']!r}）"
                              if out.get("label_washed") else "")
                           + (f"；这一份的路线说明落在第 {proof_no} 份证明上"
                              f"（{route}）" if route else "")))
        return out

    @staticmethod
    def _basis_text(basis: str, similarity: float) -> str:
        """把"凭什么判成同一条"翻成一句人话（返回值与拒信共用一份措辞）。"""
        word = str(basis)
        if word == _PK.BASIS_KEY:
            return "proposition_key 相同"
        if word == MERGED_BY_ADJUDICATION:
            return "秘书判的（条件与结论一致）"
        if word == _PK.BASIS_CONCEPT_LABEL:
            return "定义项（标签）规范化后相同"
        if word == _PK.BASIS_CONCEPT_TERM:
            return "正文里被定义的术语相同"
        return f"prose_similarity {float(similarity):.4f}"


#: 同一命题的判据：确定性键相同 ⇒ 这一笔不是新命题，而是那条命题的第 N 份证明；
#: 词面相似度只作材料读数（`_fail_closed_reason` 报"离阈值有多远"），不决定并。
#: 缺省阈值与唯一实现都在 `propositionkey`，这里只是把它们摆到秘书这一层
#: （可注入：构造参数 `same_proposition_jaccard`）。
SAME_PROPOSITION_JACCARD = _PK.SAME_PROPOSITION_JACCARD


#: 第三种依据：秘书那一趟模型判定说"同一条"（`adjudicate_proposition`）。
#:
#: 它必须与上面两条分开命名：键相同 / 相似度兜底都是机械读数，而这一条是"读了条件与结论
#: 之后判的" —— 三者的可信度、可复核方式、以及"凭什么并的"那句话都不一样。
MERGED_BY_ADJUDICATION = "secretary_adjudication"


def proof_routes_of(row: Mapping[str, Any]) -> dict[int, str]:
    """这一行每条证明的一句话路子说明 `{证明号: 说明}`（读侧唯一口径）。

    路子住在证明号上，不在命题的 label 里（业主 2026-10-24：「路线写在证明这一层」）。
    写侧是 `Secretary.record_statement`：标签里被洗掉的"（路线一：…）"这类修饰落到这里，
    与那条证明的 `proof_no` 对齐。没有说明的证明不在字典里（缺省是空串，不是"没交"）。
    """
    raw = row.get(PROOF_ROUTES_KEY)
    out: dict[int, str] = {}
    if not isinstance(raw, Mapping):
        return out
    for key, value in raw.items():
        try:
            no = int(str(key).strip())
        except (TypeError, ValueError):
            continue
        text = str(value or "").strip()
        if no >= 1 and text:
            out[no] = text
    return out


def proof_route_of(row: Mapping[str, Any], proof_no: Any = 1) -> str:
    """某一份证明自己的路子说明（没有 ⇒ 空串）。"""
    return proof_routes_of(row).get(int(proof_no or 0) or 1, "")
