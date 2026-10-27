# -*- coding: utf-8 -*-
"""第 4 位（形式化通过）是二维的：`{证明号: 状态}`（业主 2026-10-22 的裁定）。

## 裁定原文（逐字）

> 「一个定理有多种证明路径，lean 形式化需指明对哪个路径做了形式化验证，即五元判据有关
>   形式化的那一位也要改成二维列表。但关于一个定理的正确性，但凡任意一个路径通过核验，
>   它就是对的」

补裁：「L 可以通过 C 的建议选择路径，也可以由 B 指定路径，也可以自行决定，只是在标记和
五元位更新时要忠实」。

## 这一份判据守的八件事（每条都写明"改前红在哪"）

| # | 判据 | 改前红在哪 |
|---|---|---|
| ① | OR：`{"1":"verified","2":"pending"}` ⇒ 汇总 verified、等级 theorem，且明细不被压平 | `_state({"1":…})` 把 dict 折成 pending ⇒ 恒 conjecture |
| ② | 单路径 failed 不许抬档；`{"1":"verified","2":"failed"}` 汇总 verified 而 `#p2` 读 failed | 同上（dict 一律 pending） |
| ③ | 不借光：收工门的逐条 `(stmt, proof_no)` 里 `#p1` 拿不到 `#p2` 的 theorem | `per = dict(bits)` 把汇总 formal 发给每一条 |
| ④ | 二维 dict 喂给任何读点都不许被读成 pending（死判据：改回 `_state` 直读必红） | `_state` 对 dict 静默给 pending（`evidencebits.py` 那三行） |
| ⑤ | 多路径未给号 ⇒ `proof_path_unspecified` 且盘上无新文件；只有 `#p1` ⇒ 不拒 | `formalize` 根本没有"哪一份证明"这个概念 |
| ⑥ | 忠实：`observations.proof_sha256` 等于现行那一份正文的 sha，不等 ⇒ 该路径 stale；`path_source` 三值落盘，"谁选的"与"谁验的"分开 | 没有 `proof_no` / `proof_sha256` / `path_source` 三格 |
| ⑦ | D28：L verified ⇒ 第 4 位真的变成 verified（改前恒 pending、theorem 从未可达） | `bits.formal` 没有任何写者 |
| ⑧ | 反真空：夹具至少一条两路径行；退化成只有 `#p1` ⇒ ① 必红；`bit_evidence_gaps` 传空 experiments 的假绿要被点名 | — |

## 真 Lean

只有 ⑦（端到端）那一条要真检查器：本机那一版用绝对路径（PATH 上可能是别的东西）。
文件不在或自检不是 usable 时如实 skip 并把读数写进理由（不伪装通过）。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

from agentflow import closing as CL
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.store import Store

#: 本机那一版真 Lean（绝对路径，不依赖 PATH）。
#: 真 Lean 的落点：`AGENTFLOW_LEAN_BIN` 优先、没设才退回本机那一版 —— 取值点只有一处
#: （`tests/conftest.py` 的 `lean_path()`；本文件不再写第二份绝对路径）。
from conftest import lean_path

LEAN = lean_path()
HAVE_LEAN = LEAN.is_file()

#: 两条证明路径（`#p1` 落行上的 `proof_text`，`#p2` 落清单）。
P1 = "1. 由定义直接得到。\n2. 由 1 与假设得结论。"
P2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
P2_EDITED = P2 + "\n3. 补一步（这一句是改成这一版之后才有的）。"

#: 声明成猜想（B-2 的入口判据）—— 升档由五元位现算，与入口那一栏无关。
_FULL = "设 G 是 3-正则群；则弦长函数不是常值。"
_LABEL = "弦长函数不是常值"

_OK = {"verdict": "成立", "findings": []}


# ============================================================ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _own() -> dict:
    """自产命题的必填件（`origin="own_result"`：`doc_id` + `quote_reason` + 猜想入口）。"""
    return {"statement_full": _FULL, "statement_text": _LABEL, "origin": "own_result",
            "kind": "conjecture", "doc_id": S.format_id(0),
            "quote_reason": "我方自产命题，没有外部引文要比对", "label": _LABEL}


def _register(store: Store, agent_b: AgentB, *, proofs: bool = True) -> dict:
    """B 把这条定理登记成两路径（`#p1` + `#p2`）。"""
    if not proofs:
        return agent_b.register_statement(**_own(), proof_text=P1)
    return agent_b.register_statement(
        **_own(), proofs=[{"proof_no": 1, "text": P1}, {"proof_no": 2, "text": P2}])


def _row(store: Store, sid: str) -> dict:
    hit = [dict(r) for r in store.rows("statements") if str(r.get("stmt_id") or "") == sid]
    assert hit, f"盘上读不到命题 {sid}"
    return hit[0]


def _put_formal_experiment(store: Store, *, sid: str, proof_no: int,
                           proof_text: str, verified: bool = True,
                           path_source: str = "B", experiment_id: str = "000007") -> dict:
    """造一行 L 的形式化台账（与 `agent_l/record.py` 落的那一行同形）。

    只造行、不起检查器：这一份判据测的是"那一行怎么被读成第 4 位"，
    真检查器那一路由 ⑦（端到端）覆盖。
    """
    obs = {
        "status": "verified" if verified else "unknown",
        "checker_status": "verified" if verified else "not_checked",
        "verified": verified,
        "checker_verified": verified,
        "checker": "lean 4.7.0",
        "statement_id": sid,
        "code_hash": "a" * 64,
        "recorded_by": "agent-L",
        "tri_state": "verified" if verified else "not_checked",
        # 这一格是"这次形式化验的是哪一份正文"的指纹（判据 ⑥ 就咬它）。
        "proof_no": proof_no,
        "path_id": "p%dg1" % proof_no,
        "proof_sha256": VR.proof_sha(proof_text),
        "path_source": path_source,
    }
    row = S.Experiment(
        experiment_id=experiment_id, claim=_FULL, claim_key=f"stmt:{sid}",
        method="formal", evidence_kind="proof" if verified else "heuristic",
        result="supports" if verified else "inconclusive", negation_kind="not_proved",
        code_path=f"code/formal/probe__p{proof_no}.lean", code_hash="a" * 64,
        exit_code=0 if verified else None, verifier_output="no goals" if verified else "",
        # 硬约束 2b：检查器输出管的就是这一行声称的命题（`claim_key` 同一个值）。
        verifier_subject_key=f"stmt:{sid}",
        created_at=S.now_iso(), created_by="agent-L",
        observations=obs,
        params={"checker": "lean 4.7.0", "statement_id": sid, "proof_no": proof_no,
                "path_id": "p%dg1" % proof_no, "proof_sha256": obs["proof_sha256"],
                "path_source": path_source},
    )
    row.validate()
    with store.tx("experiments", actor="test", note="probe:formal") as tx:
        tx.upsert("experiments", row.to_dict(), note="probe:formal")
    return row.to_dict()


def _sync(store: Store, agent_b: AgentB) -> dict:
    """B 再登记一次（这是 D28 的写侧：第 4 位从 L 的台账同步进命题那一行）。"""
    return agent_b.register_statement(
        **_own(), proofs=[{"proof_no": 1, "text": P1}, {"proof_no": 2, "text": P2}])


def _sign(store: Store, *, sid: str, text: str, proof_no: int) -> dict:
    """V 的签名写入口（不经模型）。"""
    return VR.record_verification(store.root, statement_id=sid, proof_text=text,
                                  verdict=dict(_OK), verifier="agent-V", store=store,
                                  proof_no=proof_no)


def _two_path_fixture(tmp_path: pathlib.Path, *, verified_no: int = 1
                      ) -> tuple[Store, str, AgentB]:
    """一条两路径的命题 + 第 `verified_no` 条路径验过 ⇒ 返回 `(store, 命题号, B)`。"""
    st = _ws(tmp_path)
    agent_b = AgentB(st, extractor=None, extract_text=None, config={})
    first = _register(st, agent_b)
    assert first.get("ok") is True, first
    sid = str(first["stmt_id"])
    texts = {1: P1, 2: P2}
    _put_formal_experiment(st, sid=sid, proof_no=verified_no,
                           proof_text=texts[verified_no])
    synced = _sync(st, agent_b)
    assert synced.get("ok") is True, synced
    return st, sid, agent_b


# ============================================================ ① OR（一刀两断：汇总 / 明细）

def _assert_or_criterion(bits: dict) -> None:
    """① 的那条断言（单独抽出来：反真空那一条要把它在退化夹具上跑一遍并看着它红）。"""
    assert set(bits["formal"]) == {"1", "2"}, (
        "明细被压平了：二维位必须逐条留着（改前 `_state(dict)` 把它折成一个 pending）",
        bits["formal"])
    assert EB._bit_state(bits, EB.FORMAL_BIT) == "verified", (
        "任一路径 verified 就必须汇总成 verified（裁定的第二句）", bits["formal"])
    assert bits["grade"] == "theorem", ("第 2 位 + 任一路径形式化通过 ⇒ 正式定理", bits["grade"])
    assert EB.formal_by_proof(bits) == {1: "verified", 2: "pending"}, (
        "逐条读数必须是 {1: verified, 2: pending}", EB.formal_by_proof(bits))
    assert EB.formal_evidence_by_proof(bits).get(1, {}).get("checker") == "lean4", (
        "第 1 条路径的凭据不许丢", EB.formal_evidence_by_proof(bits))


def test_or_any_verified_path_makes_the_theorem_and_the_detail_stays() -> None:
    """①：`{"1":"verified","2":"pending"}` ⇒ 汇总 verified、等级 theorem、明细逐条在。"""
    bits = EB.bits_of(proof=True, proof_process="逐步论证……",
                      formal={"1": "verified", "2": "pending"},
                      formal_evidence={"1": {"checker": "lean4"}})
    _assert_or_criterion(bits)
    # 反真空（与 ⑧ 的两条互补）：这一条真的读到了二维，而不是"两张键都空"式的通过。
    assert len(EB.formal_by_proof(bits)) == 2, bits["formal"]


# ============================================================ ② 单路径 failed

def test_a_failed_path_is_not_promoted_and_its_neighbour_states_are_kept() -> None:
    """②：failed 不许抬档；另一条 verified 时汇总 verified 而 failed 那条仍读 failed。"""
    only_failed = EB.bits_of(proof=True, proof_process="逐步论证……",
                             formal={"1": "failed", "2": "pending"},
                             formal_evidence={"1": {"output": "error: type mismatch"}})
    assert EB._bit_state(only_failed, EB.FORMAL_BIT) == "failed", only_failed["formal"]
    assert only_failed["grade"] != "theorem", ("一条 failed 不许派生出定理", only_failed["grade"])
    assert EB.formal_by_proof(only_failed) == {1: "failed", 2: "pending"}, (
        EB.formal_by_proof(only_failed))

    mixed = EB.bits_of(proof=True, proof_process="逐步论证……",
                       formal={"1": "verified", "2": "failed"},
                       formal_evidence={"1": {"checker": "lean4"},
                                        "2": {"output": "error: type mismatch"}})
    assert EB._bit_state(mixed, EB.FORMAL_BIT) == "verified", (
        "任一路径通过即通过（这条定理是对的），而明细里 #p2 仍是 failed", mixed["formal"])
    assert EB.formal_by_proof(mixed)[2] == "failed", (
        "汇总 verified 不许把 #p2 的 failed 擦掉", EB.formal_by_proof(mixed))
    assert mixed["grade"] == "theorem", mixed["grade"]


# ============================================================ ③ 不借光（收工门的逐条键）

def test_closing_does_not_let_proof_one_borrow_proof_twos_theorem(tmp_path: pathlib.Path) -> None:
    """③：`#p2` 验过、`#p1` 没验 ⇒ 收工门的逐条读数里 `#p1` 只是预备定理级。"""
    st, sid, _b = _two_path_fixture(tmp_path, verified_no=2)
    row = _row(st, sid)
    assert EB.formal_by_proof(row) == {1: "pending", 2: "verified"}, (
        "第 4 位没按路径分开（写侧没落位）", row.get("bits"))
    _sign(st, sid=sid, text=P1, proof_no=1)
    _sign(st, sid=sid, text=P2, proof_no=2)

    _n, detail = CL._leg_reading(st, "reviewed_proof_rows", st.root)
    grades = {(str(c["stmt_id"]), int(c["proof_no"])): str(c["grade"])
              for c in detail["counted"]}
    assert grades.get((sid, 1)) == "pre_theorem", (
        "#p1 借了 #p2 的定理：它自己没有形式化通过，最多到预备定理级", (sid, grades))
    assert grades.get((sid, 2)) == "theorem", ("#p2 才是那条形式化通过的路径", (sid, grades))

    # 逐条读数那一侧（`statement_review_reading`）里也各是各的：这是同一条判据的第二个落点。
    reading = VR.statement_review_reading(st.root, row)
    per = {int(p["proof_no"]): p for p in reading["proofs"]}
    assert per[1]["formal"] == "pending" and per[2]["formal"] == "verified", (
        "逐条 formal 读数没分开", {no: p["formal"] for no, p in per.items()})
    assert per[1]["grade"] == "pre_theorem" and per[2]["grade"] == "theorem", (
        "逐条等级没分开", {no: p["grade"] for no, p in per.items()})


# ============================================================ ④ 二维 dict 不许落进 _state

def test_no_read_point_feeds_a_mapping_into_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """④：任何读点都不许把二维 dict 交给 `_state`（它会给 pending）。

    判据的形态是"记账"而不是"读结果"：把 `_state` 换成一个记录器，二维位跑一遍
    四个读点（`bits_from_row` / `derive_grade` / `bit_problems` / `bit_evidence_gaps`），
    只要有一次收到 Mapping 就红。改前 `derive_grade` 与 `bit_problems` 都是
    `_state(bits.get("formal"))` —— 第一处就会红。
    """
    seen: list[object] = []
    original = EB._state

    def _recording(value: object) -> str:
        seen.append(value)
        return original(value)

    monkeypatch.setattr(EB, "_state", _recording)
    bits = EB.bits_of(proof=True, proof_process="逐步论证……",
                      formal={"1": "verified", "2": "pending"},
                      formal_evidence={"1": {"checker": "lean4",
                                             "experiment_id": "000007"}})
    row = {"stmt_id": "000001", "origin": "own_result", "kind": "theorem",
           "proof_text": "逐步论证……", "bits": bits}
    got = EB.bits_from_row(row)
    assert got["grade"] == "theorem", got
    assert EB.derive_grade(got) == "theorem", got
    EB.bit_problems(got)
    EB.bit_evidence_gaps(row, experiments=[])
    offenders = [value for value in seen if isinstance(value, dict)]
    assert offenders == [], (
        "有读点把二维 dict 交给了 `_state`（它会静默给 pending）", offenders)


def test_reverting_to_a_direct_state_read_turns_the_reading_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 的负控：把唯一读口换回"直接 `_state`" ⇒ ① 的读数当场红。

    没有这一条，上面那条只是"今天这么写的"；有了它，"改回旧读法"是一种能被判据
    抓住的改动（改前正是那种读法：二维 dict ⇒ pending ⇒ 恒 conjecture）。
    """
    bits = EB.bits_of(proof=True, proof_process="逐步论证……",
                      formal={"1": "verified", "2": "pending"},
                      formal_evidence={"1": {"checker": "lean4"}})
    assert EB.derive_grade(bits) == "theorem", bits["grade"]
    with pytest.raises(ValueError):
        # 旧读法就是这一行；`_state` 现在对 Mapping 直接拒绝（不许静默折成 pending）。
        EB._state(bits.get(EB.FORMAL_BIT))
    # 折平之后再派生：等级掉回猜想 —— 这正是改前的读数，也是这一条要防的回归。
    flattened = {key: value for key, value in bits.items()}
    flattened[EB.FORMAL_BIT] = "pending"
    assert EB.derive_grade(flattened) == "conjecture", flattened["grade"]


