# -*- coding: utf-8 -*-
"""判据：`optimized=true` 必须有签（87 真机暴露的漏洞；业主 2026-11-03 15:55 的口径）。

## 真机读数（`projects/ramsey-4-4-87`，2026-11-03 15:55，逐字）

8 条命题：带正文 6、`reviewed` 为真 2 ⇒ 有正文无签 4 条
（`000001` / `000002` / `000004` / `000007`）；而 `optimized` 却是
`000001 / 000002 / 000003 / 000004 / 000007 = {"1": true}` ——
「`optimized=true` 能在没有签的情况下被打上」。另外 `000002` 的 evidence 里连
`reviewed_by_proof` 这一格都没有（换正文那一笔把它清掉了）。

## 与口径的冲突（业主原话）

「洗过的肯定能保证V签」「优化后拿V签，用有V签的优化后的证明精准替换原证明并将那条
证明记为已优化」⇒ `optimized=true` 的前提是"这份替换进来的正文已经有签"。
改前它可以无签被打上 ⇒ "优化过"成了比"签"更强、却可以是空的声称。

## 两处修法（判据 a–d 各钉一条）

| 处 | 改后 | 守的是哪句话 |
|---|---|---|
| ① 打 true 之前核 | `evidencebits.optimized_signature`：`reviewed_by_proof[证明号] is True` 且 `reviewed_sha_by_proof[证明号] == proof_sha(现行正文)`；不满足 ⇒ 不打 true、`optimized_blocked=no_sign / sha_mismatch`，且正文不许被替换 | 「优化后拿V签，用有V签的优化后的证明精准替换原证明」 |
| ② 换正文那一笔 | `_bits_after_canonical_write` 把这一笔按现行正文认到的签（`reviewed_by_proof` / `reviewed_sha_by_proof`）带过来，没认到的保留旧的；不许清空即通过 | 同上（签是那一格的前提，清掉它就是让 true 无凭） |

## 判据

| # | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a | 造"无签的替换" ⇒ `optimized` 不是 true、读数 `optimized_blocked=no_sign`、正文未被替换 | 改前 `_signature_covers` 只看 V 的台账；台账里没有这一份就落 false，但正文照旧被换掉、`proof_history` 照旧多一条（`optimized=true` 则只要台账有票就打上） |
| b | 造"有签的替换" ⇒ `optimized=true`，且 `reviewed_by_proof` / `reviewed_sha_by_proof` 仍在、sha 与现行正文一致 | 改前 `_bits_after_canonical_write` 把 `fresh` 里刚认到的那两张表丢掉（000002 的形态） |
| c | 87 定格重放（只读）：`000001/000002/000004/000007` 读成 `optimized=false` + 原因；`000003` 仍 true | 改前 `optimized_state` 只读那一张表 ⇒ 五条全是 true |
| d | 反真空：把 ① 那条核摘掉 ⇒ a 必须回到"能打 true"（正文被换、`optimized=true`） | —— 判据 a 的绿必须来自这条核，而不是某个顺手写的分支 |

全部 tmp 工作区、零模型调用；`projects/**` 只在 c 里按只读打开，一个字节都不写。
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import evidencebits as EB  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_b import register_statement as RS  # noqa: E402
from agentflow.store import Store  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 87 的定格现场（只读；`projects/**` 一个字节都不许写）。
PROJECT_87_STATEMENTS = REPO / "projects" / "ramsey-4-4-87" / "data" / "statements.json"

#: 一条在册命题的正文，与"优化后那一版"逐字不同（替换必须真的是一次改稿）。
STATEMENT = "设 G 是 3-正则群；则弦长函数不是常值。"
P_MECH = "1. 由定义直接得到。\n2. 由 1 与假设 n ≥ 3 得结论。"
P_OPT = ("1. 由定义直接得到。\n2. 取最短路径、按弦长分层归纳。\n"
         "3. 归纳步用 3-正则性排除环。\n4. 由 1–3 得结论。")

OWN = {
    "statement_full": STATEMENT,
    "statement_text": "弦长函数不是常值",
    "origin": "own_result",
    "kind": "conjecture",
    "doc_id": S.format_id(0),
    "quote_reason": "我方自产命题，没有外部引文要比对",
}


# ------------------------------------------------------------------ 小工具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _agent(st: Store) -> AgentB:
    return AgentB(st, extractor=None, extract_text=None, config={})


def _row(st: Store, stmt_id: str = "") -> dict:
    rows = [dict(r) for r in st.rows("statements")]
    if stmt_id:
        return next(r for r in rows if str(r.get("stmt_id")) == stmt_id)
    return rows[0]


def _seed(st: Store, *, proof_text: str, stmt_id: str = "000001") -> str:
    """铺一条在册命题（机械录入那一版：`optimized={"1": false}`、还没有签）。"""
    bits = EB.bits_of(origin="own_result", proof=True, proof_process=proof_text,
                      kind="conjecture")
    bits = EB.with_optimized_defaults(bits, [1])
    row = {
        "stmt_id": stmt_id, "origin": "own_result", "kind": "conjecture",
        "label": "弦长函数不是常值", "statement_text": OWN["statement_text"],
        "statement_full": STATEMENT, "proof_text": proof_text,
        "status": "active", "created_at": S.now_iso(), "created_by": "secretary-B",
        "quote_verified": None, "quote_reason": OWN["quote_reason"],
        "derived_from": [], "aliases": [], "bits": bits,
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row, note="seed:optimized_requires_a_sign")
    return stmt_id


def _sign_three(st: Store, *, proof_text: str, stmt_id: str, proof_no: int = 1) -> None:
    """V 对同一份正文连判「成立」到发签门槛（真签：签文件 + 逐条表都落）。"""
    for _ in range(VR.SIGN_STREAK_NEED):
        VR.record_verification(
            st.root, statement_id=str(stmt_id), proof_text=str(proof_text),
            verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
            store=st, proof_no=int(proof_no))


def _relaxed(monkeypatch) -> None:
    """把准入闸摘掉：a 判据量的是 ① 那条核，不是准入闸（准入闸在 strict 下会先拒）。"""
    monkeypatch.setenv("AGENTFLOW_UNSIGNED_PROOF_INTAKE", "relaxed")


# ============================================================ a：无签的替换
def test_a_an_unsigned_replacement_is_refused_and_the_body_is_not_replaced(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """a：无签的替换 ⇒ `optimized_blocked=no_sign`、`optimized` 不是 true、正文原样。

    为什么要把准入闸摘掉（`relaxed`）：strict 下这一笔在 `_unsigned_proof_gate` 就已经
    被拒了 —— 那样 a 的绿来自准入闸，量不到 ① 那条核。这里是 ① 自己的判据：即使没有
    准入闸，没有签的正文也不许盖掉在册那一份、更不许被打成 `optimized=true`。
    """
    _relaxed(monkeypatch)
    st = _ws(tmp_path)
    sid = _seed(st, proof_text=P_MECH)
    before = _row(st, sid)

    out = _agent(st).register_statement(**OWN, proof_text=P_OPT)

    assert out.get("ok") is False, out
    assert out.get("kind") == "proof_without_v_sign", out
    assert out.get("optimized_blocked") == EB.OPTIMIZED_BLOCKED_NO_SIGN, out
    assert [x.get("optimized") for x in (out.get("optimized") or [])] == [False], out
    # 正文原样：`proof_text` 一个字都没动、`proof_history` 也没多一条。
    after = _row(st, sid)
    assert after.get("proof_text") == P_MECH, after.get("proof_text")
    assert not (after.get("proof_history") or []), after.get("proof_history")
    assert after.get("bits") == before.get("bits"), (
        "拒了换正文，而 bits 变了", after.get("bits"))


# ============================================================ b：有签的替换
def test_b_a_signed_replacement_flips_optimized_and_keeps_the_review_tables(
        tmp_path: pathlib.Path) -> None:
    """b：有签的替换 ⇒ `optimized=true`，且两张逐条表仍在、sha 与现行正文一致。

    现场照 87 的次序铺：命题行上先是机械录入那一版（`P_MECH`）；V 先把旧正文
    签满（于是逐条表里已经有一签，sha 指旧正文），随后把优化版（`P_OPT`）签满 ——
    签的是还没上盘的那一份（真机 15:50 的三票就是这样）。换正文这一笔必须：
    ① 按新正文认到那一签（`reviewed_sha_by_proof` 改指新正文）；
    ② 两张表还在（不是被清空后"没签也算通过"）；
    ③ 由此才有资格落 `optimized=true`。
    """
    st = _ws(tmp_path)
    sid = _seed(st, proof_text=P_MECH)
    # 旧正文那一签（历史）：换正文之后它不再算数，但表里那一格不许被清掉。
    _sign_three(st, proof_text=P_MECH, stmt_id=sid, proof_no=1)
    assert EB.reviewed_by_proof(_row(st, sid)) == {1: True}, _row(st, sid)["bits"]
    # 优化版那一签：签的时候命题行上还是旧正文 ⇒ 位不翻，但签文件照发（87 的次序）。
    _sign_three(st, proof_text=P_OPT, stmt_id=sid, proof_no=1)

    out = _agent(st).register_statement(**OWN, proof_text=P_OPT)

    assert out.get("ok") is True, out
    assert out.get("optimized_blocked") == "", out
    assert [x.get("optimized") for x in (out.get("optimized") or [])] == [True], out
    row = _row(st, sid)
    assert row.get("proof_text") == P_OPT, "有签的替换没写进去"
    assert list(row.get("proof_history") or []), "旧正文没有进 proof_history ⇒ 不是精准替换"
    assert EB.optimized_by_proof(row) == {1: True}, row["bits"]["evidence"]
    # ② 两张表仍在，而且 sha 指的是现行正文（按现行正文重新判定后重写）。
    assert EB.reviewed_by_proof(row) == {1: True}, row["bits"]["evidence"]
    assert EB.reviewed_sha_by_proof(row) == {1: VR.proof_sha(P_OPT)}, row["bits"]["evidence"]


# ============================================================ c：87 定格重放
def test_c_the_87_frozen_rows_read_optimized_false_with_a_reason() -> None:
    """c：87 定格重放（只读）⇒ 无签那四条读成 false + `no_sign`；000003 仍 true。

    为什么这一条必须存在：写侧修好只保证"以后不再打上"，而 87 盘上那五格 `true`
    已经在那里了。读侧要能把它们读回来 —— 否则"优化过"这件事仍然可以是一句空声称。
    只读打开 `projects/ramsey-4-4-87/data/statements.json`，一个字节都不写。
    """
    assert PROJECT_87_STATEMENTS.is_file(), f"87 的定格现场不在盘上：{PROJECT_87_STATEMENTS}"
    rows = json.loads(PROJECT_87_STATEMENTS.read_text(encoding="utf-8"))["rows"]
    by_id = {str(r.get("stmt_id")): r for r in rows}
    assert sorted(by_id) == [S.format_id(i) for i in range(8)], sorted(by_id)

    unsigned = ("000001", "000002", "000004", "000007")
    for sid in unsigned:
        row = by_id[sid]
        # 盘上那一格仍然是 true（历史读数不追溯改写，`optimized_by_proof` 读得到）
        # —— 而"能不能声称已优化"是 false，`optimized_state` 与 `optimized_standing`
        # 两个读口给同一句话。
        assert EB.optimized_by_proof(row) == {1: True}, (sid, row.get("bits"))
        assert EB.optimized_state(row, 1) == "false", (sid, row.get("bits"))
        got = EB.optimized_standing(row, 1)
        assert got["optimized"] is False, (sid, got)
        assert got["state"] == "false", (sid, got)
        assert got["optimized_blocked"] == EB.OPTIMIZED_BLOCKED_NO_SIGN, (sid, got)
        assert got["why"].strip(), (sid, got)

    # 000003 是 87 里唯一"有正文、有签、签的就是现行正文"的那一条 ⇒ 仍 true。
    signed = by_id["000003"]
    got = EB.optimized_standing(signed, 1)
    assert got["optimized"] is True, got
    assert got["optimized_blocked"] == "", got
    assert got["recorded_sha256"] == VR.proof_sha(str(signed.get("proof_text") or "")), got


# ============================================================ d：反真空
def test_d_without_the_gate_an_unsigned_replacement_goes_green(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """d（反真空）：把 ① 那条核摘掉 ⇒ a 必须回到"能打 true"（正文被换、`optimized=true`）。

    打桩点就是 a 的判据点本身（`_optimized_gate`）：把它打成恒 true 之后，同一笔无签
    的替换就会真的盖掉在册正文、并被打上 `optimized=true` —— 那正是 a 要防的形态，
    于是 a 的断言在这里全部反转（判据红）。没有这一条，a 的绿可能来自准入闸或某个
    顺手写的分支，而不是这条核。
    """
    _relaxed(monkeypatch)
    monkeypatch.setattr(
        RS, "_optimized_gate",
        lambda bits, *, proof_no, proof_text: {
            "checked": True, "proof_no": int(proof_no), "optimized": True,
            "optimized_blocked": "", "signed": True,
            "proof_sha256": VR.proof_sha(str(proof_text)), "recorded_sha256": "",
            "why": "打桩：把 ① 那条核摘掉（判据 d）"})
    st = _ws(tmp_path)
    sid = _seed(st, proof_text=P_MECH)

    out = _agent(st).register_statement(**OWN, proof_text=P_OPT)

    assert out.get("ok") is True, out
    assert out.get("optimized_blocked") == "", out
    assert [x.get("optimized") for x in (out.get("optimized") or [])] == [True], out
    row = _row(st, sid)
    assert row.get("proof_text") == P_OPT, "打桩之后正文却没换 ⇒ a 的绿不是来自这条核"
    assert list(row.get("proof_history") or []), "打桩之后旧正文没留痕"
