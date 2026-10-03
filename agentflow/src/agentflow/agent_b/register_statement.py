"""角色 B 的动作 `register_statement`（`draft/37` §46）：把一条命题登记进命题台账。

## 为什么需要这个动作

§44.4 的真机读数把"审阅并 polish 一篇外部论文"这条链的堵点定在动作表上：
主控只能 `conductor.summon` 动作，而"把论文里的定理登记成 `statements` 行"原先只有
工具（`table.create`，A–D 都能调）—— `agent_b/` 里 `statements` 一个字都没有，
所以即使 A 把文集登记好了（§46 的另一个动作），命题台账仍然建不起来，
G 就没有可引的 `lit:`/命题依据，H 也没有可审的对象。

B 的边界里本来就写着"命题台账三件套缺一不可"（完整假设的正文 / 逐字证明摘录 / 出处），
这个动作就是那句话的执行面。

## 三个"必填"与它们各自防的是什么

1. `statement_full`（含完整假设的命题正文）：省掉假设的命题会被下游当成无条件成立
   —— 那是 FC-23 在命题级的同一种病；
2. `proof_text`（逐字摘录）：`quote_verified` 的比对对象就是它，没有它"引文回验"无从做起；
3. `source_lit_id`（`origin="external_lit"` 时）：出处必须真的存在 —— 本动作在写库前
 核一次 `literature` 表，引用一个不存在的 `lit_id` 直接拒（`kind="unknown_lit_id"`），
   与 `doc.build_document` 的 `check_citations` 同一条纪律：坏引用不许进库。

## 第四个必填：出处（按来源分档，`draft/37` §68）

`external_lit` 的命题要给非空的 `page_range`（`start` 或 `label` 至少一个）；
`own_result` 的命题要给 `doc_id` 或非空的 `line_range`（`start` / `label`）。
为什么不是"有这一栏就行"：第十三趟主控传的是 `{"start": null, "end": null}` ——
形状在场、内容是空的 —— 六条命题因此都落成了"看着有出处、其实没有"的行，
而审稿判据当场判它们缺页码，整条验收不及格。
为什么按来源分档（人裁的甲档）：从文献里摘的命题才有"第几页"这件事，
自有结果的出处是 `doc_id`/`line_range` —— 对后者要页码等于让它编一个数字。
写入口与 `reviewaccept._c_statements` 逐条对齐。

`quote_verified` 是三态：`True` 逐字通过 / `False` 比对不一致 / `None` 还没查。
只要不是 `True` 就必须给 `quote_reason`（包括"还没查"），这条由 `Statement.validate()`
与这里的预检双保险 —— 预检存在的理由是把 `kind` 说清楚（调用方要能分辨"参数不对"
与"还没查"）。

## 第五、第六个必填：逐字证明与 ID 形态（`draft/37` §87）

上面那句"双保险"原先只保了一半：`origin="own_result"` 缺 `proof_text`、以及
`doc_id`/`source_lit_id` 形态不对（写成 `"doc:0000"`），都只由 `Statement.validate()`
抛 `ValueError` —— 而它抛在事务里，调用方拿到的是一个异常，不是一条带 `kind` 的
拒绝。T1 第 2 趟真机读数：这一动作被召唤 14 次，6 次落"执行中异常"（就是这一路），
另外 8 次返回了 `ok=False` 却被台账记成 `outcome=ok` —— 两种形态都不像"拒绝"。

于是这里补齐两级预检：`missing_proof_text` 与 `bad_id`。
纪律与其余几级相同：要求写进模型看得见的形状（`specs/b.py`），也在写入口拦下并命名。
`Statement.validate()` 仍然是第二道保险（它保的是"绕开本动作的写库路径"）。

## 第七件：拒绝要自报"这是一次拒绝"（`draft/37` §88 的根因）

返回 `ok=False` 还不够。主控的终态映射原先只看"handler 有没有返回 dict"，
于是这一动作的 10 种拒绝全被记成 `outcome=ok` —— T1 第 2 趟真机：8 次拒绝
在台账上长得像 8 次成功，而 `statements` 是 0 行，整条链在这里静默停住。

所以下面每条拒绝都走 :func:`agentflow.refusals.refuse`：它带上受控的 `refusal_reason`
（`invalid_params` —— 词表的定义正是"参数/前置条件不满足：这次调用本身不成立"）。
不这么写的话，终态只能落 `failed`（"执行了、没成功"），那会把
"我参数给错了"与"代码崩了"重新混成一件事。
"""
from __future__ import annotations

