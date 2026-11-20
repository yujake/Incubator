# -*- coding: utf-8 -*-
"""RETIRE-D66FIX：「造」这一格的两条并列来源 —— 册行 ∨「稿 + 稿上的成立签」。

业主 2026-11-20 逐字：「速修，把旧链退场」「自足证明是几乎唯一的生产方式」
「F/E/B 第一阶段不依赖命题已在册」（`draft/189`）。

`reviewed_proof_rows` 那一行（RETIRE-E3）已经从「稿 + 签」独立读出来了，但整格
acceptance 还红在 D66 的内容判据 `closing.content_leg_unmet` 的 ②：它要求
`statements` 里有 `origin=own_result` 的行，而第一阶段（V 已签、B 还没收录）是 0 行。
本文件把那一格换成两条并列来源，并钉住四件事：

| # | 判据 | 造红的方式 |
|---|---|---|
| ① | 第一阶段正控：稿 + 成立签、0 册行 ⇒ 内容判据 pass、整格 acceptance pass | 把新链那一路打桩掉 ⇒ 必红（反真空） |
| ② | 在册那一路不降：册行 + 与它关联的签仍算（正控） | —— |
| ③ | 稿有、没签 ⇒ 仍 fail，`unsigned` 逐条点名 | —— |
| ④ | 签有、稿找不到 ⇒ 仍 fail，`sign_without_manuscript` 逐条点名 | —— |
| ⑤ | 签文件读不成 ⇒ `construct_leg.state == unknown`，整格 acceptance `unknown`（不折成 pass/fail） | —— |

全部 tmp 工作区、零模型调用（签走 `_credential_fixture.issue_credential` 的真写口）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

import _credential_fixture as CRED
from conftest import TS, sync_counters
from agentflow import closing as CL
from agentflow import proofregistry as PR
from agentflow.store import Store

#: 被签的那一段正文（`## 证明` 小节；与 V 签的 sha 是同一把尺）。
BODY = "第一步：由定义直接得到。\n第二步：对两边取极限。\n第三步：代入单调性。"


def _ws(root: pathlib.Path) -> Store:
    st = Store(root)
    st.init(force=True)
    return st


def _manuscript(root: pathlib.Path, name: str = "f-proof-000000.md",
                body: str = BODY) -> pathlib.Path:
    p = root / "reports" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# 证明稿 {name}\n\n## 证明\n\n{body}\n", encoding="utf-8",
                 newline="\n")
    return p


def _signed_manuscript(root: pathlib.Path, *, body: str = BODY,
                       name: str = "f-proof-000000.md",
                       statement_id: str = "") -> pathlib.Path:
    """造一份「稿 + 稿上的真签」：签文件、三行台账、手稿都在盘上。"""
    path = _manuscript(root, name=name, body=body)
    rel = f"reports/{name}"
    CRED.issue_credential(root, proof_text=body, statement_id=statement_id,
                          manuscript=rel, artifact_path=rel)
    return path


def _statement(store: Store, stmt_id: str) -> None:
    """往 `statements` 里写一条自产命题（形状照 `test_retire_e3_manuscript_sign_counts`）。"""
    row = {"stmt_id": stmt_id, "origin": "own_result", "kind": "theorem",
           "statement_full": "设 G 是 m-正则图；则……", "created_at": TS,
           "created_by": "test",
           "quote_reason": "我方自产命题，没有外部引文要比对",
           "proof_text": BODY}
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    sync_counters(store)


def _content(st: Store) -> tuple[list[str], dict]:
    unmet, readings = CL.content_leg_unmet(
        st, st.root, researched=True, computed_kinds=["reviewed_proof_rows"])
    return unmet, (readings.get("construct_leg") or {})


def _stub_new_chain(_root, _rows, _counted) -> dict:
    return {"checked": True, "scanned": 0, "counted": [], "counted_total": 0,
            "counted_keys": [], "both_ids": [], "covered_unmet": [],
            "unsigned": [], "unbacked": [], "superseded": [], "unreadable": [],
            "sign_without_manuscript": [], "problems": [], "why": "（打桩）"}


# ============================================================ ① 第一阶段正控


def test_a_signed_manuscript_alone_satisfies_the_construct_leg(
        tmp_path: pathlib.Path) -> None:
    """第一阶段：V 签了稿、B 还没收录（`statements` 0 行）⇒ 内容判据也成立。

    改前这一格只认册行 ⇒ 第一阶段永远 unmet（`the first-stage copy` 的 acceptance
    整格因此红）。改后：稿 + 成立签（verdict=成立、streak=3/3、复算通过、
    没被后来的否决盖过）就是「造」的凭据。
    """
    st = _ws(tmp_path)
    _signed_manuscript(tmp_path)

    unmet, leg = _content(st)

    assert unmet == [], leg
    assert leg["state"] == "pass", leg
    assert leg["statements"] == 0 and leg["own_result"] == 0, leg
    assert leg["with_signed_manuscript"] == 0, leg
    assert leg["by_source"] == {"registered": 0, "manuscript_sign": 1, "both": 0}, leg
    ms = leg["manuscript_sign"]
    assert ms["checked"] is True and ms["scanned"] == 1 and ms["counted_total"] == 1, ms
    assert ms["counted"][0]["path"] == "reports/f-proof-000000.md", ms["counted"]
    assert ms["counted"][0]["verdict"] == "成立", ms["counted"]
    assert ms["counted"][0]["streak"] == 3 and ms["counted"][0]["need"] == 3, ms["counted"]
    # 正控不许带着一条 why_not 混过去
    assert leg["why_not"] == [], leg["why_not"]


def test_stubbing_the_new_chain_turns_the_construct_leg_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """① 的反真空：把新链那一路打桩掉 ⇒ 同一份盘上证据必红。

    没有这一条，① 可能靠别的路亮绿，而「改的是造那一格的来源」这句话就没人验。
    """
    st = _ws(tmp_path)
    _signed_manuscript(tmp_path)
    assert _content(st)[0] == [], "夹具前提：不打桩时这一格应当 pass"

    monkeypatch.setattr(CL, "_manuscript_sign_reading", _stub_new_chain)
    unmet, leg = _content(st)

    assert unmet and "「造」那一环" in unmet[0], unmet
    assert leg["state"] == "unmet", leg
    assert leg["by_source"] == {"registered": 0, "manuscript_sign": 0, "both": 0}, leg
    assert any(w.startswith("[no_source]") for w in leg["why_not"]), leg["why_not"]


# ============================================================ ② 在册那一路不降


def test_a_registered_row_with_its_signed_manuscript_still_counts(
        tmp_path: pathlib.Path) -> None:
    """正控：册行那一路一条不许少 —— 有签的册行仍然算「造」，且记进 `registered`。"""
    st = _ws(tmp_path)
    _statement(st, "000041")
    CRED.issue_credential(tmp_path, proof_text=BODY, statement_id="000041",
                          manuscript="reports/f-proof-000041.md",
                          artifact_path="reports/f-proof-000041.md")

    unmet, leg = _content(st)

    assert unmet == [], leg
    assert leg["state"] == "pass", leg
    assert leg["own_result"] == 1 and leg["with_signed_manuscript"] == 1, leg
    assert leg["by_source"] == {"registered": 1, "manuscript_sign": 0, "both": 0}, leg
    assert [e["stmt_id"] for e in leg["linked"]] == ["000041"], leg["linked"]


def test_registered_row_without_a_link_does_not_borrow_the_new_chain(
        tmp_path: pathlib.Path) -> None:
    """归属纪律：册行覆盖的稿若册行那一路没数它，新链也不补（不绕过等级与最新判词）。

    真机形状（`projects/lp-ball-12` 的 `f-proof-000004`：05:18:58 成立、05:21:57 被
    `u-000045` 判「有毛病」）：把这份稿再算一遍等于把 V 已经打回的稿重新点亮。
    """
    st = _ws(tmp_path)
    _statement(st, "000042")        # 册行在，但没有与它关联的签
    _signed_manuscript(tmp_path)    # 一份签过的稿，但它被 000042 这一行覆盖（按稿号）

    unmet, leg = _content(st)

    # 000042 没有签关联 ⇒ 册行那一路不算；稿归册行那一路判 ⇒ 新链不补
    assert unmet, leg
    assert leg["state"] == "unmet", leg
    assert leg["by_source"] == {"registered": 0, "manuscript_sign": 0, "both": 0}, leg


# ============================================================ ③ / ④ 负控


def test_a_manuscript_without_a_sign_still_fails(tmp_path: pathlib.Path) -> None:
    """负控：有稿没签 ⇒ 仍 fail（不许变成恒过），并说清缺的是哪一版正文。"""
    st = _ws(tmp_path)
    _manuscript(tmp_path)

    unmet, leg = _content(st)

    assert unmet, leg
    assert leg["state"] == "unmet", leg
    assert leg["by_source"] == {"registered": 0, "manuscript_sign": 0, "both": 0}, leg
    assert [x["path"] for x in leg["manuscript_sign"]["counted"]] == [], leg
    assert leg["why_not"] and leg["why_not"][0].startswith("[unsigned]"), leg["why_not"]
    assert "没签" in leg["why_not"][0], leg["why_not"]


def test_a_sign_pointing_at_a_missing_manuscript_still_fails(
        tmp_path: pathlib.Path) -> None:
    """负控：签文件指一份不在盘上的稿 ⇒ 不算（签有、稿找不到），逐条点名。"""
    st = _ws(tmp_path)
    rel = "reports/f-proof-000009.md"
    CRED.issue_credential(tmp_path, proof_text=BODY, manuscript=rel, artifact_path=rel)

    unmet, leg = _content(st)

    assert unmet, leg
    assert leg["state"] == "unmet", leg
    assert leg["manuscript_sign"]["scanned"] == 0, leg["manuscript_sign"]
    assert any("稿找不到" in w for w in leg["why_not"]), leg["why_not"]


# ============================================================ ⑤ 三态


def test_an_unreadable_sign_file_makes_the_branch_unknown(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """三态：签文件读不成 ⇒ 该分支 unknown（不是 0，也不是 pass）。

    这一支与 E3 的 `reviewed_proof_rows` 同一套判定：`checked=False` 时任何一条都
    不许被读成「查过了、没有」。整格 acceptance 的接线另有一条（见下一条）。
    """
    st = _ws(tmp_path)
    _signed_manuscript(tmp_path)
    sha = PR.proof_sha(BODY)
    sign_file = tmp_path / "out" / "vsigns" / f"{sha}.json"
    assert sign_file.is_file(), "夹具前提：签文件在盘上"
    sign_file.write_text("{ 这不是 JSON\n", encoding="utf-8", newline="\n")

    unmet, leg = _content(st)

    assert unmet == [], leg
    assert leg["state"] == "unknown", leg
    assert "没查成" in leg["why_unknown"], leg["why_unknown"]
    assert any(w.startswith("[unreadable]") for w in leg["why_not"]), leg["why_not"]


def test_content_unknown_makes_the_acceptance_cell_unknown(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """接线：内容判据落 `unknown` ⇒ 整格 acceptance 记 `unknown`（不是 pass）。

    为什么必须有一条：`content_leg_unmet` 把「没查成」放进 `unknown_branches`
    而不是 `unmet`（后者是「不满足」）。验收格若只读 `unmet`，签文件坏掉那一趟
    会被显示成 pass —— 那是这一批最该防的折平。
    """
    st = _ws(tmp_path)
    checks = tmp_path / "out" / "paper" / CL.ACCEPTANCE_CHECKS_NAME.split("/", 2)[-1]
    checks.parent.mkdir(parents=True, exist_ok=True)
    checks.write_text(json.dumps({"checks": [
        {"id": "P3b", "name": "造", "kind": "reviewed_proof_rows", "min": 0}]},
        ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(
        CL, "content_leg_unmet",
        lambda *a, **k: ([], {"unknown_branches": ["construct_leg"],
                              "construct_leg": {"state": "unknown",
                                                "why_unknown": "夹具：签文件读不成"}}))

    rep = CL.ClosingReport()
    CL._check_acceptance(rep, st, str(tmp_path))

    assert rep.status["acceptance"] == "unknown", rep.to_dict()
    assert any(f.code == "acceptance_content_unknown" for f in rep.findings), rep.findings


# ============================================================ 整格：第一阶段副本


def test_the_first_stage_copy_passes_the_acceptance_cell(tmp_path: pathlib.Path) -> None:
    """整格正控：摘掉册行、只留盘上稿与签 ⇒ acceptance 从 fail(acceptance_unmet) 变 pass。

    用 `test_closing_gate._research_ready` 的「别的都过」底座（业主：内容判据的负控
    只有在这一份底座上才能证明红的是这一条），把 `statements` 置空 = 第一阶段的形状。
    """
    import test_closing_gate as G

    st, report, ws = G._research_ready(tmp_path, cover=G._construct_cover())
    stmts = ws / "data" / "statements.json"
    doc = json.loads(stmts.read_text(encoding="utf-8"))
    doc["rows"] = []
    stmts.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8", newline="\n")
    _signed_manuscript(ws)
    st2 = Store(ws)

    rep = G._gate(st2, report)

    assert rep.status["acceptance"] == "pass", rep.to_dict()
    leg = rep.readings["acceptance"]["content_branches"]["construct_leg"]
    assert leg["state"] == "pass", leg
    assert leg["statements"] == 0 and leg["by_source"]["manuscript_sign"] == 1, leg
