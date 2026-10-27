# -*- coding: utf-8 -*-
"""静态路由与前端产物：判据（W0 的判据 ①③ 落在这里，`draft/73` §2.7 与 §1.3）。这一组守什么：`webui/server.py` 在本批新增了静态路由 `GET /static/<file>` 与 SPA
回退（裁定 Q1），而前端产物按裁定 B1 要入库。两件事各需要机器读数：

| 判据 | 查什么 |
|---|---|
| 静态路由 | 只服务静态根之下的真实文件；content-type 按扩展名；带哈希 ⇒ immutable，其余 no-store |
| 目录穿越 | `..%2f` 一类解出来落到根外 ⇒ 必须 404，而且不许泄漏根外内容（负控） |
| 静态未命中 | 一个不存在的 `.js` 不许回落到 `index.html`（那会让浏览器拿 HTML 当脚本解析） |
| `/api/*` 未知 | 一律 JSON 404（GET 与 POST 都是），哪怕客户端明说要 HTML（裁定 Q1） |
| SPA 回退 | 只有 `Accept` 含 `text/html` 且 `index.html` 在盘上才吐外壳，否则 404 |
| 令牌 | `ui/index.html` 里只有 `__CSRF__` 占位符，没有真令牌；产物里的外壳同样只有占位符 |
| 产物自洽 | 产物里的 `index.html` 引用的每个 `/static/*` 都真的存在 |
| 产物新鲜度 | 提交的 `web/static/**` 与"重新构建一次"的结果逐文件一致（手改一个字节必红） |

为什么新鲜度分两半：与"重新构建"比对需要 node（没装 ⇒ 记 `unknown`，不记 pass：`pytest.skip` 的理由里写明是哪一档没查成）；- 而"手改产物一个字节"这件事不该等到有 node 才发现得了：
所以比对逻辑（`_tree_problems`）抽成纯函数，并用两份临时目录做负控 —— 那条负控不需要 node，它证明的是"这条判据真的会红"，而不是"这次没红"。
为什么测试里用临时静态根：`serve(..., static_root=...)` 可注入（见 :func:`agentflow.webui.serve`），于是判据可以在一份假产物上把每一条路都走一遍，
不必依赖"这台机器上构建成功了没有"。真产物那一支另有两条判据，产物不在盘上时它们 skip 并写明理由。
"""

from __future__ import annotations

import hashlib
import http.client
import json
import pathlib
import re
import shutil
import subprocess
import threading
from contextlib import contextmanager
from typing import Iterator

import pytest

from agentflow import webui as W
from agentflow.webui import server

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
#: 前端工程根与它的产物落点（裁定 B1）。
UI = REPO / "ui"
STATIC = REPO / "src" / "agentflow" / "web" / "static"
INDEX_HTML = UI / "index.html"

#: 静态路由要服务的扩展名 → content-type（与 `webui/server.py` 的表逐条对应）。
_EXPECTED_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".txt": "text/plain",
}


# ====================================================================== 夹具
@contextmanager
def _server(root: pathlib.Path, static_root: pathlib.Path) -> Iterator[str]:
    """在临时端口上起一个服务（`static_root` 指到临时目录：判据不碰真产物）。"""
    srv = W.serve(root, host="127.0.0.1", port=0, static_root=static_root,
                  csrf_token="testtoken0123456789")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address[0], srv.server_address[1]
    try:
        yield f"{host}:{port}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _get(base: str, path: str, *, accept: str = "") -> tuple[int, str, str, str]:
    """一次 GET：返回 `(状态码, 正文, content-type, cache-control)`。"""
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        headers = {"Accept": accept} if accept else {}
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        return (resp.status, resp.read().decode("utf-8", errors="replace"),
                resp.getheader("Content-Type") or "",
                resp.getheader("Cache-Control") or "")
    finally:
        conn.close()


def _post(base: str, path: str) -> tuple[int, str, str]:
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        conn.request("POST", path, body=b"", headers={"Content-Length": "0"})
        resp = conn.getresponse()
        return (resp.status, resp.read().decode("utf-8", errors="replace"),
                resp.getheader("Content-Type") or "")
    finally:
        conn.close()


