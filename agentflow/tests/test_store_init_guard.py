"""`R-32` 的判据：`Store.init()` 不许在"不是工作区、又不是空目录"的地方凭空建库。

## 改前是什么样（`draft/28` §136.3 事故 B）

一个复核脚本对 `projects/` 下每个目录跑了 `Store(...).init()`，于是 `projects/manual-notes/`（人的文件夹，里面只有 `我的资料.txt`）被补出整套`data/`（19
个条目）+ `library/`。那个脚本的判态函数对它的判定自始至终是`not_a_project` —— 是它先动手、后判态。处置时删的只是建出来的 `data/`、`library/`；`我的资料.txt` 的 sha256
前后逐字节相同。产品级缺口：同一件事两个入口两种安全性 —— 工具层 `projects.ensure_project`有"拒绝外来目录"的守卫，直连 `Store` 没有。

## 这一组判据守什么

```text允许 init ⇔  root 不存在∨ data/ 已存在∨ .agentflow-workspace 在∨ root 里没有不属于本框架的条目（`store._WORKSPACE_ROOT_ENTRIES`）```

正/负控 + 一格"拒绝之后一个字节都没写"（这是这一组里最要紧的一格：只断言"抛了异常"是不够的 —— 一个先建目录再抛的实现照样能过那些断言）。

`draft/28` §176 补的一格（误拦方向）：判据的第一版把"除 `data/` 与 `library/`之外还有条目"一律当外来目录，于是工作区根里有
`projects/` 这种正常部署被拦下了（`tests/test_conductor_tools.py` 里那个布局在全量套件里当场变
红）。`test_a_workspace_root_holding_projects_is_allowed` 与`test_a_workspace_root_holding_a_stray_file_is_still_refused`
把这条边界两侧各钉一次。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow.store import Store, StoreError


def _foreign_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """造一个"人的文件夹"：有别人的文件，没有 `data/`。"""
    d = tmp_path / "manual-notes"
    d.mkdir()
    (d / "我的资料.txt").write_text("人类的东西，不许动\n", encoding="utf-8")
    return d


def test_refuses_to_init_a_foreign_directory(tmp_path: pathlib.Path):
    """负控（事故 B 的原样注入）：别人的文件夹 ⇒ 拒绝，且一个字节都不写。"""
    d = _foreign_dir(tmp_path)
    before = sorted((p.relative_to(d).as_posix(), p.read_bytes()) for p in d.rglob("*") if p.is_file())
    with pytest.raises(StoreError, match="拒绝 init"):
        Store(d).init()
    after = sorted((p.relative_to(d).as_posix(), p.read_bytes()) for p in d.rglob("*") if p.is_file())
    assert before == after, "拒绝之后文件集合/内容必须逐字节不变"
    assert sorted(p.name for p in d.iterdir()) == ["我的资料.txt"], "不许留下 data/ 或 library/"
    assert not (d / "data").exists() and not (d / "library").exists()


def test_force_overrides_the_guard_and_says_what_it_does(tmp_path: pathlib.Path):
    """`force=True` 是"确认就要在这里建"的出口 ⇒ 它必须真的建出来。"""
    d = _foreign_dir(tmp_path)
    Store(d).init(force=True)
    assert Store(d).exists()
    assert (d / "我的资料.txt").is_file(), "force 也不许删别人的文件"


def test_a_fresh_directory_is_allowed(tmp_path: pathlib.Path):
    """正控①：新目录（不存在）⇒ 允许。"""
    d = tmp_path / "brand-new"
    Store(d).init()
    assert d.is_dir() and Store(d).exists()


def test_an_empty_directory_is_allowed(tmp_path: pathlib.Path):
    """正控②：空目录 ⇒ 允许（它就是"新工作区"的形态）。"""
    d = tmp_path / "empty"
    d.mkdir()
    Store(d).init()
    assert Store(d).exists()


def test_an_existing_workspace_missing_a_table_is_still_allowed(tmp_path: pathlib.Path):
    """正控③：有 `data/` 的旧工作区（缺一张表）⇒ 允许补齐。

    这一格是判据的边界，不许被"看起来更严"的改法吃掉：`draft/30` §T1 加
    `conjectures` 表时，就是靠 `init()` 给 8 个旧项目补的那一张 —— 判据要拦的是
    "在别人的目录里凭空建库"，不是"表不齐"。
    """
    d = tmp_path / "ws"
    Store(d).init()
    missing = d / "data" / "conjectures.json"
    missing.unlink()
    assert not Store(d).exists()
    Store(d).init()
    assert Store(d).exists() and missing.is_file()


def test_a_directory_holding_only_our_two_names_is_allowed(tmp_path: pathlib.Path):
    """正控④：只有空 `library/`（没有 `data/`）⇒ 允许（它是我们的两样之一，不是外来内容）。"""
    d = tmp_path / "libs-only"
    (d / "library").mkdir(parents=True)
    Store(d).init()
    assert Store(d).exists()


def test_a_workspace_root_holding_projects_is_allowed(tmp_path: pathlib.Path):
    """正控⑤（误拦方向）：工作区根里已经有 `projects/<名字>/` ⇒ 必须允许 init。

    这是本判据第一版真实拦错的那一格（§176）：项目文件夹就住在工作区根下面，
    所以"根里有 `projects/`"是正常部署，不是外来内容。
    `tests/test_conductor_tools.py::test_ensure_project_refuses_foreign_directory`
    造的就是这个布局，第一版判据让它红在"根 init 被拒"上。
    """
    d = tmp_path / "ws-root"
    (d / "projects" / "manual-notes").mkdir(parents=True)
    (d / "projects" / "manual-notes" / "notes.txt").write_text("别人的东西", encoding="utf-8")
    Store(d).init()
    assert Store(d).exists()
    assert (d / "projects" / "manual-notes" / "notes.txt").is_file(), "别人的文件一个字都不许动"


def test_a_workspace_root_holding_a_stray_file_is_still_refused(tmp_path: pathlib.Path):
    """负控（同一条边界的另一侧）：根里除了我们的东西还有别人的文件 ⇒ 照旧拒绝。

    没有这一格，"把白名单放得很宽"（例如允许一切目录）也能让上一格通过 ——
    两格必须成对存在，否则这条判据的判别力不可见。
    """
    d = tmp_path / "ws-root-with-notes"
    (d / "projects").mkdir(parents=True)
    (d / "我的资料.txt").write_text("人类的东西，不许动\n", encoding="utf-8")
    with pytest.raises(StoreError, match="拒绝 init"):
        Store(d).init()
    assert not (d / "data").exists()


def test_the_guard_predicate_itself_answers_the_four_shapes(tmp_path: pathlib.Path):
    """判据本体的诸态（直接问那个谓词，不经过建文件）：这是"判据可判"的证据。

    没有这一格的话，上面几格全部可以靠"`init()` 里随手写一句 if"通过，
    而那句 if 的正确性没有任何地方看得见。
    """
    fresh = Store(tmp_path / "not-created")
    assert fresh._foreign_dir_guard_should_refuse() is False
    empty = tmp_path / "empty"
    empty.mkdir()
    assert Store(empty)._foreign_dir_guard_should_refuse() is False
    foreign = Store(_foreign_dir(tmp_path))
    assert foreign._foreign_dir_guard_should_refuse() is True
    ws = tmp_path / "ws2"
    Store(ws).init()
    assert Store(ws)._foreign_dir_guard_should_refuse() is False
    marked = tmp_path / "marked"
    marked.mkdir()
    (marked / ".agentflow-workspace").write_text("{}", encoding="utf-8")
    assert Store(marked)._foreign_dir_guard_should_refuse() is False, "工作区标记 = 我们的目录"
    with_projects = tmp_path / "with-projects"
    (with_projects / "projects").mkdir(parents=True)
    assert Store(with_projects)._foreign_dir_guard_should_refuse() is False
    with_stranger = tmp_path / "with-stranger"
    with_stranger.mkdir()
    (with_stranger / "别人的东西.txt").write_text("x", encoding="utf-8")
    assert Store(with_stranger)._foreign_dir_guard_should_refuse() is True
