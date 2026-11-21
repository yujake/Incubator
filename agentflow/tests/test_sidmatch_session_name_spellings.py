# -*- coding: utf-8 -*-
"""判据（SIDMATCH）：同一趟会话的两种日期写法必须读到同一份文件（真机 lp-ball-14）。

## 现场（2026-11-21，只读取证：`temp/sidmatch/forensics_read.py`）

真机那一趟的会话文件是 `projects/lp-ball-14/sessions/2026-11-21.jsonl`（ISO 写法，
2300 条事件、0 条坏行），因为启动时传的是 `--sid 2026-11-21`，而写侧
（`sessions.session_path`）把会话号「逐字」当文件名。收工门的 `user_pending` 那一格
却报：

    这一趟没有会话记录（...\\sessions\\20261121.jsonl 不在盘上）⇒ 没有可判对象，记 na

`20261121` 是 `sessions.session_id()` 的缺省写法（`%Y%m%d`）：不给号的那条路按它拼
文件名，而同一趟的会话在盘上是另一种写法 ⇒ 「查过了没问题」被降成「没有可判对象」。

## 判据（四条）

| # | 判据 | 反真空 / 负控 |
|---|---|---|
| a | 会话按 ISO 写法落盘、读侧拿缺省号（`sid=None`）⇒ `user_pending` 读到它（改前 `na`） | 那份里有一个未答问题 ⇒ 必须 `fail` 且点名 qid（不是"碰巧判过了"） |
| b | `--sid 2026-11-21` 与 `--sid 20261121` 读到同一份文件（同一格读数、同一个 `session_file`） | 两种写法的 `session_file` / `pending` 逐字相同 |
| c | 三态：两种写法都不在盘上 ⇒ `na`（不是 pass）；文件在但读不成 ⇒ `unknown`（不是 na） | 同一副夹具只差"文件在不在 / 坏不坏" |
| d | 反真空：把兼容逻辑打桩掉（只认逐字那一份）⇒ a / b 必红 | 打桩复现的就是改前那一行（`sessions.session_path(root, sid).is_file()`） |

## 为什么规范形是 ISO 而不是 `%Y%m%d`

真机上「这一趟」的会话文件都是 ISO 名（`projects/*/sessions/2026-*.jsonl` 14 份，全是
真跑写的），紧凑名那一族是"没给号的那条路"落下的当日缺省文件（多数只有几十 KB）。
两种写法并存时（历史遗留的分叉）读最近被写过的那一份，两份都留在
`session_candidates` 里 —— 这一格不猜"哪一份才是这一趟"，它把事实摆出来。
"""
from __future__ import annotations

import io
import pathlib
from contextlib import redirect_stderr, redirect_stdout

import pytest

from agentflow import cli
from agentflow import closing as CL
from agentflow import sessions as SS
from agentflow.store import Store

#: 一个待答问题（形状与 `userio.ASK_KIND` 那一份逐键相同）。
QUESTION = {
    "kind": "user_question", "role": "M", "qid": "q0001",
    "text": "同一趟的两种日期写法，要不要统一？",
    "options": ["统一", "两种都认"], "timeout_sec": 60.0,
}


def _spellings() -> tuple[str, str]:
    """`(紧凑, ISO)`：今天这一天的两种写法（缺省号就是紧凑那一份）。"""
    compact = SS.session_id()
    assert len(compact) == 8 and compact.isdigit(), (
        f"`sessions.session_id()` 读出来不是 `%Y%m%d`（{compact!r}）⇒ 这副夹具的前提不成立"
        "（环境变量 `AGENTFLOW_SESSION` 把它改掉了吗）")
    return compact, f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"


