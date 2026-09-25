"""工具层装配：把各工具模块按**角色**组装成一个 `ToolRegistry`。

## 为什么要按角色组装，而不是给所有智能体同一套工具

工具不只是能力，也是**权限面**。A 不该能调 `research.submit_gap`（那是 D 的决策），
B 不该能调 `search.download`（下载是 A 的职责，且它是网络副作用）。
把"谁能用什么"固化在这里，比写在提示词里可靠得多 —— 提示词可以被绕过，注册表不能。

## 为什么用签名反射而不是写死参数

各工具模块的 `register()` 需要的依赖不同（`table_tools` 要 `store`，`fs_tools` 要 `root`，
`graph_tools` 可能只要一个已建好的 `graph`）。这里按 `inspect.signature` **只传它声明要的
关键字参数**，于是模块之间可以各自演进而不用改这里 —— 少一个必须同步维护的耦合点。

模块缺失时**不报错，只记录**：这些模块是并行开发的，任何一个还没落地都不该让整个工具层不可用。
缺失项会出现在 `build_registry()` 返回的 `skipped` 里，便于诊断。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .base import (
    EFFECT,
    EXTERNAL,
    LEGACY_EFFECTS_BY_TOOL,
    LEGACY_SIDE_EFFECTS,
    SANDBOX_AVAILABLE,
    ParamError,
    ToolError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    fail,
    ok,
    tool,
)

#: 智能体角色。顺序无关，但保持稳定便于日志可比。
#:
#: A/B/C/D 是最初的文献流水线；E/F/G/H 是面向"数学研究"补上的四个角色：
#:   E —— 数值实验与形式化验证（产出**证据**，且必须标注证据等级）
#:   F —— 多轮难题攻坚（产出**过程**，且必须有三维预算与终止条件）
#:   G —— 论文撰写（产出**稿件**，每条断言必须带引用）
#:   H —— 审校（产出**发现**，且发现本身必须有证据）
#: 它们与 A–D 一样遵循"角色即权限面"：H 只读、C 只读，是为了让
#: "改稿的人"与"审稿的人"在**结构上**不能是同一个人。
#: ⚠️ **单一来源**：角色名单定义在 `schema.ROLES`，这里只是把它引过来。
#:
#: 为什么不能各写一份：`schema` 需要"role 是否合法"的判据（`Task.validate`），
#: 而 `tools` 需要"按角色过滤工具面"。两处各写一份名单，就会出现
#: "schema 认为合法的角色，工具层不认"这种**没有任何报错**的分裂 ——
#: 这正是 FC-03（跨模块字符串约定必须集中定义）要防的事。
#: `schema` 不 import `tools`（依赖方向是 tools -> schema），所以放 schema 里没有循环。
from ..schema import ROLES  # noqa: E402  (放在这里是为了让上面的说明紧贴定义)

#: **只读角色**：它们的工具面里**不允许出现任何写工具**，无论 `ToolSpec.roles` 怎么声明。
#:
#: - **C**（只读图分析）：一旦 C 能写，它就成了"绕过 B 引文回验"的写入路径，
#:   而 B 的引文逐字回验是全系统**唯一**能自动发现幻觉引文的地方。
#: - **H**（审校）：若审校者能直接改稿，它就同时是"发现者"与"修正者"，
#:   于是**"发现问题"与"掩盖问题"在结构上无法区分**。
#:
#: 实现不在这个常量本身，而在 `ToolRegistry.for_role`（结构性过滤）——
#: 常量只是这条约束的**单一来源**（FC-03）。
READ_ONLY_ROLES = ("C", "H")

#: 有写副作用的等级。与 `base.SIDE_EFFECTS` 的尾部一致；单列一份是为了让
#: `READ_ONLY_ROLES` 的判据在一个地方可读（FC-07：`side_effect` 是一等公民）。
#:
#: ⚠️ 这张表**只活到 B3**：`network` 是遗留取值（见 `base.LEGACY_SIDE_EFFECTS`
#: 与 `base.LEGACY_EFFECTS_BY_TOOL`），它在这里的作用是"迁移期行为不变"——
#: 声明了它的工具继续被只读角色剥离、继续需要审批。B3 删掉 `network` 之后，
#: 这里会只剩 `("write_local",)`，而 `external == "exec"` 的剥离判据
#: （`ToolRegistry.for_role`）成为第二道结构性过滤。
#:
#: 两处词表不能分批删：`capabilities.assert_capabilities` 第 5 条断言
#: `set(capabilities.SIDE_EFFECTS) == set(base.SIDE_EFFECTS)`，只删一处会
#: **导入期就炸**。这是好事（"删一半"不可能静默），但排期上必须知道它们是
#: 一个原子改动。
SIDE_EFFECTS_WRITE = ("write_local", "network")

#: 遗留翻译表（**声明层**的单一来源，值来自 `base`，不在这里再写一份）。
#:
#: 为什么把它们再导出到这一层：`tools.base` 是禁改区（auth-audit），
#: 而本文件同样是禁改区且是"只读角色（C/H）的权限面单一来源"。两张表
#: 决定的是"遗留取值能不能悄悄改行为"，因此与 `READ_ONLY_ROLES` /
#: `SIDE_EFFECTS_WRITE` 一样，必须在本层可读、可审。
#:
#: - `LEGACY_SIDE_EFFECTS`：`network` => `(external, effect 默认值)`；
#: - `LEGACY_EFFECTS_BY_TOOL`：逐工具的**原意**（人写；`search.download`
#:   与 `ocr.run` 声明 `network` 但实际写我们的东西）。
LEGACY_TRANSLATIONS: tuple[dict[str, tuple[str, str]], ...] = (
    LEGACY_SIDE_EFFECTS,
    LEGACY_EFFECTS_BY_TOOL,
)

#: 模块名 -> 它需要的依赖键（值从 build_registry 的 kwargs 里按名取）。
_MODULES: tuple[str, ...] = (
    "table_tools",
    "fs_tools",
    "search_tools",
    "ocr_tools",
    "graph_tools",
    "trace_tools",
    "research_tools",
    "verify_tools",
    "attack_tools",
    "doc_tools",
    "review_tools",
)


@dataclass
class RegistryBuild:
    """装配结果。`skipped` 让"某个模块没装上"变成可见的事实，而不是静默少几个工具。"""

    registry: ToolRegistry
    loaded: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.skipped

    def summary(self) -> dict:
        return {
            "tools": self.registry.names(),
            "count": len(self.registry),
            "loaded_modules": self.loaded,
            "skipped_modules": self.skipped,
            # FC-17 的接线状态：**可打印的事实**，不是"去看源码猜"。
            # `None` = 没启用；一个对象 = 已启用（其 `threshold_chars` 等值可见）。
            "context_budget": (
                None
                if getattr(self.registry, "default_budget", None) is None
                else {
                    "enabled": True,
                    "threshold_chars": getattr(self.registry.default_budget, "threshold_chars", None),
                    "head_chars": getattr(self.registry.default_budget, "head_chars", None),
                    "tail_chars": getattr(self.registry.default_budget, "tail_chars", None),
                    "max_inline_bytes": getattr(self.registry.default_budget, "max_inline_bytes", None),
                    "spill_dir": getattr(self.registry.default_budget, "spill_dir", None),
                }
            ),
        }


def _call_register(mod: Any, registry: ToolRegistry, deps: dict[str, Any]) -> int:
    """把模块的工具装进注册表。返回新增的工具数。

    容忍三种约定 —— 这些模块是并行开发的，为"用哪种入口"去返工不值得，
    但**必须只有这三条路**，否则就成了"随便怎么写都能装上"的糊涂账：
      1. `register(registry, **deps)`   —— 首选
      2. `install(registry, ...)`        —— 等价别名
      3. 模块级 `ALL_TOOLS: list[ToolSpec]`  —— 纯声明式
    """
    before = len(registry)

    fn = getattr(mod, "register", None) or getattr(mod, "install", None)
    if fn is not None:
        sig = inspect.signature(fn)
        kwargs = {}
        for pname, p in sig.parameters.items():
            if pname == "registry":
                continue
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            if pname in deps:
                kwargs[pname] = deps[pname]
            elif p.default is inspect.Parameter.empty:
                # 模块要求一个我们没提供的依赖 —— 明确报出来，而不是传 None 让它后面炸
                raise ToolError(f"{mod.__name__}.{fn.__name__}() 需要依赖 {pname!r}，但装配时未提供")
        fn(registry, **kwargs)
        return len(registry) - before

    specs = getattr(mod, "ALL_TOOLS", None)
    if specs:
        for s in specs:
            if isinstance(s, ToolSpec):
                registry.register(s)
            else:
                raise ToolError(f"{mod.__name__}.ALL_TOOLS 里含非 ToolSpec 元素：{type(s).__name__}")
        return len(registry) - before

    raise ToolError(f"{mod.__name__} 既没有 register()/install()，也没有 ALL_TOOLS")


def untranslated_legacy_tools(registry: ToolRegistry) -> list[str]:
    """注册表里"声明了遗留取值 `network` 却没登记原意"的工具名（已排序）。

    这是一条**独立函数**而不是 `build_registry` 里的一段内联判据，理由与
    `capabilities.audit_task_ledger` 相同：判据要能被单独测（"新加的遗留工具
    会不会被抓住"必须有一个可红可绿的用例，而不是靠读代码相信它）。
    """
    return sorted(
        s.name for s in registry._specs.values()
        if s.side_effect == "network" and s.name not in LEGACY_EFFECTS_BY_TOOL
    )


def build_registry(
    *,
    store: Any = None,
    workspace_root: str | Path | None = None,
    graph: Any = None,
    roles: Iterable[str] = ROLES,
    name: str = "agentflow",
    strict: bool = False,
    context_budget: Any = None,
    config: Any = None,
) -> RegistryBuild:
    """组装工具层。

    参数
    ----
    store : Store | None
        数据表工具必需；为 None 时相关模块会被跳过（并记录原因）。
    workspace_root : Path | None
        文件工具的工作区根（沙箱边界）。为 None 时用 `<store.root>`。
    graph : RelationGraph | None
        C 的图对象；为 None 时 `graph_tools` 的只读查询类工具仍可注册（它们可自行构建）。
    strict : bool
        为 True 时，任何模块跳过都抛异常 —— 供验收脚本使用，防止"少了一半工具还以为装好了"。
    """
    reg = ToolRegistry(name=name)

    # ---- FC-17：把上下文预算装到注册表上（装配期决定，而不是靠每个调用点记得传）
    #
    # `config` 给整份配置时，从它的 `context_budget` 块取；**没有该块 ⇒ 不启用**
    # （三态：没配 ≠ 用默认值，见 `contextbudget.load_budget`）。
    # 显式传 `context_budget=` 优先于 `config=`。
    if context_budget is None and config is not None:
        from ..contextbudget import load_budget

        context_budget = load_budget(config)
    if context_budget is not None:
        # 装配期就把类型错了的关掉 —— 否则它会一路活到第一次 `call()` 才炸，
        # 而那时错误信息里已经没有"是装配时配错的"这个线索了。
        try:
            context_budget.validate()
        except AttributeError as e:
            raise ToolError(
                f"context_budget 必须是一个 ContextBudget 对象（收到 {type(context_budget).__name__}）：{e}"
            ) from None
    reg.default_budget = context_budget
    root = Path(workspace_root) if workspace_root else (Path(store.root) if store is not None else None)
    # spill 要有地方落：默认落在工作区根下的 `spill/`。没有这一句，
    # `default_budget` 生效时剪枝后的内容想落盘却没有 root（spill 那一件套走不到）。
    # ⚠️ 必须放在 `root` 算出来**之后** —— 先写的版本把它放在 `root = ...` 之前，
    # 于是 `UnboundLocalError`。好在那是**装配期**就暴露的失败，不是潜伏到某次调用。
    reg.default_spill_root = root
    deps: dict[str, Any] = {
        "store": store,
        "root": root,
        "workspace_root": root,
        "graph": graph,
        "roles": tuple(roles),
    }

    loaded: list[str] = []
    skipped: list[dict] = []
    for mod_name in _MODULES:
        try:
            mod = __import__(f"{__name__}.{mod_name}", fromlist=[mod_name])
        except Exception as e:  # noqa: BLE001
            skipped.append({"module": mod_name, "stage": "import", "error": f"{type(e).__name__}: {e}"})
            continue
        try:
            added = _call_register(mod, reg, deps)
        except Exception as e:  # noqa: BLE001
            skipped.append({"module": mod_name, "stage": "register", "error": f"{type(e).__name__}: {e}"})
            continue
        if added == 0:
            # register() 跑通了但一个工具都没加 —— 这几乎总是 bug（比如 roles 不匹配被全过滤）
            skipped.append({"module": mod_name, "stage": "register", "error": "register() 未注册任何工具"})
        else:
            loaded.append(mod_name)

    # ⚠️ 断言所有工具声明的角色都在 ROLES 里。
    #
    # 为什么必须有这一句：`roles` 是**跨模块的字符串约定**。曾经 `research_tools` 写的是
    # `roles=("agent-D",)` 而全项目其余地方按 `"D"` 过滤 —— 结果是
    # `build_for_role('D')` 静默少 5 个工具，**没有任何地方报错**，直到测试才被抓到。
    # 这类"字符串拼法不同导致静默失配"的 bug，唯一的通用解法就是**在校验点上炸出来**。
    bad_roles: dict[str, list[str]] = {}
    for spec in reg._specs.values():
        unknown = [r for r in spec.roles if r not in ROLES]
        if unknown:
            bad_roles[spec.name] = unknown
    if bad_roles:
        msg = (
            f"以下工具声明了不在 ROLES{ROLES} 里的角色：{bad_roles}。"
            "角色名是跨模块约定，拼法不一致会让 build_for_role() 静默漏掉这些工具。"
        )
        if strict:
            raise ToolError(msg)
        skipped.append({"module": "<roles>", "stage": "validate", "error": msg})

    # ⚠️ 遗留取值必须被**显式**翻译（P-13 §3.2：不许静默重新解释）。
    #
    # `side_effect="network"` 的逐工具原意（它到底写不写我们的东西）写在
    # `base.LEGACY_EFFECTS_BY_TOOL` 里。新加一个声明了 `network` 的工具却忘了登记原意时，
    # `ToolSpec.effect` 会退回翻译表的默认值 —— 而那个默认值恰好是 `network` 这个取值
    # **字面上说过的话**（"不改我们的东西"），于是"写盘的事实被丢掉"会重演，
    # 且没有任何地方报错。所以这里把它变成装配期可见的事实。
    #
    # 与上面的 roles 检查同一种形态：默认记进 `skipped`（可见、不阻塞），
    # `strict=True` 时直接抛。
    legacy_untranslated = untranslated_legacy_tools(reg)
    if legacy_untranslated:
        msg = (
            f"以下工具声明了遗留取值 side_effect='network'，但 LEGACY_EFFECTS_BY_TOOL 里"
            f"没有它们的原意：{legacy_untranslated}。遗留取值必须被**显式**翻译"
            "（`effect` 会退回默认值，于是'它其实会写我们的东西'这个事实被丢掉）。"
            "请在 base.LEGACY_EFFECTS_BY_TOOL 里逐条登记 (external, effect)。"
        )
        if strict:
            raise ToolError(msg)
        skipped.append({"module": "<legacy>", "stage": "validate", "error": msg})

    if strict and skipped:
        raise ToolError(f"严格模式下不允许模块被跳过：{skipped}")
    return RegistryBuild(registry=reg, loaded=loaded, skipped=skipped)


def build_for_role(role: str, **kwargs: Any) -> RegistryBuild:
    """只装某个角色的工具子集。"""
    build = build_registry(**kwargs)
    filtered = ToolRegistry(name=f"{kwargs.get('name', 'agentflow')}:{role}")
    for spec in build.registry.for_role(role):
        filtered.register(spec)
    return RegistryBuild(registry=filtered, loaded=build.loaded, skipped=build.skipped)


__all__ = [
    "ROLES",
    "READ_ONLY_ROLES",
    "SIDE_EFFECTS_WRITE",
    "LEGACY_TRANSLATIONS",
    "untranslated_legacy_tools",
    "RegistryBuild",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "ParamError",
    "build_for_role",
    "build_registry",
    "fail",
    "ok",
    "tool",
]
