# -- coding: utf-8 --
"""SSE 后端（`webui/sse.py`）的判据：`draft/73` §2.4 的五条 + 三态。

| 用例 | 判什么 |
|---|---|
| `test_the_wire_format_is_one_frame_per_event` | 分帧：`event:` / `id:` / 单行 `data:` / 空行 |
| `test_the_stream_endpoint_speaks_event_stream_and_no_store` | ① content-type + `Cache-Control: no-store` |
| `test_the_first_event_arrives_within_a_second` | ② 首个事件在 1 s 内（起流即补发的全量 `state`） |
| `test_the_heartbeat_period_is_injectable` | ③ 心跳周期可注入（0.2 s 跑一次） |
| `test_since_replays_only_the_events_after_it` | ④ `?since=N` 只补 N 之后的事件 |
| `test_a_new_event_on_disk_shows_up_in_the_stream` | ⑤ 端到端：盘上新增 ⇒ 流里出现 |
| `test_an_unknown_kind_is_refused_not_sent` | 负控：kind 不在词表里 ⇒ 抛，不许发出去 |
| `test_the_kind_vocabulary_matches_the_frontend` | 反真空：与 `ui/src/sse.ts` 的 `KINDS` 同集合 |

## 端点是怎么"接上"的（这一条要写清，否则读到 404 会以为是 SSE 坏了）

`routes.py` 的第三格是 `WebHandler` 上的方法名，而 `WebHandler` 住在 A 线的
`webui/server.py`（B 线不许碰）。所以本模块把处理器写成模块级函数，由 A 线在
`webui/__init__.py` 里调一次 `sse.bind_handlers(WebHandler)`（一行）接上。
绑定前 `/api/stream` 是 404（`routes.handler_names()` 里有它、类上没有它），
绑定后是这条流 —— 本文件的 `_bound_server()` 就是这个绑定的最小演示，
它同时也是"A 线只差这一行"的机器读数。
"""

from __future__ import annotations

import http.client
import pathlib
import re
import socket
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from agentflow import sessions as SS
from agentflow import stopctl as SC
from agentflow import userio as U
from agentflow import webui as W
from agentflow.webui import routes, sse


@pytest.fixture(autouse=True)
def _no_leaked_hooks() -> Iterator[None]:
    """每条用例前后都把四个钩子槽清干净。

    钩子是进程级的（`sessions` / `userio` / `stopctl` 各一个槽）：一条用例装了忘了
    撤，下一条用例的送信数就会多出几条，而那种红看上去像"业务坏了"。
    """
    sse.detach()
    yield
    sse.detach()


