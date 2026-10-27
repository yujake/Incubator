# -*- coding: utf-8 -*-
"""D 到 B 的路：D 在代码里把 F 的证明手稿递给 B（业主 2026-10-26 晚的裁定）。

业主原话（唯一权威，逐字）：
```
「？？？F怎么还默认不搞推理？F的职责是什么？D到B没有路吗？加」
「D 携带 → B 读稿落依赖」
```

## 改前是什么形态

D→B 在代码里没有任何直接调用点：D 只能用 `summon` 派 B，args 由模型产出 ⇒
所谓"D 携带"只能退化成"D 的研究报告里由代码生成一张携带单，B 自己去读"，
而 B 从来没有被 D 这样调用过（真机 `dependencies` 0 行）。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a D 直接交 B | D 交付一件带证明的命题 ⇒ B 那一笔真收到手稿（`manuscript_source=carried_by_D`）、`dependencies` 落行 | 改前 D 没有这条调用 |
| b 必走 | 携带走的是 D 的交付路径（`write_report`）里的代码调用，不是模型的 args | 改前只能靠模型记得派 B |
| c 反真空 | 把 D→B 这条调用打桩成空 ⇒ a 必红 | 改前根本没有这条调用可打桩 |
| 权限面 | D→B 的边在册、D 的写集里没有 `statements` / `dependencies`（B 仍是唯一写者） | —— |

全部 tmp 工作区、零模型钱（F 那一轮用一个假缝；V 那一笔用一个按剧本回答的替身）。

## 2026-10-26 之后多出来的那一组依赖行（D8）

F 的出口改成了 `B.register_statement`，于是 F 自己那一轮递交时 B 就已经读过同一份稿、
把依赖边落好了 —— 盘上因此多一组 `used_by = stmt:<F 的命号>` 的行，而它仍然只有 B 能写。
这改变了两件读数的含义，所以两条判据跟着改（都是变严，不是放宽）：

- "F 那一侧不写依赖台账"：改成点名那一组行是谁落的（`used_by` 是 F 的命号、
  `label` 指着手稿依赖段），而不是断言盘上一行都没有；
- "D 交付这一笔落了边"：判据 a 先把 F 那一组行清掉（真实可达：F 登记时手上没有稿），
  让 D 的携带成为唯一可能落边的动作 —— 否则 `deps_written>=1` 会因为边早就在而真空绿。
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import capabilities as CAP
from agentflow import depsection as DS
from agentflow import host
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_d import AgentD
from agentflow.agent_f import AgentF
from agentflow.agent_v import AgentV
from agentflow.store import Store

THEOREM_A = S.format_id(0)
SRC_CARRIED = "carried_by_D"


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _add_statement(store: Store, stmt_id: str, *, label: str = "",
                   level: str = "proof_review") -> dict:
    """写一条在册命题；要 `proof_review` 就先让 V 签，再升档（写入期有闸）。"""
    row = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem",
        label=label or f"在册命题 {stmt_id}",
        statement_text=f"命题 {stmt_id} 的短版",
        statement_full=f"命题 {stmt_id} 的完整正文（含假设）。",
        proof_text=f"命题 {stmt_id} 的证明正文（判据夹具）。",
        evidence_kind="heuristic", status="active", quote_verified=None,
        quote_reason="判据夹具：自产命题，没有外部引文要比对",
        created_at=S.now_iso(), created_by="agent-B")
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    if level == "proof_review":
        signed = VR.record_verification(
            store.root, statement_id=stmt_id,
            proof_text=f"命题 {stmt_id} 的证明正文（判据夹具）。",
            verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
            store=store, proof_no=1)
        assert signed.get("checked") is True, signed
    got = next(dict(r) for r in store.rows("statements")
               if str(r.get("stmt_id")) == stmt_id)
    got["evidence_kind"] = level
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", got)
    return got


class FakeSeam:
    """F 的假缝（`judge_json` 认 `complete(prompt) -> str`）。"""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.payload, ensure_ascii=False)


def _proof_payload(cite: str) -> dict:
    return {"product": "proof", "strategy": "套用已知定理",
            "why_strategy": "由在册定理直接推出结论",
            "steps": [{"n": 1, "text": "由在册定理直接得到第一步。",
                       "cites": [cite], "assumption": False},
                      {"n": 2, "text": "由第 1 步得结论。", "cites": [cite],
                       "assumption": False}]}


def _run_f_proof(store: Store, *, cite: str = f"stmt:{THEOREM_A}") -> dict:
    """F 真走一轮 proof：写稿 → 秘书洗 → 登记（拿到命题号与盘上的稿）。"""
    f = AgentF(store, config={"workspace_root": store.root},
               llm=FakeSeam(_proof_payload(cite)))
    plan = f.create_plan("引理：由在册定理推出结论", "PK-D-TO-B", subgoals=[
        {"sid": "s1", "text": "由在册定理推出目标引理", "owner": "F",
         "testable": "手稿的依赖段每条引用一行"}])
    out = f.step(str(plan["plan_id"]))
    assert out.get("action") == "proof", out
    assert str(out.get("statement_id") or ""), out
    return out


def _d_with_b(store: Store) -> AgentD:
    """按真机装配的形状造 D：构造期拿到同一个 B 实例（`specs/d.py` 的 `peers["B"]`）。"""
    b = AgentB(store, extractor=None, extract_text=None, config={})
    return AgentD(store, config={"workspace_root": store.root}, b=b)


def _a_holds(store: Store, delivery: dict) -> bool:
    """判据 a 的判据本体（正控与反真空共用同一个谓词）。

    四件事一起判：D 真递了、B 收下的读数说稿是 `carried_by_D`、依赖行落在 F 那条
    命题上、来源正是那份稿点名的那一条。
    """
    results = [dict(x) for x in (delivery.get("results") or [])]
    if not delivery.get("checked") or int(delivery.get("delivered") or 0) < 1 or not results:
        return False
    hit = next((r for r in results if r.get("ok")), None)
    if hit is None:
        return False
    if str(hit.get("manuscript_source") or "") != SRC_CARRIED:
        return False
    rows = [dict(r) for r in store.rows("dependencies")]
    if not rows:
        return False
    sid = str(hit.get("stmt_id") or "")
    return ({str(r.get("used_by")) for r in rows} == {f"stmt:{sid}"}
            and {str(r.get("source_stmt_id")) for r in rows} == {THEOREM_A})


# ------------------------------------------------------------------ 权限面


def test_the_d_to_b_edge_is_legal_and_b_is_still_the_only_writer() -> None:
    """权限面：D→B 的边在册；D 的写集里没有 `statements` / `dependencies`。

    D 只是"递交"（调 B 的登记入口），落表仍然是 B（经秘书那一笔事务）——
    所以这条新路不需要放宽任何写集，只需要那条本来就在的边。
    """
    assert "B" in CAP.ALLOWED_EDGES["D"], CAP.ALLOWED_EDGES["D"]
    for table in ("statements", "dependencies"):
        assert table not in CAP.WRITE_SETS["D"], (table, CAP.WRITE_SETS["D"])


def test_d_is_built_with_the_same_b_instance(tmp_path: pathlib.Path) -> None:
    """装配面：`specs/d.py` 在构造期把同一个 B 实例交给 D（不是各建各的）。"""
    store = _ws(tmp_path)
    reg = host.build_role_registry(store, providers=[object()])
    d = reg["D"][1](store=store)
    b = reg["B"][1](store=store)
    assert d.b is b, "D 手上的 B 不是接线层那个 B（构造期没有绑同一个实例）"


# ------------------------------------------------------------------ a D 直接交 B


def test_d_hands_the_manuscript_to_b_and_b_lands_the_edges(
        tmp_path: pathlib.Path) -> None:
    """a D 交付一件带证明的命题 ⇒ B 那一笔真收到手稿、`dependencies` 落行。

    改前红：D 的交付路径里没有任何一处调 `AgentB.register_statement` ⇒ 这条断言
    一条都成立不了（`dependencies` 0 行）。

    2026-10-26 起 F 的出口也是 `B.register_statement`（D8）⇒ F 那一轮递交时 B 已经
    落过这条边了。所以先把那几行清掉（真实可达的状态：F 登记时手上没有稿），让
    "D 携带"成为唯一可能落边的动作 —— 否则 `deps_written>=1` 会因为"边早就在"而
    变成真空绿，而这条判据要证的正是"D 这一笔自己把边落出来了"。
    """
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A, label="定理甲")
    proof = _run_f_proof(store)
    f_stmt = str(proof["statement_id"])
    assert pathlib.Path(store.root, str(proof["manuscript_path"])).is_file(), proof
    assert proof.get("manuscript_washed") is True, proof
    # F 那一侧不写依赖台账（作者只写内容）：盘上这一行是 B 在 F 递交时读稿落的
    # （`used_by` 正是 F 那条命号、`label` 指着手稿依赖段的第几行）。
    author_side = [dict(r) for r in store.rows("dependencies")]
    assert {str(r.get("used_by")) for r in author_side} == {f"stmt:{f_stmt}"}, author_side
    assert all("手稿依赖段" in str(r.get("label") or "") for r in author_side), author_side
    with store.tx("dependencies", actor="test") as tx:
        for row in author_side:
            tx.delete("dependencies", row["dep_id"], note="判据夹具：清掉 F 那一轮落的边")

    d = _d_with_b(store)
    d.write_report()
    delivery = d.last_delivery
    assert delivery.get("checked") is True, delivery
    assert delivery.get("rows") == 1, delivery
    assert _a_holds(store, delivery), delivery
    rec = delivery["results"][0]
    assert rec["ok"] is True, rec
    assert rec["stmt_id"] == f_stmt, rec
    assert rec["manuscript_washed"] is True, (
        "B 读到的不是秘书洗过的那一版（读数里没有 manuscript_washed）", rec)
    assert int(rec["deps_written"]) >= 1, rec

    rows = [dict(r) for r in store.rows("dependencies")]
    assert {str(r.get("used_by")) for r in rows} == {f"stmt:{f_stmt}"}, rows
    assert {int(r.get("path_group")) for r in rows} == {1}, rows
    # 命题行一个字没多：D 递交的是在册那一行（B 不新建、也不重判档位）
    assert [str(r.get("stmt_id")) for r in store.rows("statements")].count(f_stmt) == 1
    # 幂等：同一趟再交一次不重复落边（D 每轮都会携带一遍）
    again = _d_with_b(store)
    again.write_report()
    assert int(again.last_delivery["results"][0]["deps_written"]) == 0, (
        "同一份稿第二次携带又落了一遍依赖边（幂等被破坏）", again.last_delivery)
    assert len(store.rows("dependencies")) == len(rows)


def test_the_delivery_reading_is_written_into_d_report(tmp_path: pathlib.Path) -> None:
    """a 的读数面：D 的报告里有"交给 B 的登记回执"（递了没递、B 落了几条边）。"""
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A, label="定理甲")
    _run_f_proof(store)
    d = _d_with_b(store)
    report = pathlib.Path(str(d.write_report())).read_text(encoding="utf-8")
    assert "## D 交给 B 的登记回执（D→B）" in report, report[-2000:]
    assert "carried_by_D" in report, report[-2000:]


def test_without_b_the_delivery_says_so_instead_of_pretending(tmp_path: pathlib.Path) -> None:
    """三态：直调 `AgentD(store)`（没有 `b=`）⇒ 携带单照生成，但读数说没递。

    判据是"这一笔一条边都没落"，所以比的是携带前后那本台账一字未变 —— 盘上本来就有
    的那一行是 F 递交时 B 落的（D8），与 D 这一笔无关。
    """
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A, label="定理甲")
    _run_f_proof(store)
    before = [dict(r) for r in store.rows("dependencies")]
    d = AgentD(store, config={"workspace_root": store.root})
    d.write_report()
    assert d.last_delivery.get("checked") is False, d.last_delivery
    assert "没有 B 的入口" in str(d.last_delivery.get("why") or ""), d.last_delivery
    assert [dict(r) for r in store.rows("dependencies")] == before, store.rows("dependencies")


# ------------------------------------------------------------------ b 必走（代码行为）


def test_the_delivery_is_in_d_code_not_in_model_args(tmp_path: pathlib.Path,
                                                     monkeypatch) -> None:
    """b 携带/内联至少一条在真机代码路径上是必走的：`write_report` 自己调那条路。

    判据：把 D 那一笔"递交给 B"包一层观察者 ⇒ 调 `write_report`（D 的交付动作）
    之后观察者必须被叫过，且它收到的就是携带单上的行 —— 全程没有任何模型参数。
    """
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A, label="定理甲")
    _run_f_proof(store)
    calls: list[list[dict]] = []
    real = AgentD._deliver_carried_to_b

    def spy(self, rows):
        calls.append([dict(r) for r in rows])
        return real(self, rows)

    monkeypatch.setattr(AgentD, "_deliver_carried_to_b", spy)
    d = _d_with_b(store)
    d.write_report()
    assert len(calls) == 1, calls
    assert [r["statement_id"] for r in calls[0]], calls[0]


# ------------------------------------------------------------------ c 反真空


def test_stubbing_the_d_to_b_call_out_turns_a_red(tmp_path: pathlib.Path,
                                                  monkeypatch) -> None:
    """c 反真空：把 D→B 这条调用打桩成空 ⇒ a 必红。

    打桩点就是 D 的代码里那一笔（`AgentD._deliver_carried_to_b`）：返回"什么都没递"，
    于是携带前后那本台账一字未变、`_a_holds` 取反。它证明 a 绿的来源正是这条调用。
    """
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A, label="定理甲")
    _run_f_proof(store)
    before = [dict(r) for r in store.rows("dependencies")]
    monkeypatch.setattr(AgentD, "_deliver_carried_to_b",
                        lambda self, rows: {"checked": True, "rows": len(rows or []),
                                            "delivered": 0, "results": [],
                                            "why": "（反真空：D→B 这条调用被打桩成空）"})
    d = _d_with_b(store)
    d.write_report()
    assert _a_holds(store, d.last_delivery) is False, d.last_delivery
    assert [dict(r) for r in store.rows("dependencies")] == before, store.rows("dependencies")


# ------------------------------------------------------------------ 端到端（F→D→B→V）


class _VSeam:
    """V 的假缝（`ask` 形状）。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def ask(self, prompt: str, **_kw):
        from types import SimpleNamespace

        self.prompts.append(prompt)
        return SimpleNamespace(text=self.reply, problem="")


