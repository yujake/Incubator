# -*- coding: utf-8 -*-
"""依赖面这条链在真机上是死路：三处接线判据（业主 2026-10-26）。

业主原话（唯一权威，按时间序）：
```
「仔细查接线，F，V关于依赖与引用的东西没能跑通」
「依赖面登记是否是F在其手稿中写好，D的研究手稿引用F的证明手稿给B入库时，
  B侧读到F手稿处的依赖面，按此入库的？（即和V签一个逻辑）」
「是通过D传吗」
```

## 传递路径（业主最后定下来的那一条）

    F 先写手稿（登记之前就要在手上）→ F 的 outlet 登记那条命题（手稿改名为
    reports/f-proof-<命题号>.md）→ D 交研究手稿给 B 入库时把 F 那份稿一并带上
    （D 的报告里「## 携带的证明手稿」那张三列表：命题号 / 路径 / sha256）→
    B 读那份稿、按 `## 依赖` 四列表落 dependencies → V 读同一份依赖面核引用并签字。

## 两条死结（改前的形态）

死结 1：手稿写的时机比登记晚。`agent_f/core.py` 的 proof 档先 `_proof_outlet(...)`
（登记，拿到 `statement_id`）、之后才 `proof_manuscript(..., statement_id=...)` ——
稿按"已登记的命题号"命名，而那次登记时根本没有稿可读，D 手上也就没有稿可带。

死结 2：没有任何人把手稿正文传给 B。真机佐证（sylow5/sylow6）：`reports/f-proof-*.md`
0 份、会话里 `## 依赖` 0 次、`dependencies` 全表 0 行。

## 判据与各自的"改前红"

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a0 时序 | F 的 proof 档里，手稿在登记之前就在盘上，且登记那一笔收到的 `proof_manuscript` 与盘上那一份逐字相同 | 改前 `_proof_outlet` 没有 `proof_manuscript` 形参，写稿还在它之后 |
| a D 携带 | D 交研究手稿给 B 时带上 F 的稿 ⇒ B 落依赖、`manuscript_source=carried_by_D` | 改前 D 没有任何携带动作（报告里没有那一节），B 也没有读它的一行 |
| b 兜底读盘 | D 没带、盘上有稿 ⇒ `disk`（老调用不瘫） | 改前 0 行：没有任何一处按约定路径找稿 |
| c 两处都没有 | 有在册引用而没有稿 ⇒ 整笔拒收 `dependency_section_missing`，零写入 | 改前照常入库（依赖靠正文扫描）⇒ 负控红 |
| d 反真空 | 把写稿时机退回"登记之后" ⇒ a 必红；把携带/兜底打桩成空 ⇒ b 必红 | 打桩下 a/b 的断言正好取反 |
| e 端到端 | F 写稿 → D 携带 → B 落依赖 → V 核引用签字：盘上 `dependencies` 与 `verifications` 两行都对得上 | 改前这条链一处都不通 |

全部 tmp 工作区、零模型调用（F 那一轮用一个假缝，`complete()` 回一份 `proof` 产物；
V 那一笔用一个按剧本回答的替身），不读写 `projects/`（真机工作区只读）。
"""
from __future__ import annotations

import json
import pathlib
import sys

# 与 `tests/conftest.py` 同一个注入方式：这一份也要能在一棵临时源码树上单独跑。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_d import AgentD
from agentflow.agent_f import AgentF
from agentflow.agent_v import AgentV
from agentflow.store import Store

#: 契约字面量（业主 2026-10-26 定的那几个读数取值）。实现侧与它们对齐由
#: `test_the_contract_values_are_the_ones_in_the_code` 一处钉住 —— 其余判据用字面量，
#: 于是"改前红"红的是行为，而不是"模块里还没有那个常量"。
SRC_PARAM = "param"
SRC_CARRIED = "carried_by_D"
SRC_DISK = "disk"
SRC_NONE = "none"
CARRIED_HEADING = "## 携带的证明手稿"
MANUSCRIPT_DIR = "reports"

#: 被引用的两条在册定理（B 已收录、已站到 proof_review 级）。
THEOREM_A = S.format_id(0)
THEOREM_B = S.format_id(1)

_PROOF_TEXT = "命题 {sid} 的证明正文（判据夹具）。"
#: 依赖段的正例（与政策里那一张表同形）。
_DEP_TABLE = (
    "## 依赖\n\n"
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
    "|---|---|---|---|\n"
    "| {quote} | stmt:{sid} | 第 1 步 | 1 |\n"
)
#: 一条在册引用的最小手稿（B 的兜底读盘要能读的正是它）。
#: 证明正文里也点名那条引用（真机 F 的手稿正是这样：`（依据：stmt:…）`）：
#: 三态读数按"证明正文里引了几条"定，正文里一条都不写会被读成 `not_applicable`。
_MANUSCRIPT_FOR_A = (
    "## 证明\n\n1. 由定理甲直接得到（依据：stmt:%s）。\n\n" % THEOREM_A
    + _DEP_TABLE.format(quote="由定理甲，G 有 p 阶元", sid=THEOREM_A))
