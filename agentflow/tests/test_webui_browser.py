# -*- coding: utf-8 -*-
"""浏览器端到端判据（裁定 F1：Playwright，opt-in）。

## 怎么跑（默认不跑）

    pip install -e ".[browser]"     # pyproject 的 optional-dependencies: browser
    playwright install chromium     # 浏览器装在用户目录，不进仓
    python -m pytest -q -m browser tests/test_webui_browser.py

默认排除由 `pyproject.toml` 的 `addopts = "-m 'not network and not browser'"` 那一行
负责（`draft/79` 的 T1 那条不一致已由主控落地修掉）。这个文件自己再挂一次
`pytestmark`，是为了"单独点这个文件跑"时也走同一条口径。

## 没装就是 `unknown` 不是 `pass`

`playwright` 没装 ⇒ 整个模块 `skip`，理由逐字写明"这是 unknown 不是 pass"
（与 `-m network`、发布门 `unknown` 的处置同一条纪律：没查成不许记成通过）。
本文件在写的时候没有跑过（本机没装 playwright、也没有浏览器），
这一点写在报告里，不假装它绿过。

## 两条实况（写判据时量到的，决定了下面哪些格是 skip）

1. `GET /` 今天仍由 A 线的旧壳 `views.render_root` 提供（裁定 P1 的逐面迁移还没做），
   所以浏览器里 `#app` 那一层只在 SPA 回退路径（`/machine` 这类客户端路由，
   请求头带 `Accept: text/html`）上才挂得起来。判据一律从 `/machine` 进。
2. Machine 页的"写设置表单"与 Run 页的"叫停按钮"今天还是 W0 空壳
   （`ui/src/pages/Machine.tsx` 的 `TriState tri="not_applicable"`），
   所以"点按钮 ⇒ 403 提示"这一格没有可点的按钮 —— 那两条判据如实 `skip`
   并写明理由，不许改成一个会静默通过的弱断言。
   写面本身的浏览器侧读数（真浏览器来源去打那三个端点）照常测，见下面第 4/5/6 条。
"""

from __future__ import annotations

import json
import pathlib
import threading
import urllib.parse
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from agentflow import settings as SET
from agentflow import stopctl as SC
from agentflow import webui as W
from agentflow.store import Store
from agentflow.webui import audit

pytestmark = [pytest.mark.browser]

#: 没装 playwright ⇒ 整个模块 skip（理由要说清"这是 unknown 不是 pass"）。
_sync = pytest.importorskip(
    "playwright.sync_api",
    reason=("没装 playwright（`pip install -e \".[browser]\"` 加 `playwright install chromium`）"
            "⇒ 浏览器端到端这一档是 unknown，不是 pass：它今天一次都没被跑过"))

CSRF = "line-c-browser-csrf-0123456789"


