"""工具层基座：ToolSpec / ToolResult / ToolRegistry / 参数校验。

## 为什么要有一层"工具"

原来 A/B 直接调 `store`、`providers` 的函数。一旦智能体由 LLM 驱动，这就不够了：
- LLM 需要"手写 JSON 去改表" → 一次转义错误就写坏数据，而且每改一行都占一轮思维链；
- 没有统一输入校验 → 参数错了要到深处才炸；
- 没有统一的副作用声明 → 无法判断某个动作要不要审批；
- 同一套能力在"脚本模式"和"LLM 模式"下要写两遍。

工具层把"标准操作"固化成有名字、有 schema、有校验、有结构化返回、声明副作用的原子动作。
智能体的思维链只花在"判断该调哪个工具"，不花在"怎么把参数拼对"。

## 两个刻意的设计

1. 两根轴都是一等公民。`none` / `read` 的工具可以任意调用、不需要审批；
   `write_local` 的需要。把审批判断建立在声明上，而不是靠人记。
   这也是为什么 C 的图分析全部是 `read` —— 它应当能被任意组合地反复查询。

   本层还声明第二根正交轴 `external`（见 `EXTERNAL`）：`side_effect` 把
   "能不能改我们拥有的东西"与"能不能触到我们不拥有的东西"压进了同一个
   取值，于是 `verify.run_experiment`（既写实验记录、又执行调用方给的脚本）
   在一根轴上必须二选一，另一个事实被丢掉。两根轴的取值互相独立，
   审批（`needs_approval`）与沙箱（`sandbox_required`）由它们推导，
   不落成逐工具的布尔字段（`DEVELOPMENT.md` §3 纪律 6：派生态不许当输入）。
   `network` 这个把两根轴压成一档的遗留取值已在 B3 收官时从词表里删掉，
   连同两张翻译表；装配期再写它就是一个非法取值（`ValueError`），
   于是"出网"与"起进程"在树上各说各的话，不需要任何翻译层。

2. 参数校验自己实现，不引第三方依赖。只需要 object/array/string/integer/number/boolean
   与 required/enum/items/bounds 这几样；为此引入 `jsonschema` 会让"工具层能不能用"
   依赖于环境里有没有装它。工具层是所有智能体的公共底盘，它的依赖越少越好。
"""

from __future__ import annotations

import difflib
import inspect
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查；运行期不导入（避免模块级耦合）
    from pathlib import Path

    from ..contextbudget import ContextBudget

#: 副作用等级（第一根轴的历史名称，也是声明轴本身）。顺序即"危险程度"，便于比较。
#:
#: ⚠️ `network` 曾在这里，并在 B3 收官时被删掉：它是把两根正交轴压在一根轴上
#: 的产物（把"出网"与"起子进程"折叠成同一档）。它连同两张翻译表
#: （`LEGACY_SIDE_EFFECTS` / `LEGACY_EFFECTS_BY_TOOL`）与全部下游分支一起消失，
#: 于是"还剩几处遗留"这个数字降到 0 之后不再有第二个词表留在仓库里。
#: 与 `capabilities.SIDE_EFFECTS` 是同一个原子改动（见
#: `capabilities.assert_capabilities` 第 5 条：两处必须逐字相等，只删一处会导入期就炸）。
#:
#: `R4-AN-4` / 台账 `N-5`：本词表是"哪些等级算写"的另一半。只读角色 C/H 的结构性剥离
#: （`for_role` / `call` / `_callable_for` 三处共用的 `_role_surface`）读的是装配层那张
#: `SIDE_EFFECTS_WRITE`，不是下面这个元组。所以往下面加一个取值时，必须同时决定它落在
#: `SIDE_EFFECTS_WRITE`（会被剥离）还是 `_NON_WRITE_EFFECTS`（不会）：这条二分由
#: `tools/__init__.py` 的 `_check_write_levels_are_registered()` 在导入期断言，
#: 只改词表不改登记表会当场炸（判据与正控/负控读数见 `temp/FIX6-F4.md`）。
#: 判据落点刻意不在本文件：`base.py` 先于装配层的 `SIDE_EFFECTS_WRITE` 执行，
#: 它自己看不见那张表（写在这里只能是一份拿不到真值的同义判据）。
SIDE_EFFECTS = ("none", "read", "write_local")

#: 第一根轴：能不能改我们拥有的东西（数据表 / 工作区）。
EFFECT = ("none", "read", "write_local")

#: `axes-2`：上面两份字面量是同一个轴的两个名字，这里在导入期钉住它们不许分叉。
#:
#: 为什么需要这条断言（而不是靠"它们现在相等"）：`ToolSpec.__post_init__` 用
#: `SIDE_EFFECTS` 挡非法取值，而对外声明的轴值是 `EFFECT`（`capabilities` 与
#: 测试读它）。在加这条断言之前，本文件里这两个名字之间没有任何判据，
#: 相等只靠 `capabilities.assert_capabilities` 恰好也各留一份、又恰好有两条
#: 断言来传递维持 —— 第三方文件碰巧存在带来的相等是脆的，把这个文件单独拿走
#: 就没有任何东西守着它了。
#:
#: 还有一个更容易骗过人的事实：今天 `EFFECT is SIDE_EFFECTS` 为真，
#: 但那不是契约，而是同一个代码对象里两个等值常量被编译期折叠成同一个对象的
#: 巧合（实测：`EFFECT is SIDE_EFFECTS` 为 True，源码里却确实有两份字面量）。
#: 给任一份加一个取值、或换个解释器/换个写法，这个巧合就没了，
#: 而分叉不会红 —— 于是会出现"某取值通过了构造期校验、却不在对外声明的轴值里"
#: 这种要读两处源码才能看出来的分叉。断言放在模块级，两种改法
#: （只改一处、或把两份改成不同内容）都会在 import 那一刻就炸。
assert EFFECT == SIDE_EFFECTS, (
    f"base.EFFECT={EFFECT} 与 base.SIDE_EFFECTS={SIDE_EFFECTS} 不同 —— "
    "副作用是第一根轴，同一根轴的两份取值清单必须逐字相等；"
    "只改一处会让构造期校验与对外声明说的是两根不同的轴，而那是静默的"
)

#: 第二根轴：能不能触到我们不拥有的东西。
#:
#: - `none`：触不到；
#: - `egress`：出网；
#: - `exec`：在宿主上执行一个由调用方决定内容的程序。
#:
#: ## `axes-1`：取值清单**有两份字面量**，不是一份（这句话此前是错的）
#:
#: 旧docstring 逐字写着"取值清单只有这一份（FC-03）。`capabilities.py` 不再写第二份
#: 字面量，而是 import 这里" —— 实测与代码事实**相反**：`capabilities.py` 在
#: 模块层各写了一份 `SIDE_EFFECTS` / `EFFECT` / `EXTERNAL` 字面量
#: （**刻意不写行号**：那三行在本轮里就漂过一次 —— 行号会给人一个**会过期**的指引，
#: 而本仓的禁改区清单理由守的正是同一条纪律：写符号名，不写 `文件:行号`），
#: 且它自己的注释逐字写了**为什么刻意不 import**（它是更底层的声明层，
#: 要能被 `verify` 与 CLI 单独读，拖上工具层会改变依赖方向）。
#:
#: 所以准确的说法是：**两处各有一份字面量，由导入期断言钉住它们不许分叉**
#: （`capabilities.assert_capabilities` 的交叉断言；新增一根轴沿用同一种形态，
#: 而不是发明第二套机制）。**落点也必须知道有两个**：
#:
#: - 本文件（`tools/base.py`）—— 在禁改区清单里；
#: - `capabilities.py` —— **不在**清单里。
#:
#: 后者是这条登记的影响面：放宽词表这件事可以只改不受保护的那一份，
#: 而只改一处会在导入期炸、两处改法不一致则两处描述的是不同的轴。
#: （是否把 `capabilities.py` 登记进 `.noai-paths` 见 `draft/28` 的 §9.3 / `H-4` ——
#: 那是一条待人裁的决定，不是本文件能自行改的。）
EXTERNAL = ("none", "egress", "exec")

#: 六件套里"必须由 `ToolSpec.__post_init__` 校验"的那几件。
#:
#: `name` / `summary` / `params` / `side_effect` 的校验是无条件的（见
#: :meth:`ToolSpec.__post_init__`），`roles` 是结构性的（必须是元组）。
#:
#: `D6` 的实测更正：这句话此前是假的 —— `__post_init__` 里没有
#: `isinstance(self.roles, tuple)` 那道判据，实测 `ToolSpec(..., roles=['E'])`
#: 被接受。本轮把那道门补上了（见 `__post_init__` 末尾），所以这句话现在成真。
#: 它不是"多一条判据"：`tuple` 是 roles 这条声明的契约的一半（另一半
#: `role in ROLES` 由 `ToolRegistry._reject_unknown_roles` 管）。
#:
#: `returns` 是这里唯一的例外，理由必须写下来，否则下一个人会以为
#: "六件套校验"是一句空话：
#:
#: - `returns` 的非空校验会命中 `src/agentflow/agent_d.py` 里三个内置降级替身
#:   工具（`trace.relation` / `trace.concept` / `trace.literature`），而那个文件
#:   不在本轮授权的改动范围内（P-13 的分批清单里也没有它）；
#: - 于是本轮的口径是：`returns` 必须给且必须是字符串（给空字符串 = 你确认过它
#:   没有可声明的返回形态），但"别忘了写"这件事由 `DEVELOPMENT.md` §4.3 第 1 项的
#:   census 观察 —— 而 census 本来就在那条 DoD 项的判据里。
#:
#: 这是一条有代价的取舍，不是"文档说严、代码说松"：上面两条理由就是它的代价，
#: 而它换来的是"六件套的其他五件真的有门" + "本轮不越界改文件"。
#: 修掉它只需要给那三个替身补 `returns=`（一条声明，不涉行为）。
REQUIRED_NON_EMPTY_FIELDS: tuple[str, ...] = ("name", "summary", "params")

#: 沙箱可用性（三态）。`DEVELOPMENT.md` §3 纪律 1：把"没声明沙箱"与
#: "声明了沙箱正在用"折叠成同一个布尔，正是本仓库三态纪律禁止的形态。
#:
#: - `True`：沙箱已声明可用（起进程/出网由它承接）；
#: - `False`：已声明不可用（这才是"升级为人工审批"的判据）；
#: - `None`：未声明（默认）。它与 `False` 等价地保守（需要审批），
#:   但在报告里必须能分开：一个是"我们查过，没有沙箱"，一个是"我们没说过"。
#:
#: ## `axes-3`：`True` 这一档在**当前环境里不可达**（如实登记，不是"三种取值都在用"）
#:
#: 实测：全仓库对 `SANDBOX_AVAILABLE` 的出现只有四类 —— 上面这个定义（值恒为 `None`）、
#: `tools/__init__.py` 里一个从未被使用的导入、下面的读取点、以及测试里的 `monkeypatch`。
#: **没有任何配置或装配入口**（`build_registry` / CLI / config 都不接受它）。
#:
#: 后果必须写清，否则读文档的人会以为三档都活着：
#:
#: - `_role_surface` 的 `external == "exec"` 放行分支、`allowed_by_sandbox` 留痕，
#:   在生产里**永不发生**；
#: - `needs_approval` 里"沙箱可用所以 exec/egress 被承接"那一支同理恒假；
#: - 于是**任何 `external != "none"` 的工具在任何环境下都需要审批**，
#:   而 `for_role` 对只读角色永远剥掉 `exec` 工具。
#:
#: 这是**如实登记**而不是"现在就该补齐入口"：补齐的代价见 `draft/28` 的 `axes-3`
#: （模块级可变全局会让同一进程里两张注册表的审批面不同，该值应挪进 `ToolRegistry`
#: 实例，改动面更大）。两条口径都需要人裁 —— 在裁定之前，**这一档只由测试覆盖**。
SANDBOX_AVAILABLE: bool | None = None


