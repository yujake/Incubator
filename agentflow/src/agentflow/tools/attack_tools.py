"""F 的工具：多轮难题攻坚。

## [为什么] 为什么"攻坚"需要独立的预算模型

D 的问题生命周期是"缺口 → 补证据 → 研究 → 回答"：它有终点，因为
"证据够了"是一个可判定的条件。而难题攻坚没有这个性质 —— "还没做出来"
永远成立，所以一个没有预算的攻坚循环会一直跑下去，而且它跑得越久，
看起来越像在工作。

因此本模块把三维预算（FC-18）做成可机械检查的东西：

- `max_rounds` —— 生命周期总量：这个难题总共允许几轮；
- `max_parallel_subgoals` —— 瞬时并发：一轮里允许同时推进几个子目标；
- `max_persist_attempts` —— 单点重试：同一个子目标最多重试几次；
- `max_depth` —— 嵌套深度：攻坚中派生出的新难题最多嵌套几层。

只有总量没有并发 ⇒ 一轮可以无限扇出（瞬时打爆配额）；
只有并发没有总量 ⇒ 扇出可以无限持续（永不停止）。
两类必须同时存在，缺一类就等于没有上限。

## [契约] `can_round` 的两个维度不能混为一谈（读代码前先看这一段）

`can_round(budget, rounds_done=..., depth=...)` 同时检查两件事，但它们的
后果完全不同：

- 轮数用尽 ⇒ 这个计划该停了（交出 `best_partial`，标 `stalled`）；
- 深度到顶 ⇒ 不能再派生新的子计划，但这个计划本身的轮次照常推进。

把后者也当成"该停了"，会让一个深度恰好到顶的计划连第一轮都跑不了 ——
那是把"不能再分子问题"误读成了"这个问题不能做"。所以 `AgentF.step` 只在
轮数维度用 `can_round` 做终止判据（见 `agent_f.py` 的说明），
深度维度由 `can_derive` 单独暴露给"要不要派生"这个决策。

## [契约] 工具与智能体的分工

`attack.create_plan` / `attack.step` / `attack.status` / `attack.list_plans`
是对 `agentflow.agent_f.AgentF` 的薄封装（惰性导入避免成环）：写入逻辑只有一份。
`attack.check_budget` / `attack.pick_next_subgoal` 是纯函数，直接在这里实现，
`AgentF` 转发过来 —— 与此前一样，"不要发明第二套判据"。

## [踩过] 六个 handler 都过 `_guard`（修过的缺陷；`DEVELOPMENT.md` §3 纪律 3）

六个 handler 此前只有"成功"一条路：`PlanError` / `schema` 的 `ValueError` /
`StoreError` 会直接逃出工具层，被 `tools/base.py` 兜成 `kind="unexpected"`。
那是已知失败原因，不是"未预期的异常" —— 调用方要靠 kind 决定"重试还是改输入"
（`DEVELOPMENT.md` §3 纪律 3）。现在每一支都有受控 kind：

- `PlanError` ⇒ `kind="plan_error"`（带原始原因）；
- `ValueError`（`schema` 行校验）⇒ `kind="validation_error"`；
- `StoreError` ⇒ `kind="store_error"`；
- 未接线仍走 `_need_store()` ⇒ `kind="not_wired"`。

守卫实现只有一份（本模块的 `_guard`），`graph_tools` 从本模块 import 它。
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from typing import Any, Callable, Sequence

from ..store import StoreError
from .base import ParamError, ToolError, ToolRegistry, ToolResult, ToolSpec, fail, ok, tool

#: 读计划的角色：F 做攻坚；D 会把"多轮未收敛的问题"升级给 F，所以要能读；
#: G 需要读攻关结论来写稿；H 需要核对"stalled 有没有谎报成 resolved"。
_READ_ROLES = ("F", "D", "G", "H")

#: 写计划的角色：只有 F。
#:
#: 为什么把 `create_plan` / `step` 收窄到 F 一个人（而读侧仍是四个角色）：
#: "谁需要看见这件事"与"谁有权决定这件事"是两个不同的问题。
#: 让 D/G/H 也能立项或推进，就等于把 F 的终止条件暴露给三个不受其预算约束的
#: 调用方 —— 而"多轮攻坚必须有唯一的主人"正是 FC-18 那套预算能成立的前提。
#: 收窄的成本只是 D 想立项时要显式调用 `AgentF`（一次有意的决定），
#: 收益是"谁会推进这个计划"这个问题有唯一答案。
_WRITE_ROLES = ("F",)

#: 默认预算。数字本身可以调，但四类键必须都在（见 `check_budget`）。
DEFAULT_BUDGET: dict[str, int] = {
    "max_rounds": 6,
    "max_parallel_subgoals": 2,
    "max_persist_attempts": 2,
    "max_depth": 2,
}

_REQUIRED_BUDGET_KEYS = ("max_rounds", "max_parallel_subgoals", "max_persist_attempts", "max_depth")

#: 终结状态（不能自动重入）。`stalled` 也在其中：它表示"预算用尽仍未解决"，
#: 不是"暂时停下等一会儿"。把它排除在外，循环下一轮就会把它当活计划重新拾起，
#: 于是"预算用尽"这个终止条件形同虚设。
#: 不再自持一份名单：它就是 `schema.ATTACK_TERMINAL_STATUSES`。
#:
#: 这里原先写死 `("resolved","abandoned","stalled")`，漏了 `supported_not_proved` ——
#: 而 `agent_f` 会真的写它。后果是一个已达终态的计划被当成活计划重新拾起。
#: 两处名单的存在本身就是缺陷（FC-03）：同一个"终态"概念不可能有两个定义。
from ..schema import ATTACK_TERMINAL_STATUSES as TERMINAL_STATUSES  # noqa: E402
#: 子目标状态的**词表**（`pick_next_subgoal` 要在给结论之前拿它校验：
#: 状态写错时若直接回"没有可推进的子目标"，就把输入写错读成了"确实没有待办"）。
from ..schema import SUBGOAL_STATUSES as SUBGOAL_STATUSES  # noqa: E402


def check_budget(budget: dict | None) -> dict:
    """检查预算是否完整、是否还允许再开一轮。纯函数，不碰存储。

    返回 ``{"checked", "complete", "missing", "allowed", "reason"}``。

    三态在这里的具体形态：`checked=False` 表示"没检查"（没给预算），
    而 `allowed=False` 表示"检查了、不许"（预算用尽）。把这两者折叠成同一个
    `False`，就会让"我们忘了配预算"看起来像"预算用完了"。
    """
    if budget is None:
        return {
            "checked": False,
            "complete": False,
            "missing": list(_REQUIRED_BUDGET_KEYS),
            "allowed": None,
            "reason": "没有提供预算 ⇒ **没检查**。注意这与'预算用尽'是两件事",
        }
    missing = [k for k in _REQUIRED_BUDGET_KEYS if k not in budget]
    if missing:
        return {
            "checked": True,
            "complete": False,
            "missing": missing,
            "allowed": False,
            "reason": (
                f"预算缺少 {missing}。三维预算缺一不可（FC-18）："
                "只有轮数上限则单轮可无限扇出，只有并发上限则可无限轮"
            ),
        }
    return {
        "checked": True,
        "complete": True,
        "missing": [],
        "allowed": True,
        "reason": f"预算完整：{ {k: budget[k] for k in _REQUIRED_BUDGET_KEYS} }",
    }


def can_round(budget: dict | None, *, rounds_done: int, depth: int = 0) -> dict:
    """在给定预算与已做轮数下，能否再开一轮。

    返回里的 `allowed=False` 可能来自两个不同维度（轮数 / 深度），
    调用方必须看 `blocked_by` 再决定处置（见模块 docstring）。

    `blocked_by` 是受控词表（五个取值，`None` 表示"没有阻塞"）：

    ====================  ============  ==============  ==========================
    取值                    checked       allowed         含义
    ====================  ============  ==============  ==========================
    `None`                 `True`        `True`          允许再开一轮
    `"not_checked"`        `False`       `None`          没查（没给预算）
    `"incomplete"`         `True`        `False`         查了：预算缺键
    `"rounds"`             `True`        `False`         查了：轮数用尽
    `"depth"`              `True`        `False`         查了：深度到顶
    ====================  ============  ==============  ==========================

    刻意不放进 `schema.py`（那是禁 AI 区，而且这是工具层的返回词表，
    不是跨模块的领域词表）：`tests/test_tools_attack_graph_fixes.py` 逐支穷举
    这个函数与 `can_derive` 的全部分支，把这五个取值钉住 —— 新增取值会红。
    """
    chk = check_budget(budget)
    if not chk["checked"]:
        return {**chk, "allowed": None, "blocked_by": "not_checked"}
    if not chk["complete"]:
        return {**chk, "blocked_by": "incomplete"}
    assert budget is not None
    mr = int(budget["max_rounds"])
    md = int(budget["max_depth"])
    if rounds_done >= mr:
        return {
            **chk,
            "allowed": False,
            "blocked_by": "rounds",
            "reason": f"轮数已用尽 {rounds_done}/{mr} ⇒ 停止（此时必须交出 best_partial，而不是谎报成功）",
        }
    if depth >= md:
        return {
            **chk,
            "allowed": False,
            "blocked_by": "depth",
            "reason": f"嵌套深度已到上限 {depth}/{md} ⇒ 不再派生新的攻坚计划",
        }
    return {
        **chk,
        "allowed": True,
        "blocked_by": None,
        "reason": f"允许第 {rounds_done + 1} 轮（上限 {mr}）",
    }


def can_derive(budget: dict | None, *, depth: int) -> dict:
    """能否从当前深度派生一个子计划（`depth+1`）。

    与 `can_round` 分开是有意的：一个计划"自己还能跑"与"还能再分子问题"
    是两个独立的问题，共用一个布尔会让深度到顶的计划被误判成"该停了"。

    ## 三态（这一条曾经是缺陷）

    `blocked_by` 的取值必须把"没查"与"查了但不完整"分开：

    ====================  ============  ==============  ==========================
    情形                    checked       allowed         blocked_by（受控值）
    ====================  ============  ==============  ==========================
    没给预算（没查）         `False`       `None`          `"not_checked"`
    预算缺键（查了、不完整）  `True`        `False`         `"incomplete"`
    派生后超过 `max_depth`   `True`        `False`         `"depth"`
    可以派生                 `True`        `True`          `None`
    ====================  ============  ==============  ==========================

    修之前这里把前两行折叠成同一个 `blocked_by="incomplete"`。后果不是"少一个
    标签"，而是调用方无法区分两件处置完全不同的事：

    - `"not_checked"` ⇒ 我们根本没拿到预算 ⇒ 该去把预算传进来（或承认这次判定没做）；
    - `"incomplete"` ⇒ 预算在、但缺键 ⇒ 该去补那几类键（`missing` 逐条列出）。

    把前者说成"信息不全"，调用方会以为"查过了、只是信息不全"，于是继续往下走
    —— 而它其实一个判定都没做（`DEVELOPMENT.md` §3 纪律 1 与纪律 5 的同一形态）。
    这也是模块 docstring 里那句"`can_round(budget, ...)` 同时检查两件事"的同一个
    教训：两件结果不同的事不许共用一个标签。

    `allowed` 同样是三态：`None` 表示没判定（没查），`False` 表示判定了、不许。
    与 `can_round` 的 `blocked_by="not_checked"` 那一支逐字同形（同一份口径）。
    """
    chk = check_budget(budget)
    if not chk["checked"]:
        return {**chk, "allowed": None, "blocked_by": "not_checked"}
    if not chk["complete"]:
        return {**chk, "allowed": False, "blocked_by": "incomplete"}
    assert budget is not None
    md = int(budget["max_depth"])
    if depth + 1 > md:
        return {
            **chk,
            "allowed": False,
            "blocked_by": "depth",
            "reason": f"当前深度 {depth}，派生后为 {depth + 1} > max_depth={md} ⇒ 不许再分子问题",
        }
    return {
        **chk,
        "allowed": True,
        "blocked_by": None,
        "reason": f"当前深度 {depth}，派生后为 {depth + 1} <= max_depth={md}",
    }


def pick_next_subgoal(subgoals: Sequence[dict]) -> dict:
    """选下一个要推进的子目标。确定性排序，不看运气。

    次序（每一步都是"为什么它更该先做"）：

    0. **不在等子目标的**先选（见下面那一段 P4-7）；
    1. `in_progress` —— 已经开始的最先接着做（避免半途而废的子目标永远烂在那里）；
    2. `todo` 且 `owner` 有明确归属 —— 可执行的优先；
    3. `blocked` —— 排在最后（它需要先解决卡点，而不是重试）。

    `closed` / `dropped` / `supported_not_proved` 一律不选：前两者是终态，
    第三者表示"数值支持但没有证明" —— 它已经被推进到本框架能推进的尽头了，
    再选它只会把资源从真正待办的子目标上挪走（FC-22）。

    ## 0. `waiting_on`：父目标不许永远压住它派出去的子目标（`draft/44` 的 P4-7）

    改前的次序是"`in_progress` 最先"，而 `counterexample_request` / `reduction` 造出新
    子目标之后**父目标仍是 `in_progress`** ⇒ 每一轮都重新选中父目标，新子目标永远停在
    `todo`（真机：`s1/s5/s6` 一直 `todo`，计划一轮一轮地在父目标上打转）。

    现在父目标身上会写一个 `waiting_on: [子目标号…]`（`agent_f._apply_round` 那一跳），
    这里按它排序：**只要它等的那几条里还有能干的（`todo`/`in_progress`），父目标就排到
    最后**。两条边界写清：

    - 等的那几条全都做完了 / 都被卡住了 ⇒ 父目标立刻恢复可选的次序首位
      （否则"等"会变成死锁）；
    - 全部子目标都在等（互相等）⇒ 仍然按原次序选一个（**不许返回"没有可推进的"** ——
      那会把死锁读成"计划已经没事可做"）。

    全部不可选时返回 ``{"picked": False, "reason": ...}`` ——
    不能返回 None 让调用方自己猜。
    """
    def rank(sg: dict) -> tuple:
        st = str(sg.get("status") or "")
        order = {"in_progress": 0, "todo": 1, "blocked": 2}
        return (order.get(st, 9), str(sg.get("sid") or ""))

    # ⚠️ **2026-10-16（亲测 D 的 `attack.*` 时抓到的）**：这里原本直接过滤，
    # 于是**状态写错**（我用 `pending`/`done`，而词表是
    # `("todo","in_progress","supported_not_proved","closed","blocked","dropped")`）
    # 会掉进下面那条"没有可推进的子目标" ⇒ 把"**输入写错了**"读成"**确实没有待办**"，
    # 正是本仓最在意的"没查成写成查了没有"。先校验词表，如实说清是输入的问题。
    unknown = sorted({str(s.get("status") or "") for s in subgoals
                      if str(s.get("status") or "")} - set(SUBGOAL_STATUSES))
    if unknown:
        return {
            "picked": False,
            "subgoal": None,
            "kind": "unknown_subgoal_status",
            "reason": (f"这些状态不在词表里：{unknown}；合法状态是 {list(SUBGOAL_STATUSES)}。"
                       "这一条**没说成**『没有可推进的子目标』—— 把输入写错读成『确实没有待办』，"
                       "会让上层以为攻坚已经无事可做。"),
        }
    pool = [s for s in subgoals if str(s.get("status") or "") in ("in_progress", "todo", "blocked")]
    if not pool:
        return {
            "picked": False,
            "subgoal": None,
            "reason": "没有可推进的子目标（全部 closed/dropped/supported_not_proved 或列表为空）",
        }
    # 还在等的那几条里"能干的"（`todo`/`in_progress`）—— 等它们把活做完，父目标才回来。
    workable = {str(s.get("sid") or "") for s in subgoals
                if str(s.get("status") or "") in ("todo", "in_progress")}

    def waiting(sg: dict) -> list[str]:
        return [str(x) for x in (sg.get("waiting_on") or []) if str(x) in workable]

    blocked_by_wait = {str(s.get("sid") or "") for s in pool if waiting(s)}
    # 全部都在等 ⇒ 不许判"没有可推进的"（那是把死锁读成"没事可做"），按原次序选一个。
    if len(blocked_by_wait) == len(pool):
        blocked_by_wait = set()

    def order_key(sg: dict) -> tuple:
        return ((1 if str(sg.get("sid") or "") in blocked_by_wait else 0),) + rank(sg)

    pool.sort(key=order_key)
    chosen = pool[0]
    sid = str(chosen.get("sid") or "")
    waited = waiting(chosen)
    reason = f"按确定性次序选中 {sid}"
    if sid in blocked_by_wait:
        reason += f"（在等 {waited}；它们都做完/被卡住之后它的次序会恢复）"
    return {"picked": True, "subgoal": chosen, "reason": reason}


def _root_for(root: Any, store: Any) -> Any:
    return root if root is not None else getattr(store, "root", None)


def _agent_for(store: Any):
    """构造一个 AgentF。惰性导入：agent_f 反向引用本模块，模块级导入会成环。

    ## 两条装配期登记（`draft/44` J-07：工具路径拿不到 host 的装配上下文）

    1. 缝从 `agent_f.default_llm()` 取（`draft/39` §6.33 的 D42c）：真机里 M 派
       `F.step` 走的就是这一条工具路径，而 host 那一侧接好的缝到不了这里 —— 于是
       T2 第 14 趟（`--attack-reasoning` 开着）`F.step` 仍然连续 5 次 `no_change`。
    2. 配置从 `llmseam.role_config("F", <工作区根>)` 取（按 root 键，见那张表的
       docstring）：不取的话 F 的预算四键在工具路径上永远是空 dict
       （`J-07` 实测：那四个键全仓无赋值点）。

    两条都没登记时与不传逐字同形（`llm=None` / `config=None ⇒ {}`）——
    默认确定性不变，落 `dead_end(缺工具)` 并如实说未接线。
    """
    from ..agent_f import AgentF, default_llm  # 惰性：避免 tools ↔ agent 的循环导入
    from ..llmseam import role_config

    root = str(getattr(store, "root", "") or "")
    return AgentF(store, llm=default_llm(), config=role_config("F", root))


#: `PlanError` 在工具层映射出的 `kind`。
#:
#: 为什么不叫 `"tool_error"`（修之前的形态）：`PlanError` 是具体的已知失败
#: （计划不存在 / 子目标缺 owner / 预算不完整），而 `tool_error` 是兜底的一档。
#: 调用方要靠 kind 决定"重试还是改输入"，两者混在一档就无法决定
#: （`DEVELOPMENT.md` §3 纪律 3：`refused` 与 `failed` 不许折叠）。
PLAN_ERROR_KIND = "plan_error"


def _plan_error_kind(exc: Exception) -> str:
    """取异常在工具层应映射出的 `kind`：先看它自己有没有带，再退回模块常量。

    若将来 `agent_f.PlanError` 带上 `kind` 属性（业务自报的具体失败类型，
    例如"预算不完整"与"计划不存在"分开），这里直接用异常自己说的 ——
    判据只有一份：异常自己声明它是什么，守卫不替它翻译第二遍。
    """
    return exc.kind if isinstance(getattr(exc, "kind", None), str) and exc.kind else PLAN_ERROR_KIND


def _guard(fn: Callable[[], Any]) -> ToolResult:
    """把已知的失败原因变成结构化失败，绝不让它逃成 `kind="unexpected"`。

    这是 `attack_tools` 与 `graph_tools` 共用的一份实现（FC-03：同一判据只有
    一份）。`graph_tools` 由 `from .attack_tools import _guard` 转发，不另写一份。

    ## [踩过] 为什么必须捕这三类（修之前的实测形态，见报告；`draft/28` §150）

    ===================  ==========================================  ==========================
    异常                  谁抛                                        修之前调用方看到的 kind
    ===================  ==========================================  ==========================
    `StoreError`         `store.rows`/`store.tx`：表不是合法 JSON、   `"unexpected"`
    （`RuntimeError`）    锁超时、编号用尽
    `PlanError`          `AgentF` 的攻坚拒绝（计划不存在、子目标缺   `"tool_error"`
    （`ToolError`）      owner、预算不完整）
    `ValueError`         `schema` 的行校验 / `AttackPlan.validate()`  `"tool_error"`
    ===================  ==========================================  ==========================

    三类都是我们预料得到的失败。`kind="unexpected"` 的语义是"我们没预料到"
    —— 把已知原因混进去，调用方就无法区分"重试可能成功"与"重试一百次也一样"。
    `StoreError` 那一格尤其严重：它是环境故障，与"这次调用写错了"需要完全
    不同的处置。

    ## 守卫形态照抄同仓库已有的两处（不另发明）

    - `tools/doc_tools.py::guard_result`：`ValueError` ⇒ `validation_error`、
      `StoreError` ⇒ `store_error`；
    - `tools/verify_tools.py::_run_experiment_tool`：`except ToolError: raise`
      把工具层自己的异常留给 `ToolRegistry.call` 分类，其余各给一个结构化 kind。

    ## 为什么 `except PlanError` 要排在 `except ToolError` 之前

    `PlanError` 是 `ToolError` 的子类。`ToolError` 那一支刻意 `raise`
    （工具层自己的异常由 `base.py:456-459` 映射成 `tool_error`），
    所以 `PlanError` 必须在它之前接住 —— 否则"攻坚计划层面的拒绝"会被压成
    笼统的 `tool_error`，具体失败类型又丢一次（这正是本函数要修的东西）。

    ## 为什么 `PlanError` 的类型要运行时取（`_plan_error_type()`）

    `agent_f` 在模块级 `from .tools import attack_tools as AT`，所以本模块
    不能在模块级 `from ..agent_f import PlanError`（成环）。用
    `except _plan_error_type() as e:` —— `except` 的表达式在异常真的发生时才求值，
    那时 `agent_f` 早已装载完成。这样拿到的是 `agent_f` 模块当前的属性
    （不是首次使用时的缓存），`tests` 里对 `agent_f.PlanError` 打桩/换类也不会失效。

    ## 三态

    `ValueError` 分支的文案带具体原因（`e` 本身就是 `schema` 的字段级报错，
    例如 `invalid literal for int() with base 10: 'abc'`）。只说"校验失败"对调用方
    没有可操作性 —— 它必须知道是哪个字段读不动才能改输入
    （形态照 `verify_tools.py:477` 的 `f"…：{exc}（没有落库）"`）。
    """
    try:
        return ok(fn())
    except (ValueError, TypeError) as e:
        # 2026-10-17（子代理 tools 根因 C）：`budget` 在 schema 里是 `{"type":"object"}`
        # 无 properties ⇒ 内层值从没被校验；`int(None)` / `int([])` 抛 TypeError 穿过守卫。
        # `PlanError` 是 `ToolError` 子类、不是 `ValueError`，所以这一支抓不到它。
        # （不依赖这个事实：下面那一支排在 ToolError 之前，改基类也不会静默漂移。）
        return fail(
            f"校验失败：{e}（**这一笔没有落库**）",
            kind="validation_error",
            reason=str(e),
        )
    except _plan_error_type() as e:
        return fail(f"攻坚计划被拒绝：{e}", kind=_plan_error_kind(e), reason=str(e))
    except ToolError:
        # 工具层自己的异常（参数错 / 未接线）上抛，由 `ToolRegistry.call` 映射。
        raise
    except StoreError as e:
        return fail(
            f"存储故障：{type(e).__name__}: {e} ⇒ **没查成**（不是'没有记录'）。"
            "请先修复/重建该表",
            kind="store_error",
            reason=str(e),
        )


def _plan_error_type() -> type:
    """`agent_f.PlanError` 的类型对象（运行时取，见 `_guard` 的 docstring）。

    为什么不在模块级取：`agent_f` 在模块级反向 import 本模块，模块级取必成环。
    为什么不在函数体里每次 `from ..agent_f import PlanError`：可以那样写，
    但这里显式收成一个具名函数，好让"这个类型是运行时绑定的"这件事
    只有一个落点（下一个人不必去猜 `except` 里的名字从哪来）。
    """
    from ..agent_f import PlanError  # 惰性：避免 tools ↔ agent 的循环导入

    return PlanError


@tool(
    "attack.check_budget",
    "检查攻坚预算是否完整、是否还允许再开一轮（四类键缺一不可）。",
    {
           "type": "object",
           "properties": {
            "budget": {"type": "object",
                   "description": "三维预算，四类键缺一不可（FC-18）：{max_rounds, max_parallel_subgoals, max_persist_attempts, max_depth}"},
            "rounds_done": {"type": "integer", "minimum": 0},
            "depth": {"type": "integer", "minimum": 0},
           },
           "required": ["budget"],
           "additionalProperties": False,
           },
    side_effect="none",
    roles=_READ_ROLES,
    # ⚠️ 2026-10-15 补齐（`draft/124` §17）：`returns` 会拼进 function-calling 的
    # `description`（`tools/base.py:721`）⇒ **模型看得到**；缺的键模型就不知道它存在。
    # `blocked_by` 是"被谁挡住的"（预算不完整 / 已终结 / 该换下一层）。
    returns="{'checked','complete','missing','allowed','reason','blocked_by'}",
    tags=("attack", "budget"),
)
def _attack_check_budget(budget, rounds_done=0, depth=0):
    """attack.check_budget 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（无）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _guard(
               lambda: can_round(budget, rounds_done=rounds_done, depth=depth)
               )
    )

