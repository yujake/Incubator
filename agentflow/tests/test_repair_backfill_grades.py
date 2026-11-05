# -*- coding: utf-8 -*-
"""判据：`repair --backfill-grades` 的四栏 dry-run 与 `--apply`（2026-11-05 改口径）。

## 这一份守什么（第二次生命）

改前：`evidence_kind` 只有一条升档路（重交 / 补签），本命令事后把它补上去。
2026-11-05 业主动裁「等级是唯一的轴；`evidence_kind` 只作历史列保留，判定面一律读等级」
之后，本命令变成：按五元位现算等级，再把历史列反算成等级的反算名
（`evidencebits.kind_from_grade`）。两个方向都要刷：

- 升：五元位已有 `proof ∧ reviewed`，历史列还写着 `heuristic`；
- 降（纠虚报）：历史列写着 `proof`，五元位却只到 `conjecture` —— 存量 105+ 条
  `cross_check→heuristic` 就是这一档。

四栏：会动（等级与历史列不一致，`direction` 分 up/down）/ 已经一致 /
凭据不够（`state` 取 `proof_review_gap()` 原值；等级口径下只留给"算不出凭据也读不出"
的残余）/ 没查成（`checked=False` + 原因）。

| 判据 | 它钉的事 | 红的样子 |
|---|---|---|
| a | dry-run：等级与历史列不一致 ⇒ 落"会动"，盘上零变化；CLI 打出等级与反算名 | CLI 不认旗标 / dry-run 顺手写盘 / 只打档位 |
| b | `--apply`：历史列被反算成 `proof_review`、`_grade_recomputed` 有痕（`to` 是等级） | 写错行 / 痕丢了 / 顺手改了别的行 |
| c | 幂等：第二次 `--apply` 全部"已经一致"、`statements.json` 逐字节不变 | 再写一次 / 时间戳变 |
| d | 降档（纠虚报）：历史 `proof` + 五元位 `conjecture` ⇒ `direction=down`，`--apply` 反算成 `heuristic` | 只升不降 / 把虚报留在盘上 |
| e | 概念行不进四栏（概念不参与等级链） | 把概念读成 conjecture |

所有 `--apply` 只跑在 `tmp_path` 的临时工作区；`projects/` 下的任何文件一个字节都不碰。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import cli
from agentflow import evidencebits as EB
from agentflow import verifications as VR
from agentflow.store import Store

#: 与 `test_fake_proof_review` 同一套造行方式（同一个门槛的判据不该有两套夹具）。
from test_fake_proof_review import _PROOF, _row, _write  # noqa: E402

SID = "000000"


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _row_with(sid: str, evidence_kind: str, *, reviewed: bool,
              kind: str = "lemma", numeric: str = "pending") -> dict:
    """一条带五元位的行：`reviewed` 由判据给（模拟 V 已签 / 未签）。"""
    ev = {"experiment_id": "000001", "script": "code/scan.py", "sha": "aa11"} \
        if numeric == "verified" else None
    bits = EB.bits_of(proof=True, proof_process=_PROOF,
                      reviewed=reviewed,
                      reviewed_by={"round": "V-1"} if reviewed else None,
                      numeric=numeric, numeric_evidence=ev, kind=kind)
    return _row(sid, evidence_kind=evidence_kind) | {"bits": bits}


def _write_row(store: Store, row: dict) -> dict:
    # 带 `bits` 的行要过 `bits_shape_problems`：等级缓存与现算必须一致。
    row = dict(row)
    row["bits"] = dict(row["bits"])
    row["bits"]["grade"] = EB.derive_grade(row["bits"], kind=str(row.get("kind") or ""))
    _write(store, row)
    return row


def _with_ledger_sign(store: Store, sid: str) -> None:
    """让这一行有一条真的 V 签（写盘那一半也翻位）—— 写 `proof_review` 的闸要它。

    走 `record_verification(store=...)`（与 `verify.verify_proof` 同一条写路径）：
    连续 `SIGN_STREAK_NEED` 次「成立」之后，第 3 笔会翻 `bits.reviewed` 并落台账。
    """
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        VR.record_verification(
            store.root, statement_id=sid, proof_text=_PROOF,
            verdict={"verdict": "成立", "findings": []},
            verifier="agent-V", store=store, proof_no=1)


def _force_kind(store: Store, sid: str, evidence_kind: str) -> None:
    """把历史列改回目标值（模拟"V 签过了、历史列还停在旧档"的存量行）。"""
    row = _disk_row(store, sid)
    row["evidence_kind"] = evidence_kind
    _write(store, row)


def _disk_row(store: Store, sid: str) -> dict:
    return next(dict(r) for r in store.rows("statements")
                if str(r.get("stmt_id")) == sid)


def _cols(out: dict) -> dict:
    return dict(out["columns"])


def _only(out: dict, column: str) -> list[dict]:
    return list(_cols(out)[column])


def _snapshot(root: pathlib.Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for sub in ("data", "verifications"):
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                out[str(path.relative_to(root))] = path.read_bytes()
    return out


# ------------------------------------------------------------------ a dry-run

def test_a_dry_run_sees_the_mismatch_and_writes_nothing(
        tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """a：五元位已到 `pre_theorem`、历史列还写 `heuristic` ⇒ "会动"；盘上零变化。"""
    st = _ws(tmp_path)
    _write_row(st, _row_with(SID, "heuristic", reviewed=True))
    before = _snapshot(st.root)

    out = VR.recompute_grades(st.root, st)
    assert out["checked"] is True, out
    will = _only(out, "will_upgrade")
    assert [(e["statement_id"], e["from"], e["to"], e["from_kind"], e["to_kind"],
             e["direction"]) for e in will] == [
        (SID, "conjecture", "pre_theorem", "heuristic", "proof_review", "up")], will
    assert _disk_row(st, SID)["evidence_kind"] == "heuristic"
    assert _snapshot(st.root) == before, "dry-run 动了盘"

    code = cli.main(["--root", str(st.root), "repair", "--backfill-grades"])
    text = capsys.readouterr().out
    assert code == 0, text
    assert "会动 1" in text, text
    assert f"{SID}  等级 conjecture → pre_theorem" in text, text
    assert "档位 heuristic → proof_review" in text, text
    assert _snapshot(st.root) == before, "CLI dry-run 动了盘"


# ------------------------------------------------------------------ b apply

def test_b_apply_reverses_the_kind_from_the_grade(tmp_path: pathlib.Path) -> None:
    """b：`--apply` ⇒ 历史列被反算成 `proof_review`、痕里的 `to` 是等级 `pre_theorem`。"""
    st = _ws(tmp_path)
    _write_row(st, _row_with(SID, "heuristic", reviewed=True))
    _with_ledger_sign(st, SID)                 # 写 `proof_review` 的闸要一条真签
    _force_kind(st, SID, "heuristic")          # 存量形态：签过、历史列还停在 heuristic
    other = _row_with("000001", "heuristic", reviewed=False)     # 一致行
    _write_row(st, other)
    before_other = _disk_row(st, "000001")

    out = VR.recompute_grades(st.root, st, apply=True)
    assert [e["statement_id"] for e in out["written"]] == [SID], out
    assert out["unmoved"] == [] and out["failed"] == [], out
    assert [e["statement_id"] for e in _only(out, "already_consistent")] == ["000001"], out

    row = _disk_row(st, SID)
    assert row["evidence_kind"] == "proof_review", row
    trace = dict(row.get(VR.GRADE_RECOMPUTED_KEY) or {})
    assert trace.get("to") == "pre_theorem", trace
    assert trace.get("to_kind") == "proof_review", trace
    assert str(trace.get("at") or ""), trace
    assert _disk_row(st, "000001") == before_other, "一致行被顺手改了"


# ------------------------------------------------------------------ c 幂等

def test_c_second_apply_changes_no_byte(tmp_path: pathlib.Path) -> None:
    """c：第二次 `--apply` ⇒ 全部"已经一致"、`statements.json` 逐字节不变。"""
    st = _ws(tmp_path)
    _write_row(st, _row_with(SID, "heuristic", reviewed=True))
    _with_ledger_sign(st, SID)
    _force_kind(st, SID, "heuristic")
    first = VR.recompute_grades(st.root, st, apply=True)
    assert [e["statement_id"] for e in first["written"]] == [SID], first
    trace = dict(_disk_row(st, SID).get(VR.GRADE_RECOMPUTED_KEY) or {})
    stamp = str(trace.get("at") or "")
    assert stamp, trace
    after_first = (st.root / "data" / "statements.json").read_bytes()

    second = VR.recompute_grades(st.root, st, apply=True)
    assert _only(second, "will_upgrade") == [], second
    assert [e["statement_id"] for e in _only(second, "already_consistent")] == [SID], second
    assert second["written"] == [] and second["unmoved"] == [] and second["failed"] == [], second
    assert (st.root / "data" / "statements.json").read_bytes() == after_first, "第二次 apply 又写了"
    assert str(dict(_disk_row(st, SID).get(VR.GRADE_RECOMPUTED_KEY) or {}).get("at") or "") == stamp


# ------------------------------------------------------------------ d 降档（纠虚报）

def test_d_a_self_reported_proof_is_downgraded_to_its_real_grade(tmp_path: pathlib.Path) -> None:
    """d：历史 `proof` + 五元位只到 `conjecture` ⇒ `direction=down`，apply 反算成 `heuristic`。

    这是本次改造的纠虚报那一半（存量 105+ 条 `cross_check→heuristic` 同形）：
    自报档位不再换来引用学分，重刷把它降到等级允许的那一档。
    """
    st = _ws(tmp_path)
    _write_row(st, _row_with(SID, "proof", reviewed=False))

    out = VR.recompute_grades(st.root, st)
    will = _only(out, "will_upgrade")
    assert [(e["from"], e["to"], e["direction"]) for e in will] == [
        ("theorem", "conjecture", "down")], will
    assert will[0]["to_kind"] == "heuristic", will

    out2 = VR.recompute_grades(st.root, st, apply=True)
    assert [e["statement_id"] for e in out2["written"]] == [SID], out2
    row = _disk_row(st, SID)
    assert row["evidence_kind"] == "heuristic", row
    assert dict(row.get(VR.GRADE_RECOMPUTED_KEY) or {}).get("to") == "conjecture", row


# ------------------------------------------------------------------ e 概念行

def test_e_a_concept_row_is_not_in_the_four_columns(tmp_path: pathlib.Path) -> None:
    """e：概念行不参与等级链 ⇒ 单列进 `concepts`，不混进任何一栏。"""
    st = _ws(tmp_path)
    concept = _row("000002", evidence_kind="heuristic", kind="concept",
                   statement_text="（待补）", proof_text="")
    _write(st, concept)
    out = VR.recompute_grades(st.root, st)
    assert [c["statement_id"] for c in out["concepts"]] == ["000002"], out
    for name, rows in _cols(out).items():
        assert not [r for r in rows if r["statement_id"] == "000002"], (name, rows)
