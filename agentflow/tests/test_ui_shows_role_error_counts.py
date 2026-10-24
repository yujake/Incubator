# -*- coding: utf-8 -*-
"""UI 那一栏「按角色 × 类目的错误动作计数」的判据（业主 2026-10-24）。

业主原话（唯一权威）：「ui侧加一个大栏专门显示各角色错误动作计数」。

这一组守的是"这一栏真的把盘上的数搬到屏幕上，而且没数据的时候看得见"：

| 判据 | 查什么 |
|---|---|
| a 同源 | `GET /api/errors` 的五键与 `readouts.errors_readout(root)` 逐键相等（不许两份口径） |
| b 正控 | 空工作区 ⇒ `state=checked`、全 0，页面把 0 印出来（0 不是 unknown） |
| c 负控 | 不存在的工作区 / 事件流坏 ⇒ `state=unknown` + `reason`，页面显示「读不到」（不折成 0） |
| d 结构 | 矩阵的格由 `by_role` 渲染：行=角色、列=类目（扫 TSX 源码断言，带负控） |
| e 反真空 | 把 `by_role` 打桩成 `{}` ⇒ a 必红（证明端点不是硬编码的 0） |

为什么 d 是扫源码而不是跑浏览器：这一栏的"画法"只有源码能回答（`tests/test_webui_pages.py`
对九页用的是同一套办法）；浏览器那一层有自己的判据（`tests/test_webui_browser.py`，需要
playwright，没装就 skip），这里不重复它、也不假装跑过它。

三态纪律（这一组的主线）：`0` 与"读不到"必须是两句话。b 与 c 分别钉住这两档，而且
两者都从同一条端点读 —— 谁也不许在前端把 `unknown` 兜成 0。
"""

from __future__ import annotations

import http.client
import json
import pathlib
import re
import threading
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from agentflow import readouts as RO
from agentflow import webui as W
from agentflow.webui import routes

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
#: 前端源码根与这一栏的落点。
UI_SRC = REPO / "ui" / "src"
ROLE_ERRORS_TSX = UI_SRC / "components" / "RoleErrors.tsx"
API_TS = UI_SRC / "api.ts"

#: 两条只读端点的路径（与 `webui/routes.py` 的 `_OWN` 两行、`api.ts` 的 `ENDPOINTS` 逐字相同）。
ERRORS_PATH = "/api/errors"
CATEGORIES_PATH = "/api/errors/categories"


# ====================================================================== 夹具
@contextmanager
def _server(root: pathlib.Path) -> Iterator[str]:
    """在临时端口上起一个服务（`allow_writes` 留缺省 False：只读端点不许要写权限）。"""
    srv = W.serve(root, host="127.0.0.1", port=0, csrf_token="testtoken0123456789")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address[0], srv.server_address[1]
    try:
        yield f"{host}:{port}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _get_json(base: str, path: str) -> tuple[int, dict[str, Any]]:
    """一次 GET：返回 `(状态码, 解出来的 JSON)`。"""
    conn = http.client.HTTPConnection(base, timeout=120)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        return (resp.status, json.loads(body))
    finally:
        conn.close()


#: 事件流里那三行被拒/失败的任务（每个角色撞上不同的一类判据）。
_EVENT_ROWS: tuple[dict[str, Any], ...] = (
    # forbidden_edge 是召唤期结构判据 ⇒ 记 called_by（M），不记被召唤的 B。
    {"task_id": "t-000001", "role": "B", "called_by": "M",
     "outcome": "refused", "refusal_reason": "forbidden_edge"},
    {"task_id": "t-000002", "role": "B", "outcome": "refused",
     "refusal_reason": "缺少必填参数"},
    {"task_id": "t-000003", "role": "F", "outcome": "failed",
     "refusal_reason": "direct_write_refused"},
)

#: 会话记录里那两行（工具层拒信 + 判据层坏 JSON）。
_STEP_ROWS: tuple[dict[str, Any], ...] = (
    {"kind": "agent_step", "role": "A", "result": {"error": "参数错误：x"}},
    {"kind": "llm_call", "role": "D", "problem": "judge_bad_json"},
)


