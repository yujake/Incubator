# -*- coding: utf-8 -*-
"""两档提示词缓存的用户面：状态读数、预热计划、真预热、换 key 的提醒。

## 这一层回答什么问题

上游的前缀缓存是服务端自动建的，写不写由"前缀逐字节相同"决定
（`scripts/warm_prompt_cache.py` 的模块 docstring 逐字讲了这件事）。于是产品上
"缓存落没落地"只能靠两条读数回答：

- 落地：读数文件里这一档（`lean_enabled` 为假 / 为真）有没有那一趟预热，那一趟
  里每个目标有没有一条真的调用行；
- 新鲜：按这一档重新渲染一遍 `system_prompt`，摘要（`prompt_sha256`）与那一趟
  记下来的是否逐字节相同。提示词一改缓存就作废，而"作废"在读数上与"没预热"
  是同一件事，所以这一格必须现算，不能抄读数。

本模块只做三件事：读（:func:`status`）、算（:func:`plan`）、落（:func:`warm`）。
渲染与读数的实现仍然只有一个真身 —— `scripts/warm_prompt_cache.py`（按路径加载，
见 :func:`_warm_module`），所以"预热了什么"与"判据按什么重算"是同一份代码。
两处各写一份的话，漂了以后在读数上长得像"提示词改了、该重新预热"。

## 三态

每一档给四格（落地 / 新鲜 / 覆盖几个 / 缺谁），每格都按三态读：

- `found`：查到了，结论就在同一格；
- `unknown`：没查成，`reason` 里说清为什么（`cache_missing_for_lean_state` /
  `cache_readings_unreadable` / `render_failed: ...`）；
- "查到了但没有"：`warmed=False` 或 `fresh=False`，附点名。

不知道为什么要有这一档：`cache_readings()` 在"这一档没有读数"时返回
`tri="unknown"`，本模块照抄那一格，绝不回落到另一档 —— 回落会把"这一档没预热"
读成"读到了另一档的摘要"，而那种假绿没有任何地方会报错。

## 当前这一趟用哪一档（`active`）

两档各自的状态回答"两档落没落地"，回答不了"我现在打开的网页会用哪一档"。这一格按
三层来源定，且每一层都自报来源（`active.source`）：

1. `source="run"`：这个工作区里有正在跑（或最近一趟）的运行记录、且记录里带着那一趟
   的 lean 状态 ⇒ 用那一趟的开关。记录落在
   `<工作区>/runs/cache-active-<会话号>.json`（`lean_enabled` / `tier` / `sid` /
   `pid` / `at`），由起跑那一刻的 :func:`run_reading` 写下。正在跑与最近一趟不同时
   优先正在跑：活着的判据是 `<工作区>/runs/<角色>-<会话号>.pid` 里那个 pid 还在
   （`stopctl.alive`）。
2. `source="process"`：这个工作区没有运行记录 ⇒ 退回本进程的开关
   （`leanscope.lean_on()`），文案里写明"按本进程开关"。
3. `source="unknown"`：运行记录文件在、但读不出来（坏 JSON / 没记 lean / 列不出目录）
   ⇒ `tri="unknown"` 加理由。这一档绝不拿本进程开关冒充那一趟的开关。

工作区怎么找：显式 `root` > 环境变量 `AGENTFLOW_WORKSPACE_ROOT` > 进程命令行
`--root`（网页进程正是被它起来的）。都取不到就落到第 2 层，文案里说清"工作区不可判定"。

选中哪一档之后，档位与覆盖数仍然只走一条路 —— 调 `tier_reading(那一档)`（它内部调
`cache_readings(lean=那一档)`），与上面两档的四格是同一个入口、同一份读数，于是
"哪一档在用"与"那一档落地了没有"不可能各算一套。那一档的读数读不出来 ⇒
`tri="unknown"` 加人话理由（`why`），绝不回落到另一档。

## 起跑时那一行（`run_reading`）

`status` 是"用户主动问一次"，回答不了"跑起来以后这一趟命中的是哪一档"。业主 2026-10-23
的口径是两档缓存要有"能调用的工具 ＋ 状态显示"，而审计发现运行期一次都没读过读数，
于是补了这一格：每次起跑读一次 `active`，折成一行读数打出来（新鲜 ⇒ `缓存：使用 …`；
不新鲜 / 未落地 / 换了 key ⇒ 一行 warning 指向『试算』）。它只加读数、不拦跑 ——
不新鲜的缓存跑起来照样是对的，只是按未命中计费，所以这一行绝不改退出码、也绝不
因此不发请求。读不出来时自己接住异常降级成 warning（这一趟照旧起跑）。

它同时是运行记录的写入点：起跑那一刻把这一趟的 lean 状态记进
`<工作区>/runs/cache-active-<会话号>.json`（原子替换：先写 `.tmp` 再 `os.replace`），
于是另一条进程（网页）问"当前使用哪一档"时读到的是这一趟的开关，而不是它自己的。
写不成不拦跑：那一格退回 `source="process"`，文案里说清这个工作区没有运行记录。

## 换 key 的重落提醒

上游前缀缓存挂在（模型 + 端点 + 账号）这一片上；换 key 或换厂商，等于换了一片
空缓存。所以每一趟预热在读数里记一个 key 指纹（`sha256(key)[:16]`，外加模型名与
base_url，不存 key 本身），读数时与当前这一片比较：

- 相同 ⇒ `key.tri="same"`；
- 不同 ⇒ `key.tri="stale"`，并点名受影响的智能体：渲染出来的提示词里出现了那一对
  模型名的那几个；一个都没出现 ⇒ 所有目标都受影响（缓存按模型分片，不是按文案）；
- 旧读数里没有指纹（本模块落地之前预热的）⇒ `key.tri="unknown"`，理由是
  `key_fingerprint_missing`。这一档不是"没换过"，是"换没换过不可判定"。

## 默认零花费

`status` 与 `warm(dry_run=True)` 都不发请求（只渲染）。真预热只在用户显式敲
`cache warm` 且不给 `--dry-run`（或按网页上那两个按钮）时发生，且发第一发之前
先打印 key 的来源、模型与 base_url（不打印 key 本身）。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping

from . import agent_prompts as AP
from . import leanscope as LEANSCOPE
from .canonical import json_default

__all__ = [
    "ACTIVE_NAME",
    "DEFAULT_READINGS",
    "ENV_WORKSPACE_ROOT",
    "EXIT_FRESH",
    "EXIT_STALE",
    "EXIT_UNKNOWN",
    "REASON_ABSENT",
    "REASON_KEY_FINGERPRINT_MISSING",
    "REASON_NO_READINGS",
    "REASON_RUN_RECORD_UNREADABLE",
    "RUN_INFO",
    "RUN_RECORD_PREFIX",
    "RUN_STATE_RECENT",
    "RUN_STATE_RUNNING",
    "RUN_WARNING",
    "SOURCE_PROCESS",
    "SOURCE_RUN",
    "SOURCE_UNKNOWN",
    "TIER_LABEL",
    "TIERS",
    "active_reading",
    "add_subcommands",
    "annotate_run",
    "fingerprint",
    "key_reading",
    "plan",
    "record_active_run",
    "run",
    "run_reading",
    "run_record_reading",
    "status",
    "warm",
    "workspace_root",
]

#: 两档形式化开关在读数里的名字。`off` = `lean_enabled=false`，`on` = `true`。
TIERS: tuple[str, ...] = ("off", "on")

#: 人读的那一列（命令行与网页共用同一套字，免得两处叫法不同）。
TIER_LABEL: Mapping[str, str] = {"off": "Lean 关", "on": "Lean 开"}

#: "当前使用"那一行里的档名（命令行与网页共用这一份；页面把它画成加粗，所以这一行
#: 的正文只由 :func:`_active_text` 拼一次，两个面孔都不另拼一份）。
ACTIVE_NAME: Mapping[str, str] = {"off": "非 Lean 版缓存", "on": "Lean 版缓存"}

#: `cache status` / `cache warm --dry-run` 的退出码（三态，与 `scripts/warm_prompt_cache.py`
#: 和 `noai_gate.py` 同一纪律）：0 = 查过了、两档都新鲜；1 = 查过了、有一档要重落；
#: 2 = 没查成（读数读不出 / 渲染不出来 / 这一档整档没有读数）。unknown 绝不是 0。
EXIT_FRESH = 0
EXIT_STALE = 1
EXIT_UNKNOWN = 2

#: 三态里 `unknown` 那一档的两种理由（与 `warm_prompt_cache` 的两个常量同名同义，
#: 这里只是把"整档没有读数"与"读数文件读不出来"在本层也写出来）。
REASON_NO_READINGS = "cache_missing_for_lean_state"
REASON_KEY_FINGERPRINT_MISSING = "key_fingerprint_missing"

#: 受控缺席（这一档按产品设计不存在那个目标）的词，来自读数行的 `kind="absent"`。
REASON_ABSENT = "lean_off"

#: "当前使用哪一档"的三层来源（`active.source`）：运行记录 / 本进程开关 / 读不出来。
SOURCE_RUN = "run"
SOURCE_PROCESS = "process"
SOURCE_UNKNOWN = "unknown"

#: 运行记录那一格的两种状态：正在跑的那一趟 / 最近一趟（都不是就是没有记录）。
RUN_STATE_RUNNING = "running"
RUN_STATE_RECENT = "recent"

#: 这一趟的开关记录落在 `<工作区>/runs/` 下的文件名前缀（一份会话一份，起跑时覆盖）。
RUN_RECORD_PREFIX = "cache-active-"

#: 运行记录读不出来时的理由码（这一格是 unknown，不许冒充 run 或 process）。
REASON_RUN_RECORD_UNREADABLE = "run_record_unreadable"

#: 工作区根可以显式给的那一格。产品路径从进程命令行 `--root` 取（网页进程正是被它
#: 起来的），这一格是给"命令行里没有 --root、但调用方知道工作区"的场合留的出口。
ENV_WORKSPACE_ROOT = "AGENTFLOW_WORKSPACE_ROOT"

#: 读数文件的缺省落点。真身是 `warm_prompt_cache.DEFAULT_READINGS`，这里在调用期取，
#: 不另抄一份路径（抄一份就会在别人搬家时静默指向旧位置）。
DEFAULT_READINGS_HINT = "tests/fixtures/prompt_cache_warm.json"

#: 渲染结果的进程内缓存：提示词在一次进程生命周期里不会变，而网页的读数面板会
#: 跟着每条 SSE 事件重取一次 —— 不缓存的话每次要重新渲染十二个 system（实测 0.53 秒）。
_RENDERS: dict[str, dict[str, dict[str, Any]]] = {}

#: 切开关渲染要动 `AGENTFLOW_LEAN_ENABLED` 与 `agent_prompts` 的那个闩，两件事都不是
#: 线程安全的。网页服务是并发的，所以这一段串行化（`warm` 内部也只用这一次）。
_RENDER_LOCK = threading.Lock()

#: 按路径加载 `scripts/warm_prompt_cache.py` 的结果（`scripts/` 不是包，不能普通 import）。
_WARM_MODULE: ModuleType | None = None


def _repo_root() -> Path:
    """交付包根（`agentflow/`）：本文件在 `src/agentflow/cachectl.py` 下。"""
    return Path(__file__).resolve().parents[2]


def _warm_module() -> ModuleType:
    """按路径加载预热脚本，只加载一次。

    为什么必须有这一个入口：新鲜度的口径是 `prompt_sha256(system)`，而算它的函数、
    渲染的场景事实、受控缺席的规则全在那个脚本里。本模块要是自己再渲染一份，
    "现渲染的摘要"与"预热时的摘要"就成了两份实现 —— 它们漂了以后，读数会显示
    "提示词改了、该重新预热"，而提示词一个字都没动。
    """
    global _WARM_MODULE
    if _WARM_MODULE is not None:
        return _WARM_MODULE
    path = _repo_root() / "scripts" / "warm_prompt_cache.py"
    spec = importlib.util.spec_from_file_location("_agentflow_warm_prompt_cache", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"读不到预热脚本：{path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_agentflow_warm_prompt_cache", mod)
    spec.loader.exec_module(mod)
    _WARM_MODULE = mod
    return mod


def default_readings_path() -> Path:
    """读数文件的缺省落点（唯一真身在预热脚本里）。"""
    return Path(_warm_module().DEFAULT_READINGS)


def all_targets() -> tuple[str, ...]:
    """要预热的目标全集（唯一真身在预热脚本里；含受控缺席的 L 与秘书）。"""
    return tuple(_warm_module().WARM_TARGETS)


def _sha(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def fingerprint(key: str) -> str:
    """key 的指纹：`sha256(key)[:16]`（空 key ⇒ 空串，不是某个哈希）。

    只记指纹、不记 key：读数文件会被提交进仓库（`tests/fixtures/`），真 key 进去
    就是泄漏。十六位足够分辨"换了没换"，而它反推不出 key。
    """
    raw = str(key or "")
    return "" if not raw else _sha(raw)[:16]


def key_reading() -> dict[str, Any]:
    """当前这一片缓存的身份读数：指纹 / 模型 / base_url / 来源（不打印 key 本身）。

    `configured=False` 时指纹是空串：没配 key 就读不到"当前是哪一片"，这一格如实
    留空，不许拿设置文件里的某个旧值顶上。
    """
    from . import modelgw as MG

    spec = MG.spec_from_env()
    model = str(getattr(spec, "model", "") or "")
    base_url = str(getattr(spec, "base_url", "") or "")
    api_key = str(getattr(spec, "api_key", "") or "")
    return {
        "configured": bool(getattr(spec, "configured", False)),
        "source": str(getattr(spec, "key_source", "") or ""),
        "model": model,
        "base_url": base_url,
        # 只给长度，不给内容：读数面板要能看出"有 key / 没 key"，但 key 本身不上屏。
        "key_chars": len(api_key),
        "fingerprint": fingerprint(api_key),
    }


def clear_render_cache() -> None:
    """丢掉渲染缓存（判据在临时目录里换环境时用它；网页与命令行不用调）。"""
    with _RENDER_LOCK:
        _RENDERS.clear()


def render_tier(tier: str) -> dict[str, dict[str, Any]]:
    """按某一档渲染全部目标（只渲染，不发请求，零花费）。

    为什么要真的切开关：形式化关着时 `system_prompt` 会把 Lean 那一整套段换成另一
    份（`_apply_no_lean_variant`），于是两档的 system 逐字节不同、摘要也不同。
    抄当前开关那一档的摘要去比另一档，结论恒为"不新鲜"或恒为"新鲜"，两种都是假读数。

    切的是渲染真正读的那个闩（`AGENTFLOW_LEAN_ENABLED` 加 `agent_prompts` 的
    `reset_toolchain_readings()`），与预热脚本 `--lean on|off` 走的是同一条路；
    收尾无条件还原，免得"看一眼状态"把进程的开关改了。
    """
    if tier not in TIERS:
        raise ValueError(f"只认两档 {TIERS}，收到 {tier!r}")
    with _RENDER_LOCK:
        cached = _RENDERS.get(tier)
        if cached is not None:
            return cached
        env_name = "AGENTFLOW_LEAN_ENABLED"
        prev = os.environ.get(env_name)
        try:
            os.environ[env_name] = "1" if tier == "on" else "0"
            AP.reset_toolchain_readings()
            rendered = _warm_module().render_prompts()
        finally:
            if prev is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = prev
            AP.reset_toolchain_readings()
        _RENDERS[tier] = rendered
        return rendered


def render_all(tiers: Iterable[str] = TIERS) -> dict[str, dict[str, dict[str, Any]]]:
    """两档各渲染一遍（`{档: {目标: 渲染项}}`）。"""
    return {tier: render_tier(tier) for tier in tiers}


def _sha_matches(recorded: str, now: str) -> bool:
    """读数里的摘要与现渲染的摘要是否同一段提示词（空摘要一律算不一致）。

    单独一个函数是为了让判据能打桩（反真空那一档把"新鲜度比对"打成恒真，看主判据
    是否当场变红）。真正的比较逻辑只在这里。
    """
    return bool(str(recorded or "").strip()) and str(recorded) == str(now)


def _key_matches(recorded: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """读数里那一趟用的 key / 模型 / 端点与当前这一片是否同一片缓存。

    三个格子都不同名同义地比：`fingerprint`（key 本身）、`model`、`base_url`。
    `base_url` 只有两边都非空时才比 —— 旧读数可能没记它，拿空串当"不同"会把所有
    老读数都判成"换了厂商"（而那是另一件事）。
    """
    if str(recorded.get("fingerprint") or "") != str(current.get("fingerprint") or ""):
        return False
    if str(recorded.get("model") or "") != str(current.get("model") or ""):
        return False
    rec_base = str(recorded.get("base_url") or "")
    cur_base = str(current.get("base_url") or "")
    if rec_base and cur_base and rec_base != cur_base:
        return False
    return True


def _changed_labels(recorded: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """哪几格变了（只给"变了"的那几格，全是人话里的名字）。"""
    out: list[str] = []
    if str(recorded.get("fingerprint") or "") != str(current.get("fingerprint") or ""):
        out.append("key")
    if str(recorded.get("model") or "") != str(current.get("model") or ""):
        out.append("模型")
    rec_base = str(recorded.get("base_url") or "")
    cur_base = str(current.get("base_url") or "")
    if rec_base and cur_base and rec_base != cur_base:
        out.append("接口地址")
    return out


def _affected_targets(renders: Mapping[str, Mapping[str, Any]],
                      recorded: Mapping[str, Any], current: Mapping[str, Any],
                      present: Iterable[str]) -> tuple[list[str], str]:
    """受换 key 影响的智能体（有名字在提示词里 ⇒ 那几个；否则全部）。

    判据：渲染出来的 system 里出现了那一对模型名（旧名或新名）的目标，就是"提示词
    里带模型特有段"的那几个。一个都没出现时，结论不是"没人受影响"，而是"全部受影响"
    —— 上游按模型分片建索引，换模型等于换一片空缓存，与文案里有没有提模型无关。
    """
    names = [n for n in (str(recorded.get("model") or ""), str(current.get("model") or ""))
             if n.strip()]
    hits: list[str] = []
    for target in present:
        system = str(renders.get(target, {}).get("system") or "")
        if any(name in system for name in names):
            hits.append(target)
    if hits:
        return hits, "model_named_in_prompt"
    return [t for t in present], "all_targets"


def _reminder_text(recorded: Mapping[str, Any], current: Mapping[str, Any],
                   changed: list[str], affected: list[str]) -> str:
    """换 key 那条提醒的正文（命令行最后一行与网页横幅用同一句）。"""
    bits: list[str] = []
    if "key" in changed:
        bits.append(f"key 指纹 {str(recorded.get('fingerprint') or '(旧读数没记)'):16} → "
                    f"{str(current.get('fingerprint') or '(没有 key)'):16}")
    if "模型" in changed:
        bits.append(f"模型 {recorded.get('model') or '(空)'} → {current.get('model') or '(空)'}")
    if "接口地址" in changed:
        bits.append(f"接口地址 {recorded.get('base_url') or '(空)'} → "
                    f"{current.get('base_url') or '(空)'}")
    who = "、".join(affected) if affected else "（没有可点名的目标）"
    return ("换了 " + "，".join(bits) + "：这一档缓存要重落（上游按模型 + 端点 + 账号分片）；"
            f"受影响智能体：{who}")


def _empty_key_state() -> dict[str, Any]:
    """`key` 那一格的空形态（每一档都带这一格，下游不必判有没有）。"""
    return {"tri": "unknown", "reason": REASON_KEY_FINGERPRINT_MISSING,
            "changed": [], "affected": [], "affected_why": "", "text": "",
            "recorded": {"fingerprint": "", "model": "", "base_url": ""}}


def _absent_reason(renders: Mapping[str, Mapping[str, Any]], target: str) -> str:
    """受控缺席的理由原文（渲染项里没有就如实留空，不编一个）。"""
    return str(renders.get(target, {}).get("absent_reason") or "")


def _per_target(readings: Mapping[str, Any], renders: Mapping[str, Mapping[str, Any]],
                targets: Iterable[str]) -> dict[str, dict[str, Any]]:
    """逐目标的三格：这一趟量过没有（state）/ 摘要是不是同一段（fresh）/ 现在的摘要。

    `state` 照抄 `cache_readings()` 的三态（`measured` / `absent` / `missing`），
    `fresh` 只在 `measured` 上才有意义：其余两档是 `None`（不是 False —— "没量"
    与"量了但变了"是两件事）。
    """
    got: dict[str, Any] = dict(readings.get("targets") or {})
    out: dict[str, dict[str, Any]] = {}
    for target in targets:
        row = dict(got.get(target) or {})
        state = str(row.get("state") or "missing")
        now_sha = str(renders.get(target, {}).get("prompt_sha256") or "")
        recorded_sha = str(row.get("prompt_sha256") or "")
        fresh: bool | None = None
        if state == "measured":
            fresh = _sha_matches(recorded_sha, now_sha)
        out[target] = {"state": state, "fresh": fresh,
                       "recorded_sha256": recorded_sha, "now_sha256": now_sha,
                       "absent_reason": str(row.get("absent_reason") or "")}
    return out


def tier_reading(tier: str, *, path: Path | None = None,
                 renders: Mapping[str, Mapping[str, Any]] | None = None,
                 key: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """一档的四格读数（落地 / 新鲜 / 覆盖几个 / 缺谁）加 key 那一格。

    `renders=None` 时现渲染这一档（只渲染、零花费）；判据可以把渲染结果注入进来，
    于是"新鲜度"这条判据不依赖这台机器上装没装什么。

    整档没有读数时，四格全部落在 `unknown` 那一档，`missing` 是全部目标 —— 不是
    "缺 L"，也不是"回落到另一档"。这一条是本模块最要紧的一条：两种假绿都从
    "找不到就换一份读"开始。
    """
    if tier not in TIERS:
        raise ValueError(f"只认两档 {TIERS}，收到 {tier!r}")
    warm = _warm_module()
    targets = tuple(warm.WARM_TARGETS)
    out_path = Path(path) if path is not None else default_readings_path()
    current_key = dict(key) if key is not None else key_reading()
    readings = warm.cache_readings(lean=(tier == "on"), path=out_path)
    rendered = dict(renders) if renders is not None else render_tier(tier)

    doc: dict[str, Any] = {
        "tier": tier,
        "label": TIER_LABEL[tier],
        "lean_enabled": tier == "on",
        "tri": "unknown",
        "reason": "",
        "warmed": False,
        "fresh": None,
        "fresh_reason": "",
        "not_fresh": [],
        "version_mismatch": False,
        "covered": 0,
        "covered_fresh": 0,
        "total": len(targets),
        "missing": list(targets),
        "absent": [],
        "absent_reason": {},
        "at": "",
        "prompt_version": "",
        "readings_prompt_version": "",
        "spent_usd": None,
        "model": "",
        "per_target": {},
        "key": _empty_key_state(),
    }

    run = readings.get("run")
    if str(readings.get("tri")) != "found" or not isinstance(run, Mapping):
        doc["reason"] = str(readings.get("reason") or REASON_NO_READINGS)
        # 整档没有读数时，"受控缺席"这一档照样读得出来（它由渲染决定，不由读数决定）：
        # L 在 Lean 关那一档按产品规则不存在，把它算进"缺谁"会让人去补一趟不该补的活。
        per_empty = {t: {"state": ("absent" if str(rendered.get(t, {}).get("kind")) == "absent"
                                  else "missing"),
                         "fresh": None, "recorded_sha256": "", "now_sha256": "",
                         "absent_reason": ("" if str(rendered.get(t, {}).get("kind")) != "absent"
                                           else _absent_reason(rendered, t))}
                     for t in targets}
        doc["per_target"] = per_empty
        doc["absent"] = [t for t in targets if per_empty[t]["state"] == "absent"]
        doc["absent_reason"] = {t: per_empty[t]["absent_reason"] for t in doc["absent"]}
        doc["missing"] = [t for t in targets if per_empty[t]["state"] == "missing"]
        doc["covered"] = 0
        doc["covered_fresh"] = 0
        return doc

    per = _per_target(readings, rendered, targets)
    measured = [t for t in targets if per[t]["state"] == "measured"]
    absent = [t for t in targets if per[t]["state"] == "absent"]
    missing = [t for t in targets if per[t]["state"] == "missing"]
    recorded_version = str(run.get("prompt_version") or "")
    not_fresh = [t for t in measured if not per[t]["fresh"]]
    version_mismatch = bool(recorded_version) and recorded_version != str(AP.PROMPT_VERSION)
    fresh = (not not_fresh) and not version_mismatch
    doc.update({
        "tri": "found",
        "warmed": True,
        "fresh": fresh,
        "fresh_reason": ("提示词版本变了：读数里是 "
                         f"{recorded_version}，现在是 {AP.PROMPT_VERSION}" if version_mismatch
                         else ("" if fresh else "这些目标的现渲染摘要与读数不一致")),
        "not_fresh": not_fresh,
        "version_mismatch": version_mismatch,
        "covered": len(measured),
        "covered_fresh": len(measured) - len(not_fresh),
        "missing": missing,
        "absent": absent,
        "absent_reason": {t: _absent_reason(rendered, t) for t in absent},
        "at": str(run.get("at") or ""),
        "prompt_version": str(AP.PROMPT_VERSION),
        "readings_prompt_version": recorded_version,
        "spent_usd": (None if run.get("spent_usd") is None else float(run.get("spent_usd") or 0.0)),
        "model": str(run.get("key_model") or run.get("model") or ""),
        "per_target": per,
    })

    recorded_key = {
        "fingerprint": str(run.get("key_fingerprint") or ""),
        "model": str(run.get("key_model") or run.get("model") or ""),
        "base_url": str(run.get("key_base_url") or run.get("base_url") or ""),
    }
    if not recorded_key["fingerprint"]:
        doc["key"] = {**_empty_key_state(), "recorded": recorded_key, "tri": "unknown",
                      "reason": REASON_KEY_FINGERPRINT_MISSING,
                      "text": ("这一档的旧读数没有 key 指纹（本模块落地之前预热的）"
                               "⇒ 换没换过 key 不可判定；重落一次就会记上")}
        return doc
    if _key_matches(recorded_key, current_key):
        doc["key"] = {**_empty_key_state(), "recorded": recorded_key, "tri": "same",
                      "reason": "", "text": ""}
        return doc
    changed = _changed_labels(recorded_key, current_key)
    present = [t for t in targets if per[t]["state"] != "absent"]
    affected, why = _affected_targets(rendered, recorded_key, current_key, present)
    doc["key"] = {"tri": "stale", "reason": "", "changed": changed,
                  "affected": affected, "affected_why": why,
                  "recorded": recorded_key,
                  "current": {"fingerprint": str(current_key.get("fingerprint") or ""),
                              "model": str(current_key.get("model") or ""),
                              "base_url": str(current_key.get("base_url") or "")},
                  "text": _reminder_text(recorded_key, current_key, changed, affected)}
    return doc


def _lean_now() -> bool:
    """当前形式化开关的唯一读法（判据打桩它来反真空）。

    与 `system_prompt` 判 L 可见性读的是同一个值（`leanscope.lean_on()`），刻意不读
    环境变量：设置文件里开着而 env 没设时，读 env 会印出错的字。
    """
    return bool(LEANSCOPE.lean_on())


def _tier_in_use(lean: bool) -> str:
    """开关 ⇒ 这一趟用哪一档（判据打桩它来反真空：恒 `off` 时"开关开"那一档必红）。"""
    return "on" if lean else "off"


# ---------------------------------------------------------------- 运行记录（这一趟的开关）


def _argv_option(name: str) -> str:
    """进程命令行里那个旗标的值（`--root X` 与 `--root=X` 两种写法都认）。

    为什么要看命令行：`GET /api/cache` 拿不到工作区（那一条端点只转调
    `cachectl.status()`），而网页进程是被 `--root` 起来的 —— 命令行里那个值就是它
    服务的工作区。取不到就返回空串，调用方据此如实说"工作区不可判定"。
    """
    items = [str(item) for item in (sys.argv or [])]
    for index, item in enumerate(items):
        if item == name:
            if index + 1 < len(items):
                return items[index + 1]
        elif item.startswith(name + "="):
            return item[len(name) + 1:]
    return ""


def workspace_root(root: Path | str | None = None) -> Path | None:
    """这一格读的是哪个工作区：显式给的 > 环境变量 > 进程命令行 `--root` > 不可判定。

    不可判定时返回 `None`（不是 `Path.cwd()`）：拿当前目录顶上会读成"这个工作区没有
    运行记录"，而那句话在别的目录下起网页时就变成了谎话。宁可说"工作区不可判定"，
    再退回本进程开关。
    """
    if root is not None and str(root).strip():
        return Path(str(root)).resolve()
    env = str(os.environ.get(ENV_WORKSPACE_ROOT) or "").strip()
    if env:
        return Path(env).resolve()
    raw = _argv_option("--root").strip()
    if raw:
        return Path(raw).resolve()
    return None


def _runs_dir(root: Path) -> Path:
    """`<工作区>/runs/`：目录名与 `stopctl.PID_DIR_NAME` 是一份真身，不另抄一个。"""
    from . import stopctl as SC

    return Path(root) / SC.PID_DIR_NAME


def _file_tag(raw: Any) -> str:
    """会话号 ⇒ 文件名里那一段（只留可移植的字符，空串给 `nosid`）。"""
    keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    text = "".join(ch if ch in keep else "_" for ch in str(raw or ""))
    return text.strip("._") or "nosid"


def _session_sid() -> str:
    """这一趟的会话号：命令行 `--sid`（`--sid=lg2` 也认）> `sessions.session_id()`。"""
    from . import sessions as SS

    return _argv_option("--sid").strip() or SS.session_id()


def _alive(pid: Any) -> bool:
    """这个 pid 还活着吗（探活只有一份真身：`stopctl.alive`）。"""
    try:
        from . import stopctl as SC

        return bool(SC.alive(int(pid or 0)))
    except Exception:  # noqa: BLE001 - 探不了就当"不活着"（最多把正在跑说成最近一趟）
        return False


def record_active_run(*, root: Path | str | None = None, sid: str = "",
                      lean: bool | None = None) -> dict[str, Any]:
    """把这一趟的 lean 状态记进 `<工作区>/runs/cache-active-<会话号>.json`。

    为什么要有这一格：环境变量是进程私有的，网页那条进程读不到跑着的那一趟的开关 ——
    页面上那一格此前只能说网页自己的开关，多进程时就是说反的。把起跑那一刻的开关
    落成一份盘上读数，另一条进程才读得到"正在跑的那一趟"用的是哪一档。

    三态：`written=True` 写成了；写不成（工作区不可判定 / 目录或文件不可写）返回
    `written=False` 与 `reason`。写不成不抛、不拦跑：起跑那一行照旧印，页面上那一格
    退回 `source="process"` 并在文案里说清这个工作区没有运行记录。
    """
    out: dict[str, Any] = {"written": False, "path": "", "reason": ""}
    ws = workspace_root(root)
    if ws is None:
        out["reason"] = "workspace_root_unknown"
        return out
    value = _lean_now() if lean is None else bool(lean)
    sid_text = str(sid or _session_sid())
    path = _runs_dir(ws) / f"{RUN_RECORD_PREFIX}{_file_tag(sid_text)}.json"
    payload = {
        "schema": 1,
        "kind": "cache_active",
        "sid": sid_text,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "lean_enabled": bool(value),
        "tier": _tier_in_use(bool(value)),
        "prompt_version": str(AP.PROMPT_VERSION),
        "pid": int(os.getpid()),
        "workspace_root": str(ws),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n",
                       encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError as exc:
        out["reason"] = f"{type(exc).__name__}: {exc}"
        return out
    out.update({"written": True, "path": str(path)})
    return out


def _parse_run_record(path: Path) -> dict[str, Any]:
    """读一份运行记录；读不懂就抛 `ValueError`（调用方把它记成"读不出来"）。

    只认三样：`sid`（说不清是哪一趟就不算记录）、`lean_enabled`（必须是真布尔，
    "没记"与"记成关"是两件事）、`at`（挑最近一趟用）。其余键只带回 `prompt_version`
    与 `pid`：前者让读者看得出记录是哪一版提示词下写的，后者是探活用的那个号。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{type(exc).__name__}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("不是 JSON 对象")
    sid = str(data.get("sid") or "")
    if not sid:
        raise ValueError("没有 sid（说不清是哪一趟）")
    lean = data.get("lean_enabled")
    if not isinstance(lean, bool):
        raise ValueError("没有 lean_enabled 这一格（这份记录没记 lean 状态）")
    try:
        pid = int(data.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    return {
        "path": str(path),
        "sid": sid,
        "at": str(data.get("at") or ""),
        "lean": bool(lean),
        "tier": _tier_in_use(bool(lean)),
        "prompt_version": str(data.get("prompt_version") or ""),
        "pid": pid,
        "state": "",
    }


def _live_run_sids(root: Path) -> dict[str, str]:
    """`<工作区>/runs/*.pid` 里还活着的那些：会话号 → 角色（读不出来就当没有）。"""
    out: dict[str, str] = {}
    try:
        files = sorted(_runs_dir(root).glob("*.pid"))
    except OSError:
        return out
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        sid = str(data.get("sid") or "")
        if sid and _alive(data.get("pid")):
            out[sid] = str(data.get("role") or "")
    return out


def run_record_reading(*, root: Path | str | None = None) -> dict[str, Any]:
    """这个工作区里正在跑（或最近一趟）的运行记录的 lean 状态。

    三态（`tri`）：

    - `found`：读到一份带 lean 状态的记录；`state` 说它是"正在跑"（`running`，
      同会话的 `*.pid` 还活着）还是"最近一趟"（`recent`）；`record` 是那一份；
    - `missing`：这个工作区没有运行记录（目录不存在 / 一份都没有）—— 调用方退回
      本进程开关。`reason="workspace_root_unknown"` 表示连工作区都没判定出来；
    - `unknown`：记录文件在、但读不出来（坏 JSON / 没记 lean / 列不出目录）——
      `reason=run_record_unreadable`，`detail` 里是原话。这一档不许拿别的来源冒充。

    正在跑与最近一趟不同时优先正在跑；都在就跑得最晚的那一份。
    """
    out: dict[str, Any] = {"tri": "missing", "reason": "", "detail": "",
                           "path": "", "state": "", "record": {}}
    ws = workspace_root(root)
    if ws is None:
        out["reason"] = "workspace_root_unknown"
        return out
    runs = _runs_dir(ws)
    if not runs.exists():
        return out
    try:
        files = sorted(runs.glob(f"{RUN_RECORD_PREFIX}*.json"))
    except OSError as exc:
        out.update({"tri": "unknown", "reason": REASON_RUN_RECORD_UNREADABLE,
                    "detail": f"列不出 {runs}：{type(exc).__name__}: {exc}"})
        return out
    if not files:
        return out
    parsed: list[dict[str, Any]] = []
    problems: list[str] = []
    for path in files:
        try:
            parsed.append(_parse_run_record(path))
        except ValueError as exc:
            problems.append(f"{path.name}：{exc}")
    if not parsed:
        out.update({"tri": "unknown", "reason": REASON_RUN_RECORD_UNREADABLE,
                    "detail": ("；".join(problems) or "运行记录读不出来")[:400]})
        return out
    live = _live_run_sids(ws)
    for record in parsed:
        record["state"] = (RUN_STATE_RUNNING if record["sid"] in live
                           else RUN_STATE_RECENT)
    pool = [r for r in parsed if r["state"] == RUN_STATE_RUNNING] or parsed
    chosen = max(pool, key=lambda r: (r["at"], r["sid"]))
    out.update({"tri": "found", "state": chosen["state"], "path": chosen["path"],
                "record": chosen})
    return out


def _source_text(source: str, record: Mapping[str, Any]) -> str:
    """`active.source_text` 那一格的人话（正文里"来源=…"用的就是它）。"""
    if source == SOURCE_RUN:
        where = ("正在跑的那一趟" if record.get("state") == RUN_STATE_RUNNING
                 else "最近一趟")
        return f"{where} {str(record.get('sid') or '(不知道会话号)')}"
    if source == SOURCE_PROCESS:
        return "按本进程开关"
    return "unknown"


def _source_note(source: str, workspace: Path | None) -> str:
    """来源那一格的补充说明（为什么没读运行记录）；没有要补的就返回空串。"""
    if source == SOURCE_PROCESS:
        return ("工作区不可判定，没敢按运行记录猜" if workspace is None
                else "这个工作区没有运行记录")
    return ""


def _run_record_why(record: Mapping[str, Any]) -> str:
    """运行记录读不出来时 `active.why` 的原话（理由码 ＋ 细节，不编一句）。"""
    reason = str(record.get("reason") or REASON_RUN_RECORD_UNREADABLE)
    detail = str(record.get("detail") or "").strip()
    return f"{reason}：{detail}" if detail else reason


def _active_why(tri: str, fresh: bool, missing: Iterable[str],
                reading: Mapping[str, Any]) -> str:
    """`active.why` 那一格：没查成 / 查到了但不新鲜 / 缺谁，三种各自的原话。

    三态纪律：`tri != "found"` 时这里给的是"为什么没查成"，不是"不新鲜"。
    """
    if tri != "found":
        return str(reading.get("reason") or REASON_NO_READINGS)
    if not fresh:
        named = "、".join(str(t) for t in (reading.get("not_fresh") or []))
        return str(reading.get("fresh_reason") or "") or (f"不新鲜：{named}" if named else
                                                          "这些目标的现渲染摘要与读数不一致")
    left = [str(t) for t in missing]
    return "缺：" + "、".join(left) if left else ""


def _active_text(doc: Mapping[str, Any]) -> str:
    """这一行的人读正文（命令行原样打印，网页把星号画成加粗；两处同一份字）。

    星号是"强调"的标记而不是装饰：业主 2026-10-23 那张施工单给的就是这一句的形状
    （"当前使用：Lean 版缓存（版本 · 覆盖 · 那一趟）｜开关：开"）。做成一份字面量放
    在这里，是为了让"网页上说的档"与"命令行说的档"共用同一个产出点。

    来源必须上这一行（`source_text`）：这一格最要紧的一次误读就是它 —— 页面在说
    web 的开关，而用户要看的是正在跑的那一趟的开关。所以括号里恒有"来源=…"，
    "按本进程开关"与"正在跑的那一趟 lg2"是两句不同的话，不许混。
    """
    source_text = str(doc.get("source_text") or doc.get("source") or "unknown")
    note = str(doc.get("source_note") or "").strip()
    origin = f"来源={source_text}" + (f"；{note}" if note else "")
    if str(doc.get("tri")) != "found":
        why = str(doc.get("why") or "unknown")
        return f"当前没有可用缓存（{origin}；理由：{why}）—— 去点「试算」看要预热什么"
    switch = "开" if doc.get("lean") else "关"
    body = f"{doc.get('prompt_version') or ''} · {doc.get('covered') or '0/0'}"
    absent = [str(t) for t in (doc.get("absent") or [])]
    if absent:
        body += "，" + "、".join(absent) + " 受控缺席"
    # 预热那一趟的时间（`run_at`）刻意不上这一行：现在括号里有"来源=…"点名是哪一趟，
    # 旁边再挂一个没有标签的时间，读者会把它读成来源那一趟的时间（那是另一件事）。
    # 那一格仍在 `active.run_at` 里，要看的自己取。
    missing = [str(t) for t in (doc.get("missing") or [])]
    if missing:
        body += "，缺：" + "、".join(missing)
    elif doc.get("fresh") is False:
        body += "，" + str(doc.get("why") or "不新鲜")
    body += f"，{origin}"
    name = ACTIVE_NAME.get(str(doc.get("tier")), "")
    return f"当前使用：**{name}**（{body}）｜开关：{switch}"


def _active_doc(*, tier: str, lean: bool | None, reading: Mapping[str, Any],
                source: str = SOURCE_PROCESS,
                record: Mapping[str, Any] | None = None,
                workspace: Path | None = None) -> dict[str, Any]:
    """把一档的四格读数折成"当前使用"那一格（键集见 :func:`active_reading`）。

    `source` 是这一档从哪来的（运行记录 / 本进程开关 / 读不出来），`record` 是那一份
    运行记录（`run_record_reading` 的 `record`），`workspace` 是这一格读的是哪个工作区
    （None = 不可判定）。三者一起进正文，于是"这一格说的是谁"不需要读者猜。
    """
    record = dict(record or {})
    tri = str(reading.get("tri") or "unknown")
    total = int(reading.get("total") or 0)
    covered = int(reading.get("covered") or 0) if tri == "found" else 0
    missing = [str(t) for t in (reading.get("missing") or [])]
    absent = [str(t) for t in (reading.get("absent") or [])]
    fresh = bool(reading.get("fresh")) if tri == "found" else False
    doc: dict[str, Any] = {
        "tier": tier,
        "label": ACTIVE_NAME.get(tier, ""),
        "lean": lean,
        #: 档位从哪来：`run` / `process` / `unknown`（见模块 docstring 的三层来源）。
        "source": source,
        "source_text": _source_text(source, record),
        "source_note": _source_note(source, workspace),
        #: 运行记录那一格的三样（`source != "run"` 时是空串）：哪一趟、什么时候、还活着没有。
        "record_sid": str(record.get("sid") or ""),
        "record_at": str(record.get("at") or ""),
        "record_state": str(record.get("state") or ""),
        "strategy": (SOURCE_RUN if source == SOURCE_RUN
                     else ("switch" if source == SOURCE_PROCESS else SOURCE_UNKNOWN)),
        "run_at": str(reading.get("at") or ""),
        "prompt_version": str(AP.PROMPT_VERSION),
        "readings_prompt_version": str(reading.get("readings_prompt_version") or ""),
        "covered": f"{covered}/{total}",
        "covered_count": covered,
        "total": total,
        "missing": missing,
        "absent": absent,
        "fresh": fresh,
        "tri": tri,
        "why": _active_why(tri, fresh, missing, reading),
        #: 这一档的 key 那一格（换没换过 key / 模型 / 端点）。与
        #: `status()["tiers"][档]["key"]` 是同一份读数（都出自同一个
        #: `tier_reading` 的返回），不另算一套。起跑那一行（:func:`run_reading`）据此
        #: 判"要不要提醒重落"：换 key 之后这一档的缓存等于空缓存，而"不新鲜"这个词
        #: 说不清那件事（提示词一个字都没动）。
        "key": dict(reading.get("key") or {}),
    }
    doc["text"] = _active_text(doc)
    return doc


def active_reading(*, path: Path | None = None,
                   per_tier: Mapping[str, Mapping[str, Any]] | None = None,
                   renders: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
                   key: Mapping[str, Any] | None = None,
                   lean: bool | None = None,
                   root: Path | str | None = None,
                   use_record: bool = True) -> dict[str, Any]:
    """当前这一趟会用哪一档（`GET /api/cache` 与 `cache status` 共用的那一格）。

    ## 三层来源（每一层都进 `source`）

    - 这个工作区有运行记录且带 lean 状态 ⇒ 用那一趟的开关（`source="run"`）；
    - 没有运行记录 ⇒ 用本进程开关（`source="process"`，`lean` 参数就是它）；
    - 记录文件在但读不出来 ⇒ `source="unknown"`、`tri="unknown"`、`why` 说理由，
      绝不拿本进程开关冒充那一趟的开关。

    `use_record=False` 是给 :func:`run_reading` 用的：起跑那一刻这一趟的开关就是这个
    进程的开关（它就是"正在跑的这趟"），不许被上一个会话留下来的记录顶掉。

    ## 档位与覆盖数只走一条路

    `tier_reading(选中档)` —— 它内部调 `cache_readings(lean=那一档)`，与 `status()`
    里那两档的四格是同一个入口、同一份读数。`per_tier` 传进来时直接复用 `status()`
    已经算好的那一格（同一个对象，不重算、不另读一次文件）；没给就现算一档（`plan()`
    只要一档时走这里）。

    ## 三态

    - `tri="found"`：`covered` / `missing` / `absent` / `run_at` 都是那一档的读数；
    - `tri="unknown"`：这一档整档没有读数 / 读数文件读不出来 / 渲染失败 / 运行记录
      读不出来 —— `why` 说理由，`fresh` 是 False 但它的意思是"这一趟不能当新鲜用"，
      不是"量过了发现变了"（先看 `tri`，再看 `fresh`）。绝不回落到另一档：那会把
      "这一档没预热"画成"另一档的缓存正在用"。

    `text` 是给人看的那一行（命令行原样打印、网页把星号画成加粗）。
    """
    workspace = workspace_root(root)
    record = (run_record_reading(root=root) if use_record
              else {"tri": "missing", "reason": "", "detail": "", "path": "",
                    "state": "", "record": {}})
    if str(record.get("tri")) == "unknown":
        return _active_doc(tier="", lean=None, source=SOURCE_UNKNOWN, record={},
                           workspace=workspace, reading={
                               "tri": "unknown",
                               "reason": _run_record_why(record),
                               "total": len(all_targets()),
                               "missing": list(all_targets()),
                           })
    chosen = dict(record.get("record") or {})
    if str(record.get("tri")) == "found":
        source = SOURCE_RUN
        current = bool(chosen.get("lean"))
    else:
        source = SOURCE_PROCESS
        current = _lean_now() if lean is None else bool(lean)
    tier = _tier_in_use(current)
    reading = (per_tier or {}).get(tier)
    if reading is None:
        try:
            reading = tier_reading(tier, path=path,
                                   renders=(renders or {}).get(tier), key=key)
        except Exception as exc:  # noqa: BLE001 - 读不出来属于 unknown，不是"零覆盖"
            return _active_doc(tier=tier, lean=current, source=source, record=chosen,
                               workspace=workspace, reading={
                                   "tri": "unknown",
                                   "reason": f"render_failed: {type(exc).__name__}: {exc}",
                                   "total": len(all_targets()),
                                   "missing": list(all_targets()),
                               })
    return _active_doc(tier=tier, lean=current, source=source, record=chosen,
                       workspace=workspace, reading=reading)


#: 起跑那一行（:func:`run_reading`）的两档级别。刻意只有两档：这一行是"读数"，
#: 不是判定 —— 它既不拦跑、也不改退出码，所以不需要第三档（`unknown` 落 warning）。
RUN_INFO = "info"
RUN_WARNING = "warning"


def run_reading(*, path: Path | None = None,
                renders: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
                key: Mapping[str, Any] | None = None,
                lean: bool | None = None,
                root: Path | str | None = None,
                sid: str = "") -> dict[str, Any]:
    """起跑前读一次"这一趟用哪一档"，折成一行读数（只读、零花费、永不抛）。

    ## 为什么要有这一口

    两档缓存落地之后，用户面只有"能调用的工具＋状态显示"还不够：跑起来以后，
    没有任何一处读过 `cache_readings()` —— 于是"这一趟到底命中了哪一档、那一档还新不新"
    在运行期是看不见的，用户只能自己去敲 `cache status` 再看一遍。业主的口径是让运行时
    也读一格，但只加读数、不拦跑：不新鲜的缓存跑起来照样是对的，只是会按未命中计费。

    ## 它同时写下运行记录

    这一口是"这一趟起跑"唯一的钩子，所以运行记录由它写（`record_active_run`）：
    `<工作区>/runs/cache-active-<会话号>.json` 里记下这一趟的 lean 状态。另一条进程
    （网页）问"当前使用哪一档"时读的就是它 —— 否则那一格只能读网页自己的开关，
    多进程时就是说反的。

    这一行自己的档位不读运行记录（`use_record=False`）：它就是正在起跑的这一趟，
    上一个会话留下来的记录不许顶掉它。写不成（工作区不可判定 / 盘写不了）照样印这一行，
    `record` 那一格如实带回去（`written=False` 与理由），页面据此退回本进程开关。

    ## 三态与两种级别（不是判定，只是读数）

    - `info`：这一档查到了（`tri="found"`）、新鲜（`fresh=True`）且没换过 key ⇒
      `缓存：使用 Lean 版缓存（p188 · 12/12）`；
    - `warning`：没查成（整档没有读数 / 渲染失败）、不新鲜、或 key 变了 ⇒ 一行
      `缓存：这一档不新鲜（原因），建议先点『试算』看要预热什么`。括号里的原因逐字来自
      读数本身（`why` / `fresh_reason` / 换 key 那条提醒），不另编一句。

    `active` 那一格原样带回去（与 `cache status` / 网页面板是同一个 `active_reading`
    返回），调用方要显示更多就自己取，不必再读一次文件；`record` 是这一趟运行记录的
    写入回执（`written` / `path` / `reason`）。

    ## 为什么自己接住所有异常

    这一行是"顺带读一格"：它读不出来时该发生的事是"照常跑，只少一行说明"，绝不是"这一趟
    起不来"。所以这里把异常折成一行 warning —— 与"读数只加不拦"同一条纪律。
    """
    current = _lean_now() if lean is None else bool(lean)
    try:
        record = record_active_run(root=root, sid=str(sid or ""), lean=current)
    except Exception as exc:  # noqa: BLE001 - 写运行记录不许拖垮起跑
        record = {"written": False, "path": "",
                  "reason": f"{type(exc).__name__}: {exc}"}
    try:
        active = active_reading(path=path, renders=renders, key=key,
                                lean=current, root=root, use_record=False)
    except Exception as exc:  # noqa: BLE001 - 读不出来只许降级成一行 warning
        return {"level": RUN_WARNING, "tri": "unknown", "active": {}, "record": record,
                "text": (f"缓存：这一档不新鲜（没查成：{type(exc).__name__}: {exc}），"
                         "建议先点『试算』看要预热什么")}
    tri = str(active.get("tri") or "unknown")
    fresh = bool(active.get("fresh"))
    key_tri = str((active.get("key") or {}).get("tri") or "")
    if tri == "found" and fresh and key_tri != "stale":
        name = str(active.get("label") or "")
        body = f"{active.get('prompt_version') or ''} · {active.get('covered') or '0/0'}"
        return {"level": RUN_INFO, "tri": tri, "active": active, "record": record,
                "text": f"缓存：使用 {name}（{body}）"}
    if tri != "found":
        reason = "没查成：" + (str(active.get("why") or "").strip() or REASON_NO_READINGS)
    elif fresh and key_tri == "stale":
        reason = ("换了 key / 模型 / 接口地址（上游按这三样分片，换一片就是空缓存；"
                  "这一趟按未命中计费）")
    else:
        reason = str(active.get("why") or "").strip() or "这些目标的现渲染摘要与读数不一致"
    return {"level": RUN_WARNING, "tri": tri, "active": active, "record": record,
            "text": f"缓存：这一档不新鲜（{reason}），建议先点『试算』看要预热什么"}


def status(*, path: Path | None = None,
           renders: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
           key: Mapping[str, Any] | None = None,
           tiers: Iterable[str] = TIERS,
           root: Path | str | None = None) -> dict[str, Any]:
    """两档 × 四格的状态读数（只读、零花费），外加"当前使用哪一档"与换 key 那条提醒。

    返回的 `active` 是"这一趟会用哪一档"（:func:`active_reading`）—— 来源按三层定：
    这个工作区的运行记录 / 本进程开关 / 读不出来，`active.source` 与正文里那一句
    都会自报是哪一层。`reminder` 是网页顶部横幅与命令行最后一行共用的那一份：`active`
    为真时 `text` 就是要显示的那句话，`dismiss_key` 是"这个提醒属于哪一片缓存"
    （指纹 + 模型）—— 换 key 之后它变了，于是被关掉的横幅会再出现一次。

    `root` 是"这个工作区"的根（不给就按 `workspace_root` 那条梯子找：显式 >
    环境变量 > 进程命令行 `--root`）。`workspace` 那一格原样带回去，读的人才知道
    这一格看的是哪个工作区（空串 = 不可判定）。
    """
    out_path = Path(path) if path is not None else default_readings_path()
    current_key = dict(key) if key is not None else key_reading()
    now_lean = _lean_now()
    workspace = workspace_root(root)
    rendered = {tier: dict((renders or {}).get(tier) or render_tier(tier))
                for tier in tiers}
    per_tier = {tier: tier_reading(tier, path=out_path, renders=rendered[tier], key=current_key)
                for tier in tiers}

    unknown = [tier for tier in tiers if per_tier[tier]["tri"] != "found"]
    unknown += [tier for tier in tiers
                if per_tier[tier]["tri"] == "found" and per_tier[tier]["fresh"] is None]
    stale = [tier for tier in tiers
             if per_tier[tier]["tri"] == "found"
             and (per_tier[tier]["fresh"] is False
                  or per_tier[tier]["key"]["tri"] == "stale")]
    key_unknown = [tier for tier in tiers
                   if per_tier[tier]["tri"] == "found"
                   and per_tier[tier]["key"]["tri"] == "unknown"]
    if unknown:
        verdict = "unknown"
    elif stale or key_unknown:
        verdict = "stale"
    else:
        verdict = "fresh"

    stale_tiers = [tier for tier in tiers if per_tier[tier]["key"]["tri"] == "stale"]
    affected: list[str] = []
    for tier in stale_tiers:
        for target in per_tier[tier]["key"]["affected"]:
            if target not in affected:
                affected.append(target)
    if stale_tiers:
        first = per_tier[stale_tiers[0]]["key"]
        reminder = {"active": True, "tri": "stale", "tiers": stale_tiers,
                    "text": str(first["text"]), "affected": affected,
                    "dismiss_key": (f"{current_key.get('fingerprint') or 'none'}|"
                                    f"{current_key.get('model') or ''}")}
    elif key_unknown:
        reminder = {"active": True, "tri": "unknown", "tiers": key_unknown,
                    "text": (f"{'、'.join(TIER_LABEL[t] for t in key_unknown)} 的旧读数没有 "
                             "key 指纹 ⇒ 换没换过 key 不可判定；重落一次就会记上"),
                    "affected": [],
                    "dismiss_key": (f"{current_key.get('fingerprint') or 'none'}|"
                                    f"{current_key.get('model') or ''}")}
    else:
        reminder = {"active": False, "tri": "same", "tiers": [], "text": "",
                    "affected": [],
                    "dismiss_key": (f"{current_key.get('fingerprint') or 'none'}|"
                                    f"{current_key.get('model') or ''}")}

    return {
        "schema": 1,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "readings": str(out_path),
        # 当前开关的唯一读法（与渲染同源：`leanscope.lean_on()` 就是 `system_prompt` 判可见性
        # 时读的那个值）；不读环境变量，免得"设置文件里开着、env 没设"时印出错的字。
        "lean_now": now_lean,
        "prompt_version": str(AP.PROMPT_VERSION),
        "key": current_key,
        # 这一格读的是哪个工作区（空串 = 不可判定；`active.source` 据此说清来源）。
        "workspace": str(workspace or ""),
        "tiers": per_tier,
        # 当前这一趟会用哪一档：复用上面算好的那一格（同一个 entry、同一份读数），
        # 不另读一次文件、也不另算一套覆盖数。
        "active": active_reading(path=out_path, per_tier=per_tier,
                                 renders=rendered, key=current_key, lean=now_lean,
                                 root=root),
        "reminder": reminder,
        "verdict": {"tri": verdict, "unknown_tiers": unknown,
                    "stale_tiers": stale, "key_unknown_tiers": key_unknown},
    }


def _tokens_in_estimate(rendered: Mapping[str, Any]) -> int:
    """一次请求的输入 token 粗估（system + 工具面的字符数除四）。

    口径来自 `tokenestimate.estimate_text_tokens`（四字符一 token）。它只是"预计花多少钱"
    的分母，不参与任何判定：拿它当读数会把估值说成实测。
    """
    from . import tokenestimate as TOK

    system = str(rendered.get("system") or "")
    tools_chars = int(rendered.get("tools_chars") or 0)
    return int(TOK.estimate_text_tokens(system) + tools_chars / max(TOK.CHARS_PER_TOKEN, 1))


def _price_pair(spec: Any) -> tuple[float, float, float]:
    """(命中价, 未命中价, 输出价) 每一百万 token 的美元价；读不到就退回未命中价的 0。

    读不到价格时返回 0 而不是猜一个数：预计花费写成 0 美元会被读成"不花钱"，
    所以 :func:`plan` 会另给一格 `usd_known=False`，把这件事说清楚。
    """
    from . import modelcost as MC

    try:
        price = MC.price_of_full(spec)
    except Exception:  # noqa: BLE001 - 价表读不出来属于"没查成"，由 usd_known 报
        return (0.0, 0.0, 0.0)
    return (float(price.usd_per_m_in_hit or price.usd_per_m_in),
            float(price.usd_per_m_in), float(price.usd_per_m_out))


def plan(*, tiers: Iterable[str] = TIERS, path: Path | None = None,
         renders: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
         key: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """真预热之前的计划：每个目标要不要发、发几次、预计花多少（一个请求都不发）。

    三个答案：`to_warm`（这一档要预热的目标）、`skip_fresh`（已新鲜、可以跳过）、
    `absent`（这一档按设计不存在）。`usd_est` 是按价表与字符数算出来的粗估，
    与实测花费不是一回事（实测在读数文件的 `spent_usd` 里）。
    """
    from . import modelgw as MG

    out_path = Path(path) if path is not None else default_readings_path()
    current_key = dict(key) if key is not None else key_reading()
    st = status(path=out_path, renders=renders, key=current_key, tiers=tiers)
    warm = _warm_module()
    spec = MG.spec_from_env()
    hit_price, miss_price, out_price = _price_pair(spec)
    sample = tuple(str(x) for x in getattr(warm, "DEFAULT_HIT_SAMPLE", ()))
    per_tier: dict[str, Any] = {}
    calls_total = 0
    usd_total = 0.0
    for tier in tiers:
        reading = st["tiers"][tier]
        rendered = dict((renders or {}).get(tier) or render_tier(tier))
        per = reading.get("per_target") or {}
        present = [t for t in warm.WARM_TARGETS
                   if str(rendered.get(t, {}).get("kind")) != "absent"]
        to_warm = [t for t in present if not (per.get(t) or {}).get("fresh")]
        skip = [t for t in present if (per.get(t) or {}).get("fresh")]
        absent = [t for t in warm.WARM_TARGETS if t not in present]
        tokens = sum(_tokens_in_estimate(rendered.get(t) or {}) for t in to_warm)
        # 每个目标一次（未命中价）+ 命中样本再发一次（命中价）。
        sample_hit = [t for t in sample if t in to_warm]
        calls = len(to_warm) + len(sample_hit)
        usd = (tokens / 1_000_000.0) * miss_price
        usd += (sum(_tokens_in_estimate(rendered.get(t) or {}) for t in sample_hit)
                / 1_000_000.0) * hit_price
        usd += (calls * 16 / 1_000_000.0) * out_price
        per_tier[tier] = {
            "to_warm": to_warm, "skip_fresh": skip, "absent": absent,
            "calls": calls, "tokens_in_est": tokens, "usd_est": round(usd, 6),
        }
        calls_total += calls
        usd_total += usd
    return {
        "schema": 1,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "verdict": "dry_run",
        "readings": str(out_path),
        "key": current_key,
        "model": str(getattr(spec, "model", "") or ""),
        "cap_usd_default": float(getattr(warm, "DEFAULT_CAP_USD", 0.10)),
        "usd_known": bool(miss_price > 0.0),
        "tiers": per_tier,
        "calls_total": calls_total,
        "usd_est_total": round(usd_total, 6),
        "note": "只渲染与算钱，没发任何请求：花费 0 美元",
    }


def annotate_run(path: Path, *, at: str, key: Mapping[str, Any]) -> bool:
    """把 key 指纹写进"刚写下的那一趟"读数（找不到那一趟 ⇒ 返回 False，不猜）。

    为什么由本模块落这一格，而不是在预热脚本里落：脚本是另一路的文件，本模块不去
    改它；`cache warm` 这条路在脚本返回之后补这一格，于是"用工具预热"的读数天生带
    指纹。用脚本直跑出来的那一趟没有指纹 ⇒ 状态读数如实报 `unknown`
    （`key_fingerprint_missing`），不冒充"没换过 key"。
    """
    warm = _warm_module()
    target = Path(path)
    runs = warm.load_readings(target)
    if not runs:
        return False
    want = str(at or "")
    chosen: dict[str, Any] | None = None
    for run in reversed(runs):
        if want and str(run.get("at") or "") == want:
            chosen = run
            break
    if chosen is None:
        return False
    chosen["key_fingerprint"] = str(key.get("fingerprint") or "")
    chosen["key_model"] = str(key.get("model") or "")
    chosen["key_base_url"] = str(key.get("base_url") or "")
    chosen["key_source"] = str(key.get("source") or "")
    warm.save_readings(target, runs)
    return True


def _worst(codes: Iterable[int]) -> int:
    """几个退出码里最坏的那个（2 > 1 > 0：没查成比有问题更坏）。"""
    got = list(codes)
    if not got:
        return EXIT_UNKNOWN
    if any(int(c) == EXIT_UNKNOWN for c in got):
        return EXIT_UNKNOWN
    if any(int(c) == EXIT_STALE for c in got):
        return EXIT_STALE
    return EXIT_FRESH


def warm(*, tiers: Iterable[str] = TIERS, path: Path | None = None,
         cap_usd: float | None = None, model: str = "",
         dry_run: bool = False, key: Mapping[str, Any] | None = None,
         renders: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None) -> tuple[int, dict[str, Any]]:
    """按目标真预热（发请求、会花钱），或只给计划（`dry_run=True`，零花费）。

    真预热之前先打印这一趟用的是谁的 key（来源）、哪个模型、哪个接口地址 ——
    不许打印 key 本身。这一行是"这笔钱记在谁头上"的唯一现场读数，所以放在发第一发
    之前：放在之后就成了事后追认。

    返回 `(退出码, 结果字典)`：退出码沿用预热脚本的三态（0 落好 / 1 没落全 / 2 没查成），
    多档时取最坏的那个。
    """
    wanted = tuple(tiers)
    bad = [tier for tier in wanted if tier not in TIERS]
    if bad:
        return EXIT_UNKNOWN, {"verdict": "unknown", "error": f"只认两档 {TIERS}，收到 {bad}"}
    out_path = Path(path) if path is not None else default_readings_path()
    current_key = dict(key) if key is not None else key_reading()

    if dry_run:
        doc = plan(tiers=wanted, path=out_path, renders=renders, key=current_key)
        return EXIT_FRESH, doc

    warm_mod = _warm_module()
    cap = float(getattr(warm_mod, "DEFAULT_CAP_USD", 0.10) if cap_usd is None else cap_usd)
    codes: list[int] = []
    results: list[dict[str, Any]] = []
    keys_written: list[bool] = []
    for tier in wanted:
        rendered = dict((renders or {}).get(tier) or render_tier(tier))
        targets = tuple(t for t in warm_mod.WARM_TARGETS
                        if str(rendered.get(t, {}).get("kind")) != "absent")
        print(f"[key] 来源={current_key.get('source') or '(未配置)'} "
              f"模型={current_key.get('model') or '(空)'} "
              f"接口={current_key.get('base_url') or '(空)'} "
              f"key={'***' if current_key.get('key_chars') else '(没有)'} "
              f"指纹={current_key.get('fingerprint') or '(空)'} "
              f"（这一档：{TIER_LABEL[tier]}，上限 {cap:.2f} 美元）", flush=True)
        try:
            code, result = warm_mod.warm(targets, cap_usd=cap, model=str(model),
                                         out_path=out_path, dry_run=False,
                                         lean=("on" if tier == "on" else "off"))
        except Exception as exc:  # noqa: BLE001 - 渲染/写盘炸了属于"没查成"
            print(f"[unknown] 预热没跑起来（{TIER_LABEL[tier]}）："
                  f"{type(exc).__name__}: {exc}", flush=True)
            codes.append(EXIT_UNKNOWN)
            results.append({"verdict": "unknown", "lean_enabled": tier == "on",
                            "error": f"{type(exc).__name__}: {exc}"})
            keys_written.append(False)
            continue
        result = dict(result)
        result["tier"] = tier
        written = False
        if str(result.get("verdict")) in ("warmed", "incomplete"):
            written = annotate_run(out_path, at=str(result.get("at") or ""), key=current_key)
        keys_written.append(written)
        codes.append(int(code))
        results.append(result)
    return _worst(codes), {"verdict": "warm", "tiers": wanted, "results": results,
                           "key": current_key, "keys_written": keys_written,
                           "readings": str(out_path)}


# ---------------------------------------------------------------- 命令行（人读的那一版）


def _tier_table_line(reading: Mapping[str, Any]) -> str:
    """一档的四格（一行，列对齐；`unknown` 在格子里就写 unknown 并带理由）。"""
    tri = str(reading.get("tri"))
    fresh = reading.get("fresh")
    if tri != "found":
        land = "unknown"
        fresh_cell = "unknown"
        cover = f"0/{reading.get('total')}"
        missing = "（整档没有读数）"
    else:
        land = "已落地"
        fresh_cell = "是" if fresh else "否"
        cover = f"{reading.get('covered')}/{reading.get('total')}"
        bits: list[str] = []
        if reading.get("not_fresh"):
            bits.append("不新鲜：" + "、".join(reading["not_fresh"]))
        if reading.get("missing"):
            bits.append("缺：" + "、".join(reading["missing"]))
        if reading.get("absent"):
            bits.append("受控缺席：" + "、".join(reading["absent"]))
        missing = "；".join(bits) if bits else "-"
    return (f"  {TIER_LABEL[str(reading.get('tier'))]:<8}{land:<10}{fresh_cell:<8}"
            f"{cover:<10}{missing}")


def _print_status(doc: Mapping[str, Any]) -> None:
    key = doc.get("key") or {}
    print(f"[cache] 两档提示词缓存（读数文件 {doc.get('readings')}）")
    print(f"  当前开关：{'Lean 开' if doc.get('lean_now') else 'Lean 关'}"
          f"；提示词版本 {doc.get('prompt_version')}")
    # 业主 2026-10-23 晚要的那一行：网页顶部与这里印的是同一个 `active.text`。
    active_text = str((doc.get("active") or {}).get("text") or "")
    print(f"  {active_text}" if active_text
          else "  当前使用：unknown（这一格没读出来 —— 不是『没有缓存』）")
    print(f"  当前 key：来源={key.get('source') or '(未配置)'} "
          f"模型={key.get('model') or '(空)'} 接口={key.get('base_url') or '(空)'} "
          f"指纹={key.get('fingerprint') or '(没有 key)'}（不打印 key 本身）")
    print(f"  {'档位':<8}{'落地':<10}{'新鲜':<8}{'覆盖':<10}缺谁 / 不新鲜")
    for reading in (doc.get("tiers") or {}).values():
        print(_tier_table_line(reading))
    for tier, reading in (doc.get("tiers") or {}).items():
        if str(reading.get("tri")) != "found":
            print(f"  {TIER_LABEL[str(tier)]} 的理由：{reading.get('reason')}")
            continue
        spent = reading.get("spent_usd")
        spent_text = "unknown" if spent is None else f"{float(spent):.6f}"
        print(f"  {TIER_LABEL[str(tier)]} 最后一趟：{reading.get('at') or '(没有时间)'} · "
              f"读数的 prompt_version={reading.get('readings_prompt_version') or '(空)'} · "
              f"花费={spent_text} 美元")
    reminder = doc.get("reminder") or {}
    if reminder.get("active"):
        print(f"  提醒：{reminder.get('text')}")
    verdict = doc.get("verdict") or {}
    unknown_tiers = "、".join(TIER_LABEL[t] for t in (verdict.get("unknown_tiers") or []))
    stale_tiers = "、".join(TIER_LABEL[t] for t in (verdict.get("stale_tiers") or []))
    tail = ""
    if unknown_tiers:
        tail += f"（没查成的档：{unknown_tiers}）"
    if stale_tiers:
        tail += f"（要重落的档：{stale_tiers}）"
    print(f"  结论：{verdict.get('tri')}{tail}")


def _print_plan(doc: Mapping[str, Any]) -> None:
    key = doc.get("key") or {}
    print(f"[dry-run] 预热计划（读数文件 {doc.get('readings')}；一个请求都没发，花费 0 美元）")
    print(f"  将要用：来源={key.get('source') or '(未配置)'} 模型={doc.get('model') or '(空)'} "
          f"接口={key.get('base_url') or '(空)'} 指纹={key.get('fingerprint') or '(没有 key)'}")
    for tier, plan_tier in (doc.get("tiers") or {}).items():
        print(f"  {TIER_LABEL[str(tier)]}：要预热 {len(plan_tier.get('to_warm') or [])} 个目标"
              f"（{('、'.join(plan_tier.get('to_warm') or []) or '无')}）")
        print(f"    已新鲜可跳过：{('、'.join(plan_tier.get('skip_fresh') or []) or '无')}")
        if plan_tier.get("absent"):
            print(f"    按设计不在这一档：{'、'.join(plan_tier['absent'])}")
        print(f"    调用次数 {plan_tier.get('calls')} 次 · 输入 token 粗估 "
              f"{plan_tier.get('tokens_in_est')} · 预计花费 "
              f"{float(plan_tier.get('usd_est') or 0.0):.6f} 美元")
    print(f"  合计：{doc.get('calls_total')} 次调用，预计 "
          f"{float(doc.get('usd_est_total') or 0.0):.6f} 美元"
          + ("" if doc.get("usd_known") else "（价表读不出来 ⇒ 这个数不可信，只能说『至少不是零』）"))


def _readings_path(raw: str) -> Path | None:
    return Path(str(raw)) if str(raw or "").strip() else None


def cmd_status(args: Any) -> int:
    """`agentflow cache status`：两档的四格 + 换 key 那一行（只读、零花费）。

    工作区从顶层的 `--root` 取（命令行参数里就有；不给就走 `workspace_root` 那条梯子）：
    这样"当前使用哪一档"与网页读的是同一口径（同一个 `active_reading`）。

    读写：只读：模板文件、缓存目录与 key 指纹（不写任何东西）。
    实现方式一句话：`cachectl.status_report`。
    """
    path = _readings_path(getattr(args, "readings", ""))
    try:
        doc = status(path=path, root=getattr(args, "root", None))
    except Exception as exc:  # noqa: BLE001 - 读不出来属于"没查成"
        print(f"[unknown] 状态没读出来：{type(exc).__name__}: {exc}")
        return EXIT_UNKNOWN
    if bool(getattr(args, "json", False)):
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
    else:
        _print_status(doc)
    verdict = str((doc.get("verdict") or {}).get("tri"))
    return {"fresh": EXIT_FRESH, "stale": EXIT_STALE}.get(verdict, EXIT_UNKNOWN)


def cmd_warm(args: Any) -> int:
    """`agentflow cache warm --lean on|off|both [--dry-run]`：真预热或只给计划。

    读写：读模板并写缓存落盘（`--dry-run` 只算不写、一次模型都不调；真预热会花钱）。
    实现方式一句话：`cachectl.warm`（两档 lean 各自一份缓存）。
    """
    """`agentflow cache warm --lean on|off|both [--dry-run]`：真预热或只给计划。"""
    raw = str(getattr(args, "lean", "") or "")
    wanted = tuple(TIERS) if raw == "both" else ((raw,) if raw in TIERS else ())
    if not wanted:
        print(f"[unknown] --lean 只认 on / off / both，收到 {raw!r}")
        return EXIT_UNKNOWN
    path = _readings_path(getattr(args, "readings", ""))
    dry = bool(getattr(args, "dry_run", False))
    try:
        code, doc = warm(tiers=wanted, path=path,
                         cap_usd=float(getattr(args, "cap_usd", 0.10) or 0.10),
                         model=str(getattr(args, "model", "") or ""), dry_run=dry)
    except Exception as exc:  # noqa: BLE001 - 同一个"没查成"出口
        print(f"[unknown] 预热没跑起来：{type(exc).__name__}: {exc}")
        return EXIT_UNKNOWN
    if dry:
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str)
              if bool(getattr(args, "json", False)) else "", end="")
        _print_plan(doc)
        return EXIT_FRESH
    if str(doc.get("verdict")) == "unknown" and doc.get("error"):
        print(f"[unknown] {doc.get('error')}")
        return EXIT_UNKNOWN
    for result in doc.get("results") or []:
        tier = str(result.get("tier") or "")
        verdict = str(result.get("verdict") or "unknown")
        if verdict not in ("warmed", "incomplete"):
            print(f"[{verdict}] {TIER_LABEL.get(tier, tier)}：{result.get('error') or '没落成'}")
            continue
        print(f"[{verdict}] {TIER_LABEL.get(tier, tier)}：花费 "
              f"{float(result.get('spent_usd') or 0.0):.6f} 美元 · "
              f"{result.get('note') or ''}")
    for result, written in zip(doc.get("results") or [], doc.get("keys_written") or []):
        if str(result.get("verdict")) in ("warmed", "incomplete"):
            print(f"  key 指纹已记进读数（{TIER_LABEL.get(str(result.get('tier')), '')}）："
                  f"{'是' if written else '否 —— 找不到刚写下的那一趟，重跑一次 status 看读数'}")
    return int(code)


