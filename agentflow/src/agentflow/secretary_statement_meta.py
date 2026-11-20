# -*- coding: utf-8 -*-
"""秘书的元数据改写与两个新终态（从 secretary.py 的 U22 的元数据侧逐字搬出）。

我保证哪条不变式：能改哪一格只有一张白名单（六组键逐条列出）；白名单之外的键一律不受理。

## 为什么它能单独成文件（依赖方向）

`secretary_statement_meta` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_statement_meta` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import schema as S
from . import statementledger as SL
from typing import Mapping

from .secretary_statement import (  # noqa: F401 — 这些名字由 secretary_statement 定义
    STATEMENT_ABANDON_PATCH_KEYS,
    STATEMENT_LAND_OPS,
    STATEMENT_META_KINDS,
    STATEMENT_META_PATCH_KEYS,
    STATEMENT_RETIRE_PATCH_KEYS,
    STATEMENT_WRITER_ROLES,
)


class StatementMetaMixin:
    """元数据改写与两个新终态（从 secretary.py 搬出的混入类）。"""

    def _abandon_reason_gate(self, row: Mapping[str, Any], wanted: Mapping[str, Any],
                             given: Mapping[str, Any]) -> dict[str, Any]:
        """放弃命题那一步的换号理由闸（判据本体在 `statementabandon`）。

        返回 `{"refused","reason","form","quote_reason"}`：
        - 不归这道闸管（目标状态不是 abandoned / 明确非命题的 kind / 幂等重放且没交
          新理由）⇒ 空字典（一个字节都不干预）；
        - 受控拒 ⇒ `refused` + `reason`（调用方必须整笔不写）；
        - 过关 ⇒ `quote_reason` 是要落盘的那一条标记（`abandoned@<ISO>@<JSON>`），
          `form` 是判据的逐格读数。

        ## 判档读的是盘上原 kind
        读 `wanted.get("kind", row.get("kind"))` 会让同一笔 patch 里把
        `kind` 改成 `concept` 再写 `status=abandoned`，闸就按"想要的 kind"跳过。
        现在：
        1. 同一笔里改 `kind` + 把 `status` 改成 `abandoned` ⇒ 受控拒
           `abandon_kind_change_in_same_patch`（改类与放弃是两件事，拆开交）；
        2. 判档一律读盘上那一行；若盘上现在是 `concept` / `definition` 而
           `_statement_amend_history` 记着它曾经是命题（先改 kind、再放弃的
           两步走），仍按命题处理 —— 否则一行改成 concept 再一行放弃就绕过去了。

        ## 三档
        1. 明确非命题的两档（`concept` / `definition`）⇒ 不受这道闸管（概念没有
           "条件 ⇒ 结论"，谈不上"命题本身有数学错误"或"证明遇到的困难"）；
           其余一切 kind（含词表外的 `example` / `remark` / 空串）一律按命题处理
           （"认不出的 kind 不拦"就是一条一行 patch 的绕行）。
        2. 命题 ⇒ 必须给 `abandon_kind` + `abandon_basis`，判据
           `statementabandon.check_abandon_reason`（math_error 要 `defect_ref`
           指向这一条且审的是现行正文、理由要点名 `defect_step`；difficulty 要
           `difficulty` + 非空的 `salvaged`，每条在册 / active / 引理类 / 不许自指 /
           须在这笔放弃之前就在册，最后过 `judge_abandon_difficulty` 的语义判定）。
        3. 这一行早就是 `abandoned` 而这一次没交新理由、也没改 `quote_reason`
           ⇒ 幂等重放，不拦（历史行必须还能被重放）；理由要变 ⇒ 与第一次同一道闸
           （已 abandoned 不是免检通行证）。

        ## E 侧那两档
        `counterexample`（发现反例）/ `space_too_large`（枚举空间过于宏大）由同一道闸判：
        前者要 `experiment_id` 指一条真的证否实验、后者要一份结构化的 `space` 读数。
        这两格由调用方随 `status=abandoned` 一起交（走 `patch` 或完整的结构化
        `quote_reason` 标记），本函数只把它们原样递给判据 —— 不在这里写第二套判据。

        ## 为什么落盘的是 JSON 而不是自由文本
        读侧要按 `abandon_kind` 分组、要判"是否带证据"（`closing` 的换号读数），
        自由文本做不到。人类可读的那一段是 `abandon_basis` 本身，它没有被压缩。
        """
        from . import statementabandon as _SA

        target = str(wanted.get("status", row.get("status")) or "")
        if target != "abandoned":
            return {}
        # ---- 1) 放弃的同一笔里改 kind ⇒ 受控拒
        if "kind" in wanted and str(wanted.get("kind") or "") != str(row.get("kind") or ""):
            return {
                "refused": "abandon_kind_change_in_same_patch",
                "reason": ("放弃命题的那一笔不许同时改 kind（收到 "
                           f"{row.get('kind')!r} → {wanted.get('kind')!r}）：判档读的是"
                           "盘上原 kind，换个 kind 就换一把尺。要改类请单独交一笔，"
                           "再按新的 kind 走放弃"),
                "form": {}}

        def _kind_on_disk(current: Mapping[str, Any]) -> str:
            """盘上原 kind；当前是 concept/definition 而历史说它曾是命题 ⇒ 取那次原值。"""
            kind = str(current.get("kind") or "").strip().lower()
            if not _SA.is_abandon_exempt(kind):
                return kind
            for entry in (current.get("_statement_amend_history") or []):
                if not isinstance(entry, Mapping):
                    continue
                changes = entry.get("changes")
                cell = changes.get("kind") if isinstance(changes, Mapping) else None
                if not isinstance(cell, Mapping):
                    continue
                old = str(cell.get("from") or "").strip().lower()
                new = str(cell.get("to") or "").strip().lower()
                if _SA.is_abandon_exempt(new) and old and not _SA.is_abandon_exempt(old):
                    return old
            return kind

        kind_now = _kind_on_disk(row)
        if _SA.is_abandon_exempt(kind_now):
            return {}
        already = str(row.get("status") or "") == "abandoned"
        if not given:
            # 幂等重放：同一个标记原样重交 ⇒ 一个字节都不干预；
            # 要换一段理由（不管是自由文本还是完整结构化标记）⇒ 往下走闸。
            if already and "quote_reason" not in wanted:
                return {}
            if already and str(wanted.get("quote_reason") or "") == str(row.get("quote_reason") or ""):
                return {}
            parsed = (_SA.parse_abandon_reason(wanted.get("quote_reason"))
                      if "quote_reason" in wanted else {})
            if parsed.get("structured") and parsed.get("complete"):
                given = {"abandon_kind": parsed.get("abandon_kind"),
                         "abandon_basis": parsed.get("abandon_basis"),
                         "defect_ref": parsed.get("defect_ref") or "",
                         "difficulty": parsed.get("difficulty") or "",
                         "salvaged": parsed.get("salvaged") or (),
                         "experiment_id": parsed.get("experiment_id") or "",
                         "space": parsed.get("space") or {}}
        at = S.now_iso()
        if already:
            was = _SA.parse_abandon(row.get("quote_reason"))
            if was.get("checked") and str(was.get("at") or ""):
                at = str(was.get("at"))     # 补理由不改"几时放下的"那一刻
        form = _SA.check_abandon_reason(
            self.store,
            kind=given.get("abandon_kind"), basis=given.get("abandon_basis"),
            defect_ref=given.get("defect_ref", ""), difficulty=given.get("difficulty", ""),
            salvaged=given.get("salvaged") or (),
            experiment_id=given.get("experiment_id", ""),
            space=given.get("space") or None,
            statement_id=str(row.get("stmt_id") or ""),
            at=at, statement=row,
            difficulty_judge=self.judge_abandon_difficulty,
            judgment_required=True)
        if not form.get("checked"):
            return {"refused": str(form.get("refused") or "abandon_reason_missing"),
                    "reason": str(form.get("why") or "换号理由不齐 ⇒ 整笔不写"),
                    "form": form}
        marker = _SA.abandon_marker(
            at=at,
            reason=_SA.structured_reason(
                kind=str(form["abandon_kind"]), basis=str(form["abandon_basis"]),
                defect_ref=str(form.get("defect_ref") or ""),
                difficulty=str(form.get("difficulty") or ""),
                salvaged=form.get("salvaged") or (),
                experiment_id=str(form.get("experiment_id") or ""),
                space=form.get("space") or None))
        return {"quote_reason": marker, "form": form}

    def _retire_statement(self, *, sid: str, wanted: Mapping[str, Any],
                          given: Mapping[str, Any], abandon_given: Mapping[str, Any],
                          role: str, task_id: str) -> dict[str, Any]:
        """`refuted` / `hard_to_prove` 两个新终态的转调口（唯一实现不在本文件）。

        ## 为什么另立一格而不是塞进 `amend_statement_meta` 那笔事务
        两件事都要动 `bits`（作废载荷 / 优化栏口袋），而 `bits` 是派生面：
        `STATEMENT_META_PATCH_KEYS` 的白名单里没有它，也不该有（否则通用写口就能
        绕开 `evidencebits` 的推导）。所以这一格只做三件本层该做的事：判"一次只交
        一件"、判 role/task 那一侧的形状、把读数翻成本层既有的返回形状；写盘由
        `statementrefute` 在它自己的事务里做完（受控拒 = 一个字节都没写）。

        ## 三条形状拒（都在转调之前）
        - 同时给 `status="refuted"` 与 `hard_to_prove` ⇒ 拒：两个终态不能一笔办；
        - `status="refuted"` 又给 `abandon_kind` ⇒ 拒：证据格本身就是档
          （`defect_ref` / `construction` ⇒ math_error，`experiment_id` ⇒ counterexample），
          再给一个档名会让"凭哪一条"有两个说法；
        - `hard_to_prove` 的基理由空 ⇒ 拒（由 `mark_hard_to_prove` 给码，这里不另判）。
        """
        from . import statementrefute as _SR

        wants_refuted = str(wanted.get("status") or "") == "refuted"
        wants_hard = "hard_to_prove" in given
        if wants_refuted and wants_hard:
            return {"checked": False, "amended": False, "refused": "retire_two_in_one_patch",
                    "reason": ("这一笔同时要 `status=refuted` 与「难以自证」⇒ 两件事拆开交："
                               "refuted 是终态（命题错了），难以自证不是终态（命题留着、"
                               "只是这一份优化不出来）"),
                    "stmt_id": sid, "changes": [], "row": {}, "form": {}}
        if wants_refuted and "abandon_kind" in abandon_given:
            return {"checked": False, "amended": False, "refused": "refute_kind_not_needed",
                    "reason": ("标记为错误不用另给 `abandon_kind`：证据格本身就是档 —— "
                               "`defect_ref` / `construction` 是「数学错误」，"
                               "`experiment_id` 是「发现反例」。一次只认一种说法"),
                    "stmt_id": sid, "changes": [], "row": {}, "form": {}}
        actor = f"secretary-{self.role}"
        if wants_hard:
            got = _SR.mark_hard_to_prove(
                self.store, statement_id=sid, basis=given.get("hard_to_prove"),
                proof_no=given.get("proof_no") or 1, actor=actor)
        else:
            got = _SR.refute_statement(
                self.store, statement_id=sid,
                reason=abandon_given.get("abandon_basis"),
                experiment_id=abandon_given.get("experiment_id", ""),
                construction=given.get("construction", ""),
                defect_ref=abandon_given.get("defect_ref", ""),
                counterexample_valid=given.get("counterexample_valid"),
                actor=actor)
        out = dict(got)
        out.setdefault("amended", False)
        out["task_id"] = str(task_id or "")
        # 本层既有的返回键：`refused` + `reason`（`refute_statement` 另有一个 `why`，
        # 那是它自己的逐条读数，两个都留着，别把其中一个抹掉）。
        out["reason"] = str(got.get("reason") or got.get("why") or "")
        return out

    def amend_statement_meta(self, stmt_id: str, patch: Mapping[str, Any], *,
                             role: str = "B", task_id: str = "") -> dict[str, Any]:
        """就地改一条在册命题的非正文格（`status` / `kind` / `quote_reason`）。

        ## 为什么需要这一条（真机 82，2026-11-01 · A-1…A-4）

        B 四次用 `table.update(table="statements")` 想改 `kind` / `status` /
        `quote_reason`，四次都被"同一条 statement_full 已在册"拒：兜底把"盘上那一行 +
        patch"整份再交一次登记，而查重判据正是"同一条正文已在册" ⇒ 非正文 patch
        100% 落 duplicate 拒，三格于是没有任何写入口。
        这一格就是那条写口，也是"改哪一格"允许被路由过来的唯一白名单。

        ## 边界（这是权限面，必须写死）
        - 只认 `STATEMENT_META_PATCH_KEYS` 三个键；白名单之外一律受控拒绝
          （`statement_patch_key_not_allowed`），一个字节都不写；
        - `kind` 只认英文词表 `STATEMENT_META_KINDS`（中文 kind 是
          `bad_statement_kind`，不是"重复读数"）；
        - `status` 只认 `schema.STATEMENT_STATUSES`；
        - 正文 / 证据面不在这一格：要改正文请重交一条登记（旧正文进 `proof_history`）。

        ## 走的是秘书的校验与事务
        整行重建后过 `schema.Statement.validate()`（与登记那一支同一套字段校验），
        在 `store.tx("statements", ...)` 里写，并留 `_statement_amend_history`
        （谁、何时、从什么改成什么；只留最近 20 条，与 `_proposition_matches` 同一条
        有界读数纪律）。三态：改成了 / 已经是这些值（幂等，不写）/ 受控拒绝。

        ## 返回
        | 结局 | 返回 |
        |---|---|
        | 改成了 | `checked=True` + `amended=True` + `changes` + `row` |
        | 没有可改的 | `checked=True` + `amended=False`（一个字节都没写） |
        | 受控拒绝 | `checked=False` + `refused=<码>` + `reason` |
        """
        out: dict[str, Any] = {"checked": False, "amended": False,
                               "stmt_id": str(stmt_id or ""), "changes": [],
                               "before": {}, "row": {}, "tables": [],
                               "refused": "", "reason": "",
                               #: 换号理由那几格的判据读数（只有放弃命题那一笔才非空）。
                               "form": {}}
        if self.store is None:
            out.update(refused="secretary_unavailable",
                       reason="这一名秘书没有 store ⇒ 改不了（命题的写侧归秘书）")
            return out
        if str(role) not in STATEMENT_WRITER_ROLES:
            out.update(refused="not_statement_writer",
                       reason=(f"命题的写入侧是 B 的活（收到 role={role!r}）—— "
                               f"只有 {STATEMENT_WRITER_ROLES} 能经这一格改命题"))
            return out
        sid = str(stmt_id or "").strip()
        wanted = {str(k): v for k, v in dict(patch or {}).items()
                  if not str(k).startswith("_")}
        if not wanted:
            out.update(refused="empty_statement_patch",
                       reason=("patch 是空的 ⇒ 没有要改的格。这一条只改 "
                               f"{list(STATEMENT_META_PATCH_KEYS)} 之一或多个"))
            return out
        extra_keys = sorted(k for k in wanted if k not in STATEMENT_META_PATCH_KEYS
                            and k not in STATEMENT_ABANDON_PATCH_KEYS
                            and k not in STATEMENT_RETIRE_PATCH_KEYS)
        if extra_keys:
            out.update(refused="statement_patch_key_not_allowed", reason=(
                f"这一条只允许就地改 {list(STATEMENT_META_PATCH_KEYS)}"
                f"（放弃命题时另带 {list(STATEMENT_ABANDON_PATCH_KEYS)}；"
                f"标记为错误 / 难以自证时另带 {list(STATEMENT_RETIRE_PATCH_KEYS)}），"
                f"收到 {extra_keys}。"
                "改正文请把新正文写进 `statement_full` / `proof_text` 再交一次 "
                "`own.register_statement`（同一条命题会就地覆盖，旧正文进 `proof_history`）；"
                "其余格没有就地写口 —— 整笔不写，盘上一个字节都没变。"))
            return out
        #: 另外两个终态的格先摘出来（与放弃那几格同一条纪律：不是可写列）。
        retire_given = {k: wanted.pop(k) for k in list(wanted)
                        if k in STATEMENT_RETIRE_PATCH_KEYS}
        #: 换号理由那几格先摘出来：它们不是可写的列（见 `STATEMENT_ABANDON_PATCH_KEYS`），
        #: 只用来拼 `quote_reason` 那一条标记。
        abandon_given = {k: wanted.pop(k) for k in list(wanted)
                         if k in STATEMENT_ABANDON_PATCH_KEYS}
        if "status" in wanted:
            status = str(wanted["status"] or "").strip()
            if status not in S.STATEMENT_STATUSES:
                out.update(refused="bad_statement_status", reason=(
                    f"status 必须是 {S.STATEMENT_STATUSES} 之一，收到 {wanted['status']!r}"
                    "（它是命题的可信状态，不是自由文本）；建议：按这份词表里的取值改后重交"))
                return out
            wanted["status"] = status
        if "kind" in wanted:
            kind = str(wanted["kind"] or "").strip()
            if kind not in STATEMENT_META_KINDS:
                out.update(refused="bad_statement_kind", reason=(
                    f"kind 必须是英文词表 {list(STATEMENT_META_KINDS)} 之一，收到 {kind!r} —— "
                    "中文 kind（定理 / 引理）不是取值；这一格由证据派生，改它也请走证据。"
                    "建议：按英文词表取值重交；要让 kind 跟着证据走，就重交 "
                    "`own.register_statement`（`evidencebits.kind_following_grade` 现算）"))
                return out
            wanted["kind"] = kind
        if "quote_reason" in wanted:
            text = str(wanted["quote_reason"] or "")
            if not text.strip():
                out.update(refused="bad_quote_reason", reason=(
                    "quote_reason 不能改成空串 —— 三态纪律：没通过要说清为什么、"
                    "还没查也要说出来，不许留白。建议：写清「为什么没通过」或"
                    "「为什么还没查」后重交（空串不是一种理由）"))
                return out
            wanted["quote_reason"] = text
        # ---- 2026-11-13（业主裁定）：两个新终态转调唯一实现 ------------------------
        #
        # 为什么必须在这里分出去、不能落进下面那一笔：`_abandon_reason_gate` 只认
        # `status="abandoned"`（其它目标直接返回空字典）⇒ 一条 `status="refuted"` 的
        # patch 会绕过全部证据判据、把一行直接推成"被证否"而拿不出任何凭据。
        if retire_given or str(wanted.get("status") or "") == "refuted":
            return self._retire_statement(sid=sid, wanted=wanted, given=retire_given,
                                          abandon_given=abandon_given,
                                          role=role, task_id=task_id)
        try:
            with self.store.tx("statements", actor=f"secretary-{self.role}",
                               note="secretary:amend_statement_meta") as tx:
                # 按号定位走查口（口径一）；事务快照传 `rows=`，锁内读失败仍照旧抛出。
                by_id = SL.by_id(rows=tx.rows("statements"), stmt_id=sid)
                row = by_id["row"] if by_id["found"] else None
                if row is None:
                    out.update(refused="not_found",
                               reason=f"statements 里没有主键 {sid} ⇒ 没有可改的行")
                    return out
                # ---- 2026-11-07（业主裁定）：放弃/换号必须给清结构化理由 ----------
                #
                # 位置在"算 changed 之前、`tx.upsert` 之前"：受控拒要求一个字节都不写，
                # 而这一格一旦被判拒，`wanted` 里的 `status` 也不许落盘。
                gate = self._abandon_reason_gate(row, wanted, abandon_given)
                if gate.get("refused"):
                    out.update(refused=str(gate["refused"]),
                               reason=str(gate.get("reason") or ""),
                               form=dict(gate.get("form") or {}))
                    return out
                if gate.get("quote_reason"):
                    wanted["quote_reason"] = str(gate["quote_reason"])
                    out["form"] = dict(gate.get("form") or {})
                before = {k: row.get(k) for k in wanted}
                changed = {k: v for k, v in wanted.items() if row.get(k) != v}
                out["before"] = before
                if not changed:
                    out.update(checked=True, amended=False, row=row,
                               reason=("这一笔要改的格已经是这些值 ⇒ 一个字节都没写"
                                       "（幂等：不是失败，也不是改成了）"))
                    return out
                merged = dict(row)
                merged.update(changed)
                history = [dict(h) for h in (row.get("_statement_amend_history") or [])
                           if isinstance(h, Mapping)]
                history.append({
                    "at": S.now_iso(), "by": f"secretary-{self.role}",
                    "task_id": str(task_id or ""),
                    "changes": {k: {"from": before.get(k), "to": v}
                                for k, v in changed.items()}})
                merged["_statement_amend_history"] = history[-20:]
                try:
                    obj = S.row_from_dict("statements", dict(merged))
                    obj.validate()
                    canonical = obj.to_dict()
                except (TypeError, ValueError) as exc:
                    out.update(refused="validation", reason=(
                        f"改完之后这一行不是合法的命题行（{type(exc).__name__}: {exc}）"
                        " ⇒ 整笔不写（不在'改一格'里顺手写坏一行）"))
                    return out
                extra = {k: v for k, v in merged.items() if k not in canonical}
                row_out = {**extra, **canonical}
                tx.upsert("statements", row_out, note="secretary:amend_statement_meta")
                out.update(checked=True, amended=True, stmt_id=sid,
                           changes=sorted(changed), row=row_out,
                           tables=["statements"],
                           reason=("就地改了 " + "、".join(sorted(changed))
                                   + "（非正文格；正文与证据面一个字没动）"))
                return out
        except Exception as exc:  # noqa: BLE001 —— 落盘失败必须回三态，不许半笔
            out.update(checked=False, refused="write_failed",
                       reason=(f"改非正文格没成（{type(exc).__name__}: {exc}）"
                               " ⇒ 这一笔按'没写成'读"))
            return out

    def land_statement(self, stmt_id: str, transition: Any, *, op: str,
                       note: str = "", role: str = "B") -> dict[str, Any]:
        """在秘书的事务里落一次 `statements`：调用方只给"行变换"，写盘与"改了哪几格"的判据在这里。

        ## 为什么需要这一条（业主 2026-11-08，逐字）
        「我应该定过B实际只有台账的只读权限，B的任何所谓写台账的路实际上都由B秘书洗过」
        ⇒ B 本体对 `statements` 只读：它的两支写侧（`_attach_proofs` / `_update_numeric_evidence`）
        此前自己开 `store.tx("statements")` 落行，秘书那一层一个字都没过目。收口之后
        B 只说"这一笔要改成什么"，四件事归这一层：开事务、读现行行、判"改了哪几格"、写盘。

        ## 参数
        - `transition(row_or_None) -> {"write": bool, "row": {...}, "result": <调用方读数>}`：
          调用方用它拿到的事务内那一行算"这一笔要改成什么"（返回 `write=False` ⇒
          一个字都不写；返回 `refused` + `reason` 也等价于不写）。传进来的 `row` 是
          `tx.find` 读的，所以"读—判—写"仍在同一把锁里、与收口前逐字同序。
        - `op`：`STATEMENT_LAND_OPS` 的键 —— 决定这一笔允许改哪几格。

        ## 洗的是什么（不是空转的漏斗）
        落盘前逐条核：`stmt_id` 那一行在不在、`transition` 要写的行是不是把允许之外的格
        改了（越界 ⇒ `statement_patch_key_not_allowed`，一个字节都不写）。正文真身、出处面、
        创建留痕都不在任何 `op` 的白名单里 ⇒ 这一条路改不动它们。

        ## 三态（不折平）
        | 结局 | 返回 |
        |---|---|
        | 写成了 | `checked=True` + `written=True` + `row` + `changed` + `result` |
        | 调用方判定这一笔无内容 / 它自己拒了 | `checked=True` + `written=False` + `result` |
        | 秘书这一层拒（越界 / 行不在 / 没有 store / 不是 B 的活） | `checked=False` + `refused` + `reason` |

        ## 异常不吞
        事务里的异常照旧往上抛：两个调用方各有自己的异常处置（`_update_numeric_evidence`
        折 `numeric_evidence_write_failed`；`_attach_proofs` 一直是往上抛）。在这里吞掉会把
        它们的拒码换成一个泛码 —— 那是把"哪一步没写成"抹平。
        """
        out: dict[str, Any] = {"checked": False, "written": False,
                               "stmt_id": str(stmt_id or ""), "op": str(op or ""),
                               "refused": "", "reason": "", "changed": [],
                               "row": {}, "result": {}, "tables": []}
        if self.store is None:
            out.update(refused="secretary_unavailable",
                       reason="这一名秘书没有 store ⇒ 命题行写不了（写入侧归秘书）")
            return out
        if str(role) not in STATEMENT_WRITER_ROLES:
            out.update(refused="not_statement_writer",
                       reason=(f"命题的写入侧是 B 的活（收到 role={role!r}）—— "
                               f"只有 {STATEMENT_WRITER_ROLES} 能经这一格落命题行"))
            return out
        allowed = STATEMENT_LAND_OPS.get(str(op or ""))
        if allowed is None:
            out.update(refused="unknown_statement_land_op",
                       reason=(f"`op={op!r}` 不在 {sorted(STATEMENT_LAND_OPS)} 里 ⇒ "
                               "不知道这一笔允许改哪几格，整笔不写"))
            return out
        sid = str(stmt_id or "").strip()
        with self.store.tx("statements", actor=f"secretary-{self.role}",
                           note=note or f"secretary:land_statement:{op}") as tx:
            # 按号定位走查口（口径一）；事务快照传 `rows=`，锁内读失败仍照旧抛出。
            by_id = SL.by_id(rows=tx.rows("statements"), stmt_id=sid)
            found = (by_id["row"] if by_id["found"] else None)
            got = dict(transition(dict(found) if found is not None else None) or {})
            out["result"] = dict(got.get("result") or {})
            if got.get("refused"):
                out.update(checked=False, written=False,
                           refused=str(got.get("refused") or "statement_land_refused"),
                           reason=str(got.get("reason") or ""))
                return out
            if not got.get("write"):
                out.update(checked=True, written=False,
                           reason="这一笔没有要写的内容（调用方判定）⇒ 一个字节都没写")
                return out
            if found is None:
                out.update(checked=False, refused="statement_missing",
                           reason=(f"`statements` 里没有 {sid} ⇒ 这一笔没有落点"
                                   "（行没落成，改也无处可改）：一个字节都没写"))
                return out
            base = dict(found)
            row = dict(got.get("row") or {})
            changed = sorted(k for k in (set(base) | set(row))
                             if base.get(k) != row.get(k))
            bad = [k for k in changed if k not in allowed]
            if bad:
                out.update(checked=False, refused="statement_patch_key_not_allowed",
                           reason=(f"`{op}` 这一笔只许改 {list(allowed)}，而它改了 {bad} ⇒ "
                                   "整笔不写（正文真身 / 出处面 / 创建留痕都不在任何一条"
                                   "落盘白名单里）"))
                return out
            if not changed:
                out.update(checked=True, written=False,
                           reason=("这一笔要写的就是盘上这些值 ⇒ 一个字节都没写"
                                   "（幂等：不是失败，也不是写成了）"))
                return out
            tx.upsert("statements", row,
                      note=note or f"secretary:land_statement:{op}")
            out.update(checked=True, written=True, found=True, row=dict(row),
                       changed=changed, tables=["statements"],
                       reason=("落了 " + "、".join(changed) + f"（`{op}`；由秘书写盘）"))
            return out

    def _with_relabel_reading(self, landed: Mapping[str, Any] | None,
                              *, kind: str = "") -> dict[str, Any]:
        """登记成功之后，把"这一笔是不是换号（同一 label 再登记）"的读数带上。

        业主 2026-11-07 的裁决只拦放弃那一侧（`Statement` 的
        `status=abandoned` 写口），登记这一侧不拦：历史工作区里已经有一批没有
        结构化理由的 `abandoned` 行，拦它们只会把 B 卡死。所以这一格只做两件事：

        - 原件理由齐 ⇒ 返回读数 `supersedes`（原 `stmt_id` + `abandon_kind` +
          `abandon_basis` 摘要 + 证据是否在）；
        - 原件理由不齐（历史行）⇒ 返回 `superseded_without_reason`（原 `stmt_id` 列表），
          不拒 —— 让审计一眼看到"这一条换号是在没有给出理由的情况下发生的"。

        判据本体是 `statementabandon.relabel_events`（`closing` 的换号读数读同一份）。
        """
        out = dict(landed or {})
        if not out.get("created") or not str(out.get("stmt_id") or ""):
            return out            # 不是新建（已在册 / 升档 / 合并）⇒ 没有"换号"这回事
        from . import statementabandon as _SA

        sid = str(out.get("stmt_id") or "")
        label = str((out.get("row") or {}).get("label") or "").strip()
        if not label:
            return out
        try:
            events = _SA.relabel_events(self.store.rows("statements"))
        except Exception as exc:  # noqa: BLE001 —— 读数读不出来不许带走已经落盘的登记
            out["relabel"] = {"checked": False,
                              "reason": f"{type(exc).__name__}: {exc}"}
            return out
        priors = [one for one in events.get(label, []) if one.get("stmt_id") != sid]
        out["relabel"] = {"checked": True, "label": label,
                          "priors": len(priors),
                          "supersedes": [], "superseded_without_reason": []}
        if not priors:
            return out
        for one in priors:
            if one.get("complete"):
                out["relabel"]["supersedes"].append({
                    "stmt_id": one["stmt_id"], "at": one.get("at", ""),
                    "abandon_kind": one.get("abandon_kind", ""),
                    "basis": one.get("basis", ""),
                    "has_evidence": bool(one.get("has_evidence")),
                })
            else:
                out["relabel"]["superseded_without_reason"].append({
                    "stmt_id": one["stmt_id"], "at": one.get("at", ""),
                    "why": "原件没有结构化的换号理由（历史行）⇒ 只报不拦",
                })
        # 顶层也放一份：模型读的是返回值，`relabel` 里那一层太深时它会漏看。
        if out["relabel"]["supersedes"]:
            out["supersedes"] = list(out["relabel"]["supersedes"])
        if out["relabel"]["superseded_without_reason"]:
            out["superseded_without_reason"] = list(
                out["relabel"]["superseded_without_reason"])
        return out
