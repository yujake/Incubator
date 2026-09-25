"""工具层基座：ToolSpec / ToolResult / ToolRegistry / 参数校验。

## 为什么要有一层"工具"

原来 A/B 直接调 `store`、`providers` 的函数。一旦智能体由 LLM 驱动，这就不够了：
- LLM 需要"手写 JSON 去改表" → 一次转义错误就写坏数据，而且**每改一行都占一轮思维链**；
- 没有统一输入校验 → 参数错了要到深处才炸；
- 没有统一的**副作用声明** → 无法判断某个动作要不要审批；
- 同一套能力在"脚本模式"和"LLM 模式"下要写两遍。

工具层把"标准操作"固化成**有名字、有 schema、有校验、有结构化返回、声明副作用**的原子动作。
智能体的思维链只花在"判断该调哪个工具"，不花在"怎么把参数拼对"。

## 两个刻意的设计

1. **`side_effect` 是一等公民**。`none` / `read` 的工具可以任意调用、不需要审批；
   `write_local` / `network` 的需要。把审批判断建立在**声明**上，而不是靠人记。
   这也是为什么 C 的图分析全部是 `read` —— 它应当能被任意组合地反复查询。

   本层还声明**第二根正交轴** `external`（见 `EXTERNAL`）：`side_effect` 把
   "能不能改**我们拥有**的东西"与"能不能触到**我们不拥有**的东西"压进了同一个
   取值，于是 `verify.run_experiment`（既写实验记录、又执行调用方给的脚本）
   在一根轴上必须二选一，另一个事实被丢掉。两根轴的取值互相独立，
   审批（`needs_approval`）与沙箱（`sandbox_required`）由它们**推导**，
   不落成逐工具的布尔字段（`DEVELOPMENT.md` §3 纪律 6：派生态不许当输入）。
   `network` 是**遗留取值**，只活到 B3 结束；它由 `LEGACY_SIDE_EFFECTS`
   显式翻译成两根轴上的值，**不许静默重新解释**。

2. **参数校验自己实现，不引第三方依赖**。只需要 object/array/string/integer/number/boolean
   与 required/enum/items/bounds 这几样；为此引入 `jsonschema` 会让"工具层能不能用"
   依赖于环境里有没有装它。工具层是**所有智能体的公共底盘**，它的依赖越少越好。
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查；运行期不导入（避免模块级耦合）
    from pathlib import Path

    from ..contextbudget import ContextBudget

#: 副作用等级。顺序即"危险程度"，便于比较。
#:
#: ⚠️ `network` 是**遗留取值**（P-13 的 B1/B2 兼容期），它是把两根正交轴压在一根轴上
#: 的产物：它把"出网"与"起子进程"折叠成同一档。迁移期里它继续被接受、
#: 继续让工具需要审批（**行为不变**），但必须由 :data:`LEGACY_SIDE_EFFECTS`
#: 显式翻译成两根轴上的值，并被 lint 数出来（`scripts/lint_rules.py` 的 R010）。
#: B3 结束时它要从这里**删掉**（与 `capabilities.SIDE_EFFECTS` 是同一个原子改动，
#: 见 `capabilities.assert_capabilities` 第 5 条）。
SIDE_EFFECTS = ("none", "read", "write_local", "network")

#: 第一根轴：能不能改**我们拥有**的东西（数据表 / 工作区）。
EFFECT = ("none", "read", "write_local")

#: 第二根轴：能不能触到**我们不拥有**的东西。
#:
#: - `none`：触不到；
#: - `egress`：**出网**；
#: - `exec`：在宿主上执行一个**由调用方决定内容**的程序。
#:
#: 取值清单**只有这一份**（FC-03）。`capabilities.py` 不再写第二份字面量，
#: 而是 import 这里 —— 它与 `SIDE_EFFECTS` 的交叉断言（第 5 条）已在导入期
#: 钉住两处必须逐字一致，新增一根轴沿用同一种形态，而不是发明第二套机制。
EXTERNAL = ("none", "egress", "exec")

#: 需要审批的**遗留**副作用等级（无人值守场景下）。
#:
#: 新轴下审批是**推导**出来的（见 :attr:`ToolSpec.needs_approval`），这张表
#: 只为遗留取值保留"行为不变"：声明 `network` 的工具在迁移期**继续需要审批**，
#: 哪怕两根轴上的翻译结果（`egress` + `read`）在新规则下只要求沙箱、不要求人工签字。
#: 不做这条例外，"迁移期行为不变"就是一句假话 —— 两个只读检索工具会在迁移中
#: 悄悄免掉审批，而那正是 P-13 §5 明令必须先算清楚的那张表。
NEEDS_APPROVAL = ("write_local", "network")

#: 遗留取值 -> 两根轴上的显式翻译表，语义是 `(external, effect)`。
#:
#: 为什么必须有这张表而不是"默认翻译"：`network` 这个取值本身**丢掉了**它到底是
#: 出网还是起进程，也丢掉了它是否同时写我们的东西（`search.download` 下到
#: `downloads/`、`ocr.run` 首次构造 Reader 会下模型）。静默把它读成 `egress + none`
#: 会把那两处"写"的事实再丢一次。
#:
#: 效果一栏给的是**默认**值：`effect="none"`，它恰好也是 `network` 这个取值
#: 字面上说过的话（"不改我们的东西"）。逐工具的原意见 :data:`LEGACY_EFFECTS_BY_TOOL`。
LEGACY_SIDE_EFFECTS: dict[str, tuple[str, str]] = {"network": ("egress", "none")}

#: 逐工具的遗留原意（**翻译表的效果一栏**的覆盖值），键是工具名。
#:
#: 为什么逐工具值必须写下来：`network` 丢掉的那个事实只有工具作者知道。
#: 实测快照里两个工具用同一个遗留取值，却分属两根轴上不同的效果：
#:
#: - `search.download`：把 pdf 下到工作区 `downloads/` ⇒ 它**写我们的东西**
#:   （P-13 §4.2 第 3 条逐字登记了这一点："旧词表把它压成 network、于是写的事实被丢掉"）；
#: - `ocr.run`：首次构造 easyocr Reader 会下约 100MB 模型并 mkdir 模型目录
#:   ⇒ 按现状口径同 `ocr.backends`，归 `write_local`（P-13 §4.2 第 4 条）。
#:
#: 另两个（`search.providers` / `search.literature`）真的只发 HTTP、不落库，
#: 于是它们的 `effect` 就是翻译表的默认值 `none` 的**升级**：`read`
#: —— 它们读我们拥有的东西（`literature` 表 / 工作区）并出网。
#: 四个都写下来（而不是只写两个例外）是为了让"还剩几处遗留、各自是什么"
#: 有一份**人可逐条审**的清单，而不是靠推导去猜哪几个是缺省。
#:
#: `scripts/lint_rules.py` 的 R010 会断言这张表的键集合与全仓
#: `side_effect="network"` 的工具集合**逐条相等** —— 少一个键 ⇒ 那条 `info`
#: 会变红（新出现的遗留工具必须显式登记原意），多一个键 ⇒ 同一条 `info`
#: 会报"这里有一条翻不出来的翻译"（B3 删掉 `network` 之后它就是空表）。
LEGACY_EFFECTS_BY_TOOL: dict[str, tuple[str, str]] = {
    "search.providers": ("egress", "read"),
    "search.literature": ("egress", "read"),
    "search.download": ("egress", "write_local"),
    "ocr.run": ("egress", "write_local"),
}

#: 六件套里"必须由 `ToolSpec.__post_init__` 校验"的那几件。
#:
#: `name` / `summary` / `params` / `side_effect` 的校验是无条件的（见
#: :meth:`ToolSpec.__post_init__`），`roles` 是结构性的（必须是元组）。
#: **`returns` 是这里唯一的例外**，理由必须写下来，否则下一个人会以为
#: "六件套校验"是一句空话：
#:
#: - `returns` 的**非空**校验会命中 `src/agentflow/agent_d.py` 里三个**内置降级替身**
#:   工具（`trace.relation` / `trace.concept` / `trace.literature`），而那个文件
#:   不在本轮授权的改动范围内（P-13 的分批清单里也没有它）；
#: - 于是本轮的口径是：`returns` **必须给且必须是字符串**（给空字符串 = 你确认过它
#:   没有可声明的返回形态），但"别忘了写"这件事由 `DEVELOPMENT.md` §4.3 第 1 项的
#:   census 观察 —— 而 census 本来就在那条 DoD 项的判据里。
#:
#: 这是一条**有代价**的取舍，不是"文档说严、代码说松"：上面两条理由就是它的代价，
#: 而它换来的是"六件套的其他五件真的有门" + "本轮不越界改文件"。
#: 修掉它只需要给那三个替身补 `returns=`（一条声明，不涉行为）。
REQUIRED_NON_EMPTY_FIELDS: tuple[str, ...] = ("name", "summary", "params")

#: 沙箱可用性（三态）。`DEVELOPMENT.md` §3 纪律 1：把"没声明沙箱"与
#: "声明了沙箱正在用"折叠成同一个布尔，正是本仓库三态纪律禁止的形态。
#:
#: - `True`：沙箱**已声明可用**（起进程/出网由它承接）；
#: - `False`：**已声明不可用**（这才是"升级为人工审批"的判据）；
#: - `None`：**未声明**（默认）。它与 `False` 等价地保守（需要审批），
#:   但在报告里必须能分开：一个是"我们查过，没有沙箱"，一个是"我们没说过"。
SANDBOX_AVAILABLE: bool | None = None


class ToolError(RuntimeError):
    """工具执行失败。调用方只需捕这一个类型。"""

    def __init__(self, message: str, *, tool: str = "", detail: Any = None):
        super().__init__(message)
        self.tool = tool
        self.detail = detail


class ParamError(ToolError):
    """参数不合法。与"执行中失败"分开，便于上层区分"调用方写错了"和"环境出问题了"。"""


# ---------------------------------------------------------------- 结果


@dataclass
class ToolResult:
    """工具的统一返回。

    **不抛异常表达"业务上的失败"** —— 例如"没找到这个概念"。那种情况返回
    `ok=False` 并给出 `error`，让智能体看到并决定下一步；抛异常会打断它的循环。
    只有**调用方写错**（参数不合法）与**环境故障**才抛。
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
        """按上下文预算剪枝 / 落盘 `data` 里的大字符串（FC-17），返回**新**结果。

        为什么剪枝是**显式**的，而不是在 `ToolRegistry.call` 里自动做：
        自动剪会悄悄改变所有既有调用方拿到的返回值，于是"没开剪枝"与
        "开了但没超阈值"在调用方眼里长得一模一样 —— 那正好是本项目最忌讳的
        失败形态（分不清"没做"与"做了没效果"）。入口在这里，剪不剪由调用方决定。

        剪枝**不改结论**：`ok` / `error` 逐字段保留，只有 `data` 变短、`meta`
        多出 `pruned` / `spilled` / `spill_path` / `original_chars` 等审计字段。

        实现**转发**给 `agentflow.contextbudget.prune_tool_result`，且用**局部导入**：
        工具层基座是所有智能体的公共底盘，不该在 import 期就依赖上下文预算模块
        （`contextbudget` 也**不** import 本模块，用鸭子类型 + `dataclasses.replace`，
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


def validate_params(schema: Mapping[str, Any], params: Any, *, path: str = "") -> None:
    """按 schema 校验参数。不合法抛 `ParamError`（不是返回布尔）。

    只支持本工具层实际用到的子集：type / required / properties / enum /
    items / minimum / maximum / minLength / maxLength / minItems / maxItems /
    additionalProperties。刻意不做全量 JSON Schema —— 覆盖面够用即可，
    实现越小越不容易有 bug。

    ⚠️ 这里**必须先看 schema 声明的类型再决定怎么校验**。
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
                raise ParamError(f"出现未声明的参数：{sorted(extra)}（schema 只允许 {sorted(props)}）")
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

    `params` 用 JSON Schema 写（object 根），既用于本层校验，也能**原样喂给
    function-calling** —— 所以它必须自描述、不含 Python 专有类型。

    ## 两根轴（`effect` × `external`）与"六件套"

    `side_effect` 是**声明轴的历史名称**，它把两根正交轴压在一个取值上。
    本类同时给出两根轴上的取值：`effect`（能不能改我们拥有的东西）与
    `external`（能不能触到我们不拥有的事）。`declared_external` 由工具作者
    **人写**（默认 `none`，因为"我没说"不等于"我会出网"）；两根轴的最终取值
    都由属性就地推导（`DEVELOPMENT.md` §3 纪律 6：派生态**就地推导**或
    装配期断言，没有第三种）。

    ⚠️ **AST 只用来核对声明与代码是否一致，绝不用来生成声明**（P-13 §9①：
    N-4 已否决 AST 推断 —— 22/55 取不到 handler 源码、9 个转发型 handler
    是假阳性）。本类里没有一个字符是由 AST 推断出来的：两根轴上的值要么是
    人写的（`declared_external` / `LEGACY_EFFECTS_BY_TOOL`），要么是从人写的 `side_effect`
    按**显式**翻译表算出来的。
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
    #: 必须**人写**；AST **绝不**用它来生成这个值（P-13 §9①）。
    #:
    #: ⚠️ 它是**字段**而不是属性：属性会和 dataclass 的 `__init__(external=...)`
    #: 撞名。第二根轴的**取值**由 :attr:`external` 属性给出（遗留工具那里会
    #: 改用翻译表的值），这个名字只保留"人写下来的那一份声明"。
    declared_external: str = "none"

    def __post_init__(self) -> None:
        """装配期自检：**六件套齐全** + 两根轴的取值受控 + 两根轴不许互相矛盾。

        ## 为什么六件套校验真的在这里（它此前不在这里）

        `DEVELOPMENT.md` §4.3 第 1 项逐字声称"六件套齐全"由本方法校验，
        而实测它只校验了 `side_effect` 与"名字含 `.`"。文档承诺了一个
        不存在的门，比少一条门更危险：读者以为 `summary` / `params` /
        `returns` / `roles` 有人管，于是不再去看。本轮把这条承诺兑现成
        真正的取值校验（见 §4.3 第 1 项与本类测试）。

        ## 判据的形态

        六件套里四件（`name` / `summary` / `params` / `returns`）是**输入**，
        必须是可用的值；`side_effect` 与 `roles` 的"齐全"是**结构性**的
        （受控词表 + 元组），不是"非空"：`roles=()` 是一个真实的声明
        （"这个工具不属于任何角色"），把它判成"缺字段"会把一个可判定的
        事实折叠成错误。

        顺序刻意是**先词表后结构**：`side_effect` 的取值校验必须排在
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
        # ---- 遗留翻译：这条**取值**是受控的，逐工具原意在装配期核（见 build_registry）
        if self.side_effect == "network":
            translated = LEGACY_EFFECTS_BY_TOOL.get(self.name, LEGACY_SIDE_EFFECTS["network"])
            allowed = LEGACY_SIDE_EFFECTS["network"]
            if translated[0] != allowed[0] or translated[1] not in EFFECT:
                raise ValueError(
                    f"LEGACY_EFFECTS_BY_TOOL[{self.name!r}]={translated} 与 "
                    f"LEGACY_SIDE_EFFECTS['network']={allowed} 或 EFFECT={EFFECT} 不一致"
                )
            # 遗留工具的第二根轴由翻译表给出。显式声明了一个**不同**的值时直接拒，
            # 而不是静默取其中一个 —— 两个说法不许同时存在（P-13 §3.2）。
            if self.declared_external != "none" and self.declared_external != translated[0]:
                raise ValueError(
                    f"{self.name} 声明了 external={self.declared_external!r}，但它用的是"
                    f"遗留取值 side_effect='network'（翻译表说 external={translated[0]!r}）"
                    "—— 两个说法不许同时存在：要么把 side_effect 改成两根轴上的确定值，"
                    "要么去掉 external= 让翻译表说话"
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
            # `returns` 的**非空**校验是刻意的弱判据：见 `REQUIRED_NON_EMPTY_FIELDS`
            # 的注释（它会命中 `agent_d.py` 的三个内置降级替身，而那个文件不在
            # 本轮授权范围内）。这里只挡"类型给错"（None / 非字符串），
            # 而"忘了写"由 §4.3 的 census 观察。
            raise ValueError(
                f"{self.name} 的 returns 必须是字符串（空字符串 = 你确认过它没有"
                f"可声明的返回形态），收到 {type(self.returns).__name__}"
            )

    @property
    def external(self) -> str:
        """第二根轴：触不触到**我们不拥有**的事（`none` / `egress` / `exec`）。

        - 非遗留工具：取值就是人写的那个声明（`ToolSpec(..., external="exec")`）；
        - 遗留工具（`side_effect == "network"`）：由 :data:`LEGACY_EFFECTS_BY_TOOL`
          的显式翻译给出（`network` 这个取值本身分不清"出网"与"起进程"，
          而它字面上说过的只是"会做本框架管不住的事"）。
        """
        if self.side_effect == "network":
            return LEGACY_EFFECTS_BY_TOOL.get(self.name, LEGACY_SIDE_EFFECTS["network"])[0]
        return self.declared_external

    @property
    def effect(self) -> str:
        """第一根轴：改不改**我们拥有**的东西。

        - 遗留取值 `network` 走 :data:`LEGACY_EFFECTS_BY_TOOL` 的显式翻译
          （逐工具原意是人写在那张表里的；装配期由 `build_registry` 断言
          "每个声明了遗留取值的工具都在表里"，见那里的 `<legacy>` 检查）；
        - 其余取值与 `side_effect` 同值 —— 这根轴是从那根轴上取下来的，
          不是第二份声明，也不是第二份词表。
        """
        if self.side_effect == "network":
            return LEGACY_EFFECTS_BY_TOOL.get(self.name, LEGACY_SIDE_EFFECTS["network"])[1]
        return self.side_effect

    @property
    def needs_approval(self) -> bool:
        """要不要人工审批。**推导**，不查逐工具布尔位（P-13 §3.3）。

        ```
        needs_approval = (effect == "write_local")
                      or (external != "none" and not sandbox_available)
        ```

        两条与提案字面表述的关系，刻意写在这里而不是留给读者去猜：

        1. 提案把沙箱不可用时的升级写成 `external == "exec"` 一条。本实现还包含
           `egress`：**沙箱不可用时出网同样没有任何承接手段**（提案 §3.3 自己
           也写了这一条），而沙箱可用时两者都被承接、都不再需要签字。
        2. 遗留取值 `network` 继续需要审批（:data:`NEEDS_APPROVAL`）。这是
           "迁移期行为不变"的实现，不是新设计：B3 删掉 `network` 之后，
           `external="egress"` 的只读检索工具在沙箱未声明时才需要审批 ——
           那正是 P-13 §5 那张审批面变化表。
        """
        if self.effect == "write_local":
            return True
        if self.side_effect in NEEDS_APPROVAL:
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
    （此时自动包成 `ok(...)`）；抛 `ToolError` 会被登记为失败结果而**不再向上抛**，
    这样智能体的循环不会因为一次工具失败而中断。

    `external` 见 :class:`ToolSpec`，必须**人写**：本装饰器里没有任何一处
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


class ToolRegistry:
    """按角色组织的工具表。"""

    def __init__(self, *, name: str = "registry"):
        self.name = name
        self._specs: dict[str, ToolSpec] = {}
        self._call_log: list[dict] = []
        self.log_calls = False
        #: ⚠️ **注册表级的默认上下文预算**（FC-17 的接线点）。
        #:
        #: 为什么放在注册表上而不是让每个调用点自己传：FC-17 的实现方如实报告过
        #: "**框架里没有任何调用方真的会传 `budget`**" —— 那条约束当时只有骨架。
        #: 把预算做成**装配期属性**之后，"开启剪枝"只需要在装配处做一次决定，
        #: 而不是指望每个 `_call` 都记得传参数（那种"靠人记得"的设计已经
        #: 在本项目里失败过多次）。
        #:
        #: `None`（默认）⇒ 行为与加 FC-17 之前**逐字节一致**。
        self.default_budget: "ContextBudget | None" = None
        #: 默认的 spill 根目录。装配时设成工作区根 —— 否则 `default_budget` 生效时
        #: 剪枝后的内容**想落盘却没有地方可落**（`prune` 的语义是"没给 root ⇒ 不落盘
        #: 但如实报告"），于是 spill 这一件套永远走不到。
        self.default_spill_root: Any = None
        #: `for_role` 的过滤留痕。空 dict 表示"没有任何工具的 roles 声明需要被纠正"。
        self.role_filter_notes: dict[str, list[str]] = {}

    # ---- 注册
    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._specs:
            raise ValueError(f"工具名重复：{spec.name}")
        self._specs[spec.name] = spec
        return spec

    def register_all(self, specs: Iterable[ToolSpec]) -> None:
        for s in specs:
            self.register(s)

    def register_function(self, fn: Callable[..., Any]) -> ToolSpec:
        spec = getattr(fn, "__tool_spec__", None)
        if spec is None:
            raise ValueError(f"{getattr(fn, '__name__', fn)!r} 不是工具（缺 @tool 标记）")
        return self.register(spec)

    # ---- 查询
    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError:
            close = [n for n in self._specs if name.split(".")[-1] in n]
            hint = f"；相近的有 {close}" if close else ""
            raise ToolError(f"没有名为 {name!r} 的工具{hint}", tool=name) from None

    def names(self) -> list[str]:
        return sorted(self._specs)

    def for_role(self, role: str) -> list[ToolSpec]:
        """某个角色能用的工具。

        ## ⚠️ 只读角色在这里被**结构性**地剥掉两类工具

        `roles` 是**手工声明的**，而"哪些角色是只读的"是一条**设计约束**。
        靠"每个工具作者都记得不把 H 写进 roles"来维持这条约束是**不成立的** ——
        实测就发生过：`table.*` / `fs.*` 把所有角色都写进了 `roles`，
        于是按角色装配出来的"审校者 H 的工具面"里出现了 `table.update`、
        `fs.write`：**H 手里有能改 `documents.claims` 的刀**，
        而"H 只读"正是"发现问题"与"掩盖问题"能被区分开的前提。

        所以这里做一件工具作者无法绕过的事：对 :data:`READ_ONLY_ROLES`，
        **无论 spec 怎么声明**，一律过滤掉（1）有写副作用的工具与
        （2）`external == "exec"` 的工具。

        第二类的理由与第一类**同族**：只读角色的语义是"它在结构上不能改世界"，
        而**执行一个由调用方决定内容的程序**改变了世界（它能写工作区、能出网、
        能起更多进程）—— 所以它与"能改表"一样，不属于只读角色的能力面。
        唯一的例外是**沙箱被声明为可用**（"沙箱承接了这次执行"是一条结构性保证，
        而不是"这个工具变安全了"）；放行同样留痕。

        被过滤掉的名字记在 :attr:`role_filter_notes` 里 —— 之所以要留痕，是因为
        "某个工具本该给 H 却是写工具"是一个**声明错误**，静默过滤会让它永远
        发现不了（而"静默"正是本项目最忌讳的失败形态）。
        """
        from . import READ_ONLY_ROLES, SIDE_EFFECTS_WRITE  # 局部导入避免模块级循环

        out: list[ToolSpec] = []
        refused: list[str] = []
        allowed_by_sandbox: list[str] = []
        for s in self._specs.values():
            if role not in s.roles:
                continue
            if role in READ_ONLY_ROLES:
                if s.side_effect in SIDE_EFFECTS_WRITE:
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
        if refused:
            self.role_filter_notes.setdefault(role, []).append(
                f"按只读角色约束剥掉了 {len(refused)} 个工具（写副作用 或 external=exec）："
                f"{sorted(refused)}"
                "（这些工具的 roles 声明里包含了只读角色，属于声明错误；"
                "行为上已被拦下，但声明本身应改）"
            )
        if allowed_by_sandbox:
            self.role_filter_notes.setdefault(role, []).append(
                f"沙箱已声明可用（SANDBOX_AVAILABLE=True），因此放行了 {len(allowed_by_sandbox)} 个 "
                f"external=exec 的工具：{sorted(allowed_by_sandbox)}"
                "（承接执行的是沙箱，不是'这个工具变安全了'）"
            )
        return out

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
        /,
        *,
        budget: "ContextBudget | None" = None,
        spill_root: "str | Path | None" = None,
        **params: Any,
    ) -> ToolResult:
        """调工具。`budget=None`（默认）时**行为与加 FC-17 之前逐字节一致**。

        ## 为什么 `budget` 必须是关键字且默认为 None

        FC-17 要求"上下文预算三件套必须开"，但把它做成**自动生效**会让既有调用方
        拿到的返回值悄悄变短 —— "没开剪枝"与"开了没超阈值"就再也分不开了。
        所以这里只在**显式**传入 `budget` 时才剪枝：
        `registry.call("fs.read", path=..., budget=b)`。

        ## ⚠️ `budget` 的名字冲突（真实存在，不是假想）

        `attack.check_budget` / `attack.create_plan` **自己就有一个 `budget` 参数**
        （FC-18 的四维预算）。为了不把它们的参数吞掉，消歧规则是**结构性的**、
        且只有一条：

        > 若目标工具的 params schema 里声明了 `budget` 属性，则本关键字属于**工具**；
        > 否则属于**上下文预算**。

        这条规则读注册表就能判断，没有任何隐藏状态。代价是：对这两个工具，
        一次调用里不能同时传"工具的 budget"和"上下文的 budget" —— 需要剪枝时
        用返回值上的 `ToolResult.pruned(budget, spill_root=...)` 第二步做。
        """
        # 查工具这一步也要在 try 里：工具名写错同样属于"调用方写错了"，
        # 应该返回结构化失败让智能体自己纠正，而不是把它的循环打断。
        try:
            spec = self.get(name)
        except ToolError as e:
            return fail(str(e), tool=name, kind="unknown_tool")

        # ---- FC-17：budget 消歧（见 docstring 的规则）
        if budget is not None and "budget" in (spec.params.get("properties") or {}):
            params["budget"] = budget
            budget = None
            spill_root = None

        try:
            validate_params(spec.params, params)
        except ParamError as e:
            return fail(f"参数错误：{e}", tool=name, kind="param_error")
        except ToolError as e:
            return fail(str(e), tool=name, kind="unknown_tool")
        try:
            out = spec.handler(**params)
        except ToolError as e:
            out = fail(str(e), tool=name, kind="tool_error", detail=e.detail)
        except Exception as e:  # noqa: BLE001
            out = fail(f"{type(e).__name__}: {e}", tool=name, kind="unexpected")
        res = out if isinstance(out, ToolResult) else ok(out)
        # ---- FC-17：算出**有效**的上下文预算
        #
        # 优先级：显式传入的 `budget` > 注册表的 `default_budget`。
        # 但有一个例外必须保留：**若目标工具自己声明了 `budget` 参数**，
        # 那么"默认预算"对它不适用 —— 否则 `attack.create_plan` 会在调用方
        # 什么都没传的情况下，被塞进一个它根本不认识的 `ContextBudget` 对象。
        # 这条与上面消歧规则是同一句话的两半。
        eff_budget = budget if budget is not None else self.default_budget
        if eff_budget is not None and "budget" in (spec.params.get("properties") or {}):
            eff_budget = None
        if eff_budget is not None:
            eff_spill = spill_root if spill_root is not None else self.default_spill_root
            res = res.pruned(eff_budget, spill_root=eff_spill)
        # `default_budget=None` ⇒ 什么都不做 ⇒ 与加 FC-17 之前逐字节一致。
        if self.log_calls:
            self._call_log.append({"tool": name, "params": _safe(params), "ok": res.ok, "error": res.error})
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
        json.dumps(value, ensure_ascii=False)
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
