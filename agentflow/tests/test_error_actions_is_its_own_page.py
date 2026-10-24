# -*- coding: utf-8 -*-
"""「错误动作」是独立的一页，不是对话页里的一个锚点（业主 2026-10-24）。

业主原话：「对话页和错误动作页完全一致是怎么回是？（都有错误动作计数，都有对话）」。

成因是一处结构选择，不是配色或文案：上一批把 `RoleErrors` 挂在 `pages/Home.tsx` 里，
导航那一格「错误动作」链到 `/#role-errors` 锚点 ⇒ 点进去读到的仍然是 `/`，
`matchRoute` 给出 `Home`，于是两格导航落在同一屏上，必然一模一样。

这一组守四件事：

| 判据 | 查什么 |
|---|---|
| a 对话页不再挂那一栏 | `pages/Home.tsx` 里没有 `RoleErrors`（import 与 JSX 都不许有） |
| b 独立路由 | `main.tsx` 的 `NAV` 与 `ROUTES` 里「错误动作」是一条自己的路由，路径里没有 `#` 锚点 |
| c 两页不相交 | 对话页渲染的是对话与缓存面板，错误动作页渲染的是 `RoleErrors`，两边组件集合没有交集 |
| d 反真空 | 把 `<RoleErrors />` 塞回对话页 ⇒ a 必红（证明 a 不是一句永远成立的空话） |

为什么扫源码而不是跑浏览器：这一组问的是"路由怎么接的、哪一页挂了哪个组件"，
这两件在源码里是结构可见的（与 `tests/test_webui_pages.py` 同一套办法）；
真浏览器那一层由 `tests/test_webui_browser.py` 的逐页核对负责，这里不重复它。

`/errors` 为什么是路径而不是 `#/errors`：`main.tsx` 的路由读的是
`window.location.pathname`（`matchRoute`），服务端的 SPA 回退按路径吐外壳。
换成 hash 路由会让 `matchRoute` 永远读到 `/`，等于把这次的缺陷换个形状再来一遍。
"""

from __future__ import annotations

import pathlib
import re

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
MAIN_TSX = UI_SRC / "main.tsx"
HOME_TSX = UI_SRC / "pages" / "Home.tsx"
ERRORS_PAGE_TSX = UI_SRC / "pages" / "RoleErrorsPage.tsx"

#: 两页各自必须有的组件（判据 c 的"不相交"按这两个集合核）。
HOME_COMPONENTS: tuple[str, ...] = ("CachePanel", "对话")
ERRORS_COMPONENTS: tuple[str, ...] = ("RoleErrors",)

#: 错误动作页自己的路由（判据 b 钉的那一条）。
ERRORS_ROUTE = "/errors"

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)


def _strip_js_comments(text: str) -> str:
    """剥掉块注释与整行注释（注释里提到 RoleErrors 不算挂载）。"""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _main_text() -> str:
    """`main.tsx` 的原文；不在盘上就 fail（它是路由的唯一真身）。"""
    assert MAIN_TSX.is_file(), f"{MAIN_TSX} 不在盘上"
    return MAIN_TSX.read_text(encoding="utf-8")


def _home_text() -> str:
    assert HOME_TSX.is_file(), f"{HOME_TSX} 不在盘上"
    return HOME_TSX.read_text(encoding="utf-8")


def _errors_page_text() -> str:
    """错误动作页的源码；不在盘上就 fail（不许 skip 变绿）。"""
    assert ERRORS_PAGE_TSX.is_file(), (
        f"{ERRORS_PAGE_TSX.relative_to(REPO)} 不在盘上 —— 那一页没有落点")
    return ERRORS_PAGE_TSX.read_text(encoding="utf-8")


def _routes(main: str) -> list[str]:
    """`main.tsx` 里 `ROUTES` 的取值（顺序即声明顺序）。"""
    body = _strip_js_comments(main)
    start = body.index("export const ROUTES")
    block = body[start: body.index("] as const", start)]
    return re.findall(r'["\'](/[^"\']*)["\']', block)


def _nav(main: str) -> list[tuple[str, str]]:
    """`main.tsx` 里 `NAV` 的 `(path, label)` 表（声明顺序）。"""
    body = _strip_js_comments(main)
    start = body.index("const NAV")
    block = body[start: body.index("];", start)]
    return re.findall(r"\{\s*path:\s*(.+?),\s*label:\s*\"([^\"]+)\"\s*\}", block)


def _page_components(text: str) -> set[str]:
    """一页源码里出现的组件标识符（判据 c 只认登记过的那几个）。"""
    body = _strip_js_comments(text)
    return {name for name in HOME_COMPONENTS + ERRORS_COMPONENTS if name in body}


def _home_mount_problems(text: str) -> list[str]:
    """对话页里还挂着 RoleErrors 的证据（空 = 干净）。

    抽成纯函数是为了 d 那条负控：同一段判据喂一份"塞回去了"的文本必须报出问题。
    """
    body = _strip_js_comments(text)
    problems: list[str] = []
    if re.search(r"from\s+[\"'][^\"']*RoleErrors[\"']", body):
        problems.append("Home.tsx 还 import 着 RoleErrors")
    if "<RoleErrors" in body:
        problems.append("Home.tsx 的 JSX 里还挂着 <RoleErrors />")
    if "ROLE_ERRORS_ID" in body or "#role-errors" in body:
        problems.append("Home.tsx 里还留着 role-errors 那个锚点")
    return problems


