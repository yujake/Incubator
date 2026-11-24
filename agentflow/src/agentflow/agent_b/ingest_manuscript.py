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


def _path_group_parameter(value: Any, mode: str) -> tuple[int, str, str]:
    """`path_group` 参数面 ⇒ `(路径号, 受控码, 人话)`（码空 = 过关）。

    只在 `mode=apply` 的优化线上收：它点名的是一条已存在的路径，回填才用得上；
    预览 / 登记没有「换第 N 份」这件事。`0` = 老调用面（不提路径）。
    """
    try:
        named = int(value or 0)
    except (TypeError, ValueError):
        return 0, "bad_path_group", f"`path_group` 必须是整数（收到 {value!r}）"
    if named < 0:
        return 0, "bad_path_group", f"`path_group` 必须 >= 0（收到 {named}）"
    if named >= 1 and mode != "apply":
        return named, "path_group_not_allowed_for_mode", (
            "`path_group` 只在 `mode=apply` 的优化线上收：它点名的是一条已存在的"
            "路径，回填才用得上；预览 / 登记没有「换第 N 份」这件事")
    return named, "", ""


def _ingested_statement_id(out: Mapping[str, Any]) -> str:
    """这一笔收录落在哪一条命题上（登记支 `register` / 回填支 `target` 各一格）。

    空串 = 这一笔没有命题号。两个支的读数形状不同、号只在同一个键上，所以取法
    只有这一处：调用方拿它去回写认领（`_bind_ingested_claim`）与收口义务
    （`_settle_registration_duty`）时读的是同一个号。
    """
    for one in ((out or {}).get("register"), (out or {}).get("target")):
        if isinstance(one, Mapping):
            stmt_id = str(one.get("stmt_id") or "").strip()
            if stmt_id:
                return stmt_id
    return str((out or {}).get("stmt_id") or "").strip()


