# -*- coding: utf-8 -*-
"""判据（E5）：没有索引的 Run 页不许说「逐趟一致」。

## 改前是什么样（2026-11-03 清点，E5）

`/api/run-index` 在真实工作区上恒为
`{"usable": false, "tri": "unreadable", "drift": [], "index": null}` ——
`rebuild_run_index` 零生产调用者，`projects/` 下 156 个项目里 0 个有
`index/run-index.json`。而 Run 页的判据式只看了 `drift.length === 0`：

    {index.data.drift.length === 0 ? (
      <span class="empty">索引与事件现算结果逐趟一致（drift 是 0 条）。</span>

于是同一张卡上同时印着「索引不可信 —— 先把上面那一条理由处理掉」与
「索引与事件现算结果逐趟一致」。真浏览器正文（`/run/chain-1`）：
`索引不在盘上（还没建）：…/index/run-index.json` … `索引与事件现算结果逐趟一致`。

`drift == []` 在"索引不存在"这一档是空集，不是"一致"——
`sessions.reconcile_run_index` 的 docstring 自己写着 `unreadable` 不是"零处不一致"。

## 这一份守什么

| 判据 | 它钉的是 |
|---|---|
| ① `test_without_an_index_the_report_is_unreadable` | 端点：有会话、没索引 ⇒ `tri=unreadable`、`usable=False`、`index=None`、`drift=[]`（"空集"与"一致"是两件事） |
| ② `test_the_page_only_says_consistent_when_the_index_was_computed` | 页面：「逐趟一致」那一句前面必须有 `tri === "computed"` 这道门；`drift.length === 0` 不再是"一致"的判据 |
| ③ `test_a_page_stuck_on_the_old_judgement_is_reported` | 负控：把改前那段 JSX 喂给同一个检查函数 ⇒ 必须报出来 |
| ④ 浏览器逐页（`tests/test_webui_browser.py` 的 `/run/<sid>`） | 真浏览器正文里不出现「逐趟一致」（那一格今天红） |
"""
from __future__ import annotations

import http.client
import json
import pathlib
import re
import threading
from contextlib import contextmanager
from typing import Iterator

from agentflow import sessions as SS
from agentflow.store import Store

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
RUN_TSX = REPO / "ui" / "src" / "pages" / "Run.tsx"


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个有会话、但没有 `index/run-index.json` 的工作区（真机 156/156 的形状）。"""
    root = tmp_path / "ws"
    root.mkdir()
    st = Store(root)
    st.init()
    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "E5 夹具",
                     "ts": "2026-11-03T00:00:00+08:00"}, sid="sid-e5")
    SS.append(root, {"kind": "agent_step", "role": "M", "index": 0, "shape": "fs.write",
                     "payload": {}, "result": {"ok": True},
                     "ts": "2026-11-03T00:00:01+08:00"}, sid="sid-e5")
    SS.append(root, {"kind": "agent_run_end", "role": "M", "stop_reason": "final",
                     "final": "收工", "ts": "2026-11-03T00:00:02+08:00"}, sid="sid-e5")
    return root


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


def _get(base: str, path: str) -> tuple[int, dict]:
    conn = http.client.HTTPConnection(base, timeout=30)
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


#: 块注释与整行注释（判据只看真的会渲染的写法）。
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)


def _code_only(text: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


#: 「逐趟一致」之前要看多大一段（足够罩住那一支三元表达式，又不至于把上面
#: 「索引不可用」那张徽标段落当成门）。
_WINDOW = 1200


def _consistent_claim_problems(source: str) -> list[str]:
    """「逐趟一致」那一句是不是只在 `tri === "computed"` 那一档才可能出现。

    纯函数（负控喂改前那段 JSX 用）：只看代码、不看注释。
    """
    code = _code_only(source)
    problems: list[str] = []
    n = code.count("逐趟一致")
    if n != 1:
        problems.append(f"「逐趟一致」出现了 {n} 次（应当只有 computed 那一支一句话）")
        return problems
    at = code.index("逐趟一致")
    chain = code[max(0, at - _WINDOW):at]
    if 'tri === "computed"' not in chain:
        problems.append("「逐趟一致」那一句前面没有 tri === computed 这道门 "
                        "（无索引时 drift 为空会被读成「一致」）")
    if "drift.length === 0" in code:
        problems.append("页面还在把 drift.length === 0 当「一致」的判据")
    return problems


# ====================================================================== ① 端点
def test_without_an_index_the_report_is_unreadable(tmp_path: pathlib.Path) -> None:
    """①：有会话、没索引 ⇒ `unreadable`，`drift` 是空集而不是"一致"。"""
    root = _ws(tmp_path)
    assert not (root / "index" / "run-index.json").exists(), "夹具不该有索引"
    with _server(root) as base:
        code, got = _get(base, "/api/run-index")
    assert code == 200, code
    assert got["tri"] == "unreadable", got
    assert got["usable"] is False, got
    assert got["index"] is None, got
    assert got["drift"] == [], got
    assert "索引不在盘上" in got["reason"], got


# ====================================================================== ② 页面
def test_the_page_only_says_consistent_when_the_index_was_computed() -> None:
    """②：页面里那一句「逐趟一致」有一道 `tri === "computed"` 的门。"""
    problems = _consistent_claim_problems(RUN_TSX.read_text(encoding="utf-8"))
    assert problems == [], "；".join(problems)


# ====================================================================== ③ 负控
def test_a_page_stuck_on_the_old_judgement_is_reported() -> None:
    """③（负控）：改前那段 JSX（只看 drift 长度）⇒ 同一个检查函数必须红。"""
    old = """
            {index.data.drift.length === 0 ? (
              <span class="empty">索引与事件现算结果逐趟一致（drift 是 0 条）。</span>
            ) : (
              index.data.drift.map((d, i) => (<div class="row drift" key={i}>{d}</div>))
            )}
    """
    problems = _consistent_claim_problems(old)
    assert problems, "改前那段居然通过了"
    assert any("drift.length === 0" in p for p in problems), problems
    assert any("tri === computed" in p for p in problems), problems
