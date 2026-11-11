# -*- coding: utf-8 -*-
"""判据：B 的「证明优化」先开一份优化副本（业主 2026-11-11 裁定 ④）。

## 业主裁定（逐字）

```text
④ 「B侧进入证明优化阶段时，选中一个待优化的命题后系统自动帮其拿到稿件并复制一份
    注册成B号并清除复制版本内的V签」
```

## 这一份钉什么

| # | 判据 | 钉住的东西 |
|---|---|---|
| a | 正控：源已拿签 ⇒ 复制成功、B 稿号来自 B 的号段、复制件里**没有**签块、源稿一个字节没动 | `B.open_polish_copy` 四步走通 |
| b | 反向：源没签 ⇒ 受控拒（`no_signed_manuscript`），不产生任何文件 | 「拿没签的稿来优化」在结构上不可能 |
| c | 反向：B 稿号不乱用（来自 `counters.bmanuscript`，不是源稿号、不是命题号） | 号源唯一 |
| d1 | 反真空：不清签 ⇒ a 红（复制件仍读成已签） | a 的绿来自清签那一步 |
| d2 | 反真空：复制件用源稿号 ⇒ c 红 | c 的绿来自 B 自己的号段 |

## 一句话口径：正文 sha 为什么与源相同

复制件是**逐字复制**（优化还没开始），所以 `## 证明` 那一节的 sha 与源相同 —— 这是
对的，也是"签按正文 sha 认"的自然结果。清签改变的是**整份文件**：文件 sha 变了、
稿上不再有签块、稿号是新的。等 B 真改了正文，正文 sha 才跟着变（那时 V 的签盖的是
新 sha）。本文件把两个 sha 都当读数钉住，不靠"改一个字节"凑出不等式。

全部 tmp 工作区，不读写 `projects/`（真机工作区只读），不跑全量。
"""
from __future__ import annotations

import hashlib
import pathlib

import pytest

from agentflow import manuscriptids as MID
from agentflow import proofregistry as PR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.store import Store

import _credential_fixture as CF
import conftest

SID = "000005"
BODY = "由定义直接得到：任取 x ∈ X，按定义展开即得。"
REL_F = "reports/f-proof-000000.md"
SIGN_LINE = ("- V 签：已签=true；判词=成立；连续=3/3；正文sha={sha}；"
             "时间=2026-11-02T10:00:00+08:00；签名者=V；"
             "台账=verifications/000001.jsonl#v-000003；命题号=stmt:000001；手稿号=000000")

MANUSCRIPT = f"""# F 的证明手稿：夹具命题

- 命题号：stmt:{SID}
{SIGN_LINE.format(sha="__SHA__")}
- 依赖面洗稿：已洗=true；洗的人=secretary:F；补写=无
- 证明号：1

## 命题

夹具命题。

## 证明

{BODY}

## 依赖

| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |
|---|---|---|---|
（这一份证明没有引用任何在册命题 —— 空表就是声明。）
"""


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    reports = pathlib.Path(st.root) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    conftest.seed_statement_row(st, stmt_id=SID, statement_full="夹具命题。",
                                kind="conjecture")
    return st


def _signed_source(st: Store, *, body: str = BODY) -> str:
    """写一份「已拿签」的 F 稿（签块 + 颁发表两份都在），返回它的路径。"""
    sha = PR.proof_sha(body)
    text = MANUSCRIPT.replace("__SHA__", sha).replace(BODY, body)
    (pathlib.Path(st.root) / REL_F).write_text(text, encoding="utf-8")
    CF.issue_credential(st.root, proof_text=body, statement_id=SID,
                        manuscript=REL_F, artifact_path=REL_F)
    return REL_F


def _b(st: Store) -> AgentB:
    return AgentB(st, extractor=None, extract_text=None)


def _files(st: Store) -> list[str]:
    return sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("*.md"))


# ------------------------------------------------------------------ a 正控