def _fake_static(tmp: pathlib.Path) -> pathlib.Path:
    """一份假产物：外壳 + 每种扩展名一个带哈希的文件 + 一个根外的秘密文件。

    一律用 `write_bytes`：文本模式的 `write_text` 在 Windows 上会把 `\n` 翻成
    `\r\n`，于是"服务端原样吐出来的字节"与"盘上读回来的文本"对不上 —— 那是夹具
    的坑，不是被测代码的问题。用字节写、用字节读，比的就是真的同一批字节。
    """
    static = tmp / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_bytes(
        b'<!DOCTYPE html><html><body><div id="app">\xe5\xa3\xb3</div>'
        b'<meta name="csrf-token" content="__CSRF__"></body></html>\n')
    for name, body in (("main.abcdef123456.js", 'console.log("壳");\n'),
                       ("app.abcdef123456.mjs", 'export const x = 1;\n'),
                       ("app.abcdef123456.css", "body{margin:0}\n"),
                       ("data.abcdef123456.json", '{"ok":true}\n'),
                       ("logo.abcdef123456.svg", "<svg></svg>\n"),
                       ("main.js", "// 不带哈希\n"),
                       ("blob.bin", "not-a-known-type\n")):
        (static / "assets" / name).write_bytes(body.encode("utf-8"))
    (tmp / "secret.txt").write_bytes(b"TOP-SECRET\n")
    return static


# ====================================================================== 根路径 = SPA 外壳
def test_the_root_path_serves_the_spa_shell_with_the_token_injected(
        tmp_path: pathlib.Path) -> None:
    """正控（P1 的第一块迁移）：`GET /` 与 `GET /index.html` 吐 SPA 外壳 + 注入令牌。

    这一格原来是服务端渲染的旧壳。为什么必须改：SPA 只在"未知路径"的回退分支上
    挂得起来，而 `/` 是已知路径 ⇒ 不改这一格，浏览器地址栏就永远进不了 SPA 首页。

    三样机器读数：`#app` 挂载点、盘上的 `__CSRF__` 被换成本进程的令牌、`no-store`。
    """
    root = tmp_path / "ws"
    root.mkdir()
    static = _fake_static(tmp_path)
    with _server(root, static) as base:
        for path in ("/", "/index.html"):
            code, body, ctype, cache = _get(base, path)
            assert code == 200, (path, code)
            assert ctype.startswith("text/html"), (path, ctype)
            assert '<div id="app">' in body, (path, body[:200])
            assert "testtoken0123456789" in body, "CSRF 占位符没被注入（外壳那条路漏了）"
            assert "__CSRF__" not in body, (path, "占位符还在（注入没发生）")
            assert cache == "no-store", (path, cache)


