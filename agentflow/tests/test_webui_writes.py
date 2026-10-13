# -*- coding: utf-8 -*-
"""写面判据（W3 / 裁定 C2 · D2 · I1 · Q1）。

## 这一组守什么

| 守什么 | 用例 |
|---|---|
| 接缝：三条写入 `writes.ROUTES` + `writes.HANDLERS`，真 HTTP 走得到 | `test_the_write_endpoints_*` |
| 授权矩阵（四种拒绝 + 两种来源/令牌拒绝） | `test_the_write_face_is_off_by_default` 等 |
| 每一次写都留审计（含被拒的尝试） | `test_refused_attempts_also_leave_an_audit_row` |
| 失败不许折成 200（三态不塌） | `test_a_failed_audit_does_not_turn_into_a_clean_success` |
| 不许绕闸门（负控） | `test_the_stop_audit_follows_the_gate` · `test_the_answer_write_really_goes_through_userio` |
| `/api/submit` 不走 `admit_search_request` | `test_submit_does_not_go_through_the_admission_gate` |

## 一处口径要写清楚：`/answer` 不进授权矩阵

`draft/73` §2.5 给 `POST /answer` 的闸门栏逐字是"现状，不动"，而且
`tests/test_webui.py` 里有 21 条用例在缺省只读的服务上提交表单、要求 303/409
（`tests/test_webui.py:55` 的 `server()` 用缺省 `allow_writes=False`，
`:180`/`:282`/`:296` 三条钉着状态码）。所以 C 线只给它补审计，
不给它加 `--allow-writes` 这一层 —— 加了那 21 条会全红，而那不是本线的授权。

## 负控怎么造

每条判据的负控都用"把闸门换成桩/把中间那一步改坏"的形态，并且断言读数真的变了：
换桩之后审计里的 `result` 必须跟着变、`admission` 桩必须一次都没被调用。
少了这一条，"写路径真的经过既有闸门"就只是一句话。
"""

from __future__ import annotations

import http.client
import json
import pathlib
import threading
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlencode

import pytest

from agentflow import interactions as X
from agentflow import sessions as SS
from agentflow import settings as SET
from agentflow import stopctl as SC
from agentflow import userio as U
from agentflow import webui as W
from agentflow.store import Store
from agentflow.webui import audit, routes, writes

#: 判据自己的 CSRF 令牌（`serve(csrf_token=...)` 钉住它，于是请求头可预期）。
CSRF = "line-c-csrf-token-0123456789"
#: 一个非回环的 Origin（跨站来源那一档）。
EVIL = "http://evil.example:8080"


# ====================================================================== 夹具
@contextmanager
def _server(root: pathlib.Path, *, allow_writes: bool = True, csrf: str = CSRF,
            settings_write: bool = True) -> Iterator[str]:
    """在临时端口上起一个服务（写面开关与令牌都由判据钉住）。"""
    srv = W.serve(root, host="127.0.0.1", port=0, allow_writes=allow_writes,
                  csrf_token=csrf, settings_write=settings_write)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _post(base: str, path: str, fields: dict[str, Any] | None = None, *,
          csrf: str | None = CSRF, origin: str = "",
          headers: dict[str, str] | None = None) -> tuple[int, str, str]:
    """一次 POST：返回 `(状态码, 正文, content-type)`。"""
    body = urlencode(fields or {}, doseq=True).encode("utf-8")
    hdrs: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded",
                            "Content-Length": str(len(body))}
    if csrf is not None:
        hdrs["X-CSRF-Token"] = csrf
    if origin:
        hdrs["Origin"] = origin
    hdrs.update(headers or {})
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        conn.request("POST", path, body=body, headers=hdrs)
        resp = conn.getresponse()
        return (resp.status, resp.read().decode("utf-8", errors="replace"),
                resp.getheader("Content-Type") or "")
    finally:
        conn.close()


def _json_of(body: str) -> dict[str, Any]:
    """把回执解成字典；不是 JSON 就直接失败（写面的回执必须是 `WriteResult`）。"""
    try:
        got = json.loads(body)
    except ValueError as exc:
        raise AssertionError(f"回执不是 JSON：{body[:200]!r}（{exc}）") from exc
    assert isinstance(got, dict), got
    return got


def _events(root: pathlib.Path, sid: str = "t") -> list[dict]:
    """一段会话里的事件（写面判据只看有没有真落盘）。"""
    rows, _bad = SS.read_session(root, sid=sid)
    return rows


