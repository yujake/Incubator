"""逐工具超时：协作式截止 + 一张表（业主 2026-10-10 裁定 13甲 / 12-D / 12-E / 12-G）。

## 搬的是什么（DSH 的原文口径）

- `dsh-timeout/lib/index.js:12-25` 的 `TimeoutReason`（能力自己的 code + 到点的那口钟）、
  `:57-73` 的 `deadline()`、`:134-138` 的 `timeoutOf(x, code)` 作用域判据；
- `dsh-tool-call-timeout-policy/lib/index.js:80` 的 `TOOL_TIMEOUT`（既作内部超时分类码、
  又作结构化错误码）、`:93-109` 的替换结果（模型可见文本 `Error: tool call timed out after
  <ms>ms`、`error.info.name = "ToolTimeoutError"`）、`:115-134` 的包装器（没声明就原样放行；
  只有我们自己的那口钟响过才替换结果）；
- `:29`/`:44` 的注册期校验文案（`must be a positive finite number`）。

## 三处与 DSH 的差异（都是我方的形态，逐条写明理由）

1. 机制是 ContextVar 协作式，不是 AbortSignal（裁定 12-D 逐字「甲，不机械杀进程」）：
   我们的 `ToolRegistry.call` 是同步的（`tools/base.py`），没有 await 点可以观察计时器
   ⇒ 截止靠一个 ContextVar 发布，处理函数在检查点调 :func:`raise_if_timed_out`。
   因此没有人替工具停下它自己：到点了而工具没看信号 ⇒ 本模块不替换结果，
   只在侧信道落一条读数（`deadline_passed_unobserved`）。这是三态纪律：
   「工具确实停住了」与「到点了但工具没看」必须分得开 —— 假装拦住了比不拦更糟。
2. 表住在新模块里，不碰禁改区（裁定 12-G「按建议」= 乙先落）：`ToolSpec` 不加
   `timeout_ms` 字段、`tools/base.py` 一行不改（`tools/base.py` 在 `.noai-paths` 里，
   改它要人写或人逐行走查 + 2 名 reviewer）。等机制验过之后再由人裁要不要把
   `timeout_ms` 正式写进 `ToolSpec`。
3. 单位是秒：全仓的 `timeout_sec` 都是秒，DSH 是毫秒 ⇒ 只在
   :func:`lookup`（秒 → 毫秒）这一处边界上换算，别的地方一律毫秒（`TimeoutReason.timeout_ms`
   与模型可见文本都照 DSH 用毫秒）。

## 谁被声明了（第一批：检索 / 下载 / 起子进程）

表是真身（:data:`TIMEOUT_TABLE`），逐条带自己的 code（DSH 的纪律：不许合并成一个哨兵）
与 `checkpoint` 一格 —— 那一格说的是"这个处理函数现在到底会不会看信号"：

- `handler`：处理函数里有协作式检查点（真的会停在自己的检查点上）；
- `pending`：表里声明了、处理函数还没有检查点（它在禁改区里，要人加）⇒ 到点了
  只会落 `deadline_passed_unobserved`，不会被替换成超时结果。

`pending` 是如实登记，不是"以后再说"：`tests/test_the_tool_timeouts_are_cooperative.py`
会把这个名单与"注册表里 `external in (egress, exec)` 的那些工具"对齐 —— 少一个都要有人看见。
"""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass
from typing import Any, Mapping

#: DSH 逐字搬来的码（`dsh-tool-call-timeout-policy/lib/index.js:80`）：它同时是内部超时
#: 分类码与结构化错误码 —— 两处同一个字符串，重试/沙箱/回放才能按它路由。
TOOL_TIMEOUT = "TOOL_TIMEOUT"

#: DSH 逐字搬来的上限（`dsh-timeout/lib/index.js:27`）：Node 不把它夹到 1 毫秒的最大延迟。
MAX_TIMER_DELAY_MS = 2147483647

#: 结构化错误里那个名字（DSH 的 `error.info.name`）。
TIMEOUT_ERROR_NAME = "ToolTimeoutError"

#: 侧信道读数的两种状态（不许折成一个布尔）：工具真的停在检查点上 / 到点了而工具没看。
OBSERVED = "observed"
UNOBSERVED = "deadline_passed_unobserved"

#: 一秒多少毫秒（唯一的换算边界，见模块 docstring 第 3 条）。
_MS_PER_SEC = 1000.0


