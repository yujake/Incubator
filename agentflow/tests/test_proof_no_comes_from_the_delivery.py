# -*- coding: utf-8 -*-
"""判据：交付里写的「第几份证明」不再决定路径号（产出侧废掉 `pN`）。

## 这条判据替换的是什么

改前 B 从两处读"这是第几份证明"：稿头那一行 `- 证明号：N`（`crafted`）与 D 的携带单
第四列（`carried`），读到就把它当落点号（`_proof_no_from_delivery`）。业主口径：
`pN` 在产出侧废掉了，稿头不再写「证明号」、稿名不再带 `-pN`；路径号归 B 的秘书，
在收录那一笔事务里分配（`manuscriptpaths.assign_path_group`）。于是那两处来源整颗退役。

## 判据（三态：源码面 + 行为面 + 反真空）

| # | 造什么 | 期望 |
|---|---|---|
| a | 稿头写 `- 证明号：2`，而这是该命题的第一份证明 | 路径号 = 1（以秘书分配为准，不是稿头那个 2）；回执不说 `crafted` / `carried` |
| b | 第二份稿的稿头写 `- 证明号：1`（与事实相反） | 路径号 = 2（分配读到已有 1 条 ⇒ N+1）；两处都不采信 |
| c | 源码面 | `_proof_no_from_delivery` 不再存在；`ingest_manuscript` 不再产 `proof_no_mismatch` |
| d | 反真空 | 把唯一的分配实现打成"永远第 1 条" ⇒ b 的路径号断言必须红 |

全部 tmp 工作区、零模型调用；签走 conftest 的真写口。
"""
from __future__ import annotations

import pathlib

import conftest
from agentflow import manuscriptsubmission as MS
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.store import Store

SID = "000001"
DEP_SID = "000002"
PROPOSITION = "对任意有限群 G，若 p 整除 |G|，则 G 有 p 阶元。"
PROOF1 = ("1. 取 G 的一个 Sylow p-子群 P。\n"
          "2. |P| = p^a > 1 ⇒ 取 1 ≠ x ∈ P。")
PROOF2 = ("1. 对 |G| 归纳：取中心元 z，把 G 分成若干共轭类。\n"
          "2. 计数给出 p 阶元。")
REL1 = "reports/b-proof-000001.md"
REL2 = "reports/b-proof-000002.md"


def _ws(tmp_path: pathlib.Path) -> tuple[Store, AgentB]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, AgentB(st, extractor=None, extract_text=None, config={})


def _manuscript(*, sid: str = SID, proof: str, proof_no: int = 0) -> str:
    """一份新形式稿：依赖表只有三列（没有「路径」列）；`proof_no` 只用来造那行稿头。"""
    head = ""
    if proof_no >= 1:
        head += f"- 证明号：{proof_no}\n"   # 老形式那一行：现在只是一个被忽略的字符串
    head += f"- 证据种类：theorem\n"
    deps = ("| 引用 | 命题号 | 步 |\n|---|---|---|\n"
            f"| 引理 | stmt:{DEP_SID} | 1 |\n")
    return (head + "\n## 命题\n\n" + PROPOSITION + "\n\n"
            "## 证明\n\n" + proof + "\n\n## 依赖\n\n" + deps)


def _write(st: Store, rel: str, text: str) -> None:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _citable(st: Store) -> None:
    conftest.seed_statement_row(st, stmt_id=DEP_SID, statement_full="引理：…",
                                kind="lemma", proof_text="引理：…")
    conftest.sign_for_the_gate(st.root, statement_id=DEP_SID,
                               proof_text="引理：…", store=st)
    from agentflow import evidencebits as EB

    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id")) == DEP_SID)
    bits = dict(row.get("bits") or {})
    bits["proof"] = True
    ev = dict(bits.get("evidence") or {})
    ev.setdefault("proof_process", str(row.get("proof_text") or "（夹具：引理）"))
    bits["evidence"] = ev
    bits["grade"] = EB.derive_grade(bits, kind="lemma")
    with st.tx("statements", actor="夹具") as tx:
        tx.upsert("statements", dict(row, bits=bits))


def _signed(st: Store, rel: str, proof: str) -> None:
    conftest.sign_for_the_gate(st.root, statement_id=SID, proof_text=proof,
                               store=st, manuscript=rel)


def _ingest(b: AgentB, rel: str, *, cells: list[str]) -> dict:
    from agentflow import conductor as CND

    task = S.Task(task_id="t-000001", role="B", action="ingest_manuscript",
                  called_by="D", depth=1, status="running", started_at=S.now_iso(),
                  input_key="delivery-proof-no-retired")
    with b.store.tx("tasks", actor="fixture") as tx:
        tx.upsert("tasks", task.to_dict())
    with CND.calling_as("t-000001", "B", parent_task_id="t-000009", parent_role="D"):
        return b.ingest_manuscript(manuscript=rel, target_stmt_id=SID,
                                   cells=cells, mode="apply")


def _path_groups(st: Store) -> list[int]:
    return sorted({int(r.get("path_group") or 1) for r in st.rows("dependencies")
                   if str(r.get("used_by") or "").split("#", 1)[0] == f"stmt:{SID}"})


