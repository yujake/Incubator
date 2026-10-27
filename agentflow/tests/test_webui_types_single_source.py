# -*- coding: utf-8 -*-
"""类型的唯一来源：那两族形状必须住在生成物里，且键名与后端读数逐字一致。

2026-10-27（业主裁定 ⑥-5 / W4）之前，两档提示词缓存（`GET /api/cache`）与错误动作
计数（`GET /api/errors`、`/api/errors/categories`）那两族的形状此前是手写的，写在
`ui/src/api.ts` 里。手写的类型就是第二份口径：后端加一格，`tsc` 只会觉得"少了一个
可选字段"，一声不吭 —— 那正是 `types.ts` 生成物要挡的那一类静默。

现在它们住在 `ui/src/types.ts`（源头是 `webui/readers.py` 的 `_TS_TYPES`）。
这一组判据钉三件事：

| 判据 | 查什么 |
|---|---|
| `test_the_two_families_live_in_the_generated_types` | 14 个接口都在生成物里 |
| `test_api_ts_declares_none_of_them_any_more` | `api.ts` 一个都不再声明（两份口径没了） |
| `test_the_error_faces_keys_match_the_backend_reading` | 键名与后端真读数逐字一致（错误动作那两面） |
| `test_the_unchecked_ones_say_why` | 没进受核对名单的那几个都写了理由（`UNCHECKED_TYPES`），不是"忘了" |
"""
from __future__ import annotations

import pathlib
import re

import pytest

from agentflow import readouts as RD
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
TYPES_TS = UI_SRC / "types.ts"
API_TS = UI_SRC / "api.ts"

#: 两档提示词缓存那一族（`cachectl.status()` / `cacheface.warm_job()` 的返回形状）。
CACHE_TYPES = ("CacheTargetCell", "CacheKeyCell", "CacheTier", "CacheKeyReading",
               "CacheActive", "CacheReminder", "CacheWarmJob", "CacheView")

#: 错误动作那一族（`readouts.errors_readout()` / `errorstats.ERROR_CATEGORIES`）。
ERROR_TYPES = ("ReadoutProblem", "ErrorStatsSource", "ErrorStatsData",
               "RoleErrorsView", "ErrorCategoryMeaning", "ErrorCategoryGlossary")

_INTERFACE = re.compile(r"^export interface ([A-Za-z_][A-Za-z0-9_]*)\s*\{", re.M)
_FIELD = re.compile(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)\??\s*:", re.M)


def _interfaces(text: str) -> dict[str, set[str]]:
    """`types.ts` 里每个接口的键集合（与契约判据 C 同一个读法，字段一行一个）。"""
    out: dict[str, set[str]] = {}
    for m in _INTERFACE.finditer(text):
        body = text[m.end():]
        end = body.find("\n}")
        body = body[:end if end != -1 else len(body)]
        out[m.group(1)] = {f.group(1) for f in _FIELD.finditer(body)}
    return out


def _types_text() -> str:
    if not TYPES_TS.is_file():
        pytest.skip(f"{TYPES_TS} 不在盘上（前端骨架尚未落地）")
    return TYPES_TS.read_text(encoding="utf-8")


# ====================================================================== 唯一来源
def test_the_two_families_live_in_the_generated_types() -> None:
    """正控：14 个接口都在生成物里（少了哪一个，页面就会读到 `undefined`）。"""
    declared = _interfaces(_types_text())
    missing = [name for name in CACHE_TYPES + ERROR_TYPES if name not in declared]
    assert not missing, f"生成物里缺这些接口：{missing}"


def test_api_ts_declares_none_of_them_any_more() -> None:
    """反真空：`api.ts` 里不许再有这些 `export interface`（两份口径的那个源头）。

    为什么这条要紧：搬过去之后如果 api.ts 还留着一份同形声明，`tsc` 会挑其中一份
    用，而另一份从此没人管 —— 那正是"同一件事两份实现"最难发现的那种。
    """
    text = API_TS.read_text(encoding="utf-8")
    still = [name for name in CACHE_TYPES + ERROR_TYPES
             if re.search(rf"^export interface {name}\s*\{{", text, re.M)]
    assert not still, f"api.ts 里还手写着这些接口：{still}"


def test_api_ts_imports_the_ones_it_names() -> None:
    """接线：api.ts 自己点名用到的那几个必须从 `./types` 导入（不是从别处）。

    订的是"取数函数的返回类型来自生成物"这件事：`getCache()` / `getErrors()` /
    `getErrorCategories()` 的 `Promise<T>` 里的 `T` 必须是生成物里那一个。
    """
    text = API_TS.read_text(encoding="utf-8")
    for name in ("CacheView", "RoleErrorsView", "ErrorCategoryGlossary"):
        assert f"  {name},\n" in text, f"api.ts 的 import 头里没有 {name}"
    assert 'from "./types"' in text, "api.ts 的类型不是从 ./types 导入的"


# ====================================================================== 键名对齐
def test_the_error_faces_keys_match_the_backend_reading(
        artifacts_ws: pathlib.Path) -> None:
    """键名与后端读数字段一致（错误动作那两面；缓存那一族的理由见 `UNCHECKED_TYPES`）。

    这一条与契约判据 C 同一口径，但它在当前这个文件里单独钉一次：C 条是"所有面一起
    对账"，一条红会淹掉具体是哪一族漂了；这里红就直接点名那一族的键。
    """
    declared = _interfaces(_types_text())
    errors = RD.errors_readout(artifacts_ws)
    assert set(errors) == declared["RoleErrorsView"], (
        "RoleErrorsView 的键与 `readouts.errors_readout()` 不一致："
        f"多 {sorted(declared['RoleErrorsView'] - set(errors))} / "
        f"少 {sorted(set(errors) - declared['RoleErrorsView'])}")
    assert isinstance(errors.get("data"), dict), errors
    assert set(errors["data"]) == declared["ErrorStatsData"], (
        "ErrorStatsData 的键与 `errors_readout()['data']` 不一致："
        f"多 {sorted(declared['ErrorStatsData'] - set(errors['data']))} / "
        f"少 {sorted(set(errors['data']) - declared['ErrorStatsData'])}")


def test_the_unchecked_ones_say_why() -> None:
    """没进受核对名单的那几个都写了理由（"为什么这里没有读数"不许是空白）。"""
    reg = R.UNCHECKED_TYPES
    for name in ERROR_TYPES + CACHE_TYPES:
        if name in R.CHECKED_TYPES:
            continue
        assert name in reg, f"{name} 既不在受核对名单、也没登记理由"
        assert reg[name].strip(), f"{name} 的理由是空的"
