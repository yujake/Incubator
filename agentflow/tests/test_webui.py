# -*- coding: utf-8 -*-
"""用户端 Web 界面：正控与负控（离线，只连本机临时端口的临时服务）。
## 这一组守什么
`docs/USER-END-DSH-STYLE.md` §3.3 抄来的三条纪律，每条都要有机器可查的判据：
1. 「待回答的东西必须全局可达」：面板不按会话过滤（跨会话正控），每条问题要能看到会话号、问题号、谁在问、问了多久、正文、以及每个选项的label 与 description（选项是
`{label, description}` 而不是裸字符串）；2. 「状态一律从盘上派生」（状态不进组件 state）：同一份盘上数据读两次逐字节相同（投影，不是缓存），中间往盘上追加东西后再读 ⇒ 读数必须变；3.
「写回答的失败不许折成 200」：qid 不在待答清单 ⇒ 409（分「已经答过了」与「没有这个号」两档说清），成功 ⇒ 303 PRG（刷新不重复提交）；跳过 = 空的 `selected`（DSH 口径），不是「没答」。
另外两条是本项目的纪律，不是 DSH 的：
4. 「服务器写进 HTML 的一切文本都转义」（写路径给的 409 正文嵌进错误页时，用户给的 `qid` 必须变 `&lt;script&gt;`），外加「前端源码里不许把字符串当HTML 用」—— SPA
那一面的注入面只有那一种写法；5. 「只用令牌」（`ui/src/theme/app.css` 里不许有字面色值，且必须真的是在令牌体系里写样式）。
## W5 清仓之后这一组查的是哪些面（2026-10-08，裁定 P1 的最后一块）
旧壳 `webui/views.py` 已整件退场：`/` 与 `/run/{sid}` 都吐同一支 SPA 外壳，六个页面的读数一律走 `/api/*`。于是这一组里凡是被旧壳 HTML 影响的断言都换到了SPA 面（外壳形状 /
JSON 读数 / 写路径的状态码），用例条数一条没减（旧壳还活着时的 17 条 + 新加的 `/run/{sid}` 外壳那一条）：每条迁移都在它自己的docstring 里逐句写明"原来断言什么、现在断言什么、
为什么是同一件事"。
## 口径兼容（与并行的 `userio` 改造）
回答事件有两种口径：新的 `{"qid","selected":[...],"custom":"...","by","late"}`，以及旧的 `{"qid","answer","by","late"}`。本文件一律用:
func:`agentflow.webui.answer_text_of` 读回答文本（`custom` 非空取它，否则 `"、".join(selected)`，否则退回 `answer`），于是两种口径下判据都成立。
## 为什么不起长期服务
每个用例用 `port=0` 起一个临时端口上的服务，`finally` 里 `shutdown()` +`server_close()`。不联网（只连本机 `127.0.0.1`），不写任何全局状态。
"""
from __future__ import annotations

import http.client
import io
import json
import pathlib
import re
import socket
import struct
import sys
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlencode

import pytest

from agentflow import schema as S
from agentflow import sessions as SS
from agentflow import userio as U
from agentflow import webui as W
from agentflow.web import assets as A
from agentflow.webui import sse as SSE


# ====================================================================== 夹具
@contextmanager
def server(root: pathlib.Path) -> Iterator[str]:
    """在临时端口上起一个本机服务，用完必关（正控与负控都走它）。"""
    srv = W.serve(root, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address[0], srv.server_address[1]
    try:
        yield f"{host}:{port}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _get(base: str, path: str) -> tuple[int, str]:
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8")
    finally:
        conn.close()


def _get_full(base: str, path: str, *, accept: str = "") -> tuple[int, str, dict[str, str]]:
    """一次 GET：连响应头一起给（SPA 外壳那一格要读 `Cache-Control`）。"""
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        headers = {"Accept": accept} if accept else {}
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        return (resp.status, resp.read().decode("utf-8"),
                {k.lower(): v for k, v in resp.getheaders()})
    finally:
        conn.close()


#: 前端源码的落点（`/` 这一格迁到 SPA 之后，有几条判据要在页面源码上读"它读什么"）。
UI_SRC = pathlib.Path(__file__).resolve().parents[1] / "ui" / "src"


def _ui_text(rel: str) -> str:
    """读一个前端源文件（不在盘上就返回空串 —— 调用方按"骨架还没落地"处置）。"""
    path = UI_SRC / rel
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _spa_root(base: str) -> str:
    """`GET /` 这一格的读数：它必须是 SPA 外壳（裁定 P1 的第一块迁移）。

    三样机器读数缺一不可（旧壳那一版在这里会全红）：
    `#app` 挂载点、CSRF 占位符已被替换（漏了注入 ⇒ 前端拿到的令牌是字面量
    `__CSRF__`，写请求会以"令牌不对"失败）、`Cache-Control: no-store`。
    """
    code, body, headers = _get_full(base, "/")
    assert code == 200, code
    assert '<div id="app">' in body, "根路径吐的不是 SPA 外壳（P1 的第一块迁移）"
    assert 'name="csrf-token"' in body, "外壳里没有 CSRF 的 meta"
    assert "__CSRF__" not in body, "外壳里的 CSRF 占位符没被替换成这一进程的令牌"
    assert headers.get("cache-control") == "no-store", headers
    return body


def _spa_run(base: str, sid: str) -> str:
    """`GET /run/{sid}` 这一格的读数：它必须是同一支 SPA 外壳（P1 的最后一块）。

    同样的三样机器读数（旧壳那一版在这里会全红：它吐的是"事件卡片 + 交付说明"，
    没有 `#app`、没有 CSRF 的 meta）。会话号合法与否都不改变这一页 ——
    "没有这一段会话"由 `/api/run/{sid}` 的三态读数说（见
    `test_run_detail_replays_events_and_report`）。
    """
    code, body, headers = _get_full(base, f"/run/{sid}")
    assert code == 200, (sid, code)
    assert '<div id="app">' in body, f"/run/{sid} 吐的不是 SPA 外壳（P1 的最后一块）"
    assert 'name="csrf-token"' in body, "外壳里没有 CSRF 的 meta"
    assert "__CSRF__" not in body, "外壳里的 CSRF 占位符没被替换成这一进程的令牌"
    assert headers.get("cache-control") == "no-store", headers
    return body


def _post(base: str, path: str, fields: dict[str, Any]) -> tuple[int, str, dict[str, str]]:
    body = urlencode(fields, doseq=True).encode("utf-8")
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        conn.request("POST", path, body=body,
                     headers={"Content-Type": "application/x-www-form-urlencoded",
                              "Content-Length": str(len(body))})
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8"), dict(resp.getheaders())
    finally:
        conn.close()


def _request(base: str, method: str, path: str) -> int:
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        conn.request(method, path)
        return conn.getresponse().status
    finally:
        conn.close()


def _abort_sse(base: str) -> int:
    """开一条 SSE 流、读满两帧，然后带 RST 关掉；返回读到的数据帧数。

    为什么用裸 socket 而不是 `http.client`：RST 要落在真正那条连接上
    （`SO_LINGER` 置 0 再 close），而 `http.client` 的 `sock` 在读响应之后不一定还挂得住；
    裸 socket 让"哪条连接、什么时候断"都是判据自己说了算。
    为什么不是优雅 `close()`：那样服务端要等下一拍心跳写失败才知道对端没了
    （实测 2 秒以上），判据就变成"等得够久碰上的"。
    """
    host, port = base.split(":")
    sock = socket.create_connection((host, int(port)), timeout=5)
    try:
        sock.sendall(b"GET /api/stream HTTP/1.1\r\nHost: x\r\n\r\n")
        sock.settimeout(3.0)
        buf = b""
        while buf.count(b"data: ") < 2:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        return buf.count(b"data: ")
    finally:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                            struct.pack("ii", 1, 0))
        except OSError:
            pass
        sock.close()


