"""工具层基座：ToolSpec / ToolResult / ToolRegistry / 参数校验。

## 为什么要有一层"工具"

A/B 若直接调 `store`、`providers` 的函数，一旦智能体由 LLM 驱动就不够了：

- LLM 需要"手写 JSON 去改表" → 一次转义错误就写坏数据，而且每改一行都占一轮思维链；
- 没有统一输入校验 → 参数错了要到深处才炸；
- 没有统一的副作用声明 → 无法判断某个动作要不要审批；
- 同一套能力在"脚本模式"和"LLM 模式"下要写两遍。

工具层把"标准操作"固化成有名字、有 schema、有校验、有结构化返回、声明副作用的原子动作。
智能体的思维链只花在"判断该调哪个工具"，不花在"怎么把参数拼对"。

## 两个刻意的设计

1. 两根轴都是一等公民。`none` / `read` 的工具可以任意调用、不需要审批；`write_local`
   的需要。把审批判断建立在声明上，而不是靠人记。这也是为什么 C 的图分析全部是
   `read` —— 它应当能被任意组合地反复查询。

   本层还声明第二根正交轴 `external`（见 `EXTERNAL`）：`side_effect` 把"能不能改我们
   拥有的东西"与"能不能触到我们不拥有的东西"压进了同一个取值，于是
   `verify.run_experiment`（既写实验记录、又执行调用方给的脚本）在一根轴上必须二选一，
   另一个事实被丢掉。两根轴的取值互相独立，审批（`needs_approval`）与沙箱
   （`sandbox_required`）由它们推导，不落成逐工具的布尔字段（`DEVELOPMENT.md` §3
   纪律 6：派生态不许当输入）。`network` 这个把两根轴压成一档的遗留取值已从词表里
   删掉，连同两张翻译表；装配期再写它就是一个非法取值（`ValueError`），于是
   "出网"与"起进程"在树上各说各的话，不需要任何翻译层。

2. 参数校验自己实现，不引第三方依赖。只需要 object/array/string/integer/number/boolean
   与 required/enum/items/bounds 这几样；为此引入 `jsonschema` 会让"工具层能不能用"
   依赖于环境里有没有装它。工具层是所有智能体的公共底盘，它的依赖越少越好。
"""

from __future__ import annotations

import difflib
import inspect
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping, Sequence

#: 工具面三段的真身（只依赖标准库 ⇒ 提示词层也能安全 import 同一份渲染）。
from ..toolface import (
    FACE_EXAMPLE_MAX,
    FACE_LABELS,
    FACE_SCENARIO_MAX,
    FACE_SEP,
    FACE_SUMMARY_MAX,
    face_budget_problems,
    face_segments,
    face_text,
    face_units,
)

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查；运行期不导入（避免模块级耦合）
    from pathlib import Path

    from ..contextbudget import ContextBudget

#: 副作用等级（第一根轴的历史名称，也是声明轴本身）。顺序即"危险程度"，便于比较。
#: `network` 已删掉：它把两根正交轴压成一根（"出网"与"起子进程"同档），连同两张翻译表
#: （`LEGACY_SIDE_EFFECTS` / `LEGACY_EFFECTS_BY_TOOL`）一起消失。与 `capabilities.SIDE_EFFECTS` 是同一个
#: 原子改动（`capabilities.assert_capabilities` 第 5 条：两处必须逐字相等，只删一处会导入期就炸）。
#: 本词表是"哪些等级算写"的另一半 —— 只读角色 C/H 的剥离（`for_role` / `call` /
#: `_callable_for` 共用的 `_role_surface`）读的是装配层那张 `SIDE_EFFECTS_WRITE`，不是本元组。所以往这里
#: 加取值时必须同时决定它落在 `SIDE_EFFECTS_WRITE`（会被剥离）还是 `_NON_WRITE_EFFECTS`（不会）：这条二分
#: 由 `tools/__init__.py` 的 `_check_write_levels_are_registered()` 在导入期断言。
SIDE_EFFECTS = ("none", "read", "write_local")

#: 第一根轴：能不能改我们拥有的东西（数据表 / 工作区）。
EFFECT = ("none", "read", "write_local")

#: 上面两份字面量是同一个轴的两个名字，这里在导入期钉住它们不许分叉。
#: 为什么需要这条断言（而不是靠"它们现在相等"）：`ToolSpec.__post_init__` 用 `SIDE_EFFECTS` 挡非法
#: 取值，而对外声明的轴值是 `EFFECT`（`capabilities` 与测试读它）。两个名字之间的相等只靠
#: `capabilities.assert_capabilities` 各留一份来传递维持 —— 那是脆的。
#: 还有一个更容易骗人的事实：今天 `EFFECT is SIDE_EFFECTS` 为真，但那不是契约，而是同一个代码对象里
#: 两个等值常量被编译期折叠的巧合；给任一份加一个取值、或换个解释器，这个巧合就没了，而分叉不会红
#: （于是会出现"某取值通过了构造期校验、却不在对外声明的轴值里"）。断言放在模块级，两种改法都会在
#: import 那一刻就炸。
assert EFFECT == SIDE_EFFECTS, (
    f"base.EFFECT={EFFECT} 与 base.SIDE_EFFECTS={SIDE_EFFECTS} 不同 —— "
    "副作用是第一根轴，同一根轴的两份取值清单必须逐字相等；"
    "只改一处会让构造期校验与对外声明说的是两根不同的轴，而那是静默的"
)

#: 第二根轴：能不能触到我们不拥有的东西（`none` 触不到 / `egress` 出网 / `exec` 在宿主上执行一个
#: 由调用方决定内容的程序）。
#: 取值清单有两份字面量，不是一份：`capabilities.py` 在模块层各写了
#: 一份 `SIDE_EFFECTS` / `EFFECT` / `EXTERNAL` 字面量（刻意不写行号：行号会过期，本仓禁改区清单的
#: 理由守的正是同一条纪律 —— 写符号名），且它自己的注释逐字写了「为什么刻意不 import」（它是更底层的
#: 声明层，要能被 `verify` 与 CLI 单独读）。所以准确的说法是：「两处各有一份字面量，由导入期断言钉住
#: 它们不许分叉」（`capabilities.assert_capabilities` 的交叉断言；新增一根轴沿用同一种形态）。「落点也必须
#: 知道有两个」：本文件在禁改区清单里，`capabilities.py` 「不在」清单里 —— 后者是这条登记的影响面：放宽
#: 词表可以只改不受保护的那一份，而只改一处会在导入期炸、两处不一致则两处描述不同的轴。
EXTERNAL = ("none", "egress", "exec")

#: 六件套里"必须由 `ToolSpec.__post_init__` 校验"的那几件：`name` / `summary` / `params` /
#: `side_effect` 的校验是无条件的（见 :meth:`ToolSpec.__post_init__`），`roles` 是结构性的（必须是元组）。
#: `roles` 必须是元组：`tuple` 是 roles 契约的一半（另一半 `role in ROLES` 由
#: `ToolRegistry._reject_unknown_roles` 管），所以 `__post_init__` 里那道
#: `isinstance(self.roles, tuple)` 不是"多一条判据"。
#: `returns` 是唯一的例外：非空校验会命中 `src/agentflow/agent_d.py` 里三个内置降级替身工具
#: （`trace.relation` / `trace.concept` / `trace.literature`）。口径是：`returns` 必须给且必须是
#: 字符串（空串 = 你确认过它没有可声明的返回形态），"别忘了写"由 `DEVELOPMENT.md` §4.3 第 1 项的
#: census 观察；修掉它只需给那三个替身补 `returns=`（不涉行为）。
REQUIRED_NON_EMPTY_FIELDS: tuple[str, ...] = ("name", "summary", "params")

# ---------------------------------------------------------------- 工具面三段
#
# 业主 2026-11-22 指令（逐字）：「角色不需要知道工具的具体实现，只需要知道工具能干什么
# 以及怎么用工具，具体实现的描述仅可保留在代码注释」。落到工具面上就是**三段**：
#
#   ① 能力（`summary`）   这个工具做什么、产出什么、边界在哪；
#   ② 场景（`scenario`）  什么时候该用它（而不是别的那一件）；
#   ③ 案例（`example` + `example_code`） 一条真实调用 + 它会回什么。
#
# 三段**都不许**出现实现细节：内部模块名 / 私有函数名 / 算法名 / 内部存储布局
# （哪张表、哪个中间文件、"它其实调了 X"）。那些只留在 handler 的代码注释里 ——
# 模型读的是能力与用法，读实现既用不上，又会把"设计"误当成"契约"。
#
# 渲染与字数口径的真身在 `agentflow/toolface.py`（提示词、function-calling、本层
# 三处读者共用它）；名字在文件头的 import 块里再导出，免得"改一处、另两处没跟上"。


