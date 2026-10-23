# -*- coding: utf-8 -*-
"""Lean 只角色（L）的可见性：唯一判定入口。

业主 2026-10-22 的施工单（逐字）：「在Lean开关没开时隔绝L，也是保证待会那次跑的
测试不受干扰」。开关没开时 L 不许出现在任何面向模型/用户的地方 —— 不是"它跑不动"，
而是"它不存在"：角色表里没有它、`formal.*` 不装配、提示词里一个字都不提它、
按名取它的每一个入口给受控拒绝（理由 `lean_off`）。

## 为什么必须只有一个入口

同一个开关在本仓被读过很多次（读数的、提示词的、装配的），而"每处自己判一遍"的
失效形态是静默的：某一条判据在关着时看着是对的，另一条在开着时看着是对的，中间
没有人把两处放在一起看。所以：

- 判定的真身只有 :func:`lean_reading` 一个函数（它读
  `settings.lean_enabled()` —— 那一条是开关梯子的唯一实现：环境变量
  `AGENTFLOW_LEAN_ENABLED` 压过设置文件 `toolchain.lean_enabled`，再压过产品缺省）；
- 其余每一处（角色表、工具装配、提示词、按名取角色的工具、读数）都调本模块的
  :func:`is_hidden` / :func:`visible_roles` / :func:`require_visible`，
  不再自己 `SET.lean_enabled()` 一遍；
- `agent_prompts._lean_switch` 是唯一的例外，而它不是第二个判定：它转调
  :func:`lean_reading`，只是给自己加了一个 `lru_cache`（提示词的同一趟里必须
  前缀稳定）。那个缓存由 `agent_prompts.reset_toolchain_readings()` 清 ——
  也就是本模块的配置重载口。

## 为什么不缓存

本模块不留任何模块级缓存：每一次调用都现读 `settings.lean_enabled()`。理由是同
进程内改开关是真实用法（判据要逐档跑，用户也可能在网页上改设置文件）：缓存住旧值
的形态是"改了开关不生效"，而它在读数上与"改了开关但这一档本来就这样"完全一样。
代价是每次多一次设置文件读取（那是一个小 JSON，缺文件时直接走缺省）；换来的性质是
"改了开关，下一次调用就跟上"这件事不需要任何人记得去清缓存。

## 三态

`lean_reading().verdict` 三档：`"on"` / `"off"` / `"unknown"`。第三档是
"这一格读不出来"（`settings.lean_enabled` 对词表外的值抛 `ValueError`，例如
`"maybe"` / `"flase"`）：按"关"处理（L 一样被隔绝），并在 `reason` / `detail`
里如实说"读不出"，好让读者分得清"用户关了它"与"配置写坏了"。

## 今天只有 L 是"由开关决定存在性"的角色

:data:`LEAN_ONLY_ROLES` 是那份名单（今天只有 `L`）。E 不在这里：E 的大部分本事
（数值实验、查询、登记）与 Lean 无关，开关只改它那一面的一套文案 —— 那条路由
`specs/e.py` 的改写表承担，与本模块无关。
2026-10-22 晚裁定之后 E 的行为面也不再受本模块影响：它的 Lean 侧写死关闭
（`agent_e._support.E_LEAN_SIDE_HARD_OFF`，受控拒绝码 `formal_moved_to_l`），
两档下逐字相同 —— 本模块只管 `L` 的存在性，以及 E 那份文案里"指向谁"的措辞。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import settings as SET

#: 由 Lean 开关决定"存不存在"的角色（今天只有 L：Lean 形式化者）。
#:
#: 为什么是显式名单而不是"看它有没有 formal 工具"：工具面依赖装配结果，而装配又
#: 依赖这份名单 —— 从工具面反推会成环。名单本身很短，且它就是业主要的那一句
#: "L 这个角色只在开关打开时存在"。
LEAN_ONLY_ROLES: tuple[str, ...] = ("L",)

#: 只在 Lean 开关打开时才装配的工具模块（`tools._MODULES` 里的模块名）。
#:
#: 落在这里而不是 `tools/__init__.py` 里写死：那个文件是禁改区，而"哪几个模块是
#: Lean 专属的"这件事与角色名单是同一条口径，两处分开写必然漂。
LEAN_ONLY_TOOL_MODULES: tuple[str, ...] = ("formal_tools",)

#: 开关开着时的理由码（"它为什么可见"）。
REASON_ON = "lean_on"

#: 开关关着时的理由码（"它为什么被隔绝"）。按名取 L 的入口用它。
REASON_OFF = "lean_off"

#: 开关读不出时的理由码（按"关"处理，但读数里必须说清是读不出）。
REASON_UNREADABLE = "lean_unreadable"


@dataclass(frozen=True)
class LeanReading:
    """开关这一档的读数（一次现读的完整结论，不是"值 + 注释"）。

    六格的分工：`verdict` 是三态（`"on"` / `"off"` / `"unknown"`）、`enabled`
    是"能不能按开着处理"（`unknown` 时为 False，即 fail-closed）、`reason` 是
    受控理由码、`source` 是"这个值是哪一档给的"（`"env"` / `"settings"` /
    `""` / `"unreadable"`，与 `agent_prompts._lean_switch` 既有那两个取值逐字
    一致）、`detail` 是一句人话（"读不出"时必须写清读到了什么）。
    """

    verdict: str
    enabled: bool
    reason: str
    source: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        """可序列化的形状（读数进回执/日志时用它，别手拼字段）。"""
        return {
            "verdict": self.verdict,
            "enabled": self.enabled,
            "reason": self.reason,
            "source": self.source,
            "detail": self.detail,
        }


def lean_reading(*, env: Mapping[str, str] | None = None,
                 path: str | Path | None = None) -> LeanReading:
    """现读一次开关。这是本模块唯一读开关的地方（其余函数都调它）。

    `env` / `path` 只为让判据能喂一个确定的环境（产品路径不传，读的是真的那一档）：
    它们不是第二条产生路径，传与不传走的都是 `settings.lean_enabled` 这一条梯子。

    读不出（`ValueError` / `OSError`）时按"关"处理并把原话留在 `detail` 里：
    一个读不懂的配置不该让整趟跑不起来，也不该被当成"用户打开了形式化"。
    """
    try:
        enabled, source = SET.lean_enabled(path, env=env)
    except (ValueError, OSError) as exc:
        return LeanReading(
            verdict="unknown",
            enabled=False,
            reason=REASON_UNREADABLE,
            source="unreadable",
            detail=(f"{SET.ENV_LEAN_ENABLED} / 设置文件 toolchain.{SET.LEAN_ENABLED_KEY}"
                    f" 这一格读不懂：{type(exc).__name__}: {exc}"),
        )
    if enabled:
        return LeanReading(verdict="on", enabled=True, reason=REASON_ON,
                           source=str(source or ""), detail=_where(source, True))
    return LeanReading(verdict="off", enabled=False, reason=REASON_OFF,
                       source=str(source or ""), detail=_where(source, False))


def _where(source: str | None, on: bool) -> str:
    """"这个值是哪一档给的"那句人话（与 `toolchain_facts_text` 的 where 表同口径）。"""
    word = "true" if on else "false"
    if str(source) == "env":
        return f"环境变量 {SET.ENV_LEAN_ENABLED} = {word}"
    if str(source) == "settings":
        return f"设置文件 toolchain 段的 {SET.LEAN_ENABLED_KEY} = {word}"
    return f"没有设这一格，用的是产品缺省 {SET.DEFAULT_LEAN_ENABLED}"


def lean_on() -> bool:
    """这一档算不算"开着"（读不出算关 —— fail-closed，见模块 docstring 的三态）。"""
    return lean_reading().enabled


def is_hidden(role: str) -> bool:
    """这个角色在这一档下是不是"不存在"。

    只对 :data:`LEAN_ONLY_ROLES` 里的角色可能为真；其余角色恒为假（它们的可见性
    与 Lean 开关无关）。这一句是"隔绝"的唯一判据 —— 装配、提示词、按名取角色的
    入口、读数全部读它。
    """
    if str(role) not in LEAN_ONLY_ROLES:
        return False
    return not lean_reading().enabled


def visible_roles(roles: Iterable[str]) -> tuple[str, ...]:
    """过滤一串角色名：把这一档下不存在的那些去掉（顺序不变）。"""
    return tuple(role for role in roles if not is_hidden(role))


class RoleHidden(ValueError):
    """按名取一个"这一档下不存在的角色"时抛的受控拒绝。

    为什么是 `ValueError` 的子类：调用方既有的形态是"这个参数不成立"
    （例如 `AgentRegistry.get` 对没登记的角色抛 `KeyError`）。带上 `reason` 与
    `reading` 之后，调用方能把"角色名拼错了"与"这个角色在这一档下不存在"分开 ——
    两者该做的事不同（改拼法 / 打开开关或改派）。
    """

    def __init__(self, role: str, reading: LeanReading, *, surface: str = "") -> None:
        self.role = str(role)
        self.reading = reading
        self.surface = str(surface or "")
        where = f"（{self.surface}）" if self.surface else ""
        super().__init__(
            f"角色 {self.role}{where} 只在 Lean 形式化开关打开时存在："
            f"reason={reading.reason}；{reading.detail}")


def require_visible(role: str, *, surface: str = "") -> None:
    """不存在的角色就抛 :class:`RoleHidden`（各入口的第一句）。

    `surface` 是"哪个入口拒绝的"（`system_prompt` / `registry.get` / …）：
    拒绝那一刻说清是哪一层，读者才知道该去哪一层看。
    """
    if is_hidden(role):
        raise RoleHidden(role, lean_reading(), surface=surface)


def hidden_refusal(role: str, *, surface: str = "") -> dict[str, Any]:
    """把"这个角色在这一档下不存在"做成一个可回执的拒绝（工具层用它）。

    形状与既有的受控拒绝一致：`ok=False` + 一句人话 + 受控理由码
    （`reason` 取 :data:`REASON_OFF` / :data:`REASON_UNREADABLE`）+ 读数六格。
    `tri="refused"` 是三态位：这一格是"查过了、结论是不给"，不是"没查成"。
    """
    reading = lean_reading()
    where = f"（{surface}）" if surface else ""
    return {
        "ok": False,
        "tri": "refused",
        "role": str(role),
        "summonable": False,
        "reason": reading.reason,
        "error": (f"角色 {role}{where} 只在 Lean 形式化开关打开时存在："
                  f"{reading.detail}。要用它就把开关打开"
                  f"（环境变量 {SET.ENV_LEAN_ENABLED}=1 或设置文件 "
                  f"toolchain.{SET.LEAN_ENABLED_KEY} = true），"
                  f"否则改派别的角色（这一档下不要为形式化花钱）。"),
        "lean": reading.to_dict(),
    }


__all__ = [
    "LEAN_ONLY_ROLES",
    "LEAN_ONLY_TOOL_MODULES",
    "LeanReading",
    "REASON_OFF",
    "REASON_ON",
    "REASON_UNREADABLE",
    "RoleHidden",
    "hidden_refusal",
    "is_hidden",
    "lean_on",
    "lean_reading",
    "require_visible",
    "visible_roles",
]
