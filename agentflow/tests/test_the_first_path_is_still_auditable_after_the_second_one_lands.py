# -*- coding: utf-8 -*-
"""判据：第 1 条路径在收录第 2 条之后仍然可审、可签（F1，2026-11-12）。

## 缺陷（探针实测）

`statements` 行上只有一格 `manuscript_id`，B 收录时由
`agent_b/proof_receipt.py::write_proof_receipt`（`_attach_proofs` 调用）写成
「最后一次收录的那份稿」。`agent_v/core.py::_registered_manuscript_body` 改前只认
这一格 ⇒ 同一命题收录第 2 条路径之后，再审第 1 条路径的稿会被判
`bad_manuscript_name`：第 1 条路径结构上不可再审、不可再签。

## 修法（业主 2026-11-12 口径：多路径要保留）

逐路径的权威记录在 `manuscriptpaths.path_reading`（每条路径的 `path_group` +
`manuscript`）。V 认「被审的那份稿」改成：先问「这份稿的稿号在不在某条路径上」，
再退回命题行那一格（老盘 / 没有逐路径记录）；两种都不认才受控拒。
`statements.manuscript_id` 的写入语义一个字没动。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | 收录路径 1（稿号 000007）→ 在册审它、签住 → 收录路径 2（稿号 000008，行上那一格变成 000008）→ 改写路径 1 的证明 → 再审路径 1 | 能审、能签：`checked=True`、`matched_by="path_manuscript"`、`path_group=1`、`row_manuscript_id=000008`、新签块盖的是改写后的正文 |
| b | 同一现场，审路径 2 的稿 | 也能审、能签：`checked=True`、行上那一格 000008 不遮蔽路径 1，路径 2 不被路径 1 遮蔽 |
| c | 反真空：把 `manuscriptpaths.path_reading` 打桩成空路径表 | a 的第二半必须红（`bad_manuscript_name`）：证明 a 的绿来自「认逐路径记录」 |
| d | 三态：把 `path_reading` 打桩成读不出来（`checked=False`） | 不许静默放行：受控拒，且读数 `path_checked=False` / `path_problem` 非空、`matched_by` 不是行上那一格的退路（`fallback=False`），detail 说清「没读成」 |

零模型钱：B 的收录走确定性路径；V 的审阅缝是预置 clean，不联网。
"""
from __future__ import annotations

import contextlib
import json
import pathlib

import pytest

import conftest
from agentflow import depsection as DS
from agentflow import manuscriptpaths as MP
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_v import AgentV
from agentflow.secretary import Secretary
from agentflow.store import Store

from test_agent_v_exhaustion_review import _v_secretary

CLEAN = json.dumps({"verdict": "成立", "findings": []}, ensure_ascii=False)
PROPOSITION = "对任意有限群 G，若 p 整除 |G|，则 G 有 p 阶元。"
P1 = "1. 取 G 的一个 Sylow p-子群 P，由拉格朗日定理得到 p 阶元。"
P2 = "1. 对 |G| 归纳：取中心元，按共轭类计数得到 p 阶元。"
P1_REWRITE = "1. 换一条路：让 G 作用在自身的 p 阶元集合上，计数不动点即得。"
REL1 = "reports/f-proof-000007.md"
REL2 = "reports/f-proof-000008.md"
MID1 = "000007"
MID2 = "000008"


