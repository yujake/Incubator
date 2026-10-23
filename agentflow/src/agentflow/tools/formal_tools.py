# -*- coding: utf-8 -*-
"""L 的三件工具：`formal.formalize` / `formal.check_formal` / `formal.record`。

## 为什么 L 需要自己的工具面

`run-agent L` 这一条路是"模型 -> 循环 -> `ToolRegistry.call`"，而 L 的三个动作
（`formalize` / `check_formal` / `record`）住在 Python 方法上，不经工具面就到不了模型手里。
照 E 的成例（`verify_tools` 的 handler 惰性构造一个 `AgentE`），这里也惰性构造一个
`AgentL`：于是"工具入口"与"AgentL 方法"共用同一份实现，不会写出字段口径不同的记录。

## 为什么不改 `verify_tools` 的 roles

把 `L` 加进 `verify_tools._ROLES` 只需要一个字符，但那是 FC-27 的 prover-bridge 禁改区，
而且会让 L 的口径与 E 的 `verify.check_formal` 在工具面上重合 —— L 走的是
"自检闸 + E 的实现（函数级复用）"这条路，两条入口的差别（自检、三态形状）
必须看得见。所以 L 的工具挂在自己的组 `formal.*` 下，桥接层仍然只有一份
（`agent_l._CheckFormalL` 继承 E 的实现，最终调到 `verify.check_formal` 那个函数）。

## 三态纪律在这里的落点

- 工具调用成功（`ok(...)`）与结论通过不是一件事：`compile_error` 是一次
  成功的工具调用，data 里 `status="failed"`。所以这里不用 `fail(...)` 表达"命题没通过"
  —— 那会把"查了、不通过"读成"这次调用坏了"；
- 真失败（没接线、参数非法到起不来）才 `fail(...)`：`not_wired` / `param_error`；
- 自检不是 `usable`：`ok(...)` + `status="unknown"` + 一行的 `problems`
  （它不是失败，是"没查成"）。

## 副作用与外部性

`formal.formalize` 写工作区文件（`write_local`）并起检查器子进程（`external="exec"`），
`formal.check_formal` 只读 + 起子进程（`read` + `exec`），`formal.record` 写一行
`experiments`（`write_local`）并**自己再起一次检查器**（`external="exec"`）。
两根轴逐条如实声明 —— `capabilities` 的导入期对账读的就是这几个字面量。
"""
from __future__ import annotations

from functools import partial
from typing import Any

from .. import schema as S
from .base import ToolRegistry, fail, ok, tool

#: 这三件工具只挂给 L：L 是"写 Lean 的那一个"，E 的工具面一个字都不动。
_ROLES_L: tuple[str, ...] = ("L",)


def _not_wired() -> Any:
    """未接线时显式失败（FC-08）：不给一个看起来像结论的空 dict。"""
    return fail(
        "formal.* 未接线（装配时既没有 store 也没有工作区）⇒ 这次什么都没写、也没查",
        kind="not_wired",
    )


def _resolve_root(root: str | Any | None) -> Any:
    """工作区根。`None` ⇒ 进程 CWD（与 `verify_tools._resolve_root` 同一口径）。"""
    from pathlib import Path

    return Path(root) if root else Path.cwd()


def _agent_for(store: Any, root: str | Any | None):
    """惰性构造一个 AgentL（模块级导入会成环：`agent_l` 反过来 import 工具面）。"""
    from ..agent_l import AgentL

    return AgentL(store, workspace_root=_resolve_root(root))


def _formalize_tool(store: Any, root: Any, *, claim: str, source: str,
                    declaration_name: str | None = None,
                    statement_id: str | None = None,
                    proof_no: Any = None, path_source: str | None = None,
                    imports: Any = None, timeout_sec: Any = None) -> Any:
    """`formal.formalize` 的工具体：写盘 + 检查 + 三态（实现全在 AgentL）。"""
    if store is None:
        return _not_wired()
    agent = _agent_for(store, root)
    return ok(agent.formalize(
        claim, source=source, declaration_name=declaration_name,
        statement_id=statement_id, proof_no=proof_no,
        path_source=str(path_source or ""), imports=imports, timeout_sec=timeout_sec,
    ))


