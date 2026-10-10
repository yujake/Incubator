"""上下文预算：压缩（compaction）/ 剪枝（pruning）/ spill 三件套（FC-17）。

## 为什么需要这个模块

极简的智能体配置里"没有 compaction"（`06-...md` §9.2）：长任务会硬撞上下文上限，
而且没有任何自动缓解；一旦 200,000 token 触发截断，模型看到的就是"被悄悄剪掉一半的
世界"，它甚至不知道自己少看了东西。Anthropic 因此必须先把计划写进 Memory
（`04-...md` §D2 反模式 5）—— 那是用人力绕开缺失的机制。

所以 FC-17 要求三件套都开着，且都能被证明开着：

1. 剪枝（pruning）——单个工具结果超过 `threshold_chars` 就压成 head + 省略标记 + tail。
   为什么保留头尾而不是只保留头：长输出的尾部往往是错误信息、UNSAT core、退出码
   （DSH 的 `tailChars: 1024` 注释原文就是这个理由），只砍尾巴会把最该看的东西砍掉。
2. spill——压完仍超过 `max_inline_bytes` 就落盘，内联只留"已落盘 + 路径 + 字节数 +
   sha256 前 16 位 + 怎么读"。信息守恒（FC-12）：剪枝丢掉的中间部分必须能从盘上找回来，
   否则"剪枝"就退化成"删除"。
3. compaction——一段历史/一串结果超过 `compaction_threshold_chars` 时，保留最近
   `compaction_keep_recent` 条原文，更早的折成一条摘要。

## 三条纪律（本模块的形状就是从它们来的）

① 三态，不是两态。 `pruned=True, spilled=False, reason="未提供 spill_root"` 与
`pruned=True, spilled=True` 是两件不同的事，而它们与 `pruned=False`（没超阈值）又是
第三件事。所以 `PrunedText.reason` / `CompactResult.reason` 永远非空：
"没剪"必须和"忘了剪"在字面上可分。同理 `CompactResult.summarizer` 取值
`"injected" | "mechanical" | "none"` —— "用了哪种压缩"必须可审计。

② 不许静默兜底。 配置项类型/取值不对就抛（`"8000"` 这种字符串不会被转成整数）；
机械摘要不猜内容、只报计数；注入的 `summarize` 返回非 `str` 就抛。

③ 确定性优先（FC-16）。 默认摘要绝不调用 LLM：它只是计数
（"早期 N 条，共 M 字符，涉及 K 类"）。把"该丢什么"交给模型是引入不确定性的最短路径，
而且摘要不是证据——原始条目仍在表里 / spill 文件里，压缩不该让它们不可读。

## 一个必须说清的几何事实

按 `--config` 的默认数值，`head_chars + tail_chars = 4000` 远小于
`max_inline_bytes = 64000`，所以"压完仍超上限 ⇒ 落盘"这个分支在默认配置下不可达：
被剪枝后的文本最多 4000 多字符。落盘要真的发生，得让
`head_chars + tail_chars > max_inline_bytes`（本模块的测试就是这样触发的），
或者由调用方直接对原始文本落盘。这不是 bug，是"§B1 数值表里两组数各自独立、
并非一条流水线"的直接后果 —— 但不说出来就会被误认为 spill 已经生效。
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass, replace
from pathlib import Path
from typing import Any, Callable, TypeVar

__all__ = [
    "CompactResult",
    "ContextBudget",
    "PrunedText",
    "compact",
    "prune",
    "prune_tool_result",
]

#: 剪枝标记。把省略的字符数和原字符数都写进正文 —— 只写"…"的标记
#: 让读者无法判断"丢了 10 个字符"还是"丢了 10 万个字符"。
_MARKER_FMT = "\n… [省略 {removed} 字符，原 {total} 字符] …\n"

#: 落盘文件名的"原名"部分。`prune()` 的入口只有一段文本，没有文件名可用，
#: 所以用固定的 `result`（`<sha256 前 16 位>-<原名>.txt`）。
_SPILL_STEM = "result"

#: 需要整数校验的字段（显式列举：注解在 `from __future__ import annotations`
#: 下是字符串，靠注解反射去猜类型只会在某天静默猜错）。
_INT_FIELDS = (
    "threshold_chars",
    "head_chars",
    "tail_chars",
    "max_inline_bytes",
    "compaction_threshold_chars",
    "compaction_keep_recent",
    # S-B 新增的两格（都得是整数）：容量与"直接给保留额"那一档。
    "context_window",
    "retain_tokens",
)
#: 浮点配置键（S-B 新增）：比值与估值器的尺。为什么单列一组而不是塞进 `_INT_FIELDS`：
#: `_as_int` 刻意拒绝 `0.8` 这类浮点（那是"整数键写成了浮点"的拼写错误），
#: 而比值天生是浮点 —— 两把尺混在一个校验器里会让两类错误互相掩盖。
_FLOAT_FIELDS = ("threshold_ratio", "retain_ratio", "chars_per_token")

#: 需要字符串校验的字段。
_STR_FIELDS = ("spill_dir",)

_R = TypeVar("_R")


# ---------------------------------------------------------------- 配置对象


@dataclass(frozen=True)
class ContextBudget:
    """上下文预算。每个字段的默认值都是"开着"的（FC-17 判据①）。

    为什么默认值不能是 0 / None：默认关闭等于"这条约束在没人配它的时候不存在"，
    而 FC-17 的存在理由恰恰是"没人会主动去配它，直到任务撞上墙"。
    """

    # ---- 剪枝：单个工具结果超过 threshold_chars 就压成 head + 省略标记 + tail
    threshold_chars: int = 8000
    head_chars: int = 3000
    tail_chars: int = 1000
    # ---- spill：压完仍超过 max_inline_bytes（字节）就落盘，只留定位信息
    spill_dir: str = "spill"
    max_inline_bytes: int = 64_000
    # ---- compaction：一串条目总长超过阈值时，更早的折成摘要
    compaction_threshold_chars: int = 200_000
    compaction_keep_recent: int = 8
    # ---- 压力口径（S-B / 裁定 8乙 + 12-H=甲）：照 DSH 的"token 压力"那一套
    #
    # 为什么两套并存而不是把字符那套删掉：`compaction_threshold_chars` 的读者还在
    # （`compact()` 那条老的机械路与它的判据），而这一批只是新增一条 DSH 口径的路
    # （`compact_by_pressure`）。删掉旧口径会让"这一批到底换了什么"变成一团。
    #: 模型的上下文窗口（token）。0 = 没配（= 读不到容量那一档，不许当成"够用"）。
    context_window: int = 0
    #: 触发阈值与保留尾部的比值（DSH 逐字：`thresholdRatio = .8` / `retainRatio = .16`）。
    threshold_ratio: float = 0.8
    retain_ratio: float = 0.16
    #: 直接给"保留多少 token"（> 0 时不用 `retain_ratio`）。0 = 用比值。
    retain_tokens: int = 0
    #: 每 token 几个字符（估值器的尺；默认 4 与 DSH 对数，中文语料可调小）。
    chars_per_token: float = 4.0

    # ---- 装载

    @classmethod
    def from_mapping(cls, cfg: Mapping[str, Any] | None = None) -> "ContextBudget":
        """从 `config.yaml` 读。缺键用默认，非法值抛 `ValueError`。

        接受两种入参，二者语义明确、互不歧义：

        - 整份配置（含 `context_budget:` 块）—— 即 `yaml.safe_load(config.yaml)` 的结果；
        - 只有块本身（`{"threshold_chars": 8000, ...}`）。

        区分规则是结构性的：`cfg` 里若存在 `context_budget` 键且其值是 mapping，
        就取它当块；否则 `cfg` 本身即块。`cfg=None`（没有配置文件）⇒ 全默认。

        未知键一律抛。理由：把 `threshold_char`（少个 s）静默忽略，等于
        "用户以为改了阈值、实际没改"，这正是本项目最忌讳的失败形态。
        """
        block = _extract_block(cfg)
        unknown = sorted(set(block) - set(_INT_FIELDS) - set(_STR_FIELDS) - set(_FLOAT_FIELDS))
        if unknown:
            raise ValueError(
                f"context_budget 里有未知配置键：{unknown}。"
                f"合法键只有 {sorted(set(_INT_FIELDS) | set(_STR_FIELDS) | set(_FLOAT_FIELDS))}。"
                "拼错的键会被忽略，于是'改了阈值'与'没改'长得一样 —— 所以这里直接拒绝"
            )
        # 覆盖不到所有 dataclass 字段时必须炸：否则新增字段会永远拿不到
        # config.yaml 的值，而没有任何地方报错（"加了配置项但没接线"）。
        all_fields = {f.name for f in fields(cls)}
        covered = set(_INT_FIELDS) | set(_STR_FIELDS) | set(_FLOAT_FIELDS)
        if all_fields - covered:
            raise ValueError(
                f"ContextBudget 有字段没有任何校验器：{sorted(all_fields - covered)}。"
                "新增字段必须同时加入 _INT_FIELDS / _STR_FIELDS / _FLOAT_FIELDS，"
                "否则它永远无法从配置装载"
            )

        values: dict[str, Any] = {}
        for key in _INT_FIELDS:
            if key in block:
                values[key] = _as_int(key, block[key])
        for key in _FLOAT_FIELDS:
            if key in block:
                values[key] = _as_float(key, block[key])
        for key in _STR_FIELDS:
            if key in block:
                values[key] = _as_rel_dir(key, block[key])

        budget = cls(**values)
        # 装载即校验（fail-closed）：让"三件套没开"在读配置的时候就炸，
        # 而不是等到某个工具返回 500 KB 文本时才炸。
        budget.validate()
        return budget

    def to_mapping(self) -> dict[str, Any]:
        """回写用的平面 dict（审计：报告里要能原样打出"这轮用的到底是哪组数"）。"""
        return {f.name: getattr(self, f.name) for f in fields(self)}

    # ---- 校验

    def validate(self) -> None:
        """断言"三件套都开着"（FC-17 判据①）。不合法抛 `ValueError`。

        - `threshold_chars > 0`（剪枝开着）
        - `max_inline_bytes > 0`（spill 开着）
        - `compaction_threshold_chars > 0`（compaction 开着）
        - `head_chars + tail_chars < threshold_chars` —— 否则"剪枝"会把文本变长
          （头尾之和都不比原文短，再加省略标记就是净增长），这是自相矛盾的配置。
        """
        for key in ("threshold_chars", "max_inline_bytes", "compaction_threshold_chars"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(
                    f"FC-17 要求三件套都**开着**：context_budget.{key}={value!r} 必须是 > 0 的整数"
                )
        for key in ("head_chars", "tail_chars", "compaction_keep_recent"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"context_budget.{key}={value!r} 必须是 >= 0 的整数")
        if self.head_chars + self.tail_chars >= self.threshold_chars:
            raise ValueError(
                f"context_budget 自相矛盾：head_chars({self.head_chars}) + "
                f"tail_chars({self.tail_chars}) = {self.head_chars + self.tail_chars} "
                f">= threshold_chars({self.threshold_chars})。"
                "头 + 尾已经不比原文短，再加省略标记就是**把内容变长** —— 这不是剪枝"
            )
        # ---- S-B（裁定 8乙 + 12-H=甲）：压力口径的装载期校验（照 DSH `CB:128-136/:169`）
        for key in ("context_window", "retain_tokens"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"context_budget.{key}={value!r} 必须是 >= 0 的整数")
        if self.retain_tokens > 0 and self.retain_ratio != _DEFAULT_RETAIN_RATIO:
            raise ValueError(
                f"context_budget 自相矛盾：retain_tokens({self.retain_tokens}) 与 "
                f"retain_ratio({self.retain_ratio}) 同时给了（DSH 逐字：同给即拒）。"
                "我们的 dataclass 分不清'与默认值相同的显式赋值'，所以判据是"
                "`retain_tokens > 0 且 retain_ratio 不等于默认值` —— 这处偏差写在注释里"
            )
        if self.retain_ratio >= self.threshold_ratio:
            raise ValueError(
                f"context_budget 自相矛盾：retain_ratio({self.retain_ratio}) >= "
                f"threshold_ratio({self.threshold_ratio})（DSH 逐字：保留得比阈值还多，"
                "等于压完立刻又超阈值）"
            )
        if not isinstance(self.spill_dir, str) or not self.spill_dir.strip():
            raise ValueError(f"context_budget.spill_dir={self.spill_dir!r} 必须是非空字符串")
        # 直接构造出来的对象也要过同一套目录校验（`from_mapping` 之外的第二道门）：
        # 绝对路径 / 盘符 / '..' 会让落盘跑到工作区外面去。
        _as_rel_dir("spill_dir", self.spill_dir)


#: 保留比值的默认值（与 `ContextBudget.retain_ratio` 同一处口径；`validate()` 拿它当
#: "这一格有没有被显式赋值"的哨兵，理由见那一段）。
_DEFAULT_RETAIN_RATIO = 0.16


def _extract_block(cfg: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """把"整份配置"与"块本身"分清；都不像就抛。"""
    if cfg is None:
        return {}
    if not isinstance(cfg, Mapping):
        raise ValueError(f"context_budget 配置必须是 mapping，收到 {type(cfg).__name__}")
    inner = cfg.get("context_budget")
    if isinstance(inner, Mapping):
        return inner
    if inner is not None:
        raise ValueError(
            f"config.yaml 的 context_budget 必须是 mapping（键值对），收到 {type(inner).__name__}"
        )
    return cfg


def _as_int(key: str, value: Any) -> int:
    """整数校验。字符串数字不是整数：`"8000"` / `8000.0` 一律拒绝。

    为什么不做 `int(value)` 这样"宽容"的转换：一旦允许隐式转换，
    `threshold_chars: "8000 "`（尾随空格 / 全角数字 / `8e3`）这类拼写错误就会
    以"看起来成功了"的方式通过，而实际语义可能完全不同（`int("8_0") == 80`）。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"context_budget.{key} 必须是整数，收到 {type(value).__name__}：{value!r}。"
            "不许静默转换（YAML 里写成 '8000'、8000.0、'8e3' 都会被拒绝）"
        )
    return value


