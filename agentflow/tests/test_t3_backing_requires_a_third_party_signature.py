# -*- coding: utf-8 -*-
"""判据：收工门的穷举支路必须核 V 对那份 E 报告的真签（业主 2026-11-03 裁定）。

## 业主的原话（逐字要点）

> 「穷举式数值实验是可以作为 proof 级背书的，V 要签实验的理论论证部分（E 的那个报告）」

## 这一组守什么

`closing._has_t3` 的穷举支路改前只读 `numericproof.is_signed_exhaustion(exp)`，而那一格读的
`signed_by="V"` 是 E 在 `sign_experiment` 里自己写上去的一格自述（`signer_of` 是无分支
常量、写侧没有 `root`/`store` ⇒ 结构上不可能校验 V）。于是"V 签过"与"V 判了有毛病"在收工门上
长得一模一样（真机：`projects/paper-rewrite-78` 的 `exp:000058` 判了「有毛病」、`exp:000078`
压根没审过，两条都曾被当成可背书）。

现在这一支调 `numericproof.exhaustion_backing`（与 B 的入库闸同一份判据）：V 的台账里存在一行、
`object_sha256` == 这份 E 报告的 sha、verdict=成立、且签的就是现在这一份 ⇒ 才给背书。
四种结局各有各的理由（处置人不同）：

| # | 结局 | 夹具怎么造 | 判据 |
|---|---|---|---|
| ① | 成立且 sha 一致 | E 真跑穷举 → 落报告 → 登记猜想 → 真 V 会审签「成立」 | 门 `pass`，读数 `states.signed == 1` |
| ② | 判「有毛病」 | 同上，但程序里有剪枝（`visited`）而 ③ 一个字没解释 ⇒ 真 V 判「有毛病」 | 门 `fail`，理由点名第 4 步与那句原话 |
| ③ | 从没审过 | 同上，但不派 V | 门 `fail`，理由写「没审过」（不是「审过、没毛病」） |
| ④ | 签的是旧版 | ①之后 E 重写报告（②③ 原文不变、读数变了）⇒ 对象 sha 换了 | 门 `fail`，理由写「旧版」「对不上」 |
| ⑤ | 反真空 | 把 `exhaustion_backing` 打桩成恒「签住了」 | ②③④ 必须当场红（否则那三条的绿可能来自"判据根本没跑"） |

夹具全部在 `tmp_path` 里自建工作区：真 `Store` / 真 `AgentE` / 真 `AgentV` / 真 `Secretary`
（`enable_model=False`）⇒ 一个模型调用都不发。台账行由 V 自己的写入口
（`verify_proof` → `record_verification`）落下，不是手写的。
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import add_literature, e_form_gate_ok, sync_counters  # noqa: E402
from _proof_manuscript_fixture import write_proof_manuscript  # noqa: E402
from agentflow import closing as CL  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import settings as SET  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.store import Store  # noqa: E402
from conftest import ensure_basis_lit, ensure_basis_stmt

TS = "2026-11-03T00:00:00+08:00"
SCRIPT_REL = "code/enum_ramsey34.py"
BODY = "对任意正整数 n，R(3,4)=9。"

#: 一个真的穷举脚本：搜索空间的数字在"报数之前"的代码段里有着落（V 的会审第 3 项要核它），
#: 代码里没有剪枝/对称性构造 ⇒ 第 4 项与报告一致（都"没做过剪枝"）⇒ 会审判「成立」。
EXHAUSTIVE_PROBE = '''
import json
N = 9
SPACE = 2 ** 36
TOTAL = 68719476736
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把 R(3,4)=9 的上界归约成 K_9 的二染色穷举：按 4-子集布尔赋值编码逐点检查",
        "enumeration": ("枚举 K_9 全部 2^36 个二染色；每个染色都落在枚举里，无一遗漏；"
                        "边界：n=9 是上界侧的全部"),
        "search_space": {"graph": "K_9", "colourings": 68719476736},
    },
    "counterexample": None, "negation_kind": "not_proved",
    "bound": {"n": 9}, "strategy": "全量枚举",
}))
'''

#: 同一个穷举，但程序里做了剪枝（`visited`）而 ③ 一个字没解释 ⇒ 真 V 判「有毛病」第 4 步。
#: 这就是 `projects/paper-rewrite-78/exp:000058` 的形态（那一签的 `defect_step=4`）。
DEFECTIVE_PROBE = '''
import json
N = 9
SPACE = 2 ** 36
TOTAL = 68719476736
visited = set()
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把 R(3,4)=9 的上界归约成 K_9 的二染色穷举：按 4-子集布尔赋值编码逐点检查",
        "enumeration": ("枚举 K_9 全部 2^36 个二染色；每个染色都落在枚举里，无一遗漏；"
                        "边界：n=9 是上界侧的全部"),
        "search_space": {"graph": "K_9", "colourings": 68719476736},
    },
    "counterexample": None, "negation_kind": "not_proved",
    "bound": {"n": 9}, "strategy": "全量枚举",
}))
'''


# ------------------------------------------------------------------ 夹具

def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _write(store: Store, rel: str, body: str) -> str:
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel


def _run_exhaustive(store: Store, *, probe: str = EXHAUSTIVE_PROBE) -> dict:
    """E 真跑一次穷举实验，并把 ②③ 落到盘上（这一步之后那条实验才是 proof）。"""
    _write(store, SCRIPT_REL, probe)
    out = e_form_gate_ok(AgentE(store, config={}, workspace_root=store.root)).run_experiment(
        "R(3,4)=9（K_9 的二染色穷举）", "ramsey34=9", SCRIPT_REL, method="numeric")
    row = [r for r in store.rows("experiments") if r["experiment_id"] == out["experiment_id"]][0]
    return _land_and_resign(store, row)


def _land_and_resign(store: Store, row: dict, *, result: Any = None) -> dict:
    """E 的 ②③ 落盘（`exhaustionreport.land_report`）＋ 按落盘事实重新签一次。

    走的是 E 自己那两个写入口（`land_report` / `sign_experiment`），不手写签名格。
    """
    sig = NP.signature_of(row)
    facts = ER.land_report(
        store.root, experiment_id=row["experiment_id"], claim=row.get("claim"),
        claim_key=row.get("claim_key"), script_path=row.get("code_path"),
        script_sha256=row.get("code_hash"), design=sig.get("design"),
        enumeration=sig.get("enumeration"), search_space=sig.get("search_space"),
        result=result if result is not None else row.get("result"),
        evidence_kind=row.get("evidence_kind"))
    obs = dict(row.get("observations") or {})
    obs[ER.REPORT_KEY] = facts
    redo = NP.sign_experiment(
        method=row["method"],
        derived={"result": result if result is not None else row.get("result"),
                 "evidence_kind": row.get("evidence_kind"),
                 "negation_kind": row.get("negation_kind"), "observations": obs},
        code_path=row.get("code_path"), code_hash=row.get("code_hash"),
        certificate=row.get("certificate"), search_bound=row.get("search_bound") or {},
        experiment_id=row["experiment_id"])
    new_row = dict(row, evidence_kind=redo["evidence_kind"], observations=redo["observations"])
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", new_row, note="e-sign")
    sync_counters(store)
    return new_row


def _file_conjecture(store: Store, column: str) -> dict:
    """先按猜想落库（V 只审在册的命题；升定理级是签完之后的事）。"""
    return AgentB(store, extractor=None, extract_text=None).register_statement(
# 2026-11-17（业主裁定 ②）：own_result 必须写清来路；这一份夹具不测承重链，用形状合法的占位号。
        origin="own_result", source_lit_id=ensure_basis_lit(store), kind="conjecture", label="R(3,4)=9", statement_full=BODY,
        statement_text=BODY[:40], proof_text=column, evidence_kind="cross_check",
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导，没有第二份文本可比对")


def _e_manuscript(store: Store, row: dict, column: str) -> str:
    """E 的按号证明手稿 `reports/e-proof-<实验号>.md`：V 在册送审的载体。

    2026-11-04（业主裁定 甲）：在册命题送审必须带手稿（签块 / `## 依赖` / 按号寻址
    三样只在文件上）。穷举这一档的真机载体就是 E 自己那一趟落的这一份；这里用共享
    夹具落同样的三节内容、再按 E 的命名写一份（`## 证明` 与证明栏逐字一致、
    `## 依赖` 空表声明）。判据一个字没改：台账行那两格仍按真签核。
    """
    eid = str(row.get("experiment_id") or "")
    rel_f = write_proof_manuscript(store.root, eid or "000000", column)
    src = pathlib.Path(store.root) / rel_f
    rel = f"reports/e-proof-{eid}.md"
    (pathlib.Path(store.root) / rel).write_text(
        DS.mark_washed(src.read_text(encoding="utf-8"), actor="secretary-E"),
        encoding="utf-8")
    src.unlink()
    return rel


def _v(store: Store) -> AgentV:
    """真 V ＋ 真秘书（`enable_model=False` ⇒ 判不了发签，但台账行是 V 自己落的）。"""
    sec = SEC.Secretary("V", root=pathlib.Path(store.root), store=store, enable_model=False)
    return AgentV(store, workspace_root=store.root, secretary=sec)


def _gate(store: Store, eid: str) -> Any:
    """只跑承重那一格：正文里一条 `evidence_kind="proof"` 的断言引到 `exp:<eid>`。"""
    doc = S.Document(doc_id=S.format_id(0), kind="paper", title="未发表的论文",
                     status="in_review",
                     claims=[{"claim_id": "c1", "text": "已证明 R(3,4)=9",
                              "citations": [f"exp:{eid}"], "evidence_kind": "proof",
                              "section": "§2"}],
                     created_at=TS)
    doc.validate()
    with store.tx("documents", actor="test") as tx:
        tx.upsert("documents", doc.to_dict())
    return CL.check_closing(store, checks=("load_bearing",), project_dir="", report_path="")


def _backing_reading(rep: Any) -> dict:
    return dict((rep.readings.get("load_bearing") or {}).get("exhaustion_backing") or {})


def _reasons(rep: Any) -> str:
    """门那一条 blocker 的原文（理由必须落在这一句上 —— 读数没人看的时候只有它进上下文）。"""
    return " ".join(str(f.detail) for f in rep.findings
                    if f.code == "load_bearing_without_t3")


# ------------------------------------------------------------------ ① 成立且 sha 一致

def _world(tmp_path: pathlib.Path, *, probe: str = EXHAUSTIVE_PROBE) -> tuple[Store, dict]:
    st = _store(tmp_path)
    add_literature(st, S.format_id(0))
    return st, _run_exhaustive(st, probe=probe)


def test_1_a_signature_on_the_current_report_backs_the_claim(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """① V 签「成立」且签的就是现在这一份报告 ⇒ 给背书（门 `pass`）。

    这是业主裁定允许的那一档：穷举式数值实验可以给承重结论背书，V 签的是 E 报告的
    理论论证部分。判据同时钉住"那一签真的钉了对象"：台账行上 `object_sha256` 是 64 位、
    等于行上记的报告 sha（不是 E 自己盖在 `e_signature` 里的章）。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    st, row = _world(tmp_path)
    column = NP.proof_column(row)
    assert NP.is_signed_exhaustion(row), row
    filed = _file_conjecture(st, column)
    assert filed.get("ok") is True, filed
    signed = _v(st).verify_proof(str(filed["stmt_id"]), proof_text=column,
                                 proof_manuscript=_e_manuscript(st, row, column))
    assert signed.get("checked") is True and signed.get("verdict") == "成立", signed
    assert signed.get("kind") == "numeric_evidence", signed

    # 判据读数：V 的台账行钉住了 E 那份报告的对象 sha（不是"E 自签"那一格）。
    reading = NP.exhaustion_backing(row, root=st.root, statements=st.rows("statements"))
    assert reading["state"] == NP.EXHAUSTION_BACKING_SIGNED, reading
    assert reading["backed"] is True and reading["problems"] == [], reading
    assert len(reading["report_sha256"]) == 64, reading
    lrows, bad = VR.list_verifications(st.root, statement_id=str(filed["stmt_id"]), limit=None)
    assert bad == [] and lrows, (bad, lrows)
    assert str(lrows[-1].get("object_sha256") or "") == reading["report_sha256"], lrows[-1]
    assert str(lrows[-1].get("object_path") or "") == reading["report_path"], lrows[-1]

    # 门：pass，且读数里记的是"签住了"。
    rep = _gate(st, row["experiment_id"])
    assert rep.status["load_bearing"] == "pass", rep.to_dict()
    assert _backing_reading(rep)["states"]["signed"] == 1, _backing_reading(rep)


