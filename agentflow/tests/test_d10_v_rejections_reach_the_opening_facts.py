"""D10：V 判「有毛病」必须进运行期的开场事实（读侧，不建闸）。

## 改前的现场

V 的判决只落 `verifications/<命题号>.jsonl`，而 `agent_loop` 全文 0 处读 `verifications`
⇒ 运行期 F 看不到"V 判过、判的是有毛病"；数据诚实（`statements` 仍 active），
但没有任何人看得见、也没有人去修，只有收工门 R10 事后把它记成 rejected，运行期零后果。

## 这一组钉住两件事

- 开场事实里有一格"我名下被 V 判「有毛病」的证明明细"，条数对、逐条点名
  （命题号 / verdict / unresolved_errors / 最近一签编号 / sha 是否与现文一致）；
- 收工门 R10 的 note 把"0 条高档"拆成四种原因，其中一种就是"V 判有毛病而仍 active 的 N 条"
  —— 那一条与运行期那一格读的是同一个函数（`verifications.statement_review_reading`）。

替身模型与 `tests/test_autonomy.py` 同款，不花模型钱：这一组判的是"读数有没有递到人"，
不是模型答得好不好。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import agent_loop as AL
from agentflow import closing as CL
from agentflow import verifications as VR
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.tools import build_registry

TS = "2026-10-22T10:00:00+08:00"

#: 三条带缝的证明（`有毛病` 那一档的夹具；每一步都指得到第几步错）。
DIRTY_PROOFS = {
    "0001": "1. 显然该族非空（易证）。\n2. 故结论成立。\n",
    "0002": "1. 由定义直接得到 c(G) ≤ 1。\n2. 故结论成立。\n",
    "0003": "1. 取一个反例即可（易证）。\n2. 故结论不成立。\n",
}


class ScriptedGateway:
    """照着剧本回答的替身模型（第一步就收工：这一组只读开场事实）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        """记下 prompt 并回一句合法的 final（带 notify：协议要求）。"""
        self.prompts.append(prompt)
        text = json.dumps({"final": "这一趟只读开场事实", "evidence": [],
                           "notify": {"to": "M", "summary": "读完", "body": "## 结论\n读完了\n"}},
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
    """往 `statements` 里写一行带证明的我方命题（active，与改前真机那个形态一致）。"""
    row = {"stmt_id": stmt_id, "origin": "own_result", "kind": "theorem",
           "statement_full": f"命题 {stmt_id}：设 G 是有限群；则 c(G) ≤ 1。",
           "statement_text": f"命题 {stmt_id}：c(G) ≤ 1。",
           "proof_text": proof, "status": "active", "created_at": TS, "created_by": "test",
           "quote_reason": "我方自产命题，没有外部引文要比对"}
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)


def _reject(root: pathlib.Path, stmt_id: str, proof: str) -> dict[str, Any]:
    """走产品写路径记一条 `有毛病`（与 V 真跑一次同一条路：`record_verification`）。"""
    verdict = VR.parse_verdict(json.dumps({
        "verdict": "有毛病", "defect_step": 1, "quote": "显然该族非空（易证）",
        "why": "第 1 步无条件前提，且用了「易证」这类缝",
        "findings": [{"level": "error", "step": 1, "kind": "缝 + 无条件前提",
                      "detail": "第 1 步写了「显然（易证）」，而族非空需要构造"}],
    }, ensure_ascii=False))
    return VR.record_verification(root, statement_id=stmt_id, proof_text=proof,
                                  verdict=verdict, used_faces=("statements.read",))


def _rejected_workspace(tmp_path: pathlib.Path) -> tuple[Store, Any, Any, pathlib.Path]:
    """三条 `active` 命题 + 三条 `有毛病` 的判决（D10 的夹具）。"""
    st, cond, registry, root = _workspace(tmp_path)
    for stmt_id, proof in DIRTY_PROOFS.items():
        _statement(st, stmt_id, proof)
        got = _reject(root, stmt_id, proof)
        assert got["verdict"] == "有毛病", got
    return st, cond, registry, root


def _facts_text(prompts: list[str]) -> str:
    """开场事实的文本（`v_rejections` 那一格在第 1 步的 user 消息里）。"""
    assert prompts, "模型一次都没被调用 ⇒ 这一组什么都没读到"
    return "\n".join(prompts)


