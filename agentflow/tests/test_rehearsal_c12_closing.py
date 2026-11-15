# -*- coding: utf-8 -*-
"""彩排（真路径）C12 · 收工链 + 七格门：CLI 入口 → M 调 `conductor.closing` → 收工。

## 这条链与真机差在哪（逐项）

| 这一趟用的东西 | 真机 | 这份彩排 |
|---|---|---|
| 入口 | `agentflow start --mode research` | 同一行：`cli.main(["start", "--mode", "research", …])` |
| 执行体 | `_run_spec` → `_exec_role` → `host.wired_llm_conductor` → `LlmBackend` → `AgentLoop.run` | 同一条 |
| 派活 | `Conductor.summon`（本趟派一个 H 读一眼收工读数；它让循环本体在 `calling_as` 里花一次钱，三格②有对象） | 同一条 |
| 收工门 | `conductor.closing` 工具 → `closing.check_closing`（七格现算） | 同一条：判据本体、格表、`machine_pass` 全是产品原物 |
| M 的判据 | `goal_met` / `task_list` 由 M 交，落 `out/review/m-verdicts.jsonl` | 同一条：落盘由工具自己那一笔写 |
| M 的 final | `_final_gate_reading`（整树销号） | 同一条（H 先被销号，M 才 final） |
| 模型缝 | 真 `LlmSeam`（`_agent_seam_factory` / `for_role` / `for_secretary`） | 同一条：构造点一个都没替换 |
| 记账 | 真 `TokenMeter` → `usage_ledger` | 同一条 |
| 出网 | `modelgw.urllib_transport`（HTTP POST） | 只换这一处：回预置的 OpenAI 兼容 JSON |

旧 `test_rehearsal_c12_closing.py`（`CHAIN_ONLY` 里那份）手工造 `AgentLoop` 后直调私有
`loop._v_wait_gate_reading()`，并打桩 `manuscriptclosing.signed_candidates` 与 `Store.tx`；
这一份三处都不碰：门是 M 在真循环里用真工具调出来的。

## 这条链覆盖什么（业主点名的 C12）

```text
M --summon--> H（读一眼）--> M 销号 H
M --conductor.closing(goal_met=true, task_list=[…])--> closing.check_closing 现算七格
        ⇒ status 七格全 pass / machine_pass=True / can_close=True / closable=True
        ⇒ 判据落 out/review/m-verdicts.jsonl（运行外那一趟读同一份）
M --final--> _final_gate_reading（整树已销号）
```

判据读盘：`conductor.closing` 的回执里 `status` 恰好七格且全 `pass`、`machine_pass=True`、
`failed=[]`、`unknowns=[]`、`verdict_written.ok=True`；`m-verdicts.jsonl` 末行 `met=true`
且 `sid` 是本趟；`tasks` 里 H 行 `outcome="ok"`；钱账干净。

「每一格单独造红」的形态不在这里重复：那些单点判据在 `tests/test_closing_gate.py`
（每格一条负控 + 一条反真空）。这份彩排只用一格造红来证明链级的 `machine_pass` 承重
（见反真空）。

## 反真空（一个没被回答的问题 ⇒ user_pending 红）

`userio.ask_user(..., sid=本趟)` 在开跑前登记一个没被回答的问题（这就是循环里
「问了就停」的那条路，产品自己的 API），⇒ 真 `closing.check_closing` 的
`user_pending` 必须 `fail` ⇒ `machine_pass=False`；而 `m_says_done` / `closable`
仍是 `True`（收工由 M 判，业主 2026-10-09）—— 两条轴分开正是这一条要钉住的读数。
它证明「机器七格」不是摆设：M 说做完了，机器那一半照样记红。这条只造一格红，
其余六格照旧 `pass`。

## Lean 两档

`AGENTFLOW_LEAN_ENABLED` 开/关各跑一遍：夹具里有 T3 形态的实验行（`method=formal` +
检查器原话），所以两档的 `load_bearing` 都算有背书、`machine_pass` 都能为真。
"""
from __future__ import annotations

import io
import json
import pathlib
import re
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

import pytest

import rehearsal_contract as RC

