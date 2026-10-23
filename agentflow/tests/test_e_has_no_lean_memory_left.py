# -*- coding: utf-8 -*-
"""E 的 Lean 侧记忆：最后四处的判据（2026-10-23，审计收口）。

业主 2026-10-22 晚的裁定逐字是「其它角色关于 E 的 Lean 侧记忆可以全面清除」。
`tests/test_e_lean_side_is_hard_off.py` 已经守住了「E 的工具面 / 动作面写死关闭」与
「十一格渲染里 E 与形式化不同句」，但审计又定位到四处漏网的假话 ——
它们的共同形态是：E 已经产不出 `proof` 档，而这几处仍然说 E 能签、E 有 `proof`、
E 有 `check_formal`。

四处与各自的判据（每条都带改前红，逐条写在用例 docstring 里）：

| # | 落点 | 改前逐字 | 判据 |
|---|---|---|---|
| 1 | `evidencebits.py` 的 `BIT_OWNERS["formal"]` 与 `BIT_LEDGERS["formal"]["owner"]` | 两处都是 `"E"` | 两档真渲染里 E 与形式化绑定 = 0 |
| 2 | 同上（渲染点 `agent_prompts.collab_fivebits_text`） | ``- `formal`：E 签 —— 凭据在 experiments（method='formal'）``（盘上 owner 那一格是粗体） | 开档那一行指向 L；关档不点 L 且说清产不出 proof 档 |
| 3 | `closing.py` 的 `load_bearing_without_t3` 那条 blocker | 「要么补形式化（E 的 check_formal，检查器原话进 verifier_output），」 | 那条 finding 指向 L |
| 4 | `agent_skills.py` 的 G 技能正文 | 「正文与台账逐字一致 + E 的 proof 或 V 的签名」 | G 的技能正文不含「E 的 proof」 |
| 5 | 尺子本身 | —— | 把两处 owner 改回 `"E"` ⇒ 判据 1 与 2 必红 |

## 判据 1 的「E 签」为什么只按 formal 那一行算

「E 签」这三个字本身有两个用法。`numeric` 那一行（``- `numeric`：E 签 —— …``，
盘上 owner 那一格是粗体）是真话：数值实验那一位确实归 E 签，本次改动一个字都不该动它。
所以判据 1 里
「E 签」只在 `formal` 那一行上算命中（那一行才是假话），而「E 的 proof」与
「E 的 check_formal」这两串按整份渲染算（它们没有第二个用法）。
反真空的另一半由判据 2 的正控承担：`numeric` 那一行必须仍然是 E 签 ——
否则这一条可以靠「把 E 从整张表里删掉」变绿。

## 「两档」是哪两档

与 `test_e_lean_side_is_hard_off.py` 判据 4 同一个口径：`AGENTFLOW_LEAN_ENABLED` 的
开 / 关两档（`leanscope` 每次现读，提示词层只给读数加了缓存 ⇒ 换档后要
`reset_toolchain_readings()`）。两档都按生产形态给参：`task` / `workspace_root` /
`toolchain_facts` / `toolchain_formal` 四格都传，因为生产路径上这四格从来不是空的，
而不传时提示词走的是「没有读到读数」那一支 —— 那一支不是生产形态。

两档的格数不同（开档 11、关档 10 = 21）：L 在关档不存在（`leanscope.is_hidden`
⇒ `role_prompt_registry` 第一句就抛 `RoleHidden`），所以关档少它自己那一格。这也决定了
判据 2 要按档判两套答案：开档那一行必须指 L，关档那一行一个字都不许点 L（业主
2026-10-22「Lean 没开时隔绝 L」）—— 关档那一半的改法落在
`specs/e.py::NO_LEAN_REPLACEMENTS` 的两条新条目上（本批新加，`old` 在开档逐字出现，
只在关档生效 ⇒ 开档摘要不受影响）。

## 判据 3 为什么直接调产生它的函数

收工门（`closing_gate`）那一趟要建工作区、建 store、跑十几格检查，慢且与这一句话
无关。`_check_load_bearing` 是唯一产生这条 finding 的函数，直接喂一份最小台账
（一条没有 T3 背书的 `evidence_kind="proof"` 断言）就能拿到 finding 原文 ——
判据读的是那段文本本身，不是别人的转述。

## 判据 5 为什么要把两处一起改回去

`agent_prompts.collab_fivebits_text` 取 owner 的顺序是
`BIT_LEDGERS[bit]["owner"]` 先、`BIT_OWNERS[bit]` 后（`agent_prompts.py:2848`），
所以只翻 `BIT_OWNERS["formal"]` 那一格不会让渲染变（用例最后一段把这件事也钉住：
它是「这两格不是冗余」的读数）。改前那一版是两处都为 `"E"`，所以反真空把两处一起
改回去 —— 那才是「改前」这个状态本身。

## 零模型

全部用例只读本地代码与本地开关：不起模型、不花一分钱、不写工作区以外的任何东西。
"""
from __future__ import annotations

