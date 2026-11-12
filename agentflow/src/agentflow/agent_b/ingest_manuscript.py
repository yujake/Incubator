"""角色 B 的动作 `own.ingest_manuscript`：按「位置 + 格」从手稿里提取并回填（T1 的唯一入口）。

提取只在秘书层（`Secretary.extract_manuscript`），本动作不切节、不解析依赖表、不读稿头；
写库仍只走 `record_statement` / `land_statement` / `amend_statement_meta` 这三个既有口。
一个动作一个文件 —— 本类只由 `agent_b/register_statement.py` 的 `_RegisterStatement`
混入，成员装配面在 `core.py`。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from ._support import _norm_manuscript_rel
from .. import manuscriptfamily as _MFAM
from .. import manuscriptintake as _MI

#: `own.ingest_manuscript` 的三种模式（设计 §2.3.1）：预览 / 回填 / 登记新命题。
#: 与 `manuscriptintake.INGEST_MODES` 同一份口径（不各写各的）。
INGEST_MODES: tuple[str, ...] = _MI.INGEST_MODES


class _IngestManuscript:
    def ingest_manuscript(self, *, manuscript: str, target_stmt_id: str = "",
                          cells: Sequence[str] = (), conflict: str = "refuse",
                          mode: str = "apply", proof_no: Any = None,
                          if_match_proof_sha256: str = "", reason: str = "",
                          provenance: Any = None) -> dict:
        """按「位置 + 格」从手稿里提取并回填（T1 的唯一入口）。

        参数（设计 §2.3.1；工具面的 ActionSpec 是这一份的广告）：`manuscript` 是工作区
        相对路径、只收 `reports/` 下过族表的规范名；`target_stmt_id` 是位置（录到哪一条
        命题，`mode!="register"` 时必填）；`proof_no` 是旧调用面留下的那一格 —— 产出侧
        不写「证明号」，路径号由秘书在收录事务里分配，所以这一格只校验形态（>=1 的整数），
        不参与定号（稿名里的 `-p<N>` 也不再比对）；
        `cells` 是格（闭集），派生列请求 ⇒ 受控拒 `derived_cell_not_requestable`；
        `conflict` 是 `refuse`（默认）/ `overwrite` / `append` / `keep`；`mode` 是
        `preview`（只提取、零写）/ `apply`（按格回填）/ `register`（登记新命题）；
        `if_match_proof_sha256` 是调用方"我以为这一行现在的正文 sha 是它"，不符 ⇒
        `stale_target`（写入方带 sha，不符受控拒、不静默覆盖）。

        三条边界：提取只在秘书层（本方法不切节、不解析依赖表、不读稿头）；写库仍只有
        `record_statement` / `land_statement` / `amend_statement_meta`；`mode=apply`
        刻意不跑同一性判定（判了就可能并到调用方没点名的行）。

        返回固定键：`ok / mode / manuscript / target / requested_cells / cells / diff /
        derived_write / write / refused / reason`。`diff` 是"请求格 vs 实填格"的逐格
        对拍；I1/I2 由 `_ingest_invariant_problem` 机器核（不成立 ⇒ 整笔 `ok=False`）。
        """
        from .. import manuscriptfamily as _MFAM
        from .. import manuscriptintake as _MI

        rel = _norm_manuscript_rel(manuscript)
        out = self._ingest_empty_envelope(rel, mode)

        # ---- 参数面（先判再读盘：拒绝要能把改法说清）
        if str(mode or "") not in INGEST_MODES:
            return self._ingest_fail(
                out, "bad_ingest_mode",
                f"`mode` 只有 {INGEST_MODES}（收到 {mode!r}）")
        if str(conflict or "") not in _MI.CONFLICTS:
            return self._ingest_fail(
                out, "bad_conflict_policy",
                f"`conflict` 只有 {_MI.CONFLICTS}（收到 {conflict!r}）")
        requested, _code, _why = self._ingest_requested_cells(cells, str(mode))
        if _code:
            return self._ingest_fail(out, _code, _why)

        # ---- 族 / 目录：目录是身份的一部分（legacy 只可 preview）
        family, tier, _code, _why = self._ingest_family_reading(rel, str(mode), out)
        if _code:
            return self._ingest_fail(out, _code, _why)

        # ---- 位置：register 不收 target；其余模式 target 是权威
        target = str(target_stmt_id or "").strip()
        if str(mode) == "register":
            if target:
                return self._ingest_fail(
                    out, "target_not_allowed_for_register",
                    "`mode=register` 是登记**新**命题：`target_stmt_id` 必须空"
                    "（录到在册行请用 `mode=apply`）")
            if family not in ("f-proof", "e-proof", "e-num"):
                return self._ingest_fail(
                    out, "register_not_applicable_for_family",
                    (f"{family or '这一族'} 的稿对应的是**已登记**的命题 ⇒ 不能登记新命题；"
                     "B 自己的改写稿走 `own.register_statement` 的正文支"))
            defaults = list(_MFAM.default_cells(family))
            requested = requested or list(defaults)
            missing = [cell for cell in defaults if cell not in requested]
            if missing:
                return self._ingest_fail(
                    out, "cells_incomplete_for_register",
                    (f"登记新命题要一次交齐 {defaults}（缺 {missing}）："
                     "register 那一笔按整行落库，不能只填半行"))
        else:
            if not target:
                return self._ingest_fail(
                    out, "target_required",
                    "`target_stmt_id` 是「录入位置」：apply / preview 必须点名录到哪一条命题")

        # ---- 族收窄：请求了族不允许的格 ⇒ 受控拒（点明这一族只能填哪几格）
        # legacy 只走 preview：它的格集是 ∅，但 preview 要能看清稿里有什么
        # （`_ingest_legacy_cells` 把读数原样给出，一个字节不写）。
        allowed = _MFAM.allowed_cells(family)
        for cell in (() if tier == _MFAM.TIER_LEGACY else requested):
            # `statement_full` 在 apply/preview 是"只校验"（在册行只读），任何族都收；
            # register 那一档按族表（b-proof 已在上面被拒）。
            if cell == "statement_full" and str(mode) != "register":
                continue
            if cell not in allowed:
                return self._ingest_fail(
                    out, "cell_not_applicable_for_family",
                    (f"{family} 只能填 {allowed}；`{cell}` 不在里面"
                     + ("（普通数值档 `proof_text` 按业主口径留空）"
                        if family == "e-num" and cell == "proof_text" else "")))

        # ---- 提取归秘书（B 本体不读稿）
        sec = self._statement_secretary()
        if sec is None:
            return self._ingest_fail(
                out, "secretary_unavailable",
                "这一趟没有秘书 ⇒ 读不了稿、也写不了台账"
                + (f"（{self.secretary_problem}）"
                   if getattr(self, "secretary_problem", "") else ""))
        want_cells = list(requested)
        if str(mode) == "register":
            for cell in _MFAM.default_cells(family):
                if cell not in want_cells:
                    want_cells.append(cell)
        reading = sec.extract_manuscript(rel, want_cells)
        out["manuscript"].update({
            "sha256": str(reading.get("sha256") or ""),
            "proof_sha256": str(reading.get("proof_sha256") or ""),
            "proof_state": str(reading.get("proof_state") or ""),
            "head_statement_id": str(reading.get("head_statement_id") or ""),
        })
        if not reading.get("checked"):
            return self._ingest_fail(
                out, "manuscript_unreadable",
                str(reading.get("why") or f"读不到 `{rel}`")
                + "（读不到的稿不能当成没有）")

        # ---- 稿头点名的号：target 是权威，稿头只作校验（不一致 ⇒ 拒，不重定向）
        head = str(reading.get("head_statement_id") or "").strip()
        if str(mode) != "register" and head and head != target:
            return self._ingest_fail(
                out, "manuscript_points_elsewhere",
                (f"这一份稿点的是 stmt:{head}（稿头 `- 命题号：`），而 `target_stmt_id` "
                 f"是 stmt:{target} ⇒ 整笔不写。**不重定向**：要么改稿头、要么改位置"
                 "（位置由调用方指定，工具不许替它挑一行）"))
        if head and str(mode) != "register":
            out["target"]["stmt_id"] = target

        # ---- proof_no：只校验形态；号由秘书分配（稿名里的 `-pN` 不再比对） --------
        want_no, _code, _why = self._ingest_proof_no(reading, proof_no)
        if _code:
            return self._ingest_fail(out, _code, _why)
        out["manuscript"]["proof_no"] = want_no
        if proof_no not in (None, ""):
            #: 旧口径的号：忽略，但要让读的人看见"这个号不是它给的"。
            out["proof_no_ignored"] = {
                "given": str(proof_no), "by": "调用方",
                "why": "号由秘书在收录事务里分配；调用方给的这个数不采信",
            }

        # ---- 目标行（apply / preview 必须已在册；register 没有目标行）
        row: dict | None = None
        if str(mode) != "register":
            row, _code, _why = self._ingest_target_row(
                out, target, str(if_match_proof_sha256 or ""))
            if _code:
                return self._ingest_fail(out, _code, _why)

        # ---- legacy 只可 preview：把提取读数原样给出（每格 not_applicable + 理由）
        if tier == _MFAM.TIER_LEGACY:
            cells_out = self._ingest_legacy_cells(reading, requested)
            out.update(requested_cells=list(requested), cells=cells_out,
                       derived_write=[])
            out["diff"] = {"requested_not_filled": [], "filled_not_requested": []}
            out.update(ok=True, reason="历史档：只预览、不写（不可签、不可收录）")
            return out

        # ---- mode=register：登记新命题（继承"按手稿路径收录"那条路）
        if str(mode) == "register":
            got = self._ingest_register(
                reading=reading, requested=requested, out=out, family=family,
                path=rel, provenance=provenance)
            _pg_reg = got.get("path_group")
            _pg_reg_no = (int((_pg_reg or {}).get("path_group") or 0)
                          if isinstance(_pg_reg, Mapping) else int(_pg_reg or 0))
            return self._mark_ingested(got, rel=rel, family=family,
                                       path_group=_pg_reg_no)
        path_no, _code, _why = 0, "", ""
        got_cells = {cell: reading["cells"][cell]
                     for cell in requested if cell in (reading.get("cells") or {})}
        plan = _MI.plan_cells(
            row, got_cells, str(conflict), family=family, proof_no=int(want_no or 1),
            append_new_path=self._ingest_new_proof_path(
                mode=str(mode), row=row, target=target, rel=rel, got_cells=got_cells))
        cells_out = self._ingest_plan_cells(plan, requested)
        out.update(requested_cells=list(requested), cells=cells_out,
                   derived_write=list(plan.get("derived_write") or []),
                   refused=str(plan.get("refused") or ""),
                   reason=str(plan.get("reason") or ""),
                   ok=bool(plan.get("ok")))
        out["diff"] = self._ingest_diff(out, requested)
        problem = self._ingest_invariant_problem(out)
        if problem:
            return self._ingest_fail(out, "ingest_invariant_violated", problem)
        if not out["ok"]:
            return out
        if str(mode) == "preview":
            out["write"] = {"statements": False, "dependencies": False,
                            "written": False,
                            "sink": "preview：只提取、一个字节都不写"}
            return out
        got = self._ingest_apply(
            reading=reading, row=row, plan=plan, out=out, requested=requested,
            family=family, want_no=want_no, target=target, path=rel)
        _pg = got.get("path_group")
        _pg_no = int((_pg or {}).get("path_group") or 0) if isinstance(_pg, Mapping) else int(_pg or 0)
        return self._mark_ingested(got, rel=rel, family=family, path_group=_pg_no)

    def _ingest_new_proof_path(self, *, mode: str, row: Mapping, target: str,
                               rel: str, got_cells: Mapping) -> bool:
        """这一份是同一命题的另一条证明路径吗（换了稿 / 换了正文）？

        判据与登记那一支同一处（`_rewrite_is_the_same_proof`：同一份稿改正文 ⇒ 改稿；
        换稿 ⇒ 新路径）。只决定"计划说追加还是冲突"，不决定路径号（号归秘书）。
        """
        value = str((got_cells.get("proof_text") or {}).get("value") or "")
        return bool(
            str(mode) == "apply" and row is not None and value.strip()
            and str(row.get("proof_text") or "").strip()
            and not self._rewrite_is_the_same_proof(
                stmt_id=target, row=row, manuscript_path=rel, proof_text=value))

    def _mark_ingested(self, out: dict, *, rel: str, family: str,
                       path_group: int = 0) -> dict:
        """收录成功之后：B 自己的 `b-proof` 稿在 B 那一行 task 上置「已提交」。

        业主 2026-11-11 裁定 ③：「如果产出方是 B，则该在它将稿存进台账时更新状态为
        已提交」。只加一枚 `mss:` 记号（格式复用 F 那一套），台账业务字段一个不动；
        受控拒 / 别的族 / 没有 task 行 ⇒ 原样返回并把理由写进 `b_submission`。

        同一笔里把秘书分配的路径号回写到覆盖这份正文的 `verifications` 行：
        两件事都在"收录成功"这一刻发生，不另查一遍台账（号从回执里来，不在这里算）。
        """
        from . import autosubmit as _BAS

        if bool(out.get("ok")) and int(path_group or 0) >= 1:
            from .. import manuscriptsubmission as _MSUB
            from .. import proofregistry as _PR

            body_sha = str((out.get("manuscript") or {}).get("proof_sha256") or "")
            if not body_sha:
                body_sha = _PR.proof_sha(str(
                    (out.get("cells", {}).get("proof_text") or {}).get("value") or ""))
            out["path_group_stamp"] = _MSUB.stamp_verification_path_group(
                root=getattr(self.store, "root", ""),
                statement_id=str((out.get("target") or {}).get("stmt_id") or ""),
                body_sha=body_sha, manuscript=rel, path_group=int(path_group))
        return _BAS.mark_b_ingested(
            self.store, getattr(self.store, "root", ""), manuscript=rel,
            family=family, out=out)