def _check_formal_tool(store: Any, root: Any, *, claim: str,
                       script_path: str | None = None, source: str | None = None,
                       declaration_name: str | None = None,
                       imports: Any = None, timeout_sec: Any = None) -> Any:
    """`formal.check_formal` 的工具体：转发到 AgentL（唯一实现）。"""
    if store is None:
        return _not_wired()
    agent = _agent_for(store, root)
    return ok(agent.check_formal(
        claim, script_path=script_path, source=source,
        declaration_name=declaration_name, imports=imports, timeout_sec=timeout_sec,
    ))


def _record_tool(store: Any, root: Any, *, statement_id: str, code_path: str,
                 declaration_name: str | None = None, imports: Any = None,
                 timeout_sec: Any = None, status: str | None = None,
                 verified: Any = None, checker: str | None = None,
                 verifier_output: str | None = None, exit_code: Any = None,
                 for_question_id: str | None = None, notes: str | None = None,
                 proof_no: Any = None, path_id: str | None = None,
                 path_source: str | None = None) -> Any:
    """`formal.record` 的工具体：转发到 AgentL（唯一实现，含现跑对账）。"""
    if store is None:
        return _not_wired()
    agent = _agent_for(store, root)
    return ok(agent.record(
        statement_id, code_path,
        declaration_name=declaration_name, imports=imports, timeout_sec=timeout_sec,
        status=status, verified=verified, checker=checker,
        verifier_output=verifier_output, exit_code=exit_code,
        for_question_id=for_question_id, notes=str(notes or ""),
        proof_no=proof_no, path_id=str(path_id or ""),
        path_source=str(path_source or ""),
    ))