class _CleanSeam:
    """只记调用次数、永远回 clean 的 V 审阅缝。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def ask(self, prompt: str = "", **_kw):
        from types import SimpleNamespace

        self.prompts.append(prompt)
        return SimpleNamespace(text=CLEAN, problem="")


@contextlib.contextmanager
def _submitted_by_f(tag: str):
    from agentflow import conductor as CND

    with CND.calling_as(tag, "V", parent_task_id=f"t-f-{tag[-6:]}",
                        parent_role="F"):
        yield


@pytest.fixture(autouse=True)
def _proof_kind_different(monkeypatch):
    """B 收录第 2 条路径时「同种 / 不同种」那一问的默认回答：different。

    这一条判据量的是 V 的在册闸，不是 B 的语义判别；没有判定面时 B 会 fail-closed
    拒收第二份稿，夹具就造不出「两条路径都在册」的现场。
    """
    real = Secretary.judge

    def _judge(self, kind, context, **kw):
        if kind == "proof_kind":
            return {"checked": True, "decision": "different", "same_path": 0,
                    "reason": "夹具：不同种（本判据不量语义判别）",
                    "basis": [], "cost": {}}
        return real(self, kind, context, **kw)

    monkeypatch.setattr(Secretary, "judge", _judge)


def _manuscript(sid: str, proof: str) -> str:
    head = f"- 命题号：stmt:{sid}\n" if sid else ""
    return ("# F 的证明手稿\n\n" + head + "\n## 命题\n\n" + PROPOSITION
            + "\n\n## 证明\n\n" + proof + "\n\n"
            + DS.render_dependency_section([]) + "\n")


def _write(st: Store, rel: str, text: str) -> None:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _row(st: Store, sid: str) -> dict:
    return next(dict(r) for r in st.rows("statements")
                if str(r.get("stmt_id")) == sid)


def _signed(st: Store, rel: str, proof: str) -> dict:
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    block = VS.manuscript_sign_reading(text, manuscript_path=rel)
    return {"signed": block.get("signed"),
            "sha": str(block.get("proof_sha256") or ""),
            "want": VR.text_sha(proof),
            "block": block}


def _land_both_paths(st: Store, b: AgentB, seam: _CleanSeam) -> tuple[str, AgentV]:
    """现场：路径 1 收录后在册签住，再收录路径 2（行上那一格变成 000008）。

    路径 1 的收录闸要一份覆盖 P1 的签（B 的准入闸口径，不是本判据的对象）：
    用 `conftest.sign_before_registration` 的真 pending 台账造它。真正的在册审签
    紧接着由 V 自己做（下面那一次 `verify_proof`），它落下的台账行带
    `manuscript=reports/f-proof-000007.md`，逐路径记录由此认得出路径 1 的稿。
    """
    _write(st, REL1, _manuscript("", P1))
    conftest.sign_before_registration(st.root, proof_text=P1)
    got1 = b.ingest_manuscript(manuscript=REL1, mode="register")
    assert got1.get("ok") is True, got1
    sid = str((got1.get("target") or {}).get("stmt_id") or "")
    assert sid and sid != MID1, got1
    assert str(_row(st, sid).get("manuscript_id") or "") == MID1, _row(st, sid)
    assert MP.path_reading(st, st.root, statement_id=sid)["count"] == 1

    v = AgentV(st, workspace_root=st.root, llm=seam,
               secretary=_v_secretary(st))
    with _submitted_by_f("t-f1-000001"):
        first = v.verify_proof(sid, proof_manuscript=REL1)
    assert first.get("checked") is True, first
    assert str(first.get("kind") or "") != "bad_manuscript_name", first
    assert _signed(st, REL1, P1)["signed"] is True

    _write(st, REL2, _manuscript(sid, P2))
    conftest.sign_for_the_gate(st.root, statement_id=sid, proof_text=P2,
                               proof_no=2, store=st, manuscript=REL2)
    got2 = b.ingest_manuscript(manuscript=REL2, target_stmt_id=sid,
                               cells=["proof_text", "dependencies"], mode="apply")
    assert got2.get("ok") is True, got2
    # 路径 2 的收录闸那枚夹具签（`conftest.sign_for_the_gate`）的收方固定写给 B，
    # 它只用来过 B 的准入闸；这里把它撤掉，好让下面 b 那一次 V 在册审真的签发、真的落块。
    _cred = VS.sign_path(st.root, VR.text_sha(P2))
    if _cred.is_file():
        _cred.unlink()
    assert str(_row(st, sid).get("manuscript_id") or "") == MID2, _row(st, sid)
    reading = MP.path_reading(st, st.root, statement_id=sid)
    assert reading.get("count") == 2, reading
    return sid, v


def _put_old_row(st: Store, sid: str, proof: str) -> None:
    """老盘的命题行：没有 `manuscript_id` 这一格（退回口径的那一档）。"""
    row = {
        "stmt_id": sid, "origin": "own_result", "kind": "theorem",
        "label": "p 阶元", "statement_full": PROPOSITION, "statement_text": "p 阶元",
        "proof_text": proof, "proof_sha256": VR.text_sha(proof), "proof_no": 1,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "自产命题",
        "created_at": "2026-11-12T00:00:00+08:00", "created_by": "test",
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)


def _rewrite_first_path(st: Store, sid: str) -> None:
    """路径 1 的稿换了 `## 证明`（同一稿号、同一文件）：再审不会短接成 already_signed。"""
    _write(st, REL1, _manuscript(sid, P1_REWRITE))


# ====================================================================== a 正控
def test_a_the_first_path_is_still_auditable_after_the_second_one_lands(
        tmp_path: pathlib.Path) -> None:
    """改前红：收录路径 2 之后，再审路径 1 被判 `bad_manuscript_name`。

    这里走的是真在册闸：行上那一格已被路径 2 覆写成 000008，而送审的是路径 1
    的 000007。修后它由逐路径记录认回第 1 条路径，并且新签真的落回那份稿。
    """
    st = Store(tmp_path / "ws")
    st.init()
    b = AgentB(st, extractor=None, extract_text=None, config={})
    seam = _CleanSeam()
    sid, v = _land_both_paths(st, b, seam)
    _rewrite_first_path(st, sid)

    with _submitted_by_f("t-f1-000002"):
        got = v.verify_proof(sid, proof_manuscript=REL1)

    assert got.get("checked") is True, got
    assert str(got.get("kind") or "") != "bad_manuscript_name", got
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("matched_by") == "path_manuscript", identity
    assert identity.get("path_checked") is True, identity
    assert int(identity.get("path_group") or 0) == 1, identity
    assert identity.get("manuscript_id") == MID1, identity
    assert identity.get("row_manuscript_id") == MID2, identity
    assert identity.get("fallback") is False, identity
    block = _signed(st, REL1, P1_REWRITE)
    assert block["signed"] is True, block["block"]
    assert block["sha"] == block["want"], block
    # 路径 2 的稿还在盘上（这一趟只审路径 1，没有把路径 2 的载体弄丢）。
    assert (pathlib.Path(st.root) / REL2).is_file()


# ====================================================================== b 正控
def test_b_the_second_path_is_auditable_and_signable_too(
        tmp_path: pathlib.Path) -> None:
    """两条路径互不遮蔽：路径 2 的稿也能在册审、在册签。"""
    st = Store(tmp_path / "ws")
    st.init()
    b = AgentB(st, extractor=None, extract_text=None, config={})
    seam = _CleanSeam()
    sid, v = _land_both_paths(st, b, seam)

    with _submitted_by_f("t-f1-000003"):
        got = v.verify_proof(sid, proof_manuscript=REL2)

    assert got.get("checked") is True, got
    assert str(got.get("kind") or "") != "bad_manuscript_name", got
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("manuscript_id") == MID2, identity
    assert identity.get("row_manuscript_id") == MID2, identity
    assert int(identity.get("path_group") or 0) == 2, identity
    block = _signed(st, REL2, P2)
    assert block["signed"] is True, block["block"]
    assert block["sha"] == block["want"], block


# ====================================================================== c 反真空
def test_c_stubbing_the_per_path_records_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 `path_reading` 打桩成空 ⇒ a 的第二半必须红（不是恒真）。

    打桩点就是 V 认逐路径记录的那一个读口（`manuscriptpaths.path_reading`）：
    它一空，路径 1 只能退回行上那一格（000008），000007 立刻被拒。
    """
    st = Store(tmp_path / "ws")
    st.init()
    b = AgentB(st, extractor=None, extract_text=None, config={})
    seam = _CleanSeam()
    sid, v = _land_both_paths(st, b, seam)
    _rewrite_first_path(st, sid)

    def _empty(store, root, *, statement_id):
        return {"checked": True, "statement_id": str(statement_id),
                "paths": [], "count": 0, "why": "反真空：打桩成空路径表"}

    monkeypatch.setattr(MP, "path_reading", _empty)
    with _submitted_by_f("t-f1-000004"):
        got = v.verify_proof(sid, proof_manuscript=REL1)

    assert got.get("checked") is False, (
        "逐路径记录被打桩成空之后，a 的第二半仍然绿 ⇒ a 量不到这一格：", got)
    assert got.get("kind") == "bad_manuscript_name", got
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("path_checked") is True, identity
    assert int(identity.get("path_count") or 0) == 0, identity
    assert identity.get("matched_by") == "manuscript_id", identity
    assert identity.get("fallback") is False, identity
    assert "逐路径记录" in str(got.get("detail") or ""), got.get("detail")
    assert _signed(st, REL1, P1_REWRITE)["signed"] is False, (
        "被拒之后稿上还落了签 ⇒ 这一格没在挡")


