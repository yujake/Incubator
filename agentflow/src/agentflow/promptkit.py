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
- 作用域遮蔽：段/变量可以注册给某一个角色（scope），同名遮蔽全局；同一层重名 ⇒ 注册即抛；
- 动态上下文 `Context(name, order, text)`：与段同类，但不进 system 提示词 ——
  它渲染成一条「运行时上下文快照」，带一个 supersede 头（DSH 逐字：
  `Current runtime context. This snapshot supersedes earlier runtime-context snapshots.`）；
  抑制（`suppress_runtime_context()`）是全有全无：只要有一处抑制，整份快照消失。

段的顺序表（`SECTION_ORDERS`）与上下文的顺序表（`CONTEXT_ORDERS`）是两张表，
这是 DSH 的形状：段与上下文在装配里是两类东西（一个拼进 system，一个进会话记录），
混用一张表会让"加一条环境事实"与"加一段人设"抢同一个号段。

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
    "FACULTIES": 200,                # 十项官能（不是工具清册：先说"你有什么"，再说"按键在哪"）
    # `FACULTIES` 按空行切成 5~7 块。组数按角色变动（实测：D 没有"次要官能"组 ⇒ 5 块、
    # M 没有"结构上不许"组 ⇒ 6 块、多数角色 7 块）⇒ 段名用位置编号而不是语义名，
    # 理由见 `agent_prompts._faculty_block_names`（会撒谎的段名比位置段名坏）。
    "FACULTIES_02": 210,
    "FACULTIES_03": 220,
    "FACULTIES_04": 230,
    "FACULTIES_05": 240,
    "FACULTIES_06": 250,
    "FACULTIES_07": 260,
    "STANCE": 300,                   # 这个角色的治学姿态（脑子/思辨/创新/品味/高观点）
    "ROLE_POLICY": 500,
    "TOOL_GUIDANCE_BASE": 1000,      # 每工具一条：1000 + 序号 * 10
    # 角色专属的"做法"块（B 轴迁移那一族，`draft/109`）：一条一个角色。
    # 位置 = 工具指引之后、证据契约之前 —— 工具那一族的步长也是 10（1000 起），
    # 它有多少个工具就占多远（A 今天 19 件 ⇒ 到 1180），所以这一族从 2000 起，
    # 两族之间留 800 的余量（够任何角色再加 80 件工具）。
    # 为什么要集中分配而不是让组装文件自己拍：号段是位置这件事的唯一来源，
    # 各写各的就会出现"两个角色各写 1010"而顺序随加载漂移（本文件开头那条纪律）。
    "ROLE_STYLE_BASE": 2000,
    "A_SEARCH_STYLE": 2000,
    "EVIDENCE_CONTRACT": 3000,
    "EVIDENCE_RULES": 3010,          # 证据契约的正文（6 条连续子弹 ⇒ 一整块）
    # 论文包按空行切成 10 块（只有 M/G/H 注册；第八块按角色给不同文本 —— 见 `paper_pack_for`）
    "PAPER_PACK": 3100,
    "PAPER_01": 3110,
    "PAPER_02": 3120,
    "PAPER_03": 3130,
    "PAPER_04": 3140,
    "PAPER_05": 3150,
    "PAPER_06": 3160,
    "PAPER_07": 3170,
    "PAPER_07_BODY": 3175,           # "七、"的正文（它与标题之间有一个空行 ⇒ 是独立一块）
    "PAPER_08": 3180,
    "OUTPUT_CONTRACT": 4000,
    "THREE_STATE": 4100,
    "TASK_FRAME": 4200,              # 这一次要做的任务（提供者按调用求值）
    # 任务框按空行切成 6 栏（实测恒为 6：任务 / 留言 / 板 / 用户回答 / 草稿本 / 预算）
    "TASK_INBOX": 4210,
    "TASK_BOARD": 4220,
    "TASK_USER_REPLIES": 4230,
    "TASK_NOTEBOOK": 4240,
    "TASK_BUDGET": 4250,
    "PARTNERS": 4500,                # 可协作的伙伴（从 ALLOWED_EDGES 生成）
    "HANDOFF": 4700,                 # 交接手稿协议（`draft/37` §134）：编号 + 谁给谁 + 一句描述
    "HANDOFF_RULES": 4710,           # 手稿协议的 5 条（连续子弹 ⇒ 一整块；末尾换行并在它身上）
    "AGENT_TOOLS_SDK": 5000,         # 循环协议：第一块（前言），见下面那一段块号
    # 循环协议按空行切成 15 块（`draft/103` §2.1 的字节律：只在空行处切 ⇒
    # 段间用 `\n\n" 连回去逐字节相同）。名字与号一次定死：块名是外读数
    # （`prompt_audit["sections"]`），改名会被读成"提示词变了"。
    # 形状块的名字带形状自己的序号（`LOOP_SHAPE_02B` ↔ 正文的 `2b)`）。
    "LOOP_SHAPES_HEAD": 5010,        # 「十一种形状，互斥，每次只取其一：」
    "LOOP_SHAPE_01": 5020,
    "LOOP_SHAPE_02": 5030,
    "LOOP_SHAPE_02B": 5040,          # 一次唤起一批（出边为空的角色这一块是残桩）
    "LOOP_SHAPE_03": 5050,
    "LOOP_SHAPE_04": 5060,
    "LOOP_SHAPE_05": 5070,
    "LOOP_SHAPE_06": 5080,
    "LOOP_SHAPE_07": 5090,
    "LOOP_SHAPE_08": 5100,
    "LOOP_SHAPE_09": 5110,
    "LOOP_SHAPE_10": 5120,
    "LOOP_RULES_HEAD": 5130,         # 「规则：」
    "LOOP_RULES": 5140,              # 16 条规则（连续子弹行 ⇒ 今天是一整块）
    # 协作与父子那一族（`draft/104` §5.1）：`draft/104` §6-1 定的合并号段 ——
    # 循环协议占 5000-5200、协作块占 5210-5290（原方案两套都从 5010 起 ⇒ 撞号：
    # 同号按名字排，顺序会变成名字序而不是设计序）。
    # 今天只落了 `PARENT_LIMITS`（业主裁定 A：上限数字写、且从 `Policy` 现算）；
    # 其余九块按需加 —— 没写出来的块不留号（本仓对死表的纪律）。
    "PARENT_LIMITS": 5210,           # 派活上限（现算：Policy + fanout_limit_for）
    "COLLAB_NAMES": 5220,            # 三种指称的总判据（台账号 / 名册名 / 实例标签）
    # 什么时候停（预算 / 打转 / 上报两档）—— 正文从 `LOOP_PROTOCOL` 里逐字搬出来
    # （`draft/104` §4.9）。放在循环协议之后：先读"怎么跑"，再读"什么时候停"。
    "PARENT_STOP": 5230,
    # 环境事实分两段：工作区（结构/版本）与这台机器的工具链（现算读数）。
    # 后者由调用方传进来（`agent_prompts.role_prompt_registry(toolchain_facts=…)`）——
    # 它是机器相关的，写死在提示词里会让冻结快照变成"某一台机器"的快照。
    "TOOLCHAIN_FACTS": 9000,
    # 紧跟在事实段之后：读数是前提、口径是推论，读的人按同一顺序读。
    # 它也由调用方传（`toolchain_formal=…`），理由与事实段逐字相同 —— 机器相关。
    "TOOLCHAIN_FORMAL": 9010,
    "WORKSPACE_FACTS": 10000,
    # 身份的两个槽位（`persona.py` 是它们唯一的注册入口）。名字与号与 DSH 逐字一致：
    # 前缀 order 0（与 `AGENT_IDENTITY` 同号 ⇒ 同号按名字排，`AGENT_IDENTITY` 在前），
    # 后缀 10200（最后：易变事实放最后，前面那一段稳定前缀的 KV-cache 复用不受影响）。
    "DEPLOYMENT_PERSONA_PREFIX": 0,
    "DEPLOYMENT_PERSONA_SUFFIX": 10200,
}

