"""判据：`used_by` 里那个证明尾巴的解析（业主 2026-10-22 的多证明模型，S1 纯函数层）。

## 这一层守什么

`dependencies.used_by = "stmt:000004#p2"` 表示"第 2 条证明用到它"，不带 `#pN` 等价于第 1 条。
解析只许有一份（`agentflow.proofloc`）：两份解析意味着"台账上是第 2 条、读出来是第 1 条"
这种错没有任何东西会报 —— 而它会让 R10 把一条没复核过的证明算成复核过。

## 五条（每条都对着一类改坏的方式）

1. 兼容：不带尾巴的老写法逐字不变（`used_by_of` 不硬加 `#p1`；`#p0`/负数也不许造出尾巴）；
2. 正常：`#p2` 生成与还原成一条直线；显式 `#p1` 还原成 canonical 且算干净；
3. 坏后缀负控：`#p0` / `#p-1` / `#p` / `#pabc` / 没有命题号 —— 不许 raise，按 canonical 读，
   且 `problem` 就是坏尾巴原文（"写坏了"与"没写"必须分得开）；
4. 边界（业主定口径）：`#` 结尾、多段 `#p2#p3` 都是坏尾巴；空串是"没有这条依赖"（干净）；
5. 去重升序：`proof_nos_of` 给出这条定理用到哪几条证明。
"""

from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import proofloc as P  # noqa: E402


def test_the_old_form_is_byte_for_byte_unchanged() -> None:
    """① 兼容：老数据那一格逐字不变 —— 不许被"顺手规范化"成 `#p1`。"""
    assert P.used_by_of("stmt:000004") == "stmt:000004", "老写法不许被硬加 #p1"
    assert P.used_by_of("stmt:000004", 1) == "stmt:000004"
    assert P.used_by_of("stmt:000004", 0) == "stmt:000004", "0 不是证明号，不许造出 #p0"
    assert P.used_by_of("stmt:000004", -1) == "stmt:000004"
    assert P.parse_used_by("stmt:000004") == ("stmt:000004", 1)
    assert P.parse_used_by_checked("stmt:000004") == ("stmt:000004", 1, "")


def test_a_proof_position_round_trips() -> None:
    """② 正常：生成与还原是同一条直线，显式 `#p1` 与不带尾巴等价。"""
    made = P.used_by_of("stmt:000004", 2)
    assert made == "stmt:000004#p2"
    assert P.parse_used_by(made) == ("stmt:000004", 2)
    assert P.parse_used_by_checked(made) == ("stmt:000004", 2, "")
    assert P.parse_used_by_checked("stmt:000004#p1") == ("stmt:000004", 1, ""), (
        "显式写出来的 #p1 是干净的 canonical，不是坏尾巴")
    assert P.is_canonical(made) is False and P.is_canonical("stmt:000004") is True


def test_a_broken_tail_is_never_silently_read_as_proof_one() -> None:
    """③ 负控：坏尾巴不许被当成"第 1 条证明"，也不许抛（读侧到处会调它）。"""
    broken = ("stmt:000004#p0", "stmt:000004#p-1", "stmt:000004#p", "stmt:000004#pabc", "#p2")
    for bad in broken:
        head, number, problem = P.parse_used_by_checked(bad)
        assert (head, number) == (bad, P.DEFAULT_PROOF_NO), f"{bad} 必须原样交回、读成 canonical"
        assert problem == bad, f"{bad} 的 problem 必须是坏尾巴原文（不许只给一个布尔）"
        assert P.parse_used_by(bad) == (bad, 1), bad


def test_edge_shapes_are_pinned_and_never_raise() -> None:
    """④ 边界（业主 2026-10-22 定的口径）：坏的读成 canonical 并留痕，空串是干净的"没有"。"""
    for bad in ("stmt:000004#", "stmt:1#p2#p3"):
        assert P.parse_used_by_checked(bad) == (bad, 1, bad), (
            f"{bad} 是坏尾巴：原样交回、读成 canonical、problem 非空")
    assert P.parse_used_by_checked("") == ("", 1, ""), "空串是'没有这条依赖'，不是坏尾巴"
    assert P.proof_nos_of([""]) == [1]


def test_proof_numbers_are_deduped_and_sorted() -> None:
    """⑤ 读侧列"这条定理有哪几条证明"：去重升序，空集是空表。"""
    assert P.proof_nos_of(["a", "a#p2", "a#p3", "b", "a#p2"]) == [1, 2, 3]
    assert P.proof_nos_of([]) == []
