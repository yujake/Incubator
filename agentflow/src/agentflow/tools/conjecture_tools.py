"""猜想台账的产出面（依据 `draft/29` §7.4/§7.5 的状态机、`draft/30` §T1 的数据面）。

## 为什么需要这个模块（T1 留下的那一格）

`conjectures` 表、`CONJECTURE_STATUSES` 词表、以及"跨对象不变量"（`verify.verify_all`
的 `dangling_experiment` / `refuted_without_counterexample` / `proved_without_formal_proof` …）
在 T1 就落了地，而没有任何角色代码写得出这一行 —— T1 的条目逐字写着
"提出 / 检验 / 否证 / 升格这些语义动作在 T3 接线"。于是验收 P7 的第 4 张表
（猜想表：提出→检验→支持/否证/升格）没有任何数据可渲染。

本模块把那半件事接上：一个动作，两个语义（新建 / 更新）。

## 为什么只有一个动作而不是"propose + assess"两个

两个动作会让"第一次写"和"以后改"走两条代码路径，而这两条路径要维护同一组
单行内判据（`schema.Conjecture.validate` 的九条）。合成一个"登记/更新"动作之后：

- 判据只有一份：无论新建还是更新，最后都过 `S.Conjecture(...).validate()`；
- 状态机的"从哪到哪"不需要在这一层再写一遍 —— `validate()` 已经把
  "每条状态必须带什么"写死了（`refuted` 必须有反例实验、`proved` 必须有形式化证明…），
  跨对象那一半在 `verify.verify_all`。

## 三态

`conjecture_id` 省略 ⇒ 新建（编号由 `store.alloc_id("conjecture")` 分配）；
给了它而库里没有这一行 ⇒ 抛（不许把"更新一条不存在的猜想"静默变成新建 ——
那会让一次笔误产生一条重复的猜想，而两条都看起来正常）。
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from typing import Any, Callable, Mapping, Sequence

from .. import schema as S
from ..store import StoreError
from .base import ToolRegistry, ToolSpec, fail, ok, tool

#: 只有 D 能写猜想台账：猜想的提出者与检验者必须能分开（检验是 E 的实验行）。
ROLES = ("D",)


class ConjectureError(ValueError):
    """业务失败（带受控 `kind`），与"调用方写错了"分开报。"""

    def __init__(self, message: str, *, kind: str = "conjecture_error", **details: Any):
        super().__init__(message)
        self.kind = kind
        self.details = details


def _text(value: Any) -> str:
    return str(value or "").strip()


def register_conjecture(
    store: Any,
    *,
    statement: str,
    origin: str,
    conjecture_id: str | None = None,
    testable: Mapping[str, Any] | None = None,
    form: str | None = None,
    negation_statement: str | None = None,
    status: str | None = None,
    experiment_ids: Sequence[str] | None = None,
    proof_experiment_id: str | None = None,
    counterexample_experiment_id: str | None = None,
    promoted_to: Mapping[str, Any] | None = None,
    known_lit_id: str | None = None,
    withdraw_reason: str | None = None,
    notes: str | None = None,
    actor: str = "agent-D",
) -> dict:
    """新建或更新一条猜想。返回落库后的 `conjectures` 行。

    ## 三态在这里的落点：`None` = "调用方没提这件事"

    所有可选参数的默认值都是 `None`（不是 `""` / `"proposed"`）。这一个选择决定了
    更新语义：`None` ⇒ 保留库里已有的值；给了值（哪怕是空串）⇒ 就用给的值。
    若默认写成 `status="proposed"`，一次"只改 notes"的调用会把一条
    `supported_not_proved` 的猜想静默退回 `proposed` —— 那是把
    "我没提状态"读成了"状态是 proposed"。

    新建（没有库里那一份）时兜默认值：`status="proposed"`、`form="universal"`。

    `origin` 必填（防"凭空出现的猜想"，`Conjecture.validate` 逐字要求），
    它的取值就是"这条猜想是从哪来的"——本项目里是 `doc:0000#<label>`
    （被审论文的那一条定理类环境）。
    """
    if not _text(statement):
        raise ConjectureError("statement 不能为空：猜想必须是一条可判真假的陈述句",
                              kind="validation_error")
    if not _text(origin):
        raise ConjectureError(
            "origin 必填：猜想的来源必须可追（本项目里是 `doc:0000#<label>`）",
            kind="validation_error",
        )

    with store.tx("conjectures", "experiments", "literature", "documents",
                  actor=actor, note="register_conjecture") as tx:
        cid = _text(conjecture_id)
        prev: dict = {}
        if cid:
            row = tx.find("conjectures", conjecture_id=cid)
            if row is None:
                raise ConjectureError(
                    f"猜想 {cid} 不存在 ⇒ 不许把一次更新静默变成新建"
                    "（那会产生一条重复的猜想，而两条看起来都正常）",
                    kind="unknown_conjecture",
                    conjecture_id=cid,
                )
            prev = dict(row)
        else:
            cid = tx.alloc_id("conjecture")

        def pick(name: str, given: Any, default: Any = "") -> Any:
            """`None`（没提）⇒ 库里那一份；库里也没有 ⇒ `default`；否则用给的值。"""
            if given is not None:
                return given
            if name in prev:
                return prev.get(name)
            return default

        exp_given = experiment_ids
        if exp_given is None:
            exp_given = prev.get("experiment_ids") or []
        exp_ids = sorted({_text(x) for x in exp_given if _text(x)})
        row_obj = S.Conjecture(
            conjecture_id=cid,
            statement=_text(statement),
            negation_statement=_text(pick("negation_statement", negation_statement)),
            form=_text(pick("form", form, "universal")),
            testable=dict(testable if testable is not None else (prev.get("testable") or {})),
            origin=_text(origin),
            status=_text(pick("status", status, "proposed")),
            experiment_ids=exp_ids,
            proof_experiment_id=_text(pick("proof_experiment_id", proof_experiment_id)),
            counterexample_experiment_id=_text(
                pick("counterexample_experiment_id", counterexample_experiment_id)),
            promoted_to=dict(promoted_to if promoted_to is not None
                             else (prev.get("promoted_to") or {})),
            known_lit_id=_text(pick("known_lit_id", known_lit_id)),
            withdraw_reason=_text(pick("withdraw_reason", withdraw_reason)),
            notes=_text(pick("notes", notes)),
            created_at=str(prev.get("created_at") or S.now_iso()),
            updated_at=S.now_iso(),
            created_by=str(prev.get("created_by") or actor),
        )
        # 单行内判据只有这一处：schema 说不行就是不行（§7.5 状态机的每一句都在这里）
        row_obj.validate()
        # ---- 跨对象的存在性在写入期就核一遍（与 `register_dependency` 的
        # `status='closed'` 同一条纪律）：schema 只能查字段非空，
        # 查不出 `exp:9999` 根本不在库里。`verify.verify_all` 是第二道闸。
        for eid in exp_ids + [row_obj.proof_experiment_id, row_obj.counterexample_experiment_id]:
            if eid and not any(str(r.get("experiment_id")) == eid for r in tx.rows("experiments")):
                raise ConjectureError(
                    f"猜想 {cid} 引用了不存在的实验 {eid!r}："
                    "schema 查不出这一点（它看不见别的表）—— 引用一次不存在的实验，"
                    "等于把一条没有证据的猜想说成有证据",
                    kind="dangling_experiment", conjecture_id=cid, experiment_id=eid,
                )
        if row_obj.known_lit_id and not any(
            str(r.get("lit_id")) == row_obj.known_lit_id for r in tx.rows("literature")
        ):
            raise ConjectureError(
                f"猜想 {cid} 的 known_lit_id={row_obj.known_lit_id!r} 不在 literature 表里："
                "『别人证过』这句话必须指向一篇真的在库里的文献",
                kind="dangling_lit", conjecture_id=cid, lit_id=row_obj.known_lit_id,
            )
        data = row_obj.to_dict()
        tx.upsert("conjectures", data)
    return data


def _not_wired() -> Any:
    """未接线时显式失败（FC-08）：不许把"没接线"读成"库里没有猜想"。"""
    return fail("conjecture 工具未接线（装配时未提供 store）⇒ **没查**，不是『没有猜想』",
                kind="not_wired")


def _guard_result(fn: Any) -> Any:
    """把业务失败变成结构化结果。

    与 `doc_tools.guard_result` 同形（连 `StoreError` 与 `OSError` 都分开报，理由见那里），
    但刻意写成模块私有而不是从 `doc_tools` 导入：工具模块之间目前互不 import
    （`attack_tools` 也是各自一份私有的 `_guard`），而 `doc_tools` 是 G 的模块 ——
    让 D 的工具去 import 它，会把"哪个角色有什么工具"的边界混进 import 图里。
    公开名重名会被 lint 的 R003 抓住（本文件实测过一次），私有名不会。
    """
    try:
        return ok(fn())
    except ConjectureError as e:
        return fail(str(e), kind=e.kind, **e.details)
    except ValueError as e:
        return fail(f"校验失败：{e}", kind="validation_error")
    except StoreError as e:
        return fail(f"存储故障：{e}", kind="store_error")
    except OSError as e:
        return fail(f"文件操作失败：{type(e).__name__}: {e}", kind="io_error")


#: 本模块的工具函数：声明随函数走（`@tool` 把 `ToolSpec` 挂在 `fn.__tool_spec__` 上），
#: `register` 只做装配（`draft/36` 的 `T-8`）。与 `fs_tools` / `table_tools` 同一条路子。
#:
#: 为什么声明不放进"名字 ⇒ 字段"的 dict 表：lint `R010` 是按 `@tool(...)` 装饰器
#: 或 `ToolSpec(name=<字面量>, …)` 读声明的（`scripts/lint_rules.py::_r010_specs`），
#: 表格化成 `ToolSpec(name=变量, …)` 会让它"看不到这条工具"——而它守的正是
#: "声明的 `external` 与 handler 链里实际的出网/起进程是否相符"。所以声明留在
#: 能静态读到的位置，抽出去的是装配这一步。
@tool(
    "conjecture.register_conjecture",
    "登记或更新一条猜想（省略 conjecture_id ⇒ 新建）。"
    "单行内判据只有一份（schema.Conjecture.validate）；"
    "被引用的实验/文献必须在库里",
    {
        "type": "object",
        "properties": {
            "statement": {"type": "string"},
            "origin": {"type": "string"},
            "conjecture_id": {"type": "string"},
            "testable": {"type": "object",
                     "description": "可检验形式（三个键都要给）：{parameters, criterion, falsified_by}"},
            "form": {"type": "string", "enum": list(S.CONJECTURE_FORMS)},
            "negation_statement": {"type": "string"},
            "status": {"type": "string", "enum": list(S.CONJECTURE_STATUSES)},
            "experiment_ids": {"type": "array", "items": {"type": "string"}},
            "proof_experiment_id": {"type": "string"},
            "counterexample_experiment_id": {"type": "string"},
            "promoted_to": {"type": "object"},
            "known_lit_id": {"type": "string"},
            "withdraw_reason": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["statement", "origin"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=ROLES,
    # 键名从一个真实调用读出：落库后的 conjectures 行（`S.Conjecture` 全字段，17 个）。
    returns=(
        "{'conjecture_id','statement','negation_statement','form','testable','origin',"
        "'status','experiment_ids','proof_experiment_id','counterexample_experiment_id',"
        "'promoted_to','known_lit_id','withdraw_reason','notes','created_at','updated_at',"
        "'created_by'}（落库后的 conjectures 行）"
    ),
    tags=("conjecture", "write"),
)
def _conjecture_register_conjecture(store: Any, actor: str, **kw: Any) -> Any:
    """工具体：注入的 `store` / `actor` 由装配期绑定（`partial`），签名与从前逐字相同。

    `T-8` 只搬位置：这一句与原来那个 `lambda **kw: …` 逐字等价
    （`store is None` ⇒ 明确"没接线"，否则走 `_guard_result`）。
    """
    return (
        _not_wired()
        if store is None
        else _guard_result(lambda: register_conjecture(store, actor=actor, **kw))
    )


#: 装配清单：`register` 只遍历它（`T-8`）。
_TOOL_FUNCTIONS: tuple[Callable[..., Any], ...] = (_conjecture_register_conjecture,)


def register(
    registry: ToolRegistry,
    *,
    store: Any = None,
    actor: str = "agent-D",
    **_: Any,
) -> None:
    """装配 D 的猜想台账工具（一个动作，见模块 docstring 的取舍）。

    `T-8`：声明数据在模块级（`@tool` 装饰器），这里只把注入的 `store` / `actor` 绑上去。
    """
    for fn in _TOOL_FUNCTIONS:
        registry.register(replace(fn.__tool_spec__, handler=partial(fn, store=store, actor=actor)))

