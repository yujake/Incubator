"""一步一条入口：接住 → 拆分 → 逐条执行（角色无关的公共层）。

## 这一层回答什么（业主裁定，逐字）

「multi_call 应该让系统自动整理拆分」；实现方式「智能体要做动作时系统先接住请求，拆分，
分条执行」。于是"这一步模型要求做什么"整包先接住（可能是 1 条，也可能是 4 条），
再拆成有序条目，交给循环逐条执行（每条走完整的准入 / 预算 / 记账），
最后汇总成一份读数回给模型。

## 为什么要有独立一层（而不是在"取第一条"那行加个循环）

改前（D-35 方案 B）的形态是：解析层取 `tool_call_list[0]`，其余丢弃，循环那边补一句
`warn` 点名被丢的那几条。真机读数（r34d / cube2 等三趟）共 76 个多调用步、被丢 107 条，
全部是只读（没有一条写或召唤）—— 也就是说那 107 条一个字节都没执行，而模型以为
它们生效了。把它修成"循环里再写一段多条怎么办"只会得到第二份判据：单条一条路、
多条另一条路，而两条路迟早分叉。所以拆分这件事只有一个落点：本模块。

## 角色无关（这是硬约束）

本层的代码里不许出现任何一个角色名（判据扫源码断言一个都没有）：准入差异由
既有的角色面（`tools/base.py`）与边表（`capabilities.ALLOWED_EDGES`）在层之下判。
层只认"形状 / 载荷 / 条目序号"这三样，因此十一个角色（A–H 加主控、验证者、形式化者）
走同一条路（判据 `tests/test_multi_call_is_split_and_executed.py` 对十一个角色各跑一遍）。

## 三态

- 整步被接住 = `checked`：`StepDispatch.items` 非空、`problem` 为空；
- 某一条拆不出来 = 那一条带 `problem` / `detail`（不执行、如实记成被拒），
  其余条目照常执行 —— 一条失败不作废整步；
- 接住层自己失败（一个条目都出不来）= `problem=CATCH_FAILED`（整步 unknown）——
  绝不允许静默只跑第一条。

## 计步口径（业主要看的步数是拆后的）

一步给了 N 条调用 ⇒ 拆成 N 条条目，每条占一个步号（`step_index` 连续），
另带 `turn_index`（同一个"模型回合"= 同一次 `ask_step`）与 `call_index`（本回合第几条）。
于是"步数"（拆后条目数）与"回合数"（模型调用次数）两个数各自算得出来，而业主看的
步数是前者。某条因预算/收工未执行也计步，但标 `not_executed=True` —— 不计步会让
"第几步"错位。

## 这一层不做的事

不读盘、不写盘、不认识任何角色、不判准入：它只拆与记账。执行由调用方给的 `decode`
回调（一条原生调用 ⇒ `(shape, payload, action, problem, detail)`）与循环的逐条执行路径完成。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

#: 逐条记录的会话事件名。每一条拆分出来的调用落一条（`errorstats` 据它数
#: `multi_call_executed_calls`；出处也指在这一行上）。
STEP_CALL_EVENT = "agent_step_call"

#: 接住层自己失败的码（一个条目都拆不出来 ⇒ 整步 unknown，不是"跑了第一条"）。
CATCH_FAILED = "catch_failed"

#: 某一条没执行的两档理由（不是"成功"，也不是"被拒"——是"没轮到"）。
NOT_EXECUTED_BUDGET = "budget"
NOT_EXECUTED_FINISHED = "finished"

#: 汇总里那句可执行建议（让模型据此少发并列调用）。
ADVICE = ("下一步请只发一条调用：并列的多条会被拆成多条顺序步逐条执行与记账，"
          "不会合并成一步。")

#: 一处文本上限（汇总那一行要能进 warn，而 warn 会进模型上下文）。
LINE_CHARS = 80


def digest_line(text: Any, limit: int = LINE_CHARS) -> str:
    """把一段读数压成一句话（去换行、去多余空白、超长截断并标注）。

    名字刻意不叫 `one_line`：那个名字在 `agent_l/_support.py` 已有一份（L 自己的
    读数拼法），两处各一份会让 R003 报"同一判据两份实现"。这里只服务拆分汇总。
    """
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "…"


def step_index_of(first_step: int, call_index: int) -> int:
    """一条条目的步号：这一回合第一条的步号 + 它是第几条。

    这就是"步数按拆分后的条目记"的实现处（业主要看的步数是拆后的）：一次模型调用给了
    N 条调用 ⇒ 这 N 条各占一个步号，连续、不重号。单条那一趟（N = 1）它就是 `first_step`
    —— 于是单条的行为与改前逐字相同（判据 8）。判据 11 / 12 钉的就是这一处：
    把它打桩成"每回合只 +1"，同一个回合里的条目就会重号，"步数按条目记"当场消失。
    """
    return int(first_step) + int(call_index)


def action_of(shape: str, payload: Mapping[str, Any] | None) -> str:
    """一条条目指向的动作名（只服务读数：第几条、哪个工具）。

    只读载荷里的键名，不认任何角色名与工具名表：`tool` 取 `payload["name"]`，
    `summon` / `message` 取收件人，其余取形状名本身。
    """
    got = dict(payload or {})
    shape = str(shape or "")
    if shape == "tool":
        return str(got.get("name") or "(未命名工具)")
    if shape in ("summon", "summon_many", "message", "handoff"):
        who = got.get("role") or got.get("to") or ""
        if shape == "summon_many":
            n = len(got.get("targets") or ())
            return f"{shape}({n} 项)"
        return f"{shape}→{who}" if who else shape
    return shape or "(未命名)"


def outcome_of(shape: str, payload: Mapping[str, Any] | None,
               result: Mapping[str, Any] | None, *, executed: bool = True) -> dict[str, Any]:
    """一条条目的结局读数：`{ok, action, line}`（`line` 就是"结果一句话"）。

    三种结局分开（三态纪律）：成功 / 被拒 / 没执行。`ok` 只对"真的执行了并且成功"
    为真 —— 没执行的那一条不许折成成功。
    """
    got = dict(result or {})
    action = action_of(shape, payload)
    if not executed:
        return {"ok": False, "action": action, "line": "未执行"}
    ok = bool(got.get("ok"))
    if ok:
        data = got.get("data")
        brief = ""
        if isinstance(data, Mapping):
            for key in ("summary", "text", "content", "count", "total", "state", "id"):
                if key in data:
                    brief = digest_line(data.get(key), 40)
                    break
        if not brief:
            brief = digest_line(got.get("detail") or got.get("outcome") or "", 40)
        return {"ok": True, "action": action, "line": f"成功{('：' + brief) if brief else ''}"}
    why = (got.get("error") or got.get("detail") or got.get("refusal_reason")
           or got.get("problem") or got.get("outcome") or "")
    return {"ok": False, "action": action, "line": f"被拒：{digest_line(why, 50)}" if why
            else "被拒（没给理由）"}


@dataclass(frozen=True)
class StepRequest:
    """一次"模型回合"的请求包：第 1 条已解码好，其余条目靠 `call.tool_call_list` + `decode`。

    `turn_index` / `first_step` 是步号口径的那两格：`turn_index` 记"这是第几次模型调用"，
    `first_step` 是这一回合第一条的步号（拆分后的步号从这里连续排下去）。
    """

    turn_index: int
    first_step: int
    shape: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    action: str = ""
    problem: str = ""
    detail: str = ""
    #: 这一回合那次模型调用的结局（`llmseam.SeamCall`）；只有 `tool_call_list` 被用到。
    call: Any = None

    def raw_calls(self) -> tuple[Any, ...]:
        """模型一次给出的全部原生调用（没有原生面时是空表 ⇒ 单条目）。"""
        return tuple(getattr(self.call, "tool_call_list", ()) or ())


@dataclass(frozen=True)
class StepItem:
    """拆分后的一条：`(turn_index, call_index)` 定位，`step_index` 是它的步号。"""

    turn_index: int
    step_index: int
    call_index: int
    calls: int
    shape: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    action: str = ""
    problem: str = ""
    detail: str = ""

    @property
    def is_last(self) -> bool:
        """本回合的最后一条（汇总挂在它身上，于是模型只读一遍）。"""
        return self.call_index + 1 >= max(self.calls, 1)


@dataclass
class StepDispatch:
    """接住一步之后的整包：有序条目 + 每条的结局 + 一句汇总。"""

    items: tuple[StepItem, ...] = ()
    turn_index: int = 0
    requested: int = 0
    problem: str = ""
    detail: str = ""
    #: `call_index` → 结局读数（`outcome_of` 的那一份 + `elapsed_ms` / `usd` / 未执行理由）。
    outcomes: dict[int, dict[str, Any]] = field(default_factory=dict)

    @property
    def multi(self) -> bool:
        """这一步是不是"多调用步"（模型一次给了 2 条及以上）。"""
        return self.requested > 1

    def provenance(self, item: StepItem) -> dict[str, Any]:
        """这一条属于哪个回合、第几条、这一回合共几条（溯源字段）。"""
        return {"turn_index": int(item.turn_index), "call_index": int(item.call_index),
                "calls": int(item.calls), "step_index": int(item.step_index)}

    def note(self, item: StepItem, outcome: Mapping[str, Any]) -> dict[str, Any]:
        """记下一条的结局（顺序即执行顺序；同一 index 写了两次时后者胜）。"""
        got = dict(outcome)
        got.setdefault("action", action_of(item.shape, item.payload))
        got["call_index"] = int(item.call_index)
        got["step_index"] = int(item.step_index)
        got["shape"] = str(item.shape)
        self.outcomes[int(item.call_index)] = got
        return got

    def mark_not_executed(self, item: StepItem, reason: str) -> dict[str, Any]:
        """把一条记成"没执行"（仍占一个步号：不计步会让"第几步"错位）。"""
        why = ("因预算未执行" if str(reason) == NOT_EXECUTED_BUDGET
               else "因本回合已收工未执行")
        got = outcome_of(item.shape, item.payload, {}, executed=False)
        got["line"] = why
        if item.problem:
            got["line"] = f"未执行（这一条解码不出来：{digest_line(item.detail, 40)}）"
        got["not_executed"] = True
        got["reason"] = str(reason or "")
        got["detail"] = (f"{why}（第 {item.call_index + 1} 条 "
                         f"{action_of(item.shape, item.payload)}）")
        return self.note(item, got)

    def summary(self) -> str:
        """一句汇总（回给模型的那一份）：第 k 条 / 工具名 / 结果一句话 + 可执行建议。"""
        if not self.items:
            return "这一步一条调用都没接住（没有可执行的条目）。"
        head = (f"这一步给了 {self.requested} 条调用，已按顺序逐条"
                if all(not (self.outcomes.get(i.call_index) or {}).get("not_executed")
                       for i in self.items)
                else f"这一步给了 {self.requested} 条调用，已按顺序逐条处理（有未执行的条目）")
        parts: list[str] = []
        for item in self.items:
            got = self.outcomes.get(int(item.call_index)) or {}
            line = str(got.get("line") or "（没有读数）")
            parts.append(f"第 {item.call_index + 1} 条 {action_of(item.shape, item.payload)} {line}")
        done = sum(1 for i in self.items
                   if not (self.outcomes.get(i.call_index) or {}).get("not_executed")
                   and self.outcomes.get(i.call_index))
        return (f"{head}：{'；'.join(parts)}。"
                f"（真的执行 {done} / {self.requested} 条）{ADVICE}")

    def reading(self) -> dict[str, Any]:
        """机器读的那一份（步数 / 回合 / 调用条数三者都在这里）。"""
        not_executed = [int(i.call_index) for i in self.items
                        if (self.outcomes.get(i.call_index) or {}).get("not_executed")]
        return {
            "turn_index": int(self.turn_index),
            "calls": int(self.requested),
            "items": len(self.items),
            "steps": [int(i.step_index) for i in self.items],
            "executed": len(self.items) - len(not_executed),
            "not_executed": not_executed,
        }


def catch_step_request(request: StepRequest,
                       *, decode: Callable[[Mapping[str, Any]], tuple[str, Mapping[str, Any],
                                                                      str, str, str]]
                       ) -> StepDispatch:
    """接住这一步模型要求做的动作，拆成有序条目（顺序 = 原顺序，绝不重排）。

    `decode(一条原生调用) -> (shape, payload, action, problem, detail)` 由调用方给
    （它是"原生调用 → 循环形状"的唯一解码入口，本层不复制那份判据）。

    返回值三态见模块 docstring：一个条目都拆不出来时 `problem=CATCH_FAILED`，
    调用方必须把它当"整步 unknown"处理 —— 不许退化成"只跑第一条"。
    """
    requested = max(len(request.raw_calls()), 1)
    items: list[StepItem] = []
    if not str(request.shape):
        # 第 1 条都没解码出来：整步接不住（不是"接住了 0 条"）。
        return StepDispatch(items=(), turn_index=int(request.turn_index), requested=requested,
                            problem=CATCH_FAILED,
                            detail=(str(request.detail) or str(request.problem)
                                    or "第 1 条调用解码不出形状"))
    items.append(StepItem(
        turn_index=int(request.turn_index),
        step_index=step_index_of(request.first_step, 0),
        call_index=0, calls=requested, shape=str(request.shape),
        payload=dict(request.payload or {}),
        action=str(request.action) or action_of(request.shape, request.payload)))
    for index, raw in enumerate(request.raw_calls()[1:], start=1):
        try:
            shape, payload, action, problem, detail = decode(raw)
        except Exception as exc:  # noqa: BLE001 —— 一条解不出来不许带走其余条目
            shape, payload, action = "", {}, ""
            problem = "decode_failed"
            detail = f"{type(exc).__name__}: {exc}"
        items.append(StepItem(
            turn_index=int(request.turn_index),
            step_index=step_index_of(request.first_step, index),
            call_index=index, calls=requested, shape=str(shape or ""),
            payload=dict(payload or {}), action=str(action or ""),
            problem=str(problem or ""), detail=str(detail or "")))
    return StepDispatch(items=tuple(items), turn_index=int(request.turn_index),
                        requested=requested)
