# -*- coding: utf-8 -*-
"""E5 第二半：`rebuild_run_index` 必须有生产入口，索引才会自己出现。

## 改前读数（2026-11-03 清点 E5；本文件把"零调用者"变成机器判据）

- `projects/` 下 156 个工作区，`index/run-index.json` 0 份；
- 全仓 `rebuild_run_index` 的调用者只有 tests（`tests/test_run_index.py`、
  `tests/test_webui_pages.py`）⇒ `/api/run-index` 在真实工作区恒为
  `{"usable": false, "tri": "unreadable", ...}`，而页面那一半已经诚实地说
  "没有索引可对账"—— 于是索引永远不会自己出现。

## 两个生产入口（都调 `conductor.rebuild_run_index` 这一个函数）

1. 顶趟收工成功那一步（`Conductor.finish_top_level_run`，`stop_reason == "final"`）；
2. 一条显式命令：`agentflow project rebuild-run-index --workspace <工作区>`。

页面 / `/api/*` 一律不写盘（GET 不建索引）：那是本文件的守卫判据，不是入口。

| 判据 | 它钉的是 | 改前红在哪 |
|---|---|---|
| ① `test_a_finished_top_level_run_leaves_an_index_the_api_can_read` | 收工成功 ⇒ 盘上有索引、`/api/run-index` 读得出（真 HTTP） | 改前 0 份索引，收工后也还是 0 |
| ② `test_an_incomplete_run_neither_builds_nor_overwrites` | 收工不完整（非 `final`）⇒ 不建，也不覆盖已有索引（逐字节） | 改前不红（没有生产者就没有覆盖）；它守的是"补入口时别把半截运行也建进去" |
| ③ `test_the_cli_builds_for_any_workspace_and_is_idempotent` | 显式命令对任意工作区建、跑两次字节相同、退出码 0 | 改前没有这条命令 |
| ④ `test_a_failed_build_is_checked_false_with_reason_and_lands_in_the_audit` | 建索引失败不许静默：`checked=False` + 原因 + 进 `data/events.jsonl` 审计、退出码 2 | 改前没有这条命令，也没有这条审计 |
| ⑤ `test_a_get_request_never_builds_the_index` | `GET /api/run-index` 不写盘 | 守卫（改前后都绿；它守的是以后别顺手接成 GET 写盘） |
"""
from __future__ import annotations

import http.client
import json
import pathlib
import threading
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from agentflow import cli
from agentflow import sessions as SS
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.webui import readers as R

TS = "2026-11-03T00:00:00+08:00"


