# -*- coding: utf-8 -*-
"""秘书的同种证明判定（从 secretary.py 的 U22 的证明种侧逐字搬出）。

我保证哪条不变式：同种证明是二态判定，不是一个阈值：判不了就回「判不了」，不许折成「不同」。

## 为什么它能单独成文件（依赖方向）

`secretary_proofkind` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_proofkind` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import proofregistry as _PR
from . import propositionkey as _PK
from . import schema as S
from . import statementledger as SL
from typing import Mapping

from .secretary_wash import (  # noqa: F401 — 这些名字由 secretary_wash 定义
    _stmt_edge_count,
)


class ProofkindMixin:
    """同种证明判定（从 secretary.py 搬出的混入类）。"""

    def _proof_kind_for_existing(self, *, full: str, body: Mapping[str, Any],
                                 adjudication: Mapping[str, Any]) -> dict[str, Any]:
        """在事务外先问一次"这一份证明与在册各路径同种吗"，把结论带进事务。

        锁内不许发模型调用（硬规矩）：`record_statement` 这一笔在拿锁之前先读一次
        台账、问一次 `judge("proof_kind", …)`，事务里只落结论。适用范围与"新路径"
        同一档（`proof_path_kind="new_path"`，或同一性判定指到在册某一条）：
        - 同一份正文（sha 已在册）⇒ 不问（那是幂等重交，走"逐字同一份"那一支）；
        - 这一笔带来的是在册那一行自己的稿（同一份稿改正文）⇒ 不问（改稿不是新路径）；
        - 没有证明正文 / 没有在册行 ⇒ 不问（新命题 / 首份，没有同种可言）。
        返回 `_same_kind_hits` 的原样读数（空字典 = 这一档不问）。
        """
        from . import verifications as VR
        from . import vsigns as _VS

        proof = str(body.get("proof_text") or "")
        if not proof.strip():
            return {}
        try:
            rows = [dict(r) for r in self.store.rows("statements")]
        except Exception:  # noqa: BLE001 —— 读不到台账 ⇒ 这一问没查成（fail-closed）
            return {"checked": False, "decision": "", "same_path": 0, "hits": [],
                    "unjudged": [], "similarity": 0.0, "paths": [],
                    "reason": "statements 读不出来 ⇒ 同种证明这一问没查成"}
        if adjudication.get("checked") and str(adjudication.get("same_as") or ""):
            target = str(adjudication.get("same_as") or "")
            row = next((r for r in rows if str(r.get("stmt_id") or "") == target), None)
        else:
            hits = SL.duplicate_hits(rows, text=full)["hits"]
            row = dict(hits[0]) if hits else None
        if row is None:
            # 措辞不同的同一条命题：机械键相同的那一行也是"在册可比的那一条"
            # （判定归秘书；这里只定"跟哪一行比"，与 `_proposition_owner` 同一口径）。
            try:
                key = _PK.proposition_key(full)
                row = next((r for r in rows
                            if _PK.proposition_key(str(r.get("statement_full") or ""))
                            == key), None)
            except Exception:  # noqa: BLE001 —— 抽不出键 ⇒ 没有可比行（不猜）
                row = None
        if row is None:
            return {"checked": True, "decision": "different", "same_path": 0,
                    "similarity": 0.0, "paths": [], "hits": [], "unjudged": [],
                    "reason": ("在册没有可比的那一条命题（新命题 / 首份）"
                               "⇒ 没有同种可言，按 different 走")}
        known = {VR.text_sha(str(t)) for _no, t in VR.proof_list(row)
                 if str(t or "").strip()}
        if VR.text_sha(proof) in known:
            return {}
        manuscript = str(body.get("manuscript_path") or "")
        if manuscript:
            try:
                mid = _VS.manuscript_id_of(manuscript)
            except Exception:  # noqa: BLE001 —— 认不出稿号就当"不是同一份稿"
                mid = ""
            if mid and str(row.get("manuscript_id") or "") == str(mid):
                return {}
        return self._same_kind_hits(row, proof)

    def _same_kind_hits(self, row: Mapping[str, Any], proof: str) -> dict[str, Any]:
        """这一份新证明与在册各路径是不是同一套证法（秘书的二态语义判定）。

        判据只有一处：`self.judge("proof_kind", …)` —— 业主 2026-11-12：「对比证明方法
        后发现有很大差别（语义判别，千万别做任何机械闸，结论是二态的：一致/不同）」。
        改前这里是 `propositionkey.same_kind_proof` 的 Jaccard 阈值判定线；现在它只剩
        `similarity` 这一个材料读数（写进回执供人看），一个字节都不参与收不收。

        返回：
        - `checked`：这一问判成了没有；`False` ⇒ 调用方 fail-closed（不收录）；
        - `decision`：`same` / `different`（判成了才有）；
        - `same_path`：判 same 时它对应哪一条在册路径的 `path_group`（坏值退回第一条）；
        - `hits` / `unjudged`：与改前同形的两个列表（调用方只读这两个）；
        - `similarity`：逐路径 `propositionkey.proof_similarity` 的最大值，只作材料。
        """
        from . import verifications as VR   # 惰性：证明清单的唯一读口径

        out: dict[str, Any] = {"checked": False, "decision": "", "same_path": 0,
                               "similarity": 0.0, "paths": [], "hits": [],
                               "unjudged": [], "reason": "", "vacant_reading": {}}
        text = str(proof or "")
        if not text.strip():
            out.update(checked=True, decision="different",
                       reason="这一笔没有证明正文 ⇒ 没有同种可言")
            return out
        # ---- 「难以自证」的路径不进比较（业主 2026-11-13 裁定）------------------
        #
        # 判据只有一处（`manuscriptpaths.vacant_path_reading`）。它不是"在册没有证明"，
        # 而是"那一条的号是空号"：拿空号去跟新稿比"是不是同种"，正是业主担心的
        # 「后续正式 V 签稿被 B 秘书侧以已有证明拒」—— 一方是引文占位、一方是形式证明，
        # 语义判定却可能说"同一路"，于是整份正式稿被拒在门外。
        # 读不出来（`checked=False`）⇒ 一个号都不扣（fail-closed：按普通已有证明判）。
        from . import manuscriptpaths as _MPvac

        vac = _MPvac.vacant_path_reading(row)
        out["vacant_reading"] = dict(vac)
        vacant = [int(g) for g in (vac.get("groups") or [])] if vac.get("checked") else []
        paths = [{"path_group": int(no), "text": str(t)}
                 for no, t in VR.proof_list(row) if str(t or "").strip()
                 and int(no) not in vacant]
        out["paths"] = paths
        for one in paths:
            try:
                sim = float(_PK.proof_similarity(text, one["text"]))
            except Exception:  # noqa: BLE001 —— 相似度只是读数，算不出来不影响判定
                sim = 0.0
            out["similarity"] = max(out["similarity"], sim)
        if not paths:
            out.update(checked=True, decision="different",
                       reason=("在册各路径都处于「难以自证」状态 ⇒ 那些号是空号、"
                               "没有可比的证明正文：这一份是填上空号的那一份"
                               if vacant else "在册没有可比的证明正文 ⇒ 这是第一条路径"))
            return out
        got = dict(self.judge("proof_kind", {
            "statement_full": str(row.get("statement_full") or ""),
            "label": str(row.get("label") or ""),
            "proof_text": text,
            "proofs": paths,
        }, note="secretary:proof_kind") or {})
        out["reason"] = str(got.get("reason") or "")
        if not got.get("checked"):
            out["unjudged"] = [{"proof_no": p["path_group"],
                                "path_group": p["path_group"],
                                "reason": out["reason"] or "同种证明这一问没查成"}
                               for p in paths]
            return out
        out["checked"] = True
        out["decision"] = str(got.get("decision") or "")
        known = [p["path_group"] for p in paths]
        try:
            same_path = int(got.get("same_path") or 0)
        except (TypeError, ValueError):
            same_path = 0
        if out["decision"] == "same":
            out["same_path"] = same_path if same_path in known else known[0]
            out["hits"] = [{"proof_no": out["same_path"],
                            "similarity": out["similarity"],
                            "detail": {"material_similarity": out["similarity"]},
                            "reason": out["reason"]}]
        return out

    def _merge_target(self, row: Mapping[str, Any], proof: str,
                      body: Mapping[str, Any],
                      existing: Sequence[tuple[int, str]]) -> tuple[int, str]:
        """合并稿要覆盖哪一份证明：显式号优先，没给就取与合并稿最像的那一份。

        返回 `(证明号, 依据说明)`；证明号 < 1 表示"指定了一个不在册的号"（调用方据此拒绝）。
        为什么允许不显式给号：合并稿与两份原稿都不像（那是"各取所长"的必然结果），
        所以"最像"只能当线索；真的指错了，`proof_history` 里留着被覆盖的旧正文，
        读的人能看出来并让它重走一次。显式号则是确定的（拒信里会把它给调用方）。
        """
        explicit = body.get("proof_no")
        if explicit not in (None, "", 0):
            try:
                no = int(explicit)
            except (TypeError, ValueError):
                no = 0
            if any(int(no) == int(n) for n, _ in existing):
                return int(no), "显式给了 proof_no"
            return 0, f"而 proof_no={explicit!r} 不在册（在册的是 {[n for n, _ in existing]}）"
        best: list[tuple[float, int]] = []
        for no, text in existing:
            if not str(text or "").strip():
                continue
            best.append((_PK.proof_similarity(proof, str(text)), int(no)))
        if not best:
            return 1, "这条命题还没有任何证明正文 ⇒ 合并稿落成 #p1"
        best.sort(key=lambda item: (-item[0], item[1]))
        score, no = best[0]
        return no, f"没给 proof_no，取与合并稿最像的那一份（#{no}，相似度 {score:.4f}）"

    def _merge_same_kind_version(self, tx: Any, *, row: dict[str, Any], sid: str,
                                 full: str, proof_no: int, merged_text: str,
                                 verdict: Mapping[str, Any],
                                 kind_hits: list[dict[str, Any]],
                                 merge_note: str,
                                 out: dict[str, Any],
                                 body: Mapping[str, Any] | None = None,
                                 groups: list[list[dict[str, Any]]] | None = None
                                 ) -> dict[str, Any]:
        """`merge=True` 那一档：把合并稿作为"那一份证明的新版本"，并要求 V 重签。

        ## 写什么
        - 被命中的那一份（第 k 份）的正文换成调用方交来的合并稿：k=1 时是行上的
          `proof_text`（canonical 那一格），k>1 时是 `proofs` 清单里的那一条；
        - 旧正文整段留痕：进 `proof_history`，元素形状与 canonical 覆盖那一支逐字相同
          （`{text, sha, at, replaced_by}`）再加一格 `proof_no` —— 否则一条命题有多份
          证明时，"这一版是哪一份的旧稿"读不出来；
        - 合并痕迹那一格记下这一笔合并了哪几份、相似度、谁做的。有界，只留最近 20 条。

        ## 为什么"合并"与"直接覆盖"必须分开（业主原话：重拿 V 签）
        直接覆盖只是改稿（`stale` 是读数）；合并是"两份同种证明合成一份"，它的正确性
        依赖 V 重新看过合并稿。所以这里不动 `bits`、也不写任何"审过了"的凭据，
        返回值里 `resign_required=True` 且把 V 的现行状态如实报出来（`proof_standing`）：
        合并稿与旧签的 sha 不同 ⇒ `review_standing` 现算是 `stale`，`reviewed` 是 False，
        "未重签之前不算成立"这句话由读侧现算，而不是由本函数说一句"已成立"。
        """
        from . import verifications as VR   # 惰性：签名状态与正文 sha 的唯一读口径

        old_text = VR.proof_text_of(row, proof_no)
        entry = {"text": old_text, "sha": _PR.proof_sha(old_text), "at": S.now_iso(),
                 "replaced_by": _PR.proof_sha(merged_text), "proof_no": int(proof_no)}
        history = [dict(h) if isinstance(h, Mapping) else h
                   for h in (row.get("proof_history") or [])]
        history.append(entry)
        row["proof_history"] = history
        if int(proof_no) == 1:
            row["proof_text"] = merged_text
        else:
            listed = []
            for item in (row.get(VR.PROOFS_KEY) or []):
                one = dict(item) if isinstance(item, Mapping) else item
                if isinstance(one, Mapping) and int(VR.proof_no_of(one)) == int(proof_no):
                    one["text"] = merged_text
                listed.append(one)
            row[VR.PROOFS_KEY] = listed
        merges = [dict(m) for m in (row.get("_proof_merge") or [])
                  if isinstance(m, Mapping)]
        merges.append({"proof_no": int(proof_no),
                       "from_proofs": [int(h["proof_no"]) for h in kind_hits] or [int(proof_no)],
                       "similarity": [float(h["similarity"]) for h in kind_hits],
                       "matched_by": str(verdict.get("basis") or ""),
                       "target": merge_note,
                       "statement_full": str(full),
                       "at": S.now_iso(), "by": f"secretary-{self.role}",
                       "resign_required": True})
        row["_proof_merge"] = merges[-20:]
        matches = [dict(m) for m in (row.get("_proposition_matches") or [])
                   if isinstance(m, Mapping)]
        matches.append({"statement_full": str(full),
                        "basis": str(verdict.get("basis") or ""),
                        "similarity": float(verdict.get("similarity") or 0.0),
                        "proof_no": int(proof_no), "at": S.now_iso(),
                        "by": f"secretary-{self.role}", "merged": True})
        row["_proposition_matches"] = matches[-20:]
        # ---- 2026-11-04（业主裁定）：合并稿的依赖边与正文同一次事务落盘 ----------
        #
        # 改前这一支不写依赖：`_merge_into_proposition` 收到的 `groups` 在这一支里被整份
        # 丢掉，盘上留下的是旧正文的依赖边 —— 而 `proof_text` 已经换成合并稿，"这一条
        # 证明依赖什么"与"它的正文"从此各说一件事，且没有任何读数会说它们分家了。
        # 判据与"新建 / 第 N 份证明"那两支共用 `_resolve_write_steps` + `_write_dep_steps`：
        # 显式 `deps` 指着不在册的号 ⇒ 整笔不写；扫出来的引用照旧落 `dangling` / 点名。
        # 旧边不删（它们可能仍被合并稿用到）：这一笔只追加，`used_by` 落到同一个证明号。
        body_for_deps = dict(body or {})
        body_for_deps["proof_no"] = int(proof_no)
        steps = self._resolve_write_steps(tx, body_for_deps, out,
                                          [list(g) for g in (groups or [])])
        if steps is None:
            return out
        deps_written = self._write_dep_steps(tx, steps, stmt_id=sid, body=body_for_deps)
        tx.upsert("statements", row, note="record_statement:merge_same_kind")
        standing: dict[str, Any] = {}
        try:
            standing = VR.review_standing(self.store.root, statement_id=sid,
                                          proof_text=merged_text, proof_no=int(proof_no))
        except Exception as exc:  # noqa: BLE001 —— 读不到签名状态不等于"已重签"
            standing = {"state": "unknown",
                        "why": f"签名状态读不出来（{type(exc).__name__}: {exc}）⇒ "
                               "按'未重签'处理（不许把没查成读成已成立）"}
        state = str(standing.get("state") or "unsigned")
        out.update(checked=True, created=False, duplicate=False, merged=True,
                   merged_same_kind=True, merged_into=sid, stmt_id=sid,
                   proof_no=int(proof_no), matched_by=str(verdict.get("basis") or ""),
                   similarity=float(verdict.get("similarity") or 0.0),
                   same_kind=kind_hits,
                   tables=(["statements", "dependencies"] if deps_written else ["statements"]),
                   deps_written=deps_written,
                   #: 其中"命题→命题"几条（2026-11-05 缺陷 1c：两个数分开读）。
                   deps_stmt_edges=_stmt_edge_count(steps),
                   row=row, canonical_written=int(proof_no) == 1,
                   proof_history=list(row["proof_history"]),
                   proof_standing=standing, resign_required=True,
                   reviewed=state == "signed",
                   reason=(f"合并稿已作为 stmt:{sid} 第 {proof_no} 份证明的新版本落盘"
                           f"（{merge_note}；旧正文整段进 `proof_history`，sha 可与签名"
                           "台账的 `proof_sha256` 直接对上）；这一笔的依赖边同时落进 "
                           f"`dependencies`（{deps_written} 条，`used_by=\"stmt:{sid}#p{proof_no}\"`，"
                           "旧边不删）；这一笔是同种证明合成一份，"
                           f"按业主口径要 V 重签 —— 现行签名状态是 `{state}`，"
                           "未重签之前不算成立（读侧现算，不由本函数声明）"))
        return out


#: 同种证明的判据（同一命题下的第 N 份证明）：判成 `same` ⇒ 不新增证明号，受控拒绝
#: `proof_same_kind`（或 `merge=True` 合成一份并重拿 V 签）。判据是秘书的语义二态
#: （`Secretary.judge("proof_kind", …)`：语义判别，不做机械闸，结论只有一致/不同）；
#: 相似度只作材料读数，不参与收不收。
PROOF_SAME_JACCARD = _PK.PROOF_SAME_JACCARD


#: 同种证明的拒收码（写侧与拒信共用这一个字面量）。
PROOF_SAME_KIND = "proof_same_kind"


#: 同种证明这一问"没判成"的受控码（「没有判不了」）。
#:
#: 为什么必须与 `PROOF_SAME_KIND` 分开：那一档是现象结论（"判过了、同种"），这一档
#: 没有结论（判定面回 `checked=False`：超时 / 坏 JSON / 没给可用答案都落这一档）。
#: 折平会把"没判成"读成"判过了、不同"（于是照旧新增证明号）或"同种"（于是静默拒收）
#: —— 前者是同一种证法被并列记录，后者是一份真的另一种证法被拒，两种都错。
PROOF_KIND_UNJUDGED = "proof_kind_unjudged"
