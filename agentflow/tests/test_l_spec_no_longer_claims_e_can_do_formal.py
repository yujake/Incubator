# -*- coding: utf-8 -*-
"""判据：`specs/l.py` 不再写「E 的 run_experiment(method='formal') 仍能落 proof 行」（乙-7）。

## 为什么这一条必要

`LATER_EDGES` 的 `E → L` 那一条，理由里原写着「E 自己的
`run_experiment(method="formal")` 仍然能落 proof 级实验行」。这句话与实现相反：
E 的动作面第一句就以理由码 `formal_not_in_e` 拒绝 `method="formal"`（不起检查器、
不落行），形式化只走 L 的 `formal.formalize` / `formal.check_formal` / `formal.record`。
读声明的人会据此以为"不需要 E → L，因为 E 自己还能做" —— 那是一条已经不通的老路。

## 判据（每条都两向）

| # | 量什么 | 期望 |
|---|---|---|
| a | `specs/l.py` 现文本 | 不含「仍能落 proof」/「仍然能落」，且 `E → L` 的理由里出现 `formal_not_in_e` |
| b | 实现那一侧 | `agent_e._support.E_NO_FORMAL_REASON == "formal_not_in_e"`（文档说的理由码是真的） |
| c | 反真空 | 把旧句喂给同一个读法 ⇒ 报问题（判据不是橡皮图章） |

零模型调用、零盘上写；只读声明文本与常量。
"""
from __future__ import annotations

import pathlib

from agentflow.agent_e._support import E_NO_FORMAL_REASON

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC_L = ROOT / "src" / "agentflow" / "specs" / "l.py"

#: 旧句的两种写法（任何一处出现都算旧口径还在）。
OLD_CLAIMS: tuple[str, ...] = ("仍然能落 proof", "仍能落 proof")


def _problems(text: str) -> list[str]:
    """这段声明文本与 `formal_not_in_e` 不符的地方（空表 = 一致）。"""
    body = str(text or "")
    out = [f"旧句还在：{old!r}" for old in OLD_CLAIMS if old in body]
    if E_NO_FORMAL_REASON not in body:
        out.append(f"`E → L` 那一节没有点名理由码 {E_NO_FORMAL_REASON!r}")
    return out


# ====================================================================== a 现文本
def test_a_the_spec_no_longer_claims_e_can_do_formal() -> None:
    """`specs/l.py` 不再说 E 自己能落 formal proof 行；`E → L` 的理由点名 `formal_not_in_e`。"""
    problems = _problems(SPEC_L.read_text(encoding="utf-8"))
    assert problems == [], "specs/l.py 的 E → L 理由还是旧口径：" + "；".join(problems)


# ====================================================================== b 实现
def test_b_the_reason_code_is_the_one_the_implementation_uses() -> None:
    """文档点名的理由码就是实现里的那个常量（不是另编一个字符串）。"""
    assert E_NO_FORMAL_REASON == "formal_not_in_e", E_NO_FORMAL_REASON


# ====================================================================== c 反真空
def test_c_the_old_sentence_is_caught() -> None:
    """反真空：把旧句喂给同一个读法 ⇒ 报问题（判据不是橡皮图章）。"""
    old = ("#: - `E → L`：……而它在今天也不必要：E 自己的 "
           "`run_experiment(method=\"formal\")` 仍然能落 proof 级实验行。")
    assert _problems(old) != [], "旧句没被 `_problems` 抓到 ⇒ 这一条量不到口径"
    assert any("旧句还在" in p for p in _problems(old)), _problems(old)
