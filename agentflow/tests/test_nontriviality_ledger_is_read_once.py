# -*- coding: utf-8 -*-
"""判据：档位台账只解析一次，而"只读一次"不许变成"读到旧值"。

## 这一份守什么（R-BE1 的 ⑥-3，2026-10-27）

`secretary.nontriviality_of` 是逐条命题调的（收工读数与网页那一栏都是逐条问一次），
而改前它每次都把整份 `out/secretary/nontriviality.jsonl` 读一遍、逐行 `json.loads`。
索引按 `(st_mtime_ns, st_size)` 缓存在 `secretary._NT_INDEX_CACHE`。

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① 命中只读一次 | 同一条路径上问 N 条命题 ⇒ 文件只读 1 次 | 缓存没接上（还是每条一遍），或缓存把不同路径串了 |
| ② 追加立刻可见 | 台账追加一行并换掉 mtime ⇒ 下一次调用读到新档位 | 缓存键不含 mtime ⇒ 长跑里永远读第一版 |
| ③ 就地改返回值不污染缓存 | 调用方改返回值 ⇒ 下一次调用仍是台账里的值 | 缓存里放的要是返回值本身，一个调用方就能改掉全进程的读数 |
| ④ 同长改行 + 只改 mtime | 文件大小不变、mtime 变 ⇒ 也读到新值 | 键只有 size ⇒ 就地改短/同长改行读不到 |
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

from agentflow import secretary as SEC


def _ledger(root: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    path = SEC.nontriviality_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")
    return path


def _row(stmt_id: str, level: int | None, *, at: str) -> dict:
    return {"at": at, "stmt_id": stmt_id, "statement_sha256": "",
            "nontriviality": level, "label": f"T{level}" if level is not None else "",
            "basis": ["读数"], "applicable": True, "scale": SEC.NONTRIVIALITY_SCALE,
            "effort": {"score": level}, "text_truncated": False}


@pytest.fixture()
def workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "ws"
    root.mkdir()
    _ledger(root, [_row("000001", 1, at="2026-10-27T10:00:00+08:00"),
                   _row("000002", 4, at="2026-10-27T10:00:01+08:00")])
    return root


def _count_reads(monkeypatch: pytest.MonkeyPatch, path: pathlib.Path) -> list[int]:
    """数 `read_text` 打在这一个路径上的次数（别的路径不计数）。"""
    hits = [0]
    orig = pathlib.Path.read_text

    def counted(self, *a, **k):  # noqa: ANN001 - 替身
        if str(self) == str(path):
            hits[0] += 1
        return orig(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", counted)
    return hits


# ---------------------------------------------------------------- ① 命中只读一次


def test_the_ledger_is_parsed_once_for_many_statements(
        workspace: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """问 3 条命题（两条命中、一条没判过）⇒ 台账只读 1 次，三个答案都对。"""
    path = SEC.nontriviality_path(workspace)
    hits = _count_reads(monkeypatch, path)
    got1 = SEC.nontriviality_of(workspace, "正文一", stmt_id="000001")
    got2 = SEC.nontriviality_of(workspace, "正文二", stmt_id="000002")
    got3 = SEC.nontriviality_of(workspace, "没判过", stmt_id="000009")
    assert (got1["level"], got2["level"], got3["level"]) == (1, 4, None), (got1, got2, got3)
    assert got3["tri"] == "unknown"
    assert hits[0] == 1, f"同一份台账被读了 {hits[0]} 次（应当 1 次）"


# ---------------------------------------------------------------- ② 追加立刻可见


def test_an_appended_row_is_visible_on_the_next_call(
        workspace: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """台账追加一条更高档位 ⇒ 下一次调用立刻读到它（缓存不许把长跑冻在第一版）。"""
    path = SEC.nontriviality_path(workspace)
    hits = _count_reads(monkeypatch, path)
    before = SEC.nontriviality_of(workspace, "正文一", stmt_id="000001")
    assert before["level"] == 1
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_row("000001", 3, at="2026-10-27T11:00:00+08:00"),
                            ensure_ascii=False) + "\n")
    # 显式把 mtime 推到新的一刻：文件系统的时间粒度不该让这条判据变成偶发。
    now = path.stat()
    os.utime(path, ns=(now.st_atime_ns, now.st_mtime_ns + 10**6))
    after = SEC.nontriviality_of(workspace, "正文一", stmt_id="000001")
    assert after["level"] == 3, after
    assert hits[0] == 2, f"追加之后应当再读一次（实际 {hits[0]} 次）"


# ---------------------------------------------------------------- ③ 就地改返回值


def test_mutating_the_returned_dict_does_not_pollute_the_cache(workspace: pathlib.Path) -> None:
    """改返回值（含 `effort` 那一格）⇒ 下一次调用仍是台账里的值。"""
    got = SEC.nontriviality_of(workspace, "正文一", stmt_id="000001")
    got["level"] = 99
    got["effort"]["score"] = 99
    again = SEC.nontriviality_of(workspace, "正文一", stmt_id="000001")
    assert again["level"] == 1 and again["effort"] == {"score": 1}, again


# ---------------------------------------------------------------- ④ 只改 mtime


def test_same_size_rewrite_with_a_new_mtime_is_visible(workspace: pathlib.Path) -> None:
    """文件大小不变、只把 mtime 推新 ⇒ 也读到新值（键必须含 mtime_ns）。"""
    path = SEC.nontriviality_path(workspace)
    assert SEC.nontriviality_of(workspace, "正文一", stmt_id="000001")["level"] == 1
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows[0]["nontriviality"] = 2           # 同长改写（"1" → "2"）
    rows[0]["label"] = "T2"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")
    now = path.stat()
    os.utime(path, ns=(now.st_atime_ns, now.st_mtime_ns + 10**6))
    assert SEC.nontriviality_of(workspace, "正文一", stmt_id="000001")["level"] == 2
