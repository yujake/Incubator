# -*- coding: utf-8 -*-
"""未在册的 V 签要通知 F 的父代理（业主 2026-11-02 裁定）。

口径逐字（这一笔的唯一准绳）：

    未在册的签要送到 F 的父代理（派出 F 的那一方，通常是 M / D）

为什么这不是「B 没认领」的缺陷：签这一条时 B 根本还没有那条命题，无条目可认领。
正确的落点是 F 的父代理：让它知道「这份证明已经拿到 V 签」，从而可以据此推进
（派 B 收录、或继续下一跳）。B 之后收录时再从手稿签块里读到它。

## 四条判据（先红后绿；红的样子写在每一条的 docstring 里）

| # | 造什么 | 期望 |
|---|---|---|
| a | 未在册手稿 + 三转干净（真入口 `V.verify_proof`） | outbox 有一条回执，收件人 = F 的父 task_id、key 正确，且父代理的板上有这一项 |
| b | 同一份正文再签一次 | 不重复出条（同 sha 只有一条回执、板上只有一项） |
| c | F 的父 task_id 在台账里读不到 | 回执落「未送达」+ 原因；不静默丢、也不开板项 |
| d | 反真空：在册那条路（已有命题号） | 不该出这条回执（它走正常认领） |

外加交差读数的一格：`delivery_reading["notified_parent"]` 的三态（是 / 否 / 没查成）。

零模型调用：V 的审阅缝交出预置的干净结论（与三连判判据共用同一套替身）。
"""
from __future__ import annotations

import pathlib

import pytest
from agentflow import conductor as CND
from agentflow import depsection as _DS
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow import vreceipts as VRC
from agentflow.agent_f import vsign as FVS
from agentflow.agent_v import AgentV
from agentflow.conductor import Conductor
from agentflow.store import Store
from agentflow.tools.conductor_tools import conductor_for, reset_cache

from test_v_reviews_three_times_before_signing import CLEAN_REPLY, _ReviewSeam

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
#: 与 `agent_f/manuscript.py::proof_manuscript` 同一个形状（V 只读 `## 证明` 那一节）。
MANUSCRIPT = ("# F 的证明手稿：一致连续\n\n"
              "- 命题号：stmt:（还没落号）\n"
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              "1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
              "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。\n\n"
              "## 依赖\n\n"
              "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
#: 被签正文 = 手稿里「## 证明」那一节（与 `vsigns.ARTIFACT_SHA_RULE` 同一把尺）。
PROOF = _DS.proof_body(MANUSCRIPT).strip("\n")
SHA = VR.proof_sha(PROOF)
REL = "reports/f-proof-plan-0000.md"
#: 回执的幂等键前缀（业主裁定逐字：`v-sign-unregistered@<正文sha>@<父task_id>`）。
KEY_PREFIX = "v-sign-unregistered@"


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    """一个最小工作区：手稿在盘上，主控已存在（板项通道就位）。"""
    st = Store(tmp_path / "ws")
    st.init()
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MANUSCRIPT, encoding="utf-8")
    reset_cache()
    conductor_for(st)
    return st


