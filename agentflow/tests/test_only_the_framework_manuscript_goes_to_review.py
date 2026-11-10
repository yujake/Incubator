# -*- coding: utf-8 -*-
"""递审只能递框架渲染的手稿，章节稿不算手稿（2026-11-10）。

## 现场（`projects/dct-min-20261110` 真机读数，业主从盘上逐条读出来的）

- V 的 `verify_proof` 一共被调了 9 次，签一发都没发出来：其中 5 次是同一条拒
  （`proof_manuscript` 只收 F 的证明手稿，收到 `reports/P1-MCT.md`），另外几次收到
  `reports/P2-fatou-lemma.md` / `notes/P3-manuscript-body.md`，同样被入口闸拒；
- 有 1 次只传 `proof_text`（不传稿）⇒ `checked=true` 但判「有毛病」、只落 pending 行；
- 1 次参数错误（`statement_id` 长度不够）；
- 而盘上确实有框架稿 `reports/f-proof-P3.md` / `reports/b-proof-000001.md` /
  `reports/e-num-000000.md`。

结论：F 用 `fs.write` 写了「论文章节稿」，把章节稿当被审手稿递给 V；V 照着去读 ⇒
入口闸全拒 ⇒ 9 次白烧。入口闸本身是对的（唯一判据），缺的是递审方与收审方的教法：

| # | 谁 | 题面必须出现 | 反真空（把这一句删掉就红） |
|---|---|---|---|
| a | F | 「只能点 `F.step` 返回的 `manuscript_path`」+「章节稿不是手稿」 | 删那一句 ⇒ a 红 |
| b | V | 「被审必须是 `reports/f-proof*.md`；递来别的东西先退回」+「不要重试同一个路径」 | 删那一句 ⇒ b 红 |
| c | D（携带方） | 「只转 `manuscript_path`，不转章节稿」 | 删那一句 ⇒ c 红 |

这不是新增机制：入口闸一个字没改（`agent_v/core.py::_review_unregistered_prose` 只认
`reports/f-proof*.md` / `e-proof-*` / `b-proof-*`），本判据守的是「模型在递审之前就知道
该递哪一份」。零模型调用、零网络。
"""
from __future__ import annotations

from agentflow import agent_prompts as AP
from agentflow.tools import build_registry

TASK = "把这条链路走一遍"
ROOT = "D:/x"

#: 三句硬教法的逐字锚点（判据只认这三个子串）。
F_NEEDLE = "只能点 `F.step` 返回的 `manuscript_path`"
V_NEEDLE = "被审必须是 `reports/f-proof*.md`；递来别的东西先退回"
D_NEEDLE = "转交给 B 时只转 F 给你的 `manuscript_path`"

#: 每一条硬教法配套的「为什么」（缺了它就只是命令、不是可理解的口径）。
F_REASONS: tuple[str, ...] = (
    "`reports/P1-*.md`",
    "`reports/P2-*.md`",
    "`notes/*.md`",
    "不是手稿",
    "入口闸会整笔拒",
    "真机实测 9 次全拒、签一发未发",
)
V_REASONS: tuple[str, ...] = (
    "`reports/P*.md`",
    "`notes/*.md`",
    "这不是手稿",
    "`manuscript_path`",
    "不要重试同一个路径",
)
D_REASONS: tuple[str, ...] = (
    "不转章节稿",
    "`reports/P1-*.md`",
    "`notes/*.md`",
    "`## 命题` / `## 证明` / `## 依赖`",
)


def _prompt(role: str) -> str:
    return AP.system_prompt(role, registry=build_registry().registry,
                            task=TASK, workspace_root=ROOT)


def _problems(role: str, text: str) -> list[str]:
    """这一份题面缺了什么（空列表 = 三处硬教法都对得上）。

    纯函数：判据本体只在这里；`text` 既可以是真渲染的那一份，也可以是反真空探针
    （删掉一句之后的同一份文本）—— 两端走同一条路，反真空才打得到真判据。
    """
    if role == "F":
        needle, reasons, what = F_NEEDLE, F_REASONS, "F 递审"
    elif role == "V":
        needle, reasons, what = V_NEEDLE, V_REASONS, "V 收审"
    elif role == "D":
        needle, reasons, what = D_NEEDLE, D_REASONS, "D 携带"
    else:  # pragma: no cover - 只给三条判据用
        raise AssertionError(role)
    bad: list[str] = []
    if needle not in text:
        bad.append(f"{what}：题面里没有这一句硬教法：{needle!r}")
    missing = [x for x in reasons if x not in text]
    if missing:
        bad.append(f"{what}：缺了配套的「为什么」{missing}")
    return bad


def test_a_f_is_told_to_hand_over_only_the_manuscript_path() -> None:
    """a. F 的题面必须说清：递审只能点 `F.step` 的 `manuscript_path`，章节稿不是手稿。"""
    text = _prompt("F")
    assert len(text) > 2000, len(text)  # 反真空：读到的真的是渲染出来的那一份
    bad = _problems("F", text)
    assert bad == [], "\n".join(bad)


def test_a_removing_the_f_sentence_makes_the_criterion_red() -> None:
    """a 反真空：把那一句硬教法从同一份题面里删掉 ⇒ 同一个算式必须报出来。"""
    text = _prompt("F")
    assert F_NEEDLE in text
    hit = _problems("F", text.replace(F_NEEDLE, ""))
    assert hit and any(F_NEEDLE in x for x in hit), hit


def test_b_v_is_told_to_refuse_anything_but_the_framework_manuscript() -> None:
    """b. V 的题面必须说清：被审必须是框架稿；递来别的东西先退回，且别重试同一路径。"""
    text = _prompt("V")
    assert len(text) > 2000, len(text)
    bad = _problems("V", text)
    assert bad == [], "\n".join(bad)


def test_b_removing_the_v_sentence_makes_the_criterion_red() -> None:
    """b 反真空：删掉 V 那一句 ⇒ 同一个算式必须报出来。"""
    text = _prompt("V")
    assert V_NEEDLE in text
    hit = _problems("V", text.replace(V_NEEDLE, ""))
    assert hit and any(V_NEEDLE in x for x in hit), hit


def test_c_d_carries_only_the_manuscript_path() -> None:
    """c. D（携带方）只转 `manuscript_path`，不转章节稿。"""
    text = _prompt("D")
    assert len(text) > 2000, len(text)
    bad = _problems("D", text)
    assert bad == [], "\n".join(bad)


def test_c_removing_the_d_sentence_makes_the_criterion_red() -> None:
    """c 反真空：删掉 D 那一句 ⇒ 同一个算式必须报出来。"""
    text = _prompt("D")
    assert D_NEEDLE in text
    hit = _problems("D", text.replace(D_NEEDLE, ""))
    assert hit and any(D_NEEDLE in x for x in hit), hit