@tool(
    "attack.pick_next_subgoal",
    "按确定性次序选出下一个要推进的子目标（开始过的优先，卡住的最后）。",
    {
           "type": "object",
           "properties": {"subgoals": {"type": "array", "items": {"type": "object"}}},
           "required": ["subgoals"],
           "additionalProperties": False,
           },
    side_effect="none",
    roles=_READ_ROLES,
    returns="{'picked', 'subgoal', 'reason'}",
    tags=("attack",),
)
def _attack_pick_next_subgoal(subgoals):
    """attack.pick_next_subgoal 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（无）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return _guard(lambda: pick_next_subgoal(subgoals))

@tool(
    "attack.create_plan",
    (
            "为一个难题立项（预算四类键缺一不可，不完整就拒绝）。同一 problem_key 已有未终结的计划时不新建，返回已有 plan_id。"
            ),
    {
           "type": "object",
           "properties": {
            "problem": {"type": "string"},
            "problem_key": {"type": "string"},
            "for_question_id": {"type": "string"},
            "subgoals": {"type": "array", "items": {"type": "object"}},
            "budget": {"type": "object",
                   "description": "三维预算，四类键缺一不可（FC-18）：{max_rounds, max_parallel_subgoals, max_persist_attempts, max_depth}"},
            "depth": {"type": "integer", "minimum": 0},
            "parent_plan_id": {"type": "string"},
           },
           "required": ["problem", "problem_key"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=_WRITE_ROLES,
    # 键名逐个从实现读出（`agent_f.AgentF.create_plan`）：成功分支给
    # `subgoals`（个数，不是清单）。另有可选键 `missing` ——
    # 它只在"预算不完整 ⇒ 拒绝创建"那一支出现（三条分支各自的完整键集
    # 见 `tests/test_tools_returns_declaration.py` 的分支留痕）。
    # `ok` 三支都有（`draft/37` §127）：`False` = 预算不完整被拒（调用方据它落
    # `outcome=refused`，而不是"执行完成"），`True` = 立项成功或"已经立过项了"。
    returns="{'ok','created','plan_id','duplicate','status','budget','subgoals','reason'}",
    tags=("attack", "plan"),
)
def _attack_create_plan(_need_store, store, problem, problem_key, for_question_id=None, subgoals=None, budget=None, depth=0, parent_plan_id=None):
    """attack.create_plan 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_need_store, store）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _need_store("attack.create_plan")
               or _guard(
                   lambda: _agent_for(store).create_plan(
                       problem,
                       problem_key,
                       for_question_id=for_question_id,
                       subgoals=subgoals,
                       budget=budget,
                       depth=depth,
                       parent_plan_id=parent_plan_id,
                   )
               )
    )

