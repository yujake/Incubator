# -*- coding: utf-8 -*-
"""秘书的空号替换（四样一起换，从 secretary.py 的 U22 的空号侧逐字搬出）。

我保证哪条不变式：空号替换时四样一起换（号 / 行 / 绑定 / 计数），不许只换一半。

## 为什么它能单独成文件（依赖方向）

它只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import schema as S
from . import statementledger as SL
from typing import Mapping

from .secretary_deps import (  # noqa: F401 — 这些名字由 secretary_deps 定义
    _stamp_path_number,
)


class VacantMixin:
    """空号替换（四样一起换）（从 secretary.py 搬出的混入类）。"""

    @staticmethod
    def _reset_optimization_column(bits: Mapping[str, Any],
                                   proof_no: int) -> dict[str, Any]:
        """把某一份的优化栏复位成「未优化」，并抹掉它的「难以自证」记录。

        业主 2026-11-13：「将优化栏更新为新稿提交一致的未优化」。两格都要动，
        缺一格都会留下旧稿的结论：

        - `bits.evidence.optimized_by_proof[号] = False`（新稿刚交上来，还没洗过）；
        - `bits.evidence.hard_to_prove_by_proof[号]` 整条删掉 —— 那一格说的是"上一份
          正文证不出来"，新正文换了，这句话就不再成立；留着它，读侧
          `evidencebits.optimized_state` 会把新稿读成第四档 `hard_to_prove`。

        只动这两格：`reviewed` / `reviewed_source` 是 V 的签名面，由
        `vsigns.bits_after_sign` 写（同一个口袋，两个写者不重叠）。
        """
        from . import evidencebits as _EB

        out = _EB.with_optimized_flag(dict(bits or {}), int(proof_no), False)
        table = {str(int(n)): dict(v)
                 for n, v in _EB.hard_to_prove_by_proof(out).items()
                 if int(n) != int(proof_no)}
        ev = dict(out.get("evidence") or {})
        if table:
            ev[_EB.HARD_TO_PROVE_KEY] = table
        else:
            ev.pop(_EB.HARD_TO_PROVE_KEY, None)
        out["evidence"] = ev
        return out

    def _fill_vacant_path_in_tx(self, tx: Any, *, row: Mapping[str, Any], sid: str,
                                proof_text: Any, groups: list[list[dict[str, Any]]],
                                out: dict[str, Any], manuscript: str = "",
                                group: int = 0) -> dict[str, Any] | None:
        """把一份带真 V 签的新稿整条替换到「难以自证」那条空号上。

        业主 2026-11-13 裁定（逐字）：「后续提交 V 签稿时应替换该路径的证明稿、
        依赖面、V 签、引文状态等等，且将优化栏更新为新稿提交一致的未优化。」
        四样东西不在同一笔里换 ⇒ 盘上会出现"新稿 + 旧依赖"或"新稿 + 引文占位签"
        这种谁也读不准的半笔；所以这里一次换完，且全在调用方那一把锁里。

        | # | 格 | 换成什么 |
        |---|---|---|
        | ① | 证明稿：`proof_text` / `proofs[n]` + `proof_history` | 新正文；旧正文按号进历史（谁都能回答"这一版之前是哪一版"） |
        | ② | 依赖面：`dependencies` 里 `path_group=n` 的那几行 | 先删旧行、再写这一份稿的边（同一把锁里，要么全换要么全不换） |
        | ③ | V 签：`bits` 的逐份表 / sha 表 / `reviewed` / `reviewed_source` | 由 `vsigns.bits_after_sign` 认签（唯一口）：占位签 ⇒ 真签 |
        | ④ | 证明稿两格：`manuscripts[n]` + `manuscript_id` | 这一份稿的路径与稿号（后者是"最近一次收录的那份"的兼容读数） |
        | ⑤ | 优化栏：`optimized_by_proof[n]` / `hard_to_prove_by_proof[n]` | 复位成未优化 + 抹掉旧的难以自证（见 :meth:`_reset_optimization_column`） |

        ## 什么时候"不是这一笔"（返回 `None`，调用方照旧）
        - 这一行没有空号（`vacant_path_reading` 没有记着的那几条）；
        - 这一笔没带证明正文，或正文与空号上那一份逐字相同（那是幂等重交，不是替换）；
        - 「难以自证」那一格读不出来 ⇒ `None`（fail-closed：按普通已有证明处置，
          绝不拿一行坏字节抹掉整道"已有证明"判断）。

        ## 什么时候受控拒（`out` 里带 `refused`，一个字节都不写）
        - 这一份正文没有真 V 签 ⇒ `proof_without_v_sign`：替换的资格就是"真签"，
          没有签的正文不许盖掉在册那一份（与优化线换正文同一条判据）；
        - 依赖面判不了（`_resolve_write_steps` 的受控拒）⇒ 原样返回，整笔不写。
        """
        from . import manuscriptpaths as _MP
        from . import verifications as _VR
        from . import vsigns as _VS

        text = str(proof_text or "")
        if not text.strip():
            return None
        vac = _MP.vacant_path_reading(row)
        out["vacant_reading"] = dict(vac)
        if not vac.get("checked"):
            # 读不出来 ⇒ 不许当成空号（fail-closed：按普通已有证明那一路处置）。
            return None
        vacant = [int(g) for g in (vac.get("groups") or [])]
        if int(group or 0) >= 1:
            if int(group) not in vacant:
                return None
            no = int(group)
        else:
            if not vacant:
                return None
            no = min(vacant)
        old = str(_VR.proof_text_of(row, no) or "")
        if old.strip() == text.strip():
            return None
        # ---- ① 真 V 签：先认签（唯一口 `vsigns.bits_after_sign`）----------------
        #
        # 位置在最前：没有签的正文不许盖掉在册那一份（否则这一笔只是"把一份没签的
        # 正文写了进去"，而替换的前提是"优化后拿 V 签"）。认签同时把第 3 位那几张表
        # 从占位改成真签 —— 这一步就是"V 签 / 引文状态"那一格的替换。
        claimed, sign = _VS.bits_after_sign(
            row.get("bits") or {}, root=self.root, proof_text=text,
            statement_id=str(sid), proof_no=no, kind=str(row.get("kind") or ""),
            store=self.store)
        out["replacement_sign"] = {
            "checked": bool(sign.get("checked")),
            "applied": bool(sign.get("applied")),
            "state": str(sign.get("state") or ""),
            "why": str(sign.get("why") or "")}
        if not sign.get("applied"):
            out.update(checked=False, refused="proof_without_v_sign",
                       reason=("第 " + str(no) + " 条路径是「难以自证」的空号：要填上它"
                               "必须交一份有真 V 签的稿，而这一份没有（"
                               + str(sign.get("state") or "unsigned") + "："
                               + str(sign.get("why") or "") + "）⇒ 不替换，一个字节没动"))
            return out
        # ---- ② 依赖面：先把这一份稿的边解出来（判不了 ⇒ 整笔不写）--------------
        body_for_deps = {"proof_no": int(no), "deps": [list(g) for g in groups]}
        steps = self._resolve_write_steps(tx, body_for_deps, out, groups)
        if steps is None:
            return out
        steps = _stamp_path_number(steps, path_group=int(no), proof_no=int(no),
                                   single_group=len(groups) <= 1)
        # ---- ③ 证明稿：旧正文按号进 `proof_history`，这一份落到同一个号上 --------
        raw_history = row.get("proof_history")
        history = ([dict(h) if isinstance(h, Mapping) else h for h in raw_history]
                   if isinstance(raw_history, (list, tuple)) else [])
        if old.strip():
            entry = {"text": old, "sha": _VR.text_sha(old), "at": S.now_iso(),
                     "replaced_by": _VR.text_sha(text), "proof_no": int(no),
                     "why": ("第 " + str(no) + " 条路径本来是「难以自证」的引文占位，"
                             "被一份带真 V 签的新稿整条替换")}
            history.append(entry)
            out["proof_history"] = [dict(entry)]
        new_row = dict(row)
        new_row["proof_history"] = history
        if int(no) == 1:
            new_row["proof_text"] = text
        else:
            listed = [dict(p) if isinstance(p, Mapping) else p
                      for p in (new_row.get(_VR.PROOFS_KEY) or [])]
            for i, one in enumerate(listed):
                if isinstance(one, Mapping) and int(one.get("proof_no") or 0) == int(no):
                    listed[i] = {**dict(one), "text": text,
                                 "proof_sha256": _VR.text_sha(text)}
                    break
            else:
                listed.append({"proof_no": int(no), "text": text,
                               "proof_sha256": _VR.text_sha(text),
                               "created_at": S.now_iso()})
            new_row[_VR.PROOFS_KEY] = listed
        # ---- ④ 优化栏复位（新稿 = 未优化；旧的难以自证不许留）--------------------
        new_row["bits"] = self._reset_optimization_column(claimed, no)
        # ---- ④b 引文状态：占位签 ⇒ 真签（第 3 位的凭据档那一格）------------------
        #
        # 认签口（`vsigns.bits_after_sign` ⇒ `_apply_review_to_bits`）写的是逐份表 /
        # sha 表 / `reviewed`；"凭什么是真"这一格（`evidence.reviewed_source`）只在
        # `bits_of` 构造时写（真签 ⇒ `v`、占位 ⇒ `citation`）。从引文占位换上来的一行
        # 因此会带着上一版的 `reviewed_source="citation"` 读下去（`reviewed=true` 而
        # "凭什么是真：文献编号"）—— 业主 2026-11-13 的"引文状态……替换"就是这一格。
        # 取值仍只有词表里那两个（`v` / `citation`），不新增一档。
        from . import evidencebits as _EB
        _ev = dict(new_row["bits"].get("evidence") or {})
        _ev["reviewed_source"] = _EB.REVIEWED_SOURCE_V
        new_row["bits"]["evidence"] = _ev
        # ---- ⑤ 证明稿的两格：`manuscripts[n]` + `manuscript_id` -------------------
        rel = str(manuscript or "").strip().replace("\\", "/")
        if rel:
            per = dict(new_row.get(_MP.PER_PATH_KEY) or {})
            per[str(int(no))] = rel
            new_row[_MP.PER_PATH_KEY] = per
            mid = str(_VS.manuscript_id_of(rel) or "")
            if mid:
                new_row["manuscript_id"] = mid
                #: K6②：身份是 `(族, 稿号)`；裸号跨族会撞。
                from . import manuscriptids as _MID_FAM

                _fam_now = _MID_FAM.family_of_rel(rel)
                if _fam_now:
                    new_row["manuscript_family"] = _fam_now
        # ---- ⑥ 依赖面：这一条路径的旧行整批换掉（同一把锁里）--------------------
        dropped = 0
        for dep in list(tx.rows("dependencies")):
            if str(dep.get("used_by") or "").split("#", 1)[0] != f"stmt:{sid}":
                continue
            if int(dep.get("path_group") or 1) != int(no):
                continue
            if tx.delete("dependencies", dep.get("dep_id"),
                         note="record_statement:fill_vacant_path:drop") is not None:
                dropped += 1
        deps_written = self._write_dep_steps(tx, steps, stmt_id=sid,
                                             body=body_for_deps)
        tx.upsert("statements", new_row, note="record_statement:fill_vacant_path")
        out.update(
            checked=True, created=False, duplicate=False, merged=True,
            merged_into=str(sid), stmt_id=str(sid), proof_no=int(no),
            proof_no_source="path_group", path_group=int(no),
            path_group_reading={
                "checked": True, "path_group": int(no), "existing": False,
                "vacant_filled": True, "statement_id": str(sid),
                "manuscript": rel, "body_sha": _VR.text_sha(text),
                "count": len(vacant), "paths": [], "problems": [],
                "vacant_paths": sorted(vacant), "vacant_reading": dict(vac),
                "why": (f"第 {no} 条路径处于「难以自证」状态 ⇒ 读成空号："
                        "这一份落在同一个路径号上（整条替换）")},
            tables=["statements", "dependencies"],
            replaced=[int(no)], deps_written=int(deps_written),
            deps_dropped=int(dropped), path_groups=len(groups or []),
            vacant_paths=sorted(vacant),
            reason=(f"第 {no} 条路径原来是「难以自证」的引文占位 ⇒ 那一号读成空号，"
                    "一份带真 V 签的新稿整条替换了它：证明稿（`manuscripts` / "
                    "`manuscript_id`）、依赖面（这一条路径的旧行全部换掉）、"
                    "V 签（逐份表 / sha 表 / `reviewed` / `reviewed_source` 由认签口"
                    "从占位改真签）、引文状态，优化栏复位成未优化"
                    "（`optimized_by_proof=false`、旧的 `hard_to_prove` 记录已抹掉）"))
        return out

    def _fill_vacant_path_if_any(self, tx: Any, *, sid: str, proof_text: Any,
                                 groups: list[list[dict[str, Any]]],
                                 out: dict[str, Any], manuscript: str = "",
                                 group: int = 0) -> bool:
        """空号替换的接线：这一笔该不该整条替换，替换了就补齐回执那几格。

        三个写入口（逐份登记那一支、并进在册命题那一支、收方读稿登记那一支）共用这
        一处接线：三处各写一遍"读行 → 换不换 → 补哪几格"，迟早有一处漏补（而漏补
        只表现为回执少一个键，没有任何判据会响）。返回 `True` = 这一笔已经替换并
        写好，调用方直接返回 `out`；`False` = 这一行没有空号（照旧走原路）。
        """
        row = SL.by_id(rows=tx.rows("statements"), stmt_id=str(sid))["row"]
        landed = self._fill_vacant_path_in_tx(
            tx, row=dict(row or {}), sid=str(sid), proof_text=proof_text,
            groups=groups, out=out, manuscript=manuscript, group=group)
        if landed is None:
            return False
        for key, value in (("duplicates", []), ("deps_dangling", []),
                           ("deps_unmappable", []),
                           ("path_groups", len(groups or [])),
                           ("tables", ["statements", "dependencies"])):
            out.setdefault(key, value)
        return True
