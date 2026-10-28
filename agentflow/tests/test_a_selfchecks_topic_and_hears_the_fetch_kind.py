# -*- coding: utf-8 -*-
"""判据（阶段 ③ 第 2C 步）：A 的主动性口径，与 broad 之后的主题相关性自检。

## 两件事，一条判据各钉一半

### 一、A 要被告知「下载失败 ≠ 这篇不存在」

真机（`draft/172` §4 第 4 轮 O-04 / §8 第 3 轮）：`search.download` 10 次成功 4 次，
失败 6 次是 404 / 429 / 400 各两次 —— 每一类的正确处置不同（429 等冷却、404 换
landing、400 换 PDF 路由）。而 A 当时的行为是把「没下来」归到「这篇找不到」，
于是 27 篇只有元数据的文献被它当成「本来就没有」。口径必须写进渲染出来的提示词里
（只写进 `specs/a.py` 的声明、没进提示词，模型读不到 —— 那种错法本仓踩过）。

### 二、broad 之后把「明显跑题」的候选标 `off_topic`

`draft/172` O-05 的真机读数：broad 抓回「Hodge theory and derived categories」
「A heuristic for boundedness of ranks」这类噪声，而判官那一步会为它们各花一次调用。
判据要把它做成一条可复核的机器读数，而且要守住三条：

1. `off_topic` 只在判得出时给：topic 抽不出英文词（纯中文题面）、或标题不是英文
   ⇒ `unknown`（判不了）。把 `unknown` 折进 `off_topic` 就是「判不了」冒充「判过了」。
2. 只标不删：候选一条都不许消失（真机上是"省一次判官调用"，不是"少给 A 几条"）。
3. 标记必须走到 A 读的那个候选列表里（`search.literature` 的 `candidates[]`），
   否则它只是 providers 层内账本上的一个数。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import agent_prompts as AP
from agentflow import providers as P
from agentflow.tools import build_registry, search_tools
from agentflow.tools.base import ToolRegistry

#: 一个"明显相关"的题面与标题、一个"明显跑题"的标题、一个"判不了"的组合。
TOPIC = "large sieve inequality"
RELATED_TITLE = "The large sieve inequality for algebraic number fields"
OFF_TOPIC_TITLE = "Hodge theory and derived categories of coherent sheaves"
CJK_TOPIC = "大筛不等式"


# ---------------------------------------------------------------- 一、A 的口径


def _a_prompt() -> str:
    """A 这一次真正读到的提示词（渲染路径，不是 `specs/a.py` 那一段声明）。"""
    registry = build_registry().registry
    return AP.system_prompt("A", registry=registry, task="找几篇关于大筛不等式的文献",
                            workspace_root="D:/x")


def test_a_is_told_that_a_failed_download_is_not_a_missing_paper():
    """A 的提示词里必须有这四句口径（缺一句，模型就会按旧习惯把"没下来"写成"没有"）。"""
    text = _a_prompt()
    assert "取不到全文不等于这篇不存在" in text, (
        "A 的提示词里没有「取不到全文不等于这篇不存在」这句 —— 这一条是这批的正题"
    )
    for needle, why in (
        ("429", "429 要等冷却（换成换地址重试就是白烧时间）"),
        ("404", "404 要换 landing（那个直链就是死的）"),
        ("400", "400 要换 PDF 路由（构造出来的链接走不通）"),
    ):
        assert needle in text, f"A 的提示词里没有 {needle}：{why}"
    assert "`search.retry_pending`" in text, (
        "A 的提示词里没提批量再取的那一件工具 ⇒ 它只会一条条手工 search.download"
    )
    # 三态：取不到时要的是"如实登记没取"，不是"把它划掉"
    assert "如实登记" in text, "A 的提示词里没写「取不到就如实登记」"


def test_the_policy_reaches_the_prompt_through_the_single_source():
    """这段口径的真身是 `specs/a.py::SPEC.brief.policy`，渲染时从那里取（没有第二份）。"""
    from agentflow import specs as SP

    policy = SP.builtin_specs()["A"].brief.policy
    assert any("取不到全文不等于这篇不存在" in line for line in policy), (
        "specs/a.py 的 policy 里没有这句 ⇒ 提示词里那一句就成了别处手抄的一份"
    )
    assert AP.ROLE_BRIEFS["A"].policy == policy, "ROLE_BRIEFS 不是 specs 的视图了（出现第二份）"


# ---------------------------------------------------------------- 二、主题自检


def test_the_selfcheck_says_unknown_when_it_cannot_judge():
    """三态：判得出相关 / 判得出跑题 / 判不了 —— 后者不许折进 `off_topic`。"""
    related, _ = P.topic_selfcheck(TOPIC, RELATED_TITLE)
    off, _ = P.topic_selfcheck(TOPIC, OFF_TOPIC_TITLE)
    unknown, note = P.topic_selfcheck(CJK_TOPIC, RELATED_TITLE)
    assert related == "related", related
    assert off == "off_topic", off
    assert unknown == "unknown", (
        f"topic 是纯中文时机器判不出英文标题的相关性，必须给 unknown（现在给的是 {unknown!r}）"
    )
    assert "no_ascii_keywords" in note, note


def test_the_selfcheck_marks_but_never_drops_a_candidate():
    """只标不删：条数、顺序都不变；而且不改原对象（候选是共享的，就地改会污染台账）。"""
    cands = [
        P.Candidate(title=RELATED_TITLE, doi="10.1/a", provider="openalex"),
        P.Candidate(title=OFF_TOPIC_TITLE, doi="10.1/b", provider="openalex"),
    ]
    marked = P.mark_topic_selfcheck(cands, TOPIC, mode="broad")
    assert len(marked) == len(cands) == 2, "自检不许删候选"
    assert [c.title for c in marked] == [c.title for c in cands], "顺序也不许变"
    assert marked[0].raw["topic_selfcheck"]["state"] == "related"
    assert marked[1].raw["topic_selfcheck"]["state"] == "off_topic"
    assert "topic_selfcheck" not in cands[1].raw, (
        "自检就地改了原候选的 raw ⇒ providers 的台账与下游看到的不是同一份事实"
    )


def test_only_broad_mode_is_selfchecked():
    """precise 已经剔除跑题的（另一条判据），topical 不做标题判决 ⇒ 只有 broad 打这个标。

    为什么必须分开：三种模式对"跑题"的处置本来就不同（precise 删、broad 标、topical 不判）。
    在 precise 上再打一次标，等于给同一件事立两个口径。
    """
    class _Stub:
        name = "openalex"

        def search(self, topic, mode, description="", limit=0):
            return [P.Candidate(title=RELATED_TITLE, doi="10.1/a", provider="openalex"),
                    P.Candidate(title=OFF_TOPIC_TITLE, doi="10.1/b", provider="openalex")]

    multi = P.MultiProvider([_Stub()])
    broad = multi.search(TOPIC, "broad")
    assert all("topic_selfcheck" in c.raw for c in broad), "broad 的候选没打自检标"
    topical = P.MultiProvider([_Stub()]).search(TOPIC, "topical")
    assert all("topic_selfcheck" not in c.raw for c in topical), (
        "topical 模式不该有自检标（它不做标题判决）"
    )


def test_the_mark_reaches_the_candidates_a_reads():
    """标记必须出现在 `search.literature` 的 `candidates[]` 里 —— 那才是 A 读到的那一份。"""
    class _Stub:
        name = "openalex"

        def search(self, topic, mode, description="", limit=0):
            return [P.Candidate(title=RELATED_TITLE, doi="10.1/a", provider="openalex"),
                    P.Candidate(title=OFF_TOPIC_TITLE, doi="10.1/b", provider="openalex")]

    reg = ToolRegistry(name="topic-selfcheck")
    reg.bound_role = "A"
    search_tools.register(reg, store=None, providers=[_Stub()], workspace=Path("."))
    res = reg.call("search.literature", topic=TOPIC, mode="broad")
    assert res.ok, res.error
    states = [c.get("topic_selfcheck", {}).get("state") for c in res.data["candidates"]]
    assert states == ["related", "off_topic"], states
    assert "'topic_selfcheck'" in reg.get("search.literature").returns, (
        "`returns=` 里没点名 topic_selfcheck ⇒ 模型不知道这一格存在"
    )
