# -*- coding: utf-8 -*-
"""判据：签凭据的复算（`vsigns.credential_reading` / `credentials_reading`）。

## 这条判据钉的是哪一次现场

2026-11-19 的 lp-ball-11 有两份互相矛盾的读数：

- 网页的 `vsign.recomputable = 0`（页面上印「复算通过 0 份」）；
- 盘上有一份签文件 `out/vsigns/80061a57….json`，3 passes、verdict=成立、streak 3/3，
  锚点那本台账 `verifications/pending/30af0d0b….jsonl` 里 u-000004/5/6 三行逐条对得上。

取证结论（`temp/signfix/REPORT.md`）：那个 0 是在一份只读副本
（`temp/webcap/backend`，只拷了 `data/` `index/` `out/` `sessions/`）上读的 ——
副本里没有 `verifications/`，于是"锚点指着的那本台账不在盘上"是确实成立的读数，
不是那份签的问题。同一份实现在真工区上读到 1，在 lp-ball-12 的 6 份上读到 6。

## 四条（与派活的 a/b/c/d 一一对应）

a. 真合法的签 ⇒ `recomputable` 计 1 份（正控：lp-ball-12 那 6 份的形状）；
b. 无效的签 ⇒ 计 0 份，且 `problem` 是受控码、`why` 点名是哪一条链断了
   （形状取自 lp-ball-11 那份签，逐条拆）；
c. "复算了没"与"算不算签"是两格：文件在而复算不过 ⇒ `files` 照数、`unbacked` 记一份，
   `credential.found` 仍为真、`problem` 有码 —— 不许被读成"没有签文件"；
d. 反真空：把复算打桩成恒真 ⇒ b 必红（见 `test_d_...`）。

另加一条（取证里发现的第二处）：签的归属判据从前在两处各写了一遍，
`backed_reading`（门 / 页面的 `vsign.backed` / `without_sign`）用的是"签文件里那格
命题号与这一行逐字相等"，而签的唯一读口用的是 `_sign_names_statement`（空号 =
签发时尚在收录之前，是常态）。真机 7 份签全是空号 ⇒ 同一份签在一个读口"签了"、
在另一个读口"无侧文件"。这条判据把两个方向都钉住（空号 ⇒ 有主；别人的号 ⇒ 仍无主）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

import pytest

from agentflow import vsigns as VS

#: 签文件与台账行共用的时刻（取自 lp-ball-11 那份的真实值）。
TS = "2026-11-19T17:48:17+08:00"
#: 同一趟送审（`review_call` 是"这几转是不是同一次送审"的唯一凭据）。
CALL = "757fb961cec6"
#: 被签正文（只要一份确定的正文；正文 sha 全链由 `proofregistry.proof_sha` 现算）。
PROOF = "1. 取 p=2。\n2. 由第 1 步直接得到 A(2)=π。"
SID = "000005"
SIGNS = "out/vsigns"


# ------------------------------------------------------------------ 夹具

def _bits(sid: str) -> dict[str, Any]:
    """一条第 3 位为真的命题行（`bits.reviewed` 与 `reviewed_by_proof` 都真）。"""
    return {"numeric": "pending", "proof": True, "reviewed": True, "formal": "pending",
            "audited": False, "origin": "own_result",
            "evidence": {"numeric": {}, "numeric_reason": "", "proof_process": "",
                         "proof_source": "", "reviewed_by": {"F": sid},
                         "reviewed_source": "", "formal": {}, "formal_reason": "",
                         "audited_by": {}, "reviewed_by_proof": {"1": True}},
            "voided_by": {}, "grade": "proved", "audited_badge": False}


def _ledger_rows(sha: str) -> list[dict[str, Any]]:
    """三行 pending 台账（逐转一行；键集与 lp-ball-11 那本相同）。"""
    out = []
    for i in range(1, 4):
        out.append({
            "verification_id": f"u-00000{i + 3}", "review_call": CALL,
            "review_pass": i, "round": i + 2, "at": TS,
            "proof_sha256": sha, "object_sha256": "a" * 64,
            "object_path": "reports/f-proof-000000.md",
            "producer_role": "F", "producer_code": "attack-Ap-proof",
            "landed": "pending", "statement_id": SID, "verdict": "成立",
            "unresolved_errors": 0, "citation_checks": [],
            "secretary_judge": {"checked": True, "axis": "clean",
                                "answer": "没问题", "basis": ["逐步核对"]},
        })
    return out


def _sign_doc(sha: str, *, statement_id: str = "") -> dict[str, Any]:
    """一份签文件（键集与 lp-ball-11 那份相同；`passes` 指 u-000004/5/6）。"""
    return {
        "schema": "vsign/1", "artifact_sha": sha,
        "artifact_path": "reports/f-proof-000000.md",
        "statement_id": statement_id, "need": 3, "streak": 3, "count": 3,
        "verdict": "成立", "at": TS, "written_by": "secretary:F",
        "ledger": f"verifications/pending/{sha}.jsonl#u-000006",
        "passes": [{"verification_id": f"u-00000{i + 3}", "review_call": CALL,
                    "review_pass": i, "round": i + 2, "at": TS,
                    "proof_sha256": sha, "object_sha256": "a" * 64,
                    "object_path": "reports/f-proof-000000.md",
                    "axis": "clean", "verdict": "成立"} for i in range(1, 4)],
    }


def _workspace(root: pathlib.Path, *, count: int = 1, statement_id: str = "",
               ledger: bool = True, sign: bool = True) -> pathlib.Path:
    """造一个只带 statements + verifications + out/vsigns 的最小工区。

    `count` = 几份正文各不同的签（lp-ball-12 的 6 份就是 count=6）。
    """
    (root / "data").mkdir(parents=True)
    (root / "verifications" / "pending").mkdir(parents=True)
    (root / SIGNS).mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    for i in range(count):
        body = PROOF if i == 0 else f"{PROOF}\n{i + 1}. 第 {i + 1} 份。"
        sha = VS._sign_sha(body)
        sid = f"{int(SID) + i:06d}"
        rows.append({"stmt_id": sid, "kind": "theorem", "label": "夹具",
                     "statement_text": "T", "statement_full": "T", "proof_text": body,
                     "status": "active", "bits": _bits(sid)})
        if ledger:
            (root / "verifications" / "pending" / f"{sha}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False)
                          for r in _ledger_rows(sha)) + "\n", encoding="utf-8")
        if sign:
            (root / SIGNS / f"{sha}.json").write_text(
                json.dumps(_sign_doc(sha, statement_id=statement_id), ensure_ascii=False),
                encoding="utf-8")
    (root / "data" / "statements.json").write_text(
        json.dumps({"schema_version": 2, "rows": rows}, ensure_ascii=False),
        encoding="utf-8")
    return root


def _rows(root: pathlib.Path) -> list[dict[str, Any]]:
    doc = json.loads((root / "data" / "statements.json").read_text(encoding="utf-8"))
    return [dict(r) for r in (doc.get("rows") or [])]


def _sha() -> str:
    return VS._sign_sha(PROOF)


def _break(root: pathlib.Path, case: str) -> None:
    """把 lp-ball-11 那一份签的几条链逐条拆开（每条只拆一处）。"""
    sha = _sha()
    ledger_path = root / "verifications" / "pending" / f"{sha}.jsonl"
    sign_path = root / SIGNS / f"{sha}.json"
    rows = _ledger_rows(sha)
    doc = _sign_doc(sha)
    if case == "ledger_file_gone":          # 锚点那本台账不在盘上
        ledger_path.unlink()
    elif case == "row_gone":                # 锚点那行不在
        rows = [r for r in rows if r["verification_id"] != "u-000005"]
    elif case == "row_axis_gone":           # 那一行没有秘书轴
        rows[1]["secretary_judge"] = {"checked": False, "axis": ""}
    elif case == "row_sha_changed":         # 那一行盖的是另一版正文
        rows[1]["proof_sha256"] = "b" * 64
    elif case == "row_call_changed":        # 不是同一趟送审
        rows[1]["review_call"] = "000000000000"
    elif case == "row_pass_changed":        # 票与行对不上
        rows[1]["review_pass"] = 4
    elif case == "pass_gap":                # 趟内序号不重不漏
        doc["passes"][2]["review_pass"] = 4
    elif case == "verdict_bad":             # 签文件自己不是「成立」
        doc["verdict"] = "有毛病"
    elif case == "passes_empty":            # 没有判定读数
        doc["passes"] = []
    elif case == "self_anchored":           # 锚点指着稿自己
        doc["ledger"] = "reports/f-proof-000000.md"
    else:
        raise AssertionError(f"没有这一档：{case}")
    if case != "ledger_file_gone":
        ledger_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
    sign_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ 纯判据（可负控）

def _counted_without_backing(agg: Mapping[str, Any], broken: list[str]) -> list[str]:
    """纯函数（可负控）：已知验不过的那几份签，有没有被算进「复算通过」那一格。"""
    rows = {str(r.get("artifact_sha") or ""): r for r in (agg.get("rows") or [])}
    problems: list[str] = []
    for sha in broken:
        row = rows.get(sha)
        if row is None:
            problems.append(f"复算台账里没有 {sha[:12]}… 这一份（这一格没读它）")
        elif not str(row.get("problem") or ""):
            problems.append(f"验不过的签 {sha[:12]}… 没有理由码（复算这一格没判它）")
    files = int(agg.get("files") or 0)
    if int(agg.get("recomputable") or 0) + int(agg.get("unbacked") or 0) != files:
        problems.append("files 不等于 recomputable + unbacked（有文件两头都没记）")
    return problems


def _broken_link_problems(cred: Mapping[str, Any], want: str) -> list[str]:
    """纯函数（可负控）：这一份签是不是"复算不过、且理由点名到那一条链"。"""
    problems: list[str] = []
    if cred.get("recomputable"):
        problems.append("验不过的签被读成了「复算通过」")
    if not cred.get("found"):
        problems.append("签文件在，却被读成「没有签文件」")
    code = str(cred.get("problem") or "")
    if not code:
        problems.append("复算不过却没有理由码（读的人不知道断在哪）")
    elif want and want not in code:
        problems.append(f"理由码是 {code!r}，不是 {want!r}")
    if not str(cred.get("why") or ""):
        problems.append("没有一句人读的 why")
    return problems


# ================================================================== a 正控
def test_a_a_real_sign_file_recomputes(tmp_path: pathlib.Path) -> None:
    """真合法的签：1 份计 1 份；6 份计 6 份（lp-ball-12 那一档）。"""
    one = _workspace(tmp_path / "one", count=1)
    agg = VS.credentials_reading(one)
    assert agg["checked"] is True and agg["files"] == 1, agg
    assert (agg["recomputable"], agg["unbacked"]) == (1, 0), agg
    cred = VS.credential_reading(one, _sha())
    assert cred["recomputable"] is True and cred["problem"] == "", cred
    assert (cred["tier"], cred["ledger_kind"], cred["got"], cred["need"]) == (
        "call", "pending", 3, 3), cred
    assert str(cred["why"]).startswith("复算通过") and cred["problem"] == "", cred

    six = _workspace(tmp_path / "six", count=6)
    agg6 = VS.credentials_reading(six)
    assert (agg6["files"], agg6["recomputable"], agg6["unbacked"]) == (6, 6, 0), agg6
    assert _counted_without_backing(agg6, []) == [], _counted_without_backing(agg6, [])


def test_a_the_anchor_and_the_three_passes_are_the_same_review_call(
        tmp_path: pathlib.Path) -> None:
    """正控的第二半：复算过的不是"有 3 行"，是同一趟送审的三转（逐条点名）。

    `_recomputable` 的 call 形态：`review_pass` 恰好 1..need、同一个 `review_call`、
    每一条 `verification_id` 在那本台账里、那一行 sha 与签同源、且那一行自己签得住。
    """
    root = _workspace(tmp_path / "ws", count=1)
    cred = VS.credential_reading(root, _sha())
    rec = VS._recomputable(root, dict(cred["sign"]))
    assert rec["ok"] is True and rec["tier"] == "call", rec
    assert rec["verification_ids"] == ["u-000004", "u-000005", "u-000006"], rec
    assert rec["ledger"] == f"verifications/pending/{_sha()}.jsonl#u-000006", rec


# ================================================================== b 负控：逐条拆链
@pytest.mark.parametrize("case,want", [
    ("ledger_file_gone", "ledger_missing"),
    ("row_gone", "row_missing:u-000005"),
    ("row_axis_gone", "row_not_signable:u-000005"),
    ("row_sha_changed", "sha_mismatch:u-000005"),
    ("row_call_changed", "call_mismatch:u-000005"),
    ("row_pass_changed", "pass_mismatch:u-000005"),
    ("pass_gap", "pass_not_consecutive"),
    ("verdict_bad", "verdict_not_positive"),
    ("passes_empty", "passes_empty"),
    ("self_anchored", "sign_without_ledger"),
])
def test_b_each_broken_link_is_zero_and_names_the_link(
        tmp_path: pathlib.Path, case: str, want: str) -> None:
    """lp-ball-11 那份签的几条链，拆哪一条都必须计 0 份、且理由点名到那一条。"""
    root = _workspace(tmp_path / "ws", count=1)
    _break(root, case)
    agg, cred = VS.credentials_reading(root), VS.credential_reading(root, _sha())
    assert _broken_link_problems(cred, want) == [], (
        f"拆 {case} 之后：{_broken_link_problems(cred, want)}；读到 {cred}")
    assert agg["recomputable"] == 0 and agg["unbacked"] == 1, agg
    assert _counted_without_backing(agg, [_sha()]) == [], _counted_without_backing(
        agg, [_sha()])


# ================================================================== c 两件事分开
def test_c_a_broken_credential_is_still_a_file_that_was_read(
        tmp_path: pathlib.Path) -> None:
    """复算失败不许被当成"没有签"：文件照数、理由有码、状态是 unbacked 不是 unsigned。"""
    root = _workspace(tmp_path / "ws", count=1)
    _break(root, "ledger_file_gone")
    agg = VS.credentials_reading(root)
    cred = VS.credential_reading(root, _sha())
    assert (agg["files"], agg["recomputable"], agg["unbacked"]) == (1, 0, 1), agg
    assert cred["found"] is True and cred["checked"] is True, cred
    assert cred["problem"] == "ledger_missing", cred
    assert _sha()[:12] in str(cred["why"]), cred["why"]
    got = VS.sign_reading(root, statement_id=SID, proof_text=PROOF)
    assert got["state"] == "unbacked", got
    assert "签文件在" in got["why"] and "ledger_missing" in got["why"], got["why"]
    # 反方向：没有签文件的那一档才是"没签"，且它不叫 unbacked。
    gone = _workspace(tmp_path / "gone", count=1, sign=False)
    assert VS.credential_reading(gone, _sha())["found"] is False
    assert VS.credentials_reading(gone)["files"] == 0
    assert VS.sign_reading(gone, statement_id=SID, proof_text=PROOF)["state"] != "unbacked"


# ================================================================== d 反真空
def test_d_stubbing_the_recompute_makes_the_negative_go_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把复算打桩成恒真 ⇒ b 的那条负控必须翻红（否则 b 只是"没看"）。"""
    root = _workspace(tmp_path / "ws", count=1)
    _break(root, "ledger_file_gone")
    real_agg = VS.credentials_reading(root)
    assert _counted_without_backing(real_agg, [_sha()]) == []

    def _always_ok(_root: Any, _sign: Mapping[str, Any]) -> dict[str, Any]:
        return {"checked": True, "ok": True, "code": "", "tier": "call",
                "ledger_kind": "pending", "need": 3, "got": 3, "ledger": "", "anchor": "",
                "rows": 0, "verification_ids": [], "why": "打桩"}

    monkeypatch.setattr(VS, "_recomputable", _always_ok)
    stub_agg = VS.credentials_reading(root)
    assert VS.credential_reading(root, _sha())["recomputable"] is True, stub_agg
    problems = _counted_without_backing(stub_agg, [_sha()])
    assert problems, ("把复算打桩成恒真之后，b 的负控仍然是绿的 ⇒ 那条判据是真空的"
                      f"（{stub_agg}）")


# ================================================================== 同源：归属判据
def test_e_the_two_readers_share_one_ownership_rule(tmp_path: pathlib.Path) -> None:
    """空号签（签发时还没收录）在两个读口里都得有主；别人的号仍是无主。

    真机的 7 份签全部是空号（`statement_id: ""`）—— 这一档从前在
    `backed_reading` 里被读成「无侧文件」，与 `sign_reading` 的「签了」相互打架。
    """
    mine = _workspace(tmp_path / "mine", count=1, statement_id="")
    got = VS.backed_reading(mine, _rows(mine))
    assert got["checked"] is True, got
    assert got["signed"] == [SID], got
    assert got["backed"] == [SID] and got["without_sign"] == [], got

    # 反方向：签文件说它是别的命题的签 ⇒ 仍算"无主"（不许因为改了判据就放宽借光）。
    other = _workspace(tmp_path / "other", count=1, statement_id="000999")
    got2 = VS.backed_reading(other, _rows(other))
    assert got2["signed"] == [SID], got2
    assert got2["backed"] == [] and got2["without_sign"] == [SID], got2
    assert VS._sign_names_statement("", SID) is True
    assert VS._sign_names_statement("000999", SID) is False
