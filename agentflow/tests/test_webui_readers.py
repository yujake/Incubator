# -- coding: utf-8 --
"""六个只读面的判据（`draft/78 §2.1` 的 B 线判据；`draft/73` §2.3）。

## 每一面两半（`draft/73` §2.3 的判据口径）

- 正控：夹具造出真数据（`tests/conftest.py` 的 `make_artifacts_sample`，
  裁定 J2/K2 的样本）⇒ 读数出现在结果里，且字段名逐字对得上；
- 负控（这一组最重要）：数据源不可读 ⇒ 该面 `tri="unreadable"` + `reason` 非空；
  空工作区 ⇒ `tri="not_applicable"` + 一句"还没写过"。不许折成 `0` / `[]` / `false`
  （"没查成 vs 查到 0"这条线是本仓库最贵的纪律）。

## 三态词表

`computed` / `unreadable` / `not_applicable`（裁定 N1：与「交付说明」那一格的
`ok`/`missing`/`unknown` 不许互相顶替）。本文件同时钉住"哪一栏用哪一套"。

## 注册表

`readers.CHECKED_TYPES` / `UNCHECKED_TYPES` 是契约判据 C 的两份登记，它们必须与
`type_decls()` 自洽：一个接口要么在受核对名单里、要么在欠账名单里（且欠账那一边
不许真读出键来）。这一半在本文件里自己先核一遍，别等 A 线的判据来报。
"""

from __future__ import annotations

import http.client
import json
import pathlib
import re
import threading
from contextlib import contextmanager
from typing import Any, Iterator

import conftest
import pytest

from agentflow import sessions as SS
from agentflow import userio as U
from agentflow.webui import readers as R
from agentflow.webui import routes
from agentflow.webui.state import _read_report

#: 夹具工作区里那一段会话的号（与 `conftest.make_artifacts_sample` 的默认值一致）。
SID = "fix-sid"

#: 每个接口的字段名（来自 `readers.type_decls()` 那一份声明 —— 不在这里另抄一遍）。
FIELDS = R.ts_fields()


# ====================================================================== 1 快照面
def test_the_state_face_keeps_the_snapshot_keys_verbatim(
        artifacts_ws: pathlib.Path) -> None:
    """正控（快照）：`state_face()` 的 `snapshot` 就是 `snapshot()` 的返回值，键一字不改。

    为什么钉这个：`StateSnapshot` 的键是旧壳渲染与 `tests/test_webui.py` 共用的公开面，
    外挂一层三态头不许顺手把里面的键改名或包一层。
    """
    from agentflow.webui import snapshot

    got = R.state_face(artifacts_ws)
    live = snapshot(artifacts_ws)
    assert got["tri"] == R.TRI_COMPUTED, got
    assert got["snapshot"] == live, "外挂一层不许改快照本身"
    assert set(got["snapshot"]) == set(live)
    assert "pending_questions" in got["snapshot"]


def test_the_state_face_reports_unreadable_when_it_could_not_read(
        tmp_path: pathlib.Path) -> None:
    """负控（三态）：会话文件读不出来 ⇒ `unreadable`（不是"没有会话"）。

    做法：把这个会话文件换成一个同名的目录（`read_session` 会以 `OSError` 一族
    报出"读不出来"）⇒ 快照把它收进 `problems`，这一面必须跟着变红。
    """
    root = tmp_path / "ws"
    root.mkdir()
    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "x"}, sid="t")
    real = (root / "sessions" / "t.jsonl").read_bytes()
    (root / "sessions" / "t.jsonl").unlink()
    (root / "sessions" / "t.jsonl").mkdir()                # 同名目录 ⇒ 读不出来
    got = R.state_face(root)
    assert got["tri"] == R.TRI_UNREADABLE, got
    assert got["reason"], "变红了却没说为什么"
    # 撤回去 ⇒ 又绿（证明红的成因就是那一处）
    (root / "sessions" / "t.jsonl").rmdir()
    (root / "sessions" / "t.jsonl").write_bytes(real)
    assert R.state_face(root)["tri"] == R.TRI_COMPUTED


# ====================================================================== 2 一趟详情
def test_run_view_reads_runs_report_and_checkpoint(artifacts_ws: pathlib.Path) -> None:
    """正控（一趟详情）：`runs` / `report` / `checkpoint` 三栏都有真读数。

    检查点的 9 个键与 `spend` 的 5 个键逐字钉住（`agent_loop.save_run_checkpoint` +
    `llmseam.SeamSpend.to_dict`）。
    """
    got = R.run_view(artifacts_ws, SID)
    assert got["tri"] == R.TRI_COMPUTED, got
    assert got["sid"] == SID and got["path"].endswith(f"{SID}.jsonl")
    assert len(got["runs"]) == 1, got["runs"]
    run = got["runs"][0]
    assert set(run) == set(R.RUN_ROW_KEYS), (sorted(run), sorted(R.RUN_ROW_KEYS))
    assert run["stop_reason"] == "final" and run["steps"] == 1
    assert got["report"]["status"] == "ok", got["report"]
    assert "夹具样本交付说明" in got["report"]["text"]
    ck = got["checkpoint"]
    assert ck is not None, got["checkpoint_reason"]
    assert set(ck) == {"role", "sid", "task", "fingerprint", "step", "stop_reason",
                       "waiting_for", "spend", "at"}, sorted(ck)
    assert set(ck["spend"]) == {"calls", "tokens_in", "tokens_out", "usd",
                                "unknown_usd_calls"}, sorted(ck["spend"])
    assert ck["step"] == 3 and ck["stop_reason"] == "waiting_for_user"
    assert ck["spend"]["usd"] == 0.25
    assert SID in got["checkpoint_reason"]


def test_run_view_says_missing_session_is_unreadable(tmp_path: pathlib.Path) -> None:
    """负控（三态）：会话文件不在盘上 ⇒ `unreadable`，而不是"这一趟 0 条事件"。"""
    root = tmp_path / "ws"
    root.mkdir()
    got = R.run_view(root, "nope")
    assert got["tri"] == R.TRI_UNREADABLE, got
    assert "不在盘上" in got["reason"], got
    assert got["runs"] == [] and got["checkpoint"] is None


