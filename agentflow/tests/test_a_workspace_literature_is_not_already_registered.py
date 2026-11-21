# -*- coding: utf-8 -*-
"""判据（SEEDDOC，2026-11-21）：工作区里已有的文献，A 必须自己走「发现 → 建候选 → 判收」这条链。

## 改前为什么红（下一趟真机会踩到）

SEEDREH 把这条链在彩排里走通了（`temp/seedreh/SEEDREH-REPORT.md`：`search.ingest_local`
`dry_run=True` 发现 → `lit.stage_add` 建候选 → `text.extract` + `fs.read` →
`lit.admit(availability=readable)` → `lit.admit_all`），但 A 的可见面里一个字都没写
这条路：`specs/a.py` 的 policy 讲的是检索口径，`agent_skills.py` 的 A 手册只把
`A.ingest_local` 写成「收完 `literature` 会多出对应的行」（那是非 dry 档的登记语义，
也就是绕过判收的那一条）。下一趟真机把几十份历史 PDF 投进工作区 `library/`
（`SEED-README.md` 明说「未入库、未判收」）时，A 只有两种省事的读法可抄：把发现读数
当已入库、或者用非 dry 档一次性登记 —— 两种都不报错。

## 判据（断言顺序，不是数关键词）

| # | 判据 | 反真空 |
|---|---|---|
| a | A 的 `system_prompt` 里那条政策的整行，按 发现 → 建候选 → 抽读 → 判收 → 提交 的次序出现 | 把含某一环的那一句抠掉 ⇒ a 必红（逐环各打一次） |
| b | A 现读的那份手册的 §0.2，同样按这个次序，且写明没有正文时的受控理由码 | 把手册正文换成探针 ⇒ b 必红 |
| c | 前置提示词里唯一的手册入口（索引那一行）点到这条路，且只指路（步骤细节不抄进索引） | 把 summary 换成探针 ⇒ c 必红 |

顺序那一条另有一条纯函数负控（把「建候选」挪到「发现」之前 ⇒ 必须报顺序），证明它
真的在比位置，而不是「五个词都在」就放行。
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow.tools import build_registry

#: 渲染提示词用的固定任务与工作区（与本目录其余提示词判据同一组缺省值）。
TASK = "把这条链路走一遍"
ROOT = "D:/x"

#: 政策的标题：判据按它从渲染产物里取出「那一段」，只在这一段里比顺序。
#: 为什么必须只比这一段：同一份提示词的「手段：可改 N 件」那一行会按字母序列出
#: `lit.admit` / `lit.admit_all` / `lit.stage_add` / `text.extract` —— 拿整份提示词
#: 比顺序，比的是工具清单的字母序，不是这条链的顺序。
_POLICY_HEAD = "工作区里已有的文献不是「已入库」"

#: 手册里那一节的标题（正文才是这条路唯一的真身）。
_MANUAL_HEAD = "### 0.2 工作区里已有的文献不是「已入库」"

#: 手册那一条的 slug（索引行按路径指到它）。
_SKILL_SLUG = "找文献-换招法而不是换说法"

#: 这一条链的五环。正则而不是裸串：`lit.admit` 是 `lit.admit_all` 的前缀，裸串会把
#: 两环读成同一个位置 —— 那样「判收」与「提交」的顺序就永远成立（假绿）。
_CHAIN: tuple[tuple[str, str], ...] = (
    ("发现", r"dry_run\s*=\s*True"),
    ("建候选", r"lit\.stage_add"),
    ("抽读", r"text\.extract"),
    ("判收", r"lit\.admit(?!_all)"),
    ("提交", r"lit\.admit_all"),
)

#: 没有正文时那几个受控理由码（「不许当已收编」的机器读数，逐码都要写出来）。
_NO_BODY_CODES: tuple[str, ...] = (
    "no_read_evidence",
    "no_fulltext",
    "extract_failed",
    "metadata_only",
)


def _a_prompt() -> str:
    """A 这一次真的会读到的 system prompt。"""
    return AP.system_prompt("A", registry=build_registry().registry,
                            task=TASK, workspace_root=ROOT)


def _policy_line(prompt: str) -> str:
    """渲染产物里那条政策的整行（找不到 = 空串，判据会点名）。"""
    for line in prompt.splitlines():
        if _POLICY_HEAD in line:
            return line.strip()
    return ""


def _a_skill() -> AS.Skill:
    """A 目录里那条检索方法手册（slug 是稳定标识，判据按它取）。"""
    for skill in AS.skills_for("A"):
        if skill.slug == _SKILL_SLUG:
            return skill
    raise AssertionError(f"A 的 skills 里没有 `{_SKILL_SLUG}`（判据失去对象）")


def _a_manual() -> str:
    """A 用 `fs.read` 读到的那份手册的全文（头部 + 正文）。"""
    return AS._render("A", _a_skill())


def _manual_section() -> str:
    """手册里 §0.2 那一节（到下一个二级标题为止）。

    只在这一节里比顺序：手册的头部「会用到的工具」那一行按声明顺序列出 `text.extract`
    与 `lit.*`（`text.extract` 在 `lit.stage_add` 之前），整份手册比顺序会把那一行
    的书写顺序当成链的顺序。§八 / §九 讲的是判收链的后半段，它们与 §0.2 是同一条链的
    两处入口，但顺序断言只需要（也只应该）落在这一节里。
    """
    text = _a_manual()
    start = text.find(_MANUAL_HEAD)
    if start < 0:
        return ""
    rest = text[start + len(_MANUAL_HEAD):]
    nxt = rest.find("\n## ")
    return _MANUAL_HEAD + (rest if nxt < 0 else rest[:nxt])


def _chain_positions(text: str) -> list[tuple[str, int]]:
    """五环各自第一次出现的位置（-1 = 这一环没写）。"""
    return [(name, (m.start() if (m := re.search(pattern, text)) else -1))
            for name, pattern in _CHAIN]


def _chain_problems(text: str) -> list[str]:
    """这条链的问题（空 = 五环都在、且按 发现 → 建候选 → 抽读 → 判收 → 提交 的次序）。

    逐环返回人话，不返回布尔：红的时候要能说清「缺哪一环」还是「哪两环换了位置」——
    这两种的处置方向不同（补一句 / 改顺序）。
    """
    got = _chain_positions(text)
    missing = [f"缺「{name}」（`{pattern}`）这一环" for (name, pos), pattern
               in zip(got, (p for _n, p in _CHAIN)) if pos < 0]
    if missing:
        return missing
    out: list[str] = []
    for (prev_name, prev), (name, pos) in zip(got, got[1:]):
        if pos <= prev:
            out.append(f"顺序不对：「{name}」出现在「{prev_name}」之前（或同一处）")
    return out


def _missing_no_body_codes(text: str) -> list[str]:
    """没写出来的受控理由码（「没有正文的不许当已收编」那一格）。"""
    return [code for code in _NO_BODY_CODES if code not in text]


# ---------------------------------------------------------------- a 职责面


def test_a_prompt_carries_the_chain_in_order() -> None:
    """a. A 的职责面里，那条政策按 发现 → 建候选 → 抽读 → 判收 → 提交 的次序。"""
    prompt = _a_prompt()
    line = _policy_line(prompt)
    assert line, (
        "A 的渲染提示词里读不到那条政策（工作区里已有的文献不是已入库）⇒ "
        "下一趟真机 A 看不到这条路，只能把种子当已入库")
    assert _chain_problems(line) == [], (
        "那条政策里的链没有按顺序写全：" + "；".join(_chain_problems(line)))
    # 反真空：五环真的各在那一行里（不是五个词恰好分散在同一行的两段里被读成有序）。
    positions = [pos for _name, pos in _chain_positions(line)]
    assert len(set(positions)) == len(_CHAIN), positions
    assert _missing_no_body_codes(line) == [], (
        "那条政策没写清没有正文时的受控理由码：缺 " + "、".join(_missing_no_body_codes(line)))
    assert "不许当已收编" in line, "那条政策没写「没有正文的不许当已收编」这句禁令"


def _drop_sentences(text: str, needle: str) -> str:
    """把含 needle 的那一整句抠掉（按句号 / 分号切，不靠固定序号）。"""
    parts = re.split(r"(?<=[。；])", text)
    return "".join(part for part in parts if needle not in part)


@pytest.mark.parametrize("needle", ["dry_run=True", "lit.stage_add", "lit.admit_all"])
def test_a_anti_vacuum_removing_any_step_makes_the_prompt_criterion_red(
        needle: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """a 的反真空：把链上任意一环的那一句抠掉 ⇒ 同一个检查必须点名报缺。"""
    brief = AP.ROLE_BRIEFS["A"]
    assert _chain_problems(_policy_line(_a_prompt())) == [], "夹具前提：改后这一面应当先绿"

    stripped = dataclasses.replace(
        brief,
        policy=tuple(_drop_sentences(str(item), needle) for item in brief.policy))
    assert stripped.policy != brief.policy, (
        f"夹具前提：`{needle}` 确实长在 policy 上（否则这条负控在打空气）")
    monkeypatch.setitem(AP.ROLE_BRIEFS, "A", stripped)
    problems = _chain_problems(_policy_line(_a_prompt()))
    assert problems, f"抠掉含 `{needle}` 的那一句之后判据仍绿 —— a 是橡皮图章"
    assert any("缺" in one for one in problems), problems


def test_the_order_check_bites_on_a_reordering() -> None:
    """a 的另一半（纯函数负控）：把「建候选」挪到「发现」之前 ⇒ 必须报顺序。

    没有这一条，「五环都在」与「五环按次序」这两种说法在读数上分不开 —— 而这条判据
    要的正是后者（顺序错了，模型会先建候选、再发现，候选的 url 就没有出处）。
    """
    ordered = ("① 发现 `search.ingest_local(dry_run=True)`；② 建候选 `lit.stage_add`；"
               "③ 判收 `text.extract` → `lit.admit` → `lit.admit_all`")
    assert _chain_problems(ordered) == [], _chain_problems(ordered)
    swapped = ("① 建候选 `lit.stage_add`；② 发现 `search.ingest_local(dry_run=True)`；"
               "③ 判收 `text.extract` → `lit.admit` → `lit.admit_all`")
    problems = _chain_problems(swapped)
    assert problems, "两环换了位置，顺序检查却放过了 —— 它只在对关键词"
    assert any("顺序不对" in one for one in problems), problems


# ---------------------------------------------------------------- b 手册正文


def test_b_manual_section_carries_the_chain_in_order() -> None:
    """b. A 现读的那份手册的 §0.2 里，五环按次序写全（它真的会 `fs.read` 它）。"""
    section = _manual_section()
    assert section, (
        f"A 的手册里没有 `{_MANUAL_HEAD}` 这一节 ⇒ 前置提示词说了、现读的手册没说，"
        "两处一漂模型只会照一处做")
    assert _chain_problems(section) == [], (
        "手册 §0.2 里的链没有按顺序写全：" + "；".join(_chain_problems(section)))
    assert _missing_no_body_codes(section) == [], (
        "手册 §0.2 没写清没有正文时的受控理由码：缺 " + "、".join(_missing_no_body_codes(section)))
    # 两步禁令也要落在正文里（只在职责面写着，手册里读不到就等于没有操作口径）。
    assert "不许当已收编" in section, section[:200]
    assert "跳过判收" in section, "手册没写「非 dry 档跳过判收」这条兜底路的代价"


def test_b_anti_vacuum_removing_the_manual_body_makes_the_criterion_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """b 的反真空：把手册正文与 summary 换成探针 ⇒ 同一检查必须点名报缺。"""
    skills = AS.CATALOG["A"]
    victim = _a_skill()
    assert _chain_problems(_manual_section()) == [], "夹具前提：改后这一面应当先绿"

    probe = dataclasses.replace(victim, body="（探针：正文被清空）",
                                summary="（探针：一句话被清空）",
                                when="（探针：什么时候读被清空）")
    monkeypatch.setitem(
        AS.CATALOG, "A",
        tuple(probe if s.slug == victim.slug else s for s in skills))
    assert _manual_section() == "", "把正文换掉之后手册里仍读得到 §0.2 —— b 是橡皮图章"


# ---------------------------------------------------------------- c 索引行


def _index_row() -> str:
    """前置提示词里那条 skill 的索引行（唯一的手册入口）。"""
    for line in AS.index_block("A").splitlines():
        if f"{_SKILL_SLUG}.md" in line:
            return line
    return ""


def test_c_the_index_row_names_the_path_and_points_at_the_manual() -> None:
    """c. 索引行点到这条路，且只指路（步骤细节不抄进索引 —— 真身只有手册那一份）。"""
    row = _index_row()
    assert row, f"索引里没有 `{_SKILL_SLUG}.md` 那一行（A 看不到手册入口）"
    assert "dry_run" in row and "lit.stage_add" in row, (
        "索引行没点到「发现 → 建候选」这条入口 ⇒ 手册能被跳过，跳过后模型不知道"
        "工作区里的文献要先发现、再建候选")
    assert "§0.2" in row, "索引行没有指到手册 §0.2（正文才是这条路唯一的真身）"
    # 只指路：步骤细节（entries= / cand: 槽位写法）不抄进索引。
    assert "entries=" not in row and "cand:" not in row, (
        "索引行把手册的步骤细节抄进去了 ⇒ 同一条路有两份抄本，改一处就会漂")


def test_c_anti_vacuum_the_index_negative_control_bites(monkeypatch: pytest.MonkeyPatch) -> None:
    """c 的反真空：把那条 skill 的 summary / when 清空 ⇒ 索引判据必红。"""
    skills = AS.CATALOG["A"]
    victim = _a_skill()
    assert "lit.stage_add" in _index_row()

    probe = dataclasses.replace(victim, summary="（探针）", when="（探针）")
    monkeypatch.setitem(
        AS.CATALOG, "A",
        tuple(probe if s.slug == victim.slug else s for s in skills))
    row = _index_row()
    assert "lit.stage_add" not in row, "清空 summary 之后索引仍带着那条入口 —— c 是橡皮图章"
    assert "§0.2" not in row, "清空 summary 之后索引仍指到手册 —— c 是橡皮图章"
