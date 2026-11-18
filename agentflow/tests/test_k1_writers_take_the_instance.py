# -*- coding: utf-8 -*-
"""K1 收尾②：写者身份收到实例级（V / G 的稿、A 的工具面、E 的报告、F 的检索请求）。

## 业主口径（逐字）

> 每个 F 自己管自己的计划与稿，名册名就是实例身份。

K1 的 19 条里，BATCH1–6 与 CLOSE1 收尾① 已经把 F/E 的计划、稿、claims、ARTIFACTS、
事件、运行期那几件「每支笔一份」的东西接上 `identity`。本批收剩下的四个写盘面：

| # | 判据 | 条目 |
|---|---|---|
| a | V 的实例标签经 config 进 `AgentV.actor`（待签行 / 签文件 / V 稿索引上的写者同源） | VJ-03 |
| b | 签文件的 `envelope.issued_by` 是签发的那一个 V 实例；在册档取判词行自己的 `verifier` | VJ-07 |
| c | E 的 ②③ 报告 `ARTIFACTS.producer` 与实验行同一把尺（实例级 actor） | EM-09 |
| d | A 的工具面写者按 `identity` 现算（与实例内部链路同粒度），不再是一次定死的 `agent-A` | AL-12 |
| e | G 的 `documents.created_by` 是 `agent-G-<实例>`（与同一行的 `owner_task` / `owner_instance` 同源） | GD-01 |
| f | F 的检索请求行带 `submitted_instance`，而 `submitted_by`（I7 契约键）一个字不动 | FX-14 |

反真空都在同一个用例里：摘掉实例标签 ⇒ 读数退回改前形态（角色名 / 历史值）。
"""
from __future__ import annotations

import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import add_literature, seed_writing_material  # noqa: E402
from agentflow import conductor as C  # noqa: E402
from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow import host as H  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import doc_tools as DT  # noqa: E402
from agentflow.tools.search_tools import _Ctx  # noqa: E402

PROPOSITION = "设 X 是有限集，则 |P(X)| = 2^|X|。"


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _artifacts(st: Store) -> list[dict]:
    path = pathlib.Path(st.root) / "ARTIFACTS.jsonl"
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# ------------------------------------------------------------------ a V 的写者身份
def test_a_v_takes_its_instance_label_from_the_host_assembly(tmp_path: pathlib.Path) -> None:
    """a：装配期给的实例标签真的进了 `AgentV.actor`（改前 `_ACTOR_IN_CONFIG` 里没有 V）。"""
    st = _store(tmp_path)
    builder = H._Builder(workspace_root=st.root)
    assert builder.agent_v(st, instance="v2").actor == "agent-V-v2"
    # 反真空：不传实例 ⇒ 与改前逐字相同的角色级 actor。
    assert builder.agent_v(st).actor == "agent-V"


