# -*- coding: utf-8 -*-
"""`reviewed` 那一格的四档：已签 / 未通过 / 未审 / 未读到（业主 2026-11-02 裁定）。

业主裁定逐字：

```
「应该分：已签/未通过/未审/未读到」
```

改前那一格只有三态，而且 `未读到` 被三种完全不同的情况共用：台账行读不到、
逐份签名表里没有这一份的键、判决原话空。于是「审过五次、三次判有毛病、从没签」
与「从没送审」在表上长得一模一样。

## 判据（四条各一例 + 一条反真空）

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | `verifications/<命题号>.jsonl` 不在 ⇒ `未审` | 这一档根本不存在（同一份行读成 `未读到`） |
| b | 台账在、而这一份的键不存在或为假 ⇒ `未通过` | 同上；"没键"被读成「未读到」，与从没送审混成一档 |
| c | 逐份表里这一份为真 ⇒ `已签（判决：…）` | 这一档在改前存在，但它与 a/b 共用一个"没签/未读到"出口，四档分不开 |
| d | 台账在但读不出（坏行 / 读异常）⇒ `未读到` | 读不出与"没有这一份"共用 `未读到`（这一格没查成，却被报成了一个结论） |
| e | 反真空：四个词两两不同；把渲染器打桩成恒 `已签` ⇒ a–d 的判据必红 | 判据本身不存在，反真空无从谈起 |
| c2 | 两条路径都签（多证明）⇒ 映射表每行各一格 `已签`；#2 的判决原话是 `成立` | 改前 `reviewed_by_proof` 只有 `{1: True}` ⇒ #2 被印成 `未通过` |
| c3 | 正文 sha 记在别的号上（B 按 canonical 号落的老账）⇒ `未读到`，不是 `未通过` | 「没这一号」被一律折成「V 判过、没通过」 |
| d2 | 第 2 条没签 ⇒ `未通过`（不是 `未读到`） | 把"读不到"那一档拿来盖"审过没签"，两种事实又共用一个词 |
| e2 | 第 2 条签过而正文已改（签 sha ≠ 现 sha）⇒ `未读到`，且与 d2 的 `未通过` 可分辨 | 一张旧签被读成"这一版签过了"（或与"没签"折平） |

## 关键：判「审过没审过」认台账在不在，不认 `reviewed_by_proof` 有没有键

写侧 `verifications._reviewed_statement_row` 只在真签的时候才建那个键，于是
「审过五次、三次判有毛病、从没签」这种命题在逐份表里也没有键。若按"没键 = 未审"，
就会把它读成"从没审过" —— 这是本轮一直在治的"两种事实共用一个词"的反向形态。
判据 b 里那条 `verifications/000000.jsonl` 五行的夹具就是它的现场。

全部用例都在 `tmp_path` 下自建工作区，一个模型调用都不发。
"""
from __future__ import annotations

import collections
import json
import pathlib

import pytest

from agentflow import papermapping as PM

# ------------------------------------------------------------------ 夹具

#: 一份"签过"的 statements 行（`bits.evidence.reviewed_by_proof` 是签字的正本）。
ROW_SIGNED: dict = {
    "stmt_id": "000001", "kind": "theorem",
    "bits": {"evidence": {
        "reviewed_by_proof": {"1": True},
        "reviewed_by": {"verifier": "agent-V", "verdict": "成立", "proof_no": 1},
    }},
}

#: 审过、判了有毛病、从没签：写侧不会建这个键，但这一行有审校台账。
ROW_NO_KEY: dict = {"stmt_id": "000002", "kind": "theorem", "bits": {"evidence": {}}}

#: 逐份表里这一份显式为假（历史 / 负控形状）。
ROW_FALSE: dict = {
    "stmt_id": "000003", "kind": "theorem",
    "bits": {"evidence": {"reviewed_by_proof": {"1": False}}},
}


