# -*- coding: utf-8 -*-
"""判据 ②：F 的命题要交 B 登记，F 自己不写 `statements`。

## 改前是什么形态（两层对立，照规格做就撞墙）

- `specs/f.py` 的 policy 三处教「`statements` 那一行由你写 / 你自己落成 `statements` 一行」，
  而 `WRITE_SETS["F"]` 里也真有 `statements` 这一格；
- 秘书那一层只有一条规矩：`secretary.STATEMENT_WRITER_ROLES = ("B",)` ——
  命题只经秘书 / B 登记（业主口径）。

于是 F 被教着去写一张它写不进的表：真机 4 条 `not_statement_writer` 全是照那份规格做出来的。
顺带还有一句更细的坏指导：policy 让 F 落那一行时「`bits` 留空」，
而 `tools/table_tools.py` 的 `_NOT_ROUTABLE_KEYS` 把空对象也算作"碰了派生面"
⇒ 照规格写 `bits={}` 会被判 `direct_write`。

## 2026-11-07（业主 A4 裁边）之后「交给谁」的那条路变了

裁掉了 F→B 的直接出边（「防止向下交稿，F 只能向上通过 D 向 B 交稿」）：
F 交稿向上走 D，D 携带给 B，B 读稿登记（登记仍是 B 的活，F 仍然不写那张表）。
所以这一条钉的"交 B 登记"必须写成那条路，而不是直连 B —— 后者现在是一句照做就会
撞墙的话（边不存在）。反真空因此有两半：路上那几句要在，直连 B 的旧说法要不在。

## 判据（以秘书那一层为准）

1. F 的提示词里不再出现"你自己落 statements"这一类话（逐句扫那三种改前写法）；
2. F 的写集不含 `statements`（`capabilities.WRITE_SETS["F"]`，它派生自 `specs/f.py`）；
3. 反真空：F 的写集里仍然有 `attack_plans` 那三张表 —— 写集不是被清空了，
   而是把那一格交给了 B；且提示词里真的写着那条路（不是删了那句话了事）。
"""
from __future__ import annotations

from agentflow import capabilities as C
from agentflow.agent_prompts import system_prompt
from agentflow.tools import build_registry

#: 改前那三种写法（逐条来自 `specs/f.py` 的三处 policy）。它们一个都不许再出现在提示词里。
_STALE_TELLINGS: tuple[str, ...] = (
    "那一行由你写",
    "你自己落成 `statements`",
    "你落 `statements` 那一行",
)

#: 改后必须有的那几句：路（向上走 D）、怎么到 B（D 携带）、谁登记（B 读稿登记），
#: 外加"你不写那张表"这半句。2026-11-07 A4 裁边之后「交给 B 登记」已不是这条路的口径。
_FIXED_TELLINGS: tuple[str, ...] = (
    "交稿向上走 D",
    "经 D 携带给 B",
    "B 读稿登记",
    "你不写那张表",
)

#: 直连 B 的旧说法（F→B 那条边已被 2026-11-07 的裁定裁掉）：提示词里一个都不许留。
_STALE_ROAD = "交给 **B 登记**"

#: 改前让 F 照着写 `bits` 的那半句（`_NOT_ROUTABLE_KEYS` 会把空对象也算成碰派生面）。
_BITS_TELLING = "`bits` 留空"


def _flat(text: str) -> str:
    """去掉空白 —— 判「读到的意思」，不判排版换行/换行位置（与 d-e-f 那一份同一把尺）。"""
    return "".join(str(text).split())


def _f_prompt() -> str:
    """F 的提示词（生产路径与审计面共用的唯一渲染入口）。"""
    return system_prompt("F", registry=build_registry().registry)


def test_f_never_writes_the_statements_row_itself() -> None:
    """② F 的提示词不再教它自己落 statements，写集也不含 statements。

    改前红：三句 stale 的话都在提示词里，`WRITE_SETS["F"]` 里也有 `statements`。
    """
    text = _f_prompt()
    hits = [line for line in _STALE_TELLINGS if line in text]
    assert not hits, f"F 的提示词里还在教它自己写 statements：{hits}"

    write_set = C.WRITE_SETS["F"]
    assert "statements" not in write_set, (
        "F 的写集里还有 statements —— 秘书那一层只认 B（"
        f"`secretary.STATEMENT_WRITER_ROLES`），F 拿着这一格只会撞 not_statement_writer；"
        f"现写集：{sorted(write_set)}")


def test_f_still_has_a_write_set_and_the_prompt_points_at_b() -> None:
    """② 反真空：写集不是被清空，提示词里真的写着"交稿向上走 D（D 携带给 B 登记）"。

    没有这一条，上一条可以靠"把三句话删掉、把写集清空"变绿 ——
    那时 F 依然不知道该把命题交给谁，只是不再被误导。

    2026-11-07（业主 A4 裁边：删 F→B 直连边）之后这条路只许是 F→D→B：所以除了
    "路上那几句要在"，还要反面判一次 —— 直连 B 的旧说法不许留，否则 F 会照着一句
    结构上做不到的话去交稿。
    """
    text = _f_prompt()
    flat = _flat(text)
    missing = [line for line in _FIXED_TELLINGS if _flat(line) not in flat]
    assert not missing, f"F 的提示词里缺了'交稿向上走 D 到 B'那几句：{missing}"
    assert _flat(_STALE_ROAD) not in flat, (
        f"F 的提示词里又出现了直连 B 的旧说法 {_STALE_ROAD!r}：F→B 那条边已被 "
        "2026-11-07 的裁定裁掉，F 只能交稿向上走 D（D 携带给 B、B 读稿登记）")
    # `bits` 那句坏指导也不许留着（`_NOT_ROUTABLE_KEYS` 会把空对象判成 direct_write）
    assert _BITS_TELLING not in text, (
        "F 的提示词里还在教它写 `bits` 留空 —— 而那正是 `_NOT_ROUTABLE_KEYS` 判 direct_write 的形态")

    write_set = C.WRITE_SETS["F"]
    assert {"attack_plans", "reprocess_requests", "search_requests"} <= set(write_set), (
        f"F 的写集被清空了（它本来就该写这三张表）：{sorted(write_set)}")
