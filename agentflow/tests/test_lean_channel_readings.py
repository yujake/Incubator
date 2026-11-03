# -*- coding: utf-8 -*-
"""Lean 通道的真机读数：L 的核验 ⇒ `experiments` 行 ⇒ B 的登记 ⇒ 第 4 位 / 等级。

## 这一份判什么（业主 2026-11-04 的施工单）

背景（真机读数，2026-11-04）：全仓 33 条 `method="formal"` 行全部来自旧 E 路径，
0 条是 L 落的；0 处 `bits.evidence.formal_by_proof`、0 条 `bits.formal="verified"`。
也就是说「L 验过 ⇒ 第 4 位翻 ⇒ 等级到 theorem」这条链从未在真机走通过。
这一份把那条链钉成三条判据：

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | 真机端到端：L 真跑 Lean 核验 ⇒ `bits.formal={号: verified}`、`formal_by_proof` 有 payload、`grade="theorem"` | D28 之前第 4 位没有任何写者（`bits_of` 留 pending）⇒ 等级 `theorem` 从未可达；把 `evidencebits.formal_ledger_reading` 摘掉 ⇒ 这一条当场红 |
| b | 反真空：真 Lean 判不通过（`checked_failed`）⇒ `bits.formal={号: failed}`、等级不到 theorem | 把「查了不通过」折成 unknown（`tri_state` 不写 `checked_failed`）⇒ 第 4 位停在 pending，这一条红 |
| c | negative：`method="formal"` 但没绑到这条命题 ⇒ 第 4 位不被翻 | 把 `formal_ledger_reading` 的三道绑定点删掉（只按 `method` 认）⇒ 别条命题的 formal 行会翻这一位，这一条红 |

三条都是机器读数，不是文案：a/b 起真检查器（本机 `lean.EXE`，极小文件、不碰
Mathlib，一次编译 < 5s）；c 不起检查器（它判的是"绑定"这件事），但它的夹具里
那行 `experiments` 与 L `record` 落的那一行同形，并且先让「被绑定的那条命题真的翻」
（正控）再判未绑定的那条不动 —— 否则"不翻"可能只是"没有任何东西能翻"。

## 真 Lean 不可用时

a/b 需要真检查器：本机没有 `lean.EXE`、或自检不是 `usable` 时明确 skip 并把读数
写进理由，不伪装通过。c 不需要检查器，任何机器上都跑。

## 落点

所有工作区都建在 pytest 的 `tmp_path` 下，不往仓库里写任何东西。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.store import Store

#: 本机那一版真 Lean —— 取值点只有一处（`tests/conftest.py` 的 `lean_path()`）。
from conftest import lean_path

LEAN = lean_path()
HAVE_LEAN = LEAN.is_file()

#: 一条在册命题与它的一份证明正文（`#p1` 落行上的 `proof_text`）。
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"
LABEL = "弦长函数不是常值"
P1 = "1. 由定义直接得到。\n2. 由 1 与假设得结论。"

#: 极小 Lean 源码：不 import Mathlib（避免 10s+ 编译），一条具名定理。
LEAN_REL = "code/formal/probe.lean"
LEAN_GOOD = "namespace LProbe\n\ntheorem probe : 1 = 1 := rfl\n\nend LProbe\n"
#: 反控：假的（`rfl` 证不出 `1 = 2`）。
LEAN_BAD = "namespace LProbe\n\ntheorem probe : 1 = 2 := rfl\n\nend LProbe\n"


# ============================================================ 夹具与小工具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _own(full: str = FULL, label: str = LABEL) -> dict:
    """自产命题的必填件（`origin="own_result"`：`doc_id` + `quote_reason` + 猜想入口）。"""
    return {"statement_full": full, "statement_text": label, "origin": "own_result",
            "kind": "conjecture", "doc_id": S.format_id(0),
            "quote_reason": "我方自产命题，没有外部引文要比对", "label": label}


def _seed(store: Store, *, full: str = FULL, label: str = LABEL,
          proof_text: str = P1) -> str:
    """铺一条在册命题（真机 3134 条 own_result 历史行的同形：没有 V 签）。

    第 2 位显式写真：这一行确实有一份 `proof_text`。不写它，`derive_grade` 的
    `has_proof` 就是假 —— 那时等级到不了 theorem 与形式化这一位无关，判据会变成
    空转（业主的链是"有证明 + 形式化通过 ⇒ theorem"，两半都得在）。
    """
    bits = EB.with_optimized_defaults(
        EB.bits_of(origin="own_result", proof=True, proof_process=proof_text,
                   kind="conjecture"), [1])
    with store.tx("statements", actor="agent-B") as tx:
        sid = str(tx.alloc_id(S.TABLES["statements"]["id_kind"]))
        tx.upsert("statements", {
            "stmt_id": sid, "origin": "own_result", "kind": "conjecture",
            "label": label, "statement_text": label, "statement_full": full,
            "proof_text": proof_text, "status": "active",
            "created_at": S.now_iso(), "created_by": "agent-B",
            "quote_verified": None,
            "quote_reason": "我方自产命题，没有外部引文要比对", "bits": bits,
        })
    return sid


def _row(store: Store, sid: str) -> dict:
    hit = [dict(r) for r in store.rows("statements")
           if str(r.get("stmt_id") or "") == sid]
    assert hit, f"盘上读不到命题 {sid}"
    return hit[0]


def _bits(store: Store, sid: str) -> dict:
    return EB.bits_from_row(_row(store, sid))


def _experiment(store: Store, experiment_id: str) -> dict:
    hit = [dict(r) for r in store.rows("experiments")
           if str(r.get("experiment_id") or "") == experiment_id]
    assert hit, f"盘上读不到实验行 {experiment_id}"
    return hit[0]


def _sync(store: Store, agent_b: AgentB, *, full: str = FULL, label: str = LABEL,
          proof_text: str = P1) -> dict:
    """B 的登记入口再走一遍（D28 的写侧：第 4 位从 L 的台账同步进命题那一行）。"""
    return agent_b.register_statement(**_own(full, label),
                                      proofs=[{"proof_no": 1, "text": proof_text}])


def _lean_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentflow import agent_prompts as AP
    from agentflow import leantoolchain as LT

    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1")
    if HAVE_LEAN:
        monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


def _skip_unless_usable(root: pathlib.Path) -> None:
    """真检查器不在 / 自检不过 ⇒ 明确 skip 并把读数写进理由（不伪装通过）。"""
    from agentflow import leantoolchain as LT

    if not HAVE_LEAN:
        pytest.skip(f"本机没有 {LEAN} ⇒ 这一条要真跑检查器，跳过（不伪装通过）")
    reading = LT.lean_selfcheck_reading(root=root)
    if str(reading.get("state")) != "usable":
        pytest.skip(
            f"Lean 自检不是 usable（state={reading.get('state')}；"
            f"problems={reading.get('problems')}）⇒ 这一条要真跑检查器，跳过（不伪装通过）")


def _assert_chain_reaches_theorem(bits: dict, *, experiment_id: str,
                                  proof_sha256: str) -> None:
    """a 的断言本体（抽出来给反真空那一条在退化读数上跑一遍并看着它红）。"""
    assert bits.get("formal") == {"1": "verified"}, (
        "第 4 位不是 {号: verified}：L 的核验没有落进命题那一行", bits.get("formal"))
    assert EB.formal_by_proof(bits) == {1: "verified"}, (
        "逐条读数不对", EB.formal_by_proof(bits))
    payload = dict(EB.formal_evidence_by_proof(bits).get(1) or {})
    assert payload.get("experiment_id") == experiment_id, (
        "凭据没有指回那一行 `experiments`", payload)
    assert str(payload.get("proof_sha256") or "") == proof_sha256, (
        "凭据里记的不是这一份证明正文的 sha（验过 ≠ 验的是现行那一份）", payload)
    assert str(payload.get("checker") or "").startswith("lean"), (
        "凭据里没有检查器的名字", payload)
    assert bits.get("proof") is True, (
        "反真空：第 2 位不是真 ⇒ 这里的 theorem 与形式化这一位无关", bits.get("proof"))
    assert bits.get("grade") == "theorem", (
        "第 2 位 + 第 4 位通过 ⇒ 等级必须是 theorem", bits.get("grade"))


def _assert_fourth_bit_not_flipped(bits: dict) -> None:
    """c 的断言本体（抽出来给反真空那一条跑一遍并看着它红）。"""
    assert EB._bit_state(bits, EB.FORMAL_BIT) != "verified", (
        "第 4 位被一条没绑到这条命题的形式化行翻成了 verified", bits.get("formal"))
    assert "verified" not in EB.formal_by_proof(bits).values(), (
        "逐条读数里出现了不是这条命题的 verified",
        EB.formal_by_proof(bits))
    assert bits.get("grade") != "theorem", (
        "没验过这条命题却到了 theorem", bits.get("grade"))


# ============================================================ a. 真机端到端

def test_a_real_lean_verification_reaches_the_fourth_bit_and_theorem(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a：L 真跑 Lean 核验 ⇒ `bits.formal={1: verified}`、`formal_by_proof` 有 payload、
    `grade=theorem`。

    走的是生产入口：`AgentL.record`（`agent_l/record.py` 的动作本体，自己现跑一次
    检查器）与 `AgentB.register_statement`（`_bits_with_formal` 的唯一调用点）。
    """
    from agentflow.agent_l import AgentL

    st = _ws(tmp_path)
    lean_dir = st.root / "code" / "formal"
    lean_dir.mkdir(parents=True, exist_ok=True)
    (lean_dir / "probe.lean").write_text(LEAN_GOOD, encoding="utf-8")
    sid = _seed(st)

    _lean_on(monkeypatch)
    _skip_unless_usable(st.root)

    agent_l = AgentL(st, workspace_root=st.root)
    recorded = agent_l.record(sid, LEAN_REL, proof_no=1, declaration_name="probe",
                              path_source="B")
    assert recorded.get("recorded") is True, (
        f"`record` 没落行（reason={recorded.get('reason')!r}）：{recorded.get('detail')!r}",
        recorded)
    assert recorded.get("status") == "verified" and recorded.get("verified") is True, (
        "真 Lean 没验过这一份（那这一条判据无从谈起）", recorded)
    assert recorded.get("evidence_kind") == "proof", (
        "检查器说 verified 而这一行不是 proof 档", recorded.get("evidence_kind"))
    assert str(recorded.get("proof_sha256") or "") == VR.proof_sha(P1), (
        "记下来的 sha 不是该命题现行 `proof_text` 的", recorded.get("proof_sha256"))

    eid = str(recorded["experiment_id"])
    exp = _experiment(st, eid)
    assert exp.get("method") == "formal", exp.get("method")
    assert exp.get("evidence_kind") == "proof", exp.get("evidence_kind")
    obs = dict(exp.get("observations") or {})
    assert obs.get("statement_id") == sid and exp.get("claim_key") == f"stmt:{sid}", obs
    assert obs.get("tri_state") == "verified", (
        "三态不是 verified（没查成与查通了不许折成一件事）", obs.get("tri_state"))
    assert obs.get("proof_no") == 1 and obs.get("proof_sha256") == VR.proof_sha(P1), obs
    assert str(obs.get("checker") or "").startswith("lean"), obs.get("checker")

    # L 的写集只有 experiments：B 登记之前命题那一行的第 4 位还是"没验过"。
    before = _bits(st, sid)
    assert EB._bit_state(before, EB.FORMAL_BIT) == "pending", (
        "L 的 `record` 自己改了 `statements`（它的写集里没有这一格）", before.get("formal"))

    agent_b = AgentB(st, extractor=None, extract_text=None, config={})
    synced = _sync(st, agent_b)
    after = _bits(st, sid)
    _assert_chain_reaches_theorem(after, experiment_id=eid,
                                  proof_sha256=VR.proof_sha(P1))
    assert EB.derive_grade(after) == "theorem", (
        "等级不是从五元位现算的 theorem", EB.derive_grade(after))
    assert synced.get("formal_paths") == {"1": "verified"}, (
        "写侧没把 L 的读数同步成第 4 位", synced.get("formal_paths"))
    assert synced.get("ok") is True, synced


