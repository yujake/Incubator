# -*- coding: utf-8 -*-
"""用户端 Web 界面：正控与负控（离线，只连本机临时端口的临时服务）。

## 这一组守什么

`docs/USER-END-DSH-STYLE.md` §3.3 抄来的三条纪律，每条都要有机器可查的判据：

1. 「待回答的东西必须全局可达」：面板不按会话过滤（跨会话正控），
   每条问题要能看到会话号、问题号、谁在问、问了多久、正文、以及每个选项的
   label 与 description（选项是 `{label, description}` 而不是裸字符串）；
2. 「状态一律从盘上派生」（状态不进组件 state）：同一份盘上数据渲染两次逐字节
   相同（投影，不是缓存），中间往会话里追加一条事件后再渲染 ⇒ 内容必须变；
3. 「写回答的失败不许折成 200」：qid 不在待答清单 ⇒ 409（分「已经答过了」与
   「没有这个号」两档说清），成功 ⇒ 303 PRG（刷新不重复提交）；
   跳过 = 空的 `selected`（DSH 口径），不是「没答」。

另外两条是本项目的纪律，不是 DSH 的：

4. 「用户与模型产生的文本一律转义」（问题正文里塞 `<script>` 必须变 `&lt;script&gt;`）；
5. 「只用令牌」（`APP_CSS` 里不许有字面色值，且必须真的是在令牌体系里写样式）。

## 口径兼容（与并行的 `userio` 改造）

回答事件有两种口径：新的 `{"qid","selected":[...],"custom":"...","by","late"}`，
以及旧的 `{"qid","answer","by","late"}`。本文件一律用
:func:`agentflow.webui.answer_text_of` 读回答文本（`custom` 非空取它，
否则 `"、".join(selected)`，否则退回 `answer`），于是两种口径下判据都成立。

## 为什么不起长期服务

每个用例用 `port=0` 起一个临时端口上的服务，`finally` 里 `shutdown()` +
`server_close()`。不联网（只连本机 `127.0.0.1`），不写任何全局状态。
"""
from __future__ import annotations

import http.client
import json
import pathlib
import re
import threading
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlencode

import pytest

from agentflow import sessions as SS
from agentflow import userio as U
from agentflow import webui as W
from agentflow.web import assets as A


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
    """正控（全局面板）：待答问题的问题号、正文、每个选项的 label 与 description 都在。

    这一条同时钉住两件事：提问真的进了「人能看见的那个面」，
    以及选项是 `{label, description}` 的结构（不是被折成一串裸字符串）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    qid = _ask(root, role="M", text="交付标准是哪一档？",
               options=[{"label": "第二档 (Recommended)", "description": "可复核即可"},
                        {"label": "第一档", "description": "要形式化验证"}])
    with server(root) as base:
        code, body = _get(base, "/")
        assert code == 200, code
        assert qid in body, "待答问题的问题号没出现在页面上"
        assert "交付标准是哪一档？" in body
        assert "第二档 (Recommended)" in body, "选了推荐项，label 必须原样显示"
        assert "可复核即可" in body, "选项的 description 没渲染"
        assert "第一档" in body and "要形式化验证" in body
        assert "提交回答" in body and "跳过此问题" in body, "没有提交表单"
        assert 'method="post"' in body and 'action="/answer"' in body
        assert f'name="qid" value="{qid}"' in body
        code, raw = _get(base, "/api/state")
        assert code == 200
        state = json.loads(raw)
        assert [q["qid"] for q in state["pending_questions"]] == [qid]
        assert state["pending_questions"][0]["options"][0]["label"] == "第二档 (Recommended)"
        assert state["pending_questions"][0]["role"] == "M"


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
        # 刷新之后那条问题从页面上消失
        code, body = _get(base, "/")
        assert code == 200
        assert f'name="qid" value="{qid}"' not in body, "答过的表单还在页面上"
        assert "没有待回答" in body
        code, raw = _get(base, "/api/state")
        assert json.loads(raw)["pending_questions"] == []


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
    """负控（跨会话同名 qid）：每段会话各自从 `q0001` 编号，提交必须按 `(sid, qid)` 精确匹配。

    实测撞过的那一版：待答清单只按 `qid` 索引，于是给一个「已经答过」的会话再提交，
    会因为"别的会话还有一个 q0001"而通过存在性检查 —— 往那个会话里写下「第二条」
    回答（跨会话串味，而且 `read_replies` 会把这条假的当成真回答读给模型）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    q1 = _ask(root, role="M", text="s1 的问题", sid="s1")
    q2 = _ask(root, role="M", text="s2 的问题", sid="s2")
    assert q1 == q2 == "q0001", (q1, q2)          # 夹具前提：两段会话确实同号
    with server(root) as base:
        # ① 答 s1：落在 s1，s2 不许被动到
        code, _b, _h = _post(base, "/answer", {"qid": q1, "sid": "s1", "custom": "给 s1 的"})
        assert code == 303, code
        assert [e.get("custom") for e in _answer_events(root, "s1")] == ["给 s1 的"]
        assert _answer_events(root, "s2") == []
        assert [q.qid for q in U.pending_questions(root, sid="s2")] == ["q0001"]

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
def test_rendering_is_a_projection_not_a_cache(tmp_path: pathlib.Path):
    """负控（投影而非缓存）：两次渲染逐字节相同；追加一条事件后必须变。

    中间那次追加用 `SS.append` 直接写盘，绕过服务：于是「页面变了」只可能来自
    「每次请求重新读盘」，不可能是别的什么东西。
    """
    root = tmp_path / "ws"
    root.mkdir()
    _seed_run(root, "t")
    _write_report(root, "# 交付说明\n\n这一趟做完了。\n")
    with server(root) as base:
        c1, html1 = _get(base, "/run/t")
        c2, html2 = _get(base, "/run/t")
        assert (c1, c2) == (200, 200)
        assert html1 == html2, "同一份盘上数据两次渲染居然不同"
        assert "这一趟做完了。" in html1, "报告没渲染进详情页"
        assert "agent_run_start" in html1 and "agent_step" in html1

        # 往同一段会话里追加一条事件 ⇒ 详情页必须变
        SS.append(root, {"kind": "agent_note", "role": "M", "note": "又记了一笔"}, sid="t")
        _c3, html3 = _get(base, "/run/t")
        assert html3 != html1, "追加了事件，页面却没变（说明缓存了）"
        assert "又记了一笔" in html3

        # 首页也是投影：新问题一落盘，首页就多一条
        c4, home1 = _get(base, "/")
        c5, home2 = _get(base, "/")
        assert home1 == home2 and c4 == c5 == 200
        qid = _ask(root, role="D", text="投影负控用的新问题")
        _c6, home3 = _get(base, "/")
        assert home3 != home1
        assert qid in home3