#: 另一份（只引定理乙）：用于证明"参数给了稿就不去读盘"。
_MANUSCRIPT_FOR_B = (
    "## 证明\n\n1. 由定理乙直接得到（依据：stmt:%s）。\n\n" % THEOREM_B
    + _DEP_TABLE.format(quote="由定理乙，阶数被 p 整除", sid=THEOREM_B))


# ------------------------------------------------------------------ 夹具

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _add_statement(store: Store, stmt_id: str, *, label: str = "") -> dict:
    row = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem",
        label=label or f"在册命题 {stmt_id}",
        statement_text=f"命题 {stmt_id} 的短版",
        statement_full=f"命题 {stmt_id} 的完整正文（含假设）。",
        proof_text=_PROOF_TEXT.format(sid=stmt_id),
        evidence_kind="heuristic", status="active",
        quote_verified=None,
        quote_reason="判据夹具：自产命题，没有外部引文要比对",
        created_at=S.now_iso(), created_by="agent-B",
    )
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    return row.to_dict()


def _library(store: Store) -> None:
    """两条够格（proof_review）的在册命题：引用门槛正好卡在它们身上。"""
    for sid, label in ((THEOREM_A, "定理甲"), (THEOREM_B, "定理乙")):
        _add_statement(store, sid, label=label)
        signed = VR.record_verification(
            store.root, statement_id=sid, proof_text=_PROOF_TEXT.format(sid=sid),
            verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
            store=store, proof_no=1)
        assert signed.get("checked") is True, signed
        row = next(dict(r) for r in store.rows("statements")
                   if str(r.get("stmt_id")) == sid)
        row["evidence_kind"] = "proof_review"
        with store.tx("statements", actor="test") as tx:
            tx.upsert("statements", row)


class FakeSeam:
    """假模型缝（`judge.judge_json` 认 `complete(prompt) -> str` 这一种形状）。"""

    def __init__(self, product: dict) -> None:
        self.product = product
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.product, ensure_ascii=False)


def _proof_product(*, cites: list[str]) -> dict:
    steps = [
        {"n": 1, "text": "由在册定理直接得到第一步。", "cites": cites, "assumption": False},
        {"n": 2, "text": "由第 1 步得结论。", "cites": cites[:1], "assumption": False},
    ]
    return {"product": "proof", "strategy": "套用已知定理",
            "why_strategy": "两条已收录定理直接给出结论，不需要新的构造", "steps": steps}


def _f_with_seam(store: Store, product: dict) -> tuple[AgentF, FakeSeam]:
    seam = FakeSeam(product)
    return AgentF(store, config={"workspace_root": store.root}, llm=seam), seam


def _new_plan(f: AgentF) -> str:
    plan = f.create_plan(
        "引理：由在册定理推出结论", "PK-WIRING", subgoals=[
            {"sid": "s1", "text": "由在册定理推出目标引理", "owner": "F",
             # 可检验形式非空：这是 `attackround.pre_spend_gate` 允许花钱的前提，
             # 也是真机 sylow6 那一轮缺的那一格（模型写的是 `check`，改前被丢掉了）。
             "testable": "手稿的依赖段每条引用一行，B 读稿后落成依赖边"}])
    assert plan.get("created") is True, plan
    return str(plan["plan_id"])


def _run_proof_round(store: Store, cites: list[str]) -> dict:
    f, _seam = _f_with_seam(store, _proof_product(cites=cites))
    out = f.step(_new_plan(f))
    assert out.get("action") == "proof", out
    assert str(out.get("statement_id") or ""), out
    return out


def _b(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=None, config={})


def _register(store: Store, *, statement_full: str, proof_text: str,
              derived_from: list[str] | None = None,
              proof_manuscript: str = "") -> dict:
    return _b(store).register_statement(
        statement_full=statement_full,
        statement_text=statement_full[:20],
        origin="own_result", kind="conjecture", doc_id=S.format_id(0),
        quote_reason="我方自产命题（判据夹具）：没有外部引文要比对",
        proof_text=proof_text, derived_from=list(derived_from or []),
        proof_manuscript=proof_manuscript,
    )


def _d_report(store: Store) -> str:
    """D 交研究手稿（`write_report` 渲染出来的那一份）⇒ 返回全文。

    这一份就是 B 入库时读的"研究手稿"：携带单写在里面（业主：「是通过D传吗」）。
    """
    out = AgentD(store).write_report()
    return pathlib.Path(out).read_text(encoding="utf-8")


def _deps(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("dependencies")]


def _reports(store: Store) -> list[str]:
    d = pathlib.Path(store.root) / MANUSCRIPT_DIR
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.glob("f-proof-*.md"))


