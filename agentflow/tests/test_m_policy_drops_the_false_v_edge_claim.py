# -*- coding: utf-8 -*-
"""判据：M 的 policy 里不再把 `M→V` 说成"你的出边"，但"派 D 去核 / 由 D 让 F 补签"必须留着。
## 为什么这道判据存在
`specs/m.py::SPEC.brief.policy` 是逐字进提示词的东西（`agent_prompts.ROLE_BRIEFS`只是它的视图，`specs/` 是唯一真身）⇒ 政策里写错一句权限事实，模型就照着它派活。
2026-10-20 业主裁定撤掉 `M→V`（现 `M.edges = ('A','B','C','D','E','G','H')`，边总数 32），而 policy 第 2 条里逐字留着改前的措辞：
> `M→V` 那条边也在你的出边里（`ALLOWED_EDGES['M']` 里已有 V，`M→B→V` 仍可走）
这句今天是假话：`"V" not in ALLOWED_EDGES["M"]`，端到端派 V 判 `forbidden_edge`（边表那一侧由
`tests/test_v_signing_belongs_to_f_and_b.py` 与 `tests/test_policy.py` 守）。它比"少写一句"更坏：假陈述让主控反复去撞一条不存在的边，撞完还不知道该换哪条路
——而 `forbidden_edge` 的正确读法是"换链"，前提是提示词里那条真的存在的链还在。
## 四条，缺一条就会被"改一半"混过去
- ① 删干净：policy 里不再出现那三种写法（`M→V` / `ALLOWED_EDGES['M']` / `出边里已有`），也不再出现"B 与 V 你可以直接派"这个权限断言 —— B 那一半是真的，V 那一半是假的（M
的七条出边里没有 V），整句留着就还是在说"你能派 V"。- ② 反真空：义务转交的两句必须还在（`派 … D 去核`、`由 D 让 F 补签`），`B 你可以直接派` 也还在 —— 否则"删掉假陈述"可以退化成"整段删掉"，
而业主说的是"这条义务挪给 D"，不是"取消"。- ③ `M→B→V` 要写成"经 B 的路"：这条路今天仍可达（现读 `M.edges` 含 B、`B.edges` 含 V），所以留住 —— 但必须写成两跳，不许读成"我直连
V"。- ④ 负控：① 的三种写法各自加回 ⇒ 红；整段删掉 ⇒ 红；把 `M→B→V` 说成直连 ⇒ 红；把 `B→V` 从边表里摘掉（那句话就成了假话）⇒ 红。
## 为什么不扫文件文本
`specs/m.py` 里那两段 2026-10-18 / 2026-10-20 的裁定注释必须可以写 `M→V`（它们是历史读数与撤边记录，注释不进提示词）。
所以和`test_v_signing_belongs_to_f_and_b.py::_prove_walk_obligations` 同一条纪律：这里只看声明（`brief.policy`），不看源码文本 ——
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

#: `M→B→V` 这条两跳路（③ 认的字面）。
_TWO_HOP = "M→B→V"

#: "这不是直连"的各种写法（③ 要求其中至少一种出现）。
_NOT_DIRECT = ("不是直连", "不是你直连", "并非直连")


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

#: 义务转交的两句（按"读出来的意思"判：`派 **D** 去核` 也算命中）。
_ASSIGNED = ("派D去核", "由D让F补签")

#: 仍然成立、不许被顺手删掉的一句（B 的直接边没撤）。
_STILL_TRUE = ("B你可以直接派", "证明走查不由你派")


def _handover_problems(policy) -> list[str]:
    """policy 里"义务已转交 D"这几句的缺失（空列表 = 都在）。"""
    text = _flat("\n".join(str(s) for s in policy))
    return [f"读不到「{needle}」—— 删假陈述不许连真陈述一起删（业主：义务**挪给 D**，不是取消）"
            for needle in (*_ASSIGNED, *_STILL_TRUE) if needle not in text]


def test_the_handover_sentences_are_still_readable() -> None:
    """② 正控（反真空）：`派 D 去核` / `由 D 让 F 补签` / `B 你可以直接派` 都还读得到。"""
    policy = builtin_specs()["M"].brief.policy
    missing = _handover_problems(policy)
    assert missing == [], "M 的 policy 里读不到义务转交那几句：\n  - " + "\n  - ".join(missing)


def test_negative_control_dropping_the_whole_paragraph_is_caught() -> None:
    """② 负控：把整段删掉（"没有假陈述"用"什么都不说"来满足）⇒ 判据必须红。"""
    policy = builtin_specs()["M"].brief.policy
    dropped = tuple(s for s in policy if "证明走查不由你派" not in str(s))
    assert dropped != tuple(policy), "夹具前提：policy 里真有一段写着「证明走查不由你派」"
    assert _handover_problems(dropped) != [], (
        "整段删掉之后判据仍然绿 ⇒ 反真空没有咬合力："
        "「删掉≠转交」，D 那边接不到就没有人办")
    # (b) 把"让 F 补签"改回"让 V 补签"（换成 D 自己去派 V 的旧口径）⇒ 也必须红
    regressed = tuple(str(s).replace("由 D 让 F 补签", "由 D 自己去派 V") for s in policy)
    assert _handover_problems(regressed) != [], "把『由 D 让 F 补签』改回『D 自己去派 V』之后判据居然绿了"
    # 收尾（负控的负控）
    assert _handover_problems(policy) == []


# ============================================================ ③ `M→B→V` 必须写成"经 B 的两跳路"

def _two_hop_problems(policy, m_edges, b_edges) -> list[str]:
    """提示词里 `M→B→V` 那句话的问题（空列表 = 要么没提、要么写成经 B 的两跳路）。

    两个面一起判，因为它们坏起来是两件事：

    - 数据面：这条路得真的还通（`B ∈ M.edges`、`V ∈ B.edges`）—— 边被撤了而提示词
      还点着它，就是换了个方向说同一句假话；
    - 文字面：必须写明"经 B"且"不是你直连 V"—— 只写 `M→B→V` 三个字母，
      读的人（尤其模型）会把它当成"到 V 的一条路"的另一种写法，与旧直连句分不开。
    """
    text = "\n".join(str(s) for s in policy)
    if _TWO_HOP not in text:
        return []
    out: list[str] = []
    if "B" not in set(m_edges):
        out.append(f"提示词点着 {_TWO_HOP}，但 M 的出边 {tuple(m_edges)} 里没有 B ⇒ 这条路第一步就走不动")
    if "V" not in set(b_edges):
        out.append(f"提示词点着 {_TWO_HOP}，但 B 的出边 {tuple(b_edges)} 里没有 V ⇒ 这条路第二步就走不动")
    flat = _flat(text)
    if "经B" not in flat:
        out.append(f"点了 {_TWO_HOP} 却没写「经 B」⇒ 会被读成一条直连边的别名（这正是 2026-10-20 撤掉的那条边）")
    if not any(needle in flat for needle in _NOT_DIRECT):
        out.append(f"点了 {_TWO_HOP} 却没写明「不是你直连 V」⇒ 一句话里两种读法，模型会挑省事的那种")
    return out


def test_the_two_hop_route_is_described_as_going_through_b() -> None:
    """③ 正控：`M→B→V` 仍在，且写明是经 B 的两跳路、不是 M 直连 V（边表现读核可达）。"""
    specs = builtin_specs()
    policy = specs["M"].brief.policy
    problems = _two_hop_problems(policy, specs["M"].edges, specs["B"].edges)
    assert problems == [], "`M→B→V` 那句话与边表对不上：\n  - " + "\n  - ".join(problems)
    # 反真空：这一条真的验到了东西（不是"提示词里干脆没提这件事"）
    assert _TWO_HOP in "\n".join(str(s) for s in policy), (
        "policy 里读不到 `M→B→V` ⇒ ③ 这一整条退化成空转；而这条路今天仍可达"
        "（M.edges 含 B、B.edges 含 V），不该被顺手删掉")


def test_negative_control_calling_the_two_hop_route_direct_is_caught() -> None:
    """③ 负控：把 `M→B→V` 说成直连、或让那条路的第二步不存在 ⇒ 判据必须红。"""
    specs = builtin_specs()
    m_edges, b_edges = specs["M"].edges, specs["B"].edges
    base = ["先窄后宽：派 `D` 立题。"]  # 一个干净的起点（不含这条路，也不含义务句）
    # (a) 说成直连：只留三个字母，不写"经 B / 不是直连"
    got = _two_hop_problems((*base, "要靠 V 签字就走 `M→B→V` 那条边。"), m_edges, b_edges)
    assert any("经 B" in p for p in got), got
    assert any("不是你直连" in p for p in got), got
    # (b) 明说成"你直连 V"：`经 B` 写在旁边也救不回来这一句的读法
    got = _two_hop_problems((*base, "`M→B→V` 就是你直连 V 的那条边。"), m_edges, b_edges)
    assert any("不是你直连" in p for p in got), got
    # (c) 数据面：`B→V` 被撤掉（那句就成了假话），文字写得再对也必须红
    got = _two_hop_problems((*base, "这是**经 B** 的两跳路 `M→B→V`，不是你直连 V。"),
                            m_edges, tuple(e for e in b_edges if e != "V"))
    assert any("B 的出边" in p for p in got), got
    # (d) 数据面：`M→B` 被撤掉
    got = _two_hop_problems((*base, "这是**经 B** 的两跳路 `M→B→V`，不是你直连 V。"),
                            tuple(e for e in m_edges if e != "B"), b_edges)
    assert any("M 的出边" in p for p in got), got
    # 收尾（负控的负控）：真身 + 真边表 ⇒ 全对
    assert _two_hop_problems(specs["M"].brief.policy, m_edges, b_edges) == []