@tool(
    "formal.formalize",
    (
        "把一条命题写成 Lean 源码、落盘到 `code/formal/<声明名>.lean`，再交给检查器真跑一次。"
        "结论三态：verified（检查器说通过）/ failed（检查器说不通过）/ unknown（没查成，"
        "带原因：开关关着 / 自检不过 / 没有检查器 / 超时）。返回里带 `path` / `sha256` / "
        "`exit_code` / `verifier_output` —— 只写「通过」而没有这三样的不算数"
    ),
    {
        "type": "object",
        "properties": {
            "claim": {"type": "string",
                      "description": "被形式化的那条命题（自然语言原文，用于台账与回报）"},
            "source": {"type": "string",
                       "description": "Lean 源码全文：至少一条具名 theorem / lemma"},
            "declaration_name": {
                "type": "string",
                "description": ("源码里要核的那条声明名（也是盘上文件名）；不给时取第一条 "
                                "theorem / lemma 的名字"),
            },
            "statement_id": {
                "type": "string",
                "description": ("被形式化的那一条命题在 `statements` 表里的编号：给了就按它读"
                                "正文与 proof_text（不存在 / 没有正文 ⇒ 受控拒绝）；"
                                "不给时只认「claim 与台账正文逐字相同且唯一」这一种来源"),
            },
            "proof_no": {
                "type": "integer", "minimum": 1,
                "description": ("验的是这条命题的第几份证明（1 = canonical；2 起在同行的 "
                                "`proofs` 清单里）。号不在册 ⇒ proof_path_not_found；"
                                "有两条以上而不给号 ⇒ proof_path_unspecified（一个字节都不写）"),
            },
            "path_source": {
                "type": "string", "enum": ["B", "C", "L"],
                "description": ("这个路径是谁选的：B 指定 / 照 C 的建议 / L 自己决定。"
                                "它记「谁选的」，与「谁验的」（这一行的 recorded_by = L）分开"),
            },
            "imports": {"type": "array", "items": {"type": "string"},
                        "description": "这次检查要加载的库（不给就不注入任何库）"},
            "timeout_sec": {"type": "number"},
        },
        "required": ["claim", "source"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=_ROLES_L,
    returns=(
        "{'checked','verified','claim','reason','detail','verifier_output','missing_imports',"
        "'verifier_status','exit_code','status','problems','lean','lean_path','path','sha256',"
        "'bytes','declaration_name','written','proof_no','proof_sha256','path_id',"
        "'path_source','statement_id','statement_source','coverage','faithfulness',"
        "'steps_path','refused','checker_status','checker_reason','b_library','report'}；"
        "失败（未接线）：ok=False + kind(not_wired)"
    ),
    tags=("formal", "lean", "write"),
    external="exec",
)
def _formal_formalize(_store, _root, **kw: Any) -> Any:  # pragma: no cover - 装配期替换
    """`formal.formalize` 的声明占位（真正的 handler 由 `register` 绑定）。"""
    return _formalize_tool(_store, _root, **kw)


@tool(
    "formal.check_formal",
    (
        "把一段 Lean 源码（`source`）或工作区里的 `.lean`（`script_path`）交给检查器真跑一次。"
        "前置自检不是 usable 时如实回 unknown 并给原因：不起检查器、不抛栈。"
        "查了没通过（compile_error / uses_sorry / extra_axioms / decl_mismatch）与没查成是两件事"
    ),
    {
        "type": "object",
        "properties": {
            "claim": {"type": "string"},
            "script_path": {"type": "string",
                            "description": "工作区里的 .lean 文件（与 source 二选一）"},
            "source": {"type": "string",
                       "description": "Lean 源码全文（与 script_path 二选一）"},
            "declaration_name": {
                "type": "string",
                "description": ("要核对的声明名。不给时由桥接层取**源码里唯一那条**具名声明"
                                "的全名（`namespace` 前缀一并拼上：`LProbe.add_zero_probe`）；"
                                "0 条或多条 ⇒ 受控拒绝（`param_error`，候选名逐个列出），"
                                "不替调用方挑一条 —— 挑错了等于把声明名核对这条判据关掉"),
            },
            "imports": {"type": "array", "items": {"type": "string"}},
            "timeout_sec": {"type": "number"},
        },
        "required": ["claim"],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=_ROLES_L,
    # `draft/146` D29/D30（2026-10-23）：受控拒绝那一支在九格 + L 那四格之外还多给
    # refused / refusal_reason 两格（`status` 本来就在声明里）—— 它们是派发层
    # （`conductor._end_from_payload`）判"这次是受控拒绝"的口子。声明说的是常规返回的
    # 形状，所以这两格不列进键集合，写在下面"受控拒绝那一支"那句里：只在某一条分支上
    # 出现的键，写进那条分支的说明（`agent_l/core.py::_formal_refusal` 只在那条分支上加
    # 它们；本文件这一句如实标注，免得模型把常规返回读成也带这两格）。
    returns=(
        "{'checked','verified','claim','reason','detail','verifier_output','missing_imports',"
        "'verifier_status','exit_code','status','problems','lean','lean_path'}；"
        "受控拒绝那一支（路径越界 / 桥接层受控失败）：data 上多出 refused / refusal_reason "
        "两格，status 落 unknown；失败（未接线）：ok=False + kind(not_wired)"
    ),
    tags=("formal", "lean"),
    external="exec",
)
def _formal_check_formal(_store, _root, **kw: Any) -> Any:  # pragma: no cover - 装配期替换
    """`formal.check_formal` 的声明占位（真正的 handler 由 `register` 绑定）。"""
    return _check_formal_tool(_store, _root, **kw)


@tool(
    "formal.record",
    (
        "把一次形式化检查登记成 `experiments` 表的一行（`method=\"formal\"`）：先按 "
        "`statement_id` 读台账里那条命题的正文，再对 `code_path` 的 `.lean` **现跑一次**"
        "检查器，把现跑得到的 status / verified / checker / output_sha256 写进那一行。"
        "调用方给的读数只用于对账：与现跑不一致 ⇒ 受控拒绝 `reading_mismatch`，一行都不写。"
        "它**不动** `statements`：形式化 ≠ 审过，命题升档仍然要 V 的那一签"
    ),
    {
        "type": "object",
        "properties": {
            "statement_id": {
                "type": "string",
                "description": "台账里那条命题的编号（这一行绑定到它；不在台账里就拒绝）",
            },
            "code_path": {
                "type": "string",
                "description": "工作区里的 `.lean` 相对路径（`code/formal/<名>.lean`）",
            },
            "declaration_name": {"type": "string",
                                 "description": "要核的声明名（不给时取源码里唯一那条）"},
            "imports": {"type": "array", "items": {"type": "string"}},
            "timeout_sec": {"type": "number"},
            "status": {"type": "string",
                       "description": "调用方看到的读数（只对账，不采信）：verified/failed/unknown"},
            "verified": {"type": "boolean",
                         "description": "调用方看到的读数（只对账，不采信）"},
            "checker": {
                "type": "string",
                "description": ("调用方看到的检查器标签（`lean 4.7.0`）。记进那一行的 "
                                "`observations.checker_claimed` 并与现跑那一台对账："
                                "写了版本号而对不上 ⇒ 受控拒绝 `reading_mismatch`；"
                                "不写版本号（只写 `lean`）不拒 —— 那是泛称，不是更强的声称"),
            },
            "proof_no": {
                "type": "integer", "minimum": 1,
                "description": ("这一行绑的是第几份证明（1 = canonical，2 起在 `proofs` 清单里）。"
                                "号不在册 / 有两条以上而不给号 ⇒ 受控拒绝，一行都不写"),
            },
            "path_id": {
                "type": "string",
                "description": ("C 给这条路径的显示名（`p<证明号>g<组号>`）。只做标记，"
                                "不当键：五元位第 4 位的键只能是证明号"),
            },
            "path_source": {
                "type": "string", "enum": ["B", "C", "L"],
                "description": "这个路径是谁选的（B 指定 / 照 C 的建议 / L 自己决定）",
            },
            "verifier_output": {"type": "string",
                                "description": "调用方看到的检查器原话（只对账，不采信）"},
            "exit_code": {"type": "integer"},
            "for_question_id": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["statement_id", "code_path"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=_ROLES_L,
    returns=(
        "{'recorded','experiment_id','statement_id','method','claim','claim_key','status',"
        "'verified','checker','output_sha256','code_hash','path','evidence_kind','result',"
        "'negation_kind','exit_code','verifier_output','statement_evidence_kind_before',"
        "'statement_evidence_kind_after','verification_required','detail','problems','reason',"
        "'proof_no','path_id','proof_sha256','path_source','refused','refusal_reason'}；"
        "失败（未接线）：ok=False + kind(not_wired)"
    ),
    tags=("formal", "lean", "write", "experiment"),
    external="exec",
)
def _formal_record(_store, _root, **kw: Any) -> Any:  # pragma: no cover - 装配期替换
    """`formal.record` 的声明占位（真正的 handler 由 `register` 绑定）。"""
    return _record_tool(_store, _root, **kw)


#: 装配清单：`(工具体函数, 装配期要注入的那几个名字)`。
_TOOL_FUNCTIONS: tuple[tuple[Any, tuple[str, ...]], ...] = (
    (_formal_formalize, ("_store", "_root")),
    (_formal_check_formal, ("_store", "_root")),
    (_formal_record, ("_store", "_root")),
)


def _replace_handler(fn: Any, handler: Any) -> Any:
    """把一个 `@tool` 声明过的函数换成绑定好的 handler（与其它模块同一形态）。"""
    from dataclasses import replace

    return replace(fn.__tool_spec__, handler=handler)


def register(registry: ToolRegistry, *, store: Any = None, root: Any = None,
             **_: Any) -> int:
    """把 L 的两件工具装进注册表；返回装进去的件数。

    `store` 为 None 时照样注册（调用时给 `not_wired`，FC-08）：
    "没接线"与"没写、没查"是两件事，不许折叠。返回值用于
    `tools.build_registry` 的"register 跑通却一件都没装"那条判据。
    """
    added = 0
    for fn, deps in _TOOL_FUNCTIONS:
        bound = {"_store": store, "_root": root}
        registry.register(_replace_handler(fn, partial(fn, *[bound[k] for k in deps])))
        added += 1
    return added


__all__ = ["register"]


#: 本模块只认 L 这一个角色；`schema` 在这里只用来断言"L 真的是合法角色"
#: （拼错一个字母就会让 `roles=("L",)` 被 `ToolRegistry` 静默过滤掉整组工具）。
assert "L" in S.ROLES, "formal_tools 挂给 L，而 schema.ROLES 里没有 L"
