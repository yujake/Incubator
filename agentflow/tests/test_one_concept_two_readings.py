# -*- coding: utf-8 -*-
"""判据：台账命题「错误」与等级「错误」是同一个概念的两处读法，必须恒等。

## 业主 2026-11-13 的裁定（这条判据守的就是它）

> 「refuted 究竟是什么状态？统一 refuted 和 error。」
> 「台账命题状态就叫 error。临时命题……错了被拒就是 refuted。」

于是：
- 台账行：`status=错误那一档` ⇔ `等级=「错误」`，一个有一个没有就是缺陷；
- 临时命题（F 侧计划中命题 / E 侧命题 / B 侧命题）：`refuted` 是"被拒"，不参与这条恒等。

## 判据（a–e + 三条护栏）

| # | 判据 | 反真空在哪 |
|---|---|---|
| a | 证伪签那一笔 ⇒ `status=错误` 且 等级=错误，同一事务 | c 的两向打桩会让它红 |
| b | 反例 / 构造 / 判词那一笔 ⇒ 也读成错误 | 读口是唯一判据（不许各模块自己拼） |
| c | 打桩「等级=错误」⇒ a 红；打桩「status 落点」⇒ a 也红 | 两条都不是断言写死的结果 |
| d | 坏行（`status=错误` 没载荷 / 有载荷 status 没跟上）⇒ 读口报冲突，不许回"不是错" | 三个冲突码逐条 |
| e | 老盘/老词：词表里现在活着的那一档读成错误；另一档读成"读不出来"，不许静默变 active/猜想 | 两个方向 |
| f | 临时命题：`refuted` 的凭据两选一（反例实验号 / 拒收记录）；都没有 ⇒ 读不出来 | 正控 + 负控 |
| g | 写点唯一：`errorstate` 只读不写；它不含任何 `upsert` / 事务 / 写盘调用 | 源码级（防"读口顺手写"） |
| h | 词随表走：`ERROR_WORD` / `ERROR_WORDS` 从 `schema.STATEMENT_STATUSES` 现取 | FC-27 补丁落地后自动收紧 |

## 为什么 g 用源码扫而不是行为断言

行为断言只能证明"这一次没写"，证明不了"以后也不会写"；而这条判据守的正是
"读口不许长出写路径"（业主：单一访问口）。扫的是 `errorstate.py` 的 AST，不是字符串
—— 注释里写 `upsert` 不算违规，调用它才算。
"""
from __future__ import annotations

import ast
import hashlib
import pathlib
import sys

import pytest

from conftest import seed_statement_row  # noqa: E402

from agentflow import errorstate as ES  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import refutation as RF  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import statementrefute as SR  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-11-13T09:00:00+08:00"
SID = "000001"
FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
SIGN = {"kind": "refutation_sign", "artifact_sha": "a" * 64,
        "ledger": "verifications/000002.jsonl#v-000001", "at": TS,
        "manuscript": "reports/b-proof-000000.md",
        "signed_statement_id": "000002", "proof_no": 1}
CONSTRUCTION = {"kind": "construction", "construction": "取 G = K3，则假设不成立",
                "reason": "构造反例", "at": TS}
COUNTEREXAMPLE = {"kind": "numeric_counterexample", "experiment_id": "000009",
                  "counterexample": {"n": 14}, "reason": "反例", "at": TS}
#: 词表里"另一档"（今天没被声明的那一个）：判据 e 用它造"老词/新词"行。
OTHER_WORD = "error" if ES.ERROR_WORD == "refuted" else "refuted"


# ---------------------------------------------------------------- 夹具


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store, sid: str = SID, *, status: str = "active",
         bits: dict | None = None) -> dict:
    return seed_statement_row(
        st, stmt_id=sid, kind="theorem", label="探针命题", statement_full=FULL,
        proof_text=PROOF, origin="own_result", quote_verified=None,
        quote_reason="夹具：探针", status=status, bits=bits if bits is not None else {})


def _row(st: Store, sid: str = SID) -> dict:
    return next(dict(r) for r in st.rows("statements") if r["stmt_id"] == sid)


def _bits_with_sign(row: dict, sign: dict | None = None) -> dict:
    bits = dict(row.get("bits") or {})
    ev = dict(bits.get("evidence") or {})
    ev[EB.REFUTATION_SIGN_KEY] = dict(sign or SIGN)
    bits["evidence"] = ev
    return bits


