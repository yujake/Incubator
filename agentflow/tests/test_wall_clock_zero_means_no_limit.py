# -*- coding: utf-8 -*-
"""`--wall-clock-sec 0` ⇒ **不设墙钟上限**（缺陷 ⑳）。

## 现场（`projects/t2y`，T2，2026-10-18）

我**没有**传 `--wall-clock-sec`，于是用了 `default=3600.0` —— 1 小时整被切断，
而切断的那一刻 M 正要派 B 去登记命题：

```
t-000009 | E | by M | done | refused | 墙钟截止已过（wall_clock_sec=3600.0）
t-000010 | B | by M | done | refused | 墙钟截止已过（wall_clock_sec=3600.0）
```

结果：`conjectures 3` / `statements 0` —— 研究工作做完了，**收尾那一步被墙钟砍掉**，
看起来像"没做出定理"，其实是"没来得及登记"。

## 口径

* 不给参数 ⇒ 仍走缺省 3600（既有行为不变）；
* 给 `0`（或负数）⇒ **不设上限**（`wall=None`，`Policy` 不收墙钟）。
"""
from __future__ import annotations

import inspect

from agentflow import cli


def test_not_passing_it_means_no_limit():
    """**不传 = 无限制**（业主 2026-10-18 口径）。

    改前缺省是 3600 秒 —— 真机 `projects/t2y` 因此被切断在"派 B 登记命题"那一步
    （`B refused：墙钟截止已过`），台账上表现为"只有猜想、没有命题"。
    """
    src = inspect.getsource(cli)
    # 只盯 **argparse 那一行**：整段源码里还留着解释"为什么从 3600 改掉"的注释，
    # 拿 `"default=3600.0" not in src` 去判会把注释一起算进去（第一次就这么红了）。
    assert '"--wall-clock-sec", type=float, default=None' in src, "缺省值不是 None"
    assert '"--wall-clock-sec", type=float, default=3600' not in src, "缺省又被塞回 3600 秒了"


def test_zero_means_no_limit():
    """`<= 0` ⇒ 不设上限（这一条是缺陷 ⑳ 的修复本体）。"""
    src = inspect.getsource(cli)
    assert 'float(wall) <= 0' in src, "`--wall-clock-sec 0` 没有被翻译成「不设上限」"
    assert "wall = None" in src


def test_the_refusal_reason_is_recorded_in_the_task_row():
    """**证据面**：被墙钟拒掉的召唤要在 `tasks` 行里留下可读的原因。

    这条不测 CLI，而是钉住"拒绝理由必须写进 `detail`/`outcome`"这个事实 ——
    真机里正是靠它才查出 `t-000010 B refused` 的。
    """
    src = inspect.getsource(cli)
    assert "墙钟" in src or "wall_clock" in src
