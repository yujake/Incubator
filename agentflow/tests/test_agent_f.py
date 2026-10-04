"""智能体 F（`agent_f.py` + `tools/attack_tools.py`）的性质测试。

F 的核心是"把难题变成多轮、可终止、可交接的过程"。这里锁住六条最容易
悄悄做错的性质：

- 终止性：轮数用尽必须停，且停在 `stalled` + 非空 `best_partial`
  （不是失败，也不是成功）；
- 三态纪律：C/D/F 的子目标本框架尚未接线 ⇒ 如实记 `no_change`，
  绝不允许把"没做"写成"做了但没结果"；
- FC-22：只有数值证据的子目标不得被标 `closed`；全部只有数值支持时
  计划只能是 `supported_not_proved`；
- 预算完整性：四类键缺一即拒绝建项，且一行都不写；
- 查重：同一 `problem_key` 不重复立项；
- 判据只有一份：子目标排序/预算检查复用 `tools/attack_tools.py`。

全部离线、确定性：不联网，实验脚本现写现跑。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow.agent_f import AgentF, PlanError
from agentflow.store import Store
from agentflow.tools import attack_tools as AT

TS = "2026-01-01T00:00:00+00:00"

#: 一个"数值支持"的探针脚本（永远是 cross_check，不是证明）。
SUPPORT_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {"n": 32},
    "counterexample": None,
    "negation_kind": "not_proved",
}))
"""


# ============================================================ 辅助