# ====================================================================== d 三态
def test_d_unreadable_per_path_records_are_not_a_silent_pass(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """逐路径记录读不出来 ⇒ 受控拒，读数说清「没读成」而不是退回命题行那一格。

    与 c 的区别：c 是「查过了、没有这条路径」，d 是「没查成」。两种都 fail-closed，
    但读数必须分得开（`path_checked` / `path_problem`），不许折成同一个理由。
    """
    st = Store(tmp_path / "ws")
    st.init()
    b = AgentB(st, extractor=None, extract_text=None, config={})
    seam = _CleanSeam()
    sid, v = _land_both_paths(st, b, seam)
    _rewrite_first_path(st, sid)

    def _unreadable(store, root, *, statement_id):
        return {"checked": False, "statement_id": str(statement_id),
                "paths": [], "count": 0,
                "why": "打桩：逐路径记录读不出来（台账坏了）"}

    monkeypatch.setattr(MP, "path_reading", _unreadable)
    with _submitted_by_f("t-f1-000005"):
        got = v.verify_proof(sid, proof_manuscript=REL1)

    assert got.get("checked") is False, got
    assert got.get("kind") == "bad_manuscript_name", got
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("path_checked") is False, identity
    assert "读不出来" in str(identity.get("path_problem") or ""), identity
    assert identity.get("fallback") is False, identity
    assert identity.get("matched_by") == "manuscript_id", identity
    detail = str(got.get("detail") or "")
    assert "没读成" in detail, detail
    assert "退回老口径" not in detail, (
        "逐路径记录读不出来被折成了「行上没有 manuscript_id」的退路：", detail)
    assert _signed(st, REL1, P1_REWRITE)["signed"] is False, (
        "逐路径记录没读成还落了签 ⇒ 这一格没 fail-closed")


def test_d2_unreadable_records_do_not_ride_the_old_disk_fallback(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """「没读成」与「老盘上没有这一格」是两件事：前者不许走退回口径放行。

    这一档的行上没有 `manuscript_id`，稿名里的号 == 命题号 —— 改前这正好命中
    「退回老口径」而放行。逐路径记录读不出来时，这个放行就不再可靠：我们不知道
    它是老盘，还是台账坏了。所以受控拒，读数 `path_checked=False` / `fallback=False`。
    """
    st = Store(tmp_path / "ws")
    st.init()
    sid = "000000"
    rel = f"reports/f-proof-{sid}.md"
    _put_old_row(st, sid, P1)
    _write(st, rel, _manuscript(sid, P1))
    v = AgentV(st, workspace_root=st.root, llm=_CleanSeam(),
               secretary=_v_secretary(st))

    def _unreadable(store, root, *, statement_id):
        return {"checked": False, "statement_id": str(statement_id),
                "paths": [], "count": 0, "why": "打桩：逐路径记录读不出来"}

    monkeypatch.setattr(MP, "path_reading", _unreadable)
    with _submitted_by_f("t-f1-000006"):
        got = v.verify_proof(sid, proof_manuscript=rel)

    assert got.get("checked") is False, got
    assert got.get("kind") == "bad_manuscript_name", got
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("path_checked") is False, identity
    assert identity.get("path_problem"), identity
    assert identity.get("fallback") is False, identity
    assert identity.get("matched_by") == "statement_id", identity
    detail = str(got.get("detail") or "")
    assert "没读成" in detail, detail
    assert "判不了" in detail, detail
    assert _signed(st, rel, P1)["signed"] is False, (
        "逐路径记录没读成、行上也没有那一格，却还是按老口径放行签了")
