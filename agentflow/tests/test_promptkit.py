"""提示词装配（`agentflow.promptkit`）：段序 / 丢空段 / complete / 变量 / 作用域遮蔽。

## 为什么这些用例必须存在

模块自己的 `selftest()` 只覆盖了四条负控（未注册变量、同层重名、两个 complete、
作用域遮蔽）。而"空段被丢掉"、"提供者返回非 str"、"变量名非法"、"order 不是 int"、
"注册了但这次没有值"、"模板组没闭合"这些路径在自检里是看不见的 —— 它们一旦被改松成
静默回退，症状是"提示词少了一段"与"提示词本来就没有那一段"在输出里长得一样
（模块 docstring 记的 P16 形态），而没有任何读数会报出来。

所以本文件的每个用例都钉住一条具体的失败路径或一条具体的顺序口径，且每条 docstring
都写明"这条口径退化了会坏成什么样"，而不是只写"这段代码能跑"。

## 与 linter 的分工

本文件不做全仓扫描（那是 `scripts/lint_rules.py` 的事），linter 也不做行为断言。
两边的判据互不重叠：这些用例只回答"装配的行为还是不是 docstring 写的那套"。
"""

from __future__ import annotations

import pytest

from agentflow.promptkit import (
    CONTEXT_HEADER,
    CONTEXT_ORDERS,
    SECTION_ORDERS,
    Context,
    PromptError,
    PromptRegistry,
    Scope,
    Section,
)


# ------------------------------------------------------------------ 段序


def test_sections_render_in_ascending_order_then_by_code_unit_name():
    """段序先按 order 升序，order 相同时按名字的 code-unit 顺序（不许用 locale）。

    退化会坏成什么：若同 order 的并列段改按 locale 或按注册顺序排，同一份注册表在
    不同机器 / 不同加载顺序下会渲染出不同的提示词，"顺序是确定的"这个前提就没
    了 —— 而提示词的差异不会有任何读数报出来，只会让模型看到两套边界。
    """
    reg = PromptRegistry()
    reg.section(Section("alpha", SECTION_ORDERS["ROLE_BOUNDARY"], "a 段"))
    reg.section(Section("Zeta", SECTION_ORDERS["ROLE_BOUNDARY"], "Z 段"))
    reg.section(Section("FIRST", SECTION_ORDERS["AGENT_IDENTITY"], "首段"))
    # code-unit 顺序里大写字母在小写字母之前：Zeta（Z=90）必须排在 alpha（a=97）之前。
    assert reg.assemble().names == ("FIRST", "Zeta", "alpha")
    assert reg.render() == "首段\n\nZ 段\n\na 段"


# ------------------------------------------------------------------ 空段


def test_empty_section_disappears_and_survivors_join_with_blank_line():
    """空段（静态空串或提供者返回空串）整段消失，存活段之间用一个空行连接。

    退化会坏成什么：若空段被当成"空着占位"参与连接，输出里会多出前导/尾随/连续空行。
    那时"某个模式不适用这一条"与"这一条渲染成了空白"在文本里就分不开了，
    而下游拿到的是一份看起来正常、其实多了一段空白的提示词。
    """
    reg = PromptRegistry()
    reg.section(Section("OPENING", 0, "第一段"))
    reg.section(Section("EMPTY_STATIC", 10, ""))
    reg.section(Section("EMPTY_PROVIDER", 20, lambda _scope: ""))
    reg.section(Section("CLOSING", 30, "第二段"))
    out = reg.render()
    assert out == "第一段\n\n第二段"
    assert "\n\n\n" not in out
    assert not out.startswith("\n") and not out.endswith("\n")


# ------------------------------------------------------------------ complete


def test_complete_section_is_the_whole_prompt_and_hides_others():
    """complete 段的渲染结果就是整个提示词，其他段的文本一个字符都不许出现。

    退化会坏成什么：若 complete 只被当成"排在最后的段"，普通段会与它一起拼进结果。
    那时"这一段是完整契约"与"这一段是补充说明"混在一起，而调用方以为自己拿到的
    是一份逐字受控的提示词 —— 多出来的普通段没有任何地方会被发现。
    """
    reg = PromptRegistry()
    reg.section(Section("ORDINARY", 0, "不该出现的普通段文本"))
    reg.section(Section("FULL", 100, "整份提示词", complete=True))
    out = reg.render()
    assert out == "整份提示词"
    assert "不该出现的普通段文本" not in out


