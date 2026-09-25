"""需要联网的 provider 回归测试 —— 默认不跑，用 `-m network` 显式开启。

为什么单独放一个文件并打标记：
`tests/` 的其余部分必须离线、确定性、可重复（否则 CI 会被限流和网络抖动搞红，
久而久之就没人看红灯了）。但缺陷 #6（Crossref `select=abst` 全 400）与
缺陷 #7（`precise` 召回为 0）恰恰是纯离线测试永远抓不到的 ——
它们的错误只出现在真实 HTTP 往返里。

折中方案：进套件（所以不会被遗忘），但默认 deselect（所以不会拖垮日常测试）。
`pytest.ini` 里用 `addopts = -m "not network"` 默认排除；要跑就：

    cd D:\\Incubator\\test\\test1\\src
    python -m pytest ..\\tests -q -m network

限流处理：命中 HTTP 429 时 `pytest.skip`（这是环境状况，不是代码缺陷）；
但 400 一律判失败 —— 那正是缺陷 #6 的形态。
"""

from __future__ import annotations

import pytest

from agentflow.providers import CrossrefProvider, HttpError, OpenAlexProvider

pytestmark = pytest.mark.network

MODES = ("broad", "topical", "precise")


def _search(provider, topic: str, mode: str, limit: int = 5):
    """统一的"限流即跳过、其它 HttpError 即失败"包装。"""
    try:
        return provider.search(topic, mode, "abelian group definition and its relation to group", limit)
    except HttpError as e:
        if getattr(e, "status", None) == 429:
            pytest.skip(f"{provider.name} 限流（HTTP 429），本次跳过：{e}")
        raise AssertionError(
            f"{provider.name}.search(mode={mode}) 抛了 HttpError：{e}\n"
            "若是 400，通常是请求参数里有 provider 不接受的字段名"
            "（缺陷 #6 就是 Crossref 的 select 用了 abst 而非 abstract）。"
        ) from e


# --------------------------------------------------------------- 缺陷 #6 的回归


@pytest.mark.parametrize("mode", MODES)
def test_crossref_all_modes_do_not_400(mode):
    """Crossref 三种模式都不得产生 400（缺陷 #6 回归）。

    缺陷 #6 的形态：`select` 里混入非法字段名 `abst`，Crossref 整请求返回 400。
    注意它不会忽略未知字段，所以任何一个模式 400 都说明请求构造有问题。
    """
    got = _search(CrossrefProvider(), "abelian group", mode)
    assert isinstance(got, list)
    assert got, f"Crossref 模式 {mode} 返回 0 条 —— 若上游确实无结果可放宽，但先确认不是参数问题"


# --------------------------------------------------------------- 缺陷 #7 的回归


@pytest.mark.parametrize("mode", MODES)
def test_openalex_all_modes_return_something(mode):
    """OpenAlex 三种模式都不许归零（缺陷 #7 回归）。

    判据是"是否归零"，不是"条数够多"：`precise` 的语义就是"命中明确课题"，
    召回少是预期行为。缺陷 #7 的形态是精确模式恒为 0，说明过滤把一切都丢掉了。
    """
    got = _search(OpenAlexProvider(), "abelian group", mode)
    assert got, (
        f"OpenAlex 模式 {mode} 返回 0 条。对 broad/topical 这一定是异常；"
        "对 precise 也异常 —— 设计意图是'无法判定时不过滤'，不该全丢（缺陷 #7）。"
    )


def test_precise_results_are_on_topic():
    """`precise` 不仅要非空，头几条还应与主题相关。

    这一条是"不许归零"的语义补充：如果实现改成"关掉过滤"来消除归零，
    那么召回会变多但切题度会掉下来 —— 本用例就是防这种"用错方式修好"。
    """
    got = _search(OpenAlexProvider(), "abelian group", "precise", 5)
    if not got:
        pytest.skip("上一条用例已覆盖非空断言")
    blob = " ".join((c.title or "").lower() for c in got[:3])
    assert ("abelian" in blob) or ("group" in blob), (
        f"precise 头几条都不含 abelian/group，说明过滤被关掉而非修好：{[c.title for c in got[:3]]}"
    )


# --------------------------------------------------------------- 基础连通性


def test_openalex_returns_wellformed_candidates():
    """候选的关键字段要真的被填上（防止解析悄悄退化成空壳）。"""
    got = _search(OpenAlexProvider(), "abelian group", "topical", 3)
    assert got
    c = got[0]
    assert c.title and c.title.strip()
    assert c.type_code in ("J", "M", "C", "D", "R", "S", "P", "N", "EB", "Z"), c.type_code
    assert c.provider == "openalex"
    assert c.raw, "raw 应保留原始记录，便于事后审计"
