# -*- coding: utf-8 -*-
"""审核类调用必须**可复现**：请求体里钉死采样（业主 2026-10-17 长跑口径）。

## 现场（`draft/136` 的长跑预演，2026-10-17）

V 的 `verify_proof` 是**一次模型调用**（`LlmSeam(role='V')`）。同一命题、同一份证明，
实测三次新库得到 **`有毛病` / `成立` / `有毛病`** —— 判定随采样摆动。

后果直接砸在业主的口径上：*"自证定理在审核后要能进定理库"* ——
以 `verdict=成立` 为条件的门**天生不可复现** ⇒ 长跑里"有时进库、有时不进"，
证明链反复开合（F 的链永远闭不上）。

## 修法与判据

`src/agentflow/modelclient.py` 的**请求体**里加了 `"temperature": 0`（唯一构造处）。
这一组判据**离线**钉住它：不真调模型，只断言"发出去的请求体里采样是钉死的" ——
这样 CI 不必联网，而"可复现"这件事**不许被悄悄改回去**。

（为什么不在判据里连调模型 5 次：那要 key、要钱、要网，而且会随上游漂 ——
判据钉**我们这一侧发出的东西**，这才是我们能负责的那一半。）
"""

from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "agentflow" / "modelclient.py"


def test_the_request_body_pins_sampling() -> None:
    """正控：请求体里有 `temperature: 0`（钉死采样）。"""
    text = SRC.read_text(encoding="utf-8")
    assert re.search(r'"temperature":\s*0\b', text), (
        "modelclient 的请求体里没有把 temperature 钉成 0 ⇒ 审核判定会随采样摆动，"
        "而\"经审核才进库\"的门就不可复现"
    )


def test_the_default_is_explained_where_it_is_set() -> None:
    """负控（防误删）：这一栏旁边必须写明**为什么**（否则下一个人会当冗余删掉）。"""
    text = SRC.read_text(encoding="utf-8")
    idx = text.index('"temperature": 0')
    window = text[max(0, idx - 600):idx]
    assert "可复现" in window or "采样" in window, (
        "`temperature: 0` 旁边没有说明它为什么存在 ⇒ 迟早被当成冗余删掉"
    )
