# -*- coding: utf-8 -*-
"""`agentflow.persona`：身份的两个槽位、遮蔽、scope-only、两个开关。

## 为什么这些用例必须存在

`draft/101` §3 记下了 DSH 那一条：persona 是只在作用域里能挂的行，
"挂到全局会与注册表自己那一份撞名"。本框架此前没有这条结构 —— 谁都能往
`AGENT_IDENTITY`（order 0）上注册，于是"这个角色的身份是谁写的"取决于注册顺序。
这些用例把三件事钉住：

1. 遮蔽真的发生（角色那一份盖住部署那一份，且只盖住那个角色）；
2. `scope` 为空时抛（而不是静默挂到全局去盖住所有人）——
   这一条是本模块存在的理由本身；
3. 部署那一份无条件在（文本空也在）：它是遮蔽的靶子，缺了它，
   "角色没写身份"与"部署没写身份"在装配里就是同一件事。

每条 docstring 都写"退化会坏成什么"，而不是"这段代码能跑"。
"""
from __future__ import annotations

import pytest

from agentflow import persona as P
from agentflow.promptkit import (
    CONTEXT_ORDERS,
    Context,
    PromptError,
    PromptRegistry,
    Scope,
    Section,
)


def _persona_prompt(reg: PromptRegistry, role: str) -> str:
    """只取身份那两段渲染出来的文本（与其它的段解耦，免得被别的段影响判据）。"""
    assembly = reg.assemble(Scope(role=role))
    return "\n\n".join(
        text for name, text in
        ((s.name, s.render(assembly.scope)) for s in assembly.sections)
        if name in (P.PERSONA_PREFIX_SECTION, P.PERSONA_SUFFIX_SECTION) and text)


def test_a_role_persona_shadows_the_deployment_persona_for_that_role_only():
    """角色那一份盖住部署那一份，且只盖住它自己（别的角色照旧拿部署那一份）。

    退化会坏成什么：若遮蔽改成"追加"，两个角色的提示词里会同时出现两句身份
    （"你是 A" 与 "你是部署默认"），模型读到的是一份自相矛盾的身份；若作用域合并写错，
    一个角色换身份会把所有人的身份一起换掉 —— 而这两件事都不会有任何读数报出来。
    """
    reg = PromptRegistry()
    P.register_deployment_persona(reg, prefix="部署身份", suffix="部署后缀")
    P.apply_persona(reg, P.Persona(prefix="A 的身份", suffix="A 的后缀"), scope="A")

    a = _persona_prompt(reg, "A")
    assert a == "A 的身份\n\nA 的后缀", a
    b = _persona_prompt(reg, "B")
    assert b == "部署身份\n\n部署后缀", b


def test_applying_a_persona_without_a_scope_raises_instead_of_taking_over_globally():
    """`scope` 为空 ⇒ 抛（不许"顺手挂到全局"）。

    退化会坏成什么：挂到全局就是"用某个角色的身份盖住所有人"。它不会报错，
    只会在所有人身上生效 —— 而身份的错法是最难从行为上发现的那一类
    （每个角色都"照着一份身份在做"，只是那一份不是它的）。
    """
    reg = PromptRegistry()
    P.register_deployment_persona(reg, prefix="部署身份")
    with pytest.raises(P.PersonaError) as exc:
        P.apply_persona(reg, P.Persona(prefix="谁的都行"), scope="")
    # 消息里必须带理由（DSH 逐字的依据），否则读者只知道"错了"、不知道"为什么只能这样"。
    assert "collides" in str(exc.value)
    assert "部署身份" in _persona_prompt(reg, "A")


def test_the_deployment_persona_slots_exist_even_when_their_text_is_empty():
    """部署那一份无条件注册：文本空 ⇒ 段渲染成空串被丢掉，但槽位名字仍在 `names` 里。

    退化会坏成什么：若空文本就不注册，遮蔽的靶子没了 —— 一个角色挂上自己的身份时
    会变成"新增一段"而不是"覆盖一段"，于是部署那一份（非空时）继续渲染，
    两句话同时进提示词。
    """
    reg = PromptRegistry()
    P.register_deployment_persona(reg)
    names = reg.assemble(Scope(role="A")).names
    assert P.PERSONA_PREFIX_SECTION in names
    assert P.PERSONA_SUFFIX_SECTION in names
    assert reg.render(Scope(role="A")) == "", "空 persona 不该贡献任何文本"

    # 靶子在 ⇒ 遮蔽是覆盖；靶子不在 ⇒ 追加（这条负控把两者的读数分开）。
    P.apply_persona(reg, P.Persona(prefix="只有角色这一句"), scope="A")
    assert reg.render(Scope(role="A")) == "只有角色这一句"


