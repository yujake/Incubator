# -*- coding: utf-8 -*-
"""浏览器端到端判据（裁定 F1：Playwright，opt-in）。
## 怎么跑（默认不跑）
pip install -e ".[browser]"     # pyproject 的 optional-dependencies: browser playwright install chromium     #
浏览器装在用户目录，不进仓python -m pytest -q -m browser tests/test_webui_browser.py
默认排除由 `pyproject.toml` 的 `addopts = "-m 'not network and not browser'"` 那一行负责（`draft/79` 的 T1 那条不一致已由主控落地修掉）。
这个文件自己再挂一次`pytestmark`，是为了"单独点这个文件跑"时也走同一条口径。
## 没装就是 `unknown` 不是 `pass`
`playwright` 没装 ⇒ 整个模块 `skip`，理由逐字写明这是 unknown 不是 pass（与 `-m network`、发布门 `unknown` 的处置同一条纪律：没查成不许记成通过）。
本文件第一版写的时候一次都没跑过（当时本机既没 playwright 也没浏览器），这一点当时写在报告里，没有假装它绿过。
2026-10-13（R88）起本机能真跑了：`pip install playwright` + 本机自带的Microsoft Edge（`_launch()` 的第二条路，`channel="msedge"`）。
这一天真跑过`python -m pytest -q -m browser tests/test_webui_browser.py`，读数记在那一轮的报告里。没装浏览器的机器上它照旧 `skip`（unknown，不是 pass）。
## 三条实况（写判据时量到的，决定了下面哪些格是 skip）
1. `GET /` 现在由 SPA 外壳提供（裁定 P1 的第一块，2026-10-07 落地）；`views.py` 已整件退场，
所以浏览器里 `#app` 那一层只在 SPA 回退路径（`/machine` 这类客户端路由，请求头带 `Accept: text/html`）上才挂得起来。
2. Machine 页的"写设置表单"与 Run 页的"叫停按钮"已经不是空壳了（R81 起）：
下面那两条原先 `skip` 的判据已经换成真断言 —— 设置表单永不回填 key、且 key 那一格是 `type=password`；叫停按钮第一次点击只"上膛"，盘上零改动。
3. 九页的逐页核对（R88）走真浏览器：每页都要挂起来、控制台不许有 error、
正文里不许出现 markdown 记号（`**`；密钥掩码 `***` 不算）。写面本身的浏览器侧读数（真浏览器来源去打那几个端点）见下面第 4/5/6 条。
"""

from __future__ import annotations

import json
import os
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
def _workspace(tmp_path: pathlib.Path) -> Iterator[pathlib.Path]:
    """一个最小工作区（写面那几条判据要一个能落盘的地方）。

    R88 修正：这一支原先写的是 `return root`，可是它挂着 `@contextmanager` ——
    生成器函数里 `return` 等于立刻收工，`contextlib` 拿到的是一个 `WindowsPath`
    而不是迭代器，于是每一条用例都在 `with` 那一行炸 `TypeError`。
    这个错误之所以能一直躺在这里，是因为本模块从来没有被跑过（没装 playwright
    就整模块 skip）。2026-10-13 装上 playwright 真跑，第一条就露了。
    """
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    yield root


#: 本机自带 Edge 的落点（`channel="msedge"` 认的就是它，不额外下载浏览器）。
EDGE = pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def _launch_kwargs() -> dict[str, str]:
    """挑一条起浏览器的路：先看盘上有什么，而不是"先起一次、失败再换一条"。

    为什么必须先在盘上判（2026-10-13 实测）：在同一个 `sync_playwright()` 上下文里
    让 `launch()` 失败一次，驱动的事件循环就废了 —— 后面每一次 `page.goto` 都报
    `Event loop is closed! Is Playwright already stopped?`，十一条判据会以
    "夹具坏了"的形态全红，看上去像产品缺陷。所以这里只读盘：
    playwright 自带那一份落在 `ms-playwright/chromium-*`，没有就退到本机 Edge。
    """
    cache = pathlib.Path(
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        or (pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home()))
            / "ms-playwright"))
    if cache.is_dir():
        for child in cache.iterdir():
            if child.name.startswith("chromium-") and child.is_dir():
                return {}
    if EDGE.is_file():
        return {"channel": "msedge"}
    return {}  # 两条都没有 ⇒ 让它如实失败，由 `_launch` 判 skip（unknown 不是 pass）


