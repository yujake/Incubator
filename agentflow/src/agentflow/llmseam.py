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
            note: str = "") -> SeamCall:
        """发一次调用，落一条审计记录，返回结局（不抛业务异常）。"""
        t0 = time.monotonic()
        base = dict(
            prompt_version=self.prompt_version,
            prompt_sha256=_sha(prompt),
            system_sha256=_sha(system) if system else "",
            model=self.model_name,
            scope=self.scope,
        )
        if not self.wired:
            call = SeamCall(ok=False, problem="judge_not_wired",
                            detail="没有配置模型（AGENTFLOW_MODEL_API_KEY 为空）"
                                   "：这是没查成，不是没有问题",
                            elapsed_sec=time.monotonic() - t0, **base)
            return self._land(call, prompt=prompt, system=system, task_id=task_id, note=note)
        if self.usd_budget is not None and self.spend.usd >= self.usd_budget:
            call = SeamCall(ok=False, problem="judge_over_budget",
                            detail=f"花销预算已耗尽（已用 {self.spend.usd:.6f} / 上限 "
                                   f"{self.usd_budget:.6f}）—— 这一次没有发起请求",
                            elapsed_sec=time.monotonic() - t0, **base)
            return self._land(call, prompt=prompt, system=system, task_id=task_id, note=note)

        try:
            reply = self.gateway.complete(prompt, scope=self.scope,
                                          system=(system or None))
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
        call = SeamCall(
            ok=bool(getattr(reply, "ok", False)),
            text=str(getattr(reply, "text", "") or ""),
            problem="" if getattr(reply, "ok", False) else "judge_failed:ModelReplyNotOk",
            detail=str(getattr(reply, "error_detail", "") or ""),
            tokens_in=int(getattr(reply, "tokens_in", 0) or 0),
            tokens_out=int(getattr(reply, "tokens_out", 0) or 0),
            usd=usd,
            elapsed_sec=time.monotonic() - t0,
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

    # -------------------------------------------------------------- 落档
    def _land(self, call: SeamCall, *, prompt: str, system: str, task_id: str,
              note: str) -> SeamCall:
        event = {
            "kind": "llm_call",
            "role": self.role,
            "task_id": task_id,
            "note": note,
            "prompt_chars": len(prompt),
            **call.to_dict(),
            "spend_after": self.spend.to_dict(),
        }
        try:
            _path, problem = SS.append(self.session_root, event, sid=self.sid)
        except Exception as exc:  # 落档失败不许静默：它是审计面
            problem = f"会话记录写入抛异常：{type(exc).__name__}: {exc}"
        if problem:
            return SeamCall(**{**call.__dict__, "recorded": problem})
        return call

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict[str, Any] | None, SeamCall]:
        """要一份 JSON：返回 `(判定, 结局)`。坏 JSON 归成 `judge_bad_json`，不静默当空。"""
        call = self.ask(prompt, system=system, task_id=task_id, note=note)
        if not call.ok:
            return None, call
        from .llm import parse_llm_json

        try:
            data = parse_llm_json(call.text)
        except Exception:
            data = None
        if not isinstance(data, Mapping):
            bad = SeamCall(**{**call.__dict__, "ok": False, "problem": "judge_bad_json",
                              "detail": "模型返回的不是一个 JSON 对象"})
            return None, bad
        return dict(data), call


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