from agentflow import cli
from agentflow import closing as CL
from agentflow import leanscope as LS
from agentflow import modelgw as MG
from agentflow.store import Store

from test_closing_gate import _good

SID = "cc3-c12"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _roster_names(prompt: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r'"roster_name":\s*"([A-Z]\d*)"', prompt)]


class _Wire:
    """预置的网络传输层替身（只回答"上游收到了什么、回了什么"）。"""

    def __init__(self) -> None:
        self.bodies: list[dict[str, str]] = []
        self._steps: dict[str, int] = {}
        self._done: list[str] = []

    def _m_step(self, index: int, prompt: str) -> str:
        if index == 0:
            return _json({"summon": {"role": "H", "task": "先读一眼收工读数"}})
        todo = [n for n in _roster_names(prompt) if n not in self._done]
        if todo:
            self._done.append(todo[0])
            return _json({"tool": "conductor.retire_child",
                          "args": {"child_name": todo[0], "reason": "知道了"}})
        if not self._steps.get("M:closing"):
            self._steps["M:closing"] = 1
            return _json({"tool": "conductor.closing",
                          "args": {"project_dir": ".",
                                   "report_path": "out/review/REPORT.md",
                                   "goal": "把这一项研究做到可交付",
                                   "goal_met": True,
                                   "basis": "七格读数都过、没有 blocker",
                                   "task_list": [{"what": "收工门七格", "state": "done"}]}})
        return _json({"final": "M 收工", "evidence": []})

    def _reply(self, system: str, prompt: str) -> str:
        head = system.lstrip()
        m = re.match(r"你是「秘书」的判断面（类别：([a-z_]+)）", head)
        if m:
            return _json({"decision": "可派", "reason": "彩排", "basis": ["夹具"]})
        m = re.match(r"你是 ([A-Z]) 号角色", head)
        if m:
            role = m.group(1)
            index = self._steps.get(role, 0)
            self._steps[role] = index + 1
            if role == "M":
                return self._m_step(index, prompt)
            return _json({"final": f"{role} 看完了", "evidence": []})
        return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["夹具"]})

    def __call__(self, url: str, headers: Any, body: bytes,
                 timeout_sec: float) -> tuple[int, str]:
        payload = json.loads(body.decode("utf-8"))
        messages = payload.get("messages") or []
        system = next((str(x.get("content") or "") for x in messages
                       if x.get("role") == "system"), "")
        prompt = "\n".join(str(x.get("content") or "") for x in messages
                           if x.get("role") == "user")
        text = self._reply(system, prompt)
        self.bodies.append({"system": system, "prompt": prompt, "text": text})
        return 200, json.dumps({"choices": [{"message": {"content": text},
                                             "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 8, "completion_tokens": 8}},
                               ensure_ascii=False)


def _run(base: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *,
         lean: str = "0", pending_question: bool = False) -> dict[str, Any]:
    """真工作区（七格全过的底座）→ 从 CLI 入口真跑一趟；只替换出网那一层。"""
    base.mkdir(parents=True, exist_ok=True)
    st, _report = _good(base)
    if pending_question:
        # 「问了就停」那一档：问题登记在本趟 `sid` 上、没有回答（产品自己的 API）。
        from agentflow import userio as U

        outcome = U.ask_user(st.root, role="M", question="这一版要不要交人复核？",
                             timeout_sec=0.0, wait=False, sid=SID)
        assert outcome.state == "pending", outcome
    wire = _Wire()
    monkeypatch.setenv("AGENTFLOW_MODEL_API_KEY", "rehearsal-fake-key-never-used")
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", str(lean))
    monkeypatch.setattr(MG, "urllib_transport", wire)
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main([
                "start", "--mode", "research", "--root", str(st.root), "--sid", SID,
                "--subagents", "--task", "先读一眼收工读数再收工", "--max-steps", "8",
            ])
    except SystemExit as exc:
        rc = int(exc.code or 0)
    return {"rc": int(rc), "ws": pathlib.Path(st.root), "store": Store(st.root),
            "wire": wire, "stdout": out.getvalue(), "stderr": err.getvalue(),
            "pending_question": pending_question}


def _events(ws: pathlib.Path) -> list[dict]:
    got: list[dict] = []
    for path in sorted((ws / "sessions").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                got.append(json.loads(line))
            except ValueError:
                continue
    return got


def _closing_result(events: list[dict]) -> dict:
    for e in events:
        if (e.get("kind") == "agent_step" and e.get("role") == "M"
                and e.get("shape") == "tool"
                and str((e.get("payload") or {}).get("name") or "") == "conductor.closing"):
            got = e.get("result") or {}
            data = got.get("data")
            if hasattr(data, "to_dict"):
                data = dict(data.to_dict())
            return {"ok": bool(got.get("ok")), "data": data if isinstance(data, dict) else {},
                    "meta": dict(got.get("meta") or {})}
    raise AssertionError("M 没有调过 conductor.closing（会话事件里找不到）")


def _rows(store: Store, table: str) -> list[dict]:
    return [dict(r) for r in store.rows(table)]


def _verdict_rows(ws: pathlib.Path) -> list[dict]:
    path = ws / "out" / "review" / "m-verdicts.jsonl"
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


# ============================================================ ① 正控：七格全过、machine_pass 真


def test_the_closing_gate_passes_all_seven_cells_from_the_cli(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：M 在真循环里调 `conductor.closing` ⇒ 七格全 pass、`machine_pass=True`。"""
    got = _run(tmp_path, monkeypatch, lean="0")
    events = _events(got["ws"])
    closing = _closing_result(events)
    data = closing["data"]

    # ---- 入口与"只换了网线"
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    assert got["wire"].bodies, "出网层一次都没被调到 ⇒ 这一趟没有真模型调用"
    assert MG.urllib_transport is got["wire"], "出网层没被替换（这一条会打真网络）"
    assert cli._agent_seam_factory.__module__ == "agentflow.cli", (
        "缝工厂被整体替换了 —— 这份彩排的承诺是「只换网线」")
    assert [e for e in events if e.get("kind") == "llm_call"], (
        "会话里一条 llm_call 都没有 ⇒ 走的不是真 LlmSeam")

    # ---- 七格：恰好那七格、且全 pass（键集取自产品自己的 DEFAULT_CHECKS）
    assert closing["ok"] is True, closing
    status = dict(data.get("status") or {})
    assert set(status) == set(CL.DEFAULT_CHECKS), sorted(status)
    assert all(v == "pass" for v in status.values()), status
    assert data["machine_pass"] is True, data["machine_pass"]
    assert data["m_says_done"] is True, data.get("m_says_done")
    assert data["can_close"] is True, data.get("can_close")
    assert data["closable"] is True, data.get("closable")
    assert data["failed"] == [] and data["unknowns"] == [], (data["failed"], data["unknowns"])
    assert closing["meta"].get("blocked") is False, closing["meta"]

    # ---- M 的判据落盘（运行外那一趟读同一份；同一 `sid`）
    written = dict(data.get("verdict_written") or {})
    assert written.get("tried") is True and written.get("ok") is True, written
    rows = _verdict_rows(got["ws"])
    assert rows, "out/review/m-verdicts.jsonl 没有落盘"
    last = dict(rows[-1])
    assert last.get("met") is True, last
    assert str(last.get("sid") or "") == SID, last

    # ---- 派活那一趟真的跑过（H 行 ok、被销号；三格的调用方身份有对象）
    h_rows = [t for t in _rows(got["store"], "tasks")
              if str(t.get("role")) == "H" and not str(t.get("kind") or "")]
    assert len(h_rows) == 1 and str(h_rows[0].get("outcome")) == "ok", h_rows

    from agentflow.modelcost import reconcile_usage

    money = reconcile_usage(got["store"])
    assert money["ledger_rows"] > 0, money
    assert money["unattributed"]["count"] == 0, money["unattributed"]
    assert money["dangling"] == [], money["dangling"]
    assert money["equal"] is True, money


# ============================================================ ② 反真空：一格造红 ⇒ machine_pass 假


def test_one_red_cell_turns_machine_pass_false_while_m_still_says_done(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：一个没被回答的问题 ⇒ `user_pending` 红 ⇒ `machine_pass=False`（M 仍说做完了）。

    这条只造一格红：其余六格照旧 pass。它证明链级的 `machine_pass` 真的压在七格
    的合取上，而不是"M 说了达成"的另一种写法。逐格各自的造红形态在
    `tests/test_closing_gate.py`（那里每格一条负控 + 一条反真空）。
    """
    got = _run(tmp_path, monkeypatch, lean="0", pending_question=True)
    closing = _closing_result(_events(got["ws"]))
    data = closing["data"]
    status = dict(data.get("status") or {})
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    assert str(status.get("user_pending") or "") == "fail", status
    # 只该红这一格：其余六格照旧 pass（定位不是"整张门都炸了"）。
    assert {k for k, v in status.items() if v != "pass"} == {"user_pending"}, status
    assert data["machine_pass"] is False, data["machine_pass"]
    assert data["failed"], data.get("failed")
    # M 的自述没变：机器那一半变假了，而 `closable` 是另一条轴（收工由 M 判，
    # 业主 2026-10-09）—— 两条轴分开正是这里要钉住的读数。
    assert data["m_says_done"] is True, data.get("m_says_done")
    assert data["closable"] is True, data.get("closable")
    assert "user_pending" in [str(x) for x in (data.get("failed") or [])], data.get("failed")


# ============================================================ 判据①：每笔真调用一行账


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_real_call_has_exactly_one_ledger_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据①：这一趟的每一次真调用，`usage_ledger` 里有且只有一行（Lean 开/关各一遍）。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    reading = RC.ledger_identity(got["ws"], got["store"])
    print(f"[一行账] lean={lean} 真调用={reading['calls']} 出网={len(got['wire'].bodies)} "
          f"账本行={reading['rows']} duplicate={len(reading['duplicates'])} "
          f"未配对={len(reading['unpaired'])} 未认领={len(reading['unclaimed'])}")
    assert reading["calls"] == len(got["wire"].bodies), (
        "有真缝调用没有落 `llm_call` 事件（或反之）："
        f"事件 {reading['calls']} / 出网 {len(got['wire'].bodies)}")
    problems = RC.one_row_per_call_problems(reading)
    assert problems == [], "判据①红：\n- " + "\n- ".join(problems)


# ============================================================ 判据②：会话归口


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_llm_call_lands_in_this_runs_session(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据②：这一趟所有 `llm_call` 事件都落在本趟 `sid`，缺省会话 0 条。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    split = RC.session_split(got["ws"], SID)
    print(f"[会话归口] lean={lean} 本趟={len(split['in_run'])} "
          f"别处={len(split['elsewhere'])} 会话={sorted(split['by_session'])}")
    assert split["calls"], "这一趟一次真调用都没有 ⇒ 判据没有对象（不是干净）"
    problems = RC.session_problems(split)
    assert problems == [], "判据②红：\n- " + "\n- ".join(problems)


# ============================================================ Lean 两档


@pytest.mark.parametrize("lean,verdict,hidden", [("1", "on", False), ("0", "off", True)])
def test_machine_pass_can_be_true_in_both_lean_modes(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        lean: str, verdict: str, hidden: bool) -> None:
    """Lean 开/关两档：`machine_pass` 都能为真（夹具里有 T3 实验行撑着 load_bearing）。

    这是 `test_load_bearing_without_lean.py` 那条「改前永远真不了」的单点判据在
    链级上的对应物：两档各跑一遍，才不是"另一档没跑所以没红"。
    """
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-1500:], got["stderr"][-1500:])
    reading = LS.lean_reading()
    assert reading.verdict == verdict, reading.to_dict()
    assert LS.is_hidden("L") is hidden, (lean, reading.to_dict())
    closing = _closing_result(_events(got["ws"]))["data"]
    assert closing["machine_pass"] is True, closing.get("status")
    assert all(v == "pass" for v in (closing.get("status") or {}).values()), closing.get("status")
    from agentflow import schema as S

    roles = set(LS.visible_roles(S.ROLES))
    assert ("L" in roles) is (not hidden), sorted(roles)


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))

