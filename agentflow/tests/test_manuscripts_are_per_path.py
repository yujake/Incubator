# -*- coding: utf-8 -*-
"""判据：一份命题的每条证明路径各自留着它的稿（`statements.manuscripts`，V1）。

## 缺陷（改前，两处一起犯）

① `statements.manuscript_id` 只有一格，B 收录时被 `agent_b/proof_receipt.py::
write_proof_receipt` 写成「最后一次收录的那份稿」⇒ 收录第 2 条路径之后，「第 1 条
路径是哪份稿」只剩 `verifications` 签行那一处读数。而
`verifications._claimed_pending_rows` 只认已认领的 pending 行：收录前落下的那一签在
认领之前不属于任何命题 ⇒ 那条路径在 `manuscriptpaths.path_reading` 里只剩正文 sha、
没有稿号。V 认稿的第一来源（「这一份稿在某条逐路径记录上」）于是对那条路径恒假，
只能退回行上那一格 —— 而那一格早被第 2 条路径覆写。

② `manuscriptpaths.stamp_verification_path_group` 的跳过判据写的是
`path.name != f"{命题号}.jsonl"`，而 pending 台账的文件名是正文 sha
（`verifications.pending_ledger_path`）⇒ 收录这一笔不会给收录前落下的那一行补路径号，
哪怕它已经认领给这条命题。

## 修法

- 新格 `statements.manuscripts`：`{路径号: 工作区相对路径}`（JSON 的键只能写字符串）。
  写入口只有一处：`write_proof_receipt`；号就是这一笔的路径号，与依赖行 / 签行同号。
  `manuscript_id` 保留原义：「最近一次收录的那份稿」。
- 读口：`manuscriptpaths.path_reading` 多读这一格。每条路径取稿的次序是
  「签行的 `manuscript`（V 真的盖在那份稿上）→ 逐路径记录 → `object_path` 兜底」。
- `stamp_verification_path_group`：盖号不看认领状态（盖号不是认领 —— `statement_id`
  那一格仍然只有 `vsigns.bind_pending_claim` 能写）。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | 收路径 1 的稿（收录前那一签落 pending）→ 收路径 2 的稿 → 改写路径 1 的正文、再审路径 1 | 能审、能签（`matched_by="path_manuscript"`、`path_group=1`），且行上 `manuscript_id` 已是路径 2 的号；两条路径的 `manuscript` 都在逐路径记录里（不是只有最后一次） |
| b | 收录前读 pending 行 → `mode=register` 收录 → 再读同一份 pending 台账 | 改前那一行没有 `path_group`；改后有，等于 1；且文件名不是 `<命题号>.jsonl`（改前的跳过判据正按后一个写） |
| c | 反真空：把逐路径稿记录打桩成空 | a 的「审路径 1」必须红（`bad_manuscript_name`）；路径仍数得出两条 ⇒ 红的是「稿认不出」，不是「路径没了」 |
| d | 三态：把 `manuscripts` 写成读不出来的形状 | `path_reading` 报一条读数问题；V 受控拒、detail 说清「没读成」，不退回老口径 |
| d2 | 三态（整条记录没读成）：把 `path_reading` 打桩成 `checked=False` | 同上：受控拒 + `path_checked=False` + detail 说「没读成」 |

零模型钱：B 的收录走确定性路径；V 的审阅缝是预置 clean，不联网。
"""
from __future__ import annotations

import contextlib
import json
import pathlib

import pytest

import conftest
from agentflow import manuscriptpaths as MP
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_v import AgentV
from agentflow.store import Store

from test_agent_v_exhaustion_review import _v_secretary
from test_the_first_path_is_still_auditable_after_the_second_one_lands import (  # noqa: F401
    _CleanSeam, _manuscript, _proof_kind_different, _row, _signed, _submitted_by_f,
    _write,
)

PROPOSITION = "对任意有限群 G，若 p 整除 |G|，则 G 有 p 阶元。"
P1 = "1. 取 G 的一个 Sylow p-子群 P，由拉格朗日定理得到 p 阶元。"
P2 = "1. 对 |G| 归纳：取中心元，按共轭类计数得到 p 阶元。"
P1_REWRITE = "1. 换一条路：让 G 作用在自身的 p 阶元集合上，计数不动点即得。"
REL1 = "reports/f-proof-000007.md"
REL2 = "reports/f-proof-000008.md"
MID1 = "000007"
MID2 = "000008"