def _settle(st: Store, row: dict, payload: dict, *, merged_bits: dict | None = None):
    """走唯一 settle 点：`statementrefute._write_row(payload=...)`（两条写路都汇到这里）。"""
    merged = dict(row)
    if merged_bits is not None:
        merged["bits"] = dict(merged_bits)
    return SR._write_row(st, before=row, merged=merged, note="probe", actor="probe",
                         payload=dict(payload))


def _row_status(bits: dict | None, *, status: str, kind: str = "theorem") -> dict:
    """造一行"手上拿着的行"（不写盘）：读口只吃行，不吃盘。"""
    return {"stmt_id": "000099", "kind": kind, "status": status,
            "bits": dict(bits or {})}


# ---------------------------------------------------------------- a：证伪签那一笔


def test_a_a_refutation_sign_writes_status_and_grade_in_one_transaction(tmp_path):
    """a：证伪签落盘 ⇒ `status=错误那一档` 且 等级=错误（同一笔），读口说"是"。"""
    st = _ws(tmp_path)
    row = _put(st)
    data, code, why = _settle(st, row, SIGN, merged_bits=_bits_with_sign(row))
    assert code == "", (code, why)
    assert data["status"] == ES.ERROR_WORD, data["status"]
    assert data["bits"]["grade"] == EB.GRADE_ERROR, data["bits"]
    on_disk = _row(st)
    reading = ES.statement_refuted(st, stmt_id=SID)
    assert reading["state"] == ES.STATE_ERROR, reading
    assert reading["status"] == on_disk["status"] == ES.ERROR_WORD
    assert reading["grade"] == EB.GRADE_ERROR
    assert reading["error_by_sign"] is True and reading["error_by_evidence"] is False


# ---------------------------------------------------------------- b：另一条写路


def test_b_evidence_counterexample_and_construction_read_as_error_too(tmp_path):
    """b：反例 / 构造作废（没有证伪签）⇒ 也读成「错误」（业主第二次裁定的落点）。"""
    st = _ws(tmp_path)
    _put(st, "000001")
    got = SR.refute_statement(st, statement_id="000001", reason="构造反例",
                              construction="取 G = K3，则假设不成立")
    assert got["checked"] is True and got["amended"] is True, got
    reading = ES.statement_refuted(st, stmt_id="000001")
    assert reading["state"] == ES.STATE_ERROR, reading
    assert reading["grade"] == EB.GRADE_ERROR
    assert reading["error_by_sign"] is False and reading["error_by_evidence"] is True
    # 反例实验那一档（读侧同一族）：造一行载荷，读口同样说"是"。
    row = _row(st, "000001")
    bits = dict(row["bits"])
    bits["voided_by"] = dict(COUNTEREXAMPLE)
    reading = ES.statement_refuted(row={**row, "bits": bits})
    assert reading["state"] == ES.STATE_ERROR, reading


# ---------------------------------------------------------------- c：两向反真空


def test_c1_stubbing_the_grade_rule_turns_a_red(tmp_path, monkeypatch):
    """c-①：把「等级=错误」打桩掉 ⇒ 写口同事务读回对不上 ⇒ a 必红（整笔回滚）。"""
    st = _ws(tmp_path)
    row = _put(st)
    monkeypatch.setattr(EB, "derive_grade", lambda bits, *, kind="": "conjecture")
    data, code, why = _settle(st, row, SIGN, merged_bits=_bits_with_sign(row))
    assert data is None and code == "refute_invariant_broken", (data, code, why)
    assert "status_grade_disagree" in why, why
    # a 的断言在这里必红：盘上的行还是 active（一个字节都没写）。
    assert _row(st)["status"] == "active"


def test_c2_stubbing_the_status_word_turns_a_red(tmp_path, monkeypatch):
    """c-②：把「status 落点」打桩成另一档 ⇒ 同事务读回"载荷在而状态没跟上"⇒ a 也红。"""
    st = _ws(tmp_path)
    row = _put(st)
    monkeypatch.setattr(ES, "ERROR_WORD", "superseded")
    data, code, why = _settle(st, row, SIGN, merged_bits=_bits_with_sign(row))
    assert data is None and code == "refute_invariant_broken", (data, code, why)
    assert "payload_without_status" in why, why
    assert _row(st)["status"] == "active"


