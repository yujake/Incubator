# -*- coding: utf-8 -*-
"""判据：脚本改了之后重新登记，老登记必须被撤销（业主 2026-10-24 裁定）。

业主原话（唯一权威）：「改脚本后应该重新登记并把老登记撤销」。

## 改前现场（`projects/sylow3` 真机读数）

`exp 000000` 与 `exp 000001` 挂在同一个 `code_path` 上、`code_hash` 不同；盘上现在是
000001 那一版的脚本。页面上 000000 那一格只报「代码不一致」，于是两条实验并列挂着，
读者无从判断哪一条还算数 —— 报「不一致」不等于把它撤销。

## 这一组守七件事

1. 同 `code_path` 跑一次、改脚本、再跑一次 ⇒ 老行被撤销（理由码 `code_changed`，
   理由逐字带两个 sha 前 16 位），新行仍有效；
2. 撤销之后老行不再被算作该结论的证据：读数（`verify_tools.evidence_for`）与验收
   读数（`closing._leg_reading`）两边都不数它 —— 两边口径不许分家；
3. 负控：脚本没变就重跑 ⇒ 不撤销；
4. 负控：不同 `code_path` ⇒ 互不撤销；
5. 读侧四档：一致 / 已撤销（旧 → 新）/ 不一致 / unknown（文件不在盘上）；
6. 反真空：把撤销打桩成空、或把同路径判定打桩成恒不等 ⇒ 第 1 条必红；
7. 自动处置的三态：既有登记读不出来 ⇒ 不撤，但返回值里必须说「没能核既有登记」，
   不许静默当成「没有旧登记」。

全部用例在 `tmp_path` 里自建工作区，一个模型调用都不发，也不碰真机工作区。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import closing as CL  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import verify_tools as VT  # noqa: E402
from agentflow.webui import readers as R  # noqa: E402

import agentflow.agent_e.run_experiment as RX  # noqa: E402

#: 被判据当"同一个脚本"的那条相对路径。
SCRIPT_REL = "code/probe.py"
#: 另一条脚本（负控 ④ 用它证明"不同路径互不撤销"）。
OTHER_REL = "code/other.py"
#: 命题与它的机器可读键（两条实验挂在同一条命题上：这正是现场那一幕）。
CLAIM = "网格 n<=3 上 Spec K(m)=[-m,m]"
CLAIM_KEY = "SpecK(m)=[-m,m]"
#: 夹具用的固定时间（写进 `voided_at` 之类的地方时，判据只要求非空）。
TS = "2026-10-24T00:00:00+00:00"

#: 第一版脚本：报一条带界（`bound`）的支持性结论。
PROBE_V1 = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {"points": 3},
    "counterexample": None,
    "negation_kind": "not_proved",
    "bound": {"n": 3},
}))
"""

#: 第二版脚本：读数不变，只多一行注释 ⇒ 文件字节不同、`code_hash` 不同。
PROBE_V2 = PROBE_V1 + "\n# 2026-10-24：脚本改过（判据：改脚本要撤销老登记）\n"


def _store(root: pathlib.Path) -> Store:
    st = Store(root)
    st.init()
    return st


def _write(store: Store, rel: str, body: str) -> str:
    """按字节原样落盘（`write_text` 在 Windows 上会把 `\\n` 翻成 `\\r\\n`，
    于是夹具算出来的 sha 与盘上那一份对不上）。"""
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))
    return rel


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _e(store: Store) -> AgentE:
    return AgentE(store, config={}, workspace_root=store.root)


def _run(store: Store, *, rel: str = SCRIPT_REL) -> dict:
    return _e(store).run_experiment(CLAIM, CLAIM_KEY, rel, method="numeric")


def _rows(store: Store) -> dict[str, dict]:
    return {str(r.get("experiment_id")): dict(r) for r in store.rows("experiments")}


def _run_twice(store: Store) -> tuple[dict, dict]:
    """同一条 `code_path` 跑两次，中间把脚本改掉（现场那一幕）。"""
    _write(store, SCRIPT_REL, PROBE_V1)
    first = _run(store)
    _write(store, SCRIPT_REL, PROBE_V2)
    second = _run(store)
    return first, second


