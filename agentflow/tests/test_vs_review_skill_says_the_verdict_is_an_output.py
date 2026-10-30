# -*- coding: utf-8 -*-
"""判据：V 的复核技能必须写清"结论是工具的产出，不是入参"。

## 真机（2026-10-28，`projects/paper-rewrite-78c` 17:42:51 与 17:43:07）

V 连着两次把 `verdict` / `findings` / `defect_step` / `unresolved_errors` 当参数传给
`verify.verify_proof`，被参数门拒成 `param_invalid`：那件工具的 schema 只收
`proof_no` / `proof_text` / `readonly_facts` / `statement_id`，而结论由它自己判
（它内部走 V 的判据缝，返回里给 `verdict` / `defect_step` / `findings`）。

V 会这么写是因为派活的原文是「核…回 defect_step 与逐条 findings」—— "回"被理解成"传进去"。
工具那一侧不该收（收了就等于让被审的一方自己报结论），所以修在 V 的技能里：
把"这是产出不是入参"写成一句话，并给出"要补自己的看法就走 message"的正路。

## 这一组守什么

1. 技能正文里有这条口径（三处关键词都在：产出 / 入参 / message）；
2. 反真空：`verify.verify_proof` 的声明参数里没有 `verdict` / `findings` /
   `defect_step`（这两处必须同时成立：技能说"别传"、工具也"不收"）；
3. 落盘：技能真的物化成 `skills/V/复核-两态并指到那一步.md` 且带这一段。
"""
from __future__ import annotations

import pathlib

from agentflow import agent_skills as AS
from agentflow.tools import build_registry
from agentflow.store import Store


def _skill() -> dict:
    """在 `CATALOG`（角色 → 该角色的技能元组）里找 V 的复核技能。"""
    for role, items in AS.CATALOG.items():
        for item in items:
            got = item if isinstance(item, dict) else getattr(item, "__dict__", {})
            if str(got.get("slug")) == "复核-两态并指到那一步":
                return {**got, "_role": role}
    raise AssertionError("技能表里没有 V 的复核技能 ⇒ 判据失去对象")


def test_the_skill_says_the_conclusion_is_an_output():
    """正题：技能正文写清"结论是产出、不是入参"，并给出 message 那条正路。"""
    body = str(_skill().get("body") or "")
    assert "产出" in body and "入参" in body, body[:400]
    assert "message" in body, body[:400]
    for key in ("verdict", "findings", "defect_step"):
        assert key in body, (key, body[:400])


def test_the_tool_does_not_take_a_self_reported_verdict():
    """反真空：工具的声明参数里没有这三格（技能说"别传"、工具也"不收"）。"""
    reg = build_registry(store=Store(pathlib.Path(".")).init() and
                         Store(pathlib.Path("."))).registry
    spec = reg.get("verify.verify_proof")
    props = set((spec.params.get("properties") or {}))
    for key in ("verdict", "findings", "defect_step", "unresolved_errors"):
        assert key not in props, (key, sorted(props))
    assert "statement_id" in props, sorted(props)


def test_the_skill_lands_on_disk_with_that_paragraph(tmp_path: pathlib.Path):
    """物化之后的技能文件里也带这一段（读的是 `fs.read` 的那一份）。"""
    from agentflow.agent_skills import materialize

    ws = tmp_path / "ws"
    (ws / "skills").mkdir(parents=True)
    materialize(ws)
    text = (ws / "skills" / "V" / "复核-两态并指到那一步.md").read_text(encoding="utf-8")
    assert "产出" in text and "入参" in text, text[:400]
