"""A 不能"造概念 / 提猜想"—— 这条闸是**结构性的**，不是靠它自觉。

业主的口径（"提示词管想让它这么做，判据管不许它不这么做"）反过来也成立：
**已经结构上做不到的事，提示词里那句就是多余的**，可以删。但删之前必须先把
"结构上做不到"这件事**钉成判据** —— 否则哪天有人给 A 开一条写 `statements`
的路，删掉的那句提示词没人会替它报警。

## 这一条守的是什么

`specs/a.py::ACTIONS` 里只有检索/登记文献那一族动作（`run_once` / `run` /
`search_literature` / `walk_citations` / `ingest_local` / `shelf_search`），
**没有** `register_statement` / `register_conjecture`，写面也只有
`literature` / `search_requests`。所以 A 想"造概念/提猜想"**调不到、也写不进**。

## 判据（每条都带负控）

① 动作面：A 的动作名里不许出现任何"写 statements/conjectures"的动作（**现读**，不抄清单）；
② 写面：`capabilities.WRITE_SETS["A"]` 不许含 `statements` / `conjectures` / `dependencies`；
③ 负控：临时往 A 的 `ACTIONS` 里塞一个 `register_statement` ⇒ ①② 必须红（证明判据读的是真身）；
④ 反真空：A 至少还有一个动作（别把"动作面空了"当成通过）。
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from agentflow import capabilities as CAP
from agentflow import specs
from agentflow.specs import a as spec_a


#: 这些动作名里的词根说明"它在写命题台账"（`register_statement` / `register_conjecture`
#: / 将来可能出现的 `submit_statement` 之类）。**按词根判、不写死完整清单** ——
#: 写死清单的判据在下一个类似动作出现时不会红（这正是"同一件事两份实现"的老病）。
_FORBIDDEN_ROOTS = ("statement", "conjecture")


def _action_names() -> list[str]:
    """现读 A 的动作名 —— 从 `specs.builtin_specs()` 读（`capabilities` 派生动作表的那个入口）。

    ⚠️ 刻意**不读**模块级 `spec_a.ACTIONS`：那两者今天同源（`SPEC.actions` 在 import
    那一刻绑成 `ACTIONS`），但只有前者是"权限面真正被读出来的那一路"
    （`specs/__init__.py:31` 现取 `mod.SPEC` ⇒ `capabilities.CAPABILITIES`）。
    读模块级常量的话，哪天 `SPEC.actions` 换成别的来源，这条判据会安静地守着一份旧清单。
    """
    return [str(getattr(a, "action", "")) for a in (specs.builtin_specs()["A"].actions or ())]


def _problems(action_names: list[str], write_set: Any) -> list[str]:
    """判据本体：返回问题清单（空 = 绿）。两半（动作面 / 写面）各判各的。"""
    out: list[str] = []
    bad = sorted({n for n in action_names if any(r in n for r in _FORBIDDEN_ROOTS)})
    if bad:
        out.append(f"A 的动作面出现了「写命题台账」的动作：{bad}（A 只能把材料搬进来，不是替它们下定义的人）")
    writes = {str(x) for x in (write_set or ())}
    leaked = sorted(writes & {"statements", "conjectures", "dependencies"})
    if leaked:
        out.append(f"A 的写面漏进了 {leaked}（它只能写 literature / search_requests）")
    if not action_names:
        out.append("A 的动作面是空的 —— 那是「什么都没配」，不是「不许造概念」")
    return out


def test_a_has_no_action_that_writes_statements() -> None:
    """① 动作面：现读 `specs/a.py::ACTIONS`，不许有写命题台账的动作。"""
    problems = _problems(_action_names(), CAP.WRITE_SETS.get("A"))
    assert not problems, "；".join(problems)


def test_a_write_set_does_not_reach_the_statement_tables() -> None:
    """② 写面：只许 literature / search_requests（声明面这一半单独判，便于定位）。"""
    writes = {str(x) for x in (CAP.WRITE_SETS.get("A") or ())}
    assert "statements" not in writes, f"A 的写面含 statements：{sorted(writes)}"
    assert "conjectures" not in writes, f"A 的写面含 conjectures：{sorted(writes)}"
    assert "dependencies" not in writes, f"A 的写面含 dependencies：{sorted(writes)}"
    # 反真空：它确实有写面（否则"没有 statements"是废话）
    assert writes, "A 的写面是空的 —— 那说明这一条判据没有对象"
    assert writes == {"literature", "search_requests"}, (
        f"A 的写面变过：{sorted(writes)}（今天是 literature / search_requests 两张）")


def test_the_negative_control_an_injected_statement_action_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """③ 负控：塞一个 `register_statement` 进 A 的动作面 ⇒ ① 必须红。

    这是"判据读的是真身"的证据：如果这条判据只是在抄一份名字清单，
    塞进去的那个动作不会让它红。
    """
    # 负控必须给 `handler_name`：`ActionSpec.__post_init__` 会拒一个"没有实现落点"的动作
    # （那条自己的判据是 `agentspec.py` 的 `没有 handler_name` 分支）。这里刻意指向一个
    # **真实存在**的落库代理，这样负控考的是"动作面被改了"，不是"构造不出来"。
    injected = spec_a.ActionSpec(
        role="A", action="register_statement", summary="（负控：假装 A 能写命题台账）",
        params={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        returns="Statement", handler_name="B.register_statement",
    )
    # ⚠️ 必须改 `SPEC`，不能只改模块级 `ACTIONS`：`builtin_specs()` 现取 `mod.SPEC`，
    # 而 `SPEC.actions` 在 import 那一刻就被绑成当时那个元组 —— 只 monkeypatch `ACTIONS`
    # 的话 ① 读到的东西**一个字都不变**，负控会假绿通过（"负控没打在真身上"的形态）。
    patched = dataclasses.replace(
        spec_a.SPEC, actions=tuple(spec_a.SPEC.actions or ()) + (injected,))
    monkeypatch.setattr(spec_a, "SPEC", patched, raising=True)
    monkeypatch.setattr(spec_a, "ACTIONS", patched.actions, raising=True)

    names = _action_names()
    assert "register_statement" in names, (
        f"负控没打到真身上：`builtin_specs()` 读到的动作里没有注入的那一条（{names}）")
    problems = _problems(names, CAP.WRITE_SETS.get("A"))
    assert problems, "负控失败：塞了一个 register_statement 进去，判据仍然绿 ⇒ 它读的不是真身"
    assert "register_statement" in " ".join(problems)

    # 写面那一半的负控：临时把它塞进写集
    poisoned = dict(CAP.WRITE_SETS)
    poisoned["A"] = tuple(poisoned.get("A") or ()) + ("statements",)
    monkeypatch.setitem(CAP.WRITE_SETS, "A", poisoned["A"])
    assert _problems([], poisoned["A"]), "负控失败：写面加了 statements，判据仍然绿"


def test_the_generic_write_path_refuses_conjectures_from_a() -> None:
    """①b 通用写入通道：`table.create` 写 `conjectures` 必须被拒（2026-10-21 补的那一格）。

    ## 为什么单列一条

    2026-10-21 实机取证（临时库）：`table.create(role="A", table="conjectures", …)` 当时
    **成功落成 `c-000000`** —— 也就是说"A 不造概念、不提猜想"这句原先只被 `statements`
    那一格守着，**猜想那条路是开的**。`store.STATEMENT_WRITE_TABLES` 补进 `conjectures`
    之后这条路才真的关上；这条判据守的就是那一格（它自己在 `store.py`，属 FC-27 人审面）。
    """
    from agentflow import store as ST

    for name in ("statements", "dependencies"):
        why = ST.direct_write_refusal(name)
        assert why, f"通用写入通道没有拒绝 {name} —— A 可以绕过「不造概念」直接写它"
        assert "direct_write_refused" in why

    # 反真空：A 自己的那两张表**必须**是能写的（否则"都被拒"是废话）
    for name in ("literature", "search_requests"):
        assert ST.direct_write_refusal(name) == "", f"{name} 被误拦了：A 的正当写入路径被关上"

    # **已知缺口（读数，不是断言它"好"）**：`conjectures` 目前**不在**那张名单里 ——
    # `direct_write_refusal` 是**按表**判、不认识角色，所以把 `conjectures` 塞进去会把 D 的
    # 正当写入路径（`tests/test_conjectures.py` 的既有设计声明）一起关掉。要真正关上
    # "A 用 `table.create` 写 conjectures" 这条路，需要一个**角色感知**的闸
    # （`table_tools` 拿 `capabilities.WRITE_SETS[role]` 判，或给 `direct_write_refusal` 加 role 形参），
    # 那属 FC-27 `auth-audit` 面。这一格就是那个缺口的机器读数。
    assert ST.direct_write_refusal("conjectures") == "", (
        "缺口被补上了（角色感知闸已落地）—— 请把这条断言改成「必须拒」，并把 A 的提示词那一句再收紧")


def test_the_same_structural_check_reads_the_builtin_specs() -> None:
    """④ 反真空：A 在 `specs.builtin_specs()` 里真的存在，且动作面非空。

    否则上面两条会在"根本没构造出 A"的情形下通过（判据没有对象）。
    """
    built = specs.builtin_specs()
    assert "A" in built, "specs.builtin_specs() 里没有 A"
    # 判据与被判的对象同源：读的就是 `specs/a.py::SPEC` 那个对象，不是一份拷贝
    assert built["A"] is spec_a.SPEC, (
        "builtin_specs()['A'] 不是 specs/a.py::SPEC —— 判据读的与声明的不是同一个对象")
    names = _action_names()
    assert names, "A 的动作面是空的"
    assert "run_once" in names, f"A 的动作面里没有 run_once：{names}"
    assert CAP.WRITE_SETS.get("A"), "A 的写面是空的"