def _ask(root: pathlib.Path, *, role: str, text: str, options: list[Any] | None = None,
         sid: str = "t") -> str:
    """照 `tests/test_interaction.py` 的写法造一条待答问题（`timeout_sec=0` = 立刻超时）。"""
    out = U.ask_user(root, role=role, question=text, options=tuple(options or ()),
                     timeout_sec=0, sid=sid)
    return str(out.qid)


def _answer_events(root: pathlib.Path, sid: str = "t") -> list[dict]:
    events, _bad = SS.read_session(root, sid=sid)
    return [e for e in events if e.get("kind") == "user_answer"]


def _replies_for(root: pathlib.Path, qid: str) -> list[str]:
    """一个 qid 上所有落盘回答的文本（两种口径都读得出来）。"""
    out: list[str] = []
    for e in _answer_events(root, sid="t"):
        if str(e.get("qid")) == qid:
            out.append(W.answer_text_of(e))
    return out


def _seed_run(root: pathlib.Path, sid: str, *, role: str = "M",
              stop_reason: str = "final") -> None:
    """造一段最简会话：开场 → 一次模型调用 → 一步 → 结束（用于回放页判据）。"""
    SS.append(root, {"kind": "agent_run_start", "role": role, "task": "把口径定下来",
                     "task_id": "T-1", "depth": 0, "prompt_version": "p9"}, sid=sid)
    SS.append(root, {"kind": "llm_call", "role": role, "note": f"{role}.step0",
                     "ok": True, "model": "scripted", "tokens_in": 4, "tokens_out": 5,
                     "usd": 0.0004, "prompt_chars": 120, "text_len": 30,
                     "protocol": "json", "recorded": ""}, sid=sid)
    SS.append(root, {"kind": "agent_step", "role": role, "index": 0, "shape": "fs.write",
                     "payload": {"path": "out/review/REPORT.md"},
                     "result": {"ok": True, "bytes": 42}}, sid=sid)
    SS.append(root, {"kind": "agent_run_end", "role": role, "stop_reason": stop_reason,
                     "steps": 1, "summons": 1, "messages": 0, "final": "写完了",
                     "final_chars": 6, "spend": {"usd": 0.0004}},
               sid=sid)