def _ask(root: pathlib.Path, text: str = "先做哪一档？", sid: str = "t") -> str:
    """造一条待答问题（`timeout_sec=0` ⇒ 立刻超时，不影响写面判据）。"""
    out = U.ask_user(root, role="M", question=text, options=({"label": "甲"},),
                     timeout_sec=0, sid=sid)
    return str(out.qid)


# ====================================================================== 接缝
def test_the_write_endpoints_are_registered_in_this_line_s_own_subtable() -> None:
    """正控（接缝）：三条写端点在本模块的 `ROUTES` 里，且真的进了总表。

    `draft/78 §3` 的接缝要求"加端点只改自己模块"；这条判据证明改的是本模块，
    而且 `routes.compose` 真的把它拼进了总表（不是"写了却没人看"）。
    """
    mine = {row[1]: row[2] for row in writes.ROUTES}
    for path in ("/api/stop", "/api/submit", "/api/settings", "/api/budget"):
        assert path in mine, f"writes.ROUTES 里没有 {path}：{writes.ROUTES}"
        assert mine[path] in routes.handler_names(), (path, mine[path])
        assert routes.handler_for(mine[path]) is not None, mine[path]
        assert path in routes.patterns(), f"{path} 没进总表：{routes.patterns()}"
    # `/answer` 那一行仍指向 A 线的方法（行为不许变，见模块 docstring）
    assert mine["/answer"] == "handle_answer", mine
    # 子表里不许有"登记了却进不了总表"的孤立行
    stray = [row for row in writes.ROUTES if row not in routes.ROUTES]
    assert stray == [], stray


def test_the_handlers_are_callable_from_the_subtable_lookup() -> None:
    """正控（接缝的第二半）：`routes.handler_for` 按名字取得回本模块的函数。

    这就是 `server._invoke` 走的那一条路（先找 `WebHandler` 的方法，再找子表）
    —— 名字写错时它会当场 500，而不是静默 404。
    """
    for path, name in (("/api/stop", "handle_stop"), ("/api/submit", "handle_submit"),
                       ("/api/settings", "handle_settings"), ("/api/budget", "handle_budget")):
        assert writes.HANDLERS.get(name) is not None, (path, name, sorted(writes.HANDLERS))
        assert routes.handler_for(name) is writes.HANDLERS[name], name


# ====================================================================== 授权矩阵
def test_the_write_face_is_off_by_default(tmp_path: pathlib.Path) -> None:
    """拒绝档①：没开写面 ⇒ 403 + `WriteResult`（不是 200，也不是 HTML）。

    这一条是裁定 C2 的机器读数：缺省只读，"随手一点就叫停"挡在显式意图后面。
    """
    root = _mk(tmp_path)
    with _server(root, allow_writes=False) as base:
        for path, fields in (("/api/stop", {"reason": "user", "confirm": "1"}),
                             ("/api/submit", {"topic": "t", "mode": "topical",
                                              "confirm": "1"})):
            code, body, ctype = _post(base, path, fields)
            assert code == 403, (path, code, body[:200])
            assert ctype.startswith("application/json"), ctype
            got = _json_of(body)
            assert got["ok"] is False and got["tri"] == "not_applicable", got
            assert "写面没开" in got["reason"], got["reason"]
    assert SC.read_stop(root) is None, "没开写面却写下了停机开关"
    assert Store(root).rows("search_requests") == [], "没开写面却入了队"


def test_a_bad_or_missing_csrf_token_is_refused(tmp_path: pathlib.Path) -> None:
    """拒绝档②：CSRF 不对/没带 ⇒ 403（写请求必须带 `X-CSRF-Token`）。"""
    root = _mk(tmp_path)
    with _server(root) as base:
        code, body, _ct = _post(base, "/api/stop",
                                {"reason": "user", "confirm": "1"}, csrf=None)
        assert code == 403 and "CSRF" in _json_of(body)["reason"], (code, body[:200])
        code2, body2, _ct2 = _post(base, "/api/stop",
                                   {"reason": "user", "confirm": "1"}, csrf="wrong-token")
        assert code2 == 403 and "CSRF" in _json_of(body2)["reason"], (code2, body2[:200])
    assert SC.read_stop(root) is None