def _assert_old_row_is_revoked(store: Store, first: dict, second: dict) -> None:
    """第 1 条判据的本体：老行被撤销、留痕齐全、新行有效、返回值逐条点名。

    单独抽成函数是为了第 6 条反真空：把撤销打桩成空之后，同一个断言必须红。
    """
    rows = _rows(store)
    old = rows[str(first["experiment_id"])]
    new = rows[str(second["experiment_id"])]
    old_hash = str(first["code_hash"])
    new_hash = str(second["code_hash"])
    assert old_hash != new_hash, "两次跑出来的 code_hash 相同 ⇒ 夹具没造出'脚本改了'"

    # 老行：撤销的语义、理由码、留痕三件（谁撤的 / 什么时候 / 为什么）
    assert old["status"] == S.EXPERIMENT_VOIDED == "voided", old
    assert old["void_reason_code"] == S.VOID_REASON_CODE_CHANGED == "code_changed", old
    assert old["voided_by"] == "agent-E", old
    assert str(old["voided_at"]).strip(), old
    assert old["void_reason"] == S.experiment_void_reason(
        code_hash_from=old_hash, code_hash_to=new_hash), old
    assert old["void_reason"] == f"脚本 {old_hash[:16]} → {new_hash[:16]}", old
    assert old["voided_code_to"] == new_hash, old
    # 新行：仍有效
    assert new["status"] == S.EXPERIMENT_ACTIVE == "active", new
    # 返回值里逐条点名（不是只有台账知道）
    note = str(second["notes"])
    assert f"已撤销 exp:{old['experiment_id']}" in note, note
    assert old_hash[:16] in note and new_hash[:16] in note, note


# ---------------------------------------------------------------- ① 改脚本 ⇒ 撤销老行
def test_1_changing_the_script_voids_the_previous_row_and_keeps_the_new_one_active(
        tmp_path: pathlib.Path) -> None:
    """① 同 code_path 跑一次 → 改脚本 → 再跑一次 ⇒ 老行被撤销，新行有效。"""
    store = _store(tmp_path / "ws")
    first, second = _run_twice(store)
    _assert_old_row_is_revoked(store, first, second)
    # 两条都还在台账上（撤销不是删除：读者要能看见"这一条曾经算数、为什么不算了"）
    assert len(_rows(store)) == 2, _rows(store)


# ---------------------------------------------------------------- ② 撤销之后不再算证据
def test_2_a_voided_row_stops_counting_as_evidence_on_both_sides(
        tmp_path: pathlib.Path) -> None:
    """② 老行不再被算作该结论的证据：读数与验收读数两边都不数它。

    两边各自只有一个出处：读数走 `verify_tools.evidence_for`（E 的 `evidence_for`
    与工具 `verify.evidence_for` 共用它），验收读数走 `closing._leg_reading`
    （验收表每一行的 `got` 都是它现算的）。两边都给 1 才算口径一致。
    """
    store = _store(tmp_path / "ws")
    first, second = _run_twice(store)
    old_id = str(first["experiment_id"])
    new_id = str(second["experiment_id"])

    # 读数那一侧
    ev = VT.evidence_for(store, CLAIM_KEY)
    ids = [str(r.get("experiment_id")) for r in ev["experiments"]]
    assert ev["count"] == 1, (ev["count"], ids)
    assert ids == [new_id], ids
    assert old_id not in ids, "已撤销的那一行还被算作证据"
    assert "已撤销" in str(ev["reason"]), ev["reason"]

    # 验收读数那一侧（`numeric_experiment_rows`：给了结论的数值实验条数）
    got, detail = CL._leg_reading(store, "numeric_experiment_rows",
                                  pathlib.Path(store.root))
    assert got == 1, (got, detail)
    assert detail["experiments"] == [new_id], detail
    assert old_id not in detail["experiments"], detail
    # 两边口径一致：同一个数、同一条行
    assert ev["count"] == got == 1


# ---------------------------------------------------------------- ③ 负控：脚本没变
def test_3_negative_control_an_unchanged_script_does_not_void_anything(
        tmp_path: pathlib.Path) -> None:
    """③ 负控：脚本没变就重跑 ⇒ 不撤销（按现有口径多一条新行）。"""
    store = _store(tmp_path / "ws")
    _write(store, SCRIPT_REL, PROBE_V1)
    first = _run(store)
    second = _run(store)
    assert first["code_hash"] == second["code_hash"]
    rows = _rows(store)
    assert rows[str(first["experiment_id"])]["status"] == "active", rows
    assert rows[str(second["experiment_id"])]["status"] == "active", rows
    assert "已撤销" not in str(second["notes"]), second["notes"]
    assert len(rows) == 2, rows


