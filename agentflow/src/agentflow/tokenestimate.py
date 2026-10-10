"""固定密度估值器：把"一段消息/内容"折成 token 数（S-B / 裁定 12-H=甲）。

## 搬的是什么

`dsh-token-meter/lib/types/estimate.js`：`CHARS_PER_TOKEN = 4`、`BLOCK_OVERHEAD = 4`、
`ROLE_OVERHEAD = 4`，每块 `ceil(len / CHARS_PER_TOKEN) + BLOCK_OVERHEAD`，
每条消息再加 `ROLE_OVERHEAD` 的角色框架；system 那一条按"文本密度 + 角色框架"、
不含逐块开销（适配器把它序列化成一段纯文本，不是带类型的块）。
常量名原样保留（`CHARS_PER_TOKEN` / `BLOCK_OVERHEAD` / `ROLE_OVERHEAD`）——
它们是别人论文/文档里能对得上的名字，改一个字母就再也对不上。

## 一处必须说清的偏差（12-H=甲 逐字要求的）

DSH 的 `4 chars/token` 对 CJK 会低估（我们的语料以中文为主：一个汉字通常约 1 个
token 甚至更多，而按 4 字符/token 算会把"一千个汉字"估成 250 token）。
所以"每 token 几个字符"是配置项（`context_budget.chars_per_token`，默认 4 与 DSH 对数，
中文语料可调小），而每一条读数里都写明用的是哪一档（`source` 那一格：
`config` / `default` / `unknown`）—— "估出来的数"与"按哪把尺估的"必须一起读，
否则两个不同档的数字摆在一起会看起来像"内容变了"。

## 三态（本仓的纪律，DSH 没有这一档）

配置里那个值读不到（不是数 / 不是正数）⇒ 返回 `(None, "unknown")`，
不许静默回退成默认值：那会让"我们按 4 估的"与"配置写错了、我们按 4 估的"长得一样。
调用方（压缩那条路）据此走"警告一次 + 带完整历史继续"，与 DSH 自动路径同一姿态。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = [
    "CHARS_PER_TOKEN",
    "BLOCK_OVERHEAD",
    "ROLE_OVERHEAD",
    "Estimate",
    "chars_per_token_from",
    "estimate_content",
    "estimate_message",
    "estimate_messages",
    "estimate_structural_block",
    "estimate_text_tokens",
    "estimate_tools_tokens",
    "selftest",
]

#: 固定的文本密度（DSH 逐字：`CHARS_PER_TOKEN = 4`）——常量名原样保留。
CHARS_PER_TOKEN = 4
#: 每一块的结构开销（JSON 框架与类型标签）。
BLOCK_OVERHEAD = 4
#: 每一条消息的角色框架开销。
ROLE_OVERHEAD = 4


def _rate(chars_per_token: float | None) -> float:
    """有效密度：没给就用 DSH 那一档；给了必须是正的有限数。"""
    if chars_per_token is None:
        return float(CHARS_PER_TOKEN)
    value = float(chars_per_token)
    if not (value > 0) or value != value:      # NaN / 0 / 负数一律拒绝
        raise ValueError(f"chars_per_token 必须是正的有限数，收到 {chars_per_token!r}")
    return value


def estimate_text_tokens(text: Any, *, chars_per_token: float | None = None) -> int:
    """一段文本的估价：`ceil(字符数 / 每 token 字符数) + BLOCK_OVERHEAD`。

    `len()` 按码点算（与 DSH 的 `.length` 同口径：JS 的 length 是 UTF-16 码元，
    中文 BMP 内一个字符 == 一个码元 ⇒ 两边对中文一致；星号平面字符会差，见 `selftest`）。
    """
    body = "" if text is None else str(text)
    rate = _rate(chars_per_token)
    return int(-(-len(body) // rate)) + BLOCK_OVERHEAD if rate else BLOCK_OVERHEAD


def estimate_structural_block(block: Any, *, chars_per_token: float | None = None) -> int:
    """不认识的块（以及图片引用）按"结构 JSON 的固定估价"（DSH 的 default 支）。

    `ensure_ascii=False`：DSH 那边 `JSON.stringify` 不转义非 ASCII —— 若我们转义，
    中文会被写成 `\\uXXXX`（每个字 6 字符），估价会凭空涨一倍。
    """
    text = json.dumps(block, ensure_ascii=False, sort_keys=True, default=str)
    return BLOCK_OVERHEAD + int(-(-len(text) // _rate(chars_per_token)))


def estimate_content(blocks: Sequence[Any] | None, *,
                     chars_per_token: float | None = None) -> int:
    """内容块数组的估价（DSH `estimateContent` 的逐支照搬）。

    块是"像 DSH 那样的带 `type` 的 mapping"时走对应支；我们的消息里块是文本
    （`{"role": "user", "content": "<str>"}`）⇒ 走 `text` 支。两种形态都收，
    因为重建出来的序列可能是任意一种。
    """
    tokens = 0
    for block in (blocks or ()):
        if isinstance(block, Mapping):
            kind = str(block.get("type") or "")
            if kind in ("text", "reasoning"):
                tokens += estimate_text_tokens(block.get("text"), chars_per_token=chars_per_token)
            elif kind == "tool-call":
                tokens += (estimate_text_tokens(block.get("name"), chars_per_token=chars_per_token)
                           + estimate_text_tokens(block.get("arguments"),
                                                  chars_per_token=chars_per_token))
            elif kind == "tool-result":
                tokens += estimate_content(block.get("content"),
                                           chars_per_token=chars_per_token) + BLOCK_OVERHEAD
            else:
                tokens += estimate_structural_block(block, chars_per_token=chars_per_token)
        else:
            tokens += estimate_text_tokens(block, chars_per_token=chars_per_token)
    return tokens


def estimate_message(message: Mapping[str, Any], *,
                     chars_per_token: float | None = None) -> int:
    """一条模型可见消息的估价（`system` 那条不含逐块开销，照 DSH）。"""
    content = message.get("content")
    if str(message.get("role") or "") == "system":
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False,
                                                                  sort_keys=True, default=str)
        if not text:
            return 0
        return int(-(-len(text) // _rate(chars_per_token))) + ROLE_OVERHEAD
    blocks = content if isinstance(content, (list, tuple)) else [content]
    tokens = estimate_content(blocks, chars_per_token=chars_per_token)
    # assistant 那条还带 `tool_calls` 与 `reasoning_content`（12-A=乙 之后思维链也进历史）
    for call in (message.get("tool_calls") or ()):
        if isinstance(call, Mapping):
            fn = call.get("function") if isinstance(call.get("function"), Mapping) else {}
            tokens += (estimate_text_tokens(fn.get("name"), chars_per_token=chars_per_token)
                       + estimate_text_tokens(fn.get("arguments"),
                                              chars_per_token=chars_per_token))
    if message.get("reasoning_content"):
        tokens += estimate_text_tokens(message.get("reasoning_content"),
                                       chars_per_token=chars_per_token)
    if message.get("tool_call_id"):
        tokens += estimate_text_tokens(message.get("tool_call_id"),
                                       chars_per_token=chars_per_token)
    return tokens + ROLE_OVERHEAD


def estimate_tools_tokens(header: Mapping[str, Any] | None, *,
                          chars_per_token: float | None = None) -> int:
    """工具面（`tools` 那一段 JSON）的估价；DSH 只给这一个字段计价。"""
    if not isinstance(header, Mapping):
        return 0
    tools = header.get("tools")
    if tools is None or (isinstance(tools, Sequence) and not tools):
        return 0
    text = json.dumps(tools, ensure_ascii=False, sort_keys=True, default=str)
    return int(-(-len(text) // _rate(chars_per_token))) + BLOCK_OVERHEAD


@dataclass(frozen=True)
class Estimate:
    """一次估价的读数（数 + 用的是哪把尺一起给，见模块 docstring 的那段理由）。"""

    tokens: int
    chars: int
    messages: int
    chars_per_token: float
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {"tokens": self.tokens, "chars": self.chars, "messages": self.messages,
                "chars_per_token": self.chars_per_token, "source": self.source}


def estimate_messages(messages: Sequence[Mapping[str, Any]], *,
                      chars_per_token: float | None = None,
                      source: str = "default") -> Estimate:
    """一串消息的估价（压力门与"摘要必须更小"的校验都用它）。"""
    rate = _rate(chars_per_token)
    tokens = 0
    chars = 0
    for m in (messages or ()):
        tokens += estimate_message(m, chars_per_token=rate)
        chars += len(str(m.get("content") or ""))
    return Estimate(tokens=tokens, chars=chars, messages=len(messages or ()),
                    chars_per_token=rate, source=str(source))


def chars_per_token_from(config: Mapping[str, Any] | None) -> tuple[float | None, str]:
    """从配置里读"每 token 几个字符"：`(值, "config"|"default"|"unknown")`（三态）。

    `unknown` 不许被当成默认值：配置写了 `chars_per_token: "4"`（字符串）或 `0`
    会让估值悄悄换一把尺，而读数里看不出来。调用方（压缩那条路）据此走
    "警告一次 + 带完整历史继续"，与 DSH 自动路径 `CB:803-808` 同一姿态。
    """
    block = config if isinstance(config, Mapping) else {}
    inner = block.get("context_budget")
    if isinstance(inner, Mapping):
        block = inner
    if "chars_per_token" not in block:
        return float(CHARS_PER_TOKEN), "default"
    raw = block.get("chars_per_token")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None, "unknown"
    value = float(raw)
    if not (value > 0) or value != value:
        return None, "unknown"
    return value, "config"


def selftest() -> int:
    """自检：DSH 那几支的算术 + 三态 + 一处已知偏差的读数。"""
    bad: list[str] = []
    # ① DSH 的 text 支：`ceil(len/4) + 4`
    if estimate_text_tokens("abcdefgh") != 2 + BLOCK_OVERHEAD:
        bad.append(f"text 支算错了：{estimate_text_tokens('abcdefgh')}")
    # ② system 那条不含逐块开销（只有角色框架）
    if estimate_message({"role": "system", "content": "abcd"}) != 1 + ROLE_OVERHEAD:
        bad.append("system 支算错了（它不该带 BLOCK_OVERHEAD）")
    # ③ 空 content 的 system ⇒ 0（DSH 逐字："no system prompt"）
    if estimate_message({"role": "system", "content": ""}) != 0:
        bad.append("空 system 应当估成 0")
    # ④ 已知偏差：中文按 4 字符/token ⇒ 8 个汉字估成 2 + 4 = 6（真实值会更高）
    zh = estimate_text_tokens("汉字汉字汉字汉字")
    if zh != 2 + BLOCK_OVERHEAD:
        bad.append(f"中文那一档的读数变了（{zh}）—— 偏差是真的，但读数要稳")
    # ⑤ 调小 chars_per_token 会把估价抬上去（"中文可调小"这句话的机器读数）
    if not estimate_text_tokens("汉字汉字汉字汉字", chars_per_token=1.0) > zh:
        bad.append("把 chars_per_token 调小却没有抬高估价 ⇒ 那一档配置没接上")
    # ⑥ 三态
    if chars_per_token_from({"context_budget": {"chars_per_token": 2.5}}) != (2.5, "config"):
        bad.append("合法配置没读出 config 那一档")
    if chars_per_token_from({"context_budget": {"chars_per_token": "4"}}) != (None, "unknown"):
        bad.append("字符串形态的 chars_per_token 被当成了数字（三态折平）")
    if chars_per_token_from({"context_budget": {}}) != (float(CHARS_PER_TOKEN), "default"):
        bad.append("没配时的默认档不对")
    for line in bad:
        print(f"[tokenestimate] {line}")
    return 1 if bad else 0


if __name__ == "__main__":      # pragma: no cover —— 与全仓其它模块的 `__main__` 同形
    raise SystemExit(selftest())
