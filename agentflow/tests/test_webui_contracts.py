# -*- coding: utf-8 -*-
"""Web 端契约判据（裁定 S1：四条收在这一个文件里）。

## 这一组守什么

`draft/75` §1 的契约表是唯一来源，本文件把"表 ↔ 代码"钉死。四条名字层判据
（纯 Python、正则级、进常规全量），每条都带正控与至少一条负控：

| 判据 | 查什么 | 落点 |
|---|---|---|
| A 端点对齐 | `ui/src/api.ts` 的路径字面量集合 == `webui/routes.py` 的 `ROUTES` 里 `/api/*` 与 `/answer` | `test_a_*` |
| B 事件对齐 | `ui/src/sse.ts` 的 kind 集合 == 后端 `webui/sse.py` 的 `EVENT_KINDS` | `test_b_*` |
| C 类型字段对齐 | `ui/src/types.ts` 每个接口的键集合 == 后端在夹具工作区上真读出来的键集合 | `test_c_*` |
| D 路由对齐 | `ui/src/main.tsx` 的路由集合 == `draft/75 §1.4` 的 C4 表；页面用到的端点 ∈ ROUTES、kind ∈ KINDS | `test_d_*` |

外加本批（W0）新增的几条：静态路由与目录穿越、`/api/*` 未知不吐 HTML、
两个生成物的新鲜度（手改生成物必红）、拆包后公开面不变、两个 CLI 开关。

## 为什么负控要单独写成一条

"改前能红"不是一句形容词：每条判据都必须有一个输入，让它在不变更盘上任何
文件的前提下报出问题。做法与 `tests/test_reading_map.py` 的负控同族 ——
把检查逻辑抽成纯函数（`_endpoint_alignment_problems` 等），正控喂真文件、
负控喂改坏的字符串。少了负控，正则哪天失配（比如表格换了写法）判据会以
"一条都没解析到"的形态静默变绿。

## W0 的两处实况（不是"没查成"，是已知的欠账）

- 判据 B 的后端一半（`webui/sse.py` 的 `EVENT_KINDS`）要到 W2 才落地，所以
  正控 skip 并在理由里写明；B 的比对逻辑本身由负控证明是接上的。
- 判据 C 只核后端此刻真给得全的那些接口；`Checkpoint` / `CheckpointSpend` /
  `WriteResult` 本批没有 reader 或没有生产者，逐条登记在 `_W0_UNCHECKED_TYPES` 与各模块自己的 `UNCHECKED_TYPES` 里
  （并有一条反向断言：一旦它们真能被读出来，那份登记就过期了，判据会红）。
"""

from __future__ import annotations

import http.client
import pathlib
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from agentflow import sessions as SS
from agentflow import userio as U
from agentflow import webui as W
from agentflow.store import Store
from agentflow.web import emit_theme, emit_types
from agentflow.webui import routes
from agentflow.webui.state import _read_report

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
#: 前端工程根。
UI = REPO / "ui"
API_TS = UI / "src" / "api.ts"
SSE_TS = UI / "src" / "sse.ts"
TYPES_TS = UI / "src" / "types.ts"
MAIN_TSX = UI / "src" / "main.tsx"
INDEX_HTML = UI / "index.html"
APP_CSS = UI / "src" / "theme" / "app.css"
THEME_CSS = UI / "src" / "theme" / "generated" / "theme.css"
#: 契约表 C4 的出处（`draft/75 §1.4`）—— 判据 D 直接读那张表，不另抄一份。
DRAFT_75 = REPO.parent / "draft" / "75-Web端伪代码（逐前端文件·互相对齐）.md"

#: 判据 D 允许的例外：页面里出现、而后端还没有的端点。
#: 来源是各子表模块自己的 `PENDING_ENDPOINTS`（B/C 线在自己的文件里登记与撤销），
#: 主控只在这里读它 —— 这样"撤销一条豁免"不需要改 A 线的判据（`draft/78 §3` 的零交口径）。
#: 反向断言（`test_d_the_endpoint_allowlist_is_not_stale`）要求：后端一旦落地同名路由，
#: 那条登记就必须删掉 —— 一张永不生效的豁免表会腐烂。
def _pending_endpoints() -> dict[str, str]:
    """把三个子表模块登记的"还没落地的端点"合起来（缺失/写错形状都算空）。"""
    out: dict[str, str] = {}
    for name in ("readers", "sse", "writes"):
        mod = getattr(__import__("agentflow.webui", fromlist=[name]), name, None)
        table = getattr(mod, "PENDING_ENDPOINTS", None)
        if isinstance(table, dict):
            out.update({str(k): str(v) for k, v in table.items()})
    return out


#: 判据 C 逐条登记的欠账：这些接口在 `types.ts` 里，但没有真读数可对账。
#: 同样是"模块自己登记"：任何模块里的 `UNCHECKED_TYPES`（dict）都会并进来。
_W0_UNCHECKED_TYPES = {
    "Checkpoint": "检查点文件由 agent_loop 写；读它的适配器在 W1 的 readers.py",
    "CheckpointSpend": "同上（Checkpoint 的子结构）",
    "WriteResult": "写面的统一回执；生产者（/api/stop · /api/submit · /api/settings）在 W3/W4",
}


def _unchecked_types() -> dict[str, str]:
    """判据 C 的欠账名单 = W0 那份 + 三个模块各自的 `UNCHECKED_TYPES`。"""
    out = dict(_W0_UNCHECKED_TYPES)
    for name in ("state", "readers", "writes"):
        mod = getattr(__import__("agentflow.webui", fromlist=[name]), name, None)
        table = getattr(mod, "UNCHECKED_TYPES", None)
        if isinstance(table, dict):
            out.update({str(k): str(v) for k, v in table.items()})
    return out


