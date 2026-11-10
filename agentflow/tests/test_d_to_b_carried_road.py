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

import pytest

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import capabilities as CAP
from agentflow import conductor as CND
from agentflow import depsection as DS
from agentflow import host
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_d import AgentD
from agentflow.agent_f import AgentF
from agentflow.agent_v import AgentV
from agentflow.store import Store
# ---------------------------------------------------------------- 命题形态闸的夹具答案
#
# 2026-11-07（业主裁定）：F 交稿之前多了一道"命题形态闸"
# （`agent_f/core.py::_proposition_form_gate` → `Secretary.judge_proposition_form`）。
# 它是一次模型调用，而这一份夹具里没有模型 ⇒ 判据会 fail-closed 拒收（那是对的行为）。
# 下面这个 autouse 夹具只替代那一次调用（给一个"形态合规"的答案），不摘闸：
# 闸照跑、判据仍是那一处实现；写成补丁而不是"让闸放行"，是为了让"夹具里没有模型"
# 这件事只在这一个地方被交代一次。
@pytest.fixture(autouse=True)
def _proposition_form_answers_ok(monkeypatch):
    from agentflow import secretary as _SEC

    monkeypatch.setattr(
        _SEC.Secretary, "judge_proposition_form",
        lambda self, **_kw: {"checked": True, "well_formed": True,
                             "conditions": "夹具：前提", "conclusion": "夹具：结论",
                             "problems": [], "decision": "夹具：形态合规",
                             "refused": "", "reason": "夹具：形态合规"})