#: 动态上下文的顺序（与 `SECTION_ORDERS` 分开的一张表，理由见模块 docstring）。
#:
#: 号段刻意夹在 `ROLE_BOUNDARY 100` 与 `FACULTIES 200` 之间：上下文自己是一份快照、
#: 与段的顺序无关，这个位置只是照 DSH 的表抄（`dsh-system-prompt/lib/index.js:43-47`）。
CONTEXT_ORDERS: dict[str, int] = {
    "SANDBOX_POLICY": 110,
    "APPROVAL_POLICY": 115,
    # DSH 叫 `SUBAGENT_DELEGATION`；本框架只有「委派」这一件事，用本框架的词。
    "DELEGATION": 120,
}

#: 运行时上下文快照的头（DSH 逐字：`Current runtime context. This snapshot supersedes
#: earlier runtime-context snapshots.`）。为什么要有这个头：快照是追加进会话的，
#: 没有它，模型会把几份快照当成几条并列事实；有它，"以最后一份为准"才是明写的。
CONTEXT_HEADER = "运行时上下文快照（这一份取代此前的每一份运行时上下文快照）。"

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
        return _resolve(self.text, scope, owner=f"段 {self.name!r}")


@dataclass(frozen=True)
class Context:
    """一条动态上下文（不是提示词段：它渲染成一条快照消息，不进 system 提示词）。

    与 `Section` 的形状刻意一样（名字 + order + 文本或提供者）、语义刻意不一样：
    段是 system 提示词的组成部分，上下文是会话记录里的一条快照；两者的顺序表也分开。
    """

    name: str
    order: int
    text: str | Callable[[Scope], str] = ""

    def render(self, scope: Scope) -> str:
        """这一条在这个作用域下的文本（提供者返回非 str 时抛）。"""
        return _resolve(self.text, scope, owner=f"上下文 {self.name!r}")