def _launch(pw: Any) -> Any:
    """起一个浏览器；两条路都没有 ⇒ `skip` 并写明"这是 unknown 不是 pass"。"""
    kwargs = _launch_kwargs()
    try:
        return pw.chromium.launch(**kwargs)
    except Exception as exc:  # noqa: BLE001 - 起不来就是"没查成"
        pytest.skip(
            f"浏览器起不来（试的是 {kwargs or 'playwright 自带 chromium'}）："
            f"{type(exc).__name__}: {exc} —— 浏览器端到端这一档是 unknown 不是 pass"
            f"（修法：`playwright install chromium`，或装 Microsoft Edge）")


@contextmanager
def _live(root: pathlib.Path, *, allow_writes: bool = True,
          settings_write: bool = True) -> Iterator[dict[str, Any]]:
    """起服务 + 起浏览器，产出 `{base, page, errors, csrf}`。

    浏览器起不来（自带 chromium 与 Edge 都没起来）⇒ `skip` 并写明理由：
    那是"没查成"，不是"查过了没问题"。

    R88 修正（同一处"没跑过所以没露"的坑）：收工顺序必须由我们自己定 ——
    `sync_playwright()` 用 `with` 写在这里的话，生成器一 `yield` 就出了那个 `with`，
    等用例跑完再恢复时驱动已经 `stop()`，`browser.close()` 于是报
    `Event loop is closed!`，每条用例都在收尾时炸（看上去像产品缺陷）。
    所以改成显式 `start()/stop()`：先关浏览器、再停驱动、最后关服务。
    """
    srv = W.serve(root, host="127.0.0.1", port=0, allow_writes=allow_writes,
                  settings_write=settings_write, csrf_token=CSRF)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://{srv.server_address[0]}:{srv.server_address[1]}"
    pw = _sync.sync_playwright().start()
    browser = None
    try:
        browser = _launch(pw)
        page = browser.new_page()
        errors: list[str] = []
        page.on("console",
                lambda m: errors.append(f"console.{m.type}: {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        yield {"base": base, "page": page, "errors": errors, "csrf": CSRF}
    finally:
        try:
            if browser is not None:
                browser.close()
        finally:
            pw.stop()
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
    （`/run/{sid}` 也在 W5 里改吐同一支外壳，所以"旧壳已退场"与"根页面已迁"两件事
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
    rows = audit.read_actions(root)
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
    assert audit.read_actions(root)[0]["ok"] is False, audit.read_actions(root)


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
    secret = "SENTINEL-browser-must-never-be-shown-0123456789"
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
        assert secret not in json.dumps(audit.read_actions(root), ensure_ascii=False), \
            "台账里出现了真 key"
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["model"]["api_key"] == secret, on_disk


# ====================================================================== 4 三格真断言
def test_the_settings_form_is_never_prefilled_with_the_key(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（`draft/73` §2.8 的表单那一半）：key 那一格既不回填，也不明文上屏。

    这一条原先 `skip`（Machine 页当时还是 W0 空壳）。R81 起设置表单落地，
    于是把它换成真断言，量三件事：
    1. 后端读了设置文件之后，那一格仍然是空的 —— 读数是 `***`，回填等于把
       `***` 写回文件（`ui/src/pages/Machine.tsx` 的 `presetOf` 特意把这一格排除）；
    2. 那一格的 `type` 是 `password`（输入时不上屏）；
    3. 盘上那份真 key 在整页 HTML 里一个字都不出现。
    """
    secret = "SENTINEL-machine-form-must-not-show-me-0123456789"
    target = tmp_path / "settings.json"
    monkeypatch.setenv(SET.ENV_SETTINGS, str(target))
    with _workspace(tmp_path) as root, _live(root, allow_writes=True) as live:
        _enter_spa(live, "/machine")
        # 先把真 key 写进盘上那份设置文件（走真浏览器来源的那条写面）
        got = _browser_post(live, "/api/settings",
                            {"model.api_key": secret, "confirm": "1"})
        assert got["status"] == 200, got
        live["page"].reload(wait_until="load")
        live["page"].wait_for_selector("#app > *", timeout=10_000)
        # 设置三段那一卡是 `/api/machine` 回来之后才画的（`#app > *` 只保证外壳在），
        # 所以等那一格本身出现，而不是等一个固定毫秒数（实测这处会偶发抢跑）。
        live["page"].wait_for_selector('input[type="password"]', timeout=10_000)
        box = live["page"].query_selector('input[type="password"]')
        assert box is not None, (
            "Machine 页没有 type=password 的那一格 —— key 输入框要么不在，"
            "要么被改成了明文")
        assert box.get_attribute("value") in (None, ""), (
            f"key 那一格被回填了：{box.get_attribute('value')!r}")
        html = live["page"].content()
        assert secret not in html, "页面里出现了真 key"
        assert SET.MASKED_KEY in html or "api_key" in html, "这一页根本没读设置"


def test_the_lean_switch_really_flips_it(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """真浏览器点「打开形式化」⇒ 盘上那一格真的变了、读数也跟着翻（R90）。

    业主 2026-10-13 的原话是「lean 开关网页上没法真的开关」。取证结论：后端一直是好的
    （`POST /api/settings` 写 `toolchain.lean_enabled=true` 之后 `settings.lean_enabled()`
    立刻回 `(True, "settings")`），缺的是台面 —— 这一页原先只画 `lean_ready`
    （机器装没装）与 `can_do_formal`，不画也不给那个开关。

    这一条从页面上点下去，一路量到三处：盘上那份设置文件、`settings.lean_enabled()`
    这个唯一口径、以及页面刷新后的读数（按钮的可用态就是读数的镜子）。
    """
    target = tmp_path / "settings.json"
    monkeypatch.setenv(SET.ENV_SETTINGS, str(target))
    monkeypatch.delenv(SET.ENV_LEAN_ENABLED, raising=False)
    # 盘上先有一份没有 `lean_enabled` 那一格的设置文件：这正是最常见的情形
    # （开关缺省 = 关），也正是"盘上没写"与"没读到"必须分得开的那一格。
    target.write_text(json.dumps({"toolchain": {"lean_bin": "_env/lean/bin"}}),
                      encoding="utf-8")
    with _workspace(tmp_path) as root, _live(root, allow_writes=True) as live:
        page = live["page"]
        _enter_spa(live, "/machine")
        page.wait_for_selector('input[type="password"]', timeout=10_000)
        assert SET.lean_enabled() == (False, ""), "初态不是缺省档，这条判据的前提变了"
        body = page.inner_text("body")
        assert "形式化开关" in body, "页面上没有开关那一行"
        assert "缺省（设置文件里没写这一格）" in body, body[:400]
        assert "（盘上没写）" in body, (
            "设置三段里那一格缺席的键显成了 unknown（读到了空 ≠ 没读到）")
        assert not page.get_by_role("button", name="打开形式化").is_disabled(), \
            "开关是关的，'打开形式化'却点不动"

        page.get_by_role("button", name="打开形式化").click()
        page.wait_for_timeout(200)
        page.get_by_role("button", name="确认打开形式化").click()
        page.wait_for_timeout(700)
        on_disk = json.loads(target.read_text(encoding="utf-8"))
        assert str(on_disk["toolchain"]["lean_enabled"]).lower() == "true", on_disk
        assert SET.lean_enabled() == (True, "settings"), SET.lean_enabled()
        assert "设置文件 toolchain.lean_enabled" in page.inner_text("body"), \
            "打开之后页面上的来源没变（读数没跟着翻）"

        page.get_by_role("button", name="关闭形式化").click()
        page.wait_for_timeout(200)
        page.get_by_role("button", name="确认关闭形式化").click()
        page.wait_for_timeout(700)
        on_disk2 = json.loads(target.read_text(encoding="utf-8"))
        assert str(on_disk2["toolchain"]["lean_enabled"]).lower() == "false", on_disk2
        assert SET.lean_enabled() == (False, "settings"), SET.lean_enabled()


def test_the_page_says_when_the_env_var_overrides_the_lean_switch(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量压着设置文件时，页面必须说出来（R90）。

    `settings.lean_enabled()` 的取值梯子是 环境变量 > 设置文件 > 缺省（唯一口径）。
    带着 `AGENTFLOW_LEAN_ENABLED=1` 起服务时，网页上写设置文件不会改变这一档 ——
    这正是"我改了，它不动"最容易发生的地方，所以页面上必须写清，而不是让用户以为开关坏了。

    两处读数一起量：页面上那句提醒在，且写完之后唯一口径仍然回 `env`。
    """
    target = tmp_path / "settings.json"
    monkeypatch.setenv(SET.ENV_SETTINGS, str(target))
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    with _workspace(tmp_path) as root, _live(root, allow_writes=True) as live:
        page = live["page"]
        _enter_spa(live, "/machine")
        page.wait_for_selector('input[type="password"]', timeout=10_000)
        assert SET.lean_enabled() == (True, "env"), SET.lean_enabled()
        body = page.inner_text("body")
        assert "环境变量 AGENTFLOW_LEAN_ENABLED" in body, body[:400]
        assert "不会改变这一档" in body, "页面上没说环境变量压着设置文件"
        assert page.get_by_role("button", name="打开形式化").is_disabled(), \
            "环境变量已经把它打开了，'打开形式化'还点得动"

        page.get_by_role("button", name="关闭形式化").click()
        page.wait_for_timeout(200)
        page.get_by_role("button", name="确认关闭形式化").click()
        page.wait_for_timeout(700)
        assert SET.lean_enabled() == (True, "env"), (
            "写设置文件竟然盖住了环境变量 —— 取值梯子变了？")


def test_no_settings_input_is_prefilled_with_the_word_unknown(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """设置窗口那几格不许被填上字面量 `unknown`（R90，这一条是业主报的那件事的真身）。

    取证（本机 2026-10-13，真浏览器读输入框的 `value`）：盘上没写的四格—— `toolchain.coq_bin` / `toolchain.isabelle_bin` /
    `toolchain.lean_enabled` /`workspace.projects_dir` —— 全被填上了 `unknown`。原因是输入框初值走了`currentOf()` → `field()` →
    `cell()`，而 `cell("")` 的口径是 `unknown`（那一套是给读数表用的）。用户一按「写这些设置」，
    盘上就多出`lean_enabled: "unknown"` 这类值：`settings.lean_enabled()` 对词表外的值抛错，开关从此读不出来 —— 「lean 开关网页上没法真的开关」正是这一条。

    这一条量两处：每一格的 `value` 只能是"盘上真有的值"或空串；按一次「写这些设置」之后，盘上那份文件里只多出用户真填的那一格，一个 `unknown` 都不许落盘。
    """
    target = tmp_path / "settings.json"
    monkeypatch.setenv(SET.ENV_SETTINGS, str(target))
    monkeypatch.delenv(SET.ENV_LEAN_ENABLED, raising=False)
    target.write_text(json.dumps({"toolchain": {"lean_bin": "_env/lean/bin"}}),
                      encoding="utf-8")
    with _workspace(tmp_path) as root, _live(root, allow_writes=True) as live:
        page = live["page"]
        _enter_spa(live, "/machine")
        page.wait_for_selector('input[type="password"]', timeout=10_000)
        rows = page.eval_on_selector_all(
            "label.opt",
            """ls => ls.map(l => {
                 const i = l.querySelector('input');
                 const s = l.querySelector('span');
                 return {key: s ? s.textContent : '?', value: i ? i.value : null};
               })""")
        assert len(rows) >= 10, rows
        bad = [r for r in rows if r["value"] == "unknown"]
        assert bad == [], f"这些格被填上了字面量 unknown：{bad}"
        by_key = {r["key"]: r["value"] for r in rows}
        assert by_key["toolchain.lean_bin"] == "_env/lean/bin", by_key
        for key in ("toolchain.coq_bin", "toolchain.isabelle_bin",
                    "toolchain.lean_enabled", "workspace.projects_dir"):
            assert by_key[key] == "", (key, by_key[key])

        # 一格都不填 ⇒ 按钮点不动（口径：空串 = 这一格不动）
        assert page.get_by_role("button", name="写这些设置").is_disabled(), \
            "一格都没填，'写这些设置'却点得动 —— 空串的口径被破坏了"
        # 真填一格再写：盘上只多这一格
        page.fill('label.opt:has(span:text-is("model.name")) input', "deepseek-chat")
        page.get_by_role("button", name="写这些设置").click()
        page.wait_for_timeout(200)
        page.get_by_role("button", name="确认写这些设置").click()
        page.wait_for_timeout(700)
        on_disk = json.loads(target.read_text(encoding="utf-8"))
        assert json.dumps(on_disk, ensure_ascii=False).find("unknown") < 0, on_disk
        assert on_disk["toolchain"].get("lean_enabled") != "unknown", on_disk
        assert on_disk["model"]["name"] == "deepseek-chat", on_disk
        assert on_disk["toolchain"]["lean_bin"] == "_env/lean/bin", on_disk
        assert SET.lean_enabled() == (False, ""), SET.lean_enabled()


def test_the_stop_button_is_on_the_live_page_and_really_stops(
        tmp_path: pathlib.Path) -> None:
    """R93（业主：「网页中没找到停机开关」）：叫停按钮长在「在飞」页，且点了真的落开关。

    取证：这一对按钮此前只长在「一趟详情」（`/run/{sid}`）里，而人要叫停时待的
    往往是「在飞」那一页 —— 于是用户的原话是"网页中没找到停机开关"。
    这一条量三件事：按钮在「在飞」页真的画出来了；第一次点击只"上膛"（盘上零改动）；
    第二次点击才落 `.agentflow-stop` 并留下一条写台账。
    """
    with _workspace(tmp_path) as root, _live(root, allow_writes=True) as live:
        page = live["page"]
        _enter_spa(live, "/live")
        stop = page.get_by_role("button", name="叫停这一趟")
        stop.wait_for(timeout=10_000)
        stop.click()
        page.wait_for_timeout(200)
        assert SC.read_stop(root) is None, "第一次点击就落了停机开关 —— 确认那一格是空的"
        page.get_by_role("button", name="确认叫停这一趟").click()
        page.wait_for_timeout(700)
        assert SC.read_stop(root) is not None, "确认之后停机开关没落盘"
        rows = audit.read_actions(root)
        assert rows and rows[-1]["endpoint"] == "/api/stop", rows


def test_the_stop_button_asks_for_confirmation_before_calling_stop(
        tmp_path: pathlib.Path) -> None:
    """正控（`draft/73` §2.8 的 `test_stop_requires_confirmation`）：叫停要按两下。

    这一条原先 `skip`（当时没有可点的叫停按钮）。R88 起 Run 页的「停机」卡片有
    真按钮（`POST /api/stop`），于是量真行为：第一次点击只"上膛"（页面上出现
    「确认叫停这一趟」并把影响写出来），盘上零改动；第二次点击才落停机开关，
    并且写台账多一行。
    """
    with _workspace(tmp_path) as root, _live(root, allow_writes=True) as live:
        _enter_spa(live, "/run/demo-sid")
        live["page"].get_by_role("button", name="叫停这一趟").click()
        live["page"].wait_for_timeout(300)
        assert SC.read_stop(root) is None, "第一次点击就落了停机开关 —— 确认那一格是空的"
        assert audit.read_actions(root) == [], audit.read_actions(root)
        assert live["page"].get_by_role("button", name="确认叫停这一趟") is not None
        live["page"].get_by_role("button", name="确认叫停这一趟").click()
        live["page"].wait_for_timeout(600)
        assert SC.read_stop(root) is not None, "确认之后停机开关没落盘"
        rows = audit.read_actions(root)
        assert len(rows) == 1 and rows[0]["ok"] is True, rows


# ============================================================ 5 业主报过的那两处
def test_the_budget_set_button_really_writes_the_register(tmp_path: pathlib.Path) -> None:
    """真浏览器里点「重设总额」⇒ 盘上寄存器真的写下 `kind="set"`。

    业主 2026-10-13 报的原话是「预算页『重设金额』用不了」。后端一直是好的
    （`POST /api/budget` 的 `action=set` 实测 200），坏的是前端：原先靠一个原生
    `select` 切动作，选完再按同一个按钮 —— 那一下在浏览器里切不过去。R81 改成两个
    各自带 action 的 `ConfirmButton`。这条判据就从页面上点，一路量到盘上那份
    `budget.json`，并且顺带量"追加"那一支（两条路子都通才算修好了）。

    这一条不需要拦网络：改预算是纯本地写，不花钱、不起进程。
    """
    from agentflow import budget as B

    with _workspace(tmp_path) as root, _live(root, allow_writes=True) as live:
        page = live["page"]
        _enter_spa(live, "/budget")
        page.wait_for_selector("input", timeout=10_000)
        amount = page.locator("input").first  # 这一卡里第一个输入框就是金额
        amount.fill("3")
        page.get_by_role("button", name="重设总额").click()
        page.wait_for_timeout(200)
        page.get_by_role("button", name="确认重设总额").click()
        page.wait_for_timeout(500)
        reg = B.read_register(root)
        assert reg.get("total_usd") == 3.0, reg
        added = reg.get("added") or []
        assert added and added[-1].get("kind") == "set", reg
        assert "成了" in page.inner_text("body"), "回执没有原样显示"

        # 追加那一支（同一页、同一份寄存器）
        amount = page.locator("input").first
        amount.fill("1.5")
        page.get_by_role("button", name="追加额度").click()
        page.wait_for_timeout(200)
        page.get_by_role("button", name="确认追加额度").click()
        page.wait_for_timeout(500)
        reg2 = B.read_register(root)
        assert reg2.get("total_usd") == 4.5, reg2  # 3.0 追加 1.5
        kinds = [row.get("kind") for row in (reg2.get("added") or [])]
        assert kinds[-1] == "add", reg2


# ============================================================ 6 两处"跟系统说话"的入口
def test_the_chat_box_routes_the_message_by_state(tmp_path: pathlib.Path) -> None:
    """对话框（R94，业主：「要把前端做成对话框」）：同一个输入框按当刻状态走对的那条路。

    量四条路，逐条对应一条真端点：还没有会话 ⇒ 这一句起一趟（`POST /api/run`，`task=` 就是这句话）；
    2. 这一段收过工、闲着 ⇒ 先把话记进收件箱（`POST /api/task`），再用
    同一句话任务唤醒它（`POST /api/run` 带 `sid` + `resume=1`）——任务原文必须逐字相同（`resume_messages` 按它挑重建窗口，换了就是另一趟）；
    3. M 在飞（会话里一条没配对的 `agent_run_start`）⇒ 只插话，不许顺手又起一趟；
    4. 有提问在等回答 ⇒ `POST /answer`（带那一条自己的 qid + sid），
    而且这一下真的落盘 —— 这一段不拦网络（回答不花钱）。

    `POST /api/run` 真打下去会真起一趟（花预算）：前三条把 `/api/run` 在页面里拦下来喂一份真实形状的回执。拦的是网络，不是按钮 —— 按钮、两次确认、取数、渲染走的还是页面自己那一条路。
    """
    import urllib.parse

    from agentflow import sessions as SS
    from agentflow import userio as U

    sent: list[tuple[str, str]] = []

    def _fake(route: Any) -> None:
        req = route.request
        sent.append((req.url.split("/api/")[-1].split("?")[0], req.post_data or ""))
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": True, "tri": "computed",
                                       "reason": "拦下来喂的回执（没有真起一趟）"},
                                      ensure_ascii=False))

    def _form(where: str, field: str) -> str:
        for path, raw in sent:
            if path == where:
                return (urllib.parse.parse_qs(raw).get(field) or [""])[0]
        return ""

    def _say(page: Any, text: str) -> None:
        box = page.locator("input.input")
        box.wait_for(timeout=10_000)
        box.fill(text)

    with _workspace(tmp_path) as root, _live(root, allow_writes=True) as live:
        page = live["page"]
        # 两条写端点都拦下来：`/api/run` 会真起一趟（花预算），`/api/task` 会真写
        # 一条插话 —— 它们在 `test_webui_writes.py` 里各有真读数的判据，这一条只量
        # "同一个框在四种状态下把话送到哪一条端点"。拦的是网络，不是按钮：
        # 按钮、两次确认、取数、渲染走的还是页面自己那一条路。
        page.route("**/api/run", _fake)
        page.route("**/api/task", _fake)

        # 一、还没有会话 ⇒ 起一趟（点两次：它会花钱）
        _enter_spa(live, "/")
        _say(page, "帮我把工作区里那篇论文从头到尾审核一遍。")
        say = page.get_by_role("button", name="送出")
        assert say.is_disabled() is False, "写了字之后送出按钮还是点不动"
        say.click()
        page.wait_for_timeout(200)
        assert sent == [], f"第一次点击就发了请求：{sent}"
        page.get_by_role("button", name="确认送出").click()
        page.wait_for_timeout(500)
        assert [p for p, _raw in sent] == ["run"], sent
        assert "task=" in sent[0][1], sent[0][1]
        # 起一趟那一支不许带 --resume（表单里那一格恒在，但必须是空的）
        assert _form("run", "resume") == "", sent[0][1]
        assert _form("run", "sid") == "", sent[0][1]

        # 二、一段收过工的会话 ⇒ 记进收件箱 + 用原来那句话唤醒它
        SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "原来那句话",
                         "summoned_by": "M", "depth": 1,
                         "ts": "2026-10-13T10:00:00+08:00"}, sid="s-idle")
        SS.append(root, {"kind": "agent_run_end", "role": "M", "stop_reason": "final",
                         "final": "收工了", "ts": "2026-10-13T10:05:00+08:00"}, sid="s-idle")
        sent.clear()
        _enter_spa(live, "/")
        _say(page, "接着说：先看第二节。")
        page.get_by_role("button", name="送出").click()
        page.wait_for_timeout(200)
        assert sent == [], f"第一次点击就发了请求：{sent}"
        page.get_by_role("button", name="确认送出").click()
        page.wait_for_timeout(800)
        assert [p for p, _raw in sent] == ["task", "run"], sent
        assert _form("run", "resume") == "1", sent
        assert _form("run", "sid") == "s-idle", sent
        assert _form("run", "task") == "原来那句话", (
            f"续跑带的不是原来那句话：{sent}")
        assert _form("task", "body") == "接着说：先看第二节。", sent

        # 三、M 在飞（一条没配对的 run_start）⇒ 只插话
        SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "那一趟",
                         "summoned_by": "M", "depth": 1,
                         "ts": "2026-10-13T11:00:00+08:00"}, sid="s-live")
        sent.clear()
        _enter_spa(live, "/")
        _say(page, "插一句：别扩大范围。")
        page.get_by_role("button", name="送出").click()
        page.wait_for_timeout(800)
        assert [p for p, _raw in sent] == ["task"], sent
        assert _form("task", "body") == "插一句：别扩大范围。", sent

        # 四、有提问在等回答 ⇒ /answer（真落盘）
        sent.clear()
        U.ask_user(root, role="M", question="口径用哪一档？",
                   options=({"label": "第二档", "description": "可复核即可"},),
                   sid="s-live", timeout_sec=0, wait=False)
        qid = U.pending_questions(root, sid="s-live")[0].qid
        _enter_spa(live, "/")
        page.wait_for_selector(f"#q-s-live-{qid}", timeout=10_000)
        page.locator(f"#q-s-live-{qid} button").first.click()
        page.wait_for_timeout(800)
        events, _bad = SS.read_session(root, sid="s-live")
        answers = [e for e in events if e.get("kind") == U.ANSWER_KIND]
        assert [a.get("qid") for a in answers] == [qid], answers
        assert "第二档" in str(answers[0].get("answer")), answers[0]