# ====================================================================== 夹具
def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个有会话（一趟真 run）的初始化工作区。"""
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "E5 夹具",
                     "ts": TS}, sid="s1")
    SS.append(root, {"kind": "agent_step", "role": "M", "shape": "fs.write",
                     "payload": {"path": "out/review/REPORT.md"},
                     "result": {"ok": True}, "ts": TS}, sid="s1")
    SS.append(root, {"kind": "agent_run_end", "role": "M", "stop_reason": "final",
                     "final": "写完了", "final_chars": 3, "ts": TS}, sid="s1")
    return root


def _conductor(root: pathlib.Path) -> tuple[Conductor, str]:
    """真 Store + 真 Conductor + 一条顶趟行（与生产同形：`open_top_level_run`）。"""
    st = Store(root)
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    owner = str(cond.open_top_level_run("M", "E5：收工那一笔"))
    return cond, owner


def _index_events(root: pathlib.Path) -> list[dict[str, Any]]:
    """`data/events.jsonl` 里与建索引有关的那几行。"""
    path = root / "data" / "events.jsonl"
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if str(row.get("message") or "") == "run_index_rebuild":
            out.append(row)
    return out


@contextmanager
def _server(root: pathlib.Path) -> Iterator[str]:
    """在临时端口上起一个真服务（判据走 HTTP：`/api/run-index` 是页面读的那一条）。"""
    from agentflow import webui as W

    srv = W.serve(root, host="127.0.0.1", port=0, csrf_token="runindextoken0123456789")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _get(base: str, path: str) -> tuple[int, Any]:
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read().decode("utf-8"))
    finally:
        conn.close()


def _run_cli(argv: list[str], capsys) -> tuple[int, str, str]:
    code = cli.main(argv)
    got = capsys.readouterr()
    return code, got.out, got.err


# ====================================================================== ① 收工成功
def test_a_finished_top_level_run_leaves_an_index_the_api_can_read(
        tmp_path: pathlib.Path) -> None:
    """①：顶趟收工成功 ⇒ 该工作区有 `index/run-index.json`，`/api/run-index` 读得出。"""
    root = _ws(tmp_path)
    cond, owner = _conductor(root)

    # 前提：改前这就是"零生产调用者"的形状（索引不在盘上、接口恒 unreadable）。
    assert not SS.run_index_path(root).is_file(), "夹具不该一开始就有索引"
    before = SS.run_index_report(root)
    assert before["tri"] == "unreadable", before

    cond.finish_top_level_run(owner, stop_reason="final")

    path = SS.run_index_path(root)
    assert path.is_file(), f"收工成功之后索引不在盘上：{path}"
    report = SS.run_index_report(root)
    assert report["tri"] == "computed", report
    assert report["usable"] is True, report
    assert report["drift"] == [], report
    assert "s1" in (report["index"] or {}).get("sessions", {}), report["index"]

    # 真 HTTP：页面读的那一条端点必须读得出这份索引（不是只读函数对）。
    with _server(root) as base:
        code, got = _get(base, "/api/run-index")
    assert code == 200, (code, got)
    assert got["tri"] == "computed", got
    assert got["usable"] is True, got
    assert "s1" in (got.get("index") or {}).get("sessions", {}), got.get("index")


# ====================================================================== ② 收工不完整
def test_an_incomplete_run_neither_builds_nor_overwrites(
        tmp_path: pathlib.Path) -> None:
    """②：非 `final` 的收工既不许建索引，也不许覆盖已有索引（逐字节）。"""
    root = _ws(tmp_path)
    cond, owner = _conductor(root)
    path = SS.run_index_path(root)

    cond.finish_top_level_run(owner, stop_reason="steps_exhausted")
    assert not path.is_file(), "收工不完整（非 final）却建了索引"

    # 已有索引时：再收一次不完整的工，字节必须一个都不动。
    SS.rebuild_run_index(root)
    before = path.read_bytes()
    cond2, owner2 = _conductor(root)
    cond2.finish_top_level_run(owner2, stop_reason="bad_json")
    assert path.read_bytes() == before, "收工不完整时覆盖了已有索引"


# ====================================================================== ③ CLI
def test_the_cli_builds_for_any_workspace_and_is_idempotent(
        tmp_path: pathlib.Path, capsys) -> None:
    """③：显式命令对任意工作区建，跑两次字节相同。"""
    root = _ws(tmp_path)
    path = SS.run_index_path(root)
    assert not path.is_file()

    code, out, err = _run_cli(["project", "rebuild-run-index",
                               "--workspace", str(root)], capsys)
    assert code == 0, (code, out, err)
    assert path.is_file(), f"命令成功但索引不在盘上：{path}"
    first = path.read_bytes()
    assert SS.run_index_report(root)["tri"] == "computed"

    code2, out2, err2 = _run_cli(["project", "rebuild-run-index",
                                  "--workspace", str(root)], capsys)
    assert code2 == 0, (code2, out2, err2)
    assert path.read_bytes() == first, "跑两次字节不同 ⇒ 它不是幂等的"

    # "任意工作区"：一个还没初始化过 store 的目录也能建（只有索引，不碰 data/）。
    bare = tmp_path / "bare"
    bare.mkdir()
    code3, out3, err3 = _run_cli(["project", "rebuild-run-index",
                                  "--workspace", str(bare)], capsys)
    assert code3 == 0, (code3, out3, err3)
    assert SS.run_index_path(bare).is_file(), "空目录上没建出索引"
    assert not (bare / "data").is_dir(), "空目录上建索引不该顺手造一个 data/"


# ====================================================================== ④ 失败不静默
def test_a_failed_build_is_checked_false_with_reason_and_lands_in_the_audit(
        tmp_path: pathlib.Path, capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    """④：建索引失败 ⇒ `checked=False` + 原因 + 审计一行 + 退出码 2。"""
    root = _ws(tmp_path)

    def _boom(_root: Any) -> dict:
        raise OSError("磁盘满了（E5 判据的打桩）")

    monkeypatch.setattr(SS, "rebuild_run_index", _boom)
    code, out, err = _run_cli(["project", "rebuild-run-index",
                               "--workspace", str(root)], capsys)
    assert code == 2, (code, out, err)
    joined = out + err
    assert "checked=False" in joined, joined
    assert "磁盘满了" in joined, joined

    rows = _index_events(root)
    assert rows, f"失败没进审计（data/events.jsonl 里没有 run_index_rebuild）：{joined}"
    last = rows[-1]
    assert last.get("checked") is False, last
    assert "磁盘满了" in str(last.get("reason") or ""), last

    # 成功那一档也留一行审计（不是只有失败才留）。
    monkeypatch.undo()
    code2, out2, err2 = _run_cli(["project", "rebuild-run-index",
                                  "--workspace", str(root)], capsys)
    assert code2 == 0, (code2, out2, err2)
    rows2 = _index_events(root)
    assert len(rows2) == len(rows) + 1, rows2
    assert rows2[-1].get("checked") is True, rows2[-1]
    assert rows2[-1].get("built") is True, rows2[-1]


# ====================================================================== ⑤ GET 不写盘
def test_a_get_request_never_builds_the_index(tmp_path: pathlib.Path) -> None:
    """⑤ 守卫：`GET /api/run-index` 不写盘（索引的入口只有收工与显式命令）。"""
    root = _ws(tmp_path)
    with _server(root) as base:
        code, got = _get(base, "/api/run-index")
    assert code == 200, (code, got)
    assert got["tri"] == "unreadable", got
    assert not SS.run_index_path(root).is_file(), "GET /api/run-index 写盘了"
    # 同一份读数与 `/api/run/{sid}` 那半无关：这里只钉"GET 不建"。
    assert R.state_face(root).get("snapshot") is not None
