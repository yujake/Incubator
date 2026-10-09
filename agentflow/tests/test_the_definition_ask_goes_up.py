# -*- coding: utf-8 -*-
"""S1o：定义抽不到时的向上报文给直接父（`draft/97` §15.4 的载体那一半）。

业主 2026-10-09 逐字：

> 「最常见的定义不明极可能是A查论文要B消化时遇到生僻定义，这时和父代理A交流即可」

⇒ 补法优先级定死：①问直接父（父通常就是 A，原文在它手里，就地能给）→
②A 上网搜（`pending_search`）→ ③B 自撰基本概念（`self_authored`）。
上一批把"依赖由秘书从证明文本扫出来"与"定义来源分档计数"做完了（`cf00150`/`af312a4`），
并把 `pending_definitions[].who="direct_parent"` 备成了这一格的输入；
这一组守的是载体：那一条报文真的落盘、收件人是直接父、落到哪一级都有痕。

判据（正控 2 / 负控 1 / 反真空 2 / 三态 1）：

- 正控①：父是 A ⇒ 报文发给 A，标题是定义待补那一档，正文点名了那几条概念；
- 正控②：顶层（没有父）⇒ 发给 M（老行为只在这一档）；
- 负控：父那一行读不到 ⇒ 落回 M 并把原因写进读数（不静默改主、不丢报文）；
- 反真空①：两种收件人下都要留下结构化事件 `definition_ask`（可审计）；
- 反真空②：`escalate=True`（父那一级也办不了）⇒ 才发给 M，且 `stuck_at` 逐级留痕；
- 三态：没有待补定义 ⇒ `checked=False` + 理由，一条留言都不落（"没问"不是"问了"）。
"""
from __future__ import annotations

import pathlib

from agentflow.agent_loop import DEFINITION_ASK_SUBJECT, AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store


def _loop(tmp_path: pathlib.Path, *, parent_task_id: str = "", my_task_id: str = "b1"):
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    seam = LlmSeam(role="B", session_root=ws, gateway=None, price=(0.0, 0.0), sid="ask")
    loop = AgentLoop(role="B", session_root=ws, registry=None, conductor=cond,
                     seam=seam, store=st, sid="ask")
    loop.parent_task_id = parent_task_id          # noqa: SLF001 —— 夹具直接摆好父子关系
    loop.my_task_id = my_task_id                  # noqa: SLF001
    return loop, st, cond


