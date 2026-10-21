"""`G-14`：R006 已退休 —— 而且"退休"这件事本身必须是可断言的。

为什么需要这一节：退休一条规则最容易的坏法是悄悄不报。那样规则数仍是 10、
输出也看不出异常，于是读者会以为判据面没变，而实际上少了一条。
所以这里钉四件事：退休有登记、退休后不产生 findings、编号仍在注册表里（不悬空）、
接替者（R010）真的存在。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("_lint_rules_under_test", ROOT / "scripts" / "lint_rules.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load()


def test_r006_is_retired_with_a_reason() -> None:
    """退休必须显式登记并带理由。

    没有这张表时，读者只能看到"规则 10 条"，看不出其中一条已经不干活 ——
    数字相同不等于内容相同（`G-32`）。
    """
    assert "R006" in L.RETIRED_RULES, "退休没登记 ⇒ 规则数会假装没变"
    assert L.RETIRED_RULES["R006"].strip(), "退休必须写清理由，否则下一个人只会把它改回来"


def test_retired_rule_produces_no_findings() -> None:
    """退休后不再产生 findings（判据面已由 R010 逐工具承担）。"""
    assert L.rule_R006_read_tool_touches_network(ROOT) == []


def test_retired_rule_keeps_its_number_in_the_registry() -> None:
    """编号保留：删号会让历史报告与 `DEVELOPMENT.md` §6 里的 "R006" 变成悬空引用。"""
    assert any("R006" in str(entry) for entry in L.RULES), "R006 从注册表里消失了"


def test_the_replacement_rule_exists_and_is_registered() -> None:
    """接替者必须真的在册 —— 否则"退休"就变成了"判据面凭空消失"。"""
    assert hasattr(L, "rule_R010_external_axis_mismatch")
    assert any("R010" in str(entry) for entry in L.RULES), "R010 没有注册（那 R006 就是白退的）"
