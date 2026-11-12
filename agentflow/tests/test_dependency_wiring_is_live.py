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

    F 先写手稿（登记之前就要在手上）→ F 的 outlet 登记那条命题（稿按 F 自己的稿号
    命名 `reports/f-proof-<稿号>.md`；命题号由 B 收录时现取，不改稿名）→ D 交研究
    手稿给 B 入库时把 F 那份稿一并带上（D 的报告里「## 携带的证明手稿」那张三列表：
    命题号 / 路径 / sha256）→ B 读那份稿、按 `## 依赖` 三列表落 dependencies →
    V 读同一份依赖面核引用并签字。

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

import pytest

import json
import pathlib
import re
import sys

# 与 `tests/conftest.py` 同一个注入方式：这一份也要能在一棵临时源码树上单独跑。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import verifications as VR
import agentflow.agent_b.register_statement as RS
from agentflow.agent_b import AgentB
from agentflow.agent_d import AgentD
from agentflow.agent_f import AgentF
from agentflow.agent_v import AgentV
from agentflow.store import Store

from conftest import seed_statement_row, sign_before_registration


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
#: 2026-10-27 起还要盖那一行洗稿元信息（`DS.mark_washed`）：这份夹具代表"F 的 proof
#: 动作渲染、秘书洗过的那一版"，而 B 现在会拒收 `reports/f-proof-*.md` 里缺这一行的
#: 手写稿（`manuscript_not_washed`，见 `test_b_manuscript_must_be_framework_rendered.py`）。
_MANUSCRIPT_FOR_A = DS.mark_washed(
    "## 证明\n\n1. 由定理甲直接得到（依据：stmt:%s）。\n\n" % THEOREM_A
    + _DEP_TABLE.format(quote="由定理甲，G 有 p 阶元", sid=THEOREM_A),
    actor="secretary-F")
#: 另一份（只引定理乙）：用于证明"参数给了稿就不去读盘"。
_MANUSCRIPT_FOR_B = DS.mark_washed(
    "## 证明\n\n1. 由定理乙直接得到（依据：stmt:%s）。\n\n" % THEOREM_B
    + _DEP_TABLE.format(quote="由定理乙，阶数被 p 整除", sid=THEOREM_B),
    actor="secretary-F")


# ------------------------------------------------------------------ 夹具

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _add_statement(store: Store, stmt_id: str, *, label: str = "") -> dict:
    body = _PROOF_TEXT.format(sid=stmt_id)
    # 等级是唯一的轴（2026-11-05 口径）：被引命题的档位不再由 `evidence_kind` 声明，
    # 而是由五元位现算。第 2 位（有证明）先落真、正文就是这一份，V 的三次「成立」
    # 之后第 3 位翻真 ⇒ 等级现算 `pre_theorem`，正好够可引门槛。
    bits = EB.bits_of(origin="own_result", proof=True, proof_process=body,
                      kind="theorem")
    row = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem",
        label=label or f"在册命题 {stmt_id}",
        statement_text=f"命题 {stmt_id} 的短版",
        statement_full=f"命题 {stmt_id} 的完整正文（含假设）。",
        proof_text=body,
        bits=bits,
        evidence_kind=EB.kind_from_bits(bits, kind="theorem"),
        status="active",
        quote_verified=None,
        quote_reason="判据夹具：自产命题，没有外部引文要比对",
        created_at=S.now_iso(), created_by="agent-B",
    )
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    return row.to_dict()


