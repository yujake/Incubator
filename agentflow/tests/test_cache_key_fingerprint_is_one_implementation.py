"""key 指纹只许一处实现（`R-BE4`，2026-10-27 业主批准）。

## 这条判据守什么

`cachectl` 用 key 指纹回答"这一片上游缓存还是不是原来那一片"（模型 + 端点 + 账号，
`cachectl.key_reading` / `_key_matches` / `annotate_run`），而读数文件是
`scripts/warm_prompt_cache.py` 写的。两处各写一份 `sha256(key)[:16]` 时，它们的差别
不会出现在正常 key 上 —— 只出现在空 key 上：

- `cachectl.fingerprint("")` == `""`（"没有 key"这一档，与"没配 key"同形）
- 内联那份 `sha256("".encode())[:16]` == `"e3b0c44298fc1c14"`

于是"没有 key 时落过读数"的工作区，`cachectl` 会把 recorded `e3b0…` 与 current `""`
判成不同 ⇒ `key.tri="stale"` + "换过 key"的提醒，而事实是这一档根本没有 key
（`reason` 本该是 `key_fingerprint_missing` 那一档）。这不是理论：`_key_matches` 只比
"字符串相不相等"，它没有别的手段分辨。

## 两条判据

1. 同一函数：`scripts/warm_prompt_cache.py` 的 `key_fingerprint` 必须就是
   `cachectl.fingerprint` 的转发（对象同一，不是"算出来碰巧相等"）。
2. 结论逐字相同：空 key 与非空 key 各比一次 —— 空 key 那一格正是两份实现在
   改前不一致的地方，负控就是把它换回内联写法（见本文件末尾的负控说明）。

## 负控（怎么证明这条判据能红）

把 `warm_prompt_cache.key_fingerprint` 换回内联写法
（`hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]`）：
判据 1 立刻红（对象不是同一个），判据 2 在空 key 那一格红（`e3b0…` vs `""`）。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from agentflow import cachectl

_REPO = pathlib.Path(__file__).resolve().parents[1]


def _load_warm():
    """按路径导入 `scripts/warm_prompt_cache.py`（`scripts/` 不是包，不能普通 import）。"""
    spec = importlib.util.spec_from_file_location(
        "_warm_cache_fingerprint_under_test", _REPO / "scripts" / "warm_prompt_cache.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def warm():
    return _load_warm()


def test_the_warm_script_forwards_the_single_implementation(warm) -> None:
    """判据 1：脚本里那一格必须就是 `cachectl.fingerprint`（转发，不是第二份实现）。"""
    assert warm.key_fingerprint is cachectl.fingerprint, (
        "scripts/warm_prompt_cache.py 的 key_fingerprint 不是 cachectl.fingerprint —— "
        "两处各写一份 sha256(key)[:16] 在空 key 上会给出相反结论（见模块 docstring）")


@pytest.mark.parametrize("key", ["", "sk-abc", "sk-with-中文-与空格 ", "0" * 40])
def test_the_two_call_sites_agree_on_every_key(warm, key: str) -> None:
    """判据 2：两个调用点（读数写入 / 当前身份）在每一个 key 上结论逐字相同。"""
    assert warm.key_fingerprint(key) == cachectl.fingerprint(key)
    # 空 key 这一档单独点名：它是两份实现在改前唯一分家的地方。
    if key == "":
        assert warm.key_fingerprint(key) == "", (
            "空 key 的指纹必须是空串（\"没有 key\"这一档）—— 回落到 sha256(\"\")[:16] 会让"
            " cachectl 把它读成\"换过 key 了\"")
