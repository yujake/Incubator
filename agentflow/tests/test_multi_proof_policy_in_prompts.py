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

1. 正控（④）：三个角色各自渲染出来的提示词里，同一条政策里能读到该角色那种形状
   的几样硬东西（见下面的 `REQUIRED`）。逐角色逐条判，缺一条就点名缺哪条；
2. 反真空（⑤）：把某个角色那条政策从它的声明里删掉 ⇒ 该角色的渲染结果必须缺词（红），
   其余角色的不动。三个角色各做一遍 —— 只做其中一个的话，另外两处可以静默烂掉。

## 2026-11-10 契约变更（p272 / p274 / p275：F 的稿自建号源）

改前：三个角色共用一份硬词表（"一条 stmt" ＋ `proof_no` 1..N ＋ `path_group` ＋
`reviewed_by_proof` ＋ 反向判据）。那时 F 也被要求写"一条 stmt"。

改后（业主：「F 的稿自己维护一套号源，不依赖命题号和计划号」；命题号由 B 收录时现取）：
台账口径（一条 stmt 装 1..N 份证明）只在 B / D 侧成立；F 侧的形状是稿口径
（同一个稿号 `f-proof-<稿号>` ＋ 第 N 份证明 `-pN` ＋ 命题号由 B 收录时现取）。
判据因此逐角色分开钉，并加一条反向断言：F 的政策里不许退回台账口径的旧句子。

## 2026-11-11 契约变更（p276：一个稿号 = 一份文件 = 一份证明）

业主追加裁定：「一个稿号就相当于是该稿的文件名」「同稿号多个版本是错误的」。
⇒ F 侧不再有"同一份稿的第 N 个证明"：同一命题要第二份证明就另开一份稿（新稿号）；
`-pN` 只剩老盘只读兼容，新写不产生。台账侧（B / D）的"一条 stmt 装 1..N 份证明"
一个字没变 —— 1..N 现在是 N 份稿各算一条路径，不是一份稿里的 N 个版本。
F 的反向断言因此多钉一条：`-pN` / `proof_no=N` 那套旧教法不许回到政策里。

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

#: 每个角色那条政策必须聚齐的硬东西。
#:
#: 2026-11-10（p272/p274/p275 的稿号口径）之后三个角色不再共用同一句话：
#: - B / D 那条政策说的是台账里的形状：一条 stmt 装 1..N 份证明（`proof_no` 1..N）；
#: - F 那条政策说的是稿上的形状：一个稿号 = 一份文件 = 一份证明，同一命题要第二份
#:   证明就另开一份稿（新稿号）；命题号由 B 收录时现取 —— F 既不立命题、也不写号。
#: 改前这里是一份全局元组：F 也必须含「一条 stmt / 1..N」⇒ 它钉的其实是 B/D 的话，
#: 会把 F 按新口径写对的政策判成红。改后逐角色钉各自的形状：B/D 一条不少，F 的检查项
#: 从 0（它本来就不该有那两条）变成 9 条（稿口径的每一样都在）。
REQUIRED: dict[str, tuple[str, ...]] = {
    "B": (
        "一条 stmt",
        "proof_no",
        "1..N",
        "path_group",
        "reviewed_by_proof",
        "不要把同一条定理拆成多条命题",
    ),
    "D": (
        "一条 stmt",
        "proof_no",
        "1..N",
        "path_group",
        "reviewed_by_proof",
        "不要把同一条定理拆成多条命题",
    ),
    "F": (
        "一个稿号",
        "一份文件",
        "一份证明",
        "每份证明各开一份稿（新稿号）",
        "f-proof-",
        "命题号由 **B 收录时现取**",
        "path_group",
        "老盘上已有的",
        "不要把同一条定理拆成多条命题",
    ),
}

#: F 那条政策里不许再出现的旧教法（2026-11-11 之后）。
#:
#: 断言的是"教人按 `-pN` 在同一份稿里写第 N 份证明"的那几原话；老盘兼容那一句
#: （`reports/f-proof-<号>-p2.md` 只读兼容）是另一件事，不在本表里。
F_OLD: tuple[str, ...] = (
    "同一份稿的第 N 份证明",
    "每份落在同一份稿的第 N 个证明上",
    "`reports/f-proof-<你的稿号>-p<N>.md`",
    "`verify_proof` 带 `proof_no=N`",
    "`-pN`），不是几条命题",
)