def test_the_root_path_says_so_when_the_shell_is_not_built(tmp_path: pathlib.Path) -> None:
    """负控（P1 迁移的诚实面）：外壳不在盘上 ⇒ `/` 是 404 + 一句说清为什么。

    不许静默给一支空白页：「前端还没构建」与「页面坏了」必须分得开（三态纪律）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    empty = tmp_path / "empty-static"
    empty.mkdir()
    with _server(root, empty) as base:
        code, body, ctype, _cache = _get(base, "/")
        assert code == 404, code
        assert ctype.startswith("text/html"), ctype
        assert "前端外壳不在盘上" in body, body[:300]
        # 未知路径的回退同样如此（那时走的是另一条分支）
        code2, body2, _c2, _cache2 = _get(base, "/evidence", accept="text/html")
        assert code2 == 404, code2
        assert "404" in body2, body2[:200]


# ====================================================================== 静态路由
def test_static_route_serves_real_files_with_the_right_content_type(
        tmp_path: pathlib.Path) -> None:
    """正控（静态路由）：真实文件服务得出来，content-type 按扩展名，哈希 ⇒ immutable。

    为什么 content-type 要逐条查：静态路由猜错类型是"页面全白"的经典成因
    （浏览器按 `nosniff` 严格执行，猜错就拒绝执行），而它在服务端一声不吭。
    """
    root = tmp_path / "ws"
    root.mkdir()
    static = _fake_static(tmp_path)
    # 逐条列出来（不靠"猜扩展名"）：每一条都要真的在盘上，否则这条正控是假的
    cases = (
        ("assets/main.abcdef123456.js", ".js"),
        ("assets/app.abcdef123456.mjs", ".mjs"),
        ("assets/app.abcdef123456.css", ".css"),
        ("assets/data.abcdef123456.json", ".json"),
        ("assets/logo.abcdef123456.svg", ".svg"),
    )
    with _server(root, static) as base:
        for rel, ext in cases:
            target = static / rel
            assert target.is_file(), f"夹具少了 {rel}"
            code, body, ctype, cache = _get(base, f"/static/{rel}")
            assert code == 200, (rel, code)
            assert body == target.read_bytes().decode("utf-8"), rel
            assert ctype.startswith(_EXPECTED_TYPES[ext]), (rel, ctype)
            assert cache.startswith("public, max-age=") and "immutable" in cache, (rel, cache)

        # 外壳（不带哈希）⇒ no-store：它是"每次都要回服务端拿"的那一份
        code, shell, ctype, cache = _get(base, "/static/index.html")
        assert code == 200 and ctype.startswith("text/html"), (code, ctype)
        assert cache == "no-store", cache
        assert "testtoken0123456789" in shell and "__CSRF__" not in shell

        # 认不出来的扩展名 ⇒ octet-stream（猜错的类型比不认识的类型更危险）
        code, _body, ctype, _cache = _get(base, "/static/assets/blob.bin")
        assert code == 200 and ctype.startswith("application/octet-stream"), (code, ctype)

        # 不带哈希 ⇒ 不许长缓存（改名即失效的前提是"名字里带内容哈希"）
        code, _body, _ctype, cache = _get(base, "/static/assets/main.js")
        assert code == 200 and cache == "no-store", (code, cache)

        # 每一个响应都带 nosniff
        conn = http.client.HTTPConnection(base, timeout=10)
        try:
            conn.request("GET", "/static/assets/main.js")
            resp = conn.getresponse()
            assert resp.getheader("X-Content-Type-Options") == "nosniff"
            resp.read()
        finally:
            conn.close()


def test_static_route_rejects_directory_traversal(tmp_path: pathlib.Path) -> None:
    """负控（目录穿越）：`..%2f` 一类解出来落到根外 ⇒ 404，且不许泄漏根外内容。

    `draft/73` §2.7 点名要有这条负控：`Path.resolve()` 之后必须仍在静态根内。
    """
    root = tmp_path / "ws"
    root.mkdir()
    static = _fake_static(tmp_path)
    with _server(root, static) as base:
        for path in ("/static/..%2fsecret.txt", "/static/../secret.txt",
                     "/static/%2e%2e%2fsecret.txt", "/static/assets/../../secret.txt",
                     "/static/..%2f..%2fsecret.txt",
                     "/static/%2e%2e/%2e%2e/secret.txt"):
            code, body, _ctype, _cache = _get(base, path)
            assert code == 404, (path, code)
            assert "TOP-SECRET" not in body, (path, body[:200])
        # 反真空：根内那个真文件是拿得到的（否则上面那条"拒"可能只是"什么都拒"）
        assert _get(base, "/static/assets/main.abcdef123456.js")[0] == 200


def test_static_route_never_falls_back_to_the_shell(tmp_path: pathlib.Path) -> None:
    """负控（静态未命中）：不存在的 `.js` 必须 404，不许回落 `index.html`。

    回落会让浏览器把一支 HTML 当脚本解析 —— 静默全白，而服务端返回 200。
    """
    root = tmp_path / "ws"
    root.mkdir()
    static = _fake_static(tmp_path)
    with _server(root, static) as base:
        for path in ("/static/assets/nope.js", "/static/nope.css", "/static/a/b/c.js"):
            code, body, ctype, _cache = _get(base, path, accept="text/html")
            assert code == 404, (path, code)
            assert 'id="app"' not in body, (path, body[:200])
            assert not ctype.startswith("text/javascript"), (path, ctype)


def test_unknown_api_paths_never_return_html(tmp_path: pathlib.Path) -> None:
    """负控（裁定 Q1）：`/api/*` 未知 ⇒ JSON 404，哪怕客户端明说要 HTML。

    前端要靠这个区分"没这个端点"与"这是一张网页"；吐 HTML 会让它在
    `JSON.parse` 上炸，而错误信息指向一个不相干的地方。
    """
    root = tmp_path / "ws"
    root.mkdir()
    static = _fake_static(tmp_path)
    with _server(root, static) as base:
        code, body, ctype, _cache = _get(base, "/api/nope", accept="text/html")
        assert code == 404, code
        assert ctype.startswith("application/json"), ctype
        parsed = json.loads(body)
        assert parsed["ok"] is False and parsed["tri"] == "not_applicable", parsed
        assert "<html" not in body.lower(), body[:200]
        # POST 也一样（写面没有 SPA 回退这回事）
        code2, body2, ctype2 = _post(base, "/api/nope")
        assert code2 == 404 and ctype2.startswith("application/json"), (code2, ctype2)
        assert "<html" not in body2.lower(), body2[:200]


def test_spa_fallback_only_answers_clients_that_want_html(tmp_path: pathlib.Path) -> None:
    """正控（裁定 Q1 的收窄）：要 HTML 的客户端拿到外壳；其余拿到诚实的 404。

    为什么要有这条收窄：Q1 说"其余未知路径吐 index.html"，而既有判据
    `tests/test_webui.py::test_unknown_paths_and_methods` 要求 `GET /nope` 是 404。
    两条同时成立的唯一做法就是按 `Accept` 分流（浏览器地址栏一定带 `text/html`）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    static = _fake_static(tmp_path)
    with _server(root, static) as base:
        code, body, ctype, _cache = _get(base, "/evidence",
                                        accept="text/html,application/xhtml+xml")
        assert code == 200 and ctype.startswith("text/html"), (code, ctype)
        assert 'id="app"' in body and "testtoken0123456789" in body
        assert _get(base, "/nope")[0] == 404
        assert _get(base, "/nope", accept="application/json")[0] == 404

    # 没有 index.html 时（例如前端还没构建）：退回今天的 404 页
    empty = tmp_path / "empty-static"
    empty.mkdir()
    with _server(root, empty) as base2:
        code3, body3, _c3, _cache3 = _get(base2, "/evidence", accept="text/html")
        assert code3 == 404, code3
        assert "404" in body3, body3[:200]