def _library(store: Store) -> None:
    """两条够格（proof_review）的在册命题：引用门槛正好卡在它们身上。

    业主 2026-10-29：`proof_review` 要的那一签是「同一份正文连续 3 次成立」之后才落的，
    所以这里签够 3 次（第 1 次先断"没签上"，第 3 次断"签上了"）。
    """
    for sid, label in ((THEOREM_A, "定理甲"), (THEOREM_B, "定理乙")):
        _add_statement(store, sid, label=label)
        first = VR.record_verification(
            store.root, statement_id=sid, proof_text=_PROOF_TEXT.format(sid=sid),
            verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
            store=store, proof_no=1, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
        assert dict(first.get("statement_writeback") or {}).get("written") is False, (
            "第 1 次「成立」就把第 3 位翻了（连续 3 次才发签）", first.get("statement_writeback"))
        for _ in (1, 2):
            signed = VR.record_verification(
                store.root, statement_id=sid, proof_text=_PROOF_TEXT.format(sid=sid),
                verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
                store=store, proof_no=1, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
        assert signed.get("checked") is True, signed
        assert dict(signed.get("statement_writeback") or {}).get("written") is True, (
            "连续 3 次成立之后仍然没发签", signed.get("statement_writeback"))
        row = next(dict(r) for r in store.rows("statements")
                   if str(r.get("stmt_id")) == sid)
        # 历史列照等级反算（判定面仍只读五元位现算的等级）。
        row["evidence_kind"] = EB.kind_from_bits(row["bits"],
                                                 kind=row.get("kind") or "")
        assert row["evidence_kind"] == "proof_review", row["evidence_kind"]
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
    """跑一轮 F 的 proof 档，返回这一轮的读数（手稿登记条目 + 在册命题号）。

    2026-11-07（业主裁定：登记与写证明解耦）：F 不再自己把新命题写进 `statements`；
    命题由 B 在 V 签之后收录。这一组判据量的是"B 读 F 的手稿落依赖"那条链，所以夹具
    把这一条命题先铺成已经在册（B 先收录过的那一版），于是 F 这一轮走的是
    "已登记 ⇒ 只挂证明"那条路：手稿按 F 自己的稿号命名（`reports/f-proof-<稿号>.md`，
    2026-11-10 起与命题号是两个号段），D 才携带得走。这与真机顺序一致（B 收录在前、
    F 之后反复改证明）。
    """
    f, _seam = _f_with_seam(store, _proof_product(cites=cites))
    plan_id = _new_plan(f)
    text = "由在册定理推出目标引理"
    seeded = seed_statement_row(
        store, statement_full=text, statement_text=text, kind="conjecture",
        label=f"F 攻坚 {plan_id} 子目标 s1",
        # 出处那一栏：B 收录 F 的手稿时写的就是"这份稿在哪"（不是页码）。
        # 没有它，D 之后代递这一行会被 `missing_own_source` 拒（那是既有判据，不放宽）。
        line_range={"label": f"reports/f-proof-plan-{plan_id}.md"},
        # 证据档：B 收录时按 V 的账本写这一格；D 之后代递时读的也是它
        # （两边不一致会被判成"这一笔要更强证据"，从而绕开"只读稿登记依赖"那条早退支路）。
        evidence_kind="heuristic",
        proof_text="（B 在 V 签之后收录的那一版证明：这一轮会被 F 的新证明重写）")
    out = f.step(plan_id)
    assert out.get("action") == "proof", out
    assert str(out.get("statement_id") or "") == str(seeded["stmt_id"]), out
    # 2026-11-10（夹具归一，按稿号口径）：B 收录 F 的稿时把稿号记在 `statements` 行上
    # （`register_statement` 的 `row["manuscript_id"]`），D 的携带单之后按这一格找稿。
    # 这一行的其余部分仍是"B 收录过的那一版"；补的只是真机上 B 收录那一步写下的那一格
    # —— 不补它，D 只能把这份稿读成 `mss:<稿号>`（还等着收录的那一档），
    # 于是"D 携带的是这一条命题的稿"这条断言没有可读的连接点。断言一个字没改。
    _mid_now = str(out.get("manuscript_id") or "")
    assert _mid_now, out
    if str(seeded.get("manuscript_id") or "") != _mid_now:
        _row = dict(next(r for r in store.rows("statements")
                         if str(r.get("stmt_id")) == str(seeded["stmt_id"])))
        _row["manuscript_id"] = _mid_now
        _row["proof_no"] = int(out.get("proof_no") or 1)
        with store.tx("statements", actor="test", note="fixture:record-manuscript-id") as _tx:
            _tx.upsert("statements", _row)
    # 2026-11-10（夹具归一）：这一组用例量的是"D 携带 → B 读稿"那条链，不是 F 的秘书
    # 闸；而 `_f_with_seam` 不装秘书 ⇒ 形态闸 fail-closed，登记条目落不下来。这里用
    # 登记的那个唯一写口把条目补齐（命题号 = 已铺在册的那一条、稿号 = F 自己的稿号），
    # 判据与断言一个字没改 —— 补的是"夹具环境缺的那一格判断面"。
    if str(out.get("proof_mode") or "") != "registered":
        from agentflow import proofregistry as _PR_FIX

        _rel = pathlib.Path(store.root) / str(out["manuscript_path"])
        _text = _rel.read_text(encoding="utf-8")
        _head, _sections = _PR_FIX.split_sections(_text)
        _prop = next((b for n, b in _sections if n == "命题"), "")
        _fix = _PR_FIX.register_or_rewrite(
            store.root, family="F", label=str(out.get("proof_label") or ""),
            proposition=str(_prop or ""),
            proof_text=DS.proof_body(_text).strip("\n"),
            statement_id=str(out["statement_id"]), sid="s1", title="",
            manuscript_id=str(out.get("manuscript_id") or ""),
            kind="conjecture", template=_text,
            gate=lambda **_kw: {"checked": True, "well_formed": True,
                                "submittable": True, "problems": [],
                                "refused": "", "reason": "夹具：形态合规"})
        assert _fix.get("ok") is True, _fix
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

    def __call__(self, product, sg, *, plan, proof_manuscript="", manuscript_id=""):
        agent = self.agent
        root = pathlib.Path(agent.cfg.get("workspace_root") or agent.store.root)
        reports_dir = root / MANUSCRIPT_DIR
        files = sorted(p.name for p in reports_dir.glob("f-proof-*.md")) if (
            reports_dir.is_dir()) else []
        texts = {name: (reports_dir / name).read_text(encoding="utf-8") for name in files}
        self.calls.append({"received": str(proof_manuscript or ""), "files": files,
                           "texts": texts})
        return self.real(agent, product, sg, plan=plan, proof_manuscript=proof_manuscript,
                         manuscript_id=manuscript_id)


def _without_proposition_line(text: str) -> str:
    """去掉开头那行"命题号"之后的正文（改名那一刻它从"还没落号"换成真号）。

    为什么允许这一行不同：登记拿到命题号之后 `publish_manuscript` 会按号改名，
    并把开头那一行"命题号"写成真的号（否则盘上会出现"文件叫 f-proof-000001.md、
    正文说还没落号"的双读数，按号核对携带单的那一侧就找不到它）。
    除了这一行，手稿正文一个字都不许变 —— 那才是 a0 要钉的"登记手上的稿 == 盘上那份"。
    """
    return "\n".join(
        line for line in str(text or "").replace("\r\n", "\n").split("\n")
        if not line.strip().startswith("- 命题号"))


def _a0_holds(store: Store, out: dict, spy: _RegistrationSpy) -> bool:
    """判据 a0（判据本体，正控与反真空共用同一个谓词）。

    2026-11-07（解耦）之后的三件事（同时成立才算绿）：
    1. 登记那一笔真的收到了一份非空的手稿正文，且它里面有 `## 依赖` 那一节；
    2. 登记那一刻盘上已经有这份正文（计划名那一份底稿）；
    3. 登记条目落在 `out["manuscript_path"]`，它的三节分节哈希与收到的那份逐字相同
       （登记只补了头部元信息，没改正文）。
    """
    from agentflow import proofregistry as _PR

    if len(spy.calls) != 1:
        return False
    call = spy.calls[0]
    received = str(call["received"] or "")
    if not received.strip() or DS.SECTION_HEADING not in received:
        return False
    if not any(text == received for text in call["texts"].values()):
        return False
    rel = str(out.get("manuscript_path") or "")
    if not rel or str(out.get("proof_mode") or "") != "registered":
        return False
    path = pathlib.Path(store.root) / rel
    if not path.is_file():
        return False
    final = path.read_text(encoding="utf-8")
    return _PR.section_hashes(final) == _PR.section_hashes(received)


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

def test_the_manuscript_is_on_disk_before_the_registration(store: Store, monkeypatch,
                                                          signed_v_handoffs) -> None:
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
    # 2026-11-07（业主裁定：登记与写证明解耦）：这一轮就是一次手稿登记（新命题）——
    # 底稿是按 F 自己的稿号写的那份（此刻还没有命题号），登记条目落在同一个规范路径上；
    # F 不再写 statements，所以这一格没有命题号（B 在 V 签之后收录）。
    assert out.get("proof_mode") == "registered", out
    assert str(out.get("statement_id") or "") == "", out
    assert str(out.get("manuscript_path")) == (
        f"{MANUSCRIPT_DIR}/f-proof-{out['manuscript_id']}.md"), out
    assert str(out.get("manuscript_source")) == SRC_PARAM, out
    # 同一条命题只留一份稿（底稿与登记条目是同一份文件，不是复制两份）。
    assert _reports(store) == [f"f-proof-{out['manuscript_id']}.md"], _reports(store)


# ------------------------------------------------------------------ a D 携带

def test_d_carries_the_f_manuscript_and_b_reads_it(tmp_path: pathlib.Path,
                                                   monkeypatch) -> None:
    """a D 交研究手稿给 B 时带上 F 的稿 ⇒ B 读那份稿落依赖、来源读 `carried_by_D`。

    改前红：D 没有任何携带动作（`write_report` 里没有那一节），B 也没有读它的一行 ⇒
    `manuscript_source` 这一格根本不存在，依赖只能靠"正文散文扫描"（真机上扫出 0 条）。

    审计 M8 补的一格（2026-10-27）：报告里那张携带单是渲染出来的，而"把稿递给 B"
    是 `write_report` 里的一笔代码调用（`self._deliver_carried_to_b(...)`）。只断报告
    里的段落时，把那一笔掏空判据仍然全绿 —— 所以这里同时数它的调用次数：
    观察者不掏空实现（真调用照跑，`b=None` 那一趟如实记"没递"），只记"叫过没有、
    收到的行是不是携带单上那一行"。
    """
    store = _ws(tmp_path)
    _library(store)
    out = _run_proof_round(store, [f"stmt:{THEOREM_A}"])
    f_stmt = str(out["statement_id"])
    manuscript_rel = str(out["manuscript_path"])
    # 2026-11-10：稿名是 F 自己的稿号，不是命题号（这里刻意量"两者不同"）。
    assert manuscript_rel == f"{MANUSCRIPT_DIR}/f-proof-{out['manuscript_id']}.md", out

    # 交付动作的观察者（数次数 + 记收到的行；实现照跑）
    handed: list[list[dict]] = []
    real_hand = AgentD._deliver_carried_to_b

    def counting_hand(self, rows):
        handed.append([dict(r) for r in rows])
        return real_hand(self, rows)

    monkeypatch.setattr(AgentD, "_deliver_carried_to_b", counting_hand)

    # D 交研究手稿：携带单由 D 的渲染器算出来（不靠模型记着去传）
    report = _d_report(store)
    assert CARRIED_HEADING in report, report[-3000:]
    carried = DS.carried_manuscripts(report)
    assert carried["present"] is True and carried["refused"] == "", carried
    assert [r["statement_id"] for r in carried["rows"]] == [f_stmt], carried
    assert carried["rows"][0]["path"] == manuscript_rel, carried
    assert len(str(carried["rows"][0]["sha256"])) == 64, carried
    # 交付动作真被调用（审计 M8）：报告里那一节是渲染出来的，而"递给 B"是代码行为。
    assert handed, ("D 的交付动作一次都没被调用：携带单只是渲染进了报告，"
                    "`write_report` 里那一笔 `_deliver_carried_to_b` 没有接上")
    assert [r["statement_id"] for r in handed[0]] == [f_stmt], handed[0]

    # 2026-11-04（业主裁定 甲）：这一笔要写进台账的正文也要有一份手稿签。
    # 签在登记之前落（pending 台账按正文 sha 认领），而必须排在 D 的报告之后 ——
    # 携带单只列 `reports/f-proof-*.md`，签名载体不是被携带的那一份。
    # 这一条量的"稿从哪来"一个字没改：它读的仍是 D 交过来的那一份。
    body = f"1. 由 F 的证明手稿直接得到结论（见 stmt:{f_stmt}）。"
    sign_before_registration(store.root, proof_text=body)
    got = _register(store, statement_full="定理：D 的研究手稿引用了 F 的证明手稿。",
                    proof_text=body,
                    derived_from=[f_stmt])
    assert got.get("ok") is True, got
    assert str(got.get("manuscript_source")) == SRC_CARRIED, got
    assert _carried_holds(got, store, cited=THEOREM_A), got
    # 只核 B 新登记那一条的依赖面：F 那一轮现在也经 B 的登记落自己的依赖边
    # （D8：命题只经 B 的 `register_statement` 写），所以整张表里会有两组。
    rows = [r for r in _deps(store) if str(r.get("used_by")) == f"stmt:{got['stmt_id']}"]
    assert rows, _deps(store)
    assert {int(r.get("path_group")) for r in rows} == {1}, rows
    reading = got.get("deps_missing") or {}
    assert reading.get("manuscript_source") == SRC_CARRIED, reading
    assert (reading.get("manuscript_carried") or {}).get("carried_by") == (
        f"{MANUSCRIPT_DIR}/{pathlib.Path(_d_report_path(store)).name}"), reading
    # 走的是主路：兜底读盘那一支根本没被调用（读了就说明主路没成）
    assert (reading.get("manuscript_probe") or {}) == {}, reading


def test_a_cited_statements_carried_manuscript_does_not_lend_its_number(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空（候选号）：把"被引命题的稿不是本笔自己的稿"摘掉 ⇒ 又撞 000002。

    D 的携带单里那份稿属于 F 的在册命题（稿头 `stmt:<F 的号>`），它是「被引命题」
    的依赖面来源，不是这一笔要登记的新命题的稿。候选号只许来自"本笔自己的稿"：
    把那条判据打桩成恒 False（= 摘掉）之后，同一条链必须回到
    `stmt_id_taken`（000002 已被 F 的命题占用）—— 那正是修前的红。
    """
    store = _ws(tmp_path)
    _library(store)
    out = _run_proof_round(store, [f"stmt:{THEOREM_A}"])
    f_stmt = str(out["statement_id"])
    # 2026-11-10（夹具归一，老盘形态）：解耦之前 F 会把在册命题号写进稿头
    # （`- 命题号：stmt:<号>`）；新口径不再写（稿号就是稿的身份）。这一条量的正是
    # 「老盘上那种写着被引命题号的稿，不许把那个号借给本笔」—— 把那一行按老盘形态
    # 补回去，判据（`_manuscript_belongs_to_a_cited_statement`）才有输入。
    # 不补它，候选号两边都为空，打桩与不打桩读数相同（反真空会空转）。
    from agentflow import manuscriptform as _MF_FIX

    _rel_fix = str(out["manuscript_path"])
    _path_fix = pathlib.Path(store.root) / _rel_fix
    _old_fix = _path_fix.read_text(encoding="utf-8")
    _new_fix, _applied_fix = _MF_FIX.ensure_statement_line(_old_fix, f_stmt)
    assert _applied_fix is True, (_old_fix[:300], f_stmt)
    _path_fix.write_text(_new_fix, encoding="utf-8")
    _d_report(store)
    body = f"1. 由 F 的证明手稿直接得到结论（见 stmt:{f_stmt}）。"
    sign_before_registration(store.root, proof_text=body)
    monkeypatch.setattr(RS, "_manuscript_belongs_to_a_cited_statement",
                        lambda **kw: False, raising=False)
    got = _register(store,
                    statement_full="定理：D 的研究手稿引用了 F 的证明手稿（反真空）。",
                    proof_text=body, derived_from=[f_stmt])
    assert got.get("ok") is False, got
    assert got.get("kind") == "stmt_id_taken", got


def test_the_delivery_really_hands_the_manuscript_to_b(tmp_path: pathlib.Path,
                                                        signed_v_handoffs) -> None:
    """a 的第二格（审计 M8）：D 的交付动作真把稿递给 B，读数里 `delivered >= 1`。

    为什么单独一条：`test_d_carries_the_f_manuscript_and_b_reads_it` 那一趟的 D 没有
    B 的入口（`b=None`，那条判据读的是报告里的携带单），所以它读不到"递没递"。
    把 `write_report` 里那一笔 `delivery = self._deliver_carried_to_b(carried_rows)`
    掏空，那条判据仍然全绿 —— 审计 M8 就是这个存活的变异。这一条按真机装配的形状
    给 D 一个 B（`specs/d.py` 在构造期绑同一个实例），于是那一笔接没接上立刻分成
    两种读数：

    - 接着：`last_delivery.checked=True`、`delivered>=1`、B 收下的来源是
      `carried_by_D`、`dependencies` 落行；
    - 被掏空：`last_delivery` 是空的（或 `delivered=0`），`dependencies` 一行不落。
    """
    store = _ws(tmp_path)
    _library(store)
    out = _run_proof_round(store, [f"stmt:{THEOREM_A}"])
    f_stmt = str(out["statement_id"])
    b = AgentB(store, extractor=None, extract_text=None, config={})
    d = AgentD(store, config={"workspace_root": store.root}, b=b)
    d.write_report()
    delivery = dict(getattr(d, "last_delivery", {}) or {})
    assert delivery.get("checked") is True, delivery
    assert int(delivery.get("delivered") or 0) >= 1, (
        "D 的交付动作没有把任何一条稿递给 B（把那一笔掏空之后就是这个读数）", delivery)
    rec = next((dict(r) for r in delivery.get("results") or [] if r.get("ok")), None)
    assert rec is not None, delivery
    assert str(rec.get("stmt_id")) == f_stmt, rec
    assert str(rec.get("manuscript_source")) == SRC_CARRIED, rec
    rows = _deps(store)
    assert rows, "B 收下了稿却没有落依赖边"
    assert {str(r.get("used_by")) for r in rows} == {f"stmt:{f_stmt}"}, rows


def _d_report_path(store: Store) -> str:
    """D 报告的那一个落点（`write_report` 的返回；只用于读数对齐，不重写它）。"""
    return str(AgentD(store).write_report())


def test_d_does_not_carry_a_statements_it_has_no_manuscript_for(
        tmp_path: pathlib.Path, signed_v_handoffs) -> None:
    """a 的边界：盘上没有那份稿的命题不出现在携带单里（携带单不是"所有命题"）。"""
    store = _ws(tmp_path)
    _library(store)                      # 两条在册命题，盘上一份 f-proof-*.md 都没有
    out = _run_proof_round(store, [f"stmt:{THEOREM_A}"])
    report = _d_report(store)
    carried = DS.carried_manuscripts(report)
    assert carried["present"] is True and carried["refused"] == "", carried
    assert [r["statement_id"] for r in carried["rows"]] == [str(out["statement_id"])], carried


# ------------------------------------------------------------------ b 兜底读盘

def test_an_empty_parameter_does_not_borrow_a_cited_manuscripts_dependency_face(
        tmp_path: pathlib.Path) -> None:
    """b（2026-11-05 业主裁定：D1 严格版）盘上只有被引命题名的稿 ⇒ 整笔拒，不许借依赖面。

    ## 旧逐字（改前，已作废）

    同一现场（没有 D 报告、盘上 `reports/f-proof-<被引命题号>.md`、正文引了它）⇒
    `ok=true`、`manuscript_source=disk`、`dependencies` 落 1 行
    （`source_stmt_id=<被引号>`）、`deps_missing.state=present`。

    ## 为什么旧期望不对（这是收紧，不是放宽）

    那张 `## 依赖` 表写的是被引命题引了谁；把它按到新命题头上，台账里就会出现
    一条"我引了 X"而作者从未这么写的边。旧期望建立在"只读依赖面无害"这个前提上，
    而该前提不成立 —— 所以同一现场现在整笔受控拒绝。

    ## 新逐字

    `ok=false`、`kind=dependency_section_missing`（正文有在册引用而没有这一条自己的稿）、
    `manuscript_source=none`、`dependencies` 0 行、`statements` 零写入。
    """
    store = _ws(tmp_path)
    _library(store)
    # 没有 D 报告（历史调用 / 直调那一档），盘上那一份稿按"被引命题的号"命名。
    target = pathlib.Path(store.root) / MANUSCRIPT_DIR / f"f-proof-{THEOREM_A}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_MANUSCRIPT_FOR_A, encoding="utf-8")
    body = f"1. 由定理甲直接得到结论（见 stmt:{THEOREM_A}）。"
    sign_before_registration(store.root, proof_text=body)
    before = [dict(r) for r in store.rows("statements")]

    got = _register(store, statement_full="定理：由定理甲推出目标结论。",
                    proof_text=body,
                    derived_from=[THEOREM_A])
    assert got.get("ok") is False, got
    assert got.get("kind") == DS.REFUSED_SECTION_MISSING, got
    assert str(got.get("manuscript_source") or "") == SRC_NONE, got
    assert _deps(store) == [], _deps(store)
    assert [dict(r) for r in store.rows("statements")] == before, (
        "被拒的那一笔写了 statements（应当零写入）")


def test_the_ownership_check_is_what_makes_it_refuse(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """b 的反真空：把"必须是自己的稿"那一步摘掉 ⇒ 上一条判据立刻变红。

    打桩 `_manuscript_is_own` 恒真之后，同一现场回到旧形态：读 `reports/f-proof-<被引号>.md`、
    `manuscript_source=disk`、`dependencies` 落 1 行。于是"整笔拒 + 零写入"不再成立 ——
    这正是要证明"新判据的绿来自那一道所有权判据"，不是来自夹具太松。
    """
    monkeypatch.setattr(RS, "_manuscript_is_own", lambda **kw: True)
    store = _ws(tmp_path)
    _library(store)
    target = pathlib.Path(store.root) / MANUSCRIPT_DIR / f"f-proof-{THEOREM_A}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_MANUSCRIPT_FOR_A, encoding="utf-8")
    body = f"1. 由定理甲直接得到结论（见 stmt:{THEOREM_A}）。"
    sign_before_registration(store.root, proof_text=body)

    got = _register(store, statement_full="定理：由定理甲推出目标结论。",
                    proof_text=body,
                    derived_from=[THEOREM_A])
    assert got.get("ok") is True, got
    assert str(got.get("manuscript_source") or "") == SRC_DISK, got
    assert {str(r.get("source_stmt_id")) for r in _deps(store)} == {THEOREM_A}, _deps(store)


def test_a_rows_own_numbered_manuscript_is_read_for_its_dependency_face(
        tmp_path: pathlib.Path) -> None:
    """b 的正控（D1 严格版）：调用方自带正文 + 自己的按号稿 ⇒ 依赖面照读。

    这一条守的是"收紧之后正常的路一条都没断"：
    - 稿是 `reports/f-proof-<本行号>.md`（稿头声明 `stmt:<本行号>`）；
    - `manuscript_source=disk`、`dependencies` 1 行（来源 = 稿里 `## 依赖` 表点名的那条）；
    - 正文是调用方自己交的、签是这一份稿上的签（`bits.reviewed=true`）。
    """
    store = _ws(tmp_path)
    _library(store)
    full = "定理：由定理甲推出目标结论（自己的按号稿）。"
    first = _register(store, statement_full=full, proof_text="")
    assert first.get("ok") is True, first
    sid = str(first["stmt_id"])

    body = f"1. 由定理甲直接得到结论（见 stmt:{THEOREM_A}）。"
    rel = f"{MANUSCRIPT_DIR}/f-proof-{sid}.md"
    text = (
        f"# F 的证明手稿：自己的按号稿\n\n- 命题号：stmt:{sid}\n\n"
        "## 命题\n\n" + full + "\n\n## 证明\n\n" + body + "\n\n"
        + _DEP_TABLE.format(quote="由定理甲，G 有 p 阶元", sid=THEOREM_A))
    text = DS.mark_washed(text, actor="secretary-F")
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    # 签必须有一个盘上读得出来的台账背书（`sign_ledger_backing`）：走真写口落三票，
    # 签块由 `_vsigns_write_after_flip` 盖回这份按号稿（手写 `#v-…` 的假锚点不算签）。
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        VR.record_verification(
            store.root, statement_id=sid, proof_text=body,
            verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
            store=store, proof_no=1, manuscript=rel, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})

    got = _register(store, statement_full=full, proof_text=body)
    assert got.get("ok") is True, got
    assert str(got.get("manuscript_source")) == SRC_DISK, got
    rows = _deps(store)
    assert len(rows) == 1, rows
    assert rows[0]["source_stmt_id"] == THEOREM_A, rows
    assert rows[0]["used_by"] == f"stmt:{sid}", rows
    reading = got.get("deps_missing") or {}
    assert reading.get("state") == "present", reading
    assert str((reading.get("manuscript_probe") or {}).get("path")) == rel, reading
    row = next(dict(r) for r in store.rows("statements") if str(r.get("stmt_id")) == sid)
    assert str(row.get("proof_text") or "") == body, row.get("proof_text")
    assert (row.get("bits") or {}).get("reviewed") is True, row.get("bits")


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


def test_a_given_manuscript_wins_and_the_disk_is_not_read(
        tmp_path: pathlib.Path, signed_v_handoffs) -> None:
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


def test_a_self_contained_proof_lands_with_a_manuscript(
        tmp_path: pathlib.Path) -> None:
    """c 的边界（2026-11-04 业主裁定 甲之后的新口径）：自足证明不是"缺依赖"。

    改前这一条叫 `..._without_a_manuscript_still_lands`，钉的是"连稿都没有也照常入库、
    读 `missing`"——那个前提已被裁定作废（B 的载体闸：要写正文就必须有稿）。按新口径
    拆成同一份正文的两档，三态纪律不删：

    - a 带稿、稿的 `## 依赖` 是空表（作者显式声明自足）、正文零 `stmt:` 引用
      ⇒ 照常入库，读数是 `not_applicable`（这正是原来防的"自足证明被当成缺依赖"
      的反面：它仍然不是 `missing`），`manuscript_source=param`；
    - b 同一份正文、不带稿 ⇒ 整笔拒 `proof_manuscript_required`（新口径的正控：
      载体是硬条件；零写入）。这一档就是原句"没有稿也能过"的反面。

    签名仍是手稿签：两档各自先落一份 pending 签（按正文 sha 认领）。
    """
    store = _ws(tmp_path)
    _library(store)
    empty_table = ("## 证明\n\n1. 由定义直接得到，不引用任何在册命题。\n\n"
                   "## 依赖\n\n"
                   "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
                   "|---|---|---|---|\n\n"
                   "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
    lone = "1. 由定义直接得到，不引用任何在册命题。"

    # ---- a 带稿：自足 ⇒ not_applicable（不是 missing）----
    sign_before_registration(store.root, proof_text=lone)
    got = _register(store, statement_full="定理：自足的证明（空依赖表，判据夹具）。",
                    proof_text=lone, proof_manuscript=empty_table)
    assert got.get("ok") is True, got
    reading = got.get("deps_missing") or {}
    assert reading.get("state") == "not_applicable", reading
    assert str(reading.get("why") or "").strip(), reading
    assert reading.get("manuscript_source") == SRC_PARAM, reading
    assert int(got.get("deps_written") or 0) == 0, got
    assert _deps(store) == [], _deps(store)

    # ---- b 不带稿：同一份正文 ⇒ 受控拒绝、零写入 ----
    before = len(store.rows("statements"))
    refused = _register(store, statement_full="定理：自足的证明（不带稿，判据夹具）。",
                        proof_text=lone)
    assert refused.get("ok") is False, refused
    assert refused.get("kind") == "proof_manuscript_required", refused
    assert str(refused.get("error") or "").strip(), refused
    assert len(store.rows("statements")) == before, store.rows("statements")
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


class _Call:
    """`llmseam.SeamCall` 的替身：`judge()` 只读 ok / problem / detail。"""

    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _VSecretarySeam:
    """V 的秘书那一档的假缝（`ask_json` 形状）：只回答发签与回复分档两问。

    业主 2026-10-29：第 1、2 次「成立」不落签 ⇒ 这一条链要签上就必须过秘书那一关，
    而秘书的判定是模型调用。夹具按 `note` 分档回预置结论：
    `v_reply_defect` ⇒ 没问题（不然这一签不计入连续）、`sign_issuance` ⇒ 签发。
    """

    wired = True

    def __init__(self) -> None:
        self.seen: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        self.seen.append(str(note))
        kind = str(note).split(":", 1)[-1]
        answers = {"v_reply_defect": {"decision": "没问题", "reason": "夹具：读不出缺陷"},
                   "sign_issuance": {"decision": "签发", "reason": "夹具：连续次数够了"}}
        return dict(answers.get(kind, {})), _Call()


def _v_secretary(store: Store):
    """V 的秘书（带判断面）：`secretary_decides` 那条路走的就是它。"""
    from agentflow import secretary as SEC

    return SEC.Secretary("V", root=store.root, store=store,
                         seam=_VSecretarySeam(), enable_model=True)


def test_the_whole_chain_f_write_d_carry_b_read_v_sign(
        tmp_path: pathlib.Path) -> None:
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
    man_path = pathlib.Path(store.root) / str(out["manuscript_path"])
    assert man_path.is_file(), out

    # 2026-11-02 准入闸（默认 strict）之后的真实次序（两阶段）：
    #   ① 命题行 + 依赖面先落（正文空着 —— 闸只拦"要写进台账的证明正文"）；
    #   ② V 读这份依赖面核引用、对"要写进去的那一份正文"签字；
    #   ③ B 再交那份正文（此时已有签）。
    # 为此先把 F 稿里的证明段正文搬走、只留依赖段 —— 不然 B 的读稿那一支会把
    # 正文一并取来，撞上"无签不许写"。搬走的是「稿里的那一份」，正文本身留在
    # `PROOF_BODY` 里，第 ③ 步照原样交给 B。
    text = man_path.read_text(encoding="utf-8")
    PROOF_BODY = DS.proof_body(text).strip("\n")
    assert PROOF_BODY, text
    man_path.write_text(
        re.sub(r"(## 证明\n)(.*?)(\n## )", r"\1\n\3", text, flags=re.S),
        encoding="utf-8")

    # D 交研究手稿（携带单里应该有 F 那一条）
    report = _d_report(store)
    carried = DS.carried_manuscripts(report)
    assert [r["statement_id"] for r in carried["rows"]] == [f_stmt], carried

    got = _register(store, statement_full="定理：研究手稿引用了 F 的证明手稿（整条链）。",
                    proof_text="",
                    derived_from=[f_stmt])
    assert got.get("ok") is True, got
    assert str(got.get("manuscript_source")) == SRC_CARRIED, got
    b_stmt = str(got["stmt_id"])
    # 只核 B 新登记那一条的依赖面：F 那一轮现在也经 B 的登记落自己的依赖边
    # （D8：命题只经 B 的 `register_statement` 写），所以整张表里会有两组。
    rows = [r for r in _deps(store) if str(r.get("used_by")) == f"stmt:{b_stmt}"]
    assert len(rows) >= 1, _deps(store)
    assert {int(r["path_group"]) for r in rows} == {1}, rows
    assert {str(r["source_stmt_id"]) for r in rows} == {THEOREM_A, THEOREM_B}, rows
    # 正文还是空的 ⇒ 这一格读成 `not_applicable`（"证明里一条引用都没有"无从谈起）；
    # 第 ③ 步把正文交进来之后它才该读成 `present`（见下面 late 那一段）。

    # V 读同一份依赖面核引用并签字（签的是"这一份要写进台账的正文"）
    reply = json.dumps({"verdict": "成立", "defect_step": None, "why": "",
                        "findings": [], "citation_checks": [
                            {"stmt_id": THEOREM_A, "verdict": "consistent",
                             "quote_verbatim": False, "note": "由定理甲那一步，用法一致"},
                            {"stmt_id": THEOREM_B, "verdict": "consistent",
                             "quote_verbatim": False, "note": "由定理乙那一步，用法一致"}]},
                       ensure_ascii=False)
    v_llm = _VSeam(reply)
    v = AgentV(store, workspace_root=store.root, llm=v_llm,
               secretary=_v_secretary(store))
    # 2026-11-04（业主裁定 甲）：在册命题的 V 审必须带手稿（签块 / `## 依赖` /
    # 按号寻址三样只在文件上）。上面第 ① 步为了"正文空着"把 F 稿的证明段搬走了，
    # 所以这里按这条命题的号落一份可签的载体（正文就是第 ③ 步要交的那一份、
    # 依赖段用正文自己的那一张三列表 —— 2026-11-06 起 V 会逐条核"表与正文
    # 一致"，空表配一份引了号的正文是缺陷，不是声明）。判据一个字没改：它读的
    # 仍是"这一份正文的三转"。
    b_man_rel = f"{MANUSCRIPT_DIR}/f-proof-{b_stmt}.md"
    _b_man = pathlib.Path(store.root) / b_man_rel
    _dep_rows = DS.parse_dependency_section(text).get("rows") or []
    _b_man.write_text(
        "# F 的证明手稿（整条链夹具）\n\n"
        f"- 命题号：stmt:{b_stmt}\n\n"
        f"## 命题\n\n定理：研究手稿引用了 F 的证明手稿（整条链）。\n\n"
        f"## 证明\n\n{PROOF_BODY}\n\n"
        + DS.render_dependency_section(_dep_rows),
        encoding="utf-8")
    # 2026-11-08（V 只对手稿负责）：可引资格从被引命题自己的手稿签块读 ——
    # 整条链里这两条定理也要各有一份按号手稿与一块 3/3 的签（与真机 F 的稿同形）。
    from _proof_manuscript_fixture import write_proof_manuscript
    from agentflow import vsigns as _VS

    for _sid in (THEOREM_A, THEOREM_B):
        _body = _PROOF_TEXT.format(sid=_sid)
        _rel = write_proof_manuscript(
            store.root, _sid, _body,
            statement_full=f"命题 {_sid} 的完整正文（含假设）。")
        _raw = (pathlib.Path(store.root) / _rel).read_text(encoding="utf-8")
        _stamped = _VS.stamp_manuscript_sign(
            _raw, proof_sha=VR.text_sha(_body), streak=3, need=3, verdict="成立",
            signer="secretary:F", at=S.now_iso(),
            ledger=f"verifications/{_sid}.jsonl#v-000001",
            statement_id=_sid, manuscript_id=_sid)
        (pathlib.Path(store.root) / _rel).write_text(_stamped, encoding="utf-8")
    # 业主 2026-10-29：第 1、2 次「成立」只落台账、不翻位 ⇒ 正控要断"前几转不签"；
    # 2026-10-30 起那几次落在同一次调用的多转里（V 判没问题后连续再判，不是 F 三交）
    # ⇒ 逐转读数从 `review_passes` 读，"连续之后才签"这条口径本身没变。
    from agentflow import conductor as _CND

    with _CND.calling_as("t-v-000001", "V", parent_task_id="t-b-000001",
                         parent_role="F"):
        signed = v.verify_proof(b_stmt, proof_text=PROOF_BODY,
                                proof_manuscript=b_man_rel)
    assert signed.get("checked") is True, signed
    v_passes = signed.get("review_passes") or []
    assert len(v_passes) == int(VR.SIGN_STREAK_NEED), v_passes
    assert [p.get("issued") for p in v_passes] == [False] * (len(v_passes) - 1) + [True], (
        "逐转的发签读数不是「前几转只落台账、最后一转才签」："
        f"{[p.get('issued') for p in v_passes]}", signed)
    # 2026-11-08：V 的签落在稿上（侧文件 + 九格块）；命题行的第 3 位归 B 收录时认领，
    # 所以 `signed_bit3` 恒 False、`writeback.written` 也恒 False（没有命题位可翻）。
    assert signed.get("signed_bit3") is False, signed
    assert signed.get("review_write", {}).get("manuscript_signed") is True, (
        signed["review_write"])
    assert signed.get("review_write", {}).get("written") is False, signed["review_write"]
    assert {c["stmt_id"] for c in signed.get("citation_checks") or []} == {
        THEOREM_A, THEOREM_B}, signed.get("citation_checks")
    assert v_llm.prompts, "V 没有被问过"
    prompt = v_llm.prompts[-1]
    assert "## 引用核实" in prompt, prompt[-2500:]
    assert THEOREM_A in prompt and THEOREM_B in prompt, prompt[-2500:]
    # 签住之后 B 才把这一份正文写进台账（准入闸要的就是这一份正文的签）。
    # 2026-11-10：B 收录按F 的稿（显式 `proof_manuscript`，任务书 ③ 的口径）——
    # 携带单只递地址与 sha，签过的那一份就是上面这一张可签载体。
    late = _register(store, statement_full="定理：研究手稿引用了 F 的证明手稿（整条链）。",
                     proof_text=PROOF_BODY, derived_from=[f_stmt],
                     proof_manuscript=b_man_rel)
    assert late.get("ok") is True, late
    assert str(late.get("stmt_id")) == b_stmt, late
    # 2026-11-03 件二：V 签的时候命题行没有正文 ⇒ 位没翻；B 把正文写进来之后
    # 按正文 sha 认领那一签（`bits_after_sign`），第 3 位这时才亮。
    _lain = next(dict(r) for r in store.rows("statements")
                 if str(r.get("stmt_id") or "") == b_stmt)
    # 2026-11-03 件二：位是否翻由 B 的写入口按正文 sha 认领；这一条不是位判据。
    # 依赖面在第 ① 步已经落了（上面那组 rows 断言）；这一笔只补正文，不再重记。
    # 盘上两行：依赖行落在 B 那条命题上，verifications 里那一签是「成立」且签住第 3 位
    ledger, problems = VR.list_verifications(store.root, statement_id=b_stmt, limit=None)
    assert problems == [], problems
    assert ledger, "verifications 台账里一行都没有"
    assert str(ledger[-1].get("verdict")) == "成立", ledger[-1]
    # 签住第 3 位必须带上连续读数一起判：不给读数 ⇒ fail-closed（不许默认放行）。
    assert VR.signs_bit3(ledger[-1]) is False, (
        "没有连续读数也判签住了（那是「一次成立就签」的旧口径）", ledger[-1])
    holds = VR.consecutive_holds(store.root, b_stmt)
    assert holds.get("checked") is True and holds.get("streak") == 3, holds
    assert VR.signs_bit3(ledger[-1], streak=holds) is True, ledger[-1]


# ------------------------------------------------------------------ d 反真空

def test_regressing_the_write_order_turns_a_red(store: Store, monkeypatch) -> None:
    """d-1 反真空：把写稿时机退回"登记之后" ⇒ a（D 携带）的判据必红。

    打桩两处（合起来就是改前那一套时序）：① `proof_manuscript` 第一次调用不落盘
    （登记那一刻盘上没有稿）；② `publish_manuscript` 不改名（登记之后也不按命号落）。
    于是"登记那一刻稿已在盘上"这条判据（`_a0_holds`）必红。

    2026-11-07（解耦落地）之后，退回这个时序不再让携带单空掉：登记条目本身
    就是那份手稿（框架写），所以 D 带的是一行"还没拿到命题号"的条目（`mss:<稿号>`，
    地址 + 正文 sha 都在）。反真空的强度改由两处守住：a0 仍然红（时序真的退了），
    而这一行必须真的可被认领（V 签之后 B 按正文 sha 认领它、落到一个真命题号上）。
    """
    _library(store)
    real_write = AgentF.proof_manuscript
    state = {"calls": 0}

    def late_write(self, product, *, sg, manuscript_id="", plan):
        state["calls"] += 1
        got = real_write(self, product, sg=sg, manuscript_id=manuscript_id, plan=plan)
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
    # ---- 2026-11-07 新契约：D 手上有一份"登记条目"可带，而它还没拿到命题号 --------
    #
    # 解耦之后"手稿文件就是登记条目"（`proofregistry` 的模块说明第 1 条）：登记这一笔
    # 由框架把稿写到规范路径上，所以即便 F 自己那一笔写稿被退回登记之后，盘上仍有一份
    # 带登记元信息的稿。携带单因此不是空的 —— 它是新契约里那一行"未落号"的条目。
    # 强度：这一行必须带地址 + 正文 sha（B 认领靠的就是它），且同一份稿只许上一行
    # （`stmt:` 与 `mss:` 两行指着同一个路径 + 同一个 sha ⇒ 那是重列，不是携带）。
    carried = DS.carried_manuscripts(_d_report(store))
    rows = carried["rows"]
    # 2026-11-10：写稿被退回之后盘上是"一份未登记的 F 稿"（`publish_manuscript`
    # 已停用改名 ⇒ 它不叫命题号）。携带单因此带它一次、键是 `mss:<稿号>`：这正是
    # 解耦落地后的新契约（地址 + 正文 sha 都在，B 认领靠的就是这两格）。
    # 强度：同一份稿只许上一行（`stmt:` 与 `mss:` 两行指着同一路径同一 sha = 重列）。
    carried = DS.carried_manuscripts(_d_report(store))
    rows = carried["rows"]
    assert len(rows) == 1, rows
    term = rows[0]
    assert term["statement_id"] == "", term
    assert term["manuscript_id"] == str(out.get("manuscript_id") or ""), (term, out)
    assert term["path"] == f"{MANUSCRIPT_DIR}/f-proof-{out['manuscript_id']}.md", term
    assert len(str(term["sha256"])) == 64, term
    # 2026-11-10：旧口径里"未落号的条目在 V 签之后被认领"那一格钉的是 `publish_manuscript`
    # 按命题号改名留下的那一份稿；改名停用之后它没有对象，已删。认签按正文 sha 那一条
    # 判据在本文件前面（`test_the_delivery_really_hands_the_manuscript_to_b` /
    # `test_the_whole_chain...`）与 `tests/test_v_unregistered_manuscript_review.py`
    # 各自钉着，强度不靠这一格。这一条剩下的部分只量写稿时序的反真空（a0 必红）。


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
    """d-3 反真空：把"读 D 的携带单"打桩成永远读不到 ⇒ a 必红。

    ## 旧逐字（改前，已作废）

    打掉携带单之后，兜底读盘读到 F 那一轮落下的
    `reports/f-proof-<F 的命题号>.md`，`manuscript_source=disk`、`dependencies` 落
    `THEOREM_A` 那一条。

    ## 为什么旧期望不对（2026-11-05 业主裁定：D1 严格版）

    那一份稿的号是 F 的命题号（不是这一条新命题的），它 `## 依赖` 表写的是 F 引了谁；
    落到新命题头上就是一条作者从未写过的边。旧期望把"打掉主路 ⇒ 退到兜底"当成必须，
    但兜底只能读本行自己的稿；本行还没在册（没有号）时没有"自己的稿"可读。

    ## 新逐字

    同一现场 ⇒ `ok=false`、`kind=dependency_section_missing`、`manuscript_source=none`、
    `_carried_holds(...) is False`、`dependencies` 0 行。
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
    body = f"1. 由 F 的稿直接得到（见 stmt:{out['statement_id']}）。"
    sign_before_registration(store.root, proof_text=body)
    got = _register(store, statement_full="定理：携带单被打桩（判据夹具）。",
                    proof_text=body,
                    derived_from=[str(out["statement_id"])])
    assert str(got.get("manuscript_source")) == SRC_NONE, got
    assert got.get("ok") is False, got
    assert got.get("kind") == DS.REFUSED_SECTION_MISSING, got
    assert _carried_holds(got, store, cited=THEOREM_A) is False, got
    assert _deps(store) == [], _deps(store)


# ------------------------------------------------------------------ f 内容寻址兜底（2026-11-04）
#
# 判据 f：盘上只有计划号命名的那一份稿（87 的真机形态：按号命名的 0 份），
# 而这一笔把证明正文一起交进来 ⇒ B 的兜底读盘按 `## 证明` 的内容认出它、依赖面落行。
# 反真空 f-：把那一个实参摘掉（`read_manuscript` 收不到正文）⇒ 回到改前形态
# （整笔受控拒绝 `dependency_section_missing`、`dependencies` 0 行）。

#: 计划号那份稿里的证明正文 —— 与登记时交的 `proof_text` 逐字相同（内容认法的前提）。
_PLAN_MANUSCRIPT_PROOF = f"1. 由定理甲直接得到（依据：stmt:{THEOREM_A}）。"


def _plan_named_manuscript() -> str:
    """F 在拿到命题号之前写的那一份稿（页头 + 命题 + 证明 + 依赖三列，且已洗过）。"""
    text = (
        "# F 的证明手稿：由定理甲推出目标结论（判据夹具）\n\n"
        "- 命题号：stmt:（还没落号）\n"
        "- 计划：000009 · 子目标：L1\n\n"
        "## 命题\n\n"
        "由定理甲推出目标结论。\n\n"
        "## 证明\n\n"
        f"{_PLAN_MANUSCRIPT_PROOF}\n\n"
        + _DEP_TABLE.format(quote="由定理甲，G 有 p 阶元", sid=THEOREM_A))
    return DS.mark_washed(text, actor="secretary-F")


def _write_plan_manuscript(store: Store,
                           name: str = "f-proof-plan-000009.md") -> pathlib.Path:
    d = pathlib.Path(store.root) / MANUSCRIPT_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    path.write_text(_plan_named_manuscript(), encoding="utf-8")
    return path


def test_f_a_plan_named_manuscript_is_recognised_by_its_proof_body(
        tmp_path: pathlib.Path) -> None:
    """f：只有 `f-proof-plan-*.md` 时，兜底按证明正文认出它，依赖面落行。

    改前红：改前 `read_manuscript` 只查 `f-proof-<命题号>.md`（`tried` 里只有那一处），
    而 87 里按号命名的稿 0 份 ⇒ 这一笔整笔拒 `dependency_section_missing`、0 行。

    2026-11-04（业主裁定 甲）：这一笔要写的正文要先有一份手稿签 ⇒ 先落一份 pending 签。
    签名载体不叫 `f-proof-plan-*`（内容认法的扫描面只有那一族），所以兜底读盘仍然
    命中下面这份计划名稿：`probe.matched_by=proof_body` 的断言一个字没改。
    """
    store = _ws(tmp_path)
    _library(store)
    _write_plan_manuscript(store)
    sign_before_registration(store.root, proof_text=_PLAN_MANUSCRIPT_PROOF)
    got = _register(store, statement_full="定理：由定理甲推出目标结论（计划名稿）。",
                    proof_text=_PLAN_MANUSCRIPT_PROOF, derived_from=[THEOREM_A])
    assert got.get("ok") is True, got
    assert str(got.get("manuscript_source")) == SRC_DISK, got
    probe = dict((got.get("deps_missing") or {}).get("manuscript_probe") or {})
    assert probe.get("matched_by") == DS.MATCH_BY_PROOF_BODY, probe
    assert str(probe.get("path")) == f"{MANUSCRIPT_DIR}/f-proof-plan-000009.md", probe
    # 两种认法在 `tried` 里分开写：名字那一路 miss、正文那一路命中。
    assert [t.get("matched_by") for t in probe.get("tried") or []] == [
        DS.MATCH_BY_PATH, DS.MATCH_BY_PROOF_BODY], probe
    assert {str(r.get("source_stmt_id")) for r in _deps(store)} == {THEOREM_A}, _deps(store)


def test_f_without_the_proof_text_the_backfill_cannot_find_it(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """f- 反真空：把"把正文交给兜底读盘"这一个实参摘掉 ⇒ 回到改前形态（0 行 / 整笔拒）。

    2026-11-04（业主裁定 甲）：先给这一笔要写的正文落一份 pending 签（按正文 sha 认领），
    否则红的是"没带稿"而不是"内容认不出"——那这条反真空就没接到它要测的那根线上。
    """
    store = _ws(tmp_path)
    _library(store)
    _write_plan_manuscript(store)
    sign_before_registration(store.root, proof_text=_PLAN_MANUSCRIPT_PROOF)
    real = DS.read_manuscript

    def _without_proof_text(root, *, statement_ids=(), plan_id="", proof_text=""):
        # 模拟"那一行实参没接上"的调用（改前 B 的形态）：正文收不到，只能按名字找。
        return real(root, statement_ids=statement_ids, plan_id=plan_id)

    monkeypatch.setattr(DS, "read_manuscript", _without_proof_text)
    got = _register(store, statement_full="定理：由定理甲推出目标结论（反真空）。",
                    proof_text=_PLAN_MANUSCRIPT_PROOF, derived_from=[THEOREM_A])
    assert got.get("ok") is False, got
    assert str(got.get("kind") or "") == "dependency_section_missing", got
    assert _deps(store) == [], _deps(store)


def test_f_a_different_proof_is_never_counted_as_this_one(tmp_path: pathlib.Path) -> None:
    """f 的负控：盘上那份计划名稿的证明正文与这一笔不同 ⇒ 不许认（认了就是挂错依赖面）。

    这一条守的正是"不许按 glob 取最新"：一份计划会被每一轮覆盖，内容对不上时
    唯一的正确读法是 `source=none`（B 随后受控拒绝），不许猜。
    """
    store = _ws(tmp_path)
    _library(store)
    _write_plan_manuscript(store)
    hit = DS.read_manuscript(store.root, statement_ids=[THEOREM_A],
                             proof_text="1. 这是另一份证明（与盘上那份不同）。")
    assert hit["source"] == SRC_NONE, hit
    assert hit["matched_by"] == "", hit
    assert any(t.get("matched_by") == DS.MATCH_BY_PROOF_BODY for t in hit["tried"]), hit
    assert "按证明正文比过" in str(hit["why"]), hit