# ============================================================ ④b 秘书的待办收件箱

def _statement_with_formal(store: Store, formal: dict, *, evidence: dict | None = None,
                           stmt_id: str = "000001") -> dict:
    """造一条只有第 4 位不同的命题行（其余位够用即可）。"""
    bits = EB.bits_of(proof=True, proof_process="逐步论证……", formal=formal,
                      formal_evidence=evidence or {})
    row = S.Statement(stmt_id=stmt_id, origin="own_result", kind="conjecture",
                      statement_full="设 G 是 3-正则群；则弦长函数不是常值。",
                      proof_text="逐步论证……", quote_reason="我方自产命题",
                      created_at=S.now_iso(), bits=bits)
    row.validate()
    with store.tx("statements", actor="test", note="probe:bits") as tx:
        tx.upsert("statements", row.to_dict(), note="probe:bits")
    return row.to_dict()


def test_the_secretary_inbox_reads_the_two_dimensional_bit(tmp_path: pathlib.Path) -> None:
    """④b：待办收件箱对二维位的判据 —— 全 pending ⇒ 待办；任一非 pending ⇒ 不待办。

    改前 `secretary.py` 的 Mapping 支读 `state.get("state", state.get("value"))`：对
    `{证明号: 状态}` 只会取到空 ⇒ 一条已经验过的命题也会被列进待办（"这一位没有值"），
    而它明明有值。这一条把两种状态各跑一次（同一份夹具，只差第 4 位）。
    """
    from agentflow.secretary import Secretary

    def _formal_todos(store: Store) -> int:
        sec = Secretary("B", root=store.root, store=store)
        inbox = sec.pending_inbox(scope="global")
        assert inbox.get("checked") is True, inbox
        return len([i for i in inbox.get("items") or [] if i.get("missing") == "formal"])

    pending_dir = _ws(tmp_path / "pending")
    _statement_with_formal(pending_dir, {"1": "pending", "2": "pending"})
    assert _formal_todos(pending_dir) == 1, (
        "全 pending 的二维位必须是一条待办（还没做）")

    done_dir = _ws(tmp_path / "done")
    _statement_with_formal(done_dir, {"1": "verified", "2": "pending"},
                           evidence={"1": {"checker": "lean4"}})
    assert _formal_todos(done_dir) == 0, (
        "任一路径有结论（verified）⇒ 这一位不是待办（改前它被读成「没有值」）")


