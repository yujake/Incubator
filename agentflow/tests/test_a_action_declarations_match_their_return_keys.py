# -*- coding: utf-8 -*-
"""判据：A 的动作声明面必须与这个动作真会返回的键对得上（2026-11-04，审 F 区）。

## 背景（加这条判据时是红的）

`specs/a.py` 的动作表是主控派活时读的那一格（`capabilities.CAPABILITIES` 由它派生），
所以它写着"返回哪些键"就等于告诉下游"照这几格读"。两处与真身对不上：

- `walk_citations`：声明写「dict（逐键：lit_id / doi / openalex_id / direction /
  count / candidates / note；…）」，而 `agent_a/walk_citations.py` 的返回还有
  `ok` / `kind` / `truncated_to_tool_max` 三格 —— 少了的正是判三态（做成了没有、
  没做成是哪一档）与判截断（给的上限超过工具面上限 50）要用的那三格；
  同一格还写「失败档走工具层的 `fail(...)`：`ok=False` ＋ 一句 `error`」，
  而动作层把工具那句 error 拼进 `note`，返回里根本没有 `error` 这一格。
- `ingest_local`：声明写「IngestReport dict（含 counts / …）」，而实现返回的是
  17 个平铺的计数（`ingested` / `already_present` / `skipped` / `unreadable` …），
  没有 `counts` —— 照 `counts` 去读的人会读到 None，再把"没读到"当"没入库"。

同族先例：题 20 选 A 就是 `search_literature` 的声明面漏了 `sources` / `cost`
那一批跨源读数之后补的（补法逐字抄实现末尾那个 return 字典）。

## 这条判据钉什么

1. 反真空：四个"逐键写出来"的动作，实现里那份主档返回字典的键集至少 6 格，
   且 `walk_citations` 真的有 `truncated_to_tool_max`、`ingest_local` 真的没有 `counts`
   （键集从源码 AST 现读，不手抄）。实现改名/改形状时这条先红，那时要改的是它。
2. 正控：这四个动作声明面第一段（也就是那张键表）必须逐个点名主档的每个键。
3. 负控：从声明里抽掉一个键名 ⇒ 同一个检查必须点名报缺。
4. `walk_citations` 的失败档不许写成「`ok=False` ＋ 一句 `error`」：动作返回里没有
   `error` 这一格（原因原话在 `note` 里）。这一条钉的是"声明面描述的是动作，不是工具"。
"""
from __future__ import annotations

import ast
import pathlib
import re

from agentflow import specs as SP

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"

#: 声明面把键逐个写出来的那四个动作（其余动作写的是 "dict" / "含 …"，没有可核的键表）。
_KEY_LIST_ACTIONS: tuple[tuple[str, str, str], ...] = (
    # (动作名, 实现文件, 方法名)
    ("search_literature", "agent_a/search_literature.py", "search_literature"),
    ("walk_citations", "agent_a/walk_citations.py", "walk_citations"),
    ("ingest_local", "agent_a/ingest_local.py", "ingest_local"),
    ("shelf_search", "agent_a/shelf_search.py", "shelf_search"),
)

#: 键名（小写标识符）。`books[]` 的方括号不影响匹配。
_KEY = re.compile(r"(?<![A-Za-z0-9_])([a-z][a-z0-9_]+)(?![A-Za-z0-9_])")

#: 声明里不该出现的那句（动作层没有 `error` 这一格）。
_STALE_FAILURE = "`ok=False` ＋ 一句 `error`"


def _decl(action: str) -> str:
    """声明面那一格（`specs.builtin_specs()['A']` 里该动作的 `returns`）。"""
    for spec in SP.builtin_specs()["A"].actions:
        if spec.action == action:
            return str(spec.returns or "")
    raise AssertionError(f"`specs/a.py` 里没有动作 {action}（判据的对象没了）")