def _write_ws(tmp_path: pathlib.Path, kind: str = "filled") -> pathlib.Path:
    """造一个工作区：`filled`（有计数）/ `empty`（空事件流）/ `broken`（每行都读不明白）。"""
    root = tmp_path / kind
    (root / "data").mkdir(parents=True)
    (root / "sessions").mkdir()
    if kind == "empty":
        (root / "data" / "events.jsonl").write_text("", encoding="utf-8")
        return root
    if kind == "broken":
        (root / "data" / "events.jsonl").write_text("这不是 JSON\n还是一行坏\n",
                                                    encoding="utf-8")
        (root / "sessions" / "B-broken.jsonl").write_text("坏行\n", encoding="utf-8")
        return root
    events = [{"table": "tasks", "op": "upsert", "row": row} for row in _EVENT_ROWS]
    (root / "data" / "events.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    (root / "sessions" / "B-1.jsonl").write_text(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in _STEP_ROWS),
        encoding="utf-8")
    return root


# ====================================================================== 共用判据
def _five_key_problems(served: dict[str, Any], direct: dict[str, Any]) -> list[str]:
    """端点的五键与 `readouts.errors_readout` 的差（空 = 逐键相等）。

    a 与 e 共用这一条：e 打桩之后拿它去比，断言"此时必红" —— 于是"逐键相等"这条
    判据本身也被证明是活的（不是一句永远成立的空话）。
    """
    problems: list[str] = []
    keys = set(RO.READOUT_KEYS)
    got = set(served)
    if got != keys:
        problems.append(f"端点返回的键集不是那五个：多 {sorted(got - keys)} 少 {sorted(keys - got)}")
    for key in RO.READOUT_KEYS:
        if served.get(key) != direct.get(key):
            problems.append(f"{key} 与 readouts.errors_readout 不一致（两份口径）")
    return problems


# ====================================================================== a 同源
def test_a_the_endpoint_returns_the_five_keys_of_errors_readout(
        tmp_path: pathlib.Path) -> None:
    """正控（同源）：`GET /api/errors` 的五键 == `readouts.errors_readout(root)` 逐键。

    `allow_writes` 没开（缺省 False）：只读端点不许要写权限，所以这一条同时也是
    "只读那一档"的读数 —— 403 会让它当场红。
    """
    root = _write_ws(tmp_path, "filled")
    direct = RO.errors_readout(root)
    # 反真空：夹具必须真的产生计数（否则"逐键相等"是两个空表的相等）
    assert direct["state"] == "checked", direct
    assert direct["data"]["total"] == 5, direct["data"]
    assert direct["data"]["by_role"], direct["data"]

    with _server(root) as base:
        code, served = _get_json(base, ERRORS_PATH)
    assert code == 200, "只读端点回的不是 200（写权限不该是它的前提）"
    assert _five_key_problems(served, direct) == [], (
        f"端点 {json.dumps(served, ensure_ascii=False)[:400]}")


def test_a_both_endpoints_are_read_only_get_routes() -> None:
    """反真空（路由那一层）：两条端点都是 GET，都没有配对的 POST，handler 都在盘上。"""
    for path, handler in ((ERRORS_PATH, "handle_errors"),
                          (CATEGORIES_PATH, "handle_errors_categories")):
        assert path in routes.patterns(), (path, routes.patterns())
        hit = routes.match("GET", path)
        assert hit is not None and hit[0] == handler, (path, hit)
        assert routes.match("POST", path) is None, f"{path} 不该有 POST（它是只读端点）"
        assert hasattr(W.WebHandler, handler), f"{handler} 不在 WebHandler 上"


# ====================================================================== b 正控
def test_b_an_empty_workspace_is_checked_and_shows_a_real_zero(
        tmp_path: pathlib.Path) -> None:
    """正控（0 不是 unknown）：空工作区 ⇒ `state=checked`、全 0，页面把 0 印出来。"""
    root = _write_ws(tmp_path, "empty")
    with _server(root) as base:
        code, served = _get_json(base, ERRORS_PATH)
    assert code == 200, code
    assert served["checked"] is True, served
    assert served["state"] == "checked", served
    assert served["reason"] == "", served
    assert served["data"]["total"] == 0, served["data"]
    assert served["data"]["by_role"] == {}, served["data"]
    assert served["data"]["categories"] == {}, served["data"]

    text = _component_text()
    problems = _head_total_problems(text)
    assert problems == [], problems
    assert "全 0" in text, "页面没有那句『全 0（已读出）』—— 0 与没读到会画成一个样子"