def _agent_row(st: Store, *, role: str, parent: str, depth: int) -> str:
    """落一条代理行（`kind` 空：它不是板项，只是一趟活）。"""
    return Conductor._write_new_row(
        conductor_for(st), {
            "task_id": "", "role": role, "action": "", "called_by": "M",
            "parent_task_id": parent, "depth": depth,
            "input_key": f"@probe:{role}:{depth}:{parent}",
            "status": "done", "outcome": "ok", "refusal_reason": None,
            "instance": f"{role}#1", "detail": "夹具",
            "error": None, "started_at": "2026-11-02T16:00:00+08:00",
            "ended_at": "2026-11-02T16:50:00+08:00",
            "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        }, note="probe:agent")


def _sign_via_v(st: Store, *, f_task: str) -> dict:
    """走 V 的真入口：`AgentV.verify_proof(proof_manuscript=...)`（未在册那一支）。

    V 由 F 派出 ⇒ `current_parent()` 是 F 的台账号；回执的收件人应当是 F 的父。
    """
    v = AgentV(st, workspace_root=st.root, llm=_ReviewSeam([CLEAN_REPLY]))
    with CND.calling_as("t-v-000001", "V", parent_task_id=f_task, parent_role="F"):
        return v.verify_proof(proof_manuscript=REL)


def _receipts(st: Store) -> list[dict]:
    """outbox 里这一档的全部行（按写入顺序）。"""
    rows, _problems = VRC._read(st.root)
    return [dict(r) for r in rows
            if str(r.get("key") or "").startswith(KEY_PREFIX)]


def _board_items(st: Store) -> list[dict]:
    """板上这一档的项。"""
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith(KEY_PREFIX)]


def _f_reading(st: Store, *, parent: str) -> dict:
    """F 的交差读数（F 这一趟的召唤者是 `parent`）。"""
    with CND.calling_as("t-f-000001", "F", parent_task_id=parent, parent_role="M"):
        return FVS.delivery_reading(st.root, proof_text=PROOF,
                                    manuscript_paths=(REL,))


# ============================================================ a 回执送到父代理
def test_a_an_unregistered_sign_sends_one_receipt_to_fs_parent(tmp_path):
    """a 未在册手稿 + 三转干净 ⇒ outbox 一条回执，收件人 = F 的父 task_id。

    改前红：`unregistered_sign_reading` 不存在，且这条路上一个字节都不写 outbox
    —— 签只盖回手稿，派出 F 的那一方（M / D）永远不知道这份证明已经签了。
    """
    st = _ws(tmp_path)
    m_task = _agent_row(st, role="M", parent="t-000000", depth=1)
    f_task = _agent_row(st, role="F", parent=m_task, depth=2)

    got = _sign_via_v(st, f_task=f_task)
    assert got.get("checked") is True, got
    assert got.get("kind") == "proof_unregistered_signed", got

    want_key = f"{KEY_PREFIX}{SHA}@{m_task}"
    reading = VRC.unregistered_sign_reading(st.root, proof_sha=SHA,
                                            parent_task_id=m_task)
    assert reading["checked"] is True, reading
    assert reading["state"] == "delivered", reading
    assert reading["label"] == "送达", reading
    assert reading["key"] == want_key, reading
    assert reading["recipient"] == m_task, reading
    rows = list(reading.get("rows") or [])
    assert len(rows) == 1, rows
    row = rows[0]
    # 内容五格：签在哪个手稿、sha、判词、streak、谁签的。
    assert row["manuscript"] == REL, row
    assert row["proof_sha256"] == SHA, row
    assert row["verdict"] == "成立", row
    assert (row["streak"], row["need"]) == (3, 3), row
    assert row["signer"] == "agent-V", row
    assert row["state"] == VRC.DISPATCHED, row

    # 父代理那一侧：板上真的有一项（走既有通道，不新造）。
    items = _board_items(st)
    assert len(items) == 1, items
    item = items[0]
    assert str(item.get("input_key")) == want_key, item
    assert str(item.get("parent_task_id")) == m_task, item
    assert str(item.get("role")) == "M", item
    assert str(item.get("kind")) == "notice", item
    detail = str(item.get("detail") or "")
    for needed in (REL, SHA, "成立", "3/3", "agent-V"):
        assert needed in detail, (needed, detail)


# ============================================================ b 同一 sha 不重复
def test_b_the_same_body_is_not_notified_twice(tmp_path):
    """b 同一份正文再签 ⇒ 只有一条回执、板上只有一项。

    改前红：这一档根本没有回执；而一个只按"签了一次"就写的实现会在这里出两条。
    """
    st = _ws(tmp_path)
    m_task = _agent_row(st, role="M", parent="t-000000", depth=1)
    f_task = _agent_row(st, role="F", parent=m_task, depth=2)

    first = _sign_via_v(st, f_task=f_task)
    assert first.get("checked") is True, first
    reading1 = VRC.unregistered_sign_reading(st.root, proof_sha=SHA)
    assert len(reading1.get("rows") or []) == 1, reading1

    # 再走一次真入口：同一份正文已经有签块 ⇒ 不重复审、也不重复通知。
    again = _sign_via_v(st, f_task=f_task)
    assert again.get("checked") is True, again
    assert "不重复" in str(again.get("reason") or ""), again

    # 再直接盖一次同一块（生产的写口，幂等那一支）：仍然不许出第二条。
    stamped = VS.write_manuscript_sign(
        st.root, REL, proof_sha=SHA, streak=3, need=3, verdict="成立",
        signer="agent-V", at="2026-11-02T16:42:13+08:00",
        ledger=f"{REL}#V签", statement_id="", signed=True, store=st)
    assert stamped["written"] is True and stamped["idempotent"] is True, stamped

    reading2 = VRC.unregistered_sign_reading(st.root, proof_sha=SHA)
    assert len(reading2.get("rows") or []) == 1, reading2
    assert reading2["key"] == reading1["key"], reading2
    assert len(_receipts(st)) == 1, _receipts(st)
    assert len(_board_items(st)) == 1, _board_items(st)


# ============================================================ c 父 task 读不到
def test_c_an_unreadable_parent_is_recorded_as_undelivered(tmp_path):
    """c F 的父 task_id 在台账里没有那一行 ⇒ 回执落「未送达」+ 原因。

    改前红：这条路上连 outbox 都没有；而把「读不到收件人」静默折成「投过了」
    是本仓最忌的形态，所以这里同时断言板上没有项。
    """
    st = _ws(tmp_path)
    ghost = "t-000404"
    f_task = _agent_row(st, role="F", parent=ghost, depth=2)

    got = _sign_via_v(st, f_task=f_task)
    assert got.get("checked") is True, got
    assert got.get("kind") == "proof_unregistered_signed", got

    reading = VRC.unregistered_sign_reading(st.root, proof_sha=SHA,
                                            parent_task_id=ghost)
    assert reading["checked"] is True, reading
    assert reading["state"] == "undelivered", reading
    assert reading["label"] == "未送达", reading
    reason = str(reading.get("reason") or "")
    assert ghost in reason and "没有那一行" in reason, reason
    rows = list(reading.get("rows") or [])
    assert len(rows) == 1, rows
    assert rows[0]["state"] == VRC.UNDELIVERED, rows[0]
    assert str(rows[0].get("reason") or ""), rows[0]
    assert _board_items(st) == [], "收件人读不到却开出了板项 ⇒ 这一条是猜的"

    # F 的读数：签有了，但父代理没收到 ⇒ `notified_parent` 是「否」（带原因）。
    fr = _f_reading(st, parent=ghost)
    assert fr["state"] == FVS.STATE_SIGNED, fr
    cell = fr["notified_parent"]
    assert cell["label"] == "否", cell
    assert cell["checked"] is True, cell
    assert "没有那一行" in str(cell.get("reason") or ""), cell


# ============================================================ d 反真空：在册路
def test_d_the_registered_path_does_not_emit_this_receipt(tmp_path):
    """d 在册那条路（已有命题号）不该出这条回执 —— 它走的是正常认领。

    这一条同时是反真空：签真的发了、块真的盖进手稿（`written` / `state=written`），
    若判据只是「什么都别写」就能绿，那它量的不是「在册路不通知」。
    """
    st = _ws(tmp_path)
    got = VS.write_sign(
        st.root, artifact_sha=SHA, streak=3, need=3, artifact_path=REL,
        ledger="verifications/000001.jsonl#v-000001", statement_id="000001",
        proof_no=1, at="2026-11-02T10:00:00+08:00")
    assert got["written"] is True, got
    assert got["manuscript_write"]["state"] == "written", got["manuscript_write"]
    assert got["manuscript_write"]["notification"]["state"] == "not_applicable", (
        got["manuscript_write"])

    reading = VRC.unregistered_sign_reading(st.root, proof_sha=SHA)
    assert reading["checked"] is True, reading
    assert reading["found"] is False, reading
    assert reading["state"] == "none", reading
    assert (reading.get("rows") or []) == [], reading
    assert _receipts(st) == [], _receipts(st)
    assert _board_items(st) == [], _board_items(st)


# ============================================================ 交差读数那一格
def test_notified_parent_says_yes_after_the_receipt_is_delivered(tmp_path):
    """`notified_parent` = 是：父代理的板上有这一条回执（收件人就是它）。"""
    st = _ws(tmp_path)
    m_task = _agent_row(st, role="M", parent="t-000000", depth=1)
    f_task = _agent_row(st, role="F", parent=m_task, depth=2)
    _sign_via_v(st, f_task=f_task)

    reading = _f_reading(st, parent=m_task)
    assert reading["state"] == FVS.STATE_SIGNED, reading
    cell = reading["notified_parent"]
    assert cell["checked"] is True, cell
    assert cell["state"] == "yes", cell
    assert cell["label"] == "是", cell
    assert cell["recipient"] == m_task, cell
    assert cell["key"] == f"{KEY_PREFIX}{SHA}@{m_task}", cell


def test_notified_parent_says_no_when_no_receipt_exists(tmp_path):
    """`notified_parent` = 否：还没签、也就没有回执（不是「没查成」）。"""
    st = _ws(tmp_path)
    m_task = _agent_row(st, role="M", parent="t-000000", depth=1)
    _agent_row(st, role="F", parent=m_task, depth=2)

    reading = _f_reading(st, parent=m_task)
    assert reading["state"] == FVS.STATE_WAITING, reading
    cell = reading["notified_parent"]
    assert cell["checked"] is True, cell
    assert cell["state"] == "no", cell
    assert cell["label"] == "否", cell


def test_notified_parent_is_unknown_without_a_calling_context(tmp_path):
    """`notified_parent` = 没查成：没有召唤者就读不到父代理（不折成「否」）。"""
    st = _ws(tmp_path)
    reading = FVS.delivery_reading(st.root, proof_text=PROOF,
                                   manuscript_paths=(REL,))
    cell = reading["notified_parent"]
    assert cell["checked"] is False, cell
    assert cell["state"] == "unknown", cell
    assert cell["label"] == "没查成", cell
    assert str(cell.get("reason") or ""), cell
