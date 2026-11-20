# -*- coding: utf-8 -*-
"""每一条逐字期望都必须与产品侧逐字相等 —— 扫全 `tests/` 的通用防复发判据。

## 它防的是什么（2026-11-20 那次自伤）

`2ab3bbdb` 的 R009 清理把 `**` 从代码里的字符串字面量中也一起抹掉了，而 R009 的射程只有
注释与 docstring（`scripts/lint_rules.py::_r009_scan` 只把 `tokenize.COMMENT` 与
`ast.get_docstring` 的区间交给判定）。`tests/` 里两处「逐字豁免」的期望串跟着被抹：
`_G_VERBATIM_OWNER_LINE`（G 的业主原话整行）与 `_ALLOWED_L_PREFIXES` 的第一格。
两处既有判据当场红了，但红的原因是期望单边被改、产品侧原文一个字没动 ——
从红里读不出这一层，下一个人才会误以为是"提示词退步了"或"豁免过期了"。

## 这条判据怎么读

`tests/` 里凡以 `VERBATIM` 命名的模块级期望串，都必须在某个角色的渲染提示词里整行逐字
存在。产品侧的权威读数取 `AP.system_prompt(role)`（模型真正读到的那一份），
不是常量本身：`specs/g.py::WRITING_SCOPE` 被排成列表项之后前面多一个 `- `，所以只有
渲染结果才是"逐字"的可比对象。

于是三种改法各自的下场：
- 只改期望（抹掉 `**`、换措辞）⇒ 红；
- 只改产品（提示词正文被清、被改写）⇒ 红；
- 两边各改一半（"让判据将就实现"）⇒ 也红：判据读的是现盘产品，不是一份自洽的副本。

「逐行白名单」那一族（`_ALLOWED_L_PREFIXES`）另有一条：它的每一格必须真的是某一行的
开头。既有的 `assert 前缀 in _prompt(...)` 只保证"这串字出现在某处"，保证不了
"它是那一行的开头" —— 同一串字出现在行中间也照样过。

## 为什么扫全 `tests/` 而不是写一张清单

清单会漏掉下一个新写的逐字豁免；扫出来的新名字才让"新期望串没接上产品"变成一条红。
扫不到的代价（读不出/解析不了）单列成问题串回来，按三态纪律当作"没查成"，不是"干净"。
"""

from __future__ import annotations

import ast
import re
import warnings
from functools import lru_cache
from pathlib import Path

from agentflow import agent_prompts as AP
from agentflow import schema as S
from agentflow.tools import build_registry

#: 扫的根：`tests/` 自己（本文件也在里面，下面显式排除，免得自己扫自己）。
_TESTS = Path(__file__).resolve().parent
_SELF = Path(__file__).resolve().name

#: 逐字期望的名字形状：`_G_VERBATIM_OWNER_LINE` / `_VERBATIM_OWNER_LINES`。
#: 刻意不匹配裸名 `VERBATIM`：另外两份测试用它表示"一段样本引文"，与提示词无关。
_VERBATIM_NAME = re.compile(r"_VERBATIM|VERBATIM_")

#: 前缀族的白名单表名（`_ALLOWED_*` 里还有许多不是提示词的表，所以逐名登记）。
_PREFIX_TABLES = ("_ALLOWED_L_PREFIXES",)


