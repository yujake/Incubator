"""角色 B 的动作 `B.open_polish_copy`：把「已拿签的那份稿」复制成一份 B 号优化副本。

业主 2026-11-11 裁定 ④（逐字）：

```text
「B侧进入证明优化阶段时，选中一个待优化的命题后系统自动帮其拿到稿件并复制一份
  注册成B号并清除复制版本内的V签」
```

## 这一步解决什么

改前 B 的"证明优化"是**就地改**那份已拿签的稿（2026-11-07 裁定 ③：只换 `## 证明`、
`proof_no` 递增）。它在"稿 = 命题的证明"那个口径下是自洽的，但业主 2026-11-11 的
口径变了：

```text
「稿通过后相当于这个命题证完了，后续只对稿允许有只读权」
「同稿号多个版本是错误的，一个稿号就相当于是该稿的文件名……拿 V 签冻结后交哪份是明确的」
```

于是"优化"必须先分叉：**已拿签的那一份只读**，要改就复制一份、注册成新的 B 号、
把复制件里的 V 签清掉（它是另一份稿，签不该跟着走）。四步逐条对应业主那句话：

1. **拿到稿件** —— 走乙的读口（`vsigns.signed_manuscripts`，复用 V 的颁发表）；
   这一条还没有签 ⇒ 受控拒 `no_signed_manuscript`（"无可优化"，且一个字节都不写）；
2. **复制一份** —— 源稿**那一份文件**逐字复制（2026-11-11 追加口径：一份对一份，
   不带 `-pN`）；
3. **注册成 B 号** —— 号由 `manuscriptids.next_manuscript_id(root, family="b-proof")`
   发（B 自己那条号段），落点 `reports/b-proof-<B稿号>.md`；
4. **清除复制版本内的 V 签** —— 删掉 `- V 签：…` 那一行（`vsigns.SIGN_MARK`）。

之后 B 在那份 B 稿上改正文（`fs.edit`），再走既有送审口派 V 三转签 —— 那一签盖的是
**新正文的 sha**，与源稿的签互不相干。

## 这一格不做什么

- 不改源稿一个字节（源稿的只读权由 `丁` 的三处写口守）；
- 不把复制件写成"已签"（清签之后它是未签的新稿）；
- 不自己判"该优化哪一步"（那是 B 的判断，这里只负责把材料摆到手上）。
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

        ## 参数

        - `statement_id`：待优化的那条命题的号（必填；它是"找哪一份稿"的唯一入口）；
        - `source_manuscript`：可以不给。不给 ⇒ 从 V 的颁发表里找这一条命题签过的
          那份稿；给了 ⇒ 必须是**签过的那一份**（否则受控拒 `source_not_signed`，
          不许拿一份没签的稿当"已拿签的稿"复制）。

        ## 返回（键固定）

        `{ok, checked, refused, why, source_path, source_manuscript_id,
        source_sign_sha, source_body_sha, source_text_sha256, path, manuscript_id,
        copy_body_sha, copy_text_sha256, cleared, cleared_lines, signed_before,
        signed_after, sign_block}`。受控拒时 `path` 为空、盘上一个字节都没写。

        `cleared` 是删掉了几行 `- V 签：…`（正常是一行；历史稿可能不止一行）。
        """
        out: dict[str, Any] = {
            "ok": False, "checked": True, "refused": "", "why": "",
            "source_path": "", "source_manuscript_id": "", "source_sign_sha": "",
            "source_body_sha": "", "source_text_sha256": "",
            "path": "", "manuscript_id": "", "copy_body_sha": "",
            "copy_text_sha256": "", "cleared": 0, "cleared_lines": [],
            "signed_before": False, "signed_after": False, "sign_block": {},
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
                   signed_before=True)

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

        # ---- ④ 清掉复制件里的 V 签（清的是**复制件**，源稿一个字节不动） ----------
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

        三种证据按强度排：

        1. 调用方点名了 `source_manuscript` ⇒ 只认那一份，并且**它必须签过**
           （`vsigns.signed_manuscripts(artifact_path=…)`）；
        2. V 的颁发表里 `statement_id` 等于这条命题的签 ⇒ 它盖在哪份稿上就用哪份
           （`artifact_path` 那一格；2026-11-11 起 `issue` 会写它）；
        3. 颁发表里那些 `artifact_path` 是手稿、而签文件没记命题号（未在册那一档，
           业主 2026-11-05：「V 就不能假定有号，全签在稿上」）⇒ 读那份稿的稿头
           `- 命题号：stmt:<号>` 认领。

        三条都没有 ⇒ `no_signed_manuscript`：这一条还没有签，无可优化。
        """
        from .. import bmanuscript as _BM

        out: dict[str, Any] = {"found": False, "refused": "", "why": "", "path": "",
                               "text": "", "sign_sha": "", "block": {}}
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
                                "优化副本只能从**已拿签**的那一份复制（拿没签的稿来复制，"
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
        out.update(refused="no_signed_manuscript",
                   why=(f"查过了：V 的颁发表里没有一份签指到 stmt:{sid}"
                        "（按命题号、按稿头都找过）⇒ 这一条还没有签，无可优化"))
        return out

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