def _fixture(tmp_path: pathlib.Path) -> tuple[Store, AgentB]:
    st, b = _ws(tmp_path)
    conftest.seed_statement_row(st, stmt_id=SID, statement_full=PROPOSITION,
                                kind="theorem")
    _citable(st)
    _write(st, REL1, _manuscript(proof=PROOF1, proof_no=2))   # 稿头说第 2 份
    _signed(st, REL1, PROOF1)
    _write(st, REL2, _manuscript(proof=PROOF2, proof_no=1))   # 稿头说第 1 份
    _signed(st, REL2, PROOF2)
    return st, b


# ============================================================ a 稿头的号不采信
def test_a_the_header_number_does_not_decide_the_path(tmp_path: pathlib.Path) -> None:
    st, b = _fixture(tmp_path)
    first = _ingest(b, REL1, cells=["proof_text", "dependencies"])
    assert first.get("ok") is True, first
    # 稿头写着 2，而这是第一条路径 ⇒ 号必须来自秘书的分配（1）。
    assert first.get("path_group", {}).get("path_group") == 1, first.get("path_group")
    assert str(first.get("proof_no_source") or "") not in ("crafted", "carried"), first
    assert _path_groups(st) == [1], _path_groups(st)
    deps = [dict(r) for r in st.rows("dependencies")
            if str(r.get("used_by") or "").startswith(f"stmt:{SID}")]
    assert deps and all(int(d.get("path_group") or 0) == 1 for d in deps), deps
    assert not any("#p2" in str(d.get("used_by") or "") for d in deps), (
        f"稿头那个 2 被采信了：{[(d.get('used_by'), d.get('path_group')) for d in deps]!r}")


# ============================================================ b 第二份 = 2
def test_b_the_second_proof_gets_two_regardless_of_its_header(
        tmp_path: pathlib.Path) -> None:
    st, b = _fixture(tmp_path)
    assert _ingest(b, REL1, cells=["proof_text", "dependencies"]).get("ok") is True
    second = _ingest(b, REL2, cells=["proof_text", "dependencies"])
    assert second.get("ok") is True, second
    # 稿头写着 1（与事实相反），而这是第二条路径 ⇒ 号仍来自分配（2）。
    assert second.get("path_group", {}).get("path_group") == 2, second.get("path_group")
    assert _path_groups(st) == [1, 2], _path_groups(st)
    rows, _bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    from agentflow import proofregistry as PR

    by_sha = {str(r.get("proof_sha256")): int(r.get("path_group") or 0) for r in rows}
    assert by_sha[PR.proof_sha(PROOF2)] == 2, by_sha


# ============================================================ c 源码面
def test_c_the_delivery_reading_is_gone(tmp_path: pathlib.Path) -> None:
    from agentflow.agent_b import register_statement as RS

    assert not hasattr(AgentB, "_proof_no_from_delivery"), (
        "`_proof_no_from_delivery` 还在 ⇒ 交付里那个号仍有一条读路径")
    assert not hasattr(RS._RegisterStatement, "_proof_no_from_delivery")
    # `ingest_manuscript` 不再把稿名里的 `-pN` 与参数对拍（`proof_no_mismatch` 整条退役）：
    # 行为面——稿名说第 2 份、参数说第 1 份，不再受控拒，号仍由秘书分配。
    got = RS._RegisterStatement._ingest_proof_no(
        {"name_proof_no": 2}, 1)
    assert got == (1, "", ""), got


# ============================================================ d 反真空
def test_d_stubbing_the_allocation_turns_b_red(tmp_path: pathlib.Path,
                                               monkeypatch) -> None:
    real = MS.assign_path_group

    def _always_one(**_kw):
        return {"checked": True, "path_group": 1, "existing": False, "count": 1,
                "paths": [], "why": "打桩：永远第 1 条"}

    monkeypatch.setattr(MS, "assign_path_group", _always_one)
    st, b = _fixture(tmp_path)
    assert _ingest(b, REL1, cells=["proof_text", "dependencies"]).get("ok") is True
    second = _ingest(b, REL2, cells=["proof_text", "dependencies"])
    ok = bool(second.get("ok"))
    pg = int((second.get("path_group") or {}).get("path_group") or 0)
    groups = _path_groups(st)
    assert (not ok) or pg != 2 or groups != [1, 2], (
        "把分配打成永远第 1 条之后，第二条路径仍然成立 ⇒ 这条判据没有在看分配："
        f"ok={ok} path_group={pg} groups={groups}")
    monkeypatch.setattr(MS, "assign_path_group", real)

# ============================================================ 同种证明那一问的默认回答
import pytest as _pytest  # noqa: E402


@_pytest.fixture(autouse=True)
def _proof_kind_default(monkeypatch):
    """这一组量的是路径号 / 收录，不是同种证明的语义判别 ⇒ 默认回 different。

    2026-11-12 起"同种证明"改由秘书的语义判定给（禁机械闸）；没有判定面时按
    fail-closed 拒收，会把这里的第二份证明全部拒掉。语义判别本身的判据在
    `tests/test_rehearsal_two_f_independent_proofs.py`。
    """
    import agentflow.secretary as _SEC

    real = _SEC.Secretary.judge

    def _judge(self, kind, context, **kw):
        if kind == "proof_kind":
            return {"checked": True, "decision": "different", "same_path": 0,
                    "reason": "夹具：不同种", "basis": [], "cost": {}}
        return real(self, kind, context, **kw)

    monkeypatch.setattr(_SEC.Secretary, "judge", _judge)
