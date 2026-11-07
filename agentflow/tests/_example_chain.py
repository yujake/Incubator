# -*- coding: utf-8 -*-
"""「玩具例子 = 普通命题」这一组的共用夹具（不是判据文件；判据在三个 `test_example_*` 里）。

业主原话（逐字）：

    「对于玩具例子，F和E会协同或独立产出，类型为example，但处理时也可按照statement处理，
      一样落稿，一样审，一样有条件和结论。如果是E侧产出，通常是穷举论证；
      如果是F产出，通常是理论论证。G看到这类如果想收进正文，推荐使用Example环境而非Lemma或Theorem」
    「example这个标签只是给人看的，和普通命题一致」
    「example即玩具例子在实现时尽可能复用F和E原先的产出逻辑。」

这里只有夹具：造工作区、跑 F 侧那一条链（猜想行 → example 手稿 → V 三转 → B 收录）、
跑 E 侧那一条链（穷举实验 example → 形态闸 → B 收录 → V 三转）。零模型调用。
"""
from __future__ import annotations

import contextlib
import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import sign_before_registration  # noqa: E402
from agentflow import conductor as CND  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.agent_f.core import AgentF  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.store import Store  # noqa: E402

from test_agent_v_exhaustion_review import (  # noqa: E402
    EXHAUSTIVE_PROBE, SCRIPT_REL, _v_secretary,
)
from test_proposition_form_gate import _Seam as _FormSeam  # noqa: E402
from test_v_reviews_three_times_before_signing import (  # noqa: E402
    CLEAN_REPLY, _ReviewSeam,
)

PLAN = "0001"
SID_SLOT = "S1"
FULL = "设 G 是 6 阶群；则 G 同构于 C6 或 S3。"
PROOF = ("1. 由 Sylow 第三定理，n_3 ≡ 1 (mod 3) 且 n_3 | 2 ⇒ n_3 = 1。\n"
         "2. 于是 3-Sylow 子群正规；同法 n_2 ∈ {1,3}：n_2=3 时得到 S3，"
         "n_2=1 时两个正规子群直积得到 C6。")
CLAIM = "R(3,4)=9（K_9 的二染色穷举）"
CLAIM_KEY = "ramsey34=9"


def ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def b(st: Store) -> AgentB:
    return AgentB(st, extractor=None, extract_text=None)


def well_formed_seam() -> _FormSeam:
    return _FormSeam({"well_formed": True, "conditions": "设 G 是 6 阶群",
                      "conclusion": "则 G 同构于 C6 或 S3", "problems": [],
                      "decision": "条件与结论都写清了"})


@contextlib.contextmanager
def submitted_by_f():
    """这一趟 V 是 F 派出来的（收方秘书 = `secretary:F`）。"""
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        yield


@contextlib.contextmanager
def submitted_by_e():
    """这一趟 V 是 E 派出来的（收方秘书 = `secretary:E`）。"""
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-e-000001",
                        parent_role="E"):
        yield