# ====================================================================== 令牌
def test_the_index_html_source_has_no_real_token() -> None:
    """正控（令牌不从盘上来）：`ui/index.html` 里只有占位符，没有真令牌。

    裁定 B1 把构建产物入库 ⇒ 写死一个令牌等于把它连同产物一起发布出去。
    产物里的 `index.html` 同样只许有占位符（服务端在吐它时替换）。
    """
    if not INDEX_HTML.is_file():
        pytest.skip("前端骨架尚未落地：ui/index.html 不在盘上")
    src = INDEX_HTML.read_text(encoding="utf-8")
    assert "__CSRF__" in src, "index.html 里没有 CSRF 占位符"
    tokens = re.findall(r'name="csrf-token"\s+content="([^"]*)"', src)
    assert tokens == ["__CSRF__"], tokens
    built = STATIC / "index.html"
    if built.is_file():
        text = built.read_text(encoding="utf-8")
        assert "__CSRF__" in text, (
            "产物里的 index.html 没有占位符（服务端就无处替换）")


# ====================================================================== 产物
def test_the_built_assets_are_self_consistent_if_they_are_on_disk() -> None:
    """正控（产物自洽）：产物里 `index.html` 引用的每个本地资源都真的存在。

    本批的实况：构建产物可能不在盘上（`vite build` 需要 esbuild 起子进程，
    而本沙箱不允许 Node 的管道 stdio）⇒ 那时这条 skip，理由写明"产物不在盘上"，
    绝不把"没查成"折成"查过了没问题"。
    """
    index = STATIC / "index.html"
    if not index.is_file():
        pytest.skip("构建产物不在盘上（web/static/index.html 不存在）—— "
                    "B1 的产物要么还没构建，要么构建被环境挡住；这条判据在产物入库后自动生效")
    text = index.read_text(encoding="utf-8")
    refs = re.findall(r'(?:href|src)="(/static/[^"]+)"', text)
    assert refs, "产物里的 index.html 没有引用任何 /static/ 资源 ⇒ 判据没接上"
    missing = [r for r in refs if not (STATIC / r[len("/static/"):]).is_file()]
    assert not missing, f"index.html 引用了不存在的资源：{missing}"
    # 带哈希的产物名：名字里要有内容哈希，否则 immutable 缓存是错的。
    # 字母表与服务端同一个正则（`server._HASHED`），不在这里另写一份 ——
    # 曾经这里写的是十六进制、而 Vite 5 的 `[hash]` 是 base64url，于是"判据绿、
    # 产品把带哈希的资源发成 no-store"（2026-10-07 用真产物抓到的真缺陷）。
    hashed = [r for r in refs if server._HASHED.search(r)]
    assert hashed, f"产物里没有一个带哈希的资源名（服务端正则也认不出）：{refs}"
    # 而且服务端必须真的会给它们 immutable：拿真实文件名问一次缓存策略
    with _server(REPO, STATIC) as base:
        for ref in hashed:
            code, _body, _ctype, cache = _get(base, ref)
            assert code == 200, (ref, code)
            assert "immutable" in cache, f"真实产物 {ref} 没拿到 immutable，而是 {cache!r}"


