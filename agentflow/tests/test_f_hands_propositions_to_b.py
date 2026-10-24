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

## 判据（以秘书那一层为准）

1. F 的提示词里不再出现"你自己落 statements"这一类话（逐句扫那三种改前写法）；
2. F 的写集不含 `statements`（`capabilities.WRITE_SETS["F"]`，它派生自 `specs/f.py`）；
3. 反真空：F 的写集里仍然有 `attack_plans` 那三张表 —— 写集不是被清空了，
   而是把那一格交给了 B；且提示词里真的写着"交 B 登记"（不是删了那句话了事）。
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

#: 改后必须有的那一句（"交给 B 登记"），以及"你不写那张表"这半句。
_FIXED_TELLINGS: tuple[str, ...] = ("交给 **B 登记**", "你不写那张表")

#: 改前让 F 照着写 `bits` 的那半句（`_NOT_ROUTABLE_KEYS` 会把空对象也算成碰派生面）。
_BITS_TELLING = "`bits` 留空"


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
    """② 反真空：写集不是被清空，提示词里真的写着"交 B 登记"。

    没有这一条，上一条可以靠"把三句话删掉、把写集清空"变绿 ——
    那时 F 依然不知道该把命题交给谁，只是不再被误导。
    """
    text = _f_prompt()
    missing = [line for line in _FIXED_TELLINGS if line not in text]
    assert not missing, f"F 的提示词里缺了'交 B 登记'这半句：{missing}"
    # `bits` 那句坏指导也不许留着（`_NOT_ROUTABLE_KEYS` 会把空对象判成 direct_write）
    assert _BITS_TELLING not in text, (
        "F 的提示词里还在教它写 `bits` 留空 —— 而那正是 `_NOT_ROUTABLE_KEYS` 判 direct_write 的形态")

    write_set = C.WRITE_SETS["F"]
    assert {"attack_plans", "reprocess_requests", "search_requests"} <= set(write_set), (
        f"F 的写集被清空了（它本来就该写这三张表）：{sorted(write_set)}")