class _RegistrationSpy:
    """`_proof_outlet` 的观察者：记录"登记那一刻"盘上有哪些稿、登记收到的是哪份正文。

    这一层就是判据 a0 的判据本身：它不改行为（原实现照跑），只在调用前拍一张快照。
    快照里那两份东西必须是同一份正文 —— "登记收到 `proof_manuscript`"与"稿已经在盘上"
    要能对得上，否则"手上有一份稿"仍然只是一句自述。

    注意它的 `__call__` 故意不带 `self` 参数位：把它 `monkeypatch.setattr` 到类属性上之后，
    普通对象不是描述符 ⇒ 取出来的就是它本人，调用时不会有人替它补 `self`。
    所以 F 那一侧的引用在 :meth:`bind` 里存下来。
    """

    def __init__(self) -> None:
        self.real = AgentF._proof_outlet
        self.agent = None
        self.calls: list[dict] = []

    def bind(self, agent) -> "_RegistrationSpy":
        self.agent = agent
        return self

    def __call__(self, product, sg, *, plan, proof_manuscript=""):
        agent = self.agent
        root = pathlib.Path(agent.cfg.get("workspace_root") or agent.store.root)
        reports_dir = root / MANUSCRIPT_DIR
        files = sorted(p.name for p in reports_dir.glob("f-proof-*.md")) if (
            reports_dir.is_dir()) else []
        texts = {name: (reports_dir / name).read_text(encoding="utf-8") for name in files}
        self.calls.append({"received": str(proof_manuscript or ""), "files": files,
                           "texts": texts})
        return self.real(agent, product, sg, plan=plan, proof_manuscript=proof_manuscript)


def _a0_holds(store: Store, out: dict, spy: _RegistrationSpy) -> bool:
    """判据 a0（判据本体，正控与反真空共用同一个谓词）。

    三件事同时成立才算绿：
    1. 登记那一笔真的收到了一份非空的手稿正文，且它里面有 `## 依赖` 那一节；
    2. 登记那一刻盘上已经有一份 `f-proof-*.md`，内容与收到的那份逐字相同；
    3. 那一轮结束时手稿在按命题号的名字下（`reports/f-proof-<命题号>.md`），内容不变。
    """
    if len(spy.calls) != 1:
        return False
    call = spy.calls[0]
    received = str(call["received"] or "")
    if not received.strip() or DS.SECTION_HEADING not in received:
        return False
    if not any(text == received for text in call["texts"].values()):
        return False
    sid = str(out.get("statement_id") or "")
    rel = str(out.get("manuscript_path") or "")
    if not sid or rel != f"{MANUSCRIPT_DIR}/f-proof-{sid}.md":
        return False
    path = pathlib.Path(store.root) / rel
    return path.is_file() and path.read_text(encoding="utf-8") == received


def _carried_holds(got: dict, store: Store, *, cited: str) -> bool:
    """判据 a（D 携带）的判据本体：D 带来的那份稿真被读、依赖真落成。

    三件事一起判：`manuscript_source=carried_by_D`、落了至少一条依赖、落的那条来源
    正是这份稿点名的那一条。任何一条不成立都算红（反真空直接拿它判）。
    """
    rows = _deps(store)
    return (str(got.get("manuscript_source") or "") == SRC_CARRIED
            and str((got.get("deps_missing") or {}).get("state") or "") == "present"
            and bool(rows) and {str(r.get("source_stmt_id")) for r in rows} == {cited})


# ------------------------------------------------------- 契约取值与实现对齐

def test_the_contract_values_are_the_ones_in_the_code() -> None:
    """契约取值只有一处：这一份判据里的字面量与 `depsection` 里的常量必须逐字相等。

    为什么单独一条：其余判据刻意用字面量（于是"改前红"红的是行为，而不是 AttributeError）。
    漂了的话没人会发现 —— 读数会变成两个词，而两边各自自洽。
    """
    assert (DS.SOURCE_PARAM, DS.SOURCE_CARRIED, DS.SOURCE_DISK, DS.SOURCE_NONE) == (
        SRC_PARAM, SRC_CARRIED, SRC_DISK, SRC_NONE)
    assert DS.MANUSCRIPT_DIR == MANUSCRIPT_DIR, DS.MANUSCRIPT_DIR
    assert DS.CARRIED_HEADING == CARRIED_HEADING, DS.CARRIED_HEADING
    assert DS.MANUSCRIPT_STMT_PREFIX == "f-proof-", DS.MANUSCRIPT_STMT_PREFIX
    assert DS.MANUSCRIPT_PLAN_PREFIX == "f-proof-plan-", DS.MANUSCRIPT_PLAN_PREFIX


# ------------------------------------------------------------------ a0 时序

