"""`D11` 的机器判据：`README.md` 写出来的 linter 规则区间上界必须等于 `RULES` 里真实的最大规则号。

## 为什么这条不变量需要一条测试

`D11` 的缺陷形态不是"数字写错一次"，而是同一条不变量随着加规则反复漂移：
`README.md` 里的 `R001–R011` 在写下时是真的（那时 `scripts/lint_rules.py`
确实只到 R011），后来有人加了活规则 `rule_R012_write_text_newline` 并把它注册进
`RULES`，README 那一处就悄悄过期了 —— 而没有任何测试会发现。
这就是 `D11` 在 `draft/28` 的 §16 台账里先被判"已修"、随后又被判 `regressed` 的原因：
修的是那一处的数字，没修"数字会再次漂移"这件事。

所以修法分两半，缺一半都不算修好：

1. 把 README 更新到当前真实的最大规则号；
2. 把"README 的区间上界 == `RULES` 里的最大规则号"从散文变成判据（本文件）。

有了第 2 半，下一次加规则的人只有两条路：同步 README，或者被这条测试拦住。
那点摩擦正是它该有的形态 —— 与 `T1`（把子集断言 `<=` 改成 `==`）是同一族的取舍：
"恰好覆盖"这种承诺，只在有 `==` 判据时才是真的。

## 判据的口径（刻意写清楚，免得下一个人把它读松）

* 权威是 `RULES`，不是"函数名里出现过的最大号"：`RULES` 是 linter 真正会跑的
  那张表（退休的 R004/R006 也仍在表里，并会打印退休说明）。README 承诺的是
  "这个 linter 有哪几条规则号"，所以该与 `RULES` 对齐。
* 区间上界必须相等，不是"大于等于"：`>=` 会让 README 写一个未来的编号
  （例如规则还没写就先写 R099）而不报警。
* README 里一处区间都没有 ⇒ 判据失去对象 ⇒ 报问题（空输入不许读成通过，
  `P16` 族）。这一条是为了防"把区间删掉让判据变空"。
* "（规则 N 条）"那个计数有则必须对：它是同一句话的另一半，漂了同样会误导
  读者；但它不是本条的主判据（主判据是区间上界），所以不做"必须有"的要求。
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = REPO / "scripts"


def _load_linter():
    """按路径导入 `scripts/lint_rules.py`（`scripts/` 不是包，不能普通 import）。

    与 `tests/test_lint_rules.py::_load_linter` 同一形态：这里刻意不共享它 ——
    两个测试文件各按路径加载一次，模块名不同，互不影响。
    """
    spec = importlib.util.spec_from_file_location(
        "_lint_rules_for_readme_rule_range", _SCRIPTS / "lint_rules.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load_linter()

#: `R001–R011` 形态；破折号认 U+2013（README 用的就是它）、U+2014 与 ASCII `-`。
_RANGE_RE = re.compile(r"R(\d{3})\s*[\u2013\u2014-]\s*R(\d{3})")
#: 区间后面那句"（规则 N 条）"。
_COUNT_RE = re.compile(r"[（(]规则\s*(\d+)\s*条")


def rule_numbers(mod=None) -> list[int]:
    """`RULES` 里真实登记的规则号（按第一栏的 `R0NN` 前缀解析，不靠顺序）。"""
    mod = mod or L
    out: list[int] = []
    for entry in mod.RULES:
        name = str(entry[0])
        m = re.match(r"R(\d{3})", name)
        assert m, f"RULES 的第一栏不是 R0NN 形态：{name!r}"
        out.append(int(m.group(1)))
    assert out, "RULES 里一条规则都没有 —— 判据失去对象（不是通过）"
    return out


def range_problems(readme_text: str, numbers: list[int]) -> list[str]:
    """README 文本 vs 真实规则号 ⇒ 问题清单（空清单 = 判据成立）。

    返回清单而不是布尔：红的时候必须能说清"哪一处、差多少"，
    否则没人能复核这个结论（只回一个 False 的判据自己就不可核）。
    """
    problems: list[str] = []
    top = max(numbers)
    found = _RANGE_RE.findall(readme_text)
    if not found:
        problems.append(
            "README 里一处 `R0NN–R0NN` 区间都没有 ⇒ 本判据失去对象。"
            "（空输入不许读成通过：删掉区间不等于这条不变量成立）")
    for lo, hi in found:
        if int(hi) != top:
            problems.append(
                f"README 写的规则区间上界 R{hi} != `RULES` 里的最大规则号 R{top:03d}"
                f"（README 的区间是 R{lo}–R{hi}）")
        if int(lo) > int(hi):
            problems.append(f"README 的规则区间写反了：R{lo}–R{hi}")
    for n in _COUNT_RE.findall(readme_text):
        if int(n) != len(numbers):
            problems.append(
                f"README 说『规则 {n} 条』，而 `RULES` 里实际 {len(numbers)} 条")
    return problems


def test_readme_lint_rule_range_matches_the_real_max_rule_number() -> None:
    """正控：README 的规则区间上界 == `RULES` 里最大规则号（今天 = R012）。

    这条在 `D11` 落地时是红的（README 写 R011、真实到 R012），
    把 README 更新到 R012 之后转绿 —— 而它下次变红就正好说明"又漂了"。
    """
    text = (REPO / "README.md").read_text(encoding="utf-8")
    problems = range_problems(text, rule_numbers())
    assert not problems, problems


def test_the_criterion_is_not_vacuous_on_the_stale_range() -> None:
    """负控（非恒真）：把 README 的区间上界改回"上一个真实值" ⇒ 判据必须报问题。

    为什么是这一档：`R001–R011` 正是 `D11` 登记时 README 里那一处的真实旧值
    （`temp/batchE2-README.md.bak` 里逐字就是它），而 `RULES` 今天真实到 R012。
    所以这条负控证明的是"判据会在真的漂移时报红"，而不是"它永远为真"。
    """
    text = (REPO / "README.md").read_text(encoding="utf-8")
    top = max(rule_numbers())
    stale = _RANGE_RE.sub(
        lambda m: f"R{m.group(1)}\u2013R{top - 1:03d}", text)
    assert stale != text, "夹具前提：README 里确实有区间可改"
    problems = range_problems(stale, rule_numbers())
    assert problems, "改回旧区间之后判据居然还是绿的 ⇒ 这条判据是恒真的"


def test_a_readme_without_any_range_is_a_problem_not_a_pass() -> None:
    """负控（反真空）：把区间整段删掉 ⇒ 判据必须报"失去对象"，不许读成通过。"""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    stripped = _RANGE_RE.sub("linter（有退出码）", text)
    assert stripped != text, "夹具前提：README 里确实有区间可删"
    problems = range_problems(stripped, rule_numbers())
    assert any("失去对象" in p for p in problems), problems
