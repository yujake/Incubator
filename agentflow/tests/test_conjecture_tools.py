# -*- coding: utf-8 -*-
"""猜想台账最小集：唯一写点（`conjectureledger.register`）的正控与逐条负控。

依据：`draft/29` §7.5 的状态机 + `draft/30` §T1 的数据面 + 业主 2026-11-13 裁定甲
（D 不该立项临时命题 ⇒ 台账的唯一写点在产出侧）。

改前它是 `Tools/conjecture_tools.py` 那件工具（`conjecture.register_conjecture`，
`roles=("D",)`）的测试：业主 2026-11-13 撤掉 D 的那个动作之后，被判的对象从"工具"
变成"库层函数"，判据一条没放宽 —— 每一格都还在，只是入口换了：
`_call(st, ...)` 就是原来 `reg.call("conjecture.register_conjecture", ...)` 的那一笔。

这一组要证明五件事（每条都有反方向）：

1. 新建：省略 `conjecture_id` ⇒ 分配编号、落库、`status`/`form` 兜默认值；
2. 更新：`None` 是"我没提这件事" ⇒ 库里已有值原样保留（一次只改 `notes`
   的调用不许把 `supported_not_proved` 静默退回 `proposed`）；
3. 单行内判据只有一份：状态机由 `schema.Conjecture.validate()` 判，库层不重写
   （`refuted` 既无反例实验也无 `refusal_ref` / `proposed` 无 `testable` ⇒ 逐条拒收）；
4. 跨对象的存在性在写入期就核：引用不存在的实验 / 文献 ⇒ 抛，而不是等
   `verify_all` 事后报（那时数据已经脏了）；
5. 反方向：没有「登记一条猜想」这个动作 / 工具，D 的写集里也没有 `conjectures`
   —— 撤销之后如果有人把动作或工具加回来，这一条当场红。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import capabilities as CAP
from agentflow import conjectureledger as CL
from agentflow import schema as S
from agentflow import specs
from agentflow.store import Store
from agentflow.tools import build_registry

TS = "2026-01-01T00:00:00+00:00"


def _store(tmp_path: Path) -> Store:
    st = Store(tmp_path)
    st.init()
    return st


def _call(st: Store, **kw):
    """唯一写点的调用壳（形状对齐改前那件工具的返回：`ok` / `data` / `error`）。"""
    try:
        data = CL.register(store=st, actor="agent-E",
                           statement=kw.pop("statement", ""),
                           origin=kw.pop("origin", ""), **kw)
        return {"ok": True, "data": data, "error": ""}
    except CL.ConjectureError as exc:
        return {"ok": False, "data": {}, "error": str(exc), "kind": exc.kind}
    except ValueError as exc:
        return {"ok": False, "data": {}, "error": str(exc), "kind": "validation_error"}


def _experiment(st: Store, eid: str = "0000", **patch) -> dict:
    """落一行实验（台账要核它真的在库里）。"""
    row = {"experiment_id": eid, "claim": "谱落在 [-m, m] 内。", "claim_key": "k",
           "script": "s.py", "params": {}, "method": "numeric", "result": "supports",
           "negation_kind": "no_local_evidence",
           "evidence_kind": "cross_check", "code_hash": "0" * 16, "exit_code": 0,
           "created_at": TS, "created_by": "agent-E", **patch}
    with st.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row)
    return row


def _literature(st: Store, lid: str = "0000") -> dict:
    row = {"lit_id": lid, "title": "某文献", "type": "J", "summary": "摘要",
           "path": f"{lid}.txt", "status": "unread",
           "created_at": TS, "created_by": "agent-A"}
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", row)
    return row


# ---------------------------------------------------------------- 正控

def test_create_allocates_an_id_and_applies_the_defaults(tmp_path: Path):
    """正控：新建一条 `proposed` 猜想（`testable` 必填，`form` 兜 `universal`）。"""
    st = _store(tmp_path)
    res = _call(st, statement="对一切 m，V_m = 8m(m+1)/3。",
                origin="experiment:0001",
                testable={"why": "枚举 m<=6 与闭式比对"})
    assert res["ok"], res["error"]
    assert res["data"]["conjecture_id"] == S.format_id(0)
    assert res["data"]["status"] == "proposed" and res["data"]["form"] == "universal"
    assert res["data"]["origin"] == "experiment:0001"
    assert st.rows("conjectures")[0]["conjecture_id"] == S.format_id(0)


def test_update_keeps_what_the_caller_did_not_mention(tmp_path: Path):
    """正控（更新语义）：`None` = 没提 ⇒ 保留；这条挡住"改 notes 把状态清回 proposed"。"""
    st = _store(tmp_path)
    _experiment(st, "0008")
    cid = _call(st, statement="谱落在 [-m, m] 内。", origin="experiment:0008",
                testable={"why": "逐 m 数值可判"})["data"]["conjecture_id"]
    up = _call(st, conjecture_id=cid, statement="谱落在 [-m, m] 内。",
               origin="experiment:0008", status="supported_not_proved",
               experiment_ids=["0008"])
    assert up["ok"], up["error"]
    assert up["data"]["status"] == "supported_not_proved"

    # 只改 notes：状态与实验清单必须原样留着
    again = _call(st, conjecture_id=cid, statement="谱落在 [-m, m] 内。",
                  origin="experiment:0008", notes="补一句备注")
    assert again["ok"], again["error"]
    assert again["data"]["status"] == "supported_not_proved", "没提状态 ⇒ 不许退回 proposed"
    assert again["data"]["experiment_ids"] == ["0008"]
    assert again["data"]["notes"] == "补一句备注"


def test_known_in_literature_records_who_proved_it(tmp_path: Path):
    """正控：`known_in_literature` 指向库里真有的文献（"别人证过"与"我们证过"分开）。"""
    st = _store(tmp_path)
    _literature(st, "0037")
    res = _call(st, statement="鞅差阵列的 CLT 成立。", origin="experiment:0002",
                status="known_in_literature", known_lit_id="0037")
    assert res["ok"], res["error"]
    assert res["data"]["known_lit_id"] == "0037"


def test_refuted_accepts_the_refusal_ref(tmp_path: Path):
    """裁定 ②：被拒那一档是 `refuted` 的第二条来路（与反例实验并列）。"""
    st = _store(tmp_path)
    cid = _call(st, statement="截面面积至多 2a²。", origin="f-manuscript:reports/f-proof-000001.md",
                status="needs_evidence", notes="还没有可检验形式")["data"]["conjecture_id"]
    got = CL.mark_refuted(store=st, conjecture_id=cid,
                          refusal_ref="verifications/000000.jsonl#v-000003", actor="agent-V")
    assert got["ok"] is not False, got
    assert got["status"] == "refuted"
    assert got["refusal_ref"] == "verifications/000000.jsonl#v-000003"
    assert "refuted_without_counterexample" not in {
        str(issue.code) for issue in __import__("agentflow.verify", fromlist=["verify_all"])
        .verify_all(st).issues}, "带 refusal_ref 的 refuted 不该被审计报成'没有反例'"


def test_mark_refuted_never_creates_a_row(tmp_path: Path):
    """裁定 ② 的反方向：被拒必须有一条被登记过的命题；找不到 ⇒ 不新建一行。"""
    st = _store(tmp_path)
    got = CL.mark_refuted(store=st, statement="台账里没有这一条。",
                          refusal_ref="b-refusal:must_start_as_conjecture#x", actor="agent-B")
    assert got["ok"] is False and got["kind"] == "unknown_conjecture", got
    assert st.rows("conjectures") == [], "被拒的那一笔不许凭空造一行"


def test_promoted_to_statement_is_a_reading_not_a_status(tmp_path: Path):
    """裁定 ①：进命题台账只给读数，不改猜想行的状态（不用 `promoted`）。"""
    st = _store(tmp_path)
    cid = _call(st, statement="任意平面截面至多 2a²。", origin="experiment:0009",
                testable={"why": "逐方向数值可判"})["data"]["conjecture_id"]
    before = CL.promoted_to_statement(st, {"statement": "任意平面截面至多 2a²。"})
    assert before["checked"] is True and before["stmt_id"] == "", before
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", {"stmt_id": "000001",
                                 "statement_full": "任意平面截面至多 2a²。",
                                 "kind": "theorem", "status": "active",
                                 "origin": "own_result",
                                 "quote_reason": "夹具：还没查（不是没通过）",
                                 "created_at": TS, "updated_at": TS})
    after = CL.promoted_to_statement(st, {"statement": "任意平面截面至多 2a²。"})
    assert after["stmt_id"] == "000001", after
    row = next(r for r in st.rows("conjectures") if r["conjecture_id"] == cid)
    assert row["status"] == "proposed", f"读数不许改状态：{row}"


# ---------------------------------------------------------------- 负控

@pytest.mark.parametrize(
    "patch,expect",
    [
        ({"status": "supported_not_proved"}, "至少一条检验过它的实验"),
        ({"status": "refuted"}, "counterexample_experiment_id"),
        ({"status": "proved"}, "proof_experiment_id"),
        ({"status": "known_in_literature"}, "known_lit_id"),
        ({"status": "withdrawn"}, "withdraw_reason"),
        ({"status": "proposed", "testable": None}, "testable"),
        ({"form": "对一切"}, "form"),
        ({"status": "大概是吧"}, "status"),
        ({"statement": "这条猜想成立吗？"}, "疑问词"),
    ],
)
def test_schema_state_machine_is_the_only_judge(tmp_path: Path, patch, expect):
    """负控：状态机不在库层重写 —— 每条拒收条件都真的走进 `validate()`。

    判据打在两处：① 调用返回失败；② 错误原文里出现那条判据的关键词
    （只断言"失败了"会让"因为别的原因失败"也算通过）。
    """
    st = _store(tmp_path)
    kw = {"statement": "对一切 m，谱落在 [-m, m] 内。", "origin": "experiment:0003",
          "testable": {"why": "逐 m 可判"}, **patch}
    res = _call(st, **kw)
    assert res["ok"] is False, res["data"]
    assert expect in str(res["error"]), res["error"]


def test_referencing_a_missing_experiment_is_refused_at_write_time(tmp_path: Path):
    """负控（跨对象）：引用不存在的实验 ⇒ 写入期就拒（schema 看不见别的表）。"""
    st = _store(tmp_path)
    res = _call(st, statement="谱落在 [-m, m] 内。", origin="experiment:9999",
                testable={"why": "逐 m 可判"}, status="supported_not_proved",
                experiment_ids=["9999"])
    assert res["ok"] is False
    assert "不存在的实验" in str(res["error"])
    assert st.rows("conjectures") == [], "被拒的猜想一行都不许落库"


def test_referencing_a_missing_literature_is_refused_at_write_time(tmp_path: Path):
    """负控（跨对象）：`known_lit_id` 不在库里 ⇒ 写入期拒。"""
    st = _store(tmp_path)
    res = _call(st, statement="它是别人证的。", origin="experiment:0004",
                status="known_in_literature", known_lit_id="0099")
    assert res["ok"] is False and "不在 literature 表里" in str(res["error"])


def test_updating_a_missing_conjecture_does_not_silently_create_one(tmp_path: Path):
    """负控（三态）：给了一个库里没有的 `conjecture_id` ⇒ 抛，不许静默新建。

    静默新建的后果是"两条看起来都正常的重复猜想"，而没有任何地方会响。
    """
    st = _store(tmp_path)
    res = _call(st, conjecture_id="0042", statement="谱落在 [-m, m] 内。",
                origin="experiment:0005", testable={"why": "逐 m 可判"})
    assert res["ok"] is False and "不存在" in str(res["error"])
    assert st.rows("conjectures") == []


def test_origin_is_required(tmp_path: Path):
    """负控：`origin` 必填 —— 防"凭空出现的猜想"。"""
    st = _store(tmp_path)
    res = _call(st, statement="谱落在 [-m, m] 内。")
    assert res["ok"] is False
    assert "origin" in str(res["error"])


# ---------------------------------------------------------------- 反方向：没有"立题"这个面

def test_no_action_and_no_tool_registers_a_conjecture(tmp_path: Path):
    """撤掉之后的反方向（业主 2026-11-13 裁定甲）：谁都没有「立一条猜想」这个面。

    三格：① D 的动作表里没有 `register_conjecture`；② 工具面上没有那件工具；
    ③ D 的写集里没有 `conjectures`（它在 E / F / B 的写集里 —— 产出侧才写）。
    """
    acts = {a.action for a in specs.builtin_specs()["D"].actions}
    assert "register_conjecture" not in acts, f"D 的动作面里又有它了：{sorted(acts)}"

    reg = build_registry(workspace_root=str(tmp_path)).registry
    assert "conjecture.register_conjecture" not in set(reg.names()), (
        "工具面上又有 `conjecture.register_conjecture` 了 —— 台账的唯一写点在库层"
        "（`agentflow.conjectureledger`），不该再有第二个入口")

    assert "conjectures" not in set(CAP.WRITE_SETS["D"]), sorted(CAP.WRITE_SETS["D"])
    for role in ("E", "F", "B"):
        assert "conjectures" in set(CAP.WRITE_SETS[role]), (
            f"{role} 是产出侧，台账那一笔该落在它的写集里：{sorted(CAP.WRITE_SETS[role])}")


def test_the_generic_write_face_cannot_create_a_conjecture(tmp_path: Path):
    """堵后门（裁定甲的必要配套）：通用写口不许直写 `conjectures`。

    改前这张表是敞着的（`store.direct_write_refusal` 只拒 statements / dependencies /
    lit_candidates）⇒ 任何非只读角色都能 `table.create(table="conjectures")` 落一行。
    """
    from agentflow.refusals import PRECONDITION_REASON  # noqa: F401  （口径同族，仅做导入面不走样）
    from agentflow.store import DIRECT_WRITE_REFUSED, direct_write_refusal

    why = direct_write_refusal("conjectures")
    assert why.startswith(DIRECT_WRITE_REFUSED), why
    assert "conjectureledger" in why, f"拒信要指回唯一写点：{why}"
    st = _store(tmp_path)
    from agentflow.tools import table_tools as TT
    from agentflow.tools.base import ToolRegistry

    reg = ToolRegistry(name="t")
    reg.bound_role = "E"
    TT.register(reg, store=st)
    res = reg.call("table.create", table="conjectures",
                   row={"conjecture_id": "000009", "statement": "手写一行。",
                        "origin": "gap", "status": "needs_evidence", "notes": "手写"})
    assert res.ok is False, res.data
    assert st.rows("conjectures") == [], "通用写口把这一行写进去了 ⇒ 后门还开着"
