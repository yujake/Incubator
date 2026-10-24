# -*- coding: utf-8 -*-
"""判据（业主 2026-10-24 裁定）：G 缺命题 / 缺证明时提给 D，不是直接召唤 B。

业主原话（唯一权威）：

    「G想和B协作的动机我清楚了，但G需要走D的登记才能向B请求收录。
       B收录系统自己产出的定理和证明的正统方式就是从D侧接研究手稿」

## 现场（cube2 05:29:59 t-000039、05:31:59 t-000040；r34d 05:20:09 t-000019）

那三行都是 `role=B` / `called_by=G` / `outcome=refused` /
`refusal_reason=forbidden_edge`，detail 逐字是「G → B 不在策略允许的边里
（G 只能召唤 ['A','D','E','F']）；改派 A、D、E、F」。

根因：`specs/g.py` 的 D-40 那一条只写到「正文结构以 B 台账登记的命题为准」，
没写「命题不够、证明不够的时候该找谁补」—— 于是模型把「让 B 去登记一条」
读成了下一步动作，撞在边表上（边表那一半本来就对：`G → B` 不在
`capabilities.ALLOWED_EDGES` 里）。

所以这一条补的是正向路径：正文缺命题 / 缺证明时，把缺口提给 D；D 出研究手稿
并把命题与证明登记进台账；B 是从 D 侧的研究手稿收录入库的那一方。

## 这一组判四条

| # | 判据 | 改前 |
|---|---|---|
| ① | G 渲染出来的提示词里读得到「缺命题 → 提给 D」「B 从 D 侧的研究手稿收录入库」这一层意思（十条逐条核），且这些话逐字在 `specs/g.py` 的 policy 里 | 红：policy 里一个字都没有 |
| ② | 提示词里没有「派 B / 召唤 B / 找 B / 让 B / 命令 B / 向 B 请求」这类直接指向（例外：「不能直接召唤 B」那一句本身）；而那句真的在 —— 否则这一条的豁免会把它豁免成真空 | 红：那句禁语还没有落点 |
| ③ | 反真空：把这一条 policy 从真身上摘掉 ⇒ ① 必红；换回去又绿 | 红：没有可摘的那一条 |
| ④ | 结构：G 的可召唤面仍是 A/D/E/F（B 不在里面），提示词里的伙伴条目仍是那四个 | 绿（护栏：补提示词不许顺手加边，这里只读面，不重复跑 summon） |

④ 单独放一条的理由：这一批只许改文案。端到端派一次 `G → B` 拿
`forbidden_edge` 的判据已经在（`tests/test_agent_loop.py` 的越权那一条与
`tests/test_policy.py` 的边表那几条），再跑一遍是同义重复；这里要守的是
「补那句话的人没有顺手把 B 加进 G 的出边」—— 一个纯结构读数。

零模型调用（提示词是纯函数，边表是常量）。
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow.specs import builtin_specs
from agentflow.tools import build_registry

#: 强调符号与空白：判「读到的意思」，不判排版（与 `test_d40` / `test_d36` 同一口径）。
_EMPHASIS = re.compile(r"[\s*`]+")

#: 伙伴条目的行首（与 `tests/test_agent_prompts.py::_PARTNER_BULLET` 同一形状）。
_PARTNER_BULLET = re.compile(r"^- ([A-Z])：")

#: ① 要读到的十条（去掉强调与空白之后逐条核）。
#:
#: 拆成十条而不是一整句：语序可以改，意思不许缺 —— 缺哪一条，模型就会少一个
#: 判断依据（缺「提给 D」它仍会去试 B；缺 `forbidden_edge` 它不知道被拒的名字；
#: 缺「白丢一步」它不知道代价）。
_NEEDLES: tuple[tuple[str, str], ...] = (
    ("缺命题", "正文缺命题时要有一个动作"),
    ("提给 D", "缺口提给 D（不是提给 B）"),
    ("缺哪一条命题", "派活里写清缺的是哪一条命题"),
    ("D 出研究手稿", "D 侧出研究手稿并登记"),
    ("B 是从 D 侧的研究手稿收录入库的", "B 的入库口在 D 侧的研究手稿"),
    ("G→B 这条边不存在", "G 到 B 没有这条边，这件事写明"),
    ("你能召唤的只有 A / D / E / F", "可召唤面逐个点名"),
    ("forbidden_edge", "撞上去的受控理由码"),
    ("白丢一步", "代价：这一步白丢"),
    ("不能直接召唤 B", "那句直说（判据 ② 的豁免锚点）"),
)

#: ② 的禁语（直接指向 B）。判的是「读到的意思」：去掉强调与空白之后扫。
#:
#: 刻意不放「请 B」：伙伴表里 A 的边界原话就写着「检索完请 B 整理」—— 那是对 A
#: 说的，不是 G 在给自己指路，算进来就是假红（实测本仓 G 的提示词里它出现 1 次）。
_DIRECT_POINTING: tuple[tuple[str, str], ...] = (
    ("派 B", "派 B 去做"),
    ("召唤 B", "召唤 B"),
    ("找 B", "找 B"),
    ("让 B", "让 B"),
    ("命令 B", "命令 B"),
    ("向 B 请求", "向 B 提请求"),
)

#: ② 的豁免锚点：那一句自身写着「不能直接召唤 B」，扫的时候整句摘掉。
_EXEMPT = "不能直接召唤 B"

#: 提示词渲染下限（反真空：空串或占位文本不许通过）。
_MIN_CHARS = 3000

_TASK = "整理成论文"
_ROOT = "D:/x"
_FACTS = ("这台机器上的证明工具链（现算读数，不是记忆）：\n"
          "- 检查器：（判据夹具，与机器无关）")
_FORMAL = ("你这一岗怎么写形式化（由上面那份读数现算）：\n"
           "- （判据夹具：这一次按自足文件写）")


def _flat(text: str) -> str:
    """去掉强调符号与所有空白 —— 判「读到的意思」，不判排版。"""
    return _EMPHASIS.sub("", str(text))


def _render_g() -> str:
    """真的渲染一遍 G 的提示词（纯函数，零模型调用）。"""
    return AP.system_prompt("G", registry=build_registry().registry, task=_TASK,
                            workspace_root=_ROOT, toolchain_facts=_FACTS,
                            toolchain_formal=_FORMAL)


def _prompt_problems(text: str) -> list[str]:
    """① 的正文：渲染后的提示词里缺了哪几个意思（空清单 = 都在）。"""
    if len(str(text)) < _MIN_CHARS:
        return [f"渲染出来的提示词只有 {len(str(text))} 字（下限 {_MIN_CHARS}）"
                " ⇒ 这一条没有落脚点（它不是在判一份真的提示词）"]
    flat = _flat(text)
    return [f"读不到「{needle}」这件事（{why}）—— 这一句必须逐字进 specs/g.py 的 policy"
            for needle, why in _NEEDLES if _flat(needle) not in flat]


def _without_the_exempt_sentence(text: str) -> str:
    """去掉含 `_EXEMPT` 的那一句（含豁免锚点的是同一句，不连带删别的）。"""
    flat = _flat(text)
    kept = [seg for seg in re.split(r"[。\n]", flat) if _flat(_EXEMPT) not in seg]
    return "。".join(kept)


# ============================================================ ① 正控：提给 D
def test_1_the_g_prompt_says_the_gap_goes_to_d_and_b_ingests_from_d() -> None:
    """① G 的渲染提示词里读得到那一层意思（十条逐条核），policy 里逐字也有。"""
    text = _render_g()
    bad = _prompt_problems(text)
    assert bad == [], "\n".join(bad)
    # 那段的真身是 specs/g.py 的 policy（提示词只是把它渲染出来）：两处都要有，
    # 否则「提示词里有」可能只是别的一段碰巧写着同样的话。
    from agentflow.specs import g as GS

    policy = "\n".join(GS.SPEC.brief.policy)
    missing = [needle for needle, _why in _NEEDLES if needle not in policy]
    assert missing == [], f"specs/g.py 的 policy 里缺 {missing}"


# ============================================================ ② 没有直接指向
def test_2_the_g_prompt_does_not_point_at_b_directly() -> None:
    """② 提示词里没有直接指向 B 的说法（那一句禁语自身除外），而那句真的在。"""
    text = _render_g()
    flat = _flat(text)
    assert _flat(_EXEMPT) in flat, (
        "提示词里没有「不能直接召唤 B」这一句 ⇒ 下面的豁免没有锚点，"
        "这条判据会退化成一个恒真的扫描（真空）")

    body = _without_the_exempt_sentence(text)
    assert _flat(_EXEMPT) not in body, "夹具失效：豁免句没有被摘掉"
    hits = [(needle, why) for needle, why in _DIRECT_POINTING if _flat(needle) in body]
    assert hits == [], (
        "提示词里有直接指向 B 的说法（模型会照它去派 B，撞 `forbidden_edge`）："
        + "、".join(f"「{n}」（{w}）" for n, w in hits))


# ============================================================ ③ 反真空
def test_3_deleting_the_sentence_turns_criterion_one_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 反真空：把这一条 policy 从真身上摘掉 ⇒ ① 必红；换回去又绿。"""
    brief = AP.ROLE_BRIEFS["G"]
    kept = tuple(p for p in brief.policy if "把缺口提给 D" not in str(p))
    assert len(kept) == len(brief.policy) - 1, (
        "夹具前提：那一条 policy 真的装着这句话（否则下面摘的是空）")
    stripped = dataclasses.replace(brief, policy=kept)
    monkeypatch.setitem(AP.ROLE_BRIEFS, "G", stripped)
    bad = _prompt_problems(_render_g())
    assert bad, ("把这一段摘掉之后 ① 还是绿的 ⇒ 它判的不是提示词里那段话")
    assert any("提给 D" in one for one in bad), bad

    # 负控的负控：换回去 ⇒ 判据重新成立（这一半让本条在改前也红）
    monkeypatch.setitem(AP.ROLE_BRIEFS, "G", brief)
    assert _prompt_problems(_render_g()) == [], "换回去之后 ① 仍然红"


# ============================================================ ④ 结构：面没被加宽
def test_4_the_summonable_face_of_g_is_still_a_d_e_f() -> None:
    """④ 补文案不许顺手加边：G 的可召唤面仍是 A/D/E/F，提示词里的伙伴条目也是那四个。"""
    assert tuple(builtin_specs()["G"].edges) == ("A", "D", "E", "F"), (
        f"G 的声明边被改了：{builtin_specs()['G'].edges}")
    assert C.ALLOWED_EDGES["G"] == frozenset({"A", "D", "E", "F"}), (
        f"权限面的 G 出边被改了：{sorted(C.ALLOWED_EDGES['G'])}")
    assert "B" not in C.ALLOWED_EDGES["G"], (
        "G → B 被加进了边表 —— 这一批只许改文案，那条边不在裁定的射程里")

    text = _render_g()
    bullets = {m.group(1) for m in (_PARTNER_BULLET.match(line) for line in text.splitlines())
               if m}
    assert bullets == {"A", "D", "E", "F"}, f"提示词里的伙伴条目变了：{sorted(bullets)}"


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
