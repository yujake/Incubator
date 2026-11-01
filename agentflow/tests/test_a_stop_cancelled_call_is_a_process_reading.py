# -*- coding: utf-8 -*-
"""判据：因业主叫停而没执行的那一条，记"停机"类，不混进 `multi_call_unexecuted`。

## 现场（真机 82，2026-11-01 · F-1）

V 步 3 一步给了 2 条 `fs.read`：第 1 条执行成功，第 2 条因"本回合已收工"未执行。
而收工的原因是业主按了停（`runs/stop-history.jsonl` 里 `by="user"`），不是 V 做错。
`errorstats` 把这一档整包记成 `multi_call_unexecuted`（真失败），同一句 `warn` 还在教
"下一步请只发一条调用" —— 与"多调用是能力"（D-65）自相矛盾。

## 这一份钉的四条（改前红）

| 条 | 它要证明的事 | 改前为什么红 |
|---|---|---|
| a | 叫停导致未执行的那一条落"停机"读数（有名字、可计数） | 改前只有 `agent_step_call` + `not_executed`，被算成 `multi_call_unexecuted` |
| b | `multi_call_unexecuted` 不因它增加 | 改前 +1 |
| c | 汇总文案不再在停机这一档教"请只发一条调用" | 改前无论什么原因都拼 `ADVICE` |
| d | 反真空：模型自己 `final` 收工导致未执行的那一条仍算真失败 | 这一条钉"放宽只对停机生效"，不是把未执行整档免掉 |

边界：全部 tmp 工作区、零真实模型调用（网关打桩）；停机开关用 `stopctl.request_stop`
（与用户按停同一条写路径）；不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import errorstats as ES
from agentflow import modelgw as MG
from agentflow import sessions as SS
from agentflow import stepdispatch as SD
from agentflow import stopctl
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "stop-cancelled-call"


class _Gateway:
    """按脚本回原生 `tool_calls`；第一次调用时落一把停机开关（模拟业主按停）。"""

    def __init__(self, script: list[dict] | None = None, *,
                 stop_at: pathlib.Path | None = None) -> None:
        self.script = list(script or [])
        self.stop_at = stop_at
        self.prompts: list[str] = []
        self.spec = MG.ModelSpec(model="stub-model", api_key="x", base_url="http://stub")

    def complete(self, prompt: str, *, scope: str, system: Any = None, max_tokens: Any = None,
                 tools: Any = None, tool_choice: str = "auto") -> MG.ModelReply:
        self.prompts.append(prompt)
        if self.stop_at is not None:
            stopctl.request_stop(self.stop_at, reason="user", by="user")
            self.stop_at = None
        item = self.script.pop(0) if self.script else {"tool_calls": []}
        return MG.ModelReply(ok=True, text=str(item.get("text") or ""),
                             tool_calls=tuple(item.get("tool_calls") or ()),
                             tokens_in=1, tokens_out=1, model="stub-model", scope=scope)


def _call(name: str, args: dict) -> dict:
    return {"id": f"c{len(json.dumps(args))}", "name": name,
            "arguments": json.dumps(args, ensure_ascii=False)}


def _read_call(path: str) -> dict:
    return _call("fs_read", {"path": path})


def _wired(tmp_path: pathlib.Path, *, stop_at: pathlib.Path | None):
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    gw = _Gateway(stop_at=stop_at)
    seam = LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0), sid=SID)
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=root,
                         seam_factory=lambda role: seam, max_steps=4, store=st, sid=SID)
    cond = Conductor(st, policy=None, backend=backend)
    built = build_registry(store=st, conductor=cond, workspace_root=root)
    backend.registry = built.registry
    assert "fs.read" in built.registry.names(), built.skipped
    return st, cond, built.registry, seam, root, gw


def _run(tmp_path: pathlib.Path, script: list[dict], *, stop_at: pathlib.Path | None = None):
    st, cond, registry, seam, root, gw = _wired(tmp_path, stop_at=stop_at)
    gw.script = list(script)
    run = run_role("M", "读两样东西", store=st, registry=registry, conductor=cond,
                   seam=seam, workspace_root=str(root), sid=SID, max_steps=4,
                   from_env=False)
    return run, root


def _events(root: pathlib.Path) -> list[dict]:
    records, problems = SS.read_session(root, sid=SID)
    assert not problems, problems
    return records


def _stats(root: pathlib.Path) -> ES.ErrorStats:
    stats = ES.error_action_stats(root)
    assert stats.checked is True, stats.as_dict()
    return stats


# ============================================ a + b + c：停机那一档


def test_a_stop_cancelled_call_is_a_named_stop_reading(tmp_path):
    """a+b：叫停后剩的那一条进"停机"读数，不进 `multi_call_unexecuted`。"""
    run, root = _run(tmp_path, [
        {"tool_calls": [_read_call("data/statements.json"),
                        _read_call("data/dependencies.json")]},
    ], stop_at=tmp_path / "ws")
    assert run.stop_reason == "stop_file", run.to_dict()
    events = _events(root)
    stats = _stats(root)
    # 先钉那个数：改前它是 1（这一条被算成真失败），改后必须是 0。
    assert stats.category_total("multi_call_unexecuted") == 0, stats.as_dict()
    stopped_kind = getattr(SD, "STEP_CALL_STOPPED_EVENT", "")
    assert stopped_kind, "stepdispatch 里没有停机读数的名字（改前只有 agent_step_call）"
    stopped = [e for e in events if str(e.get("kind") or "") == stopped_kind]
    assert len(stopped) == 1, [e.get("kind") for e in events]
    one = stopped[0]
    assert one.get("not_executed") is True, one
    assert one.get("stop_reading") == SD.STOP_CANCELLED_BY_STOP, one
    assert "叫停" in str(one.get("outcome") or ""), one
    # 这一条不许再以"普通逐条记录"的形态出现（否则读侧仍会把它算成真失败）。
    plain = [e for e in events if str(e.get("kind") or "") == SD.STEP_CALL_EVENT
             and bool(e.get("not_executed"))]
    assert not plain, plain
    # 名字要在读数里看得见（"有名字"是这一条判据的一半）。
    assert one.get("stop_reading"), one


def test_the_summary_does_not_nag_about_multi_call_when_a_stop_cut_it(tmp_path):
    """c：停机导致的未执行，汇总不再说"下一步请只发一条调用"。

    改前红：`StepDispatch.summary` 无条件拼 `ADVICE`；而这一档里模型没有任何
    "多发了一条"的错 —— 多调用是能力（D-65），停是外面按的。
    """
    run, root = _run(tmp_path, [
        {"tool_calls": [_read_call("data/statements.json"),
                        _read_call("data/dependencies.json")]},
    ], stop_at=tmp_path / "ws")
    assert run.stop_reason == "stop_file", run.to_dict()
    last = run.steps[-1]
    summary = str((last.result or {}).get("warn") or "")
    assert summary, last.result
    assert SD.ADVICE not in summary, summary
    assert "叫停" in summary or "停机" in summary, summary


# ============================================ d：反真空


def test_a_self_finished_turn_still_counts_as_a_real_missed_call(tmp_path):
    """d：模型自己 `final` 收工导致没执行的那一条，仍计 `multi_call_unexecuted`。

    这一条是反真空：放宽只对"外面按的停"生效；把未执行整档免掉的话，
    "模型发了 3 条、自己收工只做了 1 条"就再也没有读数了。
    """
    run, root = _run(tmp_path, [
        {"tool_calls": [_call("framework_final", {"final": "我收工了"}),
                        _read_call("data/dependencies.json")]},
    ])
    assert run.stop_reason == "final", run.to_dict()
    events = _events(root)
    stopped_kind = getattr(SD, "STEP_CALL_STOPPED_EVENT", "")
    assert not [e for e in events
                if stopped_kind and str(e.get("kind") or "") == stopped_kind], events
    missed = [e for e in events if str(e.get("kind") or "") == SD.STEP_CALL_EVENT
              and bool(e.get("not_executed"))]
    assert len(missed) == 1, [e.get("kind") for e in events]
    stats = _stats(root)
    assert stats.category_total("multi_call_unexecuted") == 1, stats.as_dict()