import os
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow import closing as CLG
from agentflow import evidencebits as EB
from agentflow import leanscope as LS
from agentflow import schema as S
from agentflow import settings as SET
from agentflow.tools import build_registry


def _roles() -> tuple[str, ...]:
    """十一个角色：`schema.ROLES` 加主控（与 `test_e_lean_side_is_hard_off` 同一口径）。"""
    return tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)


#: 两档 = Lean 开关的开 / 关（与 `test_e_lean_side_is_hard_off.py` 判据 4 同一个口径）。
_TIERS: tuple[tuple[str, bool], ...] = (("开关开", True), ("开关关", False))

#: 生产形态的四格入参（固定值：判据必须是确定性的，且不许读到这台机器的工具链）。
_TASK = "把这条链路走一遍"
_ROOT = "D:/x"
_FACTS = ("这台机器上的证明工具链（现算读数，不是记忆）：\n"
          "- 检查器：lean 4.7.0（判据夹具，与机器无关）")
_FORMAL = ("你这一岗怎么写形式化（由上面那份读数现算）：\n"
           "- （判据夹具：这一次按自足文件写）")

#: formal 那一行在渲染里的形状（`collab_fivebits_text` 的排版：`- 位名：谁 签`）。
_FORMAL_PREFIX = "- `formal`："
#: 改前那一行上写着的签名记号（假话的形态）。
_E_SIGN = "**E** 签"
#: 改后那一行必须写着的签名记号。
_L_SIGN = "**L** 签"

#: 判据 1 里按整份渲染算的两串（它们没有第二个用法）。
_E_LEAN_MARKS: tuple[str, ...] = ("E 的 proof", "E 的 check_formal")

#: 角色名 `E` 的记号（与 `test_e_lean_side_is_hard_off.py` 同一条：ASCII 词边界）。
E_TOKEN = re.compile(r"(?<![A-Za-z0-9_])E(?![A-Za-z0-9_])")
#: 角色名 `L` 的记号（关档判据用它：L 在这一档不存在 ⇒ 那一行一个字都不许点到它）。
L_TOKEN = re.compile(r"(?<![A-Za-z0-9_])L(?![A-Za-z0-9_])")


def _registry():
    """一张不带工作区的注册表（这些用例不碰文件系统）。"""
    return build_registry().registry


def _set_switch(on: bool) -> None:
    """改 Lean 开关并清掉提示词层的读数缓存（`leanscope` 自己不缓存）。"""
    os.environ[SET.ENV_LEAN_ENABLED] = "1" if on else "0"
    AP.reset_toolchain_readings()


def _render(role: str, registry) -> str:
    """某个角色这一次的提示词（生产形态：四格入参都传）。"""
    return AP.system_prompt(role, registry=registry, task=_TASK, workspace_root=_ROOT,
                            toolchain_facts=_FACTS, toolchain_formal=_FORMAL)


def _render_tier(registry, on: bool) -> dict[str, str]:
    """这一档下能渲染的每一格（开档 11 格、关档 10 格 —— L 在关档不存在）。"""
    _set_switch(on)
    return {role: _render(role, registry) for role in LS.visible_roles(_roles())}


