# -*- coding: utf-8 -*-
"""秘书的概念行（一个概念一行，从 secretary.py 的 U24 逐字搬出）。

我保证哪条不变式：一个概念一行；先判后发号（判不了就不发号，而不是发完号再留一个 id_gap）。

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
from . import schema as S
from pathlib import Path

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    STATEMENT_WRITE_TABLES,
    _is_concept_kind,
)

from .secretary_label import (  # noqa: F401 — 这些名字由 secretary_label 定义
    wash_working_name,
)

from .secretary_port import (  # noqa: F401 — 这些名字由 secretary_port 定义
    new_secretary,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    CONCEPT_IDENTITY_UNJUDGED,
)


class ConceptMixin:
    """概念行（一个概念一行）（从 secretary.py 搬出的混入类）。"""

    def _record_pending_concept(self, body: dict[str, Any], *,
                                out: dict[str, Any]) -> dict[str, Any]:
        """交来的就是一条还没抽到定义的概念 ⇒ 落成 `pending_definition`（D12 甲）。

        与 `_record_statement_tx` 分开的理由：那一条路要求 `statement_full` 非空
        （命题没有"内容待补"这一档），而概念有 —— 混在一处会把"命题缺假设"
        与"概念缺定义"折成同一件事（前者该拒，后者该落）。

        ## 同一性判词在这里也要处置（2026-11-08）
        `concept_identity_gate` 在发号之前判，`concept_identity_action` 折成三档：

        - 判得 `same` ⇒ 并入那一条（不新建、不发号），读数 `concept_action="merged"`；
        - 判不了 ⇒ 这是 `D12` 甲 豁免的那一档（它豁免的正是"定义还没抽到"）：照落成
          `pending_definition`，但读数必须写明 `checked=False` / `d12_pending=True` 与原因
          —— 待补不是依据，也不是"可以落两行"；
        - `different` ⇒ 照常发号新建。

        `D12` 甲的边界写在这里：它豁免的是"定义还没抽到"这件事，不豁免"判得 same"。
        两条待补概念只差一个空格时闸看不到对手（`_same_concept_candidate` 跳过
        `pending_definition`），所以这一入口按同一把定义项键（`propositionkey.concept_keys`
        的标签那一半）把待补行也看一遍 —— 判据仍是那一处，不另写一份。

        拒绝（空标签 / 出处分档）都发生在 `alloc_id` 之前 ⇒ counters 不动、不留 `id_gap`。
        """
        from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口
        from . import textutil as T       # 惰性：查重键的唯一实现

        name = str(body.get("label") or "")
        if not name.strip():
            out.update(refused="empty_statement", concept_action="refused",
                       concept_identity={"checked": False, "state": "", "basis": "",
                                         "same_as": "", "candidates": [],
                                         "reason": "一条概念至少要有 label（名字）"},
                       reason="一条概念至少要有 label（名字）—— 没有名字的行谁也认不出它")
            return out
        legacy = CR.legacy_present(self.store)
        tables = list(STATEMENT_WRITE_TABLES) + ([CR.LEGACY_TABLE] if legacy.get("present") else [])
        with self.store.tx(*tables, actor=f"secretary-{self.role}",
                           note="record_statement:concept_pending") as tx:
            gate = concept_identity_gate(tx, label=name)
            act = concept_identity_action(gate)
            # 查重：先按规范化标签（既有口径，通用词也认），再按同一把定义项键把待补行
            # 也看一遍（闸跳过它们 —— 见 docstring 的 D12 甲 边界）。
            key = T.normalize(name)
            dup = next((r for r in tx.rows("statements")
                        if str(r.get("kind") or "") == "concept"
                        and T.normalize(str(r.get("label") or "")) == key), None)
            if dup is None:
                label_key = _PK.concept_keys(name, "")["label"]
                if label_key:
                    dup = next((r for r in tx.rows("statements")
                                if str(r.get("kind") or "") == "concept"
                                and _PK.concept_keys(str(r.get("label") or ""),
                                                     str(r.get("statement_full") or "")
                                                     )["label"] == label_key), None)
            if dup is not None:
                merged_id = str(dup.get("stmt_id") or "")
                if str(act.get("concept_action") or "") == "merged":
                    reading = dict(act)
                else:
                    reading = {"checked": True, "state": "same",
                               "basis": _PK.BASIS_CONCEPT_LABEL,
                               "same_as": merged_id, "candidates": [merged_id],
                               "reason": ("待补行不是同一性闸的合并落点（`pending_definition` "
                                          "不在可比行里）⇒ 这一入口按同一把定义项键补看一次："
                                          "标签规范化后相同（同一个概念）")}
                reading["concept_action"] = "merged"
                out.update(checked=True, created=False, duplicate=True, stmt_id=merged_id,
                           same_as=merged_id, concept_action="merged",
                           concept_identity=reading,
                           reason=(f"同一个概念已在册（stmt:{merged_id}）⇒ 并入那一行："
                                   "不新建第二行、不发号（判据："
                                   f"{str(reading.get('reason') or '').strip()}）"))
                return out
            # `origin` 按来源分档（本批缺陷一的第二处）：交来的概念有出处 ⇒ external_lit；
            # 没有出处 ⇒ 我们自己定义的新概念（own_result，推断，不要求调用方另声明）。
            # 这一判放在发号之前：拒的时候 counters 不动、不留 `id_gap`。
            src_lit = str(body.get("source_lit_id") or "")
            concept_origin = CR.resolve_concept_origin(source_lit_id=src_lit)
            problem = CR.concept_origin_problem(origin=concept_origin,
                                                source_lit_id=src_lit,
                                                self_authored=(concept_origin == "own_result"))
            if problem:
                out.update(checked=False, created=False, refused="concept_origin_refused",
                           concept_action="refused", reason=problem)
                return out
            # 过渡期的号空间只有一个权威：老表还在的时候就是 `concept`（B 的 pipeline
            # 从那儿发号），迁移之后才是 `stmt` —— 两边各发各的会让同一张表出现
            # `id_gap`（分配了号却没建行），而两张表还要同号。
            concept_kind = (S.TABLES[CR.LEGACY_TABLE]["id_kind"] if legacy.get("present")
                            else S.TABLES["statements"]["id_kind"])
            cid = tx.alloc_id(concept_kind)
            # 过渡期两处同号（`conceptrows` 的契约 1）：老表那份镜像沿用这个号。
            # `d12_pending=True` 是这一条 D12 甲 入口的身份（全仓只有这一处传）：
            # 判不了时照落成 pending_definition，别的普通调用不许走这条豁免。
            data = self.write_concept_row(tx, stmt_id=cid, label=name, definition="",
                                          aliases=body.get("aliases") or [],
                                          source_lit_id=src_lit,
                                          doc_id=str(body.get("doc_id") or ""),
                                          origin=concept_origin,
                                          self_authored=(concept_origin == "own_result"),
                                          mirror=bool(legacy.get("present")), out=out,
                                          d12_pending=True)
        d12 = bool(out.get("d12_pending"))
        out.update(checked=True, created=True, stmt_id=cid, row=data,
                   tables=tables, mirrored=bool(legacy.get("present")), pending_concepts=1,
                   concept_action="created",
                   nontriviality_not_applicable=True,
                   reason=("概念行已落成 pending_definition（定义待补）—— 它不是依据；"
                           "概念行不带 `proof_text`（概念不参与等级链，"
                           "要补的是定义，不是证明）"
                           + ("；同一性闸判不了（D12 甲 豁免的正是'定义还没抽到'这个前提）"
                              "⇒ 照落，但这一档不是'同一个概念可以落两行'"
                              if d12 else "")))
        return out

    def _concept_bits(self, *, origin: str, source_lit_id: str = "",
                      proof_text: str = "",
                      sign: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """概念行的五元位（唯一实现：`conceptrows.concept_bits`）。

        为什么概念行也要算这一格：见 `conceptrows.concept_bits` 的 docstring（空 `bits`
        不是"没有证据"，是"没有人替它算过"）—— 这一层只转调，不抄第二份理由。

        2026-11-10（业主裁定 甲）起这一格多了「良定义证明」一档：`proof_text` 有正文且
        `sign.state == "signed"`（`vsigns.sign_reading` 的结论）⇒ 第 2/3 位按同一套
        读数翻；等级仍是 `not_applicable`（概念没有等级轴，短路不改）。口径只有一处
        （`conceptrows.concept_bits`），这一层不抄第二份。
        """
        from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口

        return CR.concept_bits(origin=origin, source_lit_id=source_lit_id,
                               proof_text=proof_text, sign=sign)

    def _concept_row_payload(self, *, existing: Mapping[str, Any] | None,
                             sid: str, name: str, full: str,
                             alias_list: list[str], lit: str, doc_id: str,
                             origin: str, self_authored: bool,
                             proof_text: str) -> tuple[dict[str, Any], str]:
        """这一笔要写进 `statements` 的那份行数据，以及它的来路（`create` / `sync`）。

        `existing is None` = 新建：良定义证明这一格只在 V 签回来时保留正文（判据是既有
        唯一读口 `vsigns.sign_reading`，这里不新写一套），五元位随之现算。给了
        `existing` = 过渡同步改那一行：只改"从老表推得出来的那几格"，新标准独有的
        `proof_text` / `doc_id` / `created_at` / 已算好的 `bits` 一格不覆盖（老行里
        根本没有它们；已有的五元位也不整份重算 —— 签名那一族的凭据会被同步抹掉）。
        """
        from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口

        if existing is None:
            sign: dict[str, Any] = {}
            if str(proof_text or "").strip():
                from . import vsigns as _VS
                sign = dict(_VS.sign_reading(
                    (getattr(self.store, "root", "") or ""), statement_id=sid,
                    proof_text=str(proof_text), proof_no=1, store=self.store))
            data = CR.concept_statement(stmt_id=sid, label=name, definition=full,
                                        aliases=alias_list, source_lit_id=lit,
                                        doc_id=doc_id, actor=f"secretary-{self.role}",
                                        origin=origin, self_authored=self_authored,
                                        # 概念行不新写第二份判据：有没有签由上面那一读
                                        # 决定，构造口只按 `sign.state` 留 / 清。
                                        proof_text=proof_text, sign=sign
                                        ).to_dict()
            data["bits"] = self._concept_bits(
                origin=str(data.get("origin") or ""), source_lit_id=lit,
                proof_text=str(data.get("proof_text") or ""), sign=sign)
            return data, "create"
        data = dict(existing)
        # 只改"从老表推得出来的那几格"：新标准独有的 `proof_text` / `doc_id` /
        # `created_at` / 已算好的 `bits` 一格不覆盖（老行里根本没有它们）。
        data["label"] = name
        data["statement_text"] = full
        data["statement_full"] = full
        data["aliases"] = alias_list
        data["source_lit_id"] = lit or None
        if not dict(data.get("bits") or {}):
            # 老行本来没有五元位（这次才是它第一次经秘书的手）⇒ 补上一份；
            # 已经有了的那一份不整份重算（签名那一族的凭据会被同步抹掉）。
            _body = str(data.get("proof_text") or "")
            _sign: dict[str, Any] = {}
            if _body.strip():
                from . import vsigns as _VS
                _sign = dict(_VS.sign_reading(
                    (getattr(self.store, "root", "") or ""), statement_id=sid,
                    proof_text=_body, proof_no=1, store=self.store))
            data["bits"] = self._concept_bits(
                origin=str(data.get("origin") or ""), source_lit_id=lit,
                proof_text=_body, sign=_sign)
        return data, "sync"

    def write_concept_row(self, tx: Any, *, stmt_id: str, label: str,
                          definition: str = "", aliases: Iterable[str] = (),
                          source_lit_id: str = "", doc_id: str = "",
                          origin: str = "", self_authored: bool = False,
                          mirror: bool = False,
                          existing: Mapping[str, Any] | None = None,
                          status: str = "", quote_reason: str = "",
                          proof_text: str = "",
                          out: dict[str, Any] | None = None,
                          transition_sync: bool = False,
                          d12_pending: bool = False) -> dict[str, Any]:
        """在已开的事务里写一条概念行：洗名 + 五元位 + 概念同一性都在这一处做。

        ## 为什么不是调 `record_statement`

        `record_statement` 自己开事务，而概念行的写侧全都在一笔已经打开的事务里
        （`_record_pending_concept` / `conceptrows.write_concept` / `sync_from_legacy`）——
        事务不能嵌套（文件锁不可重入）。而且 `record_statement` 会先跑一次命题同一性判定
        （可能发模型调用），而"锁里不许有网络等待"是本仓的硬规矩；概念这一档也不发调用。
        所以这里是"同一个写入方、同一套判据、不开新事务"的那一格：两个过渡写口都调它，
        读侧与写侧的判据因此只有一份。

        ## 三件事在这里做

        1. 五元位：`_concept_bits` 现算（概念行算出来的等级是 `not_applicable`）；
           概念行不直写 `bits`，否则"五位一位都没做"的读数会对整批旧行全部成立；
        2. 洗名：`wash_working_name`（零模型调用）；洗过就把 `from`/`to`/`why` 放进
           `out["label_washed"]` —— 静默改名是不许的；
        3. 概念同一性：`_same_concept_candidate`（`propositionkey.same_concept` 的唯一调用点），
           判词进 `out["concept_identity"]`。

        ## 判到"同一个概念"时按 `concept_identity_action` 折算

        - `merged`（新建 + same + 有候选）⇒ 不写这一行，返回并入读数（`stmt_id` 即并入对象）。
          调用方给的号必须是在过闸之前没发过的 —— 这一档是最后一道网，不是发号点；
        - `refused`（判不了）⇒ 新建那一支不写、返回受控拒，拒信给改法（把定义项写出来）。
          例外：`d12_pending=True`（定义还没抽到的概念行的唯一入口）照落成
          `pending_definition`，读数里写明这个前提；
        - `created`（different / 候选 0 条）⇒ 照常写。

        改一条既有行（`existing` 给了）不新建也不并入：它本身就是那一行，读数只报
        `checked` / `state` / `same_as` / `reason`。

        `transition_sync=True` 只给 `conceptrows.sync_from_legacy`（一号一行的过渡同步，
        合并不在这一层做）；`d12_pending=True` 只给 `_record_pending_concept`。
        别的调用点传这两个中的任何一个 ⇒ 机械判据当场红。

        升档（`pending_definition` 回 `active`）与合并（老表墓碑 ⇒ `superseded` + 理由）
        都由调用方算好 `status` / `quote_reason` 再进来。
        """
        from . import conceptrows as CR   # 惰性：并表过渡层的唯一读写口
        from . import textutil as T       # 惰性：查重键的唯一实现

        sid = str(stmt_id or "")
        name = str(label or "")
        full = str(definition or "")
        alias_list = [str(a) for a in (aliases or ()) if str(a).strip()]
        lit = str(source_lit_id or "")
        # ---- 洗名（D1 的唯一实现；没命中就一个字节都不动）
        working = wash_working_name(name, statement_full=full, kind="concept", stmt_id=sid)
        if working:
            name = str(working["to"])
            if out is not None:
                out["canonical_name"] = name
                out["label_washed"] = dict(working, stmt_id=sid)
        data, creator = self._concept_row_payload(
            existing=existing, sid=sid, name=name, full=full,
            alias_list=alias_list, lit=lit, doc_id=doc_id, origin=origin,
            self_authored=self_authored, proof_text=proof_text)
        if str(status or "").strip():
            data["status"] = str(status)
        if str(quote_reason or "").strip():
            data["quote_reason"] = str(quote_reason)
        # 概念行的「良定义证明」读数（三态 + 来源）：写进来的这一笔与读回去的那一格
        # 用同一份实现（`conceptrows.well_definedness_reading`）。
        if out is not None:
            out["well_definedness"] = CR.well_definedness_reading(
                (getattr(self.store, "root", "") or ""), data, store=self.store)
        # ---- 概念同一性（唯一判据；改一条既有行时把自己排除在命中之外）
        identity = self._same_concept_candidate(tx, label=name, full=full, exclude_id=sid)
        hit = dict(identity.get("hit") or {})
        act = concept_identity_action(identity)
        #: 这一笔的最终处置：D12 甲（`_record_pending_concept`，按调用方身份传入
        #: `d12_pending=True`）把 refused 折成"照落"，其余按折算点的三档；
        #: 改既有行没有"新行"可谈，不写这一格。
        pending_exempt = (act["concept_action"] == "refused"
                          and existing is None and bool(d12_pending))
        final_action = "created" if pending_exempt else act["concept_action"]
        if out is not None:
            out["concept_identity"] = {
                "checked": bool(identity.get("checked")),
                "state": str(identity.get("state") or ""),
                "basis": str(identity.get("basis") or ""),
                "same_as": str(hit.get("stmt_id") or ""),
                "candidates": [str(x) for x in (identity.get("candidates") or [])],
                "reason": str(identity.get("reason") or ""),
            }
            if existing is None:
                out["concept_identity"]["concept_action"] = final_action
                out["concept_action"] = final_action
                out["d12_pending"] = pending_exempt
        elif hit:
            # 判到"同一个概念"而调用方没要读数（`conceptrows` 那三个写口就是这样）⇒
            # 落到秘书自己的台账上：这一笔判过、判的是哪一行必须在盘上留得住，
            # 否则这一层判了等于没判（改前连判据都没有，见 `_concept_secretary`）。
            try:
                self.note_decision(
                    duty=2, decision="concept_duplicate",
                    reason=str(identity.get("reason") or ""),
                    basis=[str(identity.get("basis") or "")],
                    target={"concept": sid, "same_as": str(hit.get("stmt_id") or "")},
                    fail_open=False)
            except Exception as exc:  # noqa: BLE001 —— 留痕失败不带走这一笔写
                self._log(f"概念同一性留痕没写成：{type(exc).__name__}: {exc}")
        # ---- 处置（默认强制；只有过渡同步那一条路只报不处置）
        if not transition_sync and existing is None:
            if act["concept_action"] == "refused" and not pending_exempt:
                why = str(identity.get("reason") or "")
                return {"concept_action": "refused", "checked": False, "state": "",
                        "same_as": "", "candidates": list(act.get("candidates") or []),
                        "refused": CONCEPT_IDENTITY_UNJUDGED, "concept_identity": dict(act),
                        "reason": (why + " ⇒ 这一笔不写（不新建、不合并）。"
                                   "改法：把定义项写出来 —— 标签写成具体术语，或正文写成"
                                   "「概念（X）」/「定义（X）」；若它确实与在册某一条不同，"
                                   "把那个不同的定义项写出来再交")}
            if act["concept_action"] == "merged":
                target = str(act.get("same_as") or "")
                why = (f"同一个概念已在册（stmt:{target}；依据："
                       f"{self._basis_text(str(act.get('basis') or ''), 0.0)}）⇒ 并入那一行："
                       "不新建第二行、不发号")
                return {"stmt_id": target, "concept_action": "merged", "checked": True,
                        "state": "same", "same_as": target,
                        "candidates": list(act.get("candidates") or []),
                        "concept_identity": dict(act), "reason": why}
        obj = S.row_from_dict("statements", data)
        obj.validate()
        data = obj.to_dict()
        tx.upsert("statements", data, note=f"secretary:concept_{creator}")
        if mirror and CR.LEGACY_TABLE in S.TABLES:
            # 过渡期两处同号（`conceptrows` 的契约 1）：老表那份镜像沿用这个号。
            # 落刀之后那张表不存在 ⇒ 这里自己判（与 `tables_for_concept_write` 同一口径）。
            crow = S.Concept(
                concept_id=sid, name=name, definition=full, related_concepts=[],
                normalized_name=T.normalize(name), aliases=alias_list,
                definition_source_lit_id=lit or None,
                created_at=S.now_iso(), updated_at=S.now_iso())
            crow.validate()
            tx.upsert(CR.LEGACY_TABLE, crow.to_dict(), note="secretary:concept_mirror")
        CR.push_counters(tx, sid)   # 一个号空间、两个计数器（见 push_counters）
        # 概念/定义行的档位读数：不适用（没有证明正文）。不落这一格时，读侧会把
        # "没有记录"与"不需要记录"都印成同一个"未判"。
        # 两支都调（新建与同步）：那一格是幂等的（同一段正文只落一行），于是存量概念行
        # 会在它下一次经秘书那一笔时被补上，不需要一次全库迁移。
        # 判/落拆段（NT2）：这一笔已经拿到号（`sid`）⇒ 判与落同在这一处、`record=True`。
        self.judge_statement(statement_full=full, kind="concept", stmt_id=sid,
                             record=True)
        return data

    def _same_concept_candidate(self, tx: Any, *, label: str,
                                full: str, exclude_id: str = "") -> dict[str, Any]:
        """在册的概念行里找"同一个概念"：定义项相同就命中（确定性、零模型调用）。

        判据只有一处（`propositionkey.same_concept`：标签相同，或正文里被定义的那个
        术语相同）。本函数只做"在哪儿找、怎么选"这两件本层的事：

        - 只在概念行之间判（`CONCEPT_IDENTITY_KINDS`；命题那一套键与相似度对定义无效，
          反过来"标签相同"对命题也不是同一性判据）；
        - 跳过 `schema.STATEMENT_UNUSABLE_STATUSES` 里的行（被否证 / 被取代的概念不是
          合并的落点）；
        - 跳过 `exclude_id` 那一行（改一条既有的概念行时，它自己一定会命中自己 ——
          那一格问的是"另有一行是不是同一个概念"，把自己算进命中会把每次同步都读成
          发现了一条重复）；
        - 两侧都抽不出定义项的记成"没判成"（`checked=False`）：那不是命中，也不是"不同"，
          调用方据此受控拒（`concept_identity_unjudged`）；
        - 多条命中时取"标签那一档优先、同档取号最小"（确定性：同一次登记不能因为行的
          物理顺序不同而并进不同的一条）。

        返回 `{"hit": <命中|None>, "checked", "state", "basis", "reason", "candidates"}`：
        `hit` 是 `{"stmt_id", "row", "verdict"}`。没命中时两档分得开：
        `checked=True + state="different"`（判过了、不同 ⇒ 照旧新建）与
        `checked=False + state=""`（没判成 ⇒ 调用方受控拒，不许照旧新建）。
        """
        hits: list[dict[str, Any]] = []
        saw_different = False
        unknown_why: list[str] = []
        skip_id = str(exclude_id or "")
        for r in tx.rows("statements"):
            sid = str(r.get("stmt_id") or "")
            if not sid or not _is_concept_kind(r.get("kind")):
                continue
            if skip_id and sid == skip_id:
                continue
            if str(r.get("status") or "") in S.STATEMENT_UNUSABLE_STATUSES:
                continue
            other_label = str(r.get("label") or "")
            other_full = str(r.get("statement_full") or "")
            if not other_label.strip() and not other_full.strip():
                continue
            got = _PK.same_concept(label, full, other_label, other_full)
            state = str(got.get("state") or "")
            if state == _PK.STATE_SAME:
                hits.append({"stmt_id": sid, "row": dict(r), "verdict": got})
            elif state == _PK.STATE_DIFFERENT:
                saw_different = True
            else:
                unknown_why.append(sid)
        if hits:
            hits.sort(key=lambda h: (0 if str(h["verdict"].get("basis") or "")
                                     == _PK.BASIS_CONCEPT_LABEL else 1,
                                     str(h["stmt_id"])))
            top = hits[0]
            return {"hit": top, "checked": True, "state": _PK.STATE_SAME,
                    "basis": str(top["verdict"].get("basis") or ""),
                    "reason": str(top["verdict"].get("reason") or ""),
                    "candidates": [str(h["stmt_id"]) for h in hits]}
        if saw_different:
            return {"hit": None, "checked": True, "state": _PK.STATE_DIFFERENT, "basis": "",
                    "reason": ("在册的概念行里定义项都不一样 ⇒ 这是另一个概念，应当各建一行"
                               "（判据是定义项相同，不是词面相似）"),
                    "candidates": []}
        if unknown_why:
            keep = "；在册那几条抽不出定义项：" + "、".join(f"stmt:{sid}" for sid in unknown_why[:4])
            return {"hit": None, "checked": False, "state": "", "basis": "",
                    "reason": ("判不了 = 没判成：这一条或它在册的那几条抽不出定义项（标签是"
                               "空的，正文也不是一句「概念（X）」/「定义（X）」形态）⇒ 调用方"
                               "受控拒、不新建第二行（判不了不等于不同；这一档不发模型调用 ——"
                               "概念没有「条件 ⇒ 结论」，判词表里没有它那一格）。改法：把定义项"
                               "写出来 —— 标签写具体术语，或正文写成「概念（X）」/「定义（X）」；"
                               "若它确实与在册某一条不同，写出不同的定义项，判据会判 different "
                               "并照常新建" + keep),
                    "candidates": []}
        # 在册没有可比的概念行（0 条，或全被状态 / 排除项 / 空正文跳过）⇒ "没有同一个概念"
        # 是判得出来的：这是第一个概念，没有合并对象。不把它记成"判不了"——否则第一条
        # 概念永远登记不进来（fail-closed 会把整条路关死）。
        return {"hit": None, "checked": True, "state": _PK.STATE_DIFFERENT, "basis": "",
                "reason": ("在册没有可比的概念行（0 条 / 全被跳过）⇒ 这是第一个概念，"
                           "没有同一个概念可与它合并"),
                "candidates": []}

    def _merge_into_concept(self, tx: Any, *, body: Mapping[str, Any], full: str,
                            kind: str, out: dict[str, Any]) -> dict[str, Any] | None:
        """概念行那一档：同一个概念不许落成第二行（D2；真机 mp3-r2 的 000003 / 000004）。

        ## 为什么概念要有自己的一档
        命题那一档的判据是"条件 ⇒ 结论 一致"，而一条概念行只有一句定义 —— 它没有条件
        与结论，命题键与相似度在它上面等于失效（两条把同一个术语定义了两遍的行因此被判
        成"不同"）。真机读数：`000003` 与 `000004` 的 label 都是
        `finite-dimensional Lie algebra`，正文只差一句措辞。

        ## 判据与处置（确定性优先，模型不在这一档）
        判据是 `propositionkey.same_concept`（纯函数、零调用）：定义项相同 ⇒ 同一个概念。
        命中 ⇒ 不新建行，返回既有 `stmt_id`，读数里 `duplicate=True` +
        `matched_by="concept_label"/"concept_defined_term"`，并把依据那句原话写进
        `reason`（升档 / 补别名留给那一行，不在这一笔里静默改它的内容）。判过了、不同 ⇒
        `None`（调用方照常新建）；判不了 ⇒ 受控拒（`concept_identity_unjudged`）、整笔不写
        —— "判不了当不同"正是同一个概念落成两行的来路。

        ## 为什么这一档不发模型调用
        `adjudicate_proposition` 的判词表是"条件 ⇒ 结论"（`_judge_system` 的
        `proposition_identity` 那一格），概念没有这一组；把它交给模型既判不出什么，
        又会给真机上千条概念行各买一次调用（mp3 一个工作区就 1143 条）。确定性判得出的
        事不交给模型 —— 判不出的那一档受控拒（`concept_identity_unjudged`），
        不折成"不同"去新建第二行。
        """
        got = self._same_concept_candidate(tx, label=str(body.get("label") or ""), full=full)
        if not got.get("checked"):
            why = str(got.get("reason") or "")
            out.update(checked=False, created=False,
                       refused=CONCEPT_IDENTITY_UNJUDGED,
                       proposition_state="", proposition_reason=why,
                       reason=(why + " ⇒ 整笔不写（不新建、不合并）。"
                               "改法：把定义项写出来 —— 标签写成具体术语，或正文写成"
                               "「概念（X）」/「定义（X）」；若它确实与在册某一条不同，"
                               "把那个不同的定义项写出来再交"))
            return out
        out["proposition_state"] = str(got.get("state") or "")
        out["proposition_reason"] = str(got.get("reason") or "")
        hit = got.get("hit")
        if not hit:
            return None
        sid = str(hit.get("stmt_id") or "")
        out.update(checked=True, created=False, duplicate=True, stmt_id=sid,
                   matched_by=str(got.get("basis") or ""),
                   concept_candidates=list(got.get("candidates") or []),
                   reason=(f"同一个概念已在册（stmt:{sid}；依据："
                           f"{self._basis_text(str(got.get('basis') or ''), 0.0)}） ⇒ "
                           "不新建第二行，这一条就并到那一行上（同一概念升档 / 合并只落在"
                           "既有那一行，标签与定义都不在这一笔里静默改写）"))
        return out


def concept_identity_gate(tx: Any, *, label: str, full: str = "",
                          exclude_id: str = "") -> dict[str, Any]:
    """写一条新概念行之前先过这一闸（在发号之前调）：不写盘，只回判词。

    ## 为什么需要这一处（2026-11-08，D2 的后门）
    `Secretary.write_concept_row` 会算概念同一性，但它的调用方（`conceptrows.upsert` /
    `agent_b/run_once.resolve_concept`）在调用它之前就已经把号发出去了；于是"判不了
    就拒"落在那一层只会留下 `id_gap`（分配了 ID 但未建成行），而"放过"又等于概念轴
    有个后门。正确形状是"先判后分号"，而判据本体只该有一处 —— 这一格就是给调用方在
    `tx.alloc_id(...)` 之前调的那个口。

    ## 返回
    `{"checked", "state", "basis", "reason", "candidates"}`，与
    `Secretary._same_concept_candidate` 同源（唯一的 `same_concept` 调用点）：

    - `checked=True` + `state="same"`：在册已有同一个概念（`candidates` 点名）——
      调用方按 D2 并进那一行，不新建；
    - `checked=True` + `state="different"`：判过了、不同（含"在册 0 条可比行"）⇒
      照常发号新建；
    - `checked=False`：没判成 ⇒ 调用方受控拒（`concept_identity_unjudged`），
      一个号都不发。

    概念这一档是确定性判据、零模型调用，所以现造一名无缝秘书是对的（缝与本判据无关）。
    """
    store = getattr(tx, "_store", None)
    root = str(getattr(store, "root", "") or "")
    sec = new_secretary("B", root=Path(root) if root else Path("."), store=store,
                        seam=None, enable_model=False)
    got = sec._same_concept_candidate(tx, label=str(label or ""),
                                      full=str(full or ""),
                                      exclude_id=str(exclude_id or ""))
    return {key: got.get(key) for key in
            ("checked", "state", "basis", "reason", "candidates")}


def concept_identity_action(gate: Mapping[str, Any]) -> dict[str, Any]:
    """把同一性闸的判词折成唯一一档处置（四个写入口共用，2026-11-08）。

    ## 为什么要有这一格（改前四个入口各判各的、也各不处置）
    `concept_identity_gate` 只回判词（`checked` / `state` / `candidates` / `reason`），
    而"判成 same 该并入哪一行、判不了该不该拒"四个入口各写各的：`conceptrows.upsert`
    只读 `checked`、`_record_pending_concept` 完全不判、`run_once.resolve_concept` 只按
    名字找 —— 于是闸判出来的 `same` 在四个落点都被丢掉（真机 mp3-r2 的 000003 / 000004）。
    把"判词 ⇒ 处置"收成这一处，四个入口只读它的 `concept_action`。

    ## 三档（题面 2026-11-08 逐字）
    | 闸的判词 | `concept_action` | 处置 |
    |---|---|---|
    | `checked=False`（判不了） | `refused` | 受控拒、不发号（counters 不动） |
    | `checked=True` + `state="same"` + 有候选 | `merged` | 并入 `same_as` 那一条，不新建行、不发号 |
    | 其余（`different` / 候选 0 条） | `created` | 照常新建 |

    `state="same"` 却没有候选（判词不自洽）按 `created` 走：没有可并入的对象时
    新建是唯一可执行的处置 —— 但这一档不静默，`reason` 原样带出去。

    返回的字典同时是那四个入口的读数：`checked` / `state` / `basis` / `same_as` /
    `candidates` / `reason` 六格齐全（并入与新建读同一份，不另写一份读数）。
    """
    got = dict(gate or {})
    checked = bool(got.get("checked"))
    state = str(got.get("state") or "")
    candidates = [str(x) for x in (got.get("candidates") or []) if str(x)]
    basis = str(got.get("basis") or "")
    reason = str(got.get("reason") or "")
    if not checked:
        return {"concept_action": "refused", "checked": False, "state": "",
                "basis": basis, "same_as": "", "candidates": candidates,
                "reason": reason}
    if state == _PK.STATE_SAME and candidates:
        return {"concept_action": "merged", "checked": True, "state": state,
                "basis": basis, "same_as": candidates[0],
                "candidates": candidates, "reason": reason}
    return {"concept_action": "created", "checked": True,
            "state": state or _PK.STATE_DIFFERENT, "basis": basis, "same_as": "",
            "candidates": candidates, "reason": reason}