def test_a_cross_site_origin_is_refused(tmp_path: pathlib.Path) -> None:
    """拒绝档③：非回环来源 ⇒ 403（跨站来源那一档）。"""
    root = _mk(tmp_path)
    with _server(root) as base:
        code, body, _ct = _post(base, "/api/stop", {"reason": "user", "confirm": "1"},
                                origin=EVIL)
        assert code == 403, (code, body[:200])
        reason = _json_of(body)["reason"]
        assert "Origin" in reason and "回环" in reason, reason
    assert SC.read_stop(root) is None


def test_missing_confirmation_is_400_and_writes_nothing(tmp_path: pathlib.Path) -> None:
    """拒绝档④：开了写面但缺 `confirm=1` ⇒ 400，盘上一个字节都不动。

    为什么是 400 而不是 403：这一档不是"没权限"，是"请求少带了一次确认"
    （`draft/75` §1.1 第 8/9/10 行的请求字段栏逐字有 `confirm=1`）。
    """
    root = _mk(tmp_path)
    with _server(root) as base:
        for path, fields in (("/api/stop", {"reason": "user"}),
                             ("/api/submit", {"topic": "t", "mode": "topical"})):
            code, body, _ct = _post(base, path, fields)
            assert code == 400, (path, code, body[:200])
            got = _json_of(body)
            assert got["ok"] is False and got["tri"] == "not_applicable", got
            assert "confirm=1" in got["reason"], got["reason"]
    assert SC.read_stop(root) is None
    assert Store(root).rows("search_requests") == []


def test_an_unknown_api_path_is_a_json_404_and_never_html(tmp_path: pathlib.Path) -> None:
    """拒绝档⑤（裁定 Q1）：未知 `/api/*` ⇒ JSON 404，绝不吐 HTML。"""
    root = _mk(tmp_path)
    with _server(root) as base:
        code, body, ctype = _post(base, "/api/nope", {"x": "1"})
        assert code == 404, (code, body[:200])
        assert ctype.startswith("application/json"), ctype
        assert "<html" not in body.lower(), body[:200]
        assert "没有这个端点" in _json_of(body)["reason"], body[:200]
        # 非 `/api/*` 的未知 POST 仍走 A 线的页面 404（两条口径分得开）
        code2, body2, ctype2 = _post(base, "/nope", {"x": "1"})
        assert code2 == 404 and "html" in ctype2.lower(), (code2, ctype2)


# ====================================================================== /api/stop
def test_stop_writes_the_switch_and_leaves_one_audit_row(tmp_path: pathlib.Path) -> None:
    """正控（/api/stop）：开写面 + 确认 ⇒ 200、开关落盘、台账多一行。"""
    root = _mk(tmp_path)
    with _server(root) as base:
        code, body, _ct = _post(base, "/api/stop",
                                {"reason": "user", "confirm": "1"})
    assert code == 200, (code, body[:300])
    got = _json_of(body)
    assert got["ok"] is True and got["tri"] == "computed", got
    assert got["extra"]["outcome"] == "created", got["extra"]
    assert got["id"] and pathlib.Path(got["id"]).name == SC.STOP_FILE_NAME, got["id"]
    payload = SC.read_stop(root)
    assert payload is not None and payload["reason"] == "user" and payload["by"] == "web"
    rows = audit.read_actions(root)
    assert len(rows) == 1, rows
    assert rows[0]["endpoint"] == "/api/stop" and rows[0]["ok"] is True, rows[0]
    assert rows[0]["source"].startswith("127.0.0.1"), rows[0]["source"]


def test_stop_is_idempotent_and_says_nothing_changed(tmp_path: pathlib.Path) -> None:
    """正控（幂等那一档不许折成一句"停好了"）：第二次叫停 ⇒ `existing` 且理由说清。"""
    root = _mk(tmp_path)
    with _server(root) as base:
        _post(base, "/api/stop", {"reason": "first", "confirm": "1"})
        code, body, _ct = _post(base, "/api/stop", {"reason": "second", "confirm": "1"})
    got = _json_of(body)
    assert code == 200 and got["extra"]["outcome"] == "existing", got
    assert "没有改动它" in got["reason"], got["reason"]
    assert SC.read_stop(root)["reason"] == "first", "第二次叫停改掉了第一次的理由"