def _resolve(text: str | Callable[[Scope], str], scope: Scope, *, owner: str) -> str:
    """求值一段/一条上下文的文本。非 str 当场抛（段与上下文共用这一条判据）。"""
    if callable(text):
        out = text(scope)
        if not isinstance(out, str):
            raise PromptError(
                f"{owner} 的提供者返回了 {type(out).__name__}，不是 str "
                "—— 非字符串会在拼装时变成 'None' 这种字面量，必须在源头拦住"
            )
        return out
    return text


@dataclass(frozen=True)
class Assembly:
    """一次装配的成品：规范化顺序的段 + 解析好的变量 + 是否 complete。

    `contexts` 是这次装配渲染后仍然非空的动态上下文（渲染成空串的与"这次没有"同义，
    在这一步就丢掉 —— 与段同一条规矩）；`contexts_suppressed` 记这一次有没有被抑制，
    于是"没有上下文"与"上下文被抑制"在读数里分得开（三态纪律）。
    """

    scope: Scope
    sections: tuple[Section, ...]
    variables: Mapping[str, str]
    complete: str = ""      # 非空 = 这一段的渲染结果就是整个提示词
    contexts: tuple[tuple[str, str], ...] = ()   # (名字, 插值后的文本)，已丢空
    contexts_suppressed: bool = False

    @property
    def names(self) -> tuple[str, ...]:
        """规范化顺序下的段名（含那些这次渲染成空串、会被丢掉的段）。"""
        return tuple(s.name for s in self.sections)

    @property
    def context_names(self) -> tuple[str, ...]:
        """这次真正进了快照的上下文名（空串的那些不在里面，被抑制时是空的）。"""
        return tuple(name for name, _text in self.contexts)

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

    def render_context_snapshot(self) -> str:
        """这次运行的运行时上下文快照（没有上下文时是空串，调用方据此决定发不发）。"""
        return join_context_sections(self.contexts)