def test_the_manuscript_is_on_disk_before_the_registration(store: Store, monkeypatch) -> None:
    """a0 F 的 proof 档：手稿在登记之前就在盘上，登记那一笔收到的就是它。

    改前红（逐条）：`AgentF._proof_outlet` 的形参里没有 `proof_manuscript` ⇒ 观察者拿到
    的是空串（第一条断言当场红）；而且改前写稿在 `_proof_outlet` 之后 ⇒ 登记那一刻
    `reports/` 下一份 `f-proof-*.md` 都没有（第二条断言也红）。
    """
    _library(store)
    spy = _RegistrationSpy()
    monkeypatch.setattr(AgentF, "_proof_outlet", spy)
    f, _seam = _f_with_seam(store, _proof_product(cites=[f"stmt:{THEOREM_A}",
                                                         f"stmt:{THEOREM_B}"]))
    spy.bind(f)
    out = f.step(_new_plan(f))

    assert out.get("action") == "proof", out
    assert len(spy.calls) == 1, spy.calls
    call = spy.calls[0]
    assert str(call["received"]).strip(), (
        "登记那一笔没有收到 `proof_manuscript`（改前的形态：登记时手上没有稿）")
    assert DS.SECTION_HEADING in call["received"], call["received"]
    assert call["files"], (
        "登记那一刻 `reports/` 下一份 f-proof-*.md 都没有（改前正是这样：写稿在登记之后）")
    assert [n for n, t in call["texts"].items() if t == call["received"]], (
        "登记收到的正文与盘上那一份不同 ⇒ 登记那一刻手上的稿不在盘上",
        call["files"])
    assert _a0_holds(store, out, spy), out
    # 登记那一刻的稿是按计划号命名的（此刻还没有命题号），登记之后改成按命号的名字
    assert call["files"] == [f"f-proof-plan-{out['plan_id']}.md"], call["files"]
    assert str(out.get("manuscript_path")) == (
        f"{MANUSCRIPT_DIR}/f-proof-{out['statement_id']}.md"), out
    assert str(out.get("manuscript_source")) == SRC_PARAM, out
    # 登记之后那个按计划号的名字不再留在盘上（改名，不是复制一份）。
    assert _reports(store) == [f"f-proof-{out['statement_id']}.md"], _reports(store)


# ------------------------------------------------------------------ a D 携带

def test_d_carries_the_f_manuscript_and_b_reads_it(tmp_path: pathlib.Path) -> None:
    """a D 交研究手稿给 B 时带上 F 的稿 ⇒ B 读那份稿落依赖、来源读 `carried_by_D`。

    改前红：D 没有任何携带动作（`write_report` 里没有那一节），B 也没有读它的一行 ⇒
    `manuscript_source` 这一格根本不存在，依赖只能靠"正文散文扫描"（真机上扫出 0 条）。
    """
    store = _ws(tmp_path)
    _library(store)
    out = _run_proof_round(store, [f"stmt:{THEOREM_A}"])
    f_stmt = str(out["statement_id"])
    manuscript_rel = str(out["manuscript_path"])
    assert manuscript_rel == f"{MANUSCRIPT_DIR}/f-proof-{f_stmt}.md", out

    # D 交研究手稿：携带单由 D 的渲染器算出来（不靠模型记着去传）
    report = _d_report(store)
    assert CARRIED_HEADING in report, report[-3000:]
    carried = DS.carried_manuscripts(report)
    assert carried["present"] is True and carried["refused"] == "", carried
    assert [r["statement_id"] for r in carried["rows"]] == [f_stmt], carried
    assert carried["rows"][0]["path"] == manuscript_rel, carried
    assert len(str(carried["rows"][0]["sha256"])) == 64, carried

    got = _register(store, statement_full="定理：D 的研究手稿引用了 F 的证明手稿。",
                    proof_text=f"1. 由 F 的证明手稿直接得到结论（见 stmt:{f_stmt}）。",
                    derived_from=[f_stmt])
    assert got.get("ok") is True, got
    assert str(got.get("manuscript_source")) == SRC_CARRIED, got
    assert _carried_holds(got, store, cited=THEOREM_A), got
    rows = _deps(store)
    assert {str(r.get("used_by")) for r in rows} == {f"stmt:{got['stmt_id']}"}, rows
    assert {int(r.get("path_group")) for r in rows} == {1}, rows
    reading = got.get("deps_missing") or {}
    assert reading.get("manuscript_source") == SRC_CARRIED, reading
    assert (reading.get("manuscript_carried") or {}).get("carried_by") == (
        f"{MANUSCRIPT_DIR}/{pathlib.Path(_d_report_path(store)).name}"), reading
    # 走的是主路：兜底读盘那一支根本没被调用（读了就说明主路没成）
    assert (reading.get("manuscript_probe") or {}) == {}, reading


def _d_report_path(store: Store) -> str:
    """D 报告的那一个落点（`write_report` 的返回；只用于读数对齐，不重写它）。"""
    return str(AgentD(store).write_report())