def manuscript_text(st: Store, rel: str) -> str:
    return (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")


def verification_rows(st: Store, sid: str) -> list[dict]:
    path = pathlib.Path(st.root) / "verifications" / f"{sid}.jsonl"
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def pending_rows(st: Store) -> list[dict]:
    base = pathlib.Path(st.root) / "verifications" / "pending"
    if not base.is_dir():
        return []
    return [json.loads(ln) for p in sorted(base.glob("*.jsonl"))
            for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def row_of(st: Store, sid: str) -> dict:
    return dict(next(r for r in st.rows("statements")
                     if str(r.get("stmt_id") or "") == sid))


def run_f_example(st: Store) -> dict:
    """F：先立猜想行 → 登记 example 手稿（过形态闸一次）→ V 三转 → B 收录。

    为什么要先立一条猜想行：新的 F 命题在拿到命题号之前手稿只能叫
    `f-proof-plan-0001.md`，而 V 的未在册入口只收按号命名的那一族（计划稿是
    「看过、没签」）。立一行猜想（B-2 允许 `conjecture` 起步）就有了号，F 的手稿
    于是落在 `reports/f-proof-<号>.md` —— 与真机上「先立猜想、再补证明」同一条路。
    """
    agent_b = b(st)
    seeded = agent_b.register_statement(
        origin="own_result", kind="conjecture", statement_full=FULL,
        statement_text=FULL, evidence_kind="heuristic",
        doc_id=S.format_id(0), line_range={"start": 1},
        quote_reason="我方猜想（还没有证明正文）")
    assert seeded.get("ok") is True, seeded
    sid = str(seeded.get("stmt_id") or "")
    assert sid

    seam = well_formed_seam()
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": PLAN})
    f.f_secretary = SEC.Secretary("F", root=st.root, store=st, seam=seam,
                                  enable_model=True)
    got = f._hand_proof(
        full=FULL, text=FULL, body=PROOF, sid=SID_SLOT,
        plan={"plan_id": PLAN, "problem_key": "k1"},
        sg={"sid": SID_SLOT, "text": FULL, "kind": "example"},
        manuscript_text="",
        manuscript_received={"source": "param", "chars": 0,
                             "section_rows": 0, "refs_in_proof": 0},
        cites=[], tier={"kind": "heuristic", "why": "夹具"},
        dependency_rows=[], existing_row=row_of(st, sid))
    assert got.get("ok") is True, got
    rel = str(got.get("manuscript_path") or "")
    assert rel == f"reports/f-proof-{sid}.md", rel
    text = manuscript_text(st, rel)
    body = DS.proof_body(text).strip("\n")

    v = AgentV(st, workspace_root=st.root, llm=_ReviewSeam([CLEAN_REPLY]),
               secretary=_v_secretary(st))
    with submitted_by_f():
        # 一次调用内部就连判到门槛（`review_passes` 是那三转的逐次读数）
        passes = v.verify_proof(statement_id=sid, proof_manuscript=rel)
    signed_text = manuscript_text(st, rel)
    block = VS.manuscript_sign_reading(signed_text, manuscript_path=rel)

    filed = agent_b.register_statement(
        statement_full=FULL, statement_text=FULL, origin="own_result",
        kind="conjecture", label=f"F 攻坚 {PLAN} 子目标 {SID_SLOT}",
        proof_text=body, proof_manuscript=signed_text,
        line_range={"label": rel}, quote_verified=False,
        quote_reason="夹具：V 的签在稿上（按正文 sha）")
    assert filed.get("ok") is True, filed
    return {"store": st, "sid": sid, "rel": rel, "text": text,
            "signed_text": signed_text, "seam": seam, "got": got,
            "passes": passes, "block": block, "filed": filed, "body": body}


def run_e_example(st: Store) -> dict:
    """E：跑一条穷举实验（`kind=example`）→ 过同一道形态闸 → B 收录 → V 三转升档。"""
    script = pathlib.Path(st.root) / SCRIPT_REL
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(EXHAUSTIVE_PROBE, encoding="utf-8")
    seam = well_formed_seam()
    e = AgentE(st, config={}, workspace_root=st.root,
               secretary=SEC.Secretary("E", root=st.root, store=st, seam=seam,
                                       enable_model=True))
    out = e.run_experiment(CLAIM, CLAIM_KEY, SCRIPT_REL, method="numeric",
                           kind="example")
    assert out.get("recorded") is True, out
    assert out.get("evidence_kind") == "proof", out
    rel = str(out.get("proof_manuscript") or "")
    assert rel.startswith("reports/e-proof-"), out.get("manuscript_problems")
    text = manuscript_text(st, rel)
    column = NP.proof_column(dict(st.rows("experiments")[-1]))
    # 命题还没在册时 V 的那一签（按正文 sha；B 登记时按同一个 sha 认领）
    sign_before_registration(st.root, proof_text=column)

    # B 按手稿头那一行落 kind：`example`（与普通命题同一条路，不是新开一档）
    filed = b(st).register_statement(
        origin="own_result", kind="example", label="R(3,4)=9",
        statement_full=CLAIM, statement_text=CLAIM, proof_text=column,
        proof_manuscript=text, evidence_kind="cross_check",
        doc_id=S.format_id(0), line_range={"start": 1},
        quote_verified=False, quote_reason="夹具：E 的穷举证明、V 的 pending 签按 sha 认领")
    assert filed.get("ok") is True, filed
    sid = str(filed.get("stmt_id") or "")
    # V 在册那一支三转：穷举通道由机械会审给，签完把第 1 位（numeric）翻真
    v = AgentV(st, workspace_root=st.root, secretary=_v_secretary(st))
    passes = []
    with submitted_by_e():
        for _i in range(VR.SIGN_STREAK_NEED):
            passes.append(v.verify_proof(sid, proof_text=column,
                                         proof_manuscript=rel))
    return {"store": st, "sid": sid, "rel": rel, "text": text,
            "signed_text": manuscript_text(st, rel),
            "seam": seam, "out": out, "column": column,
            "filed": filed, "passes": passes}
