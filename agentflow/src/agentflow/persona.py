"""身份文本的唯一入口（`dsh-persona` 的端口）。

## 这个模块解决什么

身份文本此前没有"唯一来源"：谁都能往 `AGENT_IDENTITY`（order 0）这个段名上注册，
而"部署那一份身份"与"某个角色的身份"用的是同一个段名 —— 于是"谁盖住了谁"取决于
注册顺序，而注册顺序是插件加载的副产品。本模块把 DSH 的答案搬过来：

- 身份占两个具名槽位（不是"某一段"）：`deployment:persona-prefix`（order 0，前缀）
  与 `deployment:persona-suffix`（order 10200，后缀）；
- 部署那一份由 `register_deployment_persona()` 无条件注册（哪怕文本是空串）；
- 一个角色的身份靠同名遮蔽：把同一对槽位注册到那个角色自己的作用域里；
- 于是"这个角色的身份是谁写的"永远只有一个答案 —— 它作用域里那一份，或者部署那一份。

## 为什么 persona 行只能挂在作用域上（DSH 逐字）

`dsh-persona/lib/index.js:8-15`：

    This row is scope-only. Mounted inside an agent preset it shadows the deployment
    persona for that one session ... mounted globally it collides with the registry's
    own registration and fails loud.

    That constraint is the reason the row exists. An agent preset cannot mount the
    prompt registry itself, so without a row of its own a preset could change an
    agent's tools but never its identity.

本模块把这条搬成两条结构：`apply_persona()` 的 `scope` 是必填关键字（签名层就拦掉
"挂全局"这个用法），而 `register_deployment_persona()` 是唯一能写全局槽位的入口。

## 两个开关（`dsh-persona/lib/index.js:23-28` 的四格）

- `complete=True`：这一段就是整份 system prompt（前缀槽位带上这个标记）。
  逐字：`minimal` 预设的整份提示词就是一句 persona 前缀 + 三个工具 description。
- `include_runtime_context=False`：抑制全部动态上下文（快照一条都不发）。

## 与 DSH 的一处偏差（刻意）

DSH 的 `SystemPrompt` 构造器还会注册一段 `harness:identity`（order -1000，文本是
"你是由 DeepSeek Harness 驱动的 AI 代理"这一类框架自述），由 `includeHarnessIdentity`
（默认 true）控制。本框架今天那句"你在一套多智能体协同框架里工作"写在
`agent_prompts.AGENT_IDENTITY` 的正文里，所以这里把开关默认取 False（不写第二句）。
要改成 DSH 的形状（框架自述与角色身份分开成两段）时，把它打开即可 —— 参数已经在这里了。
"""
from __future__ import annotations

from dataclasses import dataclass

from .promptkit import PromptError, PromptRegistry, Section

#: 身份前缀槽位的段名（DSH 同名，逐字：`dsh-system-prompt/lib/index.js:54`）。
#:
#: 为什么名字带 `deployment:` 前缀而不是叫 `AGENT_IDENTITY`：槽位是部署面的东西，
#: 一个角色遮蔽它是靠"注册同一个名字"，名字本身就是那条契约。改动它等于改动
#: "谁能盖住谁"，所以这个名字与 DSH 逐字一致、由本模块唯一导出。
PERSONA_PREFIX_SECTION = "deployment:persona-prefix"

#: 身份后缀槽位的段名（DSH 同名，`dsh-system-prompt/lib/index.js:56`）。
#: 放在 order 10200（最后）：易变事实（工作目录、这一次的会话范围）越靠后，
#: 前面那一段稳定前缀的 KV-cache 复用越不受影响。
PERSONA_SUFFIX_SECTION = "deployment:persona-suffix"

#: DSH 的框架自述段名与 order（本框架默认不注册，见模块 docstring 的偏差一节）。
HARNESS_IDENTITY_SECTION = "harness:identity"
HARNESS_IDENTITY_ORDER = -1000


class PersonaError(PromptError):
    """persona 挂错地方（挂全局）时抛。它继承 `PromptError`：调用方按装配错误处理即可。"""


@dataclass(frozen=True)
class Persona:
    """一份 persona（`dsh-persona/lib/index.js:23-28` 的四格逐字对应）。

    `prefix` 必填（DSH 的 schema 是 `z.string().required()`）：一份身份至少要有一句话 ——
    允许"空身份"等于允许"这个角色没有身份"，而那样一来遮蔽就成了静默失联。
    """

    prefix: str
    suffix: str = ""
    complete: bool = False
    include_runtime_context: bool = True


def apply_persona(reg: PromptRegistry, persona: Persona, *, scope: str) -> None:
    """把一份 persona 注册到某个角色作用域（同名遮蔽部署那一份）。

    `scope` 必填：这是 DSH 那条"scope-only"规则的结构形态（见模块 docstring）。
    它同时挡住两种坏用法：挂到全局（与部署那一份撞名）与"忘了给作用域"
    （那会让某个角色的身份盖住所有人）。
    """
    if not scope:
        raise PersonaError(
            "persona 只能挂在某个角色的作用域上（`scope` 不许为空）。"
            "挂到全局会与部署那一份撞名 —— 而'某个角色的身份盖住所有人'这句话本身"
            "就是错的：身份是 per-agent 的东西。DSH 逐字：mounted globally it collides "
            "with the registry's own registration and fails loud."
        )
    reg.section(Section(PERSONA_PREFIX_SECTION, _order("DEPLOYMENT_PERSONA_PREFIX"),
                        persona.prefix, complete=persona.complete), scope=scope)
    reg.section(Section(PERSONA_SUFFIX_SECTION, _order("DEPLOYMENT_PERSONA_SUFFIX"),
                        persona.suffix), scope=scope)
    if not persona.include_runtime_context:
        reg.suppress_runtime_context(scope=scope)