def test_run_view_says_missing_checkpoint_is_not_applicable(
        tmp_path: pathlib.Path) -> None:
    """负控（三态）：会话在、但这一趟还没落检查点 ⇒ `checkpoint` 是 `None` + 一句理由。

    "还没落检查点"不是"检查点是空的"：读数里必须看得出是哪一档。
    """
    root = tmp_path / "ws"
    root.mkdir()
    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "x"}, sid="t")
    got = R.run_view(root, "t")
    assert got["tri"] == R.TRI_COMPUTED, got
    assert got["checkpoint"] is None
    assert "还没落过检查点" in got["checkpoint_reason"], got["checkpoint_reason"]


def test_run_view_reports_a_corrupt_checkpoint_as_unreadable(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：检查点文件在、但内容不是 JSON ⇒ `unreadable` 并点名它。"""
    p = artifacts_ws / "runs" / f"agent-M-{SID}.json"
    good = p.read_text(encoding="utf-8")
    p.write_text("{这不是 JSON\n", encoding="utf-8")
    try:
        got = R.run_view(artifacts_ws, SID)
        assert got["tri"] == R.TRI_UNREADABLE, got
        assert "检查点" in got["reason"], got["reason"]
    finally:
        p.write_text(good, encoding="utf-8")
    assert R.run_view(artifacts_ws, SID)["tri"] == R.TRI_COMPUTED


# ====================================================================== 2b 逐条事件
# 题 T2-a：`GET /api/run/{sid}/events`。这一组除了"读得到"之外还钉两件事：
# ① 编号口径（`index` 与 `snapshot()` 的 `start_index`/`end_index` 同一套）；
# ② 三态不许塌（会话不在盘上 ⇒ `unreadable`，不是"这一趟 0 条事件"）。

def test_run_events_reads_the_rows_with_the_snapshot_numbering(
        artifacts_ws: pathlib.Path) -> None:
    """正控（逐条事件）：夹具那一段会话的四条事件逐条读出来，编号与快照同一套。

    夹具（`tests/conftest.py`）那一段会话是四行：`agent_run_start` / `agent_step` /
    `agent_run_end` / `user_question`。所以 `total=4`、`index` 0..3；
    而 `RunRow.start_index..end_index` 恰好圈住中间那三条 —— 这就是"同一套编号"的
    机器读数（`webui.state._scan` 与 `sessions.runs_in_session` 都对同一个列表
    `enumerate`）。
    """
    got = R.run_events(artifacts_ws, SID)
    assert got["tri"] == R.TRI_COMPUTED, got
    assert got["sid"] == SID and got["total"] == 4, got
    assert (got["from_index"], got["to_index"], got["truncated"]) == (0, 4, False), got
    rows = got["events"]
    assert [e["index"] for e in rows] == [0, 1, 2, 3], rows
    assert [e["kind"] for e in rows] == ["agent_run_start", "agent_step",
                                         "agent_run_end", "user_question"], rows
    assert all(e["ts"] != "" and e["role"] == "M" for e in rows), rows
    # 自洽：区间长度 == 行数，且 to_index 就是下一次的 since_index
    assert got["to_index"] - got["from_index"] == len(rows)
    assert [e["index"] for e in R.run_events(artifacts_ws, SID,
                                             since_index=got["to_index"])["events"]] == []
    # 「有就带上」的那几栏：`agent_step` 那一行有 shape，夹具没给它 payload/result
    # ⇒ 那一栏就不出现（补一个 null 就等于把"这一行没有"说成"读到了、是空的"）。
    # 真的带 payload/result 的行由下一条用例造出来验。
    step = rows[1]
    assert step["shape"] == "fs.write", step
    assert "payload" not in step and "result" not in step, step
    assert "payload" not in rows[0], rows[0]
    assert set(rows[0]) == {"index", "kind", "ts", "role"}, sorted(rows[0])
    # 每一行都是声明过的键的子集（多一个键就是契约漂移，C 条会在 A 那边报）
    for row in rows:
        assert set(row) <= set(FIELDS["EventRow"]), (sorted(row), sorted(FIELDS["EventRow"]))
    assert set(got) == set(FIELDS["RunEventsView"]), sorted(got)
    # 与快照的趟次编号是同一套：那一趟的事件正好落在 start_index..end_index 里
    run = R.run_view(artifacts_ws, SID)["runs"][0]
    inside = [e["index"] for e in rows
              if run["start_index"] <= e["index"] <= run["end_index"]]
    assert inside == [0, 1, 2], (inside, run["start_index"], run["end_index"])
    # `events_in_run` 是 `end_index - start_index`（不数开始那一行），逐条回放给的是
    # 闭区间 `[start_index, end_index]` 那 3 行 —— 两者差 1 是既有口径，不是漂移。
    assert run["events_in_run"] == 2, run["events_in_run"]
    assert len(inside) == run["events_in_run"] + 1


def test_run_events_pages_by_since_index_and_marks_truncation(
        artifacts_ws: pathlib.Path) -> None:
    """正控（游标分页）：`since_index` 是左闭游标，`limit` 截断时 `truncated=True`。

    四档都摆出来：续取（游标落在第一条上）、`limit` 截断、越过末尾（合法空页）、
    越界钳位（99 → 4）。四种情况下 `from_index`/`to_index`/`total` 都必须自洽。
    """
    page2 = R.run_events(artifacts_ws, SID, since_index=2)
    assert page2["events"][0]["index"] == 2, page2["events"]
    assert (page2["from_index"], page2["to_index"], page2["total"]) == (2, 4, 4), page2
    assert page2["truncated"] is False, page2

    tiny = R.run_events(artifacts_ws, SID, limit=2)
    assert [e["index"] for e in tiny["events"]] == [0, 1], tiny["events"]
    assert (tiny["from_index"], tiny["to_index"], tiny["total"]) == (0, 2, 4), tiny
    assert tiny["truncated"] is True, tiny

    one = R.run_events(artifacts_ws, SID, since_index=2, limit=1)
    assert [e["index"] for e in one["events"]] == [2], one["events"]
    assert (one["from_index"], one["to_index"]) == (2, 3), one
    assert one["truncated"] is True, one

    # 越过末尾：一页空的，但那是「读到了，游标在末尾」—— `tri` 仍是 computed
    past = R.run_events(artifacts_ws, SID, since_index=4)
    assert past["tri"] == R.TRI_COMPUTED, past
    assert past["events"] == [] and past["from_index"] == 4 and past["to_index"] == 4, past
    assert past["truncated"] is False, past
    # 越界钳位：99 钳到 4，不抛、不吐无限
    clamped = R.run_events(artifacts_ws, SID, since_index=99)
    assert (clamped["from_index"], clamped["to_index"]) == (4, 4), clamped
    # 上限：超了按上限截断并在 reason 里说明（读模型自己钳，handler 那一层也钳）
    huge = R.run_events(artifacts_ws, SID, limit=10 ** 9)
    assert len(huge["events"]) <= R.EVENTS_LIMIT_MAX, len(huge["events"])
    assert "超上限" in huge["reason"] and str(R.EVENTS_LIMIT_MAX) in huge["reason"], huge
    # `limit=0` / 负数：读模型这一层只钳位（不抛），HTTP 那一层才是 400（见下面那条用例）
    zero = R.run_events(artifacts_ws, SID, limit=0)
    assert len(zero["events"]) == 1 and "小于 1" in zero["reason"], zero
    assert R.run_events(artifacts_ws, SID, limit=-7)["total"] == 4


def test_run_events_carries_the_optional_columns_only_when_the_row_has_them(
        tmp_path: pathlib.Path) -> None:
    """正控（"有就带上"的那几栏）：行里有就原样给，没有就不出现（也不补 null/false）。

    三档在一条用例里摆齐：有值的（`ok`/`usd`/`tokens_*`/`shape`/`payload`/`result`）、
    有这一栏但算不出价钱的（`usd: null`，必须仍是 `null` 而不是被丢掉）、
    以及"这一行根本没有这一栏"（键不出现）。`stopped` 今天没有生产者，
    这一格至少要在"行里真有它"时转发得出去。
    """
    root = tmp_path / "ws"
    root.mkdir()
    SS.append(root, {"kind": "llm_call", "role": "M", "ok": True, "usd": 0.5,
                     "tokens_in": 3, "tokens_out": 4, "shape": "llm.call"}, sid="t")
    SS.append(root, {"kind": "agent_step", "role": "M", "usd": None,
                     "payload": {"path": "out/x.md"}, "result": {"ok": True}}, sid="t")
    SS.append(root, {"kind": "agent_note", "role": "M", "text": "一句摘要"}, sid="t")
    SS.append(root, {"kind": "agent_run_end", "role": "M", "stopped": True}, sid="t")
    rows = R.run_events(root, "t")["events"]
    assert set(rows[0]) == {"index", "kind", "ts", "role", "shape", "ok", "usd",
                            "tokens_in", "tokens_out"}, sorted(rows[0])
    assert rows[0]["ok"] is True and rows[0]["tokens_in"] == 3, rows[0]
    assert rows[1]["usd"] is None, "有这一栏但算不出价钱：必须是 null，不许被丢掉"
    assert rows[1]["payload"] == {"path": "out/x.md"} and rows[1]["result"] == {"ok": True}
    assert rows[2]["text"] == "一句摘要" and "payload" not in rows[2], rows[2]
    assert rows[3]["stopped"] is True, rows[3]


def test_run_events_says_a_missing_session_is_unreadable(
        tmp_path: pathlib.Path) -> None:
    """负控（三态）：会话文件不在盘上 ⇒ `unreadable` + 点名那个路径。

    这一档最要紧：`unreadable` 绝不能回一页"看起来像没有事件"的空读数 ——
    所以除了 `events == []` 之外，计数栏一律是 `None`（不是 0），理由里带路径。
    """
    root = tmp_path / "ws"
    root.mkdir()
    got = R.run_events(root, "nope")
    assert got["tri"] == R.TRI_UNREADABLE, got
    assert "不在盘上" in got["reason"] and "nope.jsonl" in got["reason"], got["reason"]
    assert got["events"] == [] and got["truncated"] is False, got
    assert got["total"] is None and got["from_index"] is None, got
    assert got["to_index"] is None, got
    # 逆命题：这个工作区里连 sessions/ 都没有 ⇒ 它不是"读到了 0 条"
    assert got["total"] != 0, "「没查成」被折成了 0"


def test_run_events_says_an_empty_session_is_not_applicable(
        tmp_path: pathlib.Path) -> None:
    """负控（三态）：会话文件在盘上但是空的 ⇒ `not_applicable` + "还没写过"。"""
    root = tmp_path / "ws"
    root.mkdir()
    (root / "sessions").mkdir()
    (root / "sessions" / "empty.jsonl").write_text("", encoding="utf-8")
    got = R.run_events(root, "empty")
    assert got["tri"] == R.TRI_NOT_APPLICABLE, got
    assert "空的" in got["reason"] and "不是没查成" in got["reason"], got["reason"]
    assert got["total"] is None and got["from_index"] is None, got
    assert got["events"] == [], got


def test_run_events_reports_bad_lines_but_keeps_the_readable_rows(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：会话里有一行坏 JSON ⇒ `unreadable` + 坏行数，而读得出来的照常给。

    两种错法都摆出来：只报 `tri` 会让"有坏行"消失，把行清空会让"这一趟有 4 条事件"
    变成一句假话 —— 这一条同时钉住两头。红前绿后：把那一行撤掉 ⇒ 又变绿。
    """
    path = artifacts_ws / "sessions" / f"{SID}.jsonl"
    good = path.read_text(encoding="utf-8")
    path.write_text(good + "{ 这一行不是 JSON\n", encoding="utf-8")
    try:
        got = R.run_events(artifacts_ws, SID)
        assert got["tri"] == R.TRI_UNREADABLE, got
        assert "坏行" in got["reason"], got["reason"]
        assert got["total"] == 4 and len(got["events"]) == 4, got
    finally:
        path.write_text(good, encoding="utf-8")
    assert R.run_events(artifacts_ws, SID)["tri"] == R.TRI_COMPUTED


# ---- 端点那一层（真实 HTTP：参数校验与"处理器缺了必须吵"）
@contextmanager
def _server(root: pathlib.Path) -> Iterator[str]:
    """在临时端口上起一个真实的 web 服务（这一组的 HTTP 判据走它）。"""
    from agentflow import webui as W

    srv = W.serve(root, host="127.0.0.1", port=0, csrf_token="readerstoken0123456789")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _get(base: str, path: str) -> tuple[int, dict[str, Any], str]:
    """一次 GET：返回 `(状态码, 解出来的 JSON（不是 JSON 就是空 dict）, 正文)`。"""
    conn = http.client.HTTPConnection(base, timeout=20)
    try:
        conn.request("GET", path, headers={"Accept": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {"_list": body}, raw
    finally:
        conn.close()


def test_the_events_endpoint_answers_json_and_bounds_every_bad_cursor(
        artifacts_ws: pathlib.Path) -> None:
    """正控 + 边界（真实 HTTP）：正常取一页；非法的游标一律 400 + JSON，超上限有界。

    后者是"不吐无限"那一条的机器读数：`limit` 给多大，返回的事件数都不超过上限
    （`limit` 超上限那一档不是非法 —— 按上限截断并在 `reason` 里说明）。
    """
    with _server(artifacts_ws) as base:
        code, got, raw = _get(base, f"/api/run/{SID}/events")
        assert code == 200, (code, raw)
        assert got["tri"] == "computed" and got["total"] == 4, got
        assert [e["index"] for e in got["events"]] == [0, 1, 2, 3], got["events"]
        # 三态那一档也在 HTTP 上验一次（会话不在盘上 ⇒ 200 + unreadable，不是 500）
        code_none, none_got, _raw = _get(base, "/api/run/nope/events")
        assert code_none == 200, code_none
        assert none_got["tri"] == "unreadable" and none_got["reason"], none_got

        # 非法游标 ⇒ 400 + JSON（`/api/*` 一律 JSON，裁定 Q1）
        for query in ("limit=0", "limit=-1", "since_index=-5", "since_index=abc",
                      "limit=abc", "limit=2.5"):
            code_bad, bad, raw_bad = _get(base, f"/api/run/{SID}/events?{query}")
            assert code_bad == 400, (query, code_bad, raw_bad)
            assert bad.get("reason"), (query, bad)
            assert bad.get("ok") is False, (query, bad)

        # 超上限：有界 + 在读数里说明（这一档是 200，不是 400）
        code_big, big, _raw = _get(base, f"/api/run/{SID}/events?limit=100000")
        assert code_big == 200, code_big
        assert len(big["events"]) <= R.EVENTS_LIMIT_MAX, len(big["events"])
        assert "超上限" in big["reason"], big


def test_the_events_handler_missing_makes_the_endpoint_scream(
        artifacts_ws: pathlib.Path) -> None:
    """负控（接缝）：把 `readers.HANDLERS` 里那个处理器摘掉 ⇒ 真实请求必须 500 且点名。

    路由表与实现的漂移不许静默 404（那会让前端以为"这条端点不存在"）：
    `server._invoke` 两边都找不到时的口径就是 500 + 把名字写进正文。
    摘掉与装回都在这条用例里做（`try/finally`），不让它污染别的用例 ——
    这与契约判据里那条接缝判据是同一个形态（那边用的是 `sse.HANDLERS`）。
    """
    original = R.HANDLERS.pop("handle_run_events")
    try:
        with _server(artifacts_ws) as base:
            code, _body, raw = _get(base, f"/api/run/{SID}/events")
            assert code == 500, (code, raw)
            assert "handle_run_events" in raw, raw
    finally:
        R.HANDLERS["handle_run_events"] = original
    # 装回去之后又绿（证明上面那条红的成因就是那一处）
    assert R.HANDLERS["handle_run_events"] is R.handle_run_events
    with _server(artifacts_ws) as base:
        code_ok, got, _raw = _get(base, f"/api/run/{SID}/events")
        assert code_ok == 200 and got["tri"] == "computed", (code_ok, got)


# ====================================================================== 3 证据链
def test_evidence_chain_reads_every_column(artifacts_ws: pathlib.Path) -> None:
    """正控（证据链）：七栏都在，且验证台账那一栏读到了夹具造的那一行（裁定 K2）。"""
    got = R.evidence_chain(artifacts_ws)
    assert got["tri"] == R.TRI_COMPUTED, got
    for key in ("statements", "conjectures", "experiments", "review_findings",
                "relations", "verifications", "secretary"):
        assert key in got, key
        assert f"{key}_tri" in got, key
    assert len(got["verifications"]) == 1, got["verifications"]
    row = got["verifications"][0]
    assert row["verdict"] == "成立", row
    assert row["proof_sha256"] and row["statement_id"] == "0001"
    assert set(row) == set(FIELDS["VerificationRow"]), sorted(row)
    assert got["secretary"], "秘书台账那一栏没读到夹具造的两条"
    assert got["secretary"][0]["role"] == "M"


def test_evidence_chain_reports_unreadable_when_a_table_is_broken(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：一张表读不出来 ⇒ 整面 `unreadable`，且那一栏也标红。

    "少了一栏"与"那一栏是空的"在界面上必须分得开：所以整面变红之外，那一栏自己的
    `<栏>_tri` 也要是 `unreadable`。
    """
    from agentflow.schema import TABLES

    rel = str(TABLES["statements"]["file"])
    p = artifacts_ws / "data" / rel
    good = p.read_bytes()
    p.write_text("{这不是 JSON\n", encoding="utf-8")
    got = R.evidence_chain(artifacts_ws)
    assert got["tri"] == R.TRI_UNREADABLE, got
    assert got["statements_tri"] == R.TRI_UNREADABLE, got["statements_tri"]
    assert got["statements"] == []
    assert "statements" in got["reason"], got["reason"]
    # 别的栏照常给行（局部坏掉不该把整份读数清空）
    assert got["verifications"], "一栏坏了不该把别的栏也清空"
    p.write_bytes(good)
    assert R.evidence_chain(artifacts_ws)["tri"] == R.TRI_COMPUTED


def test_evidence_chain_on_an_empty_workspace_is_not_applicable(
        tmp_path: pathlib.Path) -> None:
    """负控（三态）：空工作区 ⇒ `not_applicable` + "一张表都没落过盘"，不是 0。"""
    root = tmp_path / "ws"
    root.mkdir()
    got = R.evidence_chain(root)
    assert got["tri"] == R.TRI_NOT_APPLICABLE, got
    assert got["statements"] == [] and got["statements_tri"] == R.TRI_NOT_APPLICABLE
    assert "一张都没落过盘" in got["reason"], got["reason"]


# ====================================================================== 4 产物面
def test_artifacts_face_reads_ledger_handoffs_checks_style_products_tasks(
        artifacts_ws: pathlib.Path) -> None:
    """正控（产物面）：七栏都读到夹具造的东西，且台账逐行核对是 `ok`。"""
    got = R.artifacts_face(artifacts_ws)
    assert got["tri"] == R.TRI_COMPUTED, got
    assert len(got["ledger"]) == 5, got["ledger"]
    assert set(got["ledger"][0]) == set(FIELDS["ArtifactRow"]), sorted(got["ledger"][0])
    assert [r["status"] for r in got["ledger_verify"]] == ["ok"] * 5, got["ledger_verify"]
    assert set(got["ledger_verify"][0]) == set(FIELDS["LedgerVerifyRow"])
    assert len(got["handoffs"]) == 1, got["handoffs"]
    # 交接行的必填 14 栏都在（`revises`/`kind`/`ref_problems` 是"有就带上"的三栏）
    required = tuple(f for f in FIELDS["HandoffRow"]
                     if f not in ("revises", "kind", "ref_problems"))
    assert set(got["handoffs"][0]) >= set(required), sorted(got["handoffs"][0])
    assert [c["id"] for c in got["checks"]] == ["C1", "C2", "C3"], got["checks"]
    assert got["style"]["sections"] == list(conftest.REPORT_STYLE_SECTIONS)
    assert len(got["secretary"]) == 2, got["secretary"]
    assert got["run_dir"].endswith("run-1"), got["run_dir"]
    assert len(got["products"]) == 6, got["products"]
    assert all(p["exists"] for p in got["products"]), got["products"]
    assert got["tasks"] and got["tasks"][0]["task_id"] == "t-0001"


def test_the_ledger_verify_notices_a_changed_file(artifacts_ws: pathlib.Path) -> None:
    """负控（台账核对）：台账钉的文件被改过 ⇒ 那一行的 `status` 是 `changed`（不是 `ok`）。"""
    got = R.artifacts_face(artifacts_ws)
    assert all(r["status"] == "ok" for r in got["ledger_verify"])
    target = artifacts_ws / "out" / "experiments" / "e-0001.log"
    target.write_text("夹具样本：这一行是后来改的。\n", encoding="utf-8")
    got2 = R.artifacts_face(artifacts_ws)
    statuses = {r["path"]: r["status"] for r in got2["ledger_verify"]}
    assert statuses["out/experiments/e-0001.log"] == "changed", statuses
    # 删掉 ⇒ `missing`（三档不同处置，不许折成一个"不 ok"）
    target.unlink()
    got3 = R.artifacts_face(artifacts_ws)
    statuses3 = {r["path"]: r["status"] for r in got3["ledger_verify"]}
    assert statuses3["out/experiments/e-0001.log"] == "missing", statuses3


def test_artifacts_face_on_an_empty_workspace_is_not_applicable(
        tmp_path: pathlib.Path) -> None:
    """负控（三态）：空工作区 ⇒ `not_applicable`，七栏各带自己的 `tri`，不是 0。"""
    root = tmp_path / "ws"
    root.mkdir()
    got = R.artifacts_face(root)
    assert got["tri"] == R.TRI_NOT_APPLICABLE, got
    for key in ("ledger_tri", "handoffs_tri", "checks_tri", "style_tri",
                "secretary_tri", "products_tri", "tasks_tri"):
        assert got[key] == R.TRI_NOT_APPLICABLE, (key, got[key])
    assert got["ledger"] == [] and got["products"] and not any(
        p["exists"] for p in got["products"])
    assert "本机还没有跑过" in got["products_reason"], got["products_reason"]


def test_artifacts_face_on_a_broken_ledger_is_unreadable(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：台账有一行读不出来 ⇒ 整面 `unreadable` + 点名那一栏。"""
    p = artifacts_ws / "ARTIFACTS.jsonl"
    good = p.read_text(encoding="utf-8")
    p.write_text(good + "{这不是 JSON\n", encoding="utf-8")
    try:
        got = R.artifacts_face(artifacts_ws)
        assert got["tri"] == R.TRI_UNREADABLE, got
        assert got["ledger_tri"] == R.TRI_UNREADABLE
        assert "读不出来" in got["reason"], got["reason"]
    finally:
        p.write_text(good, encoding="utf-8")
    assert R.artifacts_face(artifacts_ws)["tri"] == R.TRI_COMPUTED


def test_run_products_marks_a_missing_product_not_zero(
        artifacts_ws: pathlib.Path) -> None:
    """负控（六件产物）：少一件 ⇒ 那一件 `exists=false` + `tri=not_applicable`，
    `bytes`/`lines` 是 `None`（不是 0 —— 那是"没读到"，不是"读到了 0 字节"）。"""
    (artifacts_ws / "out" / "run-1" / "claims.json").unlink()
    got = R.run_products(artifacts_ws)
    claims = next(p for p in got["products"] if p["name"] == "claims.json")
    assert claims["exists"] is False and claims["tri"] == R.TRI_NOT_APPLICABLE
    assert claims["bytes"] is None and claims["lines"] is None
    # `.json` 的 lines 按设计是 None（只有 .jsonl 能数行），那不是"0 行"
    report = next(p for p in got["products"] if p["name"] == "report.md")
    assert report["exists"] and report["lines"] is None and report["bytes"]
    # jsonl 那一件数得出真行数
    tr = next(p for p in got["products"] if p["name"] == "model-transcript.jsonl")
    assert tr["lines"] == 2, tr


# ====================================================================== 5 收工门
def test_acceptance_face_reads_the_five_criteria_and_five_aux(
        artifacts_ws: pathlib.Path) -> None:
    """正控（收工门）：5 条判据 + 5 条辅助读数的键名逐字来自 `reviewaccept`。"""
    from agentflow.reviewaccept import AUXILIARY_SIGNALS, CRITERIA

    got = R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws))
    assert got["tri"] == R.TRI_COMPUTED, got
    assert set(got["criteria"]) == {k for k, _d in CRITERIA}, got["criteria"]
    assert set(got["auxiliary"]) == {k for k, _d in AUXILIARY_SIGNALS}, got["auxiliary"]
    assert set(got["details"]) == {k for k, _d in CRITERIA}
    assert got["failed"] == sorted(k for k, v in got["criteria"].items() if v != "pass")
    assert got["auxiliary_note"], "辅助读数那句『只供人看』必须带回来"


def test_acceptance_face_leaves_the_cost_gate_unknown_without_a_cap(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：不给我 `cap_usd` ⇒「在成本上限内」那一格是 `unknown`。

    这一档是 `draft/75 §2.10` 第③行点名要的：没给上限时那一格是"没查成"，
    不是"在预算内"。判据同时要求 `reason` 把它点名。
    """
    got = R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws), cap_usd=None)
    assert got["criteria"]["within_cost_cap"] == "unknown", got["criteria"]
    assert "within_cost_cap" in got["reason"], got["reason"]
    # 给了上限 ⇒ 那一格不再因为"没给上限"而 unknown（它可能 fail/pass，那是另一回事）
    got2 = R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws), cap_usd=1.0)
    assert got2["criteria"]["within_cost_cap"] != "unknown", got2["criteria"]


def test_acceptance_face_says_unknown_branch_without_a_sid(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：不给我 `sid` ⇒ `triage_branch_recorded` 是 `unknown`。

    这条与 `tests/test_sid_scoped_questions.py` 是同一件事的两端：那边钉的是
    "带 sid 就看得见"，这边钉的是"不带 sid 时是没查成，不是通过"。
    """
    got = R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws), cap_usd=1.0)
    assert got["criteria"]["triage_branch_recorded"] == "unknown", got["criteria"]
    assert "triage_branch_recorded" in got["reason"], got["reason"]
    got2 = R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws), cap_usd=1.0,
                             sid=SID)
    assert got2["criteria"]["triage_branch_recorded"] == "fail", got2["criteria"]
    assert "没被回答" in got2["details"]["triage_branch_recorded"], got2["details"]


