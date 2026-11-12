"""台账里 `dependencies.used_by` 的路径尾巴（`#pN`）的唯一解析点。

一条定理在台账上可以有多条路径（同一个命题的第 2 份证明是另一份稿，收录时由 B 分配
`path_group`）：`used_by = "stmt:000004#p2"` 表示"第 2 条路径用到它"。不带尾巴等价于第 1 条
（canonical），所以老数据与老判据的读数逐字不变。

注意口径：这里的 `pN` 是台账上的路径号，不是产出侧的版本号 —— 产出侧「同稿号多版本 /
`-pN`」已作废（一个稿号 = 一份文件 = 一份证明），`proof_no` 在产出侧与签侧都已退役。

全仓别的模块要拆这个尾巴就调这里，不许自己 split —— 两份解析意味着"台账上是第 2 条、
读出来是第 1 条"这种错没有任何东西会报。判据：
`tests/test_proofloc_parses_proof_positions.py`。

- 干净：`stmt:000004`（老写法）、`stmt:000004#p1`（显式第 1 条）、`stmt:000004#p2`；
- 坏尾巴（读成第 1 条，坏尾巴原文交回 `problem`）：`#p0` / `#p-1` / `#p` / `#pabc` /
  `#` 结尾 / 多段 `#p2#p3` / 没有命题号的 `#p2`；
- 空串 = "没有这条依赖"，不是坏尾巴。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

#: 缺省路径号（1 = canonical，也就是老数据里那条唯一的路径）。
DEFAULT_PROOF_NO = 1
#: 干净尾巴的形状：恰好一段 `#p` + 正整数，且它前面必须还有命题号（`head` 非空）。
#: 多段 / `#` 结尾 / 没有命题号那一类不靠这一条正则兜，由 `parse_used_by_checked` 先判。
_TAIL = re.compile(r"^(?P<head>.+)#p(?P<num>[0-9]+)$")


def used_by_of(stmt_id: str, proof_no: int = DEFAULT_PROOF_NO) -> str:
    """生成依赖的 `used_by`；第 1 条路径原样返回 `stmt_id`（不加 `#p1`，老写法逐字不变）。"""
    text = str(stmt_id or "")
    try:
        number = int(proof_no)
    except (TypeError, ValueError):
        return text
    if number <= DEFAULT_PROOF_NO:
        return text
    return f"{text}#p{number}"


def parse_used_by(used_by: str) -> tuple[str, int]:
    """拆成 `(stmt_id, 路径号)`；坏后缀不猜、不抛 —— 一律按 canonical 读。"""
    head, number, _problem = parse_used_by_checked(used_by)
    return head, number


def parse_used_by_checked(used_by: str) -> tuple[str, int, str]:
    """同 :func:`parse_used_by`，多返回一项 problem：空串 = 干净，非空 = 坏尾巴原文。

    空串是"没有这条依赖"，算干净。绝不 raise：它被所有读侧调用，而"读侧拿不到答案"
    比"读成 canonical 并留痕"更坏。
    """
    text = str(used_by or "")
    if "#" not in text:
        return text, DEFAULT_PROOF_NO, ""
    if text.count("#p") != 1:
        return text, DEFAULT_PROOF_NO, text
    match = _TAIL.match(text)
    if match is None:
        return text, DEFAULT_PROOF_NO, text
    number = int(match.group("num"))
    if number < DEFAULT_PROOF_NO:
        return text, DEFAULT_PROOF_NO, text
    return match.group("head"), number, ""


def proof_nos_of(used_bys: Iterable[str]) -> list[int]:
    """这批依赖用到哪几条路径（去重升序）—— 读侧列"这条定理有几条路径"用它。"""
    return sorted({parse_used_by(item)[1] for item in used_bys})


def is_canonical(used_by: str) -> bool:
    """这条依赖挂在 canonical（第 1 条）路径上吗。"""
    return parse_used_by(used_by)[1] == DEFAULT_PROOF_NO