def assert_timer_delay(timeout_ms: float, name: str = "timeoutMs") -> None:
    """DSH `dsh-timeout/lib/index.js:28-30` 逐字搬来的注册期/装表期校验。"""
    if not isinstance(timeout_ms, (int, float)) or timeout_ms != timeout_ms:
        raise ValueError(f"{name} must be a positive finite number no greater than "
                         f"{MAX_TIMER_DELAY_MS}")
    if timeout_ms <= 0 or timeout_ms > MAX_TIMER_DELAY_MS:
        raise ValueError(f"{name} must be a positive finite number no greater than "
                         f"{MAX_TIMER_DELAY_MS}")


def clamp_timeout(requested: float | None, default: float, maximum: float,
                  name: str = "timeoutMs") -> float:
    """DSH `:43-46` 逐字搬来：调用方给的那一份必须是正的有限数（0 不是"关掉超时"）。"""
    if requested is not None:
        if not isinstance(requested, (int, float)) or requested != requested or requested <= 0:
            raise ValueError(f"{name} must be a positive finite number")
    return min(requested if requested is not None else default, maximum)


class TimeoutReason(Exception):
    """DSH `:12-25` 的 `TimeoutReason`：能力自己的 code + 到点的那口钟（毫秒）。"""

    def __init__(self, code: str, timeout_ms: float) -> None:
        super().__init__(f"{code} after {timeout_ms}ms")
        self.code = str(code)
        self.timeout_ms = timeout_ms
        self.name = "TimeoutReason"


class ToolTimedOut(Exception):
    """协作式检查点抛出来的东西：这一跳是我们自己的那口钟响了。"""

    def __init__(self, reason: TimeoutReason) -> None:
        super().__init__(str(reason))
        self.reason = reason


def timeout_of(carrier: Any, code: str | None = None) -> TimeoutReason | None:
    """DSH `:134-138` 的判据：只认自己那个 code 的 `TimeoutReason`。

    为什么这条判据必须搬（逐字理由见 `:73-80`）：嵌套时外层包装器的钟先响 ⇒ 内层要把它
    读成普通的上游取消并原样透传下游结果，而不是误报成"我超时了"。
    传 `code=None` 时才认任何 code（那是"有没有超时"的粗问，不是本包装器自己的问法）。
    """
    reason = getattr(carrier, "reason", None)
    if not isinstance(reason, TimeoutReason):
        return None
    if code is None or reason.code == code:
        return reason
    return None


@dataclass(frozen=True)
class TimeoutDecl:
    """一个工具的限时声明：秒数 + 它自己的 code + 检查点状态。"""

    seconds: float
    code: str
    checkpoint: str
    why: str

    @property
    def timeout_ms(self) -> float:
        return self.seconds * _MS_PER_SEC


#: 逐工具的限时表（真身）。第一批 = 检索 / 下载 / 起子进程那十件
#: （`external in ("egress", "exec")`，实测清单见 `tests/test_the_tool_timeouts_are_cooperative.py`）。
#:
#: 为什么只有这几件（DSH 同款口径）：`dsh-tool-web` 声明了 30s，而随附的
#: `bash`/`read`/`write`/`edit` 有意不声明（`README.md:123`）⇒ "无统一默认"是本条裁定的
#: 一部分，不是遗漏。本地读写是毫秒级的事，给它加钟只会让读数里多一格噪声。
TIMEOUT_TABLE: dict[str, TimeoutDecl] = {
    # ---- 检索（egress）：一次提问要打多个源，最坏是"每个源各自超时"的叠加。
    "search.literature": TimeoutDecl(
        120.0, "SEARCH_TIMEOUT", "handler",
        "一次检索要打多个源，慢源会把一步拖到分钟级；检查点放在每个源那一次调用之前"),
    "search.providers": TimeoutDecl(
        30.0, "PROVIDERS_TIMEOUT", "pending",
        "它只是读一张已知 provider 的清单，但探测会走网络（`_probe_network_provider`）"),
    "search.walk_citations": TimeoutDecl(
        60.0, "WALK_TIMEOUT", "pending",
        "引文走查发 1–3 次 OpenAlex 请求（取源记录 + 最多两批解析，每批 `CITATION_BATCH=25` 个 id），"
        "每次自带重试与限速 ⇒ 给 60 秒而不是 120 秒：它**不像 `search.literature` 那样一次打多个源**。"
        "检查点尚未接在 handler 里（与 `search.providers` / `search.download` 同一档，所以写 `pending`）"),
    "search.download": TimeoutDecl(
        180.0, "DOWNLOAD_TIMEOUT", "pending",
        "下 PDF 是这一层最慢的一件（分钟级是常态，所以给三分钟而不是三十秒）"),
    "ocr.run": TimeoutDecl(
        300.0, "OCR_TIMEOUT", "pending",
        "首次构造 Reader 要下 ~100MB 模型（R010-b 的已知盲区）；给它五分钟"),
    # ---- 起子进程（exec）：这些活的时长由被调的编译器/检查器决定。
    "doc.paper_compile": TimeoutDecl(
        1800.0, "COMPILE_TIMEOUT", "pending",
        "框架内置的 LaTeX 编译（两遍 pdflatex）—— 长稿子分钟级起步，给它半小时；"
        "读者从 `draft/117` 起：旧路的 render/build/anchor 三条已退场"),
    # `verify.*` 两件在禁改区 `tools/verify_tools.py` 里 ⇒ 检查点只能由人加（如实标 pending）。
    "verify.check_formal": TimeoutDecl(
        600.0, "VERIFY_TIMEOUT", "pending",
        "Lean/Coq 检查是分钟级起步；handler 在禁改区 verify_tools.py ⇒ 检查点要人加"),
    "verify.run_experiment": TimeoutDecl(
        600.0, "EXPERIMENT_TIMEOUT", "pending",
        "跑一段实验脚本；handler 在禁改区 verify_tools.py ⇒ 检查点要人加"),
}