def test_a_the_signed_manuscript_is_copied_under_a_new_b_number(tmp_path) -> None:
    """a：源已签 ⇒ 复制成 B 号副本、清掉签块、源稿一个字节不动。"""
    st = _ws(tmp_path)
    src = _signed_source(st)
    src_before = (pathlib.Path(st.root) / src).read_bytes()
    body_sha = PR.proof_sha(BODY)
    before_counter = MID.peek_manuscript_counter(st, family="b-proof")

    got = _b(st).open_polish_copy(statement_id=SID)
    assert got.get("ok") is True, got
    cp = str(got.get("path") or "")
    mid = str(got.get("manuscript_id") or "")

    # ② B 稿号来自 B 的号段（不是源稿号、不是命题号），落点就是那个号的规范名
    assert mid == f"{before_counter:06d}", got
    assert cp == MID.canonical_rel(mid, family="b-proof"), got
    assert cp != f"reports/b-proof-{SID}.md" or mid == SID, got
    assert MID.peek_manuscript_counter(st, family="b-proof") == int(mid) + 1, got
    # 一份对一份（2026-11-11：不再细分 version 几）
    assert "-p" not in pathlib.PurePosixPath(cp).name.replace("-proof", ""), cp

    copy_text = (pathlib.Path(st.root) / cp).read_text(encoding="utf-8")
    # ④ 复制件里没有签块；读数逐条对上
    assert VS.SIGN_MARK not in copy_text, copy_text.split("\n")[:8]
    assert got["cleared"] == 1, got
    assert got["cleared_lines"] and got["cleared_lines"][0].startswith(VS.SIGN_MARK), got
    assert got["signed_before"] is True and got["signed_after"] is False, got
    assert VS.manuscript_sign_reading(copy_text, manuscript_path=cp)["found"] is False
    # 源稿一个字节没动（只读权）
    assert (pathlib.Path(st.root) / src).read_bytes() == src_before
    # 两个 sha 都是读数：正文逐字复制（相同是对的），整份文件变了（签块没了）
    assert got["source_body_sha"] == body_sha == got["copy_body_sha"], got
    assert got["source_sign_sha"] == body_sha, got
    assert got["source_text_sha256"] != got["copy_text_sha256"], got
    assert got["copy_text_sha256"] == hashlib.sha256(
        copy_text.encode("utf-8")).hexdigest(), got
    # 稿头还写着这条命题（下一轮落稿靠它找回自己那份）
    assert f"- 命题号：stmt:{SID}" in copy_text, copy_text.split("\n")[:5]
    # 乙的读口：这一份副本自己**没有签**（签在源稿上）
    assert VS.signed_manuscripts(st.root, artifact_path=cp)["found"] is False
    assert VS.signed_manuscripts(st.root, artifact_path=src)["found"] is True
    # 盘上多出来的只有那一份副本
    assert _files(st) == sorted([pathlib.Path(src).name,
                                 pathlib.Path(cp).name]), _files(st)


# ------------------------------------------------------------------ b 反向：没签

def test_b_an_unsigned_statement_gets_a_controlled_refusal(tmp_path) -> None:
    """b：源没签 ⇒ 受控拒「这一条还没有签，无可优化」，且一个文件都不新增。"""
    st = _ws(tmp_path)
    (pathlib.Path(st.root) / REL_F).write_text(
        MANUSCRIPT.replace(SIGN_LINE.format(sha=PR.proof_sha(BODY)) + "\n", "")
        .replace("__SHA__", PR.proof_sha(BODY)), encoding="utf-8")
    before = _files(st)
    got = _b(st).open_polish_copy(statement_id=SID)
    assert got.get("ok") is False, got
    assert got.get("refused") == "no_signed_manuscript", got
    assert "没有签" in str(got.get("why") or ""), got
    assert str(got.get("path") or "") == "", got
    assert _files(st) == before, (_files(st), before)


# ------------------------------------------------------------------ c 反向：号不乱用

def test_c_the_b_number_comes_from_the_b_counter(tmp_path) -> None:
    """c：B 稿号来自 `counters.bmanuscript`；源稿号 / 命题号都不参与。"""
    st = _ws(tmp_path)
    src = _signed_source(st)
    # 先把 B 的计数器推到一个与源稿号 / 命题号都不同的位置
    other = MID.next_manuscript_id(st, family="b-proof")
    assert other == "000000", other
    got = _b(st).open_polish_copy(statement_id=SID)
    assert got.get("ok") is True, got
    mid = str(got["manuscript_id"])
    assert mid == "000001", got
    assert mid not in (VS.manuscript_id_of(src), SID), got
    assert str(got["path"]) == f"reports/b-proof-{mid}.md", got


# ------------------------------------------------------------------ d 反真空

def test_d1_not_clearing_the_sign_makes_a_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d-1 反真空：清签那一步被摘掉 ⇒ 复制件仍带签块 ⇒ a 必须红。"""
    st = _ws(tmp_path)
    _signed_source(st)
    from agentflow.agent_b import open_polish_copy as OPC

    real = OPC._strip_sign_lines
    monkeypatch.setattr(OPC, "_strip_sign_lines",
                        lambda text: (str(text), []))
    got = _b(st).open_polish_copy(statement_id=SID)
    # 清签没做成 ⇒ 这一笔必须受控拒（而不是"成功"一份仍带签的副本）
    assert got.get("ok") is False, got
    assert got.get("refused") == "sign_not_cleared", got
    assert got.get("signed_after") is True, got
    assert real is not None


def test_d2_copying_under_the_source_number_makes_c_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d-2 反真空：复制件用源稿号（不向 B 的号段要号）⇒ c 必须红。"""
    st = _ws(tmp_path)
    src = _signed_source(st)
    real = MID.next_manuscript_id

    def _reuse_source(root, *, family=MID.FAMILY_F):
        if str(family) == "b-proof":
            return VS.manuscript_id_of(src)      # 源稿号：复用，不发新号
        return real(root, family=family)

    monkeypatch.setattr(MID, "next_manuscript_id", _reuse_source)
    got = _b(st).open_polish_copy(statement_id=SID)
    assert got.get("ok") is True, got
    mid = str(got["manuscript_id"])
    # c 的两条判据（号来自 B 的号段 / 计数器推进了）在这里必须都不成立
    assert mid == VS.manuscript_id_of(src), got
    assert MID.peek_manuscript_counter(st, family="b-proof") == 0, got