def _pending_files(root) -> list[pathlib.Path]:
    """这一趟 pending 台账的全部文件（按名字序；`path_reading` 读的是同一批）。"""
    base = VR.pending_dir(root)
    return sorted(base.glob("*.jsonl")) if base.is_dir() else []


def _jsonl_rows(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _drop_gate_credential(root, proof_text: str) -> None:
    """撤掉只用来过 B 准入闸的那枚夹具签，让 V 下一次在册审真的签发、真的落块。"""
    cred = VS.sign_path(root, VR.text_sha(proof_text))
    if cred.is_file():
        cred.unlink()


def _scene(tmp_path: pathlib.Path) -> tuple[Store, str]:
    """现场：路径 1 先收（收录前那一签落 pending），路径 2 后收（行上那一格变成 000008）。

    路径 1 刻意没有在册审过：它的稿只有逐路径记录能认出来（签行那一面还没有它）。
    这正是「一条路径若从未在册重签、只剩未打号的 pending 行」那个形态。
    """
    st = Store(tmp_path / "ws")
    st.init()
    b = conftest.b_form_gate_ok(AgentB(st, extractor=None, extract_text=None, config={}))
    _write(st, REL1, _manuscript("", P1))
    conftest.sign_before_registration(st.root, proof_text=P1)
    first = b.ingest_manuscript(manuscript=REL1, mode="register")
    assert first.get("ok") is True, first
    sid = str((first.get("target") or {}).get("stmt_id") or "")
    assert sid and sid != MID1, first
    _write(st, REL2, _manuscript(sid, P2))
    conftest.sign_for_the_gate(st.root, statement_id=sid, proof_text=P2,
                               proof_no=2, store=st, manuscript=REL2)
    second = b.ingest_manuscript(manuscript=REL2, target_stmt_id=sid,
                                 cells=["proof_text", "dependencies"], mode="apply")
    assert second.get("ok") is True, second
    _drop_gate_credential(st.root, P2)
    assert str(_row(st, sid).get("manuscript_id") or "") == MID2, _row(st, sid)
    return st, sid


def _v(st: Store) -> AgentV:
    return AgentV(st, workspace_root=st.root, llm=_CleanSeam(),
                  secretary=_v_secretary(st))


# ====================================================================== a 正控（端到端）
def test_a_each_path_keeps_its_manuscript_and_path_one_is_still_auditable(
        tmp_path: pathlib.Path) -> None:
    """① 端到端：两条路径各留一份稿；第 2 条收录之后，第 1 条仍能审、能签。"""
    st, sid = _scene(tmp_path)
    row = _row(st, sid)
    assert row.get("manuscripts") == {"1": REL1, "2": REL2}, (
        "逐路径记录里不是两条路径各一份稿（改前只有 `manuscript_id` 那一格，"
        "它记的是最后一次）：", row.get("manuscripts"))
    assert str(row.get("manuscript_id") or "") == MID2, (
        "`manuscript_id` 的语义改了：它必须仍是「最近一次收录的那份稿」", row)

    reading = MP.path_reading(st, st.root, statement_id=sid)
    assert reading.get("checked") is True and int(reading.get("count") or 0) == 2, reading
    by_group = {int(one["path_group"]): one for one in reading.get("paths") or []}
    assert by_group[1]["manuscript"] == REL1, by_group[1]
    assert by_group[1]["manuscript_id"] == MID1, by_group[1]
    assert by_group[2]["manuscript"] == REL2, by_group[2]
    assert by_group[2]["manuscript_id"] == MID2, by_group[2]

    _write(st, REL1, _manuscript(sid, P1_REWRITE))
    with _submitted_by_f("t-v1a-000001"):
        got = _v(st).verify_proof(sid, proof_manuscript=REL1)

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

    with _submitted_by_f("t-v1a-000002"):
        second = _v(st).verify_proof(sid, proof_manuscript=REL2)
    assert second.get("checked") is True, second
    second_identity = dict(second.get("manuscript_identity") or {})
    assert int(second_identity.get("path_group") or 0) == 2, second_identity
    second_block = _signed(st, REL2, P2)
    assert second_block["signed"] is True, second_block["block"]


# ====================================================================== b B 侧：pending 盖号
def test_b_register_stamps_the_pending_rows_path_group(tmp_path: pathlib.Path) -> None:
    """② B 侧：`mode=register` 收录之后，收录前落的 pending 行带上了路径号。

    反真空是「改前不带」：同一份 pending 台账在收录之前逐行读一遍，一行都没有
    `path_group` —— 所以「改后带」只能来自收录这一笔，不是夹具铺进去的。
    """
    st = Store(tmp_path / "ws")
    st.init()
    b = conftest.b_form_gate_ok(AgentB(st, extractor=None, extract_text=None, config={}))
    _write(st, REL1, _manuscript("", P1))
    conftest.sign_before_registration(st.root, proof_text=P1)
    files = _pending_files(st.root)
    assert len(files) == 1, files
    before = _jsonl_rows(files[0])
    assert before, before
    assert all("path_group" not in row for row in before), (
        "反真空失效：收录之前 pending 行里就已经有 `path_group`：", before)

    got = b.ingest_manuscript(manuscript=REL1, mode="register")
    assert got.get("ok") is True, got
    sid = str((got.get("target") or {}).get("stmt_id") or "")
    assert files[0].name != f"{sid}.jsonl", (
        "pending 台账的文件名碰巧等于 `<命题号>.jsonl` ⇒ 这一条判据量不到"
        "改前那个跳过判据（它按文件名区分 pending 与在册台账）：", files[0].name)
    after = _jsonl_rows(files[0])
    assert after, after
    assert [int(row.get("path_group") or 0) for row in after] == [1] * len(after), (
        "收录这一笔没有给收录前落的 pending 行盖上路径号：", after)


# ====================================================================== c 反真空
def test_c_stubbing_the_per_path_record_turns_path_one_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 反真空：把逐路径稿记录打桩成空 ⇒ ① 的「审路径 1」必须红。

    桩打在「读那一格」的唯一入口（`manuscriptpaths._per_path_manuscripts`），不是把
    `path_reading` 整个换掉：换掉只能证明"V 用了某个读口"，而这条要证的是"绿来自
    这一格"。路径数仍是 2（证明清单 + 依赖面给出来的）—— 于是红的是"稿认不出"，
    不是"路径没了"。
    """
    st, sid = _scene(tmp_path)
    _write(st, REL1, _manuscript(sid, P1_REWRITE))
    monkeypatch.setattr(MP, "_per_path_manuscripts", lambda row: ({}, []))
    with _submitted_by_f("t-v1c-000001"):
        got = _v(st).verify_proof(sid, proof_manuscript=REL1)

    assert got.get("checked") is False, (
        "逐路径稿记录被打桩成空之后，路径 1 仍然绿 ⇒ ① 量不到这一格：", got)
    assert got.get("kind") == "bad_manuscript_name", got
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("path_checked") is True, identity
    assert int(identity.get("path_count") or 0) == 2, (
        "路径数不该跟着稿一起消失：", identity)
    assert identity.get("matched_by") == "manuscript_id", identity
    assert identity.get("fallback") is False, identity
    assert _signed(st, REL1, P1_REWRITE)["signed"] is False, (
        "被拒之后稿上还落了签 ⇒ 这一格没在挡")


# ====================================================================== d 三态：读不出来
def test_d_an_unreadable_per_path_record_is_a_controlled_refusal(
        tmp_path: pathlib.Path) -> None:
    """③ 三态：`manuscripts` 读不出来 ⇒ 受控拒，读数说清「没读成」，不退回老口径。"""
    st, sid = _scene(tmp_path)
    _write(st, REL1, _manuscript(sid, P1_REWRITE))
    with st.tx("statements", actor="test") as tx:
        one = tx.find("statements", stmt_id=sid)
        one["manuscripts"] = "不是映射（坏形状）"
        tx.upsert("statements", one)

    reading = MP.path_reading(st, st.root, statement_id=sid)
    assert reading.get("checked") is True, reading
    problems = [str(x) for x in (reading.get("problems") or [])]
    assert any("manuscripts" in one for one in problems), (
        "读不出来的逐路径记录没有留下读数问题（会被折成「没有这一格」）：", reading)

    with _submitted_by_f("t-v1d-000001"):
        got = _v(st).verify_proof(sid, proof_manuscript=REL1)
    assert got.get("checked") is False, got
    assert got.get("kind") == "bad_manuscript_name", got
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("path_checked") is False, identity
    assert identity.get("path_problem"), identity
    detail = str(got.get("detail") or "")
    assert "没读成" in detail, detail
    assert "退回" not in detail, (
        "逐路径记录读不出来被折成了「老盘上没有这一格」的退路：", detail)
    assert _signed(st, REL1, P1_REWRITE)["signed"] is False, "没读成还落了签 ⇒ 这一格没 fail-closed"


def test_d2_the_whole_record_unreadable_also_refuses(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 三态（整条记录）：`path_reading` 说「没查成」⇒ 受控拒，不许静默放行。"""
    st, sid = _scene(tmp_path)
    _write(st, REL1, _manuscript(sid, P1_REWRITE))

    def _unreadable(store, root, *, statement_id):
        return {"checked": False, "statement_id": str(statement_id),
                "paths": [], "count": 0,
                "why": "打桩：逐路径记录读不出来（台账坏了）"}

    monkeypatch.setattr(MP, "path_reading", _unreadable)
    with _submitted_by_f("t-v1d-000002"):
        got = _v(st).verify_proof(sid, proof_manuscript=REL1)

    assert got.get("checked") is False, got
    assert got.get("kind") == "bad_manuscript_name", got
    identity = dict(got.get("manuscript_identity") or {})
    assert identity.get("path_checked") is False, identity
    assert "读不出来" in str(identity.get("path_problem") or ""), identity
    assert "没读成" in str(got.get("detail") or ""), got.get("detail")
    assert _signed(st, REL1, P1_REWRITE)["signed"] is False, (
        "逐路径记录没读成还落了签 ⇒ 这一格没 fail-closed")


# ====================================================================== e 写面白名单
def _manuscript_workspace(tmp_path: pathlib.Path) -> tuple[Store, AgentB]:
    """一份真手稿 + 收录前落的那一签（收录那一笔会写逐路径记录）。"""
    st = Store(tmp_path / "ws")
    st.init()
    _write(st, REL1, _manuscript("", P1))
    conftest.sign_before_registration(st.root, proof_text=P1)
    return st, conftest.b_form_gate_ok(
        AgentB(st, extractor=None, extract_text=None, config={}))


def test_e_the_write_whitelist_is_what_lets_the_per_path_record_land(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """②' 写面白名单：`manuscripts` 只加在 `attach_proofs` 那一项里，且这一票是必需的。

    反真空：把这一格从 `secretary.STATEMENT_LAND_OPS["attach_proofs"]` 里拿掉 ⇒
    同一笔收录必须整笔受控拒（`statement_patch_key_not_allowed`），行上不许出现逐路径
    记录 —— 于是"能写"来自那张白名单，不是从别的口漏进去的。这条同时钉住"没登记的
    格仍然被拒"这条路不许退化成永远不触发。
    """
    st, b = _manuscript_workspace(tmp_path / "ok")
    got = b.register_statement(statement_full="", proof_manuscript=REL1)
    assert got.get("ok") is True, got
    sid = str(got.get("stmt_id") or "")
    assert _row(st, sid).get("manuscripts") == {"1": REL1}, _row(st, sid).get("manuscripts")

    st2, b2 = _manuscript_workspace(tmp_path / "red")
    #: 白名单是一格一个元组（`{op: (允许改的键, ...)}`）⇒ 拿掉的是元组里那一项。
    allowed = tuple(one for one in SEC.STATEMENT_LAND_OPS["attach_proofs"]
                    if one != "manuscripts")
    assert len(allowed) == len(SEC.STATEMENT_LAND_OPS["attach_proofs"]) - 1, (
        "`manuscripts` 不在这一笔的白名单里 ⇒ 这条反真空没有可拿掉的东西")
    monkeypatch.setitem(SEC.STATEMENT_LAND_OPS, "attach_proofs", allowed)
    refused = b2.register_statement(statement_full="", proof_manuscript=REL1)
    assert refused.get("ok") is False, refused
    assert str(refused.get("refused") or "") == "statement_patch_key_not_allowed", refused
    assert dict(refused.get("write") or {}).get("written") is False, (
        "白名单拒了，回执却写着写过（整笔不写这条纪律被折掉了）：", refused.get("write"))
    landed = [dict(one) for one in st2.rows("statements")
              if dict(one.get("manuscripts") or {})]
    assert landed == [], (
        "白名单里没有这一格，盘上却写进去了 ⇒ 这条反真空量不到写面：", landed)
