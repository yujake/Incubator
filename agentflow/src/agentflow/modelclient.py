"""把 `modelgw.ModelGateway` 适配成抽取层要的 ``.complete(prompt) -> str`` 客户端。

## 为什么需要这个模块

`agentflow.llm.LLMExtractor` 的构造签名是"任意有 ``complete(prompt) -> str`` 的对象"，
它的 docstring 写着"本机不实跑（无 API key，也不该在单测里打网络）"。于是整条
"模型读书 + 框架逐字回验、回验不过就剔除"的链路在仓里建好了却从没被真模型驱动过：
`LLMExtractor` 只有假 client 的自检，真实调用点一处都没有。

本模块补的就是那一处：把已经存在的 `ModelGateway`（有重试、有超时、有分类过的结局）
包成 `LLMExtractor` 认的形状。

## 三个口径

1. 三态不许折平：网关的结局是"成功 / 没查成 / 查了失败"三态
   （`ModelReply.ok` 与 `ModelReply.not_checked`）。`LLMExtractor` 只认
   "字符串"或"抛异常"，所以这里必须把三态翻译成两种异常，而不是把所有失败
   都折成一个 `RuntimeError`：没查成（没 key / 超时 / 限流 / 网络）与查了失败
   （坏响应 / 4xx）对调用方意味着不同的下一步动作。
2. 异常是必须的，不是偷懒：`agent_b` 对抽取异常的处理是"不置 `processed`，
   让租约过期后重试"；返回空字符串会被 `parse_llm_json` 判成不可解析，
   最终同样抛 `ExtractionError`。也就是说两条路都抛，但只有这里抛出来的那条
   带得住"为什么"（`error_kind` 与 `error_detail` 逐字保留在异常消息里）。
3. 记账只走一条路：金额与归口一律经 `modelcost.charge_reply` 写进
   `usage_ledger`，本模块不自己算钱、不自己拼账本行。`meter=None` 时它如实返回
   "未接线"（`charged=False`），那也是要能被读到的结局，不是静默丢弃。

## 边界（不许被读成"已经修好了限流/成本"）

- 重试与限流是 `ModelGateway` 的职责，本模块一次调用只发一次请求。
- `scope` 必填且只能用 `schema.USAGE_SCOPES` 里的值：抽取用 `"extract"`。
  这一档在 `schema.USAGE_SCOPE_PRODUCERS` 里的声明必须与本模块一致 ——
  本模块存在而声明写着"没有产出点"，就是一句假话（那正是 `G-6` 要防的形态）。
- 本模块不读环境变量取 key：`spec_from_env` 才是唯一入口，它读的是
  `AGENTFLOW_MODEL_API_KEY` / `AGENTFLOW_MODEL_BASE_URL` / `AGENTFLOW_MODEL_NAME`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from .modelcost import charge_reply
from .modelgw import (
    ENV_KEY,
    ModelGateway,
    ModelReply,
    spec_from_env,
)

__all__ = [
    "ModelClient",
    "ModelFailed",
    "ModelUnavailable",
    "client_from_env",
    "selftest",
]

#: 抽取业务在 `schema.USAGE_SCOPES` 里的归口。写成常量而不是散在各处的字面量：
#: 换档位时只改这一处，`by_scope` 的读数才追得回来。
SCOPE_EXTRACT = "extract"


class ModelUnavailable(RuntimeError):
    """这次调用没查成（没 key / 超时 / 网络 / 限流）。

    与 `ModelFailed` 分开的理由：这一档的正确动作是"稍后重试或去配 key"，
    而不是"去查模型说了什么"。把两者合成一个异常，调用方就只能靠字符串匹配
    猜自己该做什么。
    """

    def __init__(self, message: str, *, reply: ModelReply | None = None) -> None:
        super().__init__(message)
        self.reply = reply


class ModelFailed(RuntimeError):
    """查了、结论是失败（坏响应、HTTP 4xx、内容为空等）。"""

    def __init__(self, message: str, *, reply: ModelReply | None = None) -> None:
        super().__init__(message)
        self.reply = reply


@dataclass
class ModelClient:
    """`LLMExtractor` 认的客户端：一次 `complete(prompt)` = 一次受记账的模型调用。

    `charges` 逐笔保留 `charge_reply` 的返回值（含"未接线"与"判重放"两种
    非入账结局），所以"这次抽取花了多少、有没有真的入账"可以从对象上读出来，
    不必去翻账本倒推。
    """

    gateway: ModelGateway
    scope: str = SCOPE_EXTRACT
    system: str | None = None
    meter: Any = None
    #: 审计挂点（`usage_ledger.task_id`）。没接线就原样留 `None`：
    #: `verify.py` 的 `dangling_usage_task` 逐字容忍 `None`（那是"未接线"），
    #: 只在"非 None 且不在 `tasks` 表里"时报 error。折成一个假字符串
    #: （曾经是 `"(未接线)"`）会让每一笔未接线的花销都落成一条 dangling 行 ——
    #: 那是三态被折平：把"没有台账号"伪装成"有一个叫 (未接线) 的台账号"。
    task_id: str | None = None
    role: str = "B"
    #: `max_tokens` 这一格已删（2026-10-15 业主裁定「我们不卡 token，只卡总花销的钱」）。
    #: 它此前是"抽取那条路显式给 8192"的落点，而真调用对照证明：不带这一栏时上游给得更宽
    #: （`finish_reason=stop`、`tokens_out=14,015`）。请求体里从此不出现 `max_tokens`。
    #: 逐笔记账结局（`modelcost.charge_reply` 的原样返回值）。
    charges: list[dict] = field(default_factory=list)
    #: 已经发出去的调用次数（含失败的那几次）。
    calls: int = 0

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        """调一次模型；成功返回文本，没查成抛 `ModelUnavailable`，查了失败抛 `ModelFailed`。"""
        reply = self.call(prompt, system=system)
        if reply.ok:
            return reply.text
        detail = f"{reply.error_kind}: {reply.error_detail}"
        if reply.not_checked:
            raise ModelUnavailable(
                f"这一次没有查成（{detail}）；若要真跑，先配好环境变量 {ENV_KEY}",
                reply=reply,
            )
        raise ModelFailed(f"模型调用失败（{detail}）", reply=reply)

    def call(self, prompt: str, *, system: str | None = None) -> ModelReply:
        """发一次调用并记账，返回网关的三态结局（不抛，供需要自己看 `error_kind` 的调用方用）。"""
        try:
            reply = self.gateway.complete(
                prompt,
                scope=self.scope,
                system=self.system if system is None else system,
            )
        except Exception as exc:  # noqa: BLE001 —— 见 `runflow._complete_or_not_checked`：
            # `ModelGateway.complete` 承诺"从不抛异常"，但传输层实现抛出的意外异常
            # 仍可能穿出来（`G-7` 口径一）。这里把它折成"没查成"，理由是这一档在
            # 调用方看来与超时、网络失败同类（都要重试或换配置），而"代码崩了"
            # 不该伪装成"模型说了什么"。
            raise ModelUnavailable(
                f"网关抛出了 {type(exc).__name__}: {exc}"
                "（`ModelGateway.complete` 承诺从不抛异常，`G-7` 登记了这个缺口）"
            ) from exc
        self.calls += 1
        self.charges.append(
            charge_reply(
                self.meter,
                reply,
                role=self.role,
                # 原样透传（`""` 也归一成 `None`）：`None` 是"未接线"的合法取值，
                # 不是"缺一个字符串"。见 `task_id` 字段那段（`dangling_usage_task` 的判据）。
                task_id=(str(self.task_id).strip() or None),
                scope=self.scope,
                call_index=self.calls,
            )
        )
        return reply

    # -- 读数（给报告与产物用） ------------------------------------------- #

    def charged_usd(self) -> float:
        """本次客户端真的入账的美元合计（未接线的那些笔计 0，且由 `uncharged` 单列）。"""
        return round(sum(float(c.get("usd") or 0.0) for c in self.charges), 6)

    def uncharged(self) -> int:
        """没有真的入账的笔数（`meter=None` 或判重放）。这个数不许折进 0 里。"""
        return sum(1 for c in self.charges if not c.get("charged"))

    def tokens(self) -> tuple[int, int]:
        """本次累计的 `(tokens_in, tokens_out)`（只统计真的入账的那几笔）。"""
        tin = sum(int(c.get("tokens_in") or 0) for c in self.charges)
        tout = sum(int(c.get("tokens_out") or 0) for c in self.charges)
        return tin, tout

    def to_dict(self) -> dict[str, Any]:
        """给产物/报告用的读数（调用次数、入账金额、未入账笔数、token、模型与 base_url）。

        刻意不含 key：`base_url` 与 `model` 可以进产物，key 不行。
        """
        tin, tout = self.tokens()
        return {
            "calls": self.calls,
            "charged_usd": self.charged_usd(),
            "uncharged_calls": self.uncharged(),
            "tokens_in": tin,
            "tokens_out": tout,
            "scope": self.scope,
            # 2026-10-17（长跑 goal）：采样钉死。审核类调用（V 的 `verify_proof` 等）
            # 原先用默认采样 ⇒ 同一份证明会一次判「成立」、一次判「有毛病」（实测），
            # 于是"经审核才进定理库/才作根"这扇门天生不可复现 ⇒ 长跑里证明链反复开合。
            # 默认 0；要改由配置面显式覆盖（这一栏同时进读数，见 `SeamCall`）。
            "temperature": 0,
            "model": getattr(self.gateway.spec, "model", ""),
            "base_url": getattr(self.gateway.spec, "base_url", ""),
        }


def client_from_env(*, scope: str = SCOPE_EXTRACT, meter: Any = None,
                    task_id: str | None = None, role: str = "B",
                    env: Mapping[str, str] | None = None,
                    transport: Any = None) -> ModelClient:
    """按环境变量建一个客户端。没配 key 也照样返回（`complete` 时才如实报"没查成"）。

    为什么不在建的时候就把"没 key"当异常抛掉：调用方通常要把"没查成"这件事
    记进产物与退出码（三态），而不是在装配阶段崩掉。装配阶段崩掉的话，
    连"为什么没跑成"都写不进清单。

    `task_id=None`（缺省）表示"这次调用没有台账号可挂" ⇒ 账本那一行留空，
    由 `verify.dangling_usage_task` 按"未接线"容忍；给了号就必须是 `tasks` 里
    真有的那一行（否则审计会如实地报它挂不上 —— 那正是我们要它报的）。

    `max_tokens` 这一栏已删（2026-10-15 业主裁定「我们不卡 token，只卡总花销的钱」）。
    它此前是"抽取那条路必须显式给 8192"的落点，理由是"概念表一长，输出的 JSON 就被
    4096 截在半句上"—— 那个诊断对，处方错了：不该由我们再设一个更大的上限，而该不设。
    真调用对照（2026-10-15）：同一段 prompt 不带 `max_tokens` 时上游回
    `finish_reason=stop`、`tokens_out=14,015`；带上 `32768` 时 `12,987` ⇒ 缺省比我们给的更宽。
    """
    spec = spec_from_env(env)
    gateway = ModelGateway(spec, transport=transport)
    return ModelClient(gateway=gateway, scope=scope, meter=meter, task_id=task_id, role=role)


# --------------------------------------------------------------------------- #
# 自检：`python -m agentflow.modelclient`（不联网）
# --------------------------------------------------------------------------- #


def _ok_transport(body: str):
    def _t(url: str, headers: Mapping[str, str], data: bytes,
           timeout_sec: float) -> tuple[int, str]:
        return 200, body

    return _t


def _fake_body(text: str = "抽出结果") -> str:
    return json.dumps(
        {
            "id": "x",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        },
        ensure_ascii=False,default=str)


def selftest() -> int:
    """五条：成功取文本 / 没 key 抛 ModelUnavailable / 坏响应抛 ModelFailed /
    没 key 的那次不算失败 / 记账在未接线时如实报未接线。"""
    print("=" * 72)
    print("modelclient 自检（全部离线：transport 是替身，不碰网络）")
    problems: list[str] = []

    spec_ok = spec_from_env({"AGENTFLOW_MODEL_API_KEY": "k", "AGENTFLOW_MODEL_NAME": "m"})
    c = ModelClient(ModelGateway(spec_ok, transport=_ok_transport(_fake_body("甲"))))
    got = c.complete("你好")
    print(f"[1] 成功路径：complete -> {got!r}；记账 {c.to_dict()}")
    if got != "甲":
        problems.append("成功路径没有取到文本")
    if c.uncharged() != 1:
        problems.append("meter=None 时这笔应当记成未接线（uncharged=1）")

    spec_no = spec_from_env({})
    c2 = ModelClient(ModelGateway(spec_no, transport=_ok_transport(_fake_body())))
    try:
        c2.complete("你好")
        problems.append("没 key 时应当抛 ModelUnavailable")
    except ModelUnavailable as exc:
        print(f"[2] 没 key：ModelUnavailable -> {exc}")
        print(f"    三态标记：not_checked={exc.reply.not_checked} error_kind={exc.reply.error_kind}")

    c3 = ModelClient(ModelGateway(spec_ok, transport=_ok_transport("这不是 JSON")))
    try:
        c3.complete("你好")
        problems.append("坏响应时应当抛 ModelFailed（而不是 ModelUnavailable）")
    except ModelFailed as exc:
        print(f"[3] 坏响应：ModelFailed -> {exc}")
    except ModelUnavailable as exc:
        problems.append(f"坏响应被折成了'没查成'：{exc}")

    gw_bad = ModelGateway(spec_ok, transport=_ok_transport("{}"))
    c4 = ModelClient(gw_bad)
    r = c4.call("x")
    print(f"[4] call() 不抛，返回三态：ok={r.ok} kind={r.error_kind!r} not_checked={r.not_checked}")
    if r.ok:
        problems.append("空 choices 应当判失败")

    print("=" * 72)
    if problems:
        for p in problems:
            print(f"[!!] {p}")
        return 1
    print("自检通过：5 条全过")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手跑入口
    raise SystemExit(selftest())