# ------------------------------------------------------------------ ② 有毛病

def _assert_defective_cannot_back(tmp_path: pathlib.Path) -> None:
    """② 的正文（被 ⑤ 打桩之后必须红的那一段）。"""
    st, row = _world(tmp_path, probe=DEFECTIVE_PROBE)
    column = NP.proof_column(row)
    filed = _file_conjecture(st, column)
    assert filed.get("ok") is True, filed
    reviewed = _v(st).verify_proof(str(filed["stmt_id"]), proof_text=column,
                                   proof_manuscript=_e_manuscript(st, row, column))
    assert reviewed.get("checked") is True, reviewed
    assert reviewed.get("verdict") == "有毛病", reviewed
    assert reviewed.get("defect_step") == 4, reviewed

    reading = NP.exhaustion_backing(row, root=st.root, statements=st.rows("statements"))
    assert reading["state"] == NP.EXHAUSTION_BACKING_DEFECTIVE, reading
    assert reading["backed"] is False, reading
    assert reading["defect_step"] == 4, reading
    assert "第 4 步" in reading["why"], reading["why"]

    rep = _gate(st, row["experiment_id"])
    assert rep.status["load_bearing"] == "fail", rep.to_dict()
    text = _reasons(rep)
    assert "第 4 步" in text, text
    assert "有毛病" in text, text
    assert _backing_reading(rep)["states"]["defective"] == 1, _backing_reading(rep)
    # 去重（`draft/154` §三）：这一行已经被承重门逐条点名 ⇒ 那条 warning 不许再说第二遍。
    assert "suspect_self_signed" not in {f.code for f in rep.findings}, (
        f"承重门已经点名 exp:{row['experiment_id']}，warning 又报了一遍："
        f"{[f.code for f in rep.findings]}")