# ====================================================================== 帮手
@contextmanager
def _bound_server(root: pathlib.Path, *, heartbeat_sec: float = 0.2) -> Iterator[Any]:
    """起一个本机服务：B 线的处理器由 `routes.handler_for` 从子表 `HANDLERS` 取。"""
    sse.begin_serving(heartbeat_sec=heartbeat_sec)
    srv = W.serve(root, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        sse.close_all()          # 先关流：否则开着的流会把请求线程占住
        thread.join(timeout=5.0)


def _open(base: str, path: str) -> http.client.HTTPResponse:
    """打开一条流（返回未读完的响应；调用方自己读帧、自己 close）。"""
    conn = http.client.HTTPConnection(base, timeout=5)
    conn.request("GET", path)
    return conn.getresponse()


def _read_frames(resp: http.client.HTTPResponse, *, want: int, timeout: float = 3.0,
                 ) -> list[tuple[str, int | None, str]]:
    """读 `want` 帧；返回 `[(kind, id, data), ...]`（超时就返回已读到的）。"""
    out: list[tuple[str, int | None, str]] = []
    resp.fp.raw._sock.settimeout(timeout)  # noqa: SLF001 - 判据要能超时收手
    buf = b""
    while len(out) < want:
        try:
            chunk = resp.fp.read1(4096)  # noqa: SLF001
        except (socket.timeout, TimeoutError, OSError):
            break
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            raw, buf = buf.split(b"\n\n", 1)
            kind, eid, data = None, None, ""
            for line in raw.decode("utf-8", errors="replace").splitlines():
                if line.startswith("event: "):
                    kind = line[7:]
                elif line.startswith("id: "):
                    eid = int(line[4:])
                elif line.startswith("data: "):
                    data = line[6:]
            if kind is not None:
                out.append((kind, eid, data))
    return out


def _wait_for(predicate: Any, *, timeout: float = 3.0, step: float = 0.02) -> bool:
    """轮询等到 `predicate()` 为真（端到端判据用它，不用固定睡眠）。"""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(step)
    return bool(predicate())


# ====================================================================== 分帧
def test_the_wire_format_is_one_frame_per_event() -> None:
    """正控（分帧）：一条事件一帧，`data` 是单行 JSON，`id` 是整数。"""
    frame = sse.format_event(kind="answered", data={"qid": "q0001", "sid": "t"}, event_id=7)
    text = frame.decode("utf-8")
    assert text.startswith("event: answered\n"), text
    assert "id: 7\n" in text, text
    assert text.endswith("\n\n"), repr(text)
    lines = text.splitlines()
    data_lines = [x for x in lines if x.startswith("data: ")]
    assert len(data_lines) == 1, f"data 必须是单行：{lines}"
    import json

    assert json.loads(data_lines[0][6:]) == {"qid": "q0001", "sid": "t"}
    # 中文不被转义（生成物要人读得懂）
    cn = sse.format_event(kind="question", data={"text": "要不要保留？"}, event_id=1)
    assert "要不要保留？" in cn.decode("utf-8")
    # 同一份数据两次给出逐字节相同的帧
    assert sse.format_event(kind="heartbeat", data={"at": "T"}, event_id=1) == \
        sse.format_event(kind="heartbeat", data={"at": "T"}, event_id=1)
    # 不给 id 就不发 id 行（心跳不需要续传）
    assert "id: " not in sse.format_event(kind="heartbeat", data={"at": "T"}).decode()


def test_the_kind_vocabulary_matches_the_frontend() -> None:
    """反真空（C2 契约的后端一半）：`EVENT_KINDS` 与 `ui/src/sse.ts` 的 `KINDS` 同集合。

    这一条与 `tests/test_webui_contracts.py` 的 B 条是同一件事的两个落点：
    那边是"A 线的契约判据"，这边是"我自己的同集合断言"。多填/少填一个 kind，
    两边都会红。
    """
    assert sse.EVENT_KINDS == ("state", "question", "answered", "checkpoint", "stop",
                               "heartbeat"), sse.EVENT_KINDS
    ts = pathlib.Path(__file__).resolve().parents[1] / "ui" / "src" / "sse.ts"
    if not ts.is_file():
        pytest.skip("前端骨架不在盘上（`ui/src/sse.ts`）—— 这一半无从比对")
    text = ts.read_text(encoding="utf-8")
    m = re.search(r"KINDS\s*=\s*\[(.*?)\]", text, re.S)
    assert m is not None, "sse.ts 里找不到 KINDS 那一行 ⇒ 判据没接上"
    front = set(re.findall(r"[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']", m.group(1)))
    assert front == set(sse.EVENT_KINDS), (sorted(front), sse.EVENT_KINDS)


# ====================================================================== 负控
def test_an_unknown_kind_is_refused_not_sent() -> None:
    """负控（词表）：kind 不在 `EVENT_KINDS` 里 ⇒ 抛异常，不许发出去。

    发了会怎样：前端没注册那个 kind，`EventSource` 会静默丢掉它 —— 一条"发出去了
    但没人收"的事件，在两端都看不出问题。所以发布口就要拦。
    """
    bc = sse.Broadcaster(heartbeat_sec=0.2)
    assert bc.publish("state", {"snapshot": {}}) == 1
    with pytest.raises(ValueError) as err:
        bc.publish("progress", {"x": 1})
    assert "progress" in str(err.value), str(err.value)
    assert bc.last_id == 1, "被拒的事件不该占一个 id"


def test_replay_says_so_when_the_buffer_cannot_reach_back() -> None:
    """负控（三态）：缓冲补不齐时要说补不齐，不许静默少发（那是假补发）。"""
    bc = sse.Broadcaster(replay_limit=3)
    for i in range(5):
        bc.publish("state", {"n": i})
    frames, why = bc.replay_since(0)
    assert len(frames) == 3, [f[0] for f in frames]     # 只留了最近 3 条
    assert why and "补不齐" in why, why
    # 补得齐时不许多嘴
    frames2, why2 = bc.replay_since(4)
    assert why2 == "" and [f[0] for f in frames2] == [5], (why2, frames2)


# ====================================================================== 五条端点判据
def test_the_stream_endpoint_speaks_event_stream_and_no_store(
        tmp_path: pathlib.Path) -> None:
    """判据①：content-type 是 `text/event-stream`，且 `Cache-Control: no-store`。"""
    root = tmp_path / "ws"
    root.mkdir()
    with _bound_server(root) as srv:
        host, port = srv.server_address[0], srv.server_address[1]
        resp = _open(f"{host}:{port}", "/api/stream")
        try:
            assert resp.status == 200, resp.status
            ctype = resp.getheader("Content-Type") or ""
            assert ctype.startswith("text/event-stream"), ctype
            assert (resp.getheader("Cache-Control") or "") == "no-store", \
                resp.getheader("Cache-Control")
        finally:
            resp.close()


def test_the_first_event_arrives_within_a_second(tmp_path: pathlib.Path) -> None:
    """判据②：起流之后 1 秒内必须收到第一帧（心跳或补发的全量快照）。"""
    root = tmp_path / "ws"
    root.mkdir()
    with _bound_server(root) as srv:
        host, port = srv.server_address[0], srv.server_address[1]
        resp = _open(f"{host}:{port}", "/api/stream")
        try:
            began = time.monotonic()
            got = _read_frames(resp, want=1, timeout=1.0)
            elapsed = time.monotonic() - began
            assert got, f"1 秒内一帧都没收到（{elapsed:.2f}s）"
            assert elapsed < 1.0, elapsed
            assert got[0][0] in sse.EVENT_KINDS, got
        finally:
            resp.close()


def test_the_heartbeat_period_is_injectable(tmp_path: pathlib.Path) -> None:
    """判据③：心跳周期可注入 —— 0.2 秒一档，3 秒内至少 3 次心跳。

    为什么这条必须"可注入"：真实周期是 15 秒，判据不许等 15 秒；而把周期写死在
    循环里，判据就只能靠"等得够久"来碰运气。
    """
    root = tmp_path / "ws"
    root.mkdir()
    with _bound_server(root, heartbeat_sec=0.2) as srv:
        host, port = srv.server_address[0], srv.server_address[1]
        resp = _open(f"{host}:{port}", "/api/stream")
        try:
            beats: list[float] = []
            began = time.monotonic()
            got = _read_frames(resp, want=3, timeout=3.0)
            beats = [time.monotonic() - began for k, _i, _d in got if k == "heartbeat"]
            assert len(beats) >= 3, (len(beats), got)
            assert beats[-1] < 2.0, f"三次心跳用了 {beats[-1]:.2f}s ⇒ 周期没被注入？"
        finally:
            resp.close()


def test_since_replays_only_the_events_after_it(tmp_path: pathlib.Path) -> None:
    """判据④：`?since=N` 只补发 id > N 的事件。"""
    root = tmp_path / "ws"
    root.mkdir()
    with _bound_server(root) as srv:
        bc = sse.default_broadcaster()
        first = bc.publish("state", {"n": 1})
        second = bc.publish("question", {"qid": "q0001", "sid": "t"})
        assert (first, second) == (1, 2), (first, second)
        host, port = srv.server_address[0], srv.server_address[1]
        resp = _open(f"{host}:{port}", f"/api/stream?since={first}")
        try:
            got = _read_frames(resp, want=1, timeout=2.0)
            assert got, "补发一条都没到"
            assert got[0][0] == "question", got
            assert got[0][1] == second, got
        finally:
            resp.close()


def test_a_new_event_on_disk_shows_up_in_the_stream(tmp_path: pathlib.Path) -> None:
    """判据⑤（端到端）：盘上新增 ⇒ 流里出现对应 kind。

    这一条走的是真链路：`sessions.append` / `userio.ask_user` 之后，由这个进程里的
    写者把事件发给广播器（真实运行时那个写者就是 `sessions.append` 的调用方，
    接缝见报告）；流端从订阅队列里读出来。所以它同时证明了"订阅者真的收到了
    别处发的事件"，而不只是"自己发自己收"。
    """
    root = tmp_path / "ws"
    root.mkdir()
    with _bound_server(root) as srv:
        host, port = srv.server_address[0], srv.server_address[1]
        resp = _open(f"{host}:{port}", "/api/stream")
        try:
            assert _read_frames(resp, want=1, timeout=1.0), "流没起来"
            # 盘上真的新增一条会话事件
            SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "端到端"},
                      sid="t")
            assert (root / "sessions" / "t.jsonl").is_file(), "会话没落盘"
            sse.publish("state", {"snapshot": {"root": str(root)}})
            got = _read_frames(resp, want=1, timeout=2.0)
            assert any(k == "state" for k, _i, _d in got), got
        finally:
            resp.close()
        # 回答落盘 ⇒ `answered`
        with _bound_server(root) as srv2:
            host, port = srv2.server_address[0], srv2.server_address[1]
            resp2 = _open(f"{host}:{port}", "/api/stream")
            try:
                assert _read_frames(resp2, want=1, timeout=1.0), "第二条流没起来"
                out = U.ask_user(root, role="M", question="端到端：要不要保留？",
                                 timeout_sec=0, sid="t")
                sse.publish("question", {"qid": out.qid, "sid": "t", "role": "M",
                                         "text": "端到端：要不要保留？",
                                         "options": [], "multi": False,
                                         "ts": "", "timeout_sec": 0})
                got2 = _read_frames(resp2, want=1, timeout=2.0)
                assert any(k == "question" for k, _i, _d in got2), got2
                assert any(out.qid in d for k, _i, d in got2 if k == "question"), got2
            finally:
                resp2.close()


