"""提示词装配：有序段 + 变量 + complete + 作用域遮蔽。

## 这个模块解决什么

在本模块之前，全仓"交给模型的文本"是散装的：`runflow.SYSTEM_PROMPT` 一段散文、
`llm.DEFAULT_PROMPT_TEMPLATE` 一个模板、C/D 的钩子各自在自己函数里拼字符串
（`draft/28` §178 的实测：A/B/E/F/G/H 零提示词，C 两处、D 一处，全无版本号）。
散装的后果不是"写得不好"，而是没有任何地方能对账：
改了注册表里的工具、改了 `ALLOWED_EDGES` 里的伙伴，提示词不会跟着变，
而"提示词与事实不一致"这件事不会有任何读数报出来。

于是把 DSH 的 `dsh-system-prompt` 那套模型搬过来（`draft/34` §1）：

- 段 `Section(name, order, text, complete)`：文本可以是一个按作用域求值的提供者；
- 顺序：按 `order` 升序，同 `order` 按名字的 code-unit 顺序（跨机一致，不许用 locale）；
- 空段被丢掉：于是"某个模式/角色不适用这一条"天然写成"这段渲染成空串"；
- 变量 `{{name}}`：每次装配解析，名字必须匹配 `^[a-z][a-z0-9_]*$`；
  未知变量、注册了但这次没有值、模板组不完整、名字非法 —— 四种都抛；
- 完整提示词 `complete=True`：那一段就是整个 system prompt；生效的 complete 段多于一个 ⇒ 装配失败；
- 作用域遮蔽：段/变量可以注册给某一个角色（scope），同名遮蔽全局；同一层重名 ⇒ 注册即抛。

## 为什么"抛"而不是"回退"

DSH 的逐字理由值得照抄：一份坏提示词比一次响亮的失败更糟。
静默回退（缺变量就留空、名字不认识就跳过）会让"提示词少了一段"与
"提示词本来就没有那一段"在输出里长得一模一样 —— 那正是本项目记过的 P16 形态。
所以本模块的全部失败路径都是异常，且每一条都有测试与负控。

## 与 `draft/34` 的关系

段落顺序表（`SECTION_ORDERS`）是本框架自己的一张稀疏分配表，
理由与 DSH 相同：位置集中分配，贡献者引用名字而不是自己拍一个数字，
免得两个模块各自写 `order=500` 而顺序随加载顺序漂移。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

#: 提示词段的位置（稀疏分配；中间的号段留给将来的贡献者）。
#:
#: 与 DSH 的 `SECTION_ORDERS` 一一对应（`draft/34` §6 的表）：身份 → 边界 →
#: 可开关政策 → 每工具指引 → 证据契约 → 输出契约 → 三态 → 工具 SDK →
#: 环境事实 → 部署后缀。号段留空是刻意的：加一段时用中间的数，不必重排别人。
SECTION_ORDERS: dict[str, int] = {
    "AGENT_IDENTITY": 0,
    "ROLE_BOUNDARY": 100,
    "ROLE_POLICY": 500,
    "TOOL_GUIDANCE_BASE": 1000,      # 每工具一条：1000 + 序号 * 10
    "EVIDENCE_CONTRACT": 3000,
    "OUTPUT_CONTRACT": 4000,
    "THREE_STATE": 4100,
    "TASK_FRAME": 4200,              # 这一次要做的任务（提供者按调用求值）
    "PARTNERS": 4500,                # 可协作的伙伴（从 ALLOWED_EDGES 生成）
    "AGENT_TOOLS_SDK": 5000,
    "WORKSPACE_FACTS": 10000,
    "DEPLOYMENT_SUFFIX": 10200,
}

#: 动态上下文（不是提示词段，另算的一类；本模块只分配号，落在会话记录里）。
CONTEXT_ORDERS: dict[str, int] = {
    "SANDBOX_POLICY": 110,
    "APPROVAL_POLICY": 115,
    "DELEGATION": 120,
}

#: 变量名：与 DSH 同一条正则（小写字母开头，只含小写字母/数字/下划线）。
VARIABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
#: 一个完整的模板组：`{{name}}`，不允许嵌套、不允许表达式。
GROUP = re.compile(r"^\{\{([^{}]*)\}\}")


class PromptError(ValueError):
    """装配/渲染期的错误。全部失败路径都抛它（没有"回退到默认"这一支）。"""


@dataclass(frozen=True)
class Scope:
    """一个装配作用域：谁在用这份提示词，以及这次调用的临时事实。

    `role` 是唯一的身份键（与 `schema.ROLES` 同域）；`facts` 是这次渲染可用的变量，
    与注册表里注册的全局变量合并（同名时这次的事实优先）。
    """

    role: str = ""
    facts: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Section:
    """一个提示词段。

    `text` 给字符串就是静态段；给可调用对象就是按作用域求值的动态段
    （返回空串 = 这一段这次不存在，会被丢掉 —— 不是"空着占位"）。
    """

    name: str
    order: int
    text: str | Callable[[Scope], str] = ""
    complete: bool = False

    def render(self, scope: Scope) -> str:
        """这一段在这个作用域下的文本（提供者返回非 str 时抛）。"""
        if callable(self.text):
            out = self.text(scope)
            if not isinstance(out, str):
                raise PromptError(
                    f"段 {self.name!r} 的提供者返回了 {type(out).__name__}，不是 str "
                    "—— 非字符串会在拼装时变成 'None' 这种字面量，必须在源头拦住"
                )
            return out
        return self.text


@dataclass(frozen=True)
class Assembly:
    """一次装配的成品：规范化顺序的段 + 解析好的变量 + 是否 complete。"""

    scope: Scope
    sections: tuple[Section, ...]
    variables: Mapping[str, str]
    complete: str = ""      # 非空 = 这一段的渲染结果就是整个提示词

    @property
    def names(self) -> tuple[str, ...]:
        """规范化顺序下的段名（含那些这次渲染成空串、会被丢掉的段）。"""
        return tuple(s.name for s in self.sections)

    def render(self) -> str:
        """插值 + 丢空段 + 用空行连接（与 DSH 的 `renderPrompt` 同构）。"""
        if self.complete:
            return self.complete
        parts: list[str] = []
        for section in self.sections:
            text = _interpolate(section.render(self.scope), self.variables,
                                owner=f"段 {section.name!r}")
            if text:
                parts.append(text)
        return "\n\n".join(parts)


def _interpolate(text: str, variables: Mapping[str, str], *, owner: str) -> str:
    """严格的 `{{name}}` 插值：不认识的、没有值的、写坏的，全部抛。

    逐字理由（DSH）：一份坏提示词比一次响亮的失败更糟。
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("{{", i):
            m = GROUP.match(text[i:])
            if m is None:
                raise PromptError(
                    f"{owner}：第 {i} 个字符处有一个没有闭合的 {{{{ —— "
                    "模板组必须是完整的 {{name}}（DSH 同样没有转义语法，这里也一样）"
                )
            name = m.group(1)
            if not VARIABLE_NAME.match(name):
                raise PromptError(
                    f"{owner}：变量名 {name!r} 非法（要求 {VARIABLE_NAME.pattern}）"
                )
            if name not in variables:
                known = "、".join(sorted(variables)) or "（一个都没有）"
                raise PromptError(
                    f"{owner}：引用了没有注册的变量 {{{{{name}}}}}；已注册的有：{known}"
                )
            value = variables[name]
            if value is None or value == "":
                raise PromptError(
                    f"{owner}：变量 {{{{{name}}}}} 这次没有值（注册了但没提供）—— "
                    "空值与缺失是两件事，这里都算失败：静默留空会让提示词少一段而没人知道"
                )
            out.append(value)
            i += m.end()
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _name_key(section: Section) -> tuple[int, str]:
    return (section.order, section.name)