class _IngestManuscript:
    def ingest_manuscript(self, *, manuscript: str, target_stmt_id: str = "",
                          cells: Sequence[str] = (), conflict: str = "refuse",
                          mode: str = "apply", proof_no: Any = None,
                          path_group: int = 0,
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
        `path_group`（2026-11-12 业主裁定「换正文只允许优化这条线去换」）：优化线
        显式点名的已存在路径号（`>=1`）。它不分配号 —— 秘书在事务里核"第 n 条
        路径在册、且这一份稿对得上它"，核不过 ⇒ 受控拒 `path_not_found` /
        `path_mismatch`。普通登记一律不传（`0`）；带它才是"换第 N 份正文"那条线。
        `if_match_proof_sha256` 是调用方"我以为这一行现在的正文 sha 是它"，不符 ⇒
        `stale_target`（写入方带 sha，不符受控拒、不静默覆盖）。

        三条边界：提取只在秘书层（本方法不切节、不解析依赖表、不读稿头）；写库仍只有
        `record_statement` / `land_statement` / `amend_statement_meta`；`mode=apply`
        刻意不跑同一性判定（判了就可能并到调用方没点名的行）。

        返回固定键：`ok / mode / manuscript / target / requested_cells / cells / diff /
        derived_write / write / refused / reason / caller_reason`。`diff` 是"请求格 vs 实填格"的逐格
        对拍；`caller_reason` 原样带回调用方那一句「为什么录」（不参与判据）；I1/I2 由
        `_ingest_invariant_problem` 机器核（不成立 ⇒ 整笔 `ok=False`）。
        """
        from .. import manuscriptfamily as _MFAM
        from .. import manuscriptintake as _MI

        rel = _norm_manuscript_rel(manuscript)
        out = self._ingest_empty_envelope(rel, mode)
        #: 调用方那一句「为什么录」：读数不是判据（与失败那一格 `reason` 分开）。
        out["caller_reason"] = str(reason or "")
        #: 判/落拆段的回传槽（NT2）：判在写之前（`_ingest_register` / `_ingest_apply`
        #: 的第一件事），落在拿到 `stmt_id` + `path_group` 之后；这一层只负责收尾。
        _nt: dict = {}

        # ---- 参数面（先判再读盘：拒绝要能把改法说清）
        if str(mode or "") not in INGEST_MODES:
            return self._ingest_fail(
                out, "bad_ingest_mode",
                f"`mode` 只有 {INGEST_MODES}（收到 {mode!r}）")
        if str(conflict or "") not in _MI.CONFLICTS:
            return self._ingest_fail(
                out, "bad_conflict_policy",
                f"`conflict` 只有 {_MI.CONFLICTS}（收到 {conflict!r}）")
        named_path, _path_code, _path_why = _path_group_parameter(
            path_group, str(mode or ""))
        if _path_code:
            return self._ingest_fail(out, _path_code, _path_why)
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
        })
        if not reading.get("checked"):
            return self._ingest_fail(
                out, "manuscript_unreadable",
                str(reading.get("why") or f"读不到 `{rel}`")
                + "（读不到的稿不能当成没有）")

        # 稿里没有命题号（业主 2026-11-13 裁定逐字：「稿里没有命题号，任何稿里都没有
        # 命题号」）⇒ 位置只由调用方的 `target_stmt_id` 回答，不再拿稿头做第二来源；
        # 改前那一支「稿头与 target 不一致 ⇒ manuscript_points_elsewhere」随之删除：没有
        # 第二个来源，就没有"两个来源不一致"这件事可判。

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
                path=rel, provenance=provenance, nontriviality=_nt)
            _pg_reg = got.get("path_group")
            _pg_reg_no = (int((_pg_reg or {}).get("path_group") or 0)
                          if isinstance(_pg_reg, Mapping) else int(_pg_reg or 0))
            return self._finish_filing_nontriviality(
                self._mark_ingested(got, rel=rel, path_group=_pg_reg_no), _nt)
        path_no, _code, _why = 0, "", ""
        got_cells = {cell: reading["cells"][cell]
                     for cell in requested if cell in (reading.get("cells") or {})}
        _plan = self._ingest_plan(
            row, got_cells, conflict=str(conflict), family=family, target=target,
            rel=rel, requested=requested, out=out, named_path=named_path,
            want_no=want_no, mode=str(mode))
        if _plan.get("fail"):
            return _plan["fail"]
        plan = dict(_plan["plan"])
        if str(mode) == "preview":
            out["write"] = {"statements": False, "dependencies": False,
                            "written": False,
                            "sink": "preview：只提取、一个字节都不写"}
            return out
        got = self._ingest_apply_with_nontriviality(
            reading=reading, row=row, plan=plan, out=out, requested=requested,
            family=family, want_no=want_no, target=target, path=rel,
            path_group=named_path, nontriviality=_nt)
        _pg = got.get("path_group")
        _pg_no = int((_pg or {}).get("path_group") or 0) if isinstance(_pg, Mapping) else int(_pg or 0)
        return self._finish_filing_nontriviality(
            self._mark_ingested(got, rel=rel, path_group=_pg_no), _nt)

    def _ingest_intake_register(self, out: dict, *, rel: str, family: str,
                                target: str, reading: Mapping) -> dict | None:
        """登记"这一笔收编是我做的"（K17）；判据没查成 ⇒ 受控拒（判不了 ≠ 可以写）。

        两个会写库的出口（`_ingest_register` 与 `_ingest_apply_with_nontriviality`）
        各自在写之前调一次 —— `ingest_manuscript` 本体已经贴着 200 行的体量线，
        再塞一段进去会抬 `repo_survey` 的 long_defs 计数（仓库硬门 95 不许抬）。
        `preview` 零写、不登记；`legacy` 只预览，在调用点之前早退。

        ## 为什么收编也要登记（`MASTER-INVENTORY` K17 / BR-06）

        改前 B 收编一份 F/E 稿时，盘上只多出 `statements` 行里的 `manuscripts`
        （`{path_group: rel}`）与 `verifications` 行上的路径号 —— 回答不了
        "这一份稿是谁收的、收的是哪一版"。两个 B 实例各收一份稿时，回执与落点
        都只剩一个路径字符串。现在每写库一笔就落一条收编占用：键 `intake:<rel>`、
        holder 带 `owner` / `instance` / `sha256` / `family` / `target`，回执原样带回
        工具返回（`out["intake_claim"]`）。

        ## 为什么它不挡 F/E 的写者登记

        占用判据只有 `manuscriptids.claim_for_write` 一处，但"谁写这份稿"与"谁收编
        这份稿"是两个问题、两个命名空间（`purpose`）。F 早就在 `rel` 上登记成写者，
        B 若用同一个键会被判成 `other`；收编那一档因此走 `claim_intake`
        （`purpose="intake"` + `takeover=True`：收编是事件，后来的那一笔覆盖并把
        上一笔的 holder 带回来）。

        身份从 `identity.resolve_identity(self.store, "B", actor=self.actor)` 取 ——
        与 B 的写稿支（`_land_b_manuscript`）同一处，不另拼一份。
        """
        from .. import identity as _IDENT
        from .. import manuscriptids as _MID

        actor = str(getattr(self, "actor", "") or "")
        ident: Mapping = {}
        try:
            ident = _IDENT.resolve_identity(self.store, "B", actor=actor)
        except Exception as exc:  # noqa: BLE001 —— 身份读不成只让 claim 以 actor 顶上
            ident = {"actor": actor, "attributed": False,
                     "conflict": f"{type(exc).__name__}: {exc}"}
        owner = str(ident.get("actor") or actor or "").strip()
        claim = _MID.claim_intake(
            getattr(self.store, "root", ""), rel,
            owner=owner, role="B",
            task_id=str(ident.get("task_id") or ""),
            instance=str(ident.get("instance") or ""),
            identity=ident,
            sha256=str((reading or {}).get("sha256") or ""),
            family=str(family or ""), target=str(target or ""))
        out["intake_claim"] = dict(claim)
        if not claim.get("checked"):
            return self._ingest_fail(
                out, "intake_claim_unchecked",
                "这一笔的收编占用没登记成（"
                + str(claim.get("why") or "没有原因")
                + "）⇒ 这一笔不写库：判不了这一份稿归谁，就不落库")
        return None

    def _ingest_plan(self, row: Mapping | None, got_cells: Mapping, *,
                     conflict: str, family: str, target: str, rel: str,
                     requested: Sequence[str], out: dict, named_path: int,
                     want_no: int, mode: str) -> dict:
        """计划 + 逐格回执 + I1/I2 不变量（返回 `{"plan": …}` 或 `{"fail": 受控拒}`）。"""
        #: 优化线：计划按"覆盖这一格"走（它不分配号、也不比对号）；号由秘书核、
        #: 能不能换由写口按新正文的 V 签判。登记线的冲突矩阵逐字不变。
        plan_conflict = "overwrite" if named_path else str(conflict)
        plan = _MI.plan_cells(
            row, got_cells, plan_conflict, family=family,
            proof_no=(1 if named_path else int(want_no or 1)),
            append_new_path=(False if named_path else self._ingest_new_proof_path(
                mode=mode, row=row, target=target, rel=rel, got_cells=got_cells)))
        cells_out = self._ingest_plan_cells(plan, requested)
        out.update(requested_cells=list(requested), cells=cells_out,
                   derived_write=list(plan.get("derived_write") or []),
                   refused=str(plan.get("refused") or ""),
                   reason=str(plan.get("reason") or ""),
                   ok=bool(plan.get("ok")))
        out["diff"] = self._ingest_diff(out, requested)
        problem = self._ingest_invariant_problem(out)
        if problem:
            return {"fail": self._ingest_fail(out, "ingest_invariant_violated", problem)}
        if not out["ok"]:
            return {"fail": out}
        return {"plan": plan}

    def _ingest_new_proof_path(self, *, mode: str, row: Mapping, target: str,
                               rel: str, got_cells: Mapping,
                               path_reading: Mapping | None = None) -> bool:
        """这一份是同一命题的另一条证明路径吗（换了稿 / 换了正文）？

        判据与登记那一支同一处（`_proof_path_reading`：同一份稿改正文 ⇒ 改稿；
        换稿 ⇒ 新路径）。只决定"计划说追加还是冲突"，不决定路径号（号归秘书）。
        调用方已经算过那份读数就传进来（同一笔里不读两遍）。
        """
        value = str((got_cells.get("proof_text") or {}).get("value") or "")
        if str(mode) != "apply" or row is None or not value.strip():
            return False
        if not str(row.get("proof_text") or "").strip():
            return False
        reading = dict(path_reading or {})
        if not reading:
            reading = self._proof_path_reading(
                stmt_id=target, row=row, manuscript_path=rel, proof_text=value)
        return not bool(reading.get("same_proof"))

    def _bind_ingested_claim(self, out: dict) -> dict:
        """收录落成之后：把这一笔认到的那一签绑到命题号上（回写 pending 台账行）。

        ## 为什么补这一拍（2026-11-20，BWRITE；真机 `projects/lp-ball-10` 的 stmt:000015）

        主路是「先签后收录」：V 在命题还没号时审、签落
        `verifications/pending/<载体 sha>.jsonl`（`verifications.record_pending_sign`）。
        `mode=apply` 这一笔会调 `vsigns.bits_after_sign`（唯一的认签口）把那一签认到
        第 3 位 —— 认得不差：行上 `bits.evidence.reviewed_by.evidence` 就指着
        `verifications/pending/<sha>.jsonl#u-…`。可它交回来的 `claim` 只被读成了回执
        （`out["evidence"]["sign_claim"]["claim"]`），没有写回 pending 行。

        改前唯一调 `vsigns.bind_pending_claim` 的地方是 `register_statement` 的
        「新建」支（号有了、`bits.reviewed` 为真时）。于是"先登记、后收录"这条路
        （lp-ball-10 的现场：13:39 落 4 行 pending，13:46 登记，13:47 用
        `own.ingest_manuscript` 把签收进 000015#p1）从头到尾没有回写 —— 盘上那 4 行
        `statement_id` / `stmt_id` 全空，`verifications._claimed_pending_rows` 认不到它，
        V2FIX 第二路（`unverified_statement_refs`）照旧记 `missing`：签在盘上、号在
        行上，两个从不相遇。

        ## 判据（一条，不在这里另立口径）

        这一笔真的落成了（`out["ok"]` 为真）、并且认签那一格交回了一份 pending 台账的
        `claim` ⇒ 交唯一写口 `vsigns.bind_pending_claim` 去绑。它自己判"同一份正文只
        认领一次"（`bound_elsewhere` / `already`）、自己拒空号 —— 本函数不判第二遍、
        不写第二份实现。

        ## 三态

        `checked=True` = 查过了（`bound` / `already` / `bound_elsewhere` / 这一笔没有
        pending 认领）；`checked=False` = 没写成（没落成 / 没有号 / 写口读不出来），
        读数在 `why` 里，绝不折成"已经绑了"。

        ## 为什么写失败不把这一笔收录判死

        `land_statement` 那一笔已经提交（正文、位、等级都在盘上），把整笔改判成失败
        只会让调用方重交一次已经写好的东西。`bind_pending_claim` 是幂等的（重放那一笔
        会补上剩下的几份，见它的 `bound_files`）⇒ 读数如实留在 `pending_claim` 里，
        下一趟收录（幂等重放）自愈。这与 :meth:`_settle_registration_duty` 同一条纪律。
        """
        from .. import vsigns as _VS

        if not isinstance(out, dict):
            return out
        out["pending_claim"] = {"checked": False, "bound": False, "already": False,
                                "statement_id": "", "ledger": "", "bound_files": [],
                                "bound_elsewhere": "", "why": ""}
        evidence = out.get("evidence")
        sign_claim = dict((evidence or {}).get("sign_claim") or {}) \
            if isinstance(evidence, Mapping) else {}
        claim = dict(sign_claim.get("claim") or {})
        if not bool(out.get("ok")):
            out["pending_claim"]["why"] = (
                "这一笔没落成（ok=False）⇒ 不回写 pending 台账行：收录失败不许在盘上"
                "留下「这一签已经认给某条命题」的记号")
            return out
        if not claim:
            out["pending_claim"].update(checked=True, why=(
                "这一笔没有认到 pending 台账上的签（`evidence.sign_claim.claim` 空）"
                "⇒ 没有要回写的行"))
            return out
        stmt_id = _ingested_statement_id(out)
        if not stmt_id:
            out["pending_claim"]["why"] = (
                "这一笔拿到了 pending 认领、却没有命题号 ⇒ 不猜（不写空号冒充认领；"
                "那几行仍然算未认领）")
            return out
        try:
            bound = _VS.bind_pending_claim(
                getattr(self.store, "root", ""), claim=claim, statement_id=stmt_id)
        except Exception as exc:  # noqa: BLE001 —— 写口抛了 = 没写成，不是"已经绑了"
            out["pending_claim"]["why"] = (
                f"回写 pending 台账那一笔抛了（{type(exc).__name__}: {exc}）⇒ 没写成"
                "（这一格幂等：下一趟收录会补上）")
            return out
        out["pending_claim"].update(
            checked=bool(bound.get("checked")), bound=bool(bound.get("bound")),
            already=bool(bound.get("already")), statement_id=stmt_id,
            ledger=str(bound.get("ledger") or ""),
            bound_files=list(bound.get("bound_files") or []),
            bound_elsewhere=str(bound.get("bound_elsewhere") or ""),
            why=str(bound.get("why") or ""))
        # 认领读数并回认签那一格：`bits.evidence.reviewed_by.evidence` 指着的
        # 那一行，现在真的写着这条命题的号（同一笔里两个回执说同一句话）。
        sign_claim["claim"] = dict(
            claim, bound=bool(out["pending_claim"]["bound"]),
            bound_id=(stmt_id if out["pending_claim"]["bound"]
                      else str(out["pending_claim"]["bound_elsewhere"] or "")),
            bind=dict(bound))
        evidence = dict(evidence or {})
        evidence["sign_claim"] = sign_claim
        out["evidence"] = evidence
        return out

    def _settle_registration_duty(self, out: dict, *, rel: str) -> dict:
        """收录落成之后：把板上那条「必须收录」义务按证据收口（写点，不是等收工对账）。

        为什么写在这里而不是收工那一侧：B 收录完==义务满足了，而"收工对账"这一笔
        在本链里根本没跑（M 的脚本是「派 B → 销 B1 → final」，收工门没有调
        `obligations.reconcile`）⇒ 义务停在 `seen`、`retire_child` 受控拒、final 连拒
        三拍。RED11 的读数：`calls` 16 → 19（多出来的 3 拍全是收工补救）。

        判据与收口本体只有一处：`obligations.settle_registration`（它按"这一份稿归哪一行"
        认出义务，两个号段都对得上）。本函数只做两件事：认出这一笔拿到的命题号、
        把读数带回 `registration_settled` 那一格（失败不许带走这一笔收录）。
        """
        from .. import obligations as _OBL

        if not isinstance(out, dict):
            return out
        stmt_id = ""
        for one in (out.get("register"), out.get("target")):
            if isinstance(one, Mapping):
                stmt_id = str(one.get("stmt_id") or "").strip()
                if stmt_id:
                    break
        if not stmt_id:
            stmt_id = str(out.get("stmt_id") or "").strip()
        if not bool(out.get("ok")) or not stmt_id:
            out["registration_settled"] = {
                "checked": False, "settled": [], "left": [], "problems": [],
                "reason": ("这一笔没落成 / 没有拿到命题号 ⇒ 收不了口"
                           "（不是「没有义务」，也不是「义务还在」）")}
            return out
        try:
            got = _OBL.settle_registration(
                store=self.store, root=getattr(self.store, "root", ""),
                stmt_id=stmt_id, manuscript=rel)
        except Exception as exc:  # noqa: BLE001 —— 收口那一笔抛了不许带走这一笔收录
            got = {"checked": False, "settled": [], "left": [], "problems": [],
                   "reason": f"收口那一笔抛了（{type(exc).__name__}: {exc}）"}
        out["registration_settled"] = dict(got)
        # D 的「待递交」义务（COLLAB-E2D）：B 收录成功这一刻把 `d-handoff@<猜想号>`
        # 按证据收口。为什么挂在同一处：两个收录出口（`mode=register` 与按格回填）
        # 都从这里过，与 `b-register@` 的消账同一个落点 —— 收口不许靠"收工时有人想起来
        # 做对账"（RED11 的现场是收工对账根本没跑）。失败不许带走这一笔收录。
        try:
            settle_hand = _OBL.settle_handoff(store=self.store, stmt_id=stmt_id)
        except Exception as exc:  # noqa: BLE001 —— 收口那一笔抛了不许带走这一笔收录
            settle_hand = {"checked": False, "stmt_id": stmt_id,
                           "closed": [], "expired": [], "left": [], "problems": [],
                           "reason": f"待递交义务收口抛了（{type(exc).__name__}: {exc}）"}
        out["d_handoff_settled"] = dict(settle_hand)
        return out

    def _mark_ingested(self, out: dict, *, rel: str,
                       path_group: int = 0) -> dict:
        """收录成功之后：B 自己的 `b-proof` 稿在 B 那一行 task 上置「已提交」。

        业主 2026-11-11 裁定 ③：「如果产出方是 B，则该在它将稿存进台账时更新状态为
        已提交」。只加一枚 `mss:` 记号（格式复用 F 那一套），台账业务字段一个不动；
        受控拒 / 别的族 / 没有 task 行 ⇒ 原样返回并把理由写进 `b_submission`。

        族不再往 `autosubmit` 传：那一层按稿路径现判（`manuscriptsubmission.producer_of`）。
        改前这里收一个 `family` 形参、转发给一个同样吞掉它的形参 —— 接口看着收得下、
        实现一个字节都不认（2026-11-20 那一层删了这个形参，这里随之删掉，不留第二个假面）。

        同一笔里把秘书分配的路径号回写到覆盖这份正文的 `verifications` 行：
        两件事都在"收录成功"这一刻发生，不另查一遍台账（号从回执里来，不在这里算）。

        「必须收录」义务的消账也挂在入口这里（`_settle_registration_duty`）：两个出口
        （`mode=register` 与按格回填）都从这里过，所以义务不会因为走了哪条分支而漏收口。

        认领回写（`_bind_ingested_claim`）也挂在入口这里：`mode=apply` 把 pending 那
        一签认进第 3 位之后，命题号必须落回 pending 台账行 —— 那也是"收录成功"这一刻
        的事，且同样两个出口都从这里过（register 支没有 `evidence`，本方法自己跳过）。
        """
        from . import autosubmit as _BAS

        if isinstance(out, dict):
            self._bind_ingested_claim(out)
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
        got = _BAS.mark_b_ingested(
            self.store, getattr(self.store, "root", ""), manuscript=rel, out=out)
        # 收录成功之后把这件事记进猜想台账（业主 2026-11-13 裁定甲/①/②）。
        # 与 `register_statement` 共用同一个实现（`_note_conjecture_landing`）：
        # 收录这条路也是"B 收下了这条命题"，两个入口对台账必须说同一句话。
        if isinstance(got, dict):
            text = ""
            cells = got.get("cells") if isinstance(got.get("cells"), dict) else {}
            proof_cell = cells.get("statement_full") if isinstance(cells, dict) else None
            if isinstance(proof_cell, Mapping):
                text = str(proof_cell.get("value") or "")
            if not text:
                target = got.get("target") if isinstance(got.get("target"), dict) else {}
                text = str(target.get("statement_full") or "")
            return self._settle_registration_duty(
                self._note_conjecture_landing(got, statement_full=text, rel=rel), rel=rel)
        return got
