"""只读角色 C 的**产出登记通道**（业主 2026-10-18 裁定「只读角色的产出要能进台账」）。

## 这个模块补的是哪一个洞（先有读数，再谈修法）

真机读数（`projects/mp3` 末节第 5 条）逐字：「`analysis_reports` = 0：C 的图读数没进
登记表（**它面外操作**），只在手稿 000004 与我的报告里」。同一趟的 run 记录
（`projects/mp3/runs/C-20261018-201536-001.json`）里，C 第 4、5 步分别调 `gaps` 与
`handle`，两次都拿到：

    没有名为 'gaps' 的工具 / 没有名为 'handle' 的工具

也就是说，C 的**动作**（`gaps` / `handle` / `paths` / `cold` / `hottest`）从来不在
C 自己的工具面上 —— 它们只能由父代理用 `conductor.summon(role="C", action="gaps")`
唤起。C 被派了一个**空动作**的自由任务时，它手上只有 `graph.*` / `table.*` /
`fs.read` 这些只读工具，写 `analysis_reports` 的唯一实现（`AnalysisReport.persist`）
在它的可调用面之外 ⇒ 它只能把分析写在回复里。这不是"模型不守纪律"，是**通道不存在**。

## 修法（业主裁定：优先复用既有表、不新增表）

新增一个工具 `analysis.register_report`，只挂给 `C`：把这一趟**它自己产出的**分析
登记进 `analysis_reports`（复用 `agent_c._support.AnalysisReport.persist` —— 存盘顺序、
ID 分配、文件名规则都还是那一份实现，不在这里重写一遍）。

三条边界（改这一处时必须同时守住）：

1. **只写 `analysis_reports`**：表级例外 `capabilities.READ_ONLY_WRITE_EXCEPTIONS["C"]`
   里逐字登记了它；工具级例外 `tools.base.READONLY_CALL_EXCEPTIONS["C"]` 里也登记了
   这一个工具名。两处都改才算数（`assert_capabilities` 第 `[5c]` 条守着）。
2. **只挂给 C**：`roles=("C",)`。D 不能拿它写 C 的产出（D 有自己的 `write_report`）。
3. **不碰知识表**：调用链上唯一的写是 `AnalysisReport.persist` 的
   `st.tx("analysis_reports")`；`claims` / `literature` / `relations` 零写入点
   —— 这一条由 `tests/test_readonly_output_channel.py` 用"全表行数前后不变"的
   行为读数守着（不是只写在注释里）。
"""
from __future__ import annotations

from functools import partial
from typing import Any

from .. import schema as S
from .base import ToolRegistry, fail, tool

#: 「这一份报告属于哪一档」的受控词表 —— 与 `schema.REPORT_KINDS` 同一份
#: （D 按 `kind` 分派解析逻辑 ⇒ 表外取值不许进表）。
REPORT_KINDS: tuple[str, ...] = S.REPORT_KINDS


def _not_wired() -> Any:
    """未接线时显式失败（FC-08）：返回"没查成"，绝不返回一个假的 `report_id`。"""
    return fail(
        "analysis.register_report 未接线（装配时未提供 store）⇒ 这一行**没有登记**，"
        "不是「登记了但没有内容」",
        kind="not_wired",
    )


