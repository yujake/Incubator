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

2. **参数校验自己实现，不引第三方依赖**。只需要 object/array/string/integer/number/boolean
   与 required/enum/items/bounds 这几样；为此引入 `jsonschema` 会让"工具层能不能用"
   依赖于环境里有没有装它。工具层是**所有智能体的公共底盘**，它的依赖越少越好。
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

#: 副作用等级。顺序即"危险程度"，便于比较。
SIDE_EFFECTS = ("none", "read", "write_local", "network")

#: 需要审批的副作用等级（无人值守场景下）。
NEEDS_APPROVAL = ("write_local", "network")


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
    """

    name: str
    summary: str
    params: Mapping[str, Any]
    handler: Callable[..., Any]
    side_effect: str = "none"
    roles: tuple[str, ...] = ()
    returns: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.side_effect not in SIDE_EFFECTS:
            raise ValueError(f"side_effect 必须是 {SIDE_EFFECTS} 之一，收到 {self.side_effect!r}")
        if not self.name or "." not in self.name:
            raise ValueError(f"工具名建议用 '组.动作' 形式，收到 {self.name!r}")

    @property
    def needs_approval(self) -> bool:
        return self.side_effect in NEEDS_APPROVAL

    def to_dict(self) -> dict:
        """给人/LLM 看的描述。不含 handler（不可序列化）。"""
        return {
            "name": self.name,
            "summary": self.summary,
            "params": dict(self.params),
            "side_effect": self.side_effect,
            "needs_approval": self.needs_approval,
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
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """把普通函数标记成工具。`handler` 直接就是被装饰的函数。

    约定：handler 可以返回 `ToolResult`，也可以返回任意可 JSON 化的值
    （此时自动包成 `ok(...)`）；抛 `ToolError` 会被登记为失败结果而**不再向上抛**，
    这样智能体的循环不会因为一次工具失败而中断。
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

        ## ⚠️ 只读角色在这里被**结构性**地剥掉写工具

        `roles` 是**手工声明的**，而"哪些角色是只读的"是一条**设计约束**。
        靠"每个工具作者都记得不把 H 写进 roles"来维持这条约束是**不成立的** ——
        实测就发生过：`table.*` / `fs.*` 把所有角色都写进了 `roles`，
        于是按角色装配出来的"审校者 H 的工具面"里出现了 `table.update`、
        `fs.write`：**H 手里有能改 `documents.claims` 的刀**，
        而"H 只读"正是"发现问题"与"掩盖问题"能被区分开的前提。

        所以这里做一件工具作者无法绕过的事：对 :data:`READ_ONLY_ROLES`，
        **无论 spec 怎么声明**，一律过滤掉有写副作用的工具。被过滤掉的名字
        记在 :attr:`role_filter_notes` 里 —— 之所以要留痕，是因为
        "某个工具本该给 H 却是写工具"是一个**声明错误**，静默过滤会让它永远
        发现不了（而"静默"正是本项目最忌讳的失败形态）。
        """
        from . import READ_ONLY_ROLES, SIDE_EFFECTS_WRITE  # 局部导入避免模块级循环

        out: list[ToolSpec] = []
        refused: list[str] = []
        for s in self._specs.values():
            if role not in s.roles:
                continue
            if role in READ_ONLY_ROLES and s.side_effect in SIDE_EFFECTS_WRITE:
                refused.append(s.name)
                continue
            out.append(s)
        if refused:
            self.role_filter_notes.setdefault(role, []).append(
                f"按只读角色约束剥掉了 {len(refused)} 个写工具：{sorted(refused)}"
                "（这些工具的 roles 声明里包含了只读角色，属于声明错误；"
                "行为上已被拦下，但声明本身应改）"
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
    def call(self, name: str, /, **params: Any) -> ToolResult:
        # 查工具这一步也要在 try 里：工具名写错同样属于"调用方写错了"，
        # 应该返回结构化失败让智能体自己纠正，而不是把它的循环打断。
        try:
            spec = self.get(name)
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
