# -*- coding: utf-8 -*-
"""两格读数：「稿上已签」/「已入台账」（2026-11-08，业主「V 只对手稿负责」）。

## 为什么要单独一条判据

V 不再写 `statements` 之后，会出现一个新的中间态：

```
稿上：- V 签：已签=true；连续=3/3；正文sha=<sha>     ← 签真的在
册里：bits.reviewed=false（B 还没收录）              ← 不是"签丢了"
```

这两件事必须由两格分别回答，并且第三格 `state` 要把中间态命名出来。若只读册，
`reviewed=false` 会被读成"没签过"（看起来像签丢了）；若只读稿，又分不出"已收录"。
判据本体的唯一实现是 `vsigns.sign_filing_reading`（两格都借既有实现，不写第二份）：
稿那一格走 `vsigns.manuscript_sign_standing`，册那一格走 `proof_list` +
`evidencebits.reviewed_by_proof`（逐份优先）。

## 判据（a–e）

| 编号 | 造什么 | 期望 |
|---|---|---|
| a | 稿上无签、册里无位 | `manuscript_signed=False, filed=False, state="unsigned"` |
| b | 稿上盖了签、册里没收录 | `manuscript_signed=True, filed=False, state="signed_pending_filing"` |
| c | 稿上签 + 册里同 sha 且第 3 位为真 | `filed=True, state="filed"` |
| d | 稿上签的是新版、册里还是旧版 | `state="signed_stale_in_ledger"`（签还在，等收录新版） |
| e | 反真空：把签块的 `正文sha` 改成别的 | `manuscript_signed=False`（b 立刻红） |
| f | 反真空：把册里的逐份位清成假 | `filed=False`（c 立刻红，且落到中间态） |

零模型调用、全部 tmp 工作区、不读写 `projects/`。
"""
from __future__ import annotations

import pathlib

from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.store import Store

from conftest import seed_statement_row

PROOF = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
         "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
SID = "000000"
REL = f"reports/f-proof-{SID}.md"
SHA = VR.text_sha(PROOF)


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _manuscript(st: Store, proof: str = PROOF, *, full: str = FULL) -> str:
    """落一份手稿并返回它的全文（不是路径）。"""
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (f"# 证明手稿\n\n- 命题号：stmt:{SID}\n\n"
            f"## 命题\n\n{full}\n\n"
            f"## 证明\n\n{proof}\n\n" + DS.render_dependency_section([]))
    path.write_text(text, encoding="utf-8")
    return text


def _signed_text(text: str, *, sha: str = SHA, ledger: str = "") -> str:
    return VS.stamp_manuscript_sign(
        text, proof_sha=sha, streak=3, need=3, verdict="成立",
        signer="secretary:B", at="2026-11-08T00:00:00+08:00",
        ledger=(ledger or f"verifications/{SID}.jsonl#v-000001"),
        statement_id=SID, manuscript_id=SID)


def _row(st: Store, *, reviewed: bool) -> dict:
    bits = EB.bits_of(
        proof=True, proof_process=PROOF, reviewed=reviewed,
        reviewed_by=({"verification_id": "v-000001", "evidence":
                      f"verifications/{SID}.jsonl#v-000001"} if reviewed else None),
        kind="theorem")
    if reviewed:
        ev = dict(bits.get("evidence") or {})
        ev[EB.REVIEWED_BY_PROOF_KEY] = {str(1): True}
        bits["evidence"] = ev
        bits["grade"] = EB.derive_grade(bits, kind="theorem")
    return seed_statement_row(
        st, proof_text=PROOF, statement_full=FULL, statement_text="一致连续",
        kind="theorem", label="uniform-continuity", origin="own_result",
        evidence_kind="heuristic", bits=bits, stmt_id=SID)


def _read(st: Store, text: str) -> dict:
    return VS.sign_filing_reading(st.root, manuscript_path=REL, proof_text=text,
                                  statement_id=SID, store=st)


def test_a_no_sign_no_filed_is_unsigned(tmp_path: pathlib.Path) -> None:
    st = _ws(tmp_path)
    _row(st, reviewed=False)
    text = _manuscript(st)
    got = _read(st, text)
    assert got["checked"] is True, got
    assert got["manuscript_signed"] is False, got
    assert got["filed"] is False, got
    assert got["state"] == "unsigned", got


def test_b_signed_on_manuscript_but_not_filed_is_the_new_state(
        tmp_path: pathlib.Path) -> None:
    """b：这一条就是本次改动要救的那个态 —— 不许读成「签丢了」。"""
    st = _ws(tmp_path)
    _row(st, reviewed=False)
    text = _signed_text(_manuscript(st))
    got = _read(st, text)
    assert got["checked"] is True, got
    assert got["manuscript_signed"] is True, got
    assert got["filed"] is False, got
    assert got["state"] == "signed_pending_filing", got
    assert "不是「签丢了」" in got["why"], got["why"]
    # 稿上那一格带得出凭据（sha / 连续 / 台账锚点），不是一句布尔。
    assert got["manuscript"]["proof_sha256"] == SHA, got["manuscript"]
    assert int(got["manuscript"]["streak"]) == 3, got["manuscript"]


