# -*- coding: utf-8 -*-
"""台账面的每一行都要带"角色 + 绝对编号"（读模型的 join，不是磁盘格式变更）。

## 这一批在验什么

三个只读台账面（证据链 / 产物 / 收工门）的每一行，除了表里原本就有的字段之外，
还要能回答两个问题：

- `by_role`：这一行是谁写的（取自行里的 `created_by`；没有就是空串，页面显示
  "（未记录角色）"）；
- `by_task_id`：这一行是哪一个绝对编号的那一趟写的（从事件流反查；找不到就是空串，
  不许编）。

`by_task_id` 的三档（`by_task_id_tri`）是这一层最要紧的一格，三档不许互相顶替：

| 取值 | 意思 |
|---|---|
| `event` | 某条事件里出现了这一行的编号，而那条事件自己带着 `task_id` ⇒ 就是它 |
| `missing` | 查过了，盘上没有一条事件给出这个编号 ⇒ 空串（不猜） |
| `not_applicable` | 这一栏的行不是"某条写入"（配置行 / 文件清单 / 没有登记前缀的表） ⇒ 编号不适用 |

为什么三档不能折：把 `missing` 显示成 `not_applicable`，"查过了没找到"就变成
"用不着"；把 `not_applicable` 显示成 `missing`，配置行会永远挂着一个假红的缺口。

## 落点

只改读模型（`webui/readers.py` 的注解层）与生成物 `ui/src/types.ts`；
`schema.py` / `store.py` 一个字节都不碰 —— 这是 join，不是磁盘格式变更。

## 边界（这一批刻意定死的东西）

- 反查只扫最近 `readers.LEDGER_EVENT_SCAN_SESSIONS` 段会话，且只认
  `readers.LEDGER_EVENT_SCAN_KINDS` 里的 kind：一次请求一次有界扫描，
  不许整盘扫；
- 只有"事件自己带 `task_id`"才算 `event`：`agent_step` 那一类事件带着工具结果
  （写入的真身）却不带编号，于是它只能落到 `missing` —— 那正是这一格在等
  写侧补 `task_id` 的地方，不许拿"相邻那条 llm_call 的编号"顶上。
"""

from __future__ import annotations

import json
import os
import pathlib
import time

from agentflow import schema as S
from agentflow import sessions as SS
from agentflow.store import Store
from agentflow.webui import readers as R

#: 生成的接口声明里那一份字段表（与 `types.ts` 同源）。
FIELDS = R.ts_fields()

TS = "2026-10-21T00:00:00+08:00"