def _row(cond: Conductor, role: str) -> str:
    return cond._write_new_row({          # noqa: SLF001 —— 与真机同一处建行口
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": None, "depth": 1, "input_key": f"ask@{role}",
        "status": "running", "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "父那一趟", "error": None, "started_at": "2026-10-10T00:00:00+08:00",
        "ended_at": None, "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}.run_once")


def _pending(*ids: str) -> list[dict]:
    return [{"kind": "pending_definition", "table": "statements", "id": i,
             "missing": "statement_full", "who": "direct_parent",
             "why": "抽不到定义 ⇒ 先问直接父"}
            for i in ids]


def _events(st) -> list[dict]:
    path = st.root / "sessions"
    out: list[dict] = []
    for p in sorted(path.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "definition_ask" in line:
                import json
                out.append(json.loads(line))
    return out


def test_the_definition_ask_goes_to_the_direct_parent(tmp_path: pathlib.Path):
    """正控①：父是 A ⇒ 报文发给 A（正文点名概念 + 说清优先级），不惊动 M。"""
    loop, st, cond = _loop(tmp_path)
    pid = _row(cond, "A")
    loop.parent_task_id = pid                                  # noqa: SLF001
    out = loop.ask_parent_for_definitions(_pending("0007", "0008"))
    assert out["checked"] is True, out
    assert out["to"] == "A", out
    assert out["subject"] == DEFINITION_ASK_SUBJECT, out
    assert out["concepts"] == ["0007", "0008"], out
    assert out["ask_why"], "读数里要写清为什么发给它"
    # 留言真的落在盘上（收件人是 A、标题是定义待补那一档）
    msgs = list((st.root / "sessions").glob("*.jsonl"))
    blob = "\n".join(p.read_text(encoding="utf-8") for p in msgs)
    assert "定义待补" in blob and "0007" in blob, blob[:400]
    assert DEFINITION_ASK_SUBJECT in blob, "标题要是机器可识别的那一位"
    # 结构化事件在（可审计）且写明收件人与逐级留痕那一格
    evs = _events(st)
    assert len(evs) == 1, evs
    assert evs[0]["kind"] == "definition_ask" and evs[0]["asks"] == "A", evs
    assert evs[0]["escalated"] is False and evs[0]["concepts"] == ["0007", "0008"], evs


def test_a_top_level_agent_asks_the_conductor(tmp_path: pathlib.Path):
    """正控②：顶层（没有父）⇒ 发给 M（老行为只保留在这一档）。"""
    loop, st, cond = _loop(tmp_path, parent_task_id="", my_task_id="")
    out = loop.ask_parent_for_definitions(_pending("0007"))
    assert out["checked"] and out["to"] == "M", out
    assert "顶层" in out["ask_why"], out


def test_an_unreadable_parent_falls_back_to_the_conductor(tmp_path: pathlib.Path):
    """负控：父那一行读不到 ⇒ 落回 M，并把原因写进读数（不静默改主）。"""
    loop, st, cond = _loop(tmp_path, parent_task_id="t-9999")
    out = loop.ask_parent_for_definitions(_pending("0007"))
    assert out["checked"] and out["to"] == "M", out
    assert "落回" in out["ask_why"] or "读不到" in out["ask_why"], out


def test_escalation_to_the_conductor_keeps_the_trace(tmp_path: pathlib.Path):
    """反真空②：父那一级也办不了 ⇒ 才爬上 M，且 `stuck_at` 逐级留痕。"""
    loop, st, cond = _loop(tmp_path, parent_task_id="")
    pid = _row(cond, "A")
    loop.parent_task_id = pid                                  # noqa: SLF001
    out = loop.ask_parent_for_definitions(_pending("0007"), escalate=True,
                                          stuck="父 A 说原文里也没有这条定义（第 3 页只有个名字）")
    assert out["checked"] and out["to"] == "M" and out["escalated"] is True, out
    assert "父那一级也办不了" in out["ask_why"], out
    evs = _events(st)
    assert len(evs) == 1 and evs[0]["escalated"] is True, evs
    assert "原文里也没有" in evs[0]["stuck_at"], evs
    assert evs[0]["ask_why"], evs


def test_nothing_to_ask_sends_nothing(tmp_path: pathlib.Path):
    """三态：没有待补定义 ⇒ `checked=False` + 理由，一条留言都不落。"""
    loop, st, cond = _loop(tmp_path)
    before = sorted((st.root / "sessions").glob("*.jsonl")) if (st.root / "sessions").is_dir() else []
    out = loop.ask_parent_for_definitions([])
    assert out["checked"] is False and out["reason"], out
    assert out["message_id"] == "" and out["to"] == "", out
    assert _events(st) == [], "没有待补定义却落了 definition_ask 事件"
    after = sorted((st.root / "sessions").glob("*.jsonl")) if (st.root / "sessions").is_dir() else []
    assert len(after) == len(before), "没有待补定义却落了留言"


# ==================================================== 二、接线：工具一报待补就发（不是只写了个函数）

class _ToolResult:
    def __init__(self, data: dict) -> None:
        self.ok = True
        self.data = data
        self.error = ""
        self.meta: dict = {}


class _StubRegistry:
    """只回一个固定结果的注册表：用来把"工具报待补 ⇒ 循环就地发报文"这条线走通。"""

    def __init__(self, data: dict) -> None:
        self._data = data

    def names(self) -> list[str]:
        return ["probe.register"]

    def call(self, name: str, **kw) -> _ToolResult:
        return _ToolResult(self._data)


def test_the_loop_asks_the_parent_when_a_tool_reports_pending_definitions(tmp_path: pathlib.Path):
    """接线判据：`_do_tool` 见到 `pending_definitions` ⇒ 就地发报文，读数挂在这一步上。

    只判"函数存在"是不够的：真机上这一步发生在循环的 `_do_tool` 里，
    而"谁去问父"正是 §15.4 要落地的那件事（不做的话，定义待补只是台账上的一个状态）。
    """
    loop, st, cond = _loop(tmp_path)
    pid = _row(cond, "A")
    loop.parent_task_id = pid                                  # noqa: SLF001
    loop.registry = _StubRegistry({"ok": True, "stmt_id": "0007",
                                   "pending_definitions": _pending("0007")})
    out = loop._do_tool({"name": "probe.register", "args": {}})   # noqa: SLF001
    assert out["ok"] is True, out
    ask = out.get("definition_ask")
    assert ask and ask["checked"] is True and ask["to"] == "A", out
    assert out["meta"]["definition_ask"]["concepts"] == ["0007"], out["meta"]
    evs = _events(st)
    assert len(evs) == 1 and evs[0]["asks"] == "A", evs
    # 反真空：工具没有报待补时不许发（否则每一步工具调用都去打扰父）
    loop.registry = _StubRegistry({"ok": True, "stmt_id": "0008"})
    out2 = loop._do_tool({"name": "probe.register", "args": {}})   # noqa: SLF001
    assert "definition_ask" not in out2, out2
    assert len(_events(st)) == 1, "没有待补却又发了一次"