def test_d_does_not_carry_a_statements_it_has_no_manuscript_for(tmp_path: pathlib.Path) -> None:
    """a 的边界：盘上没有那份稿的命题不出现在携带单里（携带单不是"所有命题"）。"""
    store = _ws(tmp_path)
    _library(store)                      # 两条在册命题，盘上一份 f-proof-*.md 都没有
    out = _run_proof_round(store, [f"stmt:{THEOREM_A}"])
    report = _d_report(store)
    carried = DS.carried_manuscripts(report)
    assert carried["present"] is True and carried["refused"] == "", carried
    assert [r["statement_id"] for r in carried["rows"]] == [str(out["statement_id"])], carried


# ------------------------------------------------------------------ b 兜底读盘

def test_an_empty_parameter_reads_the_manuscript_from_disk(tmp_path: pathlib.Path) -> None:
    """b D 没带、盘上有稿 ⇒ 兜底读盘生效、依赖落成、来源读 `disk`（老调用不瘫）。

    改前红：兜底读盘这一支一行都没有（0 行）⇒ `dependencies` 一行不落、返回里也没有
    `manuscript_source` 这一格。
    """
    store = _ws(tmp_path)
    _library(store)
    # 没有 D 报告（历史调用 / 直调那一档），盘上那一份稿按"被引命题的号"命名。
    target = pathlib.Path(store.root) / MANUSCRIPT_DIR / f"f-proof-{THEOREM_A}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_MANUSCRIPT_FOR_A, encoding="utf-8")

    got = _register(store, statement_full="定理：由定理甲推出目标结论。",
                    proof_text=f"1. 由定理甲直接得到结论（见 stmt:{THEOREM_A}）。",
                    derived_from=[THEOREM_A])
    assert got.get("ok") is True, got
    assert str(got.get("manuscript_source")) == SRC_DISK, got
    rows = _deps(store)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["source_stmt_id"] == THEOREM_A, row
    assert row["used_by"] == f"stmt:{got['stmt_id']}", row
    assert int(row["path_group"]) == 1, row
    reading = got.get("deps_missing") or {}
    assert reading.get("state") == "present", reading
    assert reading.get("manuscript_source") == SRC_DISK, reading
    probe = reading.get("manuscript_probe") or {}
    assert str(probe.get("path")) == f"{MANUSCRIPT_DIR}/f-proof-{THEOREM_A}.md", probe
    assert probe.get("tried"), probe


def test_the_two_agreed_names_are_both_recognised(tmp_path: pathlib.Path) -> None:
    """b 的另一半：按计划号命名的那一种也认（"两种名都认"这条约定）。

    这一条只打 `read_manuscript` 本身（纯函数、不写台账），于是"两种名认不认"
    不需要绕一整套登记才看得出来。
    """
    store = _ws(tmp_path)
    d = pathlib.Path(store.root) / MANUSCRIPT_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / "f-proof-plan-000007.md").write_text(_MANUSCRIPT_FOR_A, encoding="utf-8")
    plan_hit = DS.read_manuscript(store.root, statement_ids=["000099"], plan_id="000007")
    assert plan_hit["source"] == SRC_DISK, plan_hit
    assert plan_hit["path"] == f"{MANUSCRIPT_DIR}/f-proof-plan-000007.md", plan_hit
    # 按命题号优先：两处都在时读按号的那一份（更精确）
    (d / f"f-proof-{THEOREM_A}.md").write_text(_MANUSCRIPT_FOR_B, encoding="utf-8")
    by_id = DS.read_manuscript(store.root, statement_ids=[THEOREM_A], plan_id="000007")
    assert by_id["path"] == f"{MANUSCRIPT_DIR}/f-proof-{THEOREM_A}.md", by_id
    # 一处都没有时：`none`，且查过哪些路径是读得出来的（不是一句"没有稿"）
    miss = DS.read_manuscript(store.root, statement_ids=["000098"], plan_id="000006")
    assert miss["source"] == SRC_NONE, miss
    assert miss["checked"] is True and miss["tried"], miss
    assert "都不在盘上" in miss["why"], miss


