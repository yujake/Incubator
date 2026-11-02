# -*- coding: utf-8 -*-
"""签文件里的 `manuscript_write` 那一格：三态，不许折成 `null`（2026-11-02）。

## 84 的现场读数（这就是这一份判据要堵的形态）

`projects/paper-rewrite-84/out/vsigns/` 里两份签文件（`a6fa76d2` / `dcb988fa`）
都没有 `manuscript_write` 这一格 —— 读出来是 `null`。可是
`reports/f-proof-000000.md` 里明明有一行：

```text
- V 签：已签=true；…；台账=verifications/000000.jsonl#v-000010；命题号=000000
```

那一行正是 `write_sign` 里"顺手把签块盖进手稿"那一步盖的（V 未在册那一支写的是
`台账=reports/…#V签`、`命题号=未在册`，84 的另一份 `f-proof-000001.md` 就是那个形状）。
问题不在块有没有写，而在写块那一步的结果只活在返回值里：签文件落盘发生在盖章
之前，`manuscript_write` 从来没被写进文件。于是读数与实际脱节，将来排查会照 `null`
去找，而实际已经写成。

## 这一份钉什么

| 判据 | 造什么 | 它要红成什么样 |
|---|---|---|
| a | 发签 + 写块成功 | 签文件里 `state != "written"`、没有 `path`/`line`、或块不在稿里 |
| b | 发签 + 手稿不在盘上 | 签文件里没有明确失败原因（`state=failed` + `why` 说为什么） |
| c | 发签 + 没有手稿路径 | 折成 `failed` 或 `null` 都红；必须是 `not_attempted` + 理由 |
| d | 旧版签文件（没有这一格） | 读侧必须落 `unrecorded`（不是 `null`、也不是 `not_attempted`） |
| e | 同一份正文再发一次签 | 一稿一签：签文件逐字节不变（补这一格只发生在新签上） |

三条写侧状态的词表在 `vsigns.MANUSCRIPT_WRITE_STATES`；读侧第四档是
`vsigns.MANUSCRIPT_WRITE_UNRECORDED`。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import vsigns as VSP

TS = "2026-11-02T16:43:01+08:00"
SHA = "d" * 64
MANUSCRIPT = "reports/f-proof-000000.md"
PROOF = ("# F 的证明手稿：夹具\n"
         "\n"
         "- 命题号：stmt:000000\n"
         "- 计划：000001\n"
         "\n"
         "## 命题\n"
         "\n"
         "夹具命题。\n"
         "\n"
         "## 证明\n"
         "\n"
         "1. 夹具第一步。\n"
         "2. 夹具第二步。\n")


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "ws"
    (root / "reports").mkdir(parents=True)
    (root / MANUSCRIPT).write_text(PROOF, encoding="utf-8")
    return root


def _issue(root: pathlib.Path, *, artifact_path: str = MANUSCRIPT) -> dict:
    """发一份签（门栏 3/3 已满足，所以走的是"真的落盘"那一条路）。"""
    return VSP.write_sign(
        root, artifact_sha=SHA, streak=3, need=3, artifact_path=artifact_path,
        ledger="verifications/000000.jsonl#v-000010", statement_id="000000",
        proof_no=1, at=TS)


def _sign_doc(root: pathlib.Path) -> dict:
    path = VSP.sign_path(root, SHA)
    return json.loads(path.read_text(encoding="utf-8"))


def _block_line(root: pathlib.Path) -> int:
    text = (root / MANUSCRIPT).read_text(encoding="utf-8")
    for no, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith(VSP.SIGN_MARK):
            return no
    return 0


# ====================================================================== a 成功
def test_a_a_written_block_is_recorded_with_its_location(tmp_path: pathlib.Path) -> None:
    """发签 + 写块成功 ⇒ 签文件里 `state=written`、带 `path` 与 `line`。"""
    root = _workspace(tmp_path)
    got = _issue(root)

    # 返回的那一笔先看：它说的和文件里写的必须是同一件事。
    mw = got["manuscript_write"]
    assert mw["state"] == "written", mw
    assert mw["written"] is True, mw
    assert mw["path"] == MANUSCRIPT, mw
    assert mw["line"] == _block_line(root) > 0, (mw, _block_line(root))
    assert got["manuscript_write_recorded"] is True, got

    doc = _sign_doc(root)
    assert "manuscript_write" in doc, (
        "新签文件里没有 manuscript_write 那一格 ⇒ 读数仍会读成 null")
    got_doc = VSP.manuscript_write_reading(doc)
    assert got_doc["state"] == "written", doc["manuscript_write"]
    assert got_doc["path"] == MANUSCRIPT, got_doc
    assert got_doc["line"] == _block_line(root), got_doc
    assert got_doc["why"], "写成功也要说清落在哪一份稿（why 不许空）"
    # 块真的在稿里，而且读得出来（不是只写了一个数字）。
    text = (root / MANUSCRIPT).read_text(encoding="utf-8")
    assert text.splitlines()[got_doc["line"] - 1].strip().startswith(VSP.SIGN_MARK)
    assert VSP.manuscript_sign_reading(text)["found"] is True


# ====================================================================== b 失败
def test_b_a_failed_block_write_says_why(tmp_path: pathlib.Path) -> None:
    """发签 + 写块失败 ⇒ 签文件里 `state=failed` + 明确原因（不折成 null）。"""
    root = _workspace(tmp_path)
    got = _issue(root, artifact_path="reports/not-there.md")

    mw = got["manuscript_write"]
    assert mw["state"] == "failed", mw
    assert mw["written"] is False and mw["missing"] is True, mw
    assert "不在盘上" in mw["why"], mw
    # 签文件仍然落盘（签已经发了这件事不许消失），并带着失败原因。
    assert got["written"] is True, got
    doc = _sign_doc(root)
    shown = VSP.manuscript_write_reading(doc)
    assert shown["state"] == "failed", doc.get("manuscript_write")
    assert "不在盘上" in shown["why"], shown
    assert shown["path"] == "reports/not-there.md", shown
    # 没写成就不许报块的位置。
    assert shown["line"] == 0, shown


# ====================================================================== c 未尝试
def test_c_no_manuscript_path_is_not_attempted_not_failed(tmp_path: pathlib.Path) -> None:
    """发签 + 没有手稿落点 ⇒ `not_attempted`（"没得写"不是"写失败"）。"""
    root = _workspace(tmp_path)
    got = _issue(root, artifact_path="")

    mw = got["manuscript_write"]
    assert mw["state"] == "not_attempted", mw
    assert mw["written"] is False and mw["missing"] is False, mw
    assert "未尝试" in mw["why"], mw
    doc = _sign_doc(root)
    shown = VSP.manuscript_write_reading(doc)
    assert shown["state"] == "not_attempted", doc.get("manuscript_write")
    assert "未尝试" in shown["why"], shown


# ====================================================================== d 旧签
def test_d_a_legacy_sign_file_reads_as_unrecorded_not_null(tmp_path: pathlib.Path) -> None:
    """旧版签文件没有这一格 ⇒ `unrecorded`（"当时没记录"），不冒充三态里的任何一档。"""
    shown = VSP.manuscript_write_reading({"schema": VSP.SIGN_SCHEMA})
    assert shown["state"] == VSP.MANUSCRIPT_WRITE_UNRECORDED, shown
    assert shown["state"] not in VSP.MANUSCRIPT_WRITE_STATES, shown
    assert shown["why"], "没记录也要说清为什么（不许静默回 None）"
    # 坏词同样不读成成功。
    bad = VSP.manuscript_write_reading({"manuscript_write": {"state": "done"}})
    assert bad["state"] == VSP.MANUSCRIPT_WRITE_UNRECORDED, bad
    # 84 那两份签文件的形状（没有这一格）就是这一档的现场。
    assert VSP.manuscript_write_reading(None)["state"] == VSP.MANUSCRIPT_WRITE_UNRECORDED


# ====================================================================== e 一稿一签
def test_e_an_existing_sign_is_not_rewritten(tmp_path: pathlib.Path) -> None:
    """同一份正文再发一次签 ⇒ 签文件逐字节不变（补格子只发生在新签上）。"""
    root = _workspace(tmp_path)
    first = _issue(root)
    assert first["written"] is True, first
    path = VSP.sign_path(root, SHA)
    before = path.read_bytes()

    second = _issue(root)
    assert second["idempotent"] is True, second
    assert second["written"] is False, second
    assert path.read_bytes() == before, (
        "第二次发签把签文件重写了 ⇒ 一稿一签被破坏（补 manuscript_write 只许发生在新签上）")
