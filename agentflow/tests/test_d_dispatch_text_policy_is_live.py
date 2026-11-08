# -*- coding: utf-8 -*-
"""判据④：`dispatchpolicy.dispatch_text_problems` 要在派活那一刻管用。

## 真机背景（业主 2026-11-08 裁定，逐字）

> 「那条猜想只是参考意见，D 不能直接把自己的猜想登记到命题台账，也不能命令 E 或 F
>   必须把它做出来，这只是研究方向参考」

`specs/d.py:272` 与 `agent_skills.py:2951,2980` 都写着"机器可核"，判据本体
`dispatchpolicy.dispatch_text_problems` 也确实写好了 —— 但改前它零调用点（只有直调
测试在用它）⇒ 这条裁定在运行期没有任何约束。

## 这一份钉的三条

| 条 | 造什么 | 期望 |
|---|---|---|
| a | D 派 F 的 `task` 里写了自己登记的 `conj:000003` / 裸 6 位号 | 那一步受控拒（`invalid_params`）且拒信点名 `000003`；`tasks` 里没有 F 那行 |
| b | D 只写研究方向（不提号） | 不被这条判据拦（`dispatch_policy.violations` 为空） |
| c | 反真空：同一段文本，但 `conjectures` 台账里没有那个号 | 不拦（判据读的是台账，不是"看到 6 位数字就红"） |

零网络、零模型：替身模型只回剧本，派活被这条闸拦在 `_execute` 之前。
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_loop as AL
from agentflow import schema as S
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.tools import build_registry

CONJ_ID = "000003"
REFUSED = "dispatch_names_a_conjecture_id"


class _Scripted:
    """照剧本回答的替身模型：每次取一条，取完重复最后一条。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None, **kw):
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _world(tmp_path: pathlib.Path, *, register_conjecture: bool = True):
    st = Store(tmp_path / "ws")
    st.init()
    if register_conjecture:
        with st.tx("conjectures", actor="test") as tx:
            tx.upsert("conjectures", {
                "conjecture_id": CONJ_ID, "statement": "对每个 n≥3 都有 c(G) ≤ 1。",
                "form": "universal", "testable": {"bounds": {"n": 20}},
                "status": "proposed", "origin": "gap",
                "created_at": S.now_iso(), "created_by": "test"})
    gw = _Scripted([])
    backend = AL.LlmBackend(inner=LocalBackend({}), loops={},
                            session_root=st.root, store=st, sid="t")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond).registry
    return st, cond, reg, gw


def _drive(st: Store, cond, reg, gw, *, task: str) -> AL.LoopRun:
    gw.replies = [json.dumps({"summon": {"role": "F", "task": task,
                                        "params": {"problem": task}}},
                             ensure_ascii=False),
                  json.dumps({"final": "这一步试过了，见读数", "evidence": []},
                             ensure_ascii=False)]
    return AL.run_role("D", "派活：把一个研究方向交给 F", store=st, registry=reg,
                       conductor=cond, gateway=gw, session_root=st.root, sid="t",
                       from_env=False, max_steps=3)


def _summon_result(run: AL.LoopRun) -> dict:
    step = next((s for s in run.steps if s.shape == "summon"), None)
    assert step is not None, [s.shape for s in run.steps]
    return dict(step.result)


def _f_task_rows(st: Store) -> list[dict]:
    return [r for r in st.rows("tasks") if str(r.get("role") or "") == "F"]


# ============================================================ a：点名 ⇒ 受控拒

def test_a_a_dispatch_that_names_its_own_conjecture_is_refused(
        tmp_path: pathlib.Path) -> None:
    st, cond, reg, gw = _world(tmp_path)
    run = _drive(st, cond, reg, gw, task=f"把 {CONJ_ID} 这条猜想证出来（必须做）")
    got = _summon_result(run)
    assert got.get("ok") is False, got
    assert got.get("refused") == REFUSED, got
    assert got.get("refusal_reason") == "invalid_params", got
    assert CONJ_ID in str(got.get("detail") or ""), got
    assert "参考意见" in str(got.get("detail") or ""), got
    pol = dict(got.get("dispatch_policy") or {})
    assert pol.get("checked") is True, pol
    hits = [v for v in (pol.get("violations") or []) if v.get("conjecture_id") == CONJ_ID]
    assert hits, pol
    assert any(v.get("kind") == "dispatch" for v in hits), hits
    assert hits[0].get("token") == CONJ_ID, hits
    # 这条派活没有落成 F 的任务行（受控拒 = 真的没有派出去）。
    assert _f_task_rows(st) == [], _f_task_rows(st)


# ============================================================ b：只写方向 ⇒ 不拦

def test_b_a_direction_only_dispatch_is_not_blocked(tmp_path: pathlib.Path) -> None:
    st, cond, reg, gw = _world(tmp_path)
    run = _drive(st, cond, reg, gw,
                 task="弄清这一族在 n≤20 时的界；可以试母函数与 Fourier 两条路")
    got = _summon_result(run)
    assert got.get("refused") != REFUSED, got
    pol = dict(got.get("dispatch_policy") or {})
    assert pol.get("checked") is True, pol
    assert pol.get("violations") == [], pol


# ============================================================ c：反真空

def test_c_without_the_registered_id_the_same_text_is_not_blocked(
        tmp_path: pathlib.Path) -> None:
    """c（反真空）：同一段带 6 位号文本，台账里没有那个号 ⇒ 不拦。

    若判据退化成"看到 6 位数字就红"，这一条会红 —— 它证明红来自
    "`conjectures` 台账里真有这个号"（`dispatchpolicy.conjecture_ids_of` 的读数）。
    """
    st, cond, reg, gw = _world(tmp_path, register_conjecture=False)
    run = _drive(st, cond, reg, gw, task=f"把 {CONJ_ID} 这条猜想证出来（必须做）")
    got = _summon_result(run)
    assert got.get("refused") != REFUSED, got
    pol = dict(got.get("dispatch_policy") or {})
    assert pol.get("checked") is True, pol
    assert pol.get("violations") == [], pol
    assert pol.get("conjectures") == [], pol