def test_two_effective_complete_sections_raise():
    """同一次装配里有不只一个生效的 complete 段 ⇒ 抛 PromptError。

    "生效"是关键：全局一条 + 某个角色的作用域一条，对这个角色就是两条。
    退化会坏成什么：若静默取其中一条，另一份完整契约会被丢掉而没有任何读数 ——
    两次注册里必然有一份是错的配置，而它会以"其中一个静默胜出"收场。
    """
    reg = PromptRegistry()
    reg.section(Section("GLOBAL_FULL", 0, "全局完整提示词", complete=True))
    reg.section(Section("D_FULL", 0, "D 的完整提示词", complete=True), scope="D")
    with pytest.raises(PromptError) as excinfo:
        reg.assemble(Scope(role="D"))
    message = str(excinfo.value)
    assert "complete" in message
    assert "GLOBAL_FULL" in message and "D_FULL" in message
    # 对没有那条作用域段的角色只生效一条，装配照常（说明抛的是"多于一个"而不是"有 complete"）
    assert reg.render(Scope(role="E")) == "全局完整提示词"


# ------------------------------------------------------------------ 变量：失败路径


def test_unregistered_variable_raises_with_name_and_registered_list():
    """引用未注册的 {{variable}} ⇒ 抛，且消息点名该变量并列出已注册的那些。

    退化会坏成什么：若未注册变量被静默留空或原样留下，提示词里会带着 {{missing}}
    这种字面量发给模型，或者少一段而没人知道。列出已注册的名单是给人看的那一半：
    没有它，读的人分不出"名字打错了"与"忘了注册"。
    """
    reg = PromptRegistry(variables={"who": "D", "task": "证明命题"})
    reg.section(Section("IDENTITY", 0, "你是 {{who}}：{{missing_one}}"))
    with pytest.raises(PromptError) as excinfo:
        reg.render()
    message = str(excinfo.value)
    assert "missing_one" in message
    assert "task" in message and "who" in message


def test_registered_variable_without_value_raises():
    """注册了、但这次没有值（空串或 None）的变量被引用 ⇒ 抛，不静默留空。

    退化会坏成什么：注册住了但值为空，与"忘了注册"是两件事；若这里回退成空白，
    "这一条这次不适用"与"提供者坏了、这次给不出值"会渲染成同一份文本，
    而坏掉的那一条再也不会被任何人发现。
    """
    bad_providers = (
        ("blank", ""),
        ("empty", lambda _scope: ""),
        ("none", lambda _scope: None),
    )
    for name, provider in bad_providers:
        reg = PromptRegistry(variables={name: provider})
        reg.section(Section("USES", 0, "值：" + "{{" + name + "}}"))
        with pytest.raises(PromptError) as excinfo:
            reg.render()
        assert name in str(excinfo.value)


def test_malformed_group_raises():
    """没有闭合的模板组（例如 {{oops）⇒ 抛，且消息指向出错的那一段。

    退化会坏成什么：若没闭合的花括号被原样输出，提示词里会留下半截模板，
    而模型看到的是"作者本来想插一个变量"这种无法回验的残迹；
    这也正是"没有转义语法"的设计里唯一必须靠判据挡住的一类写法。
    """
    reg = PromptRegistry(variables={"oops": "值"})
    reg.section(Section("BROKEN", 0, "前言 {{oops"))
    with pytest.raises(PromptError) as excinfo:
        reg.render()
    message = str(excinfo.value)
    assert "没有闭合" in message
    assert "BROKEN" in message


@pytest.mark.parametrize("bad_name", ["Bad-Name", "1x"])
def test_invalid_variable_name_raises(bad_name: str):
    """非法变量名（大写/连字符/数字开头等）⇒ 抛，不当作"未知变量"放过。

    退化会坏成什么：若非法名字被当成普通未注册变量或被跳过，注册表的命名口径
    就形同虚设 —— 那时 {{Bad-Name}} 与 {{bad_name}} 会指向两处，而两份注册各自
    都"能跑"，于是同一个事实有了两个键（本项目记过的判重键形态）。
    """
    reg = PromptRegistry(variables={bad_name: "值"})
    reg.section(Section("USES", 0, "值：{{" + bad_name + "}}"))
    with pytest.raises(PromptError) as excinfo:
        reg.render()
    message = str(excinfo.value)
    assert bad_name in message
    assert "非法" in message


