# -*- coding: utf-8 -*-
"""判据：打包配置与盘上的非 .py 资产对得上（2026-10-27，业主批 item 3）。

## 为什么要这条判据

`src/agentflow/web/static/` 是入库的前端产物（裁定 B1），运行期由
`webui/server.py::default_static_root()` 定位并服务 `GET /static/<file>`。而
`[tool.setuptools.packages.find]` 只收包：没有 `package-data` 时，`.js` / `.css` /
`.html` 一个都不进 wheel —— 源码树里一切正常，装好之后 `agentflow serve` 是白页。
这类缺陷在单测里看不见（单测跑在源码树里），所以必须有一条判据专门量"打包面"。

## 口径（为什么不去跑 `python -m build`）

构建整包太重（还要额外依赖），所以这里按 setuptools 自己的口径复算：`build_py`
的 `find_data_files` 就是"对每个 pattern 跑一次 `glob.glob`，相对包目录"。判据用
同一个 `glob` 函数、同一组 patterns 复算，再逐条断言盘上每个静态文件都被覆盖到。
配套的另一半是"配置里不认识的东西不许凭空写"（pattern 匹配不到任何文件 ⇒ 说明
盘上布局变了，这条也要红）。
"""

from __future__ import annotations

import glob
import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PKG = ROOT / "src" / "agentflow"
STATIC = PKG / "web" / "static"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _patterns() -> list[str]:
    data = _pyproject().get("tool", {}).get("setuptools", {}).get("package-data", {})
    pats = data.get("agentflow")
    assert pats, (
        "pyproject.toml 里没有 `[tool.setuptools.package-data]` 的 `agentflow` 一项 ⇒ "
        "`web/static/` 不会进 wheel（装好之后网页白页，而单测全绿）")
    assert isinstance(pats, list) and all(isinstance(p, str) for p in pats), pats
    return list(pats)


def _matched() -> set[str]:
    """按 `build_py.find_data_files` 的口径复算：每个 pattern 一次 `glob`，相对包目录。"""
    out: set[str] = set()
    for pat in _patterns():
        for hit in glob.glob(str(PKG / pat)):
            p = pathlib.Path(hit)
            if p.is_file():
                out.add(p.relative_to(PKG).as_posix())
    return out


def test_the_static_tree_is_there_to_package_at_all() -> None:
    """反真空：被判据保护的东西必须真的在盘上（否则下一条会"零个文件全通过"）。"""
    files = sorted(p for p in STATIC.rglob("*") if p.is_file())
    assert files, f"{STATIC} 下一个文件都没有 ⇒ 这条判据没有对象（不是通过）"
    rel = {p.relative_to(PKG).as_posix() for p in files}
    assert "web/static/index.html" in rel, sorted(rel)


def test_package_data_covers_every_static_file_on_disk() -> None:
    """主判据：盘上每一个静态资产都能被 `package-data` 匹配到。"""
    on_disk = {p.relative_to(PKG).as_posix() for p in STATIC.rglob("*") if p.is_file()}
    matched = _matched()
    missing = sorted(on_disk - matched)
    assert not missing, (
        f"这些文件在盘上、却不会被装进包里：{missing}。"
        "打包口径是 `build_py.find_data_files`（`glob` 逐 pattern），它不跨目录 —— "
        "新增一层静态资源就要在 `[tool.setuptools.package-data]` 里加一条 pattern")


def test_no_pattern_matches_nothing() -> None:
    """反真空的另一半：pattern 一个文件都匹配不到 ⇒ 盘上布局变了（配置该跟着改）。"""
    for pat in _patterns():
        hits = [h for h in glob.glob(str(PKG / pat)) if pathlib.Path(h).is_file()]
        assert hits, f"`package-data` 的 `{pat}` 在盘上一个文件都没匹配到 ⇒ 配置已过期"


def test_readme_is_not_empty_in_metadata() -> None:
    """item 2：`readme` 指向的文件必须真的在（否则 wheel 的 long_description 静默为空）。"""
    cfg = _pyproject().get("project", {})
    readme = cfg.get("readme")
    assert isinstance(readme, str), (
        f"`[project].readme` 是 {readme!r} —— 本条判据只覆盖『路径』这一种形态，"
        "换了形态就要跟着改判据")
    target = (ROOT / readme).resolve()
    assert target.is_file(), (
        f"`[project].readme` 指向 {readme!r}，而 {target} 不存在 ⇒ "
        "setuptools 只发一条警告、long_description 为空")
    assert target.read_text(encoding="utf-8").strip(), f"{target} 是空文件"