def lookup(name: str) -> TimeoutDecl | None:
    """查一个工具的限时声明（`None` = 没有声明 ⇒ 原样放行，照 DSH 的 `:124`）。

    三态：`None` 是"没有声明"这一档，它与"声明了 0 秒"是两件事 ——
    后者在装表期就会被 :func:`assert_timer_delay` 拒掉（0 不是"关掉超时"的公开哨兵）。
    """
    return TIMEOUT_TABLE.get(str(name))


def declared_seconds(name: str, *, overrides: Mapping[str, Any] | None = None
                     ) -> tuple[float | None, str]:
    """有效限时（秒）与它的状态：`("declared"|"undeclared"|"unknown", 秒或 None)`。

    为什么要有 `unknown` 这一档（施工单的三态要求）：调用方给了一份 overrides
    而那份读不出来（不是映射 / 键存在但值不是数）⇒ 结论是"限时读不到"，
    而它不许被当成 0（0 会变成"立刻超时"，那是把"没查成"折成"查过了"的反面）。
    """
    if overrides is not None:
        if not isinstance(overrides, Mapping):
            return None, "unknown"
        if name in overrides:
            raw = overrides[name]
            try:
                val = float(raw)
            except (TypeError, ValueError):
                return None, "unknown"
            if val != val or val <= 0:
                return None, "unknown"
            return val, "declared"
    decl = lookup(name)
    if decl is None:
        return None, "undeclared"
    return decl.seconds, "declared"


# ---------------------------------------------------------------- 协作式截止（ContextVar）

#: 当前执行上下文里的截止作用域（嵌套时内层在最上面 —— 与 DSH 的包装器套娃同形）。
_CURRENT_SCOPE: contextvars.ContextVar["DeadlineScope | None"] = contextvars.ContextVar(
    "agentflow_tool_deadline", default=None
)


@dataclass
class DeadlineScope:
    """一次工具调用的那口钟：自己的 code、到点时刻、以及"工具看没看信号"。"""

    name: str
    code: str
    timeout_ms: float
    started: float
    observed: bool = False

    @property
    def deadline(self) -> float:
        return self.started + self.timeout_ms / _MS_PER_SEC

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self.deadline

    def elapsed_ms(self) -> float:
        return (time.monotonic() - self.started) * _MS_PER_SEC

    def raise_if_timed_out(self) -> None:
        """协作式检查点：到点了就抛 `ToolTimedOut`（并记下"工具看了信号"）。"""
        if self.expired:
            self.observed = True
            raise ToolTimedOut(TimeoutReason(self.code, self.timeout_ms))

    def mark_observed(self) -> None:
        """不带异常的观察（处理函数只想记一笔"我看了、还没到点"）。"""
        self.observed = True


