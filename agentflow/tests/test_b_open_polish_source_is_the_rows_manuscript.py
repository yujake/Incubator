# -*- coding: utf-8 -*-
"""判据：B 开优化稿的取源只认行上 `manuscripts[path_group]` / `manuscript_id`。

## 缺陷（2026-11-14 真机 lp-ball）

42 条里有稿的 6 条，开优化稿时 4 份复制错源：

| 命题 | 行上 `manuscripts["1"]`（它自己的稿） | 改前抓到的源 |
|---|---|---|
| 000032（Ball，conjecture） | `reports/b-proof-000000.md` | `reports/f-proof-000000.md`（000040 的稿） |
| 000034（Meyer–Pajor，conjecture） | `reports/b-proof-000001.md` | `reports/f-proof-000001.md`（000041 的稿） |
| 000035（Oleszkiewicz，conjecture） | `reports/b-proof-000002.md` | `reports/f-proof-000002.md`（别族同号的稿） |
| 000036（坐标超平面，conjecture） | `reports/b-proof-000003.md` | 够不着，退成「行上 103 字引文」 |

根因：`_polish_source` 的第 ③ 条按行上 `manuscript_id` 拼 F 族规范名、再拿颁发表
里那一签当"这一行的已签原稿"——它核的是"那份稿自己签没签"，从来不核"那份稿的正文
是不是这一行的"。稿号只在号段内唯一（`f-proof-000000` 与 `b-proof-000000` 是两个号），
于是两条不同命题的稿被指成同一份。

## 判据（红 → 绿）

| # | 判据 | 改前 |
|---|---|---|
| a | 六条各自拿到行上 `manuscripts["1"]` 那一份，正文 sha 与行上正文一致 | 4 条错 |
| b | 000032 与 000040 的源 sha 不同；000034 与 000041 的源 sha 不同 | 两对相同 |
| c | 000036 命中 `reports/b-proof-000003.md` | 退成行上正文 |
| d | 000035 不抓 `reports/f-proof-000002.md`（别族同号、且它已签） | 抓了 |
| e | 端到端：两份副本的 `## 证明` 正文 sha 各自等于自己那一行、彼此不同 | 相同 |

## 反真空

把取源那一段打桩回"按 `kind` 猜族、不核正文"（`_row_source_rel` 的唯一落点）⇒
a/b/c/d 当场红：000032/000034 重新指向 F 族同号稿、000036 够不着自己的稿。

全部 tmp 工作区，不读写 `projects/`。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import manuscriptids as MID
from agentflow import proofregistry as PR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB, open_polish_copy as OPC
from agentflow.store import Store

import _credential_fixture as CF
import conftest

#: 六条有稿的命题：号 → (kind, 行上 `manuscripts["1"]`, 它自己的正文)
CASES = {
    "000032": ("conjecture", "reports/b-proof-000000.md", "Ball 定理的逐字转述（这一条自己的正文）。"),
    "000034": ("conjecture", "reports/b-proof-000001.md", "Meyer–Pajor 单调性的逐字转述（这一条自己的正文）。"),
    "000035": ("conjecture", "reports/b-proof-000002.md", "Oleszkiewicz 的逐字转述（这一条自己的正文）。"),
    "000036": ("conjecture", "reports/b-proof-000003.md", "坐标超平面最小/最大截面的逐字转述（这一条自己的正文）。"),
    "000040": ("theorem", "reports/f-proof-000000.md", "ℓ_p³ 三族截面积公式的自家证明正文（较长，与 000032 不同）。"),
    "000041": ("theorem", "reports/f-proof-000001.md", "ℓ_p³ 三族面积比较与单调性的自家证明正文（较长，与 000034 不同）。"),
}

#: 别族同号的稿：`f-proof-000002` 是 000035 的陷阱（它已签，但正文不是 000035 的）。
TRAP = "reports/f-proof-000002.md"
TRAP_BODY = "这是别的一条命题（被否的第三稿）的正文，不是 000035 的转述。"


def _write(root: pathlib.Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# 手稿：{pathlib.PurePosixPath(rel).name}\n\n## 命题\n\n夹具命题。\n\n"
        f"## 证明\n\n{body}\n", encoding="utf-8")


def _fixture(tmp_path: pathlib.Path) -> tuple[Store, _OpenPolishCopy]:
    """按真机那 6 行的形状铺一个工作区（逐路径记录 + 同号不同族 + 一份已签的陷阱稿）。"""
    st = Store(tmp_path / "ws")
    st.init()
    root = pathlib.Path(st.root)
    for sid, (kind, rel, body) in CASES.items():
        _write(root, rel, body)
        conftest.seed_statement_row(
            st, stmt_id=sid, statement_full=f"夹具命题 {sid}。", kind=kind,
            proof_text=body, manuscript_id=VS.manuscript_id_of(rel),
            manuscripts={"1": rel}, proof_no=1)
    _write(root, TRAP, TRAP_BODY)
    # 两条自家 F 稿已签；别族同号的陷阱稿也签（改前第 ③ 条会拿"它签过"当原稿理由）
    for body, rel in ((CASES["000040"][2], "reports/f-proof-000000.md"),
                      (CASES["000041"][2], "reports/f-proof-000001.md"),
                      (TRAP_BODY, TRAP)):
        CF.issue_credential(st.root, proof_text=body, statement_id="",
                            manuscript=rel, artifact_path=rel)
    b = OPC._OpenPolishCopy()
    b.store = st
    return st, b


def _resolved(b: _OpenPolishCopy, st: Store) -> dict[str, dict]:
    """取源读数 + 把源正文的 `## 证明` sha 补成 `source_body_sha`（`_polish_source` 只给 text）。"""
    out: dict[str, dict] = {}
    for sid in CASES:
        one = dict(b._polish_source(str(st.root), sid, ""))
        text = str(one.get("text") or "")
        one["source_body_sha"] = (PR.proof_sha(VS.manuscript_proof_body(text))
                                  if text else "")
        out[sid] = one
    return out


# ------------------------------------------------------------------ a/b/c/d

def test_a_each_statement_takes_its_own_manuscript(tmp_path) -> None:
    """a：六条都拿到行上 `manuscripts["1"]` 那一份，正文 sha 与行上正文一致。"""
    st, b = _fixture(tmp_path)
    got = _resolved(b, st)
    for sid, (_kind, rel, body) in CASES.items():
        one = got[sid]
        assert one.get("found") is True, (sid, one)
        assert one.get("path") == rel, (sid, one)
        assert one.get("matched_by") == "statement_manuscript_id", (sid, one)
        assert one.get("source_body_sha") == PR.proof_sha(body), (sid, one)
    # 有签的两条仍是 signed；四条文献转述是 unsigned（不等签）
    assert got["000040"]["source_sign"] == got["000041"]["source_sign"] == "signed"
    for sid in ("000032", "000034", "000035", "000036"):
        assert got[sid]["source_sign"] == "unsigned", (sid, got[sid])


def test_b_the_two_same_numbered_pairs_do_not_share_a_source(tmp_path) -> None:
    """b：真机上那两对同号命题，源正文 sha 必须不同。"""
    st, b = _fixture(tmp_path)
    got = _resolved(b, st)
    pairs = (("000032", "000040"), ("000034", "000041"))
    for left, right in pairs:
        assert got[left]["source_body_sha"] != got[right]["source_body_sha"], (left, right, got)
        assert got[left]["path"] != got[right]["path"], (left, right, got)


def test_c_000036_hits_its_own_b_draft(tmp_path) -> None:
    """c：000036 的稿是 `b-proof-000003.md`（F 族同号那份不存在，改前够不着）。"""
    st, b = _fixture(tmp_path)
    got = _resolved(b, st)["000036"]
    assert got.get("path") == "reports/b-proof-000003.md", got
    assert got.get("source_kind") == "unsigned_manuscript", got


def test_d_000035_does_not_grab_the_other_family(tmp_path) -> None:
    """d：000035 不抓 `f-proof-000002.md`（别族同号、且它已签）—— 只认行上那一份。"""
    st, b = _fixture(tmp_path)
    got = _resolved(b, st)["000035"]
    assert got.get("path") == "reports/b-proof-000002.md", got
    assert got.get("path") != TRAP, got
    assert got.get("source_body_sha") == PR.proof_sha(CASES["000035"][2]), got


# ------------------------------------------------------------------ e 端到端

def _b(st: Store) -> AgentB:
    return conftest.b_form_gate_ok(AgentB(st, extractor=None, extract_text=None))


def test_e_the_copies_are_built_from_each_rows_own_body(tmp_path) -> None:
    """e：端到端开两份副本 —— 每份正文 sha 等于自己那一行，彼此不同。"""
    st, _b0 = _fixture(tmp_path)
    body_a = CASES["000032"][2]
    body_b = CASES["000040"][2]
    first = _b(st).open_polish_copy(statement_id="000032")
    second = _b(st).open_polish_copy(statement_id="000040")
    assert first.get("ok") is True, first
    assert second.get("ok") is True, second
    assert first["copy_body_sha"] == PR.proof_sha(body_a), first
    assert second["copy_body_sha"] == PR.proof_sha(body_b), second
    assert first["copy_body_sha"] != second["copy_body_sha"], (first, second)
    copy_a = (pathlib.Path(st.root) / first["path"]).read_text(encoding="utf-8")
    copy_b = (pathlib.Path(st.root) / second["path"]).read_text(encoding="utf-8")
    assert body_a in copy_a and body_b not in copy_a, copy_a
    assert body_b in copy_b and body_a not in copy_b, copy_b


# ------------------------------------------------------------------ 反真空

def test_f_anti_vacuum_guessing_the_family_by_kind_turns_it_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把取源打桩回「按 kind 猜族、不核正文」⇒ a/b/c/d 的读数当场变红。

    打桩点就是 `_row_source_rel`：它是取源的唯一落点（`_polish_source` 第 ③ 条与
    `_polish_source_unsigned` 都从这里拿 rel）。桩函数复刻改前那两句：
    `family = "b-proof" if kind == "concept" else "f-proof"` + `canonical_rel(mid, family)`，
    不读 `manuscripts`、也不核正文。
    """
    st, b = _fixture(tmp_path)

    def _old_kind_guess(root, row):
        mid = str(row.get("manuscript_id") or "").strip()
        family = "b-proof" if str(row.get("kind") or "") == "concept" else "f-proof"
        rel = MID.canonical_rel(mid, family=family) if mid else ""
        found = bool(rel and (pathlib.Path(str(root)) / rel).is_file())
        return {"found": found, "rel": rel if found else "", "evidence": "",
                "why": "" if found else "反真空桩：按 kind 猜族"}

    monkeypatch.setattr(OPC._OpenPolishCopy, "_row_source_rel", staticmethod(_old_kind_guess))
    got = _resolved(b, st)

    # b 红：两对重新共用同一个源
    assert got["000032"]["path"] == "reports/f-proof-000000.md", got["000032"]
    assert got["000034"]["path"] == "reports/f-proof-000001.md", got["000034"]
    assert got["000032"]["source_body_sha"] == got["000040"]["source_body_sha"]
    assert got["000034"]["source_body_sha"] == got["000041"]["source_body_sha"]
    # c/d 红：000036 够不着自己的稿、000035 抓到别族的陷阱稿
    assert got["000036"]["path"] == "", got["000036"]
    assert got["000035"]["path"] == TRAP, got["000035"]