class ToolError(RuntimeError):
    """工具执行失败。调用方只需捕这一个类型。"""

    def __init__(self, message: str, *, tool: str = "", detail: Any = None):
        super().__init__(message)
        self.tool = tool
        self.detail = detail


class ParamError(ToolError):
    """参数不合法。与"执行中失败"分开，便于上层区分"调用方写错了"和"环境出问题了"。"""


# ---------------------------------------------------------------- 已登记的只读例外

#: 已登记的只读角色例外：角色 -> （（工具名, 理由）, …）。
#:
#: ## 为什么需要这张表（`P-14` 的另一半）
#:
#: `ToolRegistry.for_role` 把只读角色（`C` / `H`）的工具面剥成 0 个写工具，
#: 而 `H` 有一个设计允许的落库代理：它必须能改 `review_findings` 与
#: `documents.status`（`capabilities.READ_ONLY_WRITE_EXCEPTIONS` 已登记表级例外）。
#: 那个代理走的是一个单独的注册表（`agent_h.install_h_tools` 之后的
#: `AgentH.writers`），里面的工具在 `build_registry` 装配出来的注册表里
#: 根本不存在（`review_tools.register` 默认 `include_writers=False`）。
#:
#: 调用期强制（`ToolRegistry.call` 的 `role=` 判据）一旦生效，"工具面"与
#: "可调用面"就必须被分开命名，否则下面两句话会互相打架：
#:
#: - `for_role("H")` 不许多出 `review.review_document`（那条面就是"H 声明能拿到什么"，
#:   而 `docs/ROLE-SPECS.md` §H.4 的条数与清单逐字钉着它）；
#: - `H` 的落库代理必须仍能调它（否则把 H 写审校发现与报告的能力一起砍了）。
#:
#: 所以：工具面（`for_role`）与可调用面（`call` 的判据）是两个集合，
#: 第二个只允许由这张显式登记表产生 —— 没有第二条产生路径，也不许有
#: "因为沙箱可用所以放行"之外的隐式放行。沙箱那条见 `_callable_for`。
#:
#: ## 单一来源（`G-45` 那一类缺陷）
#:
#: `agent_h._H_WRITABLE_TOOLS` 曾经是同一件事的第二份名字（三个工具名的字面量），
#: 现在它从本表派生（`READONLY_CALL_EXCEPTIONS["H"]`）。改这里就是改那里。
#:
#: 每条理由必须逐字说清"为什么这个只读角色能调这个写工具"；写不出理由的，
#: 就该改代码而不是加例外（与 `role_filter_notes` 的纪律同族）。
#:
#: `R4-2`：`role_filter_notes` 里的条目有**两个来源**（重算 / 装配期），
#: 所以重算来源的那些带一个标记前缀 —— 重算时只清带标记的，装配期那几条留着。
#: 为什么用前缀而不是另开一个字典：留痕的消费方（`scripts/release_check.py` 的
#: fail 说明、`docs/ROLE-SPECS.md` 的说明）读的是**一个列表**；
#: 把它拆成两个会让每一个消费点都要记得"两边都读"，而漏读一边是**静默**的。
_SURFACE_NOTE_TAG = "［工具面重算］"
READONLY_CALL_EXCEPTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    # C（业主 2026-10-18 裁定「只读角色的产出要能进台账」）：一个写入面。
    #   `analysis.register_report` 是 C 自己的**产出登记通道**：把这一趟它算出来的
    #   图读数 / 结构洞 / 候选缺口登记进 `analysis_reports`（复用
    #   `agent_c._support.AnalysisReport.persist`，不另写一份落盘实现）。
    #   为什么必须有这一条：C 的动作（`gaps` / `handle` / `paths` / …）不在 C 自己的
    #   工具面上（它们只能由父代理 `summon` 唤起）⇒ 被派空动作的自由任务里，C 手上
    #   一件写工具都没有。真机读数（`projects/mp3` 末节第 5 条）：`analysis_reports` = 0，
    #   C 的图读数只活在回复与手稿里；同趟 run 记录里它两次尝试（`gaps` / `handle`）
    #   都拿到「没有名为 … 的工具」。表级例外
    #   （`capabilities.READ_ONLY_WRITE_EXCEPTIONS["C"]`）早就登记了 `analysis_reports`
    #   —— 缺的正是这一件**工具**（`for_role` / `_role_surface` 把只读角色的写工具全剥掉）。
    #   判据三条：(1) 工具面仍然全量只读 ✓（这一件是全工具面上唯一的写，`roles=("C",)`）；
    #   (2) 写的是**成品报告的登记行**，不是知识表（`claims`/`literature`/`relations`
    #   零写入点，由 `tests/test_readonly_output_channel.py` 用"全表行数前后不变"守）；
    #   (3) 每一行都带 `kind`（受控词表）与 summary —— D 的读取端不会拿到表外取值。
    "C": (
        (
            "analysis.register_report",
            "C 的产出登记通道：把这一趟它算出来的分析落成 analysis_reports 一行"
            "（产出即登记）。C 的动作面只能由父代理 summon 唤起 ⇒ 没有这一件时，"
            "空动作的自由任务里 C 手上一件写工具都没有，图读数只能写进回复"
            "（projects/mp3 末节第 5 条：analysis_reports = 0）。只写这一张表，"
            "不碰 claims / literature / relations",
        ),
    ),
    "H": (
        (
            "review.review_document",
            "H 的审校动作必须落成 review_findings 行并改 documents.status —— 这是"
            "「审校记录」唯一的落点（不落库的审校等于没有审校）；落点被钉死："
            "只写 review_findings 与 documents.status，不碰 claims、不碰任何知识表",
        ),
        (
            "review.verify_fixes",
            "复审判 fixed/open 必须把结论写回 review_findings 并把文档置"
            "unresolved_review —— 与 review.review_document 同一个落点，"
            "同样是「发现问题」与「记录发现」之间的唯一通路",
        ),
        (
            "review.report",
            "带版本 hash 与自证数字的审校报告必须落成 markdown 文件（`draft/17` §8.4），"
            "否则「审校记录能不能被接手的复核」没有落点；它只写一个报告文件，"
            "不碰任何数据表、不碰 claims",
        ),
        (
            "review.record_finding",
            "H 自己读出来的发现也要有落点（业主 2026-10-18）：`review_document` 只落"
            "机械扫描算得出来的那批（`scan_document`），H 自己读出来的那一条"
            "（「G8 回执没给退出码」「正文引用的材料盘上没有」）此前只能写在回复或"
            "报告文件里 ⇒ `review_findings` 里永远只有机器算得出的那几类。"
            "本工具只写 review_findings（不去改 documents.status、不碰知识表）："
            "「补一条发现」与「改一格状态」是两件事",
        ),
    ),
}


# ---------------------------------------------------------------- 参数接缝（工具 schema ↔ handler 签名）

#: 工具侧的参数接缝表：`工具名 -> {property 名: 一行理由串}`。
#:
#: ## 这张表与 `capabilities.PARAM_SEAMS` 是同一机制的两个落点（台账 `N-5`）
#:
#: 两层各有一份"声明"，两份都可能有"声明了而实现不收"的格：
#:
#: - 能力层：`ActionSpec.params` ↔ `Agent<X>.<handler_name>` 的真形参
#:   （判据在 `capabilities.assert_capabilities` 第 [8] 条，导入期 fail-closed）；
#: - 工具层：`ToolSpec.params` 的 properties ↔ `ToolSpec.handler` 的真形参
#:   （判据在下面 :func:`param_seam_violations`，由 :meth:`ToolRegistry.register`
#:   在**注册那一刻**核 —— 见该方法的 docstring：`roles ⊆ schema.ROLES` 的判据
#:   正是从装配期搬到这里来的，理由逐字相同：绕过 `build_registry` 的入口
#:   （`agent_d.install_d_tools` / `agent_e.install_e_tools` …）也必须被核到）。
#:
#: 为什么落点是注册期而不是 `import agentflow.tools`：工具模块的 `register()`
#: 是**装配时才跑**的（`build_registry` 惰性 import 各模块），导入 `agentflow.tools`
#: 的那一刻树上一个 `ToolSpec` 都还没有 —— 在导入期能核的只有"这张表自己的形态"
#: （工具名的组前缀是否由 `_MODULES` 产生、理由串是否非空），
#: 那一条在 `tools/__init__.py` 的 `_check_param_seams_are_registered()` 里。
#:
#: ## 今天为什么是空的（这不是"没接上"）
#:
#: 真实树上工具层这一格是干净的：58 条工具声明里没有一个 property 是 handler
#: 收不下的（`tests/test_schema_handler_params.py` 的正控在测试面重复了同一条读数）。
#: 空表不等于没判据 —— 判据是否真的走遍了声明由 `param_seam_violations` 的
#: 调用方核覆盖率（`build_registry` 把 `inspected` 计数留在 `RegistryBuild` 里，
#: 测试断言它 ≥ 注册的工具数）。**不许**为了让这一格"看起来有东西"而凭空
#: 登记一条不需要的接缝：`assert` 会把"已经不需要了"的登记当缺陷报出来
#: （`stale_param_seam_violations`）。
PARAM_SEAMS: dict[str, dict[str, str]] = {}


def param_seam_reason(tool: str, prop: str, seams: Mapping[str, Mapping[str, str]] | None = None) -> str | None:
    """该 property 在接缝表里的理由串；没登记返回 `None`。

    `None` 与空字符串是两件事：空字符串会被 `_check_param_seams_are_registered`
    判成"登记了但没写理由"。
    """
    table = PARAM_SEAMS if seams is None else seams
    return (table.get(tool) or {}).get(prop)