# ====================================================================== 造工作区
def _write_bytes(path: pathlib.Path, text: str) -> None:
    """按字节写一个文本文件（LF 行尾，不受 Windows 的 `\\n` 翻译影响）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _write_json(path: pathlib.Path, doc: object) -> None:
    """写一个 JSON 文件（UTF-8、LF、末尾一个换行）。"""
    _write_bytes(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def _write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    """写一个 JSONL 文件（一行一条，键排序，于是同样的输入逐字节同形）。"""
    _write_bytes(path, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                               for r in rows))


def _write_table(root: pathlib.Path, table: str, rows: list[dict]) -> None:
    """直接落一张 store 表的快照（`{"schema_version": …, "rows": [...]}`）。"""
    _write_json(root / "data" / str(S.TABLES[table]["file"]),
                {"schema_version": S.SCHEMA_VERSION, "rows": rows})


def _append_event(root: pathlib.Path, sid: str, **event: object) -> pathlib.Path:
    """往一段会话里追加一条事件（走 `sessions.append` 这一个写入口）。"""
    path, problem = SS.append(root, dict(event), sid=sid)
    assert problem == "", problem
    assert path is not None
    return path


def _age(path: pathlib.Path, seconds: float) -> None:
    """把一个文件的 mtime 定到某个时刻（`_recent_session_files` 按 mtime 排新旧）。"""
    os.utime(path, (seconds, seconds))


def _evidence_ws(tmp_path: pathlib.Path) -> pathlib.Path:
    """证据面的小工作区：两行 statements（B / V 各一行）+ 一条带编号的写入事件。"""
    root = tmp_path / "ws"
    _write_table(root, "statements", [
        {"stmt_id": "000001", "created_by": "B", "status": "ok", "created_at": TS},
        {"stmt_id": "000002", "created_by": "V", "status": "ok", "created_at": TS},
    ])
    _append_event(root, "s1", kind="agent_step", role="B", task_id="t-000009",
                  shape="table.create", ts=TS,
                  detail="table.create 落了 stmt:000001 这一行")
    return root


def _artifacts_ws(tmp_path: pathlib.Path) -> pathlib.Path:
    """产物面的小工作区：两行台账，一行有对应的写入事件、一行没有。"""
    root = tmp_path / "ws"
    _write_jsonl(root / "ARTIFACTS.jsonl", [
        {"at": TS, "path": "out/experiments/e-0001.log", "sha256": "0" * 64,
         "bytes": 10, "producer": "agent-e", "kind": "log", "task_id": "",
         "exit_code": 0, "note": ""},
        {"at": TS, "path": "out/experiments/e-0002.log", "sha256": "1" * 64,
         "bytes": 11, "producer": "agent-e", "kind": "log", "task_id": "",
         "exit_code": 0, "note": ""},
    ])
    _append_event(root, "s1", kind="agent_run_artifact", role="E", task_id="t-000009",
                  path="out/experiments/e-0001.log", ts=TS)
    return root


# ====================================================================== 判据一：证据面
def test_the_evidence_rows_carry_a_role_and_the_run(tmp_path: pathlib.Path) -> None:
    """正控（证据面）：能反查到的那一行给编号，反查不到的那一行留空 + `missing`。"""
    root = _evidence_ws(tmp_path)
    got = R.evidence_chain(root)
    assert got["statements_tri"] == R.TRI_COMPUTED, got
    assert [r["stmt_id"] for r in got["statements"]] == ["000001", "000002"], got["statements"]
    first, second = got["statements"]

    assert first["created_by"] == "B", first
    assert first["by_role"] == "B", first
    assert first["by_task_id"] == "t-000009", first
    assert first["by_task_id_tri"] == "event", first

    assert second["created_by"] == "V", second
    assert second["by_role"] == "V", second
    assert second["by_task_id"] == "", second
    assert second["by_task_id_tri"] == "missing", second

    # 多出来的三格必须同时出现在生成的类型声明里（契约 C 是双向的）
    for row in got["statements"]:
        assert set(row) == set(FIELDS["StatementRow"]), sorted(row)


# ====================================================================== 判据二：产物面
def test_the_artifact_ledger_rows_carry_the_run_that_recorded_them(
        tmp_path: pathlib.Path) -> None:
    """正控（产物面）：台账行按 `path` 反查，能查到的那一行带编号。"""
    root = _artifacts_ws(tmp_path)
    got = R.artifacts_face(root)
    assert got["ledger_tri"] == R.TRI_COMPUTED, got
    rows = {str(r["path"]): r for r in got["ledger"]}
    assert len(rows) == 2, rows

    one = rows["out/experiments/e-0001.log"]
    assert one["by_task_id"] == "t-000009", one
    assert one["by_task_id_tri"] == "event", one
    # ARTIFACTS.jsonl 的行没有 created_by ⇒ 角色这一格是空串（不是编一个 producer）
    assert one["by_role"] == "", one

    two = rows["out/experiments/e-0002.log"]
    assert two["by_task_id"] == "", two
    assert two["by_task_id_tri"] == "missing", two

    for row in got["ledger"]:
        assert set(row) == set(FIELDS["ArtifactRow"]), sorted(row)
    # 台账核对那一栏也按同一个口令反查（同一行不该在两栏里有两种归属）
    verify = {str(r["path"]): r for r in got["ledger_verify"]}
    assert verify["out/experiments/e-0001.log"]["by_task_id"] == "t-000009", verify


# ====================================================================== 判据三：验收面
def test_the_acceptance_rows_carry_a_role_slot_and_say_the_number_does_not_apply(
        tmp_path: pathlib.Path) -> None:
    """正控（验收面）：它的行不是"某条写入" ⇒ 至少带 `by_role`，编号写"不适用"。"""
    from agentflow.reviewaccept import CRITERIA

    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True, exist_ok=True)
    Store(root).init()
    got = R.acceptance_face(root, project_dir=str(root))
    rows = got["rows"]
    assert [str(r["key"]) for r in rows] == [k for k, _d in CRITERIA], rows
    for row in rows:
        assert set(row) == set(FIELDS["AcceptanceRow"]), sorted(row)
        assert row["by_role"] == "", row
        assert row["by_task_id"] == "", row
        assert row["by_task_id_tri"] == "not_applicable", row
    # 值那一格照旧是原样的三档读数（注解层不许改动它）
    assert set(got["criteria"]) == {k for k, _d in CRITERIA}, got["criteria"]
    assert {row["key"]: row["value"] for row in rows} == got["criteria"], rows


# ====================================================================== 判据四：负控
def test_a_number_that_matches_no_row_is_never_pasted_on_to_another_row(
        tmp_path: pathlib.Path) -> None:
    """负控（不许编）：事件里的编号对不上任何一行 ⇒ 那一行照样是空串 + `missing`。

    三条一起钉：

    1. 事件说的是 `stmt:000777`（台账里没有这一行）⇒ 它的编号不许贴到别的行上；
    2. 事件说的是 `stmt:0000012`（比 000001 长一位）⇒ 也不许因为"前缀相同"就贴上去；
    3. 两行的 `by_task_id` 集合必须只有空串。
    """
    root = tmp_path / "ws"
    _write_table(root, "statements", [
        {"stmt_id": "000001", "created_by": "B", "created_at": TS},
        {"stmt_id": "000002", "created_by": "V", "created_at": TS},
    ])
    _append_event(root, "s1", kind="agent_step", role="B", task_id="t-000099", ts=TS,
                  detail="讨论 stmt:000777 这一条（它不在台账里）")
    _append_event(root, "s1", kind="agent_step", role="V", task_id="t-000098", ts=TS,
                  detail="把 stmt:0000012 也读了一遍（那是另一个编号）")

    got = R.evidence_chain(root)
    rows = got["statements"]
    assert len(rows) == 2, rows
    ids = {str(r["by_task_id"]) for r in rows}
    assert ids == {""}, ids
    for bad in ("t-000099", "t-000098"):
        assert all(bad not in str(r["by_task_id"]) for r in rows), (bad, rows)
    assert {str(r["by_task_id_tri"]) for r in rows} == {"missing"}, rows


# ====================================================================== 判据五：有界
def test_the_reverse_lookup_only_scans_the_recent_sessions(tmp_path: pathlib.Path) -> None:
    """负控（有界）：扫描窗口只有 `LEDGER_EVENT_SCAN_SESSIONS` 段，多出多少段都不多看。

    三件事一起钉：

    1. 窗口常量被尊重：盘上有 `N + 3` 段会话时，真正被打开的文件恰好 `N` 个；
    2. 窗口之外那条写入事件不被采用（`missing`，不是"扫不到就当没有"的静默成功）；
    3. 再多塞几段更老的会话，读数一格不动 —— 结果不随 sid 总数变。
    """
    n = int(R.LEDGER_EVENT_SCAN_SESSIONS)
    assert n >= 1, n
    assert (R.LEDGER_TASK_TRI_EVENT, R.LEDGER_TASK_TRI_MISSING) == ("event", "missing")
    assert R.TRI_NOT_APPLICABLE == "not_applicable"

    total = n + 3
    root = tmp_path / "ws"
    _write_table(root, "statements", [
        {"stmt_id": "000001", "created_by": "B", "created_at": TS},
        {"stmt_id": "000002", "created_by": "V", "created_at": TS},
    ])
    for i in range(total):
        path = _append_event(root, f"s{i:02d}", kind="agent_note", role="B", ts=TS,
                             text=f"第 {i} 段会话的噪声事件")
        _age(path, 1_600_000_000 + i)
    # 最老的那一段带着 000002 的写入事件：它在窗口之外
    _append_event(root, "s00", kind="agent_step", role="V", task_id="t-000098", ts=TS,
                  detail="落了 stmt:000002")
    # 最新的一段带着 000001 的写入事件：它在窗口之内
    _append_event(root, f"s{total - 1:02d}", kind="agent_step", role="B",
                  task_id="t-000009", ts=TS, detail="落了 stmt:000001")

    started = time.monotonic()
    got = R.evidence_chain(root)
    elapsed = time.monotonic() - started
    rows = {str(r["stmt_id"]): r for r in got["statements"]}
    assert rows["000001"]["by_task_id"] == "t-000009", rows["000001"]
    assert rows["000001"]["by_task_id_tri"] == "event", rows["000001"]
    assert rows["000002"]["by_task_id"] == "", rows["000002"]
    assert rows["000002"]["by_task_id_tri"] == "missing", rows["000002"]

    # 1. 窗口常量被尊重：盘上 total 段，真正被取用的恰好 n 段、且是最新的那 n 段
    files = R._recent_session_files(root)
    assert len(files) == n, [p.name for p in files]
    assert [p.stem for p in files] == [f"s{i:02d}" for i in range(total - 1,
                                                                 total - n - 1, -1)], files

    # 3. 再多塞几段更老的会话：窗口没变 ⇒ 读数一格不动
    before = {k: str(v["by_task_id"]) for k, v in rows.items()}
    for i in range(5):
        path = _append_event(root, f"old{i:02d}", kind="agent_note", role="V", ts=TS,
                             text="更老的一段会话")
        _age(path, 1_500_000_000 + i)
    after = {str(r["stmt_id"]): str(r["by_task_id"])
             for r in R.evidence_chain(root)["statements"]}
    assert after == before, (before, after)
    # 一条宽松的墙钟界：它只证明"没有整盘扫"，不冒充性能判据
    assert elapsed < 30.0, elapsed
