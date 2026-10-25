"""能力面复核（第一片）：工具面上没有可删的多余项 —— 但这件事要有机器读数。
## 这一条守的是什么
业主的经验文档要求定期做"角色能力面复核"，找工具面/动作面的多余项。2026-10-21 第一遍量下来（现读注册表），跨域工具一共 58 处，逐个都有职责理由：
| 跨域工具 | 出现在谁的面 | 为什么不是噪音 |
|---|---|---|
| `conductor.escalate` | 十个角色全部 | 通用上行通道：任何角色都要能向父代理上报（业主 2026-10-19 裁定） |
| `conductor.broadcast` | 只有有子代理的角色（A/B/D/E/F/G） | 广播是"向我的子代理"——没有子代理的人拿到它才是噪音 |
| `attack.check_budget` / `list_plans` / `pick_next_subgoal` / `status` | D / G / H | 读别的角色的计划是统筹与审稿需要的（D 派 F、H 评 F
的产出） |
| `doc.compose_claim` / `list_documents` / `scan_claim` | D / F / H | 同上：读稿件面 |
| `verify.run_experiment` / `code_hash` / `check_formal` | E / F / G / H | 这些本来就是 E 的工具（`verify.` 前缀里混着 E 与 V 两家）
——按前缀当"域"会误报 |
⇒ 结论：没有"看得见却调不动"或明显多余的项。这一条把它钉住，免得以后有人凭"看着不像他的"删掉一件别人真需要的工具。
## 判据（含负控）
① `conductor.escalate` 在十个角色面上都有（通用上行，少一个就有人上不了报）；② `conductor.broadcast` 只出现在有子代理的角色面上（A/B/D/E/F/G）；③ M 的面是纯编排面：
不许出现 `attack.*` / `doc.*` / `verify.*` / `lit.*` / `analysis.*`（M 的活是统筹与搭桥，研究侧的执行归 D）；④ 反真空：十个角色面都非空、并集 = 全库减去
"只挂给普查角色集之外的那些角色的工具"
——否则"没有多余项"可能是"面是空的"。
"""

#: 本文件普查的角色集合刻意不含 L：L 的三件 `formal.*` 只挂给它自己，
#: 而这条判据问的是"A-H + V + M 的面有没有漏"。并集口径因此是
#: "全库 − 只挂给 L 的那几件"。
#:
#: 2026-10-27：这里的那个数字（95 → 102 → 104）一直是"会腐烂的字面量"：
#: 每加一件工具它就要人记得回来改一次，而它改不改都不影响这条判据在量什么。
#: 现在改成从注册表现算：`spec.roles` 与普查角色集有交集的工具必须出现在并集里，
#: 没有交集的必须不在。实测读数（2026-10-27，十件 clock 全在）：全库 110 件，
#: 其中只挂给 L 的 3 件 ⇒ 并集 107 件；那个数字从此只作为本次读数出现在失败信息里。

from __future__ import annotations

import functools
import tempfile
from pathlib import Path
from typing import Any

import pytest

from agentflow import capabilities as CAP
from agentflow import host
from agentflow import store as S

ROLES = ("A", "B", "C", "D", "E", "F", "G", "H", "V", "M")
RESEARCH_PREFIXES = ("attack.", "doc.", "verify.", "lit.", "analysis.")

#: 并集的下界（防真空）：低于它说明注册表根本没装起来，"没有多余项"只是"什么都没扫到"。
UNION_FLOOR = 100


@functools.lru_cache(maxsize=1)
def _built() -> tuple[dict[str, list[str]], dict[str, tuple[str, ...]]]:
    """现读一次注册表：每个角色的面，以及每件工具声明给了谁（都从 `spec.roles` 取）。"""
    tmp = Path(tempfile.mkdtemp())
    st = S.Store.open(tmp, "w") if hasattr(S.Store, "open") else S.Store(tmp)
    built: Any = host.wired_tool_registry(st, providers=[object()])
    reg = built.registry if hasattr(built, "registry") else built
    faces = {role: sorted(t.name for t in reg.for_role(role)) for role in ROLES}
    roles = {name: tuple(reg.get(name).roles) for name in reg.names()}
    return faces, roles


