# -*- coding: utf-8 -*-
"""交接手稿的工具面（`draft/37` §134）：写 / 读 / 列。

用户口径（逐字）：

> 我觉得各智能体在互相传递信息时可以借助手稿的方式，即建一个收集手稿的文件夹，
> 每个智能体要交接工作前写一份手稿放在里面，且有标号（这个标号靠脚本拿最新的，从 0000 开始顺次标），
> 传信息时就传手稿编号。这样的话派活也有依据，溯源也很清晰。

实现本体只有一份：`agentflow.manuscripts`（编号分配 + 追加式账本 + 读回）。存储是
`manuscripts/handoffs.jsonl`（一行一份交接，`draft/39` §C1 起；旧格式 `.md` 仍读得回来）。
这里只是把它包成工具，让「每个角色」（含只读的 C/H —— 交接手稿不是领域表，
与 `notes/<角色>.md` 同族）都能用。

三件工具：

| 工具 | 谁用 | 作用 |
|---|---|---|
| `manuscripts.write` | 所有角色（含 M） | 交接前写一份（编号由脚本给），返回 `id` —— 它不是工具：走循环形状 `handoff` |
| `manuscripts.read` | A–H | 按编号读全文（留言里传的就是这个编号） |
| `manuscripts.list` | A–H | 列最近的手稿（可按收件人过滤，`to=ALL` 表示广播） |

## 为什么主控 M 不在这张工具面上（口径，别改回去）

M 的工具面是"编排面 + 文件面白名单"（`draft/37` §38/§57，判据
`tests/test_conductor_tools.py::test_m_tool_surface_is_orchestration_only`），
而 `manuscripts.read` / `manuscripts.list` 是领域读面：把它们塞进 M 的面里，
扩的就不是"能不能碰盘"这条边界，而是"M 拿什么读"这条边界 —— 那要先有裁定。
M 不是看不见手稿：它手上有 `fs.list` / `fs.read` / `fs.search`（§38 的白名单），
`manuscripts/` 就在工作区里，读文件这条路本来就通。
"""
from __future__ import annotations

from .. import manuscripts as M
from .. import schema as S
from . import ToolError, ToolResult, fail, ok, tool

#: 读/列交接手稿：「八个角色」（读自己的交接链是本职）。
#: 写不在这里 —— 见下面 `_TOOL_FUNCTIONS` 的理由：写走循环形状 `handoff`。
#: 主控 M 也不在这里 —— 理由见模块 docstring（M 的读面是 fs.* 白名单，扩它要裁定）。
_READ_ROLES: tuple[str, ...] = tuple(S.ROLES)


@tool(
    "manuscripts.read",
    "按编号读一份交接手稿的全文（留言里给你的那个编号）。编号不存在时如实说没有，"
    "而不是返回空文本（『没有这份』与『这份是空的』必须分得开）。",
    {"type": "object",
     "properties": {"id": {"type": "string", "description": "手稿编号（四位，如 0007）"}},
     "required": ["id"], "additionalProperties": False},
    side_effect="read",
    roles=_READ_ROLES,
    # ⚠️ 2026-10-15 补齐（`draft/124` §17）：实跑返回的是整份手稿行（含正文 `body`），
    # 而声明里只列了 `text` 那一格 ⇒ 模型看不到 `body`/`refs`/`format`/`sid`/`created_at`/`task_id`。
    # `returns` 会拼进 function-calling 的 `description`（`tools/base.py:721`）⇒ 模型看得到。
    returns="{'id','path','sender','to','summary','text','sha256','bytes',"
            "'body','created_at','format','note','refs','sid','task_id'}",
)
def manuscripts_read(store, id: str) -> ToolResult:
    """工具体：按编号读全文。"""
    root = getattr(store, "root", None)
    if root is None:
        raise ToolError("manuscripts.read 需要一个带 root 的 store")
    got = M.read(root, id)
    if got is None:
        # ⚠️ **2026-10-16（亲测 A 的工具面时当场撞出来的真 bug）**：这里原写成
        # `raise ToolError(msg, kind="manuscript_not_found")` —— 而 `ToolError.__init__`
        # **不收 `kind`**（只有 `message/tool/detail`）⇒ 本该是"没有这份手稿，去看
        # `manuscripts.list`"的可读拒绝，**变成了 `TypeError: ToolError.__init__() got an
        # unexpected keyword argument 'kind'`**。第一次凭感觉调 `manuscripts.read` 的智能体
        # 会拿到一个 Python 异常，既看不懂也学不到下一步 —— 正是业主说的"会困惑并浪费 token"。
        # 类别要交给工具层的统一出口 `fail(...)`，不要塞给 `ToolError`。
        return fail(
            f"没有编号 {id!r} 的手稿（`manuscripts.list` 看现有的编号）",
            kind="manuscript_not_found", id=id,
        )
    rec = dict(got["record"])
    data = {**rec, "text": got["text"], "path": got["path"]}
    return ok(data, **data)