# ============================================================ b. 反真空（查了不通过）

def test_b_a_failed_lean_result_lands_failed_and_never_theorem(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：真 Lean 判不通过 ⇒ `bits.formal={1: failed}`、等级不到 theorem。

    反真空的那一半在最后两句：第 2 位仍是真（这条命题确实有证明），所以"不到
    theorem"只能由第 4 位解释；而那一位必须是 `failed`，不能是 `pending`
    （把"查了不通过"折成"没查"是这一条守的第二种病）。
    """
    from agentflow.agent_l import AgentL

    st = _ws(tmp_path)
    lean_dir = st.root / "code" / "formal"
    lean_dir.mkdir(parents=True, exist_ok=True)
    (lean_dir / "probe.lean").write_text(LEAN_BAD, encoding="utf-8")
    sid = _seed(st)

    _lean_on(monkeypatch)
    _skip_unless_usable(st.root)

    agent_l = AgentL(st, workspace_root=st.root)
    recorded = agent_l.record(sid, LEAN_REL, proof_no=1, declaration_name="probe",
                              path_source="B")
    assert recorded.get("recorded") is True, recorded
    assert recorded.get("status") == "failed", (
        "假命题没被判成 failed", recorded.get("status"))
    assert recorded.get("verified") is False, recorded
    assert recorded.get("evidence_kind") != "proof", (
        "一条没过检查器的行被记成了 proof 档", recorded.get("evidence_kind"))

    exp = _experiment(st, str(recorded["experiment_id"]))
    assert dict(exp.get("observations") or {}).get("tri_state") == "checked_failed", (
        "「查了不通过」没有落成 checked_failed（折成 not_checked 就等于没查）",
        (exp.get("observations") or {}).get("tri_state"))

    agent_b = AgentB(st, extractor=None, extract_text=None, config={})
    synced = _sync(st, agent_b)
    after = _bits(st, sid)
    assert after.get("formal") == {"1": "failed"}, (
        "第 4 位不是 failed", after.get("formal"))
    assert EB.formal_by_proof(after) == {1: "failed"}, EB.formal_by_proof(after)
    assert after.get("proof") is True, (
        "反真空：第 2 位不是真 ⇒ 这里的「不到 theorem」不是第 4 位造成的",
        after.get("proof"))
    assert after.get("grade") != "theorem", (
        "检查器判了不通过，等级却到了 theorem", after.get("grade"))
    assert synced.get("formal_paths") == {"1": "failed"}, synced.get("formal_paths")
    assert synced.get("ok") is True, synced


# ============================================================ c. negative（没绑这条命题）

def _put_unbound_formal_experiment(store: Store, *, bound_sid: str,
                                   proof_text: str) -> str:
    """造一行 `method="formal"` 且绑到「别条命题」的 `experiments`（与 L 落的那行同形）。"""
    obs = {
        "verifier_status": "verified", "formal_reason": "verified", "checked": True,
        "tri_state": "verified", "missing_imports": [], "lean_version": "4.7.0",
        "status": "verified", "checker_status": "verified", "verified": True,
        "checker_verified": True, "status_source": "checker", "downgraded": False,
        "checker": "lean 4.7.0", "checker_claimed": "",
        "output_sha256": "b" * 64,
        "statement_id": bound_sid, "statement_evidence_kind": "",
        "declaration_name": "LProbe.probe", "code_hash": "a" * 64,
        "recorded_by": "agent-L", "proof_no": 1, "path_id": "",
        "proof_sha256": VR.proof_sha(proof_text), "path_source": "B",
    }
    with store.tx("experiments", actor="agent-L") as tx:
        eid = str(tx.alloc_id("experiment"))
        row = S.Experiment(
            experiment_id=eid, claim="别的命题", claim_key=f"stmt:{bound_sid}",
            method="formal", evidence_kind="proof", result="supports",
            negation_kind="not_proved", code_path=LEAN_REL, code_hash="a" * 64,
            exit_code=0, verifier_output="'LProbe.probe' does not depend on any axioms",
            verifier_subject_key=f"stmt:{bound_sid}",
            created_at=S.now_iso(), created_by="agent-L",
            observations=obs,
            params={"checker": "lean 4.7.0", "statement_id": bound_sid,
                    "proof_no": 1, "path_id": "",
                    "proof_sha256": obs["proof_sha256"], "path_source": "B"},
        )
        row.validate()
        tx.upsert("experiments", row.to_dict(), note="probe:formal")
    return eid


def test_c_a_formal_row_bound_to_another_statement_does_not_flip_this_bit(
        tmp_path: pathlib.Path) -> None:
    """c：`method="formal"` 但没绑到这条命题 ⇒ 第 4 位不被翻。

    正控（这一条不能省）：同一行确实翻了它绑定的那条命题（B 到 verified 与
    theorem）—— 于是"A 没被翻"不是"这一行是死的"，而是"绑定判据在起作用"。
    """
    st = _ws(tmp_path)
    # 两条命题的证明正文故意相同：这样"绑定"是唯一的区别 —— 把
    # `formal_ledger_reading` 的三道绑定点删掉时，A 会立刻读到 verified（判据变红）。
    sid_a = _seed(st, full="设 G 是 3-正则群；则弦长函数不是常值。",
                  label="A：弦长函数不是常值", proof_text=P1)
    sid_b = _seed(st, full="设 H 是 4-正则群；则直径不超过二。",
                  label="B：直径不超过二", proof_text=P1)

    eid = _put_unbound_formal_experiment(st, bound_sid=sid_b, proof_text=P1)
    assert _experiment(st, eid).get("method") == "formal"

    agent_b = AgentB(st, extractor=None, extract_text=None, config={})

    # ---- 正控：这一行是活的（绑定的那条命题真的翻成 verified / theorem）。
    synced_b = agent_b.register_statement(
        **_own("设 H 是 4-正则群；则直径不超过二。", "B：直径不超过二"),
        proofs=[{"proof_no": 1, "text": P1}])
    bits_b = _bits(st, sid_b)
    assert EB._bit_state(bits_b, EB.FORMAL_BIT) == "verified", (
        "夹具退化了：这一行没有把绑定的那条命题翻成 verified", bits_b.get("formal"))
    assert bits_b.get("grade") == "theorem", bits_b.get("grade")
    assert synced_b.get("ok") is True, synced_b

    # ---- 判据：未绑定的那条命题一个字都不许翻。
    synced_a = agent_b.register_statement(
        **_own("设 G 是 3-正则群；则弦长函数不是常值。", "A：弦长函数不是常值"),
        proofs=[{"proof_no": 1, "text": P1}])
    assert synced_a.get("formal_synced") is not True, (
        "B 的返回值说它同步了 A 的形式化位（它绑的是别条命题）", synced_a)
    bits_a = _bits(st, sid_a)
    _assert_fourth_bit_not_flipped(bits_a)
    assert bits_a.get("formal") in ("pending", {"1": "pending"}), (
        "A 的第 4 位不是「没验过」的形态", bits_a.get("formal"))


# ============================================================ ⑧ 反真空（判据自己会红）

def test_the_three_assertions_are_not_vacuous() -> None:
    """反真空：把 a/c 的断言套在"坏了"的读数上，必须当场红（否则它们只是空转）。"""
    good = EB.bits_of(proof=True, proof_process=P1, kind="conjecture",
                      formal={"1": "verified"},
                      formal_evidence={"1": {"checker": "lean 4.7.0",
                                             "experiment_id": "000001",
                                             "proof_sha256": VR.proof_sha(P1)}})
    _assert_chain_reaches_theorem(good, experiment_id="000001",
                                  proof_sha256=VR.proof_sha(P1))
    # 第 4 位停在 pending ⇒ a 的断言必须红（D28 之前就是这个形态）。
    pending = EB.bits_of(proof=True, proof_process=P1, kind="conjecture")
    with pytest.raises(AssertionError):
        _assert_chain_reaches_theorem(pending, experiment_id="000001",
                                      proof_sha256=VR.proof_sha(P1))
    # 没绑定的读数被套上 verified ⇒ c 的断言必须红。
    flipped = EB.bits_of(proof=True, proof_process=P1, kind="conjecture",
                         formal={"1": "verified"},
                         formal_evidence={"1": {"checker": "lean 4.7.0"}})
    with pytest.raises(AssertionError):
        _assert_fourth_bit_not_flipped(flipped)