# ====================================================================== 8 负控
def test_model_and_user_text_is_escaped(tmp_path: pathlib.Path):
    """负控（安全）：问题正文里的 `<script>` 与选项 label 里的 `<b>` 必须被转义。"""
    root = tmp_path / "ws"
    root.mkdir()
    _ask(root, role="M", text='<script>alert(1)</script> 正文',
         options=[{"label": "<b>粗体</b>选项", "description": '<img src=x onerror=1>'}])
    with server(root) as base:
        code, body = _get(base, "/")
        assert code == 200
        assert "<script>alert(1)</script>" not in body, "问题正文没有被转义"
        assert "&lt;script&gt;" in body, "转义后的正文不在页面上"
        assert "<b>粗体</b>选项" not in body, "选项 label 没有被转义"
        assert "&lt;b&gt;" in body
        assert "<img src=x onerror=1>" not in body, "选项 description 没有被转义"


# ====================================================================== 9 负控
def test_app_css_uses_only_tokens():
    """负控（只用令牌）：`APP_CSS` 无字面色值，且确实在令牌体系里写样式。"""
    css = A.APP_CSS
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", css)
    assert hexes == [], f"APP_CSS 里有字面色值：{hexes}"
    assert not re.search(r"\b(?:rgb|rgba|hsl|hsla)\(", css), "APP_CSS 里有 rgb()/hsl()"
    alias = set(re.findall(r"var\((--dsw-alias-[A-Za-z0-9-]+)\)", css))
    assert len(alias) >= 8, f"只用了 {len(alias)} 个 --dsw-alias- 令牌：{sorted(alias)}"
    # 令牌必须是 THEME_CSS 里真的定义过的名字（不然浏览器静默回退）
    defined = set(re.findall(r"(--[A-Za-z0-9-]+)\s*:", A.THEME_CSS))
    used = set(re.findall(r"var\((--[A-Za-z0-9-]+)\)", css))
    missing = sorted(used - defined)
    assert missing == [], f"APP_CSS 引用了 THEME_CSS 里没定义的令牌：{missing}"
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
    assert A.STYLESHEET == A.THEME_CSS + A.APP_CSS