@pytest.fixture()
def grid():
    """两档下的全部渲染（开档 11 格 + 关档 10 格 = 21 份）。

    关档少的那一格是 L 自己：`leanscope.is_hidden("L")` 在关档为真，那一个角色这一档
    不存在（`role_prompt_registry` 的第一句就抛 `RoleHidden`），所以「两档真渲染」的
    总数是 21 而不是 22。

    出夹具时把开关与缓存放回原值：本文件会真的改环境变量（判据 4 那一档必须真改，
    `leanscope` 每次现读它），漏还原会让后面所有文件的渲染都跑在「关」那一档。
    """
    before = os.environ.get(SET.ENV_LEAN_ENABLED)
    try:
        reg = _registry()
        return {tier: _render_tier(reg, on) for tier, on in _TIERS}
    finally:
        if before is None:
            os.environ.pop(SET.ENV_LEAN_ENABLED, None)
        else:
            os.environ[SET.ENV_LEAN_ENABLED] = before
        AP.reset_toolchain_readings()


def _formal_line(text: str) -> str | None:
    """渲染文本里 `formal` 那一行（没有 ⇒ `None`：判据无从落地，按红处理）。"""
    for line in text.splitlines():
        if line.startswith(_FORMAL_PREFIX):
            return line
    return None


def _criterion_1_problems(text: str, lean_on: bool = True) -> list[str]:
    """判据 1 的尺子：这一份渲染里还把 E 与 Lean 侧绑在一起的记号（空 = 干净）。

    `lean_on` 这一格不用（两档都要 0）：关档那两处已经被
    `specs/e.py::NO_LEAN_REPLACEMENTS` 改写成不点任何角色的写法，所以三串在两档都必须是 0。
    参数照判据 2 的形状留着，是为了让 `_grid_problems` 用同一种调用方式喂两把尺子。
    """
    del lean_on
    bad = [f"还写着「{mark}」" for mark in _E_LEAN_MARKS if mark in text]
    line = _formal_line(text)
    if line is not None and _E_SIGN in line:
        bad.append(f"formal 那一行还写着「E 签」：{line}")
    return bad


def _criterion_2_problems(text: str, lean_on: bool = True) -> list[str]:
    """判据 2 的尺子：formal 那一行两档各有各的正确答案（空 = 干净）。

    两档的正确答案不同，因为 L 在两档的存在性不同（`leanscope.is_hidden`）：

    - 开档：L 是这一档的角色 ⇒ 这一行必须写着「`formal`：L 签」（第 4 位的凭据
      由 `formal.record` 落，`recorded_by="agent-L"`），且不许点 E；
    - 关档：L 在这一档不存在（业主 2026-10-22「Lean 没开时隔绝 L」）⇒ 这一行
      必须不点 L，并说清"这一档产不出 proof 档"（否则读者分不清"这一位没做"与
      "这一档做不了"）。

    两档共同的一条：不许点 E（E 的 formal 那一支写死关闭，回 `formal_moved_to_l`）。
    """
    line = _formal_line(text)
    if line is None:
        return [f"渲染里没有以 {_FORMAL_PREFIX!r} 开头的那一行（判据无从落地）"]
    bad: list[str] = []
    if lean_on:
        if _L_SIGN not in line:
            bad.append(f"formal 那一行没有指向 L（缺「`formal`：**L** 签」）：{line}")
    else:
        if L_TOKEN.search(line):
            bad.append(f"关档 formal 那一行还点着 L（这一档没有 L 这个角色）：{line}")
        if "产不出" not in line or "proof" not in line:
            bad.append(f"关档 formal 那一行没有说清「这一档产不出 proof 档」：{line}")
    if E_TOKEN.search(line):
        bad.append(f"formal 那一行还点着 E：{line}")
    return bad


#: 档名 ⇒ 开关是否开着（`_TIERS` 的现算视图；判据 2 要按档判两套答案）。
_TIER_ON: dict[str, bool] = dict(_TIERS)


def _grid_problems(grid, criterion) -> list[str]:
    """对整张（两档 × 各自可见的每一格）渲染跑一把尺子，返回逐条定位过的问题。"""
    out: list[str] = []
    for tier, renders in grid.items():
        for role, text in renders.items():
            assert len(text) > 3000, (
                f"[{tier}] {role} 的渲染只有 {len(text)} 字符 ⇒ 这一条是真空的")
            out += [f"[{tier}] {role}：{p}" for p in criterion(text, _TIER_ON[tier])]
    return out