def _as_float(key: str, value: Any) -> float:
    """浮点校验（比值与估值器的尺）。整数形态接受（`1` == `1.0`），字符串一律拒绝。

    与 `_as_int` 同一条纪律：`"0.8"`（带引号）这种拼写错误必须当场红，
    否则"配置写对了"与"配置被引号包着、其实没生效"在读数上长得一样。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"context_budget.{key} 必须是数，收到 {type(value).__name__}：{value!r}。"
            "不许静默转换（YAML 里写成 '0.8' 会被拒绝）"
        )
    out = float(value)
    if out != out or out <= 0:
        raise ValueError(f"context_budget.{key}={value!r} 必须是正的有限数")
    return out


def _as_rel_dir(key: str, value: Any) -> str:
    """目录校验：非空、相对、且不含 `..`。绝对路径会让落盘跑到工作区外面去。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"context_budget.{key} 必须是非空字符串，收到 {value!r}")
    p = Path(value)
    if p.is_absolute() or p.drive or ".." in p.parts:
        raise ValueError(
            f"context_budget.{key}={value!r} 必须是 spill_root 下的相对目录"
            "（不许绝对路径 / 盘符 / '..'：落盘位置必须可预期）"
        )
    return value


# ---------------------------------------------------------------- 剪枝结果


