# -*- coding: utf-8 -*-
"""判据（SEEDREADME，2026-11-21）：M 的职责面要写清「用户点名 ⇒ 逐字记声明 ⇒ 分批派 A 按清单收编」。

## 改前为什么红

种子投放把几十份 PDF 放进工作区 `library/` 之后，事实读数（`LOCAL_MATERIALS` 那一段，
`agent_prompts._pending_local_materials`）会报「还有 N 份没进 `literature`」，但 M 的职责面
一个字都没写：谁定「哪几份是本次的可靠参考文献」？（用户的提示词是唯一判据，M 不许自己判）
声明落在哪？一次派多少？什么时候算收编完了？

没有这一段，M 的两种省事读法都不报错：自己按题名"看起来相关"挑一批（用户没点名的也入库），
或者把整目录一次派给 A。业主 2026-11-21 裁定是 fail-closed：只有用户提示词里明确点名的
才算可靠参考文献、才可入库；未点名的只能当研究参考。

## 判据（c）

M 的渲染提示词里那一条政策，同时写到：M 不自己判断（只有用户明确点名的才可入库）、
把点名的文件/目录逐字抄进工作区根的 `RELIABLE-REFERENCES.json`（`paths` + `verbatim`，
没点名 ⇒ 空列表）、分批派 A 且清单外的文件不许派、每批回来核 pending=0、收编完确认
「未收编材料=0」再往下走、之后派 B 的 `run_once`。
反真空：把这一条从 policy 里抠掉再渲染 ⇒ c 必红。

真身只有一处：`specs/m.py` 的 policy（声明文件的读取/匹配语义真身在 `locallib`）。
"""
from __future__ import annotations

import dataclasses

import pytest

from agentflow import agent_prompts as AP
from agentflow import locallib as LL
from agentflow.tools import build_registry

#: 那一条政策的认领词（判据按它把这一条从渲染产物里取出来 —— 只在这一条里比）。
_HEAD = "工作区里有参考材料时"

#: 这一条必须写到的事（业主 2026-11-21 的 SEEDREADME 口径；顺序 = 正文的顺序）。
_REQUIRED: tuple[tuple[str, str], ...] = (
    ("M 不自己判断哪份可靠", "不自己判断"),
    ("只有用户明确点名的才可入库", "明确点名"),
    ("把点名的文件/目录逐字抄下来", "逐字抄"),
    ("声明文件名与 locallib 的真身一致", LL.DECLARATION_NAME),
    ("声明形状：paths", '"paths"'),
    ("声明形状：verbatim（用户原话）", "verbatim"),
    ("用户没点名 ⇒ 清单为空（fail-closed）", "空列表"),
    ("分批派 A", "分批派 A"),
    ("清单外的文件不许派", "清单外的文件不许派"),
    ("每批回来核 pending=0", "pending=0"),
    ("收编完确认未收编材料=0", "未收编材料=0"),
    ("之后派 B 的 run_once 整理", "run_once"),
    ("未声明被受控拒的那个码", "not_declared_reference"),
)

#: 渲染用的固定任务与工作区（与本目录其余提示词判据同一组缺省值）。
_TASK = "把工作区里的参考文献收编进来"
_ROOT = "D:/x"


def _m_prompt() -> str:
    """M 这一次真的会读到的 system prompt。"""
    return AP.system_prompt("M", registry=build_registry().registry,
                            task=_TASK, workspace_root=_ROOT)


def _policy_line(prompt: str) -> str:
    """渲染产物里那一条政策的整行（找不到 = 空串，判据会点名）。"""
    for line in prompt.splitlines():
        if _HEAD in line:
            return line.strip()
    return ""


def _problems(text: str) -> list[str]:
    """这条政策的问题（空 = 该写的事都写到了）。"""
    if not text:
        return [f"M 的渲染提示词里读不到「{_HEAD}」这一条政策"]
    return [f"缺「{label}」（`{needle}`）" for label, needle in _REQUIRED if needle not in text]


def test_c_m_transcribes_the_users_named_files_and_batches_them() -> None:
    """c：M 的渲染提示词里有「用户点名 ⇒ 逐字声明 ⇒ 分批派 A ⇒ 核 pending=0」。"""
    line = _policy_line(_m_prompt())
    assert line, (
        f"M 的渲染提示词里没有「{_HEAD}」这一条 —— 下一趟真机 M 只能自己猜"
        "（自己挑一批入库 / 把发现读数当已入库，两种都不报错）")
    problems = _problems(line)
    assert problems == [], (
        "M 的政策没把参考材料这件事写全：\n  - " + "\n  - ".join(problems))
    # 反真空：这些事真的长在同一条政策里、各在不同位置（不是散在别处被这一行借来）。
    # 用 rfind：标题句里也复述了「分批派 A」与「未收编材料=0」，正文才是口径落点。
    positions = [line.rfind(needle) for _label, needle in _REQUIRED]
    assert len(set(positions)) == len(_REQUIRED), positions
    assert positions == sorted(positions), (
        "那几件事的正文顺序不对（声明 → 抄下来 → 空清单 → 分批 → 清零 → 下一步）："
        + repr(positions))


def test_c_anti_vacuum_dropping_the_policy_makes_it_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """c 的反真空：把这一条从 M 的 policy 里抠掉 ⇒ 同一检查必红。"""
    brief = AP.ROLE_BRIEFS["M"]
    assert _problems(_policy_line(_m_prompt())) == [], "夹具前提：改后这一面应当先绿"

    keep = tuple(item for item in brief.policy if _HEAD not in str(item))
    assert len(keep) == len(brief.policy) - 1, (
        "夹具前提：这条政策恰好是一条（否则反真空打的是「删干净」）")
    monkeypatch.setitem(AP.ROLE_BRIEFS, "M", dataclasses.replace(brief, policy=keep))
    got = _policy_line(_m_prompt())
    assert got == "", "抠掉这一条之后渲染产物里仍读得到它 —— c 是橡皮图章"
    problems = _problems(got)
    assert problems and any("读不到" in one for one in problems), problems
