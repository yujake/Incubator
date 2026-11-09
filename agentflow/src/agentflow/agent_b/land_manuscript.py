"""角色 B 的动作 `own.land_manuscript`：把一版证明正文落成可签的稿（T1 从登记里拆出来）。

只写文件、不写台账；签名与返回口径见 :meth:`_LandManuscript.land_manuscript`。
`goal-7f5116c1` M6/M7 的拆包契约：一个动作一个文件 —— 本类只由
`agent_b/register_statement.py` 的 `_RegisterStatement` 混入，成员装配面在 `core.py`。
"""
from __future__ import annotations

from .. import statementledger as SL


class _LandManuscript:
    def land_manuscript(self, *, statement_id: str, statement_full: str = "",
                        proof_text: str, label: str = "", proof_no: int = 1,
                        source_manuscript: str = "",
                        if_match_sha256: str = "") -> dict:
        """B 的显式落稿动作（只写文件，不写台账；D1 从登记里拆出来的那一步）。

        ## 为什么需要它（不是"登记顺手落"）

        B 的工具面没有文件写口，而 V 只审盘上的稿。改前这件事由
        `register_statement` 在被拒之前顺手做（D1：被拒的登记留下稿）；拆出来之后
        顺序是 "显式落稿 → 派 V 签 → 带签 `own.register_statement`"，两步各自成立、
        各自可解释。工具面的薄壳是 `own.land_manuscript`（T1 起已注册）。

        ## 参数（T1 接线后）

        - `statement_id`：这条命题的号；必须已经在册（稿名由号拼出，不接受调用方给路径）；
        - `proof_text`：这一版证明正文（逐字；作者交内容、框架渲染落稿）；
        - `statement_full`：可以不给 —— 不给就取在册那一行的命题正文（"命题拿已经登记的"，
          业主 2026-11-07 裁定）；给了也只是那一行的副本，落稿用的是它；
        - `proof_no`：想落成第几份；缺省 1；
        - `if_match_sha256`：并发纪律（protocol §五）—— 调用方"我以为目标稿现在是这一版"；
          不符 ⇒ 受控拒 `stale_target`，一个字节都不写。

        ## 返回

        `{ok, path, written, preserved, signed, sha256, sha, proof_no, text, why,
        problem, refused}`。`sha256` / `sha` 是签尺（`proofregistry.proof_sha(proof_text)`）：
        这份稿将来被 V 签时对拍的就是这个值，不是整份文件的字节 sha。

        ## 幂等

        同一份正文重放：目标稿内容没变 ⇒ `written=False, preserved=True`（不出现
        第二个文件、不改名、不毁签）；已签的那一版不会被另一版正文盖掉
        （`target_holds_a_signed_version`，零写入）。
        """
        from .. import proofregistry as _PR

        sid = str(statement_id or "").strip()
        out: dict = {"ok": False, "path": "", "written": False, "preserved": False,
                     "signed": False, "sha256": "", "sha": "", "proof_no": 0,
                     "text": "", "why": "", "problem": {}, "refused": ""}
        if not sid:
            out.update(kind="statement_missing",
                       why="落稿要指定一条在册命题（`statement_id`）；没有号就没有稿名")
            out["refused"] = "statement_missing"
            return out
        got = SL.by_id(self.store, stmt_id=sid)
        if not got["checked"]:
            err = got.get("error") or {}
            out.update(kind="ledger_unreadable",
                       why=(f"`statements` 读不出来（{err.get('type') or '?'}: "
                            f"{err.get('message') or '?'}）⇒ 不知道这条命题的正文，不落稿"))
            out["refused"] = "ledger_unreadable"
            return out
        row = dict(got["row"] or {})
        if not row:
            out.update(kind="statement_missing",
                       why=(f"`statements` 里没有 stmt:{sid} ⇒ 没有可落的稿"
                            "（先 `own.register_statement` 拿号）"))
            out["refused"] = "statement_missing"
            return out
        proposition = str(statement_full or "").strip() or str(
            row.get("statement_full") or "")
        if not proposition.strip():
            out.update(kind="empty_statement_text",
                       why="这一条在册命题的正文是空的 ⇒ 落稿会写出一份没有命题的稿")
            out["refused"] = "empty_statement_text"
            return out
        label_now = str(label or "").strip() or str(row.get("label") or "")
        if str(if_match_sha256 or "").strip():
            target = _PR.entry_relpath(family="B", statement_id=sid)
            entry = _PR.read_entry(self.store.root, family="B", statement_id=sid)
            current = str((entry.get("entry") or {}).get("sha256") or "")
            if not entry.get("exists") or current != str(if_match_sha256).strip().lower():
                out.update(path=str(target or ""), kind="stale_target",
                           why=("`if_match_sha256` 与盘上那一版不符 ⇒ 不覆盖"
                                f"（盘上现在 {('没有这一份稿' if not entry.get('exists') else current[:12] + '…')}）"))
                out["refused"] = "stale_target"
                return out
        out = dict(self._land_b_manuscript(
            statement_id=sid, statement_full=proposition,
            proof_text=proof_text, label=label_now, proof_no=proof_no,
            source_manuscript=source_manuscript))
        out.setdefault("ok", False)
        out["preview"] = False
        out["sha256"] = str(out.get("sha256")
                            or _PR.proof_sha(str(proof_text or "")))
        out["sha"] = out["sha256"]
        out["proof_no"] = int(out.get("proof_no") or proof_no or 0)
        return out
