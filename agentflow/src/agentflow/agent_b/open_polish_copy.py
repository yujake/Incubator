"""角色 B 的动作 `B.open_polish_copy`：把「已拿签的那份稿」复制成一份 B 号优化副本。

这一步解决什么：稿通过后相当于这个命题证完了，后续对稿只有只读权；"同稿号多个版本"
是错误的 —— 一个稿号相当于该稿的文件名，拿 V 签冻结后交哪份是明确的。所以"优化"必须
先分叉：已拿签的那一份只读，要改就复制一份、注册成新的 B 号、把复制件里的 V 签清掉
（它是另一份稿，签不该跟着走）。四步：

1. 拿到稿件 —— 走乙的读口（`vsigns.signed_manuscripts`，复用 V 的颁发表）；这一条还
   没有签 ⇒ 受控拒 `no_signed_manuscript`（"无可优化"，一个字节都不写）；
2. 复制一份 —— 源稿那一份文件逐字复制（一份对一份，不带 `-pN`）；
3. 注册成 B 号 —— 号由 `manuscriptids.next_manuscript_id(root, family="b-proof")`
   发（B 自己那条号段），落点 `reports/b-proof-<B稿号>.md`；
4. 清除复制版本内的 V 签 —— 删掉 `- V 签：…` 那一行（`vsigns.SIGN_MARK`）。

之后 B 在那份 B 稿上改正文（`fs.edit`），再走既有送审口派 V 三转签 —— 那一签盖的是
新正文的 sha，与源稿的签互不相干。

这一格不做什么：不改源稿一个字节（源稿的只读权由 `丁` 的三处写口守）；不把复制件写成
"已签"（清签之后它是未签的新稿）；不自己判"该优化哪一步"（那是 B 的判断，这里只负责
把材料摆到手上）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .. import manuscriptform as _MF
from .. import manuscriptids as _MID
from .. import proofregistry as _PR
from .. import vsigns as _VS
from ..manuscriptwrite import _atomic_write


def source_head_statement_id(text: Any) -> str:
    """一份稿的稿头 `- 命题号：` 那一行 ⇒ 裸命题号（认不出 ⇒ 空串）。"""
    from .. import bmanuscript as _BM

    return _BM._head_statement_id(text)


class _OpenPolishCopy:
    def open_polish_copy(self, *, statement_id: str,
                         source_manuscript: str = "") -> dict:
        """把「这一条命题已拿签的那份稿」复制成一份 B 号优化副本（四步见模块 docstring）。

        参数：`statement_id` 是待优化的那条命题的号（必填；它是"找哪一份稿"的唯一入口）；
        `source_manuscript` 可以不给 —— 不给就从 V 的颁发表里找这一条命题签过的那份稿，
        给了就必须是签过的那一份（否则受控拒 `source_not_signed`，不许拿一份没签的稿当
        "已拿签的稿"复制）。

        返回（键固定）：`{ok, checked, refused, why, source_path,
        source_manuscript_id, source_sign_sha, source_body_sha, source_text_sha256,
        path, manuscript_id, copy_body_sha, copy_text_sha256, cleared, cleared_lines,
        signed_before, signed_after, sign_block, matched_by}`。受控拒时 `path` 为空、
        盘上一个字节都没写。`matched_by` 是"源稿是哪一条证据认出来的"：
        `"statement_manuscript_id"` 表示第 ④ 条（命题行上的 `manuscript_id`）；前三条
        老证据命中时仍为空串。`cleared` 是删掉了几行 `- V 签：…`（正常是一行；历史稿
        可能不止一行）。
        """
        out: dict[str, Any] = {
            "ok": False, "checked": True, "refused": "", "why": "",
            "source_path": "", "source_manuscript_id": "", "source_sign_sha": "",
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
                    "「这一条命题那份已拿签的稿」的副本，没有命题号就不知道复制哪一份")
        store = getattr(self, "store", None)
        root = getattr(store, "root", "") or ""
        if not root:
            out["checked"] = False
            return self._polish_refusal(
                out, "no_workspace",
                why="这一趟没有工作区根 ⇒ 读不到颁发表、也写不出副本（不是「没有签」）")

        # ---- ① 拿到稿件：走乙的读口（复用 V 的颁发表） ---------------------------
        picked = self._polish_source(root, sid, source_manuscript)
        if not picked.get("found"):
            out.update(source_path=str(picked.get("path") or ""),
                       source_sign_sha=str(picked.get("sign_sha") or ""),
                       sign_block=dict(picked.get("block") or {}))
            return self._polish_refusal(
                out, str(picked.get("refused") or "no_signed_manuscript"),
                why=str(picked.get("why") or ""))
        src_rel = str(picked.get("path") or "")
        sign_sha = str(picked.get("sign_sha") or "")
        text = str(picked.get("text") or "")
        block = dict(picked.get("block") or {})
        out.update(source_path=src_rel,
                   source_manuscript_id=str(_VS.manuscript_id_of(src_rel) or ""),
                   source_sign_sha=sign_sha,
                   source_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                   source_body_sha=_PR.proof_sha(_VS.manuscript_proof_body(text)),
                   sign_block=block,
                   signed_before=True,
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
        out.update(ok=True, why="")
        return out

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _polish_refusal(out: dict[str, Any], code: str, *, why: str) -> dict:
        """受控拒的返回形状（受控码 + 一句人话；`ok=False`）。"""
        out.update(ok=False, refused=str(code), why=str(why))
        return out

    def _polish_source(self, root: str, sid: str,
                       source_manuscript: str) -> dict[str, Any]:
        """找「这一条命题已拿签的那份稿」（源稿）；找不到 ⇒ `found=False` + 受控码。

        四种证据按强度排：

        1. 调用方点名了 `source_manuscript` ⇒ 只认那一份，并且它必须签过
           （`vsigns.signed_manuscripts(artifact_path=…)`）；
        2. V 的颁发表里 `statement_id` 等于这条命题的签 ⇒ 它盖在哪份稿上就用哪份
           （`artifact_path` 那一格；`issue` 会写它）；
        3. 颁发表里那些 `artifact_path` 是手稿、而签文件没记命题号（未在册那一档 ——
           V 不假定有号，全签在稿上）⇒ 读那份稿的稿头 `- 命题号：stmt:<号>` 认领；
        4. 这一条命题的 `statements` 行上记着 `manuscript_id` ⇒ 那份稿就是它的规范名
           （`manuscriptids.canonical_rel` 拼，不写前缀字面量），再回 V 的颁发表按
           `artifact_path` 核对「它确实签过」。这一条补的是收录之后才出现的现场：F 的
           稿在收录时「不改名也不改稿头」（一稿一份的纪律），稿头仍是
           `stmt:（还没落号）`，而未在册那一签的 `statement_id` 是空串 —— 于是 ②③ 都
           够不着，只有行上那一格记得住「这条命题的稿是哪一份」。

        三条老证据都没有、第 ④ 条也核不上 ⇒ `no_signed_manuscript`：这一条还没有签，
        无可优化。`why` 把第 ④ 条差在哪一格分开说清（行上没记稿号 / 记了但那一份没签 /
        那一格没查成），不折成同一句话。
        """
        from .. import bmanuscript as _BM

        out: dict[str, Any] = {"found": False, "refused": "", "why": "", "path": "",
                               "text": "", "sign_sha": "", "block": {},
                               "matched_by": ""}
        table = _VS.signed_table(root)
        if not table.get("checked"):
            out.update(checked=False, refused="signed_table_unreadable",
                       why=(f"拿签稿表没查成：{table.get('why') or '（没有理由）'} ⇒ "
                            "这一格没查成，不是「没有签」"))
            return out
        entries = [dict(e) for e in (table.get("entries") or [])]
        named = str(source_manuscript or "").strip().replace("\\", "/")
        if named:
            hit = next((e for e in entries
                        if str(e.get("artifact_path") or "") == named), None)
            if hit is None:
                out.update(refused="source_not_signed", path=named,
                           why=(f"`{named}` 不在 V 的颁发表里 ⇒ 它不是一份签过的稿："
                                "优化副本只能从已拿签的那一份复制（拿没签的稿来复制，"
                                "等于把「优化」建在一份没验过的正文上）"))
                return out
            return self._polish_source_of(root, hit, out)

        by_sid = [e for e in entries if str(e.get("statement_id") or "") == sid]
        for entry in by_sid:
            got = self._polish_source_of(root, entry, dict(out))
            if got.get("found"):
                return got
        # 未在册那一档：签文件里没有命题号，但稿头写着它
        for entry in entries:
            rel = str(entry.get("artifact_path") or "").strip().replace("\\", "/")
            if not rel or not _MF.is_safe_relpath(rel):
                continue
            try:
                text = (Path(root) / rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if source_head_statement_id(text) != sid:
                continue
            got = self._polish_source_of(root, entry, dict(out))
            if got.get("found"):
                return got
        # ④ 命题行上的 `manuscript_id`（2026-11-11：收录之后 B 反而找不到那份已签的稿）
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
        out.update(refused="no_signed_manuscript",
                   why=(f"查过了：V 的颁发表里没有一份签指到 stmt:{sid}"
                        "（按命题号、按稿头、按行上稿号都找过）⇒ 这一条还没有签，"
                        f"无可优化；差第 ④ 条证据：{row_evidence_why}"))
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
