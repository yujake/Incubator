# -*- coding: utf-8 -*-
"""判据（先红 · 未修）：`agentflow closing` 过了门就建趟次索引（2026-11-03 第二笔，E5 的第三半）。

## 改前读数

索引有两个生产入口（顶趟收工成功那一步、`agentflow project rebuild-run-index`），
而 `agentflow closing` 过了门也不建 ⇒ 运维/CI 跑完收工门之后 `/api/run-index` 仍然是
`tri="unreadable"`（页面那一半只能说"没有索引可对账"）。

## 这一笔的契约（四条）

1. 门过（退出码 0）⇒ 索引在盘上，且 `/api/run-index` 读到 `tri="computed"`；
   审计行 `by="agentflow closing"`（`data/events.jsonl` 的 `run_index_rebuild`）；
2. 门不过（退出码 1/2）⇒ 不建；盘上已有索引时逐字节不变；
3. 幂等：连跑两次通关的收工门，索引字节相同（内容一致就不重写）；
4. `--no-index` ⇒ 不写盘（连审计都不落）；
5. 建索引失败 ⇒ 退出码仍是 0（派生数据建不成不改判门），但打一句黄字 + 盘上一行
   `checked=False` 的审计 —— "失败不静默"这条纪律在这里也要成立。

为什么建索引挂在"退出码 0"之后、而且失败不改退出码：索引是派生读数（"这一趟对过账"），
建不成不该把"门过了"改判成"没交付"；但它必须可见 —— 一句黄字 + 盘上一行审计。
"""
from __future__ import annotations

import pathlib

from agentflow import sessions as SS

# 复用既有的现场：五条内容级判据全过 + M 说达成（`_good_clean_and_sid`）、
# 真 HTTP 那三个小工具（`test_run_index_has_a_producer`）—— 不新造第二份夹具。
from test_release_acceptance_wiring import (  # noqa: E402
    _good_clean_and_sid,
    _run,
    _touch_session,
)
from test_run_index_has_a_producer import _get, _index_events, _server  # noqa: E402
from _credential_fixture import issue_credential  # noqa: E402


def _good_clean_signed(tmp_path: pathlib.Path):
    """`_good_clean_and_sid` + 每条非概念命题的可复算签（D268 批 2 的口径）。

    收工门的 `statements_unsigned` 从批 2 起只认 `vsigns.sign_reading` 的可复算凭据
    （`out/vsigns/<正文 sha>.json`）：三票只在台账里 = `unissued` ⇒ blocker。这一组
    判据的前提是"门真的过了"；断言一个字没改，只是按新口径把"绿"造全（同一份正文、
    同一个号，签不上就红）。
    """
    st, report, sid = _good_clean_and_sid(tmp_path)
    for row in st.rows("statements"):
        if str(row.get("kind") or "") == "concept":
            continue
        issue_credential(st.root, proof_text=str(row.get("proof_text") or ""),
                         statement_id=str(row.get("stmt_id") or ""))
    return st, report, sid


def _passing_run(st, report, sid) -> tuple[int, str]:
    """跑一次"门过"的收工门（与 `test_release_acceptance_wiring` 的口径逐字相同）。"""
    return _run(st, report, "--sid", _touch_session(st),
                "--cap-usd", "1.0", "--acceptance-sid", sid)


def test_a_passing_gate_leaves_an_index_the_api_can_read(tmp_path: pathlib.Path) -> None:
    """① 门过 ⇒ 索引在盘上、`/api/run-index` 读到 computed、审计点名这是收工门建的。"""
    st, report, sid = _good_clean_signed(tmp_path)
    path = SS.run_index_path(st.root)
    assert not path.is_file(), "夹具不该一开始就有索引"

    code, out = _passing_run(st, report, sid)
    assert code == 0, out
    assert path.is_file(), f"门过了却没建索引：\n{out}"
    reading = SS.run_index_report(st.root)
    assert reading["tri"] == "computed", reading
    assert reading["usable"] is True, reading
    assert reading["drift"] == [], reading

    # 真 HTTP：页面读的那一条端点必须读得出这份索引（不是只读函数对）。
    with _server(st.root) as base:
        http_code, got = _get(base, "/api/run-index")
    assert http_code == 200, (http_code, got)
    assert got["tri"] == "computed", got
    assert got["usable"] is True, got

    # 审计：这一笔是收工门建的（`by` 逐字）。
    rows = _index_events(st.root)
    assert rows, "建了索引却没进审计（data/events.jsonl 里没有 run_index_rebuild）"
    assert rows[-1].get("checked") is True, rows[-1]
    assert rows[-1].get("by") == "agentflow closing", rows[-1]