from ._support import S
from ..refusals import refuse as _refuse


class _RegisterStatement:
    def register_statement(
        self,
        *,
        statement_full: str,
        source_lit_id: str = "",
        proof_text: str = "",
        kind: str = "theorem",
        label: str = "",
        statement_text: str = "",
        origin: str = "external_lit",
        page_range: dict | None = None,
        evidence_kind: str = "cross_check",
        quote_verified: bool | None = None,
        quote_reason: str = "",
        derived_from: list | None = None,
        doc_id: str = "",
        line_range: dict | None = None,
    ) -> dict:
        """登记一条命题，返回 `{"ok": True, "stmt_id": ..., "row": {...}}`；不合规就零写入。"""
        full = str(statement_full or "").strip()
        if not full:
            return _refuse("bad_statement",
                           "statement_full 不能为空 —— 只有短版（statement_text）不算数："
                           "省掉假设的命题会被下游当成无条件成立")
        origin = str(origin or "external_lit")
        if origin not in S.STATEMENT_ORIGINS:
            return _refuse("bad_origin",
                           f"origin 必须是 {S.STATEMENT_ORIGINS} 之一，收到 {origin!r}")
        evidence_kind = str(evidence_kind or "heuristic")
        if evidence_kind not in S.EVIDENCE_KINDS:
            return _refuse("bad_evidence_kind",
                           f"evidence_kind 必须是 {S.EVIDENCE_KINDS} 之一，收到 {evidence_kind!r}"
                           "（它是证据**强度**，不是来源；来源走 source_lit_id）")
        lit_id = str(source_lit_id or "").strip()
        if origin == "external_lit" and not lit_id:
            return _refuse("missing_source",
                           "origin='external_lit' 时必须给 source_lit_id —— "
                           "从文献摘的命题必须有出处（没有出处的摘录就是二手结论）")
        if quote_verified is not True and not str(quote_reason or "").strip():
            return _refuse("missing_quote_reason",
                           "quote_verified 不是 True 时必须给 quote_reason —— "
                           "三态纪律：没通过要说为什么没通过，**还没查**也要说出来（不许留白）")
        # 出处：「填了形状不算填了内容」（`draft/37` §68 的第十二/十三趟真机读数），
        # 而"出处是哪一栏"按来源分档（§68 人裁的甲档，与审稿判据逐条对齐）。
        #
        # 实测（第十三趟）：主控给六条 `external_lit` 命题传了
        # `page_range={"start": null, "end": null}` —— 字段在场、内容是空的 ——
        # 于是这一行在台账上"有出处"，而审稿判据（`reviewaccept._c_statements`）
        # 当场报"缺 page_range（页码）"，整条验收因此不及格。
        # 写入口与判据必须说同一件事：判据要求的东西，写入口在「进库之前」就要拦
        # （否则台账里会长期躺着一批"看着有、其实没有"的行，只有走完整审稿流程的人才会发现）。
        if origin == "external_lit":
            page = dict(page_range or {})
            if not (page.get("start") or str(page.get("label") or "").strip()):
                return _refuse("missing_page_range",
                               "origin='external_lit' 时必须给出处页码："
                               "`page_range` 要么给 start（可带 end），要么给 label"
                               "（例如「全文未分页」「附录 A」）—— 只传 "
                               "`{\"start\": null, \"end\": null}` 等于没给，"
                               "审稿判据会判这一行缺出处页码")
        elif origin == "own_result":
            line = dict(line_range or {})
            if not (str(doc_id or "").strip()
                    or line.get("start") or str(line.get("label") or "").strip()):
                return _refuse("missing_own_source",
                               "origin='own_result' 时必须给我们自己的出处："
                               "`doc_id`（我方稿件那一行的 id）或 `line_range`"
                               "（start / label 至少一个）—— 自有结果的出处不是"
                               "「文献第几页」，那一栏要它等于让它编一个数字")
            # 第五级（§87）：自产命题的证明 —— 与上面四级同一条纪律，
            # 由预检命名、而不是让 `Statement.validate()` 从事务里抛出去。
            if not str(proof_text or "").strip():
                return _refuse("missing_proof_text",
                               "origin='own_result' 时必须给 proof_text（逐字证明摘录）—— "
                               "自产的命题没有证明就入库，等于把我们自己的猜测抬成事实；"
                               "还没做完的证明要写成缺口，不要当命题登记")

        # 第六级（§87）：ID 形态。`source_lit_id`/`doc_id` 的形态由 `schema.require_id`
        # 定义（4 位十进制），这里在写库前用同一个谓词核，拒绝时带上 `kind` ——
        # "写成 doc:0000" 于是是一条可读的拒绝，而不是事务里抛出的 `ValueError`。
        for _what, _value in (("source_lit_id", lit_id),
                              ("doc_id", str(doc_id or "").strip())):
            if _value and not S.is_valid_id(_value):
                return _refuse("bad_id",
                               f"{_what} 必须是 4 位十进制字符串（如 \"0000\"），"
                               f"收到 {_value!r} —— 形态由 schema.require_id 定义，"
                               "本动作在写库前用同一个谓词核，整笔不写")

        with self.store.tx("literature", "statements", actor=self.actor,
                           note="register_statement") as tx:
            if lit_id and tx.find("literature", lit_id=lit_id) is None:
                # 坏引用不许进库（与 `doc.build_document` 的 check_citations 同一条纪律）。
                #
                # 附带状态读数（`draft/37` §93 的真机读数）：T1 第 8 趟里这一条被拒了
                # 20 次 —— `literature` 表 0 行（那一趟没人派 `A.ingest_local`），
                # 于是每一条 `external_lit` 命题都撞在同一堵墙上，而拒绝只说"没有这个 lit_id"，
                # 模型无从知道"表本身是空的"还是"号写错了"。这两件事的处置完全不同。
                # 读数里给出"表现在有几行、现有哪些 lit_id"，是为了让它拿一个真的号
                # （或者知道得先去登记），而不是换着号继续猜 —— 这不是分工暗示，
                # 它是这次调用失败所需要的那个事实（与 `draft/28` §196 给 documents 行同一口径）。
                lit_rows = tx.rows("literature")
                ids = [str(r.get("lit_id") or "") for r in lit_rows[:8]]
                more = "（只列前 8 个）" if len(lit_rows) > 8 else ""
                return _refuse("unknown_lit_id",
                               f"literature 表里没有 lit_id={lit_id!r} ⇒ 这条命题的出处不存在，"
                               f"整笔不写库。表里现有 {len(lit_rows)} 行，lit_id："
                               f"{ids or '（一个都没有 —— 表是空的）'}{more}",
                               source_lit_id=lit_id, literature_rows=len(lit_rows),
                               available_lit_ids=ids)

            stmt_id = tx.alloc_id("stmt")
            row = S.Statement(
                stmt_id=stmt_id,
                origin=origin,
                kind=str(kind or "theorem"),
                label=str(label or ""),
                statement_text=str(statement_text or ""),
                statement_full=full,
                proof_text=str(proof_text or ""),
                source_lit_id=lit_id or None,
                page_range=S.PageRange.from_dict(page_range),
                quote_verified=quote_verified,
                quote_reason=str(quote_reason or ""),
                evidence_kind=evidence_kind,
                status="active",
                derived_from=S.sorted_unique(list(derived_from or [])),
                doc_id=str(doc_id or "") or None,
                line_range=S.PageRange.from_dict(line_range),
                created_at=S.now_iso(),
                created_by=self.actor,
            )
            row.validate()
            data = row.to_dict()
            tx.upsert("statements", data, note="register_statement")
            return {"ok": True, "stmt_id": stmt_id, "source_lit_id": lit_id or None,
                    "quote_verified": quote_verified, "origin": origin,
                    "evidence_kind": evidence_kind, "row": data,
                    "note": ("登记 ≠ 核对：quote_verified 是三态（True/False/None），"
                             "它不是 True 时下游必须按 `quote_reason` 读，不许当成通过。")}
