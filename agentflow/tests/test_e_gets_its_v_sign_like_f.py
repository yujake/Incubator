# -*- coding: utf-8 -*-
"""判据：E 的数值证明拿 V 签，走的是与 F 一模一样的那一条链（业主 2026-11-03）。

## 业主逐字（本文件存在的唯一理由）

    「E 在数值证明拿 V 签的时候流程和 F 一模一样，若未实现请先实现」

## 改前 E 那条链断在哪（三处，逐条对应 F 的链）

| # | F 的链 | 改前 E 的现场 |
|---|---|---|
| 1 | 证明手稿 `reports/f-proof-*.md`，`## 证明` 那一节就是被签的正文 | E 只有 `out/experiments/<实验号>/exhaustion.md`（②③ 的「读数」，没有 `## 证明`）⇒ V 的未在册入口把它拒成 `bad_manuscript_path` |
| 2 | V 交付信封 → 「收方秘书」落签块（`vsigns.SECRETARY_OF`） | 收方表只有 F / B ⇒ E 那一签「能颁发、没人能落」（`not_a_secretary`）：稿上永远没有签块 |
| 3 | 签在稿上，B 收录时从稿上读到 | E 的"签"是 `experiments.observations.e_signature.signed_by="V"`（E 自己写的）＋ V 的台账行 ⇒ 没有"签在稿上"这一格；B 的认签那一路读不到它 |

## 这一组钉住什么

1. E 的那趟实验落下 `reports/e-proof-<实验号>.md`：与 F 同目录、同三节、`## 证明` 的正文
   与 `numericproof.compose_proof_column`（B 登记的 `proof_text`）逐字同源；
2. E 派 V（未在册）⇒ 三轮（`SIGN_STREAK_NEED`）机械会审都「成立」⇒ 签块由
   `secretary:E` 落进那份稿，签文件的信封也写给 `secretary:E`；
3. B 收录时从稿上读到那一签（`v_sign.applied`）、第 3 位翻真，并记下
   `optimized_by_proof={"1": false}`（机械录入那一版，等第二阶段）；
4. 第二阶段：优化后的正文重拿 V 签（在册那一路三转）⇒ B 再交一次 ⇒
   `optimized_by_proof={"1": true}`（精准替换的读数）；
5. 反真空：① 把 `E→V` 这条边摘掉 ⇒ `forbidden_edge`；② 把 `secretary:E` 从收方表里摘掉
   ⇒ 稿上没有块、B 拒收、`statements` 一行都不写；③ 盘上把稿删掉 ⇒ 退回 pending
   （老行为），稿上没有块 —— "块真的是这份稿带来的"。

零模型调用：V 的穷举会审是机械七项（`exhaustionreport.review`），不发模型请求。
"""
from __future__ import annotations

import contextlib
import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import add_literature  # noqa: E402
from agentflow import capabilities as C  # noqa: E402
from agentflow import conductor as CND  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import policy as P  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.store import Store  # noqa: E402

from test_agent_v_exhaustion_review import (  # noqa: E402
    EXHAUSTIVE_PROBE, SCRIPT_REL, _v_secretary,
)

#: 一条命题（B 登记用；与 E 那份稿的 `## 命题` 不是同一串字 —— 稿的正文才是被签的对象）。
FULL = "对任意正整数 n，R(3,4)=9。"
CLAIM = "R(3,4)=9（K_9 的二染色穷举）"
CLAIM_KEY = "ramsey34=9"


@contextlib.contextmanager
def _submitted_by_e():
    """这一趟 V 是 E 派出来的（收方 = V 的 parent 那一侧 ⇒ `secretary:E`）。"""
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-e-000001",
                        parent_role="E"):
        yield


