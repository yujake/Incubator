# -*- coding: utf-8 -*-
"""`/api/source` 的路径闸与 `/api/package` 的只读面（块 3）。

## 为什么这一份是安全判据

`/api/source` 把工作区里的文本文件读给浏览器 —— 这是本次唯一新增的攻击面。
四条闸缺一条都等于把 `C:\\Windows\\win.ini` 或 `../../etc/passwd` 读出去：

1. 绝对路径一律拒；
2. 路径分量有 `..` 一律拒（不做"resolve 之后再看"的侥幸）；
3. `resolve()` 之后必须在工作区内（符号链接跳出去也算越界）；
4. 只认文本后缀；大文件只回窗口，不把 26MB 的会话整份吐出去。

## 只读

两条新面都只有 GET（路由表里没有配对的 POST），且一次真实 HTTP 读之后工作区
一个字节都不变（文件名 / 大小 / mtime_ns 三格逐项相同）。
"""
from __future__ import annotations

import http.client
import json
import pathlib
import threading
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from agentflow.webui import readers as R
from agentflow.webui import routes


def _workspace(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """一个最小工作区 + 一份工作区外的"秘密"文件。"""
    root = tmp_path / "ws"
    (root / "out" / "review").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "out" / "review" / "REPORT.md").write_text(
        "第一行\n第二行\n第三行\n", encoding="utf-8")
    (root / "data" / "statements.json").write_text(
        json.dumps({"schema_version": 2, "rows": [{"stmt_id": "000019"}]},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("工作区外的秘密\n", encoding="utf-8")
    return root, outside


# ====================================================================== 路径闸
def test_a_relative_file_inside_the_workspace_is_read(tmp_path: pathlib.Path) -> None:
    root, _outside = _workspace(tmp_path)
    got = R.source_window(root, "out/review/REPORT.md")
    assert got["tri"] == "computed", got
    assert got["lines"] == ["第一行", "第二行", "第三行"]
    assert got["total"] == 3
    assert got["truncated"] is False


@pytest.mark.parametrize("path", [
    "../outside.txt",
    "out/../../outside.txt",
])
def test_dot_dot_is_refused(tmp_path: pathlib.Path, path: str) -> None:
    root, _outside = _workspace(tmp_path)
    got = R.source_window(root, path)
    assert got["tri"] == "unreadable", got
    assert ".." in got["reason"] or "越界" in got["reason"], got
    assert got["lines"] == []


def test_an_absolute_path_is_refused(tmp_path: pathlib.Path) -> None:
    root, outside = _workspace(tmp_path)
    got = R.source_window(root, str(outside))
    assert got["tri"] == "unreadable", got
    assert "绝对路径" in got["reason"], got
    assert got["lines"] == []
    # 盘符路径同样是绝对路径（Windows 上这条就是 C:\... 的形态）
    got2 = R.source_window(root, "C:\\Windows\\win.ini")
    assert got2["tri"] == "unreadable", got2
    assert got2["lines"] == []


def test_an_outside_target_without_dotdot_is_refused(tmp_path: pathlib.Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """符号链接式逃逸：路径里没有 `..`，但 resolve 之后在工作区外。"""
    root, outside = _workspace(tmp_path)
    link = root / "data" / "escape.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("本机不允许建符号链接 ⇒ 这一档记 unknown（不是通过）")
    got = R.source_window(root, "data/escape.txt")
    assert got["tri"] == "unreadable", got
    assert "工作区外" in got["reason"], got
    assert got["lines"] == []


def test_a_non_text_suffix_is_refused(tmp_path: pathlib.Path) -> None:
    root, _outside = _workspace(tmp_path)
    (root / "out" / "paper").mkdir(parents=True, exist_ok=True)
    (root / "out" / "paper" / "main.pdf").write_bytes(b"%PDF-1.4\n")
    got = R.source_window(root, "out/paper/main.pdf")
    assert got["tri"] == "unreadable", got
    assert "后缀" in got["reason"], got
    assert got["lines"] == []


# ====================================================================== 大文件 / match
def test_a_big_file_is_truncated_not_dumped(tmp_path: pathlib.Path) -> None:
    root, _outside = _workspace(tmp_path)
    big = root / "data" / "big.log"
    big.write_text("".join(f"第 {i} 行\n" for i in range(200_000)), encoding="utf-8")
    assert big.stat().st_size > R.SOURCE_SCAN_BYTES
    got = R.source_window(root, "data/big.log")
    assert got["tri"] == "computed", got
    assert got["truncated"] is True
    assert got["total"] is None, "截断时不许编一个总行数"
    assert len(got["lines"]) <= R.SOURCE_LINES_MAX


def test_match_locates_a_line_inside_a_pretty_json(tmp_path: pathlib.Path) -> None:
    root, _outside = _workspace(tmp_path)
    got = R.source_window(root, "data/statements.json",
                          match='"stmt_id": "000019"')
    assert got["tri"] == "computed", got
    assert got["line"] > 0
    assert any('"000019"' in one for one in got["lines"]), got["lines"]
    # 窗口有上下文，不是只回那一行
    assert got["start_line"] <= got["line"]


def test_a_missing_needle_is_a_controlled_refusal(tmp_path: pathlib.Path) -> None:
    root, _outside = _workspace(tmp_path)
    got = R.source_window(root, "data/statements.json", match="不存在的针")
    assert got["tri"] == "unreadable", got
    assert "没有找到" in got["reason"], got
    assert got["lines"] == []


# ====================================================================== 路由与只读
def test_the_two_faces_are_get_only() -> None:
    methods = {(m, p) for m, p, _h in routes.ROUTES}
    assert ("GET", "/api/source") in methods
    assert ("GET", "/api/package") in methods
    assert not any(m == "POST" and p in ("/api/source", "/api/package")
                   for m, p, _h in routes.ROUTES)


@contextmanager
def _server(root: pathlib.Path) -> Iterator[str]:
    from agentflow import webui as W

    srv = W.serve(root, host="127.0.0.1", port=0, csrf_token="sourcetoken0123456789")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _get(base: str, path: str) -> tuple[int, dict[str, Any]]:
    conn = http.client.HTTPConnection(base, timeout=20)
    try:
        conn.request("GET", path, headers={"Accept": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {"_list": body}
    finally:
        conn.close()


def _snapshot(root: pathlib.Path) -> dict[str, tuple[int, int]]:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_an_http_read_does_not_write_the_workspace(artifacts_ws: pathlib.Path) -> None:
    before = _snapshot(artifacts_ws)
    with _server(artifacts_ws) as base:
        code, got = _get(base, "/api/source?path=out/review/REPORT.md")
        assert code == 200, (code, got)
        assert got["tri"] == "computed", got
        assert got["lines"], got
        code2, pkg = _get(base, "/api/package?project_dir=.&report_path=out/review/REPORT.md")
        assert code2 == 200, (code2, pkg)
        assert set(pkg) == {"tri", "reason", "generated_at", "proofs", "structure", "closing"}
        assert pkg["closing"]["gates"]["cells"], pkg["closing"]
    assert _snapshot(artifacts_ws) == before