# ====================================================================== 6 本机
def test_machine_face_keeps_the_toolchain_keys_and_never_shows_a_key(
        artifacts_ws: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path) -> None:
    """正控（本机）：工具链那些键逐字保留；设置里的 key 只给"配没配"与掩码。

    判据逐字符断言一个真 key 不在读数里（裁定 E1：key 只写不读）。
    """
    secret = "sk-真key-绝不许出现在读数里-0123456789"
    settings_file = tmp_path / "settings-real.json"
    settings_file.write_text(json.dumps({
        "toolchain": {"lean_bin": "/opt/lean", "mathlib_root": "/opt/mathlib"},
        "model": {"api_key": secret, "base_url": "http://127.0.0.1:9", "name": "m1"},
        "workspace": {"projects_dir": "/tmp/projects"},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("AGENTFLOW_SETTINGS", str(settings_file))
    got = R.machine_face(artifacts_ws)
    from agentflow.toolchain import toolchain_report

    assert set(got) >= set(toolchain_report()), (sorted(got), sorted(toolchain_report()))
    assert set(got["provers"]) == {"checked", "available", "available_names",
                                   "probe_errors", "reason", "looked_in", "sources"}
    assert got["settings_tri"] == R.TRI_COMPUTED, got
    assert got["settings"]["exists"] is True
    assert got["settings"]["model"]["api_key"] == "***", got["settings"]["model"]
    assert got["settings"]["model"]["configured"] is True
    assert got["settings"]["model"]["base_url"] == "http://127.0.0.1:9"
    assert got["settings"]["toolchain"]["lean_bin"] == "/opt/lean"
    assert secret not in json.dumps(got, ensure_ascii=False), \
        "真 key 出现在读数里了（裁定 E1：key 只写不读）"


def test_machine_face_without_a_settings_file_says_not_applicable(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：设置文件不在盘上 ⇒ 那一段 `not_applicable` + 理由。

    注意它不让整面变红：工具链读得出来就是读得出来；"一部分没配"不等于"整面没查成"。
    """
    got = R.machine_face(artifacts_ws)
    assert got["settings_tri"] == R.TRI_NOT_APPLICABLE, got
    assert "不在盘上" in got["settings_reason"], got["settings_reason"]
    assert got["settings"]["exists"] is False
    assert got["settings"]["model"]["api_key"] == "", got["settings"]["model"]
    assert got["settings"]["model"]["configured"] is False
    assert got["tri"] == R.TRI_COMPUTED, got


def test_machine_face_reports_an_unfinished_probe_as_unreadable(
        artifacts_ws: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（三态）：探测没跑完（`provers.checked=false`）⇒ 整面 `unreadable`。

    这一档与 `available == []`（探过了、一个都没找到）必须分得开：前者是"没查成"。
    """
    from agentflow import toolchain as TC

    real = TC.toolchain_report

    def fake(env=None):  # noqa: ANN001 - 与真签名同形
        got = dict(real(env))
        got["provers"] = {"checked": False, "available": [], "available_names": [],
                          "probe_errors": {"lean": "探针超时"}, "reason": "探针没跑完",
                          "looked_in": [], "sources": {}}
        return got

    monkeypatch.setattr(TC, "toolchain_report", fake)
    got = R.machine_face(artifacts_ws)
    assert got["tri"] == R.TRI_UNREADABLE, got
    assert "checked=false" in got["reason"], got["reason"]


# ====================================================================== 注册表与接缝
def test_the_two_registries_agree_with_type_decls() -> None:
    """正控（注册表）：`CHECKED_TYPES` / `UNCHECKED_TYPES` 与 `type_decls()` 自洽。

    三条：受核对名单里的接口真的被声明了；欠账名单里的接口也被声明了；两份名单不相交。
    A 线的契约判据 C 拿这两份名单去比对键集合，所以它们自己先不许自相矛盾。
    """
    declared = set(re.findall(r"^export interface ([A-Za-z_][A-Za-z0-9_]*)",
                              R.type_decls(), re.M))
    assert declared, "type_decls() 一个接口都没吐 ⇒ 生成器那一段是空的"
    missing = [n for n in R.CHECKED_TYPES if n not in declared]
    assert not missing, f"受核对名单里有没声明的接口：{missing}"
    missing2 = [n for n in R.UNCHECKED_TYPES if n not in declared]
    assert not missing2, f"欠账名单里有没声明的接口：{missing2}"
    both = sorted(set(R.CHECKED_TYPES) & set(R.UNCHECKED_TYPES))
    assert not both, f"同一个接口不许同时在两份登记里：{both}"
    for name, why in R.UNCHECKED_TYPES.items():
        assert why.strip(), f"{name} 的欠账没有写理由"


def test_the_checked_types_really_have_readings(artifacts_ws: pathlib.Path) -> None:
    """正控（受核对名单不是空的）：名单里每个接口都能在夹具上读出键集合。

    这条是给 A 线的契约判据 C 打前站的：它失败时说明"登记了一件读不出来的事"，
    而那种失败在 A 那边会以"夹具没造出这些读数"的形态出现 —— 在这里先说清楚。
    """
    got: dict[str, set[str]] = {}
    run = R.run_view(artifacts_ws, SID)
    got["RunView"] = set(run)
    got["ReportReadingView"] = set(run["report"])
    if run["checkpoint"]:
        got["CheckpointView"] = set(run["checkpoint"])
        got["CheckpointSpendView"] = set(run["checkpoint"]["spend"])
    ev_rows = R.run_events(artifacts_ws, SID)
    got["RunEventsView"] = set(ev_rows)
    assert ev_rows["events"], "夹具没造出事件行"
    got["EventRow"] = set(ev_rows["events"][0])
    art = R.artifacts_face(artifacts_ws)
    got["ArtifactsView"] = set(art)
    for name, rows in (("ArtifactRow", art["ledger"]),
                       ("LedgerVerifyRow", art["ledger_verify"]),
                       ("HandoffRow", art["handoffs"]),
                       ("SecretaryDecision", art["secretary"]),
                       ("AcceptanceCheck", art["checks"]),
                       ("TaskRow", art["tasks"]),
                       ("RunProduct", art["products"])):
        assert rows, f"夹具没造出 {name} 的行"
        got[name] = set(rows[0])
    got["ReportStyle"] = set(art["style"])
    ev = R.evidence_chain(artifacts_ws)
    got["EvidenceView"] = set(ev)
    got["VerificationRow"] = set(ev["verifications"][0])
    acc = R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws))
    got["AcceptanceView"] = set(acc)
    mach = R.machine_face(artifacts_ws)
    got["MachineView"] = set(mach)
    got["SettingsReading"] = set(mach["settings"])
    missing = [n for n in R.CHECKED_TYPES if n not in got]
    assert not missing, f"受核对名单里这些接口在夹具上没有读数：{missing}（登记该改）"


def test_the_route_table_hands_our_endpoints_to_our_handlers() -> None:
    """正控（接缝）：六个面（加 `/api/state` 与 `/api/stream`）的表项真的进了总表，
    且 `handler_for` 取得到处理器。

    绑定/猴补丁都不需要：`routes.handler_for(name)` 直接读子表模块的 `HANDLERS`
    字典（A 线落的那条接缝）。这条是"我这一半接没接上"的机器读数。
    """
    ours = {name for _m, _p, name in R.ROUTES}
    assert ours == {"handle_state", "handle_run_view", "handle_run_events",
                    "handle_evidence", "handle_artifacts", "handle_acceptance",
                    "handle_machine", "handle_stream"}, ours
    for _m, path, name in R.ROUTES:
        assert path in routes.patterns(), f"{path} 没进总表"
        assert routes.handler_for(name) is not None, f"{name} 没有实现"
        assert callable(routes.handler_for(name)), name
    assert ("GET", "/api/stream", "handle_stream") in routes.ROUTES
    assert R.PENDING_ENDPOINTS == {}, "B1/B3 之后不该还有 PENDING 的端点"


def test_the_run_row_keys_match_what_sessions_computes(artifacts_ws: pathlib.Path) -> None:
    """反真空（两份实现的护栏）：`readers` 与 `sessions` 的趟次键集合逐字相同。

    `readers.run_view` 走 `sessions.runs_in_session`；而 `webui.state._scan` 另有一份
    同形实现（A 线）。这条断言钉住"我这一份与 `RunRow` 的 20 个键一致"——哪天
    `_scan` 改了键而我这边的（或 `RunRow` 的）没跟上，契约判据 C 会红，而这里
    先说清是"两份实现漂移"还是"夹具没造出来"。
    """
    run = R.run_view(artifacts_ws, SID)["runs"][0]
    assert set(run) == set(R.RUN_ROW_KEYS), (sorted(run), sorted(R.RUN_ROW_KEYS))
    live = SS.runs_in_session(
        SS.read_session(artifacts_ws, sid=SID)[0], sid=SID)
    assert set(live[0]) == set(run), (sorted(live[0]), sorted(run))


def test_the_report_reading_uses_the_other_tri_vocabulary(
        artifacts_ws: pathlib.Path) -> None:
    """正控（裁定 N1）：交付说明那一格用 `ok`/`missing`/`unknown`，不许与 `Tri` 互顶。"""
    got = R.run_view(artifacts_ws, SID)["report"]
    assert got["status"] in ("ok", "missing", "unknown"), got
    assert got["status"] == _read_report(artifacts_ws)[0]
    assert got["status"] not in ("computed", "unreadable", "not_applicable"), \
        "两套词表不许互相顶替（裁定 N1）"


def test_every_face_carries_tri_and_reason(artifacts_ws: pathlib.Path) -> None:
    """反真空（三态头）：六个面每一个都给 `tri` 与 `reason`，取值在词表里。"""
    faces = {
        "state": R.state_face(artifacts_ws),
        "run": R.run_view(artifacts_ws, SID),
        "events": R.run_events(artifacts_ws, SID),
        "evidence": R.evidence_chain(artifacts_ws),
        "artifacts": R.artifacts_face(artifacts_ws),
        "acceptance": R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws)),
        "machine": R.machine_face(artifacts_ws),
        "products": R.run_products(artifacts_ws),
    }
    for name, got in faces.items():
        assert got["tri"] in (R.TRI_COMPUTED, R.TRI_UNREADABLE, R.TRI_NOT_APPLICABLE), \
            (name, got["tri"])
        assert isinstance(got.get("reason"), str), name
        if got["tri"] != R.TRI_COMPUTED:
            assert got["reason"], f"{name} 不是 computed 却没给理由"