# ============================================================ 6 九页逐页核对（R88）
#: 九页的客户端路由（`ui/src/main.tsx` 的路由表；`/run/:sid` 用一个不存在的会话号，
#: 页面照样要挂起来 —— 它那时该显"读不出来"，不是白屏）。
ROUTES = ("/", "/live", "/budget", "/evidence", "/artifacts", "/acceptance",
          "/machine", "/help", "/run/demo-sid")


def test_every_page_mounts_clean_and_prints_no_markdown_markers(
        tmp_path: pathlib.Path) -> None:
    """逐页核对（R88）：九页都要挂起来、控制台不許有 error、正文里不許有 markdown 记号。

    为什么这一条必须在真浏览器里：`**` 这类记号是上屏之后才看得见的缺陷 ——
    本机 2026-10-13 就是这样逮到验收页那两处的（`reviewaccept` 的话被逐字打印）。
    静态扫源码只能守住前端那一半，后端产出的话只有渲染出来才知道。

    `***` 是密钥掩码（`ModelSpec.redacted` / `SET.MASKED_KEY`），不是 markdown：
    先把 `***` 从正文里去掉再找 `**`，免得把"key 配了"这件如实读数判成缺陷。
    """
    with _workspace(tmp_path) as root, _live(root, allow_writes=True) as live:
        page = live["page"]
        for route in ROUTES:
            live["errors"].clear()
            _enter_spa(live, route)
            page.wait_for_timeout(250)
            body = page.inner_text("body")
            clean = body.replace("***", "")
            where = clean.find("**")
            assert where < 0, (
                f"{route} 的正文里有 markdown 记号："
                f"{clean[max(0, where - 60):where + 60]!r}")
            assert body.strip() != "", f"{route} 是白屏（正文一个字都没有）"
            assert "[object Object]" not in body, (
                f"{route} 的正文里印出了 `[object Object]` —— 有一个对象被 String() 了"
                "（本机实测：Mathlib 探针那一格曾经就是这样）")
            assert page.eval_on_selector("#app", "n => n.children.length") > 0, \
                f"{route} 的 #app 里一个子节点都没有"
            noisy = [e for e in live["errors"] if "favicon" not in e]
            assert noisy == [], f"{route} 的控制台有 error：{noisy}"