def _nav_route_problems(main: str) -> list[str]:
    """「错误动作」在 NAV 与 ROUTES 里是不是一条独立路由（空 = 合格）。"""
    body = _strip_js_comments(main)
    problems: list[str] = []
    routes = _routes(main)
    nav = _nav(main)
    if not routes:
        problems.append("main.tsx 里 ROUTES 一个取值都没解析到（判据没接上）")
        return problems
    if not nav:
        problems.append("main.tsx 里 NAV 一条都没解析到（判据没接上）")
        return problems

    hits = [(path, label) for path, label in nav if label == "错误动作"]
    if len(hits) != 1:
        problems.append(f"NAV 里「错误动作」应当恰好一格，实得 {hits}")
        return problems
    raw = hits[0][0].strip()
    path = raw.strip("\"'")
    if "#" in raw:
        problems.append(f"「错误动作」仍是带锚点的链接（{raw}），点进去还是对话页那一屏")
    if "role-errors" in raw:
        problems.append(f"「错误动作」仍指向 role-errors 锚点（{raw}）")
    if path not in routes:
        problems.append(f"NAV 里「错误动作」的路径 {path} 不在 ROUTES 里")
    if f'case "{ERRORS_ROUTE}"' not in body and f"case '{ERRORS_ROUTE}'" not in body:
        problems.append(f"renderPage 没有为 {ERRORS_ROUTE} 出一条 case")
    return problems


# ====================================================================== a 对话页
def test_a_the_chat_page_no_longer_renders_the_role_errors_band() -> None:
    """判据 a：对话页里不再有 RoleErrors（import 与 JSX 都不许有）。"""
    problems = _home_mount_problems(_home_text())
    assert problems == [], problems
    assert "CachePanel" in _home_text(), (
        "对话页连缓存面板都不挂了？那一页就不成其为对话页了（判据可能读错了文件）")


# ====================================================================== b 独立路由
def test_b_the_nav_entry_is_its_own_route_not_an_anchor() -> None:
    """判据 b：NAV 与 ROUTES 里「错误动作」是一条自己的路由，不是 `#role-errors`。"""
    problems = _nav_route_problems(_main_text())
    assert problems == [], problems

    routes = _routes(_main_text())
    assert ERRORS_ROUTE in routes, f"ROUTES 里没有 {ERRORS_ROUTE}：{routes}"
    assert len(routes) == len(set(routes)), f"ROUTES 里有重复：{routes}"
    # NAV 的每一条都必须是一条真实路由（锚点应当一条都不剩）
    for path, label in _nav(_main_text()):
        assert "#" not in path, f"NAV 里「{label}」还是锚点：{path}"


# ====================================================================== c 不相交
def test_c_the_two_pages_render_disjoint_component_sets() -> None:
    """判据 c：两页渲染的组件集合不相交 —— 对话页不含 RoleErrors，错误动作页不含对话。"""
    home = _page_components(_home_text())
    page = _page_components(_errors_page_text())
    assert home, "对话页一个登记组件都没扫到（判据没接上）"
    assert page, "错误动作页一个登记组件都没扫到（判据没接上）"
    assert home & page == set(), f"两页共用了组件：{sorted(home & page)}"
    for name in HOME_COMPONENTS:
        assert name in home, f"对话页丢了 {name}"
        assert name not in page, f"错误动作页里出现了对话页的 {name}"
    for name in ERRORS_COMPONENTS:
        assert name in page, f"错误动作页没有渲染 {name}"
        assert name not in home, f"对话页里还渲染着 {name}"


# ====================================================================== d 反真空
def test_d_negative_control_catches_the_band_put_back_into_home() -> None:
    """判据 d：把 `<RoleErrors />` 塞回对话页 ⇒ a 那条必红。"""
    text = _home_text()
    assert _home_mount_problems(text) == [], _home_mount_problems(text)
    doctored = text.replace(
        "import { Table }",
        "import { RoleErrors } from \"../components/RoleErrors\";\nimport { Table }",
        1,
    )
    if doctored == text:
        doctored = text + "\nconst _back = <RoleErrors />;\n"
    assert doctored != text, "负控没改到东西（文件里找不到可插入的位置）"
    problems = _home_mount_problems(doctored)
    assert problems, "把 RoleErrors 塞回对话页却一声不吭"
    assert any("RoleErrors" in one for one in problems), problems
    # 只塞 import、不塞 JSX 也必须报（否则"移走"可以靠删一行注释蒙过去）
    import_only = text.replace(
        "import { Table }",
        "import { RoleErrors } from \"../components/RoleErrors\";\nimport { Table }",
        1,
    )
    assert import_only != text
    assert _home_mount_problems(import_only) != [], "只把 import 加回去也应当报"