# ====================================================================== c 负控
def test_c_a_missing_workspace_or_a_broken_event_stream_is_unknown(
        tmp_path: pathlib.Path) -> None:
    """负控（不折成 0）：工作区不存在 / 事件流坏 ⇒ `state=unknown` + `reason`。

    注意 `data.total` 此时仍是 0（没有东西可数）—— 判据钉的是 `checked=False`：
    同一个 0 配上 `unknown` 才是"没查成"，配上 `checked` 才是"没有错误动作"。
    """
    missing = tmp_path / "no-such-workspace"
    broken = _write_ws(tmp_path, "broken")
    seen: list[tuple[str, dict[str, Any]]] = []
    for root, why in ((missing, "不存在的工作区"), (broken, "事件流坏")):
        with _server(root) as base:
            code, served = _get_json(base, ERRORS_PATH)
        assert code == 200, (why, code)
        assert served["checked"] is False, (why, served)
        assert served["state"] == "unknown", (why, served)
        assert served["reason"].strip() != "", (why, served)
        assert served["data"]["total"] == 0, (why, served["data"])
        seen.append((why, served))
    assert [why for why, _d in seen] == ["不存在的工作区", "事件流坏"]

    problems = _unknown_band_problems(_component_text())
    assert problems == [], problems


# ====================================================================== d 结构
#: 矩阵那一格必须由 `by_role` 的三个字形：行键、列键、格值。
_ROW_KEYS = "Object.keys(view.data.by_role)"
_COL_KEYS = "Object.keys(view.data.categories)"
_CELL = "view.data.by_role[role]"


def _matrix_problems(text: str) -> list[str]:
    """矩阵是不是"由 `by_role` 渲染、行=角色、列=类目"（扫源码；空 = 合格）。"""
    problems: list[str] = []
    if _ROW_KEYS not in text:
        problems.append(f"矩阵的行不是从 by_role 的键来的（缺 {_ROW_KEYS!r}）")
    if _COL_KEYS not in text:
        problems.append(f"矩阵的列不是从 categories 的键来的（缺 {_COL_KEYS!r}）")
    if _CELL not in text:
        problems.append(f"格值不是 by_role[角色][类目]（缺 {_CELL!r}）")
    if "cellCount(" not in text:
        problems.append("格值没有经过 cellCount（缺就是 0 的那一层）")
    if re.search(r'\[\s*"A"\s*,\s*"B"', text):
        problems.append("源码里写死了一张角色表（行不是从 by_role 来的）")
    if 'class="grid err-matrix"' not in text:
        problems.append("矩阵没有用那张通用表格的样式（class=\"grid err-matrix\"）")
    if 'class="err-scroll"' not in text:
        problems.append("矩阵外面没有可横向滚的那一层（类目多时最右几列会被裁掉）")
    return problems


def test_d_the_matrix_is_rendered_from_by_role(tmp_path: pathlib.Path) -> None:
    """正控（结构）：行=角色（`by_role` 的键）、列=类目（`categories` 的键）、格=计数。"""
    text = _component_text()
    assert _matrix_problems(text) == [], _matrix_problems(text)
    # 行与列都要先过那个"排序/取键"的函数，页面里不许各自再算一遍
    assert "matrixRows(view)" in text, "矩阵的行没有走 matrixRows(view)"
    assert "matrixColumns(view)" in text, "矩阵的列没有走 matrixColumns(view)"
    # 抬头三行：总错误动作 / 最集中的类目 / 三态
    for word in ("总错误动作", "最集中的类目", "三态"):
        assert word in text, f"抬头少了那一行：{word}"
    # 点一行展开明细、点一列过滤（两个回调都在源码里）
    assert "setOpenRole(" in text, "点某一行没有展开明细"
    assert "setOnlyCategory(" in text, "点某一列没有按类目过滤"


def test_d_negative_control_catches_a_hardcoded_zero_matrix() -> None:
    """负控（d）：把 `by_role` 那一路从源码里抽掉 ⇒ 判据必须当场红。"""
    text = _component_text()
    assert _matrix_problems(text) == [], _matrix_problems(text)
    for broken in (text.replace(_ROW_KEYS, "[]"),
                   text.replace(_CELL, "0"),
                   text.replace('class="grid err-matrix"', 'class="x"'),
                   text.replace('class="err-scroll"', 'class="x"')):
        assert _matrix_problems(broken) != [], "抽掉一格判据却一声不吭"


