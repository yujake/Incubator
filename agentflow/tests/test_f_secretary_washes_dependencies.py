# -*- coding: utf-8 -*-
"""F 的秘书在"提交给 V 之前"洗一遍依赖面（业主 2026-10-26 晚的裁定）。

业主原话（唯一权威，逐字）：
```
「F写证明时务必加依赖面命题号，且由F的秘书对无引用证明忘加空依赖面的补空，
  对有引用证明的命题号核实（即秘书帮它洗一遍）」
「F的秘书工作的时候是F写好了，提交证明给V前」
「秘书若核出问题，要提前打回并说明」
```

## 时点（这是本文件最重要的断言之一）

    F 写完证明 → 框架渲染手稿（含 `## 依赖` 节，空的也要有）
      → F 的秘书在这里动手（补空 / 逐条核命题号：洗或退回）
      → 洗好的那一份才提交给 V（才走 proof outlet / 才交登记）
      → D 携带 → B 读稿落依赖 → V 核引用签字

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a 补空 | 无引用而缺节 ⇒ 秘书补一个空节；最终登记读数 `not_applicable` | 改前没有这一步（缺节只能等 B 拒） |
| b1 能确定就洗 | 写错但在册、正文那一步只点名了一条 ⇒ 洗成它，留 `deps_washing` | 改前没人核过依赖表与正文 |
| b2 确定不了就退 | 那一步引了多条、对不上 ⇒ 打回而不是猜改 | 同上 |
| c 不存在的号 | 点名的号不在册 ⇒ 打回并逐条说明（哪一行 / 原话 / 写的号 / 该是什么 / 为什么 / 怎么改）；不提交给 V | 改前只有 B 侧事后拒收，F 已经交过一轮 |
| d 反真空 | 把"洗"打桩成恒通过 ⇒ b2/c 必红 | —— |
| 时点 | `wash` 必须在 `_proof_outlet` 之前被调用 | 改前洗稿这一步不存在 |
| ② 依赖节常在 | 手稿渲染永远带 `## 依赖`（没有引用也要有表头 + 一句"空表就是声明"） | —— |

零模型钱：F 用假缝、V 用替身；全部 tmp 工作区。
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_f import AgentF
from agentflow.store import Store

THEOREM_A = S.format_id(0)
THEOREM_B = S.format_id(1)
THEOREM_C = S.format_id(2)
MISSING = "999999"

_DEP_HEAD = ("| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
             "|---|---|---|---|\n")


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _add_statement(store: Store, stmt_id: str, *, label: str = "",
                   level: str = "proof_review") -> dict:
    row = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem",
        label=label or f"在册命题 {stmt_id}",
        statement_text=f"命题 {stmt_id} 的短版",
        statement_full=f"命题 {stmt_id} 的完整正文（含假设）。",
        proof_text=f"命题 {stmt_id} 的证明正文（判据夹具）。",
        evidence_kind="heuristic", status="active", quote_verified=None,
        quote_reason="判据夹具：自产命题", created_at=S.now_iso(), created_by="agent-B")
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


def _secretary(store: Store):
    return SEC.for_role("F", root=store.root, store=store)


def _manuscript(*, step_line: str, dep_rows: str, section: bool = True) -> str:
    text = ("# F 的证明手稿：判据夹具\n\n"
            "- 命题号：stmt:（还没落号）\n"
            "- 计划：000000 · 子目标：s1\n\n"
            "## 命题\n\n由定理推出目标结论。\n\n"
            "## 证明\n\n" + step_line + "\n")
    if section:
        text += "\n## 依赖\n\n" + _DEP_HEAD + dep_rows
    return text


class FakeSeam:
    """F 的假缝（`judge_json` 认 `complete(prompt) -> str`）。"""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.payload, ensure_ascii=False)


def _no_cite_payload() -> dict:
    return {"product": "proof", "strategy": "套用已知定理",
            "why_strategy": "把结论写成两条前提",
            "steps": [{"n": 1, "text": "设 n 是正整数（前提）。", "cites": [],
                       "assumption": True},
                      {"n": 2, "text": "由前提得 n 的阶乘为正（前提）。", "cites": [],
                       "assumption": True}]}


def _f(store: Store, payload: dict | None = None) -> AgentF:
    return AgentF(store, config={"workspace_root": store.root},
                  llm=FakeSeam(payload or _no_cite_payload()))


def _plan(f: AgentF, *, key: str = "PK-WASH") -> str:
    got = f.create_plan("引理：判据夹具", key, subgoals=[
        {"sid": "s1", "text": "由在册定理推出目标引理", "owner": "F",
         "testable": "手稿的依赖段每条引用一行"}])
    assert got.get("created") is True, got
    return str(got["plan_id"])


def _b(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=None, config={})


# ------------------------------------------------------------------ ② 依赖节常在


def test_the_rendered_manuscript_always_has_the_dependency_section(
        tmp_path: pathlib.Path) -> None:
    """② F 的证明手稿里 `## 依赖` 那一节必须存在：没有引用也要有表头和一句声明。

    这一条是"空依赖面由代码生成"的守卫：渲染器不给空节，秘书的"补空"就永远在
    补一个本该有的东西（而真机里那会退化成 B 的 `dependency_section_missing`）。
    """
    store = _ws(tmp_path)
    f = _f(store)
    product = {"product": "proof", "strategy": "套用已知定理", "why_strategy": "两条前提",
               "steps": [{"n": 1, "text": "设 n 是正整数（前提）。", "cites": [],
                          "assumption": True}]}
    got = f.proof_manuscript(product, sg={"sid": "s1", "text": "目标"},
                             plan={"plan_id": "000000"})
    text = str(got.get("text") or "")
    assert DS.SECTION_HEADING in text, text
    section = DS.parse_dependency_section(text)
    assert section["present"] is True and section["rows"] == [], section
    assert section["refused"] == "", section
    assert "空表就是声明" in text, text
    assert (got.get("preview") or {}).get("deps_missing", {}).get("state") == "not_applicable", (
        got.get("preview"))


# ------------------------------------------------------------------ a 补空


def test_a_manuscript_without_citations_and_without_the_section_gets_an_empty_one(
        tmp_path: pathlib.Path) -> None:
    """a 无引用而忘了那一节 ⇒ 秘书补一个空节；最终登记是 `not_applicable`。

    改前红：没有这一遍洗稿（"缺节"这件事只有 B 那一侧才第一次发现，而 B 对
    "没有引用"这一档并不拒收 —— 于是"忘了写"与"确实自足"在盘上长得一样）。
    """
    store = _ws(tmp_path)
    raw = _manuscript(step_line="1. 由定义直接得到，本证明不引用任何在册命题。",
                      dep_rows="", section=False)
    got = _secretary(store).wash_dependency_face(raw)
    assert got["checked"] is True, got
    assert got["deps_refused"] == "", got
    assert got["washed"] is True, got
    assert got["deps_section_filled"] == DS.WASH_FILLED_EMPTY, got
    assert DS.SECTION_HEADING in got["text"], got["text"]
    assert "空表就是声明" in got["text"], got["text"]

    # 幂等：同一份洗过的稿再洗一遍不再"洗"（F 重写再交时不许累加旧记录）
    again = _secretary(store).wash_dependency_face(got["text"])
    assert again["checked"] is True and again["washed"] is False, again
    assert again["deps_section_filled"] == "", again

    # 补过空节之后，B 那一笔登记读数是 `not_applicable`（不再"缺节"）
    reg = _b(store).register_statement(
        statement_full="定理：自足的证明（洗稿夹具）。",
        statement_text="自足的证明", proof_text="1. 由定义直接得到。",
        origin="own_result", kind="conjecture", doc_id=S.format_id(0),
        quote_reason="我方自产命题（判据夹具）", proof_manuscript=got["text"])
    assert reg.get("ok") is True, reg
    reading = reg.get("deps_missing") or {}
    assert reading.get("state") == "not_applicable", reading
    assert (reading.get("manuscript") or {}).get("present") is True, reading
    assert reg.get("manuscript_washed") is False, (
        "这一份没有盖洗稿元信息（那不是 F 提交路径上的稿）", reg)


# ------------------------------------------------------------------ b 逐条核命题号


def test_a_wrong_but_registered_id_is_washed_when_the_step_names_only_one(
        tmp_path: pathlib.Path) -> None:
    """b1 能确定 ⇒ 直接洗（并留 `deps_washing`）：正文那一步只点名了甲，表里写的是乙。"""
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A, label="定理甲")
    _add_statement(store, THEOREM_B, label="定理乙")
    raw = _manuscript(step_line=f"1. 由定理甲得到第一步（依据：stmt:{THEOREM_A}）。",
                      dep_rows=f"| 由定理甲 | stmt:{THEOREM_B} | 第 1 步 | 1 |\n")
    got = _secretary(store).wash_dependency_face(raw)
    assert got["checked"] is True and got["deps_refused"] == "", got
    assert got["washed"] is True, got
    assert len(got["deps_washing"]) == 1, got["deps_washing"]
    wash = got["deps_washing"][0]
    assert wash["from"] == THEOREM_B and wash["to"] == THEOREM_A, wash
    assert int(wash["line"]) > 0 and str(wash["why"]).strip(), wash
    section = DS.parse_dependency_section(got["text"])
    assert [r["stmt_id"] for r in section["rows"]] == [THEOREM_A], section["rows"]


def test_an_ambiguous_mismatch_is_sent_back_instead_of_guessed(
        tmp_path: pathlib.Path) -> None:
    """b2 确定不了 ⇒ 打回（不猜）：那一步引了甲和乙两条，表里写的却是丙。"""
    store = _ws(tmp_path)
    for sid in (THEOREM_A, THEOREM_B, THEOREM_C):
        _add_statement(store, sid)
    raw = _manuscript(
        step_line=(f"1. 由定理甲与定理乙得到第一步（依据：stmt:{THEOREM_A}、"
                   f"stmt:{THEOREM_B}）。"),
        dep_rows=f"| 由它们 | stmt:{THEOREM_C} | 第 1 步 | 1 |\n")
    got = _secretary(store).wash_dependency_face(raw)
    assert got["washed"] is False, got
    assert got["text"] == raw, "退回时不许改稿（这一份原样退回 F 重写）"
    assert got["deps_refused"] == DS.WASH_REFUSED_ROW, got
    findings = got["deps_refused_findings"]
    assert findings, got
    assert findings[0]["got"] == f"stmt:{THEOREM_C}", findings[0]
    assert "无法唯一确定" in findings[0]["expected"], findings[0]


def test_a_missing_id_is_sent_back_with_actionable_findings(
        tmp_path: pathlib.Path) -> None:
    """c 点名的号不在册 ⇒ 退回 F，逐条说清（哪一行 / 原话 / 写的号 / 该是什么 / 为什么 / 怎么改）。"""
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A)
    raw = _manuscript(step_line=f"1. 由那条命题得到第一步（依据：stmt:{MISSING}）。",
                      dep_rows=f"| 由它，结论成立 | stmt:{MISSING} | 第 1 步 | 1 |\n")
    got = _secretary(store).wash_dependency_face(raw)
    assert got["checked"] is True, got
    assert got["deps_refused"] == DS.WASH_REFUSED_ROW, got
    findings = got["deps_refused_findings"]
    assert len(findings) == 1, findings
    f = findings[0]
    for key in ("line", "quote", "got", "expected", "why", "how_to_fix"):
        assert key in f, (key, f)
    assert int(f["line"]) > 0, f
    assert "由它，结论成立" in f["quote"], f
    assert f["got"] == f"stmt:{MISSING}", f
    assert "不在册" in f["why"], f
    assert "改成台账里真实的一条在册命题号" in f["how_to_fix"], f
    # 这一份没有提交给任何地方：正文原样退回
    assert got["text"] == raw, got["text"][:200]


def test_a_below_proof_review_source_is_caught_here_not_at_b(
        tmp_path: pathlib.Path) -> None:
    """b 的第三档：引用写在册但档位不够 `proof_review` ⇒ 在秘书这一步就打回。

    改前红：这一档只有 B 的入库闸会拒 —— 而那时 F 已经把"提交给 V 的那一份"交出去了。
    """
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A, level="cross_check")
    raw = _manuscript(step_line=f"1. 由定理甲得到第一步（依据：stmt:{THEOREM_A}）。",
                      dep_rows=f"| 由定理甲 | stmt:{THEOREM_A} | 第 1 步 | 1 |\n")
    got = _secretary(store).wash_dependency_face(raw)
    assert got["deps_refused"] == DS.WASH_REFUSED_ROW, got
    f = got["deps_refused_findings"][0]
    assert "cross_check" in f["got"], f
    assert DS.CITATION_MIN_LEVEL in f["expected"], f
    assert "V" in f["how_to_fix"], f


# ------------------------------------------------------------------ 时点 + F 侧接线


def _bad_manuscript(*, statement_id_hint: str = "（还没落号）") -> str:
    return ("# F 的证明手稿：判据夹具\n\n"
            f"- 命题号：stmt:{statement_id_hint}\n"
            "- 计划：000000 · 子目标：s1\n\n"
            "## 命题\n\n由定理推出目标结论。\n\n"
            "## 证明\n\n"
            f"1. 由那条不存在的命题得到第一步（依据：stmt:{MISSING}）。\n\n"
            "## 依赖\n\n" + _DEP_HEAD +
            f"| 由它，结论成立 | stmt:{MISSING} | 第 1 步 | 1 |\n")


def test_the_wash_happens_before_the_outlet_and_marks_the_manuscript(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """时点：`wash` 必须在 `_proof_outlet`（提交给 V / 登记）之前被调用。

    改前红：洗稿这一步根本不存在（两处观察者里只有 outlet 会被叫到）。
    顺带钉"洗过的那一份才是交出去的那一份"：盘上那份稿带 `已洗=true` 元信息，
    `_proof_outlet` 收到的是同一份正文。
    """
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A)
    order: list[str] = []
    received: dict[str, str] = {}

    real_wash = SEC.Secretary.wash_dependency_face
    real_outlet = AgentF._proof_outlet

    def wash_spy(self, manuscript, **kw):
        order.append("wash")
        return real_wash(self, manuscript, **kw)

    def outlet_spy(self, product, sg, *, plan, proof_manuscript=""):
        order.append("outlet")
        received["text"] = str(proof_manuscript or "")
        return real_outlet(self, product, sg, plan=plan,
                           proof_manuscript=proof_manuscript)

    monkeypatch.setattr(SEC.Secretary, "wash_dependency_face", wash_spy)
    monkeypatch.setattr(AgentF, "_proof_outlet", outlet_spy)
    f = _f(store)
    out = f.step(_plan(f))

    assert order == ["wash", "outlet"], f"洗稿与登记的真实次序是 {order}"
    assert out.get("action") == "proof", out
    assert out.get("manuscript_washed") is True, out
    on_disk = pathlib.Path(store.root, str(out["manuscript_path"])).read_text(encoding="utf-8")
    assert DS.manuscript_wash_reading(on_disk)["washed"] is True, on_disk
    assert received["text"].strip(), "登记那一笔没有收到稿"
    assert "已洗=true" in received["text"], received["text"][:400]
    assert DS.SECTION_HEADING in received["text"], received["text"][:400]


def test_a_refused_wash_stops_the_round_before_v_and_reaches_the_next_prompt(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c（F 侧）：核出问题 ⇒ 这一轮不提交给 V；逐条说明进返回值、history 与下一轮材料。"""
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A)
    before_statements = len(store.rows("statements"))
    outlets: list[str] = []
    real_outlet = AgentF._proof_outlet

    def outlet_spy(self, product, sg, *, plan, proof_manuscript=""):
        outlets.append(str(proof_manuscript or ""))
        return real_outlet(self, product, sg, plan=plan,
                           proof_manuscript=proof_manuscript)

    def bad_manuscript(self, product, *, sg, statement_id="", plan):
        return {"ok": True, "path": "reports/f-proof-plan-000000.md",
                "text": _bad_manuscript(), "rows": [], "preview": {},
                "named_by": "plan", "why": ""}

    monkeypatch.setattr(AgentF, "_proof_outlet", outlet_spy)
    monkeypatch.setattr(AgentF, "proof_manuscript", bad_manuscript)
    f = _f(store)
    pid = _plan(f)
    out = f.step(pid)

    assert outlets == [], "打回的那一份竟然还是被提交给 V 了（_proof_outlet 被调用）"
    assert len(store.rows("statements")) == before_statements, "打回却写了命题行"
    assert out.get("action") == "no_change", out
    assert out.get("deps_refused") == DS.WASH_REFUSED_ROW, out
    findings = out.get("deps_refused_findings") or []
    assert findings and findings[0]["got"] == f"stmt:{MISSING}", out
    assert "打回重写" in str(out.get("reason") or ""), out
    assert "怎么改" in str(out.get("reason") or ""), out
    assert out.get("manuscript_washed") is False, out

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert rec.get("deps_refused") == DS.WASH_REFUSED_ROW, rec
    assert rec.get("deps_refused_findings"), rec

    # 打回的文案要给 F 看：下一轮的提示词里必须有那句"怎么改"
    monkeypatch.undo()
    f2 = _f(store)
    seam = f2.llm
    f2.step(pid)
    prompt = seam.prompts[0]
    assert "秘书打回" in prompt, prompt[-2000:]
    assert "怎么改" in prompt, prompt[-2000:]