def test_the_opening_facts_name_every_rejected_proof(tmp_path: pathlib.Path) -> None:
    """正控：三条被 V 判「有毛病」⇒ 开场事实里 N=3，且逐条点名（判据 3）。"""
    st, cond, registry, root = _rejected_workspace(tmp_path)
    gw = ScriptedGateway()
    run = AL.run_role("F", "把这三条证明补齐", store=st, registry=registry, conductor=cond,
                      gateway=gw, session_root=root, workspace_root=str(root),
                      sid="t", max_steps=1, from_env=False)
    assert run.stop_reason == "final", run.stop_reason
    text = _facts_text(gw.prompts)
    assert "被 V 判「有毛病」的证明共 3 条" in text, text[-1500:]
    for stmt_id in DIRTY_PROOFS:
        assert stmt_id in text, f"{stmt_id} 没有被点名：{text[-1500:]}"
    # 逐条读数：verdict / unresolved_errors / 最近一签编号 / sha 是否与现文一致
    assert "verdict=有毛病" in text, text[-1500:]
    assert "unresolved_errors=1" in text, text[-1500:]
    assert "v-0000" in text, "最近一签的编号没读到"
    assert "proof_text 与现文一致）：True" in text, "sha 是否与现文一致那一格没读到"


def test_a_clean_ledger_does_not_invent_rejections(tmp_path: pathlib.Path) -> None:
    """负控（反真空）：没有任何判决 ⇒ 开场事实明说"一条都没有"，而不是留空或报 3。"""
    st, cond, registry, root = _workspace(tmp_path)
    _statement(st, "0001", DIRTY_PROOFS["0001"])
    gw = ScriptedGateway()
    AL.run_role("F", "看一眼", store=st, registry=registry, conductor=cond, gateway=gw,
                session_root=root, workspace_root=str(root), sid="t", max_steps=1,
                from_env=False)
    text = _facts_text(gw.prompts)
    assert "被 V 判「有毛病」的证明共" not in text, text[-800:]
    assert "名下没有被 V 判「有毛病」的证明" in text, text[-800:]


def test_negative_control_removing_the_reading_empties_that_fact(
        tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    """反真空：把读侧（`v_rejections_digest`）摘掉 ⇒ 开场事实里就点不出那三条。

    没有这一条，"开场事实里有 3 条"可以靠任何别的路径满足（比如板项那一半）。
    摘掉读侧之后断言必须红 —— 说明这一格真的是"读出来的"，不是"写死的"。
    """
    st, cond, registry, root = _rejected_workspace(tmp_path)
    monkeypatch.setattr(AL, "v_rejections_digest",
                        lambda *a, **kw: ("（名下没有被 V 判「有毛病」的证明）", [], []))
    gw = ScriptedGateway()
    AL.run_role("F", "把这三条证明补齐", store=st, registry=registry, conductor=cond,
                gateway=gw, session_root=root, workspace_root=str(root),
                sid="t", max_steps=1, from_env=False)
    text = _facts_text(gw.prompts)
    assert "被 V 判「有毛病」的证明共 3 条" not in text, (
        "把读侧摘掉之后开场事实里仍然报着 3 条 ⇒ 那条断言不是从台账读出来的")
    for stmt_id in DIRTY_PROOFS:
        assert f"{stmt_id}：verdict=" not in text, f"摘掉读侧之后仍然点名了 {stmt_id}"


def test_r10_splits_no_high_grade_into_four_causes(tmp_path: pathlib.Path) -> None:
    """正控：R10 的"0 条高档"拆成四种原因，其中一种是"V 判有毛病而仍 active 的 3 条"。

    直接调收工门那一格的读法（`closing._leg_reading`）：它正是 `reviewed_proof_rows`
    这条腿的实现，note 与 `zero_causes` 都从它出来 —— 走一遍 gate 只会多铺一份
    报告夹具，判的还是同一个函数。
    """
    st, _cond, _registry, root = _rejected_workspace(tmp_path)
    got, detail = CL._leg_reading(st, "reviewed_proof_rows", root)
    assert got == 0, f"夹具前提：这三条都是「有毛病」，不该有一档高档：{detail.get('counted')}"
    zero = dict(detail.get("zero_causes") or {})
    assert zero, f"note 没有把 0 条拆成四种原因：{detail.get('note')}"
    assert int(zero.get("rejected_still_active") or 0) == 3, zero
    assert sorted(zero.get("rejected_active_ids") or []) == sorted(DIRTY_PROOFS), zero
    note = str(detail.get("note") or "")
    assert "V 判「有毛病」而这一条仍 active 的 3 条" in note, note
    # 四种原因都在同一句里（不许只留第三条，把另外三种挤掉）
    for needle in ("没有位记录的行", "只到 conjecture", "签过但签的是旧版"):
        assert needle in note, (needle, note)
    assert int(detail.get("rejected_active_total") or 0) == 3, detail