# ====================================================================== e 反真空
def test_e_stubbing_by_role_to_empty_makes_the_same_source_check_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空（e）：把 `by_role` 打桩成 `{}` ⇒ a 那条"逐键相等"必红。

    为什么这一条必不可少：端点若自己硬编码了一张 0 表（或自己另算一份），
    a 在空工作区上照样绿，而真实工作区上它写着 0 —— 那正是这一栏最坏的形态。
    打桩之后端点必须跟着变（证明它真的走 `readouts.errors_readout`），
    而"拿真读数去比"必须红（证明 a 比的不是同一个空表）。
    """
    root = _write_ws(tmp_path, "filled")
    direct = RO.errors_readout(root)
    assert direct["data"]["by_role"], "反真空：夹具没有产生计数"

    real = RO.errors_readout

    def stub(target: Any) -> dict[str, Any]:
        out = real(target)
        out["data"] = dict(out["data"])
        out["data"]["by_role"] = {}
        out["data"]["role_total"] = {}
        out["data"]["categories"] = {}
        out["data"]["total"] = 0
        return out

    monkeypatch.setattr(RO, "errors_readout", stub)
    with _server(root) as base:
        code, served = _get_json(base, ERRORS_PATH)
    assert code == 200, code
    # ① 端点真的跟着桩走（不是硬编码的 0 表：它连 non-0 都跟着变了）
    assert served["data"]["by_role"] == {}, served["data"]
    assert served["data"]["total"] == 0, served["data"]
    # ② 而 a 那条判据此时必红，且点名的是 data 那一键
    problems = _five_key_problems(served, direct)
    assert problems, "打桩之后 a 仍绿 ⇒ a 比的不是端点，是它自己"
    assert any("data" in one for one in problems), problems


# ====================================================================== 读源码
def _component_text() -> str:
    """这一栏的源码；不在盘上就 fail（它是这一组判据的落点，不许 skip 变绿）。"""
    assert ROLE_ERRORS_TSX.is_file(), (
        f"{ROLE_ERRORS_TSX.relative_to(REPO)} 不在盘上 —— 这一栏没有落点")
    return ROLE_ERRORS_TSX.read_text(encoding="utf-8")


def _head_total_problems(text: str) -> list[str]:
    """抬头那一行是不是把 `data.total` 印出来（空 = 合格）。"""
    if "总错误动作" not in text:
        return ["抬头没有『总错误动作』这一行"]
    if not re.search(r"总错误动作[\s\S]{0,60}\{[^}]*view\.data\.total[^}]*\}", text):
        return ["抬头那一行印的不是 data.total（它得是后端给的那个数）"]
    return []


def _unknown_band_problems(text: str) -> list[str]:
    """unknown 时整栏显示「读不到」、而且画不到矩阵（空 = 合格）。"""
    problems: list[str] = []
    guard = re.search(
        r'if \(view\.state !== "checked"\) \{\s*return <UnreadableBand[^>]*/>;\s*\}', text)
    if guard is None:
        return ['没有 "state !== checked ⇒ 整栏读不到" 的那道早退闸门']
    if "读不到" not in text:
        problems.append("那一档没有『读不到』这三个字")
    band_at = text.find("function UnreadableBand")
    if band_at < 0:
        problems.append("没有一个专门画『读不到』的 UnreadableBand")
    elif "读不到" not in text[band_at:]:
        problems.append("UnreadableBand 里没有『读不到』")
    matrix_at = text.find("matrixRows(view)")
    if guard.start() > matrix_at >= 0:
        problems.append("早退闸门排在矩阵之后 —— unknown 时照样画得出 0 行")
    if re.search(r"view\.state !== \"checked\"[\s\S]{0,40}view\.data\.total", text):
        problems.append("unknown 那一档里还印了 data.total（那就是折成 0）")
    return problems


# ====================================================================== 前端接线
def test_the_frontend_declares_both_endpoints_and_the_nav_reaches_the_band() -> None:
    """接线：`api.ts` 声明两条端点、首页挂上这一栏、导航多了那一格。

    为什么要有这一条：端点与页面各自绿着而中间那根线没接，是这个项目反复踩的形态
    （判据 C 的 `MISSING_TYPES` 与 D 的例外表都是为这件事设的）。
    """
    api_text = API_TS.read_text(encoding="utf-8")
    assert f'errors: "{ERRORS_PATH}"' in api_text, "api.ts 的 ENDPOINTS 少了 /api/errors"
    assert f'errorCategories: "{CATEGORIES_PATH}"' in api_text, (
        "api.ts 的 ENDPOINTS 少了类目释义那一条")
    assert "getErrors:" in api_text and "getErrorCategories:" in api_text, (
        "api.ts 少了取数函数")

    home = (UI_SRC / "pages" / "Home.tsx").read_text(encoding="utf-8")
    assert "<RoleErrors" in home, "首页没有挂上这一栏（那一格导航就点了没处去）"
    main = (UI_SRC / "main.tsx").read_text(encoding="utf-8")
    assert '"错误动作"' in main, "导航里没有『错误动作』那一格"
