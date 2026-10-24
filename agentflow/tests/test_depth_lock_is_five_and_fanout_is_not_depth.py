"""深度锁 = 链上 5 个代理（台账 4 跳），扇出 = 一个父能挂几个直接子（两根互不换算的轴）。

业主 2026-10-24 原话（唯一权威，逐字）：

    「扇出12的意思是能一个父能有几个子，深度5的意思是假如M-W-X-Y-Z，
      Z就不能再派子代理。」

同日补的两句（父代理转述，逐字）：

    「12是只管直接子，不管隔着几层的子」
    「会造成歧义的变量名改掉」

## 两种数法（差一，两处都要写清，否则读的人还会差一）

- 业主数法 = 链上的代理个数：`M(1) → W(2) → X(3) → Y(4) → Z(5)`，第 5 个（Z）
  不能再派第 6 个。
- 台账数法 = `Task.depth` 是跳数：主控不落任务行，它的直接子 depth = 1
  （`Conductor._depth_of(None)` ⇒ 1）⇒ 链上 5 个代理 = 台账 4 跳。
- 所以 `Policy.max_chain_depth` = 4，换算的唯一落点是 `policy.max_agents_on_chain`
  （跳数 + 1 = 链上代理个数）。

本文件的常量把这两边的数都钉住（`EXPECTED_CHAIN_HOPS` / `EXPECTED_CHAIN_AGENTS`），
判据 7 专门守这个等式；本文件的其余判据按业主数法（第几个代理）叙述，
判定输入一律用 `_hops()` 换成台账跳数 —— 换算式只在这一个函数里出现一次。

## 守的八件事

1. 五层链（`M → A → B → D → F`，五个代理）末端再派活 ⇒ 受控拒绝，理由码仍是现成的
   `depth_exceeded`，报文点名"第 5 个代理""不能再派第 6 个"。
2. 正控：四层链的末端还能再派一层（那一次派出的是第 5 个代理）。
3. 负控：扇出不受深度影响 —— 一个父派 12 个直接子仍允许（默认档 25 / 主控档 100
   一个数都没动），证明两根轴没有被混成一根。
4. 扇出只数直接子：12 个直接子 + 每个子各 12 个孙 ⇒ 允许（不许因为总节点多就判
   超扇出）；再挂第 13 个直接子才拒。
5. 反真空：把链长上限打桩成 12 ⇒ 判据 1 必红。
6. 名字（业主「会造成歧义的变量名改掉」）：链长那一格叫 `max_chain_depth`，
   扇出那一族名字里带 `direct_child`，且注释写明只数直接子。
7. 两种数法一致：`max_chain_depth == 4` 且链上代理个数 == 5（等式 + 行为两条）。
8. 旧名只读兼容：`max_depth` / `max_fanout` 仍可读且值相同（不许一刀切断）。
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from agentflow import policy as P


#: 台账口径（跳数）= `Policy.max_chain_depth` 的值。
EXPECTED_CHAIN_HOPS = 4

#: 业主口径（链上的代理个数）= 跳数 + 1。
EXPECTED_CHAIN_AGENTS = 5

#: 五层链（按业主数法：M 是第 1 个代理）。每一跳都在
#: `capabilities.ALLOWED_EDGES` 里，所以判定一定会走到第 [3] 步链长，
#: 而不是先被越权挡掉（越权优先于深度：`check` 的第 [2] 步）。
CHAIN = ("M", "A", "B", "D", "F")

#: 第 5 个代理（业主原话里的 Z）还能走的那条边：F → E 是允许的边。
Z = CHAIN[-1]
Z_CHILD = "E"


def _hops(agent_no: int) -> int:
    """业主数法（第几个代理）→ 台账跳数。差一的换算式只写这一处。"""
    return agent_no - 1


def _walk(pol: P.Policy, chain: tuple[str, ...] = CHAIN) -> list[tuple[str, str, int, int]]:
    """沿 `chain` 逐个代理判一次（第 2 个起，每个都是"被派出来的那一次"）。

    任何一跳被拒就当场断言失败 —— "链造不起来"与"链长闸门坏了"是两件事，
    混在一起会让负控变成假绿。
    """
    hops: list[tuple[str, str, int, int]] = []
    for agent_no, (frm, to) in enumerate(zip(chain, chain[1:]), start=2):
        r = P.check(pol, P.Decision(frm=frm, to=to, depth=_hops(agent_no)))
        assert r is None, (
            f"{frm} → {to}（第 {agent_no} 个代理 / 台账跳数 {_hops(agent_no)}）"
            f"本该放行，却 {r.reason}：{r.detail}"
        )
        hops.append((frm, to, agent_no, _hops(agent_no)))
    return hops


def _z_dispatch(pol: P.Policy):
    """第 5 个代理（Z）再向下派第 6 个 ⇒ 返回判定结果。"""
    return P.check(pol, P.Decision(frm=Z, to=Z_CHILD, depth=_hops(EXPECTED_CHAIN_AGENTS + 1)))


def _assert_z_cannot_dispatch(pol: P.Policy) -> None:
    """判据 1 的断言体（单独抽出来，好让判据 5 用打桩的 policy 把它判红）。"""
    _walk(pol)
    r = _z_dispatch(pol)
    assert r is not None, (
        f"第 {EXPECTED_CHAIN_AGENTS} 个代理（{Z}）再派 {Z_CHILD} 竟然被放行 —— "
        "链长锁没有封在第 5 个代理"
    )
    assert r.reason == "depth_exceeded", r.detail
    assert r.limit == "max_chain_depth", r.limit
    # 报文按业主的数法点明，同时给出台账读数 —— 只写一种会让读的人再差一
    assert "第 5 个代理" in r.detail, r.detail
    assert "不能再派第 6 个" in r.detail, r.detail
    assert "max_chain_depth=4" in r.detail, r.detail
    assert "结构闸门" in r.detail, r.detail


# ---------------------------------------------------------------- 判据 1


def test_five_agents_work_then_the_fifth_cannot_dispatch_a_sixth():
    """判据 1：`M → A → B → D → F` 五个代理都能干活，F（Z）再派活 ⇒ `depth_exceeded`。"""
    _assert_z_cannot_dispatch(P.Policy())


# ---------------------------------------------------------------- 判据 2


def test_a_four_agent_chain_can_still_dispatch_the_fifth():
    """判据 2（正控）：四层链的末端还能派一次 —— 派出来的正是第 5 个代理。"""
    pol = P.Policy()
    assert pol.max_chain_depth == EXPECTED_CHAIN_HOPS, pol.to_dict()
    four = CHAIN[:-1]                      # M → A → B → D（第 4 个代理是 D）
    _walk(pol, four)
    y, agent_no = four[-1], len(four)
    assert agent_no == 4
    r = P.check(pol, P.Decision(frm=y, to="F", depth=_hops(EXPECTED_CHAIN_AGENTS)))
    assert r is None, (
        f"第 4 个代理（{y}）派第 5 个（台账跳数 {_hops(EXPECTED_CHAIN_AGENTS)}）本该放行，"
        f"却 {r.reason}：{r.detail}"
    )


# ---------------------------------------------------------------- 判据 3


def test_fanout_is_not_the_depth_axis():
    """判据 3（负控）：一个父派 12 个直接子仍允许；两根轴的数字互不影响。"""
    pol = P.Policy()
    # 链长这一格 = 台账 4 跳（改前是 12，这一句就是改前红的那一刀）
    assert pol.max_chain_depth == EXPECTED_CHAIN_HOPS, pol.to_dict()
    # 扇出这一族一个数都没动：默认档 25，主控一档 100
    assert pol.max_direct_children == 25, pol.to_dict()
    assert P.direct_children_limit_for(pol, "M") == 100
    # 一个工人父（D 是第 4 个代理 / 台账跳数 3）此刻已挂着 12 个直接子，仍允许再派
    r = P.check(pol, P.Decision(frm="D", to="A", depth=_hops(4), direct_children=12))
    assert r is None, f"12 个直接子竟然判超扇出：{r.reason}：{r.detail}"


# ---------------------------------------------------------------- 判据 3'


def test_fanout_counts_only_direct_children():
    """判据 3'：12 个直接子 + 每个子各 12 个孙 ⇒ 允许；第 13 个直接子才拒。"""
    # 业主原话里的 12：这里显式把扇出档设成 12（默认档 25 另行验证，不动它）
    pol = P.Policy(max_direct_children=12)

    # 第 12 个直接子：D（第 4 个代理）此刻在手 11 个 ⇒ 放行
    twelfth = P.check(pol, P.Decision(frm="D", to="A", depth=_hops(4), direct_children=11))
    assert twelfth is None, f"第 12 个直接子本该放行，却 {twelfth.reason}：{twelfth.detail}"

    # 孙辈不占父的格：D 的每个子（A，第 5 个代理）各自再挂 12 个直接子
    for _ in range(12):
        r = P.check(pol, P.Decision(frm="A", to="B", depth=_hops(5), direct_children=11))
        assert r is None, f"孙辈的格算到了父头上：{r.reason}：{r.detail}"

    # 父自己的第 13 个直接子才拒（此刻在手 12 个），且报文点明"直接子"
    thirteenth = P.check(pol, P.Decision(frm="D", to="A", depth=_hops(4), direct_children=12))
    assert thirteenth is not None, "第 13 个直接子竟然放行"
    assert thirteenth.reason == "fanout_exceeded", thirteenth.detail
    assert "直接子" in thirteenth.detail, thirteenth.detail

    # 反真空：这棵树一共 1 + 12 + 144 个节点，但总数不是扇出判据 ——
    # 父自己还差一个直接子时，照样放行
    again = P.check(pol, P.Decision(frm="D", to="A", depth=_hops(4), direct_children=11,
                                    total=1 + 12 + 144))
    assert again is None, f"总数被当成了扇出判据：{again.reason}：{again.detail}"


