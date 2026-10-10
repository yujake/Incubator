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

## key 从哪来（2026-10-07 所有者的新裁定）

改前的口径逐字是一句反问："为什么不从配置文件读：密钥一旦落盘就会进版本库与备份"。
所有者 2026-10-07 裁定改这条：填 key 与"工具链在哪"合并进同一个机器级设置文件
`settings.json`（见 :mod:`agentflow.settings`）——理由是"机器相关的事实不该散在
两个地方，且每次跑之前都靠人 export 一遍环境变量，是这台机器上最容易做错的一步"。

取值顺序（唯一口径，逐字写在 :mod:`agentflow.settings` 里）：

    环境变量 > 设置文件 > 内置默认

落盘的代价由三道新安全阀一起承担（改这条时必须一起读）：

1. 真正的 `agentflow/settings.json` 「被 git 忽略」（`.gitignore` 里逐字写着理由）；
2. 入库的是示例 `agentflow/settings.example.json`，其中 `api_key` 是空串
   （示例里不许有任何真 key）；
3. 「任何打印/读数都不回显 key」：台面上只出现 `ModelSpec.redacted()` 给的
   `"***"`，或"配没配"这一个布尔位。`spec_from_env` 是 key 的唯一入口，
   它自己不打印任何东西；下游要写日志就写 `redacted()`。

三条各配正控与负控，判据在 `tests/test_settings.py`。

## key 从哪一档取到的，是一个读数（2026-10-10 所有者裁定）

所有者当轮的两句是："key 从 config 里面接" / "我是说我们系统的 key 在 config 里面设置的"。
梯子本身没改（逐字仍是 `环境变量 > 设置文件 > 内置默认`）—— 这一批补的是
`ModelSpec.key_source`：`"env"` / `"settings"` / 空串。

为什么它必须存在：没有它，"我以为它在 config 里"与"它其实来自一个残留的环境变量"
在其余所有读数上完全一样（`configured` 都是 `True`、请求都发得出去、钱都照花）。
唯一的区别是这一格。少了它，`settings.json` 写错了也不会有人发现。

同一批还把跑批入口 `temp/_run_T.ps1` 里那段"从 `~/.dsh/.credentials.yaml` 正则刮一个
key 再 export 成 `AGENTFLOW_MODEL_API_KEY`"的接线删了：它让每一趟的 key 都来自环境变量，
而 config 里那份根本没人读。现在那一趟不设任何 key 环境变量，并在开跑前打出来源读数
（`temp/_key_source_check.ps1` 是同一段判据的单跑版）。真机对照（本机，2026-10-10）：

    干净环境                spec.redacted() → key_source='settings'
    export 一个残留 key 后   spec.redacted() → key_source='env'

## 推理强度（2026-10-10 所有者裁定）

所有者的原话是两句，先后落在同一件事上：

    现在每个智能体都会 thinking 吗？感觉像不怎么过脑子的。特别是做研究的 D 和 F。
    所有智能体都要能 thinking，且开默认到 High。

改前的读数是"确实没过脑子"，而且这个事实在网线上只有一行证据：`_payload` 的请求体里
没有 `reasoning_effort` 这一栏，回复里的 `reasoning_content` 也从没被读过
（全仓 grep `reasoning` 零命中）。改后：

- 词表 `REASONING_EFFORTS`（`off | low | high | max`）与缺省
  `DEFAULT_REASONING_EFFORT`（`high`）都在这里，唯一来源；
- 取值梯子与 key 同一条（环境变量 `AGENTFLOW_MODEL_REASONING_EFFORT` >
  `settings.json` 的 `model.reasoning_effort` > 内置默认 High）；
- 形状由 `reasoning_body_fields` 一处决定，逐字对齐 DSH 的
  `dsh-llm-deepseek`（`off` 发 `thinking: {type: disabled}`，其余三档发
  `reasoning_effort`）；
- 回复里的 `reasoning_content` 收进 `ModelReply.reasoning`，`to_dict()` 报
  `reasoning_chars` —— "这一趟想了吗"从此是一个读数，而不是一句印象。

真机对照（`temp/_thinking_probe.py`，`deepseek-chat`，同一条 prompt）：

    裸调                        200 reasoning_chars=absent tokens_in=13 tokens_out=1
    reasoning_effort=high       200 reasoning_chars=76     tokens_in=39 tokens_out=30
    thinking={type: disabled}   200 reasoning_chars=absent tokens_in=13 tokens_out=1
    reasoning_effort=medium     200 reasoning_chars=101    tokens_in=39 tokens_out=36

