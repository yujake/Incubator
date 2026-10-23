# -*- coding: utf-8 -*-
"""两档提示词缓存的两件工具：`cache.status`（只读）与 `cache.warm`（写 + 起子进程）。

## 为什么这两件工具只挂给主控 M

它们不是某个角色的职责，而是"用户使用系统"的那一面：看两档缓存落没落地、要不要
重落。真正的用户面是命令行（`agentflow cache status|warm`）与网页上那两个按钮；
工具面这一档是给主控在对话里代跑一条只读读数用的。所以 `roles=("M",)`：A–H、V、L
一个都拿不到 —— 它们既不该看到"缓存花了多少钱"，也不该有一件能自己花钱的工具。

## 两根轴逐条如实声明

- `cache.status`：只读（`side_effect="read"`）、不起子进程（`external="none"`）。
  它读的是读数文件加一次现渲染，零模型调用。
- `cache.warm`：会写读数文件（`side_effect="write_local"`）并起 detached 子进程真发
  请求（`external="exec"`）。带 `dry_run=true` 时只算计划（零花费），但"能花钱"这件事
  由声明说清 —— 声明跟着最坏的那一档走，不跟着这一次调用的实参走。

## 三态

`status` 的返回就是 `cachectl.status()` 那一份：两档 × 四格，`unknown` 的档带理由。
它不是"全部通过"的意思 —— 工具调用成功（`ok(...)`）与"缓存新鲜"是两件事，
所以判定要看 `data["verdict"]["tri"]`，不看工具调用本身的成败。

## 本模块没有接线（这是写下来的决定，不是漏掉的）

本文件不在 `src/agentflow/tools/__init__.py` 的 `_MODULES` 里 ⇒ `build_registry()`
不会装配它，任何角色的工具面上都没有 `cache.status` / `cache.warm`。
理由与"若要挂上要改什么"写在 `docs/KNOWN-UNWIRED.md`（那份清单可机核：
`tests/test_known_unwired_modules.py` 逐条核"清单 == 盘上没装配的模块"）。
业主此前裁定「本轮不挂」：这两件的真实用户面是命令行（`agentflow cache status|warm`）
与网页上那两个按钮，工具面这一档是"主控在对话里代跑一条只读读数"。
"""
from __future__ import annotations

from typing import Any

from .. import schema as S
from .base import ToolRegistry, fail, ok, tool

#: 这两件只挂给主控 M：它们代表"用户面/主控"，不是任何执行角色的活。
_ROLES_M: tuple[str, ...] = ("M",)


def _status_tool() -> Any:
    """`cache.status` 的工具体：现读两档的四格（只读、零花费）。"""
    from .. import cachectl as C

    try:
        doc = C.status()
    except Exception as exc:  # noqa: BLE001 - 读不出来属于"没查成"，不是"缓存是空的"
        return fail(f"缓存状态没读出来：{type(exc).__name__}: {exc}", kind="unreadable")
    return ok(doc)


def _warm_tool(*, lean: str = "off", dry_run: bool = True,
               cap_usd: float | None = None) -> Any:
    """`cache.warm` 的工具体：真预热一档或只给计划（转发到 `cachectl.warm`）。

    默认 `dry_run=True`：工具面的缺省必须是不花钱的那一档。"要不要真花钱"由调用方
    显式给 `dry_run=false`，与命令行上"必给 `--lean`"同一条纪律。
    """
    from .. import cachectl as C

    wanted = str(lean or "off").strip().lower()
    if wanted not in ("on", "off"):
        return fail(f"lean 只认 on / off（收到 {wanted!r}）：能预热的目标恒等于 "
                    "WARM_TARGETS，请求方点不了别的", kind="param_error")
    try:
        code, doc = C.warm(tiers=(wanted,), cap_usd=cap_usd,
                           dry_run=bool(dry_run))
    except Exception as exc:  # noqa: BLE001 - 起不来要如实报，不许静默
        return fail(f"预热没跑起来：{type(exc).__name__}: {exc}", kind="unreadable")
    return ok({"exit_code": int(code), "dry_run": bool(dry_run), **doc})