def _review_ledger(root: pathlib.Path, sid: str, text: str) -> pathlib.Path:
    path = pathlib.Path(root) / "verifications" / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _four_problems(row: dict) -> list[str]:
    """四条判据的本体（空清单 = 都对）。

    抽成函数是为了让反真空那条打同一份判据：把 `reviewed_cell` 打桩成恒一个词，
    它必须报出问题 —— 否则"四条都绿"可能只是"这一条断言从没真的比过"。
    """
    problems: list[str] = []
    cases = (
        (PM.REVIEW_LEDGER_ABSENT, PM.REVIEWED_UNREVIEWED, "无台账"),
        (PM.REVIEW_LEDGER_PRESENT, PM.REVIEWED_NOT_PASSED, "有台账、无键"),
        (PM.REVIEW_LEDGER_UNREADABLE, PM.LEDGER_CELL_UNREADABLE, "台账读不出"),
    )
    for state, want, why in cases:
        got = PM.reviewed_cell(row, 1, review_ledger=state)
        if got != want:
            problems.append(f"{why}：印成 {got!r}，应当是 {want!r}")
    if not PM.reviewed_cell(ROW_SIGNED, 1,
                            review_ledger=PM.REVIEW_LEDGER_PRESENT
                            ).startswith(PM.REVIEWED_SIGNED):
        problems.append("有台账且键真：没有印成「已签」")
    return problems


# ------------------------------------------------------------------ a 无台账 ⇒ 未审

def test_a_no_review_ledger_means_unreviewed() -> None:
    """a) `verifications/<命题号>.jsonl` 不在 ⇒「未审」（从没送审）。

    改前红：这一档不存在。没键的行一律被读成 `未读到`（"这一格没查成"），
    于是"从没送审"这个结论从来没有被印出来过。

    键是假的也一样：台账不在就说明这一份从没送审（有键没台账是外部拼出来的行）。
    """
    assert PM.reviewed_cell(ROW_NO_KEY, 1, review_ledger=PM.REVIEW_LEDGER_ABSENT) == (
        PM.REVIEWED_UNREVIEWED)
    assert PM.reviewed_cell(ROW_FALSE, 1, review_ledger=PM.REVIEW_LEDGER_ABSENT) == (
        PM.REVIEWED_UNREVIEWED)
    # 三档是三个不同的词（不是同一个出口换了个名字）。
    assert PM.REVIEWED_UNREVIEWED != PM.REVIEWED_NOT_PASSED
    assert PM.REVIEWED_UNREVIEWED != PM.LEDGER_CELL_UNREADABLE


# ------------------------------------------------------------------ b 有台账无键 ⇒ 未通过

def test_b_ledger_present_without_a_key_means_not_passed() -> None:
    """b) 台账在、而这一份的键不存在或为假 ⇒「未通过」（审过，没拿到签）。

    改前红：`reviewed_by_proof` 里没有这一份的键 ⇒ `未读到`。真机上这正是
    「审过五次、三次判有毛病、从没签」的形状：写字侧只在真签时建键，于是这一条
    在逐份表里也没有键 —— 按"没键"读就会把"审过、没签"报成"没查成"。
    """
    assert PM.reviewed_cell(ROW_NO_KEY, 1,
                            review_ledger=PM.REVIEW_LEDGER_PRESENT) == PM.REVIEWED_NOT_PASSED
    assert PM.reviewed_cell(ROW_FALSE, 1,
                            review_ledger=PM.REVIEW_LEDGER_PRESENT) == PM.REVIEWED_NOT_PASSED
    assert PM.REVIEWED_NOT_PASSED != PM.LEDGER_CELL_UNREADABLE


def test_b2_the_five_reviews_nobody_signed_read_as_not_passed(
        tmp_path: pathlib.Path) -> None:
    """b) 的现场（反"没键 = 未审"）：五条审校、三次判有毛病、一次没签 ⇒「未通过」。

    这一条走写侧的填充口（`fill_ledger_cells`）：它读的是同一份 statements 表与
    同一个 `verifications/` 目录，不是把两格手填进表里。
    """
    root = pathlib.Path(tmp_path / "ws")
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "statements.json").write_text(json.dumps({
        "rows": [{"stmt_id": "000000", "kind": "theorem",
                  "bits": {"evidence": {}}}],
    }, ensure_ascii=False), encoding="utf-8")
    # 五行审校：三行判「有毛病」，两行判「成立」但都没签到发签次数（模拟从没签）。
    rows = [
        {"statement_id": "000000", "verification_id": f"v-{i:06d}", "proof_no": 1,
         "verdict": "有毛病" if i <= 3 else "成立"}
        for i in (1, 2, 3, 4, 5)
    ]
    _review_ledger(root, "000000",
                   "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    filled = PM.fill_ledger_cells(root, [
        PM.Row(kind="theorem", label="thm:never-signed", env_no=1,
               ledger_id="stmt:000000", proof_no=1, file="main.tex")])
    assert [r.reviewed for r in filled] == [PM.REVIEWED_NOT_PASSED], filled
    # 反方向：把那份台账删掉 ⇒ 同一行变成「未审」，而不是继续报「未通过」。
    (root / "verifications" / "000000.jsonl").unlink()
    again = PM.fill_ledger_cells(root, [
        PM.Row(kind="theorem", label="thm:never-signed", env_no=1,
               ledger_id="stmt:000000", proof_no=1, file="main.tex")])
    assert [r.reviewed for r in again] == [PM.REVIEWED_UNREVIEWED], again


