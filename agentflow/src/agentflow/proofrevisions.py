# -*- coding: utf-8 -*-
"""手稿登记条目的收工读数。

`proofregistry` 的写入口做的是登记 / 重写（含形态闸、槽位识别、落盘事务）；本模块
只读数（`entries_on_disk` / `proof_revisions`，收工门与状态报告要读的登记与证明
读数）。两者共用同一份 `proofregistry.parse_entry`，不重写第二套解析。

`proofregistry` 回引本模块的三个函数，所以 `proofregistry.proof_revisions` 等既有
名字照旧可读。本模块不写盘。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def entries_on_disk(root: Any) -> list[dict[str, Any]]:
    """扫 `reports/` 下的证明手稿，返回逐份的登记条目（纯读）。"""
    from . import manuscriptform as _MF
    from .proofregistry import parse_entry

    base = Path(str(root or "")) / _MF.MANUSCRIPT_DIR
    out: list[dict[str, Any]] = []
    if not base.is_dir():
        return out
    for family, prefix in ((_MF.FAMILY_F, _MF.PREFIX[_MF.FAMILY_F]),
                           (_MF.FAMILY_B, _MF.PREFIX[_MF.FAMILY_B])):
        for path in sorted(base.glob(f"{prefix}*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            got = parse_entry(text)
            rel = f"{_MF.MANUSCRIPT_DIR}/{path.name}"
            if not got.get("checked"):
                continue
            out.append({"family": family, "path": rel, "label": str(got.get("label") or ""),
                        "statement_id": str(got.get("statement_id") or ""),
                        "proof_no": int(got.get("proof_no") or 0),
                        "sha256": str(got.get("sha256") or ""),
                        "versions": [dict(v) for v in (got.get("versions") or [])],
                        "kind": str(got.get("kind") or "")})
    return out


def proof_revisions(store: Any) -> dict[str, Any]:
    """逐命题读「登记了几次 / 那份证明的 sha 与 proof_no / 被判有毛病几次」。

    "登记了几次"按条目算（一条在册命题的手稿条目 = 一次登记；同一个 label 只有一份
    手稿 —— 一个稿号 = 一份文件 = 一份证明）；"被判有毛病"读两处：形态闸台账
    （`proposition_form`）与计划历史里那些 `proposition_form_refused` /
    `proposition_text_changed` 的拒收行。
    """
    from . import manuscriptform as _MF

    out: dict[str, Any] = {"checked": False, "propositions": [], "problems": [],
                           "registrations": 0, "proof_versions": 0,
                           "checked_from": f"{_MF.MANUSCRIPT_DIR}/*proof-*.md",
                           "reason": ""}
    root = str(getattr(store, "root", "") or "")
    if not root:
        out["reason"] = "这一层没有工作区根 ⇒ 手稿登记读不到（没查成）"
        return out
    try:
        on_disk = entries_on_disk(root)
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        out["reason"] = f"手稿目录读不出来（{type(exc).__name__}: {exc}）⇒ 没查成"
        return out
    out["checked"] = True
    refused_by_label: dict[str, int] = {}
    try:
        from . import secretary as _SEC

        for one in _SEC.proposition_form_rows(root):
            # 这本台账是 F 与 E 共用的（同一道形态闸也覆盖 E 的数值证明路线）。这一格
            # 数的是"F 的手稿登记被拒了几次" ⇒ 只认 F 自己的行（role 缺省为空的历史
            # 行也归 F）；E 的拒收进 `closing.proposition_form_reading` 的
            # `by_role["E"]`，不在这里冒充 F。
            if str(one.get("role") or "") not in ("", "F"):
                continue
            if one.get("checked") and not one.get("well_formed"):
                key = str(one.get("label") or "")
                refused_by_label[key] = refused_by_label.get(key, 0) + 1
    except Exception as exc:  # noqa: BLE001 —— 台账读不到只少一格，不改"查过了"的那一半
        out["problems"].append(f"形态闸台账读不出来：{type(exc).__name__}: {exc}")
    for one in on_disk:
        versions = [dict(v) for v in (one.get("versions") or [])]
        if not versions:
            versions = [{"proof_no": int(one.get("proof_no") or 0),
                         "at": "", "sha256": str(one.get("sha256") or "")}]
        label = str(one.get("label") or "")
        out["propositions"].append({
            "family": str(one.get("family") or ""),
            "label": label,
            "statement_id": str(one.get("statement_id") or ""),
            "manuscript_path": str(one.get("path") or ""),
            "registrations": 1,
            "proof_count": len(versions),
            "versions": [{"proof_no": int(v.get("proof_no") or 0),
                          "sha256": str(v.get("sha256") or ""),
                          "at": str(v.get("at") or "")} for v in versions],
            "problems": int(refused_by_label.get(label, 0)),
        })
    out["registrations"] = sum(int(p["registrations"]) for p in out["propositions"])
    out["proof_versions"] = sum(int(p["proof_count"]) for p in out["propositions"])
    if not out["propositions"]:
        out["reason"] = ("查过了：`reports/` 下没有一份带登记条目的证明手稿 ⇒ "
                         "这个读数不是「命题登记一次、证明改 N 次」的那种形态")
    else:
        out["reason"] = (f"查过了：{len(out['propositions'])} 条手稿登记、"
                         f"{out['proof_versions']} 个证明版本 —— "
                         + "；".join(f"{p['label'] or p['manuscript_path']}：登记 "
                                    f"{p['registrations']} 次 / 证明 {p['proof_count']} 版 / "
                                    f"有毛病 {p['problems']} 次"
                                    for p in out["propositions"][:6])
                         + "（读数，不拦门）")
    return out


def registration_note() -> str:
    """提示词里那一句（正面表述：改证明不需要重新登记）。"""
    return ("你登记一条**新命题**时，你的秘书会先看它是否写清了「从什么条件导出什么结论」；"
            "已经在登记里的命题**重写证明**时不再过这一步 —— 改证明不需要重新登记。")