def register_deployment_persona(reg: PromptRegistry, *,
                                prefix: str = "", suffix: str = "",
                                include_runtime_context: bool = True,
                                harness_identity: str = "") -> None:
    """注册部署那一份 persona（全局层，无条件注册，文本可以是空串）。

    为什么"无条件注册、允许空串"是必须的：它是遮蔽的靶子。若部署这一份只在非空时才
    注册，那么"角色没写身份"与"部署没写身份"在装配里就是同一件事，而遮蔽的语义
    （同名覆盖）会在某些配置下退化成"新增一段"。DSH 的构造器就是这么做的
    （`dsh-system-prompt/lib/index.js:218-228`）：两段永远在，文本来自 config。

    `harness_identity` 给非空文本时才注册框架自述那一段（默认不注册，见模块 docstring）。
    """
    reg.section(Section(PERSONA_PREFIX_SECTION, _order("DEPLOYMENT_PERSONA_PREFIX"),
                        prefix))
    reg.section(Section(PERSONA_SUFFIX_SECTION, _order("DEPLOYMENT_PERSONA_SUFFIX"),
                        suffix))
    if not include_runtime_context:
        reg.suppress_runtime_context()
    if harness_identity:
        reg.section(Section(HARNESS_IDENTITY_SECTION, HARNESS_IDENTITY_ORDER,
                            harness_identity))


def _order(name: str) -> int:
    """从 `promptkit.SECTION_ORDERS` 取号（集中分配，贡献者不自己拍数字）。"""
    from .promptkit import SECTION_ORDERS

    return SECTION_ORDERS[name]


def selftest() -> int:
    """自检：遮蔽、scope-only、两个开关、部署那一份的无条件注册。"""
    from .promptkit import Scope

    problems: list[str] = []

    def check(ok: bool, what: str) -> None:
        if not ok:
            problems.append(what)

    # 正控：角色那一份遮蔽部署那一份（同名），后缀跟着换。
    reg = PromptRegistry()
    register_deployment_persona(reg, prefix="部署身份", suffix="部署后缀")
    apply_persona(reg, Persona(prefix="A 的身份", suffix="A 的后缀"), scope="A")
    got = reg.render(Scope(role="A"))
    check(got.startswith("部署身份") or got.startswith("A 的身份"), f"顺序不对：{got!r}")
    check("A 的身份" in got and "部署身份" not in got, f"没遮蔽：{got!r}")
    check(got.rstrip().endswith("A 的后缀"), f"后缀没跟着换：{got!r}")
    check("部署后缀" not in got, f"部署后缀还在：{got!r}")
    # 另一个角色拿到部署那一份（遮蔽是按作用域的）。
    other = reg.render(Scope(role="B"))
    check("部署身份" in other and "A 的身份" not in other, f"遮蔽漏到别的角色：{other!r}")

    # 负控一：不给作用域 ⇒ 抛（scope-only 的结构形态）
    try:
        apply_persona(reg, Persona(prefix="x"), scope="")
        problems.append("scope 为空时没有抛")
    except PersonaError:
        pass  # 期望它抛

    # 正控：include_runtime_context=False ⇒ 快照全灭（全有全无）
    reg2 = PromptRegistry()
    from .promptkit import Context, CONTEXT_ORDERS

    reg2.context(Context("SANDBOX_POLICY", CONTEXT_ORDERS["SANDBOX_POLICY"], "沙箱：无。"))
    apply_persona(reg2, Persona(prefix="A", include_runtime_context=False), scope="A")
    asm = reg2.assemble(Scope(role="A"))
    check(asm.render_context_snapshot() == "" and asm.contexts_suppressed,
          "include_runtime_context=False 没有压掉快照")

    # 正控：complete=True ⇒ 那一段就是整份提示词
    reg3 = PromptRegistry()
    reg3.section(Section("AGENT_IDENTITY", 0, "别的身份"))
    apply_persona(reg3, Persona(prefix="只有这一句", complete=True), scope="A")
    check(reg3.render(Scope(role="A")) == "只有这一句", f"complete 没生效：{reg3.render(Scope(role='A'))!r}")

    # 正控：部署那一份无条件在（文本空 ⇒ 段被丢，但槽位已注册 ⇒ 名字在 names 里）
    reg4 = PromptRegistry()
    register_deployment_persona(reg4)
    check(PERSONA_PREFIX_SECTION in reg4.assemble().names,
          "部署 persona 的空槽位没有注册（遮蔽就没有靶子了）")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（persona 正控 5 条 + 负控 1 条）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())