# ------------------------------------------------------------------ c 键真 ⇒ 已签

def test_c_a_true_key_means_signed_with_the_verdict() -> None:
    """c) 逐份表里这一份为真 ⇒「已签（判决：<原话>）」。

    签字的正本是那个键（`reviewed_by_proof[证明号] is True`），不是台账在不在：
    台账不在时这一档照旧读得出来（签过这件事不因为台账丢了就变假）。
    判决原话那一格读不到 ⇒ `已签（判决：未读到）`：两件事分开写。
    """
    want = PM.REVIEWED_SIGNED_TEMPLATE.format(verdict="成立")
    for state in (PM.REVIEW_LEDGER_PRESENT, PM.REVIEW_LEDGER_ABSENT):
        assert PM.reviewed_cell(ROW_SIGNED, 1, review_ledger=state) == want
    silent = {"stmt_id": "000004", "kind": "theorem",
              "bits": {"evidence": {"reviewed_by_proof": {"1": True}}}}
    assert PM.reviewed_cell(silent, 1, review_ledger=PM.REVIEW_LEDGER_PRESENT) == (
        "已签（判决：未读到）")
    # 另一个证明号的签不借光：那一份的键为真不等于这一份签过。
    assert PM.reviewed_cell(ROW_SIGNED, 2, review_ledger=PM.REVIEW_LEDGER_PRESENT) == (
        PM.REVIEWED_NOT_PASSED)


# ------------------------------------------------------------------ d 台账读不出 ⇒ 未读到

def test_d_an_unreadable_ledger_means_unread(tmp_path: pathlib.Path) -> None:
    """d) 台账在但读不出（坏行 / 读异常），或 statements 行读不到 ⇒「未读到」。

    改前红：这一档虽然也叫 `未读到`，但它与"没有这一份的键"共用一个词 ——
    "这一格没查成"与"审过没签"在表上分不开。
    """
    root = pathlib.Path(tmp_path / "ws")
    # 坏行：文件在、有一条读不出来 ⇒ 这一格没查成。
    _review_ledger(root, "000005", '{"statement_id": "000005"}\n这条不是 JSON\n')
    assert PM.reviewed_ledger_state(root, "000005") == PM.REVIEW_LEDGER_UNREADABLE
    assert PM.reviewed_cell(ROW_NO_KEY, 1,
                            review_ledger=PM.REVIEW_LEDGER_UNREADABLE) == PM.LEDGER_CELL_UNREADABLE
    # statements 行读不到（行不在）：同样落到「未读到」，不是「未审」。
    assert PM.reviewed_cell(None, 1, review_ledger=PM.REVIEW_LEDGER_PRESENT) == (
        PM.LEDGER_CELL_UNREADABLE)

    # `reviewed_ledger_state` 的其余两档（同一处判据）：不在 / 在（空文件也算在）。
    assert PM.reviewed_ledger_state(root, "000006") == PM.REVIEW_LEDGER_ABSENT
    _review_ledger(root, "000007", "")
    assert PM.reviewed_ledger_state(root, "000007") == PM.REVIEW_LEDGER_PRESENT
    _review_ledger(root, "000008", '{"statement_id": "000008", "verdict": "成立"}\n')
    assert PM.reviewed_ledger_state(root, "000008") == PM.REVIEW_LEDGER_PRESENT


# ------------------------------------------------------------------ e 反真空

