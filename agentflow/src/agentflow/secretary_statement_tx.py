# -*- coding: utf-8 -*-
"""秘书的登记事务（一笔全落或一字节不落，从 secretary.py 的 U22 的事务侧逐字搬出）。

我保证哪条不变式：一笔全落或一字节不落；锁里不许有网络等待 —— 所以判断在事务外、写在事务内，这条缝就是本文件与 `secretary_merge` / `secretary_identity` 之间的边界。

## 为什么它能单独成文件（依赖方向）

`secretary_statement_tx` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_statement_tx` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import schema as S
from . import statementledger as SL
from typing import Mapping

from .secretary_concept import (  # noqa: F401 — 这些名字由 secretary_concept 定义
    concept_identity_action,
    concept_identity_gate,
)

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    STATEMENT_BITS_KEYS,
    STATEMENT_WRITE_TABLES,
)

from .secretary_deps import (  # noqa: F401 — 这些名字由 secretary_deps 定义
    _assign_path_group_in_tx,
    _deps_missing_reading,
    _note_path_material,
    _path_material_numbers,
    _stamp_path_number,
)

from .secretary_label import (  # noqa: F401 — 这些名字由 secretary_label 定义
    wash_working_name,
)

from .secretary_proofkind import (  # noqa: F401 — 这些名字由 secretary_proofkind 定义
    PROOF_KIND_UNJUDGED,
    PROOF_SAME_KIND,
)

from .secretary_tier_judge import (  # noqa: F401 — 这些名字由 secretary_tier_judge 定义
    _is_not_applicable_kind,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    LABEL_WASH_ROUTE,
)

from .secretary_wash import (  # noqa: F401 — 这些名字由 secretary_wash 定义
    _stmt_edge_count,
)


class StatementTxMixin:
    """登记事务（一笔全落或一字节不落）（从 secretary.py 搬出的混入类）。"""

    def _record_statement_tx(self, body: dict[str, Any], *, full: str, kind: str,
                             force_new: bool, out: dict[str, Any],
                             adjudication: Mapping[str, Any] | None = None,
                             candidate_id: str = "",
                             proof_kind: Mapping[str, Any] | None = None
                             ) -> dict[str, Any]:
        """一笔事务把命题（+ 概念行 + 依赖组）落盘（`record_statement` 的写那一半）。

        `adjudication` 是事务之外那一次模型判定（见 `adjudicate_proposition`）：
        它决定这一笔是"并进在册的那一条"还是"新建"，并把定理名洗成 `canonical_name`。
        `proof_kind` 是事务之外那一次"同种证明"判定（`_proof_kind_for_existing`）：
        事务里只读结论、只落盘 —— 锁里不许有网络等待、更不许发模型调用。
        """
        from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口
        from . import textutil as T       # 惰性：查重键的唯一实现
        from . import verifications as VR  # 惰性：新建那一支的 #pN 落点要它的 PROOFS_KEY

        adj = dict(adjudication or {})
        # ---- 洗定理名（业主 2026-10-24）：「Sylow 三定理（路线一：…）」⇒「Sylow 三定理」。
        # 落点是 label；被洗掉的路线进证明那一层（见下面 `PROOF_ROUTES_KEY` 那一格）。
        # 这里只动"写进这一行的那份 body 副本"：调用方交上来的原文一个字不改
        # （`out["label_washed"]` 留着 from / to 两格，静默改名是不许的）。
        if adj.get("checked") and str(adj.get("canonical_name") or "").strip():
            was = str(body.get("label") or "")
            now = str(adj.get("canonical_name") or "").strip()
            if was != now:
                body = dict(body)
                body["label"] = now
                out["canonical_name"] = now
                out["label_washed"] = {
                    "from": was, "to": now, "class": LABEL_WASH_ROUTE,
                    "why": ("标签里的路线 / 自证草稿 / 待 V 审签那一类修饰被洗掉了"
                            "（秘书判同一性那趟给的名字）；被洗掉的路线落进证明那一层，不丢")}
        route = str(adj.get("route") or "").strip() if adj.get("checked") else ""
        out["proof_route"] = route

        groups = [list(g) for g in (body.get("deps") or [])]
        # 显式给了 `deps` ⇒ 走严格那一条（指着一个不在册的号 = 整笔不写：那是 G 的
        # `register_dependency` 那一族的契约）。没给 ⇒ 从证明文本里扫（业主 §14.11：
        # B 只交"定理内容 + 证明过程"），而扫出来的悬空引用按那一条的判据不整笔拒，
        # 落成 `dangling` 并点名。
        scan = {"state": "", "groups": [], "unmappable": [], "paths": 0, "refs": 0}
        if not groups:
            scan = self._scan_proof_deps(body)
            groups = [list(g) for g in scan["groups"]]
        out["deps_state"] = scan["state"]
        out["deps_from"] = "proof" if scan["refs"] else ("explicit" if body.get("deps") else "")
        out["deps_unmappable"] = list(scan["unmappable"])
        out["deps_dangling"] = []
        concepts = [dict(c) for c in (body.get("concepts") or []) if isinstance(c, Mapping)]
        # ---- 概念行（`kind="concept"` 那一条自身）：本批缺陷一的写入侧 -----------------
        # 两件事在这个入口上也要做（它不经过 `conceptrows.write_concept`）：
        # ① `proof_text` 不许写（概念不参与等级链；真机 mp3 的 1143 条概念行每一条都
        #    带着哨兵 `concept:primitive`，把"有没有证明"的读数全顶高了）；
        # ② `origin` 按来源分档：有出处 ⇒ external_lit；没有 ⇒ 自己的概念；
        #    显式写 own_result 必须带 `self_authored`（判据在 `conceptrows`，不抄第二份）。
        if kind == "concept":
            # 良定义证明（2026-11-10 业主裁定 甲）：正文只在 V 已签时保留；没签就清空
            # 并留读数（`concept_proof_text_dropped`）。判据仍是唯一读口
            # `vsigns.sign_reading` —— 这一层不新写一套。
            _body = str(body.get("proof_text") or "")
            _sign: dict[str, Any] = {}
            if _body.strip():
                from . import vsigns as _VS
                _sign = dict(_VS.sign_reading(
                    str(getattr(self.store, "root", "") or ""),
                    statement_id=str(candidate_id or ""), proof_text=_body,
                    proof_no=1, store=self.store))
                if str(_sign.get("state") or "") != "signed":
                    out["concept_proof_text_dropped"] = [str(body.get("label") or "")]
                    body = dict(body)
                    body["proof_text"] = ""
            _src = str(body.get("source_lit_id") or "")
            _want = str(body.get("origin") or "")
            _self_auth = bool(body.get("self_authored"))
            _resolved = CR.resolve_concept_origin(
                origin=_want, source_lit_id=_src, self_authored=_self_auth)
            _self_auth = _self_auth or (_resolved == "own_result" and not _want)
            _problem = CR.concept_origin_problem(
                origin=_resolved, source_lit_id=_src, self_authored=_self_auth)
            if _problem:
                out.update(refused="concept_origin_refused", reason=_problem)
                return out
            body = dict(body)
            body["origin"] = _resolved
            if not dict(body.get("bits") or {}):
                # 五元位由这一层现算（2026-10-26，D14）：改前概念行只在调用方自己带了
                # `bits` 时才有它，而 B 的 pipeline 那条路（`conceptrows` 的三个写口）
                # 从来不带 ⇒ 真机 mp3-r3 的 30 条概念行 `bits` 全空。这一格与
                # `write_concept_row` 用的是同一个 `_concept_bits`（判据不看调用方是谁）。
                body["bits"] = self._concept_bits(
                    origin=_resolved, source_lit_id=_src,
                    proof_text=str(body.get("proof_text") or ""), sign=_sign)
            if out.get("well_definedness") is None:
                out["well_definedness"] = CR.well_definedness_reading(
                    str(getattr(self.store, "root", "") or ""),
                    {"stmt_id": str(candidate_id or ""),
                     "proof_text": str(body.get("proof_text") or "")},
                    sign=_sign, store=self.store)
        legacy = CR.legacy_present(self.store)
        # ---- 调用方给的路径号：忽略，但要让读的人看见「这个号不是它给的」 --------
        #
        # 业主口径：路径号归秘书（这一笔事务里分配）；产出侧不写 `-pN`、B 的动作也
        # 不再自己算。B 若还塞了一个进来，这里不校验、也不采信 —— 校验一致只是
        # 把两套算法并排留着（两份迟早会漂，而漂的那一天没有读数会响）；直接忽略
        # 才不会出现「调用方说了算」的第二条口径。`path_group_ignored` 把收与弃都写下来。
        _given_path_group = 0
        try:
            _given_path_group = int(body.get("path_group") or 0)
        except (TypeError, ValueError):
            _given_path_group = 0
        if _given_path_group >= 1:
            out["path_group_ignored"] = {
                "given": _given_path_group,
                "by": "调用方（B 的动作）",
                "why": ("路径号由秘书在收录事务里分配（`assign_path_group`）⇒ 调用方给的"
                        "这个数一个字节都不采信；回执里的 `path_group` 才是这一笔用的号"),
            }
        with self.store.tx(*STATEMENT_WRITE_TABLES, "literature", "experiments",
                           "documents",
                           *([CR.LEGACY_TABLE] if legacy.get("present") else ()),
                           actor=f"secretary-{self.role}",
                           note="record_statement") as tx:
            # 正文规范化全等的比对口径只有一处（查口 `duplicate_hits`）；
            # 读的是事务快照（`tx.rows`），所以"读—判—写"仍在同一把锁里。
            existing = (SL.duplicate_hits(tx.rows("statements"), text=full)["hits"]
                        or [None])[0]
            if existing is not None and not force_new:
                # ---- 路径号：先算，升档那支与重复那支都要用它 ----------------------
                #
                # 同一命题已在册、而交上来的正文是它的一条新路径（或正本还空着
                # 的"先立命题、后补证明"）⇒ 号在这里分配：B 随后用这个号把正文挂成
                # 第 N 份证明（`_attach_proofs`），依赖面 / `verifications` 行也用它。
                # 号必须在锁里分（锁外分，两个并发收录会同时看到 N ⇒ 都开 N+1）。
                # 同一份正文再交一次 ⇒ 沿用原号（`_same_no`），不新增路径；改稿 /
                # 纯重复读数那两档不分号。
                _dup_proof = str(body.get("proof_text") or "")
                _dup_alloc: dict = {}
                _dup_first_fill = not str(existing.get("proof_text") or "").strip()
                # ---- 「难以自证」的空号 ⇒ 整条替换（业主 2026-11-13 裁定）------------
                #
                # 位置在"重复 / 升档"两档之前：那一格是"引文占位"的正文，不是"已有
                # 证明"的第二次提交 —— 它不许把这一份带真 V 签的新稿挤回任何一档
                # （升档那支会把优化栏打成 true 并留下旧的 hard_to_prove）。
                # 返回 None ⇒ 这一行没有空号（或这一笔就是同一份正文的重交）⇒ 照旧。
                if self._fill_vacant_path_in_tx(
                        tx, row=dict(existing), sid=str(existing.get("stmt_id") or ""),
                        proof_text=_dup_proof, groups=groups, out=out,
                        manuscript=str(body.get("manuscript_path") or "")) is not None:
                    return out
                # ---- 同种证明（业主 2026-11-12）：结论来自事务外那一问，这里只落 -----
                #
                # 只在"这一笔是同一命题的另一条证明路径"（`proof_path_kind=="new_path"）
                # 且正文确实是新的时候判：同一份正文重交是幂等（走 `_same_no`），改稿
                # （B 的改写载体）不是新路径。判不了 ⇒ fail-closed（不收录），不许折成
                # "不同"照旧开新路径。
                _verdict = dict(proof_kind or {})
                _dup_sha = VR.text_sha(_dup_proof) if _dup_proof.strip() else ""
                _known_now = {VR.text_sha(str(t))
                              for _n, t in VR.proof_list(dict(existing))
                              if str(t or "").strip()}
                if (str(body.get("proof_path_kind") or "") == "new_path"
                        and _dup_sha and _dup_sha not in _known_now):
                    _sid_now = str(existing.get("stmt_id") or "")
                    if not _verdict.get("checked"):
                        out.update(checked=False, created=False, duplicate=False,
                                   refused=PROOF_KIND_UNJUDGED, stmt_id=_sid_now,
                                   reason=("这一份证明与在册各路径是不是同种没判成"
                                           "（没判成 ≠ 不同）⇒ 不收录、不新增路径："
                                           + str(_verdict.get("reason")
                                                 or "判定面没给可用结论")))
                        return out
                    if str(_verdict.get("decision") or "") == "same":
                        _n = int(_verdict.get("same_path") or 1)
                        out.update(checked=False, created=False, duplicate=False,
                                   refused=PROOF_SAME_KIND, stmt_id=_sid_now,
                                   same_kind_material={
                                       "similarity": float(_verdict.get("similarity") or 0.0)},
                                   reason=(f"这一份证明与 stmt:{_sid_now} 的第 {_n} 条路径同种"
                                           "（秘书的语义判定：两套证法是同一路，不是两条"
                                           "独立路径）⇒ 不收录、不新增路径。材料读数"
                                           "（只作参考）：相似度 "
                                           f"{float(_verdict.get('similarity') or 0.0):.4f}。"
                                           "处置：换一条真正不同的证法再交，或本次不再提交"))
                        return out
                if ((_dup_first_fill
                     or str(body.get("proof_path_kind") or "") == "new_path")
                        and _dup_proof.strip()):
                    _dup_sha = VR.text_sha(_dup_proof)
                    _same_no = next(
                        (int(no) for no, _t in VR.proof_list(dict(existing))
                         if str(_t or "").strip() and VR.text_sha(str(_t)) == _dup_sha), 0)
                    if _same_no >= 1:
                        out["path_group"] = _same_no
                        out["path_group_reading"] = {
                            "checked": True, "path_group": _same_no, "existing": True,
                            "statement_id": str(existing.get("stmt_id") or ""),
                            "manuscript": str(body.get("manuscript_path") or ""),
                            "body_sha": _dup_sha, "count": 0, "paths": [],
                            "problems": [],
                            "why": (f"这一份正文已经是第 {_same_no} 条路径 ⇒ 沿用原号，"
                                    "不新增路径"),
                        }
                    else:
                        _dup_alloc = _assign_path_group_in_tx(
                            tx, root=self.root,
                            statement_id=str(existing.get("stmt_id") or ""),
                            manuscript=str(body.get("manuscript_path") or ""),
                            body_sha=_dup_sha)
                        if not _dup_alloc.get("checked"):
                            out.update(checked=False, created=False, duplicate=False,
                                       refused="path_group_unreadable",
                                       reason=("路径数读不出来 ⇒ 这一笔不写（不猜第几条）："
                                               + str(_dup_alloc.get("why") or "未知原因")))
                            return out
                        out["path_group"] = int(_dup_alloc.get("path_group") or 1)
                        out["path_group_reading"] = dict(_dup_alloc)
                upgraded = self._upgrade_evidence_kind(existing, body)
                if upgraded.get("upgraded"):
                    # 同一份内容、这一回带来的证据档更强 ⇒ 改那一行（不新建）。
                    # 这是"改表"那一件活的正路，也是 `evidence_kind` 从弱档走到
                    # `proof_review` 的唯一一条路（通用写口 `table.update` 已在
                    # `store.direct_write_refusal` 那一层被拒）。
                    #
                    # `at_tier` 是"盘上已经是终态档（穷举程序 + V 签 ⇒ proof）"那一支：
                    # 这一笔不写（没有格可改），但读数与"升档"分开记 ——
                    # "这次把档改上去了"与"它早就在那一档"是两件事。
                    at_tier = bool(upgraded.get("at_tier"))
                    if not at_tier:
                        tx.upsert("statements", upgraded["row"],
                                  note="record_statement:upgrade")
                    out.update(checked=True, created=False, duplicate=False,
                               upgraded=True, at_tier=at_tier,
                               stmt_id=str(existing.get("stmt_id") or ""),
                               row=dict(upgraded["row"]),
                               tables=[] if at_tier else ["statements"],
                               changes=list(upgraded.get("changes") or []),
                               reason=str(upgraded.get("reason") or ""))
                    if at_tier:
                        out["terminal_reading"] = dict(
                            upgraded.get("terminal_reading") or {})
                    return out
                out.update(checked=True, created=False, duplicate=True,
                           stmt_id=str(existing.get("stmt_id") or ""),
                           # 2026-10-26：这一句改前写着"确实要另起一条，请给 force_new"，
                           # 而走到这里的每一条路（B 的 `register_statement`、被通用写口
                           # 路由过来的 `table.create`）都没有 force_new 这个参数 ——
                           # 拒信因此指了一条不存在的路（`duplicate` 那一档的拒信要能
                           # 把模型指回正路，指的必须是这条路上真有的做法）。
                           reason=("同一条 statement_full 已在册 ⇒ 重复读数，不新建行"
                                   "（要引用既有那一行，用返回里的 stmt_id 即可；"
                                   "确实是另一条命题时把差异写进 statement_full —— "
                                   "正文按规范化比不同才会落新的一行）"
                                   + str(upgraded.get("reason") or "")))
                return out
            # ---- 2026-10-24（业主：表述几乎相同的两条命题是同一个；证明方式几乎相同的
            # 视为同种证明）：同一命题 ⇒ 并成第 N 份证明；同种证明 ⇒ 受控拒绝或合并。
            merged = self._merge_into_proposition(tx, body, full=full, kind=kind,
                                                  groups=groups,
                                                  force_new=bool(force_new), out=out,
                                                  adjudication=adj,
                                                  proof_kind=proof_kind)
            if merged is not None:
                return merged
            steps = self._resolve_write_steps(tx, body, out, groups)
            if steps is None:
                return out
            lit = str(body.get("source_lit_id") or "")
            if lit and tx.find("literature", lit_id=lit) is None:
                lit_rows = tx.rows("literature")
                ids = [str(r.get("lit_id") or "") for r in lit_rows[:8]]
                out.update(refused="unknown_lit_id",
                           reason=(f"literature 表里没有 lit_id={lit!r} ⇒ 这条命题的出处不存在，"
                                   f"整笔不写库。表里现有 {len(lit_rows)} 行，lit_id："
                                   f"{ids or '（一个都没有 —— 表是空的）'}"),
                           literature_rows=len(lit_rows), available_lit_ids=ids)
                return out
            stmt_kind = S.TABLES["statements"]["id_kind"]
            # 过渡期的号空间只有一个权威（老表还在时是 `concept`，迁移之后是 `stmt`）
            concept_kind = (S.TABLES[CR.LEGACY_TABLE]["id_kind"] if legacy.get("present")
                            else stmt_kind)
            # ---- D2（2026-11-05 走查）：稿名 / 稿头的号当候选号，「不另发一个」 -------
            #
            # 现场（`temp/e2e-sign-20261105-b` 主链）：稿名 / 稿头是 000001，而计数器从 0
            # 起 ⇒ 登记拿到 000000。第 4 步靠"新命题还没有号"使 owner 判据短路才过；
            # 第 5 步同一条命令就撞 `manuscript_owner_mismatch`；收工扫盘按「稿名」开
            # `b-register@000001@…` 的义务永远收不了口（`reconcile_registrations` left=1）。
            #
            # 口径①（业主 2026-11-05 选定）：候选号可用 ⇒ 就用它（并把计数器抬到它之后，
            # 下一笔不会又撞）；已被占 ⇒ 受控拒绝 `stmt_id_taken`，绝不静默另发一个 ——
            # 错位是静默的，没有任何事后读数会报它（`verify_all` 0 error 就是那次真空的绿）。
            candidate = str(candidate_id or "").strip()
            if candidate:
                if not S.is_valid_id(candidate):
                    out.update(checked=False, created=False, refused="bad_candidate_id",
                               reason=(f"候选号 {candidate!r} 不是命题号形态"
                                       f"（{S.ID_DIGITS} 位十进制；旧四位仍可读）⇒ "
                                       "整笔不写。稿名 / 稿头要给号就给对形态"))
                    return out
                occupied = SL.by_id(rows=tx.rows("statements"), stmt_id=candidate)["row"]
                if occupied:
                    out.update(checked=False, created=False, refused="stmt_id_taken",
                               stmt_id=candidate,
                               reason=(f"稿名 / 稿头要的号 {candidate} 已被在册命题占用"
                                       f"（{str((occupied or {}).get('label') or '')[:60]!r}，"
                                       f"正文 {str((occupied or {}).get('statement_full') or '')[:80]!r}）"
                                       "⇒ 整笔不写，也不另发一个号：另发会让稿头号与登记号错位，"
                                       "而那个错位是静默的（扫盘义务、第 5 步的 owner 判据都会"
                                       "按错位后的号读）。处置：让作者把稿改成要登记的那个号，"
                                       "或确认这条命题确实已在册（用返回里那个 stmt_id）。"))
                    return out
                stmt_id = candidate
                tx.raise_counter_to(stmt_kind, candidate)
                out["stmt_id_candidate"] = candidate
                out["stmt_id_candidate_source"] = "candidate"
            else:
                stmt_id = tx.alloc_id(stmt_kind)
            # ---- 路径号（业主口径）：这一笔是新建 ⇒ 由秘书在这一笔事务里分配 ------
            #
            # 号在这里分而不是在 B 那一侧：新建的命题还没有任何路径 ⇒ 这个号必然是
            # 第 1 条；但它与"写依赖 / 写 `used_by` / 回执"必须是同一个数，且要在
            # 同一把锁里定下来。`assign_path_group` 是唯一实现（同一份正文 sha /
            # 同一份稿沿用原号 —— 对新建这一档是死路，对合并那一档才是活的）。
            _new_alloc = _assign_path_group_in_tx(
                tx, root=self.root, statement_id=stmt_id,
                manuscript=str(body.get("manuscript_path") or ""),
                body_sha=VR.text_sha(str(body.get("proof_text") or "")))
            if not _new_alloc.get("checked"):
                out.update(checked=False, created=False, refused="path_group_unreadable",
                           reason=("路径数读不出来 ⇒ 这一笔不写（不猜第几条）："
                                   + str(_new_alloc.get("why") or "未知原因")))
                return out
            _new_path_no = int(_new_alloc.get("path_group") or 1)
            _note_path_material(out, _path_material_numbers(groups)
                                if len(groups) <= 1 else [], decided=_new_path_no)
            out["path_group"] = _new_path_no
            out["path_group_reading"] = dict(_new_alloc)
            # ---- 内部工作名不许当定理名（D1；真机 mp3-r2 的 000000 / 000001）---------
            # 那两行的 label 逐字都是「F 攻坚 000000 子目标 S2」：派活台账里的工作名进了
            # 定理名，于是同一条定理的两份证明在台账上看起来是两条不同的定理。判据与词表
            # 在 `wash_working_name`（确定性、零模型调用），位置在这里而不是上面那一格，
            # 是因为兜底那两级要用到刚发下来的 `stmt_id`（第四级名字里有它）。
            # 与模型洗名不冲突：括号里那一类（路线 / 草稿状态）由上一格洗，这一格见括号
            # 不配对就整条不动（见 `_brackets_balanced`）。
            working = wash_working_name(body.get("label"), statement_full=full,
                                        kind=kind, stmt_id=stmt_id)
            if working:
                body = dict(body)
                body["label"] = str(working["to"])
                out["canonical_name"] = str(working["to"])
                out["label_washed"] = dict(working, stmt_id=stmt_id)
            row = self._statement_from(body, full=full, kind=kind, stmt_id=stmt_id)
            row.validate()
            # ---- 2026-11-05（缺陷乙的第二道闸）：10 键齐、没有 None ---------------
            #
            # `_statement_from` 已经用 `_complete_statement_bits` 把 `bits` 补全了
            # （"补全"那一半）；这一格是"拒"那一半：将来有人绕过补全、或者补全本身
            # 被改坏，落盘的就不再是空表，而是「整笔不写」—— 一条 `bits` 空的行
            # 比一条写坏的 evidence_kind 更坏：它让档位与等级同时变成"读不出来"，
            # 而 `bits_shape_problems({})` 返回的是 `[]`（空表 = 没有形状问题）。
            _bits_now = dict(getattr(row, "bits", None) or {})
            _bits_missing = [k for k in STATEMENT_BITS_KEYS
                             if k not in _bits_now or _bits_now[k] is None]
            if _bits_missing:
                raise ValueError(
                    "statements.bits 必须 10 键齐、且没有一格是 None；这一笔缺 "
                    f"{_bits_missing}（整表只有 {sorted(_bits_now)}）⇒ 整笔不写："
                    "落一条空 bits 的行，档位与等级就再也读不出来（现场 000019，"
                    "`data/events.jsonl:3671`）")
            if (row.origin == "own_result" and not str(body.get("quote_reason") or "").strip()
                    and body.get("quote_verified") is not True):
                # 读数：`quote_reason` 是秘书补的（B 只交两样，见 `_statement_from`）——
                # 补了必须看得见，否则"这一格为什么有值"在盘上无从分辨。
                out["quote_reason_filled"] = True
            try:
                requested_no = int(body.get("proof_no") or 0)
            except (TypeError, ValueError):
                requested_no = 0
            data = self._annotate_proposition(
                row.to_dict(), adj, proof_no=(requested_no if requested_no >= 1 else 1),
                route=route)
            # ---- C（2026-11-19 FIX186）：命题行同笔能指回它的稿 --------------------
            #
            # 改前 `manuscript_id` / `manuscripts` 只在"往在册那一行追加证明"
            # （`_attach_proofs`）那一笔写；新建那一笔（尤其 E 的 `e-num-*` 数值稿）
            # 一个字节都不写 ⇒ 稿↔命题的对应关系断了：`manuscriptretire` 三源都反查
            # 不到，放弃那条命题之后它的稿仍被 `lifecycle.state_of_manuscript` 读成
            # 活跃（lp-ball-11 的 stmt:000006 ↔ reports/e-num-000008.md 就是这一形态）。
            # 路径号是这一笔刚分配的（`_new_path_no`，唯一来源），稿号由稿路径现认
            # （`vsigns.manuscript_id_of`，与签块 / 收录回执同一口径）。
            # 概念 / 定义行只写 `manuscript_id`，不写逐路径那一格：那一格是"每条证明
            # 路径各一份稿"，概念没有证明路径 —— 给它写一格会让 `_path_groups_of`
            # 读成"这一条该有第 1 条路径"，非平凡度那一栏就多出一条永远没判的路径。
            #
            # ---- 2026-11-19（SEC1 回归修复）：有收录回执的那一笔不预写回执的格 ----
            #
            # `_attach_proofs` 那一笔的 `write_proof_receipt`（`agent_b/proof_receipt.py`）
            # 写的是同样这几格，而且它经 `land_statement` 的
            # `STATEMENT_LAND_OPS["attach_proofs"]` 白名单差分落盘（越界 ⇒
            # `statement_patch_key_not_allowed`，整笔不写）。新建这一臂若先把同样的
            # 值写进行里，白名单差分就看不见这一格：值已经在盘上、Δ 为空 ⇒ 那一笔
            # 再也不会拒，闸退化成摆设。2026-11-19 的现场就是这样：把
            # `manuscripts` 从白名单里拿掉，`register_statement` 仍回 `ok=True`
            # （`tests/test_manuscripts_are_per_path.py::test_e_the_write_whitelist_is_what_lets_the_per_path_record_land`）。
            #
            # 所以这一臂只补"没有回执可写"的那一档：E 的 `e-num-*` 数值稿没有证明
            # 正文 ⇒ `write_proof_receipt` 不进来（它的 `_body_present` 恒假），
            # FIX186 要的"命题行同笔指回它的稿"只能由这里写。有正文的一档把这几格
            # 留给回执 —— 值与改前逐字相同，只是写口回到那张白名单后面。
            _receipt_will_write = bool(
                str(data.get("proof_text") or "").strip()
                or list(data.get(VR.PROOFS_KEY) or []))
            _rel_ms = str(body.get("manuscript_path") or "").strip().replace("\\", "/")
            # ---- 2026-11-20（WIRE1）：别条命题已经收进那一行的稿，这一笔不许认领 ------
            #
            # 现场（`tests/test_dependency_wiring_is_live.py::test_..._v_sign`，全量快照
            # 里最后一条红）：B 收录一笔"研究手稿引用了 F 的证明手稿"的新命题，正文留待
            # V 签过之后再交（2026-11-02 准入闸的三步次序：先落行与依赖面、V 签那份
            # 正文、B 再交正文）。这一笔选的稿是 D 携带过来的 F 稿 —— 那是 stmt:000002
            # 的稿。上面这一臂把它写进新行 ⇒ 新行声称"我的稿是 000000"，而它这时还没有
            # 自己的正文；V 的在册闸（`agent_v/core.py::_decide_registered_manuscript_identity`，
            # 2026-11-05「签不许盖错对象」那张判据）只认行上那一格与逐路径记录 ⇒ V 签不了
            # 这条命题自己那份稿（`bad_manuscript_name`），而那份稿本来要等到第 ③ 步
            # 收录回执才记到这一行上（`_attach_proofs` 的 `write_proof_receipt`）。
            #
            # 判据是「这一份稿是不是已经被别条命题收进它那一行」（`manuscriptretire.
            # statement_of_manuscript` 的收录两源；不读签行 —— 问的是"收进了哪一行"，
            # 不是"谁签过它"）：已被别条命题认领 ⇒ 这一笔不写，把这两格留给第 ③ 步。
            # 一份稿只能属于一条命题，这条 1:1 是 `statement_of_manuscript` 自己写在
            # 读数里的（"同时被 N 条命题指向 —— 1:1 的判据被破了"）；这一臂造出的正是
            # 那个形态，于是反过来把 V 的认稿闸顶死。
            #
            # 稿名那条查询是族安全的（路径带前缀）；稿号那条不是（裸号跨族会撞，K6②
            # 因此把稿身份定成 `(族, 稿号)`）⇒ 同号不同族时宁可不认领：代价只是这一
            # 行暂时没有回指那一格（FIX186 的原始缺口，第 ③ 步的收录回执仍会写），反过
            # 来写错一格却会让那条命题永远签不下去。
            #
            # 三态：`checked=False`（台账读不出来）也不写 —— 「判不了这一份是不是
            # 别条的稿」不等于「可以认领」。两种情况都进 `out["manuscript_link"]` 的读数，
            # 不静默（`written` 是这一格写没写，`why` 是没写的原因）。
            from . import manuscriptids as _MID_FAM
            from . import vsigns as _VS_MS

            _mid_ms = str(_VS_MS.manuscript_id_of(_rel_ms) or "")
            _link: dict = {"written": False, "checked": False, "claimed_by": "",
                           "manuscript": _rel_ms, "why": ""}
            if _rel_ms and not _receipt_will_write:
                from . import manuscriptretire as _MR_MS

                _owner = dict(_MR_MS.statement_of_manuscript(
                    self.store, rel=_rel_ms, manuscript_id=_mid_ms,
                    sign_rows=False) or {})
                _holder = str(_owner.get("stmt_id") or "")
                _link["checked"] = bool(_owner.get("checked"))
                if not _owner.get("checked"):
                    _link["why"] = (f"这一份稿的归属没查成（{_owner.get('why') or '没有读数'}）"
                                    " ⇒ 不认领：判不了它是不是别条命题的稿")
                elif bool(_owner.get("found")) and _holder != str(stmt_id):
                    _link["claimed_by"] = _holder
                    _link["why"] = (f"`{_rel_ms}`（稿号 {_mid_ms or '认不出'}）已经收进 "
                                    f"stmt:{_holder} 那一行 ⇒ 这一笔不认领它（一份稿只能"
                                    "属于一条命题；这一条的稿等收录回执写）")
                else:
                    if not _is_not_applicable_kind(kind):
                        data["manuscripts"] = {str(int(_new_path_no)): _rel_ms}
                    if _mid_ms:
                        data["manuscript_id"] = _mid_ms
                        _fam_ms = _MID_FAM.family_of_rel(_rel_ms)
                        if _fam_ms:
                            data["manuscript_family"] = _fam_ms
                        _link["written"] = True
            if _rel_ms:
                out["manuscript_link"] = _link
            # ---- 交付说这一份是 #pN（N>1）⇒ 它进 `proofs` 清单，不进 canonical ----
            #
            # 2026-11-04（缺口 ①）：新建那一支同样要认交付里的号。canonical（`proof_text`）
            # 只放 #p1；把第 2 份写进那一格会让 `verifications.proof_list` 读出两条 #p1
            # （一条正文、一条空），而依赖的 `used_by`、V 的逐份签、论文对应表全按号走。
            # 五元位由 B 现算并随载荷交来，逐份表已经按这个号记（`reviewed_by_proof`），
            # 这里只搬正文、不改位。
            if requested_no > 1 and str(data.get("proof_text") or "").strip():
                text_now = str(data.get("proof_text") or "")
                data["proof_text"] = ""
                listed_now = [dict(p) if isinstance(p, Mapping) else p
                              for p in (data.get(VR.PROOFS_KEY) or [])]
                listed_now.append({"proof_no": int(requested_no),
                                   "proof_text": text_now,
                                   "created_at": S.now_iso()})
                data[VR.PROOFS_KEY] = listed_now
            # ---- 167/作者（业主 2026-11-01 裁定）：登记的那一刻把"谁写的"记下来。
            #
            # 为什么必须在这里：V 回执的收件人 = 送审者（召唤 V 的那个 task），而
            # "送审者该不该是这个人"只能拿"作者是谁"来判（业主：「F 写的证明，F 送审
            # ……B 侧收录」「不存在 F 写证明 B 送审」）。盘上此前没有这一格，81 的 8 条
            # 回执只能记成 `author_not_recorded`（`proofauthors.statement_author_of`）。
            #
            # 只加数据：不改 `bits`、不改收录行为、不改 `created_by`（那是登记口）。
            # 读不出来源 ⇒ 不写这一格（`author_not_recorded`），不许默认成 B。
            from . import proofauthors as _PAA

            author = _PAA.author_reading(body=body, root=self.root)
            if author.get("author"):
                data["proof_authors"] = _PAA.recorded(author)
            out["author_reading"] = dict(author)
            tx.upsert("statements", data, note="record_statement")
            if kind == "concept" and legacy.get("present"):
                # 交来的就是一条概念（`kind="concept"`）⇒ 它自己那一行也要镜像：
                # 漏掉这一支，B 用"整条交一条概念"的写法时老读侧就看不见它
                # （而盘上看起来一切正常 —— 这正是"两处同号"最容易漏的一格）。
                mirror = S.Concept(
                    concept_id=stmt_id, name=str(body.get("label") or ""),
                    definition=full, related_concepts=[],
                    normalized_name=T.normalize(str(body.get("label") or "")),
                    aliases=[str(a) for a in (body.get("aliases") or []) if str(a).strip()],
                    definition_source_lit_id=str(body.get("source_lit_id") or "") or None,
                    created_at=S.now_iso(), updated_at=S.now_iso())
                mirror.validate()
                tx.upsert(CR.LEGACY_TABLE, mirror.to_dict(), note="record_statement:mirror")
            written = ["statements"]
            pending_concepts = 0
            # ---- 概念的三道闸（2026-10-21，本批缺陷一） -------------------------
            # ① 概念行不带证明文本（`proof_text` 是"这段证明被审过"的比对对象，
            #    概念不参与等级链）⇒ 载荷里带了也不写，并且留痕（静默丢是另一种坏）；
            # ② `origin` 口径：有出处 ⇒ external_lit；没有 ⇒ 自己定义的概念；
            #    显式写 own_result 必须带 self_authored（判据在 conceptrows）；
            # ③ 每轮上限（`conceptrows.CONCEPTS_PER_ROUND_MAX`）：超出的受控拒绝、
            #    读数可见、已写的保留。
            quota = CR.ConceptQuota()
            dropped_proof: list[str] = []
            refused_concepts: list[dict] = []
            identity_actions: list[dict] = []
            for c in concepts:
                name = str(c.get("name") or "")
                if str(c.get("proof_text") or "").strip():
                    dropped_proof.append(name)
                src_lit = str(c.get("source_lit_id") or body.get("source_lit_id") or "")
                origin = str(c.get("origin") or "")
                self_authored = bool(c.get("self_authored"))
                resolved_origin = CR.resolve_concept_origin(
                    origin=origin, source_lit_id=src_lit, self_authored=self_authored)
                problem = CR.concept_origin_problem(
                    origin=resolved_origin, source_lit_id=src_lit,
                    self_authored=(self_authored
                                   or (resolved_origin == "own_result"
                                       and not str(origin or "").strip())))
                if problem:
                    refused_concepts.append({"name": name, "why": problem,
                                             "concept_action": "refused"})
                    continue
                # ---- 同一性闸（发号之前）：`write_concept_row` 收紧之后，先发号再判
                # same / 判不了都会留下"号已发、行没建"的空洞（`verify` 的 `id_gap`）。
                # 处置口径与四个入口同一处（`concept_identity_action` 唯一折算点）。
                gate = concept_identity_gate(
                    tx, label=name, full=str(c.get("definition") or ""))
                act = concept_identity_action(gate)
                if act["concept_action"] == "refused":
                    refused_concepts.append({
                        "name": name, "why": str(act.get("reason") or ""),
                        "concept_action": "refused", "checked": False, "state": "",
                        "same_as": "", "reason": str(act.get("reason") or "")})
                    continue
                if act["concept_action"] == "merged":
                    identity_actions.append({
                        "name": name, "concept_action": "merged",
                        "same_as": str(act.get("same_as") or ""), "checked": True,
                        "state": "same",
                        "candidates": [str(x) for x in (act.get("candidates") or [])],
                        "reason": str(act.get("reason") or "")})
                    continue
                if not quota.admit(name):
                    refused_concepts.append({"name": name, "why": quota.reading()["why"],
                                             "concept_action": "refused"})
                    continue
                # 与上面同一口径：老表还在的时候号空间的权威是 `concept`（两张表要同号，
                # 而各自发号会让两边的号不连续 —— `verify` 的 `id_gap` 会报出来）
                cid = tx.alloc_id(concept_kind)
                # 过渡期两处同号 + 老表镜像（`conceptrows` 的契约 1）：走同一处写口。
                # `proof_text` 刻意不转发：概念行不许带它（见上面①）。
                crow_data = CR.write_concept(
                    tx, stmt_id=cid, label=name,
                    definition=str(c.get("definition") or ""),
                    aliases=c.get("aliases") or (),
                    source_lit_id=src_lit,
                    doc_id=str(body.get("doc_id") or ""), actor=f"secretary-{self.role}",
                    origin=resolved_origin,
                    self_authored=(self_authored
                                   or (resolved_origin == "own_result"
                                       and not str(origin or "").strip())),
                    # 概念行也要"定义在第几页"这一格：这一支的页码由调用方随
                    # 这一条概念一起交（`concepts[].page_range`）；不交就是
                    # 不知道，读侧会逐条点名。
                    page_range=c.get("page_range"),
                    mirror=bool(legacy.get("present")))
                identity_actions.append({
                    "name": name, "concept_action": "created",
                    "concept_id": cid, "same_as": "", "checked": True,
                    "state": str(act.get("state") or "different"), "candidates": [],
                    "reason": str(act.get("reason") or "")})
                if str(crow_data.get("status") or "") == "pending_definition":
                    pending_concepts += 1
            if dropped_proof:
                out["concept_proof_text_dropped"] = dropped_proof[:20]
            if refused_concepts:
                out["concepts_refused"] = refused_concepts[:20]
            if identity_actions:
                out["concepts_identity"] = identity_actions[:20]
            out["concept_quota"] = quota.reading()
            # 这一笔的路径号是秘书刚分配的（见上）：依赖的 `used_by` 尾巴与
            # `path_group` 都从它来 —— 产出侧不再写号，这一段是那个号唯一的落点。
            steps = _stamp_path_number(steps, path_group=_new_path_no,
                                       proof_no=_new_path_no,
                                       single_group=len(groups) <= 1)
            dep_count = self._write_dep_steps(tx, steps, stmt_id=stmt_id, body=body)
            written.append("dependencies")
            #: 依赖面到底建起来没有：带证明正文而一条依赖都没落 ⇒ 这一格说 `missing`
            #: （改前只有返回值里的 `deps_written=0`，而没有任何一格问过这件事 ——
            #: 真机 sylow3 七条命题、依赖全表 0 行，就是这样静默过去的）。
            out["deps_missing"] = _deps_missing_reading(
                proof_text=body.get("proof_text") or "", deps_written=dep_count,
                derived_from=body.get("derived_from") or (), stmt_id=stmt_id,
                # 这一行刚落成的那一份证明号：交付里给了号就是它（缺口 ①；canonical
                # 只有在没给号 / 给 1 时才是 #p1）。改前这里写死 1 ⇒ 第 2 份的依赖读数
                # 也记在 #p1 上（`used_by` 与证明号分家，读的人看不出错位）。
                proof_no=(requested_no if requested_no >= 1 else 1), scan=scan)
        out.update(checked=True, created=True, duplicate=False, stmt_id=stmt_id,
                   row=data, tables=written, deps_written=len(steps),
                   #: 其中"命题→命题"几条（2026-11-05 缺陷 1c：两个数分开读）。
                   deps_stmt_edges=_stmt_edge_count(steps),
                   path_groups=len(groups), pending_concepts=pending_concepts,
                   # 新建那一行的证明号：交付给了号就是它，没给才是 canonical（#p1）。
                   # 这一格不许留 0 —— 回执说 0，调用方就会去"修"它。
                   proof_no=(requested_no if requested_no >= 1 else 1),
                   proof_no_source=str(body.get("proof_no_source") or ""))
        if _is_not_applicable_kind(kind):
            # 概念/定义行的档位读数：不适用（没有证明正文）。落在这里而不是上面的
            # `judge_statement` 那一格，是因为这一支的命题正文通过了查重与同一性判定
            # （`kind="concept"` 的那一条走 `_merge_into_concept`，零模型调用），
            # 走的不是 `judge_statement` 那条路；两处落的是同一句话，
            # 唯一的口径在 `not_applicable_nontriviality`。
            out["nontriviality"] = self.not_applicable_nontriviality(
                statement_full=full, kind=kind, stmt_id=stmt_id)
        return out
