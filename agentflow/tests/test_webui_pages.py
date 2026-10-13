# -*- coding: utf-8 -*-
"""六页面接线的判据（裁定 W1 A3）：每页一条 —— 真读数出现 + 空态 + 三态。

## 这一组守的是什么

契约判据 A–D（`tests/test_webui_contracts.py`）守的是「名字层」（端点集合、事件
集合、类型键集合、路由集合）。它们全都可能绿着，而页面照样是空壳 —— 只要页面
"声明了正确的端点却不读它的任何一栏"。这一组补的正是那一条：页面真的读到了
那一栏，而且空态与三态都分得开。

每页一条用例，每条断言三件事（`draft/74 §3` 的矩阵逐行落）：

1. 「真读数出现」：页面声明的端点，在夹具工作区（`tests/conftest.py` 的
   `make_artifacts_sample`，裁定 J2/K2）上真的读出东西来，而且页面源码里读的正是
   那些键（`_page_reads` 把页面源码里出现的契约键集合抓出来）；
2. 「空态」：换一份"合法但空"的工作区，读数仍是"读到了，里面是 0 行"，
   页面里有一句空态文案（`EMPTY_WORDS` 逐页登记）；
3. 「三态」：把那一面的源改坏（写一行坏 JSON / 不给 `cap_usd` / 索引没建），
   三态必须不是"算出来了"，而页面里必须把那个三态交给 `TriState`。

## 为什么"页面源码 + 后端读数"两头都验

只验后端：页面可以一个字都不读它（本批之前的空壳就是那样）。
只验源码：源码里可以写着一个后端不存在的键（`tsc` 抓不到 —— 后端给的是 JSON）。
两头一起验，中间那条链（端点 → 键 → 页面读的那一栏）才是通的。

## 负控

每一条判据的检查逻辑都抽成纯函数（`_page_reads` / `_empty_state_problems` /
`_tri_state_problems`），负控喂改坏的输入字符串 ⇒ 当场报出来；另外每条用例都带
一个"真机负控"（`test_*_negative_control_*` 里的那几条），证明这个函数真的会红。
"""
from __future__ import annotations

import http.client
import json
import pathlib
import re
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

import pytest

from agentflow import sessions as SS
from agentflow.store import Store
from agentflow.webui import routes

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"

#: 九页的文件名 → 那一页那条（或那几条）端点（2026-10-12：业主的预算窗口与监控加了后三页）。
PAGES: dict[str, tuple[str, ...]] = {
    "Home": ("/api/state",),
    "Run": ("/api/run/{sid}", "/api/run-index"),
    "Evidence": ("/api/evidence",),
    "Artifacts": ("/api/artifacts",),
    "Acceptance": ("/api/acceptance",),
    "Machine": ("/api/machine",),
    "Budget": ("/api/budget",),
    "Live": ("/api/live", "/api/status-reports", "/api/usage"),
    # Help 页刻意不调端点：它讲的是"其余几页各自在看什么、要动手时该做什么"。
    # 这一格空着是声明，不是漏登记 —— 下面那条正控会把空元组也照常核一遍。
    "Help": (),
}

#: 每页必须读到的键（逐字对着 `draft/74 §3` 那一页的行；写错一个就红）。
PAGE_KEYS: dict[str, tuple[str, ...]] = {
    "Home": ("pending_questions", "sessions", "problems", "bad_lines", "last_kind",
             "ledger", "tables_note", "waiting_on"),
    # Run 那一页后半段十条是题 T2-a 的逐条事件（`api.getRunEvents` 那一块）：
    # 端点与类型由契约 A/C 钉，这里钉的是"页面真的读了它"。
    # 2026-10-12 追加 `switch_present`：停机那一栏接上了 `/api/live`（它是那一面的键）。
    "Run": ("runs", "report", "checkpoint", "unknown_usd", "drift", "usable",
            "orphans", "stop_reason", "spend", "events_in_run",
            "events", "total", "from_index", "to_index", "truncated",
            "index", "kind", "ts", "shape", "ok", "usd", "switch_present"),
    "Evidence": ("statements", "conjectures", "experiments", "review_findings",
                 "relations", "verifications", "secretary", "quote_verified",
                 "counterexample_experiment_id"),
    "Artifacts": ("ledger", "ledger_verify", "handoffs", "checks", "style",
                  "products", "tasks", "sha256_now", "run_dir"),
    "Acceptance": ("criteria", "auxiliary", "details", "failed", "capUsd"),
    "Machine": ("provers", "mathlib", "lean_ready", "can_do_formal", "settings",
                "configured"),
    # 三页新的（2026-10-12）：各钉住"这一页真的读了那一面的哪几栏"。
    "Budget": ("total_usd", "spent_usd", "remaining_usd", "exceeded", "source",
               "added", "added_count", "by_role", "by_scope", "spent_tri",
               "spent_reason", "problem", "entries", "tokens"),
    "Live": ("answer", "running", "live", "unreadable_sessions", "switch_present",
             "switch", "history", "interrupts", "reports", "count", "dir",
             "spent"),
    "Help": (),
}

#: 逐条事件那一块必须写死的那句话（题 T2-a 的三态纪律：`unreadable` 不许渲染成
#: 一张空列表）。它是这一块的负控唯一抓得住的字符串 —— 抽掉它，页面就把
#: "没查成"与"这一趟没有事件"画成一个样子。
EVENTS_TRI_WORD = "不是一张空列表"