def _persist_analysis_report(
    store: Any,
    *,
    actor: str = "agent-C",
    kind: str,
    summary: str,
    markdown: str,
    request: str = "",
    payload: Any = None,
    params: Any = None,
    warnings: Any = None,
) -> dict:
    """把一份**已经是成品**的分析登记进 `analysis_reports`。

    复用 `agent_c._support.AnalysisReport.persist`：那是 C 落盘的唯一实现
    （先写 markdown 文件、再在同一个事务里拿号写登记行）—— 在这里另写一遍
    "怎么存"会立刻产生第二份口径（`FC-03` 的同族），而两份口径漂开的那一天，
    `reports/<rid>-<kind>.md` 与表里的 `markdown_path` 就对不上了。

    为什么参数里没有 `report_id`：号只能由 `tx.alloc_id("report")` 在持锁的
    事务里取（并发两个 C 实例取到同一个号会让 upsert 静默互相覆盖）。
    """
    # 局部导入：`agent_c._support` 会顺带把 `specs.c` 拉进来，而工具层不该在
    # 导入期依赖声明层（`tools/__init__` 的模块装配顺序见那里的注释）。
    from ..agent_c._support import AnalysisReport

    rep = AnalysisReport(
        kind=str(kind or ""),
        request=str(request or ""),
        params=dict(params or {}),
        summary=str(summary or ""),
        payload=dict(payload or {}),
        markdown=str(markdown or ""),
        warnings=[str(w) for w in (warnings or [])],
    )
    # `kind` / `summary` / `markdown` / `payload` 的合法性由 `persist()` 判
    # （`S.REPORT_KINDS`、非空、可 JSON 序列化）—— 这里不另写一套校验（FC-03）。
    settled = rep.persist(store, actor=actor)
    return {
        "checked": True,
        "report_id": str(settled.get("report_id") or ""),
        "markdown_path": str(settled.get("markdown_path") or ""),
        "kind": rep.kind,
        "summary": rep.summary,
        "created_by": rep.created_by,
    }


@tool(
    "analysis.register_report",
    (
        "把**你自己产出的**分析登记进 `analysis_reports`（kind 取 `hottest|paths|cold|gaps`）——你是只读角色，"
        "这是唯一写入口，不登记等于没发生。"
    ),
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(REPORT_KINDS),
                "description": (f"报告档位（受控词表 {list(REPORT_KINDS)}）："
                                "hottest=最热门概念、paths=两概念间的链条/图读数、"
                                "cold=冷门概念、gaps=候选研究缺口"),
            },
            "summary": {"type": "string", "minLength": 1,
                        "description": "一句话结论（D 的第一入口就是它；不许写成「见正文」）"},
            "markdown": {"type": "string", "minLength": 1,
                         "description": "报告正文（markdown）：读数、判断、边界逐条写清"},
            "request": {"type": "string",
                        "description": "这条分析是被什么要求做出来的（派活原文或你的复述）"},
            "payload": {"type": "object",
                        "description": "机器可读部分（代号链 / 度数表 / 评分明细等），D 溯源用"},
            "params": {"type": "object", "description": "这次分析用的参数（top_n / limit 等）"},
            "warnings": {"type": "array", "items": {"type": "string"},
                         "description": "这一份的已知边界（拿不到的行号、被截断的读数）"},
        },
        "required": ["kind", "summary", "markdown"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("C",),
    returns=("{'checked','report_id','markdown_path','kind','summary','created_by'}"
             "（`checked=False` = 没接线/参数非法 ⇒ 那一行没有登记）"),
    tags=("analysis", "write", "register"),
)
def _analysis_register_report_tool(_not_wired_fn, store, actor, **kw: Any):
    """`analysis.register_report` 的工具体（注入值由装配期 `partial` 绑定）。"""
    return _not_wired_fn() if store is None else _persist_analysis_report(
        store, actor=actor, **kw)


#: 装配清单：`(工具体函数, 需要从装配期注入的名字)`。
_TOOL_FUNCTIONS: tuple[tuple[Any, tuple[str, ...]], ...] = (
    (_analysis_register_report_tool, ("_not_wired_fn", "store", "actor")),
)


def register(registry: ToolRegistry, *, store: Any = None, actor: str = "agent-C",
             **_: Any) -> None:
    """把 C 的产出登记通道装进注册表。

    `store` 为 None 时**照样注册**（调用时给 `not_wired`，`FC-08`）：
    "没接线"与"没有分析"是两件事，不许折叠。
    """
    for fn, deps in _TOOL_FUNCTIONS:
        bound = {"_not_wired_fn": _not_wired, "store": store, "actor": actor}
        registry.register(
            _replace_handler(fn, partial(fn, *[bound[k] for k in deps])))


def _replace_handler(fn: Any, handler: Any) -> Any:
    """把一个 `@tool` 声明过的函数换成绑定好的 handler（与其它模块同一形态）。"""
    from dataclasses import replace

    return replace(fn.__tool_spec__, handler=handler)