@dataclass(frozen=True)
class PrunedText:
    """剪枝/spill 的三态结果。

    `text` 是可以内联进上下文的那部分；`original_chars` / `kept_chars` 是字符数；
    `reason` 永远非空，它承担"把三态说清楚"的责任。
    """

    text: str
    original_chars: int
    kept_chars: int
    pruned: bool
    spilled: bool
    spill_path: str | None
    reason: str


def load_budget(config: "Mapping[str, Any] | None") -> "ContextBudget | None":
    """从配置映射里取出上下文预算。没有 `context_budget` 块 ⇒ 返回 `None`。

    ## 为什么"没配"必须与"用默认值"分开

    `ContextBudget.from_mapping({})` 会填出一整套默认值 —— 那是"配了但用默认"。
    而 `config` 里压根没有 `context_budget` 块时，正确的语义是"这台部署没启用
    上下文预算"。把两者折叠成同一个对象，就无法回答
    "剪枝到底开没开"这个只有两个答案的问题。

    所以这里返回三态：
    - `config is None` ⇒ `None`（没给配置，不是"没配预算"）
    - 没有 `context_budget` 键 ⇒ `None`（没启用）
    - 有该键 ⇒ 一个 `ContextBudget`（值不合法会抛，由 `from_mapping` 负责）
    """
    if config is None:
        return None
    block = config.get("context_budget") if isinstance(config, Mapping) else None
    if block is None:
        return None
    return ContextBudget.from_mapping(block)