THEOREM_A = S.format_id(0)
SRC_CARRIED = "carried_by_D"


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _add_statement(store: Store, stmt_id: str, *, label: str = "",
                   level: str = "proof_review") -> dict:
    """写一条在册命题；要 `proof_review` 就先让 V 签，再升档（写入期有闸）。

    ## 为什么要签满 `SIGN_STREAK_NEED` 次（2026-10-29 口径）
    写入期那道闸（`store` 的 `proof_review_without_evidence`）现在读的是"连续 3 次
    「成立」且同一份正文"的签；改前它读的是"有一次「成立」"。所以夹具按同一份正文、
    同一证明号连签，并在这里钉住"第 1、2 次不翻位、第 3 次才翻"这条正控 ——
    `evidence_kind='proof_review'` 那一档的准入判据一个字都没放宽。

    ## 2026-11-05 口径：先预置五元位，再让签翻第 3 位
    可引门槛（`depsection.CITATION_MIN_LEVEL = pre_theorem`）读的是
    `evidencebits.derive_grade` 从五元位现算的等级，`evidence_kind` 只是历史列。
    所以这一格必须先把第 2 位（`proof`）落真 —— 只写 `proof_text` / 只改
    `evidence_kind` 的旧夹具在新口径下现算仍是 `conjecture`，F 的可引清单会如实
    拒掉它（本文件每一条都从这里开始）。第 3 位由下面三次真签翻真；档位随后只由
    等级反算（`kind_from_bits`），不再由夹具自报。
    """
    body = f"命题 {stmt_id} 的证明正文（判据夹具）。"
    row = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem",
        label=label or f"在册命题 {stmt_id}",
        statement_text=f"命题 {stmt_id} 的短版",
        statement_full=f"命题 {stmt_id} 的完整正文（含假设）。",
        proof_text=body,
        evidence_kind="heuristic", status="active", quote_verified=None,
        quote_reason="判据夹具：自产命题，没有外部引文要比对",
        created_at=S.now_iso(), created_by="agent-B")
    from agentflow import evidencebits as EB

    row.bits = EB.bits_of(origin="own_result", proof=True, proof_process=body,
                          kind="conjecture")
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    if level == "proof_review":
        need = int(VR.SIGN_STREAK_NEED)
        for i in range(1, need + 1):
            signed = VR.record_verification(
                store.root, statement_id=stmt_id,
                proof_text=body,
                verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
                store=store, proof_no=1, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
            assert signed.get("checked") is True, signed
            written = bool((signed.get("statement_writeback") or {}).get("written"))
            assert written is (i == need), (
                f"第 {i} 次「成立」的翻位读数是 written={written!r} —— 2026-10-29 口径："
                f"连续 {need} 次才发签，第 1..{need - 1} 次只落台账", signed)
    got = next(dict(r) for r in store.rows("statements")
               if str(r.get("stmt_id")) == stmt_id)
    # 档位只由等级反算：`proof ∧ reviewed` ⇒ `pre_theorem`，反算名 `proof_review`。
    got["evidence_kind"] = EB.kind_from_bits(got.get("bits") or {},
                                             kind=str(got.get("kind") or ""))
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", got)
    return got


def _cited_manuscript_with_a_real_sign(store: Store, stmt_id: str, *, label: str = "") -> str:
    """给一条在册命题落一份带真签的手稿（`reports/f-proof-<号>.md`），返回相对路径。

    ## 为什么这一格必须补（2026-11-08 业主：「V 现在只对手稿负责」）

    可引资格不再读 `statements.bits` 的等级，改读被引命题那一份手稿上有没有 V 签
    （`agent_v.core._cited_manuscripts`：`reports/f-proof-<号>.md` 先、`b-proof-<号>.md`
    后；读不到 ⇒ `manuscript_missing=True` + `admissible=False`，机械改判 `inadmissible`
    挡住这一签）。所以"在册命题"这一侧的前提是：它的证明有一份稿，稿上有真签。

    改前红：夹具只往 `statements` 里塞一行（+ 三次 `record_verification` 翻位），
    盘上没有那份稿 ⇒ `_cited_manuscripts` 判 `found=False` ⇒ 引用闸挡签 ⇒
    `verify_proof` 连判第一转就 `terminal=gate`，端到端那条链量不到"三转发签"。

    签是真的：先是 `record_pending_sign` 落一行 pending 台账（未在册/未登记形态那一档，
    与 `conftest.sign_before_registration` 同一口径），再把那一行的锚点写进签块 ——
    `manuscript_sign_standing` 会去台账里核这一签的背书，块本身不自己作证。
    正文 sha 与被签的那一份逐字相符（`write_manuscript_sign` 写盘前核过）。
    """
    body = f"命题 {stmt_id} 的证明正文（判据夹具）。"
    full = f"命题 {stmt_id} 的完整正文（含假设）。"
    rel = f"reports/f-proof-{stmt_id}.md"
    text = ("# F 的证明手稿（判据夹具：被引命题）\n\n"
            f"- 命题号：stmt:{stmt_id}\n"
            "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
            f"## 命题\n\n{full}\n\n"
            f"## 证明\n\n{body}\n\n"
            + DS.render_dependency_section([]))
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    on_disk = DS.proof_body(text).strip("\n")
    assert on_disk == body, (on_disk, body)
    row = VR.record_pending_sign(
        store.root, proof_text=on_disk, verdict={"verdict": "成立", "findings": []},
        verifier="agent-V", object_path=rel,
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                         "reason": "夹具：clean"})
    key = str(row.get("object_sha256") or row.get("proof_sha256") or "")
    anchor = (f"{VR.VERIFICATIONS_DIR}/{VR.PENDING_DIR_NAME}/{key}.jsonl"
              f"#{row.get('verification_id')}")
    wrote = VS.write_manuscript_sign(
        store.root, rel, proof_sha=VR.text_sha(on_disk),
        streak=int(VR.SIGN_STREAK_NEED), need=int(VR.SIGN_STREAK_NEED),
        verdict="成立", signer="V", at=S.now_iso(), ledger=anchor,
        statement_id=str(stmt_id), signed=True)
    assert wrote.get("state") == "written", (label, wrote)
    return rel


class FakeSeam:
    """F 的假缝（`judge_json` 认 `complete(prompt) -> str`）。"""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.payload, ensure_ascii=False)


