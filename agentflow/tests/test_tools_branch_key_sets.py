"""工具 handler 的跨分支键集合一致性（`R7-AN-1` 的根因判据）。

## 为什么需要它

`R7` 的重审报出两条 low，都是同一个形态：同一个 handler 的两条返回分支给出不同的键集合，
于是 `returns=` 只能描述其中一支，另一支永远是"声明看不见的缺口"，调用方必须先判某个标志位
才能安全读键。

- `tools/search_tools.py::_h_register`（`F2` 修前）：新建支 12 键 / 判重支 13 键
  （判重支多 `matched_key`），而代码注释逐字声称"两条分支必须返回同一套键（`G-23`）"；
- `tools/research_tools.py::research_submit_gap`（`F2` 修前）：判重支没有 `mode`/`topic`，
  新建支没有 `reason`/`open_requests`，而 `returns=` 写了其中的一半。

它们能活下来的原因是结构性的：现有的子集判据对每个工具只真跑一次（走"新建成功"那一支），
所以另一支的键集合从来没有被任何判据看过。这条判据改看静态字节：同一个函数里所有
（看得见的）`ok({...})` 字面量，键集合必须相同。

## 口径（写清楚，因为它同时是判据的一部分）

- 管：同一个函数里出现两个以上"看得见"的 `ok(...)` 调用时，它们的键集合必须两两相等。
  "看得见的" = 实参是字面量 dict，且所有键都是字符串常量（没有 dict 展开）。
- 不管，如实登记：
  1. 实参不是字面量（变量、函数调用、`ok(True)` 这类）；
  2. dict 里有 dict 展开或非字面量键；
  3. 跨函数的间接返回；
  4. `fail(...)` 的键（失败分支本来就不该与成功分支同形）—— 那是另一个主题；
  5. `returns=` 的措辞（属于 `C1` 的词表判据）。
- 对第 1、2 类：本文件用一个钉死的每模块计数表把它们原样记下来。这不是"豁免"，
  而是"让看不见这件事可见"：新增一个看不见的调用点 ⇒ 这张表就对不上 ⇒ 红。
  要放行必须改表，而改表会出现在 diff 里，评审看得见。

## 正控 / 负控

- 正控：真实模块全过，并断言"看得见的调用点足够多"（否则判据自己成了真空）；
- 负控（证明注入生效）：把当前字节复制一份、只删掉一个键，同一个扫描函数必须报出不一致，
  并打印副本 sha256 作指纹；锚点漂了也要红（不许静默通过）。
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "src" / "agentflow" / "tools"

#: 看不清的 `ok(...)` 调用点：每模块处数（2026-09-27 由本文件的扫描函数量出）。
#: 它保守、可复算：任何一处新增/删除都会让 `test_invisible_ok_sites_do_not_grow_silently` 变红。
INVISIBLE_OK_SITES: dict[str, int] = {
    "attack_tools.py": 1,
    "doc_tools.py": 2,
    "fs_tools.py": 6,
    "ocr_tools.py": 1,
    "review_tools.py": 1,
    "search_tools.py": 3,
    "table_tools.py": 7,
    "trace_tools.py": 22,
    "verify_tools.py": 5,
    # T0-9（2026-09-28）：主控工具模块 8 件，工具体一律 `ok(data, **data)` ——
    # 键由运行时数据决定，静态扫描读不出来，所以这 16 处如实记在"看不清"这一栏。
    # §198（2026-09-30）：`conductor.summon_many` 加进来 ⇒ 16 → 18
    # （该函数的载荷是运行时算出来的，见它自己的注释；`returns=` 仍逐字声明键集，
    # 由 `test_tools_returns_declaration.py` 的"声明必须是实跑键集的子集"钉住）。
    "conductor_tools.py": 18,
    # T3-P7（2026-09-29）：猜想台账的产出面。那 1 处是 `_guard_result` 里的
    # `ok(fn())` —— 键由被包的函数（`register_conjecture` 返回的落库行）决定，
    # 静态扫描读不出来。该工具的 `returns=` 已逐字声明那 17 个键，并由
    # `test_tools_returns_declaration.py` 的"声明必须是实跑键集的子集"钉住。
    "conjecture_tools.py": 1,
}

#: 看得见的 `ok({...})` 调用点下界（判据不许真空：扫描器坏掉时必须先是红）。
VISIBLE_MIN = 27


def _literal_keys(arg: ast.AST) -> tuple[str, ...] | None:
    """字面量 dict 且键全是字符串常量 ⇒ 键集合；否则 `None`（看不清）。"""
    if not isinstance(arg, ast.Dict):
        return None
    keys: list[str] = []
    for k in arg.keys:
        if k is None or not isinstance(k, ast.Constant) or not isinstance(k.value, str):
            return None
        keys.append(k.value)
    return tuple(sorted(keys))


def scan(root: Path) -> tuple[dict[str, list[tuple[int, tuple[str, ...]]]], dict[str, int]]:
    """扫一个目录下的 `*_tools.py`。

    返回 `(每个函数看得见的 ok 键集合, 每模块看不清的处数)`。
    """
    found: dict[str, list[tuple[int, tuple[str, ...]]]] = {}
    invisible: dict[str, int] = {}
    for f in sorted(root.glob("*_tools.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            sets: list[tuple[int, tuple[str, ...]]] = []
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
                if name != "ok":
                    continue
                keys = _literal_keys(call.args[0]) if call.args else None
                if keys is None:
                    invisible[f.name] = invisible.get(f.name, 0) + 1
                else:
                    sets.append((call.lineno, keys))
            if sets:
                found[f"{f.name}::{fn.name}"] = sets
    return found, invisible


def _disagreeing(found: dict[str, list[tuple[int, tuple[str, ...]]]]) -> dict[str, list[tuple[int, tuple[str, ...]]]]:
    return {k: v for k, v in found.items() if len({s for _, s in v}) > 1}


def _visible_total(found: dict[str, list[tuple[int, tuple[str, ...]]]]) -> int:
    return sum(len(v) for v in found.values())


# ------------------------------------------------------------------ 判据本体


def test_no_handler_returns_two_different_key_sets() -> None:
    """正控：每个 handler 里看得见的 `ok(...)` 键集合必须两两相同。"""
    found, _invisible = scan(TOOLS)
    bad = _disagreeing(found)
    detail = "; ".join(
        f"{k}: " + " | ".join(f":{ln} {len(keys)} 键" for ln, keys in v)
        for k, v in sorted(bad.items())
    )
    assert not bad, (
        "同一个 handler 的两条分支给了不同的键集合（调用方得先判标志位才能安全读键）："
        + detail
    )


def test_the_criterion_is_not_vacuous() -> None:
    """判据不许真空：看得见的调用点要够多，且必须真的有 handler 有多条分支。"""
    found, _invisible = scan(TOOLS)
    total = _visible_total(found)
    multi = {k: v for k, v in found.items() if len(v) > 1}
    assert total >= VISIBLE_MIN, (
        f"看得见的 ok(...) 只剩 {total} 处（下界 {VISIBLE_MIN}）—— 扫描器坏了，"
        "或者工具层的返回形态整体改成了看不清的那种；两种情况都必须先红"
    )
    assert multi, "一个含两条以上分支的 handler 都没有 ⇒ 上面那条判据是空的"
    print("含多条分支的 handler：", sorted(multi))


def test_invisible_ok_sites_do_not_grow_silently() -> None:
    """看不见的调用点：每模块处数必须与钉死的表逐字一致（新增/删除都要显式改表）。"""
    _found, invisible = scan(TOOLS)
    assert invisible == INVISIBLE_OK_SITES, (
        "看不清的 ok(...) 分布变了。两个方向都不许：\n"
        f"  盘上多出来的：{ {k: v for k, v in invisible.items() if INVISIBLE_OK_SITES.get(k) != v} }\n"
        f"  表里对不上的：{ {k: v for k, v in INVISIBLE_OK_SITES.items() if invisible.get(k) != v} }\n"
        "处置：要么把那个返回改成字面量 dict（好），要么在这个表里改数字并在提交信息里说明（次之）。"
    )


def test_the_two_known_handlers_now_agree() -> None:
    """把修过的两处钉住：它们都必须在扫描结果里、且各自两支的键集合相同。"""
    found, _invisible = scan(TOOLS)
    for name in ("search_tools.py::_h_register", "research_tools.py::research_submit_gap"):
        assert name in found, f"{name} 没被扫描到（它应该有两个以上看得见的分支）"
        got = found[name]
        keysets = {s for _, s in got}
        assert len(got) >= 2, f"{name} 只看到一个看得见的分支：{got}"
        assert len(keysets) == 1, f"{name} 的两支键集合仍不同：{got}"


def test_scanner_reports_a_deliberately_removed_key(tmp_path: Path) -> None:
    """负控：复制当前字节、只删一个键 ⇒ 同一个扫描函数必须报出不一致。"""
    raw = (TOOLS / "search_tools.py").read_text(encoding="utf-8")
    anchor = '"matched_key": None,'
    assert anchor in raw, (
        "负控锚点不在了（`search_tools.py` 里没有 "
        '"matched_key": None,`）—— 锚点漂了就必须让这条判据红'
    )
    dst = tmp_path / "search_tools.py"
    dst.write_text(raw.replace(anchor, "", 1), encoding="utf-8", newline="")
    assert anchor not in dst.read_text(encoding="utf-8"), "注入没生效（副本里那一行还在）"
    print("负控指纹：副本 sha256 =", hashlib.sha256(dst.read_bytes()).hexdigest()[:16])

    found, _invisible = scan(tmp_path)
    bad = _disagreeing(found)
    assert bad, "删掉一个键之后扫描器没报不一致 ⇒ 这条判据是真空的（永远通过）"
    assert any("_h_register" in k for k in bad), f"报的不是预期那一处：{sorted(bad)}"
