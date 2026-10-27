"""「交差」那条规则在十一个角色的规格里各写一遍 —— 判据是它们逐字相同。

## 为什么要一条判据（真问题）

「同事交差/回话就挂机」「既无计时而手头也没活 ⇒ 按交差处理」这条规则写在
`specs/` 的十一个角色文件里（`a b c d e f g h l m v`），而它同时是可执行的：
`clock.record_handoff` 落账、`conductor.agent_state` 认它、`agent_loop` 据此决定
这一拍还调不调模型。漂开时没有任何东西会报错 —— 提示词里少一个字，模型就会
把"还有计时的活"当成"没事可做"，而盘上读数是"它自己交差了"。这正是本项目最忌的
形态：口径两份，漂移静默。

## 为什么是十份（不是一份）

因为它们各自进不同角色的提示词：`specs/__init__.py` 的 `builtin_specs()` 按角色
取那一份，运行期一条提示词只装它自己角色那一份 —— 角色之间无法互引，所以
"只写一处、其余引用"在运行时做不到（那需要一个跨角色可读的共同段落，而提示词
是按角色拼的）。

## 为什么判据是"逐字相同"而不是"合并成一处"

合并要动 `specs/*` 十个文件 ⇒ 改十个角色的提示词 ⇒ 抬版本 + 重冻快照 + 缓存作废。
而真正的风险（漂一个字符没人报）用一条判据就关掉了，提示词一个字不动。

## 三处代码副本

同一件事在代码侧也有三处注释复述（`clock.py` 的 `wait_any_reading` 口径、
`conductor.py` 的 `agent_state` 第七档、`agent_loop.py` 的交差分支）。那三处引的是
业主原话，不是上面那一段散文（把 1 KB 散文再抄三份进代码不是改进）。所以这里
钉两件事：① 十份散文逐字相同；② 三处代码副本引的那句业主原话逐字相同
（按"折叠空白"比：注释会换行，换行不是漂移）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SPECS_DIR = Path(__file__).resolve().parents[1] / "src" / "agentflow" / "specs"
SRC_DIR = SPECS_DIR.parent

#: 写着那条规则的十一个角色规格文件名。
#: `m.py` 也在里面：它的头一句不一样（M 是"等下属的时候用挂机"），尾巴逐字相同 ——
#: 所以下面分成"共用尾巴的十一个"与"共用整段的十个"两条。
SPEC_ROLES: tuple[str, ...] = ("a", "b", "c", "d", "e", "f", "g", "h", "l", "m", "v")
#: 整段（头 + 尾）逐字相同的十个；`m` 不在里面，理由见上。
FULL_COPY_ROLES: tuple[str, ...] = ("a", "b", "c", "d", "e", "f", "g", "h", "l", "v")

#: 整段的起止标记（取包含它们的那几句，不取整段的散文边界 —— 边界会随排版动）。
RULE_HEAD = "等某个人交差或回话用"
#: 共同尾巴的起止标记。
TAIL_HEAD = "而手上没有可等的东西"
TAIL_END = "就按交差处理"

#: 三处代码副本引的业主原话（`2026-10-27 第四条`）。按折叠空白比，见模块 docstring。
OWNER_SENTENCE = ("如果已无事可做且无计时器，这意味着它交差了，需要向父代理报告，"
                  "父代理把它记为静默子代理")
#: 复述这条规则的三个代码文件（相对 `src/agentflow`）。
CODE_COPIES: tuple[str, ...] = ("clock.py", "conductor.py", "agent_loop.py")

#: 整段的字数下限（反真空：抽不到东西时下面那几条不许静默通过）。
MIN_RULE_CHARS = 800


def _squash(text: str) -> str:
    """折叠全部空白（注释换行不是漂移）。"""
    return re.sub(r"\s+", "", text)


def _segment(text: str, head: str, tail: str) -> str:
    """`text` 里从 `head` 那一句到 `tail` 那一句（含两端）的原文；找不到 ⇒ 空串。"""
    i = text.find(head)
    if i < 0:
        return ""
    j = text.find(tail, i)
    if j < 0:
        return ""
    return text[i:j + len(tail)]


def _spec_text(role: str) -> str:
    return (SPECS_DIR / f"{role}.py").read_text(encoding="utf-8")


def test_the_ten_full_copies_are_byte_identical() -> None:
    """十个角色那一整段必须逐字相同（漂一个字符就红）。

    反真空：段长必须 ≥ `MIN_RULE_CHARS`，否则说明抽取标记失效了 ——
    那时"十条都一样"会变成"十条都是空串"，照样绿（本仓点名的 P16 形态）。
    """
    blocks: dict[str, str] = {}
    for role in FULL_COPY_ROLES:
        block = _segment(_spec_text(role), RULE_HEAD, TAIL_END)
        assert block, (f"specs/{role}.py 里抽不到那条规则（标记 `{RULE_HEAD}` 到 "
                       f"`{TAIL_END}`）—— 它被改写了，或者被挪走了")
        blocks[role] = block
    first = blocks[FULL_COPY_ROLES[0]]
    assert len(first) >= MIN_RULE_CHARS, (
        f"抽到的整段只有 {len(first)} 字（下限 {MIN_RULE_CHARS}）⇒ 抽取标记失效，"
        "这条判据已经失去对象")
    diff = [role for role, block in blocks.items() if block != first]
    assert not diff, (
        "这条规则在下面这些角色里与 "
        f"`specs/{FULL_COPY_ROLES[0]}.py` 那一份**不再逐字相同**：{diff}。"
        "改它要十份一起改（各自进不同角色的提示词，运行时无法互引）")


def test_the_tail_is_byte_identical_in_all_eleven_specs() -> None:
    """共同尾巴在十一个规格里逐字相同（`m` 的头句不同，尾巴相同）。"""
    tails: dict[str, str] = {}
    for role in SPEC_ROLES:
        tail = _segment(_spec_text(role), TAIL_HEAD, TAIL_END)
        assert tail, f"specs/{role}.py 里抽不到那条规则的尾巴（`{TAIL_HEAD}` 到 `{TAIL_END}`）"
        tails[role] = tail
    first = tails[SPEC_ROLES[0]]
    diff = [role for role, tail in tails.items() if tail != first]
    assert not diff, f"那条规则的尾巴在 {diff} 里与 `specs/{SPEC_ROLES[0]}.py` 不再逐字相同"
    # 十整份的尾巴必须就是这一条（两处口径不许分家）
    full_tail = _segment(_spec_text(FULL_COPY_ROLES[0]), TAIL_HEAD, TAIL_END)
    assert full_tail == first, "整段那十份的尾巴与十一个的尾巴对不上"


def test_no_other_spec_file_grows_a_copy() -> None:
    """除这十一个之外没有别的规格文件悄悄长出第十二份。"""
    carriers = sorted(p.stem for p in SPECS_DIR.glob("*.py")
                      if TAIL_HEAD in p.read_text(encoding="utf-8"))
    assert carriers == sorted(SPEC_ROLES), (
        "写着那条规则的规格文件变了："
        f"现在 {carriers}，判据认的是 {sorted(SPEC_ROLES)}。"
        "多出来的那一份要么删掉，要么把它加进 `SPEC_ROLES` 并让十份一起改")


def test_the_three_code_copies_quote_the_same_sentence() -> None:
    """三处代码副本引的业主原话必须逐字相同（折叠空白后比）。"""
    want = _squash(OWNER_SENTENCE)
    missing = [rel for rel in CODE_COPIES
               if want not in _squash((SRC_DIR / rel).read_text(encoding="utf-8"))]
    assert not missing, (
        f"这些代码副本不再逐字引业主那句「{OWNER_SENTENCE}」：{missing} —— "
        "它们复述的是同一条判据，漂一个字就有一处会把'交差'说成别的东西")


def test_a_single_changed_character_is_caught() -> None:
    """负控：把整段改一个字，判据认得出（证明上面那条不是"恒绿"）。

    这条不打桩、也不改盘：它在内存里改一个字符，再走一遍同一套抽取与比较。
    """
    first = _segment(_spec_text(FULL_COPY_ROLES[0]), RULE_HEAD, TAIL_END)
    assert first, "前提没建立：抽不到整段，这条负控无从判起"
    victim = first.replace("就按交差处理", "就按交差办理", 1)
    assert victim != first, "替换没生效 —— 负控的前提没建立"
    assert _segment(victim, RULE_HEAD, TAIL_END) != first, (
        "改一个字之后抽取结果仍然相同 ⇒ 比较函数有问题，上面那几条判据不可信")
    # 空文本走同一套抽取：必须给空串（而不是"没有可比对象所以通过"）
    assert _segment("", RULE_HEAD, TAIL_END) == ""


@pytest.mark.parametrize("role", SPEC_ROLES)
def test_every_spec_that_carries_the_rule_carries_the_whole_tail(role: str) -> None:
    """逐个角色：抽到尾巴就以 `就按交差处理` 收尾（半截规则比没有更糟）。"""
    tail = _segment(_spec_text(role), TAIL_HEAD, TAIL_END)
    assert tail.endswith(TAIL_END), (role, tail[-40:])
    assert "没在等" in tail, (role, tail)