def _strings_of(value: ast.expr) -> list[str]:
    """一个模块级值里能读出的字符串：字面量 / 序列 / 字典的值。"""
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return [value.value]
    if isinstance(value, (ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in value.elts:
            out.extend(_strings_of(elt))
        return out
    if isinstance(value, ast.Dict):
        out = []
        for val in value.values:
            if val is not None:
                out.extend(_strings_of(val))
        return out
    return []


@lru_cache(maxsize=1)
def module_tables() -> tuple[dict[str, tuple[str, tuple[str, ...]]], list[str]]:
    """扫 `tests/` 的模块级字符串表 ⇒ `({名字: (文件, 期望串...)}, 没查成的文件)`。

    同名符号在多份测试里出现时后写的覆盖先写的（当前没有重名；真有重名时下面的
    "扫到的条数"断言会先把它暴露成红，而不是静默取一个）。
    """
    tables: dict[str, tuple[str, tuple[str, ...]]] = {}
    problems: list[str] = []
    for path in sorted(_TESTS.rglob("*.py")):
        if path.name == _SELF:
            continue
        try:
            with warnings.catch_warnings():
                # 只取 AST：被扫文件里的非法转义（`\/`、`\`` 一类）会发 DeprecationWarning，
                # 那不是本判据要管的事，别把它灌进跑测输出。
                warnings.simplefilter("ignore", DeprecationWarning)
                tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            problems.append(
                f"{path.name}：读不出/解析不了（{type(exc).__name__}）"
                "⇒ 它里面的期望串本次没查成（不是'对得上'）")
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            strings = _strings_of(value)
            if not strings:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    tables[target.id] = (path.name, tuple(strings))
    return tables, problems


@lru_cache(maxsize=1)
def product_texts() -> dict[str, str]:
    """套件基线档（Lean 开着，见 `tests/conftest.py`）下每个角色的渲染提示词。"""
    reg = build_registry().registry
    return {role: AP.system_prompt(role, registry=reg)
            for role in (*S.ROLES, S.CONDUCTOR_ROLE)}


def _found_in(want: str, *, prefix: bool = False) -> list[str]:
    """这条期望在哪几个角色的渲染里逐字成立（空 = 一处都没有 ⇒ 单边不一致）。"""
    def ok(line: str) -> bool:
        return line.startswith(want) if prefix else line == want
    return [role for role, text in product_texts().items()
            if any(ok(line) for line in text.splitlines())]


def _verbatim_wants() -> list[tuple[str, str]]:
    """`VERBATIM` 族的每一条期望 ⇒ `[(名字, 期望串)]`（同名去重，保序）。"""
    tables, _ = module_tables()
    out: list[tuple[str, str]] = []
    for name, (_, strings) in tables.items():
        if not _VERBATIM_NAME.search(name):
            continue
        for want in strings:
            if (name, want) not in out:
                out.append((name, want))
    return out


def test_every_verbatim_expectation_is_verbatim_in_the_product() -> None:
    """判据：`VERBATIM` 族的每一条期望串，都是产品侧渲染里的一整行（逐字）。"""
    tables, problems = module_tables()
    assert problems == [], "有文件没查成：\n  " + "\n  ".join(problems)
    wants = _verbatim_wants()
    assert wants, (
        "tests/ 里一条 `VERBATIM` 族期望串都没扫到 ⇒ 这条判据失去对象"
        "（'没有对象'不是'都对得上'）")
    assert len(product_texts()) >= len(S.ROLES), sorted(product_texts())
    bad = [(name, want) for name, want in wants if not _found_in(want)]
    assert bad == [], (
        f"{len(bad)} 条逐字期望在产品侧找不到整行原文（期望与产品单边不一致）：\n  "
        + "\n  ".join(f"{name}: {want[:80]!r}" for name, want in bad)
        + "\n处置只有两种：把期望恢复成产品侧原文（不许反过来改产品去将就期望），"
        "或走产品文案的裁定流程之后两边一起改。")


def test_the_ruler_turns_red_on_one_changed_character() -> None:
    """反真空：期望的最后一个字被改掉 ⇒ 同一把尺子必须报出来。

    否则"都对得上"可能只是这把尺子从来不会红 —— 与"这条链是通的"在读数上一样。
    """
    wants = _verbatim_wants()
    assert wants, "没有对象可测 ⇒ 反真空本身是空转"
    name, want = wants[0]
    assert _found_in(want), f"{name} 本身就不在产品侧 ⇒ 这条反真空没有对象"
    mutated = want[:-1] + "！"
    assert mutated != want, "负控没改到那一个字 ⇒ 这一刀是空转"
    assert not _found_in(mutated), (
        f"改掉最后一个字之后 {name} 仍被当成逐字相等 ⇒ 这条判据读的不是'逐字'")


def test_the_allowed_line_prefixes_are_really_line_starts() -> None:
    """判据：`_ALLOWED_L_PREFIXES` 的每一格都真的是产品侧某一行的开头。"""
    tables, problems = module_tables()
    assert problems == [], "有文件没查成：\n  " + "\n  ".join(problems)
    for name in _PREFIX_TABLES:
        assert name in tables, f"{name} 不见了 ⇒ 判据 1 的那一格豁免失去对象"
        _, prefixes = tables[name]
        assert prefixes, f"{name} 里一个前缀都没读到"
        missing = [want for want in prefixes if not _found_in(want, prefix=True)]
        assert missing == [], (
            f"{name} 有 {len(missing)} 格在产品侧不是任何一行的开头"
            "（期望单边被改）：\n  " + "\n  ".join(repr(w) for w in missing))

    _, prefixes = tables[_PREFIX_TABLES[0]]
    victim = prefixes[0]
    broke = victim[: len(victim) // 2] + "！" + victim[len(victim) // 2 + 1:]
    assert broke != victim, "负控没改到那一个字 ⇒ 这一刀是空转"
    assert not _found_in(broke, prefix=True), (
        "白名单前缀改了一个字仍被当成行首 ⇒ 这条判据读的不是逐字前缀")
