"""判据（鲁棒 d / h）：大台账分页搜索；金额与计数只在一处格式化。

## 为什么要这两条

- d：真机 `tasks` 已 223 行、`secretary` 380 行、`ledger` 173 行。整表一次性进 DOM
  会卡首屏，读的人在几百行里也找不到自己那一行。`PagedTable` 是唯一的分页/搜索
  落点：按页切片（默认 50 行）、在"这一张表真的会显示的列"里做子串搜索。
- h：金额与计数的写法此前散在四处（`Money.formatUsd` / `Acceptance.usd` /
  `Acceptance.num` / `Evidence` 的 `usd.toFixed(6)`）。同一个读数在「预算」页与
  「论文包」页各写各的，漂了没有任何地方会报错。现在只有 `components/Money.tsx`
  一处：`formatUsd` / `formatCount` / `formatText`。

## 判据的两半

1. 分页：Artifacts / Evidence 的每一张表都经 `PagedTable`（源码里不再有 `<Table`
   直用）；`PagedTable` 真的 `slice` 过、并带搜索框与页码；小表（≤ 一页）仍走原
   `Table`（不为了 18 行加一个搜索框）。
2. 格式化：除 `Money.tsx` 外，`ui/src` 里没有第二处 `toFixed(` / 手写 `$` 金额；
   `formatCount` / `formatText` 的定义只在 `Money.tsx`。

反真空（三条负控）：

- 在某个页面里塞一处 `toFixed(` ⇒ 格式化判据必须红；
- 把 `PagedTable` 的 `slice` 删掉（退回整表渲染）⇒ 分页判据必须红；
- 把某页的 `<PagedTable` 换回 `<Table` ⇒ 分页判据必须红。
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
UI = REPO / "ui" / "src"
PAGED = UI / "components" / "PagedTable.tsx"
MONEY = UI / "components" / "Money.tsx"
PAGES = (UI / "pages" / "Artifacts.tsx", UI / "pages" / "Evidence.tsx")


def _page_problems(name: str, text: str) -> list[str]:
    """一张页面源码用没用 PagedTable（纯函数，可负控）。"""
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    problems: list[str] = []
    if "<PagedTable" not in code:
        problems.append(f"{name} 没有用 PagedTable")
    if re.search(r"<Table\b", code):
        problems.append(f"{name} 还有直用的 <Table（大表会整表渲染）")
    return problems


def _pager_problems(paged: str, pages: tuple[pathlib.Path, ...]) -> list[str]:
    code = re.sub(r"/\*.*?\*/", "", paged, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    problems: list[str] = []
    for name in ("DEFAULT_PAGE_SIZE", "filtered.slice(", "useState", "placeholder"):
        if name not in code:
            problems.append(f"PagedTable 没有 `{name}`（分页/搜索没落点）")
    if "props.rows.length > size" not in code:
        problems.append("PagedTable 没有『小表不动』那一支（十几行也加搜索框只是噪声）")
    if "<Table rows={props.rows}" not in code:
        problems.append("PagedTable 的小表那一支没有走原 Table")
    for path in pages:
        problems.extend(_page_problems(path.name, path.read_text(encoding="utf-8")))
    return problems


def _money_problems(files: dict[str, str]) -> list[str]:
    """`{路径: 源码}` ⇒ 问题清单（金额/计数只许在 Money.tsx 一处格式化）。"""
    problems: list[str] = []
    money = files["components/Money.tsx"]
    for name in ("formatUsd", "formatCount", "formatText"):
        if f"export function {name}" not in money:
            problems.append(f"Money.tsx 没有导出 `{name}`")
    for rel, text in files.items():
        if rel == "components/Money.tsx":
            continue
        code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        code = re.sub(r"//[^\n]*", "", code)
        if "toFixed(" in code:
            problems.append(f"{rel} 里还有 toFixed( —— 金额/数字的写法应走 Money.tsx")
        if re.search(r"function\s+(formatUsd|formatCount|formatText)\b", code):
            problems.append(f"{rel} 里又定义了一份 `format*`")
    return problems


def _ui_sources() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(UI.rglob("*")):
        if path.suffix not in (".ts", ".tsx") or path.name == "types.ts":
            continue
        out[path.relative_to(UI).as_posix()] = path.read_text(encoding="utf-8")
    return out


def test_the_big_tables_go_through_one_pager() -> None:
    """正控：Artifacts / Evidence 的表都经 PagedTable；PagedTable 真的切片。"""
    paged = PAGED.read_text(encoding="utf-8")
    assert _pager_problems(paged, PAGES) == [], _pager_problems(paged, PAGES)
    # 负控一：删掉切片（退回整表渲染）。
    doctored = re.sub(r"\bfiltered\.slice\([^)]*\)", "filtered", paged)
    assert doctored != paged, "负控没改到源码"
    assert any("slice(" in p for p in _pager_problems(doctored, PAGES)), (
        _pager_problems(doctored, PAGES))
    # 负控二：某页换回 <Table。
    text = PAGES[0].read_text(encoding="utf-8")
    swapped = text.replace("<PagedTable", "<Table", 1)
    assert swapped != text, "负控没改到源码"
    assert any("直用的 <Table" in p or "没有用 PagedTable" in p
               for p in _page_problems(PAGES[0].name, swapped)), (
        _page_problems(PAGES[0].name, swapped))


def test_money_and_counts_are_formatted_in_one_place() -> None:
    """正控：只有 Money.tsx 有 format* 与 toFixed；负控能在页面里抓到一处。"""
    sources = _ui_sources()
    assert _money_problems(sources) == [], _money_problems(sources)
    doctored = dict(sources)
    doctored["pages/Budget.tsx"] = sources["pages/Budget.tsx"] + "\nconst x = (1).toFixed(6);\n"
    assert _money_problems(doctored), "页面里塞 toFixed( 之后判据仍然绿 ⇒ 没有牙"
