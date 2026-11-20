# -*- coding: utf-8 -*-
"""秘书的证据升档与正文签闸（从 secretary.py 的 U22 的证据侧逐字搬出）。

我保证哪条不变式：凭据不够不升档，并且要说清缺什么 —— 「没升档」必须带得走一句为什么。

## 为什么它能单独成文件（依赖方向）

`secretary_evidence` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_evidence` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import proofregistry as _PR
from . import schema as S
from . import statementledger as SL
from typing import Mapping

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    STATEMENT_BITS_KEYS,
)


class EvidenceMixin:
    """证据升档与正文签闸（从 secretary.py 搬出的混入类）。"""

    def _upgrade_evidence_kind(self, existing: Mapping[str, Any],
                               body: Mapping[str, Any]) -> dict[str, Any]:
        """同一份内容再交一次、这一回来的 `evidence_kind` 更强 ⇒ 返回"改哪几格"。

        ## 为什么必须有这一格（2026-10-19 晚，`projects/mp2` 的 `stmt:000003`）：`mp2` 那条真机读数：B 先把主
        命题落成 `heuristic`（那时 V 还没签，这是如实的降档），随后 V 签了 `verifications/000003.jsonl#v-000001`
        （verdict=成立、`proof_sha256` 与现行正文相符）—— 而那一行的档位再也没升上去，因为"升档"当时只有一条路：
        `table.update("statements")`。那条路是野路（`store.direct_write_refusal` 现在拒它），因为它同时能改
        `bits` / `proof_text` / `quote_verified`，而没有任何东西核过那些字段。关掉野路就必须给正路一条同样的
        出口，否则 `evidence_kind` 在结构上永远到不了 `proof_review`（`weaker_than_evidence` 会永远报 warning，
        而它要的出口"把这一行升成 proof_review"没人走得到）。这一格就是那条出口：内容一个字不动、只把档位改强，
        且判据用的是 `verifications.proof_review_gap`（写入期闸、审计期、收工门读的是同一处口径）。
        ## 三态（凭据不够就不升，而且把原因说出来）：
        | 结局 | 返回 |
        |---|---|
        | 升了 | `{"upgraded": True, "row": …, "changes": [...], "reason": …}` |
        | 该升而凭据不够 | `{"upgraded": False, "reason": "（…；V 那一签还差…）"}` |
        | 不该升（方向不对/同档） | `{"upgraded": False, "reason": ""}` |
        "凭据不够"与"不该升"都不写库：前者留在重复读数那一支，并把 `proof_review_gap` 的原话附进 `reason`。只允许
        弱 → 强（`verifications.WEAKER_THAN_PROOF_REVIEW` → `proof_review` 或 `proof`）：反方向（把 `proof_review` 降成
        `heuristic`）不在这一格 —— 降档是另一个决定，它需要的不是"同一份内容再交一次"这件事，而是写清为什么降（`quote_reason`）。
        ## 只动档位与留痕，不动 bits（与 B 的登记那一笔同一口径）：`agent_f/core._proof_outlet`
        在攻坚那一侧现在把同一份内容再交给 B 的 `register_statement`（V 签完之后那一笔把档位升到
        `proof_review`），它也只改 `evidence_kind`。五元位的
        第 3 位（`reviewed`）是 V 的签名面，由 `verifications.bit3_payload(那一行)` 现读，不在这一格里抄进来 ——
        抄进来就有第二份"谁审过了"的账，而两份账迟早会分家。

        ## D-37（2026-10-24 真机 cube）：`kind` 也跟着证据升
        现场那一行早就升到了 `proof_review`（`have == want`），而 `kind` 仍写着 `conjecture` ⇒
        "档位还要不要升"这一支根本进不来。所以 `kind` 那一格独立算：判据只有一处
        （`evidencebits.kind_following_grade`，纯读；B 同步第 4 位那一支共用同一个），依据要么是 `verifications/`
        里一条盖住现行正文、判「成立」的签，要么是第 4 位逐条里一条 `verified`。
        只抬 `conjecture → theorem / lemma`（`body.kind` 只在两档之间选落点），作者写下的
        别的 kind 一个字不动；`bits` 仍然一个字节不写（五元位由现算派生，不抄第二份账）。
        升档依据落升档痕迹那一格（from / to / basis / grade / by / at），与证据档升档
        那一格同一套留痕形态。证据不够时这一行不改，`reason` 里附 `_kind_follow_note` 的原话
        （"还差什么"），不许折成"已经升了"。
        """
        from . import evidencebits as EB   # 惰性：D-37 的 kind 口径只有一处
        from . import verifications as VR   # 惰性：只在重复读数这一支才需要

        out: dict[str, Any] = {"upgraded": False, "row": {}, "changes": [],
                               "reason": "", "review_basis": {}}
        want = str(body.get("evidence_kind") or "")
        have = str(existing.get("evidence_kind") or "")
        row = dict(existing)
        changes: list[str] = []
        # ---- 2026-11-04（缺口 ②）：这一笔交付带来的 V 签是哪一路 ------------------
        #
        # 判据三路（任一路命中即可升档，与新建那一支算出来的档一致）：
        #   ① `verifications.proof_review_gap`（既有那一路：在册签名台账）；
        #   ② 手稿签块（`vsigns.manuscript_sign_standing`）；
        #   ③ `bits.reviewed`（B 收录时按正文 sha 认到的逐份签）。
        # ②③ 由 `_manuscript_upgrade_basis` 一处收拢：它们同源（B 的 `bits.reviewed`
        # 正是从手稿签块认出来的），所以反真空打桩点也只能有一个；两处各判一次会让
        # "摘掉手稿那一支"之后另一支照样升档，判据就量不到它。
        review_basis = _manuscript_upgrade_basis(
            root=self.store.root,
            manuscript_text=str(body.get("manuscript_text") or ""),
            manuscript_path=str(body.get("manuscript_path") or ""),
            proof_text=str(body.get("proof_text") or ""),
            bits=(dict(body.get("bits") or {}) or dict(existing.get("bits") or {})))
        signed_via = (str(review_basis.get("basis") or "")
                      if review_basis.get("signed") else "")
        out["review_basis"] = dict(review_basis)
        # ---- 证据侧那一行：这一笔带来的五元位比在册那一行强时，用它判 kind -------
        #
        # 为什么不能只看 `existing`：现场那一行是按"证明还空着"落成的猜想（bits.proof
        # 为空），而这一笔交来的正是那份证明 —— 判据读旧那一份会把"这一条现在有
        # 证明、也签过"读成"还差第 2 位"，于是 kind 永远升不上去（缺口 ② 的另一半）。
        probe_row = dict(existing)
        body_bits = dict(body.get("bits") or {})
        if bool(body_bits.get("proof")):
            merged_bits = dict(existing.get("bits") or {})
            merged_bits["proof"] = body_bits.get("proof")
            ev = dict(merged_bits.get("evidence") or {})
            new_ev = dict(body_bits.get("evidence") or {})
            for key in ("proof_process", "proof_source",
                        EB.REVIEWED_BY_PROOF_KEY, EB.REVIEWED_SHA_BY_PROOF_KEY,
                        "reviewed_by", "reviewed_source"):
                if key in new_ev:
                    ev[key] = new_ev[key]
            merged_bits["evidence"] = ev
            if body_bits.get("reviewed"):
                merged_bits["reviewed"] = True
            try:
                merged_bits["grade"] = EB.derive_grade(merged_bits)
            except Exception:  # noqa: BLE001 —— 等级算不出来就留给下面那一格判"判不了"
                pass
            probe_row["bits"] = merged_bits
        # ---- D-37（2026-10-24 真机 cube 的现场）：kind 跟着证据升。
        #
        # 与下面 `evidence_kind` 那一支各自独立：现场那一行早就升到了 `proof_review`
        # （`have == want`），缺的只是 `kind` 那一步 —— 所以这一格不能挂在"档位还要不要
        # 升"的条件下面。判据只有一处（`evidencebits.kind_following_grade`，纯读；B 同步
        # 第 4 位那一支与它共用同一个），这里只做两件本层的事：改那一格、把依据留痕。
        # `signed_via` 是"这一笔的 V 签在哪"（缺口 ②）：手稿签块 / `bits.reviewed`
        # 命中的那一路由调用方判完再交进来（判据仍只有一处）。
        kind_read = EB.kind_following_grade(
            probe_row, root=self.store.root, requested=str(body.get("kind") or ""),
            signed_via=signed_via)
        kind_upgraded = False
        if str(kind_read.get("state") or "") == "upgraded":
            target = str(kind_read.get("kind") or "")
            before_kind = str(existing.get("kind") or "")
            if target in EB.KIND_UPGRADE_TARGETS and target != before_kind:
                row["kind"] = target
                # 留痕：只改 kind 的那一笔也要读得出来"凭什么"（与
                # 与证据档升档那一格同一套：from / to / 依据 / 谁 / 何时）。
                row["_kind_upgrade"] = {
                    "from": before_kind, "to": target,
                    "basis": str(kind_read.get("basis") or ""),
                    "grade": str(kind_read.get("grade") or ""),
                    "by": f"secretary-{self.role}", "at": S.now_iso(),
                }
                changes.append(
                    f"kind: {before_kind or '（空）'} → {target}"
                    f"（升档依据：{str(kind_read.get('basis') or '')}）")
                kind_upgraded = True
        #: 这一格能升到的两档：`proof_review`（V 逐行走查/会审签过）与 `proof`
        #: （穷举型证据：E 的程序 + ②③ 加上 V 那一签 —— 业主 2026-10-23 晚「穷举能拿
        #: proof」）。凭据三路见上面 `review_basis` 的说明：任一路命中即可升档。
        #: 为什么要开 `proof` 这一档：B 的第三方签字闸（`numericproof.filing_problems`）
        #: 要求 proof 必须有一份盖住这一条命题的 V 签，而 V 只审在册的命题 ⇒
        #: 「先按猜想落库、签完再升成定理级 proof」是唯一正路；这一格不通的话那条路在
        #: 秘书这一层就断了（`duplicate_statement`），穷举证明永远进不了定理证明库。
        evidence_upgraded = False
        evidence_gap = ""
        if (want in (VR.PROOF_REVIEW_KIND, "proof") and have != want
                and have in VR.WEAKER_THAN_PROOF_REVIEW):
            probe = dict(probe_row)
            probe["evidence_kind"] = want
            gap = VR.proof_review_gap(self.store.root, probe)
            if not gap.get("ok") and not review_basis.get("signed"):
                evidence_gap = (
                    f"（这一行没有升到 {want}：签名台账里读不到凭据"
                    f"（`verifications.proof_review_gap`：{str(gap.get('why') or '查不到凭据')[:240]}）"
                    f"；手稿签块 / `bits.reviewed` 也没有签"
                    f"（{str(review_basis.get('why') or '没有这一份交付的签')[:200]}））")
            else:
                row["evidence_kind"] = want
                ms = dict(review_basis.get("manuscript") or {})
                if gap.get("ok"):
                    how = "verification_ledger"
                    witness = (f"{gap.get('ledger') or ''}"
                               f"#{gap.get('verification_id') or ''}")
                elif str(ms.get("state") or "") == "signed":
                    how = "manuscript_sign_block"
                    witness = str(review_basis.get("basis") or "")
                else:
                    how = "bits_reviewed"
                    witness = str(review_basis.get("basis") or "")
                row["_evidence_kind_upgrade"] = {
                    "from": have, "to": want,
                    "verification_id": str(gap.get("verification_id") or ""),
                    "ledger": str(gap.get("ledger") or review_basis.get("basis") or ""),
                    "proof_sha256_matched": (bool(gap.get("sha_matches"))
                                             or bool(review_basis.get("signed"))),
                    #: 凭据是哪一路（`verification_ledger` / `manuscript_sign_block` /
                    #: `bits_reviewed`）：三路都能升档，但读的人必须分得开。
                    "basis": how,
                    "by": f"secretary-{self.role}", "at": S.now_iso(),
                }
                changes.append(f"evidence_kind: {have} → {want}（凭据：{witness}）")
                evidence_upgraded = True
        if not (kind_upgraded or evidence_upgraded):
            # ---- 已在终态（甲 的落点，2026-11-04）：穷举程序 + V 签 ⇒ proof 在落签那一刻
            # 就由 `verifications._grade_recomputed_from_signature` 定好了。B 这一次登记
            # 因此没有格可改 —— 但它不该被读成"重复登记"：这一条已经在库、就停在它该在
            # 的那一档。判据只读（`_signed_exhaustion_terminal`），与回填 / 审计同一份；
            # 只认 `want == have == "proof"`，文字证明（`proof_review`）那一路照旧走
            # `duplicate_statement`（D-37 的口径不动）。
            if want == have == VR.PROOF_KIND:
                body_text = str(body.get("proof_text") or "")
                disk_text = str(existing.get("proof_text") or "")
                if not body_text.strip() or body_text == disk_text:
                    try:
                        experiments = list(self.store.rows("experiments"))
                    except Exception:  # noqa: BLE001 —— 读不到就不认终态（保守）
                        experiments = []
                    terminal = _signed_exhaustion_terminal(
                        root=self.store.root, row=existing, proof_text=disk_text,
                        experiments=experiments)
                    out["terminal_reading"] = dict(terminal)
                    if terminal.get("terminal"):
                        out.update(upgraded=True, at_tier=True, row=row,
                                   reason=("同一份内容再交一次：盘上那一行已经是 "
                                           "`proof`（穷举程序 + V 签 —— 落签那一刻按通道"
                                           "定的档），这一笔没有新东西可写、也没有重复"
                                           "登记。"
                                           + str(terminal.get("why") or "")))
                        return out
            # 三态：一行都没改，而"还差什么"必须留在读数里（D-37）。
            out["reason"] = evidence_gap + self._kind_follow_note(kind_read)
            out["kind_reading"] = dict(kind_read)
            return out
        out.update(upgraded=True, row=row, changes=changes,
                   kind_reading=dict(kind_read))
        if evidence_upgraded:
            trace = dict(row.get("_evidence_kind_upgrade") or {})
            out["reason"] = (
                f"同一份内容再交一次、且这一回带了 `{want}` 的凭据 ⇒ 秘书"
                f"改那一行（不新建）：凭据是 {trace.get('basis') or '（没记）'}"
                f"（{trace.get('ledger') or ''}）；"
                "`proof_sha256` 与现行正文相符（判据与写入期那道闸同一处）。内容面一个字没动。")
        else:
            out["reason"] = (
                "同一份内容再交一次 ⇒ 秘书改那一行（不新建）："
                + "；".join(changes) + "。内容面一个字没动。")
        if not evidence_upgraded and evidence_gap:
            out["reason"] += evidence_gap
        return out

    @staticmethod
    def _kind_follow_note(reading: Mapping[str, Any]) -> str:
        """D-37 的"还差什么"那一句（三态里 `held` / `unreadable` 的那一半）。

        为什么必须说出来：证据不够时"没升"与"升了但没变化"在返回值上同形，
        而调用方要能分辨"再去拿一份证据"与"不用再交一次"。`upgraded` 与 `not_applicable`
        都不产出这句话 —— 前者已经写在 `changes` 里，后者是"本来就不该改"。
        """
        state = str((reading or {}).get("state") or "")
        if state == "held":
            return ("（`kind` 仍是 conjecture：要升成 theorem / lemma 还差 —— "
                    + str((reading or {}).get("shortfall") or "凭据不够") + "）")
        if state == "unreadable":
            return ("（`kind` 升不升判不了："
                    + str((reading or {}).get("shortfall") or "五元位算不出来") + "）")
        return ""


def _complete_statement_bits(body: Mapping[str, Any], *, kind: str, origin: str,
                             ) -> dict[str, Any]:
    """把这一笔交上来的 `bits` 补成完整的 10 键（缺哪一格补哪一格）。

    ## 三条口径（「拒或补全」里的"补全"那一半）

    1. 调用方交了 `bits` ⇒ 按 `evidencebits.normalize_raw` 归一遍（四态/布尔归一、
       等级现算）。归一只补不删：`evidence` / `voided_by` 两个口袋原样保留。
    2. 没交（或交的是空表）⇒ 从这一行自己的字段现算
       （`evidencebits.bits_of`）：`origin` / `source_lit_id` / `quote_verified`
       决定第 2、3 位的引用那一档，`proof_text` 非空即第 2 位为真。
       这一档就是 000019 那一行本来该走的：它是 `own_result`、`proof_text` 为空、
       `quote_verified=None` ⇒ 第 2/3 位为假、等级现算成 `conjecture`，而不是"全空"。
    3. 补完还缺键或有 `None` ⇒ 抛 `ValueError`（「拒」那一半）。`record_statement`
       把它翻成受控拒绝 `write_failed` + 原话，一行都不落。
       `None` 也算缺：`grade=None` 与"没有 grade"在读侧长得一样，而它俩都让
       "档位、等级读不出来"这件事重新成立。
    """
    from . import evidencebits as EB   # 惰性：位的唯一实现

    raw = dict(body.get("bits") or {})
    want_origin = str(origin or body.get("origin") or "own_result")
    if raw:
        bits = EB.normalize_raw(raw, origin=want_origin, kind=kind,
                                voided_by=dict(raw.get("voided_by") or {}))
    else:
        proof_text = str(body.get("proof_text") or "")
        bits = EB.bits_of(
            origin=want_origin,
            source_lit_id=str(body.get("source_lit_id") or ""),
            quote_verified=body.get("quote_verified"),
            proof=bool(proof_text.strip()),
            proof_process=proof_text,
            kind=kind,
        )
    missing = [k for k in STATEMENT_BITS_KEYS if k not in bits or bits.get(k) is None]
    if missing:
        raise ValueError(
            "statements.bits 必须 10 键齐、且没有一格是 None；这一笔缺 "
            f"{missing}（整表只有 {sorted(bits)}）⇒ 整笔不写：落一条空 bits 的行，"
            "档位与等级就再也读不出来（现场 000019）")
    return bits


#: 证明正文进台账的唯一收口闸（2026-11-04，业主裁定：正文必须由手稿承载）。
#:
#: 规则：`proof_text` 与在册那一份不同（或这一行还不存在）⇒ 必须有一份盖住这一份正文、
#: 而且审的是手稿的 V 签。判据只认台账行上的 `manuscript` 非空（`verifications.<号>.jsonl`）：
#: 内联审出来的签（今晚 14:22 那种）没有载体，签块 / `## 依赖` / 按号寻址三样都落不了盘。
PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN = "proof_text_needs_a_manuscript_sign"


def proof_text_manuscript_sign_gate(store: Any, *, proof_text: Any,
                                    statement_full: Any = "",
                                    statement_id: Any = "", proof_no: Any = 1,
                                    origin: Any = "", source_lit_id: Any = "",
                                    defer_without_sign: bool = False
                                    ) -> dict[str, Any]:
    """这一份要写进 `statements.proof_text` 的正文，有没有一份"手稿签"覆盖它。

    ## 为什么判据只在这一处
    写 `statements.proof_text` 的路不止一条：B 的 `register_statement`（新建 / 升档 /
    重复支的 canonical 覆盖）、`table.create` / `table.update` 的 `routed` 分支、
    秘书的合并支 —— 它们最后都落在同一个字段上。把判据放在字段的写入口（本函数由
    `Secretary.record_statement` 与 `B._attach_proofs` 共用），才谈得上"唯一收口"；
    每条路各写一份判据，下一支新写口就会静默漏过去。

    ## 判据（三态，不折平）
    - 这一笔没有正文 / 正文与在册逐字相同 ⇒ `required=False`（不是"查过了、有签"，是
      "这一笔没有要写的新正文"）：升档、重复读数、D 的读稿登记都走这一档，不能被堵死；
    - 文献侧占位签（`origin="external_lit"` 且有 `source_lit_id`）⇒ 放行，理由与
      `register_statement._unsigned_proof_gate` 的文献档同一条（业主 2026-11-02：
      「F 的签 或 文献编号」）；
    - 其余 ⇒ 在 `verifications/<命题号>.jsonl` 里找 `proof_sha256` 等于这一份正文、
      `proof_no` 相同、结论「成立」、`unresolved_errors=0`、且 `manuscript` 非空的
      那一行；找不到 ⇒ 受控拒绝。
    台账读不出来 ⇒ `checked=False` + 拒绝（"没查成"不是"没有签"，两者都不放行，但
    理由必须分开）。

    ## 为什么行不存在也拒绝
    新建一条命题时先落"没有正文"的猜想行拿号、V 审稿签字、再把正文交回来（今晚 14:16
    的现场就是这个顺序）；正文与命题同一次落库且没有号，就无从有"盖住它的台账签"。
    放行它等于把"先签后登记"折成"没签也能登记"。

    返回（键集合固定）：`{checked, required, ok, refused, reason, statement_id,
    proof_no, sha256, covering}`。`covering` 是命中的台账行摘要（`verification_id` /
    `manuscript`），给读的人核对"是哪一份稿上的签"。
    """
    from . import verifications as _VR

    out: dict[str, Any] = {"checked": True, "required": False, "ok": True,
                           "refused": "", "reason": "", "statement_id": "",
                           "proof_no": 0, "sha256": "", "covering": []}
    text = str(proof_text or "").strip()
    if not text:
        out["reason"] = "这一笔没有要写进 proof_text 的正文 ⇒ 这一格不适用"
        return out
    try:
        no = int(_VR.as_proof_no(proof_no) or 1)
    except (TypeError, ValueError):
        no = 1
    out["proof_no"] = no
    sha = _PR.proof_sha(text)
    out["sha256"] = sha
    sid = str(statement_id or "").strip()
    row: Mapping[str, Any] | None = None
    try:
        rows = [dict(r) for r in store.rows("statements")]
    except Exception as exc:  # noqa: BLE001 —— 读不到就不许放行
        out.update(checked=False, ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=(f"`statements` 读不出来（{type(exc).__name__}: {exc}）⇒ "
                           "判不了这一份正文有没有手稿签（没查成不是通过）"))
        return out
    if sid:
        # 按号定位走查口（口径一）；`rows` 是这一层刚读的那一份快照。
        row = SL.by_id(rows=rows, stmt_id=sid)["row"] or None
    elif str(statement_full or "").strip():
        # 正文规范化全等的比对口径只有一处（查口 `duplicate_hits`）。
        row = (SL.duplicate_hits(rows, text=statement_full)["hits"] or [None])[0]
    if row is not None:
        out["statement_id"] = str(row.get("stmt_id") or "")
    if row is not None and str(row.get("proof_text") or "").strip() == text:
        out["reason"] = "与在册那一份正文逐字相同 ⇒ 这一笔不写正文（升档 / 重复读数）"
        return out
    out["required"] = True
    origin_now = str(origin or (row or {}).get("origin") or "")
    lit_now = str(source_lit_id or (row or {}).get("source_lit_id") or "").strip()
    # 概念行的良定义证明不认文献占位签（2026-11-10 业主裁定 甲）：那一份正文必须
    # 由 V 对 b-稿真签过；占位签只给"命题正文摘录自文献"那一档（与
    # `_unsigned_proof_gate` 同一条分界）。
    #
    # 2026-11-18（VPLACE1 缺口 b）：免签只开给"这一份正文就是引文第一遍摘录"那一份，
    # 不再按行级 `origin+lit` 一刀切（否则第二遍改写稿也在这条豁免里）。判据只有一处
    # （`evidencebits.quote_carrier_reading`，读行上的落盘标记 `quote_carrier`）。
    from . import evidencebits as _EB_CARRIER

    _carrier = _EB_CARRIER.quote_carrier_reading(
        row, origin=origin_now, source_lit_id=lit_now,
        kind=str((row or {}).get("kind") or ""), proof_text=text)
    out["quote_carrier"] = dict(_carrier)
    if bool(_carrier.get("first_pass")):
        out["reason"] = ("文献侧：这一份正文就是引文第一遍摘录（落盘标记 "
                         f"`{_EB_CARRIER.QUOTE_CARRIER_KEY}=first`）⇒ 允许入台账"
                         "（与 `register_statement` 的文献档同一条口径）")
        return out
    if row is None:
        if defer_without_sign:
            out["reason"] = ("命题还没在册：有没有签由 B 的 `_unsigned_proof_gate` 判"
                             "（这一道只判'签有没有手稿载体'）")
            return out
        out.update(ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=("这一条命题还没有在册行，而这一笔要写证明正文 ⇒ 没有可落签的号，"
                           "也没有一份盖住它的手稿签。正路：先落一条没有正文的猜想行拿号"
                           "（`kind=\"conjecture\"`）→ 让 V 审那一份手稿（带 `proof_manuscript`）"
                           "→ 再把这一份正文交回同一 `statement_full`。"))
        return out
    # ---- D268 批 2：签这一格只认 `sign_reading.state=="signed"`（可复算的凭据）----
    # 手稿载体那一道还留在下面（这一道只判"签有没有手稿载体"）：两条合起来才是这一格
    # 的原意 —— 签是真的（凭据可复算），而且它在手稿上（不是内联签）。
    from . import vsigns as _VS

    sign = _VS.sign_reading(store.root, statement_id=out["statement_id"],
                            proof_text=text, proof_no=no, store=store)
    out["sign"] = dict(sign)
    if not bool(sign.get("checked")):
        out.update(checked=False, ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=(f"签的读数没查成（{sign.get('why') or '没有读数'}）⇒ "
                           "判不了这一份正文有没有手稿签（没查成不是通过）"))
        return out
    if str(sign.get("state") or "") != "signed":
        votes = int(sign.get("votes") or 0)
        need = int(sign.get("need") or _VR.SIGN_STREAK_NEED)
        state = str(sign.get("state") or "")
        if defer_without_sign:
            out["reason"] = (f"这一份正文的签读数是 {votes}/{need}（state={state}）⇒ "
                             "有没有签由 B 的 `_unsigned_proof_gate` 判"
                             "（这一道只判'签有没有手稿载体'）")
            return out
        out.update(ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=(f"这一份正文（sha {sha[:12]}…）的签读数是 {votes}/{need}"
                           f"（state={state}）⇒ 不能进台账。"
                           f"{sign.get('why') or ''}。正路：让 V 把这一份正文审到连续 "
                           f"{need} 次「成立」并由收方秘书发签（`vsigns.issue` 写 "
                           f"`out/vsigns/<正文sha>.json`），再入库。"))
        return out
    try:
        ledger, bad = _VR.list_verifications(store.root, statement_id=out["statement_id"],
                                             limit=None)
    except Exception as exc:  # noqa: BLE001 —— 读不到不许折成"没有签"
        out.update(checked=False, ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=(f"验证台账读不出来（{type(exc).__name__}: {exc}）⇒ "
                           "判不了这一份正文有没有手稿签（没查成不是通过）"))
        return out
    if bad:
        out.update(checked=False, ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=("验证台账有读不出来的行：" + "；".join(str(b) for b in bad[:3])
                           + " ⇒ 判不了这一份正文有没有手稿签（没查成不是通过）"))
        return out
    any_cover: list[dict[str, Any]] = []
    covers: list[dict[str, Any]] = []
    for item in ledger:
        if str(item.get("proof_sha256") or "").lower() != sha:
            continue
        try:
            if int(item.get("proof_no") or 1) != no:
                continue
        except (TypeError, ValueError):
            continue
        if not _VR.row_signable(item):
            continue
        one = {"verification_id": str(item.get("verification_id") or ""),
               "manuscript": str(item.get("manuscript") or ""),
               "at": str(item.get("at") or "")}
        any_cover.append(one)
        if one["manuscript"]:
            covers.append(one)
    out["covering"] = covers[:5]
    if not covers:
        if any_cover:
            out.update(ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                       reason=("这一份正文（sha {sha}…）在 V 的台账里有签，但那一签是"
                               "内联审出来的（台账行上没有 `manuscript`）—— 内联签没有"
                               "载体，签块 / `## 依赖` / 按号寻址三样都落不了盘。正路：先把"
                               "正文落成一份稿（`reports/f-proof-*.md` / `notes/*.md`）→ "
                               "派 V 用 `verify.verify_proof` 带 `proof_manuscript` 审那一份"
                               "稿 → 签块落回稿 → 再入库。").format(sha=sha[:12]))
            return out
        if defer_without_sign:
            out["reason"] = ("这一份正文还没有任何覆盖它的签：有没有签由 B 的 "
                             "`_unsigned_proof_gate` 判（这一道只判'签有没有手稿载体'）")
            return out
        out.update(ok=False, refused=PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN,
                   reason=("这一份正文（sha {sha}…）一次都没有被 V 签过 ⇒ 不能进台账。"
                           "正路：先把正文落成一份稿（`reports/f-proof-*.md` / `notes/*.md`）"
                           "→ 派 V 用 `verify.verify_proof` 带 `proof_manuscript` 审那一份稿"
                           "→ 签块落回稿 → 再入库。").format(sha=sha[:12]))
        return out
    out["reason"] = (f"有手稿签覆盖这一份正文（{len(covers)} 行："
                     + "、".join(str(c.get("verification_id") or "?") for c in covers[:3])
                     + "）")
    return out


def _bits_bear_evidence(bits: Any) -> bool:
    """`bits` 里有没有「调用方显式给的真凭据」（决定正文闸 defer 不 defer）。

    ## 为什么不能按 truthiness 判（2026-11-06 真退化）

    2026-11-05「等级是唯一的轴」之后，盘上每一行的 `bits` 是 10 键规范化的字典
    （`numeric/proof/reviewed/formal/audited/origin/evidence/voided_by/grade/
    audited_badge` 全在，值可以是 pending/false）—— 它恒 truthy。而
    `table.update` 的 routed 分支会把盘上整行叠进 body（`merged = dict(current)`），
    于是 `bool(body.get("bits"))` 把"盘上那一行原样带回来的空 bits"读成了
    "调用方给了证据" ⇒ 正文闸被 defer，一条没有手稿签的新行照样建出来
    （`table.update(statements, patch={statement_full, proof_text})` 实测建出 000001）。

    判据：只有第 2/3 位为真，或第 1/4 位 `verified`，才算"带真凭据"。全
    pending/false 的规范化空位不算 —— 它不是证据，只是"这一行有位记录"。
    """
    if not isinstance(bits, Mapping):
        return False
    raw = dict(bits)
    if not raw:
        return False
    if bool(raw.get("proof")) or bool(raw.get("reviewed")):
        return True
    for name in ("numeric", "formal"):
        value = raw.get(name)
        if isinstance(value, Mapping):
            if any(str(one).strip().lower() == "verified" for one in value.values()):
                return True
        elif str(value or "").strip().lower() == "verified":
            return True
    return False


def _semantic_quote_evidence_refusal(body: Mapping[str, Any]) -> dict[str, str]:
    """`quote_mode="semantic"` 但缺证据 ⇒ `{refused, reason}`；不适用/证据齐 ⇒ `{}`。

    语义那一档必须留证据：`quote_span`（来源那一段逐字正文）与
    `quote_call_sha256`（那次语义判定的调用记录）缺一不可 —— 说不出对着哪一段、
    哪一次判的，就不算通过（三态纪律：没查不许折成查过了没问题）。

    为什么单列成函数：它此前内联在 `Secretary.record_statement` 里，而那方法在
    2026-11-07 的体量读数里刚好越过 200 行基线；判据（`_normalize_quote_mode`）
    与拒码都没变，只是把这一格搬到"写库前可读拒绝"自己的函数里。
    """
    if str(body.get("quote_mode") or "") != "semantic":
        return {}
    span = str(body.get("quote_span") or "").strip()
    call = str(body.get("quote_call_sha256") or "").strip()
    if span and call:
        return {}
    miss = "quote_span（来源那一段逐字正文）" if not span else \
        "quote_call_sha256（那次语义判定的调用记录）"
    return {"refused": "quote_evidence_missing",
            "reason": (f"标了 quote_mode='semantic' 但缺 {miss} —— 语义那一档"
                       "必须留证据：说不出对着哪一段、哪一次判的，就不算通过。"
                       "补上这两栏，或把 quote_verified 改成 None/False 并写明"
                       "为什么（三态纪律：没查不许折成查过了没问题）")}


def _manuscript_upgrade_basis(*, root: Any, manuscript_text: Any = "",
                              manuscript_path: Any = "", proof_text: Any = "",
                              bits: Mapping[str, Any] | None = None
                              ) -> dict[str, Any]:
    """这一笔带来的证据里，有哪一路 V 的签 ⇒ `{checked, signed, basis, why, manuscript}`。

    ## 为什么需要这一格（2026-11-04，缺口 ②）
    同一套代码两个分支结果不一致（真机读数：`stmt 000000`）：命中在册 ⇒
    `evidence_kind` 停在 `cross_check`、`kind` 停在 `conjecture`；新建 ⇒
    `kind=theorem`、`evidence_kind=proof`。根因是 `_upgrade_evidence_kind` 只读
    `verifications.proof_review_gap`（签名台账 `verifications/<命题号>.jsonl`），
    而 E 这一签在"手稿签块 + pending 台账"里 ⇒ 读不到。

    ## 三档（两路新凭据 + 没签）
    - 手稿签块：`vsigns.manuscript_sign_standing(手稿正文, proof_sha=证明栏)` 的
      `state="signed"`（连续次数够、正文 sha 相符、块与稿不互相打脸）；
    - `bits.reviewed`：B 收录时按正文 sha 认到的签（逐份记在
      `bits.evidence.reviewed_by_proof[证明号]`），且第 2 位（proof）为真；
    - 都没有 ⇒ `signed=False`，`why` 说清"没签"（不是"没查成"）。
    手稿给了但读不出来 ⇒ `checked=False`（没查成不许折成没签）。

    这一格是纯读：不改行、不写盘。判据本体（"这一签算不算"）仍只在
    `vsigns.manuscript_sign_standing` 与 `bits` 的现算里，这里只把两路结论收拢。
    """
    out: dict[str, Any] = {"checked": True, "signed": False, "basis": "",
                           "why": "", "manuscript": {}}
    text = str(manuscript_text or "")
    proof = str(proof_text or "")
    if text.strip():
        out["checked"] = False
        try:
            from . import verifications as _VR   # 惰性：正文 sha 的口径只有一处
            from . import vsigns as _VS          # 惰性：签块读数的口径只有一处

            sha = _PR.proof_sha(proof) if proof.strip() else ""
            ms = _VS.manuscript_sign_standing(
                text, proof_sha=sha, manuscript_path=str(manuscript_path or ""))
            out["manuscript"] = {k: ms.get(k) for k in (
                "state", "signed", "streak", "need", "proof_sha256",
                "body_mismatch", "why")}
            out["checked"] = True
            if str(ms.get("state") or "") == "signed":
                out.update(
                    signed=True,
                    basis=(f"手稿签块（连续 {int(ms.get('streak') or 0)}/"
                           f"{int(ms.get('need') or 0)} 成立、正文 sha 相符）"))
                return out
        except Exception as exc:  # noqa: BLE001 —— 读不出来要如实说，不许折成"没签"
            out["checked"] = False
            out["why"] = (f"手稿签块读取失败（{type(exc).__name__}: {exc}）"
                          "⇒ 这一格没查成，不是「没签」")
    b = dict(bits or {})
    if bool(b.get("proof")) and bool(b.get("reviewed")):
        out.update(checked=True, signed=True,
                   basis=("bits.reviewed（第 3 位；B 收录时按正文 sha 认到的逐份签）"))
        return out
    if not str(out.get("why") or "").strip():
        out["why"] = ("手稿里没有 V 的签块，`bits.reviewed` 也不是真 ⇒ "
                      "这一笔没有覆盖这份正文的签（不许因为「命中在册」就升档）")
    return out


def _signed_exhaustion_terminal(*, root: Any, row: Mapping[str, Any],
                                proof_text: Any, experiments: Any
                                ) -> dict[str, Any]:
    """这一行是不是已经停在「穷举程序 + V 签 ⇒ `proof`」那个终态 —— 纯读。

    ## 为什么需要这一格（甲 的落点，2026-11-04 业主裁定）
    穷举数值证明 + 针对该穷举的 V 签 ⇒ 直接 `proof`（`schema.EVIDENCE_KINDS` 的
    口径；`proof_review` 是"V 逐行走查文字证明"，V 不能逐行走查一份程序）。于是
    `verifications._grade_recomputed_from_signature` 在 V 落签那一刻就按通道把这一行
    定到 `proof` —— 等到 B 拿着 D 的目录来登记同一条内容时，盘上那一行已经是
    `proof`，B 那一笔没有任何格可改。

    ## 这一格解决什么
    那样一笔既不是"重复登记"（东西确实在库里、就停在它该在的那一档），也不是"这次
    升了档"（盘上没动）。秘书的升档梯子只认"弱 → 强"（`WEAKER_THAN_PROOF_REVIEW`），
    `have == want == "proof"` 落不进任何一支 ⇒ 会掉进 `duplicate_statement` 的拒信里，
    让"穷举证明已经进库"被读成"没写成"。所以这里给一条只读判据：同一条内容、要的
    就是 `proof`、而盘上那一行已经是 `proof`，且凭据正是穷举程序 + V 签 ⇒ 终态，这一笔
    是空操作（`at_tier=True`）。

    ## 判据只有一处（与回填、审计同一份）
    ① 证明栏要有与它对应的、V 签下的穷举证明：`numericproof.find_signed_exhaustion_for_column`
    （与 `verify` 的 `proof_stmt_without_formal_backing` 第二条合法背书同一个函数）；
    ② 这一份正文要被 V 的签盖住：`verifications.proof_review_gap`（写入期闸 / 审计期 /
    收工门读的都是它）。两条缺一条都不认终态（保守：宁可走原来那一档读数）。

    返回 `{checked, terminal, script, experiment_id, why}`；`terminal=False` 时调用方
    保持原来的 `duplicate` 路径。
    """
    out: dict[str, Any] = {"checked": False, "terminal": False, "script": "",
                           "experiment_id": "", "why": ""}
    text = str(proof_text or row.get("proof_text") or "")
    if not text.strip():
        out["checked"] = True
        out["why"] = "这一行没有证明正文 ⇒ 没有可认的穷举证明（不认终态）"
        return out
    try:
        from . import numericproof as _NP   # 惰性：穷举判据的单一口径
        from . import verifications as _VR  # 惰性：签的判据只有一处

        hit = _NP.find_signed_exhaustion_for_column(experiments or (), text)
    except Exception as exc:  # noqa: BLE001 —— 判不了就不认终态（不是"认了"）
        out["why"] = (f"穷举判据读不出来（{type(exc).__name__}: {exc}）"
                      "⇒ 这一格没查成，按原来的重复读数走")
        return out
    out["checked"] = True
    if hit is None:
        out["why"] = ("台账里没有与这份证明栏对应的、V 签下的穷举证明 "
                      "⇒ 不是「穷举程序 + V 签」那一通道")
        return out
    out["experiment_id"] = str(hit.get("experiment_id") or hit.get("id") or "")
    try:
        out["script"] = _NP.proof_column_script(text)
        probe = dict(row)
        probe["proof_text"] = text
        probe["evidence_kind"] = _VR.PROOF_KIND
        gap = _VR.proof_review_gap(root, probe)
    except Exception as exc:  # noqa: BLE001 —— 同上：没查成就不认
        out["why"] = (f"这一份正文的签读不出来（{type(exc).__name__}: {exc}）"
                      "⇒ 这一格没查成，按原来的重复读数走")
        return out
    if not gap.get("ok"):
        out["why"] = ("这一份正文没有被 V 的签盖住"
                      f"（{str(gap.get('why') or '查不到凭据')[:240]}）⇒ 不认终态")
        return out
    out["terminal"] = True
    out["why"] = ("盘上这一行已经是「穷举程序 + V 签 ⇒ proof」的终态："
                  f"证明栏 ① 段是 {out['script'] or '（空）'}，"
                  f"台账里 exp:{out['experiment_id'] or '?'} 是 V 签下的穷举证明，"
                  f"V 的签盖住的就是这一版（{gap.get('ledger') or ''}"
                  f"#{gap.get('verification_id') or ''}）")
    return out