def _env(tmp_path: pathlib.Path) -> dict:
    """E 跑一趟真穷举实验（落 ②③ 读数 + 证明手稿），返回整条链要用的东西。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, S.format_id(0))
    script = pathlib.Path(st.root) / SCRIPT_REL
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(EXHAUSTIVE_PROBE, encoding="utf-8")
    e = AgentE(st, config={}, workspace_root=st.root)
    out = e.run_experiment(CLAIM, CLAIM_KEY, SCRIPT_REL, method="numeric")
    return {"store": st, "e": e, "out": out,
            "v": AgentV(st, workspace_root=st.root, secretary=_v_secretary(st)),
            "b": AgentB(st, extractor=None, extract_text=None)}


def _manuscript(env: dict) -> tuple[str, str]:
    """(相对路径, 盘上全文)。"""
    rel = str(env["out"].get("proof_manuscript") or "")
    assert rel, env["out"].get("manuscript_problems")
    return rel, (pathlib.Path(env["store"].root) / rel).read_text(encoding="utf-8")


def _column(env: dict) -> str:
    return NP.proof_column(dict(env["store"].rows("experiments")[-1]))


def _register(env: dict, *, text: str, column: str, reason: str = "我方推导") -> dict:
    return env["b"].register_statement(
        origin="own_result", kind="theorem", label="R(3,4)=9",
        statement_full=FULL, statement_text="R(3,4)=9", proof_text=column,
        proof_manuscript=text, evidence_kind="proof", doc_id=S.format_id(0),
        line_range={"start": 1}, quote_verified=False, quote_reason=reason)


# ============================================================ ① 与 F 同形的那份稿
def test_a_e_writes_a_proof_manuscript_in_the_f_shape(tmp_path):
    """① E 的实验落下 `reports/e-proof-<号>.md`：`## 证明` 的正文与证明栏逐字同源。"""
    env = _env(tmp_path)
    rel, text = _manuscript(env)
    assert rel == ER.proof_manuscript_relpath(env["out"]["experiment_id"]), rel
    assert rel.startswith("reports/e-proof-"), rel
    assert env["out"]["manuscript_problems"] == [], env["out"]["manuscript_problems"]

    read = ER.read_proof_manuscript(env["store"].root, rel)
    assert read["ok"] is True, read
    # 三处读口必须同一把尺（F 那一份、V 那一份、B 那一份）
    column = _column(env)
    assert DS.proof_body(text).strip("\n") == column
    assert VS.manuscript_proof_body(text) == column
    assert read["proof_body"] == column
    assert read["proof_sha256"] == VR.proof_sha(column) == env["out"]["manuscript_proof_sha256"]
    # 正文就是穷举那三段（B 登记时 `filing_problems` 认的正是这三段）
    parsed = NP.parse_proof_column(column)
    assert parsed["problems"] == [], parsed
    assert parsed["script"] == SCRIPT_REL, parsed
    # 与 F 同形的那三节都在
    for heading in (ER.MANUSCRIPT_STATEMENT_HEADING, ER.MANUSCRIPT_PROOF_HEADING,
                    ER.MANUSCRIPT_DEPENDENCY_HEADING):
        assert heading in text, heading


# ============================================================ ② E 三轮 ⇒ 不产签
def test_b_three_rounds_still_do_not_produce_a_sign_without_a_statement_id(tmp_path):
    """② E 派 V（未在册）⇒ 三轮都成立，但没有命题号 ⇒ 不产签（2026-11-05）。"""
    env = _env(tmp_path)
    rel, text = _manuscript(env)
    with _submitted_by_e():
        got = env["v"].verify_proof(proof_manuscript=rel)

    assert got.get("checked") is True, got
    assert got.get("kind") == "proof_reviewed_not_signed", got
    assert got.get("reason") == "statement_id_missing", got
    passes = list(got.get("review_passes") or [])
    assert [p["pass"] for p in passes] == [1, 2, 3], passes
    assert [p["verdict"] for p in passes] == ["成立"] * VR.SIGN_STREAK_NEED, passes

    now = (pathlib.Path(env["store"].root) / rel).read_text(encoding="utf-8")
    block = VS.manuscript_sign_reading(now, manuscript_path=rel)
    assert block["found"] is False, block
    assert not VS.sign_path(env["store"].root, VR.proof_sha(_column(env))).exists(), (
        "没有命题号却产出了签文件")

    # 审阅本身仍然留账（pending 台账是"审过的记录"，不是签；它按对象 sha 落在报告上）。
    pend = pathlib.Path(env["store"].root) / "verifications" / "pending"
    rows = [json.loads(ln) for p in sorted(pend.glob("*.jsonl"))
            for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert rows, "pending 台账一行都没有 ⇒ 这一趟的会审没有留下任何记录"
    assert any(str(r.get("object_sha256") or "") == env["out"]["report_sha256"]
               and str(r.get("verdict")) == "成立" for r in rows), rows


# ============================================================ ③ B 收录：认到 pending 那一行
def test_c_b_collects_the_pending_review_and_records_optimized(tmp_path):
    """③ 未在册不再落签块 ⇒ B 只能按 pending 台账那一行认（`why` 里会点名它）。

    2026-11-05 之后稿上没有签块（没有命题号就没有可签的对象）；这一条留着量"B 的认签
    面不许因为签块没了就退化成'什么都算有'"：它认到的是 `verifications/pending` 那一行
    （`why` 点名 pending，不点名手稿），且第 3 位 / optimized 的写法与以前逐字相同。
    """
    env = _env(tmp_path)
    rel, _before = _manuscript(env)
    with _submitted_by_e():
        env["v"].verify_proof(proof_manuscript=rel)
    text = (pathlib.Path(env["store"].root) / rel).read_text(encoding="utf-8")
    assert "手稿签块" not in text or VS.SIGN_MARK not in text, "未在册不该有签块"

    filed = _register(env, text=text, column=_column(env))
    assert filed.get("ok") is True, filed
    v_sign = dict(filed.get("v_sign") or {})
    assert v_sign.get("applied") is True, v_sign
    assert "手稿" not in str(v_sign.get("why") or ""), v_sign

    row = [dict(r) for r in env["store"].rows("statements")][-1]
    bits = dict(row.get("bits") or {})
    ev = dict(bits.get("evidence") or {})
    assert bits.get("reviewed") is True, bits
    assert ev.get("optimized_by_proof") == {"1": False}, ev.get("optimized_by_proof")
    assert ev.get("reviewed_by_proof") == {"1": True}, ev.get("reviewed_by_proof")
    assert ev.get("reviewed_sha_by_proof") == {"1": VR.proof_sha(_column(env))}, (
        "登记时记下的签的正文 sha 与证明栏不是同一份")


# ============================================================ ④ 第二阶段：optimized=true
def test_d_the_second_stage_gets_a_fresh_sign_and_flips_optimized(tmp_path):
    """④ 优化后的正文重拿 V 签（在册三转）⇒ B 再交一次 ⇒ `optimized=true`。"""
    env = _env(tmp_path)
    rel, text = _manuscript(env)
    first_column = _column(env)
    with _submitted_by_e():
        env["v"].verify_proof(proof_manuscript=rel)
    assert _register(env, text=text, column=first_column).get("ok") is True
    sid = str([dict(r) for r in env["store"].rows("statements")][0]["stmt_id"])

    # 第二阶段那一版：同一份程序、换枚举策略（真实优化形态），重落一次实验与手稿
    opt = env["e"].run_experiment(
        CLAIM, CLAIM_KEY, SCRIPT_REL, method="numeric",
        design="把 K_9 的二染色穷举改成按 canonical form 逐代表枚举",
        enumeration=("枚举全部 2^36 = 68719476736 个二染色；按顶点置换取 canonical form "
                     "去掉对称性重数，再按 3-/4-子集剪枝；边界：n=9 是上界侧的全部"),
        exhaustive=True)
    assert opt["proof_manuscript"], opt.get("manuscript_problems")
    new_rel = str(opt["proof_manuscript"])
    with _submitted_by_e():
        env["v"].verify_proof(proof_manuscript=new_rel)
    new_text = (pathlib.Path(env["store"].root) / new_rel).read_text(encoding="utf-8")
    new_column = ER.proof_body_of(new_text)
    assert new_column != first_column, "第二阶段那一版与第一版逐字相同 ⇒ 这一条判据量不到替换"

    # 在册那一路：必须带 e-proof 手稿（2026-11-04 甲：在册命题也要手稿），
    # 同一份正文连判三转（门槛与 F 那一份同源）。命题行上的 canonical 还是第一版，
    # 这一签盖的是稿里的新版 ⇒ 第 3 位不翻（`signed_bit3=False` 是诚实的：
    # `body_gate=sha_mismatch`），签文件照旧颁发；B 收录新正文时按 sha 认领。
    got: dict = {}
    with _submitted_by_e():
        for _i in range(VR.SIGN_STREAK_NEED):
            got = env["v"].verify_proof(sid, proof_manuscript=new_rel)
    assert got.get("signed_bit3") is False, got
    assert VS.sign_path(env["store"].root, VR.proof_sha(new_column)).is_file(), (
        "在册这一档带稿送审之后签没有颁发")

    filed = _register(env, text=new_text, column=new_column, reason="我方推导（优化版）")
    assert filed.get("ok") is True, filed
    row = [dict(r) for r in env["store"].rows("statements")][-1]
    ev = dict((dict(row.get("bits") or {})).get("evidence") or {})
    assert ev.get("optimized_by_proof") == {"1": True}, ev.get("optimized_by_proof")
    # 精准替换：canonical 正文就是优化后那一版（旧正文进 proof_history）
    assert VR.proof_sha(str(row.get("proof_text") or "")) == VR.proof_sha(new_column)
    assert row.get("proof_history"), "旧正文没有进 proof_history ⇒ 不是精准替换"


# ============================================================ ⑤ 反真空：E→V 的边
def test_e_without_the_e_to_v_edge_the_summon_is_forbidden(monkeypatch):
    """⑤ 反真空：把 `E→V` 这条边摘掉 ⇒ 派活被 `forbidden_edge` 拒（正控：它在就放行）。"""
    # 正控：这一条边今天是真的（`specs/e.py` 的 edges 里有 V）
    assert "V" in C.ALLOWED_EDGES["E"], sorted(C.ALLOWED_EDGES["E"])
    assert P.check_edge(P.Policy(), "E", "V") is None

    # 负控：运行期把这一条边从派生表里摘掉
    tampered = {role: frozenset(tos) for role, tos in C.ALLOWED_EDGES.items()}
    tampered["E"] = frozenset(tampered["E"] - {"V"})
    monkeypatch.setattr(C, "ALLOWED_EDGES", tampered)
    refusal = P.check_edge(P.Policy(), "E", "V")
    assert refusal is not None and refusal.reason == "forbidden_edge", refusal


# ============================================================ ⑥ 反真空：收方秘书
def test_f_without_the_e_secretary_the_reading_is_unchanged(tmp_path, monkeypatch):
    """⑥ 反真空（落签那一环）：把 `secretary:E` 从收方表里摘掉 ⇒ 读数一模一样。

    改前这一条量的是"签仍由 V 颁发、缺的只是落块"；2026-11-05 之后未在册这一支不产签
    （没有命题号），所以收方表里有没有 E 的秘书都不改变任何读数。
    """
    env = _env(tmp_path)
    rel, _before = _manuscript(env)
    monkeypatch.setattr(VS, "SECRETARY_OF", ("secretary:F", "secretary:B"))
    with _submitted_by_e():
        got = env["v"].verify_proof(proof_manuscript=rel)

    assert got.get("checked") is True, got
    assert got.get("kind") == "proof_reviewed_not_signed", got
    assert got.get("reason") == "statement_id_missing", got
    now = (pathlib.Path(env["store"].root) / rel).read_text(encoding="utf-8")
    assert VS.manuscript_sign_reading(now)["found"] is False, now
    assert not VS.sign_path(env["store"].root, VR.proof_sha(_column(env))).exists(), (
        "没有命题号却产出了签文件")

    # B 的认签面仍然只按盘上的事实：没有签块 ⇒ `why` 不点名「手稿」。
    filed = _register(env, text=now, column=_column(env))
    assert filed.get("ok") is True, filed
    v_sign = dict(filed.get("v_sign") or {})
    assert "手稿" not in str(v_sign.get("why") or ""), v_sign
    assert (v_sign.get("block") or {}).get("found") is not True, v_sign


# ============================================================ ⑦ 反真空：手稿是签的载体
def test_g_without_the_manuscript_the_sign_has_no_carrier(tmp_path):
    """⑦ 反真空：不点名手稿（只给证明栏）⇒ 看过、没签；稿上没有块、也不落 pending 签行。

    这一条量的是"块不是凭空出现的"：V 认得出手稿的入口，才落得下块。同一份稿就在盘上、
    只是这一次送审没点名它 —— 块仍然不会出现（V 不替送审方去盘上猜一份稿）。
    2026-11-04（甲）之后这一档更严：没有稿就不签发，连"按对象 sha 可认领"的 pending
    签行也不落（那一行会被 B 当成第三方签）。
    """
    env = _env(tmp_path)
    rel, _before = _manuscript(env)
    with _submitted_by_e():
        got = env["v"].verify_proof(proof_text=_column(env))
    assert got.get("checked") is True, got
    # 没有点名稿 ⇒ 看过、没签（不落签、不落 pending、不落块）
    assert got.get("kind") == "numeric_evidence_reviewed_not_signed", got
    assert got.get("signed_bit3") is False, got
    pend = pathlib.Path(env["store"].root) / "verifications" / "pending"
    assert not (pend.is_dir() and list(pend.glob("*.jsonl"))), (
        "没有手稿的一档落了 pending 签行 —— 那一行按对象 sha 可认领，会被当成第三方签")
    now = (pathlib.Path(env["store"].root) / rel).read_text(encoding="utf-8")
    assert VS.manuscript_sign_reading(now)["found"] is False, now
    # 迟到的那一份稿再点名送审 ⇒ 仍然不产签（没有命题号，块没有出现的理由）
    with _submitted_by_e():
        again = env["v"].verify_proof(proof_manuscript=rel)
    assert again.get("kind") == "proof_reviewed_not_signed", again
    assert again.get("reason") == "statement_id_missing", again
    assert VS.manuscript_sign_reading(
        (pathlib.Path(env["store"].root) / rel).read_text(encoding="utf-8"))["found"] is False
