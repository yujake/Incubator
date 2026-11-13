# -*- coding: utf-8 -*-
"""证伪通道（RF 路）的判据：B 锁 P + 锁 Q 的稿 ⇒ V 签被翻译成证伪签 ⇒ 等级「错误」。

## 六条判据（业主 2026-11-13 的施工单）

| # | 它钉的是什么 | 对应用例 |
|---|---|---|
| a | 端到端：锁 P + 锁稿 ⇒ 写 `proof_text`、旧正文进 `proof_history`、`status=refuted`、`grade=错误` | `test_a_end_to_end_*` |
| b | 证伪签否决其它等级：「该命题另有更高档真签」，error 仍是最低 | `test_b_*` |
| c | proof 栏确实是证伪论证、旧正文进 `proof_history`（不是静默覆盖） | `test_c_*` |
| d | 反真空：把"翻译成证伪签"打桩成不翻译 ⇒ error 不出现（b 红） | `test_d_*` |
| e | 反真空：去掉"证伪签否决" ⇒ b 红 | `test_e_*` |
| f | 三态：证伪签读不出来 ⇒ 不许当证伪（fail-closed） | `test_f_*` |

另加一条（业主点名）：「证伪签在 ⇒ error 绝对最低」（`GRADE_ORDER[0]`，比 `conjecture`
还低一格），现场用"该命题本可读成 theorem"的那一行造出来。

夹具（`_ws` / `_put` / `_draft` / `_sign`）只造「盘上现场」，不替判据说话：
签一律走 `_credential_fixture.issue_credential`（三行同源台账 + `vsigns.issue`），
与真机"V 签过一份稿"同形。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from conftest import seed_statement_row  # noqa: E402

from _credential_fixture import issue_credential  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import proofregistry as PR  # noqa: E402
from agentflow import refutation as RF  # noqa: E402
from agentflow.store import Store  # noqa: E402

P = "000001"          # 被证伪的命题
Q = "000002"          # B 的证伪论证（"P 不成立"）
F_DRAFT = "000003"    # F 的反例论证稿（B 正常录入后成了在册命题）
P_FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
P_PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
Q_FULL = "命题 000001 不成立：存在 [0,1] 上的连续函数 f 在一点不连续。"
REFUTE_BODY = (
    "第 1 步：由 stmt:000003（存在反例）取 f(x)=x（x<1/2），f(x)=x+1（x≥1/2），"
    "它在 1/2 处不连续。\n"
    "第 2 步：f 在 [0,1] 上有界且连续于除 1/2 外的一切点，故 000001 的「一致连续」"
    "断言在此反例下不成立。\n"
    "第 3 步：因此命题 000001 是错的。"
)
DRAFT_REL = "reports/b-proof-000001.md"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _theorem_bits(*, proof_text: str, reviewed: bool = True) -> dict:
    """一份"本可读成 theorem"的五元位：证明 + 穷举证书（机器可核）+ 真签。

    `numeric="verified"` 且 `numeric_evidence.experiments` 非空 ⇒
    `_numeric_is_certificate` 缺省为真 ⇒ `derive_grade` 给 `theorem`
    （业主点名要的"另有更高档"现场）。
    """
    sha = PR.proof_sha(proof_text)
    bits = EB.bits_of(
        proof=True, proof_process=proof_text,
        numeric="verified",
        numeric_evidence={"script": "scripts/check.py", "sha": "a" * 64,
                          "experiments": ["000001"]},
        reviewed=True,
        reviewed_by={"verification_id": "v-000001", "proof_sha256": sha},
        kind="theorem")
    # 逐份真签那两张表（写侧的唯一落点是 `vsigns._apply_review_to_bits`；
    # 夹具直接铺同形，因为这里要造的正是"这一行确有一份真签"的现场）
    bits["evidence"][EB.REVIEWED_BY_PROOF_KEY] = {"1": True}
    bits["evidence"][EB.REVIEWED_SHA_BY_PROOF_KEY] = {"1": sha}
    return bits


def _put(st: Store, sid: str, *, full: str, proof: str, status: str = "active",
         bits: dict | None = None, kind: str = "theorem", **extra) -> dict:
    extra.setdefault("quote_reason", "夹具：探针")
    return seed_statement_row(
        st, stmt_id=sid, kind=kind, label=f"探针 {sid}", statement_full=full,
        proof_text=proof, origin="own_result", quote_verified=None,
        status=status, bits=bits if bits is not None else {}, **extra)


def _draft(st: Store, *, rel: str = DRAFT_REL, body: str = REFUTE_BODY,
           deps: str | None = None, family: str = "b-proof") -> tuple[str, str]:
    """在盘上落一份证伪论证稿，返回 `(路径, ## 证明 的正文)`。

    `deps=None` ⇒ 自动渲染一条合法依赖面；`deps=""` ⇒ 「不写」那一节（负控）；
    传别的字符串 ⇒ 原样当那一节（造"读不懂"那一档）。
    """
    if rel == DRAFT_REL:
        rel = f"reports/{family}-000001.md"
    path = pathlib.Path(str(st.root)) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if deps is None:
        deps = DS.render_dependency_section(
            [{"quote": "存在反例", "stmt_id": F_DRAFT, "step": 1}])
    text = (f"# B 的证伪论证稿\n\n## 命题\n\n{Q_FULL}\n\n"
            f"## 证明\n\n{body}\n")
    if deps is not None and deps != "":
        text += "\n" + deps
    path.write_text(text, encoding="utf-8")
    # 与签的尺同一串：`manuscript_proof_body` = `proof_body(...).strip("\\n")`
    from agentflow import vsigns as VS

    return rel, VS.manuscript_proof_body(text)


def _sign(st: Store, *, rel: str, body: str, q_sid: str = Q) -> dict:
    """让 V 真签这一份证伪论证（三行同源台账 + `out/vsigns/<sha>.json`）。"""
    return issue_credential(str(st.root), proof_text=body, statement_id=q_sid,
                            manuscript=rel, artifact_path=rel, call="call-refute")


def _row(st: Store, sid: str) -> dict:
    return next(dict(r) for r in st.rows("statements") if str(r["stmt_id"]) == sid)


# ============================================================ a：端到端

def test_a_end_to_end_locks_p_and_translates_the_sign(tmp_path):
    """a：锁 P + 锁 Q 的稿 ⇒ 正文换成证伪论证、旧正文留痕、终态 + 证伪签 + 「错误」。"""
    st = _ws(tmp_path)
    _put(st, F_DRAFT, full="存在一个反例使 000001 不成立。",
         proof="取 f 为 1/2 处的跳跃函数，逐点核过。")
    _put(st, Q, full=Q_FULL, proof="（待写）")
    old_bits = _theorem_bits(proof_text=P_PROOF)
    _put(st, P, full=P_FULL, proof=P_PROOF, bits=old_bits)
    rel, body = _draft(st)
    issued = _sign(st, rel=rel, body=body)
    assert issued.get("written") is True, issued

    got = RF.refute_by_sign(st, statement_id=P, manuscript=rel)

    assert got["checked"] is True and got["wrote"] is True, got
    assert got["refused"] == "", got
    assert got["grade"] == EB.GRADE_ERROR == "错误", got
    assert got["sha"] == PR.proof_sha(body) and got["ledger"], got
    row = _row(st, P)
    assert row["status"] == "refuted"
    # ③ proof 栏 = 证伪论证
    assert row["proof_text"] == body
    # 证伪签落袋（两个口袋）
    sign = (row["bits"].get("evidence") or {}).get("refutation_sign") or {}
    assert sign.get("artifact_sha") == PR.proof_sha(body), sign
    assert sign.get("ledger") == got["ledger"] and sign.get("at"), sign
    assert sign.get("signed_statement_id") == Q, sign
    assert (row["bits"].get("voided_by") or {}).get("kind") == "refutation_sign"
    # Q 一个字节不动（它是"P 不成立"那条正常命题）
    q = _row(st, Q)
    assert q["status"] == "active" and q["proof_text"] == "（待写）"
    # 读数口
    read = RF.refutation_of(st, statement_id=P)
    assert read["status"] == "refuted" and read["refuted_by_sign"] is True, read
    assert read["grade"] == "错误", read


# ============================================================ b：否决 + 绝对最低

def test_b_refutation_sign_vetoes_a_higher_grade(tmp_path):
    """b：同一行另有穷举证书 + 真签（本可读成 theorem），证伪签在 ⇒ 仍是「错误」且最低。"""
    st = _ws(tmp_path)
    _put(st, F_DRAFT, full="存在一个反例使 000001 不成立。", proof="反例构造。")
    _put(st, Q, full=Q_FULL, proof="（待写）")
    # 先证"没有证伪签时它确实是 theorem"—— 否则这条判据就是真空的
    before_bits = _theorem_bits(proof_text=P_PROOF)
    assert EB.derive_grade(before_bits, kind="theorem") == "theorem", before_bits
    _put(st, P, full=P_FULL, proof=P_PROOF, bits=before_bits)
    rel, body = _draft(st)
    _sign(st, rel=rel, body=body)

    got = RF.refute_by_sign(st, statement_id=P, manuscript=rel)
    assert got["wrote"] is True, got

    row = _row(st, P)
    bits = EB.bits_from_row(row)
    # 否决：五元位仍说"证明 + 穷举证书"（本可读成 theorem），等级却是「错误」
    assert bits.get("proof") is True and bits.get("numeric") == "verified", bits
    # 历史那一份真签留在写下去的 `bits` 里（读侧按"正文换了"把第 3 位读成 stale 是对的：
    # P 的正文已经换成证伪论证，旧签盖的是旧那一份）
    assert ((row["bits"].get("evidence") or {}).get("reviewed_by_proof") or {}).get(
        "1") is True, row["bits"]
    assert EB.derive_grade(bits, kind="theorem") == "错误"
    # 而这正是"否决"的唯一原因：把证伪签与作废载荷摘掉，同一行立刻读成 theorem
    plain = {**bits, "voided_by": {},
             "evidence": {k: v for k, v in (bits.get("evidence") or {}).items()
                          if k != EB.REFUTATION_SIGN_KEY}}
    assert EB.derive_grade(plain, kind="theorem") == "theorem", plain
    # 绝对最低：比 conjecture 还低一格（order 的唯一落点）
    assert EB.grade_index("错误") == 0 < EB.grade_index("conjecture"), EB.GRADE_ORDER
    assert EB.GRADE_ORDER[0] == EB.GRADE_ERROR
    assert EB.GRADE_LABELS[EB.GRADE_ERROR]


# ============================================================ c：旧正文留痕

def test_c_old_body_goes_to_proof_history_not_silently_overwritten(tmp_path):
    """c：旧正文进 `proof_history`（带 sha / replaced_by / 号），不是被静默覆盖。"""
    st = _ws(tmp_path)
    _put(st, F_DRAFT, full="存在一个反例使 000001 不成立。", proof="反例构造。")
    _put(st, Q, full=Q_FULL, proof="（待写）")
    _put(st, P, full=P_FULL, proof=P_PROOF, bits=_theorem_bits(proof_text=P_PROOF))
    rel, body = _draft(st)
    _sign(st, rel=rel, body=body)

    got = RF.refute_by_sign(st, statement_id=P, manuscript=rel)
    assert got["wrote"] is True, got
    row = _row(st, P)
    history = list(row.get("proof_history") or [])
    assert len(history) == 1, history
    entry = history[0]
    assert entry["text"] == P_PROOF
    assert entry["sha"] == PR.proof_sha(P_PROOF)
    assert entry["sha"] == got["old_sha"]
    assert entry["replaced_by"] == PR.proof_sha(body)
    assert entry.get("proof_no") == 1
    assert row["proof_text"] != P_PROOF and row["proof_text"] == body


# ============================================================ d：反真空（翻译打桩）

def test_d_anti_vacuum_without_the_translation_there_is_no_error(tmp_path, monkeypatch):
    """d：把"翻译成证伪签"打桩成不翻译 ⇒ 整笔受控拒、error 不出现（b 必红）。"""
    st = _ws(tmp_path)
    _put(st, F_DRAFT, full="存在一个反例使 000001 不成立。", proof="反例构造。")
    _put(st, Q, full=Q_FULL, proof="（待写）")
    _put(st, P, full=P_FULL, proof=P_PROOF, bits=_theorem_bits(proof_text=P_PROOF))
    rel, body = _draft(st)
    _sign(st, rel=rel, body=body)

    monkeypatch.setattr(RF, "sign_payload", lambda **_kw: {})
    got = RF.refute_by_sign(st, statement_id=P, manuscript=rel)

    assert got["refused"] == RF.SIGN_MISSING, got
    assert got["wrote"] is False
    row = _row(st, P)
    assert row["status"] == "active" and row["proof_text"] == P_PROOF
    # b 红：等级仍是最强那一档，没有「错误」
    assert EB.derive_grade(EB.bits_from_row(row), kind="theorem") == "theorem"


# ============================================================ e：反真空（否决打桩）

def test_e_anti_vacuum_without_the_veto_the_grade_climbs_back(tmp_path, monkeypatch):
    """e：去掉"证伪签否决"（读口打桩成恒空）⇒ 等级不再读「错误」（b 红）。"""
    st = _ws(tmp_path)
    _put(st, F_DRAFT, full="存在一个反例使 000001 不成立。", proof="反例构造。")
    _put(st, Q, full=Q_FULL, proof="（待写）")
    _put(st, P, full=P_FULL, proof=P_PROOF, bits=_theorem_bits(proof_text=P_PROOF))
    rel, body = _draft(st)
    _sign(st, rel=rel, body=body)
    got = RF.refute_by_sign(st, statement_id=P, manuscript=rel)
    assert got["wrote"] is True and got["grade"] == "错误", got

    row = _row(st, P)
    assert EB.derive_grade(EB.bits_from_row(row), kind="theorem") == "错误"
    # 打桩：否决项读不出来 ⇒ 回落到 `voided_by` 的清零（猜想了）
    monkeypatch.setattr(EB, "refutation_sign", lambda _bits: {})
    after = EB.derive_grade(EB.bits_from_row(row), kind="theorem")
    assert after != "错误", after
    assert after == "conjecture", after


# ============================================================ f：三态 fail-closed

def test_f_malformed_sign_is_never_read_as_a_refutation(tmp_path):
    """f-1：`voided_by` 自称证伪签、口袋却不在 ⇒ 读成"读不出来"，不许当证伪。"""
    bits = {"proof": True, "reviewed": True,
            "voided_by": {"kind": "refutation_sign", "at": "2026-11-13"},
            "evidence": {}}
    reading = EB.refutation_reading(bits)
    assert reading["checked"] is False and reading["sign"] == {}, reading
    assert EB.refutation_sign(bits) == {}
    # 否决项不生效 ⇒ 落到 voided_by 的清零，不会被读成「错误」
    assert EB.derive_grade(bits, kind="theorem") == "conjecture"
    # 缺格也算读不出来（artifact_sha / ledger / at 三格）
    bad = {"evidence": {"refutation_sign": {"artifact_sha": "a" * 64}}}
    assert EB.refutation_reading(bad)["checked"] is False
    ok = {"evidence": {"refutation_sign": {
        "artifact_sha": "a" * 64, "ledger": "verifications/000002.jsonl#v-000001",
        "at": "2026-11-13T00:00:00+08:00"}}}
    assert EB.refutation_reading(ok)["checked"] is True
    assert EB.derive_grade(ok, kind="theorem") == "错误"


def test_f2_no_sign_no_channel_refusal_and_no_byte_written(tmp_path):
    """f-2：稿在、V 没签 ⇒ 受控拒 `refutation_not_signed`，一行不改。"""
    st = _ws(tmp_path)
    _put(st, F_DRAFT, full="存在一个反例使 000001 不成立。", proof="反例构造。")
    _put(st, P, full=P_FULL, proof=P_PROOF, bits=_theorem_bits(proof_text=P_PROOF))
    rel, _body = _draft(st)

    got = RF.refute_by_sign(st, statement_id=P, manuscript=rel)
    assert got["checked"] is True and got["refused"] == RF.NOT_SIGNED, got
    assert got["wrote"] is False
    row = _row(st, P)
    assert row["status"] == "active" and row["proof_text"] == P_PROOF
    assert not (row.get("bits") or {}).get("voided_by")


def test_f3_unreadable_draft_is_checked_false(tmp_path):
    """f-3：稿读不出来 ⇒ `checked=False`（没查成），不是「没有证伪」。"""
    st = _ws(tmp_path)
    _put(st, P, full=P_FULL, proof=P_PROOF, bits=_theorem_bits(proof_text=P_PROOF))
    got = RF.refute_by_sign(st, statement_id=P,
                            manuscript="reports/b-proof-000099.md")
    assert got["checked"] is True and got["refused"] == RF.DRAFT_UNREADABLE, got
    missing = RF.refute_by_sign(st, statement_id="000404", manuscript=DRAFT_REL)
    assert missing["refused"] == RF.UNKNOWN_STATEMENT, missing


def test_f4_dependency_section_is_a_form_not_a_content_requirement(tmp_path):
    """f-4：`## 依赖` 空表放行（形式要有），缺节 / 读不懂受控拒。"""
    st = _ws(tmp_path)
    _put(st, F_DRAFT, full="存在一个反例使 000001 不成立。", proof="反例构造。")
    _put(st, Q, full=Q_FULL, proof="（待写）")
    # 缺节
    _put(st, P, full=P_FULL, proof=P_PROOF, bits=_theorem_bits(proof_text=P_PROOF))
    rel_missing, body_missing = _draft(st, rel="reports/b-proof-000002.md", deps="")
    # 缺节那一档没有可签的正文形态要求：先签它，验的是"依赖面缺节"这一步
    _sign(st, rel=rel_missing, body=body_missing, q_sid=Q)
    got = RF.refute_by_sign(st, statement_id=P, manuscript=rel_missing)
    assert got["checked"] is True and got["refused"] == RF.DEPS_MISSING, got
    assert _row(st, P)["status"] == "active"
    # 空表（只有表头 + 一行声明）⇒ 放行
    rel_empty, body_empty = _draft(
        st, rel="reports/b-proof-000003.md",
        deps=DS.render_dependency_section([]))
    _sign(st, rel=rel_empty, body=body_empty, q_sid=Q)
    ok = RF.refute_by_sign(st, statement_id=P, manuscript=rel_empty)
    assert ok["wrote"] is True and ok["grade"] == "错误", ok


# ============================================================ 其余受控拒

def test_g_other_refusals_are_controlled_and_write_nothing(tmp_path):
    """负控：族不对 / 已放弃 / 概念行 / 缺正文 / 证明号不存在 —— 全部零写入。"""
    st = _ws(tmp_path)
    _put(st, F_DRAFT, full="存在一个反例使 000001 不成立。", proof="反例构造。")
    _put(st, Q, full=Q_FULL, proof="（待写）")
    _put(st, P, full=P_FULL, proof=P_PROOF, bits=_theorem_bits(proof_text=P_PROOF))
    # 族不对：f-稿不是证伪论证稿
    rel_f, body_f = _draft(st, rel="reports/f-proof-000001.md", family="f-proof")
    _sign(st, rel=rel_f, body=body_f)
    bad_family = RF.refute_by_sign(st, statement_id=P, manuscript=rel_f)
    assert bad_family["refused"] == RF.BAD_MANUSCRIPT, bad_family
    # 已放弃
    _put(st, "000009", full="另一条。", proof="另一份。", status="abandoned",
         quote_reason="abandoned@2026-11-13T00:00:00+08:00@夹具")
    rel, body = _draft(st, rel="reports/b-proof-000004.md")
    _sign(st, rel=rel, body=body)
    on_retired = RF.refute_by_sign(st, statement_id="000009", manuscript=rel)
    assert on_retired["refused"] == RF.ON_RETIRED, on_retired
    # 概念行
    _put(st, "000010", full="概念 X。", proof="", kind="concept")
    concept = RF.refute_by_sign(st, statement_id="000010", manuscript=rel)
    assert concept["refused"] == RF.NOT_A_PROPOSITION, concept
    # 缺 `## 证明`：正文为空 —— 这一档在核签之前就受控拒，不需要签
    rel_empty, _body_empty = _draft(st, rel="reports/b-proof-000005.md", body="")
    empty = RF.refute_by_sign(st, statement_id=P, manuscript=rel_empty)
    assert empty["checked"] is True and empty["refused"] == RF.PROOF_ABSENT, empty
    # 证明号不存在（#p2 而清单里只有 canonical）
    rel2, body2 = _draft(st, rel="reports/b-proof-000006.md")
    _sign(st, rel=rel2, body=body2)
    no_path = RF.refute_by_sign(st, statement_id=P, manuscript=rel2, proof_no=2)
    assert no_path["refused"] == RF.UNKNOWN_PROOF_PATH, no_path
    # 所有拒绝之后 P 一个字没改
    row = _row(st, P)
    assert row["status"] == "active" and row["proof_text"] == P_PROOF


def test_h_refuted_is_terminal_and_only_the_sign_variant_is_idempotent(tmp_path):
    """终态：同一笔重放 ⇒ already；凭反例作废（无证伪签）的行不被本通道接管。"""
    st = _ws(tmp_path)
    _put(st, F_DRAFT, full="存在一个反例使 000001 不成立。", proof="反例构造。")
    _put(st, Q, full=Q_FULL, proof="（待写）")
    _put(st, P, full=P_FULL, proof=P_PROOF, bits=_theorem_bits(proof_text=P_PROOF))
    rel, body = _draft(st)
    _sign(st, rel=rel, body=body)
    first = RF.refute_by_sign(st, statement_id=P, manuscript=rel)
    assert first["wrote"] is True, first
    again = RF.refute_by_sign(st, statement_id=P, manuscript=rel)
    assert again["checked"] is True and again["already"] is True, again
    assert again["wrote"] is False
    # 凭反例作废的那一档：refuted 但没有证伪签 ⇒ 拒（不把另一种作废读成证伪）。
    # 这里用 `bits={}` 铺那一行：`statementrefute.refute_statement` 那一笔不重算
    # `bits.grade` 缓存，带缓存的行会被它自己的 `validate` 拒（`refute_invalid_row`）——
    # 那是那条 lane 的事，本通道不收它，另报。
    from agentflow import statementrefute as SR

    _put(st, "000011", full="另一条。", proof="另一份。")
    SR.refute_statement(st, statement_id="000011", reason="反例命中",
                        construction="取 K3，假设不成立")
    assert _row(st, "000011")["status"] == "refuted"
    taken = RF.refute_by_sign(st, statement_id="000011", manuscript=rel)
    assert taken["refused"] == RF.ON_RETIRED and taken["already"] is False, taken