def test_a_blocked_gate_builds_nothing_and_keeps_the_existing_bytes(
        tmp_path: pathlib.Path) -> None:
    """② 门不过 ⇒ 不建；已有索引逐字节不变。"""
    st, report, sid = _good_clean_signed(tmp_path)
    path = SS.run_index_path(st.root)

    code, out = _run(st, report, "--sid", _touch_session(st), "--goal-not-met")
    assert code == 1, (code, out)
    assert not path.is_file(), f"门不过（退出码 {code}）却建了索引：\n{out}"

    # 盘上已有一份索引时：再跑一次不过的门，字节一个都不许动。
    SS.rebuild_run_index(st.root)
    before = path.read_bytes()
    code2, out2 = _run(st, report, "--sid", _touch_session(st), "--goal-not-met")
    assert code2 == 1, (code2, out2)
    assert path.read_bytes() == before, "门不过时覆盖了已有索引"


def test_the_index_is_idempotent_across_two_passing_runs(
        tmp_path: pathlib.Path) -> None:
    """③ 幂等：连跑两次通关的收工门，索引字节相同。"""
    st, report, sid = _good_clean_signed(tmp_path)
    path = SS.run_index_path(st.root)

    code, out = _passing_run(st, report, sid)
    assert code == 0, out
    first = path.read_bytes()

    code2, out2 = _passing_run(st, report, sid)
    assert code2 == 0, out2
    assert path.read_bytes() == first, (
        "连跑两次通关的收工门，索引字节变了 ⇒ 它不是幂等的（`generated_at` 被重写了）")


def test_a_failed_build_keeps_exit_zero_and_lands_in_the_audit(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """⑤ 建索引失败不改退出码，但必须可见（一句话 + 盘上一行审计）。"""
    st, report, sid = _good_clean_signed(tmp_path)

    def _boom(_root) -> dict:
        raise OSError("磁盘满了（判据的打桩）")

    monkeypatch.setattr(SS, "rebuild_run_index", _boom)
    code, out = _passing_run(st, report, sid)
    assert code == 0, (code, out)
    assert "趟次索引没建成" in out and "磁盘满了" in out, out
    assert not SS.run_index_path(st.root).is_file(), "打桩失败却写出了索引"
    rows = _index_events(st.root)
    assert rows, f"建索引失败没进审计：\n{out}"
    assert rows[-1].get("checked") is False, rows[-1]
    assert "磁盘满了" in str(rows[-1].get("reason") or ""), rows[-1]
    assert rows[-1].get("by") == "agentflow closing", rows[-1]


def test_no_index_does_not_write(tmp_path: pathlib.Path) -> None:
    """④ `--no-index` ⇒ 不写盘（只想看门过没过的人不留下索引，也不落审计）。"""
    st, report, sid = _good_clean_signed(tmp_path)
    path = SS.run_index_path(st.root)
    assert _index_events(st.root) == []

    code, out = _run(st, report, "--sid", _touch_session(st), "--no-index",
                     "--cap-usd", "1.0", "--acceptance-sid", sid)
    assert code == 0, (code, out)
    assert not path.is_file(), f"`--no-index` 却写了索引：\n{out}"
    assert _index_events(st.root) == [], (
        "`--no-index` 却落了审计 —— 那一趟什么都没写，不该多出一行")
    assert "没建（`--no-index`）" in out, out
