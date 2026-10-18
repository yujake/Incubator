# -*- coding: utf-8 -*-
"""`Conjecture.validate`：**一次把问题说齐**（业主 2026-10-17 授权动禁改区后改）。

## 为什么改（亲测现场，见 `draft/132` 第十节）

按工具声明逐个补字段，实测走了**四轮**才凑齐一条猜想：

```
form 词表 → status='proposed' 要 testable → testable 要对象 → needs_evidence 要 notes
```

业主口径：*"凡是你凭感觉第一次运行工具发现红了，都要假想真实智能体也会在这里困惑并浪费
时间和 token。"*

## 改法与 B/F 两处**逐字同形**

先**收集**全部问题，再**一次抛**：只有一条问题时**原文案一字不动**；
多于一条时补一行整份清单（`**这一条还差**：… —— 一次给齐就不用再来回问。`）。

这一组钉三件事：
1. 多问题 ⇒ 一次点名（并且列出全部标签）；
2. **负控**：单问题 ⇒ 拒信里**不出现**"还差"那一行，且**原文案逐字不变**；
3. 合法 ⇒ 通过（别为了改拒信把正常路径弄坏）。
"""

from __future__ import annotations

from agentflow import schema as S

BASE = dict(conjecture_id="000000", statement="若 n≥3 则无解。", form="universal",
            status="proposed", origin="lit:000000", testable={"how": "对 n=3..12 逐个验"})


def _refusal(**over) -> str:
    kw = dict(BASE)
    kw.update(over)
    try:
        S.Conjecture(**kw).validate()
    except ValueError as exc:
        return str(exc)
    raise AssertionError(f"这一组本该被拒：{over!r}")


def test_several_problems_are_named_at_once() -> None:
    """正控：三处问题 ⇒ 一次点名三处（而不是顺序抛三次）。"""
    msg = _refusal(statement="  ", origin="", testable=None)
    for label in ("statement", "origin", "testable"):
        assert label in msg, f"没点名 {label}：{msg}"
    assert "还差" in msg, msg


def test_a_single_problem_keeps_the_original_wording() -> None:
    """**负控**：只有一处问题 ⇒ 原文案**逐字不变**，且**不挂**"还差"那一行。"""
    msg = _refusal(origin="")
    assert msg == "origin 必填：猜想的来源必须可追（report_id / rel:NNNN / gap / lit:NNNN）", msg
    assert "还差" not in msg, msg


def test_a_valid_conjecture_still_passes() -> None:
    """正控：合法 ⇒ 通过（正常路径不许被弄坏）。"""
    S.Conjecture(**BASE).validate()
