# -*- coding: utf-8 -*-
"""判据（先红 · 未修）：运行外出口要能说清"你读的是哪一场"（2026-11-03，153-U-07）。

## 这一条治的是什么

收工门问"这一趟有没有话在等用户"。运行内（`tools/conductor_tools.py` 的
`conductor.closing`）把这一趟的 `sid` 传下去；运行外（`agentflow closing`）此前
一个会话号都不带 ⇒ `closing.check_closing(sid=None)` ⇒ `_check_user_pending`
按 `sessions/<今天>.jsonl` 读。于是同一个问题在两个入口上是两个问题：

    运行外问的是「今天那份会话」，运行内问的是「那一趟的会话」。

这不是"运行外更宽松"这种程度的问题 —— 缺省会话里往往什么都没有，于是
`user_pending` 读到 `pass`，而那一趟真在等用户还没答（`draft/37` §58/§63 的假绿）。

## 判据（三条，对着 `--sid` 的三个态）

1. 不带 `--sid` ⇒ 读数里点名"缺省会话"，且 `user_pending` 是「没查成」。
   负控在这一条的杀伤力上：缺省会话里真的放一个待答问题 ⇒ 读数仍必须是
   「没查成」，不许因为它读到了那个问题就变成 `拦住`（那正是要治的假绿）。
2. `--sid X`（X 在盘上）⇒ 读数点名 X，`user_pending` 读的是那一段
   （X 里有一个待答问题 ⇒ `拦住`，缺省会话里有待答问题也不算）。
3. `--sid X`（X 不在盘上）⇒ 受控拒绝：退出码 2、点名那个号、说明为什么，
   不出一份空读数（不是"八格全是没查成"那种看起来像读过的样子）。

三态纪律在这里的形态：`unknown`（没有会话身份）／`fail`（那一段真在等用户）／
受控拒绝（连读哪一段都定不下来）是三件不同的事，不许折成同一个值。
"""
from __future__ import annotations

import io
import pathlib
from contextlib import redirect_stderr, redirect_stdout

from agentflow import cli
from agentflow import sessions as SS
from agentflow.store import Store

#: 盘上那一段会话的号（`--sid` 显式给的就是它）。
SID = "real-u07"

#: 一个待答问题（形状与 `userio.ASK_KIND` 那一份逐键相同，见
#: `tests/test_session_context_wiring.py` 的同一条夹具）。
QUESTION = {
    "kind": "user_question", "role": "M", "qid": "q0001",
    "text": "这两处改动要不要保留？", "options": ["保留", "回退"], "timeout_sec": 60.0,
}


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个门跑得动的最小工作区（每张表都初始化过、都是 0 行）。"""
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    st = Store(tmp_path)
    st.init()
    return tmp_path


def _run(ws: pathlib.Path, *extra: str) -> tuple[int, str]:
    """走 CLI 出口，把 stdout/stderr 收成一段文本。

    `--no-review-acceptance` 关掉后半段（内容级验收）的噪音：这一条判据读的是
    收工门自己那一格 `user_pending`，别的栏打什么都与它无关。
    """
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        code = cli.main(["--plain", "--root", str(ws), "closing",
                         "--no-review-acceptance", *extra])
    return int(code), buf.getvalue()


# ---------------------------------------------------------------- ① 不带 --sid


def test_without_sid_the_reading_names_the_default_session(tmp_path: pathlib.Path) -> None:
    """① 不带 `--sid` ⇒ 读数点名"缺省会话"，且那一格是「没查成」（今天红）。"""
    ws = _ws(tmp_path)
    code, out = _run(ws)
    assert "缺省会话" in out, (
        "读数里没有点名「缺省会话」⇒ 读的人不知道这一格问的是哪一场会话", out[-2000:])
    assert "user_pending：没查成" in out, (
        "不带 `--sid` 时 `user_pending` 必须是「没查成」：这一次调用没有会话身份，"
        "按缺省会话读会把「问了还没答」读成「没问过」", out[-2000:])
    assert code == 2, (code, out[-2000:])


def test_the_default_session_is_not_silently_read(tmp_path: pathlib.Path) -> None:
    """① 的负控（杀伤力在这一半）：缺省会话里真有提问 ⇒ 仍必须是「没查成」。"""
    ws = _ws(tmp_path)
    SS.append(ws, QUESTION, sid=None)      # 落在 sessions/<今天>.jsonl（缺省会话）
    code, out = _run(ws)
    assert "user_pending：没查成" in out, (
        "缺省会话里有一个待答问题，读数就把它读成「拦住」了 —— 这正是 §58/§63 的假绿："
        "「今天那份会话」不是「这一趟的会话」", out[-2000:])
    assert "缺省会话" in out, out[-2000:]
    assert code == 2, (code, out[-2000:])


# ---------------------------------------------------------------- ② --sid X


def test_with_sid_the_reading_names_that_session(tmp_path: pathlib.Path) -> None:
    """② `--sid X` ⇒ 读数点名 X，且读的是那一段（今天红：没有 `--sid`）。"""
    ws = _ws(tmp_path)
    SS.append(ws, QUESTION, sid=SID)
    code, out = _run(ws, "--sid", SID)
    assert code in (1, 2), (code, out[-2000:])   # 2 = 没人判过（这一格不是这个码的来源）
    assert SID in out, (
        f"读数里没有点名 `--sid` 给的那个号 {SID!r} ⇒ 读的人不知道读的是哪一场",
        out[-2000:])
    assert "user_pending：拦住" in out, (
        "那一段里有一个待答问题 ⇒ 这一格必须是「拦住」，不是「通过」", out[-2000:])
    assert "缺省会话" not in out, (
        "给了 `--sid` 之后读数里还提「缺省会话」⇒ 两个量又混回一句话里", out[-2000:])
    # 退出码这一条判据不管：这份夹具没有 M 的判据 ⇒ `tri_state_exit_code` 落到
    # "没人判过"那一档（2），与「待答问题」这一格无关。真正钉住的是上面两句：
    # 点名了那个号、且那一格读的是那一段（`拦住`）。


# ---------------------------------------------------------------- ③ 号不在盘上


def test_an_unknown_sid_is_a_controlled_refusal(tmp_path: pathlib.Path) -> None:
    """③ `--sid X` 而 X 不在盘上 ⇒ 受控拒绝，不是一份空读数（今天红）。"""
    ws = _ws(tmp_path)
    missing = "no-such-session"
    code, out = _run(ws, "--sid", missing)
    assert code == 2, (code, out[-2000:])
    assert missing in out, (
        "拒绝里没有点名那个号 ⇒ 人不知道该去改哪一个参数", out[-2000:])
    assert "拒绝" in out, ("这不是受控拒绝：没有任何一句说明它拒了", out[-2000:])
    assert "Traceback" not in out, out[-2000:]
    # "不是空读数"：拒绝必须在跑门之前就发生 —— 八格那一张表一格都不许印出来。
    assert "paper：" not in out, (
        "号不在盘上却照样把八格印了一遍 ⇒ 那是「八格全是没查成」的假读数，"
        "读的人会以为读过一遍了", out[-2000:])