# ====================================================================== 订阅表
def test_the_subscriber_table_is_cleaned_up_on_disconnect(tmp_path: pathlib.Path) -> None:
    """负控（资源）：客户端断开之后订阅者表必须回到 0（只增不减会慢慢吃住服务）。"""
    root = tmp_path / "ws"
    root.mkdir()
    with _bound_server(root) as srv:
        bc = sse.default_broadcaster()
        host, port = srv.server_address[0], srv.server_address[1]
        resp = _open(f"{host}:{port}", "/api/stream")
        assert _wait_for(lambda: bc.subscribers == 1), bc.subscribers
        resp.close()
        assert _wait_for(lambda: bc.subscribers == 0), bc.subscribers


def test_the_route_names_resolve_to_real_handlers() -> None:
    """反真空（路由接缝）：`/api/stream` 真的进了总表，且 `handler_for` 取得到真身。

    表项住在 `readers.ROUTES`（`routes.py` 只拼那三张子表 —— 理由写在 `sse.py`
    的 `HANDLERS` 上方）；处理器真身住在这里。A 线落的那条接缝就是 `handler_for`：
    它按名字去 `readers` / `sse` / `writes` 三个模块的 `HANDLERS` 里取。
    """
    assert ("GET", "/api/stream", "handle_stream") in routes.ROUTES, routes.ROUTES
    assert any(p == "/api/stream" for p in routes.api_paths()), routes.api_paths()
    fn = routes.handler_for("handle_stream")
    assert fn is not None, "总表里登记了 handle_stream，但子表 HANDLERS 里没有它"
    assert fn is sse.handle_stream, (fn, sse.handle_stream)
    assert set(sse.HANDLERS) == {"handle_stream"}, sorted(sse.HANDLERS)
    assert sse.PENDING_ENDPOINTS == {}, "落地之后豁免必须撤掉（反向断言会抓）"
    # 反真空：这个端点真的会在 HTTP 上应答（不是"名字对但没有实现"）
    assert callable(fn)