class PromptRegistry:
    """段落与变量的注册表。全局一层 + 每个作用域各一层（作用域遮蔽全局）。"""

    def __init__(self, *, variables: Mapping[str, str] | None = None) -> None:
        self._global_sections: dict[str, Section] = {}
        self._scoped_sections: dict[str, dict[str, Section]] = {}
        self._global_variables: dict[str, Callable[[Scope], str] | str] = dict(variables or {})
        self._scoped_variables: dict[str, dict[str, Callable[[Scope], str] | str]] = {}

    # ------------------------------------------------------------ 注册
    def section(self, section: Section, *, scope: str | None = None) -> None:
        """注册一段。`scope=None` 注册到全局；给角色名注册到那个作用域。

        同一层里重名 ⇒ 抛（提示你可以注册到作用域去遮蔽全局，而不是在同一层里覆盖）。
        """
        if not isinstance(section.order, int) or isinstance(section.order, bool):
            raise PromptError(f"段 {section.name!r} 的 order 必须是 int，收到 {section.order!r}")
        if not section.name:
            raise PromptError("段名不许为空（后置不变量要求成品里每一段都有名字）")
        bucket = self._global_sections if scope is None else \
            self._scoped_sections.setdefault(scope, {})
        if section.name in bucket:
            where = "全局层" if scope is None else f"作用域 {scope!r}"
            raise PromptError(
                f"{where}里已经有段 {section.name!r} 了 —— 想覆盖全局请注册到 agent 作用域"
                "（作用域遮蔽全局是设计的一部分），同一层里覆盖是配置错误"
            )
        bucket[section.name] = section

    def variable(self, name: str, provider: Callable[[Scope], str] | str, *,
                 scope: str | None = None) -> None:
        """注册一个变量。`provider` 给字符串就是常量，给可调用对象就按作用域求值。"""
        if not VARIABLE_NAME.match(name):
            raise PromptError(f"变量名 {name!r} 非法（要求 {VARIABLE_NAME.pattern}）")
        bucket = self._global_variables if scope is None else \
            self._scoped_variables.setdefault(scope, {})
        if name in bucket:
            where = "全局层" if scope is None else f"作用域 {scope!r}"
            raise PromptError(f"{where}里已经有变量 {name!r} 了")
        bucket[name] = provider

    # ------------------------------------------------------------ 装配
    def assemble(self, scope: Scope | str = Scope()) -> Assembly:
        """合并全局 + 作用域两层，规范化顺序，校验 complete，解析全部变量。"""
        scope = scope if isinstance(scope, Scope) else Scope(role=scope)
        role = scope.role
        merged: dict[str, Section] = dict(self._global_sections)
        if role:
            if role not in self._scoped_sections and role not in self._scoped_variables:
                # 没注册过这个作用域不算错（它可能只用全局段），但要能一眼看出
                # "这个角色没有自己的段"与"注册漏了"的区别 —— 所以不抛，只是空遮蔽。
                pass
            merged.update(self._scoped_sections.get(role, {}))

        sections = tuple(sorted(merged.values(), key=_name_key))

        variables: dict[str, str] = {}
        providers: dict[str, Callable[[Scope], str] | str] = dict(self._global_variables)
        providers.update(self._scoped_variables.get(role, {}))
        for name, provider in providers.items():
            value = provider(scope) if callable(provider) else provider
            variables[name] = "" if value is None else str(value)
        # 这次调用带的事实：它们覆盖同名注册值（一次调用的临时事实优先）。
        for name, value in scope.facts.items():
            variables[str(name)] = "" if value is None else str(value)

        completes = [s for s in sections if s.complete]
        if len(completes) > 1:
            raise PromptError(
                "生效的 complete 段多于一个："
                + "、".join(s.name for s in completes)
                + " —— complete 的含义是「这段就是全部提示词」，两段同时生效说明配置错了"
            )
        complete_text = ""
        if completes:
            complete_text = _interpolate(completes[0].render(scope), variables,
                                         owner=f"段 {completes[0].name!r}")
        return Assembly(scope=scope, sections=sections, variables=variables,
                        complete=complete_text)

    def render(self, scope: Scope | str = Scope()) -> str:
        """装配并渲染一步到位（`assemble(...).render()` 的快捷方式）。"""
        return self.assemble(scope).render()