def test_force_goes_through_kill_registered(tmp_path: pathlib.Path) -> None:
    """正控（force 那一档走既有闸门）：`force=1` ⇒ 调到 `stopctl.kill_registered`。"""
    root = _mk(tmp_path)
    seen: list[str] = []
    original = SC.kill_registered

    def _spy(root_arg, **kw):  # noqa: ANN001 - 与 stopctl.kill_registered 同形
        seen.append(str(root_arg))
        return {"requested": [], "results": [], "killed": 0, "kept": [], "failed": [],
                "excluded": None}

    SC.kill_registered = _spy
    try:
        with _server(root) as base:
            code, body, _ct = _post(base, "/api/stop",
                                    {"reason": "user", "confirm": "1", "force": "1"})
    finally:
        SC.kill_registered = original
    got = _json_of(body)
    assert code == 200 and got["extra"]["force"] is True, got
    assert seen == [str(root)], seen
    assert got["extra"]["killed"]["killed"] == 0, got["extra"]["killed"]
    assert SC.read_stop(root)["force"] is True, SC.read_stop(root)


def test_the_stop_audit_follows_the_gate(tmp_path: pathlib.Path) -> None:
    """负控（不许绕闸门）：把闸门换成桩 ⇒ 审计里的 `result` 必须跟着变。

    这是 `draft/74` §4 点名的负控形态。为什么它能证明"真的经过闸门"：
    桩返回的结局与真实实现不同（`existing` vs `created`），而回执与台账都照实变；
    若写面自己造一份结局，换桩就不会有任何变化。
    """
    root = _mk(tmp_path)
    original = SC.request_stop_detail

    def _stub(root_arg, **kw):  # noqa: ANN001
        return ({"reason": kw.get("reason"), "by": kw.get("by"), "force": False,
                 "at": "", "sid": "", "path": str(SC.stop_path(root_arg))}, "existing")

    SC.request_stop_detail = _stub
    try:
        with _server(root) as base:
            code, body, _ct = _post(base, "/api/stop",
                                    {"reason": "user", "confirm": "1"})
    finally:
        SC.request_stop_detail = original
    got = _json_of(body)
    assert code == 200 and got["extra"]["outcome"] == "existing", got
    assert "没有改动它" in got["reason"], got["reason"]
    assert audit.read_actions(root)[0]["result"] == got["reason"], audit.read_actions(root)[0]
    assert SC.read_stop(root) is None, "桩没写开关，盘上却出现了一把"


# ====================================================================== /api/submit
def test_submit_enqueues_one_row_with_the_shared_id_allocator(tmp_path: pathlib.Path) -> None:
    """正控（/api/submit）：入队一行、号来自 `next_prefixed_id`、台账留档。"""
    root = _mk(tmp_path)
    with _server(root) as base:
        code, body, _ct = _post(base, "/api/submit",
                                {"topic": " 拓扑度量的紧性 ", "mode": "topical",
                                 "content": "找 2020 年后的结果", "confirm": "1",
                                 "providers": ["arxiv", "openalex"]})
    got = _json_of(body)
    assert code == 200 and got["ok"] is True, (code, got)
    assert got["id"] == "r-0001", got["id"]
    rows = Store(root).rows("search_requests")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["request_id"] == "r-0001" and row["mode"] == "topical", row
    assert row["topic"] == "拓扑度量的紧性", row["topic"]
    assert row["providers"] == ["arxiv", "openalex"], row["providers"]
    assert row["submitted_by"] == "web", row["submitted_by"]
    assert [r["endpoint"] for r in audit.read_actions(root)] == ["/api/submit"], audit.read_actions(root)


def test_submit_uses_the_real_id_allocator_not_a_second_counter(
        tmp_path: pathlib.Path) -> None:
    """负控（取号只有一份实现）：把 `next_prefixed_id` 换桩 ⇒ 号必须跟着变。

    这就是"ID 分配器只有一处"那条纪律的机器读数：换桩之后行里的号变了，
    说明写面没有自己数一遍。
    """
    root = _mk(tmp_path)
    original = X.next_prefixed_id
    X.next_prefixed_id = lambda rows, field, prefix: "r-0042"      # noqa: ARG005
    try:
        with _server(root) as base:
            code, body, _ct = _post(base, "/api/submit",
                                    {"topic": "t", "mode": "broad", "confirm": "1"})
    finally:
        X.next_prefixed_id = original
    assert code == 200, (code, body[:200])
    assert _json_of(body)["id"] == "r-0042", _json_of(body)["id"]
    assert Store(root).rows("search_requests")[0]["request_id"] == "r-0042"


