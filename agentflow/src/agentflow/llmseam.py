"""统一的模型缝：一次模型调用 = 一条可审计的记录。

## 为什么要有这一层

"接模型"这件事在仓里有两种纪律：`runflow` 那条流程把 `prompt_version`
落进 run-manifest（可复现），而 C/D 的钩子直接 `self.llm.complete(prompt)`
（没有版本、没有模型名、没有落库的调用记录）。于是同一个问题在两处有两个答案：
"这次结论是哪个版本的提示词、哪个模型、哪一次调用产生的？"

这一层把答案固定成一条记录，并且把三态纪律做成结构：

- 没接线（没有 key）= `judge_not_wired`，不是"没有结论"；
- 预算耗尽 = `judge_over_budget`，而且在发起网络请求之前就拒绝；
- 模型拒答、超时、返回坏 JSON = 各自的码；
- 其它异常 = `judge_failed:<异常类名>`，绝不吞掉。

词表直接用 `judge.JUDGE_PROBLEMS`（同一份，不另立一套）。

## 落档落在哪

落在项目会话记录里（`sessions.append`）—— 不新增表。理由是：
候选落点先落文件；表结构一改就是 schema 迁移（禁改区）。
落档失败不吞：调用结果里带 `recorded` 字段写明失败原因，调用方据此决定要不要继续。
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import json
import os
import re
import threading

from . import judge as J
from . import modelcost as MC
from . import modelgw as MG
from . import sessions as SS
from .agent_prompts import PROMPT_VERSION
from .toolface import face_text as _face_text

#: 本缝的用途归口（`schema.USAGE_SCOPES` 之一）。写死一处，避免调用点各写一个。
SEAM_SCOPE = "reason"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: 装配期类型闸的开关（默认关）。业主 2026-11-15 的硬要求「彩排路径与真机路径
#: 用的东西实际上是一致的」在装配面的机器判据：开了之后，任何 duck-type 的
#: `_Seam` / `_FakeSeam` 都进不了产品对象。
STRICT_SEAM_ENV = "AGENTFLOW_STRICT_SEAM"


def strict_seam() -> bool:
    """`AGENTFLOW_STRICT_SEAM=1` 时开着（读不懂按关：不认识的取值不许静默放宽）。"""
    raw = str(os.environ.get(STRICT_SEAM_ENV, "") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def assert_real_seam(seam: Any, *, where: str) -> None:
    """装配期类型闸：`AGENTFLOW_STRICT_SEAM=1` 时，缝必须就是 `LlmSeam`。

    为什么用 `type(seam) is not LlmSeam` 而不是 `isinstance`：子类可以覆盖 `ask`
    而不改类型名 —— 那时预算闸、账本行、`llm_call` 事件、ambient 解析同样可以被换掉，
    而 `isinstance` 会放行。判据要问的是「这是不是产品造出来的那一个对象」。

    `None` 放行（"没接线"是合法状态，由 `wired` / `judge_not_wired` 如实表达）。
    默认关：历史调用点上有大量单测用 duck-type 替身，默认开会把它们全部变红；
    要判「彩排是不是走了真机那条路」时把它打开（`tests/test_rehearsal_same_path.py`
    的反真空就是这么做）。

    接在哪（这一手能把静态扫描抓不到的「构造期直接替换」判红）：
    `Secretary.__init__`、`AgentF/AgentV.__init__(llm=…)`、
    `LlmBackend._seam`（`seam_factory` 的返回处）、`cli._agent_seam_factory` 的返回处。
    """
    if seam is None or not strict_seam():
        return
    if type(seam) is not LlmSeam:
        raise TypeError(
            f"{where} 收到一个 `{type(seam).__name__}` 替身，不是产品那个 `LlmSeam`。"
            "它没有预算闸 / 没有 usage_ledger 行 / 没有 llm_call 事件 / 读不到 ambient —— "
            "把它塞进来，这一趟的三格与钱全部测不到。"
            "改法：用 `LlmSeam(..., gateway=<脚本网关>, meter=TokenMeter(store))`"
            "（彩排侧的唯一入口是 `tests/rehearsal_contract.py:scripted_seam`）。")


@dataclass(frozen=True)
class SeamCall:
    """一次模型的结局：文本（或空）、失败码、以及这次调用的全部审计事实。"""

    ok: bool
    text: str = ""
    problem: str = ""
    detail: str = ""
    model: str = ""
    scope: str = SEAM_SCOPE
    prompt_version: str = PROMPT_VERSION
    prompt_sha256: str = ""
    system_sha256: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    #: 输入里命中缓存的那一部分（上游 `usage.prompt_cache_hit_tokens`）。
    #: `None` = 上游没回这一格（"没查成"），`0` = 明说零命中 —— 三态，不许折平。
    #: 它与 `usd` 成对：供应商按"命中/未命中/输出"三档计价，而这一格是那三档里
    #: 唯一被我们丢掉的一档（「花销标准与供应商定价吻合」）。
    cache_hit_tokens: int | None = None
    #: 输入里未命中缓存的那一部分（上游 `usage.prompt_cache_miss_tokens`）。三态同上。
    cache_miss_tokens: int | None = None
    #: 这一笔的计价读数（`modelcost.billing_reading` 的返回：用了哪几档价、命中多少、
    #: "命中价没登记 / 上游没报命中"这两种偏高情形各留一条痕迹）。
    billing: dict[str, Any] = field(default_factory=dict)
    usd: float | None = None
    elapsed_sec: float = 0.0
    recorded: str = ""      # 空串 = 审计记录已落档；否则是没落成的原因
    #: 这一趟走的是哪条协议：`"tool_calls"`（原生工具调用）/ `"text"`（文本 JSON 回落）。
    #: 它是审计读数，不是装饰：那趟真机死在"模型把 `tool` 写成 `name`"，
    #: 而那条路上"名字由谁给"正是这个字段回答的问题。
    protocol: str = "text"
    #: 这一趟广告了几件函数（工具 + 循环形状），以及那份工具面的摘要。
    tools_advertised: int = 0
    tools_sha256: str = ""
    #: 这一趟按哪个推理强度问的（`modelgw.REASONING_EFFORTS` 之一；没接线时是空串）。
    #:
    #: ## 为什么要与下面的 `reasoning_chars` 成对存在
    #:
    #: 两个读数回答两个不同的问题，折成一个就答不了任何一个：
    #: `reasoning_effort` 是"我们要求它想多深"（配置面），
    #: `reasoning_chars` 是"它实际想了多少字"（结果面）。
    #: 形态有四种，各自指向不同的修法：
    #:
    #:   effort=high + chars>0    正常；
    #:   effort=off  + chars=0    这一档本来就不想（是配置，不是缺陷）；
    #:   effort=high + chars=0    请求发了但它没想 ⇒ 查模型/端点，别查提示词；
    #:   effort=off  + chars>0    配置说关而它照想 ⇒ 查 `off` 那条序列化。
    #:
    #: "感觉像不怎么过脑子"那一句若没有这两个读数就无法验证：
    #: 请求体里没有这一栏，回复里的 `reasoning_content` 也从没被读过。
    reasoning_effort: str = ""
    #: 这一趟按哪个采样温度问的（`modelgw.TEMPERATURE_RANGE` 里的一个数）。
    #:
    #: 三态：`None` = 这一趟没有发请求（没接线 / 预算已尽）—— "没查过"不是"0"；
    #: 具体数值 = 真的进了请求体 `temperature` 那一格的那个数（显式给的那个，
    #: 或这一档配置 `ModelSpec.temperature` 的那个）。
    #: 为什么它是一个字段：温度是"这一次判定可不可复现"的一半读数；没有它，
    #: 温度只活在 `modelclient` 的 `to_dict()` 里、从没进过网线。
    temperature: float | None = None
    #: 这一趟回复里的思维链字数（上游 `message.reasoning_content`）。
    #: 只记字数不记原文：与 `tool_call_list` 不进 `to_dict()` 同一条纪律（会随每次调用膨胀）。
    reasoning_chars: int = 0
    #: 思维链的原文（空串 = 上游没给）。
    #:
    #: 为什么不进 `to_dict()`：它逐字可能上千字，每条 `llm_call` 事件都抄一份会把
    #: 会话记录撑大（与 `tool_call_list` 同一条纪律）。它的归属地是消息序列里
    #: assistant 那条的 `reasoning_content`（以及随后那条 `agent_step` 事件的
    #: `reasoning` 格 —— 序列要能从事件重建，见 `agent_loop.resume_messages`）。
    reasoning: str = ""
    #: 模型给了几条结构化工具调用（0 = 没给，于是回落去解析文本）。
    tool_calls: int = 0
    #: 原始的 `tool_calls`（`ask_step` 要把它们翻成循环的形状）。
    #: 刻意不进 `to_dict()`：审计面留条数与工具面摘要就够，逐条原文会随每次调用膨胀。
    tool_call_list: tuple[dict[str, Any], ...] = ()
    #: 这一次到底发没发请求（`False` 只有两条早退路：没接线 / 预算已尽）。
    #:
    #: 为什么它必须与 `ok=False` 分开：缓存读数的三态之外还有"第零态"——
    #: 根本没发请求的调用不可能有 `prompt_cache_*`，把它算进 `unknown_calls` 会让
    #: "上游不报这一格"与"这一趟一个请求都没发"在 run 记录里长得一样。
    #: 账本那边同一件事记的是 `ledger.reason == "no_request"`，两处口径一致。
    requested: bool = True

    @property
    def not_checked(self) -> bool:
        """这次是"没查成"（而不是"查了、结论是空"）—— 三态里的第三态。"""
        return (not self.ok) and J.is_judge_problem(self.problem)

    def to_dict(self) -> dict[str, Any]:
        """落审计记录用的扁平结构（含 not_checked，下游不必自己推）。"""
        return {
            "ok": self.ok,
            "text_len": len(self.text),
            "problem": self.problem,
            "detail": self.detail,
            "not_checked": self.not_checked,
            "model": self.model,
            "scope": self.scope,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
            "system_sha256": self.system_sha256,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            # 缓存两格（2026-10-19 补）：它们从 2026-10-14 起就存在 `SeamCall` 上、
            # 计价也按两档算了（`modelcost.usd_for`），但 `to_dict()` 此前漏了这两格
            # ⇒ `llm_call` 事件里根本没有"这一次命中没命中"的读数，于是
            # "提示词前缀稳不稳"在审计面上不可回答（上层再想汇总也无源可汇）。
            # 三态照旧：`None` = 上游没给这一格，与 `0` = 明说零命中分得开。
            "cache_hit_tokens": self.cache_hit_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
            "requested": self.requested,
            "usd": self.usd,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "recorded": self.recorded,
            "protocol": self.protocol,
            "tools_advertised": self.tools_advertised,
            "tools_sha256": self.tools_sha256,
            "reasoning_effort": self.reasoning_effort,
            "temperature": self.temperature,
            "reasoning_chars": self.reasoning_chars,
            "tool_calls": self.tool_calls,
        }


@dataclass
class SeamSpend:
    """累计用量（供预算守卫与读数）。"""

    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    unknown_usd_calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        """累计用量的可读视图（花销与"算不出来的次数"分开报）。"""
        return {"calls": self.calls, "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out, "usd": round(self.usd, 6),
                "unknown_usd_calls": self.unknown_usd_calls}


#: 逐角色登记的"默认模型缝"（装配期写入；工具层那条路从这里取）。
#:
#: ## 为什么需要它（两处断点，同一根因）
#:
#: `attack_tools._agent_for`（`F.step` 的工具路径）与 `verify_tools._agent_v`
#: （V 的三件工具）都拿不到 host 的装配上下文 —— 它们只从 `register(...)`
#: 得到 store 与工作区根。于是"模型驱动那一趟"里 H/F 有缝、而这两条路没有：
#: 真机读数（T2 第 14 趟 `p6p`）`F.step` 连续 5 次 `no_change`，因为工具层那条路
#: 造出来的 F 是 `AgentF(store)`（缝是 None）—— 而"没有缝"与"没有推理出东西"
#: 在读数上长得一模一样，那正是这一处最坏的地方。
#:
#: ## 为什么是"按角色"的一张表，而不是每个角色自己的模块级变量
#:
#: 后者就是同一件事的两份独立实现（`agent_f/core.py` 一份、`agent_v/core.py` 一份）
#: —— 两份必然分叉，而分叉是静默的（lint 的 R003 报的就是这个形态）。
#: 一张按角色索引的表既是单一来源，也保留了"每个角色一个缝"的语义：
#: F 的缝不该被 V 看见，V 的缝也不该被 F 看见。
#:
#: 默认空表 = 没接线（与 `host.DEFAULT_LLM_LOOPS` 同一条纪律：
#: 环境里有 key 也不改变行为，要接线必须由调用方显式登记）。
_ROLE_SEAMS: dict[str, Any] = {}


def set_role_seam(role: str, llm: Any) -> None:
    """登记某个角色的默认模型缝（`None` = 撤销登记，回到确定性实现）。"""
    _ROLE_SEAMS[str(role)] = llm


def role_seam(role: str) -> Any:
    """取某个角色登记的默认模型缝（没登记就是 `None`，也就是没接线）。"""
    return _ROLE_SEAMS.get(str(role))


#: 逐 `(工作区, 会话, 角色, 召唤号)` 的模型调用序号（幂等键的 `call_index`）。
#:
#: ## 为什么它必须在模块级、而不是 `LlmSeam` 的实例字段（判据 a 的根因之一）
#:
#: 现场（`temp/rmk90-audit/REPORT-R-mk-infinite-90-20261105.md` §A-5）：V 的 61 笔账散在
#: 35 个 `task_id` 上却只有 `t-000054` 一行有 token，A/B/E/F 的钱同样挤在"每个角色
#: 头几次召唤"那几行上。根因是幂等键：`_charge_ledger` 把 `f"{sid}:{role}"` 当
#: `task_id` 传进 `modelcost.idempotency_key`，而 `call_index` 取的是「这条缝自己的」
#: 计数器 —— 缝是每次召唤现造的（`host._seam` / `AgentV._seam` 都现造），
#: 计数器于是每次都从 0 开始。「第一次」召唤把 0,1,2… 这些键全占了，后面每一次召唤的
#: 第 i 次调用都撞上它 ⇒ 被判 `duplicate`、静默不记账。账本上"钱落在角色第一行"
#: 正是这么来的（不是有意按行首记，是后到的账全被吞了）。
#:
#: 序号因此挂在"这一次召唤"上（模块级、按召唤号索引）：缝可以现造，序号不回退；
#: 同一个召唤的第 i 次调用与别的召唤的第 i 次调用是两个键。跨进程不做假设 ——
#: 一次召唤只由一个进程执行，进程重启后的那一次是新召唤（新号）。
_CALL_SEQ: dict[tuple[str, str, str, str], int] = {}
_CALL_SEQ_LOCK = threading.Lock()


def _next_call_index(session_root: Any, sid: Any, role: Any, task_id: Any) -> int:
    """这个 `(工作区, 会话, 角色, 召唤号)` 上的第几次模型调用（从 0 起，单调递增）。"""
    key = (str(session_root or ""), str(sid or ""), str(role or ""), str(task_id or ""))
    with _CALL_SEQ_LOCK:
        idx = _CALL_SEQ.get(key, 0)
        _CALL_SEQ[key] = idx + 1
        return idx


def _idem_namespace(*, session_root: Any, sid: Any, role: Any, task_id: Any) -> str:
    """一次真调用的幂等键命名空间 = 「缝实例身份 + 召唤号」。

    ## 为什么不能只有召唤号（2026-11-15，RC2 彩排实测）

    序号 `call_index` 是按 `(工作区, 会话, 角色, 召唤号)` 数的，而键的命名空间
    改前只有 `task:<召唤号>`：同一个召唤上两条不同的缝（V 的本体那条 + 工具路径
    那条、秘书那条）都在自己的 `idx=0` 上算出一个键，后到的那一笔被判 `duplicate`
    —— 静默不记账。现场：16 次真调用只落 10 行账，6 笔被吞（`secretary:V` ×3、
    `V` ×2、`secretary:B` ×1），而三格照旧全绿（它们只要求"账本有行、无主 0、
    悬空 0"，不看"少了一行"）。

    ## 四格各回答一件事

    - `session_root`：同一进程里两个工作区各有各的 `t-000001`，不能互相撞；
    - `sid`：同一天里的两趟运行（缺省会话 / 显式会话）也是两本账；
    - `role`：同一个召唤上本体与秘书是两条缝（`V` / `secretary:V`）；
    - `task_id`：同一条缝在不同召唤上的第 i 次调用是两个键。

    前三格合起来就是这条缝的实例身份（`LlmSeam` 的四个构造输入里除去
    gateway/meter 的那三个）。它们与 `_next_call_index` 的计数键逐字同源 ——
    序号在哪个键上数、幂等键就必须在哪个键上分，否则"第 i 次"在两处指的不是同一件事。

    ## "同一次真调用只记一次"仍然成立

    命名空间是确定性的（不含随机量/内存计数器）：同一条缝、同一个召唤、同一进程或
    重跑一遍算出来的第 i 个键逐字相同 ⇒ 真正的重复记账（跨进程重放 / 同一笔重试）
    仍被判 `duplicate`。改掉的只是"两条不同的真调用互相吞"。
    """
    return (f"root:{str(session_root or '')}|sid:{str(sid or '')}"
            f"|role:{str(role or '')}|task:{str(task_id or '')}")


def ambient_task_id() -> str:
    """当前调用上下文里的召唤号（不在任何一次召唤里 ⇒ 空串）。

    为什么它存在：不是每一次模型调用都由循环那一路发生（V 的审阅工具、抽取那一路、
    秘书的判断都会单独发调用），而那些调用点手上的 `task_id` 常常是空串。空串不是
    "没有台账号"，是"没写"——`conductor.calling_as` / `summon` 的 `[6]` 步已经把
    "这一趟是谁"挂进了 ContextVar（`conductor.current_task_id`），所以这里能如实取到
    当时「真正在跑」的那个号，而不是让账本那一行永远 `task_id=None`。
    """
    try:
        from .conductor import current_task_id
        return str(current_task_id() or "").strip()
    except Exception:  # noqa: BLE001 —— 取不到就是取不到（空串），不猜一个号
        return ""


def ambient_sid() -> str:
    """当前调用上下文里的会话号（不在任何一趟里 ⇒ 空串）。

    与 :func:`ambient_task_id` 同族、同一个挂点（`conductor.calling_as` 的
    `sid=` 那一格）。为什么需要它：不少缝是在工具路径 / 惰性装配里现造的，那些
    调用点手上没有 host 的 `sid=`（`Secretary.for_role_wired`、`AgentV._seam`
    的兜底、各工具的秘书），于是它们的 `llm_call` 事件会落进缺省会话
    （`sessions/<当天日期>.jsonl`）—— 账本按 ambient task 归口看不出来，
    但"这一笔不在本趟的审计面上"是事实。

    空串 = 这一层不知道（与"缺省会话"是两个结论）：调用方拿去做 `sid=` 的缺省值时，
    必须自己决定"空串 ⇒ 不传"。
    """
    try:
        from .conductor import current_session
        return str(current_session()[1] or "").strip()
    except Exception:  # noqa: BLE001 —— 取不到就是取不到（空串），不猜一个会话号
        return ""


#: 逐 `(角色, 工作区根)` 登记的装配期配置（同一张表的旁边，不另开第二处注册表）。
#:
#: ## 为什么需要它
#:
#: `tools/attack_tools._agent_for` 与 `tools/verify_tools._agent_v` 这两条工具路径
#: 只拿得到 `store` 与工作区根 —— host 那一侧的装配上下文（`config=`）到不了它们手里。
#: 于是"F 的预算四键"在工具路径上永远是空 dict（`draft/44` J-07 实测：那四个键
#: 全仓无赋值点，`tools/attack_tools._agent_for` 也不传 `config=`）。
#:
#: ## 为什么按 root 键，不是全局单值
#:
#: `conductor_for` 就是按 `store.root` 缓存的（`draft/41` 的 B8：同进程里第二次装配
#: 会沿用第一次的设定 —— 真机每个 CLI 调用是一次进程，所以它没暴露）。
#: 一个全局单值会把 B8 换个地方重演：把 A 工作区的配置发给 B 工作区的 F，
#: 而读数上两边都"看起来正常"。按 root 键之后，两个工作区各自拿自己那一份。
#:
#: 默认空表 = 没登记 ⇒ 取到 `None` ⇒ 调用方按 `config=None` 走（`AgentF` 会把它当 `{}`，
#: 与"不传 config"逐字同形）。
_ROLE_CONFIGS: dict[tuple[str, str], Any] = {}


def set_role_config(role: str, root: Any, cfg: Any) -> None:
    """登记某个角色在某个工作区根上的装配期配置（`cfg=None` = 撤销登记）。

    `root` 用 `str(...)` 归一：调用方给的可能是 `Path` 或 `str`，
    两者指向同一个工作区时必须是同一个键（否则会静默出现"两份配置"）。
    """
    _ROLE_CONFIGS[(str(role), str(root))] = cfg


def role_config(role: str, root: Any) -> Any:
    """取某个角色在某个工作区根上的配置（没登记就是 `None`）。"""
    return _ROLE_CONFIGS.get((str(role), str(root)))


@dataclass
class LlmSeam:
    """一个角色的模型缝。同一角色的所有调用共用它（于是预算与用量是一份）。"""

    role: str
    session_root: Path
    gateway: Any | None = None
    scope: str = SEAM_SCOPE
    prompt_version: str = PROMPT_VERSION
    usd_budget: float | None = None
    sid: str | None = None
    price: tuple[float, float] | None = None
    spend: SeamSpend = field(default_factory=SeamSpend)
    #: 账本（`tokenmeter.TokenMeter`）。「不给就是没接账本」，而不是"记一笔零"。
    #:
    #: 为什么它是本类的一个字段（`draft/37` §64 的真机读数）：`run-agent` 这条路
    #: 从第一天起就没有任何地方把花销写进 `usage_ledger` —— 钱只活在
    #: `spend`（内存）与会话事件的 `llm_call.usd` 里。实测第 11 趟：会话里
    #: 30 次调用合计 0.289069 美元，而同一次运行的账本 9 行「全是 0.000000」，
    #: 于是 `reviewaccept.within_cost_cap` 拿着一份"花了 0"的账本判"没超上限"
    #: —— 假绿。缝是模型调用的唯一入口，所以记账必须挂在它身上。
    meter: Any = None
    #: 这个缝已经「试过」往账本里记第几次（幂等键的 `call_index`）。
    #:
    #: 为什么不复用 `spend.calls`：那两个数在两条早退路上不增长
    #: （`judge_not_wired` / `judge_over_budget` 在发请求之前就返回，
    #: 见 `ask` 的前两个分支），复用会让两次早退撞同一个幂等键，
    #: 而后到的那一笔被静默判成 `duplicate` —— 一笔真实记录凭空消失。
    ledger_calls: int = 0
    #: 现读上限的口子（预算轴）：给一个无参可调用，
    #: 每次花钱之前问一次"现在的总预算是多少"。`None` = 不看寄存器（用 `usd_budget`）。
    #:
    #: 为什么是回调而不是一个数：追加预算是运行期发生的（网页上点一下），
    #: 而这个缝是 dataclass —— 上限若只是一个字段，追加之后必须重启进程才生效，
    #: 那正好把业主那句"用户可追加预算"变成一句空话。回调每次读盘（`budget.limit_usd`），
    #: 于是"加钱 ⇒ 下一个调用就受新上限约束"。
    budget_of: Any = None

    def budget_limit(self) -> float | None:
        """这一次调用之前的上限（现读）：寄存器 > `usd_budget` > 不限。

        三态纪律：回调本身炸了（盘坏了/权限）不许把这一趟变成"不限量" ——
        回退到构造期那个 `usd_budget`（少花是安全的那一侧），异常由调用方在读数里看见。
        """
        if self.budget_of is None:
            return self.usd_budget
        try:
            got = self.budget_of()
        except Exception:  # noqa: BLE001 —— 见 docstring：回退到静态上限
            return self.usd_budget
        return self.usd_budget if got is None else got

    def spent_usd(self) -> tuple[float, str]:
        """全局已花多少钱，以及这个数是从哪儿读来的（`(usd, source)`）。

        ## 为什么必须是全局口径

        `budget_limit()` 给的是这一趟的总预算（盘上寄存器 / `--budget-usd`），
        而这里若比的是 `self.spend.usd` —— 这一条缝自己的累计。
        一个角色一条缝（`for_role`），于是每个角色都以为"我最多能花整笔"：
        十个角色就能把总预算花成十倍，而每一处闸门看起来都在"正常工作"。
        业主那句「只卡总花销的钱」说的正是这个数，不是某条缝的数。

        权威账只有一处：`usage_ledger`（`tokenmeter.TokenMeter.spent()`）。
        `meter is None`（没有账本的裸缝：单测与旧调用点）⇒ 退回 `self.spend.usd`，
        并把 `source` 明写成 `per_seam` —— 读数里不许把"两条缝各算一遍"
        与"读的是同一本总账"混成同一个数（那正是 B2 这个缺陷的形态）。

        `source` 的三态（读的人据此判这个数有多可信）：
        - `ledger`   —— 从 `usage_ledger` 现读（权威，包含所有角色的花销）；
        - `per_seam` —— 没有账本，只有这条缝自己的内存累计（口径更窄，如实标注）；
        - `ledger_unreadable` —— 有账本但读不出来（盘坏了）。回退到 `per_seam`
          并把问题记在 source 里：少算只意味着"这一处早停得晚一点"，
          而真正会拦住失控的那一处（`conductor._meter_guard`）读的是同一本账，
          它读不出来时会走它自己的失败路径，不会静默放行。
        """
        if self.meter is None:
            return float(self.spend.usd), "per_seam"
        try:
            got = self.meter.spent()
            return float(got.get("usd") or 0.0), "ledger"
        except Exception as exc:  # noqa: BLE001 —— 见 docstring 的三态
            return float(self.spend.usd), f"ledger_unreadable:{type(exc).__name__}"

    # -------------------------------------------------------------- 构造
    @classmethod
    def for_role(cls, role: str, *, session_root: Path | str, gateway: Any | None = None,
                 from_env: bool = True, settings_path: str | Path | None = None,
                 **kw: Any) -> "LlmSeam":
        """按角色造一个缝。`from_env=True` 时读配置（没 key 就是没接线）。

        配置的梯子是 `modelgw.spec_for(role, ...)`：`models.<角色>` → `models.default`
        → `model` 段 → 环境变量 → 内置缺省（允许按角色用不同厂商的
        不同 key）。`gateway` 显式给的时候按老口径用给的那个（判据与替身模型都走这条）。
        """
        if gateway is None and from_env:
            spec, _where = MG.spec_for(role, path=settings_path)
            gateway = MG.ModelGateway(spec) if spec.configured else None
        return cls(role=role, session_root=Path(session_root), gateway=gateway, **kw)

    @classmethod
    def for_secretary(cls, *, owner_role: str = "", session_root: Path | str,
                      gateway: Any | None = None, from_env: bool = True,
                      settings_path: str | Path | None = None, **kw: Any) -> "LlmSeam":
        """所有角色的秘书共用的那一把 key。

        它与 :meth:`for_role` 的差别只有一处：配置的第一格是 `secretary` 段
        （`modelgw.spec_for(secretary=True)`），而不是那个角色自己的那一档。
        为什么秘书要单独一把：秘书的模型调用是"判断类"（`Secretary.judge`），
        共用一把 key 才能单独限额、单独看账；而"本体的 key"与"秘书的 key"
        混在一起时，一次判断花掉的钱会记在本体的账上、看不出是谁花的。

        `role` 那一栏记的是 `secretary:<owner_role>` —— 账本按 `by_role` 归口，
        这一栏让"哪个角色的秘书花的钱"在汇总里读得出来
        （`usage_ledger` 的 `by_role` 那一栏）。
        """
        if gateway is None and from_env:
            spec, _where = MG.spec_for(secretary=True, path=settings_path)
            gateway = MG.ModelGateway(spec) if spec.configured else None
        label = f"secretary:{owner_role}" if owner_role else "secretary"
        return cls(role=label, session_root=Path(session_root), gateway=gateway, **kw)

    @property
    def wired(self) -> bool:
        """这次运行有没有接上模型（没接上就是 judge_not_wired，不是"没有结论"）。"""
        return self.gateway is not None

    @property
    def model_name(self) -> str:
        """这次用的是哪个模型（审计记录的一栏；拿不到就给空串）。"""
        spec = getattr(self.gateway, "spec", None)
        return str(getattr(spec, "model", "") or "")

    @property
    def reasoning_effort(self) -> str:
        """这次按哪个推理强度问（审计记录的一栏；没接线时是空串）。

        为什么从 spec 上读而不是在这里再写一个缺省：强度的唯一来源是
        `ModelSpec.reasoning_effort`（`modelgw`），这里只做"如实转抄"。
        转抄的那一栏会进会话事件 —— 于是"这一趟要求它想多深"在审计面上可查。
        """
        spec = getattr(self.gateway, "spec", None)
        return str(getattr(spec, "reasoning_effort", "") or "")

    def temperature_of(self, requested: float | None = None) -> float | None:
        """这一次真正会进请求体的那个温度（审计记录的一栏；没接线时是 `None`）。

        显式给的优先（`ask(temperature=…)`）；没给就取这一档配置
        （`ModelSpec.temperature`，唯一来源在 `modelgw`，这里只转抄）。
        没接线时回 `None` 而不是 0：这一趟没有请求体，"没查过"与"发了个 0"必须分开。
        """
        if not self.wired:
            return None
        if requested is not None:
            return float(requested)
        spec = getattr(self.gateway, "spec", None)
        got = getattr(spec, "temperature", None)
        return None if got is None else float(got)

    # -------------------------------------------------------------- 调用
    def ask(self, prompt: str, *, system: str = "", task_id: str = "",
            note: str = "",
            face: "ToolFace | None" = None,
            temperature: float | None = None) -> SeamCall:
        """发一次调用，落一条审计记录，返回结局（不抛业务异常）。

        `max_tokens` 这一栏不设（「我们不卡 token，只卡总花销的钱」）。
        它若设了，会由循环步（`agent_loop`）传 32,768；不设则请求体里没有这一栏，
        额度交回上游（真调用对照：不带比带 32768 还宽）。

        `temperature`：不给就用这一档配置的温度（`ModelSpec.temperature`，
        缺省 0.2）—— 与不给时逐字相同。给了就透传进请求体并记进 `SeamCall.temperature`。
        为什么要显式这一格：业主把 V 的审阅调用定在 1.0（正常对话的数值），
        而"这一次按几度问的"必须能在审计记录里读回来（读数与请求体同源）。
        """
        t0 = time.monotonic()
        base = dict(
            prompt_version=self.prompt_version,
            prompt_sha256=_sha(prompt),
            system_sha256=_sha(system) if system else "",
            model=self.model_name,
            scope=self.scope,
            protocol="tool_calls" if face is not None else "text",
            tools_advertised=len(face.functions) if face is not None else 0,
            tools_sha256=face.sha256 if face is not None else "",
            # "我们要求它想多深"：配置面的读数（结果面是下面的 `reasoning_chars`）。
            reasoning_effort=self.reasoning_effort,
            # "这一次按几度采样"：与 `_payload` 里那一格同源（没接线 ⇒ None）。
            temperature=self.temperature_of(temperature),
        )
        if not self.wired:
            call = SeamCall(ok=False, problem="judge_not_wired",
                            detail="没有配置模型（环境变量 AGENTFLOW_MODEL_API_KEY 与 "
                                   "agentflow/settings.json 的 model.api_key 都没有值）"
                                   "：这是没查成，不是没有问题",
                            # 没有发请求 ⇒ 不可能有缓存读数（第零态，见 `SeamCall.requested`）。
                            requested=False,
                            elapsed_sec=time.monotonic() - t0, **base)
            # `charged=False`：这一次「没有发请求」，所以没有钱要记。
            # 会话事件照旧留一条（"试过、没接线"是事实），账本不入账。
            return self._land(call, prompt=prompt, system=system, task_id=task_id, note=note,
                              charged=False)
        budget = self.budget_limit()
        spent, spent_source = self.spent_usd()
        if budget is not None and spent >= budget:
            call = SeamCall(ok=False, problem="judge_over_budget",
                            detail=(f"花销预算已耗尽（**全局**已用 {spent:.6f} / 上限 "
                                    f"{budget:.6f}；已花读数来自 {spent_source}）"
                                    "—— 这一次没有发起请求"),
                            requested=False,
                            elapsed_sec=time.monotonic() - t0, **base)
            return self._land(call, prompt=prompt, system=system, task_id=task_id, note=note,
                              charged=False)

        # 温度这一格只在调用方显式给了时才传下去：
        # 它是给 V 的审阅调用加的那一格；无条件传会让所有"按脚本回文本"的替身网关
        # （它们没有这个形参）在调用期抛 TypeError，而那个 TypeError 会被上层折成
        # `judge_failed:TypeError` ⇒ 一条本该绿的判据红在"替身签名"上，不是行为上。
        # 不给就压根不传 ⇒ 网关取这一档配置的那一格（两处同源，见 `temperature_of`）。
        _kw: dict[str, Any] = {}
        if temperature is not None:
            _kw["temperature"] = temperature
        try:
            reply = self.gateway.complete(prompt, scope=self.scope,
                                          system=(system or None),
                                          tools=(face.functions if face is not None else None),
                                          **_kw)
        except J.BudgetExhausted as exc:
            return self._finish_failure("judge_over_budget", str(exc), base, t0,
                                        prompt, system, task_id, note)
        except J.JudgeRefused as exc:
            return self._finish_failure("judge_refused", str(exc), base, t0,
                                        prompt, system, task_id, note)
        except TimeoutError as exc:
            return self._finish_failure("judge_timeout", str(exc), base, t0,
                                        prompt, system, task_id, note)
        except Exception as exc:  # 其它异常按类型归类，绝不吞掉
            return self._finish_failure(f"judge_failed:{type(exc).__name__}", str(exc),
                                        base, t0, prompt, system, task_id, note)

        usd, usd_note = self._usd_of(reply)
        calls = tuple(getattr(reply, "tool_calls", ()) or ())
        reasoning = str(getattr(reply, "reasoning", "") or "")
        call = SeamCall(
            ok=bool(getattr(reply, "ok", False)),
            text=str(getattr(reply, "text", "") or ""),
            # "它实际想了多少字"：结果面的读数。它与 `base` 里的 `reasoning_effort`
            # 成对，四种组合各自指向不同的修法（见 `SeamCall.reasoning_effort` 那段）。
            reasoning_chars=len(reasoning),
            # 原文那一条（12-A=乙：下一轮原样带回去）—— 只有它能让"它记得自己想过什么"成立。
            reasoning=reasoning,
            # "没查成"与"它回了看不懂的东西"在这一格必须分得开：网关从不抛异常，
            # 超时/网络/认证都折成 `ok=False` + `error_kind`（映射只有 `judge.problem_of_reply`
            # 一处）。真机读数：三次超时全落成 `judge_failed:ModelReplyNotOk`，
            # 循环据此把它算成"坏 JSON"并写成"连续 3 次没有给出可解析的 JSON"。
            problem=J.problem_of_reply(reply),
            detail=str(getattr(reply, "error_detail", "") or ""),
            tokens_in=int(getattr(reply, "tokens_in", 0) or 0),
            tokens_out=int(getattr(reply, "tokens_out", 0) or 0),
            # 缓存命中/未命中：三态照抄上游（`None` = 没回这一格）。
            cache_hit_tokens=getattr(reply, "cache_hit_tokens", None),
            cache_miss_tokens=getattr(reply, "cache_miss_tokens", None),
            billing=self._billing_of(reply),
            usd=usd,
            elapsed_sec=time.monotonic() - t0,
            tool_calls=len(calls),
            tool_call_list=calls,
            **base,
        )
        if usd_note:
            call = SeamCall(**{**call.__dict__, "detail": (call.detail + "；" + usd_note).strip("；")})
        self.spend.calls += 1
        self.spend.tokens_in += call.tokens_in
        self.spend.tokens_out += call.tokens_out
        if usd is None:
            self.spend.unknown_usd_calls += 1
        else:
            self.spend.usd += usd
        return self._land(call, prompt=prompt, system=system, task_id=task_id, note=note)

    def _finish_failure(self, problem: str, detail: str, base: Mapping[str, Any],
                        t0: float, prompt: str, system: str, task_id: str,
                        note: str) -> SeamCall:
        call = SeamCall(ok=False, problem=problem, detail=detail,
                        elapsed_sec=time.monotonic() - t0, **dict(base))
        self.spend.calls += 1
        return self._land(call, prompt=prompt, system=system, task_id=task_id, note=note)

    def _price_now(self) -> tuple[Any, dict[str, Any]]:
        """这一笔该按哪一档价算（厂商 × 模型 × 峰谷）+ 取价读数。

        显式给了 `self.price`（判据与替身模型走这条）就用它，读数标 `explicit`；
        否则按这次调用用的那个模型去价目表取（`modelcost.price_for`）——
        这正是"花销与供应商定价吻合"那条要求落地的地方：不同厂商/不同模型/峰谷
        各有自己的价，而不是一个数打天下。

        "从配置里读出厂商与模型"这一步（含"没配 vendor 就按端点认一家"）
        不在本函数里，在 `modelgw.vendor_model_of`：它若分两处就是抄两份
        （这一处一份，`modelcost.price_of` 那一处干脆没有）⇒ 两条路的计价口径
        不一致而两边都自洽。口径只许有一处。
        """
        if self.price is not None:
            p = self.price if isinstance(self.price, MC.Price) else MC.Price(*self.price)
            return p, {"price_source": "explicit", "peak": None}
        spec = getattr(self.gateway, "spec", None)
        vendor, model = MG.vendor_model_of(spec)
        return MC.price_for(vendor, model)

    def _usd_of(self, reply: Any) -> tuple[float | None, str]:
        """按价格表算这次花销。算不出来就如实说算不出来（不许悄悄记 0）。"""
        try:
            price, _reading = self._price_now()
            return float(MC.usd_for(reply, price)), ""
        except Exception as exc:  # 价格表缺失/格式不对：这不影响结论，但必须留痕
            return None, f"花销未能折算（{type(exc).__name__}: {exc}）"

    def _billing_of(self, reply: Any) -> dict[str, Any]:
        """这一笔的计价读数（三档价 + 命中数 + 用了峰/谷哪一档 + "我们不知道"的那几格）。

        为什么留它（「花销标准与供应商定价吻合」）：`usd` 是一个数，
        而"这个数按哪几档价、按峰还是按谷算出来的"必须能复核。三种会让它偏高的情形 ——
        命中价未登记、上游没报命中数、没登记的组合回落到了缺省价 —— 各有一条痕迹，
        读账的人因此不会把"我们算贵了"读成"供应商算错了"。
        """
        try:
            price, reading = self._price_now()
            out = dict(MC.billing_reading(reply, price))
            out.update(reading)
            return out
        except Exception as exc:  # noqa: BLE001 —— 读数算不出来不许带走这一趟
            return {"cache_tri": "unreadable", "why": f"{type(exc).__name__}: {exc}"}

    # -------------------------------------------------------------- 落账
    def _charge_ledger(self, call: SeamCall, *, task_id: str) -> dict[str, Any]:
        """把这次调用的花销写进 `usage_ledger`；返回"记成哪一行"的可读读数。

        ## 为什么不用 `modelcost.charge_reply`

        `charge_reply` 是为 `modelgw.ModelReply` 写的：它自己拿 `reply` 重算
        `usd_for(...)`（价与「重试次数」都从 `reply` 上取）。而这里手上是
        `SeamCall`，它没有 `attempts` 字段 —— 走 `charge_reply` 会让
        "网关重试过的调用"在账本上只按一次计价，而会话事件里那个 `usd`
        （`_usd_of` 用真 `reply` 算的，含重试）比它大：「同一笔钱两处两个数」。
        所以这里直接造 `Charge`：`usd=call.usd`、`attempts=1`
        —— `_row_for` 的 `usd_total = round(usd × attempts, 6)` 于是与事件里的
        `usd` 逐位相等（判据 `tests/test_ledger_charging.py` 钉的就是这个相等）。
        入账本身仍走同一条实现（`TokenMeter.charge_once` → `_row_for`）。

        ## 四条口径

        1. `meter=None` ⇒ 「不入账」，且如实报 `no_meter`（不是"记了一笔零"，
           更不是"免费"）；
        2. `call.usd is None`（价表不可用）⇒ 记一行 `usd=0` 且 `note` 里写明
           "这一行的 0 是「算不出来」" —— 账本今天表达不了这一档
           （`UsageEntry.usd` 是 float 且是 FC-27 字段），所以用 `note` 留痕，
           由 `reviewaccept._c_cost` 的交叉判据把这一格判成 `unknown`；
        3. 上游没回 usage（tokens 全 0）⇒ 零值也记，`note` 写明"不是真花了零"
           （账本设计②：`没记账` 与 `花了零` 必须分得开）；
        4. 失败也记（`ok=False` 但发过请求）：钱可能已经花了，而且"这次尝试"
           本身就是要被看见的事实。

        ## 归口（判据 a）：这笔钱记到「当时真正在跑的那一次召唤」上

        两个来源，优先级从高到低（`task_id` 的取值规则只有这一处）：

        1. 调用方显式给的 `task_id`（循环那一路会给）；
        2. 没给 ⇒ `ambient_task_id()`（`conductor.current_task_id()`：召唤上下文里
           挂着"这一趟是谁"）。V 的审阅工具、抽取那一路、秘书的判断都走这一档 ——
           不传它们就是空串，那些账落在 `task_id=None` 上，
           既不属于任何一行 `tasks`、也点不出名；
        3. 两处都没有（不在任何一次召唤里）⇒ 如实 `task_id=None`，并在 `note` 里
           写 `unattributed` 与原因。这一档是「说得出为什么」的空，不是"忘了填"：
           `reconcile_usage` 会把它单列一栏，判据 b 要求"要么 0 笔、要么全部点名"。

        ## 幂等键（判据 a 的另一半根因）

        键必须是「这一次召唤的第 i 次调用」，不是"这条缝的第 i 次调用"：缝是每次召唤
        现造的（`host._seam` / `AgentV._seam`），用缝自己的计数器会让第一次
        召唤把 `(sid, role, 0..n)` 全占满，后面每一次召唤的同号调用都被判 `duplicate`
        —— 钱静默不记（现场：V 的 61 笔账只有 27 笔真的落账，其余 34 笔撞键被吞）。
        所以 `call_index` 取自 `_next_call_index(...)`（模块级、按召唤号索引）。

        命名空间还必须与那个序号的计数键同源（`_idem_namespace`：工作区 + 会话 +
        角色 + 召唤号）。改前它只有 `task:<号>` ⇒ 同一个召唤上的两条缝（V 的本体 /
        工具路径、本体 / 秘书）在各自的 `idx=0` 上撞键，后到的被静默吞掉
        （RC2 彩排：16 次真调用只落 10 行账）。"同一次真调用只记一次"由命名空间的
        确定性保证，不靠"少写一个维度"。
        """
        from . import tokenmeter as TM

        if self.meter is None:
            return {"charged": False, "usage_id": "", "reason": "no_meter",
                    "note": "这个缝没有接账本（meter=None）⇒ 本次没有入账（不是记了一笔零）"}
        given = str(task_id or "").strip()
        tid = (given or ambient_task_id()) or None
        idx = _next_call_index(self.session_root, self.sid, self.role, tid or "")
        self.ledger_calls += 1          # 读数：这条缝试过几次（不参与键的构造）
        outcome = "ok" if call.ok else (call.problem or "failed")
        note = f"source=llmseam;role={self.role};call_index={idx};outcome={outcome}"
        if tid is None:
            note += ("；unattributed：这一次调用没有台账号可挂"
                     "（调用方没给 task_id，且不在任何一次召唤的上下文里）"
                     "⇒ 这一行的 task_id 为空，它进不了任何一行 tasks.usd")
        # 花销口径的留痕（「花销计算标准与供应商定价吻合」）：
        # 账本那一行自己要说得清这笔钱按哪一档价算的 —— 否则"和供应商账单对不上"
        # 只能靠翻会话事件才查得出来。四格都从 `SeamCall.billing` 现抄（不另算一份）。
        billing = dict(getattr(call, "billing", None) or {})
        if billing:
            note += ("；price=" + str(billing.get("price_source") or "?")
                     + f";vendor={billing.get('vendor') or '-'}"
                     + f";model={billing.get('model') or self.model_name or '-'}"
                     + f";peak={billing.get('peak')}"
                     + f";cache={billing.get('cache_tri') or '?'}"
                     + f";in_hit={billing.get('usd_per_m_in_hit')}"
                     + f";in={billing.get('usd_per_m_in')}"
                     + f";out={billing.get('usd_per_m_out')}")
        tokens_in = int(call.tokens_in or 0)
        tokens_out = int(call.tokens_out or 0)
        if call.usd is None:
            note += ("；花销未能折算（价格表不可用）⇒ 本行的 0 是「算不出来」，不是零花销")
        elif not tokens_in and not tokens_out:
            note += "；上游未回 usage ⇒ 本次只能按零记（不是真花了零）"
        charge = TM.Charge(
            role=self.role, scope=self.scope,
            tokens_in=tokens_in, tokens_out=tokens_out,
            usd=float(call.usd or 0.0), attempts=1, task_id=tid, note=note,
        )
        # 键的命名空间：与 `_next_call_index` 的计数键同源（工作区 + 会话 + 角色 +
        # 召唤号）。只写召唤号会让同一召唤上两条不同的缝撞键 —— 见 `_idem_namespace`。
        namespace = _idem_namespace(session_root=self.session_root, sid=self.sid,
                                    role=self.role, task_id=tid or "")
        key = MC.idempotency_key(namespace, idx)
        try:
            logged = self.meter.charge_once(charge, idem_key=key)
        except Exception as exc:  # 记账失败必须看得见（它是审计面，不是可选项）
            return {"charged": False, "usage_id": "", "reason": "charge_failed",
                    "note": f"入账失败：{type(exc).__name__}: {exc}"}
        return {
            "charged": bool(logged.get("recorded")),
            "usage_id": str(logged.get("usage_id") or ""),
            "reason": "charged" if logged.get("recorded") else "duplicate",
            "idem_key": key,
        }

    def _land(self, call: SeamCall, *, prompt: str, system: str, task_id: str,
              note: str, charged: bool = True) -> SeamCall:
        # 先记账、再写会话事件：万一中间崩了，宁可留一条"账上有钱、事件没有"
        # （钱记下了），也不要"事件有钱、账上没有"（那正是本次要修的漏记方向）。
        #
        # 归口只解析一次：账本行与会话事件必须说同一个号（`_charge_ledger` 自己的
        # 解析在"给了号"时与这里逐字相同，两处不会分家）。
        resolved = str(task_id or "").strip() or ambient_task_id()
        ledger = (self._charge_ledger(call, task_id=resolved) if charged
                  else {"charged": False, "usage_id": "", "reason": "no_request",
                        "note": "这次没有发请求（没接线 / 预算已尽）⇒ 没有钱要记"})
        event = {
            "kind": "llm_call",
            "role": self.role,
            "task_id": resolved,
            "note": note,
            "prompt_chars": len(prompt),
            **call.to_dict(),
            "spend_after": self.spend.to_dict(),
            # 「这次调用的钱记进账本了吗、记成哪一行」——会话事件自己给出答案，
            # 于是"账本与事件对不上"可以逐笔追，而不是靠两个汇总数猜。
            "ledger": ledger,
        }
        try:
            _path, problem = SS.append(self.session_root, event, sid=self.sid)
        except Exception as exc:  # 落档失败不许静默：它是审计面
            problem = f"会话记录写入抛异常：{type(exc).__name__}: {exc}"
        if problem:
            return SeamCall(**{**call.__dict__, "recorded": problem})
        return call

    def _parse_text_json(self, call: SeamCall) -> tuple[dict[str, Any] | None, SeamCall | None]:
        """把回复正文解析成对象；解析不出来 ⇒ `(None, 坏结局)`（`ask_json` / `ask_step` 共用）。

        为什么两处共用一个：`judge_bad_json` 的码、detail 的措辞与"原文前 200 字"是
        同一件事，两处各写一遍会漂；漂了之后"哪条路把坏 JSON 说成什么"就没人数得清。
        """
        from .llm import parse_llm_json

        err = ""
        try:
            data = parse_llm_json(call.text)
        except Exception as exc:
            # 把解析报错原文 + 一句话诊断留下来：只写
            # "不是 JSON 对象"，于是"它到底哪里写坏了"在台账上不可回答。
            # 真机实测：模型（M 与 G 的循环都）连着三次多写一个右花括号
            # （`…"why": "…"}}`）—— 现在这句话会进"纠正消息"，模型下一次就能改对。
            data = None
            err = f"{type(exc).__name__}: {exc}"
        if not isinstance(data, Mapping):
            hint = _json_shape_hint(call.text)
            return None, SeamCall(
                **{**call.__dict__, "ok": False, "problem": "judge_bad_json",
                   "detail": (f"模型返回的不是一个 JSON 对象（解析报错：{err or '不是对象'}）"
                              f"{hint}；原文前 200 字：{str(call.text)[:200]}")})
        return dict(data), None

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict[str, Any] | None, SeamCall]:
        """要一份 JSON：返回 `(判定, 结局)`。坏 JSON 归成 `judge_bad_json`，不静默当空。"""
        call = self.ask(prompt, system=system, task_id=task_id, note=note)
        if not call.ok:
            return None, call
        data, bad = self._parse_text_json(call)
        return (None, bad) if bad is not None else (data, call)

    def ask_step(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "",
                 face: ToolFace | None = None) -> tuple[dict[str, Any] | None, SeamCall]:
        """循环的一步：优先用原生工具调用，拿不到就回落去解析文本 JSON。

        为什么要这一层（`draft/37` §48/§49）：文本协议要求模型把调用重新序列化成
        一行 JSON，于是"键名漂移"（`tool` 写成 `name`）会连累整趟运行
        （第三趟真机就死在这里）。原生工具调用把名字放进传输层的结构化字段 ——
        那一类失败在结构上不再存在。回落路径一个字都没放宽：没有原生工具调用的
        传输层（离线缝 / mock / replay / 没接线的判定）照旧走 `ask_json` 的那一套，
        既有判据因此一条都不用改。
        """
        call = self.ask(prompt, system=system, task_id=task_id, note=note, face=face)
        if not call.ok:
            return None, call
        if face is not None and call.tool_call_list:
            # D-35（方案 B）：一步给多条原生调用时只执行第一条，其余丢弃 ——
            # 但丢弃必须留读数，所以这里不把 `tool_call_list` 摘掉：整份调用原样
            # 随 `call` 回去，循环那侧据 `call.tool_call_list[1:]` 在 step 结果里
            # 写一条 `warn`（点名被丢的那几条的 action 名）。
            #
            # 为什么不再把整步判成 `judge_bad_json`：r34b 真机
            # 147 步里有 10 步因为"给了 2 条工具调用"整步作废，而 token 早就计费了
            # （有的步 `tokens_out` 到 6000），产出全丢。"多条"不是坏数据，是模型
            # 多给了一条 —— 它不是"没按协议说话"，所以不该走坏 JSON 那一档。
            data, problem, detail = face.to_shape(call.tool_call_list[0])
            if data is None:
                # ---- 坏参数要留原文
                #
                # 若原样构造 `SeamCall(**{**call.__dict__, ...})`，`text` 仍是
                # 回复正文（原生调用时为空）⇒ 循环的 `_dump_invalid_reply` 写出
                # 0 字节文件，而报错里的 char 6691 谁也复核不了。
                # `judge_bad_args` 缺的那段证据就是 arguments 本身，所以这一类把
                # `text` 换成它（其它码一个字不改：坏 JSON 的 `text` 本来就是回复正文）。
                extra = ({"text": face.raw_args_text(call.tool_call_list[0])}
                         if problem == "judge_bad_args" else {})
                bad = SeamCall(**{**call.__dict__, "ok": False, "problem": problem,
                                  "detail": detail, **extra})
                return None, bad
            return data, call
        # 回落：上游没给结构化调用（或不支持 tools）⇒ 走文本 JSON 那条路。
        data, bad = self._parse_text_json(call)
        if bad is not None:
            return None, bad
        return data, SeamCall(**{**call.__dict__, "protocol": "text"})


#: `framework_final` 的 `notify` 那一栏的 schema（`agent_prompts` §7 与
#: `agent_loop.NOTIFY_FIELDS` 逐字同一份字段表）。
#:
#: 为什么必须写进广告面：提示词要求
#: 非主控角色收工时填这一栏，而原生工具面这一趟根本没有这一格；就算模型硬塞，
#: `ToolFace.to_shape` 也只会重建 `final`+`evidence` ⇒ 「收工手稿」的输入在结构上到不了
#: 秘书。广告面与接受面必须是同一份（`META_FUNCTIONS` 上面那条纪律）—— 这一格就是那
#: 条纪律漏掉的地方：`agent_loop._decode_shape` 收 `notify`，而广告面没有它。
#:
#: `required` 刻意留空：`notify` 在 `_decode_shape` 那侧是可选键（L-05e 之后
#: "没填/填错都不打回，只落 `notify_problem` 读数"），而主控 M 免填。把它列成
#: 传输层必填会让上游先拒掉一次"合法的收工" —— 那正是 L-05e 撤掉的那道闸门。
NOTIFY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "to": {"type": "string",
               "description": ("交给谁：名册名（如 D1）/ 绝对编号（如 t-000123）/ 角色名，"
                               "或主控 M 的本号；广播 `ALL` 已退场"
                               "（会被受控拒绝 `broadcast_retired`）")},
        "summary": {"type": "string",
                    "description": "一句话：交给对方什么（它会被拼进那条留言）"},
        "body": {"type": "string",
                 "description": ("markdown 正文：做了什么 / 依据（实验号、文献号、手稿号）/ "
                                 "要对方做什么 / 我卡在哪")},
        "refs": {"type": "array", "items": {"type": "string"},
                 "description": "前序手稿编号，或 stmt:/exp:/lit:/rel:/q:/c: 这类台账引用"},
        "why": {"type": "string", "description": "一句话说明为什么交这一份（可选）"},
    },
    "required": ["to", "summary", "body"],
}


#: `framework_summon` / `framework_summon_many` 的 `notify` 那一栏：主控派活时的留痕
#: （`agent_prompts` 循环协议第 2) 段逐字："主控（M）派活时留痕：这一句里可以带一张 `notify` 表"）。
#:
#: 与收工那一份 `NOTIFY_JSON_SCHEMA` 的差别只有一格：`to` 可以不填 ——
#: `agent_loop._dispatch_notify` 会把它补成"被派的那个角色"（多目标补 `ALL`，
#: 而写入口自 2026-11-20 起对 `ALL` 受控拒绝 `broadcast_retired`），
#: 于是"给谁派了活"与"手稿发给谁"不会因为要填两遍而分家。所以这一份的 `required`
#: 是 `summary` / `body`，不是 `["to", "summary", "body"]`。
#:
#: 为什么必须广告（`draft/108` CS-18）：`_decode_shape` 的 `summon` / `summon_many`
#: 两支都调 `_with_notify` 把这一栏带进 payload，而原生面没有它 ⇒ 原生那条路上
#: 主控结构上给不出留痕，只能退回"框架据派活派生"的那一行 —— 而那一行按本仓口径
#: 只是日志、不算交接。与 `NOTIFY_JSON_SCHEMA` / `blocked` 是同一族（批 R47 修的是
#: 形状名与 `final.blocked`，本批修的是键一级的这两格）。
DISPATCH_NOTIFY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "to": {"type": "string",
               "description": ("交给谁（可省略：不填就是被派的那个角色；"
                               "写名册名 / 绝对编号 / 角色名。"
                               "广播 `ALL` 已退场，填它会被受控拒绝 `broadcast_retired`）")},
        "summary": {"type": "string",
                    "description": "一句话：派了什么活（它就是留言里那句）"},
        "body": {"type": "string",
                 "description": ("markdown 正文：派了什么、依据（实验号、文献号、手稿号）/ "
                                 "要对方做什么 / 为什么")},
        "refs": {"type": "array", "items": {"type": "string"},
                 "description": "前序手稿编号，或 stmt:/exp:/lit:/rel:/q:/c: 这类台账引用（会被逐条核）"},
        "why": {"type": "string", "description": "一句话说明为什么交这一份（可选）"},
    },
    "required": ["summary", "body"],
}


#: 循环协议里那些不是工具的形状（`agent_loop.SHAPES` 减去 `tool`）：
#: 它们与真工具一起被广告成函数。理由是我们自己的一条纪律：广告出来的形状必须
#: 与接受得到的形状一致（判据 `tests/test_native_tool_calls.py` 逐字对账两张表），
#: 而"这一步要做什么"这件事的名字应当来自传输层的结构化字段，不是模型手写的一行 JSON
#: —— 后者要把名字拼错、把参数写坏，才在工具层被发现（`draft/37` §65 的真机现场）。
#:
#: 每项是 `(广告名, 目标形状, 参数 schema)`；schema 的形状与 `agent_loop._shape_of`
#: 认的那一套逐字对齐（那里仍是唯一判有效性的地方 —— 这里只负责"把名字翻译过去"）。
META_FUNCTIONS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("framework_summon", "summon", {
        "type": "object",
        "properties": {
            "role": {"type": "string", "enum": list("ABCDEFGHV")},
            # 口径 S2 最终形态：`action` 整个摘掉 ——
            # 原话逐字：「一致改成 task 必填，action 不填」「action 完全不用父代理填」。
            # ⇒ 派活只有一种形状：`role` + `task`。点哪个动作是被派者自己的事
            # （它那一趟跑自己的循环、从自己的工具面与手册里选）。
            # 内部调用方（`pipeline` / `scheduler` / `deliver`）直接调
            # `Conductor.summon(role, action, params)`，不受这一格影响。
            "task": {"type": "string", "description":
                     "**必填**：这一趟派给它的是什么活（写清做什么；可带起手建议，怎么做由它定）"},
            "params": {"type": "object"},
            "why": {"type": "string"},
            # S1k-4（名册口径）：造一个新子代理给一句简介；复用已有子代理写它的名册名；
            # 也可以自己提名。这三格与 `agent_loop._decode_shape` 的接受面同源
            # （广告一份、执行另一份，模型就会按广告写而框架说不认识）。
            "brief": {"type": "string", "description": "一句任务简介（单行、≤60 字），进名册"},
            "name": {"type": "string", "description": "可选：给这个子代理起的名册名（如 D3）"},
            "reuse": {"type": "string", "description": "复用已有子代理时写它的名册名（如 D1）"},
            # 主控派活时的留痕（CS-18）：与 `_dispatch_notify` 同源，`to` 可省略。
            "notify": DISPATCH_NOTIFY_JSON_SCHEMA,
        },
        # 口径 S2：`task` 进必填，`action` 保持可选。
        # 口径是"派活" —— 那件活是必说的；点不点动作由派活方决定（点了就是老行为）。
        "required": ["role", "task"],
    }),
    ("framework_summon_many", "summon_many", {
        "type": "object",
        "properties": {
            "targets": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": list("ABCDEFGHV")},
                    # 口径 S2 最终形态：`action` 同样摘掉 —— 派活只有
                    # `role` + `task` 两格（与 `summon` 一致）。
                    "task": {"type": "string", "description":
                             "**必填**：这件活是什么（写清做什么；可带起手建议，怎么做由它定）"},
                    "params": {"type": "object"},
                    "instance": {"type": "string"},
                    "input_key": {"type": "string"},
                    # S1k-4：一批派活也各带自己的简介/提名（口径同 `framework_summon`）
                    "brief": {"type": "string"},
                    "name": {"type": "string"},
                    "reuse": {"type": "string"},
                },
                "required": ["role", "task"],
            }},
            "why": {"type": "string"},
            # 一批派活同样带留痕（`agent_prompts` 第 2b) 段的例子逐字有这一格，CS-18）。
            "notify": DISPATCH_NOTIFY_JSON_SCHEMA,
        },
        "required": ["targets"],
    }),
    # `framework_ask_user` 的 schema 必须与 `userio` 真收的形状一致（`draft/37` §72）：
    # 选项是 `{"label","description"}` 对象、另有 `header` 与 `multi_select`（DSH 的
    # 形状：稳定 id + 短标题 + 选项带说明 + 多选）。旧形状（裸字符串选项）「照样收」
    # ——`_shape_of` 走 `userio.coerce_option` 归一化—— 但广告面必须广告真的那一份：
    # 广告一份、执行另一份，就会让模型按广告写而框架说"这不是我认识的形状"。
    ("framework_ask_user", "ask_user", {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "header": {"type": "string", "description": "短标题（一行，给界面用）"},
            "options": {"type": "array", "items": {
                "type": "object",
                "properties": {"label": {"type": "string"},
                               "description": {"type": "string"}},
                "required": ["label"],
            }, "description": "推荐项放首位，并在 label 末尾写 (Recommended)"},
            "multi_select": {"type": "boolean"},
            "timeout_sec": {"type": "number",
                            "description": "不给 = 一直等（停着）；0 = 问了就交还控制权"},
        },
        "required": ["question"],
    }),
    ("framework_note", "note", {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }),
    ("framework_message", "message", {
        "type": "object",
        "properties": {
            "to": {"type": "string",
                   "description": ("名册名（如 D1）/ 绝对编号（如 t-000123）/ 角色名，"
                                   "或主控 M 的本号；广播 `ALL` 已退场"
                                   "（会被受控拒绝 `broadcast_retired`）")},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "reply_to": {"type": "string"},
        },
        "required": ["to", "body"],
    }),
    # `framework_handoff` 与 `framework_interrupt` 不在（这张表里没有它们），而
    # `agent_loop.SHAPES` 里两个都在、提示词也按形状名教模型写它们（手稿是"交接落行"的
    # 唯一入口）。于是"`SHAPES` 减去 `tool` 全都广告成函数"这条纪律有一条裂缝：
    # 原生路上写 `framework_handoff` 只会拿到"模型调用了一个没广告过的函数"。
    # 两处一起补（`draft/108` CS-17）：这一张表 + `to_shape` 的通用支
    # （它本来就能把任意 `{形状: 载荷}` 翻过去，`handoff` / `interrupt` 不需要特例）。
    ("framework_handoff", "handoff", {
        "type": "object",
        "properties": {
            "to": {"type": "string",
                   "description": ("交给谁：名册名（如 D1）/ 绝对编号（如 t-000123）/ "
                                   "角色名，或主控 M 的本号；广播 `ALL` 已退场"
                                   "（会被受控拒绝 `broadcast_retired`）")},
            "summary": {"type": "string",
                        "description": "一句话：它就是留言里那句 `[手稿 NNNN] <summary>`"},
            "body": {"type": "string",
                     "description": "markdown 正文：做了什么 / 依据（实验号、文献号、手稿号）/ "
                                    "要对方做什么 / 我卡在哪"},
            "refs": {"type": "array", "items": {"type": "string"},
                     "description": "引用到的编号（stmt:/exp:/lit:/rel:/q:/c: 或手稿号）—— 会被逐条核"},
            "revises": {"type": "string",
                        "description": "可选：要订正的那一号手稿（旧行保留，不覆盖）"},
            "why": {"type": "string", "description": "可选：为什么写这一份"},
        },
        # 与 `agent_loop._decode_shape` 的 handoff 那一支同源：这三样缺一样就当场拒
        # （空手稿是"我交接了"的假证据）。
        "required": ["to", "summary", "body"],
    }),
    # S1k-4（业主 T22 的名册口径）：两个新形状的原生广告面。
    # 与 `agent_loop._do_roster` / `_do_retire` 的接受面同源：`of` 缺省 = 自己；
    # `retire` 只要一个名册名（父决定退役，判定与执行在秘书那一侧）。
    ("framework_roster", "roster", {
        "type": "object",
        "properties": {
            "of": {"type": "string",
                   "description": "缺省 = 自己的名册；也可写我名下某个子代理的名册名"},
            # S-H（裁定 14）的"全树"那一档：原生工具面没有这一格，
            # 于是模型在原生调用那条路上结构上给不出它（提示词里却写着）——
            # 与解码器那一侧的漏字段是同一件事的两半，两处一起补（`draft/105` A9）。
            # 不写 `enum`：取值合法性由读侧当面拒绝（与文本那条路同一套口径），
            # 不在这里多一道只在原生路上生效的闸。
            "scope": {"type": "string",
                      "description": "写 descendants 就给全树（每一行带 parent 与 depth）；"
                                     "缺省 = 只看下一层"},
        },
        "required": [],
    }),
    ("framework_retire", "retire", {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "名册名（如 D1）—— 父决定退役"},
        },
        "required": ["name"],
    }),
    # `interrupt` 与 `retire` 同一条指称纪律（S-H 裁定 14）：只说名册名。它停的是
    # "某一个子代理当前那一轮"，不是全局叫停（`conductor.stop` 才是）。
    ("framework_interrupt", "interrupt", {
        "type": "object",
        "properties": {
            "name": {"type": "string",
                     "description": "名册名（如 D1）—— 停它当前那一轮，不是全局叫停"},
        },
        "required": ["name"],
    }),
    ("framework_final", "final", {
        "type": "object",
        "properties": {
            "final": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            # `notify` 是"收工手稿"那一栏（`agent_prompts` §7）：它只活在提示词里，
            # 不在广告面上 ⇒ 原生工具面下模型结构上给不出这一栏。见
            # `NOTIFY_JSON_SCHEMA` 上面那段（含"为什么 required 里没有它"）。
            "notify": NOTIFY_JSON_SCHEMA,
            # `blocked`（"我在等上级指导"的收工声明）与 `notify` 是同一条纪律的两半：
            # 文本那条路由 `_decode_shape` 带过 `{"final": …, "blocked": {…}}`，
            # 而原生面既没广告它、`to_shape` 又把它静默丢掉 ⇒ 模型以为声明了、
            # 父那边 `subtree_blocked` 读出来仍是没有（`draft/108` CS-17）。
            # 这里只做广告 + 透传，不在传输层判必填：`why` / `needs` 齐不齐由
            # `AgentLoop._note_blocked_declaration` 判并给读数 —— 把它列进 `required`
            # 会先拒掉一次"合法的收工"，正是 `NOTIFY_JSON_SCHEMA` 上面记的那条教训。
            "blocked": {
                "type": "object",
                "properties": {
                    "what": {"type": "string", "description": "哪一件活卡住了"},
                    "why": {"type": "string",
                            "description": "被什么卡住（与 needs 都必填，否则这一笔不落痕）"},
                    "needs": {"type": "string",
                              "description": "请上级定什么（与 why 都必填）"},
                },
                "description": ("只有『等上级指导实施细则』这一档才写它（职责之外那一档不写）："
                                "`why` 与 `needs` 都非空才落痕"),
            },
        },
        "required": ["final"],
    }),
)


def _sanitize(name: str) -> str:
    """工具名 → 函数名。

    为什么必须换名：OpenAI 兼容接口的 function name 只允许 `[A-Za-z0-9_-]`，
    而本框架的工具名带点（`fs.read` / `table.create`）—— 直接送会被上游拒。
    换名是可逆的：`ToolFace.names` 把广告名映回真名，模型看到的只是另一个写法。
    """
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(name))


@dataclass(frozen=True)
class ToolFace:
    """这一趟广告给模型的函数面（角色自己的工具 + 循环的非工具形状）。

    `sha256` 是这份面的摘要，随每次调用落进审计记录 —— 要求与 `prompt_sha256` 同级：
    "这一趟广告了哪份工具面"必须是可复核的事实（工具面变了而没有任何读数变，
    正是本项目最忌的那种静默漂移）。
    """

    functions: tuple[dict[str, Any], ...]
    names: Mapping[str, str]
    sha256: str

    def _resolve(self, raw_name: str) -> str | None:
        """一条调用名 ⇒ 这一趟名字表里的键；认不出返回 `None`。

        ## 为什么两种写法都要认（`draft/152` 之二，真机读数）

        广告出去的是归一化名：`names` 的键只有下划线写法（`fs_read` 这样的函数名
        才符合 OpenAI 兼容接口的字符集），而提示词、拒信、文档、工具面里用的都是
        带点的真名（`fs.read` / `table.get`）。模型两种名字都见过，于是它写点号名
        是必然会发生的事 —— 只按原样查 `names`，点号名一律查不到，
        落成"模型调用了一个没广告过的函数"，再被计进 `judge_bad_json`。真机三趟
        16 条 `judge_bad_json` 里 8 条就是这个形态（`table.get`、`review.record_finding`
        …），而它们没有一条是坏 JSON。

        于是查找按三步走：先原样（模型写的就是广告名，最常见），再按 `_sanitize`
        归一化一次（模型写的是真名），最后交给调用方列候选。两步都查不到才算
        "真的不在这一趟的面上" —— 那一条仍然拒（负控在测试里）。

        反向不会混淆：两件不同的真名归一化成同一个广告名时，`build_tool_face`
        已经用 `ValueError` 拒掉整份面（广告名撞车），所以"归一化查一次"命中的
        至多一件工具，不会把两个工具混成一个。

        为什么不是"由调用方自己写两遍 get"：`to_shape`（解析）与 `action_name`
        （读数）读的是同一张表，两处各写一套回退，早晚会在其中一处漏掉点号写法，
        而漏掉的那一半正是"模型写对了、框架说没有"这个形态。
        """
        name = str(raw_name or "")
        target = self.names.get(name)
        if target is not None:
            return target
        alias = _sanitize(name)
        if alias != name:
            return self.names.get(alias)
        return None

    def candidates(self, raw_name: str) -> list[str]:
        """认不出的名字的并列候选（真名写法；判据只有一份，转发到工具层那一处）。

        为什么给候选而不是自动改写：选哪一个是一次判断（它是模型想做的事），
        框架替它挑一个等于替它表态。真机 `unknown_tool` 那 7 条里就有 4 条照着
        错误的候选去改会更错，所以这里只列、不改。

        为什么候选是真名（带点）：提示词与其它拒信都用真名，模型拿到的名字要与它
        在文档里看到的那一套一致。惰性导入 `tools.base` 是刻意的 —— 它在调用期
        才生效，避免本模块与工具层在 import 期互相牵扯。
        """
        from .tools.base import candidate_tool_names

        pool = sorted({(value.split(":", 1)[1] if value.startswith("tool:") else value)
                       for value in self.names.values()})
        return candidate_tool_names(str(raw_name or ""), pool)

    @staticmethod
    def raw_args_text(call: Mapping[str, Any]) -> str:
        """一条原生调用的 `arguments` 原文（不是回复正文）。

        为什么需要它：`judge_bad_args` 坏的是
        `arguments` 那段字符串，而 `SeamCall.text` 装的是"回复正文"——原生调用时它是
        空的。循环把 `call.text` 交给 `_dump_invalid_reply`，于是 `out/invalid/*.txt`
        全是 0 字节：报错给了列号（例如 char 6691），证据却被丢掉了。
        这条口径只做一件事：把那段 arguments 还原成跟模型写的一样的字符串
        （字符串原样、其它形态按 JSON 序列化），供留档与 detail 使用。
        """
        raw = call.get("arguments")
        if isinstance(raw, str):
            return raw
        return json.dumps(raw if raw is not None else {}, ensure_ascii=False, default=str)

    def to_shape(self, call: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
        """把一条原生工具调用翻成循环协议的形状。返回 `(data, problem, detail)`。

        三态纪律：翻不出来时 `data is None` 且 `problem` 非空 —— 绝不返回一个
        "看起来像调用"的空对象（那会让下一步去执行一件模型没说过的事）。
        """
        raw_name = str(call.get("name") or "")
        target = self._resolve(raw_name)
        if target is None:
            cands = self.candidates(raw_name)
            # 这一档的码从 `judge_bad_json` 改成 `judge_unknown_tool`。
            # 它从来不是坏 JSON（模型给的结构完全合法，只是名字不在这份广告面上），
            # 而 `judge_bad_json` 那一档的纠正话术是"只回一行 JSON" —— 对着这条错说那句话
            # 等于把模型领向更错的方向（真机三趟 16 条 `judge_bad_json` 里 8 条是这个形态）。
            # 文本协议下同一件事记 `unknown_tool`（`tools/base.py` 那一档），两个码现在
            # 归同一个错误类目（`errorstats.CODE_TABLE`），`judge_bad_json` 只留给真的坏 JSON。
            return None, "judge_unknown_tool", (
                f"模型调用了一个没广告过的函数 {raw_name!r}（这一趟广告的是 "
                f"{sorted(self.names)[:6]}…；并列候选（{len(cands)} 个）：{cands}"
                " —— 机器只列候选、不自动改写）")
        text = self.raw_args_text(call)
        try:
            args = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError as exc:
            # 与 DSH 的 `parseArguments` / `ToolArgsError` 同一条纪律：参数坏不是
            # "认不出的形状" —— 工具名已经从结构化字段拿到了，所以这句纠正能点名
            # "是哪个函数的参数坏了"，比"键名不对"精确得多。
            #
            # 原文头从 200 提到 2000（真机 82 · B-2）：坏点落在 char 6691 那种深处，
            # 200 字截到的只是开头，读的人依然说不出"哪里坏"。代价是有界的（2000 字）。
            return None, "judge_bad_args", (
                f"函数 {raw_name} 的参数不是合法 JSON（{exc}）；原文前 2000 字：{text[:2000]}")
        if not isinstance(args, Mapping):
            return None, "judge_bad_args", (
                f"函数 {raw_name} 的参数必须是一个 JSON 对象，收到 {type(args).__name__}；"
                f"原文前 2000 字：{text[:2000]}")
        why = str(args.pop("why", "") or "")
        if target.startswith("tool:"):
            return {"tool": target.split(":", 1)[1], "args": dict(args), "why": why}, "", ""
        if target == "final":
            payload = dict(args)
            payload.setdefault("evidence", [])
            out: dict[str, Any] = {"final": payload.get("final") or "",
                                   "evidence": payload.get("evidence") or []}
            # `notify` 原样透传（一个字节都不改），与文本回落那条路
            # （`agent_loop._decode_shape` 的 `if data.get("notify") is not None`）同一口径：
            # 校验统一在 `notify_reading` / `notify_shape_problem` 里做（那一层才知道角色、
            # 才知道"没填"与"填错"该怎么记读数）。
            #
            # 缺省时不造一个空 dict：那会让"模型没填"与"框架替它填了一份空表"在
            # 会话记录里长得一样 —— `agent_loop._with_notify` 的 docstring 记的是同一条纪律。
            # 形状不对的 `notify` 也照带（读数是 `notify_problem`，不是在这里静默丢掉）。
            if "notify" in args:
                out["notify"] = args["notify"]
            # `blocked` 同一条纪律（`draft/108` CS-17）：给了就原样带过，没给就不造空 dict ——
            # 这一格若被静默丢掉，于是"模型声明卡住了"与"没人声明"在盘上长得一样。
            # 校验与落痕仍归 `AgentLoop._note_blocked_declaration`（含它那两句读数）。
            if "blocked" in args:
                out["blocked"] = args["blocked"]
            return out, "", ""
        if target == "note":
            return {"note": {"text": str(args.get("text") or "")}}, "", ""
        payload = dict(args)
        if why:
            payload.setdefault("why", why)
        return {target: payload}, "", ""

    def action_name(self, call: Mapping[str, Any]) -> str:
        """一条原生调用指向的动作名（广告名映回真名；映不回来就照抄广告名）。

        只服务读数（D-35 方案 B）：一步给了多条调用、只执行第一条时，被丢的那几条
        要能在 step 的读数里被点名 —— 而模型给的是广告名（`fs_read`），盘上该记的是
        真名（`fs.read`），否则"丢了哪个动作"这件事核对不上工具面。
        它不解析参数、不判合法性：那件事只有 `to_shape` 一处做。

        名字查找走 `_resolve`（认点号与下划线两种写法）：与 `to_shape` 是同一处口径，
        否则会出现"这一步解析得了、被丢的那条却映不回真名"的分家。
        """
        raw = str(call.get("name") or "")
        target = self._resolve(raw)
        if target is None:
            return raw or "(未命名)"
        return target.split(":", 1)[1] if target.startswith("tool:") else target


def build_tool_face(role: str, registry: Any) -> ToolFace:
    """按角色的工具面 + 循环的非工具形状造一份函数面。

    `registry` 必须与真正执行调用的那个注册表是同一个（与提示词那条纪律相同：
    广告一份、执行另一份，就会出现"模型按广告调、框架说没这个工具"）。
    """
    spec_fn = getattr(registry, "for_role", None)
    specs = list(spec_fn(role)) if callable(spec_fn) else []
    functions: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for spec in sorted(specs, key=lambda s: str(getattr(s, "name", ""))):
        real = str(getattr(spec, "name", "") or "")
        if not real:
            continue
        san = _sanitize(real)
        if san in names:
            raise ValueError(
                f"广告名撞车：{real!r} 与另一件工具都归一化成 {san!r} —— "
                "宁可在这里炸，也不要让模型按一个含糊的名字去调工具")
        names[san] = f"tool:{real}"
        params = dict(getattr(spec, "params", None) or {})
        props = dict(params.get("properties") or {})
        # `why` 是可选的（原生调用里没有它的位置），但它在审计与提示词里都有用 ——
        # 所以把它加成每个函数的一个可选属性，而不是丢掉。
        props.setdefault("why", {"type": "string",
                                 "description": "一句话说明为什么这一步（可选）"})
        functions.append({"type": "function", "function": {
            "name": san,
            # 三段（能力 / 场景 / 例 + 代码）由 `toolface.face_text` 一处渲染，
            # 与提示词那一侧（`agent_prompts.tools_lines`）逐字同源。
            "description": _face_text(spec) or real,
            "parameters": {**params, "type": "object", "properties": props},
        }})
    for san, target, schema in META_FUNCTIONS:
        names[san] = target
        functions.append({"type": "function", "function": {
            "name": san,
            "description": f"循环形状 {target}（不是工具：它由框架执行）",
            "parameters": schema,
        }})
    digest = _sha(json.dumps(functions, ensure_ascii=False, sort_keys=True, default=str))
    return ToolFace(functions=tuple(functions), names=dict(names), sha256=digest)




def _json_shape_hint(text: str) -> str:
    """坏 JSON 的一句话诊断：`}` 多了或少了是最常见的那两种（真机实测占多数）。

    做法是"试探性修补一次再解析"：能修好，就说明模型犯的正是这个错 ——
    于是那句纠正消息可以点名它，而不是泛泛地说"不是 JSON 对象"。
    注意它只用于诊断：修补后的结果不会被当成模型的原意使用
    （那会让"多一个括号"这种错被静默接受）。

    追加一档：内联 XML 形态的工具调用（DeepSeek 的 `｜｜DSML｜｜` 标记）。
    真机 `projects/paper-rewrite-78c` 的 `B#7`：回复尾部逐字是
    `</｜｜DSML｜｜ parameter> … </｜｜DSML｜｜ calls>` —— 它根本不是 JSON，修补救不回来，
    但对模型说清"你写成了 XML，只接受一行 JSON"能让下一回合改对（泛泛的"不是 JSON"
    上一次就没让它改过来）。
    """
    from .llm import parse_llm_json

    t = str(text or "").strip()
    if "｜｜DSML｜｜" in t or "DSML" in t or "</" in t and "invoke>" in t:
        return "（诊断：这条回复是 XML 形态的工具调用；框架只接受一行 JSON —— 参照骨架重写）"
    for cand, why in ((t[:-1], "末尾多了一个 `}`"), (t + "}", "末尾少了一个 `}`")):
        if not cand or cand == t:
            continue
        try:
            parse_llm_json(cand)
        except Exception:
            continue
        return f"（诊断：{why}）"
    return ""


def selftest() -> int:
    """自检：没接线、预算、坏 JSON 三条路都落成正确的码，且审计记录真的落档。"""
    import tempfile

    problems: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        seam = LlmSeam(role="D", session_root=root, gateway=None)
        if seam.wired:
            problems.append("没有 gateway 却报告已接线")
        call = seam.ask("你好", system="sys", task_id="t-0001")
        if call.problem != "judge_not_wired" or not call.not_checked:
            problems.append(f"没接线没有落成 judge_not_wired：{call.problem!r}")
        events, bad = SS.read_session(root, sid=SS.session_id())
        if bad:
            problems.append(f"会话记录读回有问题：{bad}")
        if not any(e.get("kind") == "llm_call" for e in events):
            problems.append("没接线的调用没有落档")

        # 预算守卫：在发起请求之前就拒（用一个会抛的 gateway 证明它根本没被调用）
        class Boom:
            spec = type("S", (), {"model": "boom"})()

            def complete(self, *a: Any, **kw: Any) -> Any:
                """自检替身：被调用就说明预算守卫失效了。"""
                raise AssertionError("预算耗尽时不该发起请求")

        seam2 = LlmSeam(role="D", session_root=root, gateway=Boom(), usd_budget=0.0)
        seam2.spend.usd = 0.0
        call2 = seam2.ask("你好")
        if call2.problem != "judge_over_budget":
            problems.append(f"预算守卫没有生效：{call2.problem!r}")

        # 注入负控：坏 JSON ⇒ judge_bad_json（不许当空对象继续）
        class Garbage:
            spec = type("S", (), {"model": "garbage"})()

            def complete(self, *a: Any, **kw: Any) -> Any:
                """自检替身：永远返回一句不是 JSON 的文本。"""
                return type("R", (), {"ok": True, "text": "这不是 JSON", "tokens_in": 1,
                                      "tokens_out": 1, "error_detail": ""})()

        seam3 = LlmSeam(role="D", session_root=root, gateway=Garbage(), price=(0.0, 0.0))
        data, call3 = seam3.ask_json("给 JSON")
        if data is not None or call3.problem != "judge_bad_json":
            problems.append(f"坏 JSON 没有被归类：{call3.problem!r}")

        # 注入负控：好 JSON 必须被解析出来（判据不是真空的）
        class Good:
            spec = type("S", (), {"model": "good"})()

            def complete(self, *a: Any, **kw: Any) -> Any:
                """自检替身：返回一个合法 JSON（判据不是真空的）。"""
                return type("R", (), {"ok": True, "text": '{"tool": "graph.stats", "args": {}}',
                                      "tokens_in": 2, "tokens_out": 3, "error_detail": ""})()

        seam4 = LlmSeam(role="D", session_root=root, gateway=Good(), price=(0.0, 0.0))
        data4, call4 = seam4.ask_json("给 JSON")
        if data4 != {"tool": "graph.stats", "args": {}} or not call4.ok:
            problems.append(f"好 JSON 没被解析：{data4!r} / {call4.problem!r}")
        if call4.prompt_sha256 == "" or call4.prompt_version != PROMPT_VERSION:
            problems.append("审计字段缺失（哈希或版本）")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（没接线 / 预算 / 坏 JSON / 好 JSON 四条路，审计落档）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())