# ---------------------------------------------------------------- ④ 负控：不同路径
def test_4_negative_control_a_different_code_path_does_not_void_anything(
        tmp_path: pathlib.Path) -> None:
    """④ 负控：不同 code_path 的实验互不撤销（哪怕字节逐字相同）。"""
    store = _store(tmp_path / "ws")
    _write(store, SCRIPT_REL, PROBE_V1)
    first = _run(store)
    _write(store, OTHER_REL, PROBE_V1)
    second = _run(store, rel=OTHER_REL)
    assert first["code_hash"] == second["code_hash"], "夹具两条脚本的字节应当相同"
    rows = _rows(store)
    assert rows[str(first["experiment_id"])]["status"] == "active", rows
    assert rows[str(second["experiment_id"])]["status"] == "active", rows
    assert "已撤销" not in str(second["notes"]), second["notes"]


# ---------------------------------------------------------------- ⑤ 读侧四档
def _experiment(*, eid: str, rel: str, code_hash: str, **kw: object) -> S.Experiment:
    """造一条形状合法的实验行（`status` 与撤销留痕由 `kw` 给）。"""
    return S.Experiment(
        experiment_id=eid, claim=CLAIM, claim_key=CLAIM_KEY, method="numeric",
        result="inconclusive", negation_kind="not_proved",
        code_path=rel, code_hash=code_hash, created_at=TS, created_by="agent-E",
        **kw)


def test_5_the_code_consistency_reading_has_four_tiers(tmp_path: pathlib.Path) -> None:
    """⑤ 读侧四档：一致 / 已撤销（旧 → 新）/ 不一致（未撤销）/ unknown。

    「已撤销」不是红：它带两个 sha 前 16 位与撤销理由，读者据此判断哪一条还算数。
    """
    store = _store(tmp_path / "ws")
    old_text, new_text = PROBE_V1, PROBE_V2
    _write(store, "code/same.py", old_text)
    _write(store, "code/changed.py", new_text)
    _write(store, "code/revoked.py", new_text)
    _write(store, "code/short.py", old_text)
    old_hash = _sha(old_text)
    new_hash = _sha(new_text)
    with store.tx("experiments", actor="fixture") as tx:
        tx.upsert("experiments", _experiment(
            eid=S.format_id(1), rel="code/same.py", code_hash=old_hash).to_dict())
        tx.upsert("experiments", _experiment(
            eid=S.format_id(2), rel="code/changed.py", code_hash=old_hash).to_dict())
        tx.upsert("experiments", _experiment(
            eid=S.format_id(3), rel="code/gone.py", code_hash=old_hash).to_dict())
        tx.upsert("experiments", _experiment(
            eid=S.format_id(4), rel="code/revoked.py", code_hash=old_hash,
            status=S.EXPERIMENT_VOIDED,
            void_reason_code=S.VOID_REASON_CODE_CHANGED,
            void_reason=f"脚本 {old_hash[:16]} → {new_hash[:16]}",
            voided_by="agent-E", voided_at=TS,
            voided_code_to=new_hash).to_dict())
        # 写侧记的哈希只有前 16 位（`verify_tools.code_hash` 的定义）：这一行必须读成一致
        tx.upsert("experiments", _experiment(
            eid=S.format_id(5), rel="code/short.py", code_hash=old_hash[:16]).to_dict())

    face = R.evidence_chain(tmp_path / "ws")
    assert face["experiments_tri"] == R.TRI_COMPUTED, face
    rows = {str(r.get("experiment_id")): r for r in face["experiments"]}

    same = rows[S.format_id(1)]
    assert same["code_sha_consistency"] == R.SHA_MATCH == "match", same
    assert same["code_sha_from"] == old_hash[:16], same
    assert same["code_sha_to"] == "", same
    assert same["void_reason"] == "", same

    changed = rows[S.format_id(2)]
    assert changed["code_sha_consistency"] == R.SHA_MISMATCH == "mismatch", changed
    assert changed["code_sha_consistency"] != R.CODE_CONSISTENCY_REVOKED

    gone = rows[S.format_id(3)]
    assert gone["code_sha_consistency"] == R.SHA_UNKNOWN == "unknown", gone

    short = rows[S.format_id(5)]
    assert short["code_sha_consistency"] == R.SHA_MATCH, (
        "写侧记的是 sha 前 16 位，前缀相同就是同一份脚本（逐字比会把它读成不一致）")
    assert short["code_sha_from"] == old_hash[:16], short

    revoked = rows[S.format_id(4)]
    assert revoked["code_sha_consistency"] == R.CODE_CONSISTENCY_REVOKED == "revoked", revoked
    assert revoked["code_sha_consistency"] != R.SHA_MISMATCH, "已撤销被读成了红的那一档"
    # 两个 sha 前 16 位与撤销理由都要能显示出来
    assert revoked["code_sha_from"] == old_hash[:16], revoked
    assert revoked["code_sha_to"] == new_hash[:16], revoked
    assert revoked["void_reason"] == f"脚本 {old_hash[:16]} → {new_hash[:16]}", revoked
    # 判据本体（读侧唯一谓词）：撤销的读真、历史行（没有这一列）读成仍有效
    assert S.experiment_is_voided(revoked) is True
    assert S.experiment_is_voided(same) is False
    assert S.experiment_is_voided({"experiment_id": "000009"}) is False, (
        "没有 status 的历史行被读成了已撤销")
    assert S.active_experiment_rows([{"status": "voided"}, {"status": "active"},
                                     {"experiment_id": "000009"}]) == [
        {"status": "active"}, {"experiment_id": "000009"}]

    # 四档是四个互不相同的值（折平任意两档 ⇒ 下面这一条红）
    assert len({R.SHA_MATCH, R.SHA_MISMATCH, R.SHA_UNKNOWN,
                R.CODE_CONSISTENCY_REVOKED}) == 4