# ============================================================ 1. 渲染里没有假话
def test_1_no_cell_ties_e_to_the_lean_side(grid) -> None:
    """判据 1：两档真渲染（开档 11 格 + 关档 10 格 = 21 份）里，「E 签」（formal 那一行）
    /「E 的 proof」/「E 的 check_formal」命中 = 0。

    改前红（2026-10-23 实测，逐字，合计 23 处）：`evidencebits.BIT_OWNERS["formal"]` 与
    `BIT_LEDGERS["formal"]["owner"]` 都是 `"E"`，而渲染点
    `agent_prompts.collab_fivebits_text` 把每一行印进全部十一个角色的提示词 ⇒
    21 份渲染里每一份都有这一行（owner 那一格在盘上是粗体，这里按纯文本抄）：

        - `formal`：E 签 —— 凭据在 experiments（method='formal'）

    （连 L 自己那一格也在说「formal 是 E 签的」。）另外 `specs/m.py:256` 那句
    「正文与台账逐字一致 + E 的 proof 或 V 的签名」进 M 那一格 ⇒ 「E 的 proof」
    再命中 2 处（M 在两档里各一份）。21 + 2 = 23。

    判据 5 用同一把尺子（`_criterion_1_problems`）证明它不是真空的。
    """
    problems = _grid_problems(grid, _criterion_1_problems)
    assert problems == [], (
        f"还有 {len(problems)} 处把 E 与 Lean 侧绑在一起（两档真渲染里）：\n  "
        + "\n  ".join(problems[:40]))


# ============================================================ 2. formal 那一行归 L
def test_2_the_formal_bit_line_points_at_l(grid) -> None:
    """判据 2：`formal` 那一行在两档各有各的正确答案（owner 那一格在盘上是粗体）。

    - 开档：必须写着「`formal`：L 签」且不点 E。两处真身（`BIT_OWNERS` /
      `BIT_LEDGERS`）也必须是 L。
    - 关档：L 在这一档不存在（业主 2026-10-22「Lean 没开时隔绝 L」）⇒ 那一行一个字都
      不许点到 L，并说清"这一档产不出 proof 档"。改法落在
      `specs/e.py::NO_LEAN_REPLACEMENTS`（本批新加的两条之一）。

    改前红（2026-10-23 实测，逐字）：那份渲染里 formal 那一行是
    ``- `formal`：E 签 —— 凭据在 experiments（method='formal'）``，
    既没有「L 签」也点着 E；两处真身都是 `"E"`。

    为什么要两处真身一起判：`verify.py` 第 13 段按 `BIT_LEDGERS` 派判据，而
    `agent_prompts.py:2848` 取 owner 时先读 `BIT_LEDGERS` 再读 `BIT_OWNERS` ——
    两处不一致时渲染只跟着前者变，而"位表说归谁"这件事会出现两个答案。

    正控（反真空的另一半）：`numeric` 那一行必须仍然是「E 签」（两档都是）。否则这一条
    可以靠「把 E 从整张位表里删掉」变绿 —— 而那会同时抹掉一句真话。
    """
    problems = _grid_problems(grid, _criterion_2_problems)
    assert problems == [], (
        f"formal 那一行没有按档说对该说的话：\n  " + "\n  ".join(problems[:40]))

    assert EB.BIT_OWNERS.get("formal") == "L", (
        f"BIT_OWNERS['formal'] 应当是 'L'，实际 {EB.BIT_OWNERS.get('formal')!r}")
    assert EB.BIT_LEDGERS["formal"].get("owner") == "L", (
        f"BIT_LEDGERS['formal']['owner'] 应当是 'L'，"
        f"实际 {EB.BIT_LEDGERS['formal'].get('owner')!r}")

    # 正控：numeric 那一格还是 E 签（判据 1 不是在判「E 不许出现在位表里」）
    for tier, renders in grid.items():
        for role, text in renders.items():
            assert f"- `numeric`：{_E_SIGN}" in text, (
                f"[{tier}] {role}：`numeric` 那一行不再是 E 签 ⇒ 这一条把真话也一起删了："
                f"{text[:200]}")