def test_section_provider_returning_non_str_raises():
    """段提供者返回非 str（例如 None）⇒ 抛，且消息点名是哪一个段。

    退化会坏成什么：非字符串在拼装时会被折成 None 这种字面量而混进提示词 ——
    一个写坏的提供者于是变成一段看起来"就是这几个字"的正文，
    而错的源头（那个函数）在报告的任何一个读数里都不会出现。
    """
    reg = PromptRegistry()
    reg.section(Section("BAD_PROVIDER", 0, lambda _scope: None))
    with pytest.raises(PromptError) as excinfo:
        reg.render()
    message = str(excinfo.value)
    assert "BAD_PROVIDER" in message
    assert "NoneType" in message


@pytest.mark.parametrize("bad_order", [0.5, True, "5"])
def test_non_int_order_raises(bad_order):
    """非 int 的 order（0.5 / True / "5"）在注册那一刻就抛，不等装配。

    退化会坏成什么：布尔是 int 的子类、字符串与浮点也不是排序不了 —— 若放行，
    段序会落到"按类型混排"或"比较到一半抛 TypeError"上，两者都不是可复核的顺序。
    在注册期抛是刻意的：坏配置不该有机会活到渲染那一刻。
    """
    reg = PromptRegistry()
    with pytest.raises(PromptError) as excinfo:
        reg.section(Section("ORDER", bad_order, "文本"))
    assert "必须是 int" in str(excinfo.value)


# ------------------------------------------------------------------ 作用域：遮蔽


def test_scoped_section_shadows_global_for_that_role_only():
    """同名作用域段只对那个角色遮蔽全局段，其他角色仍然拿到全局段。

    退化会坏成什么：若遮蔽是全局生效（或作用域段被合并进全局层），一个角色专用的
    边界或政策会污染所有角色的提示词 —— 而每个角色各自渲染出来都"像一份正常提示词"，
    越权那句话就藏在这里面，没有任何读数会指出来。
    """
    reg = PromptRegistry()
    reg.section(Section("ROLE_BOUNDARY", SECTION_ORDERS["ROLE_BOUNDARY"], "全局边界"))
    reg.section(Section("SHARED", SECTION_ORDERS["AGENT_IDENTITY"], "全局共享段"))
    reg.section(Section("ROLE_BOUNDARY", SECTION_ORDERS["ROLE_BOUNDARY"], "D 的边界"),
                scope="D")
    assert reg.render(Scope(role="D")) == "全局共享段\n\nD 的边界"
    assert reg.render(Scope(role="E")) == "全局共享段\n\n全局边界"


def test_scoped_variable_shadows_global_for_that_role():
    """同名作用域变量只对那个角色遮蔽全局变量，且提供者按当前作用域求值。

    退化会坏成什么：两个角色共用一份提示词模板时，某一个角色的身份/任务事实会
    泄漏进另一个角色的渲染结果；而两边都是合法文本，谁也不会报错。
    """
    reg = PromptRegistry(variables={"who": "全局角色"})
    reg.variable("who", lambda scope: "作用域-" + scope.role, scope="D")
    reg.section(Section("IDENTITY", 0, "你是 {{who}}"))
    assert reg.render(Scope(role="D")) == "你是 作用域-D"
    assert reg.render(Scope(role="E")) == "你是 全局角色"


def test_scope_facts_override_registered_variable_for_that_render_only():
    """Scope(role=..., facts={...}) 里的事实覆盖同名注册变量，且只影响这一次渲染。

    退化会坏成什么：若这次调用的事实写回注册层（或被忽略），同一次会话里后续
    渲染会拿到上一次的临时事实 —— 那是"这一次的任务"变成"上一个任务"的形态，
    而提示词里的任务说明与当前调用对不上，没有任何读数会报出来。
    """
    reg = PromptRegistry(variables={"who": "全局值"})
    reg.section(Section("IDENTITY", 0, "你是 {{who}}"))
    assert reg.render(Scope(role="D", facts={"who": "本次事实"})) == "你是 本次事实"
    assert reg.render(Scope(role="D")) == "你是 全局值"


# ------------------------------------------------------------------ 注册期的重名