# ---------------------------------------------------------------- ⑥ 反真空
def test_6a_anti_vacuum_stubbing_the_revocation_to_nothing_breaks_criterion_1(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑥ 反真空之一：把撤销打桩成"什么都没做" ⇒ 第 1 条必红。"""
    base = _store(tmp_path / "ws")
    first, second = _run_twice(base)
    _assert_old_row_is_revoked(base, first, second)          # 正控：不打桩时是绿的

    store = _store(tmp_path / "ws2")
    monkeypatch.setattr(RX, "_void_superseded_rows", lambda *a, **k: ([], []))
    first2, second2 = _run_twice(store)
    assert _rows(store)[str(first2["experiment_id"])]["status"] == "active"
    assert "已撤销" not in str(second2["notes"])
    with pytest.raises(AssertionError):
        _assert_old_row_is_revoked(store, first2, second2)


def test_6b_anti_vacuum_stubbing_the_same_path_check_breaks_criterion_1(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑥ 反真空之二：把"同路径"判定打桩成恒不等 ⇒ 第 1 条也必红。"""
    base = _store(tmp_path / "ws")
    first, second = _run_twice(base)
    _assert_old_row_is_revoked(base, first, second)

    store = _store(tmp_path / "ws2")
    monkeypatch.setattr(RX, "_same_code_path", lambda row, code_path: False)
    first2, second2 = _run_twice(store)
    assert _rows(store)[str(first2["experiment_id"])]["status"] == "active"
    with pytest.raises(AssertionError):
        _assert_old_row_is_revoked(store, first2, second2)


# ---------------------------------------------------------------- 三态：读不到既有登记
def test_7_an_unreadable_ledger_is_reported_instead_of_silently_treated_as_empty(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """自动处置的第三态：既有登记读不出来 ⇒ 不撤，但必须说「没能核既有登记」。"""
    store = _store(tmp_path / "ws")
    _write(store, SCRIPT_REL, PROBE_V1)
    first = _run(store)
    _write(store, SCRIPT_REL, PROBE_V2)

    monkeypatch.setattr(RX, "_existing_experiment_rows",
                        lambda tx: (None, "StoreError: experiments 表读不出来"))
    second = _run(store)
    # 不撤（判不了就不许动手）
    assert _rows(store)[str(first["experiment_id"])]["status"] == "active"
    # 也不许静默：返回值里点名"没查成"，并带上原因
    note = str(second["notes"])
    assert "没能核既有登记" in note, note
    assert "StoreError" in note, note
    assert "已撤销" not in note, note