def _checked_types() -> tuple[str, ...]:
    """判据 C 受核对的接口 = W0 那 10 个 + 三个模块各自登记的 `CHECKED_TYPES`。"""
    out = list(_W0_CHECKED_TYPES)
    for name in ("state", "readers", "writes"):
        mod = getattr(__import__("agentflow.webui", fromlist=[name]), name, None)
        out += [str(x) for x in (getattr(mod, "CHECKED_TYPES", ()) or ())]
    seen: list[str] = []
    for one in out:
        if one not in seen:
            seen.append(one)
    return tuple(seen)


#: 判据 C 受核对的接口（W0 那批；顺序即报错信息的顺序）。
_W0_CHECKED_TYPES = (
    "OptionRow", "OrphanGroup", "OrphanSummary", "StateSnapshot", "SessionRow",
    "PendingQuestion", "RunRow", "OrphanRow", "LedgerReading", "ReportReading",
)


# ====================================================================== 读盘帮手
def _ui_text(path: pathlib.Path) -> str:
    """读一个前端源文件；不在盘上就 skip（理由里写明"前端骨架尚未落地"）。"""
    if not path.is_file():
        pytest.skip(f"前端骨架尚未落地：{path.relative_to(REPO)} 不在盘上")
    return path.read_text(encoding="utf-8")


def _strip_js_comments(text: str) -> str:
    """去掉 `//` 与 `/* */` 注释（字符串字面量里的斜杠不算注释）。

    为什么必须先剥注释：判据要在"真字面量"上比对，而文件头那些说明里会提到
    端点名字（`` `/api/evidence` 在 W1 落地 `` 之类）。不剥注释的话，一句说明
    就会被当成"前端声明了这个端点"。
    """
    out: list[str] = []
    i, n = 0, len(text)
    quote = ""
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


#: 一个字符串字面量（单/双引号/模板）：只收以 `/` 开头的。
_LITERAL = re.compile(r"[\"'`](/[^\"'`\n]*)[\"'`]")
#: 模板插值 `${x}` ⇒ 契约表里的 `{x}`（于是 `/api/run/${sid}` 与 `/api/run/{sid}` 可比）。
_INTERP = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _literals(text: str) -> set[str]:
    """源码里所有以 `/` 开头的字符串字面量（剥掉注释后）。"""
    out: set[str] = set()
    for m in _LITERAL.finditer(_strip_js_comments(text)):
        out.add(_INTERP.sub(r"{\1}", m.group(1)))
    return out


def _endpoint_literals(text: str) -> set[str]:
    """端点字面量：`/api/*` 与 `/answer`（契约表 C1 里只有这两族）。"""
    return {s for s in _literals(text) if s.startswith("/api/") or s == "/answer"}


# ====================================================================== A 端点对齐
def _endpoint_alignment_problems(front: set[str], back: set[str]) -> list[str]:
    """前端声明的端点集合 vs 后端路由表的端点集合（两个方向都要报）。"""
    problems: list[str] = []
    extra = sorted(front - back)
    missing = sorted(back - front)
    if extra:
        problems.append(f"前端声明了后端没有实现的端点：{extra}")
    if missing:
        problems.append(f"后端有端点而前端没声明（api.ts 少了一行）：{missing}")
    return problems


def test_a_the_frontend_and_the_route_table_declare_the_same_endpoints() -> None:
    """正控（A 端点对齐）：`api.ts` 的路径字面量 == `ROUTES` 的 `/api/*` 与 `/answer`。

    这一条就是"后端删掉一个端点、前端还在调它"这类漂移的唯一机器读数。
    """
    front = _endpoint_literals(_ui_text(API_TS))
    back = set(routes.api_paths())
    assert front, "api.ts 里一个端点字面量都没解析到 ⇒ 判据没接上（正则失配？）"
    assert back, "ROUTES 里一个 API 端点都没有 ⇒ 表结构变了"
    assert _endpoint_alignment_problems(front, back) == [], (
        f"前端 {sorted(front)} vs 后端 {sorted(back)}")
    # 反真空：W0 至少要有读数那一个与写回答那一个在两边同时存在
    assert "/api/state" in front and "/answer" in front, sorted(front)


def test_a_negative_control_catches_a_deleted_endpoint() -> None:
    """负控（A）：后端少一个端点 ⇒ 判据必须点名"前端多出一个没实现的端点"。"""
    front = {"/api/state", "/answer"}
    back = {"/answer"}
    problems = _endpoint_alignment_problems(front, back)
    assert problems and "/api/state" in problems[0], problems
    # 反过来：前端少一个也要报（两个方向都不许静默）
    problems2 = _endpoint_alignment_problems({"/answer"}, front)
    assert problems2 and "/api/state" in problems2[0], problems2
    # 反真空：两边一样时不许报
    assert _endpoint_alignment_problems(front, set(front)) == []


def test_a_comment_mentions_are_not_counted_as_endpoints() -> None:
    """负控（A 的解析器）：注释里提到的端点名字不许被当成"前端声明了它"。"""
    src = '// 还欠 `/api/evidence` 与 /api/artifacts\nconst A = "/api/state";\n'
    assert _endpoint_literals(src) == {"/api/state"}, _endpoint_literals(src)
    doc = '/* 说明：/api/machine 在 W1 */\nconst B = "/answer";\n'
    assert _endpoint_literals(doc) == {"/answer"}, _endpoint_literals(doc)


