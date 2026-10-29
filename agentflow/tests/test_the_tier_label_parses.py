# -*- coding: utf-8 -*-
"""判据：档位解析必须认 `T0`–`T4` —— 判档那一问的决策词表就是它。

## 真 bug（2026-10-29，读码发现）

`_judge_system` 的 `statement_aesthetic` 题面与 `JUDGE_VERDICTS` 都把结论词表写成
`T0..T4`，而 `_nontriviality_level` 只认整数 / 纯数字串：

```
_nontriviality_level("T3")  →  None      # 模型照题面答 T3，被读成"判不了"
```

后果："交给模型判"这条路在结构上走不通 —— 模型判什么都被解析成 None，
下游于是永远拿到"未判"（真机上还会被旧口径补成 T0）。

## 这一组守什么

1. 正题：`T3` / `t3` / `3` / `3` 都要给出 3；
2. 反真空：`9` / `"9"` / `"x"` / `""` / `True` 必须仍是 None（三态：坏输入不是"第 9 档"，也不许折成 0）。
"""
from __future__ import annotations

import pytest

from agentflow.secretary import _nontriviality_level


@pytest.mark.parametrize("raw", ["T0", "t0", "0", 0])
def test_the_t0_label_and_number_both_parse(raw):
    """T0 与 0 都给出 0（0 是一档真的档位，不是"判不了"）。"""
    assert _nontriviality_level(raw) == 0, raw


@pytest.mark.parametrize("raw", ["T3", "t3", "3", 3])
def test_the_t3_label_and_number_both_parse(raw):
    """T3 与 3 都给出 3 —— 模型照题面答的就是 T3。"""
    assert _nontriviality_level(raw) == 3, raw


@pytest.mark.parametrize("raw", ["9", 9, "x", "", None, True, False, 1.9])
def test_bad_input_stays_unjudged(raw):
    """反真空：坏输入一律 None（不静默降级成 0，也不当成某档）。"""
    assert _nontriviality_level(raw) is None, raw