def test_the_two_persona_switches_work(): 
    """`complete=True` 那一段就是整份提示词；`include_runtime_context=False` 压掉全部快照。

    退化会坏成什么：`complete` 的语义是"这段就是全部"（DSH 的 `minimal` 预设整份提示词
    就是一句 persona）—— 若它退化成普通段，极简模式会悄悄带上几十段；若抑制开关失效，
    声明"不注入运行时上下文"的角色仍然会收到环境快照，而它与提示词正文的口径会打架。
    """
    reg = PromptRegistry()
    P.register_deployment_persona(reg, prefix="部署身份")
    P.apply_persona(reg, P.Persona(prefix="只有这一句", complete=True), scope="M")
    assert reg.render(Scope(role="M")) == "只有这一句"

    reg2 = PromptRegistry()
    reg2.context(Context("SANDBOX_POLICY", CONTEXT_ORDERS["SANDBOX_POLICY"], "沙箱：无。"))
    P.apply_persona(reg2, P.Persona(prefix="A", include_runtime_context=False), scope="A")
    asm = reg2.assemble(Scope(role="A"))
    assert asm.contexts == () and asm.contexts_suppressed is True
    assert reg2.assemble(Scope(role="B")).render_context_snapshot(), \
        "只对 A 抑制，B 的快照不该跟着消失"
    # 抑制挡不住"本来就没有"这条读数：三态里「被抑制」是一个能点名的状态。
    plain = PromptRegistry()
    P.apply_persona(plain, P.Persona(prefix="B"), scope="B")
    assert plain.assemble(Scope(role="B")).contexts_suppressed is False


def test_the_harness_identity_slot_is_optional_and_ordered_before_the_persona():
    """框架自述那一段是可选的（默认不注册）；注册了要排在身份之前（order -1000）。

    退化会坏成什么：本框架今天那句"你在一套多智能体协同框架里工作"写在
    `agent_prompts.AGENT_IDENTITY` 里 ⇒ 若这里默认注册，同一件事会说两遍；
    若注册了却排在身份之后，模型先读到"你是谁"再读到"你在什么之上"，
    而 DSH 的顺序是反的（框架 → 部署 persona → 工具与政策）。
    """
    reg = PromptRegistry()
    P.register_deployment_persona(reg)          # 默认不注册 harness:identity
    assert P.HARNESS_IDENTITY_SECTION not in reg.assemble().names

    reg2 = PromptRegistry()
    P.register_deployment_persona(reg2, prefix="身份", harness_identity="框架自述")
    txt = reg2.render()
    assert txt.index("框架自述") < txt.index("身份"), txt
    assert P.HARNESS_IDENTITY_ORDER < P._order("DEPLOYMENT_PERSONA_PREFIX")


def test_persona_errors_are_prompt_errors_so_callers_keep_one_except_clause():
    """`PersonaError` 继承 `PromptError`：装配期的调用方只处理一种异常。

    退化会坏成什么：若它是一个独立异常根，那么"装配失败 ⇒ 这一趟不许发提示词"这条
    处置会在 persona 这一路漏掉，而漏掉的形态是"用半份提示词继续跑"。
    """
    assert issubclass(P.PersonaError, PromptError)
    reg = PromptRegistry()
    with pytest.raises(PromptError):
        P.apply_persona(reg, P.Persona(prefix="x"), scope="")
    # 同一层里挂两次 ⇒ 仍是装配期的重名错误（不是静默覆盖）。
    P.apply_persona(reg, P.Persona(prefix="x"), scope="A")
    with pytest.raises(PromptError):
        P.apply_persona(reg, P.Persona(prefix="y"), scope="A")
    assert P.PERSONA_PREFIX_SECTION == "deployment:persona-prefix"
    assert P._order("DEPLOYMENT_PERSONA_SUFFIX") == 10200
    # 名字与那两格必须在 `SECTION_ORDERS` 里（集中分配；贡献者不许自己拍数字）。
    assert P._order("DEPLOYMENT_PERSONA_PREFIX") == 0
    assert isinstance(Section("x", 0, "y"), Section)