def tool_param_seam_violations(
    spec: Any,
    seams: Mapping[str, Mapping[str, str]] | None = None,
) -> list[str]:
    """一个 `ToolSpec` 上"schema 声明了、handler 按名收不下、又没登记"的 property。

    判据与 `tests/test_schema_handler_params.py` 逐字同形（那一份是测试面的同一读数）：
    handler 收 `inspect.Parameter.VAR_KEYWORD` 时按定义不适用（它真的收得下任何键，
    所以这一格不会变成 `kind='unexpected'` 的假 bug 分类）。返回空列表 = 查过了、干净。

    ## 为什么名字带 `tool_`，而不是与能力层共用一个名字（`R003`）

    能力层的同族判据叫 `capabilities.param_seam_violations`，它比的是
    `ActionSpec.params` ↔ `Agent<X>.<handler_name>`。两者形状相同、对象不同，
    而依赖方向不允许合并成一份实现：`tools` 不许 import `capabilities`
    （依赖方向是 capabilities 局部 import tools），把判据搬到任一侧都会让
    另一侧反向依赖。名字里的 `tool_` 是显式的：它点明这一份守的是工具层，
    免得下一个人以为两处是同一份实现的两半（`R003` 报的正是这种同名双实现）。

    `spec.handler` 不是 callable 时这里会让 `inspect.signature` 抛出来 ——
    那是刻意的 fail-closed：注册一个 handler 坏掉的工具必须炸，
    而不是被"读不出签名就跳过"静默放过（三态纪律）。
    """
    sig = inspect.signature(spec.handler)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return []
    accepted = {
        name for name, p in sig.parameters.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    props = (spec.params or {}).get("properties") or {}
    return sorted(
        name for name in props
        if name not in accepted and param_seam_reason(spec.name, name, seams) is None
    )


def stale_tool_param_seams(
    specs: Mapping[str, Any],
    seams: Mapping[str, Mapping[str, str]] | None = None,
) -> list[str]:
    """接缝表里"已经不需要了 / 指向不存在的工具"的条目 ⇒ `["工具.property", …]`。

    两种"不需要"：这个工具名不在给定的 `specs` 里（登记指向空气），或那个
    property 现在真的被 handler 接受了（接缝已闭合）。理由与
    `capabilities.stale_param_seams` 一样：只增不减的登记表会烂成噪音。
    """
    table = PARAM_SEAMS if seams is None else seams
    out: list[str] = []
    for tool in sorted(table):
        spec = specs.get(tool)
        for prop in sorted(table[tool] or {}):
            if spec is None:
                out.append(f"{tool}.{prop}")
                continue
            if prop not in ((spec.params or {}).get("properties") or {}):
                out.append(f"{tool}.{prop}")
                continue
            if prop not in tool_param_seam_violations(spec, seams):
                # 已经不需要接缝了（handler 现在收得下它）
                out.append(f"{tool}.{prop}")
    return out


def check_param_seams(
    spec: Any,
    seams: Mapping[str, Mapping[str, str]] | None = None,
) -> None:
    """注册期的 fail-closed 判据：违反就抛 `ParamError`（`N-5` 的工具侧落点）。

    错误信息逐字给出 工具名 / property / handler 名，并说清两条出路
    （改 handler 去接受它，或登记进 `PARAM_SEAMS` + 写理由）——
    与能力层第 [8] 条同一句话，因为说的确实是同一件事。
    """
    bad = tool_param_seam_violations(spec, seams)
    if bad:
        raise ParamError(
            f"{spec.name} 的 schema 声明了 handler 收不下的参数 {bad}"
            f"（handler={getattr(getattr(spec, 'handler', None), '__name__', '?')}）—— "
            "`ToolRegistry.call` 的第一步 `validate_params` 会放行它们、第二步 "
            "`spec.handler(**merged)` 会抛 TypeError，而兜底把它记成 "
            "`ok=False / kind='unexpected'`（'库内部出错'那一类，一个假 bug 分类）。"
            "两条出路（二选一，不许留第三态）：① 改 handler 去接受它；"
            "② 登记进 `tools.base.PARAM_SEAMS` 并逐字写明理由（它只服务谁 / "
            "为什么 handler 刻意不收）",
            tool=spec.name,
            detail={"unaccepted": bad},
        )


# ---------------------------------------------------------------- 结果


@dataclass
class ToolResult:
    """工具的统一返回。

    不抛异常表达"业务上的失败" —— 例如"没找到这个概念"。那种情况返回
    `ok=False` 并给出 `error`，让智能体看到并决定下一步；抛异常会打断它的循环。
    只有调用方写错（参数不合法）与环境故障才抛。
    """

    ok: bool
    data: Any = None
    error: str | None = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "data": self.data, "error": self.error, "meta": self.meta}

    def unwrap(self) -> Any:
        """调用方确信成功时用它取数据；失败则抛。脚本模式用起来最省事。"""
        if not self.ok:
            raise ToolError(self.error or "工具调用失败")
        return self.data

    def pruned(self, budget: "ContextBudget", *, spill_root: "str | Path | None" = None) -> "ToolResult":
        """按上下文预算剪枝 / 落盘 `data` 里的大字符串（FC-17），返回新结果。

        为什么剪枝是显式的，而不是在 `ToolRegistry.call` 里自动做：
        自动剪会悄悄改变所有既有调用方拿到的返回值，于是"没开剪枝"与
        "开了但没超阈值"在调用方眼里长得一模一样 —— 那正好是本项目最忌讳的
        失败形态（分不清"没做"与"做了没效果"）。入口在这里，剪不剪由调用方决定。

        剪枝不改结论：`ok` / `error` 逐字段保留，只有 `data` 变短、`meta`
        多出 `pruned` / `spilled` / `spill_path` / `original_chars` 等审计字段。

        实现转发给 `agentflow.contextbudget.prune_tool_result`，且用局部导入：
        工具层基座是所有智能体的公共底盘，不该在 import 期就依赖上下文预算模块
        （`contextbudget` 也不 import 本模块，用鸭子类型 + `dataclasses.replace`，
        两边都不构成循环 —— 有测试锁这一点）。
        """
        from ..contextbudget import prune_tool_result  # 局部导入：避免 import 期耦合

        return prune_tool_result(self, budget=budget, spill_root=spill_root)


def ok(data: Any = None, **meta: Any) -> ToolResult:
    return ToolResult(True, data, None, dict(meta))


def fail(error: str, **meta: Any) -> ToolResult:
    return ToolResult(False, None, error, dict(meta))


# ---------------------------------------------------------------- 极简 JSON Schema 校验

