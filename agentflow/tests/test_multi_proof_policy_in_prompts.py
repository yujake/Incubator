# -*- coding: utf-8 -*-
"""判据（D-54）：D / F / B 三处渲染提示词都要写清"一条定理的多种证明"落成什么形状。

## 这条判据守什么

业主 2026-10-24 的两句话：「中间路径会有很多，我们不关心。就是最后一步，比如 Sylow 第一定理，
会有几种证明语言，会有不同的依赖面，然后后续让 C 从不同的依赖面起点追依赖链就能完整显示
不同证明路径」「B侧应该已经做过对同一定理收录多种证明和所对依赖面了，请确认」。

确认结论是：机制早就完整（`proofs=[{proof_no, text}]`、`used_by="stmt:<号>#pN"`、
二维 `path_group`、`reviewed_by_proof`、对应表带 `proof_no`、收工读数按
`(stmt_id, proof_no)`），缺的是"用户要几种证明"该落成什么形状的口径。真机上
（`projects/sylow3`）同一条 Sylow 定理被登记成三条独立命题、`proof_no` 恒 1、
`path_group` 只有一组 ⇒ 多证明机制一次都没被触发。

## 判据两条

1. 正控（④）：三个角色各自渲染出来的提示词里，同一条政策里能读到
   "一条 stmt" ＋ `proof_no` 1..N ＋ `path_group` ＋ 各自 V 签（`reviewed_by_proof`）
   ＋ 反向判据（不要把同一条定理拆成多条命题）。逐角色逐条判，缺一条就点名缺哪条；
2. 反真空（⑤）：把某个角色那条政策从它的声明里删掉 ⇒ 该角色的渲染结果必须缺词（红），
   其余角色的不动。三个角色各做一遍 —— 只做其中一个的话，另外两处可以静默烂掉。

## 边界

- 只判"渲染出来的提示词里读得到"，不判用词风格；同一句话在三个角色那里按各自的活
  写成不同措辞（B 是登记、F 是产出、D 是派活与目录），所以判据钉的是几样硬东西。
- 不动 `PROMPT_VERSION`、不重冻摘要表：本批的版本号由下一批统一抬（业主口径），
  这条判据不读版本号。
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from agentflow import agent_prompts as AP
from agentflow.tools import build_registry

#: 三处都要能读到的硬东西（一条 stmt / proof_no 1..N / path_group / 各自 V 签 / 反向判据）。
REQUIRED = (
    "一条 stmt",
    "proof_no",
    "1..N",
    "path_group",
    "reviewed_by_proof",
    "不要把同一条定理拆成多条命题",
)

#: 每个角色那条政策的识别句（删它 = 反真空；也是"这条政策真的在它的声明里"的正控）。
MARKERS: dict[str, str] = {
    "B": "同一条定理的多种证明只占一条 stmt",
    "D": "用户要「一条定理的几种证明」",
    "F": "一条定理要几种证明",
}

_ROLES = ("B", "D", "F")


def _missing(text: str) -> list[str]:
    return [token for token in REQUIRED if token not in text]


def _prompt(role: str, registry: object) -> str:
    return AP.system_prompt(role, registry=registry, task="把这条链路走一遍",
                            workspace_root="D:/x")


@pytest.fixture(scope="module")
def prompts() -> dict[str, str]:
    registry = build_registry().registry
    return {role: _prompt(role, registry) for role in _ROLES}


def test_each_role_renders_the_multi_proof_shape(prompts: dict[str, str]) -> None:
    """④ B / D / F 三处渲染提示词都能读到同一形状（缺哪一样就点名）。"""
    problems = [f"{role}：缺 {_missing(text)}" for role, text in prompts.items()
                if _missing(text)]
    assert problems == [], (
        "多证明口径没有写进这些角色的提示词（用户要「几种证明」时它们会各立一条命题）：\n  "
        + "\n  ".join(problems))


def test_the_policy_sentence_itself_carries_every_piece(prompts: dict[str, str]) -> None:
    """④的加强：那几样东西要落在同一条政策里，而不是散落在整份提示词各处。

    散落的写法在真机上吃过亏（B 的 `PROOF_CHANNEL` 里早就有 `proof_no` 这个词，
    但没有任何一句说"要几种证明是一条命题的 1..N、不是几条命题"）。
    """
    problems: list[str] = []
    for role in _ROLES:
        brief = AP.ROLE_BRIEFS[role]
        marker = MARKERS[role]
        items = [item for item in brief.policy if marker in item]
        if len(items) != 1:
            problems.append(f"{role}：含 {marker!r} 的政策条目应当恰好 1 条，实际 {len(items)} 条")
            continue
        missing = _missing(items[0])
        if missing:
            problems.append(f"{role}：那一条政策里缺 {missing}")
    assert problems == [], "\n  ".join(["多证明政策没有聚在同一条里："] + problems)


def test_deleting_one_roles_policy_makes_that_role_red(
        prompts: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 反真空：删掉某角色那句 ⇒ 该角色必红（三个角色各删一遍）。"""
    registry = build_registry().registry
    for role in _ROLES:
        brief = AP.ROLE_BRIEFS[role]
        marker = MARKERS[role]
        kept = tuple(item for item in brief.policy if marker not in item)
        assert len(kept) == len(brief.policy) - 1, (
            f"{role}：删之前应当恰好删掉一条（实际 {len(brief.policy) - len(kept)} 条）")
        with monkeypatch.context() as patch:
            patch.setitem(AP.ROLE_BRIEFS, role, replace(brief, policy=kept))
            broken = _prompt(role, registry)
        assert _missing(broken), (
            f"把 {role} 的多证明政策删掉之后，它的提示词仍然读得到那几样东西 "
            f"⇒ ⑤ 这条判据在自说自话（它读的是别处的措辞）")
    # 正控：同一批渲染里，另外两个角色（未被删）仍然是全的。
    for role in _ROLES:
        assert not _missing(prompts[role]), f"{role} 的基线提示词本来就缺词：{_missing(prompts[role])}"