def test_c_filed_means_both_cells_agree(tmp_path: pathlib.Path) -> None:
    st = _ws(tmp_path)
    _row(st, reviewed=True)
    text = _signed_text(_manuscript(st))
    got = _read(st, text)
    assert got["manuscript_signed"] is True, got
    assert got["filed"] is True, got
    assert got["state"] == "filed", got
    assert int(got["statement"]["proof_no"]) == 1, got["statement"]


def test_d_signed_new_version_is_not_lost(tmp_path: pathlib.Path) -> None:
    """d：稿上签的是新版，而册里还是旧版 ⇒ 签还在（stale），不是「没签」。"""
    st = _ws(tmp_path)
    _row(st, reviewed=True)
    new_proof = PROOF + "\n3. 补上边界情形。"     # 新版正文
    text = _signed_text(_manuscript(st, new_proof), sha=VR.text_sha(new_proof))
    got = _read(st, text)
    assert got["manuscript_signed"] is True, got
    assert got["filed"] is False, got
    assert got["state"] == "signed_stale_in_ledger", got


def test_e_moving_the_signed_sha_makes_the_manuscript_cell_red(
        tmp_path: pathlib.Path) -> None:
    """e 反真空：签块 sha 一改，稿上那一格必须掉（b 的判据真的在看 sha）。"""
    st = _ws(tmp_path)
    _row(st, reviewed=False)
    text = _signed_text(_manuscript(st), sha="0" * 64)
    got = _read(st, text)
    assert got["manuscript_signed"] is False, got
    assert got["state"] == "unsigned", got


def test_f_clearing_the_per_proof_bit_makes_the_filed_cell_red(
        tmp_path: pathlib.Path) -> None:
    """f 反真空：把逐份位清成假，`filed` 必须掉回中间态（c 的判据真的在读位）。"""
    st = _ws(tmp_path)
    row = _row(st, reviewed=True)
    bits = dict(row.get("bits") or {})
    ev = dict(bits.get("evidence") or {})
    ev[EB.REVIEWED_BY_PROOF_KEY] = {}
    bits["evidence"] = ev
    bits["reviewed"] = False
    bits["grade"] = EB.derive_grade(bits, kind="theorem")
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", dict(row, bits=bits))
    got = _read(st, _signed_text(_manuscript(st)))
    assert got["manuscript_signed"] is True, got
    assert got["filed"] is False, got
    assert got["state"] == "signed_pending_filing", got


def test_g_without_store_the_filed_cell_is_not_guessed(tmp_path: pathlib.Path) -> None:
    """g：没有 store 时 `filed` 是 `None`（没查成），不许折成「没收录」。"""
    st = _ws(tmp_path)
    _row(st, reviewed=True)
    got = VS.sign_filing_reading(st.root, manuscript_path=REL,
                                 proof_text=_signed_text(_manuscript(st)),
                                 statement_id=SID, store=None)
    assert got["manuscript_signed"] is True, got
    assert got["filed"] is None, got
    assert got["state"] == "unreadable", got


def test_h_statement_body_comes_from_the_manuscript(tmp_path: pathlib.Path) -> None:
    """手稿的 `## 命题` 是 V 的命题正文来源（替代 statements.statement_full）。"""
    st = _ws(tmp_path)
    text = _manuscript(st, full="（手稿上的命题）")
    assert DS.statement_body(text) == "（手稿上的命题）", DS.statement_body(text)
    assert DS.statement_body("# 空稿\n\n## 证明\n\n1. 显然。") == "", "没有命题页 ⇒ 空串"


def test_i_closing_reports_signed_pending_filing_not_unsigned(
        tmp_path: pathlib.Path) -> None:
    """收工读数：稿上已签、册里未收录 ⇒ `signed_pending_filing`，不是欠签。

    先把稿盖成已签（册里没位），`closing.statements_unsigned_reading` 必须把它放进
    `pending_filing`（`count` 仍 0、不阻塞收工门），而不是 `never_submitted`；
    没有签的对照组才进 `rows` / `count`。
    """
    from agentflow import closing

    st = _ws(tmp_path)
    _row(st, reviewed=False)
    _text = _signed_text(_manuscript(st))   # 稿上盖好签
    (pathlib.Path(st.root) / REL).write_text(_text, encoding="utf-8")
    got = closing.statements_unsigned_reading(st)
    assert got["checked"] is True, got
    assert got["count"] == 0, got["rows"]
    assert got["pending_filing_count"] == 1, got
    assert got["by_class"].get("signed_pending_filing") == 1, got["by_class"]
    one = dict(got["pending_filing"][0])
    assert one["class"] == "signed_pending_filing", one
    assert "不是「签丢了」" in one["why"], one["why"]
    assert "稿上已签" in got["reason"], got["reason"]

    # 对照组：同一份稿没有签 ⇒ 才是"欠签"。
    st2 = _ws(tmp_path / "no-sign")
    _row(st2, reviewed=False)
    _manuscript(st2)
    got2 = closing.statements_unsigned_reading(st2)
    assert got2["count"] == 1 and got2["pending_filing_count"] == 0, got2
    assert got2["rows"][0]["class"] == "never_submitted", got2["rows"][0]
