# -*- coding: utf-8 -*-
"""判据（16A）：渲染后的完整 system prompt 只许点名这个角色拿得到的工具。

## 为什么要有这一条（审计 AU1 ③ 的缺口）

现行四条判据都在「声明 ↔ 声明」这一层：policy ↔ 面、动作 ↔ 实现、动作参数 ↔
工具参数、动作 ↔ 冻结基线。没有一条守「模型真正读到的那份文本 ↔ 该角色的工具面」。
而 `agentskill` / `agent_prompts` 的共用段、伙伴表、官能段、工具摘要都会渲染进
system prompt —— 一句话写错，模型照着调，框架只能回 `unknown_tool` / `role_denied`。

这一条把那一层补上：逐角色渲染完整 system prompt（与生产同一条入口、同一张带
`fs.*` / `research.*` 的注册表 —— 裸 `build_registry()` 少 13 件，不能拿它当"面"），
扫 `组.动作` 形态的工具名，凡命中注册工具名而不在该角色面上 ⇒ 红。

## 豁免（逐条登记，不是白名单）

审计 AU1 表一 C1 记了一类设计如此的跨角色引用：伙伴表把同伴的 boundary 原话逐字
抄进提示词（B / D / F / G / M 五份，Lean 开档还有 L —— L 读 C 的 boundary）。
还有 M 的 `attack.status`（它是 `F.status` 的返回值字段路径，不是工具）。这两类
连同"同一句写明施事 / 自带否定 / 两种命名空间"一起登记在 `tests/_prompt_surface.py`
的 `EXEMPT` 里，每条带类目、原文锚点、两档出现次数。

## 判据（正控 / 反真空 / 负控）

1. 正控：每个角色渲染出的提示词，扫出来的跨面工具名恰好等于登记表（逐对）；
2. 反真空 ①：扫描器真的抓到一条人造的跨面提及（往 A 的提示词里塞 `review.report`）；
3. 反真空 ②：把豁免清单清空 ⇒ 五份伙伴表角色（B/D/F/G/M）必须红 —— 证明豁免真在
   挡事，而不是"这些 token 恰好不在提示词里"；
4. 反真空 ③：登记表里的锚点/次数任意改错一条 ⇒ 必须红（证明表不是橡皮图章）；
5. 反真空 ④：注册表必须是带 `fs.*` / `research.*` 的那一份（否则扫的是残缺的面）。
"""
from __future__ import annotations

import pathlib
import tempfile

from agentflow import agent_prompts as AP
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_registry

from _prompt_surface import (  # noqa: E402  （同目录的共用扫描器，不是 test_ 文件）
    EXEMPT,
    PARTNER_TOKENS,
    WHY,
    Exemption,
    foreign_tokens,
    pair_count,
    partner_text,
    scan,
)

#: 套件基线是 Lean 开档（`tests/conftest.py:179`）⇒ 十一格全在（含 L）。
ALL_ROLES: tuple[str, ...] = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)

#: 伙伴表逐字抄同伴 boundary 的五份（审计 AU1 表一 C1）。
PARTNER_ROLES: tuple[str, ...] = ("B", "D", "F", "G", "M")


def _world() -> tuple[pathlib.Path, object]:
    """一套带工作区的注册表（`fs.*` / `research.*` 装得起来的那一份）。"""
    root = pathlib.Path(tempfile.mkdtemp(prefix="cl2-prompt-surface-"))
    st = Store(root)
    st.init()
    reg = build_registry(store=st, workspace_root=str(root)).registry
    return root, reg


def _prompt(role: str, root: pathlib.Path, registry: object) -> str:
    return AP.system_prompt(role, registry=registry, task="把这条链路走一遍",
                            workspace_root=str(root))


def test_every_rendered_prompt_names_only_its_own_tools() -> None:
    """正控：十一份渲染提示词里的跨面工具名，逐对都在登记表里。"""
    root, reg = _world()
    bad: list[str] = []
    pairs = 0
    for role in ALL_ROLES:
        text = _prompt(role, root, reg)
        assert len(text) > 20000, f"{role} 的提示词只有 {len(text)} 字 ⇒ 渲染面不对"
        pairs += len(foreign_tokens(text, reg, role))
        bad += scan(role, text, reg, mode="on")
    # 反真空：扫出来的对数必须等于登记数（表与现场同进同退；少一对 = 表过期）
    assert pairs == len(EXEMPT), (
        f"现场扫出 {pairs} 对跨面提及，登记表是 {len(EXEMPT)} 对 ⇒ "
        "要么提示词变了，要么这张表过期了")
    assert not bad, (
        "渲染后的提示词点名了该角色拿不到的工具（模型会照着调）：\n  - "
        + "\n  - ".join(bad))