第三行说明 `off` 那条形状端点也认；第四行是词表外取值照样 200 ——
端点不拦，所以拦的必须是客户端（见 `normalize_reasoning_effort`）。

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

#: 用途归口的受控词表。只有一处定义（`schema.USAGE_SCOPES`）：本模块 import 它，
#: 不另写一份。两处各写一份的话，"哪些归口合法"会有两个答案，
#: 而漂移的症状是"网关接受了一个账本层会拒的值"（或反过来）—— 两边都不报错。
from .schema import USAGE_SCOPES

#: 机器级设置文件：key / base_url / name 的第二档（`settings.json`）。
#: 取值口径只有一处（`settings.env_or_setting`），理由见模块 docstring 的
#: 「key 从哪来」那一节。
from . import settings as SET

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
ENV_EFFORT = "AGENTFLOW_MODEL_REASONING_EFFORT"

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

#: 推理强度词表（唯一来源）。逐字对齐 DSH 的 `dsh-llm-deepseek`：
#: 它的 README 把 `reasoningEffort` 的取值面写成 `off | low | high | max`，
#: 于是这里不许自创第二套拼写。
#:
#: 为什么照抄它的词表而不是自己定一套（2026-10-10 读 `dsh-llm-deepseek/README.zh.md`）：
#: 那一份已经被真机跑过，且它写明了两条协议细节 —— `low`/`high`/`max` 以
#: `reasoning_effort` 序列化，`off` 则发 `thinking: {type: disabled}` 并省略
#: `reasoning_effort`（"对拒绝未知强度取值的网关保持协议拼写有效"）。
#: 本仓的网关是同一个端点的另一个客户端，形状不一致只会制造一个没人维护的方言。
REASONING_EFFORTS: tuple[str, ...] = ("off", "low", "high", "max")

#: 缺省强度。2026-10-10 所有者裁定逐字："所有智能体都要能 thinking，且开默认到 High"。
#: 它取代改前那种"什么也不发"的形态 —— 后者在真机上的读数是"模型没想"。
DEFAULT_REASONING_EFFORT = "high"

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


def normalize_reasoning_effort(raw: Any) -> str:
    """把一处来源的强度归一成词表里的取值；空 ⇒ 缺省（High），词表外 ⇒ 当场报错。

    ## 为什么词表外的取值必须当场炸，而不是回落到缺省

    真机读数（2026-10-10，`temp/_thinking_probe.py`）：`deepseek-chat` 对
    `reasoning_effort` 的词表外取值（试了 `medium`）不报错，照样 200、照样回
    `reasoning_content`（101 字）。也就是说端点把"拼错一个字母"和"一个合法的更高档"
    当同一件事办了 —— 客户端这边若也回落成缺省，那么
    `settings.json` 里写 `"hgih"` 的效果与写 `"high"` 逐位相同，而没有任何读数说得出
    "你那个值没人认"。这正是本项目反复登记的那一类静默缺陷形态。

    所以这里与 DSH 的 `UNSUPPORTED_REASONING_EFFORT` 同一条纪律：
    在发起任何网络 I/O 之前失败。触发点放在 :meth:`ModelSpec.__post_init__`，
    于是"一个不合法的强度"根本构造不出 spec —— 比"调用时再查"更早。
    """
    text = str(raw or "").strip().lower()
    if not text:
        return DEFAULT_REASONING_EFFORT
    if text not in REASONING_EFFORTS:
        raise ValueError(
            f"reasoning_effort 必须是 {REASONING_EFFORTS} 之一（空值等价于缺省 "
            f"{DEFAULT_REASONING_EFFORT!r}），收到 {raw!r}。"
            "端点对词表外的取值不报错（真机实测：照 200 并照常返回 reasoning_content），"
            "所以这里必须自己拦 —— 否则一个拼错的强度会静默地按缺省跑"
        )
    return text