#: 每页必须出现的那句空态文案（"读到了，里面是 0"那一档，不是"没查成"）。
EMPTY_WORDS: dict[str, str] = {
    "Home": "暂无待回答的问题（合法初态",
    "Run": "这一段会话里一趟都没有",
    "Evidence": "暂无命题（已读出）",
    "Artifacts": "台账 0 行（读到了，里面是空的",
    "Acceptance": "一条判据都没读到",
    "Machine": "探测读数里一格都没有",
    "Budget": "暂无追加或重设记录",
    "Live": "会话面：没有在跑的循环",
    # Help 页没有读数，也就没有空态文案（那一格对它不适用）。
    "Help": "",
}

#: 每页必须把三态交给组件的证据：`TriState` 这个标识符必须出现在页面源码里。
TRI_TOKEN = "TriState"


# ====================================================================== 读源码
def _page_text(name: str) -> str:
    """一页的源码（不在盘上就 skip —— 理由里写明）。"""
    path = UI_SRC / "pages" / f"{name}.tsx"
    if not path.is_file():
        pytest.skip(f"前端那一页还没落地：{path.name} 不在盘上")
    return path.read_text(encoding="utf-8")


#: 块注释与整行注释（这一组判据只处理这两种；行尾注释在这一批的六个页面里没有）。
#: 为什么不用"逐字符扫引号"的那一版（`test_webui_contracts.py` 里那一种）：页面的
#: JSX 正文里有中文引号对（`标明"夹具样本"`），逐字符扫会把正文里的一对引号当成
#: 一段字符串，于是代码被整段吞掉，判据会以"页面什么都没读"的形态假红。
#: 实测：Artifacts 页 10413 字节被吞成 2179 字节（2026-10-07）。
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)


def _strip_js_comments(text: str) -> str:
    """剥掉块注释与整行注释（理由见上一条注释）。"""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


#: 一次字段访问：`x.key` / `x?.key` / `x["key"]` 都算。
_READ = re.compile(r"[.?\[]\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?\s*\]?")
#: 表格列声明：`{ key: "events_in_run", ... }` 也算"这一页读了那一栏"。
_READ_COLUMN = re.compile(r"\bkey:\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']")
#: 对象字面量的属性名：`api.getAcceptance({ capUsd: cap })` 那一档。
_READ_PROP = re.compile(r"[\{,]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:")


def _page_reads(text: str) -> set[str]:
    """页面源码里出现过的字段名集合（剥注释后）。"""
    body = _strip_js_comments(text)
    return ({m.group(1) for m in _READ.finditer(body)}
            | {m.group(1) for m in _READ_COLUMN.finditer(body)}
            | {m.group(1) for m in _READ_PROP.finditer(body)})


def _read_problems(page: str, text: str, keys: Sequence[str]) -> list[str]:
    """页面没读到某些契约键 ⇒ 逐条报出来。"""
    got = _page_reads(text)
    return [f"{page} 页没有读 {key}" for key in keys if key not in got]


def _empty_state_problems(page: str, text: str, words: str) -> list[str]:
    """页面里没有那句空态文案 ⇒ 报出来（空态与"没查成"必须各有一句话）。"""
    if words not in _strip_js_comments(text):
        return [f"{page} 页没有那句空态文案：{words!r}"]
    return []


def _tri_state_problems(page: str, text: str) -> list[str]:
    """页面没有把三态交给 `TriState` ⇒ 报出来。"""
    body = _strip_js_comments(text)
    if TRI_TOKEN not in body:
        return [f"{page} 页里没有 {TRI_TOKEN}（三态没有落点）"]
    return []


def _events_unreadable_problems(page: str, text: str) -> list[str]:
    """逐条事件那一块有没有把"没查成"与"一张空列表"分开（题 T2-a 的三态纪律）。

    两件事一起查：那句写在三态分支里的说明（`EVENTS_TRI_WORD`）在不在，以及这一块
    读没读 `events` 这一栏。只查前者会被"别处也写了这句话"蒙过去，只查后者会被
    "把读数当数组直接渲染"蒙过去 —— 两条一起才说明得了问题。
    """
    problems: list[str] = []
    body = _strip_js_comments(text)
    if EVENTS_TRI_WORD not in body:
        problems.append(f"{page} 页的逐条事件那一块没有"
                        f"「{EVENTS_TRI_WORD}」这句（三态会被画成一档）")
    if "events" not in _page_reads(text):
        problems.append(f"{page} 页的逐条事件那一块没有读 events")
    return problems


# ====================================================================== 夹具
def _bare_workspace(tmp: pathlib.Path) -> pathlib.Path:
    """一份"合法但空"的工作区：表文件都在盘上（`init` 建的），一行数据都没有。"""
    root = tmp / "bare"
    root.mkdir()
    Store(root).init()
    return root


def _broken_workspace(tmp: pathlib.Path, artifacts_ws: pathlib.Path) -> pathlib.Path:
    """把夹具工作区抄一份，再往一场会话里写一行坏 JSON。"""
    import shutil

    root = tmp / "broken"
    shutil.copytree(artifacts_ws, root)
    sess = sorted((root / "sessions").glob("*.jsonl"))[0]
    with open(sess, "a", encoding="utf-8") as fh:
        fh.write("{ 这一行不是 JSON\n")
    return root


