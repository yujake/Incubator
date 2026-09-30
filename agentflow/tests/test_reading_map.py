# -*- coding: utf-8 -*-
"""`docs/READING-MAP.md` 的判据（`draft/36` 的 T-1）。

为什么文档也要判据：这张图的用途是"新人照它找到文件"，而过期的图比没有图更坏 ——
它会把读者指到一个已经不存在的文件、或者让读者以为某个模块"不重要所以没提"。
所以钉两件事：

1. 图里出现的每个文件名都真实存在（把读者指到盘上真有的地方）；
2. `src/agentflow` 的每个模块至少被提到一次（不许有"孤儿文件"）——
   新增一个模块却忘了在图上给它位置，这条判据会红。

## 两处刻意的取舍

- 只认"看起来像文件名"的 token（带扩展名且不含空格）。图里还有 `agent_<x>.py`
  这种占位写法（它指的是"八个角色各自的 `agent_x.py`"这一类），
  占位符一律跳过：把占位符当文件名去断言存在，会逼着作者把话写死。
  判据的强度靠第 2 条（模块必须逐个被提到）补回来。
- 模块名比对用"裸名"（`agent_d.py`），因为图里就是这么写的；
  带路径的写法（`tools/base.py`）也认，两者都算"提到过"。
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "READING-MAP.md"
SRC = REPO / "src" / "agentflow"

#: 看起来像文件名：带这些扩展名、且不含空格/尖括号（后者是占位写法）。
_FILENAME_RE = re.compile(r"[A-Za-z0-9_./-]+\.(?:py|md|json|jsonl|txt|toml|cfg|yaml|yml)")
#: 占位写法：`agent_<x>.py` / `<模块>.py` 这类，跳过。
_PLACEHOLDER = re.compile(r"[<>{}]")

#: 运行时产物：跑一次 `run`/`project run` 才会出现在 `out/run-<N>/` 下，
#: 仓库里本来就没有它们。读图里会提到它们（那六件产物是"查一次运行做了什么"的入口），
#: 所以显式登记、写明理由 —— 而不是把判据放宽成"找不到就算了"。
#: 反向断言见 `test_the_runtime_product_exemptions_are_not_stale`：
#: 一旦仓库里真的出现了同名文件，这条登记就过期了，判据会红。
_RUNTIME_PRODUCTS = frozenset({
    "report.md", "run-manifest.json", "claims.json", "evidence.json",
    "cost.json", "model-transcript.jsonl",
})


def _mentioned_filenames(text: str) -> set[str]:
    """图里提到过的文件名（去重，跳过占位写法与明显的外链）。"""
    out: set[str] = set()
    for raw in _FILENAME_RE.findall(text):
        if _PLACEHOLDER.search(raw):
            continue
        if raw.startswith(("http", "www")):
            continue
        out.add(raw)
    return out


def _resolves(name: str) -> bool:
    """这个名字能不能在盘上找到（相对 `agentflow/`、`agentflow/docs/` 或仓库根）。"""
    cands = [REPO / name, REPO / "docs" / name, REPO.parent / name,
             SRC / name, REPO / "src" / "agentflow" / name]
    return any(p.is_file() for p in cands)


def test_the_reading_map_exists_and_is_not_empty() -> None:
    """反真空：图必须在，而且真的有内容（不是一句"待补"）。"""
    assert DOC.is_file(), f"读图不存在：{DOC}"
    text = DOC.read_text(encoding="utf-8")
    assert len(text.splitlines()) > 80, "读图太短 ⇒ 它还没写完（本判据防的是'占位文档'）"
    assert "## §2" in text and "我想…" in text, "读图缺 §2 的『想改什么 ⇒ 读哪几个文件』表"


def test_every_filename_in_the_map_exists_on_disk() -> None:
    """图里出现的每个文件名都真实存在（把读者指到盘上真有的地方）。

    运行时产物（六件产物）除外 —— 它们由 `_RUNTIME_PRODUCTS` 显式登记，见那里的注释。
    """
    text = DOC.read_text(encoding="utf-8")
    missing = sorted(n for n in _mentioned_filenames(text)
                     if not _resolves(n) and n not in _RUNTIME_PRODUCTS)
    assert not missing, (
        "读图里这些文件名在盘上找不到（过期的图比没有图更坏）："
        + "、".join(missing)
        + "。若它是有意举的假名字例子，请写成占位写法（如 agent_<x>.py）让判据跳过它"
    )


def test_the_runtime_product_exemptions_are_not_stale() -> None:
    """反向断言：登记为"运行时产物"的名字，现在确实不在仓库里。

    没有这一条，上面那条豁免会慢慢变成"随便往表里塞名字"的垃圾桶：
    塞进去的名字哪怕后来真成了仓库里的文件，也没有任何东西会响。
    """
    stale = sorted(n for n in _RUNTIME_PRODUCTS if _resolves(n))
    assert not stale, (
        "这些名字被登记为『运行时产物』，但仓库里真的有同名文件 ⇒ 登记过期了，"
        "请把它们从 `_RUNTIME_PRODUCTS` 里删掉（它们现在是真文件，该被第 2 条判据管）："
        + "、".join(stale))


def test_every_source_module_is_placed_somewhere_in_the_map() -> None:
    """`src/agentflow` 的每个模块都要在这张图里出现（不许有孤儿文件）。

    这是这条判据的主判据：光有第 2 条只能证明"图里写的都存在"，
    证明不了"盘上有的都在图里" —— 而后者才是"新人照图找不到某个文件"的根因。
    """
    text = DOC.read_text(encoding="utf-8")
    mentioned = _mentioned_filenames(text)
    bare = {name.split("/")[-1] for name in mentioned}
    modules = sorted(p.name for p in SRC.glob("*.py") if p.name != "__pycache__")
    orphans = [m for m in modules if m not in bare]
    assert not orphans, (
        "这些模块在读图里没有位置（新增模块请在这张图上给它一行）：" + "、".join(orphans))

    tool_modules = sorted(p.name for p in (SRC / "tools").glob("*.py"))
    tool_orphans = [m for m in tool_modules if m not in bare]
    assert not tool_orphans, (
        "tools/ 下这些模块在读图里没有位置：" + "、".join(tool_orphans))
