"""判据：网页上「签文件」与「签台账」是两个数，不是同一个数。

## 为什么要有这一条（业主点名的读数口径错）

`out/vsigns/` 目录里有两类 `.json`：

- 逐份签文件 `<artifact_sha>.json` —— 证据（一份稿一份签）；
- 派生归档 `issued.json` —— 台账 / 索引（"V 侧发过哪些签"的一眼清单，
  `vsigns.INDEX_NAME`；谁都不许拿它下结论）。

两者形状相同、含义不同。前一版网页把 `out/vsigns/*.json` 的文件个数当成
"签了几份"，于是真机 lp-ball-10 的现场（3 份签 + 1 份 `issued.json`）在页面上
读成 4 份签 —— 多出来的那一份是台账。

## 判据的两半

1. 后端读数：`run_digest()` 的 `signs` 那一块把两类分开数 ——
   `signs.files` 不含 `issued.json`（口径单一来源 `vsigns.credentials_reading`），
   `signs.ledger_present` 单独回答"那份台账在不在"；`sign_files` 保持原义
   （目录里全部 JSON 的个数，含台账），两个名字不许互相顶替。
2. 页面读数：`Run.tsx` 的档案格必须同时读 `signs.files` 与 `signs.ledger_present`，
   并且把"不含台账"这件事写在读的人眼前 —— 只改后端不改页面，读的人看到的仍是
   一个孤零零的数字。

反真空（两条负控）：

- 删掉 `issued.json` ⇒ `sign_files` 与 `signs.files` 同时减一（它们确实各数各的）；
- 把台账重新放回去 ⇒ 两者又分开（不是"碰巧相等"）。

## 量法

不另写一套 glob：本判据直接调 `webui.readers.run_digest()`，再拿
`vsigns.credentials_reading()` 当第二读数对账（"签数"的唯一来源）。
"""
from __future__ import annotations

import json
import pathlib
import re

from agentflow import vsigns as VS
from agentflow.webui import readers as RD

REPO = pathlib.Path(__file__).resolve().parents[1]
RUN_TSX = REPO / "ui" / "src" / "pages" / "Run.tsx"

#: 一份签文件的形状（`credentials_reading` 只读它自己的键；这里给足以免被当成坏 JSON）。
_SIGN = {
    "schema": "v-sign-issued/1",
    "artifact_sha": "0" * 64,
    "statement_id": "000001",
    "proof_no": 1,
    "at": "2026-11-19T00:00:00+08:00",
    "passes": [],
}


def _put_signs(root: pathlib.Path, n: int = 3, *, ledger: bool = True) -> list[pathlib.Path]:
    """造 `n` 份逐份签文件；`ledger=True` 时再放一份 `issued.json` 台账。"""
    folder = root / "out" / "vsigns"
    folder.mkdir(parents=True, exist_ok=True)
    made: list[pathlib.Path] = []
    for i in range(n):
        path = folder / f"{i:064x}.json"
        path.write_text(json.dumps({**_SIGN, "statement_id": f"{i:06d}"},
                                   ensure_ascii=False) + "\n", encoding="utf-8")
        made.append(path)
    if ledger:
        (folder / VS.INDEX_NAME).write_text(
            json.dumps({"schema": "vsigns-issued/1", "signs": []}, ensure_ascii=False) + "\n",
            encoding="utf-8")
    return made


def test_the_digest_counts_sign_files_and_the_ledger_separately(tmp_path: pathlib.Path) -> None:
    """正控：3 份签 + 1 份台账 ⇒ `sign_files=4` 而 `signs.files=3`。"""
    _put_signs(tmp_path, 3, ledger=True)
    dig = RD.run_digest(tmp_path)
    signs = dig["signs"]
    assert dig["sign_files"] == 4, dig["sign_files"]
    assert signs["files"] == 3, signs
    assert signs["ledger_present"] is True, signs
    assert signs["ledger_path"] == "out/vsigns/issued.json", signs
    # 口径的单一来源：签文件的份数就是 `vsigns.credentials_reading` 的 `files`
    # （它自己排除了 INDEX_NAME）。本层不另写一份过滤。
    cred = VS.credentials_reading(tmp_path)
    assert signs["files"] == cred["files"] == 3, (signs, cred)
    assert signs["recomputable"] == cred["recomputable"], (signs, cred)
    assert signs["unbacked"] == cred["unbacked"], (signs, cred)
    assert signs["checked"] is True, signs


def test_the_ledger_is_not_a_sign_after_it_is_removed(tmp_path: pathlib.Path) -> None:
    """负控：删掉台账 ⇒ 两个数同时减一；放回去 ⇒ 又分开（不是碰巧相等）。"""
    _put_signs(tmp_path, 3, ledger=True)
    before = RD.run_digest(tmp_path)
    ledger = tmp_path / "out" / "vsigns" / VS.INDEX_NAME
    ledger.unlink()
    gone = RD.run_digest(tmp_path)
    assert before["sign_files"] == 4 and gone["sign_files"] == 3, (before, gone)
    assert before["signs"]["files"] == 3 == gone["signs"]["files"], (before, gone)
    assert gone["signs"]["ledger_present"] is False, gone["signs"]
    # 反真空：把台账放回去，两个数重新分开（这条证明上一行不是"永远相等"）。
    ledger.write_text('{"schema": "vsigns-issued/1", "signs": []}\n', encoding="utf-8")
    back = RD.run_digest(tmp_path)
    assert back["sign_files"] == 4 and back["signs"]["files"] == 3, back
    assert back["signs"]["ledger_present"] is True, back["signs"]


def test_a_missing_signs_dir_is_zero_not_unknown(tmp_path: pathlib.Path) -> None:
    """三态：目录不在 ⇒ 两个数都是 0（这个工作区还没有签，是事实不是没查成）。"""
    dig = RD.run_digest(tmp_path)
    assert dig["sign_files"] == 0, dig["sign_files"]
    assert dig["signs"]["files"] == 0, dig["signs"]
    assert dig["signs"]["ledger_present"] is False, dig["signs"]
    assert dig["signs"]["checked"] is True, dig["signs"]


#: 档案格里必须出现的几个读数名（页面那一半）。
_PAGE_MUST_HAVE = (
    "digest.data.signs.files",        # 逐份签文件（不含台账）
    "digest.data.signs.ledger_present",  # 台账在不在
    "digest.data.signs.ledger_path",
    "签台账",
    "不含台账",
)


def _page_problems(source: str) -> list[str]:
    """纯函数（可负控）：档案格读没读"签文件 / 签台账"分开的那几格。"""
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    at = code.find("趟次档案")
    if at < 0:
        return ["页面里没有档案格（「趟次档案」这张卡）"]
    region = code[at:at + 6000]
    problems = [f"档案格没有读 `{name}`" for name in _PAGE_MUST_HAVE if name not in region]
    if "digest.data.sign_files" not in region:
        problems.append("档案格没有读 digest.data.sign_files（目录里全部 JSON 的个数）")
    return problems


def test_the_page_reads_the_two_sign_cells_apart() -> None:
    """页面那一半：档案格里签文件与签台账分开写；负控能抓住退回旧读法。"""
    source = RUN_TSX.read_text(encoding="utf-8")
    assert _page_problems(source) == [], _page_problems(source)
    # 负控：删掉"不含台账"那几个读数 ⇒ 必须报（否则读的人又把 4 当签数）。
    doctored = source.replace("digest.data.signs.ledger_present", "digest.data.sign_files", 1)
    assert doctored != source, "负控没改到源码"
    assert any("ledger_present" in p for p in _page_problems(doctored)), (
        _page_problems(doctored))
