"""角色 B 的动作 `B.open_polish_copy`：把「原证明稿」复制成一份 B 号优化副本。

这一步解决什么：稿通过后相当于这个命题证完了，后续对稿只有只读权；"同稿号多个版本"
是错误的 —— 一个稿号相当于该稿的文件名，拿 V 签冻结后交哪份是明确的。所以"优化"必须
先分叉：复制一份、注册成新的 B 号、把复制件里的 V 签清掉（它是另一份稿，签不该跟着走）。
四步：

1. 拿到原证明稿 —— 先走已签的读口（`vsigns.signed_manuscripts`，复用 V 的颁发表）；
   没有签也照样开（业主 2026-11-14：「录入侧可能找不到素材」⇒ 优化侧不许要求
   源稿已签）：退到命题行上的 `manuscript_id` 那一份、再退到行上的 `proof_text`。
   三档都不在 ⇒ 受控拒 `no_source_draft`（"没有可复制的原稿"，一个字节都不写）；
   读数里的 `source_sign` 逐条说清源稿是哪一档（`signed` / `unsigned` / `none`）；
2. 复制一份 —— 源稿那一份文件逐字复制（一份对一份，不带 `-pN`）；源稿是行上正文
   （没有文件）时，按 `manuscriptform.render_proof_manuscript` 渲染出初始稿；
3. 注册成 B 号 —— 号由 `manuscriptids.next_manuscript_id(root, family="b-proof")`
   发（B 自己那条号段），落点 `reports/b-proof-<B稿号>.md`；
4. 清除复制版本内的 V 签 —— 删掉 `- V 签：…` 那一行（`vsigns.SIGN_MARK`）。

之后 B 在那份 B 稿上改正文（`fs.edit`），再走既有送审口派 V 三转签 —— 那一签盖的是
新正文的 sha，与源稿的签互不相干。优化是独立的一轮：`open_optimization_drafts`
按 `closing.statements_optimization_candidates` 的未优化清单批量开稿（一次调用开一批），
不需要等人点。

这一格不做什么：不改源稿一个字节（源稿的只读权由 `丁` 的三处写口守）；不把复制件写成
"已签"（清签之后它是未签的新稿）；不自己判"该优化哪一步"（那是 B 的判断，这里只负责
把材料摆到手上）；也不在收工读数里偷偷造稿（读口纯读，写盘只在动作里）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .. import manuscriptform as _MF
from .. import manuscriptids as _MID
from .. import proofregistry as _PR
from .. import vsigns as _VS
from ..agent_f.submission import POLISH_SOURCE_KIND
from ..manuscriptwrite import _atomic_write
from .optimize_prompts import optimization_prompt as _optimization_prompt


class _OpenPolishCopy:
    #: 一轮最多开几份优化稿（业主 2026-11-14 的一般性规定没有给数字；这里给一个
    #: 「轮」预算，与 `conceptrows.CONCEPTS_PER_ROUND_MAX` 同一条纪律：按轮限，
    #: 不按命题限 —— 真机 3134 条未优化命题一次全开既不安全也没必要，下一轮接着开）。
    #: 显式调用 `open_optimization_drafts(limit=0)` 可以一次开完（收工前清账用）。
    OPTIMIZATION_ROUND_MAX = 20

    def open_polish_copy(self, *, statement_id: str,
                         source_manuscript: str = "") -> dict:
        """把「这一条命题的原证明稿」复制成一份 B 号优化副本（四步见模块 docstring）。

        参数：`statement_id` 是待优化的那条命题的号（必填；它是"找哪一份稿"的唯一入口）；
        `source_manuscript` 可以不给 —— 不给就按「已签的稿 → 行上稿号 → 行上正文」三档
        找原稿；给了就必须是盘上那一份（签过的按签核 sha，没签的按"没有可核的签"放行并
        在 `source_sign` 里如实记 `unsigned`）。

        ## 源稿三档（业主 2026-11-14：「录入侧可能找不到素材」）

        `source_sign` 回答"这份原稿是哪一档"：
        - `signed`：V 的颁发表里有它、且那一签盖的是现在这一版正文；
        - `unsigned`：盘上有稿 / 行上有正文，但没有签（优化侧不要求源稿已签）；
        - `none`：三档都没有 ⇒ 受控拒 `no_source_draft`（"没有可复制的原稿"）。
        三态不折平：`none` 是"没有原稿"，不是"没查成"（那两档 `checked=False`）。

        返回（键固定）：`{ok, checked, refused, why, source_path, source_kind,
        source_manuscript_id, source_sign, source_sign_sha, source_body_sha,
        source_text_sha256, path, manuscript_id, copy_body_sha, copy_text_sha256,
        cleared, cleared_lines, signed_before, signed_after, sign_block, matched_by}`。
        受控拒时 `path` 为空、盘上一个字节都没写。`matched_by` 是"源稿是哪一条证据认出来
        的"：`"statement_manuscript_id"` 表示第 ④ 条（命题行上的 `manuscript_id`）；
        `"statement_proof_text"` 表示源稿是行上的正文（没有文件可复制，按同一份正文渲染
        初始稿）；前三条老证据命中时仍为空串。`cleared` 是删掉了几行 `- V 签：…`
        （正常是一行；历史稿可能不止一行）。
        """
        out: dict[str, Any] = {
            "ok": False, "checked": True, "refused": "", "why": "",
            "source_path": "", "source_kind": "", "source_manuscript_id": "",
            "source_sign": "", "source_sign_sha": "",
            "source_body_sha": "", "source_text_sha256": "",
            "path": "", "manuscript_id": "", "copy_body_sha": "",
            "copy_text_sha256": "", "cleared": 0, "cleared_lines": [],
            "signed_before": False, "signed_after": False, "sign_block": {},
            "matched_by": "",
        }
        sid = str(statement_id or "").strip()
        if not sid:
            return self._polish_refusal(
                out, "statement_missing",
                why="`open_polish_copy` 要指定一条命题（`statement_id`）：优化副本是"
                    "「这一条命题那份原证明稿」的副本，没有命题号就不知道复制哪一份")
        store = getattr(self, "store", None)
        root = getattr(store, "root", "") or ""
        if not root:
            out["checked"] = False
            return self._polish_refusal(
                out, "no_workspace",
                why="这一趟没有工作区根 ⇒ 读不到颁发表、也写不出副本（不是「没有原稿」）")

        # ---- ① 拿到原稿：已签的稿 → 行上稿号 → 行上正文（三档，见 docstring） ------
        picked = self._polish_source(root, sid, source_manuscript)
        if not picked.get("found"):
            out.update(source_path=str(picked.get("path") or ""),
                       source_sign_sha=str(picked.get("sign_sha") or ""),
                       sign_block=dict(picked.get("block") or {}))
            return self._polish_refusal(
                out, str(picked.get("refused") or "no_source_draft"),
                why=str(picked.get("why") or ""))
        src_rel = str(picked.get("path") or "")
        src_sign = str(picked.get("source_sign") or "signed")
        sign_sha = str(picked.get("sign_sha") or "")
        text = str(picked.get("text") or "")
        block = dict(picked.get("block") or {})
        try:
            src_mid = str(_VS.manuscript_id_of(src_rel) or "") if src_rel else ""
        except Exception:  # noqa: BLE001 —— 认不出号不带走复制（来源记录会退到 stmt:）
            src_mid = ""
        out.update(source_path=src_rel,
                   source_kind=str(picked.get("source_kind") or ""),
                   source_manuscript_id=src_mid,
                   source_sign=src_sign,
                   source_sign_sha=sign_sha,
                   source_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                   source_body_sha=_PR.proof_sha(_VS.manuscript_proof_body(text)),
                   sign_block=block,
                   signed_before=(src_sign == "signed"),
                   matched_by=str(picked.get("matched_by") or ""))

        # ---- ③ 注册成 B 号（先发号：发不出来就不该动盘） -------------------------
        try:
            mid = _MID.next_manuscript_id(root, family="b-proof")
        except Exception as exc:  # noqa: BLE001 —— 号发不出来要如实报，不许静默
            out["checked"] = False
            return self._polish_refusal(
                out, "manuscript_id_unavailable",
                why=(f"B 的稿号发不出来（{type(exc).__name__}: {exc}）⇒ 这一趟不复制"
                     "（一个字节都没写）"))
        target_rel = _MID.canonical_rel(mid, family="b-proof")
        out.update(manuscript_id=mid, path=target_rel)
        if not target_rel:
            out["checked"] = False
            return self._polish_refusal(
                out, "bad_manuscript_name",
                why=f"B 的稿号 {mid!r} 拼不出落点 ⇒ 这一趟不复制")
        target = Path(str(root)) / target_rel
        if target.exists():
            return self._polish_refusal(
                out, "target_exists",
                why=(f"`{target_rel}` 已经在盘上 ⇒ 不覆盖（号源的占用检查本该跳过它，"
                     "走到这里说明盘在发号之后被改过）；换一个号再试"))

        # ---- ④ 清掉复制件里的 V 签（清的是复制件，源稿一个字节不动） ----------
        copy_text, cleared_lines = _strip_sign_lines(text)
        out["cleared"] = len(cleared_lines)
        out["cleared_lines"] = list(cleared_lines)
        out["copy_body_sha"] = _PR.proof_sha(_VS.manuscript_proof_body(copy_text))
        out["copy_text_sha256"] = hashlib.sha256(copy_text.encode("utf-8")).hexdigest()

        # ---- ② 复制一份（源稿那一份文件 → reports/b-proof-<新 B 稿号>.md） -------
        try:
            _atomic_write(target, copy_text)
        except OSError as exc:  # noqa: BLE001 —— 写不进去要如实报，不留半截
            return self._polish_refusal(
                out, "write_failed",
                why=(f"`{target_rel}` 没写成（{type(exc).__name__}: {exc}）⇒ "
                     "这一趟没复制出副本"))
        after = _VS.manuscript_sign_reading(copy_text, manuscript_path=target_rel)
        out["signed_after"] = bool(after.get("found"))
        if out["signed_after"]:
            # 清签没清干净：签块还在 ⇒ 这一份"复制件"仍会被读成已签。不许静默。
            return self._polish_refusal(
                out, "sign_not_cleared",
                why=(f"复制件里还读得到签块（{after.get('why') or '认不出'}）⇒ "
                     "清签没清干净：这一份不能当未签的优化副本用"))
        # ---- ⑤ 记一条来源（事实：谁复制了谁） ---------------------------------
        #
        # 2026-11-13 业主裁定「B 做优化表述的那一份，命题已在台账上审过」——
        # 收方（B 的按稿收录）要靠这条记录认出"这是优化副本、不是新命题"。
        # 记录写在它自己那一行 task 的 artifacts（与 `mss:` 同族、多两格
        # `kind=polish` / `source=<源稿号>`），不加新表、不加新列。
        # 记录没写成不带走复制本身（副本已经在盘上）：读数如实带 `polish_source`。
        out["polish_source"] = self._record_polish_source(
            manuscript_id=mid,
            source_manuscript_id=(str(out.get("source_manuscript_id") or "")
                                  or f"stmt:{sid}"),
            path=target_rel,
            source_sign=str(out.get("source_sign") or ""))
        out.update(ok=True, why="")
        return out

    #: 优化副本来源记录里 `kind` 那一格的值（与 `agent_f.submission.POLISH_SOURCE_KIND`
    #: 是同一枚字面量：写法只有一处）。
    POLISH_KIND = POLISH_SOURCE_KIND

    @staticmethod
    def _optimization_round_enabled() -> bool:
        """优化轮开不开（反真空的打桩点；默认开）。

        与 `register_statement._optimization_replace_enabled` 同形：判据只回答"这一轮
        开不开"，不回答"开哪一条"。反真空把它打成 False ⇒ 批量入口一条都不开
        （证明"开了 N 条"不是恒真读数）。
        """
        return True

    def open_optimization_drafts(self, *, limit: int | None = None) -> dict:
        """按「未优化清单」批量开优化稿：一次调用开一批（业主 2026-11-14 的一般性规定）。

        「系统取未优化的命题号及相关信息、命题类型、原证明稿，自动注册 B 侧稿号并给出
        初始稿（就是原证明稿的复制版）」—— 这一格就是那一笔的入口：

        - 清单只有一处口径：`closing.statements_optimization_candidates`（候选面，
          与收工读数同一份函数，不另判一次）；
        - 有原稿的逐条调 `open_polish_copy`（源稿没签也开，`source_sign` 记档）；
        - 没原稿的不开（`skipped_no_draft`）—— 概念那一档要先有良定义论证，见
          `next_step`；已经在开过稿的不重复开（`skipped_open`，幂等）；
        - 每一份新稿带一条 `prompt`：按 `prompt_class` 取的那一档优化提示词
          （`agent_b.optimize_prompts`）。良定义那一档只有草案、还没落（`status`
          写着 `draft_pending`），绝不拿 F 侧那套"把证明写清楚"硬套上去。

        写盘只发生在这里（`open_polish_copy` 的四步）与它自己那条来源记录里：
        收工读数一个字都不写。返回 `{checked, enabled, count, opened, refused,
        skipped_open, skipped_no_draft, by_prompt_class, why}`。
        """
        out: dict[str, Any] = {
            "checked": False, "enabled": False, "count": 0,
            "opened": [], "refused": [], "skipped_open": [], "skipped_no_draft": [],
            "by_prompt_class": {}, "why": "",
        }
        store = getattr(self, "store", None)
        if store is None:
            out["why"] = "没有 store ⇒ 读不到「未优化清单」"
            return out
        out["enabled"] = bool(self._optimization_round_enabled())
        if not out["enabled"]:
            out.update(checked=True, why="优化轮被关掉（反真空打桩）⇒ 一条都没开")
            return out
        from .. import closing as _CL

        cand = _CL.statements_optimization_candidates(store)
        if not cand.get("checked"):
            out["why"] = str(cand.get("reason") or "「未优化清单」没查成")
            return out
        out["checked"] = True
        rows = list(cand.get("rows") or [])
        cap = int(self.OPTIMIZATION_ROUND_MAX if limit is None else limit or 0)
        if cap > 0:
            rows = rows[:cap]
        for row in rows:
            sid = str(row.get("stmt_id") or "")
            prompt_class = str(row.get("prompt_class") or "")
            draft = dict(row.get("draft") or {})
            if not draft.get("available"):
                out["skipped_no_draft"].append({
                    "stmt_id": sid, "prompt_class": prompt_class,
                    "why": "没有可复制的原稿（概念先落良定义论证；定理/穷举先让产出方落稿）",
                    "next_step": str(row.get("next_step") or "")})
                continue
            open_state = dict(row.get("optimization_open") or {})
            if open_state.get("found"):
                out["skipped_open"].append({
                    "stmt_id": sid, "copies": list(open_state.get("copies") or []),
                    "why": "这一条已经开过优化稿（来源记录在 tasks.artifacts）⇒ 不重复开"})
                continue
            got = self.open_polish_copy(statement_id=sid)
            rec = {"stmt_id": sid, "ok": bool(got.get("ok")),
                   "refused": str(got.get("refused") or ""),
                   "path": str(got.get("path") or ""),
                   "manuscript_id": str(got.get("manuscript_id") or ""),
                   "source_sign": str(got.get("source_sign") or ""),
                   "source_kind": str(got.get("source_kind") or ""),
                   "cleared": int(got.get("cleared") or 0),
                   "prompt_class": prompt_class, "why": str(got.get("why") or "")}
            if rec["ok"]:
                rec["prompt"] = _optimization_prompt(prompt_class)
                out["opened"].append(rec)
                key = prompt_class or "theorem"
                out["by_prompt_class"][key] = int(out["by_prompt_class"].get(key) or 0) + 1
            else:
                out["refused"].append(rec)
        out["count"] = len(out["opened"])
        out["why"] = (
            "查过了：这一轮开了 %d 份优化稿（按提示词档：%s）；跳过 %d 条（已有稿 %d / "
            "没有原稿 %d）、受控拒 %d 条" % (
                out["count"], out["by_prompt_class"], len(out["skipped_no_draft"])
                + len(out["skipped_open"]), len(out["skipped_open"]),
                len(out["skipped_no_draft"]), len(out["refused"])))
        return out

    def _record_polish_source(self, *, manuscript_id: Any,
                              source_manuscript_id: Any,
                              path: Any = "",
                              source_sign: Any = "") -> dict[str, Any]:
        """往「自己那一行 task」的 `artifacts` 记一条优化副本来源（事实，不是判断）。

        记号与 `mss:` 同族（`agent_f/submission.py` 那套），多几格：
        `mss:<新稿号>#kind=polish#source=<源稿号或 stmt:<命题号>>#source_sign=<档>#path=<副本路径>#at=<时刻>`。
        `source` 在源稿没有稿号（行上正文那一档）时记 `stmt:<命题号>` —— 这样"这一条命题
        开过优化稿没有"两档都能问得出来（`opened_polish_sources` 按同一枚记号匹配）。
        写口是 `tasks.artifacts`（append-only、`sorted_unique` 去重），不新表不新列。

        三态：`checked=False` = 没查成 / 没有可写的行（"不在任务上下文"是其中一档，
        副本照落，只是这条来历没留下）；`recorded=True` = 记上了（幂等：同一枚记号
        重复写不算第二次）。
        """
        from .. import schema as S

        out: dict[str, Any] = {"checked": False, "recorded": False, "token": "",
                               "task_id": "", "why": ""}
        mid = str(manuscript_id or "").strip()
        src = str(source_manuscript_id or "").strip()
        if not mid or not src:
            out["why"] = ("缺新稿号 / 源稿号 ⇒ 记不了「谁复制了谁」"
                          "（这一份的来历不完整）")
            return out
        rel = str(path or "").strip().replace("\\", "/")
        token = f"mss:{mid}#kind={self.POLISH_KIND}#source={src}"
        sign = str(source_sign or "").strip()
        if sign:
            token += f"#source_sign={sign}"
        if rel:
            token += f"#path={rel}"
        token += f"#at={S.now_iso()}"
        out["token"] = token
        try:
            from ..conductor import current_task_id

            tid = str(current_task_id() or "")
        except Exception:  # noqa: BLE001 —— 读不到召唤号 = 不在任务上下文（不是崩溃）
            tid = ""
        out["task_id"] = tid
        store = getattr(self, "store", None)
        if not tid:
            out["why"] = ("没有召唤号（不在任务上下文里）⇒ 没有「自己那一行」可写；"
                          "副本已落，这条来历没记上")
            return out
        if store is None:
            out["why"] = "没有 store ⇒ 写不了 `tasks.artifacts`"
            return out
        try:
            with store.tx("tasks", actor="agent-B", note="b.open_polish_copy") as tx:
                cur = tx.find("tasks", task_id=tid)
                if cur is None:
                    out["why"] = f"召唤号 {tid!r} 不在 `tasks` 表里 ⇒ 没有可写的行"
                    return out
                arts = list(cur.get("artifacts") or ())
                if token in arts:
                    out.update(checked=True, recorded=True, why="同一枚记号已经记过（幂等）")
                    return out
                cur["artifacts"] = S.sorted_unique(arts + [token])
                tx.upsert("tasks", cur, note="b.open_polish_copy")
        except Exception as exc:  # noqa: BLE001 —— 写不进去要如实说，不改复制结果
            out["why"] = f"来源记录没写成（{type(exc).__name__}: {exc}）"
            return out
        out.update(checked=True, recorded=True)
        return out



    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _polish_refusal(out: dict[str, Any], code: str, *, why: str) -> dict:
        """受控拒的返回形状（受控码 + 一句人话；`ok=False`）。"""
        out.update(ok=False, refused=str(code), why=str(why))
        return out

    def _polish_source(self, root: str, sid: str,
                       source_manuscript: str) -> dict[str, Any]:
        """找「这一条命题的原证明稿」（源稿）；找不到 ⇒ `found=False` + 受控码。

        两段：先按"已签的稿"找（下面第 1–3 条证据），找不到再退到"没签的原稿"
        （第 4 条）。业主 2026-11-14 的口径是优化侧「不依赖录入侧有没有好素材」
        ⇒ 源稿没有签也照样开副本，只把是哪一档如实记进 `source_sign`。

        1. 调用方点名了 `source_manuscript` ⇒ 只认那一份：签过的按签核 sha
           （`vsigns.signed_manuscripts(artifact_path=…)`），没签的按盘上正文放行
           并记 `source_sign="unsigned"`；
        2. V 的颁发表里 `statement_id` 等于这条命题的签 ⇒ 它盖在哪份稿上就用哪份
           （`artifact_path` 那一格；`issue` 会写它）；
        3. 这一条命题的 `statements` 行上记着 `manuscript_id` ⇒ 那份稿就是它的规范名
           （`manuscriptids.canonical_rel` 拼，不写前缀字面量），再回 V 的颁发表按
           `artifact_path` 核对「它确实签过」。这一条补的是收录之后才出现的现场：F 的
           稿在收录时「不改名也不改稿头」（一稿一份的纪律），未在册那一签的
           `statement_id` 是空串 ⇒ ② 够不着，只有行上那一格记得住「这条命题的稿是
           哪一份」。改前还有一条"读稿头 `- 命题号：` 认领"的证据 —— 业主 2026-11-13
           裁定「稿里没有命题号，任何稿里都没有命题号」⇒ 那一条随稿头那一行删除；
        4. 上面都够不着 ⇒ 行上 `manuscript_id` 指到的那一份（没签）/ 行上的
           `proof_text`（渲染成 B 号初始稿）—— 见 :meth:`_polish_source_unsigned`。

        四条都不在 ⇒ `no_source_draft`：没有可复制的原稿。`why` 把"差在哪一格"
        分开说清（签表里没有 / 行上没记稿号 / 行上正文是空的），不折成同一句话。
        """
        out: dict[str, Any] = {"found": False, "refused": "", "why": "", "path": "",
                               "text": "", "sign_sha": "", "block": {},
                               "matched_by": "", "source_sign": "", "source_kind": ""}
        table = _VS.signed_table(root)
        if not table.get("checked"):
            out.update(checked=False, refused="signed_table_unreadable",
                       why=(f"拿签稿表没查成：{table.get('why') or '（没有理由）'} ⇒ "
                            "这一格没查成，不是「没有原稿」"))
            return out
        entries = [dict(e) for e in (table.get("entries") or [])]
        named = str(source_manuscript or "").strip().replace("\\", "/")
        if named:
            hit = next((e for e in entries
                        if str(e.get("artifact_path") or "") == named), None)
            if hit is not None:
                got = self._polish_source_of(root, hit, out)
                if got.get("found"):
                    got.update(source_sign="signed", source_kind="signed_manuscript")
                return got
            # 点名的那一份没签：只要盘上有它，就按"没签的原稿"开（业主 2026-11-14）。
            if (Path(str(root)) / named).is_file():
                got = self._polish_source_unsigned_file(root, named, out)
                return got
            out.update(refused="source_missing", path=named,
                       why=(f"`{named}` 不在盘上 ⇒ 拿不到原稿：这一条不能开优化副本"))
            return out

        by_sid = [e for e in entries if str(e.get("statement_id") or "") == sid]
        for entry in by_sid:
            got = self._polish_source_of(root, entry, dict(out))
            if got.get("found"):
                got.update(source_sign="signed", source_kind="signed_manuscript")
                return got
        # 未在册那一档（签文件里没有命题号）不再按稿头认领：稿里没有命题号
        # （业主 2026-11-13）⇒ 那一档只由下面第 ③ 条（行上 `manuscript_id` + 颁发表
        # 核对）回答。
        # ③ 命题行上的 `manuscript_id`（2026-11-11：收录之后 B 反而找不到那份已签的稿）
        row_reading = self._statement_manuscript_id(sid)
        row_mid = str(row_reading.get("manuscript_id") or "")
        if row_mid:
            row_rel = _MID.canonical_rel(row_mid)   # F 的规范名（前缀由族表拼）
            if not row_rel:
                row_evidence_why = (
                    f"行上记着稿号 {row_mid!r}，而它拼不出 F 那份稿的规范名"
                    "（`reports/` 下这一族的规范前缀 + 六位稿号）⇒ 这一格核不上")
            else:
                hit = next((e for e in entries
                            if str(e.get("artifact_path") or "").strip().replace("\\", "/")
                            == row_rel), None)
                if hit is None:
                    row_evidence_why = (
                        f"行上记着稿号 {row_mid}（那份稿应是 `{row_rel}`），而 V 的颁发"
                        "表里没有一份签盖在它上面 ⇒ 记了稿号、但那一份没签")
                else:
                    got = self._polish_source_of(root, hit, dict(out))
                    if got.get("found"):
                        got["matched_by"] = "statement_manuscript_id"
                        got.update(source_sign="signed", source_kind="signed_manuscript")
                        return got
                    # 签表里确有这一份、但拿不到稿件（文件没了 / 签后改过）⇒
                    # 按那一档如实拒，不折成「没有签」。
                    return got
        elif row_reading.get("checked"):
            if row_reading.get("found") is False:
                row_evidence_why = (
                    f"`statements` 里没有 stmt:{sid} 这一行 ⇒ 读不出稿号"
                    "（不是「行上没记稿号」，这一格没对象）")
            else:
                row_evidence_why = (
                    "行上没有记稿号（这条命题的 `statements` 行 `manuscript_id` 是空的）")
        else:
            row_evidence_why = (
                "行上那一格没查成（`statements` 台账读不出来："
                f"{row_reading.get('why') or '没有理由'}）")
        # ④ 没签的原稿：行上稿号那一份 / 行上的正文（业主 2026-11-14「录入侧可能
        # 找不到素材」⇒ 优化侧自己造初始稿）。
        unsigned = self._polish_source_unsigned(root, sid, dict(out))
        if unsigned.get("found"):
            return unsigned
        out.update(refused="no_source_draft",
                   why=(f"查过了：这一条没有可复制的原稿（V 的颁发表里没有签指到 "
                        f"stmt:{sid}；行上没有可用的稿号或正文）。差第 ④ 条证据："
                        f"{row_evidence_why}"))
        return out

    def _polish_source_unsigned_file(self, root: str, rel: str,
                                     out: dict[str, Any]) -> dict[str, Any]:
        """盘上那一份（没签的）稿 ⇒ 源稿读数。读不出来 ⇒ `checked=False`（没查成）。"""
        target = Path(str(root)) / rel
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out["checked"] = False
            out.update(refused="source_unreadable",
                       why=f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成")
            return out
        out.update(found=True, path=rel, text=text, sign_sha="", block={},
                   refused="", why="", matched_by="named_unsigned",
                   source_sign="unsigned", source_kind="unsigned_manuscript")
        return out

    def _polish_source_unsigned(self, root: str, sid: str,
                                out: dict[str, Any]) -> dict[str, Any]:
        """没签的原稿（行上稿号那一份 / 行上的 `proof_text`）；都没有 ⇒ `found=False`。

        `source_sign` 一律 `unsigned`（这一档没有可核的签）；两种 `source_kind`：
        `unsigned_manuscript`（盘上有稿，逐字复制）与 `statement_proof_text`
        （没有文件，按同一份正文用 `manuscriptform.render_proof_manuscript` 渲染初始稿）。

        这是"优化侧自己造初始稿"的落点：录入侧可能找不到素材，而优化不该因此停摆。
        """
        from .. import manuscriptform as _MF
        from .. import manuscriptids as _MID
        from .. import statementledger as _SL

        got = _SL.by_id(getattr(self, "store", None), stmt_id=sid)
        if not got.get("checked"):
            out.update(checked=False, refused="statement_row_unreadable",
                       why=("`statements` 那一行读不出来 ⇒ 不知道原稿在哪（没查成，"
                            "不是「没有原稿」）"))
            return out
        row = dict(got.get("row") or {}) if got.get("found") else {}
        kind = str(row.get("kind") or "")
        mid = str(row.get("manuscript_id") or "").strip()
        family = "b-proof" if kind == "concept" else "f-proof"
        if mid:
            try:
                rel = _MID.canonical_rel(mid, family=family)
            except Exception:  # noqa: BLE001
                rel = ""
            if rel and (Path(str(root)) / rel).is_file():
                got_file = self._polish_source_unsigned_file(str(root), rel, out)
                if got_file.get("found"):
                    got_file.update(matched_by="statement_manuscript_id")
                return got_file
        proof = str(row.get("proof_text") or "").strip()
        if proof:
            text = _MF.render_proof_manuscript(
                "B", proposition=str(row.get("statement_full") or ""),
                proof_text=proof, label=str(row.get("label") or ""))
            out.update(found=True, path="", text=text, sign_sha="", block={},
                       refused="", why="", matched_by="statement_proof_text",
                       source_sign="unsigned", source_kind="statement_proof_text")
            return out
        return out

    def _statement_manuscript_id(self, sid: str) -> dict[str, Any]:
        """④ 的证据源：这条命题的 `statements` 行上记的稿号（三态，不折平）。

        返回 `{checked, found, manuscript_id, why}`：

        - `checked=True, found=True, manuscript_id=""` ⇒ 查过了，行上没有那一格；
        - `checked=True, found=True, manuscript_id="000000"` ⇒ 行上记着这一份稿；
        - `checked=True, found=False` ⇒ 台账里没有这一行（不是「行上没记」）；
        - `checked=False` ⇒ 台账读不出来（"没查成"不是"行上没记"）。
        """
        from .. import statementledger as _SL

        try:
            got = _SL.by_id(getattr(self, "store", None), stmt_id=sid)
        except Exception as exc:  # noqa: BLE001 —— 读不成要如实说，不许折成「没有这一格」
            return {"checked": False, "found": None, "manuscript_id": "",
                    "why": f"读 `statements` 那一行失败（{type(exc).__name__}: {exc}）"}
        if not got.get("checked"):
            return {"checked": False, "found": None, "manuscript_id": "",
                    "why": str(got.get("reason") or got.get("why") or "")}
        row = dict(got.get("row") or {})
        return {"checked": True, "found": bool(got.get("found")),
                "manuscript_id": str(row.get("manuscript_id") or "").strip(),
                "why": ""}

    @staticmethod
    def _polish_source_of(root: str, entry: dict, out: dict) -> dict[str, Any]:
        """把颁发表里那一行落成"源稿"读数（稿在不在盘上、签是不是覆盖现在这一版）。"""
        rel = str(entry.get("artifact_path") or "").strip().replace("\\", "/")
        sign_sha = str(entry.get("artifact_sha") or "").strip().lower()
        out.update(path=rel, sign_sha=sign_sha)
        if not rel:
            out.update(refused="sign_without_carrier",
                       why=("V 的颁发表里有这一签，但签文件没记它盖在哪一份稿上"
                            "（`artifact_path` 是空的）⇒ 拿不到稿件；重签一次让 V 写上那一格"))
            return out
        target = Path(str(root)) / rel
        if not target.is_file():
            out.update(refused="source_missing",
                       why=(f"`{rel}` 不在盘上（签记着它，文件却没了）⇒ 拿不到稿件："
                            "这一条不能开优化副本"))
            return out
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out["checked"] = False
            out.update(refused="source_unreadable",
                       why=f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成")
            return out
        block = _VS.manuscript_sign_reading(text, manuscript_path=rel)
        body_sha = _PR.proof_sha(_VS.manuscript_proof_body(text))
        if body_sha != sign_sha:
            # 签后改过正文 = 违规态（业主 2026-11-11：拿签后只对稿允许有只读权）。
            # 不静默放过，也不拿"签过一份旧正文"来冒充"这一份签过"。
            out.update(block=dict(block), refused="source_edited_after_sign",
                       why=(f"`{rel}` 的签盖的是 {sign_sha[:12]}…，而它现在的正文是 "
                            f"{body_sha[:12]}… ⇒ 这份稿签后改过正文（违规态：拿签后只读）。"
                            "不拿它开优化副本：先把这份稿改回签住的那一版，或让 V 重签"))
            return out
        out.update(found=True, text=text, block=dict(block), refused="", why="")
        return out


def _strip_sign_lines(text: Any) -> tuple[str, list[str]]:
    """删掉稿里全部 `- V 签：…` 行，返回 `(清过的正文, 被删掉的那些行)`。

    只删这一种行（`vsigns.SIGN_MARK` 是写与读共用的唯一前缀）；删完把可能留下的
    连续空行压掉一行（签块插在页头那几行之间，删掉后不该在页头留两个空行）。
    """
    raw = str(text or "").replace("\r\n", "\n")
    kept: list[str] = []
    removed: list[str] = []
    for line in raw.split("\n"):
        if line.strip().startswith(_VS.SIGN_MARK):
            removed.append(line)
            continue
        kept.append(line)
    return "\n".join(kept), removed


def polish_source_reading(store: Any, *, manuscript: Any = "") -> dict[str, Any]:
    """这份稿有没有「优化副本」来源记录（`open_polish_copy` 写的那一枚）。

    读口只有 `tasks.artifacts`（与 `mss:` 同一张表、同一族记号）：扫所有行，找
    `kind=polish` 且稿号 / 路径对得上这一份的那一枚。三态：
      · `checked=True, found=True`  ⇒ 它是优化副本，`source_manuscript_id` 是源稿号；
      · `checked=True, found=False` ⇒ 查过，没有这份稿的记录（按"不是优化副本"处置）；
      · `checked=False`             ⇒ 没查成（没有 store / tasks 读不出来）——
        调用方不许把这一档折成"没有记录"再当成"不是优化副本"而不留痕。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "manuscript_id": "",
                           "source_manuscript_id": "", "token": "", "why": ""}
    rel = str(manuscript or "").strip().replace("\\", "/")
    if not rel:
        out["why"] = "没给稿路径 ⇒ 不知道问哪一份"
        return out
    try:
        from .. import vsigns as _VS

        mid = str(_VS.manuscript_id_of(rel) or "")
    except Exception:  # noqa: BLE001 —— 认不出号就只按路径匹配
        mid = ""
    if store is None:
        out["why"] = "没有 store ⇒ 读不到 `tasks.artifacts`"
        return out
    try:
        rows = [dict(r) for r in store.rows("tasks")]
    except Exception as exc:  # noqa: BLE001 —— 读不出来 = 没查成
        out["why"] = f"`tasks` 读不出来（{type(exc).__name__}: {exc}）⇒ 没查成"
        return out
    out["checked"] = True
    for row in rows:
        for token in row.get("artifacts") or ():
            text = str(token or "").strip()
            if not text.startswith("mss:"):
                continue
            chunks = text.split("#")
            head = chunks[0][len("mss:"):].strip()
            fields: dict[str, str] = {}
            for chunk in chunks[1:]:
                key, sep, value = chunk.partition("=")
                if sep:
                    fields[key.strip()] = value.strip()
            if fields.get("kind") != _OpenPolishCopy.POLISH_KIND:
                continue
            if (mid and head == mid) or (rel and fields.get("path") == rel):
                out.update(found=True, manuscript_id=head, token=text,
                           source_manuscript_id=str(fields.get("source") or ""),
                           why="")
                return out
    out["why"] = "`tasks.artifacts` 里没有这份稿的优化副本来源记录"
    return out


