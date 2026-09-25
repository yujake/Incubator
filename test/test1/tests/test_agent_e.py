"""智能体 E（`agent_e.py` + `tools/verify_tools.py`）的性质测试。

E 的核心是"**产出证据，不产出结论**"。这里锁住六条最容易悄悄做错的性质：

- 正常脚本能被登记，且 `code_hash` / `exit_code` 如实落库（可复现性绑定）；
- **脚本自报 `evidence_kind="proof"` 必须被降级**（负控：让被判定的对象自己
  当判官，等于没有判官）；
- **崩溃 / 超时 / 无结论行一律 `inconclusive`**（负控：不得把崩溃写成支持）；
- `Experiment` 的 schema 硬约束逐条生效（直接对 schema 构造，不经 E）；
- `evidence_for` 的三态：**没查 ≠ 查了没有**，且 `proved` 只在有 proof 级
  证据时为真（FC-22）；
- 路径越界被拒绝。

全部离线、确定性：不联网、不依赖仓库里的任何外部文件，脚本都是现写现跑。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from abflow import schema as S
from abflow.agent_e import AgentE, ExperimentError
from abflow.store import Store
from abflow.tools import verify_tools as VT

TS = "2026-01-01T00:00:00+00:00"

#: 一个"诚实"的探针脚本：只报告观察结果，不声称证据等级之外的东西。
HONEST_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {"grid": 64, "max_err": 1e-9},
    "counterexample": None,
    "negation_kind": "not_proved",
}))
"""