def test_2_a_defect_verdict_does_not_back_and_names_the_step(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """② V 判「有毛病」⇒ 不给背书，reason 写上 defect_step（第 4 步：剪枝没解释）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    _assert_defective_cannot_back(tmp_path)


# ------------------------------------------------------------------ ③ 从没审过

def _assert_unsigned_cannot_back(tmp_path: pathlib.Path) -> None:
    """③ 的正文（被 ⑤ 打桩之后必须红的那一段）。"""
    st, row = _world(tmp_path)
    # 不派 V：`verifications/` 目录根本不存在（真机 r34c/r34d 的形态）。
    assert not (pathlib.Path(st.root) / VR.VERIFICATIONS_DIR).exists()
    reading = NP.exhaustion_backing(row, root=st.root, statements=st.rows("statements"))
    assert reading["state"] == NP.EXHAUSTION_BACKING_UNSIGNED, reading
    assert reading["backed"] is False and reading["problems"], reading
    assert "没审过" in reading["why"], reading["why"]
    # 不许把"没查"读成"清白"：从没审过时台账上没有任何判决可引（verdict 空、defect_step 空）。
    assert reading["verdict"] == "" and reading["defect_step"] is None, reading

    rep = _gate(st, row["experiment_id"])
    assert rep.status["load_bearing"] == "fail", rep.to_dict()
    assert "没审过" in _reasons(rep), _reasons(rep)
    assert _backing_reading(rep)["states"]["unsigned"] == 1, _backing_reading(rep)
    # 去重（`draft/154` §三）：承重门已经点名过它 ⇒ 那条 warning 不再说第二遍。
    assert "suspect_self_signed" not in {f.code for f in rep.findings}, (
        f"承重门已经点名 exp:{row['experiment_id']}，warning 又报了一遍："
        f"{[f.code for f in rep.findings]}")


def test_3_a_report_never_reviewed_is_not_a_report_without_defects(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 从没审过 ⇒ 不给背书，理由写「没审过」（不是「审过、没毛病」）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    _assert_unsigned_cannot_back(tmp_path)


# ------------------------------------------------------------------ ④ 签的是旧版

def _assert_stale_cannot_back(tmp_path: pathlib.Path) -> None:
    """④ 的正文（被 ⑤ 打桩之后必须红的那一段）。"""
    st, row = _world(tmp_path)
    column = NP.proof_column(row)
    filed = _file_conjecture(st, column)
    assert filed.get("ok") is True, filed
    signed = _v(st).verify_proof(str(filed["stmt_id"]), proof_text=column,
                                 proof_manuscript=_e_manuscript(st, row, column))
    assert signed.get("verdict") == "成立", signed

    # E 重写报告：②③ 原文不变（证明栏同一个 sha），但读数变了 ⇒ 对象 sha 换了。
    fresh = [r for r in st.rows("experiments") if r["experiment_id"] == row["experiment_id"]][0]
    outdated = NP.exhaustion_backing(fresh, root=st.root, statements=st.rows("statements"))
    assert outdated["state"] == NP.EXHAUSTION_BACKING_SIGNED, outdated
    redone = _land_and_resign(st, fresh, result="supports（重跑：读数变了）")
    assert NP.proof_column(redone) == column, "②③ 原文变了 ⇒ 这一条夹具测的就不是『旧版对象』"
    reading = NP.exhaustion_backing(redone, root=st.root, statements=st.rows("statements"))
    assert reading["state"] == NP.EXHAUSTION_BACKING_STALE, reading
    assert reading["backed"] is False, reading
    assert reading["report_sha256"] != outdated["report_sha256"], (reading, outdated)
    assert "旧版" in reading["why"], reading["why"]

    rep = _gate(st, row["experiment_id"])
    assert rep.status["load_bearing"] == "fail", rep.to_dict()
    assert "旧版" in _reasons(rep) and "对不上" in _reasons(rep), _reasons(rep)
    assert _backing_reading(rep)["states"]["stale"] == 1, _backing_reading(rep)


def test_4_a_signature_on_the_old_version_is_not_a_signature(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 签的是旧版（对象 sha 对不上）⇒ 不给背书，理由写「签的是旧版报告」。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    _assert_stale_cannot_back(tmp_path)


# ------------------------------------------------------------------ ⑤ 反真空

def _stub_backed(monkeypatch: pytest.MonkeyPatch) -> None:
    """把"V 到底签没签住"这一格打桩成恒「签住了」（形状与真读数同）。"""
    def _fake(experiment: Any, *, root: Any = None, statements: Any = (),
              statement_id: str = "") -> dict[str, Any]:
        return {"checked": True, "state": NP.EXHAUSTION_BACKING_SIGNED, "backed": True,
                "experiment_id": str((experiment or {}).get("experiment_id") or ""),
                "statement_id": str(statement_id or ""), "report_path": "out/x/exhaustion.md",
                "report_sha256": "0" * 64, "verdict": "成立", "defect_step": None,
                "ledger": "verifications/000000.jsonl#v-000001",
                "why": "（打桩：恒签住了）", "problems": []}

    monkeypatch.setattr(NP, "exhaustion_backing", _fake, raising=True)


def test_5_stubbing_the_backing_check_makes_2_3_4_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 反真空：把第三方签检查打桩成恒真 ⇒ ②③④ 必红。

    没有这一条，"四种结局各一条"的绿色可能来自判据根本没跑（比如 `_has_t3` 又退回只读
    `is_signed_exhaustion`）：桩一打，②③④ 的断言必须当场失败。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    _stub_backed(monkeypatch)
    for body in (_assert_defective_cannot_back, _assert_unsigned_cannot_back,
                 _assert_stale_cannot_back):
        with pytest.raises(AssertionError):
            body(tmp_path / body.__name__)


# ------------------------------------------------------------------ ⑥ 去重的另一半

def test_6_an_uncited_row_is_named_exactly_once_by_the_warning(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑥ 没被正文引到的自签穷举行仍然被那条 warning 点名一次（只报不拦）。

    真机存量（`paper-rewrite-78` 的 `000078`、`r34c` 两条、`r34d` 三条，共 6 条 unsigned）
    就是这个形态：承重门碰不到它们（正文里没有 proof 级断言引到它们），所以只由这条 warning
    点名。去重之后恰好一次 —— 既不许因为它不进 blocker 就消失（那是"不报也不拦"），
    也不许在被引到时与承重门那条 finding 各说一遍。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    st, row = _world(tmp_path)
    assert not (pathlib.Path(st.root) / VR.VERIFICATIONS_DIR).exists()
    rep = CL.check_closing(st, checks=("load_bearing",), project_dir="", report_path="")
    assert rep.status["load_bearing"] == "pass", rep.to_dict()
    warnings = [f for f in rep.findings if f.code == "suspect_self_signed"]
    assert len(warnings) == 1, [f.code for f in rep.findings]
    assert row["experiment_id"] in str(warnings[0].detail), warnings[0].detail
    assert "没被正文引到" in str(warnings[0].detail), warnings[0].detail
    assert warnings[0].level != "blocker", warnings[0].level      # 只报不拦
    assert rep.readings["suspect_self_signed"]["states"]["unsigned"] == 1, rep.readings


#: 2026-11-02 准入闸默认 strict 之后，本文件的夹具一律先给"B 即将写进台账的那一份
#: 证明正文"补一签（真签：在册走台账、未在册走 pending）。见 conftest 的同名 fixture。
pytestmark = pytest.mark.usefixtures("signed_v_handoffs")