def opened_polish_sources(store: Any) -> dict[str, Any]:
    """已经开过优化稿的源稿 ⇒ `{checked, by_source: {源标记: [新稿号…]}, count, why}`。

    「源标记」与 `_record_polish_source` 写的那一枚 `source` 是同一个记号：源稿有稿号
    就是稿号，没有稿号（行上正文那一档）就是 `stmt:<命题号>`。`closing.
    statements_optimization_candidates` 用它给逐条 `optimization_open`，幂等判据只用
    这一处（"这一条开过没有"不许各判一次）。

    三态：`checked=False`（没有 store / `tasks` 读不出来）不是"一条都没开过"。
    """
    out: dict[str, Any] = {"checked": False, "by_source": {}, "count": 0, "why": ""}
    if store is None:
        out["why"] = "没有 store ⇒ 读不到 `tasks.artifacts`"
        return out
    try:
        rows = [dict(r) for r in store.rows("tasks")]
    except Exception as exc:  # noqa: BLE001 —— 读不出来 = 没查成
        out["why"] = f"`tasks` 读不出来（{type(exc).__name__}: {exc}）⇒ 没查成"
        return out
    out["checked"] = True
    by: dict[str, list[str]] = {}
    for row in rows:
        for token in row.get("artifacts") or ():
            text = str(token or "").strip()
            if not text.startswith("mss:"):
                continue
            chunks = text.split("#")
            head = chunks[0][len("mss:"):].strip()
            fields: dict[str, str] = {}
            for chunk in chunks[1:]:
                key, sep, value = chunk.partition("=")
                if sep:
                    fields[key.strip()] = value.strip()
            if fields.get("kind") != _OpenPolishCopy.POLISH_KIND:
                continue
            src = str(fields.get("source") or "").strip()
            if not src:
                continue
            if head not in by.setdefault(src, []):
                by[src].append(head)
    out["by_source"] = {k: sorted(v) for k, v in sorted(by.items())}
    out["count"] = sum(len(v) for v in out["by_source"].values())
    if not out["count"]:
        out["why"] = "`tasks.artifacts` 里一条优化副本来源记录都没有"
    return out