def test_the_hash_pattern_matches_the_real_built_asset_names() -> None:
    """正控（正则与产品对齐）：服务端认哈希的那条正则，对盘上真产物成立。

    这条是把"产品"与"判据"钉在一起的钉子：任何一边换了命名形态（Vite 的 hash 长度 /
    字母表），这里就会红，而不是像 2026-10-07 那样两边各自亮绿、真实缓存策略悄悄失效。
    """
    files = sorted(p.name for p in STATIC.rglob("*") if p.is_file()) if STATIC.is_dir() else []
    if not files:
        pytest.skip("构建产物不在盘上 —— 这条判据在产物入库后自动生效")
    assets = [n for n in files if n != "index.html"]
    assert assets, f"产物里只有外壳、没有资源文件：{files}"
    unmatched = [n for n in assets if not server._HASHED.search(n)]
    assert not unmatched, f"这些真实产物名没被哈希正则认出（immutable 会失效）：{unmatched}"


def test_the_hash_pattern_does_not_match_unhashed_names() -> None:
    """负控（反例）：不带内容哈希的名字不许被认成带哈希。

    为什么必须有这条：把字母表放宽就能把上一条变绿 —— 那样"改名即失效"的前提就没了，
    任何 `app.vendor.js` 都会被 immutable 缓存一年。四条反例逐条钉住：
    """
    must_not = ["index.html", "main.js", "app.min.js", "theme.dark.css", "index.module.css",
                "assets/app.js", "assets/index.esm.js"]
    bad = [n for n in must_not if server._HASHED.search(n)]
    assert not bad, f"这些名字不该被判成带哈希（会让它们被永久缓存）：{bad}"
    must = ["index.ss5N1tLG.js", "index.CWdXsWpc.css", "main.abcdef123456.js",
            "app.0123456789ab.css"]
    miss = [n for n in must if not server._HASHED.search(n)]
    assert not miss, f"这些名字应当被判成带哈希：{miss}"


def test_the_package_static_dir_is_what_the_static_route_serves() -> None:
    """正控（真产物那一支）：包内 `web/static/` 的文件能按 `/static/<file>` 取到。

    产物不在盘上时 skip（同上：不把"没查成"折成"查过了没问题"）。
    """
    files = sorted(p for p in STATIC.rglob("*") if p.is_file()) if STATIC.is_dir() else []
    if not files:
        pytest.skip("构建产物不在盘上（web/static/ 下没有文件）")
    with _server(REPO, STATIC) as base:
        for path in files:
            rel = path.relative_to(STATIC).as_posix()
            code, body, _ctype, _cache = _get(base, f"/static/{rel}")
            assert code == 200, (rel, code)
            # 用字节读（不要文本模式：Windows 上它会把 \n 翻成 \r\n，那是夹具的坑）
            text = path.read_bytes().decode("utf-8", errors="replace")
            if path.name == "index.html":
                # 外壳里的 CSRF 占位符会被服务端换成这一次进程的令牌
                text = text.replace("__CSRF__", "testtoken0123456789")
            assert body == text, rel