def test_e_anti_vacuum_a_constant_renderer_fails_the_four_way_judge(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """e) 反真空：四个词两两不同；把渲染器打桩成恒一个词 ⇒ 上面的判据必红。

    第 ① 半拦的是"四个常量其实是同一个词"（那样四档判据只比了字面）；
    第 ② 半拦的是"四条断言从没真的比过"（打桩之后仍然全绿就说明它比的是空气）。
    """
    words = (PM.REVIEWED_SIGNED, PM.REVIEWED_NOT_PASSED, PM.REVIEWED_UNREVIEWED,
             PM.LEDGER_CELL_UNREADABLE)
    assert len(set(words)) == 4, words
    assert _four_problems(ROW_NO_KEY) == [], _four_problems(ROW_NO_KEY)

    monkeypatch.setattr(PM, "reviewed_cell", lambda *a, **k: PM.REVIEWED_SIGNED)
    problems = _four_problems(ROW_NO_KEY)
    assert problems, "把渲染器打桩成恒「已签」之后四档判据仍然绿 ⇒ 它没有真的比过"
    # 三条"没签"来路被压成同一个词，是判据能看见它的原因。
    assert len({PM.reviewed_cell(ROW_NO_KEY, 1, review_ledger=state)
                for state in (PM.REVIEW_LEDGER_ABSENT, PM.REVIEW_LEDGER_PRESENT,
                              PM.REVIEW_LEDGER_UNREADABLE)}) == 1


# ------------------------------------------------------------------ f 英文附录四个词

def test_f_the_english_appendix_says_the_four_words() -> None:
    """f) 英文附录同步四个词：`signed (verdict: …)` / `not passed` / `unreviewed` / `(unread)`。

    只看 `MAPPING-ROW` 机器可读注释的最后两格（说明段里那四个词是散文，不参与比较）。
    英文论文的附录里一个 CJK 都不许有（D-45）—— 四档里任何一档漏翻都会在这里红。
    """
    rows = [
        PM.Row(kind="theorem", label="thm:signed", env_no=1, ledger_id="stmt:000001",
               proof_no=1, file="main.tex", ledger_kind="theorem",
               reviewed="已签（判决：成立）"),
        PM.Row(kind="theorem", label="thm:failed", env_no=2, ledger_id="stmt:000002",
               proof_no=1, file="main.tex", ledger_kind="theorem",
               reviewed=PM.REVIEWED_NOT_PASSED),
        PM.Row(kind="theorem", label="thm:never", env_no=3, ledger_id="stmt:000003",
               proof_no=1, file="main.tex", ledger_kind="theorem",
               reviewed=PM.REVIEWED_UNREVIEWED),
        PM.Row(kind="theorem", label="thm:unread", env_no=4, ledger_id="stmt:000004",
               proof_no=1, file="main.tex", ledger_kind="theorem",
               reviewed=PM.LEDGER_CELL_UNREADABLE),
    ]
    block = PM.render_appendix(rows, lean_enabled=False, language=PM.PAPER_LANGUAGE_EN)
    cells: dict[str, str] = {}
    for line in block.splitlines():
        text = line.strip()
        if not text.startswith(PM.APPENDIX_ROW_PREFIX.strip()):
            continue
        parts = text[len(PM.APPENDIX_ROW_PREFIX.strip()):].strip().split("|")
        cells[parts[2]] = parts[-1]
    assert cells == {
        "thm:signed": "signed (verdict: holds)",
        "thm:failed": "not passed",
        "thm:never": "unreviewed",
        "thm:unread": "(unread)",
    }, cells
    assert PM._cjk_count(block) == 0, "英文附录里出现了中文"


# ------------------------------------------------------------------ g 83 的形状

def test_g_the_83_shape_is_ten_unreviewed_and_one_not_passed(
        tmp_path: pathlib.Path) -> None:
    """g) 83 的复制品那种形状：11 行里 10 条「未审」+ 1 条「未通过」。

    造法与真机同构：11 条命题、只有 `000000` 有审校台账（五行、一行没签上），
    11 行对应表全部指这些命题。读数由写侧填充口现读，不是手填。
    """
    root = pathlib.Path(tmp_path / "copy83")
    (root / "data").mkdir(parents=True, exist_ok=True)
    sids = [f"{i:06d}" for i in range(11)]
    (root / "data" / "statements.json").write_text(json.dumps({
        "rows": [{"stmt_id": sid, "kind": "theorem", "bits": {"evidence": {}}}
                 for sid in sids],
    }, ensure_ascii=False), encoding="utf-8")
    _review_ledger(root, "000000", "".join(
        json.dumps({"statement_id": "000000", "verification_id": f"v-{i:06d}",
                    "proof_no": 1, "verdict": "有毛病"}, ensure_ascii=False) + "\n"
        for i in range(1, 6)))
    rows = [PM.Row(kind="theorem", label=f"thm:{i}", env_no=i, ledger_id=f"stmt:{sid}",
                   proof_no=1, file="main.tex") for i, sid in enumerate(sids, 1)]
    filled = PM.fill_ledger_cells(root, rows)
    dist = collections.Counter(str(r.reviewed) for r in filled)
    assert dict(dist) == {PM.REVIEWED_UNREVIEWED: 10, PM.REVIEWED_NOT_PASSED: 1}, dist
    # 逐条点名：那一条「未通过」是 000000，其余全是「未审」。
    assert [r.reviewed for r in filled if r.ledger_id == "stmt:000000"] == [
        PM.REVIEWED_NOT_PASSED]
    assert {str(r.reviewed) for r in filled if r.ledger_id != "stmt:000000"} == {
        PM.REVIEWED_UNREVIEWED}


# ------------------------------------------------------------------ c/d/e：多证明两条路径
#
# 2026-11-11 缺陷（只读审计实测）：同一命题的两份证明都已签、经 B 收录之后，
# `statements.bits.reviewed_by_proof` 只有 `{1: True}` —— G 的映射表把第 2 条路径
# 的 V 判词读成 `未通过`，而 V 根本没判过它（实际是"没读到"）。下面三条从映射表
# 的写侧（`fill_ledger_cells`）现读，不手填 reviewed 那一格。
P1 = "1. 取 G 的一个 Sylow p-子群 P。\n2. |P| = p^a > 1 ⇒ 取 1 ≠ x ∈ P。"
P2 = "1. 对 |G| 归纳：取中心元 z。\n2. 每个共轭类大小被 p 整除或与 p 互素。"
P2_EDITED = "1. 对 |G| 归纳（改过的版本）。\n2. 计数给出 p 阶元。"
SHA1 = PM.V._sign_sha(P1)
SHA2 = PM.V._sign_sha(P2)
SHA2_EDITED = PM.V._sign_sha(P2_EDITED)


def _two_path_row(*, per: dict, sha_by: dict, proof2: str = P2,
                  reviewed_by: dict | None = None) -> dict:
    """一条有两条证明路径的 statements 行（#p1 = canonical，`proofs` 里是 #p2）。"""
    ev: dict = {"reviewed_by_proof": dict(per),
                "reviewed_sha_by_proof": dict(sha_by)}
    if reviewed_by is not None:
        ev["reviewed_by"] = dict(reviewed_by)
    return {"stmt_id": "000001", "kind": "theorem", "proof_text": P1,
            "bits": {"evidence": ev},
            "proofs": [{"proof_no": 2, "proof_text": str(proof2)}]}


def _two_path_rows() -> list[PM.Row]:
    """G 的映射表两行：同一命题的两条路径各占一行（`#p1` 与 `#p2`）。"""
    return [PM.Row(kind="theorem", label="thm:p1", env_no=1, ledger_id="stmt:000001",
                   proof_no=1, file="main.tex"),
            PM.Row(kind="theorem", label="thm:p2", env_no=2,
                   ledger_id="stmt:000001#p2", proof_no=2, file="main.tex")]


def _two_path_ws(tmp_path: pathlib.Path, row: dict) -> pathlib.Path:
    root = pathlib.Path(tmp_path / "ws")
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "statements.json").write_text(json.dumps({
        "rows": [row],
    }, ensure_ascii=False), encoding="utf-8")
    _review_ledger(root, "000001",
                   json.dumps({"statement_id": "000001", "verification_id": "v-000001",
                               "verdict": "成立"}, ensure_ascii=False) + "\n")
    return root


