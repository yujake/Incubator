# -*- coding: utf-8 -*-
"""业主裁定「甲」（2026-11-02）：趟次索引归索引，未收工的趟另给一份现算档案。

## 一句话

`index/run-index.json` 的口径一字不改：只在"收工成功"时建，收工没做成 / 被叫停
⇒ 那一格如实 `unreadable`（没建就是没建）。另给一条只读读数
`GET /api/run-digest`：从会话事件流现算，不读也不落 `index/run-index.json`。

## 四条判据（逐条对着裁定 ④）

| 判据 | 场景 | 要看到什么 |
|---|---|---|
| a | 造一条"被叫停"的趟（`stop_reason="stop_file"`，走生产收工入口） | 索引格 `unreadable` + 档案格 `computed` 且有值 |
| b | 造一条"收工成功"的趟（`stop_reason="final"`，走生产收工入口） | 两格都 `computed`，而且趟数 / 步数 / spend 逐格一致 |
| c | 删掉事件流（会话文件） | 档案格 `unreadable`，三格计数是 `null` 而不是 0；另：从没有事件流的工作区是 `not_applicable` |
| d | 手改 / 删掉索引 | 档案格的数一个字节都不动（两格各读各的来源，不许互相顶替） |

## 为什么 a / b 要走生产入口

`Conductor.finish_top_level_run` 是"建不建索引"的唯一判据所在（`done` 才建）。
如果夹具直接调 `SS.rebuild_run_index`，判据就绕开了那条判据本身 —— 它证明的只是
"我调了一次建索引"。所以 a / b 都先 `open_top_level_run` 再 `finish_top_level_run`。
"""
from __future__ import annotations

import http.client
import json
import pathlib
import re
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from agentflow import sessions as SS
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
RUN_TSX = REPO / "ui" / "src" / "pages" / "Run.tsx"

TS = "2026-11-02T00:00:00+08:00"

#: 档案格标题（裁定 ③：页面两格并排，这一格是新加的那一格）。
DIGEST_TITLE = "趟次档案（未收工）"
#: 索引格标题（裁定 ③：仍叫「趟次索引（已对账）」）。
INDEX_TITLE = "趟次索引（已对账）"