# ====================================================================== 产物新鲜度
def _tree_hashes(root: pathlib.Path) -> dict[str, str]:
    """一棵树的 `相对路径 → sha256`（判据比的是内容，不是时间戳）。"""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _tree_problems(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """两棵树的差异（空 = 逐文件一致）。`before` 是盘上那份，`after` 是新构建那份。"""
    problems: list[str] = []
    for rel in sorted(set(before) - set(after)):
        problems.append(f"盘上有而新构建没有：{rel}")
    for rel in sorted(set(after) - set(before)):
        problems.append(f"新构建有而盘上没有：{rel}")
    for rel in sorted(set(before) & set(after)):
        if before[rel] != after[rel]:
            problems.append(f"内容不一致：{rel}（盘上 {before[rel][:12]} vs 新构建 {after[rel][:12]}）")
    return problems


def test_negative_control_a_hand_edited_dist_file_is_reported(tmp_path: pathlib.Path) -> None:
    """负控（产物新鲜度）：手改产物一个字节 ⇒ 必须报出来（这条不需要 node）。

    正控那一半（与一次真实构建比对）要有 node 才跑得起来，而"手改产物"这件事
    不该等到有 node 才发现得了 —— 所以比对逻辑抽成纯函数，在这里用手造的
    两棵树把它逼红。
    """
    good = tmp_path / "good"
    same = tmp_path / "same"
    for tree in (good, same):
        (tree / "assets").mkdir(parents=True)
        (tree / "index.html").write_text("壳\n", encoding="utf-8")
        (tree / "assets" / "main.abcdef12.js").write_text("console.log(1);\n",
                                                          encoding="utf-8")
    assert _tree_problems(_tree_hashes(good), _tree_hashes(same)) == []

    # ① 手改一个字节
    (same / "assets" / "main.abcdef12.js").write_text("console.log(2);\n", encoding="utf-8")
    problems = _tree_problems(_tree_hashes(good), _tree_hashes(same))
    assert problems and "main.abcdef12.js" in problems[0], problems

    # ② 少一个文件 / ③ 多一个文件
    (same / "assets" / "main.abcdef12.js").write_text("console.log(1);\n", encoding="utf-8")
    (same / "assets" / "extra.js").write_text("x\n", encoding="utf-8")
    assert _tree_problems(_tree_hashes(good), _tree_hashes(same)), "多出来的文件没被看见"
    (same / "assets" / "extra.js").unlink()
    (good / "assets" / "gone.js").write_text("x\n", encoding="utf-8")
    assert _tree_problems(_tree_hashes(good), _tree_hashes(same)), "少掉的文件没被看见"


def _fresh_build(out_dir: pathlib.Path) -> tuple[int, str]:
    """跑一次真实构建到 `out_dir`（临时目录，不是入库的 `web/static`），返回 `(退出码, 输出尾巴)`。

    为什么构建到临时目录（2026-10-27 改）：改前的写法是 `cwd=UI` + 缺省 outDir，
    而缺省 outDir 正是入库的 `web/static` —— 于是这条"判据"每跑一次就把盘上产物换一次，
    然后拿换前/换后的哈希去比。实测后果（跑一次之后的 `git status`）：
    `D assets/index.<旧哈希>.js` / `M index.html` / `?? assets/index.<新哈希>.js`。
    判据不许改写它判的东西（它一红，红的原因与被它改坏的东西还混在一起）。

    `--emptyOutDir` 必须一起给：vite 只在 outDir 位于工程根之内时才自动清空，
    指到 root 之外它只警告不清（那正是上面那次实测里新旧哈希文件并存的原因）。

    为什么直接起 `node node_modules/vite/bin/vite.js build` 而不走 `pnpm -C ui build`：
    pnpm 在 Windows 上是 `.CMD`（`subprocess` 不套 shell 起不动），而且 pnpm 11 会在跑
    脚本前先跑一次 `install`（那是另一件事）。两者真正执行的都是这一条命令。
    `--outDir` 是 CLI 参数，优先级高于 `vite.config.ts` 里那一格。

    为什么 `encoding="utf-8"` 不是装饰：内容比对走 `_tree_hashes`（文件哈希），与 stdout
    无关，所以缺了它比对照样成立 —— 坏掉的是这一格的诊断。node / vite 按 UTF-8 往
    stdout / stderr 写，而 `text=True` 不给编码时 Python 用本机 locale（中文 Windows =
    GBK）去解它：读线程抛 UnicodeDecodeError、`proc.stdout` / `proc.stderr` 变成空串，
    于是构建真失败时 `tail` 是空串，skip 理由那句「构建这一步没查成（exit 1）⇒ …：」
    后面什么都接不上 —— 那正是把"没查成"写成"查过了"的形态（`P16`）。同
    `tests/test_roster_tree_renders_all_nodes.py` 与 `tests/test_webui_three_state_reading.py`
    那两处判据的口径（它们同样要起 node 读它的输出）。
    """
    node = shutil.which("node")
    vite = UI / "node_modules" / "vite" / "bin" / "vite.js"
    proc = subprocess.run([str(node), str(vite), "build",
                           "--outDir", str(out_dir), "--emptyOutDir"],
                          cwd=str(UI),
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=900)
    tail = ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()
    return proc.returncode, " / ".join(tail[-4:])


def test_the_committed_dist_is_what_a_fresh_build_produces(tmp_path: pathlib.Path) -> None:
    """正控（产物新鲜度）：盘上那份 `web/static/**` 与"重新构建一次"逐文件一致。

    三档口径（不许把"没查成"折成"查过了没问题"）：
      - 产物不在盘上 ⇒ skip，理由写明"先构建再提交（裁定 B1）"；
      - 没装 node 或依赖没装 ⇒ skip，理由写明记 `unknown`；
      - 构建这一步自己失败（例如本沙箱不允许 Node 的管道 stdio，esbuild 起不来）
        ⇒ skip，理由里带上真实的退出码与错误尾巴。

    真的跑起来时它比"内容"：手改了产物一个字节 ⇒ 与重新构建的结果对不上 ⇒ 红。
    构建落在 `tmp_path` 里（见 `_fresh_build`），盘上那份产物全程一个字节都不动。
    """
    index = STATIC / "index.html"
    if not index.is_file():
        pytest.skip("构建产物不在盘上（web/static/index.html 不存在）—— "
                    "先 `pnpm -C agentflow/ui build` 再提交（裁定 B1）")
    node = shutil.which("node")
    if node is None:
        pytest.skip("没装 node ⇒ dist 新鲜度记 unknown（不记 pass）")
    if not (UI / "node_modules" / "vite" / "bin" / "vite.js").is_file():
        pytest.skip("前端依赖没装（ui/node_modules/vite 不在）⇒ dist 新鲜度记 unknown（不记 pass）")
    fresh = tmp_path / "fresh-dist"
    try:
        code, tail = _fresh_build(fresh)
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"构建这一步没查成（{type(exc).__name__}: {exc}）"
                    "⇒ dist 新鲜度记 unknown（不记 pass）")
    if code != 0:
        pytest.skip(f"构建这一步没查成（exit {code}）⇒ dist 新鲜度记 unknown（不记 pass）：{tail}")
    problems = _tree_problems(_tree_hashes(STATIC), _tree_hashes(fresh))
    assert not problems, (
        "盘上的产物与重新构建的结果不一致（手改过、或者改了前端没重建）："
        + "；".join(problems[:6]) + "。重建之后连同产物一起提交（裁定 B1）")


#: 反真空：这一组判据必须真的有落脚点（静态根与前端源码的存在性）。
def test_the_static_route_and_the_frontend_both_have_a_landing_spot() -> None:
    """反真空（这一组的前提）：路由表里有静态那一条，前端源码在盘上。"""
    from agentflow.webui import routes
    from agentflow.webui.server import default_static_root

    assert "/static/{file...}" in routes.patterns(), routes.patterns()
    assert (UI / "index.html").is_file(), "前端骨架不在盘上 ⇒ 这一组的多数判据会 skip"
    assert pathlib.Path(default_static_root()).name == "static", default_static_root()
    assert pathlib.Path(default_static_root()).is_absolute(), default_static_root()