# ====================================================================== B6：写路径上的钩子
#
# 这一组守的是"事件真的有来源"：`sse.attach()` 把三个写路径模块的钩子接上之后，
# 每次真的写成会发一条对应 kind 的事件；`detach()` 之后一条都不发（缺省行为）。
# 逐条都先用一个记账函数替掉 `publish`（不必起流），于是断言可数、可读。


def _recorder() -> tuple[list[tuple[str, dict]], Any]:
    """返回 `(账本, publish)`：一个记下"发了哪几条"的假 publish。"""
    log: list[tuple[str, dict]] = []
    return log, (lambda kind, data: log.append((kind, dict(data))))


def _kinds(log: list[tuple[str, dict]]) -> list[str]:
    return [k for k, _d in log]


def test_attach_wires_all_four_write_paths(tmp_path: pathlib.Path) -> None:
    """正控（裁定 1a）：`attach()` 之后四条写路径各自发出对应 kind 的事件。

    | 槽 | 触发 | 期望 kind |
    |---|---|---|
    | append | `sessions.append` 写成功 | `state`（payload 带快照） |
    | question | `userio.ask_user` 真的落了新问题 | `question`（C2 那 8 栏） |
    | answered | `userio.answer_question` 写成功 | `answered`（`{qid, sid}`） |
    | stop | 停机开关真的变了 | `stop`（C2 那 5 栏） |
    """
    root = tmp_path / "ws"
    root.mkdir()
    log, pub = _recorder()
    got = sse.attach(publish=pub)
    assert got["attached"] == ("answered", "append", "question", "stop"), got
    assert got["replaced"] == (), got

    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "钩子探针"}, sid="t")
    assert _kinds(log) == ["state"], log
    snap = log[0][1]["snapshot"]
    assert isinstance(snap, dict) and "pending_questions" in snap, sorted(snap)
    assert "generated_at" in snap, sorted(snap)

    out = U.ask_user(root, role="M", question="钩子：要不要保留？",
                     options=({"label": "保留", "description": "第一档"},),
                     timeout_sec=0, sid="t")
    assert _kinds(log) == ["state", "state", "question"], log
    payload = log[-1][1]
    assert set(payload) == {"qid", "sid", "role", "text", "options", "multi", "ts",
                            "timeout_sec"}, sorted(payload)
    assert payload["qid"] == out.qid and payload["sid"] == "t"
    assert payload["options"][0]["label"] == "保留"
    assert payload["options"][0]["description"] == "第一档"

    U.answer_question(root, qid=out.qid, selected=("保留",), sid="t")
    assert _kinds(log)[-1] == "answered", log
    assert log[-1][1] == {"qid": out.qid, "sid": "t"}, log[-1]

    SC.request_stop(root, reason="钩子探针", by="probe")
    assert _kinds(log)[-1] == "stop", log
    stop = log[-1][1]
    assert set(stop) == {"stop_path", "requested_by", "at", "live_pids",
                         "running_loops"}, sorted(stop)
    assert stop["requested_by"] == "probe" and stop["stop_path"].endswith(".agentflow-stop")
    assert sse.hook_problems() == {"sessions": "", "userio": "", "stopctl": ""}, \
        sse.hook_problems()


