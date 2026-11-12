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
| a | 正控：源已拿签 ⇒ 复制成功、B 稿号来自 B 的号段、复制件里没有签块、源稿一个字节没动 | `B.open_polish_copy` 四步走通 |
| b | 反向：源没签 ⇒ 受控拒（`no_signed_manuscript`），不产生任何文件 | 「拿没签的稿来优化」在结构上不可能 |
| c | 反向：B 稿号不乱用（来自 `counters.bmanuscript`，不是源稿号、不是命题号） | 号源唯一 |
| d1 | 反真空：不清签 ⇒ a 红（复制件仍读成已签） | a 的绿来自清签那一步 |
| d2 | 反真空：复制件用源稿号 ⇒ c 红 | c 的绿来自 B 自己的号段 |

## 2026-11-11 补的第 ④ 条证据（本文件下半场）

收录之后才出现的现场：F 的稿在收录时「不改名也不改稿头」（一稿一份的纪律），稿头仍是
`stmt:（还没落号）`；V 的未在册签里 `statement_id` 是空串 ⇒ 改前那三条证据（点名 /
签里的命题号 / 稿头认领）一条都够不着，`open_polish_copy` 反而在收录之后找不到那份
已签的稿。第 ④ 条读命题行上的 `manuscript_id`，再回颁发表按 `artifact_path` 核对。

| # | 判据 | 钉住的东西 |
|---|---|---|
| a2 | 未在册签 → 收录（行上真记 `manuscript_id`）→ `open_polish_copy` ⇒ 成功，源稿是 `reports/f-proof-<稿号>.md`，`matched_by="statement_manuscript_id"` | 第 ④ 条证据真的接上了 |
| b2 | 行上记了稿号、但那一份「没签」⇒ 受控拒（`no_signed_manuscript`），不许拿没签的稿开副本 | 第 ④ 条不是"有号就放行" |
| c2 | 行上没记稿号、稿头也认不出 ⇒ 仍 `no_signed_manuscript`，且 `why` 点明差的是「行上没记稿号」 | 「没查成」与「行上没记」分得清 |
| d3 | 反真空：把第 ④ 条证据摘掉 ⇒ a2 红 | a2 的绿来自行上那一格 |

## 一句话口径：正文 sha 为什么与源相同

复制件是逐字复制（优化还没开始），所以 `## 证明` 那一节的 sha 与源相同 —— 这是
对的，也是"签按正文 sha 认"的自然结果。清签改变的是整份文件：文件 sha 变了、
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

## 命题

夹具命题。

## 证明

{BODY}

## 依赖

| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |
|---|---|---|
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
    # 乙的读口：这一份副本自己没有签（签在源稿上）
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


# ======================================================================
# 第 ④ 条证据：命题行上的 `manuscript_id`（2026-11-11）
# ======================================================================

def _ws_bare(tmp_path: pathlib.Path) -> Store:
    """只建工作区（不预铺 `statements`）：给"真走一遍收录"的那条判据用。"""
    st = Store(tmp_path / "ws")
    st.init()
    (pathlib.Path(st.root) / "reports").mkdir(parents=True, exist_ok=True)
    return st


def _unregistered_manuscript(*, manuscript_id: str, signed: bool) -> str:
    """F 的稿：稿头仍是 `stmt:（还没落号）`（收录不改稿头）；`signed` 只决定有没有签块。

    签块里的 `命题号=` 是空串 —— 与 V 未在册那一档 `vsigns.issue(statement_id="")`
    写出来的签文件同形（本文件 a2 另外用 `issue_credential(statement_id="")` 落签文件）。
    """
    lines = [
        "# F 的证明手稿：夹具命题（未在册签）",
        "",
        "- 命题号：stmt:（还没落号）",
    ]
    if signed:
        lines.append(
            "- V 签：已签=true；判词=成立；连续=3/3；"
            f"正文sha={PR.proof_sha(BODY)}；时间=2026-11-02T10:00:00+08:00；"
            "签名者=V；台账=verifications/000000.jsonl#v-000003；"
            f"命题号=stmt:；手稿号={manuscript_id}")
    lines += [
        "- 依赖面洗稿：已洗=true；洗的人=secretary:F；补写=无",
        "",
        "## 命题",
        "",
        "夹具命题。",
        "",
        "## 证明",
        "",
        BODY,
        "",
        "## 依赖",
        "",
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |",
        "|---|---|---|",
        "（这一份证明没有引用任何在册命题 —— 空表就是声明。）",
        "",
    ]
    return "\n".join(lines)


def _ingest_unregistered_signed(st: Store) -> tuple[str, str, str]:
    """F 交卷（稿头未落号）→ V 未在册签 → B 收录（行上记 `manuscript_id`）。

    - 签文件：`issue_credential(statement_id="", artifact_path=rel)` —— 与 V 的
      `proof_unregistered_signed` 那一支写出来的签同形（命题号是空串）；
    - 准入闸：`conftest.sign_before_registration` 落同一份正文的 pending 台账；
    - 收录：走 B 的真入口 `ingest_manuscript(mode="register")`，不手写
      `manuscript_id` / `bits`。

    返回 `(statement_id, 稿路径, 稿号)`。
    """
    mid = MID.next_manuscript_id(st.root)
    rel = MID.canonical_rel(mid)
    (pathlib.Path(st.root) / rel).write_text(
        _unregistered_manuscript(manuscript_id=mid, signed=True), encoding="utf-8")
    CF.issue_credential(st.root, proof_text=BODY, statement_id="",
                        manuscript=rel, artifact_path=rel)
    conftest.sign_before_registration(st.root, proof_text=BODY)
    got = _b(st).ingest_manuscript(
        manuscript=rel, mode="register",
        cells=("statement_full", "proof_text", "dependencies"))
    assert got.get("ok") is True, got
    sid = str((got.get("register") or {}).get("stmt_id") or "")
    assert sid, got
    return sid, rel, mid