def _add_leaf_parsers(inner: Any) -> None:
    """两个叶子子命令（`status` / `warm`）的参数表；`cache` 与独立入口共用这一份。"""
    st = inner.add_parser("status", help="两档缓存的状态读数（只读、零花费）")
    st.add_argument("--json", action="store_true", help="把状态读数打成 JSON")
    st.add_argument("--readings", default="", help="读数 JSON 的落点（缺省用仓库里那份夹具）")
    st.set_defaults(func=cmd_cache)

    wm = inner.add_parser("warm", help="真预热两档（发请求、会花钱）；--dry-run 只给计划")
    wm.add_argument("--lean", choices=("on", "off", "both"), required=True,
                    help="落哪一档：on / off / both（必给：真预热会花钱，档位不许有隐含缺省）")
    wm.add_argument("--dry-run", action="store_true",
                    help="只渲染与算钱，不发请求（花费 0 美元）")
    wm.add_argument("--cap-usd", type=float, default=None,
                    help="这一趟的花费上限（美元；缺省用预热脚本里那一个）")
    wm.add_argument("--model", default="", help="覆盖模型名（缺省取环境 / 设置文件）")
    wm.add_argument("--json", action="store_true", help="dry-run 时把计划打成 JSON")
    wm.add_argument("--readings", default="", help="读数 JSON 的落点（缺省用仓库里那份夹具）")
    wm.set_defaults(func=cmd_cache)


