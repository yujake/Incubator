# -*- coding: utf-8 -*-
"""一个子代理的结局只有三档：`schema.CHILD_ENDINGS` 是词表，`schema.child_ending` 是判定点。

## 这个文件修的是什么

改前那张词表是全仓 0 读者的摆设：`CHILD_ENDINGS` 写着「三档」，而唯一的判定点
`schema.child_ending()` 三个分支各把档名当字面量重写一遍 —— 词表改一个字母、多一档、
少一档，词表与行为就此分家，而没有任何东西会红（`ITEM_KINDS` / `ITEM_EXPECTS`
那一类词表不是这样：它们有真读者，`validate` 逐条核）。

改法：三档从词表里取 —— `CHILD_DELIVERED` / `CHILD_CUT_OFF_BY_PARENT` /
`CHILD_STOPPED` 是 `CHILD_ENDINGS` 的解包，判定点的三个分支各返回其中一档。

## 判据（穷举 + 反真空）

1. 三个分支各喂一组事实（父退场掐断 / 被叫停 / 子自己交差）⇒ 每个返回的 `ending`
   必须 ∈ `CHILD_ENDINGS`；
2. 三个分支覆盖的档集合恰好等于词表：一个分支一档、没有剩余、没有第四档。
   穷举是这一条的核心 —— 它同时挡住"词表里有一档没人产"与"产出了一档词表里没有"；
3. 词表有真读者（结构性）：判定点的源码里读到那三个常量，且不再有
   `"ending": "<字面量>"` 这种写法；
4. 反真空：喂一张少一档 / 多一档的词表 ⇒ 2 必红（判据不是橡皮图章）。

为什么 4 喂替身、而不是真去删词表里那一档：真删会让 `schema.py` 导入期解包当场抛
`ValueError: not enough values to unpack`，那时任何判据都不可能绿 —— 替身证明的是
"判据本身会咬"，导入期那一手挡的是"词表被悄悄改短"。
"""
from __future__ import annotations

import inspect

from agentflow import schema as S

#: 三个分支：每一项是（这一组说的是什么事实，喂给 `child_ending` 的关键字）。
#: 顺序与 `CHILD_ENDINGS` 无关（判据比的是集合，不是次序）：次序一换就红的话，
#: 这一条会变成"改词表顺序要跟着改字符串"的第二个真身。
BRANCHES: tuple[tuple[str, dict], ...] = (
    ("父代理退场时它还在跑（cut_off=True）", dict(cut_off=True)),
    ("被叫停（stop_code='user'）", dict(stop_code="user")),
    ("子自己交了差（status='done' / outcome='ok'）", dict(status="done", outcome="ok")),
)

#: 三档的常量名（判定点该读的那三个名字）。
CONSTANTS: tuple[str, ...] = (
    "CHILD_DELIVERED",
    "CHILD_CUT_OFF_BY_PARENT",
    "CHILD_STOPPED",
)


def _endings() -> dict[str, str]:
    """三个分支各判一次 ⇒ `{这个分支说的是什么: 落下的档}`。"""
    return {why: str(S.child_ending(**kw).get("ending") or "")
            for why, kw in BRANCHES}


def _drift(vocabulary: tuple[str, ...] | None = None) -> list[str]:
    """分支读数与词表的差：空列表 = 三档一一对应（判据的本体）。

    形参只为让反真空能喂一张被改坏的词表；真正跑的那一次读的是 `S.CHILD_ENDINGS`。
    """
    vocab = tuple(S.CHILD_ENDINGS if vocabulary is None else vocabulary)
    got = _endings()
    problems: list[str] = []
    for why, ending in got.items():
        if not ending:
            problems.append(f"{why}：没有给出 ending（空串不是一档）")
        elif ending not in vocab:
            problems.append(f"{why} 落了 {ending!r}，而它不在 CHILD_ENDINGS {vocab} 里")
    covered = [ending for ending in got.values() if ending]
    missing = [tier for tier in vocab if tier not in set(covered)]
    if missing:
        problems.append(f"CHILD_ENDINGS 里这些档没有任何分支产出：{missing}")
    dupes = sorted(tier for tier in set(covered) if covered.count(tier) > 1)
    if dupes:
        problems.append(f"这几个档被两条分支同时产出（三档该一一对应）：{dupes}")
    extra = sorted(set(covered) - set(vocab))
    if extra:
        problems.append(f"这些分支产出了词表之外的档：{extra}")
    return problems


