"""角色 B 的动作 `own.land_manuscript`：把一版证明正文落成可签的稿。

只写文件、不写台账；签名与返回口径见 :meth:`_LandManuscript.land_manuscript`。
本类只由 `agent_b/register_statement.py` 的 `_RegisterStatement` 混入，成员装配面在
`core.py`。
"""
from __future__ import annotations

from pathlib import Path

from .. import statementledger as SL


class _LandManuscript:
    def land_manuscript(self, *, statement_id: str, statement_full: str = "",
                        proof_text: str, label: str = "", proof_no: int = 1,
                        path_group: int = 0,
                        source_manuscript: str = "",
                        if_match_sha256: str = "") -> dict:
        """B 的显式落稿动作（只写文件，不写台账；从登记里拆出来的那一步）。

        为什么需要它（不是"登记顺手落"）：B 的工具面没有文件写口，而 V 只审盘上的稿。
        这件事原先由 `register_statement` 在被拒之前顺手做（被拒的登记留下稿）；拆出来
        之后顺序是"显式落稿 → 派 V 签 → 带签 `own.register_statement`"，两步各自成立、
        各自可解释。工具面的薄壳是 `own.land_manuscript`。

        参数：`statement_id` 是这条命题的号，必须已经在册（稿名由号拼出，不接受调用方给
        路径）；`proof_text` 是这一版证明正文（逐字；作者交内容、框架渲染落稿）；
        `statement_full` 可以不给 —— 不给就取在册那一行的命题正文，给了也只是那一行的
        副本，落稿用的是它；`proof_no` 是想落成第几份，缺省 1；`if_match_sha256` 是并发
        纪律 —— 调用方"我以为目标稿现在是这一版"，不符 ⇒ 受控拒 `stale_target`，一个
        字节都不写。

        `path_group`（2026-11-12，业主裁定「两条路径各一份 B 改写稿」）：优化线显式点名
        这一份改写稿属于哪条路径（`>=1`；`0` = 老调用面）。给了它，载体就按
        :func:`bmanuscript.manuscript_id_for_path` 从逐路径记录里认：那条路径已经有 B
        改写稿 ⇒ 就地重写那一份；还没有 ⇒ 新开一个 B 稿号；路径不在册 ⇒ 受控拒
        `path_not_found`（一个字节都不写）。路径身份不写稿头（业主：「路径在产出侧也
        不标注」），只落在 `manuscriptpaths` 的逐路径记录里。`0` 档逐字不变。

        概念行也走这一格：概念（`kind="concept"`）的良定义证明同样由 B 落稿，族仍是
        `b-proof`（不新开手稿族），`## 命题` 是这一行的定义（`statement_full`），
        `## 证明` 是良定义证明，稿名 `reports/b-proof-<B稿号>.md`（B 自己那条号段发的
        号；稿头那一行 `- 命题号：stmt:<号>` 才是稿与命题的对应）。V 照常三转签（它只对
        手稿负责，不需要知道这是概念）；签回来之后 B 用
        `own.ingest_manuscript(apply, cells=["proof_text"])` 收录。这一格本身不判断这一行
        是不是概念 —— 只按在册那一行的正文拼稿，所以概念与一般命题在这条链上逐字同形。

        返回 `{ok, path, written, preserved, signed, sha256, sha, proof_no, text, why,
        problem, refused}`。`sha256` / `sha` 是签尺（`proofregistry.proof_sha(proof_text)`）：
        这份稿将来被 V 签时对拍的就是这个值，不是整份文件的字节 sha。

        幂等：同一份正文重放、目标稿内容没变 ⇒ `written=False, preserved=True`（不出现
        第二个文件、不改名、不毁签）；已签的那一版不会被另一版正文盖掉
        （`target_holds_a_signed_version`，零写入）。
        """
        from .. import proofregistry as _PR

        sid = str(statement_id or "").strip()
        out: dict = {"ok": False, "path": "", "written": False, "preserved": False,
                     "signed": False, "sha256": "", "sha": "", "proof_no": 0,
                     "path_group": 0, "path_basis": "",
                     "text": "", "why": "", "problem": {}, "refused": ""}
        if not sid:
            out.update(kind="statement_missing",
                       why="落稿要指定一条在册命题（`statement_id`）；没有号就没有稿名")
            out["refused"] = "statement_missing"
            return out
        try:
            path_no = int(path_group or 0)
        except (TypeError, ValueError):
            out.update(kind="bad_path_group",
                       why=f"`path_group` 必须是整数（收到 {path_group!r}）")
            out["refused"] = "bad_path_group"
            return out
        if path_no < 0:
            out.update(kind="bad_path_group",
                       why=f"`path_group` 必须 >= 0（收到 {path_no}）")
            out["refused"] = "bad_path_group"
            return out
        out["path_group"] = path_no
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
        # ---- 稿号（2026-11-11 业主裁定 ①）：B 自己的号段 -------------------------
        #
        # `if_match_sha256` 要核的是「这一条命题自己那份 B 稿现在是哪一版」。改前那一格
        # 按命题号拼名（`b-proof-<命题号>`），现在稿号与命题号解耦 ⇒ 按 `statements` 行
        # 的逐路径记录找回这份稿（`bmanuscript.manuscript_id_for_statement`，稿里没有
        # 命题号，业主 2026-11-13），找不到就是"还没有这份稿"（受控拒 `stale_target`）。
        #
        # 2026-11-12 补：优化线给了 `path_group` 时，两份稿的载体按「路径」认
        # （`manuscript_id_for_path`）—— 按命题找只会挑中其中一份，第二条路径会覆盖
        # 第一条的载体。路径不在册 ⇒ 受控拒（不许落一份稿、回头再猜它是第几条）。
        _mid_now = ""
        _target = ""
        _path_basis = ""
        if path_no >= 1:
            from .. import bmanuscript as _BM_PATH

            _by_path = _BM_PATH.manuscript_id_for_path(
                self.store.root, sid, path_no, store=self.store)
            _path_basis = str(_by_path.get("basis") or (
                "new_carrier" if _by_path.get("path_exists") else ""))
            out["path_basis"] = _path_basis
            if not _by_path.get("checked"):
                out.update(kind="path_unreadable",
                           why=("逐路径记录读不出来 ⇒ 不知道这一份稿属于哪条路径："
                                + str(_by_path.get("why") or "未知原因")))
                out["refused"] = "path_unreadable"
                return out
            if not _by_path.get("path_exists"):
                out.update(kind="path_not_found",
                           why=str(_by_path.get("why")
                                   or f"第 {path_no} 条路径还没在册"))
                out["refused"] = "path_not_found"
                return out
            _mid_now = str(_by_path.get("manuscript_id") or "")
        if str(if_match_sha256 or "").strip():
            from .. import bmanuscript as _BM_READ
            from .. import proofregistry as _PR

            if path_no < 1:
                _found = _BM_READ.manuscript_id_for_statement(
                    self.store.root, sid, store=self.store)
                _mid_now = str(_found.get("manuscript_id") or "")
                if not _mid_now:
                    _legacy = _PR.entry_relpath(family="B", statement_id=sid)
                    if _legacy and (Path(str(self.store.root)) / _legacy).is_file():
                        _mid_now = sid
                        _target = _legacy
            if _mid_now:
                _target = _target or _PR.entry_relpath(family="B", manuscript_id=_mid_now)
            entry = (_PR.read_entry(self.store.root, family="B", manuscript_id=_mid_now)
                     if _mid_now else {"exists": False, "entry": {}})
            current = str((entry.get("entry") or {}).get("sha256") or "")
            if not _mid_now or not entry.get("exists") or current != str(if_match_sha256).strip().lower():
                out.update(path=str(_target or ""), kind="stale_target",
                           why=("`if_match_sha256` 与盘上那一版不符 ⇒ 不覆盖"
                                f"（盘上现在 {('没有这一份稿' if not _mid_now or not entry.get('exists') else current[:12] + '…')}）"))
                out["refused"] = "stale_target"
                return out
        out = dict(self._land_b_manuscript(
            statement_id=sid, statement_full=proposition,
            proof_text=proof_text, label=label_now, proof_no=proof_no,
            path_group=path_no,
            manuscript_id=_mid_now,
            source_manuscript=source_manuscript))
        out.setdefault("ok", False)
        out["path_group"] = path_no
        out["path_basis"] = _path_basis
        out["preview"] = False
        out["sha256"] = str(out.get("sha256")
                            or _PR.proof_sha(str(proof_text or "")))
        out["sha"] = out["sha256"]
        out["proof_no"] = int(out.get("proof_no") or proof_no or 0)
        return out