@tool(
    "manuscripts.list",
    "列交接手稿（默认最近 50 份）。`to` 给角色号可只看发给它的（`to=ALL` 表示广播给所有人的那份）——"
    "交接前先看这里，别重复别人已经写下的结论。",
    {"type": "object",
     "properties": {"to": {"type": "string", "description": "只看发给谁（A–H/M/ALL）"},
                    "sender": {"type": "string", "description": "只看谁写的"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200}},
     "required": [], "additionalProperties": False},
    side_effect="read",
    roles=_READ_ROLES,
    returns="{'count','items':[{id,sender,to,summary,path,created_at}]}",
)
def manuscripts_list(store, to: str = "", sender: str = "", limit: int = 50) -> ToolResult:
    """工具体：列手稿。"""
    root = getattr(store, "root", None)
    if root is None:
        raise ToolError("manuscripts.list 需要一个带 root 的 store")
    rows = M.list_all(root, to=to, sender=sender, limit=int(limit or 50))
    return ok({"count": len(rows), "items": rows}, count=len(rows), items=rows)


#: 装配清单（与 `attack_tools` 同一形态）：`(工具体函数, 需要从装配期注入的名字)`。
#:
#: 「只有读/列两件」：写手稿走循环形状 `handoff`（它知道"我是谁"，文件名要用它），
#: 而工具层拿不到 per-call 的身份（注入的 deps 是装配期的）—— 在这里再放一个 write
#: 只会得到"不知道谁写的交接手稿"，那正是溯源要防的形态。
_TOOL_FUNCTIONS: tuple[tuple[Any, tuple[str, ...]], ...] = (
    (manuscripts_read, ("store",)),
    (manuscripts_list, ("store",)),
)

# ---- 板的两件（`manuscripts.items` / `manuscripts.ack`）暂不注册（2026-10-08 晚，S1b）
#
# 为什么不先挂上去：它们要判两件本层拿不到的事实 ——
#   ① "谁在 ack"（必须知道调用方实例的 `task_id`，那在循环上下文里，
#      落点是 `conductor.current_task_id()`，要先确认装配期 `deps` 里有没有 `conductor`）；
#   ② "这一项是不是发给我的"（按 `to` 目标实例或角色判）。
# 本仓的纪律是"不许挂空：要么真跑，要么不注册"（`draft/44 L-06` 那一族）。
# ⇒ 先把它们从注册面拿掉，等这两处接线确认之后在同一步里补齐（连同
# `tests/test_tools_returns_declaration.py` 的 `observations` 夹具与 `EXECUTED_KEY_SOURCE`）。
# M 的那一半（`conductor.board`）已经真跑，见 `conductor_tools.py`。


def register(registry: Any, *, store: Any = None, **_: Any) -> None:
    """把交接手稿的工具装进注册表。

    `store` 为 None 时「照样注册」（调用时给 `not_wired`，`FC-08`）：
    "没接线"与"没有手稿"是两件事，不许折叠。
    """
    from functools import partial

    from dataclasses import replace

    for fn, deps in _TOOL_FUNCTIONS:
        bound = [store if name == "store" else None for name in deps]
        registry.register(replace(fn.__tool_spec__, handler=partial(fn, *bound)))
