# -*- coding: utf-8 -*-
"""T3 猜想接线的最小集：`conjecture.register` 的正控与逐条负控。

依据：`draft/29` §7.5 的状态机 + `draft/30` §T1 的数据面 + `draft/31` P7 第 4 张表。

这一组要证明四件事（每条都有反方向）：

1. 新建：省略 `conjecture_id` ⇒ 分配编号、落库、`status`/`form` 兜默认值；
2. 更新：`None` 是"我没提这件事" ⇒ 库里已有值原样保留（一次只改 `notes`
   的调用不许把 `supported_not_proved` 静默退回 `proposed`）；
3. 单行内判据只有一份：状态机由 `schema.Conjecture.validate()` 判，工具层不重写
   （`refuted` 无反例实验 / `proposed` 无 `testable` ⇒ 逐条拒收）；
4. 跨对象的存在性在写入期就核：引用不存在的实验 / 文献 ⇒ 抛，而不是等
   `verify_all` 事后报（那时数据已经脏了）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import conjecture_tools as CT
from agentflow.tools.base import ToolRegistry

TS = "2026-01-01T00:00:00+00:00"


def _store(tmp_path: Path) -> Store:
    st = Store(tmp_path)
    st.init()
    return st


def _reg(st: Store) -> ToolRegistry:
    reg = ToolRegistry(name="conjecture-test")
    reg.bound_role = "D"          # 猜想的写入面只给 D（提出的与检验的要能分开）
    CT.register(reg, store=st)
    return reg


def _experiment(st: Store, eid: str = "0000", **patch) -> dict:
    """落一行实验（`register_conjecture` 要核它真的在库里）。"""
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
           "path": f"library/{lid}.txt", "status": "unread",
           "created_at": TS, "created_by": "agent-A"}
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", row)
    return row


# ---------------------------------------------------------------- 正控

def test_create_allocates_an_id_and_applies_the_defaults(tmp_path: Path):
    """正控：新建一条 `proposed` 猜想（`testable` 必填，`form` 兜 `universal`）。"""
    st = _store(tmp_path)
    res = _reg(st).call("conjecture.register_conjecture",
                        statement="对一切 m，V_m = 8m(m+1)/3。",
                        origin="doc:0000#lem:varconst",
                        testable={"why": "枚举 m<=6 与闭式比对"})
    assert res.ok, res.error
    assert res.data["conjecture_id"] == S.format_id(0)
    assert res.data["status"] == "proposed" and res.data["form"] == "universal"
    assert res.data["origin"] == "doc:0000#lem:varconst"
    assert st.rows("conjectures")[0]["conjecture_id"] == S.format_id(0)


def test_update_keeps_what_the_caller_did_not_mention(tmp_path: Path):
    """正控（更新语义）：`None` = 没提 ⇒ 保留；这条挡住"改 notes 把状态清回 proposed"。"""
    st = _store(tmp_path)
    _experiment(st, "0008")
    reg = _reg(st)
    cid = reg.call("conjecture.register_conjecture", statement="谱落在 [-m, m] 内。",
                   origin="doc:0000#prop:step",
                   testable={"why": "逐 m 数值可判"}).data["conjecture_id"]
    up = reg.call("conjecture.register_conjecture", conjecture_id=cid, statement="谱落在 [-m, m] 内。",
                  origin="doc:0000#prop:step", status="supported_not_proved",
                  experiment_ids=["0008"])
    assert up.ok, up.error
    assert up.data["status"] == "supported_not_proved"

    # 只改 notes：状态与实验清单必须原样留着
    again = reg.call("conjecture.register_conjecture", conjecture_id=cid, statement="谱落在 [-m, m] 内。",
                     origin="doc:0000#prop:step", notes="补一句备注")
    assert again.ok, again.error
    assert again.data["status"] == "supported_not_proved", "没提状态 ⇒ 不许退回 proposed"
    assert again.data["experiment_ids"] == ["0008"]
    assert again.data["notes"] == "补一句备注"


def test_known_in_literature_records_who_proved_it(tmp_path: Path):
    """正控：`known_in_literature` 指向库里真有的文献（"别人证过"与"我们证过"分开）。"""
    st = _store(tmp_path)
    _literature(st, "0037")
    res = _reg(st).call("conjecture.register_conjecture", statement="鞅差阵列的 CLT 成立。",
                        origin="doc:0000#thm:mclt", status="known_in_literature",
                        known_lit_id="0037")
    assert res.ok, res.error
    assert res.data["known_lit_id"] == "0037"


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
    """负控：状态机不在工具层重写 —— 每条拒收条件都真的走进 `validate()`。

    判据打在两处：① 工具返回 `ok=False`；② 错误原文里出现那条判据的关键词
    （只断言"失败了"会让"因为别的原因失败"也算通过）。
    """
    st = _store(tmp_path)
    kw = {"statement": "对一切 m，谱落在 [-m, m] 内。", "origin": "doc:0000#x",
          "testable": {"why": "逐 m 可判"}, **patch}
    res = _reg(st).call("conjecture.register_conjecture", **kw)
    assert res.ok is False, res.data
    assert expect in str(res.error), res.error


def test_referencing_a_missing_experiment_is_refused_at_write_time(tmp_path: Path):
    """负控（跨对象）：引用不存在的实验 ⇒ 写入期就拒（schema 看不见别的表）。"""
    st = _store(tmp_path)
    res = _reg(st).call("conjecture.register_conjecture", statement="谱落在 [-m, m] 内。",
                        origin="doc:0000#x", testable={"why": "逐 m 可判"},
                        status="supported_not_proved", experiment_ids=["9999"])
    assert res.ok is False
    assert "不存在的实验" in str(res.error)
    assert st.rows("conjectures") == [], "被拒的猜想一行都不许落库"


def test_referencing_a_missing_literature_is_refused_at_write_time(tmp_path: Path):
    """负控（跨对象）：`known_lit_id` 不在库里 ⇒ 写入期拒。"""
    st = _store(tmp_path)
    res = _reg(st).call("conjecture.register_conjecture", statement="它是别人证的。",
                        origin="doc:0000#x", status="known_in_literature",
                        known_lit_id="0099")
    assert res.ok is False and "不在 literature 表里" in str(res.error)


def test_updating_a_missing_conjecture_does_not_silently_create_one(tmp_path: Path):
    """负控（三态）：给了一个库里没有的 `conjecture_id` ⇒ 抛，不许静默新建。

    静默新建的后果是"两条看起来都正常的重复猜想"，而没有任何地方会响。
    """
    st = _store(tmp_path)
    res = _reg(st).call("conjecture.register_conjecture", conjecture_id="0042",
                        statement="谱落在 [-m, m] 内。", origin="doc:0000#x",
                        testable={"why": "逐 m 可判"})
    assert res.ok is False and "不存在" in str(res.error)
    assert st.rows("conjectures") == []


def test_unknown_parameter_is_rejected_by_the_seam(tmp_path: Path):
    """负控（参数面）：未声明的参数由参数门拒（不是被静默忽略）。"""
    st = _store(tmp_path)
    res = _reg(st).call("conjecture.register_conjecture", statement="谱落在 [-m, m] 内。",
                        origin="doc:0000#x", evidence_kind="proof")
    assert res.ok is False and "未声明" in str(res.error)


def test_origin_is_required(tmp_path: Path):
    """负控：`origin` 必填 —— 防"凭空出现的猜想"。"""
    st = _store(tmp_path)
    res = _reg(st).call("conjecture.register_conjecture", statement="谱落在 [-m, m] 内。")
    assert res.ok is False


def test_tool_writes_only_the_conjectures_table(tmp_path: Path):
    """正控（副作用面）：这个工具只写 conjectures（写集声明与实现一致）。"""
    st = _store(tmp_path)
    _experiment(st, "0008")
    reg = _reg(st)
    reg.call("conjecture.register_conjecture", statement="谱落在 [-m, m] 内。", origin="doc:0000#x",
             testable={"why": "逐 m 可判"}, status="supported_not_proved",
             experiment_ids=["0008"])
    spec = reg.get("conjecture.register_conjecture")
    assert spec.side_effect == "write_local"
    assert spec.roles == ("D",)
    assert S.TABLES["conjectures"]["file"] == "conjectures.json"