# ============================================================ ⑤ 多路径未给号 ⇒ 拒（一个字节不写）

def _lean_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """关掉 Lean：这一组测的是路径那两道闸，不是检查器（它连不上时不该被当成没拒）。"""
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "0")
    from agentflow import agent_prompts as AP
    from agentflow import leantoolchain as LT

    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


_SOURCE = (
    "import Init.Data.Nat.Basic\n"
    "\n"
    "namespace LProbe\n"
    "\n"
    "theorem probe (n : Nat) : n + 0 = n := by\n"
    "  rfl\n"
    "\n"
    "-- step 1\n"
    "-- step 2\n"
    "\n"
    "end LProbe\n"
)


def _formal_files(tmp_path: pathlib.Path) -> list[str]:
    directory = tmp_path / "ws" / "code" / "formal"
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir())


def test_a_multi_path_statement_without_a_number_is_refused_and_writes_nothing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤：有两条证明而不给号 ⇒ `proof_path_unspecified`，且 `code/formal` 里没有新文件。"""
    from agentflow.agent_l import AgentL

    _lean_off(monkeypatch)
    st, sid, _b = _two_path_fixture(tmp_path)
    agent = AgentL(st, workspace_root=st.root)
    before = _formal_files(tmp_path)

    refused = agent.formalize(_FULL, source=_SOURCE, statement_id=sid)
    assert refused.get("refused") is True, refused
    assert refused.get("reason") == "proof_path_unspecified", (
        "多路径未给号必须受控拒绝（默认落到 #p1 会把两条路径的读数弄反）", refused["reason"])
    assert _formal_files(tmp_path) == before, (
        "被拒时盘上不许出现新文件", _formal_files(tmp_path))

    missing = agent.formalize(_FULL, source=_SOURCE, statement_id=sid, proof_no=9)
    assert missing.get("reason") == "proof_path_not_found", (
        "号不在册必须受控拒绝", missing["reason"])
    assert _formal_files(tmp_path) == before, (
        "号不在册也不许写盘", _formal_files(tmp_path))


def test_a_single_path_statement_is_not_refused(tmp_path: pathlib.Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 的正控：只有一份证明时不给号也不拒（存量 62 行就是这种）。"""
    from agentflow.agent_l import AgentL

    _lean_off(monkeypatch)
    st = _ws(tmp_path)
    agent_b = AgentB(st, extractor=None, extract_text=None, config={})
    written = _register(st, agent_b, proofs=False)
    assert written.get("ok") is True, written
    sid = str(written["stmt_id"])
    row = _row(st, sid)
    assert [no for no, _text in VR.proof_list(row)] == [1], VR.proof_list(row)

    agent = AgentL(st, workspace_root=st.root)
    got = agent.formalize(_FULL, source=_SOURCE, statement_id=sid)
    assert got.get("refused") is not True, ("只有一条路径时不许因为'没给号'而拒绝", got)
    assert got.get("reason") not in ("proof_path_unspecified", "proof_path_not_found"), got
    assert got.get("proof_no") == 1, ("没给号 ⇒ 缺省就是 #p1", got.get("proof_no"))


