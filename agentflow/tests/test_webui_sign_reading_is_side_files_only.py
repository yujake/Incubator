# -*- coding: utf-8 -*-
"""判据：收工页的「签」只认逐份签文件 `<sha>.json`，台账 `issued.json` 只是索引。

## 改前是什么样（`draft/187` P1-1 / B1 的现场读数）

真机 lp-ball-11 的 `/api/package`：

```
proofs.signed = 0（页面上「V 已签 0」）
proofs.vsign  = {files: 1, signed: ["000005"], backed: [], without_sign: ["000005"],
                 source.path: "out/vsigns/issued.json"}
```

同一张卡下面印「V 签侧文件：在盘上 1 份 · 已签 1 · 有侧文件 0 · 无侧文件 1」——
同一个命题 000005 既「已签」又「无侧文件」，而且这一块的原文出处指着
`out/vsigns/issued.json`（派生台账）。`vsigns.INDEX_NAME` 的 docstring 逐字说
「它谁都不许拿来下结论，也不参与『签了几份』」。

## 三条

1. 台账不是签：只有 `issued.json` 时 `files=0` / `recomputable=0`，
   `ledger_present=True` 单独一格，`source.path` 不许是 `issued.json`；
2. 无侧文件是子集，不是第二个签数：`set(without_sign) <= set(signed)`，
   且 `signed` 是「第 3 位为真」（含历史签），`recomputable` 才是「签了几份」；
3. 反真空：放一份真的 `<sha>.json`（`statement_id` 对上）⇒ 这一条从
   `without_sign` 挪进 `backed`（证明 `without_sign` 是算出来的，不是常量）；
   再把旧形状（出处指台账 + files 把台账数进去）喂给检查函数 ⇒ 必须报红。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import vsigns as VS
from agentflow.webui import readers as R

#: 一条「第 3 位为真」的命题（bits.reviewed 与 reviewed_by_proof 都真）。
_PROOF = "夹具证明正文"
_STMT = "000001"


def _bits() -> dict[str, Any]:
    return {"numeric": "pending", "proof": True, "reviewed": True, "formal": "pending",
            "audited": False, "origin": "own_result",
            "evidence": {"numeric": {}, "numeric_reason": "", "proof_process": "",
                         "proof_source": "", "reviewed_by": {"F": _STMT},
                         "reviewed_source": "", "formal": {}, "formal_reason": "",
                         "audited_by": {}, "reviewed_by_proof": {"1": True}},
            "voided_by": {}, "grade": "proved", "audited_badge": False}


def _workspace(tmp_path: pathlib.Path, *, ledger: bool,
               sign: bool) -> pathlib.Path:
    """造一个只带 statements + out/vsigns 的最小工作区。"""
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True)
    (root / "out" / "vsigns").mkdir(parents=True)
    row = {"stmt_id": _STMT, "kind": "theorem", "label": "夹具", "statement_text": "T",
           "statement_full": "T", "proof_text": _PROOF, "status": "active",
           "bits": _bits()}
    (root / "data" / "statements.json").write_text(
        json.dumps({"schema_version": 2, "rows": [row]}, ensure_ascii=False),
        encoding="utf-8")
    if ledger:
        (root / "out" / "vsigns" / VS.INDEX_NAME).write_text(
            json.dumps({"schema": "vsigns-issued/1", "signs": []}, ensure_ascii=False),
            encoding="utf-8")
    if sign:
        sha = VS._sign_sha(_PROOF)
        (root / "out" / "vsigns" / f"{sha}.json").write_text(
            json.dumps({"schema": "v-sign-issued/1", "artifact_sha": sha,
                        "statement_id": _STMT, "proof_no": 1,
                        "at": "2026-11-19T00:00:00+08:00", "passes": []},
                       ensure_ascii=False),
            encoding="utf-8")
    return root


def _vsign(root: pathlib.Path) -> dict[str, Any]:
    pkg = R.package_face(root, project_dir=".")
    assert pkg["tri"] == "computed", (pkg["tri"], pkg["reason"])
    return pkg["proofs"]["vsign"]


#: 收工页（`Acceptance.tsx`）必须读的那几格 —— 少读一格，读者就回到「已签 1 / 无侧文件 1」。
_PAGE_MUST_READ = ("vsign.files", "vsign.recomputable", "vsign.ledger_present",
                   "vsign.ledger_path", "vsign.without_sign", "vsign.signed", "vsign.note")


def _page_problems(source: str) -> list[str]:
    """纯函数（可负控）：签那一块是不是按「台账 / 签文件 / 子集」三件事分开写的。"""
    problems = [f"收工页没有读 `proofs.{name}`" for name in _PAGE_MUST_READ
                if f"proofs.{name}" not in source]
    if "子集" not in source:
        problems.append("收工页没有说明「无侧文件是 signed 的子集」（读者会把它当第二个签数）")
    return problems


def _sign_problems(vsign: dict[str, Any]) -> list[str]:
    """纯函数（可负控）：「签」这一块的读数口径对不对。"""
    problems: list[str] = []
    path = str((vsign.get("source") or {}).get("path") or "")
    if path.endswith(VS.INDEX_NAME):
        problems.append(f"`source.path` 指着派生台账 {path!r}（台账不是签）")
    ledger_present = vsign.get("ledger_present")
    if ledger_present is True and int(vsign.get("files") or 0) >= 1 and path == "":
        problems.append("台账在盘上而 files 也数了它（台账不是签）")
    files = int(vsign.get("files") or 0)
    if ledger_present is False and files != 0:
        problems.append(f"台账不在盘上，而 files={files} 还是非 0（把台账数进去了？）")
    signed = set(vsign.get("signed") or [])
    without = set(vsign.get("without_sign") or [])
    backed = set(vsign.get("backed") or [])
    if not without <= signed:
        problems.append(f"`without_sign` 不是 `signed` 的子集：多 {sorted(without - signed)}")
    if not backed <= signed:
        problems.append(f"`backed` 不是 `signed` 的子集：多 {sorted(backed - signed)}")
    if without & backed:
        problems.append(f"同一条既「有侧文件」又「无侧文件」：{sorted(without & backed)}")
    return problems


# ====================================================================== 1 台账不是签
def test_the_ledger_alone_is_not_a_sign(tmp_path: pathlib.Path) -> None:
    """只有 `issued.json` ⇒ 0 份签；台账在不在是另一格；出处不许指台账。"""
    root = _workspace(tmp_path, ledger=True, sign=False)
    vsign = _vsign(root)
    assert _sign_problems(vsign) == [], _sign_problems(vsign)
    assert vsign["files"] == 0, vsign
    assert vsign["recomputable"] == 0, vsign
    assert vsign["ledger_present"] is True, vsign
    assert vsign["ledger_path"] == "out/vsigns/issued.json", vsign
    assert not str(vsign["source"]["path"]).endswith(VS.INDEX_NAME), vsign["source"]
    # 改前那一对矛盾数仍会出现在「第 3 位」那一轴：000001 签过（历史签），盘上没有侧文件。
    # 但它现在是 `signed` 的子集，且页面上分成两行写（不是两个「已签」并排）。
    assert vsign["signed"] == [_STMT], vsign
    assert vsign["without_sign"] == [_STMT], vsign


# ====================================================================== 2 子集
def test_without_sign_is_a_subset_of_signed_and_moves_when_a_file_lands(
        tmp_path: pathlib.Path) -> None:
    """反真空：放一份真签文件 ⇒ 同一条从 `without_sign` 挪进 `backed`。"""
    bare = _vsign(_workspace(tmp_path / "a", ledger=True, sign=False))
    with_file = _vsign(_workspace(tmp_path / "b", ledger=True, sign=True))
    assert bare["without_sign"] == [_STMT] and bare["backed"] == [], bare
    assert with_file["backed"] == [_STMT] and with_file["without_sign"] == [], with_file
    assert with_file["files"] == 1 and bare["files"] == 0, (with_file, bare)
    assert _sign_problems(with_file) == [], _sign_problems(with_file)
    # 反真空的第二半：把旧形状（出处指台账）喂给检查函数 ⇒ 必须报红。
    old = dict(with_file)
    old["source"] = {"path": "out/vsigns/issued.json", "line": 0, "match": "", "label": "V 签"}
    assert _sign_problems(old), "检查函数对「出处指台账」没报红 ⇒ 反真空失效"


# ====================================================================== 3 目录不在
def test_no_signs_dir_is_zero_not_unknown(tmp_path: pathlib.Path) -> None:
    """三态：没有 `out/vsigns/` ⇒ 0 份签（合法初态），台账那一格是「不在」，不是「不知道」。"""
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True)
    row = {"stmt_id": _STMT, "kind": "theorem", "label": "夹具", "statement_text": "T",
           "statement_full": "T", "proof_text": _PROOF, "status": "active",
           "bits": _bits()}
    (root / "data" / "statements.json").write_text(
        json.dumps({"schema_version": 2, "rows": [row]}, ensure_ascii=False),
        encoding="utf-8")
    vsign = _vsign(root)
    assert _sign_problems(vsign) == [], _sign_problems(vsign)
    assert vsign["files"] == 0 and vsign["ledger_present"] is False, vsign
    assert vsign["tri"] == "not_applicable", vsign


# ====================================================================== 4 页面
def test_the_acceptance_page_separates_ledger_files_and_the_subset() -> None:
    """页面那一半：收工页把「台账 / 签文件 / 子集」三件事分开读；负控能抓住退回旧读法。"""
    page = (pathlib.Path(__file__).resolve().parents[1] / "ui" / "src" / "pages"
            / "Acceptance.tsx").read_text(encoding="utf-8")
    assert _page_problems(page) == [], _page_problems(page)
    doctored = page.replace("proofs.vsign.recomputable", "proofs.vsign.files", 1)
    assert doctored != page, "负控没改到源码"
    assert any("recomputable" in p for p in _page_problems(doctored)), _page_problems(doctored)