def prune(
    text: str,
    *,
    budget: ContextBudget,
    spill_root: str | os.PathLike[str] | None = None,
) -> PrunedText:
    """按预算剪枝；压完仍超 `max_inline_bytes` 就落盘（spill）。

    三态（判据②要的正是这三态都能被区分）：

    1. `len(text) <= threshold_chars` ⇒ `pruned=False, spilled=False`，
       `reason` 含"未超阈值"；
    2. 超阈值但没给 `spill_root` ⇒ `pruned=True, spilled=False`，
       `reason` 含"未提供 spill_root，未能落盘"（这是"没落盘"，不是"不需要落盘"）；
    3. 超阈值且给了 `spill_root` ⇒ `spilled=True`，内容整体（未剪枝的原文）
       写到 `spill_root/<spill_dir>/<sha256 前 16 位>-result.txt`，内联只剩定位信息。

    落盘写的是原始全文，不是剪枝后的版本。理由：spill 的存在意义就是
    "被剪掉的那部分还能找回来"；把剪枝后的文本落盘，等于把中间那段永久删掉，
    却给出一个"已落盘"的标记 —— 那是最坏的一种失败（看起来有救、实际没救）。
    因此记录在案的字节数与 sha256 都是全文的，与盘上文件逐字节一致。
    """
    if not isinstance(text, str):
        raise ValueError(f"prune() 只接受 str，收到 {type(text).__name__}")
    if not isinstance(budget, ContextBudget):
        raise ValueError(f"prune() 的 budget 必须是 ContextBudget，收到 {type(budget).__name__}")
    budget.validate()

    total = len(text)
    if total <= budget.threshold_chars:
        return PrunedText(
            text=text,
            original_chars=total,
            kept_chars=total,
            pruned=False,
            spilled=False,
            spill_path=None,
            reason=(
                f"未超阈值：{total} 字符 ≤ threshold_chars={budget.threshold_chars}；"
                "未剪枝，也未落盘（内容是原样内联的）"
            ),
        )

    removed = total - budget.head_chars - budget.tail_chars
    tail = text[-budget.tail_chars:] if budget.tail_chars > 0 else ""
    pruned_text = text[: budget.head_chars] + _MARKER_FMT.format(removed=removed, total=total) + tail
    inline_bytes = len(pruned_text.encode("utf-8"))

    if inline_bytes <= budget.max_inline_bytes:
        return PrunedText(
            text=pruned_text,
            original_chars=total,
            kept_chars=len(pruned_text),
            pruned=True,
            spilled=False,
            spill_path=None,
            reason=(
                f"超阈值已剪枝：{total} → {len(pruned_text)} 字符（省略 {removed} 字符）；"
                f"内联 {inline_bytes} 字节 ≤ max_inline_bytes={budget.max_inline_bytes}，未落盘"
            ),
        )

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if spill_root is None:
        return PrunedText(
            text=pruned_text,
            original_chars=total,
            kept_chars=len(pruned_text),
            pruned=True,
            spilled=False,
            spill_path=None,
            reason=(
                f"超阈值已剪枝：{total} → {len(pruned_text)} 字符，压完仍 {inline_bytes} 字节 "
                f"> max_inline_bytes={budget.max_inline_bytes}；**未提供 spill_root，未能落盘** —— "
                "被省略的中间部分目前没有保存在任何地方（这不是'不需要落盘'，是'没落盘'）"
            ),
        )

    path = Path(spill_root) / budget.spill_dir / f"{digest[:16]}-{_SPILL_STEM}.txt"
    payload = text.encode("utf-8")
    try:
        _atomic_write_bytes(path, payload)
    except OSError as e:
        # 落盘失败不许变成异常把智能体的循环打断，但也不许假装成功：
        # 退回"已剪枝但未落盘"这一态，并如实说明中间部分没保存（DSH 的
        # spill 策略同样是"落盘失败时原始结果仍可见"）。
        return PrunedText(
            text=pruned_text,
            original_chars=total,
            kept_chars=len(pruned_text),
            pruned=True,
            spilled=False,
            spill_path=None,
            reason=(
                f"超阈值已剪枝：{total} → {len(pruned_text)} 字符；"
                f"落盘失败（{type(e).__name__}: {e}），退回内联剪枝文本。"
                "被省略的中间部分**没有**保存下来，需要时请用更大的内联上限重试"
            ),
        )

    size = len(payload)
    rel = (Path(budget.spill_dir) / path.name).as_posix()
    inline = (
        f"[已落盘] {rel}（{size} 字节，sha256:{digest[:16]}）。"
        "用 read 工具按 offset/limit 分段读取。"
    )
    return PrunedText(
        text=inline,
        original_chars=total,
        kept_chars=len(inline),
        pruned=True,
        spilled=True,
        spill_path=str(path),
        reason=(
            f"超阈值已剪枝：{total} → {len(pruned_text)} 字符，压完仍 {inline_bytes} 字节 "
            f"> max_inline_bytes={budget.max_inline_bytes}，故**整体落盘**：{path} "
            f"（{size} 字节，sha256:{digest[:16]}）。内联只剩定位信息；"
            "文件名前 16 位就是内容的 sha256 前缀，读者可据此核对'落盘的确实是这一份'"
        ),
    )


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """同目录临时文件 → fsync → `os.replace`（与 `Store._atomic_write` 同一套路）。

    为什么必须原子：spill 文件是"剪枝丢掉的中间部分"的唯一副本，
    半截文件比没有文件更坏 —— 它看起来可读，实际内容截断在某个字节上。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with open(tmp, "wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------- 压缩（compaction）


@dataclass(frozen=True)
class CompactResult:
    """压缩结果。

    `summarizer` 三态：`"injected"`（调用方注入了 `summarize`）/ `"mechanical"`
    （确定性的机械摘要）/ `"none"`（没压缩）。`reason` 是本模块在规格要求之外
    额外加的字段：它是"没压缩"与"忘了压缩"的分界线，与 `PrunedText.reason` 同理。
    """

    text: str
    dropped_count: int
    kept_count: int
    original_chars: int
    kept_chars: int
    compacted: bool
    summarizer: str
    reason: str
    # ---- S-B（token 压力那条路）多出来的读数。老那条字符路不填它们
    # （默认值就是"没这一档"，于是两类结果在 `to_dict` 上仍然分得开）。
    #: 这一次用的阈值与保留额（token；0 = 没走压力那条路）
    threshold_tokens: int = 0
    retain_tokens: int = 0
    #: 被遮掉那一段的估价与摘要成帧后的估价（token）—— "摘要必须更小"那条判据的两端
    shadowed_tokens: int = 0
    framed_tokens: int = 0
    #: 按哪把尺估的（`chars_per_token`）与压力基线取自哪一半
    #: （`heuristic` 估算 / `usage_anchor` 上一轮真实 usage）
    chars_per_token: float = 0.0
    baseline_source: str = ""
    #: 被遮蔽的位置 span（`(第一条, 最后一条)`）。这是位置不是数值区间：
    #: 上一轮替换把摘要放到旧区间的位置后，start 在值上可能大于 end
    #: （DSH `types.d.ts:115-122` 的警告）⇒ 不许写 `range(start, end + 1)`。
    shadowed_range: tuple[int, int] = (0, 0)


def compact(
    items: Sequence[Any],
    *,
    budget: ContextBudget,
    summarize: Callable[[list[Any]], str] | None = None,
) -> CompactResult:
    """把"一串条目"压成"摘要 + 最近 N 条原文"。

    输入约定（写清，免得调用方猜）：

    - `items` 必须是 `list` / `tuple`（有稳定顺序的 `Sequence`）。拒绝 `str`、
      `set`、生成器 —— 它们的"顺序"不稳定，机械摘要会随之漂移（FC-16 确定性优先）。
    - 每个条目要么是 `str`，要么是带 `"text"` 键的 mapping（其它键保留给调用方
      自己用，本函数只看 `text`）。缺 `text` / `text` 非 str 一律抛。
    - 总长 = 各条目 `text` 的字符数之和，与 `compaction_threshold_chars` 比。
    - `summarize` 收到的是被折掉的那批条目的原样 list（与输入同类型，
      不是纯文本），返回值必须是非空 `str`。
    - `kept_chars` 是最终渲染出来的文本的字符数（与 `PrunedText.kept_chars`
      口径一致：都是"实际内联进上下文的字符数"）。
    """
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise ValueError(
            f"compact() 的 items 必须是 list/tuple 这类有序序列，收到 {type(items).__name__}"
            "（str / set / 生成器都被拒绝：没有稳定顺序就没有确定性摘要）"
        )
    if not isinstance(budget, ContextBudget):
        raise ValueError(f"compact() 的 budget 必须是 ContextBudget，收到 {type(budget).__name__}")
    if summarize is not None and not callable(summarize):
        raise ValueError("compact() 的 summarize 必须可调用（list -> str）或为 None")
    budget.validate()

    texts = [_item_text(item, i) for i, item in enumerate(items)]
    total = sum(len(t) for t in texts)

    if total <= budget.compaction_threshold_chars:
        rendered = _render_kept(texts)
        return CompactResult(
            text=rendered,
            dropped_count=0,
            kept_count=len(texts),
            original_chars=total,
            kept_chars=len(rendered),
            compacted=False,
            summarizer="none",
            reason=(
                f"未超阈值：共 {total} 字符 ≤ compaction_threshold_chars="
                f"{budget.compaction_threshold_chars}；{len(texts)} 条全部保留原文，未压缩"
            ),
        )

    keep = budget.compaction_keep_recent
    dropped_n = len(texts) - keep
    if dropped_n <= 0:
        rendered = _render_kept(texts)
        return CompactResult(
            text=rendered,
            dropped_count=0,
            kept_count=len(texts),
            original_chars=total,
            kept_chars=len(rendered),
            compacted=False,
            summarizer="none",
            reason=(
                f"超阈值（共 {total} 字符 > {budget.compaction_threshold_chars}），"
                f"但只有 {len(texts)} 条 ≤ compaction_keep_recent={keep}："
                "没有'更早的条目'可折进摘要，故未压缩"
                + ("（注入的 summarize 因此**没有被调用**）" if summarize is not None else "")
            ),
        )

    early_texts = texts[:dropped_n]
    kept_texts = texts[dropped_n:]
    early_items = list(items[:dropped_n])

    if summarize is None:
        # 默认路径绝不调 LLM（FC-16）：机械摘要只报"丢了多少、什么类型"。
        # 摘要里不放正文片段不是偷懒 —— 放进去就等于用一个不可靠的替代品
        # 替换原始证据，而原文在表 / spill 文件里仍然完整可取。
        summary = _mechanical_summary(early_texts, [type(it).__name__ for it in early_items])
        summarizer = "mechanical"
    else:
        out = summarize(early_items)
        if not isinstance(out, str) or not out.strip():
            raise ValueError(
                f"注入的 summarize 必须返回非空 str，收到 {type(out).__name__}：{out!r}"
                "（返回空摘要等于把这段历史静默扔掉）"
            )
        summary = out
        summarizer = "injected"

    rendered = (
        f"[早期 {dropped_n} 条已压缩，summarizer={summarizer}]\n"
        f"{summary}\n"
        f"--- 最近 {len(kept_texts)} 条原文 ---\n"
        f"{_render_kept(kept_texts)}"
    )
    return CompactResult(
        text=rendered,
        dropped_count=dropped_n,
        kept_count=len(kept_texts),
        original_chars=total,
        kept_chars=len(rendered),
        compacted=True,
        summarizer=summarizer,
        reason=(
            f"共 {total} 字符 > compaction_threshold_chars={budget.compaction_threshold_chars}："
            f"早期 {dropped_n} 条（{sum(len(t) for t in early_texts)} 字符）折成 {summarizer} 摘要，"
            f"最近 {len(kept_texts)} 条保留原文"
        ),
    )


def _item_text(item: Any, index: int) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        if "text" not in item:
            raise ValueError(
                f"compact() 第 {index} 条是 mapping 但缺 'text' 键（现有键：{sorted(map(str, item))}）。"
                "不许静默当空串处理"
            )
        value = item["text"]
        if not isinstance(value, str):
            raise ValueError(
                f"compact() 第 {index} 条的 text 必须是 str，收到 {type(value).__name__}"
            )
        return value
    raise ValueError(
        f"compact() 第 {index} 条既不是 str 也不是带 'text' 的 mapping，收到 {type(item).__name__}"
    )


def _render_kept(texts: Sequence[str]) -> str:
    return "\n".join(f"[{i}] {t}" for i, t in enumerate(texts, 1))


def _mechanical_summary(early_texts: Sequence[str], kind_names: Sequence[str]) -> str:
    """确定性机械摘要：只有计数，没有内容，也不调 LLM（FC-16）。

    输出必须逐字节可复现 —— 所以这里没有任何 set 迭代顺序、时间戳、随机数、ID。
    """
    kinds: dict[str, int] = {}
    for name in kind_names:
        kinds[name] = kinds.get(name, 0) + 1
    kind_txt = "、".join(f"{k} {kinds[k]} 条" for k in sorted(kinds))
    return (
        f"早期 {len(early_texts)} 条，共 {sum(len(t) for t in early_texts)} 字符，"
        f"涉及 {len(kinds)} 类（{kind_txt}）。"
        "本摘要为**机械统计**（确定性，不调用任何模型），不含条目正文："
        "原文仍在原表 / spill 文件里，压缩不改变它们的可取回性。"
    )


# ---------------------------------------------------------------- 工具结果接入


def prune_tool_result(
    result: _R,
    *,
    budget: ContextBudget,
    spill_root: str | os.PathLike[str] | None = None,
) -> _R:
    """把工具结果 `data` 里的大字符串剪掉/落盘，`ok` 与 `error` 原样不动。

    - 剪枝不改结论：`ok` / `error` 逐字段保留。失败就是失败，成功就是成功 ——
      剪枝是"少看点内容"，不是"改判"。
    - `data` 里所有 `str`（含嵌套在 dict / list / tuple 里的）逐个走 `prune()`；
      没有超过 `threshold_chars` 的字符串就原样返回，并把这件事写进 `meta`。
    - dict 的键不动：改键会改变调用方的查找语义（那不是剪枝，是改 schema）。
    - `meta` 里记 `pruned` / `spilled` / `spill_path` / `original_chars`，
      另外记 `kept_chars` / `prune_count` / `spill_paths` / `prune_reasons` /
      `prune_note`（`prune_note` 永远非空：把"没剪"与"忘了剪"分开）。
      有多个字符串落盘时 `spill_path` 为 `None`（单个路径会掩盖"其实有好几个"），
      完整清单看 `spill_paths`。

    本模块不 import `agentflow.tools.base`（那是反向依赖，会造成循环）。
    这里用鸭子类型：入参必须是"带 `ok` / `data` / `error` / `meta` 四个字段的
    dataclass 实例"，返回同类型的新实例（`dataclasses.replace`）。
    `tools.base.ToolResult` 正好满足；不满足的入参直接抛，不做猜测。
    """
    if not is_dataclass(result) or isinstance(result, type):
        raise ValueError(
            f"prune_tool_result() 需要一个工具结果对象（dataclass 实例），收到 "
            f"{type(result).__name__}。本模块刻意不 import tools.base，故用鸭子类型判定"
        )
    names = {f.name for f in fields(result)}
    if not {"ok", "data", "error", "meta"} <= names:
        raise ValueError(
            f"prune_tool_result() 的对象缺字段：{sorted({'ok', 'data', 'error', 'meta'} - names)}"
            f"（实际字段 {sorted(names)}）"
        )
    if not isinstance(budget, ContextBudget):
        raise ValueError(
            f"prune_tool_result() 的 budget 必须是 ContextBudget，收到 {type(budget).__name__}"
        )
    budget.validate()

    stats: dict[str, Any] = {
        "original_chars": 0,
        "kept_chars": 0,
        "pruned": 0,
        "spills": [],
        "reasons": [],
    }
    new_data = _prune_value(result.data, budget=budget, spill_root=spill_root, stats=stats)

    meta = dict(result.meta or {})
    spilled = len(stats["spills"]) > 0
    meta.update(
        {
            "pruned": stats["pruned"] > 0,
            "spilled": spilled,
            "spill_path": stats["spills"][0] if len(stats["spills"]) == 1 else None,
            "original_chars": stats["original_chars"],
            "kept_chars": stats["kept_chars"],
            "prune_count": stats["pruned"],
            "spill_paths": list(stats["spills"]),
            "prune_reasons": list(stats["reasons"]),
            "prune_note": _prune_note(stats, budget, spill_root, spilled),
        }
    )
    return replace(result, data=new_data, meta=meta)


def _prune_value(
    value: Any,
    *,
    budget: ContextBudget,
    spill_root: str | os.PathLike[str] | None,
    stats: dict[str, Any],
) -> Any:
    """递归剪枝。list/tuple/dict 都返回新容器（不改调用方手上的那个对象）。"""
    if isinstance(value, str):
        stats["original_chars"] += len(value)
        if len(value) <= budget.threshold_chars:
            stats["kept_chars"] += len(value)
            return value
        p = prune(value, budget=budget, spill_root=spill_root)
        stats["pruned"] += 1
        stats["kept_chars"] += len(p.text)
        stats["reasons"].append(p.reason)
        if p.spilled and p.spill_path:
            stats["spills"].append(p.spill_path)
        return p.text
    if isinstance(value, Mapping):
        return {k: _prune_value(v, budget=budget, spill_root=spill_root, stats=stats) for k, v in value.items()}
    if isinstance(value, list):
        return [_prune_value(v, budget=budget, spill_root=spill_root, stats=stats) for v in value]
    if isinstance(value, tuple):
        return tuple(_prune_value(v, budget=budget, spill_root=spill_root, stats=stats) for v in value)
    # 其它类型（数字 / bool / None / set / 自定义对象）原样保留：
    # 它们不是文本载体，也不该被本层"顺手改一下"。
    return value


def _prune_note(
    stats: Mapping[str, Any],
    budget: ContextBudget,
    spill_root: str | os.PathLike[str] | None,
    spilled: bool,
) -> str:
    if stats["pruned"] == 0:
        return (
            f"没有任何字符串超过 threshold_chars={budget.threshold_chars}，未剪枝"
            f"（共检查 {stats['original_chars']} 字符）"
        )
    if not spilled:
        why = (
            "未提供 spill_root"
            if spill_root is None
            else "给了 spill_root 但没有任何字符串落盘（剪枝后未超 max_inline_bytes，"
            "或落盘失败 —— 逐条看 prune_reasons）"
        )
        return (
            f"{stats['pruned']} 个字符串超过 threshold_chars={budget.threshold_chars} 已剪枝；"
            f"没有落盘（{why}）。注意：这不是'不需要落盘'，是'没有落盘'"
        )
    return (
        f"{stats['pruned']} 个字符串已剪枝，其中 {len(stats['spills'])} 个落盘；"
        f"完整路径见 spill_paths"
    )


# ================================================================ 压力口径（S-B / DSH）
#
# 这一段是新增的一条路（`compact_by_pressure`），它照 DSH 的"token 压力"那一套
# （`dsh-compaction-basic/lib/index.js`）：两道门（阈值 / 复测）+ 容量标定 + 从尾回积
# + 三条不变量。老的字符口径（`compact()`）一个字没动 —— 它的读者与判据都还在。


class TargetPressureConfigError(ValueError):
    """容量那一档读不到（或配置自相矛盾）—— DSH 手动路径就是抛这个（`CB:897-898`）。"""


class CompactionNotSmallerError(ValueError):
    """摘要不比被遮掉的量小（DSH `CB:571-572`：判据是 `>=`，等于也拒）。

    为什么"相等"也算失败：压缩的产物就是那条摘要，若它不比被遮掉的那一段更小，
    这一趟的账（`shadowedTokenCount` vs `framedSummaryTokenCount`）会指向一个荒谬的结论 ——
    "压过了，而历史一点没短"。DSH 选的是当场判失败，我们照抄。
    """


@dataclass(frozen=True)
class CompactSpec:
    """容量标定的结果（DSH `CB:108-126` 的四样 + 尺的读数）。"""

    context_window: int
    threshold_tokens: int
    retain_tokens: int
    chars_per_token: float
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {"context_window": self.context_window,
                "threshold_tokens": self.threshold_tokens,
                "retain_tokens": self.retain_tokens,
                "chars_per_token": self.chars_per_token, "source": self.source}


def _spec_of(budget: "ContextBudget") -> tuple[CompactSpec | None, str]:
    """容量标定（三态）：`(规格, 问题)`。问题非空 = 读不到容量那一档。

    逐条照 DSH：`contextWindow` 非正整数 ⇒ 读不到；`thresholdTokens = floor(cw*ratio)`；
    `retainTokens = floor(cw*retainRatio)`（或配置直接给的那一份）；
    `retainTokens >= thresholdTokens` ⇒ 配置自相矛盾（装载期已经拦过，这里再拦一次，
    因为 `ContextBudget(...)` 可以直接构造而不走 `from_mapping`）。
    """
    cw = int(getattr(budget, "context_window", 0) or 0)
    if cw <= 0:
        return None, ("context_window 没配（或不是正整数）⇒ **读不到容量**那一档："
                      "既不静默当 0、也不阻断这一趟（照 DSH 自动路径：警告一次、带完整历史继续）")
    threshold = int(cw * float(budget.threshold_ratio))
    retain = int(budget.retain_tokens) if int(budget.retain_tokens or 0) > 0 \
        else int(cw * float(budget.retain_ratio))
    if retain >= threshold:
        raise TargetPressureConfigError(
            f"容量自相矛盾：retainTokens({retain}) >= thresholdTokens({threshold})"
            "（DSH 逐字：压完立刻又超阈值）")
    return CompactSpec(context_window=cw, threshold_tokens=threshold, retain_tokens=retain,
                       chars_per_token=float(getattr(budget, "chars_per_token", 4.0)),
                       source="context_window"), ""


def _node_text(item: Any) -> str:
    """一条节点（消息）的模型可见文本（估价与"节点 0 保护"都用它）。"""
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        if "content" in item:
            return str(item.get("content") or "")
        return str(item.get("text") or "")
    raise ValueError(f"压力路的 items 只能是 str 或带 content/text 的 mapping，收到 "
                     f"{type(item).__name__}")


def _pairing_cuts(items: Sequence[Any]) -> list[bool]:
    """配对平衡表：`cuts[i]` = "在第 i 条之前下刀是否不切断一次调用/结果对"。

    搬的是 DSH 的 `cutBalanced`（`dsh-compaction-surface`：长度 = 节点数 + 1 的布尔数组，
    `Before(seq) = cutBalanced[idx]`）。我们的节点现在就是消息（S-C 之后：
    assistant 带 `tool_calls`、tool 带 `tool_call_id`）⇒ "一次调用"跨两条节点，
    切在它们中间就会让模型看到一个没有结果的调用（或一个没被要求过的结果）。
    """
    n = len(items)
    cuts = [True] * (n + 1)
    for i, item in enumerate(items):
        if not isinstance(item, Mapping) or str(item.get("role") or "") != "assistant":
            continue
        ids = {str(c.get("id") or "") for c in (item.get("tool_calls") or [])
               if isinstance(c, Mapping)}
        if not ids:
            continue
        for j in range(i + 1, n):
            nxt = items[j]
            if not isinstance(nxt, Mapping) or str(nxt.get("role") or "") != "tool":
                break
            if str(nxt.get("tool_call_id") or "") in ids and j == i + 1:
                cuts[j] = False          # 切在 assistant 与它的 tool 之间 = 切断配对
                break
    return cuts


def _select_keep(items: Sequence[Any], *, spec: CompactSpec, chars_per_token: float,
                 exclude_first: bool) -> int:
    """从尾往回按 token 累加到 `retain_tokens` 为止，再做配对平衡回退（DSH `CB:401-412`）。

    返回 `keep`（"从第 keep 条起保留原文"）。`retain_tokens == 0` ⇒ 第一轮就停 ⇒
    只保留最后一个节点（DSH 的 overflow 语义，也是"一次最大的平衡压缩"）。
    """
    from . import tokenestimate as TE

    n = len(items)
    keep = n
    if spec.retain_tokens <= 0:
        keep = max(1, n - 1)
    else:
        acc = 0
        while keep > 1:
            tokens = TE.estimate_message(items[keep - 1], chars_per_token=chars_per_token) \
                if isinstance(items[keep - 1], Mapping) else \
                TE.estimate_text_tokens(items[keep - 1], chars_per_token=chars_per_token)
            if acc + tokens > spec.retain_tokens:
                break
            acc += tokens
            keep -= 1
    # 至少保留最后一个节点：节点是整体，不能只保留它的一部分 —— 一个节点自己就超过
    # `retain_tokens` 时，累加在第一轮就 break，而"什么都不留"是另一件事（那会把最近的
    # 上下文也折进摘要，模型接着干活时连上一句都看不到）。DSH 的 `retainTokens=0` 那一档
    # 逐字就是"只保留最后一个节点"，这里把同一条不变量推广到所有取值。
    if n >= 2:
        keep = min(keep, n - 1)
    first = 1 if exclude_first else 0        # 节点 0（开场简报/任务原文）永不遮蔽
    if keep <= first:
        keep = min(n, first + 1)             # 至少留一条，且它必须在允许遮蔽的范围之外
    cuts = _pairing_cuts(items)
    while keep > first and not cuts[keep]:
        keep -= 1                            # 回退只动 start（往回走）⇒ 永不切断配对
    return max(keep, first)


def compact_by_pressure(
    items: Sequence[Any],
    *,
    budget: ContextBudget,
    summarize: Callable[[list[Any]], str] | None = None,
    usage_tokens: int | None = None,
    strict: bool = False,
) -> CompactResult:
    """token 压力那条路（S-B / 裁定 8乙 + 12-H=甲 + 12-I=甲）。

    `{"compacted", "shadowed_range", "shadowed_tokens", "framed_tokens", …}` 那一族读数
    都在返回的 `CompactResult` 里（多出来的格子见那个 dataclass）。

    ## 与 DSH 逐条对齐的地方

    - 两道门（`CB:899-905`）：`total < threshold ⇒ 不压`；压完复测仍在阈值之上
      才谈得上再压（本函数只做一次；重试那一格是调用方的事 —— 见下）。
    - 节点 0 永不遮蔽（`CB:379-382`）：第一条（开场简报：任务原文 + 身份 + 收件箱）
      不进被遮蔽的范围；`surface` 的第 0 个节点是 system，区间从 1 起。
    - 从尾回积 + 配对平衡回退（`CB:401-412`）：见 `_select_keep`。
    - `retain_tokens = 0` ⇒ 只留最后一个节点（`CB:891`、`:951`）。
    - 摘要必须更小（`CB:571-572`，判据是 `>=`）：不比被遮掉的量小 ⇒ 判失败
      （`CompactionNotSmallerError`），不是"成功但没省"。
    - 读不到容量（三态，`CB:803-808` / `:897-898`）：`strict=False`（自动路径）
      ⇒ 返回 `compacted=False` + 一句"读不到容量"的读数，带完整历史继续；
      `strict=True`（手动路径）⇒ 抛 `TargetPressureConfigError`。

    ## 两处如实登记的差异

    1. 压力基线：DSH 用"usage 锚（够大就信）否则估算"。我们收 `usage_tokens`
       （上一轮的真实 usage）并取 `max(估算, 锚)` —— 锚更大时以锚为准，两条读数都在
       `baseline_source` 里说明。"锚 + 本轮增量"那个更省的做法没做（每次全量重算），
       那是接线那一批的事。
    2. 重试那一格不做：DSH 压力路径最多重试 1 次（`compactionRetries=1` ⇒ 最多 2 次），
       那句"仍超阈值 ⇒ 抛"属于调用方的循环。本函数只回答"这一次压出什么"。
    """
    import math

    from . import tokenestimate as TE

    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise ValueError(
            f"compact_by_pressure() 的 items 必须是有序序列，收到 {type(items).__name__}")
    if not isinstance(budget, ContextBudget):
        raise ValueError(f"compact_by_pressure() 的 budget 必须是 ContextBudget，"
                         f"收到 {type(budget).__name__}")
    if summarize is not None and not callable(summarize):
        raise ValueError("compact_by_pressure() 的 summarize 必须可调用（list -> str）或为 None")
    budget.validate()

    spec, problem = _spec_of(budget)
    if spec is None:
        if strict:
            raise TargetPressureConfigError(problem)
        return CompactResult(
            text=_render_kept([_node_text(it) for it in items]),
            dropped_count=0, kept_count=len(items),
            original_chars=sum(len(_node_text(it)) for it in items),
            kept_chars=sum(len(_node_text(it)) for it in items),
            compacted=False, summarizer="none",
            reason=f"读不到容量 ⇒ 未压缩，带完整历史继续（照 DSH 自动路径）：{problem}",
        )

    messages = [it if isinstance(it, Mapping) else {"role": "user", "content": str(it)}
                for it in items]
    est = TE.estimate_messages(messages, chars_per_token=spec.chars_per_token, source=spec.source)
    anchor = int(usage_tokens or 0)
    total = max(est.tokens, anchor)
    baseline_source = "usage_anchor" if anchor > est.tokens else "heuristic"
    if total < spec.threshold_tokens:
        return CompactResult(
            text=_render_kept([_node_text(it) for it in items]),
            dropped_count=0, kept_count=len(items),
            original_chars=est.chars, kept_chars=est.chars,
            compacted=False, summarizer="none",
            reason=(f"未到阈值：{total} token（{baseline_source}）< threshold_tokens="
                    f"{spec.threshold_tokens}（= {spec.context_window} × {budget.threshold_ratio}）"
                    "⇒ 一次也不压"),
            threshold_tokens=spec.threshold_tokens, retain_tokens=spec.retain_tokens,
            shadowed_tokens=0, framed_tokens=0, chars_per_token=spec.chars_per_token,
            baseline_source=baseline_source,
        )

    keep = _select_keep(items, spec=spec, chars_per_token=spec.chars_per_token, exclude_first=True)
    first = 1                      # 节点 0（开场简报 = 任务原文 + 身份 + 收件箱）永不遮蔽
    if keep <= first:
        return CompactResult(
            text=_render_kept([_node_text(it) for it in items]),
            dropped_count=0, kept_count=len(items),
            original_chars=est.chars, kept_chars=est.chars, compacted=False, summarizer="none",
            reason=f"超阈值（{total} token ≥ {spec.threshold_tokens}）但可遮蔽的条目为空"
                   f"（keep={keep} ≤ {first}）：节点 0 永不遮蔽，故未压缩",
            threshold_tokens=spec.threshold_tokens, retain_tokens=spec.retain_tokens,
            shadowed_tokens=0, framed_tokens=0, chars_per_token=spec.chars_per_token,
            baseline_source=baseline_source,
        )

    # 被遮蔽的是 `[first, keep-1]` —— 不含节点 0（DSH `CB:379-382`、`:398`：
    # 表层第 0 个节点是 system/开场，区间从 1 起）。第一版写成了 `items[:keep]`，
    # 于是节点 0 一起被折进摘要 —— 那正是"压缩永远压不到任务原文"要挡的形态。
    node0 = _node_text(items[0])
    early = list(items[first:keep])
    kept = list(items[keep:])
    early_messages = messages[first:keep]
    shadowed_tokens = TE.estimate_messages(early_messages,
                                           chars_per_token=spec.chars_per_token).tokens
    if summarize is None:
        summary = _mechanical_summary([_node_text(it) for it in early],
                                      [type(it).__name__ for it in early])
        summarizer = "mechanical"
    else:
        out = summarize(early)
        if not isinstance(out, str) or not out.strip():
            raise ValueError(
                f"注入的 summarize 必须返回非空 str，收到 {type(out).__name__}：{out!r}"
                "（返回空摘要等于把这段历史静默扔掉）")
        summary = out
        summarizer = "llm"
    head = (f"\n\n[早期 {len(early)} 条已压缩（{summarizer}）："
            f"{shadowed_tokens} token 折成摘要，保留最近 {len(kept)} 条原文]\n")
    summary_node = head + summary
    rendered = (node0 + summary_node + "\n--- 最近 " + str(len(kept)) + " 条原文 ---\n"
                + _render_kept([_node_text(it) for it in kept]))
    # "摘要必须更小"比的是替换节点的价 vs 被遮节点的价（DSH：`framedSummaryTokenCount`
    # vs `shadowedTokenCount`）—— 不是整份渲染文本（那里面还有节点 0 与保留的尾部，
    # 拿它去比等于把"没被遮的东西"也算进摘要的账里，第一版就是这么写的）。
    framed_tokens = TE.estimate_text_tokens(summary_node, chars_per_token=spec.chars_per_token)
    if framed_tokens >= shadowed_tokens:
        raise CompactionNotSmallerError(
            f"摘要不比被遮掉的量小：framed={framed_tokens} >= shadowed={shadowed_tokens} "
            f"（判据是 >=，等于也拒 —— DSH `CB:571-572`）。这一趟**不算压过**："
            "压完历史一点没短，而账上会写着'压过了'")
    return CompactResult(
        text=rendered, dropped_count=len(early), kept_count=len(kept),
        original_chars=est.chars, kept_chars=len(rendered), compacted=True,
        summarizer=summarizer,
        reason=(f"token 压力触发：{total} token（{baseline_source}）≥ threshold_tokens="
                f"{spec.threshold_tokens}；早期 {len(early)} 条（{shadowed_tokens} token）"
                f"折成 {summarizer} 摘要（framed {framed_tokens} token，严格更小），"
                f"最近 {len(kept)} 条保留原文；节点 0（任务原文/开场）未遮蔽"),
        threshold_tokens=spec.threshold_tokens, retain_tokens=spec.retain_tokens,
        shadowed_tokens=shadowed_tokens, framed_tokens=framed_tokens,
        chars_per_token=spec.chars_per_token, baseline_source=baseline_source,
        shadowed_range=(first, max(first, keep - 1)),
    )