@pytest.fixture(scope="module")
def faces() -> dict[str, list[str]]:
    """现读注册表：每个角色被广告的工具名（不抄任何清单）。"""
    return _built()[0]


@pytest.fixture(scope="module")
def declared_roles() -> dict[str, tuple[str, ...]]:
    """现读注册表：每件工具 `roles` 那一格声明给了谁（并集口径的唯一来源）。"""
    return _built()[1]


def test_every_role_can_escalate_upward(faces: dict[str, list[str]]) -> None:
    """① 通用上行：十个角色都要能 `escalate`（少一个就有人上不了报）。"""
    missing = [r for r in ROLES if "conductor.escalate" not in faces[r]]
    assert not missing, f"这些角色拿不到 `conductor.escalate`（上不了报）：{missing}"


def test_broadcast_is_only_for_roles_with_children(faces: dict[str, list[str]]) -> None:
    """② 广播只给有子代理的人：`conductor.broadcast` 出现在谁的面 ⇒ 那个角色必须有出边。"""
    with_broadcast = [r for r in ROLES if "conductor.broadcast" in faces[r]]
    assert with_broadcast, "没有任何角色拿得到 `conductor.broadcast` ⇒ 这一条判据没有对象"
    no_children = [r for r in with_broadcast if not CAP.ALLOWED_EDGES.get(r)]
    assert not no_children, (
        f"这些角色没有可以唤起的伙伴，却拿到了 `conductor.broadcast`（噪音）：{no_children}")
    # 反真空：没有出边的角色不该拿到它（否则"只给有子的"这句是空话）
    for role in ROLES:
        if not CAP.ALLOWED_EDGES.get(role):
            assert "conductor.broadcast" not in faces[role], (
                f"{role} 没有出边却拿到了 broadcast")


def test_the_conductor_face_stays_orchestration_only(faces: dict[str, list[str]]) -> None:
    """③ M 的面是纯编排面：研究侧的工具一个都不许混进来。"""
    leaked = sorted(n for n in faces["M"] if n.startswith(RESEARCH_PREFIXES))
    assert not leaked, f"M 的工具面混进了研究侧工具：{leaked}"
    # 反真空：M 至少还有编排工具（别把"面空了"当成通过）
    assert [n for n in faces["M"] if n.startswith("conductor.")], "M 的工具面是空的"


def test_no_face_is_empty_and_the_union_is_the_whole_library(
    faces: dict[str, list[str]],
    declared_roles: dict[str, tuple[str, ...]],
) -> None:
    """④ 反真空：每个角色面都非空；并集 = 全库里"声明给了这十个角色"的那些工具。

    期望值不写死（那个字面量每加一件工具就要人回来改一次，而它改不改都不影响这条
    判据在量什么）：从同一张注册表的 `spec.roles` 现算 —— 与本文件普查的角色集
    有交集的必须出现在并集里，没交集的（今天只有 L 的三件 `formal.*`）必须不在。
    """
    empty = [r for r in ROLES if not faces[r]]
    assert not empty, f"这些角色的工具面是空的：{empty}"
    union = {n for names in faces.values() for n in names}
    expected = {name for name, roles in declared_roles.items() if set(roles) & set(ROLES)}
    assert len(union) >= UNION_FLOOR, (
        f"角色面并集只有 {len(union)} 件（下界 {UNION_FLOOR}）—— 注册表没装起来，"
        "这一条判据什么都没在量")
    assert union == expected, (
        "角色面并集与注册表声明的角色集对不上：\n"
        f"  面上有、声明里没有（这几件没人声明给它，却被装上了）：{sorted(union - expected)}\n"
        f"  声明里有、面上没有（有人被摘掉了工具）：{sorted(expected - union)}"
        f"（实测：全库 {len(declared_roles)} 件，期望并集 {len(expected)} 件，实际 {len(union)} 件）")