def test_duplicate_name_in_same_layer_raises():
    """同一层里重名 ⇒ 注册即抛：段重名与变量重名，全局层与作用域层都算。

    退化会坏成什么：同层"后注册者静默胜出"时，两个模块各自注册的段或变量会按
    导入顺序决出胜负 —— 换句话说，提示词的内容取决于 import 顺序，
    而配置错误会以一个"看起来正常"的胜者收场（想覆盖全局的正确做法是注册到作用域）。
    """
    reg = PromptRegistry()
    reg.section(Section("DUP", 0, "第一份"))
    with pytest.raises(PromptError) as excinfo:
        reg.section(Section("DUP", 1, "第二份"))
    assert "已经有段" in str(excinfo.value)
    # 作用域层是另一层：注册到作用域是允许的（遮蔽），但作用域层内部同样不许重名。
    reg.section(Section("DUP", 0, "作用域第一份"), scope="D")
    with pytest.raises(PromptError) as excinfo:
        reg.section(Section("DUP", 1, "作用域第二份"), scope="D")
    assert "已经有段" in str(excinfo.value)

    variables = PromptRegistry()
    variables.variable("who", "全局值")
    with pytest.raises(PromptError) as excinfo:
        variables.variable("who", "另一个全局值")
    assert "已经有变量" in str(excinfo.value)
    variables.variable("who", "D 的值", scope="D")
    with pytest.raises(PromptError) as excinfo:
        variables.variable("who", "D 的另一个值", scope="D")
    assert "已经有变量" in str(excinfo.value)


# ------------------------------------------------------------------ 装配成品


def test_assembly_names_and_unregistered_scope_role_still_render_globals():
    """Assembly.names 是规范化顺序的段名，角色没有作用域注册时照常渲染全局段。

    退化会坏成什么：若 names 改报"非空段"或注册顺序，它就是一份对不上的读数 ——
    读者会拿它去核对"哪几段生效了"，而它给出的答案与真正渲染的那份不同；
    若没有作用域注册的角色直接抛，那所有只用全局段的角色都会在运行期炸掉。
    """
    reg = PromptRegistry()
    reg.section(Section("SECOND", SECTION_ORDERS["ROLE_POLICY"], "第二段"))
    reg.section(Section("BLANK", SECTION_ORDERS["ROLE_BOUNDARY"], ""))
    reg.section(Section("FIRST", SECTION_ORDERS["AGENT_IDENTITY"], "第一段"))
    assembly = reg.assemble(Scope(role="NOBODY"))
    # names 报的是装配出来的段序（空段也在里面），而渲染把它丢掉：两者刻意不同。
    assert assembly.names == ("FIRST", "BLANK", "SECOND")
    assert assembly.render() == "第一段\n\n第二段"
    assert reg.render(Scope(role="NOBODY")) == reg.render("")


# ------------------------------------------------------------------ 动态上下文


def test_contexts_render_in_order_behind_the_supersede_header():
    """动态上下文按 order 升序（同 order 按名字）排，前面加一句 supersede 头。

    退化会坏成什么：快照是追加进会话的，没有那个头，模型会把先后两份快照当成
    两条并列事实（"当时的沙箱政策"与"现在的沙箱政策"各算一条），于是旧政策会一直
    参与判断；若顺序改按注册顺序，同一份注册表在两台机器上会渲染出两种快照。
    """
    reg = PromptRegistry(variables={"root": "D:/x"})
    reg.context(Context("APPROVAL_POLICY", CONTEXT_ORDERS["APPROVAL_POLICY"], "审批：问。"))
    reg.context(Context("SANDBOX_POLICY", CONTEXT_ORDERS["SANDBOX_POLICY"], "沙箱根：{{root}}"))
    reg.context(Context("DELEGATION", CONTEXT_ORDERS["DELEGATION"], "委派：有界。"))
    assembly = reg.assemble(Scope(role="M"))
    assert assembly.context_names == ("SANDBOX_POLICY", "APPROVAL_POLICY", "DELEGATION")
    snap = assembly.render_context_snapshot()
    assert snap.startswith(CONTEXT_HEADER)
    assert snap.index("沙箱根：D:/x") < snap.index("审批：问。") < snap.index("委派：有界。")
    # 上下文不进 system 提示词：两者是两类东西。
    assert assembly.render() == ""


