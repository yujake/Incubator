# -*- coding: utf-8 -*-
"""JSONL 的行界只有 `\\n`：U+0085 不是换行；坏行按「行号范围」报、同一句一拍只报一次。

## 现场（R10 真机 lp-ball-10，2026-11-19，只读对账 `temp/r10check`）

`jsonlfile` 改前用 `text.splitlines()` 切行。`str.splitlines()` 按 Unicode 行界 切
（`\\x0b \\x0c \\x1c \\x1d \\x1e \\x85 \\u2028 \\u2029` 全算），而 JSONL 的行界只有
`\\n`。会话里 8 行（`\\n` 口径的 522/554/556/568/570/608/610/614）带着文献抽取文本里的
82 个 U+0085（NEL） ⇒ 8 条合法 JSON 行被切成 90 段：

- `read_session` 只读出 3659/3667 条记录、报 84 条 problems；
- 收工那三格 `roster_registration` / `summon_consumption` / `verdict_escalation`
  因此 `checked=false`（"没查成"而不是"查过了没问题"）；
- M 的信箱每一拍把同一批 84 个坏行号重报一遍 —— 顶趟 `agent_run_end.notes` 里
  同一句出现 4589 次（84 个行号 × 55 拍）。

## 判据（每条都能造红，也有反真空）

| # | 判据 | 造的是什么现场 |
|---|---|---|
| a | 行内有 U+0085 / U+2028 的 JSONL 仍逐行读得出、`problems=[]` | 三条记录，两条的字符串里各带一个 Unicode 行界 |
| a-负控 | 同一份文件交给改前的读法（`splitlines`）必须读不出来 | 证明 a 的绿灯确实压在这一格上 |
| b | 连续坏行折成一条「第 A–B 行…（N 行）」；单行与改前逐字相同 | 3 条连续语法坏 + 2 条连续「不是对象」 |
| c | 会话文件里有 NEL 时 `read_session` 读全、`problems=[]` | 真写一条带 U+0085 的 `agent_step` |
| d | 同一条"读不成"在信箱里一拍只报一次（`checked` 仍为假） | 会话里有一行坏行，连投两拍 |
| d-负控 | 不把上一拍的键交回去 ⇒ 第二拍照旧报（去重不是"现在没问题"） | 同上，`rendered=()` |

""" 
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import agent_loop as AL
from agentflow import jsonlfile as JF
from agentflow import sessions as SS

NEL = "\u0085"
LS = "\u2028"


# ---------------------------------------------------------------- 夹具