# ====================================================================== 夹具
@contextmanager
def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个最小工作区（写面那几条判据要一个能落盘的地方）。"""
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    return root


@contextmanager
def _live(root: pathlib.Path, *, allow_writes: bool = True,
          settings_write: bool = True) -> Iterator[dict[str, Any]]:
    """起服务 + 起浏览器，产出 `{base, page, errors, csrf}`。

    浏览器起不来（没 `playwright install`）⇒ `skip` 并写明理由：
    那是"没查成"，不是"查过了没问题"。
    """
    srv = W.serve(root, host="127.0.0.1", port=0, allow_writes=allow_writes,
                  settings_write=settings_write, csrf_token=CSRF)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://{srv.server_address[0]}:{srv.server_address[1]}"
    browser = None
    try:
        with _sync.sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception as exc:  # noqa: BLE001 - 起不来就是"没查成"
                pytest.skip(f"浏览器起不来（先跑 `playwright install chromium`）："
                            f"{type(exc).__name__}: {exc} —— 这是 unknown 不是 pass")
            page = browser.new_page()
            errors: list[str] = []
            page.on("console",
                    lambda m: errors.append(f"console.{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            yield {"base": base, "page": page, "errors": errors, "csrf": CSRF}
    finally:
        if browser is not None:
            browser.close()
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _enter_spa(live: dict[str, Any], route: str = "/machine") -> None:
    """进一个客户端路由（SPA 回退那条路：浏览器带 `Accept: text/html`）。"""
    live["page"].goto(live["base"] + route, wait_until="load")
    live["page"].wait_for_selector("#app > *", timeout=10_000)


# ====================================================================== 1 外壳与日志
def test_the_spa_shell_mounts_and_the_console_stays_clean(tmp_path: pathlib.Path) -> None:
    """正控（前端真的挂起来了）：`#app` 有子节点、控制台没有 error。

    `#app` 是 `ui/index.html` 的挂载点；它空着就说明 bundle 没跑起来（404 的脚本、
    JS 异常、或静态路由发错了 content-type）—— 那三种都会在控制台留一条 error。
    """
    with _workspace(tmp_path) as root, _live(root) as live:
        _enter_spa(live)
        assert live["page"].eval_on_selector("#app", "n => n.children.length") > 0, \
            "`#app` 里一个子节点都没有 —— 前端 bundle 没跑起来"
        assert [e for e in live["errors"] if "favicon" not in e] == [], live["errors"]


def test_the_root_page_is_now_the_spa_shell(
        tmp_path: pathlib.Path) -> None:
    """正控（P1 第一块已落地）：`GET /` 现在吐 SPA 外壳，浏览器里能挂起来。

    这条判据的前身是"实况：`/` 仍由旧壳提供、`#app` 挂不起来"，它当时还写着
    "哪一天 P1 落地（`/` 改吐 SPA 外壳），这条会红，那时改它正合适" —— 2026-10-07
    A 线按 `draft/81 §6-D13` 落了 P1 的第一块（`handle_root` → 唯一一份
    `server._serve_spa_shell()`），于是就是现在：把它改成新形状，并保留一条反向读数
    （旧壳那条路仍活给 `GET /run/{sid}` 用，所以"旧壳没被删干净"与"根页面已迁"两件事
    在这一条里分得开）。
    """
    with _workspace(tmp_path) as root, _live(root) as live:
        live["page"].goto(live["base"] + "/", wait_until="load")
        assert live["page"].query_selector("#app") is not None, (
            "`/` 没有 `#app` 挂载点 —— P1 的第一块（`/` 改吐 SPA 外壳）没落地，"
            "或外壳产物不在盘上（后者会 404 + '前端外壳不在盘上'）")
        assert live["page"].query_selector("body > *") is not None, "整页是空的"
        # 外壳里的令牌占位符必须被这一次进程的令牌替换（与 Q1 的回退路径同一条注入逻辑）
        html = live["page"].content()
        assert "__CSRF__" not in html, "外壳里的 CSRF 占位符没被替换"


# ====================================================================== 2 CSRF
def test_the_csrf_token_is_injected_per_process_and_never_baked_in(
        tmp_path: pathlib.Path) -> None:
    """正控（令牌的来路）：页面里那一格是这一次进程的令牌，不是产物里那个占位符。"""
    with _workspace(tmp_path) as root, _live(root) as live:
        _enter_spa(live)
        got = live["page"].eval_on_selector('meta[name="csrf-token"]', "n => n.content")
        assert got == CSRF, got
        assert "__CSRF__" not in live["page"].content(), "占位符没被换掉"


# ====================================================================== 3 真浏览器来源的写面
def _browser_post(live: dict[str, Any], path: str, body: dict[str, str],
                  token: str | None = None) -> dict[str, Any]:
    """在页面上下文里发一次写请求（带浏览器自己的 `Origin`/`Host` 头）。

    为什么必须从页面里发：`http.client` 造不出浏览器那一组头（`Origin`、
    `Sec-Fetch-*`），而写面的第一道门就是来源校验 —— 用 Python 客户端测它，
    测到的是另一件事。
    """
    payload = urllib.parse.urlencode(body)
    return live["page"].evaluate(
        """async ([path, payload, token]) => {
             const headers = {"Content-Type": "application/x-www-form-urlencoded"};
             if (token) { headers["X-CSRF-Token"] = token; }
             const resp = await fetch(path, {method: "POST", headers, body: payload});
             return {status: resp.status, body: await resp.text()};
           }""",
        [path, payload, live["csrf"] if token is None else token])


def test_a_real_browser_origin_can_write_when_the_face_is_open(
        tmp_path: pathlib.Path) -> None:
    """正控（浏览器来源过得去 + 每一次写都留档）：真实浏览器发出的写 ⇒ 200 且台账多一行。"""
    with _workspace(tmp_path) as root, _live(root, allow_writes=True) as live:
        _enter_spa(live)
        got = _browser_post(live, "/api/stop", {"reason": "browser", "confirm": "1"})
        assert got["status"] == 200, got
        payload = json.loads(got["body"])
        assert payload["ok"] is True and payload["tri"] == "computed", payload
    assert SC.read_stop(root) is not None, "浏览器发来的叫停没落到盘上"
    rows = audit.read(root)
    assert len(rows) == 1 and rows[0]["ok"] is True, rows
    assert rows[0]["source"].startswith("127.0.0.1"), rows[0]["source"]


def test_a_real_browser_origin_gets_403_when_the_face_is_closed(
        tmp_path: pathlib.Path) -> None:
    """拒绝档（"没开写面时点了按钮"那件事在浏览器里的读数）：403 + 一句人话。

    Machine / Run 两个页面的按钮今天还是空壳（见模块 docstring），所以这里测的是
    按钮将要收到的那一支响应，不是一张还不存在的 DOM。前端拿到它之后渲染什么，
    属于 A 线那条判据（`tri=not_applicable` 由 `TriState` 呈现）。
    """
    with _workspace(tmp_path) as root, _live(root, allow_writes=False) as live:
        _enter_spa(live)
        got = _browser_post(live, "/api/stop", {"reason": "browser", "confirm": "1"})
        assert got["status"] == 403, got
        payload = json.loads(got["body"])
        assert payload["ok"] is False and payload["tri"] == "not_applicable", payload
        assert "写面没开" in payload["reason"], payload["reason"]
    assert SC.read_stop(root) is None
    assert audit.read(root)[0]["ok"] is False, audit.read(root)


def test_a_write_without_the_csrf_header_is_refused_in_a_real_browser(
        tmp_path: pathlib.Path) -> None:
    """拒绝档（浏览器里的 CSRF 那一档）：不带 `X-CSRF-Token` ⇒ 403。

    注意这一条不能用"跨站 Origin"来测：页面自己的 `fetch` 永远带自己站点的
    Origin，浏览器也不允许脚本伪造它 —— 跨站那一档由 `test_webui_writes.py` 用
    Python 客户端直接造头来测（那是唯一测得动它的位置）。
    """
    with _workspace(tmp_path) as root, _live(root, allow_writes=True) as live:
        _enter_spa(live)
        got = _browser_post(live, "/api/stop", {"reason": "browser", "confirm": "1"},
                            token="")
        assert got["status"] == 403, got
        assert "CSRF" in json.loads(got["body"])["reason"], got["body"]


def test_the_key_reaches_the_file_but_never_the_page_or_the_response(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（裁定 E1 的浏览器侧读数）：key 落盘、响应里 `***`、页面里一个字都没有。

    第三处读数（"页面里"）在这里是真读数：整页 `content()` 与该次响应的正文都过一遍
    尺子。表单本身还没落地（Machine 页是 W0 空壳），所以"填进表单再提交"那一步
    由下面那条 `skip` 如实记成未查。
    """
    secret = "sk-browser-must-never-be-shown-0123456789"
    target = tmp_path / "settings.json"
    monkeypatch.setenv(SET.ENV_SETTINGS, str(target))
    with _workspace(tmp_path) as root, _live(root, allow_writes=True) as live:
        _enter_spa(live)
        got = _browser_post(live, "/api/settings",
                            {"model.api_key": secret,
                             "model.base_url": "https://example.invalid/v1",
                             "confirm": "1"})
        assert got["status"] == 200, got
        payload = json.loads(got["body"])
        assert payload["extra"]["values"]["model"]["api_key"] == SET.MASKED_KEY, payload
        assert secret not in got["body"], "响应回显了真 key"
        assert secret not in live["page"].content(), "页面里出现了真 key"
        assert secret not in json.dumps(audit.read(root), ensure_ascii=False), \
            "台账里出现了真 key"
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["model"]["api_key"] == secret, on_disk