_TYPES: dict[str, tuple] = {
    "object": (dict,),
    "array": (list, tuple),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def _type_name(v: Any) -> str:
    return {dict: "object", list: "array", str: "string", bool: "boolean", int: "integer", float: "number"}.get(
        type(v), type(v).__name__
    )


def _schema_allows_null(sub: Any) -> bool:
    """这个参数**显式传 null** 是否合法（2026-10-17）。

    两档放行：子 schema 自己写了 `"nullable": True`；或 `type` 是列表且含 `"null"`。
    其余一律不放行 —— `null` 不是"没提供"，见 `validate_params` 里那段理由。
    """
    if not isinstance(sub, Mapping):
        return False
    if sub.get("nullable") is True:
        return True
    t = sub.get("type")
    return isinstance(t, (list, tuple)) and "null" in t


def validate_params(schema: Mapping[str, Any], params: Any, *, path: str = "") -> None:
    """按 schema 校验参数。不合法抛 `ParamError`（不是返回布尔）。

    只支持本工具层实际用到的子集：type / required / properties / enum /
    items / minimum / maximum / minLength / maxLength / minItems / maxItems /
    additionalProperties。刻意不做全量 JSON Schema —— 覆盖面够用即可，
    实现越小越不容易有 bug。

    ⚠️ 这里必须先看 schema 声明的类型再决定怎么校验。
    曾经把"必须是对象"的检查放在函数开头，结果任何非对象值（比如一个字符串参数）
    一进来就被判成"必须是对象" —— 因为子 schema 也会走同一个函数。
    """
    t = schema.get("type")
    if t is None:
        return  # 未声明类型 = 不约束

    if t == "object":
        if not isinstance(params, Mapping):
            raise ParamError(f"{path or 'params'} 必须是对象，收到 {_type_name(params)}")
        props: Mapping[str, Any] = schema.get("properties") or {}
        for req in schema.get("required") or []:
            if req not in params:
                raise ParamError(f"缺少必填参数：{path}{req}")
        if schema.get("additionalProperties") is False:
            extra = set(params) - set(props)
            if extra:
                raise ParamError(f"出现未声明的参数：{sorted(extra, key=str)}（schema 只允许 {sorted(props)}）")
        for name, sub in props.items():
            if name in params and params[name] is not None:
                validate_params(sub, params[name], path=f"{path}{name}.")
        return

    if t == "array":
        if not isinstance(params, (list, tuple)):
            raise ParamError(f"{path or 'value'} 必须是数组，收到 {_type_name(params)}")
        if "minItems" in schema and len(params) < schema["minItems"]:
            raise ParamError(f"{path} 至少 {schema['minItems']} 项，收到 {len(params)}")
        if "maxItems" in schema and len(params) > schema["maxItems"]:
            raise ParamError(f"{path} 最多 {schema['maxItems']} 项，收到 {len(params)}")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for i, item in enumerate(params):
                validate_params(item_schema, item, path=f"{path}[{i}].")
        return

    # ---- 标量
    # bool 是 int 的子类，必须先单独判布尔，否则 True 会被当成合法整数
    if t == "boolean":
        if not isinstance(params, bool):
            raise ParamError(f"{path or 'value'} 必须是 boolean，收到 {_type_name(params)}")
    elif t == "integer":
        if isinstance(params, bool) or not isinstance(params, int):
            raise ParamError(f"{path or 'value'} 必须是 integer，收到 {_type_name(params)}")
    else:
        expected = _TYPES.get(t)
        if expected and not isinstance(params, expected):
            raise ParamError(f"{path or 'value'} 必须是 {t}，收到 {_type_name(params)}")

    if "enum" in schema and params not in schema["enum"]:
        raise ParamError(f"{path or 'value'} 必须是 {schema['enum']} 之一，收到 {params!r}")
    if t == "string":
        if "minLength" in schema and len(params) < schema["minLength"]:
            raise ParamError(f"{path} 长度至少 {schema['minLength']}")
        if "maxLength" in schema and len(params) > schema["maxLength"]:
            raise ParamError(f"{path} 长度最多 {schema['maxLength']}")
    if t in ("integer", "number"):
        if "minimum" in schema and params < schema["minimum"]:
            raise ParamError(f"{path} 不能小于 {schema['minimum']}")
        if "maximum" in schema and params > schema["maximum"]:
            raise ParamError(f"{path} 不能大于 {schema['maximum']}")


# ---------------------------------------------------------------- ToolSpec


@dataclass(frozen=True)
class ToolSpec:
    """一个可调用工具。

    `params` 用 JSON Schema 写（object 根），既用于本层校验，也能原样喂给
    function-calling —— 所以它必须自描述、不含 Python 专有类型。

    ## 两根轴（`effect` × `external`）与"六件套"

    `side_effect` 是声明轴的历史名称，它把两根正交轴压在一个取值上。
    本类同时给出两根轴上的取值：`effect`（能不能改我们拥有的东西）与
    `external`（能不能触到我们不拥有的事）。`declared_external` 由工具作者
    人写（默认 `none`，因为"我没说"不等于"我会出网"）；两根轴的最终取值
    都由属性就地推导（`DEVELOPMENT.md` §3 纪律 6：派生态就地推导或
    装配期断言，没有第三种）。

    ⚠️ AST 只用来核对声明与代码是否一致，绝不用来生成声明（P-13 §9①：
    N-4 已否决 AST 推断 —— 22/55 取不到 handler 源码、9 个转发型 handler
    是假阳性）。本类里没有一个字符是由 AST 推断出来的：两根轴上的值都是
    人写下来的（`side_effect` 与 `declared_external`），词表只用来挡非法取值。
    """

    name: str
    summary: str
    params: Mapping[str, Any]
    handler: Callable[..., Any]
    side_effect: str = "none"
    roles: tuple[str, ...] = ()
    returns: str = ""
    tags: tuple[str, ...] = ()
    #: 第二根轴：`none` / `egress` / `exec`（取值清单见 :data:`EXTERNAL`）。
    #: 必须人写；AST 绝不用它来生成这个值（P-13 §9①）。
    #:
    #: ⚠️ 它是字段而不是属性：属性会和 dataclass 的 `__init__(external=...)`
    #: 撞名。第二根轴的取值由 :attr:`external` 属性给出，这个名字只保留
    #: "人写下来的那一份声明"（`tool()` 装饰器的同名关键字参数 `external`
    #: 也落到这个字段上）。
    declared_external: str = "none"

    def __post_init__(self) -> None:
        """装配期自检：六件套齐全 + 两根轴的取值受控。

        ## 为什么六件套校验真的在这里（它此前不在这里）

        `DEVELOPMENT.md` §4.3 第 1 项逐字声称"六件套齐全"由本方法校验，
        而实测它只校验了 `side_effect` 与"名字含 `.`"。文档承诺了一个
        不存在的门，比少一条门更危险：读者以为 `summary` / `params` /
        `returns` / `roles` 有人管，于是不再去看。本轮把这条承诺兑现成
        真正的取值校验（见 §4.3 第 1 项与本类测试）。

        ## 判据的形态

        六件套里四件（`name` / `summary` / `params` / `returns`）是输入，
        必须是可用的值；`side_effect` 与 `roles` 的"齐全"是结构性的
        （受控词表 + 元组），不是"非空"：`roles=()` 是一个真实的声明
        （"这个工具不属于任何角色"），把它判成"缺字段"会把一个可判定的
        事实折叠成错误。

        `roles` 那半的"元组"判据在末尾（`D6`：它此前只写在注释里，
        实现里没有，实测 `roles=['E']` 被接受）。

        顺序刻意是先词表后结构：`side_effect` 的取值校验必须排在
        `params` 之前，否则 `params={}` 这种手工构造会先以"params 不是
        object 根"报错，把"side_effect 非法"这条更重要的信息盖掉
        （既有测试 `test_toolspec_rejects_invalid_side_effect` 钉住了这一点）。
        """
        # ---- 一根轴：受控词表。先判它（理由见 docstring 末尾）
        if self.side_effect not in SIDE_EFFECTS:
            raise ValueError(f"side_effect 必须是 {SIDE_EFFECTS} 之一，收到 {self.side_effect!r}")
        # ---- 第二根轴：受控词表（与 SIDE_EFFECTS 同一处声明，见 EXTERNAL）
        if self.declared_external not in EXTERNAL:
            raise ValueError(
                f"external 必须是 {EXTERNAL} 之一，收到 {self.declared_external!r}"
            )
        # ---- 六件套：name / summary / params / returns
        if not self.name or "." not in self.name:
            raise ValueError(f"工具名建议用 '组.动作' 形式，收到 {self.name!r}")
        if not str(self.summary or "").strip():
            raise ValueError(f"{self.name} 没有 summary —— 它是给人和 LLM 看的唯一一句说明")
        if not isinstance(self.params, Mapping) or self.params.get("type") != "object":
            raise ValueError(
                f"{self.name} 的 params 根必须是 object（JSON Schema 子集，"
                f"要能原样喂给 function-calling），收到 {type(self.params).__name__}"
            )
        if not isinstance(self.returns, str):
            # `returns` 的非空校验是刻意的弱判据：见 `REQUIRED_NON_EMPTY_FIELDS`
            # 的注释（它会命中 `agent_d.py` 的三个内置降级替身，而那个文件不在
            # 本轮授权范围内）。这里只挡"类型给错"（None / 非字符串），
            # 而"忘了写"由 §4.3 的 census 观察。
            raise ValueError(
                f"{self.name} 的 returns 必须是字符串（空字符串 = 你确认过它没有"
                f"可声明的返回形态），收到 {type(self.returns).__name__}"
            )
        # ---- 六件套里 `roles` 的"齐全"是结构性的：必须是元组（`D6`）
        #
        # `D6`（2026-09-26 全面体检 · 子代理 B，实测）：上面两处 docstring
        # （本类的"六件套"一段与 `REQUIRED_NON_EMPTY_FIELDS`）都逐字写着
        # `roles` 的齐全判据是"受控词表 + 元组"，而实测 `ToolSpec(..., roles=['E'])`
        # 被接受、得到一个 list —— 元组那道门不存在。对照组（`summary='   '` /
        # `side_effect='network'` / `declared_external='network'` / `returns=None`）
        # 都确实被拒，只有 `roles` 没有门。同一段 docstring 点名批评的正是
        # "文档承诺了一个不存在的门，比少一条门更危险"。
        #
        # 为什么收在这里而不是放宽文档：`tuple` 是这条声明的契约的一半
        # （另一半是受控词表），而它是唯一的那个结构化判据 ——
        # `role in ROLES` 那半在 `ToolRegistry._reject_unknown_roles` 里，
        # 元组这半不在这里就没有任何地方有。`tool()` 装饰器已经用
        # `tuple(roles)` 兜住，所以只有手工构造会命中 —— 而那正是要拦的。
        if not isinstance(self.roles, tuple):
            raise ValueError(
                f"{self.name} 的 roles 必须是元组（六件套里 roles 的齐全判据是"
                f"『受控词表 + 元组』，见本类 docstring 与 REQUIRED_NON_EMPTY_FIELDS），"
                f"收到 {type(self.roles).__name__}。`tool()` 装饰器会替你转，"
                f"手工构造时请自己写 `roles=('A',)`"
            )

    @property
    def external(self) -> str:
        """第二根轴：触不触到我们不拥有的事（`none` / `egress` / `exec`）。

        它就是人写下来的那个声明（`ToolSpec(..., declared_external="exec")`）。
        B3 收官删掉遗留取值之后，这个属性不再有第二个来源：
        它曾经要查翻译表，是因为 `network` 那个取值分不清"出网"与"起进程"；
        现在没有那个取值了，属性与字段是同一件事。
        """
        return self.declared_external

    @property
    def effect(self) -> str:
        """第一根轴：改不改我们拥有的东西。

        与 `side_effect` 同值 —— 这根轴是从那根轴上取下来的，不是第二份声明，
        也不是第二份词表。它曾经为遗留取值 `network` 查逐工具翻译表（`network`
        字面上说的是"不改我们的东西"，而 `search.download` 其实会写工作区），
        B3 收官之后那层翻译连同遗留取值一起消失。
        """
        return self.side_effect

    @property
    def needs_approval(self) -> bool:
        """要不要人工审批。推导，不查逐工具布尔位（P-13 §3.3）。

        ```
        needs_approval = (effect == "write_local")
                      or (external != "none" and not sandbox_available)
        ```

        与提案字面表述的关系，刻意写在这里而不是留给读者去猜：提案把沙箱不可用
        时的升级写成 `external == "exec"` 一条，本实现还包含 `egress` ——
        沙箱不可用时出网同样没有任何承接手段（提案 §3.3 自己也写了这一条），
        而沙箱可用时两者都被承接、都不再需要签字。

        B3 收官删掉遗留取值 `network` 与 `NEEDS_APPROVAL` 那张表之后，
        这个函数只剩上面这一条判据（`write_local` 那一支已经覆盖了旧表的第一项；
        旧表的第二项 `network` 已从词表里消失）。删掉它是刻意的：
        留着它就等于"两套说法说同一件事"（FC-03 要防的形态）。
        """
        if self.effect == "write_local":
            return True
        return self.external != "none" and SANDBOX_AVAILABLE is not True

    @property
    def sandbox_required(self) -> bool:
        """要不要进沙箱：纯推导，无例外（P-13 §3.3）。"""
        return self.external != "none"

    def to_dict(self) -> dict:
        """给人/LLM 看的描述。不含 handler（不可序列化）。"""
        return {
            "name": self.name,
            "summary": self.summary,
            "params": dict(self.params),
            "side_effect": self.side_effect,
            "effect": self.effect,
            "external": self.external,
            "needs_approval": self.needs_approval,
            "sandbox_required": self.sandbox_required,
            "roles": list(self.roles),
            "returns": self.returns,
            "tags": list(self.tags),
        }

    def to_function_schema(self) -> dict:
        """OpenAI/DeepSeek 风格 function-calling 描述。"""
        return {
            "type": "function",
            "function": {
                "name": self.name.replace(".", "__"),  # 部分供应商不接受点号
                "description": self.summary + (f"\n返回：{self.returns}" if self.returns else ""),
                "parameters": dict(self.params),
            },
        }


def tool(
    name: str,
    summary: str,
    params: Mapping[str, Any] | None = None,
    *,
    side_effect: str = "none",
    roles: Iterable[str] = (),
    returns: str = "",
    tags: Iterable[str] = (),
    external: str = "none",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """把普通函数标记成工具。`handler` 直接就是被装饰的函数。

    约定：handler 可以返回 `ToolResult`，也可以返回任意可 JSON 化的值
    （此时自动包成 `ok(...)`）；抛 `ToolError` 会被登记为失败结果而不再向上抛，
    这样智能体的循环不会因为一次工具失败而中断。

    `external` 见 :class:`ToolSpec`，必须人写：本装饰器里没有任何一处
    从函数体推断副作用（AST 推断已被 N-4 否决）。
    """

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        spec = ToolSpec(
            name=name,
            summary=summary,
            params=params or {"type": "object", "properties": {}, "additionalProperties": False},
            handler=fn,
            side_effect=side_effect,
            roles=tuple(roles),
            returns=returns,
            tags=tuple(tags),
            declared_external=external,
        )
        fn.__tool_spec__ = spec  # type: ignore[attr-defined]
        return fn

    return deco


# ---------------------------------------------------------------- 注册表


def candidate_tool_names(name: str, names: Iterable[str], *, limit: int = 3) -> list[str]:
    """错名的**并列候选**（`draft/56` §2 主线 A 的 L-05h 机器半）。

    只回答"看起来像哪一个"，**绝不自动挑一个**（挑是判断，归出错方的秘书）。
    三条判据按序取并集，去重后截到 `limit`：

    1. **同尾名**：`fs.read` 与 `table.read` 的尾名都是 `read` ⇒ 给 `read` 时并列出来
       （广告名与真名共用尾名是模型最常走的错法）；
    2. **尾名近似**：`fs.raed` ⇒ `fs.read`（`difflib` 的近似匹配，阈值 0.6）；
    3. **全名近似**：`review.reportt` ⇒ `review.report`。

    `names` 传的是**本注册表**里的名字。`ToolRegistry.scoped_to(..., deps=...)`
    会把 writers 子注册表里那批落库代理（`review.*`）装进同一张表，
    于是它们与工具面上的名字一样能被命中（"含 writers 子注册表名"这一条由结构保证，
    不是另写一份名单）。
    """
    pool = sorted({str(n) for n in names if str(n)})
    want = str(name or "")
    if not want or not pool:
        return []
    out: list[str] = []
    tail = want.split(".")[-1]
    if tail:
        out += [n for n in pool if n.split(".")[-1] == tail]
        tails = sorted({n.split(".")[-1] for n in pool})
        out += [n for n in pool if n.split(".")[-1] in difflib.get_close_matches(
            tail, tails, n=limit, cutoff=0.6)]
    out += list(difflib.get_close_matches(want, pool, n=limit, cutoff=0.6))
    seen: set[str] = set()
    uniq: list[str] = []
    for n in out:
        if n != want and n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq[:limit]


class ToolRegistry:
    """按角色组织的工具表。"""

    def __init__(self, *, name: str = "registry"):
        self.name = name
        self._specs: dict[str, ToolSpec] = {}
        self._call_log: list[dict] = []
        self.log_calls = False
        #: ⚠️ 注册表级的默认上下文预算（FC-17 的接线点）。
        #:
        #: 为什么放在注册表上而不是让每个调用点自己传：FC-17 的实现方如实报告过
        #: "框架里没有任何调用方真的会传 `budget`" —— 那条约束当时只有骨架。
        #: 把预算做成装配期属性之后，"开启剪枝"只需要在装配处做一次决定，
        #: 而不是指望每个 `_call` 都记得传参数（那种"靠人记得"的设计已经
        #: 在本项目里失败过多次）。
        #:
        #: `None`（默认）⇒ 行为与加 FC-17 之前逐字节一致。
        self.default_budget: "ContextBudget | None" = None
        #: 默认的 spill 根目录。装配时设成工作区根 —— 否则 `default_budget` 生效时
        #: 剪枝后的内容想落盘却没有地方可落（`prune` 的语义是"没给 root ⇒ 不落盘
        #: 但如实报告"），于是 spill 这一件套永远走不到。
        self.default_spill_root: Any = None
        #: `for_role` 的过滤留痕。空 dict 表示"没有任何工具的 roles 声明需要被纠正"。
        self.role_filter_notes: dict[str, list[str]] = {}
        #: 这张注册表代表谁（`P-14` 的调用期判据）。`None`（默认）表示
        #: "调用方没说自己是谁" —— 那种注册表上的 `call` 一律被拒（fail-closed），
        #: 除非调用方逐次显式传 `role=`。
        #:
        #: 为什么默认是 `None` 而不是"所有角色"：默认放开等于"不写就等于允许"，
        #: 而只读约束（C/H 拿不到写工具）恰恰是靠"不写就不许"来强制的。
        self.bound_role: str | None = None

    # ---- 注册
    def register(self, spec: ToolSpec) -> ToolSpec:
        """注册一个工具。注册那一刻就核 `roles`（`P-1`）。

        ## 为什么校验必须在这里，而不是只在装配期

        `roles ⊆ schema.ROLES` 原先只在 `build_registry` 里核（`tools/__init__.py`）。
        后果实测过两次：`agent_d.install_d_tools` 自建注册表绕过它，于是
        `roles=("agent-C", "agent-D")` 这种拼错一路装到底、`for_role` 静默少工具；
        `agent_e.install_e_tools` / `agent_f.install_f_tools` 同样绕过它（那是
        `docs/PROPOSALS.md` 的 `P-1`）。绕过 `build_registry` 的入口都要自己补一次
        —— 那不是"每个入口都记得"，而是"判据放错了地方"。

        放在注册期之后，判据覆盖所有入口（`register` / `register_function` /
        `register_spec` / `register_all`），而且失败得更早（构造注册表时就炸，
        而不是等到有人按角色过滤时才发现少工具）。

        ## 注册期的失败一律用 `ToolError`（`errors-7`）

        `errors-7`（2026-09-26 全面体检 · 子代理 A，实测）：同一条注册路径上
        有两种失败类型 —— 重名抛裸 `ValueError`，而同方法里的
        `_reject_unknown_roles` 抛 `ToolError`。后果是"按 `ToolError` 分类处理
        装配失败"的调用方会**静默漏掉工具名重复**这一类；今天只有
        `build_registry` 捕 `Exception` 才把影响掩盖住。
        所以重名这一支也统一成 `ToolError`（工具层的公共契约就是只捕这一个类型，
        见 `ToolError` 的 docstring），并把工具名放进 `tool=` 元信息里，
        与 `_reject_unknown_roles` 一致。

        ## `N-5` 的第二条同族判据：参数面（schema ↔ handler 签名）

        `_reject_unknown_roles` 管的是"这个工具属于谁"，`check_param_seams`
        管的是"这个工具收不收它自己声明的参数"。两者放在同一个入口、同一个时刻，
        理由逐字相同：绕过 `build_registry` 的注册表（`agent_d.install_d_tools` /
        `agent_e.install_e_tools` 等）也必须被核到 —— 判据放错地方的症状是
        "某个入口静默少一条校验"，而不是任何一处报错（那正是 `P-1` 实测的形态）。
        """
        self._reject_unknown_roles(spec)
        check_param_seams(spec)
        if spec.name in self._specs:
            raise ToolError(f"工具名重复：{spec.name}", tool=spec.name)
        self._specs[spec.name] = spec
        return spec

    def _reject_unknown_roles(self, spec: ToolSpec) -> None:
        """`set(spec.roles) <= set(TOOL_ROLES)`，否则抛 `ToolError`（`P-1` 的判据）。

        单一来源是 `tools.TOOL_ROLES`（= `schema.ROLES` 加上主控 `CONDUCTOR_ROLE`）——
        不许另写名单。为什么主控在词汇里：`schema.ROLES` 管"谁可以被召唤"，
        工具层管"谁能拿工具"，这两件事必须分开 —— 实测（2026-09-28）
        `registry.for_role("M") == []`，主控此前工具面为空，"派活"在它手上没有动作可用。
        主控拿工具不代表它能被召唤：可召唤性由 `capabilities.ALLOWED_EDGES` /
        `NON_SUMMONABLE` 决定。
        """
        from . import TOOL_ROLES  # 局部导入避免模块级循环（`tools/__init__` 会 import 本模块）

        unknown = [r for r in spec.roles if r not in TOOL_ROLES]
        if unknown:
            raise ToolError(
                f"{spec.name} 声明了不在 TOOL_ROLES{tuple(TOOL_ROLES)} 里的角色：{unknown}。"
                "角色名是跨模块约定，拼法不一致会让 for_role() 静默漏掉这些工具；"
                "校验现在发生在注册那一刻（P-1），而不是只在 build_registry 的装配期。",
                tool=spec.name,
            )

    def register_all(self, specs: Iterable[ToolSpec]) -> None:
        for s in specs:
            self.register(s)

    def register_function(self, fn: Callable[..., Any]) -> ToolSpec:
        spec = getattr(fn, "__tool_spec__", None)
        if spec is None:
            raise ValueError(f"{getattr(fn, '__name__', fn)!r} 不是工具（缺 @tool 标记）")
        return self.register(spec)

    def register_spec(self, spec: ToolSpec) -> ToolSpec:
        """`register` 的显式别名（`P-1` 点名要求三处入口都核 `roles`）。

        它不复制判据，只是同一个入口的第二个名字：三处入口（`register` /
        `register_function` / `register_spec`）都必须核，而判据只有一份 ——
        写在这里的第二份校验会是 `FC-03` 要防的那种分叉。
        """
        return self.register(spec)

    # ---- 查询
    def get(self, name: str) -> ToolSpec:
        """取一个工具的声明；不认识这个名字时抛 `ToolError`。

        ## 错名给的是**并列候选**，不是"一次自动纠正"（`draft/56` §2 主线 A）

        原来这一格的提示是 `[n for n in self._specs if name.split(".")[-1] in n]`
        —— 一个子串包含判据：它对 `fs.raed`（调换两个字母）给不出任何候选，
        而对 `read` 会同时命中一批里含 `read` 的名字，读的人仍然不知道该改哪一处。

        新口径（`draft/53` §10 / `draft/55` §3.2 的 L-05h）：

        - 机器**只把候选并列出来**（含 writers 子注册表里的那批名字 ——
          `scoped_to(..., deps=...)` 把 `review.*` 这类落库代理装进本表，
          于是它们和工具面上的名字一样能被候选命中）；
        - 机器**不自动改写**：选哪个名字是判断，归出错方的秘书（职责 1/2），
          机器只留 fail-closed 的 `unknown_tool` 与这份候选读数。

        真机读数（`draft/44` 的 L-05h）：`review`7 / `review_report`6 /
        `review.report`5 / `doc.revise`2 次调用**全失败且无回映** —— 白烧步数。
        """
        try:
            return self._specs[name]
        except (KeyError, TypeError):
            # 2026-10-17（子代理 tools 甲类 #2）：`name` 不可哈希（如传了个 list）时
            # `self._specs[name]` 抛 **TypeError**，原来只捕 KeyError ⇒ 冒泡出 `call`。
            # 现在并进"查不到"这一条路：下面照旧给候选名与提示，不冒泡。
            close = candidate_tool_names(name, self._specs)
            hint = ""
            if close:
                hint = (f"；并列候选（{len(close)} 个）：{close} —— 机器只列候选、"
                        "不自动改写，由你（或你的秘书）决定改哪一处")
            raise ToolError(f"没有名为 {name!r} 的工具{hint}", tool=name) from None

    def names(self) -> list[str]:
        return sorted(self._specs)

    def call_surface(self, role: str) -> list[str]:
        """可调用面的工具名（`P-14`）：工具面 + 逐条登记的落库代理。

        为什么需要它（而不只是 `for_role`）：`call` 的判据用的是这个集合，
        装配方与报告方必须能看到同一个集合 —— 否则"为什么 H 能调
        `review.review_document`"就只能靠读 `call` 的实现来回答。
        名字进 `role_filter_notes` 的那一类（被只读约束剥掉的）不在里面。
        """
        surface, _ = self._role_surface(role, filter_readonly=True, call_surface=True)
        return sorted(s.name for s in surface)

    def scoped_to(self, role: str, *, deps: Mapping[str, Any] | None = None) -> "ToolRegistry":
        """返回一张只代表 `role` 的新注册表（`bound_role = role`）。

        ## 它是便利入口，不是旁路

        它内部走同一个私有谓词（:meth:`_role_surface`）：新表登记的是同一个注册表
        里的全部 spec（同一个不可变对象，不是拷贝），而"这一次到底能不能调"由
        :meth:`call` 逐次判（`_callable_for`）—— 装配时过滤一次就永久放行的那种
        设计正是 `P-14` 要消灭的形态。

        ## 为什么新表保留全部 spec，而不是只登记该角色的工具面

        两条理由，第二条是决定性的：

        1. 判据是角色，不是"表里有没有这个名字"。只登记工具面会让
           `call("fs.write", role="C")` 得到"没有名为 fs.write 的工具"——
           那既掩盖了"这张表代表 C"的事实，也让"冒充另一个角色"（`role="H"` 传进来）
           这件事没法被看见（它应该报"绑定的是 C，你传了 H"）。
        2. 只读角色的已登记落库代理必须能通过它拿到。若新表按工具面裁剪，
           `H` 的三个 `review.*`（在 `build_registry` 的完整注册表里根本不存在）
           就连名字都注册不进来，`_callable_for` 便永远只能报 `unknown_tool` ——
           那张显式例外表会失效。

        ## `deps`：例外工具没被装配过时按需补装

        `H` 的落库代理（`READONLY_CALL_EXCEPTIONS["H"]`）不在 `build_registry` 的
        产物里（`review_tools.register` 默认 `include_writers=False`），而它的 handler
        是一个闭包（把 `store` / `actor` 绑进去的那种），所以补装必须走该模块自己的
        `register(..., include_writers=True)`，而不是凭空造一个 `ToolSpec`。
        `deps` 就是传给那次 `register` 的依赖（例：`{"store": store}`）。

        补装默认不生效（`deps=None`）且绝不静默失败：补装没做成时会在
        :attr:`role_filter_notes` 里留一条说明。这不是一条第二条判据 ——
        例外表仍然是唯一的"谁可以调什么"的声明，这里只是把它的工具装进来。

        装饰性属性（上下文预算 / spill 根）一并复制，否则"按角色装配之后 FC-17
        的接线静默失效"（`AgentG` 的注册表就是这么来的）。
        """
        scoped = ToolRegistry(name=f"{self.name}:{role}")
        scoped.bound_role = role
        for spec in self._specs.values():
            scoped.register(spec)
        for message in self.role_filter_notes.get(role, []):
            scoped.role_filter_notes.setdefault(role, []).append(message)
        scoped._attach_registered_writers(role, deps=deps)
        scoped.default_budget = self.default_budget
        scoped.default_spill_root = self.default_spill_root
        return scoped

    def _attach_registered_writers(self, role: str, *, deps: Mapping[str, Any] | None) -> None:
        """把 `role` 的已登记落库代理补装进本表（`scoped_to` 的第二步）。

        代理本来就在本表里时不做事（`AgentH.writers` 那条路径就是这种情形）。
        既不在表里、又没给 `deps` ⇒ 记一条留痕（"这张表代表该角色，但它的代理
        没被装配过"），绝不假装它有。补装失败同样留痕（`FC-08`：降级必须显式）。
        """
        wanted = READONLY_CALL_EXCEPTIONS.get(role)
        if not wanted:
            return
        missing = [name for name, _why in wanted if name not in self._specs]
        if not missing:
            return
        if deps is None:
            self.role_filter_notes.setdefault(role, []).append(
                f"已登记的落库代理 {sorted(missing)} 没有装配进这张表（装配时没给 deps）⇒ "
                "它们仍是不可调用的；要给就传 deps=<该模块 register 的依赖>"
            )
            return
        from . import _MODULES  # 局部导入避免模块级循环

        by_module: dict[str, list[str]] = {}
        for name in missing:
            prefix = name.split(".", 1)[0]
            module_name = f"{__package__}.{prefix}_tools" if f"{prefix}_tools" in _MODULES else ""
            by_module.setdefault(module_name, []).append(name)
        for module_name, names in by_module.items():
            if not module_name:
                self.role_filter_notes.setdefault(role, []).append(
                    f"已登记的落库代理 {sorted(names)} 找不到对应的工具模块 ⇒ 没装进来"
                )
                continue
            try:
                mod = __import__(module_name, fromlist=[module_name.rsplit(".", 1)[-1]])
                fn = getattr(mod, "register", None) or getattr(mod, "install", None)
                if fn is None:
                    raise ToolError(f"{module_name} 没有 register()/install()，无法补装落库代理")
                # 先把本模块已装上的那几条暂时摘掉，再整模块重装一次
                # （`include_writers=True`）。为什么必须这样：各工具模块的 `register`
                # 是"整模块装配"的形态，重装会撞上"工具名重复"，而我们要的正好是
                # 它这一次多装出来的那几条写工具。摘掉再装回，`ToolSpec` 是冻结对象，
                # 恢复的是同一个对象，不产生第二份定义。
                detached = {
                    name: self._specs.pop(name)
                    for name in [
                        spec.name
                        for spec in list(self._specs.values())
                        if spec.name.split(".", 1)[0] == names[0].split(".", 1)[0]
                    ]
                }
                try:
                    # 只用 `include_writers=True` 这一种形态补装：来源是
                    # `READONLY_CALL_EXCEPTIONS`（写工具），而这一个开关就是各工具模块
                    # 表达"把写工具也装上"的统一约定（`review_tools.register` 的签名钉着它）。
                    fn(self, **dict(deps), include_writers=True)
                except Exception:
                    self._specs.update(detached)
                    raise
                self._specs.update(detached)
            except Exception as e:  # noqa: BLE001 - 补装失败必须留痕，不许静默
                self.role_filter_notes.setdefault(role, []).append(
                    f"已登记的落库代理 {sorted(names)} 补装失败（{type(e).__name__}: {e}）⇒ "
                    "它们仍是不可调用的"
                )

    def for_role(self, role: str) -> list[ToolSpec]:
        """某个角色能用的工具。

        ## ⚠️ 只读角色在这里被结构性地剥掉两类工具

        `roles` 是手工声明的，而"哪些角色是只读的"是一条设计约束。
        靠"每个工具作者都记得不把 H 写进 roles"来维持这条约束是不成立的 ——
        实测就发生过：`table.*` / `fs.*` 把所有角色都写进了 `roles`，
        于是按角色装配出来的"审校者 H 的工具面"里出现了 `table.update`、
        `fs.write`：H 手里有能改 `documents.claims` 的刀，
        而"H 只读"正是"发现问题"与"掩盖问题"能被区分开的前提。

        所以这里做一件工具作者无法绕过的事：对 :data:`READ_ONLY_ROLES`，
        无论 spec 怎么声明，一律过滤掉（1）有写副作用的工具与
        （2）`external == "exec"` 的工具。

        第二类的理由与第一类同族：只读角色的语义是"它在结构上不能改世界"，
        而执行一个由调用方决定内容的程序改变了世界（它能写工作区、能出网、
        能起更多进程）—— 所以它与"能改表"一样，不属于只读角色的能力面。
        唯一的例外是沙箱被声明为可用（"沙箱承接了这次执行"是一条结构性保证，
        而不是"这个工具变安全了"）；放行同样留痕。

        被过滤掉的名字记在 :attr:`role_filter_notes` 里 —— 之所以要留痕，是因为
        "某个工具本该给 H 却是写工具"是一个声明错误，静默过滤会让它永远
        发现不了（而"静默"正是本项目最忌讳的失败形态）。

        ## 它与"可调用面"的关系（`P-14` 之后必须说清）

        本方法返回的是工具面：这个角色声明能拿到什么。`call` 的判据用的是
        可调用面：它还多出 :data:`READONLY_CALL_EXCEPTIONS` 里逐条登记的
        落库代理（今天只有 `H` 的三个 `review.*`）。两个集合刻意分开命名、
        分开产生：把代理混进工具面会让 `docs/ROLE-SPECS.md` §H.4 的条数与清单漂移，
        而把工具面收窄成"可调用面"会把 H 的落库能力一起砍掉。
        本方法的行为不因 `P-14` 改变任何一个字节。

        ## `roles-4`：留痕必须**幂等**（每次重算，不是每次追加）

        旧实现是 `self.role_filter_notes.setdefault(role, []).append(message)` ——
        于是**每调一次就多一条**。实测：把 `SANDBOX_AVAILABLE` 从 `None` 改成 `True`
        再调一次之后，`notes['H']` 里同时留着"剥掉了 2 个工具（含 `probe.exec_read`）"
        与"放行了 `probe.exec_read`"两条 —— **前一条与当前状态相反**。
        按这份留痕写报告的人会把当前工具面写错，而工具面本身是对的、错的是叙述，
        没有第二处能纠正它；条目还会随调用次数线性膨胀。

        现在的口径：**先清掉本角色上一次的留痕，再写当次结果**。
        清的是 `role_filter_notes[role]` 整个列表 —— 那些条目全部来自本方法的同一次重算
        （`_role_surface` 的拒绝/放行，加上装配期那几条"代理没装进来"），
        所以重算一次就是它们的完整答案；留着旧的只会自相矛盾。
        """
        # `roles-4`：重算而不是追加。放在调用 `_role_surface` 之前。
        #
        # `R4-2`（第一次重审实测的修法）：**只清掉本方法自己上一次写的那几条**。
        # 留痕有**两个来源**：
        #   - `_role_surface` 的重算（本方法写的）—— 每次清掉重写，这是 `roles-4` 的幂等要求；
        #   - **装配期** `scoped_to` + `_attach_registered_writers`（"已登记的落库代理没有
        #     装配进这张表"那几条）—— 它们描述的是**装配事实**，不是本方法的重算结果。
        # 旧版一句 `self.role_filter_notes.pop(role, None)` 把整个列表清空，
        # 于是先 `scoped_to("H")` 再 `for_role("H")` 时那几条**被抹掉**：
        # 事实没有变（代理仍然没装进来），记录却没了。而 docstring 当时那句
        # "那些条目全部来自本方法的同一次重算"是**假的**（重审逐字点名）。
        self._drop_own_role_notes(role)
        surface, notes = self._role_surface(role, filter_readonly=True, call_surface=False)
        for message in notes.get(role, []):
            self._add_surface_note(role, message)
        return surface

    def _drop_own_role_notes(self, role: str) -> None:
        """清掉本表**上一次由 `_role_surface` 重算写入**的留痕；装配期那几条留着。"""
        kept = [m for m in self.role_filter_notes.get(role, []) if not m.startswith(_SURFACE_NOTE_TAG)]
        if kept:
            self.role_filter_notes[role] = kept
        else:
            self.role_filter_notes.pop(role, None)

    def _add_surface_note(self, role: str, message: str) -> None:
        """写一条**重算来源**的留痕（带标记，便于 `_drop_own_role_notes` 精确清理）。"""
        self.role_filter_notes.setdefault(role, []).append(_SURFACE_NOTE_TAG + message)

    def _role_surface(
        self, role: str, *, filter_readonly: bool, call_surface: bool
    ) -> tuple[list[ToolSpec], dict[str, list[str]]]:
        """按角色裁工具面（`P-14` 的唯一判据实现，`for_role` 与 `call` 共用）。

        返回 ``(保留的 specs, 留痕)``；留痕的键是角色名，值与 `for_role` 记进
        :attr:`role_filter_notes` 的那两句逐字相同。抽出来的理由是 `P-14` 的
        硬要求：`for_role` 与 `call` 必须调用同一个私有谓词，不许在 `call`
        里另写一遍"哪些算写工具"的名单（那是 `FC-03` 禁止的第二份实现）。

        `filter_readonly` 只用来让 `call` 的离线检查构造一个"不剥离"的临时表
        （见 `_callable_for` 的注释）；两条判据本身逐字相同，不分叉。
        """
        from . import READ_ONLY_ROLES, SIDE_EFFECTS_WRITE  # 局部导入避免模块级循环

        out: list[ToolSpec] = []
        refused: list[str] = []
        allowed_by_sandbox: list[str] = []
        allowed_by_exception: list[str] = []
        for s in self._specs.values():
            if role not in s.roles:
                continue
            if filter_readonly and role in READ_ONLY_ROLES:
                # 2026-10-17（业主裁定「方案 1」）：**该角色自己的落库代理放行**。
                # 写面钉死在 `READONLY_CALL_EXCEPTIONS[role]` 那张逐条登记的表里
                # —— 它不是"放宽只读"，而是"只读角色的写只允许这几个落点"。
                _exempt = {_n for _n, _w in READONLY_CALL_EXCEPTIONS.get(role, ())}
                if s.side_effect in SIDE_EFFECTS_WRITE:
                    if s.name in _exempt:
                        allowed_by_exception.append(s.name)
                    else:
                        refused.append(s.name)
                        continue
                if s.external == "exec":
                    if SANDBOX_AVAILABLE is True:
                        # 放行也要留痕：否则"为什么 H 拿到了一个 exec 工具"在报告里不可见
                        allowed_by_sandbox.append(s.name)
                    else:
                        refused.append(s.name)
                        continue
            out.append(s)
        notes: dict[str, list[str]] = {}
        if refused:
            notes.setdefault(role, []).append(
                f"按只读角色约束剥掉了 {len(refused)} 个工具（写副作用 或 external=exec）："
                f"{sorted(refused)}"
                "（这些工具的 roles 声明里包含了只读角色，属于声明错误；"
                "行为上已被拦下，但声明本身应改）"
            )
        if allowed_by_sandbox:
            notes.setdefault(role, []).append(
                f"沙箱已声明可用（SANDBOX_AVAILABLE=True），因此放行了 {len(allowed_by_sandbox)} 个 "
                f"external=exec 的工具：{sorted(allowed_by_sandbox)}"
                "（承接执行的是沙箱，不是'这个工具变安全了'）"
            )
        if allowed_by_exception:
            notes.setdefault(role, []).append(
                f"按业主裁定「方案 1」放行了 {len(allowed_by_exception)} 个**该角色自己的落库代理**："
                f"{sorted(allowed_by_exception)}（写面钉死在 READONLY_CALL_EXCEPTIONS[{role!r}] 里）"
            )
        if call_surface:
            # `call` 的判据与 `for_role` 的唯一差别：可调用面还包含逐条登记的落库代理。
            # 只有在角色命中 `READONLY_CALL_EXCEPTIONS` 时才可能多出东西。
            from . import ROLES  # noqa: PLC0415 - 与上面同一个局部导入的理由

            registered = {s.name for s in out} if role in ROLES else set()
            for name, _why in READONLY_CALL_EXCEPTIONS.get(role, ()):
                if name in registered or name not in self._specs:
                    continue
                out.append(self._specs[name])
                registered.add(name)
        return out, notes

    def _callable_for(self, spec: ToolSpec, role: str | None, *, include_registered_writers: bool) -> str | None:
        """`P-14` 的唯一判据：这个角色能不能调这个 spec？

        返回 ``None`` 表示"可以"，否则返回拒绝理由（两处拒绝都必须给理由，
        不许静默放行 —— "没写"不等于"允许"）。

        ## 谁走这里（`roles-1`：这句话此前是错的）

        **只有 `call` 走这里。** `for_role` 直接调 `_role_surface(..., call_surface=False)`，
        从不经过本函数。旧 docstring 逐字写着"`for_role` 与 `call` 都走这里"，
        而全仓库唯一的真调用点（`call` 里那一处）传的是 `include_registered_writers=True`
        ⇒ 本函数里 `include_registered_writers=False` 那一支是**死代码**
        （没有调用方，也没有测试），而按那句文档去理解两个面的差别，
        恰好是 `P-14` 之后最容易搞错的地方。

        判据本身仍然只有一份：`for_role` 与 `call` 都落在 `_role_surface` 上
        （那是 `FC-03` 的要求），本函数只是 `call` 侧"把理由说清"的那一层。

        三态判定顺序（每一步都要有理由，见 `call` 的 docstring）：

        1. `self.bound_role is None and role is None` ⇒ 拒（调用方没声明自己是谁）；
        2. `self.bound_role is not None and role is not None and role != self.bound_role`
           ⇒ 拒（拿一个已绑定注册表的身份去冒充另一个角色）；
        3. 该 spec 不在可调用面里 ⇒ 拒，理由里逐字给出角色名与工具名。

        第 3 步内部的分支只用来把理由说清，判据本身只有 `_role_surface` 一份：
        先把同一张表按"不剥离"裁一次（`filter_readonly=False`），于是
        "在你的角色面里，但它被只读约束剥掉了"与"它压根不在你的角色面里"
        是两句不同的拒绝理由 —— 调用方拿到的不是一句"不行"。
        """
        if self.bound_role is None and role is None:
            return (
                f"调用方没有声明角色，无法判定它能不能调 {spec.name!r}（只读角色的刀不许靠"
                "'没写'来拿）。请传 role=<角色名>，或在装配期用注册表的 scoped_to(role) 绑定角色"
            )
        if self.bound_role is not None and role is not None and role != self.bound_role:
            return (
                f"调用方声明了 role={role!r}，而这张注册表绑定的是 {self.bound_role!r} —— "
                f"不许用一个已绑定注册表的身份去冒充另一个角色（工具 {spec.name!r}）"
            )
        eff = role if role is not None else self.bound_role
        assert eff is not None  # 上面第 1 条已经挡住了"两边都没有"的情形
        surface, _ = self._role_surface(eff, filter_readonly=True, call_surface=include_registered_writers)
        if any(s.name == spec.name for s in surface):
            return None
        declared, _ = self._role_surface(eff, filter_readonly=False, call_surface=False)
        if any(s.name == spec.name for s in declared):
            return (
                f"角色 {eff!r} 拿不到工具 {spec.name!r}：它声明了 {eff!r}，但只读角色的结构性"
                f"过滤把它剥掉了（写副作用 或 external=exec 且沙箱未声明可用）"
            )
        if spec.name in {n for n, _ in READONLY_CALL_EXCEPTIONS.get(eff, ())}:
            return (
                f"角色 {eff!r} 拿不到工具 {spec.name!r}：它在已登记的只读例外表里，"
                f"但这张注册表里没有注册它 —— 例外只对显式装配了落库代理的注册表生效"
            )
        # `roles-1`：这里曾经还有一支 `if not include_registered_writers ...` 的拒绝理由。
        # 它是**死代码** —— 全仓库唯一调用点传的是 `True`，没有测试覆盖它，
        # 而留着它会让人以为 `for_role` 也受这个开关影响（`for_role` 根本不走本函数）。
        # 删掉而不是留着：一条永不执行的判据分支，读起来与"有第二条判据"没有区别。
        #
        # 参数 `include_registered_writers` 保留：它真正的作用在**上面**那句
        # `_role_surface(..., call_surface=include_registered_writers)` 里
        # （可调用面是否包含已登记的落库代理），那一句是活的。
        return f"角色 {eff!r} 拿不到工具 {spec.name!r}：它不在这个角色的可调用面里"

    def describe(self) -> list[dict]:
        return [self._specs[n].to_dict() for n in self.names()]

    def function_schemas(self, role: str | None = None) -> list[dict]:
        specs = self.for_role(role) if role else list(self._specs.values())
        return [s.to_function_schema() for s in sorted(specs, key=lambda x: x.name)]

    def text_catalog(self, role: str | None = None) -> str:
        """给 LLM 看的纯文本清单（比 JSON 省 token，也更容易被读进去）。"""
        specs = sorted(self.for_role(role) if role else self._specs.values(), key=lambda s: s.name)
        lines = [f"可用工具（{len(specs)} 个）："]
        for s in specs:
            flag = " ⚠需审批" if s.needs_approval else ""
            lines.append(f"- {s.name}({', '.join((s.params.get('properties') or {}).keys())}){flag}")
            lines.append(f"    {s.summary}")
            if s.returns:
                lines.append(f"    返回：{s.returns}")
        return "\n".join(lines)

    # ---- 调用
    def call(
        self,
        name: str,
        args: Mapping[str, Any] | None = None,
        *,
        role: str | None = None,
        budget: "ContextBudget | None" = None,
        spill_root: "str | Path | None" = None,
        **params: Any,
    ) -> ToolResult:
        """调工具。`budget=None`（默认）时行为与加 FC-17 之前逐字节一致。

        ## `role`：只读约束现在是调用期强制（`P-14`）

        `role` 是关键字参数，默认 `None` 表示"调用方没说自己是谁"，
        而 `None` 一律被拒（fail-closed）—— 三条判据见 :meth:`_callable_for`：

        1. 既不绑定角色、又不传 `role` ⇒ 拒（"只读角色的刀不许靠'没写'来拿"）；
        2. 绑定的是 A、传的是 B ⇒ 拒（不许用一张注册表的身份冒充另一个角色）；
        3. 最终生效角色 = `role or self.bound_role`；该工具不在这个角色的
           可调用面里 ⇒ 拒，理由里逐字给出角色名与工具名。

        为什么这对只读角色是决定性的：`for_role` 的过滤只在装配路径上成立，
        任何拿到完整注册表的路径都能调写工具，而没有任何东西会红（这就是
        `P-14` 记的那条洞）。判据下沉到调用期之后，"拿到注册表"不再等于
        "拿到该角色的刀"。

        ## `args` 与 `params` 两种写法（`params` 优先于 `args`）

        工具参数既可以作为映射整体传入（`call("fs.read", {"path": "a.txt"})`），
        也可以逐名传入（`call("fs.read", path="a.txt")`）—— 后者是本仓库既有的
        主流写法，逐处改成映射会动到 300+ 个调用点。两者同时给时逐名的那一份赢
        （显式关键字是更具体的意图）。

        ## 为什么 `budget` 必须是关键字且默认为 None

        FC-17 要求"上下文预算三件套必须开"，但把它做成自动生效会让既有调用方
        拿到的返回值悄悄变短 —— "没开剪枝"与"开了没超阈值"就再也分不开了。
        所以这里只在显式传入 `budget` 时才剪枝：
        `registry.call("fs.read", path=..., budget=b)`。

        ## ⚠️ `budget` 的名字冲突（真实存在，不是假想）

        `attack.check_budget` / `attack.create_plan` 自己就有一个 `budget` 参数
        （FC-18 的四维预算）。为了不把它们的参数吞掉，消歧规则是结构性的、
        且只有一条：

        > 若目标工具的 params schema 里声明了 `budget` 属性，则本关键字属于工具；
        > 否则属于上下文预算。

        这条规则读注册表就能判断，没有任何隐藏状态。代价是：对这两个工具，
        一次调用里不能同时传"工具的 budget"和"上下文的 budget" —— 需要剪枝时
        用返回值上的 `ToolResult.pruned(budget, spill_root=...)` 第二步做。

        ## 两个"吞参数"的名字（`role` / `args`）

        工具是 LLM 手写 JSON 的落点，参数名由工具作者定。若某个工具的 schema 里
        真的声明了 `role` 或 `args` 属性，调用方按名传入的那一份必须原样落到工具上
        （`role` 只从位置**上被本方法占用，`args` 在本方法里就地合并、没有单独的绑定步骤）——
        本仓库今天没有任何工具这么做，有测试钉着这一点。

        ## `roles-3`：`role` 这一格的优先级与"身份声明"的关系

        规则一句话：**显式关键字 > 位置映射 > `bound_role`**。

        - 工具声明了 `role` ⇒ 它收下 `role=<显式关键字>`，没给才用位置映射里的那一份；
          身份声明回退到 `self.bound_role`（它本来就该按绑定值判，而不是按 `None`）。
        - 旧实现用 `params.setdefault("role", role)` + `role = None`，于是
          **位置映射里给的 `role` 会被 `params` 里那个 `None` 反向覆盖**（参数静默丢失），
          而拒因还会写成"调用方没有声明角色"（与事实相反：调用方声明了，只是被工具收下了）。
        这两件事都必须留痕：调用日志里会记 `role_consumed_as_param` 与 `identity_role`。
        """
        # 查工具这一步也要在 try 里：工具名写错同样属于"调用方写错了"，
        # 应该返回结构化失败让智能体自己纠正，而不是把它的循环打断。
        try:
            spec = self.get(name)
        except ToolError as e:
            return fail(str(e), tool=name, kind="unknown_tool")

        props = spec.params.get("properties") or {}
        # ---- 同名参数的消歧（规则与 `budget` 同族：schema 说了算）
        #
        # 优先级（`roles-3` 的判据，此前是错的）：**显式关键字 > 位置映射 > bound_role**。
        # 旧实现是两句：
        #     params.setdefault("role", role)   # role=None 时它什么也不写
        #     role = None                       # 然后把身份声明丢掉
        # 于是 `call(name, {"role": "X"})`（位置映射里给了 X、关键字没给）落到
        # `merged.update(params)` 时被 `params` 里那个 `role=None` **反向覆盖** ——
        # 工具收到 `None`，参数**静默丢失**。而它紧接着又把身份声明置空，
        # 导致拒因写成"调用方没有声明角色"，与事实相反（调用方明明声明了）。
        #
        # 现在三件事分开写清：谁被工具收下、身份声明取哪一个、拒因说哪一句话。
        #
        # ⚠️ `R4-1`（第一次重审实测的修法）：位置映射里的 `role` 必须与关键字形态
        # **走同一套判据**。旧版只在 `role is not None`（关键字）时才看它，
        # 于是同一个 `role="H"` 有两种结局：
        #   `call(name, role="H")`      ⇒ `role_denied`（身份判据生效）
        #   `call(name, {"role": "H"})` ⇒ **身份判据被整格跳过**，而且工具真的收到
        #                                 `{'n': 1, 'role': 'H'}` 并返回 ok（宽 schema 下）
        # 改前这两种形态**都**判 `role_denied`，所以这是 `roles-3` 那次修复引入的分叉。
        # 修法：先把位置映射里的 `role` **提升**成一次身份声明（它是同一个语义位置），
        # 再让下面那段唯一的分流去决定"工具收下"还是"当作身份"。
        role_from_args = None
        if args is not None and isinstance(args, Mapping) and "role" in args:
            role_from_args = args.get("role")
        if role is None and role_from_args is not None:
            role = role_from_args
        role_as_param: Any = None
        role_consumed_as_param = False
        if "role" in props and role is not None:
            # 工具自己声明了 `role` ⇒ 这一格属于工具。显式关键字更具体，优先。
            role_as_param = role
            role_consumed_as_param = True
            # 身份声明回退到 bound_role（没有被显式声明过）。
            role = None
        # 3) 工具自己声明了 `budget` ⇒ 调用方按关键字传的映射属于工具（FC-17 的既有规则）。
        budget_as_tool_param = isinstance(budget, Mapping) and "budget" in props

        # ---- `P-14`：调用期角色判据（唯一判据在 `_callable_for`）
        #
        # ⚠️ 传的是 `role`（已被上面置空的那一份），而不是 `role_as_param`：
        # 身份声明与"工具收下的那个同名参数"是两件事，混起来就是 `roles-3` 的第二个形态。
        # 被置空时 `_callable_for` 会回退到 `self.bound_role`（它自己那一行 `eff = ...`）。
        denial = self._callable_for(spec, role, include_registered_writers=True)
        if denial is not None:
            # 被拒的调用**也要留痕**：拒绝理由里会出现"调用方没有声明角色"这句话，
            # 而在"role 被工具收下"的形态下那句话只有靠 `role_consumed_as_param` /
            # `identity_role` 两个字段才能自证。不留痕 ⇒ 读日志的人无法判断
            # 这句话是对的还是在冤枉调用方（`roles-3` 的第二形态就出在这里）。
            if self.log_calls:
                entry = {"tool": name, "params": _safe(dict(args or {})), "ok": False,
                         "error": denial, "kind": "role_denied"}
                if role_consumed_as_param:
                    entry["role_consumed_as_param"] = True
                    entry["identity_role"] = self.bound_role
                self._call_log.append(entry)
            return fail(denial, tool=name, kind="role_denied")

        # ---- 参数合并：位置映射 << 逐名关键字（见 docstring）
        merged: dict[str, Any] = {}
        if args is not None:
            if not isinstance(args, Mapping):
                return fail(
                    f"参数错误：args 必须是映射（object），收到 {_type_name(args)}",
                    tool=name,
                    kind="param_error",
                )
            merged.update(args)
        merged.update(params)
        if role_consumed_as_param:
            merged["role"] = role_as_param

        # ---- FC-17：budget 消歧（见 docstring 的规则）
        if budget_as_tool_param and "budget" in props and "budget" not in merged:
            merged["budget"] = budget
            budget = None
            spill_root = None
        if budget is not None and "budget" in props:
            merged["budget"] = budget
            budget = None
            spill_root = None

        try:
            # 2026-10-17（真机 T1/T4/T5 共 8 次以上）：模型习惯在参数里带 `why`（"我为什么这么调"）。
            # 参数集是封闭的 ⇒ 整份调用被拒，一次真实的写入/检索就白费了。它**不是**工具参数，
            # 但它是审计线索 —— 从参数面剥掉、记进留痕（下面 `entry` 里），不当参数也不丢。
            _why = None
            _props = (spec.params or {}).get("properties") or {}
            if "why" in merged and "why" not in _props:
                _why = merged.pop("why")
            validate_params(spec.params, merged)
        except ParamError as e:
            return fail(f"参数错误：{e}", tool=name, kind="param_error")
        except ToolError as e:
            # `errors-6`：这一支是通用兜底，不是参数校验的路径。
            #
            # 它今天不可达：`validate_params` 的每一条 raise 都是 `ParamError`
            # （见该函数的全部 raise），而 `ParamError` 是 `ToolError` 的子类，
            # 所以上面那一支总是先接住。
            # 保留它的唯一理由是"将来 validate_params 抛出别的受控类型"，
            # 而此时正确的 kind 仍然是 param_error —— 我们正处在参数校验这一阶段，
            # 失败归因就是调用方给的参数。
            #
            # 原实现把这一支标成 kind="unknown_tool"，那是一个与参数无关的类别
            # （unknown_tool 的语义是"工具名不认识"），一旦这一支真的可达，
            # 凡是按 kind 分类处置的下游都会走错分支去查工具注册表。
            # 消息里带上异常的真实类型名，是为了让"这一支真的被走到了"这件事
            # 在报告里看得见（它意味着 validate_params 的契约变了）。
            return fail(
                f"参数校验期的受控失败（{type(e).__name__}，不是 ParamError）：{e}",
                tool=name,
                kind="param_error",
            )
        try:
            out = spec.handler(**merged)
        except ToolError as e:
            out = fail(str(e), tool=name, kind="tool_error", detail=e.detail)
        except (TypeError, AttributeError) as e:
            # 2026-10-17（子代理 tools 根因 A，17 个站点）：可选参数**显式传 null** 时校验器
            # 把它当"没提供"放行，而 handler 按"一定有值"写 ⇒ 崩成 `kind="unexpected"`
            # （读账的人只看到"库内部出错"）。这里把"有 null 且崩了"翻成**可行动的拒信**，
            # 而**不改**校验语义 —— 于是 `attack.list_plans` / `review.scan_document`
            # 这类"null 本身有意义"的参数不受影响（它们不崩）。
            _nulls = sorted(k for k, v in (merged or {}).items() if v is None)
            if _nulls:
                out = fail(
                    f"参数错误：{_nulls} 收到了 null，而这个工具不接受空值 —— "
                    f"要么给它一个值，要么干脆别传这些键"
                    f"（原始异常：{type(e).__name__}: {e}）",
                    tool=name, kind="param_error")
            else:
                out = fail(f"{type(e).__name__}: {e}", tool=name, kind="unexpected")
        except Exception as e:  # noqa: BLE001
            out = fail(f"{type(e).__name__}: {e}", tool=name, kind="unexpected")
        res = out if isinstance(out, ToolResult) else ok(out)
        # ---- FC-17：算出有效的上下文预算
        #
        # 优先级：显式传入的 `budget` > 注册表的 `default_budget`。
        # 但有一个例外必须保留：若目标工具自己声明了 `budget` 参数，
        # 那么"默认预算"对它不适用 —— 否则 `attack.create_plan` 会在调用方
        # 什么都没传的情况下，被塞进一个它根本不认识的 `ContextBudget` 对象。
        # 这条与上面消歧规则是同一句话的两半。
        eff_budget = budget if budget is not None else self.default_budget
        if eff_budget is not None and "budget" in props:
            eff_budget = None
        if eff_budget is not None:
            eff_spill = spill_root if spill_root is not None else self.default_spill_root
            res = res.pruned(eff_budget, spill_root=eff_spill)
        # `default_budget=None` ⇒ 什么都不做 ⇒ 与加 FC-17 之前逐字节一致。
        if self.log_calls:
            # `roles-3` 要求"身份声明被让给工具"这件事**留痕**：否则只读拒因无法自证
            # （调用方看到"你没有声明角色"，而它其实声明了，只是被工具的参数收下了）。
            entry = {"tool": name, "params": _safe(merged), "ok": res.ok, "error": res.error}
            # 2026-10-18（缺陷 ⑬，根因）：这一段原来**掉在 `if self.log_calls:` 外面** ——
            # `entry` 只在上面那一支里赋值，于是**生产默认 `log_calls=False` 时，
            # 任何带 `why` 的调用都会 UnboundLocalError**。真机三处报错全是它：
            # `table.create`（D 写 research_questions，idx 5/6/8）、`review.verify_fixes`
            # （H 复审）、以及 M 在验收表里误记成 `search.download` 的那一条。
            # 现在 `entry` 的**全部**使用都在同一支里，`log_calls=False` 时什么都不碰。
            if _why:
                entry["why"] = str(_why)[:400]
            if role_consumed_as_param:
                entry["role_consumed_as_param"] = True
                entry["identity_role"] = self.bound_role
            self._call_log.append(entry)
        return res

    def call_log(self) -> list[dict]:
        return list(self._call_log)

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, name: object) -> bool:
        return name in self._specs


def _safe(value: Any) -> Any:
    """把参数里不可 JSON 化的部分替换掉，保证调用日志能落盘。"""
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return value
    except (TypeError, ValueError):
        if isinstance(value, Mapping):
            return {k: _safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_safe(v) for v in value]
        return repr(value)[:200]


def spec_from_dataclass_fields(title: str, fields: Mapping[str, str], required: Iterable[str] = ()) -> dict:
    """构造 object schema 的小工具（供各工具模块声明参数用）。"""
    return {
        "type": "object",
        "properties": {k: {"type": v} for k, v in fields.items()},
        "required": list(required),
        "additionalProperties": False,
    }