def test_every_page_has_the_nav_and_at_least_one_card(tmp_path: pathlib.Path) -> None:
    """反真空：九页每一页都从导航进得去，而且正文里真有卡片。

    没有这一条，上面那条可以靠"每页都渲染同一张空白卡片"或"整页只有导航"变绿 ——
    所以这里加两条下限：导航八条都在（`ui/src/main.tsx` 的 `NAV`），
    且每一页至少有一张卡片标题（`.card-title`）。
    """
    with _workspace(tmp_path) as root, _live(root) as live:
        page = live["page"]
        for route in ROUTES:
            _enter_spa(live, route)
            page.wait_for_timeout(200)
            links = page.eval_on_selector_all("nav a", "ns => ns.map(n => n.textContent)")
            assert len(links) >= 8, f"{route} 上导航只有 {links}"
            titles = page.eval_on_selector_all(
                ".card-title", "ns => ns.map(n => n.textContent)")
            assert titles, f"{route} 上一张卡片都没有（正文是空的）"


# ====================================================================== 小件
def test_the_driver_module_is_the_one_that_was_asked_for() -> None:
    """反真空：`importorskip` 拿到的确实是 `playwright.sync_api`。

    这一条只在装了 playwright 的机器上跑到；它守的是"判据驱动没被换成别的东西"
    （换成一个只在本地可用的模块名，会让没装的机器静默 skip、装了的机器测另一件事）。
    """
    assert callable(getattr(_sync, "sync_playwright", None)), dir(_sync)