# ====================================================================== 夹具
def _ws(tmp_path: pathlib.Path, *, stop_reason: str = "final") -> pathlib.Path:
    """一个有会话（一趟真 run）的初始化工作区。

    `agent_run_end` 带上查档要用的四格：`steps` / `spend` / `summons` /
    `final_gaps_reading`（验了几条 / 签了几个的唯一事件源）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "裁定甲夹具",
                     "task_id": "t-000001", "ts": TS}, sid="s1")
    SS.append(root, {"kind": "llm_call", "role": "M", "ok": True, "usd": 0.25,
                     "tokens_in": 3, "tokens_out": 4, "ts": TS}, sid="s1")
    SS.append(root, {"kind": "agent_step", "role": "M", "index": 0, "shape": "fs.write",
                     "payload": {"path": "out/review/REPORT.md"},
                     "result": {"ok": True}, "ts": TS}, sid="s1")
    SS.append(root, {"kind": "agent_run_end", "role": "M", "task_id": "t-000001",
                     "stop_reason": stop_reason, "steps": 1,
                     "summons": ["A", "B"], "messages": 0,
                     "spend": {"calls": 1, "usd": 0.25, "unknown_usd_calls": 0},
                     "final_gaps_reading": {"checked": True, "total": 3,
                                            "unsigned": 1, "unreadable": 0},
                     "final": "写完了", "final_chars": 3, "ts": TS}, sid="s1")
    return root


def _conductor(root: pathlib.Path) -> tuple[Conductor, str]:
    """真 Store + 真 Conductor + 一条顶趟行（与生产同形：`open_top_level_run`）。"""
    st = Store(root)
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    owner = str(cond.open_top_level_run("M", "裁定甲：收工那一笔"))
    return cond, owner


@contextmanager
def _server(root: pathlib.Path) -> Iterator[str]:
    from agentflow import webui as W

    srv = W.serve(root, host="127.0.0.1", port=0)
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


# ====================================================================== a 被叫停
def test_a_stopped_run_leaves_the_index_cell_unreadable_and_the_digest_cell_computed(
        tmp_path: pathlib.Path) -> None:
    """a：被叫停 ⇒ 索引格 `unreadable`（没建），档案格 `computed` 且有值。"""
    root = _ws(tmp_path, stop_reason="stop_file")
    cond, owner = _conductor(root)
    cond.finish_top_level_run(owner, stop_reason="stop_file")

    # 冻结判据的立场：收工没做成 ⇒ 索引不建（这里不是"我们不查"，是"没有"）。
    assert not SS.run_index_path(root).is_file(), "被叫停却建了趟次索引"

    with _server(root) as base:
        code_i, idx = _get(base, "/api/run-index")
        code_d, dig = _get(base, "/api/run-digest?sid=s1")
    assert code_i == 200 and idx["tri"] == "unreadable", idx
    assert idx["usable"] is False and idx["index"] is None, idx
    assert code_d == 200, code_d
    assert dig["tri"] == "computed", dig
    assert dig["scope"] == "session" and dig["sid"] == "s1", dig
    assert dig["runs"] == 1 and dig["steps"] == 1, dig
    assert dig["spend_usd"] == 0.25, dig
    assert dig["dispatched"] == 2, dig
    assert dig["verified"] == 3 and dig["signed_proofs"] == 2, dig
    assert dig["stop_reasons"] == {"stop_file": 1}, dig
    assert dig["start_ts"] == TS and dig["end_ts"] == TS, dig
    # 只读：这一条 GET 不许把索引顺手建出来（裁定 ① 的守卫）。
    assert not SS.run_index_path(root).is_file(), "GET /api/run-digest 写盘了"


# ====================================================================== b 收工成功
def test_b_a_finished_run_makes_both_cells_computed_and_the_numbers_agree(
        tmp_path: pathlib.Path) -> None:
    """b：收工成功 ⇒ 两格都有值，趟数 / 步数 / spend 逐格一致。"""
    root = _ws(tmp_path, stop_reason="final")
    cond, owner = _conductor(root)
    cond.finish_top_level_run(owner, stop_reason="final")
    assert SS.run_index_path(root).is_file(), "收工成功却没建索引"

    with _server(root) as base:
        code_i, idx = _get(base, "/api/run-index")
        code_d, dig = _get(base, "/api/run-digest?sid=s1")
    assert code_i == 200 and idx["tri"] == "computed", idx
    assert idx["usable"] is True and idx["drift"] == [], idx
    assert code_d == 200 and dig["tri"] == "computed", dig

    stored = (idx.get("index") or {}).get("sessions", {}).get("s1") or {}
    runs = stored.get("runs") or []
    assert len(runs) == dig["runs"], (runs, dig)
    assert sum(int(r.get("steps") or 0) for r in runs) == dig["steps"], (runs, dig)
    assert round(sum(float(r.get("spend_usd") or 0.0) for r in runs), 6) == dig["spend_usd"], (
        runs, dig)
    # 数字一致不是"两边都读同一格"：索引那两格来自落盘的 JSON，档案那两格来自事件流。
    for key in ("runs", "steps", "spend_usd"):
        assert dig[key] is not None, (key, dig)


# ====================================================================== c 反真空
def test_c_deleting_the_event_stream_makes_the_digest_unreadable_not_zero(
        tmp_path: pathlib.Path) -> None:
    """c：删掉事件流 ⇒ 档案格 `unreadable`；计数栏是 `null`，不是 0。"""
    root = _ws(tmp_path, stop_reason="stop_file")
    with _server(root) as base:
        _code, before = _get(base, "/api/run-digest?sid=s1")
        assert before["tri"] == "computed", before

        SS.session_path(root, "s1").unlink()
        code, gone = _get(base, "/api/run-digest?sid=s1")
    assert code == 200, code
    assert gone["tri"] == "unreadable", gone
    assert gone["reason"] != "", gone
    for key in ("runs", "unfinished", "steps", "usd", "spend_usd", "dispatched",
                "verified", "signed_proofs"):
        assert gone[key] is None, (key, gone)
    # `sign_files` 不依赖事件流：事件流没了，它仍然如实数盘上的签文件（这个夹具是 0）。
    assert gone["sign_files"] == before["sign_files"] == 0, (before, gone)
    assert gone["stop_reasons"] == {}, gone

    # 三态的另一头：从没有事件流的工作区是 `not_applicable`（不是 0，也不是 unreadable）。
    empty = tmp_path / "empty"
    empty.mkdir()
    Store(empty).init()
    with _server(empty) as base:
        code_e, na = _get(base, "/api/run-digest")
    assert code_e == 200, code_e
    assert na["tri"] == "not_applicable", na
    assert na["runs"] is None and na["steps"] is None, na
    assert na["reason"] != "", na
    # 同一份空工作区点名要一段会话：连 sessions/ 都没有 ⇒ 还是 `not_applicable`
    #（"没有事件流"与"事件流被删了"是两件事：后者见上面那一档 unreadable）。
    with _server(empty) as base:
        code_s, na_sid = _get(base, "/api/run-digest?sid=s1")
    assert code_s == 200, code_s
    assert na_sid["tri"] == "not_applicable", na_sid


# ====================================================================== d 两格不互相顶替
def test_d_tampering_or_deleting_the_index_never_moves_the_digest_numbers(
        tmp_path: pathlib.Path) -> None:
    """d：索引被手改 / 被删 ⇒ 档案那几格一个字节都不动（各读各的来源）。"""
    root = _ws(tmp_path, stop_reason="final")
    cond, owner = _conductor(root)
    cond.finish_top_level_run(owner, stop_reason="final")

    with _server(root) as base:
        _code, first = _get(base, "/api/run-digest?sid=s1")
        _code, idx_ok = _get(base, "/api/run-index")
    assert first["tri"] == "computed" and idx_ok["tri"] == "computed", (first, idx_ok)

    # 手改索引一个字节（steps 1 → 99）：索引那一格必须红，档案那一格不许跟着动。
    path = SS.run_index_path(root)
    path.write_text(path.read_text(encoding="utf-8").replace('"steps": 1', '"steps": 99'),
                    encoding="utf-8")
    with _server(root) as base:
        _code, idx_bad = _get(base, "/api/run-index")
        _code, second = _get(base, "/api/run-digest?sid=s1")
    assert idx_bad["tri"] != "computed" and idx_bad["drift"], idx_bad
    for key in ("tri", "runs", "steps", "spend_usd", "dispatched", "verified",
                "signed_proofs", "sign_files", "stop_reasons", "start_ts", "end_ts"):
        assert second[key] == first[key], (key, first[key], second[key])

    # 删掉整份索引：索引格 unreadable，档案格照旧。
    path.unlink()
    with _server(root) as base:
        _code, idx_none = _get(base, "/api/run-index")
        _code, third = _get(base, "/api/run-digest?sid=s1")
    assert idx_none["tri"] == "unreadable" and idx_none["index"] is None, idx_none
    for key in ("tri", "runs", "steps", "spend_usd", "dispatched", "verified",
                "signed_proofs", "sign_files", "stop_reasons"):
        assert third[key] == first[key], (key, first[key], third[key])


# ====================================================================== e 两个数
def _put_sign_files(root: pathlib.Path, n_signs: int = 2) -> list[pathlib.Path]:
    """造签文件目录：`n_signs` 份逐签 + 一份 `issued.json` 归档。"""
    d = root / "out" / "vsigns"
    d.mkdir(parents=True, exist_ok=True)
    made = []
    for i in range(n_signs):
        p = d / f"{i:064x}.json"
        p.write_text("{}\n", encoding="utf-8")
        made.append(p)
    issued = d / "issued.json"
    issued.write_text('{"schema": "vsigns-issued/1", "signs": []}\n', encoding="utf-8")
    made.append(issued)
    return made


def test_e_signed_proofs_and_sign_files_are_two_different_numbers(
        tmp_path: pathlib.Path) -> None:
    """② 两个数不许共用一格：已签证明位（31）≠ 签文件份数（3）。

    84 的现场：`signed` 读出来 31，而 `out/vsigns/` 里只有 3 个 JSON
    （2 份签 + `issued.json`）。改前两件事共用 `signed` 一格，读的人会把 31 读成
    "签了 31 份"。这一条同时钉反真空：删掉一份签文件 ⇒ `sign_files` 减一，
    而 `signed_proofs` 一个字节都不动（它们各读各的来源）。
    """
    root = _ws(tmp_path, stop_reason="final")
    signs = _put_sign_files(root, n_signs=2)
    with _server(root) as base:
        code, dig = _get(base, "/api/run-digest?sid=s1")
        assert code == 200 and dig["tri"] == "computed", dig
        assert dig["signed_proofs"] == 2, dig
        assert dig["sign_files"] == 3, dig
        assert "signed" not in dig, (
            "旧名字 `signed` 还在 ⇒ 名字与语义继续混用（它数的是证明位，不是签文件）")

        signs[0].unlink()
        code, after = _get(base, "/api/run-digest?sid=s1")
        assert code == 200 and after["tri"] == "computed", after
    assert after["sign_files"] == 2, after
    assert after["signed_proofs"] == dig["signed_proofs"] == 2, (
        "删签文件把已签证明位也改了 ⇒ 两个数不是各读各的来源", after)


# ====================================================================== 页面那一侧
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)


def _code_only(text: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _digest_card_problems(source: str) -> list[str]:
    """两格并排 + 档案格只读自己的来源（d 的页面那一半，纯函数、可负控）。

    检查四件事：
    1. 两个标题都在（索引格仍叫「趟次索引（已对账）」、新格叫「趟次档案（未收工）」）；
    2. 两格被包在同一个并排容器里（`class="two-up"` 且两个 `<Card` 都在里面）；
    3. 页面调了两条不同的端点（`getRunIndex(` 与 `getRunArchive(`）；
    4. 档案格那一段里只出现 `digest.data`、不出现 `index.data` —— 两格的数互相顶替
       正是裁定 ④d 要抓的形态。
    """
    code = _code_only(source)
    problems: list[str] = []
    for title in (INDEX_TITLE, DIGEST_TITLE):
        if title not in code:
            problems.append(f"页面里没有 {title!r} 这一格")
    if "getRunIndex(" not in code:
        problems.append("页面没有调 api.getRunIndex(（索引格没有取数）")
    if "getRunArchive(" not in code:
        problems.append("页面没有调 api.getRunArchive(（档案格没有取数）")
    two_up = code.find('<div class="two-up">')
    if two_up < 0:
        problems.append("两格没有并排（找不到 class=\"two-up\" 的容器）")
    else:
        # 并排容器从 `two-up` 起到下一张（时间线）卡之前；两张并排的卡都要在里面。
        tail = code.find('<Card title="时间线"', two_up)
        inner = code[two_up:tail if tail > two_up else len(code)]
        if INDEX_TITLE not in inner:
            problems.append("索引格不在并排容器里")
        if DIGEST_TITLE not in inner:
            problems.append("档案格不在并排容器里")
    at = code.find(DIGEST_TITLE)
    if at >= 0:
        region = code[at:at + 3000]
        if "digest.data" not in region:
            problems.append("档案格没有读 digest.data")
        if "index.data" in region:
            problems.append("档案格里读了 index.data —— 两格的数互相顶替")
    return problems


def test_the_page_shows_the_two_cells_side_by_side_without_substitution() -> None:
    """d 的页面那一半：两格并排、各读各的端点；改坏之后同一个函数必须报。"""
    source = RUN_TSX.read_text(encoding="utf-8")
    problems = _digest_card_problems(source)
    assert problems == [], problems

    # 负控（纯函数）：把档案格的数据源换成索引 ⇒ 必须报「互相顶替」。
    doctored = source.replace("digest.data.tri", "index.data.tri", 1)
    doctored = doctored.replace("digest.data === null", "index.data === null", 1)
    assert doctored != source, "负控没改到源码"
    assert any("互相顶替" in p for p in _digest_card_problems(doctored)), (
        _digest_card_problems(doctored))
    # 负控：删掉并排容器 ⇒ 必须报。
    flat = source.replace('class="two-up"', 'class="card"')
    assert any("并排" in p for p in _digest_card_problems(flat)), _digest_card_problems(flat)


#: 档案格里两个数的页面判据：名字与语义必须对得上（84 ②）。
_OLD_SIGNED = re.compile(r"digest\.data\.signed\b")


def _digest_count_field_problems(source: str) -> list[str]:
    """档案格必须同时读 `signed_proofs` 与 `sign_files`，且不许再读旧的 `signed`。

    纯函数、可负控：旧名字与语义混用，读的人会把"31 个已签证明位"读成"31 份签文件"。
    """
    code = _code_only(source)
    at = code.find(DIGEST_TITLE)
    problems: list[str] = []
    if at < 0:
        return ["页面里没有档案格"]
    region = code[at:at + 3000]
    if "digest.data.signed_proofs" not in region:
        problems.append("档案格没有读 digest.data.signed_proofs（已签证明位）")
    if "digest.data.sign_files" not in region:
        problems.append("档案格没有读 digest.data.sign_files（签文件份数）")
    if _OLD_SIGNED.search(region):
        problems.append("档案格还在读 digest.data.signed —— 名字与语义混用")
    for label in ("已签证明位", "签文件"):
        if label not in region:
            problems.append(f"档案格没有把 `{label}` 说给读的人")
    return problems


def test_the_page_keeps_the_two_digest_counts_apart() -> None:
    """② 的页面那一半：两个数并排显示、各有各的名字；负控能抓住退回旧名字。"""
    source = RUN_TSX.read_text(encoding="utf-8")
    assert _digest_count_field_problems(source) == [], _digest_count_field_problems(source)

    # 负控：页面退回旧名字 `digest.data.signed` ⇒ 必须报「名字与语义混用」，
    # 而且「没有读 signed_proofs」也要报（不许只改一处就悄悄过）。
    doctored = source.replace("digest.data.signed_proofs", "digest.data.signed", 1)
    assert doctored != source, "负控没改到源码"
    got = _digest_count_field_problems(doctored)
    assert any("signed_proofs" in p for p in got), got
    assert any("混用" in p for p in got), got