class SameSearchSeam:
    """B 的同一命题检索的离线替身（2026-11-08：收录要先查一圈"是不是同一条"）。

    这一份夹具里没有模型；判据照跑，只替代那两次调用：挑检索词与"没查到同一条"。
    给的是"查过了、没有同一条"，不是"免查" —— 检索面与 fail-closed 仍由
    `register_statement._resolve_same_statement` 一处实现。
    """

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "fake"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def ask_json(self, prompt, *, system: str = "", task_id: str = "",
                 note: str = ""):
        if str(note).endswith("statement_keywords"):
            return ({"keywords": ["在册定理"], "why": "夹具：用命题里的数学词去捞"},
                    self._Call())
        if str(note).endswith("statement_same"):
            # 2026-11-08：判定与 `adjudicate_proposition` 收成同一处，题面要的是
            # decision / same_as（两档），不再是旧的 found。
            return ({"decision": "different", "same_as": "", "canonical_name": "",
                     "condition": "", "conclusion": "", "basis": [],
                     "reason": "夹具：条件不同的两条"}, self._Call())
        return ({}, self._Call())


def _proof_payload(cite: str) -> dict:
    return {"product": "proof", "strategy": "套用已知定理",
            "why_strategy": "由在册定理直接推出结论",
            "steps": [{"n": 1, "text": "由在册定理直接得到第一步。",
                       "cites": [cite], "assumption": False},
                      {"n": 2, "text": "由第 1 步得结论。", "cites": [cite],
                       "assumption": False}]}


def _run_f_proof(store: Store, *, cite: str = f"stmt:{THEOREM_A}") -> dict:
    """F 真走一轮 proof：写稿 → 秘书洗 → 落手稿登记条目（命题号还没发）。

    2026-11-07（解耦 + 裁边）：F 不再直接登记 statements（`F→B` 那条边已被裁去），
    所以这一轮拿到的是一份手稿登记条目；命题号由 B 在 V 签之后按 sha 认领时才发。
    """
    f = AgentF(store, config={"workspace_root": store.root},
               llm=FakeSeam(_proof_payload(cite)))
    plan = f.create_plan("引理：由在册定理推出结论", "PK-D-TO-B", subgoals=[
        {"sid": "s1", "text": "由在册定理推出目标引理", "owner": "F",
         "testable": "手稿的依赖段每条引用一行"}])
    out = f.step(str(plan["plan_id"]))
    assert out.get("action") == "proof", out
    assert out.get("proof_mode") == "registered", out
    assert pathlib.Path(store.root, str(out["manuscript_path"])).is_file(), out
    assert out.get("manuscript_washed") is True, out
    # 交稿只走手稿：F 这一侧不写 statements、也不写 dependencies
    # （盘上那一行是夹具预置的在册定理 `THEOREM_A`，不是 F 这一轮登记的）
    assert [str(r.get("stmt_id")) for r in store.rows("statements")] == [THEOREM_A]
    assert list(store.rows("dependencies")) == [], store.rows("dependencies")
    return out


def _d_with_b(store: Store) -> AgentD:
    """按真机装配的形状造 D：构造期拿到同一个 B 实例（`specs/d.py` 的 `peers["B"]`）。

    2026-11-08：B 收录时先查一圈"是不是在册的同一条"（关键词 -> 台账检索 -> 秘书认定）。
    这一份夹具没有模型 ⇒ 给 B 一个"挑得出词、查到过、不是同一条"的离线替身，
    让判据照跑而不是把闸摘掉。
    """
    from agentflow import secretary as _SEC

    b = AgentB(store, extractor=None, extract_text=None, config={},
               secretary=_SEC.Secretary("B", root=store.root, store=store,
                                        seam=SameSearchSeam(), enable_model=True))
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
    # 2026-11-07（解耦 + 裁边）：F 那一侧只落手稿登记条目（不写 statements / dependencies）
    # ⇒ 这一笔 D 携带是唯一可能把这条命题带进台账的动作（不是"边早就在"的真空绿）。
    d = _d_with_b(store)
    d.write_report()
    delivery = d.last_delivery
    assert delivery.get("checked") is True, delivery
    assert delivery.get("rows") == 1, delivery
    assert _a_holds(store, delivery), delivery
    rec = delivery["results"][0]
    assert rec["ok"] is True, rec
    f_stmt = str(rec["stmt_id"])
    assert f_stmt, rec
    assert rec["manuscript_source"] == SRC_CARRIED, rec
    assert rec["manuscript_washed"] is True, (
        "B 读到的不是秘书洗过的那一版（读数里没有 manuscript_washed）", rec)
    assert int(rec["deps_written"]) >= 1, rec

    rows = [dict(r) for r in store.rows("dependencies")]
    assert {str(r.get("used_by")) for r in rows} == {f"stmt:{f_stmt}"}, rows
    assert {int(r.get("path_group")) for r in rows} == {1}, rows
    # 新命题只落一行（B 发号一次；F 那一侧没有预登记）；盘上另一行是夹具预置的定理甲
    assert [str(r.get("stmt_id")) for r in store.rows("statements")] == [THEOREM_A, f_stmt]
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
    # 携带单上这一条还没有命题号 ⇒ 行键是稿号（`mss:<稿号>`），不是命题号
    assert [r["manuscript_id"] for r in calls[0]], calls[0]


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