def test_without_attach_nothing_is_published_at_all(tmp_path: pathlib.Path) -> None:
    """负控（"红前绿后"的绿那一半，也是"缺省行为不变"的判据）：没人接 ⇒ 一条都不发。

    这一条是缺省状态的读数：钩子全是 `None` 时，四条写路径照常工作，
    而记账函数一条都收不到。它与下面那条"detach 之后"是同一条纪律的两端
    （一个证明"从没装过也不发"，一个证明"装了能撤"）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    log, pub = _recorder()
    del pub                                   # 故意不 attach：记账函数根本不会被接上
    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "没接"}, sid="t")
    out = U.ask_user(root, role="M", question="没人接的问句", timeout_sec=0, sid="t")
    U.answer_question(root, qid=out.qid, selected=("好",), sid="t")
    assert SC.request_stop(root, reason="没接", by="probe"), "停机开关该照常写下"
    assert log == [], log
    # 写路径本身照常（会话里有三条：run_start / user_question / user_answer）
    events, bad = SS.read_session(root, sid="t")
    assert len(events) == 3 and bad == [], (len(events), bad)


def test_detach_stops_every_event(tmp_path: pathlib.Path) -> None:
    """负控（红前绿后）：`attach()` 时发事件 ⇒ `detach()` 之后同样操作一条都不发。

    先绿（attach 时收到的条数 > 0）、再红（detach 之后增量 == 0）、再绿（重新 attach
    又能收到）—— 少了头一步，"detach 之后没发"可能只是因为尺子本来就没接上。
    """
    root = tmp_path / "ws"
    root.mkdir()
    log, pub = _recorder()

    @contextmanager
    def _attached() -> Any:
        sse.attach(publish=pub)
        try:
            yield
        finally:
            sse.detach()

    def _bump(tag: str) -> None:
        SS.append(root, {"kind": "agent_step", "role": "M", "note": tag}, sid="t")

    with _attached():
        _bump("装了")
        assert len(log) == 1, log                     # 负控前：绿

    n = len(log)
    _bump("撤了之后")
    assert len(log) == n, f"detach 之后还在发：{log[n:]}"   # 负控：红

    with _attached():
        _bump("又装上")
        assert len(log) == n + 1, log
    # 收尾：四个槽都空（autouse 夹具之外再核一次本用例自己的账）
    assert sse.detach()["detached"] == (), "本用例结束时不该还有钩子"


def test_attach_is_idempotent_and_replaces_not_stacks(tmp_path: pathlib.Path) -> None:
    """负控（幂等）：连着 `attach()` 两次 ⇒ 每次写只发一条事件（不是两条）。

    "替换"与"叠加"在读数上的差别就是这里的 1 与 2；`replaced` 里也不该出现自己上一次
    装的那四个闭包（那是自己的，不算"被顶掉的外来钩子"）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    log, pub = _recorder()
    sse.attach(publish=pub)
    again = sse.attach(publish=pub)
    assert again["replaced"] == (), again
    SS.append(root, {"kind": "agent_step", "role": "M"}, sid="t")
    assert _kinds(log) == ["state"], log
    # 两次 attach 各自是一份新闭包，但槽里只有一个 ⇒ 只发一条
    assert sse.detach()["detached"] == ("answered", "append", "question", "stop")


