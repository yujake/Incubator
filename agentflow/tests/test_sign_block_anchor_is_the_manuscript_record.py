# -*- coding: utf-8 -*-
"""SB 路：签块的归属锚换成「手稿号 + 正文 sha + 行上的稿记录」（业主 2026-11-13）。

## 口径（逐字）

```text
稿里没有命题号，任何稿里都没有命题号。
```

`a04de92c` 删掉了稿头那一行之后，签块第 8 格 `命题号` 是「稿 → 命题行」最后一条
durable 线索 —— 而这一格也是“稿里没有命题号”没清干净的那一处。这一笔把它退役：

- 写侧：:func:`vsigns.write_manuscript_sign` / `stamp_manuscript_sign` 新写的块
  只有 8 格（`手稿号` 仍在第 9 个位置），不再写 `命题号`；
- 读侧：老盘上的 8 格块（无 `手稿号`）与 `命题号=未在册` 一个字节不迁移，
  `signed` / `stale` / `unmatched` / `no_statement` 四态照旧读得出；
- 归属锚：签文件里那一格命题号与本行不符时，改问
  :func:`vsigns._manuscript_owns_the_sign` ——「这一行记着的那份稿」
  （`statements.manuscript_id` / `manuscripts` 逐路径记录）+ `手稿号` + 正文 sha。

## 判据（与凭据 ③ 的五条一一对应）

| # | 造什么 | 期望 |
|---|---|---|
| a | 写一块（显式传 `statement_id`） | 块里没有 `命题号=`，有 `手稿号`；读出来 `statement_id=""`、身份 resolved、signed |
| b | 老盘 8 格块 + `命题号=未在册` | 正控：signed / stale / unmatched / no_statement 四态都读得出（不迁移） |
| c | 收录那一笔的签（签文件里的号是“旧号”） | `sign_filing.manuscript_signed=True`；不给稿路径那一档（收工门形状）也 signed，读数里 `credential.anchor.owned=True` |
| d | 反真空：把新锚打桩成“不是本行的稿” | c 的 `manuscript_signed` 必须翻假（证明 c 量的是新锚） |
| e | 反真空：把“老盘八格读法”打桩成不认 | b 的 `signed` 必须翻假（证明 b 量的是那一支） |
| f | 老签（签文件里带 `proof_no`）问成另一个证明号 | 仍 `borrowed`：新锚不覆盖老签的号绑定（2026-11-11 的口径） |

## 不在这里的事

`test_b_addressing_and_the_sign_gate` 的 a / c / d 三条原样保留（c / d 是“签不能借光”
的承重锚点）；本文件不复制它们，d / e 只把同一件事的打桩点钉住。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import verifications as VR
from agentflow import vsigns as VS

import test_b_addressing_and_the_sign_gate as TB

#: 老盘 8 格块（第 9 格 `手稿号` 还没有、第 8 格 `命题号=未在册`）—— 一个字节不迁移的
#: 那一档。`正文sha` 用夹具正文的现算 sha（与 `TB._body_sha()` 同一把尺）。
LEGACY = (f"{VS.SIGN_MARK}已签=true；判词=成立；连续=3/3；正文sha={TB._body_sha()}；"
          "时间=2026-11-02T16:43:01+08:00；签名者=secretary:F；"
          f"台账=verifications/{TB.SID}.jsonl#v-000003；命题号=未在册")


def _with_block(block: str) -> str:
    """夹具正文 + 一行签块（插在 `- 计划：` 之后，与写口同一个位置）。"""
    marker = "- 计划：0009 · 子目标：s1\n"
    return TB.RAW.replace(marker, marker + block + "\n", 1)


# ====================================================================== a 写侧
def test_a_a_new_block_carries_no_statement_number(tmp_path: pathlib.Path) -> None:
    """写一块（显式传 `statement_id`）⇒ 新块不含 `命题号`，归属靠 `手稿号`。"""
    rel = TB.REL
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TB.RAW, encoding="utf-8")
    got = VS.write_manuscript_sign(
        tmp_path, rel, proof_sha=TB._body_sha(), streak=3, need=3, verdict="成立",
        signer="secretary:F", at="2026-11-13T18:00:00+08:00",
        ledger=f"verifications/{TB.SID}.jsonl#v-000003", statement_id=TB.SID)
    assert got["state"] == "written", got
    line = next(ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.strip().startswith(VS.SIGN_MARK))
    assert "命题号=" not in line, line
    assert f"手稿号={TB.SID}" in line, line
    cells = [one for one in line[len(VS.SIGN_MARK):].split("；") if "=" in one]
    assert len(cells) == 8, (len(cells), line)
    reading = VS.manuscript_sign_reading(path.read_text(encoding="utf-8"),
                                        manuscript_path=rel)
    assert reading["found"] is True and reading["signed"] is True, reading
    assert reading["statement_id"] == "", reading
    assert reading["manuscript_id"] == TB.SID, reading
    assert reading["identity_state"] == "resolved", reading
    # 纯渲染那一口同一件事：传了 `statement_id` 也不进块。
    mark = VS.render_manuscript_sign(
        proof_sha=TB._body_sha(), streak=3, need=3, statement_id=TB.SID,
        manuscript_id=TB.SID)
    assert "命题号=" not in mark, mark
    assert f"手稿号={TB.SID}" in mark, mark


# ====================================================================== b 老盘四态
def test_b_the_old_eight_cell_block_still_reads_all_four_states(
        tmp_path: pathlib.Path) -> None:
    """老盘 8 格块 + `命题号=未在册`：signed / stale / unmatched / no_statement 都读得出。"""
    rel = TB.REL
    text = _with_block(LEGACY)
    # ① signed：块与调用方问的正文逐字相符、`legacy` 仍是“当时真的签过”。
    reading = VS.manuscript_sign_reading(text, manuscript_path=rel)
    assert reading["found"] is True and reading["signed"] is True, reading
    assert reading["identity_state"] == "legacy", reading
    assert reading["statement_id"] == "", reading
    standing = VS.manuscript_sign_standing(text, proof_sha=TB._body_sha(),
                                           manuscript_path=rel)
    assert standing["state"] == "signed", standing
    # ② stale：签完改过正文（块盖的是另一版）⇒ stale，不是“没签”。
    stale = VS.manuscript_sign_standing(
        text, proof_sha=VR.text_sha(VS.manuscript_proof_body(TB.RAW) + "改一个字"),
        manuscript_path=rel)
    assert stale["state"] == "stale", stale
    assert stale["identity_state"] == "legacy", stale
    # ③ unmatched：老盘 9 格块（有 `手稿号`、也有第 8 格）搬到号对不上的稿上。
    moved = _with_block(f"{LEGACY}；手稿号=000777")
    moved_read = VS.manuscript_sign_standing(moved, proof_sha=TB._body_sha(),
                                             manuscript_path=rel)
    assert moved_read["identity_state"] == "unmatched", moved_read
    assert moved_read["state"] != "signed", moved_read
    # ④ no_statement：没有命题号（未在册那一档）⇒ 刷块没有台账可锚，两格保持原值。
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    refreshed = VS.refresh_manuscript_sign(
        tmp_path, artifact_sha=TB._body_sha(), statement_id="", proof_no=1,
        manuscript=rel)
    assert refreshed["state"] == "no_statement", refreshed
    assert path.read_text(encoding="utf-8") == text, "no_statement 那一档一个字节都不许写"
    # ⑤ 收录回执那两格（`sign_filing_reading`）：老盘八格块 + 未在册签，照旧读成
    # 「稿上已签、册里还没收录」—— 换锚不许把历史签读成“认不出”。
    st = TB._ws(tmp_path, manuscript=text)
    filing = VS.sign_filing_reading(st.root, manuscript_path=rel,
                                    statement_id=TB.SID, store=st)
    assert filing.get("checked") is True, filing
    assert filing.get("manuscript_signed") is True, filing
    assert filing.get("state") in ("signed_pending_filing", "filed"), filing


# ====================================================================== c 新锚正控
def test_c_the_register_reading_follows_the_manuscript_record(
        tmp_path: pathlib.Path) -> None:
    """收录那一笔的签（签文件里是“旧号”）⇒ 按行上的稿记录认归本行。

    两档都读：收录回执里的两格（给了稿路径）与收工门形状（只给 store + 命题号 +
    正文，不给路径 —— 路径由行上的 `manuscripts` 记录补）。
    """
    st = TB._ws(tmp_path, manuscript=TB._manuscript())
    got = TB._register(st, TB._CountingSeam())
    assert got.get("ok") is True, got
    filing = dict(got.get("sign_filing") or {})
    assert filing.get("manuscript_signed") is True, filing
    assert filing.get("checked") is True, filing
    sid = str(got.get("stmt_id") or "")
    assert sid and sid != TB.SID, (sid, "夹具撞号：登记目标与签里的号相同就量不到换锚")
    reading = VS.sign_reading(st.root, statement_id=sid, proof_text=TB.PROOF,
                              proof_no=1, store=st)
    assert reading.get("state") == "signed", reading
    anchor = dict((reading.get("credential") or {}).get("anchor") or {})
    assert anchor.get("used") is True and anchor.get("owned") is True, anchor
    assert anchor.get("path") == TB.REL, anchor
    assert anchor.get("manuscript_id") == TB.SID, anchor
    # 老盘那一档（签文件里的号与本行相同）不走新锚：`used=False`，`signed` 照旧。
    same = VS.sign_reading(st.root, statement_id=TB.SID, proof_text=TB.PROOF,
                           proof_no=1, store=st)
    assert same.get("state") == "signed", same
    assert dict((same.get("credential") or {}).get("anchor") or {}).get("used") is False, same
    # 收工门 R10 的调用点（`closing.statements_unsigned_reading`）只给 store + 号 + 正文，
    # 不给稿路径 —— 新锚必须在这一档也认得出（否则换锚之后 R10 会把它读成 `borrowed`）。
    from agentflow import closing as CL

    r10 = CL.statements_unsigned_reading(st)
    assert r10.get("checked") is True, r10
    assert all(str(one.get("stmt_id") or "") != sid for one in r10.get("rows") or []), (
        "R10 把这一条读成欠签了 ⇒ 换锚没有接到收工门那一处", r10.get("rows"))
    assert all(str(one.get("class") or "") != "borrowed"
               for one in (r10.get("rows") or []) + (r10.get("pending_filing") or [])), (
        "R10 把这一条读成 borrowed ⇒ 签的归属没有按新锚读出来", r10)
    # 老盘的第三件只有 `manuscript_id` 那一格（`path_group=0` 落稿 / `manuscripts`
    # 还没写）。给了稿路径时，按「行上稿号 == 稿路径现算的稿号」也认得出 —— 这一档
    # 不能因为少了逐路径记录就掉回 borrowed。
    row = next(dict(one) for one in st.rows("statements") if str(one.get("stmt_id")) == sid)
    row.pop("manuscripts", None)
    with st.tx("statements", actor="test", note="fixture: only manuscript_id") as tx:
        tx.upsert("statements", row)
    only_mid = VS.sign_reading(st.root, statement_id=sid, proof_text=TB.PROOF,
                               proof_no=1, manuscript_path=TB.REL, store=st)
    assert only_mid.get("state") == "signed", only_mid
    only_anchor = dict((only_mid.get("credential") or {}).get("anchor") or {})
    assert only_anchor.get("owned") is True, only_anchor


# ====================================================================== d 反真空（新锚）
def test_d_stubbing_the_new_anchor_turns_the_register_reading_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """把新锚打桩成“不是本行的稿”⇒ c 的 `manuscript_signed` 翻假（a 量的是新锚）。"""
    monkeypatch.setattr(
        VS, "_manuscript_owns_the_sign",
        lambda *a, **kw: {"checked": True, "owned": False, "path": "",
                          "manuscript_id": "", "paths": [],
                          "why": "夹具：把新锚打桩成空"})
    st = TB._ws(tmp_path, manuscript=TB._manuscript())
    got = TB._register(st, TB._CountingSeam())
    filing = dict(got.get("sign_filing") or {})
    assert filing.get("manuscript_signed") is not True, (
        "新锚被打桩成空、签却照样认上了 ⇒ test_b_addressing 的 a 没有量到新锚："
        f"{filing}")


# ====================================================================== e 反真空（老盘）
def test_e_stubbing_the_legacy_reading_turns_the_positive_control_red(
        monkeypatch) -> None:
    """把“老盘八格读法”打桩成不认 ⇒ b 的 `signed` 翻假（b 量的是那一支）。"""
    real = VS.manuscript_sign_reading

    def _legacy_is_not_a_sign(text: str, *, manuscript_path: str = "") -> dict:
        got = real(text, manuscript_path=manuscript_path)
        if str(got.get("identity_state") or "") == "legacy":
            return {**got, "signed": False, "identity_state": "unmatched",
                    "identity_why": "夹具：把老盘八格读法打桩成不认"}
        return got

    monkeypatch.setattr(VS, "manuscript_sign_reading", _legacy_is_not_a_sign)
    standing = VS.manuscript_sign_standing(_with_block(LEGACY),
                                           proof_sha=TB._body_sha(),
                                           manuscript_path=TB.REL)
    assert standing["state"] != "signed", (
        "老盘八格读法被打桩成不认、而它仍读成 signed ⇒ b 那条正控没有量到那一支："
        f"{standing}")


# ====================================================================== f 新锚的边界
def test_f_an_old_signs_proof_no_binding_is_not_overridden_by_the_anchor(
        tmp_path: pathlib.Path) -> None:
    """老签文件里带 `proof_no` 而号对不上 ⇒ 仍 `borrowed`（新锚不覆盖号绑定）。

    2026-11-11 的口径：老签（带 `proof_no` 的那些）仍按号比 —— 那是它们唯一可用的归属
    凭据。新锚补的是"号这一半没有 / 对得上、只是命题号不同"那一档；这一条钉住边界，
    免得下一次有人把"手稿对得上"当成可以越过老号绑定的理由。
    """
    st = TB._ws(tmp_path, manuscript=TB._manuscript())
    got = TB._register(st, TB._CountingSeam())
    sid = str(got.get("stmt_id") or "")
    sha = TB._body_sha()
    sign_file = pathlib.Path(st.root) / "out" / "vsigns" / f"{sha}.json"
    doc = json.loads(sign_file.read_text(encoding="utf-8"))
    # 老签的形态：签文件里带 `proof_no`（2026-11-11 之前发的那些）。
    doc["proof_no"] = 1
    sign_file.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1)
                         + "\n", encoding="utf-8")
    # 同一份签、问成第 2 号证明：老口径按号比 ⇒ 借光（不许因为手稿对得上就放行）。
    reading = VS.sign_reading(st.root, statement_id=sid, proof_text=TB.PROOF,
                              proof_no=2, store=st)
    assert reading.get("state") == "borrowed", reading
    anchor = dict((reading.get("credential") or {}).get("anchor") or {})
    assert anchor.get("used") is False, (
        "老签的号对不上时仍去查了新锚 ⇒ 号绑定被新锚绕过去了", anchor)

