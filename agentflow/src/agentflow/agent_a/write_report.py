# -*- coding: utf-8 -*-
"""A 的汇报稿写口（MSOWN，2026-11-27）。

业主口径：「一种角色一套稿号」——A 的入库/检索汇报稿落在 `manuscripts/A/`，
文件名 `a-report-<六位号>.md`，号源是 A 自己的计数器（`counters.amanuscript`）。
「一个角色实例只对自己产出的稿负责」：写之前过 `manuscriptown.write_refusal`，
别人的实例产出的稿受控拒（三态：归属不明也拒，不折成"允许"）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import manuscriptfamily as _MFAM
from .. import manuscriptids as _MI
from .. import manuscriptown as _OWN

#: 受控码（受控拒不只写在散文里）。
CODE_OWNED_BY_OTHER = _OWN.CODE_OWNED_BY_OTHER
CODE_OWNER_UNKNOWN = _OWN.CODE_OWNER_UNKNOWN


class _WriteReport:
    """`A.write_report`：把这一趟的检索/入库汇报写成一份稿。"""

    def write_report(self, *, markdown: str = "", summary: str = "",
                     title: str = "", path: str = "") -> dict[str, Any]:
        """写一份 A 的汇报稿（`manuscripts/A/a-report-<号>.md`），返回稿号与相对路径。

        三条边界：
        - 号由这一族自己发（`amanuscript`）：不借 F/B/E 的号段；
        - 写权：稿已存在时，只有它的 `产出者`（本实例）能再写；别人的稿受控拒
          （`manuscript_owned_by_other_instance`），归属不明也拒（`manuscript_owner_unknown`）；
        - 落点唯一：`manuscripts/A/<族>-<号>.md`，由 `manuscriptfamily.relpath` 一处拼。

        `path` 给了 ⇒ 覆盖同一份稿（仍要过写权，仍要属于 `a-report` 族）；
        不给 ⇒ 这一族发一个新号。
        """
        root = Path(str(getattr(self.store, "root", "") or ""))
        out: dict[str, Any] = {"checked": True, "written": False, "manuscript_id": "",
                               "rel": "", "refused": "", "reason": "", "owner": "",
                               "created": False}
        if not str(root):
            out.update(checked=False, refused="no_workspace",
                       reason="没有工作区根 ⇒ 汇报稿写不了（不是「没有要写的」）")
            return out
        body = str(markdown or "").strip()
        if not body:
            out.update(refused="empty_markdown",
                       reason="markdown 为空 ⇒ 这一笔没有内容要写（不写空稿）")
            return out

        want = str(path or "").strip().replace("\\", "/")
        if want:
            # 覆盖已存在的一份：必须是本族的名字，且写权归本实例。
            shape = _MFAM.classify_manuscript(want)
            if shape.get("family") != "a-report" or shape.get("tier") != _MFAM.TIER_FAMILY:
                out.update(refused="not_an_a_report",
                           reason=(f"`{want}` 不是 A 族规范名（要 "
                                   "`manuscripts/A/a-report-<号>.md`）"))
                return out
            rel = want
            mid = str(shape.get("manuscript_id") or "")
        else:
            mid = _MI.next_manuscript_id(root, family="a-report",
                                         owner=self._instance(), role="A")
            rel = _MI.canonical_rel(mid, family="a-report")

        who = self._instance()
        verdict = _OWN.write_refusal(root, rel, instance=who)
        out["owner"] = str(verdict.get("owner") or "")
        if not verdict.get("allowed"):
            out.update(refused=str(verdict.get("code") or "not_allowed"),
                       reason=str(verdict.get("why") or ""),
                       manuscript_id=mid, rel=rel)
            return out

        header = (f"# A 的汇报稿：{str(title or summary or '文献检索与入库').strip()}\n\n"
                  f"- 产出者：{who}\n- 摘要：{str(summary or '').strip()}\n"
                  f"- 稿号：{mid}（族 a-report）\n\n")
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(header + body + "\n", encoding="utf-8", newline="\n")
        out.update(written=True, manuscript_id=mid, rel=rel,
                   created=not bool(verdict.get("owner")),
                   reason=f"已写入 {rel}")
        return out

    def _instance(self) -> str:
        """本实例名（`agent-A-A1` 这种）；拿不到就退回角色名 —— 但那会退化成"同角色都能写"，
        所以调用方（写口）必须能拿到实例名。"""
        for name in ("actor", "instance"):
            got = str(getattr(self, name, "") or "").strip()
            if got:
                return got
        got = str(getattr(self, "name", "") or "").strip()
        return got or "agent-A"