class _SecCall:
    """`llmseam.SeamCall` 的替身：`Secretary.judge()` 只读 ok / problem / detail。"""

    ok = True
    problem = ""
    detail = ""


class _SecSeam:
    """V 的秘书那一档的离线替身缝（只答两件事：V 的回复没问题 / 这一签发）。

    2026-10-29 口径：签由 V 的秘书判、也由它落盘。没有这条缝时 `signed_bit3` 恒为假
    —— 那是装配缺失，不是这条端到端判据要量的东西。
    """

    wired = True

    def __init__(self) -> None:
        self.kinds: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict, _SecCall]:
        from agentflow import secretary as _SEC

        kind = note.split(":", 1)[-1]
        self.kinds.append(kind)
        if kind == "sign_issuance":
            doc = {"decision": _SEC.SIGN_ISSUE, "reason": "夹具：三次成立都干净 ⇒ 发签",
                   "basis": ["夹具"]}
        else:
            doc = {"decision": _SEC.V_REPLY_CLEAN, "reason": "夹具：照规则判 clean",
                   "basis": ["夹具"]}
        return dict(doc), _SecCall()


def _v_with_secretary(store: Store, llm) -> AgentV:
    """V 和它的秘书（2026-10-29：V 只落台账，翻位是秘书那一侧的事）。"""
    from agentflow import secretary as _SEC

    sec = _SEC.Secretary("V", root=pathlib.Path(store.root), store=store,
                         seam=_SecSeam(), enable_model=True)
    return AgentV(store, workspace_root=store.root, llm=llm, secretary=sec)


def _v_reviews_until_signed(agent: AgentV, sid: str, text: str,
                            manuscript: str = "") -> list[dict]:
    """同一份正文审到发签门槛（"连审到门槛"发生在同一次调用里）。

    两档都支持（2026-11-10，稿号口径）：

    - `sid` 非空（在册那一档）：逐转 `issued` 读数是「前几转只落台账、最后一转才签」；
    - `sid` 为空（F 的稿还没被 B 收录那一档）：三转成立 ⇒ `proof_unregistered_signed`，
      三票进 `verifications/pending/<正文 sha>.jsonl`、签块盖回稿；`issued` 不是这一支的
      读数（None），所以改判「三转都是成立」。

    两档共同的两条更硬读数一字未改：`signed_bit3` 恒 False（V 不再翻命题位）、
    `review_write.manuscript_signed` 为真（收方秘书把九格块落回稿）、
    且稿上那一块自己读出来是 `signed`（连 streak / need 一起对上门槛）。

    2026-11-04（业主裁定 甲）：在册命题送审必须带手稿 —— 签块 / `## 依赖` / 按号
    寻址三样只在文件上。`manuscript` 就是 F 那一轮已经落在盘上的那一份
    （`_run_f_proof` 的返回给出）。
    """
    need = int(VR.SIGN_STREAK_NEED)
    got = agent.verify_proof(sid, proof_text=text, proof_manuscript=manuscript)
    assert got.get("checked") is True, got
    passes = got.get("review_passes") or []
    assert len(passes) == need, (
        f"这一趟自己连判了 {len(passes)} 转（门槛 {need} 转）：{passes}")
    if str(sid or "").strip():
        assert [p.get("issued") for p in passes] == [False] * (need - 1) + [True], (
            f"逐转的发签读数是 {[p.get('issued') for p in passes]} —— 2026-10-29 口径："
            f"同一份正文连续 {need} 次「成立」且秘书判定通过才发签（前几转只落台账）")
    else:
        assert str(got.get("kind") or "") == "proof_unregistered_signed", got
        assert [p.get("verdict") for p in passes] == ["成立"] * need, passes
    # 2026-11-08（业主：「V 现在只对手稿负责」）：V 不再翻命题行的第 3 位
    # （`signed_bit3` 恒 False，命题位等 B 收录时按正文 sha 认领），签只落手稿。
    # 原句断的是"签真的发生了"；新契约下同一件事改由两处更硬的读数回答：
    # ① 收方秘书把九格块落回稿了没有（`review_write.manuscript_signed`）；
    # ② 稿上那一块自己读出来是不是 signed（连 streak / need 一起对上门槛）。
    # 只把 True 改成 False 是没断言的，所以这两处缺一不可。
    assert got.get("signed_bit3") is False, (
        f"V 不再翻命题位（业主 2026-11-08）；发签决定读数：{got.get('sign_issuance')}", got)
    assert dict(got.get("review_write") or {}).get("manuscript_signed") is True, (
        f"第三转应当把签落回手稿；写回读数：{got.get('review_write')}", got)
    block = VS.manuscript_sign_standing(
        pathlib.Path(agent.workspace_root, manuscript).read_text(encoding="utf-8"),
        proof_sha=VR.text_sha(DS.proof_body(
            pathlib.Path(agent.workspace_root, manuscript).read_text(encoding="utf-8")
        ).strip("\n")),
        manuscript_path=manuscript)
    assert block.get("state") == "signed", block
    assert (block.get("streak"), block.get("need")) == (need, need), block
    return [got]