def test_submit_does_not_go_through_the_admission_gate(tmp_path: pathlib.Path) -> None:
    """负控（这条曾经写错过）：`/api/submit` 不走 `admit_search_request`。

    `draft/73` §2.5 的更正：I7 的准入闸门在"A 领跑那一刻"，不在"入队这一刻"。
    所以把准入闸门换成"永远拒"之后，入队照样成功，而且它一次都没被调用。
    """
    root = _mk(tmp_path)
    calls: list[Any] = []
    original = X.admit_search_request

    def _deny(*a, **kw):  # noqa: ANN002, ANN003
        calls.append((a, kw))
        return {"admitted": False, "checked": True, "reason": "永远拒"}

    X.admit_search_request = _deny
    try:
        with _server(root) as base:
            code, body, _ct = _post(base, "/api/submit",
                                    {"topic": "t", "mode": "topical", "confirm": "1"})
    finally:
        X.admit_search_request = original
    assert code == 200, (code, body[:300])
    assert calls == [], f"入队这条路不该碰准入闸门，却被调了 {len(calls)} 次"
    assert len(Store(root).rows("search_requests")) == 1


def test_submit_rejects_bad_input_without_writing_anything(tmp_path: pathlib.Path) -> None:
    """负控（失败不许折成 200）：非法 mode ⇒ 400 且整批不写。"""
    root = _mk(tmp_path)
    with _server(root) as base:
        code, body, _ct = _post(base, "/api/submit",
                                {"topic": "t", "mode": "不存在的模式", "confirm": "1"})
        assert code == 400, (code, body[:300])
        got = _json_of(body)
        assert got["ok"] is False and got["tri"] == "not_applicable", got
        assert "整批未写入" in got["reason"], got["reason"]
        code2, _b2, _c2 = _post(base, "/api/submit",
                                {"topic": "   ", "mode": "topical", "confirm": "1"})
        assert code2 == 400, code2
    assert Store(root).rows("search_requests") == [], "被拒的提交居然落了盘"


# ====================================================================== /api/budget
def test_the_budget_endpoint_appends_and_the_next_gate_sees_it(tmp_path: pathlib.Path) -> None:
    """正控（/api/budget）：追加一笔落盘，而且下一个闸门就现读到新上限。

    这一条钉的是业主那句"用户可追加预算"的机器形态：网页上点一下 ⇒ 落进
    `<工作区>/budget.json` ⇒ `budget.limit_usd` 立刻变（不需要重启、不需要重跑）。
    只判"回执 ok"是不够的 —— 回执 ok 而闸门读不到，那句话就是一句空话。
    """
    from agentflow import budget as B

    root = _mk(tmp_path)
    with _server(root) as base:
        first, body1, _ct = _post(base, "/api/budget",
                                  {"action": "set", "usd": "2", "confirm": "1", "by": "web"})
        assert first == 200, (first, body1[:300])
        code, body, ctype = _post(base, "/api/budget",
                                  {"action": "add", "usd": "1.5", "note": "让它跑完",
                                   "confirm": "1"})
    got = _json_of(body)
    assert code == 200 and got["ok"] is True, (code, got)
    assert ctype.startswith("application/json"), ctype
    assert got["tri"] == "computed", got
    assert got["extra"]["total_usd"] == 3.5, got["extra"]
    assert got["extra"]["entry"]["note"] == "让它跑完", got["extra"]
    snap = B.reading(root, spent_usd=0.0)
    assert snap["total_usd"] == 3.5, snap
    assert [a["kind"] for a in snap["added"]] == ["set", "add"], snap["added"]
    assert B.limit_usd(root, fallback=None) == 3.5, "闸门那一口现读不到新上限 ⇒ 追加是空话"


def test_the_budget_endpoint_refuses_without_writes_or_confirmation(
        tmp_path: pathlib.Path) -> None:
    """拒绝档：没开写面 ⇒ 403；缺 `confirm=1` / `action` 不认 / `usd` 非数 ⇒ 400 且零写入。"""
    from agentflow import budget as B

    root = _mk(tmp_path)
    with _server(root, allow_writes=False) as base:
        code, body, _ct = _post(base, "/api/budget",
                                {"action": "add", "usd": "1", "confirm": "1"})
    assert code == 403 and _json_of(body)["ok"] is False, (code, body[:200])
    with _server(root) as base:
        for fields, why in (
            ({"action": "add", "usd": "1"}, "缺 confirm"),
            ({"action": "add", "usd": "1", "confirm": "1", "action": "eat"}, "不认的 action"),
            ({"action": "add", "usd": "abc", "confirm": "1"}, "usd 非数"),
            ({"action": "add", "confirm": "1"}, "usd 空"),
        ):
            code, body, _ct = _post(base, "/api/budget", fields)
            assert code == 400, (why, code, body[:200])
            assert _json_of(body)["ok"] is False, (why, body[:200])
    assert not (root / B.REGISTER_NAME).exists(), "被拒的那几次不许在盘上留下寄存器"
    # 审计照旧：每一次尝试（含被拒的）都留一行
    rows = audit.read_actions(root)
    assert len([r for r in rows if r.get("endpoint") == "/api/budget"]) >= 5, rows