def reasoning_body_fields(effort: str) -> dict[str, Any]:
    """强度 → chat-completions 请求体里的字段（唯一实现，全仓只此一处）。

    规则逐字来自 `dsh-llm-deepseek/README.zh.md` §带 thinking 与图片的流式调用：

        `low`、`high` 与 `max` 启用 thinking 并以 `reasoning_effort` 序列化，
        适配器自有的 `off` 则发送 `thinking.type: disabled`。

    为什么 `off` 不写成 `reasoning_effort: "off"`：那句话的后半段给了理由 ——
    "对拒绝未知强度取值的网关保持协议拼写有效"（`off` 不是端点认的强度）。
    为什么默认这一档不在这里判：调用方拿到的 `effort` 已经从
    :func:`normalize_reasoning_effort` 过了一遍（`ModelSpec` 构造时），
    这里只管形状。
    """
    if effort == "off":
        return {"thinking": {"type": "disabled"}}
    if effort not in REASONING_EFFORTS:
        # 兜底：正常构造路径到不了这里（`ModelSpec.__post_init__` 已经拦过）。
        # 留着它是因为这个函数的入参是裸字符串，而"没人查的取值"必须能被看见。
        raise ValueError(f"reasoning_effort 不在词表里：{effort!r}；词表 {REASONING_EFFORTS}")
    return {"reasoning_effort": effort}


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
    #: 推理强度（词表 `REASONING_EFFORTS`，缺省 `DEFAULT_REASONING_EFFORT`）。
    #:
    #: 它取代改前那种"请求体里根本没有这一栏"的形态：真机读数（2026-10-10）
    #: `deepseek-chat` 裸调与带 `reasoning_effort=high` 的对照 —— 前者
    #: `reasoning_chars=absent`、`tokens_in=13`，后者 `reasoning_chars=76`、
    #: `tokens_in=39`。这两行就是"模型有没有过脑子"在网线上的唯一区别。
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    #: key 是从哪一档取到的：`"env"` / `"settings"` / `""`（都没取到）。
    #:
    #: ## 为什么这是一个必须存在的读数（2026-10-10 所有者裁定「key 从 config 里面接」）
    #:
    #: 取值梯子是 `环境变量 > settings.json > 内置默认`，于是"我以为它在 config 里"
    #: 与"它其实来自一个残留的环境变量"在其余所有读数上完全一样：
    #: `configured` 都是 `True`、请求都发得出去、钱都照花。唯一的区别是这个来源位。
    #: 少了它，"key 从 config 接的"就只是一句信念 —— 而 config 写错了也不会有人发现，
    #: 因为环境变量把它盖住了。`redacted()` 会带上它（来源不是密钥，可以回显）。
    #:
    #: 只有 `spec_from_env` 会填它；直接构造的 spec 是空串（= 没经过那条梯子）。
    key_source: str = ""

    def __post_init__(self) -> None:
        """构造即校验强度（唯一的拦截点，见 `normalize_reasoning_effort`）。

        为什么放在 `__post_init__` 而不是 `complete()` 里：放在调用侧的话，
        校验要穿过 `_once` 的 `try` —— 那里的 `ValueError` 会被
        `complete` 的兜底 `except Exception` 折成 `error_kind="unknown"`（"没查成"），
        于是"配置文件里写错了一个词"长得像"网络没通"。构造时炸掉则不同：
        spec 造不出来，调用方连发请求的机会都没有。
        """
        object.__setattr__(self, "reasoning_effort",
                           normalize_reasoning_effort(self.reasoning_effort))

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
            # 来源不是密钥：把"从哪一档取到的"回显出来，好让"key 在 config 里设的"
            # 这句话有一个机器读数（见 `key_source` 上面的那段）。
            "key_source": self.key_source,
            "timeout_sec": self.timeout_sec,
            "max_retries": self.max_retries,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
        }


