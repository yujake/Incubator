"""D12：`final` 之前读一次「未了义务」（只做读数，不打回、不拦）。

## 改前的现场

`shape == "final"` 那一支收到就 `break`：模型说「做完了」，框架就把这句话当结论落盘。
而「名下还有两条证明没送 V、或者送了被判定有毛病」这件事在收工那一行
（`agent_run_end`）上一个字都没有 —— 于是欠账只在事后翻 `verifications` 时才发现。

## 这一组钉住什么

- 一趟跑完、名下两条证明没有 `signed` ⇒ `agent_run_end.final_gaps == 2`，且逐条点名；
- 两条都签住 ⇒ `0`（不是「没读」）；
- 没有走到 `final` 的那一趟 ⇒ `None`（三态：没读 ≠ 0 条）；
- 它只是读数：`stop_reason` 仍是 `final`、不打回、不拦收工。

替身模型与 `tests/test_autonomy.py` 同款，不花模型钱。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import agent_loop as AL
from agentflow import sessions as SS
from agentflow import stopctl
from agentflow import verifications as VR
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.tools import build_registry

TS = "2026-10-22T10:00:00+08:00"

#: 两条我方命题的证明（一条签住算一条，未了义务数的就是「有没有 V 的签字」）。
PROOFS = {
    "0001": "1. 取 G = C_n：它是 2-正则、围长为 n。\n2. 故结论成立。\n",
    "0002": "1. 由定义直接得到 c(G) ≤ 1。\n2. 故结论成立。\n",
}


class ScriptedGateway:
    """照剧本回答的替身模型：第一步就给 final（本组判的是收工那一刻的读数）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        """记下 prompt 并回一句合法的 final（带 notify：协议要求）。"""
        self.prompts.append(prompt)
        text = json.dumps({"final": "做完了", "evidence": [],
                           "notify": {"to": "M", "summary": "做完", "body": "## 结论\n做完了\n"}},
                          ensure_ascii=False)
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 5, "tokens_out": 5,
                                  "error_detail": "", "error_kind": ""})()


def _workspace(tmp_path: pathlib.Path) -> tuple[Store, Any, Any, pathlib.Path]:
    """造一个临时工作区 + 真工具层（模型由替身回答）。"""
    st = Store(tmp_path / "ws")
    st.init()
    cond = Conductor(st, backend=LocalBackend({}))
    registry = build_registry(store=st, conductor=cond, workspace_root=str(st.root)).registry
    return st, cond, registry, st.root


def _statement(st: Store, stmt_id: str, proof: str) -> None:
    """往 `statements` 里写一行带证明的我方命题。"""
    row = {"stmt_id": stmt_id, "origin": "own_result", "kind": "theorem",
           "statement_full": f"命题 {stmt_id}：设 G 是有限群；则 c(G) ≤ 1。",
           "statement_text": f"命题 {stmt_id}：c(G) ≤ 1。",
           "proof_text": proof, "status": "active", "created_at": TS, "created_by": "test",
           "quote_reason": "我方自产命题，没有外部引文要比对"}
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)


def _sign(root: pathlib.Path, stmt_id: str, proof: str) -> dict[str, Any]:
    """走产品写路径签一条「成立」（与 V 真跑一次同一条路）。"""
    verdict = VR.parse_verdict('{"verdict": "成立", "findings": []}')
    return VR.record_verification(root, statement_id=stmt_id, proof_text=proof,
                                  verdict=verdict, used_faces=("statements.read",))


def _run_end(tmp_path: pathlib.Path, st: Store, cond: Any, registry: Any,
             root: pathlib.Path, *, stop_before: bool = False) -> dict[str, Any]:
    """跑一趟循环，返回那一条 `agent_run_end` 事件（收工那一行）。"""
    if stop_before:
        stopctl.request_stop(root, reason="user", by="user")
    AL.run_role("D", "把这两条命题的证明补齐", store=st, registry=registry, conductor=cond,
                gateway=ScriptedGateway(), session_root=root, workspace_root=str(root),
                sid="t", max_steps=2, from_env=False)
    events, problems = SS.read_session(root, sid="t")
    assert not problems, problems
    ends = [e for e in events if e.get("kind") == "agent_run_end"]
    assert len(ends) == 1, [e.get("kind") for e in events]
    return ends[0]


def test_two_unsigned_proofs_are_counted_at_the_final_step(tmp_path: pathlib.Path) -> None:
    """正控：两条有证明、一条都没签 ⇒ `final_gaps == 2`（并逐条点名）。"""
    st, cond, registry, root = _workspace(tmp_path)
    for stmt_id, proof in PROOFS.items():
        _statement(st, stmt_id, proof)
    end = _run_end(tmp_path, st, cond, registry, root)

    assert end.get("stop_reason") == "final", end
    assert end.get("final_gaps") == 2, (end.get("final_gaps"), end.get("final_gaps_reading"))
    detail = dict(end.get("final_gaps_reading") or {})
    assert detail.get("checked") is True, detail
    assert sorted(detail.get("stmt_ids") or []) == sorted(PROOFS), detail
    assert detail.get("unsigned") == 2 and detail.get("total") == 2, detail
    # 它也进这一趟的 notes（收工那一行的读者不必自己去解析 detail）
    assert any("没有 V 的签字" in str(n) for n in (end.get("notes") or [])), end.get("notes")


def test_a_fully_signed_ledger_reads_zero_not_missing(tmp_path: pathlib.Path) -> None:
    """负控（三态的中间那档）：两条都签住 ⇒ `0`（不是 `None`，也不是「没读」）。"""
    st, cond, registry, root = _workspace(tmp_path)
    for stmt_id, proof in PROOFS.items():
        _statement(st, stmt_id, proof)
        got = _sign(root, stmt_id, proof)
        assert got["verdict"] == "成立", got
    end = _run_end(tmp_path, st, cond, registry, root)

    assert end.get("final_gaps") == 0, (end.get("final_gaps"), end.get("final_gaps_reading"))
    detail = dict(end.get("final_gaps_reading") or {})
    assert detail.get("checked") is True and detail.get("stmt_ids") == [], detail
    assert not any("没有 V 的签字" in str(n) for n in (end.get("notes") or [])), end.get("notes")


def test_a_run_that_never_reaches_final_reads_none_not_zero(tmp_path: pathlib.Path) -> None:
    """负控（第三态）：没走到 `final` 的那一趟 ⇒ `None`（「没读」不许折成「0 条」）。"""
    st, cond, registry, root = _workspace(tmp_path)
    for stmt_id, proof in PROOFS.items():
        _statement(st, stmt_id, proof)
    end = _run_end(tmp_path, st, cond, registry, root, stop_before=True)

    assert end.get("stop_reason") == "stop_file", end
    assert end.get("final_gaps") is None, (end.get("final_gaps"), end.get("final_gaps_reading"))
    assert dict(end.get("final_gaps_reading") or {}) == {}, end.get("final_gaps_reading")