def test_a2_the_row_manuscript_id_finds_the_signed_source(tmp_path) -> None:
    """第 ④ 条正控：未在册签 → 收录 → 光凭命题号就能拿到那份已签的稿。

    这条用例就是彩排那次缺陷的回归：F 的稿头仍是「stmt:（还没落号）」、签文件里的
    命题号也是空串 —— 前三条证据一条都够不着，收录之后还能不能用命题号找回它。
    """
    st = _ws_bare(tmp_path)
    sid, rel, mid = _ingest_unregistered_signed(st)
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id") or "") == sid)
    # 收录那一笔真的把稿号记在行上（第 ④ 条证据的源头，不是夹具手写）
    assert str(row.get("manuscript_id") or "") == mid, row
    assert bool((row.get("bits") or {}).get("reviewed")) is True, row
    # 前三条证据确实够不着：签里的命题号是空串、稿头也还不是这一条命题的号
    table = VS.signed_manuscripts(st.root, artifact_path=rel)
    assert table["found"] is True, table
    assert str(table["latest"].get("statement_id") or "") == "", table
    assert str(table["latest"].get("manuscript_id") or "") == mid, table
    head = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    assert "stmt:（还没落号）" in head, head.split("\n")[:6]

    got = _b(st).open_polish_copy(statement_id=sid)
    assert got.get("ok") is True, got
    assert got.get("refused") == "", got
    assert got.get("source_path") == rel, got
    assert got.get("source_manuscript_id") == mid, got
    assert got.get("matched_by") == "statement_manuscript_id", got
    # 复制件是 B 自己的号段、签块清掉、源稿一个字节没动
    cp = str(got.get("path") or "")
    assert cp == MID.canonical_rel(str(got.get("manuscript_id") or ""),
                                   family="b-proof"), got
    copy_text = (pathlib.Path(st.root) / cp).read_text(encoding="utf-8")
    assert VS.SIGN_MARK not in copy_text, copy_text.split("\n")[:8]
    assert got.get("cleared") == 1, got
    assert (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") == head


def test_b2_a_row_number_without_a_sign_is_refused(tmp_path) -> None:
    """第 ④ 条反控①：行上记了稿号，但那一份没签 ⇒ 受控拒，一个文件都不新增。

    第 ④ 条不是"有号就放行"：它只是把「该去哪一份稿」指出来，签还在 V 的颁发表里核。
    """
    st = _ws(tmp_path)
    mid = MID.next_manuscript_id(st.root)
    rel = MID.canonical_rel(mid)
    (pathlib.Path(st.root) / rel).write_text(
        _unregistered_manuscript(manuscript_id=mid, signed=False), encoding="utf-8")
    conftest.seed_statement_row(st, stmt_id=SID, statement_full="夹具命题。",
                                kind="conjecture", manuscript_id=mid)
    before = _files(st)

    got = _b(st).open_polish_copy(statement_id=SID)
    assert got.get("ok") is False, got
    assert got.get("refused") == "no_signed_manuscript", got
    assert "记了稿号、但那一份没签" in str(got.get("why") or ""), got
    assert got.get("matched_by") == "", got
    assert _files(st) == before, (_files(st), before)


def test_c2_without_a_row_number_the_why_names_the_missing_evidence(tmp_path) -> None:
    """第 ④ 条反控②：行上没记稿号、稿头也认不出 ⇒ 仍 `no_signed_manuscript`。

    `why` 必须点明差的是「行上没有记稿号」这一条 —— 不许把"行上没记"读成"没有签"，
    也不许只说"按命题号、按稿头都找过"（那正是改前那句看不出还差什么的 why）。
    """
    st = _ws(tmp_path)
    mid = MID.next_manuscript_id(st.root)
    rel = MID.canonical_rel(mid)
    (pathlib.Path(st.root) / rel).write_text(
        _unregistered_manuscript(manuscript_id=mid, signed=False), encoding="utf-8")
    conftest.seed_statement_row(st, stmt_id=SID, statement_full="夹具命题。",
                                kind="conjecture")
    before = _files(st)

    got = _b(st).open_polish_copy(statement_id=SID)
    assert got.get("ok") is False, got
    assert got.get("refused") == "no_signed_manuscript", got
    why = str(got.get("why") or "")
    assert "差第 ④ 条证据" in why, got
    assert "行上没有记稿号" in why, got
    assert "没有签" in why, got
    assert _files(st) == before, (_files(st), before)


def test_d3_removing_the_row_number_evidence_turns_a2_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """第 ④ 条反真空：把它摘掉 ⇒ a2 必须红（`no_signed_manuscript`）。

    打桩点就是第 ④ 条的证据源（`_statement_manuscript_id`）：其余三条原样保留。
    """
    st = _ws_bare(tmp_path)
    sid, _rel, _mid = _ingest_unregistered_signed(st)
    from agentflow.agent_b import open_polish_copy as OPC

    real = OPC._OpenPolishCopy._statement_manuscript_id
    monkeypatch.setattr(
        OPC._OpenPolishCopy, "_statement_manuscript_id",
        lambda self, sid: {"checked": True, "manuscript_id": "", "why": ""})
    got = _b(st).open_polish_copy(statement_id=sid)
    assert got.get("ok") is False, got
    assert got.get("refused") == "no_signed_manuscript", got
    assert got.get("matched_by") == "", got
    assert "行上没有记稿号" in str(got.get("why") or ""), got
    assert real is not None
