# -*- coding: utf-8 -*-
"""判据：M 的 policy 里不再把 `M→V` 说成"你的出边"，但"派 D 去核 / 由 D 让 F 补签"必须留着。
## 为什么这道判据存在
`specs/m.py::SPEC.brief.policy` 是逐字进提示词的东西（`agent_prompts.ROLE_BRIEFS`只是它的视图，`specs/` 是唯一真身）⇒ 政策里写错一句权限事实，模型就照着它派活。
2026-10-20 业主裁定撤掉 `M→V`（现 `M.edges = ('A','B','C','D','E','G','H')`，边总数 32），而 policy 第 2 条里逐字留着改前的措辞：
> `M→V` 那条边也在你的出边里（`ALLOWED_EDGES['M']` 里已有 V，`M→B→V` 仍可走）
这句今天是假话：`"V" not in ALLOWED_EDGES["M"]`，端到端派 V 判 `forbidden_edge`（边表那一侧由
`tests/test_v_signing_belongs_to_b_e_f.py` 与 `tests/test_policy.py` 守）。它比"少写一句"更坏：假陈述让主控反复去撞一条不存在的边，撞完还不知道该换哪条路
——而 `forbidden_edge` 的正确读法是"换链"，前提是提示词里那条真的存在的链还在。
## 四条，缺一条就会被"改一半"混过去
- ① 删干净：policy 里不再出现那三种写法（`M→V` / `ALLOWED_EDGES['M']` / `出边里已有`），也不再出现"B 与 V 你可以直接派"这个权限断言 —— B 那一半是真的，V 那一半是假的（M
的七条出边里没有 V），整句留着就还是在说"你能派 V"。- ② 反真空：义务转交的两句必须还在（`派 … D 去核`、`由 D 让 F 补签`），`B 你可以直接派` 也还在 —— 否则"删掉假陈述"可以退化成"整段删掉"，
而业主说的是"这条义务挪给 D"，不是"取消"。- ③ `M→B→V` 要写成"经 B 的路"：这条路今天仍可达（现读 `M.edges` 含 B、`B.edges` 含 V），所以留住 —— 但必须写成两跳，不许读成"我直连
V"。- ④ 负控：① 的三种写法各自加回 ⇒ 红；整段删掉 ⇒ 红；把 `M→B→V` 说成直连 ⇒ 红；把 `B→V` 从边表里摘掉（那句话就成了假话）⇒ 红。
## 为什么不扫文件文本
`specs/m.py` 里那两段 2026-10-18 / 2026-10-20 的裁定注释必须可以写 `M→V`（它们是历史读数与撤边记录，注释不进提示词）。
所以和`test_v_signing_belongs_to_b_e_f.py::_prove_walk_obligations` 同一条纪律：这里只看声明（`brief.policy`），不看源码文本 ——
否则一句正确修复会被历史注释钉红。
"""
from __future__ import annotations

import re

from agentflow.specs import builtin_specs

#: 改前那句假陈述的可扫写法（任何一种命中 ⇒ "边在你的出边里"这类权限事实还在）。
#: `M→B→V` 不含 `M→V`，所以保留那条两跳路不会被误判（③ 单独判它怎么写）。
_FALSE_CLAIM_MARKERS = (
    "M→V",                  # 直连那条边
    "ALLOWED_EDGES['M']",   # 拿派生表当"你的出边里有 V"的依据
    "出边里已有",            # "…里已有 V"
    "那条边也在你的出边里",   # 同一句的口语形态
)

#: 改前那个权限断言的抬头：B 那一半真、V 那一半假 ⇒ 整句都不许再出现。
_FALSE_HEADER = "B 与 V 你可以直接派"

#: 强调符号与空白：`派 **D** 去核` 与 `派 D 去核` 是同一句话（反真空按"读出来的意思"判）。
_EMPHASIS = re.compile(r"[\s*`]+")


def _flat(text: str) -> str:
    """去掉强调符号与所有空白 —— 判"读到的意思"，不判排版。"""
    return _EMPHASIS.sub("", text)


# ============================================================ ① 假陈述必须删干净

def _false_claim_problems(policy) -> list[str]:
    """policy 里"边在你的出边里"这类假权限陈述的全部命中（空列表 = 一句都没有）。"""
    out: list[str] = []
    for i, item in enumerate(policy):
        text = str(item)
        hits = [m for m in _FALSE_CLAIM_MARKERS if m in text]
        if hits:
            out.append(
                f"policy[{i}] 还写着「{hits[0]}」这类**权限事实** —— M 没有到 V 的边"
                f"（2026-10-20 裁定：`V not in ALLOWED_EDGES['M']`，派 V 判 `forbidden_edge`）；"
                f"原文：{text[:200]}")
        if _FALSE_HEADER in text:
            out.append(
                f"policy[{i}] 还写着「{_FALSE_HEADER}」 —— V 那一半是假的"
                f"（M 的七条出边 A/B/C/D/E/G/H 里没有 V）；B 那一半要留，V 那一半要删。"
                f"原文：{text[:200]}")
    return out


def test_m_policy_no_longer_claims_an_edge_to_v() -> None:
    """① 正控：M 的 policy 里没有 `M→V` / `ALLOWED_EDGES['M']` / `出边里已有` / 那句抬头。"""
    policy = builtin_specs()["M"].brief.policy
    bad = _false_claim_problems(policy)
    assert bad == [], ("M 的 policy 里还有『边在我的出边里』这类假陈述（它逐字进提示词，模型会照着派 V）：\n  - "
                       + "\n  - ".join(bad))