def _impl_main_keys(rel: str, func: str) -> set[str]:
    """实现里那份主档返回字典的键集：字典字面量里键最多的那一份（现读）。"""
    tree = ast.parse((_SRC / rel).read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == func):
            continue
        dicts: list[set[str]] = []
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                keys = {k.value for k in node.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                if keys:
                    dicts.append(keys)
        if not dicts:
            raise AssertionError(f"{rel} 里 {func} 没有返回字典字面量（判据的对象没了）")
        return max(dicts, key=len)
    raise AssertionError(f"{rel} 里找不到 {func}（判据的对象没了）")


def _named(decl: str) -> set[str]:
    """声明面那张键表里点了名的小写标识符（只取第一段：第一段就是键表）。"""
    first = decl.split("；", 1)[0]
    return set(_KEY.findall(first))


def _missing(decl: str, keys: set[str]) -> list[str]:
    """主档的哪些键没被声明面点名。"""
    named = _named(decl)
    return sorted(k for k in keys if k not in named)


# ---------------------------------------------------------------- ① 反真空：键集本身


def test_the_four_key_list_actions_still_have_real_key_sets() -> None:
    """① 四个动作的主档键集读得到、且本判据的两条前提今天成立。"""
    for action, rel, func in _KEY_LIST_ACTIONS:
        keys = _impl_main_keys(rel, func)
        assert len(keys) >= 6, f"{action} 的主档只有 {len(keys)} 个键 ⇒ 判据在扫空集"
    walk = _impl_main_keys("agent_a/walk_citations.py", "walk_citations")
    assert "truncated_to_tool_max" in walk, (
        "`walk_citations` 的实现里没有 `truncated_to_tool_max` 了 ⇒ 这条判据的前提过期"
        "（那时要改的是它，不是把正控放宽）")
    assert "error" not in walk, (
        "`walk_citations` 的动作返回里现在有 `error` 了 ⇒ 第 ④ 条会开始禁止一句真话："
        "请删掉第 ④ 条，不是把它放宽")
    ingest = _impl_main_keys("agent_a/ingest_local.py", "ingest_local")
    assert "counts" not in ingest, (
        "`ingest_local` 的动作返回里现在有 `counts` 了 ⇒ 这条判据的前提过期")


# ---------------------------------------------------------------- ② 正控：键表必须点齐


def test_every_declared_action_names_its_real_keys() -> None:
    """② 声明面那张键表必须点齐主档的每个键。"""
    bad: list[str] = []
    for action, rel, func in _KEY_LIST_ACTIONS:
        keys = _impl_main_keys(rel, func)
        missing = _missing(_decl(action), keys)
        if missing:
            bad.append(f"{action}：声明面没点名 {missing}（真身：{sorted(keys)}）")
    assert not bad, (
        "动作声明面的键表与真身对不上 —— 下游会照声明读，于是「没读到的格」被当成"
        "「没有这一格」：\n  - " + "\n  - ".join(bad))


# ---------------------------------------------------------------- ③ 负控：检查函数不是橡皮图章


def test_the_checker_is_not_a_rubber_stamp() -> None:
    """③ 从声明里抽掉一个键名 ⇒ 同一个检查必须点名报缺。"""
    decl = _decl("walk_citations")
    keys = _impl_main_keys("agent_a/walk_citations.py", "walk_citations")
    assert not _missing(decl, keys), "夹具前提：改后这一格应当已经点齐"

    doctored = decl.replace("truncated_to_tool_max", "", 1)
    assert doctored != decl, "夹具前提：这一格里有 `truncated_to_tool_max` 可抽"
    got = _missing(doctored, keys)
    assert got == ["truncated_to_tool_max"], (
        f"抽掉一个键名之后检查函数报的是 {got} ⇒ 它不是判据")


# ---------------------------------------------------------------- ④ 失败档描述的是动作


def test_walk_citations_does_not_promise_an_error_key() -> None:
    """④ 动作的返回里没有 `error` 这一格 ⇒ 声明面不许照工具层的 `fail(...)` 写它。"""
    keys = _impl_main_keys("agent_a/walk_citations.py", "walk_citations")
    assert "error" not in keys
    decl = _decl("walk_citations")
    assert _STALE_FAILURE not in decl, (
        "声明面写着「`ok=False` ＋ 一句 `error`」，而动作层把工具那句 error 拼进 `note`、"
        "返回里没有 `error` 键 —— 照它读的人拿不到那一格")
