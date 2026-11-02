# -*- coding: utf-8 -*-
"""判据 ①–⑤：B 的第三方签字闸 —— proof 那一档必须有一份盖住这一条命题的 V 会审签名。

## 这一组守什么（业主 2026-10-23 晚：「签字仍然由 V 签（不是 E）」）

改前的洞（实测，不是推测）：真穷举实验跑完、`verifications/` 目录根本不存在，B 的
`register_statement` 仍然 `ok=True`，落成 `kind=theorem` / `evidence_kind=proof` /
`bits.reviewed=False`。根因是两个函数只读 E 自己盖的章：

- `numericproof.is_signed_exhaustion` 读 `experiments.observations.e_signature.signed_by`
  （那串字是 E 在 `build_experiment` / `sign_experiment` 里自己写上去的）；
- `register_statement._self_authored_gate` 又拿同一个读数（`_e_signed_exhaustion`）给
  "自产定理必须先有 V 的签"那道闸开了一个例外。

现在 `numericproof.filing_problems` 多一条第三方签字判据：按正文认出在册的那条命题，
读 `verifications/<命题号>.jsonl` 的最近一签，要求 `verdict=成立`、且那一签的
`proof_sha256` 与这一份证明栏对得上。E 的 `e_signature` 一个字都不再看。

| # | 判据 | 改前为什么红 |
|---|---|---|
| ① | V 没审 ⇒ B 登记拿不到 proof | 改前 `verifications/` 根本不存在也照登记（ok=True + proof） |
| ② | V 签「成立」但 `proof_sha256` 对不上 ⇒ 不许 proof（负控） | 改前只读 E 的章，sha 无人核 |
| ③ | V 签「有毛病」⇒ 不许 proof，且点名最近一签 verdict | 同上：任何 E 章都放行 |
| ④ | V 签「成立」且 sha 相符 ⇒ 允许 proof（正控，端到端） | 改前"允许"不依赖这一签，所以正控不成立 |
| ⑤ | 反真空：把"读 verifications 最近一签"打桩成恒成立 ⇒ ② 与 ③ 必红 | 判据自身要能红 |

全部用例在 `tmp_path` 里自建工作区，一个模型调用都不发。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from typing import Any

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import add_literature, seed_statement_row, sync_counters  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-10-23T00:00:00+08:00"
SCRIPT_REL = "code/enum_ramsey34.py"
BODY = "对任意正整数 n，R(3,4)=9。"

#: 一个真的穷举脚本：搜索空间的数字在"报数之前"的代码段里有着落（V 的会审第 3 项要核它）。
EXHAUSTIVE_PROBE = """
import json
N = 9
SPACE = 2 ** 36
TOTAL = 68719476736
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把 R(3,4)=9 的上界归约成 K_9 的二染色穷举：按 4-子集布尔赋值编码逐点检查",
        "enumeration": ("枚举 K_9 全部 2^36 = 68719476736 个二染色；先按顶点置换取 canonical form "
                        "去掉对称性重数，再按 3-子集/4-子集的对称性剪枝；每个染色都落在枚举里，"
                        "无一遗漏；边界：n=9 是上界侧的全部，n<=8 由 witness 覆盖"),
        "search_space": {"graph": "K_9", "colourings": 68719476736},
    },
    "counterexample": None, "negation_kind": "not_proved",
    "bound": {"n": 9}, "strategy": "canonical form + symmetry breaking",
}))
"""


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


def _ledger(store: Store, sid: str, rows: list[dict[str, Any]]) -> pathlib.Path:
    """手写一份 V 的台账（②③ 要控制 verdict 与 sha，所以不走真 V）。"""
    path = pathlib.Path(store.root) / VR.VERIFICATIONS_DIR / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(dict(r, stmt_id=sid, statement_id=sid), ensure_ascii=False)
             for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def _run_exhaustive(store: Store) -> dict:
    """E 真跑一次穷举实验，并把 ②③ 落到盘上（这一步之后那条实验才是 proof）。"""
    _write(store, SCRIPT_REL, EXHAUSTIVE_PROBE)
    out = AgentE(store, config={}, workspace_root=store.root).run_experiment(
        "R(3,4)=9（K_9 的二染色穷举）", "ramsey34=9", SCRIPT_REL, method="numeric")
    row = [r for r in store.rows("experiments") if r["experiment_id"] == out["experiment_id"]][0]
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
    return {"column": NP.proof_column(new_row), "row": new_row}


def _b(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=None)


class _Call:
    """`llmseam.SeamCall` 的替身：`judge()` 只读 ok / problem / detail。"""

    ok = True
    problem = ""
    detail = ""


class _IssuingSeam:
    """V 的秘书那一档的离线替身缝（只答两件事：V 的回复没问题 / 这一签发）。

    2026-10-29 口径：签由 V 的秘书判、也由它落盘。没有这条缝时 `AgentV` 的
    `signed_bit3` 恒为假 —— 那是装配缺失，不是这条判据要量的东西。
    """

    wired = True

    def __init__(self) -> None:
        self.kinds: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict, _Call]:
        kind = note.split(":", 1)[-1]
        self.kinds.append(kind)
        if kind == "sign_issuance":
            doc = {"decision": SEC.SIGN_ISSUE, "reason": "夹具：三次成立都干净 ⇒ 发签",
                   "basis": ["夹具"]}
        else:
            doc = {"decision": SEC.V_REPLY_CLEAN, "reason": "夹具：照规则判 clean",
                   "basis": ["夹具"]}
        return dict(doc), _Call()


def _v(store: Store) -> AgentV:
    """V 和它的秘书（2026-10-29：V 只落台账，翻位是秘书那一侧的事）。"""
    sec = SEC.Secretary("V", root=pathlib.Path(store.root), store=store,
                        seam=_IssuingSeam(), enable_model=True)
    return AgentV(store, workspace_root=store.root, secretary=sec)


def _review_until_signed(agent: AgentV, sid: str, text: str) -> list[dict]:
    """同一份正文连审到发签门槛，返回那几次的返回（最后一条才是签发的那一次）。

    改前这条端到端判据审一次就断言 `signed_bit3=True`（旧口径：一次成立就签）。
    2026-10-29 的新口径要求同一份正文连续 `SIGN_STREAK_NEED` 次「成立」且秘书判定通过
    才落签 ⇒ 夹具按同一份正文连审，并在这里钉住"前几次不签"这条正控。
    """
    outs: list[dict] = []
    for i in range(1, int(VR.SIGN_STREAK_NEED) + 1):
        got = agent.verify_proof(sid, proof_text=text)
        outs.append(got)
        assert got.get("checked") is True, got
        assert got.get("verdict") == "成立", got
        assert got.get("signed_bit3") is (i == int(VR.SIGN_STREAK_NEED)), (
            f"第 {i} 次会审的 signed_bit3={got.get('signed_bit3')!r} —— 门槛是连续 "
            f"{int(VR.SIGN_STREAK_NEED)} 次「成立」且秘书判定通过（第 1、2 次只落台账），"
            f"读到的发签决定：{got.get('sign_issuance')}", got)
    return outs


def _file(store: Store, *, column: str, kind: str = "theorem",
          evidence_kind: str = "proof", body: str = BODY) -> dict:
    return _b(store).register_statement(
        origin="own_result", kind=kind, label="R(3,4)=9", statement_full=body,
        statement_text=body[:40], proof_text=column, evidence_kind=evidence_kind,
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导，没有第二份文本可比对")


def _file_conjecture(store: Store, *, column: str, body: str = BODY) -> dict:
    """造一条"在册的猜想"（历史形态：直接铺行；V 只审在册的命题）。

    2026-11-02 准入闸默认 strict 之后，无签的证明正文经 `register_statement` 写不进去
    （整笔 `proof_without_v_sign`）—— 而这一组测的是"第三方签（sha / 最近 verdict）
    对不上 ⇒ 不许升 proof"。现场由夹具直接铺行造出（真机在册猜想行同形：`bits` 由
    `bits_of` 现算、台账 0 行），读侧判据一个字都没改。
    """
    seeded = seed_statement_row(
        store, proof_text=column, statement_full=body, statement_text=body[:40],
        kind="conjecture", label="R(3,4)=9", origin="own_result",
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导，没有第二份文本可比对",
        evidence_kind=NP.SUPPORTED_ONLY_KIND,
        bits=EB.bits_of(origin="own_result", proof=True, proof_process=column,
                        kind="conjecture"))
    return {"ok": True, "stmt_id": str(seeded["stmt_id"]), "new_row": True}


def _is_proof_statement(store: Store, body: str = BODY) -> dict:
    return next(r for r in store.rows("statements")
                if str(r.get("statement_full") or "").strip() == body)


# ------------------------------------------------------------------ ① V 没审就不能 proof

def test_1_without_v_review_b_cannot_register_proof(tmp_path: pathlib.Path) -> None:
    """① V 没审 ⇒ B 登记拿不到 proof（改前：`verifications/` 不存在也 ok=True + proof）。

    这条用例复刻的是实测现场：真穷举实验跑完（`experiments` 那一行是 proof、E 的
    `e_signature` 也在），而 `verifications/` 目录根本不存在。
    """
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    env = _run_exhaustive(store)
    column = env["column"]
    # 现场：`verifications/` 不存在
    assert not (pathlib.Path(store.root) / VR.VERIFICATIONS_DIR).exists()
    # 而 E 的章照样在（这正是改前被当成"第三方签字"的那一串字）
    sig = NP.signature_of(env["row"])
    assert sig["signed_by"] == NP.PROOF_SIGNER and sig[NP.PROOF_AUTHORS_KEY] == ["E"], sig

    got = _file(store, column=column)
    assert got.get("ok") is False, f"V 没审却登记成 proof 了：{got}"
    assert got.get("kind") == "proof_needs_third_party_signature", got
    error = str(got.get("error") or "")
    assert "缺 V 的会审签名" in error, error
    # 一行都没落（受控拒绝，不是"落了再改"）
    assert list(store.rows("statements")) == [], list(store.rows("statements"))


def test_1b_e_self_signature_is_not_a_third_party_signature(
        tmp_path: pathlib.Path) -> None:
    """① 的另一半：E 的 `e_signature.signed_by="V"` 是 E 自己盖的章，不算第三方。

    判据只看盘上那份 `verifications/<命题号>.jsonl` 有没有那一签 —— 把 E 的章改成
    任何值都不该改变结论（这条负控防的是"把闸又接回 e_signature"）。
    """
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    env = _run_exhaustive(store)
    row = dict(env["row"])
    forged = dict((row.get("observations") or {}).get(NP.SIGNATURE_KEY) or {})
    forged["third_party"] = {"signed_by": "V", "verdict": "成立"}
    row["observations"] = {**(row.get("observations") or {}), NP.SIGNATURE_KEY: forged}
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row, note="forge")
    sync_counters(store)
    got = _file(store, column=env["column"])
    assert got.get("ok") is False and got.get("kind") == "proof_needs_third_party_signature", got


# ------------------------------------------------------------------ ② sha 对不上

def _assert_sha_mismatch_cannot_be_proof(store: Store) -> None:
    """② 的正文（被 ⑤ 打桩之后必须红的那一段）。"""
    env = _run_exhaustive(store)
    add_literature(store, S.format_id(0))
    filed = _file_conjecture(store, column=env["column"])
    assert filed.get("ok") is True, filed
    sid = str(filed["stmt_id"])
    # V 签的是"别的一份正文"（sha 对不上）—— 结论写成立也没用
    _ledger(store, sid, [{"verification_id": "v-000001", "proof_no": 1,
                          "verdict": "成立", "why": "看着没问题",
                          "proof_sha256": VR.proof_sha("另一份正文（不是这一份）"),
                          "at": TS}])
    got = _file(store, column=env["column"])
    assert got.get("ok") is False, f"sha 对不上却拿到了 proof：{got}"
    assert got.get("kind") == "proof_needs_third_party_signature", got
    error = str(got.get("error") or "")
    assert "缺 V 的会审签名" in error and "对不上" in error, error
    # 那一行仍然是猜想档（受控拒绝，没有把它升上去）
    assert _is_proof_statement(store)["evidence_kind"] != "proof"


def test_2_a_signature_on_another_version_is_not_a_signature(
        tmp_path: pathlib.Path) -> None:
    """② V 签「成立」但 `proof_sha256` 对不上 ⇒ 不许 proof（负控）。"""
    _assert_sha_mismatch_cannot_be_proof(_store(tmp_path))


# ------------------------------------------------------------------ ③ 最近一签是有毛病

def _assert_rejected_cannot_be_proof(store: Store) -> None:
    """③ 的正文（被 ⑤ 打桩之后必须红的那一段）。"""
    env = _run_exhaustive(store)
    add_literature(store, S.format_id(0))
    filed = _file_conjecture(store, column=env["column"])
    sid = str(filed["stmt_id"])
    sha = VR.proof_sha(env["column"])
    _ledger(store, sid, [
        # 先签「成立」，后来又改判「有毛病」⇒ 最近一签是有毛病（早先那一签不许救人）
        {"verification_id": "v-000001", "proof_no": 1, "verdict": "成立",
         "proof_sha256": sha, "at": TS},
        {"verification_id": "v-000002", "proof_no": 1, "verdict": "有毛病",
         "proof_sha256": sha, "why": "第 6 项：③ 写的是抽样", "defect_step": 6,
         "at": TS},
    ])
    got = _file(store, column=env["column"])
    assert got.get("ok") is False, f"最近一签是『有毛病』却拿到了 proof：{got}"
    assert got.get("kind") == "proof_needs_third_party_signature", got
    error = str(got.get("error") or "")
    assert "缺 V 的会审签名" in error, error
    assert "有毛病" in error, f"拒信没有点名最近一签的 verdict：{error}"
    assert "v-000002" in error, f"拒信没有指到最近那一签：{error}"


def test_3_the_latest_verdict_is_the_one_that_counts(tmp_path: pathlib.Path) -> None:
    """③ V 签「有毛病」⇒ 不许 proof，且点名最近一签 verdict（先成立后有毛病那一档）。"""
    _assert_rejected_cannot_be_proof(_store(tmp_path))


# ------------------------------------------------------------------ ④ 正控（端到端）

def test_4_a_real_v_review_unlocks_proof_end_to_end(tmp_path: pathlib.Path) -> None:
    """④ V 签「成立」且 sha 相符 ⇒ 允许 proof（端到端，一个模型调用都不发）。

    整条链：E 跑穷举实验（落 ②③ ⇒ 那一行是 proof）→ B 按猜想登记 → V 七项机械会审
    签「成立」→ B 把同一份内容再交一次、kind 改回定理级 ⇒ 秘书改那一行（不新建），
    行上落 `kind=theorem` + `evidence_kind=proof`，而那一签就在这条命题自己的台账里。
    """
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    env = _run_exhaustive(store)
    column = env["column"]

    # 未审 ⇒ 拒（同一份工作区里的对照组，改前的"ok=True"就是在这里出现的）
    assert _file(store, column=column).get("ok") is False
    # 先按猜想落库（V 只审在册的命题）
    filed = _file_conjecture(store, column=column)
    assert filed.get("ok") is True, filed
    sid = str(filed["stmt_id"])

    # V 真会审：同一份正文连审到发签门槛（2026-10-29：连续 3 次「成立」+ 秘书判定才签）
    reviewed = _review_until_signed(_v(store), sid, column)
    signed = reviewed[-1]
    assert signed.get("checked") is True and signed.get("verdict") == "成立", signed
    assert signed.get("signed_bit3") is True, signed
    ledger = pathlib.Path(store.root) / VR.VERIFICATIONS_DIR / f"{sid}.jsonl"
    assert ledger.is_file()
    # 前三签都留在台账里（第 1、2 次只落台账，不许因为"没发签"就不落行）
    rows, bad = VR.list_verifications(store.root, statement_id=sid, limit=None)
    assert bad == [] and len(rows) == int(VR.SIGN_STREAK_NEED), (bad, rows)

    # 签完之后同一份内容再交一次 ⇒ 允许 proof
    gate = NP.filing_problems(origin="own_result", evidence_kind="proof", proof_text=column,
                              experiments=store.rows("experiments"), root=store.root,
                              statements=store.rows("statements"), statement_full=BODY)
    assert gate == [], gate
    again = _file(store, column=column)
    assert again.get("ok") is True, again
    row = _is_proof_statement(store)
    assert row["kind"] == "theorem", row
    assert row["evidence_kind"] == "proof", row
    # 那一签盖的是这一条命题自己的台账（不是别人的签借光）
    got = NP.latest_third_party_sign(store.root, proof_text=column, statement_id=sid)
    assert got["checked"] and got["found"] and got["verdict"] == "成立", got
    assert got["proof_sha256"] == VR.proof_sha(column), got
    assert str(got["ledger"]).startswith(f"{VR.VERIFICATIONS_DIR}/{sid}.jsonl#"), got


# ------------------------------------------------------------------ ⑤ 反真空

def _stub_latest(monkeypatch: pytest.MonkeyPatch, *, verdict: str = "成立") -> None:
    """把"读 verifications 最近一签"打桩成恒成立（返回一签盖住任何正文/任何对象的签）。

    2026-11-03（`draft/154`）：读口多了 `object_sha256` / `object_path` 两个关键字
    （收工门按 E 报告的字节 sha 认签），返回值多了 `row` / `signable` 两格
    （「有毛病」的 `defect_step` 只在那一行上）。打桩必须按同一个形状回"签住了" ——
    否则这一条反真空会因为"桩少了键"而红，而不是因为"门信了桩"而红（那是两件事：
    前者说明桩过期了，后者才是判据没有反真空）。
    """
    def _fake(root: Any, *, proof_text: Any = "", statement_id: str = "",
              object_sha256: Any = "", object_path: Any = "") -> dict[str, Any]:
        sha = VR.proof_sha(str(proof_text or ""))
        row = {"verification_id": "v-000001", "verdict": verdict, "proof_sha256": sha,
               "object_sha256": str(object_sha256 or ""),
               "object_path": str(object_path or "")}
        return {"checked": True, "found": True, "verdict": verdict,
                "proof_sha256": sha, "object_sha256": str(object_sha256 or ""),
                "object_path": str(object_path or ""), "row": row, "signable": True,
                "stale": False, "stale_row": {}, "stale_ledger": "",
                "ledger": "verifications/000000.jsonl#v-000001",
                "why": "（打桩：恒成立）", "route": "statement"}

    monkeypatch.setattr(NP, "latest_third_party_sign", _fake, raising=True)


def test_5_stubbing_the_ledger_read_makes_2_and_3_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 反真空：把"读 verifications 最近一签"打桩成恒成立 ⇒ ② 与 ③ 必红。

    没有这一条，②③ 的绿色可能来自"判据根本没跑"：桩一打，"sha 对不上"和"最近一签是有
    毛病"都必须当场被放行（也就是原来的断言必须失败）。
    """
    _stub_latest(monkeypatch)
    for body in (_assert_sha_mismatch_cannot_be_proof, _assert_rejected_cannot_be_proof):
        with pytest.raises(AssertionError):
            body(_store(tmp_path / body.__name__))