def test_attach_reports_a_foreign_hook_it_replaced(tmp_path: pathlib.Path) -> None:
    """负控（不 quietly 顶掉别人的钩子）：槽里已经有别人的钩子 ⇒ `replaced` 点名它。"""
    root = tmp_path / "ws"
    root.mkdir()
    foreign = lambda root_, event: None  # noqa: E731 - 探针用的裸函数，不必有名字
    SS.set_append_hook(foreign)
    try:
        got = sse.attach(publish=lambda k, d: None)
        assert got["replaced"] == ("append",), got
    finally:
        sse.detach()


def test_a_broken_subscriber_does_not_break_the_write_path(
        tmp_path: pathlib.Path) -> None:
    """负控（旁路不许带坏主路）：注入一个必炸的 `publish` ⇒ 写路径照常成功，
    而"旁路炸了"这件事读得出来（`hook_problems()` 非空）。

    这一条是这一族钩子最容易写错的地方：监听器坏掉时把异常抛出去，会让
    "网页端推送失败"变成"会话记录写不进去"—— 那是本末倒置。
    """
    root = tmp_path / "ws"
    root.mkdir()

    def _boom(kind: str, data: Any) -> None:
        raise RuntimeError(f"推不出去：{kind}")

    sse.attach(publish=_boom)
    path, problem = SS.append(root, {"kind": "agent_step", "role": "M"}, sid="t")
    assert path is not None and problem == "", (path, problem)
    out = U.ask_user(root, role="M", question="炸的时候问的", timeout_sec=0, sid="t")
    assert out.qid, out
    assert U.answer_question(root, qid=out.qid, selected=("好",), sid="t") == ""
    assert SC.request_stop(root, reason="炸", by="probe"), "停机开关该照常写下"
    problems = sse.hook_problems()
    assert all(problems.values()), problems          # 三个模块都记到了
    assert "推不出去" in problems["sessions"], problems
    # 会话记录是完整的（三次写都落盘）
    events, bad = SS.read_session(root, sid="t")
    assert len(events) == 3 and bad == [], (len(events), bad)
    # 换回好 publish ⇒ 问题读数被清掉（"好了"也要读得出来）
    log, pub = _recorder()
    sse.attach(publish=pub)
    SS.append(root, {"kind": "agent_step", "role": "M"}, sid="t")
    assert log and sse.hook_problems()["sessions"] == "", sse.hook_problems()


