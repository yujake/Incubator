# -*- coding: utf-8 -*-
"""判据：每一族手稿各有自己的号段（业主 2026-11-11 裁定 ① / ③）。

## 业主裁定（逐字）

```text
「b侧稿号和命题号耦合是错的，这犯了原先F稿号不独立一样的问题，
  B侧稿和F侧稿的维护方法一致。你也再盯一下E侧稿的形状」
```

改前三个族的稿名都不是自己的号：`reports/b-proof-<命题号>.md`、
`reports/e-proof-<实验号>.md`、`reports/e-num-<实验号>.md`。F 在 2026-11-10 已经
先走了一步（`counters.manuscript` 一条独立号段）；这一份钉的是"另外三族跟上来"。

## 判据

| # | 判据 | 钉住的东西 |
|---|---|---|
| a | 三族各发两个号 ⇒ 各自自增、互不干扰、不覆盖既有文件；每族一条计数器 | `manuscriptids.FAMILY_COUNTERS` 是唯一号源 |
| b | 新写路径是 `reports/b-proof-<B稿号>.md` / `e-proof-<E稿号>.md` / `e-num-<E稿号>.md`，且同一命题 / 同一实验重落不新开第二份 | 写侧只按本族稿号拼名 |
| c | 老盘名（`b-proof-<命题号>` / `e-proof-<实验号>` / `e-num-<实验号>`）仍能分类、能读、能认签 | 只读兼容，不为新路径改老读数 |
| d | 反真空：把某族改回「用命题号 / 实验号」⇒ 本文件的判据红 | a / b 的绿来自号源，不是断言太松 |

全部 tmp 工作区，不读写 `projects/`（真机工作区只读），不跑全量。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentflow import bmanuscript as BM
from agentflow import exhaustionreport as ER
from agentflow import manuscriptfamily as MF
from agentflow import manuscriptids as MID
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.store import Store

import conftest

#: 三族（B / E 证明 / E 数值）—— F 那一族另有判据
#: `test_f_manuscript_ids_are_its_own_source.py`，这里只钉"另外三族跟上来"。
B_FAMILY = "b-proof"
EP_FAMILY = "e-proof"
EN_FAMILY = "e-num"


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _counters(st: Store) -> dict:
    path = pathlib.Path(st.root) / "data" / "counters.json"
    return dict((json.loads(path.read_text(encoding="utf-8")) or {}).get("counters") or {})


def _b(st: Store) -> AgentB:
    return AgentB(st, extractor=None, extract_text=None)


def _experiment_facts(**kw) -> dict:
    facts = {
        "experiment_id": "000000", "claim": "对任意 n，f(n) ≥ 0。",
        "claim_key": "夹具：数值命题", "script_path": "code/probe.py",
        "script_sha256": "0" * 64, "design": "按定义枚举",
        "enumeration": "穷举了 n ≤ 100", "search_space": {"n": 100},
        "result": "supports", "evidence_kind": "proof",
    }
    facts.update(kw)
    return facts


def _mid_of(rel: str) -> str:
    return str(VS.manuscript_id_of(rel) or "")


# ------------------------------------------------------------------ a 每族一条计数器

def test_a_each_family_issues_its_own_two_numbers(tmp_path) -> None:
    """a：三族各发两个号 ⇒ 各自 `000000` / `000001`，互不干扰，四条计数器各推一格。"""
    st = _ws(tmp_path)
    got: dict[str, list[str]] = {B_FAMILY: [], EP_FAMILY: [], EN_FAMILY: []}
    # 交错发号：若三族共用一条计数器（或谁的号被谁推着走），这里的读数立刻不同。
    for _ in range(2):
        for fam in (B_FAMILY, EP_FAMILY, EN_FAMILY):
            got[fam].append(MID.next_manuscript_id(st, family=fam))
    assert got == {B_FAMILY: ["000000", "000001"],
                   EP_FAMILY: ["000000", "000001"],
                   EN_FAMILY: ["000000", "000001"]}, got
    counters = _counters(st)
    assert counters.get(MID.FAMILY_COUNTERS[B_FAMILY]) == 2, counters
    assert counters.get(MID.FAMILY_COUNTERS[EP_FAMILY]) == 2, counters
    assert counters.get(MID.FAMILY_COUNTERS[EN_FAMILY]) == 2, counters
    # F 那一格一个字节都没动（三族发号不碰 `manuscript`）
    assert int(counters.get(MID.COUNTER_KEY, 0)) == 0, counters


def test_a_occupancy_is_per_family_and_never_overwrites(tmp_path) -> None:
    """a（占用）：某一族已占的号只推它自己那一族；既有文件逐字不变。"""
    st = _ws(tmp_path)
    reports = pathlib.Path(st.root) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "b-proof-000000.md").write_text("别人的 B 稿", encoding="utf-8")
    assert MID.next_manuscript_id(st, family=B_FAMILY) == "000001"
    assert (reports / "b-proof-000000.md").read_text(encoding="utf-8") == "别人的 B 稿"
    # 另外两族照旧从 000000 起（占用面是按族的）
    assert MID.next_manuscript_id(st, family=EP_FAMILY) == "000000"
    assert MID.next_manuscript_id(st, family=EN_FAMILY) == "000000"


def test_a_unknown_family_is_a_controlled_refusal(tmp_path) -> None:
    """a（未知族）：没有号段就不发号 —— 受控抛，不猜一条计数器。"""
    st = _ws(tmp_path)
    with pytest.raises(MID.ManuscriptIdError):
        MID.next_manuscript_id(st, family="x-proof")


# ------------------------------------------------------------------ b 新写路径

def test_b_the_b_manuscript_is_named_by_the_b_counter(tmp_path) -> None:
    """b：B 落稿的稿号来自 B 的计数器，命题号不参与命名；重落同一命题不新开一份。"""
    st = _ws(tmp_path)
    conftest.seed_statement_row(st, stmt_id="000005", statement_full="命题甲。",
                                kind="conjecture")
    conftest.seed_statement_row(st, stmt_id="000006", statement_full="命题乙。",
                                kind="conjecture")
    b = _b(st)
    first = b.land_manuscript(statement_id="000005", proof_text="甲的证明。")
    assert first.get("ok") is True, first
    rel_a = str(first.get("path") or "")
    mid_a = str(first.get("manuscript_id") or "")
    assert mid_a == "000000", first
    assert rel_a == MID.canonical_rel(mid_a, family=B_FAMILY), first
    assert "000005" not in rel_a, first
    second = b.land_manuscript(statement_id="000006", proof_text="乙的证明。")
    assert second.get("ok") is True, second
    rel_b = str(second.get("path") or "")
    assert str(second.get("manuscript_id") or "") == "000001", second
    assert rel_b == MID.canonical_rel("000001", family=B_FAMILY), second
    # 稿与命题的对应关系在 `statements` 行的逐路径记录（`manuscripts`），不在稿头：
    # 业主 2026-11-13「稿里没有命题号，任何稿里都没有命题号」⇒ 稿头那一行不再写。
    from agentflow import bmanuscript as _BM_READ

    text = (pathlib.Path(st.root) / rel_a).read_text(encoding="utf-8")
    assert "- 命题号：" not in text, text.split("\n")[:6]
    found = _BM_READ.manuscript_id_for_statement(st.root, "000005", store=st)
    assert found.get("found") is True and found.get("path") == rel_a, found
    # 同一命题再落一版 ⇒ 就地改它自己那份，不新开第二份
    again = b.land_manuscript(statement_id="000005", proof_text="甲的证明（第二版）。")
    assert again.get("ok") is True, again
    assert str(again.get("path") or "") == rel_a, again
    names = sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("b-proof-*.md"))
    assert names == [rel_a.rsplit("/", 1)[-1], rel_b.rsplit("/", 1)[-1]], names
    # 一个稿号一份稿（业主 2026-11-11）：「不再细分 version 几，应该在改正文时 edit 它」
    # ⇒ 就算调用方要"第 2 份"，文件名也不许长出一条 `-p2`。
    again2 = b.land_manuscript(statement_id="000005", proof_text="甲的证明（第三版）。",
                               proof_no=2)
    assert again2.get("ok") is True, again2
    assert str(again2.get("path") or "") == rel_a, again2
    assert re.search(r"-p\d+\.md$", rel_a) is None, again2


def test_b_the_e_families_are_named_by_their_own_counters(tmp_path) -> None:
    """b：E 的两族各按自己的计数器命名（两条号段互不干扰），重落同一实验不新开一份。"""
    st = _ws(tmp_path)
    p0 = ER.land_manuscript(st.root, **_experiment_facts(experiment_id="000000"))
    assert p0.get("ok") is True, p0
    assert p0.get("path") == MID.canonical_rel("000000", family=EP_FAMILY), p0
    p1 = ER.land_manuscript(st.root, **_experiment_facts(experiment_id="000001",
                                                         claim="另一条命题。"))
    assert p1.get("ok") is True, p1
    assert p1.get("path") == MID.canonical_rel("000001", family=EP_FAMILY), p1
    # e-num 从自己的 000000 起（不接着 e-proof 的号走）
    n0 = ER.land_numeric_manuscript(st.root, **_experiment_facts(experiment_id="000002",
                                                                 claim="普通数值命题。"))
    assert n0.get("ok") is True, n0
    assert n0.get("path") == MID.canonical_rel("000000", family=EN_FAMILY), n0
    n1 = ER.land_numeric_manuscript(st.root, **_experiment_facts(experiment_id="000003",
                                                                 claim="第二条数值命题。"))
    assert n1.get("path") == MID.canonical_rel("000001", family=EN_FAMILY), n1
    # 一个稿号一份稿：E 两族的新路径都不带 `-pN`
    for rel in (p0["path"], p1["path"], n0["path"], n1["path"]):
        assert re.search(r"-p\d+\.md$", rel) is None, rel
    # 稿与实验的对应关系在稿头 `- 实验号：` 那一行
    for rel, eid in ((p0["path"], "000000"), (n0["path"], "000002")):
        text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
        assert f"- 实验号：exp:{eid}" in text, text.split("\n")[:5]
        assert ER.experiment_id_of_manuscript(st.root, rel) == eid, rel
    # 同一实验重落 ⇒ 就地改它自己那份
    again = ER.land_manuscript(st.root, **_experiment_facts(experiment_id="000000"))
    assert again.get("path") == p0["path"], again
    names = sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("e-proof-*.md"))
    assert names == ["e-proof-000000.md", "e-proof-000001.md"], names


# ------------------------------------------------------------------ c 老盘只读兼容

def test_c_old_disk_names_still_classify_and_recognize_signs(tmp_path) -> None:
    """c：老盘名（按命题号 / 实验号命名的那一批）仍能分类、能读、能认签。"""
    st = _ws(tmp_path)
    reports = pathlib.Path(st.root) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    # 老盘 `b-proof-<命题号>`：一个真实的六位号，读侧不许因为"号不是 B 的"就拒它
    old_b = "reports/b-proof-000041.md"
    (reports / "b-proof-000041.md").write_text(
        "# B 的证明手稿：老盘\n\n- 命题号：stmt:000041\n\n"
        "## 命题\n\n老盘命题。\n\n## 证明\n\n老盘的证明。\n\n"
        "## 依赖\n\n| 引用（E 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n",
        encoding="utf-8")
    assert MF.classify_manuscript(old_b)["tier"] == MF.TIER_FAMILY, MF.classify_manuscript(old_b)
    assert MF.classify_manuscript(old_b)["family"] == B_FAMILY
    assert MF.sign_carrier(old_b)["ok"] is True, MF.sign_carrier(old_b)
    assert _mid_of(old_b) == "000041", old_b
    read = BM.read_rewrite(st.root, old_b)
    assert read.get("ok") is True and "老盘的证明" in str(read.get("text") or ""), read

    for old, fam in (("reports/e-proof-000007.md", EP_FAMILY),
                     ("reports/e-num-000009.md", EN_FAMILY)):
        reading = MF.classify_manuscript(old)
        assert reading["tier"] == MF.TIER_FAMILY, (old, reading)
        assert reading["family"] == fam, (old, reading)
        assert _mid_of(old) in ("000007", "000009"), old
    # e-num 不走 V 的签（绿色通道）—— 老盘读数不变
    assert MF.sign_carrier("reports/e-num-000009.md")["ok"] is False


# ------------------------------------------------------------------ d 反真空

def _named_by_own_counter(rel: str, *, family: str, before: int) -> bool:
    """这个名字里的号是不是"发它之前那一族计数器指着的号"。

    这是本文件 a / b 两条判据的共同谓词：名字里的号必须来自该族的计数器。
    换回"用命题号 / 实验号"时它必然为 False（那些号不随计数器走）。
    """
    mid = _mid_of(rel)
    return bool(mid) and int(mid) == int(before) and rel == MID.canonical_rel(
        mid, family=family)


def test_d_naming_the_b_manuscript_with_the_statement_number_turns_it_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d-1 反真空：B 的稿名又用命题号 ⇒ 红。"""
    st = _ws(tmp_path)
    conftest.seed_statement_row(st, stmt_id="000005", statement_full="命题甲。",
                                kind="conjecture")
    b = _b(st)
    before = MID.peek_manuscript_counter(st, family=B_FAMILY)
    ok = b.land_manuscript(statement_id="000005", proof_text="甲的证明。")
    assert ok.get("ok") is True, ok
    assert _named_by_own_counter(str(ok["path"]), family=B_FAMILY, before=before) is True, ok

    # 旧口径的重放：号源又按命题号发
    real = MID.next_manuscript_id

    def _coupled(root, *, family=MID.FAMILY_F):
        if str(family) == B_FAMILY:
            return "000005"      # 命题号
        return real(root, family=family)

    monkeypatch.setattr(MID, "next_manuscript_id", _coupled)
    conftest.seed_statement_row(st, stmt_id="000006", statement_full="命题乙。",
                                kind="conjecture")
    regressed = b.land_manuscript(statement_id="000006", proof_text="乙的证明。")
    assert regressed.get("ok") is True, regressed
    before_b = 0
    assert _named_by_own_counter(str(regressed["path"]), family=B_FAMILY,
                                 before=before_b) is False, regressed


def test_d_naming_the_e_manuscript_with_the_experiment_number_turns_it_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d-2 反真空：E 的稿名又用实验号 ⇒ 红。"""
    st = _ws(tmp_path)
    before = MID.peek_manuscript_counter(st, family=EP_FAMILY)
    ok = ER.land_manuscript(st.root, **_experiment_facts(experiment_id="000004"))
    assert ok.get("ok") is True, ok
    assert _named_by_own_counter(str(ok["path"]), family=EP_FAMILY, before=before) is True, ok

    real = MID.next_manuscript_id

    def _coupled(root, *, family=MID.FAMILY_F):
        if str(family) == EP_FAMILY:
            return "000004"      # 实验号
        return real(root, family=family)

    monkeypatch.setattr(MID, "next_manuscript_id", _coupled)
    regressed = ER.land_manuscript(st.root, **_experiment_facts(experiment_id="000009",
                                                                claim="另一条。"))
    assert regressed.get("ok") is True, regressed
    assert _named_by_own_counter(str(regressed["path"]), family=EP_FAMILY,
                                 before=0) is False, regressed