# ---------------------------------------------------------------- 判据 4


def test_anti_vacuum_stubbing_the_lock_to_twelve_turns_criterion_one_red():
    """判据 4（反真空）：把链长上限打桩成 12 ⇒ 判据 1 必红。"""
    stubbed = dataclasses.replace(P.Policy(), max_chain_depth=12)
    with pytest.raises(AssertionError, match="链长锁没有封在第 5 个代理"):
        _assert_z_cannot_dispatch(stubbed)


# ---------------------------------------------------------------- 判据 5


def test_the_names_that_were_ambiguous_are_gone():
    """判据 5（名字）：链长那一格叫 `max_chain_depth`，旧名不再是真身。"""
    names = {f.name for f in dataclasses.fields(P.Policy)}
    assert "max_chain_depth" in names, sorted(names)
    assert "max_depth" not in names, sorted(names)
    # 扇出那一族：名字里带 direct_child，且注释写明"只数直接子"
    assert "max_direct_children" in names, sorted(names)
    assert hasattr(P, "DIRECT_CHILDREN_LIMIT_BY_ROLE")
    assert hasattr(P, "direct_children_limit_for")
    src = inspect.getsource(P)
    assert "只数直接子" in src
    assert "不管隔着几层的子" in src
    assert "Z就不能再派子代理" in src
    assert "台账数法" in src and "业主数法" in src