def test_negative_control_the_old_sentence_is_caught_when_put_back() -> None:
    """① 负控：把那句假陈述逐字加回 ⇒ 判据必须红（三种写法各自都要单独咬得住）。"""
    policy = builtin_specs()["M"].brief.policy
    assert _false_claim_problems(policy) == [], "夹具前提：真身上这句话已经删掉了"
    # (a) 改前那一整句（逐字）
    old = ("`M→V` 那条边也在你的出边里（`ALLOWED_EDGES['M']` 里已有 V，`M→B→V` 仍可走），")
    got = _false_claim_problems((*policy, old))
    assert any("M→V" in p for p in got), got
    # (b) 只留"派生表里已有 V"那一半（换个说法也照样是假权限陈述）
    got = _false_claim_problems((*policy, "你的出边见 `ALLOWED_EDGES['M']`，里面已有 V。"))
    assert got, "把『ALLOWED_EDGES[M] 里已有 V』加回去之后判据居然绿了"
    # (c) 只留抬头那一句（"B 与 V 你可以直接派"）
    got = _false_claim_problems((*policy, "**B 与 V 你可以直接派**。"))
    assert any(_FALSE_HEADER in p for p in got), got
    # 收尾（负控的负控）：原样的 policy 必须重新成立
    assert _false_claim_problems(policy) == []


# ============================================================ ② 义务转交的两句不许被"整段删掉"

#: 缺签现场的两条处置（按"读出来的意思"判：2026-11-02 的责任路由）。
_ASSIGNED = ("命题已在册而缺V签", "让B处理", "经D让F先拿V签")

#: 仍然成立、不许被顺手删掉的三句（B 的直接边没撤；M 的两条义务都是"没有"）。
_STILL_TRUE = ("B你可以直接派", "证明走查不由你派",
               "没有V签的编辑权", "获取V签的义务")


def _handover_problems(policy) -> list[str]:
    """policy 里"义务已转交 D"这几句的缺失（空列表 = 都在）。"""
    text = _flat("\n".join(str(s) for s in policy))
    return [f"读不到「{needle}」—— 删假陈述不许连真陈述一起删（业主：义务**挪给 D**，不是取消）"
            for needle in (*_ASSIGNED, *_STILL_TRUE) if needle not in text]


def test_the_handover_sentences_are_still_readable() -> None:
    """② 正控（反真空）：缺签现场的两条处置 + `B 你可以直接派` + 两条"没有"都还读得到。"""
    policy = builtin_specs()["M"].brief.policy
    missing = _handover_problems(policy)
    assert missing == [], "M 的 policy 里读不到责任路由那几句：\n  - " + "\n  - ".join(missing)


def test_negative_control_dropping_the_whole_paragraph_is_caught() -> None:
    """② 负控：把整段删掉（"没有假陈述"用"什么都不说"来满足）⇒ 判据必须红。"""
    policy = builtin_specs()["M"].brief.policy
    dropped = tuple(s for s in policy if "证明走查不由你派" not in str(s))
    assert dropped != tuple(policy), "夹具前提：policy 里真有一段写着「证明走查不由你派」"
    assert _handover_problems(dropped) != [], (
        "整段删掉之后判据仍然绿 ⇒ 反真空没有咬合力："
        "「删掉≠转交」，B 那边接不到就没有人办")
    # (b) 把"在册缺签让 B 处理"改回"让 F 补签"（把 B 侧问题推给 F）⇒ 也必须红
    regressed = tuple(str(s).replace("让 **B** 处理", "让 F 补签") for s in policy)
    assert regressed != tuple(str(s) for s in policy), "夹具前提：policy 里真有『让 **B** 处理』"
    assert _handover_problems(regressed) != [], (
        "把『让 B 处理』改回『让 F 补签』之后判据居然绿了")
    # 收尾（负控的负控）
    assert _handover_problems(policy) == []


# ============================================================ ③ 代唤 V 那条两跳路必须退场

#: 2026-11-02 收口之后不许再出现的两种写法。
_RETIRED_ROUTE = ("M→B→V", "经 B 走那条路")


def _retired_route_problems(policy) -> list[str]:
    """policy 里还写着"经 B 代唤 V"的命中（空列表 = 已退场）。"""
    text = "\n".join(str(s) for s in policy)
    return [f"policy 里还写着「{needle}」—— 业主 2026-11-02 收口：M 没有 V 签的编辑权、"
            f"也没有获取义务，不需要经 B 代唤 V" for needle in _RETIRED_ROUTE if needle in text]


def test_the_two_hop_route_is_retired_from_the_policy() -> None:
    """③ 正控：代唤那条路已经退场，而"两条都没有"那句还在。"""
    policy = builtin_specs()["M"].brief.policy
    assert _retired_route_problems(policy) == [], _retired_route_problems(policy)
    flat = _flat("\n".join(str(s) for s in policy))
    assert "没有V签的编辑权" in flat and "获取V签的义务" in flat, flat[-800:]


def test_negative_control_putting_the_two_hop_route_back_is_caught() -> None:
    """③ 负控：把 `M→B→V` 那条代唤路加回 policy ⇒ 判据必须红。"""
    policy = builtin_specs()["M"].brief.policy
    got = _retired_route_problems((*policy, "要靠 V 签字就走 `M→B→V` 那条路。"))
    assert got, "把代唤那条路加回去之后判据居然绿了"
    assert _retired_route_problems(policy) == []