# ====================================================================== 11 正控
def test_pending_list_is_never_filtered_by_session(tmp_path: pathlib.Path):
    """正控（跨会话）：两个不同 sid 各有一条待答问题 ⇒ 两条都在，各自标着会话号。"""
    root = tmp_path / "ws"
    root.mkdir()
    qa = _ask(root, role="M", text="会话甲的提问", sid="s-a")
    qb = _ask(root, role="D", text="会话乙的提问", sid="s-b")
    with server(root) as base:
        code, body = _get(base, "/")
        assert code == 200
        assert qa in body and qb in body, "跨会话的两条问题没有同时出现"
        assert "s-a" in body and "s-b" in body, "每条问题没标着自己属于哪个会话"
        # 两条问题各自是一张独立的卡片（`id="q-<sid>-<qid>"`：qid 只在会话内唯一，
        # 所以锚点必须带会话号才不撞），顺序 =（会话号，提问顺序）
        card_a = f'id="q-s-a-{qa}"'
        card_b = f'id="q-s-b-{qb}"'
        assert card_a in body and card_b in body, "两条问题没有各自成卡"
        assert body.index(card_a) < body.index(card_b), "待答问题没有按（会话号，提问顺序）稳定排序"
        _c, raw = _get(base, "/api/state")
        state = json.loads(raw)
        assert [(q["sid"], q["qid"]) for q in state["pending_questions"]] == [
            ("s-a", qa), ("s-b", qb)]


# ====================================================================== 12 正控
def test_run_detail_replays_events_and_report(tmp_path: pathlib.Path):
    """正控（一趟详情）：步骤卡片与报告都渲染；不存在的 sid ⇒ 404（不是 200 空页）。"""
    root = tmp_path / "ws"
    root.mkdir()
    _seed_run(root, "r1")
    _write_report(root, "## 九节交付说明\n\n证据不足的地方：第 3 节。\n")
    with server(root) as base:
        code, body = _get(base, "/run/r1")
        assert code == 200, code
        for kind in ("agent_run_start", "llm_call", "agent_step", "agent_run_end"):
            assert kind in body, f"事件卡片里没有 {kind}"
        assert "第 0 步" in body and "fs.write" in body, "步骤卡片没有形状与索引"
        assert "证据不足的地方：第 3 节。" in body, "报告没有原样显示"
        assert "<pre>" in body
        # 列表页给得出这一趟
        _c, home = _get(base, "/")
        assert 'href="/run/r1"' in home
        assert "最近一趟" in home
        code404, body404 = _get(base, "/run/nope")
        assert code404 == 404, code404
        assert "404" in body404


# ====================================================================== 13 负控
def test_events_outside_a_run_never_become_a_run(tmp_path: pathlib.Path):
    """负控（投影不造假）：轮次之外的零散事件不许被折成一趟，`last_run` 不许被顶掉。

    父在真工作区上的复现（`projects/p5-run15`）：`agent_run_end` 之后紧跟的一条
    `user_answer`（人刚按下「提交」写进去的那条）被当成新一轮的开始，于是页头
    「最近一趟」显示的是一个 `steps=0 / llm_calls=0 / usd=null / stop_reason=""`
    的空壳；那个工作区里另一个会话甚至一个 `agent_run_start` 都没有，
    却被报成「role=A 的一趟运行」。

    三态口径：没有开始标记的事件 = 「轮次之外的零散事件」（单独一栏、写明没有开始
    标记），不是「一趟 0 步的运行」；整个工作区一趟都没有 ⇒ `last_run is None`，
    页面写「还没有跑过」。
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
    SS.append(root, {"kind": "user_answer", "qid": "q0001", "answer": "第二档",
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
        _c, body = _get(base, "/")
        # 从「运行态」那个小标题切到「轮次之外的零散事件」小标题：这一段是运行态栏
        head = body[body.index('sec-title">运行态'):
                    body.index('sec-title">轮次之外的零散事件')]
        assert "最近一趟" in head
        # 那一趟的读数在页面上：三态徽标（final ⇒ 跑完）+ 花销 + 链接
        assert 'href="/run/t"' in head
        assert "badge-pass" in head and "跑完" in head
        assert "0.250000" in head
        assert "M" in head
        # 「最近一趟」那一栏里不许出现空壳读数（本趟事件 0 条 / 0 步）
        assert "空壳" not in head
        assert "steps" not in body, "页面里出现了内部字段名"
        # 零散事件单独一栏，并写明「没有开始标记」——一眼看出它不是一次运行
        tail = body[body.index('sec-title">轮次之外的零散事件'):]
        assert "没有开始标记" in tail
        assert "20261003" in tail and "task_end" in tail
        assert "user_answer" in tail

    # 一趟都没有的工作区 ⇒ last_run is None；页面写「还没有跑过」
    empty = tmp_path / "ws2"
    empty.mkdir()
    SS.append(empty, {"kind": "task_end", "role": "A", "outcome": "ok"}, sid="solo")
    snap2 = W.snapshot(empty)
    assert snap2["runs"] == []
    assert snap2["last_run"] is None, snap2["last_run"]
    assert len(snap2["orphans"]) == 1
    with server(empty) as base:
        _c, body2 = _get(base, "/")
        assert "还没有跑过" in body2
        assert "轮次之外的零散事件" in body2
        _c, raw = _get(base, "/api/state")
        assert json.loads(raw)["last_run"] is None


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