@tool(
    "cache.status",
    (
        "两档提示词缓存（Lean 关 / Lean 开）的状态读数：每一档给四格 —— 是否落地"
        "（读数文件里有没有那一趟）、是否新鲜（现渲染的 prompt_sha256 与读数是否一致）、"
        "覆盖了几个目标、缺哪些目标（L 在关档是受控缺席，不算缺）。另有换 key 那一条："
        "读数里的 key 指纹与当前不同 ⇒ key.tri=stale 并点名受影响的智能体。"
        "只读、零模型调用"
    ),
    {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=_ROLES_M,
    returns=(
        "{'schema','at','readings','lean_now','prompt_version','key','tiers','reminder',"
        "'verdict'}；tiers 下每档 {'tier','label','tri','reason','warmed','fresh',"
        "'fresh_reason','not_fresh','covered','covered_fresh','total','missing','absent',"
        "'at','prompt_version','spent_usd','key','per_target'}；失败（读不出来）："
        "ok=False + kind(unreadable)"
    ),
    tags=("cache", "prompt", "diagnostic"),
    external="none",
)
def _cache_status() -> Any:  # pragma: no cover - 装配期替换
    """`cache.status` 的声明占位（真正的 handler 由 `register` 绑定）。"""
    return _status_tool()


@tool(
    "cache.warm",
    (
        "预热一档提示词缓存（真发请求、会花钱）：把这一档的每个目标各发一次最小请求，"
        "让上游按那段前缀建索引，并把读数写进读数文件（含 key 指纹）。"
        "dry_run=true（缺省）只渲染与算钱：报要预热几个目标、预计花费、哪些已新鲜可跳过。"
        "只能选 lean=on / off 两档，不能点名目标"
    ),
    {
        "type": "object",
        "properties": {
            "lean": {"type": "string", "enum": ["on", "off"],
                     "description": "落哪一档形式化开关（on / off；两档各自的 system 不同）"},
            "dry_run": {"type": "boolean",
                        "description": "只算计划、不发请求（缺省 true；给 false 才是真预热）"},
            "cap_usd": {"type": "number",
                        "description": "这一趟的花费上限（美元；不给就用预热脚本里那一个）"},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=_ROLES_M,
    returns=(
        "{'exit_code','dry_run','verdict','tiers'|'results','key','keys_written','readings'}；"
        "dry_run 时 verdict=dry_run 且 tiers 下每档 {'to_warm','skip_fresh','absent','calls',"
        "'tokens_in_est','usd_est'}；失败（参数不在白名单 / 起不来）：ok=False + kind(param_error|unreadable)"
    ),
    tags=("cache", "prompt", "write", "spend"),
    external="exec",
)
def _cache_warm(*, lean: str = "off", dry_run: bool = True,
                cap_usd: float | None = None) -> Any:  # pragma: no cover - 装配期替换
    """`cache.warm` 的声明占位（真正的 handler 由 `register` 绑定）。"""
    return _warm_tool(lean=lean, dry_run=dry_run, cap_usd=cap_usd)


def register(registry: ToolRegistry, **_: Any) -> int:
    """把两件工具装进注册表；返回装进去的件数。

    返回件数是装配面的读数（`tools.build_registry` 用"注册了 0 件"当缺陷报）。
    两件都不需要装配期注入：它们读的是读数文件与当前环境，不是某个 store。
    """
    added = 0
    registry.register(_cache_status.__tool_spec__)
    added += 1
    registry.register(_cache_warm.__tool_spec__)
    added += 1
    return added


__all__ = ["register"]


#: 本模块只认主控 M 这一个角色；`schema` 在这里只用来断言"拼写对得上"
#: （拼错一个字母就会让 `roles=("M",)` 被 `ToolRegistry` 静默过滤掉整组工具）。
assert S.CONDUCTOR_ROLE == "M", "cache_tools 挂给主控，而 schema.CONDUCTOR_ROLE 不是 M"