def test_a_given_manuscript_wins_and_the_disk_is_not_read(tmp_path: pathlib.Path) -> None:
    """b 的正控：参数给了稿 ⇒ `manuscript_source=param`，D 携带与盘上那份都不去读。

    改前红：改前没有"参数优先"这一回事（也没有 `manuscript_source` 这一格）——
    这条正控要证明的正是"B 不会因为别处有别的稿就把参数那份换掉"。
    """
    store = _ws(tmp_path)
    _library(store)
    d = pathlib.Path(store.root) / MANUSCRIPT_DIR
    d.mkdir(parents=True, exist_ok=True)
    # 盘上放一份只引定理乙的稿；参数里给只引定理甲的稿 ⇒ 落库的必须是参数那一份
    (d / f"f-proof-{THEOREM_A}.md").write_text(_MANUSCRIPT_FOR_B, encoding="utf-8")
    got = _register(store, statement_full="定理：由定理甲推出目标结论（参数优先）。",
                    proof_text=f"1. 由定理甲直接得到结论（见 stmt:{THEOREM_A}）。",
                    derived_from=[THEOREM_A], proof_manuscript=_MANUSCRIPT_FOR_A)
    assert got.get("ok") is True, got
    assert str(got.get("manuscript_source")) == SRC_PARAM, got
    rows = _deps(store)
    assert [r["source_stmt_id"] for r in rows] == [THEOREM_A], rows
    assert THEOREM_B not in {r["source_stmt_id"] for r in rows}, (
        "落库的依赖来自盘上那一份（只引定理乙）⇒ 参数没有优先", rows)
    reading = got.get("deps_missing") or {}
    assert (reading.get("manuscript_probe") or {}) == {}, reading
    assert (reading.get("manuscript_carried") or {}) == {}, reading


# ------------------------------------------------------------------ c 两处都没有（负控）

def test_no_manuscript_anywhere_with_a_citation_is_refused(tmp_path: pathlib.Path) -> None:
    """c 参数空、D 没带、盘上也没有稿，而正文有在册引用 ⇒ 整笔拒收、零写入。

    改前红：改前这一笔照常入库（依赖靠秘书的正文扫描，`dependencies` 会落一行）——
    于是"没有手稿"这件事在读数上完全看不见。这条负控守的就是"不许静默跳过"。
    """
    store = _ws(tmp_path)
    _library(store)
    before_statements = len(store.rows("statements"))
    got = _register(store, statement_full="定理：没有手稿的那一路（判据夹具）。",
                    proof_text=f"1. 由定理甲直接得到结论（见 stmt:{THEOREM_A}）。",
                    derived_from=[THEOREM_A])
    assert got.get("ok") is False, got
    assert got.get("kind") == DS.REFUSED_SECTION_MISSING, got
    assert f"stmt:{THEOREM_A}" in got.get("error", ""), got
    assert str(got.get("manuscript_source")) == SRC_NONE, got
    assert "携带" in got.get("error", ""), (
        "拒信要指回主路（让 D 把 F 那份稿一并带过来），而不只是说「没有稿」", got)
    assert _deps(store) == [], _deps(store)
    assert len(store.rows("statements")) == before_statements, store.rows("statements")