def _filled_cells(tmp_path: pathlib.Path, row: dict) -> list[str]:
    root = _two_path_ws(tmp_path, row)
    return [str(r.reviewed) for r in PM.fill_ledger_cells(root, _two_path_rows())]


def test_c_two_signed_paths_are_both_signed_in_the_mapping(tmp_path):
    """c) 两条路径都签 ⇒ 映射表两行都是「已签」；#2 的判决原话是「成立」。

    改前红：逐条表只有 `{1: True}` ⇒ #2 那一行印成「未通过」（一个假结论：
    V 没判过它）。#1 的判决原话读不到（`reviewed_by` 只有最近那一签 = #2），
    如实写「判决：未读到」—— 那是原话那一格读不到，不是"没签"。
    """
    row = _two_path_row(
        per={"1": True, "2": True},
        sha_by={"1": SHA1, "2": SHA2},
        reviewed_by={"verifier": "V", "verdict": "成立", "proof_no": 2,
                     "proof_sha256": SHA2})
    cells = _filled_cells(tmp_path, row)
    assert cells[0].startswith(PM.REVIEWED_SIGNED), cells
    assert cells[1] == PM.REVIEWED_SIGNED_TEMPLATE.format(verdict="成立"), cells
    assert cells[0] == PM.REVIEWED_SIGNED_TEMPLATE.format(
        verdict=PM.LEDGER_CELL_UNREADABLE), cells
    for cell in cells:
        assert cell != PM.REVIEWED_NOT_PASSED, cells
        assert cell != PM.LEDGER_CELL_UNREADABLE, cells