def test_the_second_path_gets_its_own_file_name(tmp_path: pathlib.Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 的另一半：`#p2` 的产物是 `<名字>__p2.lean`（不加后缀就把 `#p1` 覆盖掉了）。"""
    from agentflow.agent_l import AgentL

    _lean_off(monkeypatch)
    st, sid, _b = _two_path_fixture(tmp_path)
    agent = AgentL(st, workspace_root=st.root)
    got = agent.formalize(_FULL, source=_SOURCE, statement_id=sid, proof_no=2,
                          declaration_name="probe", path_source="C")
    assert got.get("proof_no") == 2 and got.get("path_source") == "C", got
    assert str(got.get("path")).endswith("code/formal/probe__p2.lean"), (
        "#p2 的产物名必须带 __p2", got.get("path"))
    assert (tmp_path / "ws" / "code" / "formal" / "probe__p2.lean").is_file(), (
        "盘上没有 __p2 那一份", _formal_files(tmp_path))
    assert str(got.get("steps_path") or "").endswith("code/formal/probe__p2.steps.jsonl") or \
        got.get("steps_path") == "", got.get("steps_path")


# ============================================================ ⑥ 忠实（sha / path_source）

def test_record_keeps_the_four_path_readings_and_they_are_faithful(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑥：`record` 记下这一行验的是哪一份、那份正文的 sha、以及"谁选的"。"""
    from agentflow.agent_l import AgentL

    _lean_off(monkeypatch)
    st, sid, _b = _two_path_fixture(tmp_path)
    lean_dir = tmp_path / "ws" / "code" / "formal"
    lean_dir.mkdir(parents=True, exist_ok=True)
    (lean_dir / "probe__p2.lean").write_bytes(_SOURCE.encode("utf-8"))
    agent = AgentL(st, workspace_root=st.root)

    # 三值逐个落盘（业主补裁：B 指定 / 照 C 的建议 / L 自己决定）。
    for source in ("B", "C", "L"):
        got = agent.record(sid, "code/formal/probe__p2.lean", proof_no=2,
                           path_id="p2g1", path_source=source, declaration_name="probe")
        assert got.get("recorded") is True, got
        assert got.get("proof_no") == 2, got
        assert got.get("path_id") == "p2g1", got
        assert got.get("path_source") == source, (
            f"path_source={source} 没落盘（它是受控三值，不许被抹成空）", got.get("path_source"))
        assert got.get("proof_sha256") == VR.proof_sha(P2), (
            "记下来的 sha 不是第 2 份证明现行正文的", got.get("proof_sha256"))
        obs = [r for r in st.rows("experiments")
               if str(r.get("experiment_id") or "") == str(got["experiment_id"])][0]
        assert obs["observations"]["proof_sha256"] == VR.proof_sha(P2), obs["observations"]
        assert obs["observations"]["path_source"] == source, obs["observations"]
        # 谁选的（path_source）与谁验的（recorded_by）是两格，不许合成一格。
        assert obs["observations"]["recorded_by"] == "agent-L", obs["observations"]
        assert obs["params"]["proof_no"] == 2, obs["params"]
        assert obs["params"]["proof_sha256"] == VR.proof_sha(P2), obs["params"]

    # 号与产物对不上 ⇒ 受控拒绝（登记进去的会是另一条路径的源码）。
    wrong = agent.record(sid, "code/formal/probe.lean", proof_no=2, declaration_name="probe")
    assert wrong.get("reason") == "proof_path_artifact_mismatch", wrong


def test_a_changed_proof_text_turns_that_path_stale(tmp_path: pathlib.Path) -> None:
    """⑥ 的负控：验完之后正文改了 ⇒ 那条路径读 stale（不是 verified，也不是 pending）。"""
    st, sid, agent_b = _two_path_fixture(tmp_path)
    row = _row(st, sid)
    assert EB.formal_by_proof(row) == {1: "verified", 2: "pending"}, row.get("bits")

    # 改 `#p1` 的正文（改稿是正常写入：不许被拒）。
    edited = dict(row)
    edited["proof_text"] = P1 + "\n3. 改成这一版之后才有的那一步。"
    with st.tx("statements", actor="test", note="probe:edit") as tx:
        tx.upsert("statements", edited, note="probe:edit")
    changed = _row(st, sid)
    assert EB.formal_by_proof(changed) == {1: "stale", 2: "pending"}, (
        "正文变了而位还读 verified：哈希是读数（该路径已过期）", changed.get("bits"))
    assert EB.derive_grade(EB.bits_from_row(changed)) != "theorem", (
        "旧稿的结论不许给新稿背书", EB.derive_grade(EB.bits_from_row(changed)))

    # 改回去 ⇒ 又读 verified（不许要求重新登记）。
    back = dict(changed)
    back["proof_text"] = P1
    with st.tx("statements", actor="test", note="probe:edit-back") as tx:
        tx.upsert("statements", back, note="probe:edit-back")
    assert EB.formal_by_proof(_row(st, sid)) == {1: "verified", 2: "pending"}, (
        "改回原样之后不许还停在 stale", _row(st, sid).get("bits"))
    # `#p2` 的正文从头到尾没动过：它一直是 pending，不许被 #p1 的过期牵连成 stale。
    assert EB.formal_by_proof(_row(st, sid))[2] == "pending", _row(st, sid).get("bits")
    assert agent_b is not None


# ============================================================ ⑦ D28（真 Lean 端到端）

def _lean_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentflow import agent_prompts as AP
    from agentflow import leantoolchain as LT

    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1")
    if HAVE_LEAN:
        monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


def _skip_unless_usable(root: pathlib.Path) -> None:
    from agentflow import leantoolchain as LT

    if not HAVE_LEAN:
        pytest.skip(f"本机没有 {LEAN} ⇒ 这一条要真跑检查器，跳过（不伪装通过）")
    reading = LT.lean_selfcheck_reading(root=root)
    if str(reading.get("state")) != "usable":
        pytest.skip(f"Lean 自检不是 usable（state={reading.get('state')}）⇒ 跳过（不伪装通过）")


def test_d28_a_verified_formalization_reaches_the_fourth_bit(tmp_path: pathlib.Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """⑦（端到端实跑）：L 真验过 `#p1` ⇒ 第 4 位真的变成 verified、等级 theorem。

    跑的是真实链路：B 登记两路径 → L `formalize(#p1)` 写盘 + 真 Lean 核 → L `record`
    落一行 `experiments` → B 再登记一次（写侧同步第 4 位）→ 命题那一行读出来。
    """
    from agentflow.agent_l import AgentL

    # 这一条自己从零走一遍（不用"已经验过"的夹具：验没验过正是它要判的那件事）。
    st = _ws(tmp_path)
    agent_b = AgentB(st, extractor=None, extract_text=None, config={})
    first = _register(st, agent_b)
    assert first.get("ok") is True, first
    sid = str(first["stmt_id"])

    _lean_on(monkeypatch)
    _skip_unless_usable(st.root)
    agent = AgentL(st, workspace_root=st.root)

    formalized = agent.formalize(_FULL, source=_SOURCE, statement_id=sid, proof_no=1,
                                 declaration_name="probe", path_source="B")
    assert formalized.get("path") == "code/formal/probe.lean", (
        "#p1 的落盘名必须逐字是 code/formal/<名字>.lean", formalized.get("path"))
    assert formalized.get("status") == "verified", (
        "真 Lean 没验过这一份（那这一条判据无从谈起）", formalized)

    recorded = agent.record(sid, "code/formal/probe.lean", proof_no=1,
                            declaration_name="probe", path_source="B")
    assert recorded.get("recorded") is True, recorded
    assert recorded.get("evidence_kind") == "proof", recorded

    # ---- D28 的现场：`record` 之后、B 再登记之前，第 4 位还是"没验过"。
    # 改前它永远停在这里（`bits.formal` 没有任何写者）⇒ 等级 theorem 从未可达。
    before = EB.bits_from_row(_row(st, sid))
    assert EB._bit_state(before, EB.FORMAL_BIT) == "pending", (
        "L 的 `record` 自己不许改 `statements`（它的写集只有 experiments）", before["formal"])

    # ---- 写侧：B 再登记一次，第 4 位从 L 的台账同步进命题那一行。
    synced = _sync(st, agent_b)
    assert synced.get("ok") is True, synced
    assert synced.get("formal_paths") == {"1": "verified", "2": "pending"}, (
        "写侧没把两路径逐条同步（第 4 位是二维的）", synced)

    after = EB.bits_from_row(_row(st, sid))
    assert EB.formal_by_proof(after) == {1: "verified", 2: "pending"}, (
        "D28：L 验过的那一条路径没有落进第 4 位", after.get("bits"))
    assert after["grade"] == "theorem", ("第 2 位 + #p1 形式化通过 ⇒ 正式定理", after["grade"])
    reading = VR.statement_review_reading(st.root, _row(st, sid))
    per = {int(p["proof_no"]): p["formal"] for p in reading["proofs"]}
    assert per == {1: "verified", 2: "pending"}, ("明细必须如实（#p2 没验）", per)


# ============================================================ ⑧ 反真空

def test_the_two_path_fixture_is_not_vacuous_and_degrades_to_red(tmp_path: pathlib.Path) -> None:
    """⑧：夹具至少一条两路径行；把它退化成只有 `#p1` ⇒ ① 的那条断言必须红。"""
    st, sid, _b = _two_path_fixture(tmp_path)
    row = _row(st, sid)
    assert [no for no, _text in VR.proof_list(row)] == [1, 2], (
        "夹具退化了（只有一条路径时 ① 与 ③ 都会变成空转）", VR.proof_list(row))

    def _bits_for(paths: list[int]) -> dict:
        states = {str(no): ("verified" if no == 1 else "pending") for no in paths}
        return EB.bits_of(proof=True, proof_process="逐步论证……", formal=states,
                          formal_evidence={"1": {"checker": "lean4"}})

    _assert_or_criterion(_bits_for([1, 2]))
    with pytest.raises(AssertionError):
        _assert_or_criterion(_bits_for([1]))


def test_bit_evidence_gaps_names_the_empty_experiments_false_green() -> None:
    """⑧：凭据指着一条实验而 `experiments` 传空 ⇒ 必须报 dangling（否则就是假绿）。

    这一条守的是判据自己的口径：`bit_evidence_gaps(..., experiments=[])` 在"凭据里没有
    指针"时返回空列表 —— 那不是"查过了没问题"，而是"没有可比对的表"。所以调用方
    （`verify` 第 13 段）必须先确认表读到了；这一条把那个边界钉成两条断言。
    """
    bits = EB.bits_of(proof=True, proof_process="逐步论证……",
                      formal={"1": "verified"},
                      formal_evidence={"1": {"checker": "lean4", "experiment_id": "000007"}})
    row = {"stmt_id": "000001", "origin": "own_result", "proof_text": "逐步论证……",
           "bits": bits}
    gaps = EB.bit_evidence_gaps(row, experiments=[])
    assert [g["code"] for g in gaps] == ["bits_evidence_pointer_dangling"], (
        "凭据指着的实验不在（空表）⇒ 这一格不许静默通过（那正是假绿）", gaps)
    assert gaps[0]["level"] == "error", gaps[0]

    # 表读到了、行也在 ⇒ 一条都不许误报（反真空的另一半）。
    experiment = {"experiment_id": "000007", "method": "formal"}
    assert EB.bit_evidence_gaps(row, experiments=[experiment]) == [], (
        "实验行在册时不许还报悬空", EB.bit_evidence_gaps(row, experiments=[experiment]))