def test_a_self_contained_proof_without_a_manuscript_still_lands(tmp_path: pathlib.Path) -> None:
    """c 的边界：正文一条在册引用都没有 ⇒ 不拒收；有稿时读数是 `not_applicable`。

    两档分开钉：
    - 连稿都没有、正文也没有引用 ⇒ 照常入库，读数仍是秘书那一份（`missing`，带 why），
      不是拒收 —— "没引"与"引了没交稿"是两件事；
    - 有稿、稿里的依赖表是空的（作者显式声明自足）⇒ `not_applicable`（业主那句
      "无引用 ⇒ not_applicable"说的就是这一档）。
    """
    store = _ws(tmp_path)
    _library(store)
    got = _register(store, statement_full="定理：自足的证明（判据夹具）。",
                    proof_text="1. 由定义直接得到，本证明不引用任何在册命题。")
    assert got.get("ok") is True, got
    reading = got.get("deps_missing") or {}
    assert reading.get("state") == "missing", reading
    assert str(reading.get("why") or "").strip(), reading
    assert reading.get("manuscript_source") == SRC_NONE, reading
    assert _deps(store) == [], _deps(store)

    empty_table = ("## 证明\n\n1. 由定义直接得到，不引用任何在册命题。\n\n"
                   "## 依赖\n\n"
                   "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
                   "|---|---|---|---|\n\n"
                   "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
    got2 = _register(store, statement_full="定理：自足的证明（空依赖表，判据夹具）。",
                     proof_text="1. 由定义直接得到，不引用任何在册命题。",
                     proof_manuscript=empty_table)
    assert got2.get("ok") is True, got2
    reading2 = got2.get("deps_missing") or {}
    assert reading2.get("state") == "not_applicable", reading2
    assert reading2.get("manuscript_source") == SRC_PARAM, reading2
    assert _deps(store) == [], _deps(store)


# ------------------------------------------------------------------ e 端到端

class _VSeam:
    """V 的假缝（`ask` 形状；记录提示词，便于判"依赖面进没进审查材料"）。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def ask(self, prompt: str, **_kw):
        from types import SimpleNamespace

        self.prompts.append(prompt)
        return SimpleNamespace(text=self.reply, problem="")


def test_the_whole_chain_f_write_d_carry_b_read_v_sign(tmp_path: pathlib.Path) -> None:
    """e F 写稿 → D 携带 → B 读稿落依赖 → V 核引用签字（整条链，零模型钱）。

    判据三件：
    1. F 那一轮的手稿按命号落盘（登记之前就在手上，见 a0）；
    2. B 读的是 D 带来的那一份（`carried_by_D`），依赖行落在 B 新登记的那条命题上，
       `used_by` / `path_group` / `source_stmt_id` 三格对得上；
    3. V 的审查材料里有那份依赖面（编号 + F 的说法 + 被引命题正文），并据此签字。
    改前红：这条链一处都不通（F 写不出稿、D 没有携带、B 没有读稿、依赖 0 行、V 的
    `citation_checks` 那一格不存在）。
    """
    store = _ws(tmp_path)
    _library(store)
    out = _run_proof_round(store, [f"stmt:{THEOREM_A}", f"stmt:{THEOREM_B}"])
    f_stmt = str(out["statement_id"])
    assert (pathlib.Path(store.root) / str(out["manuscript_path"])).is_file(), out

    # D 交研究手稿（携带单里应该有 F 那一条）
    report = _d_report(store)
    carried = DS.carried_manuscripts(report)
    assert [r["statement_id"] for r in carried["rows"]] == [f_stmt], carried

    got = _register(store, statement_full="定理：研究手稿引用了 F 的证明手稿（整条链）。",
                    proof_text=f"1. 由 F 的证明手稿直接得到结论（见 stmt:{f_stmt}）。",
                    derived_from=[f_stmt])
    assert got.get("ok") is True, got
    assert str(got.get("manuscript_source")) == SRC_CARRIED, got
    b_stmt = str(got["stmt_id"])
    rows = _deps(store)
    assert len(rows) >= 1, rows
    assert {str(r["used_by"]) for r in rows} == {f"stmt:{b_stmt}"}, rows
    assert {int(r["path_group"]) for r in rows} == {1}, rows
    assert {str(r["source_stmt_id"]) for r in rows} == {THEOREM_A, THEOREM_B}, rows
    assert (got.get("deps_missing") or {}).get("state") == "present", got

    # V 读同一份依赖面核引用并签字
    reply = json.dumps({"verdict": "成立", "defect_step": None, "why": "",
                        "findings": [], "citation_checks": [
                            {"stmt_id": THEOREM_A, "verdict": "consistent",
                             "quote_verbatim": False, "note": "由定理甲那一步，用法一致"},
                            {"stmt_id": THEOREM_B, "verdict": "consistent",
                             "quote_verbatim": False, "note": "由定理乙那一步，用法一致"}]},
                       ensure_ascii=False)
    v_llm = _VSeam(reply)
    v = AgentV(store, workspace_root=store.root, llm=v_llm)
    b_row = next(dict(r) for r in store.rows("statements") if str(r.get("stmt_id")) == b_stmt)
    signed = v.verify_proof(b_stmt, proof_text=str(b_row.get("proof_text") or ""))
    assert signed.get("signed_bit3") is True, signed
    assert {c["stmt_id"] for c in signed.get("citation_checks") or []} == {
        THEOREM_A, THEOREM_B}, signed.get("citation_checks")
    assert v_llm.prompts, "V 没有被问过"
    prompt = v_llm.prompts[-1]
    assert "## 引用核实" in prompt, prompt[-2500:]
    assert THEOREM_A in prompt and THEOREM_B in prompt, prompt[-2500:]
    # 盘上两行：依赖行落在 B 那条命题上，verifications 里那一签是「成立」且签住第 3 位
    ledger, problems = VR.list_verifications(store.root, statement_id=b_stmt, limit=None)
    assert problems == [], problems
    assert ledger, "verifications 台账里一行都没有"
    assert str(ledger[-1].get("verdict")) == "成立", ledger[-1]
    assert VR.signs_bit3(ledger[-1]) is True, ledger[-1]


# ------------------------------------------------------------------ d 反真空

def test_regressing_the_write_order_turns_a_red(store: Store, monkeypatch) -> None:
    """d-1 反真空：把写稿时机退回"登记之后" ⇒ a（D 携带）的判据必红。

    打桩两处（合起来就是改前那一套时序）：① `proof_manuscript` 第一次调用不落盘
    （登记那一刻盘上没有稿）；② `publish_manuscript` 不改名（登记之后也不按命号落）。
    于是 D 的携带单是空的、B 兜底也找不到稿 ⇒ 依赖面建不起来（在映射的判据下必红）。
    """
    _library(store)
    real_write = AgentF.proof_manuscript
    state = {"calls": 0}

    def late_write(self, product, *, sg, statement_id="", plan):
        state["calls"] += 1
        got = real_write(self, product, sg=sg, statement_id=statement_id, plan=plan)
        if state["calls"] == 1:
            path = pathlib.Path(self.cfg.get("workspace_root") or self.store.root) / got["path"]
            if path.is_file():
                path.unlink()
            got = dict(got)
            got["ok"] = False
            got["why"] = "（反真空：把写稿时机退回登记之后）"
        return got

    def no_publish(self, manuscript, *, statement_id):
        out = dict(manuscript)
        out["published"] = False
        out["renamed_from"] = ""
        return out

    monkeypatch.setattr(AgentF, "proof_manuscript", late_write)
    monkeypatch.setattr(AgentF, "publish_manuscript", no_publish)
    spy = _RegistrationSpy()
    monkeypatch.setattr(AgentF, "_proof_outlet", spy)
    f, _seam = _f_with_seam(store, _proof_product(cites=[f"stmt:{THEOREM_A}"]))
    spy.bind(f)
    out = f.step(_new_plan(f))

    # 正控先确认打桩没有把整条路打断（否则"红"是因为别的原因）
    assert out.get("action") == "proof", out
    assert spy.calls, "登记那一笔根本没被调用 ⇒ 这条反真空测的不是时序"
    assert spy.calls[0]["files"] == [], spy.calls[0]["files"]
    assert _a0_holds(store, out, spy) is False, (
        "写稿时机退回登记之后，a0 的判据竟然还是绿的 ⇒ 它测的不是时序")
    # 于是 D 手上没有稿可带（携带单空），B 也就落不了依赖
    assert DS.carried_manuscripts(_d_report(store))["rows"] == [], "携带单本该是空的"
    got = _register(store, statement_full="定理：写稿时机退回登记之后（反真空）。",
                    proof_text=f"1. 由定理甲直接得到（见 stmt:{THEOREM_A}）。",
                    derived_from=[THEOREM_A])
    assert _carried_holds(got, store, cited=THEOREM_A) is False, got
    assert got.get("ok") is False and got.get("kind") == DS.REFUSED_SECTION_MISSING, got


def test_stubbing_the_disk_fallback_out_turns_b_red(tmp_path: pathlib.Path,
                                                    monkeypatch) -> None:
    """d-2 反真空：把兜底读盘打桩成"永远没找到" ⇒ b 的判据必红。

    打桩点就是 b 读的那一条实现（`depsection.read_manuscript`）：返回 `none` 之后，
    明明盘上有稿、「依赖落成 + `manuscript_source=disk`」这一组断言必须取反。
    """
    store = _ws(tmp_path)
    _library(store)
    d = pathlib.Path(store.root) / MANUSCRIPT_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / f"f-proof-{THEOREM_A}.md").write_text(_MANUSCRIPT_FOR_A, encoding="utf-8")

    monkeypatch.setattr(DS, "read_manuscript",
                        lambda *a, **kw: {"checked": True, "source": SRC_NONE,
                                          "text": "", "path": "", "tried": [],
                                          "why": "（反真空：兜底读盘被打桩成永远没找到）"})
    got = _register(store, statement_full="定理：兜底读盘被打桩（判据夹具）。",
                    proof_text=f"1. 由定理甲直接得到结论（见 stmt:{THEOREM_A}）。",
                    derived_from=[THEOREM_A])
    # 打桩之后 b 的结论取反：依赖一行不落，且整笔被拒收（正文有在册引用而没有稿）
    assert _deps(store) == [], _deps(store)
    assert got.get("ok") is False, got
    assert got.get("kind") == DS.REFUSED_SECTION_MISSING, got
    assert str(got.get("manuscript_source")) == SRC_NONE, got


def test_stubbing_the_carried_reader_out_turns_a_red(tmp_path: pathlib.Path,
                                                     monkeypatch) -> None:
    """d-3 反真空：把"读 D 的携带单"打桩成永远读不到 ⇒ a 必红（改走 disk 兜底）。

    这一条与 d-2 合起来才说明主路与兜底是两条真的分开的路：打掉主路，来源读数
    必须变成 `disk`（而不是仍然自称 `carried_by_D`）。
    """
    store = _ws(tmp_path)
    _library(store)
    out = _run_proof_round(store, [f"stmt:{THEOREM_A}"])
    _d_report(store)
    monkeypatch.setattr(DS, "read_carried_manuscript",
                        lambda *a, **kw: {"checked": True, "source": SRC_NONE,
                                          "text": "", "path": "", "sha256": "",
                                          "carried_by": "", "tried": [],
                                          "why": "（反真空：携带单被打桩成读不到）"})
    got = _register(store, statement_full="定理：携带单被打桩（判据夹具）。",
                    proof_text=f"1. 由 F 的稿直接得到（见 stmt:{out['statement_id']}）。",
                    derived_from=[str(out["statement_id"])])
    assert str(got.get("manuscript_source")) == SRC_DISK, got
    assert _carried_holds(got, store, cited=THEOREM_A) is False, got
    assert {str(r.get("source_stmt_id")) for r in _deps(store)} == {THEOREM_A}, _deps(store)
