"""`R-52` 余的判据：产物归属登记（`agentflow.artifacts`）。

这一组回答四件事（每条都要正控 + 注入负控，与全仓同一条纪律）：

1. 登记 → 核对 → 归属：一个真文件登记之后 `verify_entries` 报 `ok`、`owners_of` 给出生产者；
2. 注入负控两种形态：篡改必须报 `changed`、删除必须报 `missing` ——
   两者不许折成同一个状态，更不许折成 `ok`；
3. fail-closed：不存在的文件、越界路径 ⇒ 拒收，且台账一个字节都不许多；
4. 坏行与"没登记"必须与"干净"分开：坏行逐条报出，`unowned` 认得出没有归属的路径。

 本文件与 `temp/_r52_probe.py` 是同一批判据的两种落点（探针给读数、本文件给回归）。
它们本轮都没有被跑过（所有者指定不跑门测试）：`tests/` 下所有用例的状态是
"写下了、未执行"，放开跑门时必须真跑。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import artifacts as A


def _file(root: pathlib.Path, rel: str, text: str = "内容") -> pathlib.Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_record_then_verify_ok_and_owner_is_known(tmp_path: pathlib.Path):
    """正控：登记 → 哈希与盘上一致 → 核对 ok → 归属给出生产者。"""
    f = _file(tmp_path, "out/report.md")
    entry = A.record(tmp_path, path="out/report.md", producer="G", kind="report",
                     task_id="t-0001")
    assert entry["sha256"] == A.sha256_of(f)
    assert entry["bytes"] == f.stat().st_size
    assert A.ledger_path(tmp_path).is_file()
    assert [c["status"] for c in A.verify_entries(tmp_path)] == ["ok"]
    owners = A.owners_of(tmp_path, "out/report.md")
    assert [(o["producer"], o["kind"], o["task_id"]) for o in owners] == [("G", "report", "t-0001")]


def test_tampered_file_reports_changed_not_ok(tmp_path: pathlib.Path):
    """注入负控①：文件被改过 ⇒ `changed`（不是 ok）。"""
    f = _file(tmp_path, "out/a.json", "第一版")
    A.record(tmp_path, path="out/a.json", producer="E")
    f.write_text("第二版", encoding="utf-8")
    checks = A.verify_entries(tmp_path)
    assert [c["status"] for c in checks] == ["changed"]
    assert checks[0]["sha256"] != checks[0]["sha256_now"]


def test_deleted_file_reports_missing_not_changed(tmp_path: pathlib.Path):
    """注入负控②：文件不在了 ⇒ `missing`（与"被改过"是两种处置）。"""
    f = _file(tmp_path, "out/b.json")
    A.record(tmp_path, path="out/b.json", producer="E")
    f.unlink()
    assert [c["status"] for c in A.verify_entries(tmp_path)] == ["missing"]


def test_refuses_unknown_and_outside_paths_without_touching_ledger(tmp_path: pathlib.Path):
    """fail-closed：拒收之后台账一个字节都不许多（"先记账后产出"会让台账变成愿望清单）。"""
    _file(tmp_path, "out/c.md")
    A.record(tmp_path, path="out/c.md", producer="M")
    before = A.ledger_path(tmp_path).read_bytes()
    with pytest.raises(A.ArtifactError, match="文件不存在"):
        A.record(tmp_path, path="out/不存在.md", producer="M")
    with pytest.raises(A.ArtifactError, match="越出工作区"):
        A.record(tmp_path, path="../越界.md", producer="M")
    assert A.ledger_path(tmp_path).read_bytes() == before


def test_bad_line_is_reported_not_swallowed(tmp_path: pathlib.Path):
    """坏行逐条报出，且 `summarize` 把它与"干净"分开。"""
    _file(tmp_path, "out/d.md")
    A.record(tmp_path, path="out/d.md", producer="M")
    with A.ledger_path(tmp_path).open("a", encoding="utf-8") as fh:
        fh.write("{坏行\n")
    records, bad = A.read_ledger(tmp_path)
    assert len(records) == 1 and len(bad) == 1
    assert A.summarize(tmp_path)["bad_lines"] == 1


def test_unowned_finds_paths_without_registration(tmp_path: pathlib.Path):
    """`unowned` 是本模块唯一的判断：没登记的路径必须被认出来（A4 那六个就是靠它）。"""
    a = _file(tmp_path, "code/a.py")
    b = _file(tmp_path, "code/b.py")
    A.record(tmp_path, path="code/a.py", producer="M", kind="script")
    assert A.unowned(tmp_path, [a, b]) == ["code/b.py"]
    A.record(tmp_path, path="code/b.py", producer="M", kind="script")
    assert A.unowned(tmp_path, [a, b]) == []


def test_render_markdown_carries_status_column(tmp_path: pathlib.Path):
    """渲染出来的表必须带"现状"列：只列 sha256 会让人以为"列出来就是对的"。"""
    _file(tmp_path, "out/e.md")
    A.record(tmp_path, path="out/e.md", producer="G", kind="report")
    text = A.render_markdown(tmp_path)
    assert "| 路径 | 生产者 | 类别 | 召唤 | 退出码 | 字节 | sha256 | 现状 |" in text
    assert "| ok |" in text


def test_selftest_passes():
    """模块自带的自检（登记→核对→篡改→删除→越界→坏行）必须过。"""
    assert A.selftest() == 0