def test_contexts_shadow_globally_but_suppression_is_all_or_nothing():
    """上下文与段同一条遮蔽规矩；抑制是全有全无（没有按提供者的过滤）。

    退化会坏成什么：若抑制变成"逐条过滤"，"这份快照为什么是空的"就同时有两个可能
    （没人注册 / 被过滤掉了），而读数上分不开 —— 三态纪律要的是"被抑制"是一个能被
    点名的状态（本用例钉住 contexts_suppressed 与 contexts 同时可读）。
    """
    reg = PromptRegistry()
    reg.context(Context("SANDBOX_POLICY", 110, "全局沙箱"))
    reg.context(Context("SANDBOX_POLICY", 110, "A 的沙箱"), scope="A")
    assert reg.assemble(Scope(role="A")).context_names == ("SANDBOX_POLICY",)
    assert "A 的沙箱" in reg.assemble(Scope(role="A")).render_context_snapshot()
    assert "全局沙箱" in reg.assemble(Scope(role="B")).render_context_snapshot()

    reg.suppress_runtime_context(scope="A")
    a = reg.assemble(Scope(role="A"))
    assert a.contexts == () and a.contexts_suppressed is True
    assert a.render_context_snapshot() == ""
    # 只对 A 抑制：B 那一份照旧（抑制也是按作用域的）。
    b = reg.assemble(Scope(role="B"))
    assert b.contexts_suppressed is False and b.render_context_snapshot()


def test_empty_contexts_disappear_and_a_context_variable_must_be_registered():
    """空上下文与"这次没有"同义（丢掉）；上下文里引用未注册变量 ⇒ 装配即抛。

    退化会坏成什么：若空上下文留在快照里，头还在、正文空着，模型读到的是"环境事实是
    空的"而不是"没有这条消息"；若上下文的变量解析被放宽成静默留空，快照就会带着
    `{{missing}}` 字面量发给模型（模块 docstring 记的 P16 形态）。
    """
    reg = PromptRegistry(variables={"ok": "有"})
    reg.context(Context("GONE", 110, lambda sc: ""))
    reg.context(Context("HERE", 115, "在：{{ok}}"))
    assert reg.assemble().context_names == ("HERE",)

    bad = PromptRegistry()
    bad.context(Context("HERE", 115, "在：{{missing}}"))
    with pytest.raises(PromptError) as exc:
        bad.assemble()
    assert "missing" in str(exc.value)
    assert "上下文" in str(exc.value)


def test_two_contexts_with_the_same_name_in_one_layer_raise():
    """同一层里同名上下文 ⇒ 注册即抛（与段同一条规矩）。

    退化会坏成什么：同层覆盖会让"这条环境事实是谁给的"取决于注册顺序；而顺序是插件
    加载的副产品，不是声明 —— 于是同一份配置在两台机器上可能报出不同的沙箱政策。
    """
    reg = PromptRegistry()
    reg.context(Context("SANDBOX_POLICY", 110, "第一条"))
    with pytest.raises(PromptError):
        reg.context(Context("SANDBOX_POLICY", 115, "第二条"))
    # 作用域里同名是可以的（那正是遮蔽）。
    reg.context(Context("SANDBOX_POLICY", 110, "角色这一条"), scope="C")
    assert "角色这一条" in reg.assemble(Scope(role="C")).render_context_snapshot()


# ------------------------------------------------------------------ 反真空


def test_non_empty_registry_renders_non_empty_without_leftover_braces():
    """反真空：有非空段的注册表必须渲染出非空文本，且结果里不留任何未解析的花括号。

    为什么这条必须与上面那些负控同时存在（P16 形态）：上面一半用例断言的都是"抛"。
    若某个改动让渲染整体返回空串或直接短路，那些用例全部会因为"抛了别的异常"或
    "输出为空"而看起来仍然通过 —— 本用例把"装配确实产出了东西"钉住，
    于是"全都抛"与"真的装配了"在测试结果里分得开。
    """
    reg = PromptRegistry(variables={"who": "D", "task": "证明群论命题"})
    reg.section(Section("AGENT_IDENTITY", SECTION_ORDERS["AGENT_IDENTITY"], "你是 {{who}}。"))
    reg.section(Section("TASK_FRAME", SECTION_ORDERS["TASK_FRAME"], "任务：{{task}}"))
    out = reg.render(Scope(role="D"))
    assert out.strip()
    assert "{{" not in out and "}}" not in out
    assert "你是 D。" in out
    assert "任务：证明群论命题" in out
