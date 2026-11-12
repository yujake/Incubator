# -*- coding: utf-8 -*-
"""判据：B 的手册要按四列读携带单，并说出第四格是路径号（由 B 收录时分配）。

## 为什么要有这一条

`depsection.CARRIED_COLUMNS` 的携带单是四列（命题号 / 手稿路径 / sha256 / 路径号），
而 B 的手册（`agent_skills` 的「登记-三件式与证据三态」）必须按四列读它 —— 否则 B 会：
① 以为第四格不存在（把 `| stmt:000009 | … | <sha> | 2 |` 读成"多了一列"或直接忽略）；
② 自己替它猜一个号（路径号由 B 收录时分配，产出侧不写证明号、稿名不带 `-pN`）。

同一句里还有第二处教法：取稿次序要写全三处（`proof_manuscript` 直递 / D 的携带单 /
行上 `manuscript_id`），不能只写"按约定路径"。

## 判据

| # | 判据 | 缺了会怎样 |
|---|---|---|
| a | 携带单那一段写成"四列表"，且"第四格是路径号"逐字出现 | 手册写成"三列表"，第四格一字未提 |
| b | 反真空：把那句换回"三列表"、删掉第四格 ⇒ 同一份判据必须报缺 | 没有这一格可打桩，判据会读别处 |
"""
from __future__ import annotations

import dataclasses

import pytest

from agentflow import agent_skills as AS
from agentflow import depsection as DS

SLUG = "登记-三件式与证据三态"


def _body() -> str:
    for skill in AS.skills_for("B"):
        if skill.slug == SLUG:
            return skill.body
    raise AssertionError(f"B 的手册里没有 {SLUG!r} —— 判据找不到落点")


def _problems(body: str) -> list[str]:
    """这一段缺哪几样（a 用真身；b 把打桩后的正文喂进同一个判据）。"""
    start = body.find("## 携带的证明手稿")
    if start < 0:
        return ["没有「## 携带的证明手稿」这一句"]
    paragraph = body[start:start + 400]
    out: list[str] = []
    if "三列表" in body:
        out.append(f"手册还写着「三列表」（携带单是 {len(DS.CARRIED_COLUMNS)} 列）")
    if "四列表" not in paragraph:
        out.append("携带单那一段没有写「四列表」")
    if "第四格是路径号" not in paragraph:
        out.append("携带单那一段没有说第四格是路径号")
    if "exp:<实验号>" not in paragraph:
        out.append("没有说第一格还认 `exp:<实验号>`")
    return out


# ============================================================ a 四列 + 第四格
def test_a_the_b_manual_reads_the_carried_sheet_as_four_columns() -> None:
    """a：携带单那一段要说"四列表"、"第四格是路径号"与 `exp:` 键。"""
    problems = _problems(_body())
    assert problems == [], "B 的手册读不懂这一版携带单：\n  - " + "\n  - ".join(problems)


# ============================================================ b 反真空
def test_b_the_old_three_column_sentence_turns_it_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """b：把那一段换回"三列表"、删掉第四格 ⇒ a 的判据必须报缺。"""
    real = _body()
    # 反真空那一句：把真身里的"四列表 / 第四格是路径号"还原成缺它的写法。
    old = real.replace("四列表", "三列表").replace("第四格是路径号", "")
    skills = tuple(
        (dataclasses.replace(s, body=old) if s.slug == SLUG else s)
        for s in AS.CATALOG["B"])
    monkeypatch.setitem(AS.CATALOG, "B", skills)
    patched = _body()
    assert patched == old and "三列表" in patched, "打桩没生效"
    assert "第四格是路径号" not in patched, "打桩没生效"
    problems = _problems(patched)
    assert problems, "打桩成缺它的写法之后判据仍然全绿 ⇒ a 读的不是这一段"


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