def test_c3_a_sign_recorded_under_another_number_reads_as_unread(tmp_path):
    """c3) 正文 sha 记在别的号上 ⇒ `未读到`，不是 `未通过`（业主 2026-11-11）。

    这是 B 收录第 2 份时按 canonical 号落老账的形状：签盖的是 #p2 的正文，而
    `reviewed_sha_by_proof` 把它记在 1 号上。逐条表里"没有 #2 这一号"不等于
    "V 判过 #2、没通过" —— 表上必须落 `未读到`。
    """
    row = _two_path_row(
        per={"1": True}, sha_by={"1": SHA2},
        reviewed_by={"verifier": "V", "verdict": "成立", "proof_no": 1,
                     "proof_sha256": SHA2})
    cells = _filled_cells(tmp_path, row)
    assert cells == [PM.LEDGER_CELL_UNREADABLE, PM.LEDGER_CELL_UNREADABLE], cells


def test_d2_an_unsigned_second_path_is_not_passed(tmp_path):
    """d2) 第 2 条没签 ⇒ `未通过`（不是 `未读到`）。

    反向控制：`未读到` 不许拿来盖"审过没签"这一档；只有"这一份的签记在别处 /
    签的是旧版"才是读不到。
    """
    row = _two_path_row(
        per={"1": True}, sha_by={"1": SHA1},
        reviewed_by={"verifier": "V", "verdict": "成立", "proof_no": 1,
                     "proof_sha256": SHA1})
    cells = _filled_cells(tmp_path, row)
    assert cells[0] == PM.REVIEWED_SIGNED_TEMPLATE.format(verdict="成立"), cells
    assert cells[1] == PM.REVIEWED_NOT_PASSED, cells
    assert cells[1] != PM.LEDGER_CELL_UNREADABLE, cells


def test_e2_a_sign_over_an_older_body_is_unread_and_distinguishable(tmp_path):
    """e2) 第 2 条签过但正文已改（签 sha ≠ 现 sha）⇒ `未读到`，且与 d2 可分辨。

    签盖的是旧版（`reviewed_sha_by_proof[2]` 是旧正文的 sha），现行正文没有被读过
    ⇒ 不许印「已签」，也不许印「未通过」（那会说"这一版被判过且有毛病"）。
    三态钉法：这一档落 `未读到`；d2（真没签）落 `未通过` —— 两档词不同。
    """
    row = _two_path_row(
        per={"1": True, "2": True}, sha_by={"1": SHA1, "2": SHA2},
        proof2=P2_EDITED,
        reviewed_by={"verifier": "V", "verdict": "成立", "proof_no": 2,
                     "proof_sha256": SHA2})
    cells = _filled_cells(tmp_path, row)
    assert SHA2_EDITED != SHA2, "夹具没改正文 ⇒ 这条判据量不到 stale"
    # #1 已签（判决原话那一格是 #2 的签 ⇒ 如实写"未读到"）；#2 签的是旧版 ⇒ 未读到。
    assert cells[0].startswith(PM.REVIEWED_SIGNED), cells
    assert cells[0] != PM.REVIEWED_NOT_PASSED, cells
    assert cells[1] == PM.LEDGER_CELL_UNREADABLE, cells
    assert cells[1] != PM.REVIEWED_NOT_PASSED, cells
    # 与 d2 同框比较：没签是「未通过」，签的是旧版是「未读到」。
    unsigned_row = _two_path_row(
        per={"1": True}, sha_by={"1": SHA1},
        reviewed_by={"verifier": "V", "verdict": "成立", "proof_no": 1,
                     "proof_sha256": SHA1})
    assert PM.reviewed_cell(unsigned_row, 2,
                            review_ledger=PM.REVIEW_LEDGER_PRESENT
                            ) == PM.REVIEWED_NOT_PASSED
    assert cells[1] != PM.reviewed_cell(unsigned_row, 2,
                                        review_ledger=PM.REVIEW_LEDGER_PRESENT)
