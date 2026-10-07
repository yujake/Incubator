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

import json
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


def test_cmd_artifacts_record_then_verify_returns_zero(tmp_path: pathlib.Path, capsys):
    """正控：`cli.cmd_artifacts` 的 record 与 verify 两个动词都退 0，且打印里有产物名。"""
    from argparse import Namespace

    from agentflow import cli

    _file(tmp_path, "out/paper/notes.md", "正文")
    rc = cli.cmd_artifacts(Namespace(command="artifacts", action="record", root=str(tmp_path),
                                     target=["out/paper/notes.md"], producer="G", kind="note",
                                     task_id="t-0001", exit_code=0, note="", json=False))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "notes.md" in out, out
    rc2 = cli.cmd_artifacts(Namespace(command="artifacts", action="verify", root=str(tmp_path),
                                      target=[], json=False))
    out2 = capsys.readouterr().out
    assert rc2 == 0, out2


def test_cmd_artifacts_verify_reports_changed_with_exit_one(tmp_path: pathlib.Path, capsys):
    """负控：产物被改过 ⇒ 退出码 1（"查过了、有变了的产物"），不是 0 也不是 2。"""
    from argparse import Namespace

    from agentflow import cli

    f = _file(tmp_path, "out/a.txt", "第一版")
    cli.cmd_artifacts(Namespace(command="artifacts", action="record", root=str(tmp_path),
                                target=["out/a.txt"], producer="E", kind="data",
                                task_id="", exit_code=0, note="", json=False))
    f.write_text("第二版", encoding="utf-8")
    rc = cli.cmd_artifacts(Namespace(command="artifacts", action="verify", root=str(tmp_path),
                                     target=[], json=False))
    capsys.readouterr()
    assert rc == 1, "被改过的产物必须让 verify 退 1"


def test_cmd_artifacts_list_is_read_only(tmp_path: pathlib.Path, capsys):
    """正控：`list` 只读，不写台账。"""
    from argparse import Namespace

    from agentflow import cli

    _file(tmp_path, "out/b.txt", "x")
    rc = cli.cmd_artifacts(Namespace(command="artifacts", action="list", root=str(tmp_path),
                                     target=[], producer="", task_id="", kind="",
                                     json=False))
    capsys.readouterr()
    assert rc == 0
    assert not (tmp_path / "ARTIFACTS.jsonl").exists(), "list 不许写台账"


# ============================================================ EE-11：producer 的写入期口径


def test_ee11_an_unregistered_producer_is_written_and_shown_not_rejected(tmp_path: pathlib.Path):
    """EE-11（主控裁定 2026-10-06）：写入期可见，不是写入期否决。

    两条依据（成本序）：① 外部脚本（真机 2985 行 `paper-generator`）的产出不许因为
    "框架没登记这个名字"就消失 —— 台账少一行 = 下游读不到那份产物（不可逆的信息损失）；
    ② 但"静默长轴"也不许发生 ⇒ 用读数解决（`summarize()["unregistered"]` 点名 + 计数）。
    判据三半：① 拼错的名字照写且读数点名（改前：静默写入、读数什么都不说）；
    ② 反负控：登记过的 / 角色 / 主控 / `tool:<名>` ⇒ 不出现在 `unregistered` 里；
    ③ 畸形（空 / 换行 / 超长）⇒ 仍然拒（那是坏输入，不是"未登记的外部名"）。
    """
    from agentflow import artifacts as A

    _file(tmp_path, "out/r.md", "x")
    known = ("G", "E", "M", "tool:fs.write", "agentflow.paperbuild",
             "paper-generator")          # 最后一个是已登记的"已知"外部生产者
    for good in known:
        assert A.producer_is_known(good), good
        A.record(tmp_path, path="out/r.md", producer=good, kind="report")
    # ① 拼错的名字：照写（不抛）+ 读数点名
    entry = A.record(tmp_path, path="out/r.md", producer="paper-genrator", kind="report")
    assert entry["producer"] == "paper-genrator", "未登记的名字照写台账（不许丢行）"
    assert not A.producer_is_known("paper-genrator")
    summ = A.summarize(tmp_path)
    assert summ["unregistered"] == {"paper-genrator": 1}, summ["unregistered"]
    assert summ["by_producer"]["paper-genrator"] == 1, summ["by_producer"]

    # ② 反负控：已知的那些一个都不许进 `unregistered`
    for good in known:
        assert good not in summ["unregistered"], (good, summ["unregistered"])

    # ③ 畸形仍然拒（两档不许折成一档）
    for bad in ("", "   ", "a\nb", "x" * (A.PRODUCER_MAX_CHARS + 1)):
        with pytest.raises(A.ArtifactError):
            A.record(tmp_path, path="out/r.md", producer=bad, kind="report")
    assert A.producer_problem("") != "" and A.producer_problem("a\nb") != ""
    assert A.producer_problem("paper-genrator") == "", "未登记不是畸形"


def test_ee11_the_read_path_still_reads_legacy_producers(tmp_path: pathlib.Path):
    """读路径一个字都不改：历史行里的未登记 producer 不许因为"今天没登记"就读不出来。

    （`store.rebuild` 会重放同一批行；读路径上加名单 = 数据遗失。）
    """
    from agentflow import artifacts as A

    _file(tmp_path, "out/legacy.md", "x")
    legacy = {"at": "2026-01-01T00:00:00+00:00", "path": "out/legacy.md",
              "sha256": A.sha256_of(tmp_path / "out" / "legacy.md"), "bytes": 1,
              "producer": "某个早已不在仓库里的外部脚本", "kind": "report",
              "task_id": "", "exit_code": None, "note": ""}
    (tmp_path / "ARTIFACTS.jsonl").write_text(json.dumps(legacy, ensure_ascii=False) + "\n",
                                              encoding="utf-8")
    rows, bad = A.read_ledger(tmp_path)
    assert not bad and len(rows) == 1, (rows, bad)
    assert rows[0]["producer"] == "某个早已不在仓库里的外部脚本"
    assert A.list_artifacts(tmp_path, producer="某个早已不在仓库里的外部脚本"), "按 producer 过滤也要读得到"