def test_stubbing_the_wash_out_turns_b_and_c_red(tmp_path: pathlib.Path,
                                                 monkeypatch) -> None:
    """d 反真空：把"洗"打桩成恒通过 ⇒ b2/c 必红（错号被原样提交出去）。

    打桩点就是 F 调的秘书那一笔（`Secretary.wash_dependency_face`）：返回"核过了、
    什么都没改"，于是那一份带不存在号的稿会一路走到 `_proof_outlet`（提交给 V）。
    正控（不打桩）下它是停住的 —— 上面 c 那一条钉的就是那一半。
    """
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A)
    outlets: list[str] = []
    real_outlet = AgentF._proof_outlet

    def outlet_spy(self, product, sg, *, plan, proof_manuscript=""):
        outlets.append(str(proof_manuscript or ""))
        return real_outlet(self, product, sg, plan=plan,
                           proof_manuscript=proof_manuscript)

    def bad_manuscript(self, product, *, sg, statement_id="", plan):
        text = _bad_manuscript()
        return {"ok": True, "path": "reports/f-proof-plan-000000.md", "text": text,
                "rows": [], "preview": {}, "named_by": "plan", "why": ""}

    monkeypatch.setattr(AgentF, "_proof_outlet", outlet_spy)
    monkeypatch.setattr(AgentF, "proof_manuscript", bad_manuscript)
    monkeypatch.setattr(SEC.Secretary, "wash_dependency_face",
                        lambda self, manuscript, **kw: {
                            "checked": True, "washed": False, "text": str(manuscript),
                            "deps_section_filled": "", "deps_washing": [],
                            "deps_refused": "", "deps_refused_findings": [],
                            "reason": "", "actor": f"secretary-{self.role}",
                            "rows": [], "section": {}})
    f = _f(store)
    out = f.step(_plan(f))
    assert outlets, "把洗稿打桩成恒通过之后，错号那份稿竟然还是没被提交（判据没在看这件事）"
    assert "stmt:999999" in outlets[0], outlets[0]
    assert out.get("deps_refused") in ("", None), out