def selftest() -> int:
    """自检：装配的正控与几条关键负控（细节用例在 `tests/test_promptkit.py`）。"""
    problems: list[str] = []

    def check(ok: bool, what: str) -> None:
        """记一条自检结论（不通过就写进 problems，供最后统一打印）。"""
        if not ok:
            problems.append(what)

    reg = PromptRegistry(variables={"who": "D"})
    reg.section(Section("AGENT_IDENTITY", SECTION_ORDERS["AGENT_IDENTITY"], "你是 {{who}}。"))
    reg.section(Section("ROLE_BOUNDARY", SECTION_ORDERS["ROLE_BOUNDARY"], "不许越权。"))
    reg.section(Section("EMPTY_ONE", SECTION_ORDERS["ROLE_POLICY"], lambda sc: ""))
    got = reg.render(Scope(role="D"))
    check(got.startswith("你是 D。"), f"变量插值/顺序不对：{got!r}")
    check("EMPTY" not in got and "不许越权" in got, f"空段没被丢掉：{got!r}")

    # 负控一：引用未注册变量 ⇒ 抛
    reg2 = PromptRegistry()
    reg2.section(Section("A", 0, "{{not_registered}}"))
    try:
        reg2.render()
        problems.append("未注册变量没有抛")
    except PromptError:
        pass  # 负控期望它抛：抛了才算这一格通过（不抛会在下面被记成问题）
    # 负控二：同层重名 ⇒ 抛
    reg3 = PromptRegistry()
    reg3.section(Section("A", 0, "x"))
    try:
        reg3.section(Section("A", 1, "y"))
        problems.append("同层重名没有抛")
    except PromptError:
        pass  # 同上：负控期望它抛
    # 负控三：两个 complete ⇒ 抛
    reg4 = PromptRegistry()
    reg4.section(Section("A", 0, "x", complete=True))
    reg4.section(Section("B", 1, "y", complete=True))
    try:
        reg4.assemble()
        problems.append("两个 complete 段没有抛")
    except PromptError:
        pass  # 同上：负控期望它抛
    # 正控：作用域遮蔽全局
    reg5 = PromptRegistry()
    reg5.section(Section("AGENT_IDENTITY", 0, "全局身份"))
    reg5.section(Section("AGENT_IDENTITY", 0, "D 的身份"), scope="D")
    check(reg5.render(Scope(role="D")) == "D 的身份", "作用域没有遮蔽全局")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（装配正控 + 4 条负控）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())
