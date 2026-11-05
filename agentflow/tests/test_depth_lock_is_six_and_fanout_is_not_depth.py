"""深度锁 = 链上 7 个代理（台账 6 跳），扇出 = 一个父能挂几个直接子（两根互不换算的轴）。

业主 2026-10-24 原话（数法，逐字，至今有效）：

    「扇出12的意思是能一个父能有几个子，深度5的意思是假如M-W-X-Y-Z，
      Z就不能再派子代理。」

业主 2026-11-05 裁定（值，逐字）：

    「将深度锁调到6，不然 M->D->F->A->B->V 是做不到的（F派A补文献，A派B录入，
      B派V拿V签）」

同日还有两句（父代理转述，逐字）：

    「12是只管直接子，不管隔着几层的子」
    「会造成歧义的变量名改掉」

## 两种数法（差一，两处都要写清，否则读的人还会差一）

- 业主数法 = 链上的代理个数：`M(1) → W(2) → X(3) → Y(4) → Z(5) → …(7)`，
  第 7 个之后不能再派第 8 个（2026-11-05 之前是第 5 个之后不能再派第 6 个）。
- 台账数法 = `Task.depth` 是跳数：主控不落任务行，它的直接子 depth = 1
  （`Conductor._depth_of(None)` ⇒ 1）⇒ 链上 7 个代理 = 台账 6 跳。
- 所以 `Policy.max_chain_depth` = 6，换算的唯一落点是 `policy.max_agents_on_chain`
  （跳数 + 1 = 链上代理个数）。
- 等式（判据 10 守它）：`max_chain_depth = N` ⇒ 台账 depth 1..N 放行
  （= 链上 N+1 个代理），depth = N+1 被 `depth_exceeded` 拒。取 6 就是"链上 7 个代理"。

本文件的常量把这两边的数都钉住（`EXPECTED_CHAIN_HOPS` / `EXPECTED_CHAIN_AGENTS`），
其余判据按业主数法（第几个代理）叙述，判定输入一律用 `_hops()` 换成台账跳数 ——
换算式只在这一个函数里出现一次。

## 守的十一条

1. 业主点名的那条链（`M → D → F → A → B → V`，6 个代理，台账 depth 1..5）每一跳都
   放行 —— V 落在台账 depth 5，旧值 4 够不着它。双证：带审稿人豁免放行 +
   摘掉豁免（`reviewer_roles=frozenset()`）也放行 ⇒ 它今天是被深度放行的，
   不是靠 2026-11-02 那条豁免（那是另一根轴，本文件不动它）。
2. 第 7 个代理仍可被派：`M → G → D → F → A → B → H`（7 个代理，台账 depth 1..6）
   每一跳都放行；H（第 7 个，depth 6）再派第 8 个（depth 7）⇒ `depth_exceeded`，
   报文点名"第 7 个代理""不能再派第 8 个"。
3. 负控：扇出不受深度影响 —— 一个父派 12 个直接子仍允许（默认档 25 / 主控档 100
   一个数都没动），证明两根轴没有被混成一根。
4. 扇出只数直接子：12 个直接子 + 每个子各 12 个孙 ⇒ 允许（不许因为总节点多就判
   超扇出）；再挂第 13 个直接子才拒。
5. 反真空（深度轴）：把 `max_chain_depth` 打桩成 12 ⇒ 判据 2 必红。
6. 反真空（扇出轴，另一条判据）：把扇出档放宽 ⇒ 判据 3 的读数红，而深度判据仍绿
   —— 两根轴各红各的，一起放宽不会互相掩护。
7. 反真空（旧值 4）：`lock=4 + 摘豁免` ⇒ 判据 1 的 V 那一跳立刻被拒（深度轴单独量它）。
8. 名字（业主「会造成歧义的变量名改掉」）：链长那一格叫 `max_chain_depth`，
   扇出那一族名字里带 `direct_child`，且注释写明只数直接子。
9. 旧名只读兼容：`max_depth` / `max_fanout` 仍可读且值相同（不许一刀切断）。
10. 两种数法一致：`max_chain_depth == 6` 且链上代理个数 == 7（等式 + 行为两条）。
11. 端到端（真 `Conductor`，两格）：判据 1/2 的读数在台账上逐跳复现；
    且判据 1 的 V 那一跳在 `reviewer_roles` 被摘掉之后仍然 ok。

> 文件名里的 "six" 是台账口径（`Policy.max_chain_depth`）；业主口径是"链上七个代理"。
> 两个数都在判据 10 里钉着 —— 文件名只许对上一个，等式负责把另一个也说清。
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any

import pytest

from agentflow import policy as P
from agentflow.conductor import Conductor
from agentflow.store import Store


#: 台账口径（跳数）= `Policy.max_chain_depth` 的值。
EXPECTED_CHAIN_HOPS = 6

#: 业主口径（链上的代理个数）= 跳数 + 1。
EXPECTED_CHAIN_AGENTS = 7

#: 业主 2026-11-05 点名的链（6 个代理 = 台账 depth 1..5）。
#: 每一跳都在 `capabilities.ALLOWED_EDGES` 里，所以判定会走到第 [3] 步链长，
#: 而不是先被越权挡掉（越权优先于深度：`check` 的第 [2] 步）。
#: V 落在台账 depth 5（链上第 6 个代理）—— 旧值 4 够不着的那一格。
OWNER_CHAIN = ("M", "D", "F", "A", "B", "V")

#: 判据 2 的链：7 个代理（台账 depth 1..6），末端 H 还不能派第 8 个。
#: 2026-11-05 起 V 没有出边，所以这一条不能用 V 收尾（那样会先撞 `forbidden_edge`，
#: 拒因就不是深度了）—— 换成 H（出边 A / E / G 仍在）。
BOUNDARY_CHAIN = ("M", "G", "D", "F", "A", "B", "H")

#: 第 7 个代理（BOUNDARY_CHAIN 的末端）还能走的那条边：H → A 是允许的边。
Z = BOUNDARY_CHAIN[-1]
Z_CHILD = "A"


def _hops(agent_no: int) -> int:
    """业主数法（第几个代理）→ 台账跳数。差一的换算式只写这一处。"""
    return agent_no - 1


def _walk(pol: P.Policy, chain: tuple[str, ...] = BOUNDARY_CHAIN
          ) -> list[tuple[str, str, int, int]]:
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
    """第 7 个代理（Z）再向下派第 8 个 ⇒ 返回判定结果。"""
    return P.check(pol, P.Decision(frm=Z, to=Z_CHILD, depth=_hops(EXPECTED_CHAIN_AGENTS + 1)))


def _assert_z_cannot_dispatch(pol: P.Policy) -> None:
    """判据 2 的断言体（单独抽出来，好让判据 5 用打桩的 policy 把它判红）。"""
    _walk(pol)
    r = _z_dispatch(pol)
    assert r is not None, (
        f"第 {EXPECTED_CHAIN_AGENTS} 个代理（{Z}）再派 {Z_CHILD} 竟然被放行 —— "
        f"链长锁没有封在第 {EXPECTED_CHAIN_AGENTS} 个代理"
    )
    assert r.reason == "depth_exceeded", r.detail
    assert r.limit == "max_chain_depth", r.limit
    # 报文按业主的数法点明，同时给出台账读数 —— 只写一种会让读的人再差一
    assert f"第 {EXPECTED_CHAIN_AGENTS} 个代理" in r.detail, r.detail
    assert f"不能再派第 {EXPECTED_CHAIN_AGENTS + 1} 个" in r.detail, r.detail
    assert f"max_chain_depth={EXPECTED_CHAIN_HOPS}" in r.detail, r.detail
    assert "结构闸门" in r.detail, r.detail


def _v_hop(pol: P.Policy):
    """业主链的最后那一跳：B（depth 4）派 V（本次 depth 5）。"""
    return P.check(pol, P.Decision(frm="B", to="V", depth=_hops(len(OWNER_CHAIN))))


# ---------------------------------------------------------------- 判据 1


def test_the_owner_named_chain_works_and_v_is_now_let_through_by_depth():
    """判据 1：`M → D → F → A → B → V` 六个代理全通；V 那一跳由深度放行。

    旧的 4 跳锁够不着 V（台账 depth 5）—— 那时它只能靠 `reviewer_roles` 那条豁免
    过去。所以这里双证：带豁免放行 + 摘掉豁免也放行。
    """
    pol = P.Policy()
    hops = _walk(pol, OWNER_CHAIN)
    assert [h[2] for h in hops] == [2, 3, 4, 5, 6], hops      # 第 2..6 个代理
    assert [h[3] for h in hops] == [1, 2, 3, 4, 5], hops      # 对应台账 depth 1..5
    assert hops[-1] == ("B", "V", 6, 5), hops                 # V = 第 6 个代理 / depth 5

    # ① 带豁免（默认档）：放行
    assert _v_hop(pol) is None
    # ② 摘掉豁免（`reviewer_roles` 一个都不免）：仍然放行 ⇒ 它是被深度放行的，
    #    不是靠 2026-11-02 那条"审稿人不占链"的豁免。这条是判据的重点：
    #    只要有人把这一格改回 4，②马上变成 `depth_exceeded`（见判据 7）。
    stripped = dataclasses.replace(pol, reviewer_roles=frozenset())
    assert _v_hop(stripped) is None, (
        f"摘掉审稿人豁免之后 V（depth {_hops(len(OWNER_CHAIN))}）被拒了 —— "
        "业主 2026-11-05 的「M->D->F->A->B->V」靠的是深度这一格，不是豁免"
    )


# ---------------------------------------------------------------- 判据 2


def test_seven_agents_work_then_the_seventh_cannot_dispatch_an_eighth():
    """判据 2：7 个代理都能干活（depth 1..6），第 7 个再派第 8 个 ⇒ `depth_exceeded`。"""
    _assert_z_cannot_dispatch(P.Policy())


# ---------------------------------------------------------------- 判据 3


def test_fanout_is_not_the_depth_axis():
    """判据 3（负控）：一个父派 12 个直接子仍允许；两根轴的数字互不影响。"""
    pol = P.Policy()
    # 链长这一格 = 台账 6 跳（2026-11-05 的裁定；这一句就是"改回 4"会红的那一格）
    assert pol.max_chain_depth == EXPECTED_CHAIN_HOPS, pol.to_dict()
    # 扇出这一族一个数都没动：默认档 25，主控一档 100
    assert pol.max_direct_children == 25, pol.to_dict()
    assert P.direct_children_limit_for(pol, "M") == 100
    # 一个工人父（D 是第 3 个代理 / 台账跳数 2）此刻已挂着 12 个直接子，仍允许再派
    r = P.check(pol, P.Decision(frm="D", to="A", depth=_hops(3), direct_children=12))
    assert r is None, f"12 个直接子竟然判超扇出：{r.reason}：{r.detail}"


# ---------------------------------------------------------------- 判据 4


def _assert_fanout_boundary(pol: P.Policy, *, limit: int) -> None:
    """判据 4 的断言体：`limit` 是这个测试档的扇出上限（不写死 12，由调用方给）。"""
    # 第 limit 个直接子：D 此刻在手 limit-1 个 ⇒ 放行
    last = P.check(pol, P.Decision(frm="D", to="A", depth=_hops(3),
                                   direct_children=limit - 1))
    assert last is None, f"第 {limit} 个直接子本该放行，却 {last.reason}：{last.detail}"

    # 孙辈不占父的格：D 的每个子（A，第 5 个代理）各自再挂 limit 个直接子
    for _ in range(limit):
        r = P.check(pol, P.Decision(frm="A", to="B", depth=_hops(5),
                                    direct_children=limit - 1))
        assert r is None, f"孙辈的格算到了父头上：{r.reason}：{r.detail}"

    # 父自己的第 limit+1 个直接子才拒（此刻在手 limit 个），且报文点明"直接子"
    over = P.check(pol, P.Decision(frm="D", to="A", depth=_hops(3),
                                   direct_children=limit))
    assert over is not None, f"第 {limit + 1} 个直接子竟然放行（扇出上限没起作用）"
    assert over.reason == "fanout_exceeded", over.detail
    assert "直接子" in over.detail, over.detail

    # 反真空：这棵树一共 1 + limit + limit*limit 个节点，但总数不是扇出判据 ——
    # 父自己还差一个直接子时，照样放行
    again = P.check(pol, P.Decision(frm="D", to="A", depth=_hops(3),
                                    direct_children=limit - 1,
                                    total=1 + limit + limit * limit))
    assert again is None, f"总数被当成了扇出判据：{again.reason}：{again.detail}"


def test_fanout_counts_only_direct_children():
    """判据 4：12 个直接子 + 每个子各 12 个孙 ⇒ 允许；第 13 个直接子才拒。

    这里显式把扇出档设成 12（业主原话里那个数）；默认档 25 另行验证，不动它。
    """
    _assert_fanout_boundary(P.Policy(max_direct_children=12), limit=12)


# ---------------------------------------------------------------- 判据 5


def test_anti_vacuum_stubbing_the_lock_to_twelve_turns_criterion_two_red():
    """判据 5（反真空·深度轴）：把链长上限打桩成 12 ⇒ 判据 2 必红。"""
    stubbed = dataclasses.replace(P.Policy(), max_chain_depth=12)
    with pytest.raises(AssertionError, match="链长锁没有封在第 7 个代理"):
        _assert_z_cannot_dispatch(stubbed)


# ---------------------------------------------------------------- 判据 6


def test_anti_vacuum_widening_the_fanout_axis_reds_its_own_criterion_only():
    """判据 6（反真空·扇出轴）：放宽扇出档 ⇒ 判据 3 的读数红，而深度判据仍绿。

    "把扇出上限也一起放宽"是这类改动最常见的搭便车形态：深度 4 → 6 时顺手把 25 也
    改大，谁也不会红。所以扇出那一根轴自己得有判据（判据 3 的 `== 25` / `== 100`
    与判据 4 的边界），而且必须证明它不是在靠深度那一格亮绿。
    """
    wide = dataclasses.replace(P.Policy(), max_direct_children=999)
    # 判据 3 的读数会红（默认档不再是 25）
    assert wide.max_direct_children == 999 != 25
    assert P.direct_children_limit_for(wide, "D") == 999
    # 而深度那两条判据对这个改动完全不敏感：链照走、第 8 个照拒
    _walk(wide, OWNER_CHAIN)
    _assert_z_cannot_dispatch(wide)
    # 反过来：只动深度也不许影响扇出档
    deeper = dataclasses.replace(P.Policy(), max_chain_depth=12)
    assert P.direct_children_limit_for(deeper, "D") == 25
    assert deeper.max_direct_children == 25


# ---------------------------------------------------------------- 判据 7


def test_anti_vacuum_reverting_to_four_refuses_the_v_hop_by_depth():
    """判据 7（反真空·旧值）：`lock=4 + 摘豁免` ⇒ 判据 1 的 V 那一跳立刻被拒。

    为什么必须同时摘豁免：`reviewer_roles`（业主 2026-11-02 裁定）让"目标是审稿人"
    时跳过链长闸 ⇒ 光把数改回 4，V 仍然过得去。那不是深度这一轴的读数。所以反真空
    落在"深度轴单独量"的那一档：4 + 摘豁免 ⇒ `depth_exceeded`。
    """
    old = dataclasses.replace(P.Policy(), max_chain_depth=4, reviewer_roles=frozenset())
    # 前四跳（第 2..5 个代理，depth 1..4）仍然放行 —— 断在 V 那一跳，不是更早
    _walk(old, OWNER_CHAIN[:-1])
    r = _v_hop(old)
    assert r is not None, "把这一格改回 4（且摘掉豁免）之后 V 竟然还放行 ⇒ 判据 1 不是靠深度"
    assert r.reason == "depth_exceeded", r
    assert r.limit == "max_chain_depth", r.limit
    # 整条链的走法也会红（判据 1 的 `_walk` 断言在 V 那一跳失败）
    with pytest.raises(AssertionError, match="本该放行"):
        _walk(old, OWNER_CHAIN)


# ---------------------------------------------------------------- 判据 8（名字）


def test_the_names_that_were_ambiguous_are_gone():
    """判据 8（名字）：链长那一格叫 `max_chain_depth`，旧名不再是真身。"""
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
    assert "将深度锁调到6" in src
    assert "台账数法" in src and "业主数法" in src


# ---------------------------------------------------------------- 判据 9（兼容）


def test_the_old_names_still_read_the_same_numbers():
    """判据 9：`max_depth` / `max_fanout` 仍可读且值相同；拒绝理由码不改。"""
    pol = P.Policy()
    assert pol.max_depth == pol.max_chain_depth == EXPECTED_CHAIN_HOPS
    assert pol.max_fanout == pol.max_direct_children == 25
    assert P.FANOUT_LIMIT_BY_ROLE is P.DIRECT_CHILDREN_LIMIT_BY_ROLE
    assert P.fanout_limit_for(pol, "A") == P.direct_children_limit_for(pol, "A") == 25
    # 对外口径（schema 里登记着的理由码）不许跟着改名
    from agentflow import schema as S

    assert "depth_exceeded" in S.REFUSAL_REASONS
    assert "fanout_exceeded" in S.REFUSAL_REASONS


# ---------------------------------------------------------------- 判据 10（两种数法）


def test_the_two_countings_agree_and_cannot_drift():
    """判据 10：两种数法一致 —— 台账 6 跳 == 链上 7 个代理（等式 + 行为两条）。

    这一条专防"以后又差一"：把 `max_chain_depth` 单独改成别的数，等式那一半先红；
    把 `max_agents_on_chain` 的 +1 改掉，等式也红。等式本身写在这里与
    `policy.max_agents_on_chain` 的 docstring 里，两处逐字一致。
    """
    pol = P.Policy()
    assert EXPECTED_CHAIN_HOPS + 1 == EXPECTED_CHAIN_AGENTS == 7
    assert pol.max_chain_depth == EXPECTED_CHAIN_HOPS == 6
    assert P.max_agents_on_chain(pol) == EXPECTED_CHAIN_AGENTS == 7

    # 行为面：第 7 个代理能被派出来（"它自己是允许存在的"）…
    _walk(pol)
    # … 而它再派第 8 个就被拒（两边的数各管一头）
    r = _z_dispatch(pol)
    assert r is not None and r.reason == "depth_exceeded", r.detail

    # 反真空：只动一边 ⇒ 等式红（这里直接把两边拆开验，不靠人记得）
    drifted = dataclasses.replace(pol, max_chain_depth=EXPECTED_CHAIN_HOPS + 1)
    assert P.max_agents_on_chain(drifted) == EXPECTED_CHAIN_AGENTS + 1 != EXPECTED_CHAIN_AGENTS


# ---------------------------------------------------------------- 判据 11（端到端）


class _FakeG:
    """G 的替身：`refresh_markdown` 的形参与声明一致（`doc_id` 必填）。"""

    def refresh_markdown(self, doc_id: str) -> dict[str, Any]:
        return {"outcome": "ok", "detail": f"夹具：G.refresh_markdown({doc_id})"}


class _FakeD:
    """D 的替身：`probe_c` 的形参与声明一致（`qid` 必填）。"""

    def probe_c(self, qid: str, qrow: Any = None) -> dict[str, Any]:
        return {"outcome": "ok", "detail": f"夹具：D.probe_c({qid})"}


class _FakeF:
    """F 的替身：`status` 的形参与声明一致（`plan_id` 必填）。"""

    def status(self, plan_id: str) -> dict[str, Any]:
        return {"outcome": "ok", "detail": f"夹具：F.status({plan_id})"}


class _FakeA:
    """A 的替身：`run_once` 不接参数（链上只需要"这一行造得出来"）。"""

    def run_once(self) -> dict[str, Any]:
        return {"outcome": "ok", "detail": "夹具：A 跑完"}


class _FakeB:
    """B 的替身：同上。"""

    def run_once(self) -> dict[str, Any]:
        return {"outcome": "ok", "detail": "夹具：B 跑完"}


class _FakeV:
    """V 的替身：`verify_proof` 的必填形参是空集（声明里 required=[]）。"""

    def verify_proof(self, **kw: Any) -> dict[str, Any]:
        return {"outcome": "ok", "detail": "夹具：V 签了"}


class _FakeH:
    """H 的替身：`list_findings` 不接必填参数。"""

    def list_findings(self, **kw: Any) -> dict[str, Any]:
        return {"outcome": "ok", "detail": "夹具：H 列了 findings"}


#: 端到端要的那几格召唤：角色 → (动作, 参数)。每一对都取自真身声明，不是编的。
_OWNER_STEPS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("D", "probe_c", {"qid": "q-1"}),
    ("F", "status", {"plan_id": "p-1"}),
    ("A", "run_once", {}),
    ("B", "run_once", {}),
    ("V", "verify_proof", {}),
)

_BOUNDARY_STEPS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("G", "refresh_markdown", {"doc_id": "doc-1"}),
    ("D", "probe_c", {"qid": "q-2"}),
    ("F", "status", {"plan_id": "p-2"}),
    ("A", "run_once", {}),
    ("B", "run_once", {}),
    ("H", "list_findings", {}),
)


def _conductor(tmp_path, *, policy: P.Policy | None = None) -> Conductor:
    """真的 `Conductor` + 真台账；只把各角色的绑定换成"造得出这一行"的替身。"""
    store = Store(tmp_path / "ws")
    store.init()
    registry = {
        "G": ("object", _FakeG()), "D": ("object", _FakeD()), "F": ("object", _FakeF()),
        "A": ("object", _FakeA()), "B": ("object", _FakeB()), "V": ("object", _FakeV()),
        "H": ("object", _FakeH()),
    }
    return Conductor(store, policy=policy or P.Policy(), registry=registry,
                     fanout_wait_sec=0.0)


def _chain(cond: Conductor, steps, *, tag: str) -> tuple[list[tuple[str, int, str]], str, str]:
    """按 `steps` 一层层 summon 下去，返回每一跳的 (角色, depth, outcome) 与末端。"""
    got: list[tuple[str, int, str]] = []
    parent: str | None = None
    by = "M"
    for i, (role, action, params) in enumerate(steps, start=1):
        r = cond.summon(role, action, params, by=by, parent_task_id=parent,
                        input_key=f"{tag}-{i}")
        got.append((role, int(r.depth), str(r.outcome)))
        assert r.outcome == "ok", (
            f"链在 {by} → {role} 这一跳断了：{r.outcome}/{r.refusal_reason}："
            f"{getattr(r, 'detail', '')}"
        )
        parent, by = str(r.task_id), role
    return got, str(parent), by


def test_end_to_end_the_owner_chain_lands_in_the_ledger_and_v_is_let_through(
        tmp_path) -> None:
    """判据 11（端到端）：真的 `Conductor` 走出 `M→D→F→A→B→V`，V 那一跳放行。

    台账读数：第 2..6 个代理 = depth 1..5；V 落在 depth 5 —— 旧值 4 的现场是
    `depth_exceeded`（83 的 `t-000252`，见 `tests/test_reviewer_does_not_occupy_the_chain.py`）。
    深的那两层（第 7 / 第 8 个）换 `BOUNDARY_CHAIN` 量：2026-11-05 起 V 没有出边，
    挂在 V 下面会先撞 `forbidden_edge`，拒因就不是深度了。
    """
    cond = _conductor(tmp_path)
    got, _parent, _by = _chain(cond, _OWNER_STEPS, tag="owner")
    assert got == [("D", 1, "ok"), ("F", 2, "ok"), ("A", 3, "ok"),
                   ("B", 4, "ok"), ("V", 5, "ok")], got

    # 双证：摘掉审稿人豁免，同一条链在真 conductor 上仍然走得通（V 由深度放行）
    stripped = _conductor(tmp_path / "stripped",
                          policy=dataclasses.replace(P.Policy(), reviewer_roles=frozenset()))
    got2, _parent2, _by2 = _chain(stripped, _OWNER_STEPS, tag="owner-stripped")
    assert got2[-1] == ("V", 5, "ok"), got2


def test_end_to_end_depth_six_is_allowed_and_depth_seven_is_refused(tmp_path) -> None:
    """判据 11'（端到端）：7 个代理全落台账（末跳 depth 6 放行），第 8 个被深度拒。"""
    cond = _conductor(tmp_path)
    got, parent, by = _chain(cond, _BOUNDARY_STEPS, tag="seven")
    assert got == [("G", 1, "ok"), ("D", 2, "ok"), ("F", 3, "ok"),
                   ("A", 4, "ok"), ("B", 5, "ok"), ("H", 6, "ok")], got
    # 第 7 个代理（H，台账 depth 6）再派第 8 个（depth 7）⇒ 深度拒
    over = cond.summon("A", "run_once", {}, by=by, parent_task_id=parent,
                       input_key="seven-over")
    assert int(over.depth) == 7, over.depth
    assert over.outcome == "refused" and over.refusal_reason == "depth_exceeded", over
    assert f"max_chain_depth={EXPECTED_CHAIN_HOPS}" in str(getattr(over, "detail", "")), \
        getattr(over, "detail", "")