@tool(
    "attack.step",
    (
            "推进攻坚计划的一轮：按 owner 分派（E 做实验 / A 提检索 / B 提重抽取），C/D/F 的推理未接线则如实记 no_change。"
            ),
    {
           "type": "object",
           "properties": {"plan_id": {"type": "string"}},
           "required": ["plan_id"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=_WRITE_ROLES,
    # 键名从实现读出（`agent_f.AgentF.step`）：`sid` 是被推进的那个子目标
    # 的代号（没有可推进的子目标时为 null）；`budget_known` / `budget_reading`
    # 是这一轮的预算读数（P-09：读不到也如实给，`status="unknown"` + `why`）。
    returns=("{'plan_id','round','sid','action','outcome','status','budget_left',"
             "'reason','budget_known','budget_reading'}"),
    tags=("attack", "loop"),
)
def _attack_step(_need_store, store, plan_id):
    """attack.step 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_need_store, store）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return _need_store("attack.step") or _guard(lambda: _agent_for(store).step(plan_id))

@tool(
    "attack.status",
    "读一个攻坚计划的完整可读视图（子目标状态、预算余量、history 尾部）。",
    {
           "type": "object",
           "properties": {"plan_id": {"type": "string"}},
           "required": ["plan_id"],
           "additionalProperties": False,
           },
    side_effect="read",
    roles=_READ_ROLES,
    # 键名逐个从实现读出（`agent_f.AgentF.status`）：计划不存在时只有
    # `checked`/`plan_id`/`reason` 三个键（`checked=False` ⇒ 没查），存在时
    # 有全部 19 个键；这里写的是"计划存在"那一支的键集合。
    returns="{'checked','plan_id','problem','problem_key','for_question_id','status','rounds','budget','budget_left','depth','parent_plan_id','subgoals','subgoal_counts','best_partial','history_len','history_tail','created_at','updated_at','reason','stale_blocked'}",
    tags=("attack",),
)
def _attack_status(_need_store, store, plan_id):
    """attack.status 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_need_store, store）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return _need_store("attack.status") or _guard(lambda: _agent_for(store).status(plan_id))

@tool(
    "attack.list_plans",
    "列出全部攻坚计划（可按 problem_key 过滤）。",
    {
           "type": "object",
           "properties": {
            "problem_key": {"type": "string"},
            "include_terminal": {"type": "boolean"},
           },
           "additionalProperties": False,
           },
    side_effect="read",
    roles=_READ_ROLES,
    # 键名从一个真实调用读出（`AgentF.list_plans`）：`plans[]` 每项是
    # plan_id/problem_key/status/rounds/max_rounds/subgoals/depth 的摘要视图。
    returns="{'checked','total','plans','reason'}",
    tags=("attack",),
)
def _attack_list_plans(_need_store, store, problem_key=None, include_terminal=True):
    """attack.list_plans 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_need_store, store）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _need_store("attack.list_plans")
               or _guard(
                   lambda: _agent_for(store).list_plans(
                       problem_key=problem_key, include_terminal=include_terminal
                   )
               )
    )

#: 装配清单（`T-8`）：`(工具体函数, 需要从装配期注入的名字)`。
#: 声明随函数走（`@tool` 写进 `fn.__tool_spec__`），这里只列装配要做的事。
_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (_attack_check_budget, ()),
    (_attack_pick_next_subgoal, ()),
    (_attack_create_plan, ('_need_store', 'store')),
    (_attack_step, ('_need_store', 'store')),
    (_attack_status, ('_need_store', 'store')),
    (_attack_list_plans, ('_need_store', 'store')),
)


def register(
    registry: ToolRegistry,
    *,
    store: Any = None,
    root: Any = None,
    **_: Any,
) -> None:
    """装配 F 可见的攻坚工具。

    ``store`` 为 None 时三个需要存储的工具照样注册，调用时返回
    ``ok=False, kind="not_wired"``（FC-08）。不这样做的话，"没接线"会以
    "计划不存在"的形式出现在调用方眼里 —— 那是把"我们没接上"说成了
    "这个东西不存在"。
    """
    root = _root_for(root, store)

    def _need_store(tool: str):
        if store is None:
            return fail(
                f"{tool} 未接线：装配时没有提供 store。"
                "**未接线不等于'没有计划'**",
                kind="not_wired",
            )
        return None

    _bound: dict[str, Any] = {}
    _bound['_need_store'] = _need_store
    _bound['store'] = store
    for _fn, _deps in _TOOL_FUNCTIONS:
        registry.register(replace(_fn.__tool_spec__,
                                  handler=partial(_fn, *[_bound[k] for k in _deps])))