def test_the_chain_f_proof_d_carry_b_edges_v_signs(tmp_path: pathlib.Path) -> None:
    """端到端：F 真推一轮 → V 在稿上签 → D 直接交 B → 依赖行 → B 按 sha 认领那一签。

    这一条是业主那句「D 到 B 没有路吗？加」的整条演示：四步全在真机代码路径上，
    没有一步靠模型记得去传。

    ## 次序为什么改成「F 写 → V 签 → D 携带 → B 收录」（2026-11-10 稿号口径）

    改前是「F 写 → D 携带 → B 收录 → V 按命题号在册签」。那条次序的前提是稿名 =
    命题号（V 的在册入口要求稿名里的号就是命题号）。2026-11-10 裁定之后 F 的稿只按
    F 自己的稿号命名，与命题号是两个号段 ⇒ V 必须在 B 现取命题号之前把签盖在稿上
    （这正是真机次序：V 签在前、B 收录在后），B 收录时按同一个正文 sha 认领那一签。
    断言没降：V 的三票仍真跑、签块仍落在这一份稿上、依赖边仍由 B 这一笔落、
    收录后第 3 位与 `reviewed_by` 仍要指回同一份正文。
    """
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A, label="定理甲")
    # 稿号与命题号是两个号段：F 的稿号从 manuscript 计数器发。先把计数器推过 3 个号，
    # 免得 F 的稿恰好落在 `f-proof-000000.md`（那正是下面被引命题 THEOREM_A 的稿名）——
    # 两份不同的稿不许共用一个名字。这是夹具环境的一格，不是判据。
    from agentflow import manuscriptids as _MID_CHAIN

    for _ in range(3):
        _MID_CHAIN.next_manuscript_id(store.root)
    proof = _run_f_proof(store)
    f_rel = str(proof.get("manuscript_path") or "")
    assert f_rel == f"reports/f-proof-{proof['manuscript_id']}.md", proof
    assert f_rel != f"reports/f-proof-{THEOREM_A}.md", (
        "夹具撞名：F 的稿与被引命题的稿落在同一个名字上", f_rel)

    # 2026-11-08（业主：「V 现在只对手稿负责」）：可引资格读"被引命题那一份手稿上有
    # 没有 V 签" ⇒ 夹具必须给被引的那一条落一份带真签的稿。这是补前提（真机上每条
    # 在册命题的证明都住在一份稿里），不是放宽引用闸。放在 V 之前：引用闸此刻就要读它。
    _cited_manuscript_with_a_real_sign(store, THEOREM_A, label="定理甲")

    # ---- ① V 在「还没被 B 收录」这一档读稿、三转、把签块盖回稿 --------------------
    f_text = pathlib.Path(store.root, f_rel).read_text(encoding="utf-8")
    f_body = DS.proof_body(f_text).strip("\n")
    reply = json.dumps({
        "verdict": "成立", "defect_step": None, "why": "", "findings": [],
        "citation_checks": [{"stmt_id": THEOREM_A, "verdict": "consistent",
                             "quote_verbatim": False,
                             "note": "由定理甲那一步，用法一致"}]}, ensure_ascii=False)
    v_llm = _VSeam(reply)
    v = _v_with_secretary(store, v_llm)
    # 2026-10-29 口径：同一份正文连续 3 次「成立」且秘书判定通过才落签。
    # 2026-11-08（V 只对手稿）：签块由收方秘书落回稿（`vsigns.land` 只认
    # `secretary:F/B/E`，`by` 从召唤上下文里的 `parent_role` 取）。真机上 V 总是被
    # 某一方派出来的，所以这一趟必须在同一个召唤上下文里跑。
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        reviewed = _v_reviews_until_signed(v, "", f_body, f_rel)
    signed = reviewed[-1]
    assert dict(signed.get("review_write") or {}).get("manuscript_signed") is True, signed
    assert signed.get("signed_bit3") is False, signed
    # 未在册那一支只读这一份稿（正文 + 机械依赖面审计），不做 LLM 逐条引用核实 ——
    # 引用核实那一格在「在册那一支」，本仓由 `test_dependency_wiring_is_live` 的整条链
    # 单独量着。这里如实量这一支的两个前提：V 的题面里有这份稿的正文与依赖面，
    # 且依赖面点名了被引的那一条（那正是 B 之后要落成 `dependencies` 的那张表）。
    _sec = DS.parse_dependency_section(f_text)
    assert _sec.get("present") is True and not _sec.get("refused"), _sec
    assert {str(r.get("stmt_id") or "") for r in (_sec.get("rows") or [])} == {THEOREM_A}, _sec
    assert str(f_body.splitlines()[0]) in v_llm.prompts[-1], v_llm.prompts[-1][-2500:]

    # ---- ② D 携带同一份稿交 B；B 按正文 sha 认领那一签、现取命题号、落依赖边 -------
    d = _d_with_b(store)
    d.write_report()
    assert _a_holds(store, d.last_delivery), d.last_delivery
    f_stmt = str(d.last_delivery["results"][0]["stmt_id"])
    assert f_stmt, d.last_delivery
    rows = [dict(r) for r in store.rows("dependencies")]
    assert rows, "依赖面一条都没有落"

    # ---- ③ 稿名与签：收录拿到命题号不改稿名；那一签被 B 认领 ---------------------
    # 2026-11-10（新口径）：收录拿到命题号不改稿名。F 的稿从写到收录始终是
    # `reports/f-proof-<稿号>.md`（稿号是 F 自己的号段），命题号只落在语句行上。
    assert pathlib.Path(store.root, f_rel).is_file(), (
        "F 那份按稿号命名的稿在 B 收录之后不在了",
        sorted(p.name for p in (pathlib.Path(store.root) / "reports").glob("f-proof*.md")))
    # 反向：稿名里不含命题号（按命题号命名的稿一份都不许出现 —— 那正是被停掉的旧口径）。
    assert not pathlib.Path(store.root, f"reports/f-proof-{f_stmt}.md").exists(), (
        "稿名里带上了命题号（旧口径的回潮）",
        sorted(p.name for p in (pathlib.Path(store.root) / "reports").glob("f-proof*.md")))
    assert not pathlib.Path(store.root, f"reports/f-proof-plan-{proof['plan_id']}.md").exists(), (
        "计划名那份稿还在 ⇒ 盘上会有另一份同一份稿",
        sorted(p.name for p in (pathlib.Path(store.root) / "reports").glob("f-proof*.md")))
    # 2026-11-07（唯一交稿链）：放行 B 那一笔的是 pending 台账里的「先签后登记」
    # （按正文 sha 认领）⇒ B 收录时把认领的那几行落进这一条的在册台账。
    # 2026-11-10（稿号口径）：V 的三票是在「还没被收录」时按正文 sha 落的 —— 与旧链
    # 同一本 pending 账，只是事件次序变成「先签、后收录」。台账里因此应有 V 的三转
    # （每转一行，带 V 那一转的引用核实读数）+ 1 行本文件的「V 已签」前提签
    # （`signed_v_handoffs`：只写 pending，不带引用核实）。精确到行数，不许写成
    # "至少几行" —— 旧链那 3 行与"3+1"在读数上是两件事。
    ledger, problems = VR.list_verifications(store.root, statement_id=f_stmt, limit=None)
    assert problems == [], problems
    _signed_block = VS.manuscript_sign_reading(
        pathlib.Path(store.root, f_rel).read_text(encoding="utf-8"),
        manuscript_path=f_rel)
    _f_sha = str(_signed_block.get("proof_sha256") or "")
    assert _f_sha, _signed_block
    assert len(ledger) == int(VR.SIGN_STREAK_NEED) + 1, (
        "台账应有 V 的三转（每转一行）+ 夹具「V 已签」那一份前提签 1 行；"
        f"读到 {len(ledger)} 行：{[r.get('verification_id') for r in ledger]}")
    _v_rows = [r for r in ledger if r.get("citation_checks")]
    assert len(_v_rows) == int(VR.SIGN_STREAK_NEED), (
        "V 的那三转应各带一条引用核实读数",
        [(r.get("verification_id"), r.get("citation_checks")) for r in ledger])
    assert all(str(r.get("verdict")) == "成立" for r in _v_rows), _v_rows
    assert all(str(r.get("proof_sha256") or "") == _f_sha for r in ledger), (
        "台账里有人签的不是这一份正文", [(r.get("verification_id"),
                                        r.get("proof_sha256")) for r in ledger])
    assert {str(c.get("stmt_id")) for r in _v_rows
            for c in (r.get("citation_checks") or [])} == {THEOREM_A}, _v_rows
    pending, pending_problems = VR.pending_rows(store.root)
    assert pending_problems == [], pending_problems
    _mine = [r for r in pending
             if str(r.get("proof_sha256") or r.get("object_sha256") or "") == _f_sha]
    assert len(_mine) >= int(VR.SIGN_STREAK_NEED), (
        f"F 这一份正文的三票不齐：{[(r.get('verification_id'), r.get('proof_sha256')) for r in pending]}")
    # B 收录时按同一个 sha 认领那一签：第 3 位翻真、`reviewed_by` 指回同一份正文的 sha。
    # 这两格是「签随稿走」的结果读数 —— 与上面 pending 三票一起，构成"签没丢"。
    _row_chain = next(dict(r) for r in store.rows("statements")
                      if str(r.get("stmt_id")) == f_stmt)
    _bits_chain = dict(_row_chain.get("bits") or {})
    assert _bits_chain.get("reviewed") is True, _bits_chain
    assert str((dict(_bits_chain.get("evidence") or {}).get("reviewed_by") or {}
                ).get("proof_sha256") or "") == _f_sha, _bits_chain


def test_the_washed_flag_travels_with_the_file(tmp_path: pathlib.Path) -> None:
    """秘书洗过的那一版必须跟着文件走：B 读到的正文里带 `已洗=true` 那一行。"""
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A, label="定理甲")
    proof = _run_f_proof(store)
    text = pathlib.Path(store.root, str(proof["manuscript_path"])).read_text(encoding="utf-8")
    reading = DS.manuscript_wash_reading(text)
    assert reading["washed"] is True, (reading, text[:400])
    assert reading["actor"].startswith("secretary"), reading


#: 2026-11-02 准入闸默认 strict 之后，本文件的夹具一律先给"B 即将写进台账的那一份
#: 证明正文"补一签（真签：在册走台账、未在册走 pending）。见 conftest 的同名 fixture。
pytestmark = pytest.mark.usefixtures("signed_v_handoffs")




