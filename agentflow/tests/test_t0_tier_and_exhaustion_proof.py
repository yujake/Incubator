# -*- coding: utf-8 -*-
"""T0 档位 ＋ 穷举 proof ＋ E 签数值证据：业主 2026-10-23 两批裁定的判据（①–⑦）。

## 裁定原文（要点逐字）

> 「B 侧收录命题时被"太平凡"拦截了很多次……请给数值实验直接穷举出来的结论也给专门的收录，
> 可以让秘书不再因"太平凡"拦收录，只是加一个档位叫 T0（和 T1 到 T4 是一个性质），
> T0 叫基础定理或初步结论，T1 重新定位为有一定价值的非平凡结论，T2 到 T4 定位不变。」
> 「如果纯数值实验直接把整个命题证掉了，那也能拿 proof 标识，理由是穷举，签名是对应的
> 程序脚本。一般的理论命题只是拿不完全的数值实验探路的不能靠此拿 proof，只能说有数值实验
> 支持。这些有关数值实验的都由 E 来签。若要入定理证明库，证明栏写程序地址（相对于仓库）。」
> 「数值实验定理的"证明栏"必须由三部分组成：① 程序相对地址（相对仓库）② 程序设计
> （思路：要解决什么、按什么结构搜、为什么覆盖全域）③ 穷举论证（搜索空间多大、怎么算出、
> 对称性/剪枝、为什么不漏、边界怎么处理）。作者分工：② 与 ③ 都由 E 写；B 只负责原样登记，
> 不许自己编 ②③，也不许把 E 的读数改写成自己的话。E 没给 ②③ ⇒ B 不许把这条登记成 proof
> （只能"有数值实验支持"），并在读数里点名缺哪一块。」

## 七条判据（每条都对着一个"改前必红"）

| # | 判据 | 改前为什么红 |
|---|---|---|
| ① | 穷举实验 ⇒ 命题可标 proof、`signed_by=V`、证明栏是脚本三段式 | `schema.Experiment.validate` 一律拒"计算类称 proof" |
| ② | 不完全实验 ⇒ 标不成 proof，只能 `cross_check`（负控） | 没有这个判据；B 可以随手标 proof |
| ③ | 平凡命题 ⇒ 收录成功且档位 T0（不再拒收） | 入库口返回 `statement_too_trivial` 拒收 |
| ④ | T0/T1 文案是业主原话，T2–T4 逐字未变 | 没有 T0；T1 还是"刚过收录门槛" |
| ⑤ | 反真空：把"穷尽判定"打桩成恒真 ⇒ ② 必红；把"懂平凡"打桩成恒平凡 ⇒ ③ 的非平凡支必红 | 判据自身要能红 |
| ⑥ | 只有程序路径、没有 ②③ ⇒ 不许 proof，读数点名缺"程序设计"/"穷举论证" | 没有这一条（只查"非空"就能过） |
| ⑦ | 签字主体是 V、②③ 的作者是 E（`signed_by=="V"` 且 `proof_authors` 含 E）；B 自称作者 / 改写 / 写 `signed_by=E` ⇒ 受控拒绝 | 没有这一条 |
| ⑧ | "形式化"那一格：数值定理填数值程序、理论定理填 `.lean`，互不冒充 | 没有这一条 |
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import add_literature, e_form_gate_ok, sync_counters  # noqa: E402
from _proof_manuscript_fixture import write_proof_manuscript  # noqa: E402
from agentflow import closing  # noqa: E402
from agentflow import conductor as CND  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.agent_loop import AgentLoop  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-10-23T00:00:00+08:00"

#: 一个"穷举"的 E 探针脚本：它报的是三件事实（exhaustive / 搜索空间 / ②③ 两段人话），
#: 等级不由它自己说（业主的裁定把签名权给了 E，而 E 的判据在 `numericproof`）。
EXHAUSTIVE_PROBE = '''
import json
# 搜索空间的数字必须在"计算段"里有着落（V 的会审第 3 项要拿代码核这几个数）：
# 报数那一行自带这些字不算数 —— 会审只拿脚本里排在报数之前的那一段去核。
N = 9
SPACE = 2 ** 36
TOTAL = 68719476736
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把 R(3,4)=9 的上界归约成 K_9 的二染色穷举：按 4-子集布尔赋值编码，逐点检查",
        "enumeration": ("枚举 K_9 全部 2^36 个二染色（36 条边各两色）；先按顶点置换取规范形去掉 9! 重数，"
                        "再按 3-子集/4-子集的对称性剪枝；K_9 的每个染色都落在枚举里，无一遗漏；"
                        "边界：n=9 是上界侧的全部，n<=8 由 witness 覆盖"),
        "search_space": {"graph": "K_9", "colourings": 68719476736}
    },
    "bound": {"n": 9},
    "counterexample": None,
    "negation_kind": "not_proved",
}))
'''

#: 一个"不完全"的探针脚本：只报了扫描点数，没有任何穷尽证据（②③ 与 exhaustive 全缺）。
PARTIAL_PROBE = '''
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {"points": 100000, "grid": 64},
    "counterexample": None,
    "negation_kind": "not_proved",
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


def _e(store: Store) -> AgentE:
    # 本文件测的是 T0 档位与穷举证明的判定链：形态闸那一关钉成"合格"
    # （闸本身由 `test_e_side_proposition_form_gate.py` 覆盖）。
    return e_form_gate_ok(AgentE(store, config={}, workspace_root=store.root))


def _b(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=None)


def _rows(store: Store, table: str) -> list[dict]:
    return list(store.rows(table))


def _report_facts(experiment_id: str = "000004") -> dict:
    """一行"②③ 已落盘"的行上事实（形状与 `exhaustionreport.land_report` 的返回同形）。

    为什么判据里可以合成它：落盘核查有两层 —— 行上的事实（`exhaustion_problems` 读
    路径形态 / 字节数 / sha256 / 三块齐不齐）与盘上再核一次（`disk_problems`，读侧用）。
    单元级判据测的是第一层，所以这里给一份形状正确的事实；"盘上真的在不在"由
    端到端那两条（`_run_exhaustive` 真写 `out/experiments/<号>/exhaustion.md`）守。
    """
    return {"path": f"out/experiments/{experiment_id}/exhaustion.md",
            "bytes": 1832, "sha256": "a" * 64, "ok": True, "problems": [],
            "blocks": {"design": 42, "enumeration": 120, "environment": 30},
            "missing": [], "experiment_id": experiment_id, "at": TS}


def _land_report_and_resign(store: Store, row: dict) -> dict:
    """E 的 ②③ 落盘那一步（`exhaustionreport` 那一侧的活）＋ 按落盘事实重新签一次。

    为什么夹具要显式做这一步：②③ 的落盘是 E 的写侧（`exhaustionreport.land_report`），
    而"落过盘才够 proof"这条判据在 `numericproof.sign_experiment` 里（签名那一刻问一次）。
    于是这里按同一条口径把 E 的读数落成盘上的 `out/experiments/<号>/exhaustion.md`，
    再调同一个签名函数重签 —— 不另写一份"怎么算 proof"的实现。
    """
    from agentflow import exhaustionreport as ER

    sig = NP.signature_of(row)
    facts = ER.land_report(
        store.root, experiment_id=row["experiment_id"], claim=row.get("claim"),
        claim_key=row.get("claim_key"), script_path=row.get("code_path"),
        script_sha256=row.get("code_hash"), design=sig.get("design"),
        enumeration=sig.get("enumeration"), search_space=sig.get("search_space"),
        result=row.get("result"), evidence_kind=row.get("evidence_kind"))
    obs = dict(row.get("observations") or {})
    obs[ER.REPORT_KEY] = facts
    redo = NP.sign_experiment(
        method=row["method"],
        derived={"result": row.get("result"), "evidence_kind": row.get("evidence_kind"),
                 "negation_kind": row.get("negation_kind"), "observations": obs},
        code_path=row.get("code_path"), code_hash=row.get("code_hash"),
        certificate=row.get("certificate"), search_bound=row.get("search_bound") or {},
        experiment_id=row["experiment_id"])
    new_row = dict(row, evidence_kind=redo["evidence_kind"],
                   observations=redo["observations"])
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", new_row, note="e-sign")
    sync_counters(store)
    return new_row


def _run_exhaustive(store: Store, *, rel: str = "code/enum_ramsey34.py") -> dict:
    _write(store, rel, EXHAUSTIVE_PROBE)
    out = _e(store).run_experiment(
        "R(3,4)=9（K_9 的二染色穷举）", "ramsey34=9", rel, method="numeric")
    row = [r for r in _rows(store, "experiments")
           if r["experiment_id"] == out["experiment_id"]][0]
    signed = _land_report_and_resign(store, row)
    return {**out, "evidence_kind": signed["evidence_kind"]}


def _run_partial(store: Store, *, rel: str = "code/scan.py") -> dict:
    _write(store, rel, PARTIAL_PROBE)
    return _e(store).run_experiment("扫描了十万个点", "scan=100000", rel, method="numeric")


def _file_as_conjecture(store: Store, *, proof_text: str,
                        statement_full: str = "对任意正整数 n，R(3,4)=9。") -> dict:
    """先按猜想把这条命题落库（V 只审在册的命题 ⇒ 会审之前它必须是"在册的猜想"）。"""
    return _b(store).register_statement(
        origin="own_result", kind="conjecture", label="R(3,4)=9（先立成猜想）",
        statement_full=statement_full, statement_text=statement_full[:40],
        proof_text=proof_text, evidence_kind="cross_check",
        doc_id=S.format_id(0), line_range={"start": 1},
        quote_verified=False, quote_reason="own_result：我方推导，没有第二份文本可比对")


def _e_manuscript(store: Store, sid: str, column: str, *,
                  statement_full: str = "") -> str:
    """E 的按号证明手稿 `reports/e-proof-<号>.md`：V 在册送审的载体。

    2026-11-04（业主裁定 甲）：在册命题送审必须带手稿。穷举这一档的真机载体是 E
    自己那一趟落的 `reports/e-proof-<实验号>.md`（`exhaustionreport.land_manuscript`），
    这里用共享夹具落同样的三节内容、再按 E 的命名写一份（不另造一套格式）：
    `## 证明` 与证明栏逐字一致、`## 依赖` 是空表声明。
    """
    rel_f = write_proof_manuscript(store.root, sid, column, statement_full=statement_full)
    src = pathlib.Path(store.root) / rel_f
    rel = f"reports/e-proof-{sid}.md"
    (pathlib.Path(store.root) / rel).write_text(
        DS.mark_washed(src.read_text(encoding="utf-8"), actor="secretary-E"),
        encoding="utf-8")
    src.unlink()
    return rel


def _sign_with_v(store: Store, column: str,
                 statement_full: str = "对任意正整数 n，R(3,4)=9。") -> dict:
    """按业主 2026-10-23 晚的正路签一签：先立成猜想 → V 会审穷举证据 → 签「成立」。

    为什么判据必须走这一步（而不是直接让 B 登记 proof）：B 的入库闸
    （`numericproof.filing_problems`）从 2026-10-23 晚起要求盘上真有第三方（V）的会审
    签名 —— E 自己盖在 `observations.e_signature` 上的那一格不算数。V 只审在册的命题，
    所以顺序只能是"先猜想落库、再会审、再升档"。

    业主 2026-10-29：第 1、2 次「成立」只落台账、不翻第 3 位，同一份正文连续 3 次
    才轮到 V 的秘书发签 ⇒ 会审要跑三次（前两次先断"没签上"，第三次断"签上了"）。
    """
    filed = _file_as_conjecture(store, proof_text=column, statement_full=statement_full)
    assert filed.get("ok") is True, filed
    sid = str(filed["stmt_id"])
    before = dict(_rows(store, "statements")[0])
    # 2026-11-04（业主裁定 甲）：在册命题的 V 审也必须带手稿 —— 签块 / `## 依赖` /
    # 按号寻址三样只在文件上。夹具把这一份证明栏落成 `reports/f-proof-<号>.md`
    # （`## 证明` 与证明栏逐字一致，`## 依赖` 空表），送审时带同一个路径。
    # 判据一个字没改：连续 3 次「成立」才翻第 3 位这条口径原样在下面判。
    manuscript = _e_manuscript(store, sid, column, statement_full=statement_full)
    v = AgentV(store, workspace_root=store.root, secretary=_secretary_v(store))
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-e-000001",
                        parent_role="E"):
        first = v.verify_proof(sid, proof_text=column, proof_manuscript=manuscript)
        assert first.get("checked") is True and first.get("verdict") == "成立", first
        assert first.get("signed_bit3") is False, (
            "第 1 次「成立」就签上了第 3 位（连续 3 次才发签）", first)
        v.verify_proof(sid, proof_text=column, proof_manuscript=manuscript)
        got = v.verify_proof(sid, proof_text=column, proof_manuscript=manuscript)
    assert got.get("checked") is True and got.get("verdict") == "成立", got
    assert got.get("signed_bit3") is False, got
    assert got.get("review_write", {}).get("manuscript_signed") is True, got["review_write"]
    #: 这一趟前后命题行的逐字对照（V 不写 statements 的直接读数）。
    got["_statement_before"] = before
    got["_statement_after"] = dict(_rows(store, "statements")[0])
    return got


def _proof_column_of(store: Store) -> str:
    """台账里那条 E 签穷举证明的证明栏原文（B 要原样登记的那一份）。"""
    rows = NP.signed_exhaustion_experiments(_rows(store, "experiments"))
    assert rows, "台账里没有 E 签的穷举证明"
    return NP.proof_column(rows[0])


def _file_via_b(store: Store, *, proof_text: str, kind: str = "theorem",
                evidence_kind: str = "proof", statement_full: str = "对任意正整数 n，R(3,4)=9。",
                label: str = "R(3,4)=9", proof_manuscript: str = "") -> dict:
    """B 的入库正路（`own.register_statement` 的真身）：自产结果 + 证明栏 + 出处两件式。"""
    return _b(store).register_statement(
        origin="own_result", kind=kind, label=label,
        statement_full=statement_full, statement_text=statement_full[:40],
        proof_text=proof_text, evidence_kind=evidence_kind,
        doc_id=S.format_id(0), line_range={"start": 1},
        proof_manuscript=proof_manuscript,
        quote_verified=False, quote_reason="own_result：我方推导，没有第二份文本可比对")


def _canned(payload: dict):
    """固定回一个 JSON 的替身缝（不联网、不记账、不落会话）。"""

    class _Canned:
        def __init__(self) -> None:
            self.payload = dict(payload)

        def ask_json(self, prompt, **kw):
            import types as _t

            return dict(self.payload), _t.SimpleNamespace(ok=True, problem="", detail="")

    return _Canned()


def _secretary_b(store: Store, payload: dict) -> SEC.Secretary:
    return SEC.Secretary("B", root=store.root, store=store,
                         seam=_canned(payload), enable_model=True)


class _VSignSeam:
    """V 的秘书那一档的替身缝（`ask_json` 形状）：按 `note` 分档回预置结论。

    业主 2026-10-29：发签权在 V 的秘书手上 ⇒ "V 签上了"这条夹具要给它一个带判断面的
    秘书。`v_reply_defect` 判这段回复有没有缺陷（判不了的行不计入连续）、
    `sign_issuance` 判发不发这一签。
    """

    wired = True

    def __init__(self) -> None:
        self.seen: list[str] = []

    def ask_json(self, prompt, *, system: str = "", task_id: str = "", note: str = ""):
        import types as _t

        self.seen.append(str(note))
        kind = str(note).split(":", 1)[-1]
        answers = {"v_reply_defect": {"decision": "没问题", "reason": "夹具：读不出缺陷"},
                   "sign_issuance": {"decision": "签发", "reason": "夹具：连续次数够了"}}
        return (dict(answers.get(kind, {})),
                _t.SimpleNamespace(ok=True, problem="", detail=""))


def _secretary_v(store: Store) -> SEC.Secretary:
    """V 的秘书（带判断面）：`verify_proof` 的第三段（秘书发签）走的就是它。"""
    return SEC.Secretary("V", root=store.root, store=store,
                         seam=_VSignSeam(), enable_model=True)


def _gate(secretary: Any, name: str = "own.register_statement",
          statement_full: str = "对任意正整数 n，n^2+n 一定是偶数。") -> dict | None:
    """入库口那一道闸的真身（B 的入库动作之前、同一个返回面上）。"""
    import types

    return AgentLoop._statement_filing_tier(
        types.SimpleNamespace(role="B", secretary=secretary, my_task_id="t-000001"),
        name, {"statement_full": statement_full})


# ------------------------------------------------------------------ ④ 档位文案

def test_criterion4_the_tier_table_starts_at_t0_and_t1_is_reworded() -> None:
    """④ T0 = 基础定理或初步结论；T1 = 有一定价值的非平凡结论；T2–T4 逐字未变。

    判据钉的是"业主原话"这四件事，不是"有这么个变量"：文案一改，T0 与 T1 的定位就漂了，
    而漂了之后没有任何一格会红（档位是判断，不是数值）。
    """
    assert SEC.NONTRIVIALITY_LEVELS == (0, 1, 2, 3, 4), SEC.NONTRIVIALITY_LEVELS
    src = pathlib.Path(SEC.__file__).read_text(encoding="utf-8")
    # ① T0 与 T1 是业主这一次改的那两条
    assert "| 0 | 基础定理或初步结论" in src, "T0 的语义不是业主原话（基础定理或初步结论）"
    assert "| 1 | 有一定价值的非平凡结论" in src, "T1 没有改成业主的新定位"
    # ② T2–T4 逐字未变（业主：「T2 到 T4 定位不变」）
    for verbatim in (
        "| 2 | 证明方法都是平凡的，但工作量较大 |",
        "| 3 | 需要用较多的技巧或跨领域工具 |",
        "| 4 | 需要天才般的洞察力，或思维链极长，或是偏离主流研究方向的神奇构造 |",
    ):
        assert verbatim in src, f"T2–T4 的文案被改了（业主说定位不变）：{verbatim!r}"
    # ③ T0 与 T1–T4 是同一性质的一档：它不许被写成"次品 / 未评级 / 判不了"
    t0_line = next(line for line in src.splitlines() if line.startswith("#: | 0 |"))
    assert "次品" not in t0_line and "未评级" not in t0_line and "判不了" not in t0_line, t0_line
    # ④ 判不了不再是 0（它是 None）：两个意思折进一个值就会把"没人判过"读成"基础定理"
    assert SEC.NONTRIVIALITY_UNJUDGED is None
    assert SEC._nontriviality_level(None) is None
    assert SEC._nontriviality_level(0) == 0 and SEC._nontriviality_level("0") == 0
    assert SEC.nontriviality_label(0) == "T0" and SEC.nontriviality_label(4) == "T4"
    assert SEC.nontriviality_label(None) == ""


def test_calculation_methods_cover_schema() -> None:
    """反真空：本模块的方法表必须正好是 schema 那四种减 formal（两份不许漂）。"""
    assert set(NP.CALCULATION_METHODS) | {NP.FORMAL_METHOD} == set(S.EXPERIMENT_METHODS)


# ------------------------------------------------------------------ ① 穷举 ⇒ proof

def test_criterion1_an_exhaustive_run_is_proof_signed_by_v_with_an_exhaustion_column(
        tmp_path: pathlib.Path) -> None:
    """① 穷举实验 ⇒ 命题可标 proof、`signed_by=V`（③ 的作者是 E）、证明栏只有穷举论证。

    整条链真跑一次：E 起子进程跑枚举脚本 → E 按穷尽证据签 proof →
    B 把 E 的证明栏原样登记 → 命题行进定理证明库（`proof` ⇒ 可以当根）。

    2026-11-08 口径（业主：「穷举式的 proof_test 应该是填穷举论证，实验栏填相对路径」）：
    证明栏只剩 ③；① 程序在 `experiments.code_path`、② 程序设计在
    `observations["design"]` —— 两段都不许再出现在证明栏里。
    """
    store = _store(tmp_path)
    out = _run_exhaustive(store)
    assert out["evidence_kind"] == "proof", out
    rows = _rows(store, "experiments")
    assert len(rows) == 1
    row = rows[0]
    sig = NP.signature_of(row)
    # ⑦ 的读数形状（业主 2026-10-23 晚）：签字由 V，③ 的作者是 E，不许 signed_by=E
    assert sig["signed_by"] == NP.PROOF_SIGNER == "V", sig
    assert sig[NP.PROOF_AUTHORS_KEY] == ["E"], sig
    assert np_author_not_signer(sig), sig
    assert sig["proof_reason"] == NP.PROOF_REASON_EXHAUSTION, sig
    assert NP.is_signed_exhaustion(row), row
    # 证明栏：只有 ③；程序路径在实验行、程序设计在 observations 里
    column = NP.proof_column(row)
    parts = NP.parse_proof_column(column, code_path=row["code_path"])
    assert parts["problems"] == [], parts
    assert parts["script"] == "code/enum_ramsey34.py", parts
    assert parts["script"] == row["code_path"], parts
    assert parts["design"] == "", "② 程序设计不许再出现在证明栏里（它住 observations）"
    assert parts["enumeration"].strip(), parts
    assert "程序设计：" not in column and "程序：" not in column, column
    assert str((row.get("observations") or {}).get("design") or "").strip(), row

    # V 的会审签名必须先落在盘上（第三方签字闸：E 自己盖的章不算）
    add_literature(store, S.format_id(0))
    _sign_with_v(store, column)
    # B 原样登记（证明栏一字不改）
    filed = _file_via_b(store, proof_text=column)
    assert filed.get("ok") is True, filed
    stmt = _rows(store, "statements")[0]
    assert stmt["evidence_kind"] == "proof", stmt
    assert stmt["proof_text"] == column, "证明栏不许被改写（业主：B 只原样登记）"
    assert stmt["kind"] == "theorem", "E 签过穷举证明的命题一进门就该能叫定理"

    # 定理证明库那一档：`proof` ⇒ 这条命题可以当根（后续定理能引它）
    from agentflow.agent_c import proof_chain as PC

    graph = PC._DepGraph(stmts=[stmt], deps=[], exps=[], lits=[])
    is_root, why = graph.is_root(f"stmt:{stmt['stmt_id']}")
    assert is_root, f"穷举证明的命题没进定理证明库（{why}）"


def test_criterion1c_the_third_clean_sign_backfills_proof_not_proof_review(
        tmp_path: pathlib.Path) -> None:
    """回归（2026-11-04，2026-11-05 改读等级）：穷举 + V 三转「成立」⇒ `theorem`。

    与 ① 同一条链，但断言点在"V 落签那一刻"而不是"B 登记之后"：旧回填一律写
    `proof_review`，于是 B 的第二笔（要 `proof`）撞 `duplicate_statement`。
    业主口径（`evidencebits.derive_grade`）：穷举程序 + 针对该穷举的 V 签 ⇒
    与 Lean 同级，都算 `theorem`（历史列反算名 `proof`）；`pre_theorem` 是
    "V 逐行审过文字证明"那一档，V 不能逐行走查一份程序。

    这里量三件事：① 落签后等级现算就是 `theorem`（按通道落 numeric 位）；
    ② B 拿着同一份内容再登记仍然 `ok=True` 且不新建行（`at_tier`；不是重复登记）；
    ③ 最终那一行仍是 `theorem`。
    """
    store = _store(tmp_path)
    _run_exhaustive(store)
    add_literature(store, S.format_id(0))
    column = _proof_column_of(store)
    got = _sign_with_v(store, column)
    signed_before = dict(got.get("_statement_before") or {})

    # 2026-11-08（V 只对手稿负责）：V 这一趟只把签落在稿上；命题行的等级 / kind /
    # 第 3 位都是 B 收录时的活。所以"V 落签那一刻"这一行必须逐字不动。
    signed = _rows(store, "statements")[0]
    assert signed == signed_before, "V 的签写进了 statements（新契约下这是 B 收录的活）"

    filed = _file_via_b(store, proof_text=column, evidence_kind="proof")
    assert filed.get("ok") is True, filed
    # B 这一笔是"同一条已在册、证据档到位"：不新建行，历史列按现算等级反算成 proof。
    assert filed.get("new_row") is False, filed
    assert filed.get("evidence_kind") == "proof", filed
    final = _rows(store, "statements")[0]
    assert final["kind"] == "theorem", final
    assert final["evidence_kind"] == "proof", final
    assert EB.bits_from_row(final)["grade"] == "theorem", final
    trace = dict(final.get(VR.GRADE_RECOMPUTED_KEY) or {})
    assert trace.get("to") == "theorem", trace
    assert trace.get("to_kind") == "proof", trace
    assert int(trace.get("proof_no") or 0) == 1, trace


def np_author_not_signer(sig: dict) -> bool:
    """反真空：签名主体与 ②③ 的作者是两个人（业主 2026-10-23 晚：不许 signed_by=E）。"""
    return str(sig.get("signed_by")) == "V" and "E" in [str(a) for a in sig.get("proof_authors") or []]


def test_criterion1b_the_verdict_helper_names_the_signature_parts() -> None:
    """① 的读数面：判定函数把三件事一起给出来（等级、签名主体、证明栏）。"""
    obs = {"exhaustive": True, "design": "按 4-子集编码枚举",
           "enumeration": "全部 2^36 个染色", "search_space": {"graph": "K_9"},
           "exhaustion_report": _report_facts()}
    v = NP.exhaustion_verdict(method="numeric", observations=obs, code_path="code/enum.py")
    assert v["evidence_kind"] == "proof" and v["proof_reason"] == NP.PROOF_REASON_EXHAUSTION
    assert v["signed_by"] == "V" and v["proof_authors"] == ["E"]
    assert NP.parse_proof_column(v["proof_text"],
                                 code_path="code/enum.py")["script"] == "code/enum.py"
    assert "程序设计：" not in v["proof_text"], "② 程序设计不许再抄进证明栏"


# ------------------------------------------------------------------ ② 不完全 ⇒ 不构成证明

def _assert_partial_cannot_be_proof(tmp_path: pathlib.Path) -> None:
    """② 的正文（被 ⑤-a 打桩之后必须红的那一段）。"""
    store = _store(tmp_path)
    # 负控 A：判定函数 —— 只有"扫了很多点"⇒ 有数值实验支持，不是证明
    partial_obs = {"points": 100000, "grid": 64}
    v = NP.exhaustion_verdict(method="numeric", observations=partial_obs,
                              code_path="code/scan.py")
    assert v["evidence_kind"] == NP.SUPPORTED_ONLY_KIND, v
    assert v["proof_reason"] == "" and v["script_path"] == "" and v["proof_text"] == "", v
    assert v["problems"], "缺什么必须逐条写清（不许只说一句'不合格'）"

    # 负控 B：schema —— 手写一条 incomplete 的 proof 行 ⇒ 写入期就炸
    with pytest.raises(ValueError) as ei:
        S.Experiment(experiment_id="000001", claim="扫描了十万个点", claim_key="scan",
                     method="numeric", evidence_kind="proof", result="supports",
                     negation_kind="not_proved", code_path="code/scan.py",
                     code_hash="deadbeef", exit_code=0, observations=partial_obs,
                     created_at=TS).validate()
    assert "不得声称" in str(ei.value), ei.value

    # 负控 C：E 真跑一次不完全的脚本 ⇒ 落 cross_check（不是 proof）
    out = _run_partial(store)
    assert out["evidence_kind"] == "cross_check", out
    row = [r for r in _rows(store, "experiments") if r["claim_key"] == "scan=100000"][0]
    assert row["evidence_kind"] == "cross_check"
    assert not NP.is_signed_exhaustion(row)
    assert NP.signature_of(row)["problems"], "读数里要点名缺哪一块"

    # 负控 C2（业主 2026-10-23 晚）：穷尽证据齐了、但 ②③ 没落盘 ⇒ 也只能 cross_check。
    # "E 没给 ②③ ⇒ 不许登记成 proof" 的这一半必须在签名那一刻就问。
    abundant = {"exhaustive": True, "design": "按 4-子集编码枚举",
                "enumeration": "全部 2^36 个染色，按同构剪枝",
                "search_space": {"graph": "K_9"}}
    signed = NP.sign_experiment(method="numeric",
                                derived={"result": "supports", "evidence_kind": "cross_check",
                                         "negation_kind": "not_proved",
                                         "observations": abundant},
                                code_path="code/enum.py", code_hash="deadbeef",
                                experiment_id=S.format_id(4))
    assert signed["evidence_kind"] == "cross_check", signed
    sig = NP.signature_of({"observations": signed["observations"]})
    assert sig["proof_text"] == "" and sig["proof_reason"] == "", sig
    assert any("②③" in p or "程序设计" in p for p in sig["problems"]), sig["problems"]

    # 负控 D：B 拿一条 cross_check 的实验去标 proof ⇒ 受控拒绝（B 不许自签）
    add_literature(store, S.format_id(0))
    fabricated = NP.compose_proof_column(enumeration="应该不漏吧")
    refused = _file_via_b(store, proof_text=fabricated)
    assert refused.get("ok") is False, refused
    assert refused.get("kind") == "proof_needs_third_party_signature", refused


def test_criterion2_an_incomplete_experiment_is_only_supported_not_proved(
        tmp_path: pathlib.Path) -> None:
    """② 不完全实验（exhaustive=false / 缺覆盖说明）⇒ 标不成 proof，只能是"有数值实验支持"。"""
    assert NP.SUPPORTED_ONLY_LABEL.startswith("有数值实验支持")
    _assert_partial_cannot_be_proof(tmp_path)
    # exhaustive=false 也是同一条结论（"说了不是"与"没说"都不够 proof）
    v = NP.exhaustion_verdict(method="numeric",
                              observations={"exhaustive": False, "design": "d",
                                            "enumeration": "e"},
                              code_path="code/sample.py")
    assert v["evidence_kind"] == NP.SUPPORTED_ONLY_KIND, v


# ------------------------------------------------------------------ ③ 平凡 ⇒ 收录且 T0

def _assert_nontrivial_branch_keeps_its_tier(store: Store) -> None:
    """③ 的非平凡那一支（被 ⑤-b 打桩之后必须红的那一段）。

    判了「合格」、力气读数落在第 3 档 ⇒ 这一条不许被压成 T0（"懂平凡"不是"恒判平凡"）。

    2026-10-24（业主裁定 B2）之后档位由"证明花的力气"给，所以这一支要带一份真够 T3 的
    证明正文（体量 16 200 字 ⇒ 分数 8 ⇒ T3）：不交证明时档位是「未判」，那一支另有判据。
    """
    statement = ("设 D 是 III 型因子，则它的某个不变量取整数值。\n\n证明：" + "推导。" * 5400)
    sec = _secretary_b(store, {"decision": "T3", "reason": "L3 那一步要用到它",
                               "basis": ["L3"], "nontriviality": 3,
                               "nontriviality_basis": "用了跨领域工具"})
    note = _gate(sec, statement_full=statement)
    assert note is None, f"非平凡命题被贴了档位读数（那说明'懂平凡'被打桩成恒平凡）：{note}"
    got = SEC.nontriviality_of(store.root, statement)
    assert (got["tri"], got["level"], got["label"]) == ("computed", 3, "T3"), got


def test_criterion3_a_trivial_statement_is_filed_and_lands_on_t0(tmp_path: pathlib.Path) -> None:
    """③ 平凡命题 ⇒ 收录成功且档位 T0（改前：被「太平凡」拒收）。

    这是业主这一次裁定的正面：平凡不是"不许进"，是"进哪一档"。

    2026-10-24（业主裁定 B2）之后"平凡"的含义是"力气小"，而档位由秘书判：
    所以这一条要带一份力气小的证明（一行推导）。不交证明时档位是「未判」——
    "没有证明正文"与"证明花的力气小"是两件事（判据见
    `tests/test_nontriviality_is_judged_by_effort.py` 的 (a)/(b)）。

    2026-10-29 业主再裁定「全交给模型判」：档位那一格由秘书自报的档位给，
    机器力气读数只作参考（`secretary.judge_statement` 那一支）。所以夹具里的秘书
    必须是一份"判太平凡、自报第 0 档"的读数 —— 改前这里报的是 2 档，于是返回的
    `tier` 读成 T2（而断言的 T0 是旧口径下"平凡 ⇒ 一律 T0"的形态）。断言一个字
    没动：仍然要求 `tier=T0` + `downgraded=True` + 收工读数里 T0 记 1 条。
    """
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    text = ("对任意正整数 n，n^2+n 一定是偶数。\n\n"
            "证明：n 与 n+1 必有一偶，故 n(n+1) 是偶数。∎")
    sec = _secretary_b(store, {"decision": "T0", "reason": "这是显而易见的等式重排",
                              "basis": ["没有后续使用"], "nontriviality": 0,
                              "nontriviality_basis": "一行推导，体量/步骤都在最低一档"})
    note = _gate(sec, statement_full=text)
    assert note is not None, "判了「太平凡」却没有给出档位读数"
    assert note["tier"] == "T0" and note["downgraded"] is True, note
    assert "T0" in str(note["note"]) and "拦收录" in str(note["note"]), note

    # 收录成功：这一条真的进了表（改前这里是 `ok=False` + `statement_too_trivial`）。
    # `kind="conjecture"` 是自产且无出处那一档的唯一入口（B-2），与本判据无关：
    # 这一条要证的是"平凡 ⇒ 照收 + 落 T0"，不是"平凡也能一进门叫定理"。
    filed = _file_via_b(store, proof_text="Proof. n(n+1) 必有一偶。",
                        statement_full=text, kind="conjecture", evidence_kind="heuristic")
    assert filed.get("ok") is True, filed
    assert len(_rows(store, "statements")) == 1

    # 档位落在 T0（读数可查，且与"判不了"分得开）
    got = SEC.nontriviality_of(store.root, text)
    assert (got["tri"], got["level"], got["label"]) == ("computed", 0, "T0"), got

    # 收工读数里看得见"降为 T0"
    reading = closing.nontriviality_reading(store.root)
    assert reading["counts"]["T0"] == 1, reading["counts"]
    assert reading["counts"]["unjudged"] == 0, reading["counts"]
    assert reading["downgraded_to_t0_total"] == 1, reading["downgraded_to_t0"]
    assert "T0" in reading["downgraded_note"]

    # 非平凡那一支：档位照旧是秘书给的那一档（"平凡 ⇒ T0"不是"一律 T0"）
    _assert_nontrivial_branch_keeps_its_tier(store)


def test_legacy_ledger_zero_is_unjudged_not_t0(tmp_path: pathlib.Path) -> None:
    """迁移守卫：旧台账（没有刻度标记）里的 `nontriviality: 0` 是"判不了"，不是 T0。"""
    root = tmp_path
    path = SEC.nontriviality_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    import hashlib

    sha = hashlib.sha256("旧命题".encode("utf-8")).hexdigest()
    path.write_text(json.dumps({"at": TS, "statement_sha256": sha, "nontriviality": 0,
                                "basis": "旧刻度：0 表示判不了"}, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")
    got = SEC.nontriviality_of(root, "旧命题")
    assert (got["tri"], got["level"], got["label"]) == ("unknown", None, ""), got
    # 而新刻度下的 0 就是 T0
    SEC.append_nontriviality(root, statement_full="新命题", level=0, basis="平凡但真")
    fresh = SEC.nontriviality_of(root, "新命题")
    assert (fresh["tri"], fresh["level"], fresh["label"]) == ("computed", 0, "T0"), fresh


# ------------------------------------------------------------------ ⑥ 缺 ②③ 不许 proof

def test_criterion6_only_an_exhaustion_argument_without_a_code_path_is_not_enough(
        tmp_path: pathlib.Path) -> None:
    """⑥ 缺穷举论证 / 缺程序路径（code_path）⇒ 不许 proof，拒信逐字点名缺哪一块。

    2026-11-08 的两条口径（业主：「穷举式的 proof_test 应该是填穷举论证，实验栏填相对
    路径」）：证明栏只有 ③，程序路径在 `experiments.code_path`；两样缺任何一样都拿不到
    proof，拒信必须逐字写「缺穷举论证」/「缺程序路径（code_path）」。
    """
    store = _store(tmp_path)
    _run_exhaustive(store)
    add_literature(store, S.format_id(0))
    # a：只有 ③、没有程序路径（那条实验的 code_path 不是这一份文本的签名）
    refused = _file_via_b(store, proof_text="穷举论证：全部 2^36 个染色，按同构剪枝")
    assert refused.get("ok") is False, refused
    assert refused.get("kind") == "proof_needs_third_party_signature", refused
    error = str(refused.get("error") or "")
    assert "缺程序路径（code_path）" in error, error

    # b：只写了一行程序路径（旧形态）⇒ 证明栏里没有 ③，拒信点名缺穷举论证
    refused2 = _file_via_b(store, proof_text="code/enum_ramsey34.py")
    assert refused2.get("ok") is False, refused2
    error2 = str(refused2.get("error") or "")
    assert "缺穷举论证" in error2, error2

    # 判定函数这一侧：E 那边缺 ②（design）或缺 ③（enumeration）⇒ 一样拿不到 proof
    base = {"exhaustive": True, "enumeration": "全部 2^36 个染色，按同构剪枝",
            "search_space": {"graph": "K_9"}, "exhaustion_report": _report_facts()}
    no_design = NP.exhaustion_verdict(method="numeric", observations=dict(base),
                                      code_path="code/enum.py")
    assert no_design["evidence_kind"] == NP.SUPPORTED_ONLY_KIND, no_design
    assert any("程序设计" in p for p in no_design["problems"]), no_design["problems"]
    no_enum = NP.exhaustion_verdict(method="numeric",
                                    observations={"exhaustive": True, "design": "按 4-子集编码",
                                                  "search_space": {"graph": "K_9"},
                                                  "exhaustion_report": _report_facts()},
                                    code_path="code/enum.py")
    assert any("穷举论证" in p for p in no_enum["problems"]), no_enum["problems"]
    # 负控：②③ 齐了（且落盘事实在）才够
    assert NP.exhaustion_verdict(
        method="numeric", observations=dict(base, design="按 4-子集编码"),
        code_path="code/enum.py")["evidence_kind"] == "proof"


# ------------------------------------------------------------------ ⑦ 作者必须是 E

def test_criterion7_the_signature_is_v_and_the_authors_are_e(tmp_path: pathlib.Path) -> None:
    """⑦ 签名主体是 V、②③ 的作者是 E；B 自称作者 / 改写 / signed_by=E ⇒ 受控拒绝。

    业主 2026-10-23 晚的更正逐字：「签字仍然由 V 签（不是 E）。E 是 ②③ 的原作者，
    但签名主体是 V。读数形状：signed_by = "V"；proof_authors 里含 "E"；不许出现 signed_by=E。」
    """
    store = _store(tmp_path)
    _run_exhaustive(store)
    add_literature(store, S.format_id(0))
    column = _proof_column_of(store)
    row = NP.signed_exhaustion_experiments(_rows(store, "experiments"))[0]
    parts = NP.parse_proof_column(column, code_path=row.get("code_path"))
    assert parts["problems"] == []
    sig = NP.signature_of(row)
    # ⑦-c 读数形状（业主点名的两个字段）
    assert sig["signed_by"] == "V" and sig[NP.PROOF_AUTHORS_KEY] == ["E"], sig

    # ⑦-a：B 把 ③ 改写成自己的话 ⇒ 拒（认法是实验号 / code_path，不是文本）
    rewritten = NP.compose_proof_column(enumeration="我自己想的搜法（E 那份我没看）")
    manuscript_rel = f"reports/e-proof-{row['experiment_id']}.md"
    refused = _file_via_b(store, proof_text=rewritten,
                          proof_manuscript=manuscript_rel)
    assert refused.get("ok") is False, refused
    assert "改写" in str(refused.get("error") or ""), refused.get("error")

    # ⑦-b：签名的作者不是 E（B 自称作者）⇒ 判据不认，且 schema 层面写不进去
    forged_sig = {**sig, NP.PROOF_AUTHORS_KEY: ["B"]}
    forged = dict(row)
    forged["observations"] = {**row["observations"], NP.SIGNATURE_KEY: forged_sig}
    assert not NP.is_signed_exhaustion(forged), "作者不是 E 的行被当成了这份证明"
    with pytest.raises(ValueError):
        S.Experiment(**{k: v for k, v in forged.items()
                        if k in S.Experiment.__dataclass_fields__}).validate()

    # ⑦-c：签名主体写成 E（那一版已作废）⇒ B 的入库闸点名"口径作废"，schema 也拒
    stale_sig = {**sig, "signed_by": "E"}
    stale = dict(row)
    stale["observations"] = {**row["observations"], NP.SIGNATURE_KEY: stale_sig}
    probs = NP.filing_problems(
        origin="own_result", evidence_kind="proof",
        proof_text=column, experiments=[stale],
        # 程序路径住在实验行：按稿名钉到那一条（2026-11-08）
        manuscript=f"reports/e-proof-{row['experiment_id']}.md")
    assert probs and "作废" in probs[0], probs
    with pytest.raises(ValueError):
        S.Experiment(**{k: v for k, v in stale.items()
                        if k in S.Experiment.__dataclass_fields__}).validate()


# ------------------------------------------------------------------ ⑧ 形式化那一格

def test_criterion8_the_formal_slot_is_filled_by_the_right_kind(tmp_path: pathlib.Path) -> None:
    """⑧ 两类定理的"形式化"格各自填对、互不冒充。

    业主 2026-10-23 晚：「对应的"形式化"那个地方用数值实验程序填；其它正常理论性的
    定理的形式化栏填 lean 程序」⇒ 同一格、两种填法；数值定理填 `.lean` ⇒ 红，
    理论定理填 `.py` ⇒ 红。
    """
    store = _store(tmp_path)
    _run_exhaustive(store)
    add_literature(store, S.format_id(0))
    column = _proof_column_of(store)
    _sign_with_v(store, column)
    assert _file_via_b(store, proof_text=column).get("ok") is True
    numeric_stmt = _rows(store, "statements")[0]
    exp_row = _rows(store, "experiments")[0]
    script = exp_row["code_path"]

    # 数值实验定理：这一格该填数值程序
    slot = NP.formal_slot(numeric_stmt, _rows(store, "experiments"))
    assert (slot["channel"], slot["kind"], slot["path"]) == (
        "numeric", NP.FORMAL_SLOT_NUMERIC, script), slot
    # 填对 ⇒ 无问题；填成 .lean ⇒ 红（拿形式化冒充数值实验）；填成别的程序 ⇒ 红
    assert NP.formal_slot(numeric_stmt, _rows(store, "experiments"), filled=script)["problems"] == []
    lean_filled = NP.formal_slot(numeric_stmt, _rows(store, "experiments"),
                                 filled="formal/000001.lean")
    assert lean_filled["problems"] and "冒充" in lean_filled["problems"][0], lean_filled
    wrong = NP.formal_slot(numeric_stmt, _rows(store, "experiments"), filled="code/other.py")
    assert wrong["problems"], wrong

    # 理论定理：证明栏是自然语言，台账里有 formal 那一行 ⇒ 这一格该填 .lean 程序
    add_literature(store, S.format_id(1))
    theory = dict(numeric_stmt)
    theory.update(stmt_id=S.format_id(7), kind="theorem",
                  proof_text="Proof. 由谱定理逐项展开。", evidence_kind="proof",
                  label="理论定理一条")
    formal_exp = {"experiment_id": S.format_id(3), "method": "formal",
                  "evidence_kind": "proof", "code_path": "formal/000003.lean",
                  "verifier_output": "verified", "claim": "理论定理一条",
                  # 绑到 theory 这一条命题（2026-11-05 起 formal 通道按命题号绑，
                  # 谓词是 `evidencebits.formal_row_bound_to`）：改前这里写的是 "k"，
                  # 那是一行"没绑到任何命题"的 formal 行 —— 旧口径把它当成 theory 的凭据，
                  # 正是 78c 缺陷的形状。
                  "claim_key": f"stmt:{S.format_id(7)}"}
    slot2 = NP.formal_slot(theory, [formal_exp])
    assert (slot2["channel"], slot2["kind"], slot2["path"]) == (
        "formal", NP.FORMAL_SLOT_LEAN, "formal/000003.lean"), slot2
    assert NP.formal_slot(theory, [formal_exp],
                          filled="formal/000003.lean")["problems"] == []
    # 理论定理填 .py ⇒ 红（拿数值程序冒充形式化核验）
    bad = NP.formal_slot(theory, [formal_exp], filled="code/enum_ramsey34.py")
    assert bad["problems"] and "冒充" in bad["problems"][0], bad
    # 三态：没填不是填错
    assert NP.formal_slot(theory, [formal_exp], filled="")["problems"] == []


# ------------------------------------------------------------------ V 不覆盖数值证据

def test_the_walk_through_review_does_not_cover_numeric_evidence(tmp_path: pathlib.Path) -> None:
    """"签字由 V"与"V 的逐行走查"是两件事：数值证据的证明栏是程序 ⇒ 逐行走查不适用。

    为什么要单独一条：这一签会被下游读成"V 逐行审过这份证明了"。业主把签字给了 V，
    而材料是 E 的程序 + ②③ —— V 没有跑过那份程序，逐行审阅这件事它做不了。
    判据只落在一处（`numericproof.verifier_problems`），接线由负责 V 那一侧的人做。
    """
    store = _store(tmp_path)
    _run_exhaustive(store)
    add_literature(store, S.format_id(0))
    column = _proof_column_of(store)
    stmt = {"stmt_id": S.format_id(0), "proof_text": column, "evidence_kind": "proof"}
    problems = NP.verifier_problems(stmt, _rows(store, "experiments"))
    assert problems and "逐行走查" in problems[0], problems
    # 负控（防误伤）：自然语言证明的命题照旧归 V 的逐行走查管
    assert NP.verifier_problems({"stmt_id": S.format_id(1),
                                 "proof_text": "Proof. 由定义直接得到。"}) == []


# ------------------------------------------------------------------ ⑤ 反真空

def test_criterion5a_stubbing_the_exhaustion_judgement_makes_criterion2_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤-a 把"穷尽判定"打桩成恒真 ⇒ ② 必红。

    没有这一条，② 的绿色可能来自"判据根本没跑"：一个恒返回 proof 的打桩版本会让
    "不完全实验 ⇒ 只能是 cross_check"当场失效。
    """
    monkeypatch.setattr(NP, "exhaustion_problems", lambda **kw: [])
    monkeypatch.setattr(NP, "exhaustion_verdict", lambda **kw: {
        "exhaustive": True, "evidence_kind": "proof", "label": "proof",
        "proof_reason": NP.PROOF_REASON_EXHAUSTION, "signed_by": "E",
        "proof_authors": ["E"], "script_path": str(kw.get("code_path") or ""),
        "design": "d", "enumeration": "e",
        "proof_text": NP.compose_proof_column(enumeration="e"),
        "search_space": {}, "problems": [],
    })
    with pytest.raises(AssertionError):
        _assert_partial_cannot_be_proof(tmp_path)


def test_criterion5b_stubbing_trivial_detection_makes_the_nontrivial_branch_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤-b 把"懂平凡"打桩成恒平凡 ⇒ ③ 里的非平凡那一支必红。

    没有这一条，③ 的绿色可能来自"什么都被判成 T0"。
    """
    store = _store(tmp_path)
    monkeypatch.setattr(SEC, "_is_trivial_verdict", lambda *a, **k: True)
    with pytest.raises(AssertionError):
        _assert_nontrivial_branch_keeps_its_tier(store)


#: 2026-11-02 准入闸默认 strict 之后，本文件的夹具一律先给"B 即将写进台账的那一份
#: 证明正文"补一签（真签：在册走台账、未在册走 pending）。见 conftest 的同名 fixture。
pytestmark = pytest.mark.usefixtures("signed_v_handoffs")