def test_a_the_subtables_really_reach_the_composed_route_table(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（接缝）：往 `readers.ROUTES` 里塞一个 api.ts 没有的路径 ⇒ 必红。

    `draft/78 §3` 的三条接缝要求总表是 `自有 + READER_ROUTES + WRITE_ROUTES` 拼出来的。
    这条负控证明拼接是真的（子表的改动会进总表、A 条会当场点出来），而不是只在导入
    那一刻拼过一次就再没人管 —— 也证明 B/C 线加端点时改的是自己的文件。
    """
    from agentflow.webui import readers, writes

    front = _endpoint_literals(_ui_text(API_TS))
    assert _endpoint_alignment_problems(front, set(routes.api_paths())) == []

    ghost = (("GET", "/api/ghost", "handle_ghost"),)
    composed = routes.compose(routes._OWN, tuple(readers.ROUTES) + ghost,
                              tuple(writes.ROUTES))
    problems = _endpoint_alignment_problems(front, set(routes.api_paths(composed)))
    assert problems and "ghost" in problems[0], problems

    # 同一条公式把真表也拼得出来（否则上面那条负控实验的不是真公式）
    assert routes.compose(routes._OWN, tuple(readers.ROUTES),
                          tuple(writes.ROUTES)) == routes.ROUTES
    # 真表不受影响：`/api/ghost` 只在实验里存在
    assert "/api/ghost" not in routes.patterns()
    monkeypatch.setattr(routes, "ROUTES", composed)
    assert "/api/ghost" in routes.patterns(), "换掉总表之后表里就该有它"


def test_a_the_seam_names_are_all_in_place() -> None:
    """正控（接缝）：`draft/78 §3` 点名的接缝名字都在各自的模块上，且形状对。

    为什么不再断言"`readers.ROUTES` 是空元组 / `readers.type_decls()` 是空串"：
    那是 W0 当时的形态，而 B/C 线的交付恰恰是往那两个名字里加东西 ——
    把"还没填"写成断言，等于让下游一动手就红（这条我实测撞过：B 线一落地就必然红）。
    现在钉的是不随施工阶段变化的形状：子表是三元组、每个名字都真的进了总表、
    欠账台账不许与已声明的东西自相矛盾。
    """
    from agentflow.webui import readers, sse, state, writes

    for mod in (readers, writes, state):
        assert isinstance(getattr(mod, "type_decls")(), str), mod.__name__
    for mod in (readers, writes, sse):
        table = getattr(mod, "ROUTES", None)
        if table is None:
            continue
        assert isinstance(table, tuple), mod.__name__
        for row in table:
            assert isinstance(row, tuple) and len(row) == 3, (mod.__name__, row)
            assert row[0] in ("GET", "POST"), (mod.__name__, row)
            assert row[2] in routes.handler_names(), (
                f"{mod.__name__} 的子表登记了 {row[2]}，但它没进总表 "
                "（`routes.compose` 少拼了一段？）")
    assert isinstance(sse.EVENT_KINDS, tuple), sse.EVENT_KINDS
    assert writes.ROUTES == (("POST", "/answer", "handle_answer"),), writes.ROUTES
    assert writes.ROUTES[0] in routes.ROUTES, "写面子表必须真的进了总表"
    # 生成物确实由三张子表拼出来（而不是谁在生成器里另写了一份清单）
    from agentflow.web import emit_types

    assert emit_types._subtable_texts() == (state.type_decls(),
                                            readers.type_decls(),
                                            writes.type_decls())
    assert state.type_decls().strip(), "state 那一份不该是空的（快照家族的接口在它那）"
    assert "WriteResult" in writes.type_decls()
    # 欠账清单住在模块里，不住在生成器里；而且不许与已声明的东西自相矛盾：
    # 一个接口若已经出现在本模块的 type_decls() 里，就不该还挂在欠账表上（那是腐烂的登记）。
    assert all(len(row) == 2 for row in readers.MISSING_TYPES), readers.MISSING_TYPES
    declared_by_readers = readers.type_decls()
    stale = [name for name, _why in readers.MISSING_TYPES if f"interface {name}" in declared_by_readers]
    assert not stale, f"这些接口已经由 readers 声明了，却还挂在 MISSING_TYPES 上：{stale}"
    todo = emit_types._missing_text()
    for name, _why in readers.MISSING_TYPES:
        assert f"// TODO {name}：" in todo, name


# ====================================================================== B 事件对齐
def _backend_event_kinds() -> tuple[str, ...] | None:
    """后端的事件词表（`webui/sse.py` 的 `EVENT_KINDS`）。

    W0 的实况：那个模块在（接缝先落地），但词表还是空的 —— W2 才填广播器与词表。
    "模块不在"与"词表还是空的"都返回 None，由调用方 skip；区别只写在 skip 理由里。
    """
    import importlib

    try:
        mod = importlib.import_module("agentflow.webui.sse")
    except ImportError:
        return None
    kinds = tuple(getattr(mod, "EVENT_KINDS", ()) or ())
    return kinds or None


def _frontend_event_kinds(text: str) -> set[str]:
    """`sse.ts` 里 `KINDS` 那一行的取值集合。"""
    m = re.search(r"KINDS\s*=\s*\[(.*?)\]", _strip_js_comments(text), re.S)
    if m is None:
        return set()
    return set(re.findall(r"[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']", m.group(1)))


def _event_alignment_problems(front: set[str], back: tuple[str, ...]) -> list[str]:
    """前端注册的 kind 集合 vs 后端事件词表（两个方向都要报）。"""
    problems: list[str] = []
    extra = sorted(front - set(back))
    missing = sorted(set(back) - front)
    if extra:
        problems.append(f"前端注册了后端不发的 kind：{extra}")
    if missing:
        problems.append(f"后端会发而前端没注册的 kind：{missing}")
    return problems


def test_b_the_frontend_registers_exactly_the_backend_event_kinds() -> None:
    """正控（B 事件对齐）：`sse.ts` 的 kind 集合 == 后端 `EVENT_KINDS`。

    W0 的实况：后端那一半（`webui/sse.py` 的词表与广播器）要到 W2 才填 ⇒ 这条 skip，
    理由写在这里而不是静默算过。
    """
    front = _frontend_event_kinds(_ui_text(SSE_TS))
    assert front, "sse.ts 里 KINDS 一个取值都没解析到 ⇒ 判据没接上"
    back = _backend_event_kinds()
    if back is None:
        pytest.skip("后端 webui/sse.py 在，但 EVENT_KINDS 还是空的（W0 只留接缝，"
                    "词表与广播器在 W2）—— 前端已注册 KINDS，后端一填这条自动生效"
                    "（B 的比对逻辑由负控证明是接上的）")
    assert _event_alignment_problems(front, back) == [], (
        f"前端 {sorted(front)} vs 后端 {sorted(back)}")


def test_b_negative_control_catches_a_kind_only_one_side_knows() -> None:
    """负控（B）：后端加一个 kind 而前端没注册 / 前端注册了后端不发的 ⇒ 必红。"""
    front = {"state", "question", "answered", "checkpoint", "stop", "heartbeat"}
    back = ("state", "question", "answered", "checkpoint", "stop", "heartbeat")
    assert _event_alignment_problems(front, back) == []
    problems = _event_alignment_problems(front, back + ("progress",))
    assert problems and "progress" in problems[0], problems
    problems2 = _event_alignment_problems(front | {"ghost"}, back)
    assert problems2 and "ghost" in problems2[0], problems2


def test_b_the_fallback_path_symbols_are_still_there() -> None:
    """正控（降级路径）：`sse.ts` 里 `EventSource` / `since` / `setInterval` 都在。

    `draft/73` §2.1 把这三个符号定成"SSE 真的接了"的最小机器读数：
    少了 `setInterval`，断流之后页面上的读数就永远停住，而没有任何东西会响。
    """
    text = _ui_text(SSE_TS)
    for symbol in ("EventSource", "since", "setInterval"):
        assert symbol in text, f"sse.ts 里没有 {symbol}"


# ====================================================================== C 类型字段对齐
_INTERFACE = re.compile(r"^export interface ([A-Za-z_][A-Za-z0-9_]*)\s*\{", re.M)
_FIELD = re.compile(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)\??\s*:", re.M)


def _parse_interfaces(text: str) -> dict[str, set[str]]:
    """`types.ts` 里每个接口的键集合（字段一行一个，按行解析）。"""
    out: dict[str, set[str]] = {}
    for m in _INTERFACE.finditer(text):
        body = text[m.end():]
        end = body.find("\n}")
        body = body[:end if end != -1 else len(body)]
        out[m.group(1)] = {f.group(1) for f in _FIELD.finditer(body)}
    return out


def _type_alignment_problems(interfaces: dict[str, set[str]],
                             backend: dict[str, set[str]]) -> list[str]:
    """`types.ts` 的键集合 vs 后端真读出来的键集合（含两份名单的反向断言）。"""
    problems: list[str] = []
    for name in _checked_types():
        if name not in interfaces:
            problems.append(f"types.ts 里没有接口 {name}（C3 契约要求它）")
            continue
        if name not in backend:
            problems.append(f"夹具工作区上没读出 {name} 的键 ⇒ 这条判据没有落脚点")
            continue
        extra = sorted(interfaces[name] - backend[name])
        missing = sorted(backend[name] - interfaces[name])
        if extra:
            problems.append(f"{name}：types.ts 多了后端没有的键 {extra}")
        if missing:
            problems.append(f"{name}：后端有而 types.ts 没有的键 {missing}")
    for name in sorted(interfaces):
        if name not in _checked_types() and name not in _unchecked_types():
            problems.append(f"{name}：既不在受核对名单、也不在欠账名单 —— "
                            "前端凭空多了一个没人核的接口")
    for name in sorted(_unchecked_types()):
        if name in backend:
            problems.append(f"{name}：它登记为「本批无读数」，而夹具上竟读出了它的键 ⇒ "
                            "登记过期，请把它挪进受核对名单")
    return problems


def _fixture_workspace(tmp: pathlib.Path) -> pathlib.Path:
    """造一份"每个受核对接口都有真读数"的最小工作区（纯夹具，不碰真工作区）。

    为什么要这么全：判据 C 是"键集合相等"，任一栏读不出来（例如台账只有在
    `data/events.jsonl` 存在时才有 `tables_note`）都会让等式变成假红。所以夹具
    把每一条读数都造出来，并在正控里断言"受核对的每个接口都拿到了读数"。
    """
    root = tmp / "ws"
    root.mkdir()
    Store(root).init()
    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "契约夹具",
                     "ts": "2026-10-07T00:00:00+08:00"}, sid="t")
    SS.append(root, {"kind": "llm_call", "role": "M", "ok": True, "usd": 0.25,
                     "tokens_in": 3, "tokens_out": 4}, sid="t")
    SS.append(root, {"kind": "agent_step", "role": "M", "index": 0, "shape": "fs.write",
                     "payload": {"path": "out/review/REPORT.md"},
                     "result": {"ok": True}}, sid="t")
    SS.append(root, {"kind": "agent_run_end", "role": "M", "stop_reason": "final",
                     "steps": 1, "final": "写完了", "final_chars": 3}, sid="t")
    U.ask_user(root, role="M", question="契约夹具的问题", timeout_sec=0, sid="t",
               options=({"label": "甲", "description": "第一档"},))
    # 轮次之外的一条零散事件（另一段会话，前面没有 agent_run_start）：
    # 它撑起 OrphanRow / OrphanGroup 两条读数。
    SS.append(root, {"kind": "task_end", "role": "A", "outcome": "ok"}, sid="solo")
    return root


def _backend_keys(root: pathlib.Path) -> dict[str, set[str]]:
    """后端在这个工作区上真读出来的键集合（一栏一个接口）。"""
    snap = W.snapshot(root)
    out: dict[str, set[str]] = {"StateSnapshot": set(snap)}
    if snap["sessions"]:
        out["SessionRow"] = set(snap["sessions"][0])
    if snap["pending_questions"]:
        q = snap["pending_questions"][0]
        out["PendingQuestion"] = set(q)
        if q["options"]:
            out["OptionRow"] = set(q["options"][0])
    if snap["runs"]:
        out["RunRow"] = set(snap["runs"][0])
    if snap["orphans"]:
        out["OrphanRow"] = set(snap["orphans"][0])
    groups = (snap["orphan_summary"] or {}).get("groups") or []
    if groups:
        out["OrphanGroup"] = set(groups[0])
    out["OrphanSummary"] = set(snap["orphan_summary"] or {})
    out["LedgerReading"] = set(snap["ledger"] or {})
    _read_report(root)
    out["ReportReading"] = {"status", "text"}
    return out


def test_c_the_generated_types_match_what_the_backend_really_reads(
        tmp_path: pathlib.Path) -> None:
    """正控（C 类型字段对齐）：`types.ts` 的键集合 == 后端在夹具上真读出来的键集合。

    反向（TS 多了后端没有的键）与正向（后端多了一个键而 TS 没加）都要红 ——
    两个方向都是漂移，而漂移的方向决定读的人会怎么错。
    """
    interfaces = _parse_interfaces(_ui_text(TYPES_TS))
    assert len(interfaces) >= 10, f"只解析出 {len(interfaces)} 个接口 ⇒ 解析器可能失配"
    root = _fixture_workspace(tmp_path)
    backend = _backend_keys(root)
    missing_readings = [n for n in _checked_types() if n not in backend]
    assert not missing_readings, f"夹具没造出这些读数：{missing_readings}"
    assert _type_alignment_problems(interfaces, backend) == [], (
        _type_alignment_problems(interfaces, backend))


def test_c_negative_controls_catch_both_directions(
        tmp_path: pathlib.Path) -> None:
    """负控（C）：后端多一个键 / TS 多一个键 / TS 少一个接口 ⇒ 三种都要报。"""
    interfaces = _parse_interfaces(_ui_text(TYPES_TS))
    backend = _backend_keys(_fixture_workspace(tmp_path))
    assert _type_alignment_problems(interfaces, backend) == []

    # ① 后端加一个键（例如 tasks 多一列）而 types.ts 没加
    grown = {k: set(v) for k, v in backend.items()}
    grown["RunRow"].add("brand_new_column")
    problems = _type_alignment_problems(interfaces, grown)
    assert problems and "brand_new_column" in problems[0], problems

    # ② TS 多了后端没有的键
    doctored = {k: set(v) for k, v in interfaces.items()}
    doctored["RunRow"].add("invented_column")
    problems2 = _type_alignment_problems(doctored, backend)
    assert problems2 and "invented_column" in problems2[0], problems2

    # ③ TS 少一个接口（契约表要求它）
    dropped = {k: v for k, v in interfaces.items() if k != "LedgerReading"}
    problems3 = _type_alignment_problems(dropped, backend)
    assert problems3 and "LedgerReading" in problems3[0], problems3


def test_c_the_unchecked_registry_is_not_stale(tmp_path: pathlib.Path) -> None:
    """反向断言（C 的欠账名单）：登记为"本批无读数"的接口，现在确实读不出来。

    没有这一条，那份名单会慢慢变成"随便往里塞名字"的垃圾桶：塞进去的接口哪怕
    后来真能读了，也没有任何东西会响。
    """
    interfaces = _parse_interfaces(_ui_text(TYPES_TS))
    backend = _backend_keys(_fixture_workspace(tmp_path))
    for name in _unchecked_types():
        assert name not in backend, (
            f"{name} 登记为「本批无读数」，但夹具上读出了它的键 ⇒ 请把它挪进受核对名单")
        assert name in interfaces, f"{name} 在欠账名单里，却不在 types.ts 里"


# ====================================================================== D 路由对齐
def _routes_in_main(text: str) -> set[str]:
    """`main.tsx` 里 `ROUTES` 那一行的取值集合。"""
    m = re.search(r"ROUTES\s*=\s*\[(.*?)\]", _strip_js_comments(text), re.S)
    if m is None:
        return set()
    return set(re.findall(r"[\"'](/[^\"']*)[\"']", m.group(1)))


def _routes_in_the_contract_table() -> set[str]:
    """`draft/75 §1.4` 那张 C4 表第一列的客户端路由（判据从这里读，不另抄一份）。"""
    if not DRAFT_75.is_file():
        pytest.skip(f"C4 表所在的 {DRAFT_75.name} 不在盘上")
    text = DRAFT_75.read_text(encoding="utf-8")
    section = text.split("### §1.4", 1)
    assert len(section) == 2, "draft/75 里找不到 §1.4（C4 表）小节"
    body = section[1].split("### §1.5", 1)[0]
    rows = set(re.findall(r"^\|\s*`(/[^`]*)`\s*\|", body, re.M))
    assert len(rows) >= 6, f"C4 表只解析出 {len(rows)} 行 ⇒ 表格格式变了"
    return rows


def _route_alignment_problems(routes_in_main: set[str], table: set[str],
                              endpoints_used: set[str], kinds_used: set[str],
                              known_kinds: set[str]) -> list[str]:
    """路由集合 vs C4 表；页面用到的端点 ∈ ROUTES、kind ∈ KINDS。"""
    problems: list[str] = []
    extra = sorted(routes_in_main - table)
    missing = sorted(table - routes_in_main)
    if extra:
        problems.append(f"main.tsx 里有 C4 表没有的路由：{extra}")
    if missing:
        problems.append(f"C4 表里有而 main.tsx 没接的路由：{missing}")
    unknown_endpoints = sorted(e for e in endpoints_used
                               if e not in set(routes.api_paths())
                               and e not in _pending_endpoints())
    if unknown_endpoints:
        problems.append(f"页面用到了后端没有的端点：{unknown_endpoints}")
    unknown_kinds = sorted(kinds_used - known_kinds)
    if unknown_kinds:
        problems.append(f"页面用到了 sse.ts 没注册的 kind：{unknown_kinds}")
    return problems


def _page_sources() -> list[pathlib.Path]:
    """前端源码里除 `api.ts` / `sse.ts` / `types.ts` 之外的那些（页面与入口）。"""
    skip = {API_TS, SSE_TS, TYPES_TS}
    found = sorted(p for p in (UI / "src").rglob("*") if p.suffix in (".ts", ".tsx"))
    return [p for p in found if p not in skip]


def test_d_the_client_routes_match_the_contract_table() -> None:
    """正控（D 路由对齐）：`main.tsx` 的路由集合 == `draft/75 §1.4` 的 C4 表。"""
    in_main = _routes_in_main(_ui_text(MAIN_TSX))
    table = _routes_in_the_contract_table()
    assert in_main, "main.tsx 里 ROUTES 一个取值都没解析到 ⇒ 判据没接上"
    assert _route_alignment_problems(in_main, table, set(), set(), set()) == [], (
        f"main.tsx {sorted(in_main)} vs C4 表 {sorted(table)}")


def test_d_pages_only_use_endpoints_that_exist() -> None:
    """正控（D 的第二半）：页面用到的端点 ∈ ROUTES、kind ∈ KINDS。

    例外只有一条，逐条登记在各子表模块的 `PENDING_ENDPOINTS` 里（SSE 流，W2 才落地）。
    """
    known_kinds = _frontend_event_kinds(_ui_text(SSE_TS))
    endpoints: set[str] = set()
    kinds: set[str] = set()
    for path in _page_sources():
        text = path.read_text(encoding="utf-8")
        endpoints |= _endpoint_literals(text)
        kinds |= _kinds_used(text, known_kinds)
    problems = _route_alignment_problems(_routes_in_main(_ui_text(MAIN_TSX)),
                                         _routes_in_the_contract_table(),
                                         endpoints, kinds, known_kinds)
    assert problems == [], problems


def _kinds_used(text: str, known: set[str]) -> set[str]:
    """页面里出现的 kind 字面量（只在已知词表里认，免得把普通字符串当 kind）。"""
    return {s for s in _literals(text) if s in known}


def test_d_negative_control_catches_an_unknown_endpoint_and_route() -> None:
    """负控（D）：页面里写一个 C1 没有的端点 / 多一条 C4 之外的路由 ⇒ 必红。"""
    table = {"/", "/run/:sid", "/evidence", "/artifacts", "/acceptance", "/machine"}
    kinds = {"state", "question", "answered", "checkpoint", "stop", "heartbeat"}
    assert _route_alignment_problems(table, table, {"/api/state"}, {"state"}, kinds) == []
    problems = _route_alignment_problems(table, table, {"/api/ghost"}, {"state"}, kinds)
    assert problems and "ghost" in problems[0], problems
    problems2 = _route_alignment_problems(table | {"/extra"}, table, set(), set(), kinds)
    assert problems2 and "/extra" in problems2[0], problems2
    problems3 = _route_alignment_problems(table, table, set(), {"progress"}, kinds)
    assert problems3 and "progress" in problems3[0], problems3


def test_d_the_endpoint_allowlist_is_not_stale() -> None:
    """反向断言（D 的例外表）：登记的例外一旦在后端落地，就必须从表里删掉。"""
    back = set(routes.api_paths())
    allow = _pending_endpoints()
    stale = sorted(p for p in allow if p in back)
    assert not stale, (
        "这些端点已被 ROUTES 实现，却还挂在 D 的例外表里（一张永不生效的豁免表会腐烂）："
        + "、".join(stale))
    for path, why in _pending_endpoints().items():
        assert why.strip(), f"{path} 的例外没有写理由"


# ====================================================================== 见别处
# 静态路由 / SPA 回退 / 产物新鲜度那几条在本批搬到了 `tests/test_webui_static.py`
# （`draft/73` §1.3 指定的 W0 落点，父代理第 3 条提醒也点了这个文件名）—— 那里同时
# 管着 content-type、哈希缓存、目录穿越负控与「产物与一次真实构建一致」。

# ====================================================================== 生成物新鲜度
def _freshness_problem(rendered: str, on_disk: str) -> str:
    """生成物与源是否一致（一致返回空串，不一致返回人话）。"""
    if rendered == on_disk:
        return ""
    return (f"生成物与源不一致：生成 {len(rendered)} 字节、盘上 {len(on_disk)} 字节。"
            "手改生成物必红（裁定 M2）：请改生成器再重跑，不要改生成物。")


def test_types_ts_is_generated_not_hand_edited() -> None:
    """正控（M2 新鲜度）：`ui/src/types.ts` 与 `emit_types.render_types()` 逐字节相同。"""
    on_disk = _ui_text(TYPES_TS)
    assert emit_types.TYPES_PATH_LABEL in on_disk, (
        "生成物头部没有「生成物，勿手改」那句")
    assert _freshness_problem(emit_types.render_types(), on_disk) == "", (
        _freshness_problem(emit_types.render_types(), on_disk))
    # 反真空：生成器真的在吐东西，而不是空文件
    assert "export interface RunRow" in on_disk


def test_theme_css_is_generated_not_hand_edited() -> None:
    """正控（令牌单一来源）：`ui/src/theme/generated/theme.css` 与 `emit_theme.render_css()` 相同。

    这一条把"前端自己抄了一份令牌"这条路堵掉：令牌只有一个来源
    （`web/assets.py` 的 `THEME_CSS`），前端那份是生成物。
    """
    on_disk = _ui_text(THEME_CSS)
    assert _freshness_problem(emit_theme.render_css(), on_disk) == "", (
        _freshness_problem(emit_theme.render_css(), on_disk))
    assert "--dsw-alias-" in on_disk, "生成物里没有令牌 ⇒ 生成器没接上"


def test_negative_control_catches_a_hand_edited_generated_file() -> None:
    """负控（新鲜度）：手改生成物一个字节 ⇒ 必须报出来。"""
    good = emit_types.render_types()
    assert _freshness_problem(good, good) == ""
    doctored = good.replace("  sid: string;", "  sid: string;  // 手改的一笔", 1)
    assert doctored != good, "负控没改到内容 —— 这条负控自己失效了"
    assert _freshness_problem(good, doctored) != "", "手改了生成物，判据却一声不吭"
    css = emit_theme.render_css()
    assert _freshness_problem(css, css + "\n") != ""


def test_app_css_uses_only_tokens_in_the_theme() -> None:
    """负控（前端的皮）：`ui/src/theme/app.css` 无字面色值，引用的令牌都定义过。

    这是 `tests/test_webui.py::test_app_css_uses_only_tokens` 在前端源码上的平移：
    写死一个色值就等于在令牌体系之外偷偷开了一层皮，下次换皮时它不动。
    """
    css = _ui_text(APP_CSS)
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", css)
    assert hexes == [], f"app.css 里有字面色值：{hexes}"
    assert not re.search(r"\b(?:rgb|rgba|hsl|hsla)\(", css), "app.css 里有 rgb()/hsl()"
    defined = set(re.findall(r"(--[A-Za-z0-9-]+)\s*:", emit_theme.render_css()))
    used = set(re.findall(r"var\((--[A-Za-z0-9-]+)\)", css))
    assert used, "app.css 里一个令牌都没用到 ⇒ 判据没接上"
    missing = sorted(used - defined)
    assert missing == [], f"app.css 引用了令牌层里没定义的令牌：{missing}"


# ====================================================================== 拆包与开关
def test_the_public_face_survived_the_split() -> None:
    """正控（裁定 R1）：拆包之后公开面逐名不变（`__all__` 就是那八个）。"""
    expected = ["snapshot", "render_root", "render_run", "serve", "run", "WebHandler",
                "answer_text_of", "option_view"]
    assert sorted(W.__all__) == sorted(expected), W.__all__
    for name in expected:
        assert callable(getattr(W, name)), name
    # 既有判据直接读的三个名字（不在 `__all__` 里，但拆包不许把它们拿走）
    for name in ("REPORT_REL", "_STOP_BADGES", "_now_iso"):
        assert hasattr(W, name), name


def test_the_route_table_handlers_all_exist() -> None:
    """正控（路由表）：`ROUTES` 每一条登记的处理器真的存在。

    表驱动的好处就在这里：写错一个名字，这条判据当场说清是哪一条，而不是等某次请求 500。
    两种落点都算存在（`draft/78 §3` 的接缝）：A 线自己的在 `WebHandler` 上，
    B/C 线的在各自子表模块的 `HANDLERS` 里 —— 后者让那两条线不必改 `server.py`。
    """
    missing = [h for h in routes.handler_names()
               if not hasattr(W.WebHandler, h) and routes.handler_for(h) is None]
    assert not missing, f"ROUTES 登记了既不在 WebHandler 上、也没在子表 HANDLERS 里的处理器：{missing}"
    assert set(routes.methods()) <= {"GET", "POST"}, routes.methods()
    assert any(m == "POST" for m in routes.methods()), "表里一条 POST 都没有 ⇒ 表结构变了"


def test_a_subtable_handler_placed_in_its_own_module_is_actually_called() -> None:
    """正控（接缝真接通）：往子表模块的 `HANDLERS` 里放一个处理器 ⇒ 请求真的进它。

    为什么要有这条：`HANDLERS` 只是约定名字；若 `server._invoke` 没去读它，那条约定
    就是假的 —— B/C 线会以为"放进去就行"，而请求会 500。所以这里用真实 HTTP 走一遍：
    ① 没登记时同一条路径是 404（反例，证明下面的 200 说明得了问题）；
    ② 登记进 `sse.HANDLERS` 并把它那条路由喂进总表 ⇒ 200 且 JSON 里带着路径参数。
    表通过 `serve(routes_table=...)` 注入，不改模块全局 —— 改全局的判据会污染别的用例
    （这一点我写第一版时踩过，留在这里当注脚）。
    """
    from agentflow.webui import sse

    seen: list[tuple[str, str]] = []
    original = dict(getattr(sse, "HANDLERS", {}) or {})

    def _probe(handler, params, query):  # noqa: ANN001 - 与子表 handler 签名一致
        seen.append((params.get("sid", ""), handler.root.name))
        handler._json(200, {"ok": True, "tri": "computed", "reason": "probe",
                            "id": params.get("sid", "")})

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="webui-seam-"))
    with _sub_server(tmp) as base:
        code, _body, _ctype, _cache = _sub_get(base, "/api/seam-probe/xyz")
        assert code == 404, (code, "该路径本来就不存在 —— 否则下面的 200 说明不了什么")

    try:
        sse.HANDLERS = dict(original, **{"handle_probe_seam": _probe})
        table = routes.compose(tuple(routes.ROUTES),
                               (("GET", "/api/seam-probe/{sid}", "handle_probe_seam"),), ())
        with _sub_server(tmp, routes_table=table) as base:
            code, body, ctype, _cache = _sub_get(base, "/api/seam-probe/xyz")
            assert code == 200, (code, body)
            assert ctype.startswith("application/json"), ctype
            assert '"xyz"' in body, body
            assert seen == [("xyz", tmp.name)], seen
        # 路由表登记了名字、但子表没登记 handler ⇒ 500 且名字出现在正文里
        # （表与实现的漂移必须吵，不许静默 404）
        sse.HANDLERS = original
        with _sub_server(tmp, routes_table=table) as base:
            code, body, _ctype, _cache = _sub_get(base, "/api/seam-probe/xyz")
            assert code == 500, (code, body)
            assert "handle_probe_seam" in body, body
    finally:
        sse.HANDLERS = original
        shutil.rmtree(tmp, ignore_errors=True)


@contextmanager
def _sub_server(root: pathlib.Path,
                routes_table: tuple[tuple[str, str, str], ...] | None = None) -> Iterator[str]:
    """在临时端口上起一个服务（接缝判据专用；`routes_table` 可注入）。"""
    srv = W.serve(root, host="127.0.0.1", port=0, csrf_token="seamtoken0123456789",
                  routes_table=routes_table)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _sub_get(base: str, path: str) -> tuple[int, str, str, str]:
    """一次 GET：返回 `(状态码, 正文, content-type, cache-control)`。"""
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return (resp.status, resp.read().decode("utf-8", errors="replace"),
                resp.getheader("Content-Type") or "",
                resp.getheader("Cache-Control") or "")
    finally:
        conn.close()


def test_the_two_cli_switches_exist_and_say_they_do_nothing_yet() -> None:
    """正控（裁定 T1）：两个开关在 CLI 与模块入口上都有，且 --help 里说明还没接线。

    为什么连 help 文案也钉住：本批开关只做到"解析并透传"，若 help 不写这一句，
    读 help 的人会以为自己已经拿到了写面（那是假读数）。W3/W4 真正接线时，
    这两条断言会红 —— 那时连同文案一起改，正是它该被想起来的地方。
    """
    from agentflow import cli

    parser = cli.build_parser()
    ns = parser.parse_args(["web", "--port", "0", "--json"])
    assert ns.allow_writes is False and ns.no_settings_write is False, vars(ns)
    ns2 = parser.parse_args(["web", "--allow-writes", "--no-settings-write"])
    assert ns2.allow_writes is True and ns2.no_settings_write is True

    helps: dict[str, str] = {}
    subs = next(a for a in parser._actions  # noqa: SLF001 - argparse 的公开入口只有这一条路
                if isinstance(a.choices, dict) and "web" in a.choices)
    for action in subs.choices["web"]._actions:  # noqa: SLF001
        helps[action.dest] = str(action.help or "")
    for dest in ("allow_writes", "no_settings_write"):
        assert "还没有接线" in helps.get(dest, ""), (dest, helps.get(dest))

    # 模块入口的签名同样带着这两个开关（parse-and-pass-through 的落点）
    import inspect

    params = inspect.signature(W.serve).parameters
    assert "allow_writes" in params and "settings_write" in params, sorted(params)
    assert params["allow_writes"].default is False, params["allow_writes"].default
    assert params["settings_write"].default is True, params["settings_write"].default


def test_the_switches_are_bound_on_the_server_and_readable(tmp_path: pathlib.Path) -> None:
    """正控（透传）：`serve(..., allow_writes=..., settings_write=...)` 真的挂到了句柄上。

    本批它们不改变任何行为（W3/W4 才判）—— 所以这里查的就是"解析并透传"这一件事：
    调用方给的值能在句柄上读回来。查"它改变了什么行为"在这里是错的（它还没接判断）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    srv = W.serve(root, host="127.0.0.1", port=0, allow_writes=True,
                  settings_write=False)
    try:
        handler = srv.RequestHandlerClass
        assert handler.allow_writes is True, handler.allow_writes
        assert handler.settings_write is False, handler.settings_write
        assert handler.root == root, handler.root
        assert handler.static_root.name == "static", handler.static_root
        assert len(handler.csrf_token) >= 16, handler.csrf_token
    finally:
        srv.server_close()
    # 缺省值仍是"只读 + 允许写设置"（裁定 C2 的默认口径）
    srv2 = W.serve(root, host="127.0.0.1", port=0)
    try:
        assert srv2.RequestHandlerClass.allow_writes is False
        assert srv2.RequestHandlerClass.settings_write is True
    finally:
        srv2.server_close()


def test_the_route_table_is_the_single_source_for_dispatch() -> None:
    """反真空（A 的前提）：`ROUTES` 覆盖了今天真有的每一条路由，且没有重复登记。"""
    paths = routes.patterns()
    assert len(paths) == len(set(paths)), f"ROUTES 里有重复的路径模式：{paths}"
    for must in ("/", "/api/state", "/run/{sid}", "/static/{file...}", "/answer"):
        assert must in paths, f"ROUTES 里缺 {must}：{paths}"
    assert routes.match("GET", "/api/state") is not None
    assert routes.match("POST", "/answer") is not None
    assert routes.match("POST", "/api/state") is None, "方法不匹配时不许命中"
    assert routes.match("GET", "/run/a/b") is None, "`{sid}` 只许匹配一段路径"
    assert routes.match("GET", "/static/assets/a.b.js") == (
        "handle_static", {"file": "assets/a.b.js"}), routes.match("GET", "/static/assets/a.b.js")
    assert routes.match("GET", "/nope") is None


def test_the_state_module_keeps_the_clock_patchable() -> None:
    """正控（拆包不许削弱判据）：`monkeypatch` 打的那只钟仍然管着 `snapshot()`。

    这条是 `tests/test_webui.py::test_rendering_is_a_projection_not_a_cache` 的
    结构前提：包化之后若取钟不走包命名空间，那次补丁会落空，而那条判据会退化成
    "两次请求碰巧同一秒才绿"（它自己不会响）。
    """
    real = W._now_iso()
    assert isinstance(real, str) and len(real) > 10, real
    import agentflow.webui as pkg

    original = pkg._now_iso
    try:
        pkg._now_iso = lambda: "1970-01-01T00:00:00+00:00"
        got = W.snapshot(REPO)
        assert got["generated_at"] == "1970-01-01T00:00:00+00:00", got["generated_at"]
    finally:
        pkg._now_iso = original
