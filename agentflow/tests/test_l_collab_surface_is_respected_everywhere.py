# -*- coding: utf-8 -*-
"""L 的协作面只有 B 一条入边、C 一条出边 —— 全仓提示词与工具面按这一面清理（五条判据）。

## 权威原文（逐字，唯一权威）

> 只有 B 可以派 L，L 允许派 C 来梳理证明链，消费 B 的定理证明库，
> 可向 B 汇报形式化过程中遇到的困难、要求 B 完善证明并重新得到 V 签，
> 若缺陷严重，B 应通知 D 开展研究处理证明难点。

2026-10-24 追加（业主原话）：「是否形式化由用户指定，需有许可再做形式化。」
⇒ 完整授权链（正向流程，六步）：用户指定 ⇒ M 派 B ⇒ B 派 L ⇒ 给什么 / 要回什么
⇒ 三态是 unknown 时怎么办 ⇒ 困难回到 B、B 改证明重拿 V 签、缺陷严重 B 通知 D。
B 也没有"自己决定要形式化"的权力：它只是"用户给了许可之后的那条执行通道"。

⇒ 除 B 与 L 自己以外，任何角色的提示词都不许把 L 当"可以打交道的人"；
L 与 A / C / D / E / F / G / H / M / V 之间没有边（C 那一格是入边，见判据 ①）。

## 五条判据与各自的改前红（改前 = 本文件加进来时的那棵树，读数见交付回报）

| # | 判据 | 改前红（实测原文） |
|---|---|---|
| 1 | 非 B / L 的渲染提示词里不出现 L（白名单只有两格：五元位的 owner 读数、C 的入边那一行） | E 写「断言能否形式化就找 L」、G 写「形式化那一岗（形式化那一岗是 L）」、H 写「找 L（形式化那一岗）」、M 写「两步都在 L 那一岗」「L 不在你的出边里」、D 写「最终背书在形式化（L）」、PAPER_PACK 写「这两步都在 L 那一岗」 |
| 2 | B 的提示词正向写全六步；M 的提示词写着"用户要形式化就派 B" | B 只写「形式化那一岗的困难只交回给你」——没有许可、没有"逐条派 L"、没有给什么/要回什么、没有 unknown 那一档；M 写的是自己派 L 的两步（而那两件工具不在 M 的面上） |
| 3 | 非 B 角色的提示词里没有"别写 Lean / 不要要形式化"这类否定式指令 | E 写「别自己写 Lean 源码」「不要主动去要形式化」、G 写「别把它排进你的写作流」、PAPER_PACK 写「别把它排进流水线」「这一趟不要写 Lean 源码、不要派 check_formal」、全部角色都读到「要形式化就找 L，别自己写 Lean 源码」 |
| 4 | 工具面：除 L 以外没有角色拿得到 `formal.*`（实跑 `for_role`） | 改前这一条就是绿的（`formal.*` 的三件只发给 L）——它的正控那一半才是红过的：`verify.check_formal` 曾在 E / F / G 的面上 |
| 5 | 反真空：删掉 B 六步里的一步 ⇒ 判据 2 必红；把 L 加回某个角色的伙伴表 ⇒ 判据 1 必红 | 若判据 2 只在一份"碰巧有那几句话"的文本上成立，删一步它照样绿 —— 那它读的不是六步 |

## 为什么 C 的白名单里留着 L

`L → C` 是裁定给的唯一出边，C 的提示词因此有一行「这些伙伴可以唤起你：…、L、…」。
那一行说的是"谁可以派你"，不是"你可以去找谁"：把它删掉，C 读到的入边清单就与边表
不一致（L 派它的时候它会读到一个不在清单里的名字）。所以判据 ① 收的是
「除这一行以外，非 B 角色一个字都不许提 L」—— 比"伙伴表里没有 L"更强，同时不制造假话。

## 零模型

全部用例只读代码与渲染结果：不起子进程、不调模型、不写工作区。
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow import schema as S
from agentflow.tools import build_registry

#: 那个只在开关打开时存在的角色（本文件判的就是它的协作面）。
ROLE_L = "L"
#: 唯一有权派 L 的角色。
ROLE_B = "B"
#: 判据 1 的射程：除 B 与 L 自己以外的每一个角色（A–H、M、V，由 `schema.ROLES` 现算）。
OTHERS = tuple(r for r in (*S.ROLES, S.CONDUCTOR_ROLE) if r not in (ROLE_B, ROLE_L))

#: 角色名 `L` 的记号（ASCII 词边界：`Lean` / `Mathlib` / `ALL` 里的 L 不算）。
ROLE_NAME = re.compile(r"(?<![A-Za-z0-9_])L(?![A-Za-z0-9_])")

#: 非 B 角色的提示词里允许出现 L 的那两行（逐行白名单，其余一律红）。
#:
#: 第一格是五元位第 4 位的 owner 读数（`formal.record` 是它的唯一落点，所以那一行写着
#: 「`formal`：L 签」）—— 那是台账事实，不是"去找谁"；
#: 第二格是 C 的入边那一行（`L → C` 是裁定给的唯一出边，见模块 docstring 末节）。
_ALLOWED_L_PREFIXES = ("- `formal`：**L** 签", "这些伙伴可以唤起你：")
#: 第二格只对谁成立（入边那一行里出现 L 的，全仓只有这一个角色）。
_INBOUND_L_ROLE = "C"

#: 「把 L 当可以打交道的人」的几种说法（判据 1 的第二种形状：点名 L 且带动作）。
#: 冗余于逐行白名单，但红的时候给出的理由更具体（读者一眼知道该改哪一句）。
L_CONTACT = re.compile(
    r"(找|派|问|请|交给|交回|转给|扔给|通知|召唤)[\s*`]*\**L(?![A-Za-z0-9_])"
    r"|L[\s*`]*\**(那一岗|那边|那儿)"
)

#: 判据 2 的六步（B 的提示词里每一步的锚点，逐条给一句人话）。
#: 锚点取的是"读的人照着能做"的那半句，不是排版：换说法可以，但要能指到同一件事。
B_STEPS: tuple[tuple[str, str], ...] = (
    ("① 用户许可（没人指定就不做）", "用户指定「这一条需要形式化验证」"),
    ("② 许可之后 M 把这件要求交给 B", "许可之后 M 会把这件要求交给你"),
    ("③ B 逐条派 L（一条才做一条）", "逐条派 L"),
    ("④ 给 L 什么（命题 + 证明链 + 库里的条目）", "给三样"),
    ("⑤ 要回什么（检查器原话 + 退出码 + 三态）", "要回三样"),
    ("⑥ unknown 怎么办（补材料再派一次）", "补齐它点名缺的那一段"),
)
#: 判据 2 的第二半：M 那一步（"用户要形式化就派 B"）必须写在 M 的提示词里。
#: 这一条单独列，是因为整条链最容易漏的就是它（B 有、M 没有 ⇒ 许可到了没有人往下交）。
M_DISPATCH: tuple[str, str] = ("M 的动作为派 B（M→B）", "你的动作是派 B")

#: 判据 2 里"升级路径"那一步的锚点（缺陷严重 ⇒ B 通知 D 开展研究）。
B_ESCALATION = "escalate_proof_research"

#: 判据 3 的尺子：非 B 角色的提示词里不许再拿"禁止自己做形式化"顶替权限判断。
#: 这一族句子的共同形态是"别 / 不要 + 动作"，而它管的事（越权、伪造、越界）由判据钉住：
#: 工具面没有 `formal.*`、边表没有到 L 的出边、受控拒绝有理由码 —— 见 `draft/63` §2 与 `draft/34` §4。
NEGATED_FORMAL_ORDERS: tuple[str, ...] = (
    "别自己写 Lean",
    "不要写 Lean",
    "别写 Lean",
    "不要主动去要形式化",
    "不要要形式化",
    "别把它排进",
    "不主动召唤",
    "别派它",
    "不要碰 L",
    "别碰 L",
    "L 不在你的出边里",
)


def _registry():
    """开档的注册表（本文件跑在 `conftest.py` 钉住的那一档：Lean 开着）。"""
    return build_registry().registry


def _prompt(role: str, registry=None) -> str:
    """生产路径的渲染入口（`system_prompt` 是唯一收口）。"""
    return AP.system_prompt(role, registry=_registry() if registry is None else registry)


# ============================================================ 判据 1 的尺子
def _l_mention_problems(role: str, text: str) -> list[str]:
    """这一份非 B 角色的渲染里"把 L 当可以打交道的人"的地方（空 = 干净）。

    判法是逐行的白名单：只要某一行出现 L 这个角色名，而它又不是
    `_ALLOWED_L_PREFIXES` 里那两种形态之一 ⇒ 记一条违反。
    """
    bad: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not ROLE_NAME.search(line):
            continue
        if line.startswith(_ALLOWED_L_PREFIXES[0]):
            continue
        if role == _INBOUND_L_ROLE and line.startswith(_ALLOWED_L_PREFIXES[1]):
            continue
        hit = L_CONTACT.search(line)
        why = f"（{hit.group(0)!r}）" if hit else ""
        bad.append(f"{role}:{lineno}: 提示词里出现了 L{why}：{line[:90]}")
    return bad


# ============================================================ 判据 2 的尺子
def _missing_steps(text: str, steps: tuple[tuple[str, str], ...]) -> list[str]:
    """六步里缺了哪几步（按锚点判；空 = 六步都在）。"""
    return [name for name, needle in steps if needle not in text]


# ============================================================ 判据 3 的尺子
def _negated_orders(text: str) -> list[str]:
    """这一份渲染里"禁止自己做形式化"的那些句子（空 = 没有）。"""
    return [phrase for phrase in NEGATED_FORMAL_ORDERS if phrase in text]


# ============================================================ 判据 1
def test_one_no_other_role_treats_l_as_a_partner() -> None:
    """判据 1：除 B 与 L 自己外，没有任何角色的提示词把 L 当可以打交道的人。

    改前红（逐字）：E「断言能否形式化就找 L（形式化那一岗）」、G「形式化那一岗
    （形式化那一岗是 L）成本极高」、H「断言能否形式化就找 L」、M「两步都在 L 那一岗」
    「L 不在你的出边里」、D「最终背书在形式化（L）或人」、全部角色读到
    「要形式化就找 L，别自己写 Lean 源码」与「形式化见 L：`formal.*` 只挂在 L 身上」。

    反真空：白名单那两格必须真的在（否则"没有 L"可能只是"这两行也没了"），
    且判据函数在一份加回「找 L」的文本上必须报出来。
    """
    reg = _registry()
    problems: list[str] = []
    for role in OTHERS:
        problems += _l_mention_problems(role, _prompt(role, reg))
    assert problems == [], (
        f"{len(problems)} 处仍把 L 当可以打交道的人：\n  " + "\n  ".join(problems[:30]))

    # 白名单第一格：五元位第 4 位的 owner 读数（每个非 L 角色都读得到）
    for role in OTHERS:
        assert _ALLOWED_L_PREFIXES[0] in _prompt(role, reg), (
            f"{role} 的提示词里连 formal 那一行的 owner 读数都没有了 ⇒ 判据 1 可能是靠删光换来的")

    # 白名单第二格：C 的入边那一行（L → C 是裁定给的唯一出边）
    c_text = _prompt(_INBOUND_L_ROLE, reg)
    inbound = next((ln for ln in c_text.splitlines()
                    if ln.startswith(_ALLOWED_L_PREFIXES[1])), "")
    assert inbound, f"{_INBOUND_L_ROLE} 的提示词里没有入边那一行 ⇒ 那一格是真空的"
    assert ROLE_NAME.search(inbound), f"入边那一行里没有 L（L → C 那条边消失了）：{inbound[:120]}"
    # 除 C 以外，谁的入边那一行都不许出现 L
    for role in OTHERS:
        if role == _INBOUND_L_ROLE:
            continue
        line = next((ln for ln in _prompt(role, reg).splitlines()
                     if ln.startswith(_ALLOWED_L_PREFIXES[1])), "")
        assert not ROLE_NAME.search(line), f"{role} 的入边那一行里出现了 L：{line[:120]}"

    # 反真空：判据函数在一份"加回找 L"的文本上必须报出来
    assert _l_mention_problems("E", "…断言能否形式化就找 L（形式化那一岗）…"), (
        "判据函数在旧句子上也报不出来 ⇒ 判据 1 读的不是这件事")


# ============================================================ 判据 2
def test_two_b_carries_the_six_steps_and_m_dispatches_b() -> None:
    """判据 2：B 的提示词正向写全六步；M 的提示词写着"用户要形式化就派 B"。

    改前红（逐字）：B 只有「形式化那一岗的困难只交回给你，你是它唯一的出口」——
    许可、逐条派 L、给什么、要回什么、unknown 那一档全部缺席；M 写的是「两步都在 L
    那一岗」并让 M 去调它面上根本没有的 `L.check_formal` / `formal.record`。

    反真空：六步的锚点不是"一份碰巧长这样的文本"——判据 5 把其中一步删掉再判一次。
    """
    reg = _registry()
    b_text = _prompt(ROLE_B, reg)
    missing = _missing_steps(b_text, B_STEPS)
    assert missing == [], f"B 的提示词里缺这几步：{missing}"
    assert B_ESCALATION in b_text, f"B 的提示词里没有升级那一步（{B_ESCALATION}）"
    # 派 L 的名字必须写出来（只写"形式化那一岗"，读的人不知道派谁）
    assert ROLE_NAME.search(b_text), "B 的提示词里连 L 这个名字都没有 ⇒ 它派不动任何人"

    m_text = _prompt(S.CONDUCTOR_ROLE, reg)
    name, needle = M_DISPATCH
    assert needle in m_text, f"M 的提示词里没有「{name}」这一步：许可到了没有人往下交"
    # 反真空：M 那一格必须落到 B 这条边上，而不是"派 L"
    assert "M→B" in m_text, "M 的提示词里没有写 `M→B` 这条路线"

    # 反真空：尺子在一份删掉一步的文本上必须报出来
    assert _missing_steps(b_text.replace(B_STEPS[2][1], "逐条安排"), B_STEPS), (
        "删掉「逐条派 L」这一步之后尺子仍然全绿 ⇒ 判据 2 读的不是这六步")


# ============================================================ 判据 3
def test_three_non_b_prompts_have_no_negated_formalization_orders() -> None:
    """判据 3：非 B 角色的提示词里没有"别写 Lean / 不要要形式化"这类否定式指令。

    改前红（逐字）：E「别自己写 Lean 源码」「不要主动去要形式化」、G「别把它排进你的
    写作流」、PAPER_PACK「别把它排进流水线」「这一趟不要写 Lean 源码、不要派
    `check_formal`」、以及每一份提示词里那句「要形式化就找 L，别自己写 Lean 源码」。

    为什么它归判据而不是提示词（`draft/63` §2 与 `draft/34` §4）：越权由工具面与边表
    钉住（判据 4 + `forbidden_edge`），伪造由受控拒绝与三态钉住；提示词只写"这件事该
    怎么做"。把"不许做"写进提示词，等于用一个靠模型自觉的句子去替代一条结构性判据。
    """
    reg = _registry()
    problems: dict[str, list[str]] = {}
    for role in OTHERS:
        hits = _negated_orders(_prompt(role, reg))
        if hits:
            problems[role] = hits
    assert problems == {}, f"这些角色的提示词里还有否定式指令：{problems}"
    # 正控（反真空的另一半）：正向指引确实在 —— 每一份非 B 角色的提示词都说清了
    # 形式化要不要做由谁定、结论以什么为准。
    for role in OTHERS:
        text = _prompt(role, reg)
        assert "用户" in text and "形式化" in text, (
            f"{role} 的提示词里既没有「用户」也没有「形式化」⇒ 判据 3 可能是靠删光换来的")


# ============================================================ 判据 4
def test_four_only_l_holds_formal_tools() -> None:
    """判据 4：工具面实跑 —— 除 L 以外没有角色拿得到 `formal.*`。

    改前红：这一条的正控那一半（`verify.check_formal` 曾在 E / F / G 的面上）——
    今天 `formal.*` 三件只发给 L，所以本判据守的是"以后也别漏给别人"。

    反真空：L 那一面必须真的有那三件（否则"别人没有"可能只是因为"谁都没有"），
    并且 `verify.check_formal` 不许以任何形态回到任何角色的面上。
    """
    build = build_registry()
    faces = {role: sorted(s.name for s in build.registry.for_role(role))
             for role in (*S.ROLES, S.CONDUCTOR_ROLE)}
    foreign = {role: [n for n in names if n.startswith("formal.")]
               for role, names in faces.items() if role != ROLE_L}
    foreign = {role: hits for role, hits in foreign.items() if hits}
    assert foreign == {}, f"这些角色拿得到 formal.*：{foreign}"

    for want in ("formal.formalize", "formal.check_formal", "formal.record"):
        assert want in faces[ROLE_L], f"L 的工具面里缺了 {want}：{faces[ROLE_L]}"
    assert "verify.check_formal" not in set(build.registry.names()), (
        "`verify.check_formal` 还在注册表里 —— 形式化的入口只有 L 那三件")
    for role, names in faces.items():
        assert "verify.check_formal" not in names, f"{role} 的工具面上还有 verify.check_formal"


# ============================================================ 判据 5
def test_five_a_dropping_one_step_turns_the_six_step_criterion_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 5 的前半（反真空）：把 B 六步里那一步（逐条派 L）删掉 ⇒ 判据 2 必红。

    删的是真身里的一句话再走真渲染（`ROLE_BRIEFS` 是声明层视图，渲染就照它排版），
    不是判据自己那份锚点表 —— 所以这条负控证明的是"判据 2 读的是提示词"。
    """
    reg = _registry()
    brief = AP.ROLE_BRIEFS[ROLE_B]
    needle = B_STEPS[2][1]
    assert any(needle in p for p in brief.policy), (
        f"夹具前提不成立：B 的 policy 里找不到那一步的锚点 {needle!r}")
    kept = tuple(p.replace(needle, "逐条安排") for p in brief.policy)
    assert kept != brief.policy, "夹具前提不成立：改写没有落到任何一条 policy 上"
    monkeypatch.setitem(AP.ROLE_BRIEFS, ROLE_B, dataclasses.replace(brief, policy=kept))

    text = _prompt(ROLE_B, reg)
    assert _missing_steps(text, B_STEPS) == [B_STEPS[2][0]], (
        f"删掉那一步之后尺子报的是 {_missing_steps(text, B_STEPS)} —— 它没盯住这一步")