# ------------------------------------------------------------------ b 签的签发者
def test_b_the_sign_names_the_v_instance_that_issued_it(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """b：`issued_by` 是签发的那一个实例；不给 ⇒ 保留历史值 `"V"`。

    台账背书与系统计数两道闸用替身（本用例量的是信封那一格，不是门槛）：替身让签
    真的写成，于是「写出来了」不是断言的前提，而是断言的对象。
    """
    st = _store(tmp_path)
    monkeypatch.setattr(VS, "sign_ledger_backing",
                        lambda *a, **kw: {"ok": True, "rows": [], "why": ""})
    monkeypatch.setattr(
        VS, "_system_count_update",
        lambda *a, **kw: ({"counted_by": "sign_counting", "count": 3, "legacy": False,
                           "counted_passes": [{"review_pass": i} for i in (1, 2, 3)]}, True))
    def _passes(sha: str, base: int) -> list[dict]:
        return [{"review_call": "c1", "review_pass": i, "object_sha256": sha,
                 "verification_id": "u-%06d" % (base + i),
                 "at": "2026-11-19T01:00:00+08:00", "proof_sha256": sha}
                for i in (1, 2, 3)]

    for sha, base, issuer in (("a" * 64, 0, "agent-V-v2"), ("c" * 64, 3, "")):
        passes = _passes(sha, base)
        monkeypatch.setattr(
            VS, "_system_count_update",
            lambda *a, _p=passes, **kw: (
                {"counted_by": "sign_counting", "count": 3, "legacy": False,
                 "counted_passes": _p}, True))
        got = VS.issue(st.root, artifact_sha=sha, streak=3, need=3, passes=passes,
                       ledger=f"verifications/pending/{sha}.jsonl#u-{base + 3:06d}",
                       artifact_path=f"reports/f-proof-{base:06d}.md", issuer=issuer)
        assert got.get("written") is True, got
        # 给了 issuer ⇒ 那一个实例；不给 ⇒ 历史值 "V"（读侧不用多一条分支）。
        assert got["envelope"]["issued_by"] == (issuer or "V"), got.get("envelope")


def test_b2_the_ledger_row_verifier_is_what_the_sign_names(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """b2：在册档签发时，`issuer` 取判词行自己的 `verifier`（不在这里另猜一个）。"""
    from agentflow import verifications as VR

    st = _store(tmp_path)
    seen: dict = {}

    def _fake_issue(root, **kw):
        seen.update(kw)
        return {"written": False, "reason": "判据替身：这一笔不写盘"}

    monkeypatch.setattr(VS, "issue", _fake_issue)
    VR._vsigns_write_after_flip(
        st, row={"verifier": "agent-V-v2", "verification_id": "v-000001"},
        ledger=pathlib.Path("verifications/000001.jsonl"), statement_id="000001",
        proof_no=1, sha="b" * 64, holds={"streak": 3, "need": 3}, append_ledger=False)
    assert seen.get("issuer") == "agent-V-v2", seen
    # 反真空：行上没有 verifier ⇒ 空串（由 `issue` 落回历史值 "V"），不编一个实例。
    seen.clear()
    VR._vsigns_write_after_flip(
        st, row={}, ledger=pathlib.Path("verifications/000001.jsonl"), statement_id="000001",
        proof_no=1, sha="b" * 64, holds={"streak": 3, "need": 3}, append_ledger=False)
    assert seen.get("issuer") == "", seen


# ------------------------------------------------------------------ c E 的报告写者
def test_c_the_e_report_carries_the_instance(tmp_path: pathlib.Path) -> None:
    """c：`land_report` 落的 `ARTIFACTS` 行同时有 producer（角色）与 instance（哪一支笔）。"""
    st = _store(tmp_path)
    got = ER.land_report(str(st.root), experiment_id="000000", claim=PROPOSITION,
                         claim_key="k", script_path="code/x.py",
                         design="全枚举 n≤20", enumeration="逐 n 枚举",
                         instance="e1", task_id="t-000123")
    assert got.get("ok") is True, got
    rel = str(got["path"])
    rows = {row["path"]: row for row in _artifacts(st)
            if str(row.get("kind") or "") == "experiment-report"}
    assert rows[rel]["producer"] == "E", rows[rel]
    assert rows[rel]["instance"] == "e1", rows[rel]
    assert rows[rel]["task_id"] == "t-000123", rows[rel]
    # 反真空：不给身份 ⇒ 与改前逐字相同的两格（producer=E、instance 空）。
    got2 = ER.land_report(str(st.root), experiment_id="000001", claim=PROPOSITION,
                          claim_key="k2", script_path="code/y.py",
                          design="d", enumeration="e")
    rel2 = str(got2["path"])
    row2 = {row["path"]: row for row in _artifacts(st)}[rel2]
    assert (row2["producer"], row2["instance"]) == ("E", ""), row2


# ------------------------------------------------------------------ d A 的工具面
def test_d_the_a_tool_face_resolves_the_writer_per_call(tmp_path: pathlib.Path) -> None:
    """d：工具面的写者按 `identity` 现算（不再是一次装配定死的 `agent-A`）。"""
    st = _store(tmp_path)
    ctx = _Ctx(workspace=pathlib.Path(st.root), store=st)
    # 反真空：没有召唤上下文 ⇒ 角色名（改前的读数）。
    assert ctx.actor == "agent-A"
    with C.calling_as("t-000007", role="A", instance="lit"):
        assert ctx.actor == "agent-A-lit", ctx.actor
    # 调用结束 ⇒ 回到角色名（读数不黏在对象上）。
    assert ctx.actor == "agent-A"
    # 显式绑定且带实例标签的那一档优先（装配期折进来的身份）。
    bound = _Ctx(workspace=pathlib.Path(st.root), store=st, bound_actor="agent-A-lit")
    assert bound.actor == "agent-A-lit"


# ------------------------------------------------------------------ e G 的稿
def test_e_the_g_document_created_by_is_the_instance(tmp_path: pathlib.Path) -> None:
    """e：`documents.created_by` 与同一行的 `owner_*` 同源（实例级）。"""
    st = _store(tmp_path)
    add_literature(st, "0000", title="探针文献", processed=True)
    seed_writing_material(st)
    claim = {"claim_id": "claim-1", "section": "主要结果", "text": "谱落在区间内。",
             "evidence_kind": "cross_check", "citations": ["lit:0000"],
             "is_negative": False, "negation_kind": None,
             "disclaimer": "数值交叉验证，不构成证明"}
    with C.calling_as("t-000042", role="G", instance="g2"):
        row = DT.build_document(
            st, kind="paper", title="探针稿", claims=[dict(claim)],
            sections=[{"heading": "主要结果", "body": "谱落在区间内。"}],
            open_problems=[], actor="agent-G")
    assert row["created_by"] == "agent-G-g2", row["created_by"]
    assert row["owner_task"] == "t-000042", row.get("owner_task")
    assert row["owner_instance"] == "g2", row.get("owner_instance")
    # 反真空：没有实例上下文 ⇒ 改前那个角色名。
    row2 = DT.build_document(
        st, kind="paper", title="探针稿二", claims=[dict(claim)],
        sections=[{"heading": "主要结果", "body": "谱落在区间内。"}],
        open_problems=[], actor="agent-G")
    assert row2["created_by"] == "agent-G", row2["created_by"]
