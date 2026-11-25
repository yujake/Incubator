# -*- coding: utf-8 -*-
"""秘书的登记外壳与形状闸（从 secretary.py 的 U22 的外壳逐字搬出）。

我保证哪条不变式：`statements` / `dependencies` 只有这一个写者；形状不对的正文在进入事务之前就被拒。

## 为什么它能单独成文件（依赖方向）

`secretary_statement` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_statement` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import refusals as R
from . import schema as S
from . import statementbody as _SB
from typing import Mapping

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    NOT_APPLICABLE_KINDS,
    PROPOSITION_KINDS,
)

from .secretary_evidence import (  # noqa: F401 — 这些名字由 secretary_evidence 定义
    _bits_bear_evidence,
    _complete_statement_bits,
    _semantic_quote_evidence_refusal,
    proof_text_manuscript_sign_gate,
)


class StatementMixin:
    """登记外壳与形状闸（从 secretary.py 搬出的混入类）。"""

    def record_statement(self, payload: Mapping[str, Any], *, role: str = "B",
                         force_new: bool = False,
                         candidate_id: str = "",
                         adjudication: Mapping[str, Any] | None = None
                         ) -> dict[str, Any]:
        """B 交内容 ⇒ 秘书落盘；受控拒的那一档同时在盘上留一份原文。

        ## 为什么这一层要留痕（2026-11-17 AL2·#3）

        这一条路是"秘书缝的落库代理"：调用方（B 自己的 `register_statement`、
        `table.create/update` 的 routed 分支、以及任何按 `store.direct_write_refusal`
        被指到这条正路上的角色）交内容，判定与写口都在秘书这一侧 —— 于是受控拒不
        产生任何 `agent_step_call`（被拒的那一笔根本没进工具执行器）。真机现场
        （AH1）：A 这一趟有 5 次收录被拒，而 B 的 `agent_step_call` 里 0 条、run 文件
        也还没写到那一刻 ⇒ 审计时"为什么拒"只能猜。

        判据（`tests/test_secretary_controlled_refusals_leave_the_original_text.py`）：
        受控拒 ⇒ `out/secretary/refusals.jsonl` 多一行原文（kind / why / at / role /
        task_id / where）；把写点打桩关掉 ⇒ 那一行必消失（反真空）。

        返回值与改前逐字相同（正文那一段在 `_record_statement_impl`）—— 这一层只加
        留痕，不改任何判定。
        """
        out = self._record_statement_impl(
            payload, role=role, force_new=force_new, candidate_id=candidate_id,
            adjudication=adjudication)
        refused = str((out or {}).get("refused") or "")
        if refused:
            # 留痕不许改变处置：写不进去时 `record_refusal` 自己返回 None（不抛）。
            #
            # `task_id` 优先用秘书自己绑的那个；没绑（`for_role_wired` 造出来的那一档
            # 不绑，`table.create` 路由过来的就是这一档）⇒ 读这一趟召唤的号 ——
            # 否则台账上"哪一单被拒"这一格是空的，而审计要的正是它。
            _task_id = str(getattr(self, "task_id", "") or "")
            if not _task_id:
                try:
                    from .conductor import current_task_id as _current_task_id
                    _task_id = str(_current_task_id() or "")
                except Exception:  # noqa: BLE001 —— 读不到挂点不妨碍留痕，也不许改变处置
                    _task_id = ""
            R.record_refusal(
                self.root, kind=refused,
                why=str((out or {}).get("reason") or ""),
                role=str(role or ""), task_id=_task_id,
                where="secretary.record_statement")
        return out

    def _record_statement_impl(self, payload: Mapping[str, Any], *, role: str = "B",
                               force_new: bool = False,
                               candidate_id: str = "",
                               adjudication: Mapping[str, Any] | None = None
                               ) -> dict[str, Any]:
        """B 交内容 ⇒ 秘书落盘（洗格式 / 拿编号 / 查重 / 改表四件一次做完）。

        这是一笔事务（`statements` + `dependencies`），B 那一侧只交内容、不调工具。

        ## 返回（要能分辨"没写"的几种原因）

        | 结局 | 返回 |
        |---|---|
        | 写成了 | `{"checked": True, "created": True, "stmt_id": …, "deps_written": n, "path_groups": k}` |
        | 同内容已有一条 | `{"checked": True, "created": False, "duplicate": True, "stmt_id": <既有>}` |
        | 同内容 + 更强证据档（有凭据） | `{"checked": True, "created": False, "upgraded": True, "stmt_id": <既有>, "changes": [...]}` |
        | 受控拒绝（一行都不落） | `{"checked": False, "refused": "<理由码>", "reason": …}` |

        理由码：`secretary_unavailable` / `not_statement_writer` / `wash_failed` /
        `unresolved_dependency`（依赖指着一个不在册的 id）/ `unknown_lit_id` /
        `empty_statement`（缺 `statement_full` —— 只有短版不算数）/
        `statement_label_taken`（同一个名字已经有 active 行在册；见 `_record_statement_tx` 的
        名字位那一格 —— 改名的出路写在 `reason` 里）/ `statement_label_unchecked`（没查成）。
        概念的定义空着不是拒绝：它落成 `pending_definition` + 待补标记。

        ## 同一命题 / 同种证明

        先按 `statement_full` 的规范化值查重（老口径）；没命中时再判"是不是同一条命题"：
        秘书判得成（`adjudicate_proposition`）⇒ 它说了算；没查成 ⇒ fail-closed，
        只认「确定性键相同」这一档等价改写（词面相似度只给候选表排序、不决定并）。
        命中 ⇒ 不新建命题行，而是那条命题的第 N 份证明：证明落 `proofs` 清单
        （canonical 空时落 `proof_text`）、依赖落 `used_by="stmt:#pN"`。
        没有证明正文的重复登记也判归属：判得成同一条 ⇒ 回 `duplicate=True` + `no_proof=True`
        （重复读数，不是第 N 份证明）；判不成 ⇒ 照常新建。
        同一命题下的新证明与在册某一份同种（`proof_same_kind` 阈值）⇒ 不新增证明号、
        受控拒绝并点名第几份；调用方给 `merge=True` 并交合并稿时，合并稿成为那一份的
        新版本、旧正文进 `proof_history`，且要求 V 重签（`resign_required=True`）。

        ## 概念行：同一个概念不许落成第二行

        `kind="concept"` 没有"条件 ⇒ 结论"，上面的判据在它上面等于失效（两条把同一个术语
        定义了两遍会被判成"不同"）。所以概念行另有一条确定性判据：定义项相同
        （标签规范化后相同，或正文里「概念（X）」/「定义（X）」抽出的术语相同）⇒
        不新建、返回既有 `stmt_id`（`duplicate=True` + `matched_by`）。这一档不发模型调用。

        ## 定理名里的内部工作名不许当定理名

        `F 攻坚 000000 子目标 S2` 这类派活台账里的工作名命中
        `LABEL_WORKING_NAME_RULES` 就洗掉，洗成什么由 `wash_working_name` 的三级兜底决定
        （剩下一截 / 正文第一句 / 待命名），读数在 `label_washed` 里逐条给
        「原标签 → 洗过的名字 + 触发了哪一类」。

        ## `candidate_id`：把稿名/稿头的号当候选号

        B 在"新建"这一档把稿名/稿头算出来的号当候选交进来：可用就用它发号
        （并 `raise_counter_to` 把计数器抬到它之后）；已被占 ⇒ 受控拒绝 `stmt_id_taken`，
        不另发一个号 —— 静默另发会让稿与命题的号错开。
        """
        out: dict[str, Any] = {"checked": False, "created": False, "duplicate": False,
                               "upgraded": False, "merged": False, "merged_into": "",
                               "merged_same_kind": False, "proof_no": 0,
                               "matched_by": "", "similarity": 0.0, "same_kind": [],
                               "proposition_state": "", "proposition_reason": "",
                               #: 命题同一性判定的三态读数（见 `_adjudication_reading`）。
                               #: 空字典 = 这一笔没走到那一格（例如 `force_new` 早退）。
                               "adjudication": {},
                               #: "判了没有"的一句话（见 `_with_adjudication_visibility`）：
                               #: `checked` / `attempted` / `reason` / `seam_source`。
                               #: 空字典 = 这一笔没走到那一格（同上；拒绝那几笔在
                               #: `reason` 里已经说清了为什么不写）。
                               "proposition_adjudication": {},
                               #: 洗过的定理名与"洗掉了什么"（业主 2026-10-24：让秘书洗定理名）。
                               "canonical_name": "", "label_washed": {},
                               #: 这一笔的证明自己的路子说明（路线住在证明这一层）。
                               "proof_route": "",
                               "resign_required": False, "reviewed": False,
                               "stmt_id": "", "deps_written": 0, "path_groups": 0,
                               #: 依赖面建起来没有（三态；见 `_deps_missing_reading`）。
                               #: 键一直在，值只有真写到那一格时才填 —— 拒绝那一档是空字典，
                               #: 不拿"没走那一格"冒充"依赖不缺"。
                               "deps_missing": {},
                               "tables": [], "washed": False, "changes": [],
                               "refused": "", "reason": "", "pending": []}
        if self.store is None:
            out.update(refused="secretary_unavailable",
                       reason=("这一名秘书没有 store ⇒ 写不了（B 交内容、秘书落盘是唯一"
                               "一条路：不许退回'B 自己写'）"))
            return out
        if str(role) not in STATEMENT_WRITER_ROLES:
            out.update(refused="not_statement_writer",
                       reason=(f"命题的写入侧是 B 的活（收到 role={role!r}）——"
                               f"只有 {STATEMENT_WRITER_ROLES} 能交内容给这一条路径"))
            return out
        washed = self.wash_statement(payload)
        out["washed"] = bool(washed.get("washed"))
        out["changes"] = list(washed.get("changes") or [])
        if not washed.get("checked"):
            out.update(refused="wash_failed", reason=str(washed.get("reason") or "洗格式没跑成"))
            return out
        body = dict(washed.get("payload") or {})
        full = str(body.get("statement_full") or "")
        kind = str(body.get("kind") or "theorem")
        if not full.strip():
            if kind == "concept":
                # 定义还没抽到的概念行照落 ——
                # 落成 `pending_definition`（不是依据）+ 待补标记（谁去补写在 reason 里）。
                # 不许折成 `active` + 空定义（`Statement.validate` 当场拒），
                # 也不许"干脆不落"（那样这个概念并表之后查不到）。
                return self._record_pending_concept(body, out=out)
            out.update(refused="empty_statement",
                       reason=("statement_full 是空的 ⇒ 不写（只有短版不算数：省掉假设的"
                               "命题会被下游当成无条件成立）"))
            return out
        # ---- 语义那一档的证据缺了就不写，并给具名理由。
        #
        # 判据本体在 `_semantic_quote_evidence_refusal`（拆出来只为让本方法留在"一屏半"之内）。
        _semantic_refusal = _semantic_quote_evidence_refusal(body)
        if _semantic_refusal:
            out.update(**_semantic_refusal)
            return out
        # ---- 出处档的词表：与 B 的 `bad_origin` 同一个码（路由过来的非法载荷也要
        # 在"正文闸"之前被按这一格拒：否则拒信会说"缺手稿签"，而真正错的是 origin）。
        _origin_now = str(body.get("origin") or "")
        if _origin_now not in S.STATEMENT_ORIGINS:
            out.update(checked=False, created=False, duplicate=False, upgraded=False,
                       merged=False, refused="bad_origin",
                       reason=(f"origin 必须是 {S.STATEMENT_ORIGINS} 之一，"
                               f"收到 {_origin_now!r}"))
            return out
        # ---- 来路不是闸（业主 2026-11-17 语义纠正）-----------------------
        #
        # `derived_from` / `source_lit_id` 是可选的补充信息：有就记，没有不算错。
        # "自产"的证据是台账里那份签过的稿（收工门「造」那一环现读
        # `closing.own_result_manuscript_links`），不是载荷里的一个 `derived_from`。
        # ---- 正文必须由手稿承载：`proof_text` 的唯一收口闸 ----
        #
        # 位置在"判同一性"之前：这一笔如果连正文都不该写，就不该先花一次模型调用去
        # 判它跟谁同一条；而且判词会诱导调用方以为"只差一个合并"。
        # 闸本身是纯读（`proof_text_manuscript_sign_gate`）：它只回答"这一份正文有没有
        # 一份审的是手稿、且盖住这份正文的签"，不写盘、不改正文。
        if body.get("merge") is not True and kind != "concept":
            _intake = proof_text_manuscript_sign_gate(
                self.store, proof_text=body.get("proof_text"),
                statement_full=full, proof_no=body.get("proof_no"),
                origin=body.get("origin"), source_lit_id=body.get("source_lit_id"),
                defer_without_sign=_bits_bear_evidence(body.get("bits")))
            out["proof_text_gate"] = dict(_intake)
            if _intake.get("refused"):
                out.update(checked=False, created=False, duplicate=False, upgraded=False,
                           merged=False, refused=str(_intake.get("refused") or ""),
                           reason=str(_intake.get("reason") or ""))
                return out
        # 合并那一支的 `statement_full` 是"近似写法"（逐字相同会先撞 duplicate 早退），
        # 它要落到哪一条在册行由同一性判定给出 ⇒ 这一闸必须在判定之后、拿到 `same_as`
        # 再判一次（`_merge_into_proposition` 里）。先在这里跳过，免得把一条合法的
        # 合并判成"没有在册行"。
        # ---- 命题同一性：让秘书洗定理名、让秘书判。
        #
        # 位置在"落盘之前、事务之外"：这一步会发一次模型调用（可以慢、可以超时），
        # 把它放进 `store.tx` 就是拿网络等待去占着写锁，而锁里不该有网络等待。
        # 读候选用的是 `self.store.rows`（只读），事务里那一份快照由 `_record_statement_tx`
        # 自己再用 `tx.rows` 核（合并前它必须确认那一条还在、还可并）。
        if adjudication is None:
            adjudication = self.adjudicate_proposition(
                {"statement_full": full, "label": str(body.get("label") or ""),
                 "kind": kind})
        else:
            # 调用方已经把"是不是在册的同一条"查过一圈
            # （`register_statement._resolve_same_statement`：关键词检索 + 秘书认定）。
            # 这里沿用那一趟的结论，不再发第二次模型调用 —— 同一件事两个判据会给出
            # 两个答案，而"两处各判一次"正是这条链要收掉的形态。
            adjudication = dict(adjudication)
            out["adjudication_source"] = "register_statement:same_statement"
        out["adjudication"] = self._adjudication_reading(adjudication)
        #: 没判成必须可见：`adjudication` 是那一趟的逐字读数，而这一格是
        #: "判了没有"的一句话（`checked` / `attempted` / `reason` / `seam_source`）。
        #: 为什么要两格：前者挨着 `verdict` / `basis` 那一组判词，读的人（模型只看工具
        #: 返回的那份 JSON）容易把它读成"判过了、结论是某一档"；这一格单独命名，于是
        #: "这一条判定根本没发生"在返回值里不可能被漏看。
        out["proposition_adjudication"] = dict(
            adjudication.get("proposition_adjudication") or {})
        out["canonical_name"] = str(adjudication.get("canonical_name") or "")
        # ---- 同种证明：在锁外先问一次（锁内不许发模型），结论带进事务 ----------
        _proof_kind = self._proof_kind_for_existing(
            full=full, body=body, adjudication=adjudication)
        if _proof_kind:
            out["proof_kind"] = {
                "checked": bool(_proof_kind.get("checked")),
                "decision": str(_proof_kind.get("decision") or ""),
                "same_path": int(_proof_kind.get("same_path") or 0),
                "material_similarity": float(_proof_kind.get("similarity") or 0.0),
                "reason": str(_proof_kind.get("reason") or ""),
            }
        return self._land_or_refuse(body, full=full, kind=kind,
                                    force_new=bool(force_new), out=out,
                                    adjudication=adjudication,
                                    proof_kind=_proof_kind,
                                    candidate_id=str(candidate_id or ""))

    def _land_or_refuse(self, body: Mapping[str, Any], *, full: str, kind: str,
                        force_new: bool, out: dict[str, Any],
                        adjudication: Mapping[str, Any],
                        candidate_id: str,
                        proof_kind: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """把这一笔交给事务写口；写不成按三态回一条读数（不抛、不半笔）。

        2026-11-08 从 `record_statement` 拆出（只搬移，块内逐字相同）：「交给事务写口」
        与「写不成怎么读」是同一件事的两半，合起来 20 余行；拆开之后 `record_statement`
        回到 200 行以内 —— 体量基线是读数，不许为了它抬（业主口径：拆函数，不抬基线）。
        """
        try:
            landed = self._record_statement_tx(body, full=full, kind=kind,
                                               force_new=bool(force_new), out=out,
                                               adjudication=adjudication,
                                               candidate_id=candidate_id,
                                               proof_kind=proof_kind)
            return self._with_relabel_reading(landed, kind=kind)
        except Exception as exc:  # noqa: BLE001 —— 落盘失败必须回三态，不许半笔
            # ---- 写入期闸的拒收要留住它自己的码（2026-11-05 走查 D2）------------
            #
            # 改前这一格把所有异常折成 `write_failed`，于是"升档这一笔被
            # `proof_review_without_evidence` 拒了"在返回值里只剩一个泛码 —— 调用方
            # （B）既看不出该去补哪一份签，也没法据码分辨"参数不对"与"证据不够"。
            # 判据仍是那个异常自己的码（`verifications.CODE_WRITE`），这里只做翻译。
            code = "write_failed"
            message = f"{type(exc).__name__}: {exc}"
            try:
                from . import verifications as _VR   # 惰性：只在这条异常路上需要
                if str(exc).startswith(_VR.CODE_WRITE):
                    code = _VR.CODE_WRITE
            except Exception:  # noqa: BLE001 —— 翻译失败仍回泛码（不许因此吞掉异常）
                pass
            out.update(checked=False, created=False, upgraded=False, refused=code,
                       reason=f"落盘没成（{message}）⇒ 这一笔按'没写成'读")
            return out

    def _statement_from(self, body: Mapping[str, Any], *, full: str, kind: str,
                        stmt_id: str) -> Any:
        """按白名单把载荷拼成 `Statement`（未知键不进库：它多半是拼错的字段名）。"""
        def _s(key: str) -> str:
            return str(body.get(key) or "")

        def _rng(key: str) -> Any:
            raw = body.get(key)
            return S.PageRange.from_dict(raw) if isinstance(raw, Mapping) else S.PageRange()

        def _lines(key: str) -> Any:
            """`line_range` 的既有约定是归一化后的区间（`{"start":120,"end":148}`）。

            判据（`tests/test_intake_actions.py`）落的是归一化区间，而 `_normalize_range`
            就是那个唯一实现 —— 所以走 `_rng`。判据比注释权威；"注释与判据对不上"
            这件事该单独记一笔，不该顺手改掉任何一边。
            """
            return _rng(key)

        origin = _s("origin") or "external_lit"
        reason = _s("quote_reason")
        if not reason.strip() and body.get("quote_verified") is not True:
            # B 只交"定理内容 + 证明过程"，别的一概不要求它给。
            # 而 `Statement.validate` 的硬要求是"不是 True 就必须写 quote_reason" ——
            # 不给一个受控的默认值，那份两件式契约对自产命题（`own_result`）在结构上
            # 就不成立（整笔会以 `quote_verified=None 时必须写 quote_reason` 被拒）。
            # 这里填的是为什么这一格是空的，不是编一个"已核对"的结论：
            # 回验要做的是拿另一份文本逐字比，而自产命题没有第二份文本可比。
            # 调用方给了就照用（不覆盖）。
            reason = ("own_result（我们自己证的）：逐字回验这一格不适用（没有第二份文本可比）—— "
                      "证明过程在 proof_text 里，采信与否由审校（H）与验证（V）那一档判")
        return S.Statement(
            stmt_id=stmt_id, origin=origin, kind=kind,
            label=_s("label"),
            # ---- 正文只有一个真身，短版是派生值。
            #
            # 同一份正文两个字段、一个空一个满，读侧读哪个都能给出另一种答案。真身定在
            # `statement_full`（schema 对它才是硬要求、下游都靠它），短版在这里由它
            # 派生（逐字复制，不截断：截断出来的"短版"是另一条命题）。派生规则只有
            # 这一处实现（`statementbody.derive_text`），读侧的唯一入口是
            # `statementbody.body_of`。
            statement_text=_SB.derive_text(full, _s("statement_text")),
            statement_full=full,
            proof_text=_s("proof_text"), source_lit_id=_s("source_lit_id") or None,
            page_range=_rng("page_range"), quote_verified=body.get("quote_verified"),
            quote_reason=reason,
            # ---- 回验的三栏证据必须能过这一层。
            #
            # 只被 `STATEMENT_PARAM_KEYS` 收下、却没搬进 `Statement` 就会被静默丢掉：
            # H 的语义判定给了 `quote_span` 与调用指纹而盘上两栏全空，
            # `schema._normalize_quote_mode` 就会把"只说了通过"的行记实成 `verbatim`
            # —— 于是"逐字回验通过"这句话在盘上没有任何读数。
            # 这里只搬，不判：缺证据那一档由 `quoteevidence.enforce_quote_evidence`
            # 在写库前处理（`register_statement` 的写侧断言），读侧判据是
            # `quoteevidence.scan_quote_evidence`。
            quote_mode=_s("quote_mode"), quote_span=_s("quote_span"),
            quote_call_sha256=_s("quote_call_sha256"),
            evidence_kind=_s("evidence_kind") or "heuristic", status="active",
            derived_from=S.sorted_unique([str(x) for x in (body.get("derived_from") or [])]),
            aliases=[str(a) for a in (body.get("aliases") or []) if str(a).strip()],
            # `line_range` 是字符串（"120-148"），不是 `PageRange` —— 走 `_rng(...)` 会让
            # 落盘那一格是一个 `{start/end/label}` 的字典（`Statement` 的声明是 `str`）。
            # 判据抓不到它（`to_dict` 照抄、`verify` 不查那一格），但下游按"行范围"
            # 读它的人会拿到一个字典。
            doc_id=_s("doc_id") or None, line_range=_lines("line_range"),
            # ---- `bits` 必须 10 键齐、没有 None -------------
            #
            # `dict(body.get("bits") or {})` 在调用方没交 `bits` 时落盘的就是 `{}`，而
            # `bits_shape_problems({})` 返回 `[]`（空表被当成"没有形状问题"）⇒ 一条
            # 整块没填 `bits` 的行照样过闸。现在"缺就现算、算不齐就拒"，
            # 判据见 `_complete_statement_bits`。
            bits=_complete_statement_bits(body, kind=kind, origin=origin),
            created_at=S.now_iso(),
            created_by=f"secretary-{self.role}")


#: 谁可以交命题内容给这一条路径（写入侧是 B 的活，别的人交 ⇒ 受控拒绝）。
STATEMENT_WRITER_ROLES: tuple[str, ...] = ("B",)


#: `table.update(table="statements")` 允许就地改的非正文三格。
#:
#: 为什么只有这三格：B 这一趟想改的三件事就是它们；改正文有专门的登记路（重交一条
#: 带新 `statement_full` / `proof_text` 的登记，旧正文进 `proof_history`）。
#: 白名单之外的键一律受控拒绝 —— 这里放宽一个词，等于放宽一整类写口，而
#: 「谁能改 statements 的哪一格」是 FC-27 的权限面（`tools/table_tools.py` 也是禁改区）。
STATEMENT_META_PATCH_KEYS: tuple[str, ...] = ("status", "kind", "quote_reason")


#: 放弃/换号时随 `status="abandoned"` 一起交上来的那几格。
#:
#: 它们不是就地改的字段（一个字节都不会落进 row 的顶层键）：它们是"理由"的
#: 结构化形状，由 `statementabandon.check_abandon_reason` 判过之后拼进
#: `quote_reason` 那一条标记里（`abandoned@<ISO8601>@<JSON>`）。所以它们在白名单里
#: （放行到这一层）却不在 `STATEMENT_META_PATCH_KEYS` 里（不被当作可写列）。
#:
#: 为什么必须在这一层就拒：`table.update` 是业主验收的通用写口，模型真会用它；
#: 而"受控拒"要求一个字节都不写 ⇒ 校验必须赶在 `tx.upsert` 之前。
STATEMENT_ABANDON_PATCH_KEYS: tuple[str, ...] = (
    "abandon_kind", "abandon_basis", "defect_ref", "difficulty", "salvaged",
    # E 侧那两档的按档证据（反例 / 枚举空间过于宏大）：
    # `experiment_id` 指一条真的证否实验；`space` 是一份结构化的枚举参数与规模读数。
    "experiment_id", "space")


#: 另外两个终态（2026-11-13 业主裁定）随 `table.update` 交上来的那几格。
#:
#: - `status="refuted"`（标记为错误）：证据三选一 —— `defect_ref` / `construction` /
#:   `experiment_id`（前两格里的 `defect_ref` / `experiment_id` 与放弃那几格同名同义，
#:   所以只在下面补 `construction` 与 `counterexample_valid`），理由正文复用
#:   `abandon_basis`；
#: - `hard_to_prove`（「难以自证」）：它的值是那句理由，另可给 `proof_no` 指哪一份
#:   （缺省 1：引文侧的行只有一份证明）。
#:
#: 与 `STATEMENT_ABANDON_PATCH_KEYS` 同一条纪律：它们不是可写列，判过之后落进
#: `bits` / `quote_reason` 的口袋里；多给一格就受控拒（一个字节都不写）。
STATEMENT_RETIRE_PATCH_KEYS: tuple[str, ...] = (
    "construction", "counterexample_valid", "hard_to_prove", "proof_no")


#: 就地改 `kind` 时认的英文词表（命题性的那几档 + 概念/定义两档）。
#:
#: 中文 kind（`定理` / `引理`）不在里面：它进不了命题性词表、
#: 也不在猜想白名单，而拒因说的是另一件事（去要 V 签）。这一格把"不是取值"说清。
STATEMENT_META_KINDS: tuple[str, ...] = PROPOSITION_KINDS + NOT_APPLICABLE_KINDS


#: 经 :meth:`Secretary.land_statement` 落盘的两类操作各自允许改哪几格（权限面，写死在这一层）。
#:
#: 为什么需要这一格（B 实际只有台账的只读权限；B 的任何"写台账"的路实际都由 B 秘书洗过）：
#: B 的写侧还有两支自己开 `store.tx("statements")`
#: 落行（追加证明 / 更新数值证据位），秘书那一层一个字都没过目。收口之后 B 只交"这一笔要
#: 改成什么"，开事务、读现行行、判"改了哪几格"、写盘四件事都在秘书这一层；这张表是第三件
#: 的判据：
#:
#: - `attach_proofs`：B 追加证明（`#p2` 及以后进 `proofs`）、换 canonical 正文（`proof_text`
#:   ＋旧正文进 `proof_history`）、按签/形式化同步五元位与等级、按证据升 `kind`、写收录回执；
#: - `numeric_evidence`：只动五元位（第 1 位 `numeric` ＋ 它的凭据流水 ＋ `grade`）。
#:
#: 不在表里的格一律改不动（`statement_patch_key_not_allowed`，一个字节都不写）：正文的真身
#: `statement_full`、出处面（`source_lit_id` / `page_range` / `doc_id` / `line_range`）、
#: 创建留痕（`stmt_id` / `created_at` / `created_by`）都在"改不动"那一侧。
#:
#: `proofs` / `_grade_recomputed` 这两格是 `verifications` 的键（`PROOFS_KEY` /
#: `GRADE_RECOMPUTED_KEY`），`_kind_upgrade` 与 `verifications._kind_upgrade_from_signature`
#: 写的是同一格；三处逐字同一套由 `tests/test_b_never_writes_statements_directly.py` 钉着
#: （本文件不在 import 期读 `verifications` —— 它会反过来读本文件）。
STATEMENT_LAND_OPS: dict[str, tuple[str, ...]] = {
    "attach_proofs": (
        "proof_text",           # #p1 的正文（canonical）
        "proof_history",        # 被换掉的旧正文
        "proofs",               # #p2 及以后的清单（`verifications.PROOFS_KEY`）
        "bits",                 # 五元位（含认签表 / 优化态 / 形式化 / `grade`）
        "kind",                 # 按证据升档（`evidencebits.kind_following_grade`）
        "_kind_upgrade",        # 升档留痕
        "proof_no",             # 收录回执（这一行现在是第几份证明）
        "proof_sha256",         # 收录回执（这一份正文的指纹）
        "manuscript_id",        # 收录回执（这份稿的 F 稿号；稿名不再与命题号绑定）
        #: K6②（2026-11-18）：稿身份 = `(族, 稿号)`。`manuscript_id` 是裸号，跨族会撞
        #: （盘上实测 stmt 000032 的 000000 是 b-proof、stmt 000040 的 000000 是
        #: f-proof）；`manuscript_family` 与它同一笔写，读侧合成 `(族, 稿号)`。
        "manuscript_family",
        # 逐路径的稿（2026-11-13，V1-A）：`{路径号: 稿路径}`。收录回执写 `manuscript_id`
        # 时同一笔写这一格 —— 它是"这一条命题的每条路径各是哪份稿"的落点，`manuscript_id`
        # 只有一格、会被第 2 条路径覆写。只由 `agent_b/proof_receipt.write_proof_receipt`
        # 写，读口是 `manuscriptpaths.path_reading`。
        "manuscripts",
        # 逐路径那份稿的字节 sha（2026-11-26 BEARINGDEF；信息读数，不拦门）：
        # `{路径号: sha256}`，与 `manuscripts` 同键。写口只有一处
        # （`manuscriptpaths.record_manuscript`，收录回执 / 落稿 / 补空号三路共用）；
        # 业主 2026-11-26 更正：稿号与命题号不同轴，洗稿合法 ⇒ 它不当身份、不当判据。
        "manuscript_sha256",
        # 「引文第几遍载体」的落盘标记（2026-11-18，VPLACE1）：形状由
        # `evidencebits.quote_carrier_mark` 定义、读口只有一个
        # （`evidencebits.quote_carrier_reading`）。只由 B 登记那一笔写：
        # `first` = 引文录入的逐字摘录（免 V 签），`second` = 改写 / 优化那一版。
        "quote_carrier",
        "_grade_recomputed",    # 按签重算等级的读数（`verifications.GRADE_RECOMPUTED_KEY`）
    ),
    "numeric_evidence": ("bits",),
}
