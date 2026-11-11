# -*- coding: utf-8 -*-
"""判据：拿签稿的稿号表复用 V 的颁发表，不新建第二份账（业主 2026-11-11 裁定 ②③）。

## 业主裁定（逐字）

```text
② 「稿通过后相当于这个命题证完了，后续只对稿允许有只读权，但由于尚未入台账暂无引用权，
    需要维护拿签稿的稿号表（在一次攻坚中应该是持续追加，后续交稿时一并递交给D）」
③ 「维护拿签稿的稿号表可以和V自动维护的颁发出V签的表进行复用」
```

## 这一份钉什么

| # | 判据 | 钉住的东西 |
|---|---|---|
| a | 签一份 ⇒ 读口按命题号 / 稿号 / 稿路径三个键都读得到（sha / 时刻 / 判词 / 哪份稿） | `vsigns.signed_table` + `vsigns.signed_manuscripts` |
| b | 同一份稿改版后再签 ⇒ 两行都在（旧那行不被抹，正文 sha 不同） | 表的身份是 `artifact_sha`，不是稿号 |
| c | 没签 ⇒ 明确「没有签」，且与「没查成」分得开 | 三态纪律 |
| d1 | 反真空：把逐份签文件挪走、只留派生归档 ⇒ 读口必须说「没有签」，并把归档对不上如实报出来 | 归档是派生，永远不许代替证据 |
| d2 | 反真空：把表按稿号折平（一份稿只留一行）⇒ b 红 | b 的绿来自"按 sha 分行"，不是断言太松 |

全部 tmp 工作区，不读写 `projects/`（真机工作区只读），不跑全量。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import vsigns as VS
from agentflow.store import Store

import _credential_fixture as CF

AT = CF.AT
AT2 = "2026-11-02T11:00:00+08:00"
SID = "000001"
MID = "000000"
REL = "reports/f-proof-000000.md"
BODY_1 = "第一版正文：由定义直接得到。"
BODY_2 = "第二版正文：改用有限覆盖。"


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    reports = pathlib.Path(st.root) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "f-proof-000000.md").write_text("# F 的证明手稿：夹具\n", encoding="utf-8")
    return st


def _sign(st: Store, *, body: str, at: str = AT) -> dict:
    return CF.issue_credential(st.root, proof_text=body, statement_id=SID,
                               manuscript=REL, artifact_path=REL, at=at)


# ------------------------------------------------------------------ a 读得到

def test_a_a_signed_manuscript_is_readable_by_each_of_the_three_keys(tmp_path) -> None:
    """a：签一份 ⇒ 命题号 / 稿号 / 稿路径三个键都读得到，且读数含 sha / 时刻 / 判词。"""
    st = _ws(tmp_path)
    assert _sign(st, body=BODY_1).get("written") is True

    table = VS.signed_table(st.root)
    assert table["checked"] is True, table
    assert table["count"] == 1, table
    entry = dict(table["entries"][0])
    assert entry["artifact_path"] == REL, entry
    assert entry["manuscript_id"] == MID, entry
    assert entry["artifact_sha"] == VS._sign_sha(BODY_1), entry
    assert entry["at"] == AT, entry
    assert entry["verdict"] == "成立", entry
    assert entry["statement_id"] == SID, entry
    assert entry["index_listed"] is True, entry

    for kw in ({"statement_id": SID}, {"manuscript_id": MID},
               {"artifact_path": REL}):
        got = VS.signed_manuscripts(st.root, **kw)
        assert got["checked"] is True and got["found"] is True, (kw, got)
        assert got["signed"] is True and got["count"] == 1, (kw, got)
        assert got["latest"]["artifact_sha"] == VS._sign_sha(BODY_1), (kw, got)
        assert got["matched_by"], (kw, got)


# ------------------------------------------------------------------ b 改版后再签

def test_b_a_second_version_adds_a_row_and_keeps_the_old_one(tmp_path) -> None:
    """b：同一份稿（同一个稿号）改正文后再签 ⇒ 两行都在；旧那行不被抹。"""
    st = _ws(tmp_path)
    _sign(st, body=BODY_1, at=AT)
    _sign(st, body=BODY_2, at=AT2)

    table = VS.signed_table(st.root)
    assert table["count"] == 2, table
    assert all(e["manuscript_id"] == MID for e in table["entries"]), table
    shas = [e["artifact_sha"] for e in table["entries"]]
    assert shas == [VS._sign_sha(BODY_1), VS._sign_sha(BODY_2)], shas

    got = VS.signed_manuscripts(st.root, manuscript_id=MID)
    assert got["count"] == 2, got
    assert {e["artifact_sha"] for e in got["entries"]} == {
        VS._sign_sha(BODY_1), VS._sign_sha(BODY_2)}, got
    # `latest` 是 `at` 最新那一行（第二版），不是"最后写进去的那一行"
    assert got["latest"]["artifact_sha"] == VS._sign_sha(BODY_2), got
    assert got["latest"]["at"] == AT2, got


# ------------------------------------------------------------------ c 没签

def test_c_unsigned_is_an_explicit_no(tmp_path) -> None:
    """c：没签 ⇒ `found=False` + `checked=True`，理由里逐字说「没有签」。"""
    st = _ws(tmp_path)
    got = VS.signed_manuscripts(st.root, statement_id="000009")
    assert got["checked"] is True and got["found"] is False, got
    assert got["signed"] is False and got["count"] == 0, got
    assert "没有" in str(got.get("why") or ""), got
    # 空工作区（`out/vsigns/` 都还没出现）也是同一条读数，不是"没查成"
    empty = Store(tmp_path / "empty")
    empty.init()
    table = VS.signed_table(empty.root)
    assert table["checked"] is True and table["count"] == 0, table
    assert "一次签都没发过" in str(table.get("why") or ""), table


# ------------------------------------------------------------------ d 反真空

def test_d1_the_derived_index_cannot_stand_in_for_the_sign_files(tmp_path) -> None:
    """d-1 反真空：逐份签文件没了 ⇒ 读口必须说「没有签」（归档不许代替证据）。

    这一条同时钉住业主 ③ 的边界：「复用颁发表」复用的是证据（逐份签文件），
    派生归档（`issued.json`）只是索引。若读口改成"只读归档"，这里的 `found` 会是
    True —— 那就等于让一份派生文件下结论。
    """
    st = _ws(tmp_path)
    _sign(st, body=BODY_1)
    index = pathlib.Path(st.root) / "out" / "vsigns" / "issued.json"
    assert index.is_file(), "夹具：签完之后派生归档应当在盘上"
    keep = index.read_text(encoding="utf-8")
    VS.rebuild_index(st.root)

    sign_files = [p for p in (pathlib.Path(st.root) / "out" / "vsigns").glob("*.json")
                  if p.name != "issued.json"]
    assert len(sign_files) == 1, sign_files
    for path in sign_files:
        path.unlink()

    got = VS.signed_manuscripts(st.root, statement_id=SID)
    assert got["found"] is False, ("归档还在，但逐份签文件没了 ⇒ 不许读成「签过」", got)
    assert "没有" in str(got.get("why") or ""), got
    table = VS.signed_table(st.root)
    # 归档里那一行成了孤儿：如实报出来，不静默
    assert table["index"]["orphan_in_index"], table
    assert index.read_text(encoding="utf-8") == keep, "夹具不该动归档本身"


def test_d2_flattening_the_table_by_manuscript_id_turns_b_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d-2 反真空：把表按稿号折平（一份稿只留一行）⇒ b 的「两行都在」必须变红。"""
    st = _ws(tmp_path)
    _sign(st, body=BODY_1, at=AT)
    _sign(st, body=BODY_2, at=AT2)
    assert VS.signed_manuscripts(st.root, manuscript_id=MID)["count"] == 2

    real = VS.signed_table

    def _flattened(root):
        table = dict(real(root))
        seen: dict[str, dict] = {}
        for entry in table.get("entries") or []:
            seen[str(entry.get("manuscript_id") or "")] = dict(entry)
        table["entries"] = list(seen.values())
        table["count"] = len(table["entries"])
        return table

    monkeypatch.setattr(VS, "signed_table", _flattened)
    regressed = VS.signed_manuscripts(st.root, manuscript_id=MID)
    assert regressed["count"] == 1, ("折平之后还读到两行？判据没打到这一格", regressed)
    assert {e["artifact_sha"] for e in regressed["entries"]} != {
        VS._sign_sha(BODY_1), VS._sign_sha(BODY_2)}, regressed