def _write_report(root: pathlib.Path, text: str) -> pathlib.Path:
    path = root.joinpath(*W.REPORT_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ====================================================================== 1 正控
def test_pending_question_shows_up_on_the_global_panel(tmp_path: pathlib.Path):
    """正控（全局面板）：待答问题的机器读数在，而 `/` 这一格是 SPA 外壳。

    迁移说明（2026-10-07，裁定 P1 的第一块）：`/` 不再服务端渲染待答面板 —— 它吐的是SPA 外壳，面板由 `ui/src/pages/Home.tsx` 从 `/api/state` 渲染。
    于是这一条钉的两件事换了面、但守的是同一件事：旧：`GET /` 的 HTML 里出现 qid / 正文 / 每个选项的 label 与 description / 提交表单；
    - 新：`GET /api/state` 里出现同四样（这是面板的唯一数据来源），且 `/` 是外壳
    （`#app` + 注入过的 CSRF token）；
    - "页面真的读这些键"那一半由 `tests/test_webui_pages.py` 的
    `test_home_page_reads_the_global_pending_panel` 守着（它逐键断言 Home.tsx读了 `pending_questions` / `options` /
    `description` 等，并断言 Home 页里有"提交回答"与空态文案）；
    - "能提交回答"那一半由下面第 2 条（PRG + 落盘）与契约 A（`/answer` 在两边都有）守着。
    """
    root = tmp_path / "ws"
    root.mkdir()
    qid = _ask(root, role="M", text="交付标准是哪一档？",
               options=[{"label": "第二档 (Recommended)", "description": "可复核即可"},
                        {"label": "第一档", "description": "要形式化验证"}])
    with server(root) as base:
        body = _spa_root(base)
        assert qid not in body, "外壳里不该有盘上数据（它是一支静态页 + 一个挂载点）"
        code, raw = _get(base, "/api/state")
        assert code == 200
        state = json.loads(raw)
        pending = state["pending_questions"]
        assert [q["qid"] for q in pending] == [qid]
        assert pending[0]["role"] == "M"
        assert pending[0]["text"] == "交付标准是哪一档？", pending[0]["text"]
        # 选项是 `{label, description}` 的结构（不是被折成一串裸字符串）
        assert [o["label"] for o in pending[0]["options"]] == [
            "第二档 (Recommended)", "第一档"], pending[0]["options"]
        assert [o["description"] for o in pending[0]["options"]] == [
            "可复核即可", "要形式化验证"], pending[0]["options"]
    # 前端那一侧：面板页确实读这些键、并有一个提交按钮（源码级读数，与上面互补）
    home = _ui_text("pages/Home.tsx")
    if home:
        for token in ("pending_questions", "options", "description", "提交回答",
                      "postAnswer", "qid", "selected", "custom"):
            assert token in home, f"Home.tsx 里没有 {token}"


# ====================================================================== 2 正控
def test_post_answer_selects_redirects_and_persists(tmp_path: pathlib.Path):
    """正控（PRG + 落盘）：带 `selected` 提交 ⇒ 303 回首页；问题消失、回答落进会话。"""
    root = tmp_path / "ws"
    root.mkdir()
    qid = _ask(root, role="M", text="口径用哪个？", options=["n<=5", "全体"])
    with server(root) as base:
        code, body, headers = _post(base, "/answer",
                                    {"qid": qid, "sid": "t", "selected": "n<=5"})
        assert code == 303, (code, body[:400])
        assert headers.get("Location") == "/", headers
        # 盘上：待答清单空了、回答事件在
        assert U.pending_questions(root, sid="t") == [], "回答之后问题还在待答清单里"
        assert _replies_for(root, qid) == ["n<=5"], _answer_events(root)
        events = _answer_events(root)
        assert len(events) == 1
        assert events[0].get("by"), "回答没有记是谁答的"
        # 口径必须钉在「哪一栏」上（这条原来只查"读回来的文本对不对"，于是
        # "点了选项却被记成自己写的"那种错能照样过 —— 实测撞过一次：
        # `selected` 提交 ⇒ 事件里 `selected: []` / `custom: "n<=5"`）。
        assert list(events[0].get("selected") or []) == ["n<=5"], events[0]
        assert not str(events[0].get("custom") or "").strip(), events[0]
        # 刷新之后那条问题从待答面上消失（P1 之后待答面板的数据面是 `/api/state`；
        # `/` 是 SPA 外壳，它对谁都吐同一支静态页 —— 两件事都要读到）
        body = _spa_root(base)
        assert f'name="qid" value="{qid}"' not in body, "外壳里不该出现表单（它是挂载点）"
        code, raw = _get(base, "/api/state")
        assert code == 200
        assert json.loads(raw)["pending_questions"] == [], (
            "答过的问题还在待答清单里")


# ====================================================================== 3 正控
def test_post_answer_custom_text_comes_back(tmp_path: pathlib.Path):
    """正控（custom 优先）：带 `custom` 提交 ⇒ 回答文本按「custom 优先」读得回来。"""
    root = tmp_path / "ws"
    root.mkdir()
    qid = _ask(root, role="D", text="要不要继续？", options=["继续", "停"])
    with server(root) as base:
        code, _body, headers = _post(base, "/answer",
                                     {"qid": qid, "sid": "t",
                                      "custom": "继续，但只做一轮"})
        assert code == 303 and headers.get("Location") == "/"
    assert _replies_for(root, qid) == ["继续，但只做一轮"], _answer_events(root)
    assert U.pending_questions(root, sid="t") == []
    got = _answer_events(root)[0]
    assert list(got.get("selected") or []) == [], got          # 自写不该同时冒充"选了某项"
    assert str(got.get("custom") or "") == "继续，但只做一轮", got


# ====================================================================== 4 正控
def test_the_same_qid_in_two_sessions_does_not_cross_wire(tmp_path: pathlib.Path):
    """负控（跨会话同名 qid）：每段会话各自从 `q000001` 编号，提交必须按 `(sid, qid)` 精确匹配。

    实测撞过的那一版：待答清单只按 `qid` 索引，于是给一个「已经答过」的会话再提交，
    会因为"别的会话还有一个同号 qid"而通过存在性检查 —— 往那个会话里写下「第二条」
    回答（跨会话串味，而且 `read_replies` 会把这条假的当成真回答读给模型）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    q1 = _ask(root, role="M", text="s1 的问题", sid="s1")
    q2 = _ask(root, role="M", text="s2 的问题", sid="s2")
    assert q1 == q2 == f"q{S.format_id(1)}", (q1, q2)   # 夹具前提：两段会话确实同号
    with server(root) as base:
        # ① 答 s1：落在 s1，s2 不许被动到
        code, _b, _h = _post(base, "/answer", {"qid": q1, "sid": "s1", "custom": "给 s1 的"})
        assert code == 303, code
        assert [e.get("custom") for e in _answer_events(root, "s1")] == ["给 s1 的"]
        assert _answer_events(root, "s2") == []
        assert [q.qid for q in U.pending_questions(root, sid="s2")] == [f"q{S.format_id(1)}"]

        # ② 再给 s1 提交一次（它已经答过）⇒ 409，且 s1 不许出现第二条回答
        code, _b, _h = _post(base, "/answer", {"qid": q1, "sid": "s1", "custom": "重复提交"})
        assert code == 409, code
        assert len(_answer_events(root, "s1")) == 1, _answer_events(root, "s1")

        # ③ 答 s2 的同号问题：它自己那条还待答 ⇒ 303，且答案落在 s2
        code, _b, _h = _post(base, "/answer", {"qid": q2, "sid": "s2", "custom": "给 s2 的"})
        assert code == 303, code
        assert [e.get("custom") for e in _answer_events(root, "s2")] == ["给 s2 的"]
        assert len(_answer_events(root, "s1")) == 1, "答 s2 不许在 s1 上留痕"


def test_skip_records_an_empty_selected(tmp_path: pathlib.Path):
    """正控（跳过）：`skip=1` ⇒ 记一条空 `selected` 的回答（DSH 口径），不是「没答」。"""
    root = tmp_path / "ws"
    root.mkdir()
    qid = _ask(root, role="M", text="这一档要不要升？", options=["升", "不升"])
    with server(root) as base:
        code, _body, headers = _post(base, "/answer", {"qid": qid, "sid": "t", "skip": "1"})
        assert code == 303 and headers.get("Location") == "/"
    events = _answer_events(root)
    assert len(events) == 1, events
    got = events[0]
    # 跳过 = 空的 `selected` 「且」空的 `custom`（DSH 口径），不是「没答」。
    # 这条原来写成"两种口径任选其一"的宽松断言，等于没钉住 —— 现在只认一种：
    # 落盘必须同时有 `selected` 与 `custom` 两栏，且都为空。
    assert list(got.get("selected") or []) == [], got
    assert not str(got.get("custom") or "").strip(), got
    assert W.answer_text_of(got) == ""
    assert U.pending_questions(root, sid="t") == [], "跳过也必须让问题离开待答清单"


# ====================================================================== 5 负控
def test_unknown_qid_is_409_and_writes_nothing(tmp_path: pathlib.Path):
    """负控（失败不许折成 200）：没有这个号 ⇒ 409，且盘上一条回答事件都没有。"""
    root = tmp_path / "ws"
    root.mkdir()
    _ask(root, role="M", text="真问题", options=["A"])
    with server(root) as base:
        code, body, _headers = _post(base, "/answer",
                                     {"qid": "q9999", "sid": "t", "selected": "A"})
        assert code == 409, (code, body[:400])
        assert "没有这个号" in body
    assert _answer_events(root) == [], "409 那条路居然写了盘"


# ====================================================================== 6 负控
def test_answering_twice_is_409_and_does_not_duplicate(tmp_path: pathlib.Path):
    """负控（第二次回答）：已经答过再答 ⇒ 409，且不产生第二条回答事件。"""
    root = tmp_path / "ws"
    root.mkdir()
    qid = _ask(root, role="M", text="一次就好", options=["A", "B"])
    with server(root) as base:
        code, _b, _h = _post(base, "/answer", {"qid": qid, "sid": "t", "selected": "A"})
        assert code == 303
        code2, body2, _h2 = _post(base, "/answer", {"qid": qid, "sid": "t", "selected": "B"})
        assert code2 == 409, (code2, body2[:400])
        assert "已经答过了" in body2 or "已经被回答过" in body2, body2[:400]
    events = _answer_events(root)
    assert len(events) == 1, f"第二次提交不该落第二条回答：{events}"
    assert _replies_for(root, qid) == ["A"], "第二次提交把第一次的答案覆盖了"


# ====================================================================== 7 负控
def test_rendering_is_a_projection_not_a_cache(tmp_path: pathlib.Path, monkeypatch):
    """负控（投影而非缓存）：两次读逐字节相同；盘上新增 ⇒ 读数必须变。W5 迁移（2026-10-08，裁定 P1 的最后一块）：这一条原来读 `/run/{sid}` 的服务端渲染页（两趟 HTML 逐字节相同 +
    追加一条事件后 HTML 变）。旧壳退场后"详情面"是`GET /api/run/{sid}` 的 JSON，于是同一个意思换成三处真读盘的读数 ——每一处都还是"盘上变了，面就得跟着变"，
    而且各自比原来更具体：`/api/run/t` 两次读逐字节相同（投影，不是缓存）—— 原来断言的是渲染两次的
    HTML 相同，同一条意思；顺带钉住这份读数里那两条事件的可读内容（`task` 来自 `agent_run_start`、`last_shape` 来自 `agent_step`）；
    2. 追加一条落在轮次之外的事件（`agent_note`）⇒ `/api/state` 的 `orphans`
    里多出它、`orphan_summary.count` +1（Run 页"轮次之外的零散事件"那一栏读的就是这两栏）；而 `/api/run/t` 逐字节不动 —— 这是旧壳那条负控的加强版：旧壳会把零散事件也画进详情页，
    今天它只进那一栏（"不许被折成一趟"由`test_events_outside_a_run_never_become_a_run` 守）；
    3. 再追加一整趟 ⇒ `/api/run/t` 变了（趟数 1 → 2，起始下标递增）——
    原来"追加事件后页面变"那一条的等价物。为什么要把那只钟钉住：`/api/state` 有一栏 `generated_at`（`webui._now_iso()`），而这一条要的是"逐字节相同"。2026-10-03
    的全量里它红过一次：两次请求跨了一秒⇒ 逐字节比较失败。钉住那只钟之后，剩下的任何字节差异都只能来自盘上的数据 ——判据反而更紧，而不是更松。
    """
    monkeypatch.setattr(W, "_now_iso", lambda: "2026-10-03T00:00:00+08:00")
    root = tmp_path / "ws"
    root.mkdir()
    _seed_run(root, "t")
    _write_report(root, "# 交付说明\n\n这一趟做完了。\n")
    with server(root) as base:
        # ① 详情面是投影：两次读逐字节相同，且两条事件的可读内容都在
        c1, run1 = _get(base, "/api/run/t")
        c2, run2 = _get(base, "/api/run/t")
        assert (c1, c2) == (200, 200)
        assert run1 == run2, "同一份盘上数据两次读居然不同"
        view = json.loads(run1)
        assert view["tri"] == "computed", view
        assert view["runs"][0]["task"] == "把口径定下来", view["runs"][0]
        assert view["runs"][0]["last_shape"] == "fs.write", view["runs"][0]
        assert view["report"]["status"] == "ok", view["report"]
        assert "这一趟做完了。" in view["report"]["text"], view["report"]

        # ①b 外壳是静态的：对谁都逐字节相同（外壳里没有盘上数据）
        shell1 = _spa_root(base)
        shell2 = _spa_root(base)
        assert shell1 == shell2, "同一支外壳两次读取居然不同"

        # ② 追加一条轮次之外的事件 ⇒ 零散事件那一栏多一条（详情面的趟次不动）
        state1 = json.loads(_get(base, "/api/state")[1])
        SS.append(root, {"kind": "agent_note", "role": "M", "note": "又记了一笔"}, sid="t")
        state2 = json.loads(_get(base, "/api/state")[1])
        assert state2 != state1, "新事件落盘了，读数却没变（说明缓存了）"
        kinds1 = [(o["sid"], o["kind"]) for o in state1["orphans"]]
        kinds2 = [(o["sid"], o["kind"]) for o in state2["orphans"]]
        assert ("t", "agent_note") in kinds2, kinds2
        assert [k for k in kinds2 if k != ("t", "agent_note")] == kinds1, (kinds1, kinds2)
        assert state2["orphan_summary"]["count"] == (
            state1["orphan_summary"]["count"] + 1), state2["orphan_summary"]
        _c3, run3 = _get(base, "/api/run/t")
        assert run3 == run1, "轮次之外的事件不许改变详情面的趟次读数"

        # ③ 再追加一整趟 ⇒ 详情面变了（趟数 1 → 2）
        _seed_run(root, "t")
        _c4, run4 = _get(base, "/api/run/t")
        assert run4 != run1, "又跑了一趟，详情面却没变（说明缓存了）"
        view4 = json.loads(run4)
        assert len(view4["runs"]) == 2, view4["runs"]
        assert view4["runs"][1]["start_index"] > view4["runs"][0]["start_index"], (
            view4["runs"])
        assert view4["runs"][0]["task"] == view4["runs"][1]["task"] == "把口径定下来"

        # ④ 面板的数据面（`/api/state`）也是投影：钟钉住之后两次读逐字节相同；
        #    新问题一落盘就多一条（这一半是 A 线 P1 迁移时加的，语法一字不改地留着）
        _c5, state_raw1 = _get(base, "/api/state")
        _c6, state_raw2 = _get(base, "/api/state")
        assert state_raw1 == state_raw2, "同一份盘上数据两次读居然不同"
        qid = _ask(root, role="D", text="投影负控用的新问题")
        state3 = json.loads(_get(base, "/api/state")[1])
        assert state3 != json.loads(state_raw1), "新问题落盘了，读数却没变（说明缓存了）"
        assert qid in [q["qid"] for q in state3["pending_questions"]], (
            state3["pending_questions"])


# ====================================================================== 8 负控
def test_model_and_user_text_is_escaped(tmp_path: pathlib.Path):
    """负控（安全）：用户/模型产生的文本不许在页面里变成 HTML。W5 迁移（2026-10-08，裁定 P1 的最后一块）：旧壳退场之后，服务器自己写 HTML 的地方只剩错误页（`server._error_page`），
    盘上文本一律走 JSON。于是"转义"这件事在三处真读数上钉 —— 它跟着「攻击面」搬，而不是跟着旧代码搬：用户给的串进 HTML 的那一条活路（写路径给的 409 正文，嵌在错误页里）：
    `POST /answer` 的 `qid` 里塞 `<script>` 必须变成 `&lt;script&gt;`。原来断言的是旧壳渲染问题正文时转义，这是同一件事在新落点上的形态；
    2. 错误页的理由串也转义（静态路由那个名字是请求方给的）：`/static/<坏名字>`
    的 404 页里不许出现原样的尖括号。这是本批新加进 HTML 的用户输入面，必须一起守住（负控见下面的 `&lt;` 那一句：它证明这条断言不是恒真）；
    3. SPA 那一面：数据走 JSON、由 Preact 建成文本节点，所以机器读数是
    "前端源码里没有任何地方把字符串当 HTML 插进去"（`innerHTML` /`dangerouslySetInnerHTML` / `outerHTML` /
    `document.write` /`insertAdjacentHTML` 一个都不许出现），外加"外壳里根本没有盘上数据"、而"正文确实还在（在 JSON 里原样带着）"。

    为什么第 3 条是等价的守卫：SPA 的注入面只有"把字符串当 HTML 用"这一种写法；堵掉它，用户文本就只能以文本节点进 DOM —— 那是浏览器替我们转义。
    """
    root = tmp_path / "ws"
    root.mkdir()
    _seed_run(root, "t")
    SS.append(root, {"kind": "agent_note", "role": "M",
                     "note": '<script>alert(1)</script> 正文'}, sid="t")
    _ask(root, role="M", text='<script>alert(1)</script> 正文',
         options=[{"label": "<b>粗体</b>选项", "description": '<img src=x onerror=1>'}])
    with server(root) as base:
        # ① 写路径的 409 正文（嵌进错误页）：用户给的 qid 必须被转义
        code, body, _headers = _post(base, "/answer",
                                     {"qid": "<script>alert(1)</script>", "sid": "t",
                                      "selected": "x"})
        assert code == 409, (code, body[:400])
        assert "<script>alert(1)</script>" not in body, (
            "错误页里出现了未转义的用户文本")
        assert "&lt;script&gt;" in body, "转义后的文本不在错误页上"

        # ② 错误页的理由串同样转义（静态路由那个名字是请求方给的）
        code2, body2 = _get(base, "/static/%3Cscript%3Ealert(1)%3C%2Fscript%3E.js")
        assert code2 == 404, code2
        assert "<script>alert(1)</script>" not in body2, (
            "404 页把请求方给的名字原样写进了 HTML")
        assert "&lt;script&gt;" in body2, body2[:400]
        # 负控（反恒真）：不带尖括号的名字不会出现 `&lt;` —— 否则上面那一句
        # 可能只是"页面里到处都有 &lt;"这种恒真形态
        _c3, plain = _get(base, "/static/nope.js")
        assert "&lt;" not in plain, plain[:300]

        # ③ SPA 那一面：外壳里没有盘上文本；源码里没有"把字符串当 HTML"的写法；
        #    正文本身没有被丢掉（它在面板的 JSON 里原样带着，由前端当文本渲染）
        shell = _spa_root(base)
        assert "<script>alert(1)</script>" not in shell, "外壳里出现了盘上文本"
        _c4, state_raw = _get(base, "/api/state")
        assert "<script>alert(1)</script> 正文" in state_raw, (
            "面板的 JSON 里应当原样带着问句正文（它是数据，不是 HTML）")
        for rel, text in (("pages/Home.tsx", _ui_text("pages/Home.tsx")),
                          ("pages/Run.tsx", _ui_text("pages/Run.tsx")),
                          ("live.tsx", _ui_text("live.tsx"))):
            if not text:
                continue
            for bad in ("innerHTML", "outerHTML", "dangerouslySetInnerHTML",
                        "document.write", "insertAdjacentHTML"):
                assert bad not in text, f"{rel} 里出现了 {bad}（把字符串当 HTML 用）"


# ====================================================================== 9 负控
def test_app_css_uses_only_tokens():
    """负控（只用令牌）：`ui/src/theme/app.css` 无字面色值，且确实在令牌体系里写样式。

    W5 迁移（2026-10-08）：被检对象从旧壳内联的 `web/assets.py::APP_CSS` 换成 SPA 的组件样式 `ui/src/theme/app.css` ——
    旧壳退场后组件样式只剩这一份（`ui/index.html`里 `<link>` 引的就是它，构建时打进 `web/static/assets/`）。断言逐条等价、强度不变：原：`APP_CSS` 里不许有
    `#rrggbb` / `rgb(` / `hsl(` ⇒ 新：同一套正则查 app.css；
    - 原：至少 8 个不同的 `--dsw-alias-` 令牌 ⇒ 新：同一条（今天 17 个）；
    - 原：引用的令牌必须在 `THEME_CSS` 里定义过 ⇒ 新：同一份 `THEME_CSS`
    （它没搬走，仍是令牌的唯一真身，前端那份是它的生成物）；
    - 原：三档状态徽标 + `--ds-font-family-code` + 运动令牌要真的用上 ⇒ 新：同一条。另外加一条反真空断言：文件不在盘上时直接红，
    不许因为读成空串而静默变绿（`hexes == []` 对空串是恒真的）。
    """
    css = _ui_text("theme/app.css")
    assert css, "ui/src/theme/app.css 不在盘上 ⇒ 这条判据没有对象了（不许静默变绿）"
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", css)
    assert hexes == [], f"app.css 里有字面色值：{hexes}"
    assert not re.search(r"\b(?:rgb|rgba|hsl|hsla)\(", css), "app.css 里有 rgb()/hsl()"
    alias = set(re.findall(r"var\((--dsw-alias-[A-Za-z0-9-]+)\)", css))
    assert len(alias) >= 8, f"只用了 {len(alias)} 个 --dsw-alias- 令牌：{sorted(alias)}"
    # 令牌必须是 THEME_CSS 里真的定义过的名字（不然浏览器静默回退）
    defined = set(re.findall(r"(--[A-Za-z0-9-]+)\s*:", A.THEME_CSS))
    used = set(re.findall(r"var\((--[A-Za-z0-9-]+)\)", css))
    missing = sorted(used - defined)
    assert missing == [], f"app.css 引用了 THEME_CSS 里没定义的令牌：{missing}"
    # 三态徽标与等宽读数：这三组是「三态读数落到令牌上」的那条判据
    assert "--dsw-alias-state-success-primary" in alias
    assert "--dsw-alias-state-error-primary" in alias
    assert "--dsw-alias-state-warn-primary" in alias
    assert "--dsw-alias-label-tertiary" in alias
    assert "var(--ds-font-family-code)" in css
    assert "var(--ds-transition-duration)" in css and "var(--ds-ease-in-out)" in css


# ====================================================================== 10 正控
def test_theme_css_keeps_dsh_tokens():
    """正控（令牌是照搬的）：两层色板 + 明暗两套 + 字体/运动 + 圆角签名都在。

    这一条是「我们抄的是 DSH 的令牌体系，不是自己编了一套颜色」的判据：
    原始色板（`--dsw-static-*`）与语义别名（`--dsw-alias-*`）两层都在，
    `data-ds-dark-theme` 那一段在，选择器只从 `body` 改成了 `:root`。

    W5 迁移（2026-10-08）：末了一条原来是 `A.STYLESHEET == A.THEME_CSS + A.APP_CSS`
    （旧壳把两份文本合起来内联）。那两件随旧壳退场，今天两份文本都在前端工程里，
    于是同一件事改由 `ui/index.html` 的两个 `<link>` 钉住：两份都要被引进页面
    （少引一份 ⇒ "令牌在、组件样式不在"或反过来会被静默写进产物）。
    """
    theme = A.THEME_CSS
    assert theme.count("--dsw-static-") >= 60, "原始色板没搬全"
    assert theme.count("--dsw-alias-") >= 79, "语义别名没搬全"
    assert theme.count("data-ds-dark-theme") == 2, "明暗两套（static + alias）不齐"
    assert ":root{" in theme and ":root[data-ds-dark-theme]{" in theme
    assert "body{" not in theme, "还有没改选择器的 body{} 规则"
    assert "--ds-ease-in-out" in theme and "--ds-transition-duration" in theme
    assert "--ds-font-family-code" in theme and "--dsw-font-family" in theme
    assert "corner-shape:superellipse(1.5)" in theme, "圆角签名那段没搬"
    assert "scrollbar-width:thin" in theme
    # 组件样式与令牌是两份文本，合起来才发给浏览器
    index_html = _ui_text("../index.html")
    assert index_html, "ui/index.html 不在盘上 ⇒ 这一条没有对象了"
    assert 'href="./src/theme/generated/theme.css"' in index_html, (
        "index.html 没引令牌那一份（换皮时颜色不会变）")
    assert 'href="./src/theme/app.css"' in index_html, (
        "index.html 没引组件样式那一份（页面会没有骨架）")


# ====================================================================== 11 正控
def test_pending_list_is_never_filtered_by_session(tmp_path: pathlib.Path):
    """正控（跨会话）：两个不同 sid 各有一条待答问题 ⇒ 两条都在，各自标着会话号。"""
    root = tmp_path / "ws"
    root.mkdir()
    qa = _ask(root, role="M", text="会话甲的提问", sid="s-a")
    qb = _ask(root, role="D", text="会话乙的提问", sid="s-b")
    with server(root) as base:
        _spa_root(base)   # `/` 是 SPA 外壳；面板的数据面在下面
        code, raw = _get(base, "/api/state")
        assert code == 200
        state = json.loads(raw)
        pending = state["pending_questions"]
        assert [q["text"] for q in pending] == ["会话甲的提问", "会话乙的提问"], pending
        # 两条问题各自带自己的会话号（qid 只在会话内唯一）：
        # 排序 =（会话号，提问顺序），而 SPA 按这个顺序逐条成卡
        assert [(q["sid"], q["qid"]) for q in pending] == [
            ("s-a", qa), ("s-b", qb)], pending
    # 前端那一侧：卡片锚点必须带会话号才不撞（`id="q-<sid>-<qid>"`）
    home = _ui_text("pages/Home.tsx")
    if home:
        assert 'id={`q-${props.q.sid}-${props.q.qid}`}' in home, (
            "Home.tsx 的卡片锚点没有同时带会话号与问题号（qid 只在会话内唯一）")


# ====================================================================== 12 正控
def test_run_detail_replays_events_and_report(tmp_path: pathlib.Path):
    """正控（一趟详情）：读数与交付说明都拿得到；没有这一段会话 ⇒ 如实说"没查成"。

    W5 迁移（2026-10-08，裁定 P1 的最后一块）：这一条原来读 `/run/{sid}` 的服务端渲染页（事件卡片里出现四个 kind、步骤的形状与下标、报告原文在一个 `<pre>` 里、不存在的 sid ⇒
    404 页）。旧壳退场后同一件事分两处、逐条等价：页面入口 `/run/r1` 是 SPA 外壳（`_spa_run` 的三样机器读数 + 外壳里没有盘上数据）；
    - 详情读数是 `GET /api/run/r1` 的 JSON（`runs` / `report` / `checkpoint`）。
    "事件被读到了"原来靠 HTML 里出现 `agent_run_start` / `agent_step` 两个 kind 来钉，今天同两条事件的「可读内容」落在 `task`（来自 `agent_run_start` 的
    payload）、`last_shape` 与 `steps`（来自 `agent_step` / `agent_run_end`）上 ——钉的还是"盘上的事件真被读成了读数"；"报告原样显示在一个
    `pre` 里"那一半移到 `Run.tsx` 的源码读数（`v.report.text` 进 `class="mono pre"`）；
    - "不存在的 sid ⇒ 404"换成 SPA 的口径：页面照吐外壳（前端路由对任何 sid 都要能
    显示），否决权在数据面 —— `/api/run/nope` 的 `tri` 必须是 `unreadable`，理由里点名"会话文件不在盘上"（三态：没查成，不是"这一趟 0 步"）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    _seed_run(root, "r1")
    _write_report(root, "## 九节交付说明\n\n证据不足的地方：第 3 节。\n")
    with server(root) as base:
        shell = _spa_run(base, "r1")
        assert "九节交付说明" not in shell, "外壳里不该有盘上数据（它是一支静态页）"

        code, raw = _get(base, "/api/run/r1")
        assert code == 200, code
        view = json.loads(raw)
        assert view["tri"] == "computed", view
        assert len(view["runs"]) == 1, view["runs"]
        row = view["runs"][0]
        assert row["task"] == "把口径定下来", row         # agent_run_start 的 payload
        assert row["last_shape"] == "fs.write", row        # agent_step 的 shape
        assert (row["steps"], row["llm_calls"]) == (1, 1), row
        assert row["stop_reason"] == "final", row          # agent_run_end
        assert row["role"] == "M", row
        assert "r1" in view["path"], view["path"]
        # 交付说明原样可读（三态词表 ReportTri：ok / missing / unknown）
        assert view["report"]["status"] == "ok", view["report"]
        assert "证据不足的地方：第 3 节。" in view["report"]["text"], view["report"]

        # 列表页给得出这一趟（P1 之后"列表页"是 SPA：数据面是 `/api/state`）
        _c, raw_state = _get(base, "/api/state")
        last = json.loads(raw_state)["last_run"]
        assert last is not None and last["sid"] == "r1", last
        main_tsx = _ui_text("main.tsx")
        if main_tsx:
            assert '"/run/:sid"' in main_tsx, "SPA 没有声明 /run/:sid 这条路由"
        home_tsx = _ui_text("pages/Home.tsx")
        if home_tsx:
            assert "/run/" in home_tsx, "Home.tsx 里没有指向一趟详情的链接"
        # "报告原样显示在一块 pre 里"那一半（旧壳断言 `<pre>` 在页面上）
        run_tsx = _ui_text("pages/Run.tsx")
        if run_tsx:
            assert "v.report.text" in run_tsx, "Run.tsx 没有读交付说明的原文"
            assert 'class="mono pre"' in run_tsx, "Run.tsx 没有把原文放进 pre 里"

        # 没有这一段会话：页面照吐外壳，否决权在数据面（unreadable + 说得清理由）
        _spa_run(base, "nope")
        _c2, raw_nope = _get(base, "/api/run/nope")
        missing = json.loads(raw_nope)
        assert missing["tri"] == "unreadable", missing
        assert "会话文件不在盘上" in missing["reason"], missing["reason"]
        assert missing["runs"] == [], missing


# ====================================================================== 15 正控
def test_the_run_path_serves_the_spa_shell(tmp_path: pathlib.Path):
    """正控（P1 的最后一块迁移）：`GET /run/{sid}` 与 `/` 吐的是同一支外壳。

    为什么必须有这一条：`/` 迁走之后（2026-10-07 的第一块），`/run/{sid}` 是旧壳
    最后一面 —— 不迁它，同一个工作区里就有两套页面实现（旧壳 + SPA），
    `views.py` 也永远清不掉。三样机器读数与 `_spa_root` 逐条相同，再加一条
    "外壳里没有盘上数据"：会话号合法与否都不改变这一页。

    反向读数（路由形状没被放宽）：`/run/` 与 `..%2f` 那一类解出来带斜杠的串仍然
    404 —— 见 `test_unknown_paths_and_methods`（`{sid}` 只匹配一段路径）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    _seed_run(root, "r1")
    with server(root) as base:
        for sid in ("r1", "nope"):
            body = _spa_run(base, sid)
            assert "把口径定下来" not in body, (
                "外壳里不该有盘上数据（它是静态页 + 一个挂载点）")
        # 两个入口吐的是同一支外壳（同一份实现，不许写第二份）
        assert _spa_run(base, "r1") == _spa_root(base), (
            "/ 与 /run/{sid} 吐的外壳不是同一支（有人写第二份注入实现？）")


# ====================================================================== 13 负控
def test_events_outside_a_run_never_become_a_run(tmp_path: pathlib.Path):
    """负控（投影不造假）：轮次之外的零散事件不许被折成一趟，`last_run` 不许被顶掉。

    父在真工作区上的复现（`projects/p5-run15`）：`agent_run_end` 之后紧跟的一条`user_answer`（人刚按下「提交」写进去的那条）被当成新一轮的开始，于是页头「最近一趟」显示的是一个
    `steps=0 / llm_calls=0 / usd=null / stop_reason=""`的空壳；那个工作区里另一个会话甚至一个 `agent_run_start` 都没有，却被报成「role=A 的一趟运行」。

    三态口径：没有开始标记的事件 = 「轮次之外的零散事件」（单独一栏、写明没有开始标记），不是「一趟 0 步的运行」；整个工作区一趟都没有 ⇒ `last_run is None`，SPA 的 Run
    页写"这一段会话里一趟都没有"（那句空态文案由`tests/test_webui_pages.py` 的 `EMPTY_WORDS` 钉住）。P1 迁移（2026-10-07）：原来读的是首页 HTML 里「运行态 /
    轮次之外的零散事件」两段。`/` 改成 SPA 外壳之后，这两栏的数据面是 `/api/state`（`runs`/`last_run`与 `orphans`/`orphan_summary`），所以这里逐项改成读那份
    JSON —— 断言的内容一条没减，只是换了面。渲染那一半（零散事件单独成栏、不并进时间线）由`tests/test_webui_pages.py` 的 Run 页判据守着。
    """
    root = tmp_path / "ws"
    root.mkdir()
    # 一趟真运行（含 steps / llm_call / usd / stop_reason）
    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "真运行"}, sid="t")
    SS.append(root, {"kind": "llm_call", "role": "M", "ok": True, "usd": 0.25,
                     "tokens_in": 3, "tokens_out": 4}, sid="t")
    SS.append(root, {"kind": "agent_step", "role": "M", "index": 0, "shape": "fs.write",
                     "payload": {}, "result": {"ok": True}}, sid="t")
    SS.append(root, {"kind": "agent_run_end", "role": "M", "stop_reason": "final",
                     "steps": 1, "final": "做完了"}, sid="t")
    # 人刚提交的回答：落在轮次之外（真机里正是「按下提交」那一刻的形态）
    SS.append(root, {"kind": "user_answer", "qid": f"q{S.format_id(1)}", "answer": "第二档",
                     "by": "web"}, sid="t")
    # 另一个会话一条 `agent_run_start` 都没有：不带 --sid 的那次 CLI 调用写的台账事件
    SS.append(root, {"kind": "task_end", "role": "A", "outcome": "ok"}, sid="20261003")

    snap = W.snapshot(root)
    # 一趟（而且只有一趟）真运行
    assert len(snap["runs"]) == 1, snap["runs"]
    run = snap["runs"][0]
    assert (run["sid"], run["role"]) == ("t", "M")
    assert run["steps"] == 1 and run["llm_calls"] == 1
    assert run["usd"] == 0.25 and run["stop_reason"] == "final"
    # 最近一趟仍然是那一趟，不是空壳
    assert snap["last_run"] is run, snap["last_run"]
    assert snap["last_run"]["steps"] == 1 and snap["last_run"]["stop_reason"] == "final"
    # 尾部两条进了「轮次之外的零散事件」（按（会话号，事件序号）排序）
    assert [(o["sid"], o["kind"]) for o in snap["orphans"]] == [
        ("20261003", "task_end"), ("t", "user_answer")], snap["orphans"]
    assert snap["orphan_summary"]["count"] == 2
    groups = {g["sid"]: g for g in snap["orphan_summary"]["groups"]}
    assert groups["20261003"]["kinds"] == ["task_end"]
    assert groups["t"]["kinds"] == ["user_answer"]

    with server(root) as base:
        # P1 迁移（2026-10-07）：原来从首页 HTML 里切「运行态 / 轮次之外的零散事件」
        # 两段来读。现在这两栏的数据面是 `/api/state`（`runs` / `last_run` 与
        # `orphans` / `orphan_summary`），而"页面真的把零散事件单独成栏、不并进趟次"
        # 由 `tests/test_webui_pages.py` 的 Run 页判据守着（它断言 Run.tsx 读了
        # `orphans` 且那一栏与时间线分开）。这里钉的是那份 JSON 读数不变形。
        _c, raw = _get(base, "/api/state")
        got = json.loads(raw)
        assert len(got["runs"]) == 1, got["runs"]
        assert got["runs"][0]["sid"] == "t" and got["runs"][0]["role"] == "M"
        assert got["runs"][0]["stop_reason"] == "final", got["runs"][0]
        assert got["runs"][0]["usd"] == 0.25, got["runs"][0]
        # 那一趟的读数里不许出现空壳（本趟事件 0 条 / 0 步）
        assert got["runs"][0]["steps"] == 1 and got["runs"][0]["events_in_run"] > 0
        # 零散事件单独一栏（两条），不是"一趟 0 步的运行"
        assert [(o["sid"], o["kind"]) for o in got["orphans"]] == [
            ("20261003", "task_end"), ("t", "user_answer")], got["orphans"]
        assert got["orphan_summary"]["count"] == 2, got["orphan_summary"]
        groups = {g["sid"]: g for g in got["orphan_summary"]["groups"]}
        assert groups["20261003"]["kinds"] == ["task_end"], groups
        assert groups["t"]["kinds"] == ["user_answer"], groups
        # 详情面（P1 之后是 JSON）仍然给得出这一趟：task 来自 agent_run_start、
        # stop_reason 来自 agent_run_end（原来读的是旧壳详情页里那两个 kind 串）
        _c2, raw_detail = _get(base, "/api/run/t")
        detail = json.loads(raw_detail)
        assert detail["tri"] == "computed", detail
        assert detail["runs"][0]["task"] == "真运行", detail["runs"][0]
        assert detail["runs"][0]["stop_reason"] == "final", detail["runs"][0]
        _spa_root(base)

    # 一趟都没有的工作区 ⇒ last_run is None（SPA 的 Run 页写"一段会话里一趟都没有"，
    # 那句空态文案由 `tests/test_webui_pages.py` 的 EMPTY_WORDS 钉住）
    empty = tmp_path / "ws2"
    empty.mkdir()
    SS.append(empty, {"kind": "task_end", "role": "A", "outcome": "ok"}, sid="solo")
    snap2 = W.snapshot(empty)
    assert snap2["runs"] == []
    assert snap2["last_run"] is None, snap2["last_run"]
    assert len(snap2["orphans"]) == 1
    with server(empty) as base:
        _c, raw = _get(base, "/api/state")
        got2 = json.loads(raw)
        assert got2["last_run"] is None, got2["last_run"]
        assert got2["orphan_summary"]["count"] == 1, got2["orphan_summary"]
        assert got2["runs"] == [], got2["runs"]
        _spa_root(base)


# ====================================================================== 14 负控
def test_unknown_paths_and_methods(tmp_path: pathlib.Path):
    """负控（路由）：其余路径 ⇒ 404；非 GET/HEAD/POST ⇒ 405（不是把什么都当 200）。"""
    root = tmp_path / "ws"
    root.mkdir()
    with server(root) as base:
        assert _get(base, "/nope")[0] == 404
        assert _get(base, "/run/")[0] == 404
        assert _post(base, "/nope", {})[0] == 404
        assert _request(base, "DELETE", "/") == 405
        assert _request(base, "PUT", "/answer") == 405
        # 会话号穿越：`..` 不许被当成一个会话名
        assert _get(base, "/run/..%2F..%2Fsecret")[0] == 404


# ====================================================================== 入口接线

# ====================================================================== 16 负控
def test_a_client_that_hangs_up_leaves_no_traceback_on_stderr(
        tmp_path: pathlib.Path, monkeypatch):
    """负控（客户端中途挂断）：服务端不留未处理异常，也不影响后续请求。形态出处（W5 收工门 §8 的 stderr 读数）：那里混进过两
    行`Exception occurred during processing of request from ('127.0.0.1', …)` +`ConnectionAbortedError: [WinError 10053]`。它不影响判定，
    但那是一条假错误信号：日志里多一条"服务器出错了"，真错误就难找了，"stderr 里有没有东西"这类判据也不好写。成因在 `handle_one_request`：SSE 的响应头写着`Connection: keep-alive` ⇒
    handler 返回后这一层会再读一次请求行，读到的正是那条已被掐断的套接字。掐断怎么造（本机五种打法都实测过：SSE 读两帧后 close、SSE 读两帧后带 RST 关闭、完整 GET 后 RST、半截请求后 RST、POST 正文没收完就
    RST）：这里取"SSE 读两帧后带 RST 关闭"——它最接近门里那一档（同一条 keep-alive 的流、同一条 handler 返回后再读请求行的路径），而且 RST 让"对端没了"当场可见（实测 0.67 秒就冒出来）；优雅 close
    则要等服务端下一拍写失败才知道（实测 2 秒以上，落在等待窗口之外）——判据要的是确定复现，而不是"等得够久就碰上了"。`GET /api/stream` 在裸 socket 上读满两帧，然后 `SO_LINGER` 置 0 再 close；2.
    stderr 里不许出现 `ConnectionAbortedError` / `ConnectionResetError`，也不许出现 `socketserver` 那句
    `Exception occurred during processing of request`；3. 一次断开不许影响后续请求（紧跟着 `GET /api/state` 仍然 200）——只把日志弄干净、却把连接循环弄死，是另一种坏。
    心跳周期在这里必须显式注入（0.2 秒）：这条判据靠"下一帧写不出去"来暴露断开，用默认的 15 秒会让判据等 15 秒（同 `test_webui_sse.py` 的理由）。负控：把
    `WebHandler.handle_one_request` 的覆写去掉（换回基类那一份）⇒上面第 2 条必须红（做法见 `temp/w5_negctl_abort.py`：只在测试进程里重新绑定，不动盘上任何一个字节；实测原文见 W5 报告）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    SSE.begin_serving(heartbeat_sec=0.2)
    SSE.attach()          # 与 serve() 自己开一代时做的两件事一致（理由见 server.serve）
    with server(root) as base:
        frames = _abort_sse(base)
        assert frames >= 2, (
            f"两帧都没读满（读到 {frames}）⇒ 这条判据没落到『读着读着被掐断』上")
        # 给服务端把这次断开处理完留出时间，再读 stderr
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if "Exception occurred during processing" in err.getvalue():
                break
            time.sleep(0.05)
        time.sleep(0.2)
        out = err.getvalue()
        assert "ConnectionAbortedError" not in out, out
        assert "ConnectionResetError" not in out, out
        assert "Exception occurred during processing of request" not in out, out
        assert "Traceback (most recent call last)" not in out, out
        # 一次断开不许影响后续请求
        code, _body = _get(base, "/api/state")
        assert code == 200, code


def test_the_cli_web_subcommand_forwards_to_the_module_entry(tmp_path: pathlib.Path,
                                                            monkeypatch):
    """`agentflow web` 只是把参数翻给 `webui.run`（一条实现，两处入口）。

    为什么要单钉这一条：CLI 那条路是「用户手敲的那条」，而它的实现若另写一份，
    就会与 `python -m agentflow.webui` 那条路慢慢分家（`R003` 要防的正是"同一个公开名
    两处各有一份实现"）。这里把 `webui.run` 换成假的，看它收到的 argv 对不对。
    """
    from argparse import Namespace

    from agentflow import cli

    seen: dict[str, Any] = {}

    def fake_run(argv: Any = None) -> int:
        seen["argv"] = list(argv or [])
        return 0

    monkeypatch.setattr(W, "run", fake_run)
    ws = tmp_path / "ws"
    ws.mkdir()
    rc = cli.cmd_web(Namespace(root=str(ws), host="127.0.0.1", port=0, open=False,
                               json=True, token=""))
    assert rc == 0
    argv = seen["argv"]
    assert "--root" in argv and str(ws) in argv, argv
    assert "--json" in argv and "--port" in argv and "0" in argv, argv
    assert "--open" not in argv and "--token" not in argv, argv

    # 负控：给了 --open / --token 才带上；不给 --json 时不许塞进去
    rc = cli.cmd_web(Namespace(root=str(ws), host="0.0.0.0", port=8788, open=True,
                               json=False, token="s3cret"))
    assert rc == 0
    argv2 = seen["argv"]
    assert "--open" in argv2 and "--token" in argv2 and "s3cret" in argv2, argv2
    assert "--json" not in argv2, argv2
    assert "0.0.0.0" in argv2, argv2


def test_the_parser_has_the_web_subcommand():
    """反真空：解析器里真的有 `web` 且指向 `cmd_web`（否则上面的接线判据测的是空气）。"""
    from agentflow import cli

    parsed = cli.build_parser().parse_args(["web", "--port", "0", "--json"])
    assert parsed.func is cli.cmd_web, parsed.func
    assert parsed.port == 0 and parsed.json is True