@dataclass
class DeadlineRun:
    """一次 `with tool_deadline(name)` 的读数（结果之外的那一半）。

    `state` 三值：`OBSERVED`（工具真的停在检查点上）/ `UNOBSERVED`（到点了而工具没看）/
    空串（这口钟没响，一切照旧）。
    """

    name: str
    declared: bool
    state: str
    code: str
    timeout_ms: float
    elapsed_ms: float

    def note(self) -> str:
        """侧信道那一条读数的正文（不进模型可见的结果，见裁定 12-E）。"""
        if self.state == OBSERVED:
            return (f"{self.name} 停在协作式截止上：{self.code} after {self.timeout_ms:g}ms"
                    f"（实际用了 {self.elapsed_ms:.0f}ms）")
        if self.state == UNOBSERVED:
            return (f"{self.name} 到点了但没有看截止（{self.code} after "
                    f"{self.timeout_ms:g}ms，实际用了 {self.elapsed_ms:.0f}ms）："
                    "这一件还没接检查点 ⇒ 结果照收，如实记下'没拦住'")
        return ""


class _Deadline:
    """`with tool_deadline(name) as scope:` 的上下文管理器（`as` 拿到的就是它自己）。

    为什么 `as` 给的是这个对象而不是一份读数快照：读数（`state` / `elapsed_ms` /
    `observed_timed_out`）只有在离开 `with` 之后才定下来 —— 给快照会让
    `with ... as r: ...` 之后的 `r.state` 永远停在 `""`（"没到点"），
    而那个空串会被读成"这口钟没响过"。所以 `as` 绑定管理器本身，读数走属性现读。
    """

    def __init__(self, name: str, *, overrides: Mapping[str, Any] | None = None) -> None:
        self.name = str(name)
        self.seconds, self.declared_state = declared_seconds(self.name, overrides=overrides)
        self.scope: DeadlineScope | None = None
        self.run: DeadlineRun | None = None
        self._token: Any = None
        self._outer_expired = False

    # ---- 读数（现读，不是快照）
    @property
    def state(self) -> str:
        return self.run.state if self.run is not None else ""

    @property
    def code(self) -> str:
        return self.run.code if self.run is not None else ""

    @property
    def timeout_ms(self) -> float:
        return self.run.timeout_ms if self.run is not None else 0.0

    @property
    def elapsed_ms(self) -> float:
        return self.run.elapsed_ms if self.run is not None else 0.0

    def note(self) -> str:
        return self.run.note() if self.run is not None else ""

    def __enter__(self) -> "_Deadline":
        decl = lookup(self.name)
        if self.seconds is None:
            # 没声明（或读不到）⇒ 不装钟，原样放行（DSH `:124` 的 `return next()`）。
            # 读不到的那一档在这里也不装：装一个猜出来的钟比不装更糟。
            self.run = DeadlineRun(self.name, False, "", "", 0.0, 0.0)
            return self
        timeout_ms = self.seconds * _MS_PER_SEC
        assert_timer_delay(timeout_ms, f'tool "{self.name}" timeoutMs')
        outer = _CURRENT_SCOPE.get()
        # 照 `timeoutOf` 的作用域：外层钟已经响过 ⇒ 这一跳读作上游取消，
        # 内层不许把自己的钟当成"我的超时"（DSH `:73-80` 的逐字理由）。
        self._outer_expired = bool(outer is not None and outer.expired)
        code = decl.code if decl is not None else TOOL_TIMEOUT
        self.scope = DeadlineScope(self.name, code, timeout_ms, time.monotonic())
        self._token = _CURRENT_SCOPE.set(self.scope)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if self.scope is not None:
            _CURRENT_SCOPE.reset(self._token)
            state = ""
            # 照 `timeoutOf` 的作用域（DSH `:73-80`）：只有"抛出来的那个 reason 的 code
            # 就是我这一层的 code"才算我超时了；别人那口钟抛上来的读作普通异常。
            if (exc is not None and isinstance(exc, ToolTimedOut)
                    and exc.reason.code == self.scope.code):
                state = OBSERVED
            elif self.scope.expired and self.scope.observed:
                state = OBSERVED
            elif self.scope.expired:
                state = UNOBSERVED
            self.run = DeadlineRun(self.name, True, state, self.scope.code,
                                   self.scope.timeout_ms, self.scope.elapsed_ms())
        return False        # 异常继续往上走（调用方整段包在 try 里，会变成模型看得见的结果）

    @property
    def observed_timed_out(self) -> bool:
        """我们自己的那口钟响了、而且工具真的停住了 ⇒ 才替换结果（DSH `:130`）。"""
        if self.run is None or not self.run.declared:
            return False
        if self._outer_expired:
            return False        # 外层钟先响 ⇒ 上游取消，原样透传
        return self.run.state == OBSERVED