@contextmanager
def _server(root: pathlib.Path) -> Iterator[str]:
    """在临时端口上起一个真实的 web 服务（判据走 HTTP，不走函数调用）。

    为什么必须走 HTTP：页面读的是端点，不是 Python 函数。只调 `readers.*` 的话，
    "端点没登记进 ROUTES"这一类缺陷（B 线六面最初就是这样）会被判据整片漏掉。
    """
    from agentflow import webui as W

    srv = W.serve(root, host="127.0.0.1", port=0, csrf_token="pagestoken0123456789")
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


# ====================================================================== 1 Home
def test_home_page_reads_the_global_pending_panel(
        artifacts_ws: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """Home：真读数（待答 1 条 + 一段会话 + 台账）· 空态 · 三态（坏行 ⇒ unreadable）。

    正控读的是端点：`GET /api/state` 在夹具工作区上必须给出
    `pending_questions`（全局，不按会话过滤）与 `sessions` 的真行；负控读的是
    `_read_problems` 的输入（页面源码少读一个契约键 ⇒ 必须报）。
    """
    text = _page_text("Home")
    assert _read_problems("Home", text, PAGE_KEYS["Home"]) == [], (
        _read_problems("Home", text, PAGE_KEYS["Home"]))
    assert _empty_state_problems("Home", text, EMPTY_WORDS["Home"]) == []
    assert _tri_state_problems("Home", text) == []

    with _server(artifacts_ws) as base:
        code, snap, _raw = _get(base, "/api/state")
        assert code == 200, code
        pending = snap["pending_questions"]
        assert len(pending) >= 1, "夹具里那条没答的提问没读出来"
        assert pending[0]["sid"] and pending[0]["qid"], pending[0]
        assert set(pending[0]) >= {"qid", "sid", "role", "text", "options", "multi",
                                  "ts", "timeout_sec", "index"}, sorted(pending[0])
        assert len(snap["sessions"]) >= 1, snap["sessions"]
        assert snap["sessions"][0]["bad_lines"] == 0, snap["sessions"][0]
        assert snap["problems"] == [], snap["problems"]
        assert snap["ledger"]["events"] is not None, snap["ledger"]
        assert snap["ledger"]["tables_note"] != "", snap["ledger"]

        empty = _bare_workspace(tmp_path)
    with _server(empty) as base:
        _code, snap0, _raw = _get(base, "/api/state")
        assert snap0["pending_questions"] == [], snap0["pending_questions"]
        assert snap0["problems"] == [], (
            "空工作区是「读到了，里面是空的」—— 不许被读成「没查成」")

    broken = _broken_workspace(tmp_path, artifacts_ws)
    with _server(broken) as base:
        _code, snap1, _raw = _get(base, "/api/state")
        assert snap1["problems"], "写坏一行之后 problems 必须非空（没查成不是「没有」）"
        assert snap1["sessions"][0]["bad_lines"] == 1, snap1["sessions"][0]


def test_home_negative_control_catches_a_page_that_reads_nothing() -> None:
    """负控（Home）：把页面源码抽成"只声明端点、不读任何键"的样子 ⇒ 三类都必须报。"""
    shell = 'const ENDPOINTS = { state: "/api/state" };\nexport function Home() { return null; }\n'
    assert _read_problems("Home", shell, PAGE_KEYS["Home"]), "少读键却没报"
    assert _empty_state_problems("Home", shell, EMPTY_WORDS["Home"]), "少空态却没报"
    assert _tri_state_problems("Home", shell), "没有三态落点却没报"


# ====================================================================== 2 Run
def test_run_page_reads_the_timeline_and_the_index(
        artifacts_ws: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """Run：真读数（一趟 + 检查点 + 交付说明）· 索引对账 · 空态 · 三态。

    索引那一栏是裁定 O2 的页面消费端：索引建好且与事件一致 ⇒ `tri=computed`；
    手改索引一个字节 ⇒ `drift` 非空且 `tri != computed`（页面据此显红）。
    """
    text = _page_text("Run")
    assert _read_problems("Run", text, PAGE_KEYS["Run"]) == [], (
        _read_problems("Run", text, PAGE_KEYS["Run"]))
    assert _empty_state_problems("Run", text, EMPTY_WORDS["Run"]) == []
    assert _tri_state_problems("Run", text) == []

    sid = "fix-sid"
    with _server(artifacts_ws) as base:
        code, view, _raw = _get(base, f"/api/run/{sid}")
        assert code == 200, code
        assert view["tri"] == "computed", view
        assert len(view["runs"]) == 1, view["runs"]
        run = view["runs"][0]
        assert {"steps", "llm_calls", "usd", "unknown_usd", "stop_reason",
                "waiting_on", "events_in_run"} <= set(run), sorted(run)
        assert view["report"]["status"] == "ok", view["report"]["status"]
        assert view["report"]["text"] != "", "夹具的交付说明有正文，读出来是空的"
        ck = view["checkpoint"]
        assert isinstance(ck, dict), ck
        assert ck["spend"]["usd"] == 0.25, ck["spend"]

        # 索引还没建 ⇒ unreadable（不是「对上了」，也不是「0 处不一致」）
        code_i, idx, _raw = _get(base, "/api/run-index")
        assert code_i == 200, code_i
        assert idx["tri"] == "unreadable" and idx["usable"] is False, idx
        assert idx["index"] is None, idx

        # 建好索引 ⇒ computed 且 drift 为空
        SS.rebuild_run_index(artifacts_ws)
        _code, idx2, _raw = _get(base, "/api/run-index")
        assert idx2["tri"] == "computed", idx2
        assert idx2["usable"] is True and idx2["drift"] == [], idx2
        assert idx2["index"]["sessions"][sid]["last_end_index"] == 2, idx2["index"]

        # 手改索引一个字节 ⇒ drift 非空 + tri 不是 computed（页面显红的那一格）
        path = SS.run_index_path(artifacts_ws)
        path.write_text(path.read_text(encoding="utf-8").replace('"steps": 1', '"steps": 99'),
                        encoding="utf-8")
        _code, idx3, _raw = _get(base, "/api/run-index")
        assert idx3["tri"] != "computed", idx3
        assert idx3["drift"], idx3
        assert idx3["usable"] is False, idx3

    # 空态：会话不在盘上 ⇒ run_view 是 unreadable（sid 是调用方给的，找不到就是没查成）
    empty = _bare_workspace(tmp_path)
    with _server(empty) as base:
        _code, none_view, _raw = _get(base, f"/api/run/{sid}")
        assert none_view["tri"] == "unreadable", none_view
        assert none_view["runs"] == [] and none_view["checkpoint"] is None, none_view
        assert none_view["report"]["status"] == "missing", none_view["report"]

    # 三态：坏行 ⇒ 整面 unreadable，而读得出来的那几栏照常给行
    broken = _broken_workspace(tmp_path, artifacts_ws)
    with _server(broken) as base:
        _code, bad_view, _raw = _get(base, f"/api/run/{sid}")
        assert bad_view["tri"] == "unreadable", bad_view
        assert bad_view["reason"] != "", bad_view
        assert len(bad_view["runs"]) == 1, bad_view["runs"]


def test_run_negative_control_catches_a_page_without_the_index_column() -> None:
    """负控（Run）：页面不读索引那两栏 / 不读报告那一栏 ⇒ 必须报。"""
    shell = 'api.getRun(sid); // 只取一趟详情\n'
    assert _read_problems("Run", shell, PAGE_KEYS["Run"]), "少读键却没报"
    assert _read_problems("Run", shell, ("drift",)) == ["Run 页没有读 drift"]
    assert _tri_state_problems("Run", shell), "没有 TriState 却没报"


def test_run_page_replays_the_events_one_by_one(
        artifacts_ws: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """Run（题 T2-a）：逐条事件那一块读真数据 · 分页 · 三态。

    正控三半：① 页面源码真的读了那一块的键（`PAGE_KEYS["Run"]` 后半段）；
    ② 端点走真实 HTTP 给出四条事件与自洽的游标区间；③ 续取那一页确实接得上
    （`since_index` 用上一页的 `to_index`）。三态那一半在下面那条负控里。
    """
    text = _page_text("Run")
    assert _read_problems("Run", text, PAGE_KEYS["Run"]) == [], (
        _read_problems("Run", text, PAGE_KEYS["Run"]))
    assert _events_unreadable_problems("Run", text) == [], (
        _events_unreadable_problems("Run", text))

    with _server(artifacts_ws) as base:
        code, got, _raw = _get(base, "/api/run/fix-sid/events")
        assert code == 200, code
        assert got["tri"] == "computed", got
        assert got["total"] == 4 and (got["from_index"], got["to_index"]) == (0, 4), got
        assert [e["index"] for e in got["events"]] == [0, 1, 2, 3], got["events"]
        assert got["events"][1]["shape"] == "fs.write", got["events"][1]
        assert got["truncated"] is False, got
        # 续取：拿上一页的 `to_index` 当 `since_index`，区间必须接着
        code2, page2, _raw2 = _get(
            base, f"/api/run/fix-sid/events?since_index={got['to_index']}&limit=2")
        assert code2 == 200, code2
        assert page2["events"] == [] and page2["from_index"] == 4, page2
        code3, page3, _raw3 = _get(base, "/api/run/fix-sid/events?since_index=2&limit=1")
        assert code3 == 200, code3
        assert [e["index"] for e in page3["events"]] == [2], page3["events"]
        assert page3["to_index"] == 3 and page3["truncated"] is True, page3

    # 空工作区：那一栏是 unreadable（sid 是调用方给的，找不到就是没查成），
    # 而且它给的不是"读到了 0 条"—— 计数栏是 None。
    empty = _bare_workspace(tmp_path)
    with _server(empty) as base:
        code_none, none_got, _raw = _get(base, "/api/run/fix-sid/events")
        assert code_none == 200, code_none
        assert none_got["tri"] == "unreadable" and none_got["reason"] != "", none_got
        assert none_got["total"] is None and none_got["events"] == [], none_got


def test_run_negative_control_catches_the_events_rendered_as_an_empty_list(
        tmp_path: pathlib.Path) -> None:
    """负控（Run 的逐条事件）：三态被画平 ⇒ 必须报（红前绿后）。

    两半：① 把页面源码抽成"只把 `events` 当数组渲染"的样子（`shell`）⇒ 纯函数
    必须报出"少了那句三态说明"；② 真机那一半：会话不在盘上 ⇒ 读数是
    `unreadable` + 理由、计数栏 `None` —— 页面据此显"没查成"而不是一张空列表。
    """
    shell = 'const rows = ev.events;\n'
    assert _events_unreadable_problems("Run", shell), "三态被画平却没报"
    assert _events_unreadable_problems("Run", f"const rows = ev.events;\n// {EVENTS_TRI_WORD}\n"), (
        "写在注释里的那句话不该算数（注释会被剥掉）")
    assert EVENTS_TRI_WORD not in _strip_js_comments(f"// {EVENTS_TRI_WORD}\n")
    # 反面：真页面上这两条都不报（上面那条正控已经断言过，这里再钉一次口径）
    real = _page_text("Run")
    assert _events_unreadable_problems("Run", real) == []

    root = _bare_workspace(tmp_path)
    with _server(root) as base:
        code, got, _raw = _get(base, "/api/run/nope/events")
        assert code == 200, code
        assert got["tri"] == "unreadable", got
        assert got["reason"] != "" and got["total"] is None, got
        assert got["events"] == [], got


# ====================================================================== 3 Evidence
def test_evidence_page_reads_the_seven_columns(artifacts_ws: pathlib.Path) -> None:
    """Evidence：真读数（验证台账 1 行 + 秘书 2 行 + 五张表读到 0 行）· 三态。"""
    text = _page_text("Evidence")
    assert _read_problems("Evidence", text, PAGE_KEYS["Evidence"]) == [], (
        _read_problems("Evidence", text, PAGE_KEYS["Evidence"]))
    assert _empty_state_problems("Evidence", text, EMPTY_WORDS["Evidence"]) == []
    assert _tri_state_problems("Evidence", text) == []

    with _server(artifacts_ws) as base:
        code, ev, _raw = _get(base, "/api/evidence")
        assert code == 200, code
        assert ev["tri"] == "computed", ev
        for column in ("statements", "conjectures", "experiments", "review_findings",
                       "relations"):
            assert ev[column] == [], f"{column} 夹具里没有行"
            assert ev[column + "_tri"] == "computed", (
                f"{column} 的表文件在盘上 ⇒ 那是「读到了，里面是 0 行」，"
                f"不是「还没写过」：{ev[column + '_tri']}")
        assert len(ev["verifications"]) == 1, ev["verifications"]
        assert ev["verifications"][0]["verdict"] != "", ev["verifications"][0]
        assert ev["verifications_tri"] == "computed", ev["verifications_tri"]
        assert len(ev["secretary"]) == 2, ev["secretary"]
        assert ev["secretary_tri"] == "computed", ev["secretary_tri"]
        assert set(ev["secretary"][0]) >= {"role", "duty", "decision", "reason",
                                           "basis", "fail_open"}, sorted(ev["secretary"][0])
        assert ev["store_problems"] == [], ev["store_problems"]


def test_evidence_negative_control_catches_a_column_swallowing_its_tri() -> None:
    """负控（Evidence）：三态不逐栏读（只读整面的 `tri`）⇒ 必须报出来。"""
    shell = 'const t = ev.tri;\n'
    assert _read_problems("Evidence", shell, ("statements_tri",)) == [
        "Evidence 页没有读 statements_tri"]
    assert _read_problems("Evidence", shell, PAGE_KEYS["Evidence"]), "少读键却没报"


# ====================================================================== 4 Artifacts
def test_artifacts_page_reads_the_seven_columns(artifacts_ws: pathlib.Path,
                                                tmp_path: pathlib.Path) -> None:
    """Artifacts：真读数（台账 5 行 / 交接 1 / 验收 3 / 六件 6 / 任务 1）· 空态 · 三态。"""
    text = _page_text("Artifacts")
    assert _read_problems("Artifacts", text, PAGE_KEYS["Artifacts"]) == [], (
        _read_problems("Artifacts", text, PAGE_KEYS["Artifacts"]))
    assert _empty_state_problems("Artifacts", text, EMPTY_WORDS["Artifacts"]) == []
    assert _tri_state_problems("Artifacts", text) == []

    with _server(artifacts_ws) as base:
        code, art, _raw = _get(base, "/api/artifacts")
        assert code == 200, code
        assert art["tri"] == "computed", art
        assert len(art["ledger"]) == 5, art["ledger"]
        assert art["ledger_tri"] == "computed", art["ledger_tri"]
        assert len(art["ledger_verify"]) == 5, art["ledger_verify"]
        assert {row["status"] for row in art["ledger_verify"]} == {"ok"}, (
            "夹具刚落盘，每一条的 sha 都该对得上：" + str(art["ledger_verify"]))
        assert len(art["handoffs"]) == 1, art["handoffs"]
        assert art["handoffs"][0]["sha256"] != "", art["handoffs"][0]
        assert len(art["checks"]) == 3, art["checks"]  # 夹具样本是 3 行（真机 8 行）
        assert len(art["style"]["sections"]) == 4, art["style"]
        assert len(art["secretary"]) == 2, art["secretary"]
        assert len(art["products"]) == 6, art["products"]
        assert {p["tri"] for p in art["products"]} == {"computed"}, art["products"]
        assert art["products"][1]["lines"] == 2, art["products"][1]
        assert art["run_dir"] != "", art["run_dir"]
        assert len(art["tasks"]) == 1, art["tasks"]

    # 空态：七栏全是 not_applicable（"还没写过"），页面据各自的 tri 显示
    empty = _bare_workspace(tmp_path)
    with _server(empty) as base:
        _code, art0, _raw = _get(base, "/api/artifacts")
        assert art0["ledger_tri"] == "not_applicable", art0["ledger_tri"]
        assert art0["handoffs_tri"] == "not_applicable", art0["handoffs_tri"]
        assert art0["products_tri"] == "not_applicable", art0["products_tri"]
        assert art0["products_reason"] != "", art0["products_reason"]
        assert all(p["exists"] is False for p in art0["products"]), art0["products"]


def test_artifacts_negative_control_catches_a_page_that_hides_the_ledger_tri() -> None:
    """负控（Artifacts）：页面只读整面 tri、不读逐栏 tri ⇒ 必须报出来。"""
    shell = 'const rows = art.ledger;\n'
    assert _read_problems("Artifacts", shell, ("ledger_verify",)) == [
        "Artifacts 页没有读 ledger_verify"]
    assert _read_problems("Artifacts", shell, PAGE_KEYS["Artifacts"]), "少读键却没报"


# ====================================================================== 5 Acceptance
def test_acceptance_page_reads_the_five_criteria_and_the_cost_cap(
        artifacts_ws: pathlib.Path) -> None:
    """Acceptance：真读数（5 判据 + 5 辅助）· 三态（不给 cap_usd ⇒ 那一格 unknown）。

    这一条钉的是 `draft/74 §3.6` 第 3 行：`within_cost_cap` 在不给 `cap_usd` 时
    必须是 `unknown`（"没查成"），给了 `cap_usd` 才是 `pass`/`fail`。
    """
    text = _page_text("Acceptance")
    assert _read_problems("Acceptance", text, PAGE_KEYS["Acceptance"]) == [], (
        _read_problems("Acceptance", text, PAGE_KEYS["Acceptance"]))
    assert _empty_state_problems("Acceptance", text, EMPTY_WORDS["Acceptance"]) == []
    assert _tri_state_problems("Acceptance", text) == []

    with _server(artifacts_ws) as base:
        code, acc, _raw = _get(base, "/api/acceptance")
        assert code == 200, code
        assert acc["tri"] == "computed", acc
        assert len(acc["criteria"]) == 5, acc["criteria"]
        assert set(acc["criteria"].values()) <= {"pass", "fail", "unknown"}, acc["criteria"]
        assert acc["criteria"]["within_cost_cap"] == "unknown", (
            "不给 cap_usd ⇒「在成本上限内」那一格是没查成，不是通过：" + str(acc["criteria"]))
        assert "within_cost_cap" in acc["reason"] or "没查成" in acc["reason"], acc["reason"]
        assert len(acc["auxiliary"]) == 5, acc["auxiliary"]
        assert acc["auxiliary"]["task_rows"] == "1", acc["auxiliary"]

        # 给了 cap_usd ⇒ 那一格真的算出结论（正控：三态不是恒 unknown）
        _code, capped, _raw = _get(base, "/api/acceptance?cap_usd=0.5")
        assert capped["criteria"]["within_cost_cap"] in ("pass", "fail"), capped["criteria"]

    # 查询参数的名字在 api.ts 那一层（页面用的是 TS 那边的 `capUsd`）
    api_ts = (UI_SRC / "api.ts").read_text(encoding="utf-8")
    assert '"cap_usd"' in api_ts, "api.ts 没把 capUsd 拼成后端的 ?cap_usd="
    # 这一页的三态落点：`unknown` 必须被说成"没查成（不是通过）"，不许写成"通过"
    assert "没查成（不是通过）" in _strip_js_comments(text), (
        "Acceptance 页没有把 unknown 那一档说成「没查成（不是通过）」")


def test_acceptance_negative_control_catches_a_page_that_writes_unknown_as_pass() -> None:
    """负控（Acceptance）：页面里把 `unknown` 写成"通过" ⇒ `_page_reads` 之外还得靠文案。"""
    shell = 'const rows = acc.criteria;\n'
    assert _read_problems("Acceptance", shell, ("auxiliary",)) == [
        "Acceptance 页没有读 auxiliary"]
    # 空态文案与三态落点都得在
    assert _empty_state_problems("Acceptance", shell, EMPTY_WORDS["Acceptance"])
    assert _tri_state_problems("Acceptance", shell)


# ====================================================================== 6 Machine
def test_machine_page_reads_the_probers_mathlib_and_settings(
        artifacts_ws: pathlib.Path) -> None:
    """Machine：真读数（探测结论 / Mathlib / 设置三段）· 三态（key 只有布尔位）。"""
    text = _page_text("Machine")
    assert _read_problems("Machine", text, PAGE_KEYS["Machine"]) == [], (
        _read_problems("Machine", text, PAGE_KEYS["Machine"]))
    assert _empty_state_problems("Machine", text, EMPTY_WORDS["Machine"]) == []
    assert _tri_state_problems("Machine", text) == []

    with _server(artifacts_ws) as base:
        code, mac, _raw = _get(base, "/api/machine")
        assert code == 200, code
        assert mac["tri"] in ("computed", "unreadable"), mac["tri"]
        assert set(mac["provers"]) >= {"checked", "available", "available_names",
                                      "looked_in", "probe_errors", "reason"}, sorted(mac["provers"])
        assert mac["provers"]["checked"] is True, mac["provers"]
        assert set(mac["mathlib"]) >= {"checked", "root", "reason"}, sorted(mac["mathlib"])
        settings = mac["settings"]
        assert set(settings) >= {"path", "exists", "toolchain", "model", "workspace"}, sorted(settings)
        assert settings["model"]["configured"] is False, settings["model"]
        # 判据的机器读数侧："key 只写不读"在这里的形态是"读数里没有真 key"
        # （`tests/test_webui_readers.py` 有一条逐字符断言，这里只钉"有这一栏"）
        assert "api_key" in settings["model"], settings["model"]
        assert mac["settings_tri"] in ("not_applicable", "unreadable"), mac["settings_tri"]
        assert mac["lean_ready"] is False or mac["lean_ready"] is None, mac["lean_ready"]


def test_machine_negative_control_catches_a_page_that_drops_the_source_column() -> None:
    """负控（Machine）：页面不读"从哪一档找到的"（`provers`）⇒ 必须报出来。"""
    shell = 'const ok = mac.lean_ready;\n'
    assert _read_problems("Machine", shell, ("provers",)) == ["Machine 页没有读 provers"]
    assert _read_problems("Machine", shell, PAGE_KEYS["Machine"]), "少读键却没报"


# ====================================================================== 反真空
def test_every_page_is_registered_and_every_page_source_exists() -> None:
    """反真空：九页都在这一组里，源码都在盘上，而且每页都用了 TriState。

    没有这一条，"页面改名/被删"会让上面几条以 skip 的形态静默变绿 —— 绿得毫无内容。
    2026-10-12：`Help` 页刻意不调端点（它是说明页），但"在盘上 + 不自己 fetch"
    这两条照旧核 —— 空端点表是声明，不是免检。
    """
    expected = {"Home", "Run", "Evidence", "Artifacts", "Acceptance", "Machine",
                "Budget", "Live", "Help"}
    assert set(PAGES) == expected, sorted(PAGES)
    assert set(PAGE_KEYS) == expected, sorted(PAGE_KEYS)
    for name in sorted(expected):
        path = UI_SRC / "pages" / f"{name}.tsx"
        assert path.is_file(), f"{path} 不在盘上"
        body = path.read_text(encoding="utf-8")
        if name != "Help":
            # Help 页是一张静态说明页（没有读数要画三态）；其余每一页都必须在源码里
            # 出现 `TriState`，否则"没查成"与"读到 0"在那一页上会长成一个样子。
            assert TRI_TOKEN in body, f"{name} 页没有用 {TRI_TOKEN}"
        # 页面必须走 api.ts 的那一层，不许自己 fetch 一个裸地址（端点的唯一出口）
        assert "fetch(" not in _strip_js_comments(body), (
            f"{name} 页自己 fetch 了 —— 端点必须只从 api.ts 走")


def test_the_run_index_endpoint_is_really_in_the_route_table() -> None:
    """反真空（裁定 O2 的消费端）：`/api/run-index` 在总表里，且 handler 找得到。"""
    assert "/api/run-index" in routes.patterns(), routes.patterns()
    name, params = routes.match("GET", "/api/run-index") or ("", {})
    assert name == "handle_run_index", name
    assert params == {}, params
    from agentflow import webui as W

    assert hasattr(W.WebHandler, name), "handler 不在 WebHandler 上"
    assert routes.match("GET", "/api/run/a/b") is None, "`{sid}` 只许匹配一段路径"
    assert routes.match("POST", "/api/run-index") is None, "它是 GET，不是 POST"


# ====================================================================== 装配（裁定 1a）
# B 线交付的是"钩子 + 广播器"（`sse.attach/detach/begin_serving/close_all`），
# 生产路径上得有人接 —— 接的地方是 `webui/server.py` 的 `serve()` 与 `run()`。
# 下面两条守的就是那一次装配：它既不能没接（流永远沉默），也不能接重（回调叠加）。

def _stream_frames(resp: Any, *, want: int, timeout: float = 8.0) -> list[tuple[str, str]]:
    """读 SSE 帧：返回 `[(kind, data), ...]`（读够 `want` 帧或超时收手）。

    这是本文件自己的小读端（B 的 `tests/test_webui_sse.py` 里有它自己那一份）：
    走真实 HTTP、按线上的 `event:` / `data:` 两行解析，于是"服务端真的发出去了"
    这件事不靠猜。
    """
    out: list[tuple[str, str]] = []
    buf = b""
    resp.fp.raw._sock.settimeout(timeout)  # noqa: SLF001 - 超时收手，判据不许挂死
    deadline = time.monotonic() + timeout
    while len(out) < want and time.monotonic() < deadline:
        try:
            chunk = resp.fp.read1(4096)  # noqa: SLF001
        except (OSError, TimeoutError):
            break
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            raw, buf = buf.split(b"\n\n", 1)
            kind = ""
            data = ""
            for line in raw.decode("utf-8", errors="replace").splitlines():
                if line.startswith("event: "):
                    kind = line[len("event: "):]
                elif line.startswith("data: "):
                    data = line[len("data: "):]
            if kind:
                out.append((kind, data))
    return out


@contextmanager
def _live_server(root: pathlib.Path, *, heartbeat_sec: float = 0.2) -> Iterator[str]:
    """起一个真的在跑的 web 服务（`serve()` + 后台 `serve_forever`），返回 `host:port`。"""
    from agentflow import webui as W
    from agentflow.webui import sse

    sse.close_all()   # 先把上一代关掉，于是下面那条"serve() 开了一代"说明得了问题
    sse.detach()
    srv = W.serve(root, host="127.0.0.1", port=0, heartbeat_sec=heartbeat_sec)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        sse.close_all()          # 先关流（否则开着的流会占住请求线程）
        srv.shutdown()
        srv.server_close()
        sse.detach()
        thread.join(timeout=5.0)


def test_serve_opens_a_broadcaster_generation_and_attaches_the_four_hooks(
        tmp_path: pathlib.Path) -> None:
    """正控（裁定 1a 的装配）：`serve()` 开一代广播器，并把四个写路径钩子接上。

    怎么读"接上了"：`detach()` 是公开入口（`sse.__all__` 里有它），它报出撤掉了哪
    几个槽 —— 四个槽都非空就说明 `serve()` 真的调过 `attach()`。这里不用私有名
    （`sse._ATTACHED`）读它，免得判据钉在两个模块之间的实现细节上。
    """
    from agentflow import webui as W
    from agentflow.webui import sse

    root = tmp_path / "wired"
    root.mkdir()
    sse.close_all()
    sse.detach()
    assert sse.serving() is False, "前提：这一代是关着的（否则下面说明不了问题）"
    srv = W.serve(root, host="127.0.0.1", port=0, heartbeat_sec=0.2)
    try:
        assert sse.serving() is True, "serve() 没有开一代广播器（心跳与流循环都靠它）"
        assert sse.default_broadcaster().heartbeat_sec == pytest.approx(0.2), (
            "serve(heartbeat_sec=...) 没有透传到广播器上")
        got = sse.detach()
        assert got["detached"] == ("answered", "append", "question", "stop"), got
        assert sse.detach() == {"detached": ()}, "detach() 必须幂等"
    finally:
        sse.close_all()
        srv.server_close()
        sse.detach()


def test_a_session_write_reaches_the_stream_through_serve(tmp_path: pathlib.Path) -> None:
    """端到端（"盘上新增 ⇒ 流里出现"）：经由 `serve()` 起的服务，写一次会话就走通。

    两条断言缺一不可：
    - 正控：`SS.append(...)` 之后流里出现 `state` 帧（装配真的通了）；
    - 负控（红前绿后）：`detach()` 之后同样写一次，流里只剩心跳、没有 `state`
      （证明上一条不是因为别的东西在发）。
    """
    from agentflow import webui as W
    from agentflow.webui import sse

    del W
    root = tmp_path / "live"
    root.mkdir()
    sid = "live"
    with _live_server(root) as base:
        conn = http.client.HTTPConnection(base, timeout=10)
        conn.request("GET", "/api/stream")
        resp = conn.getresponse()
        try:
            assert resp.status == 200, resp.status
            assert (resp.getheader("Content-Type") or "").startswith("text/event-stream"), (
                resp.getheader("Content-Type"))
            SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "装配判据"},
                      sid=sid)
            frames = _stream_frames(resp, want=1, timeout=8.0)
            kinds = [k for k, _d in frames]
            assert "state" in kinds, f"写了一次会话，流里却没有 state：{kinds}"
            payload = next(d for k, d in frames if k == "state")
            assert "snapshot" in payload, payload[:200]
        finally:
            resp.close()
            conn.close()

        # 负控：撤掉钩子之后，同样的写操作不再发 state（只会有心跳）
        sse.detach()
        conn2 = http.client.HTTPConnection(base, timeout=10)
        conn2.request("GET", "/api/stream")
        resp2 = conn2.getresponse()
        try:
            SS.append(root, {"kind": "agent_step", "role": "M", "index": 0,
                             "shape": "fs.write"}, sid=sid)
            later = _stream_frames(resp2, want=1, timeout=2.0)
            assert all(k == "heartbeat" for k, _d in later), (
                f"detach() 之后还在发事件：{[k for k, _d in later]}")
        finally:
            resp2.close()
            conn2.close()

# ====================================================================== 设置窗口的回填（R81）

def test_the_settings_panel_prefills_from_the_reading() -> None:
    """判据（业主 2026-10-13：「设置面板启动后应该同步设置文件里的参数，不然空空的就像啥
    都没设置过一样」）：设置窗口每一格的初值来自 `GET /api/machine` 的 `settings` 三段。

    按源码读（与这一组其余判据同一条路）：页面是客户端渲染的，Python 判据看不到 DOM，
    但这件事实在源码里是**结构可见**的 —— 输入框的 `value` 必须落到"读数 ⊕ 用户输入"
    这个表达式上，而不是恒为空串。

    两向都钉：
    - 正向：`value` 用 `presetOf(settings, …)`（读数为底）、存在 `currentOf` 取现值；
    - 反向：`model.api_key` **不许**回填（读数恒为 `***`，回填等于把 `***` 写回文件）。
    """
    src = _page_text("Machine")
    assert "presetOf(settings, field.key)" in src, "设置窗口的输入框没有按读数回填"
    assert "function currentOf(" in src and "function presetOf(" in src, "取值帮手不在"
    assert "盘上没设过" in src, "占位符里没写清这一格是空在哪一边"
    i = src.index("function presetOf(")
    body = src[i:i + 400]
    assert 'key === "model.api_key"' in body and 'return ""' in body, body