def test_userio_view_shapes_are_reachable_from_readers() -> None:
    """反真空（L1 收敛的入口）：`userio` 的视图与 `readers` 用到的是同一套形状。

    B4 把"待答/选项"的读取收敛到了 `userio`（那三个 `*_view`）；`readers` 不另写
    第二份选项视图 —— 这条断言两边给出的键集合相同。
    """
    from agentflow.userio import coerce_option, option_view, question_view, reply_view
    from agentflow.webui.state import option_view as state_option_view

    raw = {"label": "甲", "description": "第一档"}
    assert set(option_view(raw)) == {"label", "description", "multi"}
    assert option_view(raw) == state_option_view(raw), "两处选项视图必须同形"
    q = U.Question(qid="q0001", role="M", text="问一句",
                   options=(coerce_option(raw),), multi_select=True)
    qv = question_view(q)
    assert set(qv) == {"qid", "sid", "role", "ts", "timeout_sec", "text", "options",
                       "multi", "index"}, sorted(qv)
    assert qv["multi"] is True and qv["options"][0]["label"] == "甲"
    rv = reply_view({"qid": "q0001", "selected": ["甲"], "custom": ""})
    assert set(rv) == {"qid", "answer", "selected", "custom", "by", "late"}, sorted(rv)
    assert rv["answer"] == "甲"