def tool_deadline(name: str, *, overrides: Mapping[str, Any] | None = None) -> _Deadline:
    """给一次工具调用装上一口钟（没声明就什么都不做）。

    调用方（`agent_loop` 调 `registry.call` 的那一处）用它的两个读数做两件事：
    `observed_timed_out` ⇒ 把结果换成 :func:`timeout_result`；`run.note()` ⇒ 落侧信道读数。
    """
    return _Deadline(name, overrides=overrides)


def current_scope() -> DeadlineScope | None:
    """当前执行上下文里的那口钟（不在工具调用里时是 `None`）。"""
    return _CURRENT_SCOPE.get()


def raise_if_timed_out() -> None:
    """处理函数在检查点调它（模块级形态，供没有实例的地方调用）。

    没有钟、或钟没响 ⇒ 什么都不做（不抛）：那说明这段代码跑在时限面之外，
    而"投递一个假信号"比"没有信号"更糟（与 `cancellation.raise_if_cancelled` 同一条纪律）。
    """
    scope = _CURRENT_SCOPE.get()
    if scope is not None:
        scope.raise_if_timed_out()


def timeout_result(name: str, code: str, timeout_ms: float, *,
                   outer_expired: bool = False) -> dict[str, Any]:
    """被替换掉的那个结果（逐字节相同：耗时只进侧信道 —— 裁定 12-E）。

    形状照 DSH `:93-109`：模型可见的 `error` 文本逐字是
    `Error: tool call timed out after <ms>ms`；结构化那一份带上同一个 `TOOL_TIMEOUT`
    与 `ToolTimeoutError`（重试/沙箱/回放按它路由）。

    为什么这里一个耗时数字都没有：`agent_loop._call_reading` 会把整条结果哈希进
    "原地打转"的连击键 ⇒ 结果里带上"这次等了多久"会让两次超时产生不同的读数，
    于是 `dead >= max_dead_loop` 永远不触发（模型可以无限循环在一个超时调用上）。
    耗时放 :meth:`DeadlineRun.note`（侧信道）。
    """
    message = f"tool call timed out after {timeout_ms:g}ms"
    meta: dict[str, Any] = {
        "timeout": True,
        "timeout_ms": timeout_ms,
        "error_code": TOOL_TIMEOUT,
        "error_name": TIMEOUT_ERROR_NAME,
        "capability_code": code,
    }
    if outer_expired:
        meta["outer_deadline_expired"] = True
    return {"tool": name, "ok": False, "error": f"Error: {message}", "meta": meta}


def table_reading() -> dict[str, Any]:
    """这张表的读数（判据与报告用；现算，不手抄）。

    三样：声明了几件 / 其中几件已经接了检查点 / 几件还挂着（`pending` 那一档）。
    `pending` 那一档必须列出来而不是只报一个数：只报数的话，"谁还挂着"要人去读源码。
    """
    rows = {name: decl.checkpoint for name, decl in TIMEOUT_TABLE.items()}
    return {
        "declared": sorted(rows),
        "with_checkpoint": sorted(n for n, c in rows.items() if c == "handler"),
        "pending": sorted(n for n, c in rows.items() if c != "handler"),
        "count": len(rows),
    }


def selftest() -> int:
    """自检：装表期校验、作用域判据、逐字节相同。返回 0 表示全过。"""
    bad: list[str] = []
    for name, decl in TIMEOUT_TABLE.items():
        try:
            assert_timer_delay(decl.timeout_ms, f'tool "{name}" timeoutMs')
        except ValueError as exc:
            bad.append(f"{name}: {exc}")
        if not decl.code:
            bad.append(f"{name}: 没有 code（DSH 的纪律：每个能力有自己的 code）")
    a = timeout_result("search.literature", "SEARCH_TIMEOUT", 120000.0)
    b = timeout_result("search.literature", "SEARCH_TIMEOUT", 120000.0)
    if a != b:
        bad.append("两次超时的结果不一致（违反裁定 12-E）")
    if timeout_of(type("C", (), {"reason": TimeoutReason("OTHER", 1.0)})(), "SEARCH_TIMEOUT"):
        bad.append("timeoutOf 把别人的 code 认成了自己的")
    for line in bad:
        print(f"[timeout] {line}")
    return 1 if bad else 0


if __name__ == "__main__":      # pragma: no cover —— 与全仓其它模块的 `__main__` 同形
    raise SystemExit(selftest())
