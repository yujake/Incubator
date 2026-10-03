"""统一的模型缝：一次模型调用 = 一条可审计的记录。

## 为什么要有这一层（`draft/34` §7 的第 4 步）

在它之前，"接模型"这件事在仓里有两种纪律：`runflow` 那条流程把 `prompt_version`
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

落在项目会话记录里（`sessions.append`）—— 不新增表。理由与 `draft/29` §3.2 一致：
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
import re

from . import judge as J
from . import modelcost as MC
from . import modelgw as MG
from . import sessions as SS
from .agent_prompts import PROMPT_VERSION

#: 本缝的用途归口（`schema.USAGE_SCOPES` 之一）。写死一处，避免调用点各写一个。
SEAM_SCOPE = "reason"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    usd: float | None = None
    elapsed_sec: float = 0.0
    recorded: str = ""      # 空串 = 审计记录已落档；否则是没落成的原因
    #: 这一趟走的是哪条协议：`"tool_calls"`（原生工具调用）/ `"text"`（文本 JSON 回落）。
    #: 它是审计读数，不是装饰：`draft/37` §48 那趟真机死在"模型把 `tool` 写成 `name`"，
    #: 而那条路上"名字由谁给"正是这个字段回答的问题。
    protocol: str = "text"
    #: 这一趟广告了几件函数（工具 + 循环形状），以及那份工具面的摘要。
    tools_advertised: int = 0
    tools_sha256: str = ""
    #: 模型给了几条结构化工具调用（0 = 没给，于是回落去解析文本）。
    tool_calls: int = 0
    #: 原始的 `tool_calls`（`ask_step` 要把它们翻成循环的形状）。
    #: 刻意不进 `to_dict()`：审计面留条数与工具面摘要就够，逐条原文会随每次调用膨胀。
    tool_call_list: tuple[dict[str, Any], ...] = ()

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
            "usd": self.usd,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "recorded": self.recorded,
            "protocol": self.protocol,
            "tools_advertised": self.tools_advertised,
            "tools_sha256": self.tools_sha256,
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

    # -------------------------------------------------------------- 构造
    @classmethod
    def for_role(cls, role: str, *, session_root: Path | str, gateway: Any | None = None,
                 from_env: bool = True, **kw: Any) -> "LlmSeam":
        """按角色造一个缝。`from_env=True` 时从环境变量读配置（没 key 就是没接线）。"""
        if gateway is None and from_env:
            spec = MG.spec_from_env()
            gateway = MG.ModelGateway(spec) if spec.configured else None
        return cls(role=role, session_root=Path(session_root), gateway=gateway, **kw)

    @property
    def wired(self) -> bool:
        """这次运行有没有接上模型（没接上就是 judge_not_wired，不是"没有结论"）。"""
        return self.gateway is not None

    @property
    def model_name(self) -> str:
        """这次用的是哪个模型（审计记录的一栏；拿不到就给空串）。"""
        spec = getattr(self.gateway, "spec", None)
        return str(getattr(spec, "model", "") or "")

    # -------------------------------------------------------------- 调用
    def ask(self, prompt: str, *, system: str = "", task_id: str = "",
            note: str = "", max_tokens: int | None = None,
            face: "ToolFace | None" = None) -> SeamCall:
        """发一次调用，落一条审计记录，返回结局（不抛业务异常）。

        `max_tokens` 不给时用网关缺省（4,096）。给它的那一处是循环步
        （`agent_loop.AgentLoop.max_output_tokens`）：写稿步的回复要比"一个工具调用"
        长得多，而网关缺省会把"写一段 LaTeX + JSON 信封"截断成半句话（`draft/37` §16 P0）。
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
        )
        if not self.wired:
            call = SeamCall(ok=False, problem="judge_not_wired",
                            detail="没有配置模型（AGENTFLOW_MODEL_API_KEY 为空）"
                                   "：这是没查成，不是没有问题",
                            elapsed_sec=time.monotonic() - t0, **base)
            # `charged=False`：这一次「没有发请求」，所以没有钱要记。
            # 会话事件照旧留一条（"试过、没接线"是事实），账本不入账。
            return self._land(call, prompt=prompt, system=system, task_id=task_id, note=note,
                              charged=False)
        if self.usd_budget is not None and self.spend.usd >= self.usd_budget:
            call = SeamCall(ok=False, problem="judge_over_budget",
                            detail=f"花销预算已耗尽（已用 {self.spend.usd:.6f} / 上限 "
                                   f"{self.usd_budget:.6f}）—— 这一次没有发起请求",
                            elapsed_sec=time.monotonic() - t0, **base)
            return self._land(call, prompt=prompt, system=system, task_id=task_id, note=note,
                              charged=False)

        try:
            reply = self.gateway.complete(prompt, scope=self.scope,
                                          system=(system or None),
                                          max_tokens=max_tokens,
                                          tools=(face.functions if face is not None else None))
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
        call = SeamCall(
            ok=bool(getattr(reply, "ok", False)),
            text=str(getattr(reply, "text", "") or ""),
            problem="" if getattr(reply, "ok", False) else "judge_failed:ModelReplyNotOk",
            detail=str(getattr(reply, "error_detail", "") or ""),
            tokens_in=int(getattr(reply, "tokens_in", 0) or 0),
            tokens_out=int(getattr(reply, "tokens_out", 0) or 0),
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

    def _usd_of(self, reply: Any) -> tuple[float | None, str]:
        """按价格表算这次花销。算不出来就如实说算不出来（不许悄悄记 0）。"""
        try:
            price = self.price or MC.price_from_env()
            return float(MC.usd_for(reply, price)), ""
        except Exception as exc:  # 价格表缺失/格式不对：这不影响结论，但必须留痕
            return None, f"花销未能折算（{type(exc).__name__}: {exc}）"

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
        """
        from . import tokenmeter as TM

        if self.meter is None:
            return {"charged": False, "usage_id": "", "reason": "no_meter",
                    "note": "这个缝没有接账本（meter=None）⇒ 本次没有入账（不是记了一笔零）"}
        idx = self.ledger_calls
        self.ledger_calls += 1
        tid = str(task_id or "").strip() or None   # `""` 会被 schema 拒；None = 不挂任务
        outcome = "ok" if call.ok else (call.problem or "failed")
        note = f"source=llmseam;role={self.role};call_index={idx};outcome={outcome}"
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
        # 幂等键的命名空间必须含角色（`modelcost.idempotency_key` 的用法说明）：
        # 只用 sid 的话，两个角色各自的第 0 次调用会撞同一个键，
        # 后到的那一笔被静默判成 `duplicate` —— 一笔真实花销凭空消失。
        key = MC.idempotency_key(f"{self.sid or ''}:{self.role}", idx)
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
        ledger = (self._charge_ledger(call, task_id=task_id) if charged
                  else {"charged": False, "usage_id": "", "reason": "no_request",
                        "note": "这次没有发请求（没接线 / 预算已尽）⇒ 没有钱要记"})
        event = {
            "kind": "llm_call",
            "role": self.role,
            "task_id": task_id,
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

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "", max_tokens: int | None = None) -> tuple[dict[str, Any] | None, SeamCall]:
        """要一份 JSON：返回 `(判定, 结局)`。坏 JSON 归成 `judge_bad_json`，不静默当空。"""
        call = self.ask(prompt, system=system, task_id=task_id, note=note, max_tokens=max_tokens)
        if not call.ok:
            return None, call
        from .llm import parse_llm_json

        err = ""
        try:
            data = parse_llm_json(call.text)
        except Exception as exc:
            # 把解析报错原文 + 一句话诊断留下来（2026-09-30）：以前这里只写
            # "不是 JSON 对象"，于是"它到底哪里写坏了"在台账上不可回答。
            # 真机实测：模型（M 与 G 的循环都）连着三次多写一个右花括号
            # （`…"why": "…"}}`）—— 现在这句话会进"纠正消息"，模型下一次就能改对。
            data = None
            err = f"{type(exc).__name__}: {exc}"
        if not isinstance(data, Mapping):
            hint = _json_shape_hint(call.text)
            bad = SeamCall(**{**call.__dict__, "ok": False, "problem": "judge_bad_json",
                              "detail": (f"模型返回的不是一个 JSON 对象（解析报错：{err or '不是对象'}）"
                                         f"{hint}；原文前 200 字：{str(call.text)[:200]}")})
            return None, bad
        return dict(data), call

    def ask_step(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "", max_tokens: int | None = None,
                 face: ToolFace | None = None) -> tuple[dict[str, Any] | None, SeamCall]:
        """循环的一步：优先用原生工具调用，拿不到就回落去解析文本 JSON。

        为什么要这一层（`draft/37` §48/§49）：文本协议要求模型把调用重新序列化成
        一行 JSON，于是"键名漂移"（`tool` 写成 `name`）会连累整趟运行
        （第三趟真机就死在这里）。原生工具调用把名字放进传输层的结构化字段 ——
        那一类失败在结构上不再存在。回落路径一个字都没放宽：没有原生工具调用的
        传输层（离线缝 / mock / replay / 没接线的判定）照旧走 `ask_json` 的那一套，
        既有判据因此一条都不用改。
        """
        call = self.ask(prompt, system=system, task_id=task_id, note=note,
                        max_tokens=max_tokens, face=face)
        if not call.ok:
            return None, call
        if face is not None and call.tool_call_list:
            if len(call.tool_call_list) > 1:
                # 本循环的纪律是"一步一件事"（`_shape_of` 同名判据在文本那条路上）。
                # 多条原生调用不是错误数据，但它与"一步一件事"冲突 ⇒ 明确说清楚，
                # 而不是默默只执行第一条（那会让模型以为其余几条也生效了）。
                bad = SeamCall(**{**call.__dict__, "ok": False, "problem": "judge_bad_json",
                                  "detail": (f"这一步给了 {len(call.tool_call_list)} 条工具调用；"
                                             "本循环一步只做一件事，请只留一条")})
                return None, bad
            data, problem, detail = face.to_shape(call.tool_call_list[0])
            if data is None:
                bad = SeamCall(**{**call.__dict__, "ok": False, "problem": problem,
                                  "detail": detail})
                return None, bad
            return data, call
        # 回落：上游没给结构化调用（或不支持 tools）⇒ 走原来的文本 JSON 那条路。
        from .llm import parse_llm_json

        err = ""
        try:
            data = parse_llm_json(call.text)
        except Exception as exc:  # noqa: BLE001 —— 与 `ask_json` 同一套处理
            data = None
            err = f"{type(exc).__name__}: {exc}"
        if not isinstance(data, Mapping):
            hint = _json_shape_hint(call.text)
            bad = SeamCall(**{**call.__dict__, "ok": False, "problem": "judge_bad_json",
                              "detail": (f"模型返回的不是一个 JSON 对象（解析报错：{err or '不是对象'}）"
                                         f"{hint}；原文前 200 字：{str(call.text)[:200]}")})
            return None, bad
        return dict(data), SeamCall(**{**call.__dict__, "protocol": "text"})


#: 循环协议里那些不是工具的形状（`agent_loop.SHAPES` 减去 `tool`）：
#: 它们与真工具一起被广告成函数。理由与 DSH 同源 —— 在 DSH 里 `ask_user` /
#: `present` / `goal` 本身就是工具，于是"这一步要做什么"这件事的名字
#: 永远来自传输层的结构化字段，而不是模型手写的一行 JSON。
#:
#: 每项是 `(广告名, 目标形状, 参数 schema)`；schema 的形状与 `agent_loop._shape_of`
#: 认的那一套逐字对齐（那里仍是唯一判有效性的地方 —— 这里只负责"把名字翻译过去"）。
META_FUNCTIONS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("framework_summon", "summon", {
        "type": "object",
        "properties": {
            "role": {"type": "string", "enum": list("ABCDEFGH")},
            "action": {"type": "string"},
            "params": {"type": "object"},
            "why": {"type": "string"},
        },
        "required": ["role", "action"],
    }),
    ("framework_summon_many", "summon_many", {
        "type": "object",
        "properties": {
            "targets": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": list("ABCDEFGH")},
                    "action": {"type": "string"},
                    "params": {"type": "object"},
                    "instance": {"type": "string"},
                    "input_key": {"type": "string"},
                },
                "required": ["role", "action"],
            }},
            "why": {"type": "string"},
        },
        "required": ["targets"],
    }),
    ("framework_ask_user", "ask_user", {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
            "timeout_sec": {"type": "number"},
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
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "reply_to": {"type": "string"},
        },
        "required": ["to", "body"],
    }),
    ("framework_final", "final", {
        "type": "object",
        "properties": {
            "final": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
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

    def to_shape(self, call: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
        """把一条原生工具调用翻成循环协议的形状。返回 `(data, problem, detail)`。

        三态纪律：翻不出来时 `data is None` 且 `problem` 非空 —— 绝不返回一个
        "看起来像调用"的空对象（那会让下一步去执行一件模型没说过的事）。
        """
        raw_name = str(call.get("name") or "")
        target = self.names.get(raw_name)
        if target is None:
            return None, "judge_bad_json", (
                f"模型调用了一个没广告过的函数 {raw_name!r}（这一趟广告的是 "
                f"{sorted(self.names)[:6]}…）")
        raw_args = call.get("arguments")
        text = raw_args if isinstance(raw_args, str) else json.dumps(raw_args or {},
                                                                    ensure_ascii=False)
        try:
            args = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError as exc:
            # 与 DSH 的 `parseArguments` / `ToolArgsError` 同一条纪律：参数坏不是
            # "认不出的形状" —— 工具名已经从结构化字段拿到了，所以这句纠正能点名
            # "是哪个函数的参数坏了"，比"键名不对"精确得多。
            return None, "judge_bad_args", (
                f"函数 {raw_name} 的参数不是合法 JSON（{exc}）；原文前 200 字：{text[:200]}")
        if not isinstance(args, Mapping):
            return None, "judge_bad_args", (
                f"函数 {raw_name} 的参数必须是一个 JSON 对象，收到 {type(args).__name__}")
        why = str(args.pop("why", "") or "")
        if target.startswith("tool:"):
            return {"tool": target.split(":", 1)[1], "args": dict(args), "why": why}, "", ""
        if target == "final":
            payload = dict(args)
            payload.setdefault("evidence", [])
            return {"final": payload.get("final") or "", "evidence": payload.get("evidence") or []}, "", ""
        if target == "note":
            return {"note": {"text": str(args.get("text") or "")}}, "", ""
        payload = dict(args)
        if why:
            payload.setdefault("why", why)
        return {target: payload}, "", ""


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
            "description": str(getattr(spec, "summary", "") or real),
            "parameters": {**params, "type": "object", "properties": props},
        }})
    for san, target, schema in META_FUNCTIONS:
        names[san] = target
        functions.append({"type": "function", "function": {
            "name": san,
            "description": f"循环形状 {target}（不是工具：它由框架执行）",
            "parameters": schema,
        }})
    digest = _sha(json.dumps(functions, ensure_ascii=False, sort_keys=True))
    return ToolFace(functions=tuple(functions), names=dict(names), sha256=digest)




def _json_shape_hint(text: str) -> str:
    """坏 JSON 的一句话诊断：`}` 多了或少了是最常见的那两种（真机实测占多数）。

    做法是"试探性修补一次再解析"：能修好，就说明模型犯的正是这个错 ——
    于是那句纠正消息可以点名它，而不是泛泛地说"不是 JSON 对象"。
    注意它只用于诊断：修补后的结果不会被当成模型的原意使用
    （那会让"多一个括号"这种错被静默接受）。
    """
    from .llm import parse_llm_json

    t = str(text or "").strip()
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