# ====================================================================== /answer
def test_answer_keeps_its_old_status_codes_and_now_leaves_an_audit_row(
        tmp_path: pathlib.Path) -> None:
    """正控（既有写路径 + 新审计）：303/409 一个字不改，但每一次都留一行台账。

    为什么 `/answer` 不走授权矩阵：见模块 docstring（`draft/73` §2.5 的"现状，不动"
    + `tests/test_webui.py` 那 21 条）。
    """
    root = _mk(tmp_path)
    qid = _ask(root)
    with _server(root, allow_writes=False) as base:
        code, _body, _ctype = _post(base, "/answer", {"qid": qid, "sid": "t",
                                                      "selected": "甲"}, csrf=None)
        assert code == 303, code
        code2, _b2, _h2 = _post(base, "/answer", {"qid": qid, "sid": "t",
                                                  "selected": "甲"}, csrf=None)
        assert code2 == 409, code2
    answered = [e for e in _events(root) if e.get("kind") == "user_answer"]
    assert len(answered) == 1 and answered[0]["by"] == "web", answered
    rows = audit.read_actions(root)
    assert [r["endpoint"] for r in rows] == ["/answer", "/answer"], rows
    assert [r["http"] for r in rows] == [303, 409], rows
    assert [r["ok"] for r in rows] == [True, False], rows


def test_the_answer_write_really_goes_through_userio(tmp_path: pathlib.Path) -> None:
    """负控（不许绕闸门）：`/answer` 的落盘必须经过 `userio.answer_question`。

    换桩之后（a）桩必须被调到、参数逐项对上；（b）桩报错时状态码必须变成 500。
    若写面自己拼一份事件落盘，换桩不会有任何变化 —— 这条负控就是为了让它有变化。
    """
    root = _mk(tmp_path)
    qid = _ask(root)
    seen: list[dict[str, Any]] = []
    original = U.answer_question

    def _ok(session_root, **kw):  # noqa: ANN001
        seen.append({"root": str(session_root), **kw})
        return ""

    U.answer_question = _ok
    try:
        with _server(root) as base:
            code, _body, _h = _post(base, "/answer",
                                    {"qid": qid, "sid": "t", "custom": "走桩"})
    finally:
        U.answer_question = original
    assert code == 303, code
    assert seen and seen[0]["qid"] == qid and seen[0]["custom"] == "走桩", seen
    assert seen[0]["by"] == "web" and seen[0]["sid"] == "t", seen
    assert [e for e in _events(root) if e.get("kind") == "user_answer"] == [], \
        "走了桩却还有真事件落盘（说明另有一份写路径）"

    # 闸门报错 ⇒ 500（不是 200、不是 303）
    U.answer_question = lambda *a, **kw: "落盘失败（桩）"      # noqa: ARG005
    try:
        with _server(root) as base:
            code2, body2, _h2 = _post(base, "/answer",
                                      {"qid": qid, "sid": "t", "custom": "x"})
    finally:
        U.answer_question = original
    assert code2 == 500 and "没有落地" in body2, (code2, body2[:200])


# ====================================================================== 审计
def test_refused_attempts_also_leave_an_audit_row(tmp_path: pathlib.Path) -> None:
    """正控（D2）：被拒的尝试也留档 —— 审计要能回答"有没有人试过"。"""
    root = _mk(tmp_path)
    with _server(root, allow_writes=False) as base:
        _post(base, "/api/stop", {"reason": "user", "confirm": "1"})
        _post(base, "/api/stop", {"reason": "user", "confirm": "1"})
    rows = audit.read_actions(root)
    assert len(rows) == 2, rows
    assert all(r["ok"] is False and r["http"] == 403 for r in rows), rows
    assert all("写面没开" in r["result"] for r in rows), rows