def test_userio_pending_views_are_the_global_panel_source(
        artifacts_ws: pathlib.Path) -> None:
    """正控（L1 收敛的落点）：全部会话的待答读数是"待答面板"那一份数据。

    `workspace_pending_view` 是界面上"待答必须全局可达"那条纪律的机器形态：
    它按 `(sid, index)` 排序、逐条带会话号与事件下标（`index` 是它在事件流里的位置）。
    """
    from agentflow import userio as U

    allp = U.workspace_pending_view(artifacts_ws)
    assert len(allp) == 1, allp
    one = allp[0]
    assert one["sid"] == SID and one["qid"] == "q0001"
    assert one["role"] == "M" and one["index"] == 3, one
    assert one["options"][0]["label"] == "保留", one["options"]
    assert one["options"][0]["description"] == "第一档", one["options"]
    assert set(one) == {"qid", "sid", "role", "ts", "timeout_sec", "text", "options",
                        "multi", "index"}, sorted(one)
    assert U.pending_view(artifacts_ws, sid=SID) == allp
    assert U.pending_view(artifacts_ws, sid="别的会话") == []


def test_userio_pending_view_drops_answered_questions(tmp_path: pathlib.Path) -> None:
    """负控（L1 收敛）：答过的不再出现在待答里；两段会话各有各的 qid，互不串味。"""
    from agentflow import userio as U

    root = tmp_path / "ws"
    root.mkdir()
    a = U.ask_user(root, role="M", question="甲问", timeout_sec=0, sid="s-one")
    b = U.ask_user(root, role="A", question="乙问", timeout_sec=0, sid="s-two")
    got = U.workspace_pending_view(root)
    assert [(q["sid"], q["qid"]) for q in got] == [("s-one", a.qid),
                                                   ("s-two", b.qid)], got
    U.answer_question(root, qid=a.qid, selected=("好",), sid="s-one")
    left = U.workspace_pending_view(root)
    assert [q["qid"] for q in left] == [b.qid], left
    assert [q["sid"] for q in left] == ["s-two"], left