# ---------------------------------------------------------------- d：坏行必须被抓住


def test_d_bad_rows_are_reported_as_conflicts_never_as_not_error():
    """d：两种坏行 ⇒ 读口报冲突码，`state` 是「读不出来」，不许是"不是错"。"""
    # ① status=错误 而载荷空（等级只能读成猜想）
    bare = _row_status(None, status=ES.ERROR_WORD)
    reading = ES.statement_refuted(row=bare)
    assert reading["state"] == ES.STATE_UNKNOWN, reading
    assert reading["conflict"] == ES.CONFLICT_STATUS_WITHOUT_PAYLOAD, reading
    # ② 载荷在、等级也读成错误，而 status 不是错误那一档
    payload_bits = EB.bits_of(proof=True, reviewed=True, voided_by=dict(CONSTRUCTION))
    wrong_status = _row_status(payload_bits, status="superseded")
    reading = ES.statement_refuted(row=wrong_status)
    assert reading["state"] == ES.STATE_UNKNOWN, reading
    assert reading["conflict"] == ES.CONFLICT_PAYLOAD_WITHOUT_STATUS, reading
    assert reading["grade"] == EB.GRADE_ERROR, reading
    # ③ 自称证伪签而签读不出来（缺格）：说不出凭什么 ⇒ 也是"读不出来"
    malformed = _row_status({"proof": True, "reviewed": True,
                             "evidence": {},
                             "voided_by": {"kind": "refutation_sign", "at": TS}},
                            status=ES.ERROR_WORD)
    reading = ES.statement_refuted(row=malformed)
    assert reading["state"] == ES.STATE_UNKNOWN, reading
    assert reading["conflict"] == ES.CONFLICT_STATUS_WITHOUT_PAYLOAD, reading


def test_d2_a_healthy_row_is_not_a_conflict():
    """d 的正控：干净行 ⇒ `not_error`，且没有冲突码（负控的反面）。"""
    reading = ES.statement_refuted(row=_row_status(EB.bits_of(proof=True), status="active"))
    assert reading["state"] == ES.STATE_NOT_ERROR, reading
    assert reading["conflict"] == "", reading
    # 不在册/没查成也不是"不是错"（三态纪律）
    missing = ES.statement_refuted(None, stmt_id=SID)
    assert missing["state"] == ES.STATE_UNKNOWN and missing["checked"] is False, missing


# ---------------------------------------------------------------- e：老盘 / 老词


def test_e_the_live_word_reads_error_and_the_other_word_reads_unknown(tmp_path):
    """e：词表里活着的那一档读成错误；另一档读成"读不出来"（不许静默变 active/猜想）。

    老盘实测 0 行（`temp/u2_legacy_refuted.py`：72 工作区 / 3,600 行里 `status=refuted`
    与作废载荷都是 0）—— 所以这条不是迁移判据，是"以后别静默"的判据。
    """
    st = _ws(tmp_path)
    _put(st, "000001")
    SR.refute_statement(st, statement_id="000001", reason="构造反例",
                        construction="取 G = K3")
    live = ES.statement_refuted(st, stmt_id="000001")
    assert live["state"] == ES.STATE_ERROR and live["word"] == ES.ERROR_WORD, live
    # 另一档：同一份载荷、换一个词表外的状态词 ⇒ 读不出来，不是"不是错"。
    row = _row(st, "000001")
    other = ES.statement_refuted(row={**row, "status": OTHER_WORD})
    assert other["state"] == ES.STATE_UNKNOWN, other
    assert other["status"] == OTHER_WORD
    # 老词 + 没载荷（坏行）也不许读成"不是错"。
    empty_other = ES.statement_refuted(row={"stmt_id": "000002", "kind": "theorem",
                                            "status": OTHER_WORD, "bits": {}})
    assert empty_other["state"] == ES.STATE_UNKNOWN, empty_other


# ---------------------------------------------------------------- f：临时命题