# ============================================================ 3. 收工门那条 blocker
class _Ledger:
    """收工门要的最小台账（只实现 `_check_load_bearing` 真读的那四张表）。"""

    def __init__(self, rows: dict[str, list[dict]]) -> None:
        self._rows = rows

    def rows(self, table: str) -> list[dict]:
        return list(self._rows.get(table, []))


def _load_bearing_finding() -> CLG.Finding:
    """真跑一次 `_check_load_bearing`，取它产生的那条 blocker 原文。

    台账的形状：一条正文断言 `evidence_kind="proof"` 而 `citations` 为空 ⇒
    它没有 T3 背书 ⇒ 走 `bad` 那一支，finding 的 `code` 是 `load_bearing_without_t3`。
    """
    store = _Ledger({
        "documents": [{
            "doc_id": "doc:000001",
            "claims": [{"claim_id": "c1", "evidence_kind": "proof",
                        "text": "主定理成立（判据夹具）", "citations": []}],
        }],
        "experiments": [], "dependencies": [], "statements": [],
    })
    rep = CLG.ClosingReport()
    CLG._check_load_bearing(rep, store)
    hits = [f for f in rep.findings if f.code == "load_bearing_without_t3"]
    assert len(hits) == 1, (
        f"这一趟应当恰好产生一条 load_bearing_without_t3，实际 {[f.code for f in rep.findings]}")
    assert rep.status.get("load_bearing") == "fail", rep.status
    return hits[0]