#: 每个角色那条政策的识别句（删它 = 反真空；也是"这条政策真的在它的声明里"的正控）。
MARKERS: dict[str, str] = {
    "B": "同一条定理的多种证明只占一条 stmt",
    "D": "用户要「一条定理的几种证明」",
    "F": "一条定理要几种证明",
}

_ROLES = ("B", "D", "F")


def _missing(role: str, text: str) -> list[str]:
    return [token for token in REQUIRED[role] if token not in text]


def _policy_item(role: str) -> str | None:
    """角色声明里那一条多证明政策（应当恰好一条；不唯一时返回 `None`）。"""
    brief = AP.ROLE_BRIEFS[role]
    items = [item for item in brief.policy if MARKERS[role] in item]
    return items[0] if len(items) == 1 else None


def _prompt(role: str, registry: object) -> str:
    return AP.system_prompt(role, registry=registry, task="把这条链路走一遍",
                            workspace_root="D:/x")


@pytest.fixture(scope="module")
def prompts() -> dict[str, str]:
    registry = build_registry().registry
    return {role: _prompt(role, registry) for role in _ROLES}


def test_each_role_renders_the_multi_proof_shape(prompts: dict[str, str]) -> None:
    """④ B / D / F 三处渲染提示词都能读到各自那种形状（缺哪一样就点名）。"""
    problems = [f"{role}：缺 {_missing(role, text)}" for role, text in prompts.items()
                if _missing(role, text)]
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
        marker = MARKERS[role]
        item = _policy_item(role)
        if item is None:
            brief = AP.ROLE_BRIEFS[role]
            n = sum(1 for entry in brief.policy if marker in entry)
            problems.append(f"{role}：含 {marker!r} 的政策条目应当恰好 1 条，实际 {n} 条")
            continue
        missing = _missing(role, item)
        if missing:
            problems.append(f"{role}：那一条政策里缺 {missing}")
    assert problems == [], "\n  ".join(["多证明政策没有聚在同一条里："] + problems)


def test_the_old_ledger_shape_does_not_come_back_into_f() -> None:
    """反向（契约变更的反面）：F 那条政策不许退回 B/D 的台账口径，也不许退回 `-pN`。

    2026-11-10 之前 F 也按「一条 stmt / 1..N」写；现在 F 的稿自建号源
    （`f-proof-<稿号>`）、命题号由 B 收录时现取。2026-11-11 又收掉了「同一份稿的
    第 N 个证明」这一档：一个稿号 = 一份文件 = 一份证明。任一旧句子贴回 F 的政策里
    ⇒ 本判据红。
    """
    item = _policy_item("F")
    assert item is not None, "F 的多证明政策应当恰好一条（先看上面那条判据）"
    stale = [token for token in ("一条 stmt", "1..N") if token in item]
    stale += [token for token in F_OLD if token in item]
    assert not stale, (
        f"F 的多证明政策里又出现了旧口径的句子 {stale} —— F 不立命题、不写命题号，"
        "一个稿号 = 一份文件 = 一份证明；同一命题要第二份证明就另开一份稿（新稿号）")
    # 正控：B / D 仍是台账口径 —— 这条反向断言不是把三个角色一起放宽成"谁都不用写"。
    for role in ("B", "D"):
        other = _policy_item(role)
        assert other is not None, f"{role} 的多证明政策应当恰好一条"
        for token in ("一条 stmt", "1..N"):
            assert token in other, (
                f"{role} 的台账口径里不再有 {token!r} ⇒ 旧形状被一起删掉了（反向断言的两端都要在）")


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
        assert _missing(role, broken), (
            f"把 {role} 的多证明政策删掉之后，它的提示词仍然读得到那几样东西 "
            f"⇒ ⑤ 这条判据在自说自话（它读的是别处的措辞）")
    # 正控：同一批渲染里，另外两个角色（未被删）仍然是全的。
    for role in _ROLES:
        assert not _missing(role, prompts[role]), (
            f"{role} 的基线提示词本来就缺词：{_missing(role, prompts[role])}")
