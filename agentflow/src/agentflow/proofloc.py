"""证明定位的唯一解析点：`dependencies.used_by` 里那个 `#pN` 尾巴（业主 2026-10-22）。

一条定理可以有多条证明：`used_by = "stmt:000004#p2"` 表示"第 2 条证明用到它"。
不带 `#pN` 一律等价于 `#p1`（canonical），所以老数据与老判据的读数逐字不变。
全仓别的模块要拆这个尾巴就调这里，不许自己 split —— 两份解析意味着"台账上是第 2 条、
读出来是第 1 条"这种错没有任何东西会报。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

#: 缺省证明号（1 = canonical，也就是老数据里那条唯一的证明）。
DEFAULT_PROOF_NO = 1
#: 尾巴的形状：`#p` 后面必须是正整数（`#p0` / `#p` / `#pabc` 都不算）。
_TAIL = re.compile(r"^(?P<head>.*?)#p(?P<num>[0-9]+)$")


def used_by_of(stmt_id: str, proof_no: int = DEFAULT_PROOF_NO) -> str:
    """生成依赖的 `used_by`；第 1 条证明原样返回 `stmt_id`（不加 `#p1`，老写法逐字不变）。"""
    text = str(stmt_id or "")
    try:
        number = int(proof_no)
    except (TypeError, ValueError):
        return text
    if number <= DEFAULT_PROOF_NO:
        return text
    return f"{text}#p{number}"


def parse_used_by(used_by: str) -> tuple[str, int]:
    """拆成 `(stmt_id, proof_no)`；坏后缀不猜、不抛 —— 一律按 canonical 读。"""
    head, number, _problem = parse_used_by_checked(used_by)
    return head, number


def parse_used_by_checked(used_by: str) -> tuple[str, int, str]:
    """同 :func:`parse_used_by`，多返回一项 problem：空串 = 干净，非空 = 坏后缀原文。

    三态在这一格上：`#p2` 是干净的第 2 条；`#p0` / `#p` / `#pabc` 是坏后缀（读成 canonical
    并留痕），没有尾巴则是老数据的 canonical（也算干净 —— "没写"与"写坏了"要分得开）。
    """
    text = str(used_by or "")
    match = _TAIL.match(text)
    if match is None:
        if "#p" in text:
            return text, DEFAULT_PROOF_NO, text
        return text, DEFAULT_PROOF_NO, ""
    number = int(match.group("num"))
    head = match.group("head")
    if number < DEFAULT_PROOF_NO or not head:
        return text, DEFAULT_PROOF_NO, text
    return head, number, ""


def proof_nos_of(used_bys: Iterable[str]) -> list[int]:
    """这批依赖用到哪几条证明（去重升序）—— 读侧列"这条定理有几条证明"用它。"""
    return sorted({parse_used_by(item)[1] for item in used_bys})


def is_canonical(used_by: str) -> bool:
    """这条依赖挂在 canonical（第 1 条）证明上吗。"""
    return parse_used_by(used_by)[1] == DEFAULT_PROOF_NO
