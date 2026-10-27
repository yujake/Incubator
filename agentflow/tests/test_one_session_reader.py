# -*- coding: utf-8 -*-
"""判据：会话记录只有一个读口（R-BE1 的 ②-1，2026-10-27 业主批准）。

## 这一份守什么

改前"怎么读会话、读不明白算哪一档"有两份实现：

- `sessions.read_session(root, sid)` —— 按 sid 读一段，`problems` 是逐行/逐文件清单
  （`stopctl` / `closing` / `statusreport` / `webui` 用它）；
- `errorstats._read_sessions(root)` —— 自己 glob + splitlines + `json.loads`，再把结果折成
  `checked / files / records / bad_lines / unreadable_files / reason`（`readouts` 的
  errors/flow/cost 用它）。

同一份坏目录，两条路对"读不明白"的判定不同：一处说"bad_lines=3"，另一处说"文件读不出来"。
现在只有一处实现 —— `sessions.read_all_sessions` —— `errorstats._read_sessions` 是它的转发。

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① 两条路逐字相同 | 同一份目录上 `_read_sessions(root) == read_all_sessions(root)`（记录与读数都相等） | 又长回第二份实现，两边对坏文件的判定分家 |
| ② 三种坏形态 | 缺目录 / 空目录 / 半截 JSON + 非 UTF-8 + 好文件：`checked` / `reason` / `unreadable_files` 逐字一致 | 某一形态只有一条路认得（"没查成"与"0 条"被折平） |
| ③ 读数字段与顺序 | reading 的键顺序仍是 `checked, files, records, bad_lines, unreadable_files, reason` | 顺序变 ⇒ `sources["sessions"]` 的 JSON 变了 ⇒ `stats errors` 的输出 sha 会变 |
| ④ 按 sid 与全量同源 | 好文件的记录：`read_session(root, sid)[0] == read_all_sessions(root)` 里属于它的那几条 | 两条路各写一份解析（BOM / CRLF 只改一处） |
"""
from __future__ import annotations

import json
import pathlib

from agentflow import errorstats as ES
from agentflow import readouts as RO
from agentflow import sessions as SS

READING_KEYS = ["checked", "files", "records", "bad_lines", "unreadable_files", "reason"]


def _workspace(base: pathlib.Path, name: str) -> pathlib.Path:
    ws = base / name
    (ws / "data").mkdir(parents=True, exist_ok=True)
    return ws


def _good_sessions(ws: pathlib.Path) -> pathlib.Path:
    folder = ws / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "s1.jsonl").write_text(
        "\n".join([
            json.dumps({"kind": "agent_step", "role": "C", "index": 1, "shape": "tool",
                        "result": {"error": "没有名为 'x' 的工具"}}, ensure_ascii=False),
            json.dumps({"kind": "agent_message", "role": "G", "from": "G", "to": "M",
                        "subject": "请代唤 V"}, ensure_ascii=False),
        ]) + "\n", encoding="utf-8")
    return ws


def _bad_sessions(ws: pathlib.Path) -> pathlib.Path:
    folder = ws / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "half.jsonl").write_text(
        '{"kind": "agent_step", "role": "C"}\n{"kind": "agent_st\n', encoding="utf-8")
    (folder / "binary.jsonl").write_bytes(b"\xff\xfe\x00\x00not utf8\n")
    (folder / "ok.jsonl").write_text(
        '{"kind": "agent_step", "role": "C", "index": 1, "shape": "tool",'
        ' "result": {"error": "没有名为 \'x\' 的工具"}}\n', encoding="utf-8")
    return ws


# ---------------------------------------------------------------- ① 两条路逐字相同


def test_both_paths_return_the_same_records_and_reading(tmp_path: pathlib.Path) -> None:
    """`errorstats._read_sessions` 与 `sessions.read_all_sessions` 逐字相同。"""
    ws = _bad_sessions(_workspace(tmp_path, "wa"))
    got_es = ES._read_sessions(ws)
    got_ss = SS.read_all_sessions(ws)
    assert got_es == got_ss, (got_es, got_ss)


# ---------------------------------------------------------------- ② 三种坏形态


def test_the_three_bad_shapes_are_judged_the_same_way(tmp_path: pathlib.Path) -> None:
    """缺目录 / 空目录 / 坏文件混好文件：两边的 `checked` / `reason` / `unreadable_files` 一致。"""
    missing = tmp_path / "missing"            # 真的不存在（不是"建了但没有 sessions/"）
    empty = _workspace(tmp_path, "empty")
    (empty / "sessions").mkdir()
    nosessions = _workspace(tmp_path, "nosessions")   # 工作区在、sessions/ 没建（合法初态）
    bad = _bad_sessions(_workspace(tmp_path, "bad"))
    good = _good_sessions(_workspace(tmp_path, "good"))

    shapes = {"missing": missing, "empty": empty, "nosessions": nosessions,
              "bad": bad, "good": good}
    readings = {}
    for name, ws in shapes.items():
        es = ES._read_sessions(ws)[1]
        ss = SS.read_all_sessions(ws)[1]
        assert es == ss, (name, es, ss)
        assert es["unreadable_files"] == ss["unreadable_files"], (name, es, ss)
        assert es["reason"] == ss["reason"], (name, es, ss)
        readings[name] = es
    # 反真空：这几种形态必须真的不同（否则上面的相等是空转）
    assert readings["missing"]["checked"] is False, readings["missing"]
    assert readings["nosessions"]["checked"] is True, readings["nosessions"]
    assert readings["empty"]["checked"] is True, readings["empty"]
    assert readings["nosessions"]["reason"] != readings["empty"]["reason"], readings
    assert readings["bad"]["unreadable_files"] == ["binary.jsonl"], readings["bad"]
    assert readings["bad"]["checked"] is True and readings["bad"]["files"] == 2, readings["bad"]
    assert readings["good"]["reason"] == "", readings["good"]


# ---------------------------------------------------------------- ③ 字段与顺序


def test_the_reading_keeps_its_key_order(tmp_path: pathlib.Path) -> None:
    """reading 的键顺序不许变：`sources["sessions"]` 是按插入顺序进 JSON 的。"""
    ws = _bad_sessions(_workspace(tmp_path, "ws"))
    reading = SS.read_all_sessions(ws)[1]
    assert list(reading) == READING_KEYS, list(reading)


# ---------------------------------------------------------------- ④ 按 sid 与全量同源


def test_a_single_session_is_a_slice_of_all_sessions(tmp_path: pathlib.Path) -> None:
    """好文件：`read_session(root, sid)` 的记录与全量里的那几条相同（同一份解析）。"""
    ws = _good_sessions(_workspace(tmp_path, "ws"))
    one, problems = SS.read_session(ws, "s1")
    assert problems == [], problems
    everything = SS.read_all_sessions(ws)[0]
    assert everything == one, (everything, one)
    # 读数那一侧也接上了：`readouts.scan` 与 `errors_readout` 用的是同一份
    scanned = RO.scan(ws)
    assert scanned["sources"]["sessions"] == SS.read_all_sessions(ws)[1]
    assert RO.errors_readout(ws)["data"]["sources"]["sessions"] == SS.read_all_sessions(ws)[1]
