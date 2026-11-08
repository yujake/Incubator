# -*- coding: utf-8 -*-
"""判据夹具：B 收录时"是不是在册的同一条命题"那一问的离线替身（2026-11-08 口径）。

## 为什么需要它

收录正路（`agent_b/register_statement.py::register_statement`）现在在 B-2（新行必须以
猜想注册）/ B-4（说"无来源可核"必须指到我方手稿）这两道闸之前先问一次
"台账里有没有同一条"（`_resolve_same_statement`：秘书挑词 → 代码检索 → 一次两档判定）。
那一问要秘书；没接秘书时它 fail-closed（`same_statement_unjudged`，不新建不合并）。

fail-closed 是对的行为（"没查成"不许折成"不是同一条"），但它会把"这个夹具没接秘书"
顶到判据前面，于是 B-2 / B-4 / 概念 origin 那几条判据量到的是同一性闸，而不是自己
那一道闸。

## 它替代了什么，没替代什么

只替代"模型说了什么"这两次调用：挑得出词（`secretary:statement_keywords`）、判定说
"不是同一条"（`secretary:statement_same`）。检索面 / 命中计数 / 两档结论的形状 /
fail-closed 仍然全部走 `_resolve_same_statement` 与 `Secretary.adjudicate_proposition`
那一处实现 —— 这个替身给的是"查过了、没有同一条"，不是"免查"。

## 两种接法

- `SameStatementStub()` 直接当 `Secretary(..., seam=..., enable_model=True)` 的缝；
- `wire_for_secretary(monkeypatch)` 把 `LlmSeam.for_secretary` 换成"返给我这一条"，
  于是走 `for_role_wired` / `host.build_role_registry` 那几条真装配路径的构造点
  （`agent_b/core._statement_secretary`、`table_tools` 直写路由）都能拿到它，
  装配代码一行不改。
"""
from __future__ import annotations

import json


class _Call:
    """`llmseam.SeamCall` 的最小替身（`Secretary.judge` 只读 `ok` / `problem` / `detail`）。"""

    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


def _material(prompt: str) -> dict:
    text = str(prompt or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return {}


class SameStatementStub:
    """只答两件事的秘书缝：挑检索词 / 两档判定（缺省 different）。"""

    wired = True

    def __init__(self, *, keywords=("在册定理",), decision: str = "different",
                 same_as: str = "") -> None:
        self.keywords = [str(w) for w in keywords]
        self.decision = str(decision)
        self.same_as = str(same_as)
        self.calls: list[str] = []

    def ask_json(self, prompt, *, system: str = "", task_id: str = "", note: str = ""):
        kind = str(note or "")
        self.calls.append(kind)
        if kind.endswith("statement_keywords"):
            return ({"keywords": list(self.keywords),
                     "why": "夹具：用这几个数学词去台账里捞同义的那一条"}, _Call())
        # 判定那一问有两个入口名：`judge_statement_same` 的 `secretary:statement_same`
        # 与 `adjudicate_proposition` 直调时的 `secretary:proposition_identity` ——
        # 两个入口共用同一处判定（2026-11-08 收口），替身也按同一份判词答。
        if kind.endswith("statement_same") or kind.endswith("proposition_identity"):
            return ({"decision": self.decision, "same_as": self.same_as,
                     "canonical_name": "", "route": "",
                     "condition": "夹具：条件未读", "conclusion": "夹具：结论未读",
                     "reason": f"夹具：判 {self.decision}",
                     "basis": [f"夹具：{self.decision}"]}, _Call())
        return ({}, _Call())


def wire_for_secretary(monkeypatch, **kw) -> SameStatementStub:
    """把 `LlmSeam.for_secretary` 换成"返给我这一条替身"（上下文由 `monkeypatch` 收）。

    为什么换这一层而不是 `secretary.seam_for_secretary`：这一份要量的那几条判据都在
    `agent_b` / `host` 的真装配路径上，把桩打在 `for_secretary` 上，装配处走的仍是
    生产代码（与 `tests/test_secretary_adjudication_is_wired.py` 的 `_for_secretary_stub`
    同一口径）。
    """
    from agentflow import llmseam

    stub = SameStatementStub(**kw)
    monkeypatch.setattr(llmseam.LlmSeam, "for_secretary",
                        classmethod(lambda cls, **_kw: stub))
    return stub
