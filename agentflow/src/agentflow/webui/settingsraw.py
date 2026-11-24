# -*- coding: utf-8 -*-
"""设置文件「盘上原样」的那一面（读侧与写侧共用的唯一实现）。

## 为什么要有这个模块

`settings.load_settings()` 给的是盘上那份 JSON 的原样，而机器面过去报的是
`ModelSpec.redacted()` —— 后者是生效值（缺省已经填进去了）。两者混在一格里的
后果不是报错，而是"盘上没设过"看起来"设过了"：页面的输入框被回填成生效值，
用户一按写回就把缺省固化进 `settings.json`。

所以从这一版起，机器读数把三件事分开给（`raw` / `effective` / `source`）：

- `raw`：盘上写了什么（缺格 ⇒ 空串；`api_key` 仍只给 `MASKED_KEY`）；
- `effective`：运行期真正用的那一套（缺省与继承已经算进去）；
- `source`：这一格的值是从哪一档来的（`settings` / `env` / `default`）。

本模块只负责 `raw` 那一面 —— 它是读侧（`readers._settings_reading`）与写侧
（`writes.handle_settings` 的"给的值与 raw 相同 ⇒ 视为没改"）的同一份口径。
两处各写一份的话，"什么算没改"就会在某一侧悄悄漂掉，而漂掉之后没有任何地方会报错。

## 一个刻意的参数：`mask_secrets`

读侧必须拿掩码（`MASKED_KEY`），写侧必须拿真值（要判断"用户提交的 key 与盘上
那份是不是同一个"）。所以 :func:`raw_sections` 的缺省是掩码，写侧显式传
`mask_secrets=False`。真值只在这一条内部控制流里出现，绝不进任何回执/读数
（与 `settings._masked_section` 的"key 只写不读"同一条纪律）。
"""

from __future__ import annotations

from typing import Any, Mapping

from .. import settings as SET

__all__ = ["FLAT_SECTIONS", "is_masked", "raw_models", "raw_sections", "same_text"]

#: 平的三个段与各自认的键（顺序即文档顺序；与 `settings._write_sections` 同源）。
FLAT_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("toolchain", SET.TOOLCHAIN_KEYS),
    ("model", SET.MODEL_KEYS),
    ("workspace", SET.WORKSPACE_KEYS),
)


def _raw_cell(key: str, value: Any, *, mask_secrets: bool) -> str:
    """一格的盘上原样：布尔归一成 `true`/`false`，非字符串折空串，key 按需掩码。

    为什么非字符串折空串而不是 `str(value)`：`settings._section` 的读侧口径就是
    "非字符串当未设置"（写进来一个 `123` 当路径用比"没配"更难查）；读数若把它
    显示成 `123`，用户会以为这一格真被读到了。
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        if key == "api_key" and value and mask_secrets:
            return SET.MASKED_KEY
        return value
    return ""


def _seg_of(raw: Mapping[str, Any], section: str) -> Mapping[str, Any]:
    seg = raw.get(section)
    return seg if isinstance(seg, Mapping) else {}


def raw_flat(raw: Mapping[str, Any], section: str, keys: tuple[str, ...], *,
             mask_secrets: bool = True) -> dict[str, str]:
    """一个平段的盘上原样（`section` 不在 / 不是对象 ⇒ 每格空串）。"""
    seg = _seg_of(raw, section)
    return {k: _raw_cell(k, seg.get(k), mask_secrets=mask_secrets) for k in keys}


def raw_models(raw: Mapping[str, Any], *, mask_secrets: bool = True) -> dict[str, dict[str, str]]:
    """`models` 段的盘上原样：只给盘上真有的槽（每个槽补全 `MODEL_KEYS`）。"""
    out: dict[str, dict[str, str]] = {}
    for slot, body in _seg_of(raw, SET.MODELS_SECTION).items():
        if not isinstance(body, Mapping):
            continue
        out[str(slot)] = {k: _raw_cell(k, body.get(k), mask_secrets=mask_secrets)
                          for k in SET.MODEL_KEYS}
    return out


def raw_sections(raw: Mapping[str, Any], *,
                 mask_secrets: bool = True) -> dict[str, Any]:
    """整份设置的"盘上原样"，形状与机器面 `settings` 的三段 + 两段嵌套逐字对齐。

    返回 `{toolchain, model, workspace, models, secretary}`；除 `models` 外每段都是
    `{键: 字符串}`（缺格补空串），`models` 是 `{槽: {键: 字符串}}`。
    """
    out: dict[str, Any] = {
        name: raw_flat(raw, name, keys, mask_secrets=mask_secrets)
        for name, keys in FLAT_SECTIONS
    }
    out[SET.MODELS_SECTION] = raw_models(raw, mask_secrets=mask_secrets)
    out[SET.SECRETARY_SECTION] = raw_flat(raw, SET.SECRETARY_SECTION, SET.MODEL_KEYS,
                                          mask_secrets=mask_secrets)
    return out


def is_masked(value: Any) -> bool:
    """这一格提交的是不是掩码（`MASKED_KEY` 或"全是 `*`"）。

    为什么要认"全是 `*`"而不只认 `MASKED_KEY`：页面把 `***` 回填进输入框之后，
    浏览器/用户改一个字符又改回来、或者外部客户端手打一串星号，都会让
    "值等于常量"这条判据漏过去 —— 而漏过去的后果是把一串星号写成真 key。
    """
    text = str(value or "").strip()
    return bool(text) and set(text) == {"*"}


def same_text(given: Any, raw: Any) -> bool:
    """提交的值与盘上原样的值是不是同一件事（都去空白后逐字相同）。

    去空白与 `settings._clean_flat` 的落盘口径一致：它写进去之前会 `strip()`，
    所以"盘上是 ` x `、提交 `x`"落盘之后语义不变 —— 那一格不该算"改了"。
    """
    return str(given or "").strip() == str(raw or "").strip()