def test_the_scan_catches_an_injected_foreign_tool() -> None:
    """负控：往 A 的提示词里塞 `review.report`（A 面上没有）⇒ 扫描器必须报。"""
    root, reg = _world()
    poisoned = _prompt("A", root, reg) + "\n顺手用 `review.report` 落一份审校报告。\n"
    bad = scan("A", poisoned, reg, mode="on")
    assert any("review.report" in one for one in bad), bad


def test_clearing_the_exemption_list_turns_the_five_partner_roles_red() -> None:
    """反真空：清空豁免清单 ⇒ 五份伙伴表角色必须红（豁免真的在挡事）。

    这一条同时说明"为什么不能只按名字扫"：这五份里的 `analysis.*` / `review.*` 是
    伙伴表的机制（句子主语是"它"，逐字抄的 boundary），设计如此；登记它们是为了让
    "新出现一个没登记的跨面提及"这件事仍然红。
    """
    root, reg = _world()
    red = {role: scan(role, _prompt(role, root, reg), reg, mode="on", exempt={})
           for role in PARTNER_ROLES}
    assert all(red.values()), f"清空豁免后仍不红：{ {k: v for k, v in red.items() if not v} }"
    for role in PARTNER_ROLES:
        assert any(tok.split(".")[0] in ("analysis", "review")
                   for tok in foreign_tokens(_prompt(role, root, reg), reg, role)), role
        print(f"[反真空] 清空豁免后 {role} 报出 {len(red[role])} 条，"
              f"首条：{red[role][0]}")


def test_every_registration_is_still_needed_and_still_justified() -> None:
    """反真空：登记表逐条都要还成立（token 还在、次数对、锚点还在、伙伴表引用只在伙伴表里）。"""
    root, reg = _world()
    problems: list[str] = []
    for (role, token), entry in EXEMPT.items():
        if role not in ALL_ROLES:
            problems.append(f"{role}/{token}: 角色不在 ALL_ROLES 里")
            continue
        text = _prompt(role, root, reg)
        if token not in text:
            problems.append(f"{role}/{token}: 提示词里已经没有它了 ⇒ 删掉这条登记")
            continue
        if entry.klass not in WHY:
            problems.append(f"{role}/{token}: 类目 {entry.klass!r} 不在受控表里")
            continue
        if text.count(token) != entry.count_on:
            problems.append(f"{role}/{token}: 出现 {text.count(token)} 次，登记 "
                            f"{entry.count_on} 次")
            continue
        if entry.klass == "partner_quote":
            if token not in PARTNER_TOKENS:
                problems.append(f"{role}/{token}: partner_quote 只许用在伙伴表那五件上")
            elif partner_text(role).count(token) != text.count(token):
                problems.append(f"{role}/{token}: 不在伙伴表里，登记理由不成立")
            continue
        if not entry.anchor or entry.anchor not in text:
            problems.append(f"{role}/{token}: 锚点不在了 {entry.anchor!r}")
    assert not problems, "豁免登记表出问题（过期/理由不成立）：\n  - " + "\n  - ".join(problems)
    # 反真空：五份伙伴表角色各至少有一条 partner_quote 登记（否则上面那半是空转）
    for role in PARTNER_ROLES:
        assert pair_count(role) >= 1, role
        assert any(EXEMPT[(role, tok)].klass == "partner_quote"
                   for tok in PARTNER_TOKENS if (role, tok) in EXEMPT), role


def test_a_registration_with_a_stale_anchor_or_a_wrong_count_turns_red() -> None:
    """反真空：把一条登记的理由改错（锚点 / 次数）⇒ 必须红，证明表不是橡皮图章。"""
    root, reg = _world()
    text = _prompt("B", root, reg)
    key = ("B", "conductor.wake_blocked")
    original = EXEMPT[key]
    changed = dict(EXEMPT)

    changed[key] = Exemption(original.klass, "这句话不在提示词里", original.count_on,
                             original.count_off)
    bad_anchor = scan("B", text, reg, mode="on", exempt=changed)
    assert any("锚点" in one for one in bad_anchor), bad_anchor

    changed[key] = Exemption(original.klass, original.anchor, original.count_on + 1,
                             original.count_off)
    bad_count = scan("B", text, reg, mode="on", exempt=changed)
    assert any("出现" in one for one in bad_count), bad_count


def test_the_registry_used_here_is_the_real_exported_surface() -> None:
    """反真空：这条判据必须拿带 `fs.*` / `research.*` 的注册表扫描（不是残缺的那一份）。"""
    _root, reg = _world()
    names = {str(n) for n in reg.names()}
    assert {"fs.write", "fs.read", "research.list_gaps"} <= names, (
        "注册表里没有 fs.* / research.* ⇒ 扫的是 audit AU1 ③-1 说的那份残缺面")
    assert len(names) >= 120, f"注册表只有 {len(names)} 件工具"