def _secret_problems(blob: str, secret: str) -> list[str]:
    """一个文本里有没有出现真 key（台账与回执两侧共用同一把尺子）。

    与 `tests/test_settings.py::_key_echo_problems` 是同一族的纯函数：判据要能在
    "喂一份改坏了的文本"时当场红，而不是只在正控上亮绿。
    """
    return [f"真 key 出现在文本里（{blob.count(secret)} 处）"] if secret in blob else []


def test_the_audit_row_has_the_seven_fields_and_redacts_secrets(
        tmp_path: pathlib.Path) -> None:
    """正控（台账形状 + 脱敏）：七个字段都在；含 key 的键名一律 `***`。

    负控在同一支里：把脱敏后的那一行按原样喂给尺子 ⇒ 不许报；把值换回真 key
    ⇒ 尺子必须报（否则"脱敏"这句话没有机器读数）。
    """
    secret = "SENTINEL-not-a-real-key"
    root = _mk(tmp_path)
    row, problem = audit.record_action(root, endpoint="/api/settings", source="127.0.0.1",
                                params={"model": {"api_key": secret,
                                                  "base_url": "https://x"},
                                        "toolchain.lean_bin": "/usr/bin/lean"},
                                result="written", tri="computed", ok=True, http=200)
    assert problem == "", problem
    for field in ("at", "kind", "endpoint", "source", "params", "params_sha256",
                  "result", "tri", "ok", "http"):
        assert field in row, (field, row)
    blob = json.dumps(row, ensure_ascii=False, sort_keys=True)
    assert row["params"]["model"]["api_key"] == audit.REDACTED, row["params"]
    assert _secret_problems(blob, secret) == [], blob
    assert row["params"]["toolchain.lean_bin"] == "/usr/bin/lean", row["params"]
    # sha256 是可比的：同一份摘要 ⇒ 同一个号；换一个字符 ⇒ 变
    assert row["params_sha256"] == audit.digest_of(row["params"]), row
    assert audit.digest_of({"a": "1"}) != audit.digest_of({"a": "2"})
    # 负控：把真 key 放回那一行 ⇒ 尺子必须报
    doctored = json.dumps(dict(row, params={"model": {"api_key": secret}}),
                          ensure_ascii=False, sort_keys=True)
    assert _secret_problems(doctored, secret), "把真 key 抄进台账，尺子却没响"
    # 负控（脱敏这一层本身）：绕过 summarize 的值 ⇒ 也该被尺子抓住
    bypass = json.dumps(audit.summarize({"model": {"api_key": secret}}),
                        ensure_ascii=False)
    assert _secret_problems(bypass, secret) == [], bypass