# ============================================================ 1 穷举：三档一一对应
def test_the_three_branches_cover_the_vocabulary_exactly() -> None:
    """判据 1+2：三个分支各落一档，且合起来恰好是 `CHILD_ENDINGS`（不多不少）。"""
    assert len(BRANCHES) == 3, (
        f"判定点的分支数是三，这里写了 {len(BRANCHES)} 组事实 —— "
        "加一档就要同时改词表、判定点与这一条：三处必须一起动")
    problems = _drift()
    assert problems == [], (
        "child_ending() 的三档与 schema.CHILD_ENDINGS 对不上：\n  - "
        + "\n  - ".join(problems)
        + "\n改法：档名从词表取（`CHILD_ENDINGS` 的解包常量），不要在判定点里重写字面量。"
    )


def test_every_returned_ending_is_a_member_of_the_vocabulary() -> None:
    """判据 1（单独一条）：每个分支返回的 `ending` 都在词表里。

    与上一条拆开读的理由：上一条红的时候要说清是"有档没人产"还是"产出了词表外的档"，
    折成一条断言会让失败信息只剩一句"对不上"。
    """
    for why, ending in _endings().items():
        assert ending in S.CHILD_ENDINGS, (
            f"{why} 落下的 `ending` 是 {ending!r}，而 `schema.CHILD_ENDINGS` 只有 "
            f"{S.CHILD_ENDINGS} —— 判定点产出了一个词表里不存在的档")


# ============================================================ 2 词表有真读者（结构性）
def test_the_vocabulary_has_a_real_reader() -> None:
    """判据 3：三档从词表取，不是判定点里各写一遍字面量（改前的"摆设"形态）。

    两半都要：
      - 三个常量存在、且逐字等于词表（词表短了会在导入期炸，这里是给读的人看的读数）；
      - 判定点的源码里读得到那三个常量，且不再出现 `"ending": "<字面量>"`。
    """
    for name in CONSTANTS:
        assert hasattr(S, name), (
            f"`schema` 上没有 {name} —— 三档没有从 `CHILD_ENDINGS` 解包出来，"
            "判定点就还是在重写字面量")
    assert (S.CHILD_DELIVERED, S.CHILD_CUT_OFF_BY_PARENT, S.CHILD_STOPPED) == S.CHILD_ENDINGS, (
        "三个常量与 `CHILD_ENDINGS` 不是同一份东西（解包之后又被改过？）")
    src = inspect.getsource(S.child_ending)
    for name in CONSTANTS:
        assert name in src, (
            f"`child_ending()` 的源码里读不到 {name} ⇒ 那一档是字面量，"
            "词表对它没有约束力（改前就是这种形态）")
    assert '"ending": "' not in src, (
        "`child_ending()` 里还有 `\"ending\": \"…\"` 这种字面量写法 —— "
        "三档必须从 `CHILD_ENDINGS` 取，不许在判定点里再写一遍")


# ============================================================ 3 反真空
def test_a_vocabulary_that_drops_a_tier_makes_the_judgement_red() -> None:
    """判据 4（反真空）：从词表里删一档 ⇒ 覆盖判据必红，且点名那一档。"""
    assert _drift() == [], "反真空的前提坏了：真词表下这条判据本已是绿的"
    dropped = tuple(tier for tier in S.CHILD_ENDINGS if tier != "stopped")
    assert len(dropped) == len(S.CHILD_ENDINGS) - 1, (
        f"替身没造出来：词表里没有 `stopped`（{S.CHILD_ENDINGS}）")
    problems = _drift(vocabulary=dropped)
    assert problems, (
        "把 `stopped` 从词表里删掉，覆盖判据居然还是绿的 —— 它是橡皮图章")
    flat = "；".join(problems)
    assert "stopped" in flat, f"红了，但没有点名被删的那一档：{problems}"


def test_a_vocabulary_with_an_extra_tier_makes_the_judgement_red() -> None:
    """判据 4（反真空的另一半）：词表多一档而没有任何分支产它 ⇒ 必红。"""
    bloated = tuple(S.CHILD_ENDINGS) + ("escaped",)
    problems = _drift(vocabulary=bloated)
    assert problems, (
        "词表里多了一档 `escaped`，覆盖判据居然还是绿的 —— "
        "「三档」这句话可以随便加一档而没人管")
    assert "escaped" in "；".join(problems), problems