def test_five_b_putting_l_back_in_a_partner_table_turns_criterion_one_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 5 的后半（反真空）：把 L 加回某个角色的伙伴表 ⇒ 判据 1 必红。

    两条路各加一次：① 给 A 开一条 `A → L` 的出边（伙伴表照边表现算）；
    ② 把 L 加回主控的"全体"那一栏（`_CONDUCTOR_PARTNER_ROLES`）。两条都必须当场红，
    否则判据 1 读的只是"今天的伙伴表恰好没有它"，而不是"边表说没有它"。
    """
    reg = _registry()
    # ① A → L
    patched = {role: frozenset(values) for role, values in C.ALLOWED_EDGES.items()}
    patched["A"] = frozenset(set(patched["A"]) | {ROLE_L})
    monkeypatch.setattr(C, "ALLOWED_EDGES", patched)
    problems = _l_mention_problems("A", _prompt("A", reg))
    assert problems, "把 A → L 加回边表之后判据 1 仍然全绿 ⇒ 它读的不是伙伴表"
    monkeypatch.undo()

    # ② M 的"全体"那一栏
    monkeypatch.setattr(AP, "_CONDUCTOR_PARTNER_ROLES",
                        tuple(S.ROLES))
    problems = _l_mention_problems(S.CONDUCTOR_ROLE, _prompt(S.CONDUCTOR_ROLE, reg))
    assert problems, "把 L 加回主控的伙伴表之后判据 1 仍然全绿 ⇒ 它读的不是伙伴表"