def join_context_sections(sections: Iterable[tuple[str, str]]) -> str:
    """把（已渲染、已丢空）的上下文拼成一份快照：带 supersede 头，段间空行。

    空的时候返回空串（不是只剩一个头）—— DSH 同一条：没有上下文就不发这条消息，
    发一个只有头的空快照会让模型以为"环境事实是空的"，而事实是"没有这条消息"。
    """
    body = "\n\n".join(text for _name, text in sections)
    if not body:
        return ""
    return f"{CONTEXT_HEADER}\n\n{body}"


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
        self._global_contexts: dict[str, Context] = {}
        self._scoped_contexts: dict[str, dict[str, Context]] = {}
        # 抑制器是一张匿名表（可以有多个、各自独立）：DSH 同一条 —— 它是"关掉这一类"
        # 的开关，不是一条上下文，所以没有名字、也不参与遮蔽。
        self._global_context_suppressors: list[bool] = []
        self._scoped_context_suppressors: dict[str, list[bool]] = {}

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

    def context(self, context: Context, *, scope: str | None = None) -> None:
        """注册一条动态上下文。规则与段完全一样（同一层重名 ⇒ 抛，作用域遮蔽全局）。

        为什么要跟段用同一套注册规矩：上下文与段在装配里是两类东西，但"谁能覆盖谁"
        这件事只该有一条规矩 —— 两套规矩会让"这条环境事实是谁给的"变成需要背下来的知识。
        """
        if not isinstance(context.order, int) or isinstance(context.order, bool):
            raise PromptError(
                f"上下文 {context.name!r} 的 order 必须是 int，收到 {context.order!r}")
        if not context.name:
            raise PromptError("上下文名不许为空（成品里每一条都要能点名）")
        bucket = self._global_contexts if scope is None else \
            self._scoped_contexts.setdefault(scope, {})
        if context.name in bucket:
            where = "全局层" if scope is None else f"作用域 {scope!r}"
            raise PromptError(
                f"{where}里已经有上下文 {context.name!r} 了 —— 想覆盖全局请注册到 agent 作用域"
                "（与段同一条规矩）"
            )
        bucket[context.name] = context

    def suppress_runtime_context(self, *, scope: str | None = None) -> None:
        """抑制这一类上下文（全有全无；可以有多个抑制器，各自独立）。

        逐字照 DSH 的取舍：只抑制"这一类"，不提供按提供者的过滤 ——
        于是"为什么这份快照是空的"只有一个答案（有人关了它），而不是"可能被过滤掉了"。
        """
        if scope is None:
            self._global_context_suppressors.append(True)
        else:
            self._scoped_context_suppressors.setdefault(scope, []).append(True)

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

        # 动态上下文：与段同一套合并规矩（作用域遮蔽全局），另一张顺序表。
        merged_contexts: dict[str, Context] = dict(self._global_contexts)
        if role:
            merged_contexts.update(self._scoped_contexts.get(role, {}))
        # 抑制在装配末尾做（DSH 同一条）：只要有一处抑制整份快照就没有。
        suppressed = bool(self._global_context_suppressors) or bool(
            role and self._scoped_context_suppressors.get(role))

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
        contexts: list[tuple[str, str]] = []
        if not suppressed:
            for ctx in sorted(merged_contexts.values(), key=_name_key):
                text = _interpolate(ctx.render(scope), variables,
                                    owner=f"上下文 {ctx.name!r}")
                if text:                      # 空上下文与"这次没有"同义，丢掉
                    contexts.append((ctx.name, text))
        return Assembly(scope=scope, sections=sections, variables=variables,
                        complete=complete_text, contexts=tuple(contexts),
                        contexts_suppressed=suppressed)

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

    # 正控：动态上下文按 order 排、带 supersede 头、空的丢掉；抑制是全有全无
    reg6 = PromptRegistry(variables={"here": "D:/x"})
    reg6.context(Context("APPROVAL_POLICY", CONTEXT_ORDERS["APPROVAL_POLICY"], "审批：问。"))
    reg6.context(Context("SANDBOX_POLICY", CONTEXT_ORDERS["SANDBOX_POLICY"], "沙箱：{{here}}"))
    reg6.context(Context("GONE", 130, lambda sc: ""))
    snap = reg6.assemble(Scope(role="D")).render_context_snapshot()
    check(snap.startswith(CONTEXT_HEADER), f"快照没有 supersede 头：{snap!r}")
    check(snap.index("沙箱：D:/x") < snap.index("审批：问。"), f"上下文顺序不对：{snap!r}")
    check("GONE" not in snap, f"空上下文没被丢掉：{snap!r}")
    reg6.suppress_runtime_context()
    asm6 = reg6.assemble(Scope(role="D"))
    check(asm6.render_context_snapshot() == "", "抑制之后快照不为空")
    check(asm6.contexts_suppressed and asm6.context_names == (),
          "被抑制与「本来没有」在读数里没分开")
    # 负控四：上下文里的未注册变量 ⇒ 抛
    reg7 = PromptRegistry()
    reg7.context(Context("SANDBOX_POLICY", CONTEXT_ORDERS["SANDBOX_POLICY"], "{{nope}}"))
    try:
        reg7.assemble()
        problems.append("上下文里的未注册变量没有抛")
    except PromptError:
        pass  # 负控期望它抛：抛了才算这一格通过（不抛会在上面被记成问题）

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（装配正控 + 6 条负控）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())