def test_f_a_refuted_temporary_proposition_needs_one_of_two_evidences():
    """f：临时命题 `refuted` 的证据两选一（反例实验号 / 拒收记录），都没有 ⇒ 读不出来。"""
    base = {"conjecture_id": "000001", "statement": "每个有限群都循环", "form": "universal",
            "origin": "gap", "status": "refuted"}
    by_exp = ES.conjecture_refuted(row={**base, "counterexample_experiment_id": "000009"})
    assert by_exp["state"] == ES.CONJ_STATE_REFUTED and by_exp["by_experiment"] is True, by_exp
    by_refusal = ES.conjecture_refuted(row={**base, "refusal_ref": "refusals/task-t000001"})
    assert by_refusal["state"] == ES.CONJ_STATE_REFUTED, by_refusal
    assert by_refusal["by_refusal"] is True and by_refusal["by_experiment"] is False
    neither = ES.conjecture_refuted(row=dict(base))
    assert neither["state"] == ES.CONJ_STATE_UNKNOWN, neither
    assert neither["conflict"] == ES.CONFLICT_STATUS_WITHOUT_PAYLOAD, neither
    # 不是被拒的那一档 ⇒ not_refuted（与"读不出来"分开）
    proposed = ES.conjecture_refuted(row={**base, "status": "proposed"})
    assert proposed["state"] == ES.CONJ_STATE_NOT_REFUTED, proposed


def test_f2_a_refutation_never_lands_in_the_conjectures_table(tmp_path):
    """f-2：台账那一笔（`refute_statement`）不许顺手往 `conjectures` 写行。

    业主口径：临时命题只有 F 侧计划中命题 / E 侧命题 / B 侧命题三个来源，D 侧没有；
    台账命题判错与"临时命题被拒"是两件事，写口不许互相冒充。
    """
    st = _ws(tmp_path)
    _put(st)
    before = len(st.rows("conjectures"))
    SR.refute_statement(st, statement_id=SID, reason="构造反例", construction="取 G = K3")
    assert len(st.rows("conjectures")) == before == 0


# ---------------------------------------------------------------- g：读口只读


def _errorstate_source() -> str:
    module = sys.modules[ES.__name__]
    return pathlib.Path(module.__file__).read_text(encoding="utf-8")


def _call_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


def test_g_the_read_port_has_no_write_path():
    """g：唯一读口只读 —— 源码里没有任何写台账 / 写盘的调用。"""
    calls = _call_names(_errorstate_source())
    forbidden = {"upsert", "append", "delete", "write_text", "write_bytes", "tx",
                 "alloc_id", "dump", "insert"}
    leaked = sorted(calls & forbidden)
    assert leaked == [], f"读口里出现了写路径：{leaked}（单一访问口只读）"


def test_g2_reading_does_not_touch_the_disk(tmp_path):
    """g-2：把每一行都读一遍 ⇒ 台账文件逐字节不变（行为层的同一件事）。"""
    st = _ws(tmp_path)
    _put(st, "000001")
    SR.refute_statement(st, statement_id="000001", reason="构造反例",
                        construction="取 G = K3")
    path = pathlib.Path(str(st.root)) / "data" / "statements.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    for row in st.rows("statements"):
        ES.statement_refuted(row=dict(row))
        ES.conjecture_refuted(row={"conjecture_id": "x", "status": "refuted"})
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


# ---------------------------------------------------------------- h：词随表走


def test_h_the_word_follows_the_vocabulary():
    """h：写侧落点与读侧认的词从词表现取（FC-27 补丁落地后自动从 refuted 收紧成 error）。"""
    declared = set(S.STATEMENT_STATUSES)
    assert ES.ERROR_WORD == ("error" if "error" in declared else "refuted")
    assert set(ES.ERROR_WORDS) == {w for w in ("error", "refuted") if w in declared}
    # 落点必须在词表里（否则写侧每一笔都会被 `Statement.validate` 拒）
    assert ES.ERROR_WORD in declared
    # 读侧认的词不许出现"词表里没有的"（另一档必须读成读不出来，见 e）
    assert set(ES.ERROR_WORDS) <= declared


def test_h2_the_refutation_channel_writes_through_the_same_word(tmp_path):
    """h-2：证伪通道的 `changes` / 落盘状态与写侧常量同源（不是各写一份字面量）。"""
    st = _ws(tmp_path)
    row = _put(st)
    data, code, _why = _settle(st, row, SIGN, merged_bits=_bits_with_sign(row))
    assert code == ""
    assert data["status"] == ES.ERROR_WORD
    port = RF.statement_refuted(st, stmt_id=SID)
    assert port["state"] == ES.STATE_ERROR, port


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