def _write_jsonl(path: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    return path


def _old_reader(path: pathlib.Path) -> tuple[list[dict], list[str]]:
    """改前那一版（`text.splitlines()`）的等价实现 —— a 的负控。

    它只活在这份判据里：真实现再退回 `splitlines` 时 a 会红，而"a 红了"这件事
    必须能从这一份对照里读出来（否则"读得出来"可能只是文件里根本没有行界字符）。
    """
    records: list[dict] = []
    problems: list[str] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw or raw.isspace():
            continue
        try:
            obj = json.loads(raw)
        except ValueError as e:
            problems.append(f"第 {i} 行读不出来（{type(e).__name__}: {e}）")
            continue
        if not isinstance(obj, dict):
            problems.append(f"第 {i} 行不是对象")
            continue
        records.append(obj)
    return records, problems


class _Box:
    """够 `mailbox_digest` 用的最小 conductor 壳（板面与撤项格都"查过了、空"）。"""

    def open_items_of(self, task_id: str) -> list[dict]:
        return []

    def revoked_recent_of(self, task_id: str) -> list[dict]:
        return []


def _session_with_bad_line(root: pathlib.Path, *, sid: str) -> pathlib.Path:
    """一份会话：一行坏行 + 一条投给 F 的留言。"""
    SS.append(root, {"kind": "agent_step", "role": "A", "task_id": "t-000001",
                     "payload": {"name": "fs.read", "args": {"path": "x"}},
                     "result": {"ok": True}}, sid=sid)
    SS.append(root, {"kind": "agent_message", "msg_id": "m0001", "from": "D",
                     "to": "F", "subject": "看图", "body": "第 2 页那张"},
              sid=sid)
    path = pathlib.Path(root) / "sessions" / f"{sid}.jsonl"
    text = path.read_text(encoding="utf-8")
    path.write_text("这不是 JSON\n" + text, encoding="utf-8")
    return path


# ============================================================ a 正控


def test_a_a_nel_inside_a_json_line_is_still_one_line(tmp_path: pathlib.Path) -> None:
    """a：字符串里带 U+0085 / U+2028 的 JSONL 仍逐行读得出（`problems=[]`）。"""
    p = _write_jsonl(tmp_path / "nel.jsonl", [
        {"a": 1},
        {"b": f"前{NEL}后", "c": f"左{LS}右"},     # 两条 Unicode 行界字符
        {"d": 2},
    ])
    rows, problems = JF.read_jsonl(p)
    assert problems == [], problems
    assert [r.get("a", r.get("d")) for r in rows] == [1, None, 2], rows
    assert rows[1]["b"] == f"前{NEL}后" and rows[1]["c"] == f"左{LS}右", rows[1]

    # 夹具前提：这一份文件里真的有两个"会被 splitlines 当成行界"的字符。
    text = p.read_text(encoding="utf-8")
    assert text.count("\n") == 3, "夹具里应当只有 3 个 \\n（行界）"
    assert len(text.splitlines()) > len(text.split("\n")), (
        "这一份夹具没有造出『splitlines 多切』的形态 ⇒ a 的负控不成立")


def test_a2_the_old_splitlines_reader_cannot_read_the_same_file(
        tmp_path: pathlib.Path) -> None:
    """a-负控：同一份文件交给改前读法必须读不出来 —— a 的绿灯压在这一格上。"""
    p = _write_jsonl(tmp_path / "nel.jsonl", [
        {"a": 1}, {"b": f"前{NEL}后"}, {"d": 2}])
    rows_old, problems_old = _old_reader(p)
    assert problems_old, "改前读法居然读出来了 ⇒ 这份夹具钉不住 splitlines 那条缺陷"
    assert len(rows_old) < 3, rows_old
    # 真实现读得出来（同一份文件、同一时刻）。
    assert JF.read_jsonl(p) == ([{"a": 1}, {"b": f"前{NEL}后"}, {"d": 2}], [])


def test_a3_the_two_sign_path_readers_also_only_break_on_newline(
        tmp_path: pathlib.Path) -> None:
    """a3：签那一路的两个 JSONL 读口（`sign_counting.read_rows` / `sign_ledger_backing`）
    也只在 `\\n` 上断行 —— V 台账的 `why` 会带文献抽取文本（R10 的 82 个 U+0085 就是
    这么来的），`splitlines()` 会把那一行切碎、票数与背书当场读成 0。"""
    from agentflow import sign_counting as SC
    from agentflow import vsigns as VS

    root = tmp_path / "ws"
    key = "b" * 64                       # pending 台账的键是 64 位十六进制（正文 / 载体 sha）
    ledger = root / "verifications" / "pending" / f"{key}.jsonl"
    ledger.parent.mkdir(parents=True)
    sha = "a" * 64
    row = {"verification_id": "u-000001", "proof_sha256": sha,
           "verdict": "成立", "unresolved_errors": 0, "citation_checks": [],
           "why": f"逐行核过：第 1 步{NEL}第 2 步",
           "secretary_judge": {"checked": True, "axis": "clean", "decision": "没问题"}}
    ledger.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    assert len(ledger.read_text(encoding="utf-8").splitlines()) > 1, (
        "夹具里没有造出『splitlines 多切』的形态 ⇒ a3 的负控不成立")

    got, problems = SC.read_rows(ledger)
    assert problems == [] and len(got) == 1, (got, problems)
    backing = VS.sign_ledger_backing(
        root, f"verifications/pending/{key}.jsonl#u-000001", proof_sha256=sha)
    assert backing.get("checked") is True and backing.get("ok") is True, backing


# ============================================================ b 行号范围


def test_b_consecutive_bad_lines_are_reported_as_one_range(tmp_path: pathlib.Path) -> None:
    """b：连续坏行折成「第 A–B 行（N 行）」；单行仍逐字沿用改前格式。"""
    p = tmp_path / "bad.jsonl"
    p.write_text('{"a": 1}\n坏1\n坏2\n坏3\n[1, 2]\n[3, 4]\n{"b": 2}\n',
                 encoding="utf-8")
    rows, problems = JF.read_jsonl(p)
    assert rows == [{"a": 1}, {"b": 2}], rows
    assert len(problems) == 2, problems
    assert problems[0].startswith("第 2–4 行读不出来（3 行；首条："), problems[0]
    assert problems[1] == "第 5–6 行不是对象（2 行）", problems[1]

    # 单行那一档逐字不变（既有调用方与判据都按这个字面读）。
    one = tmp_path / "one.jsonl"
    one.write_text('{"a": 1}\n坏\n', encoding="utf-8")
    assert JF.read_jsonl(one)[1] == [
        "第 2 行读不出来（JSONDecodeError: Expecting value: line 1 column 1 (char 0)）"
    ], JF.read_jsonl(one)[1]


# ============================================================ c 真会话


def test_c_a_session_line_with_nel_is_read_whole(tmp_path: pathlib.Path) -> None:
    """c：会话里一行带 82 个 NEL 时，`read_session` 一条不丢、`problems=[]`。

    形状与真机一致：`agent_step` 的 result 里是文献抽取文本（含 U+0085）。
    """
    sid = "r10fix-nel"
    root = tmp_path / "ws"
    (root / "sessions").mkdir(parents=True)
    SS.append(root, {"kind": "agent_step", "role": "A", "task_id": "t-000012",
                     "payload": {"name": "fs.read", "args": {"path": "lit.txt"}},
                     "result": {"data": {"text": f"a{NEL}b{NEL}c{NEL}d"}}}, sid=sid)
    SS.append(root, {"kind": "agent_message", "msg_id": "m0001", "from": "A",
                     "to": "M", "subject": "s", "body": "b"}, sid=sid)
    events, problems = SS.read_session(root, sid)
    assert problems == [], problems
    assert len(events) == 2, events
    steps = [e for e in events if e.get("kind") == "agent_step"]
    assert steps and steps[0]["result"]["data"]["text"].count(NEL) == 3, steps


# ============================================================ d 一拍只报一次


def _mailbox_once(root: pathlib.Path, *, sid: str, rendered: list[str]) -> dict[str, Any]:
    return AL.mailbox_digest(_Box(), root, "F", my_task_id="t-000002", sid=sid,
                             rendered=list(rendered))


def test_d_a_read_failure_is_reported_once_per_run(tmp_path: pathlib.Path) -> None:
    """d：同一条「读不成」第二拍不再报（`checked` 仍为假）；新出现的坏行照旧报。"""
    sid = "r10fix-mailbox"
    root = tmp_path / "ws"
    (root / "sessions").mkdir(parents=True)
    _session_with_bad_line(root, sid=sid)

    first = _mailbox_once(root, sid=sid, rendered=[])
    assert first["checked"] is False, first
    assert len(first["problems"]) == 1, first["problems"]
    assert "读不出来" in first["problems"][0], first["problems"]
    assert first["problem_ids"], first

    second = _mailbox_once(root, sid=sid, rendered=list(first["problem_ids"]))
    assert second["checked"] is False, "去重只折『重报』，不许把『没查成』折成『查过了』"
    assert second["problems"] == [], second["problems"]
    assert second["problems_repeated"] == 1, second
    assert "读不出来" in str(second.get("reason") or ""), second.get("reason")

    # 新出现的一整段坏行（行号范围不同 ⇒ 键不同）照旧报出来。
    path = root / "sessions" / f"{sid}.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "又坏一行\n又坏一行\n",
                    encoding="utf-8")
    third = _mailbox_once(root, sid=sid, rendered=list(first["problem_ids"]))
    assert third["problems"], "新坏行被当成『已经报过』吞掉了"
    assert any("行读不出来" in p for p in third["problems"]), third["problems"]


def test_d2_without_the_rendered_keys_the_same_line_is_reported_again(
        tmp_path: pathlib.Path) -> None:
    """d-负控：不把上一拍的键交回去 ⇒ 第二拍照旧报（去重不是"现在没问题"）。"""
    sid = "r10fix-mailbox2"
    root = tmp_path / "ws"
    (root / "sessions").mkdir(parents=True)
    _session_with_bad_line(root, sid=sid)
    first = _mailbox_once(root, sid=sid, rendered=[])
    again = _mailbox_once(root, sid=sid, rendered=[])
    assert again["problems"] == first["problems"], (
        "不带渲染集时第二拍已经不再报了 ⇒ d 的绿灯不是由去重那一格撑着的")