def spec_from_env(env: Mapping[str, str] | None = None) -> ModelSpec:
    """读模型配置：环境变量 > 设置文件 > 内置默认（逐字口径见模块 docstring）。

    名字里的 `from_env` 保留（调用点有十几处，改名只会制造噪声），
    但它现在读的是两档：环境变量优先，缺席时读 `settings.json` 的 `model` 段。

    ## 为什么改了旧口径（2026-10-07 所有者裁定，逐字登记）

    改前的 docstring 逐字写着："为什么不从配置文件读：密钥一旦落盘就会进版本库与备份。
    环境变量是客户环境里最容易轮换、最容易被密钥管理系统注入的形态。"
    所有者 2026-10-07 裁定把"填 key"与"工具链在哪"合并进同一个机器级设置文件，
    理由是「机器相关的事实只该有一个落点」，且"每次跑之前先 export 一遍"
    在实践中是最常做错的一步（做错的症状是 `no_key`，而它长得像"模型不行"）。

    环境变量仍然压在最上面：CI 与既有脚本不许被这次改动弄坏。

    ## 新安全阀（落盘的代价这么堵）

    1. `agentflow/settings.json` 被 git 忽略（`.gitignore` 里逐字写理由）；
    2. 入库的是示例 `agentflow/settings.example.json`，`api_key` 是空串；
    3. 本函数不打印任何东西，下游要记日志就记 `ModelSpec.redacted()`
       （`api_key` 只以 `"***"` 出现）。key 的唯一入口就是这里，所以
       "有没有哪条路把它打出去了"只需审这一处 + 各打印点。

    设置文件坏了不吞：解析错原样抛出（带路径与行列号），
    不许折成"没配 key" —— 那会把一个要改文件的问题伪装成"模型不可用"。
    """
    src = dict(os.environ if env is None else env)
    ms = SET.model_settings(env=env)
    base_url, _ = SET.env_or_setting(ENV_BASE, ms.get("base_url", ""), env=src)
    name, _ = SET.env_or_setting(ENV_NAME, ms.get("name", ""), env=src)
    # key 与它的来源一起取：来源进 `ModelSpec.key_source`，
    # 于是"这一次的 key 到底是哪一档给的"在机器面上可查（见该字段的 docstring）。
    api_key, key_src = SET.env_or_setting(ENV_KEY, ms.get("api_key", ""), env=src)
    # 推理强度走同一条梯子（环境变量 > 设置文件 > 内置默认），
    # 第三档的"内置默认"就是 `DEFAULT_REASONING_EFFORT`（High）——
    # 所有者 2026-10-10 的裁定：「所有智能体都要能 thinking，且开默认到 High」。
    # 词表外的取值在 `ModelSpec` 构造时当场抛（见 `normalize_reasoning_effort`），
    # 不在这里吞成缺省。
    effort, _ = SET.env_or_setting(ENV_EFFORT, ms.get("reasoning_effort", ""), env=src)
    return ModelSpec(
        base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
        model=name or DEFAULT_MODEL,
        api_key=api_key,
        timeout_sec=_float_env(src, ENV_TIMEOUT, 60.0),
        max_retries=max(0, _int_env(src, ENV_RETRIES, 2)),
        reasoning_effort=effort or DEFAULT_REASONING_EFFORT,
        key_source=key_src,
    )


def key_source(env: Mapping[str, str] | None = None) -> str:
    """这次 `spec_from_env` 会从哪一档取到 key：`"env"` / `"settings"` / 空串。

    只回来源，不回值：它是给机器面用的（`webui.readers.settings_reading`），
    用来回答所有者 2026-10-10 那句"key 从 config 里面接"到底成没成立。
    为什么不回值、也不复用 `spec_from_env`：那一口会把 key 读进内存里的一个对象，
    而"只看来源"的调用方没有理由也能拿到密钥 —— 少一条通路就少一处泄漏面
    （与 `settings._masked_section` 的"key 只写不读"同一条纪律）。
    """
    src = dict(os.environ if env is None else env)
    ms = SET.model_settings(env=env)
    _value, source = SET.env_or_setting(ENV_KEY, ms.get("api_key", ""), env=src)
    return source


@dataclass(frozen=True)
class ModelReply:
    """一次调用的结局。`error_kind` 与 `ok` 必须一致，由 `_make_*` 构造。"""

    ok: bool
    text: str = ""
    #: 这次回复里的思维链原文（上游 `message.reasoning_content`），拿不到就是空串。
    #:
    #: ## 为什么它必须与 `text` 分开存
    #:
    #: 把思维链并进 `text` 会让下游（抽取、判 JSON、逐字引文回验）拿到一段
    #: 不该被当成答案的散文；把它丢掉则会让"这次到底想没想"不可回答 ——
    #: 而所有者 2026-10-10 的那句"感觉像不怎么过脑子"要的正是这个读数。
    #: 所以它单独一栏，且 `to_dict()` 只报字数（原文会随每次调用膨胀，
    #: 与 `tool_call_list` 不进 `to_dict()` 同一条纪律）。
    reasoning: str = ""
    error_kind: str = ""
    error_detail: str = ""
    http_status: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    attempts: int = 1
    elapsed_sec: float = 0.0
    model: str = ""
    #: 这次回复里的结构化工具调用（`tool_calls`），逐条 `{"id","name","arguments"}`。
    #:
    #: 为什么要有它（`draft/37` §49：读 DSH 的源码之后按它的做法改）：原生工具调用把
    #: 工具名放在传输层的结构化字段里，模型不必把调用"序列化成一行 JSON"——
    #: 那正是第三趟真机 `bad_json_limit` 的病因（模型把 `tool` 写成 `name`）。
    #: `arguments` 保持文本（与上游一致，不在这里解析）：解析与校验交给工具层，
    #: 与 DSH 的 `parseArguments`（坏 JSON 原样留着）+ `validateArgs`（`INVALID_ARGS`）
    #: 同一条纪律。
    tool_calls: tuple[dict[str, Any], ...] = ()
    #: 这次调用属于哪个用途（`USAGE_SCOPES` 之一）。必填，见 `complete` 的说明。
    #: 它随结局一起回传，因此"这次花了钱"与"这笔钱是为了什么"在同一条记录里，
    #: 不依赖调用方在记账时再回忆一遍（回忆就会写错，而写错是静默的）。
    scope: str = ""

    @property
    def not_checked(self) -> bool:
        """这次是"没查成"而不是"查了失败"。下游据此决定要不要再试。"""
        return (not self.ok) and self.error_kind in NOT_CHECKED

    def to_dict(self) -> dict[str, Any]:
        """落台账用的扁平结构（含三态标记，避免下游自己推）。"""
        return {
            "ok": self.ok,
            "text_len": len(self.text),
            # "它想了吗"：0 与"这一栏不存在"必须分得开 —— 改前是后者，
            # 于是"没配 thinking"与"配了但它没想"在读数上长得一样。
            "reasoning_chars": len(self.reasoning),
            "error_kind": self.error_kind,
            "error_detail": self.error_detail,
            "http_status": self.http_status,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "attempts": self.attempts,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "model": self.model,
            "not_checked": self.not_checked,
            "scope": self.scope,
            "tool_calls": len(self.tool_calls),
        }