def test_a_failed_audit_does_not_turn_into_a_clean_success(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（三态不许塌成二态）：台账落不下 ⇒ 回执必须说出口，且不许冒充成功。

    做法：把 `audit.record_action` 换成"总是失败"的桩。写本身成功了（`ok` 仍是 `true`），
    但 `extra.audit.tri` 必须是 `unreadable` 并带上原因 —— 少了这一点，
    "写成功了但没审计上"就会静默地长得和"一切都好"一样。
    """
    root = _mk(tmp_path)
    original = audit.record_action
    monkeypatch.setattr(audit, "record_action",
                        lambda *a, **kw: ({"params_sha256": ""}, "OSError: 桩"))
    with _server(root) as base:
        code, body, _ct = _post(base, "/api/stop", {"reason": "user", "confirm": "1"})
    got = _json_of(body)
    assert code == 200 and got["ok"] is True, got
    assert got["extra"]["audit"]["tri"] == "unreadable", got["extra"]["audit"]
    assert "桩" in got["extra"]["audit"]["problem"], got["extra"]["audit"]
    # 撤回桩 ⇒ 同一条判据恢复绿（"红前绿后"）
    monkeypatch.setattr(audit, "record_action", original)
    with _server(root) as base:
        code2, body2, _ct2 = _post(base, "/api/stop", {"reason": "user", "confirm": "1"})
    got2 = _json_of(body2)
    assert code2 == 200 and got2["extra"]["audit"]["tri"] == "computed", got2


def test_the_ledger_path_is_under_the_workspace_root(tmp_path: pathlib.Path) -> None:
    """正控（D2 的落点）：台账就是 `<工作区>/web-actions.jsonl`（不是子目录）。"""
    root = _mk(tmp_path)
    assert audit.actions_path(root) == root / "web-actions.jsonl", audit.actions_path(root)
    ledger = audit.read_actions_state(root)
    assert ledger["tri"] == "computed" and ledger["rows"] == [], ledger


#: 入库的那份样例（裁定 D2 要"真跑出来的一行"，不是手写的想象行）。
EXAMPLE = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow" / \
    "web-actions.example.jsonl"


def test_the_committed_example_row_is_a_real_row_from_the_writer() -> None:
    """正控（样例必须是真的）：入库样例的 `params_sha256` 与它自己的 `params` 对上。

    这一条为什么能证明"不是手写的"：`params_sha256` 是
    `json.dumps(summarize(params), sort_keys=True, separators=(",", ":"))` 的摘要 ——
    手写一行时那一格必然对不上（或者得先把摘要算法抄一遍，那就等于真跑了一遍）。
    它同时钉住字段名：少一个字段、改一个名字，这里当场红。
    """
    assert EXAMPLE.is_file(), f"样例不在盘上：{EXAMPLE}"
    lines = [ln for ln in EXAMPLE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1, f"样例应当只有一行，实得 {len(lines)} 行"
    row = json.loads(lines[0])
    for field in ("at", "kind", "endpoint", "source", "params", "params_sha256",
                  "result", "tri", "ok", "http"):
        assert field in row, (field, row)
    assert row["kind"] == audit.KIND, row
    assert row["ok"] is True and row["http"] == 200, row
    assert row["endpoint"] in ("/api/stop", "/api/submit", "/api/settings"), row
    recomputed = audit.digest_of(row["params"])
    assert recomputed == row["params_sha256"], (
        f"样例的摘要对不上（{recomputed} != {row['params_sha256']}）⇒ "
        "它不是写入口真跑出来的那一行，或者字段被改过")
    # 负控：把摘要那一格改一个字符 ⇒ 尺子必须报
    assert audit.digest_of({"confirm": "改过"}) != row["params_sha256"]


# ====================================================================== 设置端点
def test_the_settings_endpoint_reports_the_settings_tri_and_never_the_key(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（/api/settings）：写入成功、三段回显、`model.api_key` 恒 `***`。

    设置文件是机器级的，所以判据必须钉住它写到哪：`AGENTFLOW_SETTINGS` 指到
    `tmp_path` 下的那份，本机的真设置一个字节都不许动。
    """
    root = _mk(tmp_path)
    target = tmp_path / "settings.json"
    monkeypatch.setenv(SET.ENV_SETTINGS, str(target))
    with _server(root) as base:
        code, body, _ct = _post(base, "/api/settings",
                                {"toolchain.lean_bin": "/opt/lean",
                                 "model.api_key": "SENTINEL-not-a-real-key",
                                 "model.base_url": "https://example.invalid/v1",
                                 "confirm": "1"})
    got = _json_of(body)
    assert code == 200 and got["ok"] is True, (code, got)
    assert got["extra"]["settings_tri"] == "written", got["extra"]
    assert got["tri"] == "computed", got["tri"]
    assert got["extra"]["values"]["model"]["api_key"] == SET.MASKED_KEY, got["extra"]
    assert "SENTINEL-not-a-real-key" not in body, body
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["model"]["api_key"] == "SENTINEL-not-a-real-key", on_disk
    assert on_disk["toolchain"]["lean_bin"] == "/opt/lean", on_disk
    # 台账里也不许出现真 key
    assert "SENTINEL-not-a-real-key" not in json.dumps(audit.read_actions(root), ensure_ascii=False)


def test_the_settings_endpoint_honours_the_no_settings_write_switch(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """拒绝档（裁定 E1 的第 4 层）：`--no-settings-write` ⇒ 403，文件不动。"""
    root = _mk(tmp_path)
    target = tmp_path / "settings.json"
    monkeypatch.setenv(SET.ENV_SETTINGS, str(target))
    with _server(root, settings_write=False) as base:
        code, body, _ct = _post(base, "/api/settings",
                                {"toolchain.lean_bin": "/opt/lean", "confirm": "1"})
    got = _json_of(body)
    assert code == 403 and "no-settings-write" in got["reason"], (code, got)
    assert not target.exists(), target


# ====================================================================== 小件
def _mk(tmp_path: pathlib.Path) -> pathlib.Path:
    """造一个最小工作区（写面判据不需要更多数据）。"""
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    return root
