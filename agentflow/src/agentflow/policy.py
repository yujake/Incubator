"""策略层：允许哪些召唤、以及四类上限（`DESIGN-CONDUCTOR.md` §3）。

## 为什么本模块只做判定、不做执行

`check_edge()` 是纯函数：给它一个 `Decision`（当前状态快照），它返回一个
`Refusal` 或 `None`。它不是"试着召唤一下看看行不行" —— 那种试错的副作用
（真的写了台账、真的调了 handler）与"我只是想知道行不行"完全不是一回事。

## 为什么四类上限缺一不可（FC-18）

| 只有 | 会被怎么绕过 |
|---|---|
| `max_tasks_per_run`（总量） | 瞬时把并发打爆：总量对了，但 200 个任务同时开跑 |
| `max_concurrency`（瞬时） | 扇出可以无限持续：每秒 4 个，跑一天 |
| `max_depth` | 每一层都能无限宽（深度 3，每层 9999 个） |
| `max_fanout` | 链可以无限深（每次只派生 1 个，但派生 10000 层） |

所以 `Policy.validate()` 要求四个都是正数，"没设上限"这种事在本层
不存在 —— 要放宽就把数字调大，而不是把它变成 None。这是一条刻意的
不可配置：`None` 会让"我忘了设"与"我决定不限"长得一模一样。

`wall_clock_sec` / `token_budget` / `usd_budget` 则允许是 None
（`None` = 不限），因为它们不是"防爆炸"的结构性上限，而是资源上限；
但 `None` 在台账里必须能被读出来（`Policy.to_dict()` 里它原样是 None，
不会被折叠成 0）。

## 扇出的口径：受理数，不是尝试数（题15 选B，2026-10-07）

`check()` 的第 [5] 步读 `Decision.fanout`，它的定义是"父任务受理过几个子召唤"，
不是"台账里有几行子行"。这一条差别就是本模块最贵的那类缺陷：闸门拒绝也落台账
（谁试过什么必须留痕），若被拒的那一次也占名额，父任务一旦触顶就再也派不出活，
而且每次尝试还会再占一格 —— 自我毒化、不可恢复。真机读数见
`FANOUT_LIMIT_BY_ROLE` 下面那一段。分档是刻意的："跑了但失败"（或跑了而角色
自己拒了）的子行仍然占名额，它确实消耗了一次派活；只有"被闸门拒掉、根本没跑"
的不占。上限本身按发起方角色取：默认档 = `Policy.max_fanout`，主控 `M` 一档 = 20。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

from . import capabilities as C
from . import schema as S


@dataclass(frozen=True)
class Policy:
    """一次 run 的策略。四类上限必须同时存在且为正数（FC-18）。"""

    #: 召唤链深度上限。主控发起 = 1，因此 `max_depth=3` ⇒ `M(1) → A(2) → B(3)` 已到底。
    max_depth: int = 3
    #: 单个任务最多派生几个子召唤（默认档；主控那一档见 `FANOUT_LIMIT_BY_ROLE`）。
    #: 口径是受理数，不是尝试数 —— 见模块 docstring 的"扇出的口径"一节。
    max_fanout: int = 5
    #: 全局同时运行的任务数（瞬时上限）。
    max_concurrency: int = 4
    #: 一次 run 的召唤总数（生命周期总量）。
    max_tasks_per_run: int = 200
    #: 全局墙钟截止（秒，从 run 开始算）。None = 不限。
    #:
    #: 到点之后新召唤一律被拒，已在跑的走协作式取消 —— 不是强杀。
    #: 强杀会让"取消"与"完成"在同一瞬间争夺同一个 `ended_at`，而
    #: `Task.validate` 的"终态先到先得"只保证先写的赢，不保证被杀的那次
    #: 没写过半张表（§4 第 4 条："结果未知"是必须如实记下的状态）。
    wall_clock_sec: float | None = 900
    #: 全局 token 预算（None = 不限）。
    token_budget: int | None = None
    #: 全局花销预算（None = 不限）。
    usd_budget: float | None = None

    def __post_init__(self) -> None:
        # 构造即校验：`dataclass(frozen=True)` 让 policy 是值对象，值对象在
        # 出生时就该是合法的。等到"run 启动时再断言"会让一个非法 policy
        # 在构造与使用之间自由流动（中途被谁读走都不知道）。
        self.validate()

    def validate(self) -> None:
        """四类上限必须都是正数。不合法抛 ValueError（不返回布尔）。"""
        for name in ("max_depth", "max_fanout", "max_concurrency", "max_tasks_per_run"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError(f"Policy.{name} 必须是 int，收到 {v!r}")
            if v <= 0:
                raise ValueError(
                    f"Policy.{name}={v} 必须为正数。四类上限缺任一类，另三类都可以被绕过"
                    "（FC-18）：只有总量则瞬时并发可被打爆；只有并发则扇出可无限持续；"
                    "只有深度则每层可无限宽；只有扇出则链可无限深。"
                    "要放宽请调大数字，**不要**把它变成 None/0 —— 那会让『我忘了设』"
                    "与『我决定不限』长得一模一样。"
                )
        if self.wall_clock_sec is not None and not (self.wall_clock_sec > 0):
            raise ValueError(f"Policy.wall_clock_sec 必须是正数或 None，收到 {self.wall_clock_sec!r}")
        if self.token_budget is not None and self.token_budget < 0:
            raise ValueError(f"Policy.token_budget 不能为负（0 表示一开始就耗尽），收到 {self.token_budget}")
        if self.usd_budget is not None and self.usd_budget < 0:
            raise ValueError(f"Policy.usd_budget 不能为负，收到 {self.usd_budget}")

    def to_dict(self) -> dict:
        """台账/日志里的形态。None 保持 None（不折叠成 0）：
        "不限"与"限 0"是两件完全不同的事，折叠它们会让事后审计读不出当时的策略。"""
        return asdict(self)


# ---------------------------------------------------------------- 逐角色的上限覆盖


#: 发起方角色 → 扇出上限的显式覆盖（唯一一处；不在表里的角色一律用
#: `Policy.max_fanout`，所以默认档仍然只有那一个来源）。20 这个数只写在这里。
#:
#: 为什么只有主控单独一档（题15 选B，2026-10-07）：
#:
#: - 编排者一趟要派的活天然比工人多。工人的一次召唤是"干一件具体的事"，
#:   主控的一次召唤是"把这一趟的编队支起来"（检索 / 立题 / 实验 / 审阅各一件），
#:   两者合用同一个上限会让主控在正常编队下就触顶。
#: - 真机读数（工作区 `agentflow/projects/p9-post-merge-probe`，2026-10-07 台账）：
#:   顶趟行 `t-0001` 名下 10 个子行，末 5 条（`t-0007`…`t-0011`）全是
#:   `refused/fanout_exceeded`，detail 里的读数从"已派生 5 个"一路涨到"已派生 9 个"
#:   （那就是自我毒化的机器形态）；本趟主控只成功派了 3 件活（A 检索 / D 立题 /
#:   D 登记猜想），E 的实验永远进不去 ⇒ `experiments=0`、收工门两格红。
#:   那一趟主控需要至少 4 次有效派活，而名额只有 5 —— 编排余量太小，所以另立一档。
#: - 只抬主控、不抬工人：工人档维持默认值，扇出仍是"一个任务最多派生 5 个"，
#:   这一条有反真空判据咬着（`tests/test_fanout_admission.py`）。
FANOUT_LIMIT_BY_ROLE: dict[str, int] = {S.CONDUCTOR_ROLE: 20}


def fanout_limit_for(policy: Policy, frm: str) -> int:
    """发起方角色 `frm` 的扇出上限：默认档取自 `Policy.max_fanout`，主控一档见
    `FANOUT_LIMIT_BY_ROLE`。

    为什么按发起方（`Decision.frm`）取而不是按父任务的角色取：名额约束的是
    "谁在派活"。同一棵树上一个工人派 5 件就该满，而主控派 6 件是正常编队
    （真机那一趟主控需要至少 4 次有效派活，读数见 `FANOUT_LIMIT_BY_ROLE`）。
    """
    return FANOUT_LIMIT_BY_ROLE.get(frm, policy.max_fanout)


# ---------------------------------------------------------------- 拒绝


@dataclass(frozen=True)
class Refusal:
    """一次拒绝。`reason` 一定是 `schema.REFUSAL_REASONS` 里的值。

    为什么返回对象而不是抛异常：拒绝是策略的正常输出，不是异常路径。
    把它变成异常会让调用方用 try/except 包住它，而 try/except 会连真正的
    编程错误一起吞掉 —— 本项目的纪律是"静默失败比崩溃更危险"。
    """

    reason: str
    detail: str = ""
    #: 判定它的是哪一类上限（便于台账里"为什么被拒"能一眼读出）。
    limit: str = ""

    def __post_init__(self) -> None:
        if self.reason not in S.REFUSAL_REASONS:
            raise ValueError(
                f"Refusal.reason={self.reason!r} 不在受控词表 {S.REFUSAL_REASONS} 里。"
                "拒绝的理由必须可枚举：自由文本的拒绝理由无法被统计，也无法被 verify 检查"
            )

    def to_dict(self) -> dict:
        return {"reason": self.reason, "detail": self.detail, "limit": self.limit}


# ---------------------------------------------------------------- 判定输入


@dataclass
class Decision:
    """一次召唤的判定输入（纯数据，判定函数不碰 store）。

    为什么把它做成显式对象而不是一堆位置参数：判定条件有八条，
    一个 `check_edge(frm, to, depth=..., fanout=..., ...)` 的签名会让
    "忘了传 fanout"变成默认值 0 ⇒ 永远放行。显式对象让新增判据时
    调用方必须一起改，而不是悄悄拿到一个宽松的默认。
    """

    frm: str = S.CONDUCTOR_ROLE
    to: str = ""
    action: str = ""
    #: 被召唤的角色（= `to`）。它单独有一个字段，是为了让 `waves_of` 能按
    #: "调用对象上有 `role` 属性"这条约定统一取角色 —— `to` 是边判定的
    #: 名字，`role` 是写集判定的名字，两者在同一次召唤里恰好相同，
    #: 但把写集判据接到 `to` 上会让"边判定改名"顺手改坏并发判据。
    role: str = ""
    #: 本次召唤的深度（主控发起 = 1）。
    depth: int = 1
    #: 父任务已经受理的子任务数（不含本次）。口径是受理数，不是尝试数：
    #: 被闸门拒掉、根本没跑的召唤不占名额（`Conductor._admitted_children_of`），
    #: 而"跑了但失败"（或跑了而角色自己拒了）的仍然占 —— 它确实消耗了一次派活。
    #: 按尝试数算会让父任务触顶之后再也派不出活，且每次尝试再占一格（自我毒化）。
    fanout: int = 0
    #: 当前正在运行的任务数（瞬时）。
    running: int = 0
    #: 本次 run 已经发生的召唤总数。
    total: int = 0
    #: 祖先链上的 `(role, action, input_key)` 三元组（不含父自身的重复项也可以，
    #: 判定时会连同本次一起查）。
    ancestry: Sequence[tuple[str, str, str]] = field(default_factory=tuple)
    #: 本次召唤的 `(role, action, input_key)`。
    key: tuple[str, str, str] = ("", "", "")
    #: 全局剩余 token 预算（None = 不限）。
    tokens_left: int | None = None
    #: 本次召唤预计消耗的 token（None = 未知 ⇒ 不做单次预检）。
    tokens_wanted: int | None = None
    #: 全局剩余花销预算（None = 不限）。
    usd_left: float | None = None
    #: 本次召唤预计花销。
    usd_wanted: float | None = None
    #: 墙钟是否已到点（由 `Conductor` 用它的 start/deadline 算好传进来；
    #: policy 不认识时钟 —— 判据必须是可单测的纯函数）。
    deadline_hit: bool = False


# ---------------------------------------------------------------- 判定


def check_action(role: str, action: str, *, registry: Any = None) -> Refusal | None:
    """角色与动作是否存在。

    两种失败必须分开：`unknown_role`（名单里没这个人）与
    `unknown_action`（人存在，但没这个本事）。合并成一句"不支持"会让
    "我把角色名拼错了"与"我调了一个该角色真的没有的动作"无法区分。
    """
    known = C.roles_in(registry)
    if role not in known:
        return Refusal("unknown_role", f"角色 {role!r} 不在 {known} 里", "role")
    if role == S.CONDUCTOR_ROLE:
        # 主控只能被召唤这件事本身，它没有"动作"。
        return Refusal(
            "unknown_action",
            "主控 M 没有 Agent 动作（它的动作是 summon 本身，由 Conductor 实现）",
            "action",
        )
    if C.find_action(role, action, registry=registry) is None:
        known = [s.action for s in C.actions_for(role, registry=registry)]
        return Refusal(
            "unknown_action",
            f"{role} 没有动作 {action!r}（它有：{known}）",
            "action",
        )
    return None


def check_edge(policy: Policy, frm: str, to: str, *, registry: Any = None,
               **kw: Any) -> Refusal | None:
    """唯一的策略判定入口。返回 `None` = 放行；返回 `Refusal` = 拒绝。

    它不抛异常、不写台账、不调 handler。判定与执行分开，
    才能对"策略"本身写测试（本文件对应的 `tests/test_policy.py` 是纯函数测试）。

    判定顺序（有意为之，且顺序本身是判据的一部分）：

    1. 角色/动作存在性 —— 一个不存在的角色谈不上"边"
    2. 边是否允许 —— 越权优先于深度：`C → B` 无论在什么深度都是越权，
       报 `depth_exceeded` 会让人以为是"再深一点就行"；
       第 [2] 步里 `NON_SUMMONABLE` 排在角色存在性之前 —— 召唤主控是
       "这条边不许存在"，不是"角色名拼错了"
    3. 深度 → 4. 循环 → 5. 扇出 → 6. 并发 → 7. 总量 → 8. 预算 → 9. 墙钟

    唯一的例外是主控 `M` 自己：它没有"动作"这件事（`check_action('M', …)`
    永远返回 `unknown_action`），但"没人能召唤主控"是一条显式的边判据。
    若把它交给第 1 步，那条判据就永远不可达（`G-11` 实测）。
    所以 `check` 对 `to == CONDUCTOR_ROLE` 跳过第 1 步，让它落到第 2 步的
    `NON_SUMMONABLE` 上；`check_action` 本身不动。

    第 3/4 步的顺序（深度在循环前）是刻意的：`M→A→B→A` 若报 `cycle_detected`，
    人可能会去"解开循环"；而它其实是深度用尽。反过来，深度没超的
    `A→B→A` 才是真循环。两者都判得出，但先报深度更贴近"这一层到底还让不让开"
    这个问题（循环判定需要看整条链，而链的长度上限首先由深度决定）。

    参数 `**kw` 里认得的键见 :class:`Decision`；额外的键会被忽略（向前兼容），
    但拼错的键名不会被发现 —— 所以 :func:`check` 才是推荐入口。
    """
    d = Decision(frm=frm, to=to, **{k: v for k, v in kw.items() if k in Decision.__dataclass_fields__})
    return check(policy, d)


def check(policy: Policy, d: Decision, *, registry: Any = None) -> Refusal | None:
    """按 :class:`Decision` 做全部判定。见 :func:`check_edge` 的顺序说明。"""
    policy.validate()
    # `role` 是写集判定的名字、`to` 是边判定的名字：构造 `Decision` 时容易只填一个。
    # 这里做唯一一处归一（而不是让每个消费者各自 `role or to`），
    # 否则漏填的那一半会静默退化 —— 见 `write_set_of` 的"未知 ⇒ 保守"说明。
    if not d.role:
        d.role = d.to

    # ---- [0] 主控：没有"动作"这件事，但"不可召唤"由第 [2] 步负责（`G-11`）
    #
    # 为什么不在这里调 check_action：它会在第一步就把 `to == CONDUCTOR_ROLE`
    # 判成 `unknown_action` 并返回 ⇒ 下面那两条 NON_SUMMONABLE 判据
    # （连同它"不靠 ALLOWED_EDGES 里没人写 M 这个偶然事实"的理由）永远不可达。
    # 处置就是把"主控"这一格让给那两条判据；`check_action` 本身一个字符没动 ——
    # 它仍然是唯一的角色/动作存在性判据，仍然要能单独回答
    # `check_action('M','summon')`（那一条有它自己的用例与语义）。

    # ---- [1] 角色/动作
    if d.to != S.CONDUCTOR_ROLE:
        r = check_action(d.to, d.action, registry=registry)
        if r is not None:
            return r

    # ---- [2] 边：不可召唤 / 角色存在性 / 边是否允许
    if d.to in (C.NON_SUMMONABLE if registry is None
                else frozenset(r for r in registry.roles()
                                if not registry.get(r).summonable)):
        return Refusal("forbidden_edge", f"{d.to} 是不可召唤的（没有『召唤主控』这件事）", "edge")
    known = C.roles_in(registry)
    if d.to not in known:
        return Refusal("unknown_role", f"角色 {d.to!r} 不存在", "role")
    if d.frm not in known:
        return Refusal("unknown_role", f"召唤方 {d.frm!r} 不是合法角色", "role")
    allowed = C.edges_for(d.frm, registry=registry)
    if d.to not in allowed:
        return Refusal(
            "forbidden_edge",
            f"{d.frm} → {d.to} 不在策略允许的边里（{d.frm} 只能召唤 {sorted(allowed)}）",
            "edge",
        )

    # ---- [3] 深度（主控发起 = 1）
    if d.depth > policy.max_depth:
        return Refusal(
            "depth_exceeded",
            f"depth={d.depth} 超过 max_depth={policy.max_depth}（主控发起 = 1）",
            "max_depth",
        )

    # ---- [4] 循环：同一条 (role, action, input_key) 不得出现在祖先链上
    #
    # 为什么用 input_key 而不是全部参数：参数里常有时间戳这类每轮都不同的噪声，
    # 而"同样的问题问两遍"才是要防的活锁（`A→B→A→B`）。
    if d.key and d.key in set(d.ancestry):
        return Refusal(
            "cycle_detected",
            f"({d.key[0]}, {d.key[1]}, {d.key[2]!r}) 已出现在祖先链上 —— "
            "同一件事在链上问第二遍就是活锁，不是进展",
            "cycle",
        )

    # ---- [5] 扇出（口径：受理数，不是尝试数；上限按发起方角色取）
    #
    # `d.fanout` 由调用方（`Conductor`）按"受理过的子行"算：被闸门拒掉、根本没跑的
    # 那些不占名额（它们照旧落台账，见 `conductor._refuse` 与 `_admitted_children_of`）。
    # 这条口径是判据的一部分而不是实现细节 —— 若被拒的那一次也占名额，父任务一旦
    # 触顶就再也派不出活，而每次尝试还会再占一格（自我毒化、不可恢复；真机读数见
    # `FANOUT_LIMIT_BY_ROLE`）。上限按发起方取：默认档 = `policy.max_fanout`，
    # 主控一档 = `FANOUT_LIMIT_BY_ROLE`（20）。
    limit = fanout_limit_for(policy, d.frm)
    if d.fanout >= limit:
        # 报文要能同时读出"当前几"与"上限是多少"，以及那个上限是从哪来的：
        # 只说 max_fanout=5 的报文在主控那一档上会让人以为上限是 5。
        if d.frm in FANOUT_LIMIT_BY_ROLE:
            origin = f"FANOUT_LIMIT_BY_ROLE 里主控那一档，policy.max_fanout={policy.max_fanout}"
        else:
            origin = "policy.max_fanout"
        return Refusal(
            "fanout_exceeded",
            f"该任务已受理 {d.fanout} 个子召唤，达到发起方 {d.frm} 的扇出上限 {limit}"
            f"（{origin}）。这是**本趟的硬上限**（口径是受理数，不是尝试数），"
            "再派也不会被受理 ⇒ 不要再把步数花在派活上：把手上已有的读数写进交付物、"
            "把缺的缺口如实记成读数（谁没做、为什么），然后收工",
            "max_fanout",
        )

    # ---- [6] 并发（瞬时）
    if d.running >= policy.max_concurrency:
        return Refusal(
            "concurrency_exceeded",
            f"当前有 {d.running} 个任务在跑，达到 max_concurrency={policy.max_concurrency}",
            "max_concurrency",
        )

    # ---- [7] 总量（生命周期）
    if d.total >= policy.max_tasks_per_run:
        return Refusal(
            "budget_exceeded",
            f"本次 run 已发生 {d.total} 次召唤，达到 max_tasks_per_run={policy.max_tasks_per_run}",
            "max_tasks_per_run",
        )

    # ---- [8] 预算
    #
    # 单次预算只能是"预计值"（我们不可能在跑之前知道一次 LLM 调用花多少）。
    # 所以这里的判据是：已经耗尽 ⇒ 拒（确定性），或者这一单的最小预计值
    # 就已经超过剩余（`tokens_wanted > tokens_left`）⇒ 拒。真正的扣减发生在
    # handler 返回之后（`Conductor` 记账），因此"跑到一半把预算花超"是可能的
    # —— 那是如实记录的事（台账里 tokens 会超过预算），不是被掩盖的事。
    # 设计 §3.2 的"预算耗尽后不再新开任务"约束的正是新开。
    if d.tokens_left is not None:
        if d.tokens_left <= 0:
            return Refusal("budget_exceeded", f"token 预算已耗尽（剩余 {d.tokens_left}）", "token_budget")
        if d.tokens_wanted is not None and d.tokens_wanted > d.tokens_left:
            return Refusal(
                "budget_exceeded",
                f"本次预计需要 {d.tokens_wanted} token，剩余 {d.tokens_left}",
                "token_budget",
            )
    if d.usd_left is not None:
        if d.usd_left <= 0:
            return Refusal("budget_exceeded", f"花销预算已耗尽（剩余 {d.usd_left}）", "usd_budget")
        if d.usd_wanted is not None and d.usd_wanted > d.usd_left:
            return Refusal(
                "budget_exceeded",
                f"本次预计需要 {d.usd_wanted} USD，剩余 {d.usd_left}",
                "usd_budget",
            )

    # ---- [9] 墙钟（最后判：它是"环境"的限制，前面每一条都是"策略"的限制）
    if d.deadline_hit:
        return Refusal(
            "deadline_exceeded",
            f"墙钟截止已过（wall_clock_sec={policy.wall_clock_sec}）—— 新召唤一律拒绝，"
            "已在跑的走协作式取消",
            "wall_clock",
        )

    return None


# ---------------------------------------------------------------- 写集冲突


def _write_set(x: Any) -> frozenset[str]:
    """把角色名或 `ActionSpec` 归一成写集。

    未知输入不是空集：见 `capabilities.write_set_of` 的说明 ——
    "不知道"必须保守成"与所有人串行"，否则一个不认识的执行单元
    会被当成只读，与写者并发。
    """
    if isinstance(x, C.ActionSpec):
        return C.write_set_of(x.role)
    if isinstance(x, str):
        return C.write_set_of(x)
    role = getattr(x, "role", None)
    if isinstance(role, str):
        return C.write_set_of(role)
    return C.write_set_of("<unknown>")


def estimate_write_conflict(a: Any, b: Any) -> bool:
    """两个执行单元（角色 / `ActionSpec` / `TaskCall`）的写集是否相交 ⇒ 它们不该并发。

    这是并发判据，不是经验规则：它可判定、可测（见 `tests/test_scheduler.py`
    的 I-6）。保守方向的代价是多花时间；激进方向的代价是数据被改坏，
    而后者不会报错。

    实例轴（2026-09-30 加）：`TaskCall` 现在可以带一个 `instance` 标签
    （同一角色的第 N 个并发实例）。两个同一角色、不同实例的调用不算冲突 ——
    否则"N 个 B 一起读一批文献"会被结构性地排成 N 波串行（实测：3 个 B ⇒
    `[[0],[1],[2]]`、真并发峰值 1，再多 B 也没用）。

    为什么这条放宽是安全的、以及它的边界：角色级写集回答的是"这个角色会碰哪些表"，
    而行级互斥另有机制 —— B/A 的领取走 `claimed_by` + 租约
    （`agent_b._claim`），C/H 是只读，写者各自 `store.tx` 在同一把 filelock 下串行提交。
    所以"两个 B 并发"在数据面早就成立（既有判据
    `tests/test_agent_b_gates.py::test_i6_two_agents_write_concurrently_without_deadlock`
    实测通过）。同一实例（或没给实例）的两个调用仍然算冲突 ——
    默认行为逐字不变，并发多实例必须由调用方显式要（见 `waves_of` 的说明）。
    """
    if _same_role_other_instance(a, b):
        return False
    return bool(_write_set(a) & _write_set(b))


def _instance_of(x: Any) -> str:
    """执行单元的实例标签（没给就是空串 = "这个角色只有那一个实例"）。"""
    return str(getattr(x, "instance", "") or "")


def _same_role_other_instance(a: Any, b: Any) -> bool:
    """两个调用是不是"同一角色、各自显式给了不同的实例"。

    只有这一种情形才豁免写集冲突：两边都必须显式给实例（空串不豁免），
    否则"没给实例"会与"给了实例"被判成不同实例 —— 那就等于默认打开并发，
    而默认打开会让既有的"同角色串行"判据静默失效。
    """
    ia, ib = _instance_of(a), _instance_of(b)
    if not ia or not ib or ia == ib:
        return False
    ra, rb = _role_of(a), _role_of(b)
    return isinstance(ra, str) and ra == rb


def waves_of(calls: Sequence[Any], *, limit: int | None = None) -> list[list[int]]:
    """把调用按写集互斥切成波浪（返回下标，不执行）。

    贪心装箱，保持输入顺序：每个调用放进第一个与它不冲突的波浪。
    为什么贪心而不是最优划分（最小波浪数）：最优划分需要解图着色，
    而"可复现"要求同一输入的划分每次一样 —— 贪心天然确定性，
    且它的代价只是可能多一波（保守方向）。

    `limit` 是单波容量（= `max_concurrency`）：满员的波不再接收新成员，
    于是"波内并发数 ≤ max_concurrency"由划分保证，不需要再靠信号量兜底。
    （两者都留着：划分保证不超，运行时信号量保证即使调用方绕过划分也不超。）

    返回的是下标而不是调用对象：调用对象可能包含不可哈希/不可比较的
    字段（dict 参数、lambda），用 `list.index()` 去定位会得到错误的下标
    （重复元素全部指向第一个）。下标从一开始就是真的。
    """
    waves: list[list[tuple[int, Any]]] = []
    for i, call in enumerate(calls):
        ws = _write_set(_role_of(call))
        placed = False
        for wave in waves:
            if limit is not None and len(wave) >= limit:
                continue
            if any(_write_set(_role_of(other)) & ws
                   and not _same_role_other_instance(call, other)
                   for _, other in wave):
                continue
            wave.append((i, call))
            placed = True
            break
        if not placed:
            waves.append([(i, call)])
    return [[i for i, _ in wave] for wave in waves]


def _role_of(call: Any) -> Any:
    return getattr(call, "role", call)


def assert_policy_complete(policy: Policy) -> None:
    """"run 启动时断言四类都在"（设计 §3 末段）。

    与 `Policy.validate()` 的区别：`validate` 查取值合法性（正数），
    这里查这一类是否被显式声明过。目前两者等价（dataclass 有默认值，
    不可能缺席），但把这条断言单列出来，是为了将来有人把某个字段改成
    `Optional` 时，在这里炸 —— 而不是让一个 `None` 悄悄流向判定函数。
    """
    absent = [
        n for n in ("max_depth", "max_fanout", "max_concurrency", "max_tasks_per_run")
        if getattr(policy, n, None) is None
    ]
    if absent:
        raise ValueError(
            f"policy 缺少四类上限中的 {absent}（FC-18：缺任一类，另三类都可以被绕过）"
        )


def budget_state(policy: Policy, *, spent_tokens: int, spent_usd: float) -> dict:
    """预算剩余的三态视图。`None` 表示"不限"，不折叠成 0 或 -1。

    为什么返回 dict 而不是一个数：调用方需要同时回答"还剩多少"与
    "有没有上限"。一个数做不到，而"没有上限"被写成 0 会被读成"已耗尽"。
    """
    return {
        "tokens_left": None if policy.token_budget is None else max(0, policy.token_budget - spent_tokens),
        "usd_left": None if policy.usd_budget is None else max(0.0, policy.usd_budget - spent_usd),
        "token_budget": policy.token_budget,
        "usd_budget": policy.usd_budget,
        "spent_tokens": spent_tokens,
        "spent_usd": spent_usd,
    }


def iter_edges() -> Iterable[tuple[str, str]]:
    """把所有允许的边摊平（供 CLI / verify / 文档生成用）。"""
    for frm, tos in sorted(C.ALLOWED_EDGES.items()):
        for to in sorted(tos):
            yield frm, to
