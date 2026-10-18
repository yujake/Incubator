# -*- coding: utf-8 -*-
"""被限流的 provider 要**冷却**，不许被下一问立刻再试（缺陷 ⑰）。

## 现场（真机 `projects/t2w`，2026-10-18）

⑭ 让"不再睡 60 秒"生效之后，A 换一个 query **又从头把 OpenAlex 试一遍**：

```
OpenAlex 查询路失败（HTTP 429）… × 8 行，中间夹着"不在原地等"的换源决定
消费：9 分钟不动（$0.7124 没变），进程活着 —— 时间全耗在同一个已限流的源上
```

## 现在的口径

`providers` 里有一张**进程内**冷却表：

* 某个 provider 抛过"每一路都失败" ⇒ `start_provider_cooldown(name)`（默认 300 秒）；
* `Provider.search` 一进来就查冷却 ⇒ 冷却期内**立刻**抛 `ProviderError`，**不碰网络**；
* 冷却会自己过期（`_provider_cooling` 读到 <=0 就把条目删掉）。
"""
from __future__ import annotations

import inspect

from agentflow import providers as P


def test_a_provider_can_be_put_on_cooldown_and_it_expires():
    """**正控**：记一段冷却 ⇒ 读得到；`seconds=0` ⇒ 立刻过期。"""
    P.clear_provider_cooldowns()
    try:
        assert P._provider_cooling("openalex") == 0.0
        sec = P.start_provider_cooldown("openalex")
        assert sec == P.PROVIDER_COOLDOWN_SEC
        assert P._provider_cooling("openalex") > 0
        P.start_provider_cooldown("openalex", seconds=0)
        assert P._provider_cooling("openalex") == 0.0, "0 秒的冷却必须立刻过期"
    finally:
        P.clear_provider_cooldowns()


def test_clearing_removes_every_entry():
    """**负控**：`clear_provider_cooldowns` 真的清空（判据之间不许互相污染）。"""
    P.start_provider_cooldown("a")
    P.start_provider_cooldown("b")
    assert P._provider_cooling("a") > 0 and P._provider_cooling("b") > 0
    P.clear_provider_cooldowns()
    assert P._provider_cooling("a") == 0.0 and P._provider_cooling("b") == 0.0


def test_every_provider_checks_the_cooldown_before_touching_the_network():
    """**接线**：**每一个** provider 的 `search` 入口都有那道判据。

    第一版补丁只落进了 `OpenAlexProvider`（按"每一路都失败"那条错误定位），
    其余四个被限流时仍会被下一问立刻再试 —— 这条判据把"全都有"钉住。
    """
    classes = [P.OpenAlexProvider, P.CrossrefProvider, P.DoajProvider,
               P.EuropePmcProvider, P.FixtureProvider]
    missing = [c.__name__ for c in classes
               if "_provider_cooling(self.name)" not in inspect.getsource(c.search)]
    assert not missing, f"这些 provider 的 search 入口没有冷却判据：{missing}"
    src = inspect.getsource(P.OpenAlexProvider.search)
    assert "_provider_cooling(" in src, "search 入口没有查冷却"
    # 必须是**抛**（让调用方换源），不是默默返回空列表（那会被读成"上游没有这个主题"）
    assert "raise ProviderError" in src
    assert "正在限流冷却" in src


def test_the_failed_every_channel_path_starts_a_cooldown():
    """**接线（抛点）**：'每一路都失败'那条抛点必须记冷却。"""
    src = inspect.getsource(P.OpenAlexProvider.search)
    idx_raise = src.find("每一路都失败")
    assert idx_raise > 0
    window = src[max(0, idx_raise - 800):idx_raise]
    assert "start_provider_cooldown(" in window, (
        "抛'每一路都失败'之前没有记冷却 —— 下一个 query 会立刻再试这个源")
