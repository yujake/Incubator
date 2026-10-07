"""探针：实测 attack.* / graph.* 各 handler 的失败 kind（修复前基线）。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"D:\Incubator\agentflow\src")
sys.path.insert(0, r"D:\Incubator\agentflow\tests")

from agentflow.store import Store
from agentflow.tools import attack_tools as AT
from agentflow.tools import graph_tools as GT
from agentflow.tools.base import ToolRegistry


def show(label, res):
    print(f"  {label:52s} ok={res.ok!s:5s} kind={res.meta.get('kind')!r:22s} err={(res.error or '')[:90]}")


def make_store(tag):
    root = Path(tempfile.mkdtemp(prefix=f"probe-{tag}-"))
    st = Store(root)
    st.init()
    return st


def corrupt(st, filename):
    (st.data / filename).write_text("{ 这不是 JSON", encoding="utf-8")


print("=" * 78)
print("[A] attack.* 的失败 kind（健康 store，制造 PlanError / ValueError）")
st = make_store("attack")
reg = ToolRegistry(name="attack")
AT.register(reg, store=st)

show("create_plan 缺 owner (PlanError)", reg.call(
    "attack.create_plan", problem="x", problem_key="k1", subgoals=[{"sid": "s1", "text": "t"}]))
show("create_plan budget 非法 (schema ValueError)", reg.call(
    "attack.create_plan", problem="x", problem_key="k2",
    budget={"max_rounds": "abc", "max_parallel_subgoals": 1, "max_persist_attempts": 1, "max_depth": 1}))
show("step 计划不存在 (PlanError)", reg.call("attack.step", plan_id="9999"))
show("status 计划不存在 (PlanError)", reg.call("attack.status", plan_id="9999"))
show("check_budget budget=None", reg.call("attack.check_budget", budget=None))
show("list_plans", reg.call("attack.list_plans"))

print("[A2] attack.* 在表损坏时（StoreError 应被守住）")
corrupt(st, "attack_plans.json")
show("list_plans 表坏", reg.call("attack.list_plans"))
show("status 表坏", reg.call("attack.status", plan_id="0000"))
show("step 表坏", reg.call("attack.step", plan_id="0000"))
show("create_plan 表坏", reg.call("attack.create_plan", problem="p", problem_key="k"))
st2 = make_store("attack2")
reg2 = ToolRegistry(name="attack2")
AT.register(reg2, store=st2)
show("create_plan 表坏(干净store)", reg2.call("attack.create_plan", problem="p", problem_key="k"))

print("[A3] attack 未接线（store=None）")
reg3 = ToolRegistry(name="attack3")
AT.register(reg3, store=None)
show("create_plan 未接线", reg3.call("attack.create_plan", problem="p", problem_key="k"))
show("list_plans 未接线", reg3.call("attack.list_plans"))

print()
print("=" * 78)
print("[B] graph.* 在表损坏时（StoreError 应被守住）")
gst = make_store("graph")
greg = ToolRegistry(name="graph")
GT.register(greg, store=gst)
corrupt(gst, "relations.json")
show("graph.build 表坏", greg.call("graph.build"))
show("graph.stats 表坏", greg.call("graph.stats"))
show("graph.neighbors 表坏", greg.call("graph.neighbors", concept_id="0000"))
show("graph.relations_between 表坏", greg.call("graph.relations_between", a="0000", b="0001"))

print("[B2] graph.* 正常（小图）")
from agentflow.tools.graph_tools import RelationGraph

concepts = [{"concept_id": "0000", "name": "群"}, {"concept_id": "0001", "name": "阿贝尔群"}]
rels = [{"relation_id": "0000", "concept_ids": ["0000", "0001"], "description": "d", "lit_id": "0000",
         "quote_verified": True, "status": "active", "statement": "s", "quote": "q",
         "page_range": {"start": 1, "end": 1, "label": "p.1"}}]
g = RelationGraph(concepts, rels, [])
greg2 = ToolRegistry(name="graph2")
GT.register(greg2, graph=g)
nb = greg2.call("graph.neighbors", concept_id="0000")
print(f"  neighbors keys={sorted(nb.data)}")
print(f"  neighbors[0] keys={sorted(nb.data['neighbors'][0])}")
print(f"  declared returns={greg2.get('graph.neighbors').returns!r}")
print(f"  graph.concepts 存在吗: {'graph.concepts' in greg2}")
print(f"  graph_tools 注册的工具: {greg2.names()}")
print("[B3] neighbors 的裸列表：RelationGraph.neighbors 返回类型")
print(f"  type(g.neighbors('0000')) = {type(g.neighbors('0000'))}")
