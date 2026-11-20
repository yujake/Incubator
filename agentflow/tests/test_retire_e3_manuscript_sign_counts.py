# -*- coding: utf-8 -*-
"""RETIRE-E3：「造」这一格从「只数 statements 行」换成两条并列来源。

业主 2026-11-20 逐字：「速修，把旧链退场」（`draft/189`）。配套口径：

```
旧链（2026-10-02～10-19）：proof → statements 行 → V 审那一行。
新链（2026-11-02 起、11-13 定型）：V 签落在稿上 → B 之后收录 ⇒ 第一阶段没有在册命题。
```

⇒ `reviewed_proof_rows` 必须能由「稿 + 稿上的 V 签」单独满足，`statements` 行退回成
「其中一种来源」（在册那一路一条不许少 —— 正控）。

本文件钉六件事，每条都能单独造红：

| # | 判据 | 造红的方式 |
|---|---|---|
| ① | 第一阶段正控：签过的稿 + 零册行 ⇒ `got=1`、`by_source.manuscript_sign=1` | 把新链那一路打桩掉 ⇒ `got=0`（反真空） |
| ② | 在册那一路不降、也不重复计：册行 + 同一份稿 ⇒ 仍是 1、`both=1` | 册行的签抽掉 ⇒ 0 |
| ③ | 稿有、没签 ⇒ 不算，`unsigned` 点名缺的是哪一版正文 | —— |
| ④ | 签有、稿找不到 ⇒ 不算，`sign_without_manuscript` 点名 | —— |
| ⑤ | 签过之后又被判「有毛病」⇒ 不算（后来的否决盖过更早的成立） | 把那一条改成「成立」⇒ 回到 1 |
| ⑥ | 签文件读不成 ⇒ `_leg_reading` 抛（验收行 `unreadable`、绝不是 0 / pass） | —— |

全部 tmp 工作区、零模型调用（签走 `_credential_fixture.issue_credential` 的真写口：
三行台账 + 一份 `out/vsigns/<正文sha>.json`）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

import _credential_fixture as CRED
from conftest import TS, sync_counters
from agentflow import closing as CL
from agentflow import proofregistry as PR
from agentflow import verifications as VR
from agentflow.store import Store

#: 被签的那一段正文（`## 证明` 小节的正文；与 V 签的 sha 是同一把尺）。
BODY = "第一步：由定义直接得到。\n第二步：对两边取极限。\n第三步：代入单调性。"


# ============================================================ 夹具


def _ws(root: pathlib.Path) -> Store:
    st = Store(root)
    st.init(force=True)
    return st


def _manuscript(root: pathlib.Path, name: str = "f-proof-000000.md",
                body: str = BODY) -> pathlib.Path:
    """写一份签载体稿（`reports/{f,b,e}-proof-*.md`，`## 证明` 那一节就是被签的正文）。"""
    p = root / "reports" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# 证明稿 {name}\n\n## 证明\n\n{body}\n", encoding="utf-8",
                 newline="\n")
    return p


def _statement(store: Store, stmt_id: str, **kw) -> None:
    """往 `statements` 里写一行（形状照 `test_closing_gate._statement`）。"""
    row = {"stmt_id": stmt_id, "origin": "own_result", "kind": "theorem",
           "statement_full": "设 G 是 m-正则图；则……", "created_at": TS,
           "created_by": "test",
           "quote_reason": "我方自产命题，没有外部引文要比对",
           "proof_text": BODY}
    row.update(kw)
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    sync_counters(store)


def _signed_manuscript(root: pathlib.Path, *, body: str = BODY,
                       name: str = "f-proof-000000.md",
                       statement_id: str = "") -> pathlib.Path:
    """造一份「稿 + 稿上的真签」：签文件、三行台账、手稿都在盘上。"""
    path = _manuscript(root, name=name, body=body)
    rel = f"reports/{name}"
    CRED.issue_credential(root, proof_text=body, statement_id=statement_id,
                          manuscript=rel, artifact_path=rel)
    return path


def _reading(st: Store) -> tuple[int, dict]:
    return CL._leg_reading(st, "reviewed_proof_rows", st.root)


def _stub_new_chain(_root, _rows, _counted) -> dict:
    """把新链那一路打桩掉（= 只有册行那一路的旧读法）。"""
    return {"checked": True, "scanned": 0, "counted": [], "counted_total": 0,
            "counted_keys": [], "both_ids": [], "covered_unmet": [],
            "unsigned": [], "unbacked": [], "superseded": [], "unreadable": [],
            "sign_without_manuscript": [], "problems": [], "why": "（打桩）"}


# ============================================================ ① 第一阶段正控 + 反真空


def test_a_signed_manuscript_alone_satisfies_the_construct_leg(tmp_path: pathlib.Path):
    """① 第一阶段：V 签了稿、B 还没收录（`statements` 0 行）⇒ 这一格也成立。

    这正是 `draft/189` 的形态：产出链已换成「先签稿、后收录」，而「造」那一格若只数
    册行，第一阶段就永远读 0 ⇒ 收工门结构上收不了（lp-ball-12 的 P6 是同一个病，
    E3 是下一个）。判据：稿在、签成立且复算得上 ⇒ `got=1`。
    """
    st = _ws(tmp_path)
    _signed_manuscript(tmp_path)

    got, detail = _reading(st)

    assert got == 1, detail
    assert detail["by_source"] == {"registered": 0, "manuscript_sign": 1, "both": 0}, \
        detail["by_source"]
    ms = detail["manuscript_sign"]
    assert ms["checked"] is True and ms["scanned"] == 1, ms
    assert ms["counted_total"] == 1, ms
    assert ms["counted"][0]["path"] == "reports/f-proof-000000.md", ms["counted"]
    assert ms["counted"][0]["verdict"] == "成立", ms["counted"]
    assert ms["counted"][0]["streak"] == 3 and ms["counted"][0]["need"] == 3, ms["counted"]
    # 这一类的"不算"表都必须是空的：正控不许带着一条 why_not 混过去
    for bucket in ("unsigned", "unbacked", "superseded", "covered_unmet",
                   "sign_without_manuscript", "unreadable"):
        assert ms[bucket] == [], (bucket, ms[bucket])
    assert detail["why_not"] == [], detail["why_not"]


def test_the_leg_goes_back_to_zero_when_the_new_chain_is_stubbed(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """① 的反真空：把新链那一路打桩掉 ⇒ 同一份盘上证据读回 0。

    没有这一条，① 可能靠别的路（例如册行）亮绿，而"改的是「造」的来源"这句话就没人验。
    """
    st = _ws(tmp_path)
    _signed_manuscript(tmp_path)

    assert _reading(st)[0] == 1, "夹具前提：不打桩时这一格应当算 1"

    monkeypatch.setattr(CL, "_manuscript_sign_reading", _stub_new_chain)
    got, detail = _reading(st)
    assert got == 0, ("打桩之后仍算得到：说明那一条读数不来自新链那一路", detail)
    assert detail["by_source"]["manuscript_sign"] == 0, detail["by_source"]


# ============================================================ ② 在册那一路不降、也不重复计


def test_a_registered_row_is_counted_once_and_attributed_to_both_sources(
        tmp_path: pathlib.Path):
    """② 正控：册行那一路数过的一条一条不少，而同一份稿不再被第二路数一遍。

    `by_source` 的三格是互斥的（`registered + manuscript_sign + both` = 腿的读数）：
    两路都看得见的记 `both`。少记一条 = 降闸；多记一条 = 同一份证明被数了两次。
    """
    st = _ws(tmp_path)
    _statement(st, "000041", manuscript_id="000000",
               bits={"proof": True,
                     "evidence": {"proof_source": "own", "proof_process": BODY}})
    # 册行那一路的"签"：台账落在 `verifications/000041.jsonl`，稿与正文同一份。
    _signed_manuscript(tmp_path, statement_id="000041")

    got, detail = _reading(st)

    assert got == 1, detail
    assert detail["counted_statements"] == 1, detail["counted"]
    assert detail["by_source"] == {"registered": 0, "manuscript_sign": 0, "both": 1}, \
        detail["by_source"]
    assert detail["manuscript_sign"]["both_ids"] == ["000041"], \
        detail["manuscript_sign"]["both_ids"]


def test_a_registered_row_without_a_live_sign_does_not_count(tmp_path: pathlib.Path):
    """② 的负控：册行在、签不在（位上说审过，而凭据里没有任何可定位的签名）⇒ 仍是 0。

    这一条守的是在册那一路本来就有那条判据（`review_without_locator_ids`：
    判不了 ⇒ 不计数），新链那一路不许把它垫起来。
    """
    st = _ws(tmp_path)
    _statement(st, "000042",
               bits={"proof": True, "reviewed": True,
                     "evidence": {"proof_source": "own", "proof_process": BODY,
                                  "reviewed_by": {"round": "V-0001",
                                                  "verdict": "no_defect"}}})

    got, detail = _reading(st)

    assert got == 0, detail
    assert detail["review_without_locator_ids"] == ["000042"], detail
    assert detail["by_source"] == {"registered": 0, "manuscript_sign": 0, "both": 0}, \
        detail["by_source"]


# ============================================================ ③ 稿有、没签


def test_a_manuscript_without_a_sign_does_not_count_and_says_what_is_missing(
        tmp_path: pathlib.Path):
    """③ 三态之一：稿在盘上、这一版没有签文件 ⇒ 不算，并说清缺的是哪一版正文。

    不许折成"这一格没查成"（签的目录读得到，结论是确定的），也不许折成"算了"。
    """
    st = _ws(tmp_path)
    _manuscript(tmp_path)

    got, detail = _reading(st)

    assert got == 0, detail
    ms = detail["manuscript_sign"]
    assert ms["checked"] is True and ms["scanned"] == 1, ms
    assert [x["path"] for x in ms["unsigned"]] == ["reports/f-proof-000000.md"], ms
    assert "没签" in ms["unsigned"][0]["why"], ms["unsigned"]
    assert detail["why_not"] and detail["why_not"][0].startswith("[unsigned]"), \
        detail["why_not"]


# ============================================================ ④ 签有、稿找不到


def test_a_sign_pointing_at_a_missing_manuscript_does_not_count(tmp_path: pathlib.Path):
    """③ 三态之二：签文件指一份不在盘上的稿 ⇒ 不算（签有、稿找不到），逐条点名。"""
    st = _ws(tmp_path)
    rel = "reports/f-proof-000009.md"        # 故意不落这份稿
    CRED.issue_credential(tmp_path, proof_text=BODY, manuscript=rel, artifact_path=rel)

    got, detail = _reading(st)

    assert got == 0, detail
    ms = detail["manuscript_sign"]
    assert ms["scanned"] == 0, ms
    assert [x["artifact_path"] for x in ms["sign_without_manuscript"]] == [rel], ms
    assert any("稿找不到" in w for w in detail["why_not"]), detail["why_not"]


# ============================================================ ⑤ 后来的否决


def test_a_sign_superseded_by_a_later_rejection_does_not_count(
        tmp_path: pathlib.Path):
    """⑤ 同一份正文上「先成立、后有毛病」⇒ 不算（`review_standing` 的同一条纪律）。

    真机读数（`projects/lp-ball-12`）：`reports/f-proof-000004.md` 于 05:18:58 拿到
    「成立 3/3」，05:21:57 的 `u-000045` 又判了「有毛病」。旧签不是免死金牌 ——
    这一格若把它算成「造」，就等于把 V 已经打回的稿重新点亮。
    """
    st = _ws(tmp_path)
    _signed_manuscript(tmp_path)
    # 同一份正文、新的一趟送审：V 判「有毛病」（轴 fault）。
    VR.record_verification(
        str(tmp_path), statement_id="000000", proof_text=BODY,
        verdict={"verdict": "有毛病", "findings": [{"kind": "断点", "level": "error",
                                                    "step": 2, "detail": "第二步不成立"}]},
        secretary_judge={"axis": "fault", "checked": True, "reason": "夹具：判有毛病"},
        flip=False, review_call="call-2", review_pass=1)

    got, detail = _reading(st)

    assert got == 0, detail
    ms = detail["manuscript_sign"]
    assert ms["counted_total"] == 0, ms
    assert [x["path"] for x in ms["superseded"]] == ["reports/f-proof-000000.md"], ms
    assert any("后来的否决" in w for w in detail["why_not"]), detail["why_not"]


def test_a_later_positive_review_keeps_the_sign_standing(tmp_path: pathlib.Path):
    """⑤ 的负控（反真空）：后来那一行是「成立」⇒ 这一签照样算（别把"再审一次"读成否决）。

    为什么单列：只按"后来还有行"判否决，会把"又复核了一遍、还是成立"读成推翻 ——
    那是把一条真凭据读没了（方向相反的同一个错）。
    """
    st = _ws(tmp_path)
    _signed_manuscript(tmp_path)
    VR.record_verification(
        str(tmp_path), statement_id="000000", proof_text=BODY,
        verdict={"verdict": "成立", "findings": []},
        secretary_judge={"axis": "clean", "checked": True, "reason": "夹具：复核成立"},
        flip=False, review_call="call-2", review_pass=1)

    got, detail = _reading(st)

    assert got == 1, detail
    assert detail["manuscript_sign"]["superseded"] == [], detail["manuscript_sign"]
    assert detail["manuscript_sign"]["counted_total"] == 1, detail["manuscript_sign"]


# ============================================================ ⑥ 读不成 ⇒ unknown


def test_an_unreadable_sign_file_makes_the_row_unreadable_not_zero(
        tmp_path: pathlib.Path):
    """③ 三态之三：对应 sha 的签文件坏掉 ⇒ 没查成（抛）⇒ 验收行 `unreadable`。

    三态纪律：`0` 是"查过了、没有"，`unknown` 是"没查成"。签文件坏掉属于后者 ——
    把它折成 0 会让"签丢了"与"本来就没签"长得一样，折成 pass 更坏。
    """
    st = _ws(tmp_path)
    _signed_manuscript(tmp_path)
    sha = PR.proof_sha(BODY)
    sign_file = tmp_path / "out" / "vsigns" / f"{sha}.json"
    assert sign_file.is_file(), "夹具前提：签文件在盘上"
    sign_file.write_text("{ 这不是 JSON\n", encoding="utf-8", newline="\n")

    with pytest.raises(RuntimeError) as exc:
        _reading(st)
    assert "没查成" in str(exc.value), exc.value

    # ---- 接到验收门那一行上：这一行是 `unreadable`（got=None、ok=None），不是 0。
    checks = tmp_path / "out" / "paper" / "ACCEPTANCE-CHECKS.json"
    checks.parent.mkdir(parents=True, exist_ok=True)
    checks.write_text(json.dumps({"checks": [
        {"id": "P3b", "name": "造（我方判决性证据）",
         "kind": "reviewed_proof_rows", "min": 1}]}, ensure_ascii=False),
        encoding="utf-8")
    rep = CL.ClosingReport()
    CL._check_acceptance(rep, st, str(tmp_path))
    row = rep.readings["acceptance"]["rows"][0]
    assert row["state"] == "unreadable", row
    assert row["got"] is None and row["ok"] is None, row
    assert any(f.code == "acceptance_leg_unreadable" for f in rep.findings), rep.findings
    # 行级读不懂 ⇒ 整格 `unknown`（`elif unreadable_rows:` 那一支；绝不是 pass）
    assert rep.status["acceptance"] == "unknown", rep.status