# ---------------------------------------------------------------- 判据 6


def test_the_old_names_still_read_the_same_numbers():
    """判据 6（兼容）：`max_depth` / `max_fanout` 仍可读且值相同；拒绝理由码不改。"""
    pol = P.Policy()
    assert pol.max_depth == pol.max_chain_depth == EXPECTED_CHAIN_HOPS
    assert pol.max_fanout == pol.max_direct_children == 25
    assert P.FANOUT_LIMIT_BY_ROLE is P.DIRECT_CHILDREN_LIMIT_BY_ROLE
    assert P.fanout_limit_for(pol, "A") == P.direct_children_limit_for(pol, "A") == 25
    # 对外口径（schema 里登记着的理由码）不许跟着改名
    from agentflow import schema as S

    assert "depth_exceeded" in S.REFUSAL_REASONS
    assert "fanout_exceeded" in S.REFUSAL_REASONS


# ---------------------------------------------------------------- 判据 7


def test_the_two_countings_agree_and_cannot_drift():
    """判据 7：两种数法一致 —— 台账 4 跳 == 链上 5 个代理（等式 + 行为两条）。

    这一条专防"以后又差一"：把 `max_chain_depth` 单独改成别的数，
    等式那一半先红；把 `max_agents_on_chain` 的 +1 改掉，等式也红。
    """
    pol = P.Policy()
    assert EXPECTED_CHAIN_HOPS + 1 == EXPECTED_CHAIN_AGENTS == 5
    assert pol.max_chain_depth == EXPECTED_CHAIN_HOPS == 4
    assert P.max_agents_on_chain(pol) == EXPECTED_CHAIN_AGENTS == 5

    # 行为面：第 5 个代理（Z）能被派出来 —— 也就是"它自己是允许存在的" …
    _walk(pol)
    # … 而它再派第 6 个就被拒（两边的数各管一头）
    r = _z_dispatch(pol)
    assert r is not None and r.reason == "depth_exceeded", r.detail

    # 反真空：只动一边 ⇒ 等式红（这里直接把两边拆开验，不靠人记得）
    drifted = dataclasses.replace(pol, max_chain_depth=EXPECTED_CHAIN_HOPS + 1)
    assert P.max_agents_on_chain(drifted) == EXPECTED_CHAIN_AGENTS + 1 != EXPECTED_CHAIN_AGENTS
