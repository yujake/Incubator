"""工具 handler 的跨分支键集合一致性（`R7-AN-1` 的根因判据）。
## 为什么需要它
`R7` 的重审报出两条 low，都是同一个形态：同一个 handler 的两条返回分支给出不同的键集合，于是 `returns=` 只能描述其中一支，另一支永远是"声明看不见的缺口"，调用方必须先判某个标志位才能安全读键。
- `tools/search_tools.py::_h_register`（`F2` 修前）：新建支 12 键 / 判重支 13 键（判重支多 `matched_key`），
而代码注释逐字声称"两条分支必须返回同一套键（`G-23`）"；- `tools/research_tools.py::research_submit_gap`（`F2` 修前）：判重支没有 `mode`/`topic`，新建支没有
`reason`/`open_requests`，而 `returns=` 写了其中的一半。
它们能活下来的原因是结构性的：现有的子集判据对每个工具只真跑一次（走"新建成功"那一支），所以另一支的键集合从来没有被任何判据看过。这条判据改看静态字节：同一个函数里所有（看得见的）`ok({...})` 字面量，键集合必须相同。
## 口径（写清楚，因为它同时是判据的一部分）
- 管：同一个函数里出现两个以上"看得见"的 `ok(...)` 调用时，它们的键集合必须两两相等。"看得见的" = 实参是字面量 dict，且所有键都是字符串常量（没有 dict 展开）。- 不管，如实登记：1.
实参不是字面量（变量、函数调用、`ok(True)` 这类）；2. dict 里有 dict 展开或非字面量键；3. 跨函数的间接返回；4. `fail(...)` 的键（失败分支本来就不该与成功分支同形）—— 那是另一个主题；5.
`returns=` 的措辞（属于 `C1` 的词表判据）。- 对第 1、2 类：本文件用一个钉死的每模块计数表把它们原样记下来。这不是"豁免"，而是"让看不见这件事可见"：新增一个看不见的调用点 ⇒ 这张表就对不上 ⇒ 红。
要放行必须改表，而改表会出现在 diff 里，评审看得见。
## 正控 / 负控
- 正控：真实模块全过，并断言"看得见的调用点足够多"（否则判据自己成了真空）；- 负控（证明注入生效）：把当前字节复制一份、只删掉一个键，同一个扫描函数必须报出不一致，并打印副本 sha256 作指纹；
锚点漂了也要红（不许静默通过）。
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "src" / "agentflow" / "tools"

#: 看不清的 `ok(...)` 调用点：每模块处数（2026-09-27 由本文件的扫描函数量出；
#: 2026-10-01 `T-8` 搬移后按调用点去重后重算，见 `scan` 的 docstring）。
#: 它保守、可复算：任何一处新增/删除都会让 `test_invisible_ok_sites_do_not_grow_silently` 变红。
INVISIBLE_OK_SITES: dict[str, int] = {
    "attack_tools.py": 1,
    "doc_tools.py": 2,
    "fs_tools.py": 7,
    "ocr_tools.py": 1,
    "review_tools.py": 1,
    "search_tools.py": 3,
    "table_tools.py": 7,
    # 2026-10-01（`draft/28` §218.3）：`T-8` 把工具体从 `register` 里搬到模块级之后，
    # 这两个数字当场减半（22 → 11、18 → 9）—— 不是因为代码变了，而是因为原来的
    # 数法是 `ast.walk` 每层函数各数一遍（嵌套的 `ok(...)` 被外层与内层各走到一次）。
    # 真实处数一直是 11 / 9；跟着改的是条数法本身（`scan` 现在按 `(行, 列)` 去重）。
    "trace_tools.py": 11,
    # `verify_tools.py` 同族：5 里那 2 处是 `register` 的嵌套 helper 被重复数的，
    # 真实处数是 3。
    #
    # 2026-10-06（F-02，角色 V）：3 → 6。新增的三件只读工具
    # （`verify.verify_proof` / `verify.list_verifications` / `verify.read_proof`）
    # 都写成 `ok(_agent_v().<方法>(…))`：键由 `AgentV` 那三个 handler 决定
    # （它们是"三条返回路径键集合完全相同"的实现，见 `agent_v/core.py`），
    # 静态扫描在工具层读不出来，所以如实记进本表（这是本文件允许的"次之"路径：
    # 改数字并在说明里写清）。没有改判据的强度 ——
    # `tests/test_tools_returns_declaration.py` 的"声明必须是实跑键集的子集"
    # 仍然逐工具跑过这三件（探针不求模型，走 `checked=False` 那条）。
    "verify_tools.py": 6,
    # 主控工具模块里"键由运行时数据决定、静态扫描读不出来"的那几处（如实记在"看不清"这一栏，逐批归位）：
    # T0-9（2026-09-28）：8 件，工具体一律 `ok(data, data)`；§198（2026-09-30）`conductor.summon_many` 加进来
    # ⇒ 16 → 18（旧数法），2026-10-01 按调用点去重后是 9。2026-10-09（S1b 加 `conductor.board` 时欠下的一格，
    # H-1a 归位）：10 → 11 —— `conductor_board` 写 `ok(view, **view)`，键由 `Conductor.board_view` 的返回值决定，
    # 它的 `returns=` 逐字声明 `{'checked','open_items','open_count','readings'}` 并已通过实跑核。
    # 2026-10-09（S6-b 加 `conductor.broadcast` 时欠下的一格，同批归位）：11 → 12 —— `conductor_broadcast`
    # 写 `ok(got, **got)`，键由 `Conductor.broadcast` 的返回值决定，`returns=` 逐字声明八个键并由实跑核钉住
    # （探针在 `calling_as` 里跑，走"没有收件人"那一支）。该函数的载荷见它自己的注释；"声明必须是实跑键集的 # 子集"由 `test_tools_returns_declaration.py` 钉住。
    # 2026-10-21：12 → 13 —— 第 13 处是 `conductor_escalate` 的 `ok(payload, **got)`。
    # 它 2026-10-19 随 `conductor.escalate`（业主「父子天然双向」）进树时就没登记，
    # 于是这一条前存红（清洁前 `cdcb843` 上同样红，不是清洁造成的）。
    # 为什么它是"看不清"而不是"看得见"：键由 `Conductor.escalate` 的返回 dict 决定
    # （`checked`/`state`/`to`/`msg_id` … 十二条都在运行时那一份里），静态扫描读不出来。
    # 为什么不改成字面量 dict（本条判据的"好"方向）：那一处现在是透传
    # （只摘掉 `addressing` / `roster_unavailable` 两格框架读数，其余照原样给出），
    # 而 `test_tools_returns_declaration.py` 的"给了却没声明"那一半正是靠透传才咬得住
    # —— 硬写字面量会让它以后新加的键永远不可能"出现在 `data` 里"，那条判据对这一件
    # 工具就永远看不见缺口了。两害相权：保透传 + 在这里如实登记处数。
    "conductor_tools.py": 13,
    # T3-P7（2026-09-29）：猜想台账的产出面。那 1 处是 `_guard_result` 里的
    # `ok(fn())` —— 键由被包的函数（`register_conjecture` 返回的落库行）决定，
    # 静态扫描读不出来。该工具的 `returns=` 已逐字声明那 17 个键，并由
    # `test_tools_returns_declaration.py` 的"声明必须是实跑键集的子集"钉住。
    "conjecture_tools.py": 1,
    # 2026-10-04（`draft/37` §134）：交接手稿的读面。那 1 处是 `manuscripts.read` 的
    # `ok(data, data)` —— 键由手稿索引里的那条 record（`manuscripts.write` 落的行）
    # 决定，静态扫描读不出来。与 `conductor_tools.py` 那一栏同族：该工具的 `returns=`
    # 已逐字声明那 12 个键，由 `test_tools_returns_declaration.py` 的
    # "声明必须是实跑键集的子集"钉住。
    "manuscript_tools.py": 1,
    # 2026-10-24：这批新增的两处 —— cache_tools 的两个 ok(doc) 与 formal_tools 的三处 ok({...})，
    # 数字来自盘上实测；它们都是"看不清的分支"（ok 里没有 await/return 那种显式键）。
    "cache_tools.py": 2,
    "formal_tools.py": 3,
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

    "看不清"按调用点去重（`(行, 列)`）：`ast.walk` 会从外层函数走进嵌套函数，
    所以同一个 `ok(...)` 在外层与内层各被走到一次。原来不去重 ⇒ 每模块的处数
    被嵌套层数放大（实测：`conductor_tools` 18 / `trace_tools` 22 是双倍，
    真实处数是 9 / 11 —— 见 `draft/28` §218.3 的读数）。`T-8` 把工具体从
    `register` 里搬到模块级之后那两个数字当场减半，红的就是本条判据。
    """
    found: dict[str, list[tuple[int, tuple[str, ...]]]] = {}
    invisible: dict[str, int] = {}
    for f in sorted(root.glob("*_tools.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        sites: set[tuple[int, int]] = set()
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
                    sites.add((call.lineno, call.col_offset))
                else:
                    sets.append((call.lineno, keys))
            if sets:
                found[f"{f.name}::{fn.name}"] = sets
        if sites:
            invisible[f.name] = len(sites)
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
