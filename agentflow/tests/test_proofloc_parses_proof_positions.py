"""判据：`used_by` 里那个证明尾巴的解析（业主 2026-10-22 的多证明模型，S1 纯函数层）。

## 这一层守什么

`dependencies.used_by = "stmt:000004#p2"` 表示"第 2 条证明用到它"，不带 `#pN` 等价于第 1 条。
解析只许有一份（`agentflow.proofloc`）：两份解析意味着"台账上是第 2 条、读出来是第 1 条"
这种错没有任何东西会报 —— 而它会让 R10 把一条没复核过的证明算成复核过。

## 五条

1. 兼容：不带尾巴的老写法逐字不变（`used_by_of` 不硬加 `#p1`）；
2. 正常：`#p2` 生成与还原成一条直线；
3. 坏后缀负控：`#p0` / `#p` / `#pabc` / 无头 —— 不许 raise，按 canonical 读，且 problem 非空；
4. 边界：`#` 结尾、多段 `#p2#p3` —— 各自口径被钉住（都不抛）；
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
    assert P.used_by_of("stmt:000004") == "stmt:000004", "老写法不许被硬加 #p1"
    assert P.used_by_of("stmt:000004", 1) == "stmt:000004"
    assert P.parse_used_by("stmt:000004") == ("stmt:000004", 1)
    assert P.parse_used_by_checked("stmt:000004") == ("stmt:000004", 1, "")


def test_a_proof_position_round_trips() -> None:
    made = P.used_by_of("stmt:000004", 2)
    assert made == "stmt:000004#p2"
    assert P.parse_used_by(made) == ("stmt:000004", 2)
    assert P.parse_used_by_checked(made) == ("stmt:000004", 2, "")
    assert P.is_canonical(made) is False and P.is_canonical("stmt:000004") is True


def test_a_broken_tail_is_never_silently_read_as_proof_one() -> None:
    """负控：坏后缀不许被当成"第 1 条证明"，也不许抛（读侧到处会调它）。"""
    for bad in ("stmt:000004#p0", "stmt:000004#p", "stmt:000004#pabc", "#p2"):
        head, number, problem = P.parse_used_by_checked(bad)
        assert number == P.DEFAULT_PROOF_NO, bad
        assert problem, f"{bad} 必须留痕（否则写坏了与没写分不开）"
        assert P.parse_used_by(bad) == (head, 1), bad


def test_edge_shapes_do_not_raise() -> None:
    for text in ("stmt:000004#", "stmt:1#p2#p3", "", "stmt:000004#p1"):
        head, number = P.parse_used_by(text)  # 不 raise 就是这一条要的
        assert isinstance(head, str) and isinstance(number, int)


def test_proof_numbers_are_deduped_and_sorted() -> None:
    assert P.proof_nos_of(["a", "a#p2", "a#p3", "b", "a#p2"]) == [1, 2, 3]
    assert P.proof_nos_of([]) == []