def add_subcommands(sub: Any) -> None:
    """把 `cache` 这条命令挂到 `cli.build_parser()` 的 subparsers 上。

    两个子命令的形状就是业主画的那两条：`cache status`（只读）与
    `cache warm --lean on|off|both [--dry-run]`（会花钱）。`--lean` 在 warm 上是必给的：
    真预热会花钱，所以"落哪一档"不许有隐含缺省 —— 少敲一个词就多花一倍钱。

    ## 容器这一层也要有 `func`（D-1）
    两个叶子各设了自己的 `func`，而 `cache` 这一层此前一个都没设。于是
    `agentflow cache`（不带子命令）走到 `cli.main` 的 `args.func(args)` 就炸在
    `AttributeError: 'Namespace' object has no attribute 'func'` 上，退出码 1 ——
    而 1 在这个仓库里的意思是"查过了、有问题"，用法错该是 2（没查成）。这里给容器
    补一个 `func`，落到 `cmd_cache` 的"认不出子命令"那一支：打用法、退出码 2。
    """
    sp = sub.add_parser("cache", help="两档提示词缓存：看状态 / 真预热（会花钱，先看 --dry-run）")
    #: 不带子命令时 `cache_cmd` 是空串 ⇒ `cmd_cache` 打用法并返回 `EXIT_UNKNOWN`。
    #: 带子命令时叶子里那一份 `set_defaults(func=cmd_cache)` 会覆盖这里，两者同一个函数。
    sp.set_defaults(func=cmd_cache)
    _add_leaf_parsers(sp.add_subparsers(dest="cache_cmd", metavar="<子命令>"))


def cmd_cache(args: Any) -> int:
    """`cache` 这一组的总入口（分给两个子命令；认不出就报用法，退出码 2）。

    读写：读提示词模板与两档缓存目录；`warm` 会真发模型调用（花钱），`status` 只读。
    实现方式一句话：`cachectl`（命令行与网页按钮读同一份实现）。
    """
    """`cache` 这一组的总入口（分给两个子命令；认不出就报用法，退出码 2）。"""
    which = str(getattr(args, "cache_cmd", "") or "")
    if which == "status":
        return cmd_status(args)
    if which == "warm":
        return cmd_warm(args)
    print("用法：agentflow cache status [--json] | "
          "agentflow cache warm --lean on|off|both [--dry-run]")
    return EXIT_UNKNOWN


def run(argv: list[str] | None = None) -> int:
    """独立入口（不走 `cli.build_parser()` 时用它；判据与脚本都可用）。"""
    parser = argparse.ArgumentParser(prog="agentflow cache",
                                     description="两档提示词缓存：状态与预热")
    _add_leaf_parsers(parser.add_subparsers(dest="cache_cmd"))
    args = parser.parse_args(argv)
    return cmd_cache(args)