# ====================================================================== 裁定 2b：/api/state 的路由
class _FakeHandler:
    """`WebHandler` 的最小替身：处理器真正用到的只有 `root` 与 `_json` 两样。"""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.sent: list[tuple[int, Any]] = []

    def _json(self, code: int, obj: Any) -> None:
        self.sent.append((code, obj))


def test_the_state_endpoint_now_belongs_to_readers(artifacts_ws: pathlib.Path) -> None:
    """裁定 2b：`/api/state` 的路由迁到 B 线，而公开面逐键不变。

    这一条在"两边都还在表里"的交接窗口里也必须是绿的（迁的是归属，不是行为）：
    A 线删掉自己那一行之前，总表里会有两条同名表项，而 `match` 命中的名字两边相同
    （都叫 `handle_state`），`server._invoke` 先找 `WebHandler` 的方法、找不到才落到
    子表 —— 所以交接前后跑起来的 JSON 逐字节相同。

    四条读数：① 表项进了总表；② 派发名字在总表里唯一可查（`match` 给出 `handle_state`）；
    ③ `handler_for` 取到的是 readers 那一个（A 把自己的删掉之后就只剩它）；④ 回的 JSON
    与 `webui.snapshot(root)` 同值 —— `temp/_verify_w0.py` 对账的顶层 10 键就是按后者量的。
    """
    from agentflow.webui import snapshot as W_snapshot

    # ① 表项在总表里（且 B 线自己的子表里只登记一条）
    assert ("GET", "/api/state", "handle_state") in routes.ROUTES, routes.ROUTES
    assert [row for row in R.ROUTES if row[1] == "/api/state"] == [
        ("GET", "/api/state", "handle_state")], R.ROUTES
    # ② 派发名字可查（`{sid}` 一类占位符与它无关，这里没有）
    assert routes.match("GET", "/api/state") == ("handle_state", {}), \
        routes.match("GET", "/api/state")
    # ③ 处理器是 readers 这一个
    fn = routes.handler_for("handle_state")
    assert fn is not None, "总表登记了 handle_state，但子表 HANDLERS 里没有它"
    assert fn is R.handle_state, (fn, R.handle_state)
    assert R.HANDLERS["handle_state"] is R.handle_state
    # ④ 回值与 `W.snapshot` 逐键同值（`generated_at` 是那只钟，两次调用必然不同）
    fake = _FakeHandler(artifacts_ws)
    R.handle_state(fake, {}, {})
    assert [code for code, _obj in fake.sent] == [200], fake.sent
    got = fake.sent[0][1]
    want = W_snapshot(artifacts_ws)
    assert set(got) == set(want), (sorted(got), sorted(want))
    for key in want:
        if key == "generated_at":
            continue
        assert got[key] == want[key], key
    # 公开面是裸快照，不是三态包装：错了这一条，前端与 `_verify_w0.py` 会一起错
    assert "tri" not in got and "snapshot" not in got, sorted(got)
    assert "pending_questions" in got and "sessions" in got, sorted(got)


def test_the_state_face_is_still_the_reader_that_wraps_it(
        artifacts_ws: pathlib.Path) -> None:
    """正控（读模型没被端点吃掉）：`state_face` 仍是三态读模型，端点用的是它里面那张快照。

    端点回裸快照、读模型回 `{tri, snapshot, reason}` —— 两者共用同一个
    `webui.state.snapshot(root)`，所以"迁路由"不可能顺带改掉任何一栏读数。
    """
    from agentflow.webui import snapshot as W_snapshot

    face = R.state_face(artifacts_ws)
    assert set(face) == {"tri", "snapshot", "reason"}, sorted(face)
    assert face["tri"] == R.TRI_COMPUTED, face
    assert set(face["snapshot"]) == set(W_snapshot(artifacts_ws))
