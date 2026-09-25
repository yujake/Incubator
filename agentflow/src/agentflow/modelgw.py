"""模型网关：provider 无关的模型调用层，全仓唯一读 API key 的地方。

## 为什么需要它（这是本轮最致命的一条缺口）

在本文件出现之前，全仓 `src/agentflow` 里 grep `API_KEY` / `api_key` / `httpx` /
`base_url` 0 命中 —— 也就是说 A–H 八个角色从来没有真正调用过模型。
这一层是让它们开始思考的唯一入口；没有它，其余所有设计（角色、管理层、工具箱）
都只是在描述一个不会思考的系统。

## 为什么用标准库而不是 httpx / openai SDK

`pyproject.toml` 的运行期依赖刻意只有 `filelock`：核心能在任何环境被复核。
网关是最该保持这个性质的地方 —— 它必须能在客户的离线或受限网络里跑。
于是 HTTP 用 `urllib.request`，JSON 用标准库，超时与重试自己实现。

## 三态纪律（本文件的核心）

一次调用有三种结局，绝不许折叠：

1. 成功：`ok=True`，`text` 非空，`usage` 有数；
2. 失败：`ok=False`，`error_kind` 是"查过了、确实不行"（如 `auth_failed`、`bad_response`）；
3. 没查成：`ok=False`，`error_kind` 在 `NOT_CHECKED` 里（`no_key` / `timeout` / `network` /
   `server_error` / `unknown`）—— "没查成"与"查了失败"必须能分辨。

把第 3 类读成第 2 类，会让"key 没配好"看起来像"模型答错了"；反过来，
把第 3 类读成成功，就是本项目反复记过的那种最贵的错误。

## 测试怎么在没有 key、没有网络的情况下跑

`ModelGateway(transport=...)` 注入传输层：生产用 `urllib_transport`，
测试用假传输。于是每一条失败路径都能配一条负控，而套件保持离线、确定性、可重复。

## 自检

    python -m agentflow.modelgw            # 用假传输跑三态，退出码 0 / 1 / 2
    AGENTFLOW_MODEL_API_KEY=... python -m agentflow.modelgw --live   # 真调一次
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

#: 失败与"没查成"的受控词表（唯一来源；下游只许判这些值）。
MODEL_ERROR_KINDS: tuple[str, ...] = (
    "no_key",         # 环境里没有 key —— 没查成
    "auth_failed",    # 401/403：key 无效或无权 —— 查过了，确定不行
    "rate_limited",   # 429
    "timeout",        # 读取或连接超时 —— 没查成
    "network",        # DNS / 连接被拒 / 证书等 —— 没查成
    "bad_response",   # 响应不是预期的 JSON / 缺字段 / 内容为空
    "server_error",   # 5xx —— 没查成
    "unknown",        # 其余状态码 —— 没查成
)

#: 这些结局属于"没查成"，不是"查了没通过"。
NOT_CHECKED: frozenset[str] = frozenset({"no_key", "timeout", "network", "server_error", "unknown"})

#: 值得重试的结局（auth_failed 与 bad_response 不重试：重试不会让它变好）。
RETRYABLE: frozenset[str] = frozenset({"rate_limited", "timeout", "network", "server_error"})

ENV_KEY = "AGENTFLOW_MODEL_API_KEY"
ENV_BASE = "AGENTFLOW_MODEL_BASE_URL"
ENV_NAME = "AGENTFLOW_MODEL_NAME"
ENV_TIMEOUT = "AGENTFLOW_MODEL_TIMEOUT_SEC"
ENV_RETRIES = "AGENTFLOW_MODEL_MAX_RETRIES"

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

#: 传输层的签名：`(url, headers, body, timeout_sec) -> (http_status, text)`。
Transport = Callable[[str, Mapping[str, str], bytes, float], "tuple[int, str]"]


def _float_env(env: Mapping[str, str], name: str, default: float) -> float:
    """读一个浮点环境变量；读不出来就用默认值（并不静默改成 0）。"""
    raw = str(env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    """读一个整数环境变量；读不出来就用默认值。"""
    raw = str(env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class ModelSpec:
    """一次调用的静态配置（全部来自环境变量，代码里不写死任何密钥）。"""

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = ""
    timeout_sec: float = 60.0
    max_retries: int = 2
    temperature: float = 0.2
    max_tokens: int = 4096

    @property
    def configured(self) -> bool:
        """key 是否配了。没配时网关不发起任何网络请求。"""
        return bool(self.api_key)

    def redacted(self) -> dict[str, Any]:
        """可安全写进日志/台账的配置快照（永不包含 key 本体）。"""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "api_key": "***" if self.api_key else "",
            "timeout_sec": self.timeout_sec,
            "max_retries": self.max_retries,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


def spec_from_env(env: Mapping[str, str] | None = None) -> ModelSpec:
    """从环境变量读配置。

    为什么不从配置文件读：密钥一旦落盘就会进版本库与备份。
    环境变量是客户环境里最容易轮换、最容易被密钥管理系统注入的形态。
    """
    src = dict(os.environ if env is None else env)
    return ModelSpec(
        base_url=str(src.get(ENV_BASE) or DEFAULT_BASE_URL).rstrip("/"),
        model=str(src.get(ENV_NAME) or DEFAULT_MODEL),
        api_key=str(src.get(ENV_KEY) or "").strip(),
        timeout_sec=_float_env(src, ENV_TIMEOUT, 60.0),
        max_retries=max(0, _int_env(src, ENV_RETRIES, 2)),
    )


@dataclass(frozen=True)
class ModelReply:
    """一次调用的结局。`error_kind` 与 `ok` 必须一致，由 `_make_*` 构造。"""

    ok: bool
    text: str = ""
    error_kind: str = ""
    error_detail: str = ""
    http_status: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    attempts: int = 1
    elapsed_sec: float = 0.0
    model: str = ""

    @property
    def not_checked(self) -> bool:
        """这次是"没查成"而不是"查了失败"。下游据此决定要不要再试。"""
        return (not self.ok) and self.error_kind in NOT_CHECKED

    def to_dict(self) -> dict[str, Any]:
        """落台账用的扁平结构（含三态标记，避免下游自己推）。"""
        return {
            "ok": self.ok,
            "text_len": len(self.text),
            "error_kind": self.error_kind,
            "error_detail": self.error_detail,
            "http_status": self.http_status,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "attempts": self.attempts,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "model": self.model,
            "not_checked": self.not_checked,
        }


def _reply_failure(kind: str, detail: str, *, status: int = 0, attempt: int = 1,
                   elapsed: float = 0.0, model: str = "") -> ModelReply:
    """构造一个失败/没查成的结局（唯一构造点，防止 ok 与 error_kind 不一致）。"""
    assert kind in MODEL_ERROR_KINDS, f"未登记的 error_kind：{kind!r}"
    return ModelReply(ok=False, error_kind=kind, error_detail=detail,
                      http_status=status, attempts=attempt, elapsed_sec=elapsed, model=model)


def _classify_status(status: int) -> str:
    """HTTP 状态码到受控结局的映射；2xx 返回空串表示"进入解析阶段"。"""
    if 200 <= status < 300:
        return ""
    if status in (401, 403):
        return "auth_failed"
    if status == 429:
        return "rate_limited"
    if 500 <= status < 600:
        return "server_error"
    if status in (400, 404, 405, 413, 422):
        return "bad_response"
    return "unknown"


def urllib_transport(url: str, headers: Mapping[str, str], body: bytes,
                     timeout_sec: float) -> tuple[int, str]:
    """生产传输层：标准库 HTTP。

    非 2xx 也读回响应体（上游的报错正文里才有真正的原因，
    直接抛异常会把原因丢掉，只剩一个状态码）。
    """
    req = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            return int(getattr(resp, "status", 200)), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        with exc:
            raw = exc.read().decode("utf-8", "replace") if hasattr(exc, "read") else ""
        return int(exc.code), raw
    except urllib.error.URLError as exc:
        # URLError 覆盖 DNS 失败、连接被拒、证书错误、超时（socket.timeout 会被它包住）
        raise ConnectionError(f"{type(exc.reason).__name__}: {exc.reason}") from exc


class ModelGateway:
    """一次调用的执行者：组请求 → 过传输 → 解析 → 三态结局。

    刻意不碰 store / 台账：网关保持纯函数式（除了传输与 sleep），
    记账由调用方用既有 `tokenmeter` 做 —— 这样网关可以在没有工作区的情况下单测。
    """

    def __init__(self, spec: ModelSpec, *, transport: Transport | None = None,
                 sleep: Callable[[float], None] | None = None,
                 clock: Callable[[], float] | None = None) -> None:
        self.spec = spec
        self._transport = transport or urllib_transport
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic

    # ---------------------------------------------------------------- 请求组装

    def _payload(self, prompt: str, system: str | None, temperature: float | None,
                 max_tokens: int | None) -> bytes:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": self.spec.model,
            "messages": messages,
            "temperature": self.spec.temperature if temperature is None else temperature,
            "max_tokens": self.spec.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.spec.api_key}",
            "User-Agent": "agentflow/1.0 (model-gateway)",
        }

    # ---------------------------------------------------------------- 单次调用

    def _once(self, prompt: str, system: str | None, temperature: float | None,
              max_tokens: int | None, attempt: int) -> ModelReply:
        url = f"{self.spec.base_url}/chat/completions"
        started = self._clock()
        try:
            status, raw = self._transport(url, self._headers(),
                                          self._payload(prompt, system, temperature, max_tokens),
                                          self.spec.timeout_sec)
        except TimeoutError:
            return _reply_failure("timeout", f"超过 {self.spec.timeout_sec}s 未返回",
                                  attempt=attempt, elapsed=self._clock() - started,
                                  model=self.spec.model)
        except ConnectionError as exc:
            return _reply_failure("network", str(exc), attempt=attempt,
                                  elapsed=self._clock() - started, model=self.spec.model)
        elapsed = self._clock() - started

        kind = _classify_status(status)
        if kind:
            return _reply_failure(kind, raw.strip()[:400] or f"HTTP {status}", status=status,
                                  attempt=attempt, elapsed=elapsed, model=self.spec.model)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # 上游返回的不是 JSON：多半是代理页或网关错误页，必须与"模型答错"分开报
            return _reply_failure("bad_response", f"响应不是 JSON（{exc}）：{raw.strip()[:200]}",
                                  status=status, attempt=attempt, elapsed=elapsed,
                                  model=self.spec.model)

        choices = data.get("choices") if isinstance(data, dict) else None
        content = ""
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first.get("message"), dict) else {}
            content = message.get("content") if isinstance(message.get("content"), str) else ""
        if not content.strip():
            # 空内容绝不许当成成功：下游会把"没答"读成"答了"
            return _reply_failure("bad_response",
                                  "上游返回空内容（choices/message/content 缺失或为空）"
                                  f"：{raw.strip()[:200]}",
                                  status=status, attempt=attempt, elapsed=elapsed,
                                  model=self.spec.model)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return ModelReply(
            ok=True, text=content,
            http_status=status,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            attempts=attempt, elapsed_sec=elapsed, model=self.spec.model,
        )

    # ---------------------------------------------------------------- 对外入口

    def complete(self, prompt: str, *, system: str | None = None,
                 temperature: float | None = None,
                 max_tokens: int | None = None) -> ModelReply:
        """调一次模型。返回三态结局，从不抛异常（异常会让上游编排层的三态判定失效）。"""
        if not self.spec.configured:
            return _reply_failure(
                "no_key",
                f"环境变量 {ENV_KEY} 未设置 ⇒ 本次**没有调用模型**（这是没查成，不是失败）",
            )
        if not str(prompt or "").strip():
            return _reply_failure("bad_response", "空 prompt ⇒ 拒绝发起调用（省一次必然失败的钱）")

        attempt = 0
        last: ModelReply | None = None
        while attempt <= self.spec.max_retries:
            attempt += 1
            reply = self._once(prompt, system, temperature, max_tokens, attempt)
            if reply.ok or reply.error_kind not in RETRYABLE:
                return reply
            last = reply
            if attempt <= self.spec.max_retries:
                # 指数退避：429/5xx/网络抖动重试有意义，401 与格式错重试没有意义
                self._sleep(float(2 ** (attempt - 1)))
        assert last is not None
        return last


# ---------------------------------------------------------------------- 自检

SELFTEST_BODIES: dict[str, tuple[int, str]] = {}


def _fake_transport(status: int, body: str) -> Transport:
    """造一个固定应答的传输层（自检与测试共用同一种造法）。"""

    def _t(url: str, headers: Mapping[str, str], data: bytes, timeout_sec: float) -> tuple[int, str]:
        return status, body

    return _t


def _ok_body(text: str = "4", tokens_in: int = 11, tokens_out: int = 3) -> str:
    """OpenAI 兼容的成功应答（含 usage）。"""
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
    }, ensure_ascii=False)


def selftest() -> int:
    """三条路径各验一次：没配 key / 成功 / 认证失败。退出码 0 / 1 / 2。"""
    problems: list[str] = []

    no_key = ModelGateway(ModelSpec(api_key=""), transport=_fake_transport(200, _ok_body()))
    r1 = no_key.complete("1+1=?")
    if r1.ok or r1.error_kind != "no_key" or not r1.not_checked:
        problems.append(f"没配 key 时的结局不对：{r1.to_dict()}")

    good = ModelGateway(ModelSpec(api_key="k"), transport=_fake_transport(200, _ok_body("4")))
    r2 = good.complete("1+1=?")
    if not r2.ok or r2.text != "4" or r2.tokens_in != 11 or r2.not_checked:
        problems.append(f"成功路径的结局不对：{r2.to_dict()}")

    bad = ModelGateway(ModelSpec(api_key="k", max_retries=0),
                       transport=_fake_transport(401, '{"error":"invalid api key"}'))
    r3 = bad.complete("1+1=?")
    if r3.ok or r3.error_kind != "auth_failed" or r3.not_checked:
        problems.append(f"认证失败的结局不对：{r3.to_dict()}")

    for p in problems:
        print(f"  [FAIL] {p}")
    print(f"[modelgw] 自检：没配 key={r1.error_kind} / 成功={r2.ok} / 认证={r3.error_kind}")
    if problems:
        return 1
    print("[modelgw] 三条路径的结局都正确（三态没有折叠）")
    return 0


def live_smoke() -> int:
    """真调一次（需要环境里有 key）。退出码 0 成功 / 1 失败 / 2 没查成。"""
    spec = spec_from_env()
    gw = ModelGateway(spec)
    reply = gw.complete("只回答一个数字：1+1=?")
    print(f"[modelgw] live：{reply.to_dict()}")
    print(f"[modelgw] 配置（key 已脱敏）：{spec.redacted()}")
    if reply.ok:
        print(f"[modelgw] 模型回答：{reply.text.strip()[:120]}")
        return 0
    return 2 if reply.not_checked else 1


def gateway_main(argv: Sequence[str] | None = None) -> int:
    """入口：默认走自检，`--live` 真调一次。

    刻意不叫 `main`：`cli.main` 已经是这个包对外的唯一命令入口，
    两个同名的独立实现会命中 R003（同名不同契约）。自检入口是本模块私有的东西，
    名字里带上模块名才说得清它是谁。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if "--live" in args:
        return live_smoke()
    return selftest()


if __name__ == "__main__":
    raise SystemExit(gateway_main())