#: 沙箱可用性（三态）。`DEVELOPMENT.md` §3 纪律 1：把"没声明沙箱"与"声明了正在用"折叠成同一个布尔，
#: 正是三态纪律禁止的形态。`True` = 已声明可用（起进程/出网由它承接）；`False` = 已声明不可用（这才是
#: "升级为人工审批"的判据）；`None` = 未声明（默认，与 `False` 等价地保守，但报告里必须能分开：一个是
#: "我们查过、没有沙箱"，一个是"我们没说过"）。
#: `True` 这一档在「当前环境里不可达」（如实登记，不是"三种取值都在用"）：全仓库对它的出现只有
#: 四类（上面这个定义、`tools/__init__.py` 里一个未使用的导入、下面的读取点、测试里的 `monkeypatch`），
#: 「没有任何配置或装配入口」。后果：`_role_surface` 的 `external == "exec"` 放行分支与 `allowed_by_sandbox`
#: 留痕在生产里「永不发生」，`needs_approval` 里"沙箱可用所以被承接"那一支恒假 ⇒ 「任何
#: `external != "none"` 的工具在任何环境下都需要审批」。补齐入口的代价：模块级可变全局会让同进程
#: 两张注册表的审批面不同，该值应挪进 `ToolRegistry` 实例（待人裁）。
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
#: ## 为什么需要这张表
#: `ToolRegistry.for_role` 把只读角色（`C` / `H` / `V`）的工具面剥掉一切写工具，而设计允许每个只读角色
#: 有一处**自己的**写入面：H 的落库代理（`review_findings` + `documents.status`）、C 的产出登记通道
#: （`analysis_reports`），以及 V 自己维护的凭据台账（`verifications/<号>.jsonl`）与它颁的签。
#: 这些都不走"往 `roles` 里塞只读角色"那条路（那条路会被 `_role_surface` 剥掉，且留痕点名声明错误）：
#: 它们只由本表逐条产生，于是"为什么这个只读角色能调这个写工具"永远是**一处、逐条、带理由**的登记。
#: 调用期强制一旦生效，"工具面"与"可调用面"就必须分开命名，否则 `for_role("H")` 不许多出
#: `review.review_document` 与"H 的落库代理必须仍能调它"会互相打架。所以第二个集合只允许由这张显式
#: 登记表产生 —— 没有第二条产生路径。
#: ## 单一来源
#: `agent_h._H_WRITABLE_TOOLS` 曾是同一件事的第二份名字，现在从本表派生（改这里就是改那里）；每条理由必须
#: 逐字说清"为什么这个只读角色能调这个写工具，它写的是自己的什么"，写不出理由就该改代码而不是加例外。
#: `role_filter_notes` 的条目有「两个来源」（重算 / 装配期），重算来源的带一个标记前缀，重算时只清带
#: 标记的 —— 不另开一个字典，因为消费方（`scripts/release_check.py` 的 fail 说明、
#: `docs/ROLE-SPECS.md`）读的是「一个列表」，拆开会漏读。
_SURFACE_NOTE_TAG = "［工具面重算］"
READONLY_CALL_EXCEPTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    # C：一个写入面（"只读角色的产出要能进台账"）。
    # `analysis.register_report` 是 C 自己的「产出登记通道」：把这一趟算出来的图读数 / 结构洞 / 候选缺口
    # 登记进 `analysis_reports`（复用 `agent_c._support.AnalysisReport.persist`，不另写落盘实现）。
    # 为什么必须有：C 的动作（`gaps` / `handle` / `paths` / …）不在 C 的工具面上（只能由父代理 `summon`）
    # ⇒ 被派空动作的自由任务里 C 手上没有写工具，图读数只能写进回复。表级例外
    # （`capabilities.READ_ONLY_WRITE_EXCEPTIONS["C"]`）早登记了 `analysis_reports`，缺的正是这一件
    # 「工具」。判据三条：(1) 工具面仍全量只读（这一件是唯一的写，`roles=("C",)`）；(2) 写的是「成品报告
    # 的登记行」不是知识表（由 `tests/test_readonly_output_channel.py` 用"全表行数前后不变"守）；(3) 每行带
    # `kind`（受控词表）与 summary。
    "C": (
        (
            "analysis.register_report",
            "C 的产出登记通道：把这一趟它算出来的分析落成 analysis_reports 一行"
            "（产出即登记）。C 的动作面只能由父代理 summon 唤起 ⇒ 没有这一件时，"
            "空动作的自由任务里 C 手上一件写工具都没有，图读数只能写进回复"
            "（projects/mp3 末节第 5 条：analysis_reports = 0）。只写这一张表，"
            "不碰 claims / literature / relations",
        ),
        (
            "analysis.edit_report",
            "C 修订自己交过的那一份报告（业主 2026-11-27：「C 需要对自己的分析报告"
            "负责，需要核实证明链走通且逻辑自然，如遇不合理的地方需要 edit 这个报告」）。"
            "登记是一次性的，而报告交出去之后 C 还会拿读数回头核它 —— 没有这一件时"
            "「我发现自己的报告写错了」在工具面上没有出口，只能写进回复，报告照旧错着"
            "躺在 analysis_reports 里等 D 去读。三条边界把写面钉在同一张表上："
            "只改 created_by 归一等自己的那一行（别人的报告受控拒）、`reason` 必填"
            "（没理由不改）、留痕 `analysis_tools.AMENDMENTS_KEY` 那格追加式（改前 / 改后 / 谁 / 何时 "
            "都在行上，rebuild 后读得回来）。不碰 statements / dependencies / 任何知识表",
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
    # V：为什么只读角色 V 需要一件写工具 —— 它的产物**只能经它自己那张台账落盘** ——
    # `verifications/<命题号>.jsonl`（追加式，`verifications.record_verification`）、未在册档的签
    # 信封 `out/vsigns/<正文 sha>.json`（`vsigns.issue`），以及由收方秘书按台账把签块盖回送审的那份
    # 手稿（`vsigns.land`；V 这边没有直接写稿的口）。没有这一件，V 的判定就无处可落 ——
    # 而"审了没处记"与"没审"在读数上分不开。
    # 边界（这句是这一条例外的全部内容）：V 只写自己维护的那张表与自己的凭据产物，不改别人的东西。
    # 它不写任何数据表的正文或结论（`WRITE_SETS["V"]` 仍是空集）；命题行上五元位第 3 位那一格
    # 由 B 收录时按正文 sha 认领（V 不写 `statements`，所以不在本工具的表写集里，
    # `TOOL_WRITE_SETS["verify.verify_proof"] == frozenset()` 记的就是这个事实）；它不改别人的稿
    # （`fs.write` / `fs.edit` 不在 V 的工具面上），也不写 `experiments`。
    # 判据：`tests/test_v_writes_only_its_own_ledger.py`（正控真跑一次落台账；负控 C/H 与"改别人的表"
    # 仍受控拒绝；反真空摘掉这一条 ⇒ 工具从 V 面上消失）。
    "V": (
        (
            "verify.verify_proof",
            "V 写的是**它自己维护的那张表**（verifications/<命题号>.jsonl）与**它颁的签**"
            "（out/vsigns/<正文 sha>.json、收方秘书按台账落回送审手稿的签块）——"
            "判定必须有落点，否则「审了没处记」与「没审」在读数上分不开。"
            "它不改别人的东西：不写 statements / experiments 的正文与结论、"
            "不改别人的稿（命题行上第 3 位那一格由 B 收录时翻，不在这件工具的表写集里；"
            "V 不写 statements）。"
            "`for_role('V')` 仍把其余一切写工具剥掉；这一件是 V 面上唯一的例外",
        ),
    ),
}


# ---------------------------------------------------------------- 只读角色写面读数（三档）

#: `_role_surface` 写「已登记放行」留痕时用的那两句原话。
#: 消费方（`cli tools` 的「声明需要纠正」告警行）必须把它们从"要改的声明"里撇掉 ——
#: 它们描述的是"已经逐条登记过的放行"，不是"工具作者把写工具声明给了只读角色"。
#: 落成常量而不是让每个消费方按"看着像"另写一份子串判断：文案一改，干净树上就会
#: 重新冒出一条假的"声明需要纠正"，而没有任何判据会因此变红。
_ALLOWANCE_NOTE_EXCEPTION = "按业主裁定「方案 1」放行了"
_ALLOWANCE_NOTE_UNIVERSAL = "按通用能力放行了"

#: 「已登记放行」留痕的两个前缀：`_role_surface` 生成它们、`surface_note_problems` 撇掉它们。
ALLOWANCE_NOTE_MARKERS: tuple[str, ...] = (_ALLOWANCE_NOTE_EXCEPTION, _ALLOWANCE_NOTE_UNIVERSAL)


@dataclass(frozen=True)
class ReadonlyWriteSurface:
    """一个只读角色工具面的写工具读数：三档，逐档都能打印。

    ## 为什么要把它抽出来（SYSINTRO 2026-11-21 钉的缺陷）

    "这个只读角色手里有没有刀"这同一件事，此前有两套数法：`cli tools` 按"面里有没有
    `write_local`"数，而权威判据（`tests/test_tools_readonly_roles.py`）先减掉两处登记
    （`READONLY_CALL_EXCEPTIONS` / `UNIVERSAL_TOOLS`）再断言。干净树上两套数法给出相反
    的结论 —— 一件也没多，CLI 却印 `!! 有泄漏`，而 CLI 正是人看的第一读数。数法收成
    这一处（`readonly_write_surface` 是唯一实现），CLI 与判据读同一个函数。

    ## 三档（`verdict` 的取值）

    - `"leak"`：面上有「未登记」的写工具 —— 真问题，CLI 打 `!!`；
    - `"registered"`：面上的写工具全部来自两处登记之一 —— 正常，CLI 打 `ok(registered)`；
    - `"clean"`：这个角色的面上没有任何写工具 —— 正常，CLI 打 `ok(clean)`。

    `registered` 与 `universal` 刻意分两格、不合并：它们由两处互不重复的登记产生
    （例外表是"只读角色自己的落库代理"逐条带理由；通用轴是"通用能力不按角色分配"，
    判据是它只写通信/簿记表）。合并成一格会让"这件工具凭什么出现在只读角色面上"
    在读数里少一个答案，而这两个答案的失效方式不一样。
    """

    role: str
    #: 已登记例外：`((工具名, 登记理由), …)`，按工具名排序。
    registered: tuple[tuple[str, str], ...] = ()
    #: `UNIVERSAL_TOOLS` 里据实会写、且真的发到了这个角色面上的那几件（按名排序）。
    universal: tuple[str, ...] = ()
    #: 未登记的写工具（真泄漏；按名排序）。
    unregistered: tuple[str, ...] = ()

    @property
    def write_tools(self) -> tuple[str, ...]:
        """这个角色面上据实会写的全部工具（三档的并集，按名排序）。"""
        return tuple(sorted(
            [name for name, _why in self.registered] + list(self.universal) + list(self.unregistered)
        ))

    @property
    def verdict(self) -> str:
        """三档结论：`leak` / `registered` / `clean`（判据见类文档）。"""
        if self.unregistered:
            return "leak"
        return "registered" if self.write_tools else "clean"


def readonly_write_surface(
    registry: ToolRegistry,
    *,
    roles: Iterable[str] | None = None,
    exceptions: Mapping[str, Sequence[tuple[str, str]]] | None = None,
    universal: Mapping[str, Any] | None = None,
) -> dict[str, ReadonlyWriteSurface]:
    """只读角色写面的唯一读数：`cli tools` 与权威判据都读它。

    判据只有一条：把该角色 `for_role` 拿到的面上"据实会写"的工具，按来源分三档 ——
    减去 `READONLY_CALL_EXCEPTIONS[role]`（逐条登记的落库代理 / 自有凭据产物）与
    `UNIVERSAL_TOOLS`（通用能力：只写通信/簿记表，不按角色分配），剩下的才是
    「未登记」的写工具。`for_role` 的剥离保证真实树上第三档应当恒空；它是 fail-closed
    的读数，不是"重复一遍 for_role 的过滤"：哪一天剥离被绕开，这里就会把名字点出来。

    `roles` / `exceptions` / `universal` 是给负控与反真空用的注入口（默认真表）：
    `exceptions={}` 让"减例外"那一步什么都不减，于是三个已登记的代理会当场掉进
    `unregistered` —— 判据用它证明自己不是靠一张写死的名单在装绿。

    本函数不写盘、不改注册表，`role_filter_notes` 也不碰（那是 `for_role` 的返回值之外
    的另一件事）。
    """
    from . import READ_ONLY_ROLES, SIDE_EFFECTS_WRITE, UNIVERSAL_TOOLS

    who = tuple(READ_ONLY_ROLES if roles is None else roles)
    table = READONLY_CALL_EXCEPTIONS if exceptions is None else exceptions
    uni = UNIVERSAL_TOOLS if universal is None else universal
    out: dict[str, ReadonlyWriteSurface] = {}
    for role in who:
        why_by_name = {name: why for name, why in table.get(role, ())}
        registered: list[tuple[str, str]] = []
        universal_write: list[str] = []
        unregistered: list[str] = []
        for spec in registry.for_role(role):
            if spec.side_effect not in SIDE_EFFECTS_WRITE:
                continue
            if spec.name in why_by_name:
                registered.append((spec.name, why_by_name[spec.name]))
            elif spec.name in uni:
                universal_write.append(spec.name)
            else:
                unregistered.append(spec.name)
        out[role] = ReadonlyWriteSurface(
            role=role,
            registered=tuple(sorted(registered)),
            universal=tuple(sorted(universal_write)),
            unregistered=tuple(sorted(unregistered)),
        )
    return out


def surface_note_problems(registry: ToolRegistry) -> dict[str, list[str]]:
    """`role_filter_notes` 里「声明真的要改」的那一批（已登记放行不算）。

    留痕有两个来源：`_role_surface` 重算出来的"某件写工具被剥掉了"（声明错误，要人改）
    与"按登记放行了几件"（正常，是登记在干活）。后者不是问题，但它的文案里也带着
    "放行了"这种字眼 —— 消费方若按"有没有这条留痕"数，干净树上会报"声明需要纠正"。
    这里按 :data:`ALLOWANCE_NOTE_MARKERS` 把两类分开，两处共用同一份前缀常量。
    """
    out: dict[str, list[str]] = {}
    for role, notes in registry.role_filter_notes.items():
        keep = [m for m in notes if not any(mark in m for mark in ALLOWANCE_NOTE_MARKERS)]
        if keep:
            out[role] = keep
    return out


# ---------------------------------------------------------------- 参数接缝（工具 schema ↔ handler 签名）

#: 工具侧的参数接缝表：`工具名 -> {property 名: 一行理由串}`。
#: ## 与 `capabilities.PARAM_SEAMS` 是同一机制的两个落点
#: 两层各有一份"声明"，两份都可能有"声明了而实现不收"的格：能力层是 `ActionSpec.params` ↔
#: `Agent<X>.<handler_name>` 的真形参（判据在 `capabilities.assert_capabilities` 第 [8] 条，导入期
#: fail-closed）；工具层是 `ToolSpec.params` 的 properties ↔ handler 的真形参（判据在
#: :func:`param_seam_violations`，由 :meth:`ToolRegistry.register` 在「注册那一刻」核 —— 绕过
#: `build_registry` 的入口（`agent_d.install_d_tools` / `agent_e.install_e_tools` …）也必须被核到）。
#: 为什么落点是注册期而不是 `import agentflow.tools`：工具模块的 `register()` 是装配时才跑的，导入那一刻
#: 树上一个 `ToolSpec` 都没有（导入期只核"这张表自己的形态"，见 `_check_param_seams_are_registered()`）。
#: 今天这张表是空的，但「空表不等于没判据」：盘上没有一个 property 是 handler 收不下的
#: （`tests/test_schema_handler_params.py` 是测试面的同一读数），判据是否走遍声明由 `build_registry` 的
#: `inspected` 计数核；「不许」为了让这一格"看起来有东西"而凭空登记（`stale_param_seam_violations` 会报）。
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
    判据与 `tests/test_schema_handler_params.py` 逐字同形（那一份是测试面的同一读数）： handler 收 
    `inspect.Parameter.VAR_KEYWORD` 时按定义不适用（它真的收得下任何键，所以这一格不会变成 `kind='unexpected'` 的假
    bug 分类）。返回空列表 = 查过了、干净。
    ## 为什么名字带 `tool_`，而不是与能力层共用一个名字（`R003`）
    能力层的同族判据叫 `capabilities.param_seam_violations`，它比的是`ActionSpec.params` ↔ 
    `Agent<X>.<handler_name>`。两者形状相同、对象不同，而依赖方向不允许合并成一份实现：`tools` 不许 import `capabilities`
    （依赖方向是 capabilities 局部 import tools），把判据搬到任一侧都会让另一侧反向依赖。名字里的 `tool_` 是显式的：它点明这一份守的是工具层，
    免得下一个人以为两处是同一份实现的两半（`R003` 报的正是这种同名双实现）。
    `spec.handler` 不是 callable 时这里会让 `inspect.signature` 抛出来 ——那是刻意的 fail-closed：注册一个
    handler 坏掉的工具必须炸，而不是被"读不出签名就跳过"静默放过（三态纪律）。
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
        props = {} if spec is None else ((spec.params or {}).get("properties") or {})
        violations: list[str] | None = None
        for prop in sorted(table[tool] or {}):
            if spec is None or prop not in props:
                out.append(f"{tool}.{prop}")
                continue
            if violations is None:
                violations = tool_param_seam_violations(spec, seams)
            if prop not in violations:
                # 已经不需要接缝了（handler 现在收得下它）
                out.append(f"{tool}.{prop}")
    return out


def check_param_seams(
    spec: Any,
    seams: Mapping[str, Mapping[str, str]] | None = None,
) -> None:
    """注册期的 fail-closed 判据：违反就抛 `ParamError`。

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
        
        为什么剪枝是显式的，而不是在 `ToolRegistry.call` 里自动做：自动剪会悄悄改变所有既有调用方拿到的返回值，于是"没开剪枝"与"开了但没超阈值"在调用方眼里
        长得一模一样 —— 那正好是本项目最忌讳的失败形态（分不清"没做"与"做了没效果"）。入口在这里，剪不剪由调用方决定。
        
        剪枝不改结论：`ok` / `error` 逐字段保留，只有 `data` 变短、`meta`多出 `pruned` / `spilled` / `spill_path`
        / `original_chars` 等审计字段。
        
        实现转发给 `agentflow.contextbudget.prune_tool_result`，且用局部导入：工具层基座是所有智能体的公共底盘，不该在 import 期
        就依赖上下文预算模块（`contextbudget` 也不 import 本模块，用鸭子类型 + `dataclasses.replace`，两边都不构成循环 —— 有测试
        锁这一点）。
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


# `_schema_allows_null` 已删掉：它零调用点，而它描述的那个判据（"只在 schema 说 nullable
# 时才放行显式 null"）与现行的口径相反：显式 null 一律放行，崩了再翻成可行动的
# `param_error`（见 `ToolRegistry.call` 里 `except (TypeError, AttributeError)` 那一支 ——
# 那里的注释写着为什么"不改校验语义"）。留一个不打算落地的判据，只会让读的人以为 null 有闸。


#: 参数门里"已知派生列 → 该写到哪"的小表。
#:
#: 为什么需要它：这几格在盘上是可读的列，但**不可写**（由某一处现算 / 推断），
#: 而拒信只说"s schema 只允许 [...]" 时，模型会照着允许清单再猜一次。
#: 表里每一行都回答同一个问题："这一格不是我该写的，那我该写到哪？"
#: 判据：`tests/test_param_gate_reports_every_problem_at_once.py` 的 b。
_READONLY_PARAM_HINTS: dict[str, str] = {
    "bits": "`bits` 由秘书按五元位现算（不接受手写）；要写理由请用 `quote_reason`",
    "proof_authors": ("`proof_authors` 由 `proofauthors.py` 按来源路径推断"
                      "（不接受手写）；删掉它再交即可"),
    "created_by": "`created_by` 由台账按调用方角色填（写进去也只会被覆盖）；删掉它再交",
    "created_at": "`created_at` 是写入期现算的时间（手写等于编一个）；删掉它再交",
}


def _undeclared_hint(key: str, props: Mapping[str, Any]) -> str:
    """一个未声明键的"怎么改"：派生列说去哪，拼错的说最接近的已声明键。

    这是拒信从"你错了"变回"改哪一格"的那一步：只列允许清单时，模型得自己把
    "我传的是什么"与"表里有什么"对一遍 —— 而真机读数显示它做不到。
    """
    known = _READONLY_PARAM_HINTS.get(str(key))
    if known:
        return known
    near = difflib.get_close_matches(str(key), [str(p) for p in props], n=1, cutoff=0.5)
    if near:
        return f"最接近的已声明键是 {near[0]!r} —— 是不是想写它？"
    return "把不认识的键删掉再交（`why` 不用传，它会自动记进留痕）"


def _param_problems(schema: Mapping[str, Any], params: Any, *, path: str = "") -> list[str]:
    """把 schema 与 params 的全部不合规点收成一份清单（一份空清单 = 合法）。

    为什么不是"抛第一个错就返回"：缺一个必填、多给一个未声明时，模型必须先改一个、
    再撞一次 —— 两轮往返只买到一条本该一次说完的拒信。收集式校验把"要改几处"一次
    摊开；它不改变任何一条判据的严格程度。
    """
    t = schema.get("type")
    if t is None:
        return []                # 未声明类型 = 不约束

    if t == "object":
        if not isinstance(params, Mapping):
            return [f"{path or 'params'} 必须是对象，收到 {_type_name(params)}"]
        props: Mapping[str, Any] = schema.get("properties") or {}
        problems: list[str] = []
        for req in schema.get("required") or []:
            if req not in params:
                problems.append(f"缺少必填参数：{path}{req}（补上它再交）")
        if schema.get("additionalProperties") is False:
            extra = sorted((set(params) - set(props)), key=str)
            if extra:
                # 同一句"怎么改"只留一次（两个都拼错的键会各自给出同一句通用建议）。
                hints = "；".join(dict.fromkeys(
                    _undeclared_hint(str(k), props) for k in extra))
                problems.append(
                    f"出现未声明的参数：{extra}（schema 只允许 {sorted(props)}）。{hints}")
        for name, sub in props.items():
            if name in params and params[name] is not None:
                problems.extend(_param_problems(sub, params[name], path=f"{path}{name}."))
        return problems

    if t == "array":
        if not isinstance(params, (list, tuple)):
            return [f"{path or 'value'} 必须是数组，收到 {_type_name(params)}"]
        problems = []
        if "minItems" in schema and len(params) < schema["minItems"]:
            problems.append(f"{path} 至少 {schema['minItems']} 项，收到 {len(params)}")
        if "maxItems" in schema and len(params) > schema["maxItems"]:
            problems.append(f"{path} 最多 {schema['maxItems']} 项，收到 {len(params)}")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for i, item in enumerate(params):
                problems.extend(_param_problems(item_schema, item, path=f"{path}[{i}]."))
        return problems

    # ---- 标量：类型错就不再看取值（再叠一条 enum 错只会是同一件事的两种说法）
    # bool 是 int 的子类，必须先单独判布尔，否则 True 会被当成合法整数
    if t == "boolean":
        if not isinstance(params, bool):
            return [f"{path or 'value'} 必须是 boolean，收到 {_type_name(params)}"]
    elif t == "integer":
        if isinstance(params, bool) or not isinstance(params, int):
            return [f"{path or 'value'} 必须是 integer，收到 {_type_name(params)}"]
    else:
        expected = _TYPES.get(t)
        if expected and not isinstance(params, expected):
            return [f"{path or 'value'} 必须是 {t}，收到 {_type_name(params)}"]

    problems = []
    if "enum" in schema and params not in schema["enum"]:
        problems.append(f"{path or 'value'} 必须是 {schema['enum']} 之一，收到 {params!r}")
    if t == "string":
        if "minLength" in schema and len(params) < schema["minLength"]:
            problems.append(f"{path} 长度至少 {schema['minLength']}")
        if "maxLength" in schema and len(params) > schema["maxLength"]:
            problems.append(f"{path} 长度最多 {schema['maxLength']}")
    if t in ("integer", "number"):
        if "minimum" in schema and params < schema["minimum"]:
            problems.append(f"{path} 不能小于 {schema['minimum']}")
        if "maximum" in schema and params > schema["maximum"]:
            problems.append(f"{path} 不能大于 {schema['maximum']}")
    return problems


def validate_params(schema: Mapping[str, Any], params: Any, *, path: str = "") -> None:
    """按 schema 校验参数。不合法抛 `ParamError`（不是返回布尔）。

    只支持本工具层实际用到的子集：type / required / properties / enum /
    items / minimum / maximum / minLength / maxLength / minItems / maxItems /
    additionalProperties。刻意不做全量 JSON Schema —— 覆盖面够用即可，
    实现越小越不容易有 bug。

    这里必须先看 schema 声明的类型再决定怎么校验：子 schema 也走同一个函数，把
    "必须是对象"的检查放在开头，任何非对象值（比如一个字符串参数）一进来就会被判成
    "必须是对象"。

    一次报全，不是 first-error：每碰一个错就抛一次时，"缺一个必填、多给一个未声明"
    要两次往返才凑齐，而且"未声明参数"的拒信只列允许清单、不说派生列该写到哪。
    现在全部不合规点由 `_param_problems` 一次收齐，各占一行（派生列还给出去路，
    拼错的键给最接近的候选）。判据
    `tests/test_param_gate_reports_every_problem_at_once.py` 的四条。
    严格程度一个字没放宽：收齐的仍是同一批判据，只是不再逐条挤牙膏。
    """
    problems = _param_problems(schema, params, path=path)
    if not problems:
        return
    if len(problems) == 1:
        raise ParamError(problems[0])
    raise ParamError(problems[0] + "\n  - " + "\n  - ".join(problems[1:]))



# ---------------------------------------------------------------- ToolSpec


@dataclass(frozen=True)
class ToolSpec:
    """一个可调用工具。
    `params` 用 JSON Schema 写（object 根），既用于本层校验，也能原样喂给 function-calling —— 所以它必须自描述、不含
    Python 专有类型。
    ## 两根轴（`effect` × `external`）与"六件套"
    `side_effect` 是声明轴的历史名称，它把两根正交轴压在一个取值上。本类同时给出两根轴上的取值：`effect`（能不能改我们拥有的东西）与`external`（能
    不能触到我们不拥有的事）。`declared_external` 由工具作者人写（默认 `none`，因为"我没说"不等于"我会出网"）；两根轴的最终取值都由属性就地推导（`DEVELOPMENT.md`
    §3 纪律 6：派生态就地推导或装配期断言，没有第三种）。
    AST 只用来核对声明与代码是否一致，绝不用来生成声明（AST 推断已被否决：很多 handler 的源码取不到、
    转发型 handler 还会是假阳性）。本类里没有一个字符是由 AST 推断出来的：两根轴上的值都是人写下来的
    （`side_effect` 与 `declared_external`），词表只用来挡非法取值。
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
    #: 必须人写；AST 绝不用它来生成这个值。
    #:
    #: 它是字段而不是属性：属性会和 dataclass 的 `__init__(external=...)`
    #: 撞名。第二根轴的取值由 :attr:`external` 属性给出，这个名字只保留
    #: "人写下来的那一份声明"（`tool()` 装饰器的同名关键字参数 `external`
    #: 也落到这个字段上）。
    declared_external: str = "none"
    #: ② 场景（< 50 字）：什么时候该用这一件、什么时候用别的那一件。
    #:
    #: 与 `summary` 分开的理由（业主 2026-11-22 三段格式）：`summary` 只回答
    #: 「这工具做什么」，场景回答「我此刻该不该用它」。合成一段的后果是压缩判据
    #: （`cohort ≤ 0.75`，只量 `summary`）既量不准能力、又逼着人把场景压掉。
    scenario: str = ""
    #: ③ 案例的散文部分（< 100 字）：一条真实场景 + 它会回什么。
    #: 代码在 `example_code`（那一格逐字不压缩、也不计字数）。
    example: str = ""
    #: ③ 案例的代码块：与真身签名逐字一致（参数名 / 键名不许改写）。
    #:
    #: 不压它的理由：模型抄这一段就能调对；改一个键名，抄下去就是一次 `unknown_param`。
    #: 它不进任何字数统计（业主口径：代码不计），所以压它只丢信息、不换空间。
    example_code: str = ""

    def __post_init__(self) -> None:
        """装配期自检：六件套齐全 + 两根轴的取值受控。
        ## 为什么六件套校验真的在这里
        `DEVELOPMENT.md` §4.3 第 1 项声称"六件套齐全"由本方法校验。只校验 `side_effect` 与
        "名字含 `.`"的话，文档就承诺了一个不存在的门 —— 比少一条门更危险：读者以为
        `summary` / `params` / `returns` / `roles` 有人管，于是不再去看。这里把那条承诺兑现
        成真正的取值校验（见 §4.3 第 1 项与本类测试）。
        ## 判据的形态
        六件套里四件（`name` / `summary` / `params` / `returns`）是输入，必须是可用的值；`side_effect` 与 `roles` 的"齐全"是结
        构性的（受控词表 + 元组），不是"非空"：`roles=()` 是一个真实的声明（"这个工具不属于任何角色"），把它判成"缺字段"会把一个可判定的事实折叠成错误。
        `roles` 那半的"元组"判据在末尾。
        顺序刻意是先词表后结构：`side_effect` 的取值校验必须排在`params` 之前，否则 `params={}` 这种手工构造会先以"params 不是 object 根"报
        错，把"side_effect 非法"这条更重要的信息盖掉（既有测试 `test_toolspec_rejects_invalid_side_effect` 钉住了这一点）。
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
            # 的注释（它会命中 `agent_d.py` 的三个内置降级替身）。这里只挡"类型给错"
            # （None / 非字符串），而"忘了写"由 §4.3 的 census 观察。
            raise ValueError(
                f"{self.name} 的 returns 必须是字符串（空字符串 = 你确认过它没有"
                f"可声明的返回形态），收到 {type(self.returns).__name__}"
            )
        # ---- 六件套里 `roles` 的"齐全"是结构性的：必须是元组
        # `tuple` 是这条契约的一半（另一半 `role in ROLES` 在
        # `ToolRegistry._reject_unknown_roles` 里）；`tool()` 装饰器已用 `tuple(roles)` 兜住，所以只有手工
        # 构造会命中 —— 而那正是要拦的。
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
        这个属性不再有第二个来源：`network` 那个取值分不清"出网"与"起进程"，已从词表
        删掉；现在属性与字段是同一件事。
        """
        return self.declared_external

    @property
    def effect(self) -> str:
        """第一根轴：改不改我们拥有的东西。

        与 `side_effect` 同值 —— 这根轴是从那根轴上取下来的，不是第二份声明，
        也不是第二份词表。`network` 那个遗留取值及其翻译表已一起消失（`network`
        字面上说的是"不改我们的东西"，而 `search.download` 其实会写工作区）。
        """
        return self.side_effect

    @property
    def needs_approval(self) -> bool:
        """要不要人工审批。推导，不查逐工具布尔位。
        
                ```
                needs_approval = (effect == "write_local")
                              or (external != "none" and not sandbox_available)
                ```
        
        与提案字面表述的关系，刻意写在这里而不是留给读者去猜：提案把沙箱不可用时的升级写成 `external == "exec"` 一条，本实现还包含 `egress` ——沙箱
        不可用时出网同样没有任何承接手段，而沙箱可用时两者都被承接、都不再需要签字。

        这个函数只剩上面这一条判据（`write_local` 那一支覆盖了旧表的第一项；旧表的
        第二项 `network` 已从词表里消失）。删掉那张表是刻意的：留着它就等于"两套说法
        说同一件事"（FC-03 要防的形态）。
        
        """
        if self.effect == "write_local":
            return True
        return self.external != "none" and SANDBOX_AVAILABLE is not True

    @property
    def sandbox_required(self) -> bool:
        """要不要进沙箱：纯推导，无例外。"""
        return self.external != "none"

    def to_dict(self) -> dict:
        """给人/LLM 看的描述。不含 handler（不可序列化）。"""
        return {
            "name": self.name,
            "summary": self.summary,
            "scenario": self.scenario,
            "example": self.example,
            "example_code": self.example_code,
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

    # `to_function_schema` 已删掉：它生产零调用（只有两条测试断言），而模型真正看到的那份是
    # `llmseam.ToolFace` 里手搓的另一份（多注一个 `why` 属性、description 不带 `returns`）。
    # 两份 builder 并存的结果是"改这一份只让测试变绿，模型看到的字节不变" —— 那正是本仓
    # 最忌的假判据形态。提示词那一侧要不要把 `returns` 拼进 description，单列成"提示词
    # 升级"一件事（要抬版本 + 重冻 golden）。


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
    scenario: str = "",
    example: str = "",
    example_code: str = "",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """把普通函数标记成工具。`handler` 直接就是被装饰的函数。

    约定：handler 可以返回 `ToolResult`，也可以返回任意可 JSON 化的值
    （此时自动包成 `ok(...)`）；抛 `ToolError` 会被登记为失败结果而不再向上抛，
    这样智能体的循环不会因为一次工具失败而中断。

    `external` 见 :class:`ToolSpec`，必须人写：本装饰器里没有任何一处
    从函数体推断副作用（AST 推断已被否决）。

    ## 三段（业主 2026-11-22）：`summary` / `scenario` / `example` + `example_code`

    写在这里的三段是**模型可见面**（提示词的工具面与 function-calling 的
    description 同源），所以三段里都不许写实现：内部模块名、私有函数名、算法、
    内部存储布局都只写进 handler 的 docstring 或它旁边的注释 —— 那才是
    「具体实现」该待的地方（本文件的模块 docstring 与 `FACE_LABELS` 那段是同一口径）。
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
            scenario=scenario,
            example=example,
            example_code=example_code,
        )
        fn.__tool_spec__ = spec  # type: ignore[attr-defined]
        return fn

    return deco


# ---------------------------------------------------------------- 注册表


def candidate_tool_names(name: str, names: Iterable[str], *, limit: int = 3) -> list[str]:
    """错名的「并列候选」（机器半）。
    
    只回答"看起来像哪一个"，「绝不自动挑一个」（挑是判断，归出错方的秘书）。三条判据按序取并集，去重后截到 `limit`：
    
    1. 「同尾名」：`fs.read` 与 `table.read` 的尾名都是 `read` ⇒ 给 `read` 时并列出来（广告名与真名共用尾名是模型最常走的错法）；
    2. 「尾名近似」：`fs.raed` ⇒ `fs.read`（`difflib` 的近似匹配，阈值 0.6）； 3. 「全名近似」：`review.reportt` ⇒ 
    `review.report`。
    
    `names` 传的是「本注册表」里的名字。`ToolRegistry.scoped_to(..., deps=...)`会把 writers 子注册表里那批落库代理（`review.*`）
    装进同一张表，于是它们与工具面上的名字一样能被命中（"含 writers 子注册表名"这一条由结构保证，不是另写一份名单）。
    """
    pool = sorted({str(n) for n in names if str(n)})
    want = str(name or "")
    if not want or not pool:
        return []
    out: list[str] = []
    tail = want.split(".")[-1]
    if tail:
        pairs = [(n, n.split(".")[-1]) for n in pool]
        out += [n for n, t in pairs if t == tail]
        tails = sorted({t for _n, t in pairs})
        out += [n for n, t in pairs if t in difflib.get_close_matches(
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
        #: 注册表级的默认上下文预算（FC-17 的接线点）。
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
        #: 这张注册表代表谁（调用期判据）。`None`（默认）表示
        #: "调用方没说自己是谁" —— 那种注册表上的 `call` 一律被拒（fail-closed），
        #: 除非调用方逐次显式传 `role=`。
        #:
        #: 为什么默认是 `None` 而不是"所有角色"：默认放开等于"不写就等于允许"，
        #: 而只读约束（C/H 拿不到写工具）恰恰是靠"不写就不许"来强制的。
        self.bound_role: str | None = None

    # ---- 注册
    def register(self, spec: ToolSpec) -> ToolSpec:
        """注册一个工具。注册那一刻就核 `roles` 与参数接缝。

        `roles ⊆ schema.ROLES` 若只在 `build_registry` 里核（`tools/__init__.py`），
        自建注册表的入口（`agent_d.install_d_tools` / `agent_e.install_e_tools` /
        `agent_f.install_f_tools`）会绕过它：`roles=("agent-C", "agent-D")` 这种拼错
        一路装到底、`for_role` 静默少工具。判据放在注册期，覆盖所有入口（`register` /
        `register_function` / `register_spec` / `register_all`），而且失败得更早（构造
        注册表时就炸，而不是等到有人按角色过滤时才发现少工具）。
        注册期的失败一律用 `ToolError`：同一条注册路径上混两种失败类型（重名抛裸
        `ValueError`、`_reject_unknown_roles` 抛 `ToolError`）会让"按 `ToolError` 分类
        处理装配失败"的调用方静默漏掉工具名重复；工具名放进 `tool=` 元信息里。
        参数面（schema ↔ handler 签名）同理：绕过 `build_registry` 的注册表也必须被
        核到 —— 判据放错地方的症状是"某个入口静默少一条校验"，而不是任何一处报错。
        """
        self._reject_unknown_roles(spec)
        check_param_seams(spec)
        if spec.name in self._specs:
            raise ToolError(f"工具名重复：{spec.name}", tool=spec.name)
        self._specs[spec.name] = spec
        return spec

    def _reject_unknown_roles(self, spec: ToolSpec) -> None:
        """`set(spec.roles) <= set(TOOL_ROLES)`，否则抛 `ToolError`。

        单一来源是 `tools.TOOL_ROLES`（= `schema.ROLES` 加上主控 `CONDUCTOR_ROLE`）——
        不许另写名单。为什么主控在词汇里：`schema.ROLES` 管"谁可以被召唤"，工具层管
        "谁能拿工具"，这两件事必须分开（否则 `registry.for_role("M") == []`，主控工具面
        为空，"派活"在它手上没有动作可用）。主控拿工具不代表它能被召唤：可召唤性由
        `capabilities.ALLOWED_EDGES` / `NON_SUMMONABLE` 决定。
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
        """`register` 的显式别名（三处入口都必须核 `roles`）。

        它不复制判据，只是同一个入口的第二个名字：三处入口（`register` /
        `register_function` / `register_spec`）都必须核，而判据只有一份 ——
        写在这里的第二份校验会是 `FC-03` 要防的那种分叉。
        """
        return self.register(spec)

    # ---- 查询
    def get(self, name: str) -> ToolSpec:
        """取一个工具的声明；不认识这个名字时抛 `ToolError`。
        ## 错名给的是「并列候选」，不是"一次自动纠正"
        子串包含判据（`name.split(".")[-1] in n`）对调换两个字母的错名给不出任何候选，
        而对 `read` 会同时命中一批含 `read` 的名字，读的人仍然不知道该改哪一处。口径：
        - 机器「只把候选并列出来」（含 writers 子注册表里的那批名字 ——
        `scoped_to(..., deps=...)` 把 `review.*` 这类落库代理装进本表，于是它们和工具面上的名字一样能被候选命中）；
        - 机器「不自动改写」：选哪个名字是判断，归出错方的秘书（职责 1/2），机器只留 fail-closed 的
        `unknown_tool` 与这份候选读数。
        """
        try:
            return self._specs[name]
        except (KeyError, TypeError):
            # `name` 不可哈希（如传了个 list）时 `self._specs[name]` 抛 `TypeError`，
            # 所以这里也捕它：并进"查不到"这一条路，下面照旧给候选名与提示，不冒泡。
            close = candidate_tool_names(name, self._specs)
            hint = ""
            if close:
                hint = (f"；并列候选（{len(close)} 个）：{close} —— 机器只列候选、"
                        "不自动改写，由你（或你的秘书）决定改哪一处")
            raise ToolError(f"没有名为 {name!r} 的工具{hint}", tool=name) from None

    def names(self) -> list[str]:
        return sorted(self._specs)

    def call_surface(self, role: str) -> list[str]:
        """可调用面的工具名：工具面 + 逐条登记的落库代理。

        为什么需要它（而不只是 `for_role`）：`call` 的判据用的是这个集合，
        装配方与报告方必须能看到同一个集合 —— 否则"为什么 H 能调
        `review.review_document`"就只能靠读 `call` 的实现来回答。
        名字进 `role_filter_notes` 的那一类（被只读约束剥掉的）不在里面。
        """
        surface, _ = self._role_surface(role, filter_readonly=True, call_surface=True)
        return sorted(s.name for s in surface)

    def scoped_to(self, role: str, *, deps: Mapping[str, Any] | None = None) -> "ToolRegistry":
        """返回一张只代表 `role` 的新注册表（`bound_role = role`）。
        它内部走同一个私有谓词（:meth:`_role_surface`）：新表登记的是同一个注册表里的全部 spec（同一个不可变对象，不是拷贝），而"这一次到底能不能调"由:meth:`call` 逐次判（`_callable_for`）
        —— 装配时过滤一次就永久放行的那种设计正是要消灭的形态。
        只登记工具面会让`call("fs.write", role="C")` 得到"没有名为 fs.write 的工具"——那既掩盖了"这张表代表 C"的事实，也让"冒充另一个角色"（`role="H"` 传进来）这件事没法
        被看见（它应该报"绑定的是 C，你传了 H"）。若新表按工具面裁剪，`H` 的三个 `review.*`（在 `build_registry` 的完整注册表里根本不存在）就连名字都注册不进来，
        `_callable_for` 便永远只能报 `unknown_tool` ——那张显式例外表会失效。
        `deps`：例外工具没被装配过时按需补装`H` 的落库代理（`READONLY_CALL_EXCEPTIONS["H"]`）不在 `build_registry` 的产物里（`review_tools.register`
        默认 `include_writers=False`），而它的 handler 是一个闭包（把 `store` / `actor` 绑进去的那种），所以补装必须走该模块自己的
        `register(..., include_writers=True)`，而不是凭空造一个 `ToolSpec`。`deps` 就是传给那次 `register` 的依赖（例：`{"store": store}`）。
        补装默认不生效（`deps=None`）且绝不静默失败：补装没做成时会在:attr:`role_filter_notes` 里留一条说明。
        装饰性属性（上下文预算 / spill 根）一并复制，否则"按角色装配之后 FC-17 的接线静默失效"（`AgentG` 的注册表就是这么来的）。
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
        没被装配过"），绝不假装它有。补装失败同样留痕（降级必须显式）。
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

        `roles` 是手工声明的，而"哪些角色是只读的"是一条设计约束。靠"每个工具作者都
        记得不把 H 写进 roles"来维持这条约束是不成立的：`table.*` / `fs.*` 曾把所有角色
        都写进 `roles`，于是按角色装配出来的"审校者 H 的工具面"里出现了 `table.update`、
        `fs.write` —— H 手里有能改 `documents.claims` 的刀，而"H 只读"正是"发现问题"与
        "掩盖问题"能被区分开的前提。所以这里做一件工具作者无法绕过的事：对
        `READ_ONLY_ROLES`，无论 spec 怎么声明，一律过滤掉（1）有写副作用的工具与
        （2）`external == "exec"` 的工具。

        唯一的例外不是例外表，而是"通用能力"这第二根轴（"通用能力根本不该出现谁能用
        这个说法"）：登记在 `tools.UNIVERSAL_TOOLS` 的工具对只读角色照样发，不论它的
        `side_effect` 是 `read` 还是 `write_local` —— 因为 `clock.timer_start` 据实就是
        `write_local`（它写 `tasks` 的 notice 行与 `out/clock` 的状态），而它仍然必须是
        所有人都能拿的通用工具。硬约束：通用工具的登记写集只许落在通信/簿记类表上，
        越界的那些不发给只读角色（见 `_role_surface`）。

        被过滤掉的名字记在 `role_filter_notes` 里 —— 留痕是因为"某个工具本该给 H 却是
        写工具"是一个声明错误，静默过滤会让它永远发现不了。
        `call` 的判据用的是可调用面：它还多出 `READONLY_CALL_EXCEPTIONS` 里逐条登记的
        落库代理（今天只有 `H` 的三个 `review.*`）。两个集合刻意分开命名、分开产生：
        把代理混进工具面会让 `docs/ROLE-SPECS.md` §H.4 的条数与清单漂移，而把工具面
        收窄成"可调用面"会把 H 的落库能力一起砍掉。
        """
        # 重算而不是追加。放在调用 `_role_surface` 之前：留痕有「两个来源」——
        #   - `_role_surface` 的重算（本方法写的）—— 每次清掉重写，这是幂等要求；
        #   - 「装配期」 `scoped_to` + `_attach_registered_writers`（"已登记的落库代理没有
        #     装配进这张表"那几条）—— 它们描述的是「装配事实」，不是本方法的重算结果。
        # 若一句 `pop(role, None)` 把整个列表清空，先 `scoped_to("H")` 再 `for_role("H")`
        # 时那几条会被抹掉：事实没有变（代理仍然没装进来），记录却没了。
        self._drop_own_role_notes(role)
        surface, notes = self._role_surface(role, filter_readonly=True, call_surface=False)
        for message in notes.get(role, []):
            self._add_surface_note(role, message)
        return surface

    def _drop_own_role_notes(self, role: str) -> None:
        """清掉本表「上一次由 `_role_surface` 重算写入」的留痕；装配期那几条留着。"""
        kept = [m for m in self.role_filter_notes.get(role, []) if not m.startswith(_SURFACE_NOTE_TAG)]
        if kept:
            self.role_filter_notes[role] = kept
        else:
            self.role_filter_notes.pop(role, None)

    def _add_surface_note(self, role: str, message: str) -> None:
        """写一条「重算来源」的留痕（带标记，便于 `_drop_own_role_notes` 精确清理）。"""
        self.role_filter_notes.setdefault(role, []).append(_SURFACE_NOTE_TAG + message)

    def _role_surface(
        self, role: str, *, filter_readonly: bool, call_surface: bool
    ) -> tuple[list[ToolSpec], dict[str, list[str]]]:
        """按角色裁工具面（`for_role` 与 `call` 共用的唯一判据实现）。

        返回 ``(保留的 specs, 留痕)``；留痕的键是角色名，值与 `for_role` 记进
        :attr:`role_filter_notes` 的那两句逐字相同。抽出来的理由是硬要求：
        `for_role` 与 `call` 必须调用同一个私有谓词，不许在 `call`
        里另写一遍"哪些算写工具"的名单（那是 `FC-03` 禁止的第二份实现）。

        `filter_readonly` 只用来让 `call` 的离线检查构造一个"不剥离"的临时表
        （见 `_callable_for` 的注释）；两条判据本身逐字相同，不分叉。

        只读角色的剥离
        只对"某个角色的活"成立。登记在 `UNIVERSAL_TOOLS` 的工具是通用能力，不会因为
        `side_effect` 是 `read` 还是 `write_local` 被剥掉 —— 可达性轴的判据是
        "它写不写知识表"，不是"它写不写东西"。硬约束的两半都在这里：
        登记写集越出 `BOOKKEEPING_TABLES` 的通用工具不发给只读角色（fail-closed 并留痕），
        而登记本身越界在导入期就已经炸（`tools._check_universal_tools_are_registered`）。
        为什么同一件事有两处判据：导入期那条挡"登记错"，这里挡"到了这儿仍然不许发"。
        通用工具不进 `READONLY_CALL_EXCEPTIONS` —— 例外表回答的是"谁能用"，
        而通用能力没有这个问题（`_check_universal_tools_are_registered()`
        把"两边同时登记"判红）。

        由 Lean 开关决定存在性的角色在
        开关关着时不存在 ⇒ 两个面都是空的（工具面与可调用面）。判据读
        `leanscope`（唯一入口），这里不做第二份判断。
        """
        from .. import leanscope as _LEANSCOPE
        from . import BOOKKEEPING_TABLES, READ_ONLY_ROLES, SIDE_EFFECTS_WRITE, UNIVERSAL_TOOLS

        if _LEANSCOPE.is_hidden(role):
            return [], {}

        out: list[ToolSpec] = []
        refused: list[str] = []
        refused_universal: list[str] = []
        allowed_by_sandbox: list[str] = []
        allowed_by_exception: list[str] = []
        allowed_by_universal: list[str] = []
        readonly = filter_readonly and role in READ_ONLY_ROLES
        bookkeeping = set(BOOKKEEPING_TABLES) if readonly else set()
        exempt = {name for name, _why in READONLY_CALL_EXCEPTIONS.get(role, ())} if readonly else set()
        for s in self._specs.values():
            if role not in s.roles:
                continue
            if readonly:
                # 可达性轴与副作用轴分开。登记在 `UNIVERSAL_TOOLS` 的工具对只读角色
                # 照样发 —— 判据不是它的副作用等级，而是它写不写知识表。
                # 硬约束在这里（不是只在测试里）：登记的写集越出通信/簿记类表
                # ⇒ 这件工具不发给只读角色（fail-closed），并留痕。否则"通用集合"
                # 就成了"只读角色能改知识表"的后门。
                _universal = UNIVERSAL_TOOLS.get(s.name)
                if _universal is not None:
                    _outside = sorted(set(_universal.tables) - bookkeeping)
                    if _outside:
                        refused_universal.append(s.name)
                        continue
                # 「该角色自己的落库代理放行」：写面钉死在
                # `READONLY_CALL_EXCEPTIONS[role]` 那张逐条登记的表里
                # —— 它不是"放宽只读"，而是"只读角色的写只允许这几个落点"。
                if s.side_effect in SIDE_EFFECTS_WRITE:
                    if s.name in exempt:
                        allowed_by_exception.append(s.name)
                    elif _universal is not None:
                        allowed_by_universal.append(s.name)
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
        if refused_universal:
            notes.setdefault(role, []).append(
                f"通用工具 {sorted(refused_universal)} 没有发给只读角色：它们登记的写集越出了"
                f"通信/簿记类表 {sorted(BOOKKEEPING_TABLES)}（硬约束，fail-closed）"
                "—— 通用能力只许写通信与簿记，写别的表说明它该是某个角色的工具"
            )
        if allowed_by_sandbox:
            notes.setdefault(role, []).append(
                f"沙箱已声明可用（SANDBOX_AVAILABLE=True），因此放行了 {len(allowed_by_sandbox)} 个 "
                f"external=exec 的工具：{sorted(allowed_by_sandbox)}"
                "（承接执行的是沙箱，不是'这个工具变安全了'）"
            )
        if allowed_by_exception:
            notes.setdefault(role, []).append(
                f"{_ALLOWANCE_NOTE_EXCEPTION} {len(allowed_by_exception)} 个**该角色自己的写入面**"
                f"（落库代理 / 自有凭据产物）：{sorted(allowed_by_exception)}"
                f"（写面钉死在 READONLY_CALL_EXCEPTIONS[{role!r}] 里）"
            )
        if allowed_by_universal:
            notes.setdefault(role, []).append(
                f"{_ALLOWANCE_NOTE_UNIVERSAL} {len(allowed_by_universal)} 件写工具：{sorted(allowed_by_universal)}"
                f"（UNIVERSAL_TOOLS：通用能力不按角色分配，它们的写只落在通信/簿记类表 "
                f"{sorted(BOOKKEEPING_TABLES)} 上；不靠 READONLY_CALL_EXCEPTIONS）"
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
        """这个角色能不能调这个 spec？
        返回 ``None`` 表示"可以"，否则返回拒绝理由（两处拒绝都必须给理由，不许静默放行 —— "没写"不等于"允许"）。
        ## 谁走这里
        只有 `call` 走这里。`for_role` 直接调 `_role_surface(..., call_surface=False)`，从不经过本函数。
        判据本身只有一份：`for_role` 与 `call` 都落在 `_role_surface` 上（那是 `FC-03` 的要求），本函数只是 `call` 侧"把理由说清"的那一层。
        1. `self.bound_role is None and role is None` ⇒ 拒（调用方没声明自己是谁）； 2. 
        `self.bound_role is not None and role is not None and role != self.bound_role`⇒ 拒（拿一个已绑定注册表的身份去冒充另一个角色）；
        第 3 步内部的分支只用来把理由说清，判据本身只有 `_role_surface` 一份：先把同一张表按"不剥离"裁一次（`filter_readonly=False`），于是"在你的角色面里，但它被只读约束
        剥掉了"与"它压根不在你的角色面里"是两句不同的拒绝理由 —— 调用方拿到的不是一句"不行"。
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
        # 参数 `include_registered_writers` 的作用在「上面」那句
        # `_role_surface(..., call_surface=include_registered_writers)` 里
        # （可调用面是否包含已登记的落库代理）。
        return f"角色 {eff!r} 拿不到工具 {spec.name!r}：它不在这个角色的可调用面里"

    def describe(self) -> list[dict]:
        return [self._specs[n].to_dict() for n in self.names()]

    # `function_schemas` 已删掉：它只调 `ToolSpec.to_function_schema`（同批删），
    # 生产零调用。模型看到的函数面由
    # `llmseam.ToolFace` 一处产生 —— 名字归一化（`.` → `__`）、`why` 属性、description
    # 的拼法都在那里；本层不再有第二份 builder。

    def text_catalog(self, role: str | None = None) -> str:
        """给 LLM 看的纯文本清单（比 JSON 省 token，也更容易被读进去）。"""
        specs = sorted(self.for_role(role) if role else self._specs.values(), key=lambda s: s.name)
        lines = [f"可用工具（{len(specs)} 个）："]
        for s in specs:
            flag = " ⚠需审批" if s.needs_approval else ""
            lines.append(f"- {s.name}({', '.join((s.params.get('properties') or {}).keys())}){flag}")
            lines.append(f"    {face_text(s)}")
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

        `role`：只读约束是调用期强制。`role` 是关键字参数，默认 `None` 表示"调用方没说自己是谁"，
        而 `None` 一律被拒（fail-closed）—— 判据见 `_callable_for`。为什么这对只读角色是决定性的：
        `for_role` 的过滤只在装配路径上成立，任何拿到完整注册表的路径都能调写工具，而没有任何东西
        会红。

        `args` 与 `params` 两种写法（`params` 优先于 `args`）：工具参数可以作为映射整体传入
        （`call("fs.read", {"path": "a.txt"})`），也可以逐名传入（`call("fs.read", path="a.txt")`）
        —— 后者是本仓库既有的主流写法，逐处改成映射会动到 300+ 个调用点。

        为什么 `budget` 必须是关键字且默认为 None：FC-17 要求"上下文预算三件套必须开"，但把它做成
        自动生效会让既有调用方拿到的返回值悄悄变短 —— "没开剪枝"与"开了没超阈值"就再也分不开了。
        所以这里只在显式传入 `budget` 时才剪枝：`registry.call("fs.read", path=..., budget=b)`。

        `budget` 的名字冲突（真实存在）：`attack.check_budget` / `attack.create_plan` 自己就有一个
        `budget` 参数（FC-18 的四维预算）；若目标工具的 params schema 里声明了 `budget` 属性，则本
        关键字属于工具。代价是：对这两个工具，一次调用里不能同时传"工具的 budget"和"上下文的
        budget" —— 需要剪枝时用返回值上的 `ToolResult.pruned(budget, spill_root=...)` 第二步做。

        两个"吞参数"的名字（`role` / `args`）：若某个工具的 schema 里真的声明了 `role` 或 `args`
        属性，调用方按名传入的那一份必须原样落到工具上（`role` 只在身份声明那一侧被本方法占用，
        `args` 在本方法里就地合并）——本仓库今天没有任何工具这么做，有测试钉着这一点。

        `role` 这一格的优先级与"身份声明"的关系：「显式关键字 > 位置映射 > `bound_role`」。
        工具声明了 `role` ⇒ 它收下 `role=<显式关键字>`，没给才用位置映射里的那一份；身份声明回退到
        `self.bound_role`（它本来就该按绑定值判，而不是按 `None`）。「位置映射里给的 `role`」必须与
        关键字形态走同一套判据，否则 `call(name, {"role": "H"})` 会跳过身份判据。两件事都必须留痕：
        调用日志里会记 `role_consumed_as_param` 与 `identity_role`。"""
        # 查工具这一步也要在 try 里：工具名写错同样属于"调用方写错了"，
        # 应该返回结构化失败让智能体自己纠正，而不是把它的循环打断。
        try:
            spec = self.get(name)
        except ToolError as e:
            return fail(str(e), tool=name, kind="unknown_tool")

        props = spec.params.get("properties") or {}
        has_budget = "budget" in props
        # ---- 同名参数的消歧（规则与 `budget` 同族：schema 说了算）
        # 优先级：「显式关键字 > 位置映射 > bound_role」。位置映射里的 `role` 必须与关键字
        # 形态走同一套判据：否则 `call(name, {"role": "H"})` 会跳过身份判据、工具真的收到
        # `{'n': 1, 'role': 'H'}` 并返回 ok，而关键字形态判 `role_denied`。修法：先把位置映射
        # 里的 `role`「提升」成一次身份声明，再让下面那段唯一的分流去决定"工具收下"还是
        # "当作身份"。
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
        budget_as_tool_param = isinstance(budget, Mapping) and has_budget

        # ---- 调用期角色判据（唯一判据在 `_callable_for`）
        #
        # 传的是 `role`（已被上面置空的那一份），而不是 `role_as_param`：
        # 身份声明与"工具收下的那个同名参数"是两件事。
        # 被置空时 `_callable_for` 会回退到 `self.bound_role`（它自己那一行 `eff = ...`）。
        denial = self._callable_for(spec, role, include_registered_writers=True)
        if denial is not None:
            # 被拒的调用「也要留痕」：拒绝理由里会出现"调用方没有声明角色"这句话，
            # 而在"role 被工具收下"的形态下那句话只有靠 `role_consumed_as_param` /
            # `identity_role` 两个字段才能自证。不留痕 ⇒ 读日志的人无法判断
            # 这句话是对的还是在冤枉调用方。
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
        if budget_as_tool_param and "budget" not in merged:
            merged["budget"] = budget
            budget = None
            spill_root = None
        if budget is not None and has_budget:
            merged["budget"] = budget
            budget = None
            spill_root = None

        try:
            # 模型习惯在参数里带 `why`（"我为什么这么调"）。
            # 参数集是封闭的 ⇒ 整份调用被拒，一次真实的写入/检索就白费了。它「不是」工具参数，
            # 但它是审计线索 —— 从参数面剥掉、记进留痕（下面 `entry` 里），不当参数也不丢。
            _why = None
            _props = props
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
            # 可选参数「显式传 null」时校验器
            # 把它当"没提供"放行，而 handler 按"一定有值"写 ⇒ 崩成 `kind="unexpected"`
            # （读账的人只看到"库内部出错"）。这里把"有 null 且崩了"翻成「可行动的拒信」，
            # 而「不改」校验语义 —— 于是 `attack.list_plans` / `review.scan_document`
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
        if eff_budget is not None and has_budget:
            eff_budget = None
        if eff_budget is not None:
            eff_spill = spill_root if spill_root is not None else self.default_spill_root
            res = res.pruned(eff_budget, spill_root=eff_spill)
        # `default_budget=None` ⇒ 什么都不做 ⇒ 与加 FC-17 之前逐字节一致。
        if self.log_calls:
            # "身份声明被让给工具"这件事必须「留痕」：否则只读拒因无法自证
            # （调用方看到"你没有声明角色"，而它其实声明了，只是被工具的参数收下了）。
            entry = {"tool": name, "params": _safe(merged), "ok": res.ok, "error": res.error}
            # `entry` 必须整段留在 `if self.log_calls:` 里面：它只在上面那一支里赋值，
            # 若「任何带 `why` 的调用」都在支外碰 `entry`，生产默认 `log_calls=False` 时
            # 就会 UnboundLocalError。现在它的全部使用都在同一支里，False 时什么都不碰。
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
