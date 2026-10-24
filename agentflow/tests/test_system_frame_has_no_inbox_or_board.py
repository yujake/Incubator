# -*- coding: utf-8 -*-
"""判据 S1：system 段的任务框不再印「留言」与「板」两格（D-52 起它们只作为每一步的增量）。

## 守的是什么

D-52 把「你收到的留言 / 挂在你名下的工作项」从 system 的固定格改成 `agent_loop` 每一步
投一次的增量（`_deliver_mailbox`）。可是 system 的模板与 `_TASK_FRAME_BLOCK_NAMES` 还留着
这两格，缺省句恒为「没有收到留言 / 板上没有要你处理的事」⇒ 模型开场读到"没有"，下一步
又收到增量 —— 同一个问题两种说法，而且开场那句是假的。

## 判据（正控 1 / 负控 1 / 渲染完好 1）

1. 十一个角色的渲染提示词里，那两格的标题与两句缺省都不出现；
2. 反真空：把两格塞回 `_TASK_FRAME_BLOCK_NAMES` 与 `_TASK_FRAME_TEXT` ⇒ 同一个判据函数必红；
3. 渲染没有损坏：D/E/F 三份提示词里不出现 `⏎`、不出现退格造成的残字（U+0008 / U+FFFD）。

## 为什么值仍保留在 `prompt_facts`

那两格的值（含缺省句）仍是开场 user 消息的唯一来源（`prompt_facts` 的注释写着
"一处定义、两个读者"）。本判据只摘 system 的那一段，不动数据源 —— 所以第 1 条还要反向
断言 `prompt_facts` 仍能给出这两格的缺省句。
"""
from __future__ import annotations

import pytest

from agentflow import agent_prompts as AP
from agentflow import schema as S
from agentflow.tools import build_registry

ROLES = (*S.ROLES, S.CONDUCTOR_ROLE)

#: 那两格的标题（system 模板里曾经逐字出现）。
_STALE_LABELS = (
    "你收到的留言（可能为空）",
    "挂在你名下的工作项（板；可能为空）",
)

#: 那两句缺省（`prompt_facts` 里的值；不该出现在 system 段）。
_STALE_DEFAULTS = ("（没有收到留言）", "（板上没有要你处理的事）")

_OLD_NAMES = ("TASK_FRAME", "TASK_INBOX", "TASK_BOARD", "TASK_USER_REPLIES",
              "TASK_NOTEBOOK", "TASK_BUDGET")
_OLD_TEXT = (
    "这一次的任务：\n{{task}}\n\n"
    "你收到的留言（可能为空）：\n{{inbox}}\n\n"
    "挂在你名下的工作项（板；可能为空）：\n{{board}}\n\n"
    "用户回答过的问题（含迟到送达的回答）：\n{{user_replies}}\n\n"
    "你的草稿本（最近几条，是你自己以前写的）：\n{{notebook}}\n\n"
    "剩余预算：{{budget_left}}"
)

_TASK = "把这一件活做完"
_ROOT = "D:/x"


@pytest.fixture(scope="module")
def registry():
    return build_registry().registry


def _prompt(role: str, registry) -> str:
    return AP.system_prompt(role, registry=registry, task=_TASK, workspace_root=_ROOT)


def _stale_problems(text: str) -> list[str]:
    """system 段里还留着那两格（标题或缺省句）= 一条问题，点名是哪一格。"""
    out = [f"system 里还印着「{needle}」" for needle in _STALE_LABELS if needle in text]
    out += [f"system 里还念着缺省句「{needle}」" for needle in _STALE_DEFAULTS if needle in text]
    return out


# ============================================================ 1 正控（逐角色）
@pytest.mark.parametrize("role", ROLES)
def test_01_system_no_longer_prints_the_inbox_or_board_cell(role: str, registry) -> None:
    """01：这个角色的 system 段里，两格标题与两句缺省都不出现。"""
    text = _prompt(role, registry)
    assert len(text) > 3000, f"{role} 的提示词只有 {len(text)} 字 ⇒ 这条判据没有落脚点"
    problems = _stale_problems(text)
    assert problems == [], f"{role}：\n  - " + "\n  - ".join(problems)


def test_02_the_facts_still_exist_for_the_opening_user_message() -> None:
    """02（反向）：数据源没被一起删掉 —— `prompt_facts` 仍给这两格的缺省句。"""
    facts = AP.prompt_facts()
    assert facts["inbox"] == "（没有收到留言）", facts["inbox"]
    assert facts["board"] == "（板上没有要你处理的事）", facts["board"]


# ============================================================ 3 反真空：塞回去必红
def test_03_putting_the_two_cells_back_turns_the_criterion_red(
        registry, monkeypatch: pytest.MonkeyPatch) -> None:
    """03：把两格塞回块名表与模板 ⇒ `_stale_problems` 必红（不是"删了也没人知道"）。"""
    monkeypatch.setattr(AP, "_TASK_FRAME_TEXT", _OLD_TEXT)
    monkeypatch.setattr(AP, "_TASK_FRAME_BLOCK_NAMES", _OLD_NAMES)
    text = _prompt("D", registry)
    problems = _stale_problems(text)
    assert problems, (
        "把两格塞回 `_TASK_FRAME_BLOCK_NAMES` 与模板之后，判据却一声不吭 —— "
        "它读的不是 system 段里那两格")
    assert any("你收到的留言" in one for one in problems), problems


# ============================================================ 4 渲染完好
@pytest.mark.parametrize("role", ("D", "E", "F"))
def test_04_the_rendered_prompt_is_not_corrupted(role: str, registry) -> None:
    """04：三份提示词里不出现 `⏎`、不出现退格/替换字符造成的残字。"""
    text = _prompt(role, registry)
    for bad, why in (("⏎", "换行被写成了可见的 ⏎ 记号"),
                     ("\x08", "退格字符残留在文本里"),
                     ("\ufffd", "替换字符（编码坏了）")):
        assert bad not in text, f"{role} 的提示词里有 {bad!r}：{why}"