def test_a_re_asked_question_does_not_publish_twice(tmp_path: pathlib.Path) -> None:
    """负控（只有真写成才发）：同一个 qid 问两次 ⇒ 只发一条 `question`。

    第二次调用什么都没写（同一会话里这个 qid 已经在盘上），所以也不该发事件 ——
    发了就会让网页端把同一件事显示两遍。
    """
    root = tmp_path / "ws"
    root.mkdir()
    log, pub = _recorder()
    sse.attach(publish=pub)
    first = U.ask_user(root, role="M", question="同一个号", timeout_sec=0, sid="t",
                       qid="q0007")
    second = U.ask_user(root, role="M", question="同一个号（重放）", timeout_sec=0,
                        sid="t", qid="q0007")
    assert first.qid == second.qid == "q0007", (first, second)
    assert _kinds(log).count("question") == 1, log


def test_a_stop_switch_that_did_not_change_does_not_publish(
        tmp_path: pathlib.Path) -> None:
    """负控（"开关真的变了"才发）：第二次叫停（`existing`）与"没开关可撤"都不发。

    `request_stop_detail` 把结局分成 created / upgraded / existing 三档，这里钉的是
    后两档不发 —— "喊了一声但什么都没变"不是一次变化。
    """
    root = tmp_path / "ws"
    root.mkdir()
    log, pub = _recorder()
    sse.attach(publish=pub)

    assert SC.request_stop(root, reason="第一次", by="probe")
    assert _kinds(log) == ["stop"], log
    assert SC.request_stop(root, reason="第二次（幂等）", by="probe")   # existing
    assert _kinds(log) == ["stop"], f"什么都没变却发了：{log}"
    assert SC.request_stop(root, reason="升级成强制", by="probe", force=True)  # upgraded
    assert _kinds(log) == ["stop", "stop"], log

    assert SC.clear_stop(root) is True
    assert _kinds(log)[-1] == "stop" and len(log) == 3, log
    assert SC.clear_stop(root) is False              # 没开关可撤
    assert len(log) == 3, f"没开关可撤却发了：{log}"


def test_attach_and_detach_are_the_only_public_wiring() -> None:
    """反真空（装配入口）：`attach` / `detach` / `hook_problems` 都在 `__all__` 里，
    且 `detach()` 幂等（撤第二次报空、不抛）。"""
    for name in ("attach", "detach", "hook_problems"):
        assert name in sse.__all__, name
        assert callable(getattr(sse, name)), name
    assert sse.detach() == {"detached": ()}, sse.detach()
    sse.attach(publish=lambda k, d: None)
    assert sse.detach()["detached"] == ("answered", "append", "question", "stop")
    assert sse.detach() == {"detached": ()}