def write_script(store: Store, rel: str, body: str) -> str:
    p = Path(store.root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


def make_f(store: Store, **cfg) -> AgentF:
    """F 的构造。`workspace_root` 让 E 的实验脚本落在同一个临时工作区里。"""
    return AgentF(store, config={"workspace_root": store.root, **cfg})


def budget(**over) -> dict:
    b = dict(AT.DEFAULT_BUDGET)
    b.update(over)
    return b


def raw_plan(**kw) -> S.AttackPlan:
    """直接构造一行 `AttackPlan`（不经 F），用于 schema 负控。"""
    fields = {
        "plan_id": "0000",
        "problem": "难题",
        "problem_key": "PK",
        "budget": budget(),
        "rounds": 0,
        "created_at": TS,
    }
    fields.update(kw)
    return S.AttackPlan(**fields)


def three_goal_plan(store: Store, **cfg) -> tuple[AgentF, str]:
    """建一个含 E / C 两类子目标的计划，返回 (F, plan_id)。"""
    f = make_f(store, **cfg)
    rel = write_script(store, "probe.py", SUPPORT_PROBE)
    out = f.create_plan(
        "证明 Spec K(m)=[-m,m]",
        "PK-1",
        subgoals=[
            {
                "sid": "s1",
                "text": "数值验证 m<=32",
                "owner": "E",
                "script_path": rel,
                "claim": "Spec K(m)=[-m,m]",
                "claim_key": "PK-1#s1",
            },
            {"sid": "s2", "text": "需要 C 做结构分析", "owner": "C"},
        ],
    )
    assert out["created"] is True
    return f, out["plan_id"]


# ============================================================ [1] 立项


def test_create_plan_with_complete_budget(store):
    """正向：完整预算 ⇒ 创建成功，且四类键原样落库。"""
    f = make_f(store)
    out = f.create_plan(
        "难题甲",
        "PK-A",
        for_question_id="0001",
        subgoals=[{"sid": "s1", "text": "先做数值实验", "owner": "E"}],
    )
    assert out["created"] is True
    assert out["plan_id"] == "0000"
    assert out["status"] == "open"

    row = store.rows("attack_plans")[0]
    assert row["budget"] == AT.DEFAULT_BUDGET, "预算必须原样落库（不许悄悄补默认值）"
    assert row["problem_key"] == "PK-A"
    assert row["for_question_id"] == "0001"
    assert row["rounds"] == 0 and row["history"] == []
    # 子目标的每个字段都要在（下游的分派要读它们）
    sg = row["subgoals"][0]
    assert {"sid", "text", "owner", "status", "evidence_ids", "experiment_ids",
            "proof_experiment_ids", "blocked_reason", "attempts", "negation_kind"} <= set(sg)
    assert sg["status"] == "todo" and sg["attempts"] == 0


def test_create_plan_refuses_incomplete_budget_without_writing(store):
    """负控：预算缺 `max_depth` ⇒ 不创建，且 `attack_plans.json` 逐字节不变。"""
    f = make_f(store)
    before = (store.data / "attack_plans.json").read_bytes()
    bad = budget()
    bad.pop("max_depth")
    out = f.create_plan("难题乙", "PK-B", budget=bad)

    assert out["created"] is False
    assert out["missing"] == ["max_depth"]
    assert "max_depth" in out["reason"]
    assert (store.data / "attack_plans.json").read_bytes() == before, "拒绝创建时不得写库（一个字节都不行）"


def test_the_incomplete_budget_refusal_is_visible_as_a_refusal(store):
    """判据（`draft/37` §127 的真机读数）：这一支是**拒绝**，调用方必须看得出来。

    T2 第 4 趟真机：主控连续 6 次 `F.create_plan` 都只传 `{"max_rounds": 6}`，
    每一次都被拒（预算四类键缺一不可），而台账里记的全是
    「执行完成（handler 未声明 outcome，按有产出处理）」= `outcome=ok`
    —— 于是主控以为自己立了项，而 `attack_plans` 一行都没有，R5 卡死。

    判据两半：① 这一支带 `ok=False` + 受控 `refusal_reason`（`conductor` 据此落 `refused`）；
    ② 三个分支的 `ok` 各不相同地说清自己是哪一种（拒绝 / 成功 / 已经立过项）。
    """
    from agentflow.agent_f import AgentF
    from agentflow.conductor import Conductor
    from agentflow.tools import build_registry

    c = Conductor(store, registry={"F": ("object", AgentF(store))})
    reg = build_registry(store=store, conductor=c).registry

    bad = reg.call("conductor.summon", role="M", target_role="F", action="create_plan",
                   params={"problem": "难题丁", "problem_key": "PK-D",
                           "budget": {"max_rounds": 6}}, input_key="plan-bad")
    assert bad.data["outcome"] == "refused", bad.data
    assert bad.data["refusal_reason"] == "invalid_params", bad.data
    assert len(store.rows("attack_plans")) == 0, "被拒的那次不许留下行"

    good = reg.call("conductor.summon", role="M", target_role="F", action="create_plan",
                    params={"problem": "难题丁", "problem_key": "PK-D",
                            "budget": {"max_rounds": 6, "max_parallel_subgoals": 2,
                                       "max_persist_attempts": 2, "max_depth": 2}},
                    input_key="plan-good")
    assert good.data["outcome"] == "ok", good.data
    assert len(store.rows("attack_plans")) == 1

    again = reg.call("conductor.summon", role="M", target_role="F", action="create_plan",
                     params={"problem": "难题丁", "problem_key": "PK-D",
                             "budget": {"max_rounds": 6, "max_parallel_subgoals": 2,
                                        "max_persist_attempts": 2, "max_depth": 2}},
                     input_key="plan-again")
    assert again.data["outcome"] == "ok", again.data
    assert len(store.rows("attack_plans")) == 1, "幂等：已有的计划不新建"


def test_create_plan_second_time_returns_existing_plan_id(store):
    """同一 `problem_key` 第二次 ⇒ 不新建，返回已有 `plan_id`（避免同一难题被攻两遍）。"""
    f = make_f(store)
    first = f.create_plan("难题丙", "PK-C")
    assert first["created"] is True

    again = f.create_plan("换了个说法的同一个难题", "PK-C")
    assert again["created"] is False
    assert again["duplicate"] is True
    assert again["plan_id"] == first["plan_id"]
    assert len(store.rows("attack_plans")) == 1

    # 反误伤：终结的计划不挡住新立项（否则一个 stalled 的难题就再也开不了新计划）
    with store.tx("attack_plans", actor="test") as tx:
        row = tx.find("attack_plans", plan_id=first["plan_id"])
        row["status"] = "stalled"
        row["best_partial"] = "已进行 6 轮：什么都没有"
        tx.upsert("attack_plans", row)
    fresh = f.create_plan("同一个难题，重新立项", "PK-C")
    assert fresh["created"] is True and fresh["plan_id"] != first["plan_id"]


def test_create_plan_requires_owner_and_text(store):
    """子目标缺 `owner` / `text` ⇒ 当场抛（owner 是权限面的一部分，不能默认）。"""
    f = make_f(store)
    with pytest.raises(PlanError):
        f.create_plan("难题", "PK-D", subgoals=[{"sid": "s1", "text": "t"}])
    with pytest.raises(PlanError):
        f.create_plan("难题", "PK-D", subgoals=[{"sid": "s1", "owner": "E"}])
    with pytest.raises(PlanError):
        f.create_plan("难题", "PK-D", subgoals=[{"owner": "E", "text": "t"}])
    assert store.rows("attack_plans") == []


# ============================================================ [2] step 正向


def test_step_increments_rounds_and_appends_history(store):
    """`step` 正向：轮次自增、`history` 追加一条、`rounds <= max_rounds`。"""
    f, pid = three_goal_plan(store, max_rounds=4)
    out = f.step(pid)
    assert out["plan_id"] == pid
    assert out["round"] == 1
    assert out["sid"] == "s1"
    assert out["action"] == "run_experiment"
    assert out["budget_left"]["max_rounds_left"] == 3

    row = store.rows("attack_plans")[0]
    assert row["rounds"] == 1
    assert len(row["history"]) == 1
    rec = row["history"][0]
    assert {"round", "sid", "action", "outcome", "detail", "evidence", "at"} <= set(rec)
    assert rec["round"] == 1 and rec["sid"] == "s1"
    assert rec["at"], "history 每条都要带时间戳（否则'这一轮是什么时候跑的'答不上来）"
    assert row["rounds"] <= row["budget"]["max_rounds"]


def test_normalization_beats_raw_extra_fields(store):
    """回归：调用方给的原始键不得覆盖规范化后的字段（`status=None` 尤其危险）。

    曾经 `_normalize_subgoal` 把 raw 里除 sid/text/owner 之外的所有键原样透传，
    并在最后 `update` 覆盖规范化参数 —— 于是 `status` 缺失时会带着 `None` 落库，
    `attempts` 的默认值也被抹掉。这类覆盖不报任何错，只是写出一条形状不对的子目标。
    """
    f = make_f(store)
    out = f.create_plan(
        "难题",
        "PK-NORM",
        subgoals=[
            {"sid": "s1", "text": "t", "owner": "C"},  # 完全没有 status / attempts
            {"sid": "s2", "text": "t", "owner": "C", "status": None, "attempts": None},
        ],
    )
    assert out["created"] is True
    for sg in store.rows("attack_plans")[0]["subgoals"]:
        assert sg["status"] == "todo", f"{sg['sid']} 的 status 被原始键抹成了 {sg['status']!r}"
        assert sg["attempts"] == 0
        assert sg["evidence_ids"] == [] and sg["experiment_ids"] == []
        assert sg["negation_kind"] is None
    S.row_from_dict("attack_plans", store.rows("attack_plans")[0]).validate()


def test_step_is_deterministic_about_which_subgoal_it_picks(store):
    """选目标复用 `attack_tools.pick_next_subgoal`：不是随机，也不是另写一套排序。

    这里给定一组"谁都没动过"的子目标，把 F 的选择与工具层独立算出的选择对照。
    """
    f = make_f(store)
    subgoals = [
        {"sid": "s3", "text": "第三条", "owner": "C"},
        {"sid": "s1", "text": "第一条", "owner": "C"},
        {"sid": "s2", "text": "第二条", "owner": "C"},
    ]
    pid = f.create_plan("难题", "PK-PICK", subgoals=subgoals)["plan_id"]
    # 参照答案取落库后的那份子目标（`create_plan` 会给它们补齐 `status="todo"`
    # 等字段 —— 工具层的排序正是按这些字段工作的），并用深拷贝避免被 F 自己的
    # 动作就地改掉（`step` 会更新 `status` / `attempts` / `in_flight`，
    # 复用同一个对象会让断言变成自证）。
    fresh = copy.deepcopy(store.rows("attack_plans")[0]["subgoals"])
    expected = AT.pick_next_subgoal(fresh)["subgoal"]["sid"]
    first = f.step(pid)
    assert first["sid"] == expected
    assert first["sid"] == "s1", "三个 todo 子目标里按 sid 升序取第一个（确定性，不看运气）"


# ============================================================ [3] 按 owner 分派


def test_owner_e_subgoal_really_produces_an_experiment(store):
    """`owner="E"` 且带 `script_path` ⇒ 真的跑出 `experiment_id`（并且只跑一次）。"""
    f, pid = three_goal_plan(store)
    f.step(pid)

    assert len(store.rows("experiments")) == 1, "E 的子目标必须真的产生实验记录"
    eid = store.rows("experiments")[0]["experiment_id"]
    sg = next(s for s in store.rows("attack_plans")[0]["subgoals"] if s["sid"] == "s1")
    assert sg["experiment_ids"] == [eid]
    assert sg["attempts"] == 1
    # FC-22：数值实验不进 proof_experiment_ids，子目标也不是 closed
    assert sg["proof_experiment_ids"] == []
    assert sg["status"] == "supported_not_proved"
    assert sg["negation_kind"] == "not_proved"


def test_owner_e_formal_subgoal_reaches_proof_and_closes_only_with_proof(store, monkeypatch):
    """`P-8` 的 F 侧接线：形式化子目标要把 `name` / `imports` 传给 E。

    不传的话 E 只能用文件名词干 + 检查器默认库：裸 `lean` 解析不到 Mathlib
    （`import_unavailable`）⇒ 那次检查根本没发生 ⇒ F 永远拿不到 proof 级证据、
    子目标永远关不掉。这里用桩检查器证明"参数真的到了检查器"，
    并断言只有 `verified` 才把子目标标 `closed`。
    """
    from agentflow import formalgw as FG
    from agentflow.tools import verify_tools as VT

    monkeypatch.setattr(VT, "detect_verifier", lambda: {
        "checked": True,
        "available": [{"name": "lean", "path": "lean", "version": "(桩)"}],
        "available_names": ["lean"], "probe_errors": [], "reason": "（桩）探测到 lean",
    })
    seen: dict = {}

    def _fake(source, *, name, imports, timeout_sec, run_fn=None, workdir=None, source_path=None):
        seen.update({"name": name, "imports": tuple(imports), "source_path": source_path})
        raw = {"status": "verified", "reason": "（桩）通过", "stdout": "（桩）no axioms",
               "stderr": "", "axioms": [], "sorry_count": 0, "decl_matches": True,
               "declared_in_source": True, "ran": True, "backend": {"status": "ok"}}
        return FG._conclude(raw, "verified", raw["reason"])

    monkeypatch.setattr(FG, "check_lean", _fake)
    rel = write_script(store, "proofs/f_probe.lean", "theorem f_probe : 1 + 1 = 2 := rfl\n")
    f = make_f(store)
    pid = f.create_plan("难题", "PK-FORMAL", subgoals=[
        {"sid": "s1", "text": "把这条命题形式化", "owner": "E", "method": "formal",
         "script_path": rel, "name": "f_probe", "imports": []},
    ])["plan_id"]
    out = f.step(pid)

    assert seen["name"] == "f_probe", "声明名没有传到检查器"
    assert seen["imports"] == (), "imports 没有传到检查器（空列表 ⇒ 纯内核检查）"
    assert out["outcome"] == "progress"
    row = store.rows("experiments")[0]
    assert row["evidence_kind"] == "proof"
    assert row["verifier_subject_key"] == row["claim_key"], "检查器输出必须绑定到这条命题"
    sg = store.rows("attack_plans")[0]["subgoals"][0]
    assert sg["proof_experiment_ids"] == [row["experiment_id"]]
    assert sg["status"] == "closed", "只有 proof 级证据才允许关闭子目标（FC-22）"


def test_owner_e_without_script_path_is_recorded_as_not_advanced(store):
    """E 的子目标没给 `script_path` ⇒ `no_change` + "未推进"，不是"跑了但没结果"。"""
    f = make_f(store)
    pid = f.create_plan("难题", "PK-E", subgoals=[{"sid": "s1", "text": "做个实验", "owner": "E"}])["plan_id"]
    out = f.step(pid)
    assert out["action"] == "run_experiment" or out["action"] == "no_change"
    assert out["outcome"] == "no_change"
    assert "未推进" in out["reason"] or "未推进" in out["reason"]
    assert "script_path" in out["reason"]
    assert store.rows("experiments") == [], "没有脚本就没有实验记录（不许造一条空的）"
    sg = store.rows("attack_plans")[0]["subgoals"][0]
    assert sg["experiment_ids"] == [] and sg["attempts"] == 0
    assert sg["status"] == "todo", "缺参数是'还做不了'，不是'做过了'"


def test_owner_c_is_recorded_as_no_change_with_honest_detail(store):
    """三态负控（重要）：`owner="C"` ⇒ `outcome == "no_change"` 且 detail 明说"未推进/未接线"。

    本框架没有可自动调用的 C/D/F 推理入口。这里锁住的是"不许把没做写成做了"：
    出现任何伪造的 evidence、或 detail 里出现"已推进"这类说法，都是静默失败。
    """
    f = make_f(store)
    pid = f.create_plan("难题", "PK-F", subgoals=[{"sid": "s1", "text": "让 C 分析结构", "owner": "C"}])["plan_id"]
    out = f.step(pid)

    assert out["action"] == "no_change"
    assert out["outcome"] == "no_change"
    assert "未推进" in out["reason"]
    assert "未接线" in out["reason"]
    assert "已推进" not in out["reason"]
    assert out["sid"] == "s1"

    sg = store.rows("attack_plans")[0]["subgoals"][0]
    assert sg["evidence_ids"] == [], "不许伪造证据"
    assert sg["experiment_ids"] == [] and sg["proof_experiment_ids"] == []
    assert sg["status"] == "blocked", "未接线是一个**卡点**，必须用 blocked + 理由表达出来"
    assert sg["blocked_reason"], "不许静默卡住"
    assert sg["attempts"] == 0, "什么都没做就不该记一次尝试（那会让'试过几次'虚高）"

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert rec["outcome"] == "no_change" and rec["evidence"] == []


def test_owner_d_and_f_are_also_recorded_as_not_advanced(store):
    """D / F 与 C 同样：未接线就如实记 `no_change`（三种 owner 一个口径）。"""
    f = make_f(store)
    pid = f.create_plan(
        "难题",
        "PK-G",
        subgoals=[{"sid": "sd", "text": "让 D 研究", "owner": "D"}, {"sid": "sf", "text": "让 F 自己推理", "owner": "F"}],
    )["plan_id"]
    f.step(pid)
    f.step(pid)
    sgs = {s["sid"]: s for s in store.rows("attack_plans")[0]["subgoals"]}
    assert set(sgs) == {"sd", "sf"}
    for sg in sgs.values():
        assert sg["status"] == "blocked" and sg["evidence_ids"] == []
    assert len(store.rows("experiments")) == 0


def test_owner_a_submits_a_search_request_through_the_gate(store):
    """`owner="A"` ⇒ 过 `admit_search_request` 闸门后在同一个事务里写一条检索请求。"""
    f = make_f(store)
    pid = f.create_plan(
        "难题",
        "PK-H",
        subgoals=[{"sid": "s1", "text": "检索 K(m) 的谱刻画", "owner": "A", "topic": "spectrum of K(m)"}],
    )["plan_id"]
    out = f.step(pid)
    assert out["action"] == "submit_search_request"
    assert out["outcome"] == "progress"

    reqs = store.rows("search_requests")
    assert len(reqs) == 1
    req = reqs[0]
    assert req["submitted_by"] == "agent-F"
    # `"agent-F"` 不在 `schema.SUBMITTER_DEFAULT_PRIORITY` 里（那张表只有
    # agent-D / human / agent-C / agent-B / unknown），于是走契约明确规定的
    # "未登记的提交方一律 low"这条保守规则。这是契约行为，不是缺陷：
    # F 的请求排在后面比让它插队更安全。要提优先级得显式给（见下一个用例）。
    assert req["priority"] == "low", "未登记的提交方必须落到 low（宁可排后面，也不许插队）"
    assert req["content_description"], "precise 模式必须给 content_description（schema 硬约束）"
    assert req["done"] is False
    sg = store.rows("attack_plans")[0]["subgoals"][0]
    assert sg["evidence_ids"] == [req["request_id"]], "证据列里要留下这次请求的代号"
    assert req["request_id"] == "r-0001", "请求号形如 r-NNNN（前缀只出现一次）"
    assert "等 A 完成" in sg["blocked_reason"], "请求交出去之后要写清在等谁（否则无从接手）"


def test_owner_a_respects_an_explicit_priority_from_config(store):
    """配置里显式给优先级时按它提交（否则调用方无法让 F 的请求排前面）。

    这条同时锁住"配置不许被静默忽略"：`search_priority` 给了就必须生效。
    """
    f = make_f(store, search_priority="high")
    pid = f.create_plan("难题", "PK-H2", subgoals=[{"sid": "s1", "text": "检索", "owner": "A"}])["plan_id"]
    out = f.step(pid)
    assert out["action"] == "submit_search_request"
    assert store.rows("search_requests")[0]["priority"] == "high"


def test_owner_b_requires_targets_and_goes_through_the_gate(store):
    """`owner="B"` ⇒ 有目标才提交；没有 `relation_ids` 一律不提交（I4 的幂等陷阱）。"""
    f = make_f(store)
    pid = f.create_plan("难题", "PK-I", subgoals=[{"sid": "s1", "text": "回原文补语境", "owner": "B"}])["plan_id"]
    out = f.step(pid)
    assert out["action"] == "submit_reprocess_request"
    assert out["outcome"] == "no_change"
    assert "未推进" in out["reason"]
    assert store.rows("reprocess_requests") == [], "无目标的重抽取会退化成全量重抽，必须拒绝"


# ============================================================ [4] 终止性


def test_rounds_run_out_then_stalls_with_best_partial(store):
    """终止性（最重要）：反复 `step` 到轮数用尽 ⇒ 必须停，`stalled`，`best_partial` 非空。

    并断言没有无限循环：轮数恰好等于 `max_rounds`（多一轮都不行）。
    """
    f, pid = three_goal_plan(store, max_rounds=3)
    seen: list[int] = []
    for _ in range(20):  # 上限 20 次：真的死循环的话这里会先炸出来
        out = f.step(pid)
        seen.append(out["round"])
        if out["status"] == "stalled":
            break

    row = store.rows("attack_plans")[0]
    assert row["status"] == "stalled"
    assert row["rounds"] == 3, f"轮数必须恰好等于 max_rounds=3，实际 {row['rounds']}"
    assert row["best_partial"].strip(), "stalled 必须交出当前最好结果（含'什么都没有'这种如实说明）"
    assert "不构成证明" in row["best_partial"], "best_partial 里不许暗示已经证明"
    assert len(seen) == 4, "第 4 次 step 只是把计划标成 stalled，之后不该再有轮次"

    # 终态不可重入：再 step 也不改 rounds、不改 history
    hist = len(row["history"])
    again = f.step(pid)
    assert again["status"] == "stalled"
    assert store.rows("attack_plans")[0]["rounds"] == 3
    assert len(store.rows("attack_plans")[0]["history"]) == hist


def test_stalled_without_any_progress_still_writes_an_honest_best_partial(store):
    """`max_rounds=0`（预算一开始就用尽）⇒ 仍必须写出如实的 `best_partial`。

    schema 要求非空，但"非空"不等于"可以编"：真的一无所获时，正确做法是照实写
    "尚未取得任何部分结果"，而不是写一句听起来像成果的话。
    """
    f = make_f(store)
    pid = f.create_plan("难题", "PK-J", budget=budget(max_rounds=0), subgoals=[{"sid": "s1", "text": "t", "owner": "E"}])[
        "plan_id"
    ]
    out = f.step(pid)
    assert out["status"] == "stalled"
    row = store.rows("attack_plans")[0]
    assert row["best_partial"].strip()
    # 一行都没跑过，所以交接记录必须是"什么都没拿到"，而不是一句像成果的话
    assert "已进行 0 轮" in row["best_partial"]
    assert all(s["status"] == "todo" for s in row["subgoals"])
    assert "轮数已用尽（0/0）" in row["best_partial"], "停止理由要写清是哪个维度用尽了"
    assert store.rows("experiments") == [], "已经没预算了就不该再跑实验"


def test_plan_closes_when_the_only_subgoal_is_closed_by_proof(store):
    """全部子目标 `closed` ⇒ `status="resolved"`（只有 proof 级证据才允许走到这里）。"""
    f = make_f(store)
    pid = f.create_plan("难题", "PK-K", subgoals=[{"sid": "s1", "text": "已有形式化证明", "owner": "E"}])["plan_id"]
    # 直接给出 proof 级证据（模拟 E 走了 formal 路径），验证 F 的状态机
    with store.tx("attack_plans", actor="test") as tx:
        row = tx.find("attack_plans", plan_id=pid)
        row["subgoals"][0]["status"] = "closed"
        row["subgoals"][0]["proof_experiment_ids"] = ["0000"]
        row["subgoals"][0]["experiment_ids"] = ["0000"]
        tx.upsert("attack_plans", row)
    out = f.step(pid)
    assert out["status"] == "resolved"
    assert out["sid"] is None and out["action"] == "stop"


def test_plan_with_only_numeric_support_is_supported_not_proved(store):
    """FC-22：全部子目标都有数值支持但没有任何 proof ⇒ `supported_not_proved`。"""
    f = make_f(store)
    pid = f.create_plan("难题", "PK-L", subgoals=[{"sid": "s1", "text": "已有数值支持", "owner": "E"}])["plan_id"]
    with store.tx("attack_plans", actor="test") as tx:
        row = tx.find("attack_plans", plan_id=pid)
        row["subgoals"][0]["status"] = "supported_not_proved"
        row["subgoals"][0]["experiment_ids"] = ["0000"]
        tx.upsert("attack_plans", row)
    out = f.step(pid)
    assert out["status"] == "supported_not_proved", "有数值支持就报 resolved 是把 cross_check 当成了证明"


# ============================================================ [5] schema 负控（不经 F）


def test_schema_rejects_closed_subgoal_with_only_numeric_evidence():
    """FC-22 负控：子目标只有数值证据却标 `closed` ⇒ `validate()` 抛。"""
    with pytest.raises(ValueError) as ei:
        raw_plan(
            subgoals=[
                {
                    "sid": "s1",
                    "text": "数值验证",
                    "owner": "E",
                    "status": "closed",
                    "experiment_ids": ["0000"],
                    "proof_experiment_ids": [],
                }
            ]
        ).validate()
    assert "proof" in str(ei.value)


def test_schema_rejects_illegal_owner():
    """`SUBGOAL_OWNERS` 里没有的 owner ⇒ 抛（owner 是权限面的一部分）。"""
    with pytest.raises(ValueError) as ei:
        raw_plan(subgoals=[{"sid": "s1", "text": "t", "status": "todo", "owner": "Z"}]).validate()
    assert "owner" in str(ei.value)
    # 反误伤：受控词表里的每一个 owner 都该被接受
    for owner in S.SUBGOAL_OWNERS:
        raw_plan(subgoals=[{"sid": "s1", "text": "t", "status": "todo", "owner": owner}]).validate()


def test_schema_rejects_stalled_without_best_partial():
    """`status="stalled"` 但 `best_partial` 为空 ⇒ 抛（不许把中间成果丢掉）。"""
    with pytest.raises(ValueError) as ei:
        raw_plan(
            status="stalled",
            best_partial="",
            subgoals=[{"sid": "s1", "text": "t", "status": "todo", "owner": "E"}],
        ).validate()
    assert "best_partial" in str(ei.value)


def test_schema_rejects_non_monotonic_history():
    """`history` 轮次非单调 ⇒ 抛（轮次必须单调不减，否则"第几轮"无法解读）。"""
    with pytest.raises(ValueError) as ei:
        raw_plan(
            subgoals=[{"sid": "s1", "text": "t", "status": "todo", "owner": "E"}],
            history=[
                {"round": 2, "sid": "s1", "action": "run_experiment", "outcome": "progress",
                 "detail": "", "evidence": [], "at": TS},
                {"round": 1, "sid": "s1", "action": "no_change", "outcome": "no_change",
                 "detail": "", "evidence": [], "at": TS},
            ],
        ).validate()
    assert "单调" in str(ei.value)


def test_schema_rejects_rounds_over_budget():
    """`rounds > budget.max_rounds` ⇒ 抛（轮数上限是硬约束，超了就不该写）。"""
    with pytest.raises(ValueError) as ei:
        raw_plan(rounds=7, budget=budget(max_rounds=6)).validate()
    assert "max_rounds" in str(ei.value)


# ============================================================ [6] 预算与排序（纯函数）


def test_budget_has_four_dimensions_and_can_round_boundaries(store):
    """`budget` 四类键完整的正向检查 + `can_round` 在各维度的边界。"""
    b = budget()
    chk = AT.check_budget(b)
    assert chk["checked"] is True and chk["complete"] is True and chk["missing"] == []
    assert set(b) == {"max_rounds", "max_parallel_subgoals", "max_persist_attempts", "max_depth"}

    # 轮数边界：rounds=5 < 6 允许；rounds=6 == 6 不许
    assert AT.can_round(b, rounds_done=5)["allowed"] is True
    over = AT.can_round(b, rounds_done=6)
    assert over["allowed"] is False and over["blocked_by"] == "rounds"
    # 深度边界：depth=2 == max_depth=2 ⇒ 不许再往下（那是"派生"的维度）
    deep = AT.can_round(b, rounds_done=0, depth=2)
    assert deep["allowed"] is False and deep["blocked_by"] == "depth"
    assert AT.can_round(b, rounds_done=0, depth=1)["allowed"] is True

    # 三态：没给预算 ⇒ checked=False（没检查），不是"预算用尽"
    missing = AT.check_budget(None)
    assert missing["checked"] is False and missing["allowed"] is None
    assert AT.can_round(None, rounds_done=0)["allowed"] is None
    incomplete = AT.check_budget({"max_rounds": 3})
    assert incomplete["checked"] is True and incomplete["complete"] is False
    assert incomplete["allowed"] is False


def test_can_derive_stops_at_max_depth():
    """嵌套深度：`depth >= max_depth` ⇒ 不能再派生（用 `can_derive` / `can_round` 断言）。"""
    b = budget(max_depth=2)
    assert AT.can_derive(b, depth=0)["allowed"] is True
    assert AT.can_derive(b, depth=1)["allowed"] is True
    blocked = AT.can_derive(b, depth=2)
    assert blocked["allowed"] is False and blocked["blocked_by"] == "depth"
    # `can_round` 的深度维度给同一个答案（两个函数用的是同一份预算键）
    assert AT.can_round(b, rounds_done=0, depth=2)["allowed"] is False


def test_can_round_is_not_confused_with_can_derive(store):
    """两个维度不能混：深度到顶的计划自己仍然可以跑（否则它连第一轮都没有）。

    把"不能再分子问题"读成"这个问题不能做"，会让一个深度恰好到顶的计划
    连第一轮都跑不了 —— 那是本模块刻意分开 `can_round` 与 `can_derive` 的原因。
    """
    f = make_f(store)
    pid = f.create_plan("深度到顶的难题", "PK-M", budget=budget(max_depth=1), depth=1,
                        subgoals=[{"sid": "s1", "text": "t", "owner": "C"}])["plan_id"]
    out = f.step(pid)
    assert out["status"] != "stalled", "深度到顶不该让计划直接停摆"
    assert store.rows("attack_plans")[0]["rounds"] == 1
    assert AT.can_derive(budget(max_depth=1), depth=1)["allowed"] is False


def test_pick_next_subgoal_is_deterministic():
    """`pick_next_subgoal` 确定性：`in_progress` 优先于 `todo`，`blocked` 最后，全不可选返回 False。"""
    def sg(sid, status, owner="E"):
        return {"sid": sid, "text": "t", "owner": owner, "status": status,
                "evidence_ids": [], "experiment_ids": [], "proof_experiment_ids": [],
                "blocked_reason": "卡住了" if status == "blocked" else "", "attempts": 0, "negation_kind": None}

    picked = AT.pick_next_subgoal([sg("s3", "blocked"), sg("s2", "todo"), sg("s1", "in_progress")])
    assert picked["picked"] is True and picked["subgoal"]["sid"] == "s1"
    picked = AT.pick_next_subgoal([sg("s3", "blocked"), sg("s2", "todo"), sg("s1", "closed")])
    assert picked["subgoal"]["sid"] == "s2"
    picked = AT.pick_next_subgoal([sg("s3", "blocked"), sg("s1", "closed"), sg("s2", "dropped")])
    assert picked["subgoal"]["sid"] == "s3", "blocked 排最后，但仍是**可选**的（它需要人来解卡点）"
    empty = AT.pick_next_subgoal([sg("s1", "closed"), sg("s2", "supported_not_proved")])
    assert empty["picked"] is False and empty["subgoal"] is None and empty["reason"]
    assert AT.pick_next_subgoal([])["picked"] is False


# ============================================================ [7] 只读视图与工具层


def test_status_reports_counts_budget_and_history_tail(store):
    """`status` 返回子目标状态计数、预算余量与 history 尾部。"""
    f, pid = three_goal_plan(store, max_rounds=5)
    f.step(pid)
    view = f.status(pid)
    assert view["checked"] is True
    assert view["plan_id"] == pid and view["status"] == "attacking"
    assert view["rounds"] == 1
    assert view["subgoal_counts"] == {"supported_not_proved": 1, "todo": 1}
    assert view["budget_left"]["max_rounds_left"] == 4
    assert len(view["history_tail"]) == 1
    assert view["best_partial"].strip()

    missing = f.status("9999")
    assert missing["checked"] is False, "计划不存在 ⇒ **没查**（不是'查了、没有内容'）"


def test_list_plans_filters_terminal(store):
    """`list_plans`：可按 problem_key 过滤，也可只列还活着的计划。"""
    f = make_f(store)
    f.create_plan("甲", "PK-N1")
    pid2 = f.create_plan("乙", "PK-N2")["plan_id"]
    with store.tx("attack_plans", actor="test") as tx:
        row = tx.find("attack_plans", plan_id=pid2)
        row["status"] = "stalled"
        row["best_partial"] = "尚未取得任何部分结果"
        tx.upsert("attack_plans", row)

    assert f.list_plans()["total"] == 2
    assert f.list_plans(problem_key="PK-N1")["total"] == 1
    alive = f.list_plans(include_terminal=False)
    assert [p["plan_id"] for p in alive["plans"]] != [pid2]
    assert all(p["status"] not in ("resolved", "abandoned", "stalled") for p in alive["plans"])


def test_attack_tools_registered_with_honest_side_effects(store):
    """工具层的四个新工具必须注册（保留原有两个），且 `side_effect` / `roles` 如实。"""
    f = make_f(store)
    names = set(f.tools.names())
    assert {"attack.create_plan", "attack.step", "attack.status", "attack.list_plans"} <= names
    assert {"attack.check_budget", "attack.pick_next_subgoal"} <= names
    assert f.tools.get("attack.create_plan").side_effect == "write_local"
    assert f.tools.get("attack.step").side_effect == "write_local"
    assert f.tools.get("attack.status").side_effect == "read"
    assert f.tools.get("attack.list_plans").side_effect == "read"
    for name in ("attack.create_plan", "attack.step"):
        assert set(f.tools.get(name).roles) == {"F"}, "写侧收窄到 F（唯一主人，预算才有意义）"
    for name in ("attack.status", "attack.list_plans"):
        assert set(f.tools.get(name).roles) == {"F", "D", "G", "H"}, "角色即权限面"


def test_attack_tools_go_through_the_same_implementation(store):
    """工具入口与 `AgentF` 方法必须写出同一种记录（不许两套口径）。"""
    f = make_f(store)
    rel = write_script(store, "probe.py", SUPPORT_PROBE)
    created = f.tools.call(
        "attack.create_plan",
        problem="经工具立项目",
        problem_key="PK-T",
        subgoals=[{"sid": "s1", "text": "数值验证", "owner": "E", "script_path": rel}],
    )
    assert created.ok and created.data["created"] is True
    pid = created.data["plan_id"]

    stepped = f.tools.call("attack.step", plan_id=pid)
    assert stepped.ok and stepped.data["action"] == "run_experiment"

    view = f.tools.call("attack.status", plan_id=pid)
    assert view.ok and view.data["rounds"] == 1
    plans = f.tools.call("attack.list_plans")
    assert plans.ok and plans.data["total"] == 1
    # 工具跑出来的实验与 AgentF 方法跑出来的没有区别（同一份实现）
    assert len(store.rows("experiments")) == 1


def test_attack_tools_are_role_filtered_and_only_f_add_uses_them(store):
    """角色即权限面（FC-06）：A/B/C 拿不到 `attack.*`，E/G/H/D/F 能拿到。

    这里锁住"谁能用什么"是可枚举的事实 —— 提示词可以被绕过，注册表不能。
    """
    from agentflow.tools import build_for_role

    def names_for(role: str) -> set[str]:
        return set(build_for_role(role, store=store, workspace_root=store.root).registry.names())

    assert {n for n in names_for("F") if n.startswith("attack.")} == {
        "attack.check_budget",
        "attack.create_plan",
        "attack.list_plans",
        "attack.pick_next_subgoal",
        "attack.step",
        "attack.status",
    }
    for role in ("A", "B", "C"):
        assert not {n for n in names_for(role) if n.startswith("attack.")}, f"{role} 不该拿到攻坚工具"
    # E 的实验工具反过来也不该给 A/B/C（它们关心的是文献与关系，不是数值证据）
    for role in ("A", "B", "C"):
        assert not {n for n in names_for(role) if n.startswith("verify.")}, f"{role} 不该拿到实验工具"
    assert "verify.run_experiment" in names_for("E")
    # D 能读计划（它会把多轮未收敛的问题升级给 F），但不能建/推
    assert "attack.status" in names_for("D")
    assert "attack.create_plan" not in names_for("D")


def test_attack_store_tools_fail_closed_when_not_wired():
    """FC-08 负控：未接线（没有 store）时显式失败，不得返回"计划不存在"这种空数据。"""
    from agentflow.tools.base import ToolRegistry

    empty = ToolRegistry(name="no-store")
    AT.register(empty, store=None, root=None)
    empty.bound_role = "F"  # `P-14`：这张表代表 F（`attack.*` 的写侧唯一主人）
    assert empty.call("attack.create_plan", problem="p", problem_key="k").meta["kind"] == "not_wired"
    assert empty.call("attack.step", plan_id="0000").meta["kind"] == "not_wired"
    assert empty.call("attack.status", plan_id="0000").meta["kind"] == "not_wired"
    assert empty.call("attack.list_plans").meta["kind"] == "not_wired"
    for name, params in (
        ("attack.create_plan", {"problem": "p", "problem_key": "k"}),
        ("attack.status", {"plan_id": "0000"}),
    ):
        res = empty.call(name, **params)
        assert res.ok is False and res.data is None


# ============================================================ [8] 自检


def test_module_selftest_passes_offline():
    """模块自检必须能在不联网、不依赖外部文件的情况下跑通（返回 0 个失败）。"""
    from agentflow import agent_f

    assert agent_f.selftest() == 0


# ============================================================ F 的"连续无进展提前终止"
#
# 采自 dsh 数学模式（`draft/15-…md` §7.2）：那种模式要求"连续 N 轮无进展就终止"。
# 我们此前只按 `max_rounds` 停，而 `history[i]["outcome"]=="no_change"`
# 这个信号已经被生产出来却无人消费 —— 正是本项目自己总结的
# P4「检测到了却没有消费」的又一处实例。


def test_f_stops_early_when_rounds_make_no_progress(store):
    """无进展时不许把预算烧完（采自 dsh 数学模式）。

    这条测的是行为而不是某一条内部判据：一个"卡在未接线子目标上"的计划
    从第一轮起就不可能再有进展，因此它必须在远小于 max_rounds 的轮数内停下，
    并且把当前最好的部分结果与停止理由留下。

    为什么不断言"必须走 `stall_detected` 那条分支"：`step` 有多条"停"的路径
    （连续无进展、没有可选子目标、轮数用尽），它们都对。断言走哪一条会把测试
    绑在实现细节上 —— 我要钉住的是"不再烧预算"这个结果。
    """
    f = make_f(store, stall_after_no_progress_rounds=2)
    pid = f.create_plan("卡住的难题", "stall:k", subgoals=[
        {"sid": "s1", "text": "需要 D 推理", "owner": "D", "status": "todo"},
    ])["plan_id"]
    trace = []
    for _ in range(10):
        got = f.step(pid)
        trace.append((got.get("round"), got.get("action"), got.get("outcome"), got.get("status")))
        if got["status"] == "stalled":
            break
    row = f.status(pid)
    assert row["status"] == "stalled", trace
    assert row["rounds"] < 6, f"必须**提前**停下，而不是烧完 6 轮预算：{trace}"
    assert row["best_partial"].strip(), "停下时必须交出当前最好的部分结果"
    assert any(o == "no_change" for _r, _a, o, _s in trace), trace


def test_f_burns_full_budget_when_early_stall_is_disabled(store):
    """另一条路径：把提前终止关掉（=0）⇒ 停止只能由别的原因发生。

    两个方向都要测 —— 只测提前终止，就不知道"关掉它之后计划还能不能正常收口"。
    """
    f = make_f(store, stall_after_no_progress_rounds=0)
    pid = f.create_plan("永远卡住的难题", "stall:k2", subgoals=[
        {"sid": "s1", "text": "需要 D 推理", "owner": "D", "status": "todo"},
    ])["plan_id"]
    for _ in range(10):
        if f.step(pid)["status"] == "stalled":
            break
    row = f.status(pid)
    assert row["status"] == "stalled"
    assert row["rounds"] <= 6, "任何路径下都不得超出 max_rounds"
    assert "提前停止" not in row["best_partial"], "关掉之后就不该出现'提前停止'这个理由"
    assert row["best_partial"].strip()


def test_f_does_not_stop_early_when_rounds_make_progress(store):
    """防误伤：有进展时不得提前终止（否则"无进展"判据会误伤正常攻坚）。"""
    f = make_f(store, stall_after_no_progress_rounds=2)
    rel = write_script(store, "probes/ok.py", SUPPORT_PROBE)
    pid = f.create_plan("有进展的难题", "progress:k", subgoals=[
        {"sid": "s1", "text": "跑实验", "owner": "E", "status": "todo", "script_path": rel},
        {"sid": "s2", "text": "再检索", "owner": "A", "status": "todo"},
    ])["plan_id"]
    assert f.step(pid)["outcome"] == "progress"
    assert f.step(pid)["outcome"] == "progress"
    assert f.status(pid)["status"] != "stalled", "有进展时不该停"
