# -*- coding: utf-8 -*-
"""开发入口：一次打印五处登记的当前缺口与账骨架（只打印，不写盘）。

```text
python scripts/render_registration_skeletons.py
```

五处登记（顶层模块注册表 / 拒绝码表 / `returns` 基线 / 文档索引 / 读图）在失败时各自会
带着账骨架来（`docs/DEVELOPMENT-SPEC.md` 第 17.1 节的检测面）。这个入口是同一份渲染的
「跑之前先看一眼」：不用先把判据跑红就能看到当前差在哪。

三条纪律（与判据本体一致）：

1. 只打印。不写目标文件、不改基线 —— 第 17.3 / 17.4 节：自动写盘等于把被判者升成
   判据，自动重冻等于让「改参数名 / 删返回键」从一条红变成一次静默放行。
2. 用的是那五个判据文件自己的函数（`agentflow_module_inventory_problems` /
   `refusal_registration_scan` / `contract_diff_edits` / `unregistered_docs` /
   `headline_problems`），不在这里另写一份「差」的口径。
3. 退出码三档（`R008`）：`0` = 无缺口，`1` = 有缺口（已打印骨架），
   `2` = 没查成（读不到判据文件、解析失败等）。`2` 绝不能被读成 `0`。
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 判据文件与账骨架都在仓库里，不是装好的包：按仓库根 / `src` / `tests` 的顺序注入，
#: 让本脚本能在不 `pip install` 的机器上跑（与 `tests/conftest.py` 同一条口径）。
for _candidate in (ROOT / "tests", ROOT / "src", ROOT):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

import _skeleton as SK  # noqa: E402 - 路径注入之后才能 import（见上）
import conftest as _conftest  # noqa: E402,F401 - 见下：判据跑在它钉住的环境里
from agentflow.console import pin_utf8  # noqa: E402 - 同上：`src` 注入之后才 import 得到

# 为什么连 `tests/conftest.py` 也一起导入：那五个判据不是在裸环境里跑 —— conftest 在
# 导入期把本机事实类的环境变量清掉、把 Lean 开关钉成开着（理由见那份文件）。不沿用
# 这一钉，本入口会在「Lean 关着」的世界里算声明契约，报出三条盘上根本没有的缺口
# （`formal.*` 整族不见了）—— 那种假缺口比不报更坏：它会让人去补一条不该存在的账。
# 直接 import 复用同一处口径，而不是在这里抄第二份环境清单。

#: 五处的标题（打印时一处分一段；顺序与第 17.1 节的表一致）。
TITLES: tuple[str, ...] = (
    "① 顶层模块注册表（tests/test_release_all.py::_AGENTFLOW_TOP_LEVEL_MODULES）",
    "② 拒绝码表（tests/test_refusals.py::_FAILURES_NOT_REFUSALS / _REPEAT_COUNTS）",
    "③ returns 基线（tests/fixtures/tool_declaration_baseline.json::contract_amendments）",
    "④ 文档索引（docs/INDEX.md）",
    "⑤ 读图（docs/READING-MAP.md 与 tests/test_reading_map*.py）",
)


def _top_level_gaps() -> list[str]:
    """① 盘上顶层模块集合 vs 登记清单。"""
    import test_release_all as TRA

    on_disk = TRA._agentflow_top_level_modules_on_disk()
    problems = TRA.agentflow_module_inventory_problems(on_disk)
    if not problems:
        return []
    return [SK.top_level_modules_message(problems, on_disk, TRA._AGENTFLOW_TOP_LEVEL_MODULES)]


def _refusal_gaps() -> list[str]:
    """② 手写 `ok=False` 的逐站点双向对账。"""
    import test_refusals as TRF

    _scanned, _live, _want, missing, stale = TRF.refusal_registration_scan()
    out: list[str] = []
    if missing:
        out.append(SK.refusal_missing_message(missing))
    if stale:
        out.append(SK.refusal_stale_message(stale))
    return out


def _contract_gaps() -> list[str]:
    """③ 现盘声明 vs 压缩前基线（差异未逐项记账的那些）。"""
    import test_tool_descriptions_are_compressed as TTC

    frozen = TTC.baseline()
    current = TTC.declarations()
    amendments = frozen.get("contract_amendments") or ()
    diffs = TTC.contract_diffs(frozen["declarations"], current, amendments)
    if not diffs:
        return []
    return [SK.contract_amendments_message(
        diffs, TTC.contract_diff_edits(frozen["declarations"], current, amendments),
        date=datetime.date.today().isoformat())]


def _docs_gaps() -> list[str]:
    """④ 盘上文档 vs `docs/INDEX.md`（入册 / 第 6 节不入册）。"""
    import test_docs_index_covers_every_doc as TDI

    if not TDI.INDEX.is_file():
        return ["没查成：`docs/INDEX.md` 不在盘上"]
    names = TDI._disk_docs()
    missing = TDI.unregistered_docs(names, TDI._index_text())
    if not missing:
        return []
    return [SK.docs_index_message(missing)]


def _reading_map_gaps() -> list[str]:
    """⑤ 读图开头三格 / `agent_loop.py` 行数 / 第 3 节逐文件行数。"""
    import test_reading_map as TRM
    import test_reading_map_counts as TRC

    if not TRC.READING_MAP.is_file():
        return ["没查成：`docs/READING-MAP.md` 不在盘上"]
    files, total, big, loop_lines = TRC._live()
    head = TRC._head()
    out: list[str] = []
    problems = TRC.headline_problems(head, files, total, big)
    if problems:
        out.append(SK.reading_map_counts_message(problems, files, total, big, loop_lines))
    found = TRC._LARGEST.search(head)
    got_loop = int(found.group("lines").replace(",", "")) if found else None
    if got_loop != loop_lines:
        out.append(
            f"`agent_loop.py` 的行数：文档 {got_loop if got_loop is not None else '读不出'}"
            f" vs 现算 {loop_lines:,}\n\n可粘贴的账骨架（整句替换回去）：\n"
            + SK.reading_map_headline(files, total, big, loop_lines))
    text = TRM.DOC.read_text(encoding="utf-8")
    stale = TRM._stale_line_counts(text)
    if stale:
        out.append(SK.reading_map_rows_message(stale, TRM.stale_big_rows(text)))
    return out


#: 每一处缺口的来源（标题序号 -> 收集函数）。顺序即打印顺序。
_GAP_SOURCES = (
    (_top_level_gaps, 0),
    (_refusal_gaps, 1),
    (_contract_gaps, 2),
    (_docs_gaps, 3),
    (_reading_map_gaps, 4),
)


def collect_gaps() -> list[tuple[str, str]]:
    """五处的当前缺口 ⇒ `[(标题, 骨架文本)]`（空列表 = 五处都对得上）。"""
    gaps: list[tuple[str, str]] = []
    for source, index in _GAP_SOURCES:
        for body in source():
            gaps.append((TITLES[index], body))
    return gaps


def render(gaps: list[tuple[str, str]]) -> str:
    """把缺口清单渲染成要打印的文本（无缺口时只有一句「无缺口」）。"""
    if not gaps:
        return "无缺口：五处登记都与盘上一致（本入口只打印，不写盘）。"
    lines = [f"当前缺口 {len(gaps)} 条。本入口只打印，不写盘；"
             "复核后把占位那句话换成真的理由（第 17.2 节那三问只有人能答）："]
    for title, body in gaps:
        lines.extend(["", f"== {title} ==", body])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """打印五处缺口，返回三档退出码：0 无缺口 / 1 有缺口 / 2 没查成。"""
    # 默认 GBK 控制台下，下面每一处骨架都可能编不出 `⇒`(U+21D2) ⇒ `print()` 抛
    # `UnicodeEncodeError` ⇒ 进程以 1 结束，而 1 在这里恰好是「查过了、有缺口」——
    # 「打印不出来」被读成「代码有问题」，且 stdout 一个字都没留下。钉住编码，
    # 三档退出码的含义不变（口径与实现只有 `agentflow/console.py` 那一份）。
    pin_utf8()
    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg in {"-h", "--help"} for arg in args):
        print(__doc__)
        return 0
    if args:
        print(f"未知参数：{args}（本入口不接受参数）", file=sys.stderr)
        return 2
    try:
        gaps = collect_gaps()
    except Exception as exc:  # noqa: BLE001 - 查不成就是 2，绝不能被读成 0 或 1
        print(f"没查成：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(render(gaps))
    return 1 if gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
