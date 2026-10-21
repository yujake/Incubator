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
    # 交接账本（`draft/39` §C1）：每个工作区自己的那个（`<工作区>/manuscripts/` 下，
    # 第一次写手稿之后才有）—— 仓库根这一层永远没有它。
    # 两个名字都要登记：`_FILENAME_RE` 的扩展名分支把 `json` 排在 `jsonl` 前面，
    # 于是图里写的 `handoffs.jsonl` 被切成 `handoffs.json` 这个 token（判据的已知切词行为，
    # 改切词顺序会牵动一批历史文档，不在这里动）。
    "handoffs.jsonl", "handoffs.json",
    # 产物台账（`artifacts.py:63` 的 `LEDGER_NAME`）：落点是 `<工作区根>/ARTIFACTS.jsonl`，
    # 同样是"跑起来才有"的运行时产物 —— 仓库里没有它。
    # 与 `handoffs` 同一个切词行为（`ARTIFACTS.jsonl` 被切成 `ARTIFACTS.json`），
    # 所以两个 token 都登记。为什么不是把读图里那个名字改成占位写法：那个名字是真的
    # （`LEDGER_NAME` 逐字就是它），把它降级成 `ARTIFACTS.<ext>` 等于为了让判据好过
    # 而让文档不再指到真名 —— 那正是这张图的用途的反面。
    "ARTIFACTS.jsonl", "ARTIFACTS.json",
    # 名册旁支（`out/roster/<父编号>-index.jsonl` 与 `-retired.jsonl`）：同样只在工作区里
    # 才有，仓库里没有。读图里写的是真名（带 `<父编号>` 前缀），但切词从 `-index` 起算、
    # 又把 `.jsonl` 切成 `.json` ⇒ 得到 `-index.json` / `-retired.json` 两个 token。
    # 与 handoffs/ARTIFACTS 同一个已知切词行为，登记而不是把真名改成占位写法。
    "-index.json", "-retired.json",
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


#: §3「这些文件为什么这么大」那张表的行：`| \`x.py\` | 行数 | 边界 | 为什么大 |`。
#: `goal-7f5116c1` M6/M7 把八个角色拆成了包 ⇒ 这一格也可以是包内的文件（`agent_b/core.py`）。
_BIG_TABLE_ROW = re.compile(r"^\|\s*`([A-Za-z0-9_/]+\.py)`\s*\|\s*([0-9]+)\s*\|", re.M)


def _big_file_rows(text: str) -> list[tuple[str, int]]:
    """§3 表里的 `(文件名, 图里写的行数)`（只认第二格是数字的行）。"""
    return [(m.group(1), int(m.group(2))) for m in _BIG_TABLE_ROW.finditer(text)]


def _stale_line_counts(text: str) -> list[str]:
    """图里写的行数与盘上实际行数对不上的那些（返回人话，空列表 = 都对得上）。"""
    out: list[str] = []
    for name, claimed in _big_file_rows(text):
        path = SRC / name
        if not path.is_file():
            out.append(f"{name}: 图里有这一行，盘上没有这个文件")
            continue
        actual = len(path.read_text(encoding="utf-8").splitlines())
        if actual != claimed:
            out.append(f"{name}: 图里写 {claimed} 行，盘上 {actual} 行")
    return out


def test_the_line_counts_in_the_big_file_table_are_current() -> None:
    """§3 表里的行数是手抄的，所以必须有判据：`T-5`/`T-7` 各改大一次文件后它就漂了。

    漂了不算小事：这张表的用途正是"读之前先知道边界"（哪个文件为什么这么大），
    一个偏了 140 行的数字会让读者以为拆分没做、或者以为某个文件比实际更大。
    判据红了就改数字（一行的事），别改判据。
    """
    text = DOC.read_text(encoding="utf-8")
    rows = _big_file_rows(text)
    assert len(rows) >= 10, (
        f"§3 表只解析出 {len(rows)} 行 ⇒ 判据没接上（表格格式变了？）—— "
        "『没命中』在这里不等于『没问题』")
    stale = _stale_line_counts(text)
    assert not stale, "读图 §3 的行数过期了（改数字，别改判据）：" + "；".join(stale)


def test_the_line_count_judge_catches_a_stale_number() -> None:
    """负控：上面那条判据真的在读数字，不是"永远绿"。

    做法是把 §3 里第一行的数字 +1 再喂给同一个检查函数 —— 它必须报出来。
    没有这一条，`_big_file_rows` 哪天正则失配（比如表格换了写法），
    上面那条判据会以"一行都没解析到"的形态静默变绿（本例的 `>= 10` 也会拦住，
    但这条负控证明的是检查逻辑本身有效，而不只是"行数够多"）。
    """
    text = DOC.read_text(encoding="utf-8")
    rows = _big_file_rows(text)
    assert rows, "§3 表一行都没解析到 ⇒ 这条负控没有落脚点"
    name, claimed = rows[0]
    doctored = text.replace(f"| `{name}` | {claimed} |", f"| `{name}` | {claimed + 1} |", 1)
    assert doctored != text, f"负控没改到 `{name}` 那一行 —— 这条负控自己失效了"
    assert _stale_line_counts(doctored), "数字被改坏了，判据却一声不吭 ⇒ 它是真空的"