#: 一个"越权"的探针脚本：它自己声称这是证明。数值实验拿不到 proof（FC-22）。
LYING_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "proof",
    "observations": {"points": 100000},
    "counterexample": None,
    "negation_kind": "not_proved",
}))
"""


# ============================================================ 辅助


def write_script(store: Store, rel: str, body: str) -> str:
    """在工作区里写一个脚本，返回相对路径。

    ⚠️ 必须落在 `store.root` 内（它同时是 E 的 workspace_root）：
    越界的路径应当被 E 拒绝，测试要用另一条路径专门验证那件事。
    """
    p = Path(store.root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


def make_e(store: Store, **cfg) -> AgentE:
    return AgentE(store, config=dict(cfg), workspace_root=store.root)


def add_experiment(store: Store, **kw) -> dict:
    """直接插一条合法的 experiments 行（供"证明过/没证明过"两态用）。"""
    fields = {
        "experiment_id": "0000",
        "claim": "某命题",
        "claim_key": "K",
        "method": "numeric",
        "evidence_kind": "cross_check",
        "result": "supports",
        "negation_kind": "not_proved",
        "created_at": TS,
    }
    fields.update(kw)
    row = S.Experiment(**fields)
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())
    return row.to_dict()


# ============================================================ [1] 正常路径


def test_run_experiment_records_row_with_hash_and_exit_code(store):
    """跑一个真实的小脚本 ⇒ 登记成功，`code_hash` 非空、`exit_code == 0`。"""
    rel = write_script(store, "probes/honest.py", HONEST_PROBE)
    out = make_e(store).run_experiment("对 n<=64 的网格 Spec K(m)=[-m,m]", "SpecK(m)=[-m,m]", rel)

    assert out["recorded"] is True
    assert out["exit_code"] == 0
    assert out["result"] == "supports"
    assert out["evidence_kind"] == "cross_check"
    assert out["negation_kind"] == "not_proved", "数值支持只能导致 not_proved（不是 disproved）"
    assert out["code_hash"], "给了 code_path 就必须有 code_hash"
    assert out["experiment_id"] == "0000"

    rows = store.rows("experiments")
    assert len(rows) == 1
    row = rows[0]
    # 哈希必须是**那个文件内容**的哈希（不是随便一个非空字符串）
    assert row["code_hash"] == hashlib.sha256((Path(store.root) / rel).read_bytes()).hexdigest()[:16]
    assert row["code_path"] == "probes/honest.py", "记录的必须是工作区内相对路径"
    assert row["observations"] == {"grid": 64, "max_err": 1e-9}
    assert row["created_by"] == "agent-E"


def test_code_hash_is_reused_from_verify_tools_not_reimplemented(store):
    """哈希只有一份实现：工具的 `verify.code_hash` 与 E 写进表的值必须一致。"""
    rel = write_script(store, "probes/honest.py", HONEST_PROBE)
    e = make_e(store)
    got = e.tools.call("verify.code_hash", path=rel)
    assert got.ok
    out = e.run_experiment("同一份脚本", "same-script", rel)
    assert got.data["code_hash"] == out["code_hash"] == VT.code_hash(Path(store.root) / rel)


# ============================================================ [2] 负控：自报 proof


def test_script_self_reported_proof_is_downgraded_and_noted(store):
    """**负控**：脚本自报 `evidence_kind="proof"` ⇒ 降级为 `cross_check`，且 notes 记录这次越权。

    FC-22 的运行期那一半：schema 拦得住"存进去的谎话"，拦不住"脚本以为自己证明了"。
    两半都要有 —— 只靠 schema 的话，脚本的越权会被静默改写成 cross_check 而不留痕，
    于是没人能解释"为什么这条记录的等级比脚本里写的低"。
    """
    rel = write_script(store, "probes/lying.py", LYING_PROBE)
    out = make_e(store).run_experiment("数值实验不得自称证明", "selfclaimed-proof", rel, method="numeric")

    assert out["evidence_kind"] == "cross_check", "脚本自报 proof 必须被拒绝"
    assert out["result"] == "supports"
    assert "proof" in out["notes"]
    assert "降级" in out["notes"] and "cross_check" in out["notes"]
    # 落库的那一行也必须是降级后的值（不能只在返回值里降级）
    assert store.rows("experiments")[0]["evidence_kind"] == "cross_check"


def test_formal_method_keeps_proof_only_because_schema_requires_verifier_output(store):
    """反误伤：`method="formal"` 时脚本自报 proof **不**被降级为 cross_check。

    但 E 的 run_experiment 不产生 verifier_output，所以这条记录仍会因
    "proof 必须有检查器输出"被 schema 拒 —— 那条路径由 `check_formal` 负责。
    本用例只断言"降级规则只针对计算类方法"这一条边界。
    """
    rel = write_script(store, "probes/lying.py", LYING_PROBE)
    with pytest.raises(ValueError) as ei:
        make_e(store).run_experiment("形式化方法", "formal-claim", rel, method="formal")
    # schema 拒绝的理由必须是"缺 verifier_output"，**不是**"计算类方法不得声称 proof"
    assert "verifier_output" in str(ei.value)
    assert store.rows("experiments") == [], "schema 拒绝时必须一行都没写"


# ============================================================ [3] 负控：崩溃 / 超时 / 无结论


def test_crash_is_inconclusive_not_support(store):
    """**负控**：`exit_code != 0` ⇒ `inconclusive` + `no_local_evidence`（崩溃不得写成支持）。"""
    rel = write_script(
        store,
        "probes/crash.py",
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result':'supports','evidence_kind':'cross_check'}))\n"
        "raise SystemExit(3)\n",
    )
    out = make_e(store).run_experiment("崩溃脚本", "crash", rel)
    assert out["exit_code"] == 3
    assert out["result"] == "inconclusive", "崩溃被写成了正面结论"
    assert out["negation_kind"] == "no_local_evidence"
    # 即使脚本**已经打印了** supports，也不能被采信：exit_code 优先
    assert store.rows("experiments")[0]["result"] == "inconclusive"


def test_missing_repro_result_line_is_inconclusive_with_notes(store):
    """脚本不打印 `REPRO_RESULT` 行 ⇒ `inconclusive` + `no_local_evidence`，notes 说明原因。"""
    rel = write_script(store, "probes/silent.py", "print('nothing structured here')\n")
    out = make_e(store).run_experiment("没有结构化结论", "silent", rel)
    assert out["result"] == "inconclusive"
    assert out["negation_kind"] == "no_local_evidence"
    assert "未给出结构化结论" in out["notes"]
    assert out["exit_code"] == 0, "脚本自己是正常退出的 —— 失败的是'没有结论'，不是'跑崩了'"


def test_broken_json_conclusion_is_inconclusive_and_attributed(store):
    """`REPRO_RESULT` 行不是合法 JSON ⇒ 不认这条结论，且 notes 归因到"JSON 坏了"。

    FC-15：`没写结论` 与 `写坏了结论` 必须能分开计数 —— 它们的修法完全不同。
    """
    rel = write_script(store, "probes/badjson.py", "print('REPRO_RESULT: {not json')\n")
    out = make_e(store).run_experiment("坏 JSON", "badjson", rel)
    assert out["result"] == "inconclusive"
    assert "JSON" in out["notes"]
    assert "未给出结构化结论" not in out["notes"], "这两种失败必须可归因分离"


def test_timeout_is_inconclusive_and_reason_is_visible(store):
    """超时（`time.sleep` + 小 timeout）⇒ `inconclusive`，且原因在 notes 里可见。"""
    rel = write_script(store, "probes/slow.py", "import time\ntime.sleep(30)\n")
    out = make_e(store).run_experiment("超时脚本", "slow", rel, timeout=1)
    assert out["result"] == "inconclusive"
    assert out["negation_kind"] == "no_local_evidence"
    assert out["exit_code"] is None, "超时的进程是被杀掉的，没有正常退出码"
    assert "超时" in out["notes"]
    assert out["runtime_sec"] is not None and out["runtime_sec"] < 20


def test_path_escaping_is_refused(store, tmp_path):
    """**负控**：`script_path` 越出工作区 ⇒ 拒绝（相对越界与绝对路径都拒）。"""
    outside = Path(store.root).parent / "outside_probe.py"
    outside.write_text(HONEST_PROBE, encoding="utf-8")
    e = make_e(store)
    with pytest.raises(ExperimentError) as ei:
        e.run_experiment("越界脚本", "escape-rel", "../outside_probe.py")
    assert "越出工作区" in str(ei.value)
    with pytest.raises(ExperimentError):
        e.run_experiment("越界脚本", "escape-abs", str(outside))
    assert store.rows("experiments") == [], "被拒绝的实验不得留下任何行"


def test_missing_script_is_refused_before_any_write(store):
    """脚本不存在 ⇒ 当场抛（不是登记一条 inconclusive —— 那会把'没跑'记成'跑了没结论'）。"""
    with pytest.raises(ExperimentError):
        make_e(store).run_experiment("不存在的脚本", "missing", "probes/nope.py")
    assert store.rows("experiments") == []


# ============================================================ [4] schema 硬约束负控（不经 E）


def _experiment(**kw) -> S.Experiment:
    fields = {
        "experiment_id": "0000",
        "claim": "c",
        "claim_key": "k",
        "method": "numeric",
        "created_at": TS,
    }
    fields.update(kw)
    return S.Experiment(**fields)


def test_schema_rejects_numeric_experiment_claiming_proof():
    """负控：`method="numeric"` + `evidence_kind="proof"` ⇒ `validate()` 抛（FC-22 的机械落地）。"""
    row = _experiment(method="numeric", evidence_kind="proof", verifier_output="fake checker output")
    with pytest.raises(ValueError) as ei:
        row.validate()
    assert "不得声称" in str(ei.value)


def test_schema_accepts_formal_proof_with_verifier_output():
    """防误伤：`method="formal"` + `evidence_kind="proof"` + 非空 `verifier_output` ⇒ 通过。"""
    row = _experiment(
        method="formal",
        evidence_kind="proof",
        verifier_output="Lean 4: no goals",
        # ⚠️ 新硬约束（来自对 DeepMath 的观摩）：检查器输出必须**绑定到它管的那个命题**。
        # 没有它时，"把命题 A 的检查器输出粘到命题 B 的行上"在结构上合法。
        verifier_subject_key="k",
        result="supports",
        negation_kind="not_proved",
        exit_code=0,
    )
    row.validate()  # 不抛即通过


def test_schema_rejects_refutes_without_counterexample():
    """负控：`result="refutes"` 但 `counterexample` 为空 ⇒ 抛（证否必须可复核）。"""
    with pytest.raises(ValueError) as ei:
        _experiment(result="refutes", counterexample=None, negation_kind="disproved").validate()
    assert "counterexample" in str(ei.value)


def test_schema_rejects_refutes_with_wrong_negation_kind():
    """负控：`result="refutes"` 且 `negation_kind != "disproved"` ⇒ 抛（FC-25）。"""
    with pytest.raises(ValueError) as ei:
        _experiment(result="refutes", counterexample={"m": 7}, negation_kind="not_proved").validate()
    assert "disproved" in str(ei.value)


def test_schema_rejects_supports_without_negation_kind():
    """负控：`result="supports"` 且 `negation_kind=None` ⇒ 抛（三种否定必须分类）。"""
    with pytest.raises(ValueError) as ei:
        _experiment(result="supports", negation_kind=None).validate()
    assert "negation_kind" in str(ei.value)


def test_schema_rejects_code_path_without_code_hash():
    """负控：`code_path` 非空但 `code_hash` 空 ⇒ 抛（没有哈希的"可复现"只是口号）。"""
    with pytest.raises(ValueError) as ei:
        # 其余字段都填成合法的，好让校验**走到** code_hash 那一条
        # （否则会先被 result/negation_kind 的约束拦下，测到的就不是这条规则了）
        _experiment(result="supports", negation_kind="not_proved", code_path="probes/x.py", code_hash="").validate()
    assert "code_hash" in str(ei.value)


def test_schema_rejects_crash_recorded_as_support():
    """负控：`exit_code=1` 且 `result="supports"` ⇒ 抛（崩溃不得被写成支持）。"""
    with pytest.raises(ValueError) as ei:
        _experiment(exit_code=1, result="supports", negation_kind="not_proved").validate()
    assert "inconclusive" in str(ei.value)


# ============================================================ [5] evidence_for 三态与 FC-22


def test_evidence_for_three_states(store):
    """三态：没查（`checked=False`）/ 查了没有（`checked=True, experiments=[]`）/ 查到了。"""
    e = make_e(store)
    not_checked = e.evidence_for()
    assert not_checked["checked"] is False
    assert not_checked["experiments"] == []
    assert not_checked["best_evidence_kind"] is None
    assert not_checked["proved"] is False
    assert "没查" in not_checked["reason"]

    none_found = e.evidence_for("不存在的命题键")
    assert none_found["checked"] is True
    assert none_found["experiments"] == []
    assert none_found["best_evidence_kind"] is None
    assert none_found["proved"] is False
    assert "没有" in none_found["reason"], "必须是'查了、没有'的语义"

    add_experiment(store, claim_key="K", evidence_kind="cross_check")
    found = e.evidence_for("K")
    assert found["checked"] is True
    assert len(found["experiments"]) == 1
    assert found["best_evidence_kind"] == "cross_check"
    assert found["proved"] is False, "cross_check 永远不算已证明"
    # FC-10：结果分档计数，不许只给一个布尔
    assert found["result_counts"] == {"supports": 1, "refutes": 0, "inconclusive": 0}
    assert found["negation_counts"]["not_proved"] == 1


def test_evidence_for_proved_only_with_proof_level_experiment(store):
    """`proved` 只在存在 `evidence_kind == "proof"` 的实验时为真（FC-22 的 gate）。"""
    e = make_e(store)
    add_experiment(store, experiment_id="0000", claim_key="K", method="numeric", evidence_kind="cross_check")
    add_experiment(store, experiment_id="0001", claim_key="K", method="symbolic", evidence_kind="heuristic")
    assert e.evidence_for("K")["proved"] is False

    add_experiment(
        store,
        experiment_id="0002",
        claim_key="K",
        method="formal",
        evidence_kind="proof",
        verifier_output="Lean 4: no goals",
        # 新硬约束：检查器输出必须绑定到它管的命题（否则能把 A 的输出贴到 B 上）
        verifier_subject_key="K",
        exit_code=0,
    )
    got = e.evidence_for("K")
    assert got["proved"] is True
    assert got["best_evidence_kind"] == "proof"
    assert len(got["experiments"]) == 3, "三种等级的实验都要被列出（不是只列最强的）"


def test_evidence_for_filters_by_question_id(store):
    """`for_question_id` 只在**精确相等**时命中：不同问题的实验不得互相背书。"""
    add_experiment(store, experiment_id="0000", claim_key="K", for_question_id="0001")
    add_experiment(store, experiment_id="0001", claim_key="K", for_question_id="0002")
    e = make_e(store)
    assert len(e.evidence_for("K")["experiments"]) == 2
    only_1 = e.evidence_for(for_question_id="0001")
    assert [r["experiment_id"] for r in only_1["experiments"]] == ["0000"]
    assert e.evidence_for(for_question_id="0009")["experiments"] == []


# ============================================================ [6] check_formal 的三态


def test_check_formal_without_backend_is_not_checked_not_failed(store, monkeypatch):
    """无后端 ⇒ `checked=False, reason="no_backend"`，**不是** `verified=False`。

    把"没验证"与"验证没过"折叠成同一个 `False`，下游就会把"本环境没有证明检查器"
    读成"这个命题被证伪了" —— 这正是本项目反复踩到的三态坑。
    """
    monkeypatch.setattr(
        VT,
        "detect_verifier",
        lambda: {"checked": True, "available": [], "available_names": [], "reason": "（测试注入：无检查器）"},
    )
    got = make_e(store).check_formal("1 + 1 = 2")
    assert got["checked"] is False
    assert got["reason"] == "no_backend"
    assert got["verified"] is None, "没验证必须是 None，不能是 False"
    assert got["verifier_output"] == ""
    # 反误伤：这个返回值不能被读成"验证失败"
    assert got["reason"] != "verification_failed"


# ============================================================ [7] 事务性与事件日志


def test_one_run_writes_exactly_one_row_and_one_event(store):
    """一次 `run_experiment` 只产生一行 `experiments`，且 `events.jsonl` 有对应 upsert。"""
    rel = write_script(store, "probes/honest.py", HONEST_PROBE)
    before = len(store.read_events())
    make_e(store).run_experiment("一次实验", "one-row", rel)
    after = store.read_events()

    assert len(store.rows("experiments")) == 1
    new = after[before:]
    upserts = [e for e in new if e.get("op") == "upsert" and e.get("table") == "experiments"]
    assert len(upserts) == 1, f"应当恰好有一条 experiments upsert，实际 {len(upserts)}"
    assert upserts[0]["row"]["claim_key"] == "one-row"
    assert upserts[0]["actor"] == "agent-E"
    # alloc_id 也必须留下痕迹（ID 发号与建行同事务，是可审计的）
    assert any(e.get("table") == "counters" for e in new)


def test_second_run_allocates_the_next_id(store):
    """两次实验拿到两个不同的 ID（ID 发号在持锁事务内，不许撞号）。"""
    rel = write_script(store, "probes/honest.py", HONEST_PROBE)
    e = make_e(store)
    a = e.run_experiment("第一次", "k1", rel)
    b = e.run_experiment("第二次", "k2", rel)
    assert {a["experiment_id"], b["experiment_id"]} == {"0000", "0001"}
    assert len(store.rows("experiments")) == 2


# ============================================================ [8] 工具层


def test_verify_tools_registered_with_honest_side_effects(store):
    """工具层的三个新工具必须注册，且 `side_effect` 如实声明（FC-07）。

    ## 为什么 `verify.run_experiment` 的角色**不含 H**（这条断言后来被收紧了）

    原断言写的是"三个工具的角色都是 {E,F,G,H}"。那编码的是一条**更弱**的规则：
    "角色的声明只要包含需要它的人就行"。但本框架有一条更硬的约束 ——
    **`H` 是只读角色**（`abflow.tools.READ_ONLY_ROLES`）：审校者若手里有
    "跑实验并落库"的能力，它就同时是"发现者"与"执行者"，
    于是**"发现问题"与"掩盖问题"在结构上无法区分**。

    实测过这个漏洞真的存在：`table.*` / `fs.*` 把 `write_local` 工具声明给了
    全部角色，按角色装配出来的 H 工具面里出现了 `table.update`。
    现在的防线有两道：① 工具声明本身正确（本断言守它）；
    ② `ToolRegistry.for_role` 对只读角色**结构性**剥掉所有写工具（`test_tools_base.py` 守它）。
    """
    e = make_e(store)
    names = set(e.tools.names())
    assert {"verify.run_experiment", "verify.evidence_for", "verify.list_experiments"} <= names
    # 保留已有的三个工具（有人在并行做验收测试，会用到）
    assert {"verify.code_hash", "verify.detect_verifier", "verify.check_formal"} <= names
    assert e.tools.get("verify.run_experiment").side_effect == "write_local"
    assert e.tools.get("verify.evidence_for").side_effect == "read"
    assert e.tools.get("verify.list_experiments").side_effect == "read"
    # 只读工具：需要它的角色都能拿到
    for name in ("verify.evidence_for", "verify.list_experiments"):
        assert set(e.tools.get(name).roles) == {"E", "F", "G", "H"}, "角色即权限面"
    # 写工具：**只读角色 H 被排除**（否则"审校者能改数据"）
    assert set(e.tools.get("verify.run_experiment").roles) == {"E", "F", "G"}, (
        "verify.run_experiment 是 write_local，角色声明里不能有只读角色 H。"
        "（`for_role` 也会拦下它，但声明本身必须对 —— 只靠拦截会让声明与事实长期不一致）"
    )


def test_run_experiment_tool_goes_through_the_same_implementation(store):
    """工具入口与 `AgentE.run_experiment` 必须写出**同一种**记录（不许两套口径）。"""
    rel = write_script(store, "probes/keyed.py", HONEST_PROBE)
    reg = make_e(store).tools
    got = reg.call("verify.run_experiment", claim="经工具跑的实验", claim_key="via-tool", script_path=rel)
    assert got.ok, got.error
    assert got.data["recorded"] is True
    assert got.data["evidence_kind"] == "cross_check"

    rows = store.rows("experiments")
    assert len(rows) == 1
    assert rows[0]["claim_key"] == "via-tool"
    assert rows[0]["code_hash"] == VT.code_hash(Path(store.root) / rel)
    assert rows[0]["created_by"] == "agent-E"

    ev = reg.call("verify.evidence_for", claim_key="via-tool")
    assert ev.ok and ev.data["checked"] is True and len(ev.data["experiments"]) == 1
    listed = reg.call("verify.list_experiments")
    assert listed.ok and listed.data["total"] == 1


def test_verify_store_tools_fail_closed_when_not_wired():
    """**FC-08 负控**：未接线（没有 store）时必须显式失败，**不得返回空数据**。

    "我们没接上存储"与"存储里没有实验结果"在调用方眼里必须长得不一样 ——
    否则"没查"会被读成"查了没有"，而后者是一个会被引用的结论。
    """
    from abflow.tools.base import ToolRegistry

    empty = ToolRegistry(name="no-store")
    VT.register(empty, store=None, root=None)
    for name in ("verify.run_experiment", "verify.evidence_for", "verify.list_experiments"):
        res = empty.call(
            name,
            **{
                "verify.run_experiment": {"claim": "c", "claim_key": "k", "script_path": "s.py"},
                "verify.evidence_for": {"claim_key": "k"},
                "verify.list_experiments": {},
            }[name],
        )
        assert res.ok is False, f"{name} 未接线时返回了成功"
        assert res.meta.get("kind") == "not_wired"
        assert res.data is None, "未接线不得返回空数据"


# ============================================================ [9] 自检


def test_module_selftest_passes_offline():
    """模块自检必须能在**不联网、不依赖外部文件**的情况下跑通（返回 0 个失败）。

    刻意**不复用 `store` 夹具**：自检自己建临时工作区，因此这里能顺带证明
    "它不依赖测试环境的任何既有状态"。`agent_e.selftest()` 的流程是
    正常脚本 → 自报 proof → 崩溃 → 无结论 → 路径越界 → 超时 → 三态 → 事务性 → check_formal。
    """
    from abflow import agent_e

    assert agent_e.selftest() == 0


# ============================================================ 采自本地先例的两条硬约束
#
# 这两条来自对本地先例的**只读观摩**（`draft/14-…-Danus.md`、`draft/15-…-dsh数学模式与DeepMath.md`）：
# 它们各有一个我们**结构上真的缺**的东西，且成本很小、不改变我们的架构。


def test_proof_requires_verifier_subject_key_matching_the_claim(store):
    """**验证工具必须与上下文绑定**（采自 DeepMath）。

    DeepMath 的做法是"验证工具绑定上下文，越界调用直接 raise"。
    我们此前 `verifier_output` 是一个**自由字符串** —— 于是把"命题 A 的检查器输出"
    粘到"命题 B 的记录行"上，结构上完全允许，而且**没有任何地方会报错**。
    这不是理论风险：任何"批量跑一堆检查、再批量写记录"的实现都会踩到它。
    """
    store.init()
    base = dict(experiment_id="0000", claim="P", claim_key="P", method="formal",
                evidence_kind="proof", verifier_output="Lean 4: no goals",
                result="supports", negation_kind="not_proved", created_at=TS)
    # 缺 verifier_subject_key ⇒ 拒
    with pytest.raises(ValueError, match="verifier_subject_key"):
        S.Experiment(**base).validate()
    # 管的是**别的命题** ⇒ 拒
    with pytest.raises(ValueError, match="不一致"):
        S.Experiment(**{**base, "verifier_subject_key": "Q"}).validate()
    # 管的就是本命题 ⇒ 过
    S.Experiment(**{**base, "verifier_subject_key": "P"}).validate()


def test_exhaustive_search_requires_a_certificate_and_a_bound(store):
    """**搜索类结论必须携带证书**（采自 dsh 数学模式）。

    穷举/可满足性这类结论的说服力**全部**来自"证书"：
    "在 B 内没有反例"若不说清 B 是什么、怎么搜的，就只是一句**无法复核的话** ——
    它看起来是结论，实际上是一个没有定义域的断言。
    """
    store.init()
    base = dict(experiment_id="0000", claim="范围内无反例", claim_key="no-ce",
                method="exhaustive_search", evidence_kind="cross_check",
                result="supports", negation_kind="not_proved", created_at=TS)
    with pytest.raises(ValueError, match="certificate"):
        S.Experiment(**base).validate()
    # 有证书但没边界 ⇒ 仍拒（证书脱离边界没有意义）
    with pytest.raises(ValueError, match="search_bound"):
        S.Experiment(**{**base, "certificate": {"kind": "enumeration_bound"}}).validate()
    # 证书 + 边界 ⇒ 过
    S.Experiment(**{
        **base,
        "certificate": {"kind": "enumeration_bound", "detail": {"box": 3}},
        "search_bound": {"m": [3, 4, 5], "radius": 3},
    }).validate()


def test_numeric_method_still_does_not_need_a_certificate(store):
    """**防误伤**：`numeric`（连续采样）不是搜索类，不该被要求给证书。

    把"必须给证书"扩大到 `numeric` 会逼着实现者编一个没有意义的 `search_bound`，
    那会让这条约束退化成填表练习。
    """
    store.init()
    S.Experiment(experiment_id="0000", claim="c", claim_key="k", method="numeric",
                 evidence_kind="cross_check", result="supports", negation_kind="not_proved",
                 created_at=TS).validate()