def test_3_the_closing_finding_points_at_l(monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 3：收工门那条 blocker 的正文指向 L，并写明 E 的 Lean 侧已停用。

    改前红（2026-10-23 实测，逐字，`closing.py:4057` 那一段拼出来的 finding）：

        有 1 条承重结论（正文里 evidence_kind='proof'）没有 T3 背书：doc:000001#c1
        （主定理成立（判据夹具））。要么补形式化（E 的 check_formal，检查器原话进
        verifier_output），要么如实降档成 cross_check/heuristic 并改稿件的措辞
        （§10.2：措辞不许出现「已证明/定理/必然」）

    这条 finding 经 `conductor.closing` 的回执进 M 的上下文 ⇒ 它会照着「找 E 做
    check_formal」去派活，而 E 那一支现在一律回受控拒绝 `formal_moved_to_l`。

    反真空：这句话仍然说清「要么补形式化、要么降档」两条出路（不是删成一句空话）。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    AP.reset_toolchain_readings()
    finding = _load_bearing_finding()
    detail = finding.detail

    for mark in _E_LEAN_MARKS:
        assert mark not in detail, (
            f"这条 finding 还写着「{mark}」⇒ 它会把 M 指去一个不存在的入口：{detail}")
    assert "formal.check_formal" in detail or "formal.formalize" in detail, (
        f"这条 finding 没有指向 L 的入口（`formal.check_formal` / `formal.formalize`）：{detail}")
    assert "formal_moved_to_l" in detail, (
        f"这条 finding 没有写明 E 的 Lean 侧已停用（受控理由码 `formal_moved_to_l`）：{detail}")
    # 反真空：两条出路都还在
    assert "降档" in detail and "cross_check" in detail, (
        f"这条 finding 的「要么降档」那一条出路被删掉了：{detail}")


# ============================================================ 4. G 的技能正文
#: 判据 4 要的那句话的锚点（技能正文里 H 的采信规则那一句）。
_H_RULE_ANCHOR = "正文与台账逐字一致"


def test_4_g_skill_body_does_not_say_e_proof() -> None:
    """判据 4：G 的技能正文里不含「E 的 proof」（它会落盘到工作区 `skills/` 供 `fs.read`）。

    改前红（2026-10-23 实测，逐字，`agent_skills.py:2199`；`H` 那一格在盘上是粗体，
    这里按纯文本抄）：

        - 稿件级审校由 H 做（`H.review`），它的判据是"正文与台账逐字一致 +
          E 的 proof 或 V 的签名"。

    为什么这句是假话：E 这一岗从 2026-10-23 晚起没有 Lean 侧（动作表里没有 `check_formal`，
    `method="formal"` 以理由码 `formal_not_in_e` 拒绝），`proof` 档只有 L 能签。G 照着这句写稿，
    就会把一条 `cross_check` 当 `proof` 引用 —— 而收工门（判据 3 那条）会因此拦下来。

    反真空：那句话仍然说清 H 的采信规则（正文与台账逐字一致 + 形式化或 V 的签名），
    不是把整句删掉。
    """
    rows = AS.skills_for("G")
    assert rows, "G 名下一条 skill 都没有 ⇒ 这一条是真空的"
    offenders = [f"{s.slug}：{mark}" for s in rows for mark in _E_LEAN_MARKS if mark in s.body]
    assert offenders == [], (
        "G 的技能正文里还有 E 的 proof / check_formal（它会落盘供 fs.read）：\n  "
        + "\n  ".join(offenders))

    anchored = [s for s in rows if _H_RULE_ANCHOR in s.body]
    assert len(anchored) == 1, (
        f"写着 H 那条采信规则的技能应当恰好一条，实际 {[s.slug for s in anchored]}")
    body = anchored[0].body
    assert "V 的签名" in body, f"那一句里的「V 的签名」被删掉了：{body[:200]}"
    assert "L" in body and "形式化" in body, (
        f"那一句没有指向 L 的形式化：{body[:200]}")


# ============================================================ 5. 反真空
def test_5_restoring_the_old_owner_turns_1_and_2_red(
        grid, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 5：把两处 owner 改回 `"E"`（= 改前那一版）⇒ 判据 1 与 2 必红。

    为什么必须有一条这样的负控：判据 1 与 2 判的是"渲染里某个字符串在不在了"。
    如果那段渲染根本没被走到（例如五元位那一段没载入、或尺子读错了行），它们照样会绿；
    只有「把真身改回改前那一版之后它变红」才能证明那把尺子真的量在这条路上。

    为什么两处一起改回去（而不是只改 `BIT_OWNERS`）：渲染点
    `agent_prompts.py:2848` 先读 `BIT_LEDGERS[bit]["owner"]`、后读 `BIT_OWNERS[bit]`，
    所以只翻前者不会让渲染变 —— 用例最后一段把这件事单独钉住（它是「这两格不是冗余」
    的读数，也是下一次有人想"只改一处"时的提示）。

    这一条在开档上判（`_set_switch(True)`）：改前那一版在开档印的是「E 签」，
    那一档的正确答案是「L 签」⇒ 两把尺子都能看见它变红。
    """
    # 正控：现在的真身是 L ⇒ 同一把尺子是绿的
    reg = _registry()
    _set_switch(True)
    try:
        now = _render("M", reg)
        assert _criterion_1_problems(now, lean_on=True) == [], _criterion_1_problems(now)
        assert _criterion_2_problems(now, lean_on=True) == [], _criterion_2_problems(now)

        # 改前那一版：两处 owner 都是 E
        with monkeypatch.context() as mp:
            mp.setitem(EB.BIT_OWNERS, "formal", "E")
            mp.setitem(EB.BIT_LEDGERS["formal"], "owner", "E")
            old = _render("M", reg)
            assert _criterion_1_problems(old, lean_on=True), (
                "把 owner 改回 E 之后判据 1 居然还是绿的 ⇒ 那把尺子是真空的")
            assert _criterion_2_problems(old, lean_on=True), (
                "把 owner 改回 E 之后判据 2 居然还是绿的 ⇒ 那把尺子是真空的")

        # 只翻 BIT_OWNERS 那一半：渲染点读的是 BIT_LEDGERS 那一栏 ⇒ 判据 1 不会红。
        # 这一条红了说明渲染点的取数顺序变了 —— 那时把上一段收成只翻 BIT_OWNERS 即可。
        with monkeypatch.context() as mp:
            mp.setitem(EB.BIT_OWNERS, "formal", "E")
            half = _render("M", reg)
            assert _criterion_1_problems(half, lean_on=True) == [], (
                "只翻 BIT_OWNERS 就让判据 1 红了 ⇒ 渲染点改成先读 BIT_OWNERS 了："
                "这是好事，把上面那段反真空收成只翻 BIT_OWNERS 一处即可")
    finally:
        AP.reset_toolchain_readings()