def test_the_chain_f_proof_d_carry_b_edges_v_signs(tmp_path: pathlib.Path) -> None:
    """端到端：F 真推一轮 → 稿 → D 直接交 B → 依赖行 → V 签字。

    这一条是业主那句「D 到 B 没有路吗？加」的整条演示：四步全在真机代码路径上，
    没有一步靠模型记得去传。
    """
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A, label="定理甲")
    proof = _run_f_proof(store)
    f_stmt = str(proof["statement_id"])

    d = _d_with_b(store)
    d.write_report()
    assert _a_holds(store, d.last_delivery), d.last_delivery
    rows = [dict(r) for r in store.rows("dependencies")]
    assert rows, "依赖面一条都没有落"

    reply = json.dumps({
        "verdict": "成立", "defect_step": None, "why": "", "findings": [],
        "citation_checks": [{"stmt_id": THEOREM_A, "verdict": "consistent",
                             "quote_verbatim": False,
                             "note": "由定理甲那一步，用法一致"}]}, ensure_ascii=False)
    v_llm = _VSeam(reply)
    v = AgentV(store, workspace_root=store.root, llm=v_llm)
    row = next(dict(r) for r in store.rows("statements")
               if str(r.get("stmt_id")) == f_stmt)
    signed = v.verify_proof(f_stmt, proof_text=str(row.get("proof_text") or ""))
    assert signed.get("signed_bit3") is True, signed
    assert {c["stmt_id"] for c in signed.get("citation_checks") or []} == {THEOREM_A}, signed
    assert "## 引用核实" in v_llm.prompts[-1], v_llm.prompts[-1][-2500:]
    ledger, problems = VR.list_verifications(store.root, statement_id=f_stmt, limit=None)
    assert problems == [] and ledger, (problems, ledger)
    assert str(ledger[-1].get("verdict")) == "成立", ledger[-1]


def test_the_washed_flag_travels_with_the_file(tmp_path: pathlib.Path) -> None:
    """秘书洗过的那一版必须跟着文件走：B 读到的正文里带 `已洗=true` 那一行。"""
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A, label="定理甲")
    proof = _run_f_proof(store)
    text = pathlib.Path(store.root, str(proof["manuscript_path"])).read_text(encoding="utf-8")
    reading = DS.manuscript_wash_reading(text)
    assert reading["washed"] is True, (reading, text[:400])
    assert reading["actor"].startswith("secretary"), reading