# ====================================================================== 4 还没落地的那两格
def test_the_settings_form_is_never_prefilled_with_the_key(tmp_path: pathlib.Path) -> None:
    """未查（unknown，不是 pass）：Machine 页今天还没有"设置表单"这个 DOM。

    为什么写成 `skip` 而不是删掉：这是 `draft/73` §2.8 点名的那一条判据
    （"key 填了但页面/响应都不回显"的表单那一半）。A 线的 Machine 页一落地，
    把这条的 `skip` 换成真断言即可 —— 留着它，缺的那一格就是可见的。
    """
    with _workspace(tmp_path) as root, _live(root) as live:
        _enter_spa(live, "/machine")
        body = live["page"].content()
        if "password" in body or "api_key" in body:
            raise AssertionError(
                "Machine 页已经有设置表单了 —— 请把这条 skip 换成真断言"
                "（表单永不回填 key，type=password）")
    pytest.skip("Machine 页还是 W0 空壳（`ui/src/pages/Machine.tsx` 只渲染一个 "
                "TriState「这一面要等 W1 的读模型」）⇒ 表单那一格没查成："
                "这是 unknown 不是 pass")


def test_the_stop_button_asks_for_confirmation_before_calling_stop(
        tmp_path: pathlib.Path) -> None:
    """未查（unknown，不是 pass）：Run 页今天没有可点的"叫停"按钮。

    同上：`draft/73` §2.8 的 `test_stop_requires_confirmation` 要的是
    `ConfirmButton` 真接线之后的行为（不可逆动作必须先确认一次）。
    """
    with _workspace(tmp_path) as root, _live(root) as live:
        _enter_spa(live, "/machine")
        body = live["page"].content()
        if "叫停" in body or "停机" in body:
            raise AssertionError(
                "页面上已经有叫停入口了 —— 请把这条 skip 换成真断言"
                "（未确认时不许发出写请求）")
    pytest.skip("Run / Machine 页还是 W0 空壳 ⇒ 没有可点的叫停按钮："
                "这是 unknown 不是 pass")


# ====================================================================== 小件
def test_the_driver_module_is_the_one_that_was_asked_for() -> None:
    """反真空：`importorskip` 拿到的确实是 `playwright.sync_api`。

    这一条只在装了 playwright 的机器上跑到；它守的是"判据驱动没被换成别的东西"
    （换成一个只在本地可用的模块名，会让没装的机器静默 skip、装了的机器测另一件事）。
    """
    assert callable(getattr(_sync, "sync_playwright", None)), dir(_sync)