def _reply_failure(kind: str, detail: str, *, status: int = 0, attempt: int = 1,
                   elapsed: float = 0.0, model: str = "", scope: str = "") -> ModelReply:
    """构造一个失败/没查成的结局（唯一构造点，防止 ok 与 error_kind 不一致）。"""
    assert kind in MODEL_ERROR_KINDS, f"未登记的 error_kind：{kind!r}"
    return ModelReply(ok=False, error_kind=kind, error_detail=detail,
                      http_status=status, attempts=attempt, elapsed_sec=elapsed,
                      model=model, scope=scope)


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

    `Request(...)` 的构造放在 `try` 里面（`G-7` 口径一）：此前它建在
    `try` 之外，于是 `AGENTFLOW_MODEL_BASE_URL` 写成 `not-a-url` 时
    `urllib.request.Request` 抛的 `ValueError` 绕过本函数全部的错误翻译，
    直接冒到调用方 —— 用它的人拿到的是一条崩溃，而不是一条"没查成"。
    挪进来之后，能翻译的（`URLError` 家族）走下面那两条 `except`；
    翻译不了的一律由 `ModelGateway.complete` 的兜底收口成 `error_kind="unknown"`
    （属"没查成"）。刻意不把 `ValueError` 翻成 `ConnectionError`：配置错不是网络故障，
    把两者折叠会让排障的人去查网络。
    """
    try:
        req = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
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
                 max_tokens: int | None, tools: Sequence[Mapping[str, Any]] | None = None,
                 tool_choice: str = "auto") -> bytes:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {
            "model": self.spec.model,
            "messages": messages,
            "temperature": self.spec.temperature if temperature is None else temperature,
            "max_tokens": self.spec.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
            # 推理强度：唯一实现在 `reasoning_body_fields`（`off` 发 thinking.type=disabled，
            # 其余三档发 reasoning_effort）。改前这里没有这一栏 ——
            # 那正是"模型不过脑子"在网线上的成因。
            **reasoning_body_fields(self.spec.reasoning_effort),
        }
        if tools:
            # 原生工具面：与 DSH 的请求形状一致（`dsh-llm-deepseek` 也是把
            # `tools` 原样放进 chat-completions 的 body）。
            body["tools"] = list(tools)
            body["tool_choice"] = tool_choice
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.spec.api_key}",
            "User-Agent": "agentflow/1.0 (model-gateway)",
        }

    # ---------------------------------------------------------------- 单次调用

    def _once(self, prompt: str, system: str | None, temperature: float | None,
              max_tokens: int | None, attempt: int, scope: str,
              tools: Sequence[Mapping[str, Any]] | None = None,
              tool_choice: str = "auto") -> ModelReply:
        url = f"{self.spec.base_url}/chat/completions"
        started = self._clock()
        try:
            status, raw = self._transport(
                url, self._headers(),
                self._payload(prompt, system, temperature, max_tokens, tools, tool_choice),
                self.spec.timeout_sec)
        except TimeoutError:
            return _reply_failure("timeout", f"超过 {self.spec.timeout_sec}s 未返回",
                                  attempt=attempt, elapsed=self._clock() - started,
                                  model=self.spec.model, scope=scope)
        except ConnectionError as exc:
            return _reply_failure("network", str(exc), attempt=attempt,
                                  elapsed=self._clock() - started, model=self.spec.model,
                                  scope=scope)
        elapsed = self._clock() - started

        kind = _classify_status(status)
        if kind:
            return _reply_failure(kind, raw.strip()[:400] or f"HTTP {status}", status=status,
                                  attempt=attempt, elapsed=elapsed, model=self.spec.model,
                                  scope=scope)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # 上游返回的不是 JSON：多半是代理页或网关错误页，必须与"模型答错"分开报
            return _reply_failure("bad_response", f"响应不是 JSON（{exc}）：{raw.strip()[:200]}",
                                  status=status, attempt=attempt, elapsed=elapsed,
                                  model=self.spec.model, scope=scope)

        choices = data.get("choices") if isinstance(data, dict) else None
        content = ""
        reasoning = ""
        calls: list[dict[str, Any]] = []
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first.get("message"), dict) else {}
            content = message.get("content") if isinstance(message.get("content"), str) else ""
            # 思维链：上游在开了 thinking 的调用里给 `reasoning_content`
            # （真机读数 2026-10-10：`reasoning_effort=high` ⇒ 76 字，裸调 ⇒ 这一栏不在）。
            # 它不是答案，所以只在这里分开收着，绝不并进 `content`。
            reasoning = (message.get("reasoning_content")
                         if isinstance(message.get("reasoning_content"), str) else "")
            raw_calls = message.get("tool_calls")
            if isinstance(raw_calls, list):
                for item in raw_calls:
                    if not isinstance(item, Mapping):
                        continue
                    fn = item.get("function") if isinstance(item.get("function"), Mapping) else {}
                    name = str(fn.get("name") or "")
                    if not name:
                        continue
                    argv = fn.get("arguments")
                    calls.append({"id": str(item.get("id") or ""), "name": name,
                                  # `arguments` 保持文本（上游就是这样给的）：
                                  # 解析与校验交给工具层，坏 JSON 不许在这里被"洗白"。
                                  "arguments": argv if isinstance(argv, str)
                                  else json.dumps(argv, ensure_ascii=False)})
        if not content.strip() and not calls:
            # 空内容绝不许当成成功：下游会把"没答"读成"答了"。
            # 但有原生工具调用时 content 本来就可以是空的（DSH 那条路上就是这样），
            # 所以这一条判据从"content 非空"改成"content 或 tool_calls 至少有一个"。
            #
            # 这一条还必须报出"它到底想没想"（2026-10-10）：想了 500 字却一个字没答，
            # 与什么都没想，是两种不同的病因（前者是输出被截断/协议漂移，后者是没开 thinking）
            # —— 折成同一句话会让排障的人去查错方向。
            return _reply_failure("bad_response",
                                  "上游返回空内容（choices/message/content 缺失或为空，"
                                  f"且没有 tool_calls；思维链 {len(reasoning)} 字）："
                                  f"{raw.strip()[:200]}",
                                  status=status, attempt=attempt, elapsed=elapsed,
                                  model=self.spec.model, scope=scope)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return ModelReply(
            ok=True, text=content,
            reasoning=reasoning,
            tool_calls=tuple(calls),
            http_status=status,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            attempts=attempt, elapsed_sec=elapsed, model=self.spec.model,
            scope=scope,
        )

    # ---------------------------------------------------------------- 对外入口

    def complete(self, prompt: str, *, scope: str, system: str | None = None,
                 temperature: float | None = None,
                 max_tokens: int | None = None,
                 tools: Sequence[Mapping[str, Any]] | None = None,
                 tool_choice: str = "auto") -> ModelReply:
        """调一次模型。返回三态结局，从不抛异常（异常会让上游编排层的三态判定失效）。

        ## "从不抛异常"是怎么做到的（`G-7` 口径一）

        缺陷（2026-09-26 全面体检 · 子代理 G 实测，`temp/auditG-probe1.txt` P6 段）：
        改前这句话不成立 —— `_once` 只捕 `TimeoutError` / `ConnectionError`，
        传输层抛 `ValueError` / `KeyError` / `ssl.SSLError` 都会原样穿出去，
        而调用方按这句话不写 `try` ⇒ 一个配置错误（`AGENTFLOW_MODEL_BASE_URL` 写错）
        让整条 run 崩在调用上：产物一件不写、账本一行没有、熔断完全不生效，
        而"没查成"与"代码崩了"在下游无法区分。

        现在 `_once` 外面套了一层 `except Exception`，把它归成
        `error_kind="unknown"`（在 `NOT_CHECKED` 里 ⇒ 属于"没查成"，退出三态走"没查成"）；
        `urllib_transport` 也把 `Request(...)` 的构造挪进了自己的 `try`。
        唯一仍然会抛的是调用方自己传错 `scope`（下一节）：那是编码错误，
        必须当场可见，而不是被静默折成一条"没查成"的模型结局。

        ## `scope` 是必填的关键字参数（G-20）

        它回答"这次调用是为了什么"，取值只能在 `USAGE_SCOPES` 里。
        为什么必填、且没有缺省值：

        - 有缺省值时，任何忘记传的调用点都会静默落进那一档。账本看起来完全自洽
          （总额对、条目数对），只是"搜索/抽取/审校各花了多少"这个问题永远答不出来
          —— 这正是 G-20 登记的缺陷形态：`USAGE_SCOPES` 五档全无产出，
          因为当时唯一的记账入口 `modelcost.charge_reply` 的 `scope` 缺省是 `"reason"`。
        - 缺省也不许是"其它"：一个"其他"档会把"有人忘了写"伪装成一个正常的分类。

        代价是每一个新增调用点都必须想清楚自己是哪一档 —— 那正是要它承担的。
        `scope` 会随 `ModelReply` 回传，所以记账时不必再回忆一遍。
        """
        if scope not in USAGE_SCOPES:
            raise ValueError(
                f"scope 必须是 {USAGE_SCOPES} 之一，收到 {scope!r} —— "
                "它是这次调用的用途归口（缺省值会让忘记传的调用点静默落进某一档，"
                "而账本仍然自洽）"
            )
        if not self.spec.configured:
            return _reply_failure(
                "no_key",
                f"环境变量 {ENV_KEY} 与设置文件 {SET.DEFAULT_SETTINGS_REL} 的 model.api_key "
                "都没有值 ⇒ 本次**没有调用模型**（这是没查成，不是失败）",
                scope=scope,
            )
        if not str(prompt or "").strip():
            return _reply_failure("bad_response", "空 prompt ⇒ 拒绝发起调用（省一次必然失败的钱）",
                                  scope=scope)

        attempt = 0
        last: ModelReply | None = None
        while attempt <= self.spec.max_retries:
            attempt += 1
            try:
                reply = self._once(prompt, system, temperature, max_tokens, attempt, scope,
                                   tools, tool_choice)
            except Exception as exc:  # noqa: BLE001 —— 见 docstring：兜底成"没查成"
                # `G-7` 口径一：`_once` 只翻译 `TimeoutError` / `ConnectionError`，
                # 别的异常（传输层实现抛的 `ValueError`、`ssl.SSLError`、
                # 第三方 transport 的任意异常）此前会直接穿出本方法 ——
                # 而 docstring 承诺"从不抛异常"，调用方也就不会去接。
                #
                # 兜底成 `unknown`：它在 `NOT_CHECKED` 里（属于"没查成"），
                # 且不在 `RETRYABLE` 里 —— 所以下面的循环会立刻把它返回，
                # 不会拿一个连接都没建起来的配置错误去重试三次。
                # 归成 `unknown` 而不是 `network`：配置错不是网络故障，
                # 折叠两者会让排障的人去查网络。
                reply = _reply_failure(
                    "unknown",
                    f"网关内部抛出了 {type(exc).__name__}：{exc}"
                    "（`ModelGateway.complete` 承诺从不抛异常；这一条是兜底，"
                    "它记的是『这次没查成』，不是模型答错）",
                    attempt=attempt, model=self.spec.model, scope=scope,
                )
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


def _ok_body(text: str = "4", tokens_in: int = 11, tokens_out: int = 3,
             reasoning: str = "") -> str:
    """OpenAI 兼容的成功应答（含 usage；`reasoning` 非空时带上思维链那一栏）。"""
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if reasoning:
        message["reasoning_content"] = reasoning
    return json.dumps({
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
    }, ensure_ascii=False)


def _grab_transport(seen: list[dict[str, Any]], body: str) -> Transport:
    """造一个"把请求体记下来再回固定应答"的传输层（自检看请求形状用）。"""

    def _t(url: str, headers: Mapping[str, str], data: bytes, timeout_sec: float) -> tuple[int, str]:
        seen.append(json.loads(data.decode("utf-8")))
        return 200, body

    return _t


def selftest() -> int:
    """三条路径各验一次：没配 key / 成功 / 认证失败。退出码 0 / 1 / 2。"""
    problems: list[str] = []

    no_key = ModelGateway(ModelSpec(api_key=""), transport=_fake_transport(200, _ok_body()))
    r1 = no_key.complete("1+1=?", scope="reason")
    if r1.ok or r1.error_kind != "no_key" or not r1.not_checked:
        problems.append(f"没配 key 时的结局不对：{r1.to_dict()}")

    good = ModelGateway(ModelSpec(api_key="k"), transport=_fake_transport(200, _ok_body("4")))
    r2 = good.complete("1+1=?", scope="reason")
    if not r2.ok or r2.text != "4" or r2.tokens_in != 11 or r2.not_checked:
        problems.append(f"成功路径的结局不对：{r2.to_dict()}")
    if r2.scope != "reason":
        problems.append(f"scope 必须随结局回传：{r2.scope!r}")

    bad = ModelGateway(ModelSpec(api_key="k", max_retries=0),
                       transport=_fake_transport(401, '{"error":"invalid api key"}'))
    r3 = bad.complete("1+1=?", scope="reason")
    if r3.ok or r3.error_kind != "auth_failed" or r3.not_checked:
        problems.append(f"认证失败的结局不对：{r3.to_dict()}")

    # 负控：不传 scope / 传一个词表外的值 ⇒ 当场拒绝（不许静默落档）。
    for label, call in (
        ("不传 scope", lambda: good.complete("1+1=?")),
        ("scope 不在词表里", lambda: good.complete("1+1=?", scope="不是范围")),
    ):
        try:
            call()
        except TypeError:
            continue  # 必填参数没给 ⇒ TypeError，正是想要的那种"当场报错"
        except ValueError:
            continue
        problems.append(f"负控：{label} 必须当场报错，不许静默落进某一档")

    # 第四段：推理强度（2026-10-10 所有者裁定「所有智能体都要能 thinking，默认 High」）。
    # 这一段刻意读请求体而不是读 `spec.reasoning_effort`：后者只能证明"想让它开"，
    # 只有前者能证明"真的发出去的请求上有这一栏"（改前缺的正是这一栏）。
    seen: list[dict[str, Any]] = []
    thought = ModelGateway(ModelSpec(api_key="k"),
                           transport=_grab_transport(seen, _ok_body("4", reasoning="一加一等于二。")))
    r4 = thought.complete("1+1=?", scope="reason")
    if not seen or seen[0].get("reasoning_effort") != DEFAULT_REASONING_EFFORT:
        problems.append(f"缺省强度必须进请求体（期望 {DEFAULT_REASONING_EFFORT!r}）："
                        f"{seen[0] if seen else '没有发出请求'}")
    if r4.reasoning != "一加一等于二。" or r4.to_dict()["reasoning_chars"] != 7:
        problems.append(f"回复里的思维链必须被收下来并报出字数：{r4.to_dict()}")

    quiet = ModelGateway(ModelSpec(api_key="k", reasoning_effort="off"),
                         transport=_grab_transport(seen, _ok_body("4")))
    quiet.complete("1+1=?", scope="reason")
    if seen[-1].get("thinking") != {"type": "disabled"} or "reasoning_effort" in seen[-1]:
        problems.append(f"off 必须序列化成 thinking.type=disabled 且不发 reasoning_effort：{seen[-1]}")

    try:
        ModelSpec(reasoning_effort="medium")
    except ValueError:
        # 这一档正是期望的结局：词表外的强度必须当场被拒。
        # 这里不记问题，由下面的 `else` 分支负责报"它居然过了"。
        pass
    else:
        problems.append("负控：词表外的强度必须在构造 spec 时就炸"
                        "（端点对词表外取值照 200，客户端不拦就没有任何读数）")

    for p in problems:
        print(f"  [FAIL] {p}")
    print(f"[modelgw] 自检：没配 key={r1.error_kind} / 成功={r2.ok} / 认证={r3.error_kind}"
          f" / 强度={thought.spec.reasoning_effort}"
          f"（想 {r4.to_dict()['reasoning_chars']} 字）")
    if problems:
        return 1
    print("[modelgw] 三条路径的结局都正确（三态没有折叠）")
    return 0


def live_smoke() -> int:
    """真调一次（需要环境里有 key）。退出码 0 成功 / 1 失败 / 2 没查成。"""
    spec = spec_from_env()
    gw = ModelGateway(spec)
    reply = gw.complete("只回答一个数字：1+1=?", scope="reason")
    print(f"[modelgw] live：{reply.to_dict()}")
    print(f"[modelgw] 配置（key 已脱敏）：{spec.redacted()}")
    # 这一行是"模型过没过脑子"的直读（2026-10-10 所有者裁定的验收面）：
    # 强度 0 字思维链 = 请求发出去了但它没想，先查强度而不是先查模型。
    print(f"[modelgw] 思考读数：强度={spec.reasoning_effort} / "
          f"思维链 {len(reply.reasoning)} 字 / 答案 {len(reply.text)} 字")
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