def _ws(tmp_path: pathlib.Path, *, sid: str, ask: bool = True) -> pathlib.Path:
    """一个门跑得动的最小工作区；会话按 `sid` 那种写法落盘（写侧逐字命名）。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    SS.append(ws, {"kind": "agent_run_start", "role": "M"}, sid=sid)
    if ask:
        SS.append(ws, QUESTION, sid=sid)
    return ws


def _cell(ws: pathlib.Path, sid: str | None) -> tuple[str, dict]:
    """跑收工门（只跑 `user_pending` 那一格）⇒ `(三态, 那一格的读数)`。"""
    rep = CL.check_closing(Store(ws), checks=("user_pending",), sid=sid)
    return str(rep.status.get("user_pending") or ""), dict(rep.readings.get("user_pending") or {})


def _cli(ws: pathlib.Path, sid: str) -> tuple[int, str]:
    """`agentflow closing --sid <sid> --no-index` 的出口读数（stdout+stderr 收成一段）。

    `--no-index`：这一条只读门过没过，不走通关之后建索引那一笔（那会写盘）。
    """
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        code = cli.main(["--plain", "--root", str(ws), "closing",
                         "--no-review-acceptance", "--no-index", "--sid", sid])
    return int(code), buf.getvalue()


# ----------------------------------------------------------------- a) 缺省号读 ISO 那一份


def test_a_the_default_reader_finds_the_iso_named_session(tmp_path: pathlib.Path) -> None:
    """a) 会话是 ISO 名、读侧拿缺省号 ⇒ 读到它（改前：`na`）。

    改前 `_check_user_pending` 只拼 `sessions/<session_id()>.jsonl`（紧凑），那个文件
    不在盘上 ⇒ 这一格记 `na`。这一条在改前的代码上必红（读数就是现场那句
    "没有会话记录 ... 不在盘上"）。
    """
    _compact, iso = _spellings()
    ws = _ws(tmp_path, sid=iso)
    assert (ws / "sessions" / f"{iso}.jsonl").is_file(), "夹具不成立：ISO 那一份没落盘"
    assert not (ws / "sessions" / f"{_compact}.jsonl").is_file(), (
        "夹具不成立：紧凑那一份也在盘上 ⇒ 这一条测不到「两种写法」这件事")

    state, reading = _cell(ws, None)
    assert state == "fail", (
        "缺省号没读到 ISO 那一份会话（改前就是 `na`：na 说「没有可判对象」，而这里有"
        f"一个未答问题在等用户）：state={state!r} reading={reading}")
    assert [q["qid"] for q in reading.get("pending") or []] == ["q0001"], reading
    assert reading.get("session_file") == f"{iso}.jsonl", (
        f"读数没有点名实际命中的文件：{reading}")


# ----------------------------------------------------------------- b) 两种写法读到同一份


def test_b_both_sid_spellings_read_the_same_file(tmp_path: pathlib.Path) -> None:
    """b) `--sid` 的两种日期写法读到同一份文件（正控）。

    改前：紧凑那一份不在盘上 ⇒ `closing_session_identity` 走受控拒绝（退出码 2），
    门根本不跑 —— 与"用 ISO 写法读到了"是两回事。这一条钉的是
    "同一个会话号的两种写法指向同一份文件"。
    """
    compact, iso = _spellings()
    ws = _ws(tmp_path, sid=iso)

    id_compact = CL.closing_session_identity(ws, compact)
    id_iso = CL.closing_session_identity(ws, iso)
    assert not id_compact.problem, (
        f"紧凑写法被拒了：{id_compact.problem!r}（改前就是这一句：号不在盘上）")
    assert id_compact.sid == id_iso.sid == iso, (id_compact, id_iso)
    assert f"{iso}.jsonl" in id_compact.note, id_compact.note
    # 两个公开入口直接调一次（口径本身也与"两种写法同一个号"一致）。
    assert CL.session_id_spellings(iso) == CL.session_id_spellings(compact) == (iso, compact)
    _path, _candidates = CL.session_file_of(ws, compact)
    assert _path is not None and _path.name == f"{iso}.jsonl", (_path, _candidates)

    state_c, reading_c = _cell(ws, compact)
    state_i, reading_i = _cell(ws, iso)
    assert state_c == state_i == "fail", (state_c, state_i, reading_c, reading_i)
    for key in ("session_file", "session_id", "pending", "answered", "asked"):
        assert reading_c.get(key) == reading_i.get(key), (
            f"两种写法在 `{key}` 上分家了：{reading_c.get(key)!r} vs {reading_i.get(key)!r}")
    assert reading_c.get("session_file") == f"{iso}.jsonl", reading_c

    # CLI 出口（与 `agentflow closing --sid …` 同一条路）：紧凑写法不许是受控拒绝。
    code, out = _cli(ws, compact)
    assert "拒绝" not in out, (
        f"`--sid {compact}` 走了受控拒绝（改前就是这一句）⇒ 门根本没跑：{out[-800:]}")
    assert "user_pending：拦住" in out, (
        f"CLI 的 user_pending 没读到那份会话里的待答问题：{out[-800:]}")
    # 退出码这一条不管：这份夹具没有 M 的判据 ⇒ 落到"没人判过"那一档（2）。
    assert code in (1, 2), (code, out[-800:])


# ----------------------------------------------------------------- c) 三态


def test_c_absent_is_not_applicable_and_unreadable_is_unknown(
        tmp_path: pathlib.Path) -> None:
    """c) 真没有会话 ⇒ `na`（不是 pass）；文件在但读不成 ⇒ `unknown`（不是 na）。

    两档必须是两个词：前者"没有可判对象"，后者"有对象、我们没判成"。
    「真没有」分两条出口：缺省号（运维口径，`sid=None`）走判据层 ⇒ `na`；显式给号
    走身份闸 ⇒ 受控拒绝（退出码 2，门根本不跑）—— 后者不是 `na`，也不是一份空读数。
    """
    compact, iso = _spellings()
    empty = tmp_path / "empty"
    empty.mkdir()
    state, reading = _cell(empty, None)
    assert state == "na", (
        f"缺省号 + 两种写法都不在盘上 ⇒ 这一格必须是 na（不是 pass，也不是 unknown）："
        f"{state!r} {reading}")
    assert "没有可判对象" in str(reading.get("reason") or ""), reading
    for name in (f"{iso}.jsonl", f"{compact}.jsonl"):
        assert name in str(reading.get("reason") or ""), (
            f"na 的理由没有逐个点名找过的文件（{name}）：{reading.get('reason')!r}")
    # 显式给号那一档：受控拒绝（门不跑），不是 na、也不是 pass。
    refused = CL.closing_session_identity(empty, compact)
    assert refused.problem and refused.code == CL.NO_SUCH_SESSION, refused
    for name in (f"{iso}.jsonl", f"{compact}.jsonl"):
        assert name in refused.problem, (
            f"拒绝理由没有逐个点名找过的文件（{name}）：{refused.problem!r}")

    broken = _ws(tmp_path / "broken", sid=iso, ask=False)
    (broken / "sessions" / f"{iso}.jsonl").write_text("{这不是 JSON\n", encoding="utf-8")
    state, reading = _cell(broken, iso)
    assert state == "unknown", (
        f"会话文件在盘上但读不成 ⇒ 这一格必须是 unknown（不是 na、也不是 pass）："
        f"{state!r} {reading}")
    assert "读不成" in str(reading.get("reason") or ""), reading


# ----------------------------------------------------------------- d) 反真空


def test_d_stubbing_the_alias_lookup_makes_a_and_b_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 反真空：把兼容逻辑打桩掉（只认逐字那一份）⇒ a / b 必红。

    打的是唯一的兼容落点 `closing.session_file_of`（不是把 `check_closing` 换掉）：
    换掉的话证明的是"夹具能红"，不是"这一行改动就是让两种写法命中的那一行"。
    打桩之后的行为逐字等于改前那两行：
    `sessions.session_path(session_root, sid).is_file()` + `read_session(sid=sid)`。
    """
    compat = getattr(CL, "session_file_of", None)
    assert compat is not None, (
        "`closing.session_file_of` 不存在 ⇒ 这一条反真空没有对象（兼容逻辑换了落点却没换判据）")

    def _verbatim_only(session_root, sid):
        """改前口径：只认逐字那一份（另一种写法不试）。"""
        path = SS.session_path(session_root, sid)
        return (path if path.is_file() else None), (path,)

    _compact, iso = _spellings()
    ws = _ws(tmp_path, sid=iso)
    plain_state, plain_reading = _cell(ws, None)
    assert plain_state == "fail", ("先证明没打桩时 a 是绿的（否则下面的红是假红）",
                                   plain_state, plain_reading)

    monkeypatch.setattr(CL, "session_file_of", _verbatim_only)
    monkeypatch.setattr(CL, "_session_candidates",
                        lambda root, sid: (SS.session_path(root, sid),))

    stubbed_state, stubbed_reading = _cell(ws, None)
    assert stubbed_state == "na", (
        "打桩回'只认逐字'之后 a 的读数居然还是绿的 ⇒ a 没有接线到兼容逻辑那一行："
        f"{stubbed_state!r} {stubbed_reading}")
    refused = CL.closing_session_identity(ws, _spellings()[0])
    assert refused.problem and refused.code == CL.NO_SUCH_SESSION, (
        "打桩之后 b 的那一半（紧凑写法）应当受控拒绝（改前就是这样）：", refused)